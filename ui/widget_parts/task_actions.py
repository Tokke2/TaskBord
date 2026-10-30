# -*- coding: utf-8 -*-
"""
ui/widget_parts/task_actions.py — Uppgiftshändelser: bocka av, nåla fast, redigera titel, radera, lägg till, prioritet, flikar, sök och taggklick.

Del av TodoWidget (delad ur ui/widget.py). Metoderna är oförändrade; klassen
blandas in i TodoWidget i ui/widget.py. Gemensamma konstanter, hjälpfunktioner
och Qt-importer kommer från ui/widget_base.py, små UI-klasser från ui/widget_atoms.py.
"""
from __future__ import annotations

from ui.widget_base import *  # noqa: F401,F403
from ui.widget_atoms import *  # noqa: F401,F403
from core import links as _link_utils


class TaskActionsMixin:
    """Uppgiftshändelser: bocka av, nåla fast, redigera titel, radera, lägg till, prioritet, flikar, sök och taggklick."""

    def _on_task_toggle(self, task_id: str, done: bool) -> None:
        """
        NY v6.4.1 v7: Kryssa i/ur checkbox (med forbattrad felhantering).

        Vid fel: visar svensk dialog istallet for att krascha.
        """
        get_throttle().notify_activity()
        logger.info(
            f"{LOG_PREFIX} _on_task_toggle: task_id={task_id!r}, done={done}"
        )
        try:
            if hasattr(self.store, "toggle_task"):
                success = self.store.toggle_task(task_id)
                if success:
                    logger.info(
                        f"{LOG_PREFIX} store.toggle_task({task_id!r}) → OK"
                    )
                else:
                    logger.debug(
                        f"{LOG_PREFIX} store.toggle_task({task_id!r}) → False"
                    )
            else:
                logger.warning(
                    f"{LOG_PREFIX} store saknar toggle_task() — kan inte markera klar"
                )
                _show_widget_error(
                    self,
                    "Kan inte markera som klar",
                    "Store-funktionen 'toggle_task' saknas.",
                    category="code_bug",
                )
                return
            self._rebuild_task_list()
            self._schedule_rebuild()
            self._audit.add("task_toggled", {"task_id": task_id, "done": done})
        except Exception as e:
            logger.error(
                f"{LOG_PREFIX} _on_task_toggle misslyckades: {_describe_widget_error(e)}",
                exc_info=True,
            )
            _show_widget_error(
                self,
                "Kunde inte markera som klar",
                f"Uppgiften kunde inte uppdateras:\n{_describe_widget_error(e)}",
                exc=e,
                category=_categorize_widget_error(e),
            )

    @_log_event("task:pin_toggle")
    def _on_pin_toggle(self, task_id: str) -> None:
        """
        NY v6.4.1 v7: Toggle pin (med forbattrad felhantering).
        """
        get_throttle().notify_activity()
        logger.debug(f"{LOG_PREFIX} _on_pin_toggle: task_id={task_id!r}")
        try:
            if hasattr(self.store, "toggle_pinned"):
                self.store.toggle_pinned(task_id)
            else:
                logger.warning(
                    f"{LOG_PREFIX} store saknar toggle_pinned() — pinnas inte"
                )
                return
            self._schedule_rebuild()
            self._audit.add("task_pin_toggled", {"task_id": task_id})
            logger.info(f"{LOG_PREFIX} pin toggle OK: {task_id!r}")
        except Exception as e:
            logger.error(
                f"{LOG_PREFIX} _on_pin_toggle misslyckades: {_describe_widget_error(e)}",
                exc_info=True,
            )

    @_log_event("task:title_edited")
    # ------------------------------------------------------------------
    # Redigera titeln på plats (dubbelklick / F2 / E / menyn "Byt namn")
    # ------------------------------------------------------------------
    def _start_inline_title_edit(self, task_id: str) -> bool:
        """Lägg en textruta över kortets titel. Returnerar False om kortet inte syns (då tar dialogen över)."""
        try:
            if getattr(self, "_focus_mode", False):
                return False
            card = self._task_widgets.get(task_id)
            if card is None:
                return False
            lbl = card.findChild(QLabel, "taskTitle")
            if lbl is None or not lbl.isVisible():
                return False
            self._cancel_inline_edit()
            task = self.store.find_task(task_id) if hasattr(self.store, "find_task") else None
            title = str((task or {}).get("title") or lbl.text())
            parent = lbl.parentWidget() or card
            ed = InlineTitleEdit(title, parent)
            _f = lbl.font()
            _f.setStrikeOut(False)
            ed.setFont(_f)
            h = max(lbl.height(), ed.sizeHint().height())
            ed.setGeometry(lbl.x(), lbl.y() + (lbl.height() - h) // 2, max(lbl.width(), 80), h)
            ed.committed.connect(lambda text, t=task_id, e=ed: self._inline_title_committed(t, text, e))
            ed.cancelled.connect(lambda t=task_id, e=ed: self._inline_title_cancelled(t, e))
            self._inline_edit = ed
            with suppress(Exception):
                self._activate_for_typing()  # NOACTIVATE av så tangenter når rutan
            ed.show()
            ed.raise_()
            ed.setFocus(Qt.FocusReason.ShortcutFocusReason)
            ed.selectAll()
            get_throttle().notify_activity()
            logger.info(f"{LOG_PREFIX} redigerar titel på plats: {task_id!r}")
            return True
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} _start_inline_title_edit: {_describe_widget_error(e)}")
            self._inline_edit = None
            return False

    def _cancel_inline_edit(self) -> None:
        """Stäng en pågående titelredigering utan att spara (t.ex. innan en ny startar)."""
        ed = getattr(self, "_inline_edit", None)
        self._inline_edit = None
        if ed is not None:
            with suppress(Exception):
                ed._done = True
                ed.hide()
                ed.deleteLater()

    def _finish_inline_edit(self, ed: Any) -> None:
        if getattr(self, "_inline_edit", None) is ed:
            self._inline_edit = None
        with suppress(Exception):
            ed.hide()
            ed.deleteLater()

    def _inline_title_committed(self, task_id: str, text: str, ed: Any) -> None:
        """Enter eller klick utanför: spara titeln (tom titel eller oförändrad = ingen ändring)."""
        by_enter = bool(getattr(ed, "by_enter", False))
        self._finish_inline_edit(ed)
        try:
            task = self.store.find_task(task_id) if hasattr(self.store, "find_task") else None
            old = str((task or {}).get("title") or "")
            if text and text != old:
                self._store_call("update_task_title", task_id, text, _what="namn")
                logger.info(f"{LOG_PREFIX} titel ändrad på plats: {task_id!r}")
            if by_enter and task_id in getattr(self, "_nav_tids", ()):
                self._nav_select(task_id)  # fortsätt med tangentbordet där du var
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} _inline_title_committed: {_describe_widget_error(e)}")

    def _inline_title_cancelled(self, task_id: str, ed: Any) -> None:
        self._finish_inline_edit(ed)
        with suppress(Exception):
            if task_id in getattr(self, "_nav_tids", ()):
                self._nav_select(task_id)

    def _edit_selected_title(self) -> None:
        """F2 (snabbtangent 'edit_task'): redigera den markerade uppgiftens titel på plats."""
        tid = getattr(self, "_sel_tid", None)
        if not tid:
            logger.debug(f"{LOG_PREFIX} F2: ingen uppgift markerad")
            return
        if not self._start_inline_title_edit(tid):
            self._prompt_rename(tid)

    def _on_title_edited(self, task_id: str, new_text: str) -> None:
        """
        NY v6.4.1 v7: Uppdatera titel (med validering + felhantering).
        """
        get_throttle().notify_activity()
        if not new_text or not new_text.strip():
            logger.debug(
                f"{LOG_PREFIX} _on_title_edited: tom titel for {task_id!r} — ignorerar"
            )
            return
        cleaned_text = new_text.strip()
        if len(cleaned_text) > 500:
            logger.warning(
                f"{LOG_PREFIX} titel for lang ({len(cleaned_text)} tecken) — trunkerar"
            )
            cleaned_text = cleaned_text[:500]
        try:
            if hasattr(self.store, "update_task_title"):
                self.store.update_task_title(task_id, cleaned_text)
            self._schedule_rebuild()
            self._audit.add(
                "task_title_edited",
                {"task_id": task_id, "new": cleaned_text[:30]}
            )
            logger.info(
                f"{LOG_PREFIX} titel uppdaterad: {task_id!r} → {cleaned_text[:30]!r}"
            )
        except Exception as e:
            logger.error(
                f"{LOG_PREFIX} _on_title_edited misslyckades: {_describe_widget_error(e)}",
                exc_info=True,
            )

    @_log_event("task:delete")
    def _on_delete_clicked(self, task_id: str, task_text: str) -> None:
        """
        NY v6.4.1 v7: Ta bort task (med forbattrad dialog + felhantering).
        """
        get_throttle().notify_activity()
        logger.info(
            f"{LOG_PREFIX} _on_delete_clicked: task_id={task_id!r}, "
            f"text={task_text[:30]!r}"
        )
        try:
            if QMessageBox is None:
                logger.warning(
                    f"{LOG_PREFIX} QMessageBox saknas — kan inte visa dialog"
                )
                return
            if self._task_is_archived(task_id):
                self._explain_archive_is_history()
                return
            # NY v6.4.1 v7: Svensk bekräftelsedialog med tydlig info
            preview = task_text if len(task_text) < 60 else task_text[:57] + "..."
            reply = QMessageBox.question(
                self,
                "Ta bort uppgift?",
                f"Vill du ta bort den har uppgiften?\n\n"
                f"\"{preview}\"\n\n"
                f"Detta går inte att angra.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,  # Default = Nej (sakerhetsval)
            )
            if reply == QMessageBox.StandardButton.Yes:
                logger.info(
                    f"{LOG_PREFIX} ta bort: användare bekräftade {task_id!r}"
                )
                if hasattr(self.store, "remove_task"):
                    success = self.store.remove_task(task_id)
                    logger.info(
                        f"{LOG_PREFIX} store.remove_task({task_id!r}) → {success}"
                    )
                else:
                    logger.warning(
                        f"{LOG_PREFIX} store saknar remove_task() — inget taget bort"
                    )
                    _show_widget_error(
                        self,
                        "Kan inte ta bort",
                        "Store-funktionen 'remove_task' saknas.",
                        category="code_bug",
                    )
                    return
                self._rebuild_task_list()
                self._schedule_rebuild()
                self._audit.add("task_deleted", {"task_id": task_id})
            else:
                logger.debug(
                    f"{LOG_PREFIX} ta bort: användare avbrott {task_id!r}"
                )
        except Exception as e:
            logger.error(
                f"{LOG_PREFIX} _on_delete_clicked misslyckades: {_describe_widget_error(e)}",
                exc_info=True,
            )

    @_log_event("input:submit")
    def _on_input_submit(self) -> None:
        """
        NY v6.4.1 v7: Submit ny task (med validering + felhantering).
        """
        get_throttle().notify_activity()
        text = self.input_field.text().strip()
        if not text:
            logger.debug(f"{LOG_PREFIX} _on_input_submit: tom input — ignorerar")
            return
        # URL:er i texten blir klickbara länkar (🔗) med sidans titel; resten är uppgiftens text.
        # Tas ut FÖRE tolkningen av datum/taggar så siffror i adressen inte tolkas som datum.
        _urls = _link_utils.extract_urls(text)
        if _urls:
            _rest = _link_utils.strip_urls(text)
            text = _rest or _link_utils.display_title(_urls[0])
        if len(text) > 500:
            logger.warning(
                f"{LOG_PREFIX} input-text for lang ({len(text)} tecken) — trunkerar"
            )
            text = text[:500]
        current = self._pending_input_priority
        try:
            if not hasattr(self.store, "add_task"):
                logger.warning(
                    f"{LOG_PREFIX} store saknar add_task() — kan inte lagga till"
                )
                _show_widget_error(
                    self,
                    "Kan inte lagga till uppgift",
                    "Store-funktionen 'add_task' saknas.",
                    category="code_bug",
                )
                return
            # NY v7-fix65: naturligt språk — tolka datum/tid/prio/taggar
            # ("mjölk imorgon 15:00 !hög #hem"). Utan match = som förr.
            _nl = parse_natural_input(text)
            _title = _nl.get("title") or text
            _prio = _nl.get("priority") or current
            _due = _nl.get("due_date")
            _tags = _nl.get("tags") or []
            _start = _nl.get("start_date")
            if (_due or _tags or _start or _nl.get("priority")
                    or _title != text):
                logger.info(
                    f"{LOG_PREFIX} NL-input tolkad: titel='{_title[:30]}' "
                    f"due={_due} start={_start} prio={_prio} tags={_tags}"
                )
            tid = self.store.add_task(
                _title, priority=_prio,
                due_date=_due, tags=_tags,
            )
            if tid and _start and hasattr(self.store, "set_start_date"):
                self.store.set_start_date(tid, _start)  # NY v8: valfritt startdatum
            if tid and _urls:
                self._add_links_to_task(tid, _urls)
            if tid:
                self.input_field.clear()
                # Återställ pending priority till "none"
                self._pending_input_priority = "none"
                self._update_input_priority_indicator()
                # FIX v7-fix77: Enter SKA registrera uppgiften SYNGLIGT
                # i 'Aktiva' — tidigare enbart debounced rebuild (50 ms)
                # och listan sorterar nya uppgifter LÄNGST NED (skapad
                # sist) → kändes som att Enter "inte gjorde något" om
                # listan var lång/under Arkiverade-fliken.
                self._show_task_in_active(tid)
                self._audit.add(
                    "task_added",
                    {"task_id": tid, "title": text[:30], "priority": current}
                )
                logger.info(
                    f"{LOG_PREFIX} ny uppgift: {tid!r} '{text[:30]}' (priority={current})"
                )
            else:
                logger.warning(
                    f"{LOG_PREFIX} add_task returnerade ingen id (text={text[:30]!r})"
                )
                _show_widget_error(
                    self,
                    "Kunde inte spara uppgift",
                    "Lagringen returnerade inget id. Forsok igen.",
                    category="system",
                )
        except Exception as e:
            logger.error(
                f"{LOG_PREFIX} _on_input_submit misslyckades: {_describe_widget_error(e)}",
                exc_info=True,
            )
            _show_widget_error(
                self,
                "Kunde inte lagga till uppgift",
                f"Ett fel uppstod:\n{_describe_widget_error(e)}",
                exc=e,
                category=_categorize_widget_error(e),
            )

    @_log_event("priority:dot_clicked")
    def _on_priority_dot_clicked(
        self, task_id: str, new_priority: str
    ) -> None:
        """
        NY v6.4.1 v7: Klick pa fargpricken (satt prioritet).
        """
        self._set_task_priority(task_id, new_priority)

    @_log_event("priority:dot_right_clicked")
    def _on_priority_dot_right_clicked(
        self, task_id: str, current_priority: str
    ) -> None:
        """
        NY v6.4.1 v7: Hogerklick pa fargpricken (context-meny).
        """
        try:
            if QMenu is None:
                logger.warning(f"{LOG_PREFIX} QMenu saknas — kan inte visa context-meny")
                return
            menu = QMenu(self)
            menu.setTitle(f"Prioritet for uppgift {task_id[:6]}")
            for p in PRIORITY_CYCLE:
                label = {
                    "none":   "Ingen (gra)",
                    "high":   "Hog (rod)",
                    "medium": "Normal (gul)",
                    "low":    "Lag (gron)",
                }.get(p, p)
                action = menu.addAction(label)
                action.setCheckable(True)
                if p == current_priority:
                    action.setChecked(True)
                action.triggered.connect(
                    lambda checked=False, pid=task_id, pp=p:
                        self._set_task_priority(pid, pp)
                )
            menu.exec(QCursor.pos())
            self._audit.add(
                "priority_menu_shown",
                {"task_id": task_id, "current": current_priority}
            )
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} priority-meny misslyckades: {_describe_widget_error(e)}"
            )

    @_log_event("input:set_priority")
    def _set_input_priority(self, new_priority: str) -> None:
        """Satt pending prioritet i input-rutan."""
        get_throttle().notify_activity()
        if new_priority not in PRIORITY_CYCLE:
            logger.warning(
                f"{LOG_PREFIX} _set_input_priority: ogiltig {new_priority!r}"
            )
            return
        self._pending_input_priority = new_priority
        self._update_input_priority_indicator()
        self._audit.add(
            "input_priority_set", {"priority": new_priority}
        )
        logger.debug(
            f"{LOG_PREFIX} pending priority satt: {new_priority}"
        )

    def _update_input_priority_indicator(self) -> None:
        """
        NY v6.4.1 v7-fix: Uppdatera visuella prioritets-indikatorn vid input.

        Buggrapport 2026-09-22:
          AttributeError: 'TodoWidget' object has no attribute '_update_input_priority_indicator'
          på rad 1485 i _init_ui, och på rad 1741/1830 i andra metoder.

        Vad den gör:
          1. Uppdatera input_priority_dot (stor prick) till aktuell pending_priority
          2. Uppdatera de 3 små prickarna (high/medium/low) för highlighting
        """
        try:
            cur = getattr(self, "_pending_input_priority", "none")
            # Stor prick (input_priority_dot) — finns bara efter _init_ui
            if hasattr(self, "input_priority_dot"):
                try:
                    self.input_priority_dot.set_priority(cur)
                    # Force repaint
                    self.input_priority_dot.update()
                except Exception:
                    pass
            # Små prickar — highlight den aktiva prioriteten
            if hasattr(self, "_input_priority_dots"):
                for dot in self._input_priority_dots:
                    try:
                        # Hitta task_id för att se om det matchar
                        tid = dot.property("task_id") or ""
                        if tid.startswith("__input_"):
                            prio = tid.replace("__input_", "").replace("__", "")
                            if prio == cur:
                                dot.set_active(True)
                            else:
                                dot.set_active(False)
                        dot.update()
                    except Exception:
                        pass
            logger.trace(
                f"{LOG_PREFIX} _update_input_priority_indicator: "
                f"cur={cur}"
            )
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} _update_input_priority_indicator misslyckades: "
                f"{_describe_widget_error(e)}",
                exc_info=True,
            )

    @_log_event("task:set_priority")
    def _set_task_priority(self, task_id: str, new_priority: str) -> None:
        """
        NY v6.4.1 v7: Satt prioritet pa specifik task (med validering).
        """
        get_throttle().notify_activity()
        if new_priority not in PRIORITY_CYCLE:
            logger.warning(
                f"{LOG_PREFIX} _set_task_priority: ogiltig prioritet "
                f"{new_priority!r}, tillåtna: {PRIORITY_CYCLE}"
            )
            return
        try:
            if hasattr(self.store, "set_priority"):
                ok = self.store.set_priority(task_id, new_priority)
                if ok:
                    logger.info(
                        f"{LOG_PREFIX} prioritet satt: {task_id!r} → {new_priority}"
                    )
                    self._audit.add(
                        "task_priority_set",
                        {"task_id": task_id, "priority": new_priority}
                    )
                    self._rebuild_task_list()
                    self._schedule_rebuild()
                else:
                    logger.debug(
                        f"{LOG_PREFIX} set_priority: {task_id!r} oforandrad "
                        f"({new_priority})"
                    )
            else:
                logger.warning(
                    f"{LOG_PREFIX} store saknar set_priority()"
                )
        except Exception as e:
            logger.error(
                f"{LOG_PREFIX} _set_task_priority misslyckades: {_describe_widget_error(e)}",
                exc_info=True,
            )

    def _on_input_priority_dot_clicked(
        self, _task_id: str, new_priority: str
    ) -> None:
        """Klick pa stora input-pricken → cykla."""
        self._set_input_priority(new_priority)

    @_log_event("tab:changed")
    def _on_tab_changed(self, index: int) -> None:
        """Tab andrad."""
        get_throttle().notify_activity()
        old_index = self._active_tab_index
        self._active_tab_index = index
        self._audit.add(
            "tab_changed", {"from": old_index, "to": index}
        )
        logger.debug(
            f"{LOG_PREFIX} tab: {old_index} → {index}"
        )

    def _on_search_changed(self, text: str) -> None:
        """
        NY v6.4.1 v7-fix: Sökfältet ändrades → schemalägg sökning (debounce).

        Buggrapport 2026-09-22 (efter force-show-fix):
          AttributeError: 'TodoWidget' object has no attribute '_on_search_changed'
          på rad 1396 (search_input.textChanged.connect(self._on_search_changed))
          Python hint: Did you mean: '_on_tab_changed'?

        Vi använder _search_timer (debounce 150ms) så vi inte kör sökning
        på varje tangenttryck. Vid tom sträng → rebuild direkt (visa alla).
        """
        try:
            get_throttle().notify_activity()
            self._current_filter = text or ""
            # Schemalägg sökning (debounce)
            if self._search_timer is not None:
                self._search_timer.start(SEARCH_DEBOUNCE_MS)
            self._audit.add("search_changed", {"length": len(text)})
            logger.debug(
                f"{LOG_PREFIX} _on_search_changed: '{text[:30]}' "
                f"(schemalagd om {SEARCH_DEBOUNCE_MS}ms)"
            )
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} _on_search_changed misslyckades: "
                f"{_describe_widget_error(e)}",
                exc_info=True,
            )

    @_log_event("search:do")
    def _do_search(self) -> None:
        """Utfor sokning (med forbattrad felhantering)."""
        start = time.perf_counter()
        query = self._current_filter.lower().strip()
        if not query:
            self._rebuild_task_list()
            return
        try:
            if hasattr(self.store, "active_tasks_filtered"):
                tasks = self.store.active_tasks_filtered(
                    query=query, sort_by="pinned_first"
                )
            else:
                tasks = []
            self._render_tasks(tasks, archived=False)
            duration = (time.perf_counter() - start) * 1000
            self._audit.add(
                "search",
                {"query": query, "results": len(tasks), "ms": duration}
            )
            logger.debug(
                f"{LOG_PREFIX} sokning {query!r}: {len(tasks)} tradar pa {duration:.2f}ms"
            )
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} sokning misslyckades: {_describe_widget_error(e)}",
                exc_info=True,
            )

    _UPDATE_BTN_STYLES = {
        "available": "QPushButton#winBtn { background: #15803d; color: #ffffff; border: 1px solid #86efac; }"
                     " QPushButton#winBtn:hover { background: #166534; }",
        "current": "QPushButton#winBtn { color: #86efac; }",
        "installing": "QPushButton#winBtn { background: #b45309; color: #ffffff; border: 1px solid #fcd34d; }",
    }
    _UPDATE_BTN_TEXTS = {"idle": "⟳", "checking": "⏳", "available": "⬆", "installing": "⏳", "current": "✓"}
    _UPDATE_BAR_STYLES = {
        "available": ("#14532d", "#bbf7d0"),   # (bakgrund, kant) — vit text, vit knapp med mörkgrön text
        "installing": ("#92400e", "#fcd34d"),
    }

    def set_update_state(self, state: str, tooltip: str = "", count: int = 0) -> None:
        """
        Uppdateringsknappen (ikon) i titelraden + raden "Ny version finns — Uppdatera nu" under den.
        state: idle | checking | available | installing | current.
        """
        btn = getattr(self, "update_btn", None)
        if btn is None:
            return
        try:
            state = state if state in self._UPDATE_BTN_TEXTS else "idle"
            btn.setText(self._UPDATE_BTN_TEXTS[state])
            btn.setStyleSheet(self._UPDATE_BTN_STYLES.get(state, ""))
            btn.setEnabled(state not in ("checking", "installing"))
            btn.setAccessibleName({
                "idle": "Sök ny version", "checking": "Söker efter ny version", "available": "Ny version finns — uppdatera",
                "installing": "Installerar uppdatering", "current": "Du har senaste versionen",
            }[state])
            if tooltip:
                btn.setToolTip(tooltip)
            bar = getattr(self, "update_bar", None)
            if bar is not None:
                if state in self._UPDATE_BAR_STYLES:
                    bg, edge = self._UPDATE_BAR_STYLES[state]
                    bar.setStyleSheet(
                        f"QFrame#updateBar {{ background: {bg}; border: 1px solid {edge}; border-radius: 8px; }}"
                        "QFrame#updateBar QLabel { color: #ffffff; background: transparent; font-size: 12px; font-weight: 600; }"
                        f"QFrame#updateBar QPushButton {{ background: #ffffff; color: {bg}; border: none; border-radius: 6px;"
                        " font-size: 12px; font-weight: 700; padding: 0 12px; }"
                        "QFrame#updateBar QPushButton:hover { background: #e5e7eb; }"
                    )
                    if state == "available":
                        self.update_label.setText(
                            f"🆕 Ny version finns ({count} fil{'er' if count != 1 else ''})" if count else "🆕 Ny version finns")
                    else:
                        self.update_label.setText("⏳ Installerar uppdateringen — Ledgebord startar om strax…")
                    self.update_now_btn.setVisible(state == "available")
                    if tooltip:
                        bar.setToolTip(tooltip)
                bar.setVisible(state in self._UPDATE_BAR_STYLES)
            self._update_state = state
        except Exception as e:
            logger.debug(f"{LOG_PREFIX} set_update_state: {_describe_widget_error(e)}")

    def _on_update_clicked(self) -> None:
        """Klick på uppdateringsknappen → appen söker eller (om en ny version redan hittats) installerar."""
        try:
            self._audit.add("update_clicked")
            self.update_requested.emit()
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} _on_update_clicked misslyckades: {_describe_widget_error(e)}")

    def _on_hide_to_tray_clicked(self) -> None:
        """Knapparna – och ✕: göm fönstret till systemfältet (appen fortsätter köra)."""
        try:
            self._audit.add("hide_to_tray_clicked")
            self.hide_to_tray_requested.emit()
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} _on_hide_to_tray_clicked misslyckades: {_describe_widget_error(e)}")

    def _on_close_clicked(self) -> None:
        """BUGG 19/26: close = satt z-order."""
        try:
            self._setup_bugg19_zorder()
            self._audit.add("close_clicked")
            logger.debug(f"{LOG_PREFIX} _on_close_clicked: z-order uppdaterad")
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} _on_close_clicked misslyckades: {_describe_widget_error(e)}"
            )

    @_log_event("event:tag_clicked")
    def _on_tag_clicked(self, tag: str) -> None:
        """
        NY v6.4.1 v7: Filtrera pa tag (med svenska logg).
        """
        get_throttle().notify_activity()
        logger.debug(f"{LOG_PREFIX} tag-filter: {tag!r}")
        self._current_tag_filter = [tag]
        self._current_filter = tag
        if hasattr(self, "search_input"):
            self.search_input.setText(tag)
        self._audit.add("tag_filter", {"tag": tag})
