#!/usr/bin/env python3
"""
power_test.py — energisnål och minnessnål: energisparläge när fönstret inte syns, minnesstädning, glesare timers,
automatisk textstorlek efter skärmen och solid panel som standard.

Kör:  python tester/power_test.py
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
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


def src(p):
    return (ROOT / p).read_text(encoding="utf-8")


def pure() -> None:
    from core import power, prefs, screen_fit as SF
    from core.settings import Settings, DEFAULT_WINDOW_TRANSPARENCY

    # --- beslutsfunktionen -----------------------------------------------------------------------------------------------
    check("syns → inget sparläge, ingen städning", power.plan(True, 999, None) == {"eco": False, "trim": False})
    check("nyss gömt (< 45 s) → ännu inget", power.plan(False, 10, None) == {"eco": False, "trim": False})
    check("gömt ≥ 45 s → sparläge + första städningen", power.plan(False, 46, None) == {"eco": True, "trim": True})
    check("städat nyss → sparläge men ingen ny städning", power.plan(False, 600, 120) == {"eco": True, "trim": False})
    check("städat för 20 min sedan → städa igen", power.plan(False, 4000, 20 * 60) == {"eco": True, "trim": True})
    check("avstängt i inställningarna → inget", power.plan(False, 999, None, enabled=False) == {"eco": False, "trim": False})

    # --- Windows-anropen är ofarliga på andra system ----------------------------------------------------------------------------
    if sys.platform != "win32":
        check("effektivitetsläge på icke-Windows → False utan fel", power.set_eco_mode(True) is False and power.eco_mode_on() is False)
    r = power.trim_memory()
    check("trim_memory ger {before, after, collected}", set(r) == {"before", "after", "collected"} and isinstance(r["collected"], int))
    m = power.memory_mb()
    check("memory_mb ger ett positivt tal (psutil)", m is None or m > 5)
    s = src("core/power.py")
    check("energiläget rör varken DPI-läge eller prioritetsklass", "SetProcessDPIAware" not in s and "SetPriorityClass" not in s and "SetProcessDpiAwareness" not in s)
    check("EcoQoS = ProcessPowerThrottling (4) med EXECUTION_SPEED (0x1)", "SetProcessInformation" in s and ", 4," in s and "0x1" in s)

    # --- mixin: tick-logik med falska fönster -----------------------------------------------------------------------------------
    from app.mixins.power_save import PowerSaveMixin

    class Sh:
        def __init__(self, vis=True, mini=False):
            self.vis, self.mini = vis, mini

        def isVisible(self): return self.vis
        def isMinimized(self): return self.mini

    class Dk:
        def __init__(self, state): self.state = state

    class W:
        def __init__(self, sh, dk=None):
            self._shell = sh
            if dk is not None:
                self._edge_dock = dk

    class St:
        def __init__(self): self.on = True
        def pref(self, k): return self.on

    class Ctl(PowerSaveMixin):
        def __init__(self, widgets):
            self._widgets = widgets
            self._widget_lock = threading.RLock()
            self.settings = St()
            self._log = logging.getLogger("pw")
            self._power_hidden_since = None
            self._power_last_trim = None
            self._power_eco = False

    calls = []
    orig = (power.set_eco_mode, power.trim_memory)
    power.set_eco_mode = lambda on: calls.append(("eco", on)) or True
    power.trim_memory = lambda: calls.append(("trim",)) or {"before": 100.0, "after": 60.0, "collected": 1}
    try:
        shell = Sh(True)
        c = Ctl({"a": W(shell)})
        check("syns → inte gömt", c._any_window_visible() is True)
        shell.vis = False
        check("gömt i tray → ej synligt", c._any_window_visible() is False)
        shell.vis, shell.mini = True, True
        check("minimerat → ej synligt", c._any_window_visible() is False)
        shell.mini = False
        c2 = Ctl({"a": W(Sh(True), Dk("hidden"))})
        check("dockat och gömt i kanten → ej synligt", c2._any_window_visible() is False)
        c2 = Ctl({"a": W(Sh(True), Dk("shown"))})
        check("dockat men framme → synligt", c2._any_window_visible() is True)
        check("inga fönster → ej synligt", Ctl({})._any_window_visible() is False)

        c = Ctl({"a": W(Sh(False))})          # gömd
        c._power_tick(now=1000.0)
        check("första tick gömd: ännu ingen sparning (väntar 45 s)", calls == [] and c._power_eco is False)
        c._power_tick(now=1030.0)
        check("30 s: fortfarande inte", calls == [])
        c._power_tick(now=1050.0)
        check("50 s gömd: effektivitetsläge PÅ + minnet städas", calls == [("eco", True), ("trim",)], calls)
        calls.clear()
        c._power_tick(now=1065.0)
        check("nästa tick: inget nytt (ingen upprepning)", calls == [])
        c._power_tick(now=1065.0 + 20 * 60 + 1)
        check("efter 20 min: städas igen (läget redan på)", calls == [("trim",)], calls)
        calls.clear()
        c._widgets["a"]._shell.vis = True
        c._power_tick(now=3000.0)
        check("fönstret syns igen → läget AV direkt", calls == [("eco", False)], calls)
        calls.clear()
        c._widgets["a"]._shell.vis = False
        c._power_tick(now=3010.0)
        c._power_tick(now=3060.0)
        check("gömd igen → på igen + städning (börjar om)", calls == [("eco", True), ("trim",)], calls)
        calls.clear()
        c.settings.on = False
        c._power_tick(now=3100.0)
        check("avstängd i inställningarna → läget stängs av", calls == [("eco", False)], calls)
        calls.clear()
        c._power_tick(now=5000.0)
        check("…och förblir av", calls == [])
    finally:
        power.set_eco_mode, power.trim_memory = orig

    # --- inställningar, tray, kopplingar ------------------------------------------------------------------------------------------
    tmp = Path(tempfile.mkdtemp(prefix="ledgebord_pw_"))
    st = Settings(str(tmp / "s.json"))
    check("power_save, auto_scale på som standard; crisp_v2 av", st.pref("power_save") is True and st.pref("auto_scale") is True and st.pref("crisp_v2") is False)
    check("standardpanelen är solid (skarpast text)", DEFAULT_WINDOW_TRANSPARENCY == 0.0 and st.window_transparency() == 0.0)
    shutil.rmtree(tmp, ignore_errors=True)
    check("tray: Energisparläge-rad", "_toggle_power_save" in src("app/mixins/tray.py") and "power_save" in src("app/mixins/tray.py"))
    check("controller: PowerSaveMixin + start", "PowerSaveMixin" in src("app/controller.py") and "_init_power_save()" in src("app/controller.py"))
    check("tickar var 15:e sekund, bara en timer", "TICK_MS = 15_000" in src("app/mixins/power_save.py"))

    # --- glesare timers ---------------------------------------------------------------------------------------------------------
    ft = src("ui/widget_parts/focus_timers.py")
    check("PWM-statistiken tickar högst var 10:e sekund", "PWM_TICK_FLOOR_MS = 10_000" in ft and "_pwm_timer.start(PWM_TICK_FLOOR_MS)" in ft and ft.count("max(interval_ms, PWM_TICK_FLOOR_MS)") == 2)
    check("extern-synk 8 s, brygg-poll 1 s, inkorg 5 s", "setInterval(8000)" in src("app/mixins/backup_sync.py") and "setInterval(1000)" in src("app/mixins/mail_bridge_ctl.py")
          and "DEFAULT_INBOX_POLL_SEC: int = 5" in src("core/mail_bridge.py"))

    # --- automatisk textstorlek efter skärm -----------------------------------------------------------------------------------------
    f = SF.auto_scale
    check("1536 px (1080p@125 %) → 1.0, 1920 → 1.0", f(1536, 1.25) == 1.0 and f(1920, 1.0) == 1.0 and f(1800) == 1.0)
    check("1440p@100 % (2560) → 1.1", f(2560, 1.0) == 1.1)
    check("4K@100 % (3840) → 1.3, 3000 → 1.2", f(3840, 1.0) == 1.3 and f(3000) == 1.2)
    check("liten skärm: 1280 → 0.95, 1024 → 0.9", f(1280) == 0.95 and f(1024) == 0.9)
    check("skräpvärden → 1.0", f(0) == 1.0 and f(-5) == 1.0 and f("x") == 1.0 and f(None) == 1.0)
    check("alltid i 5 %-steg", all(abs(f(w) * 20 - round(f(w) * 20)) < 1e-9 for w in range(800, 5000, 37)))
    th = src("ui/widget_parts/theme.py")
    check("textfaktorn = reglage × skärmfaktor, och ingår i cache-nyckeln", "* self._auto_scale_factor()" in th and "round(self._auto_scale_factor(), 2)" in th)
    check("skärmbyte räknar om automatiska faktorn", "_last_auto_scale" in src("app/mixins/windows.py"))

    # --- engångsmigrering (källa) ------------------------------------------------------------------------------------------------
    w = src("app/mixins/windows.py")
    check("migrering: bara exakt gamla standarden 0,85 → 0 (eget val rörs inte)", 'pref("crisp_v2")' in w and "abs(float(self.settings.window_transparency()) - 0.85) < 1e-6" in w)


def child() -> None:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
    app = QApplication([])
    import widget as W
    from core.settings import Settings
    from core.store import TaskStore
    from ui.theme_dialog import ThemeDialog
    res = []

    def ck(name, cond, extra=""):
        res.append((name + (f" {extra}" if not cond and extra else ""), bool(cond)))

    tmp = Path(tempfile.mkdtemp(prefix="ledgebord_pwc_"))
    settings = Settings(str(tmp / "s.json"))
    store = TaskStore(data_dir_override=tmp / "d")
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

    from PySide6.QtCore import QTimer
    pwm = w._pwm_timer
    ck("PWM-timern tickar högst var 10:e sekund", pwm.interval() >= 10_000)
    ivs = sorted(t.interval() for t in w.findChildren(QTimer) if t.isActive())
    ck("ingen aktiv timer i fönstret tickar oftare än var 600:e ms", all(i >= 600 for i in ivs), ivs)

    # automatisk textstorlek
    base = w._text_scale_factor()
    ck("offscreen: ingen skärmfaktor (1.0)", base == 1.0, base)
    k1 = w._look_key()
    settings.set_pref("auto_scale", False)
    ck("auto av → faktorn = bara reglaget (1.0)", w._text_scale_factor() == 1.0 and w._auto_scale_factor() == 1.0)
    ck("auto-faktorn ingår i kortens cache-nyckel", len(w._look_key()) == 4 and w._look_key()[3] == 1.0)
    settings.set_pref("auto_scale", True)
    settings.set_pref("text_scale", 120)
    ck("reglage × skärmfaktor", abs(w._text_scale_factor() - 1.2 * w._auto_scale_factor()) < 1e-9)
    settings.set_pref("text_scale", 100)

    # temadialogen
    ch = []
    dlg = ThemeDialog(None, settings, lambda: ch.append(1))
    ck("temadialogen: automatisk textstorlek ikryssad", dlg.auto_check.isChecked())
    dlg.auto_check.setChecked(False)
    ck("…avkryssning sparas", settings.pref("auto_scale") is False and ch)
    dlg.reset()
    ck("återställ → auto på igen", settings.pref("auto_scale") is True and dlg.auto_check.isChecked())

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
    _run_parent("power_test")
    print(f"\npower_test: {_ok} lyckades, {_fail} misslyckades")
    sys.exit(1 if _fail else 0)
