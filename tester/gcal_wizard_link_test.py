#!/usr/bin/env python3
"""
gcal_wizard_link_test.py — "🌐 Öppna sidan hos Google" i guidade installationen ska öppna rätt adress.

Bugg som fångas: clicked(bool) skickade False till lambda u=url → adressen blev False och inget öppnades.
Kör:  python tester/gcal_wizard_link_test.py
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


def child() -> None:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import QCoreApplication, QEvent, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QPushButton

    app = QApplication([])
    import google_calendar_dialog as D
    import google_calendar as gcal

    res = []
    tmp = tempfile.mkdtemp(prefix="taskbord_gwiz_")
    opened: list = []
    D._open_url = lambda u: opened.append(u) or True  # fångar det knappen försöker öppna

    wiz = D.GoogleSetupWizard(tmp)
    wiz.show()
    for key, url in (("project", gcal.GOOGLE_CLOUD_PROJECT_URL), ("api", gcal.GOOGLE_CONSOLE_LIBRARY_URL),
                     ("consent", gcal.GOOGLE_CONSOLE_CONSENT_URL), ("credentials", gcal.GOOGLE_CONSOLE_CREDENTIALS_URL)):
        idx = next((i for i, s in enumerate(wiz._steg) if s["key"] == key), None)
        if idx is None or not wiz._steg[idx].get("url"):
            continue
        wiz.index = idx
        wiz._visa()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)  # gamla knappar (deleteLater)
        app.processEvents()
        btn = next((b for b in wiz.findChildren(QPushButton) if "Öppna sidan hos Google" in b.text()), None)
        res.append((f"steg {key}: knappen finns", btn is not None))
        if btn is None:
            continue
        opened.clear()
        QTest.mouseClick(btn, Qt.MouseButton.LeftButton)
        app.processEvents()
        res.append((f"steg {key}: öppnar rätt adress {opened} != {url}", opened == [url]))
    res.append(("minst ett steg med länk testades", len(res) >= 2))

    # riktiga _open_url avvisar icke-adresser (False/None/tom) i stället för att öppna något konstigt
    import importlib
    importlib.reload(D)
    called = []
    import webbrowser
    webbrowser.open = lambda u, *a, **k: called.append(u) or True
    ok_bad = [D._open_url(x) for x in (False, None, "", "javascript:alert(1)")]
    res.append(("ogiltiga adresser öppnas inte", ok_bad == [False] * 4 and not called))

    bad = [n for n, ok in res if not ok]
    print("CHILD", len(res) - len(bad), len(bad), flush=True)
    for n in bad:
        print("  ✗", n, flush=True)
    shutil.rmtree(tmp, ignore_errors=True)
    os._exit(0)


if "--child" in sys.argv:
    child()
else:
    from _qtenv import qt_env

    work = Path(tempfile.mkdtemp(prefix="taskbord_gwtest_"))
    env, why = qt_env(work)
    if env is None:
        print(f"gcal_wizard_link_test: hoppas över ({why})")
        sys.exit(0)
    r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--child"], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=120)
    line = [l for l in r.stdout.splitlines() if l.startswith("CHILD ")]
    a = b = 0
    if line:
        _, a, b = line[-1].split()
        a, b = int(a), int(b)
        for l in r.stdout.splitlines():
            if l.strip().startswith("✗"):
                print(l)
    else:
        b = 1
        print("  ✗ barnprocessen körde klart", (r.stdout + r.stderr)[-1500:])
    shutil.rmtree(work, ignore_errors=True)
    print(f"\ngcal_wizard_link_test: {a} lyckades, {b} misslyckades")
    sys.exit(1 if b else 0)
