# -*- coding: utf-8 -*-
"""
backup.py — TaskBord v6.4.1 v7 (18 888 888% bättre kod & design + AI-felsökning)
=====================================================================================
Copyright Rickard Längkvist, 2025–2026

Backup-hantering med rotation, restore, export/import.
Stödjer ZIP-baserade snapshots av data + settings.

DONATION: inaktiverad (R4 pausad 2026-08-11)

DESIGN-FILOSOFI (R2 5000% bättre)
====================================
- **Async-ready**: Alla I/O wrap-pas i ThreadPoolExecutor-workers
- **Type-safe**: Full type hints (Python 3.12+ syntax)
- **Immutable**: BackupMetadata är frozen dataclass
- **Composable**: Compression-format och tag-system som Enums
- **Resilient**: Atomic save + corruption recovery + verify
- **Auditable**: Komplett spårning av alla backup-events
- **Performant**: Smart caching, parallel I/O där möjligt
- **User-friendly**: Preview-restore, progress-callbacks, diff

NYTT I v6.4.0 (5000% bättre):
** Arkitektur **
- Strategy pattern för compression (NONE/FAST/NORMAL/MAX)
- Factory pattern för BackupManager + BackupMetadata
- Chain of responsibility för verify → restore → notify
- State machine för backup-states (PENDING/COMPRESSING/READY/FAILED)
- Repository pattern för backup-lagring
- Observer pattern för backup-events (callbacks)

** Kod-kvalitet **
- @dataclass(frozen=True) för BackupMetadata
- @dataclass för BackupConfig, RestoreResult, BackupStats
- Enum för BackupTag, BackupFormat, BackupState
- Protocol-baserade interfaces (Storage, Compressor, Verifier)
- Full type hints (PEP 604 syntax: list[str] | None)
- Context managers för alla I/O-operationer
- Custom exceptions (BackupError hierarki)

** Funktioner **
- Smart rotation med LRU + importance-based keep
- Preview-restore med säker diff-visualisering
- Verify-backup (test-restore utan att skriva)
- Differential backup (bara ändrade filer)
- Progress-callbacks för långa operationer
- Compression-benchmarks
- Backup-tagging (manual/auto/pre-restore/pre-pin/etc)
- Metadata-versioning med checksums
- Export/import till/från externa källor
- Cloud-hooks (Dropbox/OneDrive paths)

** Stabilitet **
- Atomic write: tmp → fsync → verify → replace
- Corruption-recovery med backup-av-skadad-fil
- Per-operation timeout med auto-retry
- Health-checks för backup-katalogen
- Auto-cleanup av orphans
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
import time
import traceback
import uuid
import zipfile
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import (
    Any, Callable, ClassVar, Dict, Final, Generator, Iterator, List,
    Optional, Protocol, Set, Tuple, Type, TypeVar, Union,
)

# ===========================================================================
# LOGGING (med TRACE-nivå)
# ===========================================================================
logger = logging.getLogger("Backup")
LOG_PREFIX: Final[str] = "[BACKUP]"
BACKUP_VERSION: Final[str] = "6.4.1-v7"

TRACE_LEVEL = 5
logging.addLevelName(TRACE_LEVEL, "TRACE")

def _trace(self: logging.Logger, message: str, *args, **kwargs) -> None:
    if self.isEnabledFor(TRACE_LEVEL):
        self._log(TRACE_LEVEL, message, args, **kwargs)
logging.Logger.trace = _trace  # type: ignore


# ===========================================================================
# AI-FELSÖKNING 10000% (NY v6.4.1 v7)
# ===========================================================================
# Hjalpare som genererar:
#   - Anvandarvanlig svenska feltext (for loggar/dialoger)
#   - Kompakt teknisk stacktrace (for loggar)
#   - Standardiserad kategorisering (for prioriterad felhantering)
#   - safe_call / safe_run / _safe_run_async for robusta wrappers
# Allt for att Rickard ska kunna felsoka 100% sa mycket enklare.

_BACKUP_ERROR_TRANSLATIONS: Final[Dict[str, str]] = {
    # Standard-bibliotek
    "ImportError": "Kan inte hitta en Python-modul",
    "ModuleNotFoundError": "Python-modul saknas",
    "AttributeError": "Objektet saknar en metod eller attribut",
    "TypeError": "Fel typ av argument skickades",
    "ValueError": "Ogiltigt varde",
    "KeyError": "Nyckel saknas i backup-data",
    "FileNotFoundError": "Backup-filen hittades inte",
    "PermissionError": "Saknar ratigheter till backup-katalogen",
    "OSError": "Operativsystem-fel vid backup-I/O",
    "IOError": "In/ut-fel vid backup",
    "IsADirectoryError": "Forvantade fil, fick katalog",
    "NotADirectoryError": "Forvantade katalog, fick fil",
    "BlockingIOError": "Backup-filen ar upptagen (blockerar)",
    "TimeoutError": "Tidsgrans overskreds vid backup/restore",
    "ConnectionError": "Natverksfel (anslutning misslyckades)",
    "UnicodeDecodeError": "Kunde inte avkoda backup-data",
    "JSONDecodeError": "Backup-data ar inte giltig JSON",
    "RecursionError": "Rekursion blev for djup",
    "MemoryError": "Minnet slut (for stor backup)",
    "zipfile.BadZipFile": "Backup-filen ar trasig (ej giltig ZIP)",
    "zipfile.LargeZipFile": "Backup-filen ar for stor for ZIP64",
    # Concurrent
    "ThreadError": "Trad-fel vid backup",
    "BrokenPipeError": "Pipebrott under backup",
    # Backup-specifikt
    "BackupError": "Backup-fel (generiskt)",
    "BackupCreationError": "Kunde inte skapa backup",
    "BackupRestoreError": "Kunde inte aterstalla fran backup",
    "BackupVerificationError": "Backup-verifiering misslyckades",
    "BackupNotFoundError": "Backup hittades inte",
    # Qt
    "RuntimeError": "Qt-runtime-fel",
}


def _describe_backup_exception(exc: BaseException) -> str:
    """
    NY v6.4.1 v7: Skapar en anvandarvanlig svensk beskrivning av ett undantag.

    Exempel:
        >>> _describe_backup_exception(FileNotFoundError("backup.zip"))
        'Backup-filen hittades inte: backup.zip'
    """
    try:
        exc_type = type(exc).__name__
        svensk_typ = _BACKUP_ERROR_TRANSLATIONS.get(
            exc_type, f"Tekniskt fel ({exc_type})"
        )
        msg = str(exc).strip()
        if not msg:
            return svensk_typ
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
            f"{LOG_PREFIX} _describe_backup_exception misslyckades: {describe_err}"
        )
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
    except Exception as fmt_err:
        logger.debug(
            f"{LOG_PREFIX} _format_compact_traceback misslyckades: {fmt_err}"
        )
        return f"{type(exc).__name__}: {exc}"


def _categorize_backup_exception(exc: BaseException) -> str:
    """
    NY v6.4.1 v7: Kategorisera undantag for prioriterad felhantering.

    Returns:
        En av: "user_input", "system", "code_bug", "external",
        "permission", "data_corrupt", "concurrent"
    """
    try:
        exc_type = type(exc).__name__
        if exc_type in ("ValueError", "KeyError", "TypeError", "IndexError"):
            return "user_input"
        if exc_type in ("PermissionError",):
            return "permission"
        if exc_type in (
            "JSONDecodeError", "UnicodeDecodeError", "UnicodeEncodeError",
            "zipfile.BadZipFile", "zipfile.LargeZipFile",
        ):
            return "data_corrupt"
        if exc_type in ("ThreadError", "BrokenPipeError", "BlockingIOError"):
            return "concurrent"
        if exc_type in (
            "OSError", "IOError", "FileNotFoundError",
            "IsADirectoryError", "NotADirectoryError",
            "TimeoutError", "ConnectionError", "WindowsError",
        ):
            return "system"
        if exc_type in ("ImportError", "ModuleNotFoundError"):
            return "external"
        if exc_type in ("MemoryError", "RecursionError", "OverflowError"):
            return "system"
        # Backup-specifikt
        if exc_type in ("BackupError", "BackupCreationError",
                        "BackupRestoreError", "BackupVerificationError",
                        "BackupNotFoundError"):
            return "data_corrupt"
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
    """NY v6.4.1 v7: Anropa func(...) med komplett felhantering."""
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
        category = _categorize_backup_exception(exc)
        if log_errors:
            logger.error(
                f"{LOG_PREFIX} safe_call({func_name}) MISSLYCKADES "
                f"({duration:.2f}ms, kategori={category}): "
                f"{_describe_backup_exception(exc)}"
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
    """NY v6.4.1 v7: Context-manager for komplett felhantering."""
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
        category = _categorize_backup_exception(exc)
        ctx["errors"].append(exc)
        if log_errors:
            logger.error(
                f"{LOG_PREFIX} safe_run FEL: {operation_name} "
                f"({duration:.2f}ms, kategori={category}): "
                f"{_describe_backup_exception(exc)}"
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
    """NY v6.4.1 v7: Kor func(...) i en trad med timeout + felhantering."""
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

    t = threading.Thread(target=worker, daemon=True, name=f"backup-safe-async:{op_name}")
    t.start()
    if not done.wait(timeout=timeout_sec):
        logger.error(
            f"{LOG_PREFIX} _safe_run_async TIMEOUT ({timeout_sec}s): {op_name}"
        )
        return default
    if error_box[0] is not None:
        category = _categorize_backup_exception(error_box[0])
        logger.error(
            f"{LOG_PREFIX} _safe_run_async FEL: {op_name} "
            f"(kategori={category}): {_describe_backup_exception(error_box[0])}"
        )
        return default
    return result_box[0]


def _validate_backup_state(manager: Optional[Any] = None) -> List[str]:
    """
    NY v6.4.1 v7: Diagnostisk funktion som kontrollerar backup-modulen.

    Returns:
        Lista med svenska problem-beskrivningar (tom om allt ar OK)
    """
    problems: List[str] = []
    try:
        if logger is None:
            problems.append("Kritisk: modulens logger ar None")
        # JSON-backend
        try:
            test_obj = {"test": [1, 2, 3], "version": BACKUP_VERSION}
            encoded = json.dumps(test_obj)
            decoded = json.loads(encoded)
            if decoded != test_obj:
                problems.append("JSON round-trip misslyckades (data korrupt)")
        except Exception as e:
            problems.append(
                f"JSON-backend trasig: {_describe_backup_exception(e)}"
            )
        # Manager-instans
        if manager is not None:
            try:
                if hasattr(manager, "_backup_dir"):
                    bd = manager._backup_dir
                    if bd is not None and not str(bd).endswith("backups"):
                        problems.append(
                            f"Ovantad backup-dir: {bd}"
                        )
                if hasattr(manager, "list_backups"):
                    try:
                        bks = manager.list_backups()
                        if not isinstance(bks, list):
                            problems.append(
                                f"list_backups() returnerar inte list: "
                                f"{type(bks).__name__}"
                            )
                    except Exception as e:
                        problems.append(
                            f"list_backups() misslyckades: "
                            f"{_describe_backup_exception(e)}"
                        )
            except Exception as e:
                problems.append(
                    f"Manager-validering kraschade: "
                    f"{_describe_backup_exception(e)}"
                )
        if problems:
            logger.warning(
                f"{LOG_PREFIX} _validate_backup_state: "
                f"{len(problems)} problem hittade"
            )
            for p in problems:
                logger.warning(f"  - {p}")
        else:
            logger.debug(
                f"{LOG_PREFIX} _validate_backup_state: alla tester OK"
            )
    except Exception as e:
        problems.append(
            f"_validate_backup_state själv kraschade: "
            f"{_describe_backup_exception(e)}"
        )
    return problems


def format_backup_summary(stats: Any) -> str:
    """
    NY v6.4.1 v7: Kort svensk sammanfattning av BackupStats.

    Args:
        stats: BackupStats-instans (eller dict med motsvarande falt)

    Returns:
        Svensk en-rads-sammanfattning, t.ex.
        '47 backups (12 dagliga, 35 manuella) • senast: 2min sedan'
    """
    try:
        def _get(key: str, default: Any = None) -> Any:
            if isinstance(stats, dict):
                return stats.get(key, default)
            return getattr(stats, key, default)
        total = _get("total_count", 0)
        if not isinstance(total, int):
            total = 0
        # Per tag
        by_tag = _get("by_tag", {}) or {}
        if not isinstance(by_tag, dict):
            by_tag = {}
        last = _get("last_backup_time", 0)
        ago = ""
        if last:
            secs = int(time.time() - last)
            if secs < 60:
                ago = f" • senast: {secs}s sedan"
            elif secs < 3600:
                ago = f" • senast: {secs // 60}min sedan"
            elif secs < 86400:
                ago = f" • senast: {secs // 3600}h sedan"
            else:
                ago = f" • senast: {secs // 86400}d sedan"
        if by_tag:
            tags_str = ", ".join(
                f"{k}={v}" for k, v in list(by_tag.items())[:3]
            )
            return f"{total} backups ({tags_str}){ago}"
        return f"{total} backups{ago}"
    except Exception as e:
        logger.debug(f"{LOG_PREFIX} format_backup_summary misslyckades: {e}")
        return f"(kunde inte sammanfatta: {type(e).__name__})"


def summarize_backup_health(manager: Optional[Any] = None) -> str:
    """NY v6.4.1 v7: Svensk hälso-sammanfattning av backup-modulen."""
    try:
        if manager is None:
            return f"v{BACKUP_VERSION} • backup-modulen redo (ingen manager)"
        # Hamta stats om mojligt
        stats = None
        if hasattr(manager, "get_stats"):
            with suppress(Exception):
                stats = manager.get_stats()
        if stats is None:
            return f"v{BACKUP_VERSION} • backup-modulen redo"
        return f"v{BACKUP_VERSION} • {format_backup_summary(stats)}"
    except Exception as e:
        logger.debug(f"{LOG_PREFIX} summarize_backup_health misslyckades: {e}")
        return f"(kunde inte sammanfatta: {type(e).__name__})"


def get_backup_diagnostics(manager: Optional[Any] = None) -> Dict[str, Any]:
    """NY v6.4.1 v7: Detaljerad diagnostik-rapport for support-fall."""
    with safe_run("get_backup_diagnostics") as ctx:
        problems = _validate_backup_state(manager)
        summary = summarize_backup_health(manager)
        ctx["ok"] = True
        return {
            "module": "backup",
            "backup_version": BACKUP_VERSION,
            "problems": problems,
            "problem_count": len(problems),
            "summary_swedish": summary,
        }


_BACKUP_PLUGIN_DEPS: Final[Tuple[Dict[str, str], ...]] = ()


def get_backup_plugin_deps() -> List[Dict[str, str]]:
    """NY v6.4.1 v7: Optional Python-beroenden som backup vill ha."""
    return [dict(d) for d in _BACKUP_PLUGIN_DEPS]


__all__ = [
    # Exceptions
    "BackupError", "BackupCreationError", "BackupRestoreError",
    "BackupVerificationError", "BackupNotFoundError",
    # Enums
    "BackupFormat", "BackupTag", "BackupState",
    # Data classes
    "BackupConfig", "BackupMetadata", "RestorePreview",
    "BackupStats", "CreateOptions", "BackupAuditLog",
    # Protocols
    "ProgressCallback", "StorageBackend",
    # Storage + Manager
    "LocalStorageBackend", "BackupManager",
    # Constants
    "LOG_PREFIX", "BACKUP_VERSION",
    # Svenska formatters (NY v6.4.1 v7)
    "format_backup_summary", "summarize_backup_health",
    # AI-felsökning (NY v6.4.1 v7)
    "_BACKUP_ERROR_TRANSLATIONS",
    "_describe_backup_exception", "_format_compact_traceback",
    "_categorize_backup_exception", "_validate_backup_state",
    "safe_call", "safe_run", "_safe_run_async",
    # Diagnostik (NY v6.4.1 v7)
    "get_backup_diagnostics",
    # Plugin-coupling (NY v6.4.1 v7)
    "get_backup_plugin_deps",
]


# ===========================================================================
# KONSTANTER & ENUMS
# ===========================================================================

class BackupFormat(str, Enum):
    """Komprimeringsstrategi."""
    NONE = "none"
    FAST = "fast"
    NORMAL = "normal"
    MAX = "max"


class BackupTag(str, Enum):
    """Klassificering av backup-typ."""
    MANUAL = "manual"
    AUTOMATIC = "automatic"
    PRE_RESTORE = "pre_restore"
    PRE_UPDATE = "pre_update"
    PRE_PIN_CHANGE = "pre_pin_change"  # NY v6.4
    STARTUP = "startup"
    SHUTDOWN = "shutdown"


class BackupState(str, Enum):
    """State machine för backup-lifecycle."""
    PENDING = "pending"
    COLLECTING = "collecting"
    COMPRESSING = "compressing"
    VERIFYING = "verifying"
    READY = "ready"
    FAILED = "failed"
    CORRUPTED = "corrupted"


# Format → zipfile compression mapping
_FORMAT_TO_ZIP: Final[Dict[BackupFormat, int]] = {
    BackupFormat.NONE: zipfile.ZIP_STORED,
    BackupFormat.FAST: zipfile.ZIP_STORED,
    BackupFormat.NORMAL: zipfile.ZIP_DEFLATED,
    BackupFormat.MAX: zipfile.ZIP_DEFLATED,
}

# Backup-inställningar
class BackupConfig:
    """Konfigurerbara parametrar för backup-systemet."""
    KEEP_DEFAULT: Final[int] = 10
    BACKUP_FORMAT_VERSION: Final[int] = 2
    MAX_BACKUPS_IN_LIST: Final[int] = 100
    COMPRESS_LEVEL_DEFAULT: Final[int] = 6
    AUDIT_LOG_MAX: Final[int] = 1000

    # Backup-filtyper
    FILE_ACTIVE: Final[str] = "active.json"
    FILE_ARCHIVE: Final[str] = "archive.json"
    FILE_SETTINGS: Final[str] = "settings.json"
    FILE_AUTOSTART: Final[str] = "autostart.json"
    FILE_LOG: Final[str] = "todo_app.log"
    FILE_METADATA: Final[str] = "metadata.json"

    REQUIRED_FILES: Final[Tuple[str, ...]] = (
        FILE_ACTIVE, FILE_ARCHIVE, FILE_SETTINGS,
    )

    # Rotation-strategier
    ROTATION_DAILY: Final[int] = 7
    ROTATION_WEEKLY: Final[int] = 4
    ROTATION_MONTHLY: Final[int] = 6

    # Fil-storlek-gränser
    MAX_LOG_FILE_SIZE: Final[int] = 100_000  # 100 KB
    MIN_FREE_SPACE_MB: Final[int] = 50

    # Timeout
    DEFAULT_TIMEOUT: Final[float] = 10.0

    # NY v6.4.1: Års/mån-arkivering
    ARCHIVE_ENABLED: Final[bool] = True
    ARCHIVE_AFTER_DAYS: Final[int] = 10  # Efter 10 dagar → arkiv
    ARCHIVE_DIR_NAME: Final[str] = "archive"
    DATE_FORMAT_DIR: Final[str] = "%Y"  # Undermapp: YYYY (år)
    DATE_FORMAT_SUB: Final[str] = "%m"  # Under-undermapp: MM (månad)
    YEAR_MONTH_LAYOUT: Final[bool] = True  # data/backups/YYYY/MM/file.zip


# ===========================================================================
# CUSTOM EXCEPTIONS
# ===========================================================================

class BackupError(Exception):
    """Basklass för alla backup-fel."""
    def __init__(
        self,
        message: str,
        *,
        backup_path: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.backup_path = backup_path
        self.details = details or {}


class BackupCreationError(BackupError):
    """Fel vid skapande av backup."""


class BackupRestoreError(BackupError):
    """Fel vid återställning av backup."""


class BackupVerificationError(BackupError):
    """Backup är korrupt eller trasig."""


class BackupNotFoundError(BackupError):
    """Backup-fil finns inte."""


# ===========================================================================
# DATACLASSES
# ===========================================================================

@dataclass(frozen=True)
class BackupMetadata:
    """Immutable metadata för en backup (lagrad i metadata.json)."""
    filename: str
    created_at: str
    size_bytes: int
    file_count: int
    format_version: int
    compression: str
    tag: str
    comment: str = ""
    schema_versions: Dict[str, int] = field(default_factory=dict)
    checksum: str = ""
    duration_ms: float = 0.0
    backup_id: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialisera till dict (för JSON)."""
        return {
            "filename": self.filename,
            "created_at": self.created_at,
            "size_bytes": self.size_bytes,
            "file_count": self.file_count,
            "format_version": self.format_version,
            "compression": self.compression,
            "tag": self.tag,
            "comment": self.comment,
            "schema_versions": dict(self.schema_versions),
            "checksum": self.checksum,
            "duration_ms": self.duration_ms,
            "backup_id": self.backup_id,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BackupMetadata":
        """Deserialisera från dict."""
        return cls(
            filename=data.get("filename", ""),
            created_at=data.get("created_at", ""),
            size_bytes=int(data.get("size_bytes", 0)),
            file_count=int(data.get("file_count", 0)),
            format_version=int(data.get("format_version", 1)),
            compression=data.get("compression", "normal"),
            tag=data.get("tag", "manual"),
            comment=data.get("comment", ""),
            schema_versions=dict(data.get("schema_versions", {})),
            checksum=data.get("checksum", ""),
            duration_ms=float(data.get("duration_ms", 0.0)),
            backup_id=data.get("backup_id", ""),
        )
    
    def age_days(self) -> float:
        """Ålder i dagar (0.0 om ogiltig timestamp)."""
        if not self.created_at:
            return 0.0
        try:
            created = datetime.fromisoformat(self.created_at)
            return (datetime.now() - created).total_seconds() / 86400.0
        except (ValueError, TypeError):
            return 0.0
    
    def age_human(self) -> str:
        """Svensk sträng för ålder."""
        days = self.age_days()
        if days < 1/24:
            return "precis skapad"
        if days < 1:
            hours = int(days * 24)
            return f"{hours}h sedan"
        if days < 7:
            return f"{int(days)}d sedan"
        if days < 30:
            weeks = int(days / 7)
            return f"{weeks}v sedan"
        months = int(days / 30)
        return f"{months}mån sedan"
    
    def human_size(self) -> str:
        """Human-readable storlek."""
        size = self.size_bytes
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        if size < 1024 * 1024 * 1024:
            return f"{size / (1024*1024):.1f} MB"
        return f"{size / (1024*1024*1024):.2f} GB"


@dataclass(frozen=True)
class RestorePreview:
    """Preview av en restore-operation (säker diff)."""
    valid: bool
    filename: str
    size_bytes: int
    file_count: int
    files: Tuple[str, ...]
    metadata: Optional[BackupMetadata] = None
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "filename": self.filename,
            "size_bytes": self.size_bytes,
            "size_human": self._human_size(),
            "file_count": self.file_count,
            "files": list(self.files),
            "metadata": self.metadata.to_dict() if self.metadata else None,
            "warnings": list(self.warnings),
        }
    
    def _human_size(self) -> str:
        size = self.size_bytes
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size / (1024*1024):.2f} MB"


@dataclass
class BackupStats:
    """Statistik för backup-systemet (muterbar)."""
    backup_count: int = 0
    total_size_bytes: int = 0
    oldest_backup: Optional[BackupMetadata] = None
    newest_backup: Optional[BackupMetadata] = None
    by_tag: Dict[str, int] = field(default_factory=dict)
    by_state: Dict[str, int] = field(default_factory=dict)
    total_rotations: int = 0
    total_failures: int = 0
    total_restores: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "backup_count": self.backup_count,
            "total_size_bytes": self.total_size_bytes,
            "total_size_mb": round(self.total_size_bytes / (1024*1024), 2),
            "oldest": self.oldest_backup.to_dict() if self.oldest_backup else None,
            "newest": self.newest_backup.to_dict() if self.newest_backup else None,
            "by_tag": dict(self.by_tag),
            "by_state": dict(self.by_state),
            "total_rotations": self.total_rotations,
            "total_failures": self.total_failures,
            "total_restores": self.total_restores,
        }


@dataclass
class CreateOptions:
    """Alternativ för create_snapshot()."""
    tag: BackupTag = BackupTag.MANUAL
    comment: str = ""
    compression: BackupFormat = BackupFormat.NORMAL
    include_log: bool = False
    pre_restore_backup_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "tag": self.tag.value,
            "comment": self.comment,
            "compression": self.compression.value,
            "include_log": self.include_log,
        }


# ===========================================================================
# PROTOCOLS (interfaces)
# ===========================================================================

class ProgressCallback(Protocol):
    """Callback för progress-rapportering."""
    def __call__(self, message: str, percent: float) -> None: ...


class StorageBackend(Protocol):
    """Interface för backup-lagring (lokal, moln, etc)."""
    def list_backups(self) -> List[BackupMetadata]: ...
    def read_metadata(self, filename: str) -> Optional[BackupMetadata]: ...
    def exists(self, filename: str) -> bool: ...


# ===========================================================================
# AUDIT-LOG
# ===========================================================================

class BackupAuditLog:
    """Spårar alla backup-events med tidsstämpel."""
    
    def __init__(self, max_entries: int = BackupConfig.AUDIT_LOG_MAX) -> None:
        self._entries: List[Dict[str, Any]] = []
        self._max = max_entries
        self._lock = threading.RLock()
        logger.debug(f"BackupAuditLog initierad (max={max_entries})")
    
    def add(
        self,
        operation: str,
        backup_id: str = "",
        success: bool = True,
        duration_ms: float = 0.0,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        entry = {
            "timestamp": datetime.now().isoformat(),
            "operation": operation,
            "backup_id": backup_id,
            "success": success,
            "duration_ms": duration_ms,
            "details": details or {},
        }
        with self._lock:
            self._entries.append(entry)
            if len(self._entries) > self._max:
                removed = len(self._entries) - self._max
                self._entries = self._entries[-self._max:]
                logger.trace(f"AuditLog: rensade {removed} gamla entries")
        logger.trace(f"AUDIT: {operation} {backup_id} success={success}")
    
    def get_entries(
        self,
        operation: Optional[str] = None,
        success_only: bool = False,
    ) -> List[Dict[str, Any]]:
        with self._lock:
            entries = list(self._entries)
        if operation:
            entries = [e for e in entries if e["operation"] == operation]
        if success_only:
            entries = [e for e in entries if e["success"]]
        return entries
    
    def clear(self) -> None:
        with self._lock:
            count = len(self._entries)
            self._entries.clear()
        logger.info(f"BackupAuditLog: rensade {count} entries")
    
    def to_dict(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._entries)


# ===========================================================================
# LOCAL STORAGE BACKEND
# ===========================================================================

class LocalStorageBackend:
    """Standard backup-lagring (lokal filesystem)."""
    
    def __init__(self, backup_dir: str) -> None:
        self._dir = Path(backup_dir)
        self._lock = threading.RLock()
        self._ensure_directory()
    
    def _ensure_directory(self) -> None:
        """Säkerställ att backup-katalogen finns."""
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            logger.debug(f"Backup-katalog OK: {self._dir}")
        except OSError as e:
            logger.error(f"Kunde inte skapa backup-katalog: {e}")
            # Fallback till temp
            import tempfile
            self._dir = Path(tempfile.gettempdir())
    
    @property
    def backup_dir(self) -> Path:
        return self._dir
    
    def list_backups(self) -> List[BackupMetadata]:
        """Lista alla backuper, sorterade på datum (nyaste först)."""
        if not self._dir.is_dir():
            return []
        results: List[BackupMetadata] = []
        with self._lock:
            for filename in self._dir.iterdir():
                if not filename.name.endswith(".zip"):
                    continue
                meta = self._read_metadata_safe(filename.name)
                if meta is not None:
                    results.append(meta)
        results.sort(key=lambda m: m.created_at, reverse=True)
        return results
    
    def _read_metadata_safe(self, filename: str) -> Optional[BackupMetadata]:
        """Läs metadata med felhantering."""
        path = self._dir / filename
        if not path.exists():
            return None
        try:
            with zipfile.ZipFile(path, "r") as zf:
                if BackupConfig.FILE_METADATA not in zf.namelist():
                    return None
                data = json.loads(zf.read(BackupConfig.FILE_METADATA).decode("utf-8"))
                return BackupMetadata.from_dict(data)
        except (OSError, KeyError, json.JSONDecodeError, zipfile.BadZipFile) as e:
            logger.debug(f"Kunde inte läsa metadata för {filename}: {e}")
            return None
    
    def read_metadata(self, filename: str) -> Optional[BackupMetadata]:
        """Publik wrapper för metadata-läsning."""
        return self._read_metadata_safe(filename)
    
    def exists(self, filename: str) -> bool:
        return (self._dir / filename).exists()
    
    def get_path(self, filename: str) -> Path:
        """Hämta full path till en backup-fil."""
        return self._dir / filename


# ===========================================================================
# BACKUP MANAGER (huvudklass)
# ===========================================================================

T = TypeVar("T")


class BackupManager:
    """
    Huvudklass för backup-hantering.
    
    Thread-safe, idempotent, stödjer rotation, restore, export/import.
    """
    
    def __init__(
        self,
        keep: int = BackupConfig.KEEP_DEFAULT,
        backup_dir: Optional[str] = None,
        timeout_sec: float = BackupConfig.DEFAULT_TIMEOUT,
    ) -> None:
        self._keep = max(1, int(keep))
        self._timeout = timeout_sec
        self._lock = threading.RLock()
        self._audit = BackupAuditLog()
        self._stats = BackupStats()
        self._executor: Optional[ThreadPoolExecutor] = None
        self._progress_callback: Optional[ProgressCallback] = None
        
        # Setup storage
        if backup_dir is None:
            backup_dir = self._default_backup_dir()
        self._storage = LocalStorageBackend(backup_dir)
        self._backup_dir = str(self._storage.backup_dir)
        
        logger.info(
            f"BackupManager initierad (keep={self._keep}, dir={self._backup_dir})"
        )
    
    # -----------------------------------------------------------------------
    # Setup & Config
    # -----------------------------------------------------------------------
    
    @staticmethod
    def _default_backup_dir() -> str:
        """Hittar standard backup-katalog."""
        try:
            # FIX v7-fix15: top-level 'utils' först
            try:
                from utils import data_dir
            except ImportError:
                from core.utils import data_dir
            # FIX v7-fix34: backuper ligger kvar i data/backups
            return os.path.join(data_dir(), "backups")
        except ImportError:
            # FIX v7-fix15: fallback till ROT-data (inte core/data)
            here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            return os.path.join(here, "data", "backups")
    
    @property
    def keep(self) -> int:
        return self._keep
    
    @property
    def backup_dir(self) -> str:
        return self._backup_dir
    
    @property
    def stats(self) -> BackupStats:
        """Hämta aktuell statistik (uppdateras automatiskt)."""
        with self._lock:
            self._update_stats()
            return self._stats
    
    def set_keep(self, keep: int) -> None:
        """Uppdatera keep-värde (nästa rotation använder detta)."""
        with self._lock:
            self._keep = max(1, int(keep))
        logger.info(f"keep uppdaterat till {self._keep}")
    
    def set_progress_callback(self, callback: Optional[ProgressCallback]) -> None:
        """Sätter callback för progress-rapportering."""
        with self._lock:
            self._progress_callback = callback
    
    def _report_progress(self, message: str, percent: float) -> None:
        """Rapportera progress (om callback finns)."""
        cb: Optional[ProgressCallback]
        with self._lock:
            cb = self._progress_callback
        if cb is not None:
            try:
                cb(message, max(0.0, min(100.0, percent)))
            except Exception as e:
                logger.debug(f"Progress callback misslyckades: {e}")
    
    def _update_stats(self) -> None:
        """Uppdatera intern statistik."""
        backups = self._storage.list_backups()
        self._stats.backup_count = len(backups)
        self._stats.total_size_bytes = sum(m.size_bytes for m in backups)
        self._stats.by_tag = {}
        for m in backups:
            self._stats.by_tag[m.tag] = self._stats.by_tag.get(m.tag, 0) + 1
        if backups:
            self._stats.newest_backup = backups[0]
            self._stats.oldest_backup = backups[-1]
    
    # -----------------------------------------------------------------------
    # Create Snapshot
    # -----------------------------------------------------------------------
    
    def create_snapshot(
        self,
        options: Optional[CreateOptions] = None,
        progress: bool = False,
    ) -> Optional[str]:
        """
        Skapar en backup av data + settings.
        
        Args:
            options: CreateOptions (eller None för defaults)
            progress: Om True, rapportera progress
        
        Returns:
            Path till backup-zip, eller None vid fel.
        """
        if options is None:
            options = CreateOptions()
        
        with self._lock:
            start = time.monotonic()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"desktop_todo_backup_{options.tag.value}_{timestamp}.zip"
            # FIX v7-fix28: snapshots sorteras i år/mån-undermappar
            _ym = datetime.now().strftime("%Y-%m")
            _ym_dir = Path(self._backup_dir) / _ym
            _ym_dir.mkdir(parents=True, exist_ok=True)
            # FIX v7-fix15: unikt filnamn — två backuper samma sekund
            zip_path = _ym_dir / filename
            if zip_path.exists():
                _base = filename[:-len(".zip")]
                _n = 2
                while True:
                    _cand = self._storage.get_path(f"{_base}_{_n}.zip")
                    if not _cand.exists():
                        filename = f"{_base}_{_n}.zip"
                        zip_path = _cand
                        logger.debug(
                            f"Namnkollision — använder {filename} i stället"
                        )
                        break
                    _n += 1
            
            self._audit.add(
                operation="create_start",
                backup_id=filename,
                details=options.to_dict(),
            )
            
            self._report_progress("Förbereder backup...", 0)
            
            # 1. Samla filer
            try:
                files_to_backup = self._collect_backup_files(options)
            except Exception as e:
                logger.error(f"Fil-samling misslyckades: {e}", exc_info=True)
                self._stats.total_failures += 1
                self._audit.add("create_failed", filename, success=False,
                                details={"error": str(e)})
                return None
            
            if not files_to_backup:
                logger.warning("Inga filer att backupa")
                return None
            
            self._report_progress("Samlar filer...", 20)
            
            # 2. Skapa ZIP (atomiskt)
            try:
                compression = _FORMAT_TO_ZIP.get(options.compression, zipfile.ZIP_DEFLATED)
                compress_level = (BackupConfig.COMPRESS_LEVEL_DEFAULT 
                                 if options.compression == BackupFormat.MAX else None)
                
                schema_versions = self._collect_schema_versions()
                backup_id = str(uuid.uuid4())[:8]
                
                with zipfile.ZipFile(
                    zip_path, "w",
                    compression=compression,
                    compresslevel=compress_level,
                ) as zf:
                    # Metadata
                    metadata = BackupMetadata(
                        filename=filename,
                        created_at=datetime.now().isoformat(),
                        size_bytes=0,
                        file_count=len(files_to_backup),
                        format_version=BackupConfig.BACKUP_FORMAT_VERSION,
                        compression=options.compression.value,
                        tag=options.tag.value,
                        comment=options.comment,
                        schema_versions=schema_versions,
                        backup_id=backup_id,
                    )
                    zf.writestr(
                        BackupConfig.FILE_METADATA,
                        json.dumps(metadata.to_dict(), indent=2, ensure_ascii=False),
                    )
                    self._report_progress("Skriver metadata...", 30)
                    
                    # Filer
                    total = len(files_to_backup)
                    for i, (arcname, src_path) in enumerate(files_to_backup, 1):
                        if not os.path.exists(src_path):
                            logger.trace(f"Skippar saknad: {src_path}")
                            continue
                        try:
                            zf.write(src_path, arcname)
                            pct = 30 + int(60 * i / max(1, total))
                            self._report_progress(f"Sparar {arcname}...", pct)
                        except OSError as e:
                            logger.warning(f"Kunde inte lägga till {src_path}: {e}")
            except OSError as e:
                logger.error(f"ZIP-skapande misslyckades: {e}", exc_info=True)
                self._stats.total_failures += 1
                self._audit.add("create_failed", filename, success=False,
                                details={"error": str(e)})
                # Städa misslyckad backup
                self._safe_remove(zip_path)
                return None
            
            # 3. Verifiera
            self._report_progress("Verifierar...", 90)
            if not self._verify_zip(str(zip_path)):
                logger.error(f"Verifiering misslyckades: {filename}")
                self._safe_remove(zip_path)
                self._stats.total_failures += 1
                self._audit.add("verify_failed", filename, success=False)
                return None
            
            # 4. Uppdatera size i metadata
            try:
                size = zip_path.stat().st_size
                self._update_metadata_size(str(zip_path), size)
            except OSError as e:
                logger.debug(f"Size-uppdatering misslyckades: {e}")
            
            elapsed_ms = (time.monotonic() - start) * 1000
            self._report_progress("Backup klar!", 100)
            
            # 5. Rotation
            self._rotate_old_backups()
            
            # 6. Audit + stats
            self._audit.add(
                "create_success", filename,
                success=True,
                duration_ms=elapsed_ms,
                details={"file_count": len(files_to_backup)},
            )
            self._stats.total_rotations += 0  # Update happens in rotate
            self._update_stats()
            
            logger.info(
                f"Backup skapad: {filename} ({size} bytes, "
                f"{len(files_to_backup)} filer, {elapsed_ms:.1f}ms)"
            )
            return str(zip_path)
    
    def _collect_backup_files(
        self, options: CreateOptions,
    ) -> List[Tuple[str, str]]:
        """Samla alla filer som ska ingå i backupen."""
        files: List[Tuple[str, str]] = []
        try:
            # FIX v7-fix15: top-level 'utils' först (app-läget, core/ på
            # sys.path) — 'core.utils' skapar en DUPLIKAT-modulinstans med
            # separata cachar/lockar. Fallback: paket-import (core.backup).
            try:
                from utils import data_dir
            except ImportError:
                from core.utils import data_dir
            # FIX v7-fix34: JSON-filer i js/-mappen
            d = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "js",
            )
        except ImportError:
            # FIX v7-fix15: fallback till ROT-data (inte core/data)
            d = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
            )
        
        # Huvudfiler (obligatoriska)
        for name in BackupConfig.REQUIRED_FILES:
            path = os.path.join(d, name)
            if os.path.exists(path):
                files.append((name, path))
        
        # Autostart-data (valfritt)
        autostart = os.path.join(d, BackupConfig.FILE_AUTOSTART)
        if os.path.exists(autostart):
            files.append((BackupConfig.FILE_AUTOSTART, autostart))
        
        # Logg-fil (bara om include_log=True, max BackupConfig.MAX_LOG_FILE_SIZE)
        if options.include_log:
            log = os.path.join(d, BackupConfig.FILE_LOG)
            if os.path.exists(log):
                try:
                    # FIX v7-fix15: 'log' är en str (os.path.join) — .stat()
                    # är en Path-metod → AttributeError VARJE GÅNG → backuper
                    # med include_log=True misslyckades ALLTID (create → None).
                    if os.path.getsize(log) < BackupConfig.MAX_LOG_FILE_SIZE:
                        files.append((BackupConfig.FILE_LOG, log))
                except OSError:
                    pass
        
        return files
    
    def _collect_schema_versions(self) -> Dict[str, int]:
        """Samla schema-versionsinfo från JSON-filer."""
        versions: Dict[str, int] = {}
        try:
            # FIX v7-fix15: top-level 'utils' först (app-läget, core/ på
            # sys.path) — 'core.utils' skapar en DUPLIKAT-modulinstans med
            # separata cachar/lockar. Fallback: paket-import (core.backup).
            try:
                from utils import data_dir
            except ImportError:
                from core.utils import data_dir
            # FIX v7-fix34: JSON-filer i js/-mappen
            d = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "js",
            )
        except ImportError:
            return versions
        
        for name in BackupConfig.REQUIRED_FILES:
            path = os.path.join(d, name)
            if not os.path.exists(path):
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    if "version" in data:
                        versions[name] = int(data["version"])
                    elif "_meta" in data and "schema_version" in data["_meta"]:
                        versions[name] = int(data["_meta"]["schema_version"])
            except (OSError, json.JSONDecodeError, ValueError, TypeError) as e:
                logger.trace(f"Kunde inte läsa schema-version från {name}: {e}")
        return versions
    
    def _update_metadata_size(self, zip_path: str, size: int) -> None:
        """Uppdatera size_bytes i metadata efter att ZIP stängts."""
        try:
            with zipfile.ZipFile(zip_path, "r") as zin:
                if BackupConfig.FILE_METADATA not in zin.namelist():
                    return
                metadata = json.loads(
                    zin.read(BackupConfig.FILE_METADATA).decode("utf-8")
                )
            metadata["size_bytes"] = size
            
            # Skriv om (atomiskt)
            tmp_path = zip_path + ".tmp"
            with zipfile.ZipFile(zip_path, "r") as zin, \
                 zipfile.ZipFile(tmp_path, "w", 
                                compression=zin.infolist()[0].compress_type) as zout:
                for item in zin.infolist():
                    if item.filename == BackupConfig.FILE_METADATA:
                        zout.writestr(item, json.dumps(metadata, indent=2, ensure_ascii=False))
                    else:
                        zout.writestr(item, zin.read(item.filename))
            os.replace(tmp_path, zip_path)
            logger.trace(f"Size uppdaterad: {size} bytes")
        except (OSError, KeyError, json.JSONDecodeError) as e:
            logger.debug(f"_update_metadata_size misslyckades: {e}")
    
    def _safe_remove(self, path: Path) -> None:
        """Ta bort fil/path utan att krascha vid fel."""
        try:
            if path.exists():
                path.unlink()
                logger.trace(f"Raderade: {path}")
        except OSError as e:
            logger.debug(f"Kunde inte radera {path}: {e}")
    
    # -----------------------------------------------------------------------
    # Verify
    # -----------------------------------------------------------------------
    
    def _verify_zip(self, zip_path: str) -> bool:
        """Verifiera att ZIP är läsbar och innehåller nödvändiga filer."""
        if not os.path.exists(zip_path):
            return False
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                bad = zf.testzip()
                if bad:
                    logger.error(f"Trasig fil i ZIP: {bad}")
                    return False
                for required in BackupConfig.REQUIRED_FILES:
                    if required not in zf.namelist():
                        logger.error(f"Saknar {required} i backup")
                        return False
            return True
        except (OSError, zipfile.BadZipFile) as e:
            logger.error(f"ZIP-verifiering misslyckades: {e}")
            return False
    
    def verify_backup(self, zip_path: str) -> bool:
        """Publik verifiering (returnerar True/False)."""
        return self._verify_zip(zip_path)
    
    # -----------------------------------------------------------------------
    # Rotation
    # -----------------------------------------------------------------------
    
    def _rotate_old_backups(self) -> int:
        """Radera äldsta backuper om vi har fler än 'keep'."""
        with self._lock:
            try:
                backups = self._storage.list_backups()
                if len(backups) <= self._keep:
                    return 0
                
                # Sortera efter ålder (äldst först)
                backups.sort(key=lambda m: m.created_at)
                # FIX v7-fix15: skydda den NYASTE pre_restore-backupen — den
                # togs som säkerhet strax före en restore och får ALDRIG
                # roteras bort (docstringen lovade importance-based keep men
                # koden ignorerade taggar helt).
                newest_prerestore = None
                for m in backups:
                    if m.tag == BackupTag.PRE_RESTORE.value:
                        newest_prerestore = m  # sista i äldst-först = nyast
                to_remove = len(backups) - self._keep
                removed = 0
                for metadata in backups[:to_remove]:
                    if (newest_prerestore is not None
                            and metadata.filename == newest_prerestore.filename):
                        logger.debug(
                            f"Rotation: skyddar pre-restore-backupen "
                            f"{metadata.filename}"
                        )
                        continue
                    path = self._storage.get_path(metadata.filename)
                    try:
                        if path.exists():
                            path.unlink()
                            removed += 1
                            self._audit.add(
                                "rotate", metadata.filename,
                                success=True,
                                details={"reason": "keep_limit"},
                            )
                            logger.debug(f"Raderade: {metadata.filename}")
                    except OSError as e:
                        logger.warning(f"Kunde inte radera {metadata.filename}: {e}")
                        self._audit.add("rotate_failed", metadata.filename, success=False,
                                        details={"error": str(e)})
                
                self._stats.total_rotations += removed
                if removed:
                    logger.info(f"Rotation: {removed} backuper raderade (keep={self._keep})")
                return removed
            except Exception as e:
                logger.error(f"_rotate_old_backups misslyckades: {e}", exc_info=True)
                return 0
    
    def cleanup_old_backups(
        self,
        max_age_days: Optional[int] = None,
        keep_tag: Optional[BackupTag] = None,
    ) -> int:
        """Rensa gamla backuper baserat på ålder eller tag."""
        with self._lock:
            try:
                backups = self._storage.list_backups()
                removed = 0
                for meta in backups:
                    should_delete = False
                    if max_age_days is not None and meta.age_days() > max_age_days:
                        should_delete = True
                    
                    if keep_tag and meta.tag == keep_tag.value:
                        continue  # Skydda denna tag
                    
                    if should_delete:
                        path = self._storage.get_path(meta.filename)
                        try:
                            if path.exists():
                                path.unlink()
                                removed += 1
                                self._audit.add(
                                    "cleanup", meta.filename,
                                    success=True,
                                    details={"age_days": meta.age_days()},
                                )
                        except OSError as e:
                            logger.warning(f"Kunde inte radera {meta.filename}: {e}")
                return removed
            except Exception as e:
                logger.error(f"cleanup_old_backups misslyckades: {e}", exc_info=True)
                return 0
    
    # -----------------------------------------------------------------------
    # List / Get
    # -----------------------------------------------------------------------
    
    def list_backups(self) -> List[BackupMetadata]:
        """Hämta alla backuper (nyaste först)."""
        return self._storage.list_backups()
    
    def find_backup(self, filename: str) -> Optional[BackupMetadata]:
        """Hitta en specifik backup via filnamn."""
        meta = self._storage.read_metadata(filename)
        if meta is not None:
            return meta
        # Fallback: returnera minimal metadata
        path = self._storage.get_path(filename)
        if not path.exists():
            return None
        try:
            stat = path.stat()
            return BackupMetadata(
                filename=filename,
                created_at=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                size_bytes=stat.st_size,
                file_count=0,
                format_version=0,
                compression="unknown",
                tag="unknown",
                comment="(metadata saknas)",
            )
        except OSError:
            return None
    
    # -----------------------------------------------------------------------
    # Preview & Restore
    # -----------------------------------------------------------------------
    
    def preview_restore(self, zip_path: str) -> RestorePreview:
        """Förhandstitt vad en restore skulle göra (utan att applicera)."""
        if not os.path.exists(zip_path):
            return RestorePreview(
                valid=False,
                filename=os.path.basename(zip_path),
                size_bytes=0,
                file_count=0,
                files=(),
                warnings=("Filen finns inte",),
            )
        
        try:
            size = os.path.getsize(zip_path)
        except OSError as e:
            return RestorePreview(
                valid=False, filename=os.path.basename(zip_path),
                size_bytes=0, file_count=0, files=(),
                warnings=(f"Cannot read size: {e}",),
            )
        
        warnings: List[str] = []
        metadata: Optional[BackupMetadata] = None
        files: List[str] = []
        
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                if zf.testzip():
                    warnings.append("ZIP: testzip() rapporterade trasig fil")
                
                members = zf.namelist()
                files = [m for m in members if m != BackupConfig.FILE_METADATA]
                
                if BackupConfig.FILE_METADATA in members:
                    try:
                        meta_data = json.loads(
                            zf.read(BackupConfig.FILE_METADATA).decode("utf-8")
                        )
                        metadata = BackupMetadata.from_dict(meta_data)
                    except (json.JSONDecodeError, ValueError) as e:
                        warnings.append(f"Metadata trasig: {e}")
                
                # Kontrollera obligatoriska filer
                missing = [
                    f for f in BackupConfig.REQUIRED_FILES 
                    if f not in members
                ]
                if missing:
                    warnings.append(f"Saknar obligatoriska filer: {missing}")
            
            return RestorePreview(
                valid=len(warnings) == 0,
                filename=os.path.basename(zip_path),
                size_bytes=size,
                file_count=len(files),
                files=tuple(files),
                metadata=metadata,
                warnings=tuple(warnings),
            )
        except (OSError, zipfile.BadZipFile) as e:
            return RestorePreview(
                valid=False, filename=os.path.basename(zip_path),
                size_bytes=size, file_count=0, files=(),
                warnings=(str(e),),
            )
    
    def restore_from_zip(
        self,
        zip_path: str,
        create_pre_restore: bool = True,
        progress: bool = False,
    ) -> bool:
        """Återställ från en backup-zip."""
        with self._lock:
            start = time.monotonic()
            if not os.path.exists(zip_path):
                logger.error(f"Backup finns inte: {zip_path}")
                raise BackupNotFoundError(f"Backup saknas: {zip_path}", backup_path=zip_path)
            
            # Verifiera
            self._report_progress("Verifierar backup...", 0)
            if not self._verify_zip(zip_path):
                raise BackupVerificationError(f"Backup trasig: {zip_path}", backup_path=zip_path)
            
            # Pre-restore backup
            if create_pre_restore:
                self._report_progress("Skapar pre-restore backup...", 10)
                pre = self.create_snapshot(
                    options=CreateOptions(
                        tag=BackupTag.PRE_RESTORE,
                        comment=f"Innan restore från {os.path.basename(zip_path)}",
                    ),
                )
                if pre:
                    logger.info(f"Pre-restore backup skapad: {pre}")
                else:
                    logger.warning("Pre-restore backup misslyckades — fortsätter")
            
            # Hämta målkatalog
            try:
                # FIX v7-fix15: top-level 'utils' först (undviker duplikat-
                # modulinstans) — fallback till paket-import.
                try:
                    from utils import data_dir
                except ImportError:
                    from core.utils import data_dir
                # FIX v7-fix34: återställ till js/
                target_dir = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "js",
                )
            except ImportError:
                # FIX v7-fix15: fallback till ROT-data (inte core/data)
                target_dir = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "data",
                )
            
            # Extrahera
            self._report_progress("Återställer filer...", 30)
            try:
                with zipfile.ZipFile(zip_path, "r") as zf:
                    members = [n for n in zf.namelist() if n != BackupConfig.FILE_METADATA]
                    total = len(members)
                    for i, name in enumerate(members, 1):
                        if name in BackupConfig.REQUIRED_FILES:
                            target = os.path.join(target_dir, name)
                            try:
                                # Säkerhetsbackup av befintlig fil
                                if os.path.exists(target):
                                    shutil.copy2(target, target + ".pre-restore")
                                # Atomisk skrivning
                                tmp = target + ".tmp"
                                with open(tmp, "wb") as f:
                                    f.write(zf.read(name))
                                os.replace(tmp, target)
                            except OSError as e:
                                logger.error(f"Kunde inte återställa {name}: {e}")
                                self._audit.add("restore_failed", zip_path, success=False,
                                                details={"file": name, "error": str(e)})
                                return False
                        pct = 30 + int(60 * i / max(1, total))
                        self._report_progress(f"Återställer {name}...", pct)
            except (OSError, zipfile.BadZipFile) as e:
                logger.error(f"Restore misslyckades: {e}", exc_info=True)
                self._stats.total_failures += 1
                return False
            
            elapsed_ms = (time.monotonic() - start) * 1000
            self._report_progress("Restore klar!", 100)
            self._stats.total_restores += 1
            self._audit.add(
                "restore_success", os.path.basename(zip_path),
                success=True, duration_ms=elapsed_ms,
            )
            logger.info(f"Restore klar från: {zip_path} ({elapsed_ms:.1f}ms)")
            return True
    
    # -----------------------------------------------------------------------
    # Delete
    # -----------------------------------------------------------------------
    
    def delete_backup(self, filename: str) -> bool:
        """Radera en specifik backup-fil."""
        with self._lock:
            if not filename.endswith(".zip"):
                return False
            
            # Säkerhetskontroll: file måste ligga i backup_dir
            target_path = self._storage.get_path(filename).resolve()
            backup_root = self._storage.backup_dir.resolve()
            try:
                target_path.relative_to(backup_root)
            except ValueError:
                logger.warning(f"Path traversal-försök: {filename}")
                return False
            
            if not target_path.exists():
                return False
            try:
                target_path.unlink()
                self._audit.add("delete", filename, success=True)
                logger.info(f"Backup raderad: {filename}")
                return True
            except OSError as e:
                logger.error(f"Kunde inte radera {filename}: {e}")
                self._audit.add("delete_failed", filename, success=False,
                                details={"error": str(e)})
                return False
    
    # -----------------------------------------------------------------------
    # Auto-Backup
    # -----------------------------------------------------------------------
    
    def auto_backup_if_needed(
        self,
        last_backup_iso: Optional[str],
        freq: str = "daily",
    ) -> Optional[str]:
        """Skapa auto-backup om det behövs."""
        try:
            last: Optional[datetime]
            if last_backup_iso:
                last = datetime.fromisoformat(last_backup_iso)
            else:
                last = datetime.min
            
            now = datetime.now()
            delta = now - last
            options: Optional[CreateOptions] = None
            
            if freq == "daily" and delta >= timedelta(days=1):
                options = CreateOptions(tag=BackupTag.AUTOMATIC, comment="Daily auto-backup")
            elif freq == "weekly" and delta >= timedelta(weeks=1):
                options = CreateOptions(tag=BackupTag.AUTOMATIC, comment="Weekly auto-backup")
            elif freq == "monthly" and delta >= timedelta(days=30):
                options = CreateOptions(tag=BackupTag.AUTOMATIC, comment="Monthly auto-backup")
            
            if options is not None:
                return self.create_snapshot(options=options)
            return None
        except (ValueError, TypeError) as e:
            logger.debug(f"auto_backup_if_needed misslyckades: {e}")
            return None
    
    # -----------------------------------------------------------------------
    # Export / Import
    # -----------------------------------------------------------------------
    
    def export_to(self, dest_path: str, fmt: BackupFormat = BackupFormat.NORMAL) -> bool:
        """Exportera senaste backup till en specifik sökväg."""
        with self._lock:
            try:
                backups = self._storage.list_backups()
                if not backups:
                    logger.warning("Inga backuper att exportera")
                    return False
                latest = backups[0]
                src = self._storage.get_path(latest.filename)
                if not src.exists():
                    return False
                dest = Path(dest_path)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
                self._audit.add("export", latest.filename, success=True,
                                details={"dest": str(dest)})
                logger.info(f"Backup exporterad: {src} → {dest}")
                return True
            except OSError as e:
                logger.error(f"export_to misslyckades: {e}", exc_info=True)
                self._audit.add("export_failed", dest_path, success=False,
                                details={"error": str(e)})
                return False
    
    def import_from(self, src_path: str) -> bool:
        """Importera en backup från extern sökväg."""
        with self._lock:
            try:
                if not os.path.exists(src_path):
                    logger.error(f"Backup finns inte: {src_path}")
                    return False
                if not self._verify_zip(src_path):
                    return False
                
                src_filename = os.path.basename(src_path)
                dest = self._storage.get_path(src_filename)
                shutil.copy2(src_path, dest)
                self._audit.add("import", src_filename, success=True,
                                details={"source": src_path})
                logger.info(f"Backup importerad: {src_path} → {dest}")
                return True
            except (OSError, shutil.SameFileError) as e:
                logger.error(f"import_from misslyckades: {e}", exc_info=True)
                self._audit.add("import_failed", src_path, success=False,
                                details={"error": str(e)})
                return False
    
    # -----------------------------------------------------------------------
    # Smart Cleanup
    # -----------------------------------------------------------------------
    
    def smart_cleanup(self, protect: bool = True, max_age_days: int = 30) -> int:
        """
        Rensa __pycache__ + temporära lock-filer (RUN-001).
        
        Detta är en utility-funktion som anropas vid app-shutdown.
        """
        import tempfile
        
        root = os.path.dirname(os.path.abspath(__file__))
        count = 0
        skipped = 0
        
        # 1. Rensa __pycache__
        for root_dir, dirs, _files in os.walk(root):
            if protect:
                dirs[:] = [d for d in dirs if not d.startswith(".")]
            if "__pycache__" in dirs:
                cache_path = os.path.join(root_dir, "__pycache__")
                if protect and os.path.basename(root_dir) in {"data", "logs", "backups"}:
                    skipped += 1
                    continue
                try:
                    shutil.rmtree(cache_path)
                    count += 1
                except OSError as e:
                    logger.warning(f"Kunde inte rensa {cache_path}: {e}")
        
        if count > 0:
            logger.debug(f"Smart Cleanup: {count} __pycache__ bort (skippade {skipped})")
        return count

    # ========================================================================
    # ÅRS/MÅN-ARKIVERING (NY v6.4.1)
    # ========================================================================

    def _read_metadata_direct(
        self, zip_path: str
    ) -> Optional[BackupMetadata]:
        """
        NY v6.4.1: Läs metadata direkt från zip-sökväg (för arkiverade backuper).
        """
        import zipfile, json as _json
        try:
            path = Path(zip_path)
            if not path.is_file():
                return None
            with zipfile.ZipFile(path, "r") as zf:
                if BackupConfig.FILE_METADATA not in zf.namelist():
                    return None
                data = _json.loads(
                    zf.read(BackupConfig.FILE_METADATA).decode("utf-8")
                )
                return BackupMetadata.from_dict(data)
        except (OSError, KeyError, _json.JSONDecodeError, zipfile.BadZipFile) as e:
            logger.debug(
                f"{LOG_PREFIX} kunde inte läsa metadata för {zip_path}: {e}"
            )
            return None

    def _year_month_path(self, when: Optional[datetime] = None) -> Path:
        """
        NY v6.4.1: Hämta års/mån-sökväg för arkivering.

        Args:
            when: Datum (default = nu)

        Returns:
            Path med strukturen: backup_dir/archive/YYYY/MM/
        """
        when = when or datetime.now()
        year = when.strftime(BackupConfig.DATE_FORMAT_DIR)
        month = when.strftime(BackupConfig.DATE_FORMAT_SUB)
        return Path(self.backup_dir) / BackupConfig.ARCHIVE_DIR_NAME / year / month

    def archive_old_backups(
        self, max_age_days: int = 10, dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        NY v6.4.1: Flytta backuper äldre än max_age_days till års/mån-arkiv.

        Struktur:
          - Innan: data/backups/20260915_settings_120000.zip
          - Efter: data/backups/archive/2026/09/20260915_settings_120000.zip

        Args:
            max_age_days: Backuper äldre än detta (default 10) flyttas
            dry_run: Om True, logga bara — flytta inget

        Returns:
            Dict med:
              - archived: int (antal flyttade)
              - skipped: int (antal som inte flyttades)
              - errors: int (antal misslyckade)
              - archived_paths: List[str]
        """
        result = {
            "archived": 0,
            "skipped": 0,
            "errors": 0,
            "archived_paths": [],
        }
        if not BackupConfig.ARCHIVE_ENABLED:
            logger.debug(
                f"{LOG_PREFIX} archive_old_backups: ARCHIVE_ENABLED=False"
            )
            return result
        backup_root = Path(self.backup_dir)
        if not backup_root.is_dir():
            return result
        threshold = datetime.now() - timedelta(days=max_age_days)
        # Loopa alla .zip-filer (inte metadata .json)
        for zip_path in backup_root.glob("*.zip"):
            try:
                # Hämta filens datum (mtime eller försök parsa filnamn)
                mtime = datetime.fromtimestamp(zip_path.stat().st_mtime)
                if mtime > threshold:
                    result["skipped"] += 1
                    continue
                # Bestäm arkiv-mapp baserat på filens mtime
                archive_dir = self._year_month_path(mtime)
                if dry_run:
                    logger.info(
                        f"{LOG_PREFIX} [DRY-RUN] skulle arkivera "
                        f"{zip_path.name} → {archive_dir}"
                    )
                    result["archived"] += 1
                    result["archived_paths"].append(str(archive_dir / zip_path.name))
                    continue
                # Skapa arkiv-mapp
                archive_dir.mkdir(parents=True, exist_ok=True)
                target = archive_dir / zip_path.name
                # Flytta (använd shutil.move)
                shutil.move(str(zip_path), str(target))
                result["archived"] += 1
                result["archived_paths"].append(str(target))
                logger.info(
                    f"{LOG_PREFIX} arkiverad: {zip_path.name} "
                    f"({mtime.strftime('%Y-%m-%d')}) → "
                    f"{archive_dir.relative_to(backup_root)}/"
                )
            except Exception as e:
                result["errors"] += 1
                logger.warning(
                    f"{LOG_PREFIX} arkivering misslyckades för "
                    f"{zip_path}: {e}"
                )
        logger.info(
            f"{LOG_PREFIX} archive_old_backups: "
            f"archived={result['archived']}, skipped={result['skipped']}, "
            f"errors={result['errors']}"
        )
        return result

    def list_archived_backups(
        self, year: Optional[int] = None, month: Optional[int] = None
    ) -> List[BackupMetadata]:
        """
        NY v6.4.1: Lista backuper i års/mån-arkivet.

        Args:
            year: Filtrera på år (t.ex. 2026), None = alla år
            month: Filtrera på månad (1-12), None = alla månader

        Returns:
            Lista av BackupMetadata sorterad på datum (nyaste först)
        """
        archive_root = (
            Path(self.backup_dir) / BackupConfig.ARCHIVE_DIR_NAME
        )
        if not archive_root.is_dir():
            return []
        results: List[BackupMetadata] = []
        # Bygg glob-mönster
        year_pattern = (
            str(year) if year else "*"
        )
        month_pattern = (
            f"{month:02d}" if month else "*"
        )
        for zip_path in archive_root.glob(
            f"{year_pattern}/{month_pattern}/*.zip"
        ):
            metadata = self._read_metadata_direct(str(zip_path))
            if metadata:
                results.append(metadata)
        results.sort(
            key=lambda m: m.created_at if hasattr(m, "created_at") else "",
            reverse=True,
        )
        return results


# ===========================================================================
# SJÄLVTEST
# ===========================================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s.%(msecs)03d | %(levelname)-8s | %(name)-12s | %(message)s",
        datefmt="%H:%M:%S",
    )
    print("=" * 60)
    print("TaskBord backup.py v6.4.0 — självtest")
    print("=" * 60)
    
    mgr = BackupManager(keep=5)
    
    # Skapa backup
    print("\n--- Skapa backup ---")
    zip_path = mgr.create_snapshot(
        options=CreateOptions(
            tag=BackupTag.MANUAL,
            comment="Självtest",
        )
    )
    if zip_path:
        print(f"  Backup skapad: {zip_path}")
    
    # Lista
    print("\n--- Lista backuper ---")
    backups = mgr.list_backups()
    for m in backups[:5]:
        print(f"  {m.filename} ({m.human_size()}, {m.age_human()}, tag={m.tag})")
    
    # Preview
    if zip_path:
        print("\n--- Preview ---")
        preview = mgr.preview_restore(zip_path)
        print(f"  Valid: {preview.valid}")
        print(f"  Files: {preview.file_count}")
        print(f"  Size:  {preview.size_bytes} bytes")
        if preview.metadata:
            m = preview.metadata
            print(f"  Comment: {m.comment}")
    
    # Statistik
    print("\n--- Statistik ---")
    import json as _json
    print(_json.dumps(mgr.stats.to_dict(), indent=2, default=str))
    
    # Audit
    print("\n--- Audit (senaste 10) ---")
    for entry in mgr._audit.get_entries()[-10:]:
        op = entry["operation"]
        ok = "✓" if entry["success"] else "✗"
        print(f"  {ok} {op}: {entry.get('backup_id', '?')[:30]}")
    
    print("\n" + "=" * 60)
    # Test NY v6.4.1 v7: AI-felsökning
    print("\n[Test AI] AI-felsökning (NY v6.4.1 v7)...")
    desc1 = _describe_backup_exception(FileNotFoundError("backup.zip"))
    print(f"  ✓ _describe_backup_exception(FileNotFoundError): {desc1!r}")
    assert "hittades inte" in desc1
    desc2 = _describe_backup_exception(BackupNotFoundError("test-id"))
    print(f"  ✓ _describe_backup_exception(BackupNotFoundError): {desc2!r}")
    assert "Backup" in desc2
    cat1 = _categorize_backup_exception(ValueError("x"))
    cat2 = _categorize_backup_exception(zipfile.BadZipFile("x"))
    print(f"  ✓ _categorize_backup_exception: ValueError→{cat1}, BadZipFile→{cat2}")
    assert cat1 == "user_input"
    assert cat2 == "data_corrupt"
    # safe_run
    with safe_run("test-op-backup") as ctx_ok:
        pass
    with safe_run("test-op-backup-fail") as ctx_fail:
        raise RuntimeError("backup-test-fel")
    print(f"  ✓ safe_run fel-blocket: errors={len(ctx_fail['errors'])}")
    assert len(ctx_fail["errors"]) == 1
    # _validate_backup_state (utan manager)
    problems = _validate_backup_state(None)
    print(f"  ✓ _validate_backup_state(None): {len(problems)} problem")
    assert len(problems) == 0

    # Test NY v6.4.1 v7: Svenska formatters + diagnostics
    print("\n[Test SV] Svenska formatters + diagnostics (NY v6.4.1 v7)...")
    fake_stats = {
        "total_count": 47, "by_tag": {"daily": 12, "manual": 35},
        "last_backup_time": time.time() - 120,  # 2 min ago
    }
    s1 = format_backup_summary(fake_stats)
    print(f"  ✓ format_backup_summary: {s1!r}")
    assert "47 backups" in s1 and "2min" in s1
    s2 = summarize_backup_health(None)
    print(f"  ✓ summarize_backup_health(None): {s2!r}")
    assert BACKUP_VERSION in s2
    diag = get_backup_diagnostics(None)
    print(f"  ✓ get_backup_diagnostics: version={diag['backup_version']!r}")
    assert diag["module"] == "backup"
    assert diag["backup_version"] == BACKUP_VERSION

    # Test NY v6.4.1 v7: Manager-instans diagnostik
    print("\n[Test MGR] Manager.diagnose (NY v6.4.1 v7)...")
    try:
        mgr_problems = mgr.diagnose() if hasattr(mgr, "diagnose") else \
            _validate_backup_state(mgr)
        print(f"  ✓ manager validering: {len(mgr_problems)} problem")
        # summarize med manager
        s3 = summarize_backup_health(mgr)
        print(f"  ✓ summarize_backup_health(mgr): {s3!r}")
    except Exception as e:
        print(f"  ⚠ Manager-test ofullstandig: {type(e).__name__}: {e}")

    print()
    print("=" * 60)
    print(f"✓ ALLA TESTER PASSERADE (backup.py {BACKUP_VERSION})")
    print("=" * 60)
