# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""
donate.py — stöddialogen "💖 Stöd Ledgebord…" (högerklicksmenyn och tray-menyn).

Designprinciper:
  • Helt frivillig — appen fungerar exakt lika bra utan donation. Inget låses upp.
  • Inga påhittade siffror, omdömen, fördelningar eller "insamlat"-mål.
  • Valfritt belopp: genvägar (25/50/100/200 kr) eller eget belopp. Beloppet följer med in i PayPal
    (``paypal.me/…/<belopp>SEK``) och i Swish-QR:en (bara Swish har QR — PayPal och Ko-fi är knappar); man kan alltid ändra det hos betaltjänsten.
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

QR_BOX = 220
DONATE_TITLE: str = "💖 Stöd Ledgebord"
ICON_PNG = Path(__file__).resolve().parent.parent / "icon" / "ledgebord.png"

try:
    from PySide6.QtCore import Qt, QUrl
    from PySide6.QtGui import QDesktopServices, QPixmap
    from PySide6.QtWidgets import (
        QButtonGroup, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QVBoxLayout,
        QWidget,
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
QLabel#donIntro { font-size: 13px; }
QPushButton#donChip { border: 2px solid palette(mid); border-radius: 17px; padding: 8px 18px; font-weight: 700;
    background: palette(base); color: palette(text); }
QPushButton#donChip:hover { border-color: #4F46E5; }
QPushButton#donChip:checked { background: #4F46E5; color: #FFFFFF; border-color: #4338CA; }
QSpinBox#donEget { border: 2px solid palette(mid); border-radius: 17px; padding: 6px 10px; font-weight: 700; min-width: 120px;
    background: palette(base); color: palette(text); }
QFrame#donCard { border: 1px solid palette(mid); border-radius: 14px; background: palette(base); }
QFrame#donCard QLabel { background: transparent; }
QLabel#donCardTitle { font-size: 15px; font-weight: 800; }
QLabel#donCardNote { font-size: 12px; }
QLabel#donQr { background: #FFFFFF; border-radius: 10px; }
QLabel#donFacts { font-size: 12px; }
QLabel#donLock { font-size: 12px; }
"""


def _btn_css(bg: str, hover: str) -> str:
    return ("QPushButton { background: %s; color: #FFFFFF; border: none; border-radius: 12px; padding: 11px 14px; "
            "font-weight: 800; font-size: 14px; } QPushButton:hover { background: %s; } "
            "QPushButton:disabled { background: #6B7280; color: #FFFFFF; }" % (bg, hover))


STYLE_FOR = {
    "donPaypal": _btn_css("#0070BA", "#005C99"),
    "donKofi": _btn_css("#C62828", "#A81F1F"),
}

INTRO_HTML = (
    "<b>Ledgebord är gratis, utan reklam och utan konto — och ska förbli det.</b><br>"
    "Jag utvecklar och underhåller appen själv: nya funktioner, rättningar och tester. "
    "Sparar den tid för dig är en donation — stor eller liten — ett uppskattat tack som hjälper mig att fortsätta. "
    "Det är helt frivilligt och ändrar ingenting i appen."
)
FACTS_TEXT = (
    "🚫 Ingen reklam, ingen inloggning, inga prenumerationer.   🎁 Inget låses upp — appen är lika bra utan donation.   "
    "🕊️ Ingen spårning.\n"
    "🔒 Betalningen sker i Swish-appen eller hos PayPal/Ko-fi. Ledgebord ser inga betalningsuppgifter. "
    "Du kan alltid ändra beloppet hos betaltjänsten."
)


def _open_url(url: str) -> bool:
    """Öppna länk i standardwebbläsaren. Returnerar True vid lyckad start."""
    try:
        ok = QDesktopServices.openUrl(QUrl(url))
        logger.info(f"{LOG_PREFIX} öppnade donationslänk ({'ok' if ok else 'misslyckades'})")
        return bool(ok)
    except Exception as e:  # pragma: no cover
        logger.warning(f"{LOG_PREFIX} kunde inte öppna länk: {e}")
        return False


def qr_png(payload: str, max_px: int = QR_BOX - 8) -> Optional[bytes]:
    """PNG-bytes med en QR-kod för ``payload`` (ritas lokalt med paketet ``segno``), eller None om det saknas.
    Hela pixlar per ruta (skarpt, inga sneda skalningar) — största skalan som ryms i ``max_px``."""
    try:
        import segno
        code = segno.make(payload, error="m")
        scale = 2
        for sc in range(8, 1, -1):
            if code.symbol_size(scale=sc, border=2)[0] <= max_px:
                scale = sc
                break
        buf = io.BytesIO()
        code.save(buf, kind="png", scale=scale, border=2)
        return buf.getvalue()
    except Exception as e:
        logger.info(f"{LOG_PREFIX} QR-kod kunde inte ritas: {e}")
        return None


def swish_qr_png(kr: int) -> Optional[bytes]:
    """Swish-QR för beloppet, eller None (inget Swish-nummer / ``segno`` saknas)."""
    return qr_png(DI.swish_payload(kr)) if DI.swish_aktiv() else None


if _QT_AVAILABLE:
    class DonateDialog(QDialog):
        """Egen stöddialog: valfritt belopp → Swish (QR enligt Swish-standard) samt PayPal och Ko-fi (bara knappar, ingen QR). Mottagarna är låsta."""

        def __init__(self, parent: Optional[QWidget] = None) -> None:
            super().__init__(parent)
            self.setWindowTitle("Ledgebord — Stöd projektet")
            self.setModal(True)
            self.setMinimumWidth(700)
            self.setStyleSheet(STYLE)
            self._lock_ok = DI.las_ok()
            if not self._lock_ok:
                logger.error(f"{LOG_PREFIX} donationsmottagarna stämmer inte med kontrollsumman — betalning avstängd")
            self.swish_available = DI.swish_aktiv()

            # Innehållet ligger i en rullningsyta så dialogen aldrig blir högre än skärmen.
            outer = QVBoxLayout(self)
            outer.setContentsMargins(0, 0, 0, 10)
            outer.setSpacing(6)
            self.scroll = QScrollArea(self)
            self.scroll.setWidgetResizable(True)
            self.scroll.setFrameShape(QFrame.Shape.NoFrame)
            self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.inner = QWidget()
            self.scroll.setWidget(self.inner)
            outer.addWidget(self.scroll, 1)
            root = QVBoxLayout(self.inner)
            root.setContentsMargins(18, 16, 18, 8)
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
            sub = QLabel("Tack för att du vill stödja Ledgebord.\nVälj belopp och sätt: Swish (QR), PayPal eller Ko-fi.", banner)
            sub.setObjectName("donSub")
            tl.addWidget(title)
            tl.addWidget(sub)
            bl.addLayout(tl, 1)
            root.addWidget(banner)

            intro = QLabel(INTRO_HTML, self)
            intro.setObjectName("donIntro")
            intro.setTextFormat(Qt.TextFormat.RichText)
            intro.setWordWrap(True)
            root.addWidget(intro)

            # --- belopp ---
            head = QLabel("1. Välj belopp — eller skriv ett eget", self)
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
            self.info.setTextFormat(Qt.TextFormat.RichText)
            root.addWidget(self.info)

            # --- sätt att stödja: Swish-QR (enligt Swish-standard) + knappar för PayPal och Ko-fi — ingen QR för dem ---
            head2 = QLabel("2. Välj sätt — skanna Swish-koden eller klicka på en knapp", self)
            head2.setObjectName("donHead")
            root.addWidget(head2)
            cards = QHBoxLayout()
            cards.setSpacing(12)
            self.swish_card = QFrame(self)
            self.swish_card.setObjectName("donCard")
            sl = QVBoxLayout(self.swish_card)
            sl.setContentsMargins(14, 12, 14, 12)
            sl.setSpacing(8)
            st = QLabel("💚 Swish", self.swish_card)
            st.setObjectName("donCardTitle")
            st.setStyleSheet("color: #047857;")
            st.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sl.addWidget(st)
            self.qr_swish = QLabel(self.swish_card)
            self.qr_swish.setObjectName("donQr")
            self.qr_swish.setFixedSize(QR_BOX, QR_BOX)
            self.qr_swish.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.qr_swish.setAccessibleName("Swish-QR-kod med valt belopp")
            sl.addWidget(self.qr_swish, 0, Qt.AlignmentFlag.AlignHCenter)
            sn = QLabel("📱 Skanna med Swish-appen. Numret visas aldrig som text — QR-koden öppnar betalningen direkt "
                        "i appen. Beloppet är förifyllt men kan ändras där.", self.swish_card)
            sn.setObjectName("donCardNote")
            sn.setWordWrap(True)
            sn.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sn.setMaximumWidth(QR_BOX + 40)
            sl.addWidget(sn, 0, Qt.AlignmentFlag.AlignHCenter)
            cards.addWidget(self.swish_card, 0)

            web = QFrame(self)
            web.setObjectName("donCard")
            wl = QVBoxLayout(web)
            wl.setContentsMargins(14, 12, 14, 12)
            wl.setSpacing(8)
            wt = QLabel("🌐 Eller via webben", web)
            wt.setObjectName("donCardTitle")
            wl.addWidget(wt)
            self.btn_paypal = QPushButton("", web)
            self.btn_paypal.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_paypal.setMinimumHeight(46)
            self.btn_paypal.setStyleSheet(STYLE_FOR["donPaypal"])
            wl.addWidget(self.btn_paypal)
            ppn = QLabel("Öppnas hos PayPal med valt belopp (kan ändras där). Kvittot kommer från PayPal.", web)
            ppn.setObjectName("donCardNote")
            ppn.setWordWrap(True)
            wl.addWidget(ppn)
            self.btn_kofi = QPushButton("", web)
            self.btn_kofi.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_kofi.setMinimumHeight(46)
            self.btn_kofi.setStyleSheet(STYLE_FOR["donKofi"])
            wl.addWidget(self.btn_kofi)
            kfn = QLabel("Valfritt belopp — engångs eller månadsvis (avsluta när du vill, ingen bindning).", web)
            kfn.setObjectName("donCardNote")
            kfn.setWordWrap(True)
            wl.addWidget(kfn)
            wl.addStretch(1)
            cards.addWidget(web, 1)
            self.btn_paypal.clicked.connect(self._open_paypal)
            self.btn_kofi.clicked.connect(lambda: _open_url(DI.kofi_url()) if self._lock_ok else None)
            self.btn_paypal.setToolTip(DI.paypal_url(DI.BELOPP_STANDARD))
            self.btn_kofi.setToolTip(DI.kofi_url())
            root.addLayout(cards)
            self.swish_card.setVisible(self.swish_available)

            facts = QLabel(FACTS_TEXT, self)
            facts.setObjectName("donFacts")
            facts.setWordWrap(True)
            root.addWidget(facts)

            self.lock_label = QLabel("", self)
            self.lock_label.setObjectName("donLock")
            self.lock_label.setWordWrap(True)
            root.addWidget(self.lock_label)

            close_row = QHBoxLayout()
            close_row.setContentsMargins(18, 0, 18, 0)
            close_row.addStretch(1)
            btn_close = QPushButton("Stäng", self)
            btn_close.setDefault(True)
            btn_close.clicked.connect(self.accept)
            close_row.addWidget(btn_close)
            outer.addLayout(close_row)

            if self._lock_ok:
                self.lock_label.setText("🔒 Mottagarna är inbyggda och låsta — de kan inte ändras i appen.")
            else:
                self.lock_label.setText(
                    "⚠ Donationsmottagarna i den här kopian av Ledgebord stämmer inte med originalet, så betalningen är "
                    "avstängd. Kör <b>Sök ny version</b> för att återställa originalfilerna, eller hämta appen från "
                    "github.com/Tokke2/TaskBord.")
                self.lock_label.setTextFormat(Qt.TextFormat.RichText)
                for b in (self.btn_paypal, self.btn_kofi):
                    b.setEnabled(False)
            self._sync_chips(self.eget.value())

        def showEvent(self, event) -> None:  # type: ignore[override]
            """Storlek efter innehållet (radbrytande etiketter ger fel förslag före första visningen), men aldrig högre än skärmen."""
            super().showEvent(event)
            try:
                self.inner.layout().activate()
                hint = self.inner.sizeHint()
                scr = self.screen().availableGeometry() if self.screen() else None
                h = hint.height() + 56
                w = hint.width() + 6
                if scr is not None:
                    h = min(h, scr.height() - 60)
                    w = min(w, scr.width() - 40)
                self.resize(max(w, 700), max(h, 360))
            except Exception as e:  # pragma: no cover
                logger.info(f"{LOG_PREFIX} storlek: {e}")

        # -------------------------------------------------------------
        def belopp(self) -> int:
            return DI.clamp_belopp(self.eget.value())

        def _pick(self, kr: int) -> None:
            self.eget.setValue(kr)

        def _set_qr(self, label: "QLabel", data: Optional[bytes]) -> None:
            if data and self._lock_ok:
                pm = QPixmap()
                pm.loadFromData(data, "PNG")
                label.setPixmap(pm)
            else:
                label.clear()
                label.setText("QR-koden kunde inte ritas" if self._lock_ok else "avstängd")

        def _sync_chips(self, v: int) -> None:
            """Markera genvägen som motsvarar beloppet, och rita om belopp-beroende QR-koder och knappar."""
            self.group.setExclusive(False)
            for kr, b in self.chips.items():
                b.setChecked(kr == v)
            self.group.setExclusive(True)
            kr = self.belopp()
            self.info.setText(f"Valt: <b>{kr} kr</b> — tack! 💚")
            self.btn_paypal.setText(f"💙 PayPal — {kr} kr")
            self.btn_paypal.setToolTip(DI.paypal_url(kr))
            self.btn_kofi.setText("☕ Ko-fi — valfritt / månadsvis")
            if self.swish_available:
                self._set_qr(self.qr_swish, swish_qr_png(kr))

        def _open_paypal(self) -> None:
            if self._lock_ok:
                _open_url(DI.paypal_url(self.belopp()))


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
