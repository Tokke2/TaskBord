# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""
dialog_front.py — dialogrutor (frågor, val av datum, inställningar, felmeddelanden …) ska ALLTID ligga överst
tills man är klar med dem — aldrig gömda bakom Thunderbird, webbläsaren eller Ledgebords eget fönster.

Varför det behövs: Ledgebords fönster kan ligga "alltid överst" (HWND_TOPMOST) och läggs om var 1,5 s. En dialog
utan ägare (öppnad från tray-menyn) är ett vanligt fönster och hamnar då bakom — och en dialog öppnad medan
en annan app har fokus kan också gömmas av Windows.

Så här gör vi: ett appövergripande filter ser varje dialog som visas och lägger den överst (Windows:
HWND_TOPMOST). Medan dialogen är öppen lägger `restack()` den överst igen efter varje omläggning av huvudfönstret.
Öppna menyer läggs överst utan fokus och följer med vid varje omläggning. Inget Qt-fönster skapas här; allt är valfritt utanför Windows.
"""
from __future__ import annotations

import logging
import sys
import weakref
from contextlib import suppress
from typing import Any, Callable, List, Optional

logger = logging.getLogger("Ledgebord")
LOG_PREFIX = "[DIALOG-FRAMME]"


def native_topmost(hwnd: int) -> bool:
    """Lägg fönstret överst bland toppfönster utan att flytta/ändra storlek. False utanför Windows."""
    if not hwnd or sys.platform != "win32":
        return False
    try:
        import ctypes
        user32 = ctypes.windll.user32
        if not user32.IsWindow(hwnd):
            return False
        # HWND_TOPMOST | NOMOVE | NOSIZE | SHOWWINDOW  (utan NOACTIVATE: dialogen får fokus)
        user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0040)
        return True
    except Exception:
        return False


def native_topmost_quiet(hwnd: int) -> bool:
    """Som native_topmost men utan att ta fokus (för menyer: de håller själva musfångsten)."""
    if not hwnd or sys.platform != "win32":
        return False
    try:
        import ctypes
        user32 = ctypes.windll.user32
        if not user32.IsWindow(hwnd):
            return False
        # HWND_TOPMOST | NOMOVE | NOSIZE | NOACTIVATE | SHOWWINDOW
        user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0010 | 0x0040)
        return True
    except Exception:
        return False


def popup_open() -> bool:
    """True medan en meny/rullista (Qt-popup) är öppen — då får huvudfönstret inte läggas om."""
    try:
        from PySide6.QtWidgets import QApplication
        return QApplication.activePopupWidget() is not None
    except Exception:
        return False


try:
    from PySide6.QtCore import QEvent, QObject, QTimer
    from PySide6.QtWidgets import QDialog, QMenu, QWidget
    _QT = True
except ImportError:  # pragma: no cover
    _QT = False
    QObject = object  # type: ignore


class DialogFront(QObject):  # type: ignore[misc]
    """Appövergripande filter: varje QDialog som visas hamnar överst och stannar där tills den stängs."""

    def __init__(self, native: Optional[Callable[[int], bool]] = None, parent: Any = None,
                 native_menu: Optional[Callable[[int], bool]] = None) -> None:
        super().__init__(parent)
        self._native = native or native_topmost
        self._native_menu = native_menu or native_topmost_quiet
        self._open: "List[weakref.ref]" = []
        self._menus: "List[weakref.ref]" = []
        self.raised = 0   # antal gånger en dialog lagts överst (diagnos/test)

    # ---------------------------------------------------------------- filter
    def eventFilter(self, obj: Any, event: Any) -> bool:  # noqa: N802
        try:
            t = event.type()
            if t == QEvent.Type.Show and isinstance(obj, QDialog) and obj.isWindow():
                self._track(obj)
                # fönstret är inte färdigt förrän efter Show → lägg överst direkt och en gång till strax efter
                self._front(obj)
                self._later(0, obj)
                self._later(250, obj)
            elif t == QEvent.Type.Show and isinstance(obj, QMenu) and obj.isWindow():
                # högerklicksmenyn ska ligga över huvudfönstret även när det läggs om var 1,5 s
                if not any(r() is obj for r in self._menus):
                    self._menus.append(weakref.ref(obj))
                self._native_menu(int(obj.winId()))
            elif t in (QEvent.Type.Hide, QEvent.Type.Close, QEvent.Type.Destroy) and isinstance(obj, QDialog):
                self._untrack(obj)
        except Exception as e:  # filtret får aldrig störa appen
            logger.debug(f"{LOG_PREFIX} filter: {e}")
        return False

    # ----------------------------------------------------------------- hjälp
    def _later(self, ms: int, d: Any) -> None:
        ref = weakref.ref(d)
        t = QTimer(self)
        t.setSingleShot(True)
        t.timeout.connect(lambda: self._front(ref()) if ref() is not None else None)
        t.timeout.connect(t.deleteLater)
        t.start(ms)

    def _track(self, d: Any) -> None:
        if not any(r() is d for r in self._open):
            self._open.append(weakref.ref(d))

    def _untrack(self, d: Any) -> None:
        self._open = [r for r in self._open if r() is not None and r() is not d]

    def visible_dialogs(self) -> List[Any]:
        out = []
        for r in list(self._open):
            d = r()
            try:
                if d is not None and d.isVisible():
                    out.append(d)
            except RuntimeError:   # C++-objektet borta
                pass
        self._open = [weakref.ref(d) for d in out]
        return out

    def _front(self, d: Any, activate: bool = True) -> None:
        try:
            if not d.isVisible():
                return
            self._native(int(d.winId()))
            if activate:
                d.raise_()
                d.activateWindow()
            self.raised += 1
        except RuntimeError:
            pass
        except Exception as e:
            logger.debug(f"{LOG_PREFIX} _front: {e}")

    def restack(self) -> int:
        """Lägg alla öppna dialoger överst igen (anropas efter att huvudfönstret lagts överst). Returnerar antal."""
        n = 0
        for d in self.visible_dialogs():
            self._front(d, activate=False)
            n += 1
        for m in self.visible_menus():
            with suppress(Exception):
                self._native_menu(int(m.winId()))
        return n

    def visible_menus(self) -> List[Any]:
        out = []
        for r in list(self._menus):
            m = r()
            try:
                if m is not None and m.isVisible():
                    out.append(m)
            except RuntimeError:
                pass
        self._menus = [weakref.ref(m) for m in out]
        return out


def install(app: Any, native: Optional[Callable[[int], bool]] = None) -> Optional["DialogFront"]:
    """Installera filtret på QApplication. Returnerar filtret (behåll referensen!)."""
    if not _QT or app is None:
        return None
    f = DialogFront(native=native, parent=app)
    app.installEventFilter(f)
    return f
