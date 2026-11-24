# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""
vector_icons.py — skarpa, ritade ikoner för titelradens knappar (uppdatera, lås, minimera, stäng).

Emoji och specialtecken ser olika ut på varje dator (och saknas helt på vissa). ``GlyphButton`` är en vanlig
``QPushButton`` vars text (⟳ ⏳ ⬆ ✓ 🔒 🔓 – ✕) styr VILKEN ikon som ritas — själva ikonen ritas som vektor i knappens
textfärg, så den följer temat, kontrasten och textstorleken. Texten finns kvar för skärmläsare och tester.
"""
from __future__ import annotations

import math
from typing import Dict, Optional

try:
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
    from PySide6.QtWidgets import QPushButton, QStyle, QStyleOptionButton, QStylePainter
    _QT = True
except ImportError:  # pragma: no cover
    _QT = False

# knapptext → ikonnamn
GLYPHS: Dict[str, str] = {
    "⟳": "refresh", "⏳": "hourglass", "⬆": "arrow_up", "✓": "check",
    "🔒": "lock", "🔓": "unlock", "–": "minimize", "✕": "close",
}


def draw_glyph(p: "QPainter", name: str, rect: "QRectF", color: "QColor", width: float = 1.9) -> bool:
    """Rita ikonen ``name`` centrerad i ``rect`` (≈ 14 px stor). False om namnet är okänt."""
    if name not in GLYPHS.values():
        return False
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    s = min(rect.width(), rect.height()) * 0.52          # ikonens sida
    cx, cy = rect.center().x(), rect.center().y()
    u = s / 14.0                                          # ritas i ett 14×14-rutnät
    pen = QPen(color, max(1.4, width * u))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    def P(x: float, y: float) -> "QPointF":               # rutnätskoordinat (-7..7) → pixel
        return QPointF(cx + x * u, cy + y * u)

    if name == "close":
        p.drawLine(P(-4.6, -4.6), P(4.6, 4.6))
        p.drawLine(P(4.6, -4.6), P(-4.6, 4.6))
    elif name == "minimize":
        p.drawLine(P(-5, 3), P(5, 3))
    elif name == "check":
        path = QPainterPath(P(-5, 0.5))
        path.lineTo(P(-1.6, 4))
        path.lineTo(P(5.2, -3.8))
        p.drawPath(path)
    elif name == "arrow_up":
        p.drawLine(P(0, 5.5), P(0, -5.2))
        path = QPainterPath(P(-4.4, -1.2))
        path.lineTo(P(0, -5.6))
        path.lineTo(P(4.4, -1.2))
        p.drawPath(path)
    elif name == "refresh":
        r = QRectF(cx - 5 * u, cy - 5 * u, 10 * u, 10 * u)
        p.drawArc(r, 40 * 16, 270 * 16)                   # nästan ett helt varv, öppet uppe till höger
        ang = math.radians(40)
        ex, ey = cx + 5 * u * math.cos(ang), cy - 5 * u * math.sin(ang)
        head = QPainterPath(QPointF(ex + 0.2 * u, ey - 4.2 * u))
        head.lineTo(QPointF(ex, ey))
        head.lineTo(QPointF(ex - 4.2 * u, ey + 0.2 * u))
        p.drawPath(head)
    elif name == "hourglass":
        path = QPainterPath(P(-4, -5.5))
        for pt in ((4, -5.5), (-4, 5.5), (4, 5.5)):
            path.lineTo(P(*pt))
        path.closeSubpath()
        p.drawPath(path)
    elif name in ("lock", "unlock"):
        body = QRectF(cx - 5 * u, cy - 0.5 * u, 10 * u, 7 * u)
        p.setBrush(color)
        p.drawRoundedRect(body, 1.8 * u, 1.8 * u)
        p.setBrush(Qt.BrushStyle.NoBrush)
        sh = QPainterPath()
        if name == "lock":
            sh.moveTo(P(-3, -0.5))
            sh.lineTo(P(-3, -3))
            sh.arcTo(QRectF(cx - 3 * u, cy - 7 * u, 6 * u, 8 * u), 180, -180)
            sh.lineTo(P(3, -0.5))
        else:                                              # öppet: bygeln lyfts på högra sidan
            sh.moveTo(P(-3, -0.5))
            sh.lineTo(P(-3, -3))
            sh.arcTo(QRectF(cx - 3 * u, cy - 7 * u, 6 * u, 8 * u), 180, -180)
            sh.lineTo(P(3, -2.5))
        p.drawPath(sh)
    p.restore()
    return True


if _QT:
    class GlyphButton(QPushButton):
        """QPushButton som ritar sin ikon som vektor (se modulens text). Utseendet i övrigt styrs av QSS."""

        def glyph(self) -> Optional[str]:
            return GLYPHS.get(self.text())

        def _glyph_color(self) -> "QColor":
            if self.objectName() == "closeBtn" and self.underMouse() and self.isEnabled():
                return QColor("#ffffff")
            if self.isChecked() and self.isCheckable():
                return QColor("#ffffff")
            c = QColor(self.palette().buttonText().color())
            if not self.isEnabled():
                c.setAlphaF(0.45)
            return c

        def paintEvent(self, ev) -> None:  # noqa: N802
            name = self.glyph()
            if name is None:
                super().paintEvent(ev)
                return
            p = QStylePainter(self)
            opt = QStyleOptionButton()
            self.initStyleOption(opt)
            opt.text = ""
            p.drawControl(QStyle.ControlElement.CE_PushButton, opt)
            draw_glyph(p, name, QRectF(self.rect()), self._glyph_color())
            p.end()
