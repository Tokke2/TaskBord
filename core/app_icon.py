"""
app_icon.py — TaskBords ikonmodul (framtida uppdelning av main.pyw).

STATUS: ⏸️ EJ KOPPLAD ÄNNU (v7-fix84, 2026-10-07)
===============================================
Detta är en FRISTÅENDE spegel av main.pyw:s ikonlogik — skapad på
Rickards begäran "gör den men koppla inte bort någon annan kod och
koppla in den ännu, för framtida bruk":

  * main.pyw behåller ALL sin egen ikonkod OFÖRÄNDRAD (create_icon,
    _validate_app_icon, _ensure_app_icon_file, apply_win32_process_icon)
  * INGEN fil importerar denna modul ännu
  * När main.pyw delas upp (se KODKARTA.md §6) ersätts main-metoderna
    med anrop hit — koden är 1:1-spegling så bytet blir mekaniskt

Innehåll (samma design/logik som main.pyw):
  * validate_app_icon()   — Qt+Win32-validering av .ico (storm-skyddet)
  * ensure_app_icon_file()— genererar data/app.ico (Qt-native ICO,
                            rundad indigo-kvadrat + vit bock + gul pinne)
  * create_status_icon()  — tray-statusikoner (cirkel + symbol), cache:ade
  * apply_win32_process_icon() — WM_SETICON + SetClassLongPtr på HWND

Logg-prefix: [IKON]
"""
from __future__ import annotations

import logging
import sys
import threading
from contextlib import suppress
from pathlib import Path
from typing import Any, Dict, Optional, Union

logger = logging.getLogger("app_icon")
LOG_PREFIX: str = "[IKON]"

# --- Qt-importer (valvda — modulen ska kunna importas utan display) -------
_QT_AVAILABLE: bool = False
try:
    from PySide6.QtCore import Qt as _Qt
    from PySide6.QtGui import (
        QColor as _QColor, QIcon as _QIcon, QPainter as _QPainter,
        QPen as _QPen, QPixmap as _QPixmap, QFont as _QFont,
    )
    _QT_AVAILABLE = True
except Exception:  # pragma: no cover
    _Qt = _QColor = _QIcon = _QPainter = _QPen = _QPixmap = _QFont = None

IS_WINDOWS: bool = sys.platform == "win32"

# Ikontillstånd (spegling av main.pyw:s IconState-enum)
ICON_STATES: tuple = ("normal", "checked", "empty", "warning")

# Cache för statusikoner (spegling av AppController._icon_cache)
_ICON_CACHE: Dict[str, Any] = {}
_ICON_CACHE_LOCK = threading.Lock()


def validate_app_icon(ico_path: Optional[Path]) -> bool:
    """
    Validera att en .ico FAKTISKT fungerar (spegling: main _validate_app_icon,
    v7-fix19).

    En korrupt .ico ger OGILTIG HICON i fönsterklassen → CreateWindowEx
    misslyckas med 'Felaktig parameter' vid VARJE försök = den eviga
    fönster-stormen. Testar:
      1. Qt: QIcon + pixmap som inte är null
      2. Win32: LoadImageW — SAMMA API som WM_SETICON använder
    """
    if ico_path is None or not Path(ico_path).is_file():
        return False
    try:
        if _QIcon is not None:
            icon = _QIcon(str(ico_path))
            if icon.isNull() or icon.pixmap(32, 32).isNull():
                return False
    except Exception:
        return False
    if IS_WINDOWS:
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hinst = ctypes.windll.kernel32.GetModuleHandleW(None)
            hicon = user32.LoadImageW(
                hinst, str(ico_path), 1, 0, 0, 0x10 | 0x40
            )
            if not hicon:
                # LoadImageW vägrar vissa PNG-i-ICO-format som Qt läser
                # utan problem — Qt-checken är det verkliga skyddet.
                logger.debug(
                    f"{LOG_PREFIX} app.ico: LoadImageW läste ej "
                    f"(PNG-i-ICO) — Qt-läsning OK, accepterar filen"
                )
        except Exception:
            pass
    return True


def ensure_app_icon_file(data_dir: Union[str, Path]) -> Optional[Path]:
    """
    Skapa data/app.ico om den saknas eller är ogiltig (spegling: main
    _ensure_app_icon_file, v7-fix19/40/52/54/67/71).

    Design (v7-fix67): "skrivbordskort" — rundad indigo-kvadrat med
    radialtoning, ljus glaskant, stor vit bock + gul pinne uppe.
    Qt-native ICO-sparning (BMP-baserad, alltid giltig).
    Returnerar sökvägen till .ico, eller None vid fel.
    """
    if not _QT_AVAILABLE:
        logger.debug(f"{LOG_PREFIX} Qt ej tillgängligt — ingen ikon")
        return None
    data_dir = Path(data_dir)
    ico_path = data_dir / "app.ico"
    try:
        # Vår EGEN genererade ikon (markör .ico.ok) används direkt —
        # den validerar ej i Qt men FUNGERAR i tray/Win32 (v7-fix54)
        _ok_marker = ico_path.with_suffix(".ico.ok")
        if (
            ico_path.is_file()
            and ico_path.stat().st_size > 1000
            and _ok_marker.is_file()
        ):
            return ico_path
        if ico_path.is_file() and ico_path.stat().st_size > 0:
            if validate_app_icon(ico_path):
                return ico_path
            broken = ico_path.with_suffix(".ico.broken")
            with suppress(Exception):
                ico_path.replace(broken)
            logger.warning(
                f"{LOG_PREFIX} app.ico OGILTIG — flyttad till "
                f"{broken.name}, genererar ny ikon"
            )
        elif ico_path.is_file():
            with suppress(Exception):
                ico_path.unlink()  # tom fil — ta bort

        data_dir.mkdir(parents=True, exist_ok=True)
        with suppress(Exception):
            ico_path.unlink(missing_ok=True)

        # --- TaskBord-ikonen (v7-fix67) — identisk design som main.pyw ---
        pm = _QPixmap(64, 64)
        if pm.isNull():
            return None
        pm.fill(_QColor(0, 0, 0, 0))
        p = _QPainter(pm)
        if not p.isActive():
            return None
        p.setRenderHint(_QPainter.RenderHint.Antialiasing)
        try:
            from PySide6.QtGui import QRadialGradient as _QRG
            from PySide6.QtCore import QPointF as _QPF
            _grad = _QRG(_QPF(32, 18), 44.0)
            _grad.setColorAt(0.0, _QColor("#8b93f9"))
            _grad.setColorAt(1.0, _QColor("#4f46e5"))
            p.setBrush(_grad)
        except Exception:
            p.setBrush(_QColor("#6366f1"))
        p.setPen(_QPen(_QColor("#3730a3"), 2))
        p.drawRoundedRect(3, 3, 58, 58, 14, 14)
        # Ljus överkant (glaskant)
        p.setPen(_QPen(_QColor(255, 255, 255, 90), 2))
        p.drawLine(12, 6, 52, 6)
        # Stor vit bock
        pen = _QPen(_QColor("#ffffff"))
        pen.setWidthF(6.5)
        try:
            pen.setCapStyle(_Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(_Qt.PenJoinStyle.RoundJoin)
        except Exception:
            pass
        p.setPen(pen)
        p.drawLine(18, 33, 28, 44)
        p.drawLine(28, 44, 47, 22)
        # Liten "pinne" uppe (påminnelse)
        p.setPen(_QPen(_QColor("#fbbf24"), 4))
        p.drawLine(32, 3, 32, 10)
        p.end()
        # Skala ner till 32 för ICO (skarp)
        try:
            pm = pm.scaled(
                32, 32,
                _Qt.AspectRatioMode.KeepAspectRatio,
                _Qt.TransformationMode.SmoothTransformation,
            )
        except Exception:
            pass  # behåll 64x64 — Qt ICO-writer hanterar det
        if not pm.save(str(ico_path), "ICO"):
            logger.warning(
                f"{LOG_PREFIX} Kunde ej spara app.ico (Qt ICO-writer)"
            )
            return None
        # Markera som vår egen + acceptera direkt (v7-fix54)
        with suppress(Exception):
            _ok_marker.write_text("ok", encoding="utf-8")
        logger.info(
            f"{LOG_PREFIX} Skapade app-ico (Qt-native): {ico_path} "
            f"({ico_path.stat().st_size}B) — accepteras utan validering"
        )
        return ico_path
    except Exception as e:
        logger.warning(f"{LOG_PREFIX} ensure_app_icon_file: {e}")
        return None


def create_status_icon(
    state: str = "normal",
    color: str = "#818cf8",
    size: int = 64,
    cache_key: Optional[str] = None,
) -> Any:
    """
    Cache:ad statusikon för tray (spegling: main create_icon).

    States: 'normal' (✓) · 'checked' (✓) · 'empty' (0) · 'warning' (!)
    Cirkel i vald färg + vit symbol.
    """
    if not _QT_AVAILABLE:
        return None
    state = str(state or "normal").lower()
    if state not in ICON_STATES:
        state = "normal"
    cache_key = cache_key or f"{state}:{color}:{size}"
    with _ICON_CACHE_LOCK:
        if cache_key in _ICON_CACHE:
            return _ICON_CACHE[cache_key]
    try:
        pixmap = _QPixmap(size, size)
        if pixmap.isNull() or size <= 0:
            logger.debug(
                f"{LOG_PREFIX} create_status_icon: null pixmap size={size}"
            )
            return _QIcon()
        pixmap.fill(_QColor(0, 0, 0, 0))  # transparent
        painter = _QPainter(pixmap)
        if not painter.isActive():
            logger.debug(f"{LOG_PREFIX} create_status_icon: QPainter ej aktiv")
            return _QIcon(pixmap)
        painter.setRenderHint(_QPainter.RenderHint.Antialiasing)
        # Cirkel
        from PySide6.QtGui import QBrush
        painter.setBrush(QBrush(_QColor(color)))
        pen = _QPen(_QColor(color).darker(150))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawEllipse(4, 4, size - 8, size - 8)
        # Symbol
        painter.setPen(_QPen(_QColor(255, 255, 255)))
        font = _QFont("Segoe UI", int(size * 0.45), _QFont.Weight.Bold)
        painter.setFont(font)
        symbol_map = {
            "normal": "✓", "checked": "✓", "empty": "0", "warning": "!",
        }
        painter.drawText(
            pixmap.rect(),
            _Qt.AlignmentFlag.AlignCenter,
            symbol_map.get(state, "✓"),
        )
        painter.end()
        icon = _QIcon(pixmap)
        with _ICON_CACHE_LOCK:
            _ICON_CACHE[cache_key] = icon
        return icon
    except Exception as e:
        logger.warning(
            f"{LOG_PREFIX} create_status_icon misslyckades: {e}, "
            f"använder default"
        )
        return _QIcon()


def apply_win32_process_icon(hwnd: int, ico_path: Union[str, Path]) -> bool:
    """
    Sätt ikon på HWND → syns i aktivitetsfält + Aktivitetshanteraren
    (spegling: main apply_win32_process_icon).

    WM_SETICON + SetClassLongPtr (GCLP_HICON/GCLP_HICONSM).
    Returnerar True om någon ikon sattes.
    """
    if not IS_WINDOWS or not hwnd:
        return False
    ico_path = Path(ico_path)
    if not ico_path.is_file():
        logger.debug(f"{LOG_PREFIX} apply_win32: {ico_path} finns ej")
        return False
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hinst = ctypes.windll.kernel32.GetModuleHandleW(None)
        # IMAGE_ICON=1, LR_LOADFROMFILE=0x10, LR_DEFAULTSIZE=0x40
        hicon_big = user32.LoadImageW(
            hinst, str(ico_path), 1, 0, 0, 0x10 | 0x40
        )
        hicon_small = user32.LoadImageW(
            hinst, str(ico_path), 1, 16, 16, 0x10
        )
        if not hicon_big and not hicon_small:
            logger.debug(f"{LOG_PREFIX} LoadImageW gav 0 HICON")
            return False
        WM_SETICON, ICON_SMALL, ICON_BIG = 0x80, 0, 1
        GCLP_HICON, GCLP_HICONSM = -14, -34
        if hicon_big:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon_big)
            user32.SetClassLongPtrW(hwnd, GCLP_HICON, hicon_big)
        if hicon_small:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon_small)
            user32.SetClassLongPtrW(hwnd, GCLP_HICONSM, hicon_small)
        logger.info(
            f"{LOG_PREFIX} Win32-ikon satt: HWND={hwnd} "
            f"big={bool(hicon_big)} small={bool(hicon_small)}"
        )
        return True
    except Exception as e:
        logger.warning(f"{LOG_PREFIX} apply_win32_process_icon: {e}")
        return False
