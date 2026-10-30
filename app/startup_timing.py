# -*- coding: utf-8 -*-
"""
Startmätning + fördröjd autostart (ren stdlib — importeras FÖRST av main.pyw, före Qt).

* ``wait_for_autostart()`` — när appen startas med datorn (``--autostart``) väntar den ~45 s innan något tungt
  laddas, så att inloggningen/skrivbordet/nätverket hinner bli klara och datorn känns snabb. Bara vid riktig
  datorstart (uptime < 20 min); annars en kort paus (8 s). Manuell start (utan flaggan) väntar aldrig.
  ``LEDGEBORD_AUTOSTART_DELAY=<sekunder>`` ändrar tiden (0 = ingen fördröjning).
* ``mark(namn)`` / ``summary()`` / ``record(data_dir)`` — mäter tiden från processstart till första händelseloopen,
  loggas och sparas (senaste 30 starterna) i ``data/startup_times.json`` i appmappen.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

AUTOSTART_FLAG = "--autostart"
AUTOSTART_DELAY_SEC = 45.0         # extra väntan efter inloggning vid datorstart
AUTOSTART_DELAY_LATE_SEC = 8.0     # appen startas med --autostart men datorn har kört länge
FRESH_BOOT_UPTIME_SEC = 20 * 60
MAX_DELAY_SEC = 600.0
KEEP_RUNS = 30
ENV_DELAY = "LEDGEBORD_AUTOSTART_DELAY"

_t0 = time.perf_counter()
_marks: List[Tuple[str, float]] = []
_waited = 0.0


def _reset() -> None:
    global _t0
    _t0 = time.perf_counter()
    _marks.clear()


def system_uptime_sec() -> Optional[float]:
    """Sekunder sedan datorn startade (None om det inte går att läsa)."""
    try:
        if sys.platform == "win32":
            import ctypes
            k32 = ctypes.windll.kernel32
            k32.GetTickCount64.restype = ctypes.c_uint64
            return float(k32.GetTickCount64()) / 1000.0
        with open("/proc/uptime", "r", encoding="ascii") as f:
            return float(f.read().split()[0])
    except Exception:  # noqa: BLE001
        return None


def autostart_delay_sec(argv: Optional[List[str]] = None, env: Optional[Dict[str, str]] = None,
                        uptime: Optional[float] = None) -> float:
    """Hur länge ska appen vänta innan den startar på riktigt? 0 = inte alls."""
    argv = sys.argv if argv is None else argv
    env = os.environ if env is None else env
    if AUTOSTART_FLAG not in argv:
        return 0.0
    raw = str(env.get(ENV_DELAY, "")).strip()
    if raw:
        try:
            return max(0.0, min(float(raw.replace(",", ".")), MAX_DELAY_SEC))
        except ValueError:
            pass
    up = system_uptime_sec() if uptime is None else uptime
    if up is not None and up >= FRESH_BOOT_UPTIME_SEC:
        return AUTOSTART_DELAY_LATE_SEC
    return AUTOSTART_DELAY_SEC


def wait_for_autostart(argv: Optional[List[str]] = None, sleep: Callable[[float], None] = time.sleep,
                       env: Optional[Dict[str, str]] = None, uptime: Optional[float] = None) -> float:
    """Väntar ut fördröjningen (om --autostart). Returnerar väntad tid i sekunder. Nollställer mätklockan."""
    global _waited
    delay = autostart_delay_sec(argv, env, uptime)
    left = delay
    while left > 0:
        step = min(1.0, left)
        sleep(step)
        left -= step
    _waited = delay
    _reset()
    return delay


def mark(name: str) -> float:
    """Sparar en tidpunkt (sekunder sedan start) och returnerar den."""
    t = time.perf_counter() - _t0
    _marks.append((name, t))
    return t


def marks() -> List[Tuple[str, float]]:
    return list(_marks)


def summary() -> str:
    """'Start 2.31 s: importer 0.80 → beroenden 1.10 (+0.30) → …'."""
    if not _marks:
        return "Start: inga mätpunkter"
    parts, prev = [], 0.0
    for name, t in _marks:
        parts.append(f"{name} {t:.2f}s (+{t - prev:.2f})")
        prev = t
    return f"Start {_marks[-1][1]:.2f} s: " + " → ".join(parts)


def slowest() -> Tuple[str, float]:
    """(namn, sekunder) på det långsammaste steget."""
    best, prev = ("", 0.0), 0.0
    for name, t in _marks:
        if t - prev > best[1]:
            best = (name, t - prev)
        prev = t
    return best


def record(data_dir: Path, autostart: bool = False) -> Optional[Path]:
    """Lägger till den här starten i ``startup_times.json`` (appmappen). Returnerar filen, eller None vid fel."""
    try:
        p = Path(data_dir) / "startup_times.json"
        runs = []
        try:
            runs = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(runs, list):
                runs = []
        except Exception:  # noqa: BLE001
            runs = []
        prev = 0.0
        steps: Dict[str, float] = {}
        for name, t in _marks:
            steps[name] = round(t - prev, 3)
            prev = t
        runs.append({
            "tid": datetime.now().isoformat(timespec="seconds"),
            "totalt_s": round(_marks[-1][1], 3) if _marks else 0.0,
            "steg_s": steps,
            "autostart": bool(autostart),
            "fördröjning_s": round(_waited, 1),
        })
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(runs[-KEEP_RUNS:], ensure_ascii=False, indent=1), encoding="utf-8")
        return p
    except Exception:  # noqa: BLE001
        return None
