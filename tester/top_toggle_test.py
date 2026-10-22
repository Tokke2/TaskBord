#!/usr/bin/env python3
"""
top_toggle_test.py — snabbtangent som slår "Alltid överst" på/av (default Ctrl+Alt+T).

Kör:  python tester/top_toggle_test.py
Windows-API:et ersätts med en attrapp; växlingslogiken, inställningarna och registreringen testas på riktigt.
"""
from __future__ import annotations

import ctypes
import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "core"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ok = _fail = 0


def check(name, cond, extra=""):
    global _ok, _fail
    if cond:
        _ok += 1
    else:
        _fail += 1
        print(f"  ✗ {name} {extra}")


from app.mixins.top_toggle import TopToggleMixin, DEFAULT_TOP_TOGGLE, TOP_TOGGLE_HOTKEY_ID  # noqa: E402
from core.settings import Settings  # noqa: E402

check("standardtangent Ctrl+Alt+T", DEFAULT_TOP_TOGGLE == "Ctrl+Alt+T")
check("eget id (krockar inte med N/V/K)", TOP_TOGGLE_HOTKEY_ID == 0xB44 and TOP_TOGGLE_HOTKEY_ID not in (0xB41, 0xB42, 0xB43))

tmp = Path(tempfile.mkdtemp(prefix="taskbord_tt_"))
st = Settings(str(tmp / "settings.json"))
check("settings: på som standard", st.top_toggle_enabled() is True)
check("settings: standardtangent", st.top_toggle_hotkey() == "Ctrl+Alt+T")
check("settings: förra läget behind", st.top_toggle_prev_mode() == "behind")
st.set_top_toggle_hotkey("Ctrl+Shift+T"); st.set_top_toggle_enabled(False); st.set_top_toggle_prev_mode("above")
check("settings: sparas", (st.top_toggle_hotkey(), st.top_toggle_enabled(), st.top_toggle_prev_mode()) == ("Ctrl+Shift+T", False, "above"))
st.set_top_toggle_prev_mode("top")
check("settings: 'top' accepteras inte som förra läge", st.top_toggle_prev_mode() == "behind")
st.set_top_toggle_hotkey("Ctrl+Alt+T"); st.set_top_toggle_enabled(True)


class Log:
    def __getattr__(self, n): return lambda *a, **k: None


class Ctl(TopToggleMixin):
    def __init__(self, settings, mode):
        self.settings = settings
        self._log = Log()
        self.mode = mode
        self.set_calls = []
        self.notes = []
        self.filter_installs = 0
        self._QMessageBox = None

    def _desktop_mode(self): return self.mode
    def _set_desktop_mode(self, m): self.set_calls.append(m); self.mode = m
    def _notify_hotkey(self, t): self.notes.append(t)
    def _ensure_hotkey_filter(self): self.filter_installs += 1
    def _populate_tray_menu(self): pass
    def _get_quick_add_hotkey_combo(self): return "Ctrl+Alt+N"
    def _get_push_hotkey_combo(self): return "Ctrl+Alt+V"
    def _get_clip_task_combo(self): return "Ctrl+Alt+K"


# --- växlingen -----------------------------------------------------------------------------
c = Ctl(st, "behind")
check("behind → top", c._toggle_always_on_top() == "top" and c.mode == "top")
check("förra läget (behind) sparades", st.top_toggle_prev_mode() == "behind")
check("notis: PÅ", "PÅ" in c.notes[-1])
check("top → tillbaka till behind", c._toggle_always_on_top() == "behind" and c.mode == "behind")
check("notis: AV", "AV" in c.notes[-1])

c = Ctl(st, "above")
c._toggle_always_on_top()
check("above → top och 'above' kommer ihåg", c.mode == "top" and st.top_toggle_prev_mode() == "above")
c._toggle_always_on_top()
check("top → tillbaka till above", c.mode == "above")

c = Ctl(st, "top")                       # startat i top (t.ex. efter omstart) utan känt förra läge
st.set_top_toggle_prev_mode("behind")
check("startar i top → av ger behind", c._toggle_always_on_top() == "behind")

c = Ctl(types.SimpleNamespace(), "behind")   # trasiga inställningar → ändå säker växling
check("utan settings-metoder går det ändå att slå på", c._toggle_always_on_top() == "top")
c._top_toggle_press()
check("tangenttryck växlar", c.mode == "behind")


# --- registrering mot falsk windll ----------------------------------------------------------
class FakeUser32:
    def __init__(self): self.registered, self.taken = {}, set()
    def RegisterHotKey(self, hwnd, hid, mods, vk):
        if (mods & ~0x4000, vk) in self.taken or hid in self.registered:
            return 0
        self.registered[hid] = (mods, vk); return 1
    def UnregisterHotKey(self, hwnd, hid): return 1 if self.registered.pop(hid, None) else 0


real_platform, had = sys.platform, hasattr(ctypes, "windll")
u = FakeUser32()
ctypes.windll = types.SimpleNamespace(user32=u)
sys.platform = "win32"
try:
    c = Ctl(st, "behind")
    c._install_top_toggle_hotkey()
    check("start: Ctrl+Alt+T registrerad (med NOREPEAT)", u.registered.get(0xB44) == (3 | 0x4000, 0x54), str(u.registered))
    check("start: Qt-filtret säkras", c.filter_installs == 1 and c._top_toggle_registered == "Ctrl+Alt+T")
    ok, why = c._register_top_toggle_hotkey("Ctrl+Alt+J")
    check("byte av tangent", ok and u.registered[0xB44][1] == 0x4A)
    u.taken.add((3, 0x58))
    ok, why = c._register_top_toggle_hotkey("Ctrl+Alt+X")
    check("upptagen tangent: nekas, den gamla lever kvar", (not ok) and "upptagen" in why and u.registered[0xB44][1] == 0x4A and c._top_toggle_registered == "Ctrl+Alt+J")
    check("ogiltig tangent nekas", not c._register_top_toggle_hotkey("Ctrl+Alt")[0])
    c._unregister_top_toggle_hotkey()
    check("avregistrera", 0xB44 not in u.registered and c._top_toggle_registered is None)
    st.set_top_toggle_enabled(False)
    c2 = Ctl(st, "behind"); u.registered.clear(); c2._install_top_toggle_hotkey()
    check("avstängd i inställningarna: inget registreras", not u.registered)
    st.set_top_toggle_enabled(True)

    # dialogen
    hd = types.ModuleType("ui.hotkey_dialog"); sys.modules["ui.hotkey_dialog"] = hd
    seen = {}
    hd.ask_hotkey = lambda *a, **k: (seen.update(k=k), "Ctrl+Alt+U")[1]
    c3 = Ctl(st, "behind"); u.registered.clear()
    c3._change_top_toggle_hotkey_dialog()
    check("dialog: ny tangent registreras och sparas", u.registered.get(0xB44, (0, 0))[1] == 0x55 and st.top_toggle_hotkey() == "Ctrl+Alt+U")
    check("dialog: övriga tangenter är 'upptagna' i valet", set(seen["k"]["taken"]) >= {"Ctrl+Alt+N", "Ctrl+Alt+V", "Ctrl+Alt+K"})
    hd.ask_hotkey = lambda *a, **k: ""
    c3._change_top_toggle_hotkey_dialog()
    check("dialog: Stäng av avregistrerar och sparar", 0xB44 not in u.registered and st.top_toggle_enabled() is False)
finally:
    sys.platform = real_platform
    if not had:
        del ctypes.windll

# --- kryssrutan "Visa över andra appar" --------------------------------------------------------
st2 = Settings(str(tmp / "settings2.json"))
check("standard: urkryssad (ligger på skrivbordet)", st2.desktop_mode() == "behind")
c = Ctl(st2, "behind")
c._set_show_over_apps(False)
check("urkryssad när den redan är urkryssad → inget ändras", c.set_calls == [] and c.mode == "behind")
c._set_show_over_apps(True)
check("ikryssa → alltid överst", c.mode == "top" and c.set_calls == ["top"])
c._set_show_over_apps(True)
check("ikryssad igen → ingen dubbelväxling", c.set_calls == ["top"])
c._set_show_over_apps(False)
check("avkryssa → tillbaka till skrivbordet (behind)", c.mode == "behind" and c.set_calls == ["top", "behind"])
check("etiketten är 'Visa över andra appar'", c._top_menu_label().startswith("Visa över andra appar"))
c2 = Ctl(st2, "behind"); c2._toggle_always_on_top(); c2._toggle_always_on_top()
check("notiserna: 'Visa över andra appar: PÅ/AV'", "Visa över andra appar: PÅ" in c2.notes[0] and "Visa över andra appar: AV" in c2.notes[1], c2.notes)

# --- ihopkoppling i appen ------------------------------------------------------------------------
src = lambda p: (ROOT / p).read_text(encoding="utf-8")
check("controllern ärver mixinen", "TopToggleMixin" in src("app/controller.py"))
check("WM_HOTKEY-filtret hanterar 0xB44", "0xB44" in src("app/mixins/hotkeys.py") and "_top_toggle_press" in src("app/mixins/hotkeys.py"))
check("tangenten installeras vid start och avregistreras vid avslut",
      "_install_top_toggle_hotkey" in src("app/mixins/hotkeys.py") and "_unregister_top_toggle_hotkey" in src("app/mixins/hotkeys.py"))
check("tray-menyn har posten", "_change_top_toggle_hotkey_dialog" in src("app/mixins/tray.py"))
check("tray-menyn har kryssrutan (checkable, kopplad till _set_show_over_apps)",
      "act_over.setCheckable(True)" in src("app/mixins/tray.py") and "_set_show_over_apps(bool(checked))" in src("app/mixins/tray.py"))
check("kantdockningen lyfter bara fönstret när kryssrutan är ikryssad", 'desktop_mode()).strip().lower() == "top"' in src("ui/edge_dock.py"))

print(f"\ntop_toggle_test: {_ok} lyckades, {_fail} misslyckades")
sys.stdout.flush()
os._exit(1 if _fail else 0)
