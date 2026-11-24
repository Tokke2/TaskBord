# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""
payment_plan.py — delbetalningsplan: en faktura/offert delad i N betalningar → N uppgifter. Ren stdlib.

* ``build_plan(...)`` ger en lista ``[{"title", "due_date", "amount_cents"}, …]`` — titeln blir
  "<rubrik> — del 1 av 3 (4 000 kr)" och datumen följer valt intervall.
* Månadssteg räknas från FÖRSTA datumet (inte steg för steg), och dagen kläms till månadens
  längd: 31 jan → 28/29 feb → 31 mar → 30 apr. Då driver inte dagen nedåt för alltid.
* Valfritt: flytta en helg- eller röd dag till närmaste vardag (``core/holidays_se.py``).
* Belopp räknas i ören (heltal) — ingen flyttalsavrundning; resten läggs på sista delen så att
  summan alltid blir exakt totalbeloppet. Valfri handpenning = första delens belopp.
"""
from __future__ import annotations

import calendar
import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from core import holidays_se

# nyckel → (visningstext, månadssteg, dagssteg)
INTERVALS: Dict[str, Tuple[str, int, int]] = {
    "month": ("Varje månad", 1, 0),
    "month2": ("Varannan månad", 2, 0),
    "month3": ("Var tredje månad", 3, 0),
    "biweekly": ("Varannan vecka", 0, 14),
    "weekly": ("Varje vecka", 0, 7),
}
INTERVAL_ORDER = ["month", "biweekly", "weekly", "month2", "month3"]

# nyckel → visningstext (hur ett datum på helg/röd dag hanteras)
SHIFT_MODES: Dict[str, str] = {
    "nearest": "Flytta till närmaste vardag",
    "next": "Flytta till nästa vardag",
    "prev": "Flytta till föregående vardag",
    "none": "Flytta inte",
}
DEFAULT_SHIFT = "nearest"
DEFAULT_INTERVAL = "month"
DEFAULT_TAG = "delbetalning"
MIN_PARTS = 2
MAX_PARTS = 60
NBSP = "\u00a0"


# ---------------------------------------------------------------- datum ---------------------------------
def add_months(d: date, n: int) -> date:
    """d + n månader; dagen kläms till månadens sista dag (31 jan + 1 → 28/29 feb)."""
    idx = d.year * 12 + (d.month - 1) + n
    y, m0 = divmod(idx, 12)
    m = m0 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def is_workday(d: date) -> bool:
    """Mån–fre som inte är röd dag (inkl. midsommar-/jul-/nyårsafton, då banker och kontor är stängda)."""
    return d.weekday() < 5 and holidays_se.holiday_on(d) is None


def shift_to_workday(d: date, mode: str = DEFAULT_SHIFT) -> date:
    """Flytta ``d`` om det är helg/röd dag. mode: nearest | next | prev | none."""
    if mode == "none" or is_workday(d):
        return d
    if mode == "next":
        for k in range(1, 15):
            c = d + timedelta(days=k)
            if is_workday(c):
                return c
    elif mode == "prev":
        for k in range(1, 15):
            c = d - timedelta(days=k)
            if is_workday(c):
                return c
    else:  # nearest — vid lika avstånd föredras DEN TIDIGARE dagen
        for k in range(1, 8):
            for c in (d - timedelta(days=k), d + timedelta(days=k)):
                if is_workday(c):
                    return c
    return d


def plan_dates(first: date, n: int, interval: str = DEFAULT_INTERVAL,
               shift: str = DEFAULT_SHIFT) -> List[date]:
    """Förfallodatum för de n delarna."""
    _label, months, days = INTERVALS.get(interval, INTERVALS[DEFAULT_INTERVAL])
    out: List[date] = []
    for k in range(n):
        d = add_months(first, months * k) if months else first + timedelta(days=days * k)
        out.append(shift_to_workday(d, shift))
    return out


# --------------------------------------------------------------- belopp ---------------------------------
def parse_amount(text: Any) -> Optional[int]:
    """'12 000 kr' / '12000,50' / '12.000,50' / '1 234.5' → ören (1200000 …). Tomt/ogiltigt → None."""
    s = str(text or "").lower().replace("kr", "").replace("sek", "").replace(":-", "")
    s = re.sub(r"[\s\u00a0\u202f']", "", s)
    if not s or not re.fullmatch(r"[0-9.,]+", s):
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".") if s.count(",") == 1 else s.replace(",", "")
    elif "." in s:
        head, _, tail = s.rpartition(".")
        if s.count(".") > 1 or len(tail) == 3:  # 12.000 / 1.234.567 = tusentalsavgränsare
            s = s.replace(".", "")
    try:
        whole, _, frac = s.partition(".")
        cents = int(whole or "0") * 100 + int((frac + "00")[:2] or "0")
    except ValueError:
        return None
    return cents if 0 < cents <= 10 ** 12 else None


def format_amount(cents: int) -> str:
    """4000 kr → '4 000 kr'; med ören bara när de behövs: '4 000,50 kr' (hårda mellanslag)."""
    whole, frac = divmod(int(cents), 100)
    txt = f"{whole:,}".replace(",", NBSP)
    if frac:
        txt += f",{frac:02d}"
    return f"{txt}{NBSP}kr"


def split_amounts(total_cents: int, n: int, down_cents: int = 0) -> List[int]:
    """Dela totalen på n delar. Med handpenning är del 1 = handpenningen och resten delas lika på
    övriga delar. Resten (ören) hamnar på sista delen. Summan = total."""
    if n < 1 or total_cents <= 0:
        return []
    if down_cents and 0 < down_cents < total_cents and n >= 2:
        rest = total_cents - down_cents
        each, rem = divmod(rest, n - 1)
        parts = [down_cents] + [each] * (n - 1)
        parts[-1] += rem
        return parts
    each, rem = divmod(total_cents, n)
    parts = [each] * n
    parts[-1] += rem
    return parts


# ----------------------------------------------------------------- plan ---------------------------------
def part_title(base: str, i: int, n: int, amount_cents: Optional[int] = None) -> str:
    t = f"{base.strip()} — del {i} av {n}"
    if amount_cents:
        t += f" ({format_amount(amount_cents)})"
    return t


def build_plan(base_title: str, first: date, n: int, interval: str = DEFAULT_INTERVAL,
               shift: str = DEFAULT_SHIFT, total_cents: Optional[int] = None,
               down_cents: int = 0, max_title: int = 500) -> List[Dict[str, Any]]:
    """Hela planen. Tom rubrik eller n utanför MIN_PARTS..MAX_PARTS → tom lista."""
    base = " ".join(str(base_title or "").split())
    if not base or not (MIN_PARTS <= int(n) <= MAX_PARTS):
        return []
    n = int(n)
    dates = plan_dates(first, n, interval, shift)
    amounts: List[Optional[int]] = list(split_amounts(total_cents, n, down_cents)) if total_cents else [None] * n
    # titeln får inte överskrida butikens maxlängd (suffixet måste få plats)
    suffix_room = max_title - len(part_title("", n, n, max(amounts) if amounts and amounts[0] else None))
    base = base[:max(10, suffix_room)].rstrip()
    out: List[Dict[str, Any]] = []
    for i, (d, a) in enumerate(zip(dates, amounts), start=1):
        out.append({"title": part_title(base, i, n, a), "due_date": d.isoformat(), "amount_cents": a})
    return out


_SUFFIX_RE = re.compile(r"\s*[—–-]\s*del\s+\d+\s+av\s+\d+(\s*\([^)]*\))?\s*$", re.IGNORECASE)


def base_title(title: Any) -> str:
    """'Limo — del 2 av 3 (4 000 kr)' → 'Limo' (för att fylla i dialogen från en befintlig uppgift)."""
    return _SUFFIX_RE.sub("", str(title or "")).strip()


def parse_tags(text: Any) -> List[str]:
    """'delbetalning, limo' → ['delbetalning', 'limo'] (kommatecken/blanksteg, max 5)."""
    out: List[str] = []
    for raw in re.split(r"[,;\s]+", str(text or "")):
        t = raw.strip().lstrip("#").lower()
        if t and t not in out:
            out.append(t)
    return out[:5]


def create_tasks(store: Any, plan: List[Dict[str, Any]], priority: str = "none",
                 tags: Optional[List[str]] = None) -> List[str]:
    """Skapa uppgifterna i butiken. Returnerar id:n för de som skapades (stannar om butiken är full)."""
    ids: List[str] = []
    for item in plan:
        tid = store.add_task(item["title"], priority=priority, due_date=item["due_date"], tags=list(tags or []))
        if not tid:
            break
        ids.append(tid)
        if item.get("amount_cents") and hasattr(store, "set_amount"):
            store.set_amount(tid, int(item["amount_cents"]))   # beloppet följer med så att summorna stämmer
    return ids
