# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""
skapa_ikoner.py — bygger om tilläggets ikoner (icon-16/32/48/64/128.png) från appens ikonmall.

Körs med:  python skapa_ikoner.py      (kräver Pillow: pip install pillow)

Ikonerna skalas ur ``icon/ledgebord-master.png`` — samma bild som appens ikon. Skriptet kör ``icon/bygg_ikoner.py``,
som samtidigt bygger om appens ``.ico``/``.png`` och README-bilderna så att allt hänger ihop.
Efter en ändring: kör ``SKAPA_XPI.bat`` så hamnar de nya ikonerna i ``Ledgebord-Thunderbird.xpi``.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "icon"))


def main() -> int:
    try:
        import bygg_ikoner
    except ModuleNotFoundError as e:
        print(f"Saknar ett paket ({e.name}). Installera med:  pip install pillow")
        return 1
    return bygg_ikoner.main([])


if __name__ == "__main__":
    sys.exit(main())
