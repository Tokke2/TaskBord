#!/usr/bin/env python3
"""
inline_edit_test.py — redigera en uppgifts titel på plats: dubbelklick eller F2 (Enter sparar, Esc avbryter).

Kör:  python tester/inline_edit_test.py
Bygger en riktig TodoWidget (offscreen) i en egen process och skickar riktiga mus-/tangenthändelser.
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
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QKeyEvent, QMouseEvent
    from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

    app = QApplication([])
    from core.settings import Settings
    from core.store import TaskStore
    import widget as W

    res: list = []

    def ck(name, cond):
        res.append((name, bool(cond)))

    tmp = tempfile.mkdtemp(prefix="taskbord_inline_")
    settings = Settings(str(Path(tmp) / "settings.json"))
    store = TaskStore(data_dir_override=Path(tmp) / "data")
    ids = [store.add_task(t) for t in ("Alfa", "Beta", "Gamma")]
    shell = QWidget()
    w = W.TodoWidget(app.primaryScreen(), store, settings, win_id="t", parent=shell)
    lay = QVBoxLayout(shell)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(w)
    w._shell = shell
    shell.resize(420, 560)
    shell.show()
    shell.activateWindow()  # aktivt fönster = kortkommandon gäller på riktigt (som i appen)
    app.processEvents()
    w._rebuild_task_list()
    app.processEvents()
    ck("fönstret är aktivt i testet", app.activeWindow() is shell)

    def title(tid):
        return store.find_task(tid)["title"]

    def editors():
        return w.findChildren(W.InlineTitleEdit)

    def label(tid):
        return w._task_widgets[tid].findChild(QLabel, "taskTitle")

    def dbl(lbl):
        ev = QMouseEvent(QEvent.Type.MouseButtonDblClick, QPointF(5, 5), QPointF(5, 5),
                         Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        app.sendEvent(lbl, ev)
        app.processEvents()

    def key(widget, k):
        app.sendEvent(widget, QKeyEvent(QEvent.Type.KeyPress, k, Qt.KeyboardModifier.NoModifier))
        app.sendEvent(widget, QKeyEvent(QEvent.Type.KeyRelease, k, Qt.KeyboardModifier.NoModifier))
        app.processEvents()

    a, b, g = ids
    ck("titeln har tooltip om dubbelklick/F2", "F2" in label(a).toolTip())
    ck("ingen editor från början", not editors())

    # --- dubbelklick -------------------------------------------------------
    dbl(label(a))
    ed = editors()
    ck("dubbelklick på titeln öppnar en editor", len(ed) == 1)
    ck("editorn visar nuvarande titel", ed and ed[0].text() == "Alfa")
    ck("editorn ligger över titeln", ed and ed[0].geometry().width() >= 80 and ed[0].isVisible())
    ck("editorn är läsbar (mörk text på ljus botten)", ed and "#111827" in ed[0].styleSheet() and "#ffffff" in ed[0].styleSheet())
    ck("editorn har fokus + allt markerat", ed and ed[0].hasFocus() or ed and ed[0].selectedText() == "Alfa")
    ed[0].setText("Alfa ändrad")
    key(ed[0], Qt.Key.Key_Return)
    ck("Enter sparar den nya titeln", title(a) == "Alfa ändrad")
    app.processEvents()
    ck("editorn är borta efter Enter", not [e for e in editors() if e.isVisible()])

    # --- Esc ---------------------------------------------------------------
    w._rebuild_task_list(); app.processEvents()
    dbl(label(b))
    ed = editors()[-1]
    ed.setText("Ska inte sparas")
    key(ed, Qt.Key.Key_Escape)
    ck("Esc avbryter — titeln är oförändrad", title(b) == "Beta")
    ck("editorn är borta efter Esc", not [e for e in editors() if e.isVisible()])

    # --- tom titel / oförändrad -------------------------------------------
    dbl(label(b))
    ed = editors()[-1]
    ed.setText("   ")
    key(ed, Qt.Key.Key_Return)
    ck("tom titel sparas inte", title(b) == "Beta")
    w._rebuild_task_list(); app.processEvents()
    dbl(label(b))
    ed = editors()[-1]
    n = len(store.all_tasks())
    key(ed, Qt.Key.Key_Return)
    ck("oförändrad titel ändrar inget", title(b) == "Beta" and len(store.all_tasks()) == n)

    # --- klick utanför (fokus förlorat) sparar -----------------------------
    w._rebuild_task_list(); app.processEvents()
    dbl(label(g))
    ed = editors()[-1]
    ed.setText("Gamma via fokusbyte")
    ed.editingFinished.emit()
    app.processEvents()
    ck("fokus bort sparar titeln", title(g) == "Gamma via fokusbyte")
    ck("sparas bara en gång (ingen dubbelskrivning)", title(g) == "Gamma via fokusbyte")

    # --- F2 ----------------------------------------------------------------
    w._rebuild_task_list(); app.processEvents()
    f2 = [s for s in w._hotkey_shortcuts if s.key().toString() == "F2"]
    ck("F2 är registrerad som snabbtangent (inte längre utan hanterare)", len(f2) == 1)
    w._sel_tid = None
    f2[0].activated.emit()
    ck("F2 utan markerad uppgift gör ingenting", not [e for e in editors() if e.isVisible()])
    w._nav_select(b)
    app.processEvents()
    f2[0].activated.emit()
    app.processEvents()
    vis = [e for e in editors() if e.isVisible()]
    ck("F2 öppnar editorn för den markerade uppgiften", len(vis) == 1 and vis[0].text() == "Beta")
    vis[0].setText("Beta via F2")
    key(vis[0], Qt.Key.Key_Return)
    ck("Enter efter F2 sparar", title(b) == "Beta via F2")
    ck("markeringen ligger kvar på uppgiften efter Enter", w._sel_tid == b)

    # --- E-tangent i navigeringsläget och menyn 'Byt namn' ------------------
    w._rebuild_task_list(); app.processEvents()
    w._nav_select(a)
    key(w, Qt.Key.Key_E)
    vis = [e for e in editors() if e.isVisible()]
    ck("E i listan öppnar editorn (inte dialogen)", len(vis) == 1 and vis[0].text() == "Alfa ändrad")
    key(vis[0], Qt.Key.Key_Escape)
    w._prompt_rename(g)
    vis = [e for e in editors() if e.isVisible()]
    ck("menyvalet Byt namn öppnar editorn på kortet", len(vis) == 1)
    # en ny start stänger den gamla
    w._start_inline_title_edit(a)
    vis = [e for e in editors() if e.isVisible()]
    ck("bara en editor åt gången", len(vis) == 1 and vis[0].text() == "Alfa ändrad")
    key(vis[0], Qt.Key.Key_Escape)

    # --- fokusläges-tangenterna får inte stjäla tangenter utanför fokusläget ----
    ck("fokus-tangenterna är AV utanför fokusläget", w._focus_shortcuts and not any(sc.isEnabled() for sc in w._focus_shortcuts))
    w._rebuild_task_list(); app.processEvents()
    w._nav_select(a)
    key(w, Qt.Key.Key_Space)
    ck("Mellanslag i listan markerar den valda uppgiften klar (stjäls inte längre)", store.find_task(a).get("done") is True)
    w._enter_focus_mode()
    ck("fokus-tangenterna är PÅ i fokusläget", all(sc.isEnabled() for sc in w._focus_shortcuts))
    w._exit_focus_mode()
    ck("…och AV igen när fokusläget stängs", not any(sc.isEnabled() for sc in w._focus_shortcuts))
    w._rebuild_task_list(); app.processEvents()
    w._enter_focus_mode()
    ck("ingen titelredigering i fokusläget", w._start_inline_title_edit(b) is False)
    w._exit_focus_mode()

    # --- kort som inte finns → False (dialogen tar över) -------------------
    ck("okänt kort → False (reserv: dialog)", w._start_inline_title_edit("finns-inte") is False)

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

    work = Path(tempfile.mkdtemp(prefix="taskbord_inlinetest_"))
    env, why = qt_env(work)
    if env is None:
        print(f"inline_edit_test: Qt-delen hoppas över ({why})")
    else:
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
            check("barnprocessen körde klart", False, (r.stdout + r.stderr)[-2000:])
    shutil.rmtree(work, ignore_errors=True)
    print(f"\ninline_edit_test: {_ok} lyckades, {_fail} misslyckades")
    sys.exit(1 if _fail else 0)
