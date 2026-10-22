"""
addon_notice_test.py — påminnelse när Thunderbird-tillägget (.xpi) ändrats.

core/addon_watch: baseline/same/new/missing, version ur manifest, referens från senaste
uppdateringens backup. AddonUpdateMixin mot låtsas-tray/-dialog: notis EN gång per ny fil,
tray-menyrad, dialogknappar (Visa filen / Jag har installerat det / Senare).
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import types
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for sub in ("", "core"):
    sys.path.insert(0, str(ROOT / sub))

from core import addon_watch as aw  # noqa: E402
from app.mixins import addon_update as au  # noqa: E402
from app.constants import AppMode  # noqa: E402

ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("  ✗", name, extra)


def make_xpi(path: Path, version: str, extra: str = "") -> None:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("manifest.json", json.dumps({"name": "Ledgebord", "version": version}))
        z.writestr("background.js", "// " + version + extra)


tmp = Path(tempfile.mkdtemp(prefix="taskbord_addon_"))
app = tmp / "app"
app.mkdir()

# --- core ------------------------------------------------------------------
st = aw.evaluate(app, "")
check("saknad .xpi → missing", st.state == "missing" and st.fingerprint == "")
make_xpi(aw.xpi_path(app), "1.0.0")
fp1 = aw.file_fingerprint(aw.xpi_path(app))
check("fingeravtryck är 40 tecken", len(fp1) == aw.FP_LEN)
check("version läses ur manifest", aw.addon_version(aw.xpi_path(app)) == "1.0.0")
check("trasig zip → tom version", aw.addon_version(app / "finns-inte.xpi") == "")
st = aw.evaluate(app, "")
check("ingen referens → baseline", st.state == "baseline" and st.fingerprint == fp1 and st.version == "1.0.0")
check("samma som bekräftad → same", aw.evaluate(app, fp1).state == "same")
make_xpi(aw.xpi_path(app), "1.0.0", "ändrad kod")     # samma versionsnummer, annat innehåll
fp2 = aw.file_fingerprint(aw.xpi_path(app))
check("annat innehåll (samma version) ger annat fingeravtryck", fp1 != fp2)
st = aw.evaluate(app, fp1)
check("ändrad .xpi → new", st.state == "new" and st.fingerprint == fp2)
check("…även när versionsnumret är oförändrat (v1.0.0 fortfarande)", st.version == "1.0.0")

# Första körningen, men senaste uppdateringen bytte ut .xpi:n (gamla ligger i backupen)
bk = app / "data" / "backups" / "app-update"
(bk / "20260101-000000").mkdir(parents=True)
make_xpi(bk / "20260101-000000" / aw.XPI_NAME, "0.9")
check("första körningen + backup med annan .xpi → new", aw.evaluate(app, "").state == "new")
shutil.copy(aw.xpi_path(app), bk / "20260101-000000" / aw.XPI_NAME)
check("backup-.xpi lika med nuvarande → baseline", aw.evaluate(app, "").state == "baseline")
# bara den allra senaste backupen räknas; en senare backup utan .xpi → baseline
(bk / "20260202-000000").mkdir()
(bk / "20260202-000000" / "UPPDATERING.txt").write_text("x")
make_xpi(bk / "20260101-000000" / aw.XPI_NAME, "0.5")
check("senaste backupen saknar .xpi → baseline (äldre ignoreras)", aw.evaluate(app, "").state == "baseline")

# reveal_in_folder: rätt kommando per OS
calls = []
orig_popen = aw.subprocess.Popen
aw.subprocess.Popen = lambda cmd, *a, **k: calls.append(cmd)
try:
    old = aw.sys.platform
    aw.sys.platform = "win32"
    aw.reveal_in_folder(aw.xpi_path(app))
    check("Windows: explorer /select, <fil>", calls[-1][:2] == ["explorer", "/select,"] and calls[-1][2].endswith(aw.XPI_NAME), str(calls))
    aw.sys.platform = "darwin"
    aw.reveal_in_folder(aw.xpi_path(app))
    check("macOS: open -R", calls[-1][:2] == ["open", "-R"])
    aw.sys.platform = "linux"
    aw.reveal_in_folder(aw.xpi_path(app))
    check("Linux: xdg-open mappen", calls[-1] == ["xdg-open", str(app)])
finally:
    aw.sys.platform = old
    aw.subprocess.Popen = orig_popen

# --- mixin -----------------------------------------------------------------
class FakeSettings:
    def __init__(self): self.seen = ""; self.notified = ""
    def addon_xpi_seen(self): return self.seen
    def set_addon_xpi_seen(self, v): self.seen = v; return True
    def addon_xpi_notified(self): return self.notified
    def set_addon_xpi_notified(self, v): self.notified = v; return True


class FakeLog:
    def __getattr__(self, n): return lambda *a, **k: None


class Signal:
    def __init__(self): self.slots = []
    def connect(self, f): self.slots.append(f)


class FakeTray:
    def __init__(self): self.messages = []; self.messageClicked = Signal()
    def showMessage(self, title, text, icon, ms): self.messages.append((title, text))


class FakeAction:
    def __init__(self, text, parent=None): self.text = text; self.triggered = Signal()
    def setToolTip(self, t): pass


class FakeBox:
    """Låtsas-QMessageBox: ``script`` = i vilken ordning knapparna 'klickas'."""
    script: list = []
    last = None
    class Icon: Information = 1
    class ButtonRole: ActionRole = 1; AcceptRole = 2; RejectRole = 3

    def __init__(self): self.buttons = {}; self._clicked = None; self.text = ""; FakeBox.last = self
    def setWindowTitle(self, t): pass
    def setIcon(self, i): pass
    def setText(self, t): self.text = t
    def addButton(self, label, role): b = object(); self.buttons[label] = b; return b
    def exec(self): self._clicked = self.buttons[FakeBox.script.pop(0)]
    def clickedButton(self): return self._clicked


class Ctl(au.AddonUpdateMixin):
    def __init__(self):
        self.settings = FakeSettings()
        self._log = FakeLog()
        self._tray = FakeTray()
        self._mode = AppMode.NORMAL
        self._QTimer = types.SimpleNamespace(singleShot=lambda ms, fn: self.timers.append((ms, fn)))
        self._QSystemTrayIcon = types.SimpleNamespace(MessageIcon=types.SimpleNamespace(Information=1))
        self._QMessageBox = FakeBox
        self._QAction = FakeAction
        self._tray_menu = None
        self.timers = []
        self.menu_rebuilds = 0
    def _populate_tray_menu(self): self.menu_rebuilds += 1


revealed = []
au.SCRIPT_DIR = app
orig_reveal = aw.reveal_in_folder
aw.reveal_in_folder = lambda p: revealed.append(Path(p)) or True
try:
    make_xpi(aw.xpi_path(app), "1.1.0")
    shutil.rmtree(app / "data")
    fpA = aw.file_fingerprint(aw.xpi_path(app))

    c = Ctl()
    c._init_addon_notice()
    check("start: kollen schemaläggs ~20 s efter start", c.timers and c.timers[0][0] == 20_000)
    c._check_addon_update()
    check("första körningen: tyst referens sparas", c.settings.seen == fpA and c._tray.messages == [])
    check("första körningen: ingen tray-menyrad", c._addon_tray_action() is None)

    # nu byts .xpi:n (som vid en uppdatering)
    make_xpi(aw.xpi_path(app), "1.2.0")
    fpB = aw.file_fingerprint(aw.xpi_path(app))
    c._check_addon_update()
    check("ny .xpi: tray-notis visas", len(c._tray.messages) == 1 and "Thunderbird" in c._tray.messages[0][0])
    check("ny .xpi: notisen anger inte att något installerats av oss", "installera om" in c._tray.messages[0][1])
    check("ny .xpi: notis markerad som visad", c.settings.notified == fpB)
    check("ny .xpi: referensen ÄNDRAS INTE förrän användaren bekräftar", c.settings.seen == fpA)
    act = c._addon_tray_action()
    check("ny .xpi: tray-menyrad finns", act is not None and "Nytt Thunderbird-tillägg" in act.text)
    check("ny .xpi: menyn byggs om", c.menu_rebuilds >= 1)
    c._check_addon_update()
    check("andra kollen: ingen ny notis (en gång per fil)", len(c._tray.messages) == 1)
    check("andra kollen: menyraden finns kvar", c._addon_tray_action() is not None)
    check("klick på notisen kopplad", len(c._tray.messageClicked.slots) == 1)

    # dialogen: Visa filen → dialogen visas igen → Senare
    FakeBox.script = ["📂 Visa filen", "Senare"]
    c._addon_update_dialog()
    check("dialog: Visa filen öppnar mappen med rätt fil", revealed == [aw.xpi_path(app)], str(revealed))
    check("dialog: texten nämner filen och installationsstegen",
          "Installera tillägg från fil" in FakeBox.last.text and aw.XPI_NAME in FakeBox.last.text)
    check("dialog: Senare bekräftar INTE", c.settings.seen == fpA and c._addon_state is not None)
    # Jag har installerat det
    FakeBox.script = ["✔ Jag har installerat det"]
    c._addon_update_dialog()
    check("dialog: bekräftad → referens uppdaterad", c.settings.seen == fpB)
    check("dialog: bekräftad → menyraden borta", c._addon_state is None and c._addon_tray_action() is None)
    n = len(c._tray.messages)
    c._check_addon_update()
    check("efter bekräftelse: tyst", len(c._tray.messages) == n and c._addon_tray_action() is None)

    # ny ändring igen → ny notis
    make_xpi(aw.xpi_path(app), "1.3.0")
    c._check_addon_update()
    check("ännu en ändring → ny notis", len(c._tray.messages) == n + 1)

    # klick på notis inom 30 s öppnar dialogen, gammal klick (annan notis) gör det inte
    FakeBox.script = ["Senare"]
    c._on_addon_message_clicked()
    check("notisklick → dialog", FakeBox.script == [])
    FakeBox.script = []
    c._on_addon_message_clicked()   # andra klicket: ts nollställd → ingen dialog (skulle krascha på tom script)
    check("andra notisklicket ignoreras", True)

    # saknad .xpi → inget hände, ingen krasch
    (app / aw.XPI_NAME).unlink()
    c._check_addon_update()
    check("saknad .xpi: ingen menyrad", c._addon_tray_action() is None)

    # felsäkert läge: ingen kontroll
    c2 = Ctl(); c2._mode = AppMode.SAFE_MODE; c2._init_addon_notice()
    check("säkert läge: schemaläggs inte", c2.timers == [])
    # utan tray: ingen krasch
    make_xpi(aw.xpi_path(app), "9.9.9")
    c3 = Ctl(); c3._tray = None; c3.settings.seen = "gammal"
    c3._check_addon_update()
    check("utan tray: menyrad ändå", c3._addon_tray_action() is not None)
finally:
    aw.reveal_in_folder = orig_reveal

shutil.rmtree(tmp, ignore_errors=True)
print(f"\naddon_notice_test: {ok} lyckades, {fail} misslyckades")
sys.exit(1 if fail else 0)
