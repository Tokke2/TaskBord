# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""
amounts.py — belopp på uppgifter: summor per vy, månad och tagg. Ren stdlib, ingen Qt.

Beloppet ligger i ``task["amount_cents"]`` (heltal i ören, så summorna blir exakta). Formatering och inläsning av
text ("12 000 kr", "1.234,50") delas med delbetalningsplanen (``core/payment_plan.py``).

* ``summarize(tasks, today)``    — aktiva uppgifter: kvar att hantera (ej klarmarkerade), klart, försenat, denna/nästa
                                   månad, per månad (förfallodatum) och per tagg.
* ``summarize_archive(tasks)``   — arkivet: summa klart per månad (klardatum) och per tagg.
* ``summary_line(s)``            — raden som visas ovanför listan.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional

from core.payment_plan import format_amount

NO_DATE = "utan datum"
NO_TAG = "utan tagg"
_MONTHS = ("januari", "februari", "mars", "april", "maj", "juni", "juli", "augusti", "september", "oktober",
           "november", "december")


def task_amount(task: Dict[str, Any]) -> int:
    """Uppgiftens belopp i ören (0 = inget belopp)."""
    v = task.get("amount_cents") if isinstance(task, dict) else None
    if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
        return 0
    return v


def _day(value: Any) -> Optional[date]:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date() if value else None
    except (ValueError, TypeError):
        return None


def month_key(d: Optional[date]) -> str:
    return f"{d.year:04d}-{d.month:02d}" if d else NO_DATE


def month_label(key: str) -> str:
    """'2026-11' → 'november 2026'."""
    try:
        y, m = key.split("-")
        return f"{_MONTHS[int(m) - 1]} {int(y)}"
    except (ValueError, IndexError):
        return key


def _tags(task: Dict[str, Any]) -> List[str]:
    tags = [str(t).strip().lower() for t in (task.get("tags") or []) if str(t).strip()]
    return tags or [NO_TAG]


def _sorted_dict(d: Dict[str, int]) -> Dict[str, int]:
    """Månader i tidsordning (utan datum sist), taggar störst först."""
    if d and all(k == NO_DATE or k[:1].isdigit() for k in d):
        return dict(sorted(d.items(), key=lambda kv: (kv[0] == NO_DATE, kv[0])))
    return dict(sorted(d.items(), key=lambda kv: (-kv[1], kv[0])))


def summarize(tasks: Iterable[Dict[str, Any]], today: Optional[date] = None) -> Dict[str, Any]:
    """Summor över en lista aktiva uppgifter (den som visas i vyn)."""
    today = today or date.today()
    cur = month_key(today)
    nxt = month_key(date(today.year + (today.month == 12), today.month % 12 + 1, 1))
    out: Dict[str, Any] = {"count": 0, "open_count": 0, "open": 0, "done": 0, "overdue": 0, "overdue_count": 0,
                           "this_month": 0, "next_month": 0, "by_month": {}, "by_tag": {}, "no_amount": 0}
    by_month: Dict[str, int] = {}
    by_tag: Dict[str, int] = {}
    for t in tasks:
        a = task_amount(t)
        if not a:
            out["no_amount"] += 1
            continue
        out["count"] += 1
        if t.get("done"):
            out["done"] += a
            continue
        out["open"] += a
        out["open_count"] += 1
        due = _day(t.get("due_date"))
        key = month_key(due)
        by_month[key] = by_month.get(key, 0) + a
        if due and due < today:
            out["overdue"] += a
            out["overdue_count"] += 1
        if key == cur:
            out["this_month"] += a
        elif key == nxt:
            out["next_month"] += a
        for tg in _tags(t):
            by_tag[tg] = by_tag.get(tg, 0) + a
    out["by_month"] = _sorted_dict(by_month)
    out["by_tag"] = _sorted_dict(by_tag)
    return out


def summarize_archive(tasks: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Arkivet: summa klart per månad (klardatum) och per tagg."""
    out: Dict[str, Any] = {"count": 0, "total": 0, "by_month": {}, "by_tag": {}}
    by_month: Dict[str, int] = {}
    by_tag: Dict[str, int] = {}
    for t in tasks:
        a = task_amount(t)
        if not a:
            continue
        out["count"] += 1
        out["total"] += a
        key = month_key(_day(t.get("completed")))
        by_month[key] = by_month.get(key, 0) + a
        for tg in _tags(t):
            by_tag[tg] = by_tag.get(tg, 0) + a
    out["by_month"] = _sorted_dict(by_month)
    out["by_tag"] = _sorted_dict(by_tag)
    return out


def summary_line(s: Dict[str, Any]) -> str:
    """'💰 48 200 kr kvar (5 uppgifter) · försenat 4 000 kr · denna månad 12 000 kr'. Tom sträng om inget belopp finns."""
    if not s.get("count"):
        return ""
    n_open = s.get("open_count", s["count"])
    parts = [f"💰 {format_amount(s['open'])} kvar" if s["open"] else "💰 allt klart"]
    parts[0] += f" ({n_open} uppgifter)" if n_open != 1 else " (1 uppgift)"
    if s.get("overdue"):
        parts.append(f"försenat {format_amount(s['overdue'])}")
    if s.get("this_month"):
        parts.append(f"denna månad {format_amount(s['this_month'])}")
    if s.get("done"):
        parts.append(f"klarmarkerat {format_amount(s['done'])}")
    return " · ".join(parts)


def overview_text(s: Dict[str, Any], archive: Optional[Dict[str, Any]] = None) -> str:
    """Hela fördelningen som text (visas i översiktsdialogen och kan kopieras)."""
    lines: List[str] = []
    lines.append(f"Kvar att hantera: {format_amount(s['open'])}")
    if s.get("overdue"):
        lines.append(f"  varav försenat: {format_amount(s['overdue'])} ({s['overdue_count']} st)")
    if s.get("done"):
        lines.append(f"Klarmarkerat (ej arkiverat): {format_amount(s['done'])}")
    if s["by_month"]:
        lines += ["", "Per förfallomånad:"]
        lines += [f"  {month_label(k) if k != NO_DATE else NO_DATE:<20}{format_amount(v):>16}" for k, v in s["by_month"].items()]
    if s["by_tag"]:
        lines += ["", "Per tagg (en uppgift med flera taggar räknas under varje tagg):"]
        lines += [f"  {k:<20}{format_amount(v):>16}" for k, v in s["by_tag"].items()]
    if archive and archive.get("count"):
        lines += ["", f"Arkivet — klart totalt: {format_amount(archive['total'])} ({archive['count']} uppgifter)", "Per klarmånad:"]
        lines += [f"  {month_label(k) if k != NO_DATE else NO_DATE:<20}{format_amount(v):>16}" for k, v in archive["by_month"].items()]
    return "\n".join(lines)
