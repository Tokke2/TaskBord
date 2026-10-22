# -*- coding: utf-8 -*-
"""Appikon: validering, skapande och Win32-processikon."""

from __future__ import annotations

import sys
from contextlib import suppress
from pathlib import Path
from typing import Any, Optional, Union

from app.constants import APP_USER_MODEL_ID, DATA_DIR, IconState, LOG_PREFIX, SCRIPT_DIR


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
            _qicon = getattr(self, "_QIcon", None)
            if _qicon is None:
                from PySide6.QtGui import QIcon as _qicon  # tidigt anrop: Qt-klasserna är inte hämtade än
            icon = _qicon(str(ico_path))
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
        Ledgebords ikon (``icon/ledgebord.ico`` i appmappen). Används överallt: fönster, tray,
        aktivitetsfält och Aktivitetshanteraren (WM_SETICON) samt genvägar.

        Saknas filen eller går den inte att läsa ritas samma ikon om (core/icon_art.py, ren
        stdlib) till ``data/ledgebord.ico`` — aldrig en Python-ikon. En korrupt .ico kan ge
        'Felaktig parameter' vid CreateWindowEx, därför valideras filen innan den används.
        """
        try:
            bundled = SCRIPT_DIR / "icon" / "ledgebord.ico"
            if bundled.is_file() and bundled.stat().st_size > 500 and self._validate_app_icon(bundled):
                return bundled
            generated = DATA_DIR / "ledgebord.ico"
            if generated.is_file() and generated.stat().st_size > 500 and self._validate_app_icon(generated):
                return generated
            from core import icon_art
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            generated.write_bytes(icon_art.build_ico((16, 24, 32, 48, 64)))
            self._log.info(f"{LOG_PREFIX} ritade om appikonen: {generated} ({generated.stat().st_size}B)")
            if self._validate_app_icon(generated):
                return generated
            self._log.warning(f"{LOG_PREFIX} den ritade ikonen validerar inte — kör utan ikon")
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} _ensure_app_icon_file: {e}")
        return None

    @staticmethod
    def _set_app_user_model_id() -> None:
        """
        Windows: ge processen ett EGET AppUserModelID innan något fönster skapas.

        Utan det grupperar Windows pythonw.exe-processen under Pythons identitet och visar
        Python-ikonen i aktivitetsfältet/startmenyn. Med det används Ledgebords fönsterikon
        (och genvägens ikon) i stället.
        """
        if sys.platform != "win32":
            return
        with suppress(Exception):
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)

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
            # SM_CXICON=11, SM_CXSMICON=49 — rätt storlek för skärmens DPI (skarp ikon i aktivitetsfältet)
            _big = max(48, int(user32.GetSystemMetrics(11)) or 32)
            _small = int(user32.GetSystemMetrics(49)) or 16
            hicon_big = user32.LoadImageW(
                hinst, str(self._app_icon_path), 1, _big, _big, 0x10
            )
            hicon_small = user32.LoadImageW(
                hinst, str(self._app_icon_path), 1, _small, _small, 0x10
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
