# -*- coding: utf-8 -*-
"""
logger_setup.py — Centraliserad loggning (NYTT v6.4) — v6.4.1 v7 (EN fil, AI-säker)
=====================================================================================================
ALLT hamnar i EN fil (Rickard 2026-09-22):
  • data/todo_app.log                (alla events, DEBUG+, daily-rotating, 7 backups)

Ingen app_*.log / debug_*.log / session_*.log längre.

Fångar:
  • Alla `logger.*()`-anrop
  • `print()` → omdirigeras till logg
  • `sys.stdout` / `sys.stderr` → omdirigeras
  • Unhandled exceptions
  • Qt warnings (qtlogging category)
  • Win32 errors (med traceback)
  • Thread names + process IDs
  • Function names + line numbers
  • Millisekund-precision

Användning:
    from logger_setup import setup_full_logging
    setup_full_logging(debug=True)  # Sätt DEBUG-nivå + alla handlers
"""
from __future__ import annotations

import io
import logging
import logging.handlers
import os
import platform
import shutil
import socket
import sys
import threading
import time
import traceback
from contextlib import contextmanager, suppress
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional

# PySide6-detektering (för Qt event-filter)
try:
    import PySide6
    _QT_AVAILABLE = True
except ImportError:
    _QT_AVAILABLE = False

# ===========================================================================
# KONSTANTER
# ===========================================================================
LOG_PREFIX: str = "[LOG]"
LOGGER_SETUP_VERSION: str = "6.4.1-v7"

# NY v6.4.1 v7: Setup en modul-logger (anvands av helpers nedan)
_module_logger = logging.getLogger("LoggerSetup")


# ===========================================================================
# AI-FELSÖKNING 10000% (NY v6.4.1 v7)
# ===========================================================================

_LOGGER_ERROR_TRANSLATIONS: Dict[str, str] = {
    "ImportError": "Kan inte hitta en Python-modul",
    "AttributeError": "Objektet saknar en metod eller attribut",
    "TypeError": "Fel typ av argument skickades",
    "ValueError": "Ogiltigt varde skickades",
    "KeyError": "Nyckel saknas i log-data",
    "FileNotFoundError": "Logg-filen hittades inte",
    "PermissionError": "Saknar ratigheter till logg-katalogen",
    "OSError": "Operativsystem-fel vid loggning",
    "IOError": "In/ut-fel vid loggning",
    "UnicodeDecodeError": "Kunde inte avkoda log-rad (fel teckenkodning)",
}


def _describe_logger_exception(exc: BaseException) -> str:
    """NY v6.4.1 v7: Skapar en anvandarvanlig svensk beskrivning."""
    try:
        exc_type = type(exc).__name__
        svensk_typ = _LOGGER_ERROR_TRANSLATIONS.get(
            exc_type, f"Tekniskt fel ({exc_type})"
        )
        msg = str(exc).strip()
        if not msg:
            return svensk_typ
        return f"{svensk_typ}: {msg}"
    except Exception:
        return f"Okant fel: {type(exc).__name__}"


def _format_compact_traceback(exc: BaseException, max_frames: int = 5) -> str:
    """NY v6.4.1 v7: Kompakt stacktrace (sista N frames)."""
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


def _categorize_logger_exception(exc: BaseException) -> str:
    """NY v6.4.1 v7: Kategorisera undantag for prioriterad felhantering."""
    try:
        exc_type = type(exc).__name__
        if exc_type in ("ValueError", "KeyError", "TypeError"):
            return "user_input"
        if exc_type in ("PermissionError",):
            return "permission"
        if exc_type in (
            "OSError", "IOError", "FileNotFoundError",
            "TimeoutError", "ConnectionError",
        ):
            return "system"
        if exc_type in ("UnicodeDecodeError", "UnicodeEncodeError"):
            return "data_corrupt"
        return "code_bug"
    except Exception:
        return "code_bug"


@contextmanager
def safe_run(
    operation_name: str,
    *,
    log_errors: bool = True,
    reraise: bool = False,
) -> Generator[Dict[str, Any], None, None]:
    """NY v6.4.1 v7: Context-manager for komplett felhantering."""
    start = time.perf_counter()
    ctx: Dict[str, Any] = {
        "start_time": start,
        "operation": operation_name,
        "errors": [],
    }
    _module_logger.debug(
        f"{LOG_PREFIX} safe_run START: {operation_name}"
    )
    try:
        yield ctx
        duration = (time.perf_counter() - start) * 1000
        _module_logger.debug(
            f"{LOG_PREFIX} safe_run OK: {operation_name} ({duration:.2f}ms)"
        )
    except Exception as exc:
        duration = (time.perf_counter() - start) * 1000
        category = _categorize_logger_exception(exc)
        ctx["errors"].append(exc)
        if log_errors:
            _module_logger.error(
                f"{LOG_PREFIX} safe_run FEL: {operation_name} "
                f"({duration:.2f}ms, kategori={category}): "
                f"{_describe_logger_exception(exc)}"
            )
        if reraise:
            raise


def _validate_logger_state() -> List[str]:
    """
    NY v6.4.1 v7: Diagnostisk funktion som kontrollerar logger_setup.

    Returns:
        Lista med svenska problem-beskrivningar
    """
    problems: List[str] = []
    try:
        if _module_logger is None:
            problems.append("Kritisk: modulens logger ar None")
        # Test att logging fungerar
        try:
            test_logger = logging.getLogger("test_validation")
            test_logger.info("test")
            problems.append("")  # placeholder
            problems.pop()
        except Exception as e:
            problems.append(
                f"logging.info() misslyckades: "
                f"{_describe_logger_exception(e)}"
            )
        # Log-dir atkomlig?
        try:
            ld = get_logs_dir()
            if not ld.exists():
                problems.append(f"Log-dir finns inte: {ld}")
            elif not os.access(ld, os.W_OK):
                problems.append(f"Log-dir ej skrivbar: {ld}")
        except Exception as e:
            problems.append(
                f"get_logs_dir() misslyckades: "
                f"{_describe_logger_exception(e)}"
            )
        if problems:
            _module_logger.warning(
                f"{LOG_PREFIX} _validate_logger_state: "
                f"{len(problems)} problem hittade"
            )
            for p in problems:
                _module_logger.warning(f"  - {p}")
        else:
            _module_logger.debug(
                f"{LOG_PREFIX} _validate_logger_state: alla tester OK"
            )
    except Exception as e:
        problems.append(
            f"_validate_logger_state kraschade: "
            f"{_describe_logger_exception(e)}"
        )
    return problems


def summarize_logging_health() -> str:
    """NY v6.4.1 v7: Svensk en-rads-sammanfattning av loggning."""
    try:
        try:
            ld = get_logs_dir()
        except Exception:
            return f"v{LOGGER_SETUP_VERSION} • log-dir ej atkomlig"
        if not ld.exists():
            return f"v{LOGGER_SETUP_VERSION} • log-dir finns inte"
        # Rakna filer
        log_files = list(ld.glob("*.log"))
        total_size = sum(f.stat().st_size for f in log_files if f.exists())
        return (
            f"v{LOGGER_SETUP_VERSION} • {len(log_files)} log-filer • "
            f"{total_size / 1024:.1f} KB totalt"
        )
    except Exception as e:
        _module_logger.debug(
            f"{LOG_PREFIX} summarize_logging_health misslyckades: {e}"
        )
        return f"(kunde inte sammanfatta: {type(e).__name__})"


def get_logger_diagnostics() -> Dict[str, Any]:
    """NY v6.4.1 v7: Detaljerad diagnostik-rapport for support-fall."""
    with safe_run("get_logger_diagnostics") as ctx:
        problems = _validate_logger_state()
        summary = summarize_logging_health()
        ctx["ok"] = True
        return {
            "module": "logger_setup",
            "logger_version": LOGGER_SETUP_VERSION,
            "problems": problems,
            "problem_count": len(problems),
            "summary_swedish": summary,
        }


_LOGGER_SETUP_PLUGIN_DEPS: Final[Tuple[Dict[str, str], ...]] = ()


def get_logger_setup_plugin_deps() -> List[Dict[str, str]]:
    """NY v6.4.1 v7: Optional Python-beroenden som logger_setup vill ha."""
    return [dict(d) for d in _LOGGER_SETUP_PLUGIN_DEPS]


__all__ = [
    # Constants
    "LOG_PREFIX", "LOGGER_SETUP_VERSION",
    "DEFAULT_DATA_DIR", "LOGS_SUBDIR",
    # Classes
    "DetailedFormatter", "StreamToLogger",
    # Setup functions
    "setup_full_logging", "quick_setup",
    "exception_hook", "thread_excepthook",
    # Log analysis
    "get_recent_logs", "search_logs", "get_log_stats",
    "create_log_snapshot", "get_logs_dir",
    # AI-felsökning (NY v6.4.1 v7)
    "_LOGGER_ERROR_TRANSLATIONS",
    "_describe_logger_exception", "_format_compact_traceback",
    "_categorize_logger_exception", "_validate_logger_state",
    "safe_run",
    # Svenska formatters (NY v6.4.1 v7)
    "summarize_logging_health",
    # Diagnostik (NY v6.4.1 v7)
    "get_logger_diagnostics",
    # Plugin-coupling (NY v6.4.1 v7)
    "get_logger_setup_plugin_deps",
]
# FIX v7-fix15: rot-data (samma som main.pyw) — inte core/data (split-brain-fix)
DEFAULT_DATA_DIR: Path = Path(__file__).resolve().parent.parent / "data"
LOGS_SUBDIR: str = "logs"
# EN logg-fil (v6.4.1 v7): sätts av setup_full_logging → används av hjälpare
SINGLE_LOG_NAME: str = "todo_app.log"
_ACTIVE_LOG_PATH: Optional[Path] = None

# Standard loggformat (med all info vi kan samla)
STANDARD_FORMAT = (
    "%(asctime)s.%(msecs)03d | %(levelname)-8s | "
    "%(name)-20s | [%(threadName)-12s#%(thread)d] | "
    "%(funcName)-20s:%(lineno)-4d | %(message)s"
)
STANDARD_DATEFMT = "%Y-%m-%d %H:%M:%S"

# Standardfält att utesluta från extra-context
STANDARD_ATTRS = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "asctime", "taskName",
})

# Filer som roterar dagligen
DAILY_FILES = {
    "app": "app_{date}.log",
    "debug": "debug_{date}.log",
    "qt": "qt_events_{date}.log",
    "win32": "win32_calls_{date}.log",
}

# Session-fil (enskild körning)
SESSION_FILE = "session_{timestamp}.log"


# ===========================================================================
# CUSTOM FORMATTER (med extra-context)
# ===========================================================================

class DetailedFormatter(logging.Formatter):
    """Formatter med extra-context (key=value)."""

    def __init__(self, fmt: str = STANDARD_FORMAT, datefmt: str = STANDARD_DATEFMT):
        super().__init__(fmt, datefmt)

    def format(self, record: logging.LogRecord) -> str:
        # NY v6.4.1 v7-fix8: try/except runt HELA format() — EN formatter-error
        # ska ALDRIG trigga "--- Logging error ---" (vilket recursion-spammar loggen).
        try:
            return self._format_unsafe(record)
        except Exception as _fmt_err:
            # Returnera minimal fallback så logging-systemet fortsätter fungera.
            try:
                return (
                    f"{record.levelname} | {record.name} | "
                    f"{record.getMessage()[:200]} | "
                    f"<formatter_error: {type(_fmt_err).__name__}>"
                )
            except Exception:
                return f"{record.levelname} | <format-error>"

    def _format_unsafe(self, record: logging.LogRecord) -> str:
        # Hämta extra-context (key=value)
        extras = []
        for key, value in record.__dict__.items():
            if key not in STANDARD_ATTRS and not key.startswith("_"):
                try:
                    # FIX 2026-09-25 v7-fix8: konvertera till str säkert
                    # (Qt-objekt, ctypes-strukturer kan krascha `!r`)
                    extras.append(f"{key}={value!r}")
                except Exception:
                    try:
                        extras.append(f"{key}=<{type(value).__name__}>")
                    except Exception:
                        extras.append(f"{key}=<?>")
        extra_str = " | " + " ".join(extras) if extras else ""
        # Format med extras
        try:
            formatted = super().format(record)
        except Exception:
            # Fallback till enkel format
            formatted = (
                f"{record.levelname} | {record.name} | {record.getMessage()}"
            )
        return formatted + extra_str


# ===========================================================================
# STDOUT/STDERR REDIRECT (fångar print())
# ===========================================================================

class StreamToLogger:
    """
    Omdirigera sys.stdout / sys.stderr till logger.
    Detta fångar ALLA print() och ohanterade stderr-output.

    NY v6.4.1 v7-fix8: Recursion-skydd.
    Bug: write() anropar self._logger.log() → logging skriver till sys.stderr
    → samma StreamToLogger.write() → oändlig recursion ("--- Logging error ---" spammas).
    Fix: reentrant-flagga — vid aktiv logging-output, skriv direkt till original-stream.
    """

    def __init__(self, logger: logging.Logger, level: int = logging.INFO):
        self._logger = logger
        self._level = level
        self._linebuf = ""
        self._original_stream: Optional[io.TextIOBase] = None
        # FIX 2026-09-25 v7-fix8: reentrant-flagga
        self._in_logging: bool = False

    def write(self, buf: str) -> int:
        # FIX 2026-09-25 v7-fix8: undvik recursion — om vi redan är i en logger.log()
        # så ska write() gå till original-stream (inte via samma StreamToLogger).
        if self._in_logging:
            try:
                if self._original_stream is not None:
                    return self._original_stream.write(buf)
                return len(buf)
            except Exception:
                return len(buf)
        self._in_logging = True
        try:
            for line in buf.rstrip().splitlines():
                # NY v6.4.1 v7-fix8: suppress exceptions vid logging —
                # EN logging-error ska ALDRIG ta ner applikationen.
                try:
                    self._logger.log(self._level, line)
                except Exception:
                    pass
            return len(buf)
        finally:
            self._in_logging = False

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False

    def install(self) -> None:
        """Installera som sys.stdout / sys.stderr."""
        # Spara original
        if self._original_stream is None:
            self._original_stream = sys.stdout
        sys.stdout = self  # type: ignore[assignment]
        sys.stderr = self  # type: ignore[assignment]

    def restore(self) -> None:
        """Återställ original streams."""
        if self._original_stream is not None:
            sys.stdout = self._original_stream
            sys.stderr = self._original_stream


# ===========================================================================
# UNHANDLED EXCEPTION HOOK
# ===========================================================================

_original_excepthook = sys.excepthook


def exception_hook(exc_type, exc_value, exc_traceback):
    """Fångar ALLA ohanterade undantag."""
    if issubclass(exc_type, KeyboardInterrupt):
        # Tillåt Ctrl+C
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    # Logga
    logger = logging.getLogger("UncaughtException")
    logger.critical(
        "OHANTERAT UNDANTAG (fångat av logger_setup):",
        exc_info=(exc_type, exc_value, exc_traceback),
    )
    # Skriv till original hook (för Qt-dialog)
    _original_excepthook(exc_type, exc_value, exc_traceback)


# ===========================================================================
# THREAD EXCEPTION HOOK
# ===========================================================================

def thread_excepthook(args):
    """Fångar undantag i trådar (Python 3.8+)."""
    logger = logging.getLogger("ThreadException")
    logger.critical(
        f"TRÅD-UNFANGAT UNDANTAG i {args.thread.name!r}:",
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )


# ===========================================================================
# WINERROR 32-SÄKER ROTATION (Etapp 9, v7-fix13)
# ===========================================================================

class WinSafeTimedRotatingFileHandler(logging.handlers.TimedRotatingFileHandler):
    """
    WinError 32-säker tidsroterande fil-handler (Etapp 9, v7-fix13).

    Rickards riktiga fel (2026-09-25):
        PermissionError: [WinError 32] Det går inte att komma åt filen
        eftersom den används av en annan process:
        'D:\\Program\\todo\\data\\todo_app.log' -> 'todo_app.log.1'

    Varför stdlib kraschar på Windows:
      Stdlib-rotate() använder os.rename(source, dest) som misslyckas om:
        * DEST redan finns (FileExistsError — t.ex. kvar efter en krashad
          tidigare rotation)
        * KÄLLAN hålls öppen av en annan process utan FILE_SHARE_DELETE
          (andra app-instansen, zombie-pythonw.exe, antivirus/backup-skanning)
      Fel ur doRollover() propagerar ut i emit-pipelinen →
      "--- Logging error ---"-spam i loggen.

    Lösning — 3 nivåer (rotationen kan ALDRIG sönder loggningen):
      Nivå 1: os.replace() — atomic och tillåter att dest redan finns
      Nivå 2: Källan låst → shutil.copyfile() till dest + truncate(0) av
              källan PÅ PLATS (delad läsning räcker — ingen rename krävs)
      Nivå 3: Allt misslyckas → rate-limiterad varning (max 1/timme) +
              fortsätt skriva i befintlig fil — loggen lever vidare

    Extra härdning:
      * Backup-städning (os.remove på gamla .log.N) skyddas i wrapper —
        ett låst backup-fil får ALDRIG krascha emit
      * rolloverAt avanzas alltid vid fel (annars retry-spam per emit)
      * Varningen går via logging med reentrant-skydd + sys.__stderr__
    """

    _WARN_INTERVAL_SEC: float = 3600.0  # max 1 rotations-varning per timme

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # -inf: FÖRSTA varningen ska alltid passera. (0.0 + monotonic() < 1h
        # på nystartad maskin/container hade blockerat den i en timme!)
        self._rollover_warned_at: float = float("-inf")
        self._in_rollover_warning: bool = False
        self._rotate_failed_reason: Optional[str] = None

    # ------------------------------------------------------------- rotate --
    def rotate(self, source: str, dest: str) -> None:
        """Nivå 1 + 2 — överskuggar stdlib:s os.rename."""
        self._rotate_failed_reason = None
        err1: Optional[BaseException] = None
        err2: Optional[BaseException] = None

        # --- Nivå 1: atomic replace (fungerar även om dest finns) ---------
        try:
            if os.path.exists(source):
                os.replace(source, dest)
            return
        except OSError as e:
            err1 = e

        # --- Nivå 2: källan låst → kopiera + trunkera på plats ------------
        try:
            if os.path.exists(source):
                shutil.copyfile(source, dest)
                with open(source, "r+b") as f:
                    f.truncate(0)
            return
        except OSError as e:
            err2 = e

        # --- Nivå 3: ge upp MJUKT — loggen fortsätter i befintlig fil ------
        self._rotate_failed_reason = (
            f"nivå1={_describe_logger_exception(err1) if err1 else 'ok'}; "
            f"nivå2={_describe_logger_exception(err2) if err2 else 'ok'}"
        )

    # --------------------------------------------------------- doRollover --
    def doRollover(self) -> None:
        """Stdlib-rollover med hårt skal — kraschar ALDRIG emit-pipelinen."""
        try:
            super().doRollover()
        except OSError as e:
            # T.ex. backup-städning (os.remove på låst gammal .log.N).
            # Avanza rolloverAt så vi inte retry-spammar vid varje emit.
            self.rolloverAt = self.computeRollover(time.time())
            self._warn_rollover(
                f"rotation misslyckades (backup-städning?): "
                f"{_describe_logger_exception(e)} — loggen fortsätter"
            )
            return
        if self._rotate_failed_reason:
            self._warn_rollover(
                f"loggfil låst av annan process — fortsätter i befintlig "
                f"fil ({self._rotate_failed_reason})"
            )

    # ----------------------------------------------------------- varning ---
    def _warn_rollover(self, message: str) -> None:
        """Rate-limiterad varning (max 1/timme) — reentrant-säker."""
        now = time.monotonic()
        if now - self._rollover_warned_at < self._WARN_INTERVAL_SEC:
            return
        self._rollover_warned_at = now
        if self._in_rollover_warning:
            return
        self._in_rollover_warning = True
        try:
            logging.getLogger("LoggerSetup").warning(
                f"{LOG_PREFIX} {message}"
            )
        except Exception:
            pass
        finally:
            self._in_rollover_warning = False
        # Spegla till RIKTIGA stderr (sys.__stderr__ — aldrig redirectad)
        try:
            sys.__stderr__.write(f"[LOG] {LOG_PREFIX} {message}\n")
            sys.__stderr__.flush()
        except Exception:
            pass


# ===========================================================================
# SETUP: Allt-i-ett
# ===========================================================================

def setup_full_logging(
    data_dir: Optional[Path] = None,
    debug: bool = True,
    capture_stdout: bool = True,
    capture_exceptions: bool = True,
    capture_threads: bool = True,
) -> Path:
    """
    Komplett loggnings-setup.

    NY v6.4.1 v7: EN log-fil istället för 3 separata.
      Rickard 2026-09-22: "all loggning i en fil, ej 3 separata, ska logga precis allt".

    Skriver allt (DEBUG+) till:
      - data/todo_app.log  (EN fil, allt, daily-rotating)
      - stderr/console     (om tillgängligt)

    Args:
        data_dir: Var data/ ska ligga. None = ./data/
        debug: Om True, sätt root till DEBUG
        capture_stdout: Om True, omdirigera print() till logg
        capture_exceptions: Om True, installera global exception hook
        capture_threads: Om True, installera thread exception hook (Py 3.8+)

    Returns:
        Path till data-katalogen (där todo_app.log finns)
    """
    # 1. Skapa data-katalog (INTE data/logs/)
    data_dir = data_dir or DEFAULT_DATA_DIR
    data_dir.mkdir(parents=True, exist_ok=True)

    # 2. Rensa gamla handlers (för att undvika dubbletter vid reinit)
    root = logging.getLogger()
    for handler in root.handlers[:]:
        try:
            handler.close()
        except Exception:
            pass
        root.removeHandler(handler)

    # 3. Sätt log-nivå (DEBUG = allt)
    level = logging.DEBUG if debug else logging.INFO
    root.setLevel(level)

    # 4. Skapa formatters
    detailed_fmt = DetailedFormatter(STANDARD_FORMAT, STANDARD_DATEFMT)
    simple_fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
        STANDARD_DATEFMT,
    )

    # 5. === ENDAST EN LOG-FIL: data/todo_app.log ===
    # NY v6.4.1 v7: Rickard vill ha EN fil med allt
    global _ACTIVE_LOG_PATH
    log_path = data_dir / SINGLE_LOG_NAME
    _ACTIVE_LOG_PATH = log_path
    # NY v7-fix13 (Etapp 9): WinSafeTimedRotatingFileHandler — WinError 32-
    # säker rotation (Rickards krasch 2026-09-25: todo_app.log låst av annan
    # process vid midnight-rollover). delay=True öppnar filen först vid
    # första logg-raden (kortare låstid vid start, tacklar också tomma filer).
    file_handler = WinSafeTimedRotatingFileHandler(
        log_path,
        when="midnight",
        interval=1,
        backupCount=7,  # Behåll 7 dagars historik
        encoding="utf-8",
        delay=True,
    )
    file_handler.setLevel(logging.DEBUG)  # Fånga ALLT
    file_handler.setFormatter(detailed_fmt)
    file_handler.suffix = "%Y%m%d"
    root.addHandler(file_handler)

    # 8. === STDOUT/STDERR → fil (om aktiverat) ===
    if capture_stdout:
        # Specifik logger för print()-output
        stdout_logger = logging.getLogger("stdout")
        stdout_logger.setLevel(logging.INFO)
        stdout_logger.propagate = True  # Sänd till root också
        stdout_redirect = StreamToLogger(stdout_logger, level=logging.INFO)
        stdout_redirect.install()
        # Spara referens för ev. senare restore
        root._stdout_redirect = stdout_redirect  # type: ignore[attr-defined]

    # 9. === EXCEPTION HOOKS (om aktiverat) ===
    if capture_exceptions:
        sys.excepthook = exception_hook
    if capture_threads:
        # Bara Python 3.8+
        if hasattr(threading, "excepthook"):
            threading.excepthook = thread_excepthook

    # 10.5. NY v6.4: Qt event-fångst (om Qt finns)
    if _QT_AVAILABLE:
        try:
            from PySide6.QtCore import QObject, QEvent
            from PySide6.QtWidgets import QApplication, QWidget

            class QtEventLogger(QObject):
                """Fångar ALLA Qt-events och loggar dem."""

                def eventFilter(self, obj, event):
                    try:
                        # Logga bara viktiga events
                        event_type = event.type()
                        if event_type == QEvent.Type.Show:
                            logger.trace(f"[QT-EVENT] Show: {obj.__class__.__name__}")
                        elif event_type == QEvent.Type.Hide:
                            logger.trace(f"[QT-EVENT] Hide: {obj.__class__.__name__}")
                        elif event_type == QEvent.Type.MouseButtonPress:
                            logger.trace(
                                f"[QT-EVENT] MousePress: {obj.__class__.__name__} "
                                f"@ ({event.x()}, {event.y()})"
                            )
                        elif event_type == QEvent.Type.KeyPress:
                            logger.trace(
                                f"[QT-EVENT] KeyPress: {obj.__class__.__name__} "
                                f"key={event.key()}"
                            )
                        elif event_type == QEvent.Type.Resize:
                            logger.trace(
                                f"[QT-EVENT] Resize: {obj.__class__.__name__} "
                                f"{event.size().width()}x{event.size().height()}"
                            )
                        elif event_type == QEvent.Type.Move:
                            logger.trace(
                                f"[QT-EVENT] Move: {obj.__class__.__name__} "
                                f"@ ({event.x()}, {event.y()})"
                            )
                        elif event_type == QEvent.Type.WindowStateChange:
                            logger.trace(
                                f"[QT-EVENT] WindowState: {obj.__class__.__name__} "
                                f"new={event.type()}"
                            )
                    except Exception:
                        pass
                    return False  # Låt eventet fortsätta

            # Installera event-filter på QApplication
            _qt_logger = QtEventLogger()
            _qt_logger_app = QApplication.instance()
            if _qt_logger_app is not None:
                _qt_logger_app.installEventFilter(_qt_logger)
                logger.debug("[LOG] Qt event-filter installerat")
        except ImportError:
            # FIX v7-fix19: 'logger' fanns inte i denna scope (latent bugg —
            # träffades bara när PySide6-importen misslyckas, t.ex. trasiga
            # systembibliotek) → NameError dödade hela setup_full_logging!
            log.debug("[LOG] Qt event-filter: PySide6 saknas")
        except Exception as e:
            logger.debug(f"[LOG] Qt event-filter misslyckades: {e}")

    # 10. === MUTE noisy libs (om ej debug) ===
    if not debug:
        logging.getLogger("PySide6").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("asyncio").setLevel(logging.WARNING)
    else:
        # I debug-läge: sätt Qt till INFO (inte DEBUG, för mycket brus)
        logging.getLogger("PySide6").setLevel(logging.INFO)

    # 11. Logga start-info
    log = logging.getLogger("LoggerSetup")
    log.info("=" * 70)
    log.info(f"{LOG_PREFIX} Full logging aktiverat (debug={debug})")
    log.info(f"{LOG_PREFIX} Data dir: {data_dir}")
    log.info(f"{LOG_PREFIX} Log-fil: {log_path}")
    log.info(f"{LOG_PREFIX} Python: {sys.version.split()[0]}")
    try:
        log.info(f"{LOG_PREFIX} Platform: {sys.platform}")
        log.info(f"{LOG_PREFIX} Hostname: {socket.gethostname()}")
        log.info(f"{LOG_PREFIX} Process: {os.getpid()}")
        log.info(f"{LOG_PREFIX} Working dir: {os.getcwd()}")
        log.info(f"{LOG_PREFIX} Script: {__file__}")
    except Exception as _info_err:
        log.debug(f"{LOG_PREFIX} kunde inte logga all start-info: {_info_err}")
    log.info(f"{LOG_PREFIX} capture_stdout: {capture_stdout}")
    log.info(f"{LOG_PREFIX} capture_exceptions: {capture_exceptions}")
    log.info(f"{LOG_PREFIX} capture_threads: {capture_threads}")
    log.info(f"{LOG_PREFIX} Qt event-filter: True")
    log.info("=" * 70)
    log.info(
        f"{LOG_PREFIX} LoggerSetup komplett — skriver till: {log_path}"
    )
    return data_dir

def quick_setup(debug: bool = True) -> Path:
    """Snabb setup med defaults."""
    return setup_full_logging(
        data_dir=Path(__file__).resolve().parent / "data",
        debug=debug,
        capture_stdout=True,
        capture_exceptions=True,
        capture_threads=True,
    )


# ===========================================================================
# DIAGNOSTIK-HJÄLPARE (NY v6.4.1)
# ===========================================================================

def _resolve_log_file(logs_dir: Optional[Path] = None) -> Optional[Path]:
    """
    NY v6.4.1 v7: Hitta den ENDa logg-filen (data/todo_app.log).

    Sökrordning:
      1. Explicit logs_dir (fil eller katalog med todo_app.log)
      2. _ACTIVE_LOG_PATH (satt av setup_full_logging)
      3. ./data/todo_app.log (app-rot, där main.pyw skriver)
      4. DEFAULT_DATA_DIR/todo_app.log (core/data — legacy)
    """
    if logs_dir is not None:
        if logs_dir.is_file():
            return logs_dir
        cand = logs_dir / SINGLE_LOG_NAME
        if cand.is_file():
            return cand
        # logs_dir = data/logs (legacy) → sök i föräldern
        cand = logs_dir.parent / SINGLE_LOG_NAME
        if cand.is_file():
            return cand
    if _ACTIVE_LOG_PATH is not None and _ACTIVE_LOG_PATH.is_file():
        return _ACTIVE_LOG_PATH
    # App-rot/data (main.pyw: SCRIPT_DIR/"data") — logger_setup ligger i core/
    app_root_data = Path(__file__).resolve().parent.parent / "data" / SINGLE_LOG_NAME
    if app_root_data.is_file():
        return app_root_data
    legacy = DEFAULT_DATA_DIR / SINGLE_LOG_NAME
    if legacy.is_file():
        return legacy
    # Returnera tänkt standard-sökväg (även om filen saknas ännu)
    return app_root_data if _ACTIVE_LOG_PATH is None else _ACTIVE_LOG_PATH


def get_recent_logs(
    logs_dir: Optional[Path] = None,
    n: int = 100,
    level_filter: Optional[str] = None,
) -> List[str]:
    """
    NY v6.4.1: Hämta senaste N log-raderna från ENA logg-filen (todo_app.log).

    Args:
        logs_dir: Data-dir eller logg-fil. None = aktiv todo_app.log
        n: Antal rader att hämta (default 100)
        level_filter: Filtrera på nivå (t.ex. "ERROR", "WARNING"), None = alla

    Returns:
        Lista av log-rader (senaste först)
    """
    latest = _resolve_log_file(logs_dir)
    if latest is None or not latest.is_file():
        return []
    try:
        with open(latest, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception:
        return []
    # Filtrera på level om angivet
    if level_filter:
        level_filter_upper = level_filter.upper()
        lines = [
            line for line in lines
            if f"| {level_filter_upper:<8s} |" in line
        ]
    # Senaste N
    return lines[-n:][::-1]


def search_logs(
    query: str,
    logs_dir: Optional[Path] = None,
    *,
    case_sensitive: bool = False,
    max_results: int = 50,
) -> List[Dict[str, Any]]:
    """
    NY v6.4.1: Sök i alla log-filer efter fritext.

    Args:
        query: Sök-sträng (ord eller fras)
        logs_dir: Var data/logs/ ligger. None = ./data/logs/
        case_sensitive: Case-sensitive sökning (default False)
        max_results: Max antal resultat (default 50)

    Returns:
        Lista av dict med:
          - file: filnamn
          - line_number: rad-nummer
          - line: hela raden

    Exempel:
        >>> results = search_logs("widget_fönster")
        >>> print(f"Hittade {len(results)} träffar")
    """
    if not query:
        return []
    # EN fil (v6.4.1 v7): sök i todo_app.log + roterade backups
    single = _resolve_log_file(logs_dir)
    log_files: List[Path] = []
    if single is not None:
        search_dir = single.parent
        log_files = sorted(search_dir.glob(f"{SINGLE_LOG_NAME}*"), reverse=True)
    if not log_files:
        return []
    results: List[Dict[str, Any]] = []
    for log_file in log_files:
        if len(results) >= max_results:
            break
        try:
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                for line_num, line in enumerate(f, start=1):
                    if case_sensitive:
                        match = query in line
                    else:
                        match = query.lower() in line.lower()
                    if match:
                        results.append({
                            "file": log_file.name,
                            "line_number": line_num,
                            "line": line.rstrip(),
                        })
                        if len(results) >= max_results:
                            break
        except Exception:
            continue
    return results


def get_log_stats(logs_dir: Optional[Path] = None) -> Dict[str, Any]:
    """
    NY v6.4.1: Statistik över log-filer (antal rader, errors, warnings).

    Args:
        logs_dir: Var data/logs/ ligger. None = ./data/logs/

    Returns:
        Dict med:
          - total_files: int
          - total_size_bytes: int
          - total_lines: int
          - by_level: Dict[str, int] (DEBUG, INFO, WARNING, ERROR, CRITICAL)
          - by_date: Dict[str, int] (YYYY-MM-DD → antal rader)
          - recent_files: List[str] (senaste 5 filnamn)

    Exempel:
        >>> stats = get_log_stats()
        >>> print(f"Errors: {stats['by_level'].get('ERROR', 0)}")
    """
    # EN fil (v6.4.1 v7): data/todo_app.log (+ roterade backups)
    single = _resolve_log_file(logs_dir)
    files: List[Path] = []
    if single is not None:
        files = list(single.parent.glob(f"{SINGLE_LOG_NAME}*"))
    if not files:
        return {
            "total_files": 0,
            "total_size_bytes": 0,
            "total_lines": 0,
            "by_level": {},
            "by_date": {},
            "recent_files": [],
        }
    total_files = 0
    total_size = 0
    total_lines = 0
    by_level: Dict[str, int] = {}
    by_date: Dict[str, int] = {}
    for log_file in files:
        total_files += 1
        try:
            stat = log_file.stat()
            total_size += stat.st_size
            # Räkna rader + level
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    total_lines += 1
                    # Level: "| ERROR    |" (8-char padded)
                    parts = line.split("|")
                    if len(parts) >= 2:
                        level = parts[1].strip()
                        if level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
                            by_level[level] = by_level.get(level, 0) + 1
                    # Date: första delen "YYYY-MM-DD HH:MM:SS"
                    if line and line[0:4].isdigit():
                        date = line[0:10]
                        by_date[date] = by_date.get(date, 0) + 1
        except Exception:
            continue
    recent_files = sorted(
        [f.name for f in files],
        reverse=True,
    )[:5]
    return {
        "total_files": total_files,
        "total_size_bytes": total_size,
        "total_lines": total_lines,
        "by_level": by_level,
        "by_date": dict(sorted(by_date.items(), reverse=True)[:7]),
        "recent_files": recent_files,
    }


def create_log_snapshot(logs_dir: Optional[Path] = None) -> Dict[str, Any]:
    """
    NY v6.4.1: Komplett log-snapshot för support / Doctor-knappen.

    Args:
        logs_dir: Var data/logs/ ligger. None = ./data/logs/

    Returns:
        Dict med all log-info (för diagnostik):
          - stats: från get_log_stats()
          - recent_errors: List[str] (senaste 50 ERROR-rader)
          - recent_warnings: List[str] (senaste 50 WARNING-rader)
          - session_count: int
          - timestamp: float
    """
    stats = get_log_stats(logs_dir)
    recent_errors = get_recent_logs(logs_dir, n=50, level_filter="ERROR")
    recent_warnings = get_recent_logs(logs_dir, n=50, level_filter="WARNING")
    single = _resolve_log_file(logs_dir)
    # "session_count" = antal roterade backup-filer (todo_app.log.*)
    backups = (
        list(single.parent.glob(f"{SINGLE_LOG_NAME}.*"))
        if single is not None
        else []
    )
    return {
        "stats": stats,
        "recent_errors": recent_errors,
        "recent_warnings": recent_warnings,
        "session_count": len(backups),
        "timestamp": time.time(),
    }


def get_logs_dir() -> Path:
    """NY v6.4.1: Hämta data-dir för ENA logg-filen (todo_app.log)."""
    single = _resolve_log_file(None)
    logs_dir = single.parent if single is not None else DEFAULT_DATA_DIR
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


# ===========================================================================
# SELF-TEST
# ===========================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("logger_setup.py — Self-Test")
    print("=" * 70)

    # Sätt upp loggning
    logs_dir = quick_setup(debug=True)
    print(f"\nData dir: {logs_dir}")
    log_file = _resolve_log_file(logs_dir)
    print(f"Log-fil: {log_file}")
    if log_file is not None and log_file.is_file():
        print(f"  - {log_file.name} ({log_file.stat().st_size} bytes)")

    # Test alla logg-nivåer
    log = logging.getLogger("SelfTest")
    log.debug("DEBUG-meddelande (test)")
    log.info("INFO-meddelande (test)")
    log.warning("WARNING-meddelande (test)")
    log.error("ERROR-meddelande (test)")
    log.critical("CRITICAL-meddelande (test)")

    # Test med extra-context
    log.info(
        "Test med extra-context",
        extra={"task_id": "abc123", "duration_ms": 42.5, "operation": "test_op"},
    )

    # Test print() (ska fångas av StreamToLogger)
    print("Detta är en print() som ska fångas av stdout-redirect")
    print("Rad 2 från print()")

    # Test unhandled exception (via thread)
    def failing_thread():
        raise ValueError("Test-fel i tråd")
    t = threading.Thread(target=failing_thread, daemon=True, name="TestThread")
    t.start()
    t.join(timeout=1.0)

    # Test Qt events (mock)
    qt_log = logging.getLogger("PySide6.QtCore")
    qt_log.info("Mockad Qt-event (test)")

    # Test Win32 calls
    win32_log = logging.getLogger("Win32")
    win32_log.info("Mockad Win32-anrop (test)")

    # Visa resultat
    print("\n" + "=" * 70)
    print("Efter test — logg-fil (EN fil):")
    for f in sorted(logs_dir.glob("todo_app.log*")):
        size = f.stat().st_size
        print(f"  - {f.name} ({size} bytes)")

    print()
    print("Log-fil innehåll (sista 20 raderna):")
    single_log = _resolve_log_file(logs_dir)
    if single_log is not None and single_log.is_file():
        print(f"  → {single_log.name}")
        with open(single_log, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines[-20:]:
            print(f"  {line.rstrip()}")

    print()
    print("=" * 70)

    # === NY v6.4.1: Diagnostik-hjälpare ===
    print("\n[Test 6] get_recent_logs (NY v6.4.1)...")
    recent = get_recent_logs(logs_dir, n=5)
    print(f"  ✓ get_recent_logs: {len(recent)} rader")
    assert len(recent) > 0

    print("\n[Test 7] get_recent_logs(level_filter=ERROR)...")
    recent_errors = get_recent_logs(logs_dir, n=10, level_filter="ERROR")
    print(f"  ✓ Errors: {len(recent_errors)} rader")

    print("\n[Test 8] search_logs (NY v6.4.1)...")
    results = search_logs("SelfTest", logs_dir)
    print(f"  ✓ search_logs('SelfTest'): {len(results)} träffar")

    print("\n[Test 9] get_log_stats (NY v6.4.1)...")
    stats = get_log_stats(logs_dir)
    print(f"  ✓ stats: total_files={stats['total_files']}")
    print(f"    total_lines={stats['total_lines']}")
    print(f"    by_level={stats['by_level']}")

    print("\n[Test 10] create_log_snapshot (NY v6.4.1)...")
    snap = create_log_snapshot(logs_dir)
    print(f"  ✓ snapshot keys: {list(snap.keys())}")
    print(f"    backup_count={snap['session_count']}")

    # Test 11: NY v6.4.1 v7 — AI-felsökning
    print("\n[Test 11] AI-felsökning (NY v6.4.1 v7)...")
    desc1 = _describe_logger_exception(FileNotFoundError("app.log"))
    print(f"  ✓ _describe_logger_exception: {desc1!r}")
    assert "hittades inte" in desc1
    cat1 = _categorize_logger_exception(ValueError("x"))
    cat2 = _categorize_logger_exception(PermissionError("x"))
    print(f"  ✓ _categorize_logger_exception: ValueError→{cat1}, PermissionError→{cat2}")
    assert cat1 == "user_input"
    assert cat2 == "permission"
    with safe_run("test-op-log") as ctx_ok:
        pass
    with safe_run("test-op-log-fail") as ctx_fail:
        raise RuntimeError("log-test-fel")
    print(f"  ✓ safe_run fel-blocket: errors={len(ctx_fail['errors'])}")
    assert len(ctx_fail["errors"]) == 1

    # Test 12: NY v6.4.1 v7 — Svenska formatters + diagnostics
    print("\n[Test 12] Svenska formatters + diagnostics (NY v6.4.1 v7)...")
    summ = summarize_logging_health()
    print(f"  ✓ summarize_logging_health: {summ!r}")
    assert LOGGER_SETUP_VERSION in summ
    diag = get_logger_diagnostics()
    print(f"  ✓ get_logger_diagnostics: version={diag['logger_version']}, "
          f"problems={diag['problem_count']}")
    assert diag["module"] == "logger_setup"
    assert diag["logger_version"] == LOGGER_SETUP_VERSION

    # Test 13: NY v6.4.1 v7 — _validate_logger_state
    print("\n[Test 13] _validate_logger_state (NY v6.4.1 v7)...")
    problems = _validate_logger_state()
    print(f"  ✓ _validate_logger_state: {len(problems)} problem")
    for p in problems:
        print(f"    - {p}")

    print()
    print("=" * 70)
    print(f"✓ logger_setup.py — 13 TESTER KLARA ({LOGGER_SETUP_VERSION})!")
    print("=" * 70)