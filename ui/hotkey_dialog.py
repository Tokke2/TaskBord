# -*- coding: utf-8 -*-
"""
Dialog för att välja en global snabbtangent genom att TRYCKA den.

Ingen text att skriva (och därför inga stavfel): klicka i rutan och tryck
t.ex. Ctrl+Alt+N. Dialogen visar direkt om kombinationen duger.
"""

from __future__ import annotations

from typing import Callable, Iterable, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QKeySequenceEdit, QLabel,
    QPushButton, QVBoxLayout,
)

from core.hotkey_combo import (
    normalize_combo, qt_to_combo, validate_global_combo,
)


class HotkeyDialog(QDialog):
    """Tryck-tangenterna-dialog. Resultat i ``chosen`` (None = avbrutet)."""

    def __init__(
        self,
        title: str,
        intro: str,
        current: str,
        default: str,
        taken: Iterable[str] = (),
        allow_disable: bool = False,
        probe: Optional[Callable[[str], Tuple[bool, str]]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(420)
        self._default = normalize_combo(default)
        self._taken = [t for t in taken if t]
        self._probe = probe
        self.chosen: Optional[str] = None
        self.disabled = False

        lay = QVBoxLayout(self)
        lbl = QLabel(intro)
        lbl.setWordWrap(True)
        lay.addWidget(lbl)

        self.edit = QKeySequenceEdit(self)
        self.edit.setMaximumSequenceLength(1)
        self.edit.setClearButtonEnabled(True)
        lay.addWidget(self.edit)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        row = QHBoxLayout()
        self.btn_default = QPushButton(f"Standard ({self._default})")
        self.btn_default.clicked.connect(
            lambda: self.set_combo(self._default)
        )
        row.addWidget(self.btn_default)
        self.btn_disable = QPushButton("Stäng av")
        self.btn_disable.setToolTip("Ingen global snabbtangent alls")
        self.btn_disable.clicked.connect(self._on_disable)
        self.btn_disable.setVisible(bool(allow_disable))
        row.addWidget(self.btn_disable)
        row.addStretch(1)
        lay.addLayout(row)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText("Spara")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Avbryt")
        self.buttons.accepted.connect(self._on_save)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)

        self.edit.keySequenceChanged.connect(self._on_changed)
        self.set_combo(current)

    # -- logik (även anropbar från tester) --------------------------------
    def combo(self) -> str:
        """Kombinationen i rutan i vårt format ('' om tom/ogiltig)."""
        return qt_to_combo(self.edit.keySequence().toString())

    def set_combo(self, combo: str) -> None:
        self.edit.setKeySequence(
            QKeySequence(combo.replace("Win", "Meta")) if combo else QKeySequence()
        )
        self._on_changed()

    def _check(self) -> Tuple[bool, str]:
        combo = self.combo()
        ok, why = validate_global_combo(combo, self._taken)
        if ok and self._probe is not None:
            ok, why = self._probe(combo)
        return ok, why

    def _on_changed(self, *_a) -> None:
        # Qt släpper igenom ett ackord om man trycker flera gånger — behåll
        # alltid bara första tangentslaget
        ok, why = self._check()
        combo = self.combo()
        if not self.edit.keySequence().isEmpty():
            if ok:
                self.status.setText(f"✅ {combo} går bra.")
                self.status.setStyleSheet("color: #2e7d32;")
            else:
                self.status.setText(f"⚠ {why}")
                self.status.setStyleSheet("color: #c62828;")
        else:
            self.status.setText("Klicka i rutan och tryck din kombination.")
            self.status.setStyleSheet("")
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(ok)

    def _on_save(self) -> None:
        ok, _why = self._check()
        if ok:
            self.chosen = self.combo()
            self.accept()

    def _on_disable(self) -> None:
        self.chosen = ""
        self.disabled = True
        self.accept()


def ask_hotkey(
    title: str,
    intro: str,
    current: str,
    default: str,
    taken: Iterable[str] = (),
    allow_disable: bool = False,
    probe: Optional[Callable[[str], Tuple[bool, str]]] = None,
    parent=None,
) -> Optional[str]:
    """Visa dialogen. Returnerar kombination, '' (= stäng av) eller None (avbrutet)."""
    dlg = HotkeyDialog(
        title, intro, current, default, taken, allow_disable, probe, parent
    )
    dlg.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    if dlg.exec() == QDialog.DialogCode.Accepted:
        return dlg.chosen
    return None
