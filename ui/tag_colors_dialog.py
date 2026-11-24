# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""
tag_colors_dialog.py — 🏷 Taggfärger: en rad per tagg med förhandsvisning, färgval och "Standard".

Taggarna hämtas från alla uppgifter (aktiva + historik) och egna taggar. Valen sparas i
inställningarna (``tag_colors``) och slår igenom direkt i alla fönster. Färglogiken finns i
core/tag_colors.py.
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional

from core import tag_colors as tc

logger = logging.getLogger("Ledgebord")
LOG_PREFIX = "[TAGGFÄRG-UI]"

try:
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import (
        QColorDialog, QDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
    )
    _QT = True
except ImportError:  # pragma: no cover
    _QT = False
    QWidget = Any  # type: ignore[misc,assignment]


def all_tags(store: Any, settings: Any = None) -> List[str]:
    """Alla taggar som används (gemener, sorterade) — plus de med eget färgval och egna taggar."""
    seen: dict = {}
    try:
        tasks = list(store.active_tasks()) + list(store.archive_tasks())
    except Exception:
        tasks = []
    for t in tasks:
        for tag in (t.get("tags") or []):
            k = tc.normalize(tag)
            if k:
                seen[k] = True
    for src in ("custom_tags", "tag_colors"):
        try:
            val = getattr(settings, src)()
        except Exception:
            val = []
        for tag in (val.keys() if isinstance(val, dict) else val):
            k = tc.normalize(tag)
            if k:
                seen[k] = True
    return sorted(seen)


if _QT:

    class TagColorsDialog(QDialog):
        def __init__(self, parent: Optional[QWidget] = None, store: Any = None, settings: Any = None) -> None:
            super().__init__(parent)
            self.store, self.settings = store, settings
            self.setWindowTitle("🏷 Taggfärger")
            self.setModal(True)
            self.setMinimumSize(420, 420)
            rot = QVBoxLayout(self)
            rot.setContentsMargins(16, 14, 16, 12)
            intro = QLabel("Välj färg för varje tagg. Samma tagg har samma färg på alla uppgifter.", self)
            intro.setWordWrap(True)
            rot.addWidget(intro)
            self._scroll = QScrollArea(self)
            self._scroll.setWidgetResizable(True)
            rot.addWidget(self._scroll, 1)
            row = QHBoxLayout()
            row.addStretch(1)
            close = QPushButton("Stäng", self)
            close.clicked.connect(self.accept)
            row.addWidget(close)
            rot.addLayout(row)
            self.rows: dict = {}
            self._fill()

        def _fill(self) -> None:
            body = QWidget()
            lay = QVBoxLayout(body)
            lay.setSpacing(6)
            tags = all_tags(self.store, self.settings)
            over = self.settings.tag_colors() if self.settings is not None else {}
            self.rows = {}
            if not tags:
                lay.addWidget(QLabel("Det finns inga taggar än.", body))
            for tag in tags:
                color = tc.resolve(tag, over)
                line = QHBoxLayout()
                chip = QLabel(tag, body)
                chip.setStyleSheet(
                    f"QLabel {{ background-color: {color}; color: {tc.text_color_for(color)}; "
                    f"border: 1px solid {tc.darker(color)}; padding: 2px 10px; border-radius: 9px; "
                    f"font-weight: 600; }}")
                chip.setMinimumWidth(120)
                line.addWidget(chip)
                line.addStretch(1)
                pick = QPushButton("Välj färg…", body)
                pick.setAccessibleName(f"Välj färg för {tag}")
                pick.clicked.connect(lambda _c=False, t=tag: self._pick(t))
                line.addWidget(pick)
                std = QPushButton("Standard", body)
                std.setEnabled(tc.normalize(tag) in over)
                std.clicked.connect(lambda _c=False, t=tag: self._reset(t))
                line.addWidget(std)
                lay.addLayout(line)
                self.rows[tag] = (chip, pick, std)
            lay.addStretch(1)
            self._scroll.setWidget(body)

        def _pick(self, tag: str) -> None:
            cur = tc.resolve(tag, self.settings.tag_colors())
            col = QColorDialog.getColor(QColor(cur), self, f"Färg för \"{tag}\"")
            if col.isValid():
                self.set_color(tag, col.name(), defer=True)

        def _reset(self, tag: str) -> None:
            self.set_color(tag, None, defer=True)

        def set_color(self, tag: str, color: Optional[str], defer: bool = False) -> bool:
            ok = bool(self.settings.set_tag_color(tag, color))
            if ok:
                if defer:  # knappen som klickades sitter i raden som byggs om → vänta tills klicket är klart
                    QTimer.singleShot(0, self._fill)
                else:
                    self._fill()
            return ok


def open_tag_colors_dialog(parent: Optional[Any] = None, store: Any = None, settings: Any = None) -> bool:
    if not _QT or settings is None:
        return False
    try:
        TagColorsDialog(parent, store, settings).exec()
        return True
    except Exception as e:
        logger.warning(f"{LOG_PREFIX} kunde inte öppna dialogen: {e}", exc_info=True)
        return False
