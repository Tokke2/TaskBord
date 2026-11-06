# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""
bygg_ikoner.py — bygger ALLA Ledgebords ikoner och README-bilder från en enda mallbild (utvecklarverktyg, kräver Pillow).

    pip install pillow
    python icon/bygg_ikoner.py                      # bygger allt från icon/ledgebord-master.png

Mallbilden ``icon/ledgebord-master.png`` är en kvadratisk PNG (1024 px, rundade hörn, genomskinliga hörn). Ny mall från
en vanlig bild:  python icon/bygg_ikoner.py --ny-mall bild.png [--mitt X,Y --storlek N]

Skriver:
  icon/ledgebord.ico + icon/ledgebord.png        appens ikon (fönster, tray, aktivitetsfält, genvägar, autostart)
  thunderbird-tillagg/icons/icon-16…128.png      Thunderbird-tilläggets ikoner
  docs/img/ikon.png, docs/img/banner.png         logotypen i README

Själva appen behöver inte Pillow: ikonfilerna ligger färdiga i repot (och ``core/icon_art.py`` ritar en reservikon
om filen skulle saknas).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
MASTER = ROOT / "icon" / "ledgebord-master.png"
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
ADDON_SIZES = (16, 32, 48, 64, 128)
FONT_BOLD = ("DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "seguisb.ttf", "arialbd.ttf")
FONT_REG = ("DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "segoeui.ttf", "arial.ttf")


def _font(names, size):
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def make_master(src: Path, out: Path, center=None, size=None, radius=0.22) -> None:
    """Beskär en kvadrat ur ``src`` och rundar hörnen → 1024 px mall."""
    im = Image.open(src).convert("RGB")
    w, h = im.size
    size = size or min(w, h)
    cx, cy = center or (w // 2, h // 2)
    box = (cx - size // 2, cy - size // 2, cx + size // 2, cy + size // 2)
    sq = im.crop(box).resize((1024, 1024), Image.LANCZOS)
    mask = Image.new("L", sq.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, 1023, 1023), int(1024 * radius), fill=255)
    out_im = sq.convert("RGBA")
    out_im.putalpha(mask)
    out_im.save(out, optimize=True)


def sized(master: Image.Image, s: int) -> Image.Image:
    im = master.resize((s, s), Image.LANCZOS)
    if s <= 48:   # små storlekar: lite skärpa så att kanterna inte flyter ut
        im = im.filter(ImageFilter.UnsharpMask(radius=0.6, percent=80, threshold=0))
    return im


def build_ico(master: Image.Image, sizes=ICO_SIZES) -> bytes:
    """Samma ICO-uppbyggnad som core/icon_art.py: BMP-poster ≤128 px, PNG-post för 256 px (fungerar med LoadImage)."""
    sys.path.insert(0, str(ROOT))
    import struct
    from core import icon_art
    entries = []
    for s in sizes:
        rgba = sized(master, s).tobytes()
        entries.append((s, icon_art.build_png(s, rgba) if s >= 256 else icon_art._bmp_entry(s, rgba)))
    head = struct.pack("<HHH", 0, 1, len(entries))
    offset = 6 + 16 * len(entries)
    table = b""
    blobs = b""
    for s, data in entries:
        table += struct.pack("<BBBBHHII", 0 if s >= 256 else s, 0 if s >= 256 else s, 0, 0, 1, 32, len(data), offset + len(blobs))
        blobs += data
    return head + table + blobs


def banner(master: Image.Image, w: int = 1280, h: int = 320) -> Image.Image:
    """README-banner: indigo → violett, ikonen till vänster, namn + en rad text."""
    bg = Image.new("RGB", (w, h))
    px = bg.load()
    top, bot = (30, 27, 90), (88, 52, 190)
    for x in range(w):
        for y in range(h):
            t = (x / w) * 0.75 + (y / h) * 0.25
            px[x, y] = tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3))
    d = ImageDraw.Draw(bg)
    # mjuk dekorcirkel till höger
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((w - 520, -160, w + 160, 520), fill=(167, 139, 250, 55))
    bg = Image.alpha_composite(bg.convert("RGBA"), glow)
    ic = master.resize((200, 200), Image.LANCZOS)
    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((86, 74, 286, 274), 44, fill=(0, 0, 0, 90))
    bg = Image.alpha_composite(bg, shadow.filter(ImageFilter.GaussianBlur(14)))
    bg.paste(ic, (80, 60), ic)
    d = ImageDraw.Draw(bg)
    d.text((330, 78), "Ledgebord", font=_font(FONT_BOLD, 92), fill=(255, 255, 255))
    d.rectangle((334, 196, 394, 202), fill=(252, 211, 77))
    d.text((332, 214), "Uppgiftslistan som ligger på skrivbordet", font=_font(FONT_REG, 34), fill=(224, 220, 255))
    return bg.convert("RGB")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--ny-mall", metavar="BILD", help="gör en ny mall (icon/ledgebord-master.png) av en vanlig bild")
    ap.add_argument("--mitt", metavar="X,Y", help="mittpunkt för beskärningen (pixlar)")
    ap.add_argument("--storlek", type=int, help="beskärningens sidlängd (pixlar)")
    a = ap.parse_args(argv)
    if a.ny_mall:
        c = tuple(int(v) for v in a.mitt.split(",")) if a.mitt else None
        make_master(Path(a.ny_mall), MASTER, c, a.storlek)
        print("skrev", MASTER)
    master = Image.open(MASTER).convert("RGBA")
    (ROOT / "icon" / "ledgebord.ico").write_bytes(build_ico(master))
    sized(master, 256).save(ROOT / "icon" / "ledgebord.png", optimize=True)
    for s in ADDON_SIZES:
        sized(master, s).save(ROOT / "thunderbird-tillagg" / "icons" / f"icon-{s}.png", optimize=True)
    img = ROOT / "docs" / "img"
    img.mkdir(parents=True, exist_ok=True)
    sized(master, 256).save(img / "ikon.png", optimize=True)
    banner(master).save(img / "banner.png", optimize=True)
    print("klart: icon/ledgebord.ico, icon/ledgebord.png, thunderbird-tillagg/icons/*, docs/img/ikon.png, docs/img/banner.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
