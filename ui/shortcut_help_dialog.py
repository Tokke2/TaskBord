# -*- coding: utf-8 -*-
"""
shortcut_help_dialog.py — ⌨️ Tangentöversikt (F1): alla tangenter och snabbkommandon, med dina egna
inställningar. Innehållet byggs i core/shortcut_help.py (testat utan Qt).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger("TaskBord")
LOG_PREFIX = "[HELP-UI]"

from core import shortcut_help as sh  # noqa: E402

try:
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import (
        QDialog, QHBoxLayout, QPushButton, QTextBrowser, QVBoxLayout, QWidget,
    )
    _QT = True
except ImportError:  # pragma: no cover
    _QT = False
    QWidget = Any  # type: ignore[misc,assignment]


if _QT:

    class ShortcutHelpDialog(QDialog):
        def __init__(self, parent: Optional[QWidget] = None, settings: Any = None) -> None:
            super().__init__(parent)
            self.setWindowTitle("⌨️ Tangentöversikt")
            self.setMinimumSize(560, 520)
            self._sections = sh.build_sections(settings)
            rot = QVBoxLayout(self)
            rot.setContentsMargins(14, 12, 14, 12)
            self.view = QTextBrowser(self)
            self.view.setOpenLinks(False)
            self.view.setHtml(sh.as_html(self._sections))
            rot.addWidget(self.view, 1)
            rad = QHBoxLayout()
            kopiera = QPushButton("📋 Kopiera som text", self)
            kopiera.clicked.connect(self._kopiera)
            rad.addWidget(kopiera)
            rad.addStretch(1)
            stang = QPushButton("Stäng", self)
            stang.setDefault(True)
            stang.clicked.connect(self.accept)
            rad.addWidget(stang)
            rot.addLayout(rad)

        def text(self) -> str:
            return sh.as_text(self._sections)

        def _kopiera(self) -> None:
            try:
                QGuiApplication.clipboard().setText(self.text())
            except Exception as e:  # pragma: no cover
                logger.warning(f"{LOG_PREFIX} kunde inte kopiera: {e}")


def open_shortcut_help(parent: Optional[Any] = None, settings: Any = None) -> bool:
    """Visa tangentöversikten. False om Qt saknas."""
    if not _QT:
        return False
    try:
        ShortcutHelpDialog(parent, settings=settings).exec()
        return True
    except Exception as e:  # pragma: no cover
        logger.error(f"{LOG_PREFIX} dialogen misslyckades: {e}", exc_info=True)
        return False
