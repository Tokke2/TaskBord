# -*- coding: utf-8 -*-
"""Konstanter: version, sökvägar, enums och undantag."""

from __future__ import annotations

import sys
from enum import Enum
from enum import auto
from pathlib import Path
from typing import Any, Dict, Final, Optional, Tuple, TypeVar


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
SCRIPT_DIR: Final[Path] = Path(__file__).resolve().parent.parent  # app/ ligger direkt under appmappen


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
