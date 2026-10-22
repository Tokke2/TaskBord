# -*- coding: utf-8 -*-
"""
ui/widget_parts/window_ops.py — Fönsterhantering: fönstermeny, flytt mellan skärmar, centrering, lås, framåt och automatisk omplacering.

Del av TodoWidget (delad ur ui/widget.py). Metoderna är oförändrade; klassen
blandas in i TodoWidget i ui/widget.py. Gemensamma konstanter, hjälpfunktioner
och Qt-importer kommer från ui/widget_base.py, små UI-klasser från ui/widget_atoms.py.
"""
from __future__ import annotations

from ui.widget_base import *  # noqa: F401,F403
from ui.widget_atoms import *  # noqa: F401,F403


class WindowOpsMixin:
    """Fönsterhantering: fönstermeny, flytt mellan skärmar, centrering, lås, framåt och automatisk omplacering."""

    def _is_always_on_top(self) -> bool:
        """Ligger fönstret i läget 'Alltid överst' just nu? (läser inställningen)"""
        try:
            return str(self.settings.desktop_mode()).strip().lower() == "top"
        except Exception:
            return False

    def _top_menu_label(self) -> str:
        """Menytext; på Windows visas snabbtangenten om den är på."""
        label = "📌 Alltid överst"
        try:
            if sys.platform == "win32" and self.settings.top_toggle_enabled():
                label += f"  ({self.settings.top_toggle_hotkey()})"
        except Exception:
            pass
        return label

    def contextMenuEvent(self, event: Any) -> None:
        """
        NY v7-fix47: högerklicksmeny på fönstret.

        Rickard 2026-10-02: "man kan vid högerklick nollställa fönstret"
        — + centrera, lås/lås upp.
        """
        try:
            get_throttle().notify_activity()
            menu = QMenu(self)
            act_center = menu.addAction("🎯 Centrera fönstret")
            act_reset = menu.addAction(
                "↩️ Nollställ (centrera + standardstorlek)"
            )
            menu.addSeparator()
            act_lock = menu.addAction(
                "🔓 Lås upp fönstret"
                if self._locked
                else "🔒 Lås fönstret"
            )
            # NY: Alltid överst (bockas av/på; samma som tray-menyn och Ctrl+Alt+T)
            act_top = menu.addAction(self._top_menu_label())
            act_top.setCheckable(True)
            act_top.setChecked(self._is_always_on_top())
            act_top.setToolTip(
                "Fönstret ligger över alla andra appar tills du slår av det.\n"
                "Av = tillbaka till skrivbordet (bakom ikonerna)."
            )
            # NY v7-fix81: PDF-export även här (utom 📄-knappen + tray)
            act_pdf = menu.addAction("📄 Exportera checklista → PDF…")
            # NY v8: kalenderexport (.ics) → Google Calendar m.fl.
            act_cal = menu.addAction("📅 Exportera till kalender (.ics)…")
            # NY v8: lokal OAuth-koppling till Google Calendar
            act_google = menu.addAction("☁️ Google Calendar (koppla konto)…")
            act_google.setToolTip(
                "Koppla ett Google-konto lokalt (OAuth i webbläsaren) och\n"
                "skicka uppgifter rakt in i din kalender."
            )
            # NY v8: backup av uppgifter
            act_backup = menu.addAction("💾 Backup av uppgifter…")
            act_help = menu.addAction("⌨️ Tangentöversikt (F1)")
            act_dock = menu.addAction("↔ Docka vid skärmkant")
            act_dock.setCheckable(True)
            act_dock.setChecked(bool(getattr(self.settings, "edge_dock_enabled", lambda: True)()))
            act_dock.setToolTip(
                "Dra fönstret mot vänster, höger eller övre kanten och släpp — då glider det ut\n"
                "och kommer tillbaka när musen nuddar kanten. Dra bort det för att sluta docka."
            )
            act_titles = menu.addAction("🔗 Hämta sidtitlar för länkar")
            act_titles.setCheckable(True)
            act_titles.setChecked(bool(getattr(self.settings, "links_fetch_titles", lambda: True)()))
            act_titles.setToolTip(
                "När du klistrar in en webbadress hämtas sidans titel (ett anrop till just den sidan).\n"
                "Av = länken visas med bara värdnamnet."
            )
            # NY v8: frivillig donation (öppnar ui/donate.py-dialogen)
            menu.addSeparator()
            act_donate = menu.addAction("💖 Stöd TaskBord…")
            chosen = menu.exec(event.globalPos())
            if chosen is act_center:
                self._center_window(reset_size=False)
            elif chosen is act_reset:
                self._center_window(reset_size=True)
            elif chosen is act_lock:
                self._toggle_lock()
            elif chosen is act_top:
                self.top_toggle_requested.emit()
            elif chosen is act_pdf:
                self._on_export_pdf()
            elif chosen is act_cal:
                self._on_export_calendar_ics()
            elif chosen is act_google:
                self._on_open_google_calendar()
            elif chosen is act_backup:
                self._on_open_backup()
            elif chosen is act_dock:
                self.settings.set_edge_dock_enabled(act_dock.isChecked())
                if not act_dock.isChecked():
                    self._edge_dock_release()
            elif chosen is act_titles:
                self.settings.set_links_fetch_titles(act_titles.isChecked())
            elif chosen is act_help:
                self._on_show_shortcut_help()
            elif chosen is act_donate:
                self._on_open_donate()
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} contextMenuEvent misslyckades: "
                f"{_describe_widget_error(e)}"
            )

    def _shell_screen_move(
        self, screen_x: int, screen_y: int,
        width: Any = None, height: Any = None,
    ) -> None:
        """
        NY v7-fix48/52: flytta (+ ev. resiza) fönstret till SKÄRM-
        koordinater.

        I desktop-läget 'ovanpå ikonerna' är fönstret barn i skrivbordet
        (Progman) — Windows tolkar koordinater som FÖRÄLDER-relativa.
        FIX v7-fix52: i above-läget sker ALLT nativt via SetWindowPos
        (skärm-koordinat - förälderorigo) — Qt:s asynkrona move/resize-
        konvertering förvirrade koordinaterna (nollställningen hamnade
        t.ex. 1920 px fel). Qt fallback för övriga lägen.
        """
        try:
            _sh = getattr(self, "_shell", None)
            _t = _sh if _sh is not None else self
            _ox, _oy = (0, 0)
            if _sh is not None:
                _ox, _oy = getattr(_sh, "_parent_origin", (0, 0)) or (0, 0)
            # FIX v7-fix54: den nativa SetWindowPos-grenen (v7-fix52)
            # var DPI-FEL — råa Windows-koordinater är FYSISKA px medan
            # Qt använder LOGISKA (125% DPI). Nu: ALLT via Qt (konver-
            # terar själv) med LOGISKT konverterad origo (sätts i main
            # vid attach: fysiskt_origo / devicePixelRatio).
            if width is not None and height is not None:
                _t.resize(int(width), int(height))
            _t.move(int(screen_x) - _ox, int(screen_y) - _oy)
        except Exception as e:
            logger.debug(f"{LOG_PREFIX} _shell_screen_move: {e}")

    # ------------------------------------------------------------------
    # Dockning vid skärmkant (ui/edge_dock.py)
    # ------------------------------------------------------------------
    def _ensure_edge_dock(self) -> Any:
        dk = getattr(self, "_edge_dock", None)
        if dk is None:
            from ui.edge_dock import EdgeDocker
            dk = self._edge_dock = EdgeDocker(self, self.settings, self.win_id)
        return dk

    def _start_edge_dock(self) -> None:
        """Vid start: återuppta dockningen om fönstret var dockat när appen stängdes."""
        try:
            self._ensure_edge_dock().adopt_saved()
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} _start_edge_dock: {_describe_widget_error(e)}")

    def _edge_dock_after_drag(self) -> None:
        """Fönstret har släppts efter drag: nära en skärmkant → docka."""
        try:
            self._ensure_edge_dock().on_drag_release()
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} _edge_dock_after_drag: {_describe_widget_error(e)}")

    def _edge_dock_reveal(self) -> None:
        dk = getattr(self, "_edge_dock", None)
        if dk is not None:
            dk.reveal()

    def _edge_dock_pin(self, on: bool) -> None:
        dk = getattr(self, "_edge_dock", None)
        if dk is not None:
            dk.pin(on)

    def _edge_dock_release(self) -> None:
        """Sluta docka (fönstret hamnar på sitt synliga läge)."""
        dk = getattr(self, "_edge_dock", None)
        if dk is not None:
            dk.undock()

    def _center_window(self, reset_size: bool = False) -> None:
        """
        NY v7-fix47: centrera fönstret på primärskärmen.

        reset_size=True → även standardstorlek (nollställ).
        Position + storlek sparas direkt (överlever omstart).
        """
        self._edge_dock_release()  # centrering = inte längre dockat
        try:
            _sh = getattr(self, "_shell", None)
            _target = _sh if _sh is not None else self
            _scr = self.primary_screen or QGuiApplication.primaryScreen()
            if _scr is not None:
                # v7-fix52: beräkna mål-STORLEK före (atomisk operation
                # — läs ALDRIG widgetens storlek asynkront efteråt)
                _tw = (
                    DEFAULT_WIDGET_WIDTH if reset_size
                    else _target.width()
                )
                _th = (
                    DEFAULT_WIDGET_HEIGHT if reset_size
                    else _target.height()
                )
                _sg = _scr.availableGeometry()
                _nx = _sg.x() + (_sg.width() - _tw) // 2
                _ny = _sg.y() + (_sg.height() - _th) // 2
                # v7-fix48/52: komposterad ATOMISK flytt+resize —
                # korrekt skärm-position även i above-läget
                self._shell_screen_move(_nx, _ny, _tw, _th)
                # FIX v7-fix55: logga BERÄKNADE skärm-värden (asynkron
                # Qt-läsning kunde visa DPI-förväxlade mått, t.ex. 280x518)
                logger.info(
                    f"{LOG_PREFIX} fönstret "
                    f"{'NOLLSTÄLLT (standardstorlek + centrerat)' if reset_size else 'centrerat'}"
                    f" → skärm ({_nx},{_ny}) {_tw}x{_th}"
                )
            # Spara direkt så det överlever omstart
            self._save_geometry_now()
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} _center_window: {e}")

    def _toggle_lock(self) -> None:
        """NY v6.4.1 v7: Toggle lås/lås upp fönstret (med position-minne).

        Rickard 2026-09-25:
          1. Kunna låsa upp fönstret och flytta → låsa positionen
          2. Appen ska komma ihåg positionen vid omstart
          3. Win+D ska INTE gömma fönstret

        Flow:
          - Lås = frozen pos, kan INTE flyttas
          - Lås upp = dragbart i 30s, auto-relock
          - Vid flytt (när upplåst): settings.window_configs[id].x/y
          - Vid låsning: säkra pos genom att spara settings
        """
        try:
            get_throttle().notify_activity()
            was_locked = bool(self._locked)
            self._locked = not was_locked
            # Auto-relock-timer
            if self._locked:
                if self._unlock_timer is not None:
                    with suppress(Exception):
                        self._unlock_timer.stop()
                # NY v7-fix49: LÅS = positionen+storleken SPARAS direkt
                # (Rickard: "tills användaren flyttar och låser
                # positionen, som sparas tills nästa gång")
                with suppress(Exception):
                    self._save_geometry_now()
                icon = "🔒"
                msg = "Låst (positionen sparad)"
            else:
                if self._unlock_timer is None:
                    self._unlock_timer = QTimer(self)
                    self._unlock_timer.setSingleShot(True)
                    self._unlock_timer.timeout.connect(self._auto_relock)
                self._unlock_timer.start(self._unlock_timeout_sec * 1000)
                icon = "🔓"
                msg = "Upplåst (auto-relock om 30s)"
            # Uppdatera UI
            with suppress(Exception):
                if hasattr(self, "lock_btn") and self.lock_btn is not None:
                    # setChecked uppdaterar QSS:checked-stilen
                    self.lock_btn.setChecked(self._locked)
                    self.lock_btn.setText(icon)
            with suppress(Exception):
                if hasattr(self, "drag_handle") and self.drag_handle is not None:
                    # FIX 2026-09-25: bara 🔒/🔓 + släpp bilagan
                    self.drag_handle.setText(
                        f"{icon}  {APP_NAME} — klicka och dra för att flytta"
                    )
            # FIX 2026-09-25: vid LÅS → spara positionen permanent
            # (annars kan settings ha annan pos som override:ar)
            # FIX v7-fix49: gamla koden sparade BARNETS lokala pos
            # (alltid 0,0 i skal-läge!) — läs SKALETs skärm-position,
            # och spara position + storlek via update_window_geometry.
            if self._locked:
                with suppress(Exception):
                    _sh_l = getattr(self, "_shell", None)
                    _lx, _ly = (
                        (_sh_l.x(), _sh_l.y()) if _sh_l is not None
                        else (self.x(), self.y())
                    )
                    if hasattr(self.settings, "update_window_geometry"):
                        self.settings.update_window_geometry(
                            self.win_id, _lx, _ly,
                            (_sh_l.width() if _sh_l is not None
                             else self.width()),
                            (_sh_l.height() if _sh_l is not None
                             else self.height()),
                        )
                    elif hasattr(self.settings, "update_window_position"):
                        self.settings.update_window_position(
                            self.win_id, _lx, _ly
                        )
                    logger.info(
                        f"{LOG_PREFIX} _toggle_lock: position "
                        f"låst vid ({_lx},{_ly})"
                    )
            logger.info(
                f"{LOG_PREFIX} _toggle_lock: {was_locked} → {self._locked} "
                f"({msg}) icon={icon}"
            )
            self._audit.add("lock_toggled", {"locked": self._locked})
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} _toggle_lock misslyckades: "
                f"{_describe_widget_error(e)}",
                exc_info=True,
            )

    def _auto_relock(self) -> None:
        """NY v6.4.1 v7-fix: Auto-relock efter _unlock_timeout_sec sekunder."""
        try:
            if self._locked:
                return  # Redan låst (race condition-skydd)
            self._locked = True
            with suppress(Exception):
                if hasattr(self, "lock_btn") and self.lock_btn is not None:
                    self.lock_btn.setText("🔒")
            with suppress(Exception):
                if hasattr(self, "drag_handle") and self.drag_handle is not None:
                    self.drag_handle.setText(
                        f"🔒  {APP_NAME} — klicka och dra för att flytta"
                    )
            logger.info(
                f"{LOG_PREFIX} _auto_relock: låst efter "
                f"{self._unlock_timeout_sec}s utan aktivitet"
            )
            self._audit.add(
                "auto_relock",
                {"after_sec": self._unlock_timeout_sec},
            )
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} _auto_relock misslyckades: "
                f"{_describe_widget_error(e)}",
                exc_info=True,
            )

    def bring_to_front(self) -> None:
        """
        NY v6.4.1 v5: Lyft widget till FRAMSIDAN vid klick.

        Vad den gor:
          1. Visa fonstret (om gomt)
          2. Satt z-order till HWND_TOP (OVER alla skrivbords-widgets)
          3. Aktivera (ta fokus — anvandaren klickade ju)

        Efter klick forsoker Z-order TIMER att aterstall till
        HWND_BOTTOM sa vi inte star over andra fonster permanent.
        """
        # FIX v7-fix29: barn → skalet hanterar fokus
        if self._is_child():
            return
        try:
            import ctypes
            if not self._native_window_ok():
                return
            hwnd = int(self.winId())
            if not hwnd:
                return
            user32 = ctypes.windll.user32
            # FIX 2026-09-24: NOTOPMOST/TOP bort — lyfter över appar.
            # Bara synlig, z-order orörd.
            if not user32.IsWindowVisible(hwnd):
                user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
            self.show()
            logger.trace(
                f"{LOG_PREFIX} bring_to_front: HWND={hwnd} synlig "
                f"(z-order orörd)"
            )
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} bring_to_front misslyckades: {e}"
            )

    def _auto_reposition_if_needed(self) -> None:
        """
        BUGG 26: flytta widgeten till sin SPARADE position om den hamnat fel
        (t.ex. efter skärmbyte, upplösningsändring eller kollision med
        skrivbordsikoner).

        NY v7-fix9 — logisk bugg åtgärdad:
          Tidigare läste metoden den sparade positionen men skrev sedan
          tillbaka widgetens NUVARANDE position till settings. Det var
          tvärtom mot syftet (auto-reposition) och gjorde metoden till en
          no-op som samtidigt triggade windows_updated → populate-loop.

          Rätt beteende: läs sparad position → flytta widgeten dit
          (endast om den faktiskt avviker och fönstret inte är låst).
        """
        # NY v6.4: Respektera lås (låst fönster får inte flyttas)
        if self._locked:
            logger.debug(
                f"{LOG_PREFIX} auto-reposition skippat (fönster låst)"
            )
            return
        if not hasattr(self.settings, "window_configs"):
            return
        configs = self.settings.window_configs() or []
        for conf in configs:
            if conf.get("id") != self.win_id:
                continue
            want_x = int(conf.get("x", self.x()))
            want_y = int(conf.get("y", self.y()))
            cur_x, cur_y = self.x(), self.y()
            if (cur_x, cur_y) == (want_x, want_y):
                logger.debug(
                    f"{LOG_PREFIX} auto-reposition: redan rätt "
                    f"({cur_x},{cur_y}) — inget att göra"
                )
                return
            logger.info(
                f"{LOG_PREFIX} auto-reposition: flyttar "
                f"({cur_x},{cur_y}) → ({want_x},{want_y})"
            )
            with suppress(Exception):
                # _move_to sparar sin egen position (throttlad) — vi skriver
                # ALDRIG till settings härifrån (undviker signal-loop).
                self.move(want_x, want_y)
            return
        logger.debug(
            f"{LOG_PREFIX} auto-reposition: ingen config för "
            f"{self.win_id!r} — hoppar över"
        )
