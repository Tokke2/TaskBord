# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""
power_save.py — PowerSaveMixin: energisparläge när fönstret inte syns (gömt i tray, dockat i skärmkanten, minimerat).

En liten timer (var 15:e sekund) kollar om något fönster syns. Har inget synts på ~45 s slås Windows effektivitetsläge på och
minnet städas (core/power.py); visas fönstret igen stängs läget av direkt (hover mot kanten, tray-klick, snabbtangent).
Påminnelser, mailbryggan och snabbtangenter fungerar som vanligt — de får bara köra lite lugnare.
Av/på: tray → "Energisparläge" (inställningen ``power_save``, standard på).
"""
from __future__ import annotations

import time
from contextlib import suppress
from typing import Any, Optional

from app.constants import LOG_PREFIX

TICK_MS = 15_000


class PowerSaveMixin:
    def _init_power_save(self) -> None:
        if getattr(self, "_power_timer", None) is not None or getattr(self, "_app", None) is None:
            return
        self._power_hidden_since: Optional[float] = None
        self._power_last_trim: Optional[float] = None
        self._power_eco = False
        t = self._QTimer(self._app)
        t.setInterval(TICK_MS)
        t.timeout.connect(self._power_tick)
        t.start()
        self._power_timer = t

    def _any_window_visible(self) -> bool:
        """Syns något av fönstren på skärmen just nu? (inte gömt i tray, minimerat eller dockat-och-gömt)."""
        with suppress(Exception):
            with self._widget_lock:
                widgets = list(self._widgets.values())
            for w in widgets:
                sh = getattr(w, "_shell", None) or w
                if not sh.isVisible() or sh.isMinimized():
                    continue
                dk = getattr(w, "_edge_dock", None)
                if dk is not None and getattr(dk, "state", "idle") == "hidden":
                    continue
                return True
            return False
        return True      # osäkert → anta att det syns (spara hellre inte)

    def _power_enabled(self) -> bool:
        with suppress(Exception):
            return bool(self.settings.pref("power_save"))
        return True

    def _power_tick(self, now: Optional[float] = None) -> None:
        try:
            from core import power
            now = time.monotonic() if now is None else now
            enabled = self._power_enabled()
            visible = self._any_window_visible()
            if visible or not enabled:
                self._power_hidden_since = None
            elif self._power_hidden_since is None:
                self._power_hidden_since = now
            hidden_for = 0.0 if self._power_hidden_since is None else now - self._power_hidden_since
            since_trim = None if self._power_last_trim is None else now - self._power_last_trim
            d = power.plan(visible, hidden_for, since_trim, enabled)
            if d["eco"] != self._power_eco:
                self._power_eco = d["eco"]
                if not d["eco"]:
                    self._power_last_trim = None        # nästa gång börjar vi om med en städning
                ok = power.set_eco_mode(d["eco"])
                self._log.info(f"{LOG_PREFIX} energisparläge {'PÅ' if d['eco'] else 'AV'} "
                               f"({'fönstret syns inte' if d['eco'] else 'fönstret syns / avstängt'}; Windows: {'ok' if ok else 'ej tillgängligt'})")
            if d["trim"]:
                self._power_last_trim = now
                r = power.trim_memory()
                if r.get("before") is not None and r.get("after") is not None:
                    self._log.info(f"{LOG_PREFIX} minnet städat: {r['before']:.0f} → {r['after']:.0f} MB")
        except Exception as e:  # noqa: BLE001
            self._log.debug(f"{LOG_PREFIX} _power_tick: {e}")

    def _toggle_power_save(self, checked: bool) -> None:
        """Tray: Energisparläge av/på."""
        with suppress(Exception):
            self.settings.set_pref("power_save", bool(checked))
            a = getattr(self, "_power_action_ref", None)
            if a is not None:
                a.setText(f"{'✅' if checked else '⚪'}  Energisparläge (när fönstret inte syns)")
            self._power_tick()
        self._log.info(f"{LOG_PREFIX} energisparläge i inställningarna: {'på' if checked else 'av'}")
