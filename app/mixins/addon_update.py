# -*- coding: utf-8 -*-
"""Påminner när Thunderbird-tillägget (.xpi) ändrats och behöver installeras om."""

from __future__ import annotations

import time
from contextlib import suppress
from typing import Any

from app.constants import APP_NAME, AppMode, LOG_PREFIX, SCRIPT_DIR


class AddonUpdateMixin:
    """
    Thunderbird byter inte ut ett installerat tillägg bara för att .xpi-filen i appmappen
    byttes vid en uppdatering. Här jämförs filens innehåll mot den .xpi användaren senast
    bekräftade: ny → tray-notis (en gång), tray-menyrad och en dialog med knapp som öppnar
    mappen med filen markerad. Oberoende av uppdateringsfunktionen (gäller även manuell
    installation av en ny version).
    """

    _addon_state: Any = None   # core.addon_watch.AddonState när en ny .xpi väntar, annars None

    def _init_addon_notice(self) -> None:
        if self._mode == AppMode.SAFE_MODE:
            return
        # Efter tray + första ritningen, och inte samtidigt som den tysta versionskollen
        self._QTimer.singleShot(20_000, self._check_addon_update)

    def _check_addon_update(self) -> None:
        try:
            from core import addon_watch
            st = addon_watch.evaluate(SCRIPT_DIR, self.settings.addon_xpi_seen())
            if st.state == "baseline":
                # Första gången och inget tyder på ändring: den som finns är referensen
                self.settings.set_addon_xpi_seen(st.fingerprint)
                self._log.info(f"{LOG_PREFIX} [ADDON] referens-.xpi sparad ({st.version or '?'})")
                self._addon_state = None
            elif st.state == "new":
                self._addon_state = st
                self._log.info(
                    f"{LOG_PREFIX} [ADDON] ny Thunderbird-.xpi i appmappen "
                    f"(v{st.version or '?'}, {st.fingerprint[:8]}) — behöver installeras om"
                )
                if st.fingerprint != self.settings.addon_xpi_notified():
                    self.settings.set_addon_xpi_notified(st.fingerprint)
                    self._addon_balloon(st)
            else:
                self._addon_state = None
            with suppress(Exception):
                self._populate_tray_menu()
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} [ADDON] kontroll misslyckades: {e}")

    def _addon_balloon(self, st: Any) -> None:
        if self._tray is None:
            return
        with suppress(Exception):
            if not getattr(self, "_addon_msg_connected", False):
                self._tray.messageClicked.connect(self._on_addon_message_clicked)
                self._addon_msg_connected = True
            self._addon_balloon_ts = time.monotonic()
            self._tray.showMessage(
                "🧩 Nytt Thunderbird-tillägg",
                "Tillägget har uppdaterats. Klicka här för att visa den nya filen och "
                "installera om den i Thunderbird.",
                self._QSystemTrayIcon.MessageIcon.Information, 12000,
            )

    def _on_addon_message_clicked(self) -> None:
        if time.monotonic() - getattr(self, "_addon_balloon_ts", -999.0) < 30:
            self._addon_balloon_ts = -999.0
            self._addon_update_dialog()

    def _addon_update_dialog(self, checked: bool = False) -> None:
        """Dialog: öppna mappen med den nya filen / markera som installerad."""
        try:
            from core import addon_watch
            st = self._addon_state
            if st is None:
                st = addon_watch.evaluate(SCRIPT_DIR, self.settings.addon_xpi_seen())
            ver = f" (version {st.version})" if getattr(st, "version", "") else ""
            text = (
                f"Thunderbird-tillägget{ver} har uppdaterats tillsammans med Ledgebord.\n\n"
                "Thunderbird byter inte ut det själv — installera den nya filen:\n\n"
                "1. Klicka ”Visa filen” nedan (mappen öppnas med filen markerad).\n"
                "2. I Thunderbird: Verktyg → Tillägg och teman → kugghjulet ⚙ →\n"
                "   ”Installera tillägg från fil…” → välj Ledgebord-Thunderbird.xpi.\n"
                "3. Din token och dina inställningar i tillägget behålls normalt.\n\n"
                f"Fil: {st.path}"
            )
            box = self._QMessageBox()
            box.setWindowTitle(f"{APP_NAME} – nytt Thunderbird-tillägg")
            box.setIcon(self._QMessageBox.Icon.Information)
            box.setText(text)
            show = box.addButton("📂 Visa filen", self._QMessageBox.ButtonRole.ActionRole)
            done = box.addButton("✔ Jag har installerat det", self._QMessageBox.ButtonRole.AcceptRole)
            box.addButton("Senare", self._QMessageBox.ButtonRole.RejectRole)
            while True:
                box.exec()
                clicked = box.clickedButton()
                if clicked is show:
                    addon_watch.reveal_in_folder(st.path)
                    continue    # låt dialogen vara kvar så man kan bocka av efteråt
                if clicked is done:
                    self.settings.set_addon_xpi_seen(st.fingerprint)
                    self._addon_state = None
                    self._log.info(f"{LOG_PREFIX} [ADDON] användaren bekräftade installation")
                    with suppress(Exception):
                        self._populate_tray_menu()
                break
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} [ADDON] dialog: {e}", exc_info=True)

    def _addon_tray_action(self) -> Any:
        """Menyrad för tray när en ny .xpi väntar (annars None)."""
        if self._addon_state is None:
            return None
        act = self._QAction("🆕  Nytt Thunderbird-tillägg — installera om…", self._tray_menu)
        act.setToolTip(
            "Ledgebord-Thunderbird.xpi har ändrats.\n"
            "Öppnar mappen med filen och visar hur du installerar den."
        )
        act.triggered.connect(self._addon_update_dialog)
        return act
