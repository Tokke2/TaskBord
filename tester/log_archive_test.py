#!/usr/bin/env python3
"""
log_archive_test.py — loggar från dagar före idag arkiveras (zip), felposter ligger kvar i fel.log tills de är åtgärdade.

Kör:  python tester/log_archive_test.py     (ingen Qt behövs)
"""
from __future__ import annotations

import logging
import os
import shutil
import sys
import tempfile
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "core"))

from core import error_log as EL  # noqa: E402
from core import log_archive as LA  # noqa: E402

ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("  ✗", name, extra)


def tmpdir():
    return Path(tempfile.mkdtemp(prefix="ledgebord_arch_"))


TODAY = date(2026, 11, 4)
Y = TODAY - timedelta(days=1)
Y2 = TODAY - timedelta(days=2)
iso = lambda d: d.isoformat()  # noqa: E731


def zread(p, name):
    with zipfile.ZipFile(p) as z:
        return z.read(name).decode("utf-8")


# ============ huvudloggen ==============================================================================
d = tmpdir()
(d / "todo_app.log.20261103").write_text("igår rad 1\nigår rad 2\n", encoding="utf-8")
(d / "todo_app.log.20261102").write_text("förrgår\n", encoding="utf-8")
(d / "todo_app.log.20261104").write_text("idag (roterad)\n", encoding="utf-8")
(d / "todo_app.log").write_text("pågående\n", encoding="utf-8")
(d / "todo_app.log.skräp").write_text("x", encoding="utf-8")
r = LA.archive_day_logs(d, TODAY)
check("två dagar arkiverades", r["files"] == 2, r)
check("igår → arkiv/2026-11-03.zip", zread(LA.day_zip(d, "2026-11-03"), "todo_app.log") == "igår rad 1\nigår rad 2\n")
check("förrgår → egen zip", zread(LA.day_zip(d, "2026-11-02"), "todo_app.log") == "förrgår\n")
check("originalen är borta först efter att zippen skrivits", not (d / "todo_app.log.20261103").exists() and not (d / "todo_app.log.20261102").exists())
check("dagens (roterade) fil och pågående logg rörs inte", (d / "todo_app.log.20261104").exists() and (d / "todo_app.log").read_text(encoding="utf-8") == "pågående\n")
check("okända filnamn rörs inte", (d / "todo_app.log.skräp").exists())
check("andra körningen gör inget", LA.archive_day_logs(d, TODAY)["files"] == 0)
check("arkivmappen ligger i loggar/", LA.archive_dir(d) == d / "arkiv")

# samma dag två gånger → båda behålls
(d / "todo_app.log.20261103").write_text("igår igen\n", encoding="utf-8")
LA.archive_day_logs(d, TODAY)
with zipfile.ZipFile(LA.day_zip(d, "2026-11-03")) as z:
    names = sorted(z.namelist())
check("samma dag igen: ny post, inget skrivs över", names == ["todo_app.log", "todo_app.log (2).log"] or len(names) == 2, names)

# fil med skräp i stället för zip: arkiveringen lyckas ändå
d2 = tmpdir()
(d2 / "arkiv").mkdir()
LA.day_zip(d2, "2026-11-03").write_bytes(b"inte en zip")
(d2 / "todo_app.log.20261103").write_text("viktigt\n", encoding="utf-8")
LA.archive_day_logs(d2, TODAY)
check("skräpfil som zip: loggen arkiveras ändå", zread(LA.day_zip(d2, "2026-11-03"), "todo_app.log") == "viktigt\n" and not (d2 / "todo_app.log.20261103").exists())
check("…och zippen går att läsa som vanligt", zipfile.is_zipfile(LA.day_zip(d2, "2026-11-03")))

# ============ appen stängd över midnatt: pågående logg från igår ======================================
d3 = tmpdir()
p = d3 / "todo_app.log"
p.write_text("gammal körning\n", encoding="utf-8")
yday = datetime(2026, 11, 3, 23, 50).timestamp()
os.utime(p, (yday, yday))
check("prepare_active: logg från igår döps om", LA.prepare_active(d3, TODAY) is True and not p.exists() and (d3 / "todo_app.log.20261103").exists())
LA.archive_day_logs(d3, TODAY)
check("…och arkiveras som igår", zread(LA.day_zip(d3, "2026-11-03"), "todo_app.log") == "gammal körning\n")
p.write_text("ny\n", encoding="utf-8")
check("prepare_active: dagens logg rörs inte", LA.prepare_active(d3, TODAY) is False and p.exists())
p.write_text("ny2\n", encoding="utf-8")
(d3 / "todo_app.log.20261103").write_text("redan där\n", encoding="utf-8")
os.utime(p, (yday, yday))
LA.prepare_active(d3, TODAY)
check("prepare_active: finns dagad fil redan läggs texten till (inget skrivs över)", (d3 / "todo_app.log.20261103").read_text(encoding="utf-8") == "redan där\nny2\n")

# ============ uppdateringsväktarens logg: rader per dag ================================================
d4 = tmpdir()
(d4 / "update_watchdog.log").write_text(
    f"{iso(Y2)} 10:00:00 | start\n{iso(Y)} 11:00:00 | ÅTERSTÄLLER\n  detaljrad utan datum\n{iso(TODAY)} 09:00:00 | idag\n", encoding="utf-8")
n = LA.archive_day_logs(d4, TODAY)
check("watchdog: tre gamla rader arkiverade", n["watchdog_lines"] == 3, n)
check("watchdog: filen har bara dagens rader kvar", (d4 / "update_watchdog.log").read_text(encoding="utf-8") == f"{iso(TODAY)} 09:00:00 | idag\n")
check("watchdog: igår-raden + följdrad i igårs zip", "ÅTERSTÄLLER" in zread(LA.day_zip(d4, iso(Y)), "update_watchdog.log") and "detaljrad" in zread(LA.day_zip(d4, iso(Y)), "update_watchdog.log"))
check("watchdog: förrgårs rad i förrgårs zip", "start" in zread(LA.day_zip(d4, iso(Y2)), "update_watchdog.log"))
check("watchdog: inget mer att arkivera", LA.archive_day_logs(d4, TODAY)["watchdog_lines"] == 0)

# ============ fel.log: blockparsning är förlustfri ======================================================
def entry(day, level, msg, extra=""):
    return f"{day} 10:00:00 | {level:<8} | Mod (a.py:1) | {msg}\n" + extra


HDR = lambda day: f"\n═══ Ledgebord startad {day} 08:00:00 (pid 1) ═══\n"  # noqa: E731
sample = (HDR(iso(Y2)) + entry(iso(Y2), "FEL", "gammalt fel", "    Traceback…\n    ValueError\n    ↳ ovanstående upprepades 2 gång(er) till, senast 10:05:00\n")
          + entry(iso(Y2), "VARNING", "gammal varning") + HDR(iso(Y)) + entry(iso(Y), "VARNING", "igårs varning 1")
          + entry(iso(Y), "VARNING", "igårs varning 2") + entry(iso(Y), "KRASCH", "igårs krasch") + HDR(iso(TODAY))
          + entry(iso(TODAY), "VARNING", "dagens varning") + entry(iso(TODAY), "FEL", "dagens fel") + entry(iso(Y), "IMPORT", "importerat fel"))
blocks = EL.parse_blocks(sample)
check("parse_blocks är förlustfri", "".join(b["text"] for b in blocks) == sample)
check("följdrader och ↳-rad hör till sin post", any("ValueError" in b["text"] and "gammalt fel" in b["text"] and "upprepades" in b["text"] for b in blocks))
check("FEL/KRASCH/IMPORT är felposter, VARNING inte",
      [EL.is_error_block(b) for b in blocks if b["kind"] == "entry"] == [True, False, False, False, True, False, True, True])

# ============ tidy ======================================================================================
d5 = tmpdir()
(d5 / "fel.log").write_text(sample, encoding="utf-8")
EL._tidy_sig.clear()
res = EL.tidy(d5, TODAY)
left = (d5 / "fel.log").read_text(encoding="utf-8")
check("tidy: tre gamla varningar arkiverades", res["warnings"] == 3, res)
check("tidy: ALLA felposter ligger kvar (även från förrgår)", all(x in left for x in ("gammalt fel", "igårs krasch", "dagens fel", "importerat fel")))
check("tidy: dagens varning ligger kvar", "dagens varning" in left)
check("tidy: gamla varningar är borta ur fel.log", not any(x in left for x in ("gammal varning", "igårs varning 1", "igårs varning 2")))
check("tidy: följdrader och ↳-rad följde med felet", "ValueError" in left and "upprepades 2 gång(er)" in left)
check("tidy: gamla varningar finns i dagens zip (fel-varningar.log)", "igårs varning 1" in zread(LA.day_zip(d5, iso(Y)), "fel-varningar.log") and "gammal varning" in zread(LA.day_zip(d5, iso(Y2)), "fel-varningar.log"))
check("tidy: sessionshuvud utan kvarvarande poster försvann, dagens finns kvar", f"startad {iso(TODAY)}" in left and f"startad {iso(Y2)}" in left and f"startad {iso(Y)}" in left)  # alla tre har kvarvarande fel
res2 = EL.tidy(d5, TODAY)
check("tidy: andra körningen ändrar inget", res2 == {"warnings": 0, "overflow": 0} and (d5 / "fel.log").read_text(encoding="utf-8") == left)

# bara varningar: tom fil → platshållare
d6 = tmpdir()
(d6 / "fel.log").write_text(HDR(iso(Y)) + entry(iso(Y), "VARNING", "bara varning"), encoding="utf-8")
EL.tidy(d6, TODAY)
check("bara gamla varningar: fel.log blir 'Inga fel loggade'", (d6 / "fel.log").read_text(encoding="utf-8") == EL.PLACEHOLDER)

# ============ öppna fel + åtgärdade ======================================================================
check("open_error_count: 4 öppna (FEL, KRASCH, FEL, IMPORT)", EL.open_error_count(d5) == 4, EL.open_error_count(d5))
check("open_error_count: placeholder → 0", EL.open_error_count(d6) == 0)
check("open_error_count: saknad fil → 0", EL.open_error_count(tmpdir()) == 0)
n = EL.resolve_all(d5, now=datetime(2026, 11, 4, 12, 0).timestamp())
left2 = (d5 / "fel.log").read_text(encoding="utf-8")
arch = (d5 / "arkiv" / EL.RESOLVED_NAME).read_text(encoding="utf-8")
check("resolve_all: 4 fel flyttades", n == 4, n)
check("…ur fel.log (dagens varning kvar)", "dagens fel" not in left2 and "igårs krasch" not in left2 and "dagens varning" in left2)
check("…till arkiv/fel_atgardade.log med datum och stacktrace", "Markerade som åtgärdade 2026-11-04 12:00:00 (4 fel)" in arch and "ValueError" in arch and "igårs krasch" in arch)
check("…och räknas inte längre som öppna", EL.open_error_count(d5) == 0)
check("resolve_all igen: inget att göra", EL.resolve_all(d5) == 0)
EL.resolve_all(d6)
check("resolve_all med bara placeholder: inget skapas", not (d6 / "arkiv" / EL.RESOLVED_NAME).exists())
d7 = tmpdir()
(d7 / "fel.log").write_text(HDR(iso(TODAY)) + entry(iso(TODAY), "FEL", "enda felet"), encoding="utf-8")
EL.resolve_all(d7)
check("alla fel åtgärdade och inga varningar → 'Inga fel loggade'", (d7 / "fel.log").read_text(encoding="utf-8") == EL.PLACEHOLDER)
EL.resolve_all(d7)
EL.resolve_all(d7)
(d7 / "fel.log").write_text(entry(iso(TODAY), "FEL", "fel två"), encoding="utf-8")
EL.resolve_all(d7)
check("flera markeringar läggs efter varandra (inget skrivs över)", (d7 / "arkiv" / EL.RESOLVED_NAME).read_text(encoding="utf-8").count("Markerade som åtgärdade") == 2)

# ============ skrivaren: åtgärdat fel som kommer tillbaka loggas igen ====================================
d8 = tmpdir()
EL._writer = EL._handler = None
lg = logging.getLogger("arch.t")
lg.setLevel(logging.DEBUG)
lg.propagate = False
w = EL.install(d8, root=lg)
lg.error("Samma fel 1")
check("skrivaren: felet loggas", "Samma fel" in (d8 / "fel.log").read_text(encoding="utf-8") and EL.open_error_count(d8) == 1)
EL.resolve_all(d8)
check("åtgärdat → borta ur fel.log", EL.open_error_count(d8) == 0)
lg.error("Samma fel 2")      # samma "typ" av fel inom dedupe-fönstret
txt = (d8 / "fel.log").read_text(encoding="utf-8")
check("kommer felet tillbaka loggas det igen (dedupe nollas)", "Samma fel 2" in txt and EL.open_error_count(d8) == 1)
check("…med nytt sessionshuvud", "Ledgebord startad" in txt)
for h in list(lg.handlers):
    lg.removeHandler(h)
EL._writer = EL._handler = None

# ============ storleksspärr: varningar arkiveras, felposter förloras aldrig ==============================
d9 = tmpdir()
big = HDR(iso(Y)) + "".join(entry(iso(Y), "VARNING", f"brus {i} " + "x" * 200) for i in range(400)) + entry(iso(Y), "FEL", "viktigt fel")
(d9 / "fel.log").write_text(big, encoding="utf-8")
EL._writer = EL._handler = None
w = EL.ErrorLogWriter(d9)
old_max = EL.MAX_BYTES
EL.MAX_BYTES = 5000
EL._tidy_sig.clear()
w._rotate_if_needed()
EL.MAX_BYTES = old_max
after = (d9 / "fel.log").read_text(encoding="utf-8")
check("stor fil: gamla varningar arkiveras, felposten ligger kvar", "viktigt fel" in after and "brus 1 " not in after and LA.day_zip(d9, iso(Y)).exists())
check("…ingen fel.log.1 skapas längre (inget tappas bort)", not (d9 / "fel.log.1").exists())
# orimligt många felposter → de äldsta flyttas till arkiv/fel_overflod.log
d10 = tmpdir()
(d10 / "fel.log").write_text("".join(entry(iso(TODAY), "FEL", f"fel nummer {i} " + "y" * 200) for i in range(300)), encoding="utf-8")
EL._tidy_sig.clear()
r = EL.tidy(d10, TODAY, cap_bytes=20000)
nowtxt = (d10 / "fel.log").read_text(encoding="utf-8")
ov = (d10 / "arkiv" / EL.OVERFLOW_NAME).read_text(encoding="utf-8")
check("överflöd: äldsta felposterna flyttas till arkiv/fel_overflod.log", r["overflow"] > 0 and "fel nummer 0 " in ov and "fel nummer 0 " not in nowtxt)
check("…de nyaste ligger kvar och inget har gått förlorat", "fel nummer 299 " in nowtxt and nowtxt.count("fel nummer") + ov.count("fel nummer") == 300)
check("…filen är under taket", len(nowtxt.encode("utf-8")) <= 20000)

# ============ öppna felloggen städar först ===============================================================
d11 = tmpdir()
(d11 / "fel.log").write_text(entry(iso(Y), "VARNING", "gammal") + entry(iso(Y), "FEL", "kvar"), encoding="utf-8")
EL._writer = EL._handler = None
EL._tidy_sig.clear()
EL.prepare_for_open(d11)
check("prepare_for_open: gamla varningar arkiverade, felet kvar", "gammal" not in (d11 / "fel.log").read_text(encoding="utf-8") and "kvar" in (d11 / "fel.log").read_text(encoding="utf-8"))

# ============ koden är inkopplad ==========================================================================
src = lambda p: (ROOT / p).read_text(encoding="utf-8")  # noqa: E731
boot = src("app/bootstrap.py")
check("start: prepare_active före loggningen, arkivering i bakgrunden efter", boot.index("log_archive.prepare_active(LOGS_DIR)") < boot.index("setup_full_logging(")
      and "log_archive.archive_in_background(LOGS_DIR)" in boot and "error_log.tidy(LOGS_DIR)" in boot)
check("underhåll: arkivering var 5:e minut (täcker midnatt) + vid start", "_run_log_archive(at_startup=False)" in src("app/mixins/maintenance.py") and "_run_log_archive(at_startup=True)" in src("app/mixins/diagnostics.py"))
check("loggar raderas inte längre vid avslut", "cleanup_old_logs" not in src("app/controller.py") and "_run_friday_log_cleanup" not in src("app/mixins/maintenance.py"))
check("tray: 'Markera fel som åtgärdade' finns", "_resolve_errors" in src("app/mixins/tray.py") and "def _resolve_errors" in src("app/mixins/diagnostics.py"))

for x in list(Path(tempfile.gettempdir()).glob("ledgebord_arch_*")):
    shutil.rmtree(x, ignore_errors=True)
print(f"\nlog_archive_test: {ok} lyckades, {fail} misslyckades")
sys.stdout.flush()
os._exit(1 if fail else 0)
