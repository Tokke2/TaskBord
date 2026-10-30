# -*- coding: utf-8 -*-
"""
Svenska röda dagar (helgdagar) — ren stdlib, inga nätverksanrop.

* ``holidays(year)``      → {datum: (namn, officiell)}; ``officiell`` = lagstadgad helgdag, annars en dag som i
                            praktiken är ledig för de flesta (midsommarafton, julafton, nyårsafton).
* ``week_items(today)``   → röda dagar på en VARDAG (mån–fre) i samma vecka (mån–sön) som ``today``, från och med
                            idag (kommande), sorterade efter datum.
* ``banner_text(today)``  → texten för rutan högst upp i fönstret, eller "" om veckan inte har någon.

Påskdagen räknas med den gregorianska algoritmen (Meeus/Jones/Butcher).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

WEEKDAYS = ("måndag", "tisdag", "onsdag", "torsdag", "fredag", "lördag", "söndag")
MONTHS = ("januari", "februari", "mars", "april", "maj", "juni", "juli", "augusti", "september",
          "oktober", "november", "december")


def easter(year: int) -> date:
    """Påskdagen (söndag) för ``year``."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _first_weekday_on_or_after(d: date, weekday: int) -> date:
    return d + timedelta(days=(weekday - d.weekday()) % 7)


def holidays(year: int) -> Dict[date, Tuple[str, bool]]:
    """Alla röda dagar (och de vanligaste 'praktiskt lediga' aftnarna) för ett år."""
    e = easter(year)
    out: Dict[date, Tuple[str, bool]] = {
        date(year, 1, 1): ("Nyårsdagen", True),
        date(year, 1, 6): ("Trettondedag jul", True),
        e - timedelta(days=2): ("Långfredagen", True),
        e: ("Påskdagen", True),
        e + timedelta(days=1): ("Annandag påsk", True),
        date(year, 5, 1): ("Första maj", True),
        e + timedelta(days=39): ("Kristi himmelsfärdsdag", True),
        e + timedelta(days=49): ("Pingstdagen", True),
        date(year, 6, 6): ("Nationaldagen", True),
        _first_weekday_on_or_after(date(year, 6, 20), 5): ("Midsommardagen", True),   # lördag 20–26 juni
        _first_weekday_on_or_after(date(year, 10, 31), 5): ("Alla helgons dag", True),  # lördag 31 okt–6 nov
        date(year, 12, 25): ("Juldagen", True),
        date(year, 12, 26): ("Annandag jul", True),
        # inte lagstadgade, men lediga för de flesta
        _first_weekday_on_or_after(date(year, 6, 19), 4): ("Midsommarafton", False),   # fredag 19–25 juni
        date(year, 12, 24): ("Julafton", False),
        date(year, 12, 31): ("Nyårsafton", False),
    }
    return out


def holiday_on(d: date) -> Optional[Tuple[str, bool]]:
    return holidays(d.year).get(d)


def week_items(today: date) -> List[Tuple[date, str, bool]]:
    """Kommande (inkl. idag) röda dagar på mån–fre i samma vecka som ``today``."""
    monday = today - timedelta(days=today.weekday())
    table: Dict[date, Tuple[str, bool]] = {}
    for y in {monday.year, (monday + timedelta(days=6)).year}:
        table.update(holidays(y))
    items = []
    for i in range(5):  # mån–fre
        d = monday + timedelta(days=i)
        if d >= today and d in table:
            name, official = table[d]
            items.append((d, name, official))
    return items


def _when(d: date, today: date) -> str:
    n = (d - today).days
    if n == 0:
        return "idag"
    if n == 1:
        return "imorgon"
    return f"{WEEKDAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]}"


def banner_text(today: date) -> str:
    """'🔴 Röd dag torsdag 14 maj: Kristi himmelsfärdsdag (om 2 dagar)' — flera dagar radas upp. '' = ingen."""
    parts = []
    for d, name, official in week_items(today):
        n = (d - today).days
        when = _when(d, today)
        label = name if official else f"{name} (ledig för de flesta)"
        if n == 0:
            parts.append(f"{label} idag")
        elif n == 1:
            parts.append(f"{label} imorgon ({WEEKDAYS[d.weekday()]})")
        else:
            parts.append(f"{label} {when} (om {n} dagar)")
    if not parts:
        return ""
    return "🔴 Röd dag: " + "  •  ".join(parts)
