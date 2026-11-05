#!/usr/bin/env python3
"""
pip_update_test.py — veckounderhåll: Pythons tillägg uppdateras (Python själv inte) en gång i veckan (helst måndag 08:00),
inte vid varje start. Samma Python, ingen egen miljö.

Kör:  python tester/pip_update_test.py     (inget nät, ingen Qt; pip ersätts av en attrapp)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
import pip_update as PU  # noqa: E402

ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("  ✗", name, extra)


def newdir(with_opt=True):
    d = Path(tempfile.mkdtemp(prefix="ledgebord_pip_"))
    (d / "requirements.txt").write_text("PySide6>=6.5.0\n", encoding="utf-8")
    if with_opt:
        (d / "requirements-optional.txt").write_text("reportlab>=4.0\n", encoding="utf-8")
    return d


class Fake:
    def __init__(self, outs):
        self.calls, self.outs = [], list(outs)

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        o = self.outs.pop(0)
        if isinstance(o, Exception):
            raise o
        rc, out, err = o
        return subprocess.CompletedProcess(cmd, rc, out, err)


def logtxt(d):
    p = d / "loggar" / PU.LOG_NAME
    return p.read_text(encoding="utf-8") if p.exists() else ""


# --- 1. uppdatering: samma Python, ingen egen miljö -------------------------------------------------------
d = newdir()
f = Fake([(0, "Successfully installed PySide6-6.11.3 shiboken6-6.11.3\n", ""), (0, "Requirement already satisfied\n", "")])
r = PU.update(d, runner=f, running=False)
check("två pip-anrop (obligatoriska, sedan valfria)", len(f.calls) == 2)
cmd = f.calls[0][0]
check("körs med den installerade Pythons pip (sys.executable -m pip install)", cmd[:4] == [sys.executable, "-m", "pip", "install"])
check("ingen venv/--target/--user: paketen hamnar i samma Python", not any(x in cmd for x in ("--target", "--user", "venv", "-t")))
check("--upgrade -r requirements.txt", "--upgrade" in cmd and cmd[cmd.index("-r") + 1].endswith("requirements.txt"))
check("2:a anropet tar requirements-optional.txt", f.calls[1][0][f.calls[1][0].index("-r") + 1].endswith("requirements-optional.txt"))
check("nät-timeout/retries satta så offline inte hänger", "--timeout" in cmd and "--retries" in cmd and "--no-input" in cmd)
check("resultat: uppdaterade + versioner", r["status"] == "uppdaterade" and r["updated"] == ["PySide6 6.11.3", "shiboken6 6.11.3"], r)
check("loggen: uppdaterade-raden och 'alla paket är aktuella'", "uppdaterade PySide6 6.11.3, shiboken6 6.11.3" in logtxt(d) and "alla paket är aktuella" in logtxt(d))
check("logg i loggar/ i appmappen", (d / "loggar" / PU.LOG_NAME).exists())
check("ingen strategi som uppgraderar delade beroenden i onödan (inte --upgrade-strategy eager)", "eager" not in " ".join(cmd))

# --- 2. allt aktuellt ----------------------------------------------------------------------------------------
d = newdir()
r = PU.update(d, runner=Fake([(0, "Requirement already satisfied: x\n", "")] * 2), running=False)
check("inget nytt → status ok", r["status"] == "ok" and r["updated"] == [])

# --- 3. offline / fel stoppar aldrig ---------------------------------------------------------------------------
d = newdir()
r = PU.update(d, runner=Fake([(1, "", "WARNING: Retrying\nERROR: Could not find a version\n"), (1, "", "ERROR: x\n")]), running=False)
check("pip-fel → status fel, ingen krasch", r["status"] == "fel" and len(r["failed"]) == 2)
check("loggen säger obligatoriska/valfria och offline", "OBLIGATORISKA" in logtxt(d) and "valfria" in logtxt(d) and "offline" in logtxt(d))
d = newdir()
r = PU.update(d, runner=Fake([subprocess.TimeoutExpired("pip", 1), (0, "", "")]), running=False)
check("timeout → avbryts, loggas, nästa fil körs ändå", r["failed"] == ["requirements.txt"] and "tog för lång tid" in logtxt(d))
d = newdir()
r = PU.update(d, runner=Fake([RuntimeError("boom")]), running=False)
check("oväntat undantag fångas", r["status"] == "fel" and "oväntat fel" in logtxt(d))
d = newdir(with_opt=False)
f = Fake([(0, "", "")])
PU.update(d, runner=f, running=False)
check("saknas requirements-optional.txt → bara ett anrop", len(f.calls) == 1)
d = Path(tempfile.mkdtemp(prefix="ledgebord_pip_"))
f = Fake([])
r = PU.update(d, runner=f, running=False)
check("inga requirements-filer → inget körs, inget fel", not f.calls and r["status"] == "ok")

# --- 4. körs appen redan: hoppa över ---------------------------------------------------------------------------
d = newdir()
f = Fake([])
r = PU.update(d, runner=f, running=True)
check("appen kör → inget pip-anrop (inlästa filer kan inte bytas)", r["status"] == "hoppade" and not f.calls and "körs redan" in logtxt(d))


class H(BaseHTTPRequestHandler):
    body = {"app": "Ledgebord"}

    def do_GET(self):
        b = json.dumps(self.body).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):
        pass


srv = HTTPServer(("127.0.0.1", 0), H)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
check("app_running: /health svarar Ledgebord → True", PU.app_running(ports=(port,)) is True)
H.body = {"app": "Task" + "Bord"}
check("app_running: äldre version (gamla namnet) räknas", PU.app_running(ports=(port,)) is True)
H.body = {"app": "NågotAnnat"}
check("app_running: annan tjänst på porten → False", PU.app_running(ports=(port,)) is False)
srv.shutdown()
check("app_running: inget lyssnar → False", PU.app_running(ports=(port,)) is False)

# --- 5. hjälpfunktioner / logg -----------------------------------------------------------------------------------
check("installed_names", PU.installed_names("blah\nSuccessfully installed a-b-1.0 c-2\n") == ["a-b 1.0", "c 2"] and PU.installed_names("nothing") == [])
d = newdir()
for i in range(PU.KEEP_LINES + 50):
    PU.log_line(d, f"rad {i}")
lines = logtxt(d).splitlines()
check("loggen begränsas till de senaste raderna", len(lines) == PU.KEEP_LINES and lines[-1].endswith(f"rad {PU.KEEP_LINES + 49}"))
check("log_line kastar aldrig (omöjlig mapp)", PU.log_line(Path("/proc/finns/inte"), "x") is None)

# --- 6. veckan: måndag 08:00 ---------------------------------------------------------------------------------------
from datetime import datetime as D, timedelta as TD  # noqa: E402

check("slot: torsdag 5 nov → måndag 2 nov 08:00", PU.slot_start(D(2026, 11, 5, 10)) == D(2026, 11, 2, 8))
check("slot: måndag 07:59 → förra måndagen", PU.slot_start(D(2026, 11, 9, 7, 59)) == D(2026, 11, 2, 8))
check("slot: måndag 08:00 → den dagen", PU.slot_start(D(2026, 11, 9, 8, 0)) == D(2026, 11, 9, 8))
check("slot: söndag kväll → måndagen före", PU.slot_start(D(2026, 11, 15, 23, 0)) == D(2026, 11, 9, 8))
NOW = D(2026, 11, 5, 10, 0)           # torsdag
d = newdir()
check("due: inget tillstånd → dags", PU.weekly_due(d, NOW) is True)
PU.mark_ok(d, "x", D(2026, 11, 2, 8, 5))
check("due: gjort måndag 08:05 → inte dags resten av veckan", PU.weekly_due(d, NOW) is False and PU.weekly_due(d, D(2026, 11, 8, 23)) is False)
check("due: nästa måndag 07:59 fortfarande inte dags", PU.weekly_due(d, D(2026, 11, 9, 7, 59)) is False)
check("due: nästa måndag 08:00 → dags igen", PU.weekly_due(d, D(2026, 11, 9, 8, 0)) is True)
d = newdir()
PU.mark_ok(d, "x", D(2026, 11, 1, 20))     # söndag kvällen före → räknas inte för denna vecka
check("due: underhåll före måndag 08:00 räknas inte", PU.weekly_due(d, NOW) is True)
d = newdir()
PU._write_state(d, last_try=D(2026, 11, 5, 8, 0).isoformat())
check("due: misslyckat försök för <6 h sedan → vänta", PU.weekly_due(d, NOW) is False)
check("due: …efter 6 h → ett nytt försök", PU.weekly_due(d, D(2026, 11, 5, 14, 1)) is True)
check("appen kör: försök redan denna vecka → ingen omstart igen", PU.app_may_restart_for_it(d, D(2026, 11, 5, 15)) is False)
d = newdir()
check("appen kör: inget försök denna vecka → får starta om (en gång)", PU.app_may_restart_for_it(d, NOW) is True)
PU.mark_try(d, NOW)
check("…och efter försöket inte mer den veckan", PU.app_may_restart_for_it(d, NOW + TD(hours=7)) is False)
check("…men nästa måndag 08:00 igen", PU.app_may_restart_for_it(d, D(2026, 11, 9, 8, 0)) is True)
check("trasig tillståndsfil → dags (kraschar inte)", (lambda dd: (PU._state_path(dd).parent.mkdir(parents=True, exist_ok=True), PU._state_path(dd).write_text("{trasig", encoding="utf-8"), PU.weekly_due(dd, NOW))[2])(newdir()) is True)

# --- --due / --run via main ---------------------------------------------------------------------------------------
o_due, o_run, o_mt, o_mo, o_up = PU.weekly_due, PU.app_running, PU.mark_try, PU.mark_ok, PU.update
rec = []
PU.mark_try = lambda *a, **k: rec.append("try")
PU.mark_ok = lambda *a, **k: rec.append("ok")
PU.weekly_due, PU.app_running = (lambda *a, **k: True), (lambda *a, **k: False)
check("--due: dags och appen kör inte → exit 10", PU.main(["--due", "--quiet"]) == 10)
PU.app_running = lambda *a, **k: True
check("--due: appen kör → exit 0 (rör inget)", PU.main(["--due", "--quiet"]) == 0)
PU.app_running = lambda *a, **k: False
PU.weekly_due = lambda *a, **k: False
check("--due: gjort → exit 0", PU.main(["--due", "--quiet"]) == 0)
PU.update = lambda *a, **k: {"status": "uppdaterade", "updated": ["a 1"], "failed": []}
rec.clear()
check("--run: lyckat → veckan bockas av, exit 0", PU.main(["--run", "--quiet"]) == 0 and rec == ["try", "ok"], rec)
PU.update = lambda *a, **k: {"status": "fel", "updated": [], "failed": ["x"]}
rec.clear()
check("--run: fel (offline) → INTE avbockad (nytt försök efter 6 h), exit 0", PU.main(["--run", "--quiet"]) == 0 and rec == ["try"], rec)
PU.update = lambda *a, **k: {"status": "hoppade", "updated": [], "failed": []}
rec.clear()
check("--run: appen kör → inte avbockad", PU.main(["--run", "--quiet"]) == 0 and rec == ["try"], rec)
rec.clear()
check("--mark → avbockad", PU.main(["--mark", "--quiet"]) == 0 and rec == ["ok"])
PU.weekly_due, PU.app_running, PU.mark_try, PU.mark_ok, PU.update = o_due, o_run, o_mt, o_mo, o_up

# --- wait_app_exit ------------------------------------------------------------------------------------------------
seq = iter([True, True, False])
slept = []
check("wait_app_exit: avstängd efter två sekunder → True", PU.wait_app_exit(10, 1, lambda: next(seq), slept.append) is True and slept == [1, 1])
check("wait_app_exit: kör kvar → False efter max", PU.wait_app_exit(3, 1, lambda: True, lambda s: None) is False)

# --- behövs något? (appens bakgrundskoll) ---------------------------------------------------------------------------
d = newdir()
f = Fake([(0, "Would install PySide6-6.11.4 shiboken6-6.11.4\n", ""), (0, "Requirement already satisfied\n", "")])
r = PU.needs_update(d, runner=f)
check("needs_update: paket med nyare version hittas via --dry-run", r["packages"] == ["PySide6-6.11.4", "shiboken6-6.11.4"] and not r["error"], r)
check("needs_update: kör pip med --dry-run (installerar inget)", all("--dry-run" in c[0] for c in f.calls))
check("needs_update: Python själv kollas inte (ingen latest_patch, inget 'python'-fält)", not hasattr(PU, "latest_patch") and "python" not in PU.needs_update(newdir(), runner=Fake([(0, "", ""), (0, "", "")])))
check("needs_update: allt aktuellt → tomt", (lambda r: not r["packages"] and not r["error"])(PU.needs_update(newdir(), runner=Fake([(0, "", "")] * 2))))
r = PU.needs_update(newdir(), runner=Fake([(1, "", "ERROR: Could not find a version\n")]))
check("needs_update: nätfel (obligatoriska) → error, ingen omstart", r["error"] and not r["packages"], r)
r = PU.needs_update(newdir(), runner=Fake([subprocess.TimeoutExpired("pip", 1)]))
check("needs_update: timeout → error", "lång tid" in r["error"])
r = PU.needs_update(newdir(), runner=Fake([(0, "", ""), (1, "", "ERROR: optional")]))
check("needs_update: fel i valfria tillägg avgör inget", not r["error"])

# --- omstart för underhållet ------------------------------------------------------------------------------------------
d = newdir()
(d / "FORSTA_START.bat").write_text("@echo off\r\n", encoding="utf-8")
check("maintenance_command: None utanför Windows", sys.platform == "win32" or PU.maintenance_command(d) is None)
real = sys.platform
sys.platform = "win32"
try:
    cmd = PU.maintenance_command(d, 8)
    check("maintenance_command (Windows): python -c <program> <delay> <bat> <mapp>", cmd[1] == "-c" and cmd[3:] == ["8", str(d / "FORSTA_START.bat"), str(d)], cmd)
    check("…programmet citerar sökvägen själv (blanksteg i mappnamn går bra) och kör /snabb /vecka dolt",
          "' + sys.argv[2] + '" in cmd[2] and "/snabb /vecka" in cmd[2] and "0x08000000" in cmd[2])
    check("…och är giltig Python", compile(cmd[2], "x", "exec") is not None)
    got = []
    check("schedule_maintenance: startar hjälparen", PU.schedule_maintenance(d, 8, popen=lambda c, **k: got.append((c, k))) is True and got and got[0][1]["cwd"] == str(d))
    check("schedule_maintenance: Popen-fel → False (ingen krasch)", PU.schedule_maintenance(d, 8, popen=lambda *a, **k: (_ for _ in ()).throw(OSError("x"))) is False)
    (d / "FORSTA_START.bat").unlink()
    check("saknas FORSTA_START.bat → None", PU.maintenance_command(d) is None)
finally:
    sys.platform = real

# --- appens veckokoll (MaintenanceMixin) ------------------------------------------------------------------------------
import time as _t  # noqa: E402
from types import SimpleNamespace  # noqa: E402

sys.path.insert(0, str(ROOT))
import app.mixins.maintenance as MM  # noqa: E402
from app.constants import AppMode  # noqa: E402


class Ctl(MM.MaintenanceMixin):
    def __init__(self):
        self._mode = AppMode.NORMAL if hasattr(AppMode, "NORMAL") else None
        self._log = type("L", (), {"info": lambda s, *a, **k: None, "warning": lambda s, *a, **k: None, "debug": lambda s, *a, **k: None})()
        self._start_time = _t.time() - 3600
        self.busy = ""
        self.events = []
        self._weekly_state = ""
        self._weekly_result = None
        self._weekly_wait = 0

    def _update_busy_reason(self): return self.busy
    def _remember_hidden_for_restart(self): self.events.append("hidden")
    def _flush_window_state(self, why): self.events.append("flush")
    def shutdown(self): self.events.append("shutdown")


wd = newdir()
MM.SCRIPT_DIR = wd
MM.sys = SimpleNamespace(platform="win32")
sched = []
PUm = PU
o_sm, o_nu = PUm.schedule_maintenance, PUm.needs_update
PUm.schedule_maintenance = lambda *a, **k: sched.append(1) or True
import core.pip_update as _cp  # noqa: E402  (samma modul via core.-sökvägen — mixin importerar den)
_cp.schedule_maintenance = PUm.schedule_maintenance


def tick(c, n=1):
    for _ in range(n):
        c._weekly_maintenance_check()
        for _w in range(200):
            if c._weekly_state != "checking":
                break
            _t.sleep(0.01)


def set_needs(res):
    _cp.needs_update = lambda *a, **k: res


set_needs({"packages": ["PySide6-6.11.4"], "python": "", "error": ""})
c = Ctl()
c._start_time = _t.time() - 30
tick(c)
check("veckokoll: inte direkt efter start (<10 min)", c._weekly_state == "" and not sched)
c = Ctl()
c.busy = "du skriver en ny uppgift"
tick(c, 3)
check("veckokoll: något att uppdatera men du är upptagen → väntar, ingen omstart", c._weekly_state == "ready" and not sched and "shutdown" not in c.events)
c.busy = ""
tick(c)
check("veckokoll: lugnt → sparar fönsterläge, schemalägger och avslutar (tyst omstart)", sched == [1] and c.events == ["hidden", "flush", "shutdown"], (sched, c.events))
check("veckokoll: försöket är bokfört (högst en omstart/vecka)", PU.app_may_restart_for_it(wd) is False)
c2 = Ctl()
tick(c2, 3)
check("veckokoll: ny app-instans samma vecka startar inte om igen", c2._weekly_state == "" and len(sched) == 1)

wd = newdir()
MM.SCRIPT_DIR = wd
sched.clear()
set_needs({"packages": [], "python": "", "error": ""})
c = Ctl()
tick(c, 2)
check("veckokoll: allt aktuellt → veckan avbockad utan omstart", c._weekly_state == "done" and not sched and PU.weekly_due(wd) is False and c.events == [])
wd = newdir()
MM.SCRIPT_DIR = wd
set_needs({"packages": [], "python": "", "error": "Could not find a version"})
c = Ctl()
tick(c, 2)
check("veckokoll: offline → ingen omstart, inte avbockad (nytt försök efter 6 h)", c._weekly_state == "done" and not sched and c.events == [] and PU.weekly_due(wd, D.now() + TD(hours=7)) is True)
wd = newdir()
MM.SCRIPT_DIR = wd
set_needs({"packages": [], "python": "3.99.9", "error": ""})
c = Ctl()
tick(c, 2)
check("veckokoll: en ny Python-version räknas INTE (Python uppdateras inte) → ingen omstart, veckan bockas av", not sched and "shutdown" not in c.events and PU.weekly_due(wd, D.now()) is False)
wd = newdir()
MM.SCRIPT_DIR = wd
sched.clear()
c = Ctl()
c.busy = "en dialog är öppen"
tick(c)
MM.sys = SimpleNamespace(platform="linux")
c3 = Ctl()
tick(c3)
check("veckokoll: bara på Windows (bat finns bara där)", c3._weekly_state == "")
MM.sys = SimpleNamespace(platform="win32")
c = Ctl()
c.busy = "en dialog är öppen"
c._weekly_state = "ready"
c._weekly_result = {"packages": ["x-1"], "python": "", "error": ""}
for _i in range(MM.MaintenanceMixin.WEEKLY_MAX_WAIT_TICKS):
    c._weekly_maintenance_check()
check("veckokoll: väntar högst ~3 h på lugn, ger sedan upp (görs vid nästa start)", c._weekly_state == "done" and not c.events)
check("veckokoll anropas var 5:e minut från _periodic_cleanup", "_weekly_maintenance_check()" in (ROOT / "app/mixins/maintenance.py").read_text(encoding="utf-8"))
PUm.schedule_maintenance, PUm.needs_update = o_sm, o_nu

# --- batchfilen: veckounderhåll, inte vid varje start ---------------------------------------------------------------------
raw = (ROOT / "FORSTA_START.bat").read_bytes()
bat = raw.decode("ascii")
check("bat: CRLF + ASCII", b"\n" not in raw.replace(b"\r\n", b""))
lines = bat.replace("\r\n", "\n").split("\n")
check("bat: /snabb med Python går via :snabb_paket", 'if "%SNABB%"=="1" if defined PY goto :snabb_paket' in bat)
i = lines.index(":snabb_paket")
blk = "\n".join(lines[i:lines.index(":vecko_kor")])
check("bat: tar bara den vanliga starten via '--due' (exit 10 = dags) — inte vid varje start",
      'pip_update.py" --due' in blk and "if errorlevel 10 goto :vecko_kor" in blk and "goto :start_app" in blk.split("if errorlevel 10 goto :vecko_kor")[1])
check("bat: /vecka (appen startade om för underhållet) går direkt till underhållet", 'if /i "%~2"=="/vecka" goto :vecko_kor' in blk)
vk = "\n".join(lines[lines.index(":vecko_kor"):lines.index(":start_app")])
check("bat: underhållet väntar tills appen avslutats, sedan paketen — och rör inte Python",
      vk.index("--wait-exit") < vk.index("--run") and "if errorlevel 1 goto :start_app" in vk and "python" not in vk.lower().replace("pip_update", ""))
check("bat: ingen Python-uppdatering finns kvar (inga upgrade_python/vecko_python, inget -Serie)", not re.search(r"upgrade_python|vecko_python|-Serie|upgrade_winget|upgrade_allusers", bat))
check("bat: hela flödet (FORSTA_START utan /snabb) bockar av veckan (--mark)", "pip_update.py\" --mark" in bat)
check("bat: ingen venv i batchfilens kommandon", not any("venv" in l.lower() for l in lines if not l.lstrip().upper().startswith("REM")))
labels = {l[1:].strip().lower() for l in lines if l.startswith(":") and not l.startswith("::")}
check("bat: alla goto/call-mål finns", all(j.lower() in labels or j.lower() == "eof" for j in re.findall(r"(?:goto|call)\s+:(\w+)", bat, re.I)))
check("bat: helt flöde går inte in i :snabb_paket (ingen dubbelkörning)", lines[i - 2].strip() == "goto :start_app")
check("pip_update.py: bara standardbibliotek", not re.search(r"^\s*(?:from|import)\s+(?:core|PySide6|ui|app)\b", (ROOT / "core/pip_update.py").read_text(encoding="utf-8"), re.M))
for _x in list(Path(tempfile.gettempdir()).glob("ledgebord_pip_*")):
    import shutil
    shutil.rmtree(_x, ignore_errors=True)

print(f"\npip_update_test: {ok} lyckades, {fail} misslyckades")
sys.stdout.flush()
os._exit(1 if fail else 0)
