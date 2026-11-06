# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""
ui/widget_parts/extras.py — belopp (💰), anteckningar (📝) och klickbara telefonnummer/adresser (📞/📍) på uppgifter.

Del av TodoWidget. Beloppet sparas i ören (``amount_cents``), anteckningen som text (``note``). Telefonnummer och
adresser hittas i titel + anteckning (core/contacts.py) och visas som chips: telefon → meny (ring, SMS, kopiera),
adress → Google Maps (högerklick: vägbeskrivning, kopiera). Summan av beloppen i den aktuella vyn visas som en rad
ovanför listan; klick ger fördelning per månad och tagg.
"""
from __future__ import annotations

from typing import Any, Dict, List

from ui.widget_base import *  # noqa: F401,F403
from ui.widget_atoms import *  # noqa: F401,F403

from core import amounts as _amounts
from core import contacts as _contacts
from core.payment_plan import format_amount, parse_amount

try:
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QCursor, QDesktopServices, QGuiApplication
    from PySide6.QtWidgets import QInputDialog, QMenu, QMessageBox
except ImportError:  # pragma: no cover
    QUrl = QCursor = QDesktopServices = QGuiApplication = QInputDialog = QMenu = QMessageBox = None  # type: ignore


class ExtrasMixin:
    """Belopp, anteckningar och klickbara kontaktuppgifter."""

    # ------------------------------------------------------------ chips på kortet
    def _add_extra_rows(self, container: Any, vbox: Any, task: Dict[str, Any], archived: bool) -> None:
        """Rader med 💰 belopp, 📝 anteckning, 📞 telefonnummer och 📍 adresser (bara det som finns)."""
        tid = str(task.get("id", ""))
        chips: List[Any] = []
        amount = _amounts.task_amount(task)
        if amount:
            c = LinkChip(f"💰 {format_amount(amount)}", tid, "amount",
                         "Belopp — klicka för att ändra (tomt = ta bort)", container)
            c.clicked.connect(lambda _k, t=tid: self._edit_amount(t))
            c.menu_requested.connect(lambda _k, _p, t=tid: self._edit_amount(t))
            chips.append(c)
        note = str(task.get("note") or "").strip()
        if note:
            first = next((ln.strip() for ln in note.splitlines() if ln.strip()), "")
            more = "  (+ fler rader)" if len([ln for ln in note.splitlines() if ln.strip()]) > 1 else ""
            tip = note if len(note) <= 700 else note[:700].rstrip() + "…"
            c = LinkChip(f"📝 {first}", tid, "note", f"{tip}\n\nKlicka: redigera anteckningen", container)
            if more:
                c.setText(c.text() + " +")
            c.clicked.connect(lambda _k, t=tid: self._edit_note(t))
            c.menu_requested.connect(lambda _k, _p, t=tid: self._edit_note(t))
            chips.append(c)
        text = f"{task.get('title') or ''}\n{note}"
        for ph in _contacts.find_phones(text):
            c = LinkChip(f"📞 {ph['text']}", ph["tel"], "phone",
                         f"{ph['text']}\n\nKlicka: ring, skicka SMS eller kopiera numret", container)
            c.clicked.connect(lambda _k, p=dict(ph): self._phone_menu(p, None))
            c.menu_requested.connect(lambda _k, pos, p=dict(ph): self._phone_menu(p, pos))
            chips.append(c)
        for ad in _contacts.find_addresses(text):
            c = LinkChip(f"📍 {ad['text']}", ad["text"], "address",
                         f"{ad['text']}\n\nKlicka: öppna i Google Maps · Högerklick: vägbeskrivning, kopiera", container)
            c.MAX_CHARS = 40
            c.clicked.connect(lambda _k, a=dict(ad): self._open_url(_contacts.maps_url(a["text"])))
            c.menu_requested.connect(lambda _k, pos, a=dict(ad): self._address_menu(a, pos))
            chips.append(c)
        for chip in chips:
            row = QHBoxLayout()
            row.setSpacing(6)
            row.addSpacing(34)
            row.addWidget(chip)
            row.addStretch(1)
            vbox.addLayout(row)

    @staticmethod
    def _extra_state(task: Dict[str, Any]) -> tuple:
        """Det som ändrar kortets extrarader (ingår i kortets cache-nyckel)."""
        return (_amounts.task_amount(task), str(task.get("note") or ""))

    # ---------------------------------------------------------------- belopp
    def _edit_amount(self, task_id: str) -> None:
        try:
            get_throttle().notify_activity()
            task = self.store.find_task(task_id) or {}
            cur = _amounts.task_amount(task)
            start = format_amount(cur).replace("\u00a0", " ") if cur else ""
            while True:
                text, ok = QInputDialog.getText(
                    self, "💰 Belopp",
                    "Belopp i kronor (t.ex. 4 000 eller 1 234,50). Tomt = ta bort beloppet:",
                    text=start)
                if not ok:
                    return
                if not str(text).strip():
                    self.store.set_amount(task_id, None)
                    return
                cents = parse_amount(text)
                if cents:
                    self.store.set_amount(task_id, cents)
                    return
                QMessageBox.warning(self, "💰 Belopp", "Det där ser inte ut som ett belopp. Skriv t.ex. 4000 eller 1 234,50.")
                start = str(text)
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} _edit_amount: {e}")

    def _update_amount_summary(self, tasks: List[Dict[str, Any]]) -> None:
        """Raden ovanför listan: summan i den vy som visas (söker/filtrerar du så följer summan med)."""
        btn = getattr(self, "amount_summary", None)
        if btn is None:
            return
        try:
            s = _amounts.summarize(tasks)
            line = _amounts.summary_line(s)
            btn.setVisible(bool(line))
            btn.setText(line)
            if line:
                btn.setToolTip("Summan av beloppen på uppgifterna som visas nu "
                               "(sök eller klicka på en tagg för att begränsa).\nKlicka: fördelning per månad och tagg.")
        except Exception as e:
            logger.debug(f"{LOG_PREFIX} _update_amount_summary: {e}")

    def _show_amount_overview(self) -> None:
        try:
            get_throttle().notify_activity()
            from ui.extras_dialogs import AmountOverviewDialog
            q = (getattr(self, "_current_filter", "") or "").lower().strip()
            active = self.store.active_tasks_filtered(query=q, sort_by="pinned_first") if q else self.store.active_tasks()
            active = [t for t in active if not _is_snoozed(t)] if q else list(active)
            arch = _amounts.summarize_archive(self.store.archive_tasks())
            scope = f"Vy: sökning \"{q}\"" if q else "Vy: alla aktiva uppgifter"
            AmountOverviewDialog(self, _amounts.overview_text(_amounts.summarize(active), arch), scope).exec()
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} _show_amount_overview: {e}")

    # ----------------------------------------------------------- anteckning
    def _edit_note(self, task_id: str) -> None:
        try:
            get_throttle().notify_activity()
            from PySide6.QtWidgets import QDialog
            from ui.extras_dialogs import NoteDialog
            task = self.store.find_task(task_id) or {}
            dlg = NoteDialog(self, str(task.get("title") or ""), str(task.get("note") or ""))
            if dlg.exec() == QDialog.DialogCode.Accepted:
                self.store.set_note(task_id, dlg.text())
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} _edit_note: {e}")

    # ------------------------------------------------------- telefon/adress
    def _open_url(self, url: str) -> None:
        try:
            get_throttle().notify_activity()
            QDesktopServices.openUrl(QUrl(url))
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} _open_url: {e}")

    def _copy_text(self, text: str, what: str = "") -> None:
        try:
            QGuiApplication.clipboard().setText(str(text))
            logger.info(f"{LOG_PREFIX} kopierade {what or 'text'} till urklipp")
        except Exception as e:
            logger.debug(f"{LOG_PREFIX} _copy_text: {e}")

    def _phone_menu(self, ph: Dict[str, str], pos: Any) -> None:
        """Ring / SMS / kopiera. Vänsterklick öppnar menyn vid musen (tel: är inte registrerat på alla datorer)."""
        try:
            menu = QMenu(self)
            a = menu.addAction(f"📞 Ring {ph['text']}")
            a.triggered.connect(lambda _c: self._open_url(_contacts.tel_url(ph["tel"])))
            a = menu.addAction("💬 Skicka SMS")
            a.triggered.connect(lambda _c: self._open_url(_contacts.sms_url(ph["tel"])))
            a = menu.addAction("📋 Kopiera numret")
            a.triggered.connect(lambda _c: self._copy_text(ph["text"], "numret"))
            menu.exec(pos if pos is not None else QCursor.pos())
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} _phone_menu: {e}")

    def _address_menu(self, ad: Dict[str, str], pos: Any) -> None:
        try:
            menu = QMenu(self)
            a = menu.addAction("🗺 Öppna i Google Maps")
            a.triggered.connect(lambda _c: self._open_url(_contacts.maps_url(ad["text"])))
            a = menu.addAction("🧭 Vägbeskrivning hit")
            a.triggered.connect(lambda _c: self._open_url(_contacts.directions_url(ad["text"])))
            a = menu.addAction("📋 Kopiera adressen")
            a.triggered.connect(lambda _c: self._copy_text(ad["text"], "adressen"))
            menu.exec(pos if pos is not None else QCursor.pos())
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} _address_menu: {e}")
