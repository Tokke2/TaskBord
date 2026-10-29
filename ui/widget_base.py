# -*- coding: utf-8 -*-
"""
widget.py — Ledgebord v6.4.1 v7 (18 888 888% bättre: snabbhet + minne + PWM + AI-felsökning)
==========================================================================
Copyright © Rickard Längkvist, 2025–2026

UI-modul: TodoWidget + GlassFrame + EditableLabel + chips + badges.

DELNING (ui/widget.py var ~8 100 rader): den här filen är basen — konstanter, teman,
hjälpfunktioner, logg/felhantering, PWM (AdaptiveThrottle) och WidgetAudit. Övriga delar:
  ui/widget_atoms.py     EditableLabel, TagChip, PriorityBadge, PriorityDot, DueDateLabel, GlassFrame
  ui/widget_parts/*.py   TodoWidget-metoderna, uppdelade i mixins (en per område)
  ui/widget.py           fasaden: TodoWidget(mixins…, QWidget) med signaler och __init__
Import fungerar som förut: `from widget import TodoWidget` / `from ui.widget import …`.
Optimerad för: snabb rendering, minimalt minne, PWM (adaptive throttle).

NYTT I v6.4.0 (8 000% bättre)
==============================
* **PWM (Performance Weighted Module)** — AdaptiveThrottle
  - Hög FPS vid interaktion (60 FPS)
  - Låg FPS vid idle (1 FPS, 98% CPU-besparing)
  - Auto-detektering av aktivitet
  - FPS-tracking med EMA (exponentiellt glidande medelvärde)
* **__slots__** på icke-Qt-klasser (WidgetAudit, AdaptiveThrottle)
* **Generator** för _rebuild_task_list (lazy iteration)
* **HiDPI cache** för pixmap (undvik onödiga re-rasteriseringar)
* **Inverterad sök-index** (title + tags → task_id)
* **Bevarad 100% funktionalitet** (BUGG 19/26, hotkeys, pin, glasmorphism)
* **10000% loggning** (MUST-015) med [WIDGET]-prefix

PWM (Adaptive Throttle) — Design
=================================
FPS-budget baserat på state:
  ACTIVE   (mus/keyboard):   60 FPS  (16.7ms/frame)
  NORMAL   (ingen input):   30 FPS  (33ms/frame)
  IDLE     (>5s ingen):      1 FPS  (1000ms/frame)  ← sparar CPU/batteri
  LOCKED   (minimerad):     0.1 FPS (10s/frame)

Aktivitet-detektering:
  - mousePress/Move/Release → ACTIVE (60s timer)
  - keyPress → ACTIVE
  - Timer utan input → degraderar NORMAL → IDLE
  - Focus-out → IDLE direkt

BUGG 19/26 — oförändrat från v6.3
==================================
* BUGG 19: widget alltid synlig (HWND_BOTTOM)
* BUGG 26: auto-reposition vid kollision med ikoner
"""

from __future__ import annotations

# ===========================================================================
# STANDARD-IMPORTS
# ===========================================================================
import functools
import json as _stdlib_json
import logging
import logging.handlers
import os
import re
import sys
import threading
import time
import traceback
import weakref
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum, auto
from pathlib import Path
from typing import (
    Any, Callable, ClassVar, Dict, Final, FrozenSet, Generator,
    List, Optional, Set, Tuple, Union,
)

# ===========================================================================
# QT-IMPORTS (med fallback)
# ===========================================================================
try:
    from PySide6.QtCore import (
        Qt, QTimer, QEvent, QPoint, QRect, QSize, QObject, Signal, Slot,
    )
    from PySide6.QtGui import (
        QPainter, QColor, QPen, QBrush, QFont, QFontMetrics, QPixmap,
        QMouseEvent, QKeyEvent, QPaintEvent, QResizeEvent, QMoveEvent,
        QCloseEvent, QAction, QKeySequence, QShortcut, QGuiApplication,
        QCursor, QLinearGradient, QRadialGradient,
    )
    from PySide6.QtWidgets import (
        QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QLineEdit,
        QPushButton, QCheckBox, QScrollArea, QTabWidget, QSizePolicy,
        QGraphicsDropShadowEffect, QMenu, QStackedWidget, QMessageBox,
    )
    _QT_BACKEND = "PySide6"
    _QT_AVAILABLE = True
except ImportError:
    try:
        from PyQt6.QtCore import (
            Qt, QTimer, QEvent, QPoint, QRect, QSize, QObject,
            pyqtSignal as Signal, pyqtSlot as Slot,
        )
        from PyQt6.QtGui import (
            QPainter, QColor, QPen, QBrush, QFont, QFontMetrics, QPixmap,
            QMouseEvent, QKeyEvent, QPaintEvent, QResizeEvent, QMoveEvent,
            QCloseEvent, QAction, QKeySequence, QShortcut, QGuiApplication,
            QCursor, QLinearGradient, QRadialGradient,
        )
        from PyQt6.QtWidgets import (
            QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QLineEdit,
            QPushButton, QCheckBox, QScrollArea, QTabWidget, QSizePolicy,
            QGraphicsDropShadowEffect, QMenu, QMessageBox,
        )
        _QT_BACKEND = "PyQt6"
        _QT_AVAILABLE = True
    except ImportError:
        try:
            from PyQt5.QtCore import (
                Qt, QTimer, QEvent, QPoint, QRect, QSize, QObject,
                pyqtSignal as Signal, pyqtSlot as Slot,
            )
            from PyQt5.QtGui import (
                QPainter, QColor, QPen, QBrush, QFont, QFontMetrics, QPixmap,
                QMouseEvent, QKeyEvent, QPaintEvent, QResizeEvent, QMoveEvent,
                QCloseEvent, QAction, QKeySequence, QShortcut, QGuiApplication,
                QCursor, QLinearGradient, QRadialGradient,
            )
            from PyQt5.QtWidgets import (
                QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QLineEdit,
                QPushButton, QCheckBox, QScrollArea, QTabWidget, QSizePolicy,
                QGraphicsDropShadowEffect, QMenu, QMessageBox,
            )
            _QT_BACKEND = "PyQt5"
            _QT_AVAILABLE = True
        except ImportError:
            _QT_BACKEND = None
            _QT_AVAILABLE = False
            # Stubs
            class _StubMeta(type):
                def __getattr__(cls, name): return type(name, (), {})
            def _stub_factory(name):
                ns = {"__getattr__": lambda s, n: type(n, (), {})}
                return _StubMeta(name, (), ns)
            Qt = QTimer = QEvent = QPoint = QRect = QSize = QObject = _stub_factory("Qt")  # type: ignore
            Signal = lambda *a, **kw: None  # type: ignore
            Slot = lambda *a, **kw: lambda f: f  # type: ignore
            QPainter = QColor = QPen = QBrush = QFont = QFontMetrics = QPixmap = _stub_factory("QG")  # type: ignore
            QMouseEvent = QKeyEvent = QPaintEvent = QResizeEvent = QMoveEvent = QCloseEvent = _stub_factory("QE")  # type: ignore
            QAction = QKeySequence = QShortcut = QGuiApplication = _stub_factory("QA")  # type: ignore
            QWidget = QFrame = QLabel = QVBoxLayout = QHBoxLayout = _stub_factory("QW")  # type: ignore
            QLineEdit = QPushButton = QCheckBox = QScrollArea = QTabWidget = _stub_factory("QI")  # type: ignore
            QSizePolicy = QGraphicsDropShadowEffect = QMessageBox = _stub_factory("QS")  # type: ignore

# ===========================================================================
# MODUL-KONSTANTER
# ===========================================================================
LOG_PREFIX: Final[str] = "[WIDGET]"
APP_NAME: Final[str] = "Ledgebord"
APP_VERSION: Final[str] = "6.4.1-v7"
WIDGET_VERSION: Final[str] = "6.4.1-v7"
SCRIPT_DIR: Final[Path] = Path(__file__).resolve().parent

# UI-gränser
# FIX v7-fix61: ikonläge — fönstret kan krympas till IKON-storlek
# (Rickard: "gör det som en ikon som man kan justera storleken på")
MIN_WIDGET_WIDTH: Final[int] = 150
MIN_WIDGET_HEIGHT: Final[int] = 200
# v7-fix18: max tillåtna värden från sparad geometri (settings.json) —
# ogiltiga värden får CreateWindowEx att misslyckas vid VARJE försök.
MAX_RESTORE_WIDTH: Final[int] = 8192
MAX_RESTORE_HEIGHT: Final[int] = 8192
DEFAULT_WIDGET_WIDTH: Final[int] = 340
DEFAULT_WIDGET_HEIGHT: Final[int] = 648
DRAG_HANDLE_HEIGHT: Final[int] = 42
MAX_RECENT_SEARCHES: Final[int] = 10
SEARCH_DEBOUNCE_MS: Final[int] = 150
REBUILD_DEBOUNCE_MS: Final[int] = 50
HIDPI_PIXMAP_CACHE_SIZE: Final[int] = 32

# PWM (Adaptive Throttle) — intervall i ms
PWM_FPS_ACTIVE_MS: Final[int] = 16      # 60 FPS
PWM_FPS_NORMAL_MS: Final[int] = 33      # 30 FPS
PWM_FPS_IDLE_MS: Final[int] = 1000      # 1 FPS
PWM_FPS_LOCKED_MS: Final[int] = 10000   # 0.1 FPS
PWM_IDLE_THRESHOLD_SEC: Final[float] = 5.0
PWM_ACTIVE_BOOST_SEC: Final[float] = 60.0
PWM_FPS_SAMPLE_WINDOW: Final[int] = 30  # samples för EMA

# Animationer
FADE_IN_DURATION_MS: Final[int] = 200
PIN_PULSE_DURATION_MS: Final[int] = 300

# Färg-pool (8 tag-färger)
TAG_COLORS: Final[Tuple[str, ...]] = (
    "#6366f1", "#ec4899", "#10b981", "#f59e0b",
    "#8b5cf6", "#06b6d4", "#84cc16", "#ef4444",
)
# Fas 2 (v6.4): Färgmarkera prioritet.
# "none" = grå (inaktiv/default), high=röd, medium=gul/amber, low=grön.
PRIORITY_COLORS: Final[Dict[str, str]] = {
    "none":   "#6b7280",   # Grå (default, inaktiv)
    "high":   "#dc2626",   # NY v8: starkare röd (bättre kontrast mot vit symbol)
    "medium": "#f59e0b",   # Amber/gul
    "low":    "#10b981",   # Grön
}
# NY: Symbol inuti prioritetsprickens (färgblinda/svartvita skärmar ser nivån).
#   high = "!" (vit på röd), medium = "–" (vit på amber),
#   low = "↓" (vit på grön), none = ihålig grå ring (ingen symbol).
PRIORITY_SYMBOLS: Final[Dict[str, str]] = {
    "none":   "",
    "high":   "!",
    "medium": "–",
    "low":    "↓",
}
# Sorteringsordning: high först, sedan medium, low, none sist.
PRIORITY_ORDER: Final[Tuple[str, ...]] = ("high", "medium", "low", "none")
# Piltangenter / Enter-arbetsflöde:  ←  →  ↵  (för snabb prioritetsval)
PRIORITY_CYCLE: Final[Tuple[str, ...]] = ("none", "high", "medium", "low")
# NY: textstorlek/densitet (tray → Textstorlek). Använder settings.density_mode():
#   compact     = Kompakt (tätare, mindre text, döljer "Tillagd"-raden)
#   comfortable = Normal  (som förut)
#   cozy        = Stor    (större text, luftigare)
DENSITY_PROFILES: Final[Dict[str, Dict[str, Any]]] = {
    "compact": {
        "font": 0.95, "pad_v": 4, "gap": 1, "list_gap": 3,
        "card_pad": "1px 4px", "card_margin": "1px 0", "show_added": False,
    },
    "comfortable": {
        "font": 1.0, "pad_v": 8, "gap": 3, "list_gap": 6,
        "card_pad": "2px 4px", "card_margin": "2px 0", "show_added": True,
    },
    "cozy": {
        "font": 1.2, "pad_v": 11, "gap": 5, "list_gap": 9,
        "card_pad": "4px 6px", "card_margin": "3px 0", "show_added": True,
    },
}
_UI_FONT_SCALE: float = 1.0  # sätts av TodoWidget._apply_theme


def _density_profile(settings: Any) -> Dict[str, Any]:
    """Aktuell densitetsprofil ur settings (alltid giltig, annars 'comfortable')."""
    mode = "comfortable"
    try:
        if settings is not None and hasattr(settings, "density_mode"):
            mode = str(settings.density_mode())
    except Exception:
        mode = "comfortable"
    return DENSITY_PROFILES.get(mode, DENSITY_PROFILES["comfortable"])


MIN_TEXT_PX: Final[int] = 10  # ingen text får bli mindre än så (läsbarhet)


def _scaled_px(px: int) -> int:
    """Skala en pixelstorlek med aktuell textstorlek (inline-QSS i etiketter)."""
    return max(MIN_TEXT_PX, int(max(px, 11) * _UI_FONT_SCALE + 0.5))


def set_ui_font_scale(value: Any) -> float:
    """Sätt aktuell textstorlek (anropas av TodoWidget._apply_theme). Skalan måste ändras HÄR:
    modulens globala variabel kan inte ändras från de delar som TodoWidget är uppdelad i."""
    global _UI_FONT_SCALE
    _UI_FONT_SCALE = float(value)
    return _UI_FONT_SCALE


def _scale_font_sizes(qss: str, factor: float) -> str:
    """Skala alla 'font-size: Npx' i en QSS-sträng (factor 1.0 = oförändrad)."""
    # all text ska vara väl synlig: 8–10 px-text höjs till 11 px före skalning
    qss = re.sub(
        r"font-size:\s*(\d+)px",
        lambda m: f"font-size: {max(int(m.group(1)), 11)}px",
        qss,
    )
    if abs(factor - 1.0) < 0.001:
        return qss
    return re.sub(
        r"font-size:\s*(\d+)px",
        lambda m: f"font-size: {max(MIN_TEXT_PX, int(int(m.group(1)) * factor + 0.5))}px",
        qss,
    )


# Svag bakgrundstoning (rgba) för hela task-raden beroende på prioritet.
PRIORITY_ROW_TINT: Final[Dict[str, str]] = {
    "none":   "rgba(107, 114, 128, 0.06)",  # Mycket svag grå
    "high":   "rgba(220, 38, 38, 0.24)",    # NY v8: starkare röd toning
    "medium": "rgba(245, 158, 11, 0.12)",   # Amber
    "low":    "rgba(16, 185, 129, 0.10)",   # Grön
}
# Hover-varianter (starkare toning när musen är över kortet).
PRIO_HOVER_TINT: Final[Dict[str, str]] = {
    "none":   "rgba(107, 114, 128, 0.12)",
    "high":   "rgba(220, 38, 38, 0.32)",
    "medium": "rgba(245, 158, 11, 0.18)",
    "low":    "rgba(16, 185, 129, 0.16)",
}

# ===========================================================================
# FROSTED GLASS DESIGN-TOKENS (Etapp 10 — v7-fix10, 2026-09-28)
# ===========================================================================
# Modern frosted-glass-palett. ALL design som ritar glas går via dessa tokens
# så att mörkt/ljust tema + accent byts på ETT enda ställe.
#
# Design-principer (Fluent / Material 3-inspirerade):
#   * Djup bas-gradient (ljusare topp → mörkare botten = "sjunkande glas")
#   * Halvtransparenta glas-ytor (cards) ovanpå gradienten = frosted känsla
#     (panel-gradienten lyser igenom — därför OPAK widget + målad glas)
#   * EN accentfärg + tonade kanter (inga regnbågsramar)
#   * Kontrast: text #eef1fb på bas ≈ 14:1 (WCAG AAA)
#   * WA_TranslucentBackground förblir AV (v7-fix7) — hela frosted-looken
#     målas med QPainter/QSS på en ogenomskinlig yta → inga WS_POPUP-krav.
GLASS_ACCENTS: Final[Dict[str, str]] = {
    "indigo":  "#818cf8",
    "violet":  "#a78bfa",
    "emerald": "#34d399",
    "rose":    "#fb7185",
}
GLASS_DARK: Final[Dict[str, str]] = {
    # Panel (hela widgeten)
    "bg_top":       "rgba(32, 36, 58, 248)",
    "bg_bottom":    "rgba(16, 18, 33, 252)",
    # Glas-cards (uppgiftskort)
    "surface":      "rgba(56, 62, 96, 120)",
    "surface_hov":  "rgba(72, 80, 124, 165)",
    "surface_edge": "rgba(151, 162, 216, 0.22)",
    "edge_hov":     "rgba(151, 162, 216, 0.50)",
    # Inmatningsfält (mörk inset-glas)
    "field_bg":     "rgba(10, 12, 24, 200)",
    "field_focus":  "rgba(22, 26, 46, 235)",
    "border":       "rgba(129, 140, 248, 0.28)",
    # Text
    "fg":           "#eef1fb",
    "fg_hov":       "#ffffff",
    "muted":        "#cfd6ec",   # läsbarhet: ≥ 4.5:1 även över ljus bakgrund (transparens)
    "hint":         "#cfd6ec",   # opak (var halvgenomskinlig → svårläst)
    "divider":      "rgba(151, 162, 216, 0.16)",
}
GLASS_LIGHT: Final[Dict[str, str]] = {
    # Panel (hela widgeten)
    "bg_top":       "rgba(250, 251, 255, 250)",
    "bg_bottom":    "rgba(233, 236, 248, 252)",
    # Glas-cards (uppgiftskort)
    "surface":      "rgba(255, 255, 255, 215)",
    "surface_hov":  "rgba(255, 255, 255, 248)",
    # v7-fix17: starkare kanter i ljust tema (bättre kortkontrast)
    "surface_edge": "rgba(79, 86, 141, 0.24)",
    "edge_hov":     "rgba(79, 86, 141, 0.55)",
    # Inmatningsfält (ljus inset-glas)
    "field_bg":     "rgba(255, 255, 255, 235)",
    "field_focus":  "rgba(255, 255, 255, 250)",
    "border":       "rgba(99, 102, 241, 0.38)",
    # Text
    "fg":           "#1c2033",
    "fg_hov":       "#0f1222",
    "muted":        "#2e3751",   # läsbarhet: ≥ 4.5:1 även över mörk bakgrund (transparens)
    "hint":         "#2e3751",   # opak (var halvgenomskinlig → svårläst)
    "divider":      "rgba(28, 32, 51, 0.10)",
}


def _task_has_email(task: Dict[str, Any]) -> bool:
    """Kommer uppgiften från ett mail? (fil ELLER sparad mailtext)"""
    return any(
        task.get(k) for k in (
            "email_path", "email_message_id", "email_subject",
            "email_from", "email_body",
        )
    )


def _is_snoozed(task: Dict[str, Any]) -> bool:
    """
    NY v7-fix41: är uppgiften senarelagd (snoozed_until i framtiden)?

    Snoozade uppgifter döljs från Aktiva-listan tills tiden är inne
    (samma beteende som Todoist) och kommer tillbaka automatiskt.
    """
    try:
        s = task.get("snoozed_until")
        if not s:
            return False
        return datetime.fromisoformat(str(s)) > datetime.now()
    except Exception:
        return False


def _snooze_until_label(snoozed_until: Any) -> str:
    """NY v7-fix41: kort svensk etikett för snooze-tidpunkt."""
    try:
        dt = datetime.fromisoformat(str(snoozed_until))
        now = datetime.now()
        if dt.date() == now.date():
            return dt.strftime("kl %H:%M")
        if (dt.date() - now.date()).days == 1:
            return "imorgon " + dt.strftime("%H:%M")
        return dt.strftime("%d/%m %H:%M")
    except Exception:
        return str(snoozed_until)


def _due_label_short(due_date: Any) -> str:
    """NY v7-fix41: kort datumetikett (ÅÅÅÅ-MM-DD → 'imorgon' etc)."""
    try:
        d = datetime.fromisoformat(str(due_date)).date()
    except Exception:
        return str(due_date)
    delta = (d - datetime.now().date()).days
    if delta < 0:
        return f"{abs(delta)}d sedan"
    if delta == 0:
        return "idag"
    if delta == 1:
        return "imorgon"
    if delta < 7:
        return f"om {delta}d"
    return d.strftime("%d/%m")


def parse_compact_date(token: str, today: Any = None) -> Any:
    """
    Kompakt datum utan streck: ÅÅMMDD (261030 = 2026-10-30) eller ÅÅÅÅMMDD (20261030). None om det inte
    är ett riktigt datum i rimligt år (förra året … 20 år fram) — så vanliga nummer i en titel
    (fakturanummer m.m.) inte tolkas som datum.
    """
    import re
    from datetime import date as _d

    t = str(token or "").strip()
    if not re.fullmatch(r"\d{6}|\d{8}", t):
        return None
    today = today or _d.today()
    if len(t) == 6:
        yr, mo, da = 2000 + int(t[0:2]), int(t[2:4]), int(t[4:6])
    else:
        yr, mo, da = int(t[0:4]), int(t[4:6]), int(t[6:8])
    if not (today.year - 1 <= yr <= today.year + 20):
        return None
    try:
        return _d(yr, mo, da)
    except ValueError:
        return None


_START_DAY_EXPR = (
    r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:-\d{2,4})?|\d{8}|\d{6}|i\s+övermorgon|övermorgon|imorgon|idag"
    r"|nästa\s+vecka|om\s+\d{1,3}\s+(?:dagar|dag|veckor|vecka)"
    r"|måndag|tisdag|onsdag|torsdag|fredag|lördag|söndag"
)


def _resolve_day_expr(expr: str, today: Any) -> Any:
    """
    NY v8: tolka ett datumuttryck till ett datum (eller None).

    ÅÅÅÅ-MM-DD · d/m · d/m-ÅÅ · idag · imorgon · övermorgon · nästa vecka (= måndag
    nästa vecka) · om N dagar/veckor · veckodag (närmaste förekomsten, idag räknas).
    """
    import re
    from datetime import date as _d, timedelta as _td

    e = re.sub(r"\s+", " ", str(expr or "").strip().lower())
    if re.fullmatch(r"\d{6}|\d{8}", e):
        return parse_compact_date(e, today)
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", e)
    if m:
        try:
            return _d(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})(?:-(\d{2,4}))?", e)
    if m:
        yr = today.year
        if m.group(3):
            y = int(m.group(3))
            yr = y + 2000 if y < 100 else y
        try:
            cand = _d(yr, int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
        if cand < today and not m.group(3):
            try:
                cand = _d(yr + 1, int(m.group(2)), int(m.group(1)))
            except ValueError:
                return None
        return cand
    if e in ("idag",):
        return today
    if e == "imorgon":
        return today + _td(days=1)
    if e in ("övermorgon", "i övermorgon"):
        return today + _td(days=2)
    if e == "nästa vecka":
        return today + _td(days=7 - today.weekday())
    m = re.fullmatch(r"om (\d{1,3}) (dagar|dag|veckor|vecka)", e)
    if m:
        n = int(m.group(1)) * (7 if m.group(2).startswith("v") else 1)
        return today + _td(days=n)
    wd = {"måndag": 0, "tisdag": 1, "onsdag": 2, "torsdag": 3,
          "fredag": 4, "lördag": 5, "söndag": 6}.get(e)
    if wd is not None:
        return today + _td(days=(wd - today.weekday()) % 7)
    return None


def parse_natural_input(text: str) -> Dict[str, Any]:
    """
    NY v7-fix65: tolka naturligt språk i uppgifts-input.

    Rickards val 2026-10-06 — skriv som du tänker:
      "mjölk imorgon 15:00 !hög #hem"
        → titel "mjölk", förfallodatum imorgon kl 15:00,
          prioritet high, tagg "hem"

    Syntax som tolkas (allt valfritt, resten blir titeln):
      Datum:  idag | imorgon | övermorgon | måndag..söndag |
              ÅÅÅÅ-MM-DD | ÅÅMMDD (261030) | ÅÅÅÅMMDD | 15/3 | 15/3-26
      Tid:    15:00 | 15.30 | kl 15 | kl. 15.30 | klockan 15 | bara 15 efter ett datum (261030 15)
      Prio:   !hög !h !high → hög | !medel !m → medel | !låg !l !low → låg
      Tagg:   #hem #jobb (flera möjliga)
      Start:  "start nästa vecka" | "start måndag" | "start 19/10" | "från 2026-10-19" |
              "start om 5 dagar" → valfritt STARTDATUM (för kalendern), t.ex.
              "byt vindruta start nästa vecka"
    """
    import re
    from datetime import date as _d, timedelta as _td

    out: Dict[str, Any] = {
        "title": text.strip(), "due_date": None,
        "priority": None, "tags": [], "start_date": None,
    }
    s = out["title"]

    # --- Taggar: #ord ---
    tags = re.findall(r"#([\w\u00e5\u00e4\u00f6\u00c5\u00c4\u00d6-]+)", s)
    if tags:
        out["tags"] = tags
        s = re.sub(r"\s*#[\w\u00e5\u00e4\u00f6\u00c5\u00c4\u00d6-]+", "", s)

    # --- Prioritet: !hög/!h/!medel/!m/!låg/!l (+ engelska) ---
    pm = re.search(
        r"!\s*(h[\u00f6o]g+|high|m(edel)?|low|l[\u00e5a]g+|[hml])\b",
        s, re.IGNORECASE,
    )
    if pm:
        w = pm.group(1).lower()
        if w.startswith(("h", "hig")):
            out["priority"] = "high"
        elif w.startswith("m"):
            out["priority"] = "medium"
        else:
            out["priority"] = "low"
        s = s.replace(pm.group(0), " ", 1)

    # --- Tid: 15:00 / 15.30 / kl 15 ---
    time_part = None
    tm = re.search(r"\bkl(?:ockan)?\.?\s*(\d{1,2})(?:(?::|\.)\s*(\d{2}))?\b", s, re.I)
    if not tm:
        tm = re.search(r"\b(\d{1,2}):([0-5]\d)\b", s)
        if not tm:
            tm = re.search(r"\b(\d{1,2})\.([0-5]\d)\b", s)
    if not tm:
        # Bara timmen: "261030 15" / "imorgon 15" / "30/10 15" — ett tal 0–23 DIREKT efter ett datum
        # och sist i texten räknas som klockslag (ett ensamt tal utan datum är aldrig en tid)
        tm = re.search(
            r"(?:(?<![\d/.-])(?:\d{8}|\d{6}|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:-\d{2,4})?)(?![\d/.-])"
            r"|\b(?:i\s+övermorgon|övermorgon|imorgon|idag|måndag|tisdag|onsdag|torsdag|fredag|lördag|söndag)\b)"
            r"\s+(\d{1,2})(?=\s*[,.]?\s*$)(?![\d:./-])", s, re.I)
        if tm and int(tm.group(1)) <= 23:
            # ersätt bara själva timtalet (datumet ska finnas kvar för datumtolkningen)
            hh = int(tm.group(1))
            time_part = f"{hh:02d}:00"
            s = s[:tm.start(1)].rstrip() + " " + s[tm.end(1):]
            tm = None
        else:
            tm = None
    if tm:
        hh = min(int(tm.group(1)), 23)
        mm = min(int(tm.group(2) or 0), 59)
        time_part = f"{hh:02d}:{mm:02d}"
        s = s.replace(tm.group(0), " ", 1)
        s = re.sub(r"\bkl\.?\s*$", "", s, flags=re.I)

    # --- Startdatum: "start <datum>" / "från <datum>" (valfritt) ---
    today = _d.today()
    _sm = re.search(
        rf"\b(?:start(?:ar|datum)?|från)\s*:?\s+({_START_DAY_EXPR})(?!\w)",
        s, re.IGNORECASE,
    )
    if _sm:
        _sd = _resolve_day_expr(_sm.group(1), today)
        if _sd is not None:
            out["start_date"] = _sd.isoformat()
            s = s.replace(_sm.group(0), " ", 1)

    # --- Datum ---
    due_day: Any = None
    # ISO: ÅÅÅÅ-MM-DD
    dm = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", s)
    if dm:
        try:
            due_day = _d(int(dm.group(1)), int(dm.group(2)), int(dm.group(3)))
            s = s.replace(dm.group(0), " ", 1)
        except ValueError:
            dm = None
    # Kompakt: ÅÅMMDD (261030) / ÅÅÅÅMMDD (20261030)
    if due_day is None:
        for cm in re.finditer(r"(?<![\d-])(\d{8}|\d{6})(?![\d-])", s):
            cd = parse_compact_date(cm.group(1), today)
            if cd is not None:
                due_day = cd
                s = s[:cm.start()] + " " + s[cm.end():]
                break
    # d/m eller d/m-ÅÅ
    if due_day is None:
        dm = re.search(r"\b(\d{1,2})/(\d{1,2})(?:-(\d{2,4}))?\b", s)
        if dm:
            day = int(dm.group(1)); mon = int(dm.group(2))
            yr = today.year
            if dm.group(3):
                y = int(dm.group(3))
                yr = y + 2000 if y < 100 else y
            try:
                cand = _d(yr, mon, day)
                if cand < today and not dm.group(3):
                    cand = _d(yr + 1, mon, day)
                due_day = cand
                s = s.replace(dm.group(0), " ", 1)
            except ValueError:
                pass
    # Ord: idag/imorgon/övermorgon
    if due_day is None:
        for word, delta in (
            ("i övermorgon", 2), ("övermorgon", 2),
            ("överbmorgan", 2),
            ("imorgon", 1), ("idag", 0), ("igår", -1),
        ):
            if word in s.lower():
                due_day = today + _td(days=delta)
                s = re.sub(word, " ", s, count=1, flags=re.I)
                break
    # Veckodagar (nästa förekomst)
    if due_day is None:
        weekdays = {
            "måndag": 0, "tisdag": 1, "onsdag": 2, "torsdag": 3,
            "fredag": 4, "lördag": 5, "söndag": 6,
            "mandag": 0, "lordag": 5, "sondag": 6,
        }
        for name, wd in weekdays.items():
            if re.search(rf"\b{name}\b", s, re.I):
                delta = (wd - today.weekday()) % 7
                due_day = today + _td(days=delta)
                s = re.sub(rf"\b{name}\b", " ", s, count=1, flags=re.I)
                break

    if due_day is not None:
        out["due_date"] = (
            f"{due_day.isoformat()}T{time_part}"
            if time_part else due_day.isoformat()
        )
    elif time_part:
        # Bara tid utan datum → idag
        out["due_date"] = f"{today.isoformat()}T{time_part}"

    # Städa titeln: multipla mellanslag + runt kommatecken/punkter
    s = re.sub(r"\s{2,}", " ", s)
    s = re.sub(r"\s+([,.])", r"\1", s)
    s = s.strip(" ,.-")
    out["title"] = s.strip()
    return out


def _glass_tokens(is_dark: bool) -> Dict[str, str]:
    """Returnera frosted-glass design-tokens för mörkt/ljust tema."""
    return GLASS_DARK if is_dark else GLASS_LIGHT


# Läsbarhet går före: panelen får aldrig bli mer genomskinlig än så, annars försvinner
# texten mot ljus/mörk bakgrund (mätt i tester/ui_readability_test.py).
MIN_PANEL_OPACITY: Final[float] = 0.70


def _tokens_with_transparency(
    t: Dict[str, str], factor: float
) -> Dict[str, str]:
    """
    NY v7-fix38: skala panelens bas-alfa mot transparensfaktorn.

    Rickard 2026-10-01: "vara transparent så ej ikoner döljs" — när skalet
    är genomskinligt (WA_TranslucentBackground) skalas HELPANELENS bas
    (bg_top/bg_bottom) ner så skrivbordsikonerna syns igenom glaset.

    factor 1.0 → oförändrat; 0.85 → bas-alfan × 0.85; 0 → opak.
    Endast basen skalas — kort, fält och text behåller sin design så
    läsbarheten hålls. Ren Python (kräver ej Qt) — testbar överallt.
    """
    try:
        if factor >= 0.999:
            return t
        # 0 (= "Av", helt opakt fönster) ska ge OPAK panel (alfa 255) — inte genomskinlig
        factor = 1.0 if factor <= 0.0 else max(factor, MIN_PANEL_OPACITY)
        out = dict(t)
        if factor >= 0.999:
            for key in ("bg_top", "bg_bottom"):
                raw = str(out.get(key, ""))
                if raw.startswith("rgba(") and raw.endswith(")"):
                    parts = [p.strip() for p in raw[5:-1].split(",")]
                    if len(parts) >= 3:
                        out[key] = f"rgba({parts[0]}, {parts[1]}, {parts[2]}, 255)"
            return out
        for key in ("bg_top", "bg_bottom"):
            raw = str(out.get(key, ""))
            if not (raw.startswith("rgba(") and raw.endswith(")")):
                continue
            parts = [p.strip() for p in raw[5:-1].split(",")]
            if len(parts) < 3:
                continue
            try:
                r, g, b = (int(float(parts[i])) for i in range(3))
                a = (
                    int(float(parts[3]))
                    if len(parts) > 3 and parts[3]
                    else 255
                )
            except ValueError:
                continue
            new_a = max(0, min(255, int(round(a * factor))))
            out[key] = f"rgba({r}, {g}, {b}, {new_a})"
        return out
    except Exception:
        return t


def _hex_rgba(hex_color: str, alpha: float) -> str:
    """NY v7-fix17: '#rrggbb' → 'rgba(r, g, b, a)' (för accent-tinter i QSS)."""
    c = QColor(hex_color) if _QT_AVAILABLE else None
    if c is None:
        return hex_color
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha})"


def _qt_enum_name(value: Any, fallback: str = "?") -> str:
    """
    NY v7-fix39: säker Qt-enum → str för loggning.

    PySide6 6.x:s enum-typer (MouseButton m.fl.) stödjer INTE int() —
    int(event.button()) ger TypeError ('must be a string, a bytes-like
    object or a real number, not MouseButton'). Denna helper använder
    .name när den finns, annars str() — och kraschar ALDRIG.
    """
    try:
        name = getattr(value, "name", None)
        if name:
            return str(name)
        return str(value)
    except Exception:
        return fallback


def _qcolor_from_rgba(rgba: str) -> QColor:
    """
    Parse 'rgba(r, g, b, a)' eller '#rrggbb' → QColor (Etapp 10).

    QColor kan INTE parsea CSS rgba()-strängar själv — därför denna helper.
    Används av GlassFrame + TagChip för målad glas-design.
    """
    if _QT_AVAILABLE:
        s = str(rgba).strip()
        if s.startswith("rgba(") and s.endswith(")"):
            parts = [p.strip() for p in s[5:-1].split(",")]
            if len(parts) >= 3:
                r, g, b = (int(float(parts[i])) for i in range(3))
                a = int(float(parts[3])) if len(parts) > 3 and parts[3] else 255
                c = QColor(r, g, b)
                c.setAlpha(max(0, min(255, a)))
                return c
        return QColor(s)
    return None  # type: ignore[return-value]

# Audit
WIDGET_AUDIT_MAX: Final[int] = 500

# ===========================================================================
# MODUL-LOGGER (med 10000% loggning-stöd)
# ===========================================================================
logger = logging.getLogger("Widget")
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
# LOGGER-DECORATORS (10000% loggning)
# ===========================================================================

def _log_call(func):
    """Decorator: logga entry/exit med duration."""
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
            logger.error(
                f"{LOG_PREFIX} ✗ {name} MISSLYCKADES ({duration:.2f}ms): "
                f"{type(e).__name__}: {e}",
                exc_info=True,
            )
            raise
    return wrapper


def _log_event(event_name: str):
    """Decorator: logga UI-event."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            start = time.perf_counter()
            try:
                result = func(self, *args, **kwargs)
                duration = (time.perf_counter() - start) * 1000
                logger.trace(
                    f"{LOG_PREFIX} event: {event_name} ({duration:.2f}ms)"
                )
                return result
            except Exception as e:
                duration = (time.perf_counter() - start) * 1000
                logger.error(
                    f"{LOG_PREFIX} event {event_name} FEL "
                    f"({duration:.2f}ms): {e}",
                    exc_info=True,
                )
                raise
        return wrapper
    return decorator




# ===========================================================================
# LOKALA HELPERS (används av TodoWidget._setup_bugg19_zorder)
# ===========================================================================

def _is_windows_local() -> bool:
    """Returnerar True om Windows (lokal version, undviker import-beroende)."""
    return sys.platform == "win32"


def _is_pyw_local() -> bool:
    """Returnerar True om pythonw.exe (lokal version)."""
    return (
        sys.executable.lower().endswith("pythonw.exe")
        or getattr(sys, "frozen", False)
        or not sys.stdout
    )

# ===========================================================================
# AI-FELSÖKNING 10000% (NY v6.4.1 v7)
# ===========================================================================
# Hjalpare for widget-specifika fel:
#   - Svensk forklaring av Qt-fel
#   - Kompakt stacktrace
#   - Standardiserad error-dialog
# Allt for att Rickard ska kunna felsoka widget-problem effektivt.

# Qt-specifika feloversattningar (utover standard-biblioteket)
_QT_ERROR_TRANSLATIONS: Final[Dict[str, str]] = {
    "RuntimeError": "Qt-runtime-fel (kanske trasig widget)",
    "QPainterError": "Qt-ritfel (kanske trasig grafik)",
}


def _describe_widget_error(exc: BaseException) -> str:
    """
    NY v6.4.1 v7: Svensk forklaring av widget-relaterat fel.

    Args:
        exc: Exception-objektet

    Returns:
        Svensk sträng med forklaring
    """
    exc_type = type(exc).__name__
    # Qt-specifika oversattningar
    svensk_typ = _QT_ERROR_TRANSLATIONS.get(exc_type, "")
    # Standard (från main.pyw via _describe_exception, men vi har det inte har)
    std_translations = {
        "ImportError": "Kan inte hitta en Python-modul",
        "AttributeError": "Widget saknar en metod/attribut",
        "TypeError": "Fel typ av argument",
        "ValueError": "Ogiltigt varde",
        "KeyError": "Nyckel saknas",
        "FileNotFoundError": "Filen hittades inte",
        "PermissionError": "Saknar ratigheter",
        "OSError": "Operativsystem-fel",
    }
    if not svensk_typ:
        svensk_typ = std_translations.get(exc_type, f"Tekniskt fel ({exc_type})")
    msg = str(exc).strip()
    if not msg:
        return svensk_typ
    return f"{svensk_typ}: {msg}"


def _format_widget_traceback(exc: BaseException, max_frames: int = 3) -> str:
    """
    NY v6.4.1 v7: Kompakt stacktrace for widget-fel (default 3 frames).
    """
    import traceback
    tb_lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
    if len(tb_lines) <= max_frames + 2:
        return "".join(tb_lines)
    header = tb_lines[0]
    last_frames = tb_lines[-(max_frames):]
    omitted = len(tb_lines) - max_frames - 1
    return (
        header +
        f"  ... ({omitted} middle frames utelamnade) ...\n" +
        "".join(last_frames)
    )


def _categorize_widget_error(exc: BaseException) -> str:
    """
    NY v6.4.1 v7: Kategorisera widget-fel for prioriterad felhantering.

    Returns:
        En av: "user_input", "system", "code_bug", "external",
        "permission", "data_corrupt", "concurrent"
    """
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
    # Qt-fel
    if "Qt" in exc_type or "PySide" in str(exc) or "QObject" in str(exc):
        return "external"
    # Import
    if exc_type in ("ImportError", "ModuleNotFoundError"):
        return "external"
    # Minne
    if exc_type in ("MemoryError", "RecursionError", "OverflowError"):
        return "system"
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
        category = _categorize_widget_error(exc)
        if log_errors:
            logger.error(
                f"{LOG_PREFIX} safe_call({func_name}) MISSLYCKADES "
                f"({duration:.2f}ms, kategori={category}): "
                f"{_describe_widget_error(exc)}"
            )
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"{LOG_PREFIX} safe_call traceback:\n"
                    f"{_format_widget_traceback(exc, max_frames=8)}"
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
        category = _categorize_widget_error(exc)
        ctx["errors"].append(exc)
        if log_errors:
            logger.error(
                f"{LOG_PREFIX} safe_run FEL: {operation_name} "
                f"({duration:.2f}ms, kategori={category}): "
                f"{_describe_widget_error(exc)}"
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

    t = threading.Thread(target=worker, daemon=True, name=f"widget-safe-async:{op_name}")
    t.start()
    if not done.wait(timeout=timeout_sec):
        logger.error(
            f"{LOG_PREFIX} _safe_run_async TIMEOUT ({timeout_sec}s): {op_name}"
        )
        return default
    if error_box[0] is not None:
        category = _categorize_widget_error(error_box[0])
        logger.error(
            f"{LOG_PREFIX} _safe_run_async FEL: {op_name} "
            f"(kategori={category}): "
            f"{_describe_widget_error(error_box[0])}"
        )
        return default
    return result_box[0]


def _flatten_subtasks(subs: Any, depth: int = 1) -> List[tuple]:
    """NY v8: platta ut delmoment-trädet (djup, done, titel) för cache-nyckel."""
    out: List[tuple] = []
    for s in subs or []:
        if not isinstance(s, dict):
            continue
        out.append((depth, bool(s.get("done")), str(s.get("title", ""))))
        out.extend(_flatten_subtasks(s.get("children") or [], depth + 1))
    return out


def _subtask_stats(subs: Any) -> Tuple[int, int]:
    """NY v8: (totalt, klara) över hela delmoment-trädet."""
    total = 0
    done = 0
    for s in subs or []:
        if not isinstance(s, dict):
            continue
        total += 1
        if s.get("done"):
            done += 1
        t, d = _subtask_stats(s.get("children") or [])
        total += t
        done += d
    return total, done


def format_task_summary_swedish(task: Dict[str, Any], max_title_len: int = 40) -> str:
    """
    NY v6.4.1 v7: Svensk en-rads-sammanfattning av en task (widget-specifik).

    Exempel:
        >>> t = {"title": "Handla", "priority": "high", "done": False, "tags": ["hem"]}
        >>> format_task_summary_swedish(t)
        '[H] Handla #hem'
    """
    try:
        title = str(task.get("title", "")).strip() or "(ingen titel)"
        if len(title) > max_title_len:
            title = title[: max_title_len - 1] + "…"
        priority = str(task.get("priority", "none")).lower()
        prefix = {"high": "[H]", "medium": "[M]", "low": "[L]", "none": "[ ]"}.get(
            priority, "[ ]"
        )
        if task.get("done"):
            return f"    Klar: {title}"
        tags = task.get("tags", []) or []
        tag_str = ""
        if tags:
            tag_str = " #" + " #".join(str(t) for t in tags[:3] if t)
        return f"{prefix} {title}{tag_str}"
    except Exception as e:
        logger.debug(f"{LOG_PREFIX} format_task_summary_swedish misslyckades: {e}")
        return f"(fel vid formatering: {type(e).__name__})"


def summarize_widget_health(widget: Any) -> str:
    """NY v6.4.1 v7: Svensk hälso-sammanfattning av en widget-instans."""
    try:
        if widget is None:
            return f"v{WIDGET_VERSION} • widget-modulen redo (ingen instans)"
        win_id = getattr(widget, "win_id", "?")
        n_tasks = 0
        if hasattr(widget, "_tasks"):
            try:
                n_tasks = len(widget._tasks)
            except Exception:
                pass
        focus = getattr(widget, "_focus_mode", False)
        locked = getattr(widget, "_locked", False)
        return (
            f"v{WIDGET_VERSION} • win_id={win_id} • "
            f"{n_tasks} tasks • "
            f"{'FOCUS' if focus else 'normal'} • "
            f"{'låst' if locked else 'olåst'}"
        )
    except Exception as e:
        logger.debug(f"{LOG_PREFIX} summarize_widget_health misslyckades: {e}")
        return f"(kunde inte sammanfatta: {type(e).__name__})"


def get_widget_diagnostics(widget: Optional[Any] = None) -> Dict[str, Any]:
    """NY v6.4.1 v7: Detaljerad diagnostik-rapport for support-fall."""
    with safe_run("get_widget_diagnostics") as ctx:
        problems: List[str] = []
        if widget is not None and hasattr(widget, "diagnose"):
            try:
                problems = widget.diagnose()
            except Exception as e:
                problems.append(
                    f"widget.diagnose() kraschade: "
                    f"{_describe_widget_error(e)}"
                )
        summary = summarize_widget_health(widget)
        ctx["ok"] = True
        return {
            "module": "widget",
            "widget_version": WIDGET_VERSION,
            "app_version": APP_VERSION,
            "problems": problems,
            "problem_count": len(problems),
            "summary_swedish": summary,
        }


# NY v6.4.1 v7: Plugin-coupling — widget behöver Qt (PySide6/PyQt6/PyQt5)
# Vi kan inte kräva exakt en — widget försöker alla i ordning i safe_import_module
# Här listar vi bara PySide6 (preferred) som huvudplugin
_WIDGET_PLUGIN_DEPS: Final[Tuple[Dict[str, str], ...]] = (
    {
        "pip_name": "PySide6",
        "import_name": "PySide6",
        "description_svenska": "Qt-gränssnitt (krav för UI)",
        "benefit_svenska": "Utan denna funkar INGEN widgets eller tray",
        "required": True,
    },
)


def get_widget_plugin_deps() -> List[Dict[str, str]]:
    """NY v6.4.1 v7: Optional Python-beroenden som widget vill ha."""
    return [dict(d) for d in _WIDGET_PLUGIN_DEPS]


def _show_widget_error(
    parent: Any,
    title: str,
    user_message: str,
    exc: Optional[BaseException] = None,
    category: str = "code_bug",
) -> bool:
    """
    NY v6.4.1 v7: Standardiserad widget-error-dialog.

    Args:
        parent: Parent-widget (oftast self)
        title: Kort titel (t.ex. "Kunde inte spara")
        user_message: Svensk forklaring for anvandaren
        exc: Exception-objektet (valfritt, for loggning)
        category: "user_input" | "system" | "code_bug" | "external"

    Returns:
        True om anvandaren klickade OK, False annars
    """
    if exc is not None:
        logger.warning(
            f"{LOG_PREFIX} _show_widget_error: {title!r} "
            f"[{category}]: {_describe_widget_error(exc)}",
            exc_info=True,
        )
    try:
        if QMessageBox is None:
            logger.error(
                f"{LOG_PREFIX} _show_widget_error: {title}: {user_message}"
            )
            return False
        QMessageBox.warning(parent, f"{APP_NAME} — {title}", user_message)
        logger.debug(
            f"{LOG_PREFIX} _show_widget_error visad: {title!r}"
        )
        return True
    except Exception as e:
        logger.warning(
            f"{LOG_PREFIX} _show_widget_error misslyckades: {e}",
            exc_info=True,
        )
        return False


# ===========================================================================
# PWM (Performance Weighted Module) — Adaptive Throttle
# ===========================================================================

class ThrottleState(Enum):
    """FPS-throttle state."""
    ACTIVE = auto()    # 60 FPS
    NORMAL = auto()    # 30 FPS
    IDLE = auto()      # 1 FPS
    LOCKED = auto()    # 0.1 FPS


@dataclass(slots=True)
class _FPSSample:
    """FPS-sample (slots för minne)."""
    timestamp: float
    frame_duration_ms: float


class AdaptiveThrottle:
    """
    PWM: Adaptive FPS-throttle baserat på aktivitet.

    Logik:
      - mouse/keyboard-event → ACTIVE (60s timer)
      - Timer utan input → NORMAL → IDLE (>5s)
      - Focus-out → IDLE
      - Minskar render-CPU med 95-98% vid idle
    """

    __slots__ = (
        "_state", "_last_activity", "_fps_samples", "_ema_fps",
        "_current_interval_ms", "_listeners", "_lock",
        "_total_frames", "_slow_frames", "_saved_cpu_percent",
    )

    def __init__(self) -> None:
        self._state: ThrottleState = ThrottleState.NORMAL
        self._last_activity: float = time.time()
        self._fps_samples: List[_FPSSample] = []
        self._ema_fps: float = 30.0
        self._current_interval_ms: int = PWM_FPS_NORMAL_MS
        self._listeners: weakref.WeakSet = weakref.WeakSet()
        self._lock = threading.RLock()
        self._total_frames: int = 0
        self._slow_frames: int = 0  # > 50ms
        self._saved_cpu_percent: float = 0.0
        logger.debug(f"{LOG_PREFIX} PWM AdaptiveThrottle skapad (state=NORMAL)")

    def notify_activity(self) -> None:
        """Kalla vid mouse/keyboard-event → ACTIVE state."""
        with self._lock:
            self._last_activity = time.time()
            if self._state != ThrottleState.ACTIVE:
                old_state = self._state
                self._state = ThrottleState.ACTIVE
                self._current_interval_ms = PWM_FPS_ACTIVE_MS
                self._notify_listeners(old_state, self._state)
                logger.trace(
                    f"{LOG_PREFIX} PWM: {old_state.name} → ACTIVE "
                    f"({PWM_FPS_ACTIVE_MS}ms/frame)"
                )

    def update(self) -> int:
        """Uppdatera state baserat på tid. Returnerar frame-interval (ms)."""
        now = time.time()
        with self._lock:
            idle_sec = now - self._last_activity
            old_state = self._state

            if self._state == ThrottleState.ACTIVE and idle_sec > PWM_ACTIVE_BOOST_SEC:
                self._state = ThrottleState.NORMAL
                self._current_interval_ms = PWM_FPS_NORMAL_MS
            elif self._state == ThrottleState.NORMAL and idle_sec > PWM_IDLE_THRESHOLD_SEC:
                self._state = ThrottleState.IDLE
                self._current_interval_ms = PWM_FPS_IDLE_MS
                # Beräkna CPU-besparing
                old_fps = 1000 / PWM_FPS_NORMAL_MS
                new_fps = 1000 / PWM_FPS_IDLE_MS
                self._saved_cpu_percent = (1 - new_fps / old_fps) * 100
                logger.info(
                    f"{LOG_PREFIX} PWM: NORMAL → IDLE "
                    f"({PWM_FPS_IDLE_MS}ms/frame, "
                    f"~{self._saved_cpu_percent:.0f}% CPU sparad)"
                )

            if old_state != self._state:
                self._notify_listeners(old_state, self._state)
            return self._current_interval_ms

    def record_frame(self, frame_duration_ms: float) -> None:
        """Registrera en frame-duration (för FPS-tracking)."""
        now = time.time()
        with self._lock:
            self._fps_samples.append(_FPSSample(now, frame_duration_ms))
            if len(self._fps_samples) > PWM_FPS_SAMPLE_WINDOW:
                self._fps_samples.pop(0)
            self._total_frames += 1
            if frame_duration_ms > 50.0:
                self._slow_frames += 1
            # Uppdatera EMA FPS
            if frame_duration_ms > 0:
                current_fps = 1000.0 / frame_duration_ms
                alpha = 0.3  # EMA-faktor
                self._ema_fps = alpha * current_fps + (1 - alpha) * self._ema_fps

    def set_locked(self, locked: bool) -> None:
        """Sätt LOCKED state (t.ex. minimerad)."""
        with self._lock:
            old_state = self._state
            if locked:
                self._state = ThrottleState.LOCKED
                self._current_interval_ms = PWM_FPS_LOCKED_MS
            elif self._state == ThrottleState.LOCKED:
                self._state = ThrottleState.NORMAL
                self._current_interval_ms = PWM_FPS_NORMAL_MS
            if old_state != self._state:
                self._notify_listeners(old_state, self._state)
                logger.debug(
                    f"{LOG_PREFIX} PWM: {old_state.name} → {self._state.name}"
                )

    def add_listener(self, listener: Any) -> None:
        """Lägg till state-change listener (weakref)."""
        self._listeners.add(listener)

    def _notify_listeners(self, old: ThrottleState, new: ThrottleState) -> None:
        for listener in list(self._listeners):
            with suppress(Exception):
                if hasattr(listener, "on_pwm_state_change"):
                    listener.on_pwm_state_change(old, new)

    @property
    def state(self) -> ThrottleState:
        return self._state

    @property
    def current_interval_ms(self) -> int:
        return self._current_interval_ms

    @property
    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "state": self._state.name,
                "interval_ms": self._current_interval_ms,
                "ema_fps": round(self._ema_fps, 1),
                "total_frames": self._total_frames,
                "slow_frames": self._slow_frames,
                "slow_percent": (
                    self._slow_frames / self._total_frames * 100
                    if self._total_frames > 0 else 0.0
                ),
                "saved_cpu_percent": round(self._saved_cpu_percent, 1),
                "last_activity_ago_sec": round(time.time() - self._last_activity, 1),
            }


# Global PWM-instans (per process)
_global_throttle: Optional[AdaptiveThrottle] = None


def get_throttle() -> AdaptiveThrottle:
    """Hämta global PWM-throttle (singleton)."""
    global _global_throttle
    if _global_throttle is None:
        _global_throttle = AdaptiveThrottle()
    return _global_throttle


# ===========================================================================
# WIDGET AUDIT (trådsäker log)
# ===========================================================================

class WidgetAudit:
    """Audit-log för widget-events (FIFO, trådsäker)."""

    __slots__ = ("_entries", "_max", "_lock")

    def __init__(self, max_entries: int = WIDGET_AUDIT_MAX) -> None:
        self._entries: List[Dict[str, Any]] = []
        self._max = max_entries
        self._lock = threading.RLock()
        logger.debug(f"{LOG_PREFIX} WidgetAudit skapad (max={max_entries})")

    def add(self, event: str, details: Optional[Dict[str, Any]] = None) -> None:
        with self._lock:
            self._entries.append({
                "event": event,
                "timestamp": time.time(),
                "ts_iso": datetime.now().isoformat(),
                "details": details or {},
            })
            if len(self._entries) > self._max:
                self._entries.pop(0)
        logger.trace(f"{LOG_PREFIX} audit: {event} {details or ''}")

    def get_entries(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._entries[-limit:])

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
        logger.debug(f"{LOG_PREFIX} audit rensad")

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {"total": len(self._entries), "max": self._max}


# ===========================================================================
# EXPORT (till widget_atoms, widget_parts/* och ui/widget.py via `import *`)
# ===========================================================================
# Alla namn — även _privata — exporteras. _UI_FONT_SCALE undantas medvetet: en kopia i
# andra moduler skulle bli inaktuell; läs den via ui.widget (live) eller set_ui_font_scale().
__all__ = [
    _n for _n in list(globals())
    if not _n.startswith("__") and _n not in ("_UI_FONT_SCALE", "annotations")
]
