#!/usr/bin/env python3
"""
error_log_test.py — data/fel.log: alla fel samlade (live-handler + import ur de andra loggarna).

Kör:  python tester/error_log_test.py      (ingen Qt behövs)
"""
from __future__ import annotations

import logging
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "core"))

from core import error_log as EL  # noqa: E402

ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("  ✗", name, extra)


def fresh(tag):
    d = Path(tempfile.mkdtemp(prefix="ledgebord_errlog_"))
    EL._writer = EL._handler = None
    lg = logging.getLogger(f"elt.{tag}")
    lg.setLevel(logging.DEBUG)
    lg.propagate = False
    for h in lg.handlers[:]:
        lg.removeHandler(h)
    w = EL.install(d, root=lg)
    return d, lg, w


def read(d):
    p = d / "fel.log"
    return p.read_text(encoding="utf-8") if p.exists() else ""


# 1. live: nivåer, format, stacktrace, sessionshuvud
d, lg, w = fresh("a")
lg.info("bara info")
lg.debug("debug")
check("INFO/DEBUG skapar ingen fil", not (d / "fel.log").exists())
lg.warning("[GCAL] token gick ut")
try:
    1 / 0
except ZeroDivisionError:
    lg.error("[UPDATE] installation misslyckades: disk full", exc_info=True)
lg.critical("kraschade totalt")
t = read(d)
check("sessionshuvud skrivs", "═══ Ledgebord startad" in t and f"pid {os.getpid()}" in t)
check("VARNING-post med tid, logger och källa", "| VARNING  | elt.a.__root__" in t or "| VARNING  | elt.a (error_log_test.py:" in t, t)
check("FEL-post med meddelandet", "| FEL      | elt.a (error_log_test.py:" in t and "[UPDATE] installation misslyckades: disk full" in t)
check("stacktrace med indrag", "    Traceback (most recent call last):" in t and "    ZeroDivisionError: division by zero" in t)
check("KRASCH-post", "| KRASCH   |" in t and "kraschade totalt" in t)
check("bara en sessionshuvud", t.count("═══ Ledgebord startad") == 1)
check("INFO syns inte", "bara info" not in t)

# 2. dubbletter samlas
d, lg, w = fresh("b")
for i in range(6):
    lg.error(f"[MAIL] nekad förfrågan från 10.0.0.{i}")
lg.error("något annat")
t = read(d)
check("likadana fel skrivs en gång", t.count("nekad förfrågan") == 1, t)
w.flush_summaries()
t = read(d)
check("…med 'upprepades 5 gång(er)'", "upprepades 5 gång(er) till" in t, t)
check("annat fel skrivs separat", "något annat" in t)

# 3. maskning
d, lg, w = fresh("c")
lg.error("kunde inte skicka till kund@exempel.se")
t = read(d)
check("mailadress maskad", "kund@exempel.se" not in t and "exempel.se" in t, t)

# 4. rotation
d, lg, w = fresh("d")
old = EL.MAX_BYTES
EL.MAX_BYTES = 2000
for i in range(80):
    lg.error("x" * 100 + chr(97 + i % 26) * 5 + str(i) + chr(65 + i % 26) * i)   # olika nycklar
EL.MAX_BYTES = old
check("rotation: fel.log.1 finns, fel.log finns", (d / "fel.log.1").exists() and (d / "fel.log").exists())
check("rotation: nya filen har nytt sessionshuvud", "═══ Ledgebord startad" in read(d))

# 5. import ur andra loggar
d, lg, w = fresh("e")
(d / "update_watchdog.log").write_text(
    "2026-10-29 08:00:00 | start: väntar 5s, vaktar 60s (main.pyw)\n"
    "2026-10-29 08:01:05 | appen avslutades (kod 1) innan den bekräftat\n"
    "2026-10-29 08:01:06 | ÅTERSTÄLLER från D:/x: appen startade inte\n"
    "2026-10-29 08:01:07 | klart: {'kopierade': 3}\n", encoding="utf-8")
(d / "window_failure_report.txt").write_text("Ledgebord — NÖDRAPPORT\n" + "=" * 20 + "\nTid: 2026-10-28 10:00:00\nPySide6: 6.11\n", encoding="utf-8")
(d / "todo_app.log").write_text(
    "2026-10-28 09:00:00,100 | INFO     | Main | [MainThread#1] | f:1 | start\n"
    "2026-10-28 09:00:01,200 | ERROR    | Store | [MainThread#1] | save:10 | [STORE] kunde inte spara\n"
    "Traceback (most recent call last):\n"
    "  File \"x.py\", line 1, in save\n"
    "OSError: disk full\n"
    "2026-10-28 09:00:02,300 | WARNING  | Gcal | [MainThread#1] | f:2 | [GCAL] token\n"
    "2026-10-28 09:00:03,400 | INFO     | Main | [MainThread#1] | f:3 | klar\n"
    "2026-10-28 09:00:04,500 | CRITICAL | Main | [MainThread#1] | f:4 | allt gick fel\n", encoding="utf-8")
(d / "todo_app.log.20261027").write_text(
    "2026-10-27 12:00:00,000 | ERROR    | Mail | [Thread#2] | g:5 | [MAIL] gammalt fel\n", encoding="utf-8")
n = EL.import_other_logs(d, w)
t = read(d)
check("import: antal poster = 2 watchdog + 1 nödrapport + 3 ur huvudloggen", n == 6, (n, t))
check("watchdog: fel/återställning med, rutinrader ute", "appen avslutades (kod 1)" in t and "ÅTERSTÄLLER" in t and "start: väntar" not in t and "klart:" not in t)
check("nödrapport med", "window_failure_report.txt" in t and "PySide6: 6.11" in t)
check("huvudlogg: ERROR med stacktrace", "kunde inte spara" in t and "    OSError: disk full" in t and "    Traceback (most recent call last):" in t)
check("huvudlogg: CRITICAL med", "allt gick fel" in t)
check("huvudlogg: roterad dagsfil med", "gammalt fel" in t and "todo_app.log.20261027" in t)
check("huvudlogg: WARNING backfylls inte", "[GCAL] token" not in t)
check("huvudlogg: INFO inte med", "klar\n" not in t.replace("klart", ""))
check("tidsordning (äldsta importen först)", t.index("gammalt fel") < t.index("kunde inte spara") < t.index("allt gick fel"))
n2 = EL.import_other_logs(d, w)
check("import igen: inga dubbletter", n2 == 0 and read(d) == t, n2)
with open(d / "update_watchdog.log", "a", encoding="utf-8") as f:
    f.write("2026-10-30 09:00:00 | kunde inte starta den förra versionen: nej\n")
    f.write("2026-10-30 09:00:01 | start: väntar 5s\n")
n3 = EL.import_other_logs(d, w)
check("import: bara nya watchdog-rader tas", n3 == 1 and read(d).count("kunde inte starta den förra versionen") == 1, n3)
(d / "update_watchdog.log").write_text("2026-10-31 01:00:00 | appen avslutades (kod 2) innan den bekräftat\n", encoding="utf-8")
check("import: trunkerad/ersatt watchdog-logg läses om", EL.import_other_logs(d, w) == 1)
with open(d / "todo_app.log", "a", encoding="utf-8") as f:
    f.write("2026-10-30 09:30:00,000 | ERROR    | X | [T#1] | h:1 | live-fel som redan fångats live\n")
check("huvudloggen backfylls bara en gång", EL.import_other_logs(d, w) == 0)

# 6. öppna: tom fil → platshållare som försvinner vid första felet
d, lg, w = fresh("f")
p = EL.prepare_for_open(d)
check("prepare_for_open skapar fil med 'Inga fel loggade'", p.exists() and "Inga fel loggade" in p.read_text(encoding="utf-8"))
lg.error("första riktiga felet")
t = read(d)
check("platshållaren tas bort när fel kommer", "Inga fel loggade" not in t and "första riktiga felet" in t, t)
check("prepare_for_open på fil med fel behåller dem", "första riktiga felet" in EL.prepare_for_open(d).read_text(encoding="utf-8"))

# 7. skriver aldrig undantag utåt (skrivskyddad katalog / konstig post)
d, lg, w = fresh("g")
w.path = Path("/proc/nonexistent/fel.log")
lg.error("det här får inte krascha")
check("fel vid skrivning kraschar inte appen", True)

# 8. riktig root-logger: install är idempotent och fångar underloggare
EL._writer = EL._handler = None
d = Path(tempfile.mkdtemp(prefix="ledgebord_errlog_"))
root = logging.getLogger()
before = len(root.handlers)
EL.install(d)
EL.install(d)
check("install är idempotent (en handler)", len(root.handlers) == before + 1)
logging.getLogger("Widget").error("[WIDGET] något gick snett")
check("root-handlern fångar fel från alla moduler", "[WIDGET] något gick snett" in read(d))
root.removeHandler(EL._handler)

# 9. felrapporten tar med fel.log
from core import bugreport  # noqa: E402
import zipfile  # noqa: E402
app = Path(tempfile.mkdtemp(prefix="ledgebord_app_"))
(app / "data").mkdir()
(app / "data" / "fel.log").write_text("2026-10-30 | FEL | x | boom kund@x.se\n", encoding="utf-8")
(app / "main.pyw").write_text("x=1\n", encoding="utf-8")
try:
    out = bugreport.create_report(app)
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        check("felrapporten innehåller fel.log (maskad)", "fel.log" in names and b"kund@x.se" not in z.read("fel.log"))
        check("LÄS_MIG nämner fel.log", b"fel.log" in z.read("L\u00c4S_MIG.txt"))
except Exception as e:  # pragma: no cover
    check("felrapport skapas", False, e)

print(f"\nerror_log_test: {ok} lyckades, {fail} misslyckades")
sys.stdout.flush()
os._exit(1 if fail else 0)
