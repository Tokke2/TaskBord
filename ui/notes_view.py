# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""
notes_view.py — fliken 📝 Anteckningar: skapa, redigera, fäst, sök, kopiera och radera egna anteckningar.

Två sidor (så det fungerar även i ett smalt fönster): LISTA (sök + ➕ Ny anteckning + alla anteckningar) och
REDIGERARE (rubrik + text). Redigeraren sparar av sig själv ~0,7 s efter sista tangenttryckningen, när man går
tillbaka, byter flik eller stänger appen (``flush()``) — man behöver aldrig trycka "Spara". Lagringen finns i
core/notes.py (testas utan Qt).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from core import notes as N

logger = logging.getLogger("Ledgebord")
LOG_PREFIX = "[NOTES-UI]"
SAVE_DELAY_MS = 700

try:
    from PySide6.QtCore import QTimer, Qt, Signal
    from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
    from PySide6.QtWidgets import (
        QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
        QPushButton, QStackedWidget, QVBoxLayout, QWidget,
    )
    _QT = True
except ImportError:  # pragma: no cover
    _QT = False
    QWidget = object  # type: ignore[misc,assignment]


def build_stylesheet(is_dark: bool, accent_hex: str, fg: str, muted: str, edge: str, surface: str, px: int = 12) -> str:
    """QSS för vyn (ren sträng-funktion, så färgerna kan kontrastmätas i tester)."""
    from core import tag_colors as _tc
    sel_text = _tc.text_color_for(accent_hex) if _tc.valid_hex(accent_hex) else "#000000"
    return "\n".join([
        f"QLabel#notesHint, QLabel#notesStatus, QLabel#notesEmpty {{ color: {muted}; font-size: {px}px; }}",
        f"QLabel#notesEmpty {{ font-size: {px + 1}px; }}",
        f"QLineEdit#notesSearch, QLineEdit#notesTitle {{ background: {surface}; color: {fg}; border: 1px solid {edge}; "
        f"border-radius: 8px; padding: 6px 8px; font-size: {px + 1}px; }}",
        f"QLineEdit#notesTitle {{ font-weight: 700; font-size: {px + 3}px; }}",
        f"QPlainTextEdit#notesBody {{ background: {surface}; color: {fg}; border: 1px solid {edge}; "
        f"border-radius: 8px; padding: 6px 8px; font-size: {px + 1}px; selection-background-color: {accent_hex}; "
        f"selection-color: {sel_text}; }}",
        f"QListWidget#notesList {{ background: transparent; color: {fg}; border: none; font-size: {px + 1}px; outline: 0; }}",
        f"QListWidget#notesList::item {{ background: {surface}; color: {fg}; border: 1px solid {edge}; "
        f"border-radius: 8px; padding: 8px 10px; margin: 3px 0; }}",
        f"QListWidget#notesList::item:hover {{ border: 1px solid {accent_hex}; }}",
        f"QListWidget#notesList::item:selected {{ background: {accent_hex}; color: {sel_text}; border: 1px solid {accent_hex}; }}",
        f"QPushButton#notesBtn {{ background: {surface}; color: {fg}; border: 1px solid {edge}; border-radius: 8px; "
        f"padding: 5px 10px; font-size: {px}px; font-weight: 600; }}",
        f"QPushButton#notesBtn:hover {{ border: 1px solid {accent_hex}; }}",
        f"QPushButton#notesBtn:checked {{ background: {accent_hex}; color: {sel_text}; border: 1px solid {accent_hex}; }}",
        f"QPushButton#notesNew {{ background: {accent_hex}; color: {sel_text}; border: none; border-radius: 8px; "
        f"padding: 6px 12px; font-size: {px + 1}px; font-weight: 700; }}",
    ])


def _when(iso: str) -> str:
    """'12 okt 14:32' (idag: bara klockslag)."""
    try:
        d = datetime.fromisoformat(iso)
    except ValueError:
        return ""
    mån = ("jan", "feb", "mar", "apr", "maj", "jun", "jul", "aug", "sep", "okt", "nov", "dec")[d.month - 1]
    now = datetime.now(d.tzinfo)
    if d.date() == now.date():
        return f"idag {d:%H:%M}"
    return f"{d.day} {mån}" + (f" {d.year}" if d.year != now.year else "") + f" {d:%H:%M}"


if _QT:

    class NotesView(QWidget):
        changed = Signal()   # något sparades (för t.ex. flikens räknare)

        def __init__(self, store: Any, parent: Optional[QWidget] = None) -> None:
            super().__init__(parent)
            self.store: N.NotesStore = store
            self._cur: Optional[str] = None      # id för anteckningen i redigeraren
            self._loading = False
            self._dirty = False
            self._saved_text = ""
            self._timer = QTimer(self)
            self._timer.setSingleShot(True)
            self._timer.setInterval(SAVE_DELAY_MS)
            self._timer.timeout.connect(self.flush)

            root = QVBoxLayout(self)
            root.setContentsMargins(0, 4, 0, 0)
            self.stack = QStackedWidget(self)
            root.addWidget(self.stack)
            self.stack.addWidget(self._build_list_page())
            self.stack.addWidget(self._build_editor_page())
            self.refresh()

        # ------------------------------------------------------------ sidor
        def _build_list_page(self) -> QWidget:
            page = QWidget(self)
            v = QVBoxLayout(page)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(6)
            top = QHBoxLayout()
            top.setSpacing(6)
            self.search = QLineEdit(page)
            self.search.setObjectName("notesSearch")
            self.search.setPlaceholderText("🔍  Sök i anteckningar…")
            self.search.setClearButtonEnabled(True)
            self.search.textChanged.connect(lambda _t: self.refresh())
            top.addWidget(self.search, 1)
            self.btn_new = QPushButton("➕ Ny anteckning", page)
            self.btn_new.setObjectName("notesNew")
            self.btn_new.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_new.setToolTip("Skapa en ny anteckning (Ctrl+N när fliken visas)")
            self.btn_new.clicked.connect(self.new_note)
            top.addWidget(self.btn_new)
            v.addLayout(top)
            self.hint = QLabel("", page)
            self.hint.setObjectName("notesHint")
            v.addWidget(self.hint)
            self.list = QListWidget(page)
            self.list.setObjectName("notesList")
            self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
            self.list.itemActivated.connect(self._on_item)
            self.list.itemClicked.connect(self._on_item)
            v.addWidget(self.list, 1)
            self.empty = QLabel("", page)
            self.empty.setObjectName("notesEmpty")
            self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.empty.setWordWrap(True)
            v.addWidget(self.empty)
            return page

        def _build_editor_page(self) -> QWidget:
            page = QWidget(self)
            v = QVBoxLayout(page)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(6)
            bar = QHBoxLayout()
            bar.setSpacing(6)
            self.btn_back = QPushButton("← Alla anteckningar", page)
            self.btn_back.setObjectName("notesBtn")
            self.btn_back.setToolTip("Tillbaka till listan (Esc) — anteckningen är redan sparad")
            self.btn_back.clicked.connect(self.show_list)
            bar.addWidget(self.btn_back)
            bar.addStretch(1)
            self.btn_pin = QPushButton("📌 Fäst", page)
            self.btn_pin.setObjectName("notesBtn")
            self.btn_pin.setCheckable(True)
            self.btn_pin.setToolTip("Fästa anteckningar ligger överst i listan")
            self.btn_pin.clicked.connect(self._on_pin)
            bar.addWidget(self.btn_pin)
            self.btn_copy = QPushButton("📋 Kopiera", page)
            self.btn_copy.setObjectName("notesBtn")
            self.btn_copy.setToolTip("Kopiera rubrik och text till urklipp")
            self.btn_copy.clicked.connect(self.copy_current)
            bar.addWidget(self.btn_copy)
            self.btn_del = QPushButton("🗑 Radera", page)
            self.btn_del.setObjectName("notesBtn")
            self.btn_del.setToolTip("Radera anteckningen (du får en kontrollfråga)")
            self.btn_del.clicked.connect(self.delete_current)
            bar.addWidget(self.btn_del)
            v.addLayout(bar)
            self.title_edit = QLineEdit(page)
            self.title_edit.setObjectName("notesTitle")
            self.title_edit.setPlaceholderText("Rubrik (valfri)")
            self.title_edit.setMaxLength(N.TITLE_MAX)
            self.title_edit.textChanged.connect(self._on_edit)
            v.addWidget(self.title_edit)
            self.body_edit = QPlainTextEdit(page)
            self.body_edit.setObjectName("notesBody")
            self.body_edit.setPlaceholderText("Skriv här … allt sparas automatiskt.")
            self.body_edit.textChanged.connect(self._on_edit)
            v.addWidget(self.body_edit, 1)
            self.status = QLabel("", page)
            self.status.setObjectName("notesStatus")
            v.addWidget(self.status)
            for seq in ("Ctrl+N",):
                QShortcut(QKeySequence(seq), self, activated=self.new_note).setContext(
                    Qt.ShortcutContext.WidgetWithChildrenShortcut)
            QShortcut(QKeySequence("Esc"), page, activated=self.show_list).setContext(
                Qt.ShortcutContext.WidgetWithChildrenShortcut)
            return page

        # ------------------------------------------------------------ lista
        def refresh(self) -> None:
            """Bygg om listan (behåller markeringen)."""
            self.store.reload_if_changed()
            q = self.search.text() if hasattr(self, "search") else ""
            items = self.store.notes(q)
            total = self.store.count()
            self.list.blockSignals(True)
            self.list.clear()
            for n in items:
                head = ("📌 " if n["pinned"] else "") + N.title_of(n)
                prev = N.preview_of(n)
                it = QListWidgetItem(f"{head}\n{prev}\n{_when(n['updated'])}" if prev else f"{head}\n{_when(n['updated'])}")
                it.setData(Qt.ItemDataRole.UserRole, n["id"])
                it.setToolTip(N.title_of(n) + (f"\n\n{n['body'][:600]}" if n["body"] else ""))
                self.list.addItem(it)
                if n["id"] == self._cur:
                    self.list.setCurrentItem(it)
            self.list.blockSignals(False)
            if total == 0:
                self.empty.setText("Inga anteckningar än.\nKlicka på ➕ Ny anteckning för att skriva din första.")
            elif not items:
                self.empty.setText("Ingen anteckning matchar sökningen.")
            self.empty.setVisible(not items)
            self.list.setVisible(bool(items))
            self.hint.setText(f"{total} anteckning{'ar' if total != 1 else ''}" + (f" — visar {len(items)}" if q.strip() else "")
                              if total else "")

        def _on_item(self, item: Any) -> None:
            nid = item.data(Qt.ItemDataRole.UserRole)
            if nid:
                self.open_note(str(nid))

        # ------------------------------------------------------------ redigerare
        def new_note(self) -> None:
            self.flush()
            try:
                n = self.store.add("", "")
            except ValueError as e:
                QMessageBox.warning(self, "Anteckningar", str(e))
                return
            self.search.clear()
            self.open_note(n["id"], focus_title=True)
            self.changed.emit()

        def open_note(self, nid: str, focus_title: bool = False) -> None:
            self.flush()
            n = self.store.get(nid)
            if n is None:
                self.refresh()
                return
            self._cur = nid
            self._loading = True
            self.title_edit.setText(n["title"])
            self.body_edit.setPlainText(n["body"])
            self.btn_pin.setChecked(bool(n["pinned"]))
            self._loading = False
            self._dirty = False
            self._saved_text = n["updated"]
            self.status.setText(f"Skapad {_when(n['created'])} · ändrad {_when(n['updated'])} · sparas automatiskt")
            self.stack.setCurrentIndex(1)
            (self.title_edit if focus_title else self.body_edit).setFocus()

        def show_list(self) -> None:
            self.flush()
            self._cur = None
            self.stack.setCurrentIndex(0)
            self.refresh()

        def _on_edit(self) -> None:
            if self._loading or self._cur is None:
                return
            self._dirty = True
            self.status.setText("Sparar …")
            self._timer.start()

        def flush(self) -> bool:
            """Spara det som skrivits NU (om något är osparat). Anropas även vid flikbyte och nedstängning."""
            self._timer.stop()
            if not self._dirty or self._cur is None:
                return True
            nid = self._cur
            n = self.store.update(nid, title=self.title_edit.text(), body=self.body_edit.toPlainText())
            self._dirty = False
            if n is None:  # raderad av något annat — skapa om så texten inte försvinner
                created = self.store.add(self.title_edit.text(), self.body_edit.toPlainText())
                self._cur = created["id"]
                n = created
            self.status.setText(f"✓ Sparat {datetime.now():%H:%M:%S}")
            self.changed.emit()
            return True

        def _on_pin(self) -> None:
            if self._cur is None:
                return
            self.flush()
            self.store.update(self._cur, pinned=self.btn_pin.isChecked())
            self.changed.emit()

        def copy_current(self) -> None:
            if self._cur is None:
                return
            t = self.title_edit.text().strip()
            b = self.body_edit.toPlainText()
            try:
                QGuiApplication.clipboard().setText((t + "\n\n" if t else "") + b)
                self.status.setText("✓ Kopierat till urklipp")
            except Exception as e:  # pragma: no cover
                logger.warning(f"{LOG_PREFIX} kunde inte kopiera: {e}")

        def delete_current(self) -> None:
            if self._cur is None:
                return
            self.flush()
            n = self.store.get(self._cur) or {}
            r = QMessageBox.question(
                self, "Radera anteckning", f"Radera “{N.title_of(n)}”?\nDet går inte att ångra (men den finns kvar i äldre backuper).",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if r != QMessageBox.StandardButton.Yes:
                return
            self.store.delete(self._cur)
            self._cur = None
            self._dirty = False
            self.stack.setCurrentIndex(0)
            self.refresh()
            self.changed.emit()

        # ------------------------------------------------------------ övrigt
        def hideEvent(self, event: Any) -> None:  # type: ignore[override]
            self.flush()
            super().hideEvent(event)

        def apply_theme(self, is_dark: bool, accent_hex: str, fg: str, muted: str, edge: str, surface: str, px: int = 12) -> None:
            self.setStyleSheet(build_stylesheet(is_dark, accent_hex, fg, muted, edge, surface, px))

        def current_id(self) -> Optional[str]:
            return self._cur

else:  # pragma: no cover
    class NotesView:  # type: ignore[no-redef]
        pass
