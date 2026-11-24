#!/usr/bin/env python3
"""
update_button_test.py — uppdateringsknappen i fönstrets titelrad (⟳ → ⬆ Uppdatera → ⏳ Installerar → ✓ Aktuell).

Kör:  python tester/update_button_test.py
Bygger en riktig TodoWidget (offscreen). Flödet bakom knappen (sök/installera direkt) testas i updater_flow_test.py.
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


def lum(hex_):
    c = [int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def child() -> None:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

    app = QApplication([])
    from core.settings import Settings
    from core.store import TaskStore
    import widget as W

    res: list = []

    def ck(name, cond, extra=None):
        res.append((name + (f"  {extra}" if not cond and extra is not None else ""), bool(cond)))

    tmp = tempfile.mkdtemp(prefix="taskbord_updbtn_")
    settings = Settings(str(Path(tmp) / "settings.json"))
    store = TaskStore(data_dir_override=Path(tmp) / "data")
    store.add_task("Alfa")
    shell = QWidget()
    w = W.TodoWidget(app.primaryScreen(), store, settings, win_id="t", parent=shell)
    lay = QVBoxLayout(shell)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(w)
    w._shell = shell
    shell.resize(420, 560)
    shell.show()
    app.processEvents()

    b = w.update_btn
    ck("knappen finns i titelraden", b is not None and b.isVisible())
    ck("vilande: ⟳ 34x28 med tooltip", b.text() == "⟳" and (b.width(), b.height()) == (34, 28) and "Sök ny version" in b.toolTip())
    hdr = w.layout().itemAt(0).layout()
    names = [hdr.itemAt(i).widget() for i in range(hdr.count())]
    ck("ordning: statistik → uppdatering → lås → – → ✕", names.index(b) == names.index(w.stats_chip) + 1 and names.index(w.lock_btn) == names.index(b) + 1, [type(n).__name__ for n in names])

    clicks = []
    w.update_requested.connect(lambda: clicks.append(1))
    b.click()
    ck("klick skickar update_requested", clicks == [1])

    bar = w.update_bar
    ck("uppdateringsraden är dold från början", not bar.isVisible())
    w.set_update_state("checking", "Kontaktar GitHub…")
    app.processEvents()
    ck("söker: ⏳, avstängd, tooltip", b.text() == "⏳" and not b.isEnabled() and b.toolTip() == "Kontaktar GitHub…")
    ck("söker: ingen uppdateringsrad", not bar.isVisible())
    b.click()
    ck("söker: klick ignoreras", clicks == [1])

    w.set_update_state("available", "Ny version finns: 3 fil(er)", 3)
    app.processEvents()
    ck("ny version: ikonen ⬆, aktiv, grön", b.text() == "⬆" and b.isEnabled() and "#15803d" in b.styleSheet() and (b.width(), b.height()) == (34, 28), (b.text(), b.width()))
    ck("ny version: raden 'Ny version finns (3 filer)' syns", bar.isVisible() and "Ny version finns (3 filer)" in w.update_label.text(), w.update_label.text())
    ck("ny version: knappen 'Uppdatera nu' syns och är aktiv", w.update_now_btn.isVisible() and w.update_now_btn.isEnabled() and w.update_now_btn.text() == "Uppdatera nu")
    ck("ny version: raden ligger under titelraden (och efter röd-dag-rutan)", w.layout().indexOf(bar) == w.layout().indexOf(w.holiday_banner) + 1 and w.layout().indexOf(bar) > 1)
    ck("ny version: raden är bred som fönstret", bar.width() >= w.width() - 40, (bar.width(), w.width()))
    ck("ny version: kontrast vit på #14532d ≥ 4,5 och mörkgrön på vit ≥ 4,5", contrast("#ffffff", "#14532d") >= 4.5 and contrast("#14532d", "#ffffff") >= 4.5)
    ck("ny version: ikon vit på #15803d ≥ 4,5", contrast("#ffffff", "#15803d") >= 4.5)
    ck("ny version: tillgängliga namn", b.accessibleName().startswith("Ny version finns") and "nu" in w.update_now_btn.accessibleName())
    b.click()
    ck("ny version: klick på ikonen skickar signalen", clicks == [1, 1])
    w.update_now_btn.click()
    ck("ny version: klick på 'Uppdatera nu' skickar signalen", clicks == [1, 1, 1])
    w.set_update_state("available", "x", 1)
    ck("en fil → singular", "(1 fil)" in w.update_label.text(), w.update_label.text())
    shell.resize(340, 560)
    app.processEvents()
    ck("smalt fönster: raden och knappen ryms", bar.geometry().right() <= w.width() and w.update_now_btn.geometry().right() <= bar.width() and w.close_btn.geometry().right() <= w.width(),
       (bar.geometry().right(), w.update_now_btn.geometry().right(), bar.width(), w.width()))
    shell.resize(420, 560)

    w.set_update_state("installing", "Installerar…")
    app.processEvents()
    ck("installerar: ⏳, avstängd", b.text() == "⏳" and not b.isEnabled())
    ck("installerar: raden säger att appen startar om, utan knapp", bar.isVisible() and "Installerar" in w.update_label.text() and not w.update_now_btn.isVisible())
    ck("installerar: vit text på #92400e ≥ 4,5", contrast("#ffffff", "#92400e") >= 4.5 and contrast("#ffffff", "#b45309") >= 4.5)

    w.set_update_state("current", "Du har senaste versionen")
    app.processEvents()
    ck("aktuell: ✓, aktiv, ingen rad", b.text() == "✓" and b.isEnabled() and not bar.isVisible())
    w.set_update_state("idle", "Sök ny version")
    app.processEvents()
    ck("tillbaka till ⟳ 34x28 utan särskild stil", b.text() == "⟳" and (b.width(), b.height()) == (34, 28) and b.styleSheet() == "" and not bar.isVisible())
    w.set_update_state("nonsens")
    ck("okänt läge → idle", b.text() == "⟳")

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

    work = Path(tempfile.mkdtemp(prefix="taskbord_updbtntest_"))
    env, why = qt_env(work)
    if env is None:
        print(f"update_button_test: Qt-delen hoppas över ({why})")
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
    print(f"\nupdate_button_test: {_ok} lyckades, {_fail} misslyckades")
    sys.exit(1 if _fail else 0)
