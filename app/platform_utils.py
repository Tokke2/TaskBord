# -*- coding: utf-8 -*-
"""Plattforms- och startdetektering (.pyw, dubbelklick, pythonw.exe)."""

from __future__ import annotations

import os
import sys
from typing import Optional


# ===========================================================================
# PLATFORM HELPERS
# ===========================================================================

def _is_pyw() -> bool:
    """Returnerar True om vi kör via pythonw.exe (ingen konsoll)."""
    return (
        sys.executable.lower().endswith("pythonw.exe")
        or getattr(sys, "frozen", False)
        or not sys.stdout
    )


def _is_double_click_start() -> bool:
    """
    NY v6.4: Detekterar om appen startades via dubbelklick på .pyw (Windows).
    Returnerar True om vi är i pyw-läge OCH startades utan argument.

    Detta används för att:
      - Visa tydligare startlog
      - Inte kräva python.exe-argument
      - Logga explicit att vi startades via filhanteraren
    """
    if not _is_pyw():
        return False
    # Om inga argument → dubbelklick-start (default)
    return len(sys.argv) <= 1 or (len(sys.argv) == 1 and sys.argv[0].endswith(".pyw"))


def _is_windows() -> bool:
    """Returnerar True om plattformen är Windows."""
    return sys.platform == "win32"


def _find_pythonw_exe() -> Optional[str]:
    """Hittar pythonw.exe bredvid python.exe (för double-click-start)."""
    if sys.executable.lower().endswith("pythonw.exe"):
        return sys.executable
    if getattr(sys, "frozen", False):
        return sys.executable
    base_dir = os.path.dirname(sys.executable)
    for name in ("pythonw.exe", "pythonw"):
        candidate = os.path.join(base_dir, name)
        if os.path.exists(candidate):
            return candidate
    return None
