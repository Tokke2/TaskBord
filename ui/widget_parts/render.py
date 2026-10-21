# -*- coding: utf-8 -*-
"""
ui/widget_parts/render.py — Rendering av listan: eventFilter, blink för ny uppgift, ombyggnad av flikar/lista, paintEvent och statistikchip.

Del av TodoWidget (delad ur ui/widget.py). Metoderna är oförändrade; klassen
blandas in i TodoWidget i ui/widget.py. Gemensamma konstanter, hjälpfunktioner
och Qt-importer kommer från ui/widget_base.py, små UI-klasser från ui/widget_atoms.py.
"""
from __future__ import annotations

from ui.widget_base import *  # noqa: F401,F403
from ui.widget_atoms import *  # noqa: F401,F403


class RenderMixin:
    """Rendering av listan: eventFilter, blink för ny uppgift, ombyggnad av flikar/lista, paintEvent och statistikchip."""

    def eventFilter(self, obj: QWidget, event: QEvent) -> bool:
        """
        NY v6.4.1 v7: Fanga piltangenter pa task-containers (for prioritet).

        ← = foregaende prioritet, → = nasta (enligt PRIORITY_CYCLE)
        NY v7-fix73: FocusIn i textfält → aktivera fönstret för
        inmatning (NOACTIVATE av + förgrund) — annars blockerar
        NOACTIVATE tangentbordsinput.
        """
        try:
            # ============================================================
            # FIX v7-fix78: Enter tillhör INPUT-FÄLTET — två skydd:
            #
            # BAKGRUND (Rickard 2026-10-06: "tvungen att trycka
            # Ctrl+Enter för att registrera"): Qt:s kortkommandon
            # (QShortcut) matchar TANGENTER FÖRE de når widgeten, men
            # bara OMODIFIERADE tangenter. Ett kortkommando som matchar
            # vanlig Return stjäl alltså Enter i luften — medan
            # Ctrl+Enter inte matchar → når fältet → registrerade.
            #
            # a) ShortcutOverride: Qt frågar den fokuserade widgeten
            #    "får kortkommandon stjäla denna tangent?" — QLineEdit
            #    svarar NEJ för Enter som default. Vi svarar JA
            #    (=fältet tar tangenten) → Enter når ALLTID fältet.
            # b) KeyPress-skydd: extra försäkring utöver
            #    keyPressEvent-överriden + returnPressed (3 lager).
            # ============================================================
            _if = getattr(self, "input_field", None)
            if _if is not None and obj is _if:
                _et = event.type()
                if _et == QEvent.Type.ShortcutOverride:
                    if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                        event.accept()
                        return True
                elif _et == QEvent.Type.KeyPress:
                    if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                        logger.info(
                            f"{LOG_PREFIX} Enter i input-fältet → "
                            f"registrerar uppgiften i 'Aktiva' (v7-fix78)"
                        )
                        self._on_input_submit()
                        event.accept()
                        return True
            # NY v7-fix73: textfältsfokus → gör fönstret skrivbart
            if (
                event.type() == QEvent.Type.FocusIn
                and obj in (self.input_field, self.search_input)
            ):
                with suppress(Exception):
                    self._activate_for_typing()
                if self._nav_active:
                    self._nav_exit()
            if (
                event.type() == QEvent.Type.MouseButtonPress
                and isinstance(obj, QFrame)
                and obj.objectName().startswith("task_")
                and event.button() in (
                    Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton,
                )
            ):
                _ctid = obj.property("task_id")
                if _ctid and not getattr(self, "_focus_mode", False):
                    self._nav_select_by_mouse(str(_ctid))
                return False  # låt klicket gå vidare (flytta fönstret, knappar, meny)
            if (
                event.type() == QEvent.Type.KeyPress
                and isinstance(obj, QFrame)
                and obj.objectName().startswith("task_")
            ):
                key = event.key()
                task_id = obj.property("task_id")
                if not task_id:
                    return super().eventFilter(obj, event)
                if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
                    cur = obj.property("task_priority") or "none"
                    if cur not in PRIORITY_CYCLE:
                        cur = "none"
                    idx = PRIORITY_CYCLE.index(cur)
                    if key == Qt.Key.Key_Right:
                        new_idx = (idx + 1) % len(PRIORITY_CYCLE)
                    else:
                        new_idx = (idx - 1) % len(PRIORITY_CYCLE)
                    new_p = PRIORITY_CYCLE[new_idx]
                    logger.info(
                        f"{LOG_PREFIX} piltangent på task {task_id!r}: "
                        f"{cur} → {new_p}"
                    )
                    self._set_task_priority(task_id, new_p)
                    get_throttle().notify_activity()
                    return True
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} eventFilter misslyckades: {_describe_widget_error(e)}",
                exc_info=True,
            )
        return super().eventFilter(obj, event)

    def _show_task_in_active(self, task_id: str) -> None:
        """
        NY v7-fix77: registrera en ny uppgift SYNGLIGT i 'Aktiva'.

        Rickards önskan 2026-10-06: "när man skrivit en uppgift så ska
        Enter-knappen registrera den inom 'Aktiv'". Flödet gör nu:
          1. OMEDELBAR synkron rebuild (ej bara 50 ms debounce —
             timern kunde missas/senareläggas)
          2. Byt till 'Aktiva'-fliken om man stod på 'Arkiverade'
          3. Byt till normalvyn om Focus Mode var aktiv
          4. Scrolla fram + accent-flasha den nya uppgiften
             (sorteringen lägger nya uppgifter sist i listan — utan
             scroll syntes den ej i långa listor!)
        Allt felhanterat — registreringen får ALDRIG krascha appen.
        """
        try:
            # 1. Omedelbar synkron rebuild av båda listorna
            with suppress(Exception):
                self._rebuild_task_list()

            # 2. + 3. Visa vyn där uppgiften finns (Aktiva + normalvy)
            _tab_changed = False
            with suppress(Exception):
                tabs = getattr(self, "tabs", None)
                if tabs is not None and tabs.count() > 0 and tabs.currentIndex() != 0:
                    tabs.setCurrentIndex(0)  # 0 = 'Aktiva'
                    _tab_changed = True
            with suppress(Exception):
                stack = getattr(self, "content_stack", None)
                if stack is not None and stack.currentIndex() != 0:
                    stack.setCurrentIndex(0)  # 0 = normalvy (ej Focus)

            # 4. Scrolla fram + flasha den nya raden (task_<id>)
            _flashed = False
            with suppress(Exception):
                _flashed = self._flash_new_task(task_id)

            logger.info(
                f"{LOG_PREFIX} uppgift {task_id!r} registrerad i "
                f"'Aktiva' (flikbyte={_tab_changed}, flash={_flashed}) "
                f"(v7-fix77)"
            )
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} _show_task_in_active misslyckades: "
                f"{_describe_widget_error(e)}",
                exc_info=True,
            )

    def _flash_new_task(self, task_id: str) -> bool:
        """
        NY v7-fix77: scrolla fram + accent-flasha en nyskapad uppgift.

        Returnerar True om raden hittades (flash är ev. påbörjad).
        Flashen är en tillfällig inline-stylesheet på just denna rad
        (task_<id>) som tas bort efter 1,8 s → global QSS tar över igen.
        """
        name = f"task_{task_id}"
        target = None
        layout = getattr(self, "active_layout", None)
        if layout is not None:
            for i in range(layout.count()):
                item = layout.itemAt(i)
                w = item.widget() if item is not None else None
                if w is not None and w.objectName() == name:
                    target = w
                    break
        if target is None:
            logger.debug(
                f"{LOG_PREFIX} _flash_new_task: hittade ingen rad {name!r}"
            )
            return False
        # Scrolla fram raden (aktiva-flikens QScrollArea = tabs.widget(0))
        tabs = getattr(self, "tabs", None)
        if tabs is not None and tabs.count() > 0:
            scroll = tabs.widget(0)
            if scroll is not None and hasattr(scroll, "ensureWidgetVisible"):
                scroll.ensureWidgetVisible(target, 16, 16)
        # Accent-flash (FIX v8: kommer ihåg flashen så den överlever en ombyggnad av listan)
        self._flash_state = (task_id, time.monotonic() + 1.8)
        self._apply_flash(target, name, 1800)
        return True

    def _apply_flash(self, target: Any, name: str, ms: int) -> None:
        accent = getattr(self, "_theme_accent_hex", "#818cf8")

        def _clear_flash() -> None:
            with suppress(Exception):
                target.setStyleSheet("")

        try:
            target.setStyleSheet(
                f"QWidget#{name} {{"
                f" background: {accent}40;"
                f" border: 1px solid {accent};"
                f" border-radius: 8px;"
                f"}}"
            )
            QTimer.singleShot(max(50, int(ms)), _clear_flash)
        except Exception as e:
            logger.debug(
                f"{LOG_PREFIX} _flash: stylesheet kunde ej "
                f"sättas ({_describe_widget_error(e)}) — scroll räcker"
            )

    def _reapply_flash(self) -> None:
        """FIX v8: en ombyggnad av listan raderar korten → flashen försvann efter ~250 ms."""
        try:
            st = getattr(self, "_flash_state", None)
            if not st:
                return
            tid, until = st
            left_ms = int((until - time.monotonic()) * 1000)
            if left_ms <= 0:
                self._flash_state = None
                return
            name = f"task_{tid}"
            layout = getattr(self, "active_layout", None)
            for i in range(layout.count() if layout is not None else 0):
                w = layout.itemAt(i).widget() if layout.itemAt(i) is not None else None
                if w is not None and w.objectName() == name:
                    self._apply_flash(w, name, left_ms)
                    break
        except Exception:
            pass

    def _schedule_rebuild(self) -> None:
        """Schemalagg rebuild (debounce 50ms)."""
        if self._rebuild_timer is not None:
            self._rebuild_timer.start(REBUILD_DEBOUNCE_MS)
            logger.trace(f"{LOG_PREFIX} rebuild schemalagd ({REBUILD_DEBOUNCE_MS}ms)")

    @_log_event("rebuild")
    def _update_archive_tab_count(self, n: int) -> None:
        """
        NY v7-fix86: "Arkiverade (N)" i flikens titel — live-räknare.

        Cachar värdet så setTabText bara körs när antalet ändras
        (rendering sker ofta — undvik onödig QSS-omtolkning).
        """
        try:
            tabs = getattr(self, "tabs", None)
            if tabs is None or tabs.count() < 2:
                return
            if getattr(self, "_archive_tab_count", -1) == n:
                return
            self._archive_tab_count = n
            tabs.setTabText(1, f"Arkiverade ({n})" if n else "Arkiverade")
        except Exception:
            pass

    def _rebuild_task_list(self) -> None:
        """Bygg om task-listan (med forbattrad felhantering)."""
        start = time.perf_counter()
        try:
            if hasattr(self.store, "active_tasks_filtered"):
                # FIX v7-fix86: respektera AKTIV SÖKNING vid rebuild —
                # tidigare nollställdes filtret visuellt efter varje
                # ändring (ny uppgift/klar/etc) trots att söktexten
                # fanns kvar i fältet. Nu filtreras rebuilden likadant
                # som _do_search.
                _q = (getattr(self, "_current_filter", "") or "").lower().strip()
                if _q:
                    active = self.store.active_tasks_filtered(
                        query=_q, sort_by="pinned_first"
                    )
                else:
                    active = self.store.active_tasks_filtered(sort_by="pinned_first")
            else:
                active = []
            if hasattr(self.store, "archive_tasks"):
                archive = self.store.archive_tasks()
            else:
                archive = []
            self._render_tasks(active, archived=False)
            self._render_tasks(archive, archived=True)
            self._reapply_flash()
            self._build_search_index()
            duration = (time.perf_counter() - start) * 1000
            self._render_count += 1
            if duration > 50.0:
                self._slow_render_count += 1
                logger.warning(
                    f"{LOG_PREFIX} _rebuild_task_list LÅNGSAM: {duration:.2f}ms "
                    f"(active={len(active)}, archive={len(archive)})"
                )
            self._throttle.record_frame(duration)
            self._audit.add(
                "rebuild",
                {
                    "active": len(active),
                    "archive": len(archive),
                    "ms": duration,
                },
            )
        except Exception as e:
            logger.error(
                f"{LOG_PREFIX} _rebuild_task_list misslyckades: {_describe_widget_error(e)}",
                exc_info=True,
            )

    # ====================================================================
    # SOK-INDEX + THEME (NY v6.4.1 v7 - aterstaller saknade metoder)
    # ====================================================================

    # ====================================================================
    # TASK-RENDERING (NY v6.4.1 v7 - aterstaller saknade metoder)
    # ====================================================================

    @_log_call
    def _build_active_tab(self) -> QWidget:
        """NY v6.4.1 v7-fix: Bygg 'Aktiva'-fliken med scrollbar.

        Skapar en QScrollArea som innehåller en container med
        self.active_layout (QVBoxLayout) som _render_tasks() fyller på.
        """
        try:
            scroll = QScrollArea(self)
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(
                __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.ScrollBarPolicy.ScrollBarAlwaysOff
                if _QT_BACKEND == "PySide6"
                else 1  # PyQt fallback (ovanligt)
            )
            container = QWidget(scroll)
            self.active_layout = QVBoxLayout(container)
            self.active_layout.setContentsMargins(4, 4, 4, 4)
            self.active_layout.setSpacing(6)  # v7-fix17: luftigare
            self.active_layout.addStretch(1)
            scroll.setWidget(container)
            logger.debug(f"{LOG_PREFIX} _build_active_tab klar")
            return scroll
        except Exception as e:
            logger.error(
                f"{LOG_PREFIX} _build_active_tab misslyckades: "
                f"{_describe_widget_error(e)}",
                exc_info=True,
            )
            # Fallback: enkel QWidget
            fallback = QWidget(self)
            self.active_layout = QVBoxLayout(fallback)
            return fallback

    @_log_call
    def _build_archive_tab(self) -> QWidget:
        """NY v6.4.1 v7-fix: Bygg 'Arkiverade'-fliken med scrollbar.

        Samma struktur som _build_active_tab men for arkiverade tasks.
        """
        try:
            scroll = QScrollArea(self)
            scroll.setWidgetResizable(True)
            container = QWidget(scroll)
            self.archive_layout = QVBoxLayout(container)
            self.archive_layout.setContentsMargins(4, 4, 4, 4)
            self.archive_layout.setSpacing(6)  # v7-fix17: luftigare
            self.archive_layout.addStretch(1)
            scroll.setWidget(container)
            logger.debug(f"{LOG_PREFIX} _build_archive_tab klar")
            return scroll
        except Exception as e:
            logger.error(
                f"{LOG_PREFIX} _build_archive_tab misslyckades: "
                f"{_describe_widget_error(e)}",
                exc_info=True,
            )
            fallback = QWidget(self)
            self.archive_layout = QVBoxLayout(fallback)
            return fallback

    def _render_tasks(
        self,
        tasks: List[Dict[str, Any]],
        archived: bool = False
    ) -> None:
        """
        NY v6.4.1 v7: Rendera task-lista (med cache + felhantering).
        """
        try:
            # NY v7-fix41: senarelagda (snoozade) uppgifter döljs
            # från Aktiva-listan tills snooze-tiden är inne
            n_snoozed_hidden = 0
            if not archived:
                _n_before = len(tasks)
                tasks = [tk for tk in tasks if not _is_snoozed(tk)]
                n_snoozed_hidden = _n_before - len(tasks)
                if n_snoozed_hidden:
                    logger.debug(
                        f"{LOG_PREFIX} _render_tasks: "
                        f"{n_snoozed_hidden} senarelagda dolda"
                    )
            layout = (
                self.archive_layout if archived else self.active_layout
            )
            self._clear_layout(layout)
            layout.setSpacing(int(_density_profile(self.settings)["list_gap"]))
            if not tasks:
                if not archived:
                    self._nav_tids = []
                    self._sel_tid = None
                # v7-fix17/86: vänligare tom-text med emoji + guide
                empty_text = (
                    "✨  Inga uppgifter ännu\n"
                    "Skriv nedan och tryck Enter" if not archived
                    else "🗄️  Inga arkiverade uppgifter"
                )
                if not archived:
                    self._update_stats_chip(0, 0, n_snoozed_hidden)
                empty_label = QLabel(empty_text, self)
                empty_label.setObjectName("emptyHint")
                empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                layout.addWidget(empty_label)
                layout.addStretch(1)
                # NY v7-fix86: håll arkiv-flikens räknare uppdaterad
                self._update_archive_tab_count(0)
                return
            if not archived:
                # v7-fix17: live-stats i headern
                self._update_stats_chip(
                    len(tasks),
                    sum(1 for tk in tasks if tk.get("done")),
                    n_snoozed_hidden,
                )
            else:
                # NY v7-fix86: "Arkiverade (N)" i fliken
                self._update_archive_tab_count(len(tasks))
            _new_nav: List[str] = []
            for task in tasks:
                widget = self._build_task_widget_cached(task, archived)
                if widget is not None:
                    if not archived and task.get("id"):
                        _new_nav.append(str(task.get("id")))
                    layout.addWidget(widget)
                    # v7-fix10: show() måste komma EFTER addWidget() —
                    # addWidget() reparentar widgeten vilket döljer den
                    # igen. Kort skapade NÄR widgeten redan syns måste
                    # visas explicit (Qt visar ej nya barn automatiskt),
                    # annars blir listan tom vid om-rendering.
                    widget.show()
            layout.addStretch(1)
            if not archived:
                self._nav_after_render(_new_nav)
            logger.debug(
                f"{LOG_PREFIX} _render_tasks(archived={archived}): {len(tasks)} tasks"
            )
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} _render_tasks misslyckades: "
                f"{_describe_widget_error(e)}",
                exc_info=True,
            )

    def paintEvent(self, event: QPaintEvent) -> None:
        """
        NY v7-fix17 (design-tweak): aurora-glow längs fönstrets överkant.

        Målas EFTER super() (ovanpå QSS-bakgrunden) men UNDER barn-widgets
        (barn målas alltid efter förälderns paintEvent) — ger samma djup-
        känsla som GlassFrame, UTAN OS-transparens (WA_TranslucentBackground
        förblir AV enligt v7-fix7 → inga WS_POPUP-risker).
        """
        super().paintEvent(event)
        try:
            p = QPainter(self)
            if not p.isActive():
                return
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            w = self.width()
            h = self.height()
            if w < 8 or h < 8:
                return
            accent = QColor(
                getattr(self, "_theme_accent_hex", "#818cf8")
            )
            is_dark = getattr(self, "_theme_is_dark", True)
            glow = QRadialGradient(
                float(w / 2), 0.0, max(float(w) * 0.9, 1.0)
            )
            top_c = QColor(accent)
            top_c.setAlpha(32 if is_dark else 44)
            end_c = QColor(accent)
            end_c.setAlpha(0)
            glow.setColorAt(0.0, top_c)
            glow.setColorAt(1.0, end_c)
            # NY v7-fix38: klipp auroran mot rundade hörn när skalet är
            # genomskinligt — annars syns kvadratiska hörn genom glaset.
            if getattr(self, "_transparency_factor", 0.0) > 0.0:
                try:
                    from PySide6.QtGui import QPainterPath
                    clip = QPainterPath()
                    clip.addRoundedRect(
                        0.0, 0.0, float(w), float(h), 14.0, 14.0
                    )
                    p.save()
                    p.setClipPath(clip)
                    p.fillRect(
                        QRect(0, 0, w, int(h * 0.45)), QBrush(glow)
                    )
                    p.restore()
                except Exception:
                    p.fillRect(
                        QRect(0, 0, w, int(h * 0.45)), QBrush(glow)
                    )
            else:
                p.fillRect(
                    QRect(0, 0, w, int(h * 0.45)), QBrush(glow)
                )
        except Exception:
            pass  # design-får ALDRIG krascha appen

    def _update_stats_chip(
        self, n_active: int, n_done: int, n_snoozed: int = 0
    ) -> None:
        """
        NY v7-fix17: uppdatera headerns stats-chip ('X aktiva · Y klara').

        NY v7-fix86:
          - snoozade visas ('· N 💤') när > 0
          - tunn progress-bar under headern (% klara, accent-färg)
          - fönstertiteln får antal kvar ("TaskBord — 3 kvar") — syns
            när fönstret lyfts/flyter
        """
        chip = getattr(self, "stats_chip", None)
        if chip is None:
            return
        try:
            _txt = f"{n_active} aktiva · {n_done} klara"
            if n_snoozed:
                _txt += f" · {n_snoozed} 💤"
            chip.setText(_txt)
            # NY v7-fix86: progress-bar (qlineargradient efter %)
            bar = getattr(self, "progress_bar", None)
            if bar is not None:
                pct = (
                    int(round(100 * n_done / n_active))
                    if n_active else 0
                )
                accent = getattr(self, "_theme_accent_hex", "#818cf8")
                with suppress(Exception):
                    bar.setStyleSheet(
                        f"QFrame#headerProgress {{"
                        f" border: none; border-radius: 2px;"
                        f" background: qlineargradient("
                        f"x1:0, y1:0, x2:1, y2:0,"
                        f" stop:0 {accent},"
                        f" stop:{pct / 100:.3f} {accent},"
                        f" stop:{min(pct / 100 + 0.001, 1.0):.3f} rgba(148,163,184,70),"
                        f" stop:1 rgba(148,163,184,70));"
                        f"}}"
                    )
                    bar.setToolTip(
                        f"{pct}% klara ({n_done} av {n_active})"
                    )
            # NY v7-fix86: fönstertitel med antal kvar
            _left = max(n_active - n_done, 0)
            with suppress(Exception):
                self.setWindowTitle(
                    f"{self.DEFAULT_TITLE} — {_left} kvar"
                    if _left else self.DEFAULT_TITLE
                )
        except Exception:
            pass

    def _window_transparency_factor(self) -> float:
        """
        NY v7-fix38: aktuell fönstertransparens (0.0 = opak, 1.0 = full).

        Läser FÖRST skal-QWidgetens faktiska läge (main.pyw kan
        nedgradera automatiskt om CreateWindowEx misslyckades för det
        genomskinliga skalet), annars settings.
        """
        try:
            shell = getattr(self, "_shell", None)
            if shell is not None and hasattr(shell, "_shell_transparency"):
                f = float(shell._shell_transparency)
            elif self.settings is not None and hasattr(
                self.settings, "window_transparency"
            ):
                f = float(self.settings.window_transparency())
            elif self.settings is not None and hasattr(self.settings, "get"):
                f = float(self.settings.get("window_transparency", 0.85))
            else:
                f = 0.85
            if f <= 0.0:
                return 0.0
            return max(MIN_PANEL_OPACITY, min(1.0, f))
        except Exception:
            return 0.85

    def _build_task_widget_cached(
        self, task: Dict[str, Any], archived: bool
    ) -> Optional[QWidget]:
        """NY v6.4.1 v7: Bygg eller återanvänd task-widget (med cache).

        v7-fix10: cache-nyckeln omfattar nu ÄVEN done/priority/pinned —
        tidigare räckte matchande titel, vilket gav gamla stylade kort
        (t.ex. saknad genomstrykning) efter att en uppgift bockats av.
        """
        try:
            tid = task.get("id", "")
            # NY v7-fix41: nyckeln omfattar nu ÄVEN due/snooze/
            # recurring/subtasks — annars återanvänds gamla kort
            # efter senareläggning/delmoment-ändringar
            state_key = (
                task.get("title", ""),
                bool(task.get("done", False)),
                task.get("priority", "none"),
                bool(task.get("pinned")),
                str(task.get("due_date") or ""),
                str(task.get("start_date") or ""),
                str(task.get("snoozed_until") or ""),
                (task.get("recurring") or {}).get("interval", ""),
                tuple(_flatten_subtasks(task.get("subtasks") or [])),
                _task_has_email(task),
            )
            if tid in self._task_widgets and not archived:
                existing = self._task_widgets[tid]
                if existing.property("task_state") == state_key:
                    return existing
            widget = self._build_task_widget(task, archived)
            if widget is not None and not archived:
                widget.setProperty("task_state", state_key)
                self._task_widgets[tid] = widget
            return widget
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} _build_task_widget_cached misslyckades: "
                f"{_describe_widget_error(e)}",
                exc_info=True,
            )
            return None
