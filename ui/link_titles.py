# -*- coding: utf-8 -*-
"""
link_titles.py — hämtar sidtitlar för länkar i bakgrunden och för över dem till GUI-tråden.

Nätverksanropet (core/links.fetch_title) körs i en egen tråd; resultatet levereras med en Qt-signal
(köad → slotten körs ALLTID i GUI-tråden, där store och fönster får ändras).
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Optional

from core import links as _links

logger = logging.getLogger("Ledgebord")
LOG_PREFIX = "[LINKTITLE]"

try:
    from PySide6.QtCore import QObject, Qt, Signal, Slot
    _QT = True
except ImportError:  # pragma: no cover
    _QT = False
    QObject = object  # type: ignore[misc,assignment]


def placeholder_for(url: str) -> str:
    """Titeln en uppgift får innan sidans titel är hämtad (värdnamnet)."""
    return _links.display_title(url)


if _QT:

    class LinkTitleFetcher(QObject):
        """``fetch(task_id, url)`` → sätter länkens titel i store när sidan svarat (och byter uppgiftens
        titel om den fortfarande är platshållaren, dvs. uppgiften skapades av bara en URL)."""

        _done = Signal(str, str, str)
        applied = Signal(str)  # task_id (efter att store ändrats)

        def __init__(
            self, store: Any, parent: Optional[QObject] = None,
            fetch: Optional[Callable[[str], str]] = None,
        ) -> None:
            super().__init__(parent)
            self._store = store
            self._fetch = fetch or _links.fetch_title  # byts ut i tester
            self._done.connect(self._apply, Qt.ConnectionType.QueuedConnection)

        def fetch(self, task_id: str, url: str) -> None:
            t = threading.Thread(target=self._work, args=(task_id, url), daemon=True, name="link-title")
            t.start()

        def _work(self, task_id: str, url: str) -> None:
            try:
                title = self._fetch(url) or ""
            except Exception:
                title = ""
            try:
                self._done.emit(task_id, url, title)
            except RuntimeError:  # objektet är borta (programmet avslutas)
                pass

        @Slot(str, str, str)
        def _apply(self, task_id: str, url: str, title: str) -> None:
            self.apply_title(task_id, url, title)

        def apply_title(self, task_id: str, url: str, title: str) -> bool:
            """Körs i GUI-tråden. Returnerar True om något ändrades."""
            title = (title or "").strip()
            if not title or self._store is None:
                return False
            changed = False
            try:
                changed = bool(self._store.set_link_title(task_id, url, title))
                task = self._store.find_task(task_id)
                if task and str(task.get("title", "")) in (placeholder_for(url), url):
                    # bara-URL-uppgift: ge den sidans titel (inte om användaren redan ändrat den)
                    if self._store.update_task_title(task_id, title):
                        changed = True
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} kunde inte spara titeln: {e}")
            if changed:
                self.applied.emit(task_id)
            return changed
