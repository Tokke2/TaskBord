#!/usr/bin/env python3
"""
pip_update_test.py — vid varje start: kolla Pythons tillägg och uppdatera dem (samma Python, ingen egen miljö).

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
H.body = {"app": "TaskBord"}
check("app_running: äldre version (TaskBord) räknas", PU.app_running(ports=(port,)) is True)
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

# --- 6. main(): alltid exit 0, så starten aldrig stoppas -------------------------------------------------------------
orig = PU.update
PU.update = lambda *a, **k: {"status": "fel", "updated": [], "failed": ["x"]}
check("main returnerar alltid 0 (även vid fel)", PU.main(["--quiet"]) == 0)
PU.update = orig

# --- 7. batchfilen anropar den vid varje (snabb)start ----------------------------------------------------------------
raw = (ROOT / "FORSTA_START.bat").read_bytes()
bat = raw.decode("ascii")
check("bat: CRLF + ASCII", b"\n" not in raw.replace(b"\r\n", b""))
lines = bat.replace("\r\n", "\n").split("\n")
check("bat: /snabb med Python går via :snabb_paket (före start)", 'if "%SNABB%"=="1" if defined PY goto :snabb_paket' in bat)
i = lines.index(":snabb_paket")
check("bat: :snabb_paket kör core\\pip_update.py --quiet med installerade Python och går sedan till start",
      'core\\pip_update.py" --quiet' in lines[i + 3] and '"%PY%"' in lines[i + 3] and lines[i + 4].strip() == "goto :start_app", lines[i + 3:i + 5])
check("bat: helt flöde går inte in i :snabb_paket (ingen dubbelkörning)", lines[i - 2].strip() == "goto :start_app")
check("bat: ingen venv i batchfilens kommandon", not any("venv" in l.lower() for l in lines if not l.lstrip().upper().startswith("REM")))
labels = {l[1:].strip().lower() for l in lines if l.startswith(":") and not l.startswith("::")}
check("bat: alla goto/call-mål finns", all(j.lower() in labels or j.lower() == "eof" for j in re.findall(r"(?:goto|call)\s+:(\w+)", bat, re.I)))
check("pip_update.py: bara standardbibliotek", not re.search(r"^\s*(?:from|import)\s+(?:core|PySide6|ui|app)\b", (ROOT / "core/pip_update.py").read_text(encoding="utf-8"), re.M))

print(f"\npip_update_test: {ok} lyckades, {fail} misslyckades")
sys.stdout.flush()
os._exit(1 if fail else 0)
