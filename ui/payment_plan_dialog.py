# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""
payment_plan_dialog.py — 💸 Delbetalningsplan: dela en faktura i flera betalningar som uppgifter.

Fyll i rubrik/kund, valfritt totalbelopp (och handpenning), antal delar, första förfallodag och
intervall. Förhandsvisningen uppdateras medan du skriver. "Skapa" lägger N uppgifter
"<rubrik> — del 1 av 3 (4 000 kr)" med förfallodatum och taggen "delbetalning".
Själva uträkningen finns i core/payment_plan.py (testas utan Qt).
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, List, Optional

from core import payment_plan as pp

logger = logging.getLogger("Ledgebord")
LOG_PREFIX = "[DELBETALNING]"

try:
    from PySide6.QtCore import QDate, Qt
    from PySide6.QtWidgets import (
        QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit,
        QListWidget, QMessageBox, QSpinBox, QVBoxLayout, QWidget,
    )
    _QT = True
except ImportError:  # pragma: no cover
    _QT = False
    QWidget = Any  # type: ignore[misc,assignment]

_WEEKDAYS = ("mån", "tis", "ons", "tors", "fre", "lör", "sön")
_PRIOS = [("Ingen prioritet", "none"), ("Hög", "high"), ("Normal", "medium"), ("Låg", "low")]


def _label(d: date) -> str:
    return f"{_WEEKDAYS[d.weekday()]} {d.day}/{d.month} {d.year}"


if _QT:

    class PaymentPlanDialog(QDialog):
        def __init__(self, parent: Optional[QWidget] = None, store: Any = None, title: str = "") -> None:
            super().__init__(parent)
            self.store = store
            self.created: List[str] = []
            self.setWindowTitle("💸 Delbetalningsplan")
            self.setModal(True)
            self.setMinimumSize(520, 560)
            rot = QVBoxLayout(self)
            rot.setContentsMargins(16, 14, 16, 12)
            rot.setSpacing(8)
            intro = QLabel(
                "Dela en faktura i flera betalningar. Varje del blir en egen uppgift med "
                "förfallodatum (och syns i kalendern).", self)
            intro.setWordWrap(True)
            rot.addWidget(intro)

            form = QFormLayout()
            form.setSpacing(6)
            self.f_title = QLineEdit(title, self)
            self.f_title.setPlaceholderText("t.ex. Anders Andersson – limousin")
            self.f_title.setAccessibleName("Rubrik eller kund")
            form.addRow("Rubrik / kund:", self.f_title)
            self.f_total = QLineEdit(self)
            self.f_total.setPlaceholderText("valfritt, t.ex. 12 000")
            self.f_total.setAccessibleName("Totalbelopp i kronor")
            form.addRow("Totalbelopp (kr):", self.f_total)
            self.f_down = QLineEdit(self)
            self.f_down.setPlaceholderText("valfritt — del 1, resten delas lika")
            self.f_down.setAccessibleName("Handpenning i kronor")
            form.addRow("Handpenning (kr):", self.f_down)
            self.f_parts = QSpinBox(self)
            self.f_parts.setRange(pp.MIN_PARTS, pp.MAX_PARTS)
            self.f_parts.setValue(3)
            form.addRow("Antal delar:", self.f_parts)
            self.f_first = QDateEdit(QDate.currentDate(), self)
            self.f_first.setCalendarPopup(True)
            self.f_first.setDisplayFormat("yyyy-MM-dd")
            form.addRow("Första förfallodag:", self.f_first)
            self.f_interval = QComboBox(self)
            for key in pp.INTERVAL_ORDER:
                self.f_interval.addItem(pp.INTERVALS[key][0], key)
            form.addRow("Intervall:", self.f_interval)
            self.f_shift = QComboBox(self)
            for key, text in pp.SHIFT_MODES.items():
                self.f_shift.addItem(text, key)
            form.addRow("Helg / röd dag:", self.f_shift)
            self.f_prio = QComboBox(self)
            for text, key in _PRIOS:
                self.f_prio.addItem(text, key)
            form.addRow("Prioritet:", self.f_prio)
            self.f_tags = QLineEdit(pp.DEFAULT_TAG, self)
            self.f_tags.setAccessibleName("Taggar")
            form.addRow("Taggar:", self.f_tags)
            rot.addLayout(form)

            self.warn = QLabel("", self)
            self.warn.setWordWrap(True)
            rot.addWidget(self.warn)
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

            for w in (self.f_title, self.f_total, self.f_down):
                w.textChanged.connect(self._refresh)
            self.f_parts.valueChanged.connect(self._refresh)
            self.f_first.dateChanged.connect(self._refresh)
            for c in (self.f_interval, self.f_shift):
                c.currentIndexChanged.connect(self._refresh)
            self._plan: List[dict] = []
            self._refresh()

        # ------------------------------------------------------------------
        def _inputs(self):
            total = pp.parse_amount(self.f_total.text()) if self.f_total.text().strip() else None
            down = pp.parse_amount(self.f_down.text()) if self.f_down.text().strip() else 0
            return total, down

        def plan(self) -> List[dict]:
            return list(self._plan)

        def _refresh(self, *_a: Any) -> None:
            msg = ""
            total, down = self._inputs()
            if self.f_total.text().strip() and total is None:
                msg = "Totalbeloppet kunde inte tolkas — skriv t.ex. 12 000 eller 12000,50."
            elif self.f_down.text().strip() and down is None:
                msg = "Handpenningen kunde inte tolkas."
            elif down and not total:
                msg = "Handpenning kräver ett totalbelopp."
            elif down and total and down >= total:
                msg = "Handpenningen måste vara mindre än totalbeloppet."
            qd = self.f_first.date()
            first = date(qd.year(), qd.month(), qd.day())
            plan: List[dict] = []
            if not msg:
                plan = pp.build_plan(
                    self.f_title.text(), first, self.f_parts.value(), self.f_interval.currentData(),
                    self.f_shift.currentData(), total, down or 0,
                )
            self._plan = plan
            self.warn.setText(f"<b>⚠ {msg}</b>" if msg else "")
            self.preview.clear()
            for it in plan:
                y, m, d = (int(x) for x in it["due_date"].split("-"))
                self.preview.addItem(f"{_label(date(y, m, d))}  —  {it['title']}")
            if not plan and not msg:
                self.preview.addItem("Skriv en rubrik så visas planen här.")
            self.ok_btn.setEnabled(bool(plan))
            self.ok_btn.setText(f"Skapa {len(plan)} uppgifter" if plan else "Skapa uppgifter")

        def _accept(self) -> None:
            if not self._plan or self.store is None:
                return
            prio = self.f_prio.currentData() or "none"
            tags = pp.parse_tags(self.f_tags.text())
            ids = pp.create_tasks(self.store, self._plan, prio, tags)
            self.created = ids
            logger.info(f"{LOG_PREFIX} skapade {len(ids)} av {len(self._plan)} uppgifter")
            if len(ids) < len(self._plan):
                QMessageBox.warning(
                    self, "Delbetalningsplan",
                    f"Bara {len(ids)} av {len(self._plan)} uppgifter kunde skapas (listan är full).")
            self.accept()


def open_payment_plan_dialog(parent: Optional[Any] = None, store: Any = None, title: str = "") -> List[str]:
    """Öppna dialogen. Returnerar id:n för skapade uppgifter (tom lista om man avbröt)."""
    if not _QT or store is None:
        return []
    try:
        dlg = PaymentPlanDialog(parent, store, title)
        dlg.exec()
        return list(dlg.created)
    except Exception as e:  # dialogen får aldrig fälla appen
        logger.warning(f"{LOG_PREFIX} kunde inte öppna dialogen: {e}", exc_info=True)
        return []
