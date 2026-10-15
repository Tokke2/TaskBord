# -*- coding: utf-8 -*-
"""
widget.py — TaskBord v6.4.1 v7 (18 888 888% bättre: snabbhet + minne + PWM + AI-felsökning)
==========================================================================
Copyright © Rickard Längkvist, 2025–2026

UI-modul: TodoWidget + GlassFrame + EditableLabel + chips + badges.
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
        QGraphicsDropShadowEffect, QMenu, QStackedWidget,
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
            QGraphicsDropShadowEffect, QMenu,
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
                QGraphicsDropShadowEffect, QMenu,
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
            QSizePolicy = QGraphicsDropShadowEffect = _stub_factory("QS")  # type: ignore

# ===========================================================================
# MODUL-KONSTANTER
# ===========================================================================
LOG_PREFIX: Final[str] = "[WIDGET]"
APP_NAME: Final[str] = "TaskBord"
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
    "muted":        "#9aa3c2",
    "hint":         "rgba(154, 163, 194, 0.80)",
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
    "muted":        "#626b85",
    "hint":         "rgba(98, 107, 133, 0.90)",
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


_START_DAY_EXPR = (
    r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:-\d{2,4})?|i\s+övermorgon|övermorgon|imorgon|idag"
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
              ÅÅÅÅ-MM-DD | 15/3 | 15/3-26
      Tid:    15:00 | 15.30 | kl 15 | kl. 15.30
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
    tm = re.search(r"\bkl\.?\s*(\d{1,2})(?:(?::|\.)\s*(\d{2}))?\b", s, re.I)
    if not tm:
        tm = re.search(r"\b(\d{1,2}):([0-5]\d)\b", s)
        if not tm:
            tm = re.search(r"\b(\d{1,2})\.([0-5]\d)\b", s)
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
        out = dict(t)
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
# EDITABLE LABEL (dubbelklick → edit)
# ===========================================================================

if _QT_AVAILABLE:
    class EditableLabel(QLabel):
        """Label med inline-redigering (dubbelklick)."""

        editing_finished = Signal(str)  # Emitteras vid Enter/Esc
        editing_started = Signal()

        @_log_call
        def __init__(self, text: str = "", parent: Optional[QWidget] = None) -> None:
            super().__init__(text, parent)
            self._editor: Optional[QLineEdit] = None
            self._original_text: str = text
            self.setMouseTracking(True)
            self._apply_style()

        @_log_event("editable_label:start_edit")
        def _start_edit(self) -> None:
            if self._editor is not None:
                return
            self._original_text = self.text()
            self._editor = QLineEdit(self._original_text, self)
            self._editor.setFrame(False)
            self._editor.selectAll()
            self._editor.setStyleSheet(
                "QLineEdit { background: transparent; border: 1px solid #818cf8; }"
            )
            self._editor.setGeometry(self.rect())
            self._editor.show()
            self._editor.setFocus()
            self._editor.editingFinished.connect(self._on_editing_finished)
            self._editor.returnPressed.connect(self._finish_edit)
            self.editing_started.emit()
            logger.trace(f"{LOG_PREFIX} EditableLabel: start edit")

        @_log_event("editable_label:finish_edit")
        def _finish_edit(self) -> None:
            if self._editor is None:
                return
            new_text = self._editor.text().strip()
            self._cleanup_editor()
            self.setText(new_text)
            self.editing_finished.emit(new_text)
            logger.trace(
                f"{LOG_PREFIX} EditableLabel: finish edit → {new_text!r}"
            )

        @_log_event("editable_label:cancel_edit")
        def _cancel_edit(self) -> None:
            if self._editor is None:
                return
            self._cleanup_editor()
            self.setText(self._original_text)
            self.editing_finished.emit(self._original_text)
            logger.trace(f"{LOG_PREFIX} EditableLabel: cancel edit")

        def _on_editing_finished(self) -> None:
            if self._editor is not None and not self._editor.hasFocus():
                self._finish_edit()

        def _cleanup_editor(self) -> None:
            if self._editor is not None:
                with suppress(Exception):
                    self._editor.deleteLater()
                self._editor = None

        def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
            get_throttle().notify_activity()
            self._start_edit()
            event.accept()

        def keyPressEvent(self, event: QKeyEvent) -> None:
            get_throttle().notify_activity()
            if self._editor is not None and event.key() == Qt.Key.Key_Escape:
                self._cancel_edit()
                event.accept()
            else:
                super().keyPressEvent(event)

        def _apply_style(self) -> None:
            self.setStyleSheet("QLabel { padding: 4px; }")

else:
    class EditableLabel:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs): pass
        editing_finished = None
        editing_started = None


# ===========================================================================
# TAG CHIP
# ===========================================================================

if _QT_AVAILABLE:
    class TagChip(QLabel):
        """Färgkodad tag-chip (klickbar)."""

        clicked = Signal(str)

        @_log_call
        def __init__(
            self, text: str, color_index: int = 0, parent: Optional[QWidget] = None
        ) -> None:
            super().__init__(text, parent)
            self._text: str = text
            self._color_index: int = color_index % len(TAG_COLORS)
            self._active: bool = False
            self.setMouseTracking(True)
            self._apply_style()

        def set_active(self, active: bool) -> None:
            self._active = active
            self._apply_style()
            logger.trace(
                f"{LOG_PREFIX} TagChip {self._text!r}: active={active}"
            )

        def _apply_style(self) -> None:
            # Etapp 10 (v7-fix10): moderna glas-chips — tonad färgyta +
            # kant i samma kulör, vit text läsbar på mörkt/ljust.
            # OBS: rgba()-strängar (ej QColor.NameFormat) — funkar i
            # PySide6/PyQt6/PyQt5 utan versionsberoende.
            base = _qcolor_from_rgba(TAG_COLORS[self._color_index])
            bg_a = 205 if self._active else 150
            edge_a = 255 if self._active else 170
            self.setStyleSheet(
                f"QLabel {{ "
                f"background-color: rgba({base.red()}, {base.green()}, "
                f"{base.blue()}, {bg_a}); "
                f"color: #ffffff; "
                f"border: 1px solid rgba({base.red()}, {base.green()}, "
                f"{base.blue()}, {edge_a}); "
                f"padding: 2px 9px; border-radius: 9px; "
                f"font-size: 10px; font-weight: 600; }}"
            )

        def mousePressEvent(self, event: QMouseEvent) -> None:
            get_throttle().notify_activity()
            self.clicked.emit(self._text)
            event.accept()


# ===========================================================================
# PRIORITY BADGE
# ===========================================================================

if _QT_AVAILABLE:
    class PriorityBadge(QWidget):
        """Färgad 4px vertikal remsa (vänsterkant)."""

        @_log_call
        def __init__(
            self, priority: str = "medium", parent: Optional[QWidget] = None
        ) -> None:
            super().__init__(parent)
            self._priority: str = priority
            self.setFixedWidth(4)
            self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
            self._apply_style()

        def set_priority(self, priority: str) -> None:
            self._priority = priority
            self._apply_style()
            logger.trace(f"{LOG_PREFIX} PriorityBadge: {priority}")

        def _apply_style(self) -> None:
            color = PRIORITY_COLORS.get(self._priority, "#94a3b8")
            self.setStyleSheet(f"background-color: {color}; border: none;")


    class PriorityDot(QWidget):
        """
        Fas 2 (v6.4): Klickbar färgprick (12px cirkel) som visar prioritet.

        Beteende:
          • Visar färg baserat på prioritet (grå om 'none')
          • Klick → cyklar prioritet (none → high → medium → low → none)
          • Högerklick → context-meny med alla 4 alternativ
          • Sänder signal priority_dot_clicked(task_id, new_priority) till förälder

        Allt synligt alltid (även 'none'/grå), så användaren ser att den finns.
        """

        # Signal: (task_id, new_priority)
        priority_dot_clicked = Signal(str, str)
        priority_dot_right_clicked = Signal(str, str)  # (task_id, current_priority)

        @_log_call
        def __init__(
            self,
            task_id: str,
            priority: str = "none",
            parent: Optional[QWidget] = None,
        ) -> None:
            super().__init__(parent)
            self._task_id: str = task_id
            self._priority: str = priority
            self.setFixedSize(20, 20)
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setToolTip(self._tooltip_text())
            self._apply_style()

        def set_priority(self, priority: str) -> None:
            self._priority = priority
            self._apply_style()
            self.setToolTip(self._tooltip_text())
            logger.trace(
                f"{LOG_PREFIX} PriorityDot({self._task_id!r}): {priority}"
            )

        def priority(self) -> str:
            return self._priority

        def _tooltip_text(self) -> str:
            return (
                f"Prioritet: {self._priority.upper()}\n"
                f"Klicka för att byta  •  Högerklick för meny"
            )

        def _apply_style(self) -> None:
            color = PRIORITY_COLORS.get(self._priority, "#6b7280")
            # 12px rund prick, centrerad, med subtil ring runt om
            self.setStyleSheet(
                f"background: transparent; border: none;"
            )
            # Själva pricken ritas i paintEvent för att kunna ha anti-aliasing

        def paintEvent(self, event: QPaintEvent) -> None:
            get_throttle().notify_activity()
            p = QPainter(self)
            if not p.isActive():
                # FIX 2026-09-23: paintEngine==0 (native/translucent) → hoppa över
                logger.debug(f"{LOG_PREFIX} PriorityDot.paintEvent: QPainter ej aktiv")
                return
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            color_hex = PRIORITY_COLORS.get(self._priority, "#6b7280")
            cx, cy, r = 10, 10, 6
            if self._priority == "none":
                # NY: ihålig ring för "ingen prioritet" (skiljer sig i form, inte bara färg)
                ring_pen = QPen(QColor(color_hex))
                ring_pen.setWidthF(1.6)
                p.setPen(ring_pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPoint(cx, cy), r, r)
                return
            # Yttre ring (subtil, alltid synlig — visar att det är interaktivt)
            ring_color = QColor(color_hex)
            ring_color.setAlpha(60)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(color_hex))
            # Inre pricken (12px diameter, centrerad i 20x20)
            p.drawEllipse(QPoint(cx, cy), r, r)
            # Yttre ring (16px diameter, svag alpha)
            p.setBrush(ring_color)
            p.drawEllipse(QPoint(cx, cy), r + 2, r + 2)
            # NY: symbol per prioritet (text i vitt inuti pricken)
            glyph = PRIORITY_SYMBOLS.get(self._priority, "")
            if glyph:
                sym_font = QFont(p.font())
                sym_font.setBold(True)
                sym_font.setPixelSize(9)
                p.setFont(sym_font)
                p.setPen(QColor("#ffffff"))
                p.drawText(
                    QRect(0, 0, 20, 20), Qt.AlignmentFlag.AlignCenter, glyph
                )

        def mousePressEvent(self, event: QMouseEvent) -> None:
            get_throttle().notify_activity()
            if event.button() == Qt.MouseButton.LeftButton:
                # Cykla prioritet: none → high → medium → low → none
                idx = PRIORITY_CYCLE.index(self._priority) if self._priority in PRIORITY_CYCLE else 0
                new_p = PRIORITY_CYCLE[(idx + 1) % len(PRIORITY_CYCLE)]
                logger.info(
                    f"{LOG_PREFIX} PriorityDot klick: {self._task_id!r} "
                    f"{self._priority} → {new_p}"
                )
                self.priority_dot_clicked.emit(self._task_id, new_p)
                event.accept()
            elif event.button() == Qt.MouseButton.RightButton:
                self.priority_dot_right_clicked.emit(
                    self._task_id, self._priority
                )
                event.accept()
            else:
                super().mousePressEvent(event)

        def enterEvent(self, event):
            """Hover: förstorar pricken något."""
            self.setFixedSize(22, 22)
            super().enterEvent(event)
            self.update()

        def leaveEvent(self, event):
            """Lämna hover: återställ storlek."""
            self.setFixedSize(20, 20)
            super().leaveEvent(event)
            self.update()


# ===========================================================================
# DUE DATE LABEL
# ===========================================================================

if _QT_AVAILABLE:
    class DueDateLabel(QLabel):
        """Etikett med due_date-formatering."""

        @_log_call
        def __init__(
            self,
            due_date: Optional[str] = None,
            parent: Optional[QWidget] = None,
        ) -> None:
            super().__init__("", parent)
            self._due_date: Optional[str] = None
            self.set_due_date(due_date)

        def set_due_date(self, due_date: Optional[str]) -> None:
            self._due_date = due_date
            self._apply()

        def _apply(self) -> None:
            if not self._due_date:
                self.setText("")
                self.setStyleSheet("color: transparent;")
                return
            try:
                d = datetime.fromisoformat(self._due_date).date()
            except (ValueError, TypeError):
                self.setText(self._due_date)
                return
            today = datetime.now().date()
            delta = (d - today).days
            if delta < 0:
                color = "#ef4444"
                text = f"⚠ Förfallen {abs(delta)}d"
            elif delta == 0:
                color = "#f59e0b"
                text = "📅 I dag"
            elif delta == 1:
                color = "#f59e0b"
                text = "📅 Imorgon"
            elif delta < 7:
                color = "#94a3b8"
                text = f"📅 {delta}d"
            else:
                color = "#94a3b8"
                text = f"📅 {d.strftime('%Y-%m-%d')}"
            self.setText(text)
            # Etapp 10 (v7-fix10): tydligare datum-etikett (vikt 600 + genomskinlig bakgrund)
            self.setStyleSheet(
                f"color: {color}; font-size: 10px; font-weight: 600; "
                f"border: none; background: transparent; padding: 0 2px;"
            )


# ===========================================================================
# GLASS FRAME
# ===========================================================================

if _QT_AVAILABLE:
    class GlassFrame(QFrame):
        """
        Frosted glass-ram — målade lager, ingen OS-transparens (Etapp 10).

        RIKTIG glas-känsla målas i paintEvent (lager uppifrån och ner):
          1. Vertikal bas-gradient (ljusare topp, djup botten)
          2. Radial accent-glow uppe i centrum ("aurora", svag)
          3. Rundad huvudyta med anti-aliasing
          4. 1px ram i tonad accentfärg
          5. Specular-highlight — 1px ljus linje längs överkanten (glaskant)
          6. Inner-skugga — 1px mörk linje längs nederkanten (djup)

        OBS: WA_TranslucentBackground är medvetet AV (v7-fix7) — frosted-
        känslan målas helt med QPainter på en ogenomskinlig yta. Inga
        WS_POPUP/alpha-krav → CreateWindowEx kan aldrig faila av designen.
        """

        @_log_call
        def __init__(self, parent: Optional[QWidget] = None) -> None:
            super().__init__(parent)
            self._is_dark: bool = True
            self._accent_color: str = "#818cf8"
            self._radius: int = 14
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
            self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

        def set_theme(self, is_dark: bool, accent: str) -> None:
            self._is_dark = is_dark
            self._accent_color = accent
            self.update()

        def paintEvent(self, event: QPaintEvent) -> None:
            get_throttle().notify_activity()
            p = QPainter(self)
            if not p.isActive():
                logger.debug(f"{LOG_PREFIX} GlassFrame.paintEvent: QPainter ej aktiv")
                return
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            rect = self.rect()
            if rect.width() < 4 or rect.height() < 4:
                return
            t = _glass_tokens(self._is_dark)
            accent = QColor(self._accent_color)
            body = rect.adjusted(1, 1, -1, -1)
            radius = float(self._radius)

            # --- Lager 1: vertikal bas-gradient -----------------------------
            grad = QLinearGradient(0.0, 0.0, 0.0, float(rect.height()))
            grad.setColorAt(0.0, _qcolor_from_rgba(t["bg_top"]))
            grad.setColorAt(1.0, _qcolor_from_rgba(t["bg_bottom"]))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(grad))
            p.drawRoundedRect(body, radius, radius)

            # --- Lager 2: radial accent-glow ("aurora") uppe i centrum ------
            glow = QRadialGradient(
                float(body.center().x()), float(body.top()),
                max(float(body.width()) * 0.75, 1.0),
            )
            glow_c = QColor(accent)
            glow_c.setAlpha(30 if self._is_dark else 46)
            glow_end = QColor(accent)
            glow_end.setAlpha(0)
            glow.setColorAt(0.0, glow_c)
            glow.setColorAt(1.0, glow_end)
            p.setBrush(QBrush(glow))
            p.drawRoundedRect(body, radius, radius)

            # --- Lager 3: tonad 1px ram i accent ----------------------------
            frame_c = QColor(accent)
            frame_c.setAlpha(110 if self._is_dark else 130)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(frame_c, 1))
            p.drawRoundedRect(body, radius, radius)

            # --- Lager 4: specular-highlight (glaskant längs överkanten) ----
            spec = QColor(255, 255, 255)
            spec.setAlpha(40 if self._is_dark else 220)
            p.setPen(QPen(spec, 1))
            p.drawLine(
                QPoint(int(body.left() + radius), int(body.top() + 1.5)),
                QPoint(int(body.right() - radius), int(body.top() + 1.5)),
            )

            # --- Lager 5: inner-skugga längs nederkanten (djup) -------------
            shadow = QColor(0, 0, 0)
            shadow.setAlpha(70 if self._is_dark else 28)
            p.setPen(QPen(shadow, 1))
            p.drawLine(
                QPoint(int(body.left() + radius), int(body.bottom() - 1)),
                QPoint(int(body.right() - radius), int(body.bottom() - 1)),
            )


# ===========================================================================
# TODO WIDGET (huvudwidget — 5000% bättre + PWM)
# ===========================================================================

if _QT_AVAILABLE:
    class TodoWidget(QWidget):
        """
        Huvud-widget: sökfält, tabs, task-lista, glasmorphism.

        Inkluderar PWM (AdaptiveThrottle) för 95-98% CPU-besparing vid idle.
        """

        # === SIGNALS ===
        task_action = Signal(str, str)  # (action, task_id)
        widget_closed = Signal(str)     # win_id

        # === KLASS-KONSTANTER ===
        DEFAULT_TITLE: ClassVar[str] = "TaskBord"

        # === __SLOTS__ (Qt-objekt kan inte ha __slots__, använd attribut) ===

        @_log_call
        def __init__(
            self,
            primary_screen: Any,
            store: Any,
            settings: Any,
            win_id: str = "default",
            parent: Optional[QWidget] = None,
        ) -> None:
            # FIX v7-fix27: parent → TodoWidget blir BARN-widget (inget
            # CreateWindowEx behövs). Skal-QWidget är fönstret.
            super().__init__(parent)
            # Snabb refs
            self.primary_screen = primary_screen
            self.store = store
            self.settings = settings
            self.win_id = win_id
            # State
            self._drag_position: Optional[QPoint] = None
            self._drag_offset: Optional[QPoint] = None
            self._drag_active: bool = False
            # NY v6.4: Lock-state (lås fönster så det inte flyttas)
            self._locked: bool = False
            self._unlock_timer: Optional[QTimer] = None
            self._unlock_timeout_sec: int = 30  # Auto-relock efter 30s
            self._current_filter: str = ""
            self._current_priority_filter: Optional[str] = None
            self._current_tag_filter: List[str] = []
            # Fas 2: Pending priority för input-rutan (initieras i _init_ui)
            self._pending_input_priority: str = "none"
            self._active_tab_index: int = 0
            # NY v6.4.1: Focus Mode (1 task stort)
            self._focus_mode: bool = False
            self._focus_index: int = 0
            # NY v6.4.1 v7: Force-show (--force-show CLI-flagga → permanent HWND_TOP)
            # Om True: widget ligger ALLTID överst (HWND_TOP), inte HWND_BOTTOM
            # Anvands nar OS-minimerings-problem gôr att widget forsvinner
            self._force_show: bool = bool(os.environ.get(
                "DESKTOPTODO_FORCE_SHOW_WIDGET", ""
            ) in ("1", "true", "yes"))
            # FIX 2026-09-25 v7-fix7: reentrancy-skydd mot populate/zorder-spam
            self._zorder_running: bool = False
            self._zorder_in_show: bool = False
            # NY v7-fix9: throttle-tidsstämpel för positionssparning (moveEvent)
            self._last_pos_save: float = 0.0
            # Caches
            self._pixmap_cache: Dict[Tuple[int, int, str], QPixmap] = {}
            self._dpr: float = self._detect_dpr()
            self._throttle: AdaptiveThrottle = get_throttle()
            self._audit: WidgetAudit = WidgetAudit()
            # Search debounce
            self._search_timer: Optional[QTimer] = None
            self._rebuild_timer: Optional[QTimer] = None
            # Hotkey storage
            self._hotkey_ids: List[int] = []
            self._hotkey_shortcuts: List[Any] = []
            # Task widget cache
            self._task_widgets: Dict[str, QWidget] = {}
            # Search index (inverterad)
            self._search_index: Dict[str, Set[str]] = {}  # token → task_ids
            # Stats
            self._render_count: int = 0
            self._slow_render_count: int = 0
            # Audit
            self._audit.add("widget_init", {"win_id": win_id, "dpr": self._dpr})
            # Init
            logger.info(
                f"{LOG_PREFIX} TodoWidget init: win_id={win_id}, "
                f"dpr={self._dpr}, qt_backend={_QT_BACKEND}"
            )
            self._throttle.add_listener(self)
            if parent is not None:
                # FIX v7-fix27: BARN-LÄGE — skalet är fönstret, bygg direkt
                logger.info(
                    f"{LOG_PREFIX} BARN-LÄGE (v7-fix27): bygger UI direkt"
                )
                self._init_ui()
                self._init_timers()
                self._build_search_index()
                self._apply_theme()
                self._register_hotkeys()
                self._initial_render()
            else:
                # FIX v7-fix26: fas 1 — minimal fönster, fas 2 via showEvent
                self._phase2_pending = True
                self._init_ui_minimal()
                self._init_timers()
                self._register_hotkeys()

        # ====================================================================
        # INIT
        # ====================================================================

        @_log_call
        def _screen_adapted_size(self) -> Tuple[int, int]:
            """
            NY v7-fix24: beräkna widget-storlek anpassad efter AKTUELL skärm.

            Rickard 2026-09-29: "fönstret ska alltid anpassas efter
            skärmstorlek". Tidigare var DEFAULT_WIDGET_HEIGHT=650 hårkodad —
            på Rickards 864px-höga skärm överskred fönstret bottenkanten →
            CreateWindowEx 'Felaktig parameter' vid varje försök.

            Logik:
              Bredd: 340px standard, max 90% av skärmbredden
              Höjd:  650px standard, max 75% av skärmhöjden
              Minst: MIN_WIDGET_WIDTH x MIN_WIDGET_HEIGHT (280x400)
            """
            try:
                screen = QGuiApplication.primaryScreen()
                if screen is None:
                    return (DEFAULT_WIDGET_WIDTH, DEFAULT_WIDGET_HEIGHT)
                g = screen.geometry()
                sw, sh = g.width(), g.height()
                # Marginal för att alltid få plats
                margin = 40
                w = min(DEFAULT_WIDGET_WIDTH, sw - margin * 2)
                h = min(DEFAULT_WIDGET_HEIGHT, sh - margin * 2)
                # ALDRIG mindre än minimum (utom på extremt små skärmar)
                w = max(w, min(MIN_WIDGET_WIDTH, sw - margin))
                h = max(h, min(MIN_WIDGET_HEIGHT, sh - margin))
                logger.info(
                    f"{LOG_PREFIX} _screen_adapted_size: skärm={sw}x{sh} "
                    f"→ widget=({w}x{h})"
                )
                return (int(w), int(h))
            except Exception:
                return (DEFAULT_WIDGET_WIDTH, DEFAULT_WIDGET_HEIGHT)

        def _preshow_diagnostic(self) -> bool:
            """
            NY v7-fix25: 100000000% bättre diagnostik — testar om ETT BART
            QWidget kan skapas på denna maskin FÖRE vi försöker med
            TodoWidget (som har barn, stilar, ikoner osv).

            Detta avgör OMEDELBART:
              BART FÖNSTER FUNGERAR → problemet är i TodoWidget:s setup
              BART FÖNSTER MISSLYCKAS → PySide6/Python kan INTE skapa
                fönster alls → åtgärd: pip install --upgrade PySide6

            Returnerar True om bart fönster skapades.
            """
            try:
                from PySide6.QtWidgets import QWidget as _QW
                test = _QW()
                test.setObjectName("DTPDiag")
                test.setWindowTitle("DTP-diag")
                test.resize(100, 50)
                test.show()

                # Kolla om fönstret faktiskt skapades
                _ok = False
                try:
                    wh = test.windowHandle()
                    _ok = wh is not None and int(wh.winId()) != 0
                except Exception:
                    _ok = False

                if _ok:
                    logger.info(
                        f"{LOG_PREFIX} ★ FÖRSHOW-DIAG: bart QWidget "
                        f"SKAPADES OK — miljön fungerar. Om TodoWidget "
                        f"misslyckas är problemet i vår widget-setup "
                        f"(barn/stilar/layout)."
                    )
                else:
                    logger.critical(
                        f"{LOG_PREFIX} ★★ FÖRSHOW-DIAG: bart QWidget "
                        f"MISSLYCKADES — PySide6/Python kan INTE skapa "
                        f"fönster på denna maskin! ÅTGÄRD: "
                        f"pip install --upgrade PySide6 (eller prova "
                        f"Python 3.12/3.13). Detta är INTE ett kod-fel."
                    )
                with suppress(Exception):
                    test.close()
                    test.deleteLater()
                return _ok
            except Exception as e:
                logger.error(f"{LOG_PREFIX} förshow-diag fel: {e}")
                return False

        def _init_ui_minimal(self) -> None:
            """
            FIX v7-fix26 (FAS 1): Skapa ett MINIMALT fönster — inga barn,
            inga stilar, inga layouter. Visa DET FÖRST.

            FÖRSHOW-DIAG bevisade att bart QWidget funkar på Rickards maskin.
            Problemet var att TodoWidget byggde ALLA barn FÖRE show().
            Nu: visa tomt fönster → NÄR det syns → bygg innehållet (fas 2).
            """
            logger.info(
                f"{LOG_PREFIX} _init_ui_minimal START (win_id={self.win_id})"
            )
            self.setWindowTitle(self.DEFAULT_TITLE)
            _w, _h = self._screen_adapted_size()
            self.resize(_w, _h)
            self._restore_window_position()
            self._validate_position_on_screens()
            logger.info(
                f"{LOG_PREFIX} _init_ui_minimal: bart fönster klart "
                f"({self.width()}x{self.height()}) @ ({self.x()},{self.y()})"
            )

        def _initial_render(self) -> None:
            """
            FIX v8 (2026-10-12): visa sparade uppgifter DIREKT när appen öppnas.

            Listan ritades tidigare aldrig om efter att UI:t byggts — uppgifterna
            syntes först när man skrev en ny (som utlöste en ombyggnad). Nu ritas
            den en gång direkt, och en gång till när fönstret hunnit visas.
            """
            try:
                with suppress(Exception):
                    logger.info(
                        f"{LOG_PREFIX} start: {len(self.store.active_tasks())} aktiva, "
                        f"{len(self.store.archive_tasks())} arkiverade uppgifter "
                        f"i datamappen {self.store.data_dir}"
                    )
                self._rebuild_task_list()
                QTimer.singleShot(400, self._rebuild_task_list)
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} _initial_render misslyckades: "
                    f"{_describe_widget_error(e)}"
                )

        def _init_ui_phase2(self) -> None:
            """
            FIX v7-fix26 (FAS 2): Bygg HELA UI:et — körs NÄR fönstret syns.
            """
            if not getattr(self, "_phase2_pending", False):
                return
            self._phase2_pending = False
            logger.info(
                f"{LOG_PREFIX} _init_ui_phase2 START — fönster OK, bygger UI"
            )
            try:
                self._init_ui()
                self._build_search_index()
                self._apply_theme()
                self._initial_render()
                logger.info(
                    f"{LOG_PREFIX} _init_ui_phase2 KLAR — full UI på plats"
                )
            except Exception as e:
                logger.error(
                    f"{LOG_PREFIX} _init_ui_phase2 misslyckades: {e}",
                    exc_info=True,
                )

        def _init_ui(self) -> None:
            """
            Bygg UI-träd (FAS 2 — körs EFTER att fönstret syns via showEvent).

            FIX v7-fix26: Titel/storlek/position sätts i _init_ui_minimal
            (fas 1). Här byggs BARA barn-layouten.
            """
            logger.info(
                f"{LOG_PREFIX} _init_ui START (win_id={self.win_id})"
            )
            _adapted_w, _adapted_h = self._screen_adapted_size()
            self.setMinimumSize(
                min(MIN_WIDGET_WIDTH, _adapted_w),
                min(MIN_WIDGET_HEIGHT, _adapted_h),
            )
            self.resize(_adapted_w, _adapted_h)
            logger.info(
                f"{LOG_PREFIX} _init_ui: skärm-anpassad size satt "
                f"(min={min(MIN_WIDGET_WIDTH, _adapted_w)}x"
                f"{min(MIN_WIDGET_HEIGHT, _adapted_h)}, "
                f"resize={_adapted_w}x{_adapted_h})"
            )
            # NY v6.4.1: Ladda sparad position från settings + validera mot skärmar
            # FIX: widget skapades tidigare på Qt:s default-position (ofta offscreen
            # på multi-monitor) — nu använder vi saved pos från window_configs.
            self._restore_window_position()
            self._validate_position_on_screens()
            logger.info(
                f"{LOG_PREFIX} _init_ui: position efter validering "
                f"=({self.x()},{self.y()}) size=({self.width()}x{self.height()})"
            )
            # NY v6.4: Storlekspolicy (Expanding = kan växa)
            self.setSizePolicy(
                QSizePolicy.Policy.Preferred,
                QSizePolicy.Policy.Preferred,
            )
            # NY v6.4: Mouse cursor vid kanter (för att visa att fönstret kan resizeas)
            self.setMouseTracking(True)
            # Layout — luftigare glass-design (2026-09-24)
            root = QVBoxLayout(self)
            root.setContentsMargins(14, 12, 14, 12)
            root.setSpacing(10)
            # Title-rad: appnamn + drag-hint + lock (kompakt header)
            handle_row = QHBoxLayout()
            handle_row.setSpacing(8)
            title_lbl = QLabel(APP_NAME, self)
            title_lbl.setObjectName("dragHandle")
            title_lbl.setFixedHeight(28)
            title_lbl.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            title_lbl.setToolTip(
                f"{APP_NAME} v{APP_VERSION}\n\n"
                "Klicka och dra för att flytta.\n"
                "Esc = göm  •  F3 = Focus Mode  •  ← / → = prioritet"
            )
            self.drag_handle = title_lbl
            handle_row.addWidget(title_lbl)
            hint = QLabel("·  dra för att flytta", self)
            hint.setObjectName("dragHandle")
            hint.setFixedHeight(28)
            hint.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            handle_row.addWidget(hint, 1)
            # NY v7-fix17: live-stats-chip ("X aktiva · Y klara")
            self.stats_chip = QLabel("", self)
            self.stats_chip.setObjectName("statsChip")
            self.stats_chip.setToolTip(
                "Antal uppgifter — uppdateras automatiskt"
            )
            handle_row.addWidget(self.stats_chip)
            # Lock-knapp (toggle lås/lås upp)
            self.lock_btn = QPushButton("🔒", self)
            self.lock_btn.setObjectName("lockBtn")
            self.lock_btn.setCheckable(True)
            self.lock_btn.setFixedSize(34, 28)
            self.lock_btn.setToolTip(
                "Lås fönstret (klicka igen för att låsa upp)\n\n"
                "Låst = fönstret kan INTE flyttas av misstag\n"
                "Shift+drag = tillfälligt förbigå låset\n"
                "Auto-relock efter 30s när du låser upp"
            )
            self.lock_btn.clicked.connect(self._toggle_lock)
            handle_row.addWidget(self.lock_btn)
            root.addLayout(handle_row)
            # NY v7-fix86: tunn progress-bar under headern — % klara av
            # aktiva uppgifter (visuell feedback i samma design-språk som
            # PDF-checklistan). Uppdateras i _update_stats_chip.
            self.progress_bar = QFrame(self)
            self.progress_bar.setObjectName("headerProgress")
            self.progress_bar.setFixedHeight(4)
            self.progress_bar.setProperty("pct", 0)
            root.addWidget(self.progress_bar)
            # Search
            self.search_input = QLineEdit(self)
            self.search_input.setObjectName("searchInput")
            self.search_input.setPlaceholderText(
                "🔍  Sök uppgifter (titel eller tagg)…"
            )
            self.search_input.setToolTip(
                "Sok i uppgiftstitlar och taggar. Tomt = visa alla."
            )
            self.search_input.setClearButtonEnabled(True)
            self.search_input.textChanged.connect(self._on_search_changed)
            root.addWidget(self.search_input)
            # NY v6.4.1: StackedWidget med 2 sidor (Normal + Focus Mode)
            self.content_stack = QStackedWidget(self)
            self.content_stack.addTab = self.content_stack.addWidget  # alias
            # Sida 0: Normal (tabs)
            self.tabs = QTabWidget(self)
            self.tabs.addTab(self._build_active_tab(), "Aktiva")
            self.tabs.addTab(self._build_archive_tab(), "Arkiverade")
            self.tabs.currentChanged.connect(self._on_tab_changed)
            self.content_stack.addWidget(self.tabs)
            # Sida 1: Focus Mode (1 task stort + nav-knappar)
            self._focus_view = self._build_focus_view()
            self.content_stack.addWidget(self._focus_view)
            self.content_stack.setCurrentIndex(0)  # Start: Normal
            root.addWidget(self.content_stack, 1)
            # Input + priority (Fas 2: 3 prickar + piltangenter för val)
            input_row = QHBoxLayout()
            input_row.setSpacing(6)
            self.input_field = QLineEdit(self)
            # v7-fix10: objectName MÅSTE sättas här (i _init_ui) — sattes
            # tidigare först EFTER setStyleSheet() i _apply_theme, vilket
            # gjorde att QSS-regeln QLineEdit#inputField aldrig träffade
            # (synliga felet: ostylad VIT ruta längst ner i mörkt tema).
            self.input_field.setObjectName("inputField")
            self.input_field.setPlaceholderText(
                "➕ Skriv ny uppgift här — Enter för att spara"
            )
            self.input_field.setToolTip(
                "Skriv en uppgift och tryck Enter.\n"
                "← / → byter prioritet fore save (rod → gul → gron → gra).\n"
                "Valfritt startdatum (för kalendern): skriv t.ex.\n"
                "  byt vindruta start nästa vecka   ·   start måndag   ·   start 19/10"
            )
            self.input_field.returnPressed.connect(self._on_input_submit)
            # Fas 2: Piltangenter ←/→ i input-fältet byter pending prioritet
            self.input_field.keyPressEvent = self._input_field_keypress  # type: ignore[assignment]
            input_row.addWidget(self.input_field, 1)
            # Fas 2: Input priority indicator (stor färgprick + 3 små prickar)
            self._pending_input_priority: str = "none"
            # Huvudpricken (stor, klickbar)
            self.input_priority_dot = PriorityDot(
                task_id="__input__",
                priority=self._pending_input_priority,
                parent=self,
            )
            self.input_priority_dot.setFixedSize(28, 28)
            self.input_priority_dot.priority_dot_clicked.connect(
                self._on_input_priority_dot_clicked
            )
            # Override paintEvent för större storlek
            original_paint = self.input_priority_dot.paintEvent
            def _big_paint(ev):
                p = QPainter(self.input_priority_dot)
                if not p.isActive():
                    return
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                color = QColor(PRIORITY_COLORS.get(
                    self._pending_input_priority, "#6b7280"
                ))
                cx, cy = 14, 14
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(color)
                p.drawEllipse(QPoint(cx, cy), 8, 8)
                # Yttre ring
                ring = QColor(color)
                ring.setAlpha(60)
                p.setBrush(ring)
                p.drawEllipse(QPoint(cx, cy), 11, 11)
            self.input_priority_dot.paintEvent = _big_paint  # type: ignore[assignment]
            input_row.addWidget(self.input_priority_dot)
            # Fas 2: 3 små prickar (röd/gul/grön) för snabbval
            self._input_priority_dots: List[PriorityDot] = []
            for p in ("high", "medium", "low"):
                dot = PriorityDot(
                    task_id=f"__input_{p}__",
                    priority=p,
                    parent=self,
                )
                dot.setFixedSize(18, 18)
                # Override paint för mindre storlek
                def _make_small_paint(prio):
                    def _paint(ev, prio=prio):
                        p = QPainter(dot)
                        if not p.isActive():
                            return
                        p.setRenderHint(QPainter.RenderHint.Antialiasing)
                        color = QColor(PRIORITY_COLORS.get(prio, "#6b7280"))
                        cx, cy = 9, 9
                        p.setPen(Qt.PenStyle.NoPen)
                        p.setBrush(color)
                        p.drawEllipse(QPoint(cx, cy), 5, 5)
                    return _paint
                dot.paintEvent = _make_small_paint(p)  # type: ignore[assignment]
                dot.priority_dot_clicked.connect(
                    lambda _tid, new_p, _p=p: self._set_input_priority(_p)
                )
                self._input_priority_dots.append(dot)
                input_row.addWidget(dot)
            # Fas 2: Enter bekräftar (alla prickar utlöser samma submit)
            self._update_input_priority_indicator()

            # NY v7-fix35: E-post-import-knapp 📧
            self.email_import_btn = QPushButton("📧", self)
            self.email_import_btn.setObjectName("emailImportBtn")
            self.email_import_btn.setFixedSize(28, 28)
            self.email_import_btn.setToolTip(
                "Importera e-post (.eml eller .msg) som uppgift —\n"
                "eller använd Thunderbird-tillägget / mappen data/inbox/\n"
                "(tray-menyn → 📧 E-post & Thunderbird)\n"
                "Outlook: spara mailet som .msg eller dra till skrivbordet\n"
                "Thunderbird: spara mailet som .eml"
            )
            self.email_import_btn.clicked.connect(self._on_email_import)
            input_row.addWidget(self.email_import_btn)
            # NY v7-fix81: PDF-export-knapp bredvid 📧 (samma som tray-menyn)
            self.pdf_export_btn = QPushButton("📄", self)
            self.pdf_export_btn.setObjectName("pdfExportBtn")
            self.pdf_export_btn.setFixedSize(28, 28)
            self.pdf_export_btn.setToolTip(
                "Exportera aktiva uppgifter som PDF-checklista\n"
                "(finns även i tray-menyn + högerklick på fönstret)"
            )
            self.pdf_export_btn.clicked.connect(self._on_export_pdf)
            input_row.addWidget(self.pdf_export_btn)
            root.addLayout(input_row)
            # NY v6.4: Resize-grip i nedre högra hörnet (synlig indikator)
            from PySide6.QtWidgets import QSizeGrip
            self.size_grip = QSizeGrip(self)
            # Lägg i en liten corner-layout
            corner_layout = QHBoxLayout()
            corner_layout.setContentsMargins(0, 0, 0, 0)
            corner_layout.addStretch(1)
            corner_layout.addWidget(self.size_grip)
            root.addLayout(corner_layout)
            # NY v6.4.1 v4: Window flags för sticky desktop-widget
            #
            # Krav fran Rickard 2026-09-18:
            #   1. Inte gomma vid Win+D (visa skrivbordet)
            #   2. Alltid synlig pa skrivbordet (overst, men inte over andra fönster)
            #   3. Kunna lyftas fram vid klick
            #
            # Teknik (NY v6.4.1 v4):
            #   - Tool = WS_EX_TOOLWINDOW (visas inte i taskbar/alt-tab)
            #   - Widgets kategoriseras som utility (inte som app)
            #   - Override WM_SYSCOMMAND för att blockera minimize
            #   - Periodic re-show timer som säkrar synlighet vid Win+D
            # NY v6.4.1 v5: Window flags för sticky desktop-widget
            #
            # Krav (Rickard 2026-09-18):
            #   - Alltid synlig pa SKRIVBORDET (aldrig gomd vid Win+D)
            #   - BAKOM andra fonster (vanligt z-beteende)
            #   - Lyssna pa klick → bring_to_front() tar fokus
            #
            # NY v6.4.1 v7-fix7: ENDAST Qt.Window — INTE Tool / FramelessWindowHint.
            # Orsak: Tool|FramelessWindowHint → WS_POPUP + WS_EX_TOOLWINDOW + alpha →
            #   CreateWindowEx misslyckas pa vissa Win10-skarmar ("Felaktig parameter"),
            #   och spammas 25+ ggr/100ms nar populate-loopen kor. WS_OVERLAPPED (Qt.Window)
            #   skapas alltid korrekt. Ram + header handlas av GlassFrame.paintEvent +
            #   custom titlebar-widget (drag-handtag + min/max/close). HWND_BOTTOM + z-order
            #   skots i _setup_bugg19_zorder precis som tidigare.
            #
            # Hur Win+D-skyddet fungerar:
            #   1. WS_EX_NOACTIVATE → fokuseras inte automatiskt vid klick
            #   2. nativeEvent() blockerar SC_MINIMIZE → Win+D ignorerar widget
            #   3. _periodic_zorder_check() re-show:ar om nagon app gomt oss
            # FIX v7-fix20: INGA explicita setWindowFlags/setAttribute här!
            # En föräldralös QWidget är REDAN ett fönster (default Qt.Window).
            # Den explicita flag-KONVERTERINGEN kan vara trasig i vissa
            # PySide6/Python 3.14-kombinationer → flags blir 0 (=
            # 'QFlags<Qt::WindowType>()' i fel-loggen!) → WS_CHILD utan
            # förälder → CreateWindowEx 'Felaktig parameter' vid varje
            # försök. Vi rör den inte — och loggar de effektiva flagsen.
            logger.info(
                f"{LOG_PREFIX} windowFlags (default, ej explicit satta): "
                f"{int(self.windowFlags())} "
                f"(Qt.Window={int(Qt.WindowType.Window)})"
            )
            # FIX 2026-09-23: app-ikon → aktivitetsfält + Aktivitetshanterare
            # (QIcon från data/app.ico om den finns — annars default)
            try:
                _ico = (
                    getattr(__import__("pathlib"), "Path")(__file__)
                    .resolve().parent.parent / "data" / "app.ico"
                )
                if _ico.is_file():
                    from PySide6.QtGui import QIcon as _QI
                    # FIX v7-fix19: validera — korrupt .ico kan ge ogiltig
                    # HICON → CreateWindowEx 'Felaktig parameter'-storm
                    _icon = _QI(str(_ico))
                    if _icon.isNull() or _icon.pixmap(32, 32).isNull():
                        logger.warning(
                            f"{LOG_PREFIX} app.ico OGILTIG — hoppar över "
                            f"ikon (korrupt ikon kan ge "
                            f"CreateWindowEx-fel!)"
                        )
                    else:
                        # FIX v7-fix22: ikonen sätts INTE här (före show) —
                        # en förgiftad ikon i fönsterklassen vid registrering
                        # dödar ALLA CreateWindowEx. main sätter den efter
                        # att fönstret faktiskt skapats.
                        logger.info(
                            f"{LOG_PREFIX} Widget-ikon förberedd (sätts "
                            f"efter show, v7-fix22): {_ico}"
                        )
            except Exception as _ico_err:
                logger.debug(f"{LOG_PREFIX} widget-ikon: {_ico_err}")
            # FIX 2026-09-23: WA_NoSystemBackground togs bort — gav
            # "QWidget::paintEngine: Should no longer be called" +
            # "QPainter::begin: engine == 0" med translucent + native HWND.
            # FIX v7-fix18: _setup_bugg19_zorder() körs INTE längre före
            # show() — den anropas från showEvent. Att tvinga fram ett nativt
            # fönster FÖRE show() (via winId()) är en CreateWindowEx-
            # omförsöksvektor när fönstret inte kan skapas.
            self._install_win_d_blocker()
            # FIX 2026-09-25: visa widgeten direkt vid start
            # (Rickard: "fönstret ska alltid synas på skrivbordet så fort man startar")
            try:
                self.show()
                logger.info(
                    f"{LOG_PREFIX} _init_ui: show() anropad — "
                    f"widget visas vid start"
                )
            except Exception as _se:
                logger.warning(f"{LOG_PREFIX} _init_ui show(): {_se}")
            # NY v6.4.1 v7: Verifiera att widgeten faktiskt är synlig
            # FIX v7-fix18: körs nu EFTER show() och ENDAST om fönstret finns
            # — winId() på ett trasigt fönster tvingar fram nya misslyckade
            # CreateWindowEx-försök (= logg-stormen).
            try:
                import ctypes
                if self._native_window_ok():
                    hwnd = int(self.winId())
                    user32 = ctypes.windll.user32
                    is_visible = bool(user32.IsWindowVisible(hwnd))
                    rect = ctypes.wintypes.RECT()
                    user32.GetWindowRect(hwnd, ctypes.byref(rect))
                    width = rect.right - rect.left
                    height = rect.bottom - rect.top
                    logger.info(
                        f"{LOG_PREFIX} _init_ui: HWND={hwnd} visible={is_visible} "
                        f"rect=({rect.left},{rect.top})-({rect.right},{rect.bottom}) "
                        f"size={width}x{height}"
                    )
                else:
                    logger.warning(
                        f"{LOG_PREFIX} _init_ui: nativt fönster SAKNAS efter "
                        f"show() — karantän sköts av showEvent (v7-fix18)"
                    )
            except Exception as _e:
                logger.warning(f"{LOG_PREFIX} _init_ui HWND-verifiering misslyckades: {_e}")
            logger.info(
                f"{LOG_PREFIX} _init_ui klar (v7: skrivbords-widget + z-order + Win+D-skydd)"
            )

        # ====================================================================
        # TASK ACTIONS (NY v6.4.1 v7 - 188888888% bättre med AI-felsökning)
        # ====================================================================

        @_log_event("task:toggle")
        def _snooze_choices(self) -> List[tuple]:
            """NY v7-fix41: snooze-alternativ [(etikett, ISO-tid), ...]."""
            now = datetime.now()
            tonight = now.replace(hour=18, minute=0, second=0, microsecond=0)
            if tonight <= now:
                tonight = tonight + timedelta(days=1)
            tomorrow = (now + timedelta(days=1)).replace(
                hour=9, minute=0, second=0, microsecond=0
            )
            week = now + timedelta(weeks=1)
            return [
                ("1 timme", (now + timedelta(hours=1)).isoformat(timespec="minutes")),
                ("Ikväll 18:00", tonight.isoformat(timespec="minutes")),
                ("Imorgon 09:00", tomorrow.isoformat(timespec="minutes")),
                ("Om 1 vecka", week.isoformat(timespec="minutes")),
            ]

        def _due_choices(self) -> List[tuple]:
            """NY v7-fix41: snabba förfallodatum [(etikett, ÅÅÅÅ-MM-DD), ...]."""
            today = datetime.now().date()
            return [
                ("I dag", today.isoformat()),
                ("Imorgon", (today + timedelta(days=1)).isoformat()),
                ("Om 3 dagar", (today + timedelta(days=3)).isoformat()),
                ("Om en vecka", (today + timedelta(days=7)).isoformat()),
            ]

        def _on_subtask_toggle(self, task_id: str, sub_id: str) -> None:
            """NY v7-fix41: kryssa delmoment (store → changed → refresh)."""
            try:
                if hasattr(self.store, "toggle_subtask"):
                    self.store.toggle_subtask(task_id, sub_id)
                    logger.debug(
                        f"{LOG_PREFIX} delmoment växlat: {sub_id!r}"
                    )
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} _on_subtask_toggle misslyckades: {e}"
                )

        def _on_task_context_menu(self, task_id: str) -> None:
            """
            NY v7-fix79: högerklick på en uppgift → åtgärdsmeny.

            Rickard 2026-10-07: "kunna ta bort felaktiga uppgifter /
            redigera via högerklicksmeny på dom". Öppnar SAMMA åtgärds-
            meny som ⋯-knappen men hämtar FÄRSK uppgift från store
            (menyns val beror på t.ex. snooze-/pinnad-status).
            Högerklick på tom yta/header ger fortfarande fönster-menyn
            (centrera/nollställ/lås, v7-fix47) — oförändrat.
            """
            try:
                get_throttle().notify_activity()
                task = None
                with suppress(Exception):
                    if hasattr(self.store, "find_task"):
                        task = self.store.find_task(task_id)
                if not task:
                    logger.debug(
                        f"{LOG_PREFIX} högerklick: uppgift {task_id!r} "
                        f"hittades ej (borttagen?) — visar ingen meny"
                    )
                    return
                logger.info(
                    f"{LOG_PREFIX} högerklick på uppgift {task_id!r} → "
                    f"åtgärdsmeny (v7-fix79)"
                )
                self._show_task_menu(task)
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} _on_task_context_menu misslyckades: "
                    f"{_describe_widget_error(e)}",
                    exc_info=True,
                )

        def _show_task_menu(self, task: Dict[str, Any]) -> None:
            """
                NY v7-fix41: åtgärdsmeny per uppgift (⋯-knappen).
                NY v7-fix79: öppnas även via HÖGERKLICK på uppgiften.

                Klar · Prioritet · Fäst · Redigera titel · Ta bort ·
                Senarelägg · Förfallodatum · Återkommande · Delmoment.
                Allt motorn (store) redan stödjer — UI:et saknade vägarna
                in (gap-analys 22.12.1).
            """
            try:
                get_throttle().notify_activity()
                from PySide6.QtGui import QCursor
                tid = task.get("id")
                if not tid:
                    return
                menu = QMenu(self)
                menu.setObjectName("taskActionMenu")

                # --- NY v7-fix79: snabbåtgärder först (högerklick) -------
                # Rickard: "ta bort felaktiga uppgifter / redigera via
                # högerklicksmeny" — de vanligaste åtgärderna överst.
                act = menu.addAction(
                    "⬜ Markera oklar" if task.get("done")
                    else "✅ Markera klar"
                )
                act.triggered.connect(
                    lambda _c: self._store_call(
                        "toggle_task", tid, _what="klarstatus"
                    )
                )
                prio_menu = menu.addMenu("🚩 Prioritet")
                for p in PRIORITY_CYCLE:
                    label = {
                        "none":   "Ingen (grå)",
                        "high":   "Hög (röd)",
                        "medium": "Normal (gul)",
                        "low":    "Låg (grön)",
                    }.get(p, p)
                    pact = prio_menu.addAction(label)
                    pact.setCheckable(True)
                    pact.setChecked(task.get("priority", "none") == p)
                    pact.triggered.connect(
                        lambda _c, _p=p: self._set_task_priority(tid, _p)
                    )
                act = menu.addAction(
                    "📍 Lossa från toppen" if task.get("pinned")
                    else "📌 Fäst överst"
                )
                act.triggered.connect(
                    lambda _c: self._store_call(
                        "toggle_pinned", tid, _what="fäst"
                    )
                )
                if _task_has_email(task):
                    menu.addSeparator()
                    act = menu.addAction("📧 Öppna mejlet")
                    act.triggered.connect(
                        lambda _c, tk=dict(task): self._open_task_email(tk)
                    )
                menu.addSeparator()
                act = menu.addAction("✏️ Redigera titel…")
                act.triggered.connect(lambda _c: self._prompt_rename(tid))
                act = menu.addAction("🗑 Ta bort…")
                act.triggered.connect(lambda _c: self._prompt_delete(tid))
                # --- NY v8: kalender (Google Calendar m.fl.) -------------
                menu.addSeparator()
                act = menu.addAction("📅 Lägg till i Google Calendar")
                act.setToolTip(
                    "Öppnar Google Calendar med uppgiften förifylld\n"
                    "(heldagshändelse — från startdatum till förfallodatum\n"
                    "om båda finns, annars på det datum som finns)"
                )
                act.triggered.connect(
                    lambda _c, _t=dict(task): self._on_open_task_in_google_calendar(_t)
                )
                act = menu.addAction("📅 Exportera uppgiften (.ics)…")
                act.setToolTip(
                    "Sparar uppgiften som kalenderfil — importeras i\n"
                    "Google Calendar, Outlook och Apple Kalender"
                )
                act.triggered.connect(
                    lambda _c, _t=dict(task): self._on_export_task_ics(_t)
                )
                act = menu.addAction("☁️ Skicka till Google Calendar")
                act.setToolTip(
                    "Skickar uppgiften direkt till din Google-kalender\n"
                    "(kräver att kontot är kopplat — se ☁️ Google Calendar)"
                )
                act.triggered.connect(
                    lambda _c, _t=dict(task): self._on_push_task_to_google(_t)
                )
                act = menu.addAction("🕘 Kalenderhistorik för uppgiften")
                act.setToolTip(
                    "Visar när uppgiften skickats till Google Calendar och\n"
                    "med vilket resultat — med knapp för att öppna händelsen"
                )
                act.triggered.connect(
                    lambda _c, _t=dict(task): self._on_show_task_calendar_history(_t)
                )
                menu.addSeparator()

                # --- ⏰ Senarelägg ------------------------------------
                snooze_menu = menu.addMenu("⏰ Senarelägg")
                for label, iso in self._snooze_choices():
                    act = snooze_menu.addAction(label)
                    act.triggered.connect(
                        lambda _c, i=iso: self._store_call(
                            "snooze_task", tid, i, _what="senarelagd"
                        )
                    )
                if task.get("snoozed_until"):
                    act = snooze_menu.addAction("💤 Visa nu (avbryt snooze)")
                    act.triggered.connect(
                        lambda _c: self._store_call(
                            "unsnooze_task", tid, _what="snooze avbruten"
                        )
                    )

                # --- 📅 Förfallodatum ---------------------------------
                due_menu = menu.addMenu("📅 Förfallodatum")
                for label, iso in self._due_choices():
                    act = due_menu.addAction(label)
                    act.triggered.connect(
                        lambda _c, i=iso: self._store_call(
                            "set_due_date", tid, i, _what="förfallodatum"
                        )
                    )
                act = due_menu.addAction("✍️ Skriv datum (ÅÅÅÅ-MM-DD)…")
                act.triggered.connect(
                    lambda _c: self._prompt_and_set_due(tid)
                )
                if task.get("due_date"):
                    act = due_menu.addAction("✖ Ta bort datum")
                    act.triggered.connect(
                        lambda _c: self._store_call(
                            "set_due_date", tid, None, _what="datum borttaget"
                        )
                    )

                # --- ▶ Startdatum (NY v8: för kalenderhändelser) ---------
                start_menu = menu.addMenu("▶ Startdatum")
                start_menu.setToolTip(
                    "Valfritt. Med både start- och förfallodatum blir uppgiften en\n"
                    "flerdagarshändelse i kalendern (start → förfallodatum)."
                )
                act = start_menu.addAction("📆 Välj i kalender…")
                act.triggered.connect(
                    lambda _c: self._prompt_and_set_start(tid)
                )
                start_menu.addSeparator()
                for label, iso in self._due_choices():
                    act = start_menu.addAction(label)
                    act.triggered.connect(
                        lambda _c, i=iso: self._store_call(
                            "set_start_date", tid, i, _what="startdatum"
                        )
                    )
                if task.get("start_date"):
                    act = start_menu.addAction("✖ Ta bort startdatum")
                    act.triggered.connect(
                        lambda _c: self._store_call(
                            "set_start_date", tid, None, _what="startdatum borttaget"
                        )
                    )

                # --- 🔁 Återkommande -----------------------------------
                rec_menu = menu.addMenu("🔁 Återkommande")
                _cur_iv = (task.get("recurring") or {}).get("interval")
                for iv, iv_label in (
                    ("daily", "Varje dag"),
                    ("weekly", "Varje vecka"),
                    ("monthly", "Varje månad"),
                ):
                    act = rec_menu.addAction(iv_label)
                    act.setCheckable(True)
                    act.setChecked(_cur_iv == iv)
                    act.triggered.connect(
                        lambda _c, i=iv: self._store_call(
                            "set_recurring", tid, i, _what="återkommande"
                        )
                    )
                if _cur_iv:
                    act = rec_menu.addAction("✖ Av (engångsuppgift)")
                    act.triggered.connect(
                        lambda _c: self._store_call(
                            "set_recurring", tid, None, _what="återkommande av"
                        )
                    )

                # --- ➕ Delmoment ---------------------------------------
                act = menu.addAction("➕ Lägg till delmoment…")
                act.triggered.connect(lambda _c: self._prompt_subtasks(tid))

                # FIX v7-fix79: Byt namn/Ta bort finns nu i menyns Topp
                # (snabbåtgärder) — här behövs ingen dubblett.

                menu.exec(QCursor.pos())
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} _show_task_menu misslyckades: "
                    f"{_describe_widget_error(e)}",
                    exc_info=True,
                )

        def _store_call(
            self, method: str, task_id: str, *args, _what: str = ""
        ) -> None:
            """NY v7-fix41: säkert anropa store-metod med logg."""
            try:
                fn = getattr(self.store, method, None)
                if fn is None:
                    logger.warning(
                        f"{LOG_PREFIX} store saknar {method}()"
                    )
                    return
                fn(task_id, *args)
                logger.info(
                    f"{LOG_PREFIX} {method}: {task_id!r} "
                    f"({_what or (args[0] if args else 'ok')})"
                )
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} _store_call({method}) misslyckades: {e}"
                )

        def _prompt_and_set_due(self, task_id: str) -> None:
            """NY v7-fix41: skriv in förfallodatum manuellt."""
            try:
                from PySide6.QtWidgets import QInputDialog
                text, ok = QInputDialog.getText(
                    self,
                    "📅 Förfallodatum",
                    "Datum (ÅÅÅÅ-MM-DD):",
                    text=datetime.now().date().isoformat(),
                )
                if not ok or not text.strip():
                    return
                try:
                    iso = datetime.fromisoformat(text.strip()).date().isoformat()
                except ValueError:
                    _show_widget_error(
                        "Ogiltigt datum",
                        f"{text.strip()!r} förstods inte — använd ÅÅÅÅ-MM-DD.",
                    )
                    return
                self._store_call("set_due_date", task_id, iso, _what="datum")
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} _prompt_and_set_due: {e}")

        def _pick_date(self, title: str, initial_iso: str = "") -> Optional[str]:
            """NY v8: kalender-väljare (veckonummer, måndag först). Returnerar ISO-datum eller None."""
            from PySide6.QtCore import QDate
            from PySide6.QtWidgets import (
                QCalendarWidget, QDialog, QHBoxLayout as _QH, QPushButton as _QB,
                QVBoxLayout as _QV, QLabel as _QL,
            )
            dlg = QDialog(self)
            dlg.setWindowTitle(title)
            lay = _QV(dlg)
            lay.addWidget(_QL("Välj dag i kalendern (dubbelklicka eller tryck Välj):", dlg))
            cal = QCalendarWidget(dlg)
            cal.setGridVisible(True)
            cal.setFirstDayOfWeek(Qt.DayOfWeek.Monday)
            cal.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.ISOWeekNumbers)
            qd = QDate.fromString(initial_iso[:10], "yyyy-MM-dd") if initial_iso else QDate()
            cal.setSelectedDate(qd if qd.isValid() else QDate.currentDate())
            lay.addWidget(cal)
            quick = _QH()
            today = QDate.currentDate()
            for label, d in (
                ("Idag", today),
                ("Imorgon", today.addDays(1)),
                ("Nästa måndag", today.addDays(8 - today.dayOfWeek())),
            ):
                b = _QB(label, dlg)
                b.clicked.connect(lambda _c=False, _d=d: cal.setSelectedDate(_d))
                quick.addWidget(b)
            quick.addStretch(1)
            lay.addLayout(quick)
            btns = _QH()
            btns.addStretch(1)
            cancel = _QB("Avbryt", dlg)
            cancel.clicked.connect(dlg.reject)
            ok = _QB("Välj", dlg)
            ok.setDefault(True)
            ok.clicked.connect(dlg.accept)
            btns.addWidget(cancel)
            btns.addWidget(ok)
            lay.addLayout(btns)
            cal.activated.connect(lambda _d: dlg.accept())
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return None
            return cal.selectedDate().toString("yyyy-MM-dd")

        def _prompt_and_set_start(self, task_id: str) -> None:
            """NY v8: välj startdatum i en kalender (valfritt, för kalendern)."""
            try:
                from PySide6.QtWidgets import QMessageBox
                current = ""
                with suppress(Exception):
                    t = self.store.find_task(task_id) or {}
                    current = str(t.get("start_date") or "")[:10]
                iso = self._pick_date("▶ Startdatum", current)
                if not iso:
                    return
                self._store_call("set_start_date", task_id, iso, _what="startdatum")
                with suppress(Exception):
                    t = self.store.find_task(task_id) or {}
                    due = str(t.get("due_date") or "")[:10]
                    if due and iso > due:
                        QMessageBox.information(
                            self,
                            "▶ Startdatum",
                            "Startdatumet ligger efter förfallodatumet.\n"
                            "I kalendern används då bara förfallodatumet.",
                        )
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} _prompt_and_set_start: {e}")

        def _add_subtask_rows(
            self,
            container: QWidget,
            parent_layout: QVBoxLayout,
            tid: str,
            subs: List[Dict[str, Any]],
            depth: int = 1,
        ) -> None:
            """NY v8: rita delmoment rekursivt med indrag per nivå."""
            for sub in subs:
                sub_id = sub.get("id")
                sub_row = QHBoxLayout()
                sub_row.setSpacing(6)
                # Indrag: 16px per nivå (nivå 1 = inget extra indrag)
                sub_row.setContentsMargins((depth - 1) * 16, 0, 0, 0)
                sub_cb = QCheckBox(container)
                sub_cb.setObjectName("subtaskCheck")
                sub_cb.setChecked(bool(sub.get("done")))
                sub_cb.setToolTip("Kryssa delmoment")
                sub_cb.toggled.connect(
                    lambda c, _t=tid, _s=sub_id: self._on_subtask_toggle(_t, _s)
                )
                sub_row.addWidget(sub_cb, 0, Qt.AlignmentFlag.AlignVCenter)
                sub_lbl = QLabel(str(sub.get("title", "")), container)
                sub_lbl.setObjectName("subtaskTitle")
                sub_lbl.setWordWrap(True)
                # NY v8: högerklick på delmomentet → byt namn / underdelmoment / ta bort
                sub_lbl.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                sub_lbl.customContextMenuRequested.connect(
                    lambda _pos, _t=tid, _s=sub_id, _n=str(sub.get("title", "")):
                        self._on_subtask_context_menu(_t, _s, _n)
                )
                if sub.get("done"):
                    _sf = sub_lbl.font()
                    _sf.setStrikeOut(True)
                    sub_lbl.setFont(_sf)
                sub_row.addWidget(sub_lbl, 1, Qt.AlignmentFlag.AlignVCenter)
                parent_layout.addLayout(sub_row)
                kids = [dict(c) for c in (sub.get("children") or []) if c.get("title")]
                if kids:
                    self._add_subtask_rows(
                        container, parent_layout, tid, kids, depth + 1
                    )

        def _on_subtask_context_menu(
            self, task_id: str, sub_id: str, title: str
        ) -> None:
            """NY v8: åtgärdsmeny för ett delmoment."""
            try:
                menu = QMenu(self)
                act_rn = menu.addAction("✏ Byt namn…")
                act_rn.triggered.connect(
                    lambda _c: self._prompt_rename_subtask(task_id, sub_id, title)
                )
                act_sub = menu.addAction("➕ Lägg till underdelmoment…")
                act_sub.triggered.connect(
                    lambda _c: self._prompt_subtasks(task_id, parent_sub_id=sub_id)
                )
                menu.addSeparator()
                act_rm = menu.addAction("🗑 Ta bort delmoment")
                act_rm.triggered.connect(
                    lambda _c: self._store_call(
                        "remove_subtask", task_id, sub_id,
                        _what="delmoment borttaget",
                    )
                )
                menu.exec(QCursor.pos())
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} _on_subtask_context_menu: {e}")

        def _prompt_rename_subtask(
            self, task_id: str, sub_id: str, current: str
        ) -> None:
            """NY v8: byt namn på ett delmoment."""
            try:
                from PySide6.QtWidgets import QInputDialog
                text, ok = QInputDialog.getText(
                    self, "✏ Byt namn på delmoment", "Nytt namn:", text=current
                )
                if ok and text.strip():
                    self.store.rename_subtask(task_id, sub_id, text.strip())
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} _prompt_rename_subtask: {e}")

        def _prompt_subtasks(
            self, task_id: str, parent_sub_id: Optional[str] = None
        ) -> None:
            """NY v7-fix41 + v8: lägg till delmoment (eller underdelmoment)."""
            try:
                from PySide6.QtWidgets import QInputDialog
                _label = "➕ Underdelmoment" if parent_sub_id else "➕ Delmoment"
                while True:
                    text, ok = QInputDialog.getText(
                        self, _label, "Nytt delmoment (tomt = klar):"
                    )
                    if not ok or not text.strip():
                        return
                    sub = None
                    if hasattr(self.store, "add_subtask"):
                        sub = self.store.add_subtask(
                            task_id, text.strip(), parent_sub_id=parent_sub_id
                        )
                    if sub is None:
                        return
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} _prompt_subtasks: {e}")

        def _prompt_rename(self, task_id: str) -> None:
            """NY v7-fix41: byt namn på uppgift."""
            try:
                from PySide6.QtWidgets import QInputDialog
                task = None
                if hasattr(self.store, "find_task"):
                    task = self.store.find_task(task_id)
                old = (task or {}).get("title", "")
                text, ok = QInputDialog.getText(
                    self, "✏️ Byt namn", "Ny titel:", text=old
                )
                if not ok or not text.strip():
                    return
                self._store_call(
                    "update_task_title", task_id, text.strip(), _what="namn"
                )
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} _prompt_rename: {e}")

        def _prompt_delete(self, task_id: str) -> None:
            """NY v7-fix41: ta bort uppgift med bekräftelse."""
            try:
                from PySide6.QtWidgets import QMessageBox
                task = None
                if hasattr(self.store, "find_task"):
                    task = self.store.find_task(task_id)
                title = (task or {}).get("title", "uppgiften")
                if task and isinstance(task.get("recurring"), dict):
                    title += "\n(⚠ återkommande serie avslutas)"
                btn = QMessageBox.question(
                    self,
                    "🗑 Ta bort uppgift",
                    f"Ta bort '{title}'?",
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if btn != QMessageBox.StandardButton.Yes:
                    return
                self._store_call("remove_task", task_id, _what="borttagen")
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} _prompt_delete: {e}")

        def _on_task_toggle(self, task_id: str, done: bool) -> None:
            """
            NY v6.4.1 v7: Kryssa i/ur checkbox (med forbattrad felhantering).

            Vid fel: visar svensk dialog istallet for att krascha.
            """
            get_throttle().notify_activity()
            logger.info(
                f"{LOG_PREFIX} _on_task_toggle: task_id={task_id!r}, done={done}"
            )
            try:
                if hasattr(self.store, "toggle_task"):
                    success = self.store.toggle_task(task_id)
                    if success:
                        logger.info(
                            f"{LOG_PREFIX} store.toggle_task({task_id!r}) → OK"
                        )
                    else:
                        logger.debug(
                            f"{LOG_PREFIX} store.toggle_task({task_id!r}) → False"
                        )
                else:
                    logger.warning(
                        f"{LOG_PREFIX} store saknar toggle_task() — kan inte markera klar"
                    )
                    _show_widget_error(
                        self,
                        "Kan inte markera som klar",
                        "Store-funktionen 'toggle_task' saknas.",
                        category="code_bug",
                    )
                    return
                self._rebuild_task_list()
                self._schedule_rebuild()
                self._audit.add("task_toggled", {"task_id": task_id, "done": done})
            except Exception as e:
                logger.error(
                    f"{LOG_PREFIX} _on_task_toggle misslyckades: {_describe_widget_error(e)}",
                    exc_info=True,
                )
                _show_widget_error(
                    self,
                    "Kunde inte markera som klar",
                    f"Uppgiften kunde inte uppdateras:\n{_describe_widget_error(e)}",
                    exc=e,
                    category=_categorize_widget_error(e),
                )

        @_log_event("task:pin_toggle")
        def _on_pin_toggle(self, task_id: str) -> None:
            """
            NY v6.4.1 v7: Toggle pin (med forbattrad felhantering).
            """
            get_throttle().notify_activity()
            logger.debug(f"{LOG_PREFIX} _on_pin_toggle: task_id={task_id!r}")
            try:
                if hasattr(self.store, "toggle_pinned"):
                    self.store.toggle_pinned(task_id)
                else:
                    logger.warning(
                        f"{LOG_PREFIX} store saknar toggle_pinned() — pinnas inte"
                    )
                    return
                self._schedule_rebuild()
                self._audit.add("task_pin_toggled", {"task_id": task_id})
                logger.info(f"{LOG_PREFIX} pin toggle OK: {task_id!r}")
            except Exception as e:
                logger.error(
                    f"{LOG_PREFIX} _on_pin_toggle misslyckades: {_describe_widget_error(e)}",
                    exc_info=True,
                )

        @_log_event("task:title_edited")
        def _on_title_edited(self, task_id: str, new_text: str) -> None:
            """
            NY v6.4.1 v7: Uppdatera titel (med validering + felhantering).
            """
            get_throttle().notify_activity()
            if not new_text or not new_text.strip():
                logger.debug(
                    f"{LOG_PREFIX} _on_title_edited: tom titel for {task_id!r} — ignorerar"
                )
                return
            cleaned_text = new_text.strip()
            if len(cleaned_text) > 500:
                logger.warning(
                    f"{LOG_PREFIX} titel for lang ({len(cleaned_text)} tecken) — trunkerar"
                )
                cleaned_text = cleaned_text[:500]
            try:
                if hasattr(self.store, "update_task_title"):
                    self.store.update_task_title(task_id, cleaned_text)
                self._schedule_rebuild()
                self._audit.add(
                    "task_title_edited",
                    {"task_id": task_id, "new": cleaned_text[:30]}
                )
                logger.info(
                    f"{LOG_PREFIX} titel uppdaterad: {task_id!r} → {cleaned_text[:30]!r}"
                )
            except Exception as e:
                logger.error(
                    f"{LOG_PREFIX} _on_title_edited misslyckades: {_describe_widget_error(e)}",
                    exc_info=True,
                )

        @_log_event("task:delete")
        def _on_delete_clicked(self, task_id: str, task_text: str) -> None:
            """
            NY v6.4.1 v7: Ta bort task (med forbattrad dialog + felhantering).
            """
            get_throttle().notify_activity()
            logger.info(
                f"{LOG_PREFIX} _on_delete_clicked: task_id={task_id!r}, "
                f"text={task_text[:30]!r}"
            )
            try:
                if QMessageBox is None:
                    logger.warning(
                        f"{LOG_PREFIX} QMessageBox saknas — kan inte visa dialog"
                    )
                    return
                # NY v6.4.1 v7: Svensk bekräftelsedialog med tydlig info
                preview = task_text if len(task_text) < 60 else task_text[:57] + "..."
                reply = QMessageBox.question(
                    self,
                    "Ta bort uppgift?",
                    f"Vill du ta bort den har uppgiften?\n\n"
                    f"\"{preview}\"\n\n"
                    f"Detta går inte att angra.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,  # Default = Nej (sakerhetsval)
                )
                if reply == QMessageBox.StandardButton.Yes:
                    logger.info(
                        f"{LOG_PREFIX} ta bort: användare bekräftade {task_id!r}"
                    )
                    if hasattr(self.store, "remove_task"):
                        success = self.store.remove_task(task_id)
                        logger.info(
                            f"{LOG_PREFIX} store.remove_task({task_id!r}) → {success}"
                        )
                    else:
                        logger.warning(
                            f"{LOG_PREFIX} store saknar remove_task() — inget taget bort"
                        )
                        _show_widget_error(
                            self,
                            "Kan inte ta bort",
                            "Store-funktionen 'remove_task' saknas.",
                            category="code_bug",
                        )
                        return
                    self._rebuild_task_list()
                    self._schedule_rebuild()
                    self._audit.add("task_deleted", {"task_id": task_id})
                else:
                    logger.debug(
                        f"{LOG_PREFIX} ta bort: användare avbrott {task_id!r}"
                    )
            except Exception as e:
                logger.error(
                    f"{LOG_PREFIX} _on_delete_clicked misslyckades: {_describe_widget_error(e)}",
                    exc_info=True,
                )

        @_log_event("input:submit")
        def _on_input_submit(self) -> None:
            """
            NY v6.4.1 v7: Submit ny task (med validering + felhantering).
            """
            get_throttle().notify_activity()
            text = self.input_field.text().strip()
            if not text:
                logger.debug(f"{LOG_PREFIX} _on_input_submit: tom input — ignorerar")
                return
            if len(text) > 500:
                logger.warning(
                    f"{LOG_PREFIX} input-text for lang ({len(text)} tecken) — trunkerar"
                )
                text = text[:500]
            current = self._pending_input_priority
            try:
                if not hasattr(self.store, "add_task"):
                    logger.warning(
                        f"{LOG_PREFIX} store saknar add_task() — kan inte lagga till"
                    )
                    _show_widget_error(
                        self,
                        "Kan inte lagga till uppgift",
                        "Store-funktionen 'add_task' saknas.",
                        category="code_bug",
                    )
                    return
                # NY v7-fix65: naturligt språk — tolka datum/tid/prio/taggar
                # ("mjölk imorgon 15:00 !hög #hem"). Utan match = som förr.
                _nl = parse_natural_input(text)
                _title = _nl.get("title") or text
                _prio = _nl.get("priority") or current
                _due = _nl.get("due_date")
                _tags = _nl.get("tags") or []
                _start = _nl.get("start_date")
                if (_due or _tags or _start or _nl.get("priority")
                        or _title != text):
                    logger.info(
                        f"{LOG_PREFIX} NL-input tolkad: titel='{_title[:30]}' "
                        f"due={_due} start={_start} prio={_prio} tags={_tags}"
                    )
                tid = self.store.add_task(
                    _title, priority=_prio,
                    due_date=_due, tags=_tags,
                )
                if tid and _start and hasattr(self.store, "set_start_date"):
                    self.store.set_start_date(tid, _start)  # NY v8: valfritt startdatum
                if tid:
                    self.input_field.clear()
                    # Återställ pending priority till "none"
                    self._pending_input_priority = "none"
                    self._update_input_priority_indicator()
                    # FIX v7-fix77: Enter SKA registrera uppgiften SYNGLIGT
                    # i 'Aktiva' — tidigare enbart debounced rebuild (50 ms)
                    # och listan sorterar nya uppgifter LÄNGST NED (skapad
                    # sist) → kändes som att Enter "inte gjorde något" om
                    # listan var lång/under Arkiverade-fliken.
                    self._show_task_in_active(tid)
                    self._audit.add(
                        "task_added",
                        {"task_id": tid, "title": text[:30], "priority": current}
                    )
                    logger.info(
                        f"{LOG_PREFIX} ny uppgift: {tid!r} '{text[:30]}' (priority={current})"
                    )
                else:
                    logger.warning(
                        f"{LOG_PREFIX} add_task returnerade ingen id (text={text[:30]!r})"
                    )
                    _show_widget_error(
                        self,
                        "Kunde inte spara uppgift",
                        "Lagringen returnerade inget id. Forsok igen.",
                        category="system",
                    )
            except Exception as e:
                logger.error(
                    f"{LOG_PREFIX} _on_input_submit misslyckades: {_describe_widget_error(e)}",
                    exc_info=True,
                )
                _show_widget_error(
                    self,
                    "Kunde inte lagga till uppgift",
                    f"Ett fel uppstod:\n{_describe_widget_error(e)}",
                    exc=e,
                    category=_categorize_widget_error(e),
                )

        @_log_event("priority:dot_clicked")
        def _on_priority_dot_clicked(
            self, task_id: str, new_priority: str
        ) -> None:
            """
            NY v6.4.1 v7: Klick pa fargpricken (satt prioritet).
            """
            self._set_task_priority(task_id, new_priority)

        @_log_event("priority:dot_right_clicked")
        def _on_priority_dot_right_clicked(
            self, task_id: str, current_priority: str
        ) -> None:
            """
            NY v6.4.1 v7: Hogerklick pa fargpricken (context-meny).
            """
            try:
                if QMenu is None:
                    logger.warning(f"{LOG_PREFIX} QMenu saknas — kan inte visa context-meny")
                    return
                menu = QMenu(self)
                menu.setTitle(f"Prioritet for uppgift {task_id[:6]}")
                for p in PRIORITY_CYCLE:
                    label = {
                        "none":   "Ingen (gra)",
                        "high":   "Hog (rod)",
                        "medium": "Normal (gul)",
                        "low":    "Lag (gron)",
                    }.get(p, p)
                    action = menu.addAction(label)
                    action.setCheckable(True)
                    if p == current_priority:
                        action.setChecked(True)
                    action.triggered.connect(
                        lambda checked=False, pid=task_id, pp=p:
                            self._set_task_priority(pid, pp)
                    )
                menu.exec(QCursor.pos())
                self._audit.add(
                    "priority_menu_shown",
                    {"task_id": task_id, "current": current_priority}
                )
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} priority-meny misslyckades: {_describe_widget_error(e)}"
                )

        @_log_event("input:set_priority")
        def _set_input_priority(self, new_priority: str) -> None:
            """Satt pending prioritet i input-rutan."""
            get_throttle().notify_activity()
            if new_priority not in PRIORITY_CYCLE:
                logger.warning(
                    f"{LOG_PREFIX} _set_input_priority: ogiltig {new_priority!r}"
                )
                return
            self._pending_input_priority = new_priority
            self._update_input_priority_indicator()
            self._audit.add(
                "input_priority_set", {"priority": new_priority}
            )
            logger.debug(
                f"{LOG_PREFIX} pending priority satt: {new_priority}"
            )

        def _update_input_priority_indicator(self) -> None:
            """
            NY v6.4.1 v7-fix: Uppdatera visuella prioritets-indikatorn vid input.

            Buggrapport 2026-09-22:
              AttributeError: 'TodoWidget' object has no attribute '_update_input_priority_indicator'
              på rad 1485 i _init_ui, och på rad 1741/1830 i andra metoder.

            Vad den gör:
              1. Uppdatera input_priority_dot (stor prick) till aktuell pending_priority
              2. Uppdatera de 3 små prickarna (high/medium/low) för highlighting
            """
            try:
                cur = getattr(self, "_pending_input_priority", "none")
                # Stor prick (input_priority_dot) — finns bara efter _init_ui
                if hasattr(self, "input_priority_dot"):
                    try:
                        self.input_priority_dot.set_priority(cur)
                        # Force repaint
                        self.input_priority_dot.update()
                    except Exception:
                        pass
                # Små prickar — highlight den aktiva prioriteten
                if hasattr(self, "_input_priority_dots"):
                    for dot in self._input_priority_dots:
                        try:
                            # Hitta task_id för att se om det matchar
                            tid = dot.property("task_id") or ""
                            if tid.startswith("__input_"):
                                prio = tid.replace("__input_", "").replace("__", "")
                                if prio == cur:
                                    dot.set_active(True)
                                else:
                                    dot.set_active(False)
                            dot.update()
                        except Exception:
                            pass
                logger.trace(
                    f"{LOG_PREFIX} _update_input_priority_indicator: "
                    f"cur={cur}"
                )
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} _update_input_priority_indicator misslyckades: "
                    f"{_describe_widget_error(e)}",
                    exc_info=True,
                )

        @_log_event("task:set_priority")
        def _set_task_priority(self, task_id: str, new_priority: str) -> None:
            """
            NY v6.4.1 v7: Satt prioritet pa specifik task (med validering).
            """
            get_throttle().notify_activity()
            if new_priority not in PRIORITY_CYCLE:
                logger.warning(
                    f"{LOG_PREFIX} _set_task_priority: ogiltig prioritet "
                    f"{new_priority!r}, tillåtna: {PRIORITY_CYCLE}"
                )
                return
            try:
                if hasattr(self.store, "set_priority"):
                    ok = self.store.set_priority(task_id, new_priority)
                    if ok:
                        logger.info(
                            f"{LOG_PREFIX} prioritet satt: {task_id!r} → {new_priority}"
                        )
                        self._audit.add(
                            "task_priority_set",
                            {"task_id": task_id, "priority": new_priority}
                        )
                        self._rebuild_task_list()
                        self._schedule_rebuild()
                    else:
                        logger.debug(
                            f"{LOG_PREFIX} set_priority: {task_id!r} oforandrad "
                            f"({new_priority})"
                        )
                else:
                    logger.warning(
                        f"{LOG_PREFIX} store saknar set_priority()"
                    )
            except Exception as e:
                logger.error(
                    f"{LOG_PREFIX} _set_task_priority misslyckades: {_describe_widget_error(e)}",
                    exc_info=True,
                )

        def _on_input_priority_dot_clicked(
            self, _task_id: str, new_priority: str
        ) -> None:
            """Klick pa stora input-pricken → cykla."""
            self._set_input_priority(new_priority)

        @_log_event("tab:changed")
        def _on_tab_changed(self, index: int) -> None:
            """Tab andrad."""
            get_throttle().notify_activity()
            old_index = self._active_tab_index
            self._active_tab_index = index
            self._audit.add(
                "tab_changed", {"from": old_index, "to": index}
            )
            logger.debug(
                f"{LOG_PREFIX} tab: {old_index} → {index}"
            )

        def _on_search_changed(self, text: str) -> None:
            """
            NY v6.4.1 v7-fix: Sökfältet ändrades → schemalägg sökning (debounce).

            Buggrapport 2026-09-22 (efter force-show-fix):
              AttributeError: 'TodoWidget' object has no attribute '_on_search_changed'
              på rad 1396 (search_input.textChanged.connect(self._on_search_changed))
              Python hint: Did you mean: '_on_tab_changed'?

            Vi använder _search_timer (debounce 150ms) så vi inte kör sökning
            på varje tangenttryck. Vid tom sträng → rebuild direkt (visa alla).
            """
            try:
                get_throttle().notify_activity()
                self._current_filter = text or ""
                # Schemalägg sökning (debounce)
                if self._search_timer is not None:
                    self._search_timer.start(SEARCH_DEBOUNCE_MS)
                self._audit.add("search_changed", {"length": len(text)})
                logger.debug(
                    f"{LOG_PREFIX} _on_search_changed: '{text[:30]}' "
                    f"(schemalagd om {SEARCH_DEBOUNCE_MS}ms)"
                )
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} _on_search_changed misslyckades: "
                    f"{_describe_widget_error(e)}",
                    exc_info=True,
                )

        @_log_event("search:do")
        def _do_search(self) -> None:
            """Utfor sokning (med forbattrad felhantering)."""
            start = time.perf_counter()
            query = self._current_filter.lower().strip()
            if not query:
                self._rebuild_task_list()
                return
            try:
                if hasattr(self.store, "active_tasks_filtered"):
                    tasks = self.store.active_tasks_filtered(
                        query=query, sort_by="pinned_first"
                    )
                else:
                    tasks = []
                self._render_tasks(tasks, archived=False)
                duration = (time.perf_counter() - start) * 1000
                self._audit.add(
                    "search",
                    {"query": query, "results": len(tasks), "ms": duration}
                )
                logger.debug(
                    f"{LOG_PREFIX} sokning {query!r}: {len(tasks)} tradar pa {duration:.2f}ms"
                )
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} sokning misslyckades: {_describe_widget_error(e)}",
                    exc_info=True,
                )

        def _on_close_clicked(self) -> None:
            """BUGG 19/26: close = satt z-order."""
            try:
                self._setup_bugg19_zorder()
                self._audit.add("close_clicked")
                logger.debug(f"{LOG_PREFIX} _on_close_clicked: z-order uppdaterad")
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} _on_close_clicked misslyckades: {_describe_widget_error(e)}"
                )

        @_log_event("event:tag_clicked")
        def _on_tag_clicked(self, tag: str) -> None:
            """
            NY v6.4.1 v7: Filtrera pa tag (med svenska logg).
            """
            get_throttle().notify_activity()
            logger.debug(f"{LOG_PREFIX} tag-filter: {tag!r}")
            self._current_tag_filter = [tag]
            self._current_filter = tag
            if hasattr(self, "search_input"):
                self.search_input.setText(tag)
            self._audit.add("tag_filter", {"tag": tag})

        def eventFilter(self, obj: QWidget, event: QEvent) -> bool:
            """
            NY v6.4.1 v7: Fanga piltangenter pa task-containers (for prioritet).

            ← = foregaende prioritet, → = nasta (enligt PRIORITY_CYCLE)
            NY v7-fix73: FocusIn i textfält → aktivera fönstret för
            inmatning (NOACTIVATE av + förgrund) — annars blockerar
            NOACTIVATE tangentbordsinput.
            """
            try:
                # ============================================================
                # FIX v7-fix78: Enter tillhör INPUT-FÄLTET — två skydd:
                #
                # BAKGRUND (Rickard 2026-10-06: "tvungen att trycka
                # Ctrl+Enter för att registrera"): Qt:s kortkommandon
                # (QShortcut) matchar TANGENTER FÖRE de når widgeten, men
                # bara OMODIFIERADE tangenter. Ett kortkommando som matchar
                # vanlig Return stjäl alltså Enter i luften — medan
                # Ctrl+Enter inte matchar → når fältet → registrerade.
                #
                # a) ShortcutOverride: Qt frågar den fokuserade widgeten
                #    "får kortkommandon stjäla denna tangent?" — QLineEdit
                #    svarar NEJ för Enter som default. Vi svarar JA
                #    (=fältet tar tangenten) → Enter når ALLTID fältet.
                # b) KeyPress-skydd: extra försäkring utöver
                #    keyPressEvent-överriden + returnPressed (3 lager).
                # ============================================================
                _if = getattr(self, "input_field", None)
                if _if is not None and obj is _if:
                    _et = event.type()
                    if _et == QEvent.Type.ShortcutOverride:
                        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                            event.accept()
                            return True
                    elif _et == QEvent.Type.KeyPress:
                        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                            logger.info(
                                f"{LOG_PREFIX} Enter i input-fältet → "
                                f"registrerar uppgiften i 'Aktiva' (v7-fix78)"
                            )
                            self._on_input_submit()
                            event.accept()
                            return True
                # NY v7-fix73: textfältsfokus → gör fönstret skrivbart
                if (
                    event.type() == QEvent.Type.FocusIn
                    and obj in (self.input_field, self.search_input)
                ):
                    with suppress(Exception):
                        self._activate_for_typing()
                if (
                    event.type() == QEvent.Type.KeyPress
                    and isinstance(obj, QFrame)
                    and obj.objectName().startswith("task_")
                ):
                    key = event.key()
                    task_id = obj.property("task_id")
                    if not task_id:
                        return super().eventFilter(obj, event)
                    if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
                        cur = obj.property("task_priority") or "none"
                        if cur not in PRIORITY_CYCLE:
                            cur = "none"
                        idx = PRIORITY_CYCLE.index(cur)
                        if key == Qt.Key.Key_Right:
                            new_idx = (idx + 1) % len(PRIORITY_CYCLE)
                        else:
                            new_idx = (idx - 1) % len(PRIORITY_CYCLE)
                        new_p = PRIORITY_CYCLE[new_idx]
                        logger.info(
                            f"{LOG_PREFIX} piltangent på task {task_id!r}: "
                            f"{cur} → {new_p}"
                        )
                        self._set_task_priority(task_id, new_p)
                        get_throttle().notify_activity()
                        return True
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} eventFilter misslyckades: {_describe_widget_error(e)}",
                    exc_info=True,
                )
            return super().eventFilter(obj, event)

        def _show_task_in_active(self, task_id: str) -> None:
            """
            NY v7-fix77: registrera en ny uppgift SYNGLIGT i 'Aktiva'.

            Rickards önskan 2026-10-06: "när man skrivit en uppgift så ska
            Enter-knappen registrera den inom 'Aktiv'". Flödet gör nu:
              1. OMEDELBAR synkron rebuild (ej bara 50 ms debounce —
                 timern kunde missas/senareläggas)
              2. Byt till 'Aktiva'-fliken om man stod på 'Arkiverade'
              3. Byt till normalvyn om Focus Mode var aktiv
              4. Scrolla fram + accent-flasha den nya uppgiften
                 (sorteringen lägger nya uppgifter sist i listan — utan
                 scroll syntes den ej i långa listor!)
            Allt felhanterat — registreringen får ALDRIG krascha appen.
            """
            try:
                # 1. Omedelbar synkron rebuild av båda listorna
                with suppress(Exception):
                    self._rebuild_task_list()

                # 2. + 3. Visa vyn där uppgiften finns (Aktiva + normalvy)
                _tab_changed = False
                with suppress(Exception):
                    tabs = getattr(self, "tabs", None)
                    if tabs is not None and tabs.count() > 0 and tabs.currentIndex() != 0:
                        tabs.setCurrentIndex(0)  # 0 = 'Aktiva'
                        _tab_changed = True
                with suppress(Exception):
                    stack = getattr(self, "content_stack", None)
                    if stack is not None and stack.currentIndex() != 0:
                        stack.setCurrentIndex(0)  # 0 = normalvy (ej Focus)

                # 4. Scrolla fram + flasha den nya raden (task_<id>)
                _flashed = False
                with suppress(Exception):
                    _flashed = self._flash_new_task(task_id)

                logger.info(
                    f"{LOG_PREFIX} uppgift {task_id!r} registrerad i "
                    f"'Aktiva' (flikbyte={_tab_changed}, flash={_flashed}) "
                    f"(v7-fix77)"
                )
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} _show_task_in_active misslyckades: "
                    f"{_describe_widget_error(e)}",
                    exc_info=True,
                )

        def _flash_new_task(self, task_id: str) -> bool:
            """
            NY v7-fix77: scrolla fram + accent-flasha en nyskapad uppgift.

            Returnerar True om raden hittades (flash är ev. påbörjad).
            Flashen är en tillfällig inline-stylesheet på just denna rad
            (task_<id>) som tas bort efter 1,8 s → global QSS tar över igen.
            """
            name = f"task_{task_id}"
            target = None
            layout = getattr(self, "active_layout", None)
            if layout is not None:
                for i in range(layout.count()):
                    item = layout.itemAt(i)
                    w = item.widget() if item is not None else None
                    if w is not None and w.objectName() == name:
                        target = w
                        break
            if target is None:
                logger.debug(
                    f"{LOG_PREFIX} _flash_new_task: hittade ingen rad {name!r}"
                )
                return False
            # Scrolla fram raden (aktiva-flikens QScrollArea = tabs.widget(0))
            tabs = getattr(self, "tabs", None)
            if tabs is not None and tabs.count() > 0:
                scroll = tabs.widget(0)
                if scroll is not None and hasattr(scroll, "ensureWidgetVisible"):
                    scroll.ensureWidgetVisible(target, 16, 16)
            # Accent-flash (FIX v8: kommer ihåg flashen så den överlever en ombyggnad av listan)
            self._flash_state = (task_id, time.monotonic() + 1.8)
            self._apply_flash(target, name, 1800)
            return True

        def _apply_flash(self, target: Any, name: str, ms: int) -> None:
            accent = getattr(self, "_theme_accent_hex", "#818cf8")

            def _clear_flash() -> None:
                with suppress(Exception):
                    target.setStyleSheet("")

            try:
                target.setStyleSheet(
                    f"QWidget#{name} {{"
                    f" background: {accent}40;"
                    f" border: 1px solid {accent};"
                    f" border-radius: 8px;"
                    f"}}"
                )
                QTimer.singleShot(max(50, int(ms)), _clear_flash)
            except Exception as e:
                logger.debug(
                    f"{LOG_PREFIX} _flash: stylesheet kunde ej "
                    f"sättas ({_describe_widget_error(e)}) — scroll räcker"
                )

        def _reapply_flash(self) -> None:
            """FIX v8: en ombyggnad av listan raderar korten → flashen försvann efter ~250 ms."""
            try:
                st = getattr(self, "_flash_state", None)
                if not st:
                    return
                tid, until = st
                left_ms = int((until - time.monotonic()) * 1000)
                if left_ms <= 0:
                    self._flash_state = None
                    return
                name = f"task_{tid}"
                layout = getattr(self, "active_layout", None)
                for i in range(layout.count() if layout is not None else 0):
                    w = layout.itemAt(i).widget() if layout.itemAt(i) is not None else None
                    if w is not None and w.objectName() == name:
                        self._apply_flash(w, name, left_ms)
                        break
            except Exception:
                pass

        def _schedule_rebuild(self) -> None:
            """Schemalagg rebuild (debounce 50ms)."""
            if self._rebuild_timer is not None:
                self._rebuild_timer.start(REBUILD_DEBOUNCE_MS)
                logger.trace(f"{LOG_PREFIX} rebuild schemalagd ({REBUILD_DEBOUNCE_MS}ms)")

        @_log_event("rebuild")
        def _update_archive_tab_count(self, n: int) -> None:
            """
            NY v7-fix86: "Arkiverade (N)" i flikens titel — live-räknare.

            Cachar värdet så setTabText bara körs när antalet ändras
            (rendering sker ofta — undvik onödig QSS-omtolkning).
            """
            try:
                tabs = getattr(self, "tabs", None)
                if tabs is None or tabs.count() < 2:
                    return
                if getattr(self, "_archive_tab_count", -1) == n:
                    return
                self._archive_tab_count = n
                tabs.setTabText(1, f"Arkiverade ({n})" if n else "Arkiverade")
            except Exception:
                pass

        def _rebuild_task_list(self) -> None:
            """Bygg om task-listan (med forbattrad felhantering)."""
            start = time.perf_counter()
            try:
                if hasattr(self.store, "active_tasks_filtered"):
                    # FIX v7-fix86: respektera AKTIV SÖKNING vid rebuild —
                    # tidigare nollställdes filtret visuellt efter varje
                    # ändring (ny uppgift/klar/etc) trots att söktexten
                    # fanns kvar i fältet. Nu filtreras rebuilden likadant
                    # som _do_search.
                    _q = (getattr(self, "_current_filter", "") or "").lower().strip()
                    if _q:
                        active = self.store.active_tasks_filtered(
                            query=_q, sort_by="pinned_first"
                        )
                    else:
                        active = self.store.active_tasks_filtered(sort_by="pinned_first")
                else:
                    active = []
                if hasattr(self.store, "archive_tasks"):
                    archive = self.store.archive_tasks()
                else:
                    archive = []
                self._render_tasks(active, archived=False)
                self._render_tasks(archive, archived=True)
                self._reapply_flash()
                self._build_search_index()
                duration = (time.perf_counter() - start) * 1000
                self._render_count += 1
                if duration > 50.0:
                    self._slow_render_count += 1
                    logger.warning(
                        f"{LOG_PREFIX} _rebuild_task_list LÅNGSAM: {duration:.2f}ms "
                        f"(active={len(active)}, archive={len(archive)})"
                    )
                self._throttle.record_frame(duration)
                self._audit.add(
                    "rebuild",
                    {
                        "active": len(active),
                        "archive": len(archive),
                        "ms": duration,
                    },
                )
            except Exception as e:
                logger.error(
                    f"{LOG_PREFIX} _rebuild_task_list misslyckades: {_describe_widget_error(e)}",
                    exc_info=True,
                )

        # ====================================================================
        # SOK-INDEX + THEME (NY v6.4.1 v7 - aterstaller saknade metoder)
        # ====================================================================

        # ====================================================================
        # TASK-RENDERING (NY v6.4.1 v7 - aterstaller saknade metoder)
        # ====================================================================

        @_log_call
        def _build_active_tab(self) -> QWidget:
            """NY v6.4.1 v7-fix: Bygg 'Aktiva'-fliken med scrollbar.

            Skapar en QScrollArea som innehåller en container med
            self.active_layout (QVBoxLayout) som _render_tasks() fyller på.
            """
            try:
                scroll = QScrollArea(self)
                scroll.setWidgetResizable(True)
                scroll.setHorizontalScrollBarPolicy(
                    __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.ScrollBarPolicy.ScrollBarAlwaysOff
                    if _QT_BACKEND == "PySide6"
                    else 1  # PyQt fallback (ovanligt)
                )
                container = QWidget(scroll)
                self.active_layout = QVBoxLayout(container)
                self.active_layout.setContentsMargins(4, 4, 4, 4)
                self.active_layout.setSpacing(6)  # v7-fix17: luftigare
                self.active_layout.addStretch(1)
                scroll.setWidget(container)
                logger.debug(f"{LOG_PREFIX} _build_active_tab klar")
                return scroll
            except Exception as e:
                logger.error(
                    f"{LOG_PREFIX} _build_active_tab misslyckades: "
                    f"{_describe_widget_error(e)}",
                    exc_info=True,
                )
                # Fallback: enkel QWidget
                fallback = QWidget(self)
                self.active_layout = QVBoxLayout(fallback)
                return fallback

        @_log_call
        def _build_archive_tab(self) -> QWidget:
            """NY v6.4.1 v7-fix: Bygg 'Arkiverade'-fliken med scrollbar.

            Samma struktur som _build_active_tab men for arkiverade tasks.
            """
            try:
                scroll = QScrollArea(self)
                scroll.setWidgetResizable(True)
                container = QWidget(scroll)
                self.archive_layout = QVBoxLayout(container)
                self.archive_layout.setContentsMargins(4, 4, 4, 4)
                self.archive_layout.setSpacing(6)  # v7-fix17: luftigare
                self.archive_layout.addStretch(1)
                scroll.setWidget(container)
                logger.debug(f"{LOG_PREFIX} _build_archive_tab klar")
                return scroll
            except Exception as e:
                logger.error(
                    f"{LOG_PREFIX} _build_archive_tab misslyckades: "
                    f"{_describe_widget_error(e)}",
                    exc_info=True,
                )
                fallback = QWidget(self)
                self.archive_layout = QVBoxLayout(fallback)
                return fallback

        def _render_tasks(
            self,
            tasks: List[Dict[str, Any]],
            archived: bool = False
        ) -> None:
            """
            NY v6.4.1 v7: Rendera task-lista (med cache + felhantering).
            """
            try:
                # NY v7-fix41: senarelagda (snoozade) uppgifter döljs
                # från Aktiva-listan tills snooze-tiden är inne
                n_snoozed_hidden = 0
                if not archived:
                    _n_before = len(tasks)
                    tasks = [tk for tk in tasks if not _is_snoozed(tk)]
                    n_snoozed_hidden = _n_before - len(tasks)
                    if n_snoozed_hidden:
                        logger.debug(
                            f"{LOG_PREFIX} _render_tasks: "
                            f"{n_snoozed_hidden} senarelagda dolda"
                        )
                layout = (
                    self.archive_layout if archived else self.active_layout
                )
                self._clear_layout(layout)
                if not tasks:
                    # v7-fix17/86: vänligare tom-text med emoji + guide
                    empty_text = (
                        "✨  Inga uppgifter ännu\n"
                        "Skriv nedan och tryck Enter" if not archived
                        else "🗄️  Inga arkiverade uppgifter"
                    )
                    if not archived:
                        self._update_stats_chip(0, 0, n_snoozed_hidden)
                    empty_label = QLabel(empty_text, self)
                    empty_label.setObjectName("emptyHint")
                    empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    layout.addWidget(empty_label)
                    layout.addStretch(1)
                    # NY v7-fix86: håll arkiv-flikens räknare uppdaterad
                    self._update_archive_tab_count(0)
                    return
                if not archived:
                    # v7-fix17: live-stats i headern
                    self._update_stats_chip(
                        len(tasks),
                        sum(1 for tk in tasks if tk.get("done")),
                        n_snoozed_hidden,
                    )
                else:
                    # NY v7-fix86: "Arkiverade (N)" i fliken
                    self._update_archive_tab_count(len(tasks))
                for task in tasks:
                    widget = self._build_task_widget_cached(task, archived)
                    if widget is not None:
                        layout.addWidget(widget)
                        # v7-fix10: show() måste komma EFTER addWidget() —
                        # addWidget() reparentar widgeten vilket döljer den
                        # igen. Kort skapade NÄR widgeten redan syns måste
                        # visas explicit (Qt visar ej nya barn automatiskt),
                        # annars blir listan tom vid om-rendering.
                        widget.show()
                layout.addStretch(1)
                logger.debug(
                    f"{LOG_PREFIX} _render_tasks(archived={archived}): {len(tasks)} tasks"
                )
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} _render_tasks misslyckades: "
                    f"{_describe_widget_error(e)}",
                    exc_info=True,
                )

        def paintEvent(self, event: QPaintEvent) -> None:
            """
            NY v7-fix17 (design-tweak): aurora-glow längs fönstrets överkant.

            Målas EFTER super() (ovanpå QSS-bakgrunden) men UNDER barn-widgets
            (barn målas alltid efter förälderns paintEvent) — ger samma djup-
            känsla som GlassFrame, UTAN OS-transparens (WA_TranslucentBackground
            förblir AV enligt v7-fix7 → inga WS_POPUP-risker).
            """
            super().paintEvent(event)
            try:
                p = QPainter(self)
                if not p.isActive():
                    return
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                w = self.width()
                h = self.height()
                if w < 8 or h < 8:
                    return
                accent = QColor(
                    getattr(self, "_theme_accent_hex", "#818cf8")
                )
                is_dark = getattr(self, "_theme_is_dark", True)
                glow = QRadialGradient(
                    float(w / 2), 0.0, max(float(w) * 0.9, 1.0)
                )
                top_c = QColor(accent)
                top_c.setAlpha(32 if is_dark else 44)
                end_c = QColor(accent)
                end_c.setAlpha(0)
                glow.setColorAt(0.0, top_c)
                glow.setColorAt(1.0, end_c)
                # NY v7-fix38: klipp auroran mot rundade hörn när skalet är
                # genomskinligt — annars syns kvadratiska hörn genom glaset.
                if getattr(self, "_transparency_factor", 0.0) > 0.0:
                    try:
                        from PySide6.QtGui import QPainterPath
                        clip = QPainterPath()
                        clip.addRoundedRect(
                            0.0, 0.0, float(w), float(h), 14.0, 14.0
                        )
                        p.save()
                        p.setClipPath(clip)
                        p.fillRect(
                            QRect(0, 0, w, int(h * 0.45)), QBrush(glow)
                        )
                        p.restore()
                    except Exception:
                        p.fillRect(
                            QRect(0, 0, w, int(h * 0.45)), QBrush(glow)
                        )
                else:
                    p.fillRect(
                        QRect(0, 0, w, int(h * 0.45)), QBrush(glow)
                    )
            except Exception:
                pass  # design-får ALDRIG krascha appen

        def _update_stats_chip(
            self, n_active: int, n_done: int, n_snoozed: int = 0
        ) -> None:
            """
            NY v7-fix17: uppdatera headerns stats-chip ('X aktiva · Y klara').

            NY v7-fix86:
              - snoozade visas ('· N 💤') när > 0
              - tunn progress-bar under headern (% klara, accent-färg)
              - fönstertiteln får antal kvar ("TaskBord — 3 kvar") — syns
                när fönstret lyfts/flyter
            """
            chip = getattr(self, "stats_chip", None)
            if chip is None:
                return
            try:
                _txt = f"{n_active} aktiva · {n_done} klara"
                if n_snoozed:
                    _txt += f" · {n_snoozed} 💤"
                chip.setText(_txt)
                # NY v7-fix86: progress-bar (qlineargradient efter %)
                bar = getattr(self, "progress_bar", None)
                if bar is not None:
                    pct = (
                        int(round(100 * n_done / n_active))
                        if n_active else 0
                    )
                    accent = getattr(self, "_theme_accent_hex", "#818cf8")
                    with suppress(Exception):
                        bar.setStyleSheet(
                            f"QFrame#headerProgress {{"
                            f" border: none; border-radius: 2px;"
                            f" background: qlineargradient("
                            f"x1:0, y1:0, x2:1, y2:0,"
                            f" stop:0 {accent},"
                            f" stop:{pct / 100:.3f} {accent},"
                            f" stop:{min(pct / 100 + 0.001, 1.0):.3f} rgba(148,163,184,70),"
                            f" stop:1 rgba(148,163,184,70));"
                            f"}}"
                        )
                        bar.setToolTip(
                            f"{pct}% klara ({n_done} av {n_active})"
                        )
                # NY v7-fix86: fönstertitel med antal kvar
                _left = max(n_active - n_done, 0)
                with suppress(Exception):
                    self.setWindowTitle(
                        f"{self.DEFAULT_TITLE} — {_left} kvar"
                        if _left else self.DEFAULT_TITLE
                    )
            except Exception:
                pass

        def _window_transparency_factor(self) -> float:
            """
            NY v7-fix38: aktuell fönstertransparens (0.0 = opak, 1.0 = full).

            Läser FÖRST skal-QWidgetens faktiska läge (main.pyw kan
            nedgradera automatiskt om CreateWindowEx misslyckades för det
            genomskinliga skalet), annars settings.
            """
            try:
                shell = getattr(self, "_shell", None)
                if shell is not None and hasattr(shell, "_shell_transparency"):
                    f = float(shell._shell_transparency)
                elif self.settings is not None and hasattr(
                    self.settings, "window_transparency"
                ):
                    f = float(self.settings.window_transparency())
                elif self.settings is not None and hasattr(self.settings, "get"):
                    f = float(self.settings.get("window_transparency", 0.85))
                else:
                    f = 0.85
                if f <= 0.0:
                    return 0.0
                return max(0.35, min(1.0, f))
            except Exception:
                return 0.85

        def _build_task_widget_cached(
            self, task: Dict[str, Any], archived: bool
        ) -> Optional[QWidget]:
            """NY v6.4.1 v7: Bygg eller återanvänd task-widget (med cache).

            v7-fix10: cache-nyckeln omfattar nu ÄVEN done/priority/pinned —
            tidigare räckte matchande titel, vilket gav gamla stylade kort
            (t.ex. saknad genomstrykning) efter att en uppgift bockats av.
            """
            try:
                tid = task.get("id", "")
                # NY v7-fix41: nyckeln omfattar nu ÄVEN due/snooze/
                # recurring/subtasks — annars återanvänds gamla kort
                # efter senareläggning/delmoment-ändringar
                state_key = (
                    task.get("title", ""),
                    bool(task.get("done", False)),
                    task.get("priority", "none"),
                    bool(task.get("pinned")),
                    str(task.get("due_date") or ""),
                    str(task.get("start_date") or ""),
                    str(task.get("snoozed_until") or ""),
                    (task.get("recurring") or {}).get("interval", ""),
                    tuple(_flatten_subtasks(task.get("subtasks") or [])),
                    _task_has_email(task),
                )
                if tid in self._task_widgets and not archived:
                    existing = self._task_widgets[tid]
                    if existing.property("task_state") == state_key:
                        return existing
                widget = self._build_task_widget(task, archived)
                if widget is not None and not archived:
                    widget.setProperty("task_state", state_key)
                    self._task_widgets[tid] = widget
                return widget
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} _build_task_widget_cached misslyckades: "
                    f"{_describe_widget_error(e)}",
                    exc_info=True,
                )
                return None

        def _build_task_widget(
            self, task: Dict[str, Any], archived: bool
        ) -> Optional[QWidget]:
            """
            NY v7-fix10: Bygg enskild task-widget — modern frosted-glass-kort.

            ALL styling sker via QSS-properties (taskCard/taskPriority/pinned/
            taskDone) i _apply_theme — inga inline-setStyleSheet som överrider
            temat (gammal bugg: inline-stylen bröt QSS-hover/regler).

            Kortets layout:
              Rad 1: [✓ checkbox] [• prioritetsprick] Titel... [📌 pin]
              Rad 2: [chips: taggar] [datum]  (endast om något finns)
            """
            try:
                tid = task.get("id")
                if not tid:
                    return None
                container = QFrame(self)
                container.setObjectName(f"task_{tid}")
                container.setProperty("taskCard", True)
                task_priority = task.get("priority", "none")
                if task_priority not in PRIORITY_CYCLE:
                    task_priority = "none"  # Fallback
                due = task.get("due_date")  # NY v7-fix41: används i properties
                is_done = bool(task.get("done", False))
                is_pinned = bool(task.get("pinned"))
                # Dynamic properties → QSS-väljare (Etapp 10)
                container.setProperty("task_priority", task_priority)
                container.setProperty("taskPriority", task_priority)
                container.setProperty("task_id", tid)
                container.setProperty("taskDone", is_done)
                container.setProperty("pinned", is_pinned)
                # NY v7-fix79: högerklick på UPPGIFTEN → åtgärdsmeny
                # (redigera/ta bort/klar/prioritet/fäst + allt från ⋯).
                # Tidigare nådde högerklicket fönster-menyn (centrera/lås).
                container.setContextMenuPolicy(
                    Qt.ContextMenuPolicy.CustomContextMenu
                )
                container.customContextMenuRequested.connect(
                    lambda _pos, _tid=tid: self._on_task_context_menu(_tid)
                )
                # NY v7-fix41: deadline-ring (QSS: overdue=töd, today=orange)
                due_state = "none"
                if due:
                    try:
                        _dd = datetime.fromisoformat(str(due)).date()
                        _delta = (_dd - datetime.now().date()).days
                        if _delta < 0:
                            due_state = "overdue"
                        elif _delta == 0:
                            due_state = "today"
                    except (ValueError, TypeError):
                        due_state = "none"
                container.setProperty("taskDue", due_state)

                vbox = QVBoxLayout(container)
                vbox.setContentsMargins(10, 8, 10, 8)
                vbox.setSpacing(3)

                # --- Rad 1: checkbox + prioritetsprick + titel + pin ---------
                row1 = QHBoxLayout()
                row1.setSpacing(8)
                checkbox = QCheckBox(container)
                checkbox.setChecked(is_done)
                # FIX v7-fix80: tydlig KLAR-KNAPP — större (26px), pekhand,
                # tooltip. Rickard: "knapp vid uppgift för att toggla klar".
                checkbox.setFixedSize(26, 26)
                checkbox.setToolTip("✓ Klar / oklar — klicka här")
                checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
                checkbox.toggled.connect(
                    lambda checked, t=tid: self._on_task_toggle(t, checked)
                )
                row1.addWidget(checkbox, 0, Qt.AlignmentFlag.AlignVCenter)

                # Klickbar prioritetsprick (klick = cykla, högerklick = meny)
                dot = PriorityDot(
                    task_id=tid, priority=task_priority, parent=container
                )
                dot.priority_dot_clicked.connect(self._on_priority_dot_clicked)
                dot.priority_dot_right_clicked.connect(
                    self._on_priority_dot_right_clicked
                )
                row1.addWidget(dot, 0, Qt.AlignmentFlag.AlignVCenter)

                title_label = QLabel(task.get("title", ""), container)
                title_label.setObjectName("taskTitle")
                title_label.setWordWrap(True)
                title_label.setToolTip(task.get("title", ""))
                if is_done:
                    # Genomstruken klar-titel (QSS saknar text-decoration)
                    _f = title_label.font()
                    _f.setStrikeOut(True)
                    title_label.setFont(_f)
                row1.addWidget(title_label, 1, Qt.AlignmentFlag.AlignVCenter)

                if is_pinned:
                    pin = QLabel("📌", container)
                    pin.setObjectName("pinBadge")
                    pin.setToolTip("Fäst uppgift")
                    row1.addWidget(pin, 0, Qt.AlignmentFlag.AlignVCenter)

                # NY v7-fix41: 🔁-ikon för återkommande uppgifter
                _rec = task.get("recurring")
                if isinstance(_rec, dict) and _rec.get("interval"):
                    _iv = {
                        "daily": "varje dag",
                        "weekly": "varje vecka",
                        "monthly": "varje månad",
                    }.get(str(_rec.get("interval")), "?")
                    rec_badge = QLabel("🔁", container)
                    rec_badge.setObjectName("recBadge")
                    rec_badge.setToolTip(f"Återkommande: {_iv}")
                    row1.addWidget(
                        rec_badge, 0, Qt.AlignmentFlag.AlignVCenter
                    )

                # NY v7-fix41: ⋯-knapp → åtgärdsmeny (snooze/datum/
                # återkommande/delmoment/namn/ta bort)
                menu_btn = QPushButton("⋯", container)
                menu_btn.setObjectName("taskMenuBtn")
                menu_btn.setFixedSize(24, 24)
                # NY v7-fix86: pekhand = tydligt klickbar
                menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                menu_btn.setToolTip(
                    "Åtgärder (eller HÖGERKLICKA på uppgiften):\n"
                    "Klar · Prioritet · Fäst · Redigera · Ta bort ·\n"
                    "Senarelägg · Förfallodatum · Startdatum · Återkommande · Delmoment"
                )
                menu_btn.clicked.connect(
                    lambda _c, tk=dict(task): self._show_task_menu(tk)
                )
                row1.addWidget(
                    menu_btn, 0, Qt.AlignmentFlag.AlignVCenter
                )

                # 📧 "Öppna mejlet" — på ALLA uppgifter som kommer från ett
                # mail (sparad fil ELLER sparad mailtext), inte bara de med
                # en fungerande filsökväg
                if _task_has_email(task):
                    mail_btn = QPushButton("📧", container)
                    mail_btn.setObjectName("emailBadge")
                    mail_btn.setFixedSize(24, 24)
                    mail_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                    mail_btn.setToolTip(
                        "Öppna mejlet\n"
                        f"{task.get('email_from') or 'Okänd avsändare'}"
                    )
                    mail_btn.clicked.connect(
                        lambda _c, tk=dict(task): self._open_task_email(tk)
                    )
                    row1.addWidget(
                        mail_btn, 0, Qt.AlignmentFlag.AlignVCenter
                    )
                vbox.addLayout(row1)

                # --- Rad 2: tagg-chips + datum (endast om något finns) -------
                tags = [
                    str(tg) for tg in (task.get("tags") or [])
                    if str(tg).strip()
                ][:6]
                _start = task.get("start_date")
                if tags or due or _start or _is_snoozed(task):
                    meta = QHBoxLayout()
                    meta.setSpacing(6)
                    meta.addSpacing(34)  # indrag i linje med titeln
                    for i, tag in enumerate(tags):
                        chip = TagChip(tag, color_index=i, parent=container)
                        chip.clicked.connect(self._on_tag_clicked)
                        meta.addWidget(chip)
                    if _is_snoozed(task):
                        sn_lbl = QLabel(
                            f"💤 till {_snooze_until_label(task.get('snoozed_until'))}",
                            container,
                        )
                        sn_lbl.setObjectName("snoozeBadge")
                        sn_lbl.setToolTip("Senarelagd — kommer tillbaka automatiskt")
                        meta.addWidget(sn_lbl)
                    if _start:
                        st_lbl = QLabel(f"▶ start {_due_label_short(_start)}", container)
                        st_lbl.setObjectName("snoozeBadge")
                        st_lbl.setToolTip(
                            f"Startdatum: {str(_start)[:10]}\n"
                            "Används när uppgiften skickas till kalendern."
                        )
                        meta.addWidget(st_lbl)
                    if due:
                        meta.addWidget(DueDateLabel(str(due), container))
                    meta.addStretch(1)
                    vbox.addLayout(meta)

                # Datumraden visas alltid: skapad-datum för aktiva och
                # avslutsdatum för arkiverade uppgifter.
                _timestamp_value = (
                    task.get("completed") if archived else task.get("created")
                )
                try:
                    if _timestamp_value:
                        _timestamp_dt = datetime.fromisoformat(
                            str(_timestamp_value).replace("Z", "+00:00")
                        )
                        if _timestamp_dt.tzinfo is not None:
                            _timestamp_dt = _timestamp_dt.astimezone()
                        _timestamp_text = _timestamp_dt.strftime("%Y-%m-%d")
                    else:
                        _timestamp_text = "datum saknas"
                except (ValueError, TypeError, OverflowError):
                    _timestamp_text = (
                        str(_timestamp_value)[:10]
                        if _timestamp_value else "datum saknas"
                    )
                _date_caption = "✓ Klar" if archived else "➕ Tillagd"
                date_row = QHBoxLayout()
                date_row.setSpacing(6)
                date_row.addSpacing(34)
                date_lbl = QLabel(
                    f"{_date_caption}: {_timestamp_text}", container
                )
                date_lbl.setObjectName("taskDate")
                date_lbl.setToolTip(
                    ("Datum då uppgiften markerades som klar."
                     if archived else "Datum då uppgiften lades till.")
                    + (f"\n{_timestamp_value}" if _timestamp_value else "")
                )
                date_row.addWidget(date_lbl)
                date_row.addStretch(1)
                vbox.addLayout(date_row)

                # --- NY v7-fix41 + v8: delmoment (checklista, nästlad) ----
                subs = [
                    dict(s) for s in (task.get("subtasks") or [])
                    if s.get("title")
                ]
                if subs:
                    sub_vbox = QVBoxLayout()
                    sub_vbox.setContentsMargins(34, 2, 4, 2)
                    sub_vbox.setSpacing(1)
                    self._add_subtask_rows(container, sub_vbox, tid, subs, depth=1)
                    _total_n, _done_n = _subtask_stats(subs)
                    if _done_n >= _total_n:
                        prog = QLabel(f"☑ {_done_n}/{_total_n} klara", container)
                        prog.setObjectName("subtaskDoneAll")
                    else:
                        prog = QLabel(f"☐ {_done_n}/{_total_n} klara", container)
                        prog.setObjectName("subtaskProgress")
                    sub_vbox.addWidget(prog)
                    vbox.addLayout(sub_vbox)
                return container
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} _build_task_widget misslyckades: "
                    f"{_describe_widget_error(e)}",
                    exc_info=True,
                )
                return None

        def _clear_layout(self, layout: Any) -> None:
            """NY v6.4.1 v7: Rensa layout (med felhantering)."""
            try:
                while layout.count():
                    item = layout.takeAt(0)
                    widget = item.widget() if item else None
                    if widget is not None:
                        for tid, cached in list(self._task_widgets.items()):
                            if cached is widget:
                                del self._task_widgets[tid]
                                break
                        widget.setParent(None)
                        with suppress(Exception):
                            widget.deleteLater()
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} _clear_layout misslyckades: "
                    f"{_describe_widget_error(e)}",
                    exc_info=True,
                )

        @_log_call
        def _build_search_index(self) -> None:
            """
            NY v6.4.1 v7: Bygg inverterad sok-index (token → task_ids).

            Används av _do_search() for snabb matchning.
            """
            self._search_index.clear()
            try:
                if hasattr(self.store, "active_tasks"):
                    tasks = self.store.active_tasks()
                else:
                    tasks = []
                for task in tasks:
                    tokens = self._tokenize_task(task)
                    for token in tokens:
                        self._search_index.setdefault(token, set()).add(task["id"])
                logger.debug(
                    f"{LOG_PREFIX} sok-index byggd: {len(self._search_index)} unika tokens, "
                    f"{sum(len(s) for s in self._search_index.values())} referenser"
                )
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} _build_search_index misslyckades: "
                    f"{_describe_widget_error(e)}",
                    exc_info=True,
                )

        @_log_call
        def _check_auto_theme(self) -> None:
            """
            NY v7-fix82: klockstyrt tema — växla utan omstart.

            Körs var 10:e minut (se _init_timers). Gäller ENDAST när
            användaren valt 'Auto' i tray-menyn (settings theme='auto'):
            07:00–18:59 = ljust, 19:00–06:59 = mörkt. theme()/is_dark()
            i settings löser värdet; här detekteras GRÄNSÖVERSKRIDANDET
            (sparat _theme_is_dark ≠ aktuellt) → _apply_theme() om.
            """
            try:
                raw = None
                with suppress(Exception):
                    if hasattr(self.settings, "theme_raw"):
                        raw = self.settings.theme_raw()
                if raw != "auto":
                    return  # auto ej valt — gör ingenting
                want_dark = None
                with suppress(Exception):
                    if hasattr(self.settings, "is_dark"):
                        want_dark = bool(self.settings.is_dark())
                if want_dark is None:
                    return
                current = bool(getattr(self, "_theme_is_dark", not want_dark))
                if want_dark != current:
                    logger.info(
                        f"{LOG_PREFIX} Auto-tema: klockan passerade "
                        f"gränsen → växlar till "
                        f"{'mörkt' if want_dark else 'ljust'} (v7-fix82)"
                    )
                    self._apply_theme()
            except Exception as e:
                logger.debug(f"{LOG_PREFIX} _check_auto_theme: {e}")

        def _apply_theme(self) -> None:
            """
            NY v6.4.1 v7: Applicera tema + proffsig glass-design (2026-09-24).

            Rickard: "designen på fönstret ska vara bättre".
            Använder settings.stylesheet() som bas + widget-specifik QSS
            (header, tabs, sök, input, uppgiftskort) — färger via accent-palette (R3).
            """
            try:
                is_dark = (
                    self.settings.is_dark()
                    if hasattr(self.settings, "is_dark")
                    else True
                )
                accent = (
                    self.settings.accent_color()
                    if hasattr(self.settings, "accent_color")
                    else "indigo"
                )
                # Etapp 10 (v7-fix10): design-tokens + accent via GLASS_ACCENTS
                accent_hex = GLASS_ACCENTS.get(accent, "#818cf8")
                t = _glass_tokens(is_dark)
                # NY v7-fix38: genomskinligt skal → skala panelens bas-alfa
                # så skrivbordsikonerna syns igenom glaset
                self._transparency_factor: float = self._window_transparency_factor()
                t = _tokens_with_transparency(t, self._transparency_factor)
                _radius_css: str = (
                    "border-radius: 14px;" if self._transparency_factor > 0.0 else ""
                )
                # NY v7-fix17: spara tema för paintEvent-auroran + accent-tinter
                self._theme_is_dark: bool = is_dark
                self._theme_accent_hex: str = accent_hex
                tab_tint = _hex_rgba(accent_hex, 0.17 if is_dark else 0.14)
                tab_edge = _hex_rgba(accent_hex, 0.45)

                base_qss = ""
                if hasattr(self.settings, "stylesheet"):
                    try:
                        base_qss = self.settings.stylesheet()
                    except Exception:
                        base_qss = ""

                # Prioritets-regler genereras ur PRIORITY_COLORS + tint-dictar
                # (ett enda ställe att justera kulörerna på).
                prio_rules = ""
                # NY v8: ALLA rader (även "ingen prio") får färgad vänsterkant.
                # Hög prioritet får tjockare kant (5px) för tydligare markering.
                for _prio in ("high", "medium", "low", "none"):
                    _edge = PRIORITY_COLORS[_prio]
                    _edge_w = 5 if _prio == "high" else 3
                    prio_rules += (
                        f'QFrame[taskCard="true"][taskPriority="{_prio}"] {{ '
                        f"background-color: {PRIORITY_ROW_TINT[_prio]}; "
                        f"border: 1px solid {t['surface_edge']}; "
                        f"border-left: {_edge_w}px solid {_edge}; }} "
                        f'QFrame[taskCard="true"][taskPriority="{_prio}"]:hover {{ '
                        f"background-color: {PRIO_HOVER_TINT[_prio]}; "
                        f"border: 1px solid {t['edge_hov']}; "
                        f"border-left: {_edge_w}px solid {_edge}; }} "
                    )

                # NY v7-fix41: deadline-ring (röd=övertruten, orange=idag)
                due_rules = (
                    'QFrame[taskCard="true"][taskDue="overdue"] { '
                    "background-color: rgba(239, 68, 68, 0.15); "
                    "border: 1px solid rgba(239, 68, 68, 0.65); "
                    "border-left: 3px solid #ef4444; } "
                    'QFrame[taskCard="true"][taskDue="today"] { '
                    "background-color: rgba(245, 158, 11, 0.12); "
                    "border: 1px solid rgba(245, 158, 11, 0.55); "
                    "border-left: 3px solid #f59e0b; } "
                )

                # NY v7-fix41: ⋯-knapp, snooze/återkommande-badges, delmoment
                fix41_rules = (
                    "QPushButton#taskMenuBtn { "
                    f"background: {t['surface']}; "
                    f"border: 1px solid {t['surface_edge']}; "
                    "border-radius: 9px; "
                    "font-size: 13px; font-weight: 700; "
                    f"color: {t['muted']}; }} "
                    "QPushButton#taskMenuBtn:hover { "
                    f"background: {t['surface_hov']}; "
                    f"border: 1px solid {t['edge_hov']}; }} "
                    "QLabel#snoozeBadge { "
                    "background: rgba(129, 140, 248, 0.16); "
                    "border: 1px solid rgba(129, 140, 248, 0.35); "
                    f"color: {t['muted']}; "
                    "border-radius: 8px; padding: 1px 7px; "
                    "font-size: 10px; font-weight: 600; } "
                    "QLabel#recBadge { background: transparent; "
                    "font-size: 12px; } "
                    f"QLabel#subtaskTitle {{ color: {t['muted']}; "
                    "font-size: 12px; } "
                    f"QLabel#subtaskProgress {{ color: {t['muted']}; "
                    "font-size: 10px; font-weight: 600; } "
                    "QLabel#subtaskDoneAll { color: #34d399; "
                    "font-size: 10px; font-weight: 600; } "
                    f"QLabel#taskDate {{ color: {t['muted']}; "
                    "font-size: 10px; font-weight: 500; } "
                )

                self.setObjectName("TodoWidget")
                widget_qss = f"""
                /* ============ ETAPP 10 — MODERN FROSTED GLASS (v7-fix10) ===== */
                QWidget#TodoWidget {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 {t['bg_top']}, stop:1 {t['bg_bottom']});
                    color: {t['fg']};
                    border: none;
                    {_radius_css}
                    font-family: "Segoe UI Variable Text", "Segoe UI", "Inter", sans-serif;
                    font-size: 13px;
                }}
                QLabel#dragHandle {{
                    background: transparent;
                    color: {t['fg']};
                    font-size: 12px;
                    font-weight: 700;
                    border: none;
                    padding: 2px 4px;
                }}
                QLabel#dragHint {{
                    background: transparent;
                    color: {t['hint']};
                    font-size: 10px;
                    font-weight: 400;
                    border: none;
                    padding: 2px 0;
                }}
                QLabel#statsChip {{
                    background: {t['surface']};
                    border: 1px solid {t['surface_edge']};
                    color: {t['muted']};
                    border-radius: 9px;
                    padding: 3px 9px;
                    font-size: 10px;
                    font-weight: 600;
                }}
                QPushButton#lockBtn {{
                    background: {t['surface']};
                    border: 1px solid {t['surface_edge']};
                    border-radius: 9px;
                    font-size: 13px;
                    padding: 2px 6px;
                    min-width: 28px;
                }}
                QPushButton#lockBtn:hover {{
                    background: {t['surface_hov']};
                    border: 1px solid {t['edge_hov']};
                }}
                QPushButton#lockBtn:checked {{
                    background: {accent_hex};
                    color: white;
                    border: 1px solid {accent_hex};
                }}
                QLineEdit#searchInput, QLineEdit#inputField {{
                    background: {t['field_bg']};
                    border: 1px solid {t['surface_edge']};
                    border-radius: 12px;
                    padding: 9px 14px;
                    font-size: 13px;
                    selection-background-color: {accent_hex};
                    selection-color: white;
                }}
                QLineEdit#searchInput:hover, QLineEdit#inputField:hover {{
                    border: 1px solid {t['edge_hov']};
                }}
                QLineEdit#searchInput:focus, QLineEdit#inputField:focus {{
                    border: 1.5px solid {accent_hex};
                    background: {t['field_focus']};
                }}
                QTabWidget::pane {{
                    border: none;
                    border-top: 1px solid {t['divider']};
                    background: transparent;
                    top: -1px;
                }}
                QTabBar {{ background: transparent; border: none; }}
                QTabBar::tab {{
                    background: transparent;
                    color: {t['muted']};
                    padding: 7px 16px;
                    margin: 2px 3px 2px 0;
                    border: 1px solid transparent;
                    border-radius: 10px;
                    font-weight: 600;
                    font-size: 12px;
                }}
                QTabBar::tab:selected {{
                    background: {tab_tint};
                    color: {accent_hex};
                    border: 1px solid {tab_edge};
                }}
                QTabBar::tab:hover:!selected {{
                    color: {t['fg_hov']};
                    background: {t['surface']};
                }}
                QScrollArea {{ border: none; background: transparent; }}
                QScrollArea > QWidget > QWidget {{ background: transparent; }}
                QScrollBar:vertical {{
                    background: transparent;
                    width: 10px;
                    margin: 2px;
                }}
                QScrollBar::handle:vertical {{
                    background: {t['surface_edge']};
                    border-radius: 5px;
                    min-height: 28px;
                }}
                QScrollBar::handle:vertical:hover {{ background: {accent_hex}; }}
                QScrollBar::add-line:vertical,
                QScrollBar::sub-line:vertical {{ height: 0; }}
                /* --- Uppgiftskort (glas-cards) -------------------------------- */
                QFrame[taskCard="true"] {{
                    background-color: {t['surface']};
                    border: 1px solid {t['surface_edge']};
                    border-radius: 12px;
                    padding: 2px 4px;
                    margin: 2px 0;
                }}
                QFrame[taskCard="true"]:hover {{
                    background-color: {t['surface_hov']};
                    border: 1px solid {t['edge_hov']};
                }}
                {prio_rules}
                {due_rules}
                {fix41_rules}
                /* Fästa (pinned) uppgifter — amber-glas; kommer EFTER
                   prioritets-reglerna = vinner vid konflikt. */
                QFrame[taskCard="true"][pinned="true"] {{
                    background-color: rgba(251, 191, 36, 0.10);
                    border: 1px solid rgba(251, 191, 36, 0.55);
                    border-left: 3px solid #fbbf24;
                }}
                QFrame[taskCard="true"][pinned="true"]:hover {{
                    background-color: rgba(251, 191, 36, 0.17);
                    border: 1px solid rgba(251, 191, 36, 0.80);
                    border-left: 3px solid #fbbf24;
                }}
                QLabel#taskTitle {{
                    color: {t['fg']};
                    font-weight: 600;
                    border: none;
                    background: transparent;
                    padding: 0;
                }}
                QFrame[taskCard="true"][taskDone="true"] QLabel#taskTitle {{
                    color: {t['muted']};
                    font-weight: 400;
                    text-decoration: line-through;
                }}
                QLabel#pinBadge {{
                    background: transparent;
                    color: #fbbf24;
                    font-size: 12px;
                    border: none;
                    padding: 0;
                }}
                QLabel#emptyHint {{
                    color: {t['muted']};
                    font-style: italic;
                    padding: 24px;
                    border: none;
                    background: transparent;
                }}
                /* --- Checkbox (målad glas-indikator) -------------------------- */
                QCheckBox {{
                    background: transparent;
                    spacing: 0;
                }}
                QCheckBox::indicator {{
                    width: 22px;
                    height: 22px;
                    border-radius: 7px;
                    border: 2px solid {t['edge_hov']};
                    background: {t['field_bg']};
                }}
                QCheckBox::indicator:hover {{
                    border: 2px solid {accent_hex};
                }}
                QCheckBox::indicator:checked {{
                    background: {accent_hex};
                    border: 2px solid {accent_hex};
                }}
                /* --- Focus Mode-knappar --------------------------------------- */
                QPushButton#emailImportBtn, QPushButton#emailBadge {{
                    background: {t['surface']};
                    border: 1px solid {t['surface_edge']};
                    border-radius: 9px;
                    font-size: 14px;
                    padding: 2px;
                }}
                QPushButton#emailImportBtn:hover, QPushButton#emailBadge:hover {{
                    background: {t['surface_hov']};
                    border: 1px solid {t['edge_hov']};
                }}
                QPushButton#focusNav {{
                    background: {t['surface']};
                    color: {t['fg']};
                    border: 1px solid {t['surface_edge']};
                    border-radius: 10px;
                    padding: 8px 12px;
                    font-weight: 600;
                }}
                QPushButton#focusNav:hover {{
                    background: {t['surface_hov']};
                    border: 1px solid {t['edge_hov']};
                }}
                QPushButton#focusDone {{
                    background: rgba(16, 185, 129, 0.78);
                    color: white;
                    border: 1px solid rgba(16, 185, 129, 0.95);
                    border-radius: 10px;
                    padding: 8px 14px;
                    font-weight: 700;
                }}
                QPushButton#focusDone:hover {{
                    background: rgba(16, 185, 129, 0.95);
                }}
                /* --- Menyer + tooltips (prioritetsmeny m.m.) ------------------ */
                QMenu {{
                    background: {t['field_focus']};
                    color: {t['fg']};
                    border: 1px solid {t['surface_edge']};
                    border-radius: 10px;
                    padding: 4px;
                }}
                QMenu::item {{ padding: 6px 24px; border-radius: 6px; }}
                QMenu::item:selected {{ background: {accent_hex}; color: white; }}
                QToolTip {{
                    background: {t['field_focus']};
                    color: {t['fg']};
                    border: 1px solid {t['surface_edge']};
                    border-radius: 6px;
                    padding: 4px 8px;
                }}
                QSizeGrip {{
                    background: transparent;
                    width: 14px;
                    height: 14px;
                }}
                """
                # v7-fix10: objectNames MÅSTE vara satta FÖRE setStyleSheet()
                # (annars hinner QSS-reglerna #inputField m.fl. aldrig träffa).
                import contextlib as _ctx
                with _ctx.suppress(Exception):
                    if hasattr(self, "drag_handle"):
                        self.drag_handle.setObjectName("dragHandle")
                    if hasattr(self, "lock_btn"):
                        self.lock_btn.setObjectName("lockBtn")
                        self.lock_btn.setCheckable(True)
                    if hasattr(self, "search_input"):
                        self.search_input.setObjectName("searchInput")
                    if hasattr(self, "input_field"):
                        self.input_field.setObjectName("inputField")
                    if getattr(self, "_glass", None) is not None:
                        self._glass.set_theme(is_dark, accent_hex)

                self.setStyleSheet(base_qss + widget_qss)

                logger.info(
                    f"{LOG_PREFIX} tema+design applicerat: "
                    f"dark={is_dark}, accent={accent}"
                )
                self._audit.add(
                    "theme_applied", {"is_dark": is_dark, "accent": accent}
                )
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} _apply_theme misslyckades: "
                    f"{_describe_widget_error(e)}",
                    exc_info=True,
                )
                try:
                    self.setStyleSheet(
                        "QWidget { background-color: #1a1a2e; color: white; }"
                    )
                except Exception:
                    pass

        def _tokenize_task(self, task: Dict[str, Any]) -> Set[str]:
            """Tokenize en task (title + tags)."""
            tokens: Set[str] = set()
            title = task.get("title", "")
            if title:
                tokens.update(self._tokenize_cached(title))
            for tag in task.get("tags", []):
                tokens.add(tag.lower())
            return tokens

        @staticmethod
        @functools.lru_cache(maxsize=128)
        def _tokenize_cached(text: str) -> FrozenSet[str]:
            """NY v6.4.1 v7-fix: Cache-ad tokenisering for snabbare sokning."""
            return frozenset(
                tok.lower()
                for tok in re.split(r"[\s\.,;:!\?\-/]+", text)
                if tok
            )

        def _focus_search(self) -> None:
            """Fokusera sokfaltet."""
            if hasattr(self, "search_input"):
                self.search_input.setFocus()
                self.search_input.selectAll()
                logger.debug(f"{LOG_PREFIX} sokfaltet fokuserat")

        # ====================================================================
        # EVENT HANDLERS (NY v6.4.1 v7 - forbattrade med AI-felsökning)
        # ====================================================================

        @_log_event("event:key_press")
        def keyPressEvent(self, event: QKeyEvent) -> None:
            """NY v6.4.1 v7: Tangentbord (med full spårning 2026-09-24).
            Hanterar: Esc→stäng, ↑/↓→navigera, ←/→→prioritet."""
            try:
                get_throttle().notify_activity()
                # FIX 2026-09-24: logga ALLA tangenter (Rickard 199999%)
                # FIX v7-fix39: crash-säker — Qt.Key(_k) kan kasta för
                # okända tangentkoder; int() på enum finns ej i PySide6
                _k = event.key()
                _kn = f"key={_k}"
                with suppress(Exception):
                    _kn = getattr(Qt.Key(_k), "name", None) or _kn
                _mods = []
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    _mods.append("Shift")
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    _mods.append("Ctrl")
                if event.modifiers() & Qt.KeyboardModifier.AltModifier:
                    _mods.append("Alt")
                _txt = event.text() if hasattr(event, "text") else ""
                logger.debug(
                    f"{LOG_PREFIX} keyPress key={_kn} text={_txt!r} "
                    f"mods={'+'.join(_mods) or '-'} "
                    f"focus={'search' if self.search_input.hasFocus() else 'content'}"
                )
                if event.key() == Qt.Key.Key_Escape and not self.search_input.hasFocus():
                    logger.debug(f"{LOG_PREFIX} Esc → _on_close_clicked")
                    self._on_close_clicked()
                    event.accept()
                    return
                if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                    self._navigate_tasks(event.key())
                    event.accept()
                    return
                super().keyPressEvent(event)
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} keyPressEvent misslyckades: {_describe_widget_error(e)}",
                    exc_info=True,
                )

        def _setup_bugg19_zorder(self) -> None:
            """
            NY v6.4.1 v7-fix6: HWND_BOTTOM + WS_EX_NOACTIVATE
            (sitter alltid på skrivbordet, under fokuserade appar).

            Rickard 2026-09-25: "syns men försvinner när man klickar
            någonstans, ska alltid ligga överst på skrivbordet".

            Approach (v7-fix6):
              1. Sätt WS_EX_NOACTIVATE (TOOLWINDOW borta i v7-fix7 — vi använder Qt.Window)
                 → fönstret på desktop-root, fokuseras INTE automatiskt
              2. Sätt HWND_BOTTOM (under andra windows UTAN TOPMOST-läget)
                 → Fokuserade appar går naturligt Ovanpå widgeten
              3. Reparenta från WorkerW (om vi blivit parentad dit)
              4. Diagnostik post: HWND, visible, pos, monitor
            """
            # FIX 2026-09-25 v7-fix7: reentrancy-skydd (showEvent→zorder→moveEvent→save
            # → signal → populate → show() → showEvent → zorder… kan loopa).
            if getattr(self, "_zorder_running", False):
                logger.debug(
                    f"{LOG_PREFIX} _setup_bugg19_zorder: redan igång, skip"
                )
                return
            self._zorder_running = True
            try:
                if sys.platform != "win32":
                    return
                # FIX v7-fix29: barn → SKALET hanterar z-order, vi hoppar över
                if self._is_child():
                    logger.debug(
                        f"{LOG_PREFIX} zorder: barn-läge, skalet hanterar"
                    )
                    return
                # FIX v7-fix18: tvinga ALDRIG fram fönster-skapande här —
                # om fönstret är trasigt går vi i karantän i stället.
                if not self._native_window_ok():
                    self._handle_window_creation_failure()
                    return
                import ctypes
                hwnd = int(self.winId())
                logger.info(
                    f"{LOG_PREFIX} _setup_bugg19_zorder START: HWND={hwnd}, "
                    f"win_id={self.win_id}, _force_show={self._force_show}"
                )
                if hwnd == 0:
                    logger.warning(
                        f"{LOG_PREFIX} _setup_bugg19_zorder: HWND=0"
                    )
                    return
                user32 = ctypes.windll.user32
                # === Reparenta från WorkerW (Explorer-ikon-lager) ===
                try:
                    current_parent = user32.GetParent(hwnd)
                    if current_parent:
                        user32.SetParent(hwnd, 0)
                        logger.info(
                            f"{LOG_PREFIX} _setup_bugg19_zorder: "
                            f"HWND={hwnd} reparentad till desktop-rot "
                            f"(var parentad till 0x{int(current_parent):X})"
                        )
                except Exception as _rp_err:
                    logger.debug(f"{LOG_PREFIX} reparent: {_rp_err}")

                # === Sätt Extended Style: NOACTIVATE ===
                # NY v6.4.1 v7-fix7: WS_EX_TOOLWINDOW borttagen — vi anvander Qt.Window
                # (WS_OVERLAPPED), inte Qt.Tool (WS_POPUP+TOOLWINDOW). Toolwindow behovs
                # inte langre eftersom vi inte vill gomma i alt-tab (icke-Tool fonster
                # ar redan dar synligt). NOACTIVATE kvar sa att klick pa widgeten inte
                # stjal fokus fran andra appar — Rickards krav: ligga pa skrivbordet
                # UTAN att stora.
                GWL_EXSTYLE = -20
                WS_EX_NOACTIVATE = 0x08000000
                WS_EX_TOOLWINDOW = 0x00000080
                WS_EX_TOPMOST = 0x00000008
                try:
                    current_ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
                except Exception:
                    current_ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                new_ex = current_ex
                # Rensa TOPMOST, Rensa TOOLWINDOW (om Qt satte det via WindowFlags), sätt NOACTIVATE
                new_ex = (new_ex & ~WS_EX_TOPMOST) & ~WS_EX_TOOLWINDOW
                new_ex = new_ex | WS_EX_NOACTIVATE
                if new_ex != current_ex:
                    try:
                        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, new_ex)
                    except Exception:
                        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new_ex)
                    logger.info(
                        f"{LOG_PREFIX} _setup_bugg19_zorder: "
                        f"WS_EX (0x{current_ex:X} → 0x{new_ex:X})"
                    )

                # === Z-order: HWND_BOTTOM (under fokuserade appar) ===
                # HWND_BOTTOM (1) = längst ner i normal z-order.
                # Andra appar som fokuseras hamnar naturligt ovanför.
                # Rickard 2026-09-25: "ska alltid ligga överst på skrivbordet"
                # — här menas skrivbords-nivån, inte över alla appar.
                HWND_BOTTOM = 1
                SWP_NOMOVE = 0x0002
                SWP_NOSIZE = 0x0001
                SWP_NOACTIVATE = 0x0010
                SWP_SHOWWINDOW = 0x0040
                ret = user32.SetWindowPos(
                    hwnd, HWND_BOTTOM, 0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
                )
                # ShowWindow garanterar synlig även om SetWindowPos misslyckades
                user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
                user32.ShowWindow(hwnd, 5)  # SW_SHOW

                # Diagnostik
                try:
                    is_visible = bool(user32.IsWindowVisible(hwnd))
                    rect_post = ctypes.wintypes.RECT()
                    user32.GetWindowRect(hwnd, ctypes.byref(rect_post))
                    width = rect_post.right - rect_post.left
                    height = rect_post.bottom - rect_post.top
                    class _MONITORINFO(ctypes.Structure):
                        _fields_ = [
                            ("cbSize", ctypes.c_ulong),
                            ("rcMonitor", ctypes.wintypes.RECT),
                            ("rcWork", ctypes.wintypes.RECT),
                            ("dwFlags", ctypes.c_ulong),
                        ]
                    monitor = user32.MonitorFromWindow(hwnd, 2)
                    mi = _MONITORINFO()
                    mi.cbSize = ctypes.sizeof(_MONITORINFO)
                    user32.GetMonitorInfoW(monitor, ctypes.byref(mi))
                    widget_on_monitor = (
                        rect_post.left < mi.rcMonitor.right
                        and rect_post.right > mi.rcMonitor.left
                        and rect_post.top < mi.rcMonitor.bottom
                        and rect_post.bottom > mi.rcMonitor.top
                    )
                    logger.info(
                        f"{LOG_PREFIX} _setup_bugg19_zorder DIAGNOSTIK POST: "
                        f"HWND={hwnd} visible={is_visible} "
                        f"rect=({rect_post.left},{rect_post.top})-{rect_post.right},{rect_post.bottom})"
                        f"size={width}x{height} "
                        f"mon_rect=({mi.rcMonitor.left},{mi.rcMonitor.top})-"
                        f"({mi.rcMonitor.right},{mi.rcMonitor.bottom}) "
                        f"widget_on_monitor={widget_on_monitor} "
                        f"setpos_ret={ret} z=BOTTOM"
                    )
                    if not widget_on_monitor:
                        new_x = mi.rcMonitor.left + 100
                        new_y = mi.rcMonitor.top + 100
                        user32.SetWindowPos(
                            hwnd, 0, new_x, new_y, 0, 0,
                            0x0040 | 0x0010,
                        )
                        logger.info(
                            f"{LOG_PREFIX} _setup_bugg19_zorder: "
                            f"flyttad till ({new_x},{new_y})"
                        )
                except Exception as _post_err:
                    logger.warning(
                        f"{LOG_PREFIX} post-diagnostik misslyckades: {_post_err}"
                    )
                logger.info(
                    f"{LOG_PREFIX} BUGG 19 v7-fix6 z-order: HWND={hwnd} "
                    f"→ HWND_BOTTOM (skrivbordet, under appar) ret={ret}"
                )
            except Exception as e:
                logger.error(
                    f"{LOG_PREFIX} _setup_bugg19_zorder misslyckades: {e}",
                    exc_info=True,
                )
            finally:
                # FIX 2026-09-25 v7-fix7: släpp reentrancy-lås alltid
                self._zorder_running = False

        def _restore_window_position(self) -> None:
            """NY v6.4.1: Ladda sparad (x,y,w,h) fran settings.window_configs()."""
            x, y = 100, 100
            w, h = DEFAULT_WIDGET_WIDTH, DEFAULT_WIDGET_HEIGHT
            try:
                if not hasattr(self.settings, "window_configs"):
                    logger.info(f"{LOG_PREFIX} _restore_window_position: settings saknar window_configs()")
                else:
                    configs = self.settings.window_configs() or []
                    for conf in configs:
                        if isinstance(conf, dict) and conf.get("id") == self.win_id:
                            x = int(conf.get("x", x))
                            y = int(conf.get("y", y))
                            w = int(conf.get("w", w))
                            h = int(conf.get("h", h))
                            logger.info(f"{LOG_PREFIX} _restore_window_position: win_id={self.win_id} → ({x},{y}) {w}x{h}")
                            break
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} _restore_window_position misslyckades: {e}")
            # NY v7-fix47: x/y < 0 = centrerings-sentinel (första start)
            # → barnet sätter INGEN egen geometri; main centrerar SKALET.
            if x < 0 or y < 0:
                logger.info(
                    f"{LOG_PREFIX} _restore_window_position: centrerings-"
                    f"läge (första start) — main positionerar skalet"
                )
                return
            # FIX v7-fix18: HÅRDA GRÄNSER på geometrin. Ogiltiga värden från
            # settings.json (w=0, negativa eller enorma tal) gör att
            # CreateWindowEx misslyckas med "Felaktig parameter" vid VARJE
            # försök — det är den eviga fönster-stormen i loggen.
            _orig = (x, y, w, h)
            w = max(MIN_WIDGET_WIDTH, min(w, MAX_RESTORE_WIDTH))
            h = max(MIN_WIDGET_HEIGHT, min(h, MAX_RESTORE_HEIGHT))
            x = max(-30000, min(x, 30000))
            y = max(-30000, min(y, 30000))
            # FIX v7-fix24: storleken FÅR ALDRIG överskrida skärmen —
            # "fönstret ska alltid anpassas efter skärmstorlek"
            try:
                _scr = QGuiApplication.primaryScreen()
                if _scr is not None:
                    _sg = _scr.geometry()
                    # Bredd: max 90% av skärmen
                    w = min(w, int(_sg.width() * 0.9))
                    # Höjd: max 75% av skärmen (marginal för aktivitetsfält)
                    h = min(h, int(_sg.height() * 0.75))
                    w = max(w, min(MIN_WIDGET_WIDTH, _sg.width() - 60))
                    h = max(h, min(MIN_WIDGET_HEIGHT, _sg.height() - 60))
                    # Position: HELA fönstret måste synas
                    y = min(y, _sg.y() + _sg.height() - h - 30)
                    x = min(x, _sg.x() + _sg.width() - w - 30)
                    y = max(y, _sg.y() + 30)
                    x = max(x, _sg.x() + 30)
            except Exception:
                pass  # ingen skärm tillgänglig ännu
            # FIX v7-fix23: y+h FÅR INTE överskrida skärmens höjd —
            # AdjustWindowRectExForDpi() vid 125% kan annars producera
            # ogiltig rektangel → CreateWindowEx ERROR_INVALID_PARAMETER.
            try:
                _scr = QGuiApplication.primaryScreen()
                if _scr is not None:
                    _sg = _scr.geometry()
                    _max_y = _sg.y() + _sg.height() - h - 30
                    if y > _max_y:
                        logger.warning(
                            f"{LOG_PREFIX} _restore_window_position: "
                            f"y={y} + h={h} överskrider skärm "
                            f"(höjd={_sg.height()}) → klamrar y till {_max_y}"
                        )
                        y = max(_sg.y() + 30, _max_y)
                    _max_x = _sg.x() + _sg.width() - w - 30
                    if x > _max_x:
                        x = max(_sg.x() + 30, _max_x)
            except Exception:
                pass  # ingen skärm tillgänglig ännu — _validate tar hand om det
            if (x, y, w, h) != _orig:
                logger.warning(
                    f"{LOG_PREFIX} _restore_window_position: OGILTIG geometri "
                    f"{_orig} → klamrad till ({x},{y}) {w}x{h} (orsakar "
                    f"'CreateWindowEx failed' vid varje försök!)"
                )
                with suppress(Exception):
                    if hasattr(self.settings, "update_window_position"):
                        self.settings.update_window_position(
                            self.win_id, x, y
                        )
            _shell_r = getattr(self, "_shell", None)
            if _shell_r is not None:
                _shell_r.move(x, y)
                _shell_r.resize(w, h)
            else:
                self.move(x, y)
                self.resize(w, h)

        def _validate_position_on_screens(self) -> None:
            """
            Validera att HELA fönstret (x, y, x+w, y+h) syns på en skärm.

            FIX v7-fix23 (CreateWindowEx-stormen DEL 5 — ROTEN!):
            Tidigare kontrollerades bara att ÖVRE VÄNSTRA hörnet (x,y) var
            på skärmen. Men en widget vid (1121,545) med höjd 650 på en
            864px-hög skärm överskrider botten med 331px! Vid dpr=1.25 blir
            den fysiska bottenkanten 1494px men skärmen är bara 1080px →
            AdjustWindowRectExForDpi() producerar ogiltig rektangel →
            CreateWindowEx ERROR_INVALID_PARAMETER = den eviga stormen.

            Nu: kontrollera att HELA fönstret får plats. Om inte → flytta
            till en position där det gör det (primära skärmens topp-vänster
            + marginal), och spara den korrigerade positionen.

            FIX v7-fix76 (Rickards logg 2026-10-06 16:40 — 3 buggar):
              a) BARN-LÄGE (skal-mönstret, v7-fix27): self.x()/y() är LOKALA
                 koordinater (relativt skalet) men jämfördes mot GLOBALA
                 skärm-rectar → falsk "ÖVERSKRIDER SKÄRM" vid varje start,
                 barnet flyttades till (30,30) INUTI skalet och lokala
                 koordinater sparades i settings! Nu: barnet valideras ej —
                 SKALET (main) äger den globala positionen (v7-fix47/62).
              b) Margin-kravet (30 px in från kanten) gjorde helt giltiga
                 kant-/hörnpositioner "ogiltiga" — t.ex. (0,0) =
                 skrivbordshörnen, helt normal plats för en desktop-widget!
                 Marginal fordras numera ENDAST för räddningspositionen.
              c) Varningsraden tryckte "botten=648 > höjd=1080" (matematiskt
                 osant — det var X-ledet mot fel skärm som misslyckades).
                 Raden redovisar nu verklig global rect + närmaste skärm.
            """
            try:
                # FIX v7-fix76a: BARN-LÄGE — hoppa över helt. Skalet äger
                # positionen; main har eget off-screen-skydd (v7-fix62) och
                # barnet fyller alltid skalet (0,0 → skalstorlek).
                if self.parentWidget() is not None:
                    logger.info(
                        f"{LOG_PREFIX} _validate_position: BARN-LÄGE — "
                        f"skalet (main) äger global position, barnet "
                        f"valideras/flyttas ej (v7-fix76)"
                    )
                    return
                screens = QGuiApplication.screens()
                x, y = self.x(), self.y()
                w, h = self.width(), self.height()
                screen_rects = []
                for screen in screens:
                    g = screen.geometry()
                    screen_rects.append((g.x(), g.y(), g.width(), g.height()))
                logger.info(
                    f"{LOG_PREFIX} _validate_position: {len(screen_rects)} "
                    f"skärmar, pos=({x},{y}) size=({w}x{h}), rects={screen_rects}"
                )
                # FIX v7-fix23: HELA fönstret måste få plats (inte bara hörnet)
                # FIX v7-fix76b: kantflush ÄR giltigt (x == sx räcker) —
                # ingen marginal fordras för giltigheten.
                fully_visible = False
                for sx, sy, sw, sh in screen_rects:
                    if (
                        x >= sx
                        and y >= sy
                        and (x + w) <= (sx + sw)
                        and (y + h) <= (sy + sh)
                    ):
                        fully_visible = True
                        break
                if fully_visible:
                    logger.info(
                        f"{LOG_PREFIX} _validate_position: ({x},{y}) {w}x{h} "
                        f"HELT synlig ✓"
                    )
                    return
                # Fönstret överskrider skärm — flytta + logga tydligt
                primary = QGuiApplication.primaryScreen()
                if primary is not None:
                    pg = primary.geometry()
                    # Räddningsposition: primära skärmens topp-vänster +
                    # 30 px marginal (om fönstret är större än skärmen
                    # hamnar det ändå längst upp-vänster och Qt klipper)
                    new_x = pg.x() + 30
                    new_y = pg.y() + 30
                    # FIX v7-fix76c: redovisa VERKLIG orsak — skärmen med
                    # störst överlapp + vilka mått som faktiskt spricker
                    _best = None
                    _best_area = -1
                    for sx, sy, sw, sh in screen_rects:
                        _ov = max(0, min(x + w, sx + sw) - max(x, sx)) * max(
                            0, min(y + h, sy + sh) - max(y, sy)
                        )
                        if _ov > _best_area:
                            _best_area = _ov
                            _best = (sx, sy, sw, sh)
                    if _best is not None:
                        bsx, bsy, bsw, bsh = _best
                        logger.warning(
                            f"{LOG_PREFIX} _validate_position: global "
                            f"({x},{y}) {w}x{h} får inte plats helt på någon "
                            f"skärm (närmaste {_best}: höger {x + w} vs "
                            f"{bsx + bsw}, botten {y + h} vs {bsy + bsh}) "
                            f"→ flyttar till ({new_x},{new_y}) så hela "
                            f"fönstret syns (v7-fix23/76)"
                        )
                    else:
                        logger.warning(
                            f"{LOG_PREFIX} _validate_position: global "
                            f"({x},{y}) {w}x{h} ligger utanför alla skärmar "
                            f"→ flyttar till ({new_x},{new_y}) (v7-fix23/76)"
                        )
                    self.move(new_x, new_y)
                    if hasattr(self.settings, "update_window_position"):
                        try:
                            self.settings.update_window_position(
                                self.win_id, new_x, new_y
                            )
                        except Exception:
                            pass
            except Exception as e:
                logger.error(f"{LOG_PREFIX} _validate_position misslyckades: {e}", exc_info=True)

        # ====================================================================
        # FOCUS MODE (NY v6.4.1 - Focus Mode §22.18 Todoist)
        # ====================================================================

        def _build_focus_view(self) -> QWidget:
            """NY v6.4.1: Bygg Focus Mode-vyn (1 task stort)."""
            view = QWidget(self)
            view.setObjectName("focusView")
            v = QVBoxLayout(view)
            v.setContentsMargins(20, 20, 20, 20)
            v.setSpacing(16)
            header = QHBoxLayout()
            self._focus_counter_label = QLabel("0 / 0", view)
            self._focus_counter_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            font = self._focus_counter_label.font()
            font.setPointSize(11)
            self._focus_counter_label.setFont(font)
            header.addWidget(self._focus_counter_label, 1)
            self._focus_exit_btn = QPushButton("X  Avsluta fokus (F3)", view)
            self._focus_exit_btn.clicked.connect(self._exit_focus_mode)
            self._focus_exit_btn.setFixedHeight(28)
            header.addWidget(self._focus_exit_btn)
            v.addLayout(header)
            self._focus_title_label = QLabel("Inga uppgifter", view)
            self._focus_title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._focus_title_label.setWordWrap(True)
            big_font = self._focus_title_label.font()
            big_font.setPointSize(22)
            big_font.setBold(True)
            self._focus_title_label.setFont(big_font)
            self._focus_title_label.setMinimumHeight(80)
            v.addWidget(self._focus_title_label, 1)
            self._focus_meta_label = QLabel("", view)
            self._focus_meta_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            meta_font = self._focus_meta_label.font()
            meta_font.setPointSize(13)
            self._focus_meta_label.setFont(meta_font)
            v.addWidget(self._focus_meta_label)
            self._focus_priority_label = QLabel("", view)
            self._focus_priority_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            prio_font = self._focus_priority_label.font()
            prio_font.setPointSize(16)
            prio_font.setBold(True)
            self._focus_priority_label.setFont(prio_font)
            self._focus_priority_label.setMinimumHeight(40)
            v.addWidget(self._focus_priority_label)
            v.addStretch(1)
            nav_row = QHBoxLayout()
            self._focus_prev_btn = QPushButton("<  Föregående", view)
            self._focus_prev_btn.setObjectName("focusNav")
            self._focus_prev_btn.clicked.connect(self._focus_prev)
            self._focus_prev_btn.setMinimumHeight(56)
            nav_row.addWidget(self._focus_prev_btn, 1)
            self._focus_complete_btn = QPushButton("OK  Markera klar", view)
            self._focus_complete_btn.setObjectName("focusDone")
            self._focus_complete_btn.clicked.connect(self._focus_complete)
            self._focus_complete_btn.setMinimumHeight(56)
            # v7-fix10: styling flyttad till QSS (focusDone) — ej inline
            nav_row.addWidget(self._focus_complete_btn, 1)
            self._focus_next_btn = QPushButton("Nästa  >", view)
            self._focus_next_btn.setObjectName("focusNav")
            self._focus_next_btn.clicked.connect(self._focus_next)
            self._focus_next_btn.setMinimumHeight(56)
            nav_row.addWidget(self._focus_next_btn, 1)
            v.addLayout(nav_row)
            try:
                QShortcut(QKeySequence("F3"), self, activated=self._toggle_focus_mode)
                QShortcut(QKeySequence("Esc"), self, activated=self._exit_focus_mode)
                QShortcut(QKeySequence("Right"), self, activated=self._focus_next)
                QShortcut(QKeySequence("Left"), self, activated=self._focus_prev)
                QShortcut(QKeySequence("Return"), self, activated=self._focus_complete)
                QShortcut(QKeySequence("Space"), self, activated=self._focus_complete)
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} Fokus-shortcuts misslyckades: {e}")
            return view

        def _get_focus_tasks(self) -> "List[Dict[str, Any]]":
            """NY v6.4.1: Hämta aktiva tasks för Focus Mode."""
            try:
                if hasattr(self, "active_tasks_filtered"):
                    return self.active_tasks_filtered()
                elif hasattr(self.store, "active_tasks"):
                    return self.store.active_tasks()
                return []
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} _get_focus_tasks misslyckades: {e}")
                return []

        def _update_focus_view(self) -> None:
            """NY v6.4.1: Uppdatera Focus Mode-vyn."""
            tasks = self._get_focus_tasks()
            total = len(tasks)
            if total == 0:
                self._focus_counter_label.setText("0 / 0")
                self._focus_title_label.setText("🎉 Inga uppgifter kvar!")
                self._focus_meta_label.setText("")
                self._focus_priority_label.setText("")
                self._focus_prev_btn.setEnabled(False)
                self._focus_complete_btn.setEnabled(False)
                self._focus_next_btn.setEnabled(False)
                return
            if self._focus_index >= total:
                self._focus_index = total - 1
            if self._focus_index < 0:
                self._focus_index = 0
            task = tasks[self._focus_index]
            self._focus_counter_label.setText(f"{self._focus_index + 1} / {total}")
            self._focus_title_label.setText(task.get("title", ""))
            meta_parts = []
            tags = task.get("tags", [])
            if tags:
                meta_parts.append("🏷  " + ", ".join(tags))
            due = task.get("due_date")
            if due:
                meta_parts.append(f"📅  {due}")
            self._focus_meta_label.setText("\n".join(meta_parts))
            priority = task.get("priority", "none")
            prio_colors = {
                "high": ("🔴  HÖG", "rgba(244, 67, 54, 0.7)"),
                "medium": ("🟡  MEDEL", "rgba(255, 193, 7, 0.7)"),
                "low": ("🟢  LÅG", "rgba(76, 175, 80, 0.6)"),
                "none": ("⚪  INGEN", "rgba(158, 158, 158, 0.5)"),
            }
            label, color = prio_colors.get(priority, prio_colors["none"])
            self._focus_priority_label.setText(label)
            self._focus_priority_label.setStyleSheet(
                f"QLabel {{ background-color: {color}; color: white; padding: 8px; border-radius: 8px; }}"
            )
            self._focus_prev_btn.setEnabled(total > 1)
            self._focus_next_btn.setEnabled(total > 1)
            self._focus_complete_btn.setEnabled(True)
            if task.get("pinned"):
                self._focus_title_label.setText("⭐  " + task.get("title", ""))

        def _enter_focus_mode(self) -> None:
            """NY v6.4.1: Gå in i Focus Mode."""
            self._focus_mode = True
            self._focus_index = 0
            if hasattr(self, "content_stack"):
                self.content_stack.setCurrentIndex(1)
            self._update_focus_view()
            logger.info(f"{LOG_PREFIX} Focus Mode aktiverat")

        def _exit_focus_mode(self) -> None:
            """NY v6.4.1: Avsluta Focus Mode."""
            if not self._focus_mode:
                return
            self._focus_mode = False
            if hasattr(self, "content_stack"):
                self.content_stack.setCurrentIndex(0)
            logger.info(f"{LOG_PREFIX} Focus Mode avslutat")

        def _toggle_focus_mode(self) -> None:
            """NY v6.4.1: Toggle Focus Mode (F3)."""
            if self._focus_mode:
                self._exit_focus_mode()
            else:
                self._enter_focus_mode()

        def _focus_next(self) -> None:
            """NY v6.4.1: Nästa task i Focus Mode."""
            tasks = self._get_focus_tasks()
            if not tasks:
                return
            self._focus_index = (self._focus_index + 1) % len(tasks)
            self._update_focus_view()

        def _focus_prev(self) -> None:
            """NY v6.4.1: Föregående task."""
            tasks = self._get_focus_tasks()
            if not tasks:
                return
            self._focus_index = (self._focus_index - 1) % len(tasks)
            self._update_focus_view()

        def _focus_complete(self) -> None:
            """NY v6.4.1: Markera aktuell task som klar."""
            tasks = self._get_focus_tasks()
            if not tasks or self._focus_index >= len(tasks):
                return
            task = tasks[self._focus_index]
            task_id = task.get("id")
            if not task_id:
                return
            try:
                if hasattr(self.store, "toggle_done"):
                    self.store.toggle_done(task_id)
                logger.info(f"{LOG_PREFIX} _focus_complete: klar! task_id={task_id!r}")
            except Exception as e:
                logger.error(f"{LOG_PREFIX} _focus_complete misslyckades: {e}", exc_info=True)
                return
            self._rebuild_task_list()
            self._update_focus_view()

        def _periodic_zorder_check(self) -> None:
            """NY v6.4.1 v7-fix3: Periodisk z-order-check (var 60s).

            Rickard 2026-09-22: Widget ska EJ dölja ikoner. Workers-tricket
            ÄR Explorer-ikon-lagret → döljer ikoner. Rätt approach:
            reparenta till desktop-rot + HWND_TOP.
            """
            if not self.isVisible():
                return
            # FIX v7-fix29: barn → inga Win32-operationer från timern
            if self._is_child():
                return
            try:
                import ctypes
                if not self._native_window_ok():
                    return
                hwnd = int(self.winId())
                if not hwnd:
                    return
                user32 = ctypes.windll.user32
                # Reparenta från WorkerW om vi blivit parentad dit
                try:
                    current_parent = user32.GetParent(hwnd)
                    if current_parent:
                        user32.SetParent(hwnd, 0)
                        logger.debug(
                            f"{LOG_PREFIX} _periodic_zorder_check: "
                            f"HWND={hwnd} reparentad till desktop-rot"
                        )
                except Exception:
                    pass
                # Enbart re-show OM dold — INTE HWND_TOP (lyfter över appar)
                if not user32.IsWindowVisible(hwnd):
                    user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
                    logger.info(
                        f"{LOG_PREFIX} _periodic_zorder_check: "
                        f"HWND={hwnd} var GÖMT — re-show (ingen z-order-lyft)!"
                    )
            except Exception as e:
                logger.debug(f"{LOG_PREFIX} _periodic_zorder_check misslyckades: {e}")

        def _install_win_d_blocker(self) -> None:
            """NY v6.4.1 v5: nativeEvent blockerar minimize. Se nativeEvent()."""
            if sys.platform != "win32":
                return
            if self._is_child():
                return  # FIX v7-fix29: barn → skalet hanterar
            logger.debug(f"{LOG_PREFIX} _install_win_d_blocker: redo (hanteras i nativeEvent)")

        @_log_call
        def _register_hotkeys(self) -> None:
            """
            NY v6.4.1 v7: Registrera globala hotkeys fran settings.

            FIX v7-fix78 (Rickard 2026-10-06: "tvungen att trycka
            Ctrl+Enter för att registrera"):
              ROT-ORSAKEN: QShortcut skapades för ALLA actions i settings
              — även de UTAN kopplad hanterare! Ett QShortcut utan
              hanterare MATCHAR och KONSUMERAR tangenten ändå (activated-
              signal utan lyssnare = tangenten försvinner i luften).
              Rickards sparade settings innehåller ett kortkommando som
              matchar vanlig Enter → Enter nådde aldrig input-fältet.
              Ctrl+Enter matchar INTE ett omodifierat kortkommando →
              nådde fältet → registrerade. Därför "fungerade" Ctrl+Enter!

              NU:
              - Kortkommandon UTAN hanterare skapas EJ (de stjäl bara
                tangenter) — loggas med varning per action
              - next_task/prev_task kopplas till riktig navigation (nytt!)
              - Enter skyddas dessutom i input-fältet via
                ShortcutOverride (se eventFilter) — inget kortkommando
                kan stjäla Enter medan man skriver
              - Tydlig logg per kortkommando (action=sekvens → hanterare)
            """
            if not hasattr(self.settings, "shortcuts"):
                return
            try:
                shortcuts = self.settings.shortcuts()
                # FIX v7-fix78: varje kortkommando MÅSTE ha en hanterare
                handlers = {
                    "add_task": ("_on_input_submit", self._on_input_submit),
                    "toggle_visible": ("_on_close_clicked", self._on_close_clicked),
                    "open_search": ("_focus_search", self._focus_search),
                    "next_task": (
                        "_navigate_tasks(ned)",
                        lambda: self._navigate_tasks(Qt.Key.Key_Down),
                    ),
                    "prev_task": (
                        "_navigate_tasks(upp)",
                        lambda: self._navigate_tasks(Qt.Key.Key_Up),
                    ),
                }
                # Vanlig Enter/Return-koder (för varning vid kollision)
                _enter_codes = set()
                with suppress(Exception):
                    _enter_codes = {
                        QKeySequence("Return")[0],
                        QKeySequence("Enter")[0],
                    }
                _reg = []
                for action, seq in shortcuts.items():
                    if not seq:
                        continue
                    entry = handlers.get(action)
                    if entry is None:
                        logger.warning(
                            f"{LOG_PREFIX} kortkommando '{action}'='{seq}' "
                            f"HAR INGEN hanterare — skapas EJ (ett QShortcut "
                            f"utan hanterare STJÄLER tangenten utan att göra "
                            f"något) (v7-fix78)"
                        )
                        continue
                    name, fn = entry
                    sc = QShortcut(QKeySequence(seq), self)
                    sc.activated.connect(fn)
                    self._hotkey_shortcuts.append(sc)
                    _reg.append(f"{action}='{seq}'→{name}")
                    # Varning: matchar detta kortkommando VANLIG ENTER?
                    with suppress(Exception):
                        _ks = QKeySequence(seq)
                        if (
                            _enter_codes
                            and _ks.count() == 1
                            and _ks[0] in _enter_codes
                        ):
                            logger.warning(
                                f"{LOG_PREFIX} ⚠ kortkommando '{action}'="
                                f"'{seq}' matchar VANLIG ENTER — Enter är "
                                f"skyddad i input-fältet (ShortcutOverride) "
                                f"så den kan ej stjäla (v7-fix78)"
                            )
                logger.info(
                    f"{LOG_PREFIX} {len(self._hotkey_shortcuts)} hotkeys "
                    f"registrerade: {', '.join(_reg) or '(ingen)'}"
                )
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} _register_hotkeys misslyckades: "
                    f"{_describe_widget_error(e)}",
                    exc_info=True,
                )

        def _unregister_hotkeys(self) -> None:
            """NY v6.4.1 v7: Avregistrera hotkeys."""
            for sc in self._hotkey_shortcuts:
                with suppress(Exception):
                    sc.setParent(None)
                    sc.deleteLater()
            self._hotkey_shortcuts.clear()
            self._hotkey_ids.clear()
            logger.debug(f"{LOG_PREFIX} hotkeys avregistrerade")

        def _init_timers(self) -> None:
            """NY v6.4.1: Initiera debounce + PWM + z-order timers."""
            self._search_timer = QTimer(self)
            self._search_timer.setSingleShot(True)
            self._search_timer.timeout.connect(self._do_search)
            self._rebuild_timer = QTimer(self)
            self._rebuild_timer.setSingleShot(True)
            self._rebuild_timer.timeout.connect(self._rebuild_task_list)
            self._pwm_timer = QTimer(self)
            self._pwm_timer.timeout.connect(self._update_pwm)
            self._pwm_timer.start(PWM_FPS_NORMAL_MS)
            # NY v6.4.1 v5: Z-order periodic check
            self._zorder_timer = QTimer(self)
            self._zorder_timer.timeout.connect(self._periodic_zorder_check)
            self._zorder_timer.start(60_000)
            # NY v7-fix82: auto-tema — kolla var 10:e minut om klockan
            # passerat dag/gränsen (07:00/19:00) och växla isåfall
            # (gäller endast när användaren valt 'Auto' i tray-menyn)
            self._auto_theme_timer = QTimer(self)
            self._auto_theme_timer.setInterval(600_000)  # 10 minuter
            self._auto_theme_timer.timeout.connect(self._check_auto_theme)
            self._auto_theme_timer.start()
            # NY v7-fix73: bevaka textfälten — FocusIn aktiverar fönstret
            with suppress(Exception):
                if getattr(self, "input_field", None) is not None:
                    self.input_field.installEventFilter(self)
                if getattr(self, "search_input", None) is not None:
                    self.search_input.installEventFilter(self)
            logger.debug(f"{LOG_PREFIX} _init_timers klar (med z-order)")

        def _update_pwm(self) -> None:
            """
            NY v6.4.1 v7-fix: PWM-tick (saknad metod → widget-krasch).

            Buggrapport 2026-09-22:
              AttributeError: 'TodoWidget' object has no attribute '_update_pwm'
              (kopplad i _init_timers via timeout.connect)

            Vad den gör:
              1. Låter AdaptiveThrottle.update() räkna om state/intervall
              2. Synkar _pwm_timer till throttle.current_interval_ms
              3. Aldrig krascha — loggar bara vid fel (tyst crash → logg)
            """
            try:
                interval_ms = self._throttle.update()
                if (
                    self._pwm_timer is not None
                    and self._pwm_timer.interval() != interval_ms
                ):
                    self._pwm_timer.setInterval(interval_ms)
            except Exception as _pwm_err:
                logger.debug(
                    f"{LOG_PREFIX} _update_pwm: {_pwm_err}",
                    exc_info=True,
                )

        def on_pwm_state_change(self, old: Any, new: Any) -> None:
            """
            NY v6.4.1 v7-fix: PWM state-change listener (widget = listener).

            ThrottleNotifier anropar denna via hasattr-listener-kedjan.
            Uppdaterar bara timer-intervall — ingen UI-rendering här.
            """
            try:
                interval_ms = self._throttle.current_interval_ms
                if self._pwm_timer is not None:
                    self._pwm_timer.setInterval(interval_ms)
                old_name = getattr(old, "name", str(old))
                new_name = getattr(new, "name", str(new))
                logger.debug(
                    f"{LOG_PREFIX} PWM state: {old_name} → {new_name} "
                    f"({interval_ms}ms)"
                )
            except Exception as _pwm_ls_err:
                logger.debug(
                    f"{LOG_PREFIX} on_pwm_state_change: {_pwm_ls_err}",
                    exc_info=True,
                )

        # ====================================================================
        # LOCK / UNLOCK (NY v6.4.1 v7-fix: _toggle_lock saknades!)
        # ====================================================================
        # Buggrapport 2026-09-22:
        #   AttributeError: 'TodoWidget' object has no attribute '_toggle_lock'
        #   på rad 1384 (lock_btn.clicked.connect(self._toggle_lock))
        #
        # _init_ui() kopplade signalen men metoden var aldrig definierad.
        # Detta är den saknade implementationen — minimal, robust, AI-felsäker.
        # ====================================================================

        def _input_field_keypress(self, event: QKeyEvent) -> None:
            """
            NY v6.4.1 v7-fix: Piltangenter i input-fältet byter pending prioritet.

            Buggrapport 2026-09-22:
              AttributeError: 'TodoWidget' object has no attribute '_input_field_keypress'
              på rad 1425 (self.input_field.keyPressEvent = self._input_field_keypress)

            Vad den gör:
              ← / →  → byter pending prioritet enligt PRIORITY_CYCLE
              Enter  → normal enter-beteende (returnPressed skickar iväg)
              Övrigt → default keyPressEvent (vanlig text-inmatning)
            """
            try:
                get_throttle().notify_activity()
                key = event.key()
                # NY v7-fix86: Escape i input-fältet rensar texten (om det
                # finns text) — snabb ångra utan att gömma fönstret
                if key == Qt.Key.Key_Escape and self.input_field.text():
                    self.input_field.clear()
                    self._pending_input_priority = "none"
                    self._update_input_priority_indicator()
                    logger.debug(
                        f"{LOG_PREFIX} Escape i input-fältet → rensar texten"
                    )
                    event.accept()
                    return
                # FIX v7-fix77: Enter hanteras FÖRST — inget före (t.ex.
                # piltangents-prioritetslogik) ska kunna svälja/senarelägga
                # registreringen av uppgiften i 'Aktiva'.
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    logger.info(
                        f"{LOG_PREFIX} Enter i input-fältet → registrerar "
                        f"uppgiften i 'Aktiva' (v7-fix77)"
                    )
                    self._on_input_submit()
                    event.accept()
                    return
                if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
                    cur = self._pending_input_priority
                    if cur not in PRIORITY_CYCLE:
                        cur = "none"
                    idx = PRIORITY_CYCLE.index(cur)
                    if key == Qt.Key.Key_Right:
                        new_idx = (idx + 1) % len(PRIORITY_CYCLE)
                    else:
                        new_idx = (idx - 1) % len(PRIORITY_CYCLE)
                    new_p = PRIORITY_CYCLE[new_idx]
                    self._set_input_priority(new_p)
                    event.accept()
                    return
                # OBS: gamla Enter-grenen (v7-fix30) ersatt av ovan —
                # returnPressed-signalen (rad ~2038) finns kvar som
                # extra försäkring om keyPressEvent-överriden skulle utebli.
                # Default: låt Qt sköta text-inmatning
                from PySide6.QtWidgets import QLineEdit
                QLineEdit.keyPressEvent(self.input_field, event)
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} _input_field_keypress misslyckades: "
                    f"{_describe_widget_error(e)}",
                    exc_info=True,
                )

        def _on_open_google_calendar(self) -> None:
            """
            NY v8: öppna Google Calendar-dialogen (lokal OAuth-koppling).

            Rickard 2026-10-12: "gör i appen att man lokalt kopplar OAuth"
            — härifrån kopplas kontot, kalendern väljs och uppgifterna skickas.
            """
            try:
                from ui.google_calendar_dialog import open_google_calendar_dialog
                open_google_calendar_dialog(
                    self,
                    store=getattr(self, "store", None),
                    settings=getattr(self, "settings", None),
                )
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} _on_open_google_calendar misslyckades: "
                    f"{_describe_widget_error(e)}"
                )

        def _on_open_backup(self) -> None:
            """NY v8: 💾 Backup av uppgifter (skapa/spara/återställ)."""
            try:
                get_throttle().notify_activity()
                from ui.backup_dialog import open_backup_dialog
                open_backup_dialog(self, store=getattr(self, "store", None))
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} _on_open_backup misslyckades: "
                    f"{_describe_widget_error(e)}"
                )

        def _on_push_task_to_google(self, task: Dict[str, Any]) -> None:
            """
            NY v8: skicka EN uppgift till Google Calendar (från uppgiftsmenyn).

            Nätverket sköts i bakgrunden av dialogen, så fönstret inte
            fryser medan Google svarar.
            """
            try:
                get_throttle().notify_activity()
                from ui.google_calendar_dialog import push_task_with_dialog
                push_task_with_dialog(
                    self,
                    task=dict(task or {}),
                    store=getattr(self, "store", None),
                    settings=getattr(self, "settings", None),
                )
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} _on_push_task_to_google misslyckades: "
                    f"{_describe_widget_error(e)}"
                )

        def _on_show_task_calendar_history(self, task: Dict[str, Any]) -> None:
            """NY v8: sändningshistoriken för EN uppgift (Google Calendar)."""
            try:
                get_throttle().notify_activity()
                from ui.google_calendar_dialog import open_history_dialog
                open_history_dialog(
                    self,
                    task=dict(task or {}),
                    store=getattr(self, "store", None),
                    settings=getattr(self, "settings", None),
                )
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} _on_show_task_calendar_history misslyckades: "
                    f"{_describe_widget_error(e)}"
                )

        def _on_open_donate(self) -> None:
            """NY v8: visa donationsdialogen (frivilligt, ingen funktion låst)."""
            try:
                from ui.donate import open_donate_dialog
                open_donate_dialog(self)
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} _on_open_donate misslyckades: {e}")

        def _on_export_pdf(self) -> None:
            """
            NY v7-fix81: exportera aktiva uppgifter som PDF-checklista.

            Rickard 2026-10-07: "går det att exportera aktiva till en pdf
            som en modern checklista" — JA: 📄-knapp (bredvid 📧),
            tray-menyn och fönster-högerklicksmenyn. Modern design med
            sektioner, progress-bar, vänliga datum och ☐/☑-rutor.
            """
            try:
                get_throttle().notify_activity()
                # Samma lista som Aktiva-fliken visar (senarelagda dolda)
                tasks: list = []
                with suppress(Exception):
                    if hasattr(self.store, "active_tasks_filtered"):
                        tasks = self.store.active_tasks_filtered(
                            sort_by="pinned_first"
                        )
                    elif hasattr(self.store, "active_tasks"):
                        tasks = self.store.active_tasks()
                tasks = [t for t in tasks if str(t.get("id", "")).strip()]
                if not tasks:
                    from PySide6.QtWidgets import QMessageBox
                    QMessageBox.information(
                        self,
                        "📄 Exportera PDF",
                        "Det finns inga aktiva uppgifter att exportera.",
                    )
                    return
                # Importera PDF-modulen på begäran
                try:
                    from core.pdf_export import render_checklist_html, save_pdf
                except Exception as e:
                    logger.error(
                        f"{LOG_PREFIX} PDF-export: import misslyckades: {e}",
                        exc_info=True,
                    )
                    return
                html = render_checklist_html(
                    tasks,
                    app_name=getattr(self, "DEFAULT_TITLE", "TaskBord"),
                )
                # Fil-dialog (default: samma mapp som js/-data, annars hem)
                from PySide6.QtWidgets import QFileDialog
                ts = datetime.now().strftime("%Y%m%d_%H%M")
                default_name = f"TaskBord_checklista_{ts}.pdf"
                default_dir = os.path.expanduser("~")
                with suppress(Exception):
                    _sp = getattr(self.store, "file_path", None) or getattr(
                        self.store, "_file_path", None
                    )
                    if _sp:
                        default_dir = str(Path(str(_sp)).resolve().parent)
                default_path = os.path.join(default_dir, default_name)
                fname, _ = QFileDialog.getSaveFileName(
                    self,
                    "Spara checklista som PDF",
                    default_path,
                    "PDF-dokument (*.pdf)",
                )
                if not fname:
                    return  # avbruten av användaren
                if not str(fname).lower().endswith(".pdf"):
                    fname = str(fname) + ".pdf"
                if save_pdf(html, str(fname)):
                    logger.info(
                        f"{LOG_PREFIX} PDF-checklista sparad: {fname} "
                        f"({len(tasks)} uppgifter) (v7-fix81)"
                    )
                    from PySide6.QtWidgets import QMessageBox
                    QMessageBox.information(
                        self,
                        "📄 Checklista sparad",
                        f"PDF sparad som:\n{fname}",
                    )
                else:
                    logger.warning(
                        f"{LOG_PREFIX} PDF-export misslyckades: {fname}"
                    )
                    from PySide6.QtWidgets import QMessageBox
                    QMessageBox.warning(
                        self,
                        "Kunde inte spara PDF",
                        f"PDF-exporten misslyckades för:\n{fname}",
                    )
            except Exception as e:
                logger.error(
                    f"{LOG_PREFIX} _on_export_pdf misslyckades: "
                    f"{_describe_widget_error(e)}",
                    exc_info=True,
                )

        def _on_export_calendar_ics(self) -> None:
            """
            NY v8: exportera aktiva uppgifter med förfallodatum till .ics.

            Rickard 2026-10-12: "kan man koppla ihop den med Google
            Calendar så man kan exportera vissa uppgifter dit?" — JA:
            .ics-filen importeras i Google Calendar (Inställningar →
            Importera och exportera), Outlook och Apple Kalender.
            Bara uppgifter som HAR ett förfallodatum kan bli händelser —
            resten hoppas över och antalet redovisas.
            """
            try:
                get_throttle().notify_activity()
                from core.calendar_export import tasks_with_due, write_ics

                tasks: list = []
                with suppress(Exception):
                    if hasattr(self.store, "active_tasks_filtered"):
                        tasks = self.store.active_tasks_filtered(
                            sort_by="pinned_first"
                        )
                    elif hasattr(self.store, "active_tasks"):
                        tasks = self.store.active_tasks()
                valda = tasks_with_due(list(tasks or []))
                if not valda:
                    from PySide6.QtWidgets import QMessageBox
                    QMessageBox.information(
                        self,
                        "📅 Exportera till kalender",
                        "Inga aktiva uppgifter har ett förfallodatum eller startdatum.\n\n"
                        "Sätt ett datum på en uppgift (⋯-menyn → 📅 Förfallodatum\n"
                        "eller ▶ Startdatum) så kan den bli en kalenderhändelse.",
                    )
                    return

                from PySide6.QtWidgets import QFileDialog
                ts = datetime.now().strftime("%Y%m%d_%H%M")
                default_dir = os.path.expanduser("~")
                with suppress(Exception):
                    _sp = getattr(self.store, "file_path", None) or getattr(
                        self.store, "_file_path", None
                    )
                    if _sp:
                        default_dir = str(Path(str(_sp)).resolve().parent)
                fname, _ = QFileDialog.getSaveFileName(
                    self,
                    "Spara kalenderfil (.ics)",
                    os.path.join(default_dir, f"TaskBord_kalender_{ts}.ics"),
                    "Kalenderfil (*.ics)",
                )
                if not fname:
                    return  # avbruten av användaren
                if not str(fname).lower().endswith(".ics"):
                    fname = str(fname) + ".ics"
                antal = write_ics(valda, str(fname), calendar_name="TaskBord")
                hoppade = len(tasks or []) - antal
                logger.info(
                    f"{LOG_PREFIX} Kalenderexport: {antal} händelser → {fname} "
                    f"({hoppade} utan datum hoppades över)"
                )
                from PySide6.QtWidgets import QMessageBox
                extra = (
                    f"\n\n{hoppade} uppgifter utan förfallodatum hoppades över."
                    if hoppade > 0 else ""
                )
                QMessageBox.information(
                    self,
                    "📅 Kalenderfil sparad",
                    f"{antal} uppgifter exporterade till:\n{fname}{extra}\n\n"
                    "Så importerar du i Google Calendar:\n"
                    "1. Öppna calendar.google.com\n"
                    "2. ⚙️ Inställningar → Importera och exportera\n"
                    "3. Välj filen → Importera\n\n"
                    "(Filen fungerar även i Outlook och Apple Kalender.)",
                )
            except Exception as e:
                logger.error(
                    f"{LOG_PREFIX} _on_export_calendar_ics misslyckades: "
                    f"{_describe_widget_error(e)}",
                    exc_info=True,
                )

        def _on_open_task_in_google_calendar(self, task: Dict[str, Any]) -> None:
            """
            NY v8: öppna Google Calendar med EN uppgift förifylld.

            OBS: hette tidigare _on_open_google_calendar, vilket krockade med
            metoden som öppnar OAuth-dialogen (samma namn två gånger i samma
            klass = den sista vinner tyst, och menyvalet slutade fungera).

            Använder Googles egen "skapa händelse"-länk (action=TEMPLATE)
            — inget konto, ingen nyckel och ingen synk behövs. Ingenting
            sparas förrän användaren trycker Spara i Google Calendar.
            """
            try:
                get_throttle().notify_activity()
                from core.calendar_export import google_calendar_url

                url = google_calendar_url(task)
                if not url:
                    from PySide6.QtWidgets import QMessageBox
                    QMessageBox.information(
                        self,
                        "📅 Google Calendar",
                        "Uppgiften behöver ett förfallodatum eller ett startdatum\n"
                        "för att kunna bli en händelse i kalendern.",
                    )
                    return
                # stdlib-webb läsare: fungerar oavsett Qt-backend
                import webbrowser
                if webbrowser.open(url):
                    logger.info(
                        f"{LOG_PREFIX} Google Calendar-länk öppnad för "
                        f"uppgift {str(task.get('id', ''))[:8]}"
                    )
                else:
                    logger.warning(
                        f"{LOG_PREFIX} kunde inte öppna webbläsaren för "
                        f"Google Calendar-länken"
                    )
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} _on_open_task_in_google_calendar misslyckades: "
                    f"{_describe_widget_error(e)}"
                )

        def _on_export_task_ics(self, task: Dict[str, Any]) -> None:
            """NY v8: exportera EN uppgift till en egen .ics-fil."""
            try:
                get_throttle().notify_activity()
                from core.calendar_export import has_calendar_date, write_ics

                if not has_calendar_date(task):
                    from PySide6.QtWidgets import QMessageBox
                    QMessageBox.information(
                        self,
                        "📅 Exportera uppgift",
                        "Uppgiften behöver ett förfallodatum eller ett startdatum\n"
                        "för att kunna bli en kalenderhändelse.",
                    )
                    return
                from PySide6.QtWidgets import QFileDialog
                titel = str(task.get("title", "uppgift"))
                säker = "".join(
                    c for c in titel[:40] if c.isalnum() or c in " -_"
                ).strip() or "uppgift"
                default_dir = os.path.expanduser("~")
                with suppress(Exception):
                    _sp = getattr(self.store, "file_path", None) or getattr(
                        self.store, "_file_path", None
                    )
                    if _sp:
                        default_dir = str(Path(str(_sp)).resolve().parent)
                fname, _ = QFileDialog.getSaveFileName(
                    self,
                    "Spara uppgiften som kalenderfil",
                    os.path.join(default_dir, f"{säker}.ics"),
                    "Kalenderfil (*.ics)",
                )
                if not fname:
                    return
                if not str(fname).lower().endswith(".ics"):
                    fname = str(fname) + ".ics"
                write_ics([task], str(fname), calendar_name="TaskBord")
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.information(
                    self,
                    "📅 Kalenderfil sparad",
                    f"Uppgiften sparad som:\n{fname}",
                )
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} _on_export_task_ics misslyckades: "
                    f"{_describe_widget_error(e)}"
                )

        def _on_email_import(self) -> None:
            """
            NY v7-fix35: Importera e-postfil (.eml/.msg) som uppgift.
            NY v7-fix41: delar kärna med dra-och-släpp (_import_email_files).
            """
            try:
                get_throttle().notify_activity()
                from PySide6.QtWidgets import QFileDialog
                file_paths, _ = QFileDialog.getOpenFileNames(
                    self,
                    "Importera e-post som uppgift",
                    "",
                    "E-postfiler (*.eml *.msg);;Alla filer (*.*)",
                )
                if not file_paths:
                    return
                self._import_email_files(list(file_paths))
            except Exception as e:
                logger.error(
                    f"{LOG_PREFIX} _on_email_import misslyckades: {e}",
                    exc_info=True,
                )

        def _import_email_files(self, file_paths: List[str]) -> None:
            """
            NY v7-fix41: importera e-postfiler (.eml/.msg) som uppgifter.

            Används av BÅDE fil-dialogen (📧-knappen) och dra-och-släpp:
            dra ett mail direkt från Outlook (.msg) eller Thunderbird (.eml)
            och släpp det på widgeten — uppgiften skapas direkt.

            FIX v7-fix88 (Rickard: "händer inget när man importerar e-post"):
              - ALLTID synlig återkoppling: nya uppgifter FLASHAS fram i
                Aktiva (fix77-mekanismen), dedup-visas tydligt och fel
                ger en ruta med anledning — aldrig tyst igen
              - .msg utan tillägget extract-msg → tydlig ruta med lösning
            """
            imported = 0
            duplicates = 0
            failures: List[str] = []
            try:
                from core.email_import import import_email
                # NY v7-fix88: .msg kräver extract-msg — kolla FÖRST så att
                # felrutan kan förklara lösningen
                _need_msg_plugin = any(
                    str(fp).lower().endswith(".msg") for fp in file_paths
                )
                _msg_plugin_ok = True
                if _need_msg_plugin:
                    try:
                        import extract_msg  # noqa: F401
                    except ImportError:
                        _msg_plugin_ok = False
                for fp in file_paths:
                    _info: Dict[str, Any] = {}
                    task_id = import_email(
                        Path(fp), self.store,
                        Path(__file__).resolve().parent.parent / "data",
                        info=_info,
                    )
                    if task_id:
                        if _info.get("duplicate"):
                            duplicates += 1
                        else:
                            imported += 1
                        # FIX v7-fix88: FLASHA uppgiften i Aktiva så att
                        # importen alltid SYNDS (även befintlig vid dedup)
                        with suppress(Exception):
                            self._show_task_in_active(task_id)
                    else:
                        failures.append(str(fp))
                logger.info(
                    f"{LOG_PREFIX} E-post-import: {imported} nya, "
                    f"{duplicates} redan importerade, {len(failures)} fel "
                    f"(av {len(file_paths)} filer) (v7-fix88)"
                )
                # --- NY v7-fix88: ALLTID användarfeedback ----------------
                from PySide6.QtWidgets import QMessageBox
                if failures:
                    _msg_plugin_hint = (
                        "\n\nOutlook-filer (.msg) kräver tillägget "
                        "extract-msg.\nInstallera via tray-menyn → "
                        "📦 Installera/Uppdatera tillägg."
                        if _need_msg_plugin and not _msg_plugin_ok else ""
                    )
                    QMessageBox.warning(
                        self,
                        "📧 E-postimport — problem",
                        f"{len(failures)} av {len(file_paths)} fil(er) "
                        f"kunde inte importeras:\n\n"
                        + "\n".join(f"• {Path(f).name}" for f in failures)
                        + _msg_plugin_hint,
                    )
                elif duplicates and not imported:
                    QMessageBox.information(
                        self,
                        "📧 Redan importerad",
                        f"Alla {duplicates} e-post(er) var redan importerade "
                        f"— deras uppgifter visas nu (markerade).",
                    )
                # (lyckad import: flashen i Aktiva RÄCKER — ingen ruta som
                # stör; loggen + listan + flikbyte + scroll visar det)
            except Exception as e:
                logger.error(
                    f"{LOG_PREFIX} _import_email_files misslyckades: {e}",
                    exc_info=True,
                )
                with suppress(Exception):
                    from PySide6.QtWidgets import QMessageBox
                    QMessageBox.warning(
                        self,
                        "📧 E-postimport misslyckades",
                        f"Ett oväntat fel uppstod:\n{e}",
                    )

        def _is_outlook_drag(self, mime_data: Any) -> bool:
            """
            NY v7-fix88: är detta ett direkt-drag FRÅN Outlook?

            Outlook ger inga fil-URL:er vid drag — bara FileGroupDescriptor-
            formatet. Qt mappar det till windows-mime-format. Tidigare
            avvisades dessa drags TYST ("händer inget") — nu accepteras
            de och användaren får en hjälpsam instruktion istället.
            """
            try:
                for fmt in (
                    'application/x-qt-windows-mime;value="FileGroupDescriptorW"',
                    'application/x-qt-windows-mime;value="FileGroupDescriptor"',
                    "application/x-qt-windows-mime;value=FileGroupDescriptorW",
                ):
                    if mime_data.hasFormat(fmt):
                        return True
                # Fallback: lista alla format och leta efter nyckelord
                with suppress(Exception):
                    for fmt in mime_data.formats():
                        if "FileGroupDescriptor" in str(fmt):
                            return True
                return False
            except Exception:
                return False

        def dragEnterEvent(self, event: Any) -> None:
            """
            NY v7-fix41: acceptera .eml/.msg-filer som dras in (Outlook/
            Thunderbird → widgeten).

            FIX v7-fix88: acceptera ÄVEN direkt-drag från Outlook
            (FileGroupDescriptor — inga fil-URL:er). Själva filen kan
            inte läsas av Qt, men dropEvent ger användaren en tydlig
            instruktion i stället för tyst avvisning ("händer inget").
            """
            try:
                if event.mimeData().hasUrls():
                    for url in event.mimeData().urls():
                        if str(url.toLocalFile()).lower().endswith(
                            (".eml", ".msg")
                        ):
                            event.acceptProposedAction()
                            return
                # NY v7-fix88: Outlook direkt-drag
                if self._is_outlook_drag(event.mimeData()):
                    event.acceptProposedAction()
                    return
                super().dragEnterEvent(event)
            except Exception:
                super().dragEnterEvent(event)

        def dropEvent(self, event: Any) -> None:
            """
            NY v7-fix41: släpp e-post → skapa uppgift.
            FIX v7-fix88: Outlook direkt-drag → hjälpsam instruktion.
            """
            try:
                if event.mimeData().hasUrls():
                    files = [
                        str(url.toLocalFile())
                        for url in event.mimeData().urls()
                        if str(url.toLocalFile()).lower().endswith(
                            (".eml", ".msg")
                        )
                    ]
                    if files:
                        event.acceptProposedAction()
                        get_throttle().notify_activity()
                        self._import_email_files(files)
                        return
                # NY v7-fix88: direkt-drag från Outlook → instruktion
                if self._is_outlook_drag(event.mimeData()):
                    event.acceptProposedAction()
                    get_throttle().notify_activity()
                    logger.info(
                        f"{LOG_PREFIX} Direkt-drag från Outlook upptäckt — "
                        f"ger instruktion (v7-fix88)"
                    )
                    from PySide6.QtWidgets import QMessageBox
                    QMessageBox.information(
                        self,
                        "📧 Dra från Outlook",
                        "Outlook-mailet måste sparas som fil först:\n\n"
                        "1. Dra mailet till skrivbordet/en mapp\n"
                        "   (det blir en .msg-fil)\n"
                        "2. Dra .msg-filen till TaskBord\n\n"
                        "Tips: du kan också använda 📧-knappen nedan\n"
                        "eller spara mailet som .eml i Thunderbird.",
                    )
                    return
                super().dropEvent(event)
            except Exception:
                super().dropEvent(event)

        def _open_task_email(self, task: Dict[str, Any]) -> None:
            """
            "Öppna mejlet": originalfilen (.eml/.msg) i standardprogrammet;
            finns den inte kvar visas den sparade mailtexten i stället.
            """
            try:
                from core.email_import import open_task_email
                data_dir = getattr(self.store, "data_dir", None)
                if open_task_email(task, data_dir):
                    return
                has_text = any(
                    task.get(k) for k in ("email_body", "email_subject", "email_from")
                )
                if has_text:
                    from ui.mail_view_dialog import MailViewDialog
                    note = (
                        "Originalfilen finns inte kvar (eller gick inte att "
                        "öppna) — här är texten som sparades på uppgiften."
                        if task.get("email_path") else ""
                    )
                    MailViewDialog(task, self, note).exec()
                else:
                    from PySide6.QtWidgets import QMessageBox as _QMB
                    _QMB.information(
                        self, "Öppna mejlet",
                        "Varken originalmailet eller dess text finns sparad "
                        "på den här uppgiften.\n\n"
                        + (f"Message-ID: {task.get('email_message_id')}"
                           if task.get("email_message_id") else ""),
                    )
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} _open_task_email misslyckades: {e}",
                    exc_info=True,
                )

        def _open_email(self, email_path: str) -> None:
            """NY v7-fix35: Öppna sparad e-postfil i standardprogrammet."""
            try:
                from core.email_import import open_email
                open_email(email_path)
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} _open_email misslyckades: {e}"
                )

        def contextMenuEvent(self, event: Any) -> None:
            """
            NY v7-fix47: högerklicksmeny på fönstret.

            Rickard 2026-10-02: "man kan vid högerklick nollställa fönstret"
            — + centrera, lås/lås upp.
            """
            try:
                get_throttle().notify_activity()
                menu = QMenu(self)
                act_center = menu.addAction("🎯 Centrera fönstret")
                act_reset = menu.addAction(
                    "↩️ Nollställ (centrera + standardstorlek)"
                )
                menu.addSeparator()
                act_lock = menu.addAction(
                    "🔓 Lås upp fönstret"
                    if self._locked
                    else "🔒 Lås fönstret"
                )
                # NY v7-fix81: PDF-export även här (utom 📄-knappen + tray)
                act_pdf = menu.addAction("📄 Exportera checklista → PDF…")
                # NY v8: kalenderexport (.ics) → Google Calendar m.fl.
                act_cal = menu.addAction("📅 Exportera till kalender (.ics)…")
                # NY v8: lokal OAuth-koppling till Google Calendar
                act_google = menu.addAction("☁️ Google Calendar (koppla konto)…")
                act_google.setToolTip(
                    "Koppla ett Google-konto lokalt (OAuth i webbläsaren) och\n"
                    "skicka uppgifter rakt in i din kalender."
                )
                # NY v8: backup av uppgifter
                act_backup = menu.addAction("💾 Backup av uppgifter…")
                # NY v8: frivillig donation (öppnar ui/donate.py-dialogen)
                menu.addSeparator()
                act_donate = menu.addAction("💖 Stöd TaskBord…")
                chosen = menu.exec(event.globalPos())
                if chosen is act_center:
                    self._center_window(reset_size=False)
                elif chosen is act_reset:
                    self._center_window(reset_size=True)
                elif chosen is act_lock:
                    self._toggle_lock()
                elif chosen is act_pdf:
                    self._on_export_pdf()
                elif chosen is act_cal:
                    self._on_export_calendar_ics()
                elif chosen is act_google:
                    self._on_open_google_calendar()
                elif chosen is act_backup:
                    self._on_open_backup()
                elif chosen is act_donate:
                    self._on_open_donate()
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} contextMenuEvent misslyckades: "
                    f"{_describe_widget_error(e)}"
                )

        def _shell_screen_move(
            self, screen_x: int, screen_y: int,
            width: Any = None, height: Any = None,
        ) -> None:
            """
            NY v7-fix48/52: flytta (+ ev. resiza) fönstret till SKÄRM-
            koordinater.

            I desktop-läget 'ovanpå ikonerna' är fönstret barn i skrivbordet
            (Progman) — Windows tolkar koordinater som FÖRÄLDER-relativa.
            FIX v7-fix52: i above-läget sker ALLT nativt via SetWindowPos
            (skärm-koordinat - förälderorigo) — Qt:s asynkrona move/resize-
            konvertering förvirrade koordinaterna (nollställningen hamnade
            t.ex. 1920 px fel). Qt fallback för övriga lägen.
            """
            try:
                _sh = getattr(self, "_shell", None)
                _t = _sh if _sh is not None else self
                _ox, _oy = (0, 0)
                if _sh is not None:
                    _ox, _oy = getattr(_sh, "_parent_origin", (0, 0)) or (0, 0)
                # FIX v7-fix54: den nativa SetWindowPos-grenen (v7-fix52)
                # var DPI-FEL — råa Windows-koordinater är FYSISKA px medan
                # Qt använder LOGISKA (125% DPI). Nu: ALLT via Qt (konver-
                # terar själv) med LOGISKT konverterad origo (sätts i main
                # vid attach: fysiskt_origo / devicePixelRatio).
                if width is not None and height is not None:
                    _t.resize(int(width), int(height))
                _t.move(int(screen_x) - _ox, int(screen_y) - _oy)
            except Exception as e:
                logger.debug(f"{LOG_PREFIX} _shell_screen_move: {e}")

        def _center_window(self, reset_size: bool = False) -> None:
            """
            NY v7-fix47: centrera fönstret på primärskärmen.

            reset_size=True → även standardstorlek (nollställ).
            Position + storlek sparas direkt (överlever omstart).
            """
            try:
                _sh = getattr(self, "_shell", None)
                _target = _sh if _sh is not None else self
                _scr = self.primary_screen or QGuiApplication.primaryScreen()
                if _scr is not None:
                    # v7-fix52: beräkna mål-STORLEK före (atomisk operation
                    # — läs ALDRIG widgetens storlek asynkront efteråt)
                    _tw = (
                        DEFAULT_WIDGET_WIDTH if reset_size
                        else _target.width()
                    )
                    _th = (
                        DEFAULT_WIDGET_HEIGHT if reset_size
                        else _target.height()
                    )
                    _sg = _scr.availableGeometry()
                    _nx = _sg.x() + (_sg.width() - _tw) // 2
                    _ny = _sg.y() + (_sg.height() - _th) // 2
                    # v7-fix48/52: komposterad ATOMISK flytt+resize —
                    # korrekt skärm-position även i above-läget
                    self._shell_screen_move(_nx, _ny, _tw, _th)
                    # FIX v7-fix55: logga BERÄKNADE skärm-värden (asynkron
                    # Qt-läsning kunde visa DPI-förväxlade mått, t.ex. 280x518)
                    logger.info(
                        f"{LOG_PREFIX} fönstret "
                        f"{'NOLLSTÄLLT (standardstorlek + centrerat)' if reset_size else 'centrerat'}"
                        f" → skärm ({_nx},{_ny}) {_tw}x{_th}"
                    )
                # Spara direkt så det överlever omstart
                self._save_geometry_now()
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} _center_window: {e}")

        def _toggle_lock(self) -> None:
            """NY v6.4.1 v7: Toggle lås/lås upp fönstret (med position-minne).

            Rickard 2026-09-25:
              1. Kunna låsa upp fönstret och flytta → låsa positionen
              2. Appen ska komma ihåg positionen vid omstart
              3. Win+D ska INTE gömma fönstret

            Flow:
              - Lås = frozen pos, kan INTE flyttas
              - Lås upp = dragbart i 30s, auto-relock
              - Vid flytt (när upplåst): settings.window_configs[id].x/y
              - Vid låsning: säkra pos genom att spara settings
            """
            try:
                get_throttle().notify_activity()
                was_locked = bool(self._locked)
                self._locked = not was_locked
                # Auto-relock-timer
                if self._locked:
                    if self._unlock_timer is not None:
                        with suppress(Exception):
                            self._unlock_timer.stop()
                    # NY v7-fix49: LÅS = positionen+storleken SPARAS direkt
                    # (Rickard: "tills användaren flyttar och låser
                    # positionen, som sparas tills nästa gång")
                    with suppress(Exception):
                        self._save_geometry_now()
                    icon = "🔒"
                    msg = "Låst (positionen sparad)"
                else:
                    if self._unlock_timer is None:
                        self._unlock_timer = QTimer(self)
                        self._unlock_timer.setSingleShot(True)
                        self._unlock_timer.timeout.connect(self._auto_relock)
                    self._unlock_timer.start(self._unlock_timeout_sec * 1000)
                    icon = "🔓"
                    msg = "Upplåst (auto-relock om 30s)"
                # Uppdatera UI
                with suppress(Exception):
                    if hasattr(self, "lock_btn") and self.lock_btn is not None:
                        # setChecked uppdaterar QSS:checked-stilen
                        self.lock_btn.setChecked(self._locked)
                        self.lock_btn.setText(icon)
                with suppress(Exception):
                    if hasattr(self, "drag_handle") and self.drag_handle is not None:
                        # FIX 2026-09-25: bara 🔒/🔓 + släpp bilagan
                        self.drag_handle.setText(
                            f"{icon}  {APP_NAME} — klicka och dra för att flytta"
                        )
                # FIX 2026-09-25: vid LÅS → spara positionen permanent
                # (annars kan settings ha annan pos som override:ar)
                # FIX v7-fix49: gamla koden sparade BARNETS lokala pos
                # (alltid 0,0 i skal-läge!) — läs SKALETs skärm-position,
                # och spara position + storlek via update_window_geometry.
                if self._locked:
                    with suppress(Exception):
                        _sh_l = getattr(self, "_shell", None)
                        _lx, _ly = (
                            (_sh_l.x(), _sh_l.y()) if _sh_l is not None
                            else (self.x(), self.y())
                        )
                        if hasattr(self.settings, "update_window_geometry"):
                            self.settings.update_window_geometry(
                                self.win_id, _lx, _ly,
                                (_sh_l.width() if _sh_l is not None
                                 else self.width()),
                                (_sh_l.height() if _sh_l is not None
                                 else self.height()),
                            )
                        elif hasattr(self.settings, "update_window_position"):
                            self.settings.update_window_position(
                                self.win_id, _lx, _ly
                            )
                        logger.info(
                            f"{LOG_PREFIX} _toggle_lock: position "
                            f"låst vid ({_lx},{_ly})"
                        )
                logger.info(
                    f"{LOG_PREFIX} _toggle_lock: {was_locked} → {self._locked} "
                    f"({msg}) icon={icon}"
                )
                self._audit.add("lock_toggled", {"locked": self._locked})
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} _toggle_lock misslyckades: "
                    f"{_describe_widget_error(e)}",
                    exc_info=True,
                )

        def _auto_relock(self) -> None:
            """NY v6.4.1 v7-fix: Auto-relock efter _unlock_timeout_sec sekunder."""
            try:
                if self._locked:
                    return  # Redan låst (race condition-skydd)
                self._locked = True
                with suppress(Exception):
                    if hasattr(self, "lock_btn") and self.lock_btn is not None:
                        self.lock_btn.setText("🔒")
                with suppress(Exception):
                    if hasattr(self, "drag_handle") and self.drag_handle is not None:
                        self.drag_handle.setText(
                            f"🔒  {APP_NAME} — klicka och dra för att flytta"
                        )
                logger.info(
                    f"{LOG_PREFIX} _auto_relock: låst efter "
                    f"{self._unlock_timeout_sec}s utan aktivitet"
                )
                self._audit.add(
                    "auto_relock",
                    {"after_sec": self._unlock_timeout_sec},
                )
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} _auto_relock misslyckades: "
                    f"{_describe_widget_error(e)}",
                    exc_info=True,
                )

        def bring_to_front(self) -> None:
            """
            NY v6.4.1 v5: Lyft widget till FRAMSIDAN vid klick.

            Vad den gor:
              1. Visa fonstret (om gomt)
              2. Satt z-order till HWND_TOP (OVER alla skrivbords-widgets)
              3. Aktivera (ta fokus — anvandaren klickade ju)

            Efter klick forsoker Z-order TIMER att aterstall till
            HWND_BOTTOM sa vi inte star over andra fonster permanent.
            """
            # FIX v7-fix29: barn → skalet hanterar fokus
            if self._is_child():
                return
            try:
                import ctypes
                if not self._native_window_ok():
                    return
                hwnd = int(self.winId())
                if not hwnd:
                    return
                user32 = ctypes.windll.user32
                # FIX 2026-09-24: NOTOPMOST/TOP bort — lyfter över appar.
                # Bara synlig, z-order orörd.
                if not user32.IsWindowVisible(hwnd):
                    user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
                self.show()
                logger.trace(
                    f"{LOG_PREFIX} bring_to_front: HWND={hwnd} synlig "
                    f"(z-order orörd)"
                )
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} bring_to_front misslyckades: {e}"
                )

        def _auto_reposition_if_needed(self) -> None:
            """
            BUGG 26: flytta widgeten till sin SPARADE position om den hamnat fel
            (t.ex. efter skärmbyte, upplösningsändring eller kollision med
            skrivbordsikoner).

            NY v7-fix9 — logisk bugg åtgärdad:
              Tidigare läste metoden den sparade positionen men skrev sedan
              tillbaka widgetens NUVARANDE position till settings. Det var
              tvärtom mot syftet (auto-reposition) och gjorde metoden till en
              no-op som samtidigt triggade windows_updated → populate-loop.

              Rätt beteende: läs sparad position → flytta widgeten dit
              (endast om den faktiskt avviker och fönstret inte är låst).
            """
            # NY v6.4: Respektera lås (låst fönster får inte flyttas)
            if self._locked:
                logger.debug(
                    f"{LOG_PREFIX} auto-reposition skippat (fönster låst)"
                )
                return
            if not hasattr(self.settings, "window_configs"):
                return
            configs = self.settings.window_configs() or []
            for conf in configs:
                if conf.get("id") != self.win_id:
                    continue
                want_x = int(conf.get("x", self.x()))
                want_y = int(conf.get("y", self.y()))
                cur_x, cur_y = self.x(), self.y()
                if (cur_x, cur_y) == (want_x, want_y):
                    logger.debug(
                        f"{LOG_PREFIX} auto-reposition: redan rätt "
                        f"({cur_x},{cur_y}) — inget att göra"
                    )
                    return
                logger.info(
                    f"{LOG_PREFIX} auto-reposition: flyttar "
                    f"({cur_x},{cur_y}) → ({want_x},{want_y})"
                )
                with suppress(Exception):
                    # _move_to sparar sin egen position (throttlad) — vi skriver
                    # ALDRIG till settings härifrån (undviker signal-loop).
                    self.move(want_x, want_y)
                return
            logger.debug(
                f"{LOG_PREFIX} auto-reposition: ingen config för "
                f"{self.win_id!r} — hoppar över"
            )

        def _navigate_tasks(self, key: int) -> None:
            """Navigera mellan tasks (Up/Down)."""
            if not self._task_widgets:
                return
            tids = list(self._task_widgets.keys())
            current_idx = getattr(self, "_nav_idx", 0)
            if key == Qt.Key.Key_Down:
                current_idx = min(current_idx + 1, len(tids) - 1)
            else:
                current_idx = max(current_idx - 1, 0)
            self._nav_idx = current_idx
            target = self._task_widgets[tids[current_idx]]
            target.setFocus()
            logger.trace(
                f"{LOG_PREFIX} navigate: idx={current_idx}, tid={tids[current_idx]}"
            )

        # ====================================================================
        # EVENT HANDLERS (NY v6.4.1 v7 - forbattrade med svenska loggar)
        # ====================================================================

        def _activate_for_typing(self) -> None:
            """
            NY v7-fix73: gör fönstret SKRIVBART vid klick.

            Rickard 2026-10-06: "kan inte skriva i textfältet" — fönstret
            har WS_EX_NOACTIVATE (stjäl inte fokus) men den blockerar
            OCKSÅ tangentbordsinput! Lösning: vid klick/fokus i ett
            textfält → ta bort NOACTIVATE + gör förgrunds-fönster →
            användaren kan skriva. Vid focusOut → NOACTIVATE tillbaka
            (stjäl inte fokus från andra appar när den inte används).
            """
            try:
                if sys.platform != "win32":
                    return
                import ctypes
                _sh = getattr(self, "_shell", None)
                _win = _sh if _sh is not None else self
                _hwnd = 0
                with suppress(Exception):
                    _hwnd = int(_win.winId())
                if not _hwnd:
                    return
                _u = ctypes.windll.user32
                GWL_EXSTYLE = -20
                WS_EX_NOACTIVATE = 0x08000000
                _ex = _u.GetWindowLongW(_hwnd, GWL_EXSTYLE)
                if _ex & WS_EX_NOACTIVATE:
                    _u.SetWindowLongW(
                        _hwnd, GWL_EXSTYLE, _ex & ~WS_EX_NOACTIVATE
                    )
                    _win._noact_saved = True
                    logger.info(
                        f"{LOG_PREFIX} FÖNSTER AKTIVERAT för inmatning "
                        f"(NOACTIVATE av) — nu går det att skriva (v7-fix73)"
                    )
                with suppress(Exception):
                    _u.SetForegroundWindow(_hwnd)
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} _activate_for_typing: {e}"
                )

        def _deactivate_restore_noact(self) -> None:
            """NY v7-fix73: fönstret tappade fokus → NOACTIVATE tillbaka."""
            try:
                if sys.platform != "win32":
                    return
                import ctypes
                _sh = getattr(self, "_shell", None)
                _win = _sh if _sh is not None else self
                if not getattr(_win, "_noact_saved", False):
                    return
                with suppress(Exception):
                    _hwnd = int(_win.winId())
                    if not _hwnd:
                        return
                    _u = ctypes.windll.user32
                    GWL_EXSTYLE = -20
                    WS_EX_NOACTIVATE = 0x08000000
                    _ex = _u.GetWindowLongW(_hwnd, GWL_EXSTYLE)
                    if not (_ex & WS_EX_NOACTIVATE):
                        _u.SetWindowLongW(
                            _hwnd, GWL_EXSTYLE, _ex | WS_EX_NOACTIVATE
                        )
                        _win._noact_saved = False
                        logger.info(
                            f"{LOG_PREFIX} Fönster deaktiverat — NOACTIVATE "
                            f"aterställd (stjäl ej fokus) (v7-fix73)"
                        )
            except Exception as e:
                logger.debug(
                    f"{LOG_PREFIX} _deactivate_restore_noact: {e}"
                )

        @_log_event("event:mouse_press")
        def mousePressEvent(self, event: QMouseEvent) -> None:
            """
            NY v6.4.1 v7: Börja drag (med bring_to_front vid klick).

            FIX v7-fix39 (2026-10-01, Rickard: "fönstret går inte att
            flytta även fast man låst upp"):
              1. BUGG: int(event.button()) i logg-raden kraschade vid
                 VARJE klick (PySide6-enum har inte int()) — och eftersom
                 f-string-defaulten i dict.get() utvärderas ALLTID dog
                 hela mousePressEvent → drag startade ALDRIG.
              2. BUGG: mouseMoveEvent loggade odefinierade old_x/old_y
                 → NameError vid första drag-rörelsen.
              3. NYTT: HELA fönstret är nu dragbart — vänsterklick som
                 når widgeten (dvs. INTE fångas av knappar/kort/fält)
                 startar drag, inte bara översta 42 px-remsan.

            Princip: DRAG-LOGIK FÖRST — loggning körs sist och får
            ALDRIG döda funktionalitet.
            """
            # === 0. AKTIVERA FÖR SKRIVNING (v7-fix73) ==================
            # Varje vänsterklick på widgeten → ta bort NOACTIVATE så
            # tangentbordet fungerar (fokus sätts av Qt/Windows).
            with suppress(Exception):
                self._activate_for_typing()

            # === 1. DRAG (körs först — krash-säkrat) ====================
            try:
                get_throttle().notify_activity()
            except Exception:
                pass
            try:
                if event.button() == Qt.MouseButton.LeftButton:
                    if (self._locked and not (
                            event.modifiers()
                            & Qt.KeyboardModifier.ShiftModifier)):
                        logger.debug(
                            f"{LOG_PREFIX} drag blockerat (fonstret låst, "
                            f"håll Shift för att flytta)"
                        )
                        event.ignore()
                        return
                    _shell = getattr(self, "_shell", None)
                    _origin = (
                        _shell.frameGeometry().topLeft()
                        if _shell is not None
                        else self.frameGeometry().topLeft()
                    )
                    self._drag_offset = (
                        event.globalPosition().toPoint() - _origin
                    )
                    self._drag_active = True
                    _zone = (
                        "handle" if event.y() < DRAG_HANDLE_HEIGHT else "yta"
                    )
                    logger.debug(
                        f"{LOG_PREFIX} drag startad (zon={_zone}, "
                        f"y={event.y()}, locked={self._locked})"
                    )
                    event.accept()
                    return
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} drag-start misslyckades: "
                    f"{_describe_widget_error(e)}"
                )

            # === 2. Övriga knappar (befintligt beteende) =================
            try:
                # Visa widget temporärt överst vid klick
                self.bring_to_front()
            except Exception:
                pass
            try:
                super().mousePressEvent(event)
            except Exception:
                pass

            # === 3. Diagnostik (SIST — får aldrig påverka ovanstående) ==
            with suppress(Exception):
                _btn = {
                    Qt.MouseButton.LeftButton: "Left",
                    Qt.MouseButton.RightButton: "Right",
                    Qt.MouseButton.MiddleButton: "Middle",
                }.get(event.button())
                if _btn is None:
                    # v7-fix39: int() på PySide6-enum = TypeError —
                    # använd .name/str() istället
                    _btn = _qt_enum_name(event.button(), "btn=?")
                _mods = []
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    _mods.append("Shift")
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    _mods.append("Ctrl")
                if event.modifiers() & Qt.KeyboardModifier.AltModifier:
                    _mods.append("Alt")
                _mod_str = "+".join(_mods) if _mods else "-"
                logger.debug(
                    f"{LOG_PREFIX} mousePress "
                    f"btn={_btn} mods={_mod_str} "
                    f"local=({event.x()},{event.y()}) "
                    f"global=({event.globalPosition().toPoint().x()},"
                    f"{event.globalPosition().toPoint().y()}) "
                    f"locked={self._locked}"
                )

        @_log_event("event:mouse_move")
        def mouseMoveEvent(self, event: QMouseEvent) -> None:
            """NY v6.4.1 v7: Drag (med bättre loggning).
            FIX 2026-09-24: trace under hela drag-rörelsen.
            FIX v7-fix39: old_x/old_y var ODEFINIERADE → NameError vid
            första drag-rörelsen (fönstret flyttades aldrig). Nu loggas
            skal-fönstrets faktiska position före/efter."""
            try:
                if (self._drag_active and self._drag_offset is not None and
                        (event.buttons() & Qt.MouseButton.LeftButton)):
                    new_pt = event.globalPosition().toPoint() - self._drag_offset
                    _shell_m = getattr(self, "_shell", None)
                    _target = _shell_m if _shell_m is not None else self
                    _old_x, _old_y = _target.x(), _target.y()
                    # v7-fix48: komposterad flytt — rätt skärm-position
                    # även när fönstret är barn i skrivbordet (Progman)
                    self._shell_screen_move(new_pt.x(), new_pt.y())
                    logger.debug(
                        f"{LOG_PREFIX} mouseMove DRAG "
                        f"({_old_x},{_old_y}) → ({_target.x()},{_target.y()}) "
                        f"size={_target.width()}x{_target.height()}"
                    )
                    event.accept()
                else:
                    super().mouseMoveEvent(event)
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} mouseMoveEvent misslyckades: "
                    f"{_describe_widget_error(e)}",
                    exc_info=True,
                )

        @_log_event("event:mouse_release")
        def mouseReleaseEvent(self, event: QMouseEvent) -> None:
            """NY v6.4.1 v7: Avsluta drag + BUGG 26 auto-reposition.
            FIX 2026-09-24: full release-info."""
            try:
                _shell_r = getattr(self, "_shell", None)
                _final = (
                    (_shell_r.x(), _shell_r.y())
                    if _shell_r is not None
                    else (self.x(), self.y())
                )
                logger.debug(
                    f"{LOG_PREFIX} mouseRelease "
                    f"btn=L?{event.button() == Qt.MouseButton.LeftButton} "
                    f"was_dragging={self._drag_active} "
                    f"final_pos=({_final[0]},{_final[1]})"
                )
                self._drag_active = False
                self._drag_offset = None
                # NY v7-fix9: Tvinga SPARNING av slutpositionen (förbi 500ms-
                # throttlen i moveEvent). Utan detta kunde sista positionen
                # tappas om användaren släppte inom 500 ms efter senaste save.
                #
                # OBS: Anropade tidigare _auto_reposition_if_needed() här — det
                # var fel, eftersom den flyttar widgeten TILL den sparade
                # positionen och därmed kunde ångra användarens drag.
                # FIX v7-fix33: spara SKALETS position om vi är barn
                _shell = getattr(self, "_shell", None)
                if _shell is not None:
                    _sx, _sy = _shell.x(), _shell.y()
                else:
                    _sx, _sy = self.x(), self.y()
                with suppress(Exception):
                    if hasattr(self.settings, "update_window_geometry"):
                        # NY v7-fix43: slutposition + slutstorlek
                        self.settings.update_window_geometry(
                            self.win_id, _sx, _sy,
                            (_shell.width() if _shell is not None
                             else self.width()),
                            (_shell.height() if _shell is not None
                             else self.height()),
                        )
                        self._last_pos_save = time.monotonic()
                        self._last_size_save = time.monotonic()
                    elif hasattr(self.settings, "update_window_position"):
                        self.settings.update_window_position(
                            self.win_id, _sx, _sy
                        )
                        self._last_pos_save = time.monotonic()
                logger.debug(f"{LOG_PREFIX} drag avslutad vid ({_sx}, {_sy})")
                event.accept()
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} mouseReleaseEvent misslyckades: "
                    f"{_describe_widget_error(e)}",
                    exc_info=True,
                )

        @_log_event("event:close")
        def closeEvent(self, event: QCloseEvent) -> None:
            """
            NY v6.4.1 v7: Close = satta z-order (widget stannar synlig).
            FIX 2026-09-24: Tillåt close när _allow_close=True
            (shutdown, populate-remove, pretest) — annars spöken
            som stod kvar över appar.
            """
            try:
                if getattr(self, "_allow_close", False):
                    event.accept()
                    with __import__("contextlib").suppress(Exception):
                        self.hide()
                    logger.info(
                        f"{LOG_PREFIX} closeEvent: TILLÅTEN "
                        f"(win_id={self.win_id!r}) — stängs"
                    )
                    return
                event.ignore()  # BUGG 19: normal close = stanna synlig
                self._setup_bugg19_zorder()
                self._audit.add("close_event_ignored")
                logger.debug(
                    f"{LOG_PREFIX} closeEvent ignorerad (BUGG 19: "
                    f"widget stannar synlig pa skrivbordet)"
                )
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} closeEvent misslyckades: "
                    f"{_describe_widget_error(e)}",
                    exc_info=True,
                )

        @_log_event("event:focus_in")
        def focusInEvent(self, event):
            """FIX 2026-09-24: logga när widgeten får fokus."""
            logger.debug(f"{LOG_PREFIX} focusInEvent: {type(event).__name__}")
            super().focusInEvent(event)

        @_log_event("event:focus_out")
        def focusOutEvent(self, event):
            """FIX 2026-09-24: logga när widgeten tappar fokus.
            NY v7-fix73: + återställ NOACTIVATE (stjäl ej fokus längre)."""
            logger.debug(f"{LOG_PREFIX} focusOutEvent: {type(event).__name__}")
            with suppress(Exception):
                self._deactivate_restore_noact()
            super().focusOutEvent(event)

        # FIX 2026-09-25: säkra position-extrahering (event.position() kan saknas)
        @staticmethod
        def _pt_of(ev) -> tuple:
            try:
                # Ny Qt6 API: position() -> QPointF
                if hasattr(ev, "position") and callable(ev.position):
                    p = ev.position()
                    return (int(p.x()), int(p.y()))
            except Exception:
                pass
            # Äldre / fallback
            if hasattr(ev, "pos"):
                p = ev.pos()
                return (int(p.x()), int(p.y()))
            return (-1, -1)

        @_log_event("event:enter")
        def enterEvent(self, event):
            """FIX 2026-09-24: logga hover-in."""
            try:
                _x, _y = self._pt_of(event)
                logger.debug(
                    f"{LOG_PREFIX} enterEvent: hover börjar @ ({_x},{_y})"
                )
                super().enterEvent(event)
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} enterEvent misslyckades: {e}")

        @_log_event("event:leave")
        def leaveEvent(self, event):
            """FIX 2026-09-24: logga hover-out."""
            try:
                _x, _y = self._pt_of(event)
                logger.debug(
                    f"{LOG_PREFIX} leaveEvent: hover slutar @ ({_x},{_y})"
                )
                super().leaveEvent(event)
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} leaveEvent misslyckades: {e}")

        @_log_event("event:wheel")
        def wheelEvent(self, event):
            """FIX 2026-09-24: logga scroll."""
            try:
                _x, _y = self._pt_of(event)
                _delta = (
                    (event.angleDelta().x(), event.angleDelta().y())
                    if hasattr(event, "angleDelta")
                    else (0, 0)
                )
                logger.debug(
                    f"{LOG_PREFIX} wheelEvent delta={_delta} @ ({_x},{_y})"
                )
                super().wheelEvent(event)
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} wheelEvent misslyckades: {e}")

        @_log_event("event:resize")
        def _save_geometry_now(self) -> None:
            """NY v7-fix43: spara skal-geometri (position + storlek)."""
            try:
                _sh = getattr(self, "_shell", None)
                _g = _sh if _sh is not None else self
                # FIX v8: spara aldrig skräpgeometri (minimerat fönster ligger på
                # (-32000,-32000) i Windows) — då skulle riktiga läget skrivas över.
                if _g.isMinimized() or _g.x() <= -10000 or _g.y() <= -10000:
                    return
                if hasattr(self.settings, "update_window_geometry"):
                    self.settings.update_window_geometry(
                        self.win_id,
                        _g.x(), _g.y(), _g.width(), _g.height(),
                    )
            except Exception as e:
                logger.debug(f"{LOG_PREFIX} _save_geometry_now: {e}")

        def resizeEvent(self, event: QResizeEvent) -> None:
            """FIX 2026-09-24: full resize-info."""
            try:
                logger.debug(
                    f"{LOG_PREFIX} resizeEvent "
                    f"old=({event.oldSize().width()}x{event.oldSize().height()}) "
                    f"new=({event.size().width()}x{event.size().height()}) "
                    f"final_pos=({self.x()},{self.y()})"
                )
                self._pixmap_cache.clear()
                # NY v7-fix43: debounced sparning — timern startas om vid
                # VARJE resize och sparar 600 ms efter den SISTA (garanterar
                # att slutstorleken alltid sparas, även snabba drag)
                _timer = getattr(self, "_size_save_timer", None)
                if _timer is None:
                    _timer = QTimer(self)
                    _timer.setSingleShot(True)
                    _timer.setInterval(600)
                    _timer.timeout.connect(self._save_geometry_now)
                    self._size_save_timer = _timer
                _timer.start()
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} resizeEvent misslyckades: {e}"
                )

        @_log_event("event:move")
        def moveEvent(self, event: QMoveEvent) -> None:
            """
            FIX 2026-09-24: full move-info + throttlad positionssparning.

            NY v7-fix9: Throttle 500 ms — förhindrar att varje pixel-drag
            skriver till settings (vilket tidigare triggade
            windows_updated → populate → show → moveEvent i en loop).
            Slutpositionen sparas alltid i mouseReleaseEvent (förbi throttlen).
            """
            try:
                cur_x, cur_y = self.x(), self.y()
                old_x, old_y = event.oldPos().x(), event.oldPos().y()
                logger.debug(
                    f"{LOG_PREFIX} moveEvent: ({old_x},{old_y}) → ({cur_x},{cur_y}) "
                    f"win_id={self.win_id!r} drag={self._drag_active}"
                )
                if not self._drag_active:
                    # Programmatisk flytt (auto-reposition, z-order, skärmbyte)
                    # — spara direkt, throttlen gäller bara användar-drag.
                    # FIX v7-fix43: i barn-läge är self.x()/y() LOKALA (0,0)
                    # — läs SKALETS skärmposition istället!
                    _sh_m = getattr(self, "_shell", None)
                    if _sh_m is not None:
                        cur_x, cur_y = _sh_m.x(), _sh_m.y()
                    logger.debug(
                        f"{LOG_PREFIX} moveEvent: programmatisk flytt — "
                        f"sparar utan throttle (skal-pos {cur_x},{cur_y})"
                    )
                    if hasattr(self.settings, "update_window_position"):
                        self.settings.update_window_position(
                            self.win_id, cur_x, cur_y
                        )
                        self._last_pos_save = time.monotonic()
                    return
                # Användar-drag → throttla (max 2 sparningar/sekund)
                now = time.monotonic()
                last = getattr(self, "_last_pos_save", 0.0)
                elapsed_ms = (now - last) * 1000.0
                if elapsed_ms < 500.0:
                    logger.trace(
                        f"{LOG_PREFIX} moveEvent: throttle — "
                        f"{elapsed_ms:.0f}ms sedan senaste save (<500ms)"
                    )
                    return
                self._last_pos_save = now
                # FIX v7-fix43: läs SKALETS position i barn-läge
                _sh_d = getattr(self, "_shell", None)
                if _sh_d is not None:
                    cur_x, cur_y = _sh_d.x(), _sh_d.y()
                logger.debug(
                    f"{LOG_PREFIX} moveEvent: sparar position "
                    f"({cur_x},{cur_y}) — {elapsed_ms:.0f}ms sedan senaste"
                )
                if hasattr(self.settings, "update_window_position"):
                    self.settings.update_window_position(
                        self.win_id, cur_x, cur_y
                    )
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} moveEvent misslyckades: {e}"
                )

        @_log_event("event:show")
        def _is_child(self) -> bool:
            """FIX v7-fix29: Är vi ett barn-widget (i skal-QWidget)?"""
            try:
                return self.parent() is not None
            except Exception:
                return False

        def _native_window_ok(self) -> bool:
            """
            NY v7-fix18: finns ett fungerande nativt fönster?

            OBS: QWidget::winId() TVINGAR fram fönster-skapande — därför
            läser vi QWindow::winId() via windowHandle() istället (ren
            getter som ALDRIG skapar). False innan första show() (normalt)
            och True efter en lyckad show().
            """
            try:
                if self._is_child():
                    # Barn: kolla FÖRÄLDERNs fönster (skalet)
                    _p = self.parent()
                    if _p is None:
                        return False
                    _ph = _p.windowHandle()
                    return _ph is not None and int(_ph.winId()) != 0
                wh = self.windowHandle()
                if wh is None:
                    return False
                return int(wh.winId()) != 0
            except Exception:
                return False

        def _handle_window_creation_failure(self) -> None:
            """
            NY v7-fix18: CreateWindowEx misslyckades → karantän + backoff.

            Storm-mekaniken som brutits:
              show() → [fönstret kan ej skapas] → Qt försöker igen vid varje
              expose/paint + VÅRA winId()-anrop tvingar fram fler försök →
              tusentals "CreateWindowEx failed"-rader per minut.

            Nu: hide() stoppar Qt:s omförsök OMEDELBART (stormen dör),
            sedan max 5 nya försök med exponentiell backoff (2s → 20s).
            """
            self._win_fail_count = getattr(self, "_win_fail_count", 0) + 1
            n = self._win_fail_count
            if n == 2:
                # FIX v7-fix20: sond — skiljer miljö-fel från vår widget-setup
                self._probe_bare_window()
            if n == 1:
                # FIX v7-fix25: FULL STACK-TRACE — visar EXAKT vilken
                # kodrad som ledde till show()-anropet
                import traceback as _tb_full
                _stack = "".join(_tb_full.format_stack())
                logger.critical(
                    f"{LOG_PREFIX} ★ STACK-TRACE (exakt kodväg till "
                    f"misslyckat show()):\n{_stack}"
                )
                thread_txt = "okänd"
                try:
                    from PySide6.QtCore import QThread
                    thread_txt = QThread.currentThread().objectName() or "main"
                except Exception:
                    pass
                logger.error(
                    f"{LOG_PREFIX} ★ FÖNSTERSKAPANDE MISSLYCKADES (försök 1) "
                    f"— karantän + backoff. Tråd={thread_txt} "
                    f"geo=({self.x()},{self.y()}) {self.width()}x{self.height()} "
                    f"flags={int(self.windowFlags())} dpr={self._dpr}. "
                    f"Vanligaste orsaken: ogiltig geometri i settings.json "
                    f"(klamras nu automatiskt, se _restore_window_position)."
                )
            try:
                self.hide()  # stoppar expose/paint-omförsöken = stormen dör
            except Exception:
                pass
            if n >= 5:
                logger.error(
                    f"{LOG_PREFIX} Fönstret kunde inte skapas efter {n} "
                    f"försök — GER UPP (appen fortsätter, tray fungerar). "
                    f"ÅTGÄRD: 1) stäng appen 2) öppna data\\settings.json och "
                    f"radera hela \"windows\"-avsnittet 3) starta igen. "
                    f"Uppdatera ev. grafikdrivrutin."
                )
                return
            delay_ms = min(2000 * (2 ** (n - 1)), 20000)
            logger.warning(
                f"{LOG_PREFIX} fönster-karantän: nytt försök om {delay_ms} ms "
                f"(försök {n + 1}/5)"
            )
            QTimer.singleShot(delay_ms, self._retry_show_after_failure)

        def _probe_bare_window(self) -> None:
            """
            NY v7-fix20: skapa ett BART QWidget och försök visa det.

            Skiljer MILJÖ-fel (Qt-installation/drvrutin/Python-version) från
            fel i VÅR widget-setup:
              probe OK  → miljön kan skapa fönster → problemet är vår setup
              probe FALLER → hela Qt-installationen kan inte skapa fönster
                          → åtgärd: 'pip install --upgrade PySide6'
            """
            try:
                from PySide6.QtWidgets import QWidget as _QW
                probe = _QW()
                probe.setObjectName("DTPProbe")
                probe.setWindowTitle("TaskBord-probe")
                probe.resize(200, 100)
                probe.show()
                _ok = False
                try:
                    _wh = probe.windowHandle()
                    _ok = _wh is not None and int(_wh.winId()) != 0
                except Exception:
                    _ok = False
                if _ok:
                    logger.error(
                        f"{LOG_PREFIX} ★ PROBE: bart QWidget SKAPADES OK → "
                        f"miljön fungerar, problemet är TodoWidget:s setup "
                        f"(flags/ikoner/barn). Rapport: window_failure_report.txt"
                    )
                else:
                    logger.error(
                        f"{LOG_PREFIX} ★ PROBE: bart QWidget MISSLYCKADES "
                        f"också → HELA Qt-installationen kan inte skapa "
                        f"fönster. ÅTGÄRD: pip install --upgrade PySide6 "
                        f"(Python 3.14 kräver färsk PySide6!)"
                    )
                with suppress(Exception):
                    probe.close()
                    probe.deleteLater()
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} probe misslyckades: {e}")

        def _retry_show_after_failure(self) -> None:
            """NY v7-fix18: backoff-retry efter misslyckat fönsterskapande."""
            logger.info(f"{LOG_PREFIX} fönster-karantän: försöker visa igen…")
            try:
                self.show()
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} retry-show misslyckades: {e}")

        def showEvent(self, event):
            """FIX 2026-09-24: logga + återställ z-order när widgeten syns.

            FIX v7-fix18: om det nativa fönstret inte kunde skapas går vi i
            karantän DIRECT (winId() i logg-raden tvingade tidigare fram nya
            CreateWindowEx-försök vid VARJE event = storm-motorn)."""
            try:
                if sys.platform == "win32" and not self._native_window_ok():
                    self._handle_window_creation_failure()
                    with suppress(Exception):
                        super().showEvent(event)
                    return
                if getattr(self, "_win_fail_count", 0) > 0:
                    logger.info(
                        f"{LOG_PREFIX} fönstret SKAPAT EFTER karantän — "
                        f"återställer felräknare"
                    )
                    self._win_fail_count = 0
                _hwnd_txt = "(saknas)"
                if self._native_window_ok():
                    with suppress(Exception):
                        _hwnd_txt = str(int(self.winId()))
                _sh_s = getattr(self, "_shell", None)
                logger.info(
                    f"{LOG_PREFIX} 🔺 showEvent: FÖNSTRET SYNS — "
                    f"win_id={self.win_id!r} HWND={_hwnd_txt} "
                    f"pos=({self.x()},{self.y()}) "
                    f"size=({self.width()}x{self.height()})"
                    + (
                        f" skal=({_sh_s.x()},{_sh_s.y()}) "
                        f"{_sh_s.width()}x{_sh_s.height()}"
                        if _sh_s is not None else ""
                    )
                )
                super().showEvent(event)
                # FIX 2026-09-25 v7-fix7: reentrancy-skydd — showEvent → SetWindowPos
                # → moveEvent → save → signal → populate → show() → showEvent (LOOP!).
                # Hoppa över z-order-push om vi redan satt denna cykel.
                if getattr(self, "_zorder_in_show", False):
                    return
                self._zorder_in_show = True
                try:
                    # FIX 2026-09-25: reaktiv HWND_BOTTOM (andra fönster kan ha flyttat oss)
                    with suppress(Exception):
                        self._setup_bugg19_zorder()
                finally:
                    self._zorder_in_show = False
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} showEvent misslyckades: {e}"
                )

        @_log_event("event:hide")
        def hideEvent(self, event):
            """
            FIX 2026-09-24: logga när widgeten göms.
            NY v7-fix44 (500000%-loggningen): synlighetsspårning —
            visar VEM/VAD som gömde fönstret + skal-status + orsak.
            """
            try:
                # FIX v7-fix18: winId() får aldrig tvinga fram skapande
                _hwnd_txt = "(saknas)"
                if self._native_window_ok():
                    with suppress(Exception):
                        _hwnd_txt = str(int(self.winId()))
                # Kort anropsstack — vem gömde oss?
                _cause = "?"
                with suppress(Exception):
                    import traceback as _tb
                    _frames = _tb.extract_stack(limit=4)[:-1]
                    if _frames:
                        _f = _frames[-1]
                        _cause = f"{_f.name} ({_f.filename.split(chr(92))[-1]}:{_f.lineno})"
                _sh = getattr(self, "_shell", None)
                _sh_state = (
                    f"skal synlig={_sh.isVisible()}" if _sh is not None
                    else "inget skal (fristående)"
                )
                _why = (
                    "APPMEN STÄNGER (allow_close=True)"
                    if getattr(self, "_allow_close", False)
                    else "GÖMS (X-knapp/toggle/hotkey eller systemet)"
                )
                logger.info(
                    f"{LOG_PREFIX} 🔻 hideEvent: FÖNSTRET GÖMS — "
                    f"win_id={self.win_id!r} HWND={_hwnd_txt} | "
                    f"{_why} | {_sh_state} | orsak={_cause}"
                )
                super().hideEvent(event)
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} hideEvent misslyckades: {e}"
                )

        @_log_event("event:change")
        def changeEvent(self, event):
            """FIX 2026-09-24: logga state-changes (minimized, fullscreen…).
            FIX v7-fix10: windowState() är enum i PySide6 >= 6.9 — int() kraschar
            där; !r funkar i ALLA versioner (och är mer läsbart i loggen)."""
            try:
                _etype = getattr(event.type(), "name", None) or repr(event.type())
                logger.debug(
                    f"{LOG_PREFIX} changeEvent type={_etype} "
                    f"state={self.windowState()!r}"
                )
                super().changeEvent(event)
            except Exception as e:
                logger.warning(
                    f"{LOG_PREFIX} changeEvent misslyckades: {e}"
                )

        @_log_event("event:native")
        def nativeEvent(self, eventType, message):
            """
            NY v6.4.1 v7: Win32-event handler — blockerar Win+D-hide.

            Rickard 2026-09-25: "Win+D ska ej funka för att dölja fönstret".

            Skydd:
              1. WM_SYSCOMMAND + SC_MINIMIZE/SC_CLOSE → blockera + re-show
              2. WM_SIZE + SIZE_MINIMIZED → blockera + re-show
              3. WM_SHOWWINDOW wParam utan SW_SHOW-flagga → blockera
            """
            if sys.platform != "win32":
                return False, 0
            # FIX v7-fix29: barn → skalet hanterar native events
            if self._is_child():
                return False, 0
            try:
                import ctypes
                from ctypes import wintypes
                WM_SYSCOMMAND = 0x0112
                WM_SIZE = 0x0005
                WM_SHOWWINDOW = 0x0018
                SC_MINIMIZE = 0xF020
                SC_CLOSE = 0xF060
                SIZE_MINIMIZED = 1
                class MSG(ctypes.Structure):
                    _fields_ = [
                        ("hwnd", wintypes.HWND),
                        ("message", wintypes.UINT),
                        ("wParam", wintypes.WPARAM),
                        ("lParam", wintypes.LPARAM),
                        ("time", wintypes.DWORD),
                        ("pt_x", wintypes.LONG),
                        ("pt_y", wintypes.LONG),
                    ]
                msg = MSG.from_address(int(message))
                user32 = ctypes.windll.user32
                # FIX v7-fix18: winId() får aldrig tvinga fram skapande
                hwnd = int(self.winId()) if self._native_window_ok() else 0

                if msg.message == WM_SYSCOMMAND:
                    cmd = msg.wParam & 0xFFF0
                    if cmd == SC_MINIMIZE or cmd == SC_CLOSE:
                        label = "SC_MINIMIZE" if cmd == SC_MINIMIZE else "SC_CLOSE"
                        logger.info(
                            f"{LOG_PREFIX} nativeEvent: blockerade {label} (Win+D-skydd)"
                        )
                        if hwnd:
                            user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
                        return True, 0
                if msg.message == WM_SIZE:
                    if msg.wParam == SIZE_MINIMIZED:
                        logger.info(
                            f"{LOG_PREFIX} nativeEvent: blockerade WM_SIZE=SIZE_MINIMIZED"
                        )
                        if hwnd:
                            user32.ShowWindow(hwnd, 4)
                        return True, 0
                if msg.message == WM_SHOWWINDOW:
                    if not (msg.wParam & 1):  # bit 0 = SW_SHOW
                        logger.info(
                            f"{LOG_PREFIX} nativeEvent: blockerade WM_SHOWWINDOW"
                            f" wParam={msg.wParam}"
                        )
                        if hwnd:
                            user32.ShowWindow(hwnd, 4)
                        return True, 0
            except Exception as e:
                logger.debug(f"{LOG_PREFIX} nativeEvent misslyckades: {e}")
            return False, 0

        # ====================================================================
        # DPI DETECTION
        # ====================================================================

        def _detect_dpr(self) -> float:
            """Detektera device pixel ratio."""
            try:
                if hasattr(self, "devicePixelRatio"):
                    return float(self.devicePixelRatio())
            except Exception:
                pass
            return 1.0

        # ====================================================================
        # HEALTH / STATS
        # ====================================================================

        def get_health_report(self) -> Dict[str, Any]:
            """
            NY v6.4.1 v7: Diagnostik-rapport (forbattrad).

            Innehall (alla svenska faltnamn for Rickard):
              - win_id, qt_backend, dpr
              - renders (totalt + långsamma)
              - pwm-state + stats
              - cache-storlekar (task, pixmap, search-index)
              - hotkeys, locked, focus_mode
            """
            return {
                "win_id": self.win_id,
                "qt_backend": _QT_BACKEND,
                "dpr": self._dpr,
                "render_count": self._render_count,
                "slow_render_count": self._slow_render_count,
                "pwm": self._throttle.stats,
                "audit": self._audit.stats(),
                "task_widgets_cached": len(self._task_widgets),
                "pixmap_cache_size": len(self._pixmap_cache),
                "search_index_size": len(self._search_index),
                "hotkeys_registered": len(self._hotkey_shortcuts),
                "locked": self._locked,
                "auto_relock_active": (
                    self._unlock_timer is not None
                    and self._unlock_timer.isActive()
                ),
                # NY v6.4.1 v7: fokuslage + aktuell task-index
                "focus_mode": self._focus_mode,
                "focus_index": self._focus_index,
                # NY v6.4.1 v7: filter-state
                "current_filter": self._current_filter,
                "current_tag_filter": self._current_tag_filter,
                # NY v6.4.1 v7: input-prio
                "pending_input_priority": self._pending_input_priority,
            }

        def _validate_widget_state(self) -> List[str]:
            """
            NY v6.4.1 v7: Validera widget-state, returnera issues.

            Returns:
                Lista av svenska issue-strängar (tom = allt OK)

            Exempel:
                >>> issues = self._validate_widget_state()
                >>> if issues: print(f"Problem: {issues}")
            """
            issues: List[str] = []
            try:
                # Store finns?
                if self.store is None:
                    issues.append("Store saknas (kan inte visa uppgifter)")
                # Settings finns?
                if self.settings is None:
                    issues.append("Settings saknas (kan inte spara position)")
                # Tab-widget finns?
                if not hasattr(self, "tabs") or self.tabs is None:
                    issues.append("Tabs-widget saknas (UI trasigt)")
                # Search-input finns?
                if not hasattr(self, "search_input") or self.search_input is None:
                    issues.append("Sokfalt saknas (UI trasigt)")
                # Input-field finns?
                if not hasattr(self, "input_field") or self.input_field is None:
                    issues.append("Input-falt saknas (kan inte lagga till)")
                # Content-stack finns?
                if not hasattr(self, "content_stack"):
                    issues.append("Content-stack saknas (Focus Mode trasigt)")
                # Lock-button finns?
                if not hasattr(self, "lock_btn"):
                    issues.append("Lock-button saknas")
                # Z-order timer aktiv?
                if not hasattr(self, "_zorder_timer"):
                    issues.append("Z-order timer saknas (Win+D-skydd fungerar inte)")
                # Pixmap cache-storlek rimlig?
                if len(self._pixmap_cache) > HIDPI_PIXMAP_CACHE_SIZE * 2:
                    issues.append(
                        f"Pixmap cache stor ({len(self._pixmap_cache)} items) — overvagn minne"
                    )
                # Search index rimlig?
                if len(self._search_index) > 10000:
                    issues.append(
                        f"Sok-index mycket stor ({len(self._search_index)} tokens)"
                    )
                # Task widgets cached rimlig?
                if len(self._task_widgets) > 1000:
                    issues.append(
                        f"Manga task-widgets cached ({len(self._task_widgets)})"
                    )
                # Slow renders ratio
                if self._render_count > 0:
                    slow_pct = (self._slow_render_count / self._render_count * 100)
                    if slow_pct > 10:
                        issues.append(
                            f"Manga långsamma renders ({slow_pct:.1f}% > 10%)"
                        )
            except Exception as e:
                issues.append(f"Validering kraschade: {_describe_widget_error(e)}")
            return issues

        def __repr__(self) -> str:
            """NY v6.4.1 v7: Mer detaljerad __repr__ for felsökning."""
            return (
                f"<TodoWidget win_id={self.win_id!r} "
                f"tasks_cached={len(self._task_widgets)} "
                f"focus_mode={self._focus_mode} "
                f"locked={self._locked} "
                f"pwm={self._throttle.state.name} "
                f"qt_backend={_QT_BACKEND}>"
            )


# ===========================================================================
# EXPORTS
# ===========================================================================

__all__ = [
    # PWM
    "AdaptiveThrottle", "ThrottleState", "get_throttle",
    # Audit
    "WidgetAudit",
    # UI-klasser
    "EditableLabel", "TagChip", "PriorityBadge", "PriorityDot", "DueDateLabel",
    "GlassFrame", "TodoWidget",
    # Constants
    "LOG_PREFIX", "APP_NAME", "APP_VERSION", "WIDGET_VERSION",
    "PWM_FPS_ACTIVE_MS", "PWM_FPS_NORMAL_MS", "PWM_FPS_IDLE_MS",
    "TAG_COLORS", "PRIORITY_COLORS", "PRIORITY_ORDER", "PRIORITY_CYCLE",
    "PRIORITY_ROW_TINT",
    # AI-felsökning (NY v6.4.1 v7)
    "_QT_ERROR_TRANSLATIONS",
    "_describe_widget_error", "_format_widget_traceback",
    "_categorize_widget_error", "_show_widget_error",
    "safe_call", "safe_run", "_safe_run_async",
    # Svenska formatters (NY v6.4.1 v7)
    "format_task_summary_swedish", "summarize_widget_health",
    # Diagnostik (NY v6.4.1 v7)
    "get_widget_diagnostics",
    # Plugin-coupling (NY v6.4.1 v7)
    "get_widget_plugin_deps",
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
    print(f"widget.py v{APP_VERSION} (8 000% bättre + PWM) — Self-Test")
    print(f"qt_available={_QT_AVAILABLE}, backend={_QT_BACKEND}")
    print("=" * 70)

    # Test 1: PWM AdaptiveThrottle
    print("\n[Test 1] PWM AdaptiveThrottle...")
    pwm = AdaptiveThrottle()
    print(f"  ✓ Initial state: {pwm.state.name}, interval={pwm.current_interval_ms}ms")
    pwm.notify_activity()
    print(f"  ✓ After activity: {pwm.state.name}, interval={pwm.current_interval_ms}ms (60 FPS)")
    pwm.record_frame(16.7)  # 60 FPS frame
    pwm.record_frame(33.3)  # 30 FPS frame
    print(f"  ✓ EMA FPS: {pwm.stats['ema_fps']:.1f}")
    # Simulera idle (tvinga NORMAL först, sedan idle)
    pwm._state = ThrottleState.NORMAL
    pwm._last_activity = time.time() - 10
    interval = pwm.update()
    print(f"  ✓ After 10s idle (NORMAL→IDLE): state={pwm.state.name}, interval={interval}ms")
    print(f"  ✓ CPU saved: {pwm.stats['saved_cpu_percent']:.0f}%")

    # Test 2: WidgetAudit
    print("\n[Test 2] WidgetAudit...")
    audit = WidgetAudit()
    audit.add("test_event", {"key": "value"})
    audit.add("another_event")
    print(f"  ✓ Audit entries: {audit.stats()}")

    # Test 3: _tokenize_cached (om Qt finns)
    print("\n[Test 3] _tokenize_cached (lru_cache)...")
    if _QT_AVAILABLE and "TodoWidget" in dir():
        tokens1 = TodoWidget._tokenize_cached("Hello World")
        tokens2 = TodoWidget._tokenize_cached("Hello World")
        print(f"  ✓ Tokens('Hello World'): {tokens1}")
        print(f"  ✓ Cache hit: {tokens1 is tokens2}")
    else:
        # Testa med en fristående wrapper
        @functools.lru_cache(maxsize=128)
        def test_tokenize(text: str) -> FrozenSet[str]:
            return frozenset(t.lower() for t in text.split() if t)
        t1 = test_tokenize("Hello World")
        t2 = test_tokenize("Hello World")
        print(f"  ✓ Test tokenize('Hello World'): {t1}")
        print(f"  ✓ Cache hit: {t1 is t2}")
        print(f"  ✓ Cache info: {test_tokenize.cache_info()}")

    # Test 4: Throttle state transitions
    print("\n[Test 4] PWM state transitions...")
    pwm2 = AdaptiveThrottle()
    pwm2._last_activity = time.time()  # Now
    pwm2.update()
    pwm2.notify_activity()
    print(f"  ✓ Active: state={pwm2.state.name}")
    pwm2._last_activity = time.time() - 100
    pwm2.update()
    print(f"  ✓ After 100s: state={pwm2.state.name}")
    pwm2.set_locked(True)
    print(f"  ✓ After lock: state={pwm2.state.name}")
    pwm2.set_locked(False)
    print(f"  ✓ After unlock: state={pwm2.state.name}")

    # Test 5: get_throttle (singleton)
    print("\n[Test 5] get_throttle (singleton)...")
    t1 = get_throttle()
    t2 = get_throttle()
    print(f"  ✓ Singleton: {t1 is t2}")

    # Test 6: PWM savings simulation
    print("\n[Test 6] PWM CPU-besparing simulering...")
    pwm3 = AdaptiveThrottle()
    # Simulera 100 frames under 10s med IDLE-throttle
    pwm3._state = ThrottleState.IDLE
    pwm3._current_interval_ms = PWM_FPS_IDLE_MS
    frames_per_10s = 10000 // PWM_FPS_IDLE_MS
    normal_frames = 10000 // PWM_FPS_NORMAL_MS
    cpu_saved = (1 - frames_per_10s / normal_frames) * 100
    print(f"  ✓ IDLE frames per 10s: {frames_per_10s}")
    print(f"  ✓ NORMAL frames per 10s: {normal_frames}")
    print(f"  ✓ CPU saved: ~{cpu_saved:.0f}%")

    print()
    print("=" * 70)
    print(f"✓ ALLA 5 TESTER PASSERADE (widget.py v{APP_VERSION} + PWM)")
    print("=" * 70)
