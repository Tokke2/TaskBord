#!/usr/bin/env python3
"""
log_paths_test.py — loggarna ligger i en egen undermapp i appmappen (loggar/) och gamla loggar flyttas dit.

Kör:  python tester/log_paths_test.py     (ingen Qt behövs)
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "core"))

from core import log_paths as LP  # noqa: E402

ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("  ✗", name, extra)


src = lambda p: (ROOT / p).read_text(encoding="utf-8")  # noqa: E731

# ---- migrering -------------------------------------------------------------------------------------------
app = Path(tempfile.mkdtemp(prefix="ledgebord_logs_"))
d = app / "data"
d.mkdir()
for name, txt in {
    "todo_app.log": "gammal logg\n", "todo_app.log.20261101": "igår\n", "fel.log": "fel\n", "fel.log.1": "fel1\n",
    "fel_import.json": "{}", "fel_seen.txt": "123", "update_watchdog.log": "wd\n", "window_failure_report.txt": "rapport",
    "active.json": "UPPGIFTER", "settings.json": "{}", "ledgebord.ico": "x", "update_pending.json": "{}", "audit.log": "audit",
}.items():
    (d / name).write_text(txt, encoding="utf-8")
(d / "backups").mkdir()
(d / "backups" / "x.zip").write_bytes(b"zip")
check("logs_dir = appmappen/loggar", LP.logs_dir(app) == app / "loggar")
moved = LP.migrate_old_logs(app)
check("alla loggfiler flyttades", sorted(moved) == sorted(["todo_app.log", "todo_app.log.20261101", "fel.log", "fel.log.1", "fel_import.json",
                                                             "fel_seen.txt", "update_watchdog.log", "window_failure_report.txt"]), moved)
check("…och finns i loggar/", all((app / "loggar" / n).exists() for n in moved))
check("…och är borta från data/", not any((d / n).exists() for n in moved))
check("uppgifter, inställningar, ikon, backuper och audit rörs inte",
      all((d / n).exists() for n in ("active.json", "settings.json", "ledgebord.ico", "update_pending.json", "audit.log")) and (d / "backups" / "x.zip").exists())
check("innehållet är intakt", (app / "loggar" / "todo_app.log").read_text(encoding="utf-8") == "gammal logg\n")
check("andra körningen flyttar inget", LP.migrate_old_logs(app) == [])

# samma fil finns redan i loggar/: loggtext slås ihop (gammal först), tillståndsfil: den nya gäller
(d / "todo_app.log").write_text("äldre rad\n", encoding="utf-8")
(d / "fel_seen.txt").write_text("999", encoding="utf-8")
LP.migrate_old_logs(app)
check("befintlig loggfil: gammal text först, sedan den nya", (app / "loggar" / "todo_app.log").read_text(encoding="utf-8") == "äldre rad\ngammal logg\n")
check("befintlig tillståndsfil behålls (den nya gäller)", (app / "loggar" / "fel_seen.txt").read_text(encoding="utf-8") == "123" and not (d / "fel_seen.txt").exists())
check("utan data/-mapp: ingen krasch", LP.migrate_old_logs(Path(tempfile.mkdtemp(prefix="ledgebord_nodata_"))) == [])
shutil.rmtree(app, ignore_errors=True)

# ---- koden använder loggar/ ----------------------------------------------------------------------------------
const = src("app/constants.py")
check("LOGS_DIR = appmappen/loggar och LOG_FILE ligger i den", 'LOGS_DIR: Final[Path] = SCRIPT_DIR / "loggar"' in const and "LOG_FILE: Final[Path] = LOGS_DIR /" in const)
boot = src("app/bootstrap.py")
check("start: gamla loggar flyttas före loggningen sätts upp", boot.index("migrate_old_logs(SCRIPT_DIR)") < boot.index("setup_full_logging(\n            data_dir=LOGS_DIR"))
check("start: felloggen installeras i loggar/", "error_log.install(LOGS_DIR)" in boot and "import_in_background(LOGS_DIR" in boot)
check("start: nödrapporten och reservloggen i loggar/", "_rep_dir = LOGS_DIR" in boot and 'log_path = LOGS_DIR / "todo_app.log"' in boot)
for f in ("app/bootstrap.py", "app/mixins/diagnostics.py", "app/mixins/reminders.py", "app/mixins/maintenance.py", "app/controller.py", "app/mixins/tray.py", "app/mixins/updates.py"):
    s = src(f)
    check(f"{f}: ingen logg pekar längre på data/", not re.search(r'data[\\/]+(todo_app|fel\.log|fel_|update_watchdog|window_failure)', s))
check("felloggens 'Öppna' + röda pricken läser loggar/", 'prepare_for_open(SCRIPT_DIR / "loggar")' in src("app/mixins/diagnostics.py")
      and 'mark_seen(SCRIPT_DIR / "loggar")' in src("app/mixins/diagnostics.py") and 'count_unseen(SCRIPT_DIR / "loggar")' in src("app/mixins/reminders.py"))
check("loggarkiveringen (start/var 5:e minut) tittar i loggar/", 'SCRIPT_DIR / "loggar"' in src("app/mixins/maintenance.py") and "archive_in_background(logs)" in src("app/mixins/maintenance.py"))
check("uppdateringsväktaren skriver loggen i loggar/", 'logs_path(app_dir) / LOG_NAME' in src("core/update_watchdog.py"))
check("loggar/ är skyddad mot uppdateringar (updater + väktare)", '"loggar"' in re.search(r"PROTECTED_TOP = frozenset\(\{[^}]*\}\)", src("core/updater.py")).group(0)
      and '"loggar"' in re.search(r"_PROTECTED_TOP = frozenset\(\{[^}]*\}\)", src("core/update_watchdog.py")).group(0))
check("loggar/ är ignorerat av git", "/loggar/" in src(".gitignore").splitlines())
LS = src("core/logger_setup.py")
check("logger_setup: standardmapp loggar/, hittar loggen där först", 'DEFAULT_LOGS_DIR: Path = Path(__file__).resolve().parent.parent / "loggar"' in LS and "data_dir = data_dir or DEFAULT_LOGS_DIR" in LS)

# logger_setup skriver verkligen dit
import importlib  # noqa: E402
import logging  # noqa: E402
tmp = Path(tempfile.mkdtemp(prefix="ledgebord_logsetup_"))
LSm = importlib.import_module("logger_setup")
out = LSm.setup_full_logging(data_dir=tmp / "loggar", capture_stdout=False, capture_exceptions=False, capture_threads=False)
logging.getLogger("x").warning("hej loggar")
for h in logging.getLogger().handlers:
    h.flush()
check("setup_full_logging(loggar) returnerar och skriver dit", Path(out) == tmp / "loggar" and (tmp / "loggar" / "todo_app.log").is_file()
      and "hej loggar" in (tmp / "loggar" / "todo_app.log").read_text(encoding="utf-8"))
for h in logging.getLogger().handlers[:]:
    h.close()
    logging.getLogger().removeHandler(h)
check("…och ingenting skapades i data/", not (tmp / "data").exists())
shutil.rmtree(tmp, ignore_errors=True)

# felrapporten hittar loggarna i loggar/ (och i data/ för äldre installationer)
from core import bugreport as br  # noqa: E402
a = Path(tempfile.mkdtemp(prefix="ledgebord_brnew_"))
(a / "loggar").mkdir()
(a / "loggar" / "todo_app.log").write_text("NY plats\n", encoding="utf-8")
(a / "loggar" / "fel.log").write_text("fel i nya\n", encoding="utf-8")
(a / "data").mkdir()
with zipfile.ZipFile(br.create_report(a)) as z:
    check("felrapport: läser loggar/", b"NY plats" in z.read("todo_app.log") and b"fel i nya" in z.read("fel.log"))
b = Path(tempfile.mkdtemp(prefix="ledgebord_brold_"))
(b / "data").mkdir()
(b / "data" / "todo_app.log").write_text("GAMMAL plats\n", encoding="utf-8")
with zipfile.ZipFile(br.create_report(b)) as z:
    check("felrapport: äldre installation (loggen i data/) fungerar fortfarande", b"GAMMAL plats" in z.read("todo_app.log"))
shutil.rmtree(a, ignore_errors=True)
shutil.rmtree(b, ignore_errors=True)

print(f"\nlog_paths_test: {ok} lyckades, {fail} misslyckades")
sys.stdout.flush()
os._exit(1 if fail else 0)
