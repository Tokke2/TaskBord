# -*- coding: utf-8 -*-
"""
ui/widget_parts/task_card.py — Uppgiftskortet: bygger ett kort (_build_task_widget), rensar layouter och bygger sökindex.

Del av TodoWidget (delad ur ui/widget.py). Metoderna är oförändrade; klassen
blandas in i TodoWidget i ui/widget.py. Gemensamma konstanter, hjälpfunktioner
och Qt-importer kommer från ui/widget_base.py, små UI-klasser från ui/widget_atoms.py.
"""
from __future__ import annotations

from ui.widget_base import *  # noqa: F401,F403
from ui.widget_atoms import *  # noqa: F401,F403


class TaskCardMixin:
    """Uppgiftskortet: bygger ett kort (_build_task_widget), rensar layouter och bygger sökindex."""

    def _build_task_widget(
        self, task: Dict[str, Any], archived: bool
    ) -> Optional[QWidget]:
        """
        NY v7-fix10: Bygg enskild task-widget — modern frosted-glass-kort.

        ALL styling sker via QSS-properties (taskCard/taskPriority/pinned/
        taskDone) i _apply_theme — inga inline-setStyleSheet som överrider
        temat (gammal bugg: inline-stylen bröt QSS-hover/regler).

        Kortets layout:
          Rad 1: [✓ checkbox] [• prioritetsprick] Titel... [📌 pin]
          Rad 2: [chips: taggar] [datum]  (endast om något finns)
        """
        try:
            tid = task.get("id")
            if not tid:
                return None
            container = QFrame(self)
            container.setObjectName(f"task_{tid}")
            container.setProperty("taskCard", True)
            # NY: klick på kortet markerar det (mus + tangentbord fungerar ihop)
            container.installEventFilter(self)
            task_priority = task.get("priority", "none")
            if task_priority not in PRIORITY_CYCLE:
                task_priority = "none"  # Fallback
            due = task.get("due_date")  # NY v7-fix41: används i properties
            is_done = bool(task.get("done", False))
            is_pinned = bool(task.get("pinned"))
            # Dynamic properties → QSS-väljare (Etapp 10)
            container.setProperty("task_priority", task_priority)
            container.setProperty("taskPriority", task_priority)
            container.setProperty("task_id", tid)
            container.setProperty("taskDone", is_done)
            container.setProperty("pinned", is_pinned)
            # NY v7-fix79: högerklick på UPPGIFTEN → åtgärdsmeny
            # (redigera/ta bort/klar/prioritet/fäst + allt från ⋯).
            # Tidigare nådde högerklicket fönster-menyn (centrera/lås).
            container.setContextMenuPolicy(
                Qt.ContextMenuPolicy.CustomContextMenu
            )
            container.customContextMenuRequested.connect(
                lambda _pos, _tid=tid: self._on_task_context_menu(_tid)
            )
            # NY v7-fix41: deadline-ring (QSS: overdue=töd, today=orange)
            due_state = "none"
            if due:
                try:
                    _dd = datetime.fromisoformat(str(due)).date()
                    _delta = (_dd - datetime.now().date()).days
                    if _delta < 0:
                        due_state = "overdue"
                    elif _delta == 0:
                        due_state = "today"
                except (ValueError, TypeError):
                    due_state = "none"
            container.setProperty("taskDue", due_state)

            _dp = _density_profile(self.settings)
            vbox = QVBoxLayout(container)
            vbox.setContentsMargins(10, int(_dp["pad_v"]), 10, int(_dp["pad_v"]))
            vbox.setSpacing(int(_dp["gap"]))

            # --- Rad 1: checkbox + prioritetsprick + titel + pin ---------
            row1 = QHBoxLayout()
            row1.setSpacing(8)
            checkbox = QCheckBox(container)
            checkbox.setChecked(is_done)
            # FIX v7-fix80: tydlig KLAR-KNAPP — större (26px), pekhand,
            # tooltip. Rickard: "knapp vid uppgift för att toggla klar".
            checkbox.setFixedSize(26, 26)
            checkbox.setToolTip("✓ Klar / oklar — klicka här")
            checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
            checkbox.toggled.connect(
                lambda checked, t=tid: self._on_task_toggle(t, checked)
            )
            row1.addWidget(checkbox, 0, Qt.AlignmentFlag.AlignVCenter)

            # Klickbar prioritetsprick (klick = cykla, högerklick = meny)
            dot = PriorityDot(
                task_id=tid, priority=task_priority, parent=container
            )
            dot.priority_dot_clicked.connect(self._on_priority_dot_clicked)
            dot.priority_dot_right_clicked.connect(
                self._on_priority_dot_right_clicked
            )
            row1.addWidget(dot, 0, Qt.AlignmentFlag.AlignVCenter)

            title_label = QLabel(task.get("title", ""), container)
            title_label.setObjectName("taskTitle")
            title_label.setWordWrap(True)
            title_label.setToolTip(task.get("title", "") + "\n(dubbelklicka eller tryck F2 för att ändra)")
            title_label.setProperty("task_id", tid)
            title_label.installEventFilter(self)  # dubbelklick → redigera titeln på plats
            if is_done:
                # Genomstruken klar-titel (QSS saknar text-decoration)
                _f = title_label.font()
                _f.setStrikeOut(True)
                title_label.setFont(_f)
            row1.addWidget(title_label, 1, Qt.AlignmentFlag.AlignVCenter)

            if is_pinned:
                pin = QLabel("📌", container)
                pin.setObjectName("pinBadge")
                pin.setToolTip("Fäst uppgift")
                row1.addWidget(pin, 0, Qt.AlignmentFlag.AlignVCenter)

            # NY v7-fix41: 🔁-ikon för återkommande uppgifter
            _rec = task.get("recurring")
            if isinstance(_rec, dict) and _rec.get("interval"):
                _iv = {
                    "daily": "varje dag",
                    "weekly": "varje vecka",
                    "monthly": "varje månad",
                }.get(str(_rec.get("interval")), "?")
                rec_badge = QLabel("🔁", container)
                rec_badge.setObjectName("recBadge")
                rec_badge.setToolTip(f"Återkommande: {_iv}")
                row1.addWidget(
                    rec_badge, 0, Qt.AlignmentFlag.AlignVCenter
                )

            # NY v7-fix41: ⋯-knapp → åtgärdsmeny (snooze/datum/
            # återkommande/delmoment/namn/ta bort)
            menu_btn = QPushButton("⋯", container)
            menu_btn.setObjectName("taskMenuBtn")
            menu_btn.setFixedSize(24, 24)
            # NY v7-fix86: pekhand = tydligt klickbar
            menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            menu_btn.setToolTip(
                "Åtgärder (eller HÖGERKLICKA på uppgiften):\n"
                "Klar · Prioritet · Fäst · Redigera · Ta bort ·\n"
                "Senarelägg · Förfallodatum · Startdatum · Återkommande · Delmoment"
            )
            menu_btn.clicked.connect(
                lambda _c, tk=dict(task): self._show_task_menu(tk)
            )
            row1.addWidget(
                menu_btn, 0, Qt.AlignmentFlag.AlignVCenter
            )

            # 📧 "Öppna mejlet" — på ALLA uppgifter som kommer från ett
            # mail (sparad fil ELLER sparad mailtext), inte bara de med
            # en fungerande filsökväg
            if _task_has_email(task):
                mail_btn = QPushButton("📧", container)
                mail_btn.setObjectName("emailBadge")
                mail_btn.setFixedSize(24, 24)
                mail_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                mail_btn.setToolTip(
                    "Öppna mejlet\n"
                    f"{task.get('email_from') or 'Okänd avsändare'}"
                )
                mail_btn.clicked.connect(
                    lambda _c, tk=dict(task): self._open_task_email(tk)
                )
                row1.addWidget(
                    mail_btn, 0, Qt.AlignmentFlag.AlignVCenter
                )
                reply_btn = QPushButton("↩", container)
                reply_btn.setObjectName("emailBadge")
                reply_btn.setFixedSize(24, 24)
                reply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                reply_btn.setToolTip(
                    "Svara på mejlet\n"
                    f"{task.get('email_from') or 'Okänd avsändare'}"
                )
                reply_btn.clicked.connect(
                    lambda _c, tk=dict(task): self._reply_to_task_email(tk)
                )
                row1.addWidget(
                    reply_btn, 0, Qt.AlignmentFlag.AlignVCenter
                )
            vbox.addLayout(row1)

            # --- Rad 2: tagg-chips + datum (endast om något finns) -------
            tags = [
                str(tg) for tg in (task.get("tags") or [])
                if str(tg).strip()
            ][:6]
            _start = task.get("start_date")
            if tags or due or _start or _is_snoozed(task):
                meta = QHBoxLayout()
                meta.setSpacing(6)
                meta.addSpacing(34)  # indrag i linje med titeln
                for i, tag in enumerate(tags):
                    chip = TagChip(tag, color_index=i, parent=container)
                    chip.clicked.connect(self._on_tag_clicked)
                    meta.addWidget(chip)
                if _is_snoozed(task):
                    sn_lbl = QLabel(
                        f"💤 till {_snooze_until_label(task.get('snoozed_until'))}",
                        container,
                    )
                    sn_lbl.setObjectName("snoozeBadge")
                    sn_lbl.setToolTip("Senarelagd — kommer tillbaka automatiskt")
                    meta.addWidget(sn_lbl)
                if _start:
                    st_lbl = QLabel(f"▶ start {_due_label_short(_start)}", container)
                    st_lbl.setObjectName("snoozeBadge")
                    st_lbl.setToolTip(
                        f"Startdatum: {str(_start)[:10]}\n"
                        "Används när uppgiften skickas till kalendern."
                    )
                    meta.addWidget(st_lbl)
                if due:
                    meta.addWidget(DueDateLabel(str(due), container))
                meta.addStretch(1)
                vbox.addLayout(meta)

            # Datumraden visas alltid: skapad-datum för aktiva och
            # avslutsdatum för arkiverade uppgifter.
            _timestamp_value = (
                task.get("completed") if archived else task.get("created")
            )
            try:
                if _timestamp_value:
                    _timestamp_dt = datetime.fromisoformat(
                        str(_timestamp_value).replace("Z", "+00:00")
                    )
                    if _timestamp_dt.tzinfo is not None:
                        _timestamp_dt = _timestamp_dt.astimezone()
                    _timestamp_text = _timestamp_dt.strftime("%Y-%m-%d")
                else:
                    _timestamp_text = "datum saknas"
            except (ValueError, TypeError, OverflowError):
                _timestamp_text = (
                    str(_timestamp_value)[:10]
                    if _timestamp_value else "datum saknas"
                )
            _date_caption = "✓ Klar" if archived else "➕ Tillagd"
            date_row = QHBoxLayout()
            date_row.setSpacing(6)
            date_row.addSpacing(34)
            date_lbl = QLabel(
                f"{_date_caption}: {_timestamp_text}", container
            )
            date_lbl.setObjectName("taskDate")
            date_lbl.setToolTip(
                ("Datum då uppgiften markerades som klar."
                 if archived else "Datum då uppgiften lades till.")
                + (f"\n{_timestamp_value}" if _timestamp_value else "")
            )
            date_row.addWidget(date_lbl)
            date_row.addStretch(1)
            if archived or _dp["show_added"]:
                vbox.addLayout(date_row)
            else:
                # kompakt: döljer "Tillagd"-raden (etiketten är barn till kortet)
                date_lbl.setParent(None)
                date_lbl.deleteLater()
                date_row.deleteLater()

            # --- NY v7-fix41 + v8: delmoment (checklista, nästlad) ----
            subs = [
                dict(s) for s in (task.get("subtasks") or [])
                if s.get("title")
            ]
            if subs:
                sub_vbox = QVBoxLayout()
                sub_vbox.setContentsMargins(34, 2, 4, 2)
                sub_vbox.setSpacing(1)
                self._add_subtask_rows(container, sub_vbox, tid, subs, depth=1)
                _total_n, _done_n = _subtask_stats(subs)
                if _done_n >= _total_n:
                    prog = QLabel(f"☑ {_done_n}/{_total_n} klara", container)
                    prog.setObjectName("subtaskDoneAll")
                else:
                    prog = QLabel(f"☐ {_done_n}/{_total_n} klara", container)
                    prog.setObjectName("subtaskProgress")
                sub_vbox.addWidget(prog)
                vbox.addLayout(sub_vbox)
            return container
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} _build_task_widget misslyckades: "
                f"{_describe_widget_error(e)}",
                exc_info=True,
            )
            return None

    def _clear_layout(self, layout: Any) -> None:
        """NY v6.4.1 v7: Rensa layout (med felhantering)."""
        try:
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget() if item else None
                if widget is not None:
                    for tid, cached in list(self._task_widgets.items()):
                        if cached is widget:
                            del self._task_widgets[tid]
                            break
                    widget.setParent(None)
                    with suppress(Exception):
                        widget.deleteLater()
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} _clear_layout misslyckades: "
                f"{_describe_widget_error(e)}",
                exc_info=True,
            )

    @_log_call
    def _build_search_index(self) -> None:
        """
        NY v6.4.1 v7: Bygg inverterad sok-index (token → task_ids).

        Används av _do_search() for snabb matchning.
        """
        self._search_index.clear()
        try:
            if hasattr(self.store, "active_tasks"):
                tasks = self.store.active_tasks()
            else:
                tasks = []
            for task in tasks:
                tokens = self._tokenize_task(task)
                for token in tokens:
                    self._search_index.setdefault(token, set()).add(task["id"])
            logger.debug(
                f"{LOG_PREFIX} sok-index byggd: {len(self._search_index)} unika tokens, "
                f"{sum(len(s) for s in self._search_index.values())} referenser"
            )
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} _build_search_index misslyckades: "
                f"{_describe_widget_error(e)}",
                exc_info=True,
            )
