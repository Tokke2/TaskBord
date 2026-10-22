# -*- coding: utf-8 -*-
"""
skapa_xpi.py — bygger Thunderbird-tillägget till en .xpi-fil.

Kör:   python skapa_xpi.py            (från appmappen)
       python thunderbird-tillagg/../skapa_xpi.py
Ger:   Ledgebord-Thunderbird.xpi   (installeras i Thunderbird via
                                    Verktyg → Tillägg → kugghjulet →
                                    "Installera tillägg från fil…")

Ren stdlib (zipfile) — inga beroenden. Manifest.json hamnar i roten av
arkivet, vilket Thunderbird kräver.
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ADDON_DIR = ROOT / "thunderbird-tillagg"
OUTPUT = ROOT / "Ledgebord-Thunderbird.xpi"

SKIP_DIRS = {"tester", "__pycache__", ".git"}
SKIP_FILES = {".DS_Store", "Thumbs.db"}


def main() -> int:
    if not (ADDON_DIR / "manifest.json").is_file():
        print(f"[FEL] Hittar inte {ADDON_DIR / 'manifest.json'}")
        return 1

    try:
        manifest = json.loads(
            (ADDON_DIR / "manifest.json").read_text(encoding="utf-8")
        )
    except Exception as e:
        print(f"[FEL] manifest.json är inte giltig JSON: {e}")
        return 1

    files = []
    for path in sorted(ADDON_DIR.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(ADDON_DIR)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if path.name in SKIP_FILES:
            continue
        files.append((path, rel))

    if OUTPUT.exists():
        OUTPUT.unlink()

    with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, rel in files:
            zf.write(path, str(rel).replace("\\", "/"))

    size_kb = OUTPUT.stat().st_size / 1024
    print("=" * 62)
    print("  Ledgebord — Thunderbird-tillägg packat")
    print("=" * 62)
    print(f"  Namn:     {manifest.get('name')} v{manifest.get('version')}")
    print(f"  Fil:      {OUTPUT}")
    print(f"  Filer:    {len(files)} ({size_kb:.1f} kB)")
    print()
    print("  Installera i Thunderbird:")
    print("    1. Verktyg → Tillägg och teman")
    print("    2. Kugghjulet ⚙️ → Installera tillägg från fil…")
    print(f"    3. Välj {OUTPUT.name}")
    print("    4. Inställningar → klistra in JSON från Ledgebord")
    print("       (Ledgebord: tray → 📧 E-post & Thunderbird →")
    print("        📋 Kopiera inställningar för Thunderbird)")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
