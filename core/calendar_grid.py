# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""
calendar_grid.py — månadsrutnät och belastning per dag för kalendervyn. Ren stdlib (testas utan Qt).

* ``month_grid(år, månad)`` — veckor måndag–söndag, med dagar från grannmånaderna som utfyllnad.
* ``tasks_by_day(uppgifter)`` — {datum: [{"task", "kind"}]}; kind = "due" (förfallodag) eller
  "remind" (extra påminnelsedatum ur importerade mail). En uppgift räknas högst en gång per dag.
* ``heat(n)`` — 0–4: hur "tung" dagen är (färgskala i vyn; antalet visas alltid som siffra också,
  så färgen aldrig är det enda sättet att läsa av dagen).
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from core import holidays_se, reminder_logic

WEEKDAYS_SHORT = ("mån", "tis", "ons", "tors", "fre", "lör", "sön")
MONTH_NAMES = holidays_se.MONTHS

# antal uppgifter per dag → nivå 0..4
_HEAT_STEPS = (1, 2, 4, 6)


def month_title(year: int, month: int) -> str:
    return f"{MONTH_NAMES[month - 1]} {year}"


def shift_month(year: int, month: int, delta: int) -> Tuple[int, int]:
    idx = year * 12 + (month - 1) + delta
    y, m0 = divmod(idx, 12)
    return y, m0 + 1


def month_grid(year: int, month: int) -> List[List[date]]:
    """Veckor (mån–sön) som täcker hela månaden — 4 till 6 rader om 7 dagar."""
    first = date(year, month, 1)
    start = first - timedelta(days=first.weekday())
    last = date(year, month, calendar.monthrange(year, month)[1])
    weeks: List[List[date]] = []
    d = start
    while d <= last:
        weeks.append([d + timedelta(days=i) for i in range(7)])
        d += timedelta(days=7)
    return weeks


def heat(n: int) -> int:
    """0 = ledig, 1 = 1 uppgift, 2 = 2–3, 3 = 4–5, 4 = 6 eller fler."""
    level = 0
    for i, step in enumerate(_HEAT_STEPS, start=1):
        if n >= step:
            level = i
    return level


def tasks_by_day(tasks: Iterable[Dict[str, Any]], include_remind: bool = True,
                 include_done: bool = False) -> Dict[date, List[Dict[str, Any]]]:
    """Gruppera uppgifter per dag. Klara uppgifter hoppas över om inte ``include_done``."""
    out: Dict[date, List[Dict[str, Any]]] = {}
    for t in tasks:
        if not isinstance(t, dict) or (t.get("done") and not include_done):
            continue
        seen: set = set()
        due = reminder_logic._day(t.get("due_date"))
        if due is not None:
            out.setdefault(due, []).append({"task": t, "kind": "due"})
            seen.add(due)
        if include_remind:
            for d in reminder_logic.remind_days(t):
                if d not in seen:
                    out.setdefault(d, []).append({"task": t, "kind": "remind"})
                    seen.add(d)
    prio = {"high": 0, "medium": 1, "low": 2, "none": 3}
    for lst in out.values():
        lst.sort(key=lambda e: (e["kind"] != "due", prio.get(str(e["task"].get("priority")), 3),
                                str(e["task"].get("title") or "").lower()))
    return out


def day_info(d: date) -> Dict[str, Any]:
    """Veckodag/röd dag för en cell: {"red": bool, "holiday": str|"", "weekend": bool}."""
    h = holidays_se.holiday_on(d)
    weekend = d.weekday() >= 5
    return {"red": weekend and d.weekday() == 6 or h is not None, "holiday": h[0] if h else "", "weekend": weekend}


def iso_week(d: date) -> int:
    return d.isocalendar()[1]


def busiest(by_day: Dict[date, List[Any]], year: int, month: int) -> Optional[Tuple[date, int]]:
    """Månadens tyngsta dag (datum, antal) eller None om månaden är tom."""
    best: Optional[Tuple[date, int]] = None
    for d, lst in by_day.items():
        if d.year == year and d.month == month and lst:
            if best is None or len(lst) > best[1] or (len(lst) == best[1] and d < best[0]):
                best = (d, len(lst))
    return best


def month_total(by_day: Dict[date, List[Any]], year: int, month: int) -> int:
    return sum(len(v) for d, v in by_day.items() if d.year == year and d.month == month)
