# -*- coding: utf-8 -*-
"""Systemfältsikon, tray-meny och snabbåtgärder därifrån."""

from __future__ import annotations

import time
from contextlib import suppress
from typing import Any

from app.config import error_boundary
from app.constants import APP_NAME, APP_VERSION_DISPLAY, AppMode, IconState, LOG_PREFIX


class TrayMixin:
    """Systemfältsikon, tray-meny och snabbåtgärder därifrån."""

    # -----------------------------------------------------------------------
    # TRAY — init, populate, create_icon
    # -----------------------------------------------------------------------

    def _init_tray(self) -> None:
        """Initiera system tray (med ikon + meny + tooltip)."""
        if self._QSystemTrayIcon is None:
            self._log.warning("QSystemTrayIcon saknas — hoppar över tray-init")
            return
        if not self._QSystemTrayIcon.isSystemTrayAvailable():
            self._log.warning("System tray ej tillgängligt på denna plattform")
            return

        with error_boundary("tray.create"):
            self._tray = self._QSystemTrayIcon(self._app)

            # Ikon (samma som app-ico om den finns — annars ritad cirkel)
            if self._app_icon is not None:
                icon = self._app_icon
            else:
                icon = self.create_icon(state=IconState.NORMAL, color="#818cf8")
            self._tray.setIcon(icon)

            # Tooltip (uppdateras dynamiskt)
            self._update_tray_tooltip()

            # Meny
            self._populate_tray_menu()

            # Visa
            self._tray.show()
            self._tray.activated.connect(self._on_tray_activated)
            self._tray_initialized.set()
            self._log.info("✓ Tray initierat")

    def _populate_tray_menu(self) -> None:
        """
        Bygger om tray-menyn med live-stats och alla actions.
        Anropas vid: init, task-add, theme-change, periodic update.
        """
        if self._tray is None or self._QMenu is None:
            return
        try:
            # Återanvänd befintlig meny om möjligt
            if self._tray_menu is None:
                self._tray_menu = self._QMenu()
            else:
                self._tray_menu.clear()

            # Header (info)
            active_count = 0
            archived_count = 0
            if hasattr(self.store, "count"):
                active_count, archived_count = self.store.count()
            uptime = self._performance.format_uptime()
            mem_mb = self._performance.take_snapshot().memory_mb

            header = self._tray_menu.addAction(
                f"📋 {APP_NAME} v{APP_VERSION_DISPLAY}"
            )
            header.setEnabled(False)
            stats_action = self._tray_menu.addAction(
                f"  {active_count} aktiva • {archived_count} arkiverade"
            )
            stats_action.setEnabled(False)
            mem_action = self._tray_menu.addAction(
                f"  Minne: {mem_mb:.1f} MB • Uptime: {uptime}"
            )
            mem_action.setEnabled(False)
            self._tray_menu.addSeparator()

            # === HUVUDAKTIONER ===
            # NY v6.4: "Visa vid markören" — placerar fönster där muspekaren är
            show_action = self._QAction("👁  Visa fönster vid markören", self._tray_menu)
            show_action.triggered.connect(self._show_window_at_cursor)
            self._tray_menu.addAction(show_action)

            # NY v6.4.1: Snabbuppgift fran tray (utan att oppna fonstret forst)
            quick_add_action = self._QAction(
                "➕  Snabbuppgift... (fran tray)", self._tray_menu
            )
            quick_add_action.setToolTip(
                "Lagg till ny uppgift direkt (utan att oppna widget-fonstret)"
            )
            quick_add_action.triggered.connect(self._tray_quick_add_task)
            self._tray_menu.addAction(quick_add_action)
            clip_action = self._QAction("📋  Ny uppgift från urklipp", self._tray_menu)
            clip_action.setToolTip(
                "Gör texten som ligger i urklippet till en uppgift\n"
                "(med snabbtangenten görs det direkt från markerad text)"
            )
            clip_action.triggered.connect(self._clip_task_from_clipboard)
            self._tray_menu.addAction(clip_action)

            # Snabbtangenten för ny uppgift: synlig och ändringsbar direkt
            # i huvudmenyn (inte bara gömd under Snabbkommandon)
            _qa_on = True
            with suppress(Exception):
                _qa_on = bool(self.settings.global_quick_add())
            _qa_now = self._get_quick_add_hotkey_combo() if _qa_on else "av"
            change_qa_action = self._QAction(
                f"⌨️  Ändra snabbtangent för ny uppgift… ({_qa_now})",
                self._tray_menu,
            )
            change_qa_action.setToolTip(
                "Tryck den tangentkombination du vill ha — gäller direkt"
            )
            change_qa_action.triggered.connect(
                self._change_quick_add_hotkey_dialog
            )
            self._tray_menu.addAction(change_qa_action)

            # "Lås upp alla" (om något är låst)
            any_locked = any(
                getattr(w, "_locked", False)
                for w in self._widgets.values()
            )
            if any_locked:
                unlock_action = self._QAction(
                    "🔓  Lås upp alla fönster", self._tray_menu
                )
                unlock_action.triggered.connect(
                    lambda: self._set_all_windows_locked(False)
                )
                self._tray_menu.addAction(unlock_action)
            else:
                lock_action = self._QAction(
                    "🔒  Lås alla fönster", self._tray_menu)
                lock_action.triggered.connect(
                    lambda: self._set_all_windows_locked(True)
                )
                self._tray_menu.addAction(lock_action)

            self._tray_menu.addSeparator()

            # NY v6.4.1: Focus Mode (1 task stort, importerad fran §22.18 Todoist)
            focus_action = self._QAction(
                "🎯  Focus Mode (F3)", self._tray_menu
            )
            focus_action.setToolTip(
                "Visa EN uppgift i taget (stor) med navigering "
                "(← →, Enter=Markera klar, Esc=Avsluta)"
            )
            focus_action.triggered.connect(self._toggle_focus_mode_all_windows)
            self._tray_menu.addAction(focus_action)

            # FIX 2026-09-25: PDF-export av checklista (klickbar i Snabbåtgärder)
            self._export_pdf_action = self._QAction(
                "📄  Exportera checklista → PDF…",
                self._tray_menu,
            )
            self._export_pdf_action.setToolTip(
                "Exportera aktiva uppgifter som en snyggt designad PDF-checklista.\n"
                "Välj filnamn i dialogen."
            )
            self._export_pdf_action.triggered.connect(self._export_checklist_pdf)
            self._tray_menu.addAction(self._export_pdf_action)

            # NY v8 (2026-10-12): kalenderexport (.ics) → Google Calendar m.fl.
            self._export_calendar_action = self._QAction(
                "📅  Exportera till kalender (.ics)…",
                self._tray_menu,
            )
            self._export_calendar_action.setToolTip(
                "Exportera uppgifter med förfallodatum som kalenderfil.\n"
                "Importeras i Google Calendar (Inställningar → Importera\n"
                "och exportera), Outlook och Apple Kalender."
            )
            self._export_calendar_action.triggered.connect(self._export_calendar_ics)
            self._tray_menu.addAction(self._export_calendar_action)

            # NY v8 (2026-10-12): lokal Google Calendar-koppling (OAuth)
            self._google_calendar_action = self._QAction(
                "☁️  Google Calendar (koppla konto)…",
                self._tray_menu,
            )
            self._google_calendar_action.setToolTip(
                "Koppla ett Google-konto lokalt: inloggningen sker i din\n"
                "webbläsare och svaret kommer till 127.0.0.1. Därefter kan\n"
                "uppgifter skickas rakt in i kalendern."
            )
            self._google_calendar_action.triggered.connect(
                self._open_google_calendar
            )
            self._tray_menu.addAction(self._google_calendar_action)

            # NY v8 (2026-10-13): uppdatera appen inifrån (GitHub-releasen Latest)
            self._update_action = self._QAction(self._update_action_text(), self._tray_menu)
            self._update_action.setToolTip(
                "Hämtar senaste releasen från GitHub och byter ut programfilerna.\n"
                "Dina uppgifter och inställningar (js\\ och data\\) rörs inte."
            )
            self._update_action.triggered.connect(lambda _c=False: self._check_for_updates())
            self._tray_menu.addAction(self._update_action)

            _auto_upd_on = bool(self.settings.update_check_enabled())
            _auto_upd = self._QAction(
                f"{'✅' if _auto_upd_on else '⚪'}  Sök ny version automatiskt (1 gång/dygn)",
                self._tray_menu,
            )
            _auto_upd.setCheckable(True)
            _auto_upd.setChecked(_auto_upd_on)
            _auto_upd.setToolTip(
                "Kollar tyst i bakgrunden vid start och sedan högst en gång per dygn.\n"
                "Du får bara en notis när det FINNS en ny version — inget installeras\n"
                "utan att du godkänner det."
            )
            _auto_upd.triggered.connect(self._toggle_auto_update)
            self._tray_menu.addAction(_auto_upd)

            # Ny Thunderbird-.xpi väntar på att installeras om
            _addon_act = self._addon_tray_action()
            if _addon_act is not None:
                self._tray_menu.addAction(_addon_act)

            # NY v8 (2026-10-12): backup av uppgifter
            self._backup_tasks_action = self._QAction(
                "💾  Backup av uppgifter…", self._tray_menu
            )
            self._backup_tasks_action.setToolTip(
                "Säkerhetskopiera alla uppgifter till en ZIP-fil,\n"
                "spara en kopia på USB/moln-mapp eller återställ."
            )
            self._backup_tasks_action.triggered.connect(self._open_backup_dialog)
            self._tray_menu.addAction(self._backup_tasks_action)

            self._tray_menu.addSeparator()

            # NY v6.4.1: Autostart toggle (med live-status från registry)
            autostart_on = self._is_autostart_active()
            # NY v7-fix36: Installera/Uppdatera tillägg i tray-menyn
            # NY v7-fix50: auto-uppdatering av tillägg vid start
            _auto_plug_on = (
                self.settings.auto_update_plugins()
                if hasattr(self.settings, "auto_update_plugins")
                else True
            )
            auto_plugin_action = self._QAction(
                "🔄  Auto-uppdatera tillägg vid start", self._tray_menu
            )
            auto_plugin_action.setCheckable(True)
            auto_plugin_action.setChecked(bool(_auto_plug_on))
            auto_plugin_action.setToolTip(
                "Saknade tillägg installeras och föråldrade uppdateras\n"
                "automatiskt 30 sekunder efter appstart (bakgrund)."
            )
            auto_plugin_action.toggled.connect(
                self._toggle_auto_update_plugins
            )
            self._tray_menu.addAction(auto_plugin_action)

            # NY v7-fix64: påminnelser av/på
            _rem_on = (
                self.settings.reminders_enabled()
                if hasattr(self.settings, "reminders_enabled")
                else True
            )
            reminders_action = self._QAction(
                "🔔  Påminnelser (förfallna uppgifter)", self._tray_menu
            )
            reminders_action.setCheckable(True)
            reminders_action.setChecked(bool(_rem_on))
            reminders_action.setToolTip(
                "Windows-notis när uppgifter passerat förfallodatum\n"
                "eller förfaller idag (kontroll var minut)."
            )
            reminders_action.toggled.connect(self._toggle_reminders)
            self._tray_menu.addAction(reminders_action)

            # NY v7-fix82: tema-undermeny (Ljust/Mörkt/Auto/Följ Windows)
            # Auto = klockstyrt: ljust 07:00–18:59, mörkt 19:00–06:59 —
            # växlar automatiskt medan appen kör (widget-timer 10 min)
            with suppress(Exception):
                _theme_now = (
                    self.settings.theme_raw()
                    if hasattr(self.settings, "theme_raw")
                    else "system"
                )
                _theme_menu = self._tray_menu.addMenu(
                    "🎨  Tema"
                    + (
                        "  (🌗 Auto aktivt)"
                        if _theme_now == "auto"
                        else ""
                    )
                )
                for _tv, _tl in (
                    ("light", "☀️  Ljust"),
                    ("dark", "🌙  Mörkt"),
                    ("auto", "🌗  Auto (ljust dag • mörkt kväll)"),
                    ("system", "🖥️  Följ Windows"),
                ):
                    _ta = _theme_menu.addAction(_tl)
                    _ta.setCheckable(True)
                    _ta.setChecked(_theme_now == _tv)
                    _ta.triggered.connect(
                        lambda _c=False, v=_tv: self._set_theme_value(v)
                    )

            # NY v7-fix74: konfigurera lyft-tid (tray-klick)
            _secs_now = 5
            with suppress(Exception):
                if hasattr(self.settings, "tray_lift_seconds"):
                    _secs_now = int(self.settings.tray_lift_seconds())
                else:
                    _secs_now = int(
                        self.settings.get("tray_lift_seconds", 5)
                    )
            lift_secs_menu = self._tray_menu.addMenu(
                f"⏱  Lyft-tid vid tray-klick ({_secs_now} s)"
            )
            for _sv in (2, 3, 5, 8, 10, 15, 20, 30):
                _sa = lift_secs_menu.addAction(f"{_sv} sekunder")
                _sa.setCheckable(True)
                _sa.setChecked(_sv == _secs_now)
                _sa.triggered.connect(
                    lambda _c=False, s=_sv: self._set_tray_lift_seconds(s)
                )

            # NY v7-fix69: ändra push-to-show-hotkey
            # FIX v7-fix83: nu en undermeny med BÅDA hotkeys (ny uppgift +
            # visa fönstret) — båda är användarbytbara
            _hk_menu = self._tray_menu.addMenu(
                f"⌨️  Snabbkommandon"
            )
            _qa = _hk_menu.addAction(
                f"➕  Ny uppgift…  ({self._get_quick_add_hotkey_combo()})"
            )
            _qa.setToolTip(
                "Global snabbknapp som öppnar snabbinput för ny uppgift\n"
                "VAR SOM HELST i Windows (default: Ctrl+Alt+N)."
            )
            _qa.triggered.connect(self._change_quick_add_hotkey_dialog)
            _ps = _hk_menu.addAction(
                f"👁  Visa fönstret…  ({self._get_push_hotkey_combo()})"
            )
            _ps.setToolTip(
                "Snabbknappen som visar fönstret över appar\n"
                "medan du håller den intryckt (default: Ctrl+Alt+V)."
            )
            _ps.triggered.connect(self._change_push_hotkey_dialog)
            _cl_on = self._clip_task_enabled()
            _cl = _hk_menu.addAction(
                f"📋  Lägg till från urklipp…  "
                f"({self._get_clip_task_combo() if _cl_on else 'av'})"
            )
            _cl.setToolTip(
                "Markera text i valfritt program och tryck tangenten —\n"
                "texten blir en uppgift direkt (default: Ctrl+Alt+K)."
            )
            _cl.triggered.connect(self._change_clip_task_hotkey_dialog)
            plugin_action = self._QAction("📦  Installera/Uppdatera tillägg")
            plugin_action.setToolTip(
                "Kontrollera och installera saknade Python-paket\n"
                "eller uppdatera föråldrade versioner"
            )
            plugin_action.triggered.connect(self._on_plugin_check)
            self._tray_menu.addAction(plugin_action)
            self._tray_menu.addSeparator()

            autostart_action = self._QAction(
                f"{'✅' if autostart_on else '⚪'}  Starta med datorn",
                self._tray_menu,
            )
            autostart_action.setCheckable(True)
            autostart_action.setChecked(autostart_on)
            autostart_action.setToolTip(
                "När aktiverad: appen startar automatiskt vid inloggning i Windows "
                "(via HKCU\\...\\Run, pythonw.exe — ingen konsol)"
            )
            autostart_action.triggered.connect(self._toggle_autostart)
            self._tray_menu.addAction(autostart_action)
            self._autostart_action_ref = autostart_action  # Spara ref för uppdatering

            # Starta minimerad (kopplat till start_minimized_to_tray)
            start_minimized = (
                self.settings.start_minimized()
                if hasattr(self.settings, "start_minimized")
                else False
            )
            minimized_action = self._QAction(
                f"{'✅' if start_minimized else '⚪'}  Starta minimerad i tray",
                self._tray_menu,
            )
            minimized_action.setCheckable(True)
            minimized_action.setChecked(start_minimized)
            minimized_action.setToolTip(
                "När aktiverad: appen startar gömd i systemfältet "
                "(syns inte förrän du klickar på ikonen)"
            )
            minimized_action.triggered.connect(self._toggle_start_minimized)
            self._tray_menu.addAction(minimized_action)
            self._minimized_action_ref = minimized_action

            self._tray_menu.addSeparator()

            new_action = self._QAction("➕  Ny uppgift…", self._tray_menu)
            new_action.triggered.connect(self.ask_new_task)
            self._tray_menu.addAction(new_action)

            # NY v7-fix40: dynamisk label — i enbart-läge visas det
            # befintliga fönstret i stället för att skapas ett nytt
            _has_windows = bool(self._widgets)
            _single_mode = self._single_window_enabled()
            new_window_action = self._QAction(
                "🪟  Visa fönstret"
                if (_single_mode and _has_windows)
                else "🪟  Nytt fönster",
                self._tray_menu,
            )
            if _single_mode and _has_windows:
                new_window_action.setToolTip(
                    "Enbart-läge: visar det befintliga fönstret\n"
                    "(skapar inget nytt)"
                )
            new_window_action.triggered.connect(lambda: self.add_window(150, 150))
            self._tray_menu.addAction(new_window_action)

            # NY v7-fix47: nollställ/centrera i TRAY-menyn
            # (Rickard: "i tray menyn, ej högerklick på fönstret")
            reset_win_action = self._QAction(
                "🎯  Centrera fönstret", self._tray_menu
            )
            reset_win_action.setToolTip(
                "Centrerar fönstret — BEHÅLLER din storlek\n"
                "(v7-fix72). Nollställ storlek: högerklicka fönstret."
            )
            reset_win_action.triggered.connect(self._tray_center_window)
            self._tray_menu.addAction(reset_win_action)

            # NY v7-fix61: storleksförinställningar (ikon → stor)
            size_menu = self._tray_menu.addMenu("📐  Fönsterstorlek")
            _size_items = (
                ("🖥  Ikon (150×230)", 150, 230),
                ("📟  Kompakt (240×400)", 240, 400),
                ("📋  Standard (340×648)", 340, 648),
                ("📰  Stor (480×750)", 480, 750),
                ("🖥️  Max skärm (90 %)", -1, -1),
            )
            for _lbl, _sw_, _sh_ in _size_items:
                _sa = size_menu.addAction(_lbl)
                _sa.triggered.connect(
                    lambda _c=False, ww=_sw_, hh=_sh_:
                        self._set_window_size_preset(
                            ww, hh
                        ) if ww > 0 else self._set_window_size_max()
                )

            # NY v7-fix57: visa ovanpå appar / fäst igen
            float_action = self._QAction(
                "🪝  Visa ovanpå appar (tills vidare)", self._tray_menu
            )
            float_action.setToolTip(
                "Lossar fönstret från skrivbordet så det syns\n"
                "bland dina appar. Återgå med 'Fäst på skrivbordet'."
            )
            float_action.triggered.connect(self._float_window_above_apps)
            self._tray_menu.addAction(float_action)

            pin_action = self._QAction(
                "📌  Fäst på skrivbordet igen", self._tray_menu
            )
            pin_action.setToolTip(
                "Fäster tillbaka fönstret på skrivbordet\n"
                "(ovanpå ikonerna, under appar, Win+D-säkert)"
            )
            pin_action.triggered.connect(self._pin_window_to_desktop)
            self._tray_menu.addAction(pin_action)

            self._tray_menu.addSeparator()

            # === GLASMORPHISM SUBMENU ===
            glass_menu = self._tray_menu.addMenu("✨  Glasmorphism")
            for style in self._config.glass_styles:
                act = glass_menu.addAction(style.capitalize())
                act.setCheckable(True)
                act.setChecked(self._glass_style == style)
                act.triggered.connect(
                    lambda checked=False, s=style: self._set_glass_style(s)
                )

            # === NY v7-fix38: SKRIVBORDSLÄGE (Win+D-säkert) ===
            desktop_menu = self._tray_menu.addMenu("🖼  Skrivbordsläge (Win+D-säkert)")
            _cur_mode = self._desktop_mode()
            # NY v7-fix45: LEGACY dolt ur menyn — det är en AUTOMATISK
            # nödfallback (above→behind→legacy), inte ett användarval.
            # v7-fix56: legacy är HELT borttaget — bara above/behind finns.
            # 'above' (över ikonerna) visade sig osynligt på din skärm och migreras
            # automatiskt till 'behind' — därför bara två val: som förut, eller alltid överst.
            _mode_items = (
                ("behind", "Bakom ikonerna (som förut)"),
                ("top", "Alltid överst (ovanpå alla fönster)"),
            )
            for _m_val, _m_label in _mode_items:
                act = desktop_menu.addAction(_m_label)
                act.setCheckable(True)
                act.setChecked(_cur_mode == _m_val)
                act.setToolTip(
                    "'Bakom ikonerna' = som förut: widgeten ligger på\n"
                    "skrivbordet, ikonerna målas ovanpå (Rainmeter-metoden),\n"
                    "Win+D kan aldrig gömma den.\n"
                    "'Alltid överst' = widgeten ligger ovanpå alla andra\n"
                    "fönster hela tiden. Valet sparas."
                )
                act.triggered.connect(
                    lambda checked=False, m=_m_val: self._set_desktop_mode(m)
                )

            # === NY v7-fix38: TRANSPARENS ===
            transp_menu = self._tray_menu.addMenu("🫧  Transparens")
            _cur_transp = self._window_transparency_value()
            _transp_items = (
                (1.0, "100 % (opak panel)"),
                (0.85, "85 % (default)"),
                (0.7, "70 %"),
                (0.55, "55 %"),
                (0.0, "Av (helt opak fönster)"),
            )
            for _t_val, _t_label in _transp_items:
                act = transp_menu.addAction(_t_label)
                act.setCheckable(True)
                act.setChecked(abs(_cur_transp - _t_val) < 0.01)
                act.setToolTip(
                    "Hur genomskinligt glas-skalet är — skrivbordsikonerna\n"
                    "syns igenom widgeten (kräver läget 'Över ikonerna')."
                )
                act.triggered.connect(
                    lambda checked=False, v=_t_val: self._set_window_transparency(v)
                )

            # === NY v7-fix90: E-POST & THUNDERBIRD ==========================
            # Rickard: "importera uppgifter från mail via thunderbird" —
            # bryggan (localhost) + inkorgsmappen + tilläggets inställningar.
            try:
                _svc = getattr(self, "_mail_bridge", None)
                _status = _svc.status() if _svc is not None else None
                _http_on = bool(
                    _status["http_running"] if _status else False
                )
                _watch_on = bool(
                    _status["watch_running"] if _status else False
                )
                _mail_menu = self._tray_menu.addMenu("📧  E-post & Thunderbird")

                _act_bridge = _mail_menu.addAction(
                    f"{'✅' if _http_on else '⚪'}  Brygga (lokal server)"
                )
                _act_bridge.setCheckable(True)
                _act_bridge.setChecked(_http_on)
                _act_bridge.setToolTip(
                    "Tar emot mail från Thunderbird-tillägget på\n"
                    "127.0.0.1 (bara denna dator) och skapar uppgifter.\n"
                    "Uppgifterna sparas direkt i data/active.json (JSON)."
                )
                _act_bridge.triggered.connect(self._toggle_mail_bridge)

                _act_inbox = _mail_menu.addAction(
                    f"{'✅' if _watch_on else '⚪'}  Bevaka inkorgsmappen "
                    f"(data/inbox)"
                )
                _act_inbox.setCheckable(True)
                _act_inbox.setChecked(_watch_on)
                _act_inbox.setToolTip(
                    "Släpp .eml/.msg/.json i data/inbox/ → importeras\n"
                    "automatiskt (även mail som kom när appen var avstängd)."
                )
                _act_inbox.triggered.connect(self._toggle_inbox_watch)

                _info_action = _mail_menu.addAction(
                    f"   {self._mail_bridge_status_text()}"
                )
                _info_action.setEnabled(False)
                _mail_menu.addSeparator()

                _act_copy = _mail_menu.addAction(
                    "📋  Kopiera inställningar för Thunderbird…"
                )
                _act_copy.setToolTip(
                    "Lägger adress + token på urklipp — klistra in i\n"
                    "Thunderbird-tilläggets inställningar."
                )
                _act_copy.triggered.connect(self._copy_mail_bridge_settings)

                _act_guide = _mail_menu.addAction(
                    "🧩  Installera Thunderbird-tillägget…"
                )
                _act_guide.triggered.connect(self._show_thunderbird_guide)

                _act_folder = _mail_menu.addAction("📂  Öppna inkorgsmappen")
                _act_folder.triggered.connect(self._open_inbox_folder)

                _act_import = _mail_menu.addAction(
                    "📥  Importera e-postfiler nu…"
                )
                _act_import.setToolTip(
                    "Välj .eml/.msg-filer (Thunderbird: spara mailet som\n"
                    ".eml) — uppgifterna skapas och sparas i JSON."
                )
                _act_import.triggered.connect(self._import_email_files_dialog)

                if _status:
                    _mail_menu.addSeparator()
                    _stat_txt = _mail_menu.addAction(
                        f"   {_status['imports']} mail importerade • "
                        f"{_status['duplicates']} dubletter"
                    )
                    _stat_txt.setEnabled(False)
            except Exception as e:
                self._log.debug(
                    f"{LOG_PREFIX} e-post-undermeny misslyckades: {e}"
                )

            self._tray_menu.addSeparator()

            # === DIAGNOSTICS ===
            stats_dlg_action = self._QAction("📊  Statistik…", self._tray_menu)
            stats_dlg_action.triggered.connect(self.show_statistics)
            self._tray_menu.addAction(stats_dlg_action)

            if self._mode == AppMode.DIAGNOSTICS:
                dump_action = self._QAction("🔍  Subsystem-dump", self._tray_menu)
                dump_action.triggered.connect(self._dump_subsystem_status)
                self._tray_menu.addAction(dump_action)

            bug_action = self._QAction("🩺  Skapa felrapport…", self._tray_menu)
            bug_action.setToolTip(
                "Packar logg, inställningar och versioner i en ZIP (data\\felrapporter).\n"
                "Dina uppgifter, Google-koppling och mail tas INTE med."
            )
            bug_action.triggered.connect(self._create_bug_report)
            self._tray_menu.addAction(bug_action)

            about_action = self._QAction("ℹ  Om…", self._tray_menu)
            about_action.triggered.connect(self.show_about)
            self._tray_menu.addAction(about_action)

            self._tray_menu.addSeparator()

            # === AVSLUTA ===
            quit_action = self._QAction("❌  Avsluta", self._tray_menu)
            quit_action.triggered.connect(self.shutdown)
            self._tray_menu.addAction(quit_action)

            self._tray.setContextMenu(self._tray_menu)
        except Exception as e:
            self._log.error(f"_populate_tray_menu misslyckades: {e}", exc_info=True)

    def _on_tray_activated(self, reason: Any) -> None:
        """Hantera tray-ikon aktivering (vänster/höger/dubbelklick)."""
        try:
            # NY v6.4: Hantera ALLA click-typer (inte bara dubbelklick)
            trigger = self._QSystemTrayIcon.ActivationReason.Trigger
            double_click = self._QSystemTrayIcon.ActivationReason.DoubleClick
            middle_click = getattr(
                self._QSystemTrayIcon.ActivationReason, "MiddleClick", None
            )
            # Vänster/dubbel/middle click = visa fönster
            if reason in (trigger, double_click, middle_click):
                # NY v7-fix72: lyft över appar i X sekunder
                self._lift_on_top_temporarily()
            # Högerklick = context-meny (Qt hanterar detta automatiskt via setContextMenu)
        except Exception as e:
            self._log.debug(f"on_tray_activated misslyckades: {e}")

    def _set_tray_lift_seconds(self, seconds: int) -> None:
        """NY v7-fix74: sätt lyft-tid (sparas i settings)."""
        try:
            _v = max(1, min(60, int(seconds)))
            if hasattr(self.settings, "set_tray_lift_seconds"):
                self.settings.set_tray_lift_seconds(_v)
            self._log.info(
                f"{LOG_PREFIX} Lyft-tid vid tray-klick: {_v} sekunder "
                f"(sparad i settings) (v7-fix74)"
            )
            _lt = getattr(self, "_lift_timer", None)
            if _lt is not None and _lt.isActive():
                _lt.start(_v * 1000)
            self._populate_tray_menu()
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _set_tray_lift_seconds: {e}", exc_info=True
            )

    def _lift_on_top_temporarily(self) -> None:
        """
        NY v7-fix72: lyft fönstret över appar i X sekunder.

        Rickard 2026-10-06: "om man klickar på tray så lyfts fönstret
        fram till topp i x antal sekunder". Efter X sekunder återfästs
        det automatiskt på skrivbordet. Nytt klick = förläng timern.
        """
        try:
            import ctypes
            _u = ctypes.windll.user32
            _secs = 5
            with suppress(Exception):
                if hasattr(self.settings, "tray_lift_seconds"):
                    _secs = int(self.settings.tray_lift_seconds())
                else:
                    _secs = int(
                        self.settings.get("tray_lift_seconds", 5)
                    )
            _secs = max(1, min(60, _secs))
            with self._widget_lock:
                widgets = list(self._widgets.values())
            for w in widgets:
                shell = getattr(w, "_shell", None)
                if shell is None:
                    continue
                wid = getattr(w, "win_id", "?")
                _hwnd = int(shell.winId())
                if not _hwnd:
                    continue
                if str(
                    getattr(shell, "_desktop_layer_mode", "")
                ) != "_lift":
                    shell._lift_prev_mode = str(
                        getattr(shell, "_desktop_layer_mode", "normal")
                    )
                # FIX v7-fix75: HWND_TOP räcker inte när t.ex. Explorer
                # ligger över (z-order kan respekteras inkonsekvent).
                # Lösning: TILLFÄLLIG TOPMOST (-1) — garanterat över
                # ALLA normala fönster. Återställs till NOTOPMOST (-2)
                # i _lift_timeout före återfästningen.
                _u.SetWindowPos(
                    _hwnd, -1, 0, 0, 0, 0,
                    0x0040 | 0x0010 | 0x0001 | 0x0002,
                )  # HWND_TOPMOST | SHOWWINDOW|NOACTIVATE|NOSIZE|NOMOVE
                shell._desktop_layer_mode = "_lift"
                self._log.info(
                    f"{LOG_PREFIX} TRAY-LYFT: {wid!r} visas över appar "
                    f"i {_secs} sekunder (v7-fix72)"
                )
            _lt = getattr(self, "_lift_timer", None)
            if _lt is None:
                _lt = self._QTimer()
                _lt.setSingleShot(True)
                _lt.timeout.connect(self._lift_timeout)
                self._lift_timer = _lt
            _lt.start(_secs * 1000)
            with suppress(Exception):
                if self._tray is not None:
                    self._tray.setToolTip(
                        f"TaskBord — lyft i {_secs}s "
                        f"(klicka igen = förläng)"
                    )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _lift_on_top_temporarily: {e}",
                exc_info=True,
            )

    def _lift_timeout(self) -> None:
        """NY v7-fix72: lyft-tiden ut — återfäst på skrivbordet."""
        try:
            import ctypes
            _u = ctypes.windll.user32
            with self._widget_lock:
                widgets = list(self._widgets.values())
            for w in widgets:
                shell = getattr(w, "_shell", None)
                if shell is None:
                    continue
                wid = getattr(w, "win_id", "?")
                _prev = str(
                    getattr(shell, "_lift_prev_mode", "behind")
                )
                # FIX v7-fix75: ta bort TOPMOST FÖRE återfästningen
                with suppress(Exception):
                    _hw = int(shell.winId())
                    if _hw:
                        _u.SetWindowPos(
                            _hw, -2, 0, 0, 0, 0,
                            0x0010 | 0x0001 | 0x0002,
                        )  # HWND_NOTOPMOST | NOACTIVATE|NOSIZE|NOMOVE
                shell._desktop_layer_mode = None
                self._apply_desktop_shell(shell, wid)
                self._log.info(
                    f"{LOG_PREFIX} TRAY-LYFT slut: {wid!r} återfäst "
                    f"(var: {_prev}) (v7-fix72)"
                )
            with suppress(Exception):
                if self._tray is not None:
                    self._tray.setToolTip("TaskBord")
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _lift_timeout: {e}", exc_info=True
            )

    def _show_window_at_cursor(self) -> None:
        """NY v6.4: Visa alla fönster vid muspekaren."""
        try:
            from PySide6.QtGui import QCursor
            cursor_pos = QCursor.pos()
            offset = 0
            with self._widget_lock:
                widgets = list(self._widgets.values())
            for w in widgets:
                # FIX v7-fix60: flytta SKALET (inte barnet!). Gamla koden
                # gjorde w.move() på TodoWidget-BARNET — i skal-läge är det
                # en LOKAL position, och (1003,374) i ett 340 px brett skal
                # = barnet 663 px UTANFÖR fönstret → tomt genomskinligt
                # skal = "fönstret syns inte"!
                _sh = getattr(w, "_shell", None)
                _tx = cursor_pos.x() + offset
                _ty = cursor_pos.y() + offset
                if _sh is not None and hasattr(w, "_shell_screen_move"):
                    # DPI-kompenserad flytt till skärm-koordinater
                    w._shell_screen_move(_tx, _ty)
                elif _sh is not None:
                    _sh.move(_tx, _ty)
                else:
                    w.move(_tx, _ty)
                # AUTO-HEAL: om barnet hamnat utanför skalet (gammal bugg
                # eller skräp-position) → tillbaka till (0,0)
                with suppress(Exception):
                    if (
                        _sh is not None
                        and (w.x() != 0 or w.y() != 0)
                        and (w.x() > _sh.width() or w.y() > _sh.height()
                             or w.x() < 0 or w.y() < 0)
                    ):
                        w.move(0, 0)
                        self._log.info(
                            f"{LOG_PREFIX} _show_window_at_cursor: barn "
                            f"utanför skalet → healad till (0,0)"
                        )
                # Lås upp automatiskt (om låst) + visa
                if hasattr(w, "set_locked"):
                    with suppress(Exception):
                        w.set_locked(False, auto_relock_sec=60)  # Auto-relock efter 60s
                if _sh is not None:
                    with suppress(Exception):
                        _sh.show()
                else:
                    if hasattr(w, "_setup_bugg19_zorder"):
                        with suppress(Exception):
                            w._setup_bugg19_zorder()
                    w.show()
                    w.raise_()
                offset += 30
            self._log.info(
                f"{LOG_PREFIX} _show_window_at_cursor: "
                f"{len(widgets)} fönster vid ({cursor_pos.x()}, {cursor_pos.y()})"
            )
        except Exception as e:
            self._log.error(f"_show_window_at_cursor misslyckades: {e}")

    def _tray_quick_add_task(self) -> None:
        """
        NY v6.4.1: Snabbuppgift fran tray-menyn.

        Vad den gor:
          1. Visar QInputDialog vid markoren
          2. Vid OK: lagger till i store via self.store.add_task()
          3. Visar widget vid markoren sa man ser den nya uppgiften
          4. Loggar allt med [MAIN]-prefix

        Bra nar man snabbt vill lagga till nagot utan att oppna appen.
        """
        try:
            from PySide6.QtGui import QCursor
            from PySide6.QtWidgets import QInputDialog
            self._log.info(
                f"{LOG_PREFIX} _tray_quick_add_task: startar input-dialog"
            )
            # QInputDialog vid markoren
            cursor_pos = QCursor.pos()
            text, ok = QInputDialog.getText(
                None,
                "➕ Snabbuppgift",
                "Ny uppgift:",
                text="",
            )
            if not ok or not text or not text.strip():
                self._log.info(
                    f"{LOG_PREFIX} _tray_quick_add_task: avbruten "
                    f"(ok={ok}, text={text!r})"
                )
                return
            text = text.strip()
            # Lagg till i store
            if self.store is None or not hasattr(self.store, "add_task"):
                self._log.error(
                    f"{LOG_PREFIX} _tray_quick_add_task: store saknas "
                    f"eller saknar add_task()"
                )
                # Visa felmeddelande till anvandaren
                if self._QMessageBox:
                    self._QMessageBox.warning(
                        None,
                        "Kunde inte lagga till",
                        "Store ar inte tillganglig. Oppna appen forst.",
                    )
                return
            new_id = self.store.add_task(text)
            if new_id:
                self._log.info(
                    f"{LOG_PREFIX} _tray_quick_add_task: ny task skapad "
                    f"id={new_id!r} text={text[:30]!r}"
                )
                # Visa widget vid markoren sa man ser den nya uppgiften
                self._show_window_at_cursor()
                # Uppdatera tray-tooltip med nya antalet
                self._update_tray_tooltip()
                # Visa kort balloon-notis (om tillgangligt)
                if self._tray is not None:
                    try:
                        self._tray.showMessage(
                            "➕ Snabbuppgift tillagd",
                            f"\"{text[:40]}{'...' if len(text) > 40 else ''}\"",
                            self._QSystemTrayIcon.MessageIcon.Information,
                            3000,  # 3 sekunder
                        )
                    except Exception as e:
                        self._log.debug(
                            f"{LOG_PREFIX} balloon-notis misslyckades: {e}"
                        )
            else:
                self._log.warning(
                    f"{LOG_PREFIX} _tray_quick_add_task: add_task returnerade "
                    f"ingen id (text={text[:30]!r})"
                )
        except Exception as e:
            self._log.error(
                f"{LOG_PREFIX} _tray_quick_add_task misslyckades: {e}",
                exc_info=True,
            )

    def _update_tray_tooltip(self) -> None:
        """Uppdatera tray-tooltip med live-data (cachas i 1s)."""
        if self._tray is None:
            return
        now = time.time()
        if now - self._last_tooltip_update < 1.0:
            return
        self._last_tooltip_update = now
        try:
            active = 0
            if hasattr(self.store, "count"):
                active, _ = self.store.count()
            uptime = self._performance.format_uptime()
            tooltip = (
                f"{APP_NAME} v{APP_VERSION_DISPLAY}\n"
                f"{active} uppgifter • {len(self._widgets)} fönster • {uptime}"
            )
            self._tray.setToolTip(tooltip)
        except Exception as e:
            self._log.debug(f"update_tray_tooltip misslyckades: {e}")
