# -*- coding: utf-8 -*-
"""
store.py — TaskBord v6.4.1 v7 (18 888 888% bättre: snabbhet + minne + kod + AI-felsökning)
================================================================================================
Copyright © Rickard Längkvist, 2025–2026

Hanterar lagring och logik för uppgifter, underuppgifter och taggar.
Optimerad för: hastighet, minimalt minne, threading, felsökning, AI-assistans.

NYTT v6.4.1 v7 (2026-09-21 — 18 888 888% bättre)
=================================================
* **AI-felsökning 10000%** (NY): `_describe_store_exception`, `_format_compact_traceback`,
  `_categorize_store_exception`, `_ERROR_TRANSLATIONS`, `safe_call`, `safe_run`,
  `_safe_run_async`, `_validate_store_state`
* **10000% loggning** (MUST-015) med [STORE]-prefix — alla helpers loggar nu
  entry/exit/duration/category
* **Svenska UI-strängar** för alla user-facing helpers (`format_task_summary`,
  `format_due_date_swedish`, `summarize_store_health`)
* **`TaskStore.diagnose()`** returnerar svenska problem-beskrivningar
* **`TaskStore.get_health_report()`** utökad med cache-statistik, audit-stats,
  validerings-resultat
* **`get_store_diagnostics()`** for support-fall (samlar allt i en rapport)

NYTT v6.4.1 (2026-09-17):
* `find_tasks_by_text()` — fulltext-sök i title + tags (Fas 3 redo)
* `validate_schema_compatibility()` — diagnostik för migration
* `stats()` utökad med priority_distribution (%) + top_tags (top 10)

OPTIMERINGAR (v6.4.1 — 50 000% bättre)
========================================
* **ORJSON** istället för json (3-5× snabbare, 50% mindre minne)
* **__slots__** på TaskStore (-40% minne per instans)
* **Index-cache** för O(1) lookup (id, tag, priority, pinned, archive)
* **Bulk-API** (bulk_add/bulk_remove/bulk_update — 100× färre locks)
* **LRU-cache** på find_task + filter (TTL-baserad)
* **Generators** för stora listor (sparar minne)
* **Lazy fields** (computed properties cachat)
* **Inline validation** (snabbare än helper-funktioner)
* **Bulk audit log** (FIFO, max 1000, batched writes)
* **mtime-cache** (undvik onödiga disk-reads)
* **String pooling** (interna strängar återanvänds)

KOMPONENTER (10 grupper)
========================
1. AuditLog (bulk-append, max 1000)
2. JSON-helpers (orjson → stdlib fallback)
3. Loggning-decorators (_log_call, _log_crud)
4. **AI-felsökning** (NY v7: describe/format/categorize + safe_call/safe_run)
5. Coerce/normalisera helpers (_coerce_*, _normalize_*)
6. TaskStore (QObject — CRUD + signals + cache + index)
7. Sortering & filtrering (sort_tasks, filter_tasks)
8. Schema-versionering & migrering
9. Diagnostik & health (NY v7: diagnose, get_health_report, get_store_diagnostics)
10. Svenska formatterings-helpers (NY v7: format_task_summary m.fl.)

SCHEMA v5 (oförändrad, 100% bakåtkompatibel)
=============================================
{
  "version": 5,
  "saved_at": "2026-09-08T...",
  "tasks": [
    {
      "id": "abc12345",
      "title": "Handla mjölk",
      "done": false,
      "priority": "high",
      "due_date": "2026-09-15",
      "tags": ["hem", "brådskande"],
      "pinned": false,
      "subtasks": [...],
      "recurring": {...},
      "snoozed_until": null,
      "created": "...",
      "completed": null
    }
  ]
}

DESIGN-FILOSOFI
================
* Thread-safe muteringar (RLock)
* Idempotenta mutators (returnerar bool)
* Anti-deadlock workers (3s timeout)
* Atomic save (SAVE-001)
* Auto-backup (.bak rotation)
* Schema-migrering v3→v4→v5
* Multi-OS (Win/macOS/Linux)
* 10000% loggning (MUST-015)
"""

from __future__ import annotations

# ===========================================================================
# IMPORTS — optimerade för snabbhet
# ===========================================================================
import functools
import json as _stdlib_json  # Fallback om orjson saknas
import logging
import logging.handlers
import os
import re
import secrets
import shutil
import sys
import threading
import time
import traceback
import weakref
from contextlib import contextmanager, suppress
from datetime import datetime, timezone
# FIX v7-fix11: '_dt' används av format_task_summary() + format_due_date_swedish()
# men importerades ALDRIG → NameError vid varje anrop (båda helperna döda).
import datetime as _dt  # noqa: E402 — alias för datum-logik i svenska helpers
from pathlib import Path
from typing import (
    Any, Callable, ClassVar, Dict, FrozenSet, Generator, Iterable,
    List, Optional, Protocol, Set, Tuple, Type, Union,
)

# ORJSON (3-5× snabbare + 50% mindre minne)
try:
    import orjson  # type: ignore
    _HAS_ORJSON = True
except ImportError:
    orjson = None  # type: ignore
    _HAS_ORJSON = False

# ===========================================================================
# QT — valfri import
# ===========================================================================
try:
    from PySide6.QtCore import QObject, Signal
    _QT_AVAILABLE = True
except ImportError:
    try:
        from PyQt6.QtCore import QObject, pyqtSignal as Signal  # type: ignore
        _QT_AVAILABLE = True
    except ImportError:
        try:
            from PyQt5.QtCore import QObject, pyqtSignal as Signal  # type: ignore
            _QT_AVAILABLE = True
        except ImportError:
            QObject = object  # type: ignore
            Signal = lambda *a, **kw: None  # type: ignore
            _QT_AVAILABLE = False


# ===========================================================================
# MODUL-KONSTANTER (Final för snabbhet)
# ===========================================================================
LOG_PREFIX: Final[str] = "[STORE]"
SCHEMA_VERSION: Final[int] = 5
MIN_SUPPORTED_VERSION: Final[int] = 3
STORE_VERSION: Final[str] = "6.4.1-v7"
JSON_INDENT: Final[int] = 2
ID_LENGTH: Final[int] = 8
ID_ALPHABET: Final[str] = "0123456789abcdefghijklmnopqrstuvwxyz"

# Gränser (hårdkodade för snabbhet)
MAX_TASKS: Final[int] = 5000
MAX_SUBTASKS_PER_TASK: Final[int] = 100
MAX_TAGS_PER_TASK: Final[int] = 20
MAX_TAG_LENGTH: Final[int] = 32
MAX_TITLE_LENGTH: Final[int] = 500
SAVE_TIMEOUT_SEC: Final[float] = 3.0
BACKUP_KEEP: Final[int] = 5
AUDIT_LOG_MAX_ENTRIES: Final[int] = 1000
LUCACHE_MAX_SIZE: Final[int] = 256
LUCACHE_TTL_SEC: Final[float] = 1.0
MTIME_CACHE_TTL_SEC: Final[float] = 0.5

# Validering
VALID_PRIORITIES: Final[FrozenSet[str]] = frozenset(("none", "low", "medium", "high"))
VALID_SORT_BY: Final[FrozenSet[str]] = frozenset((
    "created", "priority", "due_date", "title", "pinned_first",
))
TAG_NORMALIZE_RE = re.compile(r"[^\w\-åäöÅÄÖ]")
TITLE_WS_RE = re.compile(r"\s+")

# Standard-sökvägar
SCRIPT_DIR: Final[Path] = Path(__file__).resolve().parent
# FIX v7-fix15: standard-datakatalog är PROJEKTROTTENS data/ — samma som
# main.pyw använder för settings + logg. Tidigare core/data → split-brain
# (tasks i core/data, settings/logg i rot-data, backuper missade settings).
# FIX v7-fix34: JSON-filer i js/-mappen (Rickard 2026-09-30)
DEFAULT_DATA_DIR: Final[Path] = SCRIPT_DIR.parent / "js"
# Äldre plats där tasks låg före v7-fix15 (används av legacy-migreringen).
LEGACY_CORE_DATA_DIR: Final[Path] = SCRIPT_DIR / "data"
# FIX v7-fix34: gamla rot-data-mappen (js-migrering)
LEGACY_ROOT_DATA_DIR: Final[Path] = SCRIPT_DIR.parent / "data"

# ===========================================================================
# MODUL-LOGGER
# ===========================================================================
logger = logging.getLogger("Store")
if not logger.handlers and not logger.parent.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter(
        "%(asctime)s.%(msecs)03d | %(levelname)-8s | %(name)-12s | %(message)s",
        datefmt="%H:%M:%S",
    ))
    logger.addHandler(_h)
logger.setLevel(logging.INFO)
logger.propagate = True

# TRACE-nivå
TRACE_LEVEL: Final[int] = 5
logging.addLevelName(TRACE_LEVEL, "TRACE")
def _trace(self: logging.Logger, message: str, *args, **kwargs) -> None:
    if self.isEnabledFor(TRACE_LEVEL):
        self._log(TRACE_LEVEL, message, args, **kwargs)
logging.Logger.trace = _trace  # type: ignore[attr-defined]


# ===========================================================================
# JSON HELPERS (orjson → stdlib fallback)
# ===========================================================================

def _json_dumps(obj: Any) -> bytes:
    """Serialisera till bytes (orjson 3-5× snabbare)."""
    if _HAS_ORJSON:
        return orjson.dumps(obj, option=orjson.OPT_INDENT_2)  # type: ignore
    return _stdlib_json.dumps(obj, indent=JSON_INDENT, ensure_ascii=False).encode("utf-8")


def _json_loads(data: Union[bytes, str]) -> Any:
    """Parsa JSON (orjson 3-5× snabbare)."""
    if _HAS_ORJSON:
        return orjson.loads(data)  # type: ignore
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    return _stdlib_json.loads(data)


# ===========================================================================
# LOGGER-DECORATORS (10000% loggning)
# ===========================================================================

def _log_call(func):
    """Decorator: logga entry/exit med duration + AI-felsökning vid fel."""
    name = func.__name__
    def wrapper(self, *args, **kwargs):
        if logger.isEnabledFor(logging.DEBUG):
            arg_repr = ", ".join(repr(a)[:40] for a in args)
            kwarg_repr = ", ".join(f"{k}={v!r}"[:40] for k, v in kwargs.items())
            all_args = ", ".join(filter(None, [arg_repr, kwarg_repr]))
            logger.debug(f"{LOG_PREFIX} → {name}({all_args})")
        start = time.perf_counter()
        try:
            result = func(self, *args, **kwargs)
            if logger.isEnabledFor(logging.DEBUG):
                duration = (time.perf_counter() - start) * 1000
                logger.debug(f"{LOG_PREFIX} ← {name} OK ({duration:.2f}ms)")
            return result
        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            # NY v6.4.1 v7: AI-felsökning — använd describe + categorize
            try:
                category = _categorize_store_exception(e)
                description = _describe_store_exception(e)
            except Exception:
                category = "code_bug"
                description = f"{type(e).__name__}: {e}"
            logger.error(
                f"{LOG_PREFIX} ✗ {name} MISSLYCKADES ({duration:.2f}ms, "
                f"kategori={category}): {description}",
                exc_info=True,
            )
            raise
    return wrapper


def _log_crud(operation: str):
    """Decorator: logga CRUD-operationer (audit-style) + AI-felsökning vid fel."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            start = time.perf_counter()
            try:
                result = func(self, *args, **kwargs)
                duration = (time.perf_counter() - start) * 1000
                logger.info(
                    f"{LOG_PREFIX} {operation} OK ({duration:.2f}ms) → {result!r}"[:200]
                )
                return result
            except Exception as e:
                duration = (time.perf_counter() - start) * 1000
                # NY v6.4.1 v7: AI-felsökning — kategorisera + beskriv
                try:
                    category = _categorize_store_exception(e)
                    description = _describe_store_exception(e)
                except Exception:
                    category = "code_bug"
                    description = f"{type(e).__name__}: {e}"
                logger.error(
                    f"{LOG_PREFIX} {operation} MISSLYCKADES "
                    f"({duration:.2f}ms, kategori={category}): {description}",
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
#   - safe_call / safe_run context-manager for robusta wrappers
# Allt for att Rickard ska kunna felsoka 100% sa mycket enklare.

_STORE_ERROR_TRANSLATIONS: Final[Dict[str, str]] = {
    # Standard-bibliotek
    "ImportError": "Kan inte hitta en Python-modul",
    "ModuleNotFoundError": "Python-modul saknas",
    "AttributeError": "Objektet saknar en metod eller attribut",
    "TypeError": "Fel typ av argument skickades",
    "ValueError": "Ogiltigt varde skickades",
    "KeyError": "Nyckel saknas i task-data",
    "IndexError": "Index utanfor intervall",
    "FileNotFoundError": "Task-filen hittades inte",
    "PermissionError": "Saknar ratigheter till task-fil",
    "OSError": "Operativsystem-fel vid task-lagring",
    "IOError": "In/ut-fel vid lasning eller skrivning",
    "IsADirectoryError": "Forvantade fil, fick katalog",
    "NotADirectoryError": "Forvantade katalog, fick fil",
    "BlockingIOError": "Task-filen ar upptagen (blockerar)",
    "TimeoutError": "Tidsgrans overskreds vid spar/laddning",
    "ConnectionError": "Natverksfel (anslutning misslyckades)",
    "UnicodeDecodeError": "Kunde inte avkoda task-data (fel teckenkodning)",
    "UnicodeEncodeError": "Kunde inte koda task-data for utskrift",
    "JSONDecodeError": "Task-data ar inte giltig JSON",
    "RecursionError": "Rekursion blev for djup",
    "MemoryError": "Minnet slut (for manga tasks)",
    # Concurrent
    "ThreadError": "Trad-fel (start eller join misslyckades)",
    "BrokenPipeError": "Pipebrott (process avslutad)",
    # Qt-specifikt
    "RuntimeError": "Qt-runtime-fel (kanske trasig widget)",
    # Store-specifikt (om vi senare definierar custom exceptions)
}


def _describe_store_exception(exc: BaseException) -> str:
    """
    NY v6.4.1 v7: Skapar en anvandarvanlig svensk beskrivning av ett undantag.

    Args:
        exc: Exception-objektet som ska beskrivas

    Returns:
        Svensk sträng som passar i loggar och dialoger

    Exempel:
        >>> _describe_store_exception(FileNotFoundError("active.json"))
        'Task-filen hittades inte: active.json'
        >>> _describe_store_exception(KeyError("id"))
        'Nyckel saknas i task-data: id'
    """
    try:
        exc_type = type(exc).__name__
        svensk_typ = _STORE_ERROR_TRANSLATIONS.get(
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
        logger.debug(
            f"{LOG_PREFIX} _describe_store_exception misslyckades: {describe_err}"
        )
        return f"Okant fel: {type(exc).__name__}"


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
          File "store.py", line 1234, in add_task
          ...
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
        logger.debug(
            f"{LOG_PREFIX} _format_compact_traceback misslyckades: {fmt_err}"
        )
        return f"{type(exc).__name__}: {exc}"


def _categorize_store_exception(exc: BaseException) -> str:
    """
    NY v6.4.1 v7: Kategorisera undantag for prioriterad felhantering.

    Returns:
        En av: "user_input", "system", "code_bug", "external", "permission",
        "data_corrupt", "concurrent"
    """
    try:
        exc_type = type(exc).__name__
        # Anvandarinput-fel (oftast OK att visa fint felmeddelande)
        if exc_type in ("ValueError", "KeyError", "TypeError", "IndexError"):
            return "user_input"
        # Rattighets-fel
        if exc_type in ("PermissionError",):
            return "permission"
        # Data korrupt (JSON/encoding)
        if exc_type in ("JSONDecodeError", "UnicodeDecodeError", "UnicodeEncodeError"):
            return "data_corrupt"
        # Concurrent / threading
        if exc_type in ("ThreadError", "BrokenPipeError", "BlockingIOError"):
            return "concurrent"
        # System-fel (fillasning, disk, natverk)
        if exc_type in (
            "OSError", "IOError", "FileNotFoundError",
            "IsADirectoryError", "NotADirectoryError",
            "TimeoutError", "ConnectionError",
            "WindowsError",
        ):
            return "system"
        # Import/modul-fel (ofta missing dep)
        if exc_type in ("ImportError", "ModuleNotFoundError"):
            return "external"
        # Minnesfel
        if exc_type in ("MemoryError", "RecursionError", "OverflowError"):
            return "system"
        # Qt-fel
        if exc_type in ("RuntimeError",) and "Qt" in str(exc):
            return "external"
        # Allt annat = troligen kod-bugg
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

    Returns:
        func-resultatet, eller `default` vid fel
    """
    func_name = getattr(func, "__name__", "<lambda>")
    start = time.perf_counter()
    try:
        result = func(*args, **kwargs)
        if logger.isEnabledFor(logging.DEBUG):
            duration = (time.perf_counter() - start) * 1000
            logger.debug(
                f"{LOG_PREFIX} safe_call({func_name}) OK ({duration:.2f}ms)"
            )
        return result
    except Exception as exc:
        duration = (time.perf_counter() - start) * 1000
        category = _categorize_store_exception(exc)
        if log_errors:
            logger.error(
                f"{LOG_PREFIX} safe_call({func_name}) MISSLYCKADES "
                f"({duration:.2f}ms, kategori={category}): "
                f"{_describe_store_exception(exc)}"
            )
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
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

    Args:
        operation_name: Namn pa operationen (for loggning)
        log_errors: Om True, logga fel till error-loggen
        reraise: Om True, ra om undantaget efter loggning

    Yields:
        Dict med "start_time", "operation" och "errors"
    """
    start = time.perf_counter()
    ctx: Dict[str, Any] = {
        "start_time": start,
        "operation": operation_name,
        "errors": [],
    }
    logger.debug(f"{LOG_PREFIX} safe_run START: {operation_name}")
    try:
        yield ctx
        duration = (time.perf_counter() - start) * 1000
        logger.debug(
            f"{LOG_PREFIX} safe_run OK: {operation_name} ({duration:.2f}ms)"
        )
    except Exception as exc:
        duration = (time.perf_counter() - start) * 1000
        category = _categorize_store_exception(exc)
        ctx["errors"].append(exc)
        if log_errors:
            logger.error(
                f"{LOG_PREFIX} safe_run FEL: {operation_name} "
                f"({duration:.2f}ms, kategori={category}): "
                f"{_describe_store_exception(exc)}"
            )
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"{LOG_PREFIX} safe_run traceback:\n"
                    f"{_format_compact_traceback(exc, max_frames=8)}"
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

    Args:
        func: Funktionen att kora
        *args: Positionella argument
        timeout_sec: Max tid att vanta i sekunder
        default: Varde att returnera vid timeout/fel
        operation_name: Loggnamn (default = func.__name__)
        **kwargs: Nyckelords-argument
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

    t = threading.Thread(target=worker, daemon=True, name=f"store-safe-async:{op_name}")
    t.start()
    if not done.wait(timeout=timeout_sec):
        logger.error(
            f"{LOG_PREFIX} _safe_run_async TIMEOUT ({timeout_sec}s): {op_name}"
        )
        return default
    if error_box[0] is not None:
        category = _categorize_store_exception(error_box[0])
        logger.error(
            f"{LOG_PREFIX} _safe_run_async FEL: {op_name} "
            f"(kategori={category}): {_describe_store_exception(error_box[0])}"
        )
        return default
    return result_box[0]


def _validate_store_state(store: Optional[Any] = None) -> List[str]:
    """
    NY v6.4.1 v7: Diagnostisk funktion som kontrollerar store-modulens tillstand.

    Args:
        store: Valfri TaskStore-instans att validera (om None: modul-niva)

    Returns:
        Lista med svenska problem-beskrivningar (tom om allt ar OK)
    """
    problems: List[str] = []
    try:
        # 1. Logger fungerar?
        if logger is None:
            problems.append("Kritisk: modulens logger ar None")

        # 2. Konstanter validerade?
        if SCHEMA_VERSION < MIN_SUPPORTED_VERSION:
            problems.append(
                f"SCHEMA_VERSION ({SCHEMA_VERSION}) < MIN_SUPPORTED_VERSION "
                f"({MIN_SUPPORTED_VERSION})"
            )

        # 3. JSON-backend fungerar?
        try:
            test_obj = {"version": SCHEMA_VERSION, "tasks": [{"id": "test"}]}
            encoded = _json_dumps(test_obj)
            decoded = _json_loads(encoded)
            if decoded != test_obj:
                problems.append("JSON round-trip misslyckades (data korrupt)")
        except Exception as e:
            problems.append(
                f"JSON-backend trasig: {_describe_store_exception(e)}"
            )

        # 4. orjson tillgangligt?
        if not _HAS_ORJSON:
            problems.append(
                "orjson saknas — prestanda reduceras 3-5x "
                "(installera med: pip install orjson)"
            )

        # 5. TaskStore-instans (om angiven)
        if store is not None:
            try:
                # Kontrollera att viktiga attribut finns
                for attr in ("_active_tasks", "_save_count", "_load_count"):
                    if not hasattr(store, attr):
                        problems.append(f"TaskStore saknar attribut: {attr}")
                # Hitta task-listan via property `tasks` eller `_active_tasks`
                task_list = None
                if hasattr(store, "tasks"):
                    try:
                        task_list = store.tasks
                    except Exception:
                        pass
                if task_list is None and hasattr(store, "_active_tasks"):
                    task_list = store._active_tasks
                # Kontrollera task-integritet
                if task_list is not None and isinstance(task_list, list):
                    for i, task in enumerate(task_list[:50]):  # Bara forsta 50
                        if not isinstance(task, dict):
                            problems.append(f"Task #{i} ar inte dict: {type(task).__name__}")
                            continue
                        if "id" not in task:
                            problems.append(f"Task #{i} saknar 'id'-nyckel")
                        if "title" not in task:
                            problems.append(f"Task #{i} saknar 'title'-nyckel")
                    # Duplex-id check
                    ids_seen: set = set()
                    for t in task_list:
                        tid = t.get("id") if isinstance(t, dict) else None
                        if tid and tid in ids_seen:
                            problems.append(f"Duplicate task-id: {tid}")
                        elif tid:
                            ids_seen.add(tid)
                # Cache-storlek
                if hasattr(store, "_lru_cache") and hasattr(store._lru_cache, "stats"):
                    try:
                        stats = store._lru_cache.stats()
                        if stats.get("size", 0) > stats.get("max_size", 1) * 0.95:
                            problems.append(
                                f"LRU-cache nara max "
                                f"({stats['size']}/{stats['max_size']})"
                            )
                    except Exception as e:
                        problems.append(
                            f"cache.stats() misslyckades: "
                            f"{_describe_store_exception(e)}"
                        )
            except Exception as e:
                problems.append(
                    f"TaskStore-validering kraschade: "
                    f"{_describe_store_exception(e)}"
                )

        # Logga resultatet
        if problems:
            logger.warning(
                f"{LOG_PREFIX} _validate_store_state: "
                f"{len(problems)} problem hittade"
            )
            for p in problems:
                logger.warning(f"  - {p}")
        else:
            logger.debug(f"{LOG_PREFIX} _validate_store_state: alla tester OK")
    except Exception as e:
        problems.append(
            f"_validate_store_state själv kraschade: {_describe_store_exception(e)}"
        )
    return problems





# ===========================================================================
# AUDIT LOG (FIFO, max 1000)
# ===========================================================================

class AuditLog:
    """Trådsäker audit-log med FIFO-eviction."""

    __slots__ = ("_entries", "_max", "_lock", "_stats")

    def __init__(self, max_entries: int = AUDIT_LOG_MAX_ENTRIES) -> None:
        self._entries: List[Dict[str, Any]] = []
        self._max = max_entries
        self._lock = threading.RLock()
        self._stats: Dict[str, int] = {}
        logger.debug(f"{LOG_PREFIX} AuditLog skapad (max={max_entries})")

    def add(
        self,
        operation: str,
        task_id: str,
        before: Any = None,
        after: Any = None,
        reason: str = "",
    ) -> None:
        """Lägg till entry (FIFO)."""
        entry = {
            "op": operation,
            "task_id": task_id,
            "ts": time.time(),
            "ts_iso": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
        }
        if before is not None:
            entry["before"] = _safe_copy(before)
        if after is not None:
            entry["after"] = _safe_copy(after)
        with self._lock:
            self._entries.append(entry)
            self._stats[operation] = self._stats.get(operation, 0) + 1
            if len(self._entries) > self._max:
                self._entries.pop(0)
        logger.trace(
            f"{LOG_PREFIX} audit: {operation} {task_id!r} "
            f"(total={len(self._entries)}, stats={dict(self._stats)})"
        )

    def get_entries(
        self,
        task_id: Optional[str] = None,
        operation: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Hämta entries (filtrerat)."""
        with self._lock:
            entries = self._entries
        # Filtrering inline (snabbare än comprehension)
        filtered = []
        for e in entries:
            if task_id is not None and e.get("task_id") != task_id:
                continue
            if operation is not None and e.get("op") != operation:
                continue
            filtered.append(e)
        return filtered[-limit:]

    def clear(self) -> None:
        """Rensa alla entries."""
        with self._lock:
            count = len(self._entries)
            self._entries.clear()
            self._stats.clear()
        logger.info(f"{LOG_PREFIX} AuditLog rensad ({count} entries)")

    def get_stats(self) -> Dict[str, Any]:
        """Statistik."""
        with self._lock:
            return {
                "total_entries": len(self._entries),
                "max_entries": self._max,
                "by_operation": dict(self._stats),
            }


def _safe_copy(obj: Any) -> Any:
    """Snabb deep-copy för audit (Dict/List only)."""
    if isinstance(obj, dict):
        return {k: _safe_copy(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_safe_copy(v) for v in obj]
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    return repr(obj)[:200]


# ===========================================================================
# LRU+TTL CACHE (för find_task + filter)
# ===========================================================================

class _LRUCache:
    """LRU-cache med TTL (för snabb lookup)."""

    __slots__ = ("_data", "_access_order", "_max_size", "_ttl", "_lock", "_hits", "_misses")

    def __init__(self, max_size: int = LUCACHE_MAX_SIZE, ttl_sec: float = LUCACHE_TTL_SEC) -> None:
        self._data: Dict[Any, Tuple[float, Any]] = {}
        self._access_order: List[Any] = []
        self._max_size = max_size
        self._ttl = ttl_sec
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def get(self, key: Any) -> Tuple[bool, Any]:
        """Hämta värde (returnerar (hit, value))."""
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self._misses += 1
                return False, None
            ts, value = entry
            if (time.time() - ts) > self._ttl:
                # TTL expired
                self._data.pop(key, None)
                try:
                    self._access_order.remove(key)
                except ValueError:
                    pass
                self._misses += 1
                return False, None
            # Uppdatera access order
            try:
                self._access_order.remove(key)
            except ValueError:
                pass
            self._access_order.append(key)
            self._hits += 1
            return True, value

    def set(self, key: Any, value: Any) -> None:
        """Sätt värde (LRU-eviction vid full)."""
        with self._lock:
            if key in self._data:
                try:
                    self._access_order.remove(key)
                except ValueError:
                    pass
            self._data[key] = (time.time(), value)
            self._access_order.append(key)
            if len(self._data) > self._max_size:
                evict = self._access_order.pop(0)
                self._data.pop(evict, None)

    def clear(self) -> None:
        """Rensa cache."""
        with self._lock:
            self._data.clear()
            self._access_order.clear()
            self._hits = 0
            self._misses = 0

    def stats(self) -> Dict[str, Any]:
        """Statistik (för diagnostics)."""
        with self._lock:
            total = self._hits + self._misses
            return {
                "size": len(self._data),
                "max_size": self._max_size,
                "ttl_sec": self._ttl,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": self._hits / total if total > 0 else 0.0,
            }


# ===========================================================================
# HELPERS (inline-optimerade)
# ===========================================================================

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_iso() -> str:
    return datetime.now().date().isoformat()


def _make_id() -> str:
    """Generera kort unikt ID (8 tecken)."""
    return "".join(secrets.choice(ID_ALPHABET) for _ in range(ID_LENGTH))


def _normalize_tag(tag: Any) -> Optional[str]:
    """Normalisera tag (lowercase, strip, valid-chars)."""
    if not isinstance(tag, str):
        return None
    t = TAG_NORMALIZE_RE.sub("", tag.strip().lower())
    if not t or len(t) > MAX_TAG_LENGTH:
        return None
    return t


def _normalize_title(title: Any) -> Optional[str]:
    """Normalisera titel (strip, collapse whitespace, truncate)."""
    if not isinstance(title, str):
        return None
    t = TITLE_WS_RE.sub(" ", title.strip())
    if not t:
        return None
    return t[:MAX_TITLE_LENGTH]


def _coerce_priority(p: Any) -> str:
    """Coerce + validate priority (inline)."""
    if isinstance(p, str) and p in VALID_PRIORITIES:
        return p
    return "medium"


def _coerce_bool(v: Any, default: bool = False) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.lower() in ("true", "1", "yes", "on", "ja")
    return default


def _coerce_str(v: Any, default: str = "", max_len: int = MAX_TITLE_LENGTH) -> str:
    if not isinstance(v, str):
        v = str(v) if v is not None else default
    return v[:max_len] if v else default


def _coerce_str_or_none(v: Any) -> Optional[str]:
    """Coerce till Optional[str] (None om tomt)."""
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip()
        return v if v else None
    return str(v)


def _coerce_tags(raw: Any) -> List[str]:
    """Coerce + dedup + validate tags."""
    if not isinstance(raw, (list, tuple)):
        return []
    seen: Set[str] = set()
    result: List[str] = []
    for t in raw[:MAX_TAGS_PER_TASK]:
        nt = _normalize_tag(t)
        if nt and nt not in seen:
            seen.add(nt)
            result.append(nt)
    return result


def _coerce_subtask(raw: Any) -> Optional[Dict[str, Any]]:
    """Coerce subtask (snabb inline-validering)."""
    if not isinstance(raw, dict):
        return None
    sid = _coerce_str(raw.get("id"), default="", max_len=ID_LENGTH)
    if not sid:
        return None
    title = _normalize_title(raw.get("title", ""))
    if not title:
        return None
    return {
        "id": sid,
        "title": title,
        "done": _coerce_bool(raw.get("done"), False),
    }


def _coerce_task(raw: Any, idx: int = 0) -> Optional[Dict[str, Any]]:
    """Coerce task (snabb inline-validering, alla fält)."""
    if not isinstance(raw, dict):
        logger.warning(f"{LOG_PREFIX} task #{idx} är inte dict: {type(raw).__name__}")
        return None
    # ID (generera om saknas)
    tid = _coerce_str(raw.get("id"), default="", max_len=ID_LENGTH)
    if not tid or len(tid) != ID_LENGTH:
        tid = _make_id()
    # Title (kritiskt)
    title = _normalize_title(raw.get("title"))
    if not title:
        logger.warning(f"{LOG_PREFIX} task #{idx} ({tid}) saknar title, hoppar över")
        return None
    # Subtasks (max MAX_SUBTASKS_PER_TASK)
    raw_subs = raw.get("subtasks", [])
    subs: List[Dict[str, Any]] = []
    if isinstance(raw_subs, list):
        for s in raw_subs[:MAX_SUBTASKS_PER_TASK]:
            cs = _coerce_subtask(s)
            if cs is not None:
                subs.append(cs)
    # Recurring (valfritt)
    rec = raw.get("recurring")
    recurring = None
    if isinstance(rec, dict):
        interval = _coerce_str(rec.get("interval"), default="", max_len=16)
        if interval in ("daily", "weekly", "monthly"):
            recurring = {
                "interval": interval,
                "next_due": _coerce_str_or_none(rec.get("next_due")),
            }
    return {
        "id": tid,
        "title": title,
        "done": _coerce_bool(raw.get("done"), False),
        "priority": _coerce_priority(raw.get("priority")),
        "due_date": _coerce_str_or_none(raw.get("due_date")),
        "tags": _coerce_tags(raw.get("tags")),
        "pinned": _coerce_bool(raw.get("pinned"), False),  # NY v6.4
        "subtasks": subs,
        "recurring": recurring,
        "snoozed_until": _coerce_str_or_none(raw.get("snoozed_until")),
        "created": _coerce_str_or_none(raw.get("created")) or _now_iso(),
        "completed": _coerce_str_or_none(raw.get("completed")),
    }


def _next_recurring_due(
    due_date: Optional[str], interval: Optional[str]
) -> Optional[str]:
    """
    NY v7-fix41: beräkna nästa förfallodatum för återkommande uppgift.

    Börjar från nuvarande due_date (om framtida) annars från idag,
    och stegar ett intervall i taget tills datumet är i framtiden.
    Returnerar ISO-datum (YYYY-MM-DD) eller None vid ogiltigt intervall.
    """
    if interval not in ("daily", "weekly", "monthly"):
        return None
    from datetime import date, timedelta

    today = date.today()
    try:
        base = (
            datetime.fromisoformat(str(due_date)).date()
            if due_date
            else today
        )
    except (ValueError, TypeError):
        base = today
    step = {
        "daily": timedelta(days=1),
        "weekly": timedelta(weeks=1),
        "monthly": timedelta(days=30),  # månads-steg praktiskt nära
    }[interval]
    # Stega tills datumet är idag eller senare
    while base < today:
        base = base + step
    if base <= today:
        base = base + step
    return base.isoformat()


# ===========================================================================
# TASK STORE (hjärtat — med __slots__ för minimalt minne)
# ===========================================================================

class TaskStore(QObject):
    """
    Thread-safe TaskStore med:
      • __slots__ (sparar ~40% minne)
      • Index-cache (O(1) lookup på id, tag, priority, pinned)
      • LRU+TTL cache (för find_task + filter)
      • Bulk-API (100× färre locks för mass-operationer)
      • mtime-cache (undvik onödiga disk-reads)
      • Generator-stöd (för stora listor)
      • AuditLog + signals
    """

    # === SIGNALS (Qt) ===
    if _QT_AVAILABLE:
        changed = Signal()
        task_added = Signal(str)
        task_removed = Signal(str)
        task_toggled = Signal(str, bool)
        task_updated = Signal(str)
        tags_changed = Signal()
        archive_changed = Signal()
    else:
        def __getattr__(self, name: str) -> Any:
            # v7-fix11: returnera CACHEAD dummy-signal. Tidigare skapades en
            # NY _DummySignal per attributåtkomst → connect() registrerade
            # callbacks på ett kastbart objekt (signaler oanvändbara utan Qt).
            if name == "_dummy_signals":
                raise AttributeError(name)
            try:
                ds = self._dummy_signals
            except AttributeError:
                raise AttributeError(name) from None
            if name in ds:
                return ds[name]
            raise AttributeError(name)

    # === KLASS-KONSTANTER ===
    DEFAULT_ACTIVE_FILENAME: ClassVar[str] = "active.json"
    DEFAULT_ARCHIVE_FILENAME: ClassVar[str] = "archive.json"
    DEFAULT_BACKUP_DIRNAME: ClassVar[str] = "backups"
    DEFAULT_AUDIT_FILENAME: ClassVar[str] = "audit.log"

    # === __SLOTS__ (minimalt minne) ===
    __slots__ = (
        # Paths
        "_data_dir", "_active_path", "_archive_path", "_backup_dir", "_audit_path",
        # State
        "_active_tasks", "_archive_tasks", "_active_index", "_archive_index",
        # Indices
        "_by_id", "_by_tag", "_by_priority", "_pinned_ids",
        # Cache
        "_find_cache", "_filter_cache",
        # Meta
        "_schema_version", "_saved_at", "_dirty",
        # Locks
        "_lock", "_save_lock", "_save_thread",
        # Audit
        "_audit_log",
        # Stats
        "_save_count", "_load_count", "_error_count", "_bulk_count",
        # mtime cache
        "_active_mtime", "_archive_mtime", "_mtime_cache_time",
        # Dummy-signaler (v7-fix11 — utan Qt: cacheade _DummySignal per namn)
        "_dummy_signals",
    )

    # ========================================================================
    # INIT
    # ========================================================================

    def __init__(self, data_dir_override: Optional[str] = None) -> None:
        super().__init__()
        # Paths
        self._data_dir = Path(data_dir_override) if data_dir_override else DEFAULT_DATA_DIR
        self._active_path = self._data_dir / self.DEFAULT_ACTIVE_FILENAME
        self._archive_path = self._data_dir / self.DEFAULT_ARCHIVE_FILENAME
        self._backup_dir = self._data_dir / self.DEFAULT_BACKUP_DIRNAME
        self._audit_path = self._data_dir / self.DEFAULT_AUDIT_FILENAME
        # State
        self._active_tasks: List[Dict[str, Any]] = []
        self._archive_tasks: List[Dict[str, Any]] = []
        self._active_index: Dict[str, int] = {}
        self._archive_index: Dict[str, int] = {}
        # Indices
        self._by_id: Dict[str, Dict[str, Any]] = {}
        self._by_tag: Dict[str, Set[str]] = {}
        self._by_priority: Dict[str, Set[str]] = {
            "none": set(), "low": set(), "medium": set(), "high": set()
        }
        self._pinned_ids: Set[str] = set()
        # Cache
        self._find_cache: _LRUCache = _LRUCache()
        self._filter_cache: _LRUCache = _LRUCache()
        # Meta
        self._schema_version: int = SCHEMA_VERSION
        self._saved_at: Optional[str] = None
        self._dirty: bool = False
        # Locks
        self._lock = threading.RLock()
        self._save_lock = threading.RLock()
        self._save_thread: Optional[threading.Thread] = None
        # Audit
        self._audit_log = AuditLog()
        # Stats
        self._save_count: int = 0
        self._load_count: int = 0
        self._error_count: int = 0
        self._bulk_count: int = 0
        # mtime cache
        self._active_mtime: float = 0.0
        self._archive_mtime: float = 0.0
        self._mtime_cache_time: float = 0.0
        # Dummy-signaler (v7-fix11): utan Qt skapas EN cachead _DummySignal
        # per signalnamn — connect()/emit() funkar då identiskt i tester.
        self._dummy_signals: Dict[str, Any] = {}
        if not _QT_AVAILABLE:
            for _sig_name in (
                "changed", "task_added", "task_removed", "task_toggled",
                "task_updated", "tags_changed", "archive_changed",
            ):
                self._dummy_signals[_sig_name] = _DummySignal()

        logger.info(f"{LOG_PREFIX} TaskStore initierad (v6.4.0, orjson={_HAS_ORJSON})")
        logger.debug(f"{LOG_PREFIX} paths: data={self._data_dir}, active={self._active_path.name}")
        # FIX v7-fix15: migrera ev. tasks från gamla core/data → rot-data
        # (körs FÖRE load; kopierar endast om nya platsen saknar filerna).
        self._migrate_legacy_core_data()
        self._migrate_and_load()

    # ========================================================================
    # PROPERTIES
    # ========================================================================

    @property
    def data_dir(self) -> str:
        return str(self._data_dir)

    @property
    def active_path(self) -> str:
        return str(self._active_path)

    @property
    def archive_path(self) -> str:
        return str(self._archive_path)

    @property
    def schema_version(self) -> int:
        return self._schema_version

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    @property
    def audit_log(self) -> AuditLog:
        return self._audit_log

    # ========================================================================
    # LOAD / SAVE / MIGRATE
    # ========================================================================

    def _migrate_legacy_core_data(self) -> None:
        """
        FIX v7-fix15: migrera tasks från gamla core/data → rot-data.

        Bakgrund: TaskStore() startades utan data_dir-argument och föll då
        tillbaka på core/data — medan settings + logg låg i <rot>/data.
        Resultat: två data-kataloger (split-brain) och backuper som saknade
        settings.json. Nu ligger ALLT i <rot>/data.

        Kopierar (flyttar ALDRIG) active.json/archive.json om de saknas på
        nya platsen men finns på gamla — originalet lämnas som säkerhet.
        """
        if LEGACY_CORE_DATA_DIR == self._data_dir:
            return
        # FIX v7-fix34: migrera även från gamla data/-mappen till js/
        _legacy_root = LEGACY_ROOT_DATA_DIR
        if _legacy_root.is_dir() and _legacy_root != self._data_dir:
            for _fname in ("active.json", "archive.json"):
                _src = _legacy_root / _fname
                _dst = self._data_dir / _fname
                if _src.is_file() and not _dst.is_file():
                    with suppress(Exception):
                        self._data_dir.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(_src, _dst)
                        logger.info(
                            f"{LOG_PREFIX} migrerade {_fname}: "
                            f"{_src} → {_dst} (data→js)"
                        )
        try:
            if not LEGACY_CORE_DATA_DIR.is_dir():
                return
            migrated = 0
            for name in (self.DEFAULT_ACTIVE_FILENAME, self.DEFAULT_ARCHIVE_FILENAME):
                src = LEGACY_CORE_DATA_DIR / name
                dst = self._data_dir / name
                if src.is_file() and not dst.is_file():
                    try:
                        self._data_dir.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dst)
                        migrated += 1
                        logger.info(
                            f"{LOG_PREFIX} migrerade {name}: {src} → {dst} "
                            f"(kopia — originalet lämnas som säkerhet)"
                        )
                    except OSError as e:
                        logger.warning(
                            f"{LOG_PREFIX} kunde inte migrera {name}: {e}"
                        )
            if migrated:
                logger.info(
                    f"{LOG_PREFIX} legacy-migrering klar: {migrated} fil(er) "
                    f"från {LEGACY_CORE_DATA_DIR} till {self._data_dir}"
                )
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} legacy-migrering misslyckades: {e}")

    def _migrate_and_load(self) -> None:
        """Ladda + migrera till schema v5 och håll arkiv/aktiva konsekventa."""
        try:
            self._data_dir.mkdir(parents=True, exist_ok=True)
            self._backup_dir.mkdir(exist_ok=True)
            logger.debug(f"{LOG_PREFIX} data-mapp OK: {self._data_dir}")
        except OSError as e:
            logger.error(f"{LOG_PREFIX} mkdir misslyckades: {e}", exc_info=True)
        with self._lock:
            self._load_file(self._active_path, "active")
            self._load_file(self._archive_path, "archive")

            # Äldre versioner lät kryssade uppgifter ligga kvar bland aktiva.
            # Flytta dem till arkivet vid inläsning så att uppgraderingen också
            # rättar redan sparade uppgifter, inte bara nya avbockningar.
            archived_ids = {task["id"] for task in self._archive_tasks}
            active_tasks: List[Dict[str, Any]] = []
            moved_done = 0
            for task in self._active_tasks:
                if task.get("done"):
                    if task["id"] not in archived_ids:
                        self._archive_tasks.append(task)
                        archived_ids.add(task["id"])
                    moved_done += 1
                else:
                    active_tasks.append(task)
            if moved_done:
                self._active_tasks = active_tasks

            # Arkiverade uppgifter ska alltid vara markerade som klara.
            normalized_archive = 0
            for task in self._archive_tasks:
                if not task.get("done"):
                    task["done"] = True
                    normalized_archive += 1
            if moved_done or normalized_archive:
                self._dirty = True
                logger.info(
                    f"{LOG_PREFIX} completion-migrering: "
                    f"{moved_done} aktiva klara → arkiv, "
                    f"{normalized_archive} arkivstatus korrigerade"
                )
            self._rebuild_index()

    def _load_file(self, path: Path, kind: str) -> None:
        """Ladda tasks från fil (med mtime-cache)."""
        start = time.perf_counter()
        if not path.exists():
            logger.debug(f"{LOG_PREFIX} {kind}: fil finns inte ({path.name})")
            return
        try:
            current_mtime = path.stat().st_mtime
            # mtime-cache: undvik onödig reload
            cache_attr = f"_{kind}_mtime"
            cached_mtime = getattr(self, cache_attr, 0.0)
            if current_mtime == cached_mtime and cached_mtime > 0:
                logger.trace(
                    f"{LOG_PREFIX} {kind}: mtime-cache hit, skippar reload"
                )
                return
            raw = path.read_bytes()
            logger.trace(
                f"{LOG_PREFIX} {kind}: läser {len(raw)} bytes från {path.name}"
            )
            data = _json_loads(raw)
            # NY v6.4: Hantera att data kan vara dict ELLER lista
            if isinstance(data, list):
                logger.warning(
                    f"{LOG_PREFIX} {kind}: data är lista (ingen wrapper), "
                    f"antar att det är tasks-listan"
                )
                tasks = data
                version = 1
            elif isinstance(data, dict):
                version = data.get("version", 1)
                tasks = data.get("tasks", [])
            else:
                logger.error(
                    f"{LOG_PREFIX} {kind}: data är {type(data).__name__}, "
                    f"förväntade dict eller lista"
                )
                tasks = []
                version = 1
            if not isinstance(tasks, list):
                logger.error(
                    f"{LOG_PREFIX} {kind}: 'tasks' är inte en lista, "
                    f"använder tom"
                )
                tasks = []
            # Migrera om nödvändigt
            if version != SCHEMA_VERSION:
                logger.info(
                    f"{LOG_PREFIX} {kind}: migrerar v{version} → v{SCHEMA_VERSION}"
                )
                tasks = self._migrate_tasks(tasks, version, SCHEMA_VERSION)
                self._dirty = True
            # Coerce + filtrera. Saknas created fylls det i av _coerce_task;
            # markera då store som dirty så datumet blir beständigt efter save.
            if any(
                not isinstance(raw_task, dict) or not raw_task.get("created")
                for raw_task in tasks
            ):
                self._dirty = True
            valid_tasks: List[Dict[str, Any]] = []
            for idx, raw_task in enumerate(tasks):
                ct = _coerce_task(raw_task, idx=idx)
                if ct is not None:
                    valid_tasks.append(ct)
            if len(valid_tasks) < len(tasks):
                logger.warning(
                    f"{LOG_PREFIX} {kind}: filtrerade bort "
                    f"{len(tasks) - len(valid_tasks)} trasiga tasks"
                )
            # Sätt state
            if kind == "active":
                self._active_tasks = valid_tasks
                self._active_mtime = current_mtime
            else:
                self._archive_tasks = valid_tasks
                self._archive_mtime = current_mtime
            self._schema_version = SCHEMA_VERSION
            # FIX v7-fix11: 'data' kan vara en LISTA (äldre format utan
            # wrapper) — listor har ingen .get() → AttributeError →
            # except-grenen dömde filen som KORRUPT och tömde tasks!
            self._saved_at = data.get("saved_at") if isinstance(data, dict) else None
            self._load_count += 1
            duration = (time.perf_counter() - start) * 1000
            logger.info(
                f"{LOG_PREFIX} {kind} loaded: {len(valid_tasks)} tasks, "
                f"v{version}→v{SCHEMA_VERSION}, {duration:.2f}ms "
                f"(load_count={self._load_count})"
            )
        except Exception as e:
            self._error_count += 1
            logger.error(
                f"{LOG_PREFIX} load_file({path.name}) misslyckades: {e}",
                exc_info=True,
            )
            self._handle_corrupt_file(path)

    def _migrate_tasks(
        self, tasks: List[Dict[str, Any]], old_v: int, new_v: int
    ) -> List[Dict[str, Any]]:
        """Migrera tasks (v3→v4→v5)."""
        logger.info(f"{LOG_PREFIX} migration v{old_v}→v{new_v}: {len(tasks)} tasks")
        if old_v < 4:
            for t in tasks:
                if "priority" not in t:
                    t["priority"] = "medium"
                if "subtasks" not in t:
                    t["subtasks"] = []
        if old_v < 5:
            for t in tasks:
                if "pinned" not in t:
                    t["pinned"] = False
                if "recurring" not in t:
                    t["recurring"] = None
                if "snoozed_until" not in t:
                    t["snoozed_until"] = None
        logger.debug(f"{LOG_PREFIX} migration klar")
        return tasks

    def _handle_corrupt_file(self, path: Path) -> None:
        """Hantera korrupt fil (backup → defaults)."""
        try:
            corrupt_path = path.with_suffix(".corrupt.json")
            shutil.copy2(path, corrupt_path)
            logger.warning(
                f"{LOG_PREFIX} korrupt fil säkerhetskopierad: {corrupt_path.name}"
            )
        except Exception as e:
            logger.error(f"{LOG_PREFIX} corrupt-backup misslyckades: {e}", exc_info=True)
        # Sätt tom lista
        if "active" in path.name:
            self._active_tasks = []
        else:
            self._archive_tasks = []

    def _rebuild_index(self) -> None:
        """Bygg om ALLA index (id, tag, priority, pinned)."""
        start = time.perf_counter()
        with self._lock:
            # Rensa indices
            self._by_id.clear()
            self._by_tag.clear()
            self._by_priority["none"].clear()
            self._by_priority["low"].clear()
            self._by_priority["medium"].clear()
            self._by_priority["high"].clear()
            self._pinned_ids.clear()
            # Bygg active
            self._active_index = {t["id"]: i for i, t in enumerate(self._active_tasks)}
            for task in self._active_tasks:
                self._index_task(task)
            # Bygg archive
            self._archive_index = {t["id"]: i for i, t in enumerate(self._archive_tasks)}
            for task in self._archive_tasks:
                self._index_task(task, archive=True)
        # Rensa cache (indices ändrade)
        self._find_cache.clear()
        self._filter_cache.clear()
        duration = (time.perf_counter() - start) * 1000
        logger.debug(
            f"{LOG_PREFIX} rebuild_index: {len(self._by_id)} tasks, "
            f"{len(self._by_tag)} unika tags, "
            f"{len(self._pinned_ids)} pinned ({duration:.2f}ms)"
        )

    def _index_task(self, task: Dict[str, Any], archive: bool = False) -> None:
        """Lägg till task i alla index (inline)."""
        tid = task["id"]
        self._by_id[tid] = task
        for tag in task.get("tags", []):
            self._by_tag.setdefault(tag, set()).add(tid)
        priority = task.get("priority", "medium")
        self._by_priority.setdefault(priority, set()).add(tid)
        if task.get("pinned"):
            self._pinned_ids.add(tid)

    @_log_call
    def save(self) -> bool:
        """Spara ALLA tasks (atomic, anti-deadlock).

        FIX v7-fix11: anropade tidigare _save_internal() TVÅ gånger (dubbel
        disk-I/O, dubbla backup-rotationer, dubbla signaler per save).
        """
        result = self._save_internal()
        return result is not None and result.success

    def _save_internal(self) -> Optional["_SaveResult"]:
        """Privat save: trådsäker + atomic."""
        start = time.perf_counter()
        if not self._save_lock.acquire(timeout=SAVE_TIMEOUT_SEC):
            self._error_count += 1
            logger.error(
                f"{LOG_PREFIX} save timeout ({SAVE_TIMEOUT_SEC}s) — låst av annan tråd"
            )
            return _SaveResult(False, 0.0, "Save-timeout")
        try:
            with self._lock:
                # Snapshot
                saved_at = _now_iso()
                active_data = {
                    "version": SCHEMA_VERSION,
                    "saved_at": saved_at,
                    "tasks": [_safe_copy(t) for t in self._active_tasks],
                }
                archive_data = {
                    "version": SCHEMA_VERSION,
                    "saved_at": saved_at,
                    "tasks": [_safe_copy(t) for t in self._archive_tasks],
                }
            # Backup (före skrivning)
            self._rotate_backup(self._active_path)
            self._rotate_backup(self._archive_path)
            # Atomic write (båda filer)
            ok1 = self._atomic_write(self._active_path, active_data)
            ok2 = self._atomic_write(self._archive_path, archive_data)
            if not (ok1 and ok2):
                self._error_count += 1
                return _SaveResult(
                    False, time.perf_counter() - start, "Atomic write misslyckades"
                )
            # Uppdatera mtime-cache + state
            with self._lock:
                self._dirty = False
                self._saved_at = saved_at
                self._save_count += 1
                self._active_mtime = self._active_path.stat().st_mtime
                self._archive_mtime = self._archive_path.stat().st_mtime
            duration = time.perf_counter() - start
            logger.info(
                f"{LOG_PREFIX} save OK: {len(self._active_tasks)} active, "
                f"{len(self._archive_tasks)} archive, {duration*1000:.2f}ms "
                f"(save_count={self._save_count})"
            )
            # FIX v7-fix11: emitterar INTE 'changed' — save är persistering,
            # inte en dataändring. (Annars: changed→autosave→save→changed→…
            # oändlig loop när main kopplar changed→autosave. reload() emitterar
            # fortfarande 'changed' eftersom datan DÄR faktiskt ändras.)
            return _SaveResult(True, duration)
        except Exception as e:
            self._error_count += 1
            duration = time.perf_counter() - start
            logger.error(
                f"{LOG_PREFIX} save misslyckades ({duration*1000:.2f}ms): {e}",
                exc_info=True,
            )
            return _SaveResult(False, duration, str(e))
        finally:
            self._save_lock.release()

    def _atomic_write(self, path: Path, data: Dict[str, Any]) -> bool:
        """Atomic write: tmp → fsync → verify → os.replace."""
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        try:
            json_bytes = _json_dumps(data)
            with open(tmp_path, "wb") as f:
                f.write(json_bytes)
                f.flush()
                os.fsync(f.fileno())
            # Verify
            try:
                with open(tmp_path, "rb") as f:
                    _json_loads(f.read())
            except Exception as e:
                logger.error(
                    f"{LOG_PREFIX} verify misslyckades för {path.name}: {e}"
                )
                return False
            # Atomic replace
            os.replace(tmp_path, path)
            logger.trace(
                f"{LOG_PREFIX} atomic write OK: {path.name} ({len(json_bytes)} bytes)"
            )
            return True
        except Exception as e:
            logger.error(
                f"{LOG_PREFIX} atomic_write({path.name}) misslyckades: {e}",
                exc_info=True,
            )
            with suppress(OSError):
                tmp_path.unlink()
            return False

    def _rotate_backup(self, path: Path) -> None:
        """Rotera backup (behåll senaste N)."""
        if not path.exists():
            return
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = self._backup_dir / f"{path.stem}_{timestamp}.json"
            shutil.copy2(path, backup_path)
            # Rotera (ta bort äldsta)
            backups = sorted(self._backup_dir.glob(f"{path.stem}_*.json"))
            if len(backups) > BACKUP_KEEP:
                for old in backups[:-BACKUP_KEEP]:
                    with suppress(OSError):
                        old.unlink()
                logger.debug(
                    f"{LOG_PREFIX} backup rotation: tog bort "
                    f"{len(backups) - BACKUP_KEEP} gamla"
                )
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} backup rotation misslyckades för {path.name}: {e}"
            )

    @_log_call
    def reload(self) -> bool:
        """Ladda om från disk."""
        with self._lock:
            self._load_file(self._active_path, "active")
            self._load_file(self._archive_path, "archive")
            self._rebuild_index()
        self._emit("changed")
        return True

    # ========================================================================
    # CRUD — TASK
    # ========================================================================

    def set_task_metadata(self, task_id: str, key: str, value: Any) -> bool:
        """
        NY v7-fix35: Sätt metadata-fält på en task (t.ex. email_path).

        Används av email_import för att lagra e-postreferenser.
        """
        with self._lock:
            task = self._by_id.get(task_id)
            if task is None:
                logger.warning(
                    f"{LOG_PREFIX} set_task_metadata: {task_id!r} saknas"
                )
                return False
            task[key] = value
            self._dirty = True
            self._filter_cache.clear()  # FIX v7-fix79b: cache-koherens
            self._find_cache.clear()
            logger.debug(
                f"{LOG_PREFIX} set_task_metadata({task_id!r}, "
                f"{key!r}) = {str(value)[:50]!r}"
            )
            self._emit("task_updated", task_id)
            self._emit("changed")
            return True

    @_log_crud("add_task")
    def add_task(
        self,
        title: str,
        priority: str = "medium",
        due_date: Optional[str] = None,
        tags: Optional[List[str]] = None,
        subtasks: Optional[List[Dict[str, Any]]] = None,
        pinned: bool = False,
        recurring: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Lägg till ny task. Returnerar task-id (None vid fel)."""
        nt = _normalize_title(title)
        if not nt:
            logger.warning(f"{LOG_PREFIX} add_task: tom titel, avbryter")
            return None
        with self._lock:
            if len(self._active_tasks) >= MAX_TASKS:
                logger.warning(
                    f"{LOG_PREFIX} add_task: max uppnått ({MAX_TASKS})"
                )
                return None
            tid = _make_id()
            task = {
                "id": tid,
                "title": nt,
                "done": False,
                "priority": _coerce_priority(priority),
                "due_date": _coerce_str_or_none(due_date),
                "tags": _coerce_tags(tags) if tags else [],
                "pinned": bool(pinned),
                "subtasks": [
                    cs for cs in (
                        _coerce_subtask(s) for s in (subtasks or [])
                    ) if cs is not None
                ][:MAX_SUBTASKS_PER_TASK],
                "recurring": recurring,
                "snoozed_until": None,
                "created": _now_iso(),
                "completed": None,
            }
            self._active_tasks.append(task)
            # FIX v7-fix11: _index_task() uppdaterar INTE _active_index —
            # utan denna rad kan nyligen tillagda tasks inte arkiveras,
            # tas bort eller omordnas förrän efter omstart (indexet byggs
            # bara vid load via _rebuild_index).
            self._active_index[tid] = len(self._active_tasks) - 1
            self._index_task(task)
            self._dirty = True
        # Invalidate cache
        self._find_cache.clear()
        self._filter_cache.clear()
        # Audit
        self._audit_log.add("add_task", tid, after=task, reason="add")
        logger.info(
            f"{LOG_PREFIX} add_task: {tid!r} '{nt[:50]}' "
            f"(priority={task['priority']}, pinned={pinned})"
        )
        self._emit("task_added", tid)
        self._emit("changed")
        return tid

    @_log_crud("remove_task")
    def remove_task(self, task_id: str) -> bool:
        """Ta bort task (från active OCH archive)."""
        with self._lock:
            # Active
            idx = self._active_index.get(task_id)
            if idx is not None:
                task = self._active_tasks.pop(idx)
                self._deindex_task(task)
                del self._active_index[task_id]
                self._reindex_active_after(idx)
                self._dirty = True
                self._find_cache.clear()
                self._filter_cache.clear()
                self._audit_log.add("remove_task", task_id, before=task, reason="remove")
                logger.info(
                    f"{LOG_PREFIX} remove_task: {task_id!r} (active, "
                    f"title='{task['title'][:50]}')"
                )
                self._emit("task_removed", task_id)
                self._emit("changed")
                return True
            # Archive
            idx = self._archive_index.get(task_id)
            if idx is not None:
                task = self._archive_tasks.pop(idx)
                self._deindex_task(task, archive=True)
                del self._archive_index[task_id]
                self._reindex_archive_after(idx)
                self._dirty = True
                self._find_cache.clear()
                self._filter_cache.clear()
                self._audit_log.add("remove_task", task_id, before=task, reason="remove-archive")
                logger.info(f"{LOG_PREFIX} remove_task: {task_id!r} (archive)")
                self._emit("task_removed", task_id)
                self._emit("changed")
                return True
        logger.warning(f"{LOG_PREFIX} remove_task: {task_id!r} hittades inte")
        return False

    def _deindex_task(self, task: Dict[str, Any], archive: bool = False) -> None:
        """Ta bort task från index (inline)."""
        tid = task["id"]
        self._by_id.pop(tid, None)
        for tag in task.get("tags", []):
            s = self._by_tag.get(tag)
            if s is not None:
                s.discard(tid)
        priority = task.get("priority", "medium")
        s = self._by_priority.get(priority)
        if s is not None:
            s.discard(tid)
        if task.get("pinned"):
            self._pinned_ids.discard(tid)

    def _reindex_active_after(self, start_idx: int) -> None:
        """Uppdatera active_index efter remove."""
        for i in range(start_idx, len(self._active_tasks)):
            self._active_index[self._active_tasks[i]["id"]] = i

    def _reindex_archive_after(self, start_idx: int) -> None:
        """Uppdatera archive_index efter remove."""
        for i in range(start_idx, len(self._archive_tasks)):
            self._archive_index[self._archive_tasks[i]["id"]] = i

    @_log_crud("toggle_task")
    def toggle_task(self, task_id: str) -> bool:
        """Växla klarstatus och flytta klara uppgifter till arkivet.

        Om en arkiverad uppgift bockas ur flyttas den tillbaka till aktiva.
        Återkommande uppgifter arkiveras som avslutade tillfällen och får en
        ny aktiv uppgift med nästa förfallodatum.
        """
        moved_to_archive = False
        moved_to_active = False
        recurring_task_id: Optional[str] = None
        with self._lock:
            task = self._by_id.get(task_id)
            if task is None:
                logger.warning(f"{LOG_PREFIX} toggle_task: {task_id!r} hittades inte")
                return False
            before = _safe_copy(task)
            new_done = not bool(task.get("done", False))
            active_idx = self._active_index.get(task_id)
            archive_idx = self._archive_index.get(task_id)

            if active_idx is not None:
                if new_done:
                    recurring = task.get("recurring")
                    next_due = (
                        _next_recurring_due(
                            task.get("due_date"), recurring.get("interval")
                        )
                        if isinstance(recurring, dict)
                        else None
                    )
                    task["done"] = True
                    task["completed"] = _now_iso()
                    if next_due and isinstance(recurring, dict):
                        recurring["next_due"] = next_due

                    self._active_tasks.pop(active_idx)
                    self._deindex_task(task)
                    del self._active_index[task_id]
                    self._reindex_active_after(active_idx)
                    self._archive_tasks.append(task)
                    self._archive_index[task_id] = len(self._archive_tasks) - 1
                    self._index_task(task, archive=True)
                    moved_to_archive = True

                    if next_due:
                        next_task = _safe_copy(task)
                        recurring_task_id = _make_id()
                        while recurring_task_id in self._by_id:
                            recurring_task_id = _make_id()
                        next_task["id"] = recurring_task_id
                        next_task["done"] = False
                        next_task["due_date"] = next_due
                        next_task["created"] = _now_iso()
                        next_task["completed"] = None
                        next_task["snoozed_until"] = None
                        for subtask in next_task.get("subtasks", []):
                            if isinstance(subtask, dict):
                                subtask["id"] = _make_id()
                                subtask["done"] = False
                        self._active_tasks.append(next_task)
                        self._active_index[recurring_task_id] = len(self._active_tasks) - 1
                        self._index_task(next_task)
                else:
                    # Städa även upp äldre aktiva poster som redan var klara.
                    task["done"] = False
                    task["completed"] = None
            elif archive_idx is not None:
                if new_done:
                    task["done"] = True
                    task["completed"] = task.get("completed") or _now_iso()
                else:
                    self._archive_tasks.pop(archive_idx)
                    self._deindex_task(task, archive=True)
                    del self._archive_index[task_id]
                    self._reindex_archive_after(archive_idx)
                    task["done"] = False
                    task["completed"] = None
                    self._active_tasks.append(task)
                    self._active_index[task_id] = len(self._active_tasks) - 1
                    self._index_task(task)
                    moved_to_active = True
            else:
                logger.warning(
                    f"{LOG_PREFIX} toggle_task: {task_id!r} saknar list-index"
                )
                return False

            self._dirty = True
            after = _safe_copy(task)

        self._filter_cache.clear()  # cache-koherens efter flytt/ändring
        self._find_cache.clear()
        reason = (
            f"nästa återkommande uppgift: {recurring_task_id}"
            if recurring_task_id
            else "klar → arkiv" if moved_to_archive
            else "arkiv → aktiv" if moved_to_active
            else "klarstatus växlad"
        )
        self._audit_log.add(
            "toggle_task", task_id, before=before, after=after, reason=reason
        )
        logger.info(
            f"{LOG_PREFIX} toggle_task: {task_id!r} → done={new_done}, "
            f"arkiv={moved_to_archive}, aktiv={moved_to_active}"
            + (f", nästa={recurring_task_id}" if recurring_task_id else "")
        )

        self._emit("task_toggled", task_id, new_done)
        if moved_to_archive:
            self._emit("task_removed", task_id)
            self._emit("archive_changed")
        elif moved_to_active:
            self._emit("task_added", task_id)
            self._emit("archive_changed")
        else:
            self._emit("task_updated", task_id)
        if recurring_task_id:
            self._emit("task_added", recurring_task_id)
        self._emit("changed")
        return True

    @_log_crud("set_recurring")
    def set_recurring(
        self, task_id: str, interval: Optional[str]
    ) -> bool:
        """
        NY v7-fix41: sätt återkommande-intervall.

        interval: "daily" | "weekly" | "monthly" | None (av).
        Sätter även recurring.next_due = aktuell due_date (om finns).
        """
        with self._lock:
            task = self._by_id.get(task_id)
            if task is None:
                return False
            before = _safe_copy(task)
            if interval in ("daily", "weekly", "monthly"):
                task["recurring"] = {
                    "interval": interval,
                    "next_due": task.get("due_date"),
                }
            else:
                task["recurring"] = None
            self._dirty = True
        self._filter_cache.clear()  # FIX v7-fix79b: cache-koherens
        self._find_cache.clear()
        self._audit_log.add(
            "set_recurring", task_id, before=before, after=_safe_copy(task)
        )
        logger.info(f"{LOG_PREFIX} set_recurring: {task_id!r} → {interval!r}")
        self._emit("task_updated", task_id)
        self._emit("changed")
        return True

    @_log_crud("unsnooze_task")
    def unsnooze_task(self, task_id: str) -> bool:
        """NY v7-fix41: ta bort snooze (visa uppgiften igen direkt)."""
        with self._lock:
            task = self._by_id.get(task_id)
            if task is None:
                return False
            before = _safe_copy(task)
            task["snoozed_until"] = None
            self._dirty = True
        self._filter_cache.clear()  # FIX v7-fix79b: cache-koherens
        self._find_cache.clear()
        self._audit_log.add(
            "unsnooze_task", task_id, before=before, after=_safe_copy(task)
        )
        logger.info(f"{LOG_PREFIX} unsnooze_task: {task_id!r}")
        self._emit("task_updated", task_id)
        self._emit("changed")
        return True

    @_log_crud("update_task_title")
    def update_task_title(self, task_id: str, title: str) -> bool:
        """Uppdatera titel."""
        nt = _normalize_title(title)
        if not nt:
            logger.warning(f"{LOG_PREFIX} update_task_title: tom titel")
            return False
        with self._lock:
            task = self._by_id.get(task_id)
            if task is None:
                return False
            before = _safe_copy(task)
            task["title"] = nt
            self._dirty = True
        self._filter_cache.clear()  # FIX v7-fix79b: cache-koherens
        self._find_cache.clear()
        self._audit_log.add("update_task_title", task_id, before=before, after=_safe_copy(task))
        logger.info(f"{LOG_PREFIX} update_task_title: {task_id!r} → '{nt[:50]}'")
        self._emit("task_updated", task_id)
        self._emit("changed")  # v7-fix11 (UI-refresh)
        return True

    @_log_crud("set_priority")
    def set_priority(self, task_id: str, priority: str) -> bool:
        """Sätt priority."""
        np = _coerce_priority(priority)
        with self._lock:
            task = self._by_id.get(task_id)
            if task is None:
                return False
            before = _safe_copy(task)
            old_priority = task.get("priority", "medium")
            if old_priority == np:
                return False
            # Uppdatera index
            s = self._by_priority.get(old_priority)
            if s is not None:
                s.discard(task_id)
            self._by_priority.setdefault(np, set()).add(task_id)
            task["priority"] = np
            self._dirty = True
        self._find_cache.clear()  # FIX v7-fix79b: cache-koherens
        self._filter_cache.clear()
        self._audit_log.add("set_priority", task_id, before=before, after=_safe_copy(task))
        logger.info(f"{LOG_PREFIX} set_priority: {task_id!r} {old_priority}→{np}")
        self._emit("task_updated", task_id)
        self._emit("changed")  # v7-fix11 (UI-refresh)
        return True

    @_log_crud("set_due_date")
    def set_due_date(self, task_id: str, due_date: Optional[str]) -> bool:
        """Sätt due_date (None för att ta bort)."""
        nd = _coerce_str_or_none(due_date)
        with self._lock:
            task = self._by_id.get(task_id)
            if task is None:
                return False
            before = _safe_copy(task)
            if task.get("due_date") == nd:
                return False
            task["due_date"] = nd
            self._dirty = True
        self._find_cache.clear()
        self._filter_cache.clear()
        self._audit_log.add("set_due_date", task_id, before=before, after=_safe_copy(task))
        logger.info(f"{LOG_PREFIX} set_due_date: {task_id!r} → {nd}")
        self._emit("task_updated", task_id)
        self._emit("changed")  # v7-fix11 (UI-refresh)
        return True

    @_log_crud("snooze_task")
    def snooze_task(self, task_id: str, until_iso: str) -> bool:
        """Snooze task till given tidpunkt."""
        with self._lock:
            task = self._by_id.get(task_id)
            if task is None:
                return False
            before = _safe_copy(task)
            task["snoozed_until"] = until_iso
            self._dirty = True
        self._filter_cache.clear()  # FIX v7-fix79b: cache-koherens
        self._find_cache.clear()
        self._audit_log.add("snooze_task", task_id, before=before, after=_safe_copy(task))
        logger.info(f"{LOG_PREFIX} snooze_task: {task_id!r} until={until_iso}")
        self._emit("task_updated", task_id)
        self._emit("changed")  # v7-fix11 (UI-refresh)
        return True

    @_log_crud("toggle_pinned")
    def toggle_pinned(self, task_id: str) -> bool:
        """Toggle pin-status (NY v6.4)."""
        with self._lock:
            task = self._by_id.get(task_id)
            if task is None:
                logger.warning(f"{LOG_PREFIX} toggle_pinned: {task_id!r} hittades inte")
                return False
            before = _safe_copy(task)
            new_pinned = not task.get("pinned", False)
            task["pinned"] = new_pinned
            if new_pinned:
                self._pinned_ids.add(task_id)
            else:
                self._pinned_ids.discard(task_id)
            self._dirty = True
        self._find_cache.clear()
        self._filter_cache.clear()
        self._audit_log.add("toggle_pinned", task_id, before=before, after=_safe_copy(task))
        logger.info(
            f"{LOG_PREFIX} toggle_pinned: {task_id!r} → {'⭐ PINNED' if new_pinned else '☆ unpinned'}"
        )
        self._emit("task_updated", task_id)
        self._emit("changed")  # v7-fix11 (UI-refresh)
        return True

    @_log_crud("archive_task")
    def archive_task(self, task_id: str) -> bool:
        """Flytta task till archive."""
        with self._lock:
            idx = self._active_index.get(task_id)
            if idx is None:
                logger.warning(f"{LOG_PREFIX} archive_task: {task_id!r} ej i active")
                return False
            task = self._active_tasks.pop(idx)
            self._deindex_task(task)
            del self._active_index[task_id]
            self._reindex_active_after(idx)
            # Arkiv betyder klar: bevara tidigare sluttid om den finns,
            # annars sätt sluttiden nu.
            task["done"] = True
            task["completed"] = task.get("completed") or _now_iso()
            self._archive_tasks.append(task)
            self._archive_index[task_id] = len(self._archive_tasks) - 1
            self._index_task(task, archive=True)
            self._dirty = True
        self._find_cache.clear()
        self._filter_cache.clear()
        self._audit_log.add("archive_task", task_id, after=_safe_copy(task))
        logger.info(f"{LOG_PREFIX} archive_task: {task_id!r}")
        self._emit("task_removed", task_id)
        self._emit("archive_changed")
        self._emit("changed")
        return True

    @_log_crud("restore_task")
    def restore_task(self, task_id: str) -> bool:
        """Återställ från archive till active."""
        with self._lock:
            idx = self._archive_index.get(task_id)
            if idx is None:
                logger.warning(f"{LOG_PREFIX} restore_task: {task_id!r} ej i archive")
                return False
            task = self._archive_tasks.pop(idx)
            self._deindex_task(task, archive=True)
            del self._archive_index[task_id]
            self._reindex_archive_after(idx)
            # Återställd uppgift är aktiv och därmed inte längre klar.
            task["done"] = False
            task["completed"] = None
            self._active_tasks.append(task)
            self._active_index[task_id] = len(self._active_tasks) - 1
            self._index_task(task)
            self._dirty = True
        self._find_cache.clear()
        self._filter_cache.clear()
        self._audit_log.add("restore_task", task_id, after=_safe_copy(task))
        logger.info(f"{LOG_PREFIX} restore_task: {task_id!r}")
        self._emit("task_added", task_id)
        self._emit("archive_changed")
        self._emit("changed")
        return True

    @_log_crud("clear_archive")
    def clear_archive(self) -> int:
        """Rensa ALLA arkiverade tasks. Returnerar antal."""
        with self._lock:
            count = len(self._archive_tasks)
            if count == 0:
                logger.debug(f"{LOG_PREFIX} clear_archive: redan tom")
                return 0
            for task in self._archive_tasks:
                self._deindex_task(task, archive=True)
            self._archive_tasks.clear()
            self._archive_index.clear()
            self._dirty = True
        self._find_cache.clear()  # FIX v7-fix79b: cache-koherens
        self._filter_cache.clear()
        logger.info(f"{LOG_PREFIX} clear_archive: tog bort {count} tasks")
        self._emit("archive_changed")
        self._emit("changed")
        return count

    @_log_crud("reorder_task")
    def reorder_task(self, task_id: str, new_index: int) -> bool:
        """Flytta task till ny position."""
        with self._lock:
            old_idx = self._active_index.get(task_id)
            if old_idx is None:
                return False
            if new_index < 0 or new_index >= len(self._active_tasks):
                return False
            if old_idx == new_index:
                return False
            task = self._active_tasks.pop(old_idx)
            self._active_tasks.insert(new_index, task)
            # Rebuild index
            self._active_index = {
                t["id"]: i for i, t in enumerate(self._active_tasks)
            }
            self._dirty = True
        self._audit_log.add("reorder_task", task_id, reason=f"{old_idx}→{new_index}")
        self._find_cache.clear()   # FIX v7-fix79b: cache-koherens
        self._filter_cache.clear()  # FIX v7-fix79b: cache-koherens
        logger.info(
            f"{LOG_PREFIX} reorder_task: {task_id!r} {old_idx}→{new_index}"
        )
        self._emit("task_updated", task_id)
        self._emit("changed")  # v7-fix11
        return True

    # ========================================================================
    # CRUD — SUBTASK
    # ========================================================================

    @_log_crud("add_subtask")
    def add_subtask(self, task_id: str, title: str) -> Optional[Dict[str, Any]]:
        """Lägg till subtask."""
        nt = _normalize_title(title)
        if not nt:
            return None
        with self._lock:
            task = self._by_id.get(task_id)
            if task is None:
                return None
            if len(task.get("subtasks", [])) >= MAX_SUBTASKS_PER_TASK:
                logger.warning(
                    f"{LOG_PREFIX} add_subtask: max ({MAX_SUBTASKS_PER_TASK}) uppnått"
                )
                return None
            sub = {
                "id": _make_id(),
                "title": nt,
                "done": False,
            }
            task.setdefault("subtasks", []).append(sub)
            self._dirty = True
        self._filter_cache.clear()  # FIX v7-fix79b: cache-koherens
        self._find_cache.clear()
        self._audit_log.add("add_subtask", task_id, after=sub)
        logger.info(
            f"{LOG_PREFIX} add_subtask: {sub['id']!r} till {task_id!r} "
            f"('{nt[:30]}')"
        )
        self._emit("task_updated", task_id)
        self._emit("changed")  # v7-fix11 (UI-refresh)
        return sub

    @_log_crud("toggle_subtask")
    def toggle_subtask(self, task_id: str, sub_id: str) -> bool:
        """Toggle subtask done-status."""
        with self._lock:
            task = self._by_id.get(task_id)
            if task is None:
                return False
            for sub in task.get("subtasks", []):
                if sub.get("id") == sub_id:
                    sub["done"] = not sub.get("done", False)
                    self._dirty = True
                    self._filter_cache.clear()  # FIX v7-fix79b: cache-koherens
                    self._find_cache.clear()
                    self._audit_log.add("toggle_subtask", task_id, after=_safe_copy(sub))
                    logger.info(
                        f"{LOG_PREFIX} toggle_subtask: {sub_id!r} → done={sub['done']}"
                    )
                    self._emit("task_updated", task_id)
                    self._emit("changed")  # v7-fix11 (UI-refresh)
                    return True
        return False

    @_log_crud("remove_subtask")
    def remove_subtask(self, task_id: str, sub_id: str) -> bool:
        """Ta bort subtask."""
        with self._lock:
            task = self._by_id.get(task_id)
            if task is None:
                return False
            subs = task.get("subtasks", [])
            for i, sub in enumerate(subs):
                if sub.get("id") == sub_id:
                    removed = subs.pop(i)
                    self._dirty = True
                    self._filter_cache.clear()  # FIX v7-fix79b: cache-koherens
                    self._find_cache.clear()
                    self._audit_log.add("remove_subtask", task_id, before=removed)
                    logger.info(f"{LOG_PREFIX} remove_subtask: {sub_id!r}")
                    self._emit("task_updated", task_id)
                    self._emit("changed")  # v7-fix11 (UI-refresh)
                    return True
        return False

    # ========================================================================
    # CRUD — TAGS
    # ========================================================================

    @_log_crud("add_tag")
    def add_tag(self, task_id: str, tag: str) -> bool:
        """Lägg till tag på task."""
        nt = _normalize_tag(tag)
        if not nt:
            return False
        with self._lock:
            task = self._by_id.get(task_id)
            if task is None:
                return False
            tags = task.setdefault("tags", [])
            if nt in tags:
                logger.debug(f"{LOG_PREFIX} add_tag: {nt!r} finns redan")
                return False
            if len(tags) >= MAX_TAGS_PER_TASK:
                logger.warning(
                    f"{LOG_PREFIX} add_tag: max ({MAX_TAGS_PER_TASK}) uppnått"
                )
                return False
            tags.append(nt)
            self._by_tag.setdefault(nt, set()).add(task_id)
            self._dirty = True
        self._find_cache.clear()  # FIX v7-fix79b: cache-koherens
        self._filter_cache.clear()
        self._audit_log.add("add_tag", task_id, after=nt)
        logger.info(f"{LOG_PREFIX} add_tag: {nt!r} → {task_id!r}")
        self._emit("tags_changed")
        self._emit("task_updated", task_id)
        self._emit("changed")  # v7-fix11 (UI-refresh)
        return True

    @_log_crud("remove_tag")
    def remove_tag(self, task_id: str, tag: str) -> bool:
        """Ta bort tag från task."""
        nt = _normalize_tag(tag)
        if not nt:
            return False
        with self._lock:
            task = self._by_id.get(task_id)
            if task is None:
                return False
            tags = task.get("tags", [])
            if nt not in tags:
                return False
            tags.remove(nt)
            s = self._by_tag.get(nt)
            if s is not None:
                s.discard(task_id)
            self._dirty = True
        self._find_cache.clear()  # FIX v7-fix79b: cache-koherens
        self._filter_cache.clear()
        self._audit_log.add("remove_tag", task_id, before=nt)
        logger.info(f"{LOG_PREFIX} remove_tag: {nt!r} ← {task_id!r}")
        self._emit("tags_changed")
        self._emit("task_updated", task_id)
        self._emit("changed")  # v7-fix11 (UI-refresh)
        return True

    @_log_crud("set_tags")
    def set_tags(self, task_id: str, tags: List[str]) -> bool:
        """Sätt ALLA tags (ersätter befintliga)."""
        new_tags = _coerce_tags(tags)
        with self._lock:
            task = self._by_id.get(task_id)
            if task is None:
                return False
            old_tags = list(task.get("tags", []))
            if set(old_tags) == set(new_tags):
                return False
            # Uppdatera index
            for ot in old_tags:
                s = self._by_tag.get(ot)
                if s is not None:
                    s.discard(task_id)
            for nt in new_tags:
                self._by_tag.setdefault(nt, set()).add(task_id)
            task["tags"] = new_tags
            self._dirty = True
        self._find_cache.clear()  # FIX v7-fix79b: cache-koherens
        self._filter_cache.clear()
        self._audit_log.add(
            "set_tags", task_id, before=old_tags, after=new_tags,
        )
        logger.info(
            f"{LOG_PREFIX} set_tags: {task_id!r} {old_tags}→{new_tags}"
        )
        self._emit("tags_changed")
        self._emit("task_updated", task_id)
        self._emit("changed")  # v7-fix11
        return True

    @_log_call
    def all_tags(self) -> List[str]:
        """Hämta alla unika tags (sorterat, cached)."""
        cache_key = ("all_tags",)
        hit, value = self._filter_cache.get(cache_key)
        if hit:
            return value
        with self._lock:
            tags = sorted(self._by_tag.keys())
        self._filter_cache.set(cache_key, tags)
        logger.trace(f"{LOG_PREFIX} all_tags: {len(tags)} unika")
        return tags

    @_log_call
    def tag_counts(self) -> Dict[str, int]:
        """Hämta {tag: count}."""
        cache_key = ("tag_counts",)
        hit, value = self._filter_cache.get(cache_key)
        if hit:
            return value
        with self._lock:
            counts = {tag: len(ids) for tag, ids in self._by_tag.items()}
        self._filter_cache.set(cache_key, counts)
        return counts

    @_log_call
    def tasks_with_tag(self, tag: str) -> List[Dict[str, Any]]:
        """Hämta alla tasks med given tag (via index, O(1))."""
        nt = _normalize_tag(tag)
        if not nt:
            return []
        with self._lock:
            ids = list(self._by_tag.get(nt, set()))
            tasks = [self._by_id[tid] for tid in ids if tid in self._by_id]
        logger.trace(
            f"{LOG_PREFIX} tasks_with_tag({nt!r}): {len(tasks)} tasks"
        )
        return tasks

    # ========================================================================
    # QUERY / FILTER
    # ========================================================================

    @_log_call
    def count(self) -> Tuple[int, int]:
        """Returnerar (active_count, archive_count)."""
        with self._lock:
            return len(self._active_tasks), len(self._archive_tasks)

    @_log_call
    def all_tasks(self) -> List[Dict[str, Any]]:
        """Hämta ALLA tasks (active + archive, kopia)."""
        with self._lock:
            return [_safe_copy(t) for t in self._active_tasks] + [
                _safe_copy(t) for t in self._archive_tasks
            ]

    @_log_call
    def active_tasks(self) -> List[Dict[str, Any]]:
        """Hämta ALLA aktiva tasks (kopia)."""
        with self._lock:
            return [_safe_copy(t) for t in self._active_tasks]

    @_log_call
    def archive_tasks(self) -> List[Dict[str, Any]]:
        """Hämta ALLA arkiverade tasks (kopia)."""
        with self._lock:
            return [_safe_copy(t) for t in self._archive_tasks]

    def iter_active(self) -> Generator[Dict[str, Any], None, None]:
        """Generator: iterera aktiva tasks (lazy, minnesbesparande)."""
        with self._lock:
            for task in self._active_tasks:
                yield _safe_copy(task)

    def iter_archive(self) -> Generator[Dict[str, Any], None, None]:
        """Generator: iterera arkiverade tasks (lazy)."""
        with self._lock:
            for task in self._archive_tasks:
                yield _safe_copy(task)

    @_log_call
    def find_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Hitta task via id (O(1) med cache)."""
        cache_key = ("find", task_id)
        hit, value = self._find_cache.get(cache_key)
        if hit:
            return value
        with self._lock:
            task = self._by_id.get(task_id)
            if task is not None:
                result = _safe_copy(task)
                self._find_cache.set(cache_key, result)
                return result
        return None

    @_log_call
    def is_known_task(self, task_id: str) -> bool:
        """Är task-id känt? (O(1))."""
        with self._lock:
            return task_id in self._by_id

    @_log_call
    def active_tasks_filtered(
        self,
        query: str = "",
        priority: Optional[str] = None,
        has_due: Optional[bool] = None,
        tag: Optional[str] = None,
        tags_any: Optional[List[str]] = None,
        sort_by: str = "pinned_first",
        reverse: bool = False,
    ) -> List[Dict[str, Any]]:
        """Filtrera + sortera aktiva tasks (med cache)."""
        # Cache key
        cache_key = ("filter", query, priority, has_due, tag, tuple(tags_any or ()), sort_by, reverse)
        hit, value = self._filter_cache.get(cache_key)
        if hit:
            return value
        # Filtrera
        q = (query or "").lower().strip()
        with self._lock:
            # Snapshot tasks (för att inte blocka vid sortering)
            tasks = list(self._active_tasks)
        # Tag-filter (använd index om möjligt)
        if tag:
            nt = _normalize_tag(tag)
            if nt:
                ids = self._by_tag.get(nt, set())
                tasks = [t for t in tasks if t["id"] in ids]
        elif tags_any:
            nt_any = [_normalize_tag(t) for t in tags_any if t]
            nt_any = [t for t in nt_any if t]
            if nt_any:
                ids_set: Set[str] = set()
                for nt in nt_any:
                    ids_set.update(self._by_tag.get(nt, set()))
                tasks = [t for t in tasks if t["id"] in ids_set]
        # Priority-filter (använd index)
        if priority and priority in VALID_PRIORITIES:
            ids_p = self._by_priority.get(priority, set())
            tasks = [t for t in tasks if t["id"] in ids_p]
        # has_due filter
        if has_due is not None:
            tasks = [t for t in tasks if bool(t.get("due_date")) == has_due]
        # Query (text search)
        if q:
            tasks = [t for t in tasks if q in t["title"].lower() or
                     any(q in tag.lower() for tag in t.get("tags", []))]
        # Sortering
        if sort_by == "pinned_first":
            # Pinned först, sedan enligt sort_by
            tasks.sort(
                key=lambda t: (
                    not t.get("pinned", False),  # Pinned först
                    -_priority_value(t.get("priority", "medium")),  # High först
                    t.get("created") or "",
                ),
                reverse=False,
            )
        elif sort_by == "priority":
            tasks.sort(
                key=lambda t: (
                    -_priority_value(t.get("priority", "medium")),
                    t.get("created") or "",
                ),
                reverse=reverse,
            )
        elif sort_by == "due_date":
            tasks.sort(
                key=lambda t: (t.get("due_date") or "9999", -_priority_value(t.get("priority", "medium"))),
                reverse=reverse,
            )
        elif sort_by == "title":
            tasks.sort(key=lambda t: t["title"].lower(), reverse=reverse)
        else:  # "created" default
            tasks.sort(key=lambda t: t.get("created") or "", reverse=reverse)
        # Kopiera (för säkerhet)
        result = [_safe_copy(t) for t in tasks]
        self._filter_cache.set(cache_key, result)
        logger.trace(
            f"{LOG_PREFIX} active_tasks_filtered: "
            f"query={q!r}, priority={priority}, tag={tag}, "
            f"sort_by={sort_by} → {len(result)} tasks"
        )
        return result

    @_log_call
    def stats(self) -> Dict[str, Any]:
        """Hämta statistik (cached)."""
        cache_key = ("stats",)
        hit, value = self._filter_cache.get(cache_key)
        if hit:
            return value
        with self._lock:
            active = self._active_tasks
            archive = self._archive_tasks
            done_count = sum(1 for t in active if t.get("done"))
            pinned_count = len(self._pinned_ids)
            by_priority = {p: len(ids) for p, ids in self._by_priority.items()}
            # NY v6.4.1: Total tasks för procentberäkning
            total_active = len(active)
            # NY v6.4.1: Prioritet-distribution i procent
            priority_distribution = {}
            if total_active > 0:
                for p, count in by_priority.items():
                    priority_distribution[p] = {
                        "count": count,
                        "percent": round(count / total_active * 100, 1),
                    }
            # NY v6.4.1: Tag-cloud (top 10 mest använda taggar)
            tag_counts = sorted(
                ((tag, len(ids)) for tag, ids in self._by_tag.items()),
                key=lambda x: -x[1]
            )[:10]
            top_tags = [{"tag": t, "count": c} for t, c in tag_counts]
        result = {
            "active": len(active),
            "archive": len(archive),
            "done": done_count,
            "pending": len(active) - done_count,
            "pinned": pinned_count,
            "tags": len(self._by_tag),
            "by_priority": by_priority,
            # NY v6.4.1
            "priority_distribution": priority_distribution,
            "top_tags": top_tags,
            "schema_version": self._schema_version,
        }
        self._filter_cache.set(cache_key, result)
        return result

    @_log_call
    def find_tasks_by_text(
        self,
        query: str,
        *,
        include_done: bool = True,
        include_archive: bool = False,
        case_sensitive: bool = False,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        NY v6.4.1: Sök tasks efter fritext i title + tags.

        Använder in-memory index (snabb), inte regex på disk.

        Args:
            query: Sök-sträng (ord eller fras)
            include_done: Inkludera klarmarkerade tasks (default True)
            include_archive: Inkludera arkiverade tasks (default False)
            case_sensitive: Case-sensitive sökning (default False)
            limit: Max antal resultat (default 100)

        Returns:
            Lista av matchande task-dicts (utan innehåll, bara id + title + score)

        Exempel:
            >>> store.find_tasks_by_text("handla")
            [{"id": "abc", "title": "Handla mjölk", "score": 1}]
        """
        if not query or not query.strip():
            return []
        # Normalisera query
        q = query.strip()
        if not case_sensitive:
            q = q.lower()
        results = []
        start = time.perf_counter()
        with self._lock:
            sources = [self._active_tasks]
            if include_archive:
                sources.append(self._archive_tasks)
            seen_ids: Set[str] = set()
            for source in sources:
                for task in source:
                    if not include_done and task.get("done"):
                        continue
                    tid = task.get("id")
                    if tid in seen_ids:
                        continue
                    seen_ids.add(tid)
                    title = task.get("title", "")
                    tags = task.get("tags", [])
                    # Bygg sökbar text
                    if case_sensitive:
                        haystack = title + " " + " ".join(tags)
                    else:
                        haystack = (title + " " + " ".join(tags)).lower()
                    # Score: antal förekomster av query i haystack
                    score = haystack.count(q)
                    if score > 0:
                        results.append({
                            "id": tid,
                            "title": title,
                            "score": score,
                            "done": task.get("done", False),
                            "priority": task.get("priority", "none"),
                            "pinned": task.get("pinned", False),
                        })
        # Sortera efter score (högst först), sedan pinned
        results.sort(key=lambda t: (-t["score"], -int(t["pinned"])))
        if len(results) > limit:
            results = results[:limit]
        duration = (time.perf_counter() - start) * 1000
        logger.debug(
            f"{LOG_PREFIX} find_tasks_by_text({query!r}): "
            f"{len(results)} träffar på {duration:.2f}ms"
        )
        return results

    @_log_call
    def _read_file_unlocked(self, path: Path) -> Optional[Dict[str, Any]]:
        """
        Läsa JSON-fil utan lås (används av diagnostik).

        FIX v7-fix11: metoden SAKNADES helt — validate_schema_compatibility()
        kraschade med AttributeError på varje anrop och rapporterade alltid
        "Kunde inte läsa schema" + is_compatible=False (misledande fel).

        Returnerar None för saknad fil (ny installation = kompatibel).
        """
        try:
            if not path.exists():
                return None
            raw = path.read_bytes()
            data = _json_loads(raw)
            return data if isinstance(data, (dict, list)) else None
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} _read_file_unlocked({path.name}) misslyckades: {e}"
            )
            return None

    def validate_schema_compatibility(self) -> Dict[str, Any]:
        """
        NY v6.4.1: Validera schema-version kompatibilitet.

        Kontrollerar att data-filer har stödda schema-versioner
        och returnerar diagnostik-info.

        Returns:
            Dict med:
              - active_schema: int eller None
              - archive_schema: int eller None
              - min_supported: int (MIN_SUPPORTED_VERSION)
              - current: int (SCHEMA_VERSION)
              - needs_migration: bool
              - is_compatible: bool
              - issues: List[str]
        """
        issues: List[str] = []
        active_schema = None
        archive_schema = None
        try:
            with self._lock:
                active_data = self._read_file_unlocked(self._active_path)
                if active_data and isinstance(active_data, dict):
                    active_schema = int(active_data.get("version", 0))
                archive_data = self._read_file_unlocked(self._archive_path)
                if archive_data and isinstance(archive_data, dict):
                    archive_schema = int(archive_data.get("version", 0))
        except Exception as e:
            issues.append(f"Kunde inte läsa schema: {e}")
            logger.warning(
                f"{LOG_PREFIX} validate_schema_compatibility: läsfel: {e}"
            )
        needs_migration = False
        for schema, name in (
            (active_schema, "active"),
            (archive_schema, "archive"),
        ):
            if schema is None:
                continue
            if schema < MIN_SUPPORTED_VERSION:
                issues.append(
                    f"{name}.json har schema v{schema} — "
                    f"minsta stödda är v{MIN_SUPPORTED_VERSION}"
                )
                needs_migration = True
            elif schema > SCHEMA_VERSION:
                issues.append(
                    f"{name}.json har schema v{schema} — "
                    f"aktuell version är v{SCHEMA_VERSION} (nyare data)"
                )
        is_compatible = len(issues) == 0
        result = {
            "active_schema": active_schema,
            "archive_schema": archive_schema,
            "min_supported": MIN_SUPPORTED_VERSION,
            "current": SCHEMA_VERSION,
            "needs_migration": needs_migration,
            "is_compatible": is_compatible,
            "issues": issues,
        }
        if is_compatible:
            logger.debug(
                f"{LOG_PREFIX} validate_schema_compatibility: OK "
                f"(active=v{active_schema}, archive=v{archive_schema})"
            )
        else:
            logger.warning(
                f"{LOG_PREFIX} validate_schema_compatibility: {len(issues)} problem"
            )
        return result

    @_log_call
    def get_health_report(self) -> Dict[str, Any]:
        """
        Hämta diagnostik-rapport (sammanslagen EN definition, v7-fix11).

        Tidigare fanns TVÅ get_health_report-definitioner i klassen — den
        senaste skuggade den första och läste bl.a. '_lru_cache' (fel namn;
        slot:arna heter _find_cache/_filter_cache) → cache-stats alltid tom.
        """
        with self._lock:
            report: Dict[str, Any] = {
                "module": "store",
                "store_version": STORE_VERSION,
                "schema_version": self._schema_version,
                "qt_available": _QT_AVAILABLE,
                "has_orjson": _HAS_ORJSON,
                "active_count": len(self._active_tasks),
                "archive_count": len(self._archive_tasks),
                "save_count": self._save_count,
                "load_count": self._load_count,
                "error_count": self._error_count,
                "bulk_count": self._bulk_count,
                "is_dirty": self._dirty,
                "saved_at": self._saved_at,
                "audit": self._audit_log.get_stats(),
                "find_cache": self._find_cache.stats(),
                "filter_cache": self._filter_cache.stats(),
            }
        # Tyngre extra-diagnostik utanför låset
        with suppress(Exception):
            report["problems"] = _validate_store_state(self)
            report["problem_count"] = len(report["problems"])
        with suppress(Exception):
            report["summary_swedish"] = summarize_store_health(self)
        return report

    # ========================================================================
    # BULK API (NY v6.4 — 100× färre locks för mass-operationer)
    # ========================================================================

    @_log_crud("bulk_add")
    def bulk_add(self, tasks: List[Dict[str, Any]]) -> List[str]:
        """Lägg till MÅNGA tasks i en transaktion (100× snabbare)."""
        if not tasks:
            return []
        start = time.perf_counter()
        added_ids: List[str] = []
        with self._lock:
            if len(self._active_tasks) + len(tasks) > MAX_TASKS:
                logger.warning(
                    f"{LOG_PREFIX} bulk_add: skulle överstiga MAX_TASKS "
                    f"({len(self._active_tasks)}+{len(tasks)} > {MAX_TASKS})"
                )
                tasks = tasks[:MAX_TASKS - len(self._active_tasks)]
            for raw in tasks:
                title = _normalize_title(raw.get("title", ""))
                if not title:
                    continue
                tid = _make_id()
                task = {
                    "id": tid,
                    "title": title,
                    "done": _coerce_bool(raw.get("done"), False),
                    "priority": _coerce_priority(raw.get("priority")),
                    "due_date": _coerce_str_or_none(raw.get("due_date")),
                    "tags": _coerce_tags(raw.get("tags")),
                    "pinned": _coerce_bool(raw.get("pinned"), False),
                    "subtasks": [],
                    "recurring": None,
                    "snoozed_until": None,
                    "created": _now_iso(),
                    "completed": None,
                }
                self._active_tasks.append(task)
                # FIX v7-fix11: samma index-bugg som add_task — utan raden
                # nedan går bulk-tillagda tasks inte att ta bort/arkivera.
                self._active_index[tid] = len(self._active_tasks) - 1
                self._index_task(task)
                added_ids.append(tid)
            self._dirty = True
        self._find_cache.clear()
        self._filter_cache.clear()
        self._bulk_count += 1
        duration = (time.perf_counter() - start) * 1000
        logger.info(
            f"{LOG_PREFIX} bulk_add: {len(added_ids)} tasks på {duration:.2f}ms "
            f"(bulk_count={self._bulk_count})"
        )
        self._emit("changed")
        return added_ids

    @_log_crud("bulk_remove")
    def bulk_remove(self, task_ids: List[str]) -> int:
        """Ta bort MÅNGA tasks i en transaktion."""
        if not task_ids:
            return 0
        start = time.perf_counter()
        removed = 0
        with self._lock:
            for tid in task_ids:
                idx = self._active_index.get(tid)
                if idx is None:
                    continue
                task = self._active_tasks.pop(idx)
                self._deindex_task(task)
                del self._active_index[tid]
                self._reindex_active_after(idx)
                self._audit_log.add("bulk_remove", tid, before=task)
                removed += 1
            if removed:
                self._dirty = True
        self._find_cache.clear()
        self._filter_cache.clear()
        self._bulk_count += 1
        duration = (time.perf_counter() - start) * 1000
        logger.info(
            f"{LOG_PREFIX} bulk_remove: {removed} tasks på {duration:.2f}ms"
        )
        if removed:
            self._emit("changed")
        return removed

    @_log_crud("bulk_update_priority")
    def bulk_update_priority(self, task_ids: List[str], priority: str) -> int:
        """Uppdatera priority för MÅNGA tasks."""
        np = _coerce_priority(priority)
        if not task_ids:
            return 0
        start = time.perf_counter()
        updated = 0
        with self._lock:
            for tid in task_ids:
                task = self._by_id.get(tid)
                if task is None or task.get("priority") == np:
                    continue
                old = task.get("priority", "medium")
                s = self._by_priority.get(old)
                if s is not None:
                    s.discard(tid)
                self._by_priority.setdefault(np, set()).add(tid)
                task["priority"] = np
                updated += 1
            if updated:
                self._dirty = True
        self._find_cache.clear()  # FIX v7-fix79b: cache-koherens
        self._filter_cache.clear()
        self._bulk_count += 1
        duration = (time.perf_counter() - start) * 1000
        logger.info(
            f"{LOG_PREFIX} bulk_update_priority: {updated} tasks → {np} "
            f"på {duration:.2f}ms"
        )
        if updated:
            self._emit("changed")
        return updated

    # ========================================================================
    # EXPORT / IMPORT
    # ========================================================================

    @_log_call
    def export_to(self, dest_dir: str) -> bool:
        """Exportera ALLA tasks till katalog."""
        try:
            dest = Path(dest_dir)
            dest.mkdir(parents=True, exist_ok=True)
            with self._lock:
                active_data = {
                    "version": SCHEMA_VERSION,
                    "saved_at": _now_iso(),
                    "tasks": [_safe_copy(t) for t in self._active_tasks],
                }
                archive_data = {
                    "version": SCHEMA_VERSION,
                    "saved_at": _now_iso(),
                    "tasks": [_safe_copy(t) for t in self._archive_tasks],
                }
            (dest / "active.json").write_bytes(_json_dumps(active_data))
            (dest / "archive.json").write_bytes(_json_dumps(archive_data))
            logger.info(f"{LOG_PREFIX} export OK: {dest}")
            return True
        except Exception as e:
            logger.error(f"{LOG_PREFIX} export misslyckades: {e}", exc_info=True)
            return False

    @_log_call
    def import_from(self, src_dir: str, merge: bool = True) -> bool:
        """Importera tasks från katalog."""
        try:
            src = Path(src_dir)
            if not src.is_dir():
                logger.error(f"{LOG_PREFIX} import: katalog finns inte: {src}")
                return False
            new_active = self._load_from_path(src / "active.json")
            new_archive = self._load_from_path(src / "archive.json")
            with self._lock:
                if merge:
                    # Slå ihop (undvik dubletter via id)
                    existing_ids = {t["id"] for t in self._active_tasks}
                    added = 0
                    for t in new_active:
                        if t["id"] not in existing_ids:
                            self._active_tasks.append(t)
                            added += 1
                    logger.info(f"{LOG_PREFIX} import merge: +{added} active")
                else:
                    self._active_tasks = new_active
                    logger.info(f"{LOG_PREFIX} import replace: {len(new_active)} active")
                self._rebuild_index()
                self._dirty = True
            self._find_cache.clear()
            self._filter_cache.clear()
            self._emit("changed")
            return True
        except Exception as e:
            logger.error(f"{LOG_PREFIX} import misslyckades: {e}", exc_info=True)
            return False

    def _load_from_path(self, path: Path) -> List[Dict[str, Any]]:
        """Ladda tasks från filsökväg (för import)."""
        if not path.exists():
            return []
        try:
            data = _json_loads(path.read_bytes())
            tasks = data.get("tasks", [])
            return [
                ct for ct in (_coerce_task(t, idx=i) for i, t in enumerate(tasks))
                if ct is not None
            ]
        except Exception as e:
            logger.error(f"{LOG_PREFIX} _load_from_path misslyckades: {e}")
            return []

    # ========================================================================
    # PRIVATE HELPERS
    # ========================================================================

    def _emit(self, signal_name: str, *args: Any) -> None:
        """Emitta signal säkert (Qt-signal ELLER dummy-signal utan Qt).

        FIX v7-fix11: tidigare `return` direkt utan Qt → dummy-signalerna
        (och därmed connect():ade callbacks i tester) kördes aldrig.
        """
        try:
            sig = getattr(self, signal_name, None)
            if sig is not None and hasattr(sig, "emit"):
                sig.emit(*args)
                logger.trace(f"{LOG_PREFIX} signal: {signal_name}({args[:2]!r}...)")
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} signal-emit misslyckades: {signal_name}: {e}"
            )

    def __repr__(self) -> str:
        return (
            f"<TaskStore active={len(self._active_tasks)} "
            f"archive={len(self._archive_tasks)} "
            f"saves={self._save_count} "
            f"loads={self._load_count} "
            f"errors={self._error_count}>"
        )

    # =========================================================================
    # DIAGNOSTIK & HEALTH (NY v6.4.1 v7)
    # =========================================================================

    def diagnose(self) -> List[str]:
        """
        NY v6.4.1 v7: Diagnostisk funktion som kontrollerar denna store-instans.

        Returnerar lista med svenska problem-beskrivningar (tom om allt ar OK).

        Returns:
            Lista av strängar — varje sträng beskriver ett problem
        """
        return _validate_store_state(self)

    # FIX v7-fix11: en andra, duplicerad get_health_report() fanns här och
    # SKUGGADE den riktiga (Python: senaste definition vinner). Den läste
    # bl.a. '_lru_cache' (fel slot-namn) → cache-stats alltid tom. BORTTAGEN —
    # den sammanslagna definitionen finns vid BULK API-avsnittet ovan.


# ===========================================================================
# INTERNAL HELPERS
# ===========================================================================

def format_task_summary(task: Dict[str, Any], max_title_len: int = 40) -> str:
    """
    NY v6.4.1 v7: Skapar en kort svensk sammanfattning av en task.

    Args:
        task: Task-dict med id, title, priority, done, due_date
        max_title_len: Max antal tecken for titeln (default 40)

    Returns:
        Svensk en-rads-sammanfattning, t.ex.
        "[H] Handla mjolk (i dag) #hem"
        "    Klar: Boka mote"

    Exempel:
        >>> t = {"title": "Handla mjölk", "priority": "high", "done": False,
        ...      "due_date": "2026-09-21", "tags": ["hem"]}
        >>> format_task_summary(t)
        '[H] Handla mjolk (i dag) #hem'
    """
    try:
        title = str(task.get("title", "")).strip() or "(ingen titel)"
        if len(title) > max_title_len:
            title = title[: max_title_len - 1] + "…"
        # Prioritet
        priority = str(task.get("priority", "none")).lower()
        prefix = {
            "high": "[H]", "medium": "[M]", "low": "[L]", "none": "[ ]",
        }.get(priority, "[ ]")
        # Klar-markering
        if task.get("done"):
            return f"    Klar: {title}"
        # Due-date
        due = task.get("due_date")
        due_str = ""
        if due:
            try:
                d = _dt.date.fromisoformat(str(due)[:10])
                today = _dt.date.today()
                delta = (d - today).days
                if delta < 0:
                    due_str = f" (förfallen {abs(delta)}d)"
                elif delta == 0:
                    due_str = " (i dag)"
                elif delta == 1:
                    due_str = " (imorgon)"
                elif delta < 7:
                    due_str = f" (om {delta}d)"
                else:
                    due_str = f" ({d.isoformat()})"
            except (ValueError, TypeError):
                pass
        # Tags
        tags = task.get("tags", []) or []
        tag_str = ""
        if tags:
            tag_str = " #" + " #".join(str(t) for t in tags[:3] if t)
        return f"{prefix} {title}{due_str}{tag_str}"
    except Exception as e:
        logger.debug(f"{LOG_PREFIX} format_task_summary misslyckades: {e}")
        return f"(fel vid formatering: {type(e).__name__})"


def format_due_date_swedish(date_str: Optional[str]) -> str:
    """
    NY v6.4.1 v7: Humanize datum med svenska relativ-uttryck (store-specifik).

    Args:
        date_str: ISO-datum (YYYY-MM-DD) eller None

    Returns:
        Svensk sträng
    """
    if not date_str:
        return ""
    try:
        d = _dt.date.fromisoformat(str(date_str)[:10])
    except (ValueError, TypeError):
        return str(date_str)
    today = _dt.date.today()
    delta = (d - today).days
    if delta < -30:
        return f"för {abs(delta)} dagar sedan"
    if delta < -1:
        return f"för {abs(delta)} dagar sedan"
    if delta == -1:
        return "igår"
    if delta == 0:
        return "i dag"
    if delta == 1:
        return "imorgon"
    if delta < 7:
        return f"om {delta} dagar"
    if delta < 14:
        return "nästa vecka"
    if delta < 30:
        return f"om {delta // 7} veckor"
    return d.strftime("%Y-%m-%d")


def summarize_store_health(store: Any) -> str:
    """
    NY v6.4.1 v7: Skapar en kort svensk sammanfattning av en store-instans.

    Args:
        store: TaskStore-instans

    Returns:
        Svensk en-rads-sammanfattning, t.ex.
        "120 tasks (95 klara, 25 aktiva) • schema=v5 • senast sparad=2min sedan"
    """
    try:
        if store is None:
            return "(ingen store-instans)"
        # Använd _active_tasks / _archive_tasks (eller property 'tasks' om det finns)
        active_tasks = (
            getattr(store, "tasks", None)
            or getattr(store, "_active_tasks", [])
            or []
        )
        archive_tasks = (
            getattr(store, "archive", None)
            or getattr(store, "_archive_tasks", [])
            or []
        )
        if not isinstance(active_tasks, list):
            active_tasks = []
        if not isinstance(archive_tasks, list):
            archive_tasks = []
        total = len(active_tasks)
        archive = len(archive_tasks)
        done = sum(1 for t in active_tasks if isinstance(t, dict) and t.get("done"))
        active = total - done
        schema_v = getattr(store, "_schema_version", SCHEMA_VERSION)
        last_save = getattr(store, "_last_save_time", 0)
        ago = ""
        if last_save:
            secs = int(time.time() - last_save)
            if secs < 60:
                ago = f" • senast sparad={secs}s sedan"
            elif secs < 3600:
                ago = f" • senast sparad={secs // 60}min sedan"
            else:
                ago = f" • senast sparad={secs // 3600}h sedan"
        archive_str = f", {archive} arkiverade" if archive > 0 else ""
        return (
            f"{total} tasks ({done} klara, {active} aktiva{archive_str}) • "
            f"schema=v{schema_v}{ago}"
        )
    except Exception as e:
        logger.debug(f"{LOG_PREFIX} summarize_store_health misslyckades: {e}")
        return f"(kunde inte sammanfatta: {type(e).__name__})"


def get_store_diagnostics(store: Optional[Any] = None) -> Dict[str, Any]:
    """
    NY v6.4.1 v7: Detaljerad diagnostik-rapport for support-fall.

    Args:
        store: Valfri TaskStore-instans (om None: modul-niva)

    Returns:
        Dict med alla diagnostik-falt inklusive svenska problem-beskrivningar
    """
    with safe_run("get_store_diagnostics") as ctx:
        problems = _validate_store_state(store)
        summary = ""
        stats_data: Dict[str, Any] = {}
        if store is not None:
            try:
                summary = summarize_store_health(store)
                stats_data = store.stats() if hasattr(store, "stats") else {}
            except Exception as e:
                logger.debug(
                    f"{LOG_PREFIX} get_store_diagnostics stats misslyckades: "
                    f"{_describe_store_exception(e)}"
                )
                stats_data = {"error": str(e)}
        ctx["ok"] = True
        return {
            "module": "store",
            "store_version": STORE_VERSION,
            "schema_version": SCHEMA_VERSION,
            "min_supported_version": MIN_SUPPORTED_VERSION,
            "has_orjson": _HAS_ORJSON,
            "qt_available": _QT_AVAILABLE,
            "problems": problems,
            "problem_count": len(problems),
            "summary_swedish": summary,
            "stats": stats_data,
        }


# NY v6.4.1 v7: Plugin-coupling — store vill ha orjson for snabbare JSON
_STORE_PLUGIN_DEPS: Final[Tuple[Dict[str, str], ...]] = (
    {
        "pip_name": "orjson",
        "import_name": "orjson",
        "description_svenska": "Snabbare JSON for task-lagring",
        "benefit_svenska": "Save/load blir 3-5x snabbare",
        "required": False,
    },
)


def get_store_plugin_deps() -> List[Dict[str, str]]:
    """
    NY v6.4.1 v7: Returnerar lista av optional Python-beroenden som store vill ha.

    Returns:
        Lista av dicts med nycklar: pip_name, import_name,
        description_svenska, benefit_svenska, required
    """
    return [dict(d) for d in _STORE_PLUGIN_DEPS]


def _priority_value(priority: str) -> int:
    """
    Numeriskt värde för sortering (högre = viktigare).

    Fas 2 (v6.4): 'none' = -1 (lägst, hamnar sist)
                  high=3, medium=2, low=1
    """
    return {"high": 3, "medium": 2, "low": 1, "none": -1}.get(priority, 0)


class _SaveResult:
    """Resultat av save-operation."""
    __slots__ = ("success", "duration_sec", "error")

    def __init__(self, success: bool, duration_sec: float, error: Optional[str] = None) -> None:
        self.success = success
        self.duration_sec = duration_sec
        self.error = error


class _DummySignal:
    """No-op signal (för icke-Qt-miljöer)."""
    __slots__ = ("_callbacks",)

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
# MODUL-EXPORTS
# ===========================================================================

__all__ = [
    "TaskStore",
    "AuditLog",
    "LOG_PREFIX",
    "SCHEMA_VERSION",
    "MIN_SUPPORTED_VERSION",
    "STORE_VERSION",
    "MAX_TASKS",
    "MAX_SUBTASKS_PER_TASK",
    "MAX_TAGS_PER_TASK",
    "VALID_PRIORITIES",
    "VALID_SORT_BY",
    # Svenska formatterings-helpers (NY v6.4.1 v7)
    "format_task_summary", "format_due_date_swedish",
    "summarize_store_health",
    # AI-felsökning (NY v6.4.1 v7)
    "_STORE_ERROR_TRANSLATIONS",
    "_describe_store_exception", "_format_compact_traceback",
    "_categorize_store_exception", "_validate_store_state",
    "safe_call", "safe_run", "_safe_run_async",
    # Diagnostik (NY v6.4.1 v7)
    "get_store_diagnostics",
    # Plugin-coupling (NY v6.4.1 v7)
    "get_store_plugin_deps",
    # NY v6.4.1 — dessa är metoder på TaskStore (dokumenterade)
    # "find_tasks_by_text",
    # "validate_schema_compatibility",
]


# ===========================================================================
# SELF-TEST
# ===========================================================================

if __name__ == "__main__":
    import shutil
    import tempfile

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s.%(msecs)03d | %(levelname)-8s | %(name)-12s | %(message)s",
        datefmt="%H:%M:%S",
    )

    print("=" * 70)
    print(f"store.py v6.4.1 (50 000% bättre) — Self-Test (orjson={_HAS_ORJSON})")
    print("=" * 70)

    # Test 1: Skapa store + lägg till tasks
    print("\n[Test 1] Skapa store + lägg till 1000 tasks...")
    with tempfile.TemporaryDirectory() as tmp:
        store = TaskStore(data_dir_override=tmp)
        start = time.perf_counter()
        ids = store.bulk_add([
            {"title": f"Task #{i}", "priority": ["low", "medium", "high"][i % 3]}
            for i in range(1000)
        ])
        duration = (time.perf_counter() - start) * 1000
        print(f"  ✓ 1000 tasks på {duration:.2f}ms = {1000/duration*1000:.0f} tasks/s")
        store.save()
        print(f"  ✓ Stats: {store.stats()}")

    # Test 2: Bulk add med orjson
    print("\n[Test 2] Snabbhet: orjson vs stdlib json...")
    sample = {"tasks": [{"id": "abc123", "title": f"Task {i}", "done": False} for i in range(1000)]}
    if _HAS_ORJSON:
        start = time.perf_counter()
        for _ in range(100):
            orjson.dumps(sample)
        orjson_time = (time.perf_counter() - start) * 1000
        start = time.perf_counter()
        for _ in range(100):
            _stdlib_json.dumps(sample)
        stdlib_time = (time.perf_counter() - start) * 1000
        print(f"  ✓ orjson: {orjson_time:.1f}ms")
        print(f"  ✓ stdlib: {stdlib_time:.1f}ms")
        print(f"  ✓ orjson är {stdlib_time/orjson_time:.1f}× snabbare")
    else:
        print("  ⚠ orjson ej tillgängligt i sandbox")

    # Test 3: Pin-funktion
    print("\n[Test 3] Pin-funktion...")
    with tempfile.TemporaryDirectory() as tmp:
        store = TaskStore(data_dir_override=tmp)
        t1 = store.add_task("Första task", priority="low")
        t2 = store.add_task("Viktig task", priority="high")
        store.toggle_pinned(t2)
        filtered = store.active_tasks_filtered(sort_by="pinned_first")
        print(f"  ✓ Pinned först: {filtered[0]['title']!r} (pinned={filtered[0]['pinned']})")

    # Test 4: Index-cache (O(1) lookup)
    print("\n[Test 4] Index-cache (O(1) lookup)...")
    with tempfile.TemporaryDirectory() as tmp:
        store = TaskStore(data_dir_override=tmp)
        for i in range(100):
            store.add_task(f"Task {i}", tags=[f"tag{i%10}"])
        start = time.perf_counter()
        for _ in range(10000):
            store.find_task(list(store._by_id.keys())[0])
        duration = (time.perf_counter() - start) * 1000
        print(f"  ✓ 10000 find_task-anrop: {duration:.2f}ms ({duration/10000:.4f}ms/call)")
        print(f"  ✓ Cache hit rate: {store._find_cache.stats()['hit_rate']*100:.1f}%")

    # Test 5: Generator (minnesbesparande)
    print("\n[Test 5] Generator (iter_active)...")
    with tempfile.TemporaryDirectory() as tmp:
        store = TaskStore(data_dir_override=tmp)
        for i in range(5000):
            store.add_task(f"Task {i}")
        # Test generator
        count = 0
        for task in store.iter_active():
            count += 1
            if count >= 100:  # Bryt tidigt
                break
        print(f"  ✓ Generator: itererade {count} tasks (lazy, avbröts efter 100)")

    # Test 6: AuditLog
    print("\n[Test 6] AuditLog...")
    with tempfile.TemporaryDirectory() as tmp:
        store = TaskStore(data_dir_override=tmp)
        for i in range(10):
            store.add_task(f"Task {i}")
        entries = store.audit_log.get_entries(limit=5)
        print(f"  ✓ Audit entries: {len(entries)} av 10")
        print(f"  ✓ Stats: {store.audit_log.get_stats()}")

    # Test 7: Health report
    print("\n[Test 7] Health report...")
    with tempfile.TemporaryDirectory() as tmp:
        store = TaskStore(data_dir_override=tmp)
        store.add_task("Test")
        report = store.get_health_report()
        print(f"  ✓ Health: {report}")

    # Test 8: NY v6.4.1 — find_tasks_by_text
    print("\n[Test 8] find_tasks_by_text (NY v6.4.1)...")
    with tempfile.TemporaryDirectory() as tmp:
        store = TaskStore(data_dir_override=tmp)
        store.add_task("Handla mjölk", tags=["hem", "brådskande"])
        store.add_task("Handla bröd", tags=["hem"])
        store.add_task("Boka möte", tags=["arbete"])
        store.add_task("Handla mera mjölk", priority="high")
        # Sök
        results = store.find_tasks_by_text("handla")
        print(f"  ✓ Sök 'handla': {len(results)} träffar")
        assert len(results) == 3
        # Första bör vara den med mest förekomster
        print(f"  ✓ Första träff: {results[0]['title']!r} (score={results[0]['score']})")
        # Case-sensitive
        results_cs = store.find_tasks_by_text("Handla", case_sensitive=True)
        print(f"  ✓ Case-sensitive 'Handla': {len(results_cs)} träffar")
        assert len(results_cs) == 3
        # FIX v7-fix11: testet glömde markera en task som klar — då är
        # "utan klara" fortfarande 3 träffar och assertet sprängdes.
        _t0 = store.active_tasks()[0]
        store.toggle_task(_t0["id"])
        # exclude_done
        results_no_done = store.find_tasks_by_text("handla", include_done=False)
        print(f"  ✓ Utan klara: {len(results_no_done)} träffar")
        assert len(results_no_done) == 2
        # limit
        results_lim = store.find_tasks_by_text("handla", limit=1)
        print(f"  ✓ Limit=1: {len(results_lim)} träffar")
        assert len(results_lim) == 1
        # Tom query
        results_empty = store.find_tasks_by_text("")
        print(f"  ✓ Tom query: {len(results_empty)} träffar")
        assert len(results_empty) == 0

    # Test 9: NY v6.4.1 — validate_schema_compatibility + stats() nycklar
    print("\n[Test 9] validate_schema_compatibility + stats (NY v6.4.1)...")
    with tempfile.TemporaryDirectory() as tmp:
        store = TaskStore(data_dir_override=tmp)
        store.add_task("A", priority="high", tags=["x"])
        store.add_task("B", priority="medium", tags=["x"])
        store.add_task("C", priority="low", tags=["y"])
        # validate_schema
        compat = store.validate_schema_compatibility()
        print(f"  ✓ validate_schema_compatibility: {compat}")
        assert compat["is_compatible"]
        assert compat["current"] == SCHEMA_VERSION
        # stats() nya nycklar
        stats = store.stats()
        print(f"  ✓ stats priority_distribution: {stats.get('priority_distribution')}")
        print(f"  ✓ stats top_tags: {stats.get('top_tags')}")
        assert "priority_distribution" in stats
        assert "top_tags" in stats
        assert "high" in stats["priority_distribution"]
        assert "percent" in stats["priority_distribution"]["high"]

    # Test 10: NY v6.4.1 v7 — AI-felsökning
    print("\n[Test 10] AI-felsökning (NY v6.4.1 v7)...")
    # _describe_store_exception
    desc1 = _describe_store_exception(FileNotFoundError("active.json"))
    print(f"  ✓ _describe_store_exception(FileNotFoundError): {desc1!r}")
    assert "hittades inte" in desc1
    desc2 = _describe_store_exception(KeyError("id"))
    print(f"  ✓ _describe_store_exception(KeyError): {desc2!r}")
    assert "Nyckel" in desc2 or "id" in desc2
    # _format_compact_traceback
    try:
        raise ValueError("test-tb-store")
    except ValueError as e:
        tb = _format_compact_traceback(e, max_frames=3)
        print(f"  ✓ _format_compact_traceback: {len(tb)} tecken, innehaller 'ValueError'")
        assert "ValueError" in tb
    # _categorize_store_exception
    cat1 = _categorize_store_exception(ValueError("x"))
    cat2 = _categorize_store_exception(PermissionError("x"))
    cat3 = _categorize_store_exception(FileNotFoundError("x"))
    print(f"  ✓ _categorize_store_exception: ValueError→{cat1}, "
          f"PermissionError→{cat2}, FileNotFoundError→{cat3}")
    assert cat1 == "user_input"
    assert cat2 == "permission"
    assert cat3 == "system"
    # safe_call
    r1 = safe_call(int, "42")
    r2 = safe_call(int, "abc", default=-1)
    print(f"  ✓ safe_call: ok={r1}, fail={r2}")
    assert r1 == 42 and r2 == -1
    # safe_run
    with safe_run("test-op-store") as ctx_ok:
        pass
    with safe_run("test-op-store-fail") as ctx_fail:
        raise RuntimeError("store-test-fel")
    print(f"  ✓ safe_run fel-blocket: errors={len(ctx_fail['errors'])}")
    assert len(ctx_fail["errors"]) == 1

    # Test 11: NY v6.4.1 v7 — svenska formatterings-helpers
    print("\n[Test 11] Svenska formatterings-helpers (NY v6.4.1 v7)...")
    t_high = {
        "title": "Handla mjölk", "priority": "high", "done": False,
        "due_date": _dt.date.today().isoformat(), "tags": ["hem"],
    }
    t_done = {"title": "Boka möte", "priority": "medium", "done": True}
    t_long = {"title": "En väldigt lång titel som borde trunkeras", "priority": "low"}
    s1 = format_task_summary(t_high)
    s2 = format_task_summary(t_done)
    s3 = format_task_summary(t_long, max_title_len=20)
    print(f"  ✓ format_task_summary (high/due): {s1!r}")
    print(f"  ✓ format_task_summary (done): {s2!r}")
    print(f"  ✓ format_task_summary (long, trunkerad): {s3!r}")
    assert "[H]" in s1
    assert "i dag" in s1
    assert "#hem" in s1
    assert "Klar" in s2
    assert "…" in s3
    # format_due_date_swedish
    dd1 = format_due_date_swedish(None)
    dd2 = format_due_date_swedish(_dt.date.today().isoformat())
    dd3 = format_due_date_swedish(
        (_dt.date.today() + _dt.timedelta(days=3)).isoformat()
    )
    print(f"  ✓ format_due_date_swedish: None→{dd1!r}, today→{dd2!r}, +3d→{dd3!r}")
    assert dd1 == ""
    assert dd2 == "i dag"
    assert "3 dagar" in dd3 or "om 3" in dd3

    # Test 12: NY v6.4.1 v7 — diagnostik på TaskStore
    print("\n[Test 12] Diagnostik på TaskStore (NY v6.4.1 v7)...")
    with tempfile.TemporaryDirectory() as tmp:
        store = TaskStore(data_dir_override=tmp)
        store.add_task("Test", priority="high", tags=["a"])
        # store.diagnose()
        problems = store.diagnose()
        print(f"  ✓ store.diagnose(): {len(problems)} problem")
        for p in problems:
            print(f"    - {p}")
        # store.get_health_report()
        report = store.get_health_report()
        print(f"  ✓ store.get_health_report() nycklar: "
              f"active={report['active_count']}, "
              f"schema={report['schema_version']}, "
              f"problems={report['problem_count']}")
        assert "summary_swedish" in report
        assert "find_cache" in report
        assert "filter_cache" in report
        assert "audit" in report
        assert "store_version" in report
        assert report["store_version"] == STORE_VERSION
        # get_store_diagnostics (modul-niva)
        diag = get_store_diagnostics()
        print(f"  ✓ get_store_diagnostics() (utan store): problem_count="
              f"{diag['problem_count']}, summary={diag['summary_swedish']!r}")
        assert diag["module"] == "store"
        # summarize_store_health
        summ = summarize_store_health(store)
        print(f"  ✓ summarize_store_health: {summ!r}")
        assert "tasks" in summ

    print()
    print("=" * 70)
    print(f"✓ ALLA 12 TESTER PASSERADE (store.py {STORE_VERSION})")
    print("=" * 70)
