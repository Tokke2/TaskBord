"""
Test av uppdateringsflödet i main.pyw (utan Qt-fönster): metoderna plockas ur app/mixins/updates.py
med ast och körs mot en stubb med falsk timer/dialog/inställningar + riktig updater
och falsk GitHub. Täcker tyst dagskoll, notis en gång per uppdatering och förlopp.
"""
import ast
import io
import json
import sys
import tempfile
import threading
import time
import zipfile
from contextlib import suppress
from pathlib import Path
from typing import Any, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core import updater  # noqa: E402

ok = fail = 0


def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("  ✗", name)


# --- plocka metoderna ur main.pyw -------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _src import app_files  # noqa: E402
trees = [ast.parse(p.read_text(encoding="utf-8")) for p in app_files(ROOT)]
NAMES = {
    "_update_progress_cb", "_update_progress_close", "_update_progress_refresh", "_update_cancel_requested",
    "_refresh_update_action", "_update_action_text", "_check_for_updates", "_update_finish",
    "_poll_update_check", "_finish_check", "_finish_apply", "_auto_update_check",
    "_notify_update_available", "_on_tray_message_clicked", "_toggle_auto_update",
    "_update_failed_fp",
}
methods = {}
for node in (n for t in trees for n in ast.walk(t)):
    if isinstance(node, ast.ClassDef):
        for f in node.body:
            if isinstance(f, ast.FunctionDef) and f.name in NAMES:
                methods[f.name] = f
check("alla uppdateringsmetoder finns i appens kod", set(methods) == NAMES)

APP = Path(tempfile.mkdtemp())
G = dict(SCRIPT_DIR=APP, LOG_PREFIX="[MAIN]", suppress=suppress, threading=threading, time=time,
         Tuple=Tuple, Any=Any, AppMode=type("AppMode", (), {"SAFE_MODE": "safe"}))
ns: dict = {}
exec(compile(ast.Module(body=list(methods.values()), type_ignores=[]), "main.pyw", "exec"), G, ns)


class FakeTimer:
    def __init__(self, *_a):
        self.running = False
        self.timeout = type("S", (), {"connect": lambda s, f: None})()
    def setInterval(self, ms): self.interval = ms
    def start(self): self.running = True
    def stop(self): self.running = False
    @staticmethod
    def singleShot(ms, f): pass


class FakePD:
    def __init__(self, text, maximum):
        self.text, self._max, self.value, self.vis = text, maximum, 0, True
        self.history = []
        self.canceled = type("C", (), {"disconnect": lambda s: None})()
    def setLabelText(self, t): self.text = t; self.history.append(t)
    def maximum(self): return self._max
    def setRange(self, a, b): self._max = b
    def setValue(self, v): self.value = v
    def isVisible(self): return self.vis
    def show(self): self.vis = True
    def close(self): self.vis = False
    def deleteLater(self): pass


class FakeSettings:
    def __init__(self):
        self.enabled, self.last, self.notified = True, 0, ""
    def update_check_enabled(self): return self.enabled
    def set_update_check_enabled(self, v): self.enabled = v
    def update_last_check(self): return self.last
    def set_update_last_check(self, v): self.last = v
    def update_notified(self): return self.notified
    def set_update_notified(self, v): self.notified = v
    def update_failed(self): return ""


class Log:
    def __getattr__(self, n): return lambda *a, **k: None


class Tray:
    def __init__(self): self.msgs = []; self.messageClicked = type("M", (), {"connect": lambda s, f: None})()
    def showMessage(self, title, text, icon, ms): self.msgs.append((title, text))


class Stub:
    _mode = "normal"
    def __init__(self):
        self.settings = FakeSettings()
        self._tray = Tray()
        self._app = None
        self._QTimer = FakeTimer
        self._QSystemTrayIcon = type("T", (), {"MessageIcon": type("I", (), {"Information": 1})})
        self._log = Log()
        self.dialogs, self.pds, self.saved, self.restarted, self.shut = [], [], [], [], []
        self.store = type("S", (), {"save": lambda s: self_saved.append(1)})()
        self_saved = self.saved
        self.ask_answer = True
        self._update_action = None
    def _update_dialog(self, kind, title, text):
        self.dialogs.append((kind, title, text)); return self.ask_answer if kind == "ask" else True
    def _update_progress_open(self, text, cancelable, maximum=0):
        self._update_pd = FakePD(text, maximum); self.pds.append(self._update_pd)
    def _external_backup(self, reason=""): self.saved.append(reason)
    def shutdown(self): self.shut.append(1)
    def _populate_tray_menu(self): pass


for n, f in ns.items():
    setattr(Stub, n, f)

# falsk GitHub
def make_zip(files):
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as z:
        for k, v in files.items():
            z.writestr("Tokke2-TaskBord-abc1234/" + k, v)
        z.comment = b"abc1234def5678abc1234def5678abc1234def56"
    return bio.getvalue()

STATE = {"zip": make_zip({"main.pyw": b"print('v2')\n", "core/x.py": b"A=1\n"}), "fail": False, "slow": 0.0}

def fake_http(url, max_bytes, timeout=20.0, accept="*/*", progress=None):
    if STATE["fail"]:
        raise updater.UpdateError("Kunde inte nå GitHub. Kontrollera internetanslutningen.")
    if url == updater.LATEST_API:
        return json.dumps({"tag_name": "v1.0.0", "zipball_url": "https://api.github.com/z"}).encode()
    data = STATE["zip"]
    if progress:
        for i in range(0, len(data), 1000):
            progress(min(i + 1000, len(data)), len(data))
            time.sleep(STATE["slow"])
    return data

_real_check = updater.check_for_update
updater.check_for_update = lambda app_dir, http_get=None, progress=None: _real_check(app_dir, fake_http, progress)
updater.schedule_restart = lambda app_dir, *a, **k: True

(APP / "main.pyw").write_bytes(b"print('v1')\n")
(APP / "core").mkdir()
(APP / "js").mkdir()
(APP / "js" / "active.json").write_text("{}")


def run(stub, limit=15.0):
    t0 = time.time()
    while stub._update_busy and time.time() - t0 < limit:
        if stub._update_timer.running:
            stub._poll_update_check()
        time.sleep(0.01)
    return not stub._update_busy


# 1. tyst koll hittar ny version -> notis, ingen dialog, inget installerat
s = Stub()
s._auto_update_check()
ok1 = run(s)
check("tyst koll blir klar", ok1)
check("tyst: inga dialoger/förloppsfönster", not s.dialogs and not s.pds)
check("tyst: en tray-notis om ny version", len(s._tray.msgs) == 1 and "Ny version" in s._tray.msgs[0][0])
check("tyst: senaste koll sparad", s.settings.last > 0)
check("tyst: inget installerades", (APP / "main.pyw").read_bytes() == b"print('v1')\n")
check("menytexten markerar ny version", s._update_action_text().startswith("🆕"))
fp = s.settings.notified
check("fingeravtryck sparat", len(fp) == 16)

# 2. direkt igen: inom dygnet -> ingen ny koll alls
n_msgs = len(s._tray.msgs)
s._auto_update_check()
check("inom 24 h görs ingen ny koll", not getattr(s, "_update_busy", False))

# 3. nästa dygn, samma uppdatering -> menytexten kvar men ingen ny notis
s.settings.last = int(time.time()) - 25 * 3600
s._auto_update_check()
run(s)
check("samma uppdatering notifieras inte igen", len(s._tray.msgs) == n_msgs)
check("…men markeringen finns kvar", s._update_available is True)

# 4. ny, annan uppdatering -> ny notis
STATE["zip"] = make_zip({"main.pyw": b"print('v3')\n"})
s.settings.last = int(time.time()) - 25 * 3600
s._auto_update_check()
run(s)
check("ny annan uppdatering ger ny notis", len(s._tray.msgs) == n_msgs + 1 and s.settings.notified != fp)

# 5. avstängd inställning -> ingen koll
s2 = Stub()
s2.settings.enabled = False
s2._auto_update_check()
check("avstängd: ingen koll", not hasattr(s2, "_update_busy") or not s2._update_busy)
check("avstängd: ingen tid sparad", s2.settings.last == 0)

# 6. nätverksfel: tyst, tid sparas inte (nytt försök vid nästa tick)
s3 = Stub()
STATE["fail"] = True
s3._auto_update_check()
run(s3)
check("tyst fel: inga dialoger/notiser", not s3.dialogs and not s3._tray.msgs)
check("tyst fel: tid sparas inte", s3.settings.last == 0)
STATE["fail"] = False

# 7. aktuell (inget skiljer) -> tyst, ingen notis, markering av
(APP / "main.pyw").write_bytes(b"print('v3')\n")
s4 = Stub()
s4._update_available = True
s4._auto_update_check()
run(s4)
check("aktuell: ingen notis", not s4._tray.msgs)
check("aktuell: markering rensas", s4._update_available is False and s4._update_action_text().startswith("🔄"))
(APP / "main.pyw").write_bytes(b"print('v1')\n")

# 8. git-mapp -> ingen automatisk koll
(APP / ".git").mkdir()
s5 = Stub()
s5._auto_update_check()
check("git-mapp: ingen automatisk koll", not hasattr(s5, "_update_busy") or not s5._update_busy)
(APP / ".git").rmdir()

# 9. manuell uppdatering: förlopp i båda faserna + installation + omstart
STATE["zip"] = make_zip({"main.pyw": b"print('v2')\n", "core/x.py": b"A=1\n", "core/y.py": b"B=1\n"})
STATE["slow"] = 0.002
m = Stub()
m._check_for_updates()
check("manuell: förloppsfönster öppnas direkt", len(m.pds) == 1 and m.pds[0].text.startswith("Kontaktar"))
done = run(m)
check("manuell: klar", done)
texts = [t for pd in m.pds for t in pd.history]
check("förlopp: nedladdning visas i MB", any("Hämtar uppdateringen" in t and "MB" in t for t in texts))
check("förlopp: sök-fönstret fick text för nedladdning före jämförelse", len(m.pds[0].history) >= 2)
check("två förloppsfönster (sök + installation)", len(m.pds) == 2)
check("installationsfönstret fick förloppstext", any(t.startswith(("Installerar", "Klart")) for t in m.pds[1].history))
check("uppgifter sparades före uppdatering", 1 in m.saved and "före uppdatering" in m.saved)
check("filer installerade", (APP / "main.pyw").read_bytes() == b"print('v2')\n" and (APP / "core" / "y.py").exists())
check("js/ orörd", (APP / "js" / "active.json").read_text() == "{}")
check("fråga ställdes", any(d[0] == "ask" for d in m.dialogs))
check("klart-dialog + omstart + avstängning", any(d[1] == "Uppdaterad" for d in m.dialogs) and m.shut == [1])
check("markering rensad efter installation", m._update_available is False)
check("alla förloppsfönster stängda", all(not pd.vis for pd in m.pds))

# 10. manuell, användaren säger Avbryt
(APP / "main.pyw").write_bytes(b"print('v1')\n")
m2 = Stub()
m2.ask_answer = False
m2._check_for_updates()
run(m2)
check("Avbryt i frågan: inget installerat", (APP / "main.pyw").read_bytes() == b"print('v1')\n" and not m2.shut)
check("Avbryt i frågan: klar för ny koll", m2._update_busy is False)

# 11. avbryt under nedladdning -> tyst avslut utan felruta
STATE["zip"] = make_zip({"main.pyw": b"print('v2')\n", "pad.bin": b"x" * 60000})
STATE["slow"] = 0.05
m3 = Stub()
m3._check_for_updates()
time.sleep(0.2)
m3._update_cancel_requested()
run(m3)
check("avbruten nedladdning: ingen felruta", not any(d[0] == "warn" for d in m3.dialogs))
check("avbruten nedladdning: inget installerat", (APP / "main.pyw").read_bytes() == b"print('v1')\n")
STATE["slow"] = 0

# 12. fel under installation -> varning, inget ändrat, ingen omstart
STATE["zip"] = make_zip({"main.pyw": b"print('v2')\n", "core/x.py": b"A=1\n"})
(APP / "main.pyw").write_bytes(b"print('v1')\n")
orig_apply = updater.apply_update
def bad_apply(app_dir, info, progress=None):
    raise updater.UpdateError("Installationen misslyckades och återställdes: disk full")
updater.apply_update = bad_apply
m4 = Stub()
m4._check_for_updates()
run(m4)
updater.apply_update = orig_apply
check("installationsfel: varning visas", any(d[0] == "warn" and "återställdes" in d[2] for d in m4.dialogs))
check("installationsfel: ingen omstart", not m4.shut)
check("installationsfel: fönster stängt + klar", m4._update_busy is False and all(not pd.vis for pd in m4.pds))

# 13. förloppsfönstrets logik (update_progress_refresh)
r = Stub()
r._update_pd = FakePD("x", 0)
r._update_progress = ("download", 500, 1000)
r._update_progress_refresh()
check("nedladdning med känd storlek: delvis fylld stapel", r._update_pd.maximum() == 1000 and r._update_pd.value == 500)
r._update_progress = ("download", 500, 0)
r._update_progress_refresh()
check("okänd storlek: obestämd stapel", r._update_pd.maximum() == 0)
r._update_progress = ("install", 2, 5)
r._update_progress_refresh()
check("installation: 2 av 5", r._update_pd.maximum() == 5 and r._update_pd.value == 2 and "2 av 5" in r._update_pd.text)
r._update_pd.vis = False
r._update_progress = ("install", 3, 5)
r._update_progress_refresh()
check("bortstängt installationsfönster visas igen", r._update_pd.vis)

print(f"\nupdater_flow_test: {ok} lyckades, {fail} misslyckades")
sys.exit(1 if fail else 0)
