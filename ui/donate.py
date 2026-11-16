# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""
donate.py — stöddialogen "💖 Stöd Ledgebord…" (högerklicksmenyn och tray-menyn).

Designprinciper:
  • Helt frivillig — appen fungerar exakt lika bra utan donation. Inget låses upp.
  • Inga påhittade siffror, omdömen, fördelningar eller "insamlat"-mål.
  • Valfritt belopp: genvägar (25/50/100/200 kr) eller eget belopp. Beloppet följer med in i PayPal
    (``paypal.me/…/<belopp>SEK``) och i Swish-QR:en; man kan alltid ändra det hos betaltjänsten.
  • Betalning sker hos PayPal/Ko-fi/Swish — Ledgebord ser inga betalningsuppgifter och kräver ingen inloggning.
  • MOTTAGARNA ÄR LÅSTA: de finns bara i core/donate_info.py (ingen inställning, ingen datafil, ingen miljövariabel)
    och kontrolleras mot en kontrollsumma varje gång dialogen öppnas — ändrade mottagare avaktiverar betalknapparna.
"""
from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Optional

from core import donate_info as DI

logger = logging.getLogger("Ledgebord")
LOG_PREFIX = "[DONATE]"

DONATE_TITLE: str = "💖 Stöd Ledgebord"
ICON_PNG = Path(__file__).resolve().parent.parent / "icon" / "ledgebord.png"

try:
    from PySide6.QtCore import Qt, QUrl
    from PySide6.QtGui import QDesktopServices, QPixmap
    from PySide6.QtWidgets import (
        QButtonGroup, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout, QWidget,
    )
    _QT_AVAILABLE: bool = True
except ImportError:  # pragma: no cover - Qt saknas (t.ex. i tester)
    _QT_AVAILABLE = False

STYLE = """
QFrame#donBanner { border-radius: 14px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #2A2370, stop:1 #6D3AD9); }
QLabel#donTitle { color: #FFFFFF; font-size: 22px; font-weight: 800; background: transparent; }
QLabel#donSub { color: #E6E3FF; font-size: 13px; background: transparent; }
QLabel#donHead { font-size: 15px; font-weight: 800; }
QPushButton#donChip { border: 2px solid palette(mid); border-radius: 17px; padding: 8px 18px; font-weight: 700;
    background: palette(base); color: palette(text); }
QPushButton#donChip:hover { border-color: #4F46E5; }
QPushButton#donChip:checked { background: #4F46E5; color: #FFFFFF; border-color: #4338CA; }
QSpinBox#donEget { border: 2px solid palette(mid); border-radius: 17px; padding: 6px 10px; font-weight: 700; min-width: 120px;
    background: palette(base); color: palette(text); }
QFrame#donFact { border: 1px solid palette(mid); border-radius: 10px; }
QLabel#donLock { font-size: 12px; }
"""


STYLE_FOR = {
    "donSwish": "QPushButton { background: #047857; color: #FFFFFF; border: none; border-radius: 12px; padding: 12px 14px; font-weight: 800; font-size: 14px; }"
                "QPushButton:hover { background: #065F46; } QPushButton:disabled { background: #6B7280; color: #FFFFFF; }",
    "donPaypal": "QPushButton { background: #0070BA; color: #FFFFFF; border: none; border-radius: 12px; padding: 12px 14px; font-weight: 800; font-size: 14px; }"
                 "QPushButton:hover { background: #005C99; } QPushButton:disabled { background: #6B7280; color: #FFFFFF; }",
    "donKofi": "QPushButton { background: #C62828; color: #FFFFFF; border: none; border-radius: 12px; padding: 12px 14px; font-weight: 800; font-size: 14px; }"
               "QPushButton:hover { background: #A81F1F; } QPushButton:disabled { background: #6B7280; color: #FFFFFF; }",
}


def _open_url(url: str) -> bool:
    """Öppna länk i standardwebbläsaren. Returnerar True vid lyckad start."""
    try:
        ok = QDesktopServices.openUrl(QUrl(url))
        logger.info(f"{LOG_PREFIX} öppnade donationslänk ({'ok' if ok else 'misslyckades'})")
        return bool(ok)
    except Exception as e:  # pragma: no cover
        logger.warning(f"{LOG_PREFIX} kunde inte öppna länk: {e}")
        return False


def swish_qr_png(kr: int) -> Optional[bytes]:
    """PNG-bytes med Swish-QR för beloppet, eller None (inget Swish-nummer inlagt / paketet ``segno`` saknas)."""
    if not DI.swish_aktiv():
        return None
    try:
        import segno
        buf = io.BytesIO()
        segno.make(DI.swish_payload(kr), error="m").save(buf, kind="png", scale=6, border=3)
        return buf.getvalue()
    except Exception as e:
        logger.info(f"{LOG_PREFIX} Swish-QR kunde inte ritas: {e}")
        return None


if _QT_AVAILABLE:
    class DonateDialog(QDialog):
        """Snygg, ärlig stöddialog: valfritt belopp → Swish (QR) / PayPal / Ko-fi. Mottagarna är låsta."""

        def __init__(self, parent: Optional[QWidget] = None) -> None:
            super().__init__(parent)
            self.setWindowTitle("Ledgebord — Stöd projektet")
            self.setModal(True)
            self.setMinimumWidth(560)
            self.setStyleSheet(STYLE)
            self._lock_ok = DI.las_ok()
            if not self._lock_ok:
                logger.error(f"{LOG_PREFIX} donationsmottagarna stämmer inte med kontrollsumman — betalknappar avstängda")

            root = QVBoxLayout(self)
            root.setContentsMargins(18, 16, 18, 14)
            root.setSpacing(12)

            # --- banner ---
            banner = QFrame(self)
            banner.setObjectName("donBanner")
            bl = QHBoxLayout(banner)
            bl.setContentsMargins(18, 16, 18, 16)
            bl.setSpacing(14)
            self.logo = QLabel(banner)
            self.logo.setFixedSize(64, 64)
            self.logo.setStyleSheet("background: transparent;")
            pm = QPixmap(str(ICON_PNG))
            if not pm.isNull():
                self.logo.setPixmap(pm.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio,
                                              Qt.TransformationMode.SmoothTransformation))
            bl.addWidget(self.logo)
            tl = QVBoxLayout()
            tl.setSpacing(2)
            title = QLabel(DONATE_TITLE, banner)
            title.setObjectName("donTitle")
            sub = QLabel("Gratis, utan reklam och utan konto.\nEtt frivilligt tack håller appen vid liv.", banner)
            sub.setObjectName("donSub")
            tl.addWidget(title)
            tl.addWidget(sub)
            bl.addLayout(tl, 1)
            root.addWidget(banner)

            # --- belopp ---
            head = QLabel("Välj belopp — eller skriv ett eget", self)
            head.setObjectName("donHead")
            root.addWidget(head)
            row = QHBoxLayout()
            row.setSpacing(8)
            self.group = QButtonGroup(self)
            self.group.setExclusive(True)
            self.chips = {}
            for kr in DI.BELOPP_VAL:
                b = QPushButton(f"{kr} kr", self)
                b.setObjectName("donChip")
                b.setCheckable(True)
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.clicked.connect(lambda _=False, v=kr: self._pick(v))
                self.group.addButton(b)
                self.chips[kr] = b
                row.addWidget(b)
            self.eget = QSpinBox(self)
            self.eget.setObjectName("donEget")
            self.eget.setRange(DI.BELOPP_MIN, DI.BELOPP_MAX)
            self.eget.setSuffix(" kr")
            self.eget.setValue(DI.BELOPP_STANDARD)
            self.eget.setAccessibleName("Eget belopp i kronor")
            self.eget.valueChanged.connect(self._sync_chips)
            row.addWidget(self.eget)
            row.addStretch(1)
            root.addLayout(row)
            self.info = QLabel("", self)
            root.addWidget(self.info)

            self.swish_available = DI.swish_aktiv()
            # --- Swish-QR (standard, visas direkt; numret visas aldrig i text) ---
            self.qr_box = QFrame(self)
            ql = QVBoxLayout(self.qr_box)
            ql.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            self.qr_label = QLabel(self.qr_box)
            self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.qr_label.setStyleSheet("background: #FFFFFF; border-radius: 10px; padding: 8px;")
            self.qr_note = QLabel("💚 Swish — skanna QR-koden med Swish-appen. Beloppet är förifyllt men kan ändras i appen.", self.qr_box)
            self.qr_note.setWordWrap(True)
            self.qr_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ql.addWidget(self.qr_label)
            ql.addWidget(self.qr_note)
            self.qr_box.setVisible(self.swish_available)
            root.addWidget(self.qr_box)

            # --- övriga sätt: knappar (öppnar betaltjänstens sida i webbläsaren) ---
            self.other_label = QLabel("Andra sätt att stödja:", self)
            self.other_label.setObjectName("donHead")
            self.other_label.setVisible(self.swish_available)
            root.addWidget(self.other_label)
            pay = QHBoxLayout()
            pay.setSpacing(8)
            self.btn_paypal = QPushButton("", self)
            self.btn_paypal.clicked.connect(self._open_paypal)
            self.btn_kofi = QPushButton("☕ Ko-fi", self)
            self.btn_kofi.clicked.connect(lambda: _open_url(DI.kofi_url()))
            for b, extra in ((self.btn_paypal, "donPaypal"), (self.btn_kofi, "donKofi")):
                b.setProperty("kind", extra)
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.setStyleSheet(STYLE_FOR[extra])
                pay.addWidget(b, 1)
            root.addLayout(pay)

            # --- ärliga fakta ---
            for icon, text in (
                ("🚫", "Ingen reklam, ingen inloggning, inga prenumerationer."),
                ("🎁", "Appen fungerar exakt lika bra utan donation — inget låses upp."),
                ("🔒", "Betalningen sker i Swish-appen, hos PayPal eller Ko-fi. Ledgebord ser inga betalningsuppgifter."),
            ):
                f = QFrame(self)
                f.setObjectName("donFact")
                fl = QHBoxLayout(f)
                fl.setContentsMargins(10, 6, 10, 6)
                ic = QLabel(icon, f)
                ic.setFixedWidth(24)
                tx = QLabel(text, f)
                tx.setWordWrap(True)
                fl.addWidget(ic)
                fl.addWidget(tx, 1)
                root.addWidget(f)

            # --- lås-status ---
            self.lock_label = QLabel("", self)
            self.lock_label.setObjectName("donLock")
            self.lock_label.setWordWrap(True)
            root.addWidget(self.lock_label)

            close_row = QHBoxLayout()
            close_row.addStretch(1)
            btn_close = QPushButton("Stäng", self)
            btn_close.setDefault(True)
            btn_close.clicked.connect(self.accept)
            close_row.addWidget(btn_close)
            root.addLayout(close_row)

            if self._lock_ok:
                self.lock_label.setText("🔒 Mottagarna är inbyggda och låsta — de kan inte ändras i appen.")
            else:
                self.lock_label.setText(
                    "⚠ Donationsmottagarna i den här kopian av Ledgebord stämmer inte med originalet, så betalknapparna är "
                    "avstängda. Kör <b>Sök ny version</b> för att återställa originalfilerna, eller hämta appen från "
                    "github.com/Tokke2/TaskBord.")
                self.lock_label.setTextFormat(Qt.TextFormat.RichText)
                for b in (self.btn_paypal, self.btn_kofi):
                    b.setEnabled(False)
            self._sync_chips(self.eget.value())

        # -------------------------------------------------------------
        def belopp(self) -> int:
            return DI.clamp_belopp(self.eget.value())

        def _pick(self, kr: int) -> None:
            self.eget.setValue(kr)

        def _sync_chips(self, v: int) -> None:
            """Markera genvägen som motsvarar beloppet (eller ingen vid eget belopp) och uppdatera texter."""
            self.group.setExclusive(False)
            for kr, b in self.chips.items():
                b.setChecked(kr == v)
            self.group.setExclusive(True)
            kr = self.belopp()
            self.info.setText(f"Valt: <b>{kr} kr</b> — tack! 💚 (du kan ändra beloppet hos betaltjänsten)")
            self.info.setTextFormat(Qt.TextFormat.RichText)
            self.btn_paypal.setText(f"💙 PayPal — {kr} kr")
            self.btn_paypal.setToolTip(DI.paypal_url(kr))
            self.btn_kofi.setToolTip(DI.kofi_url())
            if self.swish_available:
                self._show_qr()

        def _open_paypal(self) -> None:
            if self._lock_ok:
                _open_url(DI.paypal_url(self.belopp()))

        def _show_qr(self) -> None:
            if not self._lock_ok:
                self.qr_box.setVisible(False)
                return
            data = swish_qr_png(self.belopp())
            if not data:
                self.qr_label.setText("QR-koden kunde inte ritas (paketet 'segno' saknas).")
                self.qr_box.setVisible(True)
                return
            pm = QPixmap()
            pm.loadFromData(data, "PNG")
            self.qr_label.setPixmap(pm)
            self.qr_box.setVisible(True)


def open_donate_dialog(parent: Optional["QWidget"] = None) -> bool:
    """Visa stöddialogen. Returnerar False om Qt inte är tillgängligt."""
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
