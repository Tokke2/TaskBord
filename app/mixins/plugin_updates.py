# -*- coding: utf-8 -*-
"""Automatisk installation/uppdatering av valfria Python-paket."""

from __future__ import annotations

import sys
import threading
from contextlib import suppress
from typing import Any

from app.constants import APP_NAME, AppMode, LOG_PREFIX
from app.plugins import _check_outdated_packages, _update_packages, install_missing_plugins_silent, offer_install_missing_plugins


class PluginUpdateMixin:
    """Automatisk installation/uppdatering av valfria Python-paket."""

    def _schedule_auto_plugin_update(self) -> None:
        """
        NY v7-fix50: INSTALLERA + UPPDATERA tillägg automatiskt vid start.

        Rickards val 2026-10-02: "full automatik" — saknade tillägg
        installeras tyst och föråldrade uppdateras via pip, i bakgrunds-
        tråd (30 s efter start så appstarten aldrig blockeras).
        Avstängningsbart: settings auto_update_plugins=false eller
        tray-menyn "🔄 Auto-uppdatera tillägg vid start".
        """
        try:
            if getattr(self, "_plugins_auto_started", False):
                return
            self._plugins_auto_started = True
            # Setting av/på
            try:
                _enabled = (
                    self.settings.auto_update_plugins()
                    if hasattr(self.settings, "auto_update_plugins")
                    else bool(self.settings.get("auto_update_plugins", True))
                )
            except Exception:
                _enabled = True
            if not _enabled:
                self._log.info(
                    f"{LOG_PREFIX} Auto-uppdatering av tillägg: AVSTÄNGD "
                    f"i settings"
                )
                return
            if self._mode != AppMode.NORMAL:
                return
            self._plugin_auto_result = None
            # NY v7-fix66: progress-state för dialogen (trådsäker via
            # enkla tilldelningar + GUI-poll var 500 ms)
            self._plugin_progress = {
                "state": "idle", "phase": "", "index": 0, "total": 0,
                "name": "", "last_ok": None,
            }

            def _progress_cb(phase, index, total, name, ok):
                with suppress(Exception):
                    self._plugin_progress = {
                        "state": "working", "phase": phase,
                        "index": index, "total": total, "name": name,
                        "last_ok": ok,
                    }

            def _auto_plugins_bg() -> None:
                try:
                    import time as _time
                    _time.sleep(30)  # låt appen starta klart först
                    installed = {}
                    updated = {}
                    try:
                        # FIX v7-fix52: TYST installation (full auto —
                        # gamla koden öppnade en dialog!)
                        # v7-fix66: progress-callback → progress-bar
                        installed = (
                            install_missing_plugins_silent(
                                progress_cb=_progress_cb
                            ) or {}
                        )
                    except Exception as e:
                        self._log.warning(
                            f"{LOG_PREFIX} auto-plugin: installation av "
                            f"saknade misslyckades: {e}"
                        )
                    try:
                        outdated = _check_outdated_packages() or []
                        if outdated:
                            # FIX v7-fix53: paket vars moduler REDAN KÖRS
                            # (PySide6, orjson m.fl.) kan ej uppdateras på
                            # Windows — filerna är låsta av processen.
                            # Skippa dem (pip skulle hänga/faila).
                            _MODULE_MAP = {
                                "pyside6": "PySide6",
                                "pyside6-essentials": "PySide6",
                                "pyside6-addons": "PySide6",
                                "orjson": "orjson",
                                "psutil": "psutil",
                                "extract-msg": "extract_msg",
                                "reportlab": "reportlab",
                                "pywin32": "win32api",
                            }
                            names = []
                            _skipped = []
                            for _pk, _v, _l in outdated:
                                _mod = _MODULE_MAP.get(
                                    str(_pk).lower(), str(_pk)
                                )
                                if _mod in sys.modules:
                                    _skipped.append(_pk)
                                else:
                                    names.append(_pk)
                            if _skipped:
                                self._log.info(
                                    f"{LOG_PREFIX} auto-plugin: SKIPPAR "
                                    f"{_skipped} (i bruk — filer låsta, "
                                    f"uppdatera med appen avstängd)"
                                )
                            if names:
                                self._log.info(
                                    f"{LOG_PREFIX} auto-plugin: föråldrade: "
                                    f"{names} → uppdaterar automatiskt"
                                )
                                # v7-fix66: progress för uppdateringar
                                _ntotal = len(names)
                                for _ni, _nn in enumerate(names, 1):
                                    _progress_cb(
                                        "update", _ni, _ntotal, _nn, None
                                    )
                                    _r = _update_packages([_nn]) or {}
                                    _progress_cb(
                                        "update", _ni, _ntotal, _nn,
                                        bool(_r.get(_nn)),
                                    )
                                updated = {
                                    n: True for n in names
                                }
                            else:
                                updated = {}
                    except Exception as e:
                        self._log.warning(
                            f"{LOG_PREFIX} auto-plugin: uppdatering "
                            f"misslyckades: {e}"
                        )
                    self._plugin_auto_result = {
                        "installed": installed,
                        "updated": updated,
                    }
                except Exception as e:
                    self._log.warning(
                        f"{LOG_PREFIX} auto-plugin-bakgrund: {e}"
                    )

            _t = threading.Thread(
                target=_auto_plugins_bg, daemon=True, name="AutoPlugins"
            )
            _t.start()
            # Notis på GUI-tråden när resultatet kommit (trådsäker väg)
            self._QTimer.singleShot(
                45000, self._notify_plugin_auto_result
            )
            # NY v7-fix66: poll-timer som driver progress-dialogen
            self._plugin_progress_timer = self._QTimer()
            self._plugin_progress_timer.setInterval(500)
            self._plugin_progress_timer.timeout.connect(
                self._poll_plugin_progress
            )
            self._plugin_progress_timer.start()
            self._log.info(
                f"{LOG_PREFIX} Auto-uppdatering av tillägg schemalagd "
                f"(30 s fördröjning, bakgrund, progress-bar) — v7-fix50/66"
            )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _schedule_auto_plugin_update: {e}",
                exc_info=True,
            )

    def _poll_plugin_progress(self) -> None:
        """
        NY v7-fix66: visa/uppdatera progress-dialog för tilläggs-
        installation (körs var 500 ms på GUI-tråden — trådsäkert).
        """
        try:
            st = getattr(self, "_plugin_progress", None) or {}
            if st.get("state") != "working":
                return
            total = int(st.get("total") or 0)
            if total <= 0:
                return
            # Skapa dialog vid första anropet
            dlg = getattr(self, "_plugin_progress_dlg", None)
            if dlg is None:
                dlg = self._build_plugin_progress_dialog(total)
                self._plugin_progress_dlg = dlg
            idx = int(st.get("index") or 0)
            phase = st.get("phase") or "install"
            name = st.get("name") or ""
            verb = (
                "Installerar" if phase == "install" else "Uppdaterar"
            )
            try:
                dlg.bar.setMaximum(total)
                dlg.bar.setValue(min(idx, total))
                dlg.label.setText(
                    f"{verb} tillägg {min(idx, total)}/{total}:\n{name}"
                )
                dlg.status.setText(
                    "✓" if st.get("last_ok") else "…"
                )
            except Exception:
                pass
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} _poll_plugin_progress: {e}")

    def _build_plugin_progress_dialog(self, total: int) -> Any:
        """NY v7-fix66: bygg den lilla mörka progress-dialogen."""
        try:
            from PySide6.QtCore import Qt as _Qt
            from PySide6.QtWidgets import (
                QProgressBar as _QPB, QDialog as _QDialog,
                QVBoxLayout as _QVL, QLabel as _QL,
            )
            dlg = _QDialog()
            dlg.setWindowFlags(
                _Qt.WindowType.FramelessWindowHint
                | _Qt.WindowType.Tool
                | _Qt.WindowType.WindowStaysOnTopHint
            )
            dlg.setAttribute(_Qt.WidgetAttribute.WA_TranslucentBackground, True)
            dlg.setFixedSize(340, 110)
            lay = _QVL(dlg)
            lay.setContentsMargins(16, 14, 16, 14)
            dlg.label = _QL(f"Installerar tillägg 0/{total}:")
            dlg.label.setStyleSheet(
                "color: #eef1fb; font-size: 13px; font-weight: 600;"
                "background: transparent;"
            )
            dlg.bar = _QPB()
            dlg.bar.setRange(0, total)
            dlg.bar.setTextVisible(True)
            dlg.bar.setStyleSheet(
                "QProgressBar { background: rgba(56,62,96,120); "
                "border: 1px solid rgba(151,162,216,0.35); "
                "border-radius: 8px; color: #eef1fb; "
                "text-align: center; font-size: 12px; } "
                "QProgressBar::chunk { "
                "background: qlineargradient(x1:0,y1:0,x2:1,y2:0, "
                "stop:0 #818cf8, stop:1 #6366f1); border-radius: 7px; }"
            )
            dlg.status = _QL("…")
            dlg.status.setStyleSheet(
                "color: #9aa3c2; font-size: 11px; background: transparent;"
            )
            lay.addWidget(dlg.label)
            lay.addWidget(dlg.bar)
            lay.addWidget(dlg.status)
            dlg.setStyleSheet(
                "QDialog { background: rgba(30,32,54,240); "
                "border-radius: 14px; border: 1px solid "
                "rgba(129,140,248,0.35); }"
            )
            # Centrera på primära skärmen
            try:
                _scr = self._app.primaryScreen()
                if _scr is not None:
                    _g = _scr.availableGeometry()
                    dlg.move(
                        _g.x() + (_g.width() - 340) // 2,
                        _g.y() + (_g.height() - 110) // 2,
                    )
            except Exception:
                pass
            dlg.show()
            self._log.info(
                f"{LOG_PREFIX} Progress-dialog visas: {total} tillägg"
            )
            return dlg
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _build_plugin_progress_dialog: {e}"
            )
            return None

    def _close_plugin_progress(self) -> None:
        """NY v7-fix66: stäng progress-dialogen (anropas efter done)."""
        try:
            dlg = getattr(self, "_plugin_progress_dlg", None)
            if dlg is not None:
                with suppress(Exception):
                    dlg.close()
                    dlg.deleteLater()
                self._plugin_progress_dlg = None
            _pt = getattr(self, "_plugin_progress_timer", None)
            if _pt is not None:
                with suppress(Exception):
                    _pt.stop()
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} _close_plugin_progress: {e}")

    def _notify_plugin_auto_result(self) -> None:
        """NY v7-fix50: visa tray-notis efter automatisk tilläggsuppdatering."""
        try:
            res = getattr(self, "_plugin_auto_result", None)
            if res is None:
                # v7-fix66: bg-jobbet fortfarande igång (stora paket) →
                # stäng INTE dialogen, kolla igen om 10 s
                self._QTimer.singleShot(
                    10000, self._notify_plugin_auto_result
                )
                return
            # v7-fix66: klart — stäng progress-dialogen
            self._close_plugin_progress()
            if not res or self._tray is None:
                return
            n_inst = sum(1 for v in (res.get("installed") or {}).values() if v)
            n_upd = sum(1 for v in (res.get("updated") or {}).values() if v)
            if n_inst or n_upd:
                msg = (
                    f"✅ {n_inst} tillägg installerade, {n_upd} uppdaterade."
                )
                if n_upd:
                    msg += "\nStarta om appen för att aktivera nya versioner."
                self._tray.showMessage(
                    APP_NAME,
                    msg,
                    self._QSystemTrayIcon.MessageIcon.Information,
                    6000,
                )
            else:
                self._log.info(
                    f"{LOG_PREFIX} auto-plugin: alla tillägg aktuella "
                    f"(inget att göra)"
                )
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} _notify_plugin_auto_result: {e}")
            with suppress(Exception):
                self._close_plugin_progress()

    def _toggle_auto_update_plugins(self, checked: bool) -> None:
        """NY v7-fix50: tray-toggle för auto-uppdatering av tillägg."""
        try:
            if hasattr(self.settings, "set_auto_update_plugins"):
                self.settings.set_auto_update_plugins(bool(checked))
            self._log.info(
                f"{LOG_PREFIX} Auto-uppdatering tillägg: "
                f"{'PÅ' if checked else 'AV'}"
            )
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} toggle auto-plugins: {e}")

    # -----------------------------------------------------------------------
    # AUTOSTART (NY v6.4.1) — UI-toggle i tray-menyn
    # -----------------------------------------------------------------------

    def _on_plugin_check(self) -> None:
        """
        NY v7-fix36: Kontrollera + installera/uppdatera Python-tillägg.
        Körs från tray-menyn "📦 Installera/Uppdatera tillägg".
        """
        self._log.info(
            f"{LOG_PREFIX} _on_plugin_check: kontrollerar tillägg..."
        )
        try:
            results = offer_install_missing_plugins()
            if not results:
                self._tray.showMessage(
                    APP_NAME,
                    "✅ Alla tillägg är installerade och uppdaterade!",
                    self._QSystemTrayIcon.MessageIcon.Information,
                    3000,
                )
                return
            ok_count = sum(1 for ok in results.values() if ok)
            total = len(results)
            if ok_count:
                self._tray.showMessage(
                    APP_NAME,
                    f"✅ {ok_count}/{total} tillägg installerade/uppdaterade. "
                    f"Starta om appen för att aktivera.",
                    self._QSystemTrayIcon.MessageIcon.Information,
                    5000,
                )
            else:
                self._tray.showMessage(
                    APP_NAME,
                    "⚠️ Kunde inte installera tillägg. "
                    "Kör manuellt: pip install <paket>",
                    self._QSystemTrayIcon.MessageIcon.Warning,
                    5000,
                )
        except Exception as e:
            self._log.error(
                f"{LOG_PREFIX} _on_plugin_check fel: {e}", exc_info=True
            )

    def _on_plugin_check_legacy(self) -> None:
        """
        ÄLDRE variant av tilläggskontrollen (bevarad enligt regeln
        'ta aldrig bort funktioner'). Den AKTIVA varianten som
        tray-menyn använder är _on_plugin_check (med varnings-feedback
        vid misslyckade installationer).

        NY v7-fix36: Kontrollera + installera/uppdatera Python-tillägg.
        Körs från tray-menyn "📦 Installera/Uppdatera tillägg".
        """
        self._log.info(f"{LOG_PREFIX} _on_plugin_check: kontrollerar...")
        try:
            results = offer_install_missing_plugins()
            if not results:
                if self._tray is not None:
                    self._tray.showMessage(
                        APP_NAME,
                        "✅ Alla tillägg är installerade och uppdaterade!",
                        self._QSystemTrayIcon.MessageIcon.Information,
                        3000,
                    )
                return
            ok_count = sum(1 for ok in results.values() if ok)
            total = len(results)
            if ok_count and self._tray is not None:
                self._tray.showMessage(
                    APP_NAME,
                    f"✅ {ok_count}/{total} tillägg installerade. "
                    f"Starta om appen för att aktivera.",
                    self._QSystemTrayIcon.MessageIcon.Information,
                    5000,
                )
        except Exception as e:
            self._log.error(f"{LOG_PREFIX} _on_plugin_check fel: {e}")
