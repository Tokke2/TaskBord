#!/usr/bin/env python3
"""
remind_dates_ui_test.py — 🔔-märket på uppgiften, menyvalet "Påminnelsedatum…" och dialogen (ta bort/lägg till datum).

Kör:  python tester/remind_dates_ui_test.py
Bygger en riktig TodoWidget (offscreen) i en egen process.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date, timedelta
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


def child() -> None:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QDialog, QMenu, QPushButton, QVBoxLayout, QWidget

    app = QApplication([])
    from core.settings import Settings
    from core.store import TaskStore
    from core import reminder_logic as rl
    import widget as W

    res: list = []

    def ck(name, cond, extra=""):
        res.append((name + (" " + str(extra) if not cond and extra else ""), bool(cond)))

    tmp = Path(tempfile.mkdtemp(prefix="taskbord_remui_"))
    settings = Settings(str(tmp / "settings.json"))
    store = TaskStore(data_dir_override=tmp / "data")
    shell = QWidget()
    w = W.TodoWidget(app.primaryScreen(), store, settings, win_id="t", parent=shell)
    lay = QVBoxLayout(shell)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(w)
    w._shell = shell
    shell.resize(420, 640)
    shell.show()
    app.processEvents()

    menus: list = []

    class FakeMenu(QMenu):
        def exec(self, *a, **k):  # noqa: A003
            menus.append([x.text() for x in self.actions()])
            return None

    for _m in ("window_ops", "task_menu", "links_attach"):
        sys.modules[f"ui.widget_parts.{_m}"].QMenu = FakeMenu

    today = date.today()
    d1, d2, d3 = today + timedelta(days=3), today + timedelta(days=14), today + timedelta(days=30)
    tid = store.add_task("Kontrollpanel", priority="none")
    plain = store.add_task("Utan datum", priority="none")
    store.set_task_metadata(tid, "remind_dates", [d1.isoformat(), d2.isoformat(), d3.isoformat()])
    store.set_task_metadata(tid, "remind_info", {d1.isoformat(): "Betalning 2 · förfaller"})
    w._rebuild_task_list()
    app.processEvents()

    def bells():
        return [b for b in w.findChildren(QPushButton) if b.text().startswith("🔔")]

    ck("🔔-märke syns på uppgiften med datum (och bara på den)", len(bells()) == 1, len(bells()))
    b = bells()[0] if bells() else None
    ck("märket visar antalet datum", b is not None and b.text() == "🔔 3", b and b.text())
    tip = b.toolTip() if b else ""
    expect = f"{d1.day}/{d1.month}, {d2.day}/{d2.month}, {d3.day}/{d3.month}"
    ck("tooltip listar datumen (d/m)", ("Påminner: " + expect) in tip, tip)
    ck("tooltip visar mailraden", "Betalning 2" in tip, tip)

    # menyn
    w._show_task_menu(dict(store.find_task(tid)))
    ck("högerklicksmenyn har 🔔 Påminnelsedatum…", any("🔔 Påminnelsedatum…" in t for m in menus for t in m))
    menus.clear()
    w._show_task_menu(dict(store.find_task(plain)))
    ck("…men inte för uppgift utan datum", not any("Påminnelsedatum" in t for m in menus for t in m))

    # dialogen: avmarkera första, spara
    def drive_dialog(uncheck_first=True, press="Spara"):
        def go():
            dlg = next((x for x in app.topLevelWidgets() if isinstance(x, QDialog) and x.isVisible()), None)
            if dlg is None:
                QTimer.singleShot(50, go)
                return
            from PySide6.QtCore import Qt
            from PySide6.QtWidgets import QListWidget
            lst = dlg.findChild(QListWidget)
            if uncheck_first and lst is not None and lst.count():
                lst.item(0).setCheckState(Qt.CheckState.Unchecked)
            for bt in dlg.findChildren(QPushButton):
                if bt.text() == press:
                    bt.click()
                    return
        QTimer.singleShot(50, go)

    drive_dialog(press="Avbryt")
    w._edit_remind_dates(tid)
    ck("Avbryt ändrar inget", len(store.find_task(tid)["remind_dates"]) == 3)
    drive_dialog(uncheck_first=True)
    w._edit_remind_dates(tid)
    t = store.find_task(tid)
    ck("dialogen: avmarkerat datum tas bort", t["remind_dates"] == [d2.isoformat(), d3.isoformat()], t.get("remind_dates"))
    ck("…och dess mailrad försvinner", d1.isoformat() not in (t.get("remind_info") or {}))
    w._rebuild_task_list()
    app.processEvents()
    ck("märket visar nu 2", bells() and bells()[0].text() == "🔔 2", [x.text() for x in bells()])

    # lägg till eget datum via logiken
    d4 = today + timedelta(days=60)
    w._apply_remind_dates(tid, [d2.isoformat(), d3.isoformat(), d4.isoformat()], [d4.isoformat()])
    t = store.find_task(tid)
    ck("eget datum läggs till, sorterat", t["remind_dates"] == [d2.isoformat(), d3.isoformat(), d4.isoformat()])
    ck("eget datum får text 'Eget datum'", t["remind_info"].get(d4.isoformat()) == "Eget datum", t.get("remind_info"))

    # ta bort alla
    w._apply_remind_dates(tid, [], [])
    w._rebuild_task_list()
    app.processEvents()
    ck("inga datum kvar → inget märke", not bells())
    ck("…och reminder_logic ser inga extra datum", rl.remind_days(store.find_task(tid)) == [])
    store.save()
    store2 = TaskStore(data_dir_override=tmp / "data")
    ck("borttagningen finns kvar efter omstart", not (store2.find_task(tid).get("remind_dates")))

    bad = [n for n, ok in res if not ok]
    print("CHILD", len(res) - len(bad), len(bad))
    for n in bad:
        print("  ✗", n)
    shutil.rmtree(tmp, ignore_errors=True)
    sys.stdout.flush()
    os._exit(0)


if "--child" in sys.argv:
    child()
else:
    from _qtenv import qt_env

    work = Path(tempfile.mkdtemp(prefix="taskbord_remuitest_"))
    env, why = qt_env(work)
    if env is None:
        print(f"remind_dates_ui_test: Qt-delen hoppas över ({why})")
    else:
        r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--child"], cwd=ROOT, env=env,
                           capture_output=True, text=True, timeout=300)
        line = [l for l in r.stdout.splitlines() if l.startswith("CHILD ")]
        if line:
            _, a, b = line[-1].split()
            _ok += int(a)
            _fail += int(b)
            for l in r.stdout.splitlines():
                if l.strip().startswith("✗"):
                    print(l)
        else:
            check("barnprocessen körde klart", False, (r.stdout + r.stderr)[-2500:])
    shutil.rmtree(work, ignore_errors=True)
    print(f"\nremind_dates_ui_test: {_ok} lyckades, {_fail} misslyckades")
    sys.exit(1 if _fail else 0)
