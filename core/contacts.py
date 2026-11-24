# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""
contacts.py — hitta telefonnummer och adresser i en uppgifts text (titel + anteckning) så att de blir klickbara.
Ren stdlib, ingen Qt, inga nätanrop.

* ``find_phones(text)``  → ``[{"text": "070-123 45 67", "tel": "+46701234567"}]`` (svenska format + internationella med +).
  Orgnr (556677-8899), personnummer, datum (2026-11-06), belopp och OCR-nummer räknas inte som telefonnummer.
* ``find_addresses(text)`` → ``[{"text": "Storgatan 12 B, 111 22 Stockholm"}]`` — gatunamn (…gatan, …vägen, …gränd, …torget …)
  med husnummer, valfritt följt av postnummer och ort.
* ``tel_url / sms_url / maps_url / directions_url`` bygger länkarna.
"""
from __future__ import annotations

import re
from typing import Dict, List
from urllib.parse import quote

MAX_PHONES = 3
MAX_ADDRESSES = 2
_SEPS = " \u00a0-"
_START_RE = re.compile(r"(?<![\w\-/,.+])(?:\+\d|00\d|0[1-9])")


def _walk(text: str, i: int, cap: int):
    """Läs siffror från i (en separator mellan siffror tillåts). Returnerar (siffror, slutindex, för_långt)."""
    n = len(text)
    j = i
    digits = ""
    end = i
    while j < n:
        c = text[j]
        if c.isdigit() and c.isascii():
            if len(digits) >= cap:
                # fler siffror direkt efter → för långt (OCR-nummer); efter en avgränsare är det ett nytt tal
                return digits, end, text[j - 1].isdigit()
            digits += c
            j += 1
            end = j
        elif c in _SEPS and j + 1 < n and text[j + 1].isdigit():
            j += 1
        else:
            break
    return digits, end, False


def _phone_at(text: str, start: int):
    """Försök läsa ett telefonnummer som börjar vid start. Returnerar (visningstext, tel, slut) eller None."""
    if text[start] == "+" or text.startswith("00", start):
        off = 1 if text[start] == "+" else 2
        digits, end, too_long = _walk(text, start + off, 15)
        if too_long:
            return None
        if digits.startswith("46"):
            rest = digits[2:]
            # "+46 (0)70-123 45 67": den överflödiga (0) hoppas över
            m = re.match(r"\s*\(0\)", text[start + off + 2:])
            if m and not rest:
                digits, end, too_long = _walk(text, start + off + 2 + m.end(), 9)
                rest = digits
                if too_long:
                    return None
            if rest.startswith("0"):
                rest = rest[1:]
            if not (7 <= len(rest) <= 9) or rest[0] == "0":
                return None
            if rest.startswith("7") and len(rest) != 9:
                return None
            return text[start:end].strip(), "+46" + rest, end
        if not (8 <= len(digits) <= 15) or digits[0] == "0":
            return None
        return text[start:end].strip(), "+" + digits, end
    digits, end, too_long = _walk(text, start, 10)
    if too_long:
        return None
    raw = text[start:end]
    if digits.startswith("07"):
        if len(digits) != 10:
            return None
    else:
        if not (8 <= len(digits) <= 10):
            return None
        if raw.isdigit():            # nollor och siffror utan avgränsare utanför mobilserien: troligen ett OCR-/fakturanummer
            return None
    if re.fullmatch(r"\d{6}-\d{4}|\d{8}-\d{4}", raw):  # personnummer
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}|\d{2}-\d{2}-\d{4}", raw):   # datum
        return None
    return raw.strip(), "+46" + digits[1:], end


def find_phones(text: str, limit: int = MAX_PHONES) -> List[Dict[str, str]]:
    s = str(text or "")
    out: List[Dict[str, str]] = []
    seen = set()
    pos = 0
    while pos < len(s) and len(out) < limit:
        m = _START_RE.search(s, pos)
        if not m:
            break
        got = _phone_at(s, m.start())
        if got is None:
            pos = m.start() + 1
            # hoppa förbi hela siffergruppen så att inte en svans (t.ex. "…11-06") testas som ett eget nummer
            while pos < len(s) and (s[pos].isdigit() or s[pos] in "-/."):
                pos += 1
            continue
        disp, tel, end = got
        if tel not in seen:
            seen.add(tel)
            out.append({"text": disp, "tel": tel})
        pos = max(end, m.start() + 1)
    return out


_SUFFIX = (r"(?:gatan|gata|vägen|väg|gränd|gränden|stigen|torget|torg|allén|backen|leden|stråket|platsen|plan|gården|"
           r"kajen|bron|ringen|parken|promenaden|terrassen|slingan|svängen|kroken|gången|kvarn|holmen|udden)")
_NAME = r"[A-ZÅÄÖÉ][a-zåäöéü]*"
_ADDR_RE = re.compile(
    r"(?<![\wåäöÅÄÖ])"
    r"(?P<street>(?:" + _NAME + r"\s)?" + _NAME + _SUFFIX + r")"
    r"\s+(?P<nr>\d{1,3}(?:-\d{1,3})?(?:\s?[A-Z]|[a-z])?)(?![\w\d])"
    r"(?P<post>,?\s+\d{3}\s?\d{2}\s+" + _NAME + r"(?:\s" + _NAME + r")?)?"
)


def find_addresses(text: str, limit: int = MAX_ADDRESSES) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    seen = set()
    for m in _ADDR_RE.finditer(str(text or "")):
        # "Storgatan 12 000 kr" är ett belopp, inte en adress
        tail = str(text)[m.end("nr"):m.end("nr") + 5]
        if re.match(r"\s\d{3}\b", tail) and not m.group("post"):
            continue
        t = " ".join(m.group(0).split())
        if t.lower() in seen:
            continue
        seen.add(t.lower())
        out.append({"text": t})
        if len(out) >= limit:
            break
    return out


def tel_url(tel: str) -> str:
    return "tel:" + re.sub(r"[^\d+]", "", str(tel))


def sms_url(tel: str) -> str:
    return "sms:" + re.sub(r"[^\d+]", "", str(tel))


def _query(address: str) -> str:
    a = " ".join(str(address or "").split())
    if not re.search(r"\b\d{3}\s?\d{2}\b", a):
        a += ", Sverige"
    return quote(a, safe="")


def maps_url(address: str) -> str:
    return "https://www.google.com/maps/search/?api=1&query=" + _query(address)


def directions_url(address: str) -> str:
    return "https://www.google.com/maps/dir/?api=1&destination=" + _query(address)
