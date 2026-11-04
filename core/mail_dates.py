# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""
mail_dates.py — datum i importerade mail → påminnelser.

Står det ett datum i mailet ("Betalning 2  15/11") eller en månad ("… i november 2/3 … december 3/3") läggs en
påminnelse på det datumet (popup-kortet på skärmen, samma som för förfallodatum). Alla datum sparas på uppgiften:

    remind_dates : ["2026-11-15", "2026-12-15"]            (sorterad, bara kommande)
    remind_info  : {"2026-11-15": "Betalning 2 15/11", …}   (raden i mailet — visas på påminnelsekortet)

och har uppgiften inget förfallodatum får den det tidigaste (väljer användaren ett eget datum i Thunderbird vinner det).

Igenkänt:  15/11   15/11-2026   15/11/26   2026-11-15   15.11.2026   15 november   15:e november   15 nov
           november 15   samt enbart månadsnamn ("i november", "december")
Månadsnamn utan dag ("i november", "december"): månadens FÖRSTA VARDAG (måndag–fredag, ej röd dag). Är månaden redan
igång och den dagen passerad: idag.
Ignoreras: "2/3" direkt efter ett månadsnamn ("november 2/3" = betalning 2 av 3, inte 2 mars), "1 av 3",
klockslag, belopp, citerade rader (> …) och datum som redan passerat. Årslösa datum hamnar i år; ligger de mer än
5 månader bakåt tolkas de som nästa år.
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

MAX_SCAN_CHARS = 20_000
MAX_DATES = 12
MAX_SNIPPET = 90
HORIZON_DAYS = 800

_MONTHS = {
    "januari": 1, "februari": 2, "mars": 3, "april": 4, "maj": 5, "juni": 6, "juli": 7,
    "augusti": 8, "september": 9, "oktober": 10, "november": 11, "december": 12,
}
_ABBR = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9, "okt": 10, "nov": 11, "dec": 12}
_FULL = "|".join(sorted(_MONTHS, key=len, reverse=True))
_ABBR_RX = "|".join(sorted(_ABBR, key=len, reverse=True))

_RX_ISO = re.compile(r"(?<![\d-])(20\d\d)-(\d\d)-(\d\d)(?![\d])")
_RX_DMY_DOT = re.compile(r"(?<![\d.])(\d{1,2})\.(\d{1,2})\.(20\d\d|\d\d)(?![\d])")
_RX_NUM = re.compile(r"(?<![\d/.,:-])(\d{1,2})/(\d{1,2})(?:[/-](20\d\d|\d\d))?(?![\d/])")
_RX_DAY_MONTH = re.compile(rf"(?<!\d)(\d{{1,2}})(?::e|:a|e)?\s+({_FULL}|{_ABBR_RX})\b\.?(?:\s+(20\d\d))?", re.I)
_RX_MONTH_DAY = re.compile(rf"\b({_FULL})\s+(\d{{1,2}})(?![\d/:.,])", re.I)
_RX_BARE = re.compile(rf"\b({_FULL})\b", re.I)
_RX_ENDS_MONTH = re.compile(rf"(?:{_FULL})\s*$", re.I)


def _mk(y: int, m: int, d: int) -> Optional[date]:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _year(y_raw: Optional[str]) -> Optional[int]:
    if not y_raw:
        return None
    y = int(y_raw)
    return y + 2000 if y < 100 else y


def _resolve(m: int, d: int, y: Optional[int], today: date) -> Optional[date]:
    """Årslöst datum → nästa passande år. None om det redan passerat."""
    if y is not None:
        return _mk(y, m, d)
    cand = _mk(today.year, m, d)
    if cand is None:
        return None
    if cand < today - timedelta(days=150):
        cand = _mk(today.year + 1, m, d)
    return cand


def first_weekday(year: int, month: int) -> date:
    """Månadens första vardag: måndag–fredag som inte är en röd dag (t.ex. 1 jan → 4 jan 2027)."""
    try:
        from core.holidays_se import holidays as _hol
        red = {d for d, (_n, is_red) in _hol(year).items() if is_red}
    except Exception:
        red = set()
    d = date(year, month, 1)
    while d.weekday() >= 5 or d in red:
        d += timedelta(days=1)
    return d


def _snippet(lines: List[str], idx: int, start: int = 99) -> str:
    """Raden med datumet. Är raden kort, eller börjar den med datumet, tas raden före med (rubriken, t.ex. 'Betalning 2')."""
    line = re.sub(r"\s+", " ", lines[idx]).strip()
    lead = len(lines[idx]) - len(lines[idx].lstrip())
    if len(line) < 20 or start - lead <= 1:
        for j in range(idx - 1, max(-1, idx - 4), -1):
            prev = re.sub(r"\s+", " ", lines[j]).strip()
            if prev and not prev.startswith(">"):
                if len(prev) <= 70:
                    line = f"{prev} · {line}"
                break
    return line if len(line) <= MAX_SNIPPET else line[:MAX_SNIPPET - 1] + "…"


def extract_dates(text: str, today: Optional[date] = None) -> List[Tuple[date, str]]:
    """[(datum, rad ur mailet)] — kommande datum i tidsordning, utan dubbletter (max MAX_DATES)."""
    today = today or date.today()
    lines = (text or "")[:MAX_SCAN_CHARS].splitlines()
    found: List[Tuple[date, str]] = []
    for idx, raw in enumerate(lines):
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith(">"):
            continue
        spans: List[Tuple[int, int, str, tuple]] = []   # (start, slut, typ, grupper)

        def free(a: int, b: int) -> bool:
            return all(b <= s or a >= e for s, e, _t, _g in spans)

        for m in _RX_ISO.finditer(line):
            spans.append((m.start(), m.end(), "ymd", (int(m.group(1)), int(m.group(2)), int(m.group(3)))))
        for m in _RX_DMY_DOT.finditer(line):
            if free(m.start(), m.end()):
                spans.append((m.start(), m.end(), "ymd", (_year(m.group(3)), int(m.group(2)), int(m.group(1)))))
        for m in _RX_NUM.finditer(line):
            if not free(m.start(), m.end()):
                continue
            if _RX_ENDS_MONTH.search(line[:m.start()]) and not m.group(3):
                continue                                # "november 2/3" = betalning 2 av 3
            spans.append((m.start(), m.end(), "ymd", (_year(m.group(3)), int(m.group(2)), int(m.group(1)))))
        for m in _RX_DAY_MONTH.finditer(line):
            if free(m.start(), m.end()):
                name = m.group(2).lower()
                mon = _MONTHS.get(name) or _ABBR.get(name)
                spans.append((m.start(), m.end(), "ymd", (_year(m.group(3)), mon, int(m.group(1)))))
        for m in _RX_MONTH_DAY.finditer(line):
            if free(m.start(), m.end()):
                spans.append((m.start(), m.end(), "ymd", (None, _MONTHS[m.group(1).lower()], int(m.group(2)))))
        for m in _RX_BARE.finditer(line):
            if free(m.start(), m.end()):
                spans.append((m.start(), m.end(), "month", (_MONTHS[m.group(1).lower()],)))
        spans.sort(key=lambda s: s[0])
        for _s, _e, kind, g in spans:
            _start = _s
            if kind == "ymd":
                y, mon, d = g
                dt = _mk(y, mon, d) if (y and y > 1000) else _resolve(mon, d, y, today)
            else:
                mon = g[0]
                base = _resolve(mon, 1, None, today)    # rätt år för månaden
                dt = first_weekday(base.year, mon) if base is not None else None
                if dt is not None and dt < today and (dt.year, dt.month) == (today.year, today.month):
                    dt = today                          # månaden är redan igång och dagen passerad → idag
            if dt is None or dt < today or (dt - today).days > HORIZON_DAYS:
                continue
            if any(dt == f[0] for f in found):
                continue
            found.append((dt, _snippet(lines, idx, _start)))
            if len(found) >= MAX_DATES:
                break
        if len(found) >= MAX_DATES:
            break
    found.sort(key=lambda x: x[0])
    return found


def apply_to_task(store: Any, task_id: str, subject: str, body: str, today: Optional[date] = None) -> List[str]:
    """
    Läser ämne + brödtext, sparar remind_dates/remind_info på uppgiften och sätter förfallodatum (om saknas).
    Returnerar de sparade datumen (ISO). Kraschar aldrig.
    """
    try:
        today = today or date.today()
        found = extract_dates(f"{subject or ''}\n{body or ''}", today)
        if not found or not task_id:
            return []
        iso = [d.isoformat() for d, _s in found]
        info: Dict[str, str] = {d.isoformat(): s for d, s in found}
        if hasattr(store, "set_task_metadata"):
            store.set_task_metadata(task_id, "remind_dates", iso)
            store.set_task_metadata(task_id, "remind_info", info)
        task = store.find_task(task_id) if hasattr(store, "find_task") else None
        if task is not None and not task.get("due_date") and hasattr(store, "set_due_date"):
            store.set_due_date(task_id, iso[0])
        logger.info(f"[MAILDATES] {task_id!r}: påminnelser {', '.join(iso)}")
        return iso
    except Exception as e:  # pragma: no cover
        logger.warning(f"[MAILDATES] kunde inte läsa datum: {e}")
        return []
