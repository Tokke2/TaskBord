# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""
themes.py — färgteman, bakgrundsdjup och högkontrastläge (ren logik, ingen Qt).

``adjust_tokens(base, is_dark, preset, bg_dim, high_contrast)`` tar widgetens grundtokens (GLASS_DARK/GLASS_LIGHT i
ui/widget_base.py) och returnerar nya tokens:

* **Färgtema** (``hav``, ``skog``, ``solnedgang``, ``grafit``) byter panelens och kortens färgton — text och accentfärg rörs inte.
* **Bakgrundsdjup** (0–60 %) blandar panelens bakgrund mot svart (mörkt tema) eller vitt (ljust tema): mer kontrast mot texten.
* **Hög kontrast** ersätter allt med svart/vitt, heltäckande ytor, vita/svarta kanter och text som alltid har minst 7:1 (WCAG AAA).

Glasstyrkan (genomskinlighet) ligger kvar i ``window_transparency`` (golv 70 %, se ``MIN_PANEL_OPACITY``).
Alla teman mäts mot ≥ 4,5:1 i tester/themes_test.py.
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

PRESETS: Dict[str, str] = {
    "standard": "Standard",
    "hav": "Hav",
    "skog": "Skog",
    "solnedgang": "Solnedgång",
    "grafit": "Grafit",
    "kontrast": "Hög kontrast",
}

# färgprov (mörk, ljus) för knapparna i dialogen
SWATCH: Dict[str, Tuple[str, str]] = {
    "standard": ("#20243a", "#fafbff"),
    "hav": ("#0c2236", "#f0f9ff"),
    "skog": ("#10261c", "#f0fdf4"),
    "solnedgang": ("#341a22", "#fff7ed"),
    "grafit": ("#202023", "#f4f4f5"),
    "kontrast": ("#000000", "#ffffff"),
}

_OVERRIDES: Dict[str, Dict[str, Dict[str, str]]] = {
    "hav": {
        "dark": {"bg_top": "rgba(12, 34, 54, 248)", "bg_bottom": "rgba(7, 20, 34, 252)",
                 "surface": "rgba(40, 100, 140, 95)", "surface_hov": "rgba(52, 124, 170, 165)",
                 "surface_edge": "rgba(125, 190, 230, 0.26)", "edge_hov": "rgba(125, 190, 230, 0.55)",
                 "field_bg": "rgba(6, 18, 30, 200)", "field_focus": "rgba(12, 32, 50, 235)"},
        "light": {"bg_top": "rgba(240, 249, 255, 250)", "bg_bottom": "rgba(219, 238, 250, 252)",
                  "surface": "rgba(255, 255, 255, 215)", "surface_edge": "rgba(30, 100, 150, 0.28)",
                  "edge_hov": "rgba(30, 100, 150, 0.58)"},
    },
    "skog": {
        "dark": {"bg_top": "rgba(16, 38, 28, 248)", "bg_bottom": "rgba(8, 22, 15, 252)",
                 "surface": "rgba(52, 120, 86, 95)", "surface_hov": "rgba(66, 146, 106, 165)",
                 "surface_edge": "rgba(140, 214, 170, 0.26)", "edge_hov": "rgba(140, 214, 170, 0.55)",
                 "field_bg": "rgba(6, 22, 14, 200)", "field_focus": "rgba(12, 36, 24, 235)"},
        "light": {"bg_top": "rgba(240, 253, 244, 250)", "bg_bottom": "rgba(220, 241, 228, 252)",
                  "surface": "rgba(255, 255, 255, 215)", "surface_edge": "rgba(30, 120, 70, 0.28)",
                  "edge_hov": "rgba(30, 120, 70, 0.58)"},
    },
    "solnedgang": {
        "dark": {"bg_top": "rgba(52, 26, 34, 248)", "bg_bottom": "rgba(30, 14, 24, 252)",
                 "surface": "rgba(150, 70, 84, 95)", "surface_hov": "rgba(176, 86, 100, 160)",
                 "surface_edge": "rgba(240, 160, 140, 0.26)", "edge_hov": "rgba(240, 160, 140, 0.55)",
                 "field_bg": "rgba(26, 10, 16, 200)", "field_focus": "rgba(44, 18, 28, 235)"},
        "light": {"bg_top": "rgba(255, 247, 237, 250)", "bg_bottom": "rgba(253, 228, 214, 252)",
                  "surface": "rgba(255, 255, 255, 215)", "surface_edge": "rgba(170, 70, 40, 0.28)",
                  "edge_hov": "rgba(170, 70, 40, 0.58)"},
    },
    "grafit": {
        "dark": {"bg_top": "rgba(32, 32, 35, 248)", "bg_bottom": "rgba(17, 17, 19, 252)",
                 "surface": "rgba(112, 112, 120, 95)", "surface_hov": "rgba(136, 136, 146, 160)",
                 "surface_edge": "rgba(200, 200, 210, 0.26)", "edge_hov": "rgba(200, 200, 210, 0.55)",
                 "field_bg": "rgba(10, 10, 12, 200)", "field_focus": "rgba(26, 26, 28, 235)"},
        "light": {"bg_top": "rgba(244, 244, 245, 250)", "bg_bottom": "rgba(228, 228, 231, 252)",
                  "surface": "rgba(255, 255, 255, 215)", "surface_edge": "rgba(60, 60, 70, 0.28)",
                  "edge_hov": "rgba(60, 60, 70, 0.58)"},
    },
}

HIGH_CONTRAST_DARK: Dict[str, str] = {
    "bg_top": "rgba(0, 0, 0, 255)", "bg_bottom": "rgba(0, 0, 0, 255)",
    "surface": "rgba(0, 0, 0, 255)", "surface_hov": "rgba(38, 38, 38, 255)",
    "surface_edge": "rgba(255, 255, 255, 1.0)", "edge_hov": "rgba(255, 235, 59, 1.0)",
    "field_bg": "rgba(0, 0, 0, 255)", "field_focus": "rgba(0, 0, 0, 255)",
    "border": "rgba(255, 255, 255, 1.0)",
    "fg": "#ffffff", "fg_hov": "#ffffff", "muted": "#ffffff", "hint": "#f2f2f2",
    "divider": "rgba(255, 255, 255, 0.6)",
}
HIGH_CONTRAST_LIGHT: Dict[str, str] = {
    "bg_top": "rgba(255, 255, 255, 255)", "bg_bottom": "rgba(255, 255, 255, 255)",
    "surface": "rgba(255, 255, 255, 255)", "surface_hov": "rgba(230, 230, 230, 255)",
    "surface_edge": "rgba(0, 0, 0, 1.0)", "edge_hov": "rgba(0, 0, 160, 1.0)",
    "field_bg": "rgba(255, 255, 255, 255)", "field_focus": "rgba(255, 255, 255, 255)",
    "border": "rgba(0, 0, 0, 1.0)",
    "fg": "#000000", "fg_hov": "#000000", "muted": "#000000", "hint": "#0d0d0d",
    "divider": "rgba(0, 0, 0, 0.6)",
}

_RGBA = re.compile(r"rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)")


def _blend(color: str, amount: float, pole: Tuple[int, int, int]) -> str:
    """Blanda en rgba()-färg mot en pol (svart/vit) — alfa behålls."""
    m = _RGBA.fullmatch(str(color).strip())
    if not m:
        return color
    r, g, b = (int(m.group(i)) for i in (1, 2, 3))
    a = m.group(4)
    nr = round(r + (pole[0] - r) * amount)
    ng = round(g + (pole[1] - g) * amount)
    nb = round(b + (pole[2] - b) * amount)
    return f"rgba({nr}, {ng}, {nb}, {a})" if a is not None else f"rgba({nr}, {ng}, {nb})"


def adjust_tokens(base: Dict[str, str], is_dark: bool, preset: str = "standard", bg_dim: int = 0,
                  high_contrast: bool = False) -> Dict[str, str]:
    """Nya tokens enligt valt tema, bakgrundsdjup och högkontrast. Utan val: ``base`` oförändrad (samma objekt)."""
    if high_contrast or preset == "kontrast":
        out = dict(base)
        out.update(HIGH_CONTRAST_DARK if is_dark else HIGH_CONTRAST_LIGHT)
        return out
    dim = max(0, min(60, int(bg_dim or 0))) / 100.0
    ov = _OVERRIDES.get(preset or "", {}).get("dark" if is_dark else "light")
    if not ov and dim <= 0:
        return base
    out = dict(base)
    if ov:
        out.update(ov)
    if dim > 0:
        pole = (0, 0, 0) if is_dark else (255, 255, 255)
        for k in ("bg_top", "bg_bottom"):
            out[k] = _blend(out[k], dim, pole)
    return out


def is_high_contrast(preset: str, high_contrast: bool) -> bool:
    return bool(high_contrast) or preset == "kontrast"


def labels() -> List[Tuple[str, str]]:
    return list(PRESETS.items())
