# -*- coding: utf-8 -*-
"""
find_widget.py — Diagnostisera VAR widget-fönstret är (NYTT v6.4.1 v7)
====================================================================
Kör detta för att ta reda på:
  - Var widget-fönstret är (position, storlek, HWND)
  - Om det syns (IsWindowVisible)
  - Om det täcks av andra fönster
  - Vilken skärm det är på
  - HWND z-order

Användning:
    python ui/debug/find_widget.py

Loggar hamnar i data/logs/find_widget_*.log.
10000% loggning med [FindWidget]-prefix.
"""
from __future__ import annotations

import logging
import sys
import time
import traceback
from pathlib import Path

# ===========================================================================
# SÖKVÄGS-UPPSTART
# ===========================================================================
SCRIPT_DIR = Path(__file__).resolve().parent  # ui/debug/
PROJECT_ROOT = SCRIPT_DIR.parent.parent        # <root>
sys.path.insert(0, str(PROJECT_ROOT))

# ===========================================================================
# LOGGER
# ===========================================================================
LOG_PREFIX = "[FindWidget]"
log = logging.getLogger("FindWidget")
log.setLevel(logging.DEBUG)
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(logging.Formatter(
    "%(asctime)s.%(msecs)03d | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
))
log.addHandler(_handler)


# ===========================================================================
# VERSION + AI-FELSÖKNING 10000% (NY v6.4.1 v7)
# ===========================================================================
FIND_WIDGET_VERSION: str = "6.4.1-v7"
FIND_WIDGET_LOG_PREFIX: str = "[FindWidget]"


_FIND_WIDGET_ERROR_TRANSLATIONS: dict = {
    "ImportError": "Kan inte hitta en Python-modul",
    "ModuleNotFoundError": "Python-modul saknas",
    "AttributeError": "Objektet saknar en metod/attribut",
    "TypeError": "Fel typ av argument skickades",
    "ValueError": "Ogiltigt varde for find-widget",
    "KeyError": "Nyckel saknas i find-data",
    "FileNotFoundError": "Widget-filen hittades inte",
    "PermissionError": "Saknar ratigheter till widget-data",
    "OSError": "Operativsystem-fel vid find-widget",
    "TimeoutError": "Tidsgrans overskreds",
}


def _describe_find_exception(exc: BaseException) -> str:
    """NY v6.4.1 v7: Svensk forklaring av find-widget-relaterat fel."""
    try:
        exc_type = type(exc).__name__
        svensk_typ = _FIND_WIDGET_ERROR_TRANSLATIONS.get(
            exc_type, f"Tekniskt fel ({exc_type})"
        )
        msg = str(exc).strip()
        if not msg:
            return svensk_typ
        return f"{svensk_typ}: {msg}"
    except Exception:
        return f"Okant fel: {type(exc).__name__}"


def _format_compact_traceback(exc: BaseException, max_frames: int = 5) -> str:
    """NY v6.4.1 v7: Kompakt stacktrace for loggar."""
    try:
        tb_lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
        if len(tb_lines) <= max_frames + 3:
            return "".join(tb_lines)
        header = tb_lines[0]
        middle_frame = tb_lines[1] if len(tb_lines) > 1 else ""
        last_frames = tb_lines[-(max_frames):]
        return (
            header
            + middle_frame
            + f"  ... ({len(tb_lines) - max_frames - 1} frames utelamnade) ...\n"
            + "".join(last_frames)
        )
    except Exception:
        return f"{type(exc).__name__}: {exc}"


def _categorize_find_exception(exc: BaseException) -> str:
    """NY v6.4.1 v7: Kategorisera undantag."""
    try:
        exc_type = type(exc).__name__
        if exc_type in ("ValueError", "KeyError", "TypeError"):
            return "user_input"
        if exc_type in ("ImportError", "ModuleNotFoundError"):
            return "external"
        if exc_type in ("OSError", "FileNotFoundError", "PermissionError"):
            return "system"
        if "Qt" in exc_type or "PySide" in str(exc):
            return "external"
        return "code_bug"
    except Exception:
        return "code_bug"


_FIND_WIDGET_PLUGIN_DEPS = (
    {
        "pip_name": "PySide6",
        "import_name": "PySide6",
        "description_svenska": "Qt-gränssnitt (krav for find-widget)",
        "benefit_svenska": "Utan denna kan inte find_widget.py kora",
        "required": True,
    },
)


def get_find_widget_plugin_deps() -> list:
    """NY v6.4.1 v7: Optional Python-beroenden som find_widget vill ha."""
    return [dict(d) for d in _FIND_WIDGET_PLUGIN_DEPS]


__all__ = [
    "FIND_WIDGET_VERSION", "FIND_WIDGET_LOG_PREFIX",
    "_describe_find_exception", "_format_compact_traceback",
    "_categorize_find_exception", "get_find_widget_plugin_deps",
    "main",
]


# ===========================================================================
# HUVUDFUNKTION
# ===========================================================================
def main() -> int:
    """Diagnostisera widget-fönstrets position + synlighet."""
    log.info("=" * 70)
    log.info("FIND WIDGET — diagnostisera widget-fönstret")
    log.info("=" * 70)

    # 1. Ladda moduler
    try:
        import importlib.util
        settings_path = PROJECT_ROOT / "core" / "settings.py"
        widget_path = PROJECT_ROOT / "ui" / "widget.py"
        spec_s = importlib.util.spec_from_file_location("settings", settings_path)
        sm = importlib.util.module_from_spec(spec_s)
        sys.modules["settings"] = sm
        spec_s.loader.exec_module(sm)
        spec_w = importlib.util.spec_from_file_location("widget", widget_path)
        wm = importlib.util.module_from_spec(spec_w)
        sys.modules["widget"] = wm
        spec_w.loader.exec_module(wm)
        log.info("✓ settings + widget importerade")
    except Exception as e:
        log.error(f"✗ Import misslyckades: {e}")
        traceback.print_exc()
        return 1

    # 2. Qt
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(False)
        log.info("✓ QApplication skapad")
    except ImportError as e:
        log.error(f"✗ PySide6 saknas: {e}")
        return 1

    # 3. Skapa settings + hämta window_configs
    try:
        settings = sm.Settings()
        configs = settings.window_configs() or []
        log.info(f"✓ Settings skapad, {len(configs)} window_configs")
    except Exception as e:
        log.error(f"✗ Settings misslyckades: {e}")
        traceback.print_exc()
        return 1

    # 4. Lista alla skärmar
    log.info("")
    log.info("=" * 70)
    log.info("STEG 1: Skärmar")
    log.info("=" * 70)
    screens = QGuiApplication.screens()
    primary = QGuiApplication.primaryScreen()
    log.info(f"Antal skärmar: {len(screens)}")
    for i, screen in enumerate(screens):
        g = screen.geometry()
        is_primary = " (PRIMÄR)" if screen == primary else ""
        log.info(
            f"  [{i}] {g.width()}x{g.height()} @ ({g.x()},{g.y()}){is_primary}"
        )

    # 5. Försök skapa widget för varje config
    log.info("")
    log.info("=" * 70)
    log.info("STEG 2: Widgets")
    log.info("=" * 70)

    if not configs:
        log.warning("Inga window_configs — skapar default (100, 100)")
        settings.add_window(100, 100)
        settings.save()
        configs = settings.window_configs() or []

    widgets = []
    for conf in configs:
        win_id = conf.get("id", "?")
        x = conf.get("x", 100)
        y = conf.get("y", 100)
        log.info("")
        log.info(f"--- Widget win_id={win_id} config=({x},{y}) ---")
        try:
            store = None
            try:
                store_path = PROJECT_ROOT / "core" / "store.py"
                spec_st = importlib.util.spec_from_file_location("store", store_path)
                stm = importlib.util.module_from_spec(spec_st)
                sys.modules["store"] = stm
                spec_st.loader.exec_module(stm)
                store = stm.TaskStore()
                log.info(f"  ✓ Store skapad")
            except Exception as e:
                log.warning(f"  ⚠ Store misslyckades: {e}, använder dummy")

            w = wm.TodoWidget(primary, store, settings, win_id=win_id)
            w.show()
            log.info(f"  ✓ Widget skapad + visad")

            # Ge Qt lite tid att rita
            QGuiApplication.processEvents()
            time.sleep(0.1)
            QGuiApplication.processEvents()

            # Position + storlek
            actual_x, actual_y = w.x(), w.y()
            actual_w, actual_h = w.width(), w.height()
            log.info(f"  Position efter show(): ({actual_x}, {actual_y})")
            log.info(f"  Storlek: {actual_w}x{actual_h}")

            # HWND + synlighet (Windows)
            hwnd = int(w.winId())
            log.info(f"  HWND: {hwnd}")

            if sys.platform == "win32" and hwnd:
                import ctypes
                user32 = ctypes.windll.user32
                is_visible = user32.IsWindowVisible(hwnd)
                is_iconic = user32.IsIconic(hwnd)  # Minimerad?
                # Z-order: får widget reda på vem som ligger över?
                hwnd_above = user32.GetWindow(hwnd, 3)  # GWND_HWNDPREV = 3
                hwnd_below = user32.GetWindow(hwnd, 6)  # GWND_HWNDNEXT = 6
                log.info(f"  IsWindowVisible: {bool(is_visible)}")
                log.info(f"  IsIconic (minimerad): {bool(is_iconic)}")
                log.info(f"  HWND over: {hwnd_above}")
                log.info(f"  HWND under: {hwnd_below}")
                if not is_visible:
                    log.warning(
                        f"  >>> WIDGET ÄR DOLD! <<< Kör ShowWindow(hwnd, 5) för SW_SHOW"
                    )

            # Finns den på en skärm?
            for screen in screens:
                g = screen.geometry()
                if (g.x() <= actual_x <= g.x() + g.width() - 10 and
                        g.y() <= actual_y <= g.y() + g.height() - 10):
                    log.info(
                        f"  ✓ På skärm {g.width()}x{g.height()} @ ({g.x()},{g.y()})"
                    )
                    break
            else:
                log.warning(f"  >>> UTANFÖR ALLA SKÄRMAR! <<<")
                log.warning(
                    f"  >>> Flytta till primary: ({primary.geometry().x() + 100}, "
                    f"{primary.geometry().y() + 100})"
                )

            widgets.append(w)
        except Exception as e:
            log.error(f"  ✗ Widget misslyckades: {e}")
            traceback.print_exc()

    # 6. Summering + åtgärd
    log.info("")
    log.info("=" * 70)
    log.info("STEG 3: Summering")
    log.info("=" * 70)
    log.info(f"Antal widgets skapade: {len(widgets)}")
    if widgets:
        log.info(f"Första widget: win_id={widgets[0].win_id}, "
                 f"pos=({widgets[0].x()},{widgets[0].y()})")

    log.info("")
    log.info("=" * 70)
    log.info("ÅTGÄRDER (om widget inte syns):")
    log.info("=" * 70)
    log.info("1. Om HWND över != 0 — widget kan täckas av Explorer/taskbar")
    log.info("   → Klick på tray-ikonen ska aktivera 'Visa vid markören'")
    log.info("")
    log.info("2. Om widget är UTANFÖR skärm — flytta med:")
    log.info("   python -c \"from core.utils import find_safe_screen_position\"")
    log.info("")
    log.info("3. Om IsWindowVisible = False — kör:")
    log.info("   user32.ShowWindow(hwnd, 5)  # SW_SHOW")
    log.info("")
    log.info("4. Om allt annat misslyckas — stäng app + öppna igen från:")
    log.info("   Högerklick på tray → 'Diagnostik' → 'Visa alla fönster'")
    log.info("")
    log.info("Tryck Ctrl+C för att avsluta...")
    log.info("=" * 70)

    try:
        while True:
            QGuiApplication.processEvents()
            time.sleep(0.5)
    except KeyboardInterrupt:
        log.info("Avslutar...")
        return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log.critical(f"FATAL: {e}", exc_info=True)
        sys.exit(1)
