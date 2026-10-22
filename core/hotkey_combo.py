# -*- coding: utf-8 -*-
"""
Snabbtangent-kombinationer: tolka, normalisera och validera.

Ren Python (ingen Qt, inget Windows-API) så att allt går att testa överallt.
Används av ``app.config`` (re-export av ``parse_hotkey_combo``), av tray-
dialogen och av ``ui/hotkey_dialog.py``.
"""

from __future__ import annotations

from typing import Iterable, Tuple

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008

DEFAULT_QUICK_ADD = "Ctrl+Alt+N"

# Kombinationer Windows/de flesta program redan använder — att ta över dem
# gör vardagen sämre.
RESERVED = frozenset({
    "alt+f4", "alt+tab", "alt+space", "alt+enter",
    "ctrl+alt+tab", "win+l", "win+d", "win+e", "win+r", "win+tab",
    "ctrl+shift+enter",
})


def parse_hotkey_combo(combo: str) -> Tuple[int, int]:
    """
    Tolka 'Ctrl+Alt+V' → (mod-flaggor, vk-kod).

    Returnerar (0, 0) vid ogiltig kombination.
    Stöd: Ctrl/Control, Alt, Shift, Win + A-Z, 0-9, F1-F12,
    Space, Enter, Tab.
    """
    try:
        mods = 0
        vk = 0
        parts = [
            p.strip().lower() for p in str(combo).split("+") if p.strip()
        ]
        if not parts:
            return (0, 0)
        for part in parts:
            if part in ("ctrl", "control"):
                mods |= MOD_CONTROL
            elif part == "alt":
                mods |= MOD_ALT
            elif part == "shift":
                mods |= MOD_SHIFT
            elif part in ("win", "super", "meta"):
                mods |= MOD_WIN
            elif len(part) == 1 and "a" <= part <= "z":
                vk = ord(part.upper())  # 0x41-0x5A
            elif len(part) == 1 and "0" <= part <= "9":
                vk = ord(part)  # 0x30-0x39
            elif part == "space":
                vk = 0x20
            elif part in ("enter", "return"):
                vk = 0x0D
            elif part == "tab":
                vk = 0x09
            elif len(part) in (2, 3) and part[0] == "f" and part[1:].isdigit():
                n = int(part[1:])
                if 1 <= n <= 12:
                    vk = 0x70 + (n - 1)
                else:
                    return (0, 0)
            else:
                return (0, 0)
        if vk == 0:
            return (0, 0)  # Ingen huvudtangent
        return (mods, vk)
    except Exception:
        return (0, 0)


def normalize_combo(text: str) -> str:
    """
    'ctrl + alt+n' / 'Meta+N' → 'Ctrl+Alt+N' (fast ordning, Win för Meta).

    Returnerar '' om kombinationen inte går att tolka.
    """
    mods, vk = parse_hotkey_combo(str(text or "").replace(" ", ""))
    if not vk:
        return ""
    parts = []
    if mods & MOD_CONTROL:
        parts.append("Ctrl")
    if mods & MOD_ALT:
        parts.append("Alt")
    if mods & MOD_SHIFT:
        parts.append("Shift")
    if mods & MOD_WIN:
        parts.append("Win")
    if 0x41 <= vk <= 0x5A or 0x30 <= vk <= 0x39:
        key = chr(vk)
    elif vk == 0x20:
        key = "Space"
    elif vk == 0x0D:
        key = "Enter"
    elif vk == 0x09:
        key = "Tab"
    else:
        key = f"F{vk - 0x70 + 1}"
    parts.append(key)
    return "+".join(parts)


def qt_to_combo(qt_text: str) -> str:
    """Qt:s ``QKeySequence.toString()`` ('Meta+N', 'Ctrl+Return') → vårt format."""
    text = str(qt_text or "").strip()
    if "," in text:
        # Ackord (flera tangenter i följd) stöds inte — ta första tangenten
        text = text.split(",")[0]
    return normalize_combo(text)


def validate_global_combo(
    text: str, taken: Iterable[str] = ()
) -> Tuple[bool, str]:
    """
    Duger kombinationen som GLOBAL snabbtangent?  → (ok, förklaring).

    Krav: går att tolka, har Win eller minst två modifierare (annars
    blockeras vanlig skrivning/vanliga genvägar i alla program), är inte
    en reserverad Windows-kombination och krockar inte med ``taken``.
    """
    combo = normalize_combo(text)
    if not combo:
        return False, "Tryck en kombination med en vanlig tangent (A–Z, 0–9, F1–F12, Space, Enter, Tab)."
    mods, _vk = parse_hotkey_combo(combo)
    n_mods = sum(1 for m in (MOD_CONTROL, MOD_ALT, MOD_SHIFT, MOD_WIN) if mods & m)
    if not (mods & MOD_WIN) and n_mods < 2:
        return False, (
            "Använd minst två av Ctrl / Alt / Shift (eller Win) — "
            "annars skulle tangenten sluta fungera i alla andra program."
        )
    if combo.lower() in RESERVED:
        return False, f"{combo} används av Windows — välj en annan."
    for other in taken:
        if other and normalize_combo(other).lower() == combo.lower():
            return False, f"{combo} används redan av en annan snabbtangent i Ledgebord."
    return True, ""
