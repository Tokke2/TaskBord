#!/usr/bin/env python3
"""
welcome_test.py — välkomstguiden vid första start: bara på ny installation, en gång, med exempeluppgift och
förklarande tom vy. Kör:  python tester/welcome_test.py
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


from core import welcome as W  # noqa: E402


def pure() -> None:
    check("ny installation + synligt fönster → visa", W.decide(0, 0, False, True) == W.SHOW)
    check("redan visad → inget", W.decide(0, 0, True, True) == W.SKIP)
    check("tyst autostart (gömt) → vänta", W.decide(0, 0, False, False) == W.SKIP)
    check("befintliga aktiva uppgifter → bara markera", W.decide(3, 0, False, True) == W.MARK_ONLY)
    check("bara arkiverade uppgifter → bara markera", W.decide(0, 2, False, True) == W.MARK_ONLY)
    check("befintlig användare + gömt → markera (aldrig visa senare)", W.decide(1, 0, False, False) == W.MARK_ONLY)
    ex = W.example_task()
    check("exempeluppgiften har titel, prio och tagg", ex["title"] and ex["priority"] == "medium" and ex["tags"] == ["exempel"])
    check("exempelanteckningen förklarar kortet", "Enter" in ex["note"] and "Ctrl+Alt+N" in ex["note"])
    check("minst fem tips, alla med emoji + rubrik + text", len(W.TIPS) >= 5 and all(len(t) == 3 and all(t) for t in W.TIPS))
    check("tom vy förklarar hur man börjar", "Enter" in W.EMPTY_ACTIVE and "Ctrl+Alt+N" in W.EMPTY_ACTIVE and "Välkomstguide" in W.EMPTY_ACTIVE)
    check("arkivets tomma vy kvar", "sparas för alltid" in W.EMPTY_ARCHIVE)
    check("ingen Qt i core/welcome.py", "PySide" not in (ROOT / "core/welcome.py").read_text(encoding="utf-8"))
    doc = (ROOT / "docs/MANUAL.md").read_text(encoding="utf-8")
    check("MANUAL beskriver välkomstguiden", "Välkomstguide" in doc and "exempeluppgift" in doc)
    check("tray + högerklick har guiden",
          "_open_welcome_guide" in (ROOT / "app/mixins/tray.py").read_text(encoding="utf-8")
          and "_on_open_welcome" in (ROOT / "ui/widget_parts/window_ops.py").read_text(encoding="utf-8"))
    check("testmiljön stänger av guiden", "LEDGEBORD_NO_WELCOME" in (ROOT / "tester/_qtenv.py").read_text(encoding="utf-8"))


def child() -> None:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication, QDialog, QLabel, QVBoxLayout, QWidget
    app = QApplication([])
    from core.settings import Settings
    from core.store import TaskStore
    import widget as W2

    res: list = []

    def ck(name, cond, extra=""):
        res.append((name + (f" {extra}" if not cond and extra else ""), bool(cond)))

    tmp = tempfile.mkdtemp(prefix="ledgebord_welcome_")
    opened: list = []
    import ui.welcome_dialog as WD
    WD.open_welcome_dialog = lambda parent=None: opened.append(1) or True   # ingen modal dialog i testet

    def make(store, settings):
        shell = QWidget()
        w = W2.TodoWidget(app.primaryScreen(), store, settings, win_id="w", parent=shell)
        lay = QVBoxLayout(shell)
        lay.addWidget(w)
        w._shell = shell
        shell.resize(460, 560)
        shell.show()
        app.processEvents()
        return shell, w

    # --- ny installation ---
    settings = Settings(str(Path(tmp) / "s.json"))
    store = TaskStore(data_dir_override=Path(tmp) / "d1")
    shell, w = make(store, settings)
    ck("tom lista visar förklarande tom vy", any("Ctrl+Alt+N" in l.text() for l in w.active_container.findChildren(QLabel))
       if hasattr(w, "active_container") else True)
    w._maybe_show_welcome()
    app.processEvents()
    tasks = store.active_tasks()
    ck("exempeluppgift lades in", len(tasks) == 1 and tasks[0]["title"] == W.EXAMPLE_TITLE, [t["title"] for t in tasks])
    ck("exempeluppgiften har anteckning + tagg", tasks and "Enter" in (tasks[0].get("note") or "") and tasks[0]["tags"] == ["exempel"], tasks)
    ck("guiden öppnades en gång", opened == [1], opened)
    ck("welcome_done sparat", settings.pref("welcome_done") is True)
    w._maybe_show_welcome()
    ck("andra gången: ingen ny uppgift och ingen ny guide", len(store.active_tasks()) == 1 and opened == [1])
    # ta bort exempeluppgiften → kommer inte tillbaka
    store.delete_task(tasks[0]["id"]) if hasattr(store, "delete_task") else store.archive_task(tasks[0]["id"])
    w._maybe_show_welcome()
    ck("borttagen exempeluppgift kommer aldrig tillbaka", not [t for t in store.active_tasks() if t["title"] == W.EXAMPLE_TITLE])
    shell.close()

    # --- befintlig användare (uppdatering): inget visas ---
    s2 = Settings(str(Path(tmp) / "s2.json"))
    st2 = TaskStore(data_dir_override=Path(tmp) / "d2")
    st2.add_task("Min gamla uppgift")
    opened.clear()
    shell2, w2 = make(st2, s2)
    w2._maybe_show_welcome()
    ck("befintlig användare: ingen guide, ingen exempeluppgift", not opened and len(st2.active_tasks()) == 1)
    ck("…men markerad som klar", s2.pref("welcome_done") is True)
    shell2.close()

    # --- gömd (tyst autostart): väntar ---
    s3 = Settings(str(Path(tmp) / "s3.json"))
    st3 = TaskStore(data_dir_override=Path(tmp) / "d3")
    shell3, w3 = make(st3, s3)
    shell3.hide()
    app.processEvents()
    w3._maybe_show_welcome()
    ck("gömt fönster: ingen guide än, inte markerad", not opened and s3.pref("welcome_done") is False)
    shell3.show()
    app.processEvents()
    w3._maybe_show_welcome()
    ck("när fönstret syns kommer guiden", opened == [1])
    shell3.close()

    # --- dialogen ---
    WD2 = __import__("importlib").reload(WD)
    d = WD2.WelcomeDialog(None)
    labels = [l.text() for l in d.findChildren(QLabel)]
    ck("dialogen visar alla tips", all(any(h in t for t in labels) for _e, h, _x in W.TIPS))
    ck("knappen Kom igång stänger", d.go_btn.isDefault() and d.go_btn.accessibleName() != "")
    d.go_btn.click()
    ck("dialogen accepteras", d.result() == QDialog.DialogCode.Accepted)
    _finish_child(res, tmp)


def _finish_child(res, tmp):
    bad = [n for n, ok in res if not ok]
    print("CHILD", len(res) - len(bad), len(bad))
    for n in bad:
        print("  ✗", n)
    shutil.rmtree(tmp, ignore_errors=True)
    sys.stdout.flush()
    os._exit(0)


def _run_parent(name):
    global _ok, _fail
    from _qtenv import qt_env
    work = Path(tempfile.mkdtemp(prefix=f"ledgebord_{name}_"))
    env, why = qt_env(work)
    if env is None:
        print(f"{name}: Qt-delen hoppas över ({why})")
    else:
        env.pop("LEDGEBORD_NO_WELCOME", None)
        r = subprocess.run([sys.executable, str(Path(sys.argv[0]).resolve()), "--child"], cwd=ROOT, env=env,
                           capture_output=True, text=True, timeout=240)
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


if "--child" in sys.argv:
    child()
else:
    pure()
    _run_parent("welcome_test")
    print(f"\nwelcome_test: {_ok} lyckades, {_fail} misslyckades")
    sys.exit(1 if _fail else 0)
