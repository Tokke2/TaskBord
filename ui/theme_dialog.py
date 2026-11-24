# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""
theme_dialog.py — 🎨 Teman och utseende: färgtema, glasstyrka, bakgrundsdjup, högkontrast och textstorlek.
Allt slår igenom direkt (förhandsvisning i själva fönstret) och sparas. Logiken ligger i core/themes.py.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from core import themes as TH

logger = logging.getLogger("Ledgebord")
LOG_PREFIX = "[THEME]"

try:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import (
        QCheckBox, QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSlider, QVBoxLayout, QWidget,
    )
    _QT = True
except ImportError:  # pragma: no cover
    _QT = False

STYLE = """
QLabel#thHead { font-size: 15px; font-weight: 800; }
QLabel#thVal { font-weight: 700; }
QPushButton#thPreset { border: 2px solid palette(mid); border-radius: 12px; padding: 8px 6px; font-weight: 700;
    background: palette(base); color: palette(text); text-align: center; }
QPushButton#thPreset:checked { border: 3px solid #4F46E5; background: palette(alternate-base); }
QPushButton#thPreset:focus { border: 3px solid #FDE047; }
"""


if _QT:
    class ThemeDialog(QDialog):
        def __init__(self, parent: Any, settings: Any, on_change: Optional[Callable[[], None]] = None,
                     on_glass: Optional[Callable[[float], None]] = None) -> None:
            super().__init__(parent)
            self.settings = settings
            self._on_change = on_change or (lambda: None)
            self._on_glass = on_glass
            self._busy = False
            self.setWindowTitle("🎨 Teman och utseende")
            self.setStyleSheet(STYLE)
            self.resize(480, 560)
            outer = QVBoxLayout(self)
            area = QScrollArea(self)
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.Shape.NoFrame)
            body = QWidget()
            lay = QVBoxLayout(body)
            lay.setSpacing(10)
            h = QLabel("Färgtema", body)
            h.setObjectName("thHead")
            lay.addWidget(h)
            grid = QGridLayout()
            self.preset_buttons = {}
            cur = str(settings.pref("theme_preset"))
            for i, (key, label) in enumerate(TH.labels()):
                b = QPushButton(label, body)
                b.setObjectName("thPreset")
                b.setCheckable(True)
                b.setChecked(key == cur)
                dark, light = TH.SWATCH[key]
                b.setToolTip(f"Färgtema: {label}")
                b.setAccessibleName(f"Färgtema {label}")
                b.setStyleSheet(f"QPushButton#thPreset {{ border-left: 14px solid {dark}; border-right: 14px solid {light}; }}")
                b.clicked.connect(lambda _c=False, k=key: self.set_preset(k))
                self.preset_buttons[key] = b
                grid.addWidget(b, i // 3, i % 3)
            lay.addLayout(grid)
            fh = QLabel("Typsnitt", body)
            fh.setObjectName("thHead")
            lay.addWidget(fh)
            self.font_combo = QComboBox(body)
            self.font_combo.setAccessibleName("Typsnitt")
            self.font_combo.setToolTip("Byter typsnitt i hela fönstret. Verdana är extra lättläst.")
            curf = str(settings.pref("ui_font"))
            for key, label in TH.font_labels():
                self.font_combo.addItem(label, key)
                if key == curf:
                    self.font_combo.setCurrentIndex(self.font_combo.count() - 1)
            self.font_combo.currentIndexChanged.connect(self._font_changed)
            lay.addWidget(self.font_combo)
            self.glass_slider, self.glass_val = self._slider(body, lay, "Glasstyrka (genomskinlighet)", 0, 30, self._glass_pct(),
                                                              "0 % = helt täckande panel · 30 % = mest genomskinlig (text förblir läsbar)")
            self.dim_slider, self.dim_val = self._slider(body, lay, "Bakgrundsdjup", 0, 60, int(settings.pref("bg_dim")),
                                                         "Mörkare bakgrund i mörkt tema, ljusare i ljust — mer kontrast mot texten")
            self.scale_slider, self.scale_val = self._slider(body, lay, "Textstorlek", 80, 200, int(settings.pref("text_scale")),
                                                             "80–200 %. Ctrl+Plus / Ctrl+Minus / Ctrl+0 fungerar också i fönstret")
            self.crisp_check = QCheckBox("Skarp bild (hård, tydlig text — ingen mjuk gloria över panelen)", body)
            self.crisp_check.setChecked(bool(settings.pref("crisp")))
            self.crisp_check.setToolTip("Full hinting på texten och ingen dimma över panelens överdel.")
            self.crisp_check.toggled.connect(self._crisp_toggled)
            lay.addWidget(self.crisp_check)
            self.solid_check = QCheckBox("Solid panel — ingen genomskinlighet (skarpast text)", body)
            self.solid_check.setChecked(self._glass_pct() == 0)
            self.solid_check.setToolTip("Genomskinliga fönster kan inte få Windows kantutjämnade ClearType-text. "
                                        "Solid panel ger den skarpaste texten; ikonerna på skrivbordet syns då inte genom fönstret.")
            self.solid_check.toggled.connect(self._solid_toggled)
            lay.addWidget(self.solid_check)
            self.auto_check = QCheckBox("Anpassa textstorleken automatiskt efter skärmen", body)
            self.auto_check.setChecked(bool(settings.pref("auto_scale")))
            self.auto_check.setToolTip("Större text på stora skärmar utan Windows-skalning (1440p/4K), något mindre på små. "
                                       "Vanliga skärmar (t.ex. 1080p på 125 %) påverkas inte. Ligger ovanpå reglaget Textstorlek.")
            self.auto_check.toggled.connect(self._auto_toggled)
            lay.addWidget(self.auto_check)
            self.glass_slider.valueChanged.connect(self._sync_solid)
            self.hc_check = QCheckBox("Hög kontrast (svart/vitt, tydliga kanter, text 7:1)", body)
            self.hc_check.setChecked(bool(settings.pref("high_contrast")))
            self.hc_check.toggled.connect(self._hc_toggled)
            lay.addWidget(self.hc_check)
            self.reset_btn = QPushButton("↺ Återställ utseendet", body)
            self.reset_btn.clicked.connect(self.reset)
            lay.addWidget(self.reset_btn)
            lay.addStretch(1)
            area.setWidget(body)
            outer.addWidget(area, 1)
            close = QPushButton("Stäng", self)
            close.setDefault(True)
            close.clicked.connect(self.accept)
            outer.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
            self._timer = QTimer(self)
            self._timer.setSingleShot(True)
            self._timer.setInterval(120)
            self._timer.timeout.connect(self._flush)

        # ---------------------------------------------------------------- hjälp
        def _glass_pct(self) -> int:
            try:
                f = float(self.settings.window_transparency())
            except Exception:
                f = 0.85
            return 0 if f <= 0 else max(0, min(30, round((1.0 - f) * 100)))

        def _slider(self, parent: Any, lay: Any, title: str, lo: int, hi: int, value: int, tip: str) -> Any:
            row = QHBoxLayout()
            lab = QLabel(title, parent)
            lab.setObjectName("thHead")
            val = QLabel(f"{value} %", parent)
            val.setObjectName("thVal")
            row.addWidget(lab, 1)
            row.addWidget(val)
            lay.addLayout(row)
            sl = QSlider(Qt.Orientation.Horizontal, parent)
            sl.setRange(lo, hi)
            sl.setValue(max(lo, min(hi, value)))
            sl.setToolTip(tip)
            sl.setAccessibleName(title)
            sl.valueChanged.connect(lambda v, vl=val: (vl.setText(f"{v} %"), self._timer.start()))
            lay.addWidget(sl)
            return sl, val

        def _flush(self) -> None:
            """Spara och tillämpa sliderns värden (debouncat så ritningen inte hackar)."""
            self.settings.set_pref("bg_dim", self.dim_slider.value())
            self.settings.set_pref("text_scale", self.scale_slider.value())
            if self._on_glass is not None:
                try:
                    self._on_glass(round(1.0 - self.glass_slider.value() / 100.0, 2))
                except Exception as e:  # pragma: no cover
                    logger.warning(f"{LOG_PREFIX} glas: {e}")
            self._on_change()

        def set_preset(self, key: str) -> None:
            self.settings.set_pref("theme_preset", key)
            for k, b in self.preset_buttons.items():
                b.setChecked(k == key)
            self._on_change()

        def _crisp_toggled(self, on: bool) -> None:
            self.settings.set_pref("crisp", bool(on))
            self._on_change()

        def _auto_toggled(self, on: bool) -> None:
            self.settings.set_pref("auto_scale", bool(on))
            self._on_change()

        def _sync_solid(self, v: int) -> None:
            self.solid_check.blockSignals(True)
            self.solid_check.setChecked(int(v) == 0)
            self.solid_check.blockSignals(False)

        def _solid_toggled(self, on: bool) -> None:
            self.glass_slider.setValue(0 if on else 15)     # 0 % glas = helt solid panel; flush sparar och tillämpar

        def _font_changed(self, _i: int = 0) -> None:
            self.settings.set_pref("ui_font", self.font_combo.currentData())
            self._on_change()

        def _hc_toggled(self, on: bool) -> None:
            self.settings.set_pref("high_contrast", bool(on))
            self._on_change()

        def reset(self) -> None:
            self.settings.set_pref("theme_preset", "standard")
            self.settings.set_pref("bg_dim", 0)
            self.settings.set_pref("text_scale", 100)
            self.settings.set_pref("high_contrast", False)
            self.settings.set_pref("ui_font", "standard")
            self.font_combo.blockSignals(True)
            self.font_combo.setCurrentIndex(0)
            self.font_combo.blockSignals(False)
            for k, b in self.preset_buttons.items():
                b.setChecked(k == "standard")
            self.dim_slider.setValue(0)
            self.scale_slider.setValue(100)
            self.hc_check.setChecked(False)
            self.glass_slider.setValue(0)
            self.settings.set_pref("crisp", True)
            self.settings.set_pref("auto_scale", True)
            for cb, val in ((self.crisp_check, True), (self.solid_check, True), (self.auto_check, True)):
                cb.blockSignals(True)
                cb.setChecked(val)
                cb.blockSignals(False)
            self._timer.stop()
            self._flush()


def open_theme_dialog(parent: Any, settings: Any, on_change: Optional[Callable[[], None]] = None,
                      on_glass: Optional[Callable[[float], None]] = None) -> Any:
    """Visa dialogen (icke-modalt: du ser ändringarna i fönstret medan du drar). Returnerar dialogen."""
    if not _QT:
        return None
    dlg = ThemeDialog(parent, settings, on_change, on_glass)
    dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    dlg.show()
    return dlg
