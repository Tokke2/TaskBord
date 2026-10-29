# -*- coding: utf-8 -*-
"""
reminder_logic.py — ren logik (utan Qt) för påminnelser: vilka uppgifter är försenade / förfaller idag?

Används av påminnelsepopupen (ui/reminder_popup.py), tray-ikonens siffra och app/mixins/reminders.py.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

OVERDUE = "overdue"
TODAY = "today"

# Påminnelsetider på själva förfallodagen
MORNING_HOUR = 8            # första påminnelsen på morgonen (08:00)
REPEAT_MINUTES = 30         # därefter var 30:e minut …
DAY_END_HOUR = 18           # … tills händelsen — utan klockslag: tills 18:00


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


def event_time(task: Dict[str, Any]) -> Optional[Tuple[int, int]]:
    """(timme, minut) om förfallodatumet har ett klockslag ('2026-10-30T15:00'), annars None."""
    due = str(task.get("due_date") or "")
    if len(due) < 16 or due[10] not in "T ":
        return None
    try:
        hh, mm = int(due[11:13]), int(due[14:16])
    except ValueError:
        return None
    if 0 <= hh <= 23 and 0 <= mm <= 59 and (hh or mm):
        return (hh, mm)
    return None


def day_window(task: Dict[str, Any], now: datetime) -> Tuple[datetime, datetime]:
    """
    (start, slut) för påminnelserna på förfallodagen: från 08:00 var 30:e minut tills händelsen
    (klockslaget om det finns — annars 18:00). Ligger klockslaget före 08:00 börjar fönstret en timme före.
    """
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = day + timedelta(hours=MORNING_HOUR)
    et = event_time(task)
    end = day + (timedelta(hours=et[0], minutes=et[1]) if et else timedelta(hours=DAY_END_HOUR))
    if end <= start:
        start = max(day, end - timedelta(hours=1))
    return start, end


def reminder_due(task: Dict[str, Any], now: datetime, last_shown: Optional[datetime]) -> Optional[Tuple[str, int]]:
    """
    Ska uppgiften påminnas NU? → (kind, dagar) eller None.  ``last_shown`` = när den senast visades.

    * Försenad (tidigare dag): en gång per dag.
    * Förfaller idag: första påminnelsen kl 08:00 (eller direkt om appen startas senare), sedan var 30:e minut
      tills händelsen (klockslaget — annars 18:00); en sista exakt vid klockslaget. Startas appen efter att
      tiden gått visas den en gång.
    """
    c = classify(task, now)
    if c is None:
        return None
    kind, days = c
    if kind == OVERDUE:
        return c if (last_shown is None or last_shown.date() < now.date()) else None
    start, end = day_window(task, now)
    if now < start:
        return None
    if last_shown is None or last_shown.date() < now.date():
        return c                                   # första påminnelsen i dag
    if last_shown >= end:
        return None                                # redan påmint vid/efter händelsen
    if now >= end:
        return c                                   # sista påminnelsen vid händelsen
    if now - last_shown >= timedelta(minutes=REPEAT_MINUTES) - timedelta(seconds=30):
        return c
    return None


def detail_text(task: Dict[str, Any], kind: str, days: int, now: Optional[datetime] = None) -> str:
    """Raden under titeln på påminnelsekortet ('förfaller idag kl 15:00', 'tiden har passerat', 'försenad 2 dagar')."""
    now = now or datetime.now()
    if kind == TODAY:
        et = event_time(task)
        if not et:
            return "förfaller idag"
        hhmm = f"{et[0]:02d}:{et[1]:02d}"
        if now.hour * 60 + now.minute > et[0] * 60 + et[1]:
            return f"tiden har passerat (kl {hhmm})"
        return f"förfaller idag kl {hhmm}"
    return status_text(kind, days)


def status_text(kind: str, days: int) -> str:
    """Kort svensk text: 'förfaller idag' / 'försenad 1 dag' / 'försenad 3 dagar'."""
    if kind == TODAY:
        return "förfaller idag"
    if days <= 0:
        return "tiden har passerat"
    return f"försenad {days} dag" if days == 1 else f"försenad {days} dagar"


def badge_text(n: int) -> str:
    """Siffran på tray-ikonen ('' = ingen siffra)."""
    if n <= 0:
        return ""
    return str(n) if n < 10 else "9+"
