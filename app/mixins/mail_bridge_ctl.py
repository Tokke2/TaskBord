# -*- coding: utf-8 -*-
"""E-postbryggan (Thunderbird-tillägget) och inkorgsmappen."""

from __future__ import annotations

import json as _stdlib_json
import os
import subprocess
import sys
import threading
from collections import deque
from contextlib import suppress
from pathlib import Path
from typing import Any, Dict, List

from app.constants import APP_VERSION_DISPLAY, AppMode, LOG_PREFIX, SCRIPT_DIR
from app.platform_utils import xpi_script_hint


class MailBridgeMixin:
    """E-postbryggan (Thunderbird-tillägget) och inkorgsmappen."""

    def _mail_bridge_data_dir(self) -> Path:
        """data/-katalogen (där active.json och mail_bridge/ ligger)."""
        try:
            if hasattr(self.settings, "data_dir"):
                return Path(str(self.settings.data_dir()))
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} data_dir via settings: {e}")
        return Path(getattr(self, "_SCRIPT_DIR", SCRIPT_DIR)) / "data"

    def _init_mail_bridge(self, at_startup: bool = False) -> None:
        """
        NY v7-fix90: starta e-postbryggan (Thunderbird-tillägg) + bevaka
        inkorgsmappen. Misslyckas tyst — appen får aldrig hindras av detta.
        """
        try:
            if self._mode == AppMode.SAFE_MODE:
                self._log.info(
                    f"{LOG_PREFIX} e-postbryggan hoppas över (safe-mode)"
                )
                return
            from core.mail_bridge import MailBridgeService

            data_dir = self._mail_bridge_data_dir()

            def _setting(name: str, default: Any, cast: Any) -> Any:
                """Läs en settings-nyckel säkert (gammal settings.json → default)."""
                try:
                    getter = getattr(self.settings, name, None)
                    if callable(getter):
                        return cast(getter())
                except Exception as e:
                    self._log.debug(f"{LOG_PREFIX} settings.{name}: {e}")
                return default

            _http_on = _setting("mail_bridge_enabled", True, bool)
            _watch_on = _setting("inbox_watch_enabled", True, bool)
            if at_startup:
                # FIX v8: bryggan + inkorgsbevakningen startar ALLTID automatiskt när appen
                # startar — även om de stängts av i tray-menyn förra gången.
                if not (_http_on and _watch_on):
                    self._log.info(
                        f"{LOG_PREFIX} e-postbryggan var avstängd i inställningarna — "
                        f"slås på igen vid start"
                    )
                _http_on = _watch_on = True
                with suppress(Exception):
                    self.settings.set_mail_bridge_enabled(True)
                    self.settings.set_inbox_watch_enabled(True)
            _port = _setting("mail_bridge_port", 8765, int)
            _poll = _setting("inbox_poll_seconds", 3, int)
            _token = _setting("mail_bridge_token", "", str)

            self._mail_bridge_events: deque = deque(maxlen=50)
            self._mail_bridge_lock = threading.Lock()

            self._mail_bridge = MailBridgeService(
                self.store,
                data_dir,
                port=_port,
                token=_token,
                version=APP_VERSION_DISPLAY,
                http_enabled=_http_on,
                watch_enabled=_watch_on,
                poll_seconds=_poll,
                on_event=self._mail_bridge_notify,
            )
            status = self._mail_bridge.start()

            # Spara token i settings första gången (så den syns i JSON)
            with suppress(Exception):
                if (not _token) and self._mail_bridge.token and hasattr(
                    self.settings, "set_mail_bridge_token"
                ):
                    self.settings.set_mail_bridge_token(self._mail_bridge.token)

            # Poll-timer på GUI-tråden: visar notiser/flashar uppgifter
            try:
                self._mail_bridge_timer = self._QTimer(self._app)
                self._mail_bridge_timer.setInterval(700)
                self._mail_bridge_timer.timeout.connect(self._poll_mail_bridge)
                self._mail_bridge_timer.start()
            except Exception as e:
                self._log.debug(
                    f"{LOG_PREFIX} kunde inte starta brygg-poll-timer: {e}"
                )

            if at_startup and not status.get("http_running"):
                # port kan vara upptagen en kort stund (app nyss stängd) → försök igen
                self._mail_bridge_start_retries = 0
                self._QTimer.singleShot(1500, self._retry_mail_bridge_start)
            self._log.info(
                f"{LOG_PREFIX} ✓ E-postbrygga: http="
                f"{'PÅ' if status['http_running'] else 'AV'} "
                f"(port {status['port']}), inkorg="
                f"{'PÅ' if status['watch_running'] else 'AV'} "
                f"({status['inbox']}), token={status['token'][:6]}…"
            )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _init_mail_bridge misslyckades: {e}",
                exc_info=True,
            )

    def _retry_mail_bridge_start(self) -> None:
        """FIX v8: starta bryggan igen om den inte kom igång vid appstart (max 8 försök, 2 s)."""
        try:
            svc = getattr(self, "_mail_bridge", None)
            if svc is None or svc.server.running:
                return
            n = getattr(self, "_mail_bridge_start_retries", 0) + 1
            self._mail_bridge_start_retries = n
            if svc.server.start():
                svc.port = svc.server.port
                svc.config_payload()
                self._log.info(f"{LOG_PREFIX} e-postbryggan startad (försök {n}, port {svc.port})")
                with suppress(Exception):
                    self._populate_tray_menu()
                return
            if n < 8:
                self._QTimer.singleShot(2000, self._retry_mail_bridge_start)
            else:
                self._log.warning(
                    f"{LOG_PREFIX} e-postbryggan kunde inte starta efter {n} försök "
                    f"(port upptagen?) — watchdog fortsätter försöka"
                )
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} _retry_mail_bridge_start: {e}")

    def _mail_bridge_notify(self, event: Dict[str, Any]) -> None:
        """
        NY v7-fix90: kallas från brygg-tråden/bevakningstråden vid import.

        Lägger händelsen i en trådsäker kö — GUI:t hämtar den i
        _poll_mail_bridge (Qt-får aldrig röras från andra trådar).
        """
        try:
            lock = getattr(self, "_mail_bridge_lock", None)
            events = getattr(self, "_mail_bridge_events", None)
            if events is None:
                return
            if lock is not None:
                with lock:
                    events.append(event)
            else:
                events.append(event)
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} mail-notis kunde ej köas: {e}")

    def _poll_mail_bridge(self) -> None:
        """NY v7-fix90: töm notiskön och visa resultatet i tray/widget."""
        try:
            if getattr(self, "_store_changed_in_thread", False):
                # FIX v8: store ändrades av bryggtråden → rita om + autospara HÄR (GUI-tråden)
                self._store_changed_in_thread = False
                with suppress(Exception):
                    self._refresh_task_lists()
                with suppress(Exception):
                    self._schedule_autosave()
                with suppress(Exception):
                    self._update_tray_tooltip()
            events = getattr(self, "_mail_bridge_events", None)
            if not events:
                return
            lock = getattr(self, "_mail_bridge_lock", None)
            batch: List[Dict[str, Any]] = []
            if lock is not None:
                with lock:
                    while events:
                        batch.append(events.popleft())
            else:
                while events:
                    batch.append(events.popleft())
            _last_tid = None
            for evt in batch:
                for res in evt.get("results", []):
                    if res.get("ok") and res.get("task_id"):
                        _last_tid = res.get("task_id")
            for evt in batch:
                for res in evt.get("results", []):
                    if not res.get("ok"):
                        self._log.warning(
                            f"{LOG_PREFIX} mail-import misslyckades: "
                            f"{res.get('error')}"
                        )
                        continue
                    task_id = res.get("task_id")
                    title = str(res.get("title", ""))[:60]
                    duplicate = bool(res.get("duplicate"))
                    # 1. Flasha uppgiften i Aktiva (widgeten). FIX v8: bara den SISTA i en
                    # batch — varje flash bygger om hela listan och byter flik.
                    if task_id and task_id == _last_tid:
                        self._flash_task_in_widgets(task_id)
                    # 2. Tray-notis
                    if self._tray is not None:
                        try:
                            self._tray.showMessage(
                                (
                                    "📋 Redan importerad"
                                    if duplicate else "📧 Mail → uppgift"
                                ),
                                (
                                    f"'{title}' finns redan i listan."
                                    if duplicate else
                                    f"'{title}' skapades och sparades."
                                ),
                                self._QSystemTrayIcon.MessageIcon.Information,
                                6000,
                            )
                        except Exception as e:
                            self._log.debug(
                                f"{LOG_PREFIX} tray-notis misslyckades: {e}"
                            )
                    self._log.info(
                        f"{LOG_PREFIX} mail → uppgift: {task_id!r} "
                        f"'{title}' ({'dublett' if duplicate else 'ny'}, "
                        f"källa={evt.get('source', '?')})"
                    )
            with suppress(Exception):
                self._update_tray_tooltip()
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} _poll_mail_bridge: {e}")

    def _flash_task_in_widgets(self, task_id: str) -> None:
        """NY v7-fix90: visa uppgiften synligt i alla widgets (like fix77)."""
        try:
            with self._widget_lock:
                widgets = list(self._widgets.values())
            for w in widgets:
                fn = getattr(w, "_show_task_in_active", None)
                if callable(fn):
                    with suppress(Exception):
                        fn(task_id)
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} _flash_task_in_widgets: {e}")

    def _mail_bridge_status_text(self) -> str:
        """Kort statustext för tray-menyn."""
        svc = getattr(self, "_mail_bridge", None)
        if svc is None:
            return "avstängd"
        try:
            return svc.status_text()
        except Exception:
            return "okänd status"

    def _toggle_mail_bridge(self, checked: bool) -> None:
        """NY v7-fix90: slå bryggan (localhost-servern) på/av."""
        try:
            if hasattr(self.settings, "set_mail_bridge_enabled"):
                self.settings.set_mail_bridge_enabled(bool(checked))
            svc = getattr(self, "_mail_bridge", None)
            if svc is None:
                self._init_mail_bridge()
            else:
                svc.http_enabled = bool(checked)
                if checked:
                    ok = svc.server.start()
                    if ok:
                        svc.port = svc.server.port
                        with suppress(Exception):
                            if hasattr(self.settings, "set_mail_bridge_port"):
                                self.settings.set_mail_bridge_port(svc.port)
                        svc.config_payload()
                    self._log.info(
                        f"{LOG_PREFIX} bryggan {'startad' if ok else 'kunde ej starta'}"
                    )
                else:
                    svc.server.stop()
                    self._log.info(f"{LOG_PREFIX} bryggan stoppad (tray-toggle)")
            with suppress(Exception):
                self._populate_tray_menu()
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} _toggle_mail_bridge: {e}")

    def _toggle_inbox_watch(self, checked: bool) -> None:
        """NY v7-fix90: slå automatisk import från data/inbox/ på/av."""
        try:
            if hasattr(self.settings, "set_inbox_watch_enabled"):
                self.settings.set_inbox_watch_enabled(bool(checked))
            svc = getattr(self, "_mail_bridge", None)
            if svc is None:
                self._init_mail_bridge()
            else:
                svc.watch_enabled = bool(checked)
                if checked:
                    svc.start_watcher()
                else:
                    svc.stop_watcher()
            self._log.info(
                f"{LOG_PREFIX} inkorgsbevakning: {'PÅ' if checked else 'AV'}"
            )
            with suppress(Exception):
                self._populate_tray_menu()
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} _toggle_inbox_watch: {e}")

    def _stop_mail_bridge(self) -> None:
        """NY v7-fix90: stoppa brygga + bevakning (vid avslut)."""
        try:
            timer = getattr(self, "_mail_bridge_timer", None)
            if timer is not None:
                with suppress(Exception):
                    timer.stop()
            svc = getattr(self, "_mail_bridge", None)
            if svc is not None:
                svc.stop()
                self._log.info(f"{LOG_PREFIX} e-postbryggan stoppad")
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} _stop_mail_bridge: {e}")

    def _mail_bridge_config_json(self) -> str:
        """Inställningarna som JSON-sträng (för urklipp/tillägget)."""
        svc = getattr(self, "_mail_bridge", None)
        if svc is None:
            return "{}"
        try:
            cfg = svc.config_payload()
            return _stdlib_json.dumps(cfg, ensure_ascii=False, indent=2)
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} kunde ej bygga config: {e}")
            return "{}"

    def _copy_mail_bridge_settings(self) -> None:
        """
        NY v7-fix90: kopiera inställningarna (url + token) till urklipp och
        visa dem — användaren klistrar in dem i Thunderbird-tillägget.
        """
        try:
            svc = getattr(self, "_mail_bridge", None)
            if svc is None:
                self._init_mail_bridge()
                svc = getattr(self, "_mail_bridge", None)
            if svc is None:
                if self._QMessageBox is not None:
                    self._QMessageBox.warning(
                        None, "TaskBord", "E-postbryggan kunde inte startas."
                    )
                return
            text = self._mail_bridge_config_json()
            copied = False
            try:
                from PySide6.QtWidgets import QApplication
                app = QApplication.instance() or self._app
                if app is not None:
                    app.clipboard().setText(text)
                    copied = True
            except Exception as e:
                self._log.debug(f"{LOG_PREFIX} urklipp misslyckades: {e}")
            status = svc.status()
            info = (
                f"Adress:  {status['url']}\n"
                f"Token:   {status['token'][:10]}…"
                f"({len(status['token'])} tecken)\n"
                f"Brygga:  {'🟢 körs' if status['http_running'] else '🔴 stoppad'}\n"
                f"Inkorg:  {'🟢 bevakas' if status['watch_running'] else '⚪ av'}"
                f" — {status['inbox']}\n\n"
                f"{'✅ Inställningarna ligger på urklipp.' if copied else '⚠️ Kunde inte kopiera — markera texten manuellt.'}\n\n"
                f"Klistra in i Thunderbird:\n"
                f"  Tilläggen → TaskBord → Inställningar →\n"
                f"  fältet 'Klistra in JSON' → Läs in och spara."
            )
            self._log.info(
                f"{LOG_PREFIX} brygg-inställningar kopierade till urklipp "
                f"(port {status['port']})"
            )
            if self._QMessageBox is not None:
                box = self._QMessageBox()
                box.setWindowTitle("📧 TaskBord — inställningar för Thunderbird")
                box.setIcon(self._QMessageBox.Icon.Information)
                box.setText(info)
                box.setDetailedText(text)
                box.exec()
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _copy_mail_bridge_settings: {e}", exc_info=True
            )

    def _open_inbox_folder(self) -> None:
        """NY v7-fix90: öppna data/inbox/ i Utforskaren."""
        try:
            svc = getattr(self, "_mail_bridge", None)
            if svc is not None:
                folder = Path(svc.paths["inbox"])
            else:
                folder = self._mail_bridge_data_dir() / "inbox"
            folder.mkdir(parents=True, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(str(folder))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
            self._log.info(f"{LOG_PREFIX} inkorgsmappen öppnad: {folder}")
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} _open_inbox_folder: {e}")

    def _open_thunderbird_addon_folder(self) -> None:
        """NY v7-fix90: öppna thunderbird-tillagg/ (för installation i TB)."""
        try:
            folder = Path(
                getattr(self, "_SCRIPT_DIR", SCRIPT_DIR)
            ) / "thunderbird-tillagg"
            if not folder.is_dir():
                folder = Path(getattr(self, "_SCRIPT_DIR", SCRIPT_DIR))
            if sys.platform == "win32":
                os.startfile(str(folder))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} kunde ej öppna tilläggsmappen: {e}")

    def _show_thunderbird_guide(self) -> None:
        """NY v7-fix90: steg-för-steg: installera Thunderbird-tillägget."""
        folder = Path(
            getattr(self, "_SCRIPT_DIR", SCRIPT_DIR)
        ) / "thunderbird-tillagg"
        text = (
            "Så kopplar du Thunderbird mot TaskBord:\n\n"
            "1. Öppna TaskBord-menyn (tray-ikonen) → 📧 E-post & Thunderbird\n"
            "   → '📋 Kopiera inställningar' (adress + token ligger nu på urklipp)\n\n"
            "2. I Thunderbird: Verktyg → Tillägg och teman\n"
            "   • Klicka kugghjulet ⚙️ → 'Installera tillägg från fil…'\n"
            f"   • Välj filen TaskBord-Thunderbird.xpi (finns i\n"
            f"     {folder})\n"
            f"     – saknas .xpi: kör {xpi_script_hint()} i appmappen en gång\n\n"
            "3. Öppna tilläggets inställningar (Tillägg och teman →\n"
            "   TaskBord → Inställningar), klistra in JSON och spara.\n\n"
            "4. Använd: högerklicka på ett mail →\n"
            "   '📋 Skicka till TaskBord (ny uppgift)'\n\n"
            "Uppgiften dyker upp i widgeten och sparas i data/active.json\n"
            "(finns kvar efter omstart)."
        )
        try:
            if self._QMessageBox is None:
                self._log.info(f"{LOG_PREFIX} {text}")
                return
            box = self._QMessageBox()
            box.setWindowTitle("🧩 Thunderbird-tillägg")
            box.setIcon(self._QMessageBox.Icon.Information)
            box.setText(text)
            open_btn = box.addButton(
                "📂 Öppna tilläggsmappen", self._QMessageBox.ButtonRole.ActionRole
            )
            box.addButton("Stäng", self._QMessageBox.ButtonRole.AcceptRole)
            box.exec()
            if box.clickedButton() is open_btn:
                self._open_thunderbird_addon_folder()
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} _show_thunderbird_guide: {e}")

    def _import_email_files_dialog(self) -> None:
        """
        NY v7-fix90: importera .eml/.msg via fil-dialog (samma kärna som
        📧-knappen i widgeten) — för hela appen, från tray-menyn.
        """
        try:
            from PySide6.QtWidgets import QFileDialog
            files, _ = QFileDialog.getOpenFileNames(
                None,
                "Importera e-post som uppgift",
                "",
                "E-postfiler (*.eml *.msg);;Alla filer (*.*)",
            )
            if not files:
                return
            from core.email_import import import_email
            data_dir = self._mail_bridge_data_dir()
            imported = duplicates = failed = 0
            for fp in files:
                info: Dict[str, Any] = {}
                task_id = import_email(Path(fp), self.store, data_dir, info=info)
                if not task_id:
                    failed += 1
                    continue
                if info.get("duplicate"):
                    duplicates += 1
                else:
                    imported += 1
                self._flash_task_in_widgets(task_id)
            with suppress(Exception):
                self.store.save()
            self._log.info(
                f"{LOG_PREFIX} manuell e-postimport: {imported} nya, "
                f"{duplicates} dubletter, {failed} fel"
            )
            if self._QMessageBox is not None:
                self._QMessageBox.information(
                    None,
                    "📧 E-postimport",
                    f"{imported} importerade, {duplicates} redan importerade, "
                    f"{failed} misslyckades.\n\nUppgifterna sparas i "
                    f"data/active.json (kvar efter omstart).",
                )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _import_email_files_dialog: {e}", exc_info=True
            )

    def _mail_bridge_watchdog(self) -> None:
        """
        NY v7-fix90: starta om bryggan om den dött (port stulen, fel, krasch).

        Körs var 5:e sekund via heartbeat. Max 3 återstart-försök per
        session — annars skulle en permanent portkonflikt snurra i evighet.
        """
        svc = getattr(self, "_mail_bridge", None)
        if svc is None:
            return
        if getattr(self, "_mail_bridge_restarts", 0) >= 3:
            return
        restarted = False
        try:
            if getattr(svc, "http_enabled", True) and not svc.server.running:
                if svc.server.start():
                    self._mail_bridge_restarts = (
                        getattr(self, "_mail_bridge_restarts", 0) + 1
                    )
                    restarted = True
            if getattr(svc, "watch_enabled", True) and not svc.watch_running:
                if svc.start_watcher():
                    restarted = True
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} brygg-watchdog: {e}")
            return
        if restarted:
            svc.config_payload()
            self._log.info(
                f"{LOG_PREFIX} e-postbryggan återstartad av watchdog "
                f"(port {svc.server.port or svc.port})"
            )
            with suppress(Exception):
                self._populate_tray_menu()
