#!/usr/bin/env python3
"""
reminder_schedule_test.py — (1) Ctrl+Alt+N-dialogen ligger överst och flyttar inte fönstret,
(2) datum som 261030 tolkas, (3) påminnelser på förfallodagen: morgon + var 30:e minut tills händelsen.

Kör:  python tester/reminder_schedule_test.py
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "ui"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

_ok = _fail = 0


def check(name, cond, extra=""):
    global _ok, _fail
    if cond:
        _ok += 1
    else:
        _fail += 1
        print(f"  ✗ {name} {extra}")


def schedule_tests() -> None:
    from core import reminder_logic as rl
    day = datetime(2026, 10, 30)
    at = lambda h, m=0: day.replace(hour=h, minute=m)  # noqa: E731
    t_date = {"id": "a", "title": "Fakturera", "due_date": "2026-10-30"}
    t_time = {"id": "b", "title": "Möte", "due_date": "2026-10-30T15:00"}

    check("datum utan tid: ingen påminnelse före 08:00", rl.reminder_due(t_date, at(7, 59), None) is None)
    check("datum utan tid: första påminnelsen kl 08:00", rl.reminder_due(t_date, at(8, 0), None) == (rl.TODAY, 0))
    check("…inte igen efter 10 min", rl.reminder_due(t_date, at(8, 10), at(8, 0)) is None)
    check("…inte efter 29 min", rl.reminder_due(t_date, at(8, 29), at(8, 0)) is None)
    check("…igen efter 30 min (kontrollen går varje minut → 29:30 räcker)", rl.reminder_due(t_date, at(8, 30), at(8, 0)) is not None)
    # hela dagen simulerad med en kontroll per minut
    last, shown = None, []
    for minute in range(0, 24 * 60):
        now = day + timedelta(minutes=minute)
        if rl.reminder_due(t_date, now, last):
            shown.append(now.strftime("%H:%M"))
            last = now
    check("datum utan tid: 08:00, 08:30 … 18:00 (var 30:e minut, sedan slut)", shown[0] == "08:00" and shown[-1] == "18:00" and len(shown) == 21, shown)
    gaps = {(datetime.strptime(b, "%H:%M") - datetime.strptime(a, "%H:%M")).seconds // 60 for a, b in zip(shown, shown[1:])}
    check("avståndet mellan påminnelserna är 30 min (±1 pga minutkontroll)", gaps <= {29, 30, 31} and 30 in gaps | {30}, gaps)
    check("ingen påminnelse efter slutet", rl.reminder_due(t_date, at(18, 1), at(18, 0)) is None and rl.reminder_due(t_date, at(22, 0), at(18, 0)) is None)

    last, shown = None, []
    for minute in range(0, 24 * 60):
        now = day + timedelta(minutes=minute)
        if rl.reminder_due(t_time, now, last):
            shown.append(now.strftime("%H:%M"))
            last = now
    check("med klockslag 15:00: börjar 08:00, slutar exakt 15:00", shown[0] == "08:00" and shown[-1] == "15:00", shown)
    check("…och inget efter klockslaget", "15:30" not in shown and all(x <= "15:00" for x in shown))
    check("klockslag: en sista påminnelse vid 15:00 även när förra var 14:50",
          rl.reminder_due(t_time, at(15, 0), at(14, 50)) is not None)
    # appen startas mitt på dagen
    check("appen startas 11:12 → direkt påminnelse, sedan 30 min senare", rl.reminder_due(t_date, at(11, 12), None) is not None
          and rl.reminder_due(t_date, at(11, 20), at(11, 12)) is None and rl.reminder_due(t_date, at(11, 42), at(11, 12)) is not None)
    check("appen startas efter händelsen (20:00) → en enda påminnelse", rl.reminder_due(t_date, at(20, 0), None) is not None
          and rl.reminder_due(t_date, at(20, 1), at(20, 0)) is None)
    check("tidig händelse 07:30: fönstret börjar en timme före", rl.day_window({"due_date": "2026-10-30T07:30"}, at(6, 0)) == (at(6, 30), at(7, 30)))
    # försenad
    od = {"id": "c", "title": "Gammal", "due_date": "2026-10-28"}
    check("försenad (tidigare dag): direkt, en gång per dag", rl.reminder_due(od, at(9, 0), None) == (rl.OVERDUE, 2)
          and rl.reminder_due(od, at(9, 30), at(9, 0)) is None and rl.reminder_due(od, at(9, 0), at(9, 0) - timedelta(days=1)) is not None)
    check("klar/snoozad/framtida → inget", rl.reminder_due(dict(t_date, done=True), at(9), None) is None
          and rl.reminder_due(dict(t_date, snoozed_until=at(10).isoformat()), at(9), None) is None
          and rl.reminder_due({"id": "z", "due_date": "2026-11-02"}, at(9), None) is None)
    check("första påminnelsen en ny dag trots att den visades igår", rl.reminder_due(t_date, at(8, 5), at(8, 5) - timedelta(days=1)) is not None)
    # texter
    check("kort: tid → 'förfaller idag kl 15:00'", rl.detail_text(t_time, rl.TODAY, 0, at(9)) == "förfaller idag kl 15:00")
    check("kort: tiden har gått → 'tiden har passerat (kl 15:00)'", rl.detail_text(t_time, rl.TODAY, 0, at(16)) == "tiden har passerat (kl 15:00)")
    check("kort: utan tid → 'förfaller idag'", rl.detail_text(t_date, rl.TODAY, 0, at(9)) == "förfaller idag")
    check("event_time", rl.event_time(t_time) == (15, 0) and rl.event_time(t_date) is None and rl.event_time({"due_date": "2026-10-30T00:00"}) is None)


def parsing_tests() -> None:
    from PySide6 import QtCore  # noqa: F401  (widget_base kräver Qt)
    from widget_base import parse_compact_date, parse_natural_input
    today = date(2026, 10, 29)
    check("261030 → 2026-10-30", parse_compact_date("261030", today) == date(2026, 10, 30))
    check("20261030 → 2026-10-30", parse_compact_date("20261030", today) == date(2026, 10, 30))
    check("261331 (månad 13) → inget", parse_compact_date("261331", today) is None)
    check("261032 (dag 32) → inget", parse_compact_date("261032", today) is None)
    check("260230 (30 feb) → inget", parse_compact_date("260230", today) is None)
    check("123456 → inget", parse_compact_date("123456", today) is None)
    check("år långt bak (150101) → inget", parse_compact_date("150101", today) is None)
    check("4 siffror → inget", parse_compact_date("1030", today) is None)
    n = parse_natural_input("Fakturera Andreas 261030")
    check("natural: '261030' → due 2026-10-30, rubrik utan datum", n["due_date"] == "2026-10-30" and n["title"] == "Fakturera Andreas", n)
    n = parse_natural_input("261030 Fakturera")
    check("natural: datum först", n["due_date"] == "2026-10-30" and n["title"] == "Fakturera", n)
    n = parse_natural_input("Möte 20261030 kl 15 !hög #jobb")
    check("natural: 20261030 + tid + prio + tagg", n["due_date"] == "2026-10-30T15:00" and n["priority"] == "high" and n["tags"] == ["jobb"] and n["title"] == "Möte", n)
    n = parse_natural_input("Fakturera 261030 15:30")
    check("natural: 261030 + 15:30", n["due_date"] == "2026-10-30T15:30", n)
    n = parse_natural_input("Order 123456 skickad")
    check("natural: vanligt nummer är inte ett datum", n["due_date"] is None and n["title"] == "Order 123456 skickad", n)
    n = parse_natural_input("Byt vindruta start 261101")
    check("natural: start 261101 → startdatum", n["start_date"] == "2026-11-01", n)
    n = parse_natural_input("Fakturor 2026-10-30")
    check("natural: ISO-datum fungerar som förut", n["due_date"] == "2026-10-30")
    n = parse_natural_input("Telefon 070-123456")
    check("natural: telefonnummer med streck lämnas ifred", n["due_date"] is None, n)


def child(work: str) -> None:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtWidgets import QApplication, QInputDialog
    app = QApplication([])
    res = []

    def ck(n, c, extra=""):
        res.append((n + (f" {extra}" if not c and extra else ""), bool(c)))

    # --- dialogen: överst + fokus ---
    from app.mixins.tray import TrayMixin
    from core.store import TaskStore

    store = TaskStore(data_dir_override=str(Path(work) / "s"))
    calls = {"at_cursor": 0, "lift": 0, "msgs": []}

    class Tray:
        def showMessage(self, *a):
            calls["msgs"].append(a)

    class Ctl(TrayMixin):
        _QSystemTrayIcon = type("T", (), {"MessageIcon": type("I", (), {"Information": 2})})
        _QMessageBox = None

        def __init__(self):
            self.store, self._tray = store, Tray()
            self._log = logging.getLogger("qa")
            self._widget_lock = threading.RLock()
            self._widgets = {}
            self._last_tooltip_update = 0.0
            self.hidden = False

        def _show_window_at_cursor(self):
            calls["at_cursor"] += 1

        def _lift_on_top_temporarily(self):
            calls["lift"] += 1

        def _is_hidden_to_tray(self):
            return self.hidden

        def _update_tray_tooltip(self):
            pass

    c = Ctl()
    seen = {}

    def poke():
        dlgs = [w for w in app.topLevelWidgets() if isinstance(w, QInputDialog) and w.isVisible()]
        seen["n"] = len(dlgs)
        if dlgs:
            d = dlgs[0]
            seen["top"] = bool(d.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
            seen["title"] = d.windowTitle()
            seen["w"] = d.width()
            seen["label"] = d.labelText()
            d.setTextValue("Fakturera Andreas 261030 15:00 !hög #jobb")
            d.accept()

    QTimer.singleShot(300, poke)
    text, ok = c._ask_quick_task_text()
    ck("snabbdialogen öppnades", seen.get("n") == 1, seen)
    ck("snabbdialogen ligger ÖVER alla andra fönster (WindowStaysOnTopHint)", seen.get("top") is True)
    ck("dialogen har rubrik + exempel på datum", "Snabbuppgift" in seen.get("title", "") and "261030" in seen.get("label", ""))
    ck("dialogen returnerar text + OK", ok is True and text.startswith("Fakturera Andreas"))

    # --- hela flödet: datum tolkas, fönstret flyttas inte ---
    QTimer.singleShot(300, poke)
    c._tray_quick_add_task()
    ts = [t for t in store.active_tasks() if "Fakturera" in t.get("title", "")]
    ck("uppgiften skapades", len(ts) == 1, [t.get("title") for t in store.active_tasks()])
    if ts:
        t = ts[0]
        ck("rubriken är utan datum/prio/tagg", t["title"] == "Fakturera Andreas", t["title"])
        ck("förfallodatum 261030 → 2026-10-30 kl 15:00", t.get("due_date") == "2026-10-30T15:00", t.get("due_date"))
        ck("prioritet hög + tagg jobb", t.get("priority") == "high" and "jobb" in (t.get("tags") or []), (t.get("priority"), t.get("tags")))
    ck("fönstret FLYTTAS INTE till muspekaren (positionen behålls)", calls["at_cursor"] == 0)
    ck("listan lyfts en stund där den står", calls["lift"] == 1)
    ck("tray-notis bekräftar", len(calls["msgs"]) == 1)
    c.hidden = True
    QTimer.singleShot(300, lambda: (setattr(poke, "x", 1), poke()))
    c._tray_quick_add_task()
    ck("ligger fönstret i tray lämnas det där (ingen lyftning)", calls["lift"] == 1 and calls["at_cursor"] == 0)

    # avbryt
    def cancel():
        for w in app.topLevelWidgets():
            if isinstance(w, QInputDialog) and w.isVisible():
                w.reject()
    n0 = len(store.active_tasks())
    QTimer.singleShot(300, cancel)
    c.hidden = False
    c._tray_quick_add_task()
    ck("Avbryt skapar ingen uppgift", len(store.active_tasks()) == n0)

    # --- påminnelsetjänsten över dagen (riktig mixin + store) ---
    from app.mixins.reminders import RemindersMixin

    st2 = TaskStore(data_dir_override=str(Path(work) / "s2"))
    st2.add_task("Dagens utan tid", due_date="2026-10-30")
    st2.add_task("Dagens kl 15", due_date="2026-10-30T15:00")
    clock = {"now": datetime(2026, 10, 30, 7, 0)}

    class Tray2:
        def isVisible(self):
            return True

        def showMessage(self, *a):
            pass

        def setIcon(self, i):
            pass

        def setToolTip(self, t):
            pass

    class Ctl2(RemindersMixin):
        _QTimer = type("Q", (), {"singleShot": staticmethod(lambda ms, f: None)})
        _QSystemTrayIcon = type("T", (), {"MessageIcon": type("I", (), {"Warning": 1, "Information": 2})})

        def __init__(self):
            self.store, self._tray = st2, Tray2()
            self.settings = type("S", (), {"reminders_enabled": lambda s: True})()
            self._log = logging.getLogger("r2")
            self._app_icon = None
            self._reminder_last = {}

        def _reminder_now(self):
            return clock["now"]

        def _update_tray_badge(self):
            pass

    r = Ctl2()
    log = []
    for minute in range(7 * 60, 19 * 60):
        clock["now"] = datetime(2026, 10, 30, 0, 0) + timedelta(minutes=minute)
        r._check_reminders()
        pop = getattr(r, "_reminder_popup", None)
        if pop is not None and pop.items():
            log.append((clock["now"].strftime("%H:%M"), sorted(i[1] for i in pop.items()), [i[4] for i in pop.items()]))
            pop.dismiss()
    times = [t for t, _n, _d in log]
    ck("första påminnelsedialogen kl 08:00 (inte före)", times and times[0] == "08:00", times[:3])
    ck("två uppgifter visas samtidigt kl 08:00", log and log[0][1] == ["Dagens kl 15", "Dagens utan tid"], log[:1])
    ck("kortet visar klockslaget", log and "förfaller idag kl 15:00" in log[0][2], log[:1])
    ck("sedan var 30:e minut (08:30, 09:00 …)", "08:30" in times and "09:00" in times and "08:45" not in times, times[:6])
    only_time = [t for t, n, _d in log if n == ["Dagens kl 15"]]
    ck("uppgiften med klockslag påminns sista gången kl 15:00", "15:00" in times and "15:30" not in [t for t, n, _d in log if "Dagens kl 15" in n], [t for t, n, _d in log if "Dagens kl 15" in n][-3:])
    ck("uppgiften utan klockslag påminns till 18:00", times[-1] == "18:00", times[-3:])
    _ = only_time

    bad = [n for n, ok in res if not ok]
    print("CHILD", len(res) - len(bad), len(bad))
    for n in bad:
        print("  ✗", n)
    sys.stdout.flush()
    os._exit(0)


if "--parse" in sys.argv:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    parsing_tests()
    print("PARSED", _ok, _fail, flush=True)
    for _line in ():
        pass
    os._exit(0)
elif "--child" in sys.argv:
    child(sys.argv[-1])
else:
    schedule_tests()
    from _qtenv import qt_env
    work = Path(tempfile.mkdtemp(prefix="remsched_"))
    env, why = qt_env(work)
    if env is None:
        print(f"reminder_schedule_test: Qt-delen hoppas över ({why})")
    else:
        r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--child", str(work)], cwd=ROOT, env=env,
                           capture_output=True, text=True, timeout=300)
        out = r.stdout
        line = [x for x in out.splitlines() if x.startswith("CHILD ")]
        if line:
            _, a, b = line[-1].split()
            _ok += int(a)
            _fail += int(b)
            for x in out.splitlines():
                if x.strip().startswith("✗"):
                    print(x)
        else:
            check("barnprocessen körde klart", False, (r.stdout + r.stderr)[-2500:])
        # parsning kräver Qt-import (widget_base) → kör i samma miljö
        r2 = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--parse"], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=300)
        pl = [x for x in r2.stdout.splitlines() if x.startswith("PARSED ")]
        if pl:
            _, a, b = pl[-1].split()
            _ok += int(a)
            _fail += int(b)
            for x in r2.stdout.splitlines():
                if x.strip().startswith("✗"):
                    print(x)
        else:
            check("parsningstesterna körde klart", False, (r2.stdout + r2.stderr)[-2500:])
    shutil.rmtree(work, ignore_errors=True)
    hs = (ROOT / "app/mixins/hotkeys.py").read_text(encoding="utf-8")
    i = hs.index("def _global_quick_add(")
    check("Ctrl+Alt+N kör inte om skrivbordslagret på ett synligt fönster", "_any_window_not_visible()" in hs[i:i + 900])
    ts = (ROOT / "app/mixins/tray.py").read_text(encoding="utf-8")
    i = ts.index("def _tray_quick_add_task(")
    seg = ts[i:i + 4500]
    check("snabbuppgiften anropar aldrig _show_window_at_cursor", "_show_window_at_cursor()" not in seg)
    print(f"\nreminder_schedule_test: {_ok} lyckades, {_fail} misslyckades")
    sys.exit(1 if _fail else 0)
