# -*- coding: utf-8 -*-
"""Sök ny version: manuell och automatisk uppdatering av appen (core/updater.py)."""

from __future__ import annotations

import threading
import time
from contextlib import suppress
from typing import Any, Tuple

from app.constants import AppMode, LOG_PREFIX, SCRIPT_DIR
from app.platform_utils import install_script_name


class UpdateMixin:
    """Sök ny version: manuell och automatisk uppdatering av appen (core/updater.py)."""

    # ------------------------------------------------------------------
    # 🔄 Sök ny version (core/updater.py)
    # ------------------------------------------------------------------
    def _update_dialog(self, kind: str, title: str, text: str) -> bool:
        """Visa dialog. kind: info | warn | ask. Returnerar True vid Ja."""
        from PySide6.QtWidgets import QMessageBox
        box = QMessageBox()
        box.setWindowTitle(title)
        box.setText(text)
        if kind == "ask":
            box.setIcon(QMessageBox.Icon.Question)
            yes = box.addButton("Uppdatera nu", QMessageBox.ButtonRole.YesRole)
            box.addButton("Avbryt", QMessageBox.ButtonRole.NoRole)
            box.exec()
            return box.clickedButton() is yes
        box.setIcon(QMessageBox.Icon.Warning if kind == "warn" else QMessageBox.Icon.Information)
        box.exec()
        return True

    def _update_progress_cb(self, phase: str, done: int, total: int) -> None:
        """Anropas från arbetstråden: lagra förlopp (GUI-tråden läser) och hantera avbryt."""
        self._update_progress = (phase, int(done), int(total))
        if getattr(self, "_update_cancel", False) and phase in ("release", "download"):
            from core import updater
            raise updater.UpdateError("Avbröts av dig.")

    def _update_progress_open(self, text: str, cancelable: bool, maximum: int = 0) -> None:
        """Förloppsfönster (GUI-tråden). maximum=0 → obestämd 'upptagen'-stapel."""
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QProgressDialog
        self._update_progress_close()
        pd = QProgressDialog(text, "Avbryt" if cancelable else "", 0, maximum)
        pd.setWindowTitle("Ledgebord – uppdatering")
        pd.setMinimumDuration(0)
        pd.setAutoClose(False)
        pd.setAutoReset(False)
        pd.setMinimumWidth(400)
        if cancelable:
            pd.canceled.connect(self._update_cancel_requested)
        else:
            # Under filbytet ska inget kunna avbrytas eller stängas av misstag.
            pd.setCancelButton(None)
            pd.setWindowModality(Qt.WindowModality.ApplicationModal)
            pd.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        pd.setValue(0)
        pd.show()
        self._update_pd = pd
        with suppress(Exception):
            self._app.processEvents()

    def _update_cancel_requested(self) -> None:
        self._update_cancel = True

    def _update_progress_close(self) -> None:
        pd = getattr(self, "_update_pd", None)
        self._update_pd = None
        if pd is not None:
            with suppress(Exception):
                pd.canceled.disconnect()
            with suppress(Exception):
                pd.close()
                pd.deleteLater()

    def _update_progress_refresh(self) -> None:
        """GUI-tråden: spegla senaste förloppet i förloppsfönstret."""
        from core import updater
        pd = getattr(self, "_update_pd", None)
        prog = getattr(self, "_update_progress", None)
        if pd is None or not prog:
            return
        phase, done, total = prog
        with suppress(Exception):
            pd.setLabelText(updater.phase_text(phase, done, total))
            if phase in ("install", "done"):
                if pd.maximum() != max(total, 1):
                    pd.setRange(0, max(total, 1))
                pd.setValue(min(done, max(total, 1)))
                if not pd.isVisible():
                    pd.show()
            elif phase == "download" and total > 0:
                if pd.maximum() != total:
                    pd.setRange(0, total)
                pd.setValue(min(done, total))
            elif pd.maximum() != 0:
                pd.setRange(0, 0)

    def _refresh_update_action(self) -> None:
        """Tray-texten markerar när en ny version väntar."""
        act = getattr(self, "_update_action", None)
        if act is None:
            return
        with suppress(Exception):   # QAction kan ha raderats när menyn byggdes om
            act.setText(self._update_action_text())

    def _update_action_text(self) -> str:
        if getattr(self, "_update_available", False):
            return "🆕  Ny version finns — uppdatera…"
        return "🔄  Sök ny version…"

    def _check_for_updates(self, silent: bool = False) -> None:
        """
        Sök i bakgrunden (nätverk) och visa resultatet på GUI-tråden.
        silent=True (automatisk koll): inga fönster alls, bara tray-notis om det finns en ny version.
        """
        if getattr(self, "_update_busy", False):
            if not silent:
                self._update_dialog("info", "Sök ny version", "En uppdatering pågår redan.")
            return
        self._update_busy = True
        self._update_silent = bool(silent)
        self._update_cancel = False
        self._update_stage = "check"
        self._update_progress = None
        self._update_result = None
        self._update_info = None
        if not silent:
            self._update_progress_open("Kontaktar GitHub…", cancelable=True)

        def _work() -> None:
            try:
                from core import updater
                self._update_result = (
                    "ok",
                    updater.check_for_update(SCRIPT_DIR, progress=self._update_progress_cb),
                )
            except Exception as e:  # UpdateError har svenskt meddelande
                self._update_result = ("err", str(e) or e.__class__.__name__)

        threading.Thread(target=_work, name="UpdateCheck", daemon=True).start()
        self._update_timer = self._QTimer(self._app)
        self._update_timer.setInterval(500 if silent else 120)
        self._update_timer.timeout.connect(self._poll_update_check)
        self._update_timer.start()

    def _update_finish(self) -> None:
        with suppress(Exception):
            self._update_timer.stop()
        self._update_progress_close()
        self._update_result = None
        self._update_busy = False

    def _poll_update_check(self) -> None:
        """GUI-tråd, ticker medan en koll/installation pågår."""
        self._update_progress_refresh()
        res = getattr(self, "_update_result", None)
        if res is None:
            return
        # Stoppa tickandet INNAN några (modala) dialoger visas.
        with suppress(Exception):
            self._update_timer.stop()
        self._update_result = None
        try:
            if getattr(self, "_update_stage", "check") == "apply":
                self._finish_apply(res)
            else:
                self._finish_check(res)
        except Exception as e:
            self._log.error(f"{LOG_PREFIX} uppdatering misslyckades: {e}", exc_info=True)
            self._update_finish()
            if not getattr(self, "_update_silent", False):
                with suppress(Exception):
                    self._update_dialog("warn", "Uppdatering misslyckades", str(e))

    def _finish_check(self, res: Tuple[str, Any]) -> None:
        from core import updater
        kind, payload = res
        silent = getattr(self, "_update_silent", False)
        self._update_progress_close()
        if kind == "err":
            self._update_finish()
            if silent:
                self._log.debug(f"{LOG_PREFIX} automatisk uppdateringskoll misslyckades: {payload}")
            elif getattr(self, "_update_cancel", False):
                self._log.info(f"{LOG_PREFIX} uppdateringskoll avbröts av användaren")
            else:
                self._update_dialog("warn", "Sök ny version", str(payload))
            return
        info = payload
        with suppress(Exception):
            self.settings.set_update_last_check(int(time.time()))
        self._update_available = not info.up_to_date
        self._refresh_update_action()
        if silent:
            self._update_finish()
            why_not = self._auto_install_blocker(info)
            if not why_not:
                self._auto_install_when_idle(info)
            else:
                if not info.up_to_date:
                    self._log.info(f"{LOG_PREFIX} ingen automatisk installation: {why_not}")
                self._notify_update_available(info)
            return
        if info.up_to_date:
            self._update_finish()
            self._update_dialog(
                "info", "Sök ny version",
                f"Du har redan senaste versionen.\n\n(Release {info.tag}, "
                f"commit {info.commit[:7] or '?'} — inga filer skiljer sig.)",
            )
            return
        extra = ""
        if info.requirements_changed:
            extra = ("\n\n⚠️ requirements.txt har ändrats. Efter uppdateringen: kör "
                     f"{install_script_name()} (installerar nya paket). Appen startar inte om "
                     "automatiskt.")
        if updater.fingerprint(info) == self._update_failed_fp():
            extra += ("\n\n⚠️ Just den här uppdateringen fick Ledgebord att inte starta förra gången och "
                      "återställdes automatiskt. Installera den bara om du vet att något ändrats.")
        if not self._update_dialog(
            "ask", "Ny version finns",
            updater.describe(info)
            + "\n\nDina uppgifter och inställningar (js\\ och data\\) rörs inte. "
              "Ersatta filer sparas i data\\backups\\app-update\\.\n"
              "Appen startar om efter uppdateringen. Kommer den inte igång inom 60 sekunder "
              "återställs den förra versionen automatiskt." + extra,
        ):
            self._update_finish()
            return
        self._begin_install(info, silent=False)

    def _begin_install(self, info: Any, silent: bool = False) -> None:
        """
        Installationsfas: spara uppgifter + fönsterläge + backup, byt filerna i en bakgrundstråd.
        silent=True (automatisk uppdatering): inga fönster alls — omstarten sker också tyst.
        """
        from core import updater
        n = len(info.changed)
        self._update_busy = True
        self._update_silent = bool(silent)
        if not silent:
            self._update_progress_open(updater.phase_text("save"), cancelable=False, maximum=0)
        with suppress(Exception):
            self.store.save()
        self._flush_window_state("före uppdatering")
        with suppress(Exception):
            self._external_backup("före uppdatering")
        self._update_info = info
        self._update_stage = "apply"
        self._update_progress = ("install", 0, n)
        self._update_result = None
        self._update_progress_refresh()

        def _apply() -> None:
            try:
                self._update_result = (
                    "ok", updater.apply_update(SCRIPT_DIR, info, progress=self._update_progress_cb)
                )
            except Exception as e:
                self._update_result = ("err", str(e) or e.__class__.__name__)

        threading.Thread(target=_apply, name="UpdateApply", daemon=True).start()
        self._update_timer.setInterval(100)
        self._update_timer.start()

    def _flush_window_state(self, why: str) -> None:
        """
        Spara fönstrets position + storlek och skriv settings till disk NU.

        Efter en uppdatering ska fönstret komma upp exakt där det var. js\\ (där settings.json
        ligger) rörs aldrig av uppdateringen, men vi skriver ner läget uttryckligen före
        installationen och före omstarten — så det inte hänger på att nedstängningen hinner.
        """
        try:
            with self._widget_lock:
                _ws = list(self._widgets.values())
            for _w in _ws:
                with suppress(Exception):
                    if hasattr(_w, "_save_geometry_now"):
                        _w._save_geometry_now()
            ok = None
            if self.settings is not None and hasattr(self.settings, "save"):
                ok = self.settings.save()
            self._log.info(
                f"{LOG_PREFIX} fönsterläge sparat ({why}): {len(_ws)} fönster, "
                f"settings {'OK' if ok else ok}"
            )
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} _flush_window_state ({why}): {e}")

    def _finish_apply(self, res: Tuple[str, Any]) -> None:
        from core import updater
        kind, payload = res
        info = self._update_info
        silent = getattr(self, "_update_silent", False)
        self._update_finish()
        if kind == "err":
            self._log.error(f"{LOG_PREFIX} installation misslyckades: {payload}")
            if silent:
                return  # tyst: inget har ändrats; nästa koll försöker igen
            self._update_dialog(
                "warn", "Uppdatering misslyckades",
                f"{payload}\n\nInget har ändrats — din installation är som förut.",
            )
            return
        self._update_available = False
        self._refresh_update_action()
        self._log.info(
            f"{LOG_PREFIX} uppdaterad till {info.tag} ({info.commit[:7]}), backup {payload}"
        )
        if silent:
            # Tyst omstart: inga dialoger. Uppgifter och fönsterläge sparas, väktaren startar den nya
            # versionen (och återställer den gamla om den inte kommer igång inom 60 s).
            self._flush_window_state("före tyst omstart")
            if updater.schedule_restart(SCRIPT_DIR, backup_root=payload):
                self._log.info(f"{LOG_PREFIX} tyst omstart efter uppdatering")
                self.shutdown()
            else:
                self._log.warning(f"{LOG_PREFIX} tyst omstart misslyckades — ny version används vid nästa start")
            return
        if info.requirements_changed:
            self._update_dialog(
                "info", "Uppdaterad",
                "Uppdateringen är installerad.\n\nKör " + install_script_name() + " för att installera "
                "nya paket och starta om Ledgebord.",
            )
            return
        _addon_note = (
            "\n\nThunderbird-tillägget har också ändrats — efter omstarten får du en "
            "påminnelse med en knapp som öppnar mappen med den nya filen."
            if "Ledgebord-Thunderbird.xpi" in info.changed else ""
        )
        self._update_dialog(
            "info", "Uppdaterad",
            f"{len(info.changed)} fil(er) uppdaterade. Ledgebord startar om nu." + _addon_note,
        )
        self._flush_window_state("före omstart")
        if updater.schedule_restart(SCRIPT_DIR, backup_root=payload):
            self.shutdown()
        else:
            self._update_dialog(
                "warn", "Uppdaterad",
                "Starta om Ledgebord manuellt (Avsluta i tray-menyn, starta sedan igen).",
            )

    # --- självläkande uppdatering (core/update_watchdog.py) -------------
    _update_guard_pending = False

    def _init_update_guard(self) -> None:
        """
        Startades vi av väktaren efter en uppdatering? Då finns data/update_pending.json.
        Appen bekräftar att den kom igång (tar bort filen) ~10 s efter start — annars
        återställer väktaren de gamla filerna efter 60 s. Visar även ett meddelande om en
        återställning skett sedan sist.
        """
        from core import update_watchdog as wd
        self._update_guard_pending = wd.read_pending(SCRIPT_DIR) is not None
        if self._update_guard_pending:
            self._log.info(f"{LOG_PREFIX} startad efter uppdatering — bekräftar att allt fungerar om 10 s")
            self._QTimer.singleShot(10_000, self._confirm_update_health)
        self._QTimer.singleShot(8_000, self._show_update_rollback_notice)

    def _update_failed_fp(self) -> str:
        """Fingeravtryck för uppdateringen som senast återställdes ('' om ingen)."""
        try:
            return str(self.settings.update_failed() or "")
        except Exception:
            return ""

    def _confirm_update_health(self, on_exit: bool = False) -> None:
        if not self._update_guard_pending:
            return
        if on_exit and time.time() - getattr(self, "_start_time", time.time()) < 3:
            return      # föll direkt efter start: låt väktaren bedöma
        from core import update_watchdog as wd
        self._update_guard_pending = False
        if wd.confirm_healthy(SCRIPT_DIR):
            self._log.info(f"{LOG_PREFIX} uppdateringen bekräftad som fungerande")
        with suppress(Exception):
            if self.settings.update_failed():
                self.settings.set_update_failed("")

    def _show_update_rollback_notice(self) -> None:
        """Visa (en gång) att en uppdatering återställdes eftersom appen inte startade."""
        from core import update_watchdog as wd
        info = wd.read_rollback(SCRIPT_DIR)
        if not info:
            return
        wd.clear_rollback(SCRIPT_DIR)
        fp = str(info.get("fingerprint") or "")
        if fp:
            with suppress(Exception):
                self.settings.set_update_failed(fp)
        tag = str(info.get("tag") or "?")
        commit = str(info.get("commit") or "")[:7]
        self._log.warning(
            f"{LOG_PREFIX} uppdateringen {tag} {commit} återställdes automatiskt: {info.get('reason')}"
        )
        text = (
            f"Uppdateringen till {tag}{' (' + commit + ')' if commit else ''} fick Ledgebord att inte "
            f"starta ({info.get('reason', 'okänd orsak')}).\n\n"
            f"Din förra version har återställts automatiskt "
            f"({info.get('restored', 0)} fil(er) tillbaka, {info.get('removed', 0)} nya borttagna). "
            "Dina uppgifter och inställningar är orörda.\n\n"
            "Du får inte fler notiser om just den här uppdateringen. "
            "Detaljer: data\\update_watchdog.log. Backup: " + str(info.get("backup", ""))
        )
        with suppress(Exception):
            if self._tray is not None:
                self._tray.showMessage(
                    "↩️ Uppdateringen återställdes", f"{tag} startade inte — din förra version är tillbaka.",
                    self._QSystemTrayIcon.MessageIcon.Warning, 10000,
                )
        with suppress(Exception):
            self._update_dialog("warn", "Uppdateringen återställdes", text)

    # --- automatisk, tyst koll (2 gånger/dygn) + tyst installation --------
    def _init_update_check(self) -> None:
        """Första kollen ~30 s efter start, därefter varje timme om det är >12 h sedan sist (2 gånger/dygn)."""
        if self._mode == AppMode.SAFE_MODE:
            return
        self._update_auto_timer = self._QTimer(self._app)
        self._update_auto_timer.setInterval(3600 * 1000)
        self._update_auto_timer.timeout.connect(self._auto_update_check)
        self._update_auto_timer.start()
        self._QTimer.singleShot(30_000, self._auto_update_check)

    def _auto_update_check(self) -> None:
        try:
            from core import updater
            if self._mode == AppMode.SAFE_MODE or getattr(self, "_update_busy", False):
                return
            if not self.settings.update_check_enabled():
                return
            if not updater.check_due(self.settings.update_last_check()):
                return
            self._log.info(f"{LOG_PREFIX} tyst uppdateringskoll")
            self._check_for_updates(silent=True)
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} _auto_update_check: {e}")

    AUTO_INSTALL_MAX_WAIT = 180   # försök i högst 3 timmar (1 gång/min) att hitta ett lugnt ögonblick

    def _auto_install_blocker(self, info: Any) -> str:
        """Varför en tyst installation INTE ska göras (tom sträng = det går bra)."""
        from core import updater
        try:
            if info.up_to_date:
                return "ingen ny version"
            if not self.settings.update_auto_install():
                return "automatisk installation är avstängd"
            if not info.changed:
                return "inga filer att byta"
            if info.requirements_changed:
                return "requirements.txt har ändrats (kräver paketinstallation av dig)"
            fp = updater.fingerprint(info)
            if not fp:
                return "saknar fingeravtryck"
            if fp == self._update_failed_fp():
                return "samma uppdatering återställdes förut (startade inte)"
            if fp == self.settings.update_auto_fp():
                return "samma uppdatering har redan installerats automatiskt (skydd mot omstartsloop)"
            if getattr(self, "_update_guard_pending", False):
                return "förra uppdateringen är inte bekräftad ännu"
            if getattr(self, "_update_auto_pending", False):
                return "en tyst installation väntar redan"
            return ""
        except Exception as e:
            return f"kontrollen misslyckades: {e}"

    def _update_busy_reason(self) -> str:
        """Pågår något där en omstart skulle störa? (tom sträng = lugnt)"""
        try:
            app = self._app
            if app.activeModalWidget() is not None:
                return "en dialog är öppen"
            if app.activePopupWidget() is not None:
                return "en meny är öppen"
            with self._widget_lock:
                ws = list(self._widgets.values())
            for w in ws:
                if getattr(w, "_inline_edit", None) is not None:
                    return "du redigerar en uppgift"
                if getattr(w, "_drag_active", False):
                    return "du drar i ett kort"
                inp = getattr(w, "input_field", None)
                if inp is not None and inp.text().strip():
                    return "du skriver en ny uppgift"
        except Exception:
            pass
        return ""

    def _auto_install_when_idle(self, info: Any, attempt: int = 0) -> None:
        """
        Installera tyst så fort du inte håller på med något (dialog/redigering/text i inmatningsfältet).
        Väntar upp till 3 h; går det inte hamnar uppdateringen som vanligt i en tray-notis.
        """
        from core import updater
        try:
            self._update_auto_pending = True
            reason = self._update_busy_reason()
            if not reason and getattr(self, "_update_busy", False):
                reason = "en annan uppdatering pågår"
            if reason:
                if attempt >= self.AUTO_INSTALL_MAX_WAIT:
                    self._update_auto_pending = False
                    self._log.info(f"{LOG_PREFIX} tyst installation gav upp ({reason}) — notis i stället")
                    self._notify_update_available(info)
                    return
                if attempt == 0:
                    self._log.info(f"{LOG_PREFIX} tyst installation väntar: {reason}")
                self._QTimer.singleShot(60_000, lambda: self._auto_install_when_idle(info, attempt + 1))
                return
            self._update_auto_pending = False
            fp = updater.fingerprint(info)
            with suppress(Exception):
                self.settings.set_update_auto_fp(fp)   # sparas FÖRE bytet: samma uppdatering körs aldrig två gånger
            self._log.info(f"{LOG_PREFIX} tyst installation av {info.tag} ({len(info.changed)} filer, {fp})")
            self._begin_install(info, silent=True)
        except Exception as e:
            self._update_auto_pending = False
            self._log.warning(f"{LOG_PREFIX} tyst installation misslyckades: {e}", exc_info=True)
            self._update_finish()

    def _toggle_auto_install(self, checked: bool = False) -> None:
        new = not self.settings.update_auto_install()
        with suppress(Exception):
            self.settings.set_update_auto_install(new)
        self._log.info(f"{LOG_PREFIX} automatisk installation: {'PÅ' if new else 'AV'}")
        with suppress(Exception):
            self._populate_tray_menu()

    def _notify_update_available(self, info: Any) -> None:
        """Tyst koll hittade något: tray-notis EN gång per uppdatering (menytexten markeras alltid)."""
        from core import updater
        if info.up_to_date:
            return
        fp = updater.fingerprint(info)
        self._log.info(f"{LOG_PREFIX} ny version finns ({info.tag}, {len(info.changed)} filer, {fp})")
        if fp and fp == self._update_failed_fp():
            self._log.info(f"{LOG_PREFIX} den här uppdateringen återställdes förut (startade inte) — ingen notis")
            return
        if fp == self.settings.update_notified():
            return
        with suppress(Exception):
            self.settings.set_update_notified(fp)
        if self._tray is None:
            return
        with suppress(Exception):
            if not getattr(self, "_update_msg_connected", False):
                self._tray.messageClicked.connect(self._on_tray_message_clicked)
                self._update_msg_connected = True
            self._update_balloon_ts = time.monotonic()
            self._tray.showMessage(
                "🆕 Ny version av Ledgebord",
                f"{len(info.changed)} fil(er) skiljer sig från din installation. "
                "Klicka här eller välj “Ny version finns” i tray-menyn.",
                self._QSystemTrayIcon.MessageIcon.Information, 10000,
            )

    def _on_tray_message_clicked(self) -> None:
        if time.monotonic() - getattr(self, "_update_balloon_ts", -999.0) < 30:
            self._update_balloon_ts = -999.0
            self._check_for_updates()

    def _toggle_auto_update(self, checked: bool = False) -> None:
        new = not self.settings.update_check_enabled()
        with suppress(Exception):
            self.settings.set_update_check_enabled(new)
        self._log.info(f"{LOG_PREFIX} automatisk uppdateringskoll: {'PÅ' if new else 'AV'}")
        with suppress(Exception):
            self._populate_tray_menu()
        if new:
            self._QTimer.singleShot(1000, self._auto_update_check)
