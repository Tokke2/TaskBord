#!/usr/bin/env python3
"""
context_top_test.py — högerklicksmenyn i fönstret har "📌 Alltid överst" (bockruta).

Kör:  python tester/context_top_test.py
Bygger en riktig TodoWidget (offscreen) i en egen process; menyns exec() ersätts så att den väljer ett val.
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

from _src import app_source  # noqa: E402

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
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QApplication, QMenu, QVBoxLayout, QWidget

    app = QApplication([])
    from core.settings import Settings
    from core.store import TaskStore
    import widget as W

    res: list = []

    def ck(name, cond):
        res.append((name, bool(cond)))

    tmp = tempfile.mkdtemp(prefix="taskbord_ctxtop_")
    settings = Settings(str(Path(tmp) / "settings.json"))
    store = TaskStore(data_dir_override=Path(tmp) / "data")
    shell = QWidget()
    w = W.TodoWidget(app.primaryScreen(), store, settings, win_id="t", parent=shell)
    lay = QVBoxLayout(shell)
    lay.addWidget(w)
    w._shell = shell
    shell.resize(420, 520)
    shell.show()
    app.processEvents()

    seen: dict = {}
    pick = {"text": None}

    class FakeMenu(QMenu):
        def exec(self, pos=None):  # noqa: A003
            seen["acts"] = [(a.text(), a.isCheckable(), a.isChecked(), a.toolTip()) for a in self.actions() if a.text()]
            for a in self.actions():
                if pick["text"] and a.text().startswith(pick["text"]):
                    return a
            return None

    sys.modules["ui.widget_parts.window_ops"].QMenu = FakeMenu

    class Ev:
        def globalPos(self):
            return QPoint(5, 5)

    emitted: list = []
    w.top_toggle_requested.connect(lambda: emitted.append(1))

    settings.set_desktop_mode("behind")
    w.contextMenuEvent(Ev())
    top = [a for a in seen["acts"] if a[0].startswith("📌 Alltid överst")]
    ck("menyn har valet '📌 Alltid överst'", len(top) == 1)
    ck("valet är en bockruta", top and top[0][1])
    ck("inte bockad i läget 'behind'", top and top[0][2] is False)
    ck("har förklarande tooltip", top and "över alla andra appar" in top[0][3])
    ck("ingen signal när inget väljs", not emitted)
    ck("valet ligger bland de andra (lås, PDF, backup finns kvar)",
       all(any(t[0].startswith(p) for t in seen["acts"]) for p in ("🔒", "📄", "💾", "🎯")))

    pick["text"] = "📌 Alltid överst"
    w.contextMenuEvent(Ev())
    ck("att välja valet skickar top_toggle_requested", emitted == [1])

    settings.set_desktop_mode("top")
    pick["text"] = None
    w.contextMenuEvent(Ev())
    top = [a for a in seen["acts"] if a[0].startswith("📌 Alltid överst")]
    ck("bockad i läget 'top'", top and top[0][2] is True)
    ck("_is_always_on_top följer inställningen", w._is_always_on_top() is True)
    settings.set_desktop_mode("above")
    ck("…och 'above' räknas inte som överst", w._is_always_on_top() is False)

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

    work = Path(tempfile.mkdtemp(prefix="taskbord_ctxtoptest_"))
    env, why = qt_env(work)
    if env is None:
        print(f"context_top_test: Qt-delen hoppas över ({why})")
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
            check("barnprocessen körde klart", False, (r.stdout + r.stderr)[-1800:])
    shutil.rmtree(work, ignore_errors=True)
    src = app_source(ROOT)
    check("appen kopplar menyvalet till _toggle_always_on_top",
          "top_toggle_requested.connect(self._toggle_always_on_top)" in src)
    check("signalen finns i TodoWidget", "top_toggle_requested = Signal()" in (ROOT / "ui" / "widget.py").read_text(encoding="utf-8"))
    print(f"\ncontext_top_test: {_ok} lyckades, {_fail} misslyckades")
    sys.exit(1 if _fail else 0)
