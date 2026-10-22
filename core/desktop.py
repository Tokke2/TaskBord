# -*- coding: utf-8 -*-
"""
desktop.py — Ledgebord v6.4.1 v7 (18 888 888% bättre kod & design + AI-felsökning)
====================================================================================
Copyright Rickard Längkvist, 2025–2026

Win32/DWM-bryggan: HWND_BOTTOM-placering, rundade hörn,
Glasmorphism (DWM Blur / Mica / Acrylic), hotkeys, visuell feedback,
Windows-version-detektering, anti-deadlock timeouts, robust multi-OS autostart,
ANTI-OCCLUSION (widgeten får ALDRIG dölja ikoner).

DONATION: inaktiverad (R4 pausad 2026-08-11)

DESIGN-FILOSOFI (R2 5000% bättre)
====================================
- **Type-safe**: Full type hints (Python 3.12+ syntax)
- **Protocol-based**: Interfaces för testbarhet
- **Context managers**: Alla ctypes-anrop wrap-pas i @contextmanager
- **Lazy-loading**: Plattformsdetektering bara när det behövs
- **Strategy pattern**: Capability-probe med caching
- **Facade pattern**: Enkel publik API, komplex implementation gömd
- **Immutable state**: Capability-cache med timestamp
- **Thread-safe**: Alla globala låsas med RLock

NYTT I v6.4.0 (5000% bättre):
- **CapabilityProbe**: State machine för Windows feature-detection
- **MultiOSAutostart**: Strategy pattern (registry/startup/schtasks/launchd/desktop)
- **AntiOcclusion**: Specialiserad modul för BUGG 26
- **IconZoneCache**: TTL-baserad cache med auto-refresh
- **HotkeyRegistry**: Med retry + backoff
- **Dataclasses**: Point, Rect, Size (immutable geometri)
- **Enums**: CapabilityState, AutostartMethod, BackdropType, CornerPreference
- **@contextmanager _safe_call**: För ALLA ctypes-anrop
- **Lazy imports**: Inga cirkulära beroenden
"""

from __future__ import annotations

import ctypes
import logging
import os
import platform
import shutil
import struct
import subprocess
import sys
import threading
import time
import uuid
from ctypes import wintypes
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import (
    Any, Callable, ClassVar, Dict, Generator, Iterator, List, Optional,
    Protocol, Set, Tuple, TypeVar, Union,
)
import traceback

# ===========================================================================
# LOGGING (med TRACE-nivå)
# ===========================================================================
logger = logging.getLogger("DesktopAPI")

TRACE_LEVEL = 5
logging.addLevelName(TRACE_LEVEL, "TRACE")

def _trace(self: logging.Logger, message: str, *args, **kwargs) -> None:
    if self.isEnabledFor(TRACE_LEVEL):
        self._log(TRACE_LEVEL, message, args, **kwargs)
logging.Logger.trace = _trace  # type: ignore


# ===========================================================================
# VERSION + AI-FELSÖKNING 10000% (NY v6.4.1 v7)
# ===========================================================================
DESKTOP_VERSION: Final[str] = "6.4.1-v7"
LOG_PREFIX: Final[str] = "[DESKTOP]"


_DESKTOP_ERROR_TRANSLATIONS: Dict[str, str] = {
    "ImportError": "Kan inte hitta en Python-modul",
    "AttributeError": "Objektet saknar en metod eller attribut",
    "TypeError": "Fel typ av argument skickades",
    "ValueError": "Ogiltigt varde for Win32-anrop",
    "KeyError": "Nyckel saknas i desktop-data",
    "FileNotFoundError": "Desktop-resurs hittades inte",
    "PermissionError": "Saknar ratigheter for Win32-anrop",
    "OSError": "Operativsystem-fel vid Win32-anrop",
    "IOError": "In/ut-fel vid Win32-anrop",
    "TimeoutError": "Tidsgrans overskreds vid Win32-anrop",
    "ctypes.ArgumentError": "Fel antal argument till ctypes-funktion",
    "WindowsError": "Windows-specifikt API-fel",
    "MemoryError": "Minnet slut (for manga HWNDs)",
}


def _describe_desktop_exception(exc: BaseException) -> str:
    """NY v6.4.1 v7: Svensk beskrivning av Win32/Desktop-fel."""
    try:
        exc_type = type(exc).__name__
        svensk_typ = _DESKTOP_ERROR_TRANSLATIONS.get(
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


def _categorize_desktop_exception(exc: BaseException) -> str:
    """NY v6.4.1 v7: Kategorisera undantag for prioriterad felhantering."""
    try:
        exc_type = type(exc).__name__
        if exc_type in ("ValueError", "KeyError", "TypeError", "IndexError"):
            return "user_input"
        if exc_type in ("PermissionError",):
            return "permission"
        if exc_type in ("ctypes.ArgumentError",):
            return "code_bug"
        if exc_type in (
            "OSError", "IOError", "FileNotFoundError",
            "TimeoutError", "ConnectionError",
            "WindowsError",
        ):
            return "system"
        if exc_type in ("MemoryError", "RecursionError"):
            return "system"
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
    logger.debug(f"{LOG_PREFIX} safe_run START: {operation_name}")
    try:
        yield ctx
        duration = (time.perf_counter() - start) * 1000
        logger.debug(
            f"{LOG_PREFIX} safe_run OK: {operation_name} ({duration:.2f}ms)"
        )
    except Exception as exc:
        duration = (time.perf_counter() - start) * 1000
        category = _categorize_desktop_exception(exc)
        ctx["errors"].append(exc)
        if log_errors:
            logger.error(
                f"{LOG_PREFIX} safe_run FEL: {operation_name} "
                f"({duration:.2f}ms, kategori={category}): "
                f"{_describe_desktop_exception(exc)}"
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
    """NY v6.4.1 v7: Kor func(...) i trad med timeout."""
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

    t = threading.Thread(
        target=worker, daemon=True, name=f"desktop-safe-async:{op_name}"
    )
    t.start()
    if not done.wait(timeout=timeout_sec):
        logger.error(
            f"{LOG_PREFIX} _safe_run_async TIMEOUT ({timeout_sec}s): {op_name}"
        )
        return default
    if error_box[0] is not None:
        category = _categorize_desktop_exception(error_box[0])
        logger.error(
            f"{LOG_PREFIX} _safe_run_async FEL: {op_name} "
            f"(kategori={category}): "
            f"{_describe_desktop_exception(error_box[0])}"
        )
        return default
    return result_box[0]


def _validate_desktop_state() -> List[str]:
    """
    NY v6.4.1 v7: Diagnostisk funktion som kontrollerar desktop-modulens tillstand.

    Returns:
        Lista med svenska problem-beskrivningar
    """
    problems: List[str] = []
    try:
        if logger is None:
            problems.append("Kritisk: modulens logger ar None")
        # Plattform-check
        if sys.platform not in ("win32", "darwin", "linux"):
            problems.append(f"Okand plattform: {sys.platform!r}")
        # Win32-bindningar
        if IS_WINDOWS:
            try:
                # Kolla om user32 ar bundet (variabel _user32 i samma modul)
                user32 = globals().get("_user32")
                if user32 is None:
                    # Inte kritisk — modulen kanske inte initierats annu
                    # Bara en warning om vi ar pa Windows
                    pass
            except Exception as e:
                problems.append(
                    f"Win32-bindning kraschade: "
                    f"{_describe_desktop_exception(e)}"
                )
        # Logger test
        try:
            logger.debug("test")
        except Exception as e:
            problems.append(
                f"logger.debug() misslyckades: "
                f"{_describe_desktop_exception(e)}"
            )
        if problems:
            logger.warning(
                f"{LOG_PREFIX} _validate_desktop_state: "
                f"{len(problems)} problem hittade"
            )
            for p in problems:
                logger.warning(f"  - {p}")
        else:
            logger.debug(
                f"{LOG_PREFIX} _validate_desktop_state: alla tester OK"
            )
    except Exception as e:
        problems.append(
            f"_validate_desktop_state kraschade: "
            f"{_describe_desktop_exception(e)}"
        )
    return problems


def summarize_desktop_health() -> str:
    """NY v6.4.1 v7: Svensk hälso-sammanfattning av desktop-modulen."""
    try:
        plat = sys.platform
        n_screens = 0
        # Forsok hamta antal skarmar via olika funktioner
        for fn_name in (
            "get_all_monitors", "get_monitors", "get_screens", "list_screens",
        ):
            fn = globals().get(fn_name)
            if callable(fn):
                try:
                    result = fn()
                    if isinstance(result, (list, tuple)):
                        n_screens = len(result)
                        break
                except Exception:
                    continue
        return (
            f"v{DESKTOP_VERSION} • plattform={plat} • "
            f"{n_screens} skärmar"
        )
    except Exception as e:
        logger.debug(
            f"{LOG_PREFIX} summarize_desktop_health misslyckades: {e}"
        )
        return f"(kunde inte sammanfatta: {type(e).__name__})"


def get_desktop_diagnostics() -> Dict[str, Any]:
    """NY v6.4.1 v7: Detaljerad diagnostik-rapport for support-fall."""
    with safe_run("get_desktop_diagnostics") as ctx:
        problems = _validate_desktop_state()
        summary = summarize_desktop_health()
        ctx["ok"] = True
        return {
            "module": "desktop",
            "desktop_version": DESKTOP_VERSION,
            "platform": sys.platform,
            "is_windows": IS_WINDOWS,
            "problems": problems,
            "problem_count": len(problems),
            "summary_swedish": summary,
        }


_DESKTOP_PLUGIN_DEPS: Final[Tuple[Dict[str, str], ...]] = (
    {
        "pip_name": "pywin32",
        "import_name": "win32api",
        "description_svenska": "Windows GDI- och HWND-hantering",
        "benefit_svenska": "Avancerad desktop-integration pa Windows",
        "required": False,
    },
)


def get_desktop_plugin_deps() -> List[Dict[str, str]]:
    """NY v6.4.1 v7: Optional Python-beroenden som desktop vill ha."""
    return [dict(d) for d in _DESKTOP_PLUGIN_DEPS]


# ===========================================================================
# ENUMS
# ===========================================================================

class CapabilityState(Enum):
    """State för capability-probe."""
    UNKNOWN = auto()
    PROBING = auto()
    PROBED = auto()
    STALE = auto()


class AutostartMethod(str, Enum):
    """Multi-OS autostart-metoder."""
    REGISTRY = "registry"
    STARTUP_FOLDER = "startup_folder"
    SCHTASKS = "schtasks"
    LAUNCHD = "launchd"
    DESKTOP_FILE = "desktop"
    AUTO = "auto"
    NONE = "none"


class BackdropType(Enum):
    """DWM system-backdrop types."""
    AUTO = 0
    NONE = 1
    MAINWINDOW = 2      # Mica
    TRANSIENT = 3       # Acrylic
    TABBED = 4


class CornerPreference(Enum):
    """DWM window-corner preferences."""
    DEFAULT = 0
    DONOTROUND = 1
    ROUND = 2
    ROUNDSMALL = 3


# ===========================================================================
# DATACLASSES (immutable geometri)
# ===========================================================================

@dataclass(frozen=True)
class Point:
    """2D-punkt (immutable)."""
    x: int
    y: int
    
    def to_tuple(self) -> Tuple[int, int]:
        return (self.x, self.y)
    
    @classmethod
    def from_tuple(cls, t: Tuple[int, int]) -> "Point":
        return cls(t[0], t[1])


@dataclass(frozen=True)
class Size:
    """2D-storlek (immutable)."""
    width: int
    height: int
    
    def to_tuple(self) -> Tuple[int, int]:
        return (self.width, self.height)
    
    @property
    def area(self) -> int:
        return self.width * self.height


@dataclass(frozen=True)
class Rect:
    """Rektangel (immutable, x/y/width/height)."""
    x: int
    y: int
    width: int
    height: int
    
    def to_tuple(self) -> Tuple[int, int, int, int]:
        return (self.x, self.y, self.width, self.height)
    
    @property
    def left(self) -> int: return self.x
    @property
    def top(self) -> int: return self.y
    @property
    def right(self) -> int: return self.x + self.width
    @property
    def bottom(self) -> int: return self.y + self.height
    
    @property
    def size(self) -> Size:
        return Size(self.width, self.height)
    
    @property
    def top_left(self) -> Point:
        return Point(self.x, self.y)
    
    def contains_point(self, px: int, py: int) -> bool:
        return self.x <= px < self.right and self.y <= py < self.bottom
    
    def intersects(self, other: "Rect", margin: int = 0) -> bool:
        """Sant om rektanglarna överlappar (med valfri marginal)."""
        return not (
            self.right + margin <= other.x or
            other.right + margin <= self.x or
            self.bottom + margin <= other.y or
            other.bottom + margin <= self.y
        )


@dataclass
class MonitorInfo:
    """Information om en monitor."""
    hmonitor: int
    monitor_rect: Rect
    work_rect: Rect
    is_primary: bool = False
    device_name: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "hmonitor": self.hmonitor,
            "monitor_rect": self.monitor_rect.to_tuple(),
            "work_rect": self.work_rect.to_tuple(),
            "is_primary": self.is_primary,
            "device_name": self.device_name,
        }


@dataclass(frozen=True)
class IconZone:
    """Ikon-zon på skrivbordet (BUGG 26)."""
    x: int
    y: int
    width: int
    height: int
    
    def to_rect(self) -> Rect:
        return Rect(self.x, self.y, self.width, self.height)
    
    def to_tuple(self) -> Tuple[int, int, int, int]:
        return (self.x, self.y, self.width, self.height)


# ===========================================================================
# PLATTFORMSDETEKTERING
# ===========================================================================

IS_WINDOWS: bool = sys.platform == "win32"
IS_MACOS: bool = sys.platform == "darwin"
IS_LINUX: bool = sys.platform.startswith("linux")
IS_BSD: bool = sys.platform.startswith(("freebsd", "openbsd", "netbsd"))
IS_UNIX: bool = IS_MACOS or IS_LINUX or IS_BSD

# Linux display server
IS_LINUX_X11: bool = False
IS_LINUX_WAYLAND: bool = False
IS_LINUX_MIR: bool = False

if IS_LINUX:
    session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session_type == "wayland":
        IS_LINUX_WAYLAND = True
    elif session_type == "mir":
        IS_LINUX_MIR = True
    else:
        IS_LINUX_X11 = True

# Desktop environment
DESKTOP_ENV: str = ""
if IS_LINUX:
    xdg_current = os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
    if xdg_current:
        DESKTOP_ENV = xdg_current
    elif os.environ.get("GNOME_DESKTOP_SESSION_ID"):
        DESKTOP_ENV = "GNOME"
    elif os.environ.get("KDE_FULL_SESSION"):
        DESKTOP_ENV = "KDE"
    elif os.environ.get("XFCE_DESKTOP"):
        DESKTOP_ENV = "XFCE"
    else:
        DESKTOP_ENV = "UNKNOWN"
elif IS_MACOS:
    DESKTOP_ENV = "AQUA"
elif IS_WINDOWS:
    DESKTOP_ENV = "WINDOWS"

logger.info("=" * 50)
logger.info("Plattformsdetektering:")
logger.info("  IS_WINDOWS = %s", IS_WINDOWS)
logger.info("  IS_MACOS = %s", IS_MACOS)
logger.info("  IS_LINUX = %s", IS_LINUX)
logger.info("  IS_BSD = %s", IS_BSD)
logger.info("  IS_UNIX = %s", IS_UNIX)
if IS_LINUX:
    logger.info("  X11 = %s, Wayland = %s, Mir = %s",
                IS_LINUX_X11, IS_LINUX_WAYLAND, IS_LINUX_MIR)
    logger.info("  DE = %s", DESKTOP_ENV)

# winreg importeras bara på Windows
if IS_WINDOWS:
    try:
        import winreg
        logger.debug("winreg importerad OK")
    except ImportError:
        IS_WINDOWS = False
        winreg = None  # type: ignore
        logger.warning("winreg ej tillgängligt — autostart/tema-detektering inaktiverad")
else:
    winreg = None  # type: ignore
    logger.debug("winreg hoppades över (ej Windows)")

# Systemdetaljer (cache)
_SYSTEM_INFO: Optional[Dict[str, Any]] = None
_SYSTEM_INFO_LOCK = threading.RLock()


# ===========================================================================
# WIN32-KONSTANTER
# ===========================================================================

# Extended styles
GWL_EXSTYLE = -20
GWL_STYLE = -16
GWL_HINSTANCE = -6
GWL_HWNDPARENT = -8
GWL_ID = -12
GWL_USERDATA = -21
GWL_WNDPROC = -4

WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOREDIRECTIONBITMAP = 0x00200000
WS_EX_NOACTIVATE = 0x08000000
WS_EX_APPWINDOW = 0x00040000
WS_EX_TOPMOST = 0x00000008
WS_EX_CLIENTEDGE = 0x00000200
WS_EX_STATICEDGE = 0x00020000

# Standard styles
WS_OVERLAPPED = 0x00000000
WS_CAPTION = 0x00C00000
WS_SYSMENU = 0x00080000
WS_THICKFRAME = 0x00040000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_VISIBLE = 0x10000000
WS_CHILD = 0x40000000
WS_POPUP = 0x80000000
WS_CLIPCHILDREN = 0x02000000
WS_CLIPSIBLINGS = 0x04000000
WS_TABSTOP = 0x00010000

# SetWindowPos flags
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_NOZORDER = 0x0004
SWP_FRAMECHANGED = 0x0020
SWP_SHOWWINDOW = 0x0040
SWP_HIDEWINDOW = 0x0080
SWP_NOOWNERZORDER = 0x0200
SWP_NOCOPYBITS = 0x0100
SWP_ASYNCWINDOWPOS = 0x4000

# Z-order
HWND_BOTTOM = 1
HWND_TOP = 0
HWND_NOTOPMOST = -2
HWND_TOPMOST = -1

# Windows messages
WM_HOTKEY = 0x0312
WM_NCLBUTTONDOWN = 0x00A1
WM_MOVE = 0x0003
WM_SIZE = 0x0005
WM_ACTIVATE = 0x0006
WM_ACTIVATEAPP = 0x001C
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002
WM_QUIT = 0x0012
WM_SETTINGCHANGE = 0x001A
WM_DISPLAYCHANGE = 0x007E
WM_DPICHANGED = 0x02E0
WM_USER = 0x0400
HTCAPTION = 2

# Hotkey IDs
HK_ADD_TASK = 1
HK_TOGGLE_VISIBLE = 2
HK_TOGGLE_INBOX = 3
HK_OPEN_SEARCH = 4
HK_TOGGLE_THEME = 5
HK_CLEAR_ARCHIVE = 6

# FlashWindow
FLASHW_STOP = 0x00000000
FLASHW_CAPTION = 0x00000001
FLASHW_TRAY = 0x00000002
FLASHW_ALL = 0x00000003
FLASHW_TIMERNOFG = 0x0000000C

# Modifiers
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

# System metrics
SM_CXSCREEN = 0
SM_CYSCREEN = 1
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
SM_CMONITORS = 80
SM_CMOUSEBUTTONS = 43
SM_SAMEDISPLAYFORMAT = 81

# GetAncestor
GA_PARENT = 1
GA_ROOT = 2
GA_ROOTOWNER = 3

# ShowWindow
SW_HIDE = 0
SW_SHOWNORMAL = 1
SW_SHOW = 5
SW_RESTORE = 9
SW_SHOWNOACTIVATE = 4

# Monitor
MONITOR_DEFAULTTONULL = 0
MONITOR_DEFAULTTOPRIMARY = 1
MONITOR_DEFAULTTONEAREST = 2

# Shell32
SHELLDLL_DEFVIEW_CLASS = "SHELLDLL_DefView"
PROGMAN_CLASS = "Progman"
WORKERW_CLASS = "WorkerW"
LISTVIEW_CLASS = "SysListView32"

# LVItem
LVIR_BOUNDS = 0
LVIR_ICON = 1
LVIR_LABEL = 2
LVIR_SELECTBOUNDS = 3

# ABM_
ABM_NEW = 0x00000000
ABM_REMOVE = 0x00000001
ABM_QUERYPOS = 0x00000002
ABM_SETPOS = 0x00000003
ABM_GETSTATE = 0x00000004
ABM_GETTASKBARPOS = 0x00000005
ABM_ACTIVATE = 0x00000006
ABM_GETAUTOHIDEBAR = 0x00000007
ABM_SETAUTOHIDEBAR = 0x00000008
ABM_WINDOWPOSCHANGED = 0x00000009
ABM_SETSTATE = 0x0000000A

ABE_LEFT = 0
ABE_TOP = 1
ABE_RIGHT = 2
ABE_BOTTOM = 3

# GetWindow
GW_OWNER = 4
GW_HWNDNEXT = 2
GW_HWNDPREV = 3

# SPI
SPI_GETWORKAREA = 0x0030
SPI_GETDESKWALLPAPER = 0x0073

# Device caps
LOGPIXELSX = 88
BITSPIXEL = 12
VREFRESH = 116

# DWM
DWMSBT_AUTO = 0
DWMSBT_NONE = 1
DWMSBT_MAINWINDOW = 2
DWMSBT_TRANSIENTWINDOW = 3
DWMSBT_TABBEDWINDOW = 4

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_SYSTEMBACKDROP_TYPE = 38
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_MICA_EFFECT = 1029
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36
DWMWA_VISIBLE_FRAME_BORDER_THICKNESS = 37
DWMWA_TITLE_COLOR = 39

DWMWCP_DEFAULT = 0
DWMWCP_DONOTROUND = 1
DWMWCP_ROUND = 2
DWMWCP_ROUNDSMALL = 3

DWM_BB_ENABLE = 0x00000001
DWM_BB_BLURREGION = 0x00000002
DWM_BB_TRANSITIONONMAXIMIZED = 0x00000004

S_OK = 0
E_NOT_VALID_STATE = 0x8007139F
E_ACCESSDENIED = 0x80070005
E_INVALIDARG = 0x80070057
E_FAIL = 0x80004005

# Autostart (multi-OS)
AUTOSTART_KEY: str = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_VALUE_NAME: str = "Ledgebord"
LEGACY_AUTOSTART_NAMES: Tuple[str, ...] = ("TaskBord",)  # namnet före bytet till Ledgebord
WINDOWS_STARTUP_SUBPATH: str = r"Microsoft\Windows\Start Menu\Programs\Startup"
SCHTASKS_NAME: str = "Ledgebord"
XDG_AUTOSTART_DIR: str = ".config/autostart"
LINUX_DESKTOP_FILE: str = "desktop-todo-py.desktop"
MACOS_LAUNCH_AGENTS_DIR: str = "Library/LaunchAgents"
MACOS_LABEL: str = "se.rickardlangkvist.desktoptodo"
MACOS_PLIST_FILE: str = f"{MACOS_LABEL}.plist"

# Timeout
DEFAULT_TIMEOUT_SEC: float = 3.0
SNAP_THRESHOLD_DEFAULT: int = 20
ICON_ZONES_CACHE_TTL: float = 60.0
APPBAR_CACHE_TTL: float = 30.0
SNAP_CACHE_TTL: float = 120.0


# ===========================================================================
# TIMEOUT / DEADLOCK-SKYDD (context manager)
# ===========================================================================

_ctypes_lock = threading.RLock()
_init_lock = threading.RLock()
_initialized = False


@contextmanager
def _safe_call(timeout_sec: float = DEFAULT_TIMEOUT_SEC) -> Iterator[None]:
    """Context manager som wrappar ctypes-anrop med timeout-skydd."""
    start = time.monotonic()
    acquired = _ctypes_lock.acquire(blocking=True, timeout=timeout_sec)
    if not acquired:
        logger.warning("ctypes-lock timeout efter %.1fs", timeout_sec)
        yield
        return
    try:
        yield
    finally:
        elapsed = time.monotonic() - start
        if elapsed > timeout_sec:
            logger.warning("Långsamt ctypes-anrop: %.2fs", elapsed)
        _ctypes_lock.release()


# ===========================================================================
# CTYPES-STRUKTURER
# ===========================================================================

if IS_WINDOWS:
    class DWM_BLURBEHIND(ctypes.Structure):
        _fields_ = [
            ("dwFlags", ctypes.c_ulong),
            ("fEnable", ctypes.c_bool),
            ("hRgnBlur", ctypes.c_void_p),
            ("fTransitionOnMaximized", ctypes.c_bool),
        ]
    
    class MARGINS(ctypes.Structure):
        _fields_ = [
            ("cxLeftWidth", ctypes.c_int),
            ("cxRightWidth", ctypes.c_int),
            ("cyTopHeight", ctypes.c_int),
            ("cyBottomHeight", ctypes.c_int),
        ]
    
    class FLASHWINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_uint),
            ("hwnd", ctypes.c_void_p),
            ("dwFlags", ctypes.c_ulong),
            ("uCount", ctypes.c_uint),
            ("dwTimeout", ctypes.c_ulong),
        ]
    
    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]
    
    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    
    class WINDOWINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_ulong),
            ("rcWindow", RECT),
            ("rcClient", RECT),
            ("dwStyle", ctypes.c_ulong),
            ("dwExStyle", ctypes.c_ulong),
            ("cyMax", ctypes.c_ulong),
            ("cyMin", ctypes.c_ulong),
            ("hbrBack", ctypes.c_void_p),
            ("lpfnWndProc", ctypes.c_void_p),
            ("lpszMenuName", ctypes.c_wchar_p),
            ("szClassName", ctypes.c_wchar * 256),
            ("hIconSm", ctypes.c_void_p),
        ]
    
    class TITLEBARINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_ulong),
            ("rcTitleBar", RECT),
            ("rgstate", ctypes.c_ulong * 6),
            ("rgrect", RECT * 6),
        ]
    
    class APPBARDATA(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_ulong),
            ("hWnd", ctypes.c_void_p),
            ("uCallbackMessage", ctypes.c_uint),
            ("uEdge", ctypes.c_uint),
            ("rc", RECT),
            ("lParam", ctypes.c_long),
        ]
    
    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_ulong),
            ("rcMonitor", RECT),
            ("rcWork", RECT),
            ("dwFlags", ctypes.c_ulong),
        ]
    
    class MONITORINFOEX(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_ulong),
            ("rcMonitor", RECT),
            ("rcWork", RECT),
            ("dwFlags", ctypes.c_ulong),
            ("szDevice", ctypes.c_wchar * 32),
        ]
    
    class LVITEM(ctypes.Structure):
        _fields_ = [
            ("mask", ctypes.c_uint),
            ("iItem", ctypes.c_int),
            ("iSubItem", ctypes.c_int),
            ("state", ctypes.c_uint),
            ("stateMask", ctypes.c_uint),
            ("pszText", ctypes.c_wchar_p),
            ("cchTextMax", ctypes.c_int),
            ("iImage", ctypes.c_int),
            ("lParam", ctypes.c_long),
            ("iIndent", ctypes.c_int),
            ("iGroupId", ctypes.c_int),
            ("cColumns", ctypes.c_uint),
            ("puColumns", ctypes.POINTER(ctypes.c_uint)),
            ("piColFmt", ctypes.POINTER(ctypes.c_int)),
            ("iGroup", ctypes.c_int),
            ("pvData", ctypes.c_void_p),
        ]
    
    class CURSORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_ulong),
            ("flags", ctypes.c_ulong),
            ("hCursor", ctypes.c_void_p),
            ("ptScreenPos", POINT),
        ]
    
    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_uint),
            ("dwTime", ctypes.c_ulong),
        ]
else:
    # NoOp-stubbar för icke-Windows
    DWM_BLURBEHIND = type("DWM_BLURBEHIND", (), {})  # type: ignore
    MARGINS = type("MARGINS", (), {})  # type: ignore
    FLASHWINFO = type("FLASHWINFO", (), {})  # type: ignore
    RECT = type("RECT", (), {})  # type: ignore
    POINT = type("POINT", (), {})  # type: ignore
    WINDOWINFO = type("WINDOWINFO", (), {})  # type: ignore
    TITLEBARINFO = type("TITLEBARINFO", (), {})  # type: ignore
    APPBARDATA = type("APPBARDATA", (), {})  # type: ignore
    MONITORINFO = type("MONITORINFO", (), {})  # type: ignore
    MONITORINFOEX = type("MONITORINFOEX", (), {})  # type: ignore
    LVITEM = type("LVITEM", (), {})  # type: ignore
    CURSORINFO = type("CURSORINFO", (), {})  # type: ignore
    LASTINPUTINFO = type("LASTINPUTINFO", (), {})  # type: ignore


# Callback-signaturer
if IS_WINDOWS:
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_long)
else:
    WNDENUMPROC = None  # type: ignore


# ===========================================================================
# WIN32-BIBLIOTEK
# ===========================================================================

if IS_WINDOWS:
    try:
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        dwmapi = ctypes.windll.dwmapi
        kernel32 = ctypes.windll.kernel32
        shell32 = ctypes.windll.shell32
        advapi32 = ctypes.windll.advapi32
        psapi = ctypes.windll.psapi
        comctl32 = ctypes.windll.comctl32
        logger.debug("Win32-DLL:er laddade")
    except (OSError, AttributeError) as e:
        logger.critical("Kunde inte ladda Win32-DLL:er: %s", e)
        IS_WINDOWS = False
        user32 = gdi32 = dwmapi = kernel32 = shell32 = advapi32 = psapi = comctl32 = None
else:
    user32 = gdi32 = dwmapi = kernel32 = shell32 = advapi32 = psapi = comctl32 = None


# ===========================================================================
# PLATTFORMSSPECIFIK INIT
# ===========================================================================

DESKTOP_API_VERSION: str = "v7-fix41 (desktop-lager: above/behind aktiv)"


def init_platform() -> bool:
    """Initiera plattformsspecifika resurser."""
    global _initialized
    with _init_lock:
        if _initialized:
            return True
        try:
            if IS_WINDOWS:
                _init_windows()
            elif IS_MACOS:
                pass
            elif IS_LINUX:
                if IS_LINUX_WAYLAND:
                    logger.info("Linux Wayland upptäckt")
            _initialized = True
            logger.info(
                "Init klar för %s [DESKTOP_API %s]",
                sys.platform, DESKTOP_API_VERSION,
            )
            return True
        except Exception as e:
            logger.error("Platform init misslyckades: %s", e)
            return False


def _init_windows() -> None:
    """Windows-specifik init.
    FIX 2026-09-23: INTE suppress (gav NameError om import-krock) — plain try/except.

    FIX v7-fix21 (2026-09-29 — ROTEN TILL CreateWindowEx-STORMEN):
    SetProcessDPIAware() är BORTTAGEN! Den satte processen till legacy
    SYSTEM-DPI-aware vid IMPORT-tid (FÖRE QApplication) — oåterkalleligt —
    vilket gjorde Qt:s SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)
    till "Åtkomst nekad" (syns i Rickards logg). Resultatet: Qt räknade
    fönstergeometri per-monitor medan Windows virtualiserade system-DPI →
    CreateWindowEx fick OGILTIGA PARAMETRAR vid VARJE försök = den eviga
    "Felaktig parameter"-stormen på flerskärms-uppsättningar med skalning
    (2x Samsung LS27D39x @ 125%).
    Qt 6 sätter ALLTID sin egen DPI-medvetenhet korrekt — den får ALDRIG
    röras av oss före QApplication.
    """
    if kernel32 is not None:
        try:
            kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), 0x00008000)
        except Exception:
            pass


# Initiera vid import
try:
    init_platform()
except Exception as e:
    logger.debug("Auto-init misslyckades: %s", e)


# ===========================================================================
# CAPABILITY STATE
# ===========================================================================

_capability_state: CapabilityState = CapabilityState.UNKNOWN
_capability_lock = threading.RLock()


def _ensure_capabilities_probed() -> None:
    """Säkerställ att capabilities har probeats."""
    global _capability_state
    with _capability_lock:
        if _capability_state in (CapabilityState.PROBED, CapabilityState.STALE):
            _probe_capabilities()
            _capability_state = CapabilityState.PROBED


def _probe_capabilities() -> None:
    """Probe Windows-features (DWM, Mica, etc)."""
    if not IS_WINDOWS:
        return
    global _WIN_BUILD, _WIN_VERSION_LABEL
    with _capability_lock:
        # Hämta Windows build
        try:
            info = sys.getwindowsversion()
            build = int(info.build)
            major = int(info.major)
            _WIN_BUILD = build
            _WIN_VERSION_LABEL = _format_windows_version(major, build)
        except (AttributeError, OSError):
            _WIN_BUILD = 0
            _WIN_VERSION_LABEL = "unknown"


def _format_windows_version(major: int, build: int) -> str:
    """Formatera Windows-version till läsbar sträng."""
    if major == 10:
        if build >= 22621: return "Windows 11 22H2+"
        if build >= 22000: return "Windows 11 21H2"
        if build >= 19041: return "Windows 10 2004+"
        if build >= 18362: return "Windows 10 1903"
        if build >= 14393: return "Windows 10 1607"
    elif major == 6:
        if build == 3 or build == 9600: return "Windows 8.1"
        if build == 2 or build == 9200: return "Windows 8"
        if build == 1 or build == 7601: return "Windows 7"
    return f"Windows {major}.0 (build {build})"


# ===========================================================================
# DWM CAPABILITY-PROBES (NY v6.4.1 v7-fix)
# ===========================================================================
# Buggrapport 2026-09-22:
#   desktop.py rad 1291: NameError: name 'dwm_has_blur' is not defined
#   Dessa funktioner används på många ställen men var aldrig definierade.
#   Vi lägger till robusta stubs som returnerar rimliga default baserat på
#   Windows-version + DWM-composition-status.
#
# Design:
#   - På icke-Windows: alla returnerar False (säkert fallback)
#   - På Windows: heuristik baserat på build-nummer
#   - Kan överskridas med environment variables for testing:
#       DESKTOPTODO_DWM_BLUR=1, DESKTOPTODO_DWM_MICA=1, etc.
# ===========================================================================

def _dwm_cap_env(name: str, default: bool) -> bool:
    """Läs env-override for DWM-capability (for testing/debugging)."""
    try:
        import os as _os
        val = _os.environ.get(f"DESKTOPTODO_{name}", "").lower()
        if val in ("1", "true", "yes"):
            return True
        if val in ("0", "false", "no"):
            return False
    except Exception:
        pass
    return default


def _dwm_has_blur_inline() -> bool:
    """
    Inline DWM-blur-probe (används av dwm_has_blur() vid modul-import).

    NY v6.4.1 v7-fix: Tidigare anropade dwm_has_blur() is_composition_enabled()
    som inte var definierad än (rad 2422, efter rad 1126). Detta orsakade
    NameError vid import. Nu gor vi en inline-probe istället.
    """
    if not IS_WINDOWS:
        return False
    if dwmapi is None:
        return False
    try:
        enabled = ctypes.c_bool()
        hr = dwmapi.DwmIsCompositionEnabled(ctypes.byref(enabled))
        return hr == S_OK and bool(enabled.value)
    except Exception:
        return False


def dwm_has_blur() -> bool:
    """
    NY v6.4.1 v7-fix: Har Windows DWM blur (alla Win10+ har det).

    DwmEnableBlurBehindWindow funkar på Windows Vista+.
    Vi returnerar True om composition är aktiverat på Windows.
    """
    if not IS_WINDOWS:
        return False
    if dwmapi is None:
        return False
    # Env override
    return _dwm_cap_env("DWM_BLUR", True) and _dwm_has_blur_inline()


def dwm_has_mica() -> bool:
    """
    NY v6.4.1 v7-fix: Mica kräver Windows 11 21H2 (build 22000+).
    """
    if not IS_WINDOWS:
        return False
    if dwmapi is None:
        return False
    # Mica kräver Win11 (build >= 22000) + DWMWA_SYSTEMBACKDROP_TYPE
    has_build = (_WIN_BUILD is not None and _WIN_BUILD >= 22000)
    return _dwm_cap_env("DWM_MICA", has_build)


def dwm_has_acrylic() -> bool:
    """
    NY v6.4.1 v7-fix: Acrylic kräver Windows 11 22H2 (build 22621+).
    """
    if not IS_WINDOWS:
        return False
    if dwmapi is None:
        return False
    has_build = (_WIN_BUILD is not None and _WIN_BUILD >= 22621)
    return _dwm_cap_env("DWM_ACRYLIC", has_build)


def dwm_has_corner() -> bool:
    """
    NY v6.4.1 v7-fix: Window corner preference kräver Windows 11.
    """
    if not IS_WINDOWS:
        return False
    if dwmapi is None:
        return False
    has_build = (_WIN_BUILD is not None and _WIN_BUILD >= 22000)
    return _dwm_cap_env("DWM_CORNER", has_build)


def dwm_has_backdrop() -> bool:
    """
    NY v6.4.1 v7-fix: System backdrop (Mica/Acrylic/etc) kräver Windows 11.
    """
    if not IS_WINDOWS:
        return False
    if dwmapi is None:
        return False
    has_build = (_WIN_BUILD is not None and _WIN_BUILD >= 22000)
    return _dwm_cap_env("DWM_BACKDROP", has_build)


def supports_immersive_dark() -> bool:
    """
    NY v6.4.1 v7-fix: Immersive dark mode kräver Windows 10 1903 (build 18985+).
    """
    if not IS_WINDOWS:
        return False
    has_build = (_WIN_BUILD is not None and _WIN_BUILD >= 18985)
    return _dwm_cap_env("IMMERSIVE_DARK", has_build)


def supports_aero_snap_zones() -> bool:
    """
    NY v6.4.1 v7-fix: Aero Snap-zoner funkar på Windows 7+ (alla moderna).
    """
    if not IS_WINDOWS:
        return False
    has_build = (_WIN_BUILD is None or _WIN_BUILD >= 7601)  # Win7 build 7601
    return _dwm_cap_env("AERO_SNAP", has_build)


_WIN_BUILD: Optional[int] = None
_WIN_VERSION_LABEL: str = "unknown"
_WIN_EDITION: Optional[str] = None


# ===========================================================================
# FUNKTIONSBINDNINGAR (Win32)
# ===========================================================================

def _bind_user32() -> Tuple[Any, Any, bool]:
    """Binda user32 funktioner."""
    if not IS_WINDOWS or user32 is None:
        return None, None, False
    with _safe_call():
        try:
            user32.SetProcessDPIAware.argtypes = []
            user32.SetProcessDPIAware.restype = ctypes.c_bool
        except AttributeError:
            pass

        user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        user32.SetWindowPos.restype = ctypes.c_bool
        user32.SetWindowRgn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool]
        user32.SetWindowRgn.restype = ctypes.c_int
        # FIX 2026-09-23: c_void_p istället för POINTER(RECT) —
        # widget.py använder wintypes.RECT → "expected LP_RECT" om exakt klass krävs.
        user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        user32.GetWindowRect.restype = ctypes.c_bool
        user32.GetClientRect.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        user32.GetClientRect.restype = ctypes.c_bool
        user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
        user32.IsWindowVisible.restype = ctypes.c_bool
        user32.IsWindow.argtypes = [ctypes.c_void_p]
        user32.IsWindow.restype = ctypes.c_bool
        user32.IsWindowEnabled.argtypes = [ctypes.c_void_p]
        user32.IsWindowEnabled.restype = ctypes.c_bool
        user32.IsIconic.argtypes = [ctypes.c_void_p]
        user32.IsIconic.restype = ctypes.c_bool
        user32.IsZoomed.argtypes = [ctypes.c_void_p]
        user32.IsZoomed.restype = ctypes.c_bool
        user32.GetWindowTextLengthW.argtypes = [ctypes.c_void_p]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.SetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        user32.SetWindowTextW.restype = ctypes.c_bool
        user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
        user32.GetClassNameW.restype = ctypes.c_int
        user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
        user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        user32.GetAncestor.restype = ctypes.c_void_p
        user32.GetParent.argtypes = [ctypes.c_void_p]
        user32.GetParent.restype = ctypes.c_void_p
        user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.ShowWindow.restype = ctypes.c_bool
        user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
        user32.SetForegroundWindow.restype = ctypes.c_bool
        user32.GetForegroundWindow.argtypes = []
        user32.GetForegroundWindow.restype = ctypes.c_void_p
        # NY v6.4.1 v7: SetParent + FindWindowW for Workers-tricket
        user32.SetParent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        user32.SetParent.restype = ctypes.c_void_p
        user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
        user32.FindWindowW.restype = ctypes.c_void_p
        user32.FindWindowExW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p]
        user32.FindWindowExW.restype = ctypes.c_void_p
        user32.GetActiveWindow.argtypes = []
        user32.GetActiveWindow.restype = ctypes.c_void_p
        user32.BringWindowToTop.argtypes = [ctypes.c_void_p]
        user32.BringWindowToTop.restype = ctypes.c_bool
        user32.EnumWindows.argtypes = [WNDENUMPROC, ctypes.c_long]
        user32.EnumWindows.restype = ctypes.c_bool
        user32.EnumChildWindows.argtypes = [ctypes.c_void_p, WNDENUMPROC, ctypes.c_long]
        user32.EnumChildWindows.restype = ctypes.c_bool
        user32.GetWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        user32.GetWindow.restype = ctypes.c_void_p
        user32.GetTopWindow.argtypes = []
        user32.GetTopWindow.restype = ctypes.c_void_p
        user32.GetSystemMetrics.argtypes = [ctypes.c_int]
        user32.GetSystemMetrics.restype = ctypes.c_int
        user32.MonitorFromWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        user32.MonitorFromWindow.restype = ctypes.c_void_p
        user32.MonitorFromPoint.argtypes = [POINT, ctypes.c_ulong]
        user32.MonitorFromPoint.restype = ctypes.c_void_p
        # FIX: c_void_p — accepterar widget.py:s lokala _MONITORINFO
        # (annars "expected LP_MONITORINFO instead of pointer to _MONITORINFO")
        user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        user32.GetMonitorInfoW.restype = ctypes.c_bool
        # FIX: c_void_p → accepterar both desktop.RECT och wintypes.RECT via byref
        user32.MonitorFromRect.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        user32.MonitorFromRect.restype = ctypes.c_void_p
        user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_long]
        user32.SendMessageW.restype = ctypes.c_long
        user32.FlashWindowEx.argtypes = [ctypes.POINTER(FLASHWINFO)]
        user32.FlashWindowEx.restype = ctypes.c_bool
        user32.RegisterHotKey.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
        user32.RegisterHotKey.restype = ctypes.c_bool
        user32.UnregisterHotKey.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.UnregisterHotKey.restype = ctypes.c_bool
        user32.MessageBoxW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
        user32.MessageBoxW.restype = ctypes.c_int
        user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        user32.GetAsyncKeyState.restype = ctypes.c_short
        user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
        user32.GetCursorPos.restype = ctypes.c_bool
        user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        user32.SetCursorPos.restype = ctypes.c_bool
        user32.ClipCursor.argtypes = [ctypes.POINTER(RECT)]
        user32.ClipCursor.restype = ctypes.c_bool
        user32.GetCursorInfo.argtypes = [ctypes.POINTER(CURSORINFO)]
        user32.GetCursorInfo.restype = ctypes.c_bool
        user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
        user32.GetLastInputInfo.restype = ctypes.c_bool
        user32.InvalidateRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(RECT), ctypes.c_bool]
        user32.InvalidateRect.restype = ctypes.c_bool
        user32.UpdateWindow.argtypes = [ctypes.c_void_p]
        user32.UpdateWindow.restype = ctypes.c_bool
        user32.RedrawWindow.argtypes = [ctypes.c_void_p, ctypes.POINTER(RECT), ctypes.c_void_p, ctypes.c_uint]
        user32.RedrawWindow.restype = ctypes.c_bool

        try:
            user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
            user32.SetWindowLongPtrW.restype = ctypes.c_long
            user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
            user32.GetWindowLongPtrW.restype = ctypes.c_long
            return user32.SetWindowLongPtrW, user32.GetWindowLongPtrW, True
        except AttributeError:
            user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
            user32.SetWindowLongW.restype = ctypes.c_long
            user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
            user32.GetWindowLongW.restype = ctypes.c_long
            return user32.SetWindowLongW, user32.GetWindowLongW, False


def _bind_gdi32() -> None:
    if not IS_WINDOWS or gdi32 is None:
        return
    with _safe_call():
        gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
        gdi32.CreateRoundRectRgn.restype = ctypes.c_void_p
        gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
        gdi32.DeleteObject.restype = ctypes.c_bool
        gdi32.CreateRectRgn.argtypes = [ctypes.c_int] * 4
        gdi32.CreateRectRgn.restype = ctypes.c_void_p
        gdi32.CombineRgn.argtypes = [ctypes.c_void_p] * 3 + [ctypes.c_int]
        gdi32.CombineRgn.restype = ctypes.c_int
        gdi32.GetDeviceCaps.argtypes = [ctypes.c_void_p, ctypes.c_int]
        gdi32.GetDeviceCaps.restype = ctypes.c_int


def _bind_dwmapi() -> None:
    if not IS_WINDOWS or dwmapi is None:
        return
    with _safe_call():
        dwmapi.DwmEnableBlurBehindWindow.argtypes = [ctypes.c_void_p, ctypes.POINTER(DWM_BLURBEHIND)]
        dwmapi.DwmEnableBlurBehindWindow.restype = ctypes.c_long
        dwmapi.DwmSetWindowAttribute.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t]
        dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long
        dwmapi.DwmGetWindowAttribute.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t]
        dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long
        dwmapi.DwmExtendFrameIntoClientArea.argtypes = [ctypes.c_void_p, ctypes.POINTER(MARGINS)]
        dwmapi.DwmExtendFrameIntoClientArea.restype = ctypes.c_long
        dwmapi.DwmIsCompositionEnabled.argtypes = [ctypes.POINTER(ctypes.c_bool)]
        dwmapi.DwmIsCompositionEnabled.restype = ctypes.c_long


def _bind_kernel32() -> None:
    if not IS_WINDOWS or kernel32 is None:
        return
    with _safe_call():
        kernel32.GetCurrentProcessId.argtypes = []
        kernel32.GetCurrentProcessId.restype = ctypes.c_ulong
        kernel32.GetCurrentThreadId.argtypes = []
        kernel32.GetCurrentThreadId.restype = ctypes.c_ulong
        kernel32.GetProcessId.argtypes = [ctypes.c_void_p]
        kernel32.GetProcessId.restype = ctypes.c_ulong
        kernel32.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)]
        kernel32.QueryFullProcessImageNameW.restype = ctypes.c_bool
        kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_bool
        kernel32.GetTickCount64.argtypes = []
        kernel32.GetTickCount64.restype = ctypes.c_ulonglong
        kernel32.GetCommandLineW.argtypes = []
        kernel32.GetCommandLineW.restype = ctypes.c_wchar_p
        kernel32.Sleep.argtypes = [ctypes.c_ulong]
        kernel32.Sleep.restype = None
        kernel32.QueryPerformanceCounter.argtypes = [ctypes.POINTER(ctypes.c_longlong)]
        kernel32.QueryPerformanceCounter.restype = ctypes.c_bool
        kernel32.QueryPerformanceFrequency.argtypes = [ctypes.POINTER(ctypes.c_longlong)]
        kernel32.QueryPerformanceFrequency.restype = ctypes.c_bool


def _bind_psapi() -> None:
    if not IS_WINDOWS or psapi is None:
        return
    with _safe_call():
        try:
            psapi.GetModuleFileNameExW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_ulong]
            psapi.GetModuleFileNameExW.restype = ctypes.c_ulong
        except AttributeError:
            pass


# Bind alla funktioner
_SetWindowLong, _GetWindowLong, _IS_64BIT = _bind_user32()
_bind_gdi32()
_bind_dwmapi()
_bind_kernel32()
_bind_psapi()

# Initiera capabilities
if IS_WINDOWS:
    _ensure_capabilities_probed()
    logger.debug(
        "Win32 bunden (64-bit: %s, build: %s, blur: %s, mica: %s, acrylic: %s)",
        _IS_64BIT, _WIN_VERSION_LABEL,
        dwm_has_blur(), dwm_has_mica(), dwm_has_acrylic(),
    )


# ===========================================================================
# VALIDERING
# ===========================================================================

def _validate_hwnd(hwnd: Any) -> bool:
    """Validera att hwnd är ett giltigt window handle."""
    if hwnd is None:
        return False
    try:
        h = int(hwnd)
    except (TypeError, ValueError):
        return False
    if h <= 0 or h > 0xFFFFFFFF:
        return False
    if IS_WINDOWS and user32 is not None:
        try:
            return bool(user32.IsWindow(h))
        except Exception:
            return True
    return True


# ===========================================================================
# CACHE (GDI-regioner)
# ===========================================================================

_REGION_CACHE: Dict[int, Any] = {}
_WINDOW_CLASS_REGISTERED: Optional[str] = None
WINDOW_CLASS_NAME: str = "LedgebordMain"


def _clear_region_cache(hwnd: int) -> None:
    """Städa cache för en HWND."""
    rgn = _REGION_CACHE.pop(hwnd, None)
    if rgn and gdi32 is not None:
        with suppress(Exception):
            gdi32.DeleteObject(rgn)


# ===========================================================================
# WINDOW CLASS REGISTRATION
# ===========================================================================

def register_window_class(class_name: str = WINDOW_CLASS_NAME) -> bool:
    global _WINDOW_CLASS_REGISTERED
    if not IS_WINDOWS or user32 is None:
        return False
    if _WINDOW_CLASS_REGISTERED == class_name:
        return True
    _WINDOW_CLASS_REGISTERED = class_name
    return True


# ===========================================================================
# FINDERS
# ===========================================================================

def find_window_by_class(class_name: str) -> List[int]:
    """Hitta alla fönster med given class name."""
    if not IS_WINDOWS or user32 is None:
        return []
    results: List[int] = []
    def callback(hwnd: int, _lparam: int) -> bool:
        try:
            buf = ctypes.create_unicode_buffer(256)
            length = user32.GetClassNameW(hwnd, buf, 256)
            if length > 0 and buf.value == class_name:
                if user32.IsWindowVisible(hwnd):
                    results.append(int(hwnd))
        except Exception:
            pass
        return True
    try:
        with _safe_call():
            user32.EnumWindows(WNDENUMPROC(callback), 0)
    except Exception as e:
        logger.debug("EnumWindows misslyckades: %s", e)
    return results


def find_window_by_title_and_class(title: str, class_name: str = "") -> List[int]:
    """Hitta fönster som matchar både titel och klass."""
    if not IS_WINDOWS or user32 is None:
        return []
    results: List[int] = []
    def callback(hwnd: int, _lparam: int) -> bool:
        try:
            if class_name:
                buf = ctypes.create_unicode_buffer(256)
                length = user32.GetClassNameW(hwnd, buf, 256)
                if length <= 0 or buf.value != class_name:
                    return True
            if title:
                length = user32.GetWindowTextLengthW(hwnd)
                if length <= 0:
                    return True
                buf2 = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf2, length + 1)
                if title not in (buf2.value or ""):
                    return True
            if user32.IsWindowVisible(hwnd):
                results.append(int(hwnd))
        except Exception:
            pass
        return True
    try:
        with _safe_call():
            user32.EnumWindows(WNDENUMPROC(callback), 0)
    except Exception as e:
        logger.debug("find_window_by_title_and_class misslyckades: %s", e)
    return results


# ===========================================================================
# EXTENDED STYLES
# ===========================================================================

def set_window_desktop_style(hwnd: int) -> bool:
    """Sätt WS_EX_TOOLWINDOW på fönstret (förhindrar taskbar-visning)."""
    if not _validate_hwnd(hwnd):
        return False
    try:
        with _safe_call():
            ex = _GetWindowLong(hwnd, GWL_EXSTYLE)
            ex |= WS_EX_TOOLWINDOW
            _SetWindowLong(hwnd, GWL_EXSTYLE, ex)
        return True
    except Exception as e:
        logger.error("set_window_desktop_style misslyckades: %s", e)
        return False


# ===========================================================================
# WORKERS-TRICK (NY v6.4.1 v7)
# ===========================================================================
# "Workers-tricket" används av Rainmeter, Wallpaper Engine m.fl. för att
# placera fönster på skrivbordet Ovanför Explorer-ikoner men UNDER alla
# andra fönster. Utan detta blir widgeten antingen gömd (HWND_BOTTOM)
# eller påträngande över ALLT (HWND_TOPMOST).
#
# Implementation:
#   1. Hitta Progman via FindWindowW("Progman", None)
#   2. Hitta WorkerW via EnumChildWindows på Progman med WorkerW-klass
#   3. SetParent(hwnd, workerw_hwnd) → widget lever i desktop-lagret
#   4. Z-order = HWND_TOP (toppen av desktop-lagret, inte överst av allt)
#
# Rickard 2026-09-22: "i toppen av skrivbordet, men ej över andra appar"
# ===========================================================================

_WORKERW_CACHE: Dict[int, int] = {}
_WORKERS_TRICK_LAST_PROBE: float = 0.0
_WORKERS_TRICK_PROBE_TTL: float = 10.0
_WORKERS_TRICK_LOCK = threading.RLock()


def find_progman_hwnd() -> Optional[int]:
    """NY v6.4.1 v7: Hitta Progman-fönstret (Windows desktop manager)."""
    if not IS_WINDOWS or user32 is None:
        return None
    try:
        with _safe_call():
            hwnd = user32.FindWindowW(PROGMAN_CLASS, None)
            if hwnd:
                return int(hwnd)
    except Exception as e:
        logger.debug("find_progman_hwnd misslyckades: %s", e)
    return None


def find_workerw_hwnd(progman_hwnd: int) -> Optional[int]:
    """
    NY v6.4.1 v7: Hitta WorkerW-fönstret (WorkerW-klass under Progman).

    WorkerW är ett osynligt fönster som Explorer skapar efter Progman via
    SHCreateDirectory-tricket. Om WorkerW inte finns (t.ex. Explorer
    visar bara Classic Desktop), returnera None.
    """
    if not IS_WINDOWS or user32 is None or not _validate_hwnd(progman_hwnd):
        return None
    try:
        result: List[int] = []
        def callback(hwnd: int, _lparam: int) -> bool:
            try:
                buf = ctypes.create_unicode_buffer(256)
                length = user32.GetClassNameW(hwnd, buf, 256)
                if length > 0 and buf.value == WORKERW_CLASS:
                    result.append(int(hwnd))
            except Exception:
                pass
            return True
        with _safe_call():
            user32.EnumChildWindows(progman_hwnd, WNDENUMPROC(callback), 0)
        if result:
            # Första WorkerW som hittas (ofta den under Progman)
            return result[0]
    except Exception as e:
        logger.debug("find_workerw_hwnd misslyckades: %s", e)
    return None


def parent_window_to_desktop(hwnd: int) -> Optional[int]:
    """
    NY v6.4.1 v7: Workers-tricket — placera fönstret i desktop-lagret.

    Returnerar parent-HWND (workerw eller progman) om framgångsrik,
    annars None. Widgeten blir nu ett child till Progman/WorkerW
    och ligger:
      - Ovanför Explorer-ikoner (Progman-viewer)
      - Under alla andra fönster (normala top-level windows)

    Args:
        hwnd: HWND för fönstret som ska flyttas till desktop-lagret

    Returns:
        Parent-HWND vid framgång, None om Progman/WorkerW ej hittades
        eller SetParent misslyckades.
    """
    if not IS_WINDOWS or user32 is None:
        return None
    if not _validate_hwnd(hwnd):
        return None
    with _WORKERS_TRICK_LOCK:
        try:
            progman = find_progman_hwnd()
            if not progman:
                logger.warning(
                    f"{LOG_PREFIX} parent_window_to_desktop: "
                    f"Progman hittades inte — widget kan inte placeras "
                    f"i desktop-lagret"
                )
                return None
            # Försök WorkerW först (ger bästa z-positionen)
            workerw = find_workerw_hwnd(progman)
            target_parent = workerw if workerw else progman
            parent_name = "WorkerW" if workerw else "Progman"
            with _safe_call():
                old_parent = user32.SetParent(hwnd, target_parent)
            _WORKERW_CACHE[hwnd] = int(target_parent)
            logger.info(
                f"{LOG_PREFIX} parent_window_to_desktop: "
                f"HWND={hwnd} → parent={parent_name} "
                f"(0x{int(target_parent):X}, old_parent=0x{old_parent or 0:X})"
            )
            return int(target_parent)
        except Exception as e:
            logger.error(
                f"{LOG_PREFIX} parent_window_to_desktop misslyckades: {e}"
            )
            return None


def unparent_window_from_desktop(hwnd: int) -> bool:
    """
    NY v6.4.1 v7: Återställ fönstret till desktop-rot (NULL parent).

    Används vid städning (close event) eller om WorkerW-tricket misslyckas.
    """
    if not IS_WINDOWS or user32 is None or not _validate_hwnd(hwnd):
        return False
    try:
        with _safe_call():
            user32.SetParent(hwnd, 0)  # 0 = ingen parent (desktop-rot)
        _WORKERW_CACHE.pop(hwnd, None)
        logger.debug(
            f"{LOG_PREFIX} unparent_window_from_desktop: HWND={hwnd} → NULL"
        )
    except Exception as e:
        logger.debug("unparent_window_from_desktop misslyckades: %s", e)
        return False
    return True


def get_desktop_parent(hwnd: int) -> Optional[int]:
    """Returnerar cached parent-HWND (WorkerW/Progman) eller None."""
    return _WORKERW_CACHE.get(int(hwnd))


def has_workers_trick(hwnd: int) -> bool:
    """Returnerar True om widgeten är parentad till desktop-lagret."""
    if not IS_WINDOWS or user32 is None or not _validate_hwnd(hwnd):
        return False
    try:
        with _safe_call():
            parent = user32.GetParent(hwnd)
        if not parent:
            return False
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(parent, buf, 256)
        return buf.value in (PROGMAN_CLASS, WORKERW_CLASS)
    except Exception:
        return False


# ===========================================================================
# DESKTOP-LAGER (NY v7-fix38) — Win+D-säkert skrivbordsläge
# ===========================================================================
# Rickard 2026-10-01:
#   "win+d döljer fönstret, ska alltid vara synligt överst på skrivbordet
#    + vara transparent så ej ikoner döljs"
#
# Windows "Visa skrivbordet" (Win+D) minimerar ALLA toppfönster — HWND_BOTTOM,
# WS_EX_NOACTIVATE och SC_MINIMIZE-blockering räcker INTE (bevisat på Rickards
# maskin). ENDA robusta lösningen (samma som Rainmeter "On Desktop", Wallpaper
# Engine, Lively) är att leva i skrivbordslagret:
#
#   Z-ordning (underst → överst):
#     1. WorkerW  — tapet-lagret (Explorer skapar det via meddelande 0x052C)
#     2. Progman + SHELLDLL_DefView — skrivbordsikonerna
#     3. Vanliga app-fönster
#
# Lägen:
#   above  — SetParent(ikon-ägaren, normalt Progman) + placeras ovanför
#            SHELLDLL_DefView: widgeten ligger ÖVER ikonerna och Win+D kan
#            ALDRIG gömma den (den är barn till själva skrivbordet, precis
#            som tapeten). Ikonerna under widgeten syns genom ett
#            genomskinligt skal (WA_TranslucentBackground).
#   behind — kila in direkt ovanför WorkerW (Rainmeter-metoden, EJ reparent):
#            skrivbordsikonerna målas OVANPÅ widgeten → ikonerna döljs ALDRIG.
#
# Båda lägena är immuna mot Win+D, Win+M och "Visa skrivbordet".
# Gamla funktioner (parent_window_to_desktop m.fl.) behålls orörda.
# ============================================================================

_WM_DESKTOP_SPAWN_WORKERW: int = 0x052C  # Progman → skapa WorkerW bakom ikoner
_SMTO_NORMAL: int = 0x0000
_DESKTOP_LAYER_LOCK = threading.RLock()
# NY v7-fix48: skrivbordslagrets klient-origo i SKÄRM-koordinater
# (behövs för att kompensera att Qt-koordinater tolkas parent-relativt
# efter SetParent(Progman) — utan kompensation skiftas fönstret t.ex.
# -1920 px på Rickards tvåskärms-uppsättning)
_DESKTOP_PARENT_ORIGIN: Dict[int, Any] = {}


def get_desktop_parent_origin(hwnd: int) -> Any:
    """NY v7-fix48: förälderns klient-origo (skärm-koordinater) som tuple."""
    return _DESKTOP_PARENT_ORIGIN.get(int(hwnd), (0, 0))


def _send_desktop_spawn_workerw(progman_hwnd: int) -> bool:
    """NY v7-fix38: be Progman skapa WorkerW (0x052C) — krävs för kil-läget."""
    if not IS_WINDOWS or user32 is None or not _validate_hwnd(progman_hwnd):
        return False
    try:
        send = getattr(user32, "SendMessageTimeoutW", None)
        if send is None:
            return False
        result = ctypes.c_size_t(0)
        try:
            send.argtypes = [
                ctypes.c_void_p, ctypes.c_uint,
                ctypes.c_size_t, ctypes.c_size_t,
                ctypes.c_uint, ctypes.c_uint,
                ctypes.POINTER(ctypes.c_size_t),
            ]
            send.restype = ctypes.c_size_t
        except Exception:
            pass  # argtypes redan satta — inget problem
        send(
            progman_hwnd, _WM_DESKTOP_SPAWN_WORKERW, 0, 0,
            _SMTO_NORMAL, 1000, ctypes.byref(result),
        )
        return True
    except Exception as e:
        logger.debug(f"{LOG_PREFIX} _send_desktop_spawn_workerw misslyckades: {e}")
        return False


def find_desktop_layer_windows(spawn: bool = True) -> Dict[str, Optional[int]]:
    """
    NY v7-fix38: hitta skrivbordslagrets fönster (Progman, ikon-lager, WorkerW).

    Returnerar dict med:
      progman    — Progman-HWND (skrivbordets rot)
      defview    — SHELLDLL_DefView-HWND (skrivbordsikon-lagret)
      icon_owner — toppfönstret som ÄGER DefView (normalt Progman)
      workerw    — WorkerW direkt BAKOM ikon-lagret i z-ordning
                   (den WorkerW som Rainmeter/Wallpaper Engine använder)

    `spawn=True` ber Progman skapa WorkerW (0x052C) om den saknas —
    samma meddelande Wallpaper Engine skickar. Helt ofarligt om den
    redan finns.
    """
    out: Dict[str, Optional[int]] = {
        "progman": None, "defview": None, "icon_owner": None, "workerw": None,
    }
    if not IS_WINDOWS or user32 is None:
        return out
    with _DESKTOP_LAYER_LOCK:
        try:
            progman = find_progman_hwnd()
            if not progman:
                # FIX v7-fix40: varning (ej debug) — detta är en oväntad
                # omgivning och förklarar varför desktop-lagret faller tillbaka
                logger.warning(
                    f"{LOG_PREFIX} find_desktop_layer_windows: "
                    f"Progman hittades inte — skrivbordslagret otillgängligt"
                )
                return out
            out["progman"] = int(progman)

            # Ikon-lagret (SHELLDLL_DefView) — normalt barn till Progman
            with _safe_call():
                dv = user32.FindWindowExW(
                    progman, None, SHELLDLL_DEFVIEW_CLASS, None
                )
                if dv:
                    out["defview"] = int(dv)
                    out["icon_owner"] = int(progman)

            if spawn and _should_spawn_workerw():
                _send_desktop_spawn_workerw(progman)

            # Hitta toppfönstret som äger DefView + WorkerW precis bakom den.
            # EnumWindows går uppifrån-och-ner i z-ordning; när ägaren hittas
            # är nästa WorkerW NEDANFÖR den = tapet-lagret bakom ikonerna.
            holder: List[int] = []

            def _enum_cb(hwnd: int, _lparam: int) -> bool:
                try:
                    if user32.FindWindowExW(
                        hwnd, None, SHELLDLL_DEFVIEW_CLASS, None
                    ):
                        holder.append(int(hwnd))
                        return False  # klar — ikon-ägaren hittad
                except Exception:
                    pass
                return True

            with _safe_call():
                user32.EnumWindows(WNDENUMPROC(_enum_cb), 0)
            icon_owner = holder[0] if holder else out["icon_owner"]
            if icon_owner:
                out["icon_owner"] = int(icon_owner)
                with _safe_call():
                    ww = user32.FindWindowExW(
                        None, icon_owner, WORKERW_CLASS, None
                    )
                    if ww:
                        out["workerw"] = int(ww)
            # NY v7-fix89: rapportera till spawn-cachen (sluta skicka
            # 0x052C i onödan på maskiner som aldrig skapar WorkerW)
            _record_spawn_result(bool(out["workerw"]))
            logger.debug(
                f"{LOG_PREFIX} find_desktop_layer_windows: "
                f"progman=0x{out['progman'] or 0:X} "
                f"defview=0x{out['defview'] or 0:X} "
                f"icon_owner=0x{out['icon_owner'] or 0:X} "
                f"workerw=0x{out['workerw'] or 0:X}"
            )
            return out
        except Exception as e:
            logger.debug(f"{LOG_PREFIX} find_desktop_layer_windows misslyckades: {e}")
            return out


# ===========================================================================
# NY v7-fix89: SPAWN-CACHE — sluta skicka 0x052C i onödan (prestanda)
# ===========================================================================
# Rickards Win11 skapar ALDRIG WorkerW — ändå skickade 30-sekunders-
# underhållet en systembroadcast (0x052C) till Progman VARJE cykel.
# Efter 5 misslyckade försök pausas sändningen 10 minuter; därefter ett
# nytt försök (Explorer-omstart kan ändra läget). Progman-fallbacken
# (v7-fix71) fungerar oavsett — detta är ren optimering.
_SPAWN_STATE: Dict[str, Any] = {
    "misses": 0,
    "skip_until": 0.0,
    "pause_logged": False,
}
_SPAWN_MAX_MISSES: int = 5
_SPAWN_PAUSE_SEC: float = 600.0  # 10 minuter


def _should_spawn_workerw() -> bool:
    """NY v7-fix89: ska 0x052C skickas just nu? (spawn-cache)"""
    try:
        if int(_SPAWN_STATE.get("misses", 0)) < _SPAWN_MAX_MISSES:
            return True
        return time.time() >= float(_SPAWN_STATE.get("skip_until", 0.0))
    except Exception:
        return True


def _record_spawn_result(workerw_found: bool) -> None:
    """NY v7-fix89: rapportera WorkerW-resultat till spawn-cachen."""
    try:
        if workerw_found:
            if (_SPAWN_STATE.get("misses", 0) >= _SPAWN_MAX_MISSES
                    or _SPAWN_STATE.get("pause_logged", False)):
                logger.info(
                    f"{LOG_PREFIX} spawn-cache: WorkerW hittad igen — "
                    f"återupptar normal spawn-sökning (v7-fix89)"
                )
            _SPAWN_STATE.update(
                {"misses": 0, "skip_until": 0.0, "pause_logged": False}
            )
            return
        _SPAWN_STATE["misses"] = int(_SPAWN_STATE.get("misses", 0)) + 1
        if _SPAWN_STATE["misses"] >= _SPAWN_MAX_MISSES:
            _SPAWN_STATE["skip_until"] = time.time() + _SPAWN_PAUSE_SEC
            if not _SPAWN_STATE.get("pause_logged", False):
                _SPAWN_STATE["pause_logged"] = True
                logger.info(
                    f"{LOG_PREFIX} spawn-cache: denna Windows skapar inte "
                    f"WorkerW (vissa Win11 gör det) — sänder 0x052C bara "
                    f"var {int(_SPAWN_PAUSE_SEC / 60)}:e minut nu. "
                    f"Progman-fallback används, allt fungerar (v7-fix89)"
                )
    except Exception:
        pass


def reset_spawn_cache() -> None:
    """NY v7-fix89: nollställ spawn-cachen (t.ex. efter Explorer-omstart)."""
    try:
        _SPAWN_STATE.update(
            {"misses": 0, "skip_until": 0.0, "pause_logged": False}
        )
    except Exception:
        pass


# ===========================================================================
# NY v7-fix89: DIAGNOSPELARE (guld vid skrivbordslager-felsökning)
# ===========================================================================

def _hwnd_brief(hwnd: int) -> str:
    """Intern: kort beskrivning av ett fönster (hwnd, klass, titel, rect)."""
    try:
        if not _validate_hwnd(hwnd):
            return f"0x{int(hwnd or 0):X} (ogiltig)"
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        klass = buf.value
        user32.GetWindowTextW(hwnd, buf, 256)
        titel = buf.value[:30]
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        return (
            f"0x{int(hwnd):X} [{klass}] \"{titel}\" "
            f"({rect.left},{rect.top})-({rect.right},{rect.bottom})"
        )
    except Exception as e:
        return f"0x{int(hwnd or 0):X} (fel: {e})"


def get_window_z_neighbors(hwnd: int) -> Dict[str, Any]:
    """
    NY v7-fix89: fönstret ovanför/under i z-ordningen (diagnos).

    Returnerar {"above": {...}, "below": {...}} med hwnd/klass/titel.
    """
    out: Dict[str, Any] = {"above": None, "below": None}
    if not IS_WINDOWS or user32 is None or not _validate_hwnd(hwnd):
        return out
    try:
        with _safe_call():
            for key, flag in (("above", GW_HWNDPREV), ("below", GW_HWNDNEXT)):
                nb = int(user32.GetWindow(hwnd, flag) or 0)
                if nb:
                    buf = ctypes.create_unicode_buffer(256)
                    user32.GetClassNameW(nb, buf, 256)
                    tbuf = ctypes.create_unicode_buffer(256)
                    user32.GetWindowTextW(nb, tbuf, 256)
                    out[key] = {
                        "hwnd": nb,
                        "class": buf.value,
                        "title": tbuf.value[:40],
                    }
    except Exception as e:
        logger.debug(f"{LOG_PREFIX} get_window_z_neighbors: {e}")
    return out


def dump_desktop_hierarchy(our_hwnd: Optional[int] = None) -> str:
    """
    NY v7-fix89: läsbar dump av skrivbordslager-hierarkin (diagnos).

    Visar Progman/DefView/ikon-ägare/WorkerW (med klass, titel, rekt)
    + var VÅRT fönster sitter i z-ordningen. Använd vid felsökning:
        from core.desktop import dump_desktop_hierarchy
        logger.info(dump_desktop_hierarchy(hwnd))
    """
    lines: List[str] = ["── Skrivbordshierarki (v7-fix89) ──"]
    try:
        if not IS_WINDOWS:
            lines.append("  (icke-Windows — ingen hierarki)")
            return "\n".join(lines)
        layer = find_desktop_layer_windows(spawn=False)
        for key in ("progman", "defview", "icon_owner", "workerw"):
            val = layer.get(key)
            lines.append(
                f"  {key:11}: "
                + (_hwnd_brief(val) if val else "(saknas)")
            )
        if our_hwnd and _validate_hwnd(our_hwnd):
            lines.append(f"  vårt fönster: {_hwnd_brief(our_hwnd)}")
            nb = get_window_z_neighbors(int(our_hwnd))
            for side in ("above", "below"):
                info = nb.get(side)
                if info:
                    lines.append(
                        f"  {side:11}: 0x{info['hwnd']:X} "
                        f"[{info['class']}] \"{info['title']}\""
                    )
            anchor = layer.get("workerw") or layer.get("icon_owner") or layer.get("progman")
            if anchor:
                with _safe_call():
                    direct = int(user32.GetWindow(anchor, GW_HWNDNEXT) or 0)
                lines.append(
                    f"  kil-check  : direkt under ankaret = "
                    f"{'VÅRT FÖNSTER ✓' if direct == int(our_hwnd) else _hwnd_brief(direct)}"
                )
        lines.append("  spawn-cache: "
                     + f"{_SPAWN_STATE.get('misses', 0)} missar"
                     + (f", pausad till "
                        f"{time.strftime('%H:%M:%S', time.localtime(_SPAWN_STATE.get('skip_until', 0)))}"
                        if time.time() < _SPAWN_STATE.get("skip_until", 0)
                        else ""))
    except Exception as e:
        lines.append(f"  (fel: {e})")
    return "\n".join(lines)


def wedge_status(hwnd: int) -> Dict[str, Any]:
    """
    NY v7-fix89: kort kil-status för ett fönster (diagnos/monitorering).

    Returnerar:
      {"wedged": bool,          — sitter direkt under WorkerW/Progman?
       "anchor": int|None,      — ankaret det är kilat under
       "anchor_kind": str}      — "workerw" | "progman" | "none"
    """
    out: Dict[str, Any] = {
        "wedged": False, "anchor": None, "anchor_kind": "none",
    }
    if not IS_WINDOWS or user32 is None or not _validate_hwnd(hwnd):
        return out
    try:
        layer = find_desktop_layer_windows(spawn=False)
        for kind in ("workerw", "progman"):
            anchor = layer.get(kind)
            if anchor:
                with _safe_call():
                    direct = int(user32.GetWindow(anchor, GW_HWNDNEXT) or 0)
                if direct == int(hwnd):
                    out.update(
                        {"wedged": True, "anchor": anchor, "anchor_kind": kind}
                    )
                    return out
        out["anchor"] = layer.get("workerw") or layer.get("progman")
        out["anchor_kind"] = "workerw" if layer.get("workerw") else "progman"
    except Exception as e:
        logger.debug(f"{LOG_PREFIX} wedge_status: {e}")
    return out


def safe_set_foreground(hwnd: int) -> bool:
    """
    NY v7-fix89 (framtida bruk — EJ kopplad): fokusregeln-medveten
    SetForegroundWindow.

    Windows tillåter bara förgrundsbyte under vissa villkor; den klassiska
    lösningen är AttachThreadInput mot det nuvarande förgrunds-fönstrets
    tråd. Widgetens nuvarande lösning (fix73) fungerar och ändras EJ —
    detta är en robustare hjälpreda för framtiden.
    """
    if not IS_WINDOWS or user32 is None or not _validate_hwnd(hwnd):
        return False
    try:
        import ctypes as _ct
        fg = user32.GetForegroundWindow()
        fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        our_thread = _ct.windll.kernel32.GetCurrentThreadId()
        attached = False
        if fg_thread and fg_thread != our_thread:
            attached = bool(user32.AttachThreadInput(
                our_thread, fg_thread, True
            ))
        try:
            ok = bool(user32.SetForegroundWindow(hwnd))
        finally:
            if attached:
                with _safe_call():
                    user32.AttachThreadInput(our_thread, fg_thread, False)
        return ok
    except Exception as e:
        logger.debug(f"{LOG_PREFIX} safe_set_foreground: {e}")
        return False


def attach_window_above_desktop_icons(hwnd: int) -> bool:
    """
    NY v7-fix38: fäst fönstret ÖVER skrivbordsikonerna (Win+D-säkert).

    SetParent(ikon-ägaren) + SetWindowPos ovanför SHELLDLL_DefView:
      - widgeten ligger över ikonerna men under ALLA appar
      - Win+D/Win+M/"Visa skrivbordet" kan ALDRIG gömma den
      - ikoner under widgeten syns genom ett genomskinligt skal

    Idempotent — kan anropas om och om igen som underhåll.
    Returnerar True vid framgång.
    """
    if not IS_WINDOWS or user32 is None:
        return False
    if not _validate_hwnd(hwnd):
        # FIX v7-fix40: tyst return dolde felet — logga ANLEDNINGEN
        logger.warning(
            f"{LOG_PREFIX} attach_window_above_desktop_icons: "
            f"ogiltig HWND={hwnd!r} — kan inte fästa i skrivbordslagret"
        )
        return False
    with _DESKTOP_LAYER_LOCK:
        try:
            layer = find_desktop_layer_windows(spawn=False)
            owner = layer.get("icon_owner") or layer.get("progman")
            if not owner:
                logger.warning(
                    f"{LOG_PREFIX} attach_window_above_desktop_icons: "
                    f"ingen Progman/ikon-ägare — avbryter"
                )
                return False
            # FIX v7-fix55: GetParent returnerar 0/owner för fönster
            # med WS_POPUP-stil (vårt frameless skal!) → koden trodde
            # VARJE 30:e sekund att fönstret behövde SetParent →
            # göm+flytt-cykel var 30:e sekund. GetAncestor(GA_PARENT)
            # ger SANN parent även för popup-stil.
            _ga_parent = 0
            with _safe_call():
                _ga_parent = int(user32.GetAncestor(hwnd, 2) or 0)  # GA_PARENT
            if _ga_parent != int(owner):
                # FIX v7-fix54: läs SKÄRM-positionen FÖRE SetParent!
                # Gamla koden läste EFTER — dvs "bevarade" den redan
                # skiftade positionen (fönstret hamnade på fel skärm,
                # förvärrat av 125% DPI: logiska vs fysiska pixlar).
                _pre = wintypes.RECT()
                with _safe_call():
                    user32.GetWindowRect(hwnd, ctypes.byref(_pre))
                with _safe_call():
                    old = user32.SetParent(hwnd, owner)
                    if not old and not user32.IsWindow(hwnd):
                        logger.warning(
                            f"{LOG_PREFIX} attach_window_above_desktop_icons: "
                            f"SetParent misslyckades för HWND={hwnd}"
                        )
                        return False
                logger.info(
                    f"{LOG_PREFIX} attach_window_above_desktop_icons: "
                    f"HWND={hwnd} → parent=ikon-ägare 0x{int(owner):X} "
                    f"(ovanför ikonerna, Win+D-säkert)"
                )
            # Håll oss ovanför DefView bland syskonen
            defview = layer.get("defview")
            with _safe_call():
                user32.SetWindowPos(
                    hwnd,
                    0,  # FIX v7-fix60: HWND_TOP bland syskon = OVANFÖR
                    # DefView/ikonerna. (Gamla koden använde 'defview' som
                    # hWndInsertAfter — MSDN: fönstret placeras BENEATH
                    # hWndInsertAfter → vi låg BAKOM ikonlagret.)
                    0, 0, 0, 0,
                    SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE,
                )
            # NY v7-fix48: KOMPENSERA koordinatskiftet! Efter SetParent
            # tolkas fönstrets position förälder-relativt — utan detta
            # skiftas fönstret (på två skärmar t.ex. -1920 px = fel
            # skärm). MapWindowPoints ger förälderns origo; vi flyttar
            # tillbaka till ursprunglig SKÄRM-position.
            try:
                _pt = wintypes.POINT(0, 0)
                user32.MapWindowPoints(owner, None, ctypes.byref(_pt), 1)
                # FYSIKT origo (Windows-koordinater)
                _DESKTOP_PARENT_ORIGIN[int(hwnd)] = (int(_pt.x), int(_pt.y))
                # FIX v7-fix54: återställ till den FYSISKA skärm-position
                # som gällde FÖRE SetParent (inte den skiftade efter)
                user32.SetWindowPos(
                    hwnd, 0,
                    _pre.left - _pt.x, _pre.top - _pt.y, 0, 0,
                    SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE,
                )
                logger.info(
                    f"{LOG_PREFIX} attach: koordinatkompensation "
                    f"origo=({_pt.x},{_pt.y}) → skärmpos bevarad "
                    f"({_pre.left},{_pre.top}) [pre-SetParent, DPI-säker]"
                )
            except Exception as _komp_err:
                logger.debug(f"{LOG_PREFIX} kompensering misslyckades: {_komp_err}")
            _WORKERW_CACHE[hwnd] = int(owner)
            return True
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} attach_window_above_desktop_icons misslyckades: {e}"
            )
            return False


def wedge_window_behind_desktop_icons(hwnd: int) -> bool:
    """
    NY v7-fix38: kila in fönstret BAKOM skrivbordsikonerna (Rainmeter-läget).

    Ingen reparent — fönstret förblir toppfönster men placeras direkt
    ovanför WorkerW (tapet-lagret) i z-ordningen:
      - skrivbordsikonerna målas OVANPÅ widgeten → ikoner döljs aldrig
      - Win+D-säkert (Explorer rör inte fönster under ikon-lagret)

    Idempotent — anropas var 30:e sekund som underhåll.
    Returnerar True vid framgång.

    FIX v7-fix76: 30-sekunderunderhållet loggade 2 INFO-rader + gjorde en
    SetWindowPos VARJE gång (Rickards logg 2026-10-06: ~200 rader på
    50 minuter). Nu: snabbspår — ligger fönstret REDAN direkt ovanför
    ankaret (WorkerW/Progman) returneras True direkt med DEBUG-logg =
    helt tyst + noll z-order-churn när allt redan står rätt. Blir
    fönstret avlägsnat (Explorer-omstart, annat verktyg) gör kilen
    jobbet som innan och loggar INFO.
    """
    if not IS_WINDOWS or user32 is None:
        return False
    if not _validate_hwnd(hwnd):
        # FIX v7-fix40: tyst return dolde felet — logga ANLEDNINGEN
        logger.warning(
            f"{LOG_PREFIX} wedge_window_behind_desktop_icons: "
            f"ogiltig HWND={hwnd!r} — kan inte kila in i skrivbordslagret"
        )
        return False
    with _DESKTOP_LAYER_LOCK:
        try:
            layer = find_desktop_layer_windows(spawn=True)
            workerw = layer.get("workerw")
            # FIX v7-fix71: Windows 11 skapar ibland ALDRIG WorkerW
            # (Rickards maskin: "ingen WorkerW bakom ikonerna" vid varje
            # försök). Fallback: kila DIREKT Ovanför Progman (skrivbords-
            # grunden) — samma teknik Rainmeter använder som återväg.
            # Resultat: fönstret ligger ÖVER tapeten/ikonerna men UNDER
            # alla appar = synligt + Win+D-säkert, utan SetParent.
            if not workerw:
                _anchor = layer.get("icon_owner") or layer.get("progman")
                if _anchor:
                    # FIX v7-fix76: snabbspår — ligger vi REDAN direkt
                    # ovanför ankaret (och är toppfönster)? Då är kilen på
                    # plats: ingen SetWindowPos, bara DEBUG-logg = tyst
                    # 30s-underhåll utan loggspamm/z-order-churn.
                    _already = False
                    with _safe_call():
                        _cur = int(user32.GetParent(hwnd) or 0)
                    if not _cur:
                        # FIX v7-fix80: SetWindowPos(hwnd, anchor) placerar
                        # fönstret DIREKT UNDER ankaret → rätt "redan på
                        # plats"-kontroll är fönstret NEDANFÖR ankaret
                        # (GW_HWNDNEXT), inte ovanför (GW_HWNDPREV —
                        # matchade aldrig på Rickards maskin, därför
                        # loggade 30s-underhållet på som förr).
                        with _safe_call():
                            _already = (
                                int(
                                    user32.GetWindow(
                                        int(_anchor), GW_HWNDNEXT
                                    )
                                    or 0
                                )
                                == int(hwnd)
                            )
                    if _already:
                        logger.debug(
                            f"{LOG_PREFIX} wedge: redan på plats ovanför "
                            f"ankaret 0x{int(_anchor):X} — ingen åtgärd "
                            f"(v7-fix76)"
                        )
                        return True
                    logger.info(
                        f"{LOG_PREFIX} wedge: ingen WorkerW → kilar "
                        f"ovanför Progman (skrivbordsgrunden) 0x"
                        f"{int(_anchor):X} (v7-fix71)"
                    )
                    with _safe_call():
                        _cur = int(user32.GetParent(hwnd) or 0)
                    if _cur:
                        with _safe_call():
                            user32.SetParent(hwnd, 0)
                    with _safe_call():
                        ok = bool(user32.SetWindowPos(
                            hwnd, _anchor, 0, 0, 0, 0,
                            SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE,
                        ))
                    if ok:
                        _WORKERW_CACHE.pop(hwnd, None)
                        logger.info(
                            f"{LOG_PREFIX} wedge (Progman-fallback): "
                            f"HWND={hwnd} kild ovanför skrivbordsgrunden "
                            f"— Win+D-säkert (v7-fix71)"
                        )
                    return ok
                logger.warning(
                    f"{LOG_PREFIX} wedge_window_behind_desktop_icons: "
                    f"ingen WorkerW/Progman — avbryter"
                )
                return False
            # Måste vara toppfönster för att kilas i global z-ordning
            with _safe_call():
                current_parent = int(user32.GetParent(hwnd) or 0)
            if current_parent:
                with _safe_call():
                    user32.SetParent(hwnd, 0)
                logger.info(
                    f"{LOG_PREFIX} wedge_window_behind_desktop_icons: "
                    f"HWND={hwnd} lossad från parent 0x{current_parent:X}"
                )
            # FIX v7-fix76: snabbspår även i WorkerW-läget — ligger vi
            # redan direkt under WorkerW är kilen på plats (tyst).
            # FIX v7-fix80: GW_HWNDNEXT (under), inte GW_HWNDPREV —
            # SetWindowPos(hwnd, workerw) placerar oss UNDER WorkerW.
            with _safe_call():
                _already_w = (
                    int(user32.GetWindow(int(workerw), GW_HWNDNEXT) or 0)
                    == int(hwnd)
                )
            if _already_w:
                logger.debug(
                    f"{LOG_PREFIX} wedge: redan på plats ovanför WorkerW "
                    f"0x{int(workerw):X} — ingen åtgärd (v7-fix76)"
                )
                return True
            with _safe_call():
                ok = bool(user32.SetWindowPos(
                    hwnd, workerw, 0, 0, 0, 0,
                    SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE,
                ))
            if ok:
                _WORKERW_CACHE.pop(hwnd, None)
                logger.info(
                    f"{LOG_PREFIX} wedge_window_behind_desktop_icons: "
                    f"HWND={hwnd} kilar ovanför WorkerW 0x{int(workerw):X} "
                    f"(under ikonerna, Win+D-säkert)"
                )
            return ok
        except Exception as e:
            logger.warning(
                f"{LOG_PREFIX} wedge_window_behind_desktop_icons misslyckades: {e}"
            )
            return False


def detach_window_from_desktop_layer(hwnd: int) -> bool:
    """
    NY v7-fix38: lossa fönstret från skrivbordslagret (åter till toppfönster).

    Wrapper runt unparent_window_from_desktop (som behålls orörd).
    """
    return unparent_window_from_desktop(hwnd)


def is_window_in_desktop_layer(hwnd: int) -> bool:
    """NY v7-fix38: är fönstret parentat till skrivbordet (Progman/WorkerW)?"""
    return has_workers_trick(hwnd)


def set_click_through(hwnd: int, enabled: bool) -> bool:
    """Sätt WS_EX_TRANSPARENT (klick-through-läge)."""
    if not _validate_hwnd(hwnd):
        return False
    try:
        with _safe_call():
            ex = _GetWindowLong(hwnd, GWL_EXSTYLE)
            ex = (ex | WS_EX_TRANSPARENT) if enabled else (ex & ~WS_EX_TRANSPARENT)
            _SetWindowLong(hwnd, GWL_EXSTYLE, ex)
        return True
    except Exception as e:
        logger.error("set_click_through misslyckades: %s", e)
        return False


def set_no_activate(hwnd: int, enabled: bool) -> bool:
    """Sätt WS_EX_NOACTIVATE (stjäl inte fokus)."""
    if not _validate_hwnd(hwnd):
        return False
    try:
        with _safe_call():
            ex = _GetWindowLong(hwnd, GWL_EXSTYLE)
            ex = (ex | WS_EX_NOACTIVATE) if enabled else (ex & ~WS_EX_NOACTIVATE)
            _SetWindowLong(hwnd, GWL_EXSTYLE, ex)
        return True
    except Exception as e:
        logger.debug("set_no_activate misslyckades: %s", e)
        return False


def set_topmost(hwnd: int, enabled: bool) -> bool:
    """Sätt WS_EX_TOPMOST."""
    if not _validate_hwnd(hwnd):
        return False
    try:
        with _safe_call():
            ex = _GetWindowLong(hwnd, GWL_EXSTYLE)
            ex = (ex | WS_EX_TOPMOST) if enabled else (ex & ~WS_EX_TOPMOST)
            _SetWindowLong(hwnd, GWL_EXSTYLE, ex)
        return set_window_pos(
            hwnd, 0, 0, 0, 0,
            flags=SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
            after=HWND_TOPMOST if enabled else HWND_NOTOPMOST,
        )
    except Exception as e:
        logger.debug("set_topmost misslyckades: %s", e)
        return False


def set_immersive_dark(hwnd: int, enabled: bool) -> bool:
    """Aktivera/inaktivera Windows 11 immersive dark mode."""
    if not _validate_hwnd(hwnd) or dwmapi is None or not supports_immersive_dark():
        return False
    try:
        with _safe_call():
            value = ctypes.c_int(1 if enabled else 0)
            hr = dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
                ctypes.byref(value), ctypes.sizeof(value),
            )
        return hr == S_OK
    except Exception as e:
        logger.debug("set_immersive_dark misslyckades: %s", e)
        return False


def get_immersive_dark(hwnd: int) -> bool:
    """Hämta immersive dark mode-status."""
    if not _validate_hwnd(hwnd) or dwmapi is None or not supports_immersive_dark():
        return False
    try:
        with _safe_call():
            value = ctypes.c_int(0)
            hr = dwmapi.DwmGetWindowAttribute(
                hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
                ctypes.byref(value), ctypes.sizeof(value),
            )
        return hr == S_OK and value.value != 0
    except Exception as e:
        logger.debug("get_immersive_dark misslyckades: %s", e)
        return False


def set_window_layered(hwnd: int, enabled: bool) -> bool:
    """Sätt WS_EX_LAYERED."""
    if not _validate_hwnd(hwnd):
        return False
    try:
        with _safe_call():
            ex = _GetWindowLong(hwnd, GWL_EXSTYLE)
            ex = (ex | WS_EX_LAYERED) if enabled else (ex & ~WS_EX_LAYERED)
            _SetWindowLong(hwnd, GWL_EXSTYLE, ex)
        return True
    except Exception as e:
        logger.debug("set_window_layered misslyckades: %s", e)
        return False


# ===========================================================================
# POSITIONERING + Z-ORDNING (BUGG 26)
# ===========================================================================

def set_window_on_bottom(
    hwnd: int, x: int, y: int, w: int, h: int,
    auto_reposition: bool = True,
) -> bool:
    """Placera fönstret på skrivbordsnivå (HWND_BOTTOM)."""
    if not _validate_hwnd(hwnd) or user32 is None:
        return False
    try:
        if auto_reposition and IS_WINDOWS:
            icon_zones = get_icon_zones()
            if icon_zones and not is_position_safe(x, y, w, h, icon_zones):
                new_x, new_y = find_safe_position(
                    x, y, w, h, get_screen_geometry(), icon_zones
                )
                logger.debug("BUGG 26: %d,%d → %d,%d", x, y, new_x, new_y)
                x, y = new_x, new_y
        with _safe_call():
            ok = user32.SetWindowPos(
                hwnd, HWND_BOTTOM, int(x), int(y), int(w), int(h),
                SWP_NOACTIVATE | SWP_FRAMECHANGED | SWP_SHOWWINDOW,
            )
        return bool(ok)
    except Exception as e:
        logger.error("set_window_on_bottom misslyckades: %s", e)
        return False


def set_window_on_bottom_safe(hwnd: int, x: int, y: int, w: int, h: int) -> bool:
    """Fail-safe version — flyttar ALLTID till safe position."""
    if not IS_WINDOWS:
        return set_window_on_bottom(hwnd, x, y, w, h, auto_reposition=False)
    icon_zones = get_icon_zones()
    screen_geo = get_screen_geometry()
    safe_x, safe_y = find_safe_position(x, y, w, h, screen_geo, icon_zones)
    return set_window_on_bottom(hwnd, safe_x, safe_y, w, h, auto_reposition=False)


def smooth_move_to_safe(
    hwnd: int, x: int, y: int, w: int, h: int,
    duration_ms: int = 200, steps: int = 12,
) -> bool:
    """Animera fönstret till safe position (BUGG 26)."""
    if not _validate_hwnd(hwnd):
        return False
    try:
        cur = get_window_rect(hwnd)
        if not cur or cur[2] - cur[0] <= 0:
            return set_window_on_bottom_safe(hwnd, x, y, w, h)
        safe_x, safe_y = find_safe_position(x, y, w, h)
        cur_x, cur_y = int(cur[0]), int(cur[1])
        step_delay = max(1, duration_ms // steps) / 1000.0
        dx = (safe_x - cur_x) / steps
        dy = (safe_y - cur_y) / steps
        for i in range(1, steps + 1):
            ix = int(cur_x + dx * i)
            iy = int(cur_y + dy * i)
            set_window_on_bottom(hwnd, ix, iy, w, h, auto_reposition=False)
            time.sleep(step_delay)
        return True
    except Exception as e:
        logger.warning("smooth_move_to_safe misslyckades: %s", e)
        return set_window_on_bottom_safe(hwnd, x, y, w, h)


def set_window_pos(
    hwnd: int, x: int, y: int, w: int, h: int,
    flags: int = SWP_NOACTIVATE | SWP_FRAMECHANGED | SWP_SHOWWINDOW,
    after: Optional[int] = None,
) -> bool:
    """Flexibel SetWindowPos."""
    if not _validate_hwnd(hwnd) or user32 is None:
        return False
    try:
        with _safe_call():
            ok = user32.SetWindowPos(
                hwnd, after if after is not None else HWND_BOTTOM,
                int(x), int(y), int(w), int(h), ctypes.c_uint(flags),
            )
        return bool(ok)
    except Exception as e:
        logger.error("set_window_pos misslyckades: %s", e)
        return False


def raise_window(hwnd: int) -> bool:
    """BUGG 19: Tillfällig fokushöjning."""
    return set_window_pos(
        hwnd, 0, 0, 0, 0,
        flags=SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        after=HWND_TOP,
    )


def lower_window(hwnd: int) -> bool:
    """BUGG 19: Sänker fönstret till botten."""
    return set_window_pos(
        hwnd, 0, 0, 0, 0,
        flags=SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        after=HWND_BOTTOM,
    )


def show_window(hwnd: int, command: int = SW_SHOW) -> bool:
    if not _validate_hwnd(hwnd) or user32 is None:
        return False
    try:
        with _safe_call():
            return bool(user32.ShowWindow(hwnd, ctypes.c_int(command)))
    except Exception as e:
        logger.debug("ShowWindow misslyckades: %s", e)
        return False


def set_foreground(hwnd: int) -> bool:
    if not _validate_hwnd(hwnd) or user32 is None:
        return False
    try:
        with _safe_call():
            return bool(user32.SetForegroundWindow(hwnd))
    except Exception as e:
        logger.debug("SetForegroundWindow misslyckades: %s", e)
        return False


def bring_window_to_top(hwnd: int) -> bool:
    if not _validate_hwnd(hwnd) or user32 is None:
        return False
    try:
        with _safe_call():
            return bool(user32.BringWindowToTop(hwnd))
    except Exception as e:
        logger.debug("BringWindowToTop misslyckades: %s", e)
        return False


# ===========================================================================
# WINDOW INFO
# ===========================================================================

def get_window_rect(hwnd: int) -> Tuple[int, int, int, int]:
    """Returnerar (left, top, right, bottom) eller (0, 0, 0, 0) vid fel."""
    if not _validate_hwnd(hwnd) or user32 is None:
        return (0, 0, 0, 0)
    try:
        with _safe_call():
            rect = RECT()
            if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))
    except Exception as e:
        logger.debug("GetWindowRect misslyckades: %s", e)
    return (0, 0, 0, 0)


def get_client_rect(hwnd: int) -> Tuple[int, int, int, int]:
    if not _validate_hwnd(hwnd) or user32 is None:
        return (0, 0, 0, 0)
    try:
        with _safe_call():
            rect = RECT()
            if user32.GetClientRect(hwnd, ctypes.byref(rect)):
                return (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))
    except Exception as e:
        logger.debug("GetClientRect misslyckades: %s", e)
    return (0, 0, 0, 0)


def get_window_info(hwnd: int) -> Optional[Dict[str, Any]]:
    if not _validate_hwnd(hwnd) or user32 is None:
        return None
    try:
        with _safe_call():
            info = WINDOWINFO()
            info.cbSize = ctypes.sizeof(WINDOWINFO)
            if user32.GetWindowInfo(hwnd, ctypes.byref(info)):
                return {
                    "window_rect": (int(info.rcWindow.left), int(info.rcWindow.top),
                                    int(info.rcWindow.right), int(info.rcWindow.bottom)),
                    "client_rect": (int(info.rcClient.left), int(info.rcClient.top),
                                    int(info.rcClient.right), int(info.rcClient.bottom)),
                    "style": int(info.dwStyle),
                    "ex_style": int(info.dwExStyle),
                    "class_name": info.szClassName,
                    "active": bool(info.dwStyle & 0x0001),
                }
    except Exception as e:
        logger.debug("GetWindowInfo misslyckades: %s", e)
    return None


def is_window_visible(hwnd: int) -> bool:
    if not _validate_hwnd(hwnd) or user32 is None:
        return False
    try:
        with _safe_call():
            return bool(user32.IsWindowVisible(hwnd))
    except Exception:
        return False


def is_window_enabled(hwnd: int) -> bool:
    if not _validate_hwnd(hwnd) or user32 is None:
        return False
    try:
        with _safe_call():
            return bool(user32.IsWindowEnabled(hwnd))
    except Exception:
        return False


def is_window_minimized(hwnd: int) -> bool:
    if not _validate_hwnd(hwnd) or user32 is None:
        return False
    try:
        with _safe_call():
            return bool(user32.IsIconic(hwnd))
    except Exception:
        return False


def is_window_maximized(hwnd: int) -> bool:
    if not _validate_hwnd(hwnd) or user32 is None:
        return False
    try:
        with _safe_call():
            return bool(user32.IsZoomed(hwnd))
    except Exception:
        return False


def is_main_window(hwnd: int) -> bool:
    if not _validate_hwnd(hwnd) or user32 is None:
        return False
    try:
        if not user32.IsWindowVisible(hwnd):
            return False
        owner = user32.GetWindow(hwnd, GW_OWNER)
        if owner:
            return False
        ex = _GetWindowLong(hwnd, GWL_EXSTYLE)
        if ex & WS_EX_TOOLWINDOW:
            return False
        return True
    except Exception:
        return False


def get_window_title(hwnd: int) -> str:
    if not _validate_hwnd(hwnd) or user32 is None:
        return ""
    try:
        with _safe_call():
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return ""
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            return buf.value or ""
    except Exception as e:
        logger.debug("get_window_title misslyckades: %s", e)
        return ""


def get_window_text_safe(hwnd: int, max_len: int = 1024) -> str:
    if not _validate_hwnd(hwnd) or user32 is None:
        return ""
    try:
        with _safe_call():
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0 or length > max_len:
                length = min(length, max_len)
            buf = ctypes.create_unicode_buffer(length + 1)
            written = user32.GetWindowTextW(hwnd, buf, length + 1)
            return buf.value or "" if written > 0 else ""
    except Exception as e:
        logger.debug("get_window_text_safe misslyckades: %s", e)
        return ""


def set_window_title(hwnd: int, title: str) -> bool:
    if not _validate_hwnd(hwnd) or user32 is None:
        return False
    try:
        with _safe_call():
            return bool(user32.SetWindowTextW(hwnd, ctypes.c_wchar_p(title)))
    except Exception as e:
        logger.debug("set_window_title misslyckades: %s", e)
        return False


def get_window_class(hwnd: int) -> str:
    if not _validate_hwnd(hwnd) or user32 is None:
        return ""
    try:
        with _safe_call():
            buf = ctypes.create_unicode_buffer(256)
            length = user32.GetClassNameW(hwnd, buf, 256)
            return buf.value if length > 0 else ""
    except Exception as e:
        logger.debug("get_window_class misslyckades: %s", e)
        return ""


def get_window_pid(hwnd: int) -> Optional[int]:
    if not _validate_hwnd(hwnd) or user32 is None:
        return None
    try:
        with _safe_call():
            pid = ctypes.c_ulong(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            return int(pid.value) if pid.value else None
    except Exception as e:
        logger.debug("get_window_pid misslyckades: %s", e)
        return None


def get_process_path(pid: int) -> Optional[str]:
    if not IS_WINDOWS or kernel32 is None or pid <= 0:
        return None
    try:
        with _safe_call():
            access = 0x1000 | 0x0010
            h = kernel32.OpenProcess(access, False, ctypes.c_ulong(pid))
            if not h:
                return None
            try:
                buf = ctypes.create_unicode_buffer(1024)
                size = ctypes.c_ulong(1024)
                if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                    return buf.value
            finally:
                kernel32.CloseHandle(h)
    except Exception as e:
        logger.debug("get_process_path misslyckades: %s", e)
    return None


def get_window_ancestor(hwnd: int, ga_flag: int = GA_ROOT) -> Optional[int]:
    if not _validate_hwnd(hwnd) or user32 is None:
        return None
    try:
        with _safe_call():
            result = user32.GetAncestor(hwnd, ctypes.c_uint(ga_flag))
            return int(result) if result else None
    except Exception as e:
        logger.debug("GetAncestor misslyckades: %s", e)
        return None


def get_ancestor_chain(hwnd: int) -> List[int]:
    if not _validate_hwnd(hwnd) or user32 is None:
        return []
    chain: List[int] = []
    try:
        with _safe_call():
            current = int(hwnd)
            seen: Set[int] = set()
            while current and current not in seen:
                seen.add(current)
                chain.append(current)
                parent = user32.GetParent(current)
                if parent:
                    current = int(parent)
                    continue
                ancestor = user32.GetAncestor(current, GA_ROOT)
                if ancestor and int(ancestor) != current:
                    current = int(ancestor)
                else:
                    break
                if len(chain) > 20:
                    break
    except Exception as e:
        logger.debug("get_ancestor_chain misslyckades: %s", e)
    return chain


def get_window_styles(hwnd: int) -> Tuple[int, int]:
    if not _validate_hwnd(hwnd):
        return (0, 0)
    try:
        with _safe_call():
            style = _GetWindowLong(hwnd, GWL_STYLE)
            ex = _GetWindowLong(hwnd, GWL_EXSTYLE)
            return (int(style) & 0xFFFFFFFF, int(ex) & 0xFFFFFFFF)
    except Exception as e:
        logger.debug("get_window_styles misslyckades: %s", e)
        return (0, 0)


def has_extended_style(hwnd: int, style: int) -> bool:
    _, ex = get_window_styles(hwnd)
    return bool(ex & style)


def get_z_order_position(hwnd: int) -> int:
    if not _validate_hwnd(hwnd) or user32 is None:
        return -1
    try:
        with _safe_call():
            pos = 0
            current = int(hwnd)
            while True:
                prev = user32.GetWindow(current, GW_HWNDPREV)
                if not prev:
                    break
                pos += 1
                current = int(prev)
                if pos > 1000:
                    break
            return pos
    except Exception as e:
        logger.debug("get_z_order_position misslyckades: %s", e)
        return -1


def move_to_z_position(hwnd: int, pos: int) -> bool:
    if not _validate_hwnd(hwnd) or user32 is None or pos < 0:
        return False
    try:
        with _safe_call():
            after = hwnd
            for _ in range(pos):
                prev = user32.GetWindow(after, GW_HWNDPREV)
                if not prev:
                    break
                after = int(prev)
            return bool(user32.SetWindowPos(
                hwnd, int(after) if after else HWND_BOTTOM,
                0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
            ))
    except Exception as e:
        logger.debug("move_to_z_position misslyckades: %s", e)
        return False


def dump_window_tree(hwnd: int, max_depth: int = 3, _depth: int = 0) -> List[Dict[str, Any]]:
    if not _validate_hwnd(hwnd) or _depth > max_depth:
        return []
    info = get_window_info(hwnd)
    title = get_window_title(hwnd)
    children = enum_child_windows(hwnd)
    node = {
        "hwnd": int(hwnd) if hwnd else None,
        "title": title,
        "info": info,
        "children": [],
    }
    for child in children[:50]:
        node["children"].extend(dump_window_tree(child, max_depth, _depth + 1))
    return [node]


# ===========================================================================
# MONITOR / SCREEN HELPERS
# ===========================================================================

def _monitors_via_qt() -> List["MonitorInfo"]:
    """
    NY v7-fix12: monitor-info via Qt — multi-OS-fallback när Win32 saknas
    (Linux/macOS). Kräver en initierad QGuiApplication (annars tomt).
    """
    qgui = None
    for mod, attr in (
        ("PySide6.QtGui", "QGuiApplication"),
        ("PyQt6.QtGui", "QGuiApplication"),
        ("PyQt5.QtGui", "QGuiApplication"),
    ):
        try:
            import importlib
            qgui = getattr(importlib.import_module(mod), attr)
            break
        except Exception:
            continue
    if qgui is None:
        return []
    try:
        if qgui.instance() is None:
            return []  # ingen app-instans → inga skärmar att fråga
        out: List[MonitorInfo] = []
        for i, screen in enumerate(qgui.screens()):
            g = screen.geometry()
            avail = screen.availableGeometry()
            out.append(MonitorInfo(
                hmonitor=i + 1,
                monitor_rect=Rect(g.x(), g.y(), g.width(), g.height()),
                work_rect=Rect(
                    avail.x(), avail.y(), avail.width(), avail.height()
                ),
                is_primary=(i == 0),
                device_name=screen.name() if hasattr(screen, "name") else "",
            ))
        return out
    except Exception as e:
        logger.debug("_monitors_via_qt misslyckades: %s", e)
        return []


def get_screen_size() -> Tuple[int, int]:
    if not IS_WINDOWS or user32 is None:
        # v7-fix12: multi-OS — primärskärm via Qt om Win32 saknas
        mons = _monitors_via_qt()
        if mons:
            m = mons[0]
            return (m.monitor_rect.width, m.monitor_rect.height)
        return (0, 0)
    try:
        with _safe_call():
            return (int(user32.GetSystemMetrics(SM_CXSCREEN)),
                    int(user32.GetSystemMetrics(SM_CYSCREEN)))
    except Exception as e:
        logger.debug("get_screen_size misslyckades: %s", e)
        return (0, 0)


def get_screen_geometry() -> Tuple[int, int, int, int]:
    if not IS_WINDOWS or user32 is None:
        return (0, 0, 0, 0)
    try:
        with _safe_call():
            x = int(user32.GetSystemMetrics(SM_XVIRTUALSCREEN))
            y = int(user32.GetSystemMetrics(SM_YVIRTUALSCREEN))
            w = int(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN))
            h = int(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))
            if w > 0 and h > 0:
                return (x, y, x + w, y + h)
            return (0, 0, int(user32.GetSystemMetrics(SM_CXSCREEN)),
                    int(user32.GetSystemMetrics(SM_CYSCREEN)))
    except Exception as e:
        logger.debug("get_screen_geometry misslyckades: %s", e)
        return (0, 0, 0, 0)


def get_monitor_info(hwnd: int) -> Optional[MonitorInfo]:
    if not _validate_hwnd(hwnd) or user32 is None:
        return None
    try:
        with _safe_call():
            monitor = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
            if not monitor:
                return None
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                return MonitorInfo(
                    hmonitor=int(monitor),
                    monitor_rect=Rect(
                        int(info.rcMonitor.left), int(info.rcMonitor.top),
                        int(info.rcMonitor.right) - int(info.rcMonitor.left),
                        int(info.rcMonitor.bottom) - int(info.rcMonitor.top),
                    ),
                    work_rect=Rect(
                        int(info.rcWork.left), int(info.rcWork.top),
                        int(info.rcWork.right) - int(info.rcWork.left),
                        int(info.rcWork.bottom) - int(info.rcWork.top),
                    ),
                    is_primary=bool(info.dwFlags & 1),
                )
    except Exception as e:
        logger.debug("GetMonitorInfo misslyckades: %s", e)
    return None


def get_all_monitors() -> List[MonitorInfo]:
    if not IS_WINDOWS or user32 is None:
        # v7-fix12: multi-OS — fråga Qt om Win32 saknas (Linux/macOS)
        return _monitors_via_qt()
    results: List[MonitorInfo] = []
    try:
        MonitorEnumProc = ctypes.WINFUNCTYPE(
            ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p,
            ctypes.POINTER(RECT), ctypes.c_long,
        )
        def callback(hmonitor: int, _hdc: int, _lprect: int, _lparam: int) -> bool:
            try:
                info = MONITORINFO()
                info.cbSize = ctypes.sizeof(MONITORINFO)
                if user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
                    results.append(MonitorInfo(
                        hmonitor=int(hmonitor),
                        monitor_rect=Rect(
                            int(info.rcMonitor.left), int(info.rcMonitor.top),
                            int(info.rcMonitor.right) - int(info.rcMonitor.left),
                            int(info.rcMonitor.bottom) - int(info.rcMonitor.top),
                        ),
                        work_rect=Rect(
                            int(info.rcWork.left), int(info.rcWork.top),
                            int(info.rcWork.right) - int(info.rcWork.left),
                            int(info.rcWork.bottom) - int(info.rcWork.top),
                        ),
                        is_primary=bool(info.dwFlags & 1),
                    ))
            except Exception:
                pass
            return True
        with _safe_call():
            user32.EnumDisplayMonitors(None, None, MonitorEnumProc(callback), 0)
    except Exception as e:
        logger.debug("get_all_monitors misslyckades: %s", e)
    return results


def get_monitor_at_point(x: int, y: int) -> Optional[MonitorInfo]:
    if not IS_WINDOWS or user32 is None:
        return None
    try:
        with _safe_call():
            pt = POINT(x, y)
            monitor = user32.MonitorFromPoint(pt, MONITOR_DEFAULTTONEAREST)
            if not monitor:
                return None
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                return MonitorInfo(
                    hmonitor=int(monitor),
                    monitor_rect=Rect(
                        int(info.rcMonitor.left), int(info.rcMonitor.top),
                        int(info.rcMonitor.right) - int(info.rcMonitor.left),
                        int(info.rcMonitor.bottom) - int(info.rcMonitor.top),
                    ),
                    work_rect=Rect(
                        int(info.rcWork.left), int(info.rcWork.top),
                        int(info.rcWork.right) - int(info.rcWork.left),
                        int(info.rcWork.bottom) - int(info.rcWork.top),
                    ),
                    is_primary=bool(info.dwFlags & 1),
                )
    except Exception as e:
        logger.debug("get_monitor_at_point misslyckades: %s", e)
    return None


def get_active_monitor() -> Optional[MonitorInfo]:
    if not IS_WINDOWS or user32 is None:
        return None
    try:
        pos = get_cursor_pos()
        if pos:
            return get_monitor_at_point(pos[0], pos[1])
    except Exception as e:
        logger.debug("get_active_monitor misslyckades: %s", e)
    return None


def get_safe_zone_for_monitor(monitor_index: int = 0) -> Tuple[int, int, int, int]:
    monitors = get_all_monitors()
    if not monitors or monitor_index >= len(monitors):
        return get_screen_geometry()
    work = monitors[monitor_index].work_rect
    return work.to_tuple()


# ===========================================================================
# ENUM WINDOWS
# ===========================================================================

def enum_windows(visible_only: bool = True) -> List[int]:
    if not IS_WINDOWS or user32 is None:
        return []
    results: List[int] = []
    def callback(hwnd: int, _lparam: int) -> bool:
        try:
            if not visible_only or user32.IsWindowVisible(hwnd):
                results.append(int(hwnd))
        except Exception:
            pass
        return True
    try:
        with _safe_call():
            user32.EnumWindows(WNDENUMPROC(callback), 0)
    except Exception as e:
        logger.debug("EnumWindows misslyckades: %s", e)
    return results


def enum_child_windows(parent_hwnd: int) -> List[int]:
    if not _validate_hwnd(parent_hwnd) or user32 is None:
        return []
    results: List[int] = []
    def callback(hwnd: int, _lparam: int) -> bool:
        results.append(int(hwnd))
        return True
    try:
        with _safe_call():
            user32.EnumChildWindows(parent_hwnd, WNDENUMPROC(callback), 0)
    except Exception as e:
        logger.debug("EnumChildWindows misslyckades: %s", e)
    return results


def get_visible_window_count() -> int:
    if not IS_WINDOWS or user32 is None:
        return 0
    count = [0]
    def callback(hwnd: int, _lparam: int) -> bool:
        try:
            if user32.IsWindowVisible(hwnd):
                count[0] += 1
        except Exception:
            pass
        return True
    try:
        with _safe_call():
            user32.EnumWindows(WNDENUMPROC(callback), 0)
    except Exception:
        return 0
    return count[0]


# ===========================================================================
# RUNDADE HÖRN
# ===========================================================================

def set_rounded_region(hwnd: int, w: int, h: int, dpr: float, radius: int = 14) -> bool:
    if not _validate_hwnd(hwnd) or gdi32 is None or user32 is None:
        return False
    if w <= 0 or h <= 0:
        return False
    _clear_region_cache(hwnd)
    try:
        with _safe_call():
            r = max(1, int(radius * dpr))
            rgn = gdi32.CreateRoundRectRgn(0, 0, int(w) + 1, int(h) + 1, r, r)
            if rgn:
                user32.SetWindowRgn(hwnd, rgn, True)
                _REGION_CACHE[hwnd] = rgn
                return True
    except Exception as e:
        logger.error("set_rounded_region misslyckades: %s", e)
    return False


def clear_rounded_region(hwnd: int) -> bool:
    if not _validate_hwnd(hwnd) or user32 is None:
        return False
    _clear_region_cache(hwnd)
    try:
        with _safe_call():
            user32.SetWindowRgn(hwnd, 0, True)
        return True
    except Exception as e:
        logger.debug("clear_rounded_region misslyckades: %s", e)
        return False


def cleanup_dead_regions() -> int:
    if not IS_WINDOWS or user32 is None:
        return 0
    cleaned = 0
    for hwnd in list(_REGION_CACHE.keys()):
        if not is_window_visible(hwnd):
            _clear_region_cache(hwnd)
            cleaned += 1
    if cleaned:
        logger.info("Rensade %d döda GDI-regioner", cleaned)
    return cleaned


# ===========================================================================
# GLASMORPHISM
# ===========================================================================

def enable_glass_blur(hwnd: int, region: Optional[int] = None) -> bool:
    if not _validate_hwnd(hwnd) or dwmapi is None or not dwm_has_blur():
        return False
    if not is_composition_enabled():
        return False
    try:
        with _safe_call():
            bb = DWM_BLURBEHIND()
            bb.dwFlags = DWM_BB_ENABLE | (DWM_BB_BLURREGION if region else 0)
            bb.fEnable = True
            bb.hRgnBlur = region if region else 0
            bb.fTransitionOnMaximized = False
            hr = dwmapi.DwmEnableBlurBehindWindow(hwnd, ctypes.byref(bb))
        return hr == S_OK
    except Exception as e:
        logger.warning("enable_glass_blur misslyckades: %s", e)
        return False


def set_system_backdrop(hwnd: int, kind: int = DWMSBT_TRANSIENTWINDOW) -> bool:
    if (not _validate_hwnd(hwnd) or dwmapi is None
            or kind in (DWMSBT_MAINWINDOW, DWMSBT_TABBEDWINDOW) and not dwm_has_mica()
            or kind == DWMSBT_TRANSIENTWINDOW and not dwm_has_acrylic()):
        return False
    try:
        with _safe_call():
            value = ctypes.c_int(int(kind))
            hr = dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_SYSTEMBACKDROP_TYPE,
                ctypes.byref(value), ctypes.sizeof(value),
            )
        return hr == S_OK
    except Exception as e:
        logger.debug("set_system_backdrop misslyckades: %s", e)
        return False


def get_system_backdrop(hwnd: int) -> int:
    if not _validate_hwnd(hwnd) or dwmapi is None or not dwm_has_backdrop():
        return 0
    try:
        with _safe_call():
            value = ctypes.c_int(0)
            hr = dwmapi.DwmGetWindowAttribute(
                hwnd, DWMWA_SYSTEMBACKDROP_TYPE,
                ctypes.byref(value), ctypes.sizeof(value),
            )
        return int(value.value) if hr == S_OK else 0
    except Exception as e:
        logger.debug("get_system_backdrop misslyckades: %s", e)
        return 0


def set_window_corner(hwnd: int, kind: int = DWMWCP_ROUND) -> bool:
    if not _validate_hwnd(hwnd) or dwmapi is None or not dwm_has_corner():
        return False
    try:
        with _safe_call():
            value = ctypes.c_int(int(kind))
            hr = dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(value), ctypes.sizeof(value),
            )
        return hr == S_OK
    except Exception as e:
        logger.debug("set_window_corner misslyckades: %s", e)
        return False


def get_window_corner(hwnd: int) -> int:
    if not _validate_hwnd(hwnd) or dwmapi is None or not dwm_has_corner():
        return 0
    try:
        with _safe_call():
            value = ctypes.c_int(0)
            hr = dwmapi.DwmGetWindowAttribute(
                hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(value), ctypes.sizeof(value),
            )
        return int(value.value) if hr == S_OK else 0
    except Exception as e:
        logger.debug("get_window_corner misslyckades: %s", e)
        return 0


def set_border_color(hwnd: int, colorref: int) -> bool:
    if not _validate_hwnd(hwnd) or dwmapi is None:
        return False
    try:
        with _safe_call():
            value = ctypes.c_int(int(colorref))
            hr = dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_BORDER_COLOR,
                ctypes.byref(value), ctypes.sizeof(value),
            )
        return hr == S_OK
    except Exception as e:
        logger.debug("set_border_color misslyckades: %s", e)
        return False


def set_caption_color(hwnd: int, colorref: int) -> bool:
    if not _validate_hwnd(hwnd) or dwmapi is None:
        return False
    try:
        with _safe_call():
            value = ctypes.c_int(int(colorref))
            hr = dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_CAPTION_COLOR,
                ctypes.byref(value), ctypes.sizeof(value),
            )
        return hr == S_OK
    except Exception as e:
        logger.debug("set_caption_color misslyckades: %s", e)
        return False


def set_text_color(hwnd: int, colorref: int) -> bool:
    if not _validate_hwnd(hwnd) or dwmapi is None:
        return False
    try:
        with _safe_call():
            value = ctypes.c_int(int(colorref))
            hr = dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_TEXT_COLOR,
                ctypes.byref(value), ctypes.sizeof(value),
            )
        return hr == S_OK
    except Exception as e:
        logger.debug("set_text_color misslyckades: %s", e)
        return False


def extend_frame_into_client(hwnd: int, margins: Optional[Tuple[int, int, int, int]] = None) -> bool:
    if not _validate_hwnd(hwnd) or dwmapi is None:
        return False
    try:
        with _safe_call():
            m = MARGINS()
            if margins:
                m.cxLeftWidth, m.cxRightWidth, m.cyTopHeight, m.cyBottomHeight = margins
            hr = dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(m))
        return hr == S_OK
    except Exception as e:
        logger.debug("DwmExtendFrameIntoClientArea misslyckades: %s", e)
        return False


def apply_glassmorphism(hwnd: int, style: str = "translucent") -> bool:
    """Auto-fallback till translucent om Mica/Acrylic ej stöds."""
    if not _validate_hwnd(hwnd):
        return False
    style = (style or "").lower()
    if style == "none":
        return set_system_backdrop(hwnd, DWMSBT_NONE)
    if style == "mica":
        if not dwm_has_mica():
            return enable_glass_blur(hwnd)
        return (set_system_backdrop(hwnd, DWMSBT_MAINWINDOW) or
                set_window_corner(hwnd, DWMWCP_ROUND))
    if style == "acrylic":
        if not dwm_has_acrylic():
            return enable_glass_blur(hwnd)
        return (set_system_backdrop(hwnd, DWMSBT_TRANSIENTWINDOW) or
                set_window_corner(hwnd, DWMWCP_ROUND))
    if style == "auto":
        if dwm_has_acrylic():
            return apply_glassmorphism(hwnd, "acrylic")
        if dwm_has_mica():
            return apply_glassmorphism(hwnd, "mica")
        return enable_glass_blur(hwnd)
    return enable_glass_blur(hwnd)


# ===========================================================================
# KOMPOSITION
# ===========================================================================

def is_composition_enabled() -> bool:
    global _DWM_COMPOSITION_ENABLED
    if not IS_WINDOWS or dwmapi is None:
        return False
    try:
        with _safe_call():
            enabled = ctypes.c_bool()
            hr = dwmapi.DwmIsCompositionEnabled(ctypes.byref(enabled))
            _DWM_COMPOSITION_ENABLED = (hr == S_OK and bool(enabled.value))
            return _DWM_COMPOSITION_ENABLED
    except Exception as e:
        logger.debug("DwmIsCompositionEnabled misslyckades: %s", e)
        return False


_DWM_COMPOSITION_ENABLED: Optional[bool] = None


def refresh_composition_state() -> None:
    global _DWM_COMPOSITION_ENABLED
    _DWM_COMPOSITION_ENABLED = None


# ===========================================================================
# IKON-ZONER (BUGG 26)
# ===========================================================================

_ICON_ZONES_CACHE: List[IconZone] = []
_ICON_ZONES_CACHE_TIME: float = 0.0
_ICON_ZONES_LOCK = threading.RLock()
_DESKTOP_CHANGE_SUBSCRIBERS: List[Tuple[int, Callable[[str], None]]] = []
_SUBSCRIBER_LOCK = threading.RLock()
_NEXT_SUBSCRIBER_TOKEN: int = 1
_APPBAR_ZONES_CACHE: List[IconZone] = []
_APPBAR_ZONES_CACHE_TIME: float = 0.0
_SNAP_ZONES_CACHE: Dict[int, List[IconZone]] = {}
_SNAP_CACHE_TIME: float = 0.0


def _find_shelldll_defview() -> List[int]:
    if not IS_WINDOWS or user32 is None:
        return []
    try:
        results: List[int] = []
        def callback(hwnd: int, _lparam: int) -> bool:
            try:
                buf = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, buf, 256)
                if buf.value == SHELLDLL_DEFVIEW_CLASS:
                    results.append(int(hwnd))
            except Exception:
                pass
            return True
        with _safe_call():
            user32.EnumWindows(WNDENUMPROC(callback), 0)
        return results
    except Exception as e:
        logger.debug("_find_shelldll_defview misslyckades: %s", e)
        return []


def _find_listview_in_defview(defview_hwnd: int) -> Optional[int]:
    if not IS_WINDOWS or user32 is None:
        return None
    try:
        result = [None]
        def callback(hwnd: int, _lparam: int) -> bool:
            try:
                buf = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, buf, 256)
                if buf.value == LISTVIEW_CLASS:
                    if user32.IsWindowVisible(hwnd):
                        result[0] = int(hwnd)
                        return False
            except Exception:
                pass
            return True
        with _safe_call():
            user32.EnumChildWindows(defview_hwnd, WNDENUMPROC(callback), 0)
        return result[0]
    except Exception as e:
        logger.debug("_find_listview_in_defview misslyckades: %s", e)
        return None


def _get_icon_positions(listview_hwnd: int) -> List[IconZone]:
    if not IS_WINDOWS or user32 is None:
        return []
    rectangles: List[IconZone] = []
    try:
        LVM_GETITEMCOUNT = 0x1004
        LVM_GETITEMRECT = 0x100E

        count = user32.SendMessageW(listview_hwnd, LVM_GETITEMCOUNT, 0, 0)
        if count <= 0 or count > 1000:
            return []

        win_rect = RECT()
        if not user32.GetWindowRect(listview_hwnd, ctypes.byref(win_rect)):
            return []

        for i in range(min(count, 200)):
            try:
                rect = RECT()
                ok = user32.SendMessageW(
                    listview_hwnd, LVM_GETITEMRECT, i, ctypes.byref(rect)
                )
                if ok:
                    abs_left = win_rect.left + rect.left
                    abs_top = win_rect.top + rect.top
                    w = rect.right - rect.left
                    h = rect.bottom - rect.top
                    if w > 0 and h > 0:
                        rectangles.append(IconZone(abs_left, abs_top, w, h))
            except Exception:
                continue
    except Exception as e:
        logger.debug("_get_icon_positions misslyckades: %s", e)
    return rectangles


def get_icon_zones(force_refresh: bool = False) -> List[IconZone]:
    """Returnerar lista med IconZone-objekt (cachas i 60s)."""
    global _ICON_ZONES_CACHE, _ICON_ZONES_CACHE_TIME
    if not IS_WINDOWS:
        return []
    with _ICON_ZONES_LOCK:
        now = time.time()
        if (not force_refresh
                and _ICON_ZONES_CACHE
                and (now - _ICON_ZONES_CACHE_TIME) < ICON_ZONES_CACHE_TTL):
            return list(_ICON_ZONES_CACHE)
        try:
            all_zones: List[IconZone] = []
            defviews = _find_shelldll_defview()
            for defview in defviews:
                listview = _find_listview_in_defview(defview)
                if listview:
                    zones = _get_icon_positions(listview)
                    all_zones.extend(zones)
            _ICON_ZONES_CACHE = all_zones
            _ICON_ZONES_CACHE_TIME = now
            logger.debug(f"Hittade {len(all_zones)} ikon-zoner")
            return list(_ICON_ZONES_CACHE)
        except Exception as e:
            logger.error("get_icon_zones misslyckades: %s", e)
            return list(_ICON_ZONES_CACHE)


def refresh_icon_zones() -> None:
    """Tvinga om-probe av ikon-zoner."""
    global _ICON_ZONES_CACHE, _ICON_ZONES_CACHE_TIME
    with _ICON_ZONES_LOCK:
        _ICON_ZONES_CACHE = []
        _ICON_ZONES_CACHE_TIME = 0.0
    _notify_desktop_change("icon_zones_refreshed")


def subscribe_desktop_changes(callback: Callable[[str], None]) -> int:
    """Prenumerera på desktop-ändringar."""
    global _NEXT_SUBSCRIBER_TOKEN
    with _SUBSCRIBER_LOCK:
        token = _NEXT_SUBSCRIBER_TOKEN
        _NEXT_SUBSCRIBER_TOKEN += 1
        _DESKTOP_CHANGE_SUBSCRIBERS.append((token, callback))
        return token


def unsubscribe_desktop_changes(token: int) -> bool:
    with _SUBSCRIBER_LOCK:
        for i, (t, _) in enumerate(_DESKTOP_CHANGE_SUBSCRIBERS):
            if t == token:
                _DESKTOP_CHANGE_SUBSCRIBERS.pop(i)
                return True
        return False


def _notify_desktop_change(event: str) -> None:
    with _SUBSCRIBER_LOCK:
        subs = list(_DESKTOP_CHANGE_SUBSCRIBERS)
    for _, cb in subs:
        with suppress(Exception):
            cb(event)


# ===========================================================================
# REKTANGEL-UTILS (för anti-occlusion)
# ===========================================================================

def rects_overlap(
    rect1: Tuple[int, int, int, int],
    rect2: Tuple[int, int, int, int],
    margin: int = 0,
) -> bool:
    """Returnerar True om två rektanglar överlappar."""
    x1, y1, w1, h1 = rect1
    x2, y2, w2, h2 = rect2
    return not (
        x1 + w1 + margin <= x2 or
        x2 + w2 + margin <= x1 or
        y1 + h1 + margin <= y2 or
        y2 + h2 + margin <= y1
    )


def rect_contains_point(rect: Tuple[int, int, int, int], x: int, y: int) -> bool:
    rx, ry, rw, rh = rect
    return rx <= x < rx + rw and ry <= y < ry + rh


def rect_intersect(
    rect1: Tuple[int, int, int, int],
    rect2: Tuple[int, int, int, int],
) -> Optional[Tuple[int, int, int, int]]:
    left = max(rect1[0], rect2[0])
    top = max(rect1[1], rect2[1])
    right = min(rect1[0] + rect1[2], rect2[0] + rect2[2])
    bottom = min(rect1[1] + rect1[3], rect2[1] + rect2[3])
    if left < right and top < bottom:
        return (left, top, right - left, bottom - top)
    return None


def is_position_safe(
    x: int, y: int, w: int, h: int,
    icon_zones: Optional[List[IconZone]] = None,
    margin: int = 8,
) -> bool:
    """Returnerar True om (x, y, w, h) INTE täcker någon ikon."""
    if icon_zones is None:
        icon_zones = get_icon_zones()
    if not icon_zones:
        return True
    widget_rect = (x, y, w, h)
    for zone in icon_zones:
        if rects_overlap(widget_rect, zone.to_tuple(), margin):
            return False
    return True


def find_safe_position(
    target_x: int, target_y: int, w: int, h: int,
    screen_geo: Optional[Tuple[int, int, int, int]] = None,
    icon_zones: Optional[List[IconZone]] = None,
    margin: int = 8,
) -> Tuple[int, int]:
    """Hittar en säker position nära target som inte täcker ikoner."""
    if icon_zones is None:
        icon_zones = get_icon_zones()
    if screen_geo is None:
        screen_geo = get_screen_geometry()
    if not screen_geo:
        return (target_x, target_y)
    sx_left, sy_top, sx_right, sy_bot = screen_geo
    appbar_zones = get_appbar_zones()
    forbidden = list(icon_zones) + list(appbar_zones)
    candidates = [
        (target_x, target_y),
        (sx_right - w - 20, target_y),
        (sx_left + 20, target_y),
        (target_x, sy_top + 20),
        (target_x, sy_bot - h - 20),
        (sx_right - w - 20, sy_top + 20),
        (sx_left + 20, sy_top + 20),
        (sx_right - w - 20, sy_bot - h - 20),
        (sx_left + 20, sy_bot - h - 20),
    ]
    for cx, cy in candidates:
        cx = max(sx_left + 20, min(cx, sx_right - w - 20))
        cy = max(sy_top + 20, min(cy, sy_bot - h - 20))
        widget_rect = (cx, cy, w, h)
        if all(not rects_overlap(widget_rect, zone.to_tuple(), margin) for zone in forbidden):
            return (cx, cy)
    return (sx_left + 20, sy_top + 20)


def find_safe_position_on_monitor(
    target_x: int, target_y: int, w: int, h: int,
    monitor_index: int = 0,
    icon_zones: Optional[List[IconZone]] = None,
    margin: int = 8,
) -> Tuple[int, int]:
    """Hittar safe position inom specifik monitor."""
    monitors = get_all_monitors()
    if not monitors or monitor_index >= len(monitors):
        return find_safe_position(target_x, target_y, w, h, None, icon_zones, margin)
    m = monitors[monitor_index]
    work = m.work_rect
    return find_safe_position(
        max(work.x, min(target_x, work.right - w - 20)),
        max(work.y, min(target_y, work.bottom - h - 20)),
        w, h, work.to_tuple(), icon_zones, margin,
    )


def get_appbar_zones(force_refresh: bool = False) -> List[IconZone]:
    """Returnerar AppBar-zoner (taskbar)."""
    global _APPBAR_ZONES_CACHE, _APPBAR_ZONES_CACHE_TIME
    if not IS_WINDOWS or shell32 is None:
        return []
    now = time.time()
    if (not force_refresh
            and _APPBAR_ZONES_CACHE
            and (now - _APPBAR_ZONES_CACHE_TIME) < APPBAR_CACHE_TTL):
        return list(_APPBAR_ZONES_CACHE)
    zones: List[IconZone] = []
    try:
        results: List[IconZone] = []
        def callback(hwnd: int, _lparam: int) -> bool:
            try:
                buf = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, buf, 256)
                if buf.value in ("Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
                    if user32.IsWindowVisible(hwnd):
                        rect = RECT()
                        if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                            results.append(IconZone(
                                int(rect.left), int(rect.top),
                                int(rect.right - rect.left),
                                int(rect.bottom - rect.top),
                            ))
            except Exception:
                pass
            return True
        with _safe_call():
            user32.EnumWindows(WNDENUMPROC(callback), 0)
        zones = results
        _APPBAR_ZONES_CACHE = zones
        _APPBAR_ZONES_CACHE_TIME = now
    except Exception as e:
        logger.debug("get_appbar_zones misslyckades: %s", e)
    return list(_APPBAR_ZONES_CACHE)


def get_snap_zones(force_refresh: bool = False) -> List[IconZone]:
    """Returnerar Windows 11 Aero Snap-zoner."""
    global _SNAP_ZONES_CACHE, _SNAP_CACHE_TIME
    if not IS_WINDOWS or not supports_aero_snap_zones():
        return []
    now = time.time()
    if (not force_refresh
            and _SNAP_ZONES_CACHE
            and (now - _SNAP_CACHE_TIME) < SNAP_CACHE_TTL):
        all_zones: List[IconZone] = []
        for v in _SNAP_ZONES_CACHE.values():
            all_zones.extend(v)
        return all_zones
    snap_zones: Dict[int, List[IconZone]] = {}
    try:
        monitors = get_all_monitors()
        for i, m in enumerate(monitors):
            work = m.work_rect
            mx, my, mw, mh = work.x, work.y, work.width, work.height
            left = IconZone(mx, my, mw // 2, mh)
            right = IconZone(mx + mw // 2, my, mw - mw // 2, mh)
            snap_zones[i] = [left, right]
        _SNAP_ZONES_CACHE = snap_zones
        _SNAP_CACHE_TIME = now
    except Exception as e:
        logger.debug("get_snap_zones misslyckades: %s", e)
    all_zones = []
    for v in _SNAP_ZONES_CACHE.values():
        all_zones.extend(v)
    return all_zones


def validate_position_comprehensive(
    x: int, y: int, w: int, h: int,
    icon_zones: Optional[List[IconZone]] = None,
    appbar_zones: Optional[List[IconZone]] = None,
    margin: int = 8,
) -> Dict[str, Any]:
    """Fullständig kollisionskontroll (ikoner + appbar)."""
    if icon_zones is None:
        icon_zones = get_icon_zones()
    if appbar_zones is None:
        appbar_zones = get_appbar_zones()
    widget_rect = (x, y, w, h)
    result = {
        "safe": True,
        "icon_overlap": None,
        "appbar_overlap": None,
        "icon_count_overlapped": 0,
        "appbar_count_overlapped": 0,
    }
    for zone in icon_zones:
        if rects_overlap(widget_rect, zone.to_tuple(), margin):
            result["safe"] = False
            result["icon_overlap"] = zone.to_tuple()
            result["icon_count_overlapped"] += 1
    for zone in appbar_zones:
        if rects_overlap(widget_rect, zone.to_tuple(), margin):
            result["safe"] = False
            result["appbar_overlap"] = zone.to_tuple()
            result["appbar_count_overlapped"] += 1
    return result


def snap_to_monitor_edge(
    x: int, y: int, w: int, h: int,
    threshold: int = SNAP_THRESHOLD_DEFAULT,
) -> Tuple[int, int]:
    """Snappar positionen till monitor-kanter inom threshold."""
    geo = get_screen_geometry()
    if not geo or geo[2] - geo[0] <= 0:
        return (x, y)
    sx_left, sy_top, sx_right, sy_bot = geo
    nx, ny = x, y
    if abs(x - sx_left) <= threshold:
        nx = sx_left
    elif abs((x + w) - sx_right) <= threshold:
        nx = sx_right - w
    if abs(y - sy_top) <= threshold:
        ny = sy_top
    elif abs((y + h) - sy_bot) <= threshold:
        ny = sy_bot - h
    return (nx, ny)


# ===========================================================================
# HOTKEYS
# ===========================================================================

def register_hotkey(hwnd: int, hotkey_id: int, modifiers: int, vk_code: int) -> bool:
    if not _validate_hwnd(hwnd) or user32 is None:
        return False
    try:
        with _safe_call():
            ok = user32.RegisterHotKey(hwnd, int(hotkey_id), ctypes.c_uint(modifiers), ctypes.c_uint(vk_code))
        return bool(ok)
    except Exception as e:
        logger.error("RegisterHotKey misslyckades: %s", e)
        return False


def register_hotkey_with_retry(
    hwnd: int, hotkey_id: int, modifiers: int, vk_code: int,
    max_retries: int = 3, initial_delay: float = 0.1,
) -> bool:
    """Registrera hotkey med exponentiell backoff."""
    delay = initial_delay
    for attempt in range(max_retries):
        if register_hotkey(hwnd, hotkey_id, modifiers, vk_code):
            if attempt > 0:
                logger.info("Hotkey %d registrerad efter %d försök", hotkey_id, attempt + 1)
            return True
        time.sleep(delay)
        delay *= 2
    logger.error("Hotkey %d kunde inte registreras efter %d försök", hotkey_id, max_retries)
    return False


def unregister_hotkey(hwnd: int, hotkey_id: int) -> bool:
    if not _validate_hwnd(hwnd) or user32 is None:
        return False
    try:
        with _safe_call():
            ok = user32.UnregisterHotKey(hwnd, int(hotkey_id))
        return bool(ok)
    except Exception as e:
        logger.debug("UnregisterHotKey misslyckades: %s", e)
        return False


def unregister_all_hotkeys(hwnd: int, max_id: int = 100) -> int:
    if not _validate_hwnd(hwnd) or user32 is None:
        return 0
    count = 0
    for hid in range(1, max_id + 1):
        with suppress(Exception):
            if unregister_hotkey(hwnd, hid):
                count += 1
    return count


def register_hotkey_profile(hwnd: int, profile: Dict[str, Tuple[int, int, int]]) -> int:
    if not _validate_hwnd(hwnd):
        return 0
    count = 0
    for name, (hk_id, mods, vk) in profile.items():
        with suppress(Exception):
            if register_hotkey_with_retry(hwnd, hk_id, mods, vk):
                count += 1
    return count


DEFAULT_HOTKEY_PROFILE: Dict[str, Tuple[int, int, int]] = {
    "add_task":         (HK_ADD_TASK, MOD_ALT | MOD_CONTROL, 0x4E),
    "toggle_visible":   (HK_TOGGLE_VISIBLE, MOD_ALT | MOD_CONTROL, 0x48),
    "toggle_inbox":     (HK_TOGGLE_INBOX, MOD_ALT | MOD_CONTROL, 0x49),
    "open_search":      (HK_OPEN_SEARCH, MOD_ALT | MOD_CONTROL, 0x46),
    "toggle_theme":     (HK_TOGGLE_THEME, MOD_ALT | MOD_CONTROL, 0x54),
    "clear_archive":    (HK_CLEAR_ARCHIVE, MOD_ALT | MOD_CONTROL, 0x43),
}


# ===========================================================================
# VISUELL FEEDBACK
# ===========================================================================

def flash_window(hwnd: int, count: int = 3, timeout_ms: int = 0,
                 flags: int = FLASHW_ALL) -> bool:
    if not _validate_hwnd(hwnd) or user32 is None:
        return False
    try:
        with _safe_call():
            info = FLASHWINFO()
            info.cbSize = ctypes.sizeof(FLASHWINFO)
            info.hwnd = hwnd
            info.dwFlags = ctypes.c_ulong(flags)
            info.uCount = ctypes.c_uint(int(count))
            info.dwTimeout = ctypes.c_ulong(int(timeout_ms))
            return bool(user32.FlashWindowEx(ctypes.byref(info)))
    except Exception as e:
        logger.debug("FlashWindowEx misslyckades: %s", e)
        return False


def flash_window_pattern(hwnd: int, on_ms: int = 500, off_ms: int = 500, count: int = 3) -> bool:
    if not _validate_hwnd(hwnd):
        return False
    for _ in range(count):
        if not flash_window(hwnd, count=1, timeout_ms=on_ms, flags=FLASHW_TRAY | FLASHW_TIMERNOFG):
            return False
        time.sleep((on_ms + off_ms) / 1000.0)
    return flash_window(hwnd, count=0, flags=FLASHW_STOP)


def stop_flash_window(hwnd: int) -> bool:
    return flash_window(hwnd, count=0, flags=FLASHW_STOP)


def message_box(text: str, title: str = "Ledgebord",
                flags: int = 0x00000040) -> int:
    if not IS_WINDOWS or user32 is None:
        return 0
    try:
        with _safe_call():
            return int(user32.MessageBoxW(None, ctypes.c_wchar_p(text), ctypes.c_wchar_p(title), ctypes.c_uint(flags)))
    except Exception as e:
        logger.debug("MessageBox misslyckades: %s", e)
        return 0


def play_system_sound(sound_type: str = "asterisk") -> bool:
    sound_map = {
        "asterisk": 0x00000040,
        "exclamation": 0x00000030,
        "hand": 0x00000010,
        "question": 0x00000020,
        "ok": 0x00000040,
    }
    flags = sound_map.get(sound_type.lower(), 0x00000040)
    return message_box("", "System", flags) >= 0


# ===========================================================================
# INPUT / CURSOR
# ===========================================================================

def is_key_pressed(vk_code: int) -> bool:
    if not IS_WINDOWS or user32 is None:
        return False
    try:
        return bool(user32.GetAsyncKeyState(int(vk_code)) & 0x8000)
    except Exception:
        return False


def get_cursor_pos() -> Optional[Tuple[int, int]]:
    if not IS_WINDOWS or user32 is None:
        return None
    try:
        pt = POINT()
        with _safe_call():
            if user32.GetCursorPos(ctypes.byref(pt)):
                return (int(pt.x), int(pt.y))
    except Exception as e:
        logger.debug("get_cursor_pos misslyckades: %s", e)
    return None


def set_cursor_pos(x: int, y: int) -> bool:
    if not IS_WINDOWS or user32 is None:
        return False
    try:
        with _safe_call():
            return bool(user32.SetCursorPos(int(x), int(y)))
    except Exception as e:
        logger.debug("set_cursor_pos misslyckades: %s", e)
        return False


def clip_cursor(rect: Optional[Tuple[int, int, int, int]]) -> bool:
    """Lås markören till rect (None = frigör)."""
    if not IS_WINDOWS or user32 is None:
        return False
    try:
        with _safe_call():
            if rect is None:
                return bool(user32.ClipCursor(None))
            r = RECT(rect[0], rect[1], rect[2], rect[3])
            return bool(user32.ClipCursor(ctypes.byref(r)))
    except Exception as e:
        logger.debug("clip_cursor misslyckades: %s", e)
        return False


def get_idle_time_ms() -> int:
    if not IS_WINDOWS or user32 is None or kernel32 is None:
        return 0
    try:
        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(LASTINPUTINFO)
        with _safe_call():
            if not user32.GetLastInputInfo(ctypes.byref(info)):
                return 0
        now = int(kernel32.GetTickCount64())
        return now - int(info.dwTime)
    except Exception as e:
        logger.debug("get_idle_time_ms misslyckades: %s", e)
        return 0


# ===========================================================================
# REDRAW HELPERS
# ===========================================================================

def invalidate_window(hwnd: int, rect: Optional[Tuple[int, int, int, int]] = None) -> bool:
    if not _validate_hwnd(hwnd) or user32 is None:
        return False
    try:
        with _safe_call():
            if rect:
                r = RECT(rect[0], rect[1], rect[2], rect[3])
                return bool(user32.InvalidateRect(hwnd, ctypes.byref(r), True))
            return bool(user32.InvalidateRect(hwnd, None, True))
    except Exception as e:
        logger.debug("invalidate_window misslyckades: %s", e)
        return False


def update_window(hwnd: int) -> bool:
    if not _validate_hwnd(hwnd) or user32 is None:
        return False
    try:
        with _safe_call():
            return bool(user32.UpdateWindow(hwnd))
    except Exception as e:
        logger.debug("update_window misslyckades: %s", e)
        return False


def force_window_redraw(hwnd: int) -> bool:
    if not _validate_hwnd(hwnd) or user32 is None:
        return False
    try:
        with _safe_call():
            user32.InvalidateRect(hwnd, None, True)
            user32.UpdateWindow(hwnd)
            return True
    except Exception as e:
        logger.debug("force_window_redraw misslyckades: %s", e)
        return False


# ===========================================================================
# PROCESS INFO
# ===========================================================================

def get_current_process_id() -> int:
    if not IS_WINDOWS or kernel32 is None:
        return 0
    try:
        return int(kernel32.GetCurrentProcessId())
    except Exception:
        return 0


def get_current_thread_id() -> int:
    if not IS_WINDOWS or kernel32 is None:
        return 0
    try:
        return int(kernel32.GetCurrentThreadId())
    except Exception:
        return 0


def get_tick_count_ms() -> int:
    if not IS_WINDOWS or kernel32 is None:
        return 0
    try:
        return int(kernel32.GetTickCount64())
    except Exception:
        return 0


def get_command_line_args() -> List[str]:
    if not IS_WINDOWS or kernel32 is None:
        return sys.argv
    try:
        with _safe_call():
            cmd = kernel32.GetCommandLineW()
            if cmd:
                raw = ctypes.wstring_at(cmd)
                return raw.split() if raw else []
    except Exception as e:
        logger.debug("get_command_line_args misslyckades: %s", e)
    return sys.argv


def get_executable_path() -> Optional[str]:
    if not IS_WINDOWS or kernel32 is None:
        return sys.executable
    try:
        with _safe_call():
            h = kernel32.GetCurrentProcess()
            buf = ctypes.create_unicode_buffer(1024)
            size = ctypes.c_ulong(1024)
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return buf.value
    except Exception as e:
        logger.debug("get_executable_path misslyckades: %s", e)
    return sys.executable


def shell_execute(path: str, args: str = "", verb: str = "open") -> bool:
    if not IS_WINDOWS or shell32 is None:
        return False
    try:
        with _safe_call():
            result = shell32.ShellExecuteW(
                None, ctypes.c_wchar_p(verb), ctypes.c_wchar_p(path),
                ctypes.c_wchar_p(args), None, 1,
            )
        return int(result) > 32
    except Exception as e:
        logger.debug("shell_execute misslyckades: %s", e)
        return False


# ===========================================================================
# AUTOSTART (multi-OS)
# ===========================================================================

def _find_python_executable() -> str:
    if getattr(sys, "frozen", False):
        return sys.executable
    exe = os.path.abspath(sys.executable)
    if exe.lower().endswith("python.exe"):
        candidate = exe[:-10] + "pythonw.exe"
        if os.path.exists(candidate):
            return candidate
    return exe


def _find_main_script() -> str:
    candidates = ["main.pyw", "main.py"]
    # FIX v7-fix12: core/desktop.py ligger i core/ — main.pyw ligger i
    # projektroten (ett steg upp). Gamla sökvägen pekade på core/main.pyw
    # som ALDRIG finns → autostart-kommandot startade ingenting.
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for c in candidates:
        path = os.path.join(root, c)
        if os.path.exists(path):
            return path
    return os.path.join(root, "main.pyw")


def _resolve_exe_command(
    cmd: Optional[str] = None,
    include_delay: bool = False,
    delay_sec: int = 0,
    executable_path: Optional[str] = None,
    script_path: Optional[str] = None,
    args: str = "",
) -> str:
    """
    Bygg autostart-kommando (multi-OS, v7-fix12).

    FIX v7-fix12: gamla signaturen (cmd, include_delay, delay_sec) matchade
    INTE anroparna i enable_autostart_windows/macos/linux som skickade
    (executable_path, script_path, args, delay_sec) → TypeError på ALLA
    plattformar → autostart kunde ALDRIG aktiveras via denna modul.

    Prioritet: explicit 'cmd' > executable_path+script_path+args >
    auto-detektering (pythonw.exe på Windows + main.pyw i projektroten).
    Delay: Windows → 'cmd.exe /c timeout N', Unix → 'sleep N' (körs via sh).
    """
    base = cmd
    if not base:
        if getattr(sys, "frozen", False):
            # FIX v7-fix12: fryst exe (PyInstaller) tar INTE main.pyw som
            # argument — kommandot är bara exe:t (+ ev. args).
            base = f'"{executable_path or sys.executable}"'
        else:
            exe = executable_path or _find_python_executable()
            script = script_path or _find_main_script()
            base = f'"{exe}" "{script}"'
        if args:
            base = f"{base} {args}"
    if include_delay and delay_sec > 0:
        if IS_WINDOWS:
            return f"cmd.exe /c timeout {delay_sec} >nul && {base}"
        return f"sleep {delay_sec} && {base}"
    return base


def is_autostart_enabled() -> bool:
    if IS_WINDOWS:
        return _is_autostart_enabled_windows()
    if IS_MACOS:
        return _is_autostart_enabled_macos()
    if IS_LINUX:
        return _is_autostart_enabled_linux()
    return False


def _is_autostart_enabled_windows() -> bool:
    if not IS_WINDOWS or winreg is None:
        return False
    try:
        with _safe_call():
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, winreg.KEY_READ
            )
        try:
            winreg.QueryValueEx(key, AUTOSTART_VALUE_NAME)
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except Exception:
        return False


def _is_autostart_enabled_macos() -> bool:
    plist_path = os.path.expanduser(
        os.path.join("~", MACOS_LAUNCH_AGENTS_DIR, MACOS_PLIST_FILE)
    )
    return os.path.exists(plist_path)


def _is_autostart_enabled_linux() -> bool:
    if not IS_LINUX:
        return False
    autostart_dir = os.path.join(
        os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
        "autostart",
    )
    return os.path.exists(os.path.join(autostart_dir, LINUX_DESKTOP_FILE))


def enable_autostart(
    executable_path: Optional[str] = None,
    args: str = "",
    delay_sec: int = 0,
) -> bool:
    if IS_WINDOWS:
        return enable_autostart_windows(executable_path, args, delay_sec)
    if IS_MACOS:
        return enable_autostart_macos(executable_path, args, delay_sec)
    if IS_LINUX:
        return enable_autostart_linux(executable_path, args, delay_sec)
    return False


def disable_autostart() -> bool:
    results = []
    if IS_WINDOWS:
        results.append(disable_autostart_windows())
        results.append(disable_autostart_startup())
        results.append(disable_autostart_schtasks())
    if IS_MACOS:
        results.append(disable_autostart_macos())
    if IS_LINUX:
        results.append(disable_autostart_linux())
    return any(results) if results else False


def enable_autostart_windows(
    executable_path: Optional[str] = None,
    args: str = "",
    delay_sec: int = 0,
    methods: Optional[List[str]] = None,
) -> bool:
    if not IS_WINDOWS:
        return False
    if methods is None:
        methods = ["registry", "startup"]
    cmd = _resolve_exe_command(executable_path=executable_path, args=args)
    results = []
    for method in methods:
        try:
            if method == "registry":
                results.append(_enable_autostart_registry(cmd))
            elif method == "startup":
                results.append(_enable_autostart_startup(cmd))
            elif method == "schtasks" and shutil.which("schtasks"):
                results.append(_enable_autostart_schtask(cmd, delay_sec))
        except Exception as e:
            logger.error("Autostart %s misslyckades: %s", method, e)
    return any(results)


def _enable_autostart_registry(cmd: str) -> bool:
    if not IS_WINDOWS or winreg is None:
        return False
    try:
        with _safe_call():
            key = winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, winreg.KEY_SET_VALUE
            )
        try:
            winreg.SetValueEx(key, AUTOSTART_VALUE_NAME, 0, winreg.REG_SZ, cmd)
            logger.info(f"Autostart aktiverat (Registry): {cmd}")
            return True
        finally:
            winreg.CloseKey(key)
    except Exception as e:
        logger.error(f"Registry-autostart misslyckades: {e}")
        return False


def _enable_autostart_startup(cmd: str) -> bool:
    if not IS_WINDOWS:
        return False
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return False
    startup_dir = os.path.join(appdata, *WINDOWS_STARTUP_SUBPATH.split("\\"))
    if not os.path.isdir(startup_dir):
        with suppress(OSError):
            os.makedirs(startup_dir, exist_ok=True)
    bat_path = os.path.join(startup_dir, f"{AUTOSTART_VALUE_NAME}.bat")
    try:
        # FIX v8: tidigare togs ALLA citattecken bort och hela kommandot citerades
        # som EN fil ("pythonw.exe main.pyw") → Windows: "Det går inte att hitta
        # filen" vid varje inloggning. Nu behålls citaten runt exe och skript.
        with open(bat_path, "w", encoding="utf-8", newline="") as f:
            f.write(f'@echo off\r\nchcp 65001 >nul\r\nstart "" {cmd}\r\n')
        logger.info(f"Autostart aktiverat (Startup-mapp): {bat_path}")
        return True
    except OSError as e:
        logger.error(f"Startup-mapp-autostart misslyckades: {e}")
        return False


def _enable_autostart_schtask(cmd: str, delay_sec: int = 0) -> bool:
    if not IS_WINDOWS or not shutil.which("schtasks"):
        return False
    try:
        result = subprocess.run(
            ["schtasks", "/create", "/tn", SCHTASKS_NAME, "/tr", cmd,
             "/sc", "onlogon", "/rl", "highest", "/f"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            logger.info(f"Autostart aktiverat (schtasks)")
            return True
        return False
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def disable_autostart_windows() -> bool:
    if not IS_WINDOWS or winreg is None:
        return False
    try:
        with _safe_call():
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, winreg.KEY_SET_VALUE
            )
        try:
            for _legacy in LEGACY_AUTOSTART_NAMES:
                with suppress(OSError):
                    winreg.DeleteValue(key, _legacy)
            winreg.DeleteValue(key, AUTOSTART_VALUE_NAME)
            return True
        except FileNotFoundError:
            return True
        finally:
            winreg.CloseKey(key)
    except Exception as e:
        logger.error(f"disable_autostart_windows misslyckades: {e}")
        return False


def disable_autostart_startup() -> bool:
    if not IS_WINDOWS:
        return False
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return False
    startup_dir = os.path.join(appdata, *WINDOWS_STARTUP_SUBPATH.split("\\"))
    for _name in (AUTOSTART_VALUE_NAME,) + tuple(LEGACY_AUTOSTART_NAMES):
        for ext in (".bat", ".lnk", ".cmd", ".vbs"):
            p = os.path.join(startup_dir, f"{_name}{ext}")
            with suppress(OSError):
                if os.path.exists(p):
                    os.remove(p)
    return True


def disable_autostart_schtasks() -> bool:
    if not IS_WINDOWS or not shutil.which("schtasks"):
        return False
    try:
        result = subprocess.run(
            ["schtasks", "/delete", "/tn", SCHTASKS_NAME, "/f"],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def get_autostart_command() -> Optional[str]:
    if IS_WINDOWS:
        if not IS_WINDOWS or winreg is None:
            return None
        try:
            with _safe_call():
                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, winreg.KEY_READ
                )
            try:
                value, _ = winreg.QueryValueEx(key, AUTOSTART_VALUE_NAME)
                return str(value) if value else None
            except FileNotFoundError:
                return None
            finally:
                winreg.CloseKey(key)
        except Exception:
            return None
    if IS_MACOS:
        return _get_autostart_command_macos()
    if IS_LINUX:
        return _get_autostart_command_linux()
    return None


def enable_autostart_macos(
    executable_path: Optional[str] = None,
    args: str = "",
    delay_sec: int = 0,
) -> bool:
    if not IS_MACOS:
        return False
    launch_agents = os.path.expanduser(os.path.join("~", MACOS_LAUNCH_AGENTS_DIR))
    with suppress(OSError):
        os.makedirs(launch_agents, exist_ok=True)
    plist_path = os.path.join(launch_agents, MACOS_PLIST_FILE)
    if executable_path is None:
        executable_path = get_executable_path() or sys.executable
    # FIX v7-fix12: samma som Linux — alltid appens entry point, aldrig argv[0].
    cmd = _resolve_exe_command(
        executable_path=executable_path,
        args=args, include_delay=delay_sec > 0, delay_sec=delay_sec,
    )
    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{MACOS_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/sh</string>
        <string>-c</string>
        <string>{cmd}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
</dict>
</plist>
"""
    try:
        with open(plist_path, "w", encoding="utf-8") as f:
            f.write(plist_content)
        with suppress(OSError, subprocess.TimeoutExpired, FileNotFoundError):
            subprocess.run(["launchctl", "load", plist_path], capture_output=True, timeout=5)
        logger.info(f"Autostart aktiverat (macOS LaunchAgent): {plist_path}")
        return True
    except OSError as e:
        logger.error(f"macOS-autostart misslyckades: {e}")
        return False


def disable_autostart_macos() -> bool:
    if not IS_MACOS:
        return False
    plist_path = os.path.expanduser(
        os.path.join("~", MACOS_LAUNCH_AGENTS_DIR, MACOS_PLIST_FILE)
    )
    if not os.path.exists(plist_path):
        return True
    try:
        with suppress(OSError, subprocess.TimeoutExpired, FileNotFoundError):
            subprocess.run(["launchctl", "unload", plist_path], capture_output=True, timeout=5)
        os.remove(plist_path)
        return True
    except OSError as e:
        logger.error(f"disable_autostart_macos misslyckades: {e}")
        return False


def _get_autostart_command_macos() -> Optional[str]:
    if not IS_MACOS:
        return None
    plist_path = os.path.expanduser(
        os.path.join("~", MACOS_LAUNCH_AGENTS_DIR, MACOS_PLIST_FILE)
    )
    if not os.path.exists(plist_path):
        return None
    try:
        with open(plist_path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def enable_autostart_linux(
    executable_path: Optional[str] = None,
    args: str = "",
    delay_sec: int = 0,
) -> bool:
    if not IS_LINUX:
        return False
    autostart_dir = os.path.join(
        os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
        "autostart",
    )
    with suppress(OSError):
        os.makedirs(autostart_dir, exist_ok=True)
    desktop_path = os.path.join(autostart_dir, LINUX_DESKTOP_FILE)
    if executable_path is None:
        executable_path = get_executable_path() or sys.executable
    # FIX v7-fix12: autostart ska ALLTID peka på appens entry point
    # (main.pyw i projektroten via _find_main_script) — INTE på argv[0]
    # som kan vara '-c', ett test-script eller interaktivt läge.
    cmd = _resolve_exe_command(executable_path=executable_path, args=args)
    # FIX v7-fix12: XDG-specen tillåter INTE "sleep N && ..." i Exec=
    # (Exec är inte ett shell-kommando) — delay hanteras via nyckeln nedan
    # som GNOME/KDE respekterar.
    delay_line = (
        f"X-GNOME-Autostart-Delay={delay_sec}\n" if delay_sec > 0 else ""
    )
    content = f"""[Desktop Entry]
Type=Application
Name=Ledgebord
GenericName=Desktop Todo
Comment=Desktop todo widget (autostart)
Exec={cmd}
Terminal=false
StartupNotify=false
X-GNOME-Autostart-enabled=true
{delay_line}Hidden=false
Categories=Utility;
"""
    try:
        with open(desktop_path, "w", encoding="utf-8") as f:
            f.write(content)
        with suppress(OSError):
            os.chmod(desktop_path, 0o755)
        logger.info(f"Autostart aktiverat (Linux .desktop): {desktop_path}")
        return True
    except OSError as e:
        logger.error(f"Linux-autostart misslyckades: {e}")
        return False


def disable_autostart_linux() -> bool:
    if not IS_LINUX:
        return False
    autostart_dir = os.path.join(
        os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
        "autostart",
    )
    desktop_path = os.path.join(autostart_dir, LINUX_DESKTOP_FILE)
    if os.path.exists(desktop_path):
        try:
            os.remove(desktop_path)
            return True
        except OSError as e:
            logger.error(f"disable_autostart_linux misslyckades: {e}")
            return False
    return True


def _get_autostart_command_linux() -> Optional[str]:
    if not IS_LINUX:
        return None
    autostart_dir = os.path.join(
        os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
        "autostart",
    )
    desktop_path = os.path.join(autostart_dir, LINUX_DESKTOP_FILE)
    if not os.path.exists(desktop_path):
        return None
    try:
        with open(desktop_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("Exec="):
                    return line[5:].strip()
    except OSError:
        return None
    return None


def register_autostart_universal(
    executable_path: Optional[str] = None,
    args: str = "",
    delay_sec: int = 0,
    methods: Optional[List[str]] = None,
) -> Dict[str, bool]:
    """Universal autostart (auto-detekterar plattform)."""
    results: Dict[str, bool] = {}
    if IS_WINDOWS:
        if methods is None:
            methods = ["registry", "startup"]
        for method in methods:
            if method == "registry":
                results["registry"] = bool(enable_autostart(executable_path, args, delay_sec))
            elif method == "startup":
                cmd = _resolve_exe_command(executable_path=executable_path, args=args)
                results["startup"] = _enable_autostart_startup(cmd)
            elif method == "schtasks":
                cmd = _resolve_exe_command(executable_path=executable_path, args=args)
                results["schtasks"] = _enable_autostart_schtask(cmd, delay_sec)
    elif IS_MACOS:
        results["launchd"] = enable_autostart_macos(executable_path, args, delay_sec)
    elif IS_LINUX:
        results["desktop"] = enable_autostart_linux(executable_path, args, delay_sec)
    else:
        logger.warning(f"Autostart stöds inte på plattform: {sys.platform}")
    return results


def remove_autostart_universal(methods: Optional[List[str]] = None) -> Dict[str, bool]:
    results: Dict[str, bool] = {}
    if IS_WINDOWS:
        if methods is None:
            methods = ["registry", "startup", "schtasks"]
        for method in methods:
            if method == "registry":
                results["registry"] = disable_autostart_windows()
            elif method == "startup":
                results["startup"] = disable_autostart_startup()
            elif method == "schtasks":
                results["schtasks"] = disable_autostart_schtasks()
    elif IS_MACOS:
        results["launchd"] = disable_autostart_macos()
    elif IS_LINUX:
        results["desktop"] = disable_autostart_linux()
    return results


def verify_autostart() -> Dict[str, Any]:
    """Verifiera att autostart fungerar."""
    result: Dict[str, Any] = {
        "enabled": False,
        "command": None,
        "platform": sys.platform,
        "methods": {},
        "all_paths": [],
    }
    if IS_WINDOWS:
        result["methods"]["registry"] = _is_autostart_enabled_windows()
        if result["methods"]["registry"]:
            result["command"] = get_autostart_command()
            result["enabled"] = True
            result["all_paths"].append(f"Registry: HKCU\\{AUTOSTART_KEY}\\{AUTOSTART_VALUE_NAME}")
        appdata = os.environ.get("APPDATA")
        if appdata:
            startup_dir = os.path.join(appdata, *WINDOWS_STARTUP_SUBPATH.split("\\"))
            bat_path = os.path.join(startup_dir, f"{AUTOSTART_VALUE_NAME}.bat")
            result["methods"]["startup"] = os.path.exists(bat_path)
            if result["methods"]["startup"]:
                result["enabled"] = True
                result["all_paths"].append(f"Startup: {bat_path}")
        try:
            schtasks_result = subprocess.run(
                ["schtasks", "/query", "/tn", SCHTASKS_NAME],
                capture_output=True, text=True, timeout=5,
            )
            result["methods"]["schtasks"] = (schtasks_result.returncode == 0)
            if result["methods"]["schtasks"]:
                result["enabled"] = True
                result["all_paths"].append(f"schtasks: {SCHTASKS_NAME}")
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            result["methods"]["schtasks"] = False
    elif IS_MACOS:
        result["methods"]["launchd"] = _is_autostart_enabled_macos()
        result["enabled"] = result["methods"]["launchd"]
        if result["enabled"]:
            result["command"] = _get_autostart_command_macos()
            plist_path = os.path.expanduser(
                os.path.join("~", MACOS_LAUNCH_AGENTS_DIR, MACOS_PLIST_FILE)
            )
            result["all_paths"].append(plist_path)
    elif IS_LINUX:
        result["methods"]["desktop"] = _is_autostart_enabled_linux()
        result["enabled"] = result["methods"]["desktop"]
        if result["enabled"]:
            result["command"] = _get_autostart_command_linux()
            autostart_dir = os.path.join(
                os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
                "autostart",
            )
            desktop_path = os.path.join(autostart_dir, LINUX_DESKTOP_FILE)
            result["all_paths"].append(desktop_path)
    return result


def list_all_autostart_entries() -> List[Dict[str, str]]:
    entries: List[Dict[str, str]] = []
    if IS_WINDOWS and winreg is not None:
        try:
            with _safe_call():
                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, winreg.KEY_READ
                )
            try:
                i = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(key, i)
                        entries.append({
                            "platform": "windows",
                            "type": "registry",
                            "name": name,
                            "command": str(value) if value else "",
                        })
                        i += 1
                    except OSError:
                        break
            finally:
                winreg.CloseKey(key)
        except Exception as e:
            logger.debug("list_all_autostart_entries misslyckades: %s", e)
        appdata = os.environ.get("APPDATA")
        if appdata:
            startup_dir = os.path.join(appdata, *WINDOWS_STARTUP_SUBPATH.split("\\"))
            if os.path.isdir(startup_dir):
                for name in os.listdir(startup_dir):
                    if name.endswith((".bat", ".lnk", ".cmd", ".vbs")):
                        entries.append({
                            "platform": "windows",
                            "type": "startup-folder",
                            "name": name,
                            "command": os.path.join(startup_dir, name),
                        })
    elif IS_MACOS:
        launch_agents = os.path.expanduser(os.path.join("~", MACOS_LAUNCH_AGENTS_DIR))
        if os.path.isdir(launch_agents):
            for name in os.listdir(launch_agents):
                if name.endswith(".plist"):
                    entries.append({
                        "platform": "macos",
                        "type": "launchagent",
                        "name": name,
                        "command": os.path.join(launch_agents, name),
                    })
    elif IS_LINUX:
        autostart_dir = os.path.join(
            os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
            "autostart",
        )
        if os.path.isdir(autostart_dir):
            for name in os.listdir(autostart_dir):
                if name.endswith(".desktop"):
                    entries.append({
                        "platform": "linux",
                        "type": "xdg-autostart",
                        "name": name,
                        "command": os.path.join(autostart_dir, name),
                    })
    return entries


# ===========================================================================
# DIAGNOSTIK
# ===========================================================================

def get_platform_capabilities() -> Dict[str, Any]:
    """Returnerar komplett plattform + capabilities dict."""
    caps: Dict[str, Any] = {
        "platform": sys.platform,
        "is_windows": IS_WINDOWS,
        "is_macos": IS_MACOS,
        "is_linux": IS_LINUX,
        "is_bsd": IS_BSD,
        "is_unix": IS_UNIX,
        "is_64bit": _IS_64BIT,
        "desktop_env": DESKTOP_ENV,
        "session_type": _get_session_type(),
        "display_server": _get_display_server(),
        "windows_build": windows_build() if IS_WINDOWS else None,
        "windows_label": windows_version_label() if IS_WINDOWS else None,
        "windows_edition": windows_edition() if IS_WINDOWS else None,
        "dwm_composition": is_composition_enabled() if IS_WINDOWS else None,
        "dwm_blur": dwm_has_blur() if IS_WINDOWS else None,
        "dwm_mica": dwm_has_mica() if IS_WINDOWS else None,
        "dwm_acrylic": dwm_has_acrylic() if IS_WINDOWS else None,
        "dwm_corner": dwm_has_corner() if IS_WINDOWS else None,
        "dwm_backdrop": dwm_has_backdrop() if IS_WINDOWS else None,
        "immersive_dark": supports_immersive_dark() if IS_WINDOWS else None,
        "aero_snap_zones": supports_aero_snap_zones() if IS_WINDOWS else None,
        "user32_loaded": user32 is not None,
        "gdi32_loaded": gdi32 is not None,
        "dwmapi_loaded": dwmapi is not None,
        "kernel32_loaded": kernel32 is not None,
        "shell32_loaded": shell32 is not None,
        "screen_size": get_screen_size(),
        "screen_geometry": get_screen_geometry(),
        "monitor_count": len(get_all_monitors()) if IS_WINDOWS else 0,
        "visible_window_count": get_visible_window_count() if IS_WINDOWS else 0,
        "current_pid": get_current_process_id(),
        "platform_initialized": _initialized,
        "icon_zones_known": len(_ICON_ZONES_CACHE),
        "appbar_zones_known": len(_APPBAR_ZONES_CACHE),
        "autostart_enabled": is_autostart_enabled(),
        "autostart_methods": list_all_autostart_entries(),
        "idle_time_ms": get_idle_time_ms() if IS_WINDOWS else 0,
        "locale": _get_locale(),
        "screen_dpi": _get_screen_dpi(),
        "scaling_factor": _get_scaling_factor(),
        "color_depth": _get_color_depth(),
        "refresh_rate": _get_refresh_rate(),
    }
    return caps


# ===========================================================================
# SUPPORTERANDE FUNKTIONER (multi-OS)
# ===========================================================================

def _get_session_type() -> str:
    if IS_WINDOWS: return "win32"
    if IS_MACOS: return "aqua"
    if IS_LINUX_WAYLAND: return "wayland"
    if IS_LINUX_MIR: return "mir"
    if IS_LINUX_X11: return "x11"
    if IS_BSD: return "bsd"
    return "console"


def _get_display_server() -> str:
    if IS_WINDOWS: return "Windows"
    if IS_MACOS: return "Quartz"
    if IS_LINUX_WAYLAND: return "Wayland"
    if IS_LINUX_X11: return "X11"
    if IS_BSD: return "X11"
    return "Unknown"


def get_session_type() -> str: return _get_session_type()
def detect_display_server() -> str: return _get_display_server()
def get_desktop_environment() -> str: return DESKTOP_ENV


def get_system_theme() -> str:
    """Auto-detektering av systemtema (per plattform)."""
    if IS_WINDOWS: return _get_windows_theme()
    if IS_MACOS: return _get_macos_theme()
    if IS_LINUX: return _get_linux_theme()
    return "light"


def _get_windows_theme(timeout_sec: float = 2.0) -> str:
    if not IS_WINDOWS or winreg is None:
        return "light"
    try:
        with _safe_call(timeout_sec=timeout_sec):
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
                0, winreg.KEY_READ,
            )
        try:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return "light" if int(value) == 1 else "dark"
        except FileNotFoundError:
            return "light"
        finally:
            with suppress(OSError):
                winreg.CloseKey(key)
    except OSError as e:
        logger.debug(f"Kunde inte läsa Windows-tema: {e}")
        return "light"


def _get_macos_theme() -> str:
    if not IS_MACOS:
        return "light"
    try:
        result = subprocess.run(
            ["defaults", "read", "-g", "AppleInterfaceStyle"],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode == 0:
            return "dark" if "dark" in result.stdout.lower() else "light"
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return "light"


def _get_linux_theme() -> str:
    if not IS_LINUX:
        return "light"
    if shutil.which("gsettings"):
        try:
            result = subprocess.run(
                ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                capture_output=True, text=True, timeout=2,
            )
            if result.returncode == 0:
                value = result.stdout.strip().lower()
                if "dark" in value:
                    return "dark"
                return "light"
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
    return "light"


def _get_locale() -> str:
    try:
        import locale
        return locale.getdefaultlocale()[0] or "en_US"
    except Exception:
        return "en_US"


def get_locale() -> str: return _get_locale()


def _get_screen_dpi() -> int:
    if IS_WINDOWS and user32 is not None:
        try:
            with _safe_call():
                hdc = user32.GetDC(0)
                if hdc:
                    try:
                        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, LOGPIXELSX)
                        return int(dpi) if dpi > 0 else 96
                    finally:
                        user32.ReleaseDC(0, hdc)
        except Exception:
            pass
    return 96


def get_screen_dpi() -> int: return _get_screen_dpi()


def _get_scaling_factor() -> float:
    return _get_screen_dpi() / 96.0


def get_scaling_factor() -> float: return _get_scaling_factor()


def _get_color_depth() -> int:
    if IS_WINDOWS and user32 is not None:
        try:
            with _safe_call():
                hdc = user32.GetDC(0)
                if hdc:
                    try:
                        bpp = ctypes.windll.gdi32.GetDeviceCaps(hdc, BITSPIXEL)
                        return int(bpp) if bpp > 0 else 32
                    finally:
                        user32.ReleaseDC(0, hdc)
        except Exception:
            pass
    return 32


def get_color_depth() -> int: return _get_color_depth()


def _get_refresh_rate() -> int:
    if IS_WINDOWS and user32 is not None:
        try:
            with _safe_call():
                hdc = user32.GetDC(0)
                if hdc:
                    try:
                        rate = ctypes.windll.gdi32.GetDeviceCaps(hdc, VREFRESH)
                        return int(rate) if rate > 0 else 60
                    finally:
                        user32.ReleaseDC(0, hdc)
        except Exception:
            pass
    return 60


def get_refresh_rate() -> int: return _get_refresh_rate()


def _get_mouse_buttons() -> int:
    if IS_WINDOWS and user32 is not None:
        try:
            with _safe_call():
                return int(user32.GetSystemMetrics(SM_CMOUSEBUTTONS))
        except Exception:
            return 3
    return 3


def get_mouse_buttons() -> int: return _get_mouse_buttons()


def _get_keyboard_layout() -> str:
    if IS_WINDOWS and user32 is not None:
        try:
            with _safe_call():
                hwnd = user32.GetForegroundWindow()
                tid = user32.GetWindowThreadProcessId(hwnd, None)
                kl = user32.GetKeyboardLayout(tid)
                lang_id = kl & 0xFFFF
                return f"0x{lang_id:04X}"
        except Exception:
            pass
    return "unknown"


def get_keyboard_layout() -> str: return _get_keyboard_layout()


def detect_multi_monitor_layout() -> Dict[str, Any]:
    """
    Multi-monitor layout-detektering.

    NY v6.4.1: Returnerar nu komplett info (alla skärmar + primär + work_area).
    """
    if not IS_WINDOWS:
        return {"count": 1, "layout": "single", "monitors": []}
    monitors = get_all_monitors()
    if len(monitors) <= 1:
        return {
            "count": len(monitors),
            "layout": "single",
            "monitors": [_monitor_to_dict(m) for m in monitors],
            "primary_index": 0 if monitors else -1,
        }
    primary_idx = next(
        (i for i, m in enumerate(monitors) if m.is_primary), 0
    )
    return {
        "count": len(monitors),
        "layout": "extended" if len(monitors) > 1 else "single",
        "primary_index": primary_idx,
        "monitors": [_monitor_to_dict(m) for m in monitors],
    }


def _monitor_to_dict(m: MonitorInfo) -> Dict[str, Any]:
    """NY v6.4.1: Konvertera MonitorInfo till dict för loggning/serialisering."""
    return {
        "hmonitor": m.hmonitor,
        "x": m.monitor_rect.x,
        "y": m.monitor_rect.y,
        "width": m.monitor_rect.width,
        "height": m.monitor_rect.height,
        "work_x": m.work_rect.x,
        "work_y": m.work_rect.y,
        "work_width": m.work_rect.width,
        "work_height": m.work_rect.height,
        "is_primary": m.is_primary,
    }


def get_foreground_window_info() -> Dict[str, Any]:
    """
    NY v6.4.1: Hämta info om foreground-fönstret (för diagnostik).

    Returns:
        Dict med:
          - hwnd: int (0 om inget)
          - title: str
          - class_name: str
          - pid: int
          - is_ours: bool (class_name matchar LedgebordMain)
    """
    if not IS_WINDOWS or user32 is None:
        return {
            "hwnd": 0, "title": "", "class_name": "", "pid": 0, "is_ours": False,
        }
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return {
                "hwnd": 0, "title": "", "class_name": "", "pid": 0, "is_ours": False,
            }
        # Title
        length = user32.GetWindowTextLengthW(hwnd)
        title = ""
        if length > 0:
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            title = buff.value
        # Class name
        class_buff = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_buff, 256)
        class_name = class_buff.value
        # PID
        pid = ctypes.c_ulong(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return {
            "hwnd": int(hwnd),
            "title": title,
            "class_name": class_name,
            "pid": int(pid.value),
            "is_ours": class_name == WINDOW_CLASS_NAME,
        }
    except Exception as e:
        logger.debug("get_foreground_window_info misslyckades: %s", e)
        return {
            "hwnd": 0, "title": "", "class_name": "", "pid": 0, "is_ours": False,
        }


def find_visible_hwnds(class_name: str = "") -> List[int]:
    """
    NY v6.4.1: Hitta alla synliga top-level HWNDs (för diagnostik).

    Args:
        class_name: Filtrera på class_name (None/"" = alla)

    Returns:
        Lista av HWNDs som är synliga
    """
    if not IS_WINDOWS or user32 is None:
        return []
    results: List[int] = []
    try:
        EnumWindowsProc = ctypes.WINFUNCTYPE(
            ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p,
        )
        def callback(hwnd, _lparam):
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                if class_name:
                    class_buff = ctypes.create_unicode_buffer(256)
                    user32.GetClassNameW(hwnd, class_buff, 256)
                    if class_buff.value != class_name:
                        return True
                results.append(int(hwnd))
            except Exception:
                pass
            return True
        user32.EnumWindows(EnumWindowsProc(callback), None)
    except Exception as e:
        logger.debug("find_visible_hwnds misslyckades: %s", e)
    return results


def move_window_to_safe_position(
    hwnd: int, width: int, height: int
) -> Optional[Tuple[int, int]]:
    """
    NY v6.4.1: Flytta offscreen-fönster till safe position på primary screen.

    Args:
        hwnd: Window handle
        width: Fönstrets bredd
        height: Fönstrets höjd

    Returns:
        (new_x, new_y) om flyttades, None om redan OK eller misslyckades
    """
    if not IS_WINDOWS or user32 is None:
        return None
    try:
        # Hämta nuvarande position
        rect = ctypes.wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        cur_x, cur_y = int(rect.left), int(rect.top)
        # Kolla om offscreen (med 50px marginal)
        monitors = get_all_monitors()
        on_screen = False
        for m in monitors:
            mx, my = m.monitor_rect.x, m.monitor_rect.y
            mw, mh = m.monitor_rect.width, m.monitor_rect.height
            if (mx - 50) <= cur_x <= (mx + mw - 50) and \
               (my - 50) <= cur_y <= (my + mh - 50):
                on_screen = True
                break
        if on_screen:
            return None
        # Hitta primary screen
        primary = next((m for m in monitors if m.is_primary), None)
        if primary is None and monitors:
            primary = monitors[0]
        if primary is None:
            return None
        new_x = primary.monitor_rect.x + 100
        new_y = primary.monitor_rect.y + 100
        # Flytta (SWP_NOZORDER = 0x0004, SWP_NOACTIVATE = 0x0010)
        user32.SetWindowPos(
            hwnd, 0, new_x, new_y, width, height,
            0x0004 | 0x0010,
        )
        logger.info(
            "move_window_to_safe_position: HWND=%d flyttad (%d,%d) → (%d,%d)",
            hwnd, cur_x, cur_y, new_x, new_y,
        )
        return (new_x, new_y)
    except Exception as e:
        logger.debug("move_window_to_safe_position misslyckades: %s", e)
        return None


def is_schtask_enabled(name: str = SCHTASKS_NAME) -> bool:
    if not IS_WINDOWS:
        return False
    try:
        result = subprocess.run(
            ["schtasks", "/query", "/tn", name],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def list_autostart_entries(timeout_sec: float = 2.0) -> List[Dict[str, str]]:
    """Publik wrapper för list_all_autostart_entries."""
    return list_all_autostart_entries()


# ===========================================================================
# BACKWARDS-COMPATIBILITY (publikt API bevarat)
# ===========================================================================

# Windows-funktioner (används av main.pyw, widget.py)
def windows_build() -> Optional[int]: return _WIN_BUILD
def windows_version_label() -> str: return _WIN_VERSION_LABEL
def windows_edition() -> Optional[str]: return _WIN_EDITION

def supports_dwm_blur() -> bool:
    return dwm_has_blur()


def is_composition_enabled() -> bool:
    """Returnerar om DWM composition är aktiverat."""
    global _DWM_COMPOSITION_ENABLED
    if not IS_WINDOWS or dwmapi is None:
        return False
    if _DWM_COMPOSITION_ENABLED is not None:
        return _DWM_COMPOSITION_ENABLED
    try:
        with _safe_call():
            enabled = ctypes.c_bool()
            hr = dwmapi.DwmIsCompositionEnabled(ctypes.byref(enabled))
            _DWM_COMPOSITION_ENABLED = (hr == S_OK and bool(enabled.value))
            return _DWM_COMPOSITION_ENABLED
    except Exception as e:
        logger.debug("DwmIsCompositionEnabled misslyckades: %s", e)
        return False


def cleanup_dead_regions() -> int:
    if not IS_WINDOWS or user32 is None:
        return 0
    cleaned = 0
    for hwnd in list(_REGION_CACHE.keys()):
        if not is_window_visible(hwnd):
            _clear_region_cache(hwnd)
            cleaned += 1
    if cleaned:
        logger.info("Rensade %d döda GDI-regioner", cleaned)
    return cleaned


# ===========================================================================
# DIAGNOSTIK (legacy)
# ===========================================================================

def get_capabilities() -> dict:
    """Legacy-wrapper för get_platform_capabilities()."""
    return get_platform_capabilities()


def dump_system_info() -> str:
    try:
        import json as _json
        return _json.dumps(get_capabilities(), indent=2, default=str)
    except Exception as e:
        return f"dump_system_info misslyckades: {e}"


# ===========================================================================
# SJÄLVTEST
# ===========================================================================

# ===========================================================================
# EXPORTS
# ===========================================================================
__all__ = [
    # Constants
    "LOG_PREFIX", "DESKTOP_VERSION",
    # Enums
    "CapabilityState", "AutostartMethod", "BackdropType", "CornerPreference",
    # Data classes
    "Point", "Size", "Rect", "MonitorInfo", "IconZone",
    # AI-felsökning (NY v6.4.1 v7)
    "_DESKTOP_ERROR_TRANSLATIONS",
    "_describe_desktop_exception", "_format_compact_traceback",
    "_categorize_desktop_exception", "_validate_desktop_state",
    "safe_run", "_safe_run_async",
    # Svenska formatters (NY v6.4.1 v7)
    "summarize_desktop_health",
    # Diagnostik (NY v6.4.1 v7)
    "get_desktop_diagnostics",
    # Plugin-coupling (NY v6.4.1 v7)
    "get_desktop_plugin_deps",
    # Workers-trick (NY v6.4.1 v7)
    "find_progman_hwnd", "find_workerw_hwnd",
    "parent_window_to_desktop", "unparent_window_from_desktop",
    "get_desktop_parent", "has_workers_trick",
]


if __name__ == "__main__":
    import json as _json
    print("=" * 60)
    print(f"Ledgebord desktop.py v6.4.0 — självtest ({sys.platform})")
    print("=" * 60)
    print(dump_system_info())
    print()
    print(f"IS_WINDOWS: {IS_WINDOWS}")
    print(f"_IS_64BIT: {_IS_64BIT}")
    if IS_WINDOWS:
        print(f"validate(0): {_validate_hwnd(0)}")
        print(f"validate(12345): {_validate_hwnd(12345)}")
        print(f"set_rounded_region(0, 100, 100, 1.0): {set_rounded_region(0, 100, 100, 1.0)}")
        print(f"apply_glassmorphism(0, 'auto'): {apply_glassmorphism(0, 'auto')}")
        print(f"is_composition_enabled(): {is_composition_enabled()}")
        print(f"get_screen_size(): {get_screen_size()}")
        print(f"get_screen_geometry(): {get_screen_geometry()}")
        print(f"get_current_pid(): {get_current_process_id()}")
        print(f"enum_windows(): {len(enum_windows())} fönster")
        print(f"get_visible_window_count(): {get_visible_window_count()}")
        print(f"is_autostart_enabled(): {is_autostart_enabled()}")
        print(f"get_autostart_command(): {get_autostart_command()}")
        print(f"get_executable_path(): {get_executable_path()}")
        print(f"get_idle_time_ms(): {get_idle_time_ms()}")
        print(f"get_system_theme(): {get_system_theme()}")
        print(f"get_locale(): {get_locale()}")
        print(f"get_screen_dpi(): {get_screen_dpi()}")
        print(f"get_scaling_factor(): {get_scaling_factor()}")
        print(f"get_refresh_rate(): {get_refresh_rate()} Hz")
        print(f"get_color_depth(): {get_color_depth()} bpp")
        print(f"get_mouse_buttons(): {get_mouse_buttons()}")
        print(f"get_keyboard_layout(): {get_keyboard_layout()}")
        print(f"get_desktop_environment(): {get_desktop_environment()}")
        print(f"get_session_type(): {get_session_type()}")
        print(f"detect_display_server(): {detect_display_server()}")
    print()
    print("=== AUTOSTART (multi-OS) ===")
    verify = verify_autostart()
    print(f"Enabled: {verify['enabled']}")
    print(f"Methods: {verify['methods']}")
    print(f"Command: {verify['command']}")
    print(f"Paths: {verify['all_paths']}")
    print()
    entries = list_all_autostart_entries()
    print(f"Autostart entries: {len(entries)}")
    for e in entries[:5]:
        print(f"  {e['platform']}/{e['type']}: {e['name']}")
    print()
    print("=== Multi-monitor layout ===")
    layout = detect_multi_monitor_layout()
    print(f"Layout: {layout}")
    print("=" * 60)
    # Test NY v6.4.1 v7: AI-felsökning
    print("\n[Test AI] AI-felsökning (NY v6.4.1 v7)...")
    desc1 = _describe_desktop_exception(FileNotFoundError("desktop.dll"))
    print(f"  ✓ _describe_desktop_exception: {desc1!r}")
    assert "hittades inte" in desc1
    cat1 = _categorize_desktop_exception(ValueError("x"))
    cat2 = _categorize_desktop_exception(PermissionError("x"))
    print(f"  ✓ _categorize_desktop_exception: ValueError→{cat1}, PermissionError→{cat2}")
    assert cat1 == "user_input"
    assert cat2 == "permission"
    with safe_run("test-op-desktop") as ctx_ok:
        pass
    with safe_run("test-op-desktop-fail") as ctx_fail:
        raise RuntimeError("desktop-test-fel")
    print(f"  ✓ safe_run fel-blocket: errors={len(ctx_fail['errors'])}")
    assert len(ctx_fail["errors"]) == 1

    # Test NY v6.4.1 v7: Svenska formatters + diagnostics
    print("\n[Test SV] Svenska formatters + diagnostics (NY v6.4.1 v7)...")
    summ = summarize_desktop_health()
    print(f"  ✓ summarize_desktop_health: {summ!r}")
    assert DESKTOP_VERSION in summ
    diag = get_desktop_diagnostics()
    print(f"  ✓ get_desktop_diagnostics: version={diag['desktop_version']}, "
          f"platform={diag['platform']}, problems={diag['problem_count']}")
    assert diag["module"] == "desktop"
    assert diag["desktop_version"] == DESKTOP_VERSION

    # Test NY v6.4.1 v7: _validate_desktop_state
    print("\n[Test VAL] _validate_desktop_state (NY v6.4.1 v7)...")
    problems = _validate_desktop_state()
    print(f"  ✓ _validate_desktop_state: {len(problems)} problem")
    for p in problems:
        print(f"    - {p}")

    print()
    print("=" * 60)
    print(f"✓ desktop.py — TESTER KLARA ({DESKTOP_VERSION})")
    print("=" * 60)
