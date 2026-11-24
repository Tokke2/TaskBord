# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""
job_template_dialog.py — 📋 Jobbmallar: skapa alla uppgifter för ett jobb med ett klick (och, om du vill, skicka
dem automatiskt till Google Calendar). Själva logiken finns Qt-fri i core/job_templates.py.

* JobTemplateDialog   — välj mall, kund och jobbdag → förhandsvisning → Skapa.
* TemplateEditorDialog — skapa/ändra/duplicera/ta bort mallar och deras steg.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

from core import job_templates as jt
from core import payment_plan as pp

logger = logging.getLogger("Ledgebord")
LOG_PREFIX = "[MALLAR]"

try:
    from PySide6.QtCore import QDate, Qt
    from PySide6.QtWidgets import (
        QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
        QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSpinBox,
        QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
    )
    _QT = True
except ImportError:  # pragma: no cover
    _QT = False
    QWidget = Any  # type: ignore[misc,assignment]

_WEEKDAYS = ("mån", "tis", "ons", "tors", "fre", "lör", "sön")
_PRIOS = [("Ingen", "none"), ("Hög", "high"), ("Normal", "medium"), ("Låg", "low")]


def _label(d: date) -> str:
    return f"{_WEEKDAYS[d.weekday()]} {d.day}/{d.month} {d.year}"


if _QT:

    # ===================================================================================== använd mall
    class JobTemplateDialog(QDialog):
        def __init__(self, parent: Optional[QWidget] = None, store: Any = None, settings: Any = None) -> None:
            super().__init__(parent)
            self.store = store
            self.settings = settings
            self.data_dir = getattr(store, "_data_dir", None)
            self.created: List[str] = []
            self.sent = False
            self.templates: List[Dict[str, Any]] = jt.load_templates(self.data_dir) if self.data_dir else []
            self._items: List[Dict[str, Any]] = []
            self.setWindowTitle("📋 Ny uppgift från mall")
            self.setModal(True)
            self.setMinimumSize(520, 520)
            rot = QVBoxLayout(self)
            rot.setContentsMargins(16, 14, 16, 12)
            rot.setSpacing(8)
            intro = QLabel("Välj en mall, skriv kundens namn och jobbdagen — alla uppgifterna för jobbet skapas "
                           "med förfallodatum räknat från jobbdagen.", self)
            intro.setWordWrap(True)
            rot.addWidget(intro)

            form = QFormLayout()
            form.setSpacing(6)
            row = QHBoxLayout()
            self.f_template = QComboBox(self)
            self.f_template.setAccessibleName("Mall")
            row.addWidget(self.f_template, 1)
            self.edit_btn = QPushButton("✏ Hantera mallar…", self)
            self.edit_btn.clicked.connect(self._open_editor)
            row.addWidget(self.edit_btn)
            form.addRow("Mall:", row)
            self.f_customer = QLineEdit(self)
            self.f_customer.setPlaceholderText("t.ex. Anders Andersson")
            self.f_customer.setAccessibleName("Kund")
            form.addRow("Kund:", self.f_customer)
            self.f_date = QDateEdit(QDate.currentDate(), self)
            self.f_date.setCalendarPopup(True)
            self.f_date.setDisplayFormat("yyyy-MM-dd")
            self.f_date.setAccessibleName("Jobbdag")
            form.addRow("Jobbdag:", self.f_date)
            rot.addLayout(form)

            self.f_gcal = QCheckBox("Skicka uppgifterna automatiskt till Google Calendar", self)
            self.f_gcal.setAccessibleName("Skicka till Google Calendar")
            rot.addWidget(self.f_gcal)
            self.gcal_note = QLabel("", self)
            self.gcal_note.setWordWrap(True)
            rot.addWidget(self.gcal_note)

            rot.addWidget(QLabel("<b>Förhandsvisning</b>", self))
            self.preview = QListWidget(self)
            self.preview.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            rot.addWidget(self.preview, 1)

            self.buttons = QDialogButtonBox(self)
            self.ok_btn = self.buttons.addButton("Skapa uppgifter", QDialogButtonBox.ButtonRole.AcceptRole)
            cancel = self.buttons.addButton("Avbryt", QDialogButtonBox.ButtonRole.RejectRole)
            self.buttons.accepted.connect(self._accept)
            cancel.clicked.connect(self.reject)
            rot.addWidget(self.buttons)

            self._google_ok = bool(self.data_dir) and jt.google_ready(self.data_dir)
            self._fill_templates()
            self.f_template.currentIndexChanged.connect(self._template_changed)
            self.f_customer.textChanged.connect(self._refresh)
            self.f_date.dateChanged.connect(self._refresh)
            self._template_changed()

        # ------------------------------------------------------------------
        def current_template(self) -> Optional[Dict[str, Any]]:
            i = self.f_template.currentIndex()
            return self.templates[i] if 0 <= i < len(self.templates) else None

        def _fill_templates(self, select_id: str = "") -> None:
            self.f_template.blockSignals(True)
            self.f_template.clear()
            sel = 0
            for k, t in enumerate(self.templates):
                self.f_template.addItem(f"{t['name']}  ({len(t['steps'])} uppgifter)", t["id"])
                if t["id"] == select_id:
                    sel = k
            self.f_template.setCurrentIndex(sel if self.templates else -1)
            self.f_template.blockSignals(False)

        def _template_changed(self, *_a: Any) -> None:
            t = self.current_template()
            self.f_gcal.blockSignals(True)
            self.f_gcal.setChecked(bool(t and t.get("gcal") and self._google_ok))
            self.f_gcal.blockSignals(False)
            self.f_gcal.setEnabled(self._google_ok)
            self.gcal_note.setText(
                "" if self._google_ok else
                "Google Calendar är inte kopplat — koppla under ☁️ Google Calendar för att kunna skicka automatiskt.")
            self._refresh()

        def _refresh(self, *_a: Any) -> None:
            t = self.current_template()
            qd = self.f_date.date()
            day = date(qd.year(), qd.month(), qd.day())
            self._items = jt.build_tasks(t, day, self.f_customer.text()) if t else []
            self.preview.clear()
            for it in self._items:
                y, m, d = (int(x) for x in it["due_date"].split("-"))
                extra = f"  ({pp.format_amount(it['amount_cents'])})" if it.get("amount_cents") else ""
                self.preview.addItem(f"{_label(date(y, m, d))}  —  {it['title']}{extra}")
            if not self._items:
                self.preview.addItem("Mallen har inga steg ännu — lägg till under ✏ Hantera mallar." if t
                                     else "Det finns inga mallar — skapa en under ✏ Hantera mallar.")
            self.ok_btn.setEnabled(bool(self._items))
            self.ok_btn.setText(f"Skapa {len(self._items)} uppgifter" if self._items else "Skapa uppgifter")

        def _open_editor(self) -> None:
            if not self.data_dir:
                return
            keep = (self.current_template() or {}).get("id", "")
            dlg = TemplateEditorDialog(self, self.data_dir)
            dlg.exec()
            self.templates = jt.load_templates(self.data_dir)
            self._fill_templates(keep)
            self._template_changed()

        def _accept(self) -> None:
            t = self.current_template()
            if not self._items or self.store is None or t is None:
                return
            ids = jt.create_tasks(self.store, self._items)
            self.created = ids
            logger.info(f"{LOG_PREFIX} '{t['name']}': skapade {len(ids)} av {len(self._items)} uppgifter")
            if len(ids) < len(self._items):
                QMessageBox.warning(self, "Jobbmall",
                                    f"Bara {len(ids)} av {len(self._items)} uppgifter kunde skapas (listan är full).")
            if ids and self.f_gcal.isChecked() and self.f_gcal.isEnabled():
                try:
                    opts = {}
                    from core.gcal_autosync import options_from_settings
                    opts = options_from_settings(self.settings, self.data_dir)
                    cust = self.f_customer.text().strip()
                    label = f"{t['name']}{' — ' + cust if cust else ''}"
                    jt.export_async(self.data_dir, self.store.find_task, ids, opts, label)
                    self.sent = True
                except Exception as e:
                    logger.warning(f"{LOG_PREFIX} kunde inte starta Google-exporten: {e}")
            self.accept()

    # ================================================================================ hantera mallar
    class TemplateEditorDialog(QDialog):
        COLS = ("Uppgift", "Dagar från jobbdag", "Prioritet", "Taggar", "Belopp (kr)", "Bara vardag")

        def __init__(self, parent: Optional[QWidget] = None, data_dir: Any = None) -> None:
            super().__init__(parent)
            self.data_dir = data_dir
            self.templates: List[Dict[str, Any]] = jt.load_templates(data_dir)
            self._cur = -1
            self.setWindowTitle("✏ Hantera jobbmallar")
            self.setModal(True)
            self.setMinimumSize(900, 540)
            rot = QHBoxLayout(self)
            rot.setContentsMargins(14, 12, 14, 12)
            rot.setSpacing(10)

            left = QVBoxLayout()
            left.addWidget(QLabel("<b>Mallar</b>", self))
            self.list = QListWidget(self)
            self.list.setMaximumWidth(210)
            self.list.setAccessibleName("Mallar")
            left.addWidget(self.list, 1)
            for label, slot, attr in (("➕ Ny mall", self._new, "new_btn"), ("⧉ Duplicera", self._dup, "dup_btn"),
                                      ("🗑 Ta bort", self._delete, "del_btn")):
                b = QPushButton(label, self)
                b.clicked.connect(slot)
                setattr(self, attr, b)
                left.addWidget(b)
            rot.addLayout(left)

            right = QVBoxLayout()
            form = QFormLayout()
            self.f_name = QLineEdit(self)
            self.f_name.setAccessibleName("Mallens namn")
            self.f_name.setMaxLength(jt.MAX_NAME)
            form.addRow("Namn:", self.f_name)
            right.addLayout(form)
            self.f_gcal = QCheckBox("Skicka uppgifterna automatiskt till Google Calendar när mallen används", self)
            self.f_gcal.setToolTip("Förvalet i rutan när du skapar från mallen — du kan ändra det varje gång.\n"
                                   "Kräver att Google Calendar är kopplat.")
            right.addWidget(self.f_gcal)
            hint = QLabel("Skriv <b>{kund}</b> i en titel där kundens namn ska stå. Dagar: −3 = tre dagar före "
                          "jobbdagen, 0 = jobbdagen, 30 = en månad efter.", self)
            hint.setWordWrap(True)
            right.addWidget(hint)
            self.table = QTableWidget(0, len(self.COLS), self)
            self.table.setHorizontalHeaderLabels(list(self.COLS))
            self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            hh = self.table.horizontalHeader()
            hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            for c in range(1, len(self.COLS)):
                hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
            self.table.setAccessibleName("Stegen i mallen")
            right.addWidget(self.table, 1)
            row = QHBoxLayout()
            for label, slot, attr in (("➕ Lägg till steg", self._add_step, "add_step_btn"),
                                      ("🗑 Ta bort steg", self._del_step, "del_step_btn"),
                                      ("↑", lambda: self._move(-1), "up_btn"), ("↓", lambda: self._move(1), "down_btn")):
                b = QPushButton(label, self)
                b.clicked.connect(slot)
                setattr(self, attr, b)
                row.addWidget(b)
            row.addStretch(1)
            right.addLayout(row)
            self.buttons = QDialogButtonBox(self)
            self.save_btn = self.buttons.addButton("Spara", QDialogButtonBox.ButtonRole.AcceptRole)
            cancel = self.buttons.addButton("Avbryt", QDialogButtonBox.ButtonRole.RejectRole)
            self.buttons.accepted.connect(self._save)
            cancel.clicked.connect(self.reject)
            right.addWidget(self.buttons)
            rot.addLayout(right, 1)

            self._reload_list(0)
            self.list.currentRowChanged.connect(self._row_changed)

        # ------------------------------------------------------------------ steg-tabellen
        def _add_row(self, s: Optional[Dict[str, Any]] = None) -> None:
            s = s or {"title": "", "days": 0, "priority": "none", "tags": [], "amount_cents": 0, "workday": False}
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(str(s.get("title", ""))))
            sp = QSpinBox(self.table)
            sp.setRange(jt.MIN_DAYS, jt.MAX_DAYS)
            sp.setValue(int(s.get("days", 0)))
            sp.setSuffix(" d")
            sp.setAccessibleName("Dagar från jobbdagen")
            self.table.setCellWidget(r, 1, sp)
            cb = QComboBox(self.table)
            for text, key in _PRIOS:
                cb.addItem(text, key)
            cb.setCurrentIndex(max(0, cb.findData(s.get("priority", "none"))))
            self.table.setCellWidget(r, 2, cb)
            self.table.setItem(r, 3, QTableWidgetItem(", ".join(s.get("tags") or [])))
            amt = int(s.get("amount_cents") or 0)
            self.table.setItem(r, 4, QTableWidgetItem(pp.format_amount(amt).replace("\u00a0kr", "") if amt else ""))
            wd = QCheckBox(self.table)
            wd.setChecked(bool(s.get("workday")))
            wd.setToolTip("Hamnar dagen på helg eller röd dag flyttas den till nästa vardag.")
            wd.setAccessibleName("Bara vardag")
            self.table.setCellWidget(r, 5, wd)

        def _read_steps(self) -> List[Dict[str, Any]]:
            out: List[Dict[str, Any]] = []
            for r in range(self.table.rowCount()):
                def txt(c: int) -> str:
                    it = self.table.item(r, c)
                    return it.text() if it else ""
                amt = pp.parse_amount(txt(4)) if txt(4).strip() else 0
                st = jt.coerce_step({
                    "title": txt(0), "days": self.table.cellWidget(r, 1).value(),
                    "priority": self.table.cellWidget(r, 2).currentData(), "tags": txt(3),
                    "amount_cents": amt or 0, "workday": self.table.cellWidget(r, 5).isChecked()})
                if st:
                    out.append(st)
            return out

        def _add_step(self) -> None:
            self._add_row()
            self.table.setCurrentCell(self.table.rowCount() - 1, 0)
            self.table.editItem(self.table.item(self.table.rowCount() - 1, 0))

        def _del_step(self) -> None:
            r = self.table.currentRow()
            if r >= 0:
                self.table.removeRow(r)

        def _move(self, d: int) -> None:
            r = self.table.currentRow()
            steps = [self._row_dict(i) for i in range(self.table.rowCount())]
            n = r + d
            if r < 0 or not (0 <= n < len(steps)):
                return
            steps[r], steps[n] = steps[n], steps[r]
            self._fill_table(steps)
            self.table.setCurrentCell(n, 0)

        def _row_dict(self, r: int) -> Dict[str, Any]:
            """Raden som den står (även om titeln är tom — används vid flytt)."""
            def txt(c: int) -> str:
                it = self.table.item(r, c)
                return it.text() if it else ""
            amt = pp.parse_amount(txt(4)) if txt(4).strip() else 0
            return {"title": txt(0), "days": self.table.cellWidget(r, 1).value(),
                    "priority": self.table.cellWidget(r, 2).currentData(),
                    "tags": pp.parse_tags(txt(3)), "amount_cents": amt or 0,
                    "workday": self.table.cellWidget(r, 5).isChecked()}

        def _fill_table(self, steps: List[Dict[str, Any]]) -> None:
            self.table.setRowCount(0)
            for s in steps:
                self._add_row(s)

        # ------------------------------------------------------------------ mallar
        def _commit(self) -> None:
            """Skriv editorns innehåll till den valda mallen i minnet."""
            if not (0 <= self._cur < len(self.templates)):
                return
            t = self.templates[self._cur]
            name = self.f_name.text().strip() or t["name"]
            t["name"] = name[:jt.MAX_NAME]
            t["gcal"] = self.f_gcal.isChecked()
            t["steps"] = self._read_steps()

        def _reload_list(self, select: int) -> None:
            self.list.blockSignals(True)
            self.list.clear()
            for t in self.templates:
                self.list.addItem(QListWidgetItem(t["name"]))
            self.list.blockSignals(False)
            if self.templates:
                self.list.setCurrentRow(max(0, min(select, len(self.templates) - 1)))
                self._load(self.list.currentRow())
            else:
                self._cur = -1
                self.f_name.clear()
                self.f_gcal.setChecked(False)
                self.table.setRowCount(0)
            self._enable()

        def _enable(self) -> None:
            has = bool(self.templates)
            for w in (self.f_name, self.f_gcal, self.table, self.add_step_btn, self.del_step_btn, self.up_btn,
                      self.down_btn, self.dup_btn, self.del_btn):
                w.setEnabled(has)

        def _load(self, i: int) -> None:
            self._cur = i
            t = self.templates[i]
            self.f_name.setText(t["name"])
            self.f_gcal.setChecked(bool(t.get("gcal")))
            self._fill_table(t["steps"])

        def _row_changed(self, i: int) -> None:
            if i == self._cur or not (0 <= i < len(self.templates)):
                return
            self._commit()
            if 0 <= self._cur < len(self.templates):
                it = self.list.item(self._cur)
                if it:
                    it.setText(self.templates[self._cur]["name"])
            self._load(i)

        def _new(self) -> None:
            if len(self.templates) >= jt.MAX_TEMPLATES:
                return
            self._commit()
            self.templates.append({"id": jt.new_id(), "name": jt.unique_name(self.templates, "Ny mall"),
                                   "gcal": False, "steps": [
                                       {"title": "Utför jobbet — {kund}", "days": 0, "priority": "none", "tags": [],
                                        "amount_cents": 0, "workday": False}]})
            self._reload_list(len(self.templates) - 1)
            self.f_name.setFocus()
            self.f_name.selectAll()

        def _dup(self) -> None:
            if not (0 <= self._cur < len(self.templates)) or len(self.templates) >= jt.MAX_TEMPLATES:
                return
            self._commit()
            src = self.templates[self._cur]
            cp = {"id": jt.new_id(), "name": jt.duplicate_name(self.templates, src["name"]), "gcal": src["gcal"],
                  "steps": [dict(s, tags=list(s["tags"])) for s in src["steps"]]}
            self.templates.append(cp)
            self._reload_list(len(self.templates) - 1)

        def _delete(self) -> None:
            if not (0 <= self._cur < len(self.templates)):
                return
            name = self.templates[self._cur]["name"]
            if QMessageBox.question(self, "Ta bort mall", f"Ta bort mallen “{name}”?\n"
                                    "Uppgifter som redan skapats från den påverkas inte.") != QMessageBox.StandardButton.Yes:
                return
            del self.templates[self._cur]
            self._cur = -1
            self._reload_list(0)

        def _save(self) -> None:
            self._commit()
            if jt.save_templates(self.data_dir, self.templates):
                self.accept()
            else:
                QMessageBox.warning(self, "Jobbmallar", "Mallarna kunde inte sparas (skrivskyddad mapp?).")


def open_job_template_dialog(parent: Optional[Any] = None, store: Any = None, settings: Any = None) -> List[str]:
    """Öppna dialogen. Returnerar id:n för skapade uppgifter (tom lista om man avbröt)."""
    if not _QT or store is None or not getattr(store, "_data_dir", None):
        return []
    try:
        dlg = JobTemplateDialog(parent, store, settings)
        dlg.exec()
        return list(dlg.created)
    except Exception as e:  # dialogen får aldrig fälla appen
        logger.warning(f"{LOG_PREFIX} kunde inte öppna dialogen: {e}", exc_info=True)
        return []
