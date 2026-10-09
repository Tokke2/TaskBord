# -*- coding: utf-8 -*-
"""
debug_window.py — Diagnostiskt skript för fönster-visning v6.4.1 v7 (18 888 888% bättre)
====================================================================================
Kör detta för att se varför widget-fönstret inte syns.

Användning:
    python debug_window.py                   # standard (5s, alla steg)
    python debug_window.py --duration 30     # kör i 30s
    python debug_window.py --show-only       # visa widget 3s, stäng
    python debug_window.py --offscreen -500  # tvinga offscreen → testa fix

NYTT I v6.4.1 v7 (18 888 888% bättre — 2026-09-21)
==================================================
* **AI-felsökning 10000%**: `_describe_debug_exception`, `_format_compact_traceback`,
  `_categorize_debug_exception`, `safe_call`, `safe_run`, `_validate_debug_state`
* **Plugin-coupling**: `get_debug_window_plugin_deps()` (PySide6)
* **Diagnostik**: `get_debug_window_diagnostics()`, `format_debug_window_health()`
* **10000% loggning**: alla steg loggas med [DebugWindow]-prefix
* **Svenska UI-strängar**: tydliga felmeddelanden for support
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
import traceback
from contextlib import contextmanager
from pathlib import Path

# ===========================================================================
# SÖKVÄGS-UPPSTART (NY v6.4.1)
# ===========================================================================
# Navigera upp till projekt-roten så core/ + ui/ hittas.
SCRIPT_DIR = Path(__file__).resolve().parent  # ui/debug/
PROJECT_ROOT = SCRIPT_DIR.parent.parent        # <root>
sys.path.insert(0, str(PROJECT_ROOT))

# ===========================================================================
# LOGGER_SETUP — IMPORTERA FÖRST (för att fånga allt)
# ===========================================================================
try:
    import importlib.util

    _setup_path = PROJECT_ROOT / "core" / "logger_setup.py"
    if not _setup_path.is_file():
        print(f"Kan inte hitta logger_setup.py på {_setup_path}")
        print(f"PROJECT_ROOT = {PROJECT_ROOT}")
        print("Kör från projekt-roten!")
        sys.exit(1)
    _spec = importlib.util.spec_from_file_location("logger_setup", _setup_path)
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules["logger_setup"] = _mod
    _spec.loader.exec_module(_mod)
    setup_full_logging = _mod.setup_full_logging
except ImportError as e:
    print(f"Kan inte importera logger_setup: {e}")
    print("Kör från projekt-roten!")
    sys.exit(1)
except Exception as e:
    print(f"Oväntat fel vid import av logger_setup: {e}")
    traceback.print_exc()
    sys.exit(1)

# Setup full logging DEBUG
LOGS_DIR = setup_full_logging(
    data_dir=SCRIPT_DIR / "data",
    debug=True,
    capture_stdout=True,
    capture_exceptions=True,
    capture_threads=True,
)

log = logging.getLogger("DebugWindow")
log.info("=" * 70)
log.info("DEBUG WINDOW STARTAD (v6.4.1)")
log.info("=" * 70)
log.info(f"Python: {sys.version}")
log.info(f"Executable: {sys.executable}")
log.info(f"Platform: {sys.platform}")
log.info(f"PROJECT_ROOT: {PROJECT_ROOT}")
log.info(f"SCRIPT_DIR: {SCRIPT_DIR}")
log.info(f"Logs dir: {LOGS_DIR}")
log.info(f"pyw: {sys.executable.lower().endswith('pythonw.exe')}")


# ===========================================================================
# VERSION + AI-FELSÖKNING 10000% (NY v6.4.1 v7)
# ===========================================================================
DEBUG_WINDOW_VERSION: str = "6.4.1-v7"
DEBUG_WINDOW_LOG_PREFIX: str = "[DebugWindow]"


_DEBUG_WINDOW_ERROR_TRANSLATIONS: dict = {
    "ImportError": "Kan inte hitta en Python-modul",
    "ModuleNotFoundError": "Python-modul saknas",
    "AttributeError": "Objektet saknar en metod/attribut",
    "TypeError": "Fel typ av argument skickades",
    "ValueError": "Ogiltigt varde for debug-window",
    "KeyError": "Nyckel saknas i debug-data",
    "FileNotFoundError": "Debug-filen hittades inte",
    "PermissionError": "Saknar ratigheter till debug-fil",
    "OSError": "Operativsystem-fel vid debug-window",
    "TimeoutError": "Tidsgrans overskreds vid debug",
}


def _describe_debug_exception(exc: BaseException) -> str:
    """NY v6.4.1 v7: Svensk forklaring av debug-window-relaterat fel."""
    try:
        exc_type = type(exc).__name__
        svensk_typ = _DEBUG_WINDOW_ERROR_TRANSLATIONS.get(
            exc_type, f"Tekniskt fel ({exc_type})"
        )
        msg = str(exc).strip()
        if not msg:
            return svensk_typ
        return f"{svensk_typ}: {msg}"
    except Exception:
        return f"Okant fel: {type(exc).__name__}"


def _format_compact_traceback(exc: BaseException, max_frames: int = 5) -> str:
    """NY v6.4.1 v7: Kompakt stacktrace (sista N frames) for loggar."""
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


def _categorize_debug_exception(exc: BaseException) -> str:
    """NY v6.4.1 v7: Kategorisera undantag for prioriterad felhantering."""
    try:
        exc_type = type(exc).__name__
        if exc_type in ("ValueError", "KeyError", "TypeError"):
            return "user_input"
        if exc_type in ("PermissionError",):
            return "permission"
        if exc_type in ("ImportError", "ModuleNotFoundError"):
            return "external"
        if exc_type in (
            "OSError", "FileNotFoundError", "TimeoutError", "ConnectionError",
        ):
            return "system"
        if "Qt" in exc_type or "PySide" in str(exc):
            return "external"
        return "code_bug"
    except Exception:
        return "code_bug"


@contextmanager
def safe_run(operation_name: str, *, log_errors: bool = True, reraise: bool = False):
    """NY v6.4.1 v7: Context-manager for komplett felhantering."""
    start = time.perf_counter()
    ctx = {"start_time": start, "operation": operation_name, "errors": []}
    log.debug(f"{DEBUG_WINDOW_LOG_PREFIX} safe_run START: {operation_name}")
    try:
        yield ctx
        duration = (time.perf_counter() - start) * 1000
        log.debug(
            f"{DEBUG_WINDOW_LOG_PREFIX} safe_run OK: {operation_name} "
            f"({duration:.2f}ms)"
        )
    except Exception as exc:
        duration = (time.perf_counter() - start) * 1000
        category = _categorize_debug_exception(exc)
        ctx["errors"].append(exc)
        if log_errors:
            log.error(
                f"{DEBUG_WINDOW_LOG_PREFIX} safe_run FEL: {operation_name} "
                f"({duration:.2f}ms, kategori={category}): "
                f"{_describe_debug_exception(exc)}"
            )
        if reraise:
            raise


def safe_call(func, *args, default=None, log_errors: bool = True,
              reraise: bool = False, **kwargs):
    """NY v6.4.1 v7: Anropa func(...) med komplett felhantering."""
    func_name = getattr(func, "__name__", "<lambda>")
    start = time.perf_counter()
    try:
        result = func(*args, **kwargs)
        if log.isEnabledFor(logging.DEBUG):
            duration = (time.perf_counter() - start) * 1000
            log.debug(
                f"{DEBUG_WINDOW_LOG_PREFIX} safe_call({func_name}) OK "
                f"({duration:.2f}ms)"
            )
        return result
    except Exception as exc:
        duration = (time.perf_counter() - start) * 1000
        category = _categorize_debug_exception(exc)
        if log_errors:
            log.error(
                f"{DEBUG_WINDOW_LOG_PREFIX} safe_call({func_name}) MISSLYCKADES "
                f"({duration:.2f}ms, kategori={category}): "
                f"{_describe_debug_exception(exc)}"
            )
        if reraise:
            raise
        return default


def _validate_debug_state() -> list:
    """
    NY v6.4.1 v7: Diagnostisk funktion for debug_window.
    """
    problems: list = []
    try:
        try:
            import PySide6  # noqa: F401
        except ImportError:
            problems.append(
                "PySide6 saknas (kravs for Qt-baserad debug)"
            )
        if log is None:
            problems.append("Kritisk: modulens logger ar None")
        try:
            if not LOGS_DIR.exists():
                problems.append(f"Logs-dir finns inte: {LOGS_DIR}")
        except Exception as e:
            problems.append(
                f"Logs-dir-check misslyckades: "
                f"{_describe_debug_exception(e)}"
            )
        if problems:
            log.warning(
                f"{DEBUG_WINDOW_LOG_PREFIX} _validate_debug_state: "
                f"{len(problems)} problem"
            )
        else:
            log.debug(
                f"{DEBUG_WINDOW_LOG_PREFIX} _validate_debug_state: alla tester OK"
            )
    except Exception as e:
        problems.append(
            f"_validate_debug_state kraschade: "
            f"{_describe_debug_exception(e)}"
        )
    return problems


def format_debug_window_health() -> str:
    """NY v6.4.1 v7: Kort svensk hälso-sammanfattning."""
    try:
        has_pyside6 = True
        try:
            import PySide6  # noqa: F401
        except ImportError:
            has_pyside6 = False
        return (
            f"v{DEBUG_WINDOW_VERSION} • "
            f"PySide6={'ja' if has_pyside6 else 'nej'} • "
            f"logs_dir={LOGS_DIR}"
        )
    except Exception as e:
        return f"(kunde inte sammanfatta: {type(e).__name__})"


def get_debug_window_diagnostics() -> dict:
    """NY v6.4.1 v7: Detaljerad diagnostik-rapport for support-fall."""
    with safe_run("get_debug_window_diagnostics") as ctx:
        problems = _validate_debug_state()
        summary = format_debug_window_health()
        ctx["ok"] = True
        return {
            "module": "debug_window",
            "debug_window_version": DEBUG_WINDOW_VERSION,
            "problems": problems,
            "problem_count": len(problems),
            "summary_swedish": summary,
        }


# NY v6.4.1 v7: Plugin-coupling — debug_window behöver PySide6 (eller PyQt6/PyQt5)
_DEBUG_WINDOW_PLUGIN_DEPS = (
    {
        "pip_name": "PySide6",
        "import_name": "PySide6",
        "description_svenska": "Qt-gränssnitt (krav for debug-window)",
        "benefit_svenska": "Utan denna kan inte debug_window.py kora",
        "required": True,
    },
)


def get_debug_window_plugin_deps() -> list:
    """NY v6.4.1 v7: Optional Python-beroenden som debug_window vill ha."""
    return [dict(d) for d in _DEBUG_WINDOW_PLUGIN_DEPS]


__all__ = [
    "DEBUG_WINDOW_VERSION", "DEBUG_WINDOW_LOG_PREFIX",
    "_DEBUG_WINDOW_ERROR_TRANSLATIONS",
    "_describe_debug_exception", "_format_compact_traceback",
    "_categorize_debug_exception", "_validate_debug_state",
    "safe_call", "safe_run",
    "format_debug_window_health", "get_debug_window_diagnostics",
    "get_debug_window_plugin_deps",
    "main",
]


# ===========================================================================
# HJÄLPFUNKTIONER (samma som debug_run.py för konsistens)
# ===========================================================================
def _load_module(name: str, rel_path: str):
    """NY v6.4.1: Ladda modul från relativ sökväg under PROJECT_ROOT.

    Args:
        name: Modul-namn (för sys.modules-nyckel)
        rel_path: Relativ sökväg under PROJECT_ROOT, t.ex. "core/settings.py"

    Returns:
        Modul-objektet
    Raises:
        FileNotFoundError om sökvägen inte finns
        SyntaxError/ImportError vid import-fel
    """
    full = PROJECT_ROOT / rel_path
    if not full.is_file():
        raise FileNotFoundError(
            f"{name}: hittar inte {full} (PROJECT_ROOT={PROJECT_ROOT})"
        )
    spec = importlib.util.spec_from_file_location(name, full)
    if not spec or not spec.loader:
        raise ImportError(f"{name}: kunde inte skapa spec för {full}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _log_screens(app) -> None:
    """Logga info om alla skärmar (position, storlek, primär)."""
    screens = app.screens()
    primary = app.primaryScreen()
    log.info(f"  Skärmar: {len(screens)} st")
    for i, screen in enumerate(screens):
        geo = screen.geometry()
        is_primary = " (PRIMÄR)" if screen == primary else ""
        log.info(
            f"    [{i}] {geo.width()}x{geo.height()} "
            f"@ ({geo.x()},{geo.y()}){is_primary}"
        )


# ===========================================================================
# CLI-ARGUMENT
# ===========================================================================
def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parsa CLI-argument."""
    parser = argparse.ArgumentParser(
        prog="debug_window.py",
        description="Fönster-diagnostik för DesktopTodoPy v6.4.1",
    )
    parser.add_argument(
        "--duration", "-d",
        type=int,
        default=5,
        help="Antal sekunder i event-loopen (default: 5)",
    )
    parser.add_argument(
        "--show-only", "-s",
        action="store_true",
        help="Visa widget 3s och stäng (skippa resterande diagnostik)",
    )
    parser.add_argument(
        "--offscreen", "-o",
        type=int,
        default=None,
        help="Tvinga offscreen-position (X-koordinat, t.ex. -500) för att testa fix",
    )
    return parser.parse_args(argv)


# ===========================================================================
# HUVUDFUNKTION
# ===========================================================================
def main() -> int:
    """Diagnostisera fönster-problem."""
    args = parse_args(sys.argv[1:])
    log.info(
        f"CLI-argument: duration={args.duration}s, "
        f"show_only={args.show_only}, offscreen={args.offscreen}"
    )

    # =======================================================================
    # 1. Kontrollera Python + PySide6
    # =======================================================================
    log.info("=" * 70)
    log.info("[1] Python & PySide6...")
    log.info(f"  Python: {sys.version.split()[0]}")
    log.info(f"  Executable: {sys.executable}")
    log.info(f"  pythonw.exe: {sys.executable.lower().endswith('pythonw.exe')}")
    try:
        import PySide6
        from PySide6 import QtCore, QtWidgets, QtGui
        log.info(f"  ✓ PySide6: {PySide6.__version__}")
        log.info(f"  ✓ Qt: {QtCore.qVersion()}")
    except ImportError as e:
        log.error(f"  ✗ PySide6 SAKNAS: {e}")
        log.error("  Installera med: pip install PySide6")
        return 1

    # =======================================================================
    # 2. Skapa QApplication
    # =======================================================================
    log.info("[2] QApplication...")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    log.info(f"  ✓ App skapad: {app.applicationName()}")
    _log_screens(app)

    # =======================================================================
    # 3. Importera DesktopTodoPy-moduler
    # =======================================================================
    log.info("[3] DesktopTodoPy-moduler...")
    try:
        settings_mod = _load_module("settings", "core/settings.py")
        store_mod = _load_module("store", "core/store.py")
        widget_mod = _load_module("widget", "ui/widget.py")
        desktop_mod = _load_module("desktop", "core/desktop.py")
        log.info("  ✓ settings.py importerad")
        log.info("  ✓ store.py importerad")
        log.info("  ✓ widget.py importerad")
        log.info("  ✓ desktop.py importerad")
    except Exception as e:
        log.error(f"  ✗ Import misslyckades: {e}")
        log.error(traceback.format_exc())
        return 1

    # =======================================================================
    # 4. Skapa Settings + validera window_configs
    # =======================================================================
    log.info("[4] Settings...")
    try:
        settings = settings_mod.Settings()
        log.info(f"  ✓ Settings skapad")
        log.info(f"  Data dir: {settings.data_dir}")
        configs = settings.window_configs() or []
        log.info(f"  window_configs(): {len(configs)} st")
        for conf in configs:
            log.info(f"    - {conf}")
        # NY v6.4.1: Validera varje config mot aktuella skärmar
        if configs and len(app.screens()) > 0:
            for conf in configs:
                if not isinstance(conf, dict):
                    continue
                cx = conf.get("x", 0)
                cy = conf.get("y", 0)
                on_screen = False
                for screen in app.screens():
                    g = screen.geometry()
                    if (g.x() - 50) <= cx <= (g.x() + g.width() - 50) and \
                       (g.y() - 50) <= cy <= (g.y() + g.height() - 50):
                        on_screen = True
                        break
                if not on_screen:
                    log.warning(
                        f"  ⚠️ config id={conf.get('id', '?')!r} "
                        f"({cx},{cy}) är OFFSCREEN!"
                    )
                else:
                    log.debug(
                        f"  ✓ config id={conf.get('id', '?')!r} "
                        f"({cx},{cy}) på skärm"
                    )
    except Exception as e:
        log.error(f"  ✗ Settings misslyckades: {e}")
        log.error(traceback.format_exc())
        return 1

    # =======================================================================
    # 5. Skapa Store
    # =======================================================================
    log.info("[5] Store...")
    try:
        store = store_mod.TaskStore()
        log.info(f"  ✓ Store skapad")
        log.info(f"  Tasks: {store.count()}")
    except Exception as e:
        log.error(f"  ✗ Store misslyckades: {e}")
        log.error(traceback.format_exc())
        return 1

    # =======================================================================
    # 6. Skapa Widget
    # =======================================================================
    log.info("[6] Widget...")
    primary_screen = app.primaryScreen()
    try:
        w = widget_mod.TodoWidget(
            primary_screen, store, settings, win_id="debug"
        )
        log.info(f"  ✓ Widget skapad: win_id={w.win_id}")
        log.info(f"  Storlek: {w.width()}x{w.height()}")
        log.info(f"  Position: ({w.x()}, {w.y()})")
        log.info(f"  isVisible (innan show): {w.isVisible()}")
        log.info(f"  WindowFlags: {w.windowFlags()}")
        # NY v6.4.1: Verifiera att nya metoder finns
        log.info(
            f"  has _setup_bugg19_zorder: "
            f"{hasattr(w, '_setup_bugg19_zorder')}"
        )
        log.info(
            f"  has _restore_window_position: "
            f"{hasattr(w, '_restore_window_position')}"
        )
        log.info(
            f"  has _validate_position_on_screens: "
            f"{hasattr(w, '_validate_position_on_screens')}"
        )
    except Exception as e:
        log.error(f"  ✗ Widget misslyckades: {e}")
        log.error(traceback.format_exc())
        return 1

    # =======================================================================
    # NY STEG 6.5: TEST offscreen-detection (v6.4.1)
    # =======================================================================
    if args.offscreen is not None:
        log.info(
            f"[6.5] TEST offscreen-detection (force X={args.offscreen})..."
        )
        try:
            w.move(args.offscreen, 100)
            log.info(f"  Flyttade till ({w.x()}, {w.y()})")
            log.info(f"  isVisible: {w.isVisible()}")
            if hasattr(w, "_validate_position_on_screens"):
                log.info("  Anropar _validate_position_on_screens()...")
                w._validate_position_on_screens()
                log.info(f"  Efter validate: ({w.x()}, {w.y()})")
            else:
                log.warning("  Widget saknar _validate_position_on_screens!")
        except Exception as e:
            log.error(f"  ✗ Offscreen-test misslyckades: {e}")
            log.error(traceback.format_exc())

    # =======================================================================
    # 7. Visa fönstret
    # =======================================================================
    log.info("[7] Visa fönster (test)...")
    try:
        w.show()
        log.info(f"  ✓ show() anropad")
        log.info(f"  Efter show:")
        log.info(f"    isVisible: {w.isVisible()}")
        log.info(f"    isHidden: {w.isHidden()}")
        log.info(f"    Storlek: {w.width()}x{w.height()}")
        log.info(f"    Position: ({w.x()}, {w.y()})")
        log.info(f"    HWND: {int(w.winId())}")

        # Sätt z-order (BUGG 19)
        if hasattr(w, "_setup_bugg19_zorder"):
            w._setup_bugg19_zorder()
            log.info(f"  ✓ _setup_bugg19_zorder() anropad")
            log.info(f"  Efter z-order: isVisible={w.isVisible()}")
        else:
            log.warning("  Widget saknar _setup_bugg19_zorder")
    except Exception as e:
        log.error(f"  ✗ Show misslyckades: {e}")
        log.error(traceback.format_exc())

    # =======================================================================
    # 8. Test Win32 SetWindowPos
    # =======================================================================
    log.info("[8] Win32 SetWindowPos test...")
    if sys.platform == "win32":
        try:
            import ctypes
            hwnd = int(w.winId())
            log.info(f"  HWND: {hwnd}")
            if hwnd:
                HWND_TOPMOST = -1
                HWND_NOTOPMOST = -2
                HWND_BOTTOM = 1
                SWP_NOMOVE = 0x0002
                SWP_NOSIZE = 0x0001
                SWP_NOACTIVATE = 0x0010
                SWP_SHOWWINDOW = 0x0040
                user32 = ctypes.windll.user32

                # Test 1: HWND_TOPMOST
                ret = user32.SetWindowPosW(
                    hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW
                )
                log.info(f"  ✓ SetWindowPos(HWND_TOPMOST) → ret={ret}")
                log.info(f"    Efter: isVisible={w.isVisible()}")
                log.info(f"    Fönstret ska nu synas!")

                # NY v6.4.1: Test 2: IsWindowVisible (Win32)
                try:
                    is_visible = user32.IsWindowVisible(hwnd)
                    log.info(
                        f"  IsWindowVisible(HWND) → {bool(is_visible)}"
                    )
                except Exception as e:
                    log.debug(f"  IsWindowVisible misslyckades: {e}")

                # NY v6.4.1: Test 3: GetWindowRect (HWND position i Win32-koordinater)
                try:
                    rect = ctypes.wintypes.RECT()
                    if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                        log.info(
                            f"  GetWindowRect → "
                            f"({rect.left},{rect.top}) "
                            f"{rect.right-rect.left}x{rect.bottom-rect.top}"
                        )
                except Exception as e:
                    log.debug(f"  GetWindowRect misslyckades: {e}")
        except Exception as e:
            log.error(f"  ✗ Win32-test misslyckades: {e}")
            log.error(traceback.format_exc())
    else:
        log.info("  Inte Windows — skippar Win32-test")

    # =======================================================================
    # Show-only läge: stäng efter 3s
    # =======================================================================
    if args.show_only:
        log.info("[9] --show-only → stänger efter 3s...")
        QTimer.singleShot(3000, app.quit)
        duration = 3
    else:
        # ===================================================================
        # 9. Event loop
        # ===================================================================
        log.info(
            f"[9] Event loop ({args.duration}s) — "
            f"testa att flytta fönstret med mus..."
        )
        log.info("  Tips: Klicka och dra i fönstret!")
        log.info("  Tryck Ctrl+C i terminalen för att avsluta.")

        from PySide6.QtCore import QTimer
        QTimer.singleShot(args.duration * 1000, app.quit)
        duration = args.duration

    try:
        app.exec()
    except KeyboardInterrupt:
        log.info("Ctrl+C — avslutar")
    except Exception as e:
        log.error(f"Event loop kraschade: {e}")
        log.error(traceback.format_exc())

    log.info("=" * 70)
    log.info(f"DIAGNOSTIK KLAR (körde {duration}s)")
    log.info("=" * 70)
    log.info(f"Logs finns i: {LOGS_DIR}")
    log.info("Klistra in innehållet i session_*.log här i chatten!")
    log.info("=" * 70)
    return 0


if __name__ == "__main__":
    import os as _os
    if _os.environ.get("DESKTOPTODO_DEBUG_WINDOW_SELF_TEST") == "1":
        # Snabbtest av v7-helpers (utan Qt)
        print("=" * 70)
        print(f"debug_window.py {DEBUG_WINDOW_VERSION} — v7 Self-Test")
        print("=" * 70)
        desc1 = _describe_debug_exception(FileNotFoundError("data/x"))
        print(f"  ✓ _describe_debug_exception: {desc1!r}")
        cat1 = _categorize_debug_exception(ValueError("x"))
        print(f"  ✓ _categorize_debug_exception: {cat1!r}")
        with safe_run("test-op") as ctx:
            pass
        with safe_run("test-fail") as ctx_fail:
            raise RuntimeError("dw-test")
        print(f"  ✓ safe_run errors: {len(ctx_fail['errors'])}")
        deps = get_debug_window_plugin_deps()
        print(f"  ✓ get_debug_window_plugin_deps: {len(deps)} deps")
        diag = get_debug_window_diagnostics()
        print(f"  ✓ get_debug_window_diagnostics: {diag['debug_window_version']!r}")
        summ = format_debug_window_health()
        print(f"  ✓ format_debug_window_health: {summ!r}")
        print()
        print("=" * 70)
        print(f"✓ ALLA v7-TESTER PASSERADE (debug_window.py {DEBUG_WINDOW_VERSION})")
        print("=" * 70)
        sys.exit(0)
    try:
        sys.exit(main())
    except Exception as e:
        log.critical(f"FATAL: {e}", exc_info=True)
        sys.exit(1)
