"""
clip_capture.py — "Lägg till från urklipp": markerad text i ett annat program blir en uppgift.

Flöde (anropas när den globala snabbtangenten trycks):
  1. Släpp de modifierartangenter användaren håller (Ctrl/Alt/Shift/Win) med SendInput, annars
     skulle det vi skickar bli Ctrl+Alt+C i stället för Ctrl+C.
  2. Skicka Ctrl+C till fönstret som har fokus.
  3. Vänta (icke-blockerande, via en timer) tills ``GetClipboardSequenceNumber`` ändrats.
  4. Ändrades inget (inget markerat) används det som redan ligger i urklippet.
  5. Det som låg i urklippet innan återställs.

Allt Windows-specifikt går via ett injicerbart ``user32``-objekt så att logiken kan testas utan
Windows. ``split_text`` (rubrik + anteckning) är ren logik.
"""
from __future__ import annotations

import ctypes
import logging
import time
from typing import Any, Callable, List, Optional, Tuple

logger = logging.getLogger("TaskBord")

DEFAULT_CLIP_TASK = "Ctrl+Alt+K"
HOTKEY_ID = 0xB43

TITLE_MAX = 120
NOTE_MAX = 4000

# Virtuella tangentkoder
VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN = 0x10, 0x11, 0x12, 0x5B, 0x5C
VK_C = 0x43
VK_MASK = 0xE8  # "oanvänd" tangent — hindrar att Alt-släpp aktiverar programmets meny

KEYEVENTF_KEYUP = 0x0002
INPUT_KEYBOARD = 1

_ULONG_PTR = ctypes.c_size_t


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_uint32), ("time", ctypes.c_uint32),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_int32), ("dy", ctypes.c_int32), ("mouseData", ctypes.c_uint32),
        ("dwFlags", ctypes.c_uint32), ("time", ctypes.c_uint32), ("dwExtraInfo", _ULONG_PTR),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", ctypes.c_uint32), ("wParamL", ctypes.c_ushort), ("wParamH", ctypes.c_ushort)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT), ("hi", _HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("u", _INPUTUNION)]


def _key(vk: int, up: bool) -> INPUT:
    i = INPUT()
    i.type = INPUT_KEYBOARD
    i.u.ki.wVk = vk
    i.u.ki.dwFlags = KEYEVENTF_KEYUP if up else 0
    return i


def _send(user32: Any, events: List[INPUT]) -> int:
    if not events:
        return 0
    arr = (INPUT * len(events))(*events)
    return int(user32.SendInput(len(events), arr, ctypes.sizeof(INPUT)))


def held_modifiers(user32: Any) -> List[int]:
    """Vilka modifierartangenter är nedtryckta just nu?"""
    held = []
    for vk in (VK_CONTROL, VK_MENU, VK_SHIFT, VK_LWIN, VK_RWIN):
        try:
            if user32.GetAsyncKeyState(vk) & 0x8000:
                held.append(vk)
        except Exception:
            pass
    return held


def send_copy(user32: Any) -> List[int]:
    """Släpp hållna modifierare och skicka Ctrl+C. Returnerar de modifierare som släpptes."""
    held = held_modifiers(user32)
    events: List[INPUT] = []
    if VK_MENU in held or VK_LWIN in held or VK_RWIN in held:
        # Alt/Win släppta utan annan tangent emellan aktiverar menyraden/Start — maskera
        events += [_key(VK_MASK, False), _key(VK_MASK, True)]
    events += [_key(vk, True) for vk in held]
    events += [_key(VK_CONTROL, False), _key(VK_C, False), _key(VK_C, True), _key(VK_CONTROL, True)]
    _send(user32, events)
    return held


def split_text(text: str) -> Tuple[str, str]:
    """
    Text → (rubrik, anteckning). Första icke-tomma raden blir rubrik, resten anteckning.
    En för lång rubrik kortas vid ett ord och hela texten sparas i anteckningen.
    """
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "").strip()
    if not text:
        return "", ""
    lines = text.split("\n")
    first = " ".join(lines[0].split())
    rest = "\n".join(lines[1:]).strip()
    if len(first) > TITLE_MAX:
        cut = first[:TITLE_MAX]
        sp = cut.rfind(" ")
        if sp > TITLE_MAX // 2:
            cut = cut[:sp]
        title = cut.rstrip(" ,;:-") + "…"
        note = text
    else:
        title, note = first, rest
    return title, note[:NOTE_MAX]


class ClipCapture:
    """
    Icke-blockerande fångst av markerad text.

    ``get_state``/``set_state`` läser/återställer urklippets innehåll (valfritt format, t.ex. en
    kopia av QMimeData), ``get_text`` läser texten i urklippet, ``schedule(ms, fn)`` kör fn senare
    på GUI-tråden. ``done(text, source)`` anropas en gång: source = "markering" | "urklipp" | "".
    """

    def __init__(
        self,
        user32: Any,
        get_text: Callable[[], str],
        get_state: Callable[[], Any],
        set_state: Callable[[Any], None],
        schedule: Callable[[int, Callable[[], None]], None],
        done: Callable[[str, str], None],
        poll_ms: int = 40,
        timeout_ms: int = 600,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.user32 = user32
        self.get_text = get_text
        self.get_state = get_state
        self.set_state = set_state
        self.schedule = schedule
        self.done = done
        self.poll_ms = poll_ms
        self.timeout_ms = timeout_ms
        self.clock = clock
        self.busy = False
        self._seq = 0
        self._last_seen = -1
        self._deadline = 0.0
        self._state: Any = None
        self._prev_text = ""

    def start(self) -> bool:
        """Starta fångsten. False om en fångst redan pågår."""
        if self.busy:
            return False
        self.busy = True
        try:
            self._prev_text = self.get_text() or ""
            self._state = self.get_state()
            self._seq = int(self.user32.GetClipboardSequenceNumber())
            self._last_seen = -1
            send_copy(self.user32)
            self._deadline = self.clock() + self.timeout_ms / 1000.0
            self.schedule(self.poll_ms, self._poll)
        except Exception as e:
            logger.warning(f"[CLIPTASK] kunde inte starta fångsten: {e}")
            self._finish(self._prev_text, "urklipp" if self._prev_text else "")
        return True

    def _poll(self) -> None:
        try:
            cur = int(self.user32.GetClipboardSequenceNumber())
        except Exception:
            cur = self._seq
        if cur != self._seq:
            # Urklippet ändrades. Vänta tills det är STABILT en varv till — många program tömmer
            # först urklippet och skriver sedan texten, och då vore första läsningen tom.
            if cur == self._last_seen:
                text = self.get_text() or ""
                if text.strip() or self.clock() >= self._deadline:
                    self._restore()
                    self._finish(text, "markering" if text.strip() else "")
                    return
            self._last_seen = cur
        elif self.clock() >= self._deadline:
            # Inget markerat (eller programmet kopierar inte) → använd det som redan låg i urklippet
            self._finish(self._prev_text, "urklipp" if self._prev_text.strip() else "")
            return
        if self.clock() >= self._deadline + 0.4:
            # Urklippet ändrades men blev aldrig läsbar text — ge upp, återställ
            self._restore()
            self._finish("", "")
            return
        self.schedule(self.poll_ms, self._poll)

    def _restore(self) -> None:
        try:
            if self._state is not None:
                self.set_state(self._state)
        except Exception as e:
            logger.warning(f"[CLIPTASK] kunde inte återställa urklippet: {e}")

    def _finish(self, text: str, source: str) -> None:
        self.busy = False
        try:
            self.done(text, source)
        except Exception as e:
            logger.warning(f"[CLIPTASK] done-callback misslyckades: {e}", exc_info=True)


def load_user32() -> Optional[Any]:
    """user32 med rätt signaturer (None utanför Windows)."""
    try:
        u = ctypes.WinDLL("user32", use_last_error=True)  # type: ignore[attr-defined]
    except Exception:
        return None
    u.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int]
    u.SendInput.restype = ctypes.c_uint
    u.GetAsyncKeyState.argtypes = [ctypes.c_int]
    u.GetAsyncKeyState.restype = ctypes.c_short
    u.GetClipboardSequenceNumber.argtypes = []
    u.GetClipboardSequenceNumber.restype = ctypes.c_uint32
    return u
