# -*- coding: utf-8 -*-
"""
ui/widget_parts/links_attach.py — länkar (🔗) och bilagor (📎) på uppgifter: chips på kortet,
högerklicksmenyer, "Lägg till länk…", "Bifoga fil…" och hämtning av sidtitlar i bakgrunden.

Del av TodoWidget. Bilagor KOPIERAS in i appens datamapp (core/attachments.py) — inget skrivs utanför
appmappen. Länkar öppnas i standardwebbläsaren, bilagor i filens vanliga program.
"""
from __future__ import annotations

from contextlib import suppress
from typing import Any, Dict, List, Tuple

from ui.widget_base import *  # noqa: F401,F403
from ui.widget_atoms import *  # noqa: F401,F403

from core import attachments as _att
from core import links as _links

try:
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices, QGuiApplication
    from PySide6.QtWidgets import QFileDialog, QInputDialog, QMenu, QMessageBox
except ImportError:  # pragma: no cover
    QUrl = QDesktopServices = QGuiApplication = QFileDialog = QInputDialog = QMenu = QMessageBox = None  # type: ignore

_MAX_CHIPS = 6  # fler visas som "+N till"


class LinksAttachMixin:
    """Länkar och bilagor på uppgifter."""

    # ------------------------------------------------------------------ hjälp
    def _task_is_archived(self, task_id: str) -> bool:
        fn = getattr(self.store, "is_archived", None)
        return bool(fn(task_id)) if callable(fn) else False

    def _data_dir_str(self) -> str:
        return str(getattr(self.store, "data_dir", "") or "")

    def _get_link_fetcher(self) -> Any:
        f = getattr(self, "_link_fetcher", None)
        if f is None:
            from ui.link_titles import LinkTitleFetcher
            f = LinkTitleFetcher(self.store, self)
            self._link_fetcher = f
        return f

    def _start_link_title_fetch(self, task_id: str, url: str) -> bool:
        """Hämta sidtiteln i bakgrunden (om inställningen tillåter). True om en hämtning startades."""
        try:
            on = getattr(self.settings, "links_fetch_titles", None)
            if callable(on) and not on():
                return False
            self._get_link_fetcher().fetch(task_id, url)
            return True
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} kunde inte starta titelhämtning: {e}")
            return False

    # ------------------------------------------------------------ chips på kortet
    def _add_link_rows(self, container: Any, vbox: Any, task: Dict[str, Any], archived: bool) -> None:
        """En rad per länk/bilaga (högst _MAX_CHIPS av varje, resten som '+N till')."""
        tid = str(task.get("id", ""))
        links = [x for x in (task.get("links") or []) if isinstance(x, dict) and x.get("url")]
        atts = [x for x in (task.get("attachments") or []) if isinstance(x, dict) and x.get("file")]
        if not (links or atts):
            return
        data_dir = self._data_dir_str()
        rows: List[Tuple[Any, str]] = []
        for lk in links[:_MAX_CHIPS]:
            url = str(lk["url"])
            title = str(lk.get("title") or "") or _links.display_title(url)
            chip = LinkChip(
                f"🔗 {title}", url, "link",
                f"{title}\n{url}\n\nKlicka: öppna i webbläsaren · Högerklick: fler val", container,
            )
            chip.clicked.connect(self._open_link)
            chip.menu_requested.connect(
                lambda key, pos, t=tid, a=archived: self._link_chip_menu(t, key, pos, a)
            )
            rows.append((chip, "link"))
        for at in atts[:_MAX_CHIPS]:
            file_rel = str(at["file"])
            present = bool(data_dir) and _att.exists(data_dir, file_rel)
            size = _att.human_size(int(at.get("size") or 0))
            label = f"{'📎' if present else '⚠'} {at.get('name') or file_rel} · {size}"
            tip = (f"{at.get('name')}\n{size}\n\nKlicka: öppna · Högerklick: fler val" if present
                   else f"{at.get('name')}\n\n⚠ Filen saknas i appmappen (attachments).")
            chip = LinkChip(label, file_rel, "attachment", tip, container)
            chip.clicked.connect(lambda key, t=tid: self._open_attachment(t, key))
            chip.menu_requested.connect(
                lambda key, pos, t=tid, a=archived: self._attach_chip_menu(t, key, pos, a)
            )
            rows.append((chip, "attachment"))
        extra = max(0, len(links) - _MAX_CHIPS) + max(0, len(atts) - _MAX_CHIPS)
        if extra:
            more = LinkChip(f"+{extra} till…", "", "link", "Fler länkar/bilagor — öppna uppgiftens meny", container)
            more.clicked.connect(lambda _k, tk=dict(task): self._show_task_menu(tk))
            rows.append((more, "more"))
        for chip, _kind in rows:
            row = QHBoxLayout()
            row.setSpacing(6)
            row.addSpacing(34)
            row.addWidget(chip)
            row.addStretch(1)
            vbox.addLayout(row)

    # ----------------------------------------------------------------- öppna
    def _open_link(self, url: str) -> None:
        try:
            get_throttle().notify_activity()
            u = _links.normalize(url)
            if not u:
                return
            QDesktopServices.openUrl(QUrl(u))
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} _open_link: {e}")

    def _open_attachment(self, task_id: str, file_rel: str) -> None:
        try:
            get_throttle().notify_activity()
            p = _att.resolve(self._data_dir_str(), file_rel)
            if p is None or not p.is_file():
                QMessageBox.information(self, "📎 Filen saknas",
                                        "Bilagan finns inte längre i appmappen (attachments).")
                return
            if _att.is_dangerous(p.name):
                r = QMessageBox.question(
                    self, "⚠ Öppna den här filen?",
                    f"'{p.name}' är en körbar filtyp och kan köra kod när den öppnas.\n\nÖppna ändå?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if r != QMessageBox.StandardButton.Yes:
                    return
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} _open_attachment: {e}")

    def _show_attachment_in_folder(self, file_rel: str) -> None:
        with suppress(Exception):
            p = _att.resolve(self._data_dir_str(), file_rel)
            if p is not None:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(p.parent)))

    # --------------------------------------------------------------- menyer
    def _link_chip_menu(self, task_id: str, url: str, pos: Any, archived: bool = False) -> None:
        try:
            menu = QMenu(self)
            a_open = menu.addAction("🌐 Öppna i webbläsaren")
            a_copy = menu.addAction("📋 Kopiera länken")
            a_title = menu.addAction("🔄 Hämta titeln igen")
            a_rm = None
            if not archived:
                menu.addSeparator()
                a_rm = menu.addAction("🗑 Ta bort länken")
            chosen = menu.exec(pos)
            if chosen is None:
                return
            if chosen is a_open:
                self._open_link(url)
            elif chosen is a_copy:
                QGuiApplication.clipboard().setText(url)
            elif chosen is a_title:
                self._start_link_title_fetch(task_id, url)
            elif a_rm is not None and chosen is a_rm:
                self.store.remove_link(task_id, url)
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} _link_chip_menu: {e}")

    def _attach_chip_menu(self, task_id: str, file_rel: str, pos: Any, archived: bool = False) -> None:
        try:
            menu = QMenu(self)
            a_open = menu.addAction("📂 Öppna")
            a_dir = menu.addAction("🗂 Visa i mappen")
            a_copy = menu.addAction("📋 Kopiera sökvägen")
            a_rm = None
            if not archived:
                menu.addSeparator()
                a_rm = menu.addAction("🗑 Ta bort bilagan")
            chosen = menu.exec(pos)
            if chosen is None:
                return
            if chosen is a_open:
                self._open_attachment(task_id, file_rel)
            elif chosen is a_dir:
                self._show_attachment_in_folder(file_rel)
            elif chosen is a_copy:
                p = _att.resolve(self._data_dir_str(), file_rel)
                QGuiApplication.clipboard().setText(str(p or file_rel))
            elif a_rm is not None and chosen is a_rm:
                self._remove_attachment(task_id, file_rel)
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} _attach_chip_menu: {e}")

    def _remove_attachment(self, task_id: str, file_rel: str) -> bool:
        r = QMessageBox.question(
            self, "🗑 Ta bort bilagan?",
            "Bilagan och den kopierade filen i appmappen tas bort.\nOriginalfilen påverkas inte.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if r != QMessageBox.StandardButton.Yes:
            return False
        return bool(self.store.remove_attachment(task_id, file_rel))

    # ------------------------------------------------------- lägg till (dialoger)
    def _clipboard_url(self) -> str:
        with suppress(Exception):
            urls = _links.extract_urls(QGuiApplication.clipboard().text() or "")
            if urls:
                return urls[0]
        return ""

    def _prompt_add_link(self, task_id: str) -> None:
        try:
            get_throttle().notify_activity()
            text, ok = QInputDialog.getText(
                self, "🔗 Lägg till länk", "Klistra in adressen (https://…):", text=self._clipboard_url()
            )
            if not ok or not text.strip():
                return
            urls = _links.extract_urls(text) or ([u] if (u := _links.normalize(text.strip())) else [])
            if not urls:
                QMessageBox.information(self, "🔗 Ogiltig länk",
                                        "Det där ser inte ut som en webbadress (börja med https://).")
                return
            self._add_links_to_task(task_id, urls)
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} _prompt_add_link: {e}")

    def _add_links_to_task(self, task_id: str, urls: List[str]) -> int:
        """Lägg till länkar och starta titelhämtning. Returnerar antal tillagda."""
        n = 0
        for u in urls:
            if self.store.add_link(task_id, u, ""):
                n += 1
                self._start_link_title_fetch(task_id, u)
        return n

    def _prompt_attach_file(self, task_id: str) -> None:
        try:
            get_throttle().notify_activity()
            paths, _flt = QFileDialog.getOpenFileNames(self, "📎 Bifoga fil(er) — kopieras in i appmappen")
            if not paths:
                return
            ok, errors = self._attach_files(task_id, list(paths))
            if errors:
                QMessageBox.warning(self, "📎 Kunde inte bifoga allt", "\n\n".join(errors[:5]))
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} _prompt_attach_file: {e}")

    def _attach_files(self, task_id: str, paths: List[str]) -> Tuple[int, List[str]]:
        """Kopiera filerna in i appmappen och registrera dem. Returnerar (antal ok, felmeddelanden)."""
        ok, errors = 0, []
        data_dir = self._data_dir_str()
        for src in paths:
            try:
                meta = _att.copy_in(data_dir, task_id, src)
            except _att.AttachmentError as e:
                errors.append(str(e))
                continue
            if self.store.add_attachment(task_id, meta["name"], meta["file"], meta["size"], meta["added"]):
                ok += 1
            else:
                _att.delete_file(data_dir, meta["file"])  # kunde inte registreras → ingen herrelös fil
                errors.append(f"Kunde inte lägga till '{meta['name']}' (för många bilagor?).")
        return ok, errors
