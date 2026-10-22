# -*- coding: utf-8 -*-
"""
backup_dialog.py — NY v8 (2026-10-12): 💾 Backup av uppgifter (dialog).

Skapa backup nu, spara en kopia någon annanstans (USB, moln-mapp), och återställ
från en backup. Själva logiken ligger i core/tasks_backup.py (testad utan Qt).
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("Ledgebord")
LOG_PREFIX = "[BACKUP-UI]"

from core import tasks_backup as tb  # noqa: E402

try:
    from PySide6.QtCore import Qt, QUrl
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import (
        QDialog, QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
        QMessageBox, QPushButton, QVBoxLayout, QWidget,
    )
    _QT = True
except ImportError:  # pragma: no cover
    _QT = False
    QWidget = Any  # type: ignore[misc,assignment]


def _human(n: int) -> str:
    return f"{n} B" if n < 1024 else f"{n / 1024:.0f} kB" if n < 1048576 else f"{n / 1048576:.1f} MB"


def _info(parent: Any, title: str, text: str, warn: bool = False) -> None:
    (QMessageBox.warning if warn else QMessageBox.information)(parent, title, text)


if _QT:

    class BackupDialog(QDialog):
        def __init__(self, parent: Optional[QWidget] = None, store: Any = None) -> None:
            super().__init__(parent)
            self.store = store
            self.setWindowTitle("💾 Backup av uppgifter")
            self.setModal(True)
            self.setMinimumSize(560, 440)
            rot = QVBoxLayout(self)
            rot.setContentsMargins(16, 14, 16, 12)
            rot.setSpacing(8)
            self.info = QLabel(self)
            self.info.setWordWrap(True)
            self.info.setTextFormat(Qt.TextFormat.RichText)
            rot.addWidget(self.info)

            rad = QHBoxLayout()
            for text, fn in (("💾 Säkerhetskopiera nu", self._nu), ("📁 Spara kopia som…", self._spara_som)):
                b = QPushButton(text, self)
                b.clicked.connect(fn)
                rad.addWidget(b)
            rad.addStretch(1)
            rot.addLayout(rad)

            rot.addWidget(QLabel("<b>Tidigare backuper</b> (nyast först):", self))
            self.lista = QListWidget(self)
            self.lista.itemDoubleClicked.connect(lambda _i: self._aterstall_vald())
            rot.addWidget(self.lista, 1)

            rad2 = QHBoxLayout()
            for text, fn in (("♻ Återställ vald", self._aterstall_vald),
                             ("📂 Återställ från fil…", self._aterstall_fil),
                             ("🗂 Öppna mappen", self._oppna_mapp)):
                b = QPushButton(text, self)
                b.clicked.connect(fn)
                rad2.addWidget(b)
            rad2.addStretch(1)
            st = QPushButton("Stäng", self)
            st.clicked.connect(self.accept)
            rad2.addWidget(st)
            rot.addLayout(rad2)
            self._fyll()

        def _fyll(self) -> None:
            self.lista.clear()
            for b in tb.list_backups(self.store):
                t = datetime.fromtimestamp(b["mtime"]).strftime("%Y-%m-%d %H:%M")
                extra = ("  (före återställning)" if "fore-aterstallning" in b["name"]
                         else "  (automatisk)" if b.get("auto") else "")
                it = QListWidgetItem(f"{t}  —  {_human(b['size'])}{extra}")
                it.setData(Qt.ItemDataRole.UserRole, b["path"])
                self.lista.addItem(it)
            try:
                n = len(self.store.active_tasks())
                a = len(self.store.archive_tasks())
            except Exception:
                n = a = 0
            self.info.setText(
                f"Du har <b>{n}</b> aktiva och <b>{a}</b> arkiverade uppgifter. "
                f"En backup är en ZIP-fil med allt. Standardmapp:<br><code>{tb.default_dir(self.store)}</code><br>"
                "<b>Automatisk backup:</b> uppgifter och inställningar (fönsterläge) kopieras även "
                f"vid avslut och var 5:e minut till <code>{tb.auto_dir()}</code>. "
                "Försvinner uppgifterna (<code>js/</code>) vid en uppdatering läses de in därifrån vid nästa start.<br>"
                "Tips: använd <i>Spara kopia som…</i> för att lägga en kopia på ett USB-minne eller i en molnmapp."
            )

        def _nu(self) -> None:
            try:
                p = tb.create_backup(self.store)
                i = tb.inspect_backup(p)
                _info(self, "💾 Backup klar", f"{i['active']} aktiva och {i['archive']} arkiverade uppgifter sparades i:\n{p}")
            except tb.TasksBackupError as e:
                _info(self, "💾 Backup misslyckades", str(e), warn=True)
            self._fyll()

        def _spara_som(self) -> None:
            namn = f"{tb.PREFIX}{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
            fil, _ = QFileDialog.getSaveFileName(self, "Spara backup som", str(Path.home() / namn), "ZIP (*.zip)")
            if not fil:
                return
            if not fil.lower().endswith(".zip"):
                fil += ".zip"
            try:
                p = tb.create_backup(self.store, dest=fil)
                _info(self, "💾 Backup klar", f"Kopian sparades i:\n{p}")
            except tb.TasksBackupError as e:
                _info(self, "💾 Backup misslyckades", str(e), warn=True)

        def _aterstall(self, path: str) -> None:
            try:
                i = tb.inspect_backup(path)
            except tb.TasksBackupError as e:
                _info(self, "♻ Kan inte återställa", str(e), warn=True)
                return
            när = i["created"][:16].replace("T", " ") if i["created"] else "okänd tid"
            svar = QMessageBox.question(
                self, "♻ Återställ uppgifter",
                f"Backupen ({när}) innehåller {i['active']} aktiva och {i['archive']} arkiverade uppgifter.\n\n"
                "Dina nuvarande uppgifter ersätts. Först sparas en säkerhetskopia av nuläget, "
                "så du kan ångra dig.\n\nÅterställa?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if svar != QMessageBox.StandardButton.Yes:
                return
            try:
                r = tb.restore_backup(self.store, path)
                _info(self, "♻ Återställt", f"{r['active']} aktiva och {r['archive']} arkiverade uppgifter är tillbaka."
                      + (f"\n\n{r['archive_kept']} nyare arkiverade uppgifter behölls (arkivet är historik som aldrig tas bort)."
                         if r.get("archive_kept") else "")
                      + (f"\n\nNuläget före återställningen finns sparat i:\n{r['safety']}" if r.get("safety") else ""))
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} återställning misslyckades: {e}", exc_info=True)
                _info(self, "♻ Återställning misslyckades", str(e), warn=True)
            self._fyll()

        def _aterstall_vald(self) -> None:
            it = self.lista.currentItem()
            if it is None:
                _info(self, "♻ Återställ", "Välj en backup i listan först.")
                return
            self._aterstall(str(it.data(Qt.ItemDataRole.UserRole)))

        def _aterstall_fil(self) -> None:
            fil, _ = QFileDialog.getOpenFileName(self, "Välj backup", str(tb.default_dir(self.store)), "ZIP (*.zip)")
            if fil:
                self._aterstall(fil)

        def _oppna_mapp(self) -> None:
            d = tb.default_dir(self.store)
            d.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))


def open_backup_dialog(parent: Optional[QWidget] = None, store: Any = None) -> bool:
    """Visa backup-dialogen. False om Qt/store saknas."""
    if not _QT or store is None:
        return False
    try:
        BackupDialog(parent, store=store).exec()
        return True
    except Exception as e:  # pragma: no cover
        logger.error(f"{LOG_PREFIX} dialogen misslyckades: {e}", exc_info=True)
        return False
