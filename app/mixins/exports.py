# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""Export: checklista som PDF, Google Calendar och .ics."""

from __future__ import annotations

import collections
import os
import threading
from contextlib import suppress
from datetime import datetime as _datetime
from pathlib import Path

from app.constants import APP_NAME, APP_VERSION_DISPLAY, LOG_PREFIX
from app.errors import show_error_dialog


class ExportsMixin:
    """Export: checklista som PDF, Google Calendar och .ics."""

    # -----------------------------------------------------------------------
    # PDF-EXPORT (NY v6.4.1 v7: AI-snygg checklista)
    # -----------------------------------------------------------------------

    def _export_checklist_pdf(self) -> None:
        """
        FIX 2026-09-25: Skriv ut / spara aktiva uppgifter som PDF-checklista
        (modul: core/pdf_export.py — snygg sektionerad design).
        """
        try:
            tasks = self.store.active_tasks() if hasattr(
                self.store, "active_tasks"
            ) else []
        except Exception as _at_e:
            self._log.warning(f"{LOG_PREFIX} PDF-export: task-list misslyckades: {_at_e}")
            tasks = []
        if not tasks:
            try:
                show_error_dialog(
                    title="Inga uppgifter",
                    user_message="Det finns inga aktiva uppgifter att exportera.",
                    technical="",
                    category="user_input",
                )
            except Exception:
                pass
            return
        tasks = [t for t in tasks if str(t.get("id", "")).strip()]
        # Importera PDF-export-modul på begäran (ingen permanent import)
        try:
            from core.pdf_export import render_checklist_html, save_pdf
        except Exception as _pe_imp:
            self._log.error(
                f"{LOG_PREFIX} PDF-export: import misslyckades: {_pe_imp}",
                exc_info=True,
            )
            return
        html = render_checklist_html(
            tasks, app_name=APP_NAME, app_version=APP_VERSION_DISPLAY
        )
        # Fil-dialog
        from PySide6.QtWidgets import QFileDialog
        ts = _datetime.now().strftime("%Y%m%d_%H%M")
        default_name = f"{APP_NAME}_checklista_{ts}.pdf"
        try:
            store_path = (
                getattr(self.store, "file_path", None)
                or getattr(self.store, "_file_path", None)
            )
            default_dir = str(Path(str(store_path)).resolve().parent) \
                if store_path else os.path.expanduser("~")
        except Exception:
            default_dir = os.path.expanduser("~")
        default_path = os.path.join(default_dir, default_name)
        try:
            fname, _ = QFileDialog.getSaveFileName(
                None,
                "Spara checklista som PDF",
                default_path,
                "PDF-dokument (*.pdf)",
            )
        except Exception as _fd_e:
            self._log.warning(
                f"{LOG_PREFIX} PDF-export: file-dialog misslyckades: {_fd_e}"
            )
            fname = ""
        if not fname:
            fname = default_path
            self._log.info(
                f"{LOG_PREFIX} PDF-export: ingen fil vald → {fname}"
            )
        if not str(fname).lower().endswith(".pdf"):
            fname = str(fname) + ".pdf"
        ok = save_pdf(html, str(fname))
        if ok:
            self._log.info(
                f"{LOG_PREFIX} PDF-export klar: {fname} ({len(tasks)} uppgifter)"
            )
            show_error_dialog(
                title="PDF skapad",
                user_message=(
                    f"Checklista sparad till:\n{fname}\n\n{len(tasks)} uppgifter."
                ),
                technical="",
                category="user_input",
            )
        else:
            self._log.warning(
                f"{LOG_PREFIX} PDF-export misslyckades (modul returnerade False)"
            )

    def _open_payment_plan(self) -> None:
        """Tray-menyn: 💸 Delbetalningsplan… (dialogen skapar uppgifterna direkt i butiken)."""
        try:
            from ui.payment_plan_dialog import open_payment_plan_dialog
            ids = open_payment_plan_dialog(None, getattr(self, "store", None))
            if ids:
                for w in list(getattr(self, "_widgets", {}).values()):
                    try:
                        w._schedule_rebuild()
                    except Exception:
                        pass
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} kunde inte öppna delbetalningsplanen: {e}")

    def _open_job_templates(self) -> None:
        """Tray-menyn: 📋 Ny uppgift från mall… (dialogen skapar uppgifterna direkt i butiken)."""
        try:
            from ui.job_template_dialog import open_job_template_dialog
            ids = open_job_template_dialog(None, getattr(self, "store", None), getattr(self, "settings", None))
            if ids:
                for w in list(getattr(self, "_widgets", {}).values()):
                    try:
                        w._schedule_rebuild()
                    except Exception:
                        pass
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} kunde inte öppna jobbmallarna: {e}")

    def _open_google_calendar(self) -> None:
        """
        NY v8 (2026-10-12): öppna Google Calendar-dialogen från tray-menyn.

        Hela kopplingen (OAuth) och alla anrop till Google sköts av
        ui/google_calendar_dialog.py, som kör nätverket i en egen tråd så
        att appen inte fryser.
        """
        try:
            from ui.google_calendar_dialog import open_google_calendar_dialog
            open_google_calendar_dialog(
                None,
                store=getattr(self, "store", None),
                settings=getattr(self, "settings", None),
                data_dir=self._mail_bridge_data_dir(),
            )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} kunde inte öppna Google Calendar-dialogen: {e}"
            )

    def _export_calendar_ics(self) -> None:
        """
        NY v8 (2026-10-12): exportera uppgifter med förfallodatum till .ics
        (Google Calendar, Outlook, Apple Kalender).

        Samma uppgiftslista som Aktiva-fliken visar. Uppgifter utan
        förfallodatum kan inte bli händelser och rapporteras i dialogen.
        """
        try:
            tasks = self.store.active_tasks() if hasattr(
                self.store, "active_tasks"
            ) else []
        except Exception as _at_e:
            self._log.warning(
                f"{LOG_PREFIX} Kalenderexport: task-list misslyckades: {_at_e}"
            )
            tasks = []
        tasks = [t for t in tasks if str(t.get("id", "")).strip()]
        try:
            from core.calendar_export import tasks_with_due, write_ics
        except Exception as _ce_imp:
            self._log.error(
                f"{LOG_PREFIX} Kalenderexport: import misslyckades: {_ce_imp}",
                exc_info=True,
            )
            return
        valda = tasks_with_due(tasks)
        if not valda:
            try:
                show_error_dialog(
                    title="Inga datum",
                    user_message=(
                        "Inga aktiva uppgifter har ett förfallodatum eller startdatum.\n\n"
                        "Sätt ett datum på en uppgift så kan den "
                        "bli en händelse i kalendern."
                    ),
                    technical="",
                    category="user_input",
                )
            except Exception:
                pass
            return
        from PySide6.QtWidgets import QFileDialog
        ts = _datetime.now().strftime("%Y%m%d_%H%M")
        try:
            store_path = (
                getattr(self.store, "file_path", None)
                or getattr(self.store, "_file_path", None)
            )
            default_dir = str(Path(str(store_path)).resolve().parent) \
                if store_path else os.path.expanduser("~")
        except Exception:
            default_dir = os.path.expanduser("~")
        default_path = os.path.join(default_dir, f"{APP_NAME}_kalender_{ts}.ics")
        try:
            fname, _ = QFileDialog.getSaveFileName(
                None,
                "Spara kalenderfil (.ics)",
                default_path,
                "Kalenderfil (*.ics)",
            )
        except Exception as _fd_e:
            self._log.warning(
                f"{LOG_PREFIX} Kalenderexport: file-dialog misslyckades: {_fd_e}"
            )
            fname = ""
        if not fname:
            fname = default_path
            self._log.info(
                f"{LOG_PREFIX} Kalenderexport: ingen fil vald → {fname}"
            )
        if not str(fname).lower().endswith(".ics"):
            fname = str(fname) + ".ics"
        try:
            antal = write_ics(valda, str(fname), calendar_name=APP_NAME)
        except Exception as _w_e:
            self._log.error(
                f"{LOG_PREFIX} Kalenderexport: skrivning misslyckades: {_w_e}",
                exc_info=True,
            )
            return
        hoppade = len(tasks) - antal
        self._log.info(
            f"{LOG_PREFIX} Kalenderexport klar: {fname} ({antal} händelser, "
            f"{hoppade} utan datum)"
        )
        extra = (
            f"\n\n{hoppade} uppgifter utan förfallodatum hoppades över."
            if hoppade > 0 else ""
        )
        try:
            show_error_dialog(
                title="Kalenderfil skapad",
                user_message=(
                    f"{antal} uppgifter exporterade till:\n{fname}{extra}\n\n"
                    "Google Calendar: ⚙️ Inställningar →\n"
                    "Importera och exportera → Importera.\n"
                    "Filen fungerar även i Outlook och Apple Kalender."
                ),
                technical="",
                category="user_input",
            )
        except Exception:
            pass

    # -----------------------------------------------------------------------
    # ☁️ Datum ändrat → flytta händelsen i Google Calendar (core/gcal_autosync.py)
    # -----------------------------------------------------------------------

    def _connect_gcal_autosync(self) -> None:
        """Koppla store.dates_changed → AutoSync. Körs en gång vid start; allt nät sker i en egen tråd."""
        try:
            if not hasattr(self.store, "dates_changed"):
                return
            self._gcal_events = collections.deque(maxlen=20)
            self._gcal_sync = None
            self.store.dates_changed.connect(self._on_task_dates_changed)
            self._log.info(f"{LOG_PREFIX} Google Calendar-synk av datumändringar kopplad")
            # uppgifter som inte hann synkas förra gången provas igen strax efter start
            _t = threading.Timer(20.0, self._gcal_resume)
            _t.daemon = True
            _t.start()
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} kunde inte koppla kalendersynk: {e}")

    def _gcal_autosync(self):
        """Skapa AutoSync vid första behov (först då behövs data-mappen)."""
        a = getattr(self, "_gcal_sync", None)
        if a is None:
            from core.gcal_autosync import AutoSync, options_from_settings
            data = getattr(self.store, "_data_dir", None)
            if not data:
                return None
            a = AutoSync(
                data,
                find_task=lambda tid: self.store.find_task(tid),
                get_options=lambda: options_from_settings(self.settings, data),
                notify=self._gcal_events.append,   # deque.append är trådsäkert; tray visas från GUI-tråden
            )
            self._gcal_sync = a
        return a

    def _gcal_resume(self) -> None:
        with suppress(Exception):
            a = self._gcal_autosync()
            if a is not None and a._opts().get("enabled", True):
                a.resume(delay=0.0)

    def _on_task_dates_changed(self, task_id: str = "") -> None:
        """Start-/förfallodatum ändrat. Kan komma från vilken tråd som helst → rör inget Qt här."""
        with suppress(Exception):
            a = self._gcal_autosync()
            if a is not None:
                a.request(task_id)

    def _drain_gcal_sync_results(self) -> None:
        """GUI-tråden: visa vad synken gjort (liten tray-notis; tyst om inget hänt)."""
        ev = getattr(self, "_gcal_events", None)
        with suppress(Exception):
            from core import job_templates as _jt
            if ev is None:
                ev = self._gcal_events = collections.deque(maxlen=20)
            while _jt.EVENTS:                      # notiser från jobbmallarnas Google-export (egen tråd)
                ev.append(_jt.EVENTS.popleft())
        while ev:
            try:
                r = ev.popleft()
            except IndexError:
                break
            with suppress(Exception):
                if self._tray is None:
                    continue
                titel = str(r.get("title") or "")[:50]
                ok = bool(r.get("ok"))
                if r.get("action") == "uppdaterad":
                    text = f"📅 “{titel}” flyttad i Google Calendar → {r.get('when', '')}"
                elif r.get("action") == "hoppad" and ok:
                    continue
                else:
                    text = f"📅 “{titel}”: {r.get('message', '')}"
                self._tray.showMessage(
                    APP_NAME, text,
                    self._QSystemTrayIcon.MessageIcon.Information if ok else self._QSystemTrayIcon.MessageIcon.Warning,
                    4000,
                )
