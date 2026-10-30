#!/usr/bin/env python3
"""
desktop_top_test.py — tray-valet "Alltid överst" (desktop_mode == "top").

Kör:  python tester/desktop_top_test.py

Windows-API:erna finns inte i sandlådan, så ctypes.windll ersätts med en logg-attrap;
testet kontrollerar vilka anrop som görs (HWND_TOPMOST / NOTOPMOST / SetParent).
"""
from __future__ import annotations

import ctypes
import logging
import os
import sys
import tempfile
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "core"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.mixins.desktop_shell import DesktopShellMixin  # noqa: E402

_ok = _fail = 0


def check(name: str, cond: bool) -> None:
    global _ok, _fail
    if cond:
        _ok += 1
    else:
        _fail += 1
        print(f"  FAIL: {name}")


class FakeUser32:
    def __init__(self, parent: int = 0):
        self.calls: list[tuple] = []
        self.parent = parent
        self.ex = 0x08000000 | 0x80  # NOACTIVATE | TOOLWINDOW

    def _rec(self, name, *a):
        self.calls.append((name,) + a)
        return 1

    def IsWindow(self, h): return 1
    def IsIconic(self, h): return 0
    def IsWindowVisible(self, h): return 1
    def GetParent(self, h): return self.parent
    def GetAncestor(self, h, f): return self.parent
    def GetWindowRect(self, h, r): return 1
    def GetWindowLongW(self, h, i): return self.ex

    def SetWindowLongW(self, h, i, v):
        self.ex = v
        return self._rec("SetWindowLongW", h, i, v)

    def SetParent(self, h, p):
        self.parent = p
        return self._rec("SetParent", h, p)

    def SetWindowPos(self, h, after, *rest): return self._rec("SetWindowPos", h, after, *rest)
    def ShowWindow(self, h, c): return self._rec("ShowWindow", h, c)
    def __getattr__(self, name):  # allt annat: ofarlig no-op
        return lambda *a, **k: 1


class Timer:
    def __init__(self): self._i = 30000
    def interval(self): return self._i
    def setInterval(self, v): self._i = v


class Shell:
    def __init__(self, visible: bool = True):
        self._vis = visible
        self._zorder_timer = Timer()
        self._desktop_layer_mode = None
        self.nativeEvent = lambda *a: (False, 0)

    def winId(self): return 4242
    def isVisible(self): return self._vis


class Ctl(DesktopShellMixin):
    def __init__(self, mode: str):
        self.mode = mode
        self._log = logging.getLogger("desktop_top_test")
        self._log.setLevel(logging.CRITICAL)
        self._imports = {}
        self._widgets = {}

    def _desktop_mode(self): return self.mode
    def _is_hidden_to_tray(self): return False


def topmost_calls(u: FakeUser32, after: int) -> list:
    return [c for c in u.calls if c[0] == "SetWindowPos" and c[2] == after]


def with_fake(user: FakeUser32):
    ctypes.windll = SimpleNamespace(user32=user)  # type: ignore[attr-defined]


# --- 1. apply: top -----------------------------------------------------------------------
u = FakeUser32(parent=777)  # satt som barn i Progman ('above')
with_fake(u)
c, sh = Ctl("top"), Shell()
c._apply_desktop_shell(sh, "w1")
check("top: läget sätts till 'top'", sh._desktop_layer_mode == "top")
check("top: HWND_TOPMOST anropas", len(topmost_calls(u, -1)) >= 1)
check("top: lossas från skrivbordsförälder (SetParent 0)", ("SetParent", 4242, 0) in u.calls)
check("top: WS_EX_NOACTIVATE borttagen (kan skriva i fönstret)", not (u.ex & 0x08000000))
check("top: WS_EX_TOOLWINDOW kvar (ej i aktivitetsfältet)", bool(u.ex & 0x80))
check("top: inget NOTOPMOST", not topmost_calls(u, -2))
check("top: bevakningstimer 5 s", sh._zorder_timer.interval() == 5000)

# --- 2. maintain: top --------------------------------------------------------------------
u.calls.clear()
c._maintain_desktop_level(sh)
check("maintain/top: återställer TOPMOST", len(topmost_calls(u, -1)) == 1)
check("maintain/top: läget behålls", sh._desktop_layer_mode == "top")
u.calls.clear()
hidden = Shell(visible=False)
hidden._desktop_layer_mode = "top"
c._maintain_desktop_level(hidden)
check("maintain/top: användar-dolt fönster rörs inte", not topmost_calls(u, -1))

# --- 3. top → behind släpper topmost ----------------------------------------------------
u.calls.clear()
c.mode = "behind"
c._apply_desktop_shell(sh, "w1")
check("top→behind: NOTOPMOST anropas", len(topmost_calls(u, -2)) >= 1)
check("top→behind: läget är inte längre 'top'", sh._desktop_layer_mode != "top")
check("top→behind: tillbaka till 30 s-timer eller 5 s-fallback", sh._zorder_timer.interval() in (5000, 30000))

# --- 4. behind → top (inget barn) --------------------------------------------------------
u2 = FakeUser32(parent=0)
with_fake(u2)
sh2 = Shell()
sh2._desktop_layer_mode = "behind"
Ctl("top")._apply_desktop_shell(sh2, "w2")
check("behind→top: TOPMOST", len(topmost_calls(u2, -1)) >= 1 and sh2._desktop_layer_mode == "top")
check("behind→top: ingen onödig SetParent", not any(x[0] == "SetParent" for x in u2.calls))

# --- 5. lyft/push-release återgår till top ----------------------------------------------
sh3 = Shell()
sh3._desktop_layer_mode = None
Ctl("top")._apply_desktop_shell(sh3, "w3")
check("lift-timeout/push-release (läge None → apply) ger 'top' igen", sh3._desktop_layer_mode == "top")

# --- 5b. urkryssad 'Visa över andra appar': kvarglömd topmost städas bort ----------------------------
u5 = FakeUser32(parent=0)
u5.ex |= 0x8  # WS_EX_TOPMOST har blivit kvar (t.ex. efter en tillfällig lyftning)
with_fake(u5)
sh5 = Shell()
c5 = Ctl("behind")
c5._maintain_desktop_level(sh5)
check("maintain/behind: kvarglömd TOPMOST släpps (NOTOPMOST)", len(topmost_calls(u5, -2)) == 1)
u5.calls.clear()
u5.ex &= ~0x8
c5._maintain_desktop_level(sh5)
check("maintain/behind: inget onödigt NOTOPMOST när stilen är ren", not topmost_calls(u5, -2))
sh5._desktop_layer_mode = "normal"
u5.ex |= 0x8
u5.calls.clear()
c5._apply_desktop_shell(sh5, "w5")
check("apply/behind utan skrivbordslager: aldrig topmost", len(topmost_calls(u5, -2)) >= 1 and not topmost_calls(u5, -1))
check("_clear_topmost: inget hwnd → False", DesktopShellMixin._clear_topmost(0) is False)

# --- 6. källkod: inställning, meny, tvinga-synlig, push-release --------------------------
src = lambda p: (ROOT / p).read_text(encoding="utf-8")  # noqa: E731
check("tray-menyn har kryssrutan 'Visa över andra appar'", "_set_show_over_apps" in src("app/mixins/tray.py") and "Visa över andra appar" in src("app/mixins/top_toggle.py"))
check("force_show lämnar 'top' ifred", '("above", "behind", "top")' in src("app/mixins/windows.py"))
check("push-release återfäster 'top'", '("behind", "above", "top")' in src("app/mixins/hotkeys.py"))

# --- 7. settings (kräver PySide6) --------------------------------------------------------
try:
    from PySide6.QtCore import QCoreApplication
except Exception:
    print("PySide6 saknas — hoppar över inställningstest")
else:
    app = QCoreApplication.instance() or QCoreApplication([])
    from core.settings import DEFAULT_DESKTOP_MODE, Settings, VALID_DESKTOP_MODES

    check("'top' är ett giltigt läge", "top" in VALID_DESKTOP_MODES)
    check("standardläget är fortfarande 'behind'", DEFAULT_DESKTOP_MODE == "behind")
    with tempfile.TemporaryDirectory() as d:
        p = str(Path(d) / "settings.json")
        s = Settings(p)
        check("nytt läge: standard 'behind'", s.desktop_mode() == "behind")
        s.set_desktop_mode("top")
        check("set 'top' → desktop_mode() == 'top'", s.desktop_mode() == "top")
        with suppress(Exception):
            s.save()
        s2 = Settings(p)
        check("'top' överlever omstart", s2.desktop_mode() == "top")
        s2.set_desktop_mode("nonsens")
        check("ogiltigt läge → standard", s2.desktop_mode() == "behind")
        s2.set_desktop_mode("above")
        check("'above' migreras fortfarande till 'behind'", s2.desktop_mode() == "behind")

print(f"\n{'PASSERADE' if not _fail else 'MISSLYCKADES'}: {_ok} ok, {_fail} fel")
sys.exit(1 if _fail else 0)
