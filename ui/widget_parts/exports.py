# -*- coding: utf-8 -*-
"""
ui/widget_parts/exports.py — Export, kalender, mejl och drag-och-släpp: PDF/ICS, Google Kalender, mejlimport, svara på mejl.

Del av TodoWidget (delad ur ui/widget.py). Metoderna är oförändrade; klassen
blandas in i TodoWidget i ui/widget.py. Gemensamma konstanter, hjälpfunktioner
och Qt-importer kommer från ui/widget_base.py, små UI-klasser från ui/widget_atoms.py.
"""
from __future__ import annotations

from ui.widget_base import *  # noqa: F401,F403
from ui.widget_atoms import *  # noqa: F401,F403


class ExportsMixin:
    """Export, kalender, mejl och drag-och-släpp: PDF/ICS, Google Kalender, mejlimport, svara på mejl."""

    # ====================================================================
    # LOCK / UNLOCK (NY v6.4.1 v7-fix: _toggle_lock saknades!)
    # ====================================================================
    # Buggrapport 2026-09-22:
    #   AttributeError: 'TodoWidget' object has no attribute '_toggle_lock'
    #   på rad 1384 (lock_btn.clicked.connect(self._toggle_lock))
    #
    # _init_ui() kopplade signalen men metoden var aldrig definierad.
    # Detta är den saknade implementationen — minimal, robust, AI-felsäker.
    # ====================================================================

    def _input_field_keypress(self, event: QKeyEvent) -> None:
        """
        NY v6.4.1 v7-fix: Piltangenter i input-fältet byter pending prioritet.

        Buggrapport 2026-09-22:
          AttributeError: 'TodoWidget' object has no attribute '_input_field_keypress'
          på rad 1425 (self.input_field.keyPressEvent = self._input_field_keypress)

        Vad den gör:
          ← / →  → byter pending prioritet enligt PRIORITY_CYCLE
          Enter  → normal enter-beteende (returnPressed skickar iväg)
          Övrigt → default keyPressEvent (vanlig text-inmatning)
        """
        try:
            get_throttle().notify_activity()
            key = event.key()
            # NY v7-fix86: Escape i input-fältet rensar texten (om det
            # finns text) — snabb ångra utan att gömma fönstret
            if key == Qt.Key.Key_Escape and self.input_field.text():
                self.input_field.clear()
                self._pending_input_priority = "none"
                self._update_input_priority_indicator()
                logger.debug(
                    f"{LOG_PREFIX} Escape i input-fältet → rensar texten"
                )
                event.accept()
                return
            # FIX v7-fix77: Enter hanteras FÖRST — inget före (t.ex.
            # piltangents-prioritetslogik) ska kunna svälja/senarelägga
            # registreringen av uppgiften i 'Aktiva'.
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                logger.info(
                    f"{LOG_PREFIX} Enter i input-fältet → registrerar "
                    f"uppgiften i 'Aktiva' (v7-fix77)"
                )
                self._on_input_submit()
                event.accept()
                return
            if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
                cur = self._pending_input_priority
                if cur not in PRIORITY_CYCLE:
                    cur = "none"
                idx = PRIORITY_CYCLE.index(cur)
                if key == Qt.Key.Key_Right:
                    new_idx = (idx + 1) % len(PRIORITY_CYCLE)
                else:
                    new_idx = (idx - 1) % len(PRIORITY_CYCLE)
                new_p = PRIORITY_CYCLE[new_idx]
                self._set_input_priority(new_p)
                event.accept()
                return
            # OBS: gamla Enter-grenen (v7-fix30) ersatt av ovan —
            # returnPressed-signalen (rad ~2038) finns kvar som
            # extra försäkring om keyPressEvent-överriden skulle utebli.
            # Default: låt Qt sköta text-inmatning
            from PySide6.QtWidgets import QLineEdit
            QLineEdit.keyPressEvent(self.input_field, event)
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} _input_field_keypress misslyckades: "
                f"{_describe_widget_error(e)}",
                exc_info=True,
            )

    def _on_open_google_calendar(self) -> None:
        """
        NY v8: öppna Google Calendar-dialogen (lokal OAuth-koppling).

        Rickard 2026-10-12: "gör i appen att man lokalt kopplar OAuth"
        — härifrån kopplas kontot, kalendern väljs och uppgifterna skickas.
        """
        try:
            from ui.google_calendar_dialog import open_google_calendar_dialog
            open_google_calendar_dialog(
                self,
                store=getattr(self, "store", None),
                settings=getattr(self, "settings", None),
            )
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} _on_open_google_calendar misslyckades: "
                f"{_describe_widget_error(e)}"
            )

    def _on_open_backup(self) -> None:
        """NY v8: 💾 Backup av uppgifter (skapa/spara/återställ)."""
        try:
            get_throttle().notify_activity()
            from ui.backup_dialog import open_backup_dialog
            open_backup_dialog(self, store=getattr(self, "store", None))
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} _on_open_backup misslyckades: "
                f"{_describe_widget_error(e)}"
            )

    def _on_show_shortcut_help(self) -> None:
        """F1 / fönstermenyn: ⌨️ Tangentöversikt (alla tangenter, med dina inställningar)."""
        try:
            get_throttle().notify_activity()
            from ui.shortcut_help_dialog import open_shortcut_help
            open_shortcut_help(self, settings=getattr(self, "settings", None))
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} _on_show_shortcut_help misslyckades: "
                f"{_describe_widget_error(e)}"
            )

    def _on_push_task_to_google(self, task: Dict[str, Any]) -> None:
        """
        NY v8: skicka EN uppgift till Google Calendar (från uppgiftsmenyn).

        Nätverket sköts i bakgrunden av dialogen, så fönstret inte
        fryser medan Google svarar.
        """
        try:
            get_throttle().notify_activity()
            from ui.google_calendar_dialog import push_task_with_dialog
            push_task_with_dialog(
                self,
                task=dict(task or {}),
                store=getattr(self, "store", None),
                settings=getattr(self, "settings", None),
            )
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} _on_push_task_to_google misslyckades: "
                f"{_describe_widget_error(e)}"
            )

    def _on_show_task_calendar_history(self, task: Dict[str, Any]) -> None:
        """NY v8: sändningshistoriken för EN uppgift (Google Calendar)."""
        try:
            get_throttle().notify_activity()
            from ui.google_calendar_dialog import open_history_dialog
            open_history_dialog(
                self,
                task=dict(task or {}),
                store=getattr(self, "store", None),
                settings=getattr(self, "settings", None),
            )
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} _on_show_task_calendar_history misslyckades: "
                f"{_describe_widget_error(e)}"
            )

    def _on_open_donate(self) -> None:
        """NY v8: visa donationsdialogen (frivilligt, ingen funktion låst)."""
        try:
            from ui.donate import open_donate_dialog
            open_donate_dialog(self)
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} _on_open_donate misslyckades: {e}")

    def _on_export_pdf(self) -> None:
        """
        NY v7-fix81: exportera aktiva uppgifter som PDF-checklista.

        Rickard 2026-10-07: "går det att exportera aktiva till en pdf
        som en modern checklista" — JA: 📄-knapp (bredvid 📧),
        tray-menyn och fönster-högerklicksmenyn. Modern design med
        sektioner, progress-bar, vänliga datum och ☐/☑-rutor.
        """
        try:
            get_throttle().notify_activity()
            # Samma lista som Aktiva-fliken visar (senarelagda dolda)
            tasks: list = []
            with suppress(Exception):
                if hasattr(self.store, "active_tasks_filtered"):
                    tasks = self.store.active_tasks_filtered(
                        sort_by="pinned_first"
                    )
                elif hasattr(self.store, "active_tasks"):
                    tasks = self.store.active_tasks()
            tasks = [t for t in tasks if str(t.get("id", "")).strip()]
            if not tasks:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.information(
                    self,
                    "📄 Exportera PDF",
                    "Det finns inga aktiva uppgifter att exportera.",
                )
                return
            # Importera PDF-modulen på begäran
            try:
                from core.pdf_export import render_checklist_html, save_pdf
            except Exception as e:
                logger.error(
                    f"{LOG_PREFIX} PDF-export: import misslyckades: {e}",
                    exc_info=True,
                )
                return
            html = render_checklist_html(
                tasks,
                app_name=getattr(self, "DEFAULT_TITLE", "Ledgebord"),
            )
            # Fil-dialog (default: samma mapp som js/-data, annars hem)
            from PySide6.QtWidgets import QFileDialog
            ts = datetime.now().strftime("%Y%m%d_%H%M")
            default_name = f"Ledgebord_checklista_{ts}.pdf"
            default_dir = os.path.expanduser("~")
            with suppress(Exception):
                _sp = getattr(self.store, "file_path", None) or getattr(
                    self.store, "_file_path", None
                )
                if _sp:
                    default_dir = str(Path(str(_sp)).resolve().parent)
            default_path = os.path.join(default_dir, default_name)
            fname, _ = QFileDialog.getSaveFileName(
                self,
                "Spara checklista som PDF",
                default_path,
                "PDF-dokument (*.pdf)",
            )
            if not fname:
                return  # avbruten av användaren
            if not str(fname).lower().endswith(".pdf"):
                fname = str(fname) + ".pdf"
            if save_pdf(html, str(fname)):
                logger.info(
                    f"{LOG_PREFIX} PDF-checklista sparad: {fname} "
                    f"({len(tasks)} uppgifter) (v7-fix81)"
                )
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.information(
                    self,
                    "📄 Checklista sparad",
                    f"PDF sparad som:\n{fname}",
                )
            else:
                logger.warning(
                    f"{LOG_PREFIX} PDF-export misslyckades: {fname}"
                )
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(
                    self,
                    "Kunde inte spara PDF",
                    f"PDF-exporten misslyckades för:\n{fname}",
                )
        except Exception as e:
            logger.error(
                f"{LOG_PREFIX} _on_export_pdf misslyckades: "
                f"{_describe_widget_error(e)}",
                exc_info=True,
            )

    def _on_export_calendar_ics(self) -> None:
        """
        NY v8: exportera aktiva uppgifter med förfallodatum till .ics.

        Rickard 2026-10-12: "kan man koppla ihop den med Google
        Calendar så man kan exportera vissa uppgifter dit?" — JA:
        .ics-filen importeras i Google Calendar (Inställningar →
        Importera och exportera), Outlook och Apple Kalender.
        Bara uppgifter som HAR ett förfallodatum kan bli händelser —
        resten hoppas över och antalet redovisas.
        """
        try:
            get_throttle().notify_activity()
            from core.calendar_export import tasks_with_due, write_ics

            tasks: list = []
            with suppress(Exception):
                if hasattr(self.store, "active_tasks_filtered"):
                    tasks = self.store.active_tasks_filtered(
                        sort_by="pinned_first"
                    )
                elif hasattr(self.store, "active_tasks"):
                    tasks = self.store.active_tasks()
            valda = tasks_with_due(list(tasks or []))
            if not valda:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.information(
                    self,
                    "📅 Exportera till kalender",
                    "Inga aktiva uppgifter har ett förfallodatum eller startdatum.\n\n"
                    "Sätt ett datum på en uppgift (⋯-menyn → 📅 Förfallodatum\n"
                    "eller ▶ Startdatum) så kan den bli en kalenderhändelse.",
                )
                return

            from PySide6.QtWidgets import QFileDialog
            ts = datetime.now().strftime("%Y%m%d_%H%M")
            default_dir = os.path.expanduser("~")
            with suppress(Exception):
                _sp = getattr(self.store, "file_path", None) or getattr(
                    self.store, "_file_path", None
                )
                if _sp:
                    default_dir = str(Path(str(_sp)).resolve().parent)
            fname, _ = QFileDialog.getSaveFileName(
                self,
                "Spara kalenderfil (.ics)",
                os.path.join(default_dir, f"Ledgebord_kalender_{ts}.ics"),
                "Kalenderfil (*.ics)",
            )
            if not fname:
                return  # avbruten av användaren
            if not str(fname).lower().endswith(".ics"):
                fname = str(fname) + ".ics"
            antal = write_ics(valda, str(fname), calendar_name="Ledgebord")
            hoppade = len(tasks or []) - antal
            logger.info(
                f"{LOG_PREFIX} Kalenderexport: {antal} händelser → {fname} "
                f"({hoppade} utan datum hoppades över)"
            )
            from PySide6.QtWidgets import QMessageBox
            extra = (
                f"\n\n{hoppade} uppgifter utan förfallodatum hoppades över."
                if hoppade > 0 else ""
            )
            QMessageBox.information(
                self,
                "📅 Kalenderfil sparad",
                f"{antal} uppgifter exporterade till:\n{fname}{extra}\n\n"
                "Så importerar du i Google Calendar:\n"
                "1. Öppna calendar.google.com\n"
                "2. ⚙️ Inställningar → Importera och exportera\n"
                "3. Välj filen → Importera\n\n"
                "(Filen fungerar även i Outlook och Apple Kalender.)",
            )
        except Exception as e:
            logger.error(
                f"{LOG_PREFIX} _on_export_calendar_ics misslyckades: "
                f"{_describe_widget_error(e)}",
                exc_info=True,
            )

    def _on_open_task_in_google_calendar(self, task: Dict[str, Any]) -> None:
        """
        NY v8: öppna Google Calendar med EN uppgift förifylld.

        OBS: hette tidigare _on_open_google_calendar, vilket krockade med
        metoden som öppnar OAuth-dialogen (samma namn två gånger i samma
        klass = den sista vinner tyst, och menyvalet slutade fungera).

        Använder Googles egen "skapa händelse"-länk (action=TEMPLATE)
        — inget konto, ingen nyckel och ingen synk behövs. Ingenting
        sparas förrän användaren trycker Spara i Google Calendar.
        """
        try:
            get_throttle().notify_activity()
            from core.calendar_export import google_calendar_url

            url = google_calendar_url(task)
            if not url:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.information(
                    self,
                    "📅 Google Calendar",
                    "Uppgiften behöver ett förfallodatum eller ett startdatum\n"
                    "för att kunna bli en händelse i kalendern.",
                )
                return
            # stdlib-webb läsare: fungerar oavsett Qt-backend
            import webbrowser
            if webbrowser.open(url):
                logger.info(
                    f"{LOG_PREFIX} Google Calendar-länk öppnad för "
                    f"uppgift {str(task.get('id', ''))[:8]}"
                )
            else:
                logger.warning(
                    f"{LOG_PREFIX} kunde inte öppna webbläsaren för "
                    f"Google Calendar-länken"
                )
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} _on_open_task_in_google_calendar misslyckades: "
                f"{_describe_widget_error(e)}"
            )

    def _on_export_task_ics(self, task: Dict[str, Any]) -> None:
        """NY v8: exportera EN uppgift till en egen .ics-fil."""
        try:
            get_throttle().notify_activity()
            from core.calendar_export import has_calendar_date, write_ics

            if not has_calendar_date(task):
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.information(
                    self,
                    "📅 Exportera uppgift",
                    "Uppgiften behöver ett förfallodatum eller ett startdatum\n"
                    "för att kunna bli en kalenderhändelse.",
                )
                return
            from PySide6.QtWidgets import QFileDialog
            titel = str(task.get("title", "uppgift"))
            säker = "".join(
                c for c in titel[:40] if c.isalnum() or c in " -_"
            ).strip() or "uppgift"
            default_dir = os.path.expanduser("~")
            with suppress(Exception):
                _sp = getattr(self.store, "file_path", None) or getattr(
                    self.store, "_file_path", None
                )
                if _sp:
                    default_dir = str(Path(str(_sp)).resolve().parent)
            fname, _ = QFileDialog.getSaveFileName(
                self,
                "Spara uppgiften som kalenderfil",
                os.path.join(default_dir, f"{säker}.ics"),
                "Kalenderfil (*.ics)",
            )
            if not fname:
                return
            if not str(fname).lower().endswith(".ics"):
                fname = str(fname) + ".ics"
            write_ics([task], str(fname), calendar_name="Ledgebord")
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                self,
                "📅 Kalenderfil sparad",
                f"Uppgiften sparad som:\n{fname}",
            )
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} _on_export_task_ics misslyckades: "
                f"{_describe_widget_error(e)}"
            )

    def _on_email_import(self) -> None:
        """
        NY v7-fix35: Importera e-postfil (.eml/.msg) som uppgift.
        NY v7-fix41: delar kärna med dra-och-släpp (_import_email_files).
        """
        try:
            get_throttle().notify_activity()
            from PySide6.QtWidgets import QFileDialog
            file_paths, _ = QFileDialog.getOpenFileNames(
                self,
                "Importera e-post som uppgift",
                "",
                "E-postfiler (*.eml *.msg);;Alla filer (*.*)",
            )
            if not file_paths:
                return
            self._import_email_files(list(file_paths))
        except Exception as e:
            logger.error(
                f"{LOG_PREFIX} _on_email_import misslyckades: {e}",
                exc_info=True,
            )

    def _import_email_files(self, file_paths: List[str]) -> None:
        """
        NY v7-fix41: importera e-postfiler (.eml/.msg) som uppgifter.

        Används av BÅDE fil-dialogen (📧-knappen) och dra-och-släpp:
        dra ett mail direkt från Outlook (.msg) eller Thunderbird (.eml)
        och släpp det på widgeten — uppgiften skapas direkt.

        FIX v7-fix88 (Rickard: "händer inget när man importerar e-post"):
          - ALLTID synlig återkoppling: nya uppgifter FLASHAS fram i
            Aktiva (fix77-mekanismen), dedup-visas tydligt och fel
            ger en ruta med anledning — aldrig tyst igen
          - .msg utan tillägget extract-msg → tydlig ruta med lösning
        """
        imported = 0
        duplicates = 0
        failures: List[str] = []
        try:
            from core.email_import import import_email
            # NY v7-fix88: .msg kräver extract-msg — kolla FÖRST så att
            # felrutan kan förklara lösningen
            _need_msg_plugin = any(
                str(fp).lower().endswith(".msg") for fp in file_paths
            )
            _msg_plugin_ok = True
            if _need_msg_plugin:
                try:
                    import extract_msg  # noqa: F401
                except ImportError:
                    _msg_plugin_ok = False
            for fp in file_paths:
                _info: Dict[str, Any] = {}
                task_id = import_email(
                    Path(fp), self.store,
                    Path(__file__).resolve().parent.parent / "data",
                    info=_info,
                )
                if task_id:
                    if _info.get("duplicate"):
                        duplicates += 1
                    else:
                        imported += 1
                    # FIX v7-fix88: FLASHA uppgiften i Aktiva så att
                    # importen alltid SYNDS (även befintlig vid dedup)
                    with suppress(Exception):
                        self._show_task_in_active(task_id)
                else:
                    failures.append(str(fp))
            logger.info(
                f"{LOG_PREFIX} E-post-import: {imported} nya, "
                f"{duplicates} redan importerade, {len(failures)} fel "
                f"(av {len(file_paths)} filer) (v7-fix88)"
            )
            # --- NY v7-fix88: ALLTID användarfeedback ----------------
            from PySide6.QtWidgets import QMessageBox
            if failures:
                _msg_plugin_hint = (
                    "\n\nOutlook-filer (.msg) kräver tillägget "
                    "extract-msg.\nInstallera via tray-menyn → "
                    "📦 Installera/Uppdatera tillägg."
                    if _need_msg_plugin and not _msg_plugin_ok else ""
                )
                QMessageBox.warning(
                    self,
                    "📧 E-postimport — problem",
                    f"{len(failures)} av {len(file_paths)} fil(er) "
                    f"kunde inte importeras:\n\n"
                    + "\n".join(f"• {Path(f).name}" for f in failures)
                    + _msg_plugin_hint,
                )
            elif duplicates and not imported:
                QMessageBox.information(
                    self,
                    "📧 Redan importerad",
                    f"Alla {duplicates} e-post(er) var redan importerade "
                    f"— deras uppgifter visas nu (markerade).",
                )
            # (lyckad import: flashen i Aktiva RÄCKER — ingen ruta som
            # stör; loggen + listan + flikbyte + scroll visar det)
        except Exception as e:
            logger.error(
                f"{LOG_PREFIX} _import_email_files misslyckades: {e}",
                exc_info=True,
            )
            with suppress(Exception):
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(
                    self,
                    "📧 E-postimport misslyckades",
                    f"Ett oväntat fel uppstod:\n{e}",
                )

    def _is_outlook_drag(self, mime_data: Any) -> bool:
        """
        NY v7-fix88: är detta ett direkt-drag FRÅN Outlook?

        Outlook ger inga fil-URL:er vid drag — bara FileGroupDescriptor-
        formatet. Qt mappar det till windows-mime-format. Tidigare
        avvisades dessa drags TYST ("händer inget") — nu accepteras
        de och användaren får en hjälpsam instruktion istället.
        """
        try:
            for fmt in (
                'application/x-qt-windows-mime;value="FileGroupDescriptorW"',
                'application/x-qt-windows-mime;value="FileGroupDescriptor"',
                "application/x-qt-windows-mime;value=FileGroupDescriptorW",
            ):
                if mime_data.hasFormat(fmt):
                    return True
            # Fallback: lista alla format och leta efter nyckelord
            with suppress(Exception):
                for fmt in mime_data.formats():
                    if "FileGroupDescriptor" in str(fmt):
                        return True
            return False
        except Exception:
            return False

    def dragEnterEvent(self, event: Any) -> None:
        """
        NY v7-fix41: acceptera .eml/.msg-filer som dras in (Outlook/
        Thunderbird → widgeten).

        FIX v7-fix88: acceptera ÄVEN direkt-drag från Outlook
        (FileGroupDescriptor — inga fil-URL:er). Själva filen kan
        inte läsas av Qt, men dropEvent ger användaren en tydlig
        instruktion i stället för tyst avvisning ("händer inget").
        """
        try:
            if event.mimeData().hasUrls():
                for url in event.mimeData().urls():
                    if str(url.toLocalFile()).lower().endswith(
                        (".eml", ".msg")
                    ):
                        event.acceptProposedAction()
                        return
            # NY v7-fix88: Outlook direkt-drag
            if self._is_outlook_drag(event.mimeData()):
                event.acceptProposedAction()
                return
            super().dragEnterEvent(event)
        except Exception:
            super().dragEnterEvent(event)

    def dropEvent(self, event: Any) -> None:
        """
        NY v7-fix41: släpp e-post → skapa uppgift.
        FIX v7-fix88: Outlook direkt-drag → hjälpsam instruktion.
        """
        try:
            if event.mimeData().hasUrls():
                files = [
                    str(url.toLocalFile())
                    for url in event.mimeData().urls()
                    if str(url.toLocalFile()).lower().endswith(
                        (".eml", ".msg")
                    )
                ]
                if files:
                    event.acceptProposedAction()
                    get_throttle().notify_activity()
                    self._import_email_files(files)
                    return
            # NY v7-fix88: direkt-drag från Outlook → instruktion
            if self._is_outlook_drag(event.mimeData()):
                event.acceptProposedAction()
                get_throttle().notify_activity()
                logger.info(
                    f"{LOG_PREFIX} Direkt-drag från Outlook upptäckt — "
                    f"ger instruktion (v7-fix88)"
                )
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.information(
                    self,
                    "📧 Dra från Outlook",
                    "Outlook-mailet måste sparas som fil först:\n\n"
                    "1. Dra mailet till skrivbordet/en mapp\n"
                    "   (det blir en .msg-fil)\n"
                    "2. Dra .msg-filen till Ledgebord\n\n"
                    "Tips: du kan också använda 📧-knappen nedan\n"
                    "eller spara mailet som .eml i Thunderbird.",
                )
                return
            super().dropEvent(event)
        except Exception:
            super().dropEvent(event)

    def _open_task_email(self, task: Dict[str, Any]) -> None:
        """
        "Öppna mejlet": originalfilen (.eml/.msg) i standardprogrammet;
        finns den inte kvar visas den sparade mailtexten i stället.
        """
        try:
            from core.email_import import open_task_email
            data_dir = getattr(self.store, "data_dir", None)
            if open_task_email(task, data_dir):
                return
            has_text = any(
                task.get(k) for k in ("email_body", "email_subject", "email_from")
            )
            if has_text:
                from ui.mail_view_dialog import MailViewDialog
                note = (
                    "Originalfilen finns inte kvar (eller gick inte att "
                    "öppna) — här är texten som sparades på uppgiften."
                    if task.get("email_path") else ""
                )
                MailViewDialog(task, self, note).exec()
            else:
                from PySide6.QtWidgets import QMessageBox as _QMB
                _QMB.information(
                    self, "Öppna mejlet",
                    "Varken originalmailet eller dess text finns sparad "
                    "på den här uppgiften.\n\n"
                    + (f"Message-ID: {task.get('email_message_id')}"
                       if task.get("email_message_id") else ""),
                )
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} _open_task_email misslyckades: {e}",
                exc_info=True,
            )

    def _reply_to_task_email(self, task: Dict[str, Any]) -> None:
        """
        "Svara på mejlet": öppnar ett färdigt svar (till, "Re: ämne", citerad text) i
        standard-mailprogrammet. Svaret hamnar inte i samma TRÅD (mailto kan inte
        bära In-Reply-To).
        """
        try:
            from PySide6.QtWidgets import QMessageBox as _QMB
            from core.email_import import find_email_file
            from core.mail_reply import build_mailto, open_mailto, reply_info
            data_dir = getattr(self.store, "data_dir", None)
            info = reply_info(task, find_email_file(task, data_dir))
            if info is None:
                _QMB.information(
                    self, "Svara på mejlet",
                    "Hittar ingen avsändaradress på den här uppgiften, så det "
                    "går inte att skapa ett svar.",
                )
                return
            if not open_mailto(build_mailto(info)):
                _QMB.warning(
                    self, "Svara på mejlet",
                    "Kunde inte öppna något mailprogram.\n\n"
                    f"Mottagare: {info['to']}\nÄmne: {info['subject']}",
                )
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} _reply_to_task_email misslyckades: {e}",
                exc_info=True,
            )

    def _open_email(self, email_path: str) -> None:
        """NY v7-fix35: Öppna sparad e-postfil i standardprogrammet."""
        try:
            from core.email_import import open_email
            open_email(email_path)
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} _open_email misslyckades: {e}"
            )
