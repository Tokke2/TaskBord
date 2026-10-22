# -*- coding: utf-8 -*-
"""
ui/widget_parts/focus_timers.py — Fokusvyn, periodisk z-ordningskontroll, snabbtangenter, timers och PWM (adaptiv uppdateringstakt).

Del av TodoWidget (delad ur ui/widget.py). Metoderna är oförändrade; klassen
blandas in i TodoWidget i ui/widget.py. Gemensamma konstanter, hjälpfunktioner
och Qt-importer kommer från ui/widget_base.py, små UI-klasser från ui/widget_atoms.py.
"""
from __future__ import annotations

from ui.widget_base import *  # noqa: F401,F403
from ui.widget_atoms import *  # noqa: F401,F403


class FocusTimersMixin:
    """Fokusvyn, periodisk z-ordningskontroll, snabbtangenter, timers och PWM (adaptiv uppdateringstakt)."""

    # ====================================================================
    # FOCUS MODE (NY v6.4.1 - Focus Mode §22.18 Todoist)
    # ====================================================================

    def _build_focus_view(self) -> QWidget:
        """NY v6.4.1: Bygg Focus Mode-vyn (1 task stort)."""
        view = QWidget(self)
        view.setObjectName("focusView")
        v = QVBoxLayout(view)
        v.setContentsMargins(20, 20, 20, 20)
        v.setSpacing(16)
        header = QHBoxLayout()
        self._focus_counter_label = QLabel("0 / 0", view)
        self._focus_counter_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = self._focus_counter_label.font()
        font.setPointSize(11)
        self._focus_counter_label.setFont(font)
        header.addWidget(self._focus_counter_label, 1)
        self._focus_exit_btn = QPushButton("X  Avsluta fokus (F3)", view)
        self._focus_exit_btn.clicked.connect(self._exit_focus_mode)
        self._focus_exit_btn.setFixedHeight(28)
        header.addWidget(self._focus_exit_btn)
        v.addLayout(header)
        self._focus_title_label = QLabel("Inga uppgifter", view)
        self._focus_title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._focus_title_label.setWordWrap(True)
        big_font = self._focus_title_label.font()
        big_font.setPointSize(22)
        big_font.setBold(True)
        self._focus_title_label.setFont(big_font)
        self._focus_title_label.setMinimumHeight(80)
        v.addWidget(self._focus_title_label, 1)
        self._focus_meta_label = QLabel("", view)
        self._focus_meta_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        meta_font = self._focus_meta_label.font()
        meta_font.setPointSize(13)
        self._focus_meta_label.setFont(meta_font)
        v.addWidget(self._focus_meta_label)
        self._focus_priority_label = QLabel("", view)
        self._focus_priority_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        prio_font = self._focus_priority_label.font()
        prio_font.setPointSize(16)
        prio_font.setBold(True)
        self._focus_priority_label.setFont(prio_font)
        self._focus_priority_label.setMinimumHeight(40)
        v.addWidget(self._focus_priority_label)
        v.addStretch(1)
        nav_row = QHBoxLayout()
        self._focus_prev_btn = QPushButton("<  Föregående", view)
        self._focus_prev_btn.setObjectName("focusNav")
        self._focus_prev_btn.clicked.connect(self._focus_prev)
        self._focus_prev_btn.setMinimumHeight(56)
        nav_row.addWidget(self._focus_prev_btn, 1)
        self._focus_complete_btn = QPushButton("OK  Markera klar", view)
        self._focus_complete_btn.setObjectName("focusDone")
        self._focus_complete_btn.clicked.connect(self._focus_complete)
        self._focus_complete_btn.setMinimumHeight(56)
        # v7-fix10: styling flyttad till QSS (focusDone) — ej inline
        nav_row.addWidget(self._focus_complete_btn, 1)
        self._focus_next_btn = QPushButton("Nästa  >", view)
        self._focus_next_btn.setObjectName("focusNav")
        self._focus_next_btn.clicked.connect(self._focus_next)
        self._focus_next_btn.setMinimumHeight(56)
        nav_row.addWidget(self._focus_next_btn, 1)
        v.addLayout(nav_row)
        try:
            QShortcut(QKeySequence("F3"), self, activated=self._toggle_focus_mode)
            # Fokusläges-tangenterna är PÅ BARA i fokusläget. Tidigare var de alltid på och
            # stal Esc/Enter/Mellanslag/←/→ i hela fönstret (ett QShortcut konsumerar tangenten
            # även när hanteraren inte gör något) → mellanslag-för-klar, ←/→-prioritet,
            # Esc i listan och Enter i titelredigeringen nådde aldrig sin hanterare.
            self._focus_shortcuts = []
            for _seq, _fn in (
                ("Esc", self._exit_focus_mode),
                ("Right", self._focus_next),
                ("Left", self._focus_prev),
                ("Return", self._focus_complete),
                ("Space", self._focus_complete),
            ):
                _sc = QShortcut(QKeySequence(_seq), self, activated=_fn)
                _sc.setEnabled(bool(getattr(self, "_focus_mode", False)))
                self._focus_shortcuts.append(_sc)
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} Fokus-shortcuts misslyckades: {e}")
        return view

    def _get_focus_tasks(self) -> "List[Dict[str, Any]]":
        """NY v6.4.1: Hämta aktiva tasks för Focus Mode."""
        try:
            if hasattr(self, "active_tasks_filtered"):
                return self.active_tasks_filtered()
            elif hasattr(self.store, "active_tasks"):
                return self.store.active_tasks()
            return []
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} _get_focus_tasks misslyckades: {e}")
            return []

    def _update_focus_view(self) -> None:
        """NY v6.4.1: Uppdatera Focus Mode-vyn."""
        tasks = self._get_focus_tasks()
        total = len(tasks)
        if total == 0:
            self._focus_counter_label.setText("0 / 0")
            self._focus_title_label.setText("🎉 Inga uppgifter kvar!")
            self._focus_meta_label.setText("")
            self._focus_priority_label.setText("")
            self._focus_prev_btn.setEnabled(False)
            self._focus_complete_btn.setEnabled(False)
            self._focus_next_btn.setEnabled(False)
            return
        if self._focus_index >= total:
            self._focus_index = total - 1
        if self._focus_index < 0:
            self._focus_index = 0
        task = tasks[self._focus_index]
        self._focus_counter_label.setText(f"{self._focus_index + 1} / {total}")
        self._focus_title_label.setText(task.get("title", ""))
        meta_parts = []
        tags = task.get("tags", [])
        if tags:
            meta_parts.append("🏷  " + ", ".join(tags))
        due = task.get("due_date")
        if due:
            meta_parts.append(f"📅  {due}")
        self._focus_meta_label.setText("\n".join(meta_parts))
        priority = task.get("priority", "none")
        prio_colors = {
            "high": ("🔴  HÖG", "rgba(244, 67, 54, 0.7)"),
            "medium": ("🟡  MEDEL", "rgba(255, 193, 7, 0.7)"),
            "low": ("🟢  LÅG", "rgba(76, 175, 80, 0.6)"),
            "none": ("⚪  INGEN", "rgba(158, 158, 158, 0.5)"),
        }
        label, color = prio_colors.get(priority, prio_colors["none"])
        self._focus_priority_label.setText(label)
        self._focus_priority_label.setStyleSheet(
            f"QLabel {{ background-color: {color}; color: white; padding: 8px; border-radius: 8px; }}"
        )
        self._focus_prev_btn.setEnabled(total > 1)
        self._focus_next_btn.setEnabled(total > 1)
        self._focus_complete_btn.setEnabled(True)
        if task.get("pinned"):
            self._focus_title_label.setText("⭐  " + task.get("title", ""))

    def _set_focus_shortcuts_enabled(self, on: bool) -> None:
        """Slå fokusläges-tangenterna (Esc/Enter/Mellanslag/←/→) på bara när fokusläget är på."""
        for _sc in getattr(self, "_focus_shortcuts", []):
            with suppress(Exception):
                _sc.setEnabled(bool(on))

    def _enter_focus_mode(self) -> None:
        """NY v6.4.1: Gå in i Focus Mode."""
        self._cancel_inline_edit()
        self._focus_mode = True
        self._set_focus_shortcuts_enabled(True)
        self._focus_index = 0
        if hasattr(self, "content_stack"):
            self.content_stack.setCurrentIndex(1)
        self._update_focus_view()
        logger.info(f"{LOG_PREFIX} Focus Mode aktiverat")

    def _exit_focus_mode(self) -> None:
        """NY v6.4.1: Avsluta Focus Mode."""
        if not self._focus_mode:
            return
        self._focus_mode = False
        self._set_focus_shortcuts_enabled(False)
        if hasattr(self, "content_stack"):
            self.content_stack.setCurrentIndex(0)
        logger.info(f"{LOG_PREFIX} Focus Mode avslutat")

    def _toggle_focus_mode(self) -> None:
        """NY v6.4.1: Toggle Focus Mode (F3)."""
        if self._focus_mode:
            self._exit_focus_mode()
        else:
            self._enter_focus_mode()

    def _focus_next(self) -> None:
        """NY v6.4.1: Nästa task i Focus Mode."""
        tasks = self._get_focus_tasks()
        if not tasks:
            return
        self._focus_index = (self._focus_index + 1) % len(tasks)
        self._update_focus_view()

    def _focus_prev(self) -> None:
        """NY v6.4.1: Föregående task."""
        tasks = self._get_focus_tasks()
        if not tasks:
            return
        self._focus_index = (self._focus_index - 1) % len(tasks)
        self._update_focus_view()

    def _focus_complete(self) -> None:
        """NY v6.4.1: Markera aktuell task som klar."""
        tasks = self._get_focus_tasks()
        if not tasks or self._focus_index >= len(tasks):
            return
        task = tasks[self._focus_index]
        task_id = task.get("id")
        if not task_id:
            return
        try:
            if hasattr(self.store, "toggle_done"):
                self.store.toggle_done(task_id)
            logger.info(f"{LOG_PREFIX} _focus_complete: klar! task_id={task_id!r}")
        except Exception as e:
            logger.error(f"{LOG_PREFIX} _focus_complete misslyckades: {e}", exc_info=True)
            return
        self._rebuild_task_list()
        self._update_focus_view()

    def _periodic_zorder_check(self) -> None:
        """NY v6.4.1 v7-fix3: Periodisk z-order-check (var 60s).

        Rickard 2026-09-22: Widget ska EJ dölja ikoner. Workers-tricket
        ÄR Explorer-ikon-lagret → döljer ikoner. Rätt approach:
        reparenta till desktop-rot + HWND_TOP.
        """
        if not self.isVisible():
            return
        # FIX v7-fix29: barn → inga Win32-operationer från timern
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
            # Reparenta från WorkerW om vi blivit parentad dit
            try:
                current_parent = user32.GetParent(hwnd)
                if current_parent:
                    user32.SetParent(hwnd, 0)
                    logger.debug(
                        f"{LOG_PREFIX} _periodic_zorder_check: "
                        f"HWND={hwnd} reparentad till desktop-rot"
                    )
            except Exception:
                pass
            # Enbart re-show OM dold — INTE HWND_TOP (lyfter över appar)
            if not user32.IsWindowVisible(hwnd):
                user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
                logger.info(
                    f"{LOG_PREFIX} _periodic_zorder_check: "
                    f"HWND={hwnd} var GÖMT — re-show (ingen z-order-lyft)!"
                )
        except Exception as e:
            logger.debug(f"{LOG_PREFIX} _periodic_zorder_check misslyckades: {e}")

    def _install_win_d_blocker(self) -> None:
        """NY v6.4.1 v5: nativeEvent blockerar minimize. Se nativeEvent()."""
        if sys.platform != "win32":
            return
        if self._is_child():
            return  # FIX v7-fix29: barn → skalet hanterar
        logger.debug(f"{LOG_PREFIX} _install_win_d_blocker: redo (hanteras i nativeEvent)")

    @_log_call
    def _register_hotkeys(self) -> None:
        """
        NY v6.4.1 v7: Registrera globala hotkeys fran settings.

        FIX v7-fix78 (Rickard 2026-10-06: "tvungen att trycka
        Ctrl+Enter för att registrera"):
          ROT-ORSAKEN: QShortcut skapades för ALLA actions i settings
          — även de UTAN kopplad hanterare! Ett QShortcut utan
          hanterare MATCHAR och KONSUMERAR tangenten ändå (activated-
          signal utan lyssnare = tangenten försvinner i luften).
          Rickards sparade settings innehåller ett kortkommando som
          matchar vanlig Enter → Enter nådde aldrig input-fältet.
          Ctrl+Enter matchar INTE ett omodifierat kortkommando →
          nådde fältet → registrerade. Därför "fungerade" Ctrl+Enter!

          NU:
          - Kortkommandon UTAN hanterare skapas EJ (de stjäl bara
            tangenter) — loggas med varning per action
          - next_task/prev_task kopplas till riktig navigation (nytt!)
          - Enter skyddas dessutom i input-fältet via
            ShortcutOverride (se eventFilter) — inget kortkommando
            kan stjäla Enter medan man skriver
          - Tydlig logg per kortkommando (action=sekvens → hanterare)
        """
        # F1 = tangentöversikt (fast tangent, ligger utanför inställningarnas lista)
        with suppress(Exception):
            _f1 = QShortcut(QKeySequence("F1"), self)
            _f1.activated.connect(self._on_show_shortcut_help)
            self._hotkey_shortcuts.append(_f1)
        if not hasattr(self.settings, "shortcuts"):
            return
        try:
            shortcuts = self.settings.shortcuts()
            # FIX v7-fix78: varje kortkommando MÅSTE ha en hanterare
            handlers = {
                "add_task": ("_on_input_submit", self._on_input_submit),
                "toggle_visible": ("_on_close_clicked", self._on_close_clicked),
                "open_search": ("_focus_search", self._focus_search),
                "edit_task": ("_edit_selected_title", self._edit_selected_title),
                "next_task": (
                    "_navigate_tasks(ned)",
                    lambda: self._navigate_tasks(Qt.Key.Key_Down),
                ),
                "prev_task": (
                    "_navigate_tasks(upp)",
                    lambda: self._navigate_tasks(Qt.Key.Key_Up),
                ),
            }
            # Vanlig Enter/Return-koder (för varning vid kollision)
            _enter_codes = set()
            with suppress(Exception):
                _enter_codes = {
                    QKeySequence("Return")[0],
                    QKeySequence("Enter")[0],
                }
            _reg = []
            for action, seq in shortcuts.items():
                if not seq:
                    continue
                entry = handlers.get(action)
                if entry is None:
                    logger.warning(
                        f"{LOG_PREFIX} kortkommando '{action}'='{seq}' "
                        f"HAR INGEN hanterare — skapas EJ (ett QShortcut "
                        f"utan hanterare STJÄLER tangenten utan att göra "
                        f"något) (v7-fix78)"
                    )
                    continue
                if str(seq).strip().upper() == "F1":
                    logger.warning(
                        f"{LOG_PREFIX} kortkommando '{action}'='{seq}' hoppas över: "
                        f"F1 är reserverad för tangentöversikten"
                    )
                    continue
                name, fn = entry
                sc = QShortcut(QKeySequence(seq), self)
                sc.activated.connect(fn)
                self._hotkey_shortcuts.append(sc)
                _reg.append(f"{action}='{seq}'→{name}")
                # Varning: matchar detta kortkommando VANLIG ENTER?
                with suppress(Exception):
                    _ks = QKeySequence(seq)
                    if (
                        _enter_codes
                        and _ks.count() == 1
                        and _ks[0] in _enter_codes
                    ):
                        logger.warning(
                            f"{LOG_PREFIX} ⚠ kortkommando '{action}'="
                            f"'{seq}' matchar VANLIG ENTER — Enter är "
                            f"skyddad i input-fältet (ShortcutOverride) "
                            f"så den kan ej stjäla (v7-fix78)"
                        )
            logger.info(
                f"{LOG_PREFIX} {len(self._hotkey_shortcuts)} hotkeys "
                f"registrerade: {', '.join(_reg) or '(ingen)'}"
            )
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} _register_hotkeys misslyckades: "
                f"{_describe_widget_error(e)}",
                exc_info=True,
            )

    def _unregister_hotkeys(self) -> None:
        """NY v6.4.1 v7: Avregistrera hotkeys."""
        for sc in self._hotkey_shortcuts:
            with suppress(Exception):
                sc.setParent(None)
                sc.deleteLater()
        self._hotkey_shortcuts.clear()
        self._hotkey_ids.clear()
        logger.debug(f"{LOG_PREFIX} hotkeys avregistrerade")

    def _init_timers(self) -> None:
        """NY v6.4.1: Initiera debounce + PWM + z-order timers."""
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._do_search)
        self._rebuild_timer = QTimer(self)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.timeout.connect(self._rebuild_task_list)
        self._pwm_timer = QTimer(self)
        self._pwm_timer.timeout.connect(self._update_pwm)
        self._pwm_timer.start(PWM_FPS_NORMAL_MS)
        # NY v6.4.1 v5: Z-order periodic check
        self._zorder_timer = QTimer(self)
        self._zorder_timer.timeout.connect(self._periodic_zorder_check)
        self._zorder_timer.start(60_000)
        # NY v7-fix82: auto-tema — kolla var 10:e minut om klockan
        # passerat dag/gränsen (07:00/19:00) och växla isåfall
        # (gäller endast när användaren valt 'Auto' i tray-menyn)
        self._auto_theme_timer = QTimer(self)
        self._auto_theme_timer.setInterval(600_000)  # 10 minuter
        self._auto_theme_timer.timeout.connect(self._check_auto_theme)
        self._auto_theme_timer.start()
        # NY v7-fix73: bevaka textfälten — FocusIn aktiverar fönstret
        with suppress(Exception):
            if getattr(self, "input_field", None) is not None:
                self.input_field.installEventFilter(self)
            if getattr(self, "search_input", None) is not None:
                self.search_input.installEventFilter(self)
        logger.debug(f"{LOG_PREFIX} _init_timers klar (med z-order)")

    def _update_pwm(self) -> None:
        """
        NY v6.4.1 v7-fix: PWM-tick (saknad metod → widget-krasch).

        Buggrapport 2026-09-22:
          AttributeError: 'TodoWidget' object has no attribute '_update_pwm'
          (kopplad i _init_timers via timeout.connect)

        Vad den gör:
          1. Låter AdaptiveThrottle.update() räkna om state/intervall
          2. Synkar _pwm_timer till throttle.current_interval_ms
          3. Aldrig krascha — loggar bara vid fel (tyst crash → logg)
        """
        try:
            interval_ms = self._throttle.update()
            if (
                self._pwm_timer is not None
                and self._pwm_timer.interval() != interval_ms
            ):
                self._pwm_timer.setInterval(interval_ms)
        except Exception as _pwm_err:
            logger.debug(
                f"{LOG_PREFIX} _update_pwm: {_pwm_err}",
                exc_info=True,
            )

    def on_pwm_state_change(self, old: Any, new: Any) -> None:
        """
        NY v6.4.1 v7-fix: PWM state-change listener (widget = listener).

        ThrottleNotifier anropar denna via hasattr-listener-kedjan.
        Uppdaterar bara timer-intervall — ingen UI-rendering här.
        """
        try:
            interval_ms = self._throttle.current_interval_ms
            if self._pwm_timer is not None:
                self._pwm_timer.setInterval(interval_ms)
            old_name = getattr(old, "name", str(old))
            new_name = getattr(new, "name", str(new))
            logger.debug(
                f"{LOG_PREFIX} PWM state: {old_name} → {new_name} "
                f"({interval_ms}ms)"
            )
        except Exception as _pwm_ls_err:
            logger.debug(
                f"{LOG_PREFIX} on_pwm_state_change: {_pwm_ls_err}",
                exc_info=True,
            )
