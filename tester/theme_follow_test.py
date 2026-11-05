#!/usr/bin/env python3
"""
theme_follow_test.py — temat följer Windows ljust/mörkt LIVE (och klockan i Auto-läget), utan omstart.

Kör:  python tester/theme_follow_test.py
Riktig TodoWidget (offscreen) i en Qt-barnprocess; Windows-läget simuleras via Settings.system_theme.
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


def pure() -> None:
    src = (ROOT / "ui/widget_parts/theme.py").read_text(encoding="utf-8")
    body = src.split("def _check_auto_theme")[1].split("def _apply_theme")[0]
    check("vakten gäller både 'auto' och 'system'", '("auto", "system")' in body)
    check("vakten loggar inte när inget ändrats (körs var 5:e sekund)", body.count("logger.info") == 1 and "_log_call" not in src.split("def _check_auto_theme")[0][-80:])
    fsrc = (ROOT / "ui/widget_parts/focus_timers.py").read_text(encoding="utf-8")
    check("tema-timern tickar var 5:e sekund", "setInterval(5_000)" in fsrc and "600_000" not in fsrc.split("_auto_theme_timer")[1][:300])
    check("colorSchemeChanged lyssnas på", "colorSchemeChanged" in src and "_watch_system_theme()" in fsrc)
    ssrc = (ROOT / "core/settings.py").read_text(encoding="utf-8")
    sys_fn = ssrc.split("def system_theme")[1].split("def theme_quiet")[0]
    check("Windows-läget läses färskt ur registret (ingen cache)", "AppsUseLightTheme" in sys_fn and "self._cache" not in sys_fn and "_log" not in sys_fn)


def child() -> None:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
    app = QApplication([])
    from core.settings import Settings
    from core.store import TaskStore
    import widget as W
    from app.mixins.tray import TrayMixin

    res: list = []

    def ck(name, cond, extra=""):
        res.append((name + (f" {extra}" if not cond and extra else ""), bool(cond)))

    tmp = tempfile.mkdtemp(prefix="ledgebord_themefollow_")
    settings = Settings(str(Path(tmp) / "s.json"))
    state = {"win": "dark"}
    settings.system_theme = lambda: state["win"]  # simulerar Windows ljust/mörkt läge
    ck("standardtemat är 'Följ Windows'", settings.theme_raw() == "system")
    ck("theme_quiet följer Windows", settings.theme_quiet() == "dark" and settings.is_dark_quiet())
    state["win"] = "light"
    ck("…och ändras när Windows ändras", settings.theme_quiet() == "light" and not settings.is_dark_quiet() and settings.theme() == "light")
    state["win"] = None
    ck("okänt Windows-läge ger mörkt (reserv)", settings.theme_quiet() == "dark")
    ck("system_theme finns på riktigt och returnerar ljust/mörkt/None", Settings("/tmp/_x_unused.json").system_theme() in ("light", "dark", None))
    state["win"] = "dark"

    store = TaskStore(data_dir_override=Path(tmp) / "data")
    store.add_task("Tema-test", priority="high")
    shell = QWidget()
    w = W.TodoWidget(app.primaryScreen(), store, settings, win_id="t", parent=shell)
    lay = QVBoxLayout(shell)
    lay.addWidget(w)
    w._shell = shell
    shell.resize(460, 560)
    shell.show()
    app.processEvents()
    calls = []
    orig = w._apply_theme
    w._apply_theme = lambda: (calls.append(1), orig())[1]
    ck("fönstret startar mörkt", w._theme_is_dark is True)
    ck("tema-timern är aktiv och tickar var 5:e sekund", w._auto_theme_timer.isActive() and w._auto_theme_timer.interval() == 5000)
    ck("färgschema-signalen är kopplad (Qt ≥ 6.5)", getattr(w, "_system_theme_signal", False) is True)

    w._check_auto_theme()
    ck("ingen ändring → ingen omritning", calls == [])
    qss_dark = w.styleSheet()
    state["win"] = "light"            # användaren byter Windows till ljust läge
    w._check_auto_theme()             # (timern gör detta var 5:e sekund)
    ck("Windows bytte till ljust → fönstret byter live", calls == [1] and w._theme_is_dark is False)
    ck("stilmallen ändrades", w.styleSheet() != qss_dark)
    w._check_auto_theme()
    ck("ingen upprepad omritning när inget ändras", calls == [1])
    state["win"] = "dark"
    w._check_auto_theme()
    ck("och tillbaka till mörkt", calls == [1, 1] and w._theme_is_dark is True)
    # timer driver kontrollen
    state["win"] = "light"
    w._auto_theme_timer.timeout.emit()
    ck("timer-tick räcker för att byta", w._theme_is_dark is False)
    # signal driver kontrollen
    state["win"] = "dark"
    fired = False
    try:
        QGuiApplication.styleHints().colorSchemeChanged.emit(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.ColorScheme.Dark)
        fired = True
    except Exception:
        pass
    ck("colorSchemeChanged växlar direkt (utan att vänta på timern)", (not fired) or w._theme_is_dark is True, fired)

    # fasta teman följer inte Windows
    settings.set_theme("light")
    n = len(calls)
    w._apply_theme()
    state["win"] = "dark"
    w._check_auto_theme()
    ck("fast 'Ljust' ignorerar Windows", w._theme_is_dark is False and len(calls) == n + 1)
    settings.set_theme("dark")
    w._apply_theme()
    state["win"] = "light"
    n = len(calls)
    w._check_auto_theme()
    ck("fast 'Mörkt' ignorerar Windows", w._theme_is_dark is True and len(calls) == n)
    # auto (klocka)
    settings.set_theme("auto")
    settings.theme_quiet = lambda: "light"
    w._check_auto_theme()
    ck("Auto: klockan styr (ljust dagtid) och växlar utan omstart", w._theme_is_dark is False)
    del settings.theme_quiet

    # tray-menyns rubrik
    class Ctl(TrayMixin):
        pass
    c = Ctl()
    c.settings = settings
    settings.set_theme("system")
    state["win"] = "dark"
    t1 = c._theme_menu_title("system")
    state["win"] = "light"
    t2 = c._theme_menu_title("system")
    ck("tray: 'Följer Windows: mörkt/ljust'", "Följer Windows: mörkt" in t1 and "Följer Windows: ljust" in t2, (t1, t2))
    ck("tray: fast tema har ingen parentes", c._theme_menu_title("dark") == "🎨  Tema")
    settings.set_theme("auto")
    ck("tray: auto visar aktuellt läge", "Auto:" in c._theme_menu_title("auto"))
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
    _run_parent("theme_follow_test")
    print(f"\ntheme_follow_test: {_ok} lyckades, {_fail} misslyckades")
    sys.exit(1 if _fail else 0)
