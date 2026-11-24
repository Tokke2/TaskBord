# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""
tag_colors.py — färg per tagg. Ren stdlib (testas utan Qt).

* Samma tagg får ALLTID samma färg, oavsett vilken uppgift den sitter på eller i vilken ordning
  taggarna står (förut styrdes färgen av platsen i uppgiftens taggslista). Standardfärgen väljs
  ur ``PALETTE`` med ett stabilt hash av taggnamnet (gemener, så "Faktura" = "faktura").
* Användaren kan välja egen färg per tagg; valen sparas i inställningarna (``tag_colors``,
  {gement taggnamn: "#rrggbb"}).
* ``text_color_for`` väljer svart eller vit text så att kontrasten mot färgen alltid är ≥ 4,5:1
  (WCAG AA) — även för färger användaren valt själv.
"""
from __future__ import annotations

import re
import zlib
from typing import Any, Dict, List, Optional, Tuple

# (namn, färg). Alla ger ≥ 4,5:1 mot vit text; ordningen är en del av "stabil standardfärg" — ändra
# den inte (då byter alla taggar färg), lägg nya sist.
PALETTE: List[Tuple[str, str]] = [
    ("Indigo", "#4f46e5"),
    ("Rosa", "#be185d"),
    ("Grön", "#047857"),
    ("Orange", "#b45309"),
    ("Lila", "#7c3aed"),
    ("Turkos", "#0e7490"),
    ("Lime", "#4d7c0f"),
    ("Röd", "#b91c1c"),
    ("Blå", "#1d4ed8"),
    ("Grå", "#4b5563"),
    ("Brun", "#92400e"),
    ("Magenta", "#a21caf"),
]

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
WHITE = "#ffffff"
DARK = "#000000"
MAX_CUSTOM = 200  # fler egna taggfärger än så sparas inte (skydd mot skräp i inställningsfilen)


def normalize(tag: Any) -> str:
    """Nyckeln för en tagg: trimmad, gemener, enkla mellanrum."""
    return " ".join(str(tag or "").split()).lower()


def valid_hex(value: Any) -> bool:
    return isinstance(value, str) and bool(_HEX.match(value.strip()))


def normalize_hex(value: Any) -> Optional[str]:
    """'#ABCDEF' / ' #abcdef ' → '#abcdef'; annars None."""
    if not valid_hex(value):
        return None
    return str(value).strip().lower()


def default_color(tag: Any) -> str:
    """Stabil standardfärg för taggen (samma namn → samma färg, alltid, på alla datorer)."""
    key = normalize(tag)
    return PALETTE[zlib.crc32(key.encode("utf-8")) % len(PALETTE)][1]


def resolve(tag: Any, overrides: Optional[Dict[str, str]] = None) -> str:
    """Färgen att visa: användarens val om det finns (och är giltigt), annars standardfärgen."""
    if overrides:
        c = normalize_hex(overrides.get(normalize(tag)))
        if c:
            return c
    return default_color(tag)


def clean_overrides(raw: Any) -> Dict[str, str]:
    """Rensa en sparad ordlista: bara giltiga '#rrggbb', gemena nycklar, max MAX_CUSTOM st."""
    out: Dict[str, str] = {}
    if not isinstance(raw, dict):
        return out
    for k, v in raw.items():
        key = normalize(k)
        col = normalize_hex(v)
        if key and col:
            out[key] = col
        if len(out) >= MAX_CUSTOM:
            break
    return out


def _lin(c: int) -> float:
    s = c / 255.0
    return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4


def luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast(a: str, b: str) -> float:
    """WCAG-kontrast mellan två '#rrggbb' (1 … 21)."""
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def text_color_for(bg_hex: str) -> str:
    """Vit eller mörk text — den som ger bäst kontrast mot bakgrunden (alltid ≥ 4,5:1)."""
    return WHITE if contrast(bg_hex, WHITE) >= contrast(bg_hex, DARK) else DARK


def darker(hex_color: str, factor: float = 0.78) -> str:
    """Något mörkare kulör (för chipets kant)."""
    h = hex_color.lstrip("#")
    r, g, b = (max(0, min(255, int(int(h[i:i + 2], 16) * factor))) for i in (0, 2, 4))
    return f"#{r:02x}{g:02x}{b:02x}"
