# -*- coding: utf-8 -*-
"""
rules_dialog.py — NY v8 (2026-10-12): hantera och köra regler.

Dialogen visar reglerna, låter dig lägga till/ändra/ta bort/slå av dem och har
knappen ▶ Kör alla regler nu. All logik ligger i core/rules.py (testad utan Qt).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("TaskBord")
LOG_PREFIX = "[RULES-UI]"

from core import rules as rl  # noqa: E402

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit,
        QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
        QPushButton, QSpinBox, QVBoxLayout, QWidget,
    )
    _QT_AVAILABLE = True
except ImportError:  # pragma: no cover
    _QT_AVAILABLE = False
    QWidget = Any  # type: ignore[misc,assignment]


def _data_dir(store: Any = None, settings: Any = None, data_dir: Any = None):
    from ui.google_calendar_dialog import _resolve_data_dir
    return _resolve_data_dir(store, settings, data_dir)


def last_run_text(ruleset: "rl.RuleSet") -> str:
    """T.ex. “Senast körd: 2026-10-12 14:03 (timkörning, 2 ändrade)”."""
    t = ruleset.last_run()
    if t is None:
        return "Reglerna har inte körts ännu."
    res = ruleset.last_result()
    namn = {"manual": "manuell", "hourly": "timkörning"}.get(res.get("trigger"), "körning")
    extra = f", {res.get('changed', 0)} ändrade" if res else ""
    return f"Senast körd: {t.astimezone().strftime('%Y-%m-%d %H:%M')} ({namn}{extra})"


def details_text(resultat: Dict[str, Any], max_rows: int = 40) -> str:
    rader = [f"• {c['title'][:50]} — {c['rule']}: {', '.join(c['what'])}"
             for c in resultat.get("changes", [])[:max_rows]]
    mer = len(resultat.get("changes", [])) - max_rows
    if mer > 0:
        rader.append(f"… och {mer} till")
    return "\n".join(rader)


def run_rules_with_message(
    parent: Optional[QWidget] = None,
    store: Any = None,
    settings: Any = None,
    data_dir: Any = None,
    trigger: str = "manual",
) -> Optional[Dict[str, Any]]:
    """Kör alla regler nu och visa resultatet. Används av knappen i widgeten och tray-menyn."""
    if store is None:
        return None
    try:
        rs = rl.load_rules(_data_dir(store, settings, data_dir))
        res = rl.run_rules(store, rs, trigger=trigger)
    except Exception as e:
        logger.warning(f"{LOG_PREFIX} körning misslyckades: {type(e).__name__}: {e}", exc_info=True)
        return None
    if _QT_AVAILABLE:
        try:
            box = QMessageBox(parent)
            box.setIcon(QMessageBox.Icon.Information)
            box.setWindowTitle("▶ Regler körda")
            box.setText(rl.summarize(res))
            det = details_text(res)
            if det:
                box.setDetailedText(det)
            box.exec()
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} resultatruta misslyckades: {e}")
    return res


if _QT_AVAILABLE:

    class RuleEditDialog(QDialog):
        """Skapa eller ändra EN regel."""

        def __init__(self, rule: Optional[Dict[str, Any]] = None,
                     parent: Optional[QWidget] = None) -> None:
            super().__init__(parent)
            self._rule = rule or {}
            self.result_rule: Optional[Dict[str, Any]] = None
            self.setWindowTitle("Regel")
            self.setModal(True)
            self.setMinimumWidth(560)
            rot = QVBoxLayout(self)
            rot.setSpacing(8)

            self.namn = QLineEdit(self._rule.get("name", ""), self)
            self.namn.setPlaceholderText("Namn, t.ex. “Fakturor är viktiga”")
            rot.addWidget(QLabel("Namn:", self))
            rot.addWidget(self.namn)

            rad = QHBoxLayout()
            rad.addWidget(QLabel("Villkor — regeln gäller när", self))
            self.mode = QComboBox(self)
            self.mode.addItem("alla villkor stämmer", "all")
            self.mode.addItem("något villkor stämmer", "any")
            self.mode.setCurrentIndex(0 if self._rule.get("match", "all") == "all" else 1)
            rad.addWidget(self.mode)
            rad.addStretch(1)
            rot.addLayout(rad)

            self.cond_box = QVBoxLayout()
            rot.addLayout(self.cond_box)
            self._cond_rows: List[Dict[str, Any]] = []
            for c in self._rule.get("conditions") or [{}]:
                self._add_cond(c)
            btn_add = QPushButton("➕ Lägg till villkor", self)
            btn_add.clicked.connect(lambda: self._add_cond({}))
            rot.addWidget(btn_add, 0, Qt.AlignmentFlag.AlignLeft)

            self.mail_only = QCheckBox("Bara uppgifter som kommit från mail", self)
            self.mail_only.setChecked(bool(self._rule.get("mail_only")))
            rot.addWidget(self.mail_only)

            rot.addWidget(QLabel("<b>Då ska appen:</b>", self))
            a = self._rule.get("actions") or {}
            r1 = QHBoxLayout()
            r1.addWidget(QLabel("Sätta prioritet:", self))
            self.prio = QComboBox(self)
            self.prio.addItem("(ändra inte)", "")
            for k, t in (("high", "Hög"), ("medium", "Normal"), ("low", "Låg"), ("none", "Ingen")):
                self.prio.addItem(t, k)
            self.prio.setCurrentIndex(max(0, self.prio.findData(a.get("priority", ""))))
            r1.addWidget(self.prio)
            r1.addStretch(1)
            rot.addLayout(r1)

            r2 = QHBoxLayout()
            r2.addWidget(QLabel("Lägga till taggar:", self))
            self.taggar = QLineEdit(", ".join(a.get("add_tags") or []), self)
            self.taggar.setPlaceholderText("kommaseparerade, t.ex. jobb, ekonomi")
            r2.addWidget(self.taggar, 1)
            rot.addLayout(r2)

            r3 = QHBoxLayout()
            self.chk_due = QCheckBox("Sätta förfallodatum om det saknas: om", self)
            self.chk_due.setChecked(a.get("due_in_days") is not None)
            r3.addWidget(self.chk_due)
            self.dagar = QSpinBox(self)
            self.dagar.setRange(0, 3650)
            self.dagar.setValue(int(a.get("due_in_days") or 2))
            r3.addWidget(self.dagar)
            r3.addWidget(QLabel("dagar", self))
            r3.addStretch(1)
            rot.addLayout(r3)

            self.pin = QCheckBox("Nåla fast uppgiften", self)
            self.pin.setChecked(bool(a.get("pin")))
            rot.addWidget(self.pin)

            self.aktiv = QCheckBox("Regeln är påslagen", self)
            self.aktiv.setChecked(bool(self._rule.get("enabled", True)))
            rot.addWidget(self.aktiv)

            self.fel = QLabel("", self)
            self.fel.setStyleSheet("color: #dc2626;")
            self.fel.setWordWrap(True)
            rot.addWidget(self.fel)

            nav = QHBoxLayout()
            nav.addStretch(1)
            avbryt = QPushButton("Avbryt", self)
            avbryt.clicked.connect(self.reject)
            nav.addWidget(avbryt)
            ok = QPushButton("Spara regel", self)
            ok.setDefault(True)
            ok.clicked.connect(self._spara)
            nav.addWidget(ok)
            rot.addLayout(nav)

        def _add_cond(self, c: Dict[str, Any]) -> None:
            rad = QHBoxLayout()
            f = QComboBox(self)
            for k, t in rl.FIELDS.items():
                f.addItem(t, k)
            f.setCurrentIndex(max(0, f.findData(c.get("field", "subject"))))
            o = QComboBox(self)
            for k, t in rl.OPS.items():
                o.addItem(t, k)
            o.setCurrentIndex(max(0, o.findData(c.get("op", "contains"))))
            v = QLineEdit(c.get("value", ""), self)
            v.setPlaceholderText("text att leta efter")
            x = QPushButton("✕", self)
            x.setFixedWidth(28)
            for w in (f, o):
                rad.addWidget(w)
            rad.addWidget(v, 1)
            rad.addWidget(x)
            post = {"layout": rad, "f": f, "o": o, "v": v, "x": x}
            self._cond_rows.append(post)
            self.cond_box.addLayout(rad)
            x.clicked.connect(lambda: self._ta_bort_cond(post))

        def _ta_bort_cond(self, post: Dict[str, Any]) -> None:
            if len(self._cond_rows) <= 1:
                return
            self._cond_rows.remove(post)
            for w in (post["f"], post["o"], post["v"], post["x"]):
                w.setParent(None)
                w.deleteLater()
            self.cond_box.removeItem(post["layout"])

        def _spara(self) -> None:
            raw = {
                "id": self._rule.get("id") or rl.new_rule_id(),
                "name": self.namn.text(),
                "enabled": self.aktiv.isChecked(),
                "match": self.mode.currentData(),
                "mail_only": self.mail_only.isChecked(),
                "conditions": [{"field": p["f"].currentData(), "op": p["o"].currentData(),
                                "value": p["v"].text()} for p in self._cond_rows],
                "actions": {
                    "priority": self.prio.currentData() or "",
                    "add_tags": self.taggar.text(),
                    "due_in_days": self.dagar.value() if self.chk_due.isChecked() else None,
                    "pin": self.pin.isChecked(),
                },
            }
            rule, problems = rl.normalize_rule(raw)
            if rule is None:
                self.fel.setText("• " + "\n• ".join(problems))
                return
            self.result_rule = rule
            self.accept()

    class RulesDialog(QDialog):
        """Alla regler på ett ställe + ▶ Kör alla regler nu."""

        def __init__(self, parent: Optional[QWidget] = None, store: Any = None,
                     settings: Any = None, data_dir: Any = None) -> None:
            super().__init__(parent)
            self.store = store
            self.data_dir = _data_dir(store, settings, data_dir)
            self.ruleset = rl.load_rules(self.data_dir)
            self.setWindowTitle("📏 Regler")
            self.setModal(True)
            self.setMinimumSize(620, 480)
            rot = QVBoxLayout(self)
            rot.setContentsMargins(16, 14, 16, 12)
            rot.setSpacing(8)

            info = QLabel(
                "Reglerna körs <b>automatiskt 1 gång per timme</b> och direkt på "
                "<b>varje nytt mail</b> som kommer in (Thunderbird-tillägget och "
                "inkorgsmappen bevakas hela tiden). Ordningen avgör: för prioritet "
                "vinner den sista matchande regeln.", self)
            info.setWordWrap(True)
            info.setTextFormat(Qt.TextFormat.RichText)
            rot.addWidget(info)

            self.lista = QListWidget(self)
            self.lista.itemChanged.connect(self._on_toggle)
            self.lista.itemDoubleClicked.connect(lambda _i: self._redigera())
            rot.addWidget(self.lista, 1)

            rad = QHBoxLayout()
            for text, fn in (("➕ Ny regel", self._ny), ("✏ Ändra", self._redigera),
                             ("🗑 Ta bort", self._ta_bort), ("▲", lambda: self._flytta(-1)),
                             ("▼", lambda: self._flytta(1))):
                b = QPushButton(text, self)
                b.clicked.connect(fn)
                rad.addWidget(b)
            rad.addStretch(1)
            rot.addLayout(rad)

            self.status = QLabel("", self)
            rot.addWidget(self.status)
            self.btn_kor = QPushButton("▶ Kör alla regler nu", self)
            self.btn_kor.setStyleSheet("font-weight: 700; padding: 6px;")
            self.btn_kor.clicked.connect(self._kor)
            rot.addWidget(self.btn_kor)
            self.logg = QPlainTextEdit(self)
            self.logg.setReadOnly(True)
            self.logg.setMaximumHeight(110)
            rot.addWidget(self.logg)

            stang = QHBoxLayout()
            stang.addStretch(1)
            b = QPushButton("Stäng", self)
            b.clicked.connect(self.accept)
            stang.addWidget(b)
            rot.addLayout(stang)
            self._fyll()

        def _fyll(self) -> None:
            self.ruleset.load()
            self.lista.blockSignals(True)
            self.lista.clear()
            for r in self.ruleset.all():
                it = QListWidgetItem(f"{r['name']}\n    {rl.describe_rule(r)}")
                it.setData(Qt.ItemDataRole.UserRole, r["id"])
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(Qt.CheckState.Checked if r["enabled"] else Qt.CheckState.Unchecked)
                self.lista.addItem(it)
            self.lista.blockSignals(False)
            self.status.setText(last_run_text(self.ruleset))
            self.btn_kor.setEnabled(bool(self.ruleset.enabled()) and self.store is not None)

        def _valt_id(self) -> Optional[str]:
            it = self.lista.currentItem()
            return str(it.data(Qt.ItemDataRole.UserRole)) if it else None

        def _on_toggle(self, it: QListWidgetItem) -> None:
            self.ruleset.set_enabled(str(it.data(Qt.ItemDataRole.UserRole)),
                                     it.checkState() == Qt.CheckState.Checked)
            self.btn_kor.setEnabled(bool(self.ruleset.enabled()) and self.store is not None)

        def _ny(self) -> None:
            d = RuleEditDialog(None, self)
            if d.exec() == QDialog.DialogCode.Accepted and d.result_rule:
                self.ruleset.upsert(d.result_rule)
                self._fyll()

        def _redigera(self) -> None:
            rid = self._valt_id()
            rule = self.ruleset.get(rid) if rid else None
            if not rule:
                return
            d = RuleEditDialog(rule, self)
            if d.exec() == QDialog.DialogCode.Accepted and d.result_rule:
                self.ruleset.upsert(d.result_rule)
                self._fyll()

        def _ta_bort(self) -> None:
            rid = self._valt_id()
            if not rid:
                return
            if QMessageBox.question(
                self, "Ta bort regel", "Vill du ta bort regeln?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                self.ruleset.remove(rid)
                self._fyll()

        def _flytta(self, delta: int) -> None:
            rid = self._valt_id()
            if rid and self.ruleset.move(rid, delta):
                self._fyll()
                for i in range(self.lista.count()):
                    if self.lista.item(i).data(Qt.ItemDataRole.UserRole) == rid:
                        self.lista.setCurrentRow(i)

        def _kor(self) -> None:
            res = rl.run_rules(self.store, self.ruleset, trigger="manual")
            self.logg.setPlainText(
                f"{datetime.now().strftime('%H:%M:%S')}  {rl.summarize(res)}\n" + details_text(res))
            self.status.setText(last_run_text(self.ruleset))


def open_rules_dialog(parent: Optional[QWidget] = None, store: Any = None,
                      settings: Any = None, data_dir: Any = None) -> bool:
    """Visa regeldialogen. False om Qt saknas."""
    if not _QT_AVAILABLE:  # pragma: no cover
        return False
    try:
        RulesDialog(parent, store=store, settings=settings, data_dir=data_dir).exec()
        return True
    except Exception as e:  # pragma: no cover
        logger.error(f"{LOG_PREFIX} regeldialogen misslyckades: {e}", exc_info=True)
        return False
