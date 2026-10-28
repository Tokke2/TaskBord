# -*- coding: utf-8 -*-
"""Stäng / minimera → gömmer fönstret till systemfältet (tray). Tray-ikonen tar fram det igen."""

from __future__ import annotations

from contextlib import suppress
from typing import Any, List

from app.constants import APP_NAME, LOG_PREFIX


class TrayHideMixin:
    """
    Knapparna – (minimera) och ✕ (stäng) i fönstrets topp, Stäng-förfrågan och högerklicksmenyn
    gömmer fönstret till tray. Appen fortsätter köra (påminnelser, mailbrygga, snabbtangenter).

    Tillbaka: klicka på tray-ikonen, tray-menyn → Visa, snabbtangenten för ny uppgift eller starta
    appen en gång till. Win+D gömmer fortfarande INTE fönstret (bara våra egna knappar gör det).
    """

    _hidden_to_tray = False
    _tray_hide_notice_shown = False

    # ------------------------------------------------------------------
    def _is_hidden_to_tray(self) -> bool:
        return bool(getattr(self, "_hidden_to_tray", False))

    def _tray_available(self) -> bool:
        """Finns en synlig tray-ikon att komma tillbaka via? (annars göms inget — man skulle bli utelåst)"""
        try:
            t = getattr(self, "_tray", None)
            return bool(t is not None and t.isVisible())
        except Exception:
            return False

    def _tray_hidden_targets(self) -> List[Any]:
        """[(widget, fönstret som ska gömmas)] — skalet om det finns, annars widgeten själv."""
        out = []
        with self._widget_lock:
            widgets = list(self._widgets.values())
        for w in widgets:
            out.append((w, getattr(w, "_shell", None) or w))
        return out

    def _hide_to_tray(self, notice: bool = True) -> bool:
        """Göm alla fönster till tray. False om det inte gick (ingen tray-ikon)."""
        try:
            if not self._tray_available():
                self._log.warning(f"{LOG_PREFIX} gömma till tray: ingen synlig tray-ikon — fönstret göms inte")
                return False
            self._hidden_to_tray = True
            for w, target in self._tray_hidden_targets():
                with suppress(Exception):
                    if hasattr(w, "_save_geometry_now"):
                        w._save_geometry_now()   # läget sparas innan det göms
                for obj in (w, target):
                    with suppress(Exception):
                        obj._hidden_to_tray = True
                with suppress(Exception):
                    target.hide()
            self._log.info(f"{LOG_PREFIX} fönstret gömt till tray")
            if notice and not self._tray_hide_notice_shown:
                self._tray_hide_notice_shown = True
                with suppress(Exception):
                    self._tray.showMessage(
                        APP_NAME,
                        "Ledgebord ligger kvar i systemfältet. Klicka på ikonen för att visa fönstret igen.",
                        self._QSystemTrayIcon.MessageIcon.Information,
                        5000,
                    )
            return True
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} _hide_to_tray misslyckades: {e}", exc_info=True)
            return False

    def _clear_tray_hidden(self) -> bool:
        """Ta bort 'gömd'-märkningen (anropas av allt som visar fönstret). True om det var gömt."""
        was = self._is_hidden_to_tray()
        self._hidden_to_tray = False
        with suppress(Exception):
            for w, target in self._tray_hidden_targets():
                for obj in (w, target):
                    with suppress(Exception):
                        obj._hidden_to_tray = False
        return was

    def _restore_from_tray(self) -> bool:
        """Visa fönstret igen om det var gömt till tray."""
        if not self._is_hidden_to_tray():
            return False
        self._log.info(f"{LOG_PREFIX} visar fönstret igen (från tray)")
        self._show_existing_window()   # rensar märkningen + visar skalet + återfäster skrivbordslagret
        self._clear_tray_hidden()
        return True

    def _remember_hidden_for_restart(self) -> None:
        """Före tyst omstart: ligger fönstret i tray ska nya versionen också starta gömd (i 3 min)."""
        import time as _time
        if self._is_hidden_to_tray():
            self.settings.set_restart_hidden_until(_time.time() + 180)

    def _started_by_autostart(self) -> bool:
        """Startades appen med datorn (autostart-kommandot har --autostart)?"""
        from app.constants import AUTOSTART_FLAG
        import sys
        return AUTOSTART_FLAG in sys.argv[1:]

    def _apply_start_minimized(self, attempt: int = 0) -> None:
        """
        Göm fönstret till tray strax efter start när appen startats MED DATORN (--autostart)
        eller 'Starta minimerad i tray' är ikryssat (tray-menyn). Manuell start visar fönstret som vanligt.
        Tray-ikonen kan dyka upp sent vid inloggning → några försök (annars göms inget).
        """
        try:
            import time as _time
            want = self._started_by_autostart()
            if not want:
                with suppress(Exception):
                    want = bool(self.settings.start_minimized())
            if not want:
                # tyst omstart efter uppdatering medan fönstret låg i tray → fortsätt gömd
                with suppress(Exception):
                    if _time.time() < float(self.settings.restart_hidden_until()):
                        want = True
            with suppress(Exception):
                if float(self.settings.restart_hidden_until()) and attempt == 0:
                    self.settings.set_restart_hidden_until(0)   # gäller bara en omstart
            if not want:
                return
            if self._hide_to_tray(notice=False):
                self._log.info(f"{LOG_PREFIX} startade minimerad i tray ({'med datorn' if self._started_by_autostart() else 'inställning'})")
            elif attempt < 4:
                self._QTimer.singleShot(5000, lambda: self._apply_start_minimized(attempt + 1))
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} _apply_start_minimized: {e}")
