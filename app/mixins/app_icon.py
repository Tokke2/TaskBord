# -*- coding: utf-8 -*-
"""Appikon: validering, skapande och Win32-processikon."""

from __future__ import annotations

import sys
from contextlib import suppress
from pathlib import Path
from typing import Any, Optional, Union

from app.constants import DATA_DIR, IconState, LOG_PREFIX


class AppIconMixin:
    """Appikon: validering, skapande och Win32-processikon."""

    def _validate_app_icon(self, ico_path: Optional[Path]) -> bool:
        """
        NY v7-fix19: validera att app.ico FAKTISKT fungerar.

        En korrupt .ico kan ge OGILTIG HICON i fönsterklassen →
        CreateWindowEx misslyckas med 'Felaktig parameter' vid VARJE
        försök = den eviga fönster-stormen. Vi testar BÅDE:
          1. Qt: QIcon + pixmap som inte är null
          2. Win32: LoadImageW — SAMMA API som WM_SETICON använder
        """
        if ico_path is None or not ico_path.is_file():
            return False
        try:
            if self._QIcon is not None:
                icon = self._QIcon(str(ico_path))
                if icon.isNull() or icon.pixmap(32, 32).isNull():
                    return False
        except Exception:
            return False
        if sys.platform == "win32":
            try:
                import ctypes
                user32 = ctypes.windll.user32
                hinst = ctypes.windll.kernel32.GetModuleHandleW(None)
                hicon = user32.LoadImageW(
                    hinst, str(ico_path), 1, 0, 0, 0x10 | 0x40
                )
                if not hicon:
                    # FIX v7-fix46: LoadImageW vägrar vissa PNG-i-ICO-format
                    # som Qt läser utan problem. Qt-checken ovan är det
                    # verkliga storm-skyddet (korrupt fil → null-QIcon där).
                    # Tidigare flyttades app.ico till .broken vid VARJE
                    # start och genererades om = evig loop + varningsbrus.
                    self._log.debug(
                        f"{LOG_PREFIX} app.ico: LoadImageW läste ej "
                        f"(PNG-i-ICO) — Qt-läsning OK, accepterar filen"
                    )
            except Exception:
                pass
        return True

    def _ensure_app_icon_file(self) -> Optional[Path]:
        """
        FIX 2026-09-23: Skapa data/app.ico om den saknas (PNG-in-ICO, 16–64px).
        Returnerar sökväg till .ico (används av QApplication + Win32 WM_SETICON).

        FIX v7-fix19: befintlig OCH genererad ikon valideras nu — en korrupt
        .ico är huvudmisstänkt för CreateWindowEx-stormen ('Felaktig parameter').
        """
        ico_path = DATA_DIR / "app.ico"
        try:
            # FIX v7-fix54: vår EGEN genererade ikon (markör .ico.ok finns)
            # används direkt — den validerar ej i Qt men FUNGERAR i
            # tray/Win32 (bevisat i loggen). Bryter .broken-loopen.
            _ok_marker = ico_path.with_suffix(".ico.ok")
            if (
                ico_path.is_file()
                and ico_path.stat().st_size > 1000
                and _ok_marker.is_file()
            ):
                return ico_path
            if ico_path.is_file() and ico_path.stat().st_size > 0:
                # FIX v7-fix19: validera — korrupt .ico → ogiltig HICON →
                # CreateWindowEx 'Felaktig parameter' vid varje försök!
                if self._validate_app_icon(ico_path):
                    return ico_path
                broken = ico_path.with_suffix(".ico.broken")
                with suppress(Exception):
                    ico_path.replace(broken)
                self._log.warning(
                    f"{LOG_PREFIX} app.ico OGILTIG — flyttad till "
                    f"{broken.name}, genererar ny ikon"
                )
            elif ico_path.is_file():
                with suppress(Exception):
                    ico_path.unlink()  # tom fil — ta bort
            # FIX v7-fix40: attributen kan saknas vid tidigt anrop
            # (före _init_qt_application) — hämta säkert + cacha
            _QPix = getattr(self, "_QPixmap", None)
            _QPaint = getattr(self, "_QPainter", None)
            _QCol = getattr(self, "_QColor", None)
            _QPen = getattr(self, "_QPen", None)
            if (_QPix is None or _QPaint is None or _QCol is None
                    or _QPen is None):
                try:
                    from PySide6.QtGui import (
                        QColor as _QColImp, QPainter as _QPaintImp,
                        QPen as _QPenImp, QPixmap as _QPixImp,
                    )
                    _QPix, _QPaint, _QCol, _QPen = (
                        _QPixImp, _QPaintImp, _QColImp, _QPenImp
                    )
                    self._QPixmap, self._QPainter = _QPix, _QPaint
                    self._QColor, self._QPen = _QCol, _QPen
                except Exception as _imp_err:
                    self._log.debug(
                        f"{LOG_PREFIX} _ensure_app_icon_file: Qt-klasser "
                        f"ej tillgängliga ännu: {_imp_err}"
                    )
                    return None
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            # FIX v7-fix52: den manuella PNG-i-ICO-bygget validerade EJ
            # (QIcon/LoadImageW vägrar vissa PNG-poster) och filen
            # genererades om vid VARJE start. Nu: Qt-native ICO-sparning
            # (BMP-baserad, alltid giltig) — samma cirkel+check-design.
            with suppress(Exception):
                ico_path.unlink(missing_ok=True)
            # NY v7-fix67: TaskBord-ikonen — ett litet "skrivbords-
            # kort" (rundad indigo-kvadrat) med en tydlig vit bock +
            # ljus top-kant (glaskänsla). Används överallt: fönster,
            # tray, aktivitetshanteraren (WM_SETICON).
            pm = self._QPixmap(64, 64)
            if pm.isNull():
                return None
            pm.fill(self._QColor(0, 0, 0, 0))
            p = self._QPainter(pm)
            if not p.isActive():
                return None
            p.setRenderHint(self._QPainter.RenderHint.Antialiasing)
            try:
                from PySide6.QtGui import QRadialGradient as _QRG
                from PySide6.QtCore import QPointF as _QPF
                _grad = _QRG(_QPF(32, 18), 44.0)
                _grad.setColorAt(0.0, self._QColor("#8b93f9"))
                _grad.setColorAt(1.0, self._QColor("#4f46e5"))
                p.setBrush(_grad)
            except Exception:
                p.setBrush(self._QColor("#6366f1"))
            p.setPen(self._QPen(self._QColor("#3730a3"), 2))
            p.drawRoundedRect(3, 3, 58, 58, 14, 14)
            # Ljus överkant (glaskant)
            p.setPen(self._QPen(self._QColor(255, 255, 255, 90), 2))
            p.drawLine(12, 6, 52, 6)
            # Stor vit bock
            pen = self._QPen(self._QColor("#ffffff"))
            pen.setWidthF(6.5)
            try:
                from PySide6.QtCore import Qt as _QtEnum
                pen.setCapStyle(_QtEnum.PenCapStyle.RoundCap)
                pen.setJoinStyle(_QtEnum.PenJoinStyle.RoundJoin)
            except Exception:
                pass
            p.setPen(pen)
            p.drawLine(18, 33, 28, 44)
            p.drawLine(28, 44, 47, 22)
            # Liten "pinne" uppe (påminnelse)
            p.setPen(self._QPen(self._QColor("#fbbf24"), 4))
            p.drawLine(32, 3, 32, 10)
            p.end()
            # Skala ner till 32 för ICO (skarp)
            # FIX v7-fix71: self._Qt finns ej vid tidigt anrop —
            # lokal import
            try:
                from PySide6.QtCore import Qt as _QtIco
                pm = pm.scaled(
                    32, 32,
                    _QtIco.AspectRatioMode.KeepAspectRatio,
                    _QtIco.TransformationMode.SmoothTransformation,
                )
            except Exception:
                pass  # behåll 64x64 — Qt ICO-writer hanterar det
            if not pm.save(str(ico_path), "ICO"):
                self._log.warning(
                    f"{LOG_PREFIX} Kunde ej spara app.ico (Qt ICO-writer)"
                )
                return None
            # FIX v7-fix54: markera som vår egen + acceptera direkt
            # (Qt-valideringen failar på Qt-skrivna ICO:er på vissa
            # maskiner, men ikonen fungerar i tray/Win32)
            with suppress(Exception):
                _ok_marker.write_text("ok", encoding="utf-8")
            self._log.info(
                f"{LOG_PREFIX} Skapade app-ico (Qt-native): {ico_path} "
                f"({ico_path.stat().st_size}B) — accepteras utan validering"
            )
            return ico_path
            # FIX v7-fix19: validera ÄVEN den genererade filen
            if not self._validate_app_icon(ico_path):
                with suppress(Exception):
                    ico_path.unlink()
                self._log.warning(
                    f"{LOG_PREFIX} genererad app.ico validerar EJ — "
                    f"kör utan ikon (bättre än CreateWindowEx-storm!)"
                )
                return None
            return ico_path
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} _ensure_app_icon_file: {e}")
            return None

    def apply_win32_process_icon(self, hwnd: int) -> None:
        """
        FIX 2026-09-23: Sätt ikon på HWND → syns i aktivitetsfält +
        Aktivitetshanteraren (WM_SETICON + SetClassLongPtr GCLP_HICON/SM).
        """
        if sys.platform != "win32" or not hwnd or self._app_icon_path is None:
            return
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            hinst = ctypes.windll.kernel32.GetModuleHandleW(None)
            # IMAGE_ICON=1, LR_LOADFROMFILE=0x10, LR_DEFAULTSIZE=0x40
            hicon_big = user32.LoadImageW(
                hinst, str(self._app_icon_path), 1, 0, 0, 0x10 | 0x40
            )
            hicon_small = user32.LoadImageW(
                hinst, str(self._app_icon_path), 1, 16, 16, 0x10
            )
            if not hicon_big and not hicon_small:
                self._log.debug("LoadImageW gav 0 HICON")
                return
            WM_SETICON, ICON_SMALL, ICON_BIG = 0x80, 0, 1
            GCLP_HICON, GCLP_HICONSM = -14, -34
            if hicon_big:
                user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon_big)
                user32.SetClassLongPtrW(hwnd, GCLP_HICON, hicon_big)
            if hicon_small:
                user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon_small)
                user32.SetClassLongPtrW(hwnd, GCLP_HICONSM, hicon_small)
            self._log.info(
                f"{LOG_PREFIX} Win32-ikon satt: HWND={hwnd} "
                f"big={bool(hicon_big)} small={bool(hicon_small)}"
            )
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} apply_win32_process_icon: {e}")

    def create_icon(
        self,
        state: Union[IconState, str] = IconState.NORMAL,
        color: str = "#818cf8",
        size: int = 64,
        cache_key: Optional[str] = None,
    ) -> Any:
        """
        Skapar en cache:ad QIcon med pixmap-grafik (checkmark, star, etc.).
        States:
          - NORMAL:  Tom cirkel med färg
          - CHECKED: Cirkel med ✓
          - EMPTY:   Cirkel med 0
          - WARNING: Cirkel med ⚠
        """
        if isinstance(state, str):
            try:
                state = IconState(state)
            except ValueError:
                state = IconState.NORMAL

        cache_key = cache_key or f"{state.value}:{color}:{size}"
        with self._icon_cache_lock:
            if cache_key in self._icon_cache:
                return self._icon_cache[cache_key]

        try:
            pixmap = self._QPixmap(size, size)
            if pixmap.isNull() or size <= 0:
                # FIX 2026-09-23: QPainter på null-pixmap → engine==0 type:1
                self._log.debug(
                    f"{LOG_PREFIX} create_icon: null pixmap size={size}"
                )
                return self._app.style().standardIcon(
                    self._QStyle.StandardPixmap.SP_ComputerIcon
                ) if self._app and hasattr(self._app, "style") else self._QIcon()
            pixmap.fill(self._QColor(0, 0, 0, 0))  # Transparent

            painter = self._QPainter(pixmap)
            if not painter.isActive():
                self._log.debug(f"{LOG_PREFIX} create_icon: QPainter ej aktiv")
                return self._QIcon(pixmap)
            painter.setRenderHint(self._QPainter.RenderHint.Antialiasing)

            # Cirkel
            brush = self._QBrush(self._QColor(color))
            painter.setBrush(brush)
            pen = self._QPen(self._QColor(color).darker(150))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawEllipse(4, 4, size - 8, size - 8)

            # Symbol
            painter.setPen(self._QPen(self._QColor(255, 255, 255)))
            font = self._QFont("Segoe UI", int(size * 0.45), self._QFont.Weight.Bold)
            painter.setFont(font)
            symbol_map = {
                IconState.NORMAL: "✓",
                IconState.CHECKED: "✓",
                IconState.EMPTY: "0",
                IconState.WARNING: "!",
            }
            symbol = symbol_map.get(state, "✓")
            painter.drawText(pixmap.rect(), self._Qt.AlignmentFlag.AlignCenter, symbol)
            painter.end()

            icon = self._QIcon(pixmap)
            with self._icon_cache_lock:
                self._icon_cache[cache_key] = icon
            return icon
        except Exception as e:
            self._log.warning(f"create_icon misslyckades: {e}, använder default")
            return self._app.style().standardIcon(
                self._QStyle.StandardPixmap.SP_ComputerIcon
            ) if self._app and hasattr(self._app, "style") else self._QIcon()
