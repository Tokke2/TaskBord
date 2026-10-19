#!/usr/bin/env python3
"""
keynav_test.py — tangentbordsnavigering i listan + textstorlek/densitet.

Kör:  python tester/keynav_test.py
Bygger en riktig TodoWidget (offscreen) i en egen process och skickar tangenttryck.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
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
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication

    app = QApplication([])
    from core.settings import Settings
    from core.store import TaskStore
    import widget as W

    tmp = tempfile.mkdtemp(prefix="taskbord_nav_")
    settings = Settings(str(Path(tmp) / "settings.json"))
    store = TaskStore(data_dir_override=Path(tmp) / "data")
    ids = [store.add_task(t) for t in ("Alfa", "Beta", "Gamma", "Delta")]
    from PySide6.QtWidgets import QVBoxLayout, QWidget
    shell = QWidget()  # som i appen: skal-fönstret äger TodoWidget (barn-läge)
    w = W.TodoWidget(app.primaryScreen(), store, settings, win_id="t", parent=shell)
    lay = QVBoxLayout(shell)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(w)
    w._shell = shell
    shell.resize(420, 520)
    shell.show()
    app.processEvents()
    w._rebuild_task_list()
    app.processEvents()

    res: list[tuple[str, bool]] = []

    def ck(name, cond):
        res.append((name, bool(cond)))

    def press(key, text=""):
        ev = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier, text)
        w.keyPressEvent(ev)
        app.processEvents()
        return ev

    def order():
        return list(w._nav_tids)

    def sel_card():
        return [t for t, c in w._task_widgets.items() if c.property("taskSelected")]

    ck("listan har 4 uppgifter i nav-ordning", len(order()) == 4)
    ck("ingen markering från start", w._sel_tid is None and not sel_card())

    # --- riktig tangentväg: ↓ i inmatningsfältet (QShortcut) → fokus flyttas till listan --
    from PySide6.QtTest import QTest
    shell.activateWindow()
    app.processEvents()
    w.input_field.setFocus()
    app.processEvents()
    QTest.keyClick(w.input_field, Qt.Key.Key_Down)
    app.processEvents()
    ck("verklig ↓ i inmatningsfältet markerar första", w._nav_active and w._sel_tid == order()[0])
    ck("fokus har lämnat inmatningsfältet", not w.input_field.hasFocus())
    ck("fokus ligger på listan (widgeten)", QApplication.focusWidget() is w)
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_2)
    app.processEvents()
    ck("verklig tangent '2' sätter prioritet", store.find_task(order()[0]).get("priority") == "medium")
    store.set_priority(order()[0], "none")
    w._nav_exit()
    app.processEvents()

    # --- ↓ / ↑ -------------------------------------------------------------------------
    w._navigate_tasks(Qt.Key.Key_Down)
    o = order()
    ck("↓ markerar första uppgiften", w._sel_tid == o[0] and sel_card() == [o[0]])
    ck("navigeringsläge aktivt", w._nav_active)
    w._navigate_tasks(Qt.Key.Key_Down)
    ck("↓ igen → andra", w._sel_tid == o[1] and sel_card() == [o[1]])
    w._navigate_tasks(Qt.Key.Key_End)
    ck("End → sista", w._sel_tid == o[-1])
    w._navigate_tasks(Qt.Key.Key_Down)
    ck("↓ på sista stannar kvar", w._sel_tid == o[-1])
    w._navigate_tasks(Qt.Key.Key_Home)
    ck("Home → första", w._sel_tid == o[0])
    w._navigate_tasks(Qt.Key.Key_Down)
    w._navigate_tasks(Qt.Key.Key_Up)
    ck("↑ flyttar upp ett steg", w._sel_tid == o[0])

    # --- prioritet 1/2/3/0 -------------------------------------------------------------
    press(Qt.Key.Key_1, "1")
    ck("1 = hög prioritet", store.find_task(o[0]).get("priority") == "high")
    press(Qt.Key.Key_2, "2")
    ck("2 = normal prioritet", store.find_task(o[0]).get("priority") == "medium")
    press(Qt.Key.Key_3, "3")
    ck("3 = låg prioritet", store.find_task(o[0]).get("priority") == "low")
    press(Qt.Key.Key_0, "0")
    ck("0 = ingen prioritet", store.find_task(o[0]).get("priority") == "none")
    ck("markeringen finns kvar efter ombyggnad", w._sel_tid == o[0] and sel_card() == [o[0]])

    # --- P = fäst ----------------------------------------------------------------------
    first_before = order()[0]
    w._navigate_tasks(Qt.Key.Key_Down)  # → andra
    target = w._sel_tid
    press(Qt.Key.Key_P, "p")
    ck("P fäster uppgiften", bool(store.find_task(target).get("pinned")))
    w._rebuild_task_list()
    app.processEvents()
    ck("fäst uppgift hamnar överst och är fortfarande markerad",
       order()[0] == target and w._sel_tid == target and sel_card() == [target])
    press(Qt.Key.Key_P, "p")
    ck("P igen lossar", not store.find_task(target).get("pinned"))
    w._rebuild_task_list()
    app.processEvents()

    # --- E / F2 / Delete anropar dialogerna (modala → ersatta) ---------------------------
    calls = []
    w._prompt_rename = lambda tid: calls.append(("rename", tid))
    w._prompt_delete = lambda tid: calls.append(("delete", tid))
    cur = w._sel_tid
    press(Qt.Key.Key_E, "e")
    press(Qt.Key.Key_F2, "")
    press(Qt.Key.Key_Delete, "")
    ck("E och F2 → redigera", calls[:2] == [("rename", cur), ("rename", cur)])
    ck("Delete → ta bort (med bekräftelse)", calls[2:] == [("delete", cur)])

    # --- Space = klar → uppgiften lämnar listan, markeringen går till grannen -----------
    w._navigate_tasks(Qt.Key.Key_Home)
    n_before = len(order())
    gone = w._sel_tid
    expect_next = order()[1]
    press(Qt.Key.Key_Space, " ")
    app.processEvents()
    ck("Space markerar klar (arkiveras)", store.find_task(gone) is not None and bool(store.find_task(gone).get("done")))
    ck("listan har en färre", len(order()) == n_before - 1 and gone not in order())
    ck("markeringen flyttas till nästa uppgift", w._sel_tid == expect_next and sel_card() == [expect_next])

    # --- text → tillbaka till inmatningsfältet ------------------------------------------
    press(Qt.Key.Key_X, "x")
    ck("tecken lämnar läget", not w._nav_active and w._sel_tid is None and not sel_card())
    ck("tecknet hamnar i inmatningsfältet", w.input_field.text() == "x")
    w.input_field.clear()

    # --- Esc lämnar läget, utan att stänga fönstret --------------------------------------
    w._navigate_tasks(Qt.Key.Key_Down)
    closed = []
    w._on_close_clicked = lambda: closed.append(1)
    press(Qt.Key.Key_Escape)
    ck("Esc lämnar navigeringsläget", not w._nav_active and not sel_card())
    ck("första Esc gömmer inte fönstret", not closed)
    press(Qt.Key.Key_Escape)
    ck("andra Esc gör som förut (gömmer)", closed == [1])

    # --- ↑ överst lämnar listan -----------------------------------------------------------
    w._navigate_tasks(Qt.Key.Key_Home)
    w._navigate_tasks(Qt.Key.Key_Up)
    ck("↑ på första lämnar listan", not w._nav_active and w._sel_tid is None)

    # --- bokstäver gör inget utan navigeringsläge ---------------------------------------
    calls.clear()
    press(Qt.Key.Key_P, "p")
    ck("P utanför navigeringsläget gör inget", not store.active_tasks() or not any(t.get("pinned") for t in store.active_tasks()))

    # --- arkivfliken: ingen navigering -----------------------------------------------------
    w.tabs.setCurrentIndex(1)
    w._navigate_tasks(Qt.Key.Key_Down)
    ck("ingen navigering i Arkiverade-fliken", not w._nav_active)
    w.tabs.setCurrentIndex(0)

    # --- textstorlek / densitet -------------------------------------------------------------
    def card_metrics():
        c = next(iter(w._task_widgets.values()))
        m = c.layout().contentsMargins()
        return m.top(), c.layout().spacing()

    def title_px():
        import re
        ss = w.styleSheet()
        m = re.search(r"QWidget#TodoWidget\s*\{[^}]*?font-size:\s*(\d+)px", ss, re.S)
        return int(m.group(1)) if m else -1

    def has_added_row(c):
        from PySide6.QtWidgets import QLabel
        return any((l.text() or "").startswith("➕") for l in c.findChildren(QLabel))

    def title_h():
        from PySide6.QtWidgets import QLabel
        lb = [l for l in w.findChildren(QLabel) if l.objectName() == "taskTitle"][0]
        return lb.fontMetrics().height()

    settings.set_density_mode("comfortable")
    w._apply_theme(); w._rebuild_task_list(); app.processEvents()
    th_n = title_h()
    top_n, gap_n = card_metrics(); px_n = title_px()
    added_n = has_added_row(next(iter(w._task_widgets.values())))
    settings.set_density_mode("compact")
    w._apply_theme(); w._rebuild_task_list(); app.processEvents()
    th_c = title_h()
    top_c, gap_c = card_metrics(); px_c = title_px()
    added_c = has_added_row(next(iter(w._task_widgets.values())))
    settings.set_density_mode("cozy")
    w._apply_theme(); w._rebuild_task_list(); app.processEvents()
    th_z = title_h()
    top_z, gap_z = card_metrics(); px_z = title_px()
    ck("normal = som förut (13 px, marginal 8)", px_n == 13 and top_n == 8 and gap_n == 3)
    ck("kompakt: mindre text och tätare kort", px_c < px_n and top_c < top_n and gap_c < gap_n)
    ck("stor: större text och luftigare kort", px_z > px_n and top_z > top_n and gap_z > gap_n)
    ck("uppgiftstitlarna följer textstorleken (kompakt < normal < stor)", th_c <= th_n < th_z)
    ck("normal: titel som förut (9 pt = 12 px, höjd 14)", th_n == 14)
    ck("normal visar 'Tillagd'-raden, kompakt döljer den", added_n and not added_c)
    ck("global textskala följer läget", abs(W._UI_FONT_SCALE - 1.2) < 0.001)
    ck("alla font-size skalas (inga 10px kvar i stor)", "font-size: 10px" not in w.styleSheet())
    settings.set_density_mode("comfortable")
    w._apply_theme(); w._rebuild_task_list(); app.processEvents()
    ck("tillbaka till normal ger samma som förut", title_px() == 13 and card_metrics() == (8, 3))
    ck("skalfunktionen lämnar 1.0 orörd", W._scale_font_sizes("a{font-size: 10px}", 1.0) == "a{font-size: 10px}")

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

    work = Path(tempfile.mkdtemp(prefix="taskbord_navtest_"))
    env, why = qt_env(work)
    if env is None:
        print(f"keynav_test: hoppas över ({why})")
        sys.exit(0)
    r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--child"], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=240)
    line = [l for l in r.stdout.splitlines() if l.startswith("CHILD ")]
    if line:
        _, a, b = line[-1].split()
        _ok += int(a)
        _fail += int(b)
        for l in r.stdout.splitlines():
            if l.strip().startswith("✗"):
                print(l)
    else:
        check("barnprocessen körde klart", False, (r.stdout + r.stderr)[-1500:])
    shutil.rmtree(work, ignore_errors=True)
    _tray = (ROOT / "app/mixins/tray.py").read_text(encoding="utf-8")
    check("tray-menyn har 'Textstorlek' med tre lägen",
          "🔠  Textstorlek" in _tray and all(f'"{m}"' in _tray for m in ("compact", "comfortable", "cozy")))
    check("tray-menyn kopplar valet till _set_ui_density", "_set_ui_density(d)" in _tray)
    print(f"\nkeynav_test: {_ok} lyckades, {_fail} misslyckades")
    sys.exit(1 if _fail else 0)
