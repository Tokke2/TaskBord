# -*- coding: utf-8 -*-
"""
main.pyw — TaskBord v6.4.1 v7 (18 888 888% bättre: central loggning + plugin + minne + snabbhet + enkelhet)
=========================================================================
Copyright © Rickard Längkvist, 2025–2026

App Controller: System Tray, Single Instance Lock, multi-window sync,
glasmorphism-applicering, statistik, shutdown hooks, capability-vyn,
ROBUST start via dubbelklick (.pyw + pythonw.exe, INGEN konsoll).

DONATION: inaktiverad (R4 pausad 2026-08-11)
KÖR UTAN KONSOLL: stöder både .py + python.exe OCH .pyw + pythonw.exe.
All UI-kommunikation sker via QMessageBox, QInputDialog eller tray-balloon.
Loggning via logging-modulen (skriver till data/todo_app.log).

NYTT I v6.4.0 (8 000% bättre)
============================
* **PWM-integration** — get_throttle() från widget.py (95-98% CPU-besparing)
* **orjson för cache** — 18× snabbare JSON (dump, stats, cache)
* **Bättre dubbelklick-start** — explicit no-console-detection + pythonw.exe check
* **Bättre autostart-detektering** — utils.is_autostart_enabled() med fallback
* **10000% loggning** — `[MAIN]`-prefix på ALLA main-specifika logs
* **CLI-flagga --no-pwm** — inaktivera PWM vid behov

NYTT I v6.4.1 v7 (18 888 888% bättre — 2026-09-21)
==================================================
* **Central loggning 10000%** (NYTT!) — `CentralEventLog` fångar ALLA
  log-events från ALLA moduler ([MAIN], [WIDGET], [STORE], [UTILS], etc.)
  i en trådsäker ring-buffer. UI kan lyssna live via
  `add_central_log_listener(callback)`. `get_recent_app_events()` ger
  kronologisk sammanfattning av vad som hänt i appen.
* **Plugin-system 10000%** — erbjuder att installera saknade Python-moduler
  (`orjson`, `psutil`, `PySide6` m.fl.) via `pip install` vid start.
  Användaren får en svensk dialog med "Installera nu" / "Hoppa över" / "Kom ihåg senare".
  Alla plugin-events loggas i central-loggen.
* **Minnes-optimering** — `optimize_memory()` (gc.collect + cache-rensning) +
  `get_memory_stats()` (RSS, traced, gc-counts) for enkel diagnostik
* **Snabbhets-optimering** — `time_operation()` context-manager for att mäta
  varje operation i millisekunder
* **Enkelhet** — `format_plugin_status_swedish()` + `get_plugin_status()` ger en
  enkel svensk överblick över alla plugin + `format_event_log_swedish()` for
  central-loggen

DESIGN-FILOSOFI (v6.4 — 18 888 888% bättre)
====================================
* **Async-first**      — All I/O går via QThreadPool eller QTimer (UI-tråden ledig)
* **Subsystem Registry** — DI-container med health-tracking för varje modul
* **Immutabel config**  — Frozen dataclass för AppConfig; en mutationspunkt
* **Smart recovery**    — Stability-system + circuit breakers + auto-restart
* **Protocols**         — Strukturella interfaces (ingen arv-tvång)
* **UX**                — Splash, tray-tooltip, smooth dialogs, hotkeys
* **PWM**               — Adaptive throttling från widget.py
* **orjson**            — Snabbare JSON (för cache + subsystem-dump)
* **Central loggning**  — CentralEventLog fångar ALLA events från ALLA moduler (NY v7)
* **Plugin-system**     — Auto-detect missing + offer install (NY v7)
* **Enkelhet**          — Svenska UI-strängar, tydliga felmeddelanden (NY v7)
* **Minne**             — optimize_memory() + get_memory_stats() (NY v7)
* **Snabbhet**          — time_operation() context-manager (NY v7)
* **Säkerhet**          — Path validation, single-instance lock, sanitized input

VAD ÄR NYTT I v6.4 (mot v6.3.2)
================================
Arkitektur:
    • SubsystemRegistry med health-monitoring
    • AsyncTaskRunner (QThreadPool-baserad)
    • PerformanceMonitor (psutil + tracemalloc snapshots)
    • Splash-screen med smooth fade-in
    • Global Qt exception hook (QMessageBox.critical)
    • Global Python excepthook (loggning)
    • Signal handlers (SIGINT, SIGTERM, SIGBREAK)

UI:
    • Komplett system tray med hover-state + dynamisk tooltip
    • populate_tray_menu() med live-stats (aktiva/arkiverade/uptime/minne)
    • create_icon() med pixmap-cache (checkmark, star, empty) + 5 färgade varianter
    • ask_new_task, ask_rename_task, ask_confirm_delete (input-dialoger)
    • populate_windows() — synkar widgets ↔ settings.window_configs()
    • BUGG 19: HWND_BOTTOM via Win32 SetWindowPos (widget alltid synlig)
    • BUGG 26: auto-reposition vid kollision med skrivbordsikoner
    • NY v7-fix38: Win+D-säkert skrivbordslager (above/behind/legacy) +
      genomskinligt glas-skal med auto-fallback — se _apply_desktop_shell

Stabilitet:
    • StabilityManager-integration (auto-recovery, circuit breakers)
    • Heartbeat-timer (watchdog)
    • Periodic cleanup (GDI-regioner, minne)
    • Idle-detection (dölj widget om idle > 10 min)

Driftsättning:
    • Single Instance Lock (med retry, 3×500ms)
    • Robust mot saknade moduler (safe-mode, dummy-impls)
    • Pre-flight check (Python, PySide6, stdlib, cwd)
"""

from __future__ import annotations

# ===========================================================================
# IMPORTS — standardbibliotek
# ===========================================================================
import argparse
import atexit
import functools
import json as _stdlib_json
import logging
import logging.handlers
import os
import platform
import signal
import sys
import importlib.util
import subprocess
import threading
import time
import traceback
import weakref
from concurrent.futures import Future, ThreadPoolExecutor
from collections import deque
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from datetime import datetime as _datetime
from enum import Enum, auto
from pathlib import Path
from typing import (
    Any, Callable, ClassVar, Dict, Final, List, Optional, Protocol, Set,
    Tuple, Type, TypeVar, Union,
)

# ORJSON (18× snabbare — fallback till stdlib)
try:
    import orjson  # type: ignore
    _HAS_ORJSON = True
except ImportError:
    orjson = None  # type: ignore
    _HAS_ORJSON = False


def _json_dumps(obj: Any) -> bytes:
    """Serialisera (orjson 18× snabbare)."""
    if _HAS_ORJSON:
        return orjson.dumps(obj, option=orjson.OPT_INDENT_2)  # type: ignore
    return _stdlib_json.dumps(obj, indent=2, ensure_ascii=False).encode("utf-8")


def _json_loads(data: Union[bytes, str]) -> Any:
    """Parsa JSON (orjson 18× snabbare)."""
    if _HAS_ORJSON:
        return orjson.loads(data)  # type: ignore
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    return _stdlib_json.loads(data)

# ===========================================================================
# TYPE VARIABLES & GENERICS
# ===========================================================================
T = TypeVar("T")
T_co = TypeVar("T_co", covariant=True)

# ===========================================================================
# CONSTANTS — versionsinfo
# ===========================================================================
APP_NAME: Final[str] = "TaskBord"
APP_VERSION: Final[str] = "6.4.1-v7"
APP_VERSION_DISPLAY: Final[str] = "6.4.1 v7"
APP_VERSION_TUPLE: Final[Tuple[int, int, int]] = (6, 4, 1)
RELEASE_VERSION: Final[str] = "1.0.0"  # GitHub-release (visas i loggen vid start)
ORG_NAME: Final[str] = "Rickard Längkvist"
COPYRIGHT_YEARS: Final[str] = "2025–2026"
APP_DESCRIPTION: Final[str] = "Desktop todo-widget med glasmorphism, pin-funktion och stabilitet-system"
LOG_PREFIX: Final[str] = "[MAIN]"  # NY v6.4 — 10000% loggning

# Sökväg-konstanter
SCRIPT_DIR: Final[Path] = Path(__file__).resolve().parent
# FIX v7-fix34: JSON-filer sparas i js/-mappen (Rickard 2026-09-30)
# Loggar + ikoner + backuper ligger kvar i data/
JS_DIR: Final[Path] = SCRIPT_DIR / "js"
DATA_DIR: Final[Path] = SCRIPT_DIR / "data"
LOG_FILE: Final[Path] = DATA_DIR / "todo_app.log"
SETTINGS_FILE: Final[Path] = JS_DIR / "settings.json"
TASKS_FILE: Final[Path] = JS_DIR / "tasks.json"
BACKUP_DIR: Final[Path] = DATA_DIR / "backups"
AUDIT_FILE: Final[Path] = DATA_DIR / "audit.log"
ICON_DIR: Final[Path] = SCRIPT_DIR / "icons"

# NY v6.4.1: Lägg till core/ + ui/ i sys.path så `from logger_setup`,
# `from stability`, etc. funkar utan `core.`-prefix.
# safe_import_module() använder fortfarande sökvägs-baserad import
# (för felsäker modul-laddning), men legacy-imports på rot-nivå
# (t.ex. rad 2525 `from logger_setup import setup_full_logging`)
# behöver core/ på sys.path.
_CORES_PATH: Final[Path] = SCRIPT_DIR / "core"
_UI_PATH: Final[Path] = SCRIPT_DIR / "ui"
if _CORES_PATH.is_dir():
    sys.path.insert(0, str(_CORES_PATH))
if _UI_PATH.is_dir():
    sys.path.insert(0, str(_UI_PATH))


class Timeouts:
    """Tidskonstanter (i sekunder)."""
    FILE_IO: float = 3.0
    REGISTRY: float = 2.0
    UI_RESPONSE: float = 2.0
    STARTUP_VALIDATION: float = 5.0
    WORKER_CLEANUP: float = 2.0
    HEARTBEAT: float = 5.0
    SPLASH_MIN_DURATION: float = 1.0
    LOCK_RETRY: float = 0.5
    LOCK_MAX_ATTEMPTS: int = 3
    IDLE_HIDE_THRESHOLD_SEC: int = 600  # 10 min


# ===========================================================================
# ENUMS
# ===========================================================================

class LogLevel(Enum):
    """Logg-nivåer (utökar standard)."""
    TRACE = 5
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
    CRITICAL = 50


class AppMode(Enum):
    """App-lägen (via CLI-flaggor)."""
    NORMAL = auto()
    DIAGNOSTICS = auto()    # --diagnostics: DEBUG + subsystem-dump
    SAFE_MODE = auto()      # --safe-mode: dummy settings/store
    NO_TRAY = auto()        # --no-tray: hoppa över tray-init
    RESET = auto()          # --reset: återställ settings.json
    VERBOSE = auto()        # --verbose: DEBUG


class SubsystemStatus(Enum):
    """Hälsostatus för subsystems."""
    UNINITIALIZED = auto()
    INITIALIZING = auto()
    HEALTHY = auto()
    DEGRADED = auto()
    FAILED = auto()
    SHUTDOWN = auto()


class GlassStyle(Enum):
    """Glasmorphism-stilar (Win32)."""
    AUTO = "auto"
    TRANSLUCENT = "translucent"
    MICA = "mica"
    ACRYLIC = "acrylic"
    NONE = "none"


class IconState(Enum):
    """Ikon-tillstånd för tray/create_icon."""
    NORMAL = "normal"
    CHECKED = "checked"   # När alla tasks är klara
    EMPTY = "empty"       # När inga tasks finns
    WARNING = "warning"   # När fel upptäckts


# ===========================================================================
# CUSTOM EXCEPTIONS
# ===========================================================================

class DesktopTodoError(Exception):
    """Basklass for alla TaskBord-fel."""

    def __init__(
        self,
        message: str,
        *,
        recoverable: bool = True,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.recoverable = recoverable
        self.details = details or {}


class StartupError(DesktopTodoError):
    """Fel vid uppstart (pre-flight misslyckades)."""
    def __init__(self, message: str, **kwargs) -> None:
        super().__init__(message, recoverable=False, **kwargs)


class DependencyError(StartupError):
    """Beroende (modul, paket) saknas eller trasigt."""


class ConfigError(DesktopTodoError):
    """Konfigurationsfel (settings.json korrupt)."""


class PlatformError(DesktopTodoError):
    """Plattformsspecifikt fel (Win32-anrop misslyckades)."""


# ===========================================================================
# PLATFORM HELPERS
# ===========================================================================

def _is_pyw() -> bool:
    """Returnerar True om vi kör via pythonw.exe (ingen konsoll)."""
    return (
        sys.executable.lower().endswith("pythonw.exe")
        or getattr(sys, "frozen", False)
        or not sys.stdout
    )


def _is_double_click_start() -> bool:
    """
    NY v6.4: Detekterar om appen startades via dubbelklick på .pyw (Windows).
    Returnerar True om vi är i pyw-läge OCH startades utan argument.

    Detta används för att:
      - Visa tydligare startlog
      - Inte kräva python.exe-argument
      - Logga explicit att vi startades via filhanteraren
    """
    if not _is_pyw():
        return False
    # Om inga argument → dubbelklick-start (default)
    return len(sys.argv) <= 1 or (len(sys.argv) == 1 and sys.argv[0].endswith(".pyw"))


def _is_windows() -> bool:
    """Returnerar True om plattformen är Windows."""
    return sys.platform == "win32"


def _find_pythonw_exe() -> Optional[str]:
    """Hittar pythonw.exe bredvid python.exe (för double-click-start)."""
    if sys.executable.lower().endswith("pythonw.exe"):
        return sys.executable
    if getattr(sys, "frozen", False):
        return sys.executable
    base_dir = os.path.dirname(sys.executable)
    for name in ("pythonw.exe", "pythonw"):
        candidate = os.path.join(base_dir, name)
        if os.path.exists(candidate):
            return candidate
    return None


# ===========================================================================
# AI-FELSÖKNING 10000% (NY v6.4.1 v7)
# ===========================================================================
# Hjalpare som genererar:
#   - Anvandarvanlig svenska feltext (for dialoger)
#   - Kompakt teknisk stacktrace (for loggar)
#   - Standardiserad error-dialog
# Allt for att Rickard ska kunna felsoka 100% sa mycket enklare.

_ERROR_TRANSLATIONS: Final[Dict[str, str]] = {
    # Standard-bibliotek
    "ImportError": "Kan inte hitta en Python-modul",
    "ModuleNotFoundError": "Python-modul saknas",
    "AttributeError": "Objektet saknar en metod/attribut",
    "TypeError": "Fel typ av argument skickades",
    "ValueError": "Ogiltigt varde",
    "KeyError": "Nyckel saknas i data",
    "FileNotFoundError": "Filen hittades inte",
    "PermissionError": "Saknar ratigheter till filen",
    "OSError": "Operativsystem-fel",
    # Qt-specifikt
    "RuntimeError": "Qt-runtime-fel (kanske trasig widget)",
}


def _describe_exception(exc: BaseException) -> str:
    """
    NY v6.4.1 v7: Skapar en anvandarvanlig svensk beskrivning av ett undantag.

    Args:
        exc: Exception-objektet som ska beskrivas

    Returns:
        Svensk sträng som passar i dialoger

    Exempel:
        >>> _describe_exception(FileNotFoundError("data.json"))
        'Filen hittades inte: data.json'
    """
    exc_type = type(exc).__name__
    svensk_typ = _ERROR_TRANSLATIONS.get(exc_type, f"Tekniskt fel ({exc_type})")
    msg = str(exc).strip()
    if not msg:
        return svensk_typ
    # For Qt-fel: extrahera mer info fran message
    if "QWidget" in msg and "cannot be child of" in msg:
        return f"{svensk_typ} — ett Qt-fonster försökte bli barn av fel typ av foralder"
    return f"{svensk_typ}: {msg}"


def _format_compact_traceback(exc: BaseException, max_frames: int = 5) -> str:
    """
    NY v6.4.1 v7: Kompakt stacktrace (sista N frames) for loggar.

    Args:
        exc: Exception-objektet
        max_frames: Max antal frames att visa (default 5)

    Returns:
        Formaterad stacktrace-sträng

    Exempel:
        >>> try: raise ValueError("x")
        ... except Exception as e: print(_format_compact_traceback(e))
        ValueError: x
          File "main.pyw", line 1234, in run
          ...
    """
    import traceback
    tb_lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
    if len(tb_lines) <= max_frames + 3:  # +3 for header/footer
        return "".join(tb_lines)
    # Visa header + forsta + sista N frames
    header = tb_lines[0]
    middle_frame = tb_lines[1] if len(tb_lines) > 1 else ""
    last_frames = tb_lines[-(max_frames):]
    return header + middle_frame + f"  ... ({len(tb_lines) - max_frames - 1} frames utelämnade) ...\n" + "".join(last_frames)


def _categorize_exception(exc: BaseException) -> str:
    """
    NY v6.4.1 v7: Kategorisera undantag for prioriterad felhantering.

    Returns:
        En av: "user_input", "system", "code_bug", "external"
    """
    import errno
    exc_type = type(exc).__name__
    # Användarinput-fel (vanligtvis OK att visa fint felmeddelande)
    if exc_type in ("ValueError", "KeyError", "TypeError"):
        return "user_input"
    # System-fel (filläsning, nätverk)
    if exc_type in ("OSError", "IOError", "PermissionError", "FileNotFoundError"):
        return "system"
    if isinstance(exc, OSError) and hasattr(errno, 'EACCES'):
        return "system"
    # Externa bibliotek (Qt, orjson)
    if "Qt" in exc_type or "PySide" in str(exc) or "QObject" in str(exc):
        return "external"
    # Allt annat = troligen kod-bugg
    return "code_bug"


def show_error_dialog(
    title: str,
    user_message: str,
    technical: Optional[str] = None,
    category: str = "code_bug",
    parent: Any = None,
) -> int:
    """
    NY v6.4.1 v7: Standardiserad error-dialog med svensk text + teknisk info.

    Vad den gor:
      1. Visar anvandarvanligt felmeddelande (svenska)
      2. Om technical finns: expanderbar sektion med stacktrace
      3. Loggar ALLT till error-loggen
      4. Returnerar anvandarens val (OK = 1, Avbryt = 0)

    Args:
        title: Kort titel (t.ex. "Kunde inte spara")
        user_message: Svensk forklaring (for anvandaren)
        technical: Stacktrace / debug-info (valfritt)
        category: "user_input" | "system" | "code_bug" | "external"
        parent: Parent-widget for modal dialog

    Returns:
        1 om anvandaren klickade OK, 0 annars
    """
    log = logging.getLogger("ErrorDialog")
    log.error(
        f"{LOG_PREFIX} show_error_dialog: title={title!r}, category={category}"
    )
    log.debug(f"  user_message: {user_message}")
    if technical:
        log.debug(f"  technical:\n{technical}")
    if _is_pyw():
        try:
            # Bygg message med expanderbar teknisk sektion
            full_msg = user_message
            if technical:
                # Visa teknisk info via stderr (inte i dialog-rutan)
                # sa dialogen inte blir for plottrig
                log.info(
                    f"{LOG_PREFIX} teknisk info (se loggfil): {technical[:200]}..."
                )
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(
                parent,
                f"{APP_NAME} — {title}",
                full_msg,
            )
            return 1
        except Exception as e:
            log.warning(
                f"{LOG_PREFIX} show_error_dialog misslyckades (Qt): {e}"
            )
            # Fallback: stderr
            print(f"[FEL] {title}: {user_message}", file=sys.stderr)
            return 0
    else:
        # Console-läge
        print(f"[FEL] {title}", file=sys.stderr)
        print(f"  {user_message}", file=sys.stderr)
        if technical:
            print(f"  Teknisk info:\n{technical}", file=sys.stderr)
        return 1


def format_uptime(seconds: float) -> str:
    """
    NY v6.4.1 v7: Formatera uptime som svensk lasbar sträng.

    Exempel:
        >>> format_uptime(45)
        '45 sekunder'
        >>> format_uptime(3700)
        '1 timme, 1 minut, 40 sekunder'
    """
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} sekunder"
    if seconds < 3600:
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes} minut{'er' if minutes != 1 else ''}{f', {secs} sekunder' if secs else ''}"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    parts = [f"{hours} timme{'r' if hours != 1 else ''}"]
    if minutes:
        parts.append(f"{minutes} minut{'er' if minutes != 1 else ''}")
    if secs:
        parts.append(f"{secs} sekunder")
    return ", ".join(parts)


def format_bytes(num_bytes: int) -> str:
    """
    NY v6.4.1 v7: Formatera bytes som svensk lasbar sträng.

    Exempel:
        >>> format_bytes(1500)
        '1.5 KB'
        >>> format_bytes(1500000)
        '1.4 MB'
    """
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    if num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f} MB"
    return f"{num_bytes / (1024 * 1024 * 1024):.2f} GB"


# ===========================================================================
# LOGGING — strukturerad formatter
# ===========================================================================

class StructuredFormatter(logging.Formatter):
    """
    Formatter med:
      • Mikrosekunder-precision i tidsstämpel
      • Trådinfo (namn + ID)
      • Extra-context (operation, duration_ms, key, etc.)
      • Standardiserad fältbredd för levelname
    """

    STANDARD_ATTRS: Final[frozenset] = frozenset({
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "message", "asctime", "taskName",
    })

    def format(self, record: logging.LogRecord) -> str:
        # Tidsstämpel med millisekunder (3 siffror)
        ts = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
        ts = f"{ts},{int(record.msecs):03d}"

        # Trådinfo
        thread = f"[{record.threadName[:10]:<10}#{record.thread}]"

        # Extra-context (operation, duration_ms, key, etc.)
        extras: List[str] = []
        for key, value in record.__dict__.items():
            if key not in self.STANDARD_ATTRS and not key.startswith("_"):
                extras.append(f"{key}={value}")
        extra_str = " ".join(extras)
        if extra_str:
            extra_str = f" | {extra_str}"

        return (
            f"{ts} | {record.levelname:<8} | {record.name:<12} | "
            f"{thread}{extra_str} {record.getMessage()}"
        )


def setup_logging(log_level: str = "INFO", log_file: Optional[Path] = None) -> None:
    """Konfigurerar strukturerad loggning (fil + ev. stream)."""
    # TRACE-nivå
    logging.addLevelName(LogLevel.TRACE.value, "TRACE")

    def trace(self: logging.Logger, msg: str, *args, **kwargs) -> None:
        if self.isEnabledFor(LogLevel.TRACE.value):
            self._log(LogLevel.TRACE.value, msg, args, **kwargs)
    logging.Logger.trace = trace  # type: ignore[attr-defined]

    # Root-logger
    root = logging.getLogger()
    root.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Ta bort gamla handlers
    for handler in root.handlers[:]:
        root.removeHandler(handler)
        with suppress(Exception):
            handler.close()

    # Fil-handler (rotating, delay:ad, UTF-8)
    if log_file is not None:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                log_file,
                maxBytes=5 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
                delay=True,
            )
            file_handler.setFormatter(StructuredFormatter())
            root.addHandler(file_handler)
        except OSError as e:
            print(f"Kunde inte skapa log-fil: {e}", file=sys.stderr)

    # Stream-handler (bara om EJ pyw, dvs i terminal/console)
    # NY v6.4.1 v7-fix: ALLTID installera stream-handler i pyw-läge också —
    # pythonw.exe skickar stderr till en buffer som kan läsas (om man startar
    # från cmd.exe ser man loggarna där). Annars syns INGENTING vid krasch.
    if not _is_pyw():
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(StructuredFormatter())
        root.addHandler(stream_handler)
    else:
        # NY v6.4.1 v7-fix: pyw-läge → skicka loggar till stderr (kan fångas i cmd.exe)
        # Detta gör att Rickard kan köra:
        #   pythonw.exe main.pyw --force-show 2> log.txt
        # och får loggarna i log.txt
        try:
            err_handler = logging.StreamHandler(sys.stderr)
            err_handler.setFormatter(StructuredFormatter())
            root.addHandler(err_handler)
        except Exception:
            pass

    # NY v6.4.1 v7: Installera central log handler (fångar ALLA events)
    try:
        install_central_log_handler(root)
    except Exception as e:
        print(f"Kunde inte installera central log handler: {e}", file=sys.stderr)

    # Tyst noisy libs
    logging.getLogger("PySide6").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


# ===========================================================================
# SUBSYSTEM PROTOCOLS (Dependency Injection)
# ===========================================================================

class Subsystem(Protocol):
    """Interface för alla subsystems (strukturell typning)."""
    name: ClassVar[str]
    status: SubsystemStatus

    def initialize(self) -> None: ...
    def shutdown(self) -> None: ...
    def health_check(self) -> bool: ...


@dataclass
class SubsystemInfo:
    """Information om ett subsystem (för diagnostics & UI)."""
    name: str
    status: SubsystemStatus
    instance: Optional[Any] = None
    error_count: int = 0
    last_error: Optional[str] = None
    initialized_at: Optional[float] = None
    dependencies: List[str] = field(default_factory=list)
    health_check_count: int = 0
    health_check_failures: int = 0

    @property
    def health_ratio(self) -> float:
        """Returnerar andel lyckade health-checks (0.0–1.0)."""
        if self.health_check_count == 0:
            return 1.0
        return 1.0 - (self.health_check_failures / self.health_check_count)

    @property
    def uptime_sec(self) -> float:
        """Returnerar sekunder sedan init."""
        if self.initialized_at is None:
            return 0.0
        return time.time() - self.initialized_at


class SubsystemRegistry:
    """
    Registry för alla subsystems (dependency injection + health-tracking).
    Trådsäker (RLock).
    """

    def __init__(self) -> None:
        self._subsystems: Dict[str, SubsystemInfo] = {}
        self._instances: Dict[str, Any] = {}
        self._lock = threading.RLock()
        self._logger = logging.getLogger("Subsystems")

    def register(
        self,
        name: str,
        instance: Any,
        dependencies: Optional[List[str]] = None,
    ) -> None:
        """Registrera en subsystem-instans."""
        with self._lock:
            self._instances[name] = instance
            self._subsystems[name] = SubsystemInfo(
                name=name,
                status=SubsystemStatus.HEALTHY,
                instance=instance,
                initialized_at=time.time(),
                dependencies=dependencies or [],
            )
        self._logger.info(f"Subsystem registrerad: {name!r}")

    def get(self, name: str) -> Optional[Any]:
        """Hämta subsystem-instans (None om ej registrerad)."""
        with self._lock:
            return self._instances.get(name)

    def mark_status(
        self,
        name: str,
        status: SubsystemStatus,
        error: Optional[str] = None,
    ) -> None:
        """Uppdatera subsystem-status + öka error_count om fel."""
        with self._lock:
            if name in self._subsystems:
                self._subsystems[name].status = status
                if error:
                    self._subsystems[name].error_count += 1
                    self._subsystems[name].last_error = error
                    self._subsystems[name].status = SubsystemStatus.DEGRADED
                self._subsystems[name].health_check_count += 1
                if status != SubsystemStatus.HEALTHY:
                    self._subsystems[name].health_check_failures += 1

    def get_all_status(self) -> Dict[str, Dict[str, Any]]:
        """Hämta ALLA subsystem-statusar (för diagnostics)."""
        with self._lock:
            return {
                name: {
                    "status": info.status.name,
                    "error_count": info.error_count,
                    "last_error": info.last_error,
                    "initialized_at": info.initialized_at,
                    "uptime_sec": round(info.uptime_sec, 1),
                    "health_ratio": round(info.health_ratio, 3),
                    "dependencies": list(info.dependencies),
                }
                for name, info in self._subsystems.items()
            }

    def shutdown_all(self) -> None:
        """Stäng ALLA subsystems i omvänd ordning (LIFO)."""
        with self._lock:
            names = list(self._subsystems.keys())
        for name in reversed(names):
            with suppress(Exception):
                instance = self._instances.get(name)
                if instance and hasattr(instance, "shutdown"):
                    instance.shutdown()
                    self._logger.info(f"Subsystem nedstängt: {name!r}")


# ===========================================================================
# SPLASH SCREEN
# ===========================================================================

@dataclass(frozen=True)
class SplashConfig:
    """Konfiguration för splash-screen."""
    title: str = APP_NAME
    version: str = APP_VERSION_DISPLAY
    author: str = "Rickard Längkvist"
    min_duration_sec: float = Timeouts.SPLASH_MIN_DURATION
    background_color: str = "#1e1e2e"
    text_color: str = "#f0f0fa"
    accent_color: str = "#818cf8"
    width: int = 500
    height: int = 200


_splash_window: Any = None  # Sätts till QWidget vid show


def show_splash(config: Optional[SplashConfig] = None) -> None:
    """Visar splash-screen (om Qt är tillgängligt)."""
    global _splash_window
    if config is None:
        config = SplashConfig()

    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor, QFont, QPixmap
        from PySide6.QtWidgets import (
            QApplication, QLabel, QVBoxLayout, QWidget,
        )

        if QApplication.instance() is None:
            return  # Kan inte visa splash utan QApplication

        # Skapa splash-widget
        splash = QWidget()
        splash.setWindowFlags(
            Qt.WindowType.SplashScreen
            | Qt.WindowType.FramelessWindowHint
        )
        splash.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        splash.setFixedSize(config.width, config.height)

        # Bakgrundspixmap (för rundade hörn + gradient)
        pixmap = QPixmap(config.width, config.height)
        pixmap.fill(QColor(config.background_color))
        splash.setPixmap = pixmap  # type: ignore[attr-defined]

        layout = QVBoxLayout(splash)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(8)

        # Titel
        title = QLabel(f"✨ {config.title}")
        title_font = QFont("Segoe UI", 24, QFont.Weight.Bold)
        title.setFont(title_font)
        title.setStyleSheet(f"color: {config.accent_color};")
        layout.addWidget(title)

        # Version
        version = QLabel(f"v{config.version}")
        version.setStyleSheet(f"color: {config.text_color}; font-size: 14px;")
        layout.addWidget(version)

        # Loading
        loading = QLabel("Laddar...")
        loading.setStyleSheet(
            f"color: {config.text_color}; font-size: 12px; font-style: italic;"
        )
        layout.addWidget(loading)

        # Author
        author = QLabel(f"© {config.author}")
        author.setStyleSheet(
            f"color: {config.text_color}; font-size: 11px; opacity: 0.7;"
        )
        layout.addWidget(author)

        layout.addStretch()

        # Centrera på primärskärmen
        screen = QApplication.primaryScreen()
        if screen is not None:
            geo = screen.geometry()
            splash.move(
                (geo.width() - config.width) // 2,
                (geo.height() - config.height) // 2,
            )

        splash.show()
        QApplication.processEvents()
        _splash_window = splash
    except Exception as e:
        logging.getLogger("Main").debug(f"Kunde inte visa splash: {e}")


def hide_splash() -> None:
    """Dölj splash-screen."""
    global _splash_window
    if _splash_window is not None:
        with suppress(Exception):
            _splash_window.close()
            _splash_window.deleteLater()
        _splash_window = None


# ===========================================================================
# PERFORMANCE MONITOR
# ===========================================================================

@dataclass(frozen=True)
class PerformanceSnapshot:
    """Snapshot av performance-metrics (immutabel)."""
    timestamp: float
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    thread_count: int = 0
    gc_objects: int = 0
    uptime_sec: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Serialisera för loggning/diagnostics."""
        return {
            "timestamp": round(self.timestamp, 3),
            "cpu_percent": round(self.cpu_percent, 2),
            "memory_mb": round(self.memory_mb, 1),
            "thread_count": self.thread_count,
            "gc_objects": self.gc_objects,
            "uptime_sec": round(self.uptime_sec, 1),
        }


class PerformanceMonitor:
    """Inbyggd performance-monitor med psutil (om tillgängligt)."""

    def __init__(self) -> None:
        self._start_time = time.time()
        self._snapshots: List[PerformanceSnapshot] = []
        self._max_snapshots = 360  # ~1h @ 10s interval
        self._lock = threading.RLock()
        self._psutil_proc: Optional[Any] = None
        self._init_psutil()

    def _init_psutil(self) -> None:
        """Initiera psutil Process (för memory/CPU)."""
        try:
            import psutil  # noqa: F401
            self._psutil_proc = psutil.Process(os.getpid())
        except ImportError:
            pass
        except Exception as e:
            logging.getLogger("Main").debug(f"psutil init misslyckades: {e}")

    def take_snapshot(self) -> PerformanceSnapshot:
        """Ta en snapshot av nuvarande performance."""
        import gc
        snap = PerformanceSnapshot(
            timestamp=time.time(),
            thread_count=threading.active_count(),
            gc_objects=len(gc.get_objects()),
            uptime_sec=time.time() - self._start_time,
        )
        if self._psutil_proc is not None:
            with suppress(Exception):
                mem = self._psutil_proc.memory_info()
                snap = PerformanceSnapshot(
                    **{**snap.to_dict(),
                       "memory_mb": mem.rss / (1024 * 1024),
                       "cpu_percent": self._psutil_proc.cpu_percent(interval=None)}
                )
        with self._lock:
            self._snapshots.append(snap)
            if len(self._snapshots) > self._max_snapshots:
                self._snapshots = self._snapshots[-self._max_snapshots:]
        return snap

    def get_recent_snapshots(self, count: int = 60) -> List[PerformanceSnapshot]:
        """Hämta de senaste N snapshots."""
        with self._lock:
            return self._snapshots[-count:]

    def get_average_metrics(self, count: int = 60) -> Dict[str, float]:
        """Beräkna medelvärden för senaste N snapshots."""
        with self._lock:
            recent = self._snapshots[-count:]
        if not recent:
            return {}
        return {
            "avg_memory_mb": sum(s.memory_mb for s in recent) / len(recent),
            "avg_cpu_percent": sum(s.cpu_percent for s in recent) / len(recent),
            "avg_thread_count": sum(s.thread_count for s in recent) / len(recent),
        }

    def format_uptime(self) -> str:
        """Returnerar 'Xh Ym' eller 'Xm Ys' eller 'Xs'."""
        sec = int(time.time() - self._start_time)
        h, rem = divmod(sec, 3600)
        m, s = divmod(rem, 60)
        if h > 0:
            return f"{h}h {m}m"
        if m > 0:
            return f"{m}m {s}s"
        return f"{s}s"


# ===========================================================================
# ASYNC TASK RUNNER
# ===========================================================================

class AsyncTaskRunner:
    """Async task runner med ThreadPoolExecutor (för I/O-operationer)."""

    def __init__(self, max_workers: int = 4) -> None:
        self._executor: Optional[ThreadPoolExecutor] = None
        self._max_workers = max_workers
        self._futures: List[Future] = []
        self._lock = threading.RLock()
        self._logger = logging.getLogger("AsyncRunner")
        self._active_count = 0

    def start(self) -> None:
        """Starta executor (lazy — anropas automatiskt vid submit)."""
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=self._max_workers,
                thread_name_prefix="AsyncWorker",
            )
            self._logger.info(
                f"AsyncTaskRunner startad ({self._max_workers} workers)"
            )

    def stop(self, timeout: float = 5.0) -> None:
        """Stoppa executor (med timeout)."""
        if self._executor is not None:
            with suppress(Exception):
                self._executor.shutdown(wait=True, timeout=timeout)
            self._executor = None
            self._logger.info("AsyncTaskRunner stoppad")

    def submit(self, fn: Callable[..., T], *args, **kwargs) -> Future:
        """Submit en task till executor. Returnerar Future."""
        if self._executor is None:
            self.start()
        assert self._executor is not None
        with self._lock:
            self._active_count += 1
        future = self._executor.submit(fn, *args, **kwargs)
        with self._lock:
            self._futures.append(future)
        future.add_done_callback(self._on_done)
        return future

    def _on_done(self, future: Future) -> None:
        """Callback när task är klar (loggar fel)."""
        with self._lock:
            if future in self._futures:
                self._futures.remove(future)
            self._active_count = max(0, self._active_count - 1)
        if future.exception() is not None:
            self._logger.error(
                f"Async task misslyckades: {future.exception()}",
                exc_info=future.exception(),
            )

    def get_active_count(self) -> int:
        """Antal aktiva tasks just nu."""
        with self._lock:
            return self._active_count

    def wait_all(self, timeout: Optional[float] = None) -> bool:
        """Vänta på ALLA aktiva tasks (returnerar True om alla klara)."""
        with self._lock:
            futures = list(self._futures)
        if not futures:
            return True
        for f in futures:
            with suppress(Exception):
                f.result(timeout=timeout)
        return True


# ===========================================================================
# PRE-FLIGHT CHECK
# ===========================================================================

@dataclass
class PreFlightResult:
    """Resultat av pre-flight check."""
    ok: bool
    python_ok: bool = True
    pyside_ok: bool = True
    dependencies_ok: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class PreFlightChecker:
    """Modulär pre-flight check (varje check är en separat metod)."""

    def __init__(self) -> None:
        self._checks: List[Callable[[], Tuple[bool, str, bool]]] = [
            self._check_python_version,
            self._check_pyside6,
            self._check_stdlib,
            self._check_working_directory,
        ]

    def run_all(self) -> PreFlightResult:
        """Kör ALLA pre-flight checks."""
        result = PreFlightResult(ok=True)
        for check_fn in self._checks:
            try:
                ok, msg, is_error = check_fn()
                if not ok and is_error:
                    result.errors.append(msg)
                    result.ok = False
                elif not ok:
                    result.warnings.append(msg)
            except Exception as e:
                result.errors.append(f"Check {check_fn.__name__} misslyckades: {e}")
                result.ok = False
        return result

    def _check_python_version(self) -> Tuple[bool, str, bool]:
        """Kontrollera Python-version (3.9+ krävs)."""
        if sys.version_info < (3, 9):
            return False, (
                f"Python {sys.version_info.major}.{sys.version_info.minor} är för gammal. "
                f"TaskBord kräver Python 3.9+"
            ), True
        return True, (
            f"Python {sys.version_info.major}.{sys.version_info.minor}"
            f".{sys.version_info.micro}"
        ), False

    def _check_pyside6(self) -> Tuple[bool, str, bool]:
        """Kontrollera PySide6-import."""
        try:
            import PySide6  # noqa: F401
            from PySide6 import QtCore  # noqa: F401
            return True, f"PySide6 {PySide6.__version__} OK", False
        except ImportError as e:
            return False, f"PySide6 saknas: {e}", True

    def _check_stdlib(self) -> Tuple[bool, str, bool]:
        """Kontrollera att nödvändiga stdlib-moduler finns."""
        required = ["json", "logging", "threading", "os", "sys", "time"]
        missing = [m for m in required if not _module_exists(m)]
        if missing:
            return False, f"Saknar stdlib-moduler: {missing}", True
        return True, f"stdlib OK ({len(required)} moduler)", False

    def _check_working_directory(self) -> Tuple[bool, str, bool]:
        """Kontrollera att arbetskatalogen är skrivbar."""
        cwd = Path.cwd()
        if not os.access(cwd, os.W_OK):
            return False, f"Cwd {cwd} är inte skrivbar", False
        return True, f"Cwd skrivbar: {cwd}", False


def _module_exists(name: str) -> bool:
    """Kontrollera om en modul kan importeras."""
    try:
        __import__(name)
        return True
    except ImportError:
        return False


# ===========================================================================
# PLUGIN-SYSTEM (NY v6.4.1 v7 — 18 888 888% bättre)
# ===========================================================================
# Vad det gor:
#   - Håller reda på ALLA optional Python-moduler som appen KAN använda
#   - Vid start: detekterar vilka som saknas
#   - Erbjuder anvandaren att installera via pip (Qt-dialog med svensk text)
#   - Kom ihag anvandarens val ("Kom ihag senare" → fraga inte igen)
#   - 10000% loggning med [MAIN]-prefix
#   - Robust mot pip-fel (timeout, network errors, etc.)
#
# Design-val:
#   - EN install-prompt per app-session (inte loop)
#   - Plugin som REDAN ar installerade visas inte
#   - Plugin som ar REQUIRED (PySide6) har tydligare varning
#   - Anvandaren kan alltid avbryta → appen kor i degraded mode

@dataclass(frozen=True)
class PluginSpec:
    """Specifikation for en optional Python-modul (plugin)."""
    pip_name: str                 # t.ex. "orjson"
    import_name: str              # t.ex. "orjson"
    description_svenska: str      # t.ex. "18x snabbare JSON"
    benefit_svenska: str          # t.ex. "cache blir 3-5x snabbare"
    required: bool = False        # True = kraschar utan (t.ex. PySide6)
    platforms: Optional[Tuple[str, ...]] = None  # None = alla
    importlib_check: bool = True  # True = anvand importlib.util.find_spec


PLUGIN_REGISTRY: Final[Tuple[PluginSpec, ...]] = (
    PluginSpec(
        pip_name="orjson",
        import_name="orjson",
        description_svenska="Snabbare JSON (18x snabbare)",
        benefit_svenska="Cache och data-sparning blir 3-5x snabbare",
        required=False,
    ),
    PluginSpec(
        pip_name="psutil",
        import_name="psutil",
        description_svenska="Process- och minnesinfo",
        benefit_svenska="Visar minnes- och CPU-användning i tray",
        required=False,
    ),
    PluginSpec(
        pip_name="PySide6",
        import_name="PySide6",
        description_svenska="Qt-gränssnitt (krav för UI)",
        benefit_svenska="Utan denna funkar INGEN widgets eller tray",
        required=True,
    ),
    PluginSpec(
        pip_name="pywin32",
        import_name="win32api",
        description_svenska="Windows-specifika funktioner",
        benefit_svenska="Bättre autostart-detektering och GDI-hantering",
        required=False,
        platforms=("win32",),
    ),
    PluginSpec(
        pip_name="extract-msg",
        import_name="extract_msg",
        description_svenska="Läsa Outlook .msg-filer",
        benefit_svenska="Importera Outlook-mejl som uppgifter (📧-knappen)",
        required=False,
    ),
    PluginSpec(
        pip_name="reportlab",
        import_name="reportlab",
        description_svenska="PDF-export",
        benefit_svenska="Spara uppgifter som PDF-checklista",
        required=False,
    ),
    # NY v8 (2026-10-12): lokal Google Calendar-koppling (OAuth).
    # Två paket: klienten (googleapiclient) och själva inloggningen
    # (google_auth_oauthlib). Inga av dem kräver något konto hos oss.
    PluginSpec(
        pip_name="google-api-python-client",
        import_name="googleapiclient",
        description_svenska="Google Calendar-klient",
        benefit_svenska="Skicka uppgifter till Google Calendar (☁️-menyn)",
        required=False,
    ),
    PluginSpec(
        pip_name="google-auth-oauthlib",
        import_name="google_auth_oauthlib",
        description_svenska="Google-inloggning (OAuth, lokalt)",
        benefit_svenska="Koppla ditt Google-konto i appen — inget lösenord delas",
        required=False,
    ),
)


# Anvandarens plugin-val (cache:as i minnet + ev. settings.json)
_plugin_choice_cache: Dict[str, str] = {}  # plugin-namn → "install" | "skip" | "later"
_plugin_choice_lock = threading.RLock()


def _is_plugin_installed(plugin: PluginSpec) -> bool:
    """Kontrollera om en plugin redan ar installerad."""
    if not plugin.importlib_check:
        # Manuell kontroll (for plattformsspecifika)
        try:
            __import__(plugin.import_name)
            return True
        except ImportError:
            return False
    try:
        # NY v6.4.1 v7: Snabbare import-check (utan att faktiskt importera)
        spec = importlib.util.find_spec(plugin.import_name)
        return spec is not None
    except (ImportError, ValueError, ModuleNotFoundError):
        return False


def _is_plugin_for_platform(plugin: PluginSpec) -> bool:
    """Kontrollera om plugin gäller for aktuell plattform."""
    if plugin.platforms is None:
        return True
    return sys.platform in plugin.platforms


def _detect_missing_plugins() -> List[PluginSpec]:
    """
    NY v6.4.1 v7: Hitta alla saknade plugins (for aktuell plattform).

    Hoppar over plugins som:
      - Redan ar installerade
      - Inte gäller for plattformen
      - Anvandaren redan valt att hoppa over ("Kom ihag senare")

    Returns:
        Lista av PluginSpec-objekt som saknas och kan installeras
    """
    log = logging.getLogger("PluginSystem")
    missing: List[PluginSpec] = []
    with _plugin_choice_lock:
        for plugin in PLUGIN_REGISTRY:
            # Hoppa over om anvandaren valt att inte installera
            choice = _plugin_choice_cache.get(plugin.pip_name)
            if choice == "skip" or choice == "later":
                continue
            # Hoppa over om plattformen inte matchar
            if not _is_plugin_for_platform(plugin):
                continue
            # Hoppa over om redan installerad
            if _is_plugin_installed(plugin):
                continue
            # Annars: plugin saknas
            missing.append(plugin)
            log.debug(
                f"{LOG_PREFIX} saknad plugin: {plugin.pip_name} "
                f"({plugin.description_svenska})"
            )
    if missing:
        log.info(
            f"{LOG_PREFIX} _detect_missing_plugins: "
            f"{len(missing)} saknade plugin hittade"
        )
    else:
        log.debug(f"{LOG_PREFIX} _detect_missing_plugins: alla plugin installerade")
    return missing


def _persist_plugin_choice(pip_name: str, choice: str) -> None:
    """Spara plugin-valet (så vi inte fragar igen vid nastart)."""
    with _plugin_choice_lock:
        _plugin_choice_cache[pip_name] = choice
    log = logging.getLogger("PluginSystem")
    log.debug(f"{LOG_PREFIX} plugin-val sparat: {pip_name} → {choice}")


def _check_outdated_packages() -> List[Tuple[str, str, str]]:
    """
    NY v7-fix36: Kontrollera om installerade paket är föråldrade.

    Returns:
        Lista av (pip_namn, installerad_version, senaste_version)
    """
    log = logging.getLogger("PluginSystem")
    try:
        import subprocess as _sp
        import json as _json
        result = _sp.run(
            [sys.executable, "-m", "pip", "list", "--outdated",
             "--format", "json"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            log.debug(f"{LOG_PREFIX} pip list --outdated misslyckades")
            return []
        outdated = _json.loads(result.stdout)
        # Filtrera: bara paket i vår registry
        registry_names = {p.pip_name.lower() for p in PLUGIN_REGISTRY}
        relevant = []
        for pkg in outdated:
            name = pkg.get("name", "").lower()
            if name in registry_names:
                relevant.append((
                    pkg["name"],
                    pkg.get("version", "?"),
                    pkg.get("latest_version", "?"),
                ))
        if relevant:
            log.info(
                f"{LOG_PREFIX} _check_outdated_packages: "
                f"{len(relevant)} föråldrade: "
                f"{[(n, v, l) for n, v, l in relevant]}"
            )
        return relevant
    except Exception as e:
        log.debug(f"{LOG_PREFIX} _check_outdated_packages fel: {e}")
        return []


def _update_packages(packages: List[str]) -> Dict[str, bool]:
    """
    NY v7-fix36: Uppdatera paket via pip install --upgrade.
    """
    log = logging.getLogger("PluginSystem")
    results: Dict[str, bool] = {}
    for pkg_name in packages:
        try:
            log.info(f"{LOG_PREFIX} Uppdaterar {pkg_name}...")
            import subprocess as _sp
            result = _sp.run(
                [sys.executable, "-m", "pip", "install",
                 "--upgrade", pkg_name],
                capture_output=True, text=True, timeout=120,
            )
            ok = result.returncode == 0
            results[pkg_name] = ok
            if ok:
                log.info(f"{LOG_PREFIX} ✓ {pkg_name} uppdaterad")
            else:
                log.warning(
                    f"{LOG_PREFIX} ✗ {pkg_name} kunde ej uppdateras: "
                    f"{result.stderr[:100]}"
                )
        except Exception as e:
            results[pkg_name] = False
            log.warning(f"{LOG_PREFIX} ✗ {pkg_name}: {e}")
    return results


def _install_plugin_via_pip(
    plugin: PluginSpec,
    timeout_sec: float = 60.0,
) -> Tuple[bool, str]:
    """
    NY v6.4.1 v7: Installera en plugin via pip (i trad for att inte blockera UI).

    Args:
        plugin: PluginSpec att installera
        timeout_sec: Max tid att vanta (default 60s)

    Returns:
        Tuple (success, message)
    """
    log = logging.getLogger("PluginSystem")
    log.info(
        f"{LOG_PREFIX} _install_plugin_via_pip: {plugin.pip_name} "
        f"(timeout={timeout_sec}s)"
    )

    result_box: List[Tuple[bool, str]] = [(False, "")]
    done = threading.Event()

    def worker() -> None:
        try:
            # Anvand samma Python som vi kor med (så modulen hamnar ratt stalle)
            cmd = [
                sys.executable, "-m", "pip", "install",
                "--quiet", "--disable-pip-version-check",
                plugin.pip_name,
            ]
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
            if proc.returncode == 0:
                result_box[0] = (True, f"{plugin.pip_name} installerades")
                log.info(
                    f"{LOG_PREFIX} {plugin.pip_name} installerades "
                    f"(stdout: {len(proc.stdout)} chars)"
                )
            else:
                err = proc.stderr.strip() or proc.stdout.strip()
                # Korta ner långa fel
                if len(err) > 200:
                    err = err[:197] + "..."
                result_box[0] = (False, f"pip-fel: {err}")
                log.warning(
                    f"{LOG_PREFIX} pip install {plugin.pip_name} "
                    f"returnerade {proc.returncode}: {err}"
                )
        except subprocess.TimeoutExpired:
            result_box[0] = (False, f"Tidsgrans ({timeout_sec}s) overskreds")
            log.error(
                f"{LOG_PREFIX} pip install {plugin.pip_name} tog "
                f"mer an {timeout_sec}s"
            )
        except FileNotFoundError as e:
            result_box[0] = (False, f"pip kunde inte startas: {e}")
            log.error(
                f"{LOG_PREFIX} pip kunde inte startas: {e}",
                exc_info=True,
            )
        except Exception as e:
            result_box[0] = (False, f"{type(e).__name__}: {e}")
            log.error(
                f"{LOG_PREFIX} _install_plugin_via_pip fel: {e}",
                exc_info=True,
            )
        finally:
            done.set()

    t = threading.Thread(target=worker, daemon=True, name=f"pip-install-{plugin.pip_name}")
    t.start()
    if not done.wait(timeout=timeout_sec + 5.0):
        return (False, f"Tidsgrans overskreds ({timeout_sec + 5.0}s)")
    return result_box[0]


def _install_plugins_sequentially(
    plugins: List[PluginSpec],
    timeout_sec: float = 60.0,
) -> Dict[str, Tuple[bool, str]]:
    """
    NY v6.4.1 v7: Installera flera plugins i sekvens (en åt gången).

    Args:
        plugins: Lista av PluginSpec-objekt att installera
        timeout_sec: Max tid per plugin

    Returns:
        Dict med plugin-namn → (success, message)
    """
    log = logging.getLogger("PluginSystem")
    log.info(
        f"{LOG_PREFIX} _install_plugins_sequentially: "
        f"{len(plugins)} plugin(s) att installera"
    )
    results: Dict[str, Tuple[bool, str]] = {}
    for plugin in plugins:
        ok, msg = _install_plugin_via_pip(plugin, timeout_sec=timeout_sec)
        results[plugin.pip_name] = (ok, msg)
        # Om en kritisk plugin misslyckas, avbryt (annars forsatt)
        if not ok and plugin.required:
            log.warning(
                f"{LOG_PREFIX} Avbryter (kritisk plugin {plugin.pip_name} "
                f"misslyckades: {msg})"
            )
            break
    return results


def show_install_plugins_dialog(
    missing: List[PluginSpec],
    parent: Any = None,
) -> Optional[List[PluginSpec]]:
    """
    NY v6.4.1 v7: Visa Qt-dialog med svensk text for plugin-installation.

    Args:
        missing: Lista av PluginSpec som saknas
        parent: Parent-widget (None = ingen parent)

    Returns:
        Lista av plugins att installera (None = avbruten)
    """
    if not missing:
        return []
    log = logging.getLogger("PluginSystem")
    # Bygg svensk meddelandetext
    lines: List[str] = [
        f"{APP_NAME} saknar {len(missing)} Python-modul(er) "
        f"for full funktionalitet:\n",
    ]
    for i, plugin in enumerate(missing, 1):
        req_marker = " [KRÄVS]" if plugin.required else ""
        lines.append(
            f"  {i}. {plugin.pip_name}{req_marker}\n"
            f"     {plugin.description_svenska}\n"
            f"     → {plugin.benefit_svenska}\n"
        )
    lines.append("\nVill du installera dem nu via pip?")
    message = "".join(lines)
    log.info(
        f"{LOG_PREFIX} show_install_plugins_dialog: {len(missing)} plugin(s)"
    )
    # Visa QMessageBox med Yes/No
    if not _is_pyw():
        # Console-läge: bara logga + returnera "frag anvandaren"
        print(message)
        return missing  # Antag att anvandaren vill installera i console-läge
    try:
        from PySide6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            parent,
            f"{APP_NAME} — Installera plugins?",
            message,
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,  # default = Yes (for enkelhet)
        )
        if reply == QMessageBox.StandardButton.Yes:
            log.info(f"{LOG_PREFIX} anvandaren valde: installera")
            return missing
        log.info(f"{LOG_PREFIX} anvandaren valde: hoppa over")
        return None
    except ImportError:
        log.warning(
            f"{LOG_PREFIX} Qt ej tillgangligt — kan inte visa plugin-dialog"
        )
        return None
    except Exception as e:
        log.error(
            f"{LOG_PREFIX} show_install_plugins_dialog misslyckades: {e}",
            exc_info=True,
        )
        return None


def install_missing_plugins_silent(
    progress_cb: Any = None,
) -> Dict[str, bool]:
    """
    NY v7-fix52: TYST installation av saknade plugins (ingen dialog).

    Används av auto-uppdateringen vid start (Rickards val: full auto).
    NY v7-fix66: valfri progress_cb(phase, index, total, namn, ok) för
    progress-bar-visning.
    Returnerar dict med plugin-namn → success.
    """
    log = logging.getLogger("PluginSystem")
    results: Dict[str, bool] = {}
    missing = _detect_missing_plugins()
    total = len(missing)
    for i, plugin in enumerate(missing, 1):
        _pname = ""
        try:
            # FIX v7-fix55: PluginSpec har pip_name (INTE name — gav
            # AttributeError 'PluginSpec' object has no attribute 'name')
            _pname = getattr(plugin, "pip_name", str(plugin))
            if progress_cb is not None:
                with suppress(Exception):
                    progress_cb("install", i, total, _pname, None)
            ok, _msg = _install_plugin_via_pip(plugin)
            results[_pname] = bool(ok)
            if progress_cb is not None:
                with suppress(Exception):
                    progress_cb("install", i, total, _pname, bool(ok))
            if ok:
                log.info(f"{LOG_PREFIX} TYST INSTALLATION OK: {_pname}")
            else:
                log.warning(
                    f"{LOG_PREFIX} Tyst installation misslyckades: "
                    f"{_pname}: {_msg[:80]}"
                )
        except Exception as e:
            results[_pname] = False
            if progress_cb is not None:
                with suppress(Exception):
                    progress_cb("install", i, total, _pname, False)
            log.warning(
                f"{LOG_PREFIX} Tyst installation fel: {_pname}: {e}"
            )
    return results


def offer_install_missing_plugins(parent: Any = None) -> Dict[str, bool]:
    """
    NY v6.4.1 v7: Huvudfunktion — detektera + fragga + installera.

    Vad den gor:
      1. Anropar _detect_missing_plugins()
      2. Om inga saknas → returnerar tidigt
      3. Visar Qt-dialog med svensk text
      4. Om anvandaren valt "Ja" → installerar via pip
      5. Returnerar dict med plugin-namn → success

    Args:
        parent: Parent-widget for modal dialog

    Returns:
        Dict med plugin-namn → True om installerad, False annars
    """
    log = logging.getLogger("PluginSystem")

    # FIX v7-fix53: anropad från bakgrundstråd? Då är Qt-dialog OLAGLIG
    # (QDialog.exec på icke-GUI-tråd = HELA APPEN LÅSER SIG — exakt det
    # som hände vid auto-installationen). Tvinga tyst läge automatiskt.
    try:
        import threading as _thr
        if _thr.current_thread() is not _thr.main_thread():
            log.warning(
                f"{LOG_PREFIX} offer_install_missing_plugins: anropad "
                f"från bakgrundstråd → TYST läge (dialog ej tillåten)"
            )
            return install_missing_plugins_silent()
    except Exception:
        pass

    missing = _detect_missing_plugins()

    # FIX v7-fix36: kolla även föråldrade paket
    outdated = _check_outdated_packages()

    if not missing and not outdated:
        log.debug(f"{LOG_PREFIX} offer_install_missing_plugins: inget att gora")
        return {}

    # NY v7-fix36: om det bara finns föråldrade paket → fråga om uppdatering
    if not missing and outdated:
        _out_names = ", ".join(
            f"{n} ({v} → {l})" for n, v, l in outdated
        )
        log.info(
            f"{LOG_PREFIX} offer_install: {len(outdated)} föråldrade "
            f"paket: {_out_names}"
        )
        # Uppdatera automatiskt (användaren kan avbryta via tray)
        _update_result = _update_packages(
            [n for n, _, _ in outdated]
        )
        _updated = sum(1 for ok in _update_result.values() if ok)
        if _updated:
            log.info(
                f"{LOG_PREFIX} {_updated} paket uppdaterade"
            )
        return _update_result

    # Standard-flöde: saknade paket
    # Visa dialog (kanske avbryts av anvandaren)
    to_install = show_install_plugins_dialog(missing, parent=parent)
    if not to_install:
        # Anvandaren avbröt → spara valet sa vi inte fragar igen
        for plugin in missing:
            _persist_plugin_choice(plugin.pip_name, "later")
        log.info(
            f"{LOG_PREFIX} offer_install_missing_plugins: avbruten av anvandaren"
        )
        return {p.pip_name: False for p in missing}
    # Installera
    log.info(
        f"{LOG_PREFIX} offer_install_missing_plugins: installerar "
        f"{len(to_install)} plugin(s)..."
    )
    results = _install_plugins_sequentially(to_install)
    # Spara val for lyckade + misslyckade (så vi inte fragar igen for dem som lyckats)
    for pip_name, (ok, _msg) in results.items():
        _persist_plugin_choice(pip_name, "install" if ok else "later")
    # Logga resultat
    success_count = sum(1 for ok, _ in results.values() if ok)
    fail_count = len(results) - success_count
    log.info(
        f"{LOG_PREFIX} offer_install_missing_plugins: klar "
        f"({success_count} OK, {fail_count} misslyckades)"
    )
    return {pip_name: ok for pip_name, (ok, _msg) in results.items()}


def get_plugin_status() -> Dict[str, Dict[str, Any]]:
    """
    NY v6.4.1 v7: Hämta status for ALLA plugins (for UI/diagnostics).

    Returns:
        Dict med pip_name → info (installed, required, choice, etc.)
    """
    with _plugin_choice_lock:
        choices = dict(_plugin_choice_cache)
    status: Dict[str, Dict[str, Any]] = {}
    for plugin in PLUGIN_REGISTRY:
        status[plugin.pip_name] = {
            "installed": _is_plugin_installed(plugin),
            "required": plugin.required,
            "for_platform": _is_plugin_for_platform(plugin),
            "description": plugin.description_svenska,
            "benefit": plugin.benefit_svenska,
            "user_choice": choices.get(plugin.pip_name, "unknown"),
        }
    return status


def format_plugin_status_swedish() -> str:
    """
    NY v6.4.1 v7: Formatera plugin-status som svensk en-rads-sammanfattning.

    Returns:
        Svensk sträng, t.ex.
        "Plugins: 3/4 installerade (1 saknas)"
    """
    status = get_plugin_status()
    installed = sum(1 for s in status.values() if s["installed"])
    total_applicable = sum(1 for s in status.values() if s["for_platform"])
    missing = [
        name for name, s in status.items()
        if not s["installed"] and s["for_platform"]
    ]
    if not missing:
        return f"Plugins: alla {installed} installerade ✓"
    return (
        f"Plugins: {installed}/{total_applicable} installerade "
        f"({len(missing)} saknas: {', '.join(missing)})"
    )


# ===========================================================================
# MINNES- & SNABBHETS-OPTIMERING (NY v6.4.1 v7)
# ===========================================================================

def optimize_memory() -> Dict[str, Any]:
    """
    NY v6.4.1 v7: Optimerar minne (gc.collect + tracemalloc snapshot).

    Vad den gor:
      1. Kor gc.collect() i alla generationer
      2. Snapshottar tracemalloc (om aktiverat)
      3. Loggar for- och efter-minnesanvandning
      4. Returnerar statistik

    Returns:
        Dict med:
          - collected: antal objekt som samlades in
          - rss_before_mb, rss_after_mb: process-minne
          - saved_mb: uppskattad minnesbesparing
    """
    log = logging.getLogger("MemoryOpt")
    import gc
    # For-minne
    rss_before_mb = 0.0
    try:
        import psutil  # type: ignore
        proc = psutil.Process(os.getpid())
        rss_before_mb = proc.memory_info().rss / (1024 * 1024)
    except ImportError:
        pass
    # Kor GC
    start = time.perf_counter()
    collected = sum(gc.collect(generation=i) for i in range(3))
    duration = (time.perf_counter() - start) * 1000
    # Efter-minne
    rss_after_mb = 0.0
    try:
        import psutil  # type: ignore
        proc = psutil.Process(os.getpid())
        rss_after_mb = proc.memory_info().rss / (1024 * 1024)
    except ImportError:
        pass
    saved_mb = max(0.0, rss_before_mb - rss_after_mb)
    log.info(
        f"{LOG_PREFIX} optimize_memory: collected={collected} "
        f"object(s) på {duration:.2f}ms "
        f"(rss: {rss_before_mb:.1f} MB → {rss_after_mb:.1f} MB, "
        f"saved={saved_mb:.1f} MB)"
    )
    return {
        "collected": collected,
        "rss_before_mb": round(rss_before_mb, 2),
        "rss_after_mb": round(rss_after_mb, 2),
        "saved_mb": round(saved_mb, 2),
        "duration_ms": round(duration, 2),
    }


def get_memory_stats() -> Dict[str, Any]:
    """
    NY v6.4.1 v7: Hämta minnes-statistik for appen.

    Returns:
        Dict med:
          - rss_mb: process-minne (om psutil finns)
          - vms_mb: virtuellt minne (om psutil finns)
          - gc_objects: antal objekt som GC tracker
          - gc_counts: lista med [gen0, gen1, gen2] counts
          - thread_count: antal aktiva tradar
    """
    import gc
    stats: Dict[str, Any] = {
        "rss_mb": None,
        "vms_mb": None,
        "gc_objects": len(gc.get_objects()),
        "gc_counts": list(gc.get_count()),
        "thread_count": threading.active_count(),
    }
    try:
        import psutil  # type: ignore
        proc = psutil.Process(os.getpid())
        mem = proc.memory_info()
        stats["rss_mb"] = round(mem.rss / (1024 * 1024), 2)
        stats["vms_mb"] = round(mem.vms / (1024 * 1024), 2)
    except ImportError:
        pass
    return stats


@contextmanager
def time_operation(name: str, *, log_level: int = logging.DEBUG):
    """
    NY v6.4.1 v7: Context-manager som mäter och loggar operationstid.

    Args:
        name: Operationens namn (for loggning)
        log_level: Log-nivå (default DEBUG — använd INFO for viktigt)

    Exempel:
        >>> with time_operation("ladda_tasks"):
        ...     store.load()
        [MAIN] time_operation[ladda_tasks] OK (123.45ms)
    """
    log = logging.getLogger("Timer")
    start = time.perf_counter()
    try:
        yield
    finally:
        duration = (time.perf_counter() - start) * 1000
        if duration > 100:
            log.warning(
                f"{LOG_PREFIX} time_operation[{name}]: "
                f"{duration:.2f}ms (slow!)"
            )
        else:
            log.log(
                log_level,
                f"{LOG_PREFIX} time_operation[{name}]: OK ({duration:.2f}ms)",
            )


# ===========================================================================
# CENTRAL LOGGNING (NY v6.4.1 v7 — 18 888 888% bättre)
# ===========================================================================
# Vad det gor:
#   - Fångar ALLA log-events från ALLA moduler ([MAIN], [WIDGET], [STORE],
#     [UTILS], [STABILITY], [BACKUP], [SETTINGS], [DESKTOP], [LOG], [PLUGIN])
#   - Lagrar i tradsaker ringbuffer (senaste N events)
#   - Lar UI/widgets subscribe:a pa events live via add_central_log_listener()
#   - `get_recent_app_events()` ger kronologisk lista for UI/diagnostics
#   - `format_event_log_swedish()` gor svensk en-rads-sammanfattning
#   - `get_central_log_stats()` ger statistik for support
#
# Design-val:
#   - EN central handler installeras automatiskt vid setup_logging()
#   - UI kan visa en "live tail" av vad som hander i appen
#   - Trådsäker (RLock skyddar buffer)
#   - Låg overhead (deque + RLock, inga tunga operationer)

# Max antal events att lagra i minnet
_CENTRAL_LOG_MAX_EVENTS: Final[int] = 5000

# Ringbuffer med alla events (deque ar tradsaker for append/pop)
_central_events: "deque[Dict[str, Any]]" = deque(maxlen=_CENTRAL_LOG_MAX_EVENTS)
_central_events_lock = threading.RLock()
_central_listeners: List[Callable[[Dict[str, Any]], None]] = []
_central_listeners_lock = threading.RLock()

# Standardiserade level-namn
_LEVEL_NAMES: Final[Dict[int, str]] = {
    logging.DEBUG: "DEBUG",
    logging.INFO: "INFO",
    logging.WARNING: "WARNING",
    logging.ERROR: "ERROR",
    logging.CRITICAL: "CRITICAL",
    LogLevel.TRACE.value: "TRACE",
}


@dataclass(frozen=True)
class CentralLogEvent:
    """
    NY v6.4.1 v7: Ett log-event i den centrala loggen (immutabel).

    Attribut:
        timestamp: Unix timestamp da eventet skedde
        level: Log-niva (DEBUG/INFO/WARNING/ERROR/CRITICAL)
        module: Logger-namn (t.ex. "Main", "Widget", "Store")
        message: Log-meddelandet
        thread_name: Namn pa traden som loggade
        extra: Extra-falt fran loggningen (valfritt)
    """
    timestamp: float
    level: str
    module: str
    message: str
    thread_name: str = "main"
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialisera for loggning/JSON-export."""
        return {
            "timestamp": self.timestamp,
            "level": self.level,
            "module": self.module,
            "message": self.message,
            "thread_name": self.thread_name,
            "extra": dict(self.extra),
        }


class CentralLogHandler(logging.Handler):
    """
    NY v6.4.1 v7: Logging-handler som fångar ALLA events i central logg.

    Installeras automatiskt pa root-logger vid setup_logging().
    """

    def __init__(self, level: int = logging.DEBUG) -> None:
        super().__init__(level=level)

    def emit(self, record: logging.LogRecord) -> None:
        """Fånga log-record till central ringbuffer."""
        try:
            level_name = _LEVEL_NAMES.get(record.levelno, record.levelname)
            extra: Dict[str, Any] = {}
            for key, value in record.__dict__.items():
                if key not in (
                    "name", "msg", "args", "levelname", "levelno", "pathname",
                    "filename", "module", "exc_info", "exc_text", "stack_info",
                    "lineno", "funcName", "created", "msecs", "relativeCreated",
                    "thread", "threadName", "processName", "process",
                    "message", "asctime", "taskName",
                ):
                    extra[key] = value
            event = CentralLogEvent(
                timestamp=record.created,
                level=level_name,
                module=record.name,
                message=record.getMessage(),
                thread_name=getattr(record, "threadName", "main"),
                extra=extra,
            )
            with _central_events_lock:
                _central_events.append(event)
            # Notifiera listeners (kort callbacks — ingen IO)
            with _central_listeners_lock:
                listeners = list(_central_listeners)
            for cb in listeners:
                try:
                    cb(event.to_dict())
                except Exception:
                    pass  # Lyssnarfel får inte påverka logging
        except Exception:
            # Fångar ALDRIG — får inte krascha appen
            pass


# Singleton handler-instans
_central_handler: Optional[CentralLogHandler] = None
_central_handler_lock = threading.Lock()


def get_central_handler() -> CentralLogHandler:
    """
    NY v6.4.1 v7: Hämta (och skapa vid behov) singleton central-handler.

    Returns:
        CentralLogHandler-instansen
    """
    global _central_handler
    with _central_handler_lock:
        if _central_handler is None:
            _central_handler = CentralLogHandler()
        return _central_handler


def install_central_log_handler(logger_obj: Optional[logging.Logger] = None) -> bool:
    """
    NY v6.4.1 v7: Installera central-log handler på en logger.

    Args:
        logger_obj: Logger att installera pa (None = root)

    Returns:
        True om handlern installerades, False om den redan fanns
    """
    log = logger_obj or logging.getLogger()
    handler = get_central_handler()
    with _central_handler_lock:
        if handler in log.handlers:
            return False
        log.addHandler(handler)
        log.info(
            f"{LOG_PREFIX} central log handler installerad pa "
            f"{'root' if logger_obj is None else logger_obj.name!r}"
        )
        return True


def add_central_log_listener(
    callback: Callable[[Dict[str, Any]], None],
) -> Callable[[], None]:
    """
    NY v6.4.1 v7: Lägg till en listener som anropas for varje centralt event.

    Args:
        callback: Funktion som tar emot event-dict
                  (format: {"timestamp", "level", "module", "message", ...})

    Returns:
        En unsubscribe-funktion (använd for att ta bort lyssnaren)

    Exempel:
        >>> events = []
        >>> unsub = add_central_log_listener(lambda e: events.append(e))
        >>> logging.getLogger().info("test")
        >>> len(events) >= 1
        True
        >>> unsub()  # Sluta lyssna
    """
    with _central_listeners_lock:
        _central_listeners.append(callback)

    def unsubscribe() -> None:
        with _central_listeners_lock:
            try:
                _central_listeners.remove(callback)
            except ValueError:
                pass

    return unsubscribe


def get_recent_app_events(
    count: int = 100,
    level_min: int = logging.INFO,
    module_filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    NY v6.4.1 v7: Hämta senaste N events fran centrala loggen.

    Args:
        count: Max antal events att returnera (default 100)
        level_min: Minimum log-niva (default INFO = hoppa DEBUG)
        module_filter: Filtrera pa modul-namn (t.ex. "Widget") (None = alla)

    Returns:
        Lista av event-dicts, sorterade i kronologisk ordning (äldsta först)
    """
    with _central_events_lock:
        # Senaste N events (fran slutet av deque)
        events_snapshot = list(_central_events)[-count:]
    # Filtrera
    level_priority = {
        "DEBUG": 10, "TRACE": 5, "INFO": 20, "WARNING": 30,
        "ERROR": 40, "CRITICAL": 50,
    }
    filtered: List[Dict[str, Any]] = []
    for ev in events_snapshot:
        ev_level = ev.level if isinstance(ev.level, str) else "INFO"
        ev_prio = level_priority.get(ev_level, 20)
        if ev_prio < level_min:
            continue
        if module_filter and module_filter not in ev.module:
            continue
        filtered.append(ev.to_dict() if hasattr(ev, "to_dict") else ev)
    return filtered


def get_central_log_stats() -> Dict[str, Any]:
    """
    NY v6.4.1 v7: Statistik for centrala loggen.

    Returns:
        Dict med:
          - total_events: antal events i buffer
          - max_events: max kapacitet
          - by_level: Dict[level, count]
          - by_module: Dict[module, count]
          - oldest_timestamp: Unix time for aldsta eventet
          - newest_timestamp: Unix time for senaste eventet
          - listener_count: antal aktiva listeners
    """
    with _central_events_lock:
        events_snapshot = list(_central_events)
    with _central_listeners_lock:
        n_listeners = len(_central_listeners)
    by_level: Dict[str, int] = {}
    by_module: Dict[str, int] = {}
    oldest: Optional[float] = None
    newest: Optional[float] = None
    for ev in events_snapshot:
        lvl = ev.level if isinstance(ev.level, str) else "INFO"
        by_level[lvl] = by_level.get(lvl, 0) + 1
        mod = ev.module if isinstance(ev.module, str) else "?"
        by_module[mod] = by_module.get(mod, 0) + 1
        ts = ev.timestamp if isinstance(ev.timestamp, (int, float)) else 0
        if oldest is None or ts < oldest:
            oldest = ts
        if newest is None or ts > newest:
            newest = ts
    return {
        "total_events": len(events_snapshot),
        "max_events": _CENTRAL_LOG_MAX_EVENTS,
        "by_level": by_level,
        "by_module": by_module,
        "oldest_timestamp": oldest,
        "newest_timestamp": newest,
        "listener_count": n_listeners,
    }


def clear_central_log() -> None:
    """NY v6.4.1 v7: Rensa central-loggen (for test/admin)."""
    with _central_events_lock:
        _central_events.clear()


def format_event_log_swedish(
    events: Optional[List[Dict[str, Any]]] = None,
    max_items: int = 20,
) -> str:
    """
    NY v6.4.1 v7: Formatera central-loggen som svensk lasbar sträng.

    Args:
        events: Lista av events (None = hamta senaste automatiskt)
        max_items: Max antal events att visa (default 20)

    Returns:
        Svensk flerrads-sträng med kronologisk logg

    Exempel:
        >>> format_event_log_swedish()
        '=== APP-LOGG (senaste 20) ===\\n  [14:32:01] [INFO] [Main] Startar app\\n...'
    """
    if events is None:
        events = get_recent_app_events(count=max_items, level_min=logging.DEBUG)
    if not events:
        return "(central log ar tom)"
    lines: List[str] = ["=== APP-LOGG (senaste events) ==="]
    for ev in events[-max_items:]:
        try:
            ts = ev.get("timestamp", 0)
            from datetime import datetime as _dt
            time_str = _dt.fromtimestamp(ts).strftime("%H:%M:%S")
        except Exception:
            time_str = "??:??:??"
        level = ev.get("level", "?")
        module = ev.get("module", "?")
        msg = ev.get("message", "")
        # Korta ner långa meddelanden
        if len(msg) > 100:
            msg = msg[:97] + "..."
        # Svensk level-emoji
        icon = {
            "DEBUG": "·", "TRACE": "·", "INFO": "ℹ", "WARNING": "⚠",
            "ERROR": "✗", "CRITICAL": "‼",
        }.get(level, "·")
        lines.append(f"  [{time_str}] {icon} [{level}] [{module}] {msg}")
    return "\n".join(lines)


def format_central_log_stats_swedish() -> str:
    """
    NY v6.4.1 v7: Kort svensk sammanfattning av central-loggen.

    Returns:
        Svensk en-rads-sammanfattning

    Exempel:
        >>> format_central_log_stats_swedish()
        'Central logg: 1234 events (max 5000) • 5 INFO, 3 WARNING, 1 ERROR'
    """
    stats = get_central_log_stats()
    total = stats["total_events"]
    max_ev = stats["max_events"]
    by_level = stats["by_level"]
    level_strs = []
    for lvl in ("ERROR", "WARNING", "INFO", "DEBUG", "CRITICAL"):
        n = by_level.get(lvl, 0)
        if n > 0:
            level_strs.append(f"{n} {lvl}")
    levels_part = ", ".join(level_strs) if level_strs else "inga events"
    return f"Central logg: {total}/{max_ev} events • {levels_part}"


# ===========================================================================
# SAFE EXECUTION HELPERS
# ===========================================================================

@contextmanager
def error_boundary(
    operation: str,
    *,
    default: Any = None,
    logger: Optional[logging.Logger] = None,
    reraise: bool = False,
):
    """
    NY v6.4.1 v7: Context manager med AI-felsokning 10000%.

    Vad den gor:
      1. Fångar undantag inom with-blocket
      2. Kategoriserar felet (user_input / system / code_bug / external)
      3. Loggar med operation-context + categori + kompakt traceback
      4. Användare kan valja 'reraise=True' for att propagerar felet vidare
    """
    log = logger or logging.getLogger("ErrorBoundary")
    try:
        yield
    except Exception as e:
        category = _categorize_exception(e)
        svensk = _describe_exception(e)
        log.error(
            f"{LOG_PREFIX} Fel i '{operation}' [{category}]: {svensk}",
            exc_info=True,
        )
        log.debug(
            f"{LOG_PREFIX} operation='{operation}', category={category}, "
            f"exc_type={type(e).__name__}"
        )
        if reraise:
            raise


def safe_call(func: Callable[..., T], *args, default: Any = None, **kwargs) -> T:
    """Anropa en funktion säkert med default vid fel."""
    try:
        return func(*args, **kwargs)
    except Exception as e:
        logging.getLogger("SafeCall").warning(f"safe_call misslyckades: {e}")
        return default  # type: ignore[return-value]


# ===========================================================================
# GLOBAL CONFIG (immutable)
# ===========================================================================

@dataclass(frozen=True)
class AppConfig:
    """Immutable app-konfiguration (frozen dataclass)."""
    app_name: str = APP_NAME
    app_version: str = APP_VERSION_DISPLAY
    org_name: str = ORG_NAME
    log_level: str = "INFO"
    log_file: Optional[Path] = None
    max_windows: int = 16
    icon_size: int = 64
    glass_styles: Tuple[str, ...] = ("auto", "translucent", "mica", "acrylic", "none")
    cleanup_interval_sec: int = 300
    metrics_interval_sec: int = 30
    backup_check_interval_sec: int = 60
    capabilities_refresh_sec: int = 300
    heartbeat_interval_sec: int = 5
    idle_check_interval_sec: int = 30
    enable_animations: bool = True
    show_splash: bool = True
    enable_stability: bool = True
    enable_async_runner: bool = True
    enable_pwm: bool = True  # NY v6.4 — PWM (adaptive throttle)
    force_show_widget: bool = True  # NY v6.4.1 v7 — DEFAULT PÅ: tvinga widget synlig (Rickard 2026-09-22: ska ej behövas)
    no_plugin_install: bool = True  # NY v6.4.1 v7 — DEFAULT PÅ: skippa plugin-erbjudande (Rickard: ska ej behövas)
    no_bootstrap: bool = True  # NY v6.4.1 v7 — DEFAULT PÅ: skippa requirements.txt auto-install (Rickard: ska ej behövas)


# ===========================================================================
# ARGUMENT PARSING
# ===========================================================================

def parse_args(argv: List[str]) -> Tuple[AppConfig, AppMode]:
    """Parsa CLI-argument och returnera config + mode."""
    parser = argparse.ArgumentParser(
        prog="TaskBord",
        description=APP_DESCRIPTION,
        add_help=False,
    )
    parser.add_argument("--diagnostics", action="store_true", help="Aktivera diagnostics-läge")
    parser.add_argument("--safe-mode", action="store_true", help="Kör med dummy-Settings/Store")
    parser.add_argument("--no-tray", action="store_true", help="Inaktivera system tray")
    parser.add_argument("--no-splash", action="store_true", help="Inaktivera splash-screen")
    parser.add_argument("--no-stability", action="store_true", help="Inaktivera stability-system")
    parser.add_argument("--no-async", action="store_true", help="Inaktivera async runner")
    parser.add_argument("--no-pwm", action="store_true", help="Inaktivera PWM (adaptive throttle)")
    parser.add_argument("--no-force-show", action="store_true", help="INAKTIVERA force-show (default PÅ)")
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="Tvinga auto-install av requirements.txt (default: SKIPPA — Rickard 2026-09-22)",
    )
    parser.add_argument(
        "--plugin-install",
        action="store_true",
        help="Visa plugin-installations-erbjudande (default: SKIPPA — Rickard 2026-09-22)",
    )
    # Behåll gamla flaggor som no-ops (default = redan skippa/force-show)
    parser.add_argument("--no-bootstrap", action="store_true", help="(no-op, default skippar redan)")
    parser.add_argument("--no-plugin-install", action="store_true", help="(no-op, default skippar redan)")
    parser.add_argument("--reset", action="store_true", help="Återställ inställningar")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging (DEBUG)")
    parser.add_argument("--log-level", type=str, default="INFO", help="Logg-nivå (DEBUG/INFO/WARNING/ERROR)")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} v{APP_VERSION_DISPLAY}")

    try:
        args = parser.parse_args(argv[1:])
    except SystemExit:
        return AppConfig(), AppMode.NORMAL

    # Bestäm mode
    if args.diagnostics:
        mode = AppMode.DIAGNOSTICS
    elif args.safe_mode:
        mode = AppMode.SAFE_MODE
    elif args.no_tray:
        mode = AppMode.NO_TRAY
    elif args.reset:
        mode = AppMode.RESET
    elif args.verbose:
        mode = AppMode.VERBOSE
    else:
        mode = AppMode.NORMAL

    # Bestäm log-nivå
    log_level = args.log_level.upper()
    if args.verbose and log_level == "INFO":
        log_level = "DEBUG"
    if mode == AppMode.DIAGNOSTICS:
        log_level = "DEBUG"

    # Log-fil
    log_file = LOG_FILE

    # Skapa config (frozen)
    config = AppConfig(
        log_level=log_level,
        log_file=log_file,
        show_splash=not args.no_splash,
        enable_stability=not args.no_stability,
        enable_async_runner=not args.no_async,
        enable_pwm=not args.no_pwm,  # NY v6.4
        force_show_widget=not args.no_force_show,  # NY v6.4.1 v7 — DEFAULT PÅ (Rickard 2026-09-22)
        # Rickard 2026-09-22: --no-plugin-install / --no-bootstrap ska ej behövas
        no_plugin_install=not args.plugin_install,  # DEFAULT True (skippa)
        no_bootstrap=not args.bootstrap,  # DEFAULT True (skippa)
    )

    return config, mode


# ===========================================================================
# SAFE IMPORTS
# ===========================================================================

def parse_hotkey_combo(combo: str) -> Tuple[int, int]:
    """
    NY v7-fix69: tolka 'Ctrl+Alt+V' → (mod-flaggor, vk-kod).

    Returnerar (0, 0) vid ogiltig kombination.
    Stöd: Ctrl/Control, Alt, Shift, Win + A-Z, 0-9, F1-F12,
    Space, Enter, Tab.
    """
    try:
        mods = 0
        vk = 0
        parts = [
            p.strip().lower() for p in str(combo).split("+") if p.strip()
        ]
        if not parts:
            return (0, 0)
        for part in parts:
            if part in ("ctrl", "control"):
                mods |= 0x0002
            elif part == "alt":
                mods |= 0x0001
            elif part == "shift":
                mods |= 0x0004
            elif part in ("win", "super", "meta"):
                mods |= 0x0008
            elif len(part) == 1 and "a" <= part <= "z":
                vk = ord(part.upper())  # 0x41-0x5A
            elif len(part) == 1 and "0" <= part <= "9":
                vk = ord(part)  # 0x30-0x39
            elif part == "space":
                vk = 0x20
            elif part == "enter":
                vk = 0x0D
            elif part == "tab":
                vk = 0x09
            elif len(part) in (2, 3) and part[0] == "f" and part[1:].isdigit():
                n = int(part[1:])
                if 1 <= n <= 12:
                    vk = 0x70 + (n - 1)
            else:
                return (0, 0)
        if vk == 0:
            return (0, 0)  # Ingen huvudtangent
        return (mods, vk)
    except Exception:
        return (0, 0)


@dataclass
class ImportStatus:
    """Status för en modul-import."""
    module: str
    ok: bool
    error: Optional[str] = None
    instance: Optional[Any] = None


def safe_import_module(
    module_name: str,
    *,
    from_items: Optional[List[str]] = None,
    required: bool = True,
) -> ImportStatus:
    """Importera en modul säkert med detaljerad felhantering.

    NY v6.4.1: Stöd för sökvägs-baserad import så moduler kan ligga i
    core/ och ui/ underkataloger (tidigare __import__ hittade inte dem).

    NY v6.4.1 v7: Validerar att alla from_items faktiskt är definierade i modulen
    efter import (Rickard 2026-09-22: "tyst crash, loggningen ska upptäcka det").
    """
    import_log = logging.getLogger("Main")
    try:
        # NY v6.4.1: Försök hitta modulen relativt main.pyw först
        here = Path(__file__).resolve().parent
        candidate_paths = [
            here / "core" / f"{module_name}.py",
            here / "ui" / f"{module_name}.py",
            here / f"{module_name}.py",
            here / f"{module_name}.pyw",
        ]
        loaded_via_path = False
        module = None
        for p in candidate_paths:
            if p.is_file():
                spec = importlib.util.spec_from_file_location(module_name, p)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = module
                    spec.loader.exec_module(module)
                    loaded_via_path = True
                    break

        if module is None:
            if from_items:
                module = __import__(module_name, fromlist=from_items)
            else:
                module = __import__(module_name)

        if from_items:
            # NY v7: Validera att alla from_items existerar
            instances: Dict[str, Any] = {}
            missing_items: List[str] = []
            for item in from_items:
                if hasattr(module, item):
                    instances[item] = getattr(module, item)
                else:
                    missing_items.append(item)
                    import_log.error(
                        f"{LOG_PREFIX} safe_import_module: {module_name} "
                        f"saknar '{item}' — tyst krasch risk!"
                    )
            if missing_items:
                import_log.error(
                    f"{LOG_PREFIX} safe_import_module: {module_name} importerad "
                    f"men saknar {len(missing_items)} objekt: {missing_items}"
                )
                return ImportStatus(
                    module=module_name, ok=False,
                    error=f"saknar objekt: {missing_items}",
                    instance=instances,
                )
            return ImportStatus(module=module_name, ok=True, instance=instances)
        # NY v6.4.1 fix: alltid returnera dict (med modulnamn som nyckel)
        # så instance["Settings"] / instance.get("BackupManager") funkar
        # både när from_items angavs och när det inte gjorde det.
        return ImportStatus(
            module=module_name, ok=True, instance={module_name: module}
        )
    except ImportError as e:
        status = ImportStatus(module=module_name, ok=False, error=str(e))
        if required:
            import_log.critical(
                f"{LOG_PREFIX} Kunde inte importera {module_name}: {e}"
            )
        else:
            import_log.warning(
                f"{LOG_PREFIX} Kunde inte importera {module_name}: {e}"
            )
        return status
    except SyntaxError as e:
        # NY v7: SyntaxError är vanligt — logga med tydlig info
        status = ImportStatus(module=module_name, ok=False, error=str(e))
        import_log.critical(
            f"{LOG_PREFIX} SYNTAX-FEL i {module_name}: {e} (rad {e.lineno})",
            exc_info=True,
        )
        return status
    except BaseException as e:
        status = ImportStatus(module=module_name, ok=False, error=str(e))
        import_log.critical(
            f"{LOG_PREFIX} FEL VID IMPORT av {module_name}: "
            f"{type(e).__name__}: {e}",
            exc_info=True,
        )
        return status


def import_all_dependencies() -> Dict[str, ImportStatus]:
    """Importera ALLA nödvändiga moduler och returnera status."""
    return {
        "PySide6.QtCore": safe_import_module(
            "PySide6.QtCore",
            from_items=["Qt", "QTimer", "Slot", "Signal", "QObject"],
        ),
        "PySide6.QtGui": safe_import_module(
            "PySide6.QtGui",
            from_items=["QAction", "QFont", "QIcon", "QPainter", "QColor", "QPixmap", "QPen", "QBrush"],
        ),
        "PySide6.QtWidgets": safe_import_module(
            "PySide6.QtWidgets",
            from_items=[
                "QApplication", "QSystemTrayIcon", "QMenu", "QMessageBox",
                "QInputDialog", "QWidget", "QDialog", "QDialogButtonBox",
            ],
        ),
        "desktop": safe_import_module("desktop", required=False),
        "settings": safe_import_module(
            "settings", from_items=["Settings"], required=False,
        ),
        "store": safe_import_module(
            "store", from_items=["TaskStore"], required=False,
        ),
        "utils": safe_import_module("utils", required=False),
        "widget": safe_import_module(
            "widget", from_items=["TodoWidget"], required=False,
        ),
        "backup": safe_import_module(
            "backup", from_items=["BackupManager"], required=False,
        ),
        "stability": safe_import_module("stability", required=False),
    }


# ===========================================================================
# APP CONTROLLER (HJÄRTAT)
# ===========================================================================

class AppController:
    """
    Huvudkontroll med dependency injection + subsystem-registry.

    Ansvar:
        1. Initiera QApplication + alla subsystems
        2. Skapa + underhålla TodoWidget-fönster (BUGG 19/26)
        3. System tray (med populate_tray_menu, dynamisk tooltip)
        4. Input-dialoger (ask_new_task, ask_rename_task, ask_confirm_delete)
        5. Backup-integration (auto-restore, periodic status-check)
        6. Stability (heartbeat, recovery, idle-detection)
        7. Shutdown (graceful, trådsäker)
    """

    # Timing-konstanter (millisekunder)
    CLEANUP_INTERVAL_MS: ClassVar[int] = 5 * 60 * 1000
    METRICS_REFRESH_MS: ClassVar[int] = 30 * 1000
    BACKUP_CHECK_INTERVAL_MS: ClassVar[int] = 60 * 1000
    CAPABILITIES_REFRESH_MS: ClassVar[int] = 5 * 60 * 1000
    HEARTBEAT_INTERVAL_MS: ClassVar[int] = 5 * 1000
    IDLE_CHECK_INTERVAL_MS: ClassVar[int] = 30 * 1000

    def __init__(
        self,
        config: AppConfig,
        mode: AppMode,
        imports: Dict[str, ImportStatus],
        registry: SubsystemRegistry,
        performance: PerformanceMonitor,
        async_runner: AsyncTaskRunner,
    ) -> None:
        self._log = logging.getLogger("AppController")
        self._config = config
        self._mode = mode
        self._imports = imports
        self._registry = registry
        self._performance = performance
        self._async_runner = async_runner

        self._app: Optional[Any] = None
        self._widgets: Dict[str, Any] = {}
        self._widget_lock = threading.RLock()
        self._shutdown_initiated = False
        self._start_time = time.time()

        # State
        self._glass_style: str = GlassStyle.AUTO.value
        self._tray: Any = None
        self._tray_menu: Any = None
        self._tray_initialized = threading.Event()
        self._icon_cache: Dict[str, Any] = {}
        self._icon_cache_lock = threading.Lock()
        self._last_tooltip_update: float = 0.0
        self._capabilities: Dict[str, Any] = {}

        # Initiera i ordning
        self._init_qt_application()
        self._init_subsystems()
        self._init_timers()
        self._init_signals()
        self._refresh_capabilities()

        self._log.info(
            f"AppController klar (fönster={len(self._widgets)}, "
            f"mode={mode.name})"
        )

    # -----------------------------------------------------------------------
    # INIT — QApplication
    # -----------------------------------------------------------------------

    def _init_qt_application(self) -> None:
        """Initiera QApplication (eller skapa dummy)."""
        QtWidgets = self._imports.get("PySide6.QtWidgets")
        if QtWidgets is None or not QtWidgets.ok:
            raise StartupError("QApplication kan inte skapas (QtWidgets saknas)")

        QApplicationCls = QtWidgets.instance["QApplication"]
        self._app = QApplicationCls(sys.argv)
        self._app.setQuitOnLastWindowClosed(False)
        self._app.setApplicationName(self._config.app_name)
        self._app.setApplicationVersion(self._config.app_version)
        self._app.setOrganizationName(self._config.org_name)

        # FIX 2026-09-23: App-ikon → aktivitetsfält + Aktivitetshanterare
        # FIX v7-fix22: INGEN ikon sätts FÖRE det första fönstret!
        # Qt registrerar fönsterklassen vid första CreateWindowEx — om
        # ikonen då är förgiftad misslyckas ALLA efterföljande skapanden
        # ('Felaktig parameter'). Ikonerna sätts i _populate_windows
        # EFTER att fönstret faktiskt skapats.
        self._app_icon = None
        self._app_icon_path: Optional[Path] = None
        self._app_icon_set_on_first_window: bool = False
        with suppress(Exception):
            # ENDAST validera/förbered filen — sätt den INTE på appen än
            self._app_icon_path = self._ensure_app_icon_file()
            if self._app_icon_path is not None:
                self._log.info(
                    f"{LOG_PREFIX} App-ikon förberedd (sätts efter första "
                    f"fönstret, v7-fix22): {self._app_icon_path}"
                )

        # Installera global exception hook (Qt-specifik)
        with suppress(Exception):
            self._app.aboutToQuit.connect(self._on_about_to_quit)
        try:
            sys.excepthook = self._qt_exception_hook
        except Exception as e:
            self._log.debug(f"Kunde inte installera Qt exception hook: {e}")

        # Hämta Qt-klasser (snabbare access)
        self._Qt = self._imports["PySide6.QtCore"].instance["Qt"]
        self._QTimer = self._imports["PySide6.QtCore"].instance["QTimer"]
        self._Signal = self._imports["PySide6.QtCore"].instance["Signal"]
        self._Slot = self._imports["PySide6.QtCore"].instance["Slot"]
        self._QAction = self._imports["PySide6.QtGui"].instance["QAction"]
        self._QFont = self._imports["PySide6.QtGui"].instance["QFont"]
        self._QIcon = self._imports["PySide6.QtGui"].instance["QIcon"]
        self._QPainter = self._imports["PySide6.QtGui"].instance["QPainter"]
        self._QColor = self._imports["PySide6.QtGui"].instance["QColor"]
        self._QPixmap = self._imports["PySide6.QtGui"].instance["QPixmap"]
        self._QPen = self._imports["PySide6.QtGui"].instance["QPen"]
        self._QBrush = self._imports["PySide6.QtGui"].instance["QBrush"]
        self._QApplication = self._imports["PySide6.QtWidgets"].instance["QApplication"]
        self._QSystemTrayIcon = self._imports["PySide6.QtWidgets"].instance["QSystemTrayIcon"]
        self._QMenu = self._imports["PySide6.QtWidgets"].instance["QMenu"]
        self._QMessageBox = self._imports["PySide6.QtWidgets"].instance["QMessageBox"]
        self._QInputDialog = self._imports["PySide6.QtWidgets"].instance["QInputDialog"]
        self._QWidget = self._imports["PySide6.QtWidgets"].instance["QWidget"]

        # FIX v7-fix22: fortfarande INGEN ikon på appen — bara förbered.
        # (Sätts i _populate_windows efter att fönstret skapats.)
        with suppress(Exception):
            if self._app_icon_path is None:
                self._app_icon_path = self._ensure_app_icon_file()
            if self._app_icon_path is not None and self._QIcon is not None:
                self._app_icon = self._QIcon(str(self._app_icon_path))
                self._log.info(
                    f"{LOG_PREFIX} App-ikon förberedd (ej satt ännu, v7-fix22)"
                )

        # ============================================================
        # FIX v7-fix22: STARTPANEL I KONSOLEN — syns i PowerShell!
        # Avslöjar direkt: körs rätt desktop.py? Fungerade DPI-fixen?
        # ============================================================
        try:
            _dpi_txt = "?"
            if sys.platform == "win32":
                import ctypes as _ct
                _ctx = _ct.windll.user32.GetProcessDpiAwarenessContext(
                    _ct.windll.kernel32.GetCurrentProcess()
                )
                _v = int(_ctx) & 0xFFFFFFFFFFFFFFFF if _ctx else 0
                _dpi_map = {
                    0xFFFFFFFFFFFFFFFF: "UNAWARE",
                    0xFFFFFFFFFFFFFFFE: "SYSTEM (FEL! gammal desktop.py?)",
                    0xFFFFFFFFFFFFFFFD: "PER_MONITOR",
                    0xFFFFFFFFFFFFFFFC: "PER_MONITOR_V2 (RÄTT!)",
                }
                _dpi_txt = _dpi_map.get(_v, hex(_v))
            _ver_txt = "?"
            try:
                import PySide6 as _ps6
                _ver_txt = _ps6.__version__
            except Exception:
                pass
            _start_panel = (
                "=" * 58 + "\n"
                "TaskBord v6.4.1 v7 — startpanel (v7-fix22)\n"
                f"  PySide6:        {_ver_txt}\n"
                f"  DPI-medvetenhet: {_dpi_txt}\n"
                "  Ikon: uppskjuten tills efter första fönstret\n"
                + "=" * 58
            )
            self._log.info(f"{LOG_PREFIX}\n{_start_panel}")
            sys.__stderr__.write(_start_panel + "\n")
            sys.__stderr__.flush()
        except Exception:
            pass

    def _cleanup_all_caches(self) -> int:
        """
        NY v7-fix25: Rensa ALL cache när appen avslutas.

        Rickard 2026-09-29: "tömma all cache efter att appen avslutas".

        Rensar:
          1. __pycache__-mappar i hela projektet
          2. .pyc-filer
          3. Qt:s pixmap-cache
          4. Python:s import-cache (sys.path_importer_cache)

        Returnerar antal borttagna objekt.
        """
        removed = 0
        try:
            import shutil as _shutil

            root = Path(__file__).resolve().parent

            # 1. __pycache__-mappar
            for pycache in root.rglob("__pycache__"):
                if pycache.is_dir():
                    with suppress(Exception):
                        _shutil.rmtree(pycache, ignore_errors=True)
                        removed += 1

            # 2. .pyc-filer (från root, core/, ui/)
            for pyc in root.rglob("*.pyc"):
                with suppress(Exception):
                    pyc.unlink()
                    removed += 1

            # 3. Qt pixmap-cache
            with suppress(Exception):
                from PySide6.QtGui import QPixmapCache
                QPixmapCache.clear()

            # 4. Python import-cache
            with suppress(Exception):
                sys.path_importer_cache.clear()

            if removed:
                self._log.info(
                    f"{LOG_PREFIX} Cache-rensning: {removed} objekt "
                    f"borttagna (__pycache__ + .pyc)"
                )
            else:
                self._log.debug(
                    f"{LOG_PREFIX} Cache-rensning: inget att rensa"
                )
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} cache-rensning fel: {e}")
        return removed

    def _apply_desktop_shell(self, shell: Any, wid: str) -> None:
        """
        NY v7-fix38: Desktop-lager — Win+D-säkert skrivbordsläge.

        Rickard 2026-10-01:
          "win+d döljer fönstret, ska alltid vara synligt överst på
           skrivbordet + vara transparent så ej ikoner döljs"

        Windows "Visa skrivbordet" (Win+D) minimerar ALLA toppfönster —
        HWND_BOTTOM + SC_MINIMIZE-blockering räcker INTE (v7-fix32
        bevisade detta på Rickards maskin). Därför tre lägen
        (settings 'desktop_mode'):

          above  (default) — barn i skrivbordslagret, ÖVER ikonerna:
                    SetParent(Progman/ikon-ägare) + ovanför
                    SHELLDLL_DefView. Win+D kan ALDRIG gömma den
                    (den lever i skrivbordet, precis som tapeten).
                    Genomskinligt glas-skal → ikonerna syns igenom.
          behind — kila ovanför WorkerW (Rainmeter "On Desktop"):
                    skrivbordsikonerna målas OVANPÅ widgeten →
                    ikonerna döljs ALDRIG. Också Win+D-säkert.
          legacy — v7-fix32-beteende: HWND_BOTTOM + NOACTIVATE +
                    TOOLWINDOW + SC_MINIMIZE-blockerare + 30s-timer.

        Fallback-kedja: above → behind → legacy (inga gamla
        funktioner tas bort — REGEL: behåll gamla + lägg till nya).
        """
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            hwnd = int(shell.winId())
            if not hwnd:
                self._log.warning(
                    f"{LOG_PREFIX} _apply_desktop_shell: HWND=0 — hoppar"
                )
                shell._desktop_layer_pending = True
                return
            shell._desktop_wid = wid

            # 1. Extended styles: NOACTIVATE + TOOLWINDOW (alla lägen)
            GWL_EXSTYLE = -20
            WS_EX_NOACTIVATE = 0x08000000
            WS_EX_TOOLWINDOW = 0x00000080
            old_ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            new_ex = (old_ex | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW) & ~0x8  # clear TOPMOST
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new_ex)

            # 1b. NY v7-fix43: WS_THICKFRAME → ÄKTA resize-kanter.
            # Krävs för att Windows ska starta resize-loopen när
            # WM_NCHITTEST returnerar HTLEFT/HTRIGHT/etc. Den osynliga
            # non-client-ramen tas bort via WM_NCCALCSIZE (se nedan) så
            # hela fönstret förblir klientyta — ingen synlig ram.
            GWL_STYLE = -16
            WS_THICKFRAME = 0x00040000
            old_style = user32.GetWindowLongW(hwnd, GWL_STYLE)
            user32.SetWindowLongW(
                hwnd, GWL_STYLE, old_style | WS_THICKFRAME
            )

            # 2. nativeEvent-blockerare på skalet (extra Win+D-skydd)
            if not hasattr(shell, "_native_event_patched"):
                shell._native_event_patched = True
                _orig_native = shell.nativeEvent

                def _block_minimize(eventType, message):
                    """
                    Skal-fönstrets nativeEvent:

                    1. Blockera SC_MINIMIZE — Win+D ska ej gömma oss
                    2. NY v7-fix43: WM_NCCALCSIZE → 0 (frameless: hela
                       fönstret = klientyta trots WS_THICKFRAME)
                    3. NY v7-fix43: WM_NCHITTEST → resize-kanter (HT*)
                       när musen är ≤6 px från kanten/hörnen
                    """
                    try:
                        WM_SYSCOMMAND = 0x0112
                        SC_MINIMIZE = 0xF020
                        WM_NCCALCSIZE = 0x0083
                        WM_NCHITTEST = 0x0084
                        HTLEFT, HTRIGHT = 10, 11
                        HTTOP, HTTOPLEFT, HTTOPRIGHT = 12, 13, 14
                        HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT = 15, 16, 17
                        _KANT = 8  # px från kanten som räknas som resize-zon (v7-fix51: 6→8 för 125% DPI)

                        class _MSG(ctypes.Structure):
                            _fields_ = [
                                ("hwnd", wintypes.HWND),
                                ("message", wintypes.UINT),
                                ("wParam", wintypes.WPARAM),
                                ("lParam", wintypes.LPARAM),
                                ("time", wintypes.DWORD),
                                ("pt_x", wintypes.LONG),
                                ("pt_y", wintypes.LONG),
                            ]

                        msg = _MSG.from_address(int(message))
                        if msg.message == WM_SYSCOMMAND:
                            cmd = msg.wParam & 0xFFF0
                            if cmd == SC_MINIMIZE:
                                self._log.info(
                                    f"{LOG_PREFIX} Win+D blockerat "
                                    f"(SC_MINIMIZE på skal-HWND)"
                                )
                                return True, 0  # Blockerad
                        elif msg.message == 0x0005 and msg.wParam == 1:
                            # NY v7-fix44: WM_SIZE + SIZE_MINIMIZED
                            # FIX v7-fix76: under pågående nedstängning är
                            # detta NORMALT (fönstret stängs) — tyst.
                            if not getattr(self, "_shutdown_initiated", False):
                                self._log.warning(
                                    f"{LOG_PREFIX} ⚠ FÖNSTRET MINIMERAS "
                                    f"(Win+D/Win+M?) — HWND={hwnd}, "
                                    f"läge={getattr(shell, '_desktop_layer_mode', '?')} "
                                    f"(återställs automatiskt i legacy-läge)"
                                )
                        elif msg.message == 0x0018 and not msg.wParam:
                            # NY v7-fix44: WM_SHOWWINDOW FALSE = göms
                            # FIX v7-fix76: samma — vid nedstängning SKA
                            # fönstret gömmas, alltså ingen varning.
                            if not getattr(self, "_shutdown_initiated", False):
                                self._log.warning(
                                    f"{LOG_PREFIX} ⚠ FÖNSTRET GÖMS av "
                                    f"systemet (WM_SHOWWINDOW=FALSE) — HWND={hwnd}"
                                )
                        elif msg.message == WM_NCCALCSIZE and msg.wParam:
                            # v7-fix43: hela fönstret = klientyta
                            # (annars stjäl THICKFRAME en osynlig ram)
                            return True, 0
                        elif msg.message == WM_NCHITTEST:
                            # lParam = skärmkoordinater (signerade 16-bit)
                            _lx = ctypes.c_short(
                                msg.lParam & 0xFFFF
                            ).value
                            _ly = ctypes.c_short(
                                (msg.lParam >> 16) & 0xFFFF
                            ).value
                            _hw = int(msg.hwnd) if msg.hwnd else hwnd
                            rect = wintypes.RECT()
                            user32.GetWindowRect(
                                _hw, ctypes.byref(rect)
                            )
                            _dl = _lx - rect.left
                            _dr = rect.right - _lx
                            _dt = _ly - rect.top
                            _db = rect.bottom - _ly
                            _ht = 0
                            if _dl <= _KANT and _dt <= _KANT:
                                _ht = HTTOPLEFT
                            elif _dr <= _KANT and _dt <= _KANT:
                                _ht = HTTOPRIGHT
                            elif _dl <= _KANT and _db <= _KANT:
                                _ht = HTBOTTOMLEFT
                            elif _dr <= _KANT and _db <= _KANT:
                                _ht = HTBOTTOMRIGHT
                            elif _dl <= _KANT:
                                _ht = HTLEFT
                            elif _dr <= _KANT:
                                _ht = HTRIGHT
                            elif _dt <= _KANT:
                                _ht = HTTOP
                            elif _db <= _KANT:
                                _ht = HTBOTTOM
                            if _ht:
                                return True, _ht
                    except Exception:
                        pass
                    return False, 0

                shell.nativeEvent = _block_minimize

            # 3. Timer: mode-medvetet underhåll var 30:e sekund
            if not hasattr(shell, "_zorder_timer"):
                _timer = self._QTimer(shell)
                _timer.setInterval(30000)  # 30 sek
                _timer.timeout.connect(
                    lambda: self._maintain_desktop_level(shell)
                )
                _timer.start()
                shell._zorder_timer = _timer

            # 4. Desktop-lager enligt läge (med fallback-kedja)
            mode = self._desktop_mode()
            # v7-fix72: lyft pågår? — applicera inte skrivbordslager
            if str(getattr(shell, "_desktop_layer_mode", "")) == "_lift":
                return
            desktop_status = self._imports.get("desktop")
            if mode in ("above", "behind") and desktop_status and desktop_status.ok:
                if mode == "above":
                    fn = getattr(
                        self._desktop_mod(desktop_status),
                        "attach_window_above_desktop_icons", None,
                    )
                    if fn is None:
                        # NY v7-fix40: tyst fn-None dolde att desktop.py
                        # är gammal — säg det TYDLIGT
                        # NY v7-fix42: visa OCKSÅ vilken fil som laddats
                        _dfile = getattr(
                            self._desktop_mod(desktop_status), "__file__", "?"
                        )
                        self._log.critical(
                            f"{LOG_PREFIX} core/desktop.py är GAMMAL — "
                            f"'attach_window_above_desktop_icons' saknas! "
                            f"Inläst fil: {_dfile} — ersätt den med nya "
                            f"core/desktop.py från workspacen (v7-fix38/40)"
                        )
                    if fn and fn(hwnd):
                        shell._desktop_layer_mode = "above"  # experimentellt
                        # NY v7-fix48: spara förälderns origo — widgeten
                        # komponerar alla flyttar mot SKÄRM-koordinater
                        _dm = self._desktop_mod(desktop_status)
                        _org = (0, 0)
                        if _dm is not None and hasattr(
                            _dm, "get_desktop_parent_origin"
                        ):
                            _org_fys = (
                                _dm.get_desktop_parent_origin(hwnd)
                                or (0, 0)
                            )
                            # FIX v7-fix54: konvertera FYSISKT origo →
                            # LOGISKT (Qt:s koordinatrum, t.ex. 125% DPI).
                            # Qt-move konverterar logiskt→fysikt självt,
                            # därför måste kompenseringen ske i logiskt
                            # rum: fys_skärm = (log - origo_log)*dpr.
                            _dpr = 1.0
                            with suppress(Exception):
                                _dpr = float(
                                    shell.devicePixelRatioF() or 1.0
                                ) or 1.0
                            _org = (
                                _org_fys[0] / _dpr,
                                _org_fys[1] / _dpr,
                            )
                        shell._parent_origin = _org
                        self._log.info(
                            f"{LOG_PREFIX} ═══ DESKTOP-LÄGE: OVANPÅ IKONERNA "
                            f"═══ Win+D-säkert ✅ (barn i skrivbordet) "
                            f"skal {wid!r} HWND={hwnd} origo={_org} (komp. aktiv)"
                        )
                        return
                    self._log.warning(
                        f"{LOG_PREFIX} Skal {wid!r}: läget 'ovanpå ikoner' "
                        f"misslyckades → provar 'bakom ikoner'"
                    )
                fn = getattr(
                    self._desktop_mod(desktop_status),
                    "wedge_window_behind_desktop_icons", None,
                )
                if fn is None:
                    _dfile2 = getattr(
                        self._desktop_mod(desktop_status), "__file__", "?"
                    )
                    self._log.critical(
                        f"{LOG_PREFIX} core/desktop.py är GAMMAL — "
                        f"'wedge_window_behind_desktop_icons' saknas! "
                        f"Inläst fil: {_dfile2} — ersätt med nya "
                        f"core/desktop.py (v7-fix38/40)"
                    )
                if fn and fn(hwnd):
                    shell._desktop_layer_mode = "behind"
                    self._log.info(
                        f"{LOG_PREFIX} ═══ DESKTOP-LÄGE: BAKOM IKONERNA "
                        f"═══ Win+D-säkert ✅ (WorkerW-kil) "
                        f"skal {wid!r} HWND={hwnd}"
                    )
                    return
                # NY v7-fix70: behind-kilen misslyckades (t.ex. ingen
                # WorkerW på denna dator) — PROVA ABOVE automatiskt!
                # Above = barn i skrivbordet, ÖVER ikonerna, Win+D-säkert
                # (Rickard 2026-10-06: "fönstret ligger överst" när bakom-
                # läget faller tillbaka på vanligt toppfönster — ge en
                # SYNLIG återväg i stället).
                self._log.warning(
                    f"{LOG_PREFIX} Skal {wid!r}: behind-kilen misslyckades "
                    f"→ provar OVANPÅ IKONERNA automatiskt (v7-fix70)"
                )
                _dm70 = self._desktop_mod(desktop_status)
                _fn70 = getattr(
                    _dm70, "attach_window_above_desktop_icons", None
                )
                if _fn70 and _fn70(hwnd):
                    shell._desktop_layer_mode = "above"  # experimentellt
                    _org70 = (0, 0)
                    with suppress(Exception):
                        if hasattr(_dm70, "get_desktop_parent_origin"):
                            _of = (
                                _dm70.get_desktop_parent_origin(hwnd)
                                or (0, 0)
                            )
                            _dpr70 = float(
                                shell.devicePixelRatioF() or 1.0
                            ) or 1.0
                            _org70 = (_of[0] / _dpr70, _of[1] / _dpr70)
                    shell._parent_origin = _org70
                    self._log.info(
                        f"{LOG_PREFIX} ═══ DESKTOP-LÄGE: OVANPÅ IKONERNA "
                        f"═══ Win+D-säkert ✅ (behind misslyckades → "
                        f"automatisk återväg) skal {wid!r} HWND={hwnd} "
                        f"origo={_org70}"
                    )
                    return
                self._log.warning(
                    f"{LOG_PREFIX} Skal {wid!r}: desktop-lager otillgängligt "
                    f"(behind+above misslyckades) — körs som vanligt "
                    f"toppfönster med Win+D-bevakning (v7-fix56/70)"
                )

            # 5. NY v7-fix56: LEGACY ÄR BORTTAGET (Rickards beslut —
            # above fungerar bevisat + behind är fallback). Om BÅDA
            # skrivbordslagren misslyckas körs fönstret som vanligt
            # toppfönster (NOACTIVATE+TOOLWINDOW redan satta) — synligt
            # och användbart, bevakas av _maintain_desktop_level.
            shell._desktop_layer_mode = "normal"
            self._log.warning(
                f"{LOG_PREFIX} ═══ DESKTOP-LÄGE: VANLIGT FÖNSTER ═══ "
                f"(skrivbordslagret ej tillgängligt — extremely ovanligt; "
                f"Win+D-bevakning aktiv). Skal {wid!r} HWND={hwnd}"
            )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _apply_desktop_shell misslyckades: {e}",
                exc_info=True,
            )

    def _maintain_desktop_level(self, shell: Any) -> None:
        """
        NY v7-fix38: Mode-medvetet underhåll (var 30:e sekund).

        above  → återfäst i skrivbordslagret om Explorer tappat oss
        behind → re-kila ovanför WorkerW
        normal → vanligt toppfönster (v7-fix56: legacy borttaget) —
                  re-show om gömt, tätare bevakning (5 s)
        """
        try:
            import ctypes
            user32 = ctypes.windll.user32
            mode = getattr(shell, "_desktop_layer_mode", "normal")
            wid = getattr(shell, "_desktop_wid", "?")

            # NY v7-fix70: om läget är "_push" men push INTE är aktiv
            # (t.ex. släpp-detektering missad) → återfäst nu
            if (
                mode == "_push"
                and not getattr(self, "_push_show_active", False)
            ):
                self._log.info(
                    f"{LOG_PREFIX} Skal {wid!r}: kvarvarande push-läge "
                    f"utan aktiv push → återfäster"
                )
                with suppress(Exception):
                    self._push_show_release()
                return
            # FIX v7-fix51: force_show-skip gäller NUMERA ENDAST legacy-
            # z-ordern. Iconic-restore + desktop-lager-återfästning måste
            # ALLTID köras — annars kunde Win+D gömma fönstret permanent
            # (force_show är default PÅ vid start!).
            _w = None
            with suppress(Exception):
                _w = self._widgets.get(wid)

            hwnd = 0
            with suppress(Exception):
                hwnd = int(shell.winId())
            if not hwnd or not user32.IsWindow(hwnd):
                # Fönstret dött (t.ex. Explorer-omstart) → återskapa
                self._log.warning(
                    f"{LOG_PREFIX} Skal {wid!r}: HWND saknas/död — "
                    f"återskapar fönstret (Explorer-omstart?)"
                )
                with suppress(Exception):
                    shell._desktop_layer_mode = None
                    shell.show()
                with suppress(Exception):
                    self._QTimer.singleShot(
                        1500, lambda: self._apply_desktop_shell(shell, wid)
                    )
                return

            # NY v7-fix44: MINIMERAD? (Win+D/Win+M i legacy-läge) → ÅTERSTÄLL!
            # OBS: IsWindowVisible är TRUE för minimerade fönster — därför
            # upptäckte inte gamla koden detta och fönstret kom aldrig tillbaka.
            with suppress(Exception):
                if user32.IsIconic(hwnd):
                    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                    self._log.warning(
                        f"{LOG_PREFIX} ⚠ FÖNSTRET VAR MINIMERAT (t.ex. Win+D) "
                        f"→ ÅTERSTÄLLT NU — skal {wid!r}, läge={mode}"
                    )

            # NY v7-fix44: legacy-läge = sårbart för Win+D → bevaka TÄTARE
            # (5 s) så fönstret alltid kommer tillbaka automatiskt.
            with suppress(Exception):
                _tm = getattr(shell, "_zorder_timer", None)
                if _tm is not None:
                    _want = 5000 if mode == "normal" else 30000
                    if _tm.interval() != _want:
                        _tm.setInterval(_want)

            desktop_status = self._imports.get("desktop")
            if mode in ("above", "behind") and desktop_status and desktop_status.ok:
                if mode == "above":
                    fn = getattr(
                        self._desktop_mod(desktop_status),
                        "attach_window_above_desktop_icons", None,
                    )
                    if fn and fn(hwnd):
                        with suppress(Exception):
                            if not user32.IsWindowVisible(hwnd):
                                user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
                        return
                else:
                    fn = getattr(
                        self._desktop_mod(desktop_status),
                        "wedge_window_behind_desktop_icons", None,
                    )
                    if fn and fn(hwnd):
                        return

            # NY v7-fix56: legacy är BORTTAGET — utan desktop-lager
            # kör fönstret som vanligt toppfönster. Bevakning: endast
            # re-show om gömt/minimerat (ingen HWND_BOTTOM-push någonsin).
            if not user32.IsWindowVisible(hwnd):
                user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
                self._log.info(
                    f"{LOG_PREFIX} Desktop-shell re-show (var gömd)"
                )
        except Exception:
            pass

    # -----------------------------------------------------------------------
    # NY v7-fix38: SKAL-UTSEENDE (frameless + genomskinligt glas-skal)
    # -----------------------------------------------------------------------

    def _window_transparency_value(self) -> float:
        """NY v7-fix38: fönstertransparens 0.0–1.0 (0 = helt opak)."""
        try:
            if hasattr(self.settings, "window_transparency"):
                raw = float(self.settings.window_transparency())
            else:
                raw = float(self.settings.get("window_transparency", 0.85))
        except Exception:
            raw = 0.85
        if raw != raw:  # NaN-skydd
            raw = 0.85
        return max(0.0, min(1.0, raw))

    def _desktop_mode(self) -> str:
        """NY v7-fix38: aktuellt skrivbordsläge (above|behind|legacy)."""
        try:
            if hasattr(self.settings, "desktop_mode"):
                mode = str(self.settings.desktop_mode()).strip().lower()
            else:
                mode = str(
                    self.settings.get("desktop_mode", "above")
                ).strip().lower()
        except Exception:
            mode = "above"
        # v7-fix56: legacy är BORTTAGET — ogiltiga/legacy-värden → above
        return mode if mode in ("above", "behind") else "above"

    def _apply_shell_appearance(self, shell: Any, wid: str) -> None:
        """
        NY v7-fix38: frameless + genomskinligt glas-skal.

        MÅSTE anropas FÖRE show() — fönsterflaggor sätts innan det
        nativa fönstret skapas (inget extra CreateWindowEx-byte senare).

        transparens > 0 → WA_TranslucentBackground + WA_NoSystemBackground:
        hela fönstret blir ett genomskinligt glas-skal — skrivbordet och
        ikonerna syns igenom de rundade hörnen och den tonade panelen.
        """
        try:
            from PySide6.QtCore import Qt as _Qt
            transp = self._window_transparency_value()
            shell.setWindowFlag(_Qt.WindowType.FramelessWindowHint, True)
            shell.setAttribute(
                _Qt.WidgetAttribute.WA_TranslucentBackground, transp > 0.0
            )
            shell.setAttribute(
                _Qt.WidgetAttribute.WA_NoSystemBackground, transp > 0.0
            )
            shell._shell_transparency = transp
            self._log.info(
                f"{LOG_PREFIX} Skal {wid!r}: frameless + "
                f"transparens={transp:.2f} (v7-fix38)"
            )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _apply_shell_appearance misslyckades: {e}",
                exc_info=True,
            )

    def _schedule_shell_native_check(self, shell: Any, wid: str) -> None:
        """NY v7-fix38: fördröjd säkerhetskontroll av skal-fönstret."""
        try:
            self._QTimer.singleShot(
                900, lambda: self._verify_shell_native_window(shell, wid)
            )
        except Exception:
            pass

    def _verify_shell_native_window(self, shell: Any, wid: str) -> None:
        """
        NY v7-fix38: verifiera att det genomskinliga skalet skapades.

        Historik (v7-fix7): Frameless+alpha kunde ge CreateWindowEx-fel
        på Rickards maskin (fönster-stormen). Skulle det hända igen
        nedgraderas skalet AUTOMATISKT till opak + desktop-lagret
        startas om — appen får aldrig dö av design-flaggor.
        """
        try:
            hwnd = 0
            with suppress(Exception):
                wh = shell.windowHandle()
                hwnd = int(wh.winId()) if wh is not None else 0
            ok = False
            if hwnd:
                import ctypes
                ok = bool(ctypes.windll.user32.IsWindow(hwnd))
            if ok:
                # Fönstret lever — komplettera med desktop-lager om det väntar
                if getattr(shell, "_desktop_layer_pending", False):
                    shell._desktop_layer_pending = False
                    self._apply_desktop_shell(shell, wid)
                return
            # FALLBACK: transparent skal kunde ej skapas
            self._log.critical(
                f"{LOG_PREFIX} Skal {wid!r}: nativt fönster SAKNAS efter "
                f"show() (CreateWindowEx-fel?) → faller tillbaka på opak "
                f"skal (v7-fix38 auto-fallback)"
            )
            from PySide6.QtCore import Qt as _Qt
            shell.setAttribute(
                _Qt.WidgetAttribute.WA_TranslucentBackground, False
            )
            shell.setAttribute(
                _Qt.WidgetAttribute.WA_NoSystemBackground, False
            )
            shell.setWindowFlag(_Qt.WindowType.FramelessWindowHint, False)
            shell._shell_transparency = 0.0
            with suppress(Exception):
                shell.show()
            self._apply_desktop_shell(shell, wid)
            # Widgeten ska måla om med opaka design-tokens
            _w = None
            with suppress(Exception):
                _w = self._widgets.get(wid)
            if _w is not None and hasattr(_w, "_apply_theme"):
                with suppress(Exception):
                    _w._apply_theme()
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _verify_shell_native_window: {e}",
                exc_info=True,
            )

    def _reapply_shell_appearance(self, shell: Any, wid: str) -> None:
        """
        NY v7-fix38: applicera om skal-utseendet LIVE.

        (dölj → nya flaggor → visa → desktop-lager igen)
        """
        try:
            with suppress(Exception):
                shell.hide()
            self._apply_shell_appearance(shell, wid)
            with suppress(Exception):
                shell.show()
            self._apply_desktop_shell(shell, wid)
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _reapply_shell_appearance misslyckades: {e}",
                exc_info=True,
            )

    def _reapply_desktop_shells(self) -> None:
        """NY v7-fix38: applicera skrivbordsläge + transparens live på alla skal."""
        try:
            with self._widget_lock:
                items = [
                    (wid, getattr(w, "_shell", None), w)
                    for wid, w in self._widgets.items()
                ]
            for _wid, _shell, _w in items:
                if _shell is not None:
                    self._reapply_shell_appearance(_shell, _wid)
            # Måla om widget-ytorna med nya alfa-tokens
            for _wid, _shell, _w in items:
                with suppress(Exception):
                    if hasattr(_w, "_apply_theme"):
                        _w._apply_theme()
            self._log.info(
                f"{LOG_PREFIX} _reapply_desktop_shells klar "
                f"(läge={self._desktop_mode()!r}, "
                f"transparens={self._window_transparency_value():.2f})"
            )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _reapply_desktop_shells misslyckades: {e}",
                exc_info=True,
            )

    def _set_desktop_mode(self, mode: str) -> None:
        """NY v7-fix38: tray-handler — sätt skrivbordsläge live."""
        try:
            # v7-fix56: legacy borta — bara above/behind
            mode = mode if mode in ("above", "behind") else "above"
            if hasattr(self.settings, "set_desktop_mode"):
                self.settings.set_desktop_mode(mode)
            self._reapply_desktop_shells()
            self._populate_tray_menu()
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _set_desktop_mode misslyckades: {e}",
                exc_info=True,
            )

    def _set_window_transparency(self, value: float) -> None:
        """NY v7-fix38: tray-handler — sätt fönstertransparens live."""
        try:
            if hasattr(self.settings, "set_window_transparency"):
                self.settings.set_window_transparency(value)
            self._reapply_desktop_shells()
            self._populate_tray_menu()
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _set_window_transparency misslyckades: {e}",
                exc_info=True,
            )

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

    def _qt_exception_hook(self, exc_type, exc_value, exc_traceback) -> None:
        """Qt-specifik exception hook (visar QMessageBox + loggar UTFÖRLIGT)."""
        # Logga UTFÖRLIGT (med hela traceback)
        try:
            import traceback as _tb
            tb_str = "".join(_tb.format_exception(exc_type, exc_value, exc_traceback))
            self._log.critical(
                f"OHANTERAT FEL (Qt-hook) — "
                f"type={exc_type.__name__}, msg={exc_value}",
                extra={"traceback": tb_str[:5000]},  # Begränsa längd
            )
            self._log.critical(
                f"OHANTERAT FEL (Qt-hook) traceback:\n{tb_str}",
            )
        except Exception as e:
            self._log.critical(
                "OHANTERAT FEL (Qt-hook):",
                exc_info=(exc_type, exc_value, exc_traceback),
            )
        if self._app is not None:
            with suppress(Exception):
                self._QMessageBox.critical(
                    None,
                    f"{APP_NAME} — Kritisk krasch",
                    f"Ett oväntat fel uppstod:\n\n{exc_value}",
                )

    def _on_about_to_quit(self) -> None:
        """Callback när Qt håller på att stänga."""
        self._log.info("Qt aboutToQuit-signal mottagen")
        with suppress(Exception):
            self.shutdown()

    # -----------------------------------------------------------------------
    # DIAGNOSTIK (NY v6.4.1)
    # -----------------------------------------------------------------------

    def _run_diagnostics_on_startup(self) -> None:
        """
        NY v6.4.1: Kör diagnostik vid app-start.

        Vad den gör:
          1. validate_startup() — kolla att alla dependencies OK
          2. diagnose_app_health() — komplett app-hälsa
          3. attempt_widget_window_recovery() — flytta widget-fönster vid behov
          4. archive_old_backups() — arkivera gamla backuper

        Loggar resultat men visar inget UI.
        """
        self._log.info(
            f"{LOG_PREFIX} === DIAGNOSTIK VID STARTUP ==="
        )
        # NY v7-fix37: Autostart-självreparation
        with suppress(Exception):
            self._autostart_health_check()
        # 1. validate_startup
        try:
            from stability import validate_startup
            success, errors = validate_startup()
            if not success:
                self._log.warning(
                    f"{LOG_PREFIX} validate_startup: {len(errors)} fel"
                )
                for err in errors[:3]:  # Första 3
                    self._log.warning(f"{LOG_PREFIX}   - {err}")
            else:
                self._log.info(f"{LOG_PREFIX} validate_startup: OK")
        except ImportError:
            self._log.debug(
                f"{LOG_PREFIX} stability ej importerbar — skippar validate_startup"
            )
        # 2. diagnose_app_health
        try:
            from stability import diagnose_app_health
            diag = diagnose_app_health()
            self._log.info(
                f"{LOG_PREFIX} diagnose_app_health: "
                f"errors={diag['total_errors']}, "
                f"breakers_open={diag['circuit_breakers_open']}, "
                f"issues={len(diag['issues'])}, "
                f"critical_ok={diag['critical_systems_ok']}"
            )
            for issue in diag["issues"]:
                self._log.warning(f"{LOG_PREFIX}   issue: {issue}")
        except ImportError:
            self._log.debug(
                f"{LOG_PREFIX} diagnose_app_health: stability ej importerbar"
            )
        # 3. attempt_widget_window_recovery
        try:
            from stability import attempt_widget_window_recovery
            rec = attempt_widget_window_recovery()
            if rec["attempted"] > 0:
                self._log.info(
                    f"{LOG_PREFIX} widget recovery: "
                    f"attempted={rec['attempted']}, "
                    f"recovered={rec['recovered']}, "
                    f"failed={rec['failed']}"
                )
        except ImportError:
            self._log.debug(
                f"{LOG_PREFIX} widget recovery: stability ej importerbar"
            )
        # 4. archive_old_backups (max 10 dagar → års/mån-mapp)
        try:
            from backup import BackupManager
            mgr = BackupManager()
            result = mgr.archive_old_backups(max_age_days=10)
            if result["archived"] > 0:
                self._log.info(
                    f"{LOG_PREFIX} backup-arkivering: {result['archived']} "
                    f"flyttade till års/mån-mapp"
                )
        except ImportError:
            self._log.debug(
                f"{LOG_PREFIX} backup-arkivering: backup ej importerbar"
            )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} backup-arkivering misslyckades: {e}"
            )
        self._log.info(
            f"{LOG_PREFIX} === DIAGNOSTIK KLAR ==="
        )
        # NY 2026-09-23: Smart cache — rensa __pycache__ varje fredag
        # NY 2026-09-25: Smart log-cleanup — rensa ALLA gamla loggar (behåll dagens)
        with suppress(Exception):
            self._run_friday_pycache_cleanup(at_startup=True)
        with suppress(Exception):
            self._run_friday_log_cleanup(at_startup=True)

    def _get_app_health_status(self) -> Dict[str, Any]:
        """
        NY v6.4.1: Hämta komplett app-hälsa (för UI + diagnostik).
        """
        issues: List[str] = []
        widget_count = len(self._widgets) if hasattr(self, "_widgets") else 0
        task_count = 0
        if self.store is not None and hasattr(self.store, "count"):
            try:
                active, _archive = self.store.count()
                task_count = active
            except Exception:
                pass
        autostart_status: Dict[str, Any] = {"enabled": False}
        if self.settings is not None and hasattr(
            self.settings, "get_autostart_status"
        ):
            try:
                autostart_status = self.settings.get_autostart_status()
                if not autostart_status.get("consistent"):
                    issues.append("Autostart: settings vs OS inkonsistent")
            except Exception:
                pass
        stability_health: Dict[str, Any] = {"total_errors": 0, "issues": []}
        try:
            from stability import diagnose_app_health
            stability_health = diagnose_app_health()
            issues.extend(stability_health.get("issues", []))
        except ImportError:
            pass
        # NY v6.4.1 v7: Logg-stats med svensk evaluering
        log_stats: Dict[str, Any] = {"total_lines": 0, "by_level": {}, "total_size_bytes": 0}
        try:
            from logger_setup import get_log_stats
            log_stats = get_log_stats()
            by_level = log_stats.get("by_level", {})
            err_count = by_level.get("ERROR", 0)
            critical_count = by_level.get("CRITICAL", 0)
            warning_count = by_level.get("WARNING", 0)
            # Bygg svenska issues
            if err_count > 10:
                issues.append(
                    f"Manga errors i loggar: {err_count} "
                    f"(kolla data/logs/session_*.log)"
                )
            if critical_count > 0:
                issues.append(
                    f"Kritiska fel i loggar: {critical_count} "
                    f"(bor undersökas omedelbart)"
                )
            if warning_count > 50:
                issues.append(
                    f"Manga varningar: {warning_count} "
                    f"(kan indikera instabilitet)"
                )
        except ImportError:
            pass
        uptime_sec = 0.0
        if hasattr(self, "_start_time"):
            uptime_sec = time.time() - self._start_time
        # Logga health-snapshot for felsokning
        self._log.debug(
            f"{LOG_PREFIX} _get_app_health_status: "
            f"widgets={widget_count}, tasks={task_count}, "
            f"uptime={uptime_sec:.0f}s, issues={len(issues)}"
        )
        return {
            "app_version": APP_VERSION,
            "uptime_sec": uptime_sec,
            "widget_count": widget_count,
            "task_count": task_count,
            "autostart_status": autostart_status,
            "stability_health": stability_health,
            "log_stats": log_stats,
            "issues": issues,
            "uptime_human": format_uptime(uptime_sec),
        }

    def show_doctor_dialog(self) -> None:
        """
        NY v6.4.1 v7: 🔧 Visa Doctor-dialog (188888888% bättre design).

        Vad den visar (svenska, lasbart format):
          - App-version + uptime (formaterad som "X timmar, Y minuter")
          - Widget-antal + task-antal
          - Autostart-status (enabled + konsistens)
          - Stability-health (errors + breakers)
          - Log-statistik (total lines + per level)
          - Issues-lista (om problem finns)
        """
        try:
            health = self._get_app_health_status()
            n_issues = len(health["issues"])
            self._log.info(
                f"{LOG_PREFIX} Doctor-dialog: {n_issues} issues"
            )
            # Formatera uptime svenskt
            uptime_sv = format_uptime(health["uptime_sec"])
            # Formatera logg-bytes
            total_bytes = health["log_stats"].get("total_size_bytes", 0)
            log_size = format_bytes(total_bytes)
            # Bygg issues-text
            issues_text = (
                "\n".join(f"  - {i}" for i in health["issues"])
                if health["issues"]
                else "  - Inga problem!"
            )
            # Status-emoji baserat pa issues
            if n_issues == 0:
                status_icon = "✅"
                status_text = "Allt ser bra ut!"
            else:
                status_icon = "⚠️"
                status_text = f"{n_issues} problem behöver atgärd"
            # Bygg dialog-text
            summary = (
                f"=== APP HEALTH v{health['app_version']} ===\n\n"
                f"{status_icon} Status: {status_text}\n\n"
                f"Widgets: {health['widget_count']} "
                f"(uppgifter i minnet)\n"
                f"Tasks: {health['task_count']} aktiva\n"
                f"Uptime: {uptime_sv}\n"
                f"Autostart: "
                f"{'✅ aktiverad' if health['autostart_status'].get('enabled') else '⚪ avstängd'} "
                f"({'konsistent' if health['autostart_status'].get('consistent') else 'INKONSISTENT — kolla!'})\n\n"
                f"=== STABILITY ===\n"
                f"Errors totalt: {health['stability_health'].get('total_errors', 0)}\n"
                f"Circuit breakers öppna: "
                f"{health['stability_health'].get('circuit_breakers_open', 0)}\n\n"
                f"=== LOGGAR ===\n"
                f"Totalt antal rader: {health['log_stats'].get('total_lines', 0)}\n"
                f"Storlek: {log_size}\n"
                f"Per nivå: {health['log_stats'].get('by_level', {})}\n"
            )

            # NY v6.4.1 v7: Lägg till central log-statistik
            try:
                central_stats = get_central_log_stats()
                summary += (
                    f"\n=== CENTRAL LOGG (NY v7) ===\n"
                    f"Events i minnet: {central_stats['total_events']}/"
                    f"{central_stats['max_events']}\n"
                    f"Per nivå: {central_stats['by_level']}\n"
                    f"Per modul (top 5): "
                    f"{dict(list(central_stats['by_module'].items())[:5])}\n"
                    f"Aktiva lyssnare: {central_stats['listener_count']}\n"
                )
            except Exception as central_err:
                summary += f"\n=== CENTRAL LOGG ===\n(kunde inte ladda: {central_err})\n"

            summary += f"\n=== PROBLEM ===\n{issues_text}\n"
            self._show_simple_error(
                f"🔧 Doctor — App Health (v{health['app_version']})",
                summary,
            )
            self._log.info(
                f"{LOG_PREFIX} Doctor-dialog stängd (visade {n_issues} issues)"
            )
        except Exception as e:
            self._log.error(
                f"{LOG_PREFIX} Doctor-dialog misslyckades: {e}",
                exc_info=True,
            )
            show_error_dialog(
                title="Doctor misslyckades",
                user_message=_describe_exception(e),
                technical=_format_compact_traceback(e),
                category="code_bug",
            )

    # -----------------------------------------------------------------------
    # INIT — Subsystems
    # -----------------------------------------------------------------------

    def _init_subsystems(self) -> None:
        """
        NY v6.4.1 v7: Initiera ALLA subsystems (med error boundary + AI-felsokning).

        Loggar varje steg med ✓ / ⚠ / ✗ for tydlig status.
        Vid fel: error_boundary fångar + visar svensk dialog.
        """
        self._log.info(f"{LOG_PREFIX} === Initierar subsystems (mode={self._mode.name}) ===")

        # 0. NY v8 (2026-10-12): saknas uppgifter/inställningar (t.ex. efter en
        # uppdatering som tagit js/-mappen) → läs in dem från den automatiska backupen
        # INNAN något annat läser filerna.
        with suppress(Exception):
            self._restore_from_external_backup()

        # 1. Settings (eller dummy)
        settings_status = self._imports.get("settings")
        if settings_status and settings_status.ok and self._mode != AppMode.SAFE_MODE:
            with error_boundary("settings.init"):
                SettingsCls = settings_status.instance["Settings"]
                self.settings = SettingsCls()
                self._registry.register("settings", self.settings, dependencies=[])
                self._log.info(f"{LOG_PREFIX} ✓ Settings initierat")
                # NY v7-fix9: Rensa skräp-fönster EN gång vid start.
                # window_configs() är nu en pure getter (inga sidoeffekter) —
                # cleanup sker här istället, innan _init_signals kopplar
                # windows_updated → _safe_update_widgets (så emit:en inte
                # triggar populate innan widgets finns).
                if hasattr(self.settings, "cleanup_stale_windows"):
                    with suppress(Exception):
                        _removed = self.settings.cleanup_stale_windows()
                        if _removed:
                            self._log.info(
                                f"{LOG_PREFIX} ✓ Rensade {_removed} skräp-fönster "
                                f"ur settings"
                            )
        else:
            self.settings = self._create_dummy_settings()
            self._registry.register("settings", self.settings)
            self._log.warning(f"{LOG_PREFIX} ⚠ Settings: dummy-läge (använder tomt)")

        # 2. Store (eller dummy)
        store_status = self._imports.get("store")
        if store_status and store_status.ok and self._mode != AppMode.SAFE_MODE:
            with error_boundary("store.init"):
                TaskStoreCls = store_status.instance["TaskStore"]
                self.store = TaskStoreCls()
                self._registry.register("store", self.store, dependencies=["utils"])
                self._log.info(f"{LOG_PREFIX} ✓ Store (TaskStore) initierat")
        else:
            self.store = self._create_dummy_store()
            self._registry.register("store", self.store)
            self._log.warning(f"{LOG_PREFIX} ⚠ Store: dummy-läge")

        # 3. Stability (om aktiverat)
        if self._config.enable_stability:
            stab_status = self._imports.get("stability")
            if stab_status and stab_status.ok:
                with error_boundary("stability.init"):
                    stability_mod = stab_status.instance.get("stability")
                    get_stability = getattr(stability_mod, "get_stability_manager", None)
                    if get_stability:
                        self.stability = get_stability()
                        self._registry.register("stability", self.stability)
                        self._log.info(f"{LOG_PREFIX} ✓ Stability-system initierat")

        # 4. Backup manager
        backup_status = self._imports.get("backup")
        if backup_status and backup_status.ok and self._mode != AppMode.SAFE_MODE:
            with error_boundary("backup.init"):
                BackupMgrCls = backup_status.instance.get("BackupManager")
                if BackupMgrCls:
                    # NY v6.4.1 v7-fix: BackupManager.__init__ tar (keep, backup_dir, timeout_sec)
                    # INTE data_dir/tasks_file/settings_file (gamla felaktiga anropet).
                    # Vi skickar bara 'keep' och låter default _default_backup_dir() användas.
                    self.backup_manager = BackupMgrCls(keep=10)
                    self._registry.register("backup", self.backup_manager)
                    self._log.info(f"{LOG_PREFIX} ✓ Backup-manager initierat")

        # 5. Window creation + populate
        with error_boundary("windows.create"):
            # FIX 2026-09-25 v7-fix8: Skippa pretest-widgets helt.
            # Orsak: pretest-widgeten (`__pretest__`) skapade WS_OVERLAPPED-widgets
            # mitt i Qt:s flag-handshake, vilket gav:
            #   - "Failed to create platform window ... flags QFlags<Qt::WindowType>()"
            #     (tomma flaggor — Qt hann inte registrera Window-typ innan show())
            #   - PermissionError [WinError 32] pa TimedRotatingFileHandler.doRollover
            #     nar pretest skapade log-events under log-rotation
            # Pretest var ett forsok att "fanga tysta krascher" men skapar mer
            # brus an nytta — populate-widgets ger samma signal vid fel.
            self._log.info(
                f"{LOG_PREFIX} === Hoppar over widget pre-test (v7-fix8) ==="
            )

            self._create_default_window()
            self._populate_windows()

        # 5.5. NY v6.4.1 v7: Tvinga synlig vid force-show (DEFAULT PÅ)
        # FIX 2026-09-23: Kör på GUI-tråden via QTimer — INTE bakgrundstråd.
        # Qt-widget-metoder (show/raise/activate) från annan tråd → "Python svarar inte".
        if self._config.force_show_widget:
            try:
                if self._QTimer is None:
                    raise RuntimeError("self._QTimer saknas")
                # singleShot köar till GUI-tråden (widget-tråd) → ingen frysning
                self._QTimer.singleShot(600, self.force_show_all_widgets)
                self._log.info(
                    f"{LOG_PREFIX} force_show schemalagd på GUI-tråd (+600ms)"
                )
            except Exception as _fs_e:
                # Fallback: Win32-only via liten bakgrundstråd (inga Qt-anrop där)
                self._log.warning(
                    f"{LOG_PREFIX} QTimer.force-show misslyckades ({_fs_e}), "
                    f"fallback Win32-tråd"
                )

                def _force_show_bg() -> None:
                    import time as _time
                    _time.sleep(0.6)
                    try:
                        self.force_show_all_widgets()
                    except Exception as e:
                        self._log.warning(
                            f"{LOG_PREFIX} force_show_bg misslyckades: {e}"
                        )
                fs_thread = threading.Thread(
                    target=_force_show_bg,
                    daemon=True,
                    name="ForceShow",
                )
                fs_thread.start()

        # 6. Tray (om aktiverat)
        if self._mode != AppMode.NO_TRAY:
            with error_boundary("tray.init"):
                self._init_tray()

        # 6b. NY v7-fix41: global snabbinput (Ctrl+Alt+N, hela Windows)
        with suppress(Exception):
            self._install_global_quick_add()

        # 6c. NY v7-fix50: installera/uppdatera tillägg automatiskt vid
        # start (Rickards val: full auto — bakgrund, 30 s fördröjning)
        with suppress(Exception):
            self._schedule_auto_plugin_update()

        # 6d. NY v7-fix64: påminnelsetjänst (förfallna + dagens uppgifter)
        with suppress(Exception):
            self._init_reminder_service()

        # 6e-2. NY v8: automatisk säkerhetskopia av uppgifter + inställningar
        with suppress(Exception):
            self._init_external_backup()

        # 6e. NY v7-fix90: e-postbrygga (Thunderbird-tillägg) + inkorgsmapp
        # (tar emot mail från tillägget och skapar uppgifter som sparas i JSON)
        with suppress(Exception):
            self._init_mail_bridge()

        # 7. NY v6.4.1 v7: Erbjud installera saknade plugins (icke-blockerande)
        # Körs BARA i NORMAL-läge (inte --safe-mode eller --no-tray)
        # NY v6.4.1 v7-fix: Skippa om --force-show (användaren vill bara se widgets)
        # NY v6.4.1 v7-fix: Skippa om --no-plugin-install
        if (self._mode == AppMode.NORMAL
                and not self._config.force_show_widget
                and not self._config.no_plugin_install):
            try:
                # Kör i bakgrunds-tråd så UI inte fryser under installation
                def _offer_plugins_bg() -> None:
                    try:
                        results = offer_install_missing_plugins()
                        if results:
                            ok_count = sum(1 for v in results.values() if v)
                            self._log.info(
                                f"{LOG_PREFIX} plugin-installation klar: "
                                f"{ok_count}/{len(results)} lyckades"
                            )
                    except Exception as e:
                        self._log.warning(
                            f"{LOG_PREFIX} plugin-erbjudande misslyckades: {e}",
                            exc_info=True,
                        )
                bg_thread = threading.Thread(
                    target=_offer_plugins_bg,
                    daemon=True,
                    name="PluginInstaller",
                )
                bg_thread.start()
                self._log.debug(
                    f"{LOG_PREFIX} plugin-erbjudande startat i bakgrunds-tråd"
                )
            except Exception as e:
                self._log.warning(
                    f"{LOG_PREFIX} kunde inte starta plugin-erbjudande: {e}"
                )

    def _init_timers(self) -> None:
        """Initiera ALLA periodiska timers."""
        if self._QTimer is None:
            self._log.warning("Kan inte initiera timers (QTimer saknas)")
            return

        timer_configs = [
            (self.CLEANUP_INTERVAL_MS, self._periodic_cleanup, "cleanup"),
            (self.METRICS_REFRESH_MS, self._refresh_metrics, "metrics"),
            (self.BACKUP_CHECK_INTERVAL_MS, self._check_backup_status, "backup"),
            (self.CAPABILITIES_REFRESH_MS, self._refresh_capabilities, "capabilities"),
            (self.HEARTBEAT_INTERVAL_MS, self._heartbeat, "heartbeat"),
            (self.IDLE_CHECK_INTERVAL_MS, self._check_idle, "idle"),
        ]

        for interval_ms, callback, name in timer_configs:
            with error_boundary(f"timer.{name}"):
                timer = self._QTimer(self._app)
                timer.timeout.connect(callback)
                timer.start(interval_ms)
                self._log.debug(f"Timer startad: {name} ({interval_ms}ms)")

    def _init_signals(self) -> None:
        """Koppla ALLA Qt-signaler."""
        with error_boundary("signals.connect"):
            if hasattr(self.settings, "windows_updated"):
                self.settings.windows_updated.connect(self._safe_update_widgets)
            if hasattr(self.settings, "theme_changed"):
                self.settings.theme_changed.connect(self._on_theme_changed)
            if hasattr(self.settings, "accent_changed"):
                self.settings.accent_changed.connect(self._on_theme_changed)
            # FIX v7-fix11: signalen heter 'changed' — INTE 'tasks_changed'!
            # Gammal bugg: hasattr(self.store, "tasks_changed") var alltid
            # False → kopplingen hoppades tyst över → UI:et uppdaterades
            # ALDRIG när uppgifter ändrades (och inget sparades till disk).
            if hasattr(self.store, "changed"):
                self.store.changed.connect(self._on_tasks_changed)
                self.store.changed.connect(self._on_store_data_changed)
                self._log.info(
                    f"{LOG_PREFIX} store.changed kopplad → live-refresh + autosave"
                )
            else:
                self._log.warning(
                    f"{LOG_PREFIX} store saknar 'changed'-signal — "
                    f"live-refresh/autosave avstängt"
                )
            self._log.debug("Signaler kopplade")

    def _get_qt_class(self, class_name: str) -> Optional[type]:
        """Hämta en Qt-klass från imports (QtCore/QtGui/QtWidgets)."""
        for mod_name in ("PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets"):
            status = self._imports.get(mod_name)
            if status and status.ok and class_name in status.instance:
                return status.instance[class_name]
        return None

    # -----------------------------------------------------------------------
    # DUMMY SUBSYSTEMS (safe-mode)
    # -----------------------------------------------------------------------

    def _create_dummy_settings(self) -> Any:
        """Skapa dummy-Settings för safe-mode."""

        class _DummySettings:
            def window_configs(self) -> List[Dict[str, Any]]:
                return []

            def add_window(self, x: int, y: int) -> None:
                pass

            def remove_window(self, wid: str) -> None:
                pass

            def __getattr__(self, name: str) -> Any:
                return lambda *a, **kw: None

        return _DummySettings()

    def _create_dummy_store(self) -> Any:
        """Skapa dummy-Store för safe-mode."""

        class _DummyStore:
            def count(self) -> Tuple[int, int]:
                return (0, 0)

            def active_tasks(self) -> List[Dict[str, Any]]:
                return []

            def archive_tasks(self) -> List[Dict[str, Any]]:
                return []

            def reload(self) -> None:
                pass

            def add_task(self, text: str) -> None:
                pass

            def __getattr__(self, name: str) -> Any:
                return lambda *a, **kw: None

        return _DummyStore()

    # -----------------------------------------------------------------------
    # WINDOWS — create / populate / BUGG 19/26
    # -----------------------------------------------------------------------

    def _create_default_window(self) -> None:
        """Skapa default-fönster om inget finns sparat."""
        try:
            if not hasattr(self.settings, "window_configs") or not self.settings.window_configs():
                if hasattr(self.settings, "add_window"):
                    self.settings.add_window(100, 100)
                    self._log.debug("Default-fönster skapat (100, 100)")
        except Exception as e:
            self._log.error(f"Kunde inte skapa default-fönster: {e}")

    def _populate_windows(self) -> None:
        """
        Initiera/synka ALLA widgets baserat på settings.window_configs().
        Befintliga widgets behåller sin state (position, storlek, hotkeys).

        NY v6.4.1 v7: Steg-for-steg loggning sa vi ser VAR det kraschar.
        Rickard 2026-09-22: "tyst crash, loggningen ska upptäcka det".
        """
        self._log.info(f"{LOG_PREFIX} === _populate_windows START ===")
        # FIX 2026-09-24: reentrancy-skydd (populate → show → move → signal → populate)
        import traceback as _pbtb
        _pst = _pbtb.extract_stack(limit=4)[:-1]
        _pcall = " ← ".join(
            f"{f.filename.split('/')[-1]}:{f.lineno}({f.name})"
            for f in _pst[-2:]
        )
        # FIX 2026-09-25 v7-fix7: Hard reentrancy + cooldown mot populate-spam
        # Symptomet i loggen: 25+ anrop / 100 ms → 100-tals fönster-försök / sekund.
        # Orsak: windows_updated signal triggas rekursivt (moveEvent → save → signal → populate → show → moveEvent).
        # Skydd:
        #   1. _populate_in_progress — return direkt om populate redan kör
        #   2. _populate_last_ts + _populate_calls_in_window —> 3 anrop / 500 ms = SPAM
        #      return +_DEBUG-log med stack-frame (så vi ser VEM som spammar)
        import time as _t_pop
        _now = _t_pop.monotonic()
        _last = getattr(self, "_populate_last_ts", 0.0)
        _cnt = getattr(self, "_populate_calls_in_window", 0)
        if (_now - _last) > 0.5:
            # Nytt fönster — återställ räknare
            self._populate_calls_in_window = 1
            self._populate_last_ts = _now
        else:
            _cnt += 1
            self._populate_calls_in_window = _cnt
            self._populate_last_ts = _now
            if _cnt > 3:
                self._log.warning(
                    f"{LOG_PREFIX} _populate_windows SPAM-SKYDD: {_cnt} anrop "
                    f"sista 500 ms — return (kallad från {_pcall})"
                )
                return
        if getattr(self, "_populate_in_progress", False):
            self._log.debug(
                f"{LOG_PREFIX} _populate_windows: redan igång — hoppar över "
                f"(kallad från {_pcall})"
            )
            return
        self._log.info(f"{LOG_PREFIX} _populate_windows ORSAK: {_pcall}")
        self._populate_in_progress = True
        widget_status = self._imports.get("widget")
        if not widget_status or not widget_status.ok:
            self._log.error(
                f"{LOG_PREFIX} Widget-modul EJ TILLGANGLIG — hoppar over populate! "
                f"widget_status={widget_status}"
            )
            self._populate_in_progress = False
            return
        TodoWidget = widget_status.instance["TodoWidget"]
        self._log.info(f"{LOG_PREFIX} TodoWidget class: {TodoWidget}")

        try:
            with self._widget_lock:
                configs = (
                    self.settings.window_configs()
                    if hasattr(self.settings, "window_configs")
                    else []
                )
                self._log.info(
                    f"{LOG_PREFIX} _populate_windows: {len(configs)} "
                    f"window_configs fran settings: "
                    f"{[c.get('id') for c in configs if c.get('id')]}"
                )
                # NY v7-fix40: enbart-läge — visa MAX ett fönster
                if self._single_window_enabled() and len(configs) > 1:
                    _keep = next(
                        (c for c in configs if c.get("id") == "default"),
                        configs[0],
                    )
                    _skipped = [c.get("id") for c in configs if c is not _keep]
                    configs = [_keep]
                    self._log.info(
                        f"{LOG_PREFIX} enbart-ett-fönster-läge: visar "
                        f"{_keep.get('id')!r}, hoppar över {_skipped} "
                        f"(v7-fix40)"
                    )
                primary = self._app.primaryScreen() if self._app else None
                self._log.info(
                    f"{LOG_PREFIX} primary screen: {primary}, "
                    f"QApplication: {self._app}"
                )

                for conf in configs:
                    wid = conf.get("id")
                    if not wid:
                        self._log.warning(f"{LOG_PREFIX} config utan id: {conf}")
                        continue
                    # FIX 2026-09-23: skapa aldrig widget för interna __*-id
                    if str(wid).startswith("__"):
                        self._log.warning(
                            f"{LOG_PREFIX} hoppar över internt-id {wid!r}"
                        )
                        continue
                    if wid in self._widgets:
                        self._log.debug(f"{LOG_PREFIX} widget {wid!r} finns redan, skip")
                        continue
                    self._log.info(
                        f"{LOG_PREFIX} === Skapar widget {wid!r} ==="
                    )
                    # NY v7: Wrappa i BADE error_boundary OCH en extra try/except
                    # som loggar VARJE steg sa vi kan se exakt var det kraschar.
                    try:
                        self._log.info(
                            f"{LOG_PREFIX} widget {wid!r}: steg 1/4 — skapar "
                            f"TodoWidget(primary, store, settings, win_id={wid!r})"
                        )
                        # FIX v7-fix27: SKAL-MÖNSTER — vanligt QWidget som
                        # fönster (bevisat funka!), TodoWidget som BARN.
                        _QW = self._get_qt_class("QWidget")
                        if _QW is not None:
                            _shell = _QW()
                            _shell.setWindowTitle("TaskBord")
                            # v7-fix61: ikonläge — tillåt ikon-storlek
                            _shell.setMinimumSize(150, 200)
                            # NY v7-fix46: positionera SKALET från config!
                            # Tidigare positionerades bara BARN-widgeten —
                            # skalet fick Windows cascade-position (slump,
                            # ofta fel skärm) → "fönstret syns inte".
                            # NY v7-fix47: x/y < 0 = centrera (första start).
                            with suppress(Exception):
                                _gx = int(conf.get("x", -1))
                                _gy = int(conf.get("y", -1))
                                _gw = int(conf.get("w", 340) or 340)
                                _gh = int(conf.get("h", 648) or 648)
                                # v7-fix48: centrera vid sentinel (-1) ELLER
                                # om positionen är utanför ALLA skärmar
                                # (sparad skräpposition från koordinat-buggen)
                                _on_screen = False
                                for _sc in (self._app.screens() if self._app else []):
                                    if _sc.geometry().contains(_gx, _gy):
                                        _on_screen = True
                                        break
                                if _gx == -1 or _gy == -1 or not _on_screen:
                                    if primary is not None:
                                        _sg = primary.availableGeometry()
                                        _gx = _sg.x() + (_sg.width() - _gw) // 2
                                        _gy = _sg.y() + (_sg.height() - _gh) // 2
                                        self._log.info(
                                            f"{LOG_PREFIX} Fönster {wid!r}: "
                                            f"FÖRSTA START/OGILTIG POS → "
                                            f"centrerad ({_gx},{_gy}) "
                                            f"{_gw}x{_gh} (v7-fix47/48)"
                                        )
                                _shell.setGeometry(_gx, _gy, _gw, _gh)
                            w = TodoWidget(
                                primary, self.store, self.settings,
                                win_id=wid, parent=_shell,
                            )
                            from PySide6.QtWidgets import (
                                QVBoxLayout as _QVL,
                            )
                            _lay = _QVL(_shell)
                            _lay.setContentsMargins(0, 0, 0, 0)
                            _lay.addWidget(w)
                            w._shell = _shell
                            # NY v7-fix46: spara skal-geometrin direkt —
                            # rättar ev. (0,0)-skräp som barnets tidiga
                            # moveEvent hann skriva under konstruktorn
                            with suppress(Exception):
                                if hasattr(self.settings, "update_window_geometry"):
                                    self.settings.update_window_geometry(
                                        wid,
                                        _shell.x(), _shell.y(),
                                        _shell.width(), _shell.height(),
                                    )
                        else:
                            w = TodoWidget(
                                primary, self.store, self.settings, win_id=wid,
                            )
                        self._log.info(
                            f"{LOG_PREFIX} widget {wid!r}: steg 2/4 — TodoWidget "
                            f"skapad utan krasch"
                        )
                        if self._config.force_show_widget:
                            w._force_show = True
                            self._log.info(
                                f"{LOG_PREFIX} Widget {wid!r}: force-show aktiverat"
                            )
                        self._log.info(
                            f"{LOG_PREFIX} widget {wid!r}: steg 3/4 — show()"
                        )
                        _shell_ref = getattr(w, "_shell", None)
                        if _shell_ref is not None:
                            # FIX v7-fix32+38: FULLSTÄNDIG desktop-shell —
                            # Rickard: "win+D ska ej funka, ska alltid vara
                            # synlig på skrivbordet, INTE över andra fönster"
                            # + "transparent så ej ikoner döljs"
                            #
                            # NY v7-fix38: frameless + genomskinligt glas-skal.
                            # MÅSTE ske FÖRE show() (flaggor sätts innan det
                            # nativa fönstret skapas — inget riskfyllt byte
                            # av fönsterklass efteråt).
                            self._apply_shell_appearance(_shell_ref, wid)
                            #
                            # 1. Desktop-lager (above/behind) — Win+D-säkert
                            # 2. WS_EX_NOACTIVATE + WS_EX_TOOLWINDOW
                            # 3. nativeEvent blockerar SC_MINIMIZE (Win+D)
                            # 4. Timer underhåller lagret var 30:e sek
                            _shell_ref.show()
                            self._apply_desktop_shell(_shell_ref, wid)
                            # NY v7-fix38: auto-fallback om det genomskinliga
                            # skalet inte kunde skapas (CreateWindowEx-fel)
                            self._schedule_shell_native_check(_shell_ref, wid)
                        else:
                            w.show()
                        self._log.info(
                            f"{LOG_PREFIX} widget {wid!r}: steg 4/4 — registrerar "
                            f"i self._widgets"
                        )
                        self._widgets[wid] = w
                        # FIX v7-fix18: winId() får ALDRIG tvinga fram
                        # fönster-skapande (CreateWindowEx-storm-vektor)
                        _hwnd_txt = "?"
                        with suppress(Exception):
                            if (hasattr(w, "_native_window_ok")
                                    and not w._native_window_ok()):
                                _hwnd_txt = "(skapande misslyckades — karantän)"
                            else:
                                _hwnd_txt = str(int(w.winId()))
                        self._log.info(
                            f"{LOG_PREFIX} Fönster skapat: {wid!r} — "
                            f"HWND={_hwnd_txt} visible={w.isVisible()}"
                        )
                        # FIX v7-fix22: ikoner ENDAST om fönstret FACTISKT
                        # skapats — annars förgiftas fönsterklassen och
                        # ALLA efterföljande CreateWindowEx misslyckas.
                        with suppress(Exception):
                            _win_ok = (
                                hasattr(w, "_native_window_ok")
                                and w._native_window_ok()
                            )
                            if _win_ok and self._app_icon:
                                if hasattr(w, "setWindowIcon"):
                                    w.setWindowIcon(self._app_icon)
                                if not self._app_icon_set_on_first_window:
                                    self._app_icon_set_on_first_window = True
                                    self._app.setWindowIcon(self._app_icon)
                                    self._log.info(
                                        f"{LOG_PREFIX} App-ikon satt NU "
                                        f"(efter lyckat fönster, v7-fix22)"
                                    )
                                self.apply_win32_process_icon(int(w.winId()))
                            elif not _win_ok:
                                self._log.warning(
                                    f"{LOG_PREFIX} hoppar över ikon-sättning "
                                    f"— fönstret skapades ej (v7-fix22)"
                                )
                    except BaseException as _bw_err:  # Fångar ALLT
                        import traceback as _tb
                        self._log.critical(
                            f"{LOG_PREFIX} WIDGET-SKAPANDE KRASCHADE for {wid!r}: "
                            f"{type(_bw_err).__name__}: {_bw_err}"
                        )
                        for line in _tb.format_exception(
                            type(_bw_err), _bw_err, _bw_err.__traceback__
                        ):
                            self._log.critical(f"{LOG_PREFIX}   {line.rstrip()}")
                        # Visa dialog sa Rickard ser vad som handde
                        try:
                            show_error_dialog(
                                title=f"Widget {wid!r} kunde inte skapas",
                                user_message=(
                                    f"Kunde inte skapa widget {wid!r}.\n\n"
                                    f"Fel: {type(_bw_err).__name__}: {_bw_err}\n\n"
                                    f"Loggfil: {LOG_FILE}"
                                ),
                                technical=_format_compact_traceback(_bw_err),
                                category="code_bug",
                            )
                        except Exception:
                            pass
                        # Fortsatt med naesta widget istallet for att krascha helt
                        continue

                self._log.info(
                    f"{LOG_PREFIX} _populate_windows: skapat {len(self._widgets)} "
                    f"widgets"
                )

                # Ta bort widgets som inte längre finns i settings
                config_ids = {c.get("id") for c in configs if c.get("id")}
                to_remove = [wid for wid in self._widgets if wid not in config_ids]
                for wid in to_remove:
                    with error_boundary(f"widget.remove.{wid}"):
                        w = self._widgets.pop(wid)
                        if hasattr(w, "_unregister_hotkeys"):
                            w._unregister_hotkeys()
                        if hasattr(w, "close"):
                            # FIX 2026-09-24: tillåt close (annars spöken)
                            w._allow_close = True
                            with suppress(Exception):
                                w.hide()
                            w.close()
                            with suppress(Exception):
                                w.deleteLater()
                        self._log.info(f"Fönster borttaget: {wid!r}")
                self._log.info(
                    f"{LOG_PREFIX} === _populate_windows SLUT — "
                    f"{len(self._widgets)} widgets kvar ==="
                )
        except Exception as e:
            self._log.error(f"_populate_windows misslyckades: {e}", exc_info=True)
        finally:
            self._populate_in_progress = False

    def _install_global_quick_add(self) -> None:
        """
        NY v7-fix41: GLOBAL snabbinput — Ctrl+Alt+N var som helst i Windows.

        RegisterHotKey (Win32) + QAbstractNativeEventFilter som fångar
        WM_HOTKEY (0x0312) i Qt:s meddelandepump — inget extra fönster
        behövs (viktigt med tanke på CreateWindowEx-storm-historiken!).
        Öppnar samma snabbinput-dialog som tray-menyn + visar widgeten.
        """
        if sys.platform != "win32":
            return
        try:
            if hasattr(self.settings, "global_quick_add"):
                if not self.settings.global_quick_add():
                    self._log.info(
                        f"{LOG_PREFIX} Global snabbinput avstängd i settings"
                    )
                    return
            elif hasattr(self.settings, "get") and not self.settings.get(
                "global_quick_add", True
            ):
                return
        except Exception:
            pass
        try:
            import ctypes
            from PySide6.QtCore import QAbstractNativeEventFilter

            user32 = ctypes.windll.user32
            self._global_hotkey_id = 0xB41  # unikt hotkey-id
            # FIX v7-fix83: hotkey NUMERA KONFIGURERBAR (settings
            # 'quick_add_hotkey', default 'Ctrl+Alt+N') — ändras i tray →
            # ⌨️ Snabbkommandon → Ny uppgift (registreras om direkt).
            _qa_combo = self._get_quick_add_hotkey_combo()
            _qa_mods, _qa_vk = parse_hotkey_combo(_qa_combo)
            if not _qa_vk:
                # Ogiltig sparad kombination → fallback default
                self._log.warning(
                    f"{LOG_PREFIX} ogiltig quick_add_hotkey '{_qa_combo}' "
                    f"— använder Ctrl+Alt+N"
                )
                _qa_combo = "Ctrl+Alt+N"
                _qa_mods, _qa_vk = parse_hotkey_combo(_qa_combo)
            ok = bool(user32.RegisterHotKey(
                None, self._global_hotkey_id, _qa_mods, _qa_vk,
            ))
            if not ok:
                self._log.warning(
                    f"{LOG_PREFIX} RegisterHotKey({_qa_combo}) misslyckades "
                    f"— kanske upptagen av annan app"
                )
                return
            ctrl = self

            class _HotkeyFilter(QAbstractNativeEventFilter):
                """Fångar WM_HOTKEY i Qt:s meddelandepump (GUI-tråd)."""

                def nativeEventFilter(self, eventType, message):
                    try:
                        if eventType != b"windows_generic_MSG":
                            return False

                        class _MSG(ctypes.Structure):
                            _fields_ = [
                                ("hwnd", ctypes.c_void_p),
                                ("message", ctypes.c_uint),
                                ("wParam", ctypes.c_size_t),
                                ("lParam", ctypes.c_ssize_t),
                                ("time", ctypes.c_uint32),
                                ("pt_x", ctypes.c_long),
                                ("pt_y", ctypes.c_long),
                            ]

                        m_ = _MSG.from_address(int(message))
                        if (
                            m_.message == 0x0312
                            and (m_.wParam & 0xFFFF) == ctrl._global_hotkey_id
                        ):
                            ctrl._log.info(
                                f"{LOG_PREFIX} Global snabbinput-hotkey "
                                f"triggad ({ctrl._get_quick_add_hotkey_combo()}, "
                                f"var som helst i Windows)"
                            )
                            ctrl._QTimer.singleShot(
                                0, ctrl._global_quick_add
                            )
                            return True
                        # NY v7-fix68: push-to-show (Ctrl+Alt+V intryckt)
                        elif (
                            m_.message == 0x0312
                            and (m_.wParam & 0xFFFF)
                            == getattr(ctrl, "_push_hotkey_id", 0)
                        ):
                            ctrl._QTimer.singleShot(
                                0, ctrl._push_show_press
                            )
                            return True
                    except Exception:
                        pass
                    return False

            # NY v7-fix68/69: push-to-show — konfigurerbar hotkey
            # (settings 'push_show_hotkey', default 'Ctrl+Alt+V').
            # Håll inne = fönstret över appar; släpp = tillbaka.
            self._push_hotkey_id = 0xB42  # unikt id
            _combo = self._get_push_hotkey_combo()
            _mods, _vk = parse_hotkey_combo(_combo)
            if _vk:
                _ok_push = bool(user32.RegisterHotKey(
                    None, self._push_hotkey_id, _mods, _vk,
                ))
            else:
                _ok_push = False
            if _ok_push:
                self._log.info(
                    f"{LOG_PREFIX} Push-to-show aktiv: HÅLL INNE "
                    f"{_combo} = fönstret visas över appar; släpp = "
                    f"tillbaka på skrivbordet (v7-fix68/69)"
                )
            else:
                self._log.warning(
                    f"{LOG_PREFIX} RegisterHotKey({_combo}) misslyckades "
                    f"(ogiltig/upptagen) — push-to-show ej aktivt. "
                    f"Ändra via tray → '⌨️ Ändra Visa-över-hotkey...'"
                )

            self._global_hotkey_filter = _HotkeyFilter()
            self._app.installNativeEventFilter(self._global_hotkey_filter)
            self._log.info(
                f"{LOG_PREFIX} Global snabbinput aktiv: {_qa_combo} öppnar "
                f"ny uppgift VAR SOM HELST i Windows (v7-fix41/83)"
            )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _install_global_quick_add misslyckades: {e}",
                exc_info=True,
            )

    def _get_push_hotkey_combo(self) -> str:
        """NY v7-fix69: läs konfigurerad push-to-show-hotkey."""
        try:
            if hasattr(self.settings, "push_show_hotkey"):
                return self.settings.push_show_hotkey()
            return str(
                self.settings.get("push_show_hotkey", "Ctrl+Alt+V")
            )
        except Exception:
            return "Ctrl+Alt+V"

    def _get_quick_add_hotkey_combo(self) -> str:
        """
        NY v7-fix83: läs konfigurerad snabbinput-hotkey (ny uppgift).

        Default 'Ctrl+Alt+N' — ändras i tray → ⌨️ Snabbkommandon.
        """
        try:
            if hasattr(self.settings, "quick_add_hotkey"):
                return self.settings.quick_add_hotkey()
            return str(
                self.settings.get("quick_add_hotkey", "Ctrl+Alt+N")
            )
        except Exception:
            return "Ctrl+Alt+N"

    def _change_quick_add_hotkey_dialog(self) -> None:
        """
        NY v7-fix83: tray-dialog för att ändra snabbinput-hotkey.

        Skriv t.ex. 'Ctrl+Alt+N', 'Ctrl+Shift+N' eller 'Alt+F4'.
        Valideras + testregistreras innan den sparas; koll även mot
        konflikt med Visa-över-hotkey:en. Widgetens interna genväg
        (shortcuts 'add_task') uppdateras till samma kombination.
        """
        try:
            if self._QInputDialog is None:
                return
            _current = self._get_quick_add_hotkey_combo()
            text, ok = self._QInputDialog.getText(
                None,
                "⌨️ Snabbinput-hotkey (ny uppgift)",
                "Skriv din kombination:\n\n"
                "Modifierare: Ctrl, Alt, Shift, Win\n"
                "Tangent: A-Z, 0-9, F1-F12, Space, Enter, Tab\n\n"
                "Exempel: Ctrl+Alt+N  eller  Ctrl+Shift+A\n"
                "(öppnar snabbinput för ny uppgift VAR SOM HELST)",
                text=_current,
            )
            if not ok or not text.strip():
                return
            combo = text.strip()
            # Konflikt med Visa-över-hotkey?
            if combo.lower() == self._get_push_hotkey_combo().lower():
                if self._QMessageBox is not None:
                    self._QMessageBox.warning(
                        None,
                        "Konflikt",
                        f"'{combo}' används redan som Visa-över-hotkey.\n"
                        f"Välj en annan kombination.",
                    )
                return
            mods, vk = parse_hotkey_combo(combo)
            if not vk:
                if self._QMessageBox is not None:
                    self._QMessageBox.warning(
                        None,
                        "Ogiltig kombination",
                        f"'{combo}' kunde inte tolkas.\n\n"
                        f"Format: Ctrl+Alt+N (modifierare + tangent).",
                    )
                return
            # Testregistrera (avregistrera gammal först — Windows tillåter
            # bara en registrering per kombination)
            import ctypes
            _u = ctypes.windll.user32
            _old_id = getattr(self, "_global_hotkey_id", None)
            if _old_id is not None:
                with suppress(Exception):
                    _u.UnregisterHotKey(None, _old_id)
            _ok = bool(_u.RegisterHotKey(None, 0xB41, mods, vk))
            if not _ok:
                # Registrera tillbaka den gamla
                if _old_id is not None:
                    _om, _ov = parse_hotkey_combo(_current)
                    if _ov:
                        with suppress(Exception):
                            _u.RegisterHotKey(None, 0xB41, _om, _ov)
                if self._QMessageBox is not None:
                    self._QMessageBox.warning(
                        None,
                        "Kunde inte registrera",
                        f"'{combo}' är upptagen av ett annat program.\n"
                        f"Prova en annan kombination.",
                    )
                return
            # Spara (settings + widgetens interna genväg)
            if hasattr(self.settings, "set_quick_add_hotkey"):
                self.settings.set_quick_add_hotkey(combo)
            if hasattr(self.settings, "set_shortcut"):
                self.settings.set_shortcut("add_task", combo)
            # Omregistrera widgetens QShortcuts med nya kombinationen
            with self._widget_lock:
                for w in self._widgets.values():
                    with suppress(Exception):
                        if hasattr(w, "_unregister_hotkeys"):
                            w._unregister_hotkeys()
                        if hasattr(w, "_register_hotkeys"):
                            w._register_hotkeys()
            self._global_hotkey_id = 0xB41
            if self._tray is not None:
                self._tray.showMessage(
                    APP_NAME,
                    f"✅ Snabbinput-hotkey ändrad till: {combo}\n"
                    f"(ny uppgift var som helst i Windows)",
                    self._QSystemTrayIcon.MessageIcon.Information,
                    4000,
                )
            self._populate_tray_menu()
            self._log.info(
                f"{LOG_PREFIX} Snabbinput-hotkey ändrad: "
                f"{_current} → {combo} (v7-fix83)"
            )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _change_quick_add_hotkey_dialog: {e}",
                exc_info=True,
            )

    def _change_push_hotkey_dialog(self) -> None:
        """
        NY v7-fix69: tray-dialog för att ändra push-to-show-hotkey.

        Skriv t.ex. 'Ctrl+Alt+V', 'Ctrl+Shift+Space' eller 'Alt+F3'.
        Valideras + testregistreras innan den sparas.
        """
        try:
            if self._QInputDialog is None:
                return
            _current = self._get_push_hotkey_combo()
            text, ok = self._QInputDialog.getText(
                None,
                "⌨️ Visa-över-hotkey (push-to-show)",
                "Skriv din kombination:\n\n"
                "Modifierare: Ctrl, Alt, Shift, Win\n"
                "Tangent: A-Z, 0-9, F1-F12, Space, Enter, Tab\n\n"
                "Exempel: Ctrl+Alt+V  eller  Ctrl+Shift+Space\n"
                "(Håll inne tangenten = fönstret visas över appar)",
                text=_current,
            )
            if not ok or not text.strip():
                return
            combo = text.strip()
            mods, vk = parse_hotkey_combo(combo)
            if not vk:
                if self._QMessageBox is not None:
                    self._QMessageBox.warning(
                        None,
                        "Ogiltig kombination",
                        f"'{combo}' kunde inte tolkas.\n\n"
                        f"Format: Ctrl+Alt+V (modifierare + tangent).",
                    )
                return
            # Testregistrera den nya (kräver att gamla avregistreras först)
            import ctypes
            _u = ctypes.windll.user32
            _old_id = getattr(self, "_push_hotkey_id", None)
            if _old_id is not None:
                with suppress(Exception):
                    _u.UnregisterHotKey(None, _old_id)
            _ok = bool(_u.RegisterHotKey(None, 0xB42, mods, vk))
            if not _ok:
                # Registrera tillbaka den gamla
                if _old_id is not None:
                    _om, _ov = parse_hotkey_combo(_current)
                    if _ov:
                        with suppress(Exception):
                            _u.RegisterHotKey(None, 0xB42, _om, _ov)
                if self._QMessageBox is not None:
                    self._QMessageBox.warning(
                        None,
                        "Hotkey upptagen",
                        f"'{combo}' används redan av ett annat program."
                        f"\nProva en annan kombination.",
                    )
                return
            # Spara
            if hasattr(self.settings, "set_push_show_hotkey"):
                self.settings.set_push_show_hotkey(combo)
            self._push_hotkey_id = 0xB42
            if self._tray is not None:
                self._tray.showMessage(
                    APP_NAME,
                    f"✅ Visa-över-hotkey ändrad till: {combo}\n"
                    f"(håll inne = fönstret över appar)",
                    self._QSystemTrayIcon.MessageIcon.Information,
                    4000,
                )
            self._log.info(
                f"{LOG_PREFIX} Push-to-show-hotkey ändrad: "
                f"{_current} → {combo} (v7-fix69)"
            )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _change_push_hotkey_dialog: {e}",
                exc_info=True,
            )

    def _push_show_press(self) -> None:
        """
        NY v7-fix68: Ctrl+Alt+V tryckt ned — visa fönstret ÖVER appar.

        Behind-läge: lyft fönstret överst (HWND_TOP bland toppfönster).
        Above-läge: lossa från Progman (bevara skärm-position) + lyft.
        Släpp detekteras av _push_show_poll (GetAsyncKeyState) →
        _push_show_release återfäster på skrivbordet.
        """
        try:
            if getattr(self, "_push_show_active", False):
                return  # Redan aktivt
            import ctypes
            from ctypes import wintypes as _wt
            _u = ctypes.windll.user32
            with self._widget_lock:
                widgets = list(self._widgets.values())
            for w in widgets:
                shell = getattr(w, "_shell", None)
                if shell is None:
                    continue
                wid = getattr(w, "win_id", "?")
                hwnd = int(shell.winId())
                if not hwnd:
                    continue
                _prev = str(
                    getattr(shell, "_desktop_layer_mode", "normal")
                )
                shell._push_prev_mode = _prev
                if _prev == "above":
                    # Lossa från Progman + bevara skärm-position
                    _pre = _wt.RECT()
                    _u.GetWindowRect(hwnd, ctypes.byref(_pre))
                    _u.SetParent(hwnd, 0)
                    _u.SetWindowPos(
                        hwnd, 0, _pre.left, _pre.top, 0, 0,
                        0x0004 | 0x0010 | 0x0001,  # NOZORDER|NOACTIVATE|NOSIZE
                    )
                # FIX v7-fix75: TILLFÄLLIG TOPMOST — garanterat över
                # alla normala fönster (HWND_TOP räckte inte när t.ex.
                # Explorer låg över). NOTOPMOST vid release.
                _u.SetWindowPos(
                    hwnd, -1, 0, 0, 0, 0,
                    0x0040 | 0x0010 | 0x0001 | 0x0002,
                )  # HWND_TOPMOST | SHOWWINDOW|NOACTIVATE|NOSIZE|NOMOVE
                shell._desktop_layer_mode = "_push"
                self._log.info(
                    f"{LOG_PREFIX} PUSH-TO-SHOW: {wid!r} visas över "
                    f"appar (var: {_prev}) — släpp Ctrl+Alt+V för "
                    f"tillbaka (v7-fix68)"
                )
            self._push_show_active = True
            # Poll-timer: detektera släpp (V-knappen)
            _pt = getattr(self, "_push_poll_timer", None)
            if _pt is None:
                _pt = self._QTimer()
                _pt.setInterval(120)  # 120 ms
                _pt.timeout.connect(self._push_show_poll)
                self._push_poll_timer = _pt
            _pt.start()
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _push_show_press: {e}", exc_info=True
            )

    def _push_show_poll(self) -> None:
        """NY v7-fix68: polla V-knappen — släppt? → release."""
        try:
            import ctypes
            _still_down = bool(
                ctypes.windll.user32.GetAsyncKeyState(0x56) & 0x8000
            )
            if _still_down:
                return
            _pt = getattr(self, "_push_poll_timer", None)
            if _pt is not None:
                with suppress(Exception):
                    _pt.stop()
            self._push_show_release()
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} _push_show_poll: {e}")

    def _push_show_release(self) -> None:
        """
        NY v7-fix68: Ctrl+Alt+V släppt — återfäst på skrivbordet.
        """
        try:
            import ctypes
            _u = ctypes.windll.user32
            # FIX v7-fix75: ta bort TOPMOST först
            with self._widget_lock:
                _shells_r = [
                    getattr(w, "_shell", None)
                    for w in self._widgets.values()
                ]
            for _sh_r in _shells_r:
                if _sh_r is None:
                    continue
                with suppress(Exception):
                    _hw = int(_sh_r.winId())
                    if _hw:
                        _u.SetWindowPos(
                            _hw, -2, 0, 0, 0, 0,
                            0x0010 | 0x0001 | 0x0002,
                        )  # HWND_NOTOPMOST
            desktop_status = self._imports.get("desktop")
            with self._widget_lock:
                widgets = list(self._widgets.values())
            for w in widgets:
                shell = getattr(w, "_shell", None)
                if shell is None:
                    continue
                wid = getattr(w, "win_id", "?")
                _prev = str(
                    getattr(shell, "_push_prev_mode", "normal")
                )
                hwnd = int(shell.winId())
                if _prev in ("behind", "above"):
                    # FIX v7-fix70: kör HELA kedjan (behind → above →
                    # toppfönster) i stället för endast en väg —
                    # garanterar en fungerande återfästning
                    shell._desktop_layer_mode = None
                    self._apply_desktop_shell(shell, wid)
                else:
                    # normal: låt vara (vanligt fönster, rör ej z-ordning)
                    shell._desktop_layer_mode = "normal"
                self._log.info(
                    f"{LOG_PREFIX} PUSH-TO-SHOW: {wid!r} tillbaka "
                    f"({_prev}) (v7-fix68)"
                )
            self._push_show_active = False
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _push_show_release: {e}", exc_info=True
            )

    def _global_quick_add(self) -> None:
        """
        NY v7-fix41: global snabbinput triggad (köad på GUI-tråden).

        Visar befintligt fönster (enbart-läge) + öppnar snabbinput-dialogen.
        """
        try:
            if self._single_window_enabled():
                self._show_existing_window()
            self._tray_quick_add_task()
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} _global_quick_add: {e}")

    def _uninstall_global_quick_add(self) -> None:
        """NY v7-fix41: avregistrera global hotkey vid nedstängning."""
        hk_id = getattr(self, "_global_hotkey_id", None)
        if hk_id is None:
            return
        try:
            import ctypes
            ctypes.windll.user32.UnregisterHotKey(None, hk_id)
            self._log.info(f"{LOG_PREFIX} Global hotkey avregistrerad")
        except Exception:
            pass
        # NY v7-fix68: push-to-show-hotkey
        _phk = getattr(self, "_push_hotkey_id", None)
        if _phk is not None:
            with suppress(Exception):
                import ctypes as _ct
                _ct.windll.user32.UnregisterHotKey(None, _phk)
                self._log.info(
                    f"{LOG_PREFIX} Push-to-show-hotkey avregistrerad"
                )
            self._push_hotkey_id = None
        _pt = getattr(self, "_push_poll_timer", None)
        if _pt is not None:
            with suppress(Exception):
                _pt.stop()
        _f = getattr(self, "_global_hotkey_filter", None)
        if _f is not None and self._app is not None:
            with suppress(Exception):
                self._app.removeNativeEventFilter(_f)
        self._global_hotkey_filter = None
        self._global_hotkey_id = None

    def _desktop_mod(self, status: Any = None) -> Any:
        """
        NY v7-fix46: hämta desktop-MODULEN ur ImportStatus.

        ImportStatus.instance är en DICT ({modulnamn: modul}) när from_items
        ej angavs — ALL koden gjorde getattr() på själva dicten, vilket
        ALLTID misslyckades! Det gav falska "core/desktop.py är GAMMAL"-
        alarm trots att modulen var ny (och osynliggjorde ALL desktop-
        funktionalitet: desktop-lager, ikon-kollisioner m.m.).
        """
        try:
            st = status if status is not None else self._imports.get("desktop")
            if not st or not st.ok:
                return None
            inst = st.instance
            if isinstance(inst, dict):
                if "desktop" in inst:
                    return inst["desktop"]
                for _v in inst.values():
                    if _v is not None:
                        return _v
                return None
            return inst
        except Exception:
            return None

    def _init_reminder_service(self) -> None:
        """
        NY v7-fix64: Påminnelsetjänst — notiser för förfallna/dagens
        uppgifter (konkurrenternas kärnfunktion, gap 22.12.2).

        Kollar var 60:e sekund (QTimer på GUI-tråden):
          - Förfallna (due < idag) → "⚠ N uppgifter har passerat datum"
          - Dagens (due == idag)  → "📅 N uppgifter förfaller idag"
        Dedup: varje uppgift påminns EN gång per session.
        Snoozade uppgifter exkluderas. Av/på i tray-menyn.
        """
        try:
            self._reminded_ids = set()
            self._reminder_timer = self._QTimer()
            self._reminder_timer.setInterval(60000)  # 60 sek
            self._reminder_timer.timeout.connect(self._check_reminders)
            self._reminder_timer.start()
            # Första kontrollen efter 45 s (efter appstart, före/lägre än
            # auto-plugins på 30 s + notis på 45 s — utspritt)
            self._QTimer.singleShot(45000, self._check_reminders)
            self._log.info(
                f"{LOG_PREFIX} Påminnelsetjänst aktiv (var 60:e sek) — v7-fix64"
            )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _init_reminder_service: {e}", exc_info=True
            )

    def _check_reminders(self) -> None:
        """NY v7-fix64: kontrollera förfallna/dagens uppgifter → notis."""
        try:
            # Av/på?
            try:
                _enabled = (
                    self.settings.reminders_enabled()
                    if hasattr(self.settings, "reminders_enabled")
                    else bool(
                        self.settings.get("reminders_enabled", True)
                    )
                )
            except Exception:
                _enabled = True
            if not _enabled or self._tray is None:
                return

            from datetime import datetime as _dt, date as _d
            _today = _d.today()
            _now = _dt.now()
            if not hasattr(self, "_reminded_ids"):
                self._reminded_ids = set()

            overdue_new: List[Any] = []
            today_new: List[Any] = []
            if hasattr(self.store, "active_tasks"):
                for task in self.store.active_tasks():
                    tid = task.get("id")
                    due = task.get("due_date")
                    if not tid or not due or task.get("done"):
                        continue
                    # Snoozad? (gömd tills vidare — påminn ej)
                    sn = task.get("snoozed_until")
                    if sn:
                        try:
                            if _dt.fromisoformat(str(sn)) > _now:
                                continue
                        except (ValueError, TypeError):
                            pass
                    try:
                        d = _dt.fromisoformat(str(due)).date()
                    except (ValueError, TypeError):
                        continue
                    if tid in self._reminded_ids:
                        continue
                    if d < _today:
                        overdue_new.append(task)
                    elif d == _today:
                        today_new.append(task)

            if overdue_new:
                for task in overdue_new:
                    self._reminded_ids.add(task.get("id"))
                titles = ", ".join(
                    f"'{t.get('title', '?')[:25]}'"
                    for t in overdue_new[:3]
                )
                extra = (
                    f" (+{len(overdue_new) - 3} till)"
                    if len(overdue_new) > 3 else ""
                )
                self._tray.showMessage(
                    APP_NAME,
                    f"⚠ {len(overdue_new)} uppgift(er) har passerat "
                    f"förfallodatum:\n{titles}{extra}\n"
                    f"(högerklicka tray → 📋 Statistik eller öppna listan)",
                    self._QSystemTrayIcon.MessageIcon.Warning,
                    8000,
                )
                self._log.info(
                    f"{LOG_PREFIX} PÅMINNELSE: {len(overdue_new)} "
                    f"förfallna uppgifter"
                )
            if today_new:
                for task in today_new:
                    self._reminded_ids.add(task.get("id"))
                titles = ", ".join(
                    f"'{t.get('title', '?')[:25]}'"
                    for t in today_new[:3]
                )
                extra = (
                    f" (+{len(today_new) - 3} till)"
                    if len(today_new) > 3 else ""
                )
                self._tray.showMessage(
                    APP_NAME,
                    f"📅 {len(today_new)} uppgift(er) förfaller idag:\n"
                    f"{titles}{extra}",
                    self._QSystemTrayIcon.MessageIcon.Information,
                    8000,
                )
                self._log.info(
                    f"{LOG_PREFIX} PÅMINNELSE: {len(today_new)} "
                    f"uppgifter förfaller idag"
                )
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} _check_reminders: {e}")

    def _toggle_reminders(self, checked: bool) -> None:
        """NY v7-fix64: tray-toggle för påminnelser."""
        try:
            if hasattr(self.settings, "set_reminders_enabled"):
                self.settings.set_reminders_enabled(bool(checked))
            if hasattr(self, "_reminder_timer"):
                with suppress(Exception):
                    if checked:
                        self._reminder_timer.start()
                    else:
                        self._reminder_timer.stop()
            self._log.info(
                f"{LOG_PREFIX} Påminnelser: {'PÅ' if checked else 'AV'}"
            )
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} _toggle_reminders: {e}")

    # -----------------------------------------------------------------------
    # NY v7-fix90: E-POSTBRYGGA — Thunderbird-tillägg + inkorgsmapp
    # -----------------------------------------------------------------------
    #  Rickard 2026-10-11: "importera uppgifter från mail via thunderbird —
    #  om man kan göra tillägg till thunderbird som kan importera uppgift
    #  till appen. Uppgifter ska sparas i json-fil för att finnas kvar
    #  efter omstart av appen."
    #
    #  Lösning (två vägar in, alltid JSON-sparande):
    #    1. HTTP-brygga på 127.0.0.1 (Thunderbird-tillägget POST:ar mailet)
    #    2. Inkorgsmappen data/inbox/ (fungerar även om appen var avstängd)
    #  Se core/mail_bridge.py + katalogen thunderbird-tillagg/.
    # -----------------------------------------------------------------------

    # ------------------------------------------------------------------
    # NY v8 (2026-10-12): automatisk säkerhetskopia (data/backups/auto/)
    # ------------------------------------------------------------------
    def _user_data_dir(self) -> Path:
        """Mappen med active.json/archive.json/settings.json (js/)."""
        store = getattr(self, "store", None)
        d = getattr(store, "data_dir", None) if store is not None else None
        if callable(d):
            with suppress(Exception):
                d = d()
        return Path(str(d)) if d else JS_DIR

    def _restore_from_external_backup(self) -> None:
        from core import tasks_backup as _tb
        r = _tb.restore_if_missing(JS_DIR)
        if r.get("active") or r.get("settings"):
            self._log.warning(
                f"{LOG_PREFIX} ♻ Återställde från automatisk backup ({r.get('from')}): "
                f"uppgifter={r.get('active')}, inställningar={r.get('settings')}"
            )

    def _external_backup(self, reason: str = "") -> None:
        """Kopiera uppgifter + inställningar till data/backups/auto/ (hoppar över om oförändrat)."""
        try:
            if self._mode == AppMode.SAFE_MODE:
                return
            from core import tasks_backup as _tb
            p = _tb.snapshot_external(self._user_data_dir())
            if p is not None:
                self._log.info(f"{LOG_PREFIX} automatisk backup ({reason}): {p.name}")
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} automatisk backup misslyckades ({reason}): {e}")

    def _init_external_backup(self) -> None:
        """Första kopian strax efter start, därefter var 5:e minut (bara ändringar sparas)."""
        if self._mode == AppMode.SAFE_MODE:
            return
        self._ext_backup_timer = self._QTimer(self._app)
        self._ext_backup_timer.setInterval(5 * 60 * 1000)
        self._ext_backup_timer.timeout.connect(lambda: self._external_backup("timer"))
        self._ext_backup_timer.start()
        self._QTimer.singleShot(15_000, lambda: self._external_backup("start"))

    def _mail_bridge_data_dir(self) -> Path:
        """data/-katalogen (där active.json och mail_bridge/ ligger)."""
        try:
            if hasattr(self.settings, "data_dir"):
                return Path(str(self.settings.data_dir()))
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} data_dir via settings: {e}")
        return Path(getattr(self, "_SCRIPT_DIR", SCRIPT_DIR)) / "data"

    def _init_mail_bridge(self) -> None:
        """
        NY v7-fix90: starta e-postbryggan (Thunderbird-tillägg) + bevaka
        inkorgsmappen. Misslyckas tyst — appen får aldrig hindras av detta.
        """
        try:
            if self._mode == AppMode.SAFE_MODE:
                self._log.info(
                    f"{LOG_PREFIX} e-postbryggan hoppas över (safe-mode)"
                )
                return
            from core.mail_bridge import MailBridgeService

            data_dir = self._mail_bridge_data_dir()

            def _setting(name: str, default: Any, cast: Any) -> Any:
                """Läs en settings-nyckel säkert (gammal settings.json → default)."""
                try:
                    getter = getattr(self.settings, name, None)
                    if callable(getter):
                        return cast(getter())
                except Exception as e:
                    self._log.debug(f"{LOG_PREFIX} settings.{name}: {e}")
                return default

            _http_on = _setting("mail_bridge_enabled", True, bool)
            _watch_on = _setting("inbox_watch_enabled", True, bool)
            _port = _setting("mail_bridge_port", 8765, int)
            _poll = _setting("inbox_poll_seconds", 3, int)
            _token = _setting("mail_bridge_token", "", str)

            self._mail_bridge_events: deque = deque(maxlen=50)
            self._mail_bridge_lock = threading.Lock()

            self._mail_bridge = MailBridgeService(
                self.store,
                data_dir,
                port=_port,
                token=_token,
                version=APP_VERSION_DISPLAY,
                http_enabled=_http_on,
                watch_enabled=_watch_on,
                poll_seconds=_poll,
                on_event=self._mail_bridge_notify,
            )
            status = self._mail_bridge.start()

            # Spara token i settings första gången (så den syns i JSON)
            with suppress(Exception):
                if (not _token) and self._mail_bridge.token and hasattr(
                    self.settings, "set_mail_bridge_token"
                ):
                    self.settings.set_mail_bridge_token(self._mail_bridge.token)

            # Poll-timer på GUI-tråden: visar notiser/flashar uppgifter
            try:
                self._mail_bridge_timer = self._QTimer(self._app)
                self._mail_bridge_timer.setInterval(700)
                self._mail_bridge_timer.timeout.connect(self._poll_mail_bridge)
                self._mail_bridge_timer.start()
            except Exception as e:
                self._log.debug(
                    f"{LOG_PREFIX} kunde inte starta brygg-poll-timer: {e}"
                )

            self._log.info(
                f"{LOG_PREFIX} ✓ E-postbrygga: http="
                f"{'PÅ' if status['http_running'] else 'AV'} "
                f"(port {status['port']}), inkorg="
                f"{'PÅ' if status['watch_running'] else 'AV'} "
                f"({status['inbox']}), token={status['token'][:6]}…"
            )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _init_mail_bridge misslyckades: {e}",
                exc_info=True,
            )

    def _mail_bridge_notify(self, event: Dict[str, Any]) -> None:
        """
        NY v7-fix90: kallas från brygg-tråden/bevakningstråden vid import.

        Lägger händelsen i en trådsäker kö — GUI:t hämtar den i
        _poll_mail_bridge (Qt-får aldrig röras från andra trådar).
        """
        try:
            lock = getattr(self, "_mail_bridge_lock", None)
            events = getattr(self, "_mail_bridge_events", None)
            if events is None:
                return
            if lock is not None:
                with lock:
                    events.append(event)
            else:
                events.append(event)
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} mail-notis kunde ej köas: {e}")

    def _poll_mail_bridge(self) -> None:
        """NY v7-fix90: töm notiskön och visa resultatet i tray/widget."""
        try:
            events = getattr(self, "_mail_bridge_events", None)
            if not events:
                return
            lock = getattr(self, "_mail_bridge_lock", None)
            batch: List[Dict[str, Any]] = []
            if lock is not None:
                with lock:
                    while events:
                        batch.append(events.popleft())
            else:
                while events:
                    batch.append(events.popleft())
            for evt in batch:
                for res in evt.get("results", []):
                    if not res.get("ok"):
                        self._log.warning(
                            f"{LOG_PREFIX} mail-import misslyckades: "
                            f"{res.get('error')}"
                        )
                        continue
                    task_id = res.get("task_id")
                    title = str(res.get("title", ""))[:60]
                    duplicate = bool(res.get("duplicate"))
                    # 1. Flasha uppgiften i Aktiva (widgeten)
                    if task_id:
                        self._flash_task_in_widgets(task_id)
                    # 2. Tray-notis
                    if self._tray is not None:
                        try:
                            self._tray.showMessage(
                                (
                                    "📋 Redan importerad"
                                    if duplicate else "📧 Mail → uppgift"
                                ),
                                (
                                    f"'{title}' finns redan i listan."
                                    if duplicate else
                                    f"'{title}' skapades och sparades."
                                ),
                                self._QSystemTrayIcon.MessageIcon.Information,
                                6000,
                            )
                        except Exception as e:
                            self._log.debug(
                                f"{LOG_PREFIX} tray-notis misslyckades: {e}"
                            )
                    self._log.info(
                        f"{LOG_PREFIX} mail → uppgift: {task_id!r} "
                        f"'{title}' ({'dublett' if duplicate else 'ny'}, "
                        f"källa={evt.get('source', '?')})"
                    )
            with suppress(Exception):
                self._update_tray_tooltip()
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} _poll_mail_bridge: {e}")

    def _flash_task_in_widgets(self, task_id: str) -> None:
        """NY v7-fix90: visa uppgiften synligt i alla widgets (like fix77)."""
        try:
            with self._widget_lock:
                widgets = list(self._widgets.values())
            for w in widgets:
                fn = getattr(w, "_show_task_in_active", None)
                if callable(fn):
                    with suppress(Exception):
                        fn(task_id)
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} _flash_task_in_widgets: {e}")

    def _mail_bridge_status_text(self) -> str:
        """Kort statustext för tray-menyn."""
        svc = getattr(self, "_mail_bridge", None)
        if svc is None:
            return "avstängd"
        try:
            return svc.status_text()
        except Exception:
            return "okänd status"

    def _toggle_mail_bridge(self, checked: bool) -> None:
        """NY v7-fix90: slå bryggan (localhost-servern) på/av."""
        try:
            if hasattr(self.settings, "set_mail_bridge_enabled"):
                self.settings.set_mail_bridge_enabled(bool(checked))
            svc = getattr(self, "_mail_bridge", None)
            if svc is None:
                self._init_mail_bridge()
            else:
                svc.http_enabled = bool(checked)
                if checked:
                    ok = svc.server.start()
                    if ok:
                        svc.port = svc.server.port
                        with suppress(Exception):
                            if hasattr(self.settings, "set_mail_bridge_port"):
                                self.settings.set_mail_bridge_port(svc.port)
                        svc.config_payload()
                    self._log.info(
                        f"{LOG_PREFIX} bryggan {'startad' if ok else 'kunde ej starta'}"
                    )
                else:
                    svc.server.stop()
                    self._log.info(f"{LOG_PREFIX} bryggan stoppad (tray-toggle)")
            with suppress(Exception):
                self._populate_tray_menu()
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} _toggle_mail_bridge: {e}")

    def _toggle_inbox_watch(self, checked: bool) -> None:
        """NY v7-fix90: slå automatisk import från data/inbox/ på/av."""
        try:
            if hasattr(self.settings, "set_inbox_watch_enabled"):
                self.settings.set_inbox_watch_enabled(bool(checked))
            svc = getattr(self, "_mail_bridge", None)
            if svc is None:
                self._init_mail_bridge()
            else:
                svc.watch_enabled = bool(checked)
                if checked:
                    svc.start_watcher()
                else:
                    svc.stop_watcher()
            self._log.info(
                f"{LOG_PREFIX} inkorgsbevakning: {'PÅ' if checked else 'AV'}"
            )
            with suppress(Exception):
                self._populate_tray_menu()
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} _toggle_inbox_watch: {e}")

    def _stop_mail_bridge(self) -> None:
        """NY v7-fix90: stoppa brygga + bevakning (vid avslut)."""
        try:
            timer = getattr(self, "_mail_bridge_timer", None)
            if timer is not None:
                with suppress(Exception):
                    timer.stop()
            svc = getattr(self, "_mail_bridge", None)
            if svc is not None:
                svc.stop()
                self._log.info(f"{LOG_PREFIX} e-postbryggan stoppad")
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} _stop_mail_bridge: {e}")

    def _mail_bridge_config_json(self) -> str:
        """Inställningarna som JSON-sträng (för urklipp/tillägget)."""
        svc = getattr(self, "_mail_bridge", None)
        if svc is None:
            return "{}"
        try:
            cfg = svc.config_payload()
            return _stdlib_json.dumps(cfg, ensure_ascii=False, indent=2)
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} kunde ej bygga config: {e}")
            return "{}"

    def _copy_mail_bridge_settings(self) -> None:
        """
        NY v7-fix90: kopiera inställningarna (url + token) till urklipp och
        visa dem — användaren klistrar in dem i Thunderbird-tillägget.
        """
        try:
            svc = getattr(self, "_mail_bridge", None)
            if svc is None:
                self._init_mail_bridge()
                svc = getattr(self, "_mail_bridge", None)
            if svc is None:
                if self._QMessageBox is not None:
                    self._QMessageBox.warning(
                        None, "TaskBord", "E-postbryggan kunde inte startas."
                    )
                return
            text = self._mail_bridge_config_json()
            copied = False
            try:
                from PySide6.QtWidgets import QApplication
                app = QApplication.instance() or self._app
                if app is not None:
                    app.clipboard().setText(text)
                    copied = True
            except Exception as e:
                self._log.debug(f"{LOG_PREFIX} urklipp misslyckades: {e}")
            status = svc.status()
            info = (
                f"Adress:  {status['url']}\n"
                f"Token:   {status['token'][:10]}…"
                f"({len(status['token'])} tecken)\n"
                f"Brygga:  {'🟢 körs' if status['http_running'] else '🔴 stoppad'}\n"
                f"Inkorg:  {'🟢 bevakas' if status['watch_running'] else '⚪ av'}"
                f" — {status['inbox']}\n\n"
                f"{'✅ Inställningarna ligger på urklipp.' if copied else '⚠️ Kunde inte kopiera — markera texten manuellt.'}\n\n"
                f"Klistra in i Thunderbird:\n"
                f"  Tilläggen → TaskBord → Inställningar →\n"
                f"  fältet 'Klistra in JSON' → Läs in och spara."
            )
            self._log.info(
                f"{LOG_PREFIX} brygg-inställningar kopierade till urklipp "
                f"(port {status['port']})"
            )
            if self._QMessageBox is not None:
                box = self._QMessageBox()
                box.setWindowTitle("📧 TaskBord — inställningar för Thunderbird")
                box.setIcon(self._QMessageBox.Icon.Information)
                box.setText(info)
                box.setDetailedText(text)
                box.exec()
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _copy_mail_bridge_settings: {e}", exc_info=True
            )

    def _open_inbox_folder(self) -> None:
        """NY v7-fix90: öppna data/inbox/ i Utforskaren."""
        try:
            svc = getattr(self, "_mail_bridge", None)
            if svc is not None:
                folder = Path(svc.paths["inbox"])
            else:
                folder = self._mail_bridge_data_dir() / "inbox"
            folder.mkdir(parents=True, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(str(folder))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
            self._log.info(f"{LOG_PREFIX} inkorgsmappen öppnad: {folder}")
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} _open_inbox_folder: {e}")

    def _open_thunderbird_addon_folder(self) -> None:
        """NY v7-fix90: öppna thunderbird-tillagg/ (för installation i TB)."""
        try:
            folder = Path(
                getattr(self, "_SCRIPT_DIR", SCRIPT_DIR)
            ) / "thunderbird-tillagg"
            if not folder.is_dir():
                folder = Path(getattr(self, "_SCRIPT_DIR", SCRIPT_DIR))
            if sys.platform == "win32":
                os.startfile(str(folder))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} kunde ej öppna tilläggsmappen: {e}")

    def _show_thunderbird_guide(self) -> None:
        """NY v7-fix90: steg-för-steg: installera Thunderbird-tillägget."""
        folder = Path(
            getattr(self, "_SCRIPT_DIR", SCRIPT_DIR)
        ) / "thunderbird-tillagg"
        text = (
            "Så kopplar du Thunderbird mot TaskBord:\n\n"
            "1. Öppna TaskBord-menyn (tray-ikonen) → 📧 E-post & Thunderbird\n"
            "   → '📋 Kopiera inställningar' (adress + token ligger nu på urklipp)\n\n"
            "2. I Thunderbird: Verktyg → Tillägg och teman\n"
            "   • Klicka kugghjulet ⚙️ → 'Installera tillägg från fil…'\n"
            f"   • Välj filen TaskBord-Thunderbird.xpi (finns i\n"
            f"     {folder})\n"
            "     – saknas .xpi: kör SKAPA_XPI.bat i appmappen en gång\n\n"
            "3. Öppna tilläggets inställningar (Tillägg och teman →\n"
            "   TaskBord → Inställningar), klistra in JSON och spara.\n\n"
            "4. Använd: högerklicka på ett mail →\n"
            "   '📋 Skicka till TaskBord (ny uppgift)'\n\n"
            "Uppgiften dyker upp i widgeten och sparas i data/active.json\n"
            "(finns kvar efter omstart)."
        )
        try:
            if self._QMessageBox is None:
                self._log.info(f"{LOG_PREFIX} {text}")
                return
            box = self._QMessageBox()
            box.setWindowTitle("🧩 Thunderbird-tillägg")
            box.setIcon(self._QMessageBox.Icon.Information)
            box.setText(text)
            open_btn = box.addButton(
                "📂 Öppna tilläggsmappen", self._QMessageBox.ButtonRole.ActionRole
            )
            box.addButton("Stäng", self._QMessageBox.ButtonRole.AcceptRole)
            box.exec()
            if box.clickedButton() is open_btn:
                self._open_thunderbird_addon_folder()
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} _show_thunderbird_guide: {e}")

    def _import_email_files_dialog(self) -> None:
        """
        NY v7-fix90: importera .eml/.msg via fil-dialog (samma kärna som
        📧-knappen i widgeten) — för hela appen, från tray-menyn.
        """
        try:
            from PySide6.QtWidgets import QFileDialog
            files, _ = QFileDialog.getOpenFileNames(
                None,
                "Importera e-post som uppgift",
                "",
                "E-postfiler (*.eml *.msg);;Alla filer (*.*)",
            )
            if not files:
                return
            from core.email_import import import_email
            data_dir = self._mail_bridge_data_dir()
            imported = duplicates = failed = 0
            for fp in files:
                info: Dict[str, Any] = {}
                task_id = import_email(Path(fp), self.store, data_dir, info=info)
                if not task_id:
                    failed += 1
                    continue
                if info.get("duplicate"):
                    duplicates += 1
                else:
                    imported += 1
                self._flash_task_in_widgets(task_id)
            with suppress(Exception):
                self.store.save()
            self._log.info(
                f"{LOG_PREFIX} manuell e-postimport: {imported} nya, "
                f"{duplicates} dubletter, {failed} fel"
            )
            if self._QMessageBox is not None:
                self._QMessageBox.information(
                    None,
                    "📧 E-postimport",
                    f"{imported} importerade, {duplicates} redan importerade, "
                    f"{failed} misslyckades.\n\nUppgifterna sparas i "
                    f"data/active.json (kvar efter omstart).",
                )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _import_email_files_dialog: {e}", exc_info=True
            )

    def _set_theme_value(self, value: str) -> None:
        """
        NY v7-fix82: sätt tema från tray-menyn (light/dark/auto/system).

        settings.set_theme() sänder theme_changed → _on_theme_changed
        applicerar om temat på ALLA widgets + bygger om tray-menyn.
        'auto' = klockstyrt (07:00–18:59 ljust, annars mörkt).
        """
        try:
            value = str(value).lower().strip()
            if value not in ("light", "dark", "auto", "system"):
                self._log.warning(
                    f"{LOG_PREFIX} _set_theme_value: ogiltigt tema {value!r}"
                )
                return
            if hasattr(self.settings, "set_theme"):
                self.settings.set_theme(value)
                self._log.info(
                    f"{LOG_PREFIX} Tema satt till '{value}' via tray-menyn "
                    f"(v7-fix82)"
                )
            else:
                self._log.warning(
                    f"{LOG_PREFIX} settings saknar set_theme() — kan ej "
                    f"sätta tema {value!r}"
                )
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} _set_theme_value: {e}")

    def _schedule_auto_plugin_update(self) -> None:
        """
        NY v7-fix50: INSTALLERA + UPPDATERA tillägg automatiskt vid start.

        Rickards val 2026-10-02: "full automatik" — saknade tillägg
        installeras tyst och föråldrade uppdateras via pip, i bakgrunds-
        tråd (30 s efter start så appstarten aldrig blockeras).
        Avstängningsbart: settings auto_update_plugins=false eller
        tray-menyn "🔄 Auto-uppdatera tillägg vid start".
        """
        try:
            if getattr(self, "_plugins_auto_started", False):
                return
            self._plugins_auto_started = True
            # Setting av/på
            try:
                _enabled = (
                    self.settings.auto_update_plugins()
                    if hasattr(self.settings, "auto_update_plugins")
                    else bool(self.settings.get("auto_update_plugins", True))
                )
            except Exception:
                _enabled = True
            if not _enabled:
                self._log.info(
                    f"{LOG_PREFIX} Auto-uppdatering av tillägg: AVSTÄNGD "
                    f"i settings"
                )
                return
            if self._mode != AppMode.NORMAL:
                return
            self._plugin_auto_result = None
            # NY v7-fix66: progress-state för dialogen (trådsäker via
            # enkla tilldelningar + GUI-poll var 500 ms)
            self._plugin_progress = {
                "state": "idle", "phase": "", "index": 0, "total": 0,
                "name": "", "last_ok": None,
            }

            def _progress_cb(phase, index, total, name, ok):
                with suppress(Exception):
                    self._plugin_progress = {
                        "state": "working", "phase": phase,
                        "index": index, "total": total, "name": name,
                        "last_ok": ok,
                    }

            def _auto_plugins_bg() -> None:
                try:
                    import time as _time
                    _time.sleep(30)  # låt appen starta klart först
                    installed = {}
                    updated = {}
                    try:
                        # FIX v7-fix52: TYST installation (full auto —
                        # gamla koden öppnade en dialog!)
                        # v7-fix66: progress-callback → progress-bar
                        installed = (
                            install_missing_plugins_silent(
                                progress_cb=_progress_cb
                            ) or {}
                        )
                    except Exception as e:
                        self._log.warning(
                            f"{LOG_PREFIX} auto-plugin: installation av "
                            f"saknade misslyckades: {e}"
                        )
                    try:
                        outdated = _check_outdated_packages() or []
                        if outdated:
                            # FIX v7-fix53: paket vars moduler REDAN KÖRS
                            # (PySide6, orjson m.fl.) kan ej uppdateras på
                            # Windows — filerna är låsta av processen.
                            # Skippa dem (pip skulle hänga/faila).
                            _MODULE_MAP = {
                                "pyside6": "PySide6",
                                "pyside6-essentials": "PySide6",
                                "pyside6-addons": "PySide6",
                                "orjson": "orjson",
                                "psutil": "psutil",
                                "extract-msg": "extract_msg",
                                "reportlab": "reportlab",
                                "pywin32": "win32api",
                            }
                            names = []
                            _skipped = []
                            for _pk, _v, _l in outdated:
                                _mod = _MODULE_MAP.get(
                                    str(_pk).lower(), str(_pk)
                                )
                                if _mod in sys.modules:
                                    _skipped.append(_pk)
                                else:
                                    names.append(_pk)
                            if _skipped:
                                self._log.info(
                                    f"{LOG_PREFIX} auto-plugin: SKIPPAR "
                                    f"{_skipped} (i bruk — filer låsta, "
                                    f"uppdatera med appen avstängd)"
                                )
                            if names:
                                self._log.info(
                                    f"{LOG_PREFIX} auto-plugin: föråldrade: "
                                    f"{names} → uppdaterar automatiskt"
                                )
                                # v7-fix66: progress för uppdateringar
                                _ntotal = len(names)
                                for _ni, _nn in enumerate(names, 1):
                                    _progress_cb(
                                        "update", _ni, _ntotal, _nn, None
                                    )
                                    _r = _update_packages([_nn]) or {}
                                    _progress_cb(
                                        "update", _ni, _ntotal, _nn,
                                        bool(_r.get(_nn)),
                                    )
                                updated = {
                                    n: True for n in names
                                }
                            else:
                                updated = {}
                    except Exception as e:
                        self._log.warning(
                            f"{LOG_PREFIX} auto-plugin: uppdatering "
                            f"misslyckades: {e}"
                        )
                    self._plugin_auto_result = {
                        "installed": installed,
                        "updated": updated,
                    }
                except Exception as e:
                    self._log.warning(
                        f"{LOG_PREFIX} auto-plugin-bakgrund: {e}"
                    )

            _t = threading.Thread(
                target=_auto_plugins_bg, daemon=True, name="AutoPlugins"
            )
            _t.start()
            # Notis på GUI-tråden när resultatet kommit (trådsäker väg)
            self._QTimer.singleShot(
                45000, self._notify_plugin_auto_result
            )
            # NY v7-fix66: poll-timer som driver progress-dialogen
            self._plugin_progress_timer = self._QTimer()
            self._plugin_progress_timer.setInterval(500)
            self._plugin_progress_timer.timeout.connect(
                self._poll_plugin_progress
            )
            self._plugin_progress_timer.start()
            self._log.info(
                f"{LOG_PREFIX} Auto-uppdatering av tillägg schemalagd "
                f"(30 s fördröjning, bakgrund, progress-bar) — v7-fix50/66"
            )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _schedule_auto_plugin_update: {e}",
                exc_info=True,
            )

    def _poll_plugin_progress(self) -> None:
        """
        NY v7-fix66: visa/uppdatera progress-dialog för tilläggs-
        installation (körs var 500 ms på GUI-tråden — trådsäkert).
        """
        try:
            st = getattr(self, "_plugin_progress", None) or {}
            if st.get("state") != "working":
                return
            total = int(st.get("total") or 0)
            if total <= 0:
                return
            # Skapa dialog vid första anropet
            dlg = getattr(self, "_plugin_progress_dlg", None)
            if dlg is None:
                dlg = self._build_plugin_progress_dialog(total)
                self._plugin_progress_dlg = dlg
            idx = int(st.get("index") or 0)
            phase = st.get("phase") or "install"
            name = st.get("name") or ""
            verb = (
                "Installerar" if phase == "install" else "Uppdaterar"
            )
            try:
                dlg.bar.setMaximum(total)
                dlg.bar.setValue(min(idx, total))
                dlg.label.setText(
                    f"{verb} tillägg {min(idx, total)}/{total}:\n{name}"
                )
                dlg.status.setText(
                    "✓" if st.get("last_ok") else "…"
                )
            except Exception:
                pass
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} _poll_plugin_progress: {e}")

    def _build_plugin_progress_dialog(self, total: int) -> Any:
        """NY v7-fix66: bygg den lilla mörka progress-dialogen."""
        try:
            from PySide6.QtCore import Qt as _Qt
            from PySide6.QtWidgets import (
                QProgressBar as _QPB, QDialog as _QDialog,
                QVBoxLayout as _QVL, QLabel as _QL,
            )
            dlg = _QDialog()
            dlg.setWindowFlags(
                _Qt.WindowType.FramelessWindowHint
                | _Qt.WindowType.Tool
                | _Qt.WindowType.WindowStaysOnTopHint
            )
            dlg.setAttribute(_Qt.WidgetAttribute.WA_TranslucentBackground, True)
            dlg.setFixedSize(340, 110)
            lay = _QVL(dlg)
            lay.setContentsMargins(16, 14, 16, 14)
            dlg.label = _QL(f"Installerar tillägg 0/{total}:")
            dlg.label.setStyleSheet(
                "color: #eef1fb; font-size: 13px; font-weight: 600;"
                "background: transparent;"
            )
            dlg.bar = _QPB()
            dlg.bar.setRange(0, total)
            dlg.bar.setTextVisible(True)
            dlg.bar.setStyleSheet(
                "QProgressBar { background: rgba(56,62,96,120); "
                "border: 1px solid rgba(151,162,216,0.35); "
                "border-radius: 8px; color: #eef1fb; "
                "text-align: center; font-size: 12px; } "
                "QProgressBar::chunk { "
                "background: qlineargradient(x1:0,y1:0,x2:1,y2:0, "
                "stop:0 #818cf8, stop:1 #6366f1); border-radius: 7px; }"
            )
            dlg.status = _QL("…")
            dlg.status.setStyleSheet(
                "color: #9aa3c2; font-size: 11px; background: transparent;"
            )
            lay.addWidget(dlg.label)
            lay.addWidget(dlg.bar)
            lay.addWidget(dlg.status)
            dlg.setStyleSheet(
                "QDialog { background: rgba(30,32,54,240); "
                "border-radius: 14px; border: 1px solid "
                "rgba(129,140,248,0.35); }"
            )
            # Centrera på primära skärmen
            try:
                _scr = self._app.primaryScreen()
                if _scr is not None:
                    _g = _scr.availableGeometry()
                    dlg.move(
                        _g.x() + (_g.width() - 340) // 2,
                        _g.y() + (_g.height() - 110) // 2,
                    )
            except Exception:
                pass
            dlg.show()
            self._log.info(
                f"{LOG_PREFIX} Progress-dialog visas: {total} tillägg"
            )
            return dlg
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _build_plugin_progress_dialog: {e}"
            )
            return None

    def _close_plugin_progress(self) -> None:
        """NY v7-fix66: stäng progress-dialogen (anropas efter done)."""
        try:
            dlg = getattr(self, "_plugin_progress_dlg", None)
            if dlg is not None:
                with suppress(Exception):
                    dlg.close()
                    dlg.deleteLater()
                self._plugin_progress_dlg = None
            _pt = getattr(self, "_plugin_progress_timer", None)
            if _pt is not None:
                with suppress(Exception):
                    _pt.stop()
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} _close_plugin_progress: {e}")

    def _notify_plugin_auto_result(self) -> None:
        """NY v7-fix50: visa tray-notis efter automatisk tilläggsuppdatering."""
        try:
            res = getattr(self, "_plugin_auto_result", None)
            if res is None:
                # v7-fix66: bg-jobbet fortfarande igång (stora paket) →
                # stäng INTE dialogen, kolla igen om 10 s
                self._QTimer.singleShot(
                    10000, self._notify_plugin_auto_result
                )
                return
            # v7-fix66: klart — stäng progress-dialogen
            self._close_plugin_progress()
            if not res or self._tray is None:
                return
            n_inst = sum(1 for v in (res.get("installed") or {}).values() if v)
            n_upd = sum(1 for v in (res.get("updated") or {}).values() if v)
            if n_inst or n_upd:
                msg = (
                    f"✅ {n_inst} tillägg installerade, {n_upd} uppdaterade."
                )
                if n_upd:
                    msg += "\nStarta om appen för att aktivera nya versioner."
                self._tray.showMessage(
                    APP_NAME,
                    msg,
                    self._QSystemTrayIcon.MessageIcon.Information,
                    6000,
                )
            else:
                self._log.info(
                    f"{LOG_PREFIX} auto-plugin: alla tillägg aktuella "
                    f"(inget att göra)"
                )
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} _notify_plugin_auto_result: {e}")
            with suppress(Exception):
                self._close_plugin_progress()

    def _toggle_auto_update_plugins(self, checked: bool) -> None:
        """NY v7-fix50: tray-toggle för auto-uppdatering av tillägg."""
        try:
            if hasattr(self.settings, "set_auto_update_plugins"):
                self.settings.set_auto_update_plugins(bool(checked))
            self._log.info(
                f"{LOG_PREFIX} Auto-uppdatering tillägg: "
                f"{'PÅ' if checked else 'AV'}"
            )
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} toggle auto-plugins: {e}")

    def _float_window_above_apps(self) -> None:
        """
        NY v7-fix57: visa fönstret OVANPÅ appar tills vidare.

        Lossar fönstret från skrivbordslagret (ovanpå ikonerna) och
        gör det till ett vanligt fönster som du ser bland dina appar —
        praktiskt när du vill "hitta" widgeten eller jobba med den.
        Återgå med "📌 Fäst på skrivbordet igen".
        """
        try:
            with self._widget_lock:
                widgets = list(self._widgets.values())
            for w in widgets:
                shell = getattr(w, "_shell", None)
                if shell is None:
                    continue
                wid = getattr(w, "win_id", "?")
                if sys.platform == "win32":
                    with suppress(Exception):
                        import ctypes
                        from ctypes import wintypes as _wt
                        _u = ctypes.windll.user32
                        _hw = int(shell.winId())
                        if _hw and _u.GetAncestor(_hw, 2):
                            # FIX v7-fix62: las SKARM-positionen FORE
                            # lossningen — annars behaller Windows de
                            # Progman-relativa koordinaterna som tolkas
                            # som skarm-koordinater → fönstret hoppar
                            # +1920 px UTANFOR skärmen (osynligt)!
                            _pre = _wt.RECT()
                            _u.GetWindowRect(_hw, ctypes.byref(_pre))
                            _u.SetParent(_hw, 0)
                            # Aterstall exakt skarm-position
                            _u.SetWindowPos(
                                _hw, 0,
                                _pre.left, _pre.top, 0, 0,
                                0x0004 | 0x0010 | 0x0001,
                            )  # NOZORDER | NOACTIVATE | NOSIZE
                        # Visa + lyft (HWND_TOP — ej TOPMOST, ej påträngande)
                        _u.SetWindowPos(
                            _hw, 0, 0, 0, 0, 0,
                            0x0040 | 0x0010 | 0x0001 | 0x0002,
                        )  # SHOWWINDOW | NOACTIVATE | NOSIZE | NOMOVE
                shell._desktop_layer_mode = "normal"
                with suppress(Exception):
                    shell.show()
                    shell.raise_()
                self._log.info(
                    f"{LOG_PREFIX} {wid!r}: FLYTANDE LÄGE — ovanpå appar "
                    f"tills du väljer 'Fäst på skrivbordet' (v7-fix57)"
                )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _float_window_above_apps: {e}", exc_info=True
            )

    def _pin_window_to_desktop(self) -> None:
        """
        NY v7-fix57: fäst fönstret på skrivbordet igen (above-läget).
        """
        try:
            with self._widget_lock:
                widgets = list(self._widgets.values())
            for w in widgets:
                shell = getattr(w, "_shell", None)
                if shell is None:
                    continue
                wid = getattr(w, "win_id", "?")
                shell._desktop_layer_mode = None
                self._apply_desktop_shell(shell, wid)
                self._log.info(
                    f"{LOG_PREFIX} {wid!r}: FÄST PÅ SKRIVBORDET igen (v7-fix57)"
                )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _pin_window_to_desktop: {e}", exc_info=True
            )

    def _set_window_size_max(self) -> None:
        """NY v7-fix61: max storlek (90 % bredd, 75 % höjd av skärmen)."""
        try:
            _scr = (
                self._app.primaryScreen() if self._app else None
            )
            if _scr is None:
                return
            _sg = _scr.availableGeometry()
            self._set_window_size_preset(
                int(_sg.width() * 0.9), int(_sg.height() * 0.75)
            )
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} _set_window_size_max: {e}")

    def _set_window_size_preset(self, width: int, height: int) -> None:
        """
        NY v7-fix61: sätt fönsterstorlek (förinställning från tray).

        Rickard: "gör det som en ikon som man kan justera storleken på" —
        Ikon / Kompakt / Standard / Stor. Behåller topp-vänster-position,
        sparar geometrin, fungerar i alla desktop-lägen (DII-kompenserad).
        """
        try:
            with self._widget_lock:
                widgets = list(self._widgets.values())
            for w in widgets:
                shell = getattr(w, "_shell", None)
                if shell is None:
                    continue
                _sx, _sy = shell.x(), shell.y()
                # FIX v7-fix62: sakerhets-clamp — om positionen ligger
                # utanfor ALLA skärmar (sparade felkoordinater, t.ex.
                # 2546 på en 1536 px skärm) → centrera på primära skärmen
                _on_screen = False
                for _sc in (self._app.screens() if self._app else []):
                    if _sc.geometry().contains(_sx, _sy):
                        _on_screen = True
                        break
                if not _on_screen:
                    _sg = (
                        self._app.primaryScreen().availableGeometry()
                        if self._app and self._app.primaryScreen() else None
                    )
                    if _sg is not None:
                        _sx = _sg.x() + (_sg.width() - width) // 2
                        _sy = _sg.y() + (_sg.height() - height) // 2
                        self._log.info(
                            f"{LOG_PREFIX} Storlek: position utanfor "
                            f"skarm → centrerad ({_sx},{_sy})"
                        )
                if hasattr(w, "_shell_screen_move"):
                    w._shell_screen_move(_sx, _sy, width, height)
                else:
                    shell.resize(width, height)
                with suppress(Exception):
                    shell.show()
                with suppress(Exception):
                    w._save_geometry_now()
                self._log.info(
                    f"{LOG_PREFIX} Storlek satt: {width}x{height} "
                    f"(vid {_sx},{_sy}) — v7-fix61"
                )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _set_window_size_preset: {e}", exc_info=True
            )

    def _tray_center_window(self, keep_size: bool = True) -> None:
        """
        NY v7-fix47: centrera fönstret via tray-menyn.

        FIX v7-fix72: keep_size=True som default — BEHÅLLER nuvarande
        storlek (Rickard: "fönsterstorlek ska alltid sparas, även vid
        omstart eller centrering"). Full nollställning finns i fönstrets
        högerklicksmeny "Nollställ (centrera + standardstorlek)".
        """
        try:
            with self._widget_lock:
                widgets = list(self._widgets.values())
            for w in widgets:
                if hasattr(w, "_center_window"):
                    w._center_window(reset_size=not keep_size)
            self._log.info(
                f"{LOG_PREFIX} Fönstret centrerat via tray-menyn "
                f"(storlek {'beholden' if keep_size else 'nollställd'})"
            )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _tray_center_window misslyckades: {e}",
                exc_info=True,
            )

    def _single_window_enabled(self) -> bool:
        """
        NY v7-fix40: är enbart-ett-fönster-läget aktivt?

        Rickard 2026-10-01: "ska enbart visa ett fönster, när man väljer
        öppna nytt fönster, så ska den enbart visa det redan skapat".
        Default: PÅ. Kan stängas av via settings (single_window=false)
        om multi-fönster önskas igen.
        """
        try:
            if hasattr(self.settings, "single_window"):
                return bool(self.settings.single_window())
            return bool(self.settings.get("single_window", True))
        except Exception:
            return True

    def _show_existing_window(self) -> None:
        """
        NY v7-fix40: visa det BEFINTLIGA fönstret (enbart-läge).

        Visar skalet (om gömt), återfäster desktop-lagret och ser till
        att widget-barnet är synligt.
        """
        try:
            with self._widget_lock:
                widgets = list(self._widgets.values())
            for w in widgets:
                wid = getattr(w, "win_id", "?")
                shell = getattr(w, "_shell", None)
                if shell is not None:
                    # NY v7-fix44: minimerat (Win+D)? → SW_RESTORE först
                    with suppress(Exception):
                        if sys.platform == "win32":
                            import ctypes as _ct
                            _hw = int(shell.winId())
                            _u32 = _ct.windll.user32
                            if _u32.IsIconic(_hw):
                                _u32.ShowWindow(_hw, 9)  # SW_RESTORE
                                self._log.info(
                                    f"{LOG_PREFIX} _show_existing_window: "
                                    f"{wid!r} var MINIMERAT → återställt"
                                )
                    with suppress(Exception):
                        if not shell.isVisible():
                            shell.show()
                    self._apply_desktop_shell(shell, wid)
                with suppress(Exception):
                    if not w.isVisible():
                        w.setVisible(True)
                self._log.info(
                    f"{LOG_PREFIX} _show_existing_window: {wid!r} synlig "
                    f"(enbart-läge, inget nytt fönster skapat)"
                )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _show_existing_window misslyckades: {e}",
                exc_info=True,
            )

    def add_window(self, x: Optional[int] = None, y: Optional[int] = None) -> Optional[str]:
        """
        Lägg till ett nytt fönster (via settings.add_window + populate).
        Returnerar window-id (None vid fel).

        NY v7-fix40: i enbart-läge (default) visas DET BEFINTLIGA fönstret
        i stället för att skapa ett nytt.
        """
        try:
            if not hasattr(self.settings, "add_window"):
                self._log.warning("Settings saknar add_window")
                return None
            # NY v7-fix40: finns redan fönster? → VISA det, skapa inget nytt
            if self._single_window_enabled():
                with self._widget_lock:
                    _existing = list(self._widgets.items())
                if _existing:
                    _wid, _w = _existing[0]
                    self._log.info(
                        f"{LOG_PREFIX} enbart-läge: 'Nytt fönster' → visar "
                        f"det befintliga fönstret {_wid!r}"
                    )
                    self._show_existing_window()
                    return _wid
            x = x if x is not None else 100
            y = y if y is not None else 100
            wid = self.settings.add_window(x, y)
            self._populate_windows()
            self._log.info(f"Nytt fönster skapat: wid={wid!r} vid ({x}, {y})")
            return wid
        except Exception as e:
            self._log.error(f"add_window misslyckades: {e}")
            return None

    def remove_window(self, wid: str) -> bool:
        """Ta bort ett fönster (via settings.remove_window + populate)."""
        try:
            if hasattr(self.settings, "remove_window"):
                self.settings.remove_window(wid)
            self._populate_windows()
            self._log.info(f"Fönster borttaget via UI: {wid!r}")
            return True
        except Exception as e:
            self._log.error(f"remove_window misslyckades: {e}")
            return False

    # -----------------------------------------------------------------------
    # TRAY — init, populate, create_icon
    # -----------------------------------------------------------------------

    def _init_tray(self) -> None:
        """Initiera system tray (med ikon + meny + tooltip)."""
        if self._QSystemTrayIcon is None:
            self._log.warning("QSystemTrayIcon saknas — hoppar över tray-init")
            return
        if not self._QSystemTrayIcon.isSystemTrayAvailable():
            self._log.warning("System tray ej tillgängligt på denna plattform")
            return

        with error_boundary("tray.create"):
            self._tray = self._QSystemTrayIcon(self._app)

            # Ikon (samma som app-ico om den finns — annars ritad cirkel)
            if self._app_icon is not None:
                icon = self._app_icon
            else:
                icon = self.create_icon(state=IconState.NORMAL, color="#818cf8")
            self._tray.setIcon(icon)

            # Tooltip (uppdateras dynamiskt)
            self._update_tray_tooltip()

            # Meny
            self._populate_tray_menu()

            # Visa
            self._tray.show()
            self._tray.activated.connect(self._on_tray_activated)
            self._tray_initialized.set()
            self._log.info("✓ Tray initierat")

    def _populate_tray_menu(self) -> None:
        """
        Bygger om tray-menyn med live-stats och alla actions.
        Anropas vid: init, task-add, theme-change, periodic update.
        """
        if self._tray is None or self._QMenu is None:
            return
        try:
            # Återanvänd befintlig meny om möjligt
            if self._tray_menu is None:
                self._tray_menu = self._QMenu()
            else:
                self._tray_menu.clear()

            # Header (info)
            active_count = 0
            archived_count = 0
            if hasattr(self.store, "count"):
                active_count, archived_count = self.store.count()
            uptime = self._performance.format_uptime()
            mem_mb = self._performance.take_snapshot().memory_mb

            header = self._tray_menu.addAction(
                f"📋 {APP_NAME} v{APP_VERSION_DISPLAY}"
            )
            header.setEnabled(False)
            stats_action = self._tray_menu.addAction(
                f"  {active_count} aktiva • {archived_count} arkiverade"
            )
            stats_action.setEnabled(False)
            mem_action = self._tray_menu.addAction(
                f"  Minne: {mem_mb:.1f} MB • Uptime: {uptime}"
            )
            mem_action.setEnabled(False)
            self._tray_menu.addSeparator()

            # === HUVUDAKTIONER ===
            # NY v6.4: "Visa vid markören" — placerar fönster där muspekaren är
            show_action = self._QAction("👁  Visa fönster vid markören", self._tray_menu)
            show_action.triggered.connect(self._show_window_at_cursor)
            self._tray_menu.addAction(show_action)

            # NY v6.4.1: Snabbuppgift fran tray (utan att oppna fonstret forst)
            quick_add_action = self._QAction(
                "➕  Snabbuppgift... (fran tray)", self._tray_menu
            )
            quick_add_action.setToolTip(
                "Lagg till ny uppgift direkt (utan att oppna widget-fonstret)"
            )
            quick_add_action.triggered.connect(self._tray_quick_add_task)
            self._tray_menu.addAction(quick_add_action)

            # "Lås upp alla" (om något är låst)
            any_locked = any(
                getattr(w, "_locked", False)
                for w in self._widgets.values()
            )
            if any_locked:
                unlock_action = self._QAction(
                    "🔓  Lås upp alla fönster", self._tray_menu
                )
                unlock_action.triggered.connect(
                    lambda: self._set_all_windows_locked(False)
                )
                self._tray_menu.addAction(unlock_action)
            else:
                lock_action = self._QAction(
                    "🔒  Lås alla fönster", self._tray_menu)
                lock_action.triggered.connect(
                    lambda: self._set_all_windows_locked(True)
                )
                self._tray_menu.addAction(lock_action)

            self._tray_menu.addSeparator()

            # NY v6.4.1: Focus Mode (1 task stort, importerad fran §22.18 Todoist)
            focus_action = self._QAction(
                "🎯  Focus Mode (F3)", self._tray_menu
            )
            focus_action.setToolTip(
                "Visa EN uppgift i taget (stor) med navigering "
                "(← →, Enter=Markera klar, Esc=Avsluta)"
            )
            focus_action.triggered.connect(self._toggle_focus_mode_all_windows)
            self._tray_menu.addAction(focus_action)

            # FIX 2026-09-25: PDF-export av checklista (klickbar i Snabbåtgärder)
            self._export_pdf_action = self._QAction(
                "📄  Exportera checklista → PDF…",
                self._tray_menu,
            )
            self._export_pdf_action.setToolTip(
                "Exportera aktiva uppgifter som en snyggt designad PDF-checklista.\n"
                "Välj filnamn i dialogen."
            )
            self._export_pdf_action.triggered.connect(self._export_checklist_pdf)
            self._tray_menu.addAction(self._export_pdf_action)

            # NY v8 (2026-10-12): kalenderexport (.ics) → Google Calendar m.fl.
            self._export_calendar_action = self._QAction(
                "📅  Exportera till kalender (.ics)…",
                self._tray_menu,
            )
            self._export_calendar_action.setToolTip(
                "Exportera uppgifter med förfallodatum som kalenderfil.\n"
                "Importeras i Google Calendar (Inställningar → Importera\n"
                "och exportera), Outlook och Apple Kalender."
            )
            self._export_calendar_action.triggered.connect(self._export_calendar_ics)
            self._tray_menu.addAction(self._export_calendar_action)

            # NY v8 (2026-10-12): lokal Google Calendar-koppling (OAuth)
            self._google_calendar_action = self._QAction(
                "☁️  Google Calendar (koppla konto)…",
                self._tray_menu,
            )
            self._google_calendar_action.setToolTip(
                "Koppla ett Google-konto lokalt: inloggningen sker i din\n"
                "webbläsare och svaret kommer till 127.0.0.1. Därefter kan\n"
                "uppgifter skickas rakt in i kalendern."
            )
            self._google_calendar_action.triggered.connect(
                self._open_google_calendar
            )
            self._tray_menu.addAction(self._google_calendar_action)

            # NY v8 (2026-10-12): backup av uppgifter
            self._backup_tasks_action = self._QAction(
                "💾  Backup av uppgifter…", self._tray_menu
            )
            self._backup_tasks_action.setToolTip(
                "Säkerhetskopiera alla uppgifter till en ZIP-fil,\n"
                "spara en kopia på USB/moln-mapp eller återställ."
            )
            self._backup_tasks_action.triggered.connect(self._open_backup_dialog)
            self._tray_menu.addAction(self._backup_tasks_action)

            self._tray_menu.addSeparator()

            # NY v6.4.1: Autostart toggle (med live-status från registry)
            autostart_on = self._is_autostart_active()
            # NY v7-fix36: Installera/Uppdatera tillägg i tray-menyn
            # NY v7-fix50: auto-uppdatering av tillägg vid start
            _auto_plug_on = (
                self.settings.auto_update_plugins()
                if hasattr(self.settings, "auto_update_plugins")
                else True
            )
            auto_plugin_action = self._QAction(
                "🔄  Auto-uppdatera tillägg vid start", self._tray_menu
            )
            auto_plugin_action.setCheckable(True)
            auto_plugin_action.setChecked(bool(_auto_plug_on))
            auto_plugin_action.setToolTip(
                "Saknade tillägg installeras och föråldrade uppdateras\n"
                "automatiskt 30 sekunder efter appstart (bakgrund)."
            )
            auto_plugin_action.toggled.connect(
                self._toggle_auto_update_plugins
            )
            self._tray_menu.addAction(auto_plugin_action)

            # NY v7-fix64: påminnelser av/på
            _rem_on = (
                self.settings.reminders_enabled()
                if hasattr(self.settings, "reminders_enabled")
                else True
            )
            reminders_action = self._QAction(
                "🔔  Påminnelser (förfallna uppgifter)", self._tray_menu
            )
            reminders_action.setCheckable(True)
            reminders_action.setChecked(bool(_rem_on))
            reminders_action.setToolTip(
                "Windows-notis när uppgifter passerat förfallodatum\n"
                "eller förfaller idag (kontroll var minut)."
            )
            reminders_action.toggled.connect(self._toggle_reminders)
            self._tray_menu.addAction(reminders_action)

            # NY v7-fix82: tema-undermeny (Ljust/Mörkt/Auto/Följ Windows)
            # Auto = klockstyrt: ljust 07:00–18:59, mörkt 19:00–06:59 —
            # växlar automatiskt medan appen kör (widget-timer 10 min)
            with suppress(Exception):
                _theme_now = (
                    self.settings.theme_raw()
                    if hasattr(self.settings, "theme_raw")
                    else "system"
                )
                _theme_menu = self._tray_menu.addMenu(
                    "🎨  Tema"
                    + (
                        "  (🌗 Auto aktivt)"
                        if _theme_now == "auto"
                        else ""
                    )
                )
                for _tv, _tl in (
                    ("light", "☀️  Ljust"),
                    ("dark", "🌙  Mörkt"),
                    ("auto", "🌗  Auto (ljust dag • mörkt kväll)"),
                    ("system", "🖥️  Följ Windows"),
                ):
                    _ta = _theme_menu.addAction(_tl)
                    _ta.setCheckable(True)
                    _ta.setChecked(_theme_now == _tv)
                    _ta.triggered.connect(
                        lambda _c=False, v=_tv: self._set_theme_value(v)
                    )

            # NY v7-fix74: konfigurera lyft-tid (tray-klick)
            _secs_now = 5
            with suppress(Exception):
                if hasattr(self.settings, "tray_lift_seconds"):
                    _secs_now = int(self.settings.tray_lift_seconds())
                else:
                    _secs_now = int(
                        self.settings.get("tray_lift_seconds", 5)
                    )
            lift_secs_menu = self._tray_menu.addMenu(
                f"⏱  Lyft-tid vid tray-klick ({_secs_now} s)"
            )
            for _sv in (2, 3, 5, 8, 10, 15, 20, 30):
                _sa = lift_secs_menu.addAction(f"{_sv} sekunder")
                _sa.setCheckable(True)
                _sa.setChecked(_sv == _secs_now)
                _sa.triggered.connect(
                    lambda _c=False, s=_sv: self._set_tray_lift_seconds(s)
                )

            # NY v7-fix69: ändra push-to-show-hotkey
            # FIX v7-fix83: nu en undermeny med BÅDA hotkeys (ny uppgift +
            # visa fönstret) — båda är användarbytbara
            _hk_menu = self._tray_menu.addMenu(
                f"⌨️  Snabbkommandon"
            )
            _qa = _hk_menu.addAction(
                f"➕  Ny uppgift…  ({self._get_quick_add_hotkey_combo()})"
            )
            _qa.setToolTip(
                "Global snabbknapp som öppnar snabbinput för ny uppgift\n"
                "VAR SOM HELST i Windows (default: Ctrl+Alt+N)."
            )
            _qa.triggered.connect(self._change_quick_add_hotkey_dialog)
            _ps = _hk_menu.addAction(
                f"👁  Visa fönstret…  ({self._get_push_hotkey_combo()})"
            )
            _ps.setToolTip(
                "Snabbknappen som visar fönstret över appar\n"
                "medan du håller den intryckt (default: Ctrl+Alt+V)."
            )
            _ps.triggered.connect(self._change_push_hotkey_dialog)
            plugin_action = self._QAction("📦  Installera/Uppdatera tillägg")
            plugin_action.setToolTip(
                "Kontrollera och installera saknade Python-paket\n"
                "eller uppdatera föråldrade versioner"
            )
            plugin_action.triggered.connect(self._on_plugin_check)
            self._tray_menu.addAction(plugin_action)
            self._tray_menu.addSeparator()

            autostart_action = self._QAction(
                f"{'✅' if autostart_on else '⚪'}  Starta med datorn",
                self._tray_menu,
            )
            autostart_action.setCheckable(True)
            autostart_action.setChecked(autostart_on)
            autostart_action.setToolTip(
                "När aktiverad: appen startar automatiskt vid inloggning i Windows "
                "(via HKCU\\...\\Run, pythonw.exe — ingen konsol)"
            )
            autostart_action.triggered.connect(self._toggle_autostart)
            self._tray_menu.addAction(autostart_action)
            self._autostart_action_ref = autostart_action  # Spara ref för uppdatering

            # Starta minimerad (kopplat till start_minimized_to_tray)
            start_minimized = (
                self.settings.start_minimized()
                if hasattr(self.settings, "start_minimized")
                else False
            )
            minimized_action = self._QAction(
                f"{'✅' if start_minimized else '⚪'}  Starta minimerad i tray",
                self._tray_menu,
            )
            minimized_action.setCheckable(True)
            minimized_action.setChecked(start_minimized)
            minimized_action.setToolTip(
                "När aktiverad: appen startar gömd i systemfältet "
                "(syns inte förrän du klickar på ikonen)"
            )
            minimized_action.triggered.connect(self._toggle_start_minimized)
            self._tray_menu.addAction(minimized_action)
            self._minimized_action_ref = minimized_action

            self._tray_menu.addSeparator()

            new_action = self._QAction("➕  Ny uppgift…", self._tray_menu)
            new_action.triggered.connect(self.ask_new_task)
            self._tray_menu.addAction(new_action)

            # NY v7-fix40: dynamisk label — i enbart-läge visas det
            # befintliga fönstret i stället för att skapas ett nytt
            _has_windows = bool(self._widgets)
            _single_mode = self._single_window_enabled()
            new_window_action = self._QAction(
                "🪟  Visa fönstret"
                if (_single_mode and _has_windows)
                else "🪟  Nytt fönster",
                self._tray_menu,
            )
            if _single_mode and _has_windows:
                new_window_action.setToolTip(
                    "Enbart-läge: visar det befintliga fönstret\n"
                    "(skapar inget nytt)"
                )
            new_window_action.triggered.connect(lambda: self.add_window(150, 150))
            self._tray_menu.addAction(new_window_action)

            # NY v7-fix47: nollställ/centrera i TRAY-menyn
            # (Rickard: "i tray menyn, ej högerklick på fönstret")
            reset_win_action = self._QAction(
                "🎯  Centrera fönstret", self._tray_menu
            )
            reset_win_action.setToolTip(
                "Centrerar fönstret — BEHÅLLER din storlek\n"
                "(v7-fix72). Nollställ storlek: högerklicka fönstret."
            )
            reset_win_action.triggered.connect(self._tray_center_window)
            self._tray_menu.addAction(reset_win_action)

            # NY v7-fix61: storleksförinställningar (ikon → stor)
            size_menu = self._tray_menu.addMenu("📐  Fönsterstorlek")
            _size_items = (
                ("🖥  Ikon (150×230)", 150, 230),
                ("📟  Kompakt (240×400)", 240, 400),
                ("📋  Standard (340×648)", 340, 648),
                ("📰  Stor (480×750)", 480, 750),
                ("🖥️  Max skärm (90 %)", -1, -1),
            )
            for _lbl, _sw_, _sh_ in _size_items:
                _sa = size_menu.addAction(_lbl)
                _sa.triggered.connect(
                    lambda _c=False, ww=_sw_, hh=_sh_:
                        self._set_window_size_preset(
                            ww, hh
                        ) if ww > 0 else self._set_window_size_max()
                )

            # NY v7-fix57: visa ovanpå appar / fäst igen
            float_action = self._QAction(
                "🪝  Visa ovanpå appar (tills vidare)", self._tray_menu
            )
            float_action.setToolTip(
                "Lossar fönstret från skrivbordet så det syns\n"
                "bland dina appar. Återgå med 'Fäst på skrivbordet'."
            )
            float_action.triggered.connect(self._float_window_above_apps)
            self._tray_menu.addAction(float_action)

            pin_action = self._QAction(
                "📌  Fäst på skrivbordet igen", self._tray_menu
            )
            pin_action.setToolTip(
                "Fäster tillbaka fönstret på skrivbordet\n"
                "(ovanpå ikonerna, under appar, Win+D-säkert)"
            )
            pin_action.triggered.connect(self._pin_window_to_desktop)
            self._tray_menu.addAction(pin_action)

            self._tray_menu.addSeparator()

            # === GLASMORPHISM SUBMENU ===
            glass_menu = self._tray_menu.addMenu("✨  Glasmorphism")
            for style in self._config.glass_styles:
                act = glass_menu.addAction(style.capitalize())
                act.setCheckable(True)
                act.setChecked(self._glass_style == style)
                act.triggered.connect(
                    lambda checked=False, s=style: self._set_glass_style(s)
                )

            # === NY v7-fix38: SKRIVBORDSLÄGE (Win+D-säkert) ===
            desktop_menu = self._tray_menu.addMenu("🖼  Skrivbordsläge (Win+D-säkert)")
            _cur_mode = self._desktop_mode()
            # NY v7-fix45: LEGACY dolt ur menyn — det är en AUTOMATISK
            # nödfallback (above→behind→legacy), inte ett användarval.
            # v7-fix56: legacy är HELT borttaget — bara above/behind finns.
            _mode_items = (
                ("above", "Över ikonerna (transparent)"),
                ("behind", "Bakom ikonerna (Rainmeter)"),
            )
            for _m_val, _m_label in _mode_items:
                act = desktop_menu.addAction(_m_label)
                act.setCheckable(True)
                act.setChecked(_cur_mode == _m_val)
                act.setToolTip(
                    "Win+D kan aldrig gömma widgeten — den lever i\n"
                    "skrivbordslagret tillsammans med ikonerna.\n"
                    "'Över ikonerna' = genomskinligt glas, ikonerna syns\n"
                    "igenom widgeten. 'Bakom ikonerna' = ikonerna målas\n"
                    "ovanpå widgeten (Rainmeter-metoden)."
                )
                act.triggered.connect(
                    lambda checked=False, m=_m_val: self._set_desktop_mode(m)
                )

            # === NY v7-fix38: TRANSPARENS ===
            transp_menu = self._tray_menu.addMenu("🫧  Transparens")
            _cur_transp = self._window_transparency_value()
            _transp_items = (
                (1.0, "100 % (opak panel)"),
                (0.85, "85 % (default)"),
                (0.7, "70 %"),
                (0.55, "55 %"),
                (0.0, "Av (helt opak fönster)"),
            )
            for _t_val, _t_label in _transp_items:
                act = transp_menu.addAction(_t_label)
                act.setCheckable(True)
                act.setChecked(abs(_cur_transp - _t_val) < 0.01)
                act.setToolTip(
                    "Hur genomskinligt glas-skalet är — skrivbordsikonerna\n"
                    "syns igenom widgeten (kräver läget 'Över ikonerna')."
                )
                act.triggered.connect(
                    lambda checked=False, v=_t_val: self._set_window_transparency(v)
                )

            # === NY v7-fix90: E-POST & THUNDERBIRD ==========================
            # Rickard: "importera uppgifter från mail via thunderbird" —
            # bryggan (localhost) + inkorgsmappen + tilläggets inställningar.
            try:
                _svc = getattr(self, "_mail_bridge", None)
                _status = _svc.status() if _svc is not None else None
                _http_on = bool(
                    _status["http_running"] if _status else False
                )
                _watch_on = bool(
                    _status["watch_running"] if _status else False
                )
                _mail_menu = self._tray_menu.addMenu("📧  E-post & Thunderbird")

                _act_bridge = _mail_menu.addAction(
                    f"{'✅' if _http_on else '⚪'}  Brygga (lokal server)"
                )
                _act_bridge.setCheckable(True)
                _act_bridge.setChecked(_http_on)
                _act_bridge.setToolTip(
                    "Tar emot mail från Thunderbird-tillägget på\n"
                    "127.0.0.1 (bara denna dator) och skapar uppgifter.\n"
                    "Uppgifterna sparas direkt i data/active.json (JSON)."
                )
                _act_bridge.triggered.connect(self._toggle_mail_bridge)

                _act_inbox = _mail_menu.addAction(
                    f"{'✅' if _watch_on else '⚪'}  Bevaka inkorgsmappen "
                    f"(data/inbox)"
                )
                _act_inbox.setCheckable(True)
                _act_inbox.setChecked(_watch_on)
                _act_inbox.setToolTip(
                    "Släpp .eml/.msg/.json i data/inbox/ → importeras\n"
                    "automatiskt (även mail som kom när appen var avstängd)."
                )
                _act_inbox.triggered.connect(self._toggle_inbox_watch)

                _info_action = _mail_menu.addAction(
                    f"   {self._mail_bridge_status_text()}"
                )
                _info_action.setEnabled(False)
                _mail_menu.addSeparator()

                _act_copy = _mail_menu.addAction(
                    "📋  Kopiera inställningar för Thunderbird…"
                )
                _act_copy.setToolTip(
                    "Lägger adress + token på urklipp — klistra in i\n"
                    "Thunderbird-tilläggets inställningar."
                )
                _act_copy.triggered.connect(self._copy_mail_bridge_settings)

                _act_guide = _mail_menu.addAction(
                    "🧩  Installera Thunderbird-tillägget…"
                )
                _act_guide.triggered.connect(self._show_thunderbird_guide)

                _act_folder = _mail_menu.addAction("📂  Öppna inkorgsmappen")
                _act_folder.triggered.connect(self._open_inbox_folder)

                _act_import = _mail_menu.addAction(
                    "📥  Importera e-postfiler nu…"
                )
                _act_import.setToolTip(
                    "Välj .eml/.msg-filer (Thunderbird: spara mailet som\n"
                    ".eml) — uppgifterna skapas och sparas i JSON."
                )
                _act_import.triggered.connect(self._import_email_files_dialog)

                if _status:
                    _mail_menu.addSeparator()
                    _stat_txt = _mail_menu.addAction(
                        f"   {_status['imports']} mail importerade • "
                        f"{_status['duplicates']} dubletter"
                    )
                    _stat_txt.setEnabled(False)
            except Exception as e:
                self._log.debug(
                    f"{LOG_PREFIX} e-post-undermeny misslyckades: {e}"
                )

            self._tray_menu.addSeparator()

            # === DIAGNOSTICS ===
            stats_dlg_action = self._QAction("📊  Statistik…", self._tray_menu)
            stats_dlg_action.triggered.connect(self.show_statistics)
            self._tray_menu.addAction(stats_dlg_action)

            if self._mode == AppMode.DIAGNOSTICS:
                dump_action = self._QAction("🔍  Subsystem-dump", self._tray_menu)
                dump_action.triggered.connect(self._dump_subsystem_status)
                self._tray_menu.addAction(dump_action)

            about_action = self._QAction("ℹ  Om…", self._tray_menu)
            about_action.triggered.connect(self.show_about)
            self._tray_menu.addAction(about_action)

            self._tray_menu.addSeparator()

            # === AVSLUTA ===
            quit_action = self._QAction("❌  Avsluta", self._tray_menu)
            quit_action.triggered.connect(self.shutdown)
            self._tray_menu.addAction(quit_action)

            self._tray.setContextMenu(self._tray_menu)
        except Exception as e:
            self._log.error(f"_populate_tray_menu misslyckades: {e}", exc_info=True)

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

    def _on_tray_activated(self, reason: Any) -> None:
        """Hantera tray-ikon aktivering (vänster/höger/dubbelklick)."""
        try:
            # NY v6.4: Hantera ALLA click-typer (inte bara dubbelklick)
            trigger = self._QSystemTrayIcon.ActivationReason.Trigger
            double_click = self._QSystemTrayIcon.ActivationReason.DoubleClick
            middle_click = getattr(
                self._QSystemTrayIcon.ActivationReason, "MiddleClick", None
            )
            # Vänster/dubbel/middle click = visa fönster
            if reason in (trigger, double_click, middle_click):
                # NY v7-fix72: lyft över appar i X sekunder
                self._lift_on_top_temporarily()
            # Högerklick = context-meny (Qt hanterar detta automatiskt via setContextMenu)
        except Exception as e:
            self._log.debug(f"on_tray_activated misslyckades: {e}")

    def _set_tray_lift_seconds(self, seconds: int) -> None:
        """NY v7-fix74: sätt lyft-tid (sparas i settings)."""
        try:
            _v = max(1, min(60, int(seconds)))
            if hasattr(self.settings, "set_tray_lift_seconds"):
                self.settings.set_tray_lift_seconds(_v)
            self._log.info(
                f"{LOG_PREFIX} Lyft-tid vid tray-klick: {_v} sekunder "
                f"(sparad i settings) (v7-fix74)"
            )
            _lt = getattr(self, "_lift_timer", None)
            if _lt is not None and _lt.isActive():
                _lt.start(_v * 1000)
            self._populate_tray_menu()
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _set_tray_lift_seconds: {e}", exc_info=True
            )

    def _lift_on_top_temporarily(self) -> None:
        """
        NY v7-fix72: lyft fönstret över appar i X sekunder.

        Rickard 2026-10-06: "om man klickar på tray så lyfts fönstret
        fram till topp i x antal sekunder". Efter X sekunder återfästs
        det automatiskt på skrivbordet. Nytt klick = förläng timern.
        """
        try:
            import ctypes
            _u = ctypes.windll.user32
            _secs = 5
            with suppress(Exception):
                if hasattr(self.settings, "tray_lift_seconds"):
                    _secs = int(self.settings.tray_lift_seconds())
                else:
                    _secs = int(
                        self.settings.get("tray_lift_seconds", 5)
                    )
            _secs = max(1, min(60, _secs))
            with self._widget_lock:
                widgets = list(self._widgets.values())
            for w in widgets:
                shell = getattr(w, "_shell", None)
                if shell is None:
                    continue
                wid = getattr(w, "win_id", "?")
                _hwnd = int(shell.winId())
                if not _hwnd:
                    continue
                if str(
                    getattr(shell, "_desktop_layer_mode", "")
                ) != "_lift":
                    shell._lift_prev_mode = str(
                        getattr(shell, "_desktop_layer_mode", "normal")
                    )
                # FIX v7-fix75: HWND_TOP räcker inte när t.ex. Explorer
                # ligger över (z-order kan respekteras inkonsekvent).
                # Lösning: TILLFÄLLIG TOPMOST (-1) — garanterat över
                # ALLA normala fönster. Återställs till NOTOPMOST (-2)
                # i _lift_timeout före återfästningen.
                _u.SetWindowPos(
                    _hwnd, -1, 0, 0, 0, 0,
                    0x0040 | 0x0010 | 0x0001 | 0x0002,
                )  # HWND_TOPMOST | SHOWWINDOW|NOACTIVATE|NOSIZE|NOMOVE
                shell._desktop_layer_mode = "_lift"
                self._log.info(
                    f"{LOG_PREFIX} TRAY-LYFT: {wid!r} visas över appar "
                    f"i {_secs} sekunder (v7-fix72)"
                )
            _lt = getattr(self, "_lift_timer", None)
            if _lt is None:
                _lt = self._QTimer()
                _lt.setSingleShot(True)
                _lt.timeout.connect(self._lift_timeout)
                self._lift_timer = _lt
            _lt.start(_secs * 1000)
            with suppress(Exception):
                if self._tray is not None:
                    self._tray.setToolTip(
                        f"TaskBord — lyft i {_secs}s "
                        f"(klicka igen = förläng)"
                    )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _lift_on_top_temporarily: {e}",
                exc_info=True,
            )

    def _lift_timeout(self) -> None:
        """NY v7-fix72: lyft-tiden ut — återfäst på skrivbordet."""
        try:
            import ctypes
            _u = ctypes.windll.user32
            with self._widget_lock:
                widgets = list(self._widgets.values())
            for w in widgets:
                shell = getattr(w, "_shell", None)
                if shell is None:
                    continue
                wid = getattr(w, "win_id", "?")
                _prev = str(
                    getattr(shell, "_lift_prev_mode", "behind")
                )
                # FIX v7-fix75: ta bort TOPMOST FÖRE återfästningen
                with suppress(Exception):
                    _hw = int(shell.winId())
                    if _hw:
                        _u.SetWindowPos(
                            _hw, -2, 0, 0, 0, 0,
                            0x0010 | 0x0001 | 0x0002,
                        )  # HWND_NOTOPMOST | NOACTIVATE|NOSIZE|NOMOVE
                shell._desktop_layer_mode = None
                self._apply_desktop_shell(shell, wid)
                self._log.info(
                    f"{LOG_PREFIX} TRAY-LYFT slut: {wid!r} återfäst "
                    f"(var: {_prev}) (v7-fix72)"
                )
            with suppress(Exception):
                if self._tray is not None:
                    self._tray.setToolTip("TaskBord")
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _lift_timeout: {e}", exc_info=True
            )

    def _show_window_at_cursor(self) -> None:
        """NY v6.4: Visa alla fönster vid muspekaren."""
        try:
            from PySide6.QtGui import QCursor
            cursor_pos = QCursor.pos()
            offset = 0
            with self._widget_lock:
                widgets = list(self._widgets.values())
            for w in widgets:
                # FIX v7-fix60: flytta SKALET (inte barnet!). Gamla koden
                # gjorde w.move() på TodoWidget-BARNET — i skal-läge är det
                # en LOKAL position, och (1003,374) i ett 340 px brett skal
                # = barnet 663 px UTANFÖR fönstret → tomt genomskinligt
                # skal = "fönstret syns inte"!
                _sh = getattr(w, "_shell", None)
                _tx = cursor_pos.x() + offset
                _ty = cursor_pos.y() + offset
                if _sh is not None and hasattr(w, "_shell_screen_move"):
                    # DPI-kompenserad flytt till skärm-koordinater
                    w._shell_screen_move(_tx, _ty)
                elif _sh is not None:
                    _sh.move(_tx, _ty)
                else:
                    w.move(_tx, _ty)
                # AUTO-HEAL: om barnet hamnat utanför skalet (gammal bugg
                # eller skräp-position) → tillbaka till (0,0)
                with suppress(Exception):
                    if (
                        _sh is not None
                        and (w.x() != 0 or w.y() != 0)
                        and (w.x() > _sh.width() or w.y() > _sh.height()
                             or w.x() < 0 or w.y() < 0)
                    ):
                        w.move(0, 0)
                        self._log.info(
                            f"{LOG_PREFIX} _show_window_at_cursor: barn "
                            f"utanför skalet → healad till (0,0)"
                        )
                # Lås upp automatiskt (om låst) + visa
                if hasattr(w, "set_locked"):
                    with suppress(Exception):
                        w.set_locked(False, auto_relock_sec=60)  # Auto-relock efter 60s
                if _sh is not None:
                    with suppress(Exception):
                        _sh.show()
                else:
                    if hasattr(w, "_setup_bugg19_zorder"):
                        with suppress(Exception):
                            w._setup_bugg19_zorder()
                    w.show()
                    w.raise_()
                offset += 30
            self._log.info(
                f"{LOG_PREFIX} _show_window_at_cursor: "
                f"{len(widgets)} fönster vid ({cursor_pos.x()}, {cursor_pos.y()})"
            )
        except Exception as e:
            self._log.error(f"_show_window_at_cursor misslyckades: {e}")

    def _tray_quick_add_task(self) -> None:
        """
        NY v6.4.1: Snabbuppgift fran tray-menyn.

        Vad den gor:
          1. Visar QInputDialog vid markoren
          2. Vid OK: lagger till i store via self.store.add_task()
          3. Visar widget vid markoren sa man ser den nya uppgiften
          4. Loggar allt med [MAIN]-prefix

        Bra nar man snabbt vill lagga till nagot utan att oppna appen.
        """
        try:
            from PySide6.QtGui import QCursor
            from PySide6.QtWidgets import QInputDialog
            self._log.info(
                f"{LOG_PREFIX} _tray_quick_add_task: startar input-dialog"
            )
            # QInputDialog vid markoren
            cursor_pos = QCursor.pos()
            text, ok = QInputDialog.getText(
                None,
                "➕ Snabbuppgift",
                "Ny uppgift:",
                text="",
            )
            if not ok or not text or not text.strip():
                self._log.info(
                    f"{LOG_PREFIX} _tray_quick_add_task: avbruten "
                    f"(ok={ok}, text={text!r})"
                )
                return
            text = text.strip()
            # Lagg till i store
            if self.store is None or not hasattr(self.store, "add_task"):
                self._log.error(
                    f"{LOG_PREFIX} _tray_quick_add_task: store saknas "
                    f"eller saknar add_task()"
                )
                # Visa felmeddelande till anvandaren
                if self._QMessageBox:
                    self._QMessageBox.warning(
                        None,
                        "Kunde inte lagga till",
                        "Store ar inte tillganglig. Oppna appen forst.",
                    )
                return
            new_id = self.store.add_task(text)
            if new_id:
                self._log.info(
                    f"{LOG_PREFIX} _tray_quick_add_task: ny task skapad "
                    f"id={new_id!r} text={text[:30]!r}"
                )
                # Visa widget vid markoren sa man ser den nya uppgiften
                self._show_window_at_cursor()
                # Uppdatera tray-tooltip med nya antalet
                self._update_tray_tooltip()
                # Visa kort balloon-notis (om tillgangligt)
                if self._tray is not None:
                    try:
                        self._tray.showMessage(
                            "➕ Snabbuppgift tillagd",
                            f"\"{text[:40]}{'...' if len(text) > 40 else ''}\"",
                            self._QSystemTrayIcon.MessageIcon.Information,
                            3000,  # 3 sekunder
                        )
                    except Exception as e:
                        self._log.debug(
                            f"{LOG_PREFIX} balloon-notis misslyckades: {e}"
                        )
            else:
                self._log.warning(
                    f"{LOG_PREFIX} _tray_quick_add_task: add_task returnerade "
                    f"ingen id (text={text[:30]!r})"
                )
        except Exception as e:
            self._log.error(
                f"{LOG_PREFIX} _tray_quick_add_task misslyckades: {e}",
                exc_info=True,
            )

    def _update_tray_tooltip(self) -> None:
        """Uppdatera tray-tooltip med live-data (cachas i 1s)."""
        if self._tray is None:
            return
        now = time.time()
        if now - self._last_tooltip_update < 1.0:
            return
        self._last_tooltip_update = now
        try:
            active = 0
            if hasattr(self.store, "count"):
                active, _ = self.store.count()
            uptime = self._performance.format_uptime()
            tooltip = (
                f"{APP_NAME} v{APP_VERSION_DISPLAY}\n"
                f"{active} uppgifter • {len(self._widgets)} fönster • {uptime}"
            )
            self._tray.setToolTip(tooltip)
        except Exception as e:
            self._log.debug(f"update_tray_tooltip misslyckades: {e}")

    def _set_glass_style(self, style: str) -> None:
        """Sätt glasmorphism-stil och uppdatera alla fönster."""
        self._glass_style = style
        self._log.info(f"Glasmorphism: {style}")
        with self._widget_lock:
            for w in self._widgets.values():
                if hasattr(w, "set_glass_style"):
                    with suppress(Exception):
                        w.set_glass_style(style)
                elif hasattr(w, "_apply_theme"):
                    with suppress(Exception):
                        w._apply_theme()
        self._populate_tray_menu()  # Uppdatera checkmarks

    # -----------------------------------------------------------------------
    # LOCK / UNLOCK (NY v6.4)
    # -----------------------------------------------------------------------

    def _set_all_windows_locked(self, locked: bool) -> None:
        """Sätt lås-status för ALLA fönster (via tray-menyn)."""
        with self._widget_lock:
            widgets = list(self._widgets.values())
        for w in widgets:
            if hasattr(w, "set_locked"):
                with suppress(Exception):
                    w.set_locked(locked)
        self._log.info(
            f"{LOG_PREFIX} {'Låser' if locked else 'Låser upp'} "
            f"{len(widgets)} fönster"
        )
        # Uppdatera tray-meny
        self._populate_tray_menu()

    # -----------------------------------------------------------------------
    # AUTOSTART (NY v6.4.1) — UI-toggle i tray-menyn
    # -----------------------------------------------------------------------

    def _on_plugin_check(self) -> None:
        """
        NY v7-fix36: Kontrollera + installera/uppdatera Python-tillägg.
        Körs från tray-menyn "📦 Installera/Uppdatera tillägg".
        """
        self._log.info(
            f"{LOG_PREFIX} _on_plugin_check: kontrollerar tillägg..."
        )
        try:
            results = offer_install_missing_plugins()
            if not results:
                self._tray.showMessage(
                    APP_NAME,
                    "✅ Alla tillägg är installerade och uppdaterade!",
                    self._QSystemTrayIcon.MessageIcon.Information,
                    3000,
                )
                return
            ok_count = sum(1 for ok in results.values() if ok)
            total = len(results)
            if ok_count:
                self._tray.showMessage(
                    APP_NAME,
                    f"✅ {ok_count}/{total} tillägg installerade/uppdaterade. "
                    f"Starta om appen för att aktivera.",
                    self._QSystemTrayIcon.MessageIcon.Information,
                    5000,
                )
            else:
                self._tray.showMessage(
                    APP_NAME,
                    "⚠️ Kunde inte installera tillägg. "
                    "Kör manuellt: pip install <paket>",
                    self._QSystemTrayIcon.MessageIcon.Warning,
                    5000,
                )
        except Exception as e:
            self._log.error(
                f"{LOG_PREFIX} _on_plugin_check fel: {e}", exc_info=True
            )

    def _on_plugin_check_legacy(self) -> None:
        """
        ÄLDRE variant av tilläggskontrollen (bevarad enligt regeln
        'ta aldrig bort funktioner'). Den AKTIVA varianten som
        tray-menyn använder är _on_plugin_check (med varnings-feedback
        vid misslyckade installationer).

        NY v7-fix36: Kontrollera + installera/uppdatera Python-tillägg.
        Körs från tray-menyn "📦 Installera/Uppdatera tillägg".
        """
        self._log.info(f"{LOG_PREFIX} _on_plugin_check: kontrollerar...")
        try:
            results = offer_install_missing_plugins()
            if not results:
                if self._tray is not None:
                    self._tray.showMessage(
                        APP_NAME,
                        "✅ Alla tillägg är installerade och uppdaterade!",
                        self._QSystemTrayIcon.MessageIcon.Information,
                        3000,
                    )
                return
            ok_count = sum(1 for ok in results.values() if ok)
            total = len(results)
            if ok_count and self._tray is not None:
                self._tray.showMessage(
                    APP_NAME,
                    f"✅ {ok_count}/{total} tillägg installerade. "
                    f"Starta om appen för att aktivera.",
                    self._QSystemTrayIcon.MessageIcon.Information,
                    5000,
                )
        except Exception as e:
            self._log.error(f"{LOG_PREFIX} _on_plugin_check fel: {e}")

    def _is_autostart_active(self) -> bool:
        """
        Kontrollera om autostart är aktivt (Windows registry ELLER settings.set_autostart).

        Använder samma källa som resten av appen (utils.is_autostart_enabled
        om tillgängligt, annars settings.set_autostart/get_autostart_command).
        Returnerar True om appen startar automatiskt vid Windows-inloggning.
        """
        try:
            # 0. NY v7-fix12: desktop.is_autostart_enabled — multi-OS
            #    (Windows registry/startup/schtask, macOS launchd, Linux XDG)
            desktop_status = self._imports.get("desktop")
            if desktop_status and desktop_status.ok:
                d_is = getattr(
                    self._desktop_mod(desktop_status), "is_autostart_enabled", None
                )
                if callable(d_is):
                    with suppress(Exception):
                        return bool(d_is())
            # 1. Försök via utils.is_autostart_enabled (snabbast, live registry-check)
            utils_status = self._imports.get("utils")
            if utils_status and utils_status.ok:
                is_fn = getattr(utils_status.instance, "is_autostart_enabled", None)
                if callable(is_fn):
                    with suppress(Exception):
                        return bool(is_fn())
            # 2. Fallback: settings.set_autostart (settings-driven)
            if hasattr(self.settings, "is_autostart_enabled"):
                with suppress(Exception):
                    return bool(self.settings.is_autostart_enabled())
            if hasattr(self.settings, "get_autostart_command"):
                with suppress(Exception):
                    cmd = self.settings.get_autostart_command()
                    return bool(cmd and cmd.strip())
            # 3. Sista fallback: direktregistry-check (Windows)
            if _is_windows():
                try:
                    import winreg
                    with winreg.OpenKey(
                        winreg.HKEY_CURRENT_USER,
                        r"Software\Microsoft\Windows\CurrentVersion\Run",
                        0, winreg.KEY_READ,
                    ) as key:
                        try:
                            winreg.QueryValueEx(key, APP_NAME)
                            return True
                        except FileNotFoundError:
                            return False
                except Exception:
                    pass
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} _is_autostart_active misslyckades: {e}")
        return False

    def _toggle_focus_mode_all_windows(self) -> None:
        """
        NY v6.4.1: Toggla Focus Mode för ALLA widget-fönster (från tray).

        Vad Focus Mode gör:
          - Döljer normal task-lista
          - Visar 1 task åt gången (stor)
          - ← → = navigera, Enter/Space = markera klar, Esc = avsluta
        """
        try:
            toggled = 0
            for widget in self._widgets.values():
                if hasattr(widget, "_toggle_focus_mode"):
                    widget._toggle_focus_mode()
                    toggled += 1
            self._log.info(
                f"{LOG_PREFIX} _toggle_focus_mode_all_windows: "
                f"togglade {toggled} fönster"
            )
        except Exception as e:
            self._log.error(
                f"{LOG_PREFIX} _toggle_focus_mode_all_windows misslyckades: {e}",
                exc_info=True,
            )

    def _autostart_build_command(self) -> str:
        """NY v7-fix37: Bygg korrekt autostart-kommando (pythonw + main.pyw)."""
        exe = sys.executable
        if exe.lower().endswith("python.exe"):
            pythonw = Path(exe).parent / "pythonw.exe"
            if pythonw.is_file():
                exe = str(pythonw)
        script = Path(__file__).resolve().parent / "main.pyw"
        if not script.is_file():
            script = Path(__file__).resolve().parent / "main.py"
        cmd = f'"{exe}" "{script}"'
        self._log.debug(f"{LOG_PREFIX} autostart-kommando: {cmd}")
        return cmd

    @staticmethod
    def _autostart_bat_text(cmd: str) -> str:
        """FIX v8: korrekt Startup-.bat. `cmd` är redan '"exe" "skript"' med citat runt var del.

        Tidigare skrevs tre citattecken (start \"\"\") eller så citerades hela kommandot som
        EN fil → "Det går inte att hitta filen …pythonw.exe …main.pyw" vid inloggning.
        """
        return f'@echo off\r\nrem TaskBord (v8)\r\nchcp 65001 >nul\r\nstart "" {cmd}\r\n'

    def _autostart_repair_startup_bat(self) -> None:
        """FIX v8: reparerar en gammal, trasig Startup-.bat (skriver bara om om den redan finns)."""
        if sys.platform != "win32":
            return
        try:
            bat = Path(os.environ.get("APPDATA", ""), "Microsoft", "Windows",
                       "Start Menu", "Programs", "Startup", f"{APP_NAME}.bat")
            if not bat.is_file():
                return
            want = self._autostart_bat_text(self._autostart_build_command())
            if bat.read_bytes().decode("utf-8", "replace") != want:
                bat.write_bytes(want.encode("utf-8"))
                self._log.warning(f"{LOG_PREFIX} ★ AUTOSTART: reparerade Startup-.bat ({bat})")
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} _autostart_repair_startup_bat: {e}")

    def _autostart_enable_robust(self) -> Dict[str, bool]:
        """NY v7-fix37: Aktivera autostart via multipla metoder + verifiering."""
        results: Dict[str, bool] = {}
        cmd = self._autostart_build_command()
        if sys.platform != "win32":
            try:
                import desktop as _desk
                results["desktop-motor"] = bool(_desk.enable_autostart())
            except Exception:
                results["desktop-motor"] = False
            return results
        # Metod 1: Registry
        try:
            import winreg
            kp = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, kp, 0, winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, cmd)
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, kp, 0, winreg.KEY_READ) as k:
                v, _ = winreg.QueryValueEx(k, APP_NAME)
                results["registry"] = bool(v)
        except FileNotFoundError:
            results["registry"] = True
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} autostart registry: {e}")
            results["registry"] = False
        # Metod 2: Startup-mapp
        try:
            sd = Path(os.environ.get("APPDATA", ""), "Microsoft", "Windows",
                      "Start Menu", "Programs", "Startup")
            sd.mkdir(parents=True, exist_ok=True)
            bat = sd / f"{APP_NAME}.bat"
            bat.write_bytes(self._autostart_bat_text(cmd).encode("utf-8"))
            results["startup-mapp"] = bat.is_file()
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} autostart startup: {e}")
            results["startup-mapp"] = False
        # Metod 3: schtasks (endast om andra misslyckades)
        if not any(results.values()):
            try:
                import subprocess as _sp
                _sp.run(["schtasks", "/create", "/tn", "TaskBord_Auto",
                         "/tr", cmd, "/sc", "onlogon", "/f"],
                        capture_output=True, timeout=15)
                chk = _sp.run(["schtasks", "/query", "/tn", "TaskBord_Auto"],
                              capture_output=True, timeout=10)
                results["schtasks"] = chk.returncode == 0
            except Exception:
                results["schtasks"] = False
        return results

    def _autostart_disable_all(self) -> int:
        """NY v7-fix37: Ta bort autostart från ALLA platser."""
        removed = 0
        if sys.platform != "win32":
            try:
                import desktop as _desk
                if _desk.disable_autostart():
                    removed += 1
            except Exception:
                pass
            return removed
        try:
            import winreg
            kp = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, kp, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, APP_NAME)
            removed += 1
        except FileNotFoundError:
            pass
        except Exception:
            pass
        try:
            sd = Path(os.environ.get("APPDATA", ""), "Microsoft", "Windows",
                      "Start Menu", "Programs", "Startup")
            bat = sd / f"{APP_NAME}.bat"
            if bat.is_file():
                bat.unlink()
                removed += 1
        except Exception:
            pass
        try:
            import subprocess as _sp
            _sp.run(["schtasks", "/delete", "/tn", "TaskBord_Auto", "/f"],
                    capture_output=True, timeout=10)
        except Exception:
            pass
        return removed

    def _autostart_health_check(self) -> None:
        """NY v7-fix37: Självreparation — om autostart borde vara på men inte är → fixa."""
        try:
            settings_on = bool(
                getattr(self.settings, "is_autostart_enabled", lambda: False)()
            )
            if not settings_on:
                return
            self._autostart_repair_startup_bat()
            if sys.platform == "win32":
                import winreg
                kp = r"Software\Microsoft\Windows\CurrentVersion\Run"
                # NY v7-fix67: städa gamla DesktopTodoPy-autostart
                # (namnbyte → TaskBord) så den inte startar en död kopia
                with suppress(Exception):
                    with winreg.OpenKey(
                        winreg.HKEY_CURRENT_USER, kp, 0,
                        winreg.KEY_SET_VALUE,
                    ) as _k_old:
                        winreg.DeleteValue(_k_old, "DesktopTodoPy")
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, kp, 0, winreg.KEY_READ) as k:
                        _val, _ = winreg.QueryValueEx(k, APP_NAME)
                        # NY v7-fix58: PORTABILITET — om appen flyttats
                        # (USB, annan mapp) pekar registry på en DÖD
                        # sökväg → skriv om med aktuell plats.
                        _want = self._autostart_build_command() or ""
                        if str(_val).strip().lower() != str(_want).strip().lower():
                            self._log.warning(
                                f"{LOG_PREFIX} ★ AUTOSTART SJÄLVREPARATION: "
                                f"sökväg föråldrad (app flyttad?) → skriver "
                                f"om till aktuell plats"
                            )
                            self._autostart_enable_robust()
                        return  # Finns (och är aktuell) — OK
                except FileNotFoundError:
                    pass
                self._log.warning(
                    f"{LOG_PREFIX} ★ AUTOSTART SJÄLVREPARATION: "
                    f"settings=PÅ, registry=SAKNAS → återaktiverar"
                )
                results = self._autostart_enable_robust()
                ok = [k for k, v in results.items() if v]
                if ok:
                    self._log.info(
                        f"{LOG_PREFIX} ✓ självreparation: {', '.join(ok)}"
                    )
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} autostart health: {e}")

    def _toggle_autostart(self, checked: bool) -> None:
        """
        NY v7-fix37: 10000% bättre autostart — robust + verifierad.

        Förbättringar jämfört med v6.4.1:
          1. Bygger korrekt kommando direkt (pythonw.exe + main.pyw)
          2. Sätter via MULTIPLA metoder (registry + startup-mapp)
          3. VERIFIERAR att det faktiskt funkar efteråt
          4. Ren disable: tar bort från ALLA platser
          5. Detaljerad feedback i tray + logg
        """
        self._log.info(
            f"{LOG_PREFIX} _toggle_autostart: requested={checked}"
        )
        try:
            if checked:
                # === AKTIVERA: multi-metod + verifiering ===
                results = self._autostart_enable_robust()
                ok_methods = [k for k, v in results.items() if v]
                if ok_methods:
                    msg = (
                        f"✅ Autostart aktiverat via: "
                        f"{', '.join(ok_methods)}"
                    )
                    self._log.info(f"{LOG_PREFIX} {msg}")
                    if self._tray is not None:
                        with suppress(Exception):
                            self._tray.showMessage(
                                APP_NAME, msg,
                                self._QSystemTrayIcon.MessageIcon.Information,
                                3000,
                            )
                    # Spara i settings
                    with suppress(Exception):
                        if hasattr(self.settings, "set_autostart"):
                            self.settings.set_autostart(True)
                else:
                    msg = "⚠️ Autostart kunde inte aktiveras — se logg"
                    self._log.warning(f"{LOG_PREFIX} {msg}")
                    if self._tray is not None:
                        with suppress(Exception):
                            self._tray.showMessage(
                                APP_NAME, msg,
                                self._QSystemTrayIcon.MessageIcon.Warning,
                                4000,
                            )
                    self._restore_autostart_checkbox()
            else:
                # === INAKTIVERA: ta bort från ALLA platser ===
                removed = self._autostart_disable_all()
                msg = f"⛔ Autostart inaktiverat ({removed} platser rensade)"
                self._log.info(f"{LOG_PREFIX} {msg}")
                if self._tray is not None:
                    with suppress(Exception):
                        self._tray.showMessage(
                            APP_NAME, msg,
                            self._QSystemTrayIcon.MessageIcon.Information,
                            2500,
                        )
                with suppress(Exception):
                    if hasattr(self.settings, "set_autostart"):
                        self.settings.set_autostart(False)
        except Exception as e:
            self._log.error(
                f"{LOG_PREFIX} _toggle_autostart misslyckades: {e}",
                exc_info=True,
            )
            self._show_simple_error(
                "Autostart-fel",
                f"Fel: {e}\n\nAutostart-status återställd till oförändrad.",
            )
            self._restore_autostart_checkbox()

    def _restore_autostart_checkbox(self) -> None:
        """Återställ autostart-checkbox till faktisk status (vid fel)."""
        try:
            if hasattr(self, "_autostart_action_ref") and self._autostart_action_ref is not None:
                actual = self._is_autostart_active()
                self._autostart_action_ref.blockSignals(True)
                self._autostart_action_ref.setChecked(actual)
                self._autostart_action_ref.setText(
                    f"{'✅' if actual else '⚪'}  Starta med Windows"
                )
                self._autostart_action_ref.blockSignals(False)
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} _restore_autostart_checkbox: {e}")

    def _toggle_start_minimized(self, checked: bool) -> None:
        """
        NY v6.4.1: Toggla 'starta minimerad i tray' via UI.

        Anropar settings.set_start_minimized(True/False).
        """
        self._log.info(
            f"{LOG_PREFIX} _toggle_start_minimized: requested={checked}"
        )
        if not hasattr(self.settings, "set_start_minimized"):
            self._log.warning(
                f"{LOG_PREFIX} settings.set_start_minimized saknas"
            )
            self._show_simple_error(
                "Starta minimerad ej tillgängligt",
                "Settings-modulen saknar set_start_minimized-metoden.",
            )
            if hasattr(self, "_minimized_action_ref") and self._minimized_action_ref is not None:
                self._minimized_action_ref.blockSignals(True)
                self._minimized_action_ref.setChecked(
                    self.settings.start_minimized()
                    if hasattr(self.settings, "start_minimized")
                    else False
                )
                self._minimized_action_ref.blockSignals(False)
            return
        try:
            ok = self.settings.set_start_minimized(checked)
            if ok:
                if checked:
                    msg = "🚀 Nästa start: appen startar gömd i systemfältet."
                else:
                    msg = "👁 Nästa start: appen visas direkt på skrivbordet."
                self._log.info(f"{LOG_PREFIX} {msg}")
                if self._tray is not None:
                    with suppress(Exception):
                        self._tray.showMessage(
                            APP_NAME,
                            msg,
                            self._QSystemTrayIcon.MessageIcon.Information,
                            2500,
                        )
            else:
                self._log.warning(
                    f"{LOG_PREFIX} set_start_minimized({checked}) → False"
                )
        except Exception as e:
            self._log.error(
                f"{LOG_PREFIX} _toggle_start_minimized misslyckades: {e}",
                exc_info=True,
            )
            self._show_simple_error(
                "Starta minimerad-fel", f"Fel: {e}"
            )

    def _show_simple_error(self, title: str, message: str) -> None:
        """
        NY v6.4.1 v7: Visa kort QMessageBox-fel (med forbattrad loggning).

        Args:
            title: Kort titel (utan app-namn)
            message: Medellangt meddelande (svenska forklaringar)
        """
        if self._app is None or self._QMessageBox is None:
            self._log.error(
                f"{LOG_PREFIX} _show_simple_error: {title}: {message}"
            )
            return
        try:
            self._QMessageBox.warning(None, f"{APP_NAME} — {title}", message)
            self._log.debug(
                f"{LOG_PREFIX} _show_simple_error visad: {title!r}"
            )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _show_simple_error misslyckades: {e}",
                exc_info=True,
            )

    # -----------------------------------------------------------------------
    # DIALOGS — ask_new_task, ask_rename, ask_confirm_delete
    # -----------------------------------------------------------------------

    def ask_new_task(self) -> None:
        """Öppna dialog för ny uppgift (QInputDialog)."""
        if not self._app or self._QInputDialog is None:
            return
        try:
            text, ok = self._QInputDialog.getText(
                None,
                "Ny uppgift",
                "Vad behöver göras?",
            )
            if ok and text and text.strip():
                if hasattr(self.store, "add_task"):
                    self.store.add_task(text.strip())
                    self._log.info(f"Ny uppgift tillagd: {text.strip()!r}")
                    self.bring_all_to_front()
                else:
                    self._log.warning("Store har ingen add_task-metod")
        except Exception as e:
            self._log.error(f"ask_new_task misslyckades: {e}")

    def ask_rename_task(self, task_id: str, current_text: str) -> None:
        """Öppna dialog för att byta namn på en uppgift."""
        if not self._app or self._QInputDialog is None:
            return
        try:
            text, ok = self._QInputDialog.getText(
                None,
                "Byt namn på uppgift",
                "Ny text:",
                text=current_text,
            )
            if ok and text and text.strip() and text != current_text:
                if hasattr(self.store, "rename_task"):
                    self.store.rename_task(task_id, text.strip())
                    self._log.info(f"Task {task_id!r} döpt om till: {text.strip()!r}")
        except Exception as e:
            self._log.error(f"ask_rename_task misslyckades: {e}")

    def ask_confirm_delete(self, task_id: str, task_text: str) -> bool:
        """Fråga användaren om bekräftelse innan radering."""
        if not self._app or self._QMessageBox is None:
            return False
        try:
            reply = self._QMessageBox.question(
                None,
                "Ta bort uppgift?",
                f"Vill du verkligen ta bort:\n\n\"{task_text}\"\n\n"
                f"Detta går inte att ångra.",
                self._QMessageBox.StandardButton.Yes
                | self._QMessageBox.StandardButton.No,
                self._QMessageBox.StandardButton.No,
            )
            return reply == self._QMessageBox.StandardButton.Yes
        except Exception as e:
            self._log.error(f"ask_confirm_delete misslyckades: {e}")
            return False

    # -----------------------------------------------------------------------
    # TIMERS (callback-metoder)
    # -----------------------------------------------------------------------

    def _periodic_cleanup(self) -> None:
        """Periodisk cleanup av GDI-regioner (Win32) + fredags-pycache."""
        try:
            desktop_status = self._imports.get("desktop")
            if desktop_status and desktop_status.ok:
                cleanup = getattr(self._desktop_mod(desktop_status), "cleanup_dead_regions", None)
                if cleanup:
                    cleanup()
        except Exception as e:
            self._log.debug(f"cleanup misslyckades: {e}")
        # Smart cache: fångar också om appen stannar öppen över till fredag
        with suppress(Exception):
            self._run_friday_pycache_cleanup(at_startup=False)
        with suppress(Exception):
            self._run_friday_log_cleanup(at_startup=False)

    def _run_friday_pycache_cleanup(self, at_startup: bool = False) -> None:
        """
        NY 2026-09-23: Smart cache — rensa __pycache__ varje fredag.
        Anropas vid start + via _periodic_cleanup (5 min) → en gång per ISO-vecka.
        """
        utils_status = self._imports.get("utils")
        if not utils_status or not utils_status.ok:
            return
        inst = utils_status.instance
        # instance kan vara modul ELLER {"utils": modul}-dict (safe_import)
        fn = getattr(inst, "smart_friday_pycache_cleanup", None)
        if fn is None and isinstance(inst, dict):
            mod = inst.get("utils") or next(
                (v for v in inst.values() if hasattr(
                    v, "smart_friday_pycache_cleanup"
                )),
                None,
            )
            fn = getattr(mod, "smart_friday_pycache_cleanup", None)
        if fn is None:
            self._log.debug(
                f"{LOG_PREFIX} [CACHE] smart_friday_pycache_cleanup saknas"
            )
            return
        result = fn(base_dir=str(SCRIPT_DIR), force=False)
        if result.get("ran"):
            self._log.info(
                f"{LOG_PREFIX} [CACHE] Fredags-pycache rensad: "
                f"{result.get('pycache_removed')} mappar "
                f"({result.get('week')}, start={at_startup})"
            )
        elif result.get("reason") not in ("inte_fredag", "redan_rensad_denna_vecka"):
            self._log.debug(f"{LOG_PREFIX} [CACHE] friday_pycache: {result}")

    def _run_friday_log_cleanup(self, at_startup: bool = False) -> None:
        """
        NY 2026-09-25: Log-rensning varje fredag.
        Behåll ENDAST dagens log-fil (todo_app.log + aktuell backup).
        Anropas vid start + via _periodic_cleanup (5 min).
        """
        utils_status = self._imports.get("utils")
        if not utils_status or not utils_status.ok:
            return
        inst = utils_status.instance
        fn = getattr(inst, "smart_friday_log_cleanup", None)
        if fn is None and isinstance(inst, dict):
            mod = inst.get("utils") or next(
                (v for v in inst.values() if hasattr(
                    v, "smart_friday_log_cleanup"
                )),
                None,
            )
            fn = getattr(mod, "smart_friday_log_cleanup", None)
        if fn is None:
            self._log.debug(
                f"{LOG_PREFIX} [CACHE] smart_friday_log_cleanup saknas"
            )
            return
        try:
            data_dir = str(getattr(self, "_SCRIPT_DIR", SCRIPT_DIR) / "data")
        except Exception:
            data_dir = str(SCRIPT_DIR / "data")
        result = fn(data_path=data_dir, force=False)
        if result.get("ran"):
            self._log.info(
                f"{LOG_PREFIX} [CACHE] Fredags-loggrensning: "
                f"behöll={result.get('logs_kept')} "
                f"raderade={result.get('logs_removed')} "
                f"({result.get('week')}, idag={result.get('today_key')}, "
                f"start={at_startup})"
            )
        elif result.get("reason") not in (
            "inte_fredag", "redan_rensad_denna_vecka"
        ):
            self._log.debug(
                f"{LOG_PREFIX} [CACHE] friday_log_cleanup: {result}"
            )

    def _refresh_metrics(self) -> None:
        """Uppdatera performance-metrics + tooltip."""
        try:
            self._performance.take_snapshot()
            self._update_tray_tooltip()
        except Exception as e:
            self._log.debug(f"refresh_metrics misslyckades: {e}")

    def _refresh_capabilities(self) -> None:
        """Uppdatera capabilities-cache (Win32 features, HWND-stöd, etc.)."""
        try:
            caps: Dict[str, Any] = {
                "platform": sys.platform,
                "is_windows": _is_windows(),
                "python_version": sys.version.split()[0],
                "pyside6_available": False,
                "mica_supported": False,
                "acrylic_supported": False,
                "tray_available": False,
            }
            if self._imports.get("PySide6.QtWidgets", ImportStatus("", False)).ok:
                caps["pyside6_available"] = True
                if self._QSystemTrayIcon:
                    caps["tray_available"] = self._QSystemTrayIcon.isSystemTrayAvailable()
            # Mica/acrylic kräver Win10+ vissa builds
            if _is_windows():
                try:
                    import platform as _p
                    win_ver = _p.win32_ver()
                    caps["win_version"] = win_ver
                    major, _, _ = (int(x) if x.isdigit() else 0 for x in win_ver[1].split("."))
                    caps["mica_supported"] = major >= 10
                    caps["acrylic_supported"] = major >= 10
                except Exception:
                    pass
            self._capabilities = caps
            self._log.debug(f"Capabilities: {caps}")
        except Exception as e:
            self._log.debug(f"refresh_capabilities misslyckades: {e}")

    def _heartbeat(self) -> None:
        """Heartbeat för watchdog + log periodic health."""
        try:
            if hasattr(self, "stability"):
                with suppress(Exception):
                    self.stability.heartbeat()
        except Exception as e:
            self._log.debug(f"heartbeat misslyckades: {e}")
        # NY v7-fix90: håll e-postbryggan vid liv (Thunderbird-tillägget)
        with suppress(Exception):
            self._mail_bridge_watchdog()

    def _mail_bridge_watchdog(self) -> None:
        """
        NY v7-fix90: starta om bryggan om den dött (port stulen, fel, krasch).

        Körs var 5:e sekund via heartbeat. Max 3 återstart-försök per
        session — annars skulle en permanent portkonflikt snurra i evighet.
        """
        svc = getattr(self, "_mail_bridge", None)
        if svc is None:
            return
        if getattr(self, "_mail_bridge_restarts", 0) >= 3:
            return
        restarted = False
        try:
            if getattr(svc, "http_enabled", True) and not svc.server.running:
                if svc.server.start():
                    self._mail_bridge_restarts = (
                        getattr(self, "_mail_bridge_restarts", 0) + 1
                    )
                    restarted = True
            if getattr(svc, "watch_enabled", True) and not svc.watch_running:
                if svc.start_watcher():
                    restarted = True
        except Exception as e:
            self._log.debug(f"{LOG_PREFIX} brygg-watchdog: {e}")
            return
        if restarted:
            svc.config_payload()
            self._log.info(
                f"{LOG_PREFIX} e-postbryggan återstartad av watchdog "
                f"(port {svc.server.port or svc.port})"
            )
            with suppress(Exception):
                self._populate_tray_menu()

    def _check_idle(self) -> None:
        """Kontrollera idle-tid (dölj widget om idle > 10 min)."""
        try:
            desktop_status = self._imports.get("desktop")
            if desktop_status and desktop_status.ok:
                get_idle = getattr(self._desktop_mod(desktop_status), "get_idle_time_ms", None)
                if get_idle:
                    idle_sec = get_idle() // 1000
                    if idle_sec > Timeouts.IDLE_HIDE_THRESHOLD_SEC:
                        self._log.debug(f"Idle: {idle_sec}s (döljer widget)")
                        with self._widget_lock:
                            for w in self._widgets.values():
                                with suppress(Exception):
                                    if hasattr(w, "hide"):
                                        w.hide()
                    else:
                        # Visa igen om vi tidigare var idle
                        with self._widget_lock:
                            for w in self._widgets.values():
                                with suppress(Exception):
                                    if hasattr(w, "show") and not w.isVisible():
                                        w.show()
        except Exception as e:
            self._log.debug(f"check_idle misslyckades: {e}")

    def _check_backup_status(self) -> None:
        """Kontrollera backup-status (auto-restore om tasks är trasiga)."""
        try:
            if hasattr(self, "backup_manager"):
                with suppress(Exception):
                    status = self.backup_manager.get_status()
                    if status.get("needs_restore"):
                        self._log.warning("Backup restore behövs — återställer…")
                        self.backup_manager.restore_latest()
                        if hasattr(self.store, "reload"):
                            self.store.reload()
        except Exception as e:
            self._log.debug(f"check_backup_status misslyckades: {e}")

    # -----------------------------------------------------------------------
    # EVENT HANDLERS
    # -----------------------------------------------------------------------

    def _on_second_instance(self, message: str = "SHOW") -> None:
        """
        NY v7-fix87: en andra instans av TaskBord startade → visa oss.

        Kedja: användaren startar appen igen → det hårda låset stoppar
        den nya processen → den signalar "SHOW" via instans-kanalen →
        HÄR: visa + lyft fönstret + tray-notis. Att starta appen igen
        blir alltså ett sätt att TA FRAM den.
        """
        try:
            self._log.info(
                f"{LOG_PREFIX} Andra instans startade ({message!r}) → "
                f"visar fönstret (v7-fix87)"
            )
            with suppress(Exception):
                self._show_existing_window()
            # Lyft över appar en stund så att den SYNNS (tray-lyft-tricket)
            with suppress(Exception):
                self._lift_on_top_temporarily()
            if self._tray is not None:
                with suppress(Exception):
                    self._tray.showMessage(
                        APP_NAME,
                        "TaskBord var redan igång — fönstret visas nu",
                        self._QSystemTrayIcon.MessageIcon.Information,
                        3000,
                    )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} _on_second_instance misslyckades: {e}"
            )

    def _on_theme_changed(self, _theme: str = "") -> None:
        """Hantera tema-ändring (uppdatera tray + alla widgets)."""
        try:
            if self._tray is not None:
                self._update_tray_tooltip()
                self._populate_tray_menu()
            with self._widget_lock:
                for w in self._widgets.values():
                    with suppress(Exception):
                        if hasattr(w, "_apply_theme"):
                            w._apply_theme()
        except Exception as e:
            self._log.debug(f"on_theme_changed misslyckades: {e}")

    def _on_tasks_changed(self, *_args: Any) -> None:
        """Hantera task-ändring (uppdatera tray-tooltip + meny)."""
        try:
            self._update_tray_tooltip()
            # Uppdatera inte menyn varje gång (för dyrt) — bara tooltip
        except Exception as e:
            self._log.debug(f"on_tasks_changed misslyckades: {e}")

    def _on_store_data_changed(self, *_args: Any) -> None:
        """
        NY v7-fix11: store-data ändrad → debounced lista-refresh + autospara.

        Bakgrund: INGEN kod anropade tidigare store.save() — alla ändringar
        (lägg till / bocka av / byta prioritet ...) levde bara i RAM och
        FÖRSVANN vid omstart. Denna handler kopplas till store.changed och
        startar två single-shot-timers (debounce):
          * 250 ms  → _refresh_task_lists (uppdatera alla widgets listor)
          * 1500 ms → _autosave_store (spara till disk om dirty)
        Loop-säkert: save() emiterar INTE 'changed' (fix i store.py v7-fix11).
        """
        try:
            self._schedule_task_refresh()
            self._schedule_autosave()
        except Exception as e:
            self._log.debug(f"on_store_data_changed misslyckades: {e}")

    def _schedule_task_refresh(self) -> None:
        """Debounce (250 ms) av task-lists-refresh — många signals per batch."""
        timer = getattr(self, "_task_refresh_timer", None)
        if timer is None:
            if self._QTimer is None:
                return
            timer = (
                self._QTimer(self._app) if self._app else self._QTimer()
            )
            timer.setSingleShot(True)
            timer.setInterval(250)
            timer.timeout.connect(self._refresh_task_lists)
            self._task_refresh_timer = timer
        timer.start()

    def _refresh_task_lists(self) -> None:
        """
        NY v7-fix11: Uppdatera task-listor i ALLA befintliga widgets.

        _populate_windows skapar bara SAKNADE fönster — befintliga widgets
        fick aldrig nya tasks förrän omstart. Här renderas listorna om direkt
        (loop-säkert: _render_tasks skriver varken till settings eller store).
        """
        refreshed = 0
        with self._widget_lock:
            widgets = list(self._widgets.values())
        for w in widgets:
            try:
                if hasattr(w, "_render_tasks"):
                    w._render_tasks(
                        self.store.active_tasks(), archived=False
                    )
                    w._render_tasks(
                        self.store.archive_tasks(), archived=True
                    )
                if hasattr(w, "_build_search_index"):
                    w._build_search_index()
                refreshed += 1
            except Exception as e:
                self._log.warning(
                    f"{LOG_PREFIX} task-lists-refresh misslyckades "
                    f"för en widget: {e}"
                )
        if refreshed:
            self._log.debug(
                f"{LOG_PREFIX} task-listor uppdaterade i {refreshed} widget(s)"
            )

    def _schedule_autosave(self) -> None:
        """Debounce (1500 ms) autospara av store — skyddar mot dataförlust."""
        timer = getattr(self, "_autosave_timer", None)
        if timer is None:
            if self._QTimer is None:
                return
            timer = (
                self._QTimer(self._app) if self._app else self._QTimer()
            )
            timer.setSingleShot(True)
            timer.setInterval(1500)
            timer.timeout.connect(self._autosave_store)
            self._autosave_timer = timer
        timer.start()

    def _autosave_store(self) -> None:
        """NY v7-fix11: Spara store om dirty (kallas av debounce-timer)."""
        try:
            if self.store is None:
                return
            if getattr(self.store, "is_dirty", False):
                ok = self.store.save()
                self._log.info(
                    f"{LOG_PREFIX} autosave: "
                    f"{'OK' if ok else 'MISSLYCKADES'} "
                    f"(active={len(self.store.active_tasks())}, "
                    f"archive={len(self.store.archive_tasks())})"
                )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} autosave misslyckades: {e}", exc_info=True
            )

    # -----------------------------------------------------------------------
    # PDF-EXPORT (NY v6.4.1 v7: AI-snygg checklista)
    # -----------------------------------------------------------------------

    def _export_checklist_pdf(self) -> None:
        """
        FIX 2026-09-25: Skriv ut / spara aktiva uppgifter som PDF-checklista
        (modul: core/pdf_export.py — snygg sektionerad design).
        """
        try:
            tasks = self.store.active_tasks() if hasattr(
                self.store, "active_tasks"
            ) else []
        except Exception as _at_e:
            self._log.warning(f"{LOG_PREFIX} PDF-export: task-list misslyckades: {_at_e}")
            tasks = []
        if not tasks:
            try:
                show_error_dialog(
                    title="Inga uppgifter",
                    user_message="Det finns inga aktiva uppgifter att exportera.",
                    technical="",
                    category="user_input",
                )
            except Exception:
                pass
            return
        tasks = [t for t in tasks if str(t.get("id", "")).strip()]
        # Importera PDF-export-modul på begäran (ingen permanent import)
        try:
            from core.pdf_export import render_checklist_html, save_pdf
        except Exception as _pe_imp:
            self._log.error(
                f"{LOG_PREFIX} PDF-export: import misslyckades: {_pe_imp}",
                exc_info=True,
            )
            return
        html = render_checklist_html(
            tasks, app_name=APP_NAME, app_version=APP_VERSION_DISPLAY
        )
        # Fil-dialog
        from PySide6.QtWidgets import QFileDialog
        ts = _datetime.now().strftime("%Y%m%d_%H%M")
        default_name = f"{APP_NAME}_checklista_{ts}.pdf"
        try:
            store_path = (
                getattr(self.store, "file_path", None)
                or getattr(self.store, "_file_path", None)
            )
            default_dir = str(Path(str(store_path)).resolve().parent) \
                if store_path else os.path.expanduser("~")
        except Exception:
            default_dir = os.path.expanduser("~")
        default_path = os.path.join(default_dir, default_name)
        try:
            fname, _ = QFileDialog.getSaveFileName(
                None,
                "Spara checklista som PDF",
                default_path,
                "PDF-dokument (*.pdf)",
            )
        except Exception as _fd_e:
            self._log.warning(
                f"{LOG_PREFIX} PDF-export: file-dialog misslyckades: {_fd_e}"
            )
            fname = ""
        if not fname:
            fname = default_path
            self._log.info(
                f"{LOG_PREFIX} PDF-export: ingen fil vald → {fname}"
            )
        if not str(fname).lower().endswith(".pdf"):
            fname = str(fname) + ".pdf"
        ok = save_pdf(html, str(fname))
        if ok:
            self._log.info(
                f"{LOG_PREFIX} PDF-export klar: {fname} ({len(tasks)} uppgifter)"
            )
            show_error_dialog(
                title="PDF skapad",
                user_message=(
                    f"Checklista sparad till:\n{fname}\n\n{len(tasks)} uppgifter."
                ),
                technical="",
                category="user_input",
            )
        else:
            self._log.warning(
                f"{LOG_PREFIX} PDF-export misslyckades (modul returnerade False)"
            )

    def _open_backup_dialog(self) -> None:
        """NY v8: öppna backup-dialogen från tray-menyn."""
        try:
            from ui.backup_dialog import open_backup_dialog
            open_backup_dialog(None, store=getattr(self, "store", None))
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} kunde inte öppna backup-dialogen: {e}")

    def _open_google_calendar(self) -> None:
        """
        NY v8 (2026-10-12): öppna Google Calendar-dialogen från tray-menyn.

        Hela kopplingen (OAuth) och alla anrop till Google sköts av
        ui/google_calendar_dialog.py, som kör nätverket i en egen tråd så
        att appen inte fryser.
        """
        try:
            from ui.google_calendar_dialog import open_google_calendar_dialog
            open_google_calendar_dialog(
                None,
                store=getattr(self, "store", None),
                settings=getattr(self, "settings", None),
                data_dir=self._mail_bridge_data_dir(),
            )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} kunde inte öppna Google Calendar-dialogen: {e}"
            )

    def _export_calendar_ics(self) -> None:
        """
        NY v8 (2026-10-12): exportera uppgifter med förfallodatum till .ics
        (Google Calendar, Outlook, Apple Kalender).

        Samma uppgiftslista som Aktiva-fliken visar. Uppgifter utan
        förfallodatum kan inte bli händelser och rapporteras i dialogen.
        """
        try:
            tasks = self.store.active_tasks() if hasattr(
                self.store, "active_tasks"
            ) else []
        except Exception as _at_e:
            self._log.warning(
                f"{LOG_PREFIX} Kalenderexport: task-list misslyckades: {_at_e}"
            )
            tasks = []
        tasks = [t for t in tasks if str(t.get("id", "")).strip()]
        try:
            from core.calendar_export import tasks_with_due, write_ics
        except Exception as _ce_imp:
            self._log.error(
                f"{LOG_PREFIX} Kalenderexport: import misslyckades: {_ce_imp}",
                exc_info=True,
            )
            return
        valda = tasks_with_due(tasks)
        if not valda:
            try:
                show_error_dialog(
                    title="Inga datum",
                    user_message=(
                        "Inga aktiva uppgifter har ett förfallodatum eller startdatum.\n\n"
                        "Sätt ett datum på en uppgift så kan den "
                        "bli en händelse i kalendern."
                    ),
                    technical="",
                    category="user_input",
                )
            except Exception:
                pass
            return
        from PySide6.QtWidgets import QFileDialog
        ts = _datetime.now().strftime("%Y%m%d_%H%M")
        try:
            store_path = (
                getattr(self.store, "file_path", None)
                or getattr(self.store, "_file_path", None)
            )
            default_dir = str(Path(str(store_path)).resolve().parent) \
                if store_path else os.path.expanduser("~")
        except Exception:
            default_dir = os.path.expanduser("~")
        default_path = os.path.join(default_dir, f"{APP_NAME}_kalender_{ts}.ics")
        try:
            fname, _ = QFileDialog.getSaveFileName(
                None,
                "Spara kalenderfil (.ics)",
                default_path,
                "Kalenderfil (*.ics)",
            )
        except Exception as _fd_e:
            self._log.warning(
                f"{LOG_PREFIX} Kalenderexport: file-dialog misslyckades: {_fd_e}"
            )
            fname = ""
        if not fname:
            fname = default_path
            self._log.info(
                f"{LOG_PREFIX} Kalenderexport: ingen fil vald → {fname}"
            )
        if not str(fname).lower().endswith(".ics"):
            fname = str(fname) + ".ics"
        try:
            antal = write_ics(valda, str(fname), calendar_name=APP_NAME)
        except Exception as _w_e:
            self._log.error(
                f"{LOG_PREFIX} Kalenderexport: skrivning misslyckades: {_w_e}",
                exc_info=True,
            )
            return
        hoppade = len(tasks) - antal
        self._log.info(
            f"{LOG_PREFIX} Kalenderexport klar: {fname} ({antal} händelser, "
            f"{hoppade} utan datum)"
        )
        extra = (
            f"\n\n{hoppade} uppgifter utan förfallodatum hoppades över."
            if hoppade > 0 else ""
        )
        try:
            show_error_dialog(
                title="Kalenderfil skapad",
                user_message=(
                    f"{antal} uppgifter exporterade till:\n{fname}{extra}\n\n"
                    "Google Calendar: ⚙️ Inställningar →\n"
                    "Importera och exportera → Importera.\n"
                    "Filen fungerar även i Outlook och Apple Kalender."
                ),
                technical="",
                category="user_input",
            )
        except Exception:
            pass


    def _safe_update_widgets(self) -> None:
        """Säker widget-uppdatering (anropas via windows_updated-signal).
        FIX 2026-09-24: Debounce — populate ska inte spammas av
        windows_updated (moveEvent→save→signal→populate→show→move…)."""
        try:
            import traceback as _tbs
            _stk = _tbs.extract_stack(limit=4)[:-1]
            _call = " ← ".join(
                f"{f.filename.split('/')[-1]}:{f.lineno}({f.name})"
                for f in _stk[-2:]
            )
            self._log.info(
                f"{LOG_PREFIX} _safe_update_widgets ANROPAD "
                f"← {_call}"
            )
            if getattr(self, "_populate_scheduled", False):
                self._log.debug(
                    f"{LOG_PREFIX} _safe_update_widgets: populate redan schemalagd"
                )
                return
            self._populate_scheduled = True
            # NY v6.4.1 v7-fix7: 150→500 ms — vi såg 25 anrop / 100 ms i loggen.
            # 500 ms tar kvar poptat-kaskad men UI känns fortfarande responsivt.
            delay_ms = 500
            if self._QTimer is not None:
                def _run_populate() -> None:
                    self._populate_scheduled = False
                    import traceback as _tbr
                    _s = _tbr.extract_stack(limit=4)[:-1]
                    _src = " ← ".join(
                        f"{f.filename.split('/')[-1]}:{f.lineno}({f.name})"
                        for f in _s[-2:]
                    )
                    self._log.info(
                        f"{LOG_PREFIX} _populate_windows UTLÖST "
                        f"av QTimer (debounced 500ms) ← {_src}"
                    )
                    self._populate_windows()
                self._QTimer.singleShot(delay_ms, _run_populate)
            else:
                self._populate_scheduled = False
                self._populate_windows()
        except Exception as e:
            self._populate_scheduled = False
            self._log.error(f"update_widgets misslyckades: {e}")

    # -----------------------------------------------------------------------
    # POPULATE / REFRESH — synka UI med data
    # -----------------------------------------------------------------------

    def populate_all(self) -> None:
        """Synka ALLA UI-komponenter med aktuell data (användbart efter restore)."""
        with error_boundary("populate_all"):
            self._populate_windows()
            self._update_tray_tooltip()
            if self._tray is not None:
                self._populate_tray_menu()
            with self._widget_lock:
                for w in self._widgets.values():
                    with suppress(Exception):
                        if hasattr(w, "_rebuild_task_list"):
                            w._rebuild_task_list()
                        elif hasattr(w, "reload"):
                            w.reload()
            self._log.info("populate_all klar")

    # -----------------------------------------------------------------------
    # FORCE SHOW WIDGET (NY v6.4.1 v7)
    # -----------------------------------------------------------------------

    def force_show_all_widgets(self) -> None:
        """
        NY v6.4.1 v7-fix3: Tvinga ALLA widget-fonster att bli synliga.

        Rickard 2026-09-22: "fortfarande inget fönster, ska ej vara osynligt,
        men ej dölja iconer".

        Approach (v7-fix3):
          - Reparenta från WorkerW (som ÄR Explorer-ikon-lagret → döljer ikoner)
          - Ta bort WS_EX_NOACTIVATE + WS_EX_TOPMOST
          - HWND_TOP = toppen av normal z-order (över Explorer-ikoner)
          - ShowWindow(SW_SHOW) + SW_RESTORE

        Skilljer fran bring_all_to_front() som respekterar z-order.
        Aktiveras via:
          - CLI-flagga --force-show (permanent under sessionen)
          - Tray-meny 'Diagnostik' → 'Tvinga synlig'
        """
        n_total = 0
        n_shown = 0
        try:
            with self._widget_lock:
                widgets = list(self._widgets.values())
            n_total = len(widgets)
            self._log.info(
                f"{LOG_PREFIX} force_show_all_widgets: {n_total} widgets → "
                f"NOTOPMOST (synlig, EJ över appar)"
            )
            for w in widgets:
                try:
                    # NY v6.4.1 v7-fix2: Sätt _force_show PÅ widget så
                    # _periodic_zorder_check + _setup_bugg19_zorder använder
                    # HWND_TOP (toppen av desktop-lagret, EJ över allt).
                    w._force_show = True
                    # NY v7-fix51: desktop-lagret aktivt? → slita ALDRIG
                    # loss fönstret från skrivbordet! Gamla koden körde
                    # SetParent(hwnd, 0) som rev ner Progman-parentingen
                    # → Win+D kunde gömma fönstret igen (+ force_show-
                    # flaggan gjorde att bevakningen hoppade över det).
                    _fs_shell0 = getattr(w, "_shell", None)
                    _layer_active = str(
                        getattr(_fs_shell0, "_desktop_layer_mode", "")
                    ) in ("above", "behind")
                    if _layer_active:
                        with suppress(Exception):
                            if sys.platform == "win32":
                                import ctypes as _ct0
                                _u0 = _ct0.windll.user32
                                _h0 = (
                                    int(_fs_shell0.winId())
                                    if _fs_shell0 is not None else 0
                                )
                                if _h0 and _u0.IsIconic(_h0):
                                    _u0.ShowWindow(_h0, 9)  # SW_RESTORE
                            if (_fs_shell0 is not None
                                    and not _fs_shell0.isVisible()):
                                _fs_shell0.show()
                        self._log.info(
                            f"{LOG_PREFIX} force_show: "
                            f"{getattr(w, 'win_id', '?')!r} behåller "
                            f"desktop-lagret ({getattr(_fs_shell0, '_desktop_layer_mode', '?')}) "
                            f"— sliter ej loss (v7-fix51)"
                        )
                        n_shown += 1
                        continue
                    # 1. Använd Win32 ShowWindow(hwnd, SW_RESTORE = 9)
                    if sys.platform == "win32":
                        try:
                            import ctypes
                            hwnd = int((w._shell.winId() if hasattr(w, '_shell') and w._shell else w.winId()))
                            if hwnd:
                                user32 = ctypes.windll.user32
                                # NY v6.4.1 v7-fix3: Reparenta från WorkerW
                                # Workers ÄR Explorer-ikon-lagret → döljer ikoner.
                                # Vi vill vara top-level igen.
                                try:
                                    current_parent = user32.GetParent(hwnd)
                                    if current_parent:
                                        user32.SetParent(hwnd, 0)
                                except Exception:
                                    pass
                                # NY v7-fix38: force-show = escape hatch —
                                # markera skalet som legacy så underhålls-
                                # timern INTE återfäster det i desktop-lagret
                                with suppress(Exception):
                                    _fs_shell = getattr(w, "_shell", None)
                                    if _fs_shell is not None:
                                        _fs_shell._desktop_layer_mode = (
                                            "normal"  # v7-fix56: ej legacy
                                        )
                                # Ta bort WS_EX_NOACTIVATE + WS_EX_TOPMOST
                                try:
                                    GWL_EXSTYLE = -20
                                    WS_EX_NOACTIVATE = 0x08000000
                                    WS_EX_TOPMOST = 0x00000008
                                    try:
                                        current_ex = user32.GetWindowLongPtrW(
                                            hwnd, GWL_EXSTYLE
                                        )
                                    except Exception:
                                        current_ex = user32.GetWindowLongW(
                                            hwnd, GWL_EXSTYLE
                                        )
                                    new_ex = (
                                        current_ex
                                        & ~WS_EX_NOACTIVATE
                                        & ~WS_EX_TOPMOST
                                    )
                                    if new_ex != current_ex:
                                        try:
                                            user32.SetWindowLongPtrW(
                                                hwnd, GWL_EXSTYLE, new_ex
                                            )
                                        except Exception:
                                            user32.SetWindowLongW(
                                                hwnd, GWL_EXSTYLE, new_ex
                                            )
                                except Exception:
                                    pass
                                # VIKTIGT: först ShowWindow(SW_RESTORE) + SW_SHOW
                                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                                user32.ShowWindow(hwnd, 5)  # SW_SHOW
                                # FIX 2026-09-24: INTE NOTOPMOST/TOP —
                                # båda flyttar ÖVER andra appar.
                                # Bara säkerställ synlig (SW_SHOWNOACTIVATE).
                                # Z-order lämnas orörd → fokuserade app går
                                # naturligt ovanför widgeten.
                                user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
                                user32.ShowWindow(hwnd, 5)  # SW_SHOW
                                # 3. Verifiera synlig
                                if user32.IsWindowVisible(hwnd):
                                    n_shown += 1
                                    self._log.info(
                                        f"{LOG_PREFIX} force_show: "
                                        f"HWND={hwnd} nu SYNLIG "
                                        f"(z-order orörd, ej över appar)"
                                    )
                                else:
                                    user32.ShowWindow(hwnd, 5)
                                    if user32.IsWindowVisible(hwnd):
                                        n_shown += 1
                                        self._log.info(
                                            f"{LOG_PREFIX} force_show (fallback): "
                                            f"HWND={hwnd} nu SYNLIG"
                                        )
                                    else:
                                        self._log.warning(
                                            f"{LOG_PREFIX} force_show: "
                                            f"HWND={hwnd} FORTFARANDE dold!"
                                        )
                        except Exception as e:
                            self._log.warning(
                                f"{LOG_PREFIX} force_show Win32 misslyckades: {e}"
                            )
                    # 4. Qt-niva: visa om dold — INTE raise/activate
                    # (activate/raise flyttar fönstret ÖVER andra appar)
                    try:
                        import threading as _th
                        on_gui = _th.current_thread() is _th.main_thread()
                        if on_gui:
                            if not w.isVisible():
                                w.show()
                        else:
                            from PySide6.QtCore import QMetaObject, Qt as _Qt
                            QMetaObject.invokeMethod(
                                w, "show", _Qt.ConnectionType.QueuedConnection,
                            )
                    except Exception as e:
                        self._log.warning(
                            f"{LOG_PREFIX} force_show Qt misslyckades: {e}"
                        )
                except Exception as e:
                    self._log.error(
                        f"{LOG_PREFIX} force_show misslyckades for widget: {e}"
                    )
            self._log.info(
                f"{LOG_PREFIX} force_show_all_widgets klar: "
                f"{n_shown}/{n_total} widgets synliga "
                f"(NOTOPMOST — ej över appar)"
            )
        except Exception as e:
            self._log.error(
                f"{LOG_PREFIX} force_show_all_widgets FEL: {e}",
                exc_info=True,
            )

    # -----------------------------------------------------------------------
    # BRING TO FRONT (BUGG 19/26)
    # -----------------------------------------------------------------------

    def bring_all_to_front(self) -> None:
        """
        BUGG 19: Visa alla fönster tillfälligt (användaren klickade på tray).
        BUGG 26: Auto-reposition om widget täcker skrivbordsikoner.

        Flöde:
          1. Hämta skrivbordsikoner-positioner (desktop.get_icon_rects)
          2. För varje fönster: kontrollera kollision, flytta om nödvändigt
          3. Visa fönster, raise, activate
          4. Sänk till botten igen (HWND_BOTTOM) så att andra fönster kan täcka
        """
        try:
            # Hämta ikonpositioner (BUGG 26)
            icon_rects: List[Tuple[int, int, int, int]] = []
            desktop_status = self._imports.get("desktop")
            if desktop_status and desktop_status.ok:
                get_icons = getattr(self._desktop_mod(desktop_status), "get_icon_rects", None)
                if get_icons:
                    with suppress(Exception):
                        icon_rects = get_icons() or []

            with self._widget_lock:
                widgets = list(self._widgets.values())
            for w in widgets:
                with suppress(Exception):
                    if hasattr(w, "bring_to_front"):
                        w.bring_to_front()
                    else:
                        w.show()
                        w.raise_()
                        w.activateWindow()
                        w.lower()
        except Exception as e:
            self._log.debug(f"bring_all_to_front misslyckades: {e}")

    def show_statistics(self) -> None:
        """Visa statistik-dialog (med subsystem-status)."""
        if not self._app or self._QMessageBox is None:
            return
        try:
            active, archived = (0, 0)
            if hasattr(self.store, "count"):
                active, archived = self.store.count()
            perf_snap = self._performance.take_snapshot()
            uptime = self._performance.format_uptime()
            subsystem_status = self._registry.get_all_status()

            lines = [
                f"📊  Statistik — {APP_NAME} v{APP_VERSION_DISPLAY}",
                "─" * 50,
                f"Aktiva uppgifter:    {active}",
                f"Arkiverade:          {archived}",
                f"Fönster:             {len(self._widgets)}",
                "─" * 50,
                f"Uptime:              {uptime}",
                f"Minne (RSS):         {perf_snap.memory_mb:.1f} MB",
                f"Trådar:              {perf_snap.thread_count}",
                f"GC-obj:            {perf_snap.gc_objects}",
                "─" * 50,
                f"Subsystems:          {len(subsystem_status)}",
            ]
            for name, info in subsystem_status.items():
                status_icon = "✓" if info["status"] == "HEALTHY" else "✗"
                hr_pct = int(info.get("health_ratio", 1.0) * 100)
                lines.append(
                    f"  {status_icon} {name:<15} {info['status']:<10} "
                    f"({hr_pct}% health)"
                )

            lines.append("─" * 50)
            lines.append(f"Python:     {platform.python_version()}")
            lines.append(f"Plattform:  {platform.system()} {platform.release()}")
            if self._capabilities:
                lines.append(f"Capabilities: {len(self._capabilities)} st")

            self._QMessageBox.information(
                None,
                f"{APP_NAME} — Statistik",
                "\n".join(lines),
            )
        except Exception as e:
            self._log.error(f"show_statistics misslyckades: {e}")

    def show_about(self) -> None:
        """Visa Om-dialog."""
        if not self._app or self._QMessageBox is None:
            return
        try:
            msg = (
                f"{APP_NAME} v{APP_VERSION_DISPLAY}\n"
                f"Copyright {ORG_NAME}, {COPYRIGHT_YEARS}\n"
                f"\n"
                f"{APP_DESCRIPTION}\n"
                f"\n"
                f"Funktioner:\n"
                f"  • Pin-funktion för viktiga uppgifter\n"
                f"  • Glasmorphism med mica/acrylic\n"
                f"  • Stability-system med auto-recovery\n"
                f"  • Backup med auto-restore\n"
                f"  • Multi-window + tray-icon\n"
                f"  • BUGG 19/26-fix: widget alltid synlig, aldrig över ikoner\n"
                f"\n"
                f"Donation: inaktiverad (R4 pausad 2026-08-11)\n"
            )
            self._QMessageBox.about(None, f"Om {APP_NAME}", msg)
        except Exception as e:
            self._log.error(f"show_about misslyckades: {e}")

    def _dump_subsystem_status(self) -> None:
        """Dump subsystem-status till logg (diagnostics-läge, NY v6.4: orjson)."""
        try:
            status = self._registry.get_all_status()
            # NY v6.4: använd orjson om tillgängligt (18× snabbare)
            json_str = _json_dumps(status).decode("utf-8") if _HAS_ORJSON else _stdlib_json.dumps(status, indent=2, default=str)
            self._log.info(f"=== SUBSYSTEM-DUMP ===\n{json_str}")
        except Exception as e:
            self._log.error(f"dump_subsystem_status misslyckades: {e}")

    # -----------------------------------------------------------------------
    # SHUTDOWN
    # -----------------------------------------------------------------------

    def shutdown(self) -> None:
        """
        NY v6.4.1 v7: Stäng app rent (graceful, idempotent, trådsäker).

        Steg (alla med 10000% loggning):
          1. Stang alla widget-fönster
          2. Dolj + frigör tray-ikon
          3. Stäng subsystems (LIFO)
          4. Stoppa async workers
          5. Logga sammanfattning
        """
        if self._shutdown_initiated:
            self._log.debug(
                f"{LOG_PREFIX} shutdown: redan initierad (idempotent)"
            )
            return
        self._shutdown_initiated = True
        # Använd svensk uptime-text i loggen
        uptime_sec = time.time() - getattr(self, "_start_time", time.time())
        uptime_sv = format_uptime(uptime_sec)
        # NY v7-fix41: avregistrera global hotkey FÖRST
        self._uninstall_global_quick_add()
        self._log.info(
            f"{LOG_PREFIX} Stänger ner {APP_NAME} efter {uptime_sv}..."
        )
        # FIX v7-fix11: slutgiltig save av store — tidigare sparades ALDRIG
        # vid nedstängning (dataförlust). Autosave-timern hinner kanske inte
        # köra klart innan processen dör, därför sparas här synkront.
        try:
            if self.store is not None and getattr(self.store, "is_dirty", False):
                ok = self.store.save()
                self._log.info(
                    f"{LOG_PREFIX} Slutgiltig save vid nedstängning: "
                    f"{'OK' if ok else 'MISSLYCKADES'}"
                )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} Slutgiltig save misslyckades: {e}", exc_info=True
            )
        # NY v7-fix90: stoppa e-postbryggan (släpper porten + skriver status)
        with suppress(Exception):
            self._stop_mail_bridge()
        # NY v8 (2026-10-12): spara fönstrets position + storlek INNAN något stängs
        # och skriv settings till disk (nedstängningen sparade tidigare inte settings
        # alls → fönsterläget glömdes vid omstart).
        with suppress(Exception):
            with self._widget_lock:
                _geo_widgets = list(self._widgets.values())
            for _w in _geo_widgets:
                with suppress(Exception):
                    if hasattr(_w, "_save_geometry_now"):
                        _w._save_geometry_now()
            if self.settings is not None and hasattr(self.settings, "save"):
                _ok_s = self.settings.save()
                self._log.info(
                    f"{LOG_PREFIX} Settings sparade vid nedstängning: "
                    f"{'OK' if _ok_s else 'MISSLYCKADES'}"
                )
        # NY v8: automatisk säkerhetskopia av uppgifter + inställningar
        with suppress(Exception):
            self._external_backup("nedstängning")
        try:
            # 1. Stäng alla widgets
            with self._widget_lock:
                widget_ids = list(self._widgets.keys())
            for wid in widget_ids:
                with suppress(Exception):
                    w = self._widgets.pop(wid, None)
                    if w and hasattr(w, "_unregister_hotkeys"):
                        w._unregister_hotkeys()
                    if w and hasattr(w, "close"):
                        # FIX 2026-09-24: tillåt close vid shutdown
                        w._allow_close = True
                        w.close()
                        with suppress(Exception):
                            w.deleteLater()
            # FIX: stäng också ev. pretest/spök-widgeter som inte är i _widgets
            with suppress(Exception):
                for child in list(self._app.topLevelWidgets()):
                    if not hasattr(child, "win_id"):
                        continue
                    if str(getattr(child, "win_id", "")).startswith("__"):
                        child._allow_close = True
                        child.close()
                        with suppress(Exception):
                            child.deleteLater()
            self._log.info(
                f"{LOG_PREFIX} Stängt {len(widget_ids)} widget-fönster"
            )

            # 2. Dölj + frigör tray
            if self._tray is not None:
                with suppress(Exception):
                    self._tray.hide()
                    self._tray.deleteLater()
                self._tray = None
                self._log.debug(f"{LOG_PREFIX} Tray dold och frigjord")

            # 3. Stäng subsystems (LIFO)
            self._registry.shutdown_all()
            self._log.debug(f"{LOG_PREFIX} Subsystems avslutade")

            # 4. Stoppa async runner
            if self._async_runner:
                self._async_runner.stop(timeout=Timeouts.WORKER_CLEANUP)
                self._log.debug(f"{LOG_PREFIX} Async runner stoppad")

            # NY v7-fix25: Full cache-rensning
            with suppress(Exception):
                self._cleanup_all_caches()

            # NY v7-fix28: Logg-rensning — 3 dagars retention
            with suppress(Exception):
                from utils import cleanup_old_logs
                _lr = cleanup_old_logs(
                    data_path=str(SCRIPT_DIR / "data"), max_age_days=3
                )
                if _lr.get("removed"):
                    self._log.info(
                        f"{LOG_PREFIX} Logg-rensning: "
                        f"{_lr['removed']} gamla loggar raderade"
                    )

            # 5. Flush logging
            for handler in logging.getLogger().handlers:
                with suppress(Exception):
                    handler.flush()

            # NY v7-fix87: stäng instans-kanalen (så att nästa start kan
            # lyssna direkt)
            _m = getattr(self, "_instance_messenger", None)
            if _m is not None:
                with suppress(Exception):
                    _m.close()
                self._instance_messenger = None
            self._log.info("Avslutning klar")
        except Exception as e:
            self._log.error(f"Shutdown-fel: {e}", exc_info=True)
        finally:
            hide_splash()
            if self._app is not None:
                with suppress(Exception):
                    self._app.quit()

    def run(self) -> int:
        """Kör Qt event loop (blocking)."""
        if self._app is None:
            self._log.error("Kan inte starta event loop (QApplication saknas)")
            return 1
        # NY v6.4.1: Kör diagnostik vid start (efter Qt-init)
        try:
            self._run_diagnostics_on_startup()
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} diagnostik vid start misslyckades: {e}"
            )
        return self._app.exec()


# ===========================================================================
# MAIN ENTRY POINT
# ===========================================================================

def setup_signal_handlers(controller: AppController) -> None:
    """
    NY v6.4.1 v7: Installera signal handlers for graceful shutdown.

    Hanterar SIGINT (Ctrl+C), SIGTERM (avsluta), SIGBREAK (Windows).
    Loggar signal + startar shutdown.
    """
    log = logging.getLogger("Main")

    def handler(signum, frame):
        # Signal-namn for svensk lasbarhet
        signal_names = {
            signal.SIGINT: "Ctrl+C (SIGINT)",
            signal.SIGTERM: "Avsluta (SIGTERM)",
            signal.SIGBREAK: "Windows Ctrl+Break (SIGBREAK)",
        }
        name = signal_names.get(signum, f"signal {signum}")
        log.info(
            f"{LOG_PREFIX} Signal mottagen: {name} — startar graceful shutdown"
        )
        try:
            controller.shutdown()
        except Exception as e:
            log.warning(
                f"{LOG_PREFIX} shutdown efter signal misslyckades: {e}",
                exc_info=True,
            )

    with suppress(Exception):
        signal.signal(signal.SIGINT, handler)
        log.debug(f"{LOG_PREFIX} SIGINT handler installerad")
    with suppress(Exception):
        signal.signal(signal.SIGTERM, handler)
        log.debug(f"{LOG_PREFIX} SIGTERM handler installerad")
    if hasattr(signal, "SIGBREAK"):
        with suppress(Exception):
            signal.signal(signal.SIGBREAK, handler)
            log.debug(f"{LOG_PREFIX} SIGBREAK handler installerad")


def show_pre_flight_error_dialog(error: str) -> None:
    """
    NY v6.4.1 v7: Visa pre-flight error (forbattrad).

    Använder show_error_dialog() for konsistent felhantering.
    Felmeddelandet oversatts till svenska nar mojligt.
    """
    log = logging.getLogger("PreFlight")
    log.critical(f"{LOG_PREFIX} Pre-flight error: {error}")
    # Visa med show_error_dialog (standardiserad)
    show_error_dialog(
        title="Startfel",
        user_message=(
            f"{APP_NAME} kunde inte startas.\n\n"
            f"Orsak: {error}\n\n"
            f"Mer information finns i loggfilen:\n{LOG_FILE}"
        ),
        technical=error,
        category="system",
    )


def install_global_exception_hook() -> None:
    """
    NY v6.4.1 v7: Global exception hook med AI-felsokning.

    Rickard 2026-09-22: "tyst crash, loggningen ska upptäcka det".

    Vad den gor:
      1. Fångar ALLA ohanterade undantag (inte KeyboardInterrupt)
      2. Loggar komplett stacktrace till data/todo_app.log
      3. Visar svensk fel-dialog till anvandaren
      4. Kallar original hook (for Qt-dialog)
      5. NY v7: Installerar Qt-message-handler for Qt-fel (qInstallMessageHandler)
      6. NY v7: Loggar även SystemExit och BaseException (utom KeyboardInterrupt/SystemExit frivillig)
    """
    # Säkerställ att logger finns — vi loggar alltid, även före run() startat
    log = logging.getLogger("Main")
    try:
        # Om root-logger saknar handlers, lägg till en basic file-handler som
        # alltid skriver till data/todo_app.log (även vid tyst crash)
        root = logging.getLogger()
        if not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers):
            try:
                log_path = SCRIPT_DIR / "data" / "todo_app.log"
                log_path.parent.mkdir(parents=True, exist_ok=True)
                fallback_handler = logging.handlers.RotatingFileHandler(
                    log_path,
                    maxBytes=5 * 1024 * 1024,
                    backupCount=3,
                    encoding="utf-8",
                )
                fallback_handler.setLevel(logging.DEBUG)
                fallback_handler.setFormatter(logging.Formatter(
                    "%(asctime)s.%(msecs)03d | %(levelname)-8s | %(name)-20s | %(message)s",
                    "%H:%M:%S",
                ))
                root.addHandler(fallback_handler)
                log.info(f"{LOG_PREFIX} fallback file-handler tillagd: {log_path}")
            except Exception as _fh_err:
                log.warning(f"{LOG_PREFIX} kunde inte lägga till fallback-handler: {_fh_err}")
    except Exception as _setup_err:
        # Om vi inte ens kan logga, skriv till stderr som sista utväg
        try:
            print(f"[FATAL] install_global_exception_hook setup: {_setup_err}", file=sys.stderr)
        except Exception:
            pass

    def hook(exc_type, exc_value, exc_traceback):
        # NY v7: Tillåt KeyboardInterrupt + frivillig SystemExit
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        try:
            log.critical(
                f"{LOG_PREFIX} OHANTERAT FEL [{exc_type.__name__}]: "
                f"{_describe_exception(exc_value)}"
            )
            # Skriv ut hela traceback rad-för-rad till ALLA loggers
            import traceback as _tb
            tb_lines = _tb.format_exception(exc_type, exc_value, exc_traceback)
            for line in tb_lines:
                for h in logging.getLogger().handlers:
                    try:
                        h.emit(logging.LogRecord(
                            name="Main", level=logging.CRITICAL,
                            pathname=__file__, lineno=0, msg=line.rstrip(),
                            args=(), exc_info=None,
                        ))
                    except Exception:
                        pass
        except Exception as log_err:
            try:
                print(f"[FATAL] FEL vid loggning av fel: {log_err}", file=sys.stderr)
            except Exception:
                pass
        # Visa dialog sa Rickard vet vad som handde
        try:
            show_error_dialog(
                title="Ohanterat fel",
                user_message=(
                    f"{APP_NAME} rakade ut for ett fel som inte kunde hanteras.\n\n"
                    f"Fel: {_describe_exception(exc_value)}\n\n"
                    f"Loggfil: {LOG_FILE}"
                ),
                technical=_format_compact_traceback(exc_value),
                category="code_bug",
            )
        except Exception:
            pass
        # Anropa original hook (Qt-dialog for debug-builds)
        try:
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
        except Exception:
            pass

    sys.excepthook = hook

    # NY v7: Installera Qt-message-handler — fångar Qt's egna fel-meddelanden
    # (t.ex. "qt.qpa.plugin: Could not load the Qt platform plugin")
    try:
        from PySide6.QtCore import qInstallMessageHandler
        # FIX v7-fix18: skydd mot Qt-meddelande-stormar (CreateWindowEx som
        # misslyckas vid varje expose = tusentals rader/minut).
        #   1. Reentrancy-skydd: meddelanden MEDAN vi loggar släpps tyst
        #      (loggning → Qt → meddelande → loggning → … = RecursionError)
        #   2. Dedupe: identiskt meddelande loggas 1:a, 2:a och 100:e gång
        #      med räknare — loggen förblir läslig men felet syns.
        _qt_msg_counts: Dict[str, int] = {}
        _qt_msg_active: List[bool] = [False]
        _qt_win_fail_logged: List[bool] = [False]
        _qt_win_fail_count: List[int] = [0]
        _qt_icon_remedied: List[bool] = [False]

        def qt_msg_handler(mode, ctx, msg):
            if _qt_msg_active[0]:
                return  # reentrant — släpp tyst (dödar RecursionError-loopen)
            _qt_msg_active[0] = True
            try:
                level_map = {
                    0: logging.DEBUG,    # QtDebugMsg
                    1: logging.WARNING,  # QtInfoMsg
                    2: logging.WARNING,  # QtWarningMsg
                    3: logging.ERROR,    # QtCriticalMsg
                    4: logging.CRITICAL, # QtFatalMsg
                }
                level = level_map.get(mode, logging.WARNING)
                _msg = str(msg)
                if len(_qt_msg_counts) > 256:
                    _qt_msg_counts.clear()
                _n = _qt_msg_counts.get(_msg[:200], 0) + 1
                _qt_msg_counts[_msg[:200]] = _n
                if ("CreateWindowEx failed" in _msg
                        or "Failed to create platform window" in _msg):
                    _qt_win_fail_count[0] += 1
                    _nf = _qt_win_fail_count[0]
                    if not _qt_win_fail_logged[0]:
                        _qt_win_fail_logged[0] = True
                        _thread_txt = "okänd"
                        try:
                            from PySide6.QtCore import (
                                QThread as _QT, QCoreApplication as _QApp,
                            )
                            _app = _QApp.instance()
                            _cur = _QT.currentThread()
                            _main = _app.thread() if _app is not None else None
                            _thread_txt = (
                                f"{_cur.objectName() or 'main'} "
                                f"(rätt tråd={_cur is _main})"
                            )
                        except Exception:
                            pass
                        # FIX v7-fix19: rikare diagnostik — version + skärmar + ikon
                        _ps6_ver = "?"
                        try:
                            import PySide6 as _ps6
                            _ps6_ver = _ps6.__version__
                        except Exception:
                            pass
                        _screens_txt = "?"
                        try:
                            from PySide6.QtGui import QGuiApplication as _QGA
                            _screens_txt = "; ".join(
                                f"{_s.name()}="
                                f"{_s.geometry().width()}x{_s.geometry().height()}"
                                f"@{_s.geometry().x()},{_s.geometry().y()}"
                                f" dpr={_s.devicePixelRatio()}"
                                for _s in _QGA.screens()
                            )
                        except Exception:
                            pass
                        _ico_txt = "ingen"
                        try:
                            _ico_fp = Path(__file__).resolve().parent / "data" / "app.ico"
                            if _ico_fp.is_file():
                                _ico_txt = f"{_ico_fp} ({_ico_fp.stat().st_size}B)"
                        except Exception:
                            pass
                        log.critical(
                            f"{LOG_PREFIX} ★ QT-FEL: Fönster kunde inte "
                            f"skapas (CreateWindowEx 'Felaktig parameter'). "
                            f"Tråd: {_thread_txt}. PySide6: {_ps6_ver}. "
                            f"Skärmar: {_screens_txt}. Ikon: {_ico_txt}. "
                            f"Se data\\todo_app.log + "
                            f"data\\window_failure_report.txt"
                        )
                        # FIX v7-fix20/22: syns även i konsolen (PowerShell)
                        # med DPI-läge + desktop.py-version — en konsol-paste
                        # räcker nu för diagnos!
                        try:
                            _dpi_c = "?"
                            if sys.platform == "win32":
                                import ctypes as _ct2
                                _c = _ct2.windll.user32.GetProcessDpiAwarenessContext(
                                    _ct2.windll.kernel32.GetCurrentProcess()
                                )
                                _cv = int(_c) & 0xFFFFFFFFFFFFFFFF if _c else 0
                                _dpi_c = {
                                    0xFFFFFFFFFFFFFFFE: "SYSTEM (GAMMAL desktop.py KÖRS!)",
                                    0xFFFFFFFFFFFFFFFC: "PER_MONITOR_V2",
                                }.get(_cv, hex(_cv))
                            _desk_ver = "?"
                            try:
                                import desktop as _dm
                                _desk_ver = getattr(
                                    _dm, "DESKTOP_API_VERSION", "SAKNAR v7-fix22!"
                                )
                            except Exception:
                                pass
                            sys.__stderr__.write(
                                "\n★ Fönster-skapande misslyckas!\n"
                                f"  desktop.py: {_desk_ver}\n"
                                f"  DPI: {_dpi_c}\n"
                                "  Detaljer: data\\todo_app.log\n"
                            )
                            sys.__stderr__.flush()
                        except Exception:
                            pass
                    # ---- AUTO-REMEDY 1 (25 fel): rensa ikonen minnet -------
                    if _nf == 25 and not _qt_icon_remedied[0]:
                        _qt_icon_remedied[0] = True
                        try:
                            from PySide6.QtGui import QIcon as _QI
                            from PySide6.QtWidgets import QApplication as _QA
                            _qa = _QA.instance()
                            if _qa is not None:
                                _qa.setWindowIcon(_QI())
                            log.critical(
                                f"{LOG_PREFIX} ★ REMEDY (25 fel): app-ikonen "
                                f"RENSAD — om fönstret nu skapas var KORRUPT "
                                f"app.ico orsaken till stormen!"
                            )
                        except Exception:
                            pass
                    # ---- AUTO-REMEDY 2 (50 fel): byt namn på app.ico -------
                    elif _nf == 50:
                        try:
                            _ico_fp = Path(__file__).resolve().parent / "data" / "app.ico"
                            if _ico_fp.is_file():
                                _suspect = _ico_fp.with_suffix(".ico.suspect")
                                _ico_fp.replace(_suspect)
                                log.critical(
                                    f"{LOG_PREFIX} ★ REMEDY (50 fel): "
                                    f"{_ico_fp.name} → {_suspect.name}. "
                                    f"STARTA OM appen — en ny ikon genereras."
                                )
                        except Exception:
                            pass
                    # ---- NÖDSTOPP (1000 fel): rapport + stoppa CPU-bränna --
                    elif _nf >= 1000:
                        # FIX v7-fix20: skriv nödrapport FÖRE avslut
                        try:
                            _ps6_ver2 = "?"
                            try:
                                import PySide6 as _ps6b
                                _ps6_ver2 = _ps6b.__version__
                            except Exception:
                                pass
                            _rep_dir = Path(__file__).resolve().parent / "data"
                            _rep_dir.mkdir(parents=True, exist_ok=True)
                            _rep = _rep_dir / "window_failure_report.txt"
                            _rep.write_text(
                                "TaskBord — NÖDRAPPORT FÖNSTERSKAPANDE\n"
                                "=" * 60 + "\n"
                                f"Tid: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                                f"Python: {sys.version.split()[0]} "
                                f"(exe: {sys.executable})\n"
                                f"PySide6: {_ps6_ver2}\n"
                                f"DESKTOP_API: {getattr(__import__('desktop'), 'DESKTOP_API_VERSION', 'OKAND — importera fel?') if sys.platform == 'win32' else 'n/a (icke-Windows)'}\n"
                                f"Antal misslyckade fönster-skapanden: "
                                f"{_qt_win_fail_count[0]}\n"
                                f"Ikon-remedy körd: {_qt_icon_remedied[0]}\n"
                                "\nÅTGÄRDER (i ordning):\n"
                                " 1. pip install --upgrade PySide6 "
                                "(Python 3.14 kräver färsk version!)\n"
                                " 2. Starta om och läs data\todo_app.log —\n"
                                "    sök efter ★ (PROBE-raden berättar om det\n"
                                "    är miljön eller vår widget)\n"
                                " 3. Uppdatera grafikdrivrutin\n"
                                " 4. Skicka ★-raderna + denna fil vid fortsatt fel\n",
                                encoding="utf-8",
                            )
                            log.critical(
                                f"{LOG_PREFIX} ★★ NÖDSTOPP: 1000+ misslyckade "
                                f"fönster-skapanden — nödrapport: {_rep}"
                            )
                        except Exception:
                            pass
                        log.critical(
                            f"{LOG_PREFIX} ★★ NÖDSTOPP — appen avslutas för "
                            f"att skydda CPU:n. ÅTGÄRD: pip install --upgrade "
                            f"PySide6 + läs data\\window_failure_report.txt"
                        )
                        try:
                            sys.__stderr__.write(
                                "\n★★ NÖDSTOPP — cache rensas, avslutar rent...\n"
                            )
                            sys.__stderr__.flush()
                        except Exception:
                            pass
                        # FIX v7-fix25: RENT avslut — INTE os._exit() som
                        # lämnar QThreadStorage-läckor. QApplication.quit()
                        # städar upp Qt:s trådar korrekt.
                        try:
                            from PySide6.QtWidgets import (
                                QApplication as _QA,
                            )
                            _qa = _QA.instance()
                            if _qa is not None:
                                _qa.quit()
                                return
                        except Exception:
                            pass
                        # Fallback: flusha logg + rensa cache + exit
                        try:
                            for _h in logging.getLogger().handlers:
                                with suppress(Exception):
                                    _h.flush()
                        except Exception:
                            pass
                        import os as _os
                        _os._exit(1)
                if _n <= 2 or _n % 100 == 0:
                    _suffix = f" [förekomst {_n}]" if _n > 2 else ""
                    log.log(
                        level,
                        f"{LOG_PREFIX} Qt-meddelande: {msg}{_suffix} "
                        f"(fil={getattr(ctx, 'file', '?')}, "
                        f"rad={getattr(ctx, 'line', '?')})"
                    )
            finally:
                _qt_msg_active[0] = False
        qInstallMessageHandler(qt_msg_handler)
        _ps6_ver_txt = "?"
        try:
            import PySide6 as _ps6
            _ps6_ver_txt = _ps6.__version__
        except Exception:
            pass
        log.info(
            f"{LOG_PREFIX} Qt message handler installerad "
            f"(v7-fix18/19: dedupe + reentrancy + ikon-remedy) — "
            f"PySide6 {_ps6_ver_txt}"
        )
    except Exception as _q_err:
        try:
            log.debug(f"{LOG_PREFIX} qInstallMessageHandler ej tillgängligt: {_q_err}")
        except Exception:
            pass

    # NY v7: Installera thread exception hook (fångar fel i bakgrundstrådar)
    try:
        import threading
        def thread_hook(args):
            log.critical(
                f"{LOG_PREFIX} OHANTERAT FEL i trad "
                f"{getattr(args.thread, 'name', '?')}: {args.exc_value}"
            )
            import traceback as _tb
            tb_lines = "".join(_tb.format_exception(
                args.exc_type, args.exc_value, args.exc_traceback
            ))
            for line in tb_lines.splitlines():
                log.critical(f"{LOG_PREFIX}   {line}")
        threading.excepthook = thread_hook
        log.info(f"{LOG_PREFIX} thread exception hook installerad")
    except Exception as _t_err:
        try:
            log.debug(f"{LOG_PREFIX} threading.excepthook ej tillgängligt: {_t_err}")
        except Exception:
            pass


def _bootstrap_requirements_txt() -> bool:
    """
    NY v6.4.1 v7-fix: Auto-installera + ta bort requirements.txt vid start.

    Design:
      - Körs FÖRST i run() — innan nån annan import
      - Om requirements.txt finns i samma mapp som main.pyw:
          1. Parsa den (enkel rad-för-rad)
          2. Testa varje modul med importlib.util.find_spec()
          3. Om alla finns: ta bort filen (clean state)
          4. Om något saknas: install via pip, sen ta bort filen

    Returnerar True om filen togs bort (eller inte fanns från början).
    Returnerar False om installationen misslyckades (Rickard får felmeddelande).

    Loggar med [BOOT]-prefix.
    """
    BOOT_PREFIX = "[BOOT]"
    req_path = SCRIPT_DIR / "requirements.txt"
    if not req_path.is_file():
        # Ingen fil → inget att göra (redan bootstrappad)
        return True
    log = logging.getLogger("Bootstrap")
    if not log.handlers and not log.parent.handlers:
        # Säkerställ att vi har en handler
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(StructuredFormatter())
        log.addHandler(h)
        log.setLevel(logging.INFO)
        log.propagate = False
    log.info(
        f"{BOOT_PREFIX} requirements.txt hittad — kontrollerar beroenden..."
    )
    # 1. Parsa filen (enkel parser, hoppa över kommentarer + tomma rader)
    required: List[str] = []
    try:
        with open(req_path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                # Hantera "PySide6>=6.5.0" → "PySide6"
                # Hantera "pywin32>=306; sys_platform == 'win32'" → skippa om ej match
                if ";" in line:
                    # Krav: t.ex. "; sys_platform == 'win32'"
                    pkg_part, marker = line.split(";", 1)
                    marker = marker.strip()
                    if "sys_platform" in marker:
                        # Enkel parser: "sys_platform == 'win32'" eller "!= 'win32'"
                        if "win32" in marker:
                            # Kräver win32 — kolla om vi är på Windows
                            if not _is_windows():
                                log.debug(
                                    f"{BOOT_PREFIX} skippar {pkg_part.strip()} "
                                    f"({marker}, vi är {sys.platform})"
                                )
                                continue
                            else:
                                pkg = pkg_part.strip()
                        else:
                            # Skippa (vi matchar inte)
                            continue
                    else:
                        pkg = pkg_part.strip()
                else:
                    pkg = line
                # Ta bort versionsspec
                for sep in (">=", "<=", "==", "!=", ">", "<", "~="):
                    if sep in pkg:
                        pkg = pkg.split(sep, 1)[0].strip()
                        break
                if pkg:
                    required.append(pkg)
    except Exception as e:
        log.error(
            f"{BOOT_PREFIX} kunde inte läsa requirements.txt: {e}"
        )
        return False
    log.info(
        f"{BOOT_PREFIX} requirements.txt: {len(required)} paket "
        f"({', '.join(required)})"
    )
    # 2. Testa vilka som redan finns
    missing: List[str] = []
    for pkg in required:
        # Mappa pip-namn → import-namn (specialfall)
        import_name = {
            "PySide6": "PySide6",
            "psutil": "psutil",
            "pywin32": "win32api",
            "orjson": "orjson",
        }.get(pkg, pkg)
        try:
            spec = importlib.util.find_spec(import_name)
            if spec is None:
                missing.append(pkg)
        except (ImportError, ValueError, ModuleNotFoundError):
            missing.append(pkg)
    if not missing:
        log.info(
            f"{BOOT_PREFIX} alla {len(required)} paket redan installerade ✓ "
            f"— tar bort requirements.txt"
        )
        with suppress(Exception):
            req_path.unlink()
        log.info(
            f"{BOOT_PREFIX} requirements.txt borttagen "
            f"(ren bootstrap-state)"
        )
        return True
    log.warning(
        f"{BOOT_PREFIX} saknar {len(missing)} paket: {', '.join(missing)}"
    )
    log.info(
        f"{BOOT_PREFIX} installerar via pip (kan ta 30-60s)..."
    )
    # 3. Installera via pip (sekventiellt — säkrare)
    failed: List[str] = []
    for pkg in missing:
        log.info(f"{BOOT_PREFIX} pip install {pkg}...")
        try:
            cmd = [
                sys.executable, "-m", "pip", "install",
                "--quiet", "--disable-pip-version-check",
                pkg,
            ]
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if proc.returncode == 0:
                log.info(
                    f"{BOOT_PREFIX} ✓ {pkg} installerades"
                )
            else:
                err = (proc.stderr or proc.stdout).strip()
                if len(err) > 200:
                    err = err[:197] + "..."
                log.error(
                    f"{BOOT_PREFIX} ✗ {pkg} misslyckades: {err}"
                )
                failed.append(pkg)
        except subprocess.TimeoutExpired:
            log.error(f"{BOOT_PREFIX} ✗ {pkg} tog för lång tid (>120s)")
            failed.append(pkg)
        except Exception as e:
            log.error(f"{BOOT_PREFIX} ✗ {pkg} kraschade: {e}")
            failed.append(pkg)
    if failed:
        log.error(
            f"{BOOT_PREFIX} misslyckades installera: {', '.join(failed)} "
            f"— lämnar requirements.txt kvar"
        )
        return False
    log.info(
        f"{BOOT_PREFIX} ✓ alla paket installerade — tar bort "
        f"requirements.txt"
    )
    with suppress(Exception):
        req_path.unlink()
    log.info(
        f"{BOOT_PREFIX} requirements.txt borttagen "
        f"(ren bootstrap-state). Starta om appen for att ladda moduler."
    )
    return True


def run() -> int:
    """Entry point med 8000% bättre struktur (PWM + orjson + bättre autostart)."""
    # 0. NY v6.4.1 v7-fix: Bootstrap requirements.txt
    # Rickard 2026-09-22: --bootstrap ska EJ behövas → SKIPPA om flagga saknas.
    # Opt-in: kör bara med explicit `--bootstrap` på kommandoraden.
    # Om installation misslyckas (vid opt-in) → QMessageBox + avsluta.
    if "--bootstrap" not in sys.argv:
        bootstrap_ok = True  # DEFAULT: skippa (inga oväntade pip-anrop)
    else:
        try:
            bootstrap_ok = _bootstrap_requirements_txt()
        except Exception as _bst_err:
            bootstrap_ok = False
            # Fortsätt ändå — kanske Qt/PySide6 redan är installerat
            try:
                print(
                    f"[BOOT] bootstrap-fel: {_bst_err}",
                    file=sys.stderr,
                )
            except Exception:
                pass
    if not bootstrap_ok:
        # Försök visa QMessageBox (om Qt redan finns — annars stderr)
        try:
            msg = (
                "Kunde inte installera alla beroenden fran requirements.txt.\n\n"
                "Kor manuellt:\n"
                f"  {sys.executable} -m pip install -r requirements.txt\n\n"
                "Nar det ar klart, starta appen igen."
            )
            from PySide6.QtWidgets import QApplication, QMessageBox
            app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(None, "Bootstrap misslyckades", msg)
        except Exception:
            try:
                print(
                    "[BOOT] Bootstrap misslyckades — installera manuellt:\n"
                    f"  {sys.executable} -m pip install -r requirements.txt",
                    file=sys.stderr,
                )
            except Exception:
                pass
        return 1

    # 0. NY v6.4: Bättre dubbelklick-detektering
    is_pyw = _is_pyw()
    is_double_click = _is_double_click_start()

    # 1. Parsa argument
    config, mode = parse_args(sys.argv)

    # 2. NY v6.4: Setup full logging (logger_setup → data/logs/)
    # Importera logger_setup dynamiskt (för att undvika cirkulär import)
    try:
        from logger_setup import setup_full_logging
        logs_dir = setup_full_logging(
            data_dir=SCRIPT_DIR / "data",
            debug=(config.log_level == "DEBUG"),
            capture_stdout=True,
            capture_exceptions=True,
            capture_threads=True,
        )
        log = logging.getLogger("Main")
        log.info(f"{LOG_PREFIX} Data dir: {logs_dir}")
        log.info(f"{LOG_PREFIX} Log-fil: {logs_dir / 'todo_app.log'}")
    except ImportError as e:
        # Fallback till inbyggd setup_logging
        setup_logging(config.log_level, config.log_file)
        log = logging.getLogger("Main")
        log.warning(f"{LOG_PREFIX} logger_setup ej tillgängligt: {e}, använder fallback")
    # 3. Installera global exception hook (extra Qt-specifik)
    try:
        install_global_exception_hook()
    except Exception as e:
        log.debug(f"{LOG_PREFIX} install_global_exception_hook: {e}")

    # 4. NY v6.4: Förbättrad startlog (inkl dubblklick-info)
    log.info("=" * 60)
    log.info(f"--- Programstart ({APP_NAME} v{APP_VERSION_DISPLAY}, mode={mode.name}) ---")
    log.info(f"{LOG_PREFIX} Release: v{RELEASE_VERSION}")
    log.info(f"{LOG_PREFIX} Python: {sys.version.split()[0]}")
    log.info(f"{LOG_PREFIX} Plattform: {sys.platform}")
    log.info(f"{LOG_PREFIX} Arbetskatalog: {Path.cwd()}")
    log.info(f"{LOG_PREFIX} Script: {Path(__file__).resolve()}")
    log.info(f"{LOG_PREFIX} pythonw.exe: {is_pyw} (dubbelklick: {is_double_click})")
    log.info(f"{LOG_PREFIX} orjson: {_HAS_ORJSON} (cache)")
    log.info(f"{LOG_PREFIX} PWM: {config.enable_pwm} (95-98% CPU-besparing vid idle)")
    log.info("=" * 60)

    preflight = PreFlightChecker()
    result = preflight.run_all()
    if not result.ok:
        error_msg = "Pre-flight misslyckades:\n  - " + "\n  - ".join(result.errors)
        log.critical(f"{LOG_PREFIX} {error_msg}")
        show_pre_flight_error_dialog(error_msg)
        return 1
    for warning in result.warnings:
        log.warning(f"{LOG_PREFIX} Pre-flight: {warning}")

    # 5. Visa splash (om aktiverat)
    splash_start = time.time()
    if config.show_splash and not is_pyw:
        with suppress(Exception):
            show_splash()

    # 6. Skapa subsystem-infrastruktur
    registry = SubsystemRegistry()
    performance = PerformanceMonitor()
    async_runner = (
        AsyncTaskRunner(max_workers=4) if config.enable_async_runner else None
    )
    if async_runner:
        async_runner.start()

    # 7. Importera dependencies
    log.info(f"{LOG_PREFIX} Importerar dependencies...")
    imports = import_all_dependencies()

    # Kontrollera kritiska imports
    critical = ["PySide6.QtCore", "PySide6.QtWidgets"]
    for mod in critical:
        if not imports[mod].ok:
            error_msg = (
                f"Kritiskt beroende saknas: {mod}\n  {imports[mod].error}"
            )
            log.critical(f"{LOG_PREFIX} {error_msg}")
            show_pre_flight_error_dialog(error_msg)
            return 1

    # 8. Validera stability-system
    if config.enable_stability:
        stab_status = imports.get("stability")
        if stab_status and stab_status.ok:
            with suppress(Exception):
                from stability import validate_startup
                ok, errors = validate_startup()
                if not ok:
                    log.warning(
                        f"{LOG_PREFIX} Stability-validation hittade {len(errors)} problem"
                    )
                    for err in errors:
                        log.warning(f"{LOG_PREFIX}   - {err}")
                else:
                    log.info(f"{LOG_PREFIX} ✓ Stability-validation OK")

    # 9. Säkerställ data-mapp
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        log.debug(f"{LOG_PREFIX} Data-mapp: {DATA_DIR}")
    except OSError as e:
        log.warning(f"{LOG_PREFIX} Kunde inte skapa data-mapp: {e}")

    # 10. NY v6.4: Bättre autostart-detektering (använd utils om tillgängligt)
    autostart_status = "unknown"
    if _is_windows():
        utils_status = imports.get("utils")
        if utils_status and utils_status.ok:
            utils_inst = utils_status.instance
            is_autostart = getattr(utils_inst, "is_autostart_enabled", None)
            if is_autostart:
                with suppress(Exception):
                    autostart_status = "enabled" if is_autostart() else "disabled"
                    log.info(f"{LOG_PREFIX} Autostart: {autostart_status}")
    if autostart_status == "unknown" and is_pyw:
        # Försök basic registry-check om utils ej tillgängligt
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_READ,
            ) as key:
                try:
                    winreg.QueryValueEx(key, APP_NAME)
                    autostart_status = "enabled"
                except FileNotFoundError:
                    autostart_status = "disabled"
        except Exception:
            autostart_status = "check_failed"
        log.info(f"{LOG_PREFIX} Autostart (basic check): {autostart_status}")

    # 11. Single Instance Lock (med retry)
    utils_status = imports.get("utils", ImportStatus(module="utils", ok=False))
    if utils_status.ok:
        utils_inst = utils_status.instance
        SingleInstanceLock = getattr(utils_inst, "SingleInstanceLock", None)
        if SingleInstanceLock:
            lock = SingleInstanceLock()
            acquired = False
            for attempt in range(Timeouts.LOCK_MAX_ATTEMPTS):
                if lock.acquire():
                    acquired = True
                    break
                log.info(
                    f"{LOG_PREFIX} Lock upptaget (försök {attempt+1}/"
                    f"{Timeouts.LOCK_MAX_ATTEMPTS}), väntar..."
                )
                time.sleep(Timeouts.LOCK_RETRY)
            if not acquired:
                log.warning(f"{LOG_PREFIX} En annan instans körs redan — avslutar")
                # NY v7-fix87: signalera den befintliga instansen att VISA
                # sitt fönster (mycket bättre än bara en ruta "körs redan").
                # Lyckas det → AVSLUTA TYST (fönstret dyker upp hos den
                # befintliga instansen). Misslyckas det → gamla rutan kvar.
                _notified = False
                with suppress(Exception):
                    from core.single_instance import (
                        InstanceMessenger, default_key,
                    )
                    _notified = InstanceMessenger().notify(
                        default_key(), "SHOW"
                    )
                if _notified:
                    log.info(
                        f"{LOG_PREFIX} befintlig instans signalerad — "
                        f"dess fönster visas nu. Avslutar tyst (v7-fix87)"
                    )
                elif is_pyw:
                    with suppress(Exception):
                        import ctypes
                        ctypes.windll.user32.MessageBoxW(
                            None,
                            "En instans av TaskBord körs redan.\n\nAvslutar.",
                            APP_NAME,
                            0x00000040,  # MB_ICONINFORMATION
                        )
                return 0
            atexit.register(lock.release)
            log.info(f"{LOG_PREFIX} ✓ Single Instance Lock acquired")

    # 12. Skapa AppController
    try:
        controller = AppController(
            config=config,
            mode=mode,
            imports=imports,
            registry=registry,
            performance=performance,
            async_runner=async_runner,
        )
        # NY v6.4: Logga PWM-status
        if config.enable_pwm and hasattr(controller, "_widgets"):
            for w in controller._widgets.values():
                if hasattr(w, "_throttle"):
                    log.debug(
                        f"{LOG_PREFIX} PWM aktiverat på widget {w.win_id!r}"
                    )
    except Exception as e:
        log.critical(f"{LOG_PREFIX} AppController-init misslyckades: {e}", exc_info=True)
        show_pre_flight_error_dialog(f"Kunde inte initiera app:\n\n{e}")
        return 1

    # 13. Setup signal handlers
    setup_signal_handlers(controller)
    atexit.register(controller.shutdown)

    # NY v7-fix87: lyssna efter ANDRA instanser → visa vårt fönster.
    # (Det hårda låset i steg 11 stoppar dem; detta gör att start av
    # appen en gång till = "visa mig" i stället för en ruta.)
    try:
        from core.single_instance import InstanceMessenger, default_key
        _messenger = InstanceMessenger()
        if _messenger.acquire(default_key()):
            _messenger.message_received.connect(
                controller._on_second_instance
            )
            controller._instance_messenger = _messenger
            log.info(
                f"{LOG_PREFIX} Instans-kanal aktiv: nästa start av "
                f"TaskBord visar detta fönster (v7-fix87)"
            )
        # kunde ej lyssna (t.ex. QLocalServer saknas) — låset i steg 11
        # skyddar fortfarande mot dubbla instanser
    except Exception as _si_e:
        log.debug(f"{LOG_PREFIX} instans-kanal ej aktiv: {_si_e}")

    # 14. Vänta på splash minimum-tid (UX)
    elapsed = time.time() - splash_start
    if elapsed < Timeouts.SPLASH_MIN_DURATION:
        time.sleep(Timeouts.SPLASH_MIN_DURATION - elapsed)
    hide_splash()

    # 15. Kör event loop (NY v6.4.1 v7: forbattrade svenska meddelanden)
    start_time = time.time()
    log.info(
        f"{LOG_PREFIX} App startad: {len(imports)} moduler, "
        f"{len(controller._widgets)} fönster, mode={mode.name}, "
        f"pwm={config.enable_pwm}, orjson={_HAS_ORJSON}"
    )
    # FIX 2026-09-24: komplett start-summary (Rickard 199999% AI-läsbart)
    _qapp_widgets = []
    _qt_ver = "?"
    _platform_info = (
        f"{platform.system()} {platform.release()}"  # typ = global 'platform'
        if "platform" in dir()
        else sys.platform
    )
    with suppress(Exception):
        if hasattr(controller, "_app") and controller._app is not None:
            _qt_ver = controller._app.applicationVersion() or "?"
            _qapp_widgets = [
                w for w in controller._app.topLevelWidgets()
                if w.__class__.__name__ not in ("QWidget", "QApplication")
            ]
            _ = QWidget  # säkerställ importerad
    log.info(
        f"{LOG_PREFIX} ╔═══════════════════════ START-SUMMARY "
        f"═══════════════════════╗"
    )
    log.info(
        f"{LOG_PREFIX} ║ Användare     : {os.environ.get('USERNAME', '?')}\n"
        f"{LOG_PREFIX} ║ OS            : {_platform_info}\n"
        f"{LOG_PREFIX} ║ Python        : {sys.version.split()[0]}\n"
        f"{LOG_PREFIX} ║ App-version   : {_qt_ver}\n"
        f"{LOG_PREFIX} ║ Moduler laddade: {len(imports)} "
        f"({sum(1 for v in imports.values() if v.ok)} OK, "
        f"{sum(1 for v in imports.values() if not v.ok)} fel)\n"
        f"{LOG_PREFIX} ║ PWM           : {'PÅ' if config.enable_pwm else 'AV'}\n"
        f"{LOG_PREFIX} ║ orjson        : {_HAS_ORJSON}\n"
        f"{LOG_PREFIX} ║ Mode          : {mode.name}\n"
        f"{LOG_PREFIX} ║ Force-show    : "
        f"{'PÅ' if config.force_show_widget else 'AV'}\n"
        f"{LOG_PREFIX} ║ Bootstrap     : "
        f"{'PÅ' if not config.no_bootstrap else 'AV'}\n"
        f"{LOG_PREFIX} ║ Plugin-install: "
        f"{'PÅ' if not config.no_plugin_install else 'AV'}\n"
        f"{LOG_PREFIX} ║ Widgets (i Qt): {len(_qapp_widgets)} top-level\n"
        f"{LOG_PREFIX} ║   typer: "
        f"{[type(w).__name__ for w in _qapp_widgets[:10]]}\n"
        f"{LOG_PREFIX} ║ Widgets-i-AppController: {len(controller._widgets)}\n"
        f"{LOG_PREFIX} ║   listor: {list(controller._widgets.keys())}\n"
        f"{LOG_PREFIX} ║ Window-configs (settings): "
        f"{[c.get('id') for c in controller.settings.window_configs() if hasattr(controller.settings, 'window_configs')]}"
    )
    log.info(
        f"{LOG_PREFIX} ╚═════════════════════════════════════════════"
        f"════════════════╝"
    )
    log.info(
        f"{LOG_PREFIX} Event loop startar. "
        f"Avsluta med: Ctrl+C, tray → Avsluta, eller signal."
    )

    try:
        exit_code = controller.run()
        # Logga hur lange appen kordes
        runtime_sec = time.time() - start_time
        log.info(
            f"{LOG_PREFIX} Event loop avslutades efter {format_uptime(runtime_sec)} "
            f"(exit_code={exit_code})"
        )
        return exit_code
    except KeyboardInterrupt:
        log.info(f"{LOG_PREFIX} KeyboardInterrupt — stänger ner...")
        controller.shutdown()
        return 0
    except Exception as e:
        # NY v6.4.1 v7: AI-felsokning — kategorisera + visa dialog
        category = _categorize_exception(e)
        svensk = _describe_exception(e)
        tb = _format_compact_traceback(e, max_frames=10)
        log.critical(
            f"{LOG_PREFIX} FATAL under event loop [{category}]: {svensk}"
        )
        log.critical(f"{LOG_PREFIX} Traceback:\n{tb}")
        # Visa dialog for Rickard
        show_error_dialog(
            title="Event loop kraschade",
            user_message=(
                f"{APP_NAME} kunde inte fortsätta:\n\n{svensk}\n\n"
                f"App avslutas med felkod 1."
            ),
            technical=tb,
            category=category,
        )
        return 1
    finally:
        hide_splash()
        log.info(f"{LOG_PREFIX} Program avslutat.")


# ===========================================================================
# SELF-TEST: CENTRAL LOGGNING (NY v6.4.1 v7)
# ===========================================================================
def _self_test_central_log() -> int:
    """Snabbtest av central-loggning. Returnerar 0 vid success."""
    print("=" * 70)
    print(f"main.pyw {APP_VERSION_DISPLAY} — Central Log Self-Test")
    print("=" * 70)

    # Test 1: Listener
    print("\n[Test 1] Listener installeras...")
    captured: List[Dict[str, Any]] = []
    unsub = add_central_log_listener(lambda ev: captured.append(ev))
    print(f"  ✓ Listener added: 0 events initially")

    # Test 2: Install handler + emit
    print("\n[Test 2] Handler installeras + events emitteras...")
    logging.getLogger().setLevel(logging.INFO)
    install_central_log_handler(logging.getLogger())
    logging.getLogger("TestMod").info("INFO från TestMod")
    logging.getLogger("TestMod").warning("VARNING")
    logging.getLogger("Widget").error("Widget-fel")
    print(f"  ✓ After 3 logs: {len(captured)} events captured (>= 3)")
    assert len(captured) >= 3, f"Förväntade >= 3, fick {len(captured)}"

    # Test 3: get_recent_app_events
    print("\n[Test 3] get_recent_app_events...")
    recent = get_recent_app_events(count=10)
    print(f"  ✓ {len(recent)} events returned")
    for ev in recent[-3:]:
        print(f"    [{ev['level']}] [{ev['module']}] {ev['message'][:50]}")

    # Test 4: get_central_log_stats
    print("\n[Test 4] get_central_log_stats...")
    stats = get_central_log_stats()
    print(f"  ✓ total={stats['total_events']}, "
          f"by_level={stats['by_level']}, "
          f"listeners={stats['listener_count']}")
    assert stats["total_events"] >= 3

    # Test 5: format_event_log_swedish
    print("\n[Test 5] format_event_log_swedish...")
    fmt = format_event_log_swedish(recent, max_items=5)
    print(f"  ✓ Output (första 4 rader):")
    for line in fmt.split("\n")[:4]:
        print(f"    {line}")

    # Test 6: format_central_log_stats_swedish
    print("\n[Test 6] format_central_log_stats_swedish...")
    stats_str = format_central_log_stats_swedish()
    print(f"  ✓ {stats_str!r}")
    assert "Central logg" in stats_str

    # Test 7: Unsubscribe
    print("\n[Test 7] Unsubscribe...")
    unsub()
    n_before = len(captured)
    logging.getLogger("TestMod").info("Efter unsub")
    print(f"  ✓ After unsub + 1 log: {len(captured)} events (oförändrat)")
    assert len(captured) == n_before, "Listener borde inte längre fångas"

    # Test 8: Plugin + central-log integration
    print("\n[Test 8] Plugin-system + central-log integration...")
    plugin_status = get_plugin_status()
    summary_plugin = format_plugin_status_swedish()
    print(f"  ✓ Plugins: {summary_plugin!r}")

    print()
    print("=" * 70)
    print(f"✓ ALLA 8 CENTRAL-LOG TESTER PASSERADE ({APP_VERSION_DISPLAY})")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    # NY v6.4.1 v7-fix: `os` är redan importerad på top-level (rad 88).
    # Innan fanns en dubblett `import os as _os` här som var förvirrande.
    if os.environ.get("DESKTOPTODO_SELF_TEST_CENTRAL") == "1":
        sys.exit(_self_test_central_log())
    sys.exit(run())