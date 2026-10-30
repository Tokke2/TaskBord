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
    "_update_failed_fp", "_begin_install", "_auto_install_blocker", "_update_busy_reason",
    "_auto_install_when_idle", "_toggle_auto_install",
    "_confirm_and_install", "_update_ui_state", "_push_update_state", "_on_update_button",
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
    def singleShot(ms, f): FakeTimer.shots.append((ms, f))
    shots: list = []


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
        self.auto, self.auto_fp = False, ""   # tyst installation: av i de gamla scenarierna
    def update_check_enabled(self): return self.enabled
    def set_update_check_enabled(self, v): self.enabled = v
    def update_last_check(self): return self.last
    def set_update_last_check(self, v): self.last = v
    def update_notified(self): return self.notified
    def set_update_notified(self, v): self.notified = v
    def update_failed(self): return getattr(self, "failed", "")
    def update_auto_install(self): return self.auto
    def set_update_auto_install(self, v): self.auto = v
    def update_auto_fp(self): return self.auto_fp
    def set_update_auto_fp(self, v): self.auto_fp = v


class Log:
    def __getattr__(self, n): return lambda *a, **k: None


class Tray:
    def __init__(self): self.msgs = []; self.messageClicked = type("M", (), {"connect": lambda s, f: None})()
    def showMessage(self, title, text, icon, ms): self.msgs.append((title, text))


class FakeApp:
    modal = None
    popup = None
    def activeModalWidget(self): return self.modal
    def activePopupWidget(self): return self.popup


class FakeLock:
    def __enter__(self): return self
    def __exit__(self, *a): return False


class FakeInput:
    def __init__(self, text=""): self._t = text
    def text(self): return self._t


class FakeWidget:
    def __init__(self, text="", inline=None, drag=False):
        self.input_field = FakeInput(text)
        self._inline_edit = inline
        self._drag_active = drag


class Stub:
    _mode = "normal"
    AUTO_INSTALL_MAX_WAIT = 3
    UPDATE_INFO_FRESH_SEC = 1800
    UPDATE_CURRENT_FLASH_SEC = 8
    def __init__(self):
        self.settings = FakeSettings()
        self._widget_lock = FakeLock()
        self._widgets = {"w": FakeWidget()}
        self.waits = []
        self._tray = Tray()
        self._app = FakeApp()
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
    def _flush_window_state(self, why): self.__dict__.setdefault("flushed", []).append(why)
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

# 8. git-mapp -> automatisk koll görs ändå (mot releasen, inte main)
(APP / ".git").mkdir()
s5 = Stub()
s5._auto_update_check()
check("git-mapp: automatisk koll mot releasen görs", getattr(s5, "_update_busy", False) is True)
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
check("fönsterläget sparades före installation och före omstart", getattr(m, "flushed", []) == ["före uppdatering", "före omstart"])
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


# ===== 10. TYST INSTALLATION + TYST OMSTART (2026-10-26) =====================================
(APP / "main.pyw").write_bytes(b"print('v1')\n")
(APP / "core" / "y.py").unlink(missing_ok=True)
STATE["slow"] = 0.0
STATE["zip"] = make_zip({"main.pyw": b"print('v9')\n", "core/x.py": b"A=9\n"})


def reset_app():
    """Tillbaka till 'gamla' installationen (main.pyw v1, ingen core/x.py)."""
    (APP / "main.pyw").write_bytes(b"print('v1')\n")
    (APP / "core" / "x.py").unlink(missing_ok=True)


def auto_stub(**kw):
    st = Stub()
    st.settings.auto = True
    for k, v in kw.items():
        setattr(st.settings, k, v)
    return st


a = auto_stub()
a._auto_update_check()
check("tyst installation: klar", run(a))
check("tyst installation: inga dialoger och inga förloppsfönster", not a.dialogs and not a.pds)
check("tyst installation: ingen tray-notis", not a._tray.msgs)
check("tyst installation: filerna byttes", (APP / "main.pyw").read_bytes() == b"print('v9')\n")
check("tyst installation: js/ orörd", (APP / "js" / "active.json").read_text() == "{}")
check("tyst omstart: appen avslutas (väktaren startar den nya)", a.shut == [1])
check("uppgifter + fönsterläge sparades före bytet och före omstarten",
      "före uppdatering" in a.saved and getattr(a, "flushed", []) == ["före uppdatering", "före tyst omstart"])
check("fingeravtryck sparat före bytet (skydd mot loop)", len(a.settings.auto_fp) == 16)
check("ingen fråga ställdes", not any(d[0] == "ask" for d in a.dialogs))

# samma uppdatering igen (t.ex. filerna blev aldrig lika) -> ingen ny omstart, bara vanlig notis
reset_app()
b = auto_stub(auto_fp=a.settings.auto_fp)
b._auto_update_check()
run(b)
check("loopskydd: samma uppdatering installeras inte automatiskt två gånger", b.shut == [] and (APP / "main.pyw").read_bytes() == b"print('v1')\n")
check("loopskydd: användaren får i stället den vanliga notisen", len(b._tray.msgs) == 1)

# avstängd inställning -> som förut (bara notis)
c = auto_stub(auto=False)
c._auto_update_check()
run(c)
check("avstängd tyst installation: bara notis, inget byts", len(c._tray.msgs) == 1 and c.shut == [] and (APP / "main.pyw").read_bytes() == b"print('v1')\n")

# upptaget: dialog / meny / redigering / drag / text i inmatningsfältet -> väntar
for label, setup in (
    ("öppen dialog", lambda st: setattr(st._app, "modal", object())),
    ("öppen meny", lambda st: setattr(st._app, "popup", object())),
    ("inline-redigering", lambda st: st._widgets.update(w=FakeWidget(inline=object()))),
    ("drag av kort", lambda st: st._widgets.update(w=FakeWidget(drag=True))),
    ("text i inmatningsfältet", lambda st: st._widgets.update(w=FakeWidget(text="halvskriven uppgift"))),
):
    FakeTimer.shots.clear()
    d = auto_stub()
    setup(d)
    check(f"upptaget ({label}) ger en orsak", d._update_busy_reason() != "")
    d._auto_update_check()
    run(d)
    check(f"upptaget ({label}): ingen installation, ingen omstart", d.shut == [] and (APP / "main.pyw").read_bytes() == b"print('v1')\n")
    check(f"upptaget ({label}): försöker igen om en minut", FakeTimer.shots and FakeTimer.shots[-1][0] == 60_000)
    check(f"upptaget ({label}): ingen dialog", not d.dialogs)

# väntan som blir lugn -> installerar då
FakeTimer.shots.clear()
e = auto_stub()
e._app.modal = object()
e._auto_update_check()
run(e)
e._app.modal = None
FakeTimer.shots[-1][1]()   # minutens väntan är över
check("lugnt igen: installerar tyst och startar om", run(e) and e.shut == [1] and (APP / "main.pyw").read_bytes() == b"print('v9')\n")

# ger upp efter max väntan -> vanlig notis
reset_app()
FakeTimer.shots.clear()
g = auto_stub(auto_fp="")
g._app.modal = object()
g._auto_update_check()
run(g)
for _ in range(10):
    if not FakeTimer.shots:
        break
    FakeTimer.shots.pop()[1]()
check("väntar högst AUTO_INSTALL_MAX_WAIT gånger sedan notis i stället", len(g._tray.msgs) == 1 and g.shut == [] and (APP / "main.pyw").read_bytes() == b"print('v1')\n")

# requirements.txt ändrad -> aldrig tyst (kräver paketinstallation)
(APP / "requirements.txt").write_text("PySide6==1\n")
STATE["zip"] = make_zip({"main.pyw": b"print('v9')\n", "requirements.txt": b"PySide6==2\n"})
r = auto_stub()
r._auto_update_check()
run(r)
check("requirements ändrad: ingen tyst installation, bara notis", r.shut == [] and len(r._tray.msgs) == 1 and (APP / "main.pyw").read_bytes() == b"print('v1')\n")
(APP / "requirements.txt").unlink()
STATE["zip"] = make_zip({"main.pyw": b"print('v9')\n", "core/x.py": b"A=9\n"})

# uppdatering som återställdes förut -> ingen tyst installation
f = auto_stub()
f.settings.failed = updater.fingerprint(updater.check_for_update(APP, fake_http))
f._auto_update_check()
run(f)
check("återställd uppdatering installeras inte tyst", f.shut == [] and (APP / "main.pyw").read_bytes() == b"print('v1')\n")

# förra uppdateringen ännu obekräftad -> vänta
h = auto_stub()
h._update_guard_pending = True
h._auto_update_check()
run(h)
check("obekräftad förra uppdatering: ingen ny tyst installation", h.shut == [] and (APP / "main.pyw").read_bytes() == b"print('v1')\n")

# installationen misslyckas -> helt tyst, inget ändrat, ingen omstart
_real_apply = updater.apply_update
def _boom(*a, **k): raise updater.UpdateError("disk full")
updater.apply_update = _boom
k = auto_stub()
k._auto_update_check()
run(k)
check("misslyckad tyst installation: ingen dialog, ingen omstart", not k.dialogs and k.shut == [] and not k._tray.msgs)
check("misslyckad tyst installation: appen kan köra vidare (inte upptagen)", k._update_busy is False)
updater.apply_update = _real_apply

# omstarten går inte att schemalägga -> tyst, appen kör vidare
_real_restart = updater.schedule_restart
updater.schedule_restart = lambda app_dir, *a, **kw: False
reset_app()
q = auto_stub()
q._auto_update_check()
run(q)
check("omstart ej möjlig: inga dialoger, appen avslutas inte", not q.dialogs and q.shut == [])
updater.schedule_restart = _real_restart

# tray-växlaren
t = auto_stub()
t._toggle_auto_install()
check("_toggle_auto_install slår av och på", t.settings.auto is False)
t._toggle_auto_install()
check("…och på igen", t.settings.auto is True)

# --- knappen i titelraden (⟳ → ⬆ Uppdatera → ⏳ Installerar…) ----------------------------------------------
class ButtonWidget(FakeWidget):
    def __init__(self):
        super().__init__()
        self.calls = []
    def set_update_state(self, state, tooltip="", count=0): self.calls.append((state, tooltip, count))


def btn_stub():
    b = Stub()
    b.rw = ButtonWidget()
    b._widgets = {"w": b.rw}
    return b


reset_app()
STATE["zip"] = make_zip({"main.pyw": b"print('v2')\n", "core/x.py": b"A=1\n"})
b = btn_stub()
st0 = b._update_ui_state()
check("knapp: vilande läge = idle med tooltip om senaste koll", st0[0] == "idle" and "Senast kollat: ännu inte" in st0[1])
b.ask_answer = False                      # första klicket: sök, men avböj installationen
b._on_update_button()
check("knapp: klick utan känd uppdatering söker (förloppsfönster)", len(b.pds) == 1 and b.rw.calls and b.rw.calls[-1][0] == "checking")
run(b)
asks = [d for d in b.dialogs if d[0] == "ask"]
check("knapp: sökningen visar frågan 'Ny version finns'", len(asks) == 1 and asks[0][1] == "Ny version finns")
check("knapp: efter avböjd installation står knappen som ⬆ med antal filer", b._update_ui_state()[0] == "available" and b._update_ui_state()[2] == 2)
check("knapp: fönstret fick läget 'available' + tooltip med release/commit", b.rw.calls[-1][0] == "available" and "abc1234" in b.rw.calls[-1][1] and "2 fil" in b.rw.calls[-1][1])
check("knapp: inget installerades än", (APP / "main.pyw").read_bytes() == b"print('v1')\n" and b._update_busy is False)
STATE["fail"] = True                      # ingen nätverkskoll ska behövas för att installera en redan hittad uppdatering
b.ask_answer = True
n_pds = len(b.pds)
b._on_update_button()
check("knapp: nytt klick installerar direkt (ingen ny sökning, bara en fråga till)", len([d for d in b.dialogs if d[0] == "ask"]) == 2 and len(b.pds) == n_pds + 1)
check("knapp: under installationen visas ⏳ Installerar", any(c[0] == "installing" for c in b.rw.calls))
run(b)
STATE["fail"] = False
check("knapp: filerna uppdaterades från den hittade uppdateringen", (APP / "main.pyw").read_bytes() == b"print('v2')\n" and (APP / "core" / "x.py").exists())
check("knapp: appen startade om (shutdown) efter lyckad installation", b.shut == [1])
check("knapp: efter installationen är läget idle igen", b._update_ui_state()[0] == "idle" and b.rw.calls[-1][0] == "idle")

# redan aktuell → ✓ Aktuell en kort stund
b2 = btn_stub()
b2._on_update_button()
run(b2)
check("knapp: manuell koll utan nyheter → '✓ Aktuell'", b2._update_ui_state()[0] == "current" and b2.rw.calls[-1][0] == "current")
check("knapp: texten återställs automatiskt efter några sekunder", any(ms >= 8000 for ms, _f in FakeTimer.shots))
b2._update_current_until = 0.0
b2._refresh_update_action()
check("knapp: … tillbaka till ⟳", b2.rw.calls[-1][0] == "idle")

# gammal träff (> 30 min) → ny sökning i stället för direktinstallation
reset_app()
b3 = btn_stub()
b3.ask_answer = False
b3._on_update_button(); run(b3)
b3._update_last_info_ts -= 3600
n_pds = len(b3.pds)
b3._on_update_button()
check("knapp: gammal träff → söker på nytt", len(b3.pds) == n_pds + 1 and b3.rw.calls[-1][0] == "checking")
run(b3)

# pågår redan → klicket ignoreras
b4 = btn_stub()
b4._update_busy = True
n_d = len(b4.dialogs)
b4._on_update_button()
check("knapp: klick under pågående sökning ignoreras", len(b4.pds) == 0 and len(b4.dialogs) == n_d)

# tyst koll ska inte blinka med 'Söker…'
reset_app()
STATE["zip"] = make_zip({"main.pyw": b"print('v9')\n"})
b5 = btn_stub()
b5._auto_update_check()
check("knapp: tyst koll visar aldrig 'Söker…'", all(c[0] != "checking" for c in b5.rw.calls))
run(b5)
check("knapp: tyst koll som hittar uppdatering (ej auto-installerad) → ⬆", b5._update_ui_state()[0] == "available")
reset_app()

print(f"\nupdater_flow_test: {ok} lyckades, {fail} misslyckades")
sys.exit(1 if fail else 0)
