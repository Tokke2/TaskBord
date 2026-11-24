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
check("…med 'upprepades 5 gång(er)'", "Upprepades 5 gång(er)" in t, t)
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
check("stor fil: ingen fel.log.1 längre (felposter får inte försvinna)", not (d / "fel.log.1").exists() and (d / "fel.log").exists())
check("stor fil: alla 80 felposter ligger kvar tills de åtgärdats", read(d).count("| FEL") == 80, read(d).count("| FEL"))

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

# ---- nya fel (röd prick) --------------------------------------------------------------------------------
_d = Path(tempfile.mkdtemp(prefix="ledgebord_errseen_"))
_t = time.time()
_fmt = lambda ts: time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
check("inget log → 0 nya fel", EL.count_unseen(_d, now=_t) == 0)
check("första anropet sätter baslinjen (fel_seen.txt skapas)", EL.read_seen(_d) is not None)
(_d / "fel.log").write_text(
    f"{_fmt(_t - 500)} | FEL      | a (x.py:1) | gammalt fel\n"
    f"{_fmt(_t + 5)} | FEL      | a (x.py:2) | nytt fel\n    följdrad\n"
    f"{_fmt(_t + 6)} | KRASCH   | a (x.py:3) | krasch\n"
    f"{_fmt(_t + 7)} | VARNING  | a (x.py:4) | varning räknas inte\n"
    f"{_fmt(_t + 8)} | IMPORT   | update_watchdog | importerat räknas inte\n",
    encoding="utf-8")
check("endast FEL/KRASCH nyare än baslinjen räknas", EL.count_unseen(_d) == 2, EL.count_unseen(_d))
check("cache ger samma svar", EL.count_unseen(_d) == 2)
with open(_d / "fel.log", "a", encoding="utf-8") as _f:
    _f.write(f"{_fmt(_t + 20)} | FEL      | b (y.py:9) | ett till\n")
check("ny rad syns direkt trots cache", EL.count_unseen(_d) == 3)
EL.mark_seen(_d, when=_t + 30)
check("öppnat felloggen → 0 nya", EL.count_unseen(_d) == 0)
with open(_d / "fel.log", "a", encoding="utf-8") as _f:
    _f.write(f"{_fmt(_t + 60)} | FEL      | b (y.py:10) | efter öppnandet\n")
check("fel efter öppnandet räknas igen", EL.count_unseen(_d) == 1)
check("fel_seen.txt ligger i data-mappen", EL.seen_path(_d).parent == _d)
(_d / "fel.log").write_text(EL.PLACEHOLDER, encoding="utf-8")
check("platshållartexten ger 0", EL.count_unseen(_d) == 0)
shutil.rmtree(_d, ignore_errors=True)

# --- Qt-meddelanden: rätt nivå (info var förut KRASCH) ------------------------------------------------------------
import logging as _lg
check("qt_msg_level: debug/warning/critical/fatal/info",
      [EL.qt_msg_level(i) for i in range(5)] == [_lg.DEBUG, _lg.WARNING, _lg.ERROR, _lg.CRITICAL, _lg.INFO], [EL.qt_msg_level(i) for i in range(5)])
check("qt_msg_level: info (FFmpeg-raden) blir inte KRASCH", EL.qt_msg_level(4) < _lg.WARNING)


class _Enumish:
    value = 4


check("qt_msg_level: enum med .value", EL.qt_msg_level(_Enumish()) == _lg.INFO)
check("qt_msg_level: textform QtInfoMsg", EL.qt_msg_level("QtMsgType.QtInfoMsg") == _lg.INFO and EL.qt_msg_level("junk") == _lg.WARNING)
_bs = (ROOT / "app" / "bootstrap.py").read_text(encoding="utf-8")
check("bootstrap använder qt_msg_level", "qt_msg_level(mode)" in _bs and "QtInfoMsg\n" not in _bs)
_ft = (ROOT / "ui" / "widget_parts" / "focus_timers.py").read_text(encoding="utf-8")
check("kortkommandon som hanteras annorstädes varnar inte", "_SHORTCUTS_HANDLED_ELSEWHERE" in _ft and "toggle_inbox" in _ft)

# Två olika fel får inte dela en sammanfattning.
with tempfile.TemporaryDirectory() as _dedupe_tmp:
    _dedupe_path = Path(_dedupe_tmp)
    _dedupe_writer = EL.ErrorLogWriter(_dedupe_path)
    for _message in ("första felet", "första felet", "andra felet", "andra felet"):
        _dedupe_writer.write_record(logging.LogRecord("test", logging.ERROR, "test.py", 1, _message, (), None))
    _dedupe_writer.flush_summaries()
    _dedupe_text = _dedupe_writer.path.read_text(encoding="utf-8")
    _dedupe_blocks = [b for b in EL.parse_blocks(_dedupe_text) if b["kind"] == "entry"]
    check("upprepningar hör till respektive fel", len(_dedupe_blocks) == 2 and
          all("Upprepades 1" in b["text"] for b in _dedupe_blocks))

# --- Automatiskt åtgärdade fel -----------------------------------------------------------------------------------
def _entry(ts, level, where, msg):
    return f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))} | {level:<8} | {where} | {msg}\n"


_now = time.time()
_day = 86400
_ad = Path(tempfile.mkdtemp(prefix="ledgebord_autores_"))
_hdr = lambda ts: f"\n═══ Ledgebord startad {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))} (pid 1) ═══\n"
_txt = (_hdr(_now - 40 * _day)
        + _entry(_now - 40 * _day, "KRASCH", "Main (bootstrap.py:426)", "[MAIN] Qt-meddelande: Using Qt multimedia with FFmpeg version 7.1.5 LGPL (fil=None, rad=0)")
        + _entry(_now - 30 * _day, "FEL", "Store (store.py:10)", "gammalt fel 123 som aldrig kom tillbaka")
        + "    Traceback (most recent call last):\n      File x\n"
        + _entry(_now - 30 * _day, "FEL", "Widget (w.py:5)", "återkommande fel 5")
        + _hdr(_now - 2 * _day)
        + _entry(_now - 2 * _day, "FEL", "Widget (w.py:5)", "återkommande fel 9")
        + _entry(_now - 3 * _day, "FEL", "Mail (m.py:1)", "nytt fel")
        + _entry(_now - 30 * _day, "VARNING", "Widget (r.py:1)", "gammal varning rörs inte här"))
(_ad / "fel.log").write_text(_txt, encoding="utf-8")
EL._writer = None
_r = EL.auto_resolve(_ad, now=_now, days=14)
check("auto: ett känt rättat fel och ett tyst gammalt fel arkiveras", _r == {"known": 1, "quiet": 1}, _r)
_left = (_ad / "fel.log").read_text(encoding="utf-8")
check("auto: nya fel ligger kvar", "nytt fel" in _left)
check("auto: fel som återkommit nyligen ligger kvar (alla förekomster)", "återkommande fel 5" in _left and "återkommande fel 9" in _left)
check("auto: det tysta felet och KRASCH-raden är borta ur fel.log", "gammalt fel" not in _left and "multimedia" not in _left and "Traceback" not in _left)
check("auto: varningar rörs inte här", "gammal varning" in _left)
_arch = (_ad / "arkiv" / EL.RESOLVED_NAME).read_text(encoding="utf-8")
check("auto: arkivet har posterna + stacktrace + rubrik", "Automatiskt arkiverade" in _arch and "multimedia" in _arch and "gammalt fel" in _arch and "Traceback" in _arch, _arch[:300])
check("auto: andra körningen gör inget", EL.auto_resolve(_ad, now=_now, days=14) == {"known": 0, "quiet": 0})
check("auto: öppna fel räknas om", EL.open_error_count(_ad) == 3, EL.open_error_count(_ad))
check("auto: 10 dagar senare (13 dagar sedan senaste) ligger de kvar", EL.auto_resolve(_ad, now=_now + 10 * _day, days=14) == {"known": 0, "quiet": 0})
check("auto: 13 dagar senare (16 dagar) arkiveras resten", EL.auto_resolve(_ad, now=_now + 13 * _day, days=14) == {"known": 0, "quiet": 3})
# allt åtgärdat → fel.log får den trevliga platshållaren
_ad2 = Path(tempfile.mkdtemp(prefix="ledgebord_autores_"))
(_ad2 / "fel.log").write_text(_hdr(_now - 50 * _day) + _entry(_now - 50 * _day, "FEL", "A (a.py:1)", "urgammalt fel"), encoding="utf-8")
check("auto: allt åtgärdat → platshållaren 'Inga fel loggade'", EL.auto_resolve(_ad2, now=_now, days=14)["quiet"] == 1 and (_ad2 / "fel.log").read_text(encoding="utf-8") == EL.PLACEHOLDER)
check("auto: ingen fel.log alls ger inget fel", EL.auto_resolve(_ad2 / "finns_inte", now=_now, days=14) == {"known": 0, "quiet": 0})
# manuella 'markera som åtgärdade' fungerar som förut (delad hjälpfunktion)
_ad3 = Path(tempfile.mkdtemp(prefix="ledgebord_autores_"))
(_ad3 / "fel.log").write_text(_hdr(_now) + _entry(_now, "FEL", "A (a.py:1)", "nyss") + _entry(_now, "VARNING", "A (a.py:2)", "varning"), encoding="utf-8")
check("manuell markering: felposten flyttas, varningen blir kvar", EL.resolve_all(_ad3) == 1 and "varning" in (_ad3 / "fel.log").read_text(encoding="utf-8") and "nyss" in (_ad3 / "arkiv" / EL.RESOLVED_NAME).read_text(encoding="utf-8"))
_bs2 = (ROOT / "app" / "bootstrap.py").read_text(encoding="utf-8")
_mt = (ROOT / "app" / "mixins" / "maintenance.py").read_text(encoding="utf-8")
check("appen kör auto_resolve vid start och löpande", "error_log.auto_resolve(LOGS_DIR)" in _bs2 and "error_log.auto_resolve(logs)" in _mt)
for _x in (_ad, _ad2, _ad3):
    shutil.rmtree(_x, ignore_errors=True)

print(f"\nerror_log_test: {ok} lyckades, {fail} misslyckades")
sys.stdout.flush()
os._exit(1 if fail else 0)
