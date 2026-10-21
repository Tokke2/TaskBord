# -*- coding: utf-8 -*-
"""
ui/widget_parts/task_menu.py — Uppgifternas menyer och dialoger: högerklicksmeny, datum/start/underuppgifter, namnbyte och radering (frågor).

Del av TodoWidget (delad ur ui/widget.py). Metoderna är oförändrade; klassen
blandas in i TodoWidget i ui/widget.py. Gemensamma konstanter, hjälpfunktioner
och Qt-importer kommer från ui/widget_base.py, små UI-klasser från ui/widget_atoms.py.
"""
from __future__ import annotations

from ui.widget_base import *  # noqa: F401,F403
from ui.widget_atoms import *  # noqa: F401,F403


class TaskMenuMixin:
    """Uppgifternas menyer och dialoger: högerklicksmeny, datum/start/underuppgifter, namnbyte och radering (frågor)."""

    # ====================================================================
    # TASK ACTIONS (NY v6.4.1 v7 - 188888888% bättre med AI-felsökning)
    # ====================================================================

    @_log_event("task:toggle")
    def _snooze_choices(self) -> List[tuple]:
        """NY v7-fix41: snooze-alternativ [(etikett, ISO-tid), ...]."""
        now = datetime.now()
        tonight = now.replace(hour=18, minute=0, second=0, microsecond=0)
        if tonight <= now:
            tonight = tonight + timedelta(days=1)
        tomorrow = (now + timedelta(days=1)).replace(
            hour=9, minute=0, second=0, microsecond=0
        )
        week = now + timedelta(weeks=1)
        return [
            ("1 timme", (now + timedelta(hours=1)).isoformat(timespec="minutes")),
            ("Ikväll 18:00", tonight.isoformat(timespec="minutes")),
            ("Imorgon 09:00", tomorrow.isoformat(timespec="minutes")),
            ("Om 1 vecka", week.isoformat(timespec="minutes")),
        ]

    def _due_choices(self) -> List[tuple]:
        """NY v7-fix41: snabba förfallodatum [(etikett, ÅÅÅÅ-MM-DD), ...]."""
        today = datetime.now().date()
        return [
            ("I dag", today.isoformat()),
            ("Imorgon", (today + timedelta(days=1)).isoformat()),
            ("Om 3 dagar", (today + timedelta(days=3)).isoformat()),
            ("Om en vecka", (today + timedelta(days=7)).isoformat()),
        ]

    def _on_subtask_toggle(self, task_id: str, sub_id: str) -> None:
        """NY v7-fix41: kryssa delmoment (store → changed → refresh)."""
        try:
            if hasattr(self.store, "toggle_subtask"):
                self.store.toggle_subtask(task_id, sub_id)
                logger.debug(
                    f"{LOG_PREFIX} delmoment växlat: {sub_id!r}"
                )
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} _on_subtask_toggle misslyckades: {e}"
            )

    def _on_task_context_menu(self, task_id: str) -> None:
        """
        NY v7-fix79: högerklick på en uppgift → åtgärdsmeny.

        Rickard 2026-10-07: "kunna ta bort felaktiga uppgifter /
        redigera via högerklicksmeny på dom". Öppnar SAMMA åtgärds-
        meny som ⋯-knappen men hämtar FÄRSK uppgift från store
        (menyns val beror på t.ex. snooze-/pinnad-status).
        Högerklick på tom yta/header ger fortfarande fönster-menyn
        (centrera/nollställ/lås, v7-fix47) — oförändrat.
        """
        try:
            get_throttle().notify_activity()
            task = None
            with suppress(Exception):
                if hasattr(self.store, "find_task"):
                    task = self.store.find_task(task_id)
            if not task:
                logger.debug(
                    f"{LOG_PREFIX} högerklick: uppgift {task_id!r} "
                    f"hittades ej (borttagen?) — visar ingen meny"
                )
                return
            logger.info(
                f"{LOG_PREFIX} högerklick på uppgift {task_id!r} → "
                f"åtgärdsmeny (v7-fix79)"
            )
            self._show_task_menu(task)
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} _on_task_context_menu misslyckades: "
                f"{_describe_widget_error(e)}",
                exc_info=True,
            )

    def _show_task_menu(self, task: Dict[str, Any]) -> None:
        """
            NY v7-fix41: åtgärdsmeny per uppgift (⋯-knappen).
            NY v7-fix79: öppnas även via HÖGERKLICK på uppgiften.

            Klar · Prioritet · Fäst · Redigera titel · Ta bort ·
            Senarelägg · Förfallodatum · Återkommande · Delmoment.
            Allt motorn (store) redan stödjer — UI:et saknade vägarna
            in (gap-analys 22.12.1).
        """
        try:
            get_throttle().notify_activity()
            from PySide6.QtGui import QCursor
            tid = task.get("id")
            if not tid:
                return
            menu = QMenu(self)
            menu.setObjectName("taskActionMenu")

            # --- NY v7-fix79: snabbåtgärder först (högerklick) -------
            # Rickard: "ta bort felaktiga uppgifter / redigera via
            # högerklicksmeny" — de vanligaste åtgärderna överst.
            act = menu.addAction(
                "⬜ Markera oklar" if task.get("done")
                else "✅ Markera klar"
            )
            act.triggered.connect(
                lambda _c: self._store_call(
                    "toggle_task", tid, _what="klarstatus"
                )
            )
            prio_menu = menu.addMenu("🚩 Prioritet")
            for p in PRIORITY_CYCLE:
                label = {
                    "none":   "Ingen (grå)",
                    "high":   "Hög (röd)",
                    "medium": "Normal (gul)",
                    "low":    "Låg (grön)",
                }.get(p, p)
                pact = prio_menu.addAction(label)
                pact.setCheckable(True)
                pact.setChecked(task.get("priority", "none") == p)
                pact.triggered.connect(
                    lambda _c, _p=p: self._set_task_priority(tid, _p)
                )
            act = menu.addAction(
                "📍 Lossa från toppen" if task.get("pinned")
                else "📌 Fäst överst"
            )
            act.triggered.connect(
                lambda _c: self._store_call(
                    "toggle_pinned", tid, _what="fäst"
                )
            )
            if _task_has_email(task):
                menu.addSeparator()
                act = menu.addAction("📧 Öppna mejlet")
                act.triggered.connect(
                    lambda _c, tk=dict(task): self._open_task_email(tk)
                )
                act = menu.addAction("↩️ Svara på mejlet")
                act.triggered.connect(
                    lambda _c, tk=dict(task): self._reply_to_task_email(tk)
                )
            menu.addSeparator()
            act = menu.addAction("✏️ Redigera titel…")
            act.triggered.connect(lambda _c: self._prompt_rename(tid))
            act = menu.addAction("🗑 Ta bort…")
            act.triggered.connect(lambda _c: self._prompt_delete(tid))
            # --- NY v8: kalender (Google Calendar m.fl.) -------------
            menu.addSeparator()
            act = menu.addAction("📅 Lägg till i Google Calendar")
            act.setToolTip(
                "Öppnar Google Calendar med uppgiften förifylld\n"
                "(heldagshändelse — från startdatum till förfallodatum\n"
                "om båda finns, annars på det datum som finns)"
            )
            act.triggered.connect(
                lambda _c, _t=dict(task): self._on_open_task_in_google_calendar(_t)
            )
            act = menu.addAction("📅 Exportera uppgiften (.ics)…")
            act.setToolTip(
                "Sparar uppgiften som kalenderfil — importeras i\n"
                "Google Calendar, Outlook och Apple Kalender"
            )
            act.triggered.connect(
                lambda _c, _t=dict(task): self._on_export_task_ics(_t)
            )
            act = menu.addAction("☁️ Skicka till Google Calendar")
            act.setToolTip(
                "Skickar uppgiften direkt till din Google-kalender\n"
                "(kräver att kontot är kopplat — se ☁️ Google Calendar)"
            )
            act.triggered.connect(
                lambda _c, _t=dict(task): self._on_push_task_to_google(_t)
            )
            act = menu.addAction("🕘 Kalenderhistorik för uppgiften")
            act.setToolTip(
                "Visar när uppgiften skickats till Google Calendar och\n"
                "med vilket resultat — med knapp för att öppna händelsen"
            )
            act.triggered.connect(
                lambda _c, _t=dict(task): self._on_show_task_calendar_history(_t)
            )
            menu.addSeparator()

            # --- ⏰ Senarelägg ------------------------------------
            snooze_menu = menu.addMenu("⏰ Senarelägg")
            for label, iso in self._snooze_choices():
                act = snooze_menu.addAction(label)
                act.triggered.connect(
                    lambda _c, i=iso: self._store_call(
                        "snooze_task", tid, i, _what="senarelagd"
                    )
                )
            if task.get("snoozed_until"):
                act = snooze_menu.addAction("💤 Visa nu (avbryt snooze)")
                act.triggered.connect(
                    lambda _c: self._store_call(
                        "unsnooze_task", tid, _what="snooze avbruten"
                    )
                )

            # --- 📅 Förfallodatum ---------------------------------
            due_menu = menu.addMenu("📅 Förfallodatum")
            for label, iso in self._due_choices():
                act = due_menu.addAction(label)
                act.triggered.connect(
                    lambda _c, i=iso: self._store_call(
                        "set_due_date", tid, i, _what="förfallodatum"
                    )
                )
            act = due_menu.addAction("✍️ Skriv datum (ÅÅÅÅ-MM-DD)…")
            act.triggered.connect(
                lambda _c: self._prompt_and_set_due(tid)
            )
            if task.get("due_date"):
                act = due_menu.addAction("✖ Ta bort datum")
                act.triggered.connect(
                    lambda _c: self._store_call(
                        "set_due_date", tid, None, _what="datum borttaget"
                    )
                )

            # --- ▶ Startdatum (NY v8: för kalenderhändelser) ---------
            start_menu = menu.addMenu("▶ Startdatum")
            start_menu.setToolTip(
                "Valfritt. Med både start- och förfallodatum blir uppgiften en\n"
                "flerdagarshändelse i kalendern (start → förfallodatum)."
            )
            act = start_menu.addAction("📆 Välj i kalender…")
            act.triggered.connect(
                lambda _c: self._prompt_and_set_start(tid)
            )
            start_menu.addSeparator()
            for label, iso in self._due_choices():
                act = start_menu.addAction(label)
                act.triggered.connect(
                    lambda _c, i=iso: self._store_call(
                        "set_start_date", tid, i, _what="startdatum"
                    )
                )
            if task.get("start_date"):
                act = start_menu.addAction("✖ Ta bort startdatum")
                act.triggered.connect(
                    lambda _c: self._store_call(
                        "set_start_date", tid, None, _what="startdatum borttaget"
                    )
                )

            # --- 🔁 Återkommande -----------------------------------
            rec_menu = menu.addMenu("🔁 Återkommande")
            _cur_iv = (task.get("recurring") or {}).get("interval")
            for iv, iv_label in (
                ("daily", "Varje dag"),
                ("weekly", "Varje vecka"),
                ("monthly", "Varje månad"),
            ):
                act = rec_menu.addAction(iv_label)
                act.setCheckable(True)
                act.setChecked(_cur_iv == iv)
                act.triggered.connect(
                    lambda _c, i=iv: self._store_call(
                        "set_recurring", tid, i, _what="återkommande"
                    )
                )
            if _cur_iv:
                act = rec_menu.addAction("✖ Av (engångsuppgift)")
                act.triggered.connect(
                    lambda _c: self._store_call(
                        "set_recurring", tid, None, _what="återkommande av"
                    )
                )

            # --- ➕ Delmoment ---------------------------------------
            act = menu.addAction("➕ Lägg till delmoment…")
            act.triggered.connect(lambda _c: self._prompt_subtasks(tid))

            # FIX v7-fix79: Byt namn/Ta bort finns nu i menyns Topp
            # (snabbåtgärder) — här behövs ingen dubblett.

            menu.exec(QCursor.pos())
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} _show_task_menu misslyckades: "
                f"{_describe_widget_error(e)}",
                exc_info=True,
            )

    def _store_call(
        self, method: str, task_id: str, *args, _what: str = ""
    ) -> None:
        """NY v7-fix41: säkert anropa store-metod med logg."""
        try:
            fn = getattr(self.store, method, None)
            if fn is None:
                logger.warning(
                    f"{LOG_PREFIX} store saknar {method}()"
                )
                return
            fn(task_id, *args)
            logger.info(
                f"{LOG_PREFIX} {method}: {task_id!r} "
                f"({_what or (args[0] if args else 'ok')})"
            )
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} _store_call({method}) misslyckades: {e}"
            )

    def _prompt_and_set_due(self, task_id: str) -> None:
        """NY v7-fix41: skriv in förfallodatum manuellt."""
        try:
            from PySide6.QtWidgets import QInputDialog
            text, ok = QInputDialog.getText(
                self,
                "📅 Förfallodatum",
                "Datum (ÅÅÅÅ-MM-DD):",
                text=datetime.now().date().isoformat(),
            )
            if not ok or not text.strip():
                return
            try:
                iso = datetime.fromisoformat(text.strip()).date().isoformat()
            except ValueError:
                _show_widget_error(
                    "Ogiltigt datum",
                    f"{text.strip()!r} förstods inte — använd ÅÅÅÅ-MM-DD.",
                )
                return
            self._store_call("set_due_date", task_id, iso, _what="datum")
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} _prompt_and_set_due: {e}")

    def _pick_date(self, title: str, initial_iso: str = "") -> Optional[str]:
        """NY v8: kalender-väljare (veckonummer, måndag först). Returnerar ISO-datum eller None."""
        from PySide6.QtCore import QDate
        from PySide6.QtWidgets import (
            QCalendarWidget, QDialog, QHBoxLayout as _QH, QPushButton as _QB,
            QVBoxLayout as _QV, QLabel as _QL,
        )
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        lay = _QV(dlg)
        lay.addWidget(_QL("Välj dag i kalendern (dubbelklicka eller tryck Välj):", dlg))
        cal = QCalendarWidget(dlg)
        cal.setGridVisible(True)
        cal.setFirstDayOfWeek(Qt.DayOfWeek.Monday)
        cal.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.ISOWeekNumbers)
        qd = QDate.fromString(initial_iso[:10], "yyyy-MM-dd") if initial_iso else QDate()
        cal.setSelectedDate(qd if qd.isValid() else QDate.currentDate())
        lay.addWidget(cal)
        quick = _QH()
        today = QDate.currentDate()
        for label, d in (
            ("Idag", today),
            ("Imorgon", today.addDays(1)),
            ("Nästa måndag", today.addDays(8 - today.dayOfWeek())),
        ):
            b = _QB(label, dlg)
            b.clicked.connect(lambda _c=False, _d=d: cal.setSelectedDate(_d))
            quick.addWidget(b)
        quick.addStretch(1)
        lay.addLayout(quick)
        btns = _QH()
        btns.addStretch(1)
        cancel = _QB("Avbryt", dlg)
        cancel.clicked.connect(dlg.reject)
        ok = _QB("Välj", dlg)
        ok.setDefault(True)
        ok.clicked.connect(dlg.accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)
        cal.activated.connect(lambda _d: dlg.accept())
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        return cal.selectedDate().toString("yyyy-MM-dd")

    def _prompt_and_set_start(self, task_id: str) -> None:
        """NY v8: välj startdatum i en kalender (valfritt, för kalendern)."""
        try:
            from PySide6.QtWidgets import QMessageBox
            current = ""
            with suppress(Exception):
                t = self.store.find_task(task_id) or {}
                current = str(t.get("start_date") or "")[:10]
            iso = self._pick_date("▶ Startdatum", current)
            if not iso:
                return
            self._store_call("set_start_date", task_id, iso, _what="startdatum")
            with suppress(Exception):
                t = self.store.find_task(task_id) or {}
                due = str(t.get("due_date") or "")[:10]
                if due and iso > due:
                    QMessageBox.information(
                        self,
                        "▶ Startdatum",
                        "Startdatumet ligger efter förfallodatumet.\n"
                        "I kalendern används då bara förfallodatumet.",
                    )
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} _prompt_and_set_start: {e}")

    def _add_subtask_rows(
        self,
        container: QWidget,
        parent_layout: QVBoxLayout,
        tid: str,
        subs: List[Dict[str, Any]],
        depth: int = 1,
    ) -> None:
        """NY v8: rita delmoment rekursivt med indrag per nivå."""
        for sub in subs:
            sub_id = sub.get("id")
            sub_row = QHBoxLayout()
            sub_row.setSpacing(6)
            # Indrag: 16px per nivå (nivå 1 = inget extra indrag)
            sub_row.setContentsMargins((depth - 1) * 16, 0, 0, 0)
            sub_cb = QCheckBox(container)
            sub_cb.setObjectName("subtaskCheck")
            sub_cb.setChecked(bool(sub.get("done")))
            sub_cb.setToolTip("Kryssa delmoment")
            sub_cb.toggled.connect(
                lambda c, _t=tid, _s=sub_id: self._on_subtask_toggle(_t, _s)
            )
            sub_row.addWidget(sub_cb, 0, Qt.AlignmentFlag.AlignVCenter)
            sub_lbl = QLabel(str(sub.get("title", "")), container)
            sub_lbl.setObjectName("subtaskTitle")
            sub_lbl.setWordWrap(True)
            # NY v8: högerklick på delmomentet → byt namn / underdelmoment / ta bort
            sub_lbl.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            sub_lbl.customContextMenuRequested.connect(
                lambda _pos, _t=tid, _s=sub_id, _n=str(sub.get("title", "")):
                    self._on_subtask_context_menu(_t, _s, _n)
            )
            if sub.get("done"):
                _sf = sub_lbl.font()
                _sf.setStrikeOut(True)
                sub_lbl.setFont(_sf)
            sub_row.addWidget(sub_lbl, 1, Qt.AlignmentFlag.AlignVCenter)
            parent_layout.addLayout(sub_row)
            kids = [dict(c) for c in (sub.get("children") or []) if c.get("title")]
            if kids:
                self._add_subtask_rows(
                    container, parent_layout, tid, kids, depth + 1
                )

    def _on_subtask_context_menu(
        self, task_id: str, sub_id: str, title: str
    ) -> None:
        """NY v8: åtgärdsmeny för ett delmoment."""
        try:
            menu = QMenu(self)
            act_rn = menu.addAction("✏ Byt namn…")
            act_rn.triggered.connect(
                lambda _c: self._prompt_rename_subtask(task_id, sub_id, title)
            )
            act_sub = menu.addAction("➕ Lägg till underdelmoment…")
            act_sub.triggered.connect(
                lambda _c: self._prompt_subtasks(task_id, parent_sub_id=sub_id)
            )
            menu.addSeparator()
            act_rm = menu.addAction("🗑 Ta bort delmoment")
            act_rm.triggered.connect(
                lambda _c: self._store_call(
                    "remove_subtask", task_id, sub_id,
                    _what="delmoment borttaget",
                )
            )
            menu.exec(QCursor.pos())
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} _on_subtask_context_menu: {e}")

    def _prompt_rename_subtask(
        self, task_id: str, sub_id: str, current: str
    ) -> None:
        """NY v8: byt namn på ett delmoment."""
        try:
            from PySide6.QtWidgets import QInputDialog
            text, ok = QInputDialog.getText(
                self, "✏ Byt namn på delmoment", "Nytt namn:", text=current
            )
            if ok and text.strip():
                self.store.rename_subtask(task_id, sub_id, text.strip())
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} _prompt_rename_subtask: {e}")

    def _prompt_subtasks(
        self, task_id: str, parent_sub_id: Optional[str] = None
    ) -> None:
        """NY v7-fix41 + v8: lägg till delmoment (eller underdelmoment)."""
        try:
            from PySide6.QtWidgets import QInputDialog
            _label = "➕ Underdelmoment" if parent_sub_id else "➕ Delmoment"
            while True:
                text, ok = QInputDialog.getText(
                    self, _label, "Nytt delmoment (tomt = klar):"
                )
                if not ok or not text.strip():
                    return
                sub = None
                if hasattr(self.store, "add_subtask"):
                    sub = self.store.add_subtask(
                        task_id, text.strip(), parent_sub_id=parent_sub_id
                    )
                if sub is None:
                    return
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} _prompt_subtasks: {e}")

    def _prompt_rename(self, task_id: str) -> None:
        """NY v7-fix41: byt namn på uppgift."""
        try:
            from PySide6.QtWidgets import QInputDialog
            task = None
            if hasattr(self.store, "find_task"):
                task = self.store.find_task(task_id)
            old = (task or {}).get("title", "")
            text, ok = QInputDialog.getText(
                self, "✏️ Byt namn", "Ny titel:", text=old
            )
            if not ok or not text.strip():
                return
            self._store_call(
                "update_task_title", task_id, text.strip(), _what="namn"
            )
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} _prompt_rename: {e}")

    def _prompt_delete(self, task_id: str) -> None:
        """NY v7-fix41: ta bort uppgift med bekräftelse."""
        try:
            from PySide6.QtWidgets import QMessageBox
            task = None
            if hasattr(self.store, "find_task"):
                task = self.store.find_task(task_id)
            title = (task or {}).get("title", "uppgiften")
            if task and isinstance(task.get("recurring"), dict):
                title += "\n(⚠ återkommande serie avslutas)"
            btn = QMessageBox.question(
                self,
                "🗑 Ta bort uppgift",
                f"Ta bort '{title}'?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if btn != QMessageBox.StandardButton.Yes:
                return
            self._store_call("remove_task", task_id, _what="borttagen")
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} _prompt_delete: {e}")
