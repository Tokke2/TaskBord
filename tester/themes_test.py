#!/usr/bin/env python3
"""
themes_test.py — färgteman, bakgrundsdjup, högkontrast: logik (core/themes.py), läsbarhet (≥ 4,5:1 för ALLA kombinationer)
och att fönstret faktiskt byter utseende. Kör:  python tester/themes_test.py
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


from core import prefs, themes as TH  # noqa: E402


def parse(s):
    s = s.strip()
    if s.startswith("#"):
        return int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16), 1.0
    p = [x.strip() for x in s[s.index("(") + 1:-1].split(",")]
    a = 1.0
    if len(p) > 3:
        a = float(p[3]) if "." in p[3] else int(p[3]) / 255
    return int(p[0]), int(p[1]), int(p[2]), a


def over(fg, bg):
    r, g, b, a = fg
    return (a * r + (1 - a) * bg[0], a * g + (1 - a) * bg[1], a * b + (1 - a) * bg[2], 1.0)


def lum(c):
    def f(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2])


def ratio(a, b):
    hi, lo = max(lum(a), lum(b)), min(lum(a), lum(b))
    return (hi + 0.05) / (lo + 0.05)


def pure() -> None:
    base = {"bg_top": "rgba(32, 36, 58, 248)", "bg_bottom": "rgba(16, 18, 33, 252)", "surface": "rgba(56, 62, 96, 120)",
            "fg": "#eef1fb", "muted": "#cfd6ec", "hint": "#cfd6ec"}
    check("standard utan justering = oförändrade tokens", TH.adjust_tokens(base, True, "standard", 0, False) is base)
    check("alla förval har etikett och färgprov", set(TH.PRESETS) == set(TH.SWATCH) == set(prefs.THEME_PRESETS))
    hav = TH.adjust_tokens(base, True, "hav")
    check("tema byter panelfärg men inte textfärg", hav["bg_top"] != base["bg_top"] and hav["fg"] == base["fg"] and hav["muted"] == base["muted"])
    check("grundtokens ändras aldrig (kopia)", base["bg_top"] == "rgba(32, 36, 58, 248)")
    d = TH.adjust_tokens(base, True, "standard", 50)
    check("bakgrundsdjup mörkar mörkt tema, alfa kvar", parse(d["bg_top"])[0] < 32 and d["bg_top"].endswith(", 248)"), d["bg_top"])
    lt = {"bg_top": "rgba(250, 251, 255, 250)", "bg_bottom": "rgba(233, 236, 248, 252)", "surface": "rgba(255,255,255,215)"}
    ld = TH.adjust_tokens(lt, False, "standard", 40)
    check("bakgrundsdjup ljusnar ljust tema", parse(ld["bg_bottom"])[0] > 233, ld["bg_bottom"])
    check("djup klämms 0–60", TH.adjust_tokens(base, True, "standard", 999)["bg_top"] == TH.adjust_tokens(base, True, "standard", 60)["bg_top"])
    hc = TH.adjust_tokens(base, True, "standard", 0, True)
    check("högkontrast mörkt: svart yta, vit text, heltäckande", hc["bg_top"].endswith(", 255)") and hc["fg"] == "#ffffff" and hc["muted"] == "#ffffff")
    hcl = TH.adjust_tokens(lt, False, "standard", 0, True)
    check("högkontrast ljust: vit yta, svart text", hcl["fg"] == "#000000" and parse(hcl["bg_top"])[:3] == (255, 255, 255))
    check("preset 'kontrast' = högkontrast", TH.adjust_tokens(base, True, "kontrast") == hc and TH.is_high_contrast("kontrast", False))
    check("pref-värden: valt tema rensas", prefs.coerce("theme_preset", "hav") == "hav" and prefs.coerce("bg_dim", 500) == 60)
    check("modulen har ingen Qt-import", "PySide" not in (ROOT / "core/themes.py").read_text(encoding="utf-8"))
    doc = (ROOT / "docs/MANUAL.md").read_text(encoding="utf-8")
    check("MANUAL beskriver teman", "Teman och utseende" in doc and "Hög kontrast" in doc and "Bakgrund" in doc)
    check("tray + högerklick har temadialogen",
          "_open_theme_dialog" in (ROOT / "app/mixins/tray.py").read_text(encoding="utf-8")
          and "theme_dialog_requested" in (ROOT / "ui/widget_parts/window_ops.py").read_text(encoding="utf-8"))


def child() -> None:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
    app = QApplication([])
    import widget as W
    from core.settings import Settings
    from core.store import TaskStore

    res: list = []

    def ck(name, cond, extra=""):
        res.append((name + (f" {extra}" if not cond and extra else ""), bool(cond)))

    tints = [parse(x) for x in (*W.PRIORITY_ROW_TINT.values(), *W.PRIO_HOVER_TINT.values(),
                                "rgba(239, 68, 68, 0.15)", "rgba(245, 158, 11, 0.12)",
                                "rgba(251, 191, 36, 0.10)", "rgba(251, 191, 36, 0.17)")]

    def worst(t, factor, backdrop):
        t = W._tokens_with_transparency(t, factor)
        w = 99.0
        for pk in ("bg_top", "bg_bottom"):
            panel = over(parse(t[pk]), backdrop)
            layers = [panel, over(parse(t["surface"]), panel)] + [over(tint, panel) for tint in tints]
            for bg in layers:
                for tk in ("fg", "muted", "hint"):
                    w = min(w, ratio(over(parse(t[tk]), bg), bg))
        return w

    white, black, mid = (255, 255, 255, 1), (0, 0, 0, 1), (128, 128, 128, 1)
    n = 0
    for preset in TH.PRESETS:
        for dark, base, extreme in ((True, W.GLASS_DARK, white), (False, W.GLASS_LIGHT, black)):
            for dim in (0, 30, 60):
                for hc in (False, True):
                    tk = TH.adjust_tokens(base, dark, preset, dim, hc)
                    for f in (1.0, 0.85, 0.70, 0.0):
                        n += 1
                        wm = worst(tk, f, mid)
                        ck(f"{preset} {'mörkt' if dark else 'ljust'} djup {dim} hk {hc} transp {f}: ≥ 4,5:1 mot mellangrå", wm >= 4.5, f"({wm:.2f})")
                        if f in (1.0, 0.0) or TH.is_high_contrast(preset, hc):
                            we = worst(tk, f, extreme)
                            ck(f"{preset} {'mörkt' if dark else 'ljust'} djup {dim} hk {hc} transp {f}: ≥ 4,5:1 mot värsta bakgrund", we >= 4.5, f"({we:.2f})")
                        else:
                            we = worst(tk, f, extreme)
                            lim = 4.0 if f >= 0.85 else 3.0
                            ck(f"{preset} {'mörkt' if dark else 'ljust'} djup {dim} transp {f}: ≥ {lim}:1 mot värsta bakgrund", we >= lim, f"({we:.2f})")
                    if TH.is_high_contrast(preset, hc):
                        wh = worst(tk, 1.0, extreme)
                        ck(f"högkontrast {'mörkt' if dark else 'ljust'}: ≥ 7:1 (AAA)", wh >= 7.0, f"({wh:.2f})")
    ck("kombinationer testade", n >= 250, n)

    tmp = tempfile.mkdtemp(prefix="ledgebord_themes_")
    settings = Settings(str(Path(tmp) / "s.json"))
    store = TaskStore(data_dir_override=Path(tmp) / "d")
    store.add_task("Tema-test", priority="high", due_date="2020-01-01")
    shell = QWidget()
    w = W.TodoWidget(app.primaryScreen(), store, settings, win_id="t", parent=shell)
    lay = QVBoxLayout(shell)
    lay.addWidget(w)
    w._shell = shell
    shell.resize(460, 560)
    shell.show()
    app.processEvents()
    settings.set_theme("dark")
    w._apply_theme()
    base_qss = w.styleSheet()
    settings.set_pref("theme_preset", "hav")
    w._apply_theme()
    hav_qss = w.styleSheet()
    ck("temat 'hav' ändrar stilen", hav_qss != base_qss and "rgba(12, 34, 54" in hav_qss, "")
    settings.set_pref("theme_preset", "standard")
    settings.set_pref("bg_dim", 40)
    w._apply_theme()
    ck("bakgrundsdjup ändrar stilen", w.styleSheet() != base_qss)
    settings.set_pref("bg_dim", 0)
    w._apply_theme()
    ck("tillbaka till standard = exakt samma stil som förut", w.styleSheet() == base_qss)
    settings.set_pref("high_contrast", True)
    w._apply_theme()
    hcq = w.styleSheet()
    ck("högkontrast: svart yta och vit text i stilen", "rgba(0, 0, 0, 255)" in hcq and "#ffffff" in hcq)
    ck("högkontrast: tjockare kanter på korten", "border: 2px solid" in hcq or "border-width: 2px" in hcq, "")
    ck("högkontrast gör panelen opak (ingen genomskinlighet)", getattr(w, "_transparency_factor", 1) in (0.0, 1.0) and getattr(w, "_hc_active", False))
    settings.set_pref("high_contrast", False)
    w._apply_theme()
    ck("högkontrast av → normal igen", w.styleSheet() == base_qss and not getattr(w, "_hc_active", True))
    # ljust tema
    settings.set_theme("light")
    settings.set_pref("high_contrast", True)
    w._apply_theme()
    ck("högkontrast ljust: vit yta", "rgba(255, 255, 255, 255)" in w.styleSheet())
    # dialogen
    from ui.theme_dialog import ThemeDialog
    calls: list = []
    settings.set_pref("high_contrast", False)
    settings.set_theme("dark")
    dlg = ThemeDialog(None, settings, on_change=lambda: calls.append(1), on_glass=lambda v: calls.append(("glass", v)))
    ck("dialogen har en knapp per tema", set(dlg.preset_buttons) == set(TH.PRESETS))
    dlg.preset_buttons["skog"].click()
    ck("val av tema sparas och meddelas", settings.pref("theme_preset") == "skog" and calls)
    dlg.dim_slider.setValue(35)
    dlg._flush()
    ck("slider bakgrund sparas", settings.pref("bg_dim") == 35)
    dlg.glass_slider.setValue(30)
    dlg._flush()
    ck("slider glas ger genomskinlighet 0,70 (golvet)", ("glass", 0.7) in calls, calls[-3:])
    dlg.glass_slider.setValue(0)
    dlg._flush()
    ck("glas 0 = 1,0", ("glass", 1.0) in calls)
    dlg.hc_check.setChecked(True)
    ck("hög kontrast sparas", settings.pref("high_contrast") is True)
    dlg.reset_btn.click()
    ck("återställ: standard", settings.pref("theme_preset") == "standard" and settings.pref("bg_dim") == 0
       and settings.pref("high_contrast") is False)
    shutil.rmtree(tmp, ignore_errors=True)
    bad = [n_ for n_, ok in res if not ok]
    print("CHILD", len(res) - len(bad), len(bad))
    for n_ in bad[:40]:
        print("  ✗", n_)
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
    _run_parent("themes_test")
    print(f"\nthemes_test: {_ok} lyckades, {_fail} misslyckades")
    sys.exit(1 if _fail else 0)
