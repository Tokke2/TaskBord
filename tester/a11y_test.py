#!/usr/bin/env python3
"""
a11y_test.py — tillgänglighet: textstorlek 80–200 %, fokusringar, namn för skärmläsare, tangentbordsstyrning.
Kör:  python tester/a11y_test.py
"""
from __future__ import annotations

import os
import re
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


def pure() -> None:
    from ui import a11y as A
    check("clean_label tar bort emoji", A.clean_label("📝  Ny anteckning") == "Ny anteckning" and A.clean_label("✓ Klar / oklar — klicka här") == "Klar / oklar — klicka här")
    check("clean_label: bara symbol → tomt", A.clean_label("⏰") == "" and A.clean_label("") == "" and A.clean_label(None) == "")
    check("zoom upp", A.next_zoom(100, 1) == 110 and A.next_zoom(150, 1) == 175 and A.next_zoom(200, 1) == 200)
    check("zoom ner", A.next_zoom(100, -1) == 90 and A.next_zoom(80, -1) == 80 and A.next_zoom(125, -1) == 110)
    check("zoom 0 = 100", A.next_zoom(175, 0) == 100)
    check("zoom från mellanvärde", A.next_zoom(120, 1) == 125 and A.next_zoom(120, -1) == 110)
    check("zoomsteg 80–200 i ordning", A.ZOOM_STEPS[0] == 80 and A.ZOOM_STEPS[-1] == 200 and A.ZOOM_STEPS == sorted(A.ZOOM_STEPS))
    d = A.describe_task({"title": "📞 Ring Anna", "priority": "high", "due_date": "2026-11-20T09:00", "tags": ["jobb", "bil"], "amount_cents": 150000})
    check("kortets mening", d.startswith("Uppgift: Ring Anna. Hög prioritet. Förfaller 2026-11-20 kl 09:00. Ej klar.") and "Taggar: jobb, bil" in d and "1500 kronor" in d, d)
    check("klar uppgift", "Klar." in A.describe_task({"title": "x", "done": True}) and "Klar." in A.describe_task({"title": "x"}, archived=True))
    check("titel saknas", "utan titel" in A.describe_task({"title": ""}))
    tok = {"fg": "#fff"}
    q = A.focus_qss(tok, True, "#818cf8")
    check("fokusring: gul på mörkt, 2 px", "#fde047" in q and "2px solid" in q and "QPushButton:focus" in q and "QLineEdit:focus" in q and "QTabBar::tab:focus" in q)
    check("fokusring: mörkblå på ljust", "#1d4ed8" in A.focus_qss(tok, False, "#4f46e5"))
    hc = A.focus_qss(tok, True, "#fff", True)
    check("fokusring i högkontrast: 3 px + markerat kort", "3px solid #ffeb3b" in hc and "taskSelected" in hc)
    # kontrast på ringen mot panelens färger
    def lum(h):
        v = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        v = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in v]
        return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]
    def cr(a, b):
        hi, lo = max(lum(a), lum(b)), min(lum(a), lum(b))
        return (hi + 0.05) / (lo + 0.05)
    check("ringen syns mot mörk panel (≥ 3:1)", cr("#fde047", "#202448") >= 3.0 and cr("#ffeb3b", "#000000") >= 3.0)
    check("ringen syns mot ljus panel (≥ 3:1)", cr("#1d4ed8", "#fafbff") >= 3.0 and cr("#0000a0", "#ffffff") >= 3.0)
    doc = (ROOT / "docs/MANUAL.md").read_text(encoding="utf-8")
    check("MANUAL beskriver tillgänglighet", "Tillgänglighet" in doc and "200 %" in doc and "Skärmläsare" in doc)
    from core import shortcut_help as SH
    txt = SH.as_text(SH.build_sections(None, "linux"))
    check("F1-översikten nämner zoom, flikar och menytangent", "Ctrl + Plus" in txt and "Ctrl + 1 / 2 / 3 / 4" in txt and "Skift+F10" in txt)


def child() -> None:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QAbstractButton, QApplication, QLineEdit, QVBoxLayout, QWidget
    app = QApplication([])
    import widget as W
    from core.settings import Settings
    from core.store import TaskStore

    res: list = []

    def ck(name, cond, extra=""):
        res.append((name + (f" {extra}" if not cond and extra else ""), bool(cond)))

    tmp = tempfile.mkdtemp(prefix="ledgebord_a11y_")
    settings = Settings(str(Path(tmp) / "s.json"))
    store = TaskStore(data_dir_override=Path(tmp) / "d")
    t1 = store.add_task("Ring Anna", priority="high", due_date="2026-11-20", tags=["jobb"])
    store.add_task("Faktura 2")
    shell = QWidget()
    w = W.TodoWidget(app.primaryScreen(), store, settings, win_id="a", parent=shell)
    lay = QVBoxLayout(shell)
    lay.addWidget(w)
    w._shell = shell
    shell.resize(520, 640)
    shell.show()
    app.processEvents()
    w._rebuild_task_list()
    app.processEvents()

    def sizes():
        return [int(x) for x in re.findall(r"font-size:\s*(\d+)px", w.styleSheet())]
    s100 = sizes()
    w._set_text_scale(200)
    s200 = sizes()
    ck("200 %: texten är i snitt nära dubbelt så stor", sum(s200) / len(s200) >= 1.8 * sum(s100) / len(s100), (sum(s100) / len(s100), sum(s200) / len(s200)))
    ck("200 %: sparat", settings.pref("text_scale") == 200)
    ck("200 %: minsta text ≥ 20 px", min(s200) >= 20, min(s200))
    w._set_text_scale(80)
    s80 = sizes()
    ck("80 %: minsta text fortfarande ≥ 10 px", min(s80) >= 10, min(s80))
    w._set_text_scale(100)
    ck("100 %: som förut", sizes() == s100)
    # Ctrl+Plus/Minus/0
    w._zoom_text(1)
    ck("Ctrl+Plus: 110 %", settings.pref("text_scale") == 110)
    w._zoom_text(-1)
    w._zoom_text(-1)
    ck("Ctrl+Minus x2: 90 %", settings.pref("text_scale") == 90)
    w._zoom_text(0)
    ck("Ctrl+0: 100 %", settings.pref("text_scale") == 100)
    for _ in range(12):
        w._zoom_text(1)
    ck("tak 200 %", settings.pref("text_scale") == 200)
    w._set_text_scale(100)
    # korten byggs om vid ändrad storlek (cache-nyckel)
    old = w._task_widgets.get(t1)
    w._set_text_scale(150)
    w._rebuild_task_list()
    ck("kortet byggs om när textstorleken ändras", w._task_widgets.get(t1) is not old)
    w._set_text_scale(100)
    # fokusringar i stilen
    ck("fokusring i fönstrets stil", "QPushButton:focus" in w.styleSheet() and "#fde047" in w.styleSheet() or "#1d4ed8" in w.styleSheet())
    settings.set_pref("high_contrast", True)
    w._apply_theme()
    ck("högkontrast: kraftigare ring (3 px)", "3px solid" in w.styleSheet())
    settings.set_pref("high_contrast", False)
    w._apply_theme()
    # namn
    unnamed = []
    for b in w.findChildren(QAbstractButton):
        if not b.accessibleName() and (b.text() or b.toolTip()):
            unnamed.append(b.text() or b.toolTip())
    ck("alla knappar med text/tips har tillgängligt namn", not unnamed, unnamed[:5])
    ck("knapparna i titelraden har namn", w.close_btn.accessibleName() and w.min_btn.accessibleName())
    ck("inmatningsfältet har namn", w.input_field.accessibleName() != "", w.input_field.placeholderText())
    ck("sökfältet har namn", w.search_input.accessibleName() != "")
    card = w._task_widgets[t1]
    nm = card.accessibleName()
    ck("kortet läses som en mening", nm.startswith("Uppgift: Ring Anna. Hög prioritet.") and "Förfaller 2026-11-20" in nm, nm)
    boxes = card.findChildren(QAbstractButton)
    ck("kortets knappar och kryssruta har namn", boxes and all(b.accessibleName() for b in boxes), [b.text() for b in boxes if not b.accessibleName()])
    # tangentbordsfokus
    for nm_, b in (("close", w.close_btn), ("min", w.min_btn), ("update", w.update_btn)):
        ck(f"{nm_}-knappen nås med Tab", b.focusPolicy() == Qt.FocusPolicy.TabFocus)
    ck("inmatningsfältet tar fokus", w.input_field.focusPolicy() in (Qt.FocusPolicy.StrongFocus, Qt.FocusPolicy.ClickFocus, Qt.FocusPolicy.WheelFocus))
    # genvägar
    from PySide6.QtGui import QKeySequence
    seqs = {sc.key().toString() for sc in getattr(w, "_a11y_shortcuts", [])}
    ck("Ctrl+Plus, Ctrl+Minus, Ctrl+0 och Ctrl+1–4 finns", {"Ctrl++", "Ctrl+=", "Ctrl+-", "Ctrl+0", "Ctrl+1", "Ctrl+2", "Ctrl+3", "Ctrl+4"} <= seqs, seqs)
    w._goto_tab(2)
    ck("Ctrl+3 → Kalender", w.tabs.currentIndex() == 2)
    w._goto_tab(0)
    ck("Ctrl+1 → Aktiva", w.tabs.currentIndex() == 0)
    # Meny-tangenten på markerad uppgift
    opened = []
    w._show_task_menu = lambda task: opened.append(task.get("id"))
    w._sel_tid = t1
    w._nav_active = True
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent
    ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Menu, Qt.KeyboardModifier.NoModifier)
    handled = w._handle_nav_key(ev)
    ck("Meny-tangenten öppnar uppgiftsmenyn", handled and opened == [t1], opened)
    opened.clear()
    ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_F10, Qt.KeyboardModifier.ShiftModifier)
    ck("Skift+F10 öppnar uppgiftsmenyn", w._handle_nav_key(ev) and opened == [t1])
    shutil.rmtree(tmp, ignore_errors=True)
    bad = [n for n, ok in res if not ok]
    print("CHILD", len(res) - len(bad), len(bad))
    for n in bad:
        print("  ✗", n)
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
    _run_parent("a11y_test")
    print(f"\na11y_test: {_ok} lyckades, {_fail} misslyckades")
    sys.exit(1 if _fail else 0)
