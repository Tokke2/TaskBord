# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""
power.py — energisnål och minnessnål när fönstret inte syns (gömt i tray, dockat i skärmkanten, minimerat).

* ``plan(...)``            — ren beslutsfunktion (testas utan Windows): när ska energisparläget slå på, och när ska minnet städas?
* ``set_eco_mode(on)``     — Windows 10/11: *effektivitetsläge* (EcoQoS) för processen. Windows kör då Ledgebords trådar på de
                             sparsamma kärnorna med låg frekvens (samma som "Effektivitetsläge" i Aktivitetshanteraren).
                             Inget annat Windows-läge ändras — varken DPI eller prioritetsklass. Andra system: gör ingenting.
* ``trim_memory()``        — Pythons skräpsamling + Windows ``EmptyWorkingSet`` (släpper sidor som inte behövs medan fönstret är
                             gömt; de läses in igen vid behov). Siffran i Aktivitetshanteraren sjunker tydligt.

Allt är best-effort: ett fel loggas på debug-nivå och påverkar aldrig appen.
"""
from __future__ import annotations

import gc
import logging
import sys
from typing import Any, Dict, Optional

logger = logging.getLogger("Ledgebord")
LOG_PREFIX = "[ENERGI]"

HIDDEN_GRACE_S = 45.0          # fönstret måste ha varit osynligt så här länge innan vi sparar (undvik fram-och-tillbaka)
TRIM_EVERY_S = 20 * 60.0       # därefter städas minnet högst var 20:e minut medan fönstret är gömt

_eco_on = False


def plan(visible: bool, hidden_for_s: float, since_trim_s: Optional[float], enabled: bool = True) -> Dict[str, Any]:
    """Beslut: {"eco": bool, "trim": bool}.

    * Fönstret syns (eller funktionen är av) → inget sparläge, ingen städning.
    * Osynligt kortare än HIDDEN_GRACE_S → ännu inget (användaren kanske bara tittar förbi).
    * Osynligt längre → sparläge. Minnet städas första gången direkt när sparläget börjar (since_trim_s=None) och
      därefter högst var TRIM_EVERY_S.
    """
    if not enabled or visible or hidden_for_s < HIDDEN_GRACE_S:
        return {"eco": False, "trim": False}
    trim = since_trim_s is None or since_trim_s >= TRIM_EVERY_S
    return {"eco": True, "trim": bool(trim)}


def _win_ctypes():
    import ctypes
    from ctypes import wintypes
    return ctypes, wintypes


def set_eco_mode(on: bool) -> bool:
    """Slå effektivitetsläget (EcoQoS) på/av. True om Windows tog emot ändringen."""
    global _eco_on
    if sys.platform != "win32":
        return False
    try:
        ctypes, wintypes = _win_ctypes()

        class PROCESS_POWER_THROTTLING_STATE(ctypes.Structure):
            _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG), ("StateMask", wintypes.ULONG)]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.SetProcessInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.SetProcessInformation.restype = wintypes.BOOL
        st = PROCESS_POWER_THROTTLING_STATE(1, 0x1, 0x1 if on else 0x0)    # PROCESS_POWER_THROTTLING_EXECUTION_SPEED
        ok = bool(k32.SetProcessInformation(k32.GetCurrentProcess(), 4, ctypes.byref(st), ctypes.sizeof(st)))  # ProcessPowerThrottling
        if ok:
            _eco_on = bool(on)
        return ok
    except Exception as e:  # noqa: BLE001
        logger.debug(f"{LOG_PREFIX} set_eco_mode({on}): {e}")
        return False


def eco_mode_on() -> bool:
    return _eco_on


def memory_mb() -> Optional[float]:
    """Processens minne (arbetsset) i MB, eller None om psutil saknas."""
    try:
        import psutil
        return psutil.Process().memory_info().rss / 1e6
    except Exception:
        return None


def trim_memory() -> Dict[str, Any]:
    """Skräpsamling + (Windows) släpp arbetsset. Returnerar {"before": MB, "after": MB, "collected": n}."""
    before = memory_mb()
    n = 0
    try:
        n = gc.collect()
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            ctypes, wintypes = _win_ctypes()
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.GetCurrentProcess.restype = wintypes.HANDLE
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            psapi.EmptyWorkingSet.argtypes = [wintypes.HANDLE]
            psapi.EmptyWorkingSet.restype = wintypes.BOOL
            psapi.EmptyWorkingSet(k32.GetCurrentProcess())
        except Exception as e:  # noqa: BLE001
            logger.debug(f"{LOG_PREFIX} EmptyWorkingSet: {e}")
    return {"before": before, "after": memory_mb(), "collected": n}
