# -*- coding: utf-8 -*-
"""
skapa_ikoner.py — genererar tilläggets ikoner (PNG) utan externa paket.

Körs med:  python skapa_ikoner.py
Skapar:    icon-16.png, icon-32.png, icon-48.png, icon-64.png, icon-128.png
           (samma Ledgebord-ikon som appen: indigo ruta, gul kantlist och ett bockat uppgiftskort)

Ritningen ligger i core/icon_art.py (ren stdlib: zlib + struct) — fungerar på alla plattformar.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from core import icon_art  # noqa: E402


def main() -> None:
    print("Skapar Ledgebord-tilläggets ikoner…")
    for size in (16, 32, 48, 64, 128):
        (HERE / f"icon-{size}.png").write_bytes(icon_art.build_png(size))
        print(f"  icon-{size}.png")


if __name__ == "__main__":
    main()
