#!/usr/bin/env python3
"""
mail_dates_test.py — datum i importerade mail ("15/11", "november", "december") → påminnelser.

Kör:  python tester/mail_dates_test.py      (ingen Qt behövs)
"""
from __future__ import annotations

import logging
import os
import shutil
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "core"))
logging.disable(logging.CRITICAL)

from core import mail_dates as MD  # noqa: E402
from core import reminder_logic as RL  # noqa: E402

ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("  ✗", name, extra)


T = date(2026, 11, 2)
MAIL = """1st kontrollpanel fram till Royale Lincoln Town Car Limo

Betalning 2

15/11 - om det står ett datum i importerad uppgift från mail som i denna så ska deet läggas en påminnelse det datumet



Ljudutrustning till DNG726 Hummer H2 enligt öv.

1 av 3



Likadan med samma belopp i

november 2/3

och december 3/3 - likadent i denna, om månadsnamn står så ska påminnelse komma upp
"""

# --- 1. extraktion: användarens exempelmail ---------------------------------------------------------------------
f = MD.extract_dates(MAIL, T)
check("exempelmailet: 15/11 och 15/12 (november/december efter 15/11 = samma dag)", [d for d, _ in f] == [date(2026, 11, 15), date(2026, 12, 15)], f)
check("'2/3' efter 'november' blir INTE 2 mars", date(2027, 3, 2) not in [d for d, _ in f])
check("'1 av 3' ignoreras", len(f) == 2)
check("raden ur mailet följer med (rubrik + datumrad)", f[0][1].startswith("Betalning 2 · 15/11"), f[0][1])
check("december-raden med", "december 3/3" in f[1][1], f[1][1])

# --- 2. olika format ---------------------------------------------------------------------------------------------
def dates(txt, today=T):
    return [d for d, _ in MD.extract_dates(txt, today)]

check("15/11-2026", dates("betala 15/11-2026") == [date(2026, 11, 15)])
check("15/11/26", dates("betala 15/11/26") == [date(2026, 11, 15)])
check("2026-11-20", dates("senast 2026-11-20") == [date(2026, 11, 20)])
check("15.11.2026", dates("senast 15.11.2026") == [date(2026, 11, 15)])
check("15 november", dates("senast 15 november") == [date(2026, 11, 15)])
check("15:e november / 5:e januari", dates("15:e november och 5:e januari") == [date(2026, 11, 15), date(2027, 1, 5)])
check("15 nov (förkortning)", dates("senast 15 nov") == [date(2026, 11, 15)])
check("november 15", dates("senast november 15") == [date(2026, 11, 15)])
check("bara 'december' utan föregående datum → 1:a", dates("faktureras i december") == [date(2026, 12, 1)])
check("bara 'november' (månaden pågår, dagen passerad) → idag", dates("betalas i november") == [T])
check("bara 'januari' → nästa år", dates("i januari") == [date(2027, 1, 1)])
check("månadsnamn efter datum tar datumets dag", dates("3 dec och sedan januari") == [date(2026, 12, 3), date(2027, 1, 3)])
check("passerade datum ignoreras", dates("betalades 20/10 och 1/11") == [])
check("årslöst datum långt bakåt → nästa år", dates("15/3") == [date(2027, 3, 15)])
check("klockslag/belopp/telefon ignoreras", dates("kl 10.30, 1.500 kr, tel 08-123 45 67, 12:30") == [])
check("ogiltigt datum (31/2, 40/1) ignoreras", dates("31/2 och 40/1") == [])
check("citerade rader ( > ) hoppas över", dates("> 15/11 gammalt\n20/11 nytt") == [date(2026, 11, 20)])
check("dubbletter slås ihop", dates("15/11 och 15 november och 2026-11-15") == [date(2026, 11, 15)])
check("flera datum sorteras", dates("20/12 och 15/11") == [date(2026, 11, 15), date(2026, 12, 20)])
check("max 12 datum", len(dates(" ".join(f"{d}/12" for d in range(3, 29)) + " " + " ".join(f"{d}/1" for d in range(1, 20)))) <= 12)
check("tomt/None ger []", dates("") == [] and MD.extract_dates(None, T) == [])  # type: ignore[arg-type]

# --- 3. påminnelselogik ------------------------------------------------------------------------------------------
t = {"id": "a", "title": "Kontrollpanel", "remind_dates": ["2026-11-15", "2026-12-15"],
     "remind_info": {"2026-11-15": "Betalning 2 · 15/11", "2026-12-15": "december 3/3"}}
at = lambda d, h=9, m=0: datetime(d.year, d.month, d.day, h, m)  # noqa: E731
check("före första datumet: ingen påminnelse", RL.classify(t, at(date(2026, 11, 14))) is None)
check("på datumet: förfaller idag", RL.classify(t, at(date(2026, 11, 15))) == (RL.TODAY, 0))
check("dagen efter obesvarad: försenad 1 dag", RL.classify(t, at(date(2026, 11, 16))) == (RL.OVERDUE, 1))
check("påminnelse 08:00 på datumet (utan förfallodatum)", RL.reminder_due(t, at(date(2026, 11, 15), 8, 0), None) == (RL.TODAY, 0))
check("…ingen före 08:00", RL.reminder_due(t, at(date(2026, 11, 15), 7, 0), None) is None)
check("klar uppgift påminns inte", RL.classify(dict(t, done=True), at(date(2026, 11, 15))) is None)
check("snoozad uppgift påminns inte", RL.classify(dict(t, snoozed_until="2026-11-15T12:00:00"), at(date(2026, 11, 15))) is None)
check("due_date i framtiden + remind idag → påminner", RL.classify(dict(t, due_date="2027-01-01"), at(date(2026, 11, 15))) == (RL.TODAY, 0))
check("vanlig uppgift utan remind_dates oförändrad", RL.classify({"id": "z", "due_date": "2026-11-15"}, at(date(2026, 11, 15))) == (RL.TODAY, 0))
check("kortets rad: mailraden + nästa datum", "Betalning 2 · 15/11" in RL.detail_text(t, RL.TODAY, 0, at(date(2026, 11, 15))) and "nästa 15/12" in RL.detail_text(t, RL.TODAY, 0, at(date(2026, 11, 15))),
      RL.detail_text(t, RL.TODAY, 0, at(date(2026, 11, 15))))
check("sista datumet: ingen 'nästa'", "nästa" not in RL.detail_text(t, RL.TODAY, 0, at(date(2026, 12, 15))))
check("försenad: texten säger försenad", "försenad 1 dag" in RL.detail_text(t, RL.OVERDUE, 1, at(date(2026, 11, 16))))
check("uppgift utan mailrad: gamla texten", RL.detail_text({"id": "q", "due_date": "2026-11-15"}, RL.TODAY, 0, at(date(2026, 11, 15))) == "förfaller idag")

# Klar-planen
p = RL.plan_done(dict(t, due_date="2026-11-15"), date(2026, 11, 15))
check("Klar på första datumet: flytta förfallodatum till 15/12, bocka INTE av", p["complete"] is False and p["set_due"] == "2026-12-15" and p["next"] == date(2026, 12, 15), p)
p = RL.plan_done(dict(t, due_date="2026-12-15"), date(2026, 12, 15))
check("Klar på sista datumet: bocka av", p["complete"] is True and p["set_due"] is None, p)
p = RL.plan_done(t, date(2026, 11, 15))
check("Klar utan förfallodatum: väntar på nästa, bockas inte av", p["complete"] is False and p["next"] == date(2026, 12, 15) and p["remind_dates"] == ["2026-12-15"], p)
p = RL.plan_done(dict(t, remind_dates=["2026-11-15"]), date(2026, 11, 15))
check("Klar på enda extra-datumet utan förfallodatum: bocka av", p["complete"] is True, p)
p = RL.plan_done(dict(t, remind_dates=["2026-11-15"], due_date="2027-01-01"), date(2026, 11, 15))
check("Klar på extra-datum när egen förfallodag ligger framåt: bockas inte av", p["complete"] is False and p["set_due"] is None, p)
p = RL.plan_done({"id": "v", "due_date": "2026-11-15"}, date(2026, 11, 15))
check("vanlig uppgift: Klar bockar av som förut", p["complete"] is True)

# --- 4. store: importvägarna + sparning ---------------------------------------------------------------------------
from core.store import TaskStore  # noqa: E402
from core import mail_bridge  # noqa: E402

work = Path(tempfile.mkdtemp(prefix="ledgebord_maildates_"))
today = date.today()
d1, d2 = today + timedelta(days=10), today + timedelta(days=40)
body = f"Betalning 2\n\n{d1.day}/{d1.month} - förfaller\n\nLikadan i\n\n{d2.strftime('%d')}/{d2.month}\n"
store = TaskStore(data_dir_override=work / "data")
res = mail_bridge.create_task_from_payload(store, work / "data", {"subject": "Kontrollpanel", "from": "k@x.se", "body": body, "message_id": "<m1@x>"})
tid = res["task_id"]
task = store.find_task(tid)
check("bryggan: remind_dates sparade", task.get("remind_dates") == [d1.isoformat(), d2.isoformat()], task.get("remind_dates"))
check("bryggan: förfallodatum = första datumet", task.get("due_date") == d1.isoformat(), task.get("due_date"))
check("bryggan: mailrad sparad", "Betalning 2" in str((task.get("remind_info") or {}).get(d1.isoformat(), "")))
store.save()
store2 = TaskStore(data_dir_override=work / "data")
t2 = store2.find_task(tid)
check("sparas på disk och finns kvar efter omstart", t2 and t2.get("remind_dates") == [d1.isoformat(), d2.isoformat()] and t2.get("remind_info"), t2 and t2.get("remind_dates"))

res = mail_bridge.create_task_from_payload(store, work / "data", {"subject": "Eget datum", "body": body, "message_id": "<m2@x>", "due_date": (today + timedelta(days=3)).isoformat()})
t3 = store.find_task(res["task_id"])
check("användarens eget förfallodatum vinner; mailens datum blir ändå påminnelser", t3.get("due_date") == (today + timedelta(days=3)).isoformat() and len(t3.get("remind_dates") or []) == 2, t3.get("due_date"))

res = mail_bridge.create_task_from_payload(store, work / "data", {"subject": "Utan datum", "body": "Hej, ring mig. 1 av 3", "message_id": "<m3@x>"})
t4 = store.find_task(res["task_id"])
check("mail utan datum: inget påverkas", not t4.get("remind_dates") and not t4.get("due_date"))

# .eml-vägen
eml = work / "m.eml"
eml.write_text(f"From: Kund <k@x.se>\nTo: me@x.se\nSubject: Delbetalning\nMessage-ID: <e1@x>\nDate: Mon, 02 Nov 2026 10:00:00 +0100\nContent-Type: text/plain; charset=utf-8\n\n{body}", encoding="utf-8")
from core.email_import import import_email  # noqa: E402
tid5 = import_email(eml, store, work / "data")
t5 = store.find_task(tid5)
check(".eml-importen: datum → påminnelser + förfallodatum", t5.get("remind_dates") == [d1.isoformat(), d2.isoformat()] and t5.get("due_date") == d1.isoformat(), (t5.get("remind_dates"), t5.get("due_date")))

# --- 5. Klar-knappen i appen (RemindersMixin._reminder_done) ----------------------------------------------------------
from app.mixins.reminders import RemindersMixin  # noqa: E402


class FakeQTimer:
    @staticmethod
    def singleShot(ms, f): pass


class Quiet:
    def __getattr__(self, n): return lambda *a, **k: None


class Ctl(RemindersMixin):
    def __init__(self, st, now):
        self.store, self._now, self._QTimer, self._log, self._tray = st, now, FakeQTimer, Quiet(), None
        self._reminder_last = {"x": 1}
    def _reminder_now(self): return self._now
    def _update_tray_badge(self): pass


c = Ctl(store, datetime(d1.year, d1.month, d1.day, 9, 0))
c._reminder_last[tid] = datetime.now()
c._reminder_done(tid)
t = store.find_task(tid)
check("Klar på första datumet: uppgiften finns kvar, ej klar", t is not None and not t.get("done") and any(a["id"] == tid for a in store.active_tasks()))
check("…förfallodatum flyttat till andra datumet", t.get("due_date") == d2.isoformat(), t.get("due_date"))
check("…påminnelseminnet nollat (nästa kort kommer direkt på nya datumet)", tid not in c._reminder_last)
c2 = Ctl(store, datetime(d2.year, d2.month, d2.day, 9, 0))
c2._reminder_done(tid)
check("Klar på sista datumet: uppgiften bockas av (arkiveras)", not any(a["id"] == tid for a in store.active_tasks()))
c3 = Ctl(store, datetime.now())
plain = store.add_task("Vanlig", due_date=today.isoformat())
c3._reminder_done(plain)
check("vanlig uppgift: Klar bockar av som förut", not any(a["id"] == plain for a in store.active_tasks()))

shutil.rmtree(work, ignore_errors=True)
print(f"\nmail_dates_test: {ok} lyckades, {fail} misslyckades")
sys.stdout.flush()
os._exit(1 if fail else 0)
