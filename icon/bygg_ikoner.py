# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""
bygg_ikoner.py — bygger ALLA Ledgebords ikoner, logotyper och README-bilder från vektorritningen i icon/ledgebord_svg.py
(utvecklarverktyg).

    pip install pillow resvg-py
    python icon/bygg_ikoner.py

Skriver:
  logotyp/Ledgebord-logotyp.zip (+ SVG/, PNG/)   logotyper som vektor-SVG för tryck + PNG. Mappen ligger i .gitignore:
                                                 filerna laddas upp på GitHub-releasen, de ingår inte i appen
  icon/ledgebord.ico + icon/ledgebord.png        appens ikon (fönster, tray, aktivitetsfält, genvägar, autostart)
  thunderbird-tillagg/icons/icon-16…128.png      Thunderbird-tilläggets ikoner
  docs/img/ikon.png, docs/img/banner.png         logotypen i README

Varje storlek ritas direkt från vektorn (inte nedskalad); 16–64 px använder en förenklad, grövre variant så att raderna
syns i aktivitetsfältet. Själva appen behöver varken Pillow eller resvg: filerna ligger färdiga i repot (och
``core/icon_art.py`` ritar en reservikon om ikonfilen skulle saknas).
"""
from __future__ import annotations

import io
import struct
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

import resvg_py

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "icon"))
import ledgebord_svg as S  # noqa: E402
from core import icon_art  # noqa: E402

ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
ADDON_SIZES = (16, 32, 48, 64, 128)
FONT_BOLD = ("DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "seguisb.ttf", "arialbd.ttf")
FONT_REG = ("DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "segoeui.ttf", "arial.ttf")
SMALL_MAX = 64    # upp till så här många px används den förenklade ikonen


def _font(names, size):
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def raster(svg: str, width: int) -> Image.Image:
    """Ritar en SVG-sträng till en RGBA-bild med given bredd (genomskinlig bakgrund)."""
    data = bytes(resvg_py.svg_to_bytes(svg_string=svg, width=width))
    return Image.open(io.BytesIO(data)).convert("RGBA")


def sized(s: int) -> Image.Image:
    return raster(S.ikon(liten=s <= SMALL_MAX), s)


def build_ico(sizes=ICO_SIZES) -> bytes:
    """Samma ICO-uppbyggnad som core/icon_art.py: BMP-poster ≤128 px, PNG-post för 256 px (fungerar med LoadImage)."""
    entries = []
    for s in sizes:
        rgba = sized(s).tobytes()
        entries.append((s, icon_art.build_png(s, rgba) if s >= 256 else icon_art._bmp_entry(s, rgba)))
    head = struct.pack("<HHH", 0, 1, len(entries))
    offset = 6 + 16 * len(entries)
    table = b""
    blobs = b""
    for s, data in entries:
        table += struct.pack("<BBBBHHII", 0 if s >= 256 else s, 0 if s >= 256 else s, 0, 0, 1, 32, len(data), offset + len(blobs))
        blobs += data
    return head + table + blobs


LASMIG = """Ledgebord — logotyp för tryck
===============================

SVG/      vektorfiler (skalbara utan kvalitetsförlust) — använd dessa för tryck, skyltar, tröjor, broderi m.m.
PNG/      samma som genomskinliga PNG (ikon 1024 px, logotyper 3000 px) för skärm och dokument.

ledgebord-ikon          appikonen (rundad ruta)          -svart / -vit = enfärgat tryck / mörk botten
ledgebord-logo          ikon + ordet "Ledgebord", liggande
ledgebord-logo-stapel   ikonen över ordet

Filerna är rena former och toningar: inga filter, inga bilder och ingen typsnittsfil — ordet "Ledgebord" är omritat
till banor (Inter ExtraBold, SIL Open Font License 1.1, (c) The Inter Project Authors).
Färger (RGB): indigo #4F46E5, violett #7C3AED, mörk indigo #2A2370, gul #FBBF24 / #F59E0B, vit #FFFFFF.
För CMYK-tryck: öppna SVG:n i Inkscape/Illustrator och konvertera till tryckeriets färgprofil.

Copyright (c) Rickard Langkvist, 2025-2026. Licens: MIT (se LICENSE i projektet).
"""


def write_logotyp(out: Path) -> list:
    """Skriver logotyperna (SVG + PNG) och ``Ledgebord-logotyp.zip`` i ``out``. Mappen ligger INTE i git: zip-filen och
    de två viktigaste SVG:erna laddas upp som filer på GitHub-releasen (se docs/MANUAL.md)."""
    import zipfile
    (out / "SVG").mkdir(parents=True, exist_ok=True)
    (out / "PNG").mkdir(parents=True, exist_ok=True)
    files = S.alla()
    for name, svg in files.items():
        (out / "SVG" / f"{name}.svg").write_text(svg, encoding="utf-8")
        raster(svg, 1024 if "ikon" in name else 3000).save(out / "PNG" / f"{name}.png", optimize=True)
    (out / "LASMIG.txt").write_text(LASMIG, encoding="utf-8")
    zp = out / "Ledgebord-logotyp.zip"
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(out / "LASMIG.txt", "LASMIG.txt")
        for sub in ("SVG", "PNG"):
            for f in sorted((out / sub).iterdir()):
                z.write(f, f"{sub}/{f.name}")
    return sorted(files)


def banner(w: int = 1280, h: int = 320) -> Image.Image:
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
    ic = raster(S.ikon(), 200)
    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((86, 74, 286, 274), 44, fill=(0, 0, 0, 90))
    bg = Image.alpha_composite(bg, shadow.filter(ImageFilter.GaussianBlur(14)))
    bg.paste(ic, (80, 60), ic)
    d = ImageDraw.Draw(bg)
    sc = 0.05    # samma omritade ord som i logotypen (Inter ExtraBold)
    ww, wh = int(S.WORD_ADV * sc) + 4, 150
    word = raster(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {ww} {wh}" width="{ww}" height="{wh}">'
                  f'<path transform="translate(0 {1490 * sc + 6:.1f}) scale({sc})" fill="#FFFFFF" d="{S.WORD_PATH}"/></svg>', ww)
    bg.paste(word, (330, 70), word)
    d = ImageDraw.Draw(bg)
    d.rectangle((334, 196, 394, 202), fill=(252, 211, 77))
    d.text((332, 214), "Uppgiftslistan som ligger på skrivbordet", font=_font(FONT_REG, 34), fill=(224, 220, 255))
    return bg.convert("RGB")


def main(argv=None) -> int:
    names = write_logotyp(ROOT / "logotyp")
    (ROOT / "icon" / "ledgebord.ico").write_bytes(build_ico())
    sized(256).save(ROOT / "icon" / "ledgebord.png", optimize=True)
    for s_ in ADDON_SIZES:
        sized(s_).save(ROOT / "thunderbird-tillagg" / "icons" / f"icon-{s_}.png", optimize=True)
    img = ROOT / "docs" / "img"
    img.mkdir(parents=True, exist_ok=True)
    sized(256).save(img / "ikon.png", optimize=True)
    banner().save(img / "banner.png", optimize=True)
    print(f"klart: {len(names)} logotyper + Ledgebord-logotyp.zip i logotyp/ (inte i git — ladda upp på releasen), icon/ledgebord.ico + .png, thunderbird-tillagg/icons/*, docs/img/*")
    return 0


if __name__ == "__main__":
    sys.exit(main())
