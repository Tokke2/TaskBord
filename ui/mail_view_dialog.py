# -*- coding: utf-8 -*-
"""
Visar mailet som sparats på en uppgift (avsändare, ämne, text).

Används när originalfilen (.eml) inte finns kvar eller inte går att öppna, så att
”Öppna mejlet” alltid ger något — aldrig en död knapp.
"""

from __future__ import annotations

from typing import Any, Dict

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QLabel, QPlainTextEdit,
    QPushButton, QVBoxLayout,
)


class MailViewDialog(QDialog):
    def __init__(self, task: Dict[str, Any], parent=None, note: str = "") -> None:
        super().__init__(parent)
        self.task = dict(task)
        subject = str(task.get("email_subject") or task.get("title") or "")
        self.setWindowTitle(f"📧 {subject}"[:90] or "📧 Mejl")
        self.resize(560, 460)
        lay = QVBoxLayout(self)
        if note:
            n = QLabel(note)
            n.setWordWrap(True)
            n.setStyleSheet("color: #b26a00;")
            lay.addWidget(n)
        form = QFormLayout()
        for label, key in (
            ("Från", "email_from"), ("Till", "email_to"),
            ("Datum", "email_date"), ("Ämne", "email_subject"),
            ("Bilagor", "email_attachments"),
        ):
            val = str(task.get(key) or "").strip()
            if val:
                lab = QLabel(val)
                lab.setWordWrap(True)
                lab.setTextInteractionFlags(
                    lab.textInteractionFlags()
                    | lab.textInteractionFlags().TextSelectableByMouse
                )
                form.addRow(f"{label}:", lab)
        lay.addLayout(form)
        self.body = QPlainTextEdit(self)
        self.body.setReadOnly(True)
        self.body.setPlainText(str(task.get("email_body") or "(ingen text sparad)"))
        lay.addWidget(self.body, 1)

        mid = str(task.get("email_message_id") or "").strip()
        self.btn_mid = QPushButton("Kopiera Message-ID")
        self.btn_mid.setToolTip(
            "Klistra in i Thunderbirds sökruta för att hitta mailet"
        )
        self.btn_mid.clicked.connect(lambda: self._copy(mid))
        self.btn_text = QPushButton("Kopiera texten")
        self.btn_text.clicked.connect(lambda: self._copy(self.body.toPlainText()))
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.button(QDialogButtonBox.StandardButton.Close).setText("Stäng")
        box.addButton(self.btn_text, QDialogButtonBox.ButtonRole.ActionRole)
        box.addButton(self.btn_mid, QDialogButtonBox.ButtonRole.ActionRole)
        box.rejected.connect(self.reject)
        self.btn_mid.setVisible(bool(mid))  # efter addButton (omförälder återställer synlighet)
        lay.addWidget(box)

    @staticmethod
    def _copy(text: str) -> None:
        cb = QGuiApplication.clipboard()
        if cb is not None:
            cb.setText(text)
