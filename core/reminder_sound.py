# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""
reminder_sound.py — påminnelseljud som skapas lokalt (ren Python, ingen Qt, inga filer i repot).

``chime`` (två ljusa toner) · ``bell`` (klocka) · ``gentle`` (mjukt ackord) · ``none`` (tyst).
WAV-filerna genereras första gången de behövs och sparas i appens datamapp (``<datamapp>/sounds/``) — inget
skrivs utanför appmappen.
"""
from __future__ import annotations

import io
import math
import struct
import wave
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

RATE = 22050
LABELS: Dict[str, str] = {"none": "Inget ljud", "chime": "🔔 Pling", "bell": "🛎 Klocka", "gentle": "🎵 Mjukt"}


def _tone(freq: float, dur: float, vol: float, decay: float, partials: Tuple[Tuple[float, float], ...] = ((1.0, 1.0),)) -> List[float]:
    n = int(RATE * dur)
    out = []
    norm = sum(a for _m, a in partials) or 1.0
    for i in range(n):
        t = i / RATE
        env = math.exp(-decay * t) * min(1.0, t / 0.005)           # mjuk start (5 ms) → inget klick
        v = sum(a * math.sin(2 * math.pi * freq * m * t) for m, a in partials) / norm
        out.append(vol * env * v)
    return out


def _mix(parts: List[Tuple[float, List[float]]]) -> List[float]:
    """[(startsekund, samples)] → en lista samples."""
    end = max(int(s * RATE) + len(x) for s, x in parts)
    buf = [0.0] * end
    for s, x in parts:
        o = int(s * RATE)
        for i, v in enumerate(x):
            buf[o + i] += v
    return buf


def samples(name: str) -> List[float]:
    if name == "chime":
        return _mix([(0.0, _tone(1318.5, 0.45, 0.55, 7.0)), (0.18, _tone(1760.0, 0.6, 0.55, 6.0))])
    if name == "bell":
        return _mix([(0.0, _tone(880.0, 1.4, 0.7, 3.2, ((1.0, 1.0), (2.0, 0.5), (2.76, 0.35), (5.4, 0.15))))])
    if name == "gentle":
        return _mix([(0.0, _tone(523.25, 0.7, 0.35, 4.0)), (0.16, _tone(659.25, 0.7, 0.35, 4.0)),
                     (0.32, _tone(783.99, 0.9, 0.35, 3.5))])
    return []


def wav_bytes(name: str) -> bytes:
    """WAV (16 bit, mono) för ljudet — b'' för 'none'/okänt."""
    smp = samples(name)
    if not smp:
        return b""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", max(-32767, min(32767, int(v * 32767)))) for v in smp))
    return buf.getvalue()


def ensure_file(data_dir: Union[str, Path], name: str) -> Optional[Path]:
    """Skriv ljudfilen till ``<datamapp>/sounds/<namn>.wav`` om den saknas. None för 'none' eller vid fel."""
    if name not in ("chime", "bell", "gentle"):
        return None
    try:
        d = Path(data_dir) / "sounds"
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{name}.wav"
        if not p.is_file() or p.stat().st_size < 1000:
            tmp = p.with_suffix(".tmp")
            tmp.write_bytes(wav_bytes(name))
            tmp.replace(p)
        return p
    except OSError:
        return None
