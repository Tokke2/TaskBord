"""
update_watchdog_test.py — självläkande uppdatering (core/update_watchdog.py + apply_update/schedule_restart).

Kör RIKTIGA processer: en låtsas-appmapp uppdateras med ``updater.apply_update``, väktaren (kopian i
backupmappen) startas som egen process med korta tider och startar en låtsas-``main.pyw``:

  * frisk (bekräftar)            → inget återställs
  * kraschar direkt / syntaxfel  → filerna återställs, nya tas bort, gamla appen startas
  * hänger sig (bekräftar aldrig)→ processen stoppas, återställs
  * bekräftar inte men svarar på /health → behålls (appen kom igång)
  * avslutas rent efter bekräftelse (användaren stängde) → behålls
  * en annan TaskBord kör redan (avslutar med 0, /health svarar) → ingen återställning
  * js/ och data/ rörs aldrig; osäkra sökvägar i manifestet ignoreras
Dessutom: apply_update lägger väktare + manifest, schedule_restart bygger rätt kommando och faller
tillbaka på den enkla omstartaren när väktaren saknas, app-sidans bekräftelse/underrättelse.
"""
from __future__ import annotations

import http.server
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for sub in ("", "core"):
    sys.path.insert(0, str(ROOT / sub))

from core import update_watchdog as wd  # noqa: E402
from core import updater  # noqa: E402

ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("  ✗", name, extra)


tmp = Path(tempfile.mkdtemp(prefix="taskbord_wd_"))
PIDS: list = []


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


# --- låtsas-appar ---------------------------------------------------------------------------------
COMMON = '''
import os, sys, time
from pathlib import Path
HERE = Path(__file__).resolve().parent
DATA = HERE / "data"; DATA.mkdir(exist_ok=True)
with open(DATA / "pids.txt", "a") as f: f.write(str(os.getpid()) + "\\n")
def log(t):
    with open(DATA / "run.log", "a") as f: f.write(t + "\\n")
def confirm():
    try: (DATA / "update_pending.json").unlink()
    except FileNotFoundError: pass
'''
OLD_APP = COMMON + 'log("old started")\ntime.sleep(60)\n'
NEW_VARIANTS = {
    "healthy":  COMMON + 'log("new started")\ntime.sleep(0.4)\nconfirm()\nlog("new confirmed")\ntime.sleep(60)\n',
    "crash":    COMMON + 'log("new started")\nsys.exit(3)\n',
    "syntax":   'def broken(:\n',
    "hang":     COMMON + 'log("new started")\ntime.sleep(60)\n',
    "quit_ok":  COMMON + 'log("new started")\ntime.sleep(0.4)\nconfirm()\nsys.exit(0)\n',
    "single":   COMMON + 'log("new started")\nsys.exit(0)\n',
    "health":   COMMON + '''log("new started")
import http.server, json, threading
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        b = json.dumps({"app": "TaskBord"}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def log_message(self, *a): pass
srv = http.server.HTTPServer(("127.0.0.1", int(os.environ["WD_TEST_PORT"])), H)
srv.serve_forever()
''',
}


def make_app(name: str, variant: str):
    """Låtsas-appmapp (gammal version) + UpdateInfo som byter main.pyw, ersätter app/mod.py och lägger till filer."""
    app = tmp / name
    (app / "app").mkdir(parents=True)
    (app / "js").mkdir()
    (app / "js" / "active.json").write_text('{"tasks": []}', encoding="utf-8")
    (app / "main.pyw").write_text(OLD_APP, encoding="utf-8")
    (app / "app" / "mod.py").write_text("VERSION = 'old'\n", encoding="utf-8")
    (app / "keep.txt").write_text("lokal fil som inte ingår i releasen", encoding="utf-8")
    info = updater.UpdateInfo(
        tag="v1.0.0", commit="abc1234" + "0" * 33,
        files={"main.pyw": NEW_VARIANTS[variant].encode("utf-8"),
               "app/mod.py": b"VERSION = 'new'\n",
               "newpkg/added.py": b"X = 1\n",
               "newpkg/sub/deep.py": b"Y = 2\n",
               "new_root.txt": b"ny"},
        changed=["main.pyw", "app/mod.py", "newpkg/added.py", "newpkg/sub/deep.py", "new_root.txt"],
        new_files=["newpkg/added.py", "newpkg/sub/deep.py", "new_root.txt"],
    )
    return app, info


def run_guard(app: Path, bk: Path, port=None, timeout=4.0, grace=1.0, ports="1"):
    env = dict(os.environ)
    if port:
        env["WD_TEST_PORT"] = str(port)
        ports = str(port)
    cmd = wd.guard_command(app, bk, sys.executable, app / "main.pyw", 0, int(timeout))
    # testtider: kortare än heltal-sekunder i guard_command
    cmd[cmd.index("--timeout") + 1] = str(timeout)
    cmd += ["--grace", str(grace), "--poll", "0.1", "--ports", ports]
    r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=60)
    return r


def run_log(app: Path) -> list:
    p = app / "data" / "run.log"
    return p.read_text(encoding="utf-8").splitlines() if p.exists() else []


def collect_pids(app: Path) -> None:
    p = app / "data" / "pids.txt"
    if p.exists():
        PIDS.extend(int(x) for x in p.read_text().split())


def wait_for(cond, secs=5.0):
    t0 = time.time()
    while time.time() - t0 < secs:
        if cond():
            return True
        time.sleep(0.1)
    return False


def prepare(name, variant):
    app, info = make_app(name, variant)
    bk = updater.apply_update(app, info)
    return app, info, bk


try:
    # =========================================================================================
    # 1. apply_update: väktare + manifest i backupen
    # =========================================================================================
    app, info, bk = prepare("t_apply", "healthy")
    check("backup: watchdog.py finns", (bk / "watchdog.py").is_file())
    check("backup: watchdog.py = nuvarande kod", (bk / "watchdog.py").read_bytes() == (ROOT / "core" / "update_watchdog.py").read_bytes())
    man = json.loads((bk / "manifest.json").read_text(encoding="utf-8"))
    check("manifest: ersatta filer", sorted(man["replaced"]) == ["app/mod.py", "main.pyw"], str(man))
    check("manifest: nya filer", sorted(man["new"]) == ["new_root.txt", "newpkg/added.py", "newpkg/sub/deep.py"], str(man))
    check("manifest: tag/commit/fingerprint", man["tag"] == "v1.0.0" and man["commit"].startswith("abc1234") and len(man["fingerprint"]) == 16)
    check("backup: gamla filen finns", (bk / "app" / "mod.py").read_text() == "VERSION = 'old'\n")
    check("filerna är bytta", (app / "app" / "mod.py").read_text() == "VERSION = 'new'\n")

    # =========================================================================================
    # 2. schedule_restart: kommando + pending, och reservvägen
    # =========================================================================================
    popen_calls = []
    real_popen = subprocess.Popen
    subprocess.Popen = lambda cmd, **kw: popen_calls.append((cmd, kw)) or types_dummy
    try:
        types_dummy = object()
        check("schedule_restart med backup → True", updater.schedule_restart(app, 6, backup_root=bk))
        cmd = popen_calls[-1][0]
        check("väktaren startas från backupen", cmd[1] == str(bk / "watchdog.py"), str(cmd))
        check("kommandot har app-dir, backup, delay 6 och timeout 60",
              cmd[cmd.index("--app-dir") + 1] == str(app) and cmd[cmd.index("--delay") + 1] == "6"
              and cmd[cmd.index("--timeout") + 1] == "60" and cmd[cmd.index("--backup") + 1] == str(bk), str(cmd))
        check("startas frikopplad", popen_calls[-1][1].get("start_new_session") is True or sys.platform == "win32")
        pend = wd.read_pending(app)
        check("update_pending.json skrevs", pend is not None and pend.get("tag") == "v1.0.0" and pend.get("backup") == str(bk), str(pend))
        wd.confirm_healthy(app)
        # utan watchdog.py → enkla omstartaren
        (bk / "watchdog.py").unlink()
        updater.schedule_restart(app, 6, backup_root=bk)
        check("utan väktare → vanlig omstart (ping/sleep)", "watchdog" not in " ".join(popen_calls[-1][0]) and wd.read_pending(app) is None, str(popen_calls[-1][0]))
        updater.schedule_restart(app, 6)
        check("utan backup → vanlig omstart", "watchdog" not in " ".join(popen_calls[-1][0]))
    finally:
        subprocess.Popen = real_popen

    # =========================================================================================
    # 3. riktiga väktar-körningar
    # =========================================================================================
    # 3a. frisk
    app, info, bk = prepare("t_healthy", "healthy")
    wd.write_pending(app, {"backup": str(bk)})
    r = run_guard(app, bk)
    collect_pids(app)
    check("frisk: väktaren avslutas utan fel", r.returncode == 0, r.stderr[-300:])
    check("frisk: nya koden körs, ingen återställning",
          (app / "app" / "mod.py").read_text() == "VERSION = 'new'\n" and "old started" not in run_log(app), str(run_log(app)))
    check("frisk: pending borta, ingen rollback-fil", wd.read_pending(app) is None and wd.read_rollback(app) is None)

    # 3b. kraschar direkt
    app, info, bk = prepare("t_crash", "crash")
    wd.write_pending(app, {"backup": str(bk)})
    t0 = time.time()
    r = run_guard(app, bk, timeout=30, grace=1.0)
    el = time.time() - t0
    check("krasch: återställs snabbt (inte efter hela 30 s)", el < 15, f"{el:.1f}s")
    check("krasch: gamla filer tillbaka", (app / "app" / "mod.py").read_text() == "VERSION = 'old'\n" and (app / "main.pyw").read_text() == OLD_APP)
    check("krasch: nya filer + katalog borta",
          not (app / "new_root.txt").exists() and not (app / "newpkg").exists(), str(list(app.iterdir())))
    check("krasch: lokal fil + js orörda", (app / "keep.txt").exists() and (app / "js" / "active.json").read_text() == '{"tasks": []}')
    check("krasch: gamla appen startades igen", wait_for(lambda: "old started" in run_log(app)), str(run_log(app)))
    collect_pids(app)
    rb = wd.read_rollback(app)
    check("krasch: update_rollback.json med orsak, tag och fingeravtryck",
          rb is not None and "kod 3" in str(rb.get("reason")) and rb.get("tag") == "v1.0.0" and len(str(rb.get("fingerprint"))) == 16
          and rb.get("restored") == 2 and rb.get("removed") == 3, str(rb))
    check("krasch: pending borta", wd.read_pending(app) is None)
    check("krasch: väktarloggen finns", "ÅTERSTÄLLER" in (app / "data" / "update_watchdog.log").read_text(encoding="utf-8"))

    # 3c. syntaxfel i nya main.pyw
    app, info, bk = prepare("t_syntax", "syntax")
    wd.write_pending(app, {"backup": str(bk)})
    r = run_guard(app, bk, timeout=30)
    check("syntaxfel: återställs", (app / "main.pyw").read_text() == OLD_APP and wd.read_rollback(app) is not None)
    check("syntaxfel: gamla appen startad", wait_for(lambda: "old started" in run_log(app)))
    collect_pids(app)

    # 3d. hänger sig utan att bekräfta → stoppas efter timeout
    app, info, bk = prepare("t_hang", "hang")
    wd.write_pending(app, {"backup": str(bk)})
    t0 = time.time()
    r = run_guard(app, bk, timeout=3.0)
    el = time.time() - t0
    check("hängning: väntar ut tiden (≥3 s) men inte mycket längre", 3.0 <= el < 20, f"{el:.1f}s")
    check("hängning: återställd", (app / "app" / "mod.py").read_text() == "VERSION = 'old'\n")
    rb = wd.read_rollback(app)
    check("hängning: orsaken nämner tiden", rb is not None and "inom 3 s" in str(rb.get("reason")), str(rb))
    pids = [int(x) for x in (app / "data" / "pids.txt").read_text().split()]
    hung_pid = pids[0]
    def dead(pid):
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        try:
            return os.waitpid(pid, os.WNOHANG)[0] != 0
        except ChildProcessError:
            # inte vårt barn (väktaren är en egen process) — zombie räknas via /proc
            try:
                return "Z" in Path(f"/proc/{pid}/stat").read_text().split(")")[-1].split()[0]
            except OSError:
                return True
    check("hängning: den hängda processen är stoppad", wait_for(lambda: dead(hung_pid), 5), f"pid {hung_pid}")
    check("hängning: gamla appen startad", wait_for(lambda: "old started" in run_log(app)))
    collect_pids(app)

    # 3e. bekräftar inte men svarar på /health → behålls
    port = free_port()
    app, info, bk = prepare("t_health", "health")
    wd.write_pending(app, {"backup": str(bk)})
    r = run_guard(app, bk, port=port, timeout=3.0)
    collect_pids(app)
    check("svarar på /health: ingen återställning",
          (app / "app" / "mod.py").read_text() == "VERSION = 'new'\n" and wd.read_rollback(app) is None and wd.read_pending(app) is None,
          str(run_log(app)))

    # 3f. ren avslutning efter bekräftelse
    app, info, bk = prepare("t_quit", "quit_ok")
    wd.write_pending(app, {"backup": str(bk)})
    r = run_guard(app, bk, timeout=4.0)
    check("avslutad efter bekräftelse: ingen återställning",
          (app / "app" / "mod.py").read_text() == "VERSION = 'new'\n" and wd.read_rollback(app) is None)

    # 3g. annan TaskBord kör redan (nya avslutar med 0, /health svarar)
    port = free_port()

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            b = json.dumps({"app": "TaskBord"}).encode()
            self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
        def log_message(self, *a): pass
    srv = http.server.HTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    app, info, bk = prepare("t_single", "single")
    wd.write_pending(app, {"backup": str(bk)})
    r = run_guard(app, bk, ports=str(port), timeout=6.0, grace=1.0)
    check("annan instans svarar: ingen återställning",
          (app / "app" / "mod.py").read_text() == "VERSION = 'new'\n" and wd.read_rollback(app) is None and wd.read_pending(app) is None)
    srv.shutdown()

    # 3h. samma sak men NY app avslutar med 0 och ingen annan svarar → återställs
    app, info, bk = prepare("t_exit0", "single")
    wd.write_pending(app, {"backup": str(bk)})
    r = run_guard(app, bk, ports="1", timeout=6.0, grace=1.0)
    check("avslut 0 utan bekräftelse och ingen annan instans: återställs", wd.read_rollback(app) is not None)
    check("…gamla appen startad", wait_for(lambda: "old started" in run_log(app)))
    collect_pids(app)

    # =========================================================================================
    # 4. restore_files: säkerhet och robusthet
    # =========================================================================================
    app = tmp / "t_safe"
    (app / "js").mkdir(parents=True)
    (app / "data").mkdir()
    (app / "js" / "active.json").write_text("viktigt")
    (app / "data" / "x.log").write_text("logg")
    outside = tmp / "utanför.txt"
    outside.write_text("rör ej")
    b = tmp / "t_safe_bk"
    (b / "js").mkdir(parents=True)
    (b / "js" / "active.json").write_text("FEL — får inte skrivas över")
    (b / "ok.txt").write_text("återställd")
    wd.write_manifest(b, {"replaced": ["../utanför.txt", "js/active.json", "/etc/passwd", "ok.txt", "saknas.txt"],
                          "new": ["../utanför.txt", "data/x.log", "js/active.json"]})
    res = wd.restore_files(app, b)
    check("osäkra/skyddade sökvägar ignoreras",
          outside.read_text() == "rör ej" and (app / "js" / "active.json").read_text() == "viktigt" and (app / "data" / "x.log").exists(), str(res))
    check("giltig fil återställs", (app / "ok.txt").read_text() == "återställd" and res["restored"] == 1, str(res))
    check("saknad backupfil + osäkra räknas som failed", res["failed"] >= 4, str(res))
    # utan manifest: återställ allt i backupen utom metafiler
    b2 = tmp / "t_safe_bk2"
    (b2 / "sub").mkdir(parents=True)
    (b2 / "sub" / "a.py").write_text("A")
    (b2 / "UPPDATERING.txt").write_text("x")
    (b2 / "watchdog.py").write_text("x")
    res = wd.restore_files(app, b2)
    check("utan manifest: filer återställs, metafiler inte",
          (app / "sub" / "a.py").read_text() == "A" and not (app / "UPPDATERING.txt").exists() and not (app / "watchdog.py").exists())

    # =========================================================================================
    # 5. app-sidan: bekräfta, underrätta
    # =========================================================================================
    from app.mixins import updates as um  # noqa: E402
    um.SCRIPT_DIR = tmp / "t_appside"
    (um.SCRIPT_DIR / "data").mkdir(parents=True)

    class S:
        def __init__(self): self.failed = ""
        def update_failed(self): return self.failed
        def set_update_failed(self, v): self.failed = v

    class L:
        def __getattr__(self, n): return lambda *a, **k: None

    class Tray:
        def __init__(self): self.msgs = []
        def showMessage(self, *a): self.msgs.append(a)

    class Ctl(um.UpdateMixin):
        def __init__(self):
            self.settings = S(); self._log = L(); self._tray = Tray(); self.timers = []; self.dialogs = []
            self._QTimer = type("T", (), {"singleShot": staticmethod(lambda ms, fn: self.timers.append((ms, fn)))})
            self._QSystemTrayIcon = type("I", (), {"MessageIcon": type("M", (), {"Warning": 2})})
        def _update_dialog(self, kind, title, text): self.dialogs.append((kind, title, text)); return True

    c = Ctl()
    c._init_update_guard()
    check("vanlig start: ingen bekräftelse schemalagd, notis-koll finns",
          c._update_guard_pending is False and [ms for ms, _ in c.timers] == [8_000])
    wd.write_pending(um.SCRIPT_DIR, {"tag": "v1.0.0"})
    c = Ctl(); c.settings.failed = "gammal"
    c._init_update_guard()
    check("start efter uppdatering: bekräftelse om 10 s", c._update_guard_pending is True and 10_000 in [ms for ms, _ in c.timers])
    c._confirm_update_health(on_exit=True)       # nystartad (<3 s) → väktaren avgör
    check("avslut direkt efter start bekräftar inte", wd.read_pending(um.SCRIPT_DIR) is not None)
    c._confirm_update_health()
    check("bekräftelse tar bort pending och nollar update_failed", wd.read_pending(um.SCRIPT_DIR) is None and c.settings.failed == "")
    wd.write_pending(um.SCRIPT_DIR, {})
    c = Ctl(); c._init_update_guard(); c._start_time = time.time() - 20
    c._confirm_update_health(on_exit=True)
    check("ren avslutning efter uppstart bekräftar", wd.read_pending(um.SCRIPT_DIR) is None)
    # gammal app som själv startar uppdatering: pending skrivs EFTER dess start → dess avslut får inte bekräfta
    c = Ctl(); c._init_update_guard(); c._start_time = time.time() - 600
    wd.write_pending(um.SCRIPT_DIR, {"tag": "v1.0.0"})   # som schedule_restart gör
    c._confirm_update_health(on_exit=True)
    check("uppdaterande appens egen nedstängning raderar INTE väktarens pending", wd.read_pending(um.SCRIPT_DIR) is not None)
    wd.confirm_healthy(um.SCRIPT_DIR)

    (um.SCRIPT_DIR / "data" / "update_rollback.json").write_text(json.dumps(
        {"reason": "appen avslutades med kod 1", "tag": "v1.0.0", "commit": "abcdef0123", "fingerprint": "f" * 16,
         "restored": 4, "removed": 2, "backup": "data/backups/app-update/X"}), encoding="utf-8")
    c = Ctl()
    c._show_update_rollback_notice()
    check("återställningsmeddelande visas", len(c.dialogs) == 1 and c.dialogs[0][0] == "warn" and "abcdef0" in c.dialogs[0][2]
          and "kod 1" in c.dialogs[0][2], str(c.dialogs))
    check("…tray-notis också", len(c._tray.msgs) == 1)
    check("…uppdateringen märks som misslyckad", c.settings.failed == "f" * 16)
    check("…och visas bara en gång", wd.read_rollback(um.SCRIPT_DIR) is None)
    c._show_update_rollback_notice()
    check("…andra anropet gör inget", len(c.dialogs) == 1)

    # tyst notis tystas för misslyckad uppdatering
    class Info:
        up_to_date = False; tag = "v1.0.0"; changed = ["a"]; files = {"a": b"x"}
    fp = updater.fingerprint(Info())
    c = Ctl(); c.settings.failed = fp
    c.settings.update_notified = lambda: ""
    c.settings.set_update_notified = lambda v: c.dialogs.append(("notified", v, ""))
    c._notify_update_available(Info())
    check("misslyckad uppdatering → ingen ny notis", c.dialogs == [] and c._tray.msgs == [])
finally:
    for pid in PIDS:
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception:
            pass
    time.sleep(0.3)
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\nupdate_watchdog_test: {ok} lyckades, {fail} misslyckades")
sys.exit(1 if fail else 0)
