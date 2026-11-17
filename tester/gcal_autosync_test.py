#!/usr/bin/env python3
"""
gcal_autosync_test.py — ändrat start-/förfallodatum flyttar händelsen i Google Calendar (om uppgiften finns där).
Google-nätverket är en attrapp. Kör:  python tester/gcal_autosync_test.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "ui"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _src import app_source, widget_source  # noqa: E402

_ok = _fail = 0


def check(name, cond, extra=""):
    global _ok, _fail
    if cond:
        _ok += 1
    else:
        _fail += 1
        print(f"  ✗ {name} {extra}")


def http_error(status, msg="fel"):
    from googleapiclient.errors import HttpError
    from httplib2 import Response
    return HttpError(Response({"status": int(status)}), msg.encode())


class Req:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class Svc:
    def __init__(self):
        self.patches = []
        self.fail = []           # lista av undantag som kastas i tur och ordning
        self.gone = set()

    def events(self):
        return self

    def patch(self, calendarId, eventId, body):
        def run():
            self.patches.append((calendarId, eventId, body))
            if self.fail:
                raise self.fail.pop(0)
            if eventId in self.gone:
                raise http_error(404, "Not Found")
            return {"id": eventId, "htmlLink": "https://calendar.google.com/x"}
        return Req(run)


def main() -> None:
    from core import gcal_autosync as GS
    from core import google_calendar as gcal
    from core.store import TaskStore
    from core.prefs import coerce

    tmp = Path(tempfile.mkdtemp(prefix="ledgebord_gsync_"))
    store = TaskStore(data_dir_override=tmp / "d")
    data = tmp / "d"

    t_in = store.add_task("Vindrutebyte", priority="high", due_date="2026-11-17")
    t_out = store.add_task("Aldrig skickad", due_date="2026-11-17")
    em = gcal.load_event_map(data)
    em.set(t_in, "evA")

    # --- store-signalen
    got = []
    store.dates_changed.connect(lambda tid: got.append(tid))
    store.set_start_date(t_in, "2026-11-24")
    check("store: set_start_date ger dates_changed", got == [t_in], got)
    store.set_due_date(t_in, "2026-11-25")
    check("store: set_due_date ger dates_changed", got == [t_in, t_in])
    store.set_due_date(t_in, "2026-11-25")
    check("store: oförändrat datum ger ingen signal", len(got) == 2)
    store.set_priority(t_in, "low")
    check("store: annan ändring ger ingen datumsignal", len(got) == 2)
    store.set_priority(t_in, "high")

    # --- pure hjälp
    task = store.find_task(t_in)
    p = GS.date_patch(task)
    check("patch: start→slut, slutdatum exklusivt", p == {"start": {"date": "2026-11-24"}, "end": {"date": "2026-11-26"}}, p)
    check("patch: bara datumfält (ingen titel/färg)", set(p) == {"start", "end"})
    check("patch: uppgift utan datum → None", GS.date_patch({"id": "x", "title": "y"}) is None)
    check("beskrivning av enstaka dag", GS.describe_dates({"due_date": "2026-11-23"}) == "mån 23 nov")
    check("beskrivning av period", GS.describe_dates({"start_date": "2026-11-23", "due_date": "2026-11-24"}) == "mån 23 nov – tis 24 nov")
    check("pref gcal_autosync finns, på som standard", coerce("gcal_autosync", None) is True and coerce("gcal_autosync", "nej") is False)

    # --- AutoSync
    svc = Svc()
    results = []
    opts = {"enabled": True, "calendar_id": "cal1", "color": True, "done_style": "grey"}
    a = GS.AutoSync(data, find_task=store.find_task, get_options=lambda: dict(opts), notify=results.append,
                    service_factory=lambda d: svc, connected=lambda d: True, debounce=0.05, retry_delays=(0.05, 0.05))
    check("uppgift som skickats räknas som synkad", a.is_synced_task(t_in) and not a.is_synced_task(t_out))
    check("uppgift som aldrig skickats köas inte", a.request(t_out) is False)
    a.flush(2)
    check("… och ger inget anrop", svc.patches == [])
    check("okänt id köas inte", a.request("finns-inte") is False and a.request("") is False)

    check("ändrad uppgift köas", a.request(t_in) is True)
    check("flush klar", a.flush(5))
    check("ett PATCH-anrop mot rätt kalender/händelse", len(svc.patches) == 1 and svc.patches[0][:2] == ("cal1", "evA"), svc.patches)
    check("PATCH innehåller nya datum", svc.patches[0][2]["start"] == {"date": "2026-11-24"} and svc.patches[0][2]["end"] == {"date": "2026-11-26"})
    check("PATCH rör inget annat", set(svc.patches[0][2]) == {"start", "end"})
    check("notis: uppdaterad", results and results[-1]["action"] == "uppdaterad" and results[-1]["when"] == "tis 24 nov – ons 25 nov", results[-1:])
    hist = gcal.load_history(data).for_task(t_in)
    check("historiken visar automatisk flytt", hist and hist[-1]["action"] == "uppdaterad" and "automatiskt" in hist[-1]["message"], hist[-1:])
    check("inget kvar på disk efter lyckad synk", not GS.pending_path(data).exists())

    # debounce: tre ändringar → ett anrop
    svc.patches.clear()
    for _ in range(3):
        a.request(t_in)
    a.flush(5)
    check("flera ändringar i rad slås ihop till ett anrop", len(svc.patches) == 1, len(svc.patches))

    # av
    svc.patches.clear()
    opts["enabled"] = False
    check("avstängd funktion köar inget", a.request(t_in) is False)
    a.flush(2)
    check("… inga anrop", svc.patches == [])
    opts["enabled"] = True

    # tillfälligt fel → nytt försök → lyckas
    svc.patches.clear()
    results.clear()
    svc.fail = [http_error(503, "backend")]
    a.request(t_in)
    a.flush(5)
    time.sleep(0.6)
    a.flush(5)
    check("tillfälligt fel provas igen och lyckas", results and results[-1]["ok"] and results[-1]["action"] == "uppdaterad", (results, svc.patches))

    # permanent fel (nätet borta) → ger upp, ligger kvar för nästa start
    svc.patches.clear()
    results.clear()
    svc.fail = [OSError("nät"), OSError("nät"), OSError("nät"), OSError("nät"), OSError("nät")]
    a.request(t_in)
    for _ in range(10):
        a.flush(3)
        time.sleep(0.25)
        if results:
            break
    check("ger upp med begripligt fel efter flera försök", results and not results[-1]["ok"] and results[-1]["action"] == "fel" and "startar" in results[-1]["message"], results)
    check("misslyckad synk sparas till nästa start", GS.pending_path(data).exists() and t_in in GS.pending_path(data).read_text(encoding="utf-8"))
    svc.fail = []
    svc.patches.clear()
    results.clear()
    a2 = GS.AutoSync(data, find_task=store.find_task, get_options=lambda: dict(opts), notify=results.append,
                     service_factory=lambda d: svc, connected=lambda d: True, debounce=0.05)
    check("resume tar upp kvarlämnat", a2.resume(delay=0.0) == 1)
    a2.flush(5)
    check("… och flyttar händelsen", len(svc.patches) == 1 and results and results[-1]["ok"])
    check("… och städar disken", not GS.pending_path(data).exists())

    # händelsen borttagen i Google
    svc.patches.clear()
    results.clear()
    svc.gone.add("evA")
    a.request(t_in)
    a.flush(5)
    check("borttagen händelse skapas INTE på nytt (bara patch försökt)", all(c[0] == "cal1" for c in svc.patches) and len(svc.patches) == 1)
    check("kopplingen släpps", gcal.load_event_map(data).get(t_in) is None)
    check("notis om borttagen händelse", results and results[-1]["action"] == "borttagen", results)
    svc.patches.clear()
    check("därefter följer uppgiften inte med längre", a.request(t_in) is False)

    # inte kopplat
    em = gcal.load_event_map(data)
    em.set(t_in, "evB")
    results.clear()
    a3 = GS.AutoSync(data, find_task=store.find_task, get_options=lambda: dict(opts), notify=results.append,
                     service_factory=lambda d: svc, connected=lambda d: False, debounce=0.05)
    svc.patches.clear()
    a3.request(t_in)
    a3.flush(5)
    check("ej kopplat Google → inget anrop, tydlig notis", not svc.patches and results and results[-1]["action"] == "hoppad" and "inte kopplat" in results[-1]["message"], results)

    # uppgiften raderad
    store.remove_task(t_in) if hasattr(store, "remove_task") else store.delete_task(t_in)
    results.clear()
    a.request(t_in)
    a.flush(3)
    check("raderad uppgift → inget fel", not svc.patches)

    # tråden blockerar aldrig anroparen
    slow = Svc()
    orig = slow.patch
    def slow_patch(**kw):
        time.sleep(0.5)
        return orig(**kw)
    em.set(t_out, "evC")
    slow.patch = lambda calendarId, eventId, body: Req(lambda: (time.sleep(0.5), {"id": eventId})[1])
    a4 = GS.AutoSync(data, find_task=store.find_task, get_options=lambda: dict(opts), service_factory=lambda d: slow,
                     connected=lambda d: True, debounce=0.0)
    t0 = time.monotonic()
    a4.request(t_out)
    check("request() väntar inte på Google", time.monotonic() - t0 < 0.2)
    a4.flush(5)
    a4.stop()
    a.stop()

    # --- källkoden: kopplingar finns
    ex = app_source("exports") if False else (ROOT / "app/mixins/exports.py").read_text(encoding="utf-8")
    ctl = (ROOT / "app/controller.py").read_text(encoding="utf-8")
    tray = (ROOT / "app/mixins/tray.py").read_text(encoding="utf-8")
    mb = (ROOT / "app/mixins/mail_bridge_ctl.py").read_text(encoding="utf-8")
    check("controller kopplar synken", "_connect_gcal_autosync()" in ctl)
    check("exports har hanterare och daemon-timer", "def _on_task_dates_changed" in ex and "dates_changed.connect" in ex and "_t.daemon = True" in ex)
    check("notiser visas från GUI-tråden via pollen", "_drain_gcal_sync_results" in mb)
    check("tray har av/på", "gcal_autosync" in tray)
    manual = (ROOT / "docs/MANUAL.md").read_text(encoding="utf-8")
    check("MANUAL beskriver automatisk flytt", "Flytta händelsen när datum ändras" in manual and "nästa vecka" in manual)
    shutil.rmtree(tmp, ignore_errors=True)


def child() -> None:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
    app = QApplication([])
    import widget as W
    from core.settings import Settings
    from core.store import TaskStore
    res = []

    def ck(n, c, e=""):
        res.append((n + (f" {e}" if not c and e else ""), bool(c)))
    tmp = tempfile.mkdtemp(prefix="ledgebord_gsync_ui_")
    settings = Settings(str(Path(tmp) / "s.json"))
    store = TaskStore(data_dir_override=Path(tmp) / "d")
    t = store.add_task("Vindrutebyte", due_date="2026-11-17")
    events = []
    store.dates_changed.connect(events.append)
    shell = QWidget()
    w = W.TodoWidget(app.primaryScreen(), store, settings, win_id="a", parent=shell)
    asked = []
    w._ask_move_due = lambda iso, due: (asked.append((iso, due)), True)[1]
    w._move_start_date(t, "2026-11-24")
    task = store.find_task(t)
    ck("flytt framåt förbi förfallodatum frågar", asked == [("2026-11-24", "2026-11-17")], asked)
    ck("Ja → både start och förfallo flyttas", task.get("start_date") == "2026-11-24" and task.get("due_date") == "2026-11-24", task)
    ck("synk signalerad", events and set(events) == {t})
    asked.clear()
    w._ask_move_due = lambda iso, due: (asked.append(1), False)[1]
    t2 = store.add_task("Annan", due_date="2026-11-17")
    w._move_start_date(t2, "2026-11-30")
    task2 = store.find_task(t2)
    ck("Nej → bara startdatum", task2.get("start_date") == "2026-11-30" and task2.get("due_date") == "2026-11-17", task2)
    asked.clear()
    t3 = store.add_task("Tredje", due_date="2026-11-30")
    w._move_start_date(t3, "2026-11-20")
    ck("start före förfallo frågar inte", not asked and store.find_task(t3).get("start_date") == "2026-11-20")
    t4 = store.add_task("Fjärde")
    w._move_start_date(t4, "2026-11-20")
    ck("utan förfallodatum frågar inte", not asked and store.find_task(t4).get("start_date") == "2026-11-20")
    shutil.rmtree(tmp, ignore_errors=True)
    bad = [n for n, ok in res if not ok]
    print("CHILD", len(res) - len(bad), len(bad))
    for n in bad:
        print("  ✗", n)
    sys.stdout.flush()
    os._exit(0)


if "--child" in sys.argv:
    child()
else:
    try:
        main()
    except ImportError as e:
        print(f"Google-paketen saknas — hoppar över ({e})")
    from _qtenv import qt_env
    work = Path(tempfile.mkdtemp(prefix="ledgebord_gsyncq_"))
    env, why = qt_env(work)
    if env is None:
        print(f"Qt-delen hoppas över ({why})")
    else:
        r = subprocess.run([sys.executable, str(Path(sys.argv[0]).resolve()), "--child"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=200)
        line = [x for x in r.stdout.splitlines() if x.startswith("CHILD ")]
        if line:
            _, a_, b_ = line[-1].split()
            _ok += int(a_)
            _fail += int(b_)
            for x in r.stdout.splitlines():
                if x.strip().startswith("✗"):
                    print(x)
        else:
            check("barnprocessen körde klart", False, (r.stdout + r.stderr)[-2500:])
    shutil.rmtree(work, ignore_errors=True)
    print(f"\ngcal_autosync_test: {_ok} lyckades, {_fail} misslyckades")
    sys.exit(1 if _fail else 0)
