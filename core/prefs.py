# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""
prefs.py — nya inställningar i EN ordlista (``settings["prefs"]``) med standardvärde och rensning per nyckel.

Ren logik (ingen Qt). ``core.settings.Settings.pref(key)`` / ``set_pref(key, value)`` använder ``coerce`` här, så ett
trasigt värde i filen aldrig kan ge annat än ett giltigt värde.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, Tuple

_HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def _bool(default: bool) -> Callable[[Any], bool]:
    def f(v: Any) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return bool(v)
        if isinstance(v, str):
            return v.strip().lower() in ("1", "true", "ja", "yes", "on")
        return default
    return f


def _int(default: int, lo: int, hi: int) -> Callable[[Any], int]:
    def f(v: Any) -> int:
        try:
            n = int(round(float(v)))
        except (TypeError, ValueError):
            return default
        return max(lo, min(hi, n))
    return f


def _choice(default: str, valid: Tuple[str, ...]) -> Callable[[Any], str]:
    def f(v: Any) -> str:
        s = str(v or "").strip().lower()
        return s if s in valid else default
    return f


def _hhmm(default: str) -> Callable[[Any], str]:
    def f(v: Any) -> str:
        m = _HHMM.match(str(v or "").strip())
        return f"{int(m.group(1)):02d}:{m.group(2)}" if m else default
    return f


def _list(default: Any, maxlen: int) -> Callable[[Any], Any]:
    def f(v: Any) -> Any:
        if not isinstance(v, list):
            return list(default)
        return [x for x in v if isinstance(x, dict)][:maxlen]
    return f


THEME_PRESETS = ("standard", "hav", "skog", "solnedgang", "grafit", "kontrast")
SOUNDS = ("none", "chime", "bell", "gentle")
LANGS = ("sv", "en")

# nyckel → (standardvärde, rensare)
SPEC: Dict[str, Tuple[Any, Callable[[Any], Any]]] = {
    # 🌙 tysta timmar
    "quiet_enabled": (True, _bool(True)),
    "quiet_start": ("22:00", _hhmm("22:00")),
    "quiet_end": ("08:00", _hhmm("08:00")),
    "quiet_weekends": (False, _bool(False)),
    # 🎨 teman
    "theme_preset": ("standard", _choice("standard", THEME_PRESETS)),
    "glass_strength": (85, _int(85, 70, 100)),       # panelens täckning i % (aldrig under 70 — läsbarhet)
    "bg_dim": (0, _int(0, 0, 60)),                   # extra mörkläggning av bakgrunden i %
    "high_contrast": (False, _bool(False)),
    # 🔠 tillgänglighet
    "text_scale": (100, _int(100, 80, 200)),
    "focus_rings": (True, _bool(True)),
    # 🪟 mini-läge
    "mini_mode": (False, _bool(False)),
    "mini_restore": ([], lambda v: [int(x) for x in v][:4] if isinstance(v, list) and all(isinstance(x, (int, float)) for x in v) else []),
    # 👋 välkomstguide
    "welcome_done": (False, _bool(False)),
    # 🌐 språk
    "lang": ("sv", _choice("sv", LANGS)),
    # ↔ skärmkantsdockning slog på "Visa över andra appar" (läget återställs när dockningen släpps)
    "dock_forced_top": (False, _bool(False)),
    # ☁️ flytta Google Calendar-händelsen när datum ändras (bara uppgifter som redan finns där)
    "gcal_autosync": (True, _bool(True)),
    "autostart_dock": (True, _bool(True)),   # start med datorn: lägg fönstret i skärmkanten (annars göms det i tray)
    "start_min_default": (False, _bool(False)),   # engångsmigrering: "Starta minimerad" blev standard
    # 📆 kalenderprenumerationer (ICS)
    "ics_subs": ([], _list([], 12)),
}

DEFAULTS: Dict[str, Any] = {k: (list(v[0]) if isinstance(v[0], list) else v[0]) for k, v in SPEC.items()}


def coerce(key: str, value: Any) -> Any:
    """Giltigt värde för ``key`` (okänd nyckel → ValueError)."""
    if key not in SPEC:
        raise KeyError(key)
    default, fn = SPEC[key]
    try:
        return fn(value)
    except Exception:
        return list(default) if isinstance(default, list) else default


def default(key: str) -> Any:
    d = SPEC[key][0]
    return list(d) if isinstance(d, list) else d


def get(prefs: Any, key: str) -> Any:
    """Värdet ur en ordlista (saknas/trasigt → standardvärdet)."""
    if not isinstance(prefs, dict) or key not in prefs:
        return default(key)
    return coerce(key, prefs[key])
