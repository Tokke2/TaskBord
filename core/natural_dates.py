# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""
natural_dates.py — naturliga datum på svenska, utan Qt.

Överallt där ett förfallodatum skrivs för hand förstås t.ex.:

    fre 14 · fredag · nästa mån · nästa fredag · om 3 dagar · om en vecka · om 2 månader · nästa vecka
    nästa månad · 15 nov · 15 november 2026 · vecka 47 · slutet av månaden · idag · imorgon · övermorgon
    ÅÅÅÅ-MM-DD · ÅÅMMDD · d/m · d/m-ÅÅ

* ``parse_date(text, today)``      — hela texten är ett datum → ``date`` eller None.
* ``parse_datetime(text, today)``  — som ovan + valfritt klockslag ("fre 14 kl 15", "imorgon 9:30") → ``(date, "HH:MM"|None)``.
* ``find_in_text(text, today)``    — hittar ett TYDLIGT datumuttryck inuti en längre text (en uppgiftstitel) →
  ``(date, start, end)`` eller None. Försiktigare än ``parse_date``: ett ensamt tal eller en ensam förkortning
  ("mån", "14") tolkas aldrig som datum inne i en titel.

Tolkningar som kan vara tvetydiga (dokumenterade i MANUAL):
* ``fre 14`` = närmaste fredag som också är den 14:e (hittas ingen inom tre månader → närmaste den 14:e).
* ``fredag`` = närmaste fredag (idag räknas); ``nästa fredag`` = närmaste fredag EFTER idag.
* ``nästa vecka`` = måndag nästa vecka; ``nästa månad`` = den 1:a nästa månad.
* ``14`` (bara ett tal) = närmaste den 14:e (idag räknas).
"""
from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Optional, Tuple

_WD_FULL = {"måndag": 0, "tisdag": 1, "onsdag": 2, "torsdag": 3, "fredag": 4, "lördag": 5, "söndag": 6,
            "mandag": 0, "lordag": 5, "sondag": 6}
_WD_ABBR = {"mån": 0, "tis": 1, "ons": 2, "tors": 3, "tor": 3, "fre": 4, "lör": 5, "sön": 6}
_WD_ALL = {**_WD_FULL, **_WD_ABBR}

_MONTHS = {"januari": 1, "februari": 2, "mars": 3, "april": 4, "maj": 5, "juni": 6, "juli": 7, "augusti": 8,
           "september": 9, "oktober": 10, "november": 11, "december": 12,
           "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
           "okt": 10, "nov": 11, "dec": 12}

_NUM_WORDS = {"en": 1, "ett": 1, "två": 2, "tva": 2, "tre": 3, "fyra": 4, "fem": 5, "sex": 6, "sju": 7,
              "åtta": 8, "atta": 8, "nio": 9, "tio": 10, "elva": 11, "tolv": 12}

_NUM = r"\d{1,3}|" + "|".join(sorted(_NUM_WORDS, key=len, reverse=True))
_WD_RX = "|".join(sorted(_WD_ALL, key=len, reverse=True))
_WD_FULL_RX = "|".join(sorted(_WD_FULL, key=len, reverse=True))
_MON_RX = "|".join(sorted(_MONTHS, key=len, reverse=True))
_FILLER = re.compile(r"^(?:senast|till|på|pa|den|i|på\s+den|till\s+och\s+med)\s+", re.I)


def add_months(d: date, n: int) -> date:
    """Lägg till n månader (dagen kläms till månadens sista om den inte finns)."""
    m0 = d.month - 1 + n
    y, m = d.year + m0 // 12, m0 % 12 + 1
    return date(y, m, min(d.day, monthrange(y, m)[1]))


def next_weekday(today: date, wd: int, after: bool = False) -> date:
    delta = (wd - today.weekday()) % 7
    if after and delta == 0:
        delta = 7
    return today + timedelta(days=delta)


def _num(tok: str) -> int:
    tok = tok.lower()
    return int(tok) if tok.isdigit() else _NUM_WORDS[tok]


def _safe(y: int, m: int, d: int) -> Optional[date]:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _weekday_dom(wd: int, dom: int, today: date) -> Optional[date]:
    """Närmaste datum ≥ idag som är en viss veckodag OCH den dom:e (annars bara närmaste dom:e)."""
    first_any: Optional[date] = _dom_only(dom, today)
    y, m = today.year, today.month
    for _ in range(4):
        c = _safe(y, m, dom)
        if c is not None and c >= today:
            if first_any is None:
                first_any = c
            if c.weekday() == wd:
                return c
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return first_any


def _dom_only(dom: int, today: date) -> Optional[date]:
    y, m = today.year, today.month
    for _ in range(14):
        c = _safe(y, m, dom)
        if c is not None and c >= today:
            return c
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return None


def _day_month(dom: int, mon: int, year: Optional[int], today: date) -> Optional[date]:
    if year is not None:
        year = year + 2000 if year < 100 else year
        return _safe(year, mon, dom)
    c = _safe(today.year, mon, dom)
    if c is None:
        return None
    if c < today:
        c = _safe(today.year + 1, mon, dom)
    return c


def _compact(tok: str, today: date) -> Optional[date]:
    if len(tok) == 6:
        yr, mo, da = 2000 + int(tok[0:2]), int(tok[2:4]), int(tok[4:6])
    else:
        yr, mo, da = int(tok[0:4]), int(tok[4:6]), int(tok[6:8])
    if not (today.year - 1 <= yr <= today.year + 20):
        return None
    return _safe(yr, mo, da)


def _iso_week_monday(week: int, today: date) -> Optional[date]:
    if not 1 <= week <= 53:
        return None
    for yr in (today.year, today.year + 1):
        try:
            mon = date.fromisocalendar(yr, week, 1)
        except ValueError:
            continue
        if mon + timedelta(days=6) >= today:
            return mon
    return None


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower()).strip(" .,;")


def parse_date(text: str, today: Optional[date] = None) -> Optional[date]:
    """Hela texten är ett datumuttryck → datum, annars None."""
    today = today or date.today()
    e = _norm(text)
    if not e:
        return None
    simple = {"idag": 0, "i dag": 0, "imorgon": 1, "i morgon": 1, "övermorgon": 2, "i övermorgon": 2,
              "overmorgon": 2, "igår": -1, "i går": -1, "igar": -1}
    if e in simple:
        return today + timedelta(days=simple[e])
    e = _FILLER.sub("", e).strip()

    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", e)
    if m:
        return _safe(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if re.fullmatch(r"\d{6}|\d{8}", e):
        return _compact(e, today)
    m = re.fullmatch(r"(?:(?:" + _WD_RX + r")\s+)?(\d{1,2})[/.](\d{1,2})(?:[/.-](\d{2,4}))?", e)
    if m:
        return _day_month(int(m.group(1)), int(m.group(2)), int(m.group(3)) if m.group(3) else None, today)

    if e in ("nästa vecka", "nasta vecka", "nästa v", "nästkommande vecka"):
        return today + timedelta(days=7 - today.weekday())
    if e in ("nästa månad", "nasta manad", "nästkommande månad"):
        return add_months(today.replace(day=1), 1)
    if e in ("slutet av månaden", "slutet av manaden", "månadsskiftet", "månadsskifte", "månadsslut",
             "sista dagen i månaden", "sista i månaden", "månadens slut"):
        return today.replace(day=monthrange(today.year, today.month)[1])
    if e in ("nästa år", "nasta ar"):
        return _safe(today.year + 1, 1, 1)

    m = re.fullmatch(r"nästa\s+(" + _WD_RX + r")", e)
    if m:
        return next_weekday(today, _WD_ALL[m.group(1)], after=True)
    m = re.fullmatch(r"(" + _WD_RX + r")(?:\s+nästa\s+vecka)?", e)
    if m:
        wd = _WD_ALL[m.group(1)]
        if "nästa vecka" in e:
            return today + timedelta(days=7 - today.weekday() + wd)
        return next_weekday(today, wd)
    m = re.fullmatch(r"(" + _WD_RX + r")\s+(\d{1,2})", e)
    if m:
        dom = int(m.group(2))
        if 1 <= dom <= 31:
            return _weekday_dom(_WD_ALL[m.group(1)], dom, today)
        return None
    m = re.fullmatch(r"om\s+(" + _NUM + r")\s+(dagar|dag|veckor|vecka|månader|månad|manader|manad)", e)
    if m:
        n, unit = _num(m.group(1)), m.group(2)
        if unit.startswith("d"):
            return today + timedelta(days=n)
        if unit.startswith("v"):
            return today + timedelta(days=7 * n)
        return add_months(today, n)
    m = re.fullmatch(r"(\d{1,2})(?::a|:e|e|a)?\s+(" + _MON_RX + r")(?:\s+(\d{4}|\d{2}))?", e)
    if m:
        return _day_month(int(m.group(1)), _MONTHS[m.group(2)], int(m.group(3)) if m.group(3) else None, today)
    m = re.fullmatch(r"(" + _MON_RX + r")\s+(\d{1,2})(?:\s+(\d{4}))?", e)
    if m:
        return _day_month(int(m.group(2)), _MONTHS[m.group(1)], int(m.group(3)) if m.group(3) else None, today)
    m = re.fullmatch(r"(?:v|vecka|vk)\.?\s*(\d{1,2})", e)
    if m:
        return _iso_week_monday(int(m.group(1)), today)
    m = re.fullmatch(r"(\d{1,2})(?::a|:e)?", e)
    if m and 1 <= int(m.group(1)) <= 31:
        return _dom_only(int(m.group(1)), today)
    return None


_TIME_TAIL = re.compile(
    r"\s*(?:kl(?:ockan)?\.?\s*)?(\d{1,2})(?:[:.]([0-5]\d))?\s*$", re.I)


def parse_datetime(text: str, today: Optional[date] = None) -> Tuple[Optional[date], Optional[str]]:
    """'fre 14 kl 15', 'imorgon 9:30', '2026-11-30 15.30' → (datum, 'HH:MM') — (None, None) om datumet inte förstås."""
    today = today or date.today()
    s = _norm(text)
    d = parse_date(s, today)
    if d is not None:
        return d, None
    # klockslag sist: "kl 15", "15:30", "15.30"; ett blott tal efter ett datum räknas bara med "kl"
    m = _TIME_TAIL.search(s)
    if m:
        has_kl = bool(re.search(r"\bkl", m.group(0), re.I))
        has_min = m.group(2) is not None
        hh = int(m.group(1))
        if (has_kl or has_min) and 0 <= hh <= 23:
            rest = s[:m.start()].strip()
            d = parse_date(rest, today)
            if d is not None:
                return d, f"{hh:02d}:{int(m.group(2) or 0):02d}"
    return None, None


# --------------------------------------------------------------------------- inne i en titel
_EMBED = [
    # (regex, handler(match, today))
    (re.compile(r"(?<!\w)nästa\s+(?:" + _WD_RX + r")(?![\wåäö])", re.I), None),
    (re.compile(r"(?<!\w)nästa\s+(?:vecka|månad)(?![\wåäö])", re.I), None),
    (re.compile(r"(?<!\w)om\s+(?:" + _NUM + r")\s+(?:dagar|dag|veckor|vecka|månader|månad)(?![\wåäö])", re.I), None),
    (re.compile(r"(?<!\w)(?:slutet\s+av\s+månaden|månadsskiftet|månadsskifte|månadsslut)(?![\wåäö])", re.I), None),
    (re.compile(r"(?<!\w)(?:" + _WD_RX + r")\s+\d{1,2}(?![\d:.,/\-]\d)(?![\d:/])(?![\wåäö])", re.I), None),
    (re.compile(r"(?<!\w)\d{1,2}\s+(?:" + _MON_RX + r")(?:\s+\d{4})?(?![\wåäö])", re.I), None),
    (re.compile(r"(?<!\w)vecka\s+\d{1,2}(?![\d:.,/\-]\d)(?![\d:/])", re.I), None),
]


def find_in_text(text: str, today: Optional[date] = None) -> Optional[Tuple[date, int, int]]:
    """Första tydliga datumuttrycket inne i en längre text → (datum, start, slut). Förkortade veckodagar
    ('mån', 'fre') räknas bara tillsammans med ett datum ('fre 14') eller efter 'nästa'."""
    today = today or date.today()
    s = str(text or "")
    best: Optional[Tuple[date, int, int]] = None
    for rx, _h in _EMBED:
        for m in rx.finditer(s):
            frag = m.group(0)
            # "fre 14" men inte "fredag 15" (= fredag kl 15 i uppgiftsinmatningen)
            if re.match(r"(?:" + _WD_FULL_RX + r")\s+\d", frag, re.I) and not frag.lower().startswith("nästa"):
                continue
            d = parse_date(frag, today)
            if d is None:
                continue
            if best is None or m.start() < best[1]:
                best = (d, m.start(), m.end())
            break
    return best


def describe(d: date, today: Optional[date] = None) -> str:
    """Kort svensk text för bekräftelsen i dialogen: 'fredag 14 november 2026 (om 3 dagar)'."""
    today = today or date.today()
    wd = ("måndag", "tisdag", "onsdag", "torsdag", "fredag", "lördag", "söndag")[d.weekday()]
    mon = ("januari", "februari", "mars", "april", "maj", "juni", "juli", "augusti", "september",
           "oktober", "november", "december")[d.month - 1]
    delta = (d - today).days
    rel = ("idag" if delta == 0 else "imorgon" if delta == 1 else "igår" if delta == -1
           else f"om {delta} dagar" if delta > 0 else f"{-delta} dagar sedan")
    return f"{wd} {d.day} {mon} {d.year} ({rel})"
