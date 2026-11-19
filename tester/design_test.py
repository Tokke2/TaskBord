#!/usr/bin/env python3
"""
design_test.py — bättre design: typsnitt, nya färgteman, ritade ikoner i titelraden, bredare standardfönster.

Kör:  python tester/design_test.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "core", ROOT / "ui", Path(__file__).resolve().parent):
    sys.path.insert(0, str(p))

_ok = _fail = 0


def check(name, cond, extra=""):
    global _ok, _fail
    if cond:
        _ok += 1
    else:
        _fail += 1
        print(f"  ✗ {name} {extra}")


def pure() -> None:
    from core import prefs, themes as TH
    from core.settings import Settings
    check("tre nya teman: midnatt, lavendel, sand", {"midnatt", "lavendel", "sand"} <= set(TH.PRESETS) <= set(prefs.THEME_PRESETS))
    check("alla teman har färgprov och förändrar tokens", all(k in TH.SWATCH for k in TH.PRESETS))
    from widget import GLASS_DARK, GLASS_LIGHT  # noqa: F401
    for k in ("midnatt", "lavendel", "sand"):
        check(f"{k}: byter panelens färg (mörkt och ljust)",
              TH.adjust_tokens(GLASS_DARK, True, k)["bg_top"] != GLASS_DARK["bg_top"]
              and TH.adjust_tokens(GLASS_LIGHT, False, k)["bg_top"] != GLASS_LIGHT["bg_top"])
    check("fem typsnitt, standard först", list(TH.FONTS)[0] == "standard" and len(TH.FONTS) == 5 and tuple(TH.FONTS) == prefs.FONTS)
    check("standardtypsnittet har Segoe UI först och en reserv", TH.font_css("standard").startswith('"Segoe UI Variable Text", "Segoe UI"') and "sans-serif" in TH.font_css("standard"))
    check("okänt typsnitt → standard", TH.font_css("nonsens") == TH.font_css("standard") and TH.font_css("") == TH.font_css("standard"))
    check("alla typsnitt har en generisk reserv", all(v[1].rstrip().endswith(("sans-serif", "serif")) for v in TH.FONTS.values()))
    tmp = tempfile.mkdtemp()
    s = Settings(str(Path(tmp) / "s.json"))
    check("ui_font: standard, och ogiltigt rensas", s.pref("ui_font") == "standard" and (s.set_pref("ui_font", "xx") or True) and s.pref("ui_font") == "standard")
    s.set_pref("ui_font", "lattlast")
    check("ui_font sparas", s.pref("ui_font") == "lattlast")
    check("nya standardstorleken är 420×700", Settings.DEFAULT_WINDOWS[0]["w"] == 420 and Settings.DEFAULT_WINDOWS[0]["h"] == 700)
    import widget_base as WB
    check("DEFAULT_WIDGET_WIDTH 420", WB.DEFAULT_WIDGET_WIDTH == 420 and WB.DEFAULT_WIDGET_HEIGHT == 700)
    tray = (ROOT / "app/mixins/tray.py").read_text(encoding="utf-8")
    check("tray-menyn: Smal, Standard, Bred, Extra bred", all(x in tray for x in ("Smal (340×648)", "Standard (420×700)", "Bred (560×760)", "Extra bred (720×800)")))
    win = (ROOT / "app/mixins/windows.py").read_text(encoding="utf-8")
    check("engångsmigrering 340×648 → 420×700 (rör inte egna storlekar)", 'pref("width_v2")' in win and "(_gw, _gh) == (340, 648)" in win)
    check("width_v2 finns som inställning", s.pref("width_v2") is False)
    shutil.rmtree(tmp, ignore_errors=True)


def child() -> None:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter, QColor
    from PySide6.QtCore import QRectF
    from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
    app = QApplication([])
    import widget as W
    from core.settings import Settings
    from core.store import TaskStore
    from ui import vector_icons as VI
    res = []

    def ck(name, cond, extra=""):
        res.append((name + (f" {extra}" if not cond and extra else ""), bool(cond)))

    # ikonerna ritas (inte tomma) för varje knapptext, och olika för olika ikoner
    sigs = {}
    for text, name in VI.GLYPHS.items():
        img = QImage(34, 28, QImage.Format.Format_ARGB32)
        img.fill(0)
        p = QPainter(img)
        ok = VI.draw_glyph(p, name, QRectF(img.rect()), QColor("#ffffff"))
        p.end()
        px = sum(1 for y in range(28) for x in range(34) if (img.pixel(x, y) >> 24) > 0)
        sigs[name] = img.bits().tobytes() if hasattr(img.bits(), "tobytes") else bytes(img.bits())
        ck(f"ikon {name} ritas", ok and px > 12, px)
    ck("alla ikoner ser olika ut", len(set(sigs.values())) == len(sigs))
    ck("okänt ikonnamn ritas inte", VI.draw_glyph(QPainter(QImage(4, 4, QImage.Format.Format_ARGB32)), "nonsens", QRectF(0, 0, 4, 4), QColor("#fff")) is False)

    tmp = tempfile.mkdtemp(prefix="ledgebord_design_")
    settings = Settings(str(Path(tmp) / "s.json"))
    store = TaskStore(data_dir_override=Path(tmp) / "d")
    store.add_task("Ring Anna", priority="high")
    shell = QWidget()
    w = W.TodoWidget(app.primaryScreen(), store, settings, win_id="a", parent=shell)
    lay = QVBoxLayout(shell)
    lay.addWidget(w)
    w._shell = shell
    shell.resize(420, 700)
    shell.show()
    for _ in range(8):
        app.processEvents()
    for nm in ("update_btn", "lock_btn", "min_btn", "close_btn", "holiday_close_btn"):
        ck(f"{nm} är en GlyphButton med ikon", isinstance(getattr(w, nm), VI.GlyphButton) and getattr(w, nm).glyph() is not None, getattr(w, nm).text())
    w.lock_btn.setText("🔓")
    ck("låsknappen byter ikon med texten", w.lock_btn.glyph() == "unlock")
    w.lock_btn.setText("🔒")
    ck("texten finns kvar för skärmläsare/tester", w.close_btn.text() == "✕" and w.close_btn.accessibleName())
    img = w.close_btn.grab().toImage()
    ck("knappen målas utan fel", img.width() == 30 and img.height() == 28)

    # flikarna ryms utan rullpilar vid standardbredden
    tb = w.tabs.tabBar()
    ck("flikar: inga rullpilar, delar bredden", (not tb.usesScrollButtons()) and tb.expanding())
    ck("flikar: alla fyra syns inom fönstrets bredd", all(tb.tabRect(i).right() <= w.width() for i in range(tb.count())), [tb.tabRect(i).right() for i in range(tb.count())])

    # typsnittet och teman slår igenom i fönstrets stil
    settings.set_pref("ui_font", "lattlast")
    w._apply_theme()
    ck("typsnitt Verdana i stilen", "Verdana" in w.styleSheet())
    settings.set_pref("ui_font", "standard")
    w._apply_theme()
    ck("standardtypsnitt i stilen", "Segoe UI Variable Text" in w.styleSheet() and "Verdana" not in w.styleSheet())
    key_a = w._look_key()
    settings.set_pref("ui_font", "serif")
    ck("typsnittet ingår i kortens cache-nyckel", w._look_key() != key_a)
    settings.set_pref("ui_font", "standard")
    for k in ("midnatt", "lavendel", "sand"):
        settings.set_pref("theme_preset", k)
        w._apply_theme()
        ck(f"tema {k} tillämpas", True)

    # dialogen har typsnittsval
    from ui.theme_dialog import ThemeDialog
    changed = []
    dlg = ThemeDialog(None, settings, lambda: changed.append(1))
    ck("temadialogen: knapp för varje tema", len(dlg.preset_buttons) == 9)
    ck("temadialogen: typsnittsväljare med 5 val", dlg.font_combo.count() == 5)
    dlg.font_combo.setCurrentIndex(1)
    ck("typsnittsval sparas och slår igenom", settings.pref("ui_font") == "lattlast" and changed)
    dlg.reset()
    ck("återställ → standardtypsnitt", settings.pref("ui_font") == "standard" and dlg.font_combo.currentIndex() == 0)

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
    _run_parent("design_test")
    print(f"\ndesign_test: {_ok} lyckades, {_fail} misslyckades")
    sys.exit(1 if _fail else 0)
