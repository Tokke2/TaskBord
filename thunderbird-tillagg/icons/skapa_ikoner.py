# -*- coding: utf-8 -*-
"""
skapa_ikoner.py — genererar tilläggets ikoner (PNG) utan externa paket.

Körs med:  python skapa_ikoner.py
Skapar:    icon-16.png, icon-32.png, icon-48.png, icon-64.png, icon-128.png
           (kuvert i TaskBords indigo + grön bock)

Ren stdlib (zlib + struct) — inga beroenden, fungerar på alla plattformar.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

SS = 4  # supersampling (4x4 prover per pixel → mjuka kanter)

INDIGO_TOP = (129, 140, 248)    # #818cf8
INDIGO_BOTTOM = (99, 102, 241)  # #6366f1
WHITE = (248, 250, 252)
FLAP = (199, 210, 254)
GREEN = (34, 197, 94)
CHECK = (240, 253, 244)


# ---------------------------------------------------------------------------
# Geometri-hjälpare
# ---------------------------------------------------------------------------

def inside_round_rect(x: float, y: float, x0: float, y0: float,
                      x1: float, y1: float, r: float) -> bool:
    """Punkt i rundad rektangel?"""
    if x < x0 or x > x1 or y < y0 or y > y1:
        return False
    cx = min(max(x, x0 + r), x1 - r)
    cy = min(max(y, y0 + r), y1 - r)
    dx, dy = x - cx, y - cy
    return (dx * dx + dy * dy) <= r * r


def dist_to_segment(px: float, py: float, ax: float, ay: float,
                    bx: float, by: float) -> float:
    """Kortaste avstånd från punkt till linjesegment."""
    vx, vy = bx - ax, by - ay
    wx, wy = px - ax, py - ay
    length2 = vx * vx + vy * vy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, (wx * vx + wy * vy) / length2))
    cx, cy = ax + t * vx, ay + t * vy
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5


def inside_circle(x: float, y: float, cx: float, cy: float, r: float) -> bool:
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def sample(x: float, y: float) -> tuple:
    """Färg för en punkt i enhetskvadraten (0..1) — None = genomskinlig."""
    # 1. Rundad bakgrund med gradient
    if not inside_round_rect(x, y, 0.02, 0.02, 0.98, 0.98, 0.22):
        return None
    t = max(0.0, min(1.0, (y - 0.02) / 0.96))
    bg = tuple(
        int(INDIGO_TOP[i] + (INDIGO_BOTTOM[i] - INDIGO_TOP[i]) * t)
        for i in range(3)
    )

    # 2. Kuvert (vit kropp)
    if inside_round_rect(x, y, 0.17, 0.30, 0.83, 0.70, 0.05):
        color = WHITE
        # 2b. Fliken (två linjer från övre hörnen till mitten)
        w = 0.035
        d1 = dist_to_segment(x, y, 0.17, 0.31, 0.50, 0.56)
        d2 = dist_to_segment(x, y, 0.83, 0.31, 0.50, 0.56)
        if min(d1, d2) <= w:
            color = FLAP
        bg = color

    # 3. Grön bock-badge nere till höger
    if inside_circle(x, y, 0.735, 0.735, 0.235):
        bg = GREEN
        w = 0.045
        d1 = dist_to_segment(x, y, 0.635, 0.735, 0.705, 0.805)
        d2 = dist_to_segment(x, y, 0.705, 0.805, 0.845, 0.660)
        if min(d1, d2) <= w:
            bg = CHECK
    return bg


# ---------------------------------------------------------------------------
# Rendering + PNG-skrivning
# ---------------------------------------------------------------------------

def render(size: int) -> bytes:
    """Rendera RGBA-rådata för en ikon i given storlek."""
    rows = []
    step = 1.0 / (size * SS)
    for py in range(size):
        row = bytearray()
        for px in range(size):
            r = g = b = 0
            hits = 0
            for sy in range(SS):
                y = (py * SS + sy + 0.5) * step
                for sx in range(SS):
                    x = (px * SS + sx + 0.5) * step
                    color = sample(x, y)
                    if color is not None:
                        r += color[0]
                        g += color[1]
                        b += color[2]
                        hits += 1
            total = SS * SS
            if hits == 0:
                row += bytes((0, 0, 0, 0))
            else:
                alpha = int(255 * hits / total)
                row += bytes((
                    r // hits, g // hits, b // hits, alpha,
                ))
        rows.append(bytes(row))
    return b"".join(b"\x00" + row for row in rows)


def write_png(path: Path, size: int) -> None:
    raw = render(size)
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)
    print(f"  ✓ {path.name} ({size}×{size}, {len(png)} byte)")


def main() -> None:
    here = Path(__file__).resolve().parent
    print("Skapar TaskBord-tilläggets ikoner…")
    for size in (16, 32, 48, 64, 128):
        write_png(here / f"icon-{size}.png", size)
    print("Klart.")


if __name__ == "__main__":
    main()
