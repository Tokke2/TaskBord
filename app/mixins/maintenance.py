# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""Periodisk städning, hjärtslag och inaktivitet."""

from __future__ import annotations

import sys
import threading
import time
from contextlib import suppress
from typing import Any

from app.constants import AppMode, LOG_PREFIX, SCRIPT_DIR, Timeouts


class MaintenanceMixin:
    """Periodisk städning, hjärtslag och inaktivitet."""

    # -----------------------------------------------------------------------
    # TIMERS (callback-metoder)
    # -----------------------------------------------------------------------

    def _periodic_cleanup(self) -> None:
        """Periodisk cleanup av GDI-regioner (Win32) + fredags-pycache."""
        try:
            desktop_status = self._imports.get("desktop")
            if desktop_status and desktop_status.ok:
                cleanup = getattr(self._desktop_mod(desktop_status), "cleanup_dead_regions", None)
                if cleanup:
                    cleanup()
        except Exception as e:
            self._log.debug(f"cleanup misslyckades: {e}")
        # Smart cache: fångar också om appen stannar öppen över till fredag
        with suppress(Exception):
            self._run_friday_pycache_cleanup(at_startup=False)
        with suppress(Exception):
            self._run_log_archive(at_startup=False)
        with suppress(Exception):
            self._weekly_maintenance_check()

    # -----------------------------------------------------------------------
    # VECKOUNDERHÅLL: Pythons tillägg (Python själv uppdateras inte), helst måndag 08:00 (core/pip_update.py)
    # -----------------------------------------------------------------------
    WEEKLY_MIN_UPTIME_SEC = 600      # inte direkt efter start (autostart m.m.)
    WEEKLY_MAX_WAIT_TICKS = 36       # väntar högst ~3 h (5-minuterstick) på ett lugnt ögonblick

    _weekly_state = ""               # "" → "checking" → "ready" → "done"
    _weekly_result: Any = None
    _weekly_wait = 0

    def _weekly_maintenance_check(self) -> None:
        """
        Anropas var 5:e minut. Är veckans underhåll inte gjort (se ``pip_update.slot_start``: måndag 08:00) kollas
        i bakgrunden om något finns att uppdatera (pip --dry-run). Finns något och du inte håller på
        med något startar appen om tyst via FORSTA_START.bat /snabb /vecka, som uppdaterar medan appen är avstängd
        och sedan startar den igen (fönsterläge och uppgifter sparas som vid tyst omstart efter en uppdatering).
        Högst ett omstartsförsök per vecka; ingenting hittas → veckan bockas av utan omstart.
        """
        if sys.platform != "win32" or getattr(self, "_shutdown_initiated", False):
            return
        if self._mode == AppMode.SAFE_MODE or getattr(self, "_update_busy", False) or getattr(self, "_update_guard_pending", False):
            return
        from core import pip_update
        state = self._weekly_state
        if state == "checking":
            return
        if state == "done":
            if not pip_update.weekly_due(SCRIPT_DIR):
                self._weekly_state = ""         # ny vecka → ny koll
            return
        if state == "":
            if time.time() - getattr(self, "_start_time", time.time()) < self.WEEKLY_MIN_UPTIME_SEC:
                return
            if not pip_update.app_may_restart_for_it(SCRIPT_DIR):
                return
            self._weekly_state = "checking"
            pip_update.mark_try(SCRIPT_DIR)      # före kollen: aldrig fler än ett försök per vecka härifrån
            self._log.info(f"{LOG_PREFIX} veckounderhåll: kollar Pythons tillägg i bakgrunden")

            def _work() -> None:
                try:
                    self._weekly_result = pip_update.needs_update(SCRIPT_DIR)
                except Exception as e:
                    self._weekly_result = {"packages": [], "error": str(e)}
                self._weekly_state = "ready"

            threading.Thread(target=_work, name="weekly-check", daemon=True).start()
            return
        # state == "ready"
        res = self._weekly_result or {}
        if res.get("error"):
            self._log.info(f"{LOG_PREFIX} veckounderhåll: kunde inte kolla ({res['error']}) — provar igen vid nästa start efter 6 h")
            pip_update.log_line(SCRIPT_DIR, f"veckokoll misslyckades: {res['error']}")
            self._weekly_state = "done"
            return
        if not res.get("packages"):
            pip_update.mark_ok(SCRIPT_DIR, "inget att uppdatera (kollat av appen)")
            pip_update.log_line(SCRIPT_DIR, "veckokoll: alla paket är aktuella")
            self._log.info(f"{LOG_PREFIX} veckounderhåll: allt är aktuellt")
            self._weekly_state = "done"
            return
        reason = self._update_busy_reason()
        if reason:
            self._weekly_wait += 1
            if self._weekly_wait >= self.WEEKLY_MAX_WAIT_TICKS:
                self._log.info(f"{LOG_PREFIX} veckounderhåll: gav upp att vänta ({reason}) — görs vid nästa start")
                self._weekly_state = "done"
            return
        what = ", ".join((res.get("packages") or [])[:6])
        self._log.info(f"{LOG_PREFIX} veckounderhåll: {what} — startar om tyst för att uppdatera")
        pip_update.log_line(SCRIPT_DIR, f"veckounderhåll: appen startar om för att uppdatera ({what})")
        with suppress(Exception):
            self._remember_hidden_for_restart()
        self._flush_window_state("före veckounderhåll")
        if pip_update.schedule_maintenance(SCRIPT_DIR):
            self._weekly_state = "done"
            self.shutdown()
        else:
            self._log.warning(f"{LOG_PREFIX} veckounderhåll: kunde inte schemalägga — görs vid nästa start")
            self._weekly_state = "done"

    def _run_friday_pycache_cleanup(self, at_startup: bool = False) -> None:
        """
        NY 2026-09-23: Smart cache — rensa __pycache__ varje fredag.
        Anropas vid start + via _periodic_cleanup (5 min) → en gång per ISO-vecka.
        """
        utils_status = self._imports.get("utils")
        if not utils_status or not utils_status.ok:
            return
        inst = utils_status.instance
        # instance kan vara modul ELLER {"utils": modul}-dict (safe_import)
        fn = getattr(inst, "smart_friday_pycache_cleanup", None)
        if fn is None and isinstance(inst, dict):
            mod = inst.get("utils") or next(
                (v for v in inst.values() if hasattr(
                    v, "smart_friday_pycache_cleanup"
                )),
                None,
            )
            fn = getattr(mod, "smart_friday_pycache_cleanup", None)
        if fn is None:
            self._log.debug(
                f"{LOG_PREFIX} [CACHE] smart_friday_pycache_cleanup saknas"
            )
            return
        result = fn(base_dir=str(SCRIPT_DIR), force=False)
        if result.get("ran"):
            self._log.info(
                f"{LOG_PREFIX} [CACHE] Fredags-pycache rensad: "
                f"{result.get('pycache_removed')} mappar "
                f"({result.get('week')}, start={at_startup})"
            )
        elif result.get("reason") not in ("inte_fredag", "redan_rensad_denna_vecka"):
            self._log.debug(f"{LOG_PREFIX} [CACHE] friday_pycache: {result}")

    def _run_log_archive(self, at_startup: bool = False) -> None:
        """
        Loggar från dagar före idag arkiveras (zip i loggar/arkiv/) — ingenting raderas. Kallas vid start och var 5:e
        minut (billig om det inte finns något att göra), så även en app som står öppen över midnatt arkiverar igår.
        Gamla VARNINGAR i fel.log arkiveras också; felposter ligger kvar tills de markerats som åtgärdade.
        """
        import time as _t
        last = getattr(self, "_log_archive_ts", 0.0)
        if _t.monotonic() - last < 240 and not at_startup:
            return
        self._log_archive_ts = _t.monotonic()
        from core import error_log, log_archive
        logs = SCRIPT_DIR / "loggar"
        log_archive.archive_in_background(logs)
        with suppress(Exception):
            error_log.tidy(logs)

    def _heartbeat(self) -> None:
        """Heartbeat för watchdog + log periodic health."""
        try:
            if hasattr(self, "stability"):
                with suppress(Exception):
                    self.stability.heartbeat()
        except Exception as e:
            self._log.debug(f"heartbeat misslyckades: {e}")
        # NY v7-fix90: håll e-postbryggan vid liv (Thunderbird-tillägget)
        with suppress(Exception):
            self._mail_bridge_watchdog()

    def _check_idle(self) -> None:
        """Kontrollera idle-tid (dölj widget om idle > 10 min)."""
        try:
            if self._is_hidden_to_tray():
                return   # redan gömd till tray av användaren — visa inte igen
            desktop_status = self._imports.get("desktop")
            if desktop_status and desktop_status.ok:
                get_idle = getattr(self._desktop_mod(desktop_status), "get_idle_time_ms", None)
                if get_idle:
                    idle_sec = get_idle() // 1000
                    if idle_sec > Timeouts.IDLE_HIDE_THRESHOLD_SEC:
                        self._log.debug(f"Idle: {idle_sec}s (döljer widget)")
                        with self._widget_lock:
                            for w in self._widgets.values():
                                with suppress(Exception):
                                    if hasattr(w, "hide"):
                                        w.hide()
                    else:
                        # Visa igen om vi tidigare var idle
                        with self._widget_lock:
                            for w in self._widgets.values():
                                with suppress(Exception):
                                    if hasattr(w, "show") and not w.isVisible():
                                        w.show()
        except Exception as e:
            self._log.debug(f"check_idle misslyckades: {e}")
