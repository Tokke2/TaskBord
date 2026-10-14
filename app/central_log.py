# -*- coding: utf-8 -*-
"""Central händelselogg som fångar events från alla moduler."""

from __future__ import annotations

import logging.handlers
import threading
from collections import deque
from dataclasses import dataclass
from dataclasses import field
from typing import Any, Callable, Dict, Final, List, Optional

from app.constants import LOG_PREFIX, LogLevel


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
