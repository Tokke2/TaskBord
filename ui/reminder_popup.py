# -*- coding: utf-8 -*-
"""
ui/reminder_popup.py — påminnelse som ett litet kort nere i hörnet, med knappar:

    ✓ Klar     Skjut 1 h (skjut upp en timme)     Öppna listan     ✕

Tar inte fokus (du kan skriva vidare i en annan app), försvinner av sig själv efter en stund
(står kvar medan musen är över kortet) och slår ihop flera påminnelser i samma kort.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from core.reminder_logic import OVERDUE, status_text

Item = Tuple[Any, ...]  # (task_id, titel, kind, dagar[, rad under titeln])

# Färger (WCAG ≥ 4,5:1 mot kortets bakgrund)
BG = "#1e1b4b"
BORDER = "#4338ca"
TEXT = "#f8fafc"
HEAD = "#c7d2fe"
SUB_TODAY = "#fcd34d"
SUB_OVERDUE = "#fca5a5"
BTN_BG = "#4f46e5"
BTN_BG_HOVER = "#5b54f0"
BTN_TEXT = "#ffffff"

STYLE = f"""
QFrame#card {{ background: {BG}; border: 1px solid {BORDER}; border-radius: 12px; }}
QLabel {{ background: transparent; }}
QLabel#head {{ color: {HEAD}; font-size: 12px; font-weight: 700; }}
QLabel#title {{ color: {TEXT}; font-size: 13px; font-weight: 600; }}
QLabel#more {{ color: {HEAD}; font-size: 12px; }}
QPushButton {{ background: {BTN_BG}; color: {BTN_TEXT}; border: none; border-radius: 6px;
               padding: 4px 10px; font-size: 12px; font-weight: 600; }}
QPushButton:hover {{ background: {BTN_BG_HOVER}; }}
QPushButton#ghost {{ background: transparent; color: {HEAD}; border: 1px solid {BORDER}; }}
QPushButton#ghost:hover {{ background: {BORDER}; color: {TEXT}; }}
"""


class ReminderPopup(QWidget):
    MAX_ROWS = 4
    WIDTH = 380

    def __init__(self, on_done: Callable[[str], None], on_snooze: Callable[[str], None],
                 on_open: Callable[[], None], timeout_ms: int = 30_000, hover_ms: int = 8_000) -> None:
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setObjectName("ReminderPopup")
        self.setStyleSheet(STYLE)
        self._on_done, self._on_snooze, self._on_open = on_done, on_snooze, on_open
        self._timeout_ms, self._hover_ms = timeout_ms, hover_ms
        self._items: Dict[str, Item] = {}
        self._card: Optional[QFrame] = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._expire)
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self.setFixedWidth(self.WIDTH)

    # ------------------------------------------------------------------ innehåll
    def items(self) -> List[Item]:
        return list(self._items.values())

    def show_items(self, items: List[Item]) -> None:
        """Lägg till/uppdatera påminnelser och visa kortet (utan att ta fokus)."""
        for it in items:
            self._items[it[0]] = it
        self._rebuild()
        if not self._items:
            self.hide()
            return
        self.place()
        if not self.isVisible():
            self.show()
        self.raise_()
        self._timer.start(self._timeout_ms)

    def _rebuild(self) -> None:
        if self._card is not None:
            self._outer.removeWidget(self._card)
            self._card.hide()
            self._card.setParent(None)   # inte kvar som barn medan raderingen väntar
            self._card.deleteLater()
            self._card = None
        if not self._items:
            return
        items = sorted(self._items.values(), key=lambda i: (0 if i[2] == OVERDUE else 1, -i[3]))
        n_over = sum(1 for i in items if i[2] == OVERDUE)
        n_today = len(items) - n_over
        parts = []
        if n_over:
            parts.append(f"{n_over} försenad{'e' if n_over > 1 else ''}")
        if n_today:
            parts.append(f"{n_today} förfaller idag")
        card = QFrame(self)
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)
        head = QLabel("Ledgebord — " + " • ".join(parts), card)
        head.setObjectName("head")
        lay.addWidget(head)
        for it in items[: self.MAX_ROWS]:
            lay.addLayout(self._row(card, it[0], it[1], it[2], it[3], it[4] if len(it) > 4 else ""))
        if len(items) > self.MAX_ROWS:
            more = QLabel(f"+ {len(items) - self.MAX_ROWS} till", card)
            more.setObjectName("more")
            lay.addWidget(more)
        foot = QHBoxLayout()
        foot.addStretch(1)
        b_open = QPushButton("Öppna listan", card)
        b_open.setObjectName("ghost")
        b_open.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b_open.clicked.connect(self._open)
        b_close = QPushButton("Stäng", card)
        b_close.setObjectName("ghost")
        b_close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b_close.clicked.connect(self.dismiss)
        foot.addWidget(b_open)
        foot.addWidget(b_close)
        lay.addLayout(foot)
        self._outer.addWidget(card)
        self._card = card
        self.adjustSize()

    def _row(self, parent: QWidget, tid: str, title: str, kind: str, days: int, detail: str = "") -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        col = QVBoxLayout()
        col.setSpacing(0)
        t = QLabel(title if len(title) <= 40 else title[:39] + "…", parent)
        t.setObjectName("title")
        t.setToolTip(title)
        sub = QLabel(detail or status_text(kind, days), parent)
        sub.setObjectName("sub")
        sub.setStyleSheet(f"color: {SUB_OVERDUE if kind == OVERDUE else SUB_TODAY}; font-size: 11px; font-weight: 600;")
        col.addWidget(t)
        col.addWidget(sub)
        row.addLayout(col, 1)
        b_done = QPushButton("✓ Klar", parent)
        b_done.setObjectName("done")
        b_done.setToolTip("Bocka av uppgiften")
        b_snz = QPushButton("Skjut 1 h", parent)
        b_snz.setObjectName("snooze")
        b_snz.setToolTip("Skjut upp en timme (uppgiften kommer tillbaka och påminner igen)")
        for b in (b_done, b_snz):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            row.addWidget(b)
        b_done.clicked.connect(lambda _c=False, i=tid: self._act(i, self._on_done))
        b_snz.clicked.connect(lambda _c=False, i=tid: self._act(i, self._on_snooze))
        return row

    # ------------------------------------------------------------------ handlingar
    def _act(self, tid: str, cb: Callable[[str], None]) -> None:
        try:
            cb(tid)
        finally:
            self._items.pop(tid, None)
            if self._items:
                self._rebuild()
                self.place()
                self._timer.start(self._timeout_ms)
            else:
                self.dismiss()

    def _open(self) -> None:
        try:
            self._on_open()
        finally:
            self.dismiss()

    def dismiss(self) -> None:
        """Stäng kortet (påminnelserna räknas som sedda)."""
        self._timer.stop()
        self._items.clear()
        self._rebuild()
        self.hide()

    def _expire(self) -> None:
        if self.underMouse():
            self._timer.start(self._hover_ms)
            return
        self.dismiss()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self._items:
            self._timer.start(self._hover_ms)
        super().leaveEvent(event)

    # ------------------------------------------------------------------ placering
    def place(self) -> None:
        """Nere till höger på skärmen där musen är (ovanför aktivitetsfältet)."""
        screen = QGuiApplication.screenAt(self._cursor_pos()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        g = screen.availableGeometry()
        self.adjustSize()
        x = g.right() - self.width() - 16 + 1
        y = g.bottom() - self.height() - 16 + 1
        self.move(max(g.left(), x), max(g.top(), y))

    @staticmethod
    def _cursor_pos():
        from PySide6.QtGui import QCursor
        return QCursor.pos()
