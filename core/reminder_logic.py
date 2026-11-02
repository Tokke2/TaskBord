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
REPEAT_MINUTES = 30         # därefter var 30:e minut … tills uppgiften markerats som klar
NIGHT_HOUR = 22             # nattro: inga påminnelser från 22:00 (de fortsätter nästa morgon)


def _day(value: Any) -> Optional[date]:
    try:
        s = str(value or "")
        if not s:
            return None
        return datetime.fromisoformat(s[:19]).date() if len(s) > 10 else date.fromisoformat(s[:10])
    except (ValueError, TypeError):
        return None


def remind_days(task: Dict[str, Any]) -> List[date]:
    """Extra påminnelsedatum (ur datum i importerade mail, se core/mail_dates.py), sorterade."""
    out = []
    for v in task.get("remind_dates") or []:
        d = _day(v)
        if d is not None:
            out.append(d)
    return sorted(set(out))


def classify(task: Dict[str, Any], now: Optional[datetime] = None) -> Optional[Tuple[str, int]]:
    """
    ("overdue", dagar_sen) / ("today", 0) för en aktiv uppgift med förfallodatum (eller extra påminnelsedatum)
    idag eller tidigare. None för klara, datumlösa, framtida och senarelagda (snoozed) uppgifter.
    """
    now = now or datetime.now()
    try:
        if not task.get("id") or task.get("done"):
            return None
        days = [d for d in [_day(task.get("due_date"))] + remind_days(task) if d is not None]
        if not days:
            return None
        sn = task.get("snoozed_until")
        if sn:
            try:
                if datetime.fromisoformat(str(sn)) > now:
                    return None
            except (ValueError, TypeError):
                pass
    except (ValueError, TypeError):
        return None
    delta = max((now.date() - d).days for d in days)       # äldsta obesvarade datumet styr "försenad N dagar"
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
    (start, slut) för dagens påminnelser: från 08:00 (ligger klockslaget tidigare börjar fönstret en timme före)
    till nattron 22:00. Påminnelserna fortsätter hela fönstret — även efter klockslaget — tills uppgiften är klar.
    """
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = day + timedelta(hours=MORNING_HOUR)
    end = day + timedelta(hours=NIGHT_HOUR)
    et = event_time(task)
    if et:
        ev = day + timedelta(hours=et[0], minutes=et[1])
        if ev < start:
            start = max(day, ev - timedelta(hours=1))
    return start, end


def reminder_due(task: Dict[str, Any], now: datetime, last_shown: Optional[datetime]) -> Optional[Tuple[str, int]]:
    """
    Ska uppgiften påminnas NU? → (kind, dagar) eller None.  ``last_shown`` = när den senast visades.

    På förfallodagen (och för försenade uppgifter varje dag): första påminnelsen kl 08:00 (eller direkt om appen
    startas senare), sedan var 30:e minut TILLS UPPGIFTEN MARKERATS SOM KLAR (eller skjutits upp). Har uppgiften
    ett klockslag kommer dessutom en påminnelse exakt då. Nattro från 22:00.
    """
    c = classify(task, now)
    if c is None:
        return None
    start, end = day_window(task if c[0] == TODAY else {}, now)
    if now < start or now >= end:
        return None
    if last_shown is None or last_shown.date() < now.date():
        return c                                   # första påminnelsen i dag
    et = event_time(task)
    if et and c[0] == TODAY:
        ev = now.replace(hour=et[0], minute=et[1], second=0, microsecond=0)
        if last_shown < ev <= now:
            return c                               # exakt vid klockslaget
    if now - last_shown >= timedelta(minutes=REPEAT_MINUTES) - timedelta(seconds=30):
        return c
    return None


def triggering_date(task: Dict[str, Any], now: datetime) -> Optional[date]:
    """Det datum som just nu utlöser påminnelsen (äldsta datumet som är idag eller passerat)."""
    cands = [d for d in [_day(task.get("due_date"))] + remind_days(task) if d is not None and d <= now.date()]
    return min(cands) if cands else None


def mail_note(task: Dict[str, Any], now: datetime) -> str:
    """Raden ur mailet som hör till det utlösande datumet ('Betalning 2 · 15/11 …'), annars ''."""
    d = triggering_date(task, now)
    info = task.get("remind_info")
    if d is None or not isinstance(info, dict):
        return ""
    return str(info.get(d.isoformat()) or "")


def trigger_days(task: Dict[str, Any]) -> List[date]:
    """Alla datum som kan utlösa en påminnelse för uppgiften (förfallodatum + extra datum ur mail), sorterade."""
    days = set(remind_days(task))
    due = _day(task.get("due_date"))
    if due is not None:
        days.add(due)
    return sorted(days)


def next_remind_date(task: Dict[str, Any], today: date) -> Optional[date]:
    """Datumet som står på tur efter det som just utlöser påminnelsen (kan vara framtida eller ett äldre obesvarat), annars None."""
    days = trigger_days(task)
    cur = min((d for d in days if d <= today), default=None)
    if cur is None:
        return None
    nxt = [d for d in days if d > cur]
    return nxt[0] if nxt else None


def plan_done(task: Dict[str, Any], today: date) -> Dict[str, Any]:
    """
    Vad knappen ✓ Klar på påminnelsekortet ska göra. Mail med flera datum (delbetalningar: 15/11, 1/12 …) är EN
    uppgift: Klar = det ÄLDSTA obesvarade datumet är avklarat (ett datum i taget — inget sväljs i smyg) → uppgiften
    väntar på nästa datum och bockas av först när inga datum återstår.

    {"complete": bool, "set_due": iso|None, "remind_dates": [iso…], "next": date|None}
    """
    ack = min((d for d in trigger_days(task) if d <= today), default=None)
    if ack is None:                                         # inget datum utlöste (t.ex. gammalt kort) → som förut: bocka av
        return {"complete": True, "set_due": None, "remind_dates": [d.isoformat() for d in remind_days(task)], "next": None}
    due = _day(task.get("due_date"))
    remaining = [d for d in remind_days(task) if d != ack]
    out: Dict[str, Any] = {"complete": False, "set_due": None, "remind_dates": [d.isoformat() for d in remaining], "next": None}
    left = set(remaining)
    if due is not None and due != ack:
        left.add(due)
    if due is not None and due == ack and remaining:
        out["set_due"] = remaining[0].isoformat()          # förfallodatumet hoppar till nästa datum
    out["complete"] = not left
    out["next"] = min(left) if left else None
    return out


def detail_text(task: Dict[str, Any], kind: str, days: int, now: Optional[datetime] = None) -> str:
    """Raden under titeln på påminnelsekortet ('förfaller idag kl 15:00', 'tiden har passerat', 'försenad 2 dagar')."""
    now = now or datetime.now()
    note = mail_note(task, now)
    if note:
        nxt = next_remind_date(task, now.date())
        base = status_text(kind, days) if kind == OVERDUE else "idag"
        tail = f"  ·  Klar → nästa {nxt.day}/{nxt.month}" if nxt else ""
        return f"📅 {base}: {note}{tail}"
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
