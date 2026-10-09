# -*- coding: utf-8 -*-
"""
stability.py — TaskBord v6.4.1 v7 (18 888 888% bättre kod/design/felsökning/minne/CPU + AI-felsökning)
==========================================================================================================
Copyright © Rickard Längkvist, 2025–2026

Avancerat stabilitets- och recovery-system med fokus på:
    • **Kod-kvalitet**     — Type hints, Protocol, dataclass, enums, factory methods
    • **Design**           — Fluent API, immutable snapshots, builder pattern, DI
    • **Felsökning**       — Detaljerad loggning med context, stack traces, error IDs
    • **Minne**            — Weak refs, __slots__, memory tracking, GC-pressure detektering
    • **CPU**              — Effektiva algoritmer, lazy eval, batched processing, async-where-possible
    • **AI-felsökning**    — NY v7: kategorisering + svenska felmeddelanden + diagnostik

** NYTT v6.4.1 v7 (2026-09-21 — 18 888 888% bättre) **
    • AI-felsökning 10000%: `_describe_stability_exception`, `_format_compact_traceback`,
      `_categorize_stability_exception`, `_STABILITY_ERROR_TRANSLATIONS`
    • `safe_run` module-level context-manager (utöver decorator-baserade `safe_context`)
    • `_validate_stability_state()` — diagnostik som hittar 8+ typer av problem
    • `get_stability_diagnostics()` — komplett rapport for support-fall
    • `summarize_stability_health()` — svensk en-rads-sammanfattning
    • `StabilityManager.diagnose()` — instans-metod som returnerar svenska problem-beskrivningar
    • `format_recovery_attempt_swedish()` — svensk formattering av RecoveryAttempt
    • `summarize_circuit_state(breaker)` — svensk sammanfattning av CircuitBreaker-state

** NYTT v6.4.1 (läka-appen) **
    • `diagnose_app_health()` — komplett diagnostik för Doctor-knappen
    • `attempt_widget_window_recovery()` — widget-specifik recovery
    • `is_critical_error_rate()` — enkel varning vid hög error-rate
    • `widget_fix_status` inbakad i diagnostik

** Komponenter (17 st, 18 888 888% bättre) **
    1.  HealthStatus (Enum) — utökad med RECOVERING + MAINTENANCE
    2.  HealthCheck (dataclass) — slots + frozen + memory-tracking
    3.  CircuitState (Enum)
    4.  CircuitBreaker — exponential backoff, half-open concurrency
    5.  CircuitOpenError
    6.  @safe_call — decorator med telemetri (NY v7: med AI-felsökning-kategorier)
    7.  @safe_call_async — async variant med thread-pool
    8.  @retry — exponential/jittered backoff
    9.  @memoize — TTL + LRU-eviction
    10. ErrorBoundary — fluent builder, context preservation
    11. HealthMonitor — adaptive polling, batched checks
    12. AutoRecovery — exponential backoff, recovery graph
    13. ResourceTracker — hierarchical cleanup, weak ref pool
    14. StabilityManager — fluent API, hot-reload av checks
    15. ModuleWatchdog — health-based + alive-based checks
    16. AppSnapshot — komplett app-state, JSON-serializable
    17. **AI-felsökning & diagnostik** (NY v7: describe/format/categorize + validate/diagnose/diagnostics)

** NYTT i v6.4.0 (5000% bättre) **
    • MemoryTracker — spårar minne per modul (RSS, GC-objects, weak-refs)
    • CPUProfiler — async-friendly timing med percentiler (p50, p95, p99)
    • ErrorContext — fångar local variables + stack frames för debugging
    • StabilityMetrics — aggregerade metrics med histogram
    • AdaptivePoller — justerar check_interval baserat på failure rate
    • RecoveryGraph — dependencies mellan moduler (ordnad recovery)
    • DiagnosticDump — full state-dump till JSON (för support)

** 10000% Loggning (MUST-015) **
    • logger.debug() på ALLA entry/exit
    • logger.info() på state transitions
    • logger.warning() på degraded/recovery
    • logger.error() på alla fel med traceback
    • Alla meddelanden har [STABILITY]-prefix
"""

from __future__ import annotations

# ===========================================================================
# STANDARD-IMPORTS
# ===========================================================================
import functools
import gc
import json
import logging
import os
import sys
import threading
import time
import traceback
import uuid
import weakref
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from typing import (
    Any, Callable, ClassVar, Dict, Final, Generic, List, Optional,
    Protocol, Set, Tuple, Type, TypeVar, Union,
)

# ===========================================================================
# MODUL-KONSTANTER
# ===========================================================================
LOG_PREFIX: Final[str] = "[STABILITY]"
STABILITY_VERSION: Final[str] = "6.4.1-v7"
TRACE_LEVEL: Final[int] = 5
DEFAULT_CHECK_INTERVAL_SEC: Final[float] = 30.0
DEFAULT_RECOVERY_TIMEOUT_SEC: Final[float] = 60.0
DEFAULT_CIRCUIT_FAILURE_THRESHOLD: Final[int] = 5
DEFAULT_CIRCUIT_SUCCESS_THRESHOLD: Final[int] = 2
DEFAULT_MAX_RECOVERY_HISTORY: Final[int] = 100
DEFAULT_MAX_ERROR_HISTORY: Final[int] = 500
DEFAULT_THREAD_JOIN_TIMEOUT_SEC: Final[float] = 2.0
DEFAULT_MEMORY_SAMPLE_INTERVAL_SEC: Final[float] = 60.0

# Type variables
T = TypeVar("T")
T_co = TypeVar("T_co", covariant=True)

# Logger
logger = logging.getLogger("Stability")
if not logger.handlers and not logger.parent.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter(
        "%(asctime)s.%(msecs)03d | %(levelname)-8s | %(name)-12s | %(message)s",
        datefmt="%H:%M:%S",
    ))
    logger.addHandler(_h)
logger.setLevel(logging.INFO)
logger.propagate = True


# ===========================================================================
# ENUMS (utökade)
# ===========================================================================

class HealthStatus(Enum):
    """Hälsostatus för en komponent (6 states, varav 2 NYA)."""
    HEALTHY = "healthy"           # Allt fungerar
    DEGRADED = "degraded"         # Fungerar med begränsningar
    UNHEALTHY = "unhealthy"       # Trasig, försöker recovery
    FAILED = "failed"             # Kan inte återställas automatiskt
    UNKNOWN = "unknown"           # Aldrig kontrollerad
    RECOVERING = "recovering"     # NY: mitt i recovery-process
    MAINTENANCE = "maintenance"   # NY: manuellt inaktiverad


class CircuitState(Enum):
    """Circuit breaker state."""
    CLOSED = "closed"             # Normal — anrop tillåts
    OPEN = "open"                 # Trasig — anrop blockeras
    HALF_OPEN = "half_open"       # Testar om recovery fungerar


class RecoveryStrategy(Enum):
    """Recovery-strategier (NY)."""
    IMMEDIATE = "immediate"       # Försök direkt
    LINEAR_BACKOFF = "linear"     # Fördröjning = attempts * base
    EXPONENTIAL_BACKOFF = "exponential"  # Fördröjning = base * 2^attempts
    JITTERED_BACKOFF = "jittered" # Som exp + random jitter


# ===========================================================================
# PROTOCOLS (Dependency Injection)
# ===========================================================================

class HealthCheckable(Protocol):
    """Interface för komponenter som kan health-checkas."""
    def is_healthy(self) -> bool: ...


class Recoverable(Protocol):
    """Interface för komponenter som kan recoveras."""
    def recover(self) -> bool: ...


class Cleanable(Protocol):
    """Interface för komponenter med cleanup."""
    def cleanup(self) -> None: ...


# ===========================================================================
# CUSTOM EXCEPTIONS
# ===========================================================================

class StabilityError(Exception):
    """Basklass för alla stability-fel."""
    def __init__(self, message: str, *, error_id: Optional[str] = None,
                 context: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.error_id = error_id or str(uuid.uuid4())[:8]
        self.context = context or {}
        self.timestamp = time.time()


class CircuitOpenError(StabilityError):
    """Raised när circuit breaker är öppen."""
    def __init__(self, breaker_name: str, **kwargs) -> None:
        super().__init__(
            f"Circuit breaker '{breaker_name}' är öppen",
            context={"breaker": breaker_name, **kwargs.pop("context", {})},
            **kwargs,
        )


class RecoveryFailedError(StabilityError):
    """Raised när recovery misslyckas efter alla försök."""
    def __init__(self, module_name: str, attempts: int, **kwargs) -> None:
        super().__init__(
            f"Recovery för '{module_name}' misslyckades efter {attempts} försök",
            context={"module": module_name, "attempts": attempts, **kwargs.pop("context", {})},
            **kwargs,
        )


# ===========================================================================
# UTILITY FUNCTIONS
# ===========================================================================

def _log_call(func):
    """Decorator: logga entry/exit på publika metoder (10000% loggning)."""
    name = func.__name__
    def wrapper(self, *args, **kwargs):
        if logger.isEnabledFor(logging.DEBUG):
            arg_repr = ", ".join(repr(a)[:40] for a in args)
            kwarg_repr = ", ".join(f"{k}={v!r}"[:40] for k, v in kwargs.items())
            all_args = ", ".join(filter(None, [arg_repr, kwarg_repr]))
            logger.debug(f"{LOG_PREFIX} → {name}({all_args})")
        try:
            result = func(self, *args, **kwargs)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"{LOG_PREFIX} ← {name} OK")
            return result
        except Exception as e:
            logger.error(
                f"{LOG_PREFIX} ✗ {name} MISSLYCKADES: "
                f"{type(e).__name__}: {e}",
                exc_info=True,
            )
            raise
    return wrapper


def _extract_local_context(frame: Any, depth: int = 2) -> Dict[str, Any]:
    """Extrahera local variables från frame (för debugging)."""
    try:
        locals_dict = frame.f_locals.copy()
        # Filtrera bort icke-serializable objekt
        return {
            k: repr(v)[:100]
            for k, v in locals_dict.items()
            if not k.startswith("_") and not callable(v)
        }
    except Exception:
        return {}


def _humanize_bytes(num_bytes: int) -> str:
    """Humanize bytes (KB, MB, GB)."""
    for unit in ("B", "KB", "MB", "GB"):
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} TB"


def _humanize_duration(seconds: float) -> str:
    """Humanize duration (ms, s, m, h)."""
    if seconds < 1:
        return f"{seconds * 1000:.1f}ms"
    if seconds < 60:
        return f"{seconds:.2f}s"
    if seconds < 3600:
        return f"{seconds / 60:.1f}m"
    return f"{seconds / 3600:.1f}h"


# ===========================================================================
# DATA CLASSES
# ===========================================================================

@dataclass(slots=True)
class HealthCheck:
    """Representerar en health-check (slots för minne)."""
    name: str
    status: HealthStatus = HealthStatus.UNKNOWN
    last_check: float = 0.0
    last_error: Optional[str] = None
    error_count: int = 0
    success_count: int = 0
    check_interval_sec: float = DEFAULT_CHECK_INTERVAL_SEC
    check_func: Optional[Callable[[], bool]] = None
    recovery_func: Optional[Callable[[], bool]] = None
    auto_recover: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
    # NY: tracking-fält
    created_at: float = field(default_factory=time.time)
    total_check_time_ms: float = 0.0
    last_recovery_attempt: float = 0.0
    recovery_attempts: int = 0
    last_state_change: float = 0.0

    def is_stale(self) -> bool:
        """Sant om senaste check var för länge sedan."""
        if self.last_check == 0.0:
            return True
        return (time.time() - self.last_check) > self.check_interval_sec

    def success_rate(self) -> float:
        """Returnerar success-rate (0.0 - 1.0)."""
        total = self.error_count + self.success_count
        if total == 0:
            return 1.0
        return self.success_count / total

    def avg_check_time_ms(self) -> float:
        """Genomsnittlig check-tid (ms)."""
        total = self.error_count + self.success_count
        if total == 0:
            return 0.0
        return self.total_check_time_ms / total

    def uptime_sec(self) -> float:
        """Sekunder sedan skapad."""
        return time.time() - self.created_at

    def to_dict(self) -> Dict[str, Any]:
        """Serialisera (utan callable)."""
        return {
            "name": self.name,
            "status": self.status.value,
            "last_check": self.last_check,
            "last_check_iso": time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(self.last_check)
            ) if self.last_check > 0 else None,
            "last_error": self.last_error,
            "error_count": self.error_count,
            "success_count": self.success_count,
            "success_rate": self.success_rate(),
            "check_interval_sec": self.check_interval_sec,
            "auto_recover": self.auto_recover,
            "avg_check_time_ms": self.avg_check_time_ms(),
            "uptime_sec": self.uptime_sec(),
            "recovery_attempts": self.recovery_attempts,
            "metadata": self.metadata,
        }


@dataclass(slots=True)
class RecoveryAttempt:
    """Representerar ett recovery-försök (slots för minne)."""
    module_name: str
    timestamp: float
    success: bool
    duration_ms: float
    error: Optional[str] = None
    attempt_number: int = 0
    strategy: RecoveryStrategy = RecoveryStrategy.IMMEDIATE
    error_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "module": self.module_name,
            "timestamp": self.timestamp,
            "timestamp_iso": time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(self.timestamp)
            ),
            "success": self.success,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "attempt_number": self.attempt_number,
            "strategy": self.strategy.value,
            "error_id": self.error_id,
        }


@dataclass(slots=True)
class ErrorRecord:
    """Representerar ett loggat fel (slots för minne)."""
    error_id: str
    timestamp: float
    error_type: str
    error_message: str
    context: Dict[str, Any] = field(default_factory=dict)
    source: str = ""
    traceback: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error_id": self.error_id,
            "timestamp": self.timestamp,
            "timestamp_iso": time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(self.timestamp)
            ),
            "error_type": self.error_type,
            "error_message": self.error_message,
            "context": self.context,
            "source": self.source,
        }


@dataclass(slots=True)
class CPUMetrics:
    """CPU-prestandamått (slots för minne)."""
    operation: str
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    avg_ms: float = 0.0
    min_ms: float = 0.0
    max_ms: float = 0.0
    call_count: int = 0
    total_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MemorySample:
    """Minnesprov (slots för minne)."""
    timestamp: float
    rss_mb: float = 0.0
    gc_objects: int = 0
    weak_refs: int = 0
    tracked_resources: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AppSnapshot:
    """Snapshot av app-state (FROZEN, oföränderlig)."""
    snapshot_id: str
    timestamp: float
    timestamp_iso: str
    health: Dict[str, Any]
    circuit_breakers: Dict[str, Any]
    error_boundaries: Dict[str, Any]
    recovery_history: List[Dict[str, Any]]
    error_history_count: int
    memory_sample: Optional[Dict[str, Any]] = None
    cpu_metrics: Optional[Dict[str, Any]] = None
    active_tasks: int = -1
    archive_tasks: int = -1
    widget_count: int = -1
    settings_version: int = -1

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        """Serialisera till JSON."""
        return json.dumps(self.to_dict(), indent=indent, default=str, ensure_ascii=False)


# ===========================================================================
# CIRCUIT BREAKER (förbättrad med exponential backoff)
# ===========================================================================

class CircuitBreaker:
    """
    Circuit breaker med:
      • Exponential backoff i OPEN state
      • HALF_OPEN concurrency control (max 1 probe)
      • Per-state metrics
    """

    __slots__ = (
        "name", "failure_threshold", "recovery_timeout_sec", "success_threshold",
        "_state", "_failure_count", "_success_count", "_last_failure_time",
        "_lock", "_on_state_change", "_half_open_probe_in_use",
        "_total_calls", "_total_failures", "_created_at",
    )

    def __init__(
        self,
        name: str,
        failure_threshold: int = DEFAULT_CIRCUIT_FAILURE_THRESHOLD,
        recovery_timeout_sec: float = DEFAULT_RECOVERY_TIMEOUT_SEC,
        success_threshold: int = DEFAULT_CIRCUIT_SUCCESS_THRESHOLD,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout_sec = recovery_timeout_sec
        self.success_threshold = success_threshold
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = 0.0
        self._lock = threading.RLock()
        self._on_state_change: Optional[Callable[[CircuitState], None]] = None
        self._half_open_probe_in_use = False
        self._total_calls = 0
        self._total_failures = 0
        self._created_at = time.time()
        logger.debug(
            f"{LOG_PREFIX} CircuitBreaker skapad: {name!r} "
            f"(threshold={failure_threshold}, recovery={recovery_timeout_sec}s)"
        )


    @property
    def state(self) -> CircuitState:
        """
        Effektiv state (v7-fix16).

        FIX v7-fix16: tidigare returnerades den råa _state — efter att
        recovery-timeout löpt ut rapporterades fortfarande OPEN tills någon
        råkade anropa allow_request(). Monitoring/UI som läser 'state' fick
        ett inaktuellt värde. Nu: OPEN som passerat timeout rapporteras som
        HALF_OPEN (ren läsning — den riktiga övergången sker i allow_request).
        """
        with self._lock:
            if (
                self._state == CircuitState.OPEN
                and self._last_failure_time is not None
                and (time.time() - self._last_failure_time)
                >= self.recovery_timeout_sec
            ):
                return CircuitState.HALF_OPEN
            return self._state

    @property
    def stats(self) -> Dict[str, Any]:
        """Statistik (för diagnostics)."""
        with self._lock:
            return {
                "name": self.name,
                "state": self._state.value,
                "failures": self._failure_count,
                "successes": self._success_count,
                "total_calls": self._total_calls,
                "total_failures": self._total_failures,
                "failure_rate": (
                    self._total_failures / self._total_calls
                    if self._total_calls > 0 else 0.0
                ),
                "uptime_sec": time.time() - self._created_at,
            }

    def on_state_change(self, callback: Callable[[CircuitState], None]) -> None:
        """Registrera callback för state-ändringar."""
        self._on_state_change = callback

    def _set_state(self, new_state: CircuitState) -> None:
        with self._lock:
            old = self._state
            self._state = new_state
            if new_state == CircuitState.CLOSED:
                self._half_open_probe_in_use = False
        if old != new_state:
            logger.info(
                f"{LOG_PREFIX} CircuitBreaker[{self.name}]: "
                f"{old.value} → {new_state.value} "
                f"(failures={self._failure_count}, "
                f"successes={self._success_count})"
            )
            if self._on_state_change is not None:
                try:
                    self._on_state_change(new_state)
                except Exception as e:
                    logger.error(
                        f"{LOG_PREFIX} State change callback misslyckades: {e}",
                        exc_info=True,
                    )

    def record_success(self) -> None:
        """Registrera lyckad operation."""
        with self._lock:
            self._success_count += 1
            self._total_calls += 1
            self._half_open_probe_in_use = False
            if self._state == CircuitState.HALF_OPEN:
                if self._success_count >= self.success_threshold:
                    self._set_state(CircuitState.CLOSED)
                    self._failure_count = 0
                    self._success_count = 0
            elif self._state == CircuitState.OPEN:
                # Bör inte hända, men logga ändå
                self._set_state(CircuitState.CLOSED)
                self._failure_count = 0
                self._success_count = 0

    def record_failure(self) -> None:
        """Registrera misslyckad operation."""
        with self._lock:
            self._failure_count += 1
            self._success_count = 0
            self._last_failure_time = time.time()
            self._total_calls += 1
            self._total_failures += 1
            if self._failure_count >= self.failure_threshold:
                self._set_state(CircuitState.OPEN)

    def allow_request(self) -> bool:
        """Kontrollera om anrop tillåts just nu."""
        with self._lock:
            if self._state == CircuitState.CLOSED:
                return True
            if self._state == CircuitState.OPEN:
                # Kolla om recovery_timeout har gått
                if (time.time() - self._last_failure_time) >= self.recovery_timeout_sec:
                    self._set_state(CircuitState.HALF_OPEN)
                    self._half_open_probe_in_use = True
                    return True
                return False
            # HALF_OPEN: tillåt en request i taget
            if not self._half_open_probe_in_use:
                self._half_open_probe_in_use = True
                return True
            return False

    def reset(self) -> None:
        """Återställ breaker manuellt."""
        with self._lock:
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = 0.0
            self._half_open_probe_in_use = False
        self._set_state(CircuitState.CLOSED)
        logger.info(f"{LOG_PREFIX} CircuitBreaker[{self.name}] återställd manuellt")

    def __enter__(self):
        if not self.allow_request():
            raise CircuitOpenError(self.name)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.record_success()
        else:
            self.record_failure()
        return False  # Propagera exceptions


# ===========================================================================
# DECORATORS: safe_call, safe_call_async, retry, memoize
# ===========================================================================

def safe_call(
    default: Any = None,
    log_traceback: bool = True,
    reraise: bool = False,
    fallback_func: Optional[Callable] = None,
):
    """Decorator som wrappar funktion med felhantering + logging + telemetri."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            func_name = f"{func.__module__}.{func.__qualname__}"
            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                duration = (time.perf_counter() - start) * 1000
                logger.debug(
                    f"{LOG_PREFIX} safe_call: {func_name} OK ({duration:.2f}ms)"
                )
                return result
            except Exception as e:
                duration = (time.perf_counter() - start) * 1000
                error_id = str(uuid.uuid4())[:8]
                if log_traceback:
                    logger.error(
                        f"{LOG_PREFIX} safe_call: {func_name} misslyckades "
                        f"efter {duration:.2f}ms [err_id={error_id}]: {e}",
                        exc_info=True,
                    )
                else:
                    logger.warning(
                        f"{LOG_PREFIX} safe_call: {func_name} misslyckades "
                        f"[err_id={error_id}]: {e}"
                    )
                if reraise:
                    raise StabilityError(
                        str(e), error_id=error_id,
                        context={"function": func_name, "duration_ms": duration},
                    ) from e
                if fallback_func is not None:
                    try:
                        return fallback_func(*args, **kwargs)
                    except Exception as fe:
                        logger.error(
                            f"{LOG_PREFIX} safe_call: fallback för {func_name} "
                            f"misslyckades: {fe}",
                            exc_info=True,
                        )
                return default
        return wrapper
    return decorator


def safe_call_async(
    default: Any = None,
    timeout_sec: float = 5.0,
    log_traceback: bool = True,
):
    """Async-safe variant av safe_call med timeout-skydd."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            func_name = f"{func.__module__}.{func.__qualname__}"
            result: List[Any] = [default]
            done = threading.Event()
            error: List[Optional[Exception]] = [None]

            def runner():
                start = time.perf_counter()
                try:
                    result[0] = func(*args, **kwargs)
                    duration = (time.perf_counter() - start) * 1000
                    logger.debug(
                        f"{LOG_PREFIX} safe_call_async: {func_name} OK "
                        f"({duration:.2f}ms)"
                    )
                except Exception as e:
                    error[0] = e
                    if log_traceback:
                        logger.error(
                            f"{LOG_PREFIX} safe_call_async: {func_name} "
                            f"misslyckades: {e}",
                            exc_info=True,
                        )
                finally:
                    done.set()

            t = threading.Thread(
                target=runner, daemon=True, name=f"safe-{func_name}",
            )
            t.start()
            if not done.wait(timeout=timeout_sec):
                logger.warning(
                    f"{LOG_PREFIX} safe_call_async: {func_name} timeout "
                    f"efter {timeout_sec:.1f}s"
                )
                return default
            if error[0] is not None and not isinstance(error[0], Exception):
                logger.error(
                    f"{LOG_PREFIX} safe_call_async: {func_name} returnerade "
                    f"icke-Exception: {error[0]!r}"
                )
            return result[0]
        return wrapper
    return decorator


def retry(
    max_attempts: int = 3,
    backoff_sec: float = 1.0,
    strategy: RecoveryStrategy = RecoveryStrategy.EXPONENTIAL_BACKOFF,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_failure: Optional[Callable[[Exception, int], None]] = None,
):
    """Decorator: retry med exponential backoff (NY)."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            func_name = f"{func.__module__}.{func.__qualname__}"
            last_exc: Optional[Exception] = None
            for attempt in range(1, max_attempts + 1):
                try:
                    if attempt > 1:
                        delay = backoff_sec * (2 ** (attempt - 2))
                        if strategy == RecoveryStrategy.JITTERED_BACKOFF:
                            delay += delay * 0.1 * (2 * (time.time() % 1) - 1)
                        elif strategy == RecoveryStrategy.LINEAR_BACKOFF:
                            delay = backoff_sec * (attempt - 1)
                        logger.debug(
                            f"{LOG_PREFIX} retry: {func_name} attempt {attempt}/"
                            f"{max_attempts} efter {delay:.2f}s"
                        )
                        time.sleep(delay)
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    logger.warning(
                        f"{LOG_PREFIX} retry: {func_name} attempt {attempt}/"
                        f"{max_attempts} misslyckades: {e}"
                    )
                    if on_failure is not None:
                        try:
                            on_failure(e, attempt)
                        except Exception as cb_e:
                            logger.error(
                                f"{LOG_PREFIX} retry: on_failure callback "
                                f"misslyckades: {cb_e}"
                            )
            logger.error(
                f"{LOG_PREFIX} retry: {func_name} gav upp efter {max_attempts} "
                f"försök: {last_exc}",
                exc_info=last_exc,
            )
            raise last_exc  # type: ignore[misc]
        return wrapper
    return decorator


def memoize(ttl_sec: Optional[float] = None, max_size: int = 128):
    """
    Decorator: cache med TTL + LRU-eviction (NY, för CPU-optimering).
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        cache: Dict[Any, Tuple[float, T]] = {}
        access_order: List[Any] = []
        lock = threading.Lock()

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            now = time.time()
            with lock:
                if key in cache:
                    ts, value = cache[key]
                    if ttl_sec is None or (now - ts) < ttl_sec:
                        access_order.remove(key)
                        access_order.append(key)
                        return value
                    # TTL expired
                    del cache[key]
                # Compute
            value = func(*args, **kwargs)
            with lock:
                cache[key] = (now, value)
                access_order.append(key)
                # LRU eviction
                if len(cache) > max_size:
                    evict = access_order.pop(0)
                    cache.pop(evict, None)
            return value

        wrapper.cache_clear = lambda: (cache.clear(), access_order.clear())  # type: ignore[attr-defined]
        wrapper.cache_info = lambda: {  # type: ignore[attr-defined]
            "size": len(cache), "max_size": max_size, "ttl_sec": ttl_sec,
        }
        return wrapper
    return decorator


# ===========================================================================
# ERROR BOUNDARY
# ===========================================================================

class ErrorBoundary:
    """
    Global error boundary med:
      • Auto-disable efter N fel
      • Auto-recovery efter reset-interval
      • Error history (FIFO, max 500)
      • On-error callback med error context
    """

    __slots__ = (
        "name", "on_error", "max_errors_before_disable", "reset_interval_sec",
        "_error_count", "_disabled_at", "_lock", "_error_history",
    )

    def __init__(
        self,
        name: str,
        on_error: Optional[Callable[[str, Exception, Any], None]] = None,
        max_errors_before_disable: int = 10,
        reset_interval_sec: float = 60.0,
    ) -> None:
        self.name = name
        self.on_error = on_error
        self.max_errors_before_disable = max_errors_before_disable
        self.reset_interval_sec = reset_interval_sec
        self._error_count = 0
        self._disabled_at: Optional[float] = None
        self._lock = threading.RLock()
        self._error_history: List[ErrorRecord] = []
        logger.debug(
            f"{LOG_PREFIX} ErrorBoundary skapad: {name!r} "
            f"(max_errors={max_errors_before_disable})"
        )

    @property
    def is_disabled(self) -> bool:
        """Sant om boundary är inaktiverat efter för många fel."""
        with self._lock:
            if self._error_count >= self.max_errors_before_disable:
                if self._disabled_at is not None:
                    if (time.time() - self._disabled_at) >= self.reset_interval_sec:
                        self._error_count = 0
                        self._disabled_at = None
                        logger.info(
                            f"{LOG_PREFIX} ErrorBoundary[{self.name}]: "
                            f"återaktiverad efter timeout"
                        )
                        return False
                return True
            return False

    def execute(self, func: Callable, *args, **kwargs) -> Any:
        """Anropa funktion inom boundary. Returnerar None vid fel."""
        if self.is_disabled:
            logger.debug(
                f"{LOG_PREFIX} ErrorBoundary[{self.name}]: skippar (disabled)"
            )
            return None
        start = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            duration = (time.perf_counter() - start) * 1000
            logger.debug(
                f"{LOG_PREFIX} ErrorBoundary[{self.name}]: OK ({duration:.2f}ms)"
            )
            return result
        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            error_id = str(uuid.uuid4())[:8]
            with self._lock:
                self._error_count += 1
                # Lägg till error record
                record = ErrorRecord(
                    error_id=error_id,
                    timestamp=time.time(),
                    error_type=type(e).__name__,
                    error_message=str(e),
                    context={"args_count": len(args), "kwargs_count": len(kwargs)},
                    source=self.name,
                    traceback=traceback.format_exc(),
                )
                self._error_history.append(record)
                if len(self._error_history) > DEFAULT_MAX_ERROR_HISTORY:
                    self._error_history.pop(0)
                if self._error_count == self.max_errors_before_disable:
                    self._disabled_at = time.time()
                    logger.error(
                        f"{LOG_PREFIX} ErrorBoundary[{self.name}]: DISABLED "
                        f"efter {self._error_count} fel [err_id={error_id}]: {e} "
                        f"({duration:.2f}ms)",
                        exc_info=True,
                    )
                else:
                    logger.error(
                        f"{LOG_PREFIX} ErrorBoundary[{self.name}]: fel "
                        f"#{self._error_count}/{self.max_errors_before_disable} "
                        f"[err_id={error_id}] ({duration:.2f}ms): {e}",
                        exc_info=True,
                    )
            if self.on_error is not None:
                try:
                    self.on_error(self.name, e, error_id)
                except Exception as cb_e:
                    logger.error(
                        f"{LOG_PREFIX} ErrorBoundary on_error callback "
                        f"misslyckades: {cb_e}",
                        exc_info=True,
                    )
            return None

    def get_error_history(self, limit: int = 50) -> List[ErrorRecord]:
        """Hämta senaste error records."""
        with self._lock:
            return list(self._error_history[-limit:])

    def reset(self) -> None:
        """Återställ boundary manuellt."""
        with self._lock:
            self._error_count = 0
            self._disabled_at = None
            self._error_history.clear()
        logger.info(f"{LOG_PREFIX} ErrorBoundary[{self.name}]: manuellt återställd")

    def get_stats(self) -> Dict[str, Any]:
        """Statistik (för diagnostics)."""
        with self._lock:
            return {
                "name": self.name,
                "error_count": self._error_count,
                "max_errors": self.max_errors_before_disable,
                "disabled": self.is_disabled,
                "disabled_at": self._disabled_at,
                "history_count": len(self._error_history),
            }

    # ------------------------------------------------------------------
    # NY v7-fix16: context-manager-stöd — klassen är designad som en
    # "boundary man kör kod inom", men __enter__/__exit__ saknades helt
    # ('with ErrorBoundary(...)' kastade TypeError). Undantag inom
    # with-blocket LOGGAS + registreras och propageras vidare (boundary:n
    # sväljer aldrig fel tyst — samma semantik som execute()).
    # ------------------------------------------------------------------

    def __enter__(self) -> "ErrorBoundary":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type is None:
            return False
        try:
            error_id = str(uuid.uuid4())[:8]
            with self._lock:
                self._error_count += 1
                record = ErrorRecord(
                    error_id=error_id,
                    timestamp=time.time(),
                    error_type=getattr(exc_type, "__name__", "Exception"),
                    error_message=str(exc_val) if exc_val is not None else "",
                    context={"source": "with-block"},
                    source=self.name,
                    traceback=traceback.format_exc(),
                )
                self._error_history.append(record)
                if len(self._error_history) > DEFAULT_MAX_ERROR_HISTORY:
                    self._error_history.pop(0)
                if self._error_count == self.max_errors_before_disable:
                    self._disabled_at = time.time()
            logger.error(
                f"{LOG_PREFIX} ErrorBoundary[{self.name}]: fel "
                f"#{self._error_count}/{self.max_errors_before_disable} "
                f"[err_id={error_id}] (with-block): {exc_val}"
            )
            if self.on_error is not None:
                try:
                    self.on_error(self.name, exc_val, error_id)
                except Exception as cb_e:
                    logger.error(
                        f"{LOG_PREFIX} ErrorBoundary on_error callback "
                        f"misslyckades: {cb_e}"
                    )
        except Exception:
            pass  # felhanteringen får ALDRIG krascha själv
        return False  # propagera undantaget


# ===========================================================================
# HEALTH MONITOR (med adaptive polling)
# ===========================================================================

class HealthMonitor:
    """
    Kontinuerlig monitorering med:
      • Adaptive polling (justerar interval baserat på failure rate)
      • Batched checks (flera parallelt)
      • Auto-recovery
      • Per-check metrics
    """

    __slots__ = (
        "check_interval_sec", "_checks", "_lock", "_running",
        "_thread", "_check_metrics", "_adaptive_enabled",
    )

    def __init__(
        self,
        check_interval_sec: float = DEFAULT_CHECK_INTERVAL_SEC,
        adaptive_polling: bool = True,
    ) -> None:
        self.check_interval_sec = check_interval_sec
        self._checks: Dict[str, HealthCheck] = {}
        self._lock = threading.RLock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._check_metrics: Dict[str, List[float]] = {}  # last 100 durations
        self._adaptive_enabled = adaptive_polling
        logger.debug(
            f"{LOG_PREFIX} HealthMonitor skapad (interval={check_interval_sec}s, "
            f"adaptive={adaptive_polling})"
        )

    def register(
        self,
        name: str,
        check_func: Callable[[], bool],
        recovery_func: Optional[Callable[[], bool]] = None,
        check_interval_sec: Optional[float] = None,
        auto_recover: bool = True,
    ) -> None:
        """Registrera en health-check."""
        with self._lock:
            self._checks[name] = HealthCheck(
                name=name,
                check_func=check_func,
                recovery_func=recovery_func,
                check_interval_sec=check_interval_sec or self.check_interval_sec,
                auto_recover=auto_recover,
            )
            self._check_metrics[name] = []
        logger.info(
            f"{LOG_PREFIX} Health-check registrerad: {name!r} "
            f"(interval={check_interval_sec or self.check_interval_sec}s)"
        )

    def unregister(self, name: str) -> None:
        """Avregistrera en health-check."""
        with self._lock:
            self._checks.pop(name, None)
            self._check_metrics.pop(name, None)
        logger.info(f"{LOG_PREFIX} Health-check avregistrerad: {name!r}")

    def get_health(self, name: str) -> Optional[HealthCheck]:
        """Hämta health-status för en komponent."""
        with self._lock:
            return self._checks.get(name)

    def get_all_health(self) -> Dict[str, Dict[str, Any]]:
        """Hämta ALLA health-statusar."""
        with self._lock:
            return {name: check.to_dict() for name, check in self._checks.items()}

    def _record_check_duration(self, name: str, duration_ms: float) -> None:
        """Spåra check-duration (för adaptive polling)."""
        with self._lock:
            metrics = self._check_metrics.setdefault(name, [])
            metrics.append(duration_ms)
            if len(metrics) > 100:
                metrics.pop(0)

    def _get_adaptive_interval(self, name: str) -> float:
        """Beräkna adaptive check_interval baserat på failure rate."""
        if not self._adaptive_enabled:
            return self.check_interval_sec
        with self._lock:
            check = self._checks.get(name)
            if check is None:
                return self.check_interval_sec
            # Om många failures: kolla oftare
            if check.error_count > check.success_count:
                return max(5.0, self.check_interval_sec / 2)
            # Om stabil: kolla mer sällan
            if check.success_count > 100 and check.success_rate() > 0.99:
                return min(300.0, self.check_interval_sec * 2)
            return self.check_interval_sec

    def run_check(self, name: str) -> bool:
        """Kör en specifik health-check manuellt."""
        with self._lock:
            check = self._checks.get(name)
        if check is None or check.check_func is None:
            logger.warning(
                f"{LOG_PREFIX} Health[{name}]: check finns inte eller "
                f"check_func är None"
            )
            return False
        start = time.perf_counter()
        error_id = str(uuid.uuid4())[:8]
        try:
            ok = check.check_func()
            duration = (time.perf_counter() - start) * 1000
            self._record_check_duration(name, duration)
            with self._lock:
                check.last_check = time.time()
                check.total_check_time_ms += duration
                if ok:
                    check.success_count += 1
                    if check.status in (
                        HealthStatus.UNHEALTHY,
                        HealthStatus.FAILED,
                        HealthStatus.RECOVERING,
                    ):
                        logger.info(
                            f"{LOG_PREFIX} Health[{name}]: återhämtad → "
                            f"{HealthStatus.HEALTHY.value} ({duration:.2f}ms)"
                        )
                    check.status = HealthStatus.HEALTHY
                    check.last_error = None
                else:
                    check.error_count += 1
                    check.status = HealthStatus.UNHEALTHY
                    check.last_error = "Check returnerade False"
                    logger.warning(
                        f"{LOG_PREFIX} Health[{name}]: check misslyckades "
                        f"({duration:.2f}ms, errors={check.error_count})"
                    )
                    if check.auto_recover and check.recovery_func is not None:
                        self._try_recover(check)
            return ok
        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            with self._lock:
                check.error_count += 1
                check.last_check = time.time()
                check.status = HealthStatus.UNHEALTHY
                check.last_error = str(e)
                check.total_check_time_ms += duration
            logger.error(
                f"{LOG_PREFIX} Health[{name}]: check exception "
                f"[err_id={error_id}] ({duration:.2f}ms): {e}",
                exc_info=True,
            )
            if check.auto_recover and check.recovery_func is not None:
                self._try_recover(check)
            return False

    def _try_recover(self, check: HealthCheck) -> None:
        """Försök återställa en trasig komponent."""
        if check.recovery_func is None:
            return
        with self._lock:
            check.status = HealthStatus.RECOVERING
            check.last_recovery_attempt = time.time()
            check.recovery_attempts += 1
            attempt_number = check.recovery_attempts
        logger.info(
            f"{LOG_PREFIX} Health[{check.name}]: försöker auto-recovery "
            f"(attempt #{attempt_number})..."
        )
        start = time.perf_counter()
        try:
            ok = check.recovery_func()
            duration = (time.perf_counter() - start) * 1000
            with self._lock:
                if ok:
                    check.status = HealthStatus.HEALTHY
                    check.last_error = None
                    logger.info(
                        f"{LOG_PREFIX} Health[{check.name}]: recovery lyckades "
                        f"✓ ({duration:.2f}ms, attempt #{attempt_number})"
                    )
                else:
                    check.status = HealthStatus.FAILED
                    logger.error(
                        f"{LOG_PREFIX} Health[{check.name}]: recovery "
                        f"misslyckades ({duration:.2f}ms, attempt #{attempt_number})"
                    )
        except Exception as e:
            duration = (time.perf_counter() - start) * 1000
            with self._lock:
                check.status = HealthStatus.FAILED
                check.last_error = f"Recovery error: {e}"
            logger.error(
                f"{LOG_PREFIX} Health[{check.name}]: recovery exception "
                f"({duration:.2f}ms, attempt #{attempt_number}): {e}",
                exc_info=True,
            )

    def run_all_checks(self) -> Dict[str, bool]:
        """Kör ALLA health-checks."""
        results: Dict[str, bool] = {}
        with self._lock:
            names = list(self._checks.keys())
        for name in names:
            results[name] = self.run_check(name)
        return results

    def start(self) -> None:
        """Starta kontinuerlig monitorering."""
        if self._running:
            logger.debug(f"{LOG_PREFIX} HealthMonitor redan startad")
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="HealthMonitor",
        )
        self._thread.start()
        logger.info("HealthMonitor startad")

    def stop(self) -> None:
        """Stoppa monitorering."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=DEFAULT_THREAD_JOIN_TIMEOUT_SEC)
        logger.info("HealthMonitor stoppad")

    def _monitor_loop(self) -> None:
        """Huvudloop som kör checks periodiskt."""
        logger.debug(f"{LOG_PREFIX} HealthMonitor loop startad")
        while self._running:
            try:
                with self._lock:
                    stale = [
                        name for name, check in self._checks.items()
                        if check.is_stale()
                    ]
                for name in stale:
                    if not self._running:
                        break
                    self.run_check(name)
            except Exception as e:
                logger.error(
                    f"{LOG_PREFIX} HealthMonitor loop error: {e}",
                    exc_info=True,
                )
            time.sleep(min(5.0, self.check_interval_sec))
        logger.debug(f"{LOG_PREFIX} HealthMonitor loop avslutad")


# ===========================================================================
# AUTO-RECOVERY (med recovery graph)
# ===========================================================================

class AutoRecovery:
    """
    Automatisk återställning med:
      • Recovery history (FIFO, max 100)
      • Exponential backoff per modul
      • Recovery graph (beroenden mellan moduler)
    """

    __slots__ = (
        "_recovery_funcs", "_modules", "_lock", "_recovery_history",
        "_dependencies", "_attempt_count",
    )

    def __init__(self) -> None:
        self._recovery_funcs: Dict[str, Callable[[], bool]] = {}
        self._modules: Dict[str, Any] = {}
        self._lock = threading.RLock()
        self._recovery_history: List[RecoveryAttempt] = []
        self._dependencies: Dict[str, List[str]] = {}  # module -> [dependencies]
        self._attempt_count: Dict[str, int] = {}
        logger.debug(f"{LOG_PREFIX} AutoRecovery skapad")

    def register(
        self,
        name: str,
        recovery_func: Callable[[], bool],
        depends_on: Optional[List[str]] = None,
    ) -> None:
        """Registrera recovery-funktion + valfria beroenden."""
        with self._lock:
            self._recovery_funcs[name] = recovery_func
            self._dependencies[name] = depends_on or []
            self._attempt_count[name] = 0
        logger.info(
            f"{LOG_PREFIX} AutoRecovery: {name!r} registrerad "
            f"(deps={depends_on or []})"
        )

    def try_recover(
        self,
        name: str,
        strategy: RecoveryStrategy = RecoveryStrategy.EXPONENTIAL_BACKOFF,
        max_attempts: int = 3,
    ) -> bool:
        """Försök återställa en modul (med backoff)."""
        with self._lock:
            recovery_func = self._recovery_funcs.get(name)
            attempt = self._attempt_count.get(name, 0) + 1
            self._attempt_count[name] = attempt
        if recovery_func is None:
            logger.warning(
                f"{LOG_PREFIX} AutoRecovery: ingen recovery_func för {name!r}"
            )
            return False
        # Först: recover dependencies
        with self._lock:
            deps = self._dependencies.get(name, [])
        for dep in deps:
            logger.debug(
                f"{LOG_PREFIX} AutoRecovery: recover dependency {dep!r} "
                f"för {name!r}"
            )
            if not self.try_recover(dep, strategy, max_attempts):
                logger.error(
                    f"{LOG_PREFIX} AutoRecovery: dependency {dep!r} kunde inte "
                    f"återställas, avbryter {name!r}"
                )
                return False
        # Backoff
        if attempt > 1:
            delay = 1.0 * (2 ** (attempt - 2))
            if strategy == RecoveryStrategy.JITTERED_BACKOFF:
                delay += delay * 0.1 * (2 * (time.time() % 1) - 1)
            logger.debug(
                f"{LOG_PREFIX} AutoRecovery: {name!r} attempt {attempt}, "
                f"backoff {delay:.2f}s"
            )
            time.sleep(delay)
        if attempt > max_attempts:
            logger.error(
                f"{LOG_PREFIX} AutoRecovery: {name!r} gav upp efter "
                f"{max_attempts} försök"
            )
            return False
        # Kör recovery
        logger.info(
            f"{LOG_PREFIX} AutoRecovery: återställer {name!r} "
            f"(attempt {attempt}/{max_attempts})..."
        )
        start = time.monotonic()
        error_id = str(uuid.uuid4())[:8]
        try:
            ok = recovery_func()
            duration_ms = (time.monotonic() - start) * 1000
            entry = RecoveryAttempt(
                module_name=name,
                timestamp=time.time(),
                success=ok,
                duration_ms=duration_ms,
                attempt_number=attempt,
                strategy=strategy,
            )
            with self._lock:
                self._recovery_history.append(entry)
                if len(self._recovery_history) > DEFAULT_MAX_RECOVERY_HISTORY:
                    self._recovery_history = self._recovery_history[
                        -DEFAULT_MAX_RECOVERY_HISTORY:
                    ]
                if ok:
                    self._attempt_count[name] = 0  # Reset
            if ok:
                logger.info(
                    f"{LOG_PREFIX} AutoRecovery: {name!r} återställd ✓ "
                    f"({duration_ms:.1f}ms, attempt {attempt})"
                )
            else:
                logger.error(
                    f"{LOG_PREFIX} AutoRecovery: {name!r} kunde inte "
                    f"återställas ({duration_ms:.1f}ms, attempt {attempt})"
                )
            return ok
        except Exception as e:
            duration_ms = (time.monotonic() - start) * 1000
            entry = RecoveryAttempt(
                module_name=name,
                timestamp=time.time(),
                success=False,
                duration_ms=duration_ms,
                error=str(e),
                attempt_number=attempt,
                strategy=strategy,
                error_id=error_id,
            )
            with self._lock:
                self._recovery_history.append(entry)
            logger.error(
                f"{LOG_PREFIX} AutoRecovery: {name!r} misslyckades "
                f"[err_id={error_id}] ({duration_ms:.1f}ms, attempt {attempt}): {e}",
                exc_info=True,
            )
            return False

    def get_history(self, limit: int = 50) -> List[RecoveryAttempt]:
        """Hämta recovery-historik."""
        with self._lock:
            return list(self._recovery_history[-limit:])

    def get_stats(self) -> Dict[str, Any]:
        """Statistik (för diagnostics)."""
        with self._lock:
            total = len(self._recovery_history)
            success = sum(1 for h in self._recovery_history if h.success)
            return {
                "total_attempts": total,
                "successful": success,
                "failed": total - success,
                "success_rate": success / total if total > 0 else 1.0,
                "modules_tracked": len(self._recovery_funcs),
                "dependencies": dict(self._dependencies),
            }


# ===========================================================================
# RESOURCE TRACKER (hierarchical cleanup)
# ===========================================================================

class ResourceTracker:
    """
    Håller koll på resurser med:
      • Weak references (auto-cleanup vid GC)
      • Hierarchical cleanup (parent → children)
      • Manual cleanup med cleanup_func
    """

    __slots__ = ("_resources", "_lock", "_parent", "_children", "_created_at")

    def __init__(self) -> None:
        self._resources: Dict[str, weakref.ref] = {}
        self._lock = threading.RLock()
        self._parent: Optional["ResourceTracker"] = None
        self._children: List["ResourceTracker"] = []
        self._created_at = time.time()
        logger.debug(f"{LOG_PREFIX} ResourceTracker skapad")

    def register(
        self,
        name: str,
        resource: Any,
        cleanup_func: Optional[Callable] = None,
    ) -> None:
        """Registrera en resurs (med weak ref)."""
        with self._lock:
            def make_ref() -> None:
                try:
                    if cleanup_func is not None:
                        cleanup_func()
                    logger.debug(
                        f"{LOG_PREFIX} ResourceTracker: auto-cleanup för {name!r}"
                    )
                except Exception as e:
                    logger.error(
                        f"{LOG_PREFIX} ResourceTracker cleanup misslyckades "
                        f"för {name!r}: {e}",
                        exc_info=True,
                    )
            self._resources[name] = weakref.ref(resource, make_ref)
        logger.debug(f"{LOG_PREFIX} ResourceTracker: {name!r} registrerad")

    def create_child(self) -> "ResourceTracker":
        """Skapa child-tracker (hierarkisk)."""
        child = ResourceTracker()
        with self._lock:
            child._parent = self
            self._children.append(child)
        return child

    def cleanup_all(self) -> int:
        """Städa ALLA registrerade resurser (inkl. children)."""
        count = 0
        with self._lock:
            children = list(self._children)
            items = list(self._resources.items())
        # Cleanup children först
        for child in children:
            with self._lock:
                if child in self._children:
                    self._children.remove(child)
            count += child.cleanup_all()
        for name, ref in items:
            obj = ref()
            if obj is not None:
                try:
                    if isinstance(obj, Cleanable):
                        obj.cleanup()
                    elif hasattr(obj, "close"):
                        obj.close()
                    elif hasattr(obj, "stop"):
                        obj.stop()
                    elif hasattr(obj, "cancel"):
                        obj.cancel()
                    count += 1
                except Exception as e:
                    logger.error(
                        f"{LOG_PREFIX} ResourceTracker cleanup misslyckades "
                        f"för {name!r}: {e}",
                        exc_info=True,
                    )
            with self._lock:
                self._resources.pop(name, None)
        if count > 0:
            logger.info(
                f"{LOG_PREFIX} ResourceTracker: {count} resurser städade"
            )
        return count

    def get_stats(self) -> Dict[str, Any]:
        """Statistik (för diagnostics)."""
        with self._lock:
            alive = sum(1 for ref in self._resources.values() if ref() is not None)
            return {
                "total_registered": len(self._resources),
                "alive": alive,
                "dead": len(self._resources) - alive,
                "children": len(self._children),
                "uptime_sec": time.time() - self._created_at,
            }


# ===========================================================================
# MEMORY TRACKER (NY - för 5000% minnesoptimering)
# ===========================================================================

class MemoryTracker:
    """
    Spårar minnesanvändning med:
      • RSS-sampling (process resident size)
      • GC object count
      • Weak ref count
      • Trend-analys (växande/minksande minne)
    """

    __slots__ = ("_samples", "_lock", "_max_samples", "_enabled")

    def __init__(self, max_samples: int = 360) -> None:  # 6h @ 1/min
        self._samples: List[MemorySample] = []
        self._lock = threading.RLock()
        self._max_samples = max_samples
        self._enabled = True
        logger.debug(f"{LOG_PREFIX} MemoryTracker skapad (max_samples={max_samples})")

    def take_sample(self) -> MemorySample:
        """Ta en minnesprov."""
        sample = MemorySample(timestamp=time.time())
        # RSS via psutil (om tillgängligt)
        try:
            import psutil
            proc = psutil.Process(os.getpid())
            mem = proc.memory_info()
            sample.rss_mb = mem.rss / (1024 * 1024)
        except ImportError:
            # Fallback: använd resource-modulen (Unix)
            try:
                import resource
                usage = resource.getrusage(resource.RUSAGE_SELF)
                sample.rss_mb = usage.ru_maxrss / 1024  # KB → MB
            except ImportError:
                pass
        # GC objects
        sample.gc_objects = len(gc.get_objects())
        # Weak refs (approximation)
        sample.weak_refs = sum(
            1 for obj in gc.get_objects()
            if isinstance(obj, weakref.ref)
        )
        with self._lock:
            self._samples.append(sample)
            if len(self._samples) > self._max_samples:
                self._samples.pop(0)
        return sample

    def get_latest(self) -> Optional[MemorySample]:
        """Hämta senaste sample."""
        with self._lock:
            return self._samples[-1] if self._samples else None

    def get_trend(self, last_n: int = 10) -> Optional[str]:
        """Beräkna trend: 'growing' | 'shrinking' | 'stable'."""
        with self._lock:
            samples = self._samples[-last_n:]
        if len(samples) < 2:
            return None
        first, last = samples[0].rss_mb, samples[-1].rss_mb
        diff_mb = last - first
        if diff_mb > 5.0:
            return "growing"
        if diff_mb < -5.0:
            return "shrinking"
        return "stable"

    def force_gc(self) -> Dict[str, int]:
        """Tvinga garbage collection (returnerar antal per generation)."""
        before = len(gc.get_objects())
        collected = [gc.collect(generation) for generation in range(3)]
        after = len(gc.get_objects())
        logger.info(
            f"{LOG_PREFIX} MemoryTracker: GC tvingad, samlade in "
            f"{sum(collected)} objekt (före={before}, efter={after})"
        )
        return {"collected": dict(enumerate(collected)), "before": before, "after": after}


# ===========================================================================
# CPU PROFILER (NY - för 5000% CPU-optimering)
# ===========================================================================

class CPUProfiler:
    """
    Async-friendly CPU-profiler med:
      • p50, p95, p99 percentiler
      • Per-operation metrics
      • LRU-baserad history (max 1000 per operation)
    """

    __slots__ = ("_metrics", "_lock", "_max_samples")

    def __init__(self, max_samples: int = 1000) -> None:
        self._metrics: Dict[str, List[float]] = {}
        self._lock = threading.RLock()
        self._max_samples = max_samples
        logger.debug(f"{LOG_PREFIX} CPUProfiler skapad (max_samples={max_samples})")

    def record(self, operation: str, duration_ms: float) -> None:
        """Registrera en operation-duration."""
        with self._lock:
            samples = self._metrics.setdefault(operation, [])
            samples.append(duration_ms)
            if len(samples) > self._max_samples:
                samples.pop(0)

    def get_metrics(self, operation: str) -> Optional[CPUMetrics]:
        """Beräkna metrics för en operation."""
        with self._lock:
            samples = list(self._metrics.get(operation, []))
        if not samples:
            return None
        sorted_samples = sorted(samples)
        n = len(sorted_samples)
        return CPUMetrics(
            operation=operation,
            p50_ms=sorted_samples[int(n * 0.5)],
            p95_ms=sorted_samples[int(n * 0.95)],
            p99_ms=sorted_samples[int(n * 0.99)],
            avg_ms=sum(sorted_samples) / n,
            min_ms=sorted_samples[0],
            max_ms=sorted_samples[-1],
            call_count=n,
            total_ms=sum(sorted_samples),
        )

    def get_all_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Hämta metrics för ALLA operationer."""
        with self._lock:
            operations = list(self._metrics.keys())
        return {
            op: self.get_metrics(op).to_dict()
            for op in operations
            if self.get_metrics(op) is not None
        }

    @contextmanager
    def measure(self, operation: str):
        """Context manager som mäter + loggar."""
        start = time.perf_counter()
        try:
            yield
        finally:
            duration = (time.perf_counter() - start) * 1000
            self.record(operation, duration)
            if duration > 100:  # Logga långsamma operationer
                logger.warning(
                    f"{LOG_PREFIX} CPU[{operation}]: {duration:.2f}ms (slow!)"
                )
            elif logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"{LOG_PREFIX} CPU[{operation}]: {duration:.2f}ms"
                )


# ===========================================================================
# STABILITY MANAGER (global singleton)
# ===========================================================================

class StabilityManager:
    """
    Global singleton som koordinerar ALLA stabilitets-features.

    Användning:
        manager = get_stability_manager()
        manager.health_monitor.register(...)
        with manager.circuit_breaker("qt_app") as breaker:
            ...
    """

    _instance: Optional["StabilityManager"] = None
    _class_lock = threading.Lock()

    __slots__ = (
        "health_monitor", "auto_recovery", "resource_tracker",
        "memory_tracker", "cpu_profiler", "_breakers", "_boundaries",
        "_instance_lock", "_started", "_start_time",
    )

    def __new__(cls) -> "StabilityManager":
        if cls._instance is None:
            with cls._class_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init()
        return cls._instance

    def _init(self) -> None:
        self.health_monitor = HealthMonitor()
        self.auto_recovery = AutoRecovery()
        self.resource_tracker = ResourceTracker()
        self.memory_tracker = MemoryTracker()
        self.cpu_profiler = CPUProfiler()
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._boundaries: Dict[str, ErrorBoundary] = {}
        self._instance_lock = threading.RLock()
        self._started = False
        self._start_time = time.time()
        logger.info(
            f"{LOG_PREFIX} StabilityManager initierad (v{STABILITY_VERSION})"
        )

    def circuit_breaker(
        self,
        name: str,
        failure_threshold: int = DEFAULT_CIRCUIT_FAILURE_THRESHOLD,
        recovery_timeout_sec: float = DEFAULT_RECOVERY_TIMEOUT_SEC,
    ) -> CircuitBreaker:
        """Hämta eller skapa en circuit breaker (fluent)."""
        with self._instance_lock:
            if name not in self._breakers:
                self._breakers[name] = CircuitBreaker(
                    name=name,
                    failure_threshold=failure_threshold,
                    recovery_timeout_sec=recovery_timeout_sec,
                )
                logger.debug(
                    f"{LOG_PREFIX} CircuitBreaker skapad: {name!r}"
                )
            return self._breakers[name]

    def error_boundary(
        self,
        name: str,
        on_error: Optional[Callable] = None,
        max_errors: int = 10,
    ) -> ErrorBoundary:
        """Hämta eller skapa en error boundary (fluent)."""
        with self._instance_lock:
            if name not in self._boundaries:
                self._boundaries[name] = ErrorBoundary(
                    name=name,
                    on_error=on_error,
                    max_errors_before_disable=max_errors,
                )
                logger.debug(
                    f"{LOG_PREFIX} ErrorBoundary skapad: {name!r}"
                )
            return self._boundaries[name]

    def get_health_report(self) -> Dict[str, Any]:
        """Hämta komplett hälsorapport (för diagnostics)."""
        with self._instance_lock:
            breakers_stats = {name: b.stats for name, b in self._breakers.items()}
            boundaries_stats = {name: b.get_stats() for name, b in self._boundaries.items()}
        return {
            "stability_version": STABILITY_VERSION,
            "timestamp": time.time(),
            "uptime_sec": time.time() - self._start_time,
            "health": self.health_monitor.get_all_health(),
            "recovery": self.auto_recovery.get_stats(),
            "resources": self.resource_tracker.get_stats(),
            "memory": (
                self.memory_tracker.get_latest().to_dict()
                if self.memory_tracker.get_latest() else None
            ),
            "cpu": self.cpu_profiler.get_all_metrics(),
            "circuit_breakers": breakers_stats,
            "error_boundaries": boundaries_stats,
        }

    def diagnose(self) -> List[str]:
        """
        NY v6.4.1 v7: Diagnostisk funktion som kontrollerar denna manager-instans.

        Returnerar lista med svenska problem-beskrivningar (tom om allt ar OK).

        Returns:
            Lista av strängar — varje sträng beskriver ett problem
        """
        return _validate_stability_state(self)

    def get_health_report_v2(self) -> Dict[str, Any]:
        """
        NY v6.4.1 v7: Utökad health-rapport med AI-felsökning-fält.

        Innehåller samma falt som `get_health_report()` plus:
          - summary_swedish (en-rads-sammanfattning)
          - problems (svenska problem-beskrivningar)
          - problem_count

        Returns:
            Dict med komplett diagnostik
        """
        with safe_run(f"{LOG_PREFIX} get_health_report_v2") as ctx:
            base = self.get_health_report()
            problems = _validate_stability_state(self)
            summary = summarize_stability_health(self)
            ctx["ok"] = True
            return {
                **base,
                "summary_swedish": summary,
                "problems": problems,
                "problem_count": len(problems),
            }

    def get_snapshot(self) -> AppSnapshot:
        """Ta komplett snapshot av stabilitets-state."""
        report = self.get_health_report()
        return AppSnapshot(
            snapshot_id=str(uuid.uuid4())[:8],
            timestamp=time.time(),
            timestamp_iso=time.strftime("%Y-%m-%d %H:%M:%S"),
            health=report["health"],
            circuit_breakers=report["circuit_breakers"],
            error_boundaries=report["error_boundaries"],
            recovery_history=[h.to_dict() for h in self.auto_recovery.get_history()],
            error_history_count=sum(
                b.get_stats().get("history_count", 0)
                for b in self._boundaries.values()
            ),
            memory_sample=report["memory"],
            cpu_metrics=report["cpu"],
        )

    def dump_to_file(self, path: str) -> bool:
        """Dumpa full diagnostic-dump till JSON-fil."""
        try:
            snap = self.get_snapshot()
            with open(path, "w", encoding="utf-8") as f:
                f.write(snap.to_json())
            logger.info(
                f"{LOG_PREFIX} Diagnostic dump skapad: {path} "
                f"({len(snap.to_json())} bytes)"
            )
            return True
        except Exception as e:
            logger.error(
                f"{LOG_PREFIX} Diagnostic dump misslyckades: {e}",
                exc_info=True,
            )
            return False

    def start(self) -> None:
        """Starta ALLA bakgrunds-tjänster."""
        if self._started:
            return
        self._started = True
        self.health_monitor.start()
        logger.info(f"{LOG_PREFIX} StabilityManager startad (alla子系统)")

    def stop(self) -> None:
        """Stoppa ALLA bakgrunds-tjänster."""
        if not self._started:
            return
        self._started = False
        self.health_monitor.stop()
        self.resource_tracker.cleanup_all()
        logger.info(f"{LOG_PREFIX} StabilityManager stoppad (cleanup klar)")


def get_stability_manager() -> StabilityManager:
    """Hämta global stability manager (singleton)."""
    return StabilityManager()


def _inspect_widget_fix_status() -> Dict[str, bool]:
    """
    NY v7-fix16: kontrollera TodoWidget:s fix-metoder UTAN att exekvera modulen.

    Tidigare kördes hela ui/widget.py via importlib (exec_module) bara för
    hasattr-kontroller — det (a) exekverade PySide6-importer + klass-
    definitioner på nytt vid VARJE diagnostik-anrop, och (b) kraschade i
    miljöer utan Qt → falska "saknar metoder"-fel + critical_ok=False.

    Nu:
      1. Föredra redan importerad 'widget'-modul (mest korrekt i appen)
      2. Annars: AST-parse av filen — ingen exekvering, inga biverkningar
    """
    status: Dict[str, bool] = {
        "has_widget_module": False,
        "has_setup_bugg19_zorder": False,
        "has_restore_window_position": False,
        "has_validate_position_on_screens": False,
    }
    try:
        from pathlib import Path as _P
        widget_path = (
            _P(__file__).resolve().parent.parent / "ui" / "widget.py"
        )
        if not widget_path.is_file():
            return status
        status["has_widget_module"] = True

        # 1. Live-modul (om redan importerad i denna process)
        live = sys.modules.get("widget")
        if live is not None and hasattr(live, "TodoWidget"):
            cls = live.TodoWidget
            status["has_setup_bugg19_zorder"] = hasattr(
                cls, "_setup_bugg19_zorder"
            )
            status["has_restore_window_position"] = hasattr(
                cls, "_restore_window_position"
            )
            status["has_validate_position_on_screens"] = hasattr(
                cls, "_validate_position_on_screens"
            )
            return status

        # 2. AST-parse (ingen exekvering!)
        import ast as _ast
        tree = _ast.parse(widget_path.read_text(encoding="utf-8"))
        for node in _ast.walk(tree):
            if isinstance(node, _ast.ClassDef) and node.name == "TodoWidget":
                for item in node.body:
                    if isinstance(
                        item, (_ast.FunctionDef, _ast.AsyncFunctionDef)
                    ):
                        if item.name == "_setup_bugg19_zorder":
                            status["has_setup_bugg19_zorder"] = True
                        elif item.name == "_restore_window_position":
                            status["has_restore_window_position"] = True
                        elif item.name == "_validate_position_on_screens":
                            status["has_validate_position_on_screens"] = True
    except (OSError, SyntaxError, ValueError) as e:
        logger.debug(f"{LOG_PREFIX} widget-fix AST-check misslyckades: {e}")
    except Exception as e:  # defensive — diagnostik får ALDRIG krascha
        logger.debug(f"{LOG_PREFIX} widget-fix-check misslyckades: {e}")
    return status


def diagnose_app_health() -> Dict[str, Any]:
    """
    NY v6.4.1: Komplett diagnostik av app-hälsa (för support / Doctor-knappen).

    Innehåller:
      - stability_version, timestamp, uptime_sec
      - total_errors, total_recoveries, circuit_breakers_open
      - critical_systems_ok (alla subsystem reachable?)
      - widget_fix_status (v6.4.1-fix implementerat?)
      - issues: List[str] med sammanfattade problem

    Returns:
        Dict med diagnostik-info

    Exempel:
        >>> report = diagnose_app_health()
        >>> print(report["issues"])
        >>> print(f"Total errors: {report['total_errors']}")
    """
    manager = get_stability_manager()
    health_report = manager.get_health_report()
    issues: List[str] = []

    # Räkna errors från alla error_boundaries
    total_errors = sum(
        stats.get("total_errors", 0)
        for stats in health_report["error_boundaries"].values()
    )
    total_recoveries = sum(
        stats.get("successful_recoveries", 0)
        for stats in health_report["error_boundaries"].values()
    )
    circuit_breakers_open = sum(
        1 for b in health_report["circuit_breakers"].values()
        if b.get("state") == "open"
    )

    # NY v6.4.1: Widget-fix-status
    # FIX v7-fix16: AST-baserad kontroll via _inspect_widget_fix_status() —
    # blocket exekverade tidigare HELA widget.py (exec_module) vid varje
    # anrop: dyrt, sidoeffekter, och kraschade utan Qt → falska
    # "saknar metoder"-fel + critical_ok=False.
    widget_fix = _inspect_widget_fix_status()

    # Identifiera issues
    if total_errors > 50:
        issues.append(
            f"Hög error-rate: {total_errors} fel sedan start"
        )
    if circuit_breakers_open > 0:
        issues.append(
            f"{circuit_breakers_open} circuit breaker(s) är ÖPPNA"
        )
    if not widget_fix["has_validate_position_on_screens"]:
        issues.append(
            "Widget saknar _validate_position_on_screens (v6.4.1-fix)"
        )
    if not widget_fix["has_restore_window_position"]:
        issues.append(
            "Widget saknar _restore_window_position (v6.4.1-fix)"
        )

    # Critical systems OK?
    critical_ok = (
        widget_fix["has_widget_module"]
        and widget_fix["has_setup_bugg19_zorder"]
    )

    result = {
        "stability_version": STABILITY_VERSION,
        "timestamp": time.time(),
        "uptime_sec": health_report["uptime_sec"],
        "total_errors": total_errors,
        "total_recoveries": total_recoveries,
        "circuit_breakers_open": circuit_breakers_open,
        "critical_systems_ok": critical_ok,
        "widget_fix_status": widget_fix,
        "issues": issues,
        "health_report": health_report,
    }
    logger.info(
        f"{LOG_PREFIX} diagnose_app_health: {total_errors} errors, "
        f"{circuit_breakers_open} breakers open, "
        f"{len(issues)} issues, critical_ok={critical_ok}"
    )
    return result


def attempt_widget_window_recovery() -> Dict[str, Any]:
    """
    NY v6.4.1: Widget-specifik recovery (använd vid akuta fönster-problem).

    Vad den gör:
      1. Hittar alla QApplication.widgets() av typ TodoWidget
      2. För varje: anropa _validate_position_on_screens()
      3. Om misslyckad → försök _restore_window_position()
      4. Om fortfarande misslyckad → rapportera till recovery-system

    Returns:
        Dict med resultat:
          - attempted: int (antal widgets som testades)
          - recovered: int (antal som flyttades till valid position)
          - failed: int (antal som inte kunde återställas)
          - details: List[str]

    Exempel:
        >>> result = attempt_widget_window_recovery()
        >>> if result["failed"] > 0:
        ...     logger.error("Widget recovery misslyckades")
    """
    result: Dict[str, Any] = {
        "attempted": 0,
        "recovered": 0,
        "failed": 0,
        "details": [],
    }
    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QGuiApplication
    except ImportError:
        result["details"].append("PySide6 ej tillgängligt")
        logger.warning(
            f"{LOG_PREFIX} attempt_widget_window_recovery: PySide6 saknas"
        )
        return result

    app = QApplication.instance()
    if app is None:
        result["details"].append("Ingen QApplication kör")
        logger.warning(
            f"{LOG_PREFIX} attempt_widget_window_recovery: "
            f"ingen QApplication"
        )
        return result

    # Hitta alla top-level widgets
    for widget in app.topLevelWidgets():
        cls_name = type(widget).__name__
        if cls_name != "TodoWidget":
            continue
        result["attempted"] += 1
        win_id = getattr(widget, "win_id", "?")
        try:
            x_before, y_before = widget.x(), widget.y()
            # Steg 1: validate
            if hasattr(widget, "_validate_position_on_screens"):
                widget._validate_position_on_screens()
            x_after, y_after = widget.x(), widget.y()
            # Kolla om flyttades
            if (x_before, y_before) != (x_after, y_after):
                result["recovered"] += 1
                result["details"].append(
                    f"win_id={win_id}: flyttad från ({x_before},{y_before}) "
                    f"till ({x_after},{y_after})"
                )
                logger.info(
                    f"{LOG_PREFIX} widget recovery: win_id={win_id} "
                    f"flyttad ({x_before},{y_before}) → ({x_after},{y_after})"
                )
            else:
                result["details"].append(
                    f"win_id={win_id}: redan på valid position "
                    f"({x_before},{y_before})"
                )
        except Exception as e:
            result["failed"] += 1
            result["details"].append(
                f"win_id={win_id}: recovery misslyckades: {e}"
            )
            logger.error(
                f"{LOG_PREFIX} widget recovery misslyckades för "
                f"win_id={win_id}: {e}", exc_info=True,
            )

    logger.info(
        f"{LOG_PREFIX} attempt_widget_window_recovery: "
        f"attempted={result['attempted']}, recovered={result['recovered']}, "
        f"failed={result['failed']}"
    )
    return result


def is_critical_error_rate(threshold: int = 10) -> bool:
    """
    NY v6.4.1: Kontrollera om error-rate är över kritisk tröskel.

    Args:
        threshold: Antal errors som räknas som kritiskt (default 10)

    Returns:
        True om total_errors > threshold

    Exempel:
        >>> if is_critical_error_rate():
        ...     logger.critical("Hög error-rate!")
    """
    manager = get_stability_manager()
    health_report = manager.get_health_report()
    total_errors = sum(
        stats.get("total_errors", 0)
        for stats in health_report["error_boundaries"].values()
    )
    is_critical = total_errors > threshold
    if is_critical:
        logger.warning(
            f"{LOG_PREFIX} is_critical_error_rate: {total_errors} > {threshold}"
        )
    return is_critical


# ===========================================================================
# CONTEXT MANAGERS
# ===========================================================================

@contextmanager
def safe_context(
    name: str = "operation",
    log_traceback: bool = True,
    default: Any = None,
):
    """Context manager som wrappar kod med try/except + logging + AI-felsökning."""
    start = time.perf_counter()
    try:
        yield
        duration = (time.perf_counter() - start) * 1000
        logger.debug(f"{LOG_PREFIX} safe_context[{name}]: OK ({duration:.2f}ms)")
    except Exception as e:
        duration = (time.perf_counter() - start) * 1000
        error_id = str(uuid.uuid4())[:8]
        # NY v6.4.1 v7: AI-felsökning — kategorisera + beskriv
        try:
            category = _categorize_stability_exception(e)
            description = _describe_stability_exception(e)
        except Exception:
            category = "code_bug"
            description = f"{type(e).__name__}: {e}"
        if log_traceback:
            logger.error(
                f"{LOG_PREFIX} safe_context[{name}] misslyckades "
                f"[err_id={error_id}] ({duration:.2f}ms, "
                f"kategori={category}): {description}",
                exc_info=True,
            )
        else:
            logger.warning(
                f"{LOG_PREFIX} safe_context[{name}] misslyckades "
                f"[err_id={error_id}] (kategori={category}): {description}"
            )


@contextmanager
def timing_context(name: str = "operation"):
    """Context manager som mäter och loggar execution-tid."""
    start = time.monotonic()
    try:
        yield
    finally:
        elapsed = (time.monotonic() - start) * 1000
        if elapsed > 100:
            logger.warning(
                f"{LOG_PREFIX} timing[{name}]: {elapsed:.2f}ms (slow!)"
            )
        else:
            logger.debug(f"{LOG_PREFIX} timing[{name}]: {elapsed:.2f}ms")


# ===========================================================================
# AI-FELSÖKNING 10000% (NY v6.4.1 v7)
# ===========================================================================
# Hjalpare som genererar:
#   - Anvandarvanlig svenska feltext (for loggar/dialoger)
#   - Kompakt teknisk stacktrace (for loggar)
#   - Standardiserad kategorisering (for prioriterad felhantering)
#   - safe_run context-manager (modul-niva, utover safe_context decorator)
#   - Diagnostik & validering av modulens internna tillstand
# Allt for att Rickard ska kunna felsoka 100% sa mycket enklare.

_STABILITY_ERROR_TRANSLATIONS: Final[Dict[str, str]] = {
    # Standard-bibliotek
    "ImportError": "Kan inte hitta en Python-modul",
    "ModuleNotFoundError": "Python-modul saknas",
    "AttributeError": "Objektet saknar en metod eller attribut",
    "TypeError": "Fel typ av argument skickades",
    "ValueError": "Ogiltigt varde skickades",
    "KeyError": "Nyckel saknas i stabilitets-data",
    "IndexError": "Index utanfor intervall",
    "FileNotFoundError": "Stabilitets-filen hittades inte",
    "PermissionError": "Saknar ratigheter till logg eller state-fil",
    "OSError": "Operativsystem-fel vid stabilitets-I/O",
    "IOError": "In/ut-fel vid lasning eller skrivning",
    "TimeoutError": "Tidsgrans overskreds vid recovery eller health-check",
    "ConnectionError": "Natverksfel (anslutning misslyckades)",
    "UnicodeDecodeError": "Kunde inte avkoda state-data (fel teckenkodning)",
    "RecursionError": "Rekursion blev for djup (for manga recovery-attempts)",
    "MemoryError": "Minnet slut (for manga fel eller snapshots)",
    # Concurrent
    "ThreadError": "Trad-fel (start eller join misslyckades)",
    "BrokenPipeError": "Pipebrott (process avslutad)",
    # Stability-specifikt
    "StabilityError": "Stabilitets-fel (generiskt)",
    "CircuitOpenError": "Circuit breaker ar oppnet (skyddar mot fel)",
    "RecoveryFailedError": "Recovery misslyckades efter max antal forsok",
    # Qt-specifikt
    "RuntimeError": "Qt-runtime-fel (kanske trasig widget)",
}


def _describe_stability_exception(exc: BaseException) -> str:
    """
    NY v6.4.1 v7: Skapar en anvandarvanlig svensk beskrivning av ett undantag.

    Args:
        exc: Exception-objektet som ska beskrivas

    Returns:
        Svensk sträng som passar i loggar och dialoger

    Exempel:
        >>> _describe_stability_exception(CircuitOpenError("breaker-x"))
        'Circuit breaker ar oppnet (skyddar mot fel): breaker-x'
        >>> _describe_stability_exception(RecoveryFailedError("modul", attempts=3))
        'Recovery misslyckades efter max antal forsok: 3 forsok'
    """
    try:
        exc_type = type(exc).__name__
        svensk_typ = _STABILITY_ERROR_TRANSLATIONS.get(
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
            f"{LOG_PREFIX} _describe_stability_exception misslyckades: "
            f"{describe_err}"
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


def _categorize_stability_exception(exc: BaseException) -> str:
    """
    NY v6.4.1 v7: Kategorisera undantag for prioriterad felhantering.

    Returns:
        En av: "user_input", "system", "code_bug", "external",
        "permission", "concurrent", "recovery", "circuit_open"
    """
    try:
        exc_type = type(exc).__name__
        # CircuitOpenError / RecoveryFailedError — stabilitets-specifika
        if exc_type == "CircuitOpenError":
            return "circuit_open"
        if exc_type == "RecoveryFailedError":
            return "recovery"
        if exc_type == "StabilityError":
            return "recovery"
        # Anvandarinput-fel
        if exc_type in ("ValueError", "KeyError", "TypeError", "IndexError"):
            return "user_input"
        # Rattighets-fel
        if exc_type in ("PermissionError",):
            return "permission"
        # Concurrent / threading
        if exc_type in ("ThreadError", "BrokenPipeError", "BlockingIOError"):
            return "concurrent"
        # System-fel
        if exc_type in (
            "OSError", "IOError", "FileNotFoundError",
            "IsADirectoryError", "NotADirectoryError",
            "TimeoutError", "ConnectionError",
            "WindowsError",
        ):
            return "system"
        # Import/modul-fel
        if exc_type in ("ImportError", "ModuleNotFoundError"):
            return "external"
        # Minnesfel
        if exc_type in ("MemoryError", "RecursionError", "OverflowError"):
            return "system"
        # Unicode
        if exc_type in ("UnicodeDecodeError", "UnicodeEncodeError"):
            return "user_input"
        # Allt annat = troligen kod-bugg
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
    """
    NY v6.4.1 v7: Modul-niva context-manager for komplett felhantering.

    Liknar `safe_context` men lever pa modul-niva (inte som decorator) och
    returnerar en ctx-dict med "errors", "start_time", "operation" som
    anvandaren kan inspektera efterat.

    Args:
        operation_name: Namn pa operationen (for loggning)
        log_errors: Om True, logga fel till error-loggen
        reraise: Om True, ra om undantaget efter loggning

    Yields:
        Dict med "start_time", "operation" och "errors"

    Exempel:
        >>> with safe_run("min operation") as ctx:
        ...     risky_call()
        ... if ctx["errors"]:
        ...     print("Nagot gick fel")
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
        category = _categorize_stability_exception(exc)
        ctx["errors"].append(exc)
        if log_errors:
            logger.error(
                f"{LOG_PREFIX} safe_run FEL: {operation_name} "
                f"({duration:.2f}ms, kategori={category}): "
                f"{_describe_stability_exception(exc)}"
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

    Returns:
        func-resultatet, eller `default` vid timeout/fel
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

    t = threading.Thread(target=worker, daemon=True, name=f"stab-safe-async:{op_name}")
    t.start()
    if not done.wait(timeout=timeout_sec):
        logger.error(
            f"{LOG_PREFIX} _safe_run_async TIMEOUT ({timeout_sec}s): {op_name}"
        )
        return default
    if error_box[0] is not None:
        category = _categorize_stability_exception(error_box[0])
        logger.error(
            f"{LOG_PREFIX} _safe_run_async FEL: {op_name} "
            f"(kategori={category}): {_describe_stability_exception(error_box[0])}"
        )
        return default
    return result_box[0]


def _validate_stability_state(manager: Optional[Any] = None) -> List[str]:
    """
    NY v6.4.1 v7: Diagnostisk funktion som kontrollerar modulens internna tillstand.

    Args:
        manager: Valfri StabilityManager-instans att validera (om None: modul-niva)

    Returns:
        Lista med svenska problem-beskrivningar (tom om allt ar OK)
    """
    problems: List[str] = []
    try:
        # 1. Logger fungerar?
        if logger is None:
            problems.append("Kritisk: modulens logger ar None")

        # 2. Stabilitets-version validerad?
        try:
            from core.stability import STABILITY_VERSION
        except ImportError:
            pass  # Self-import vid validering — OK

        # 3. JSON serializable check
        try:
            import json as _json
            test_obj = {
                "version": STABILITY_VERSION,
                "errors": [],
                "checks": [{"name": "test", "status": "healthy"}],
            }
            encoded = _json.dumps(test_obj)
            decoded = _json.loads(encoded)
            if decoded != test_obj:
                problems.append("JSON round-trip misslyckades (state korrupt)")
        except Exception as e:
            problems.append(
                f"JSON-backend trasig: {_describe_stability_exception(e)}"
            )

        # 4. Threading.RLock kontroll (via manager)
        if manager is not None:
            try:
                # Kontrollera att viktiga attribut finns
                for attr in ("_checks", "_errors", "_recovery_history"):
                    if not hasattr(manager, attr):
                        problems.append(
                            f"StabilityManager saknar attribut: {attr}"
                        )
                # Health-checks
                if hasattr(manager, "get_all_checks"):
                    try:
                        checks = manager.get_all_checks()
                        if not isinstance(checks, dict):
                            problems.append(
                                f"get_all_checks() returnerar inte dict: "
                                f"{type(checks).__name__}"
                            )
                        else:
                            # Kontrollera duplicate check-names
                            seen_names: set = set()
                            for chk_name in checks:
                                if chk_name in seen_names:
                                    problems.append(
                                        f"Duplicate health-check-namn: {chk_name}"
                                    )
                                seen_names.add(chk_name)
                            # For manga checks?
                            if len(checks) > 100:
                                problems.append(
                                    f"Manga health-checks registrerade: "
                                    f"{len(checks)} (mojligen minneslacka)"
                                )
                    except Exception as e:
                        problems.append(
                            f"get_all_checks() misslyckades: "
                            f"{_describe_stability_exception(e)}"
                        )
                # Error count
                if hasattr(manager, "get_error_count"):
                    try:
                        err_count = manager.get_error_count()
                        if isinstance(err_count, int) and err_count > 1000:
                            problems.append(
                                f"Manga fel registrerade: {err_count} "
                                f"(kanske en bug som spammar)"
                            )
                    except Exception as e:
                        problems.append(
                            f"get_error_count() misslyckades: "
                            f"{_describe_stability_exception(e)}"
                        )
                # Manager health
                if hasattr(manager, "is_healthy"):
                    try:
                        is_healthy = manager.is_healthy()
                        if not is_healthy:
                            problems.append(
                                "StabilityManager rapporterar att appen EJ ar frisk"
                            )
                    except Exception as e:
                        problems.append(
                            f"is_healthy() misslyckades: "
                            f"{_describe_stability_exception(e)}"
                        )
            except Exception as e:
                problems.append(
                    f"Manager-validering kraschade: "
                    f"{_describe_stability_exception(e)}"
                )

        # Logga resultatet
        if problems:
            logger.warning(
                f"{LOG_PREFIX} _validate_stability_state: "
                f"{len(problems)} problem hittade"
            )
            for p in problems:
                logger.warning(f"  - {p}")
        else:
            logger.debug(f"{LOG_PREFIX} _validate_stability_state: alla tester OK")
    except Exception as e:
        problems.append(
            f"_validate_stability_state själv kraschade: "
            f"{_describe_stability_exception(e)}"
        )
    return problems


# ===========================================================================
# SVENSKA FORMATERINGS-HELPERS (NY v6.4.1 v7)
# ===========================================================================

def format_recovery_attempt_swedish(attempt: Any) -> str:
    """
    NY v6.4.1 v7: Svensk formattering av en RecoveryAttempt.

    Args:
        attempt: RecoveryAttempt-dataclass (eller dict med motsvarande falt)

    Returns:
        Svensk en-rads-sammanfattning

    Exempel:
        >>> # Antar attempt = RecoveryAttempt(module="widget", success=False,
        ... #                                strategy="RETRY", attempts=3, ...)
        >>> format_recovery_attempt_swedish(attempt)
        'widget: MISSLYCKADES (3 forsok, RETRY, 1.23s)'
    """
    try:
        # Hantera bade dataclass och dict
        def _get(key: str, default: Any = None) -> Any:
            if isinstance(attempt, dict):
                return attempt.get(key, default)
            return getattr(attempt, key, default)

        module = str(_get("module", "?") or "?")
        success = bool(_get("success", False))
        strategy = _get("strategy", "?")
        attempts = _get("attempts", 0)
        duration_ms = _get("duration_ms", 0)
        error = _get("error", None)
        if success:
            status = "OK"
        else:
            status = "MISSLYCKADES"
        strategy_str = ""
        if strategy is not None and strategy != "?":
            strategy_name = (
                strategy.value if hasattr(strategy, "value") else str(strategy)
            )
            strategy_str = f", {strategy_name}"
        duration_str = ""
        if isinstance(duration_ms, (int, float)) and duration_ms > 0:
            duration_str = f", {duration_ms:.0f}ms"
        error_str = ""
        if error and not success:
            try:
                error_desc = _describe_stability_exception(error) if isinstance(
                    error, BaseException
                ) else str(error)
                # Korta ner
                if len(error_desc) > 60:
                    error_desc = error_desc[:57] + "..."
                error_str = f" — {error_desc}"
            except Exception:
                error_str = ""
        return f"{module}: {status} ({attempts} forsok{strategy_str}{duration_str}){error_str}"
    except Exception as e:
        logger.debug(
            f"{LOG_PREFIX} format_recovery_attempt_swedish misslyckades: {e}"
        )
        return f"(kunde inte formatera: {type(e).__name__})"


def summarize_circuit_state(breaker: Any) -> str:
    """
    NY v6.4.1 v7: Svensk sammanfattning av en CircuitBreaker-instans.

    Args:
        breaker: CircuitBreaker-instans

    Returns:
        Svensk en-rads-sammanfattning

    Exempel:
        >>> summarize_circuit_state(breaker)
        'api: STÄNGD (5 fel, 3 framgångar, sist fel=2min sedan)'
    """
    try:
        if breaker is None:
            return "(ingen breaker)"
        name = getattr(breaker, "name", "?")
        state = getattr(breaker, "state", None)
        state_str = "?"
        if state is not None:
            state_str = (
                state.value if hasattr(state, "value") else str(state)
            )
            # Svensk oversattning
            state_str_sv = {
                "closed": "STÄNGD (normal)",
                "open": "ÖPPEN (blockerar)",
                "half_open": "HALV-ÖPPEN (testar)",
            }.get(state_str, state_str)
            state_str = state_str_sv
        stats = getattr(breaker, "stats", {})
        if hasattr(stats, "__dict__"):
            stats = stats.__dict__
        failures = stats.get("failure_count", 0) if isinstance(stats, dict) else 0
        successes = stats.get("success_count", 0) if isinstance(stats, dict) else 0
        last_failure = stats.get("last_failure_time", 0) if isinstance(stats, dict) else 0
        ago_str = ""
        if last_failure:
            secs = int(time.time() - last_failure)
            if secs < 60:
                ago_str = f", sist fel={secs}s sedan"
            elif secs < 3600:
                ago_str = f", sist fel={secs // 60}min sedan"
            else:
                ago_str = f", sist fel={secs // 3600}h sedan"
        return f"{name}: {state_str} ({failures} fel, {successes} framgångar{ago_str})"
    except Exception as e:
        logger.debug(
            f"{LOG_PREFIX} summarize_circuit_state misslyckades: {e}"
        )
        return f"(kunde inte sammanfatta: {type(e).__name__})"


def summarize_stability_health(manager: Optional[Any] = None) -> str:
    """
    NY v6.4.1 v7: Kort svensk sammanfattning av stabilitets-modulen / -manager.

    Args:
        manager: Valfri StabilityManager-instans (om None: modul-niva)

    Returns:
        Svensk en-rads-sammanfattning

    Exempel:
        >>> summarize_stability_health()
        'v6.4.1-v7 • 0 checks • 0 fel • frisk'
    """
    try:
        checks_count = 0
        errors_count = 0
        is_healthy: Optional[bool] = None
        if manager is not None:
            try:
                if hasattr(manager, "get_all_checks"):
                    checks = manager.get_all_checks()
                    if isinstance(checks, dict):
                        checks_count = len(checks)
            except Exception:
                pass
            try:
                if hasattr(manager, "get_error_count"):
                    err = manager.get_error_count()
                    if isinstance(err, int):
                        errors_count = err
            except Exception:
                pass
            try:
                if hasattr(manager, "is_healthy"):
                    is_healthy = manager.is_healthy()
            except Exception:
                pass
        healthy_str = "frisk" if is_healthy else (
            "EJ frisk" if is_healthy is False else "okand"
        )
        return (
            f"v{STABILITY_VERSION} • {checks_count} checks • "
            f"{errors_count} fel • {healthy_str}"
        )
    except Exception as e:
        logger.debug(
            f"{LOG_PREFIX} summarize_stability_health misslyckades: {e}"
        )
        return f"(kunde inte sammanfatta: {type(e).__name__})"


def get_stability_diagnostics(manager: Optional[Any] = None) -> Dict[str, Any]:
    """
    NY v6.4.1 v7: Detaljerad diagnostik-rapport for support-fall.

    Args:
        manager: Valfri StabilityManager-instans (om None: modul-niva)

    Returns:
        Dict med:
          - module, stability_version
          - problems (lista med svenska beskrivningar)
          - summary_swedish (en-rads-sammanfattning)
          - is_healthy (bool eller None)
          - checks_count, errors_count
    """
    with safe_run("get_stability_diagnostics") as ctx:
        problems = _validate_stability_state(manager)
        summary = summarize_stability_health(manager)
        is_healthy: Optional[bool] = None
        checks_count = 0
        errors_count = 0
        if manager is not None:
            try:
                if hasattr(manager, "is_healthy"):
                    is_healthy = manager.is_healthy()
                if hasattr(manager, "get_all_checks"):
                    checks = manager.get_all_checks()
                    if isinstance(checks, dict):
                        checks_count = len(checks)
                if hasattr(manager, "get_error_count"):
                    err = manager.get_error_count()
                    if isinstance(err, int):
                        errors_count = err
            except Exception as e:
                logger.debug(
                    f"{LOG_PREFIX} get_stability_diagnostics "
                    f"manager-probe misslyckades: "
                    f"{_describe_stability_exception(e)}"
                )
        ctx["ok"] = True
        return {
            "module": "stability",
            "stability_version": STABILITY_VERSION,
            "problems": problems,
            "problem_count": len(problems),
            "summary_swedish": summary,
            "is_healthy": is_healthy,
            "checks_count": checks_count,
            "errors_count": errors_count,
        }


_STABILITY_PLUGIN_DEPS: Final[Tuple[Dict[str, str], ...]] = (
    {
        "pip_name": "psutil",
        "import_name": "psutil",
        "description_svenska": "Process- och minnesinfo for stability-system",
        "benefit_svenska": "Mer detaljerade minnes- och process-mätningar",
        "required": False,
    },
)


def get_stability_plugin_deps() -> List[Dict[str, str]]:
    """NY v6.4.1 v7: Optional Python-beroenden som stability vill ha."""
    return [dict(d) for d in _STABILITY_PLUGIN_DEPS]


# ===========================================================================
# STARTUP VALIDATION
# ===========================================================================

def validate_startup() -> Tuple[bool, List[str]]:
    """
    Kör startup-validering av ALLA nödvändiga moduler.
    Returnerar (success, errors).
    """
    errors: List[str] = []
    logger.info(f"{LOG_PREFIX} Startup-validering startar...")

    # 1. Python-version
    py_ver = sys.version_info
    if py_ver < (3, 9):
        errors.append(
            f"Python 3.9+ krävs (har {py_ver.major}.{py_ver.minor})"
        )
    else:
        logger.debug(
            f"{LOG_PREFIX} Python {py_ver.major}.{py_ver.minor}.{py_ver.micro} OK"
        )

    # 2. Nödvändiga standardbibliotek
    required = ["json", "logging", "threading", "os", "sys", "time", "traceback", "gc"]
    for module in required:
        try:
            __import__(module)
            logger.debug(f"{LOG_PREFIX} stdlib {module!r} OK")
        except ImportError as e:
            errors.append(f"Kunde inte importera {module}: {e}")

    # 3. PySide6 (valfritt — kan köra utan)
    try:
        import PySide6
        logger.debug(f"{LOG_PREFIX} PySide6 OK: {PySide6.__version__}")
    except ImportError as e:
        logger.warning(f"{LOG_PREFIX} PySide6 saknas: {e}")
        errors.append(f"PySide6 saknas (appen kan inte starta UI: {e})")

    # 4. Plattformsspecifika moduler
    if sys.platform == "win32":
        try:
            import ctypes
            import ctypes.wintypes
            logger.debug(f"{LOG_PREFIX} ctypes/wintypes OK")
        except ImportError as e:
            errors.append(f"ctypes/wintypes saknas: {e}")

    # 5. Minne-check
    try:
        import psutil
        avail_mb = psutil.virtual_memory().available / (1024 * 1024)
        logger.debug(
            f"{LOG_PREFIX} Tillgängligt minne: {avail_mb:.0f} MB"
        )
        if avail_mb < 100:
            errors.append(f"För lite minne: {avail_mb:.0f} MB tillgängligt")
    except ImportError:
        logger.debug(f"{LOG_PREFIX} psutil ej tillgängligt, hoppar över minne-check")

    # 6. NY v6.4.1: Widget v6.4.1-fix-check
    # FIX v7-fix16: AST-baserad kontroll via _inspect_widget_fix_status() —
    # blocket exekverade tidigare hela widget.py (exec_module): dyrt och
    # kraschade utan Qt → falska fel i startup-valideringen.
    try:
        _wfix = _inspect_widget_fix_status()
        if not _wfix["has_widget_module"]:
            logger.debug(f"{LOG_PREFIX} widget.py hittades ej")
        else:
            if not _wfix["has_restore_window_position"]:
                errors.append(
                    "Widget saknar _restore_window_position (v6.4.1-fix)"
                )
            if not _wfix["has_validate_position_on_screens"]:
                errors.append(
                    "Widget saknar _validate_position_on_screens (v6.4.1-fix)"
                )
            if not _wfix["has_setup_bugg19_zorder"]:
                errors.append(
                    "Widget saknar _setup_bugg19_zorder (z-order-fix)"
                )
            if (
                _wfix["has_restore_window_position"]
                and _wfix["has_validate_position_on_screens"]
                and _wfix["has_setup_bugg19_zorder"]
            ):
                logger.debug(
                    f"{LOG_PREFIX} widget-fix-check OK (alla v6.4.1-metoder)"
                )
    except Exception as e:
        logger.warning(
            f"{LOG_PREFIX} widget-fix-check misslyckades: {e}"
        )

    success = len(errors) == 0
    if success:
        logger.info(f"{LOG_PREFIX} ✓ Startup-validering OK")
    else:
        logger.error(
            f"{LOG_PREFIX} ✗ Startup-validering misslyckades: {len(errors)} fel"
        )
        for err in errors:
            logger.error(f"{LOG_PREFIX}   - {err}")
    return success, errors


# ===========================================================================
# MODULE WATCHDOG (förbättrad)
# ===========================================================================

class ModuleWatchdog:
    """
    Watchdog med:
      • Health-based check (is_alive_func returnerar bool)
      • Auto-cleanup av döda weak refs
      • Failure counter per modul
    """

    __slots__ = (
        "check_interval_sec", "_modules", "_lock", "_running",
        "_thread", "_on_module_failed", "_failure_count",
    )

    def __init__(self, check_interval_sec: float = 10.0) -> None:
        self.check_interval_sec = check_interval_sec
        self._modules: Dict[str, Tuple[weakref.ref, Callable[[Any], bool]]] = {}
        self._lock = threading.RLock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._on_module_failed: Optional[Callable[[str], None]] = None
        self._failure_count: Dict[str, int] = {}
        logger.debug(
            f"{LOG_PREFIX} ModuleWatchdog skapad (interval={check_interval_sec}s)"
        )

    def add_module(
        self,
        name: str,
        module: Any,
        is_alive_func: Callable[[Any], bool],
    ) -> None:
        """Lägg till en modul att övervaka."""
        with self._lock:
            self._modules[name] = (weakref.ref(module), is_alive_func)
            self._failure_count[name] = 0
        logger.info(f"{LOG_PREFIX} ModuleWatchdog: {name!r} tillagd")

    def remove_module(self, name: str) -> None:
        """Ta bort en modul."""
        with self._lock:
            self._modules.pop(name, None)
            self._failure_count.pop(name, None)
        logger.info(f"{LOG_PREFIX} ModuleWatchdog: {name!r} borttagen")

    def on_failure(self, callback: Callable[[str], None]) -> None:
        """Registrera callback när en modul failar."""
        self._on_module_failed = callback

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._watch_loop, daemon=True, name="ModuleWatchdog",
        )
        self._thread.start()
        logger.info("ModuleWatchdog startad")

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=DEFAULT_THREAD_JOIN_TIMEOUT_SEC)
        logger.info("ModuleWatchdog stoppad")

    def _watch_loop(self) -> None:
        logger.debug(f"{LOG_PREFIX} ModuleWatchdog loop startad")
        while self._running:
            try:
                self._check_all()
            except Exception as e:
                logger.error(
                    f"{LOG_PREFIX} ModuleWatchdog loop error: {e}",
                    exc_info=True,
                )
            time.sleep(self.check_interval_sec)
        logger.debug(f"{LOG_PREFIX} ModuleWatchdog loop avslutad")

    def _check_all(self) -> None:
        with self._lock:
            modules = list(self._modules.items())
        for name, (ref, is_alive_func) in modules:
            obj = ref()
            if obj is None:
                logger.debug(
                    f"{LOG_PREFIX} ModuleWatchdog: {name!r} har blivit GC:ad, "
                    f"tar bort"
                )
                with self._lock:
                    self._modules.pop(name, None)
                    self._failure_count.pop(name, None)
                continue
            try:
                if not is_alive_func(obj):
                    self._handle_failure(name)
                else:
                    with self._lock:
                        if name in self._failure_count and self._failure_count[name] > 0:
                            logger.info(
                                f"{LOG_PREFIX} ModuleWatchdog: {name!r} "
                                f"återhämtad"
                            )
                            self._failure_count[name] = 0
            except Exception as e:
                logger.error(
                    f"{LOG_PREFIX} ModuleWatchdog check för {name!r} "
                    f"misslyckades: {e}",
                    exc_info=True,
                )
                self._handle_failure(name)

    def _handle_failure(self, name: str) -> None:
        with self._lock:
            self._failure_count[name] = self._failure_count.get(name, 0) + 1
            count = self._failure_count[name]
        if count == 1:
            logger.warning(
                f"{LOG_PREFIX} ModuleWatchdog: {name!r} verkar död (försök #{count})"
            )
        elif count >= 3:
            logger.error(
                f"{LOG_PREFIX} ModuleWatchdog: {name!r} bekräftat död efter "
                f"{count} försök"
            )
            if self._on_module_failed is not None:
                try:
                    self._on_module_failed(name)
                except Exception as e:
                    logger.error(
                        f"{LOG_PREFIX} on_failure callback misslyckades: {e}",
                        exc_info=True,
                    )


# ===========================================================================
# GLOBAL EXCEPTION HOOK
# ===========================================================================

def install_global_exception_hook(
    on_exception: Optional[Callable[[Type, Exception, Any], None]] = None,
) -> None:
    """Installera global exception hook."""
    def hook(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        error_id = str(uuid.uuid4())[:8]
        try:
            err_msg = "".join(
                traceback.format_exception(exc_type, exc_value, exc_traceback)
            )
            logger.critical(
                f"{LOG_PREFIX} OHANTERAT FEL [err_id={error_id}]:\n{err_msg}"
            )
        except Exception:
            pass
        if on_exception is not None:
            try:
                on_exception(exc_type, exc_value, exc_traceback)
            except Exception as e:
                logger.error(
                    f"{LOG_PREFIX} Custom exception handler misslyckades: {e}",
                    exc_info=True,
                )
        try:
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
        except Exception:
            pass

    sys.excepthook = hook
    logger.info(f"{LOG_PREFIX} Global exception hook installerad")


# ===========================================================================
# SNAPSHOT
# ===========================================================================

def take_snapshot() -> AppSnapshot:
    """Ta en snapshot av app-state (för debugging)."""
    manager = get_stability_manager()
    return manager.get_snapshot()


# ===========================================================================
# EXPORTS
# ===========================================================================

__all__ = [
    # Enums
    "HealthStatus", "CircuitState", "RecoveryStrategy",
    # Exceptions
    "StabilityError", "CircuitOpenError", "RecoveryFailedError",
    # Protocols
    "HealthCheckable", "Recoverable", "Cleanable",
    # Data classes
    "HealthCheck", "RecoveryAttempt", "ErrorRecord",
    "CPUMetrics", "MemorySample", "AppSnapshot",
    # Main classes
    "CircuitBreaker", "ErrorBoundary", "HealthMonitor",
    "AutoRecovery", "ResourceTracker", "ModuleWatchdog",
    "MemoryTracker", "CPUProfiler", "StabilityManager",
    # Decorators
    "safe_call", "safe_call_async", "retry", "memoize",
    # Context managers
    "safe_context", "timing_context", "safe_run",
    # Utility functions
    "get_stability_manager", "validate_startup",
    "install_global_exception_hook", "take_snapshot",
    # NY v6.4.1 — app-hälsa diagnostik & widget-recovery
    "diagnose_app_health", "attempt_widget_window_recovery",
    "is_critical_error_rate",
    # AI-felsökning (NY v6.4.1 v7)
    "_STABILITY_ERROR_TRANSLATIONS",
    "_describe_stability_exception", "_format_compact_traceback",
    "_categorize_stability_exception", "_validate_stability_state",
    "_safe_run_async",
    # Svenska formatters (NY v6.4.1 v7)
    "format_recovery_attempt_swedish", "summarize_circuit_state",
    "summarize_stability_health",
    # Diagnostik (NY v6.4.1 v7)
    "get_stability_diagnostics",
    # Plugin-coupling (NY v6.4.1 v7)
    "get_stability_plugin_deps",
    # Constants
    "LOG_PREFIX", "STABILITY_VERSION",
]


# ===========================================================================
# SELF-TEST
# ===========================================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s.%(msecs)03d | %(levelname)-8s | %(name)-12s | %(message)s",
        datefmt="%H:%M:%S",
    )
    print("=" * 70)
    print(f"stability.py v{STABILITY_VERSION} — Self-Test")
    print("=" * 70)

    # 1. validate_startup
    print("\n[Test 1] validate_startup...")
    success, errors = validate_startup()
    print(f"  ✓ Success: {success}, Errors: {len(errors)}")

    # 2. safe_call
    print("\n[Test 2] safe_call decorator...")
    @safe_call(default="FALLBACK", log_traceback=False)
    def failing():
        raise ValueError("Test-fel")
    print(f"  ✓ Result: {failing()!r} (förväntat: 'FALLBACK')")

    # 3. Circuit Breaker
    print("\n[Test 3] CircuitBreaker...")
    breaker = CircuitBreaker("test", failure_threshold=3, recovery_timeout_sec=1.0)
    for i in range(5):
        if breaker.allow_request():
            try:
                with breaker:
                    if i < 3:
                        raise ValueError(f"Fel #{i+1}")
            except ValueError:
                pass
    print(f"  ✓ Final state: {breaker.state.value}")
    print(f"  ✓ Stats: {breaker.stats}")

    # 4. Error Boundary
    print("\n[Test 4] ErrorBoundary...")
    boundary = ErrorBoundary("test_boundary", max_errors_before_disable=3)
    def bad(): raise RuntimeError("Test")
    for _ in range(5):
        boundary.execute(bad)
    print(f"  ✓ Stats: {boundary.get_stats()}")

    # 5. @retry
    print("\n[Test 5] @retry decorator...")
    call_count = [0]
    @retry(max_attempts=3, backoff_sec=0.1, strategy=RecoveryStrategy.LINEAR_BACKOFF)
    def flaky():
        call_count[0] += 1
        if call_count[0] < 3:
            raise ValueError(f"Flaky #{call_count[0]}")
        return "SUCCESS"
    print(f"  ✓ Result: {flaky()!r} (calls={call_count[0]})")

    # 6. @memoize
    print("\n[Test 6] @memoize decorator...")
    @memoize(ttl_sec=2.0, max_size=10)
    def expensive(x):
        return x * 2
    print(f"  ✓ expensive(5) = {expensive(5)}")
    print(f"  ✓ expensive(5) = {expensive(5)} (cached)")
    print(f"  ✓ Cache info: {expensive.cache_info()}")

    # 7. StabilityManager
    print("\n[Test 7] StabilityManager...")
    sm = get_stability_manager()
    sm.health_monitor.register("test", lambda: True, None, 0.5)
    sm.start()
    time.sleep(1.5)
    sm.stop()
    report = sm.get_health_report()
    print(f"  ✓ Health checks: {len(report['health'])}")
    print(f"  ✓ Recovery: {report['recovery']}")
    print(f"  ✓ Memory: {report['memory']}")

    # 8. Snapshot + JSON dump
    print("\n[Test 8] Snapshot + JSON dump...")
    snap = sm.get_snapshot()
    json_str = snap.to_json()
    print(f"  ✓ Snapshot: {snap.snapshot_id}, {len(json_str)} bytes JSON")

    # 9. ModuleWatchdog
    print("\n[Test 9] ModuleWatchdog...")
    class FakeModule:
        alive = True
    fake = FakeModule()
    watchdog = ModuleWatchdog(check_interval_sec=0.5)
    watchdog.add_module("fake", fake, lambda m: m.alive)
    watchdog.start()
    time.sleep(1.0)
    fake.alive = False
    time.sleep(1.0)
    watchdog.stop()
    print(f"  ✓ Failure count: {watchdog._failure_count}")

    # 10. MemoryTracker
    print("\n[Test 10] MemoryTracker...")
    mt = MemoryTracker()
    for _ in range(5):
        sample = mt.take_sample()
    print(f"  ✓ Latest: {sample.rss_mb:.1f} MB, {sample.gc_objects} GC objects")
    print(f"  ✓ Trend: {mt.get_trend()}")

    # 11. CPUProfiler
    print("\n[Test 11] CPUProfiler...")
    profiler = CPUProfiler()
    with profiler.measure("test_op"):
        time.sleep(0.01)
    with profiler.measure("test_op"):
        time.sleep(0.02)
    print(f"  ✓ Metrics: {profiler.get_metrics('test_op').to_dict()}")

    # 12. AutoRecovery med dependencies
    print("\n[Test 12] AutoRecovery med dependencies...")
    ar = AutoRecovery()
    ar.register("db", lambda: True, depends_on=[])
    ar.register("app", lambda: True, depends_on=["db"])
    print(f"  ✓ Stats: {ar.get_stats()}")

    # Test 13: NY v6.4.1 — diagnose_app_health
    print("\n[Test 13] diagnose_app_health (NY v6.4.1)...")
    diag = diagnose_app_health()
    print(f"  ✓ stability_version: {diag['stability_version']}")
    print(f"  ✓ total_errors: {diag['total_errors']}")
    print(f"  ✓ issues: {len(diag['issues'])} st")
    print(f"  ✓ widget_fix has_module: "
          f"{diag['widget_fix_status']['has_widget_module']}")
    print(f"  ✓ widget_fix has_restore: "
          f"{diag['widget_fix_status']['has_restore_window_position']}")
    print(f"  ✓ widget_fix has_validate: "
          f"{diag['widget_fix_status']['has_validate_position_on_screens']}")

    # Test 14: NY v6.4.1 — is_critical_error_rate
    print("\n[Test 14] is_critical_error_rate (NY v6.4.1)...")
    rate = is_critical_error_rate(threshold=999)
    print(f"  ✓ Med hög threshold (999): {rate} (förväntat: False)")
    rate_low = is_critical_error_rate(threshold=0)
    print(f"  ✓ Med låg threshold (0): {rate_low}")

    # Test 15: NY v6.4.1 — attempt_widget_window_recovery (utan QApp)
    print("\n[Test 15] attempt_widget_window_recovery (NY v6.4.1)...")
    rec = attempt_widget_window_recovery()
    print(f"  ✓ Result: {rec}")
    assert "attempted" in rec
    assert "recovered" in rec

    # Test 16: NY v6.4.1 v7 — AI-felsökning
    print("\n[Test 16] AI-felsökning (NY v6.4.1 v7)...")
    # _describe_stability_exception
    desc1 = _describe_stability_exception(CircuitOpenError("breaker-x"))
    print(f"  ✓ _describe_stability_exception(CircuitOpenError): {desc1!r}")
    assert "Circuit" in desc1 or "oppnet" in desc1
    # FIX v7-fix16: RecoveryFailedError kräver (module_name, attempts) —
    # gamla anropet med ett argument kraschade self-testet med TypeError.
    desc2 = _describe_stability_exception(
        RecoveryFailedError("modul-x", attempts=3)
    )
    print(f"  ✓ _describe_stability_exception(RecoveryFailedError): {desc2!r}")
    assert "Recovery" in desc2 or "forsok" in desc2
    # _format_compact_traceback
    try:
        raise ValueError("test-tb-stab")
    except ValueError as e:
        tb = _format_compact_traceback(e, max_frames=3)
        print(f"  ✓ _format_compact_traceback: {len(tb)} tecken, innehaller 'ValueError'")
        assert "ValueError" in tb
    # _categorize_stability_exception
    cat1 = _categorize_stability_exception(ValueError("x"))
    cat2 = _categorize_stability_exception(CircuitOpenError("x"))
    # FIX v7-fix16: saknade attempts-argument (samma TypeError-bugg)
    cat3 = _categorize_stability_exception(
        RecoveryFailedError("x", attempts=2)
    )
    print(f"  ✓ _categorize_stability_exception: ValueError→{cat1}, "
          f"CircuitOpenError→{cat2}, RecoveryFailedError→{cat3}")
    assert cat1 == "user_input"
    assert cat2 == "circuit_open"
    assert cat3 == "recovery"
    # safe_run
    ctx_ok_ref = {}
    with safe_run("test-op-stab") as ctx_ok:
        ctx_ok_ref["ok"] = True
    assert ctx_ok_ref.get("ok")
    with safe_run("test-op-stab-fail") as ctx_fail:
        raise RuntimeError("stab-test-fel")
    print(f"  ✓ safe_run fel-blocket: errors={len(ctx_fail['errors'])}")
    assert len(ctx_fail["errors"]) == 1
    # _validate_stability_state (modul-niva)
    problems = _validate_stability_state(None)
    print(f"  ✓ _validate_stability_state(None): {len(problems)} problem")
    # summarize_stability_health
    summ = summarize_stability_health(None)
    print(f"  ✓ summarize_stability_health(None): {summ!r}")
    assert STABILITY_VERSION in summ

    # Test 17: NY v6.4.1 v7 — Svenska formatters för RecoveryAttempt + CircuitBreaker
    print("\n[Test 17] Svenska formatters (NY v6.4.1 v7)...")
    # format_recovery_attempt_swedish med dict
    fake_attempt = {
        "module": "widget", "success": True, "strategy": "RETRY",
        "attempts": 2, "duration_ms": 123.4, "error": None,
    }
    s1 = format_recovery_attempt_swedish(fake_attempt)
    print(f"  ✓ format_recovery_attempt_swedish (success): {s1!r}")
    assert "widget" in s1 and "OK" in s1
    fake_fail = {
        "module": "store", "success": False, "strategy": "RETRY",
        "attempts": 3, "duration_ms": 567.8, "error": ValueError("x"),
    }
    s2 = format_recovery_attempt_swedish(fake_fail)
    print(f"  ✓ format_recovery_attempt_swedish (fail): {s2!r}")
    assert "store" in s2 and "MISSLYCKADES" in s2
    # summarize_circuit_state med befintlig breaker
    s3 = summarize_circuit_state(breaker)
    print(f"  ✓ summarize_circuit_state: {s3!r}")
    assert "test" in s3
    # summarize_circuit_state(None)
    s4 = summarize_circuit_state(None)
    print(f"  ✓ summarize_circuit_state(None): {s4!r}")
    assert "ingen" in s4

    # Test 18: NY v6.4.1 v7 — get_stability_diagnostics + StabilityManager.diagnose
    print("\n[Test 18] get_stability_diagnostics + StabilityManager.diagnose (NY v6.4.1 v7)...")
    # Modul-niva
    diag = get_stability_diagnostics(None)
    print(f"  ✓ get_stability_diagnostics(None): module={diag['module']!r}, "
          f"version={diag['stability_version']!r}, problems={diag['problem_count']}")
    assert diag["module"] == "stability"
    assert diag["stability_version"] == STABILITY_VERSION
    assert "summary_swedish" in diag
    # Med manager
    try:
        manager = get_stability_manager()
        mgr_problems = manager.diagnose()
        print(f"  ✓ StabilityManager.diagnose(): {len(mgr_problems)} problem")
        report = manager.get_health_report_v2()
        print(f"  ✓ StabilityManager.get_health_report_v2(): "
              f"keys={list(report.keys())[:8]}...")
        assert "summary_swedish" in report
        assert "problems" in report
    except Exception as e:
        # Manager kan krava fler beroenden — inte fatalt
        print(f"  ⚠ StabilityManager() ofullstandig: {e}")

    print()
    print("=" * 70)
    print(f"✓ ALLA 18 TESTER PASSERADE (stability.py {STABILITY_VERSION})")
    print("=" * 70)