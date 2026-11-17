#!/usr/bin/env python3
"""
dialog_front_test.py — dialoger ska alltid ligga överst tills man är klar (app/dialog_front.py).
Windows-anropet (SetWindowPos) är utbytbart och kan inte provas på Linux; här testas logiken runt det.
Kör:  python tester/dialog_front_test.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
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
    from PySide6.QtWidgets import QApplication, QDialog, QMenu, QMessageBox, QWidget
    app = QApplication([])
    from app import dialog_front as DF
    res = []

    def ck(n, c, e=""):
        res.append((n + (f" {e}" if not c and e else ""), bool(c)))

    calls = []
    f = DF.install(app, native=lambda h: (calls.append(h), True)[1])
    ck("filtret installeras", f is not None)

    def spin(ms=350):
        t0 = time.time()
        while time.time() - t0 < ms / 1000.0:
            app.processEvents()
            time.sleep(0.01)

    d = QDialog()
    d.resize(200, 100)
    d.show()
    spin()
    ck("dialog som visas läggs överst (flera gånger: direkt, 0 ms, 250 ms)", len(calls) >= 3 and set(calls) == {int(d.winId())}, calls)
    ck("dialogen följs medan den är öppen", d in f.visible_dialogs())

    calls.clear()
    n = f.restack()
    ck("restack lägger öppna dialoger överst igen", n == 1 and calls == [int(d.winId())], (n, calls))

    d.hide()
    app.processEvents()
    calls.clear()
    ck("stängd dialog följs inte längre", f.visible_dialogs() == [] and f.restack() == 0 and not calls)

    # QMessageBox är också en dialog
    calls.clear()
    box = QMessageBox()
    box.setText("hej")
    box.show()
    spin()
    ck("QMessageBox läggs överst", int(box.winId()) in calls)
    box.close()
    app.processEvents()

    # vanligt fönster, meny och dialog som barn rörs inte
    calls.clear()
    w = QWidget()
    w.show()
    m = QMenu()
    m.addAction("x")
    m.popup(w.pos())
    host = QWidget()
    child_dlg = QDialog(host)    # barn-dialog utan eget fönster? (QDialog med förälder är ändå ett fönster)
    spin()
    ck("vanligt fönster och meny läggs inte överst", int(w.winId()) not in calls and int(m.winId()) not in calls, calls)
    m.close()
    w.close()

    # dialog med ägare är också ett fönster och läggs överst
    calls.clear()
    owner = QWidget()
    owner.show()
    od = QDialog(owner)
    od.show()
    spin()
    ck("dialog med ägare läggs överst", int(od.winId()) in calls)
    od.close()
    owner.close()

    # en dialog som tas bort medan den följs ger inget fel
    d2 = QDialog()
    d2.show()
    spin(50)
    d2.deleteLater()
    app.processEvents()
    spin(50)
    try:
        f.restack()
        ok = True
    except Exception:
        ok = False
    ck("raderad dialog kraschar inte restack", ok)

    # native utanför Windows: gör inget och kastar inte
    ck("native_topmost utan fönster/Windows ger False", DF.native_topmost(0) is False and (sys.platform == "win32" or DF.native_topmost(123) is False))

    # nätverks- och Windows-delen kan inte köras här — kontrollera källkoden
    src = (ROOT / "app/dialog_front.py").read_text(encoding="utf-8")
    ck("Windows: HWND_TOPMOST (-1) utan NOACTIVATE", "SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0040)" in src)
    ds = (ROOT / "app/mixins/desktop_shell.py").read_text(encoding="utf-8")
    ck("huvudfönstrets omläggning lägger dialogerna överst igen", "_df.restack()" in ds)
    ctl = (ROOT / "app/controller.py").read_text(encoding="utf-8")
    ck("controller installerar filtret", "_df.install(self._app)" in ctl)
    bad = [n for n, ok in res if not ok]
    print("CHILD", len(res) - len(bad), len(bad))
    for n in bad:
        print("  ✗", n)
    sys.stdout.flush()
    os._exit(0)


if "--child" in sys.argv:
    child()
else:
    from _qtenv import qt_env
    work = Path(tempfile.mkdtemp(prefix="ledgebord_dfront_"))
    env, why = qt_env(work)
    if env is None:
        print(f"Qt-delen hoppas över ({why})")
    else:
        r = subprocess.run([sys.executable, str(Path(sys.argv[0]).resolve()), "--child"], cwd=ROOT, env=env,
                           capture_output=True, text=True, timeout=200)
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
    print(f"\ndialog_front_test: {_ok} lyckades, {_fail} misslyckades")
    sys.exit(1 if _fail else 0)
