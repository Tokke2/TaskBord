# -*- coding: utf-8 -*-
"""
reminder_logic.py — ren logik (utan Qt) för påminnelser: vilka uppgifter är försenade / förfaller idag?

Används av påminnelsepopupen (ui/reminder_popup.py), tray-ikonens siffra och app/mixins/reminders.py.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

OVERDUE = "overdue"
TODAY = "today"


def classify(task: Dict[str, Any], now: Optional[datetime] = None) -> Optional[Tuple[str, int]]:
    """
    ("overdue", dagar_sen) / ("today", 0) för en aktiv uppgift med förfallodatum idag eller tidigare.
    None för klara, datumlösa, framtida och senarelagda (snoozed) uppgifter.
    """
    now = now or datetime.now()
    try:
        if not task.get("id") or task.get("done"):
            return None
        due = task.get("due_date")
        if not due:
            return None
        sn = task.get("snoozed_until")
        if sn:
            try:
                if datetime.fromisoformat(str(sn)) > now:
                    return None
            except (ValueError, TypeError):
                pass
        d = datetime.fromisoformat(str(due)[:19]).date() if len(str(due)) > 10 else date.fromisoformat(str(due)[:10])
    except (ValueError, TypeError):
        return None
    delta = (now.date() - d).days
    if delta > 0:
        return (OVERDUE, delta)
    if delta == 0:
        return (TODAY, 0)
    return None


def due_items(tasks: Iterable[Dict[str, Any]], now: Optional[datetime] = None) -> List[Tuple[Dict[str, Any], str, int]]:
    """[(uppgift, kind, dagar)] — försenade först (mest försenade först), sedan dagens."""
    out = []
    for t in tasks:
        c = classify(t, now)
        if c:
            out.append((t, c[0], c[1]))
    out.sort(key=lambda x: (0 if x[1] == OVERDUE else 1, -x[2], str(x[0].get("title", "")).lower()))
    return out


def count_due(tasks: Iterable[Dict[str, Any]], now: Optional[datetime] = None) -> Tuple[int, int]:
    """(antal försenade, antal som förfaller idag)."""
    items = due_items(tasks, now)
    return (sum(1 for _, k, _ in items if k == OVERDUE), sum(1 for _, k, _ in items if k == TODAY))


def status_text(kind: str, days: int) -> str:
    """Kort svensk text: 'förfaller idag' / 'försenad 1 dag' / 'försenad 3 dagar'."""
    if kind == TODAY:
        return "förfaller idag"
    return f"försenad {days} dag" if days == 1 else f"försenad {days} dagar"


def badge_text(n: int) -> str:
    """Siffran på tray-ikonen ('' = ingen siffra)."""
    if n <= 0:
        return ""
    return str(n) if n < 10 else "9+"
