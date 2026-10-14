# -*- coding: utf-8 -*-
"""Strukturerad loggning till data/todo_app.log."""

from __future__ import annotations

import logging.handlers
import sys
from contextlib import suppress
from pathlib import Path
from typing import Final, List, Optional

from app.central_log import install_central_log_handler
from app.constants import LogLevel
from app.platform_utils import _is_pyw


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
