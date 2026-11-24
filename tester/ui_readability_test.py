#!/usr/bin/env python3
"""
ui_readability_test.py — all text ska vara väl synlig.

Kör:  python tester/ui_readability_test.py

Mäter WCAG-kontrast för widgetens riktiga färgtokens (mörkt + ljust tema) över både
värsta tänkbara bakgrund (vit under mörkt tema / svart under ljust) och en mellangrå, för alla
transparensval. Kontrollerar också att "Av" (helt opakt) ger opak panel, att ingen text är
mindre än 10 px och att inmatningsfältens platshållartext har läsbar färg.
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
    import re
    from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

    app = QApplication([])
    import widget as W
    from core.settings import Settings
    from core.store import TaskStore

    res: list[tuple[str, bool, str]] = []

    def ck(name, cond, extra=""):
        res.append((name, bool(cond), extra))

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

    tints = [parse(x) for x in (
        *W.PRIORITY_ROW_TINT.values(), *W.PRIO_HOVER_TINT.values(),
        "rgba(239, 68, 68, 0.15)", "rgba(245, 158, 11, 0.12)",       # försenad / idag
        "rgba(251, 191, 36, 0.10)", "rgba(251, 191, 36, 0.17)",      # fäst
    )]

    def worst(theme, factor, backdrop):
        t = W._tokens_with_transparency(theme, factor)
        w = 99.0
        for pk in ("bg_top", "bg_bottom"):
            panel = over(parse(t[pk]), backdrop)
            layers = [panel, over(parse(t["surface"]), panel)]
            layers += [over(tint, panel) for tint in tints]
            for bg in layers:
                for tk in ("fg", "muted", "hint"):
                    w = min(w, ratio(over(parse(t[tk]), bg), bg))
        return w

    white, black, mid = (255, 255, 255, 1), (0, 0, 0, 1), (128, 128, 128, 1)
    for name, theme, extreme in (("mörkt", W.GLASS_DARK, white), ("ljust", W.GLASS_LIGHT, black)):
        for f in (1.0, 0.85, 0.70, 0.55, 0.0):
            wm = worst(theme, f, mid)
            ck(f"{name} tema, transparens {f}: text ≥ 4.5:1 mot mellangrå bakgrund", wm >= 4.5, f"({wm:.2f})")
            we = worst(theme, f, extreme)
            lim = 4.5 if f in (1.0, 0.0) else (4.0 if f >= 0.85 else 3.0)
            ck(f"{name} tema, transparens {f}: text ≥ {lim}:1 även mot värsta bakgrund", we >= lim, f"({we:.2f})")

    # --- "Av" = opak panel, aldrig genomskinlig -------------------------------------------
    t0 = W._tokens_with_transparency(W.GLASS_DARK, 0.0)
    ck('"Av" (0.0) ger opak panel (alfa 255)', t0["bg_top"].endswith(", 255)") and t0["bg_bottom"].endswith(", 255)"), t0["bg_top"])
    t1 = W._tokens_with_transparency(W.GLASS_DARK, 0.30)
    ck("panelen blir aldrig mer genomskinlig än golvet", parse(t1["bg_top"])[3] >= W.MIN_PANEL_OPACITY * 0.97 * (248 / 255) - 0.01)

    # --- byggd widget: minsta textstorlek + platshållartext ------------------------------
    tmp = tempfile.mkdtemp(prefix="taskbord_read_")
    settings = Settings(str(Path(tmp) / "settings.json"))
    store = TaskStore(data_dir_override=Path(tmp) / "data")
    store.add_task("Läsbarhetstest")
    shell = QWidget()
    w = W.TodoWidget(app.primaryScreen(), store, settings, win_id="r", parent=shell)
    lay = QVBoxLayout(shell)
    lay.addWidget(w)
    w._shell = shell
    shell.show()
    for dens in ("compact", "comfortable", "cozy"):
        settings.set_density_mode(dens)
        w._apply_theme()
        sizes = [int(x) for x in re.findall(r"font-size:\s*(\d+)px", w.styleSheet())]
        ck(f"textstorlek {dens}: ingen text under 10 px", sizes and min(sizes) >= 10, f"(min {min(sizes) if sizes else '-'})")
    settings.set_density_mode("comfortable")
    w._apply_theme()
    ss = w.styleSheet()
    ck("platshållartext (Sök/Skriv ny uppgift) har läsbar färg", ss.count("placeholder-text-color") >= 1)
    ck("normal: minsta text är 11 px (var 10)", min(int(x) for x in re.findall(r"font-size:\s*(\d+)px", ss)) >= 11)

    bad = [(n, e) for n, ok, e in res if not ok]
    print("CHILD", len(res) - len(bad), len(bad))
    for n, e in bad:
        print("  ✗", n, e)
    shutil.rmtree(tmp, ignore_errors=True)
    sys.stdout.flush()
    os._exit(0)


if "--child" in sys.argv:
    child()
else:
    from _qtenv import qt_env

    work = Path(tempfile.mkdtemp(prefix="taskbord_readtest_"))
    env, why = qt_env(work)
    if env is None:
        print(f"ui_readability_test: hoppas över ({why})")
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
    print(f"\nui_readability_test: {_ok} lyckades, {_fail} misslyckades")
    sys.exit(1 if _fail else 0)
