# -*- coding: utf-8 -*-
"""
icon_art.py — Ledgebords appikon, ritad utan externa paket (bara stdlib: zlib + struct).

Motiv: en indigo rundad ruta med en gul KANTLIST längs vänsterkanten ("ledge") och ett vitt
uppgiftskort som glider ut från den, med bockade rader. Samma bild används som fönster-, tray-,
aktivitetsfälts- och genvägsikon (``icon/ledgebord.ico``) och i Thunderbird-tillägget.

* ``render(size)``      → RGBA-bytes (rad för rad, uppifrån), supersamplad för mjuka kanter
* ``build_ico(sizes)``  → .ico med klassiska BMP-poster (≤128 px) + PNG-post för 256 px
* ``build_png(size)``   → PNG-bytes
* ``write_icon_files(dir)`` → skriver ledgebord.ico + ledgebord.png (256 px)

Små storlekar (<32 px) ritas förenklat (ett stort bockmärke) så ikonen är läsbar i aktivitetsfältet.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

RGBA = Tuple[float, float, float, float]
ICO_SIZES: Tuple[int, ...] = (16, 24, 32, 48, 64, 128, 256)

# Palett
BG_TOP = (91, 91, 240)
BG_BOTTOM = (42, 38, 112)
LEDGE_TOP = (252, 211, 77)
LEDGE_BOTTOM = (245, 158, 11)
CARD = (248, 250, 255)
INDIGO = (79, 70, 229)
LINE = (199, 203, 235)
LINE_DONE = (222, 225, 243)
BOX_EDGE = (140, 146, 200)
LEDGE_X = 0.18          # kantlistens bredd (andel av bredden)


def _rr(x: float, y: float, x0: float, y0: float, x1: float, y1: float, r: float) -> bool:
    """Punkt i rundad rektangel?"""
    if x < x0 or x > x1 or y < y0 or y > y1:
        return False
    cx = min(max(x, x0 + r), x1 - r)
    cy = min(max(y, y0 + r), y1 - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def _seg(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    vx, vy = bx - ax, by - ay
    wx, wy = px - ax, py - ay
    l2 = vx * vx + vy * vy
    t = 0.0 if l2 == 0 else max(0.0, min(1.0, (wx * vx + wy * vy) / l2))
    return ((px - (ax + t * vx)) ** 2 + (py - (ay + t * vy)) ** 2) ** 0.5


def _poly(px: float, py: float, pts: Sequence[Tuple[float, float]], half: float) -> bool:
    """Nära en bruten linje (rundade ändar)?"""
    return any(_seg(px, py, pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1]) <= half
               for i in range(len(pts) - 1))


def _mix(a: Sequence[float], b: Sequence[float], t: float) -> Tuple[float, float, float]:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def _over(dst: RGBA, rgb: Sequence[float], a: float) -> RGBA:
    """Lägg färg ``rgb`` med alfa ``a`` ovanpå ``dst`` (ej-premultiplicerad)."""
    da = dst[3]
    oa = a + da * (1.0 - a)
    if oa <= 0:
        return (0.0, 0.0, 0.0, 0.0)
    k = da * (1.0 - a)
    return ((rgb[0] * a + dst[0] * k) / oa, (rgb[1] * a + dst[1] * k) / oa,
            (rgb[2] * a + dst[2] * k) / oa, oa)


def make_sampler(size: int) -> Callable[[float, float], RGBA]:
    detail = size >= 32

    def sample(x: float, y: float) -> RGBA:
        px: RGBA = (0.0, 0.0, 0.0, 0.0)
        if not _rr(x, y, 0.03, 0.03, 0.97, 0.97, 0.21):
            return px
        # bakgrund (gradient uppifrån och ned)
        px = _over(px, _mix(BG_TOP, BG_BOTTOM, y), 1.0)
        # kantlisten längs vänsterkanten (klipps av den rundade bakgrunden)
        if x < LEDGE_X:
            px = _over(px, _mix(LEDGE_TOP, LEDGE_BOTTOM, y), 1.0)
        elif x < LEDGE_X + 0.022:
            px = _over(px, (25, 22, 70), 0.45)           # skugga mot listen
        # kortets skugga + kortet (glider ut från listen)
        if detail and _rr(x, y, 0.285, 0.225, 0.905, 0.825, 0.075):
            px = _over(px, (15, 12, 50), 0.38)
        if _rr(x, y, 0.27, 0.20, 0.89, 0.80, 0.075):
            px = _over(px, CARD, 1.0)
            if detail:
                for i, cy in enumerate((0.335, 0.50, 0.665)):
                    # rad: kryssruta + linje
                    if i == 0:
                        if _rr(x, y, 0.315, cy - 0.047, 0.409, cy + 0.047, 0.02):
                            px = _over(px, INDIGO, 1.0)
                        if _poly(x, y, ((0.335, cy), (0.357, cy + 0.022), (0.392, cy - 0.024)), 0.0105):
                            px = _over(px, (255, 255, 255), 1.0)
                    else:
                        if _rr(x, y, 0.315, cy - 0.047, 0.409, cy + 0.047, 0.02) and not _rr(
                                x, y, 0.329, cy - 0.033, 0.395, cy + 0.033, 0.012):
                            px = _over(px, BOX_EDGE, 1.0)
                    if _poly(x, y, ((0.455, cy), (0.80 if i != 2 else 0.70, cy)), 0.0185):
                        px = _over(px, LINE_DONE if i == 0 else LINE, 1.0)
            else:
                if _poly(x, y, ((0.405, 0.52), (0.52, 0.645), (0.775, 0.36)), 0.055):
                    px = _over(px, INDIGO, 1.0)
        return px

    return sample


def render(size: int, ss: Optional[int] = None) -> bytes:
    """RGBA-bytes för en ``size``×``size`` bild (rader uppifrån och ned)."""
    ss = ss or (4 if size <= 64 else 3)
    sample = make_sampler(size)
    out = bytearray()
    n = ss * ss
    inv = 1.0 / (size * ss)
    for j in range(size):
        for i in range(size):
            r = g = b = a = 0.0
            for sj in range(ss):
                y = (j * ss + sj + 0.5) * inv
                for si in range(ss):
                    pr, pg, pb, pa = sample((i * ss + si + 0.5) * inv, y)
                    r += pr * pa
                    g += pg * pa
                    b += pb * pa
                    a += pa
            if a <= 0:
                out += b"\x00\x00\x00\x00"
            else:
                out += bytes((int(r / a + 0.5), int(g / a + 0.5), int(b / a + 0.5), int(a / n * 255 + 0.5)))
    return bytes(out)


def build_png(size: int, rgba: Optional[bytes] = None) -> bytes:
    rgba = rgba if rgba is not None else render(size)

    def chunk(tag: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + rgba[y * size * 4:(y + 1) * size * 4] for y in range(size))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def _bmp_entry(size: int, rgba: bytes) -> bytes:
    """Klassisk ICO-post: BITMAPINFOHEADER + BGRA (nedifrån och upp) + AND-mask."""
    hdr = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    rows = []
    for y in range(size - 1, -1, -1):
        row = rgba[y * size * 4:(y + 1) * size * 4]
        bgra = bytearray(len(row))
        bgra[0::4], bgra[1::4], bgra[2::4], bgra[3::4] = row[2::4], row[1::4], row[0::4], row[3::4]
        rows.append(bytes(bgra))
    mask_row = b"\x00" * (((size + 31) // 32) * 4)
    return hdr + b"".join(rows) + mask_row * size


def build_ico(sizes: Sequence[int] = ICO_SIZES) -> bytes:
    """Flerstorleks-.ico: BMP-poster upp till 128 px, PNG-post för 256 px (Windows Vista+)."""
    entries: List[Tuple[int, bytes]] = []
    for s in sizes:
        rgba = render(s)
        entries.append((s, build_png(s, rgba) if s >= 256 else _bmp_entry(s, rgba)))
    head = struct.pack("<HHH", 0, 1, len(entries))
    offset = 6 + 16 * len(entries)
    table = b""
    blobs = b""
    for s, data in entries:
        table += struct.pack("<BBBBHHII", 0 if s >= 256 else s, 0 if s >= 256 else s, 0, 0, 1, 32,
                             len(data), offset + len(blobs))
        blobs += data
    return head + table + blobs


def write_icon_files(folder: Path, sizes: Sequence[int] = ICO_SIZES) -> Tuple[Path, Path]:
    """Skriver ``ledgebord.ico`` och ``ledgebord.png`` (256 px) i ``folder``."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    ico, png = folder / "ledgebord.ico", folder / "ledgebord.png"
    ico.write_bytes(build_ico(sizes))
    png.write_bytes(build_png(256))
    return ico, png


if __name__ == "__main__":  # python core/icon_art.py [målmapp]
    import sys
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "icon"
    a, b = write_icon_files(target)
    print(f"skrev {a} ({a.stat().st_size} B) och {b} ({b.stat().st_size} B)")
