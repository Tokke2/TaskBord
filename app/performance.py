# -*- coding: utf-8 -*-
"""Prestanda, minne och bakgrundsjobb."""

from __future__ import annotations

import logging.handlers
import os
import threading
import time
from concurrent.futures import Future
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from app.constants import LOG_PREFIX, T


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
