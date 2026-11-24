#!/usr/bin/env python3
"""
quiet_hours_test.py — tysta timmar (natt/helger) + valbart påminnelseljud + nya inställningar (core/prefs.py).

Kör:  python tester/quiet_hours_test.py      (ingen Qt behövs)
"""
from __future__ import annotations

import logging
import sys
import tempfile
import wave
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import prefs, quiet_hours as qh, reminder_logic as rl, reminder_sound as rs  # noqa: E402
from core.settings import Settings  # noqa: E402
from core.store import TaskStore  # noqa: E402

_ok = _fail = 0


def ck(name, cond, extra=""):
    global _ok, _fail
    if cond:
        _ok += 1
    else:
        _fail += 1
        print(f"  ✗ {name} {extra}")


def main() -> None:
    # --- prefs ---
    ck("standardvärden", prefs.default("quiet_start") == "22:00" and prefs.default("quiet_end") == "08:00"
       and prefs.default("quiet_enabled") is True and prefs.default("quiet_weekends") is False)
    ck("klockslag rensas", prefs.coerce("quiet_start", "7:5") == "22:00" and prefs.coerce("quiet_start", "7:05") == "07:05"
       and prefs.coerce("quiet_end", "25:00") == "08:00" and prefs.coerce("quiet_end", None) == "08:00")
    ck("bool rensas", prefs.coerce("quiet_weekends", "ja") is True and prefs.coerce("quiet_weekends", "nej") is False
       and prefs.coerce("quiet_enabled", 0) is False)
    ck("heltal klämms", prefs.coerce("text_scale", 999) == 200 and prefs.coerce("text_scale", 10) == 80
       and prefs.coerce("text_scale", "abc") == 100)
    ck("val rensas", prefs.coerce("theme_preset", "hax") == "standard" and prefs.coerce("lang", "EN") == "en")
    try:
        prefs.coerce("finns_inte", 1)
        ck("okänd nyckel → KeyError", False)
    except KeyError:
        ck("okänd nyckel → KeyError", True)

    # --- QuietHours ---
    q = qh.QuietHours()
    D = lambda d, h, m=0: datetime(2026, 11, d, h, m)   # noqa: E731   (18 nov 2026 = onsdag)
    ck("kl 23 är tyst", q.is_quiet(D(18, 23)))
    ck("kl 03 är tyst", q.is_quiet(D(18, 3)))
    ck("kl 21:59 är inte tyst, 22:00 är", not q.is_quiet(D(18, 21, 59)) and q.is_quiet(D(18, 22)))
    ck("kl 07:59 tyst, 08:00 inte", q.is_quiet(D(18, 7, 59)) and not q.is_quiet(D(18, 8)))
    ck("kl 12 är inte tyst", not q.is_quiet(D(18, 12)))
    ck("lördag dagtid ej tyst utan helgval", not q.is_quiet(D(21, 12)))
    qw = qh.QuietHours(weekends=True)
    ck("lördag/söndag tyst med helgval", qw.is_quiet(D(21, 12)) and qw.is_quiet(D(22, 9)) and not qw.is_quiet(D(23, 9)))
    ck("av = aldrig tyst", not qh.QuietHours(enabled=False).is_quiet(D(18, 3)))
    ck("av men helger", qh.QuietHours(enabled=False, weekends=True).is_quiet(D(21, 12)))
    ck("tyst mitt på dagen (utan midnatt)", qh.QuietHours(start="12:00", end="13:00").is_quiet(D(18, 12, 30))
       and not qh.QuietHours(start="12:00", end="13:00").is_quiet(D(18, 13)))
    ck("start == slut = ingen tystnad", not qh.QuietHours(start="08:00", end="08:00").is_quiet(D(18, 8)))
    ck("sammanfattning", q.summary() == "22:00–08:00" and qw.summary().endswith("helger")
       and qh.QuietHours(enabled=False).summary() == "av")
    w = q.active_window(D(18, 12))
    ck("aktivt fönster 08–22", w and w[0].hour == 8 and w[1].hour == 22)
    ck("skräp i tid ger standard", qh.QuietHours(start="xx", end="yy").t_start.hour == 22)

    # --- reminder_due med tysta timmar ---
    task = {"id": "a", "title": "x", "due_date": "2026-11-18"}
    ck("utan quiet: som förut 08:00 ja / 07:00 nej / 22:00 nej",
       rl.reminder_due(task, D(18, 8), None) and not rl.reminder_due(task, D(18, 7), None)
       and not rl.reminder_due(task, D(18, 22), None))
    ck("standard-quiet = samma som förut",
       rl.reminder_due(task, D(18, 8), None, q) and not rl.reminder_due(task, D(18, 7), None, q)
       and not rl.reminder_due(task, D(18, 22), None, q))
    q2 = qh.QuietHours(start="23:00", end="06:00")
    ck("eget fönster 06–23", rl.reminder_due(task, D(18, 6, 30), None, q2) and rl.reminder_due(task, D(18, 22, 30), None, q2)
       and not rl.reminder_due(task, D(18, 23, 30), None, q2) and not rl.reminder_due(task, D(18, 5, 59), None, q2))
    ck("tyst helg: inget på lördag",
       not rl.reminder_due({"id": "a", "title": "x", "due_date": "2026-11-20"}, D(21, 10), None, qw))
    ck("utan helgval: försenad uppgift påminns på lördag",
       rl.reminder_due({"id": "a", "title": "x", "due_date": "2026-11-20"}, D(21, 10), None, q))
    ck("måndag morgon efter tyst helg: första påminnelsen kommer",
       rl.reminder_due({"id": "a", "title": "x", "due_date": "2026-11-20"}, D(23, 8), D(20, 21), qw))
    ck("av = påminnelse även kl 03", rl.reminder_due(task, D(18, 3), None, qh.QuietHours(enabled=False)))
    ck("repetition var 30 min gäller fortfarande",
       rl.reminder_due(task, D(18, 9, 0), D(18, 8, 0), q) and not rl.reminder_due(task, D(18, 8, 15), D(18, 8, 0), q))
    ck("tyst mitt på dagen blockerar",
       not rl.reminder_due(task, D(18, 12, 30), None, qh.QuietHours(start="12:00", end="13:00")))

    # --- ljud ---
    for n in ("chime", "bell", "gentle"):
        b = rs.wav_bytes(n)
        ck(f"{n}: giltig WAV", b[:4] == b"RIFF" and len(b) > 10000)
    ck("none ger inget ljud", rs.wav_bytes("none") == b"" and rs.wav_bytes("finns_inte") == b"")
    td = tempfile.mkdtemp(prefix="quiet_")
    if True:
        p = rs.ensure_file(td, "chime")
        ck("ljudfil skapas i datamappen", p is not None and p.is_file() and Path(td) in p.parents)
        with wave.open(str(p)) as w:
            ck("WAV: mono 16 bit", w.getnchannels() == 1 and w.getsampwidth() == 2 and w.getnframes() > 5000)
        ck("none → ingen fil", rs.ensure_file(td, "none") is None)
        ck("ljudetiketter finns för alla val", set(rs.LABELS) == {"none", "chime", "bell", "gentle"})

        # --- Settings.pref / set_pref ---
        st = Settings(str(Path(td) / "set.json"))
        ck("pref standard", st.pref("quiet_start") == "22:00" and st.pref("text_scale") == 100)
        ck("set_pref sparar rensat värde", st.set_pref("quiet_start", "21:00") and st.pref("quiet_start") == "21:00")
        ck("set_pref avvisar okänd nyckel", st.set_pref("nope", 1) is False)
        st.set_pref("quiet_end", "99:99")
        ck("trasigt värde → standard", st.pref("quiet_end") == "08:00")
        ck("from_settings", qh.from_settings(st).start == "21:00")
        st._data["prefs"] = "skräp"
        ck("trasig prefs-ordlista → standard", st.pref("quiet_start") == "22:00")
        ck("from_settings utan pref → standard", qh.from_settings(object()) == qh.QuietHours())

        # --- mixin: tysta timmar i påminnelsetjänsten + ljud ---
        from app.mixins.reminders import RemindersMixin
        store = TaskStore(data_dir_override=str(Path(td) / "d"))
        store.add_task("Dagens", due_date="2026-11-18")
        clock = {"now": D(18, 7)}
        played = []

        class Tray:
            def isVisible(self):
                return True

            def showMessage(self, *a):
                pass

            def setIcon(self, i):
                pass

            def setToolTip(self, t):
                pass

        class Ctl(RemindersMixin):
            _QTimer = type("Q", (), {"singleShot": staticmethod(lambda ms, f: None)})
            _QSystemTrayIcon = type("T", (), {"MessageIcon": type("I", (), {"Warning": 1, "Information": 2})})

            def __init__(self):
                self.store, self._tray, self.settings = store, Tray(), st
                st._data["prefs"] = {}
                self._log = logging.getLogger("q")
                self._reminder_last = {}

            def _reminder_now(self):
                return clock["now"]

            def _update_tray_badge(self):
                pass

            def _reminder_popup_show(self, items):
                played.append(("popup", clock["now"].strftime("%H:%M")))
                return True

            def _play_reminder_sound(self, name=None):
                played.append(("ljud", clock["now"].strftime("%H:%M")))
                return True

        c = Ctl()
        c._check_reminders()
        ck("kl 07:00: ingen påminnelse (tyst)", not played, played)
        clock["now"] = D(18, 8)
        c._check_reminders()
        ck("kl 08:00: popup + ljud", played == [("popup", "08:00"), ("ljud", "08:00")], played)
        st.set_pref("quiet_end", "09:00")
        c._reminder_last = {}
        played.clear()
        clock["now"] = D(18, 8, 30)
        c._check_reminders()
        ck("tystnaden förlängd till 09:00 → inget kl 08:30", not played, played)
        clock["now"] = D(18, 9)
        c._check_reminders()
        ck("kl 09:00 kommer första påminnelsen", played and played[0] == ("popup", "09:00"), played)

        class Ctl2(RemindersMixin):
            def __init__(self):
                self.store, self.settings = store, st
                self._log = logging.getLogger("q2")

            def _reminder_now(self):
                return clock["now"]

        c2 = Ctl2()
        st.set_notification_sound("none")
        ck("ljud 'none' spelas inte", c2._play_reminder_sound() is False)
        clock["now"] = D(18, 3)
        st.set_notification_sound("gentle")
        ck("inget ljud under tysta timmar", c2._play_reminder_sound() is False)

    import shutil
    import time
    time.sleep(0.6)                      # låt bakgrundssparningarna bli klara innan mappen tas bort
    shutil.rmtree(td, ignore_errors=True)
    doc = (ROOT / "docs" / "MANUAL.md").read_text(encoding="utf-8")
    ck("MANUAL beskriver tysta timmar", "Tysta timmar" in doc and "lördag och söndag" in doc)
    tray = (ROOT / "app" / "mixins" / "tray.py").read_text(encoding="utf-8")
    ck("tray-menyn har tysta timmar", "_add_quiet_menu" in tray)


main()
print(f"\nquiet_hours_test: {_ok} lyckades, {_fail} misslyckades")
sys.exit(1 if _fail else 0)
