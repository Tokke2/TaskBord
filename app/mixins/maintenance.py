# -*- coding: utf-8 -*-
"""Periodisk städning, hjärtslag och inaktivitet."""

from __future__ import annotations

from contextlib import suppress

from app.constants import LOG_PREFIX, SCRIPT_DIR, Timeouts


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
            self._run_friday_log_cleanup(at_startup=False)

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

    def _run_friday_log_cleanup(self, at_startup: bool = False) -> None:
        """
        NY 2026-09-25: Log-rensning varje fredag.
        Behåll ENDAST dagens log-fil (todo_app.log + aktuell backup).
        Anropas vid start + via _periodic_cleanup (5 min).
        """
        utils_status = self._imports.get("utils")
        if not utils_status or not utils_status.ok:
            return
        inst = utils_status.instance
        fn = getattr(inst, "smart_friday_log_cleanup", None)
        if fn is None and isinstance(inst, dict):
            mod = inst.get("utils") or next(
                (v for v in inst.values() if hasattr(
                    v, "smart_friday_log_cleanup"
                )),
                None,
            )
            fn = getattr(mod, "smart_friday_log_cleanup", None)
        if fn is None:
            self._log.debug(
                f"{LOG_PREFIX} [CACHE] smart_friday_log_cleanup saknas"
            )
            return
        try:
            data_dir = str(getattr(self, "_SCRIPT_DIR", SCRIPT_DIR) / "data")
        except Exception:
            data_dir = str(SCRIPT_DIR / "data")
        result = fn(data_path=data_dir, force=False)
        if result.get("ran"):
            self._log.info(
                f"{LOG_PREFIX} [CACHE] Fredags-loggrensning: "
                f"behöll={result.get('logs_kept')} "
                f"raderade={result.get('logs_removed')} "
                f"({result.get('week')}, idag={result.get('today_key')}, "
                f"start={at_startup})"
            )
        elif result.get("reason") not in (
            "inte_fredag", "redan_rensad_denna_vecka"
        ):
            self._log.debug(
                f"{LOG_PREFIX} [CACHE] friday_log_cleanup: {result}"
            )

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
