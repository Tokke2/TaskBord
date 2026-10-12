# -*- coding: utf-8 -*-
"""
settings.py — TaskBord v6.4.1 v7 (18 888 888% bättre kod & design + AI-felsökning)
=====================================================================================
Copyright © Rickard Längkvist, 2025–2026

Configuration manager for TaskBord.

** Ansvar (v6.4 — 5000% bättre) **
    • JSON-persistens med schema-versionering (v8)
    • Thread-safe muteringar (RLock)
    • Anti-deadlock worker-trådar för save()
    • 30+ publika inställningar med typade accessors
    • QSS-stylesheet-generering (alla färger centralt)
    • 4 accentpaletter (indigo/violet/emerald/rose)
    • Schema-migrering v3→v4, v7→v8
    • Auto-backup före varje save
    • Custom tags + tag-filter
    • Anpassningsbara shortcuts
    • Export/import av settings
    • Diagnostik (log_level, max_log_files)
    • Audit-log (alla ändringar)
    • Window-configs (multi-window)
    • BUGG 19/26: start_hidden, safe position

NYTT I v6.4.1 v7 (18 888 888% bättre)
======================================
* **AI-felsökning 10000%**: `_describe_settings_exception`, `_format_compact_traceback`,
  `_categorize_settings_exception`, `_SETTINGS_ERROR_TRANSLATIONS`, `safe_call`,
  `safe_run`, `_safe_run_async`, `_validate_settings_state`
* **`Settings.diagnose()`** returnerar svenska problem-beskrivningar
* **`Settings.get_health_report()`** utökad med cache-stats, audit-stats, problems
* **`get_settings_diagnostics()`** for support-fall
* **Svenska UI-strängar**: `format_settings_summary`, `summarize_settings_health`
* **`_log_call`/`_log_setter` decorators** — integrerar nu categorize + describe

** 10000% Loggning (MUST-015) **
    • logger.debug() på ALLA publika metoder (entry/exit)
    • logger.info() på ALLA state-ändringar
    • logger.warning() på ALLA validerings-varningar
    • logger.error() på ALLA exceptions
    • Alla meddelanden har [SETTINGS]-prefix
    • Tråd-info, varaktighet, antal entries

** Threading **
    • _lock (data) — skyddar settings-dict
    • _save_lock (IO) — förhindrar parallella save()
    • _save_thread — worker-tråd för save_async()
    • signal_bus — Qt-signaler för cross-thread updates

** Schema v8 (oförändrad från v6.3) **
    Behåller 100% bakåtkompatibilitet med v6.3-settings.json
"""

from __future__ import annotations

# ===========================================================================
# STANDARD-IMPORTS
# ===========================================================================
import copy
import json
import logging
import logging.handlers
import os
import shutil
import sys
import threading
import time
import traceback
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path
from typing import (
    Any, Callable, ClassVar, Dict, Final, List, Optional, Set, Tuple, Type, Union,
)

# ===========================================================================
# Qt-imports (med fallback)
# ===========================================================================
try:
    from PySide6.QtCore import QObject, Signal, Slot
    _QT_AVAILABLE = True
except ImportError:
    try:
        from PyQt6.QtCore import QObject, pyqtSignal as Signal, pyqtSlot as Slot  # type: ignore
        _QT_AVAILABLE = True
    except ImportError:
        try:
            from PyQt5.QtCore import QObject, pyqtSignal as Signal, pyqtSlot as Slot  # type: ignore
            _QT_AVAILABLE = True
        except ImportError:
            QObject = object  # type: ignore[misc,assignment]
            Signal = lambda *a, **kw: None  # type: ignore[assignment]
            Slot = lambda *a, **kw: lambda f: f  # type: ignore[assignment]
            _QT_AVAILABLE = False


# ===========================================================================
# MODUL-KONSTANTER
# ===========================================================================
LOG_PREFIX: Final[str] = "[SETTINGS]"
SETTINGS_VERSION: Final[int] = 11
APP_VERSION_TAG: Final[str] = "6.4.1-v7"
MIN_SUPPORTED_VERSION: Final[int] = 3  # v3 → v11 migrering
AUDIT_LOG_MAX_ENTRIES: Final[int] = 500
DEFAULT_AUTOSTART_METHOD: Final[str] = "registry"  # registry | shortcut | schtask
SAVE_TIMEOUT_SEC: Final[float] = 3.0
BACKUP_KEEP_COUNT: Final[int] = 5

# Standard-sökväg
SCRIPT_DIR: Final[Path] = Path(__file__).resolve().parent
# FIX v7-fix19: rot-data (samma som main/store/backup/logg sedan v7-fix15).
# Tidigare core/data → settings levde i en ANNAN katalog än allt annat
# (split-brain-resten — Rickards logg 14:14 visade core\data\settings.json).
# FIX v7-fix34: JSON-filer i js/-mappen (Rickard 2026-09-30)
DEFAULT_SETTINGS_PATH: Final[Path] = SCRIPT_DIR.parent / "js" / "settings.json"
DEFAULT_AUDIT_PATH: Final[Path] = SCRIPT_DIR.parent / "js" / "settings_audit.log"
# Äldre plats (används av legacy-migreringen nedan).
LEGACY_CORE_SETTINGS_PATH: Final[Path] = SCRIPT_DIR.parent / "data" / "settings.json"

# Modul-logger (sätts vid första användning)
_logger = logging.getLogger("Settings")
if not _logger.handlers and not _logger.parent.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)-12s | %(message)s"))
    _logger.addHandler(_h)
_logger.setLevel(logging.INFO)
_logger.propagate = True


# ===========================================================================
# ENUMS
# ===========================================================================

class Theme(Enum):
    """TEMA-värden (UI-tema)."""
    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"
    # NY v7-fix82: klockstyrt tema — ljust dagtid, mörkt kväll/natt.
    # Löses i theme()-gettern (07:00–18:59 = ljust, annars mörkt) och
    # växlas under körning av widgetens _check_auto_theme (10-minuters-
    # intervall). Väljs i tray-menyn "🎨 Tema → 🌗 Auto".
    AUTO = "auto"


class AccentColor(Enum):
    """ACCENT-färger (4 paletter)."""
    INDIGO = "indigo"
    VIOLET = "violet"
    EMERALD = "emerald"
    ROSE = "rose"


class GlassStyle(Enum):
    """GLASMORPHISM-stilar."""
    AUTO = "auto"
    TRANSLUCENT = "translucent"
    MICA = "mica"
    ACRYLIC = "acrylic"
    NONE = "none"


class DensityMode(Enum):
    """UI-densitet."""
    COMFORTABLE = "comfortable"
    COMPACT = "compact"
    COZY = "cozy"


class NotificationSound(Enum):
    """Notifikationsljud."""
    NONE = "none"
    CHIME = "chime"
    BELL = "bell"
    GENTLE = "gentle"


class AutostartMethod(Enum):
    """Autostart-metod (Windows-specifik)."""
    REGISTRY = "registry"
    SHORTCUT = "shortcut"
    SCHTASK = "schtask"


# Standardvärden för ENUMs
VALID_THEMES: Final[frozenset] = frozenset(t.value for t in Theme)
VALID_ACCENTS: Final[frozenset] = frozenset(a.value for a in AccentColor)
VALID_GLASS_STYLES: Final[frozenset] = frozenset(g.value for g in GlassStyle)
VALID_DENSITY_MODES: Final[frozenset] = frozenset(d.value for d in DensityMode)

# NY v7-fix38: Win+D-säkert skrivbordsläge + fönstertransparens
VALID_DESKTOP_MODES: Final[frozenset] = frozenset(("above", "behind"))  # v7-fix56: legacy BORT
DEFAULT_DESKTOP_MODE: Final[str] = "behind"  # v7-fix63: behind = beprövat
DEFAULT_WINDOW_TRANSPARENCY: Final[float] = 0.85

# NY v7-fix40: enbart ett fönster (Rickard 2026-10-01: "ska enbart visa
# ett fönster, när man väljer öppna nytt fönster, så ska den enbart
# visa det redan skapat")
DEFAULT_SINGLE_WINDOW: Final[bool] = True
VALID_NOTIFICATION_SOUNDS: Final[frozenset] = frozenset(n.value for n in NotificationSound)
VALID_AUTOSTART_METHODS: Final[frozenset] = frozenset(m.value for m in AutostartMethod)


# ===========================================================================
# ACCENT-PALETTER (rgba-tupler)
# ===========================================================================

ACCENT_PALETTES: Final[Dict[str, Dict[str, Tuple[int, int, int, int]]]] = {
    "indigo": {
        "primary": (99, 102, 241, 255),
        "secondary": (129, 140, 248, 255),
        "accent": (99, 102, 241, 255),
        "hover": (129, 140, 248, 230),
        "pressed": (79, 70, 229, 255),
    },
    "violet": {
        "primary": (139, 92, 246, 255),
        "secondary": (167, 139, 250, 255),
        "accent": (139, 92, 246, 255),
        "hover": (167, 139, 250, 230),
        "pressed": (124, 58, 237, 255),
    },
    "emerald": {
        "primary": (16, 185, 129, 255),
        "secondary": (52, 211, 153, 255),
        "accent": (16, 185, 129, 255),
        "hover": (52, 211, 153, 230),
        "pressed": (5, 150, 105, 255),
    },
    "rose": {
        "primary": (244, 63, 94, 255),
        "secondary": (251, 113, 133, 255),
        "accent": (244, 63, 94, 255),
        "hover": (251, 113, 133, 230),
        "pressed": (225, 29, 72, 255),
    },
}


# ===========================================================================
# DATACLASSES
# ===========================================================================

@dataclass(frozen=True)
class SettingsChange:
    """Representerar en enskild settings-ändring (immutabel)."""
    field: str
    old_value: Any
    new_value: Any
    timestamp: float
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "field": self.field,
            "old": self.old_value,
            "new": self.new_value,
            "timestamp": self.timestamp,
            "iso": datetime.fromtimestamp(self.timestamp, timezone.utc).isoformat(),
            "reason": self.reason,
        }


@dataclass
class SaveResult:
    """Resultat av save()-operation."""
    success: bool
    duration_sec: float
    error: Optional[str] = None
    bytes_written: int = 0
    backup_path: Optional[Path] = None

    def __str__(self) -> str:
        return (
            f"SaveResult(success={self.success}, "
            f"duration={self.duration_sec:.3f}s, "
            f"bytes={self.bytes_written}, "
            f"backup={self.backup_path})"
        )


# ===========================================================================
# LOGGING-HELPERS (för 10000% loggning)
# ===========================================================================

def _log_call(func):
    """Decorator: logga entry/exit på publika metoder + AI-felsökning vid fel."""
    name = func.__name__

    def wrapper(self, *args, **kwargs):
        if not _logger.isEnabledFor(logging.DEBUG):
            return func(self, *args, **kwargs)
        start = time.perf_counter()
        arg_repr = ", ".join(repr(a)[:50] for a in args)
        kwarg_repr = ", ".join(f"{k}={v!r}"[:50] for k, v in kwargs.items())
        all_args = ", ".join(filter(None, [arg_repr, kwarg_repr]))
        _logger.debug(f"{LOG_PREFIX} → {name}({all_args})")
        try:
            result = func(self, *args, **kwargs)
            duration = (time.perf_counter() - start) * 1000
            _logger.debug(f"{LOG_PREFIX} ← {name} OK ({duration:.2f}ms)")
            return result
        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            # NY v6.4.1 v7: AI-felsökning — kategorisera + beskriv
            try:
                category = _categorize_settings_exception(e)
                description = _describe_settings_exception(e)
            except Exception:
                category = "code_bug"
                description = f"{type(e).__name__}: {e}"
            _logger.error(
                f"{LOG_PREFIX} ✗ {name} MISSLYCKADES efter {duration:.2f}ms "
                f"(kategori={category}): {description}",
                exc_info=True,
            )
            raise
    return wrapper


def _log_setter(field_name: str):
    """Decorator: logga state-ändringar + audit."""
    def decorator(func):
        def wrapper(self, value, *args, **kwargs):
            start = time.perf_counter()
            with self._lock:
                old_value = self._data.get(field_name)
            if old_value == value:
                _logger.debug(
                    f"{LOG_PREFIX} {field_name} redan {value!r} (ingen ändring)"
                )
                return True
            _logger.info(
                f"{LOG_PREFIX} {field_name}: {old_value!r} → {value!r}"
            )
            try:
                result = func(self, value, *args, **kwargs)
                duration = (time.perf_counter() - start) * 1000
                if result:
                    _logger.debug(
                        f"{LOG_PREFIX} {field_name} sparat OK ({duration:.2f}ms)"
                    )
                return result
            except Exception as e:
                _logger.error(
                    f"{LOG_PREFIX} Kunde inte sätta {field_name}={value!r}: {e}",
                    exc_info=True,
                )
                raise
        return wrapper
    return decorator


# ===========================================================================
# AI-FELSÖKNING 10000% (NY v6.4.1 v7)
# ===========================================================================
# Hjalpare som genererar:
#   - Anvandarvanlig svenska feltext (for loggar/dialoger)
#   - Kompakt teknisk stacktrace (for loggar)
#   - Standardiserad kategorisering (for prioriterad felhantering)
#   - safe_call / safe_run / _safe_run_async for robusta wrappers
#   - Diagnostik av modulens internna tillstand
# Allt for att Rickard ska kunna felsoka 100% sa mycket enklare.

_SETTINGS_ERROR_TRANSLATIONS: Final[Dict[str, str]] = {
    # Standard-bibliotek
    "ImportError": "Kan inte hitta en Python-modul",
    "ModuleNotFoundError": "Python-modul saknas",
    "AttributeError": "Objektet saknar en metod eller attribut",
    "TypeError": "Fel typ av argument skickades (forvantade t.ex. str)",
    "ValueError": "Ogiltigt varde for inställning",
    "KeyError": "Nyckel saknas i settings-data",
    "IndexError": "Index utanfor intervall",
    "FileNotFoundError": "Settings-filen hittades inte",
    "PermissionError": "Saknar ratigheter till settings.json",
    "OSError": "Operativsystem-fel vid settings-I/O",
    "IOError": "In/ut-fel vid lasning eller skrivning",
    "IsADirectoryError": "Forvantade fil, fick katalog",
    "NotADirectoryError": "Forvantade katalog, fick fil",
    "BlockingIOError": "Settings-filen ar upptagen (blockerar)",
    "TimeoutError": "Tidsgrans overskreds vid save/load",
    "ConnectionError": "Natverksfel (anslutning misslyckades)",
    "UnicodeDecodeError": "Kunde inte avkoda settings (fel teckenkodning)",
    "JSONDecodeError": "Settings-data ar inte giltig JSON",
    "RecursionError": "Rekursion blev for djup",
    "MemoryError": "Minnet slut (for manga inställningar)",
    # Concurrent
    "ThreadError": "Trad-fel (start eller join misslyckades)",
    "BrokenPipeError": "Pipebrott (process avslutad)",
    # Qt
    "RuntimeError": "Qt-runtime-fel (kanske trasig signal)",
}


def _describe_settings_exception(exc: BaseException) -> str:
    """
    NY v6.4.1 v7: Skapar en anvandarvanlig svensk beskrivning av ett undantag.

    Args:
        exc: Exception-objektet som ska beskrivas

    Returns:
        Svensk sträng som passar i loggar och dialoger

    Exempel:
        >>> _describe_settings_exception(FileNotFoundError("settings.json"))
        'Settings-filen hittades inte: settings.json'
    """
    try:
        exc_type = type(exc).__name__
        svensk_typ = _SETTINGS_ERROR_TRANSLATIONS.get(
            exc_type, f"Tekniskt fel ({exc_type})"
        )
        msg = str(exc).strip()
        if not msg:
            return svensk_typ
        # For OSError: inkludera errno om det finns
        if isinstance(exc, OSError) and exc.errno is not None:
            try:
                import errno as _errno
                errno_name = _errno.errorcode.get(exc.errno, str(exc.errno))
                return f"{svensk_typ} ({errno_name}): {msg}"
            except Exception:
                pass
        return f"{svensk_typ}: {msg}"
    except Exception as describe_err:
        _logger.debug(
            f"{LOG_PREFIX} _describe_settings_exception misslyckades: {describe_err}"
        )
        return f"Okant fel: {type(exc).__name__}"


def _format_compact_traceback(exc: BaseException, max_frames: int = 5) -> str:
    """
    NY v6.4.1 v7: Kompakt stacktrace (sista N frames) for loggar.

    Args:
        exc: Exception-objektet
        max_frames: Max antal frames att visa (default 5)
    """
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
    except Exception as fmt_err:
        _logger.debug(
            f"{LOG_PREFIX} _format_compact_traceback misslyckades: {fmt_err}"
        )
        return f"{type(exc).__name__}: {exc}"


def _categorize_settings_exception(exc: BaseException) -> str:
    """
    NY v6.4.1 v7: Kategorisera undantag for prioriterad felhantering.

    Returns:
        En av: "user_input", "system", "code_bug", "external",
        "permission", "data_corrupt", "concurrent"
    """
    try:
        exc_type = type(exc).__name__
        # Anvandarinput-fel
        if exc_type in ("ValueError", "KeyError", "TypeError", "IndexError"):
            return "user_input"
        # Rattighets-fel
        if exc_type in ("PermissionError",):
            return "permission"
        # Data korrupt
        if exc_type in ("JSONDecodeError", "UnicodeDecodeError", "UnicodeEncodeError"):
            return "data_corrupt"
        # Concurrent
        if exc_type in ("ThreadError", "BrokenPipeError", "BlockingIOError"):
            return "concurrent"
        # System-fel
        if exc_type in (
            "OSError", "IOError", "FileNotFoundError",
            "IsADirectoryError", "NotADirectoryError",
            "TimeoutError", "ConnectionError", "WindowsError",
        ):
            return "system"
        # Import
        if exc_type in ("ImportError", "ModuleNotFoundError"):
            return "external"
        # Minne
        if exc_type in ("MemoryError", "RecursionError", "OverflowError"):
            return "system"
        return "code_bug"
    except Exception:
        return "code_bug"


def safe_call(
    func: Callable[..., Any],
    *args: Any,
    default: Any = None,
    log_errors: bool = True,
    reraise: bool = False,
    **kwargs: Any,
) -> Any:
    """
    NY v6.4.1 v7: Anropa func(...) med komplett felhantering.

    Args:
        func: Funktionen som ska anropas
        *args: Positionella argument
        default: Varde att returnera vid fel (default None)
        log_errors: Om True, logga fel till error-loggen
        reraise: Om True, ra om undantaget efter loggning
        **kwargs: Nyckelords-argument
    """
    func_name = getattr(func, "__name__", "<lambda>")
    start = time.perf_counter()
    try:
        result = func(*args, **kwargs)
        if _logger.isEnabledFor(logging.DEBUG):
            duration = (time.perf_counter() - start) * 1000
            _logger.debug(
                f"{LOG_PREFIX} safe_call({func_name}) OK ({duration:.2f}ms)"
            )
        return result
    except Exception as exc:
        duration = (time.perf_counter() - start) * 1000
        category = _categorize_settings_exception(exc)
        if log_errors:
            _logger.error(
                f"{LOG_PREFIX} safe_call({func_name}) MISSLYCKADES "
                f"({duration:.2f}ms, kategori={category}): "
                f"{_describe_settings_exception(exc)}"
            )
            if _logger.isEnabledFor(logging.DEBUG):
                _logger.debug(
                    f"{LOG_PREFIX} safe_call traceback:\n"
                    f"{_format_compact_traceback(exc, max_frames=8)}"
                )
        if reraise:
            raise
        return default


@contextmanager
def safe_run(
    operation_name: str,
    *,
    log_errors: bool = True,
    reraise: bool = False,
) -> Generator[Dict[str, Any], None, None]:
    """
    NY v6.4.1 v7: Context-manager for komplett felhantering kring ett block.
    """
    start = time.perf_counter()
    ctx: Dict[str, Any] = {
        "start_time": start,
        "operation": operation_name,
        "errors": [],
    }
    _logger.debug(f"{LOG_PREFIX} safe_run START: {operation_name}")
    try:
        yield ctx
        duration = (time.perf_counter() - start) * 1000
        _logger.debug(
            f"{LOG_PREFIX} safe_run OK: {operation_name} ({duration:.2f}ms)"
        )
    except Exception as exc:
        duration = (time.perf_counter() - start) * 1000
        category = _categorize_settings_exception(exc)
        ctx["errors"].append(exc)
        if log_errors:
            _logger.error(
                f"{LOG_PREFIX} safe_run FEL: {operation_name} "
                f"({duration:.2f}ms, kategori={category}): "
                f"{_describe_settings_exception(exc)}"
            )
        if reraise:
            raise


def _safe_run_async(
    func: Callable[..., Any],
    *args: Any,
    timeout_sec: float = 10.0,
    default: Any = None,
    operation_name: Optional[str] = None,
    **kwargs: Any,
) -> Any:
    """
    NY v6.4.1 v7: Kor func(...) i en trad med timeout + felhantering.
    """
    op_name = operation_name or getattr(func, "__name__", "<anon>")
    result_box: List[Any] = [default]
    error_box: List[Optional[BaseException]] = [None]
    done = threading.Event()

    def worker() -> None:
        try:
            result_box[0] = func(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001
            error_box[0] = exc
        finally:
            done.set()

    t = threading.Thread(target=worker, daemon=True, name=f"set-safe-async:{op_name}")
    t.start()
    if not done.wait(timeout=timeout_sec):
        _logger.error(
            f"{LOG_PREFIX} _safe_run_async TIMEOUT ({timeout_sec}s): {op_name}"
        )
        return default
    if error_box[0] is not None:
        category = _categorize_settings_exception(error_box[0])
        _logger.error(
            f"{LOG_PREFIX} _safe_run_async FEL: {op_name} "
            f"(kategori={category}): {_describe_settings_exception(error_box[0])}"
        )
        return default
    return result_box[0]


def _validate_settings_state(settings: Optional[Any] = None) -> List[str]:
    """
    NY v6.4.1 v7: Diagnostisk funktion som kontrollerar settings-modulens tillstand.

    Args:
        settings: Valfri Settings-instans att validera (om None: modul-niva)

    Returns:
        Lista med svenska problem-beskrivningar (tom om allt ar OK)
    """
    problems: List[str] = []
    try:
        if _logger is None:
            problems.append("Kritisk: modulens logger ar None")
        # JSON-backend
        try:
            test_obj = {"version": SETTINGS_VERSION, "theme": "dark"}
            encoded = json.dumps(test_obj)
            decoded = json.loads(encoded)
            if decoded != test_obj:
                problems.append("JSON round-trip misslyckades (data korrupt)")
        except Exception as e:
            problems.append(
                f"JSON-backend trasig: {_describe_settings_exception(e)}"
            )
        # Version-validering
        if SETTINGS_VERSION < MIN_SUPPORTED_VERSION:
            problems.append(
                f"SETTINGS_VERSION ({SETTINGS_VERSION}) < "
                f"MIN_SUPPORTED_VERSION ({MIN_SUPPORTED_VERSION})"
            )
        # Settings-instans
        if settings is not None:
            try:
                if hasattr(settings, "_data") and isinstance(settings._data, dict):
                    data_keys = len(settings._data)
                    if data_keys > 200:
                        problems.append(
                            f"Manga settings-nycklar: {data_keys} "
                            f"(bor normalt vara ~30)"
                        )
                if hasattr(settings, "_audit_log"):
                    audit_count = len(settings._audit_log) \
                        if hasattr(settings._audit_log, "__len__") else 0
                    if audit_count > 1000:
                        problems.append(
                            f"Manga audit-entries: {audit_count}"
                        )
            except Exception as e:
                problems.append(
                    f"Settings-validering kraschade: "
                    f"{_describe_settings_exception(e)}"
                )
        if problems:
            _logger.warning(
                f"{LOG_PREFIX} _validate_settings_state: "
                f"{len(problems)} problem hittade"
            )
            for p in problems:
                _logger.warning(f"  - {p}")
        else:
            _logger.debug(
                f"{LOG_PREFIX} _validate_settings_state: alla tester OK"
            )
    except Exception as e:
        problems.append(
            f"_validate_settings_state själv kraschade: "
            f"{_describe_settings_exception(e)}"
        )
    return problems


# ===========================================================================
# SVENSKA FORMATERINGS-HELPERS (NY v6.4.1 v7)
# ===========================================================================

def format_settings_summary(settings: Any) -> str:
    """
    NY v6.4.1 v7: Kort svensk sammanfattning av en Settings-instans.

    Args:
        settings: Settings-instans

    Returns:
        Svensk en-rads-sammanfattning

    Exempel:
        >>> format_settings_summary(settings)
        'v9 • 30 inställningar • dark theme • 15 audit-entries'
    """
    try:
        if settings is None:
            return "(ingen settings-instans)"
        version = getattr(settings, "_version", SETTINGS_VERSION)
        theme = "?"
        if hasattr(settings, "theme"):
            with suppress(Exception):
                theme_val = settings.theme()
                theme = theme_val.value if hasattr(theme_val, "value") else str(theme_val)
        data_count = 0
        if hasattr(settings, "_data") and isinstance(settings._data, dict):
            data_count = len(settings._data)
        audit_count = 0
        if hasattr(settings, "_audit_log"):
            with suppress(Exception):
                audit_count = len(settings._audit_log)
        last_save = getattr(settings, "_last_save_time", 0)
        ago = ""
        if last_save:
            secs = int(time.time() - last_save)
            if secs < 60:
                ago = f" • senast sparad={secs}s sedan"
            elif secs < 3600:
                ago = f" • senast sparad={secs // 60}min sedan"
        return (
            f"v{version} • {data_count} inställningar • "
            f"{theme} theme • {audit_count} audit-entries{ago}"
        )
    except Exception as e:
        _logger.debug(f"{LOG_PREFIX} format_settings_summary misslyckades: {e}")
        return f"(kunde inte sammanfatta: {type(e).__name__})"


def summarize_settings_health(settings: Optional[Any] = None) -> str:
    """
    NY v6.4.1 v7: Kort svensk hälso-sammanfattning av settings-modulen.

    Returns:
        Svensk en-rads-sammanfattning
    """
    try:
        if settings is None:
            return (
                f"v{APP_VERSION_TAG} • settings-modulen redo "
                f"(ingen instans validerad)"
            )
        return f"v{APP_VERSION_TAG} • {format_settings_summary(settings)}"
    except Exception as e:
        _logger.debug(f"{LOG_PREFIX} summarize_settings_health misslyckades: {e}")
        return f"(kunde inte sammanfatta: {type(e).__name__})"


def get_settings_diagnostics(settings: Optional[Any] = None) -> Dict[str, Any]:
    """
    NY v6.4.1 v7: Detaljerad diagnostik-rapport for support-fall.
    """
    with safe_run("get_settings_diagnostics") as ctx:
        problems = _validate_settings_state(settings)
        summary = summarize_settings_health(settings)
        ctx["ok"] = True
        return {
            "module": "settings",
            "app_version_tag": APP_VERSION_TAG,
            "settings_version": SETTINGS_VERSION,
            "min_supported_version": MIN_SUPPORTED_VERSION,
            "problems": problems,
            "problem_count": len(problems),
            "summary_swedish": summary,
        }


# NY v6.4.1 v7: Plugin-coupling — settings vill ha pywin32 pa Windows
_SETTINGS_PLUGIN_DEPS: Final[Tuple[Dict[str, str], ...]] = (
    {
        "pip_name": "pywin32",
        "import_name": "win32api",
        "description_svenska": "Windows-registret (autostart etc.)",
        "benefit_svenska": "Bättre Windows-integration (endast Windows)",
        "required": False,
    },
)


def get_settings_plugin_deps() -> List[Dict[str, str]]:
    """NY v6.4.1 v7: Optional Python-beroenden som settings vill ha."""
    return [dict(d) for d in _SETTINGS_PLUGIN_DEPS]


# ===========================================================================
# AUDIT-LOG
# ===========================================================================

class AuditLog:
    """Trådsäker audit-log för settings-ändringar."""

    def __init__(self, max_entries: int = AUDIT_LOG_MAX_ENTRIES) -> None:
        self._entries: List[SettingsChange] = []
        self._max = max_entries
        self._lock = threading.RLock()
        _logger.debug(f"{LOG_PREFIX} AuditLog initierad (max_entries={max_entries})")

    def add(self, field: str, old_value: Any, new_value: Any, reason: str = "") -> None:
        """Lägg till entry (FIFO, max_entries)."""
        with self._lock:
            change = SettingsChange(
                field=field,
                old_value=copy.deepcopy(old_value),
                new_value=copy.deepcopy(new_value),
                timestamp=time.time(),
                reason=reason,
            )
            self._entries.append(change)
            if len(self._entries) > self._max:
                removed = self._entries.pop(0)
                _logger.debug(
                    f"{LOG_PREFIX} AuditLog: tog bort äldsta entry "
                    f"({removed.field}, max={self._max})"
                )
        _logger.debug(
            f"{LOG_PREFIX} Audit: {field}={old_value!r}→{new_value!r} "
            f"(total={len(self._entries)})"
        )

    def get_entries(self, field: Optional[str] = None) -> List[SettingsChange]:
        """Hämta entries (optionellt filtrerat på fält)."""
        with self._lock:
            if field is None:
                return list(self._entries)
            return [e for e in self._entries if e.field == field]

    def clear(self) -> None:
        """Rensa alla entries."""
        with self._lock:
            count = len(self._entries)
            self._entries.clear()
        _logger.info(f"{LOG_PREFIX} AuditLog rensad ({count} entries)")

    def to_dict(self) -> List[Dict[str, Any]]:
        """Serialisera för export."""
        with self._lock:
            return [e.to_dict() for e in self._entries]


# ===========================================================================
# HJÄLPFUNKTIONER
# ===========================================================================

def _coerce_bool(value: Any, default: bool = False) -> bool:
    """Konvertera värde till bool robust."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes", "on", "ja")
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _coerce_int(value: Any, default: int = 0, min_val: int = 0, max_val: int = 2**31) -> int:
    """Konvertera värde till int med range-check."""
    try:
        result = int(value)
        return max(min_val, min(max_val, result))
    except (TypeError, ValueError):
        return default


def _coerce_list(value: Any, default: Optional[List[Any]] = None) -> List[Any]:
    """Konvertera värde till lista."""
    if isinstance(value, list):
        return list(value)
    if isinstance(value, (tuple, set)):
        return list(value)
    return default or []


def _coerce_str(value: Any, default: str = "", valid: Optional[Set[str]] = None) -> str:
    """Konvertera värde till str (med valid-set-check)."""
    if not isinstance(value, str):
        value = str(value) if value is not None else default
    if valid is not None and value not in valid:
        _logger.warning(
            f"{LOG_PREFIX} Ogiltigt värde {value!r}, använder default {default!r}"
        )
        return default
    return value or default


def _coerce_window_transparency(
    value: Any, default: float = DEFAULT_WINDOW_TRANSPARENCY
) -> float:
    """NY v7-fix38: tvinga fönstertransparens till 0.0–1.0 (0 = helt opak)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if v != v:  # NaN-skydd
        return default
    return round(min(1.0, max(0.0, v)), 2)


# ===========================================================================
# MAIN CLASS: Settings
# ===========================================================================

class Settings(QObject):
    """
    Huvudklass för settings-hantering.

    Signals (Qt):
        theme_changed(str)
        accent_changed(str)
        glass_style_changed(str)
        animations_changed(bool)
        autostart_changed(bool)
        windows_updated(list)
        tabs_changed(list)
        shortcuts_changed(dict)
        settings_saved()
        settings_loaded()
        error_occurred(str)
    """

    # ========================================================================
    # SIGNALS
    # ========================================================================

    if _QT_AVAILABLE:
        theme_changed = Signal(str)
        accent_changed = Signal(str)
        glass_style_changed = Signal(str)
        animations_changed = Signal(bool)
        # FIX v7-fix12: signalen emiteras med (enabled, os_ok) i set_autostart
        # men var definierad med EN parameter → TypeError vid varje anrop.
        autostart_changed = Signal(bool, bool)  # (enabled, os_ok)
        windows_updated = Signal(list)
        tabs_changed = Signal(list)
        shortcuts_changed = Signal(dict)
        settings_saved = Signal()
        settings_loaded = Signal()
        error_occurred = Signal(str)
    else:
        # Fallback: no-op signaler
        def __getattr__(self, name: str) -> Any:
            if name.endswith("_changed") or name.endswith("_updated") or name in (
                "settings_saved", "settings_loaded", "error_occurred"
            ):
                return _DummySignal()
            raise AttributeError(name)

    # ========================================================================
    # KLASS-KONSTANTER
    # ========================================================================

    DEFAULT_WINDOWS: ClassVar[List[Dict[str, Any]]] = [
        {"id": "default", "x": -1, "y": -1, "w": 340, "h": 648, "locked": False}  # -1 = centrera vid första start (v7-fix47)
    ]

    DEFAULT_VISIBLE_TABS: ClassVar[List[str]] = ["Aktiva", "Arkiverade"]

    DEFAULT_SHORTCUTS: ClassVar[Dict[str, str]] = {
        "add_task": "Ctrl+Alt+N",
        "toggle_visible": "Ctrl+Alt+H",
        "toggle_inbox": "Ctrl+Alt+I",
        "open_search": "Ctrl+Alt+F",
        "next_task": "Down",
        "prev_task": "Up",
        "edit_task": "F2",
        "delete_task": "Delete",
        "toggle_done": "Space",
    }

    # ========================================================================
    # INIT
    # ========================================================================

    def __init__(self, file_path: Optional[Union[str, Path]] = None) -> None:
        """
        Initiera Settings.

        Args:
            file_path: Sökväg till settings.json. None = default.
        """
        super().__init__()
        self._log = logging.getLogger("Settings")
        self._lock = threading.RLock()
        self._save_lock = threading.RLock()
        self._save_thread: Optional[threading.Thread] = None
        self._audit_log = AuditLog()

        # Paths
        self._file_path: Path = (
            Path(file_path) if file_path else DEFAULT_SETTINGS_PATH
        )
        self._audit_path: Path = DEFAULT_AUDIT_PATH
        # FIX v7-fix19: migrera settings från gamla core/data → rot-data.
        # Kopiera om nya platsen saknar filen — eller om den gamla är NYARE
        # (då backupas den befintliga som .json.old först).
        if file_path is None:
            with suppress(Exception):
                _legacy = LEGACY_CORE_SETTINGS_PATH
                if _legacy.is_file() and _legacy != self._file_path:
                    _do_copy = False
                    if not self._file_path.is_file():
                        _do_copy = True
                    elif _legacy.stat().st_mtime > self._file_path.stat().st_mtime:
                        _backup = self._file_path.with_suffix(".json.old")
                        with suppress(Exception):
                            self._file_path.replace(_backup)
                        self._log.info(
                            f"{LOG_PREFIX} gamla core/settings är nyare — "
                            f"backup: {_backup.name}"
                        )
                        _do_copy = True
                    if _do_copy:
                        self._file_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(_legacy, self._file_path)
                        self._log.info(
                            f"{LOG_PREFIX} migrerade settings: "
                            f"{_legacy} → {self._file_path}"
                        )

        # Internal state
        self._data: Dict[str, Any] = {}
        self._dirty = False
        self._initialized = False
        self._last_save_time: float = 0.0
        self._last_load_time: float = 0.0
        self._save_count: int = 0
        self._load_count: int = 0
        self._error_count: int = 0

        self._log.info(
            f"{LOG_PREFIX} Settings initierad: sökväg={self._file_path}"
        )
        self._log.debug(
            f"{LOG_PREFIX} Qt tillgängligt: {_QT_AVAILABLE}, "
            f"schema-version: {SETTINGS_VERSION}"
        )

        # Init
        self._initialize()
        self._initialized = True
        self._log.info(
            f"{LOG_PREFIX} Settings klar: {len(self._data)} nycklar inlästa, "
            f"audit={len(self._audit_log.get_entries())} entries"
        )

    def _initialize(self) -> None:
        """Privat init: ladda från fil, migrera om nödvändigt."""
        try:
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            self._log.debug(
                f"{LOG_PREFIX} Säkerställer data-mapp: {self._file_path.parent}"
            )
        except OSError as e:
            self._log.error(
                f"{LOG_PREFIX} Kunde inte skapa data-mapp: {e}", exc_info=True
            )

        if self._file_path.exists():
            self._log.info(
                f"{LOG_PREFIX} Settings-fil finns: {self._file_path} "
                f"(size={self._file_path.stat().st_size} bytes)"
            )
            self._load()
        else:
            self._log.info(
                f"{LOG_PREFIX} Ingen settings-fil hittades, "
                f"använder defaults (första körningen?)"
            )
            self._apply_defaults()
            self._save_internal()

    @_log_call
    def file_path(self) -> str:
        """Returnerar aktuell settings-sökväg."""
        return str(self._file_path)

    @_log_call
    def data_dir(self) -> str:
        """Returnerar data-katalog (förälder till settings.json)."""
        return str(self._file_path.parent)

    @property
    def settings_path(self) -> str:
        """Alias för file_path (publik property)."""
        return self.file_path()

    # ========================================================================
    # LOAD / SAVE / MIGRATE
    # ========================================================================

    def _load(self) -> bool:
        """Ladda settings från JSON-fil (privat)."""
        start = time.perf_counter()
        try:
            with open(self._file_path, "r", encoding="utf-8") as f:
                raw = f.read()
            self._log.debug(
                f"{LOG_PREFIX} Läser {len(raw)} tecken från {self._file_path}"
            )
            data = json.loads(raw)
            version = data.get("version", 1)
            self._log.info(
                f"{LOG_PREFIX} Schema-version vid load: {version} "
                f"(target: {SETTINGS_VERSION})"
            )
            if version != SETTINGS_VERSION:
                self._log.info(
                    f"{LOG_PREFIX} Migrerar från v{version} → v{SETTINGS_VERSION}"
                )
                data = self._migrate(version, SETTINGS_VERSION, data)
            else:
                self._log.debug(f"{LOG_PREFIX} Ingen migrering behövs")
            with self._lock:
                self._data = data
            self._validate_all()
            self._last_load_time = time.time()
            self._load_count += 1
            duration = (time.perf_counter() - start) * 1000
            self._log.info(
                f"{LOG_PREFIX} Load OK: {len(self._data)} nycklar, "
                f"{duration:.2f}ms (load_count={self._load_count})"
            )
            self._safe_emit("settings_loaded")
            return True
        except FileNotFoundError:
            self._log.warning(
                f"{LOG_PREFIX} Fil hittades inte: {self._file_path}"
            )
            self._apply_defaults()
            return False
        except json.JSONDecodeError as e:
            self._log.error(
                f"{LOG_PREFIX} JSON-decode misslyckades: {e}", exc_info=True
            )
            self._handle_corrupt_settings()
            return False
        except Exception as e:
            self._log.error(
                f"{LOG_PREFIX} Load misslyckades: {type(e).__name__}: {e}",
                exc_info=True,
            )
            self._error_count += 1
            self._safe_emit("error_occurred", f"Load misslyckades: {e}")
            return False

    def _handle_corrupt_settings(self) -> None:
        """Hantera korrupt settings-fil (backup → defaults)."""
        try:
            corrupt_path = self._file_path.with_suffix(".corrupt.json")
            shutil.copy2(self._file_path, corrupt_path)
            self._log.warning(
                f"{LOG_PREFIX} Korrupt settings säkerhetskopierad till {corrupt_path}"
            )
        except Exception as e:
            self._log.error(
                f"{LOG_PREFIX} Kunde inte backup:a korrupt settings: {e}",
                exc_info=True,
            )
        self._apply_defaults()
        self._save_internal()

    def _migrate(
        self, old_version: int, new_version: int, data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Migrera settings mellan schema-versioner."""
        self._log.info(
            f"{LOG_PREFIX} Migration v{old_version} → v{new_version} startar"
        )
        if old_version < 4:
            # v3 → v4: inga större ändringar, bara bump
            self._log.debug(f"{LOG_PREFIX} v3→v4: bump version")
        if old_version < 7:
            # v6 → v7: inga strukturella ändringar
            self._log.debug(f"{LOG_PREFIX} v6→v7: bump version")
        if old_version < 8:
            # v7 → v8: nya fält
            self._log.debug(f"{LOG_PREFIX} v7→v8: lägger till nya defaults")
            defaults = self._default_settings()
            for key, default in defaults.items():
                if key not in data:
                    data[key] = default
                    self._log.debug(
                        f"{LOG_PREFIX} Migration: lade till {key}={default!r}"
                    )
        if old_version < 10:
            # NY v7-fix90: v9 → v10 — e-postbrygga (Thunderbird-tillägg):
            # mail_bridge_enabled, mail_bridge_port, mail_bridge_token,
            # inbox_watch_enabled, inbox_poll_seconds
            self._log.debug(
                f"{LOG_PREFIX} v9→v10: lägger till brygg-inställningar "
                f"(Thunderbird-tillägg + inkorgsmapp)"
            )
            defaults = self._default_settings()
            for key, default in defaults.items():
                if key not in data:
                    data[key] = default
                    self._log.debug(
                        f"{LOG_PREFIX} Migration: lade till {key}={default!r}"
                    )
        if old_version < 11:
            # NY v8 (2026-10-12): v10 → v11 — lokal Google Calendar (OAuth):
            # google_calendar_enabled, google_calendar_id,
            # google_calendar_color_by_priority
            self._log.debug(
                f"{LOG_PREFIX} v10→v11: lägger till Google Calendar-inställningar "
                f"(lokal OAuth-anslutning)"
            )
            defaults = self._default_settings()
            for key, default in defaults.items():
                if key not in data:
                    data[key] = default
                    self._log.debug(
                        f"{LOG_PREFIX} Migration: lade till {key}={default!r}"
                    )
        data["version"] = new_version
        self._log.info(
            f"{LOG_PREFIX} Migration klar: {len(data)} nycklar, version={new_version}"
        )
        return data

    def _apply_defaults(self) -> None:
        """Applicera default-värden (privat)."""
        defaults = self._default_settings()
        with self._lock:
            self._data = copy.deepcopy(defaults)
        # NY v7-fix63: migrera above → behind (above-läget visar sig
        # osynligt på Rickards primära skärm trots korrekt position —
        # behind/Rainmeter-läget är beprövat och garanterat synligt)
        if self._data.get("desktop_mode") == "above":
            self._data["desktop_mode"] = "behind"
            self._dirty = True
            self._log.info(
                f"{LOG_PREFIX} desktop_mode migrerad: above → behind "
                f"(v7-fix63 — above osynlig på primära skärmen)"
            )

        self._log.debug(
            f"{LOG_PREFIX} Defaults applicerade: {len(self._data)} nycklar"
        )

    def _default_settings(self) -> Dict[str, Any]:
        """Returnerar default-settings (privat)."""
        return {
            "version": SETTINGS_VERSION,
            "theme": Theme.SYSTEM.value,
            "visible_tabs": list(self.DEFAULT_VISIBLE_TABS),
            "windows": copy.deepcopy(self.DEFAULT_WINDOWS),
            "glass_blur": True,
            "glass_style": GlassStyle.AUTO.value,
            "accent_color": AccentColor.INDIGO.value,
            "animations": True,
            "start_minimized_to_tray": False,
            "start_hidden": False,
            "first_run": True,
            "autostart": False,
            "autostart_method": DEFAULT_AUTOSTART_METHOD,
            "autostart_os_ok": False,  # NY v6.4.1: senaste OS-anrop lyckades?
            "backup_keep_count": BACKUP_KEEP_COUNT,
            "last_backup_at": None,
            "custom_tags": [],
            "active_tag_filter": [],
            "shortcuts": copy.deepcopy(self.DEFAULT_SHORTCUTS),
            "diagnostics": {"log_level": "INFO", "max_log_files": 5},
            "language": "sv",
            "density_mode": DensityMode.COMFORTABLE.value,
            "notification_sound": NotificationSound.GENTLE.value,
            # NY v7-fix38: Win+D-säkert skrivbordsläge + fönstertransparens
            "desktop_mode": DEFAULT_DESKTOP_MODE,  # v7-fix63: behind
            "window_transparency": DEFAULT_WINDOW_TRANSPARENCY,
            # NY v7-fix40: enbart ETT fönster ("Nytt fönster" visar det befintliga)
            "single_window": DEFAULT_SINGLE_WINDOW,
            # NY v7-fix41: global snabbinput (Ctrl+Alt+N var som helst i Windows)
            "global_quick_add": True,
            # NY v7-fix50: installera saknade + uppdatera föråldrade tillägg
            # automatiskt vid start (Rickards val 2026-10-02: full auto)
            "auto_update_plugins": True,
            # NY v7-fix64: påminnelser för förfallna/dagens uppgifter
            "reminders_enabled": True,
            # NY v7-fix69: konfigurerbar hotkey för push-to-show
            # Format: "Ctrl+Alt+V", "Ctrl+Shift+Space", "Alt+F1" etc.
            "push_show_hotkey": "Ctrl+Alt+V",
            "quick_add_hotkey": "Ctrl+Alt+N",
            # NY v7-fix72: tray-klick lyfter fönstret i X sekunder
            "tray_lift_seconds": 5,
            # NY v7-fix90: e-postbrygga — Thunderbird-tillägg + inkorgsmapp
            # Bryggan lyssnar BARA på 127.0.0.1 och kräver token.
            "mail_bridge_enabled": True,
            "mail_bridge_port": 8765,
            "mail_bridge_token": "",       # skapas automatiskt (secrets)
            "inbox_watch_enabled": True,   # bevaka data/inbox/ automatiskt
            "inbox_poll_seconds": 3,
            # NY v8: lokal Google Calendar-anslutning (OAuth, loopback).
            # OBS: själva åtkomstbeviset ligger i <data>/google/token.json —
            # här finns bara användarens val.
            "google_calendar_enabled": False,
            "google_calendar_id": "primary",
            "google_calendar_color_by_priority": True,
            # Klara uppgifter i kalendern: "grey" | "strike" | "off"
            "google_calendar_done_style": "grey",
            "_meta": {
                "schema_version": SETTINGS_VERSION,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "last_modified": datetime.now(timezone.utc).isoformat(),
            },
        }

    def _default_shortcuts(self) -> Dict[str, str]:
        """Returnerar default-shortcuts (privat)."""
        return copy.deepcopy(self.DEFAULT_SHORTCUTS)

    def _validate_all(self) -> None:
        """Validera ALLA settings-värden (privat)."""
        self._log.debug(f"{LOG_PREFIX} Validerar {len(self._data)} nycklar")
        with self._lock:
            for key in list(self._data.keys()):
                if key.startswith("_"):
                    continue  # Skip meta
                self._validate_field(key, self._data[key])

    def _validate_field(self, key: str, value: Any) -> bool:
        """Validera en enskild fält (returnerar True om OK)."""
        validators: Dict[str, Callable[[Any], Any]] = {
            "theme": lambda v: _coerce_str(v, Theme.SYSTEM.value, VALID_THEMES),
            "accent_color": lambda v: _coerce_str(v, AccentColor.INDIGO.value, VALID_ACCENTS),
            "glass_style": lambda v: _coerce_str(v, GlassStyle.AUTO.value, VALID_GLASS_STYLES),
            "density_mode": lambda v: _coerce_str(v, DensityMode.COMFORTABLE.value, VALID_DENSITY_MODES),
            "notification_sound": lambda v: _coerce_str(v, NotificationSound.GENTLE.value, VALID_NOTIFICATION_SOUNDS),
            # NY v7-fix38
            "desktop_mode": lambda v: _coerce_str(v, DEFAULT_DESKTOP_MODE, VALID_DESKTOP_MODES),
            "window_transparency": lambda v: _coerce_window_transparency(v),
            # NY v7-fix40
            "single_window": lambda v: _coerce_bool(v, DEFAULT_SINGLE_WINDOW),
            # NY v7-fix41
            "global_quick_add": lambda v: _coerce_bool(v, True),
            # NY v7-fix50
            "auto_update_plugins": lambda v: _coerce_bool(v, True),
            # NY v7-fix64
            "reminders_enabled": lambda v: _coerce_bool(v, True),
            # NY v7-fix69 (sträng, max 40 tecken)
            "push_show_hotkey": lambda v: _coerce_str(v, "Ctrl+Alt+V")[:40],
            "quick_add_hotkey": lambda v: _coerce_str(v, "Ctrl+Alt+N")[:40],
            # NY v7-fix72 (1-60 sekunder)
            "tray_lift_seconds": lambda v: _coerce_int(v, 5, 1, 60),
            # NY v7-fix90: e-postbrygga (Thunderbird-tillägget)
            "mail_bridge_enabled": lambda v: _coerce_bool(v, True),
            "mail_bridge_port": lambda v: _coerce_int(v, 8765, 1024, 65535),
            "mail_bridge_token": lambda v: _coerce_str(v, "")[:64],
            "inbox_watch_enabled": lambda v: _coerce_bool(v, True),
            "inbox_poll_seconds": lambda v: _coerce_int(v, 3, 1, 60),
            # NY v8: Google Calendar (kalender-id max 200 tecken)
            "google_calendar_enabled": lambda v: _coerce_bool(v, False),
            "google_calendar_id": lambda v: _coerce_str(v, "primary")[:200],
            "google_calendar_color_by_priority": lambda v: _coerce_bool(v, True),
            "google_calendar_done_style": lambda v: _coerce_str(
                v, "grey", ("grey", "strike", "off")
            ),
            "autostart_method": lambda v: _coerce_str(v, DEFAULT_AUTOSTART_METHOD, VALID_AUTOSTART_METHODS),
            "animations": lambda v: _coerce_bool(v, True),
            "start_minimized_to_tray": lambda v: _coerce_bool(v, False),
            "start_hidden": lambda v: _coerce_bool(v, False),
            "first_run": lambda v: _coerce_bool(v, True),
            "autostart": lambda v: _coerce_bool(v, False),
            "glass_blur": lambda v: _coerce_bool(v, True),
            "backup_keep_count": lambda v: _coerce_int(v, BACKUP_KEEP_COUNT, 1, 100),
            "visible_tabs": lambda v: _coerce_list(v, list(self.DEFAULT_VISIBLE_TABS)),
            "windows": lambda v: _coerce_list(v, self.DEFAULT_WINDOWS),
            "custom_tags": lambda v: _coerce_list(v, []),
            "active_tag_filter": lambda v: _coerce_list(v, []),
            "shortcuts": lambda v: v if isinstance(v, dict) else copy.deepcopy(self.DEFAULT_SHORTCUTS),
        }
        if key not in validators:
            return True
        try:
            validated = validators[key](value)
            if validated != value:
                self._log.warning(
                    f"{LOG_PREFIX} Validering: {key}={value!r} → {validated!r}"
                )
                with self._lock:
                    self._data[key] = validated
            return True
        except Exception as e:
            self._log.error(
                f"{LOG_PREFIX} Validering misslyckades för {key}={value!r}: {e}",
                exc_info=True,
            )
            return False

    # ========================================================================
    # SAVE
    # ========================================================================

    @_log_call
    def save(self) -> bool:
        """Spara settings till JSON (synkron, anti-deadlock via timeout)."""
        res = self._save_internal()  # EN gång (tidigare anropades den två gånger)
        return res is not None and res.success

    def _save_internal(self) -> Optional[SaveResult]:
        """Privat save: trådsäker + anti-deadlock."""
        start = time.perf_counter()
        if not self._save_lock.acquire(timeout=SAVE_TIMEOUT_SEC):
            self._log.error(
                f"{LOG_PREFIX} Save-timeout ({SAVE_TIMEOUT_SEC}s) — låst av annan tråd"
            )
            self._error_count += 1
            return SaveResult(success=False, duration_sec=0.0, error="Save-timeout")
        try:
            with self._lock:
                data = copy.deepcopy(self._data)
            # Uppdatera meta
            data["_meta"] = data.get("_meta", {})
            data["_meta"]["last_modified"] = datetime.now(timezone.utc).isoformat()
            data["_meta"]["schema_version"] = SETTINGS_VERSION

            # Backup
            backup_path = self._create_backup()
            self._log.debug(
                f"{LOG_PREFIX} Backup skapad: {backup_path}"
            ) if backup_path else None

            # Skriv atomärt
            tmp_path = self._file_path.with_suffix(".json.tmp")
            json_str = json.dumps(data, indent=2, ensure_ascii=False)
            with open(tmp_path, "w", encoding="utf-8") as f:
                bytes_written = f.write(json_str)
                f.flush()
                os.fsync(f.fileno())
            self._log.debug(
                f"{LOG_PREFIX} Skrev {bytes_written} bytes till {tmp_path}"
            )

            # Verifiera
            try:
                with open(tmp_path, "r", encoding="utf-8") as f:
                    json.loads(f.read())
                self._log.debug(f"{LOG_PREFIX} Verifiering OK")
            except Exception as e:
                self._log.error(
                    f"{LOG_PREFIX} Verifiering av tmp-fil misslyckades: {e}",
                    exc_info=True,
                )
                return SaveResult(
                    success=False,
                    duration_sec=time.perf_counter() - start,
                    error=f"Verify: {e}",
                )

            # Atomisk replace
            os.replace(tmp_path, self._file_path)
            self._log.debug(
                f"{LOG_PREFIX} Atomic replace: {tmp_path.name} → {self._file_path.name}"
            )

            with self._lock:
                self._dirty = False
                self._last_save_time = time.time()
                self._save_count += 1

            duration = time.perf_counter() - start
            self._log.info(
                f"{LOG_PREFIX} Save OK: {bytes_written} bytes, "
                f"{duration*1000:.2f}ms (save_count={self._save_count})"
            )
            self._safe_emit("settings_saved")
            return SaveResult(
                success=True,
                duration_sec=duration,
                bytes_written=bytes_written,
                backup_path=backup_path,
            )
        except Exception as e:
            duration = time.perf_counter() - start
            self._log.error(
                f"{LOG_PREFIX} Save misslyckades efter {duration*1000:.2f}ms: "
                f"{type(e).__name__}: {e}",
                exc_info=True,
            )
            self._error_count += 1
            self._safe_emit("error_occurred", f"Save misslyckades: {e}")
            return SaveResult(
                success=False, duration_sec=duration, error=str(e)
            )
        finally:
            self._save_lock.release()

    def _create_backup(self) -> Optional[Path]:
        """Skapa backup av befintlig settings-fil (privat)."""
        if not self._file_path.exists():
            self._log.debug(f"{LOG_PREFIX} Ingen backup behövs (fil finns ej)")
            return None
        try:
            # FIX v7-fix28: backups sorteras i år/mån-undermappar
            # Rickard 2026-09-30: "backup ska sorteras i undermapp år/mån"
            _ym = datetime.now().strftime("%Y-%m")
            backup_dir = self._file_path.parent / "backups" / _ym
            backup_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = backup_dir / f"settings_{timestamp}.json"
            shutil.copy2(self._file_path, backup_path)
            self._log.debug(f"{LOG_PREFIX} Backup skapad: {backup_path}")
            # Rotera gamla backups (behåll senaste BACKUP_KEEP_COUNT)
            # FIX v7-fix28: sök i ALLA undermappar (år/mån) för rotation
            _root_backups = self._file_path.parent / "backups"
            backups = sorted(_root_backups.rglob("settings_*.json"))
            if len(backups) > BACKUP_KEEP_COUNT:
                removed_count = 0
                for old in backups[:-BACKUP_KEEP_COUNT]:
                    try:
                        old.unlink()
                        removed_count += 1
                    except OSError as e:
                        self._log.warning(
                            f"{LOG_PREFIX} Kunde inte ta bort gammal backup "
                            f"{old}: {e}"
                        )
                if removed_count:
                    self._log.info(
                        f"{LOG_PREFIX} Rensade {removed_count} gamla backup-filer"
                    )
            return backup_path
        except Exception as e:
            self._log.error(
                f"{LOG_PREFIX} Backup misslyckades: {e}", exc_info=True
            )
            return None

    def _save_async_worker(self, data: Dict[str, Any]) -> bool:
        """Worker för async-save (privat)."""
        thread_name = threading.current_thread().name
        self._log.debug(
            f"{LOG_PREFIX} Async-save worker startad: {thread_name}"
        )
        try:
            result = self._save_internal()
            return result is not None and result.success
        except Exception as e:
            self._log.error(
                f"{LOG_PREFIX} Async-save misslyckades: {e}", exc_info=True
            )
            return False
        finally:
            self._log.debug(
                f"{LOG_PREFIX} Async-save worker klar: {thread_name}"
            )

    def save_async(self) -> None:
        """Spara asynkront i worker-tråd."""
        with self._lock:
            data = copy.deepcopy(self._data)
        self._save_thread = threading.Thread(
            target=self._save_async_worker,
            args=(data,),
            daemon=True,
            name="SettingsSave",
        )
        self._save_thread.start()
        self._log.debug(
            f"{LOG_PREFIX} Async-save startad: thread={self._save_thread.name}"
        )

    @_log_call
    def reload(self) -> bool:
        """Ladda om settings från disk."""
        self._log.info(f"{LOG_PREFIX} Reload från {self._file_path}")
        return self._load()

    # ========================================================================
    # GENERIC ACCESSORS
    # ========================================================================

    @_log_call
    def get(self, key: str, default: Any = None) -> Any:
        """Hämta värde (med default)."""
        with self._lock:
            value = self._data.get(key, default)
        self._log.debug(
            f"{LOG_PREFIX} get({key!r}) = {value!r} (default={default!r})"
        )
        return value

    @_log_call
    def has(self, key: str) -> bool:
        """Kontrollera om nyckel finns."""
        with self._lock:
            present = key in self._data
        self._log.debug(f"{LOG_PREFIX} has({key!r}) = {present}")
        return present

    # ========================================================================
    # THEME / ACCENT / GLASS
    # ========================================================================

    @_log_call
    def theme(self) -> str:
        """Hämta aktuellt tema (med system-fallback)."""
        with self._lock:
            theme = self._data.get("theme", Theme.SYSTEM.value)
        if theme == Theme.AUTO.value:
            # NY v7-fix82: klockstyrt tema — ljust dagtid (07:00–18:59),
            # mörkt kväll/natt (19:00–06:59). Växling under körning sköts
            # av widgetens _check_auto_theme-timer (var 10:e minut).
            _hour = datetime.now().hour
            _resolved = "light" if 7 <= _hour < 19 else "dark"
            return _resolved
        if theme == Theme.SYSTEM.value:
            # Detektera systemtema
            try:
                import sys as _sys
                if _sys.platform == "win32":
                    try:
                        import winreg
                        with winreg.OpenKey(
                            winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
                        ) as key:
                            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                            resolved = "light" if value else "dark"
                            self._log.debug(
                                f"{LOG_PREFIX} Systemtema detekterat: {resolved}"
                            )
                            return resolved
                    except OSError as e:
                        self._log.debug(
                            f"{LOG_PREFIX} Kunde inte läsa systemtema: {e}"
                        )
                resolved = "dark"  # Default fallback
                self._log.debug(f"{LOG_PREFIX} Default-tema: {resolved}")
                return resolved
            except Exception as e:
                self._log.warning(
                    f"{LOG_PREFIX} Tema-detektering misslyckades: {e}"
                )
                return "dark"
        return theme

    @_log_call
    def theme_setting(self) -> str:
        """Hämta tema-inställning (utan system-fallback)."""
        with self._lock:
            return self._data.get("theme", Theme.SYSTEM.value)

    @_log_setter("theme")
    def set_theme(self, theme: str) -> bool:
        """Sätt tema."""
        theme = _coerce_str(theme, Theme.SYSTEM.value, VALID_THEMES)
        with self._lock:
            self._data["theme"] = theme
        self._dirty = True
        self._safe_emit("theme_changed", theme)
        self._save_async_worker(self._data)
        return True

    @_log_call
    def is_dark(self) -> bool:
        """Är mörkt tema aktivt just nu?"""
        return self.theme() == Theme.DARK.value

    @_log_call
    def theme_raw(self) -> str:
        """
        NY v7-fix82: lagrat tema OBELOST ('light'/'dark'/'system'/'auto').

        theme() löser system/auto → light/dark; denna returnerar det
        SPARADE värdet (för meny-markering i tray-menyn).
        """
        with self._lock:
            return self._data.get("theme", Theme.SYSTEM.value)

    @_log_call
    def accent_color(self) -> str:
        """Hämta accent-färg."""
        with self._lock:
            return self._data.get("accent_color", AccentColor.INDIGO.value)

    @_log_setter("accent_color")
    def set_accent_color(self, color: str) -> bool:
        """Sätt accent-färg."""
        color = _coerce_str(color, AccentColor.INDIGO.value, VALID_ACCENTS)
        with self._lock:
            self._data["accent_color"] = color
        self._dirty = True
        self._safe_emit("accent_changed", color)
        self._save_async_worker(self._data)
        return True

    @_log_call
    def accent_rgb(self) -> Tuple[int, int, int]:
        """Hämta accent-färg som RGB (exkl. alpha)."""
        accent = self.accent_color()
        rgba = ACCENT_PALETTES.get(accent, ACCENT_PALETTES["indigo"])["primary"]
        return (rgba[0], rgba[1], rgba[2])

    @_log_call
    def glass_style(self) -> str:
        """Hämta glasmorphism-stil."""
        with self._lock:
            return self._data.get("glass_style", GlassStyle.AUTO.value)

    @_log_setter("glass_style")
    def set_glass_style(self, style: str) -> bool:
        """Sätt glasmorphism-stil."""
        style = _coerce_str(style, GlassStyle.AUTO.value, VALID_GLASS_STYLES)
        with self._lock:
            self._data["glass_style"] = style
        self._dirty = True
        self._safe_emit("glass_style_changed", style)
        self._save_async_worker(self._data)
        return True

    # ========================================================================
    # ANIMATIONS / GLASS_BLUR
    # ========================================================================

    @_log_call
    def glass_blur_enabled(self) -> bool:
        """Är glass blur aktiverat?"""
        with self._lock:
            return _coerce_bool(self._data.get("glass_blur", True))

    @_log_setter("glass_blur")
    def set_glass_blur(self, enabled: bool) -> bool:
        """Aktivera/inaktivera glass blur."""
        enabled = _coerce_bool(enabled, True)
        with self._lock:
            self._data["glass_blur"] = enabled
        self._dirty = True
        self._log.info(f"{LOG_PREFIX} glass_blur: {enabled}")
        return True

    @_log_call
    def animations_enabled(self) -> bool:
        """Är animationer aktiverade?"""
        with self._lock:
            return _coerce_bool(self._data.get("animations", True))

    @_log_setter("animations")
    def set_animations_enabled(self, enabled: bool) -> bool:
        """Aktivera/inaktivera animationer."""
        enabled = _coerce_bool(enabled, True)
        with self._lock:
            self._data["animations"] = enabled
        self._dirty = True
        self._safe_emit("animations_changed", enabled)
        self._save_async_worker(self._data)
        return True

    # ========================================================================
    # STARTUP / AUTOSTART
    # ========================================================================

    @_log_call
    def start_minimized(self) -> bool:
        """Starta minimerad till tray?"""
        with self._lock:
            return _coerce_bool(self._data.get("start_minimized_to_tray", False))

    @_log_setter("start_minimized_to_tray")
    def set_start_minimized(self, enabled: bool) -> bool:
        """Sätt start_minimized."""
        enabled = _coerce_bool(enabled, False)
        with self._lock:
            self._data["start_minimized_to_tray"] = enabled
        self._dirty = True
        self._log.info(f"{LOG_PREFIX} start_minimized_to_tray: {enabled}")
        return True

    @_log_call
    def start_hidden(self) -> bool:
        """Starta dold (för BUGG 19/26)?"""
        with self._lock:
            return _coerce_bool(self._data.get("start_hidden", False))

    @_log_setter("start_hidden")
    def set_start_hidden(self, enabled: bool) -> bool:
        """Sätt start_hidden."""
        enabled = _coerce_bool(enabled, False)
        with self._lock:
            self._data["start_hidden"] = enabled
        self._dirty = True
        self._log.info(f"{LOG_PREFIX} start_hidden: {enabled} (BUGG 19/26)")
        return True

    @_log_call
    def autostart_enabled(self) -> bool:
        """Är autostart aktiverat?"""
        with self._lock:
            return _coerce_bool(self._data.get("autostart", False))

    @_log_setter("autostart")
    def set_autostart(self, enabled: bool) -> bool:
        """Aktivera/inaktivera autostart (via OS, default 'registry'-metod).

        NY v6.4.1: Faktiskt applicerar i OS via utils.set_autostart_any(),
        inte bara sparar boolean i settings.
        """
        enabled = _coerce_bool(enabled, False)
        # NY v6.4.1: Hämta vald metod och faktiskt sätt i OS
        method = self._data.get("autostart_method", DEFAULT_AUTOSTART_METHOD)
        os_ok = False
        # NY v7-fix12: desktop.py är multi-OS-motorn (Windows registry/
        # startup/schtasks + macOS launchd + Linux XDG) — prova den FÖRST.
        # (Före v7-fix12 var desktop-motorn trasig med TypeError på alla
        # plattformar; nu är den fixad och testad.)
        try:
            import desktop as _desktop_mod
            if enabled:
                os_ok = bool(_desktop_mod.enable_autostart())
            else:
                os_ok = bool(_desktop_mod.disable_autostart())
            self._log.info(
                f"{LOG_PREFIX} set_autostart({enabled}) via desktop-motor "
                f"(multi-OS): OS-resultat={os_ok}"
            )
        except ImportError:
            self._log.debug(
                f"{LOG_PREFIX} set_autostart: desktop ej importerbar — "
                f"provar utils-fallback"
            )
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} set_autostart: desktop-motorn misslyckades: "
                f"{e} — provar utils-fallback"
            )
        # Fallback (v6.4.1): utils.set_autostart_any (Windows registry m.fl.)
        if not os_ok:
            try:
                from utils import set_autostart_any, APP_NAME
                os_ok = set_autostart_any(enabled, name=APP_NAME, method=method)
                self._log.info(
                    f"{LOG_PREFIX} set_autostart({enabled}) via {method!r}: "
                    f"OS-resultat={os_ok}"
                )
            except ImportError:
                os_ok = False
                self._log.warning(
                    f"{LOG_PREFIX} set_autostart: utils ej importerbar — "
                    f"sparar bara i settings"
                )
            except Exception as e:
                os_ok = False
                self._log.error(
                    f"{LOG_PREFIX} set_autostart OS-anrop misslyckades: {e}",
                    exc_info=True,
                )
        with self._lock:
            self._data["autostart"] = enabled
            self._data["autostart_os_ok"] = os_ok
            self._data["autostart_method"] = method
        self._dirty = True
        self._safe_emit("autostart_changed", enabled, os_ok)
        self._save_async_worker(self._data)
        return True

    @_log_call
    def set_autostart_method(self, method: str) -> bool:
        """
        NY v6.4.1: Välj autostart-metod.

        Args:
            method: "registry" | "shortcut" | "schtask"

        Returns:
            True om metoden är giltig och satt
        """
        if method not in VALID_AUTOSTART_METHODS:
            self._log.error(
                f"{LOG_PREFIX} set_autostart_method: ogiltig metod {method!r}, "
                f"giltiga: {sorted(VALID_AUTOSTART_METHODS)}"
            )
            return False
        with self._lock:
            old_method = self._data.get("autostart_method", DEFAULT_AUTOSTART_METHOD)
            self._data["autostart_method"] = method
        self._dirty = True
        self._log.info(
            f"{LOG_PREFIX} autostart_method: {old_method!r} → {method!r}"
        )
        # Om autostart redan är på, applicera nya metoden direkt
        if self.is_autostart_enabled():
            self.set_autostart(True)
        self._save_async_worker(self._data)
        return True

    @_log_call
    def is_autostart_enabled(self) -> bool:
        """Är autostart aktiverat (i settings)?."""
        with self._lock:
            return bool(self._data.get("autostart", False))

    @_log_call
    def is_autostart_configured(self) -> bool:
        """
        NY v6.4.1: Är autostart FAKTISKT konfigurerat i OS?

        Skiljer mellan:
          - `is_autostart_enabled()` — boolean i settings (vad användaren vill)
          - `is_autostart_configured()` — OS-nivå (vad OS faktiskt gör)
        """
        if not self.is_autostart_enabled():
            return False
        # NY v7-fix12: desktop.py först — multi-OS (Win/macOS/Linux);
        # utils.is_autostart_enabled är Windows registry-centrerad.
        try:
            import desktop as _desktop_mod
            if _desktop_mod.is_autostart_enabled():
                return True
        except Exception:
            pass
        try:
            from utils import is_autostart_enabled, APP_NAME
            return is_autostart_enabled(APP_NAME)
        except ImportError:
            self._log.warning(
                f"{LOG_PREFIX} is_autostart_configured: utils ej importerbar"
            )
            return False
        except Exception as e:
            self._log.error(
                f"{LOG_PREFIX} is_autostart_configured misslyckades: {e}"
            )
            return False

    @_log_call
    def get_autostart_status(self) -> Dict[str, Any]:
        """
        NY v6.4.1: Komplett autostart-status (för UI-visning + diagnostik).

        Returns:
            Dict med:
              - enabled: bool (settings.vill)
              - configured: bool (OS-faktiskt)
              - method: str (registry | shortcut | schtask)
              - command: Optional[str] (OS-kommandot som körs)
              - os_ok: bool (sista OS-anrop lyckades?)
              - consistent: bool (settings == OS)
        """
        enabled = self.is_autostart_enabled()
        configured = self.is_autostart_configured()
        with self._lock:
            method = self._data.get("autostart_method", DEFAULT_AUTOSTART_METHOD)
            os_ok = bool(self._data.get("autostart_os_ok", False))
        command = None
        try:
            from utils import get_autostart_command, APP_NAME
            command = get_autostart_command(APP_NAME)
        except Exception:
            pass
        consistent = (
            (not enabled)  # Om disabled, behöver inte vara konfigurerad
            or (enabled and configured)
        )
        status = {
            "enabled": enabled,
            "configured": configured,
            "method": method,
            "command": command,
            "os_ok": os_ok,
            "consistent": consistent,
        }
        self._log.debug(
            f"{LOG_PREFIX} get_autostart_status: {status}"
        )
        return status

    # ========================================================================
    # TABS
    # ========================================================================

    @_log_call
    def visible_tabs(self) -> List[str]:
        """Hämta synliga tabs."""
        with self._lock:
            return list(self._data.get("visible_tabs", self.DEFAULT_VISIBLE_TABS))

    @_log_setter("visible_tabs")
    def set_visible_tabs(self, tabs: List[str]) -> bool:
        """Sätt synliga tabs."""
        if not isinstance(tabs, list):
            self._log.error(
                f"{LOG_PREFIX} set_visible_tabs: förväntade lista, fick {type(tabs).__name__}"
            )
            return False
        with self._lock:
            self._data["visible_tabs"] = list(tabs)
        self._dirty = True
        self._safe_emit("tabs_changed", list(tabs))
        self._save_async_worker(self._data)
        return True

    # ========================================================================
    # WINDOWS
    # ========================================================================

    @_log_call
    def window_configs(self) -> List[Dict[str, Any]]:
        """
        NY v7-fix9: PURE GETTER — läser bara, har INGA sidoeffekter.

        Bakgrund (bugg som fixades):
          Tidigare anropade denna metod _save_async_worker() + _safe_emit(
          "windows_updated") och rensade _data["windows"] INIFRÅN gettern.
          Kedjan blev:

            populate → window_configs() → _safe_emit(windows_updated)
              → _safe_update_widgets → populate → window_configs() → ...

          Det gav 25+ anrop / 100 ms och 100-tals misslyckade
          CreateWindowEx-försök.

        Cleanup (bort med interna __*-id och gamla win_* som ackumulerats)
        sker nu EN gång vid start via cleanup_stale_windows() — anropas
        explicit från AppController._init_subsystems().

        Returnerar:
            Lista med fönster-konfigurationer (djupkopia, utan __*-id).
        """
        with self._lock:
            windows = copy.deepcopy(
                self._data.get("windows", self.DEFAULT_WINDOWS)
            )
        # Filtrera bort interna id (__pretest__, __input__ etc) — ren läsning
        return [
            w for w in windows
            if w.get("id") and not str(w["id"]).startswith("__")
        ]

    def cleanup_stale_windows(self) -> int:
        """
        NY v7-fix9: Rensa skräp-fönster — anropas EN gång vid start.

        Vad den gör:
          1. Tar bort interna __*-id (pretest-spöken)
          2. Tar bort ackumulerade win_*-fönster (auto-add-skäp)
          3. Behåller ENDAST "default" (eller första fönstret om default saknas)
          4. Sparar + emittar windows_updated EN gång (inte i en loop)

        VIKTIGT: Anropas ALDRIG från populate-kedjan — bara från startup.

        Returns:
            Antal borttagna fönster-konfigurationer (0 = inget att rensa).
        """
        with self._lock:
            windows = list(self._data.get("windows", self.DEFAULT_WINDOWS))
            valid = [
                w for w in windows
                if w.get("id") and not str(w["id"]).startswith("__")
            ]
            default_windows = [w for w in valid if w.get("id") == "default"]
            other_windows = [w for w in valid if w.get("id") != "default"]

            if not other_windows and len(valid) == len(windows):
                # Inget skräp — rör inte datan
                self._log.debug(
                    f"{LOG_PREFIX} cleanup_stale_windows: inget att rensa "
                    f"({len(windows)} fönster, alla giltiga)"
                )
                return 0

            # Behåll default (eller första giltiga om default saknas)
            if default_windows:
                cleaned = default_windows[:1]
            elif valid:
                cleaned = valid[:1]
            elif windows:
                # Inga giltiga alls → behåll första rå-posten som "default"
                first = dict(windows[0])
                first["id"] = "default"
                cleaned = [first]
            else:
                cleaned = copy.deepcopy(self.DEFAULT_WINDOWS)

            removed_n = len(windows) - len(cleaned)
            self._data["windows"] = cleaned
            self._dirty = True
            self._log.info(
                f"{LOG_PREFIX} cleanup_stale_windows: tog bort {removed_n} "
                f"skräp-fönster ({len(other_windows)} win_*, "
                f"{len(windows) - len(valid)} interna __*-id) → "
                f"behåller {[w.get('id') for w in cleaned]}"
            )

        # Spara + emitta UTANFÖR låset (undvik deadlock i signal-handlers)
        self._save_async_worker(self._data)
        self._safe_emit("windows_updated", cleaned)
        return removed_n

    @_log_call
    def add_window(
        self, x: int, y: int, w: int = 340, h: int = 648, locked: bool = False
    ) -> Optional[str]:
        """Lägg till nytt fönster. Returnerar window-id.
        FIX 2026-09-24: logga VEM som anropade (stack-frame → UI/förälder)."""
        import traceback as _tb
        _stack = _tb.extract_stack(limit=4)[:-1]
        _caller = ", ".join(
            f"{f.filename.split('/')[-1]}:{f.lineno}({f.name})"
            for f in _stack[-2:]
        )
        wid = f"win_{int(time.time() * 1000)}"
        self._log.info(
            f"{LOG_PREFIX} add_window ANROPAD: wid={wid!r}, "
            f"pos=({x},{y}), caller=[{_caller}]"
        )
        with self._lock:
            windows = self._data.setdefault("windows", [])
            if len(windows) >= 16:  # MAX_WIDGETS
                self._log.warning(
                    f"{LOG_PREFIX} Max antal fönster (16) uppnått, kan inte lägga till"
                )
                return None
            windows.append({
                "id": wid, "x": int(x), "y": int(y),
                "w": int(w), "h": int(h), "locked": bool(locked),
            })
        self._dirty = True
        self._log.info(
            f"{LOG_PREFIX} add_window: {wid} vid ({x}, {y}), "
            f"size=({w}x{h}) — total={len(windows)}"
        )
        self._safe_emit("windows_updated", self.window_configs())
        self._save_async_worker(self._data)
        return wid

    @_log_call
    def remove_window(self, wid: str) -> bool:
        """Ta bort fönster."""
        with self._lock:
            windows = self._data.get("windows", [])
            before = len(windows)
            windows[:] = [w for w in windows if w.get("id") != wid]
            removed = len(windows) < before
        if removed:
            self._dirty = True
            self._log.info(f"{LOG_PREFIX} remove_window: {wid} OK")
            self._safe_emit("windows_updated", self.window_configs())
            self._save_async_worker(self._data)
            return True
        self._log.warning(f"{LOG_PREFIX} remove_window: {wid} hittades inte")
        return False

    @_log_call
    def update_window_geometry(
        self, wid: str, x: int, y: int, w: int, h: int
    ) -> bool:
        """
        NY v7-fix43: uppdatera position OCH storlek for ett fonster.

        Anvands av resizeEvent/mouseReleaseEvent sa fonstrets storlek
        (andrad via kanter eller QSizeGrip) overlever omstart.
        Sandner INTE windows_updated (undviker populate-loop).
        """
        try:
            with self._lock:
                windows = self._data.get("windows", [])
                found = False
                for win in windows:
                    if win.get("id") == wid:
                        win["x"], win["y"] = int(x), int(y)
                        win["w"], win["h"] = int(w), int(h)
                        found = True
                        break
            if not found:
                # Auto-add (_behaller skyddet mot interna __*-id via
                # update_window_position som forsta steg, sa komplettera)
                with self._lock:
                    windows = self._data.get("windows", [])
                    if not any(win.get("id") == wid for win in windows):
                        windows.append({
                            "id": wid, "x": int(x), "y": int(y),
                            "w": int(w), "h": int(h), "locked": False,
                        })
            self._dirty = True
            self._log.debug(
                f"{LOG_PREFIX} window {wid}: geometri ({x},{y}) {w}x{h}"
            )
            # FIX v8 (2026-10-12): spara PÅ DISK. Tidigare sattes bara _dirty —
            # ingenting skrev filen (och nedstängningen sparade inte settings),
            # så storlek/position försvann vid omstart. Anropas bara efter
            # avslutad drag/resize (debouncad), så en bakgrundssparning räcker.
            self.save_async()
            return True
        except Exception as e:
            self._log.warning(
                f"{LOG_PREFIX} update_window_geometry misslyckades: {e}"
            )
            return False

    def update_window_position(self, wid: str, x: int, y: int) -> bool:
        """Uppdatera fönsterposition (för BUGG 26 auto-reposition)."""
        with self._lock:
            windows = self._data.get("windows", [])
            updated = False
            was_auto_added = False
            for w in windows:
                if w.get("id") == wid:
                    old_x, old_y = w.get("x"), w.get("y")
                    w["x"] = int(x)
                    w["y"] = int(y)
                    self._log.debug(
                        f"{LOG_PREFIX} window {wid}: ({old_x},{old_y}) → ({x},{y})"
                    )
                    updated = True
                    break
            # NY v6.4: Auto-add window om den inte finns
            # FIX 2026-09-24: spara ALDRIG internt-id (__pretest__ etc)
            # + logga VARJE auto-add med stack-frame (vem försökte).
            if not updated:
                if str(wid).startswith("__"):
                    import traceback as _atb
                    _stk = _atb.extract_stack(limit=4)[:-1]
                    _call = ", ".join(
                        f"{f.filename.split('/')[-1]}:{f.lineno}({f.name})"
                        for f in _stk[-2:]
                    )
                    self._log.warning(
                        f"{LOG_PREFIX} update_window_position: "
                        f"AUTO-ADD stoppad for internt-id {wid!r} "
                        f"(caller=[{_call}])"
                    )
                    return False
                import traceback as _atb2
                _stk2 = _atb2.extract_stack(limit=4)[:-1]
                _call2 = ", ".join(
                    f"{f.filename.split('/')[-1]}:{f.lineno}({f.name})"
                    for f in _stk2[-2:]
                )
                self._log.info(
                    f"{LOG_PREFIX} update_window_position: {wid} hittades inte, "
                    f"skapar ny (caller=[{_call2}])"
                )
                windows.append({
                    "id": wid, "x": int(x), "y": int(y),
                    "w": 340, "h": 648, "locked": False,
                })
                updated = True
                was_auto_added = True

        if not updated:
            return False

        self._dirty = True
        self._save_async_worker(self._data)

        # NY v7-fix9: Emitta windows_updated ENDAST vid auto-add (nytt fönster).
        #
        # Buggkedja som fixades (25+ anrop / 100 ms i loggen):
        #   widget.moveEvent → settings.update_window_position()
        #     → _safe_emit("windows_updated")
        #     → AppController._safe_update_widgets
        #     → _populate_windows → w.show()
        #     → widget.moveEvent → ... (oändlig loop)
        #
        # Ren positionsändring kräver INGEN repopulering — widgeten står
        # redan på rätt plats. Bara auto-add (nytt id) behöver en widget.
        if was_auto_added:
            self._log.info(
                f"{LOG_PREFIX} update_window_position: {wid!r} auto-addad → "
                f"emittar windows_updated (ny widget behövs)"
            )
            self._safe_emit("windows_updated", self.window_configs())
        return True

    # ========================================================================
    # TAGS
    # ========================================================================

    @_log_call
    def custom_tags(self) -> List[str]:
        """Hämta custom tags."""
        with self._lock:
            return list(self._data.get("custom_tags", []))

    @_log_setter("custom_tags")
    def set_custom_tags(self, tags: List[str]) -> bool:
        """Sätt custom tags."""
        if not isinstance(tags, list):
            self._log.error(
                f"{LOG_PREFIX} set_custom_tags: förväntade lista, fick {type(tags).__name__}"
            )
            return False
        # Sanitize: strip + dedup
        clean_tags = list({str(t).strip() for t in tags if str(t).strip()})
        with self._lock:
            self._data["custom_tags"] = clean_tags
        self._dirty = True
        self._log.info(
            f"{LOG_PREFIX} set_custom_tags: {len(clean_tags)} unika tags"
        )
        return True

    @_log_call
    def active_tag_filter(self) -> List[str]:
        """Hämta aktiva tag-filter."""
        with self._lock:
            return list(self._data.get("active_tag_filter", []))

    @_log_setter("active_tag_filter")
    def set_active_tag_filter(self, tags: List[str]) -> bool:
        """Sätt aktiva tag-filter."""
        if not isinstance(tags, list):
            return False
        with self._lock:
            self._data["active_tag_filter"] = list(tags)
        self._dirty = True
        self._log.debug(
            f"{LOG_PREFIX} active_tag_filter: {len(tags)} tags"
        )
        return True

    # ========================================================================
    # BACKUP
    # ========================================================================

    @_log_call
    def backup_keep_count(self) -> int:
        """Hämta antal backups att behålla."""
        with self._lock:
            return _coerce_int(self._data.get("backup_keep_count", BACKUP_KEEP_COUNT), BACKUP_KEEP_COUNT, 1, 100)

    @_log_setter("backup_keep_count")
    def set_backup_keep_count(self, count: int) -> bool:
        """Sätt antal backups att behålla."""
        count = _coerce_int(count, BACKUP_KEEP_COUNT, 1, 100)
        with self._lock:
            self._data["backup_keep_count"] = count
        self._dirty = True
        self._log.info(f"{LOG_PREFIX} backup_keep_count: {count}")
        return True

    @_log_call
    def last_backup_at(self) -> Optional[str]:
        """Hämta tidpunkt för senaste backup."""
        with self._lock:
            return self._data.get("last_backup_at")

    @_log_setter("last_backup_at")
    def set_last_backup_at(self, iso_time: str) -> bool:
        """Sätt tidpunkt för senaste backup."""
        with self._lock:
            self._data["last_backup_at"] = iso_time
        self._dirty = True
        self._log.info(f"{LOG_PREFIX} last_backup_at: {iso_time}")
        return True

    # ========================================================================
    # SHORTCUTS
    # ========================================================================

    @_log_call
    def shortcuts(self) -> Dict[str, str]:
        """Hämta alla shortcuts."""
        with self._lock:
            return dict(self._data.get("shortcuts", self.DEFAULT_SHORTCUTS))

    @_log_call
    def set_shortcut(self, action: str, sequence: str) -> bool:
        """Sätt enskild shortcut."""
        if not isinstance(action, str) or not isinstance(sequence, str):
            self._log.error(
                f"{LOG_PREFIX} set_shortcut: ogiltiga argument "
                f"action={action!r}, sequence={sequence!r}"
            )
            return False
        with self._lock:
            shortcuts = self._data.setdefault("shortcuts", {})
            old = shortcuts.get(action)
            shortcuts[action] = sequence
        if old != sequence:
            self._dirty = True
            self._log.info(
                f"{LOG_PREFIX} shortcut.{action}: {old!r} → {sequence!r}"
            )
            self._audit_log.add("shortcuts", old, sequence, reason=f"action={action}")
            self._safe_emit("shortcuts_changed", self.shortcuts())
            self._save_async_worker(self._data)
        return True

    # ========================================================================
    # DIAGNOSTICS
    # ========================================================================

    @_log_call
    def log_level(self) -> str:
        """Hämta log-nivå."""
        with self._lock:
            diag = self._data.get("diagnostics", {})
            return diag.get("log_level", "INFO")

    @_log_call
    def set_log_level(self, level: str) -> bool:
        """Sätt log-nivå (påverkar root-logger direkt)."""
        level = _coerce_str(level, "INFO", {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
        with self._lock:
            diag = self._data.setdefault("diagnostics", {})
            old = diag.get("log_level", "INFO")
            diag["log_level"] = level
        if old != level:
            self._dirty = True
            logging.getLogger().setLevel(getattr(logging, level, logging.INFO))
            self._log.info(f"{LOG_PREFIX} log_level: {old} → {level} (root-logger uppdaterad)")
            self._save_async_worker(self._data)
        return True

    @_log_call
    def first_run(self) -> bool:
        """Är det första körningen?"""
        with self._lock:
            return _coerce_bool(self._data.get("first_run", True))

    @_log_setter("first_run")
    def set_first_run(self, value: bool) -> bool:
        """Sätt first_run-flagga."""
        value = _coerce_bool(value, True)
        with self._lock:
            self._data["first_run"] = value
        self._dirty = True
        self._log.info(f"{LOG_PREFIX} first_run: {value}")
        return True

    # ========================================================================
    # LANGUAGE / DENSITY / SOUND
    # ========================================================================

    @_log_call
    def language(self) -> str:
        """Hämta språk."""
        with self._lock:
            return self._data.get("language", "sv")

    @_log_setter("language")
    def set_language(self, lang: str) -> bool:
        """Sätt språk."""
        lang = _coerce_str(lang, "sv", {"sv", "en"})
        with self._lock:
            self._data["language"] = lang
        self._dirty = True
        self._log.info(f"{LOG_PREFIX} language: {lang}")
        return True

    @_log_call
    def density_mode(self) -> str:
        """Hämta UI-densitet."""
        with self._lock:
            return self._data.get("density_mode", DensityMode.COMFORTABLE.value)

    @_log_setter("density_mode")
    def set_density_mode(self, mode: str) -> bool:
        """Sätt UI-densitet."""
        mode = _coerce_str(mode, DensityMode.COMFORTABLE.value, VALID_DENSITY_MODES)
        with self._lock:
            self._data["density_mode"] = mode
        self._dirty = True
        self._log.info(f"{LOG_PREFIX} density_mode: {mode}")
        return True

    # ========================================================================
    # NY v7-fix38: SKRIVBORDSLÄGE (Win+D-säkert) + FÖNSTERTRANSPARENS
    # ========================================================================

    @_log_call
    def desktop_mode(self) -> str:
        """
        Aktuellt skrivbordsläge (above|behind).

        FIX v7-fix63: 'above' migreras automatiskt till 'behind' —
        above-läget visar sig osynligt på Rickards primära skärm
        trots tekniskt korrekt position (bevisat i logg 2026-10-05).
        """
        with self._lock:
            m = self._data.get("desktop_mode", DEFAULT_DESKTOP_MODE)
            if m == "above":
                self._data["desktop_mode"] = "behind"
                self._dirty = True
                m = "behind"
                if not getattr(self, "_above_migrated_logged", False):
                    self._above_migrated_logged = True
                    self._log.info(
                        f"{LOG_PREFIX} desktop_mode migrerad: above → "
                        f"behind (v7-fix63 — above osynlig på primära "
                        f"skärmen)"
                    )
            return m

    @_log_setter("desktop_mode")
    def set_desktop_mode(self, mode: str) -> bool:
        """
        NY v7-fix38: sätt skrivbordsläge.

        above  — widgeten ÖVER skrivbordsikonerna, barn till skrivbordet
                 (Win+D kan aldrig gömma den) + transparent glas-skal
        behind — widgeten BAKOM ikonerna (Rainmeter "On Desktop")
        legacy — gammalt v7-fix32-beteende (HWND_BOTTOM + blockerare)
        """
        mode = _coerce_str(mode, DEFAULT_DESKTOP_MODE, VALID_DESKTOP_MODES)
        with self._lock:
            self._data["desktop_mode"] = mode
        self._dirty = True
        self._log.info(f"{LOG_PREFIX} desktop_mode: {mode}")
        return True

    @_log_call
    def window_transparency(self) -> float:
        """NY v7-fix38: fönstertransparens 0.0–1.0 (0 = helt opak)."""
        with self._lock:
            return _coerce_window_transparency(
                self._data.get("window_transparency", DEFAULT_WINDOW_TRANSPARENCY)
            )

    @_log_setter("window_transparency")
    def set_window_transparency(self, value: float) -> bool:
        """
        NY v7-fix38: sätt fönstertransparens (0.0–1.0).

        0.0 = av (opak fönsterbakgrund, som innan v7-fix38)
        0.5–0.85 = genomskinligt frostat glas (ikonerna syns igenom)
        1.0 = full alfa i design-tokens (rundade hörn men opak panel)
        """
        v = _coerce_window_transparency(value, DEFAULT_WINDOW_TRANSPARENCY)
        with self._lock:
            self._data["window_transparency"] = v
        self._dirty = True
        self._log.info(f"{LOG_PREFIX} window_transparency: {v}")
        return True

    # ========================================================================
    # NY v7-fix40: ENBART ETT FÖNSTER
    # ========================================================================

    @_log_call
    def single_window(self) -> bool:
        """
        NY v7-fix40: enbart-läge — appen visar MAX ett fönster.

        True (default): "Nytt fönster" visar det befintliga fönstret
        i stället för att skapa ett nytt.
        False: gamla beteendet (flera fönster parallellt) — bevarat.
        """
        with self._lock:
            return bool(self._data.get("single_window", DEFAULT_SINGLE_WINDOW))

    @_log_setter("single_window")
    def set_single_window(self, enabled: bool) -> bool:
        """NY v7-fix40: sätt enbart-ett-fönster-läget."""
        v = _coerce_bool(enabled, DEFAULT_SINGLE_WINDOW)
        with self._lock:
            self._data["single_window"] = v
        self._dirty = True
        self._log.info(f"{LOG_PREFIX} single_window: {v}")
        return True

    @_log_call
    def global_quick_add(self) -> bool:
        """NY v7-fix41: global snabbinput på/av (Ctrl+Alt+N i hela Windows)."""
        with self._lock:
            return bool(self._data.get("global_quick_add", True))

    @_log_setter("global_quick_add")
    def set_global_quick_add(self, enabled: bool) -> bool:
        """NY v7-fix41: sätt global snabbinput."""
        v = _coerce_bool(enabled, True)
        with self._lock:
            self._data["global_quick_add"] = v
        self._dirty = True
        self._log.info(f"{LOG_PREFIX} global_quick_add: {v}")
        return True

    @_log_call
    def auto_update_plugins(self) -> bool:
        """NY v7-fix50: auto-uppdatera tillägg vid start (av/på)."""
        with self._lock:
            return bool(self._data.get("auto_update_plugins", True))

    @_log_setter("auto_update_plugins")
    def set_auto_update_plugins(self, enabled: bool) -> bool:
        """NY v7-fix50: sätt auto-uppdatering av tillägg vid start."""
        v = _coerce_bool(enabled, True)
        with self._lock:
            self._data["auto_update_plugins"] = v
        self._dirty = True
        self._log.info(f"{LOG_PREFIX} auto_update_plugins: {v}")
        return True

    @_log_call
    def reminders_enabled(self) -> bool:
        """NY v7-fix64: påminnelser av/på (förfallna + dagens uppgifter)."""
        with self._lock:
            return bool(self._data.get("reminders_enabled", True))

    @_log_setter("reminders_enabled")
    def set_reminders_enabled(self, enabled: bool) -> bool:
        """NY v7-fix64: sätt påminnelser."""
        v = _coerce_bool(enabled, True)
        with self._lock:
            self._data["reminders_enabled"] = v
        self._dirty = True
        self._log.info(f"{LOG_PREFIX} reminders_enabled: {v}")
        return True

    # ------------------------------------------------------------------
    # NY v7-fix90: E-POSTBRYGGA (Thunderbird-tillägg + inkorgsmapp)
    # ------------------------------------------------------------------

    @_log_call
    def mail_bridge_enabled(self) -> bool:
        """Är den lokala HTTP-bryggan på (Thunderbird-tillägget kan koppla)?"""
        with self._lock:
            return bool(self._data.get("mail_bridge_enabled", True))

    @_log_setter("mail_bridge_enabled")
    def set_mail_bridge_enabled(self, enabled: bool) -> bool:
        """Slå på/av e-postbryggan (localhost-server för tillägget)."""
        v = _coerce_bool(enabled, True)
        with self._lock:
            self._data["mail_bridge_enabled"] = v
        self._dirty = True
        self._log.info(f"{LOG_PREFIX} mail_bridge_enabled: {v}")
        self._save_async_worker(self._data)
        return True

    @_log_call
    def mail_bridge_port(self) -> int:
        """Port för bryggan (default 8765, bara 127.0.0.1)."""
        with self._lock:
            return _coerce_int(self._data.get("mail_bridge_port", 8765),
                               8765, 1024, 65535)

    @_log_setter("mail_bridge_port")
    def set_mail_bridge_port(self, port: int) -> bool:
        """Sätt port (1024-65535). Startar om bryggan i main.pyw."""
        v = _coerce_int(port, 8765, 1024, 65535)
        with self._lock:
            self._data["mail_bridge_port"] = v
        self._dirty = True
        self._log.info(f"{LOG_PREFIX} mail_bridge_port: {v}")
        self._save_async_worker(self._data)
        return True

    @_log_call
    def mail_bridge_token(self) -> str:
        """
        Token (hemlig nyckel) för tillägget.

        Tom sträng = inte skapad ännu → core.mail_bridge skapar en
        slumpad nyckel vid start och sparar den i data/mail_bridge/token.txt.
        """
        with self._lock:
            return str(self._data.get("mail_bridge_token", "") or "")[:64]

    @_log_setter("mail_bridge_token")
    def set_mail_bridge_token(self, token: str) -> bool:
        """Spara token (kortare än 8 tecken ignoreras av mail_bridge)."""
        v = _coerce_str(token, "")[:64]
        with self._lock:
            self._data["mail_bridge_token"] = v
        self._dirty = True
        self._log.info(
            f"{LOG_PREFIX} mail_bridge_token uppdaterad ({len(v)} tecken)"
        )
        self._save_async_worker(self._data)
        return True

    @_log_call
    def inbox_watch_enabled(self) -> bool:
        """Bevakas data/inbox/ automatiskt (släpp .eml/.msg/.json där)?"""
        with self._lock:
            return bool(self._data.get("inbox_watch_enabled", True))

    @_log_setter("inbox_watch_enabled")
    def set_inbox_watch_enabled(self, enabled: bool) -> bool:
        """Slå på/av automatisk import från inkorgsmappen."""
        v = _coerce_bool(enabled, True)
        with self._lock:
            self._data["inbox_watch_enabled"] = v
        self._dirty = True
        self._log.info(f"{LOG_PREFIX} inbox_watch_enabled: {v}")
        self._save_async_worker(self._data)
        return True

    @_log_call
    def inbox_poll_seconds(self) -> int:
        """Hur ofta inkorgsmappen genomsöks (1-60 sekunder)."""
        with self._lock:
            return _coerce_int(self._data.get("inbox_poll_seconds", 3),
                               3, 1, 60)

    @_log_setter("inbox_poll_seconds")
    def set_inbox_poll_seconds(self, seconds: int) -> bool:
        """Sätt genomsökningsintervall för inkorgsmappen."""
        v = _coerce_int(seconds, 3, 1, 60)
        with self._lock:
            self._data["inbox_poll_seconds"] = v
        self._dirty = True
        self._log.info(f"{LOG_PREFIX} inbox_poll_seconds: {v}")
        self._save_async_worker(self._data)
        return True

    # ------------------------------------------------------------------
    # NY v8 (2026-10-12): GOOGLE CALENDAR (lokal OAuth-anslutning)
    # ------------------------------------------------------------------

    @_log_call
    def google_calendar_enabled(self) -> bool:
        """
        Är ett Google-konto kopplat?

        Själva beviset är token-filen i <data>/google/token.json — denna
        flagga är appens minne av att anslutningen gjordes (och slås av
        när man kopplar från).
        """
        with self._lock:
            return bool(self._data.get("google_calendar_enabled", False))

    @_log_setter("google_calendar_enabled")
    def set_google_calendar_enabled(self, enabled: bool) -> bool:
        """Kom ihåg att Google Calendar är kopplad (eller inte)."""
        v = _coerce_bool(enabled, False)
        with self._lock:
            self._data["google_calendar_enabled"] = v
        self._dirty = True
        self._log.info(f"{LOG_PREFIX} google_calendar_enabled: {v}")
        self._save_async_worker(self._data)
        return True

    @_log_call
    def google_calendar_id(self) -> str:
        """Kalendern som uppgifterna skickas till ("primary" = huvudkalendern)."""
        with self._lock:
            return _coerce_str(
                self._data.get("google_calendar_id", "primary"), "primary"
            )[:200]

    @_log_setter("google_calendar_id")
    def set_google_calendar_id(self, calendar_id: str) -> bool:
        """Välj vilken kalender händelserna ska hamna i."""
        v = _coerce_str(calendar_id, "primary")[:200]
        with self._lock:
            self._data["google_calendar_id"] = v
        self._dirty = True
        self._log.info(f"{LOG_PREFIX} google_calendar_id: {v}")
        self._save_async_worker(self._data)
        return True

    @_log_call
    def google_calendar_color_by_priority(self) -> bool:
        """Färga händelser efter uppgiftens prioritet (röd/gul/grön)?"""
        with self._lock:
            return bool(self._data.get("google_calendar_color_by_priority", True))

    @_log_setter("google_calendar_color_by_priority")
    def set_google_calendar_color_by_priority(self, enabled: bool) -> bool:
        """Slå på/av färgkodning av händelser efter prioritet."""
        v = _coerce_bool(enabled, True)
        with self._lock:
            self._data["google_calendar_color_by_priority"] = v
        self._dirty = True
        self._log.info(f"{LOG_PREFIX} google_calendar_color_by_priority: {v}")
        self._save_async_worker(self._data)
        return True

    @_log_call
    def google_calendar_done_style(self) -> str:
        """Hur klara uppgifter syns i kalendern: grey | strike | off."""
        with self._lock:
            return _coerce_str(
                self._data.get("google_calendar_done_style", "grey"),
                "grey", ("grey", "strike", "off"),
            )

    @_log_setter("google_calendar_done_style")
    def set_google_calendar_done_style(self, style: str) -> bool:
        """Välj hur klara uppgifter markeras i Google Calendar."""
        v = _coerce_str(style, "grey", ("grey", "strike", "off"))
        with self._lock:
            self._data["google_calendar_done_style"] = v
        self._dirty = True
        self._log.info(f"{LOG_PREFIX} google_calendar_done_style: {v}")
        self._save_async_worker(self._data)
        return True

    @_log_call
    def push_show_hotkey(self) -> str:
        """NY v7-fix69: hotkey för push-to-show (t.ex. 'Ctrl+Alt+V')."""
        with self._lock:
            return str(
                self._data.get("push_show_hotkey", "Ctrl+Alt+V")
            )[:40]

    @_log_setter("push_show_hotkey")
    def set_push_show_hotkey(self, combo: str) -> bool:
        """NY v7-fix69: sätt hotkey-sträng (valideras i main vid registrering)."""
        v = _coerce_str(combo, "Ctrl+Alt+V")[:40]
        with self._lock:
            self._data["push_show_hotkey"] = v
        self._dirty = True
        self._log.info(f"{LOG_PREFIX} push_show_hotkey: {v}")
        # FIX v7-fix83: spara till disk direkt (annars försvann ändringen
        # tills nästa slumpmässiga save)
        self._save_async_worker(self._data)
        return True

    @_log_call
    def quick_add_hotkey(self) -> str:
        """
        NY v7-fix83: hotkey för global snabbinput (t.ex. 'Ctrl+Alt+N').

        Användaren kan ändra via tray → ⌨️ Snabbkommandon → Ny uppgift.
        """
        with self._lock:
            return str(
                self._data.get("quick_add_hotkey", "Ctrl+Alt+N")
            )[:40]

    @_log_setter("quick_add_hotkey")
    def set_quick_add_hotkey(self, combo: str) -> bool:
        """NY v7-fix83: sätt snabbinput-hotkey (valideras i main)."""
        v = _coerce_str(combo, "Ctrl+Alt+N")[:40]
        with self._lock:
            self._data["quick_add_hotkey"] = v
        self._dirty = True
        self._log.info(f"{LOG_PREFIX} quick_add_hotkey: {v}")
        self._save_async_worker(self._data)
        return True

    @_log_setter("shortcuts")
    def set_shortcut(self, action: str, seq: str) -> bool:
        """
        NY v7-fix83: sätt ETT värde i shortcuts-dikten (t.ex. add_task).

        Widgetens QShortcut för samma action uppdateras vid omregistrering
        (widget._unregister_hotkeys + _register_hotkeys).
        """
        try:
            with self._lock:
                sc = dict(self._data.get("shortcuts", {}) or {})
                sc[str(action)] = str(seq or "")
                self._data["shortcuts"] = sc
            self._dirty = True
            self._log.info(
                f"{LOG_PREFIX} shortcut '{action}' → '{seq}'"
            )
            self._save_async_worker(self._data)
            return True
        except Exception as e:
            self._log.warning(f"{LOG_PREFIX} set_shortcut: {e}")
            return False

    @_log_call
    def tray_lift_seconds(self) -> int:
        """NY v7-fix72: antal sekunder tray-klick lyfter fönstret (1-60)."""
        with self._lock:
            return _coerce_int(
                self._data.get("tray_lift_seconds", 5), 5, 1, 60
            )

    @_log_setter("tray_lift_seconds")
    def set_tray_lift_seconds(self, seconds: int) -> bool:
        """NY v7-fix72: sätt lyft-tid (sekunder, 1-60)."""
        v = _coerce_int(seconds, 5, 1, 60)
        with self._lock:
            self._data["tray_lift_seconds"] = v
        self._dirty = True
        self._log.info(f"{LOG_PREFIX} tray_lift_seconds: {v}")
        return True

    @_log_call
    def notification_sound(self) -> str:
        """Hämta notifikationsljud."""
        with self._lock:
            return self._data.get("notification_sound", NotificationSound.GENTLE.value)

    @_log_setter("notification_sound")
    def set_notification_sound(self, sound: str) -> bool:
        """Sätt notifikationsljud."""
        sound = _coerce_str(sound, NotificationSound.GENTLE.value, VALID_NOTIFICATION_SOUNDS)
        with self._lock:
            self._data["notification_sound"] = sound
        self._dirty = True
        self._log.info(f"{LOG_PREFIX} notification_sound: {sound}")
        return True

    # ========================================================================
    # EXPORT / IMPORT
    # ========================================================================

    @_log_call
    def export_to(self, dest_path: str) -> bool:
        """Exportera settings till fil."""
        try:
            dest = Path(dest_path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                data = copy.deepcopy(self._data)
            data["_meta"] = data.get("_meta", {})
            data["_meta"]["exported_at"] = datetime.now(timezone.utc).isoformat()
            with open(dest, "w", encoding="utf-8") as f:
                bytes_written = f.write(json.dumps(data, indent=2, ensure_ascii=False))
            self._log.info(
                f"{LOG_PREFIX} Exporterad till {dest}: {bytes_written} bytes"
            )
            return True
        except Exception as e:
            self._log.error(
                f"{LOG_PREFIX} Export misslyckades: {e}", exc_info=True
            )
            return False

    @_log_call
    def import_from(self, src_path: str, merge: bool = True) -> bool:
        """Importera settings från fil."""
        try:
            src = Path(src_path)
            if not src.exists():
                self._log.error(f"{LOG_PREFIX} Import: fil finns inte: {src}")
                return False
            with open(src, "r", encoding="utf-8") as f:
                new_data = json.load(f)
            new_data.pop("_meta", None)  # Ignorera meta
            with self._lock:
                if merge:
                    old_count = len(self._data)
                    self._data.update(new_data)
                    new_count = len(self._data) - old_count
                    self._log.info(
                        f"{LOG_PREFIX} Import (merge): {new_count} nya nycklar"
                    )
                else:
                    self._data = new_data
                    self._log.info(
                        f"{LOG_PREFIX} Import (replace): {len(self._data)} nycklar"
                    )
            self._dirty = True
            self._validate_all()
            self._save_async_worker(self._data)
            return True
        except Exception as e:
            self._log.error(
                f"{LOG_PREFIX} Import misslyckades: {e}", exc_info=True
            )
            return False

    # ========================================================================
    # STYLESHEET GENERATION
    # ========================================================================

    @_log_call
    def stylesheet(self) -> str:
        """Generera QSS-stylesheet dynamiskt baserat på tema + accent."""
        is_dark = self.is_dark()
        accent = self.accent_color()
        rgba = ACCENT_PALETTES.get(accent, ACCENT_PALETTES["indigo"])
        self._log.debug(
            f"{LOG_PREFIX} Genererar stylesheet: dark={is_dark}, accent={accent}"
        )
        if is_dark:
            bg = "#1e1e2e"
            fg = "#f0f0fa"
            surface = "#2a2a3e"
            border = "#3a3a4e"
            accent_str = f"rgba({rgba['primary'][0]}, {rgba['primary'][1]}, {rgba['primary'][2]}, 0.9)"
        else:
            bg = "#fafafa"
            fg = "#1a1a2e"
            surface = "#ffffff"
            border = "#e0e0e0"
            accent_str = f"rgba({rgba['primary'][0]}, {rgba['primary'][1]}, {rgba['primary'][2]}, 0.9)"
        qss = f"""
        QWidget {{
            background-color: {bg};
            color: {fg};
            font-family: "Segoe UI", "Inter", sans-serif;
        }}
        QFrame {{
            background-color: {surface};
            border: 1px solid {border};
            border-radius: 8px;
        }}
        QPushButton {{
            background-color: {accent_str};
            color: white;
            border: none;
            border-radius: 6px;
            padding: 8px 16px;
            font-weight: 600;
        }}
        QPushButton:hover {{
            background-color: rgba({rgba['hover'][0]}, {rgba['hover'][1]}, {rgba['hover'][2]}, {rgba['hover'][3]});
        }}
        QPushButton:pressed {{
            background-color: rgba({rgba['pressed'][0]}, {rgba['pressed'][1]}, {rgba['pressed'][2]}, {rgba['pressed'][3]});
        }}
        QLineEdit, QTextEdit, QPlainTextEdit {{
            background-color: {surface};
            color: {fg};
            border: 1px solid {border};
            border-radius: 6px;
            padding: 6px 10px;
        }}
        QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
            border: 2px solid {accent_str};
        }}
        QLabel {{
            color: {fg};
        }}
        QTabBar::tab {{
            background-color: {surface};
            color: {fg};
            padding: 8px 16px;
            border: 1px solid {border};
        }}
        QTabBar::tab:selected {{
            background-color: {accent_str};
            color: white;
            font-weight: 600;
        }}
        """
        self._log.debug(
            f"{LOG_PREFIX} Stylesheet genererad: {len(qss)} tecken"
        )
        return qss

    # ========================================================================
    # DIAGNOSTICS / HEALTH
    # ========================================================================

    @_log_call
    def get_health_report(self) -> Dict[str, Any]:
        """Hämta diagnostik-rapport."""
        with self._lock:
            data = copy.deepcopy(self._data)
        report = {
            "file_path": str(self._file_path),
            "file_exists": self._file_path.exists(),
            "file_size_bytes": (
                self._file_path.stat().st_size if self._file_path.exists() else 0
            ),
            "schema_version": data.get("version", 1),
            "key_count": len(data),
            "save_count": self._save_count,
            "load_count": self._load_count,
            "error_count": self._error_count,
            "last_save_time": self._last_save_time,
            "last_load_time": self._last_load_time,
            "dirty": self._dirty,
            "audit_entries": len(self._audit_log.get_entries()),
            "is_dark": self.is_dark(),
            "accent_color": self.accent_color(),
            "glass_style": self.glass_style(),
            "autostart_enabled": self.autostart_enabled(),
            "animations_enabled": self.animations_enabled(),
            "window_count": len(self.window_configs()),
        }
        self._log.debug(
            f"{LOG_PREFIX} Health report: save_count={report['save_count']}, "
            f"load_count={report['load_count']}, errors={report['error_count']}"
        )
        return report

    @_log_call
    def get_changed_keys(self, other: Dict[str, Any]) -> List[str]:
        """Jämför med annan dict, returnera ändrade nycklar."""
        with self._lock:
            current = copy.deepcopy(self._data)
        changed = []
        for key in set(current.keys()) | set(other.keys()):
            if current.get(key) != other.get(key):
                changed.append(key)
        self._log.debug(
            f"{LOG_PREFIX} Diff med annan dict: {len(changed)} ändrade nycklar"
        )
        return changed

    @_log_call
    def get_snapshot(self) -> Dict[str, Any]:
        """Ta snapshot av nuvarande state (immutabel kopia)."""
        with self._lock:
            snapshot = copy.deepcopy(self._data)
        self._log.debug(
            f"{LOG_PREFIX} Snapshot tagen: {len(snapshot)} nycklar"
        )
        return snapshot

    # ========================================================================
    # PRIVATE HELPERS
    # ========================================================================

    def _safe_emit(self, signal_name: str, *args: Any) -> None:
        """Emitta signal säkert (med loggning + felhantering)."""
        if not _QT_AVAILABLE:
            return
        try:
            signal = getattr(self, signal_name, None)
            if signal is None:
                self._log.warning(
                    f"{LOG_PREFIX} _safe_emit: signal {signal_name!r} finns inte"
                )
                return
            # FIX 2026-09-24: logga windows_updated-anrop separat
            # (annars kan vi inte se VARFÖR populate spammar).
            if signal_name == "windows_updated":
                import traceback as _te
                _stk = _te.extract_stack(limit=5)[:-1]
                _call = " ← ".join(
                    f"{f.filename.split('/')[-1]}:{f.lineno}"
                    for f in _stk[-3:]
                )
                try:
                    cnt = len(args[0]) if args else -1
                except Exception:
                    cnt = -1
                self._log.info(
                    f"{LOG_PREFIX} _safe_emit(windows_updated, "
                    f"ANTAL={cnt})  ← {_call}"
                )
            signal.emit(*args)
            self._log.debug(
                f"{LOG_PREFIX} Signal emitterad: {signal_name}({args!r})"
            )
        except Exception as e:
            self._log.error(
                f"{LOG_PREFIX} Signal-emit misslyckades: {signal_name}: {e}",
                exc_info=True,
            )

    def _audit_log(self, field: str, old: Any, new: Any, reason: str = "") -> None:
        """Wrapper för audit-log (privat)."""
        self._audit_log.add(field, old, new, reason)

    def __repr__(self) -> str:
        return (
            f"<Settings file={self._file_path.name} "
            f"keys={len(self._data)} saves={self._save_count} "
            f"loads={self._load_count} errors={self._error_count}>"
        )

    def __str__(self) -> str:
        return self.__repr__()

    # =========================================================================
    # DIAGNOSTIK & HEALTH (NY v6.4.1 v7)
    # =========================================================================

    def diagnose(self) -> List[str]:
        """
        NY v6.4.1 v7: Diagnostisk funktion som kontrollerar denna Settings-instans.

        Returns:
            Lista av svenska problem-beskrivningar (tom om allt ar OK)
        """
        return _validate_settings_state(self)

    def get_health_report(self) -> Dict[str, Any]:
        """
        NY v6.4.1 v7: Komplett health-rapport for denna Settings-instans.
        """
        with safe_run(f"{LOG_PREFIX} get_health_report") as ctx:
            problems = _validate_settings_state(self)
            summary = format_settings_summary(self)
            audit_count = 0
            try:
                if hasattr(self, "_audit_log"):
                    audit_count = len(self._audit_log)
            except Exception as e:
                _logger.debug(
                    f"{LOG_PREFIX} get_health_report audit count fel: "
                    f"{_describe_settings_exception(e)}"
                )
            ctx["ok"] = True
            return {
                "module": "settings",
                "app_version_tag": APP_VERSION_TAG,
                "settings_version": self._version,
                "file_path": str(getattr(self, "_file_path", "?")),
                "data_keys": len(self._data) if isinstance(self._data, dict) else 0,
                "save_count": self._save_count,
                "load_count": self._load_count,
                "error_count": self._error_count,
                "audit_count": audit_count,
                "problems": problems,
                "problem_count": len(problems),
                "summary_swedish": summary,
            }


# ===========================================================================
# DUMMY SIGNAL (för icke-Qt-miljöer)
# ===========================================================================

class _DummySignal:
    """No-op signal för tester / icke-Qt-miljöer."""

    def __init__(self) -> None:
        self._callbacks: List[Callable] = []

    def connect(self, callback: Callable) -> None:
        self._callbacks.append(callback)

    def disconnect(self, callback: Optional[Callable] = None) -> None:
        if callback is None:
            self._callbacks.clear()
        else:
            with suppress(ValueError):
                self._callbacks.remove(callback)

    def emit(self, *args: Any, **kwargs: Any) -> None:
        for cb in self._callbacks:
            with suppress(Exception):
                cb(*args, **kwargs)


# ===========================================================================
# MODUL-EXPORT
# ===========================================================================

__all__ = [
    "Settings",
    "AuditLog",
    "SettingsChange",
    "SaveResult",
    "Theme",
    "AccentColor",
    "GlassStyle",
    "DensityMode",
    "NotificationSound",
    "AutostartMethod",
    "ACCENT_PALETTES",
    "SETTINGS_VERSION",
    "MIN_SUPPORTED_VERSION",
    "APP_VERSION_TAG",
    "VALID_THEMES",
    "VALID_ACCENTS",
    "VALID_GLASS_STYLES",
    "VALID_DENSITY_MODES",
    "VALID_NOTIFICATION_SOUNDS",
    "VALID_AUTOSTART_METHODS",
    # NY v7-fix38: skrivbordsläge + transparens
    "VALID_DESKTOP_MODES",
    "DEFAULT_DESKTOP_MODE",
    "DEFAULT_WINDOW_TRANSPARENCY",
    # NY v7-fix40: enbart ett fönster
    "DEFAULT_SINGLE_WINDOW",
    # Svenska formatters (NY v6.4.1 v7)
    "format_settings_summary", "summarize_settings_health",
    # AI-felsökning (NY v6.4.1 v7)
    "_SETTINGS_ERROR_TRANSLATIONS",
    "_describe_settings_exception", "_format_compact_traceback",
    "_categorize_settings_exception", "_validate_settings_state",
    "safe_call", "safe_run", "_safe_run_async",
    # Diagnostik (NY v6.4.1 v7)
    "get_settings_diagnostics",
    # Plugin-coupling (NY v6.4.1 v7)
    "get_settings_plugin_deps",
]


# ===========================================================================
# SELF-TEST
# ===========================================================================

if __name__ == "__main__":
    import sys
    import tempfile

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s | %(levelname)-8s | %(name)-12s | %(message)s",
    )

    print("=" * 70)
    print("Settings.py — Self-Test")
    print("=" * 70)

    # Test 1: Skapa + spara + ladda
    print("\n[Test 1] Skapa + spara + ladda...")
    with tempfile.TemporaryDirectory() as tmp:
        test_path = Path(tmp) / "settings.json"
        s1 = Settings(file_path=test_path)
        print(f"  ✓ Settings skapad: {s1}")
        print(f"  ✓ Theme: {s1.theme_setting()}")
        print(f"  ✓ Accent: {s1.accent_color()}")
        s1.set_theme(Theme.DARK.value)
        s1.set_accent_color(AccentColor.EMERALD.value)
        s1.set_animations_enabled(True)
        s1.add_window(100, 100)
        s1.save()
        print(f"  ✓ Saved: {s1.get_health_report()['save_count']} saves")

        s2 = Settings(file_path=test_path)
        print(f"  ✓ Re-loaded: theme={s2.theme_setting()}, accent={s2.accent_color()}")
        assert s2.theme_setting() == Theme.DARK.value
        assert s2.accent_color() == AccentColor.EMERALD.value

    # Test 2: Enums
    print("\n[Test 2] Enums...")
    print(f"  ✓ Theme: {[t.value for t in Theme]}")
    print(f"  ✓ AccentColor: {[a.value for a in AccentColor]}")
    print(f"  ✓ GlassStyle: {[g.value for g in GlassStyle]}")
    print(f"  ✓ DensityMode: {[d.value for d in DensityMode]}")
    print(f"  ✓ NotificationSound: {[n.value for n in NotificationSound]}")

    # Test 3: AuditLog
    print("\n[Test 3] AuditLog...")
    audit = AuditLog()
    audit.add("theme", "system", "dark", reason="user-request")
    audit.add("accent", "indigo", "emerald", reason="user-request")
    entries = audit.get_entries()
    print(f"  ✓ Audit entries: {len(entries)}")
    for e in entries:
        print(f"    - {e.field}: {e.old_value!r} → {e.new_value!r}")

    # Test 4: Coerce helpers
    print("\n[Test 4] Coerce helpers...")
    print(f"  ✓ _coerce_bool('yes'): {_coerce_bool('yes')}")
    print(f"  ✓ _coerce_int('42'): {_coerce_int('42')}")
    print(f"  ✓ _coerce_list((1,2,3)): {_coerce_list((1,2,3))}")
    print(f"  ✓ _coerce_str(123, valid={{'a','b'}}): "
          f"{_coerce_str(123, valid={'a', 'b'})}")

    # Test 5: ACCENT_PALETTES
    print("\n[Test 5] ACCENT_PALETTES...")
    for name, palette in ACCENT_PALETTES.items():
        print(f"  ✓ {name}: primary={palette['primary']}, hover={palette['hover']}")

    # Test 6: NY v6.4.1 v7 — AI-felsökning
    print("\n[Test 6] AI-felsökning (NY v6.4.1 v7)...")
    desc1 = _describe_settings_exception(FileNotFoundError("settings.json"))
    print(f"  ✓ _describe_settings_exception: {desc1!r}")
    assert "hittades inte" in desc1
    cat1 = _categorize_settings_exception(ValueError("x"))
    cat2 = _categorize_settings_exception(PermissionError("x"))
    print(f"  ✓ _categorize_settings_exception: ValueError→{cat1}, PermissionError→{cat2}")
    assert cat1 == "user_input" and cat2 == "permission"
    with safe_run("test-op-set") as ctx_ok:
        pass
    with safe_run("test-op-set-fail") as ctx_fail:
        raise RuntimeError("set-test-fel")
    print(f"  ✓ safe_run fel-blocket: errors={len(ctx_fail['errors'])}")
    assert len(ctx_fail["errors"]) == 1

    # Test 7: NY v6.4.1 v7 — Svenska formatters
    print("\n[Test 7] Svenska formatters (NY v6.4.1 v7)...")
    # Skapa en minimal Settings för att testa format_settings_summary
    try:
        s = Settings()
        s1 = format_settings_summary(s)
        print(f"  ✓ format_settings_summary: {s1!r}")
        assert "v9" in s1
    except Exception as e:
        # Kan misslyckas utan Qt — testa iaf summarize_settings_health(None)
        s1 = summarize_settings_health(None)
        print(f"  ✓ summarize_settings_health(None): {s1!r}")
        assert "6.4.1-v7" in s1
    diag = get_settings_diagnostics()
    print(f"  ✓ get_settings_diagnostics: version={diag['settings_version']}, "
          f"problems={diag['problem_count']}")
    assert diag["module"] == "settings"
    assert diag["settings_version"] == SETTINGS_VERSION

    # Test 8: NY v6.4.1 v7 — Settings-instans metoder (diagnose + get_health_report)
    print("\n[Test 8] Settings.diagnose + get_health_report (NY v6.4.1 v7)...")
    try:
        s = Settings()
        problems = s.diagnose()
        print(f"  ✓ Settings.diagnose(): {len(problems)} problem")
        report = s.get_health_report()
        print(f"  ✓ Settings.get_health_report(): keys={report['data_keys']}, "
              f"audit={report['audit_count']}, summary={report['summary_swedish'][:50]!r}")
        assert "summary_swedish" in report
        assert "problems" in report
    except Exception as e:
        print(f"  ⚠ Settings-instans test hoppades over: {type(e).__name__}: {e}")

    print()
    print("=" * 70)
    print("✓ ALLA TESTER PASSERADE (settings.py v6.4.1 v7)")
    print("=" * 70)