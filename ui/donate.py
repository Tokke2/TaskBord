# -*- coding: utf-8 -*-
"""
NY v8: Donationsdialog för Ledgebord.

Öppnas från fönstrets högerklicksmeny ("💖 Stöd Ledgebord…").

Designprinciper:
  • Helt frivillig — appen fungerar lika bra utan donation.
  • Inga påhittade siffror, omdömen eller "insamlat"-mål.
  • Betalning sker hos PayPal/Ko-fi i webbläsaren. Appen ser inga
    betalningsuppgifter och kräver ingen inloggning.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("Ledgebord")
LOG_PREFIX = "[DONATE]"

# Donationslänkar. Ändra här om de ska peka på andra konton.
DONATE_PAYPAL_URL: str = "https://paypal.me/Rickard3dPrint"
DONATE_KOFI_URL: str = "https://ko-fi.com/tokke2"

DONATE_TITLE: str = "💖 Stöd Ledgebord"
DONATE_TEXT_HTML: str = (
    "<p><b>Ledgebord är gratis och utan reklam.</b> Om appen hjälper dig i "
    "vardagen är en donation ett frivilligt tack som hjälper mig att fortsätta "
    "utveckla och underhålla den.</p>"
    "<ul>"
    "<li>Ingen reklam, ingen inloggning, inga prenumerationer.</li>"
    "<li>Donationer går direkt till utveckling och underhåll.</li>"
    "<li>Appen fungerar exakt lika bra utan donation.</li>"
    "</ul>"
    "<p style='color:#8a8a9e;font-size:11px'>Betalningen sker hos PayPal eller "
    "Ko-fi i din webbläsare. Ledgebord ser inga betalningsuppgifter.</p>"
)

try:
    from PySide6.QtCore import Qt, QUrl
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import (
        QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
    )
    _QT_AVAILABLE: bool = True
except ImportError:  # pragma: no cover - Qt saknas (t.ex. i tester)
    _QT_AVAILABLE = False


if _QT_AVAILABLE:
    class DonateDialog(QDialog):
        """Liten, ärlig donationsruta med länkar till PayPal och Ko-fi."""

        def __init__(self, parent: Optional[QWidget] = None) -> None:
            super().__init__(parent)
            self.setWindowTitle("Ledgebord — Stöd projektet")
            self.setModal(True)
            self.setMinimumWidth(380)

            root = QVBoxLayout(self)
            root.setContentsMargins(18, 16, 18, 14)
            root.setSpacing(10)

            title = QLabel(DONATE_TITLE, self)
            title.setStyleSheet("font-size: 18px; font-weight: 800;")
            root.addWidget(title)

            body = QLabel(DONATE_TEXT_HTML, self)
            body.setTextFormat(Qt.TextFormat.RichText)
            body.setWordWrap(True)
            body.setOpenExternalLinks(True)
            root.addWidget(body)

            buttons = QHBoxLayout()
            buttons.setSpacing(8)

            btn_paypal = QPushButton("💙 Donera via PayPal", self)
            btn_paypal.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_paypal.setToolTip(DONATE_PAYPAL_URL)
            btn_paypal.clicked.connect(lambda: _open_url(DONATE_PAYPAL_URL))
            buttons.addWidget(btn_paypal, 1)

            btn_kofi = QPushButton("☕ Bjud på en kaffe", self)
            btn_kofi.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_kofi.setToolTip(DONATE_KOFI_URL)
            btn_kofi.clicked.connect(lambda: _open_url(DONATE_KOFI_URL))
            buttons.addWidget(btn_kofi, 1)

            root.addLayout(buttons)

            close_row = QHBoxLayout()
            close_row.addStretch(1)
            btn_close = QPushButton("Stäng", self)
            btn_close.clicked.connect(self.accept)
            close_row.addWidget(btn_close)
            root.addLayout(close_row)


def _open_url(url: str) -> bool:
    """Öppna länk i standardwebbläsaren. Returnerar True vid lyckad start."""
    try:
        ok = QDesktopServices.openUrl(QUrl(url))
        logger.info(f"{LOG_PREFIX} öppnade donationslänk ({'ok' if ok else 'misslyckades'})")
        return bool(ok)
    except Exception as e:  # pragma: no cover
        logger.warning(f"{LOG_PREFIX} kunde inte öppna länk: {e}")
        return False


def open_donate_dialog(parent: Optional[QWidget] = None) -> bool:
    """Visa donationsdialogen. Returnerar False om Qt inte är tillgängligt."""
    if not _QT_AVAILABLE:
        logger.warning(f"{LOG_PREFIX} Qt saknas — kan inte visa donationsdialog")
        return False
    try:
        dlg = DonateDialog(parent)
        dlg.exec()
        return True
    except Exception as e:  # pragma: no cover
        logger.warning(f"{LOG_PREFIX} donationsdialog misslyckades: {e}")
        return False
