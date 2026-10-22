"""
app_boot_test.py — startar HELA appen på riktigt (Qt "offscreen") och kontrollerar loggen.

Fångar fel som bara syns när koden körs: saknade importer/namn efter omstrukturering, trasig
uppstart, undantag i AppController.__init__ osv. Körs i en kopia av projektet så ingenting
skrivs i din riktiga js\\ eller data\\.

* Kräver PySide6. På Linux utan GL-bibliotek (t.ex. en server) skapas tomma stubbar med gcc/nm.
* Hoppas över (exit 0) om något saknas, eller om en annan Ledgebord redan kör (port 8765).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def skip(msg: str):
    print(f"  (hoppar över app_boot_test: {msg})")
    print("\napp_boot_test: 0 lyckades, 0 misslyckades (överhoppad)")
    sys.exit(0)


try:
    import PySide6  # noqa: F401
except ImportError:
    skip("PySide6 saknas")

work = Path(tempfile.mkdtemp(prefix="taskbord_boot_"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _qtenv import qt_env  # noqa: E402

env, why = qt_env(work)
if env is None:
    shutil.rmtree(work, ignore_errors=True)
    skip(why)
env.pop("TASKBORD_BACKUP_DIR", None)

# --- kopia av projektet (utan .git, js, data) ------------------------------------
app_copy = work / "Ledgebord"
shutil.copytree(ROOT, app_copy, ignore=shutil.ignore_patterns(".git", "js", "data", "__pycache__", "*.pyc", "node_modules"))

ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("  ✗", name, extra)


# tre uppgifter: vanlig, mail med flyttad (död) filsökväg och mail med bara sparad text — korten
# (inkl. 📧-knappen) byggs på riktigt vid start
import json  # noqa: E402
(app_copy / "js" / "emails").mkdir(parents=True, exist_ok=True)
(app_copy / "js" / "emails" / "mail00001.eml").write_text("From: a@b\nSubject: x\n\nhej\n", encoding="utf-8")
seed = [{"id": "plain001", "title": "Vanlig uppgift"},
        {"id": "mail00001", "title": "Mail med flyttad fil", "email_from": "Anna <a@x>", "email_subject": "Rapport",
         "email_path": "D:\\Program\\todo\\js\\emails\\mail00001.eml"},
        {"id": "mail00002", "title": "Mail utan fil", "email_from": "Bo <b@x>", "email_body": "text",
         "email_message_id": "<m2@x>"}]
(app_copy / "js" / "active.json").write_text(json.dumps({"version": 5, "tasks": seed}), encoding="utf-8")

# som efter en uppdatering: väktaren har lagt update_pending.json (appen ska bekräfta den) och en
# tidigare återställning har lämnat update_rollback.json (appen ska berätta om den)
(app_copy / "data").mkdir(exist_ok=True)
(app_copy / "data" / "update_pending.json").write_text(json.dumps({"tag": "v1.0.0", "started": time.time()}), encoding="utf-8")
(app_copy / "data" / "update_rollback.json").write_text(json.dumps(
    {"reason": "test", "tag": "v1.0.0", "commit": "abcdef0", "fingerprint": "f" * 16, "restored": 1, "removed": 0}), encoding="utf-8")

proc = subprocess.Popen([sys.executable, "main.pyw"], cwd=app_copy, env=env,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
log = app_copy / "data" / "todo_app.log"
text = ""
t0 = time.time()
while time.time() - t0 < 60:
    if log.exists():
        text = log.read_text(encoding="utf-8", errors="replace")
        if "AppController klar" in text or "startar ingen ny instans" in text or proc.poll() is not None:
            break
    time.sleep(0.5)
time.sleep(1.5)   # låt de första timrarna hinna gå
# uppdateringsväktaren: appen ska ta bort update_pending.json ~10 s efter uppstart och ha tagit
# hand om återställningsmeddelandet (~8 s)
t1 = time.time()
while time.time() - t1 < 30 and ((app_copy / "data" / "update_pending.json").exists()
                                 or (app_copy / "data" / "update_rollback.json").exists()):
    time.sleep(0.5)
guard_cleared = not (app_copy / "data" / "update_pending.json").exists()
rollback_taken = not (app_copy / "data" / "update_rollback.json").exists()
alive = proc.poll() is None
proc.kill()
out = proc.communicate()[0] or ""
if log.exists():
    text = log.read_text(encoding="utf-8", errors="replace")

if "startar ingen ny instans" in text:
    shutil.rmtree(work, ignore_errors=True)
    skip("en annan Ledgebord kör redan (port 8765)")

check("appen startade klart (AppController klar)", "AppController klar" in text, out[-400:])
check("release loggades", "Release: v" in text)
check("e-postbryggan startade", "E-postbrygga: http=PÅ" in text)
check("fönstret ritades (start: N aktiva)", "start: " in text and "aktiva" in text)
check("de 3 seedade uppgifterna ritades (inkl. mailkorten)", "start: 3 aktiva" in text, text[-300:])
check("inget kort misslyckades att byggas", "_build_task_widget" not in text and "_rebuild_task_list misslyckades" not in text)
check("inga ERROR/CRITICAL i loggen", not any(("| ERROR" in l or "| CRITICAL" in l) for l in text.splitlines()),
      "\n".join(l[:200] for l in text.splitlines() if "| ERROR" in l or "| CRITICAL" in l)[:600])
check("inga ohanterade undantag", "OHANTERAT" not in text)
check("appen levde när testet avslutade den", alive)
check("uppdateringen bekräftades (update_pending.json borta)", guard_cleared)
check("återställningsmeddelandet hanterades", rollback_taken and "återställdes automatiskt" in text)

shutil.rmtree(work, ignore_errors=True)
print(f"\napp_boot_test: {ok} lyckades, {fail} misslyckades")
sys.exit(1 if fail else 0)
