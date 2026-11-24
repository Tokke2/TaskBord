# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""
edge_handle.py — den lilla FLIKEN som sitter kvar i skärmkanten när Ledgebord är gömt.

Fliken ligger alltid överst (över webbläsare, Thunderbird m.fl.), visar antal aktiva uppgifter — eller röd
”N försenade” — och är det enda stället som visar fönstret igen (håll musen på den en kort stund, eller klicka).
Då slipper andra programs verktygsfält och flikar i kanten råka ta fram Ledgebord.
Mått och text kommer från core/edge_dock.py; här finns bara ritningen.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from core import edge_dock as geo

logger = logging.getLogger("Ledgebord")
LOG_PREFIX = "[EDGEHANDLE]"

# Färger (vit text ≥ 4,5:1 mot alla): indigo 6,3 · mörkare indigo (hover) 7,9 · röd 6,5 · svart (hög kontrast) 21
COLORS = {"normal": "#4F46E5", "hover": "#4338CA", "overdue": "#B91C1C", "overdue_hover": "#991B1B", "contrast": "#000000"}
TEXT = "#FFFFFF"

try:
    from PySide6.QtCore import QPointF, QRectF, Qt, Signal
    from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPolygonF
    from PySide6.QtWidgets import QWidget
    _QT = True
except ImportError:  # pragma: no cover
    _QT = False
    QWidget = object  # type: ignore[misc,assignment]


def bg_color(overdue: bool, hover: bool, contrast: bool) -> str:
    if contrast:
        return COLORS["contrast"]
    if overdue:
        return COLORS["overdue_hover" if hover else "overdue"]
    return COLORS["hover" if hover else "normal"]


if _QT:

    class EdgeHandle(QWidget):
        clicked = Signal()

        def __init__(self, native_top: Optional[Callable[[int], bool]] = None) -> None:
            super().__init__(None)
            self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                                | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
            self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)
            self.setMouseTracking(True)
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.edge = "top"
            self._text = "Ledgebord"
            self._overdue = False
            self._hover = False
            self._contrast = False
            self._native = native_top
            self.zone: Optional[geo.Rect] = None      # skärmkoordinater

        # ------------------------------------------------------------------ data
        def font_for(self) -> Any:
            f = QFont(self.font())
            f.setPixelSize(12)
            f.setBold(True)
            return f

        def length_for(self, text: str) -> int:
            return QFontMetrics(self.font_for()).horizontalAdvance(text) + 46

        def set_info(self, active: int, overdue: int, contrast: bool = False) -> None:
            self._text = geo.handle_text(active, overdue)
            self._overdue = overdue > 0
            self._contrast = bool(contrast)
            self.setToolTip(
                (f"{overdue} försenade uppgifter · " if overdue else "") + f"{active} aktiva — håll musen här eller klicka för att visa Ledgebord"
            )
            self.setAccessibleName("Ledgebord — visa fönstret. " + self.toolTip())
            self.update()

        def place(self, edge: str, shown: geo.Rect, screen: geo.Rect) -> geo.Rect:
            """Placera fliken i kanten (mitt för fönstret). Returnerar flikens skärmrektangel."""
            self.edge = edge
            r = geo.handle_rect(shown, screen, edge, self.length_for(self._text))
            self.zone = r
            self.setGeometry(*r)
            return r

        def present(self) -> None:
            self.show()
            self.raise_()
            self.native_front()

        def native_front(self) -> None:
            """Lägg fliken överst bland alla toppfönster (Windows)."""
            try:
                fn = self._native
                if fn is None:
                    from app.dialog_front import native_topmost as fn  # type: ignore[assignment]
                if self.isVisible():
                    fn(int(self.winId()))
            except Exception as e:
                logger.debug(f"{LOG_PREFIX} native_front: {e}")

        # ------------------------------------------------------------------ ritning
        def paintEvent(self, _e: Any) -> None:  # noqa: N802
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            w, h = self.width(), self.height()
            r = 9.0
            path = QPainterPath()
            # runda hörn bara på sidan som INTE ligger mot skärmkanten
            if self.edge == "top":
                path.addRoundedRect(QRectF(0, -r, w, h + r), r, r)
            elif self.edge == "left":
                path.addRoundedRect(QRectF(-r, 0, w + r, h), r, r)
            else:
                path.addRoundedRect(QRectF(0, 0, w + r, h), r, r)
            col = QColor(bg_color(self._overdue, self._hover, self._contrast))
            p.fillPath(path, col)
            if self._contrast:
                p.setPen(QPen(QColor("#FFFFFF"), 2))
                p.drawPath(path)
            p.setPen(QColor(TEXT))
            p.setFont(self.font_for())
            if self.edge == "top":
                self._arrow(p, 14, h / 2 - 1, "down")
                p.drawText(QRectF(26, 0, w - 30, h - 2), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._text)
            else:
                p.save()
                if self.edge == "left":     # text som läses nerifrån och upp, pil åt höger
                    p.translate(0, h)
                    p.rotate(-90)
                else:                        # text som läses uppifrån och ner, pil åt vänster
                    p.translate(w, 0)
                    p.rotate(90)
                self._arrow(p, 14, w / 2 - 1, "down")
                p.drawText(QRectF(26, 0, h - 30, w - 2), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._text)
                p.restore()
            p.end()

        @staticmethod
        def _arrow(p: Any, cx: float, cy: float, _dir: str) -> None:
            tri = QPolygonF([QPointF(cx - 4, cy - 2), QPointF(cx + 4, cy - 2), QPointF(cx, cy + 3)])
            p.setBrush(QColor(TEXT))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPolygon(tri)
            p.setPen(QColor(TEXT))

        # ------------------------------------------------------------------ mus
        def enterEvent(self, e: Any) -> None:  # noqa: N802
            self._hover = True
            self.update()
            super().enterEvent(e)

        def leaveEvent(self, e: Any) -> None:  # noqa: N802
            self._hover = False
            self.update()
            super().leaveEvent(e)

        def mousePressEvent(self, e: Any) -> None:  # noqa: N802
            if e.button() == Qt.MouseButton.LeftButton:
                self.clicked.emit()
            e.accept()
