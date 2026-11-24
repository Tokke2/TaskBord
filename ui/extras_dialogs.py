# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""
extras_dialogs.py — dialoger för anteckningar (📝) och beloppsöversikten (💰).

* ``NoteDialog``            — flera rader text; Ctrl+Retur sparar. ``text()`` ger texten.
* ``AmountOverviewDialog``  — summor per månad och tagg (aktiva) + klart per månad (arkivet); text som kan kopieras.
Själva uträkningen finns i core/amounts.py (testas utan Qt).
"""
from __future__ import annotations

from typing import Optional

try:
    from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
    from PySide6.QtWidgets import (
        QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
    )
    _QT = True
except ImportError:  # pragma: no cover
    _QT = False
    QWidget = object  # type: ignore[misc,assignment]

NOTE_MAX = 50_000

if _QT:

    class NoteDialog(QDialog):
        def __init__(self, parent: Optional[QWidget] = None, title: str = "", text: str = "") -> None:
            super().__init__(parent)
            self.setWindowTitle("📝 Anteckning")
            self.setModal(True)
            self.setMinimumSize(460, 320)
            lay = QVBoxLayout(self)
            lay.setContentsMargins(14, 12, 14, 10)
            head = QLabel(f"Anteckning till: {title}" if title else "Anteckning", self)
            head.setWordWrap(True)
            lay.addWidget(head)
            self.edit = QPlainTextEdit(self)
            self.edit.setPlainText(text or "")
            self.edit.setPlaceholderText("Skriv flera rader — adress, telefonnummer, vad som ska göras …\n"
                                         "Telefonnummer och adresser blir klickbara på kortet.")
            lay.addWidget(self.edit, 1)
            self.counter = QLabel("", self)
            lay.addWidget(self.counter)
            row = QHBoxLayout()
            row.addStretch(1)
            cancel = QPushButton("Avbryt", self)
            cancel.clicked.connect(self.reject)
            ok = QPushButton("Spara (Ctrl+Retur)", self)
            ok.setDefault(True)
            ok.clicked.connect(self.accept)
            row.addWidget(cancel)
            row.addWidget(ok)
            lay.addLayout(row)
            for seq in ("Ctrl+Return", "Ctrl+Enter"):
                QShortcut(QKeySequence(seq), self, activated=self.accept)
            self.edit.textChanged.connect(self._count)
            self._count()
            self.edit.setFocus()

        def _count(self) -> None:
            n = len(self.edit.toPlainText())
            self.counter.setText(f"{n:,} / {NOTE_MAX:,} tecken".replace(",", "\u00a0") + ("  ⚠ för långt — kortas vid sparning" if n > NOTE_MAX else ""))

        def text(self) -> str:
            return self.edit.toPlainText()[:NOTE_MAX]

    class AmountOverviewDialog(QDialog):
        def __init__(self, parent: Optional[QWidget] = None, text: str = "", scope: str = "") -> None:
            super().__init__(parent)
            self.setWindowTitle("💰 Belopp — översikt")
            self.setModal(True)
            self.setMinimumSize(460, 400)
            lay = QVBoxLayout(self)
            lay.setContentsMargins(14, 12, 14, 10)
            if scope:
                lay.addWidget(QLabel(scope, self))
            self.view = QPlainTextEdit(self)
            self.view.setReadOnly(True)
            f = self.view.font()
            f.setFamily("Consolas")
            f.setStyleHint(f.StyleHint.Monospace)
            self.view.setFont(f)
            self.view.setPlainText(text)
            lay.addWidget(self.view, 1)
            row = QHBoxLayout()
            copy = QPushButton("📋 Kopiera", self)
            copy.clicked.connect(self._copy)
            close = QPushButton("Stäng", self)
            close.setDefault(True)
            close.clicked.connect(self.accept)
            row.addWidget(copy)
            row.addStretch(1)
            row.addWidget(close)
            lay.addLayout(row)

        def _copy(self) -> None:
            QGuiApplication.clipboard().setText(self.view.toPlainText())
