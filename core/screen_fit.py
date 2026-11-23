# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""
screen_fit.py — fönstret anpassar sig efter skärmen (ren logik, ingen Qt).

* ``fit_size``: lagom storlek för skärmens användbara yta (bredd ≈ 24 %, höjd ≈ 90 %), avrundad till ett steg som ger
  HELA bildpunkter på skärmar med skalning (125 % → steg om 4 px, 150 % → 2 px). Fönster på halva bildpunkter blir
  suddiga — heltalsstorlek ger skarp text och skarpa kanter.
* ``clamp_rect``: håller ett fönster inom den användbara ytan (krymper bara om det är större än skärmen).
"""
from __future__ import annotations

from typing import Tuple

Rect = Tuple[int, int, int, int]      # x, y, w, h

MIN_W, MAX_W = 400, 560
MIN_H, MAX_H = 480, 900
MARGIN = 24


def pixel_step(dpr: float) -> int:
    """Minsta logiska steg (≥ 2) som ger heltal bildpunkter vid skalfaktorn ``dpr`` (1.25 → 4, 1.5 → 2, 1.75 → 4)."""
    try:
        d = float(dpr)
    except (TypeError, ValueError):
        return 2
    if d <= 0:
        return 2
    for s in range(1, 17):
        if abs(s * d - round(s * d)) < 1e-6:
            return max(2, s)
    return 4


def snap(n: float, step: int, lo: int = 0) -> int:
    """Avrunda ``n`` nedåt till närmaste multipel av ``step`` (aldrig under ``lo``)."""
    step = max(1, int(step))
    v = int(n) // step * step
    return max(v, lo // step * step if lo else 0)


def fit_size(avail_w: int, avail_h: int, dpr: float = 1.0) -> Tuple[int, int]:
    """Fönsterstorlek (w, h) för en skärm med användbar yta ``avail_w`` × ``avail_h`` (logiska px)."""
    aw, ah = max(1, int(avail_w)), max(1, int(avail_h))
    step = pixel_step(dpr)
    w = min(max(aw * 0.24, MIN_W), MAX_W, aw - MARGIN * 2)
    h = min(max(ah * 0.90, MIN_H), MAX_H, ah - MARGIN * 2)
    w = max(snap(w, step), min(150, aw))
    h = max(snap(h, step), min(200, ah))
    return int(w), int(h)


def clamp_rect(rect: Rect, avail: Rect) -> Rect:
    """Flytta (och vid behov krymp) ``rect`` så att det ryms i ``avail``. Ligger det redan inom → oförändrat."""
    x, y, w, h = (int(v) for v in rect)
    ax, ay, aw, ah = (int(v) for v in avail)
    w, h = min(w, aw), min(h, ah)
    x = max(ax, min(x, ax + aw - w))
    y = max(ay, min(y, ay + ah - h))
    return x, y, w, h


def is_inside(rect: Rect, avail: Rect, slack: int = 0) -> bool:
    x, y, w, h = rect
    ax, ay, aw, ah = avail
    return x >= ax - slack and y >= ay - slack and x + w <= ax + aw + slack and y + h <= ay + ah + slack
