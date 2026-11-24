# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""
welcome_dialog.py — 👋 Välkomstguiden: kort, lugn och utan inloggning. Texterna ligger i core/welcome.py.
"""
from __future__ import annotations

import logging
from typing import Any

from core import welcome as W

logger = logging.getLogger("Ledgebord")
LOG_PREFIX = "[WELCOME]"

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget
    _QT = True
except ImportError:  # pragma: no cover
    _QT = False

STYLE = """
QFrame#welBanner { border-radius: 14px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #2A2370, stop:1 #6D3AD9); }
QLabel#welTitle { color: #FFFFFF; font-size: 22px; font-weight: 800; background: transparent; }
QLabel#welSub { color: #E6E3FF; font-size: 13px; background: transparent; }
QLabel#welEmoji { font-size: 22px; background: transparent; }
QLabel#welHead { font-size: 14px; font-weight: 800; background: transparent; }
QLabel#welText { font-size: 13px; background: transparent; }
QPushButton#welGo { background: #4F46E5; color: #FFFFFF; border: 2px solid #4338CA; border-radius: 16px;
    padding: 9px 26px; font-weight: 800; font-size: 14px; }
QPushButton#welGo:hover { background: #4338CA; }
QPushButton#welGo:focus { border: 3px solid #FDE047; }
"""


if _QT:
    class WelcomeDialog(QDialog):
        def __init__(self, parent: Any = None) -> None:
            super().__init__(parent)
            self.setWindowTitle("👋 Välkommen till Ledgebord")
            self.setModal(True)
            self.setStyleSheet(STYLE)
            self.resize(520, 560)
            outer = QVBoxLayout(self)
            outer.setContentsMargins(16, 16, 16, 14)
            outer.setSpacing(12)
            banner = QFrame(self)
            banner.setObjectName("welBanner")
            bl = QVBoxLayout(banner)
            bl.setContentsMargins(18, 14, 18, 14)
            t = QLabel("👋  Välkommen till Ledgebord", banner)
            t.setObjectName("welTitle")
            s = QLabel("Din lugna uppgiftslista på skrivbordet. Allt sparas i en mapp på din egen dator.", banner)
            s.setObjectName("welSub")
            s.setWordWrap(True)
            bl.addWidget(t)
            bl.addWidget(s)
            outer.addWidget(banner)
            area = QScrollArea(self)
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.Shape.NoFrame)
            body = QWidget()
            lay = QVBoxLayout(body)
            lay.setContentsMargins(4, 4, 4, 4)
            lay.setSpacing(10)
            for emoji, head, text in W.TIPS:
                row = QHBoxLayout()
                row.setSpacing(12)
                e = QLabel(emoji, body)
                e.setObjectName("welEmoji")
                e.setFixedWidth(36)
                e.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
                col = QVBoxLayout()
                col.setSpacing(1)
                h = QLabel(head, body)
                h.setObjectName("welHead")
                tx = QLabel(text, body)
                tx.setObjectName("welText")
                tx.setWordWrap(True)
                col.addWidget(h)
                col.addWidget(tx)
                row.addWidget(e)
                row.addLayout(col, 1)
                lay.addLayout(row)
            lay.addStretch(1)
            area.setWidget(body)
            outer.addWidget(area, 1)
            note = QLabel("En exempeluppgift ligger i listan — bocka av den eller ta bort den när du vill. "
                          "Guiden finns alltid under högerklick → 👋 Välkomstguide.", self)
            note.setWordWrap(True)
            note.setObjectName("welText")
            outer.addWidget(note)
            btns = QHBoxLayout()
            btns.addStretch(1)
            self.go_btn = QPushButton("✓  Kom igång", self)
            self.go_btn.setObjectName("welGo")
            self.go_btn.setDefault(True)
            self.go_btn.setAccessibleName("Stäng välkomstguiden och kom igång")
            self.go_btn.clicked.connect(self.accept)
            btns.addWidget(self.go_btn)
            outer.addLayout(btns)


def open_welcome_dialog(parent: Any = None) -> bool:
    """Visa guiden (modalt). False om Qt saknas eller något gick fel."""
    if not _QT:
        return False
    try:
        dlg = WelcomeDialog(parent)
        dlg.exec()
        return True
    except Exception as e:  # pragma: no cover
        logger.warning(f"{LOG_PREFIX} kunde inte visa guiden: {e}")
        return False
