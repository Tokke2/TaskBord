# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""
quiet_hours.py — tysta timmar för påminnelser (ren logik, ingen Qt).

* ``QuietHours(enabled, start, end, weekends)`` — tyst från ``start`` till ``end`` (”22:00”–”08:00” går över midnatt),
  och valfritt hela lördagen och söndagen.
* ``is_quiet(now)``  — ska inget påminnas just nu?
* ``active_window(now)`` — (början, slut) på dagens aktiva fönster när tystnaden går över midnatt, annars None.
* Avstängda tysta timmar = påminnelser när som helst.

Påminnelsernas innehåll rörs inte: det som inte visas i natt kommer som första påminnelse när tystnaden är slut.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any, Optional, Tuple


def _parse(s: str, fallback: time) -> time:
    try:
        hh, mm = str(s).split(":")
        return time(int(hh), int(mm))
    except (ValueError, TypeError):
        return fallback


@dataclass(frozen=True)
class QuietHours:
    enabled: bool = True
    start: str = "22:00"
    end: str = "08:00"
    weekends: bool = False

    @property
    def t_start(self) -> time:
        return _parse(self.start, time(22, 0))

    @property
    def t_end(self) -> time:
        return _parse(self.end, time(8, 0))

    def is_weekend(self, now: datetime) -> bool:
        return now.weekday() >= 5

    def in_night(self, now: datetime) -> bool:
        """Inom intervallet start–slut (oberoende av helg)?"""
        s, e, t = self.t_start, self.t_end, now.time().replace(second=0, microsecond=0)
        if s == e:
            return False
        if s > e:                      # över midnatt
            return t >= s or t < e
        return s <= t < e

    def is_quiet(self, now: datetime) -> bool:
        if self.weekends and self.is_weekend(now):
            return True
        return bool(self.enabled and self.in_night(now))

    def active_window(self, now: datetime) -> Optional[Tuple[datetime, datetime]]:
        """Dagens aktiva fönster (slut → start) när tystnaden går över midnatt, annars None."""
        if not self.enabled or self.t_start <= self.t_end:
            return None
        day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return (day + timedelta(hours=self.t_end.hour, minutes=self.t_end.minute),
                day + timedelta(hours=self.t_start.hour, minutes=self.t_start.minute))

    def summary(self) -> str:
        parts = []
        if self.enabled:
            parts.append(f"{self.start}–{self.end}")
        if self.weekends:
            parts.append("helger")
        return " + ".join(parts) if parts else "av"


def from_settings(settings: Any) -> QuietHours:
    """QuietHours ur appens inställningar (saknas pref → standard = som förut: tyst 22:00–08:00)."""
    try:
        return QuietHours(
            bool(settings.pref("quiet_enabled")), str(settings.pref("quiet_start")),
            str(settings.pref("quiet_end")), bool(settings.pref("quiet_weekends")),
        )
    except Exception:
        return QuietHours()
