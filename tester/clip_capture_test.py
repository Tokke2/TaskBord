"""
clip_capture_test.py — "Lägg till från urklipp" (Ctrl+Alt+K): rubrik/anteckning, tangentföljd
(modifierare släpps innan Ctrl+C), väntan på urklippsändring, fallback, återställning, mixin-uppgift.
Windows-delarna körs mot ett fejkat user32.
"""
from __future__ import annotations

import ctypes
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for sub in ("", "core", "ui"):
    sys.path.insert(0, str(ROOT / sub))

from core import clip_capture as cc  # noqa: E402

ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("  ✗", name, extra)


# --- split_text ---
check("tom → tomt", cc.split_text("") == ("", "") and cc.split_text("  \n ") == ("", ""))
check("en rad → bara rubrik", cc.split_text("Ring Anna") == ("Ring Anna", ""))
check("flera rader → rubrik + anteckning",
      cc.split_text("Köp mjölk\nOch bröd\nOch ost") == ("Köp mjölk", "Och bröd\nOch ost"))
check("tomma rader först hoppas över", cc.split_text("\n\n  Hej  \nDel 2")[0] == "Hej")
check("CRLF hanteras", cc.split_text("A\r\nB\r\nC") == ("A", "B\nC"))
long_line = "ord " * 80
t, n = cc.split_text(long_line)
check("lång rubrik kortas med …", len(t) <= cc.TITLE_MAX + 1 and t.endswith("…"), len(t))
check("lång rubrik: hela texten sparas i anteckningen", n.startswith("ord ord"), n[:20])
check("kortas vid ordgräns", not t[:-1].endswith("or"))
t2, n2 = cc.split_text("x" * 300)
check("ord utan mellanslag kortas hårt", len(t2) == cc.TITLE_MAX + 1)
check("anteckning begränsas", len(cc.split_text("A\n" + "b" * 10000)[1]) == cc.NOTE_MAX)
check("NUL-tecken tas bort", "\x00" not in cc.split_text("A\x00B")[0])
check("inre blanksteg plattas", cc.split_text("A   \t B")[0] == "A B")

# --- INPUT-struktur måste vara 40 byte (x64) för att SendInput ska acceptera den ---
check("sizeof(INPUT) == 40", ctypes.sizeof(cc.INPUT) == 40, ctypes.sizeof(cc.INPUT))


class FakeUser32:
    def __init__(self, held=()):
        self.held = set(held)
        self.seq = 100
        self.sent = []          # (vk, up)
        self.on_copy = None     # anropas när Ctrl+C skickats

    def GetAsyncKeyState(self, vk):
        return 0x8000 if vk in self.held else 0

    def GetClipboardSequenceNumber(self):
        return self.seq

    def SendInput(self, n, arr, size):
        assert size == ctypes.sizeof(cc.INPUT)
        for i in range(n):
            ki = arr[i].u.ki
            self.sent.append((ki.wVk, bool(ki.dwFlags & cc.KEYEVENTF_KEYUP)))
        if (cc.VK_C, True) in self.sent[-n:] and self.on_copy:
            self.on_copy()
        return n


# --- send_copy: tangentföljd ---
u = FakeUser32(held={cc.VK_CONTROL, cc.VK_MENU})
held = cc.send_copy(u)
check("hållna modifierare upptäcks", set(held) == {cc.VK_CONTROL, cc.VK_MENU}, held)
seq = u.sent
check("Alt släpps", (cc.VK_MENU, True) in seq)
check("Ctrl släpps först och trycks sedan igen",
      seq.index((cc.VK_CONTROL, True)) < seq.index((cc.VK_CONTROL, False)))
check("Alt släpps INNAN C trycks", seq.index((cc.VK_MENU, True)) < seq.index((cc.VK_C, False)))
check("slutar med C upp, Ctrl upp", seq[-2:] == [(cc.VK_C, True), (cc.VK_CONTROL, True)], seq)
check("mask-tangent före Alt-släpp (stoppar menyaktivering)",
      (cc.VK_MASK, False) in seq and seq.index((cc.VK_MASK, True)) < seq.index((cc.VK_MENU, True)), seq)
u2 = FakeUser32()
cc.send_copy(u2)
check("inga modifierare hållna → bara Ctrl+C",
      u2.sent == [(cc.VK_CONTROL, False), (cc.VK_C, False), (cc.VK_C, True), (cc.VK_CONTROL, True)], u2.sent)
u3 = FakeUser32(held={cc.VK_SHIFT})
cc.send_copy(u3)
check("Shift utan Alt → ingen mask-tangent", (cc.VK_MASK, False) not in u3.sent)


# --- ClipCapture med fejkad klocka/timer/urklipp ---
class Harness:
    def __init__(self, user32, clipboard="gammalt", copy_delay=3, copies="Markerad text",
                 set_in_two_steps=False):
        self.u = user32
        self.clipboard = clipboard
        self.copies = copies
        self.t = 0.0
        self.queue = []
        self.results = []
        self.restored = []
        self.copy_delay = copy_delay
        self.two_steps = set_in_two_steps
        if copies is not None:
            user32.on_copy = self._app_copies
        self._pending = None
        self.cap = cc.ClipCapture(
            user32, lambda: self.clipboard, lambda: ("STATE", self.clipboard),
            self._set_state, lambda ms, fn: self.queue.append((self.t + ms / 1000, fn)),
            lambda text, src: self.results.append((text, src)),
            clock=lambda: self.t,
        )

    def _app_copies(self):
        self._pending = self.copy_delay   # appen skriver urklippet efter N varv

    def _set_state(self, st):
        self.restored.append(st)
        self.clipboard = st[1]
        self.u.seq += 1

    def run(self, limit=200):
        n = 0
        while self.queue and n < limit:
            n += 1
            self.queue.sort(key=lambda x: x[0])
            self.t, fn = self.queue.pop(0)
            if self._pending is not None:
                self._pending -= 1
                if self._pending == 0:
                    if self.two_steps:
                        self.clipboard = ""        # EmptyClipboard
                        self.u.seq += 1
                        self._pending = 2
                        self.two_steps = False
                    else:
                        self.clipboard = self.copies
                        self.u.seq += 1
                        self._pending = None
            fn()
        return n


h = Harness(FakeUser32(held={cc.VK_CONTROL, cc.VK_MENU}))
check("start() ger True", h.cap.start() is True)
check("andra start() under pågående → False", h.cap.start() is False)
h.run()
check("markerad text fångas", h.results == [("Markerad text", "markering")], h.results)
check("urklippet återställs", h.clipboard == "gammalt" and h.restored == [("STATE", "gammalt")], (h.clipboard, h.restored))
check("busy är falskt efteråt", h.cap.busy is False)
check("kan startas igen", h.cap.start() is True)
h.run()

# inget markerat → urklippet oförändrat → fallback
h = Harness(FakeUser32(), clipboard="Det som låg i urklippet", copies=None)
h.cap.start()
h.run()
check("inget markerat → använder urklippets text", h.results == [("Det som låg i urklippet", "urklipp")], h.results)
check("fallback rör inte urklippet", h.restored == [])

h = Harness(FakeUser32(), clipboard="", copies=None)
h.cap.start()
h.run()
check("inget markerat + tomt urklipp → tom text", h.results == [("", "")], h.results)

# app som tömmer urklippet först och skriver texten sen
h = Harness(FakeUser32(), copies="Skrivs i två steg", set_in_two_steps=True)
h.cap.start()
h.run()
check("tvåstegs-skrivning: får inte läsa det tomma mellanläget",
      h.results == [("Skrivs i två steg", "markering")], h.results)

# långsam app (men inom tidsgränsen)
h = Harness(FakeUser32(), copy_delay=9)
h.cap.start()
h.run()
check("långsam app fångas inom tidsgränsen", h.results and h.results[0][1] == "markering", h.results)

# fel i user32 kraschar inte
class Broken(FakeUser32):
    def SendInput(self, *a):
        raise OSError("blockerad")


h = Harness(Broken(), clipboard="X", copies=None)
h.cap.start()
h.run()
check("SendInput-fel → faller tillbaka på urklipp, busy släpps",
      h.results == [("X", "urklipp")] and h.cap.busy is False, h.results)

# done-callback som kastar får inte låsa busy
h = Harness(FakeUser32())
h.cap.done = lambda t, s: 1 / 0
h.cap.start()
h.run()
check("kastande callback låser inte fångsten", h.cap.busy is False)

# --- mixin: skapa uppgift (utan Qt) ---
from app.mixins.clip_task import ClipTaskMixin  # noqa: E402


class FakeStore:
    def __init__(self):
        self.tasks = {}

    def add_task(self, title):
        tid = f"t{len(self.tasks) + 1}"
        self.tasks[tid] = {"title": title}
        return tid

    def set_task_metadata(self, tid, k, v):
        self.tasks[tid][k] = v
        return True


class FakeLog:
    def info(self, *a, **k): pass
    warning = debug = error = info


class FakeTray:
    def __init__(self): self.msgs = []
    def showMessage(self, title, text, icon, ms): self.msgs.append((title, text))


class FakeIconCls:
    class MessageIcon:
        Information = 1


class C(ClipTaskMixin):
    def __init__(self):
        self.store = FakeStore()
        self._log = FakeLog()
        self._tray = FakeTray()
        self._QSystemTrayIcon = FakeIconCls
    def _update_tray_tooltip(self): pass


c = C()
c._clip_task_done("Boka tandläkare\nTa med remiss\nRing 08-123", "markering")
tk = list(c.store.tasks.values())
check("mixin: uppgift med rubrik", tk and tk[0]["title"] == "Boka tandläkare", tk)
check("mixin: anteckning sparad", tk[0].get("note") == "Ta med remiss\nRing 08-123", tk)
check("mixin: kvittens 'från markeringen'", "markeringen" in c._tray.msgs[-1][0], c._tray.msgs)
c._clip_task_done("Bara en rad", "urklipp")
check("mixin: ingen anteckning för en rad", "note" not in list(c.store.tasks.values())[1])
check("mixin: kvittens 'från urklippet'", "urklippet" in c._tray.msgs[-1][0], c._tray.msgs)
n_before = len(c.store.tasks)
c._clip_task_done("", "")
check("mixin: tom text skapar inget", len(c.store.tasks) == n_before)
check("mixin: tom text → upplysning", "Inget" in c._tray.msgs[-1][0], c._tray.msgs)
c._tray = None
c._clip_task_done("Utan tray", "urklipp")
check("mixin: fungerar utan tray", len(c.store.tasks) == n_before + 1)

# --- inställningar + koppling ---
src = (ROOT / "app/mixins/hotkeys.py").read_text(encoding="utf-8")
check("WM_HOTKEY-filtret skickar 0xB43 vidare", "0xB43" in src and "_clip_task_press" in src)
check("hotkey avregistreras vid avslut", "_unregister_clip_task_hotkey" in src)
check("ID:t krockar inte med de andra", cc.HOTKEY_ID not in (0xB41, 0xB42))
from core.hotkey_combo import validate_global_combo  # noqa: E402
check("standardtangenten duger", validate_global_combo(cc.DEFAULT_CLIP_TASK, ["Ctrl+Alt+N", "Ctrl+Alt+V"])[0])
check("krock med Ny uppgift fångas", not validate_global_combo("Ctrl+Alt+K", ["Ctrl+Alt+K"])[0])
tray = (ROOT / "app/mixins/tray.py").read_text(encoding="utf-8")
check("tray: meny för urklipp finns", "_change_clip_task_hotkey_dialog" in tray and "_clip_task_from_clipboard" in tray)

from core.settings import Settings  # noqa: E402
import tempfile  # noqa: E402
try:
    st = Settings(str(Path(tempfile.mkdtemp()) / "settings.json"))
    check("settings: default Ctrl+Alt+K", st.clip_task_hotkey() == "Ctrl+Alt+K")
    check("settings: på som standard", st.clip_task_enabled() is True)
    st.set_clip_task_hotkey("Ctrl+Shift+K")
    st.set_clip_task_enabled(False)
    check("settings: sparar tangent/avstängd", st.clip_task_hotkey() == "Ctrl+Shift+K" and st.clip_task_enabled() is False)
except Exception as e:  # pragma: no cover
    check("settings fungerar", False, repr(e))

print(f"\nclip_capture: {ok} lyckades, {fail} misslyckades")
sys.exit(1 if fail else 0)
