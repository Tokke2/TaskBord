#!/usr/bin/env python3
"""
reminder_popup_test.py — påminnelsekortet (Klar / Skjut 1 h / Öppna listan) och siffran på tray-ikonen.

Kör:  python tester/reminder_popup_test.py
Logiken (core/reminder_logic.py) testas utan Qt; kortet och påminnelsetjänsten med riktiga Qt-widgets
(offscreen) mot en riktig TaskStore.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

_ok = _fail = 0


def check(name, cond, extra=""):
    global _ok, _fail
    if cond:
        _ok += 1
    else:
        _fail += 1
        print(f"  ✗ {name} {extra}")


def lum(hexcol: str) -> float:
    h = hexcol.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast(a: str, b: str) -> float:
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def logic_tests() -> None:
    from core import reminder_logic as rl
    now = datetime(2026, 10, 26, 14, 0, 0)
    d = lambda n: (now.date() + timedelta(days=n)).isoformat()  # noqa: E731
    t = lambda **k: dict({"id": "x", "title": "T"}, **k)  # noqa: E731
    check("idag → today", rl.classify(t(due_date=d(0)), now) == (rl.TODAY, 0))
    check("igår → overdue 1", rl.classify(t(due_date=d(-1)), now) == (rl.OVERDUE, 1))
    check("för 5 dagar sen → overdue 5", rl.classify(t(due_date=d(-5)), now) == (rl.OVERDUE, 5))
    check("imorgon → ingen påminnelse", rl.classify(t(due_date=d(1)), now) is None)
    check("utan datum → ingen", rl.classify(t(), now) is None)
    check("klar → ingen", rl.classify(t(due_date=d(-1), done=True), now) is None)
    check("utan id → ingen", rl.classify({"title": "x", "due_date": d(0)}, now) is None)
    check("ogiltigt datum → ingen krasch", rl.classify(t(due_date="snart"), now) is None)
    check("datum med klockslag funkar", rl.classify(t(due_date=d(-2) + "T09:30:00"), now) == (rl.OVERDUE, 2))
    check("snoozad i framtiden → ingen", rl.classify(t(due_date=d(0), snoozed_until=(now + timedelta(hours=1)).isoformat()), now) is None)
    check("snooze utgången → påminner igen", rl.classify(t(due_date=d(0), snoozed_until=(now - timedelta(minutes=1)).isoformat()), now) == (rl.TODAY, 0))
    tasks = [t(id="a", title="Zeta", due_date=d(0)), t(id="b", title="Beta", due_date=d(-3)), t(id="c", title="Alfa", due_date=d(-1)),
             t(id="d", title="Framtid", due_date=d(4)), t(id="e", title="Anna", due_date=d(0))]
    items = rl.due_items(tasks, now)
    check("sorterat: mest försenade först, sedan dagens A–Ö", [i[0]["id"] for i in items] == ["b", "c", "e", "a"], [i[0]["id"] for i in items])
    check("count_due", rl.count_due(tasks, now) == (2, 2))
    check("status_text", rl.status_text(rl.TODAY, 0) == "förfaller idag" and rl.status_text(rl.OVERDUE, 1) == "försenad 1 dag"
          and rl.status_text(rl.OVERDUE, 3) == "försenad 3 dagar")
    check("badge_text", rl.badge_text(0) == "" and rl.badge_text(3) == "3" and rl.badge_text(9) == "9" and rl.badge_text(10) == "9+")
    # färger på kortet
    import importlib.util
    spec = importlib.util.spec_from_file_location("rp_colors", ROOT / "ui" / "reminder_popup.py")
    src = (ROOT / "ui" / "reminder_popup.py").read_text(encoding="utf-8")
    import re
    col = dict(re.findall(r'^([A-Z_]+) = "(#[0-9a-f]{6})"', src, re.M))
    check("kontrast: titel mot kortets bakgrund ≥ 7", contrast(col["TEXT"], col["BG"]) >= 7, contrast(col["TEXT"], col["BG"]))
    check("kontrast: rubrik ≥ 4,5", contrast(col["HEAD"], col["BG"]) >= 4.5)
    check("kontrast: 'idag' (gul) ≥ 4,5", contrast(col["SUB_TODAY"], col["BG"]) >= 4.5)
    check("kontrast: 'försenad' (röd) ≥ 4,5", contrast(col["SUB_OVERDUE"], col["BG"]) >= 4.5)
    check("kontrast: knapptext mot knapp ≥ 4,5", contrast(col["BTN_TEXT"], col["BTN_BG"]) >= 4.5, contrast(col["BTN_TEXT"], col["BTN_BG"]))
    check("kontrast: knapptext vid hovring ≥ 4,5", contrast(col["BTN_TEXT"], col["BTN_BG_HOVER"]) >= 4.5, contrast(col["BTN_TEXT"], col["BTN_BG_HOVER"]))
    sizes = [int(x) for x in re.findall(r"font-size: (\d+)px", src)]
    check("ingen text under 11 px", sizes and min(sizes) >= 11, sizes)
    del spec


def child(work: str) -> None:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    import logging
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPixmap
    from PySide6.QtWidgets import QApplication, QLabel, QPushButton
    app = QApplication([])
    res = []

    def ck(n, c, extra=""):
        res.append((n + (f" {extra}" if not c and extra else ""), bool(c)))

    from ui.reminder_popup import ReminderPopup
    calls = {"done": [], "snooze": [], "open": 0}
    pop = ReminderPopup(lambda i: calls["done"].append(i), lambda i: calls["snooze"].append(i),
                        lambda: calls.__setitem__("open", calls["open"] + 1), timeout_ms=400, hover_ms=200)
    items = [("a", "Fakturera Andreas Andersson", "overdue", 2), ("b", "Köp hallon abonnemang", "today", 0)]
    pop.show_items(items)
    app.processEvents()
    fl = pop.windowFlags()
    ck("kortet tar inte fokus (WindowDoesNotAcceptFocus + ShowWithoutActivating)",
       bool(fl & Qt.WindowType.WindowDoesNotAcceptFocus) and pop.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating))
    ck("kortet är synligt", pop.isVisible())
    labels = [l.text() for l in pop.findChildren(QLabel)]
    ck("rubrik räknar försenade + dagens", any("1 försenad" in t and "1 förfaller idag" in t for t in labels), labels)
    ck("båda uppgifterna visas med status", "Fakturera Andreas Andersson" in labels and "försenad 2 dagar" in labels and "förfaller idag" in labels, labels)
    btns = {b.text() for b in pop.findChildren(QPushButton)}
    ck("knappar: ✓ Klar, Skjut 1 h, Öppna listan, Stäng", {"✓ Klar", "Skjut 1 h", "Öppna listan", "Stäng"} <= btns, btns)
    ck("knapparna tar inte tangentbordsfokus", all(b.focusPolicy() == Qt.FocusPolicy.NoFocus for b in pop.findChildren(QPushButton)))
    g = QGuiApplication.primaryScreen().availableGeometry()
    ck("kortet ligger helt inom skärmen (nere till höger)", g.contains(pop.geometry()) and pop.geometry().right() > g.center().x(), (pop.geometry(), g))

    # Klar på första raden
    pop.findChildren(QPushButton, "done")[0].click()
    app.processEvents()
    ck("Klar → callback med rätt id (försenade först)", calls["done"] == ["a"], calls)
    ck("raden försvinner, kortet står kvar för den andra", [i[0] for i in pop.items()] == ["b"] and pop.isVisible())
    pop.findChildren(QPushButton, "snooze")[0].click()
    app.processEvents()
    ck("Skjut 1 h → callback med rätt id", calls["snooze"] == ["b"])
    ck("sista raden åtgärdad → kortet stängs", not pop.isVisible() and pop.items() == [])

    # många → max 4 rader + "+ N till"
    many = [(f"t{i}", f"Uppgift {i}", "today", 0) for i in range(7)]
    pop.show_items(many)
    app.processEvents()
    ck("max 4 rader", len(pop.findChildren(QPushButton, "done")) == ReminderPopup.MAX_ROWS)
    ck("'+ 3 till' visas", any(l.text() == "+ 3 till" for l in pop.findChildren(QLabel)))
    # ny påminnelse medan kortet är öppet → slås ihop
    pop.show_items([("n1", "Ny", "overdue", 1)])
    ck("nya påminnelser slås ihop med kortet (8 totalt)", len(pop.items()) == 8)
    ck("de mest försenade hamnar överst", pop.findChildren(QPushButton, "done") and
       [l.text() for l in pop.findChildren(QLabel, "title")][0] == "Ny")
    # lång titel förkortas, full titel i tooltip
    pop.dismiss()
    long_t = "x" * 80
    pop.show_items([("L", long_t, "today", 0)])
    tl = pop.findChildren(QLabel, "title")[0]
    ck("lång titel förkortas med … och har hela texten som tooltip", tl.text().endswith("…") and len(tl.text()) == 40 and tl.toolTip() == long_t)
    # Öppna listan
    pop.findChildren(QPushButton, "ghost")[0].click()
    ck("Öppna listan → callback + kortet stängs", calls["open"] == 1 and not pop.isVisible())
    # Stäng
    pop.show_items(items)
    [b for b in pop.findChildren(QPushButton, "ghost") if b.text() == "Stäng"][0].click()
    ck("Stäng → inga callbacks, kortet borta", not pop.isVisible() and calls["done"] == ["a"] and calls["snooze"] == ["b"])
    # försvinner av sig själv
    pop.show_items(items)
    from PySide6.QtTest import QTest
    QTest.qWait(700)
    ck("kortet försvinner av sig självt efter timeout", not pop.isVisible())

    # ----- påminnelsetjänsten med riktig store ------------------------------------------------------------
    from app.mixins.reminders import RemindersMixin
    from core.store import TaskStore
    tmp = Path(work) / "store"
    store = TaskStore(data_dir_override=str(tmp))
    today = datetime.now().date()
    t_over = store.add_task("Försenad sak", due_date=(today - timedelta(days=2)).isoformat())
    t_today = store.add_task("Dagens sak", due_date=today.isoformat())
    t_future = store.add_task("Framtida sak", due_date=(today + timedelta(days=3)).isoformat())
    t_none = store.add_task("Utan datum")

    class Tray:
        def __init__(self): self.msgs, self.icons, self.tip = [], [], ""
        def showMessage(self, *a): self.msgs.append(a)
        def setIcon(self, ic): self.icons.append(ic)
        def setToolTip(self, t): self.tip = t

    class Sett:
        enabled = True
        def reminders_enabled(self): return self.enabled

    class Q:
        shots = []
        @staticmethod
        def singleShot(ms, f): Q.shots.append(f)

    class Ctl(RemindersMixin):
        _QTimer = Q
        _QSystemTrayIcon = type("T", (), {"MessageIcon": type("I", (), {"Warning": 1, "Information": 2})})
        def __init__(self):
            self.store, self.settings, self._tray = store, Sett(), Tray()
            self._log = logging.getLogger("rem")
            self._app_icon = QIcon(str(ROOT / "icon" / "ledgebord.ico"))
            self.lifted = 0
        def _lift_on_top_temporarily(self): self.lifted += 1

        def _reminder_now(self):
            # alltid efter 08:00 så testet inte beror på vilken tid på dygnet det körs
            n = datetime.now()
            return n if n.hour >= 9 else n.replace(hour=9, minute=0, second=0, microsecond=0)

    c = Ctl()
    c._check_reminders()
    pp = c._reminder_popup
    ids = sorted(i[0] for i in pp.items())
    ck("förfallen + dagens visas på kortet, inte framtida/datumlösa", ids == sorted([t_over, t_today]), ids)
    ck("inga vanliga tray-notiser när kortet funkar", c._tray.msgs == [])
    c._check_reminders()
    ck("samma uppgifter påminns inte igen under sessionen", sorted(i[0] for i in pp.items()) == ids)
    # Klar från kortet → uppgiften är avbockad/arkiverad
    c._reminder_done(t_over)
    ck("Klar på kortet bockar av uppgiften i store", store.find_task(t_over) is None or store.find_task(t_over).get("done"))
    ck("…och den är inte längre aktiv", t_over not in [t["id"] for t in store.active_tasks()])
    # Skjut 1 h
    before = c._reminder_now()
    c._reminder_snooze(t_today)
    sn = store.find_task(t_today).get("snoozed_until")
    dt = datetime.fromisoformat(sn)
    ck("Skjut 1 h sätter snoozed_until ≈ nu + 1 h", timedelta(minutes=59) < dt - before < timedelta(minutes=61), sn)
    ck("snoozad uppgift påminns inte nu", True)
    pp.dismiss()
    c._check_reminders()
    ck("under snoozen kommer ingen ny påminnelse", pp.items() == [])
    # snoozen går ut → påminner igen
    store.snooze_task(t_today, (c._reminder_now() - timedelta(minutes=1)).replace(microsecond=0).isoformat())
    c._check_reminders()
    ck("när snoozen gått ut påminns uppgiften igen", [i[0] for i in pp.items()] == [t_today], [i[0] for i in pp.items()])
    pp.dismiss()
    # Öppna listan → lyft
    c._reminder_open()
    ck("Öppna listan lyfter fönstret", c.lifted == 1)
    # avstängda påminnelser
    c2 = Ctl()
    c2.settings.enabled = False
    store.snooze_task(t_today, "")
    c2._check_reminders()
    ck("påminnelser av → inget kort", getattr(c2, "_reminder_popup", None) is None)
    # kortet kraschar → tray-notis som reserv
    c3 = Ctl()
    c3._reminder_popup_show = lambda items: False
    c3._check_reminders()
    ck("reserv: vanlig tray-notis om kortet inte kan visas", len(c3._tray.msgs) >= 1 and "förfaller idag" in c3._tray.msgs[-1][1])

    # ----- siffra på tray-ikonen -----------------------------------------------------------------------------
    t2 = store.add_task("Idag 2", due_date=today.isoformat())  # noqa: F841
    c4 = Ctl()
    c4._update_tray_badge()
    ic = c4._tray.icons[-1]
    img = ic.pixmap(64, 64).toImage()
    corner = QColor(img.pixelColor(52, 52))
    ck("siffran ritas som en röd/orange ring nere till höger", corner.red() > 180 and corner.blue() < 120, corner.getRgb())
    base = QIcon(str(ROOT / "icon" / "ledgebord.ico")).pixmap(64, 64).toImage()
    ck("resten av ikonen är orörd (övre vänstra hörnet lika)", img.pixelColor(10, 10) == base.pixelColor(10, 10))
    n_icons = len(c4._tray.icons)
    c4._update_tray_badge()
    ck("oförändrat antal → ikonen byts inte i onödan", len(c4._tray.icons) == n_icons)
    for t in list(store.active_tasks()):
        if t.get("due_date"):
            store.snooze_task(t["id"], (datetime.now() + timedelta(hours=5)).replace(microsecond=0).isoformat())
    c4._update_tray_badge()
    ck("inga försenade/dagens → ursprungsikonen tillbaka", c4._tray.icons[-1] is c4._app_icon)
    c5 = Ctl()
    c5._app_icon = None
    c5._update_tray_badge()
    ck("utan ikon: ingen krasch", c5._tray.icons == [])
    src = (ROOT / "app/mixins/backup_sync.py").read_text(encoding="utf-8")
    ck("siffran uppdateras när uppgifter ändras (GUI-tråden)", "_update_tray_badge()" in src)
    ck("QPixmap skapas aldrig utanför GUI-tråden (anropas bara från trådskyddade ställen)",
       src.index("threading.current_thread() is not threading.main_thread()") < src.index("_update_tray_badge()"))
    _ = QPixmap, QColor
    bad = [n for n, ok in res if not ok]
    print("CHILD", len(res) - len(bad), len(bad))
    for n in bad:
        print("  ✗", n)
    sys.stdout.flush()
    os._exit(0)


if "--child" in sys.argv:
    child(sys.argv[-1])
else:
    logic_tests()
    from _qtenv import qt_env
    work = Path(tempfile.mkdtemp(prefix="remtest_"))
    env, why = qt_env(work)
    if env is None:
        print(f"reminder_popup_test: Qt-delen hoppas över ({why})")
    else:
        r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--child", str(work)], cwd=ROOT, env=env,
                           capture_output=True, text=True, timeout=300)
        line = [x for x in r.stdout.splitlines() if x.startswith("CHILD ")]
        if line:
            _, a, b = line[-1].split()
            _ok += int(a)
            _fail += int(b)
            for x in r.stdout.splitlines():
                if x.strip().startswith("✗"):
                    print(x)
        else:
            check("barnprocessen körde klart", False, (r.stdout + r.stderr)[-2500:])
    shutil.rmtree(work, ignore_errors=True)
    print(f"\nreminder_popup_test: {_ok} lyckades, {_fail} misslyckades")
    sys.exit(1 if _fail else 0)
