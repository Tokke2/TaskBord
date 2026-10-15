"""
hotkey_test.py — snabbtangenten för NY UPPGIFT: tolkning, validering, registrering och dialog.

* core/hotkey_combo: tolka/normalisera/validera (ren logik).
* HotkeysMixin mot en FALSK ``ctypes.windll`` (Windows-API:et finns inte här): registrera, byta,
  upptagen tangent (den gamla ska leva kvar), stänga av, och buggen att Qt-filtret inte
  installerades när standardtangenten var upptagen vid start.
* HotkeyDialog med riktiga Qt-widgets (offscreen) — tangenttryck simuleras med QTest.
  Körs i en egen process (``--dialog``) eftersom Qt kan behöva stub-bibliotek.
"""
from __future__ import annotations

import ctypes
import subprocess
import sys
import tempfile
import shutil
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "ui"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("  ✗", name, extra)


# ===========================================================================
def dialog_part() -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialogButtonBox
    app = QApplication.instance() or QApplication([])
    from ui.hotkey_dialog import HotkeyDialog

    CA = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier

    def mk(current="Ctrl+Alt+N", taken=(), disable=True):
        return HotkeyDialog("t", "intro", current, "Ctrl+Alt+N", taken, disable)

    def save_enabled(d):
        return d.buttons.button(QDialogButtonBox.StandardButton.Save).isEnabled()

    d = mk()
    check("dialog: startvärdet visas", d.combo() == "Ctrl+Alt+N", d.combo())
    check("dialog: startvärdet duger → Spara aktiv", save_enabled(d))

    d.edit.clear()
    check("dialog: tom ruta → Spara avstängd", not save_enabled(d))
    QTest.keyClick(d.edit, Qt.Key.Key_K, CA)
    check("dialog: Ctrl+Alt+K trycks in", d.combo() == "Ctrl+Alt+K", d.combo())
    check("dialog: …och duger", save_enabled(d))

    d.edit.clear()
    QTest.keyClick(d.edit, Qt.Key.Key_N)
    check("dialog: bara 'N' nekas (skulle blockera skrivning)",
          not save_enabled(d) and "minst två" in d.status.text(), d.status.text())

    d.edit.clear()
    QTest.keyClick(d.edit, Qt.Key.Key_N, Qt.KeyboardModifier.ControlModifier)
    check("dialog: bara Ctrl+N nekas", not save_enabled(d))

    d.edit.clear()
    QTest.keyClick(d.edit, Qt.Key.Key_N, Qt.KeyboardModifier.MetaModifier)
    check("dialog: Meta → Win", d.combo() == "Win+N", d.combo())
    check("dialog: Win+N duger", save_enabled(d))

    d.edit.clear()
    QTest.keyClick(d.edit, Qt.Key.Key_F5, CA)
    check("dialog: F-tangent går", d.combo() == "Ctrl+Alt+F5", d.combo())

    d2 = mk(taken=["Ctrl+Alt+V"])
    d2.edit.clear()
    QTest.keyClick(d2.edit, Qt.Key.Key_V, CA)
    check("dialog: samma som Visa-över-tangenten nekas",
          not save_enabled(d2) and "annan snabbtangent" in d2.status.text(), d2.status.text())

    d2.edit.clear()
    QTest.keyClick(d2.edit, Qt.Key.Key_K, CA)
    d2.btn_default.click()
    check("dialog: Standard-knappen återställer", d2.combo() == "Ctrl+Alt+N", d2.combo())

    d3 = mk()
    d3.edit.clear()
    QTest.keyClick(d3.edit, Qt.Key.Key_J, CA)
    d3.buttons.button(QDialogButtonBox.StandardButton.Save).click()
    check("dialog: Spara ger vald kombination", d3.chosen == "Ctrl+Alt+J", d3.chosen)

    d4 = mk()
    d4.btn_disable.click()
    check("dialog: Stäng av ger ''", d4.chosen == "" and d4.disabled)
    d5 = mk()
    d5.buttons.button(QDialogButtonBox.StandardButton.Cancel).click()
    check("dialog: Avbryt ger None", d5.chosen is None)
    d6 = mk(disable=False)
    check("dialog: Stäng av dold när den inte tillåts", d6.btn_disable.isHidden())

    print(f"DIALOG {ok} {fail}")


if "--dialog" in sys.argv:
    dialog_part()
    sys.exit(1 if fail else 0)


# ===========================================================================
# 1. ren logik
# ===========================================================================
from core.hotkey_combo import (  # noqa: E402
    normalize_combo, parse_hotkey_combo, qt_to_combo, validate_global_combo,
)

check("parse Ctrl+Alt+N", parse_hotkey_combo("Ctrl+Alt+N") == (3, 0x4E))
check("parse ogiltig", parse_hotkey_combo("Ctrl+Alt") == (0, 0))
check("parse Win", parse_hotkey_combo("Win+N") == (8, 0x4E))
check("parse F13 ogiltig", parse_hotkey_combo("Ctrl+F13") == (0, 0))
check("normalize ordning/versaler", normalize_combo("alt + ctrl+n") == "Ctrl+Alt+N")
check("normalize Meta→Win", normalize_combo("Meta+Shift+x") == "Shift+Win+X")
check("normalize skräp → ''", normalize_combo("blabla") == "")
check("qt_to_combo Return→Enter", qt_to_combo("Ctrl+Alt+Return") == "Ctrl+Alt+Enter")
check("qt_to_combo ackord → första", qt_to_combo("Ctrl+K, Ctrl+C") == "Ctrl+K")
check("qt_to_combo tom", qt_to_combo("") == "")
from app.config import parse_hotkey_combo as _cfg_parse  # noqa: E402
check("app.config återexporterar samma funktion", _cfg_parse is parse_hotkey_combo)
for combo, expect in [("Ctrl+Alt+N", True), ("Ctrl+Shift+K", True), ("Win+N", True),
                      ("N", False), ("Ctrl+N", False), ("Alt+F4", False),
                      ("Win+L", False), ("Ctrl+Alt+", False), ("", False)]:
    check(f"validate {combo!r}", validate_global_combo(combo)[0] is expect)
check("validate: taken", not validate_global_combo("ctrl+alt+v", ["Ctrl+Alt+V"])[0])
check("validate: taken tom ok", validate_global_combo("Ctrl+Alt+V", [""])[0])

# ===========================================================================
# 2. HotkeysMixin mot falsk windll
# ===========================================================================
from PySide6.QtCore import QAbstractNativeEventFilter  # noqa: E402,F401  (före win32-låtsasen)
from app.mixins import hotkeys as hk  # noqa: E402


class FakeUser32:
    def __init__(self):
        self.registered = {}      # id -> (mods, vk)
        self.taken = set()        # (mods_utan_norepeat, vk) som "ett annat program" äger
        self.calls = []

    def RegisterHotKey(self, hwnd, hid, mods, vk):
        self.calls.append(("reg", hid, mods, vk))
        if (mods & ~0x4000, vk) in self.taken or hid in self.registered:
            return 0
        self.registered[hid] = (mods, vk)
        return 1

    def UnregisterHotKey(self, hwnd, hid):
        self.calls.append(("unreg", hid))
        return 1 if self.registered.pop(hid, None) else 0


class FakeSettings:
    def __init__(self):
        self.quick = "Ctrl+Alt+N"
        self.push = "Ctrl+Alt+V"
        self.enabled = True
        self.shortcuts_ = {}

    def global_quick_add(self): return self.enabled
    def set_global_quick_add(self, v): self.enabled = bool(v); return True
    def quick_add_hotkey(self): return self.quick
    def set_quick_add_hotkey(self, c): self.quick = c; return True
    def push_show_hotkey(self): return self.push
    def set_shortcut(self, a, c): self.shortcuts_[a] = c; return True


class FakeLog:
    def __getattr__(self, n):
        if n in ("warning", "error", "critical"):
            return lambda *a, **k: LOGGED.append(str(a[0]) if a else "")
        return lambda *a, **k: None


LOGGED: list = []


class FakeApp:
    def __init__(self): self.filters = []
    def installNativeEventFilter(self, f): self.filters.append(f)
    def removeNativeEventFilter(self, f): self.filters.remove(f)


class Box:
    def __init__(self): self.warnings = []
    def warning(self, parent, title, text): self.warnings.append((title, text))


class Ctl(hk.HotkeysMixin):
    def __init__(self, settings):
        self.settings = settings
        self._log = FakeLog()
        self._app = FakeApp()
        self._tray = None
        self._QMessageBox = Box()
        self._QSystemTrayIcon = None
        self._widget_lock = __import__("threading").RLock()
        self._widgets = {}
        self.menu_rebuilds = 0

    def _populate_tray_menu(self): self.menu_rebuilds += 1


def setup(user32):
    ctypes.windll = types.SimpleNamespace(user32=user32)
    hk.sys.platform, setup.old_platform = "win32", hk.sys.platform


def teardown():
    hk.sys.platform = setup.old_platform
    if hasattr(ctypes, "windll"):
        del ctypes.windll


# ui.hotkey_dialog kräver QtWidgets (GL) — här ersätts den av en låtsasmodul;
# den riktiga dialogen testas i del 3.
hd = types.ModuleType("ui.hotkey_dialog")
sys.modules["ui.hotkey_dialog"] = hd
asked = {}


def answer(value):
    def fake(*a, **k):
        asked["args"], asked["kwargs"] = a, k
        return value
    hd.ask_hotkey = fake


try:
    # a) standardtangenten upptagen vid start → filtret ska ÄNDÅ installeras (buggen)
    u = FakeUser32(); u.taken.add((3, 0x4E)); setup(u)
    s = FakeSettings(); c = Ctl(s)
    c._install_global_quick_add()
    check("start/upptagen: ingen snabbtangent aktiv", c._global_hotkey_id is None)
    check("start/upptagen: Qt-filtret installerat ändå", len(c._app.filters) == 1)
    check("start/upptagen: push-to-show registrerad", 0xB42 in u.registered)
    answer("Ctrl+Shift+K")
    c._change_quick_add_hotkey_dialog()
    check("byte efter upptagen start: registrerad hos Windows",
          u.registered.get(0xB41, (0, 0))[1] == 0x4B, str(u.registered))
    check("byte: MOD_NOREPEAT satt", u.registered[0xB41][0] & 0x4000)
    check("byte: id aktivt", c._global_hotkey_id == 0xB41)
    check("byte: sparad i settings", s.quick == "Ctrl+Shift+K" and s.shortcuts_.get("add_task") == "Ctrl+Shift+K")
    check("byte: fortfarande ETT filter (inte dubbla)", len(c._app.filters) == 1)
    check("byte: tray-menyn byggs om", c.menu_rebuilds == 1)
    check("dialog fick Visa-över-tangenten som upptagen",
          asked["kwargs"].get("taken") == ["Ctrl+Alt+V"], str(asked))

    # b) ny tangent upptagen → gamla lever kvar
    u.taken.add((3, 0x4D))
    answer("Ctrl+Alt+M")
    c._change_quick_add_hotkey_dialog()
    check("upptagen: gamla tangenten kvar hos Windows",
          u.registered.get(0xB41, (0, 0))[1] == 0x4B, str(u.registered))
    check("upptagen: inget sparat", s.quick == "Ctrl+Shift+K")
    check("upptagen: id fortfarande aktivt", c._global_hotkey_id == 0xB41)
    check("upptagen: användaren får veta", len(c._QMessageBox.warnings) == 1
          and "upptagen" in c._QMessageBox.warnings[0][1].lower(), str(c._QMessageBox.warnings))

    # c) stäng av
    answer("")
    c._change_quick_add_hotkey_dialog()
    check("av: avregistrerad", 0xB41 not in u.registered)
    check("av: setting av", s.enabled is False and c._global_hotkey_id is None)

    # d) på igen när den var avstängd vid start
    answer("Ctrl+Alt+J")
    c._change_quick_add_hotkey_dialog()
    check("på igen: registrerad + setting på", u.registered.get(0xB41, (0, 0))[1] == 0x4A and s.enabled)

    # e) avbryt ändrar inget
    before = dict(u.registered)
    answer(None)
    c._change_quick_add_hotkey_dialog()
    check("avbryt: ingenting ändras", u.registered == before and s.quick == "Ctrl+Alt+J")
    teardown()

    # f) avstängd i settings vid start: filter ändå, men ingen registrering
    u = FakeUser32(); setup(u)
    s = FakeSettings(); s.enabled = False; c = Ctl(s)
    c._install_global_quick_add()
    check("start/av: ingen snabbtangent", 0xB41 not in u.registered)
    check("start/av: filter installerat", len(c._app.filters) == 1)
    answer("Alt+Shift+N")
    c._change_quick_add_hotkey_dialog()
    check("start/av → på via menyn", 0xB41 in u.registered and s.enabled)
    # nedstängning avregistrerar allt och tar bort filtret
    c._uninstall_global_quick_add()
    check("nedstängning: allt avregistrerat", not u.registered and not c._app.filters, str(u.registered))
    teardown()

    # g) normal start
    u = FakeUser32(); setup(u)
    s = FakeSettings(); c = Ctl(s)
    c._install_global_quick_add()
    check("normal start: Ctrl+Alt+N + Ctrl+Alt+V", u.registered.get(0xB41, (0, 0))[1] == 0x4E
          and u.registered.get(0xB42) == (3, 0x56), str(u.registered))
    # ogiltig sparad kombination → default
    teardown()
    u = FakeUser32(); setup(u)
    s = FakeSettings(); s.quick = "skräp"; c = Ctl(s)
    c._install_global_quick_add()
    check("ogiltig sparad → default", u.registered.get(0xB41, (0, 0))[1] == 0x4E)
finally:
    teardown()

# ===========================================================================
# 3. riktig dialog (egen process)
# ===========================================================================
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _qtenv import qt_env  # noqa: E402

work = Path(tempfile.mkdtemp(prefix="taskbord_hk_"))
env, why = qt_env(work)
if env is None:
    print(f"  (dialogdelen hoppas över: {why})")
else:
    r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--dialog"], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=120)
    line = [l for l in r.stdout.splitlines() if l.startswith("DIALOG ")]
    if line:
        _, n_ok, n_fail = line[-1].split()
        ok += int(n_ok)
        fail += int(n_fail)
        for l in r.stdout.splitlines():
            if l.strip().startswith("✗"):
                print(l)
    else:
        check("dialogprocessen körde klart", False, (r.stdout + r.stderr)[-600:])
shutil.rmtree(work, ignore_errors=True)

print(f"\nhotkey_test: {ok} lyckades, {fail} misslyckades")
sys.exit(1 if fail else 0)
