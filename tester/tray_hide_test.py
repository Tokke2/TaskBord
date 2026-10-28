#!/usr/bin/env python3
"""
tray_hide_test.py — stäng (✕) och minimera (–) gömmer fönstret till systemfältet; tray-ikonen tar fram det.

Kör:  python tester/tray_hide_test.py
Riktig TodoWidget (offscreen) i en egen process + TrayHideMixin mot stubbar.
"""
from __future__ import annotations

import logging
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
    import threading
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QApplication, QMenu, QPushButton, QVBoxLayout, QWidget

    app = QApplication([])
    from core.settings import Settings
    from core.store import TaskStore
    import widget as W

    res: list = []

    def ck(name, cond, extra=""):
        res.append((name + (f" {extra}" if not cond and extra else ""), bool(cond)))

    tmp = tempfile.mkdtemp(prefix="taskbord_trayhide_")
    settings = Settings(str(Path(tmp) / "settings.json"))
    store = TaskStore(data_dir_override=Path(tmp) / "data")
    shell = QWidget()
    w = W.TodoWidget(app.primaryScreen(), store, settings, win_id="t", parent=shell)
    lay = QVBoxLayout(shell)
    lay.addWidget(w)
    w._shell = shell
    shell.resize(460, 520)
    shell.show()
    app.processEvents()

    # ----- knapparna i fönstret -----
    mb, cb = w.min_btn, w.close_btn
    ck("minimera-knapp finns", isinstance(mb, QPushButton) and mb.text() == "–")
    ck("stäng-knapp finns", isinstance(cb, QPushButton) and cb.text() == "✕")
    ck("tooltips förklarar systemfältet", "systemfältet" in mb.toolTip() and "systemfältet" in cb.toolTip())
    ck("knapparna har tillgängliga namn", bool(mb.accessibleName()) and bool(cb.accessibleName()))
    ck("knapparna syns och är klickbara (≥ 28 px)", mb.isVisible() and cb.isVisible() and mb.width() >= 28 and cb.height() >= 28)
    ck("knapparna ligger i headern (ovanför sökrutan)", mb.mapTo(w, QPoint(0, 0)).y() < w.search_input.mapTo(w, QPoint(0, 0)).y())
    qss = w.styleSheet()
    ck("knapparna har egen stil med text i temats textfärg", "QPushButton#winBtn" in qss and "QPushButton#closeBtn" in qss)

    got: list = []
    w.hide_to_tray_requested.connect(lambda: got.append(1))
    mb.click()
    ck("– skickar hide_to_tray_requested", got == [1])
    cb.click()
    ck("✕ skickar hide_to_tray_requested", got == [1, 1])
    w.close()
    app.processEvents()
    ck("stäng-förfrågan (Alt+F4 m.m.) skickar också signalen", len(got) == 3, got)
    ck("…och fönstret förstörs inte", w.isVisible())
    w._allow_close = True
    w.close()
    ck("vid riktig nedstängning (_allow_close) skickas ingen signal", len(got) == 3, got)
    w._allow_close = False

    # högerklicksmenyn
    seen = {}
    pick = {"t": None}

    class FakeMenu(QMenu):
        def exec(self, pos=None):  # noqa: A003
            seen["acts"] = [a.text() for a in self.actions() if a.text()]
            for a in self.actions():
                if pick["t"] and a.text().startswith(pick["t"]):
                    return a
            return None

    sys.modules["ui.widget_parts.window_ops"].QMenu = FakeMenu

    class Ev:
        def globalPos(self):
            return QPoint(5, 5)

    pick["t"] = "🗕"
    n = len(got)
    w.contextMenuEvent(Ev())
    ck("högerklicksmenyn har 'Minimera till systemfältet'", any("systemfältet" in a for a in seen["acts"]), seen)
    ck("…och valet gömmer", len(got) == n + 1)

    # ----- kontrollern (TrayHideMixin) -----
    from app.mixins.tray_hide import TrayHideMixin

    class Tray:
        def __init__(self, visible=True):
            self.visible, self.msgs = visible, []

        def isVisible(self):
            return self.visible

        def showMessage(self, *a):
            self.msgs.append(a)

    class Shell:
        def __init__(self):
            self.vis, self.calls = True, []

        def hide(self):
            self.vis = False
            self.calls.append("hide")

        def show(self):
            self.vis = True
            self.calls.append("show")

    class Wid:
        def __init__(self, shell):
            self._shell, self.saved = shell, 0

        def _save_geometry_now(self):
            self.saved += 1

    class Ctl(TrayHideMixin):
        _QSystemTrayIcon = type("T", (), {"MessageIcon": type("I", (), {"Information": 2})})

        def __init__(self, visible=True):
            self._tray = Tray(visible)
            self._log = logging.getLogger("th")
            self._widget_lock = threading.RLock()
            self.sh = Shell()
            self.wd = Wid(self.sh)
            self._widgets = {"a": self.wd}
            self.settings = type("S", (), {"start_minimized": lambda s: self.sm})()
            self.sm = False
            self.shown = 0

        def _show_existing_window(self):
            self.shown += 1
            self._clear_tray_hidden()
            self.sh.show()

    c = Ctl()
    ck("från början inte gömd", not c._is_hidden_to_tray())
    ck("_hide_to_tray lyckas", c._hide_to_tray() is True)
    ck("skalet göms", c.sh.vis is False and c.sh.calls == ["hide"])
    ck("märkt som gömd (kontroller, widget, skal)", c._is_hidden_to_tray() and c.wd._hidden_to_tray and c.sh._hidden_to_tray)
    ck("läget sparas innan det göms", c.wd.saved == 1)
    ck("tray-notis visas första gången", len(c._tray.msgs) == 1 and "systemfältet" in c._tray.msgs[0][1])
    c._hide_to_tray()
    ck("notisen visas bara en gång", len(c._tray.msgs) == 1)
    ck("återställ: visar fönstret", c._restore_from_tray() is True and c.sh.vis is True and c.shown == 1)
    ck("…och märkningen är borta överallt", not c._is_hidden_to_tray() and not c.wd._hidden_to_tray and not c.sh._hidden_to_tray)
    ck("återställ när inget är gömt gör ingenting", c._restore_from_tray() is False and c.shown == 1)

    c2 = Ctl(visible=False)
    ck("ingen tray-ikon → fönstret göms INTE (man skulle bli utelåst)", c2._hide_to_tray() is False and c2.sh.vis is True and not c2._is_hidden_to_tray())

    c3 = Ctl()
    c3.sm = True
    c3._apply_start_minimized()
    ck("'Starta minimerad i tray' gömmer vid start (utan notis)", c3.sh.vis is False and c3._tray.msgs == [])
    c4 = Ctl()
    c4._apply_start_minimized()
    ck("avstängd inställning → fönstret visas som vanligt", c4.sh.vis is True)

    # ----- start med datorn (--autostart) → minimerad -----
    saved_argv = list(sys.argv)
    try:
        sys.argv = ["main.pyw", "--autostart"]
        c5 = Ctl()
        ck("startad med datorn (--autostart) → känns igen", c5._started_by_autostart() is True)
        c5._apply_start_minimized()
        ck("start med datorn: fönstret göms till tray (utan notis)", c5.sh.vis is False and c5._tray.msgs == [])
        sys.argv = ["main.pyw"]
        c6 = Ctl()
        ck("vanlig start → inte autostart", c6._started_by_autostart() is False)
        c6._apply_start_minimized()
        ck("vanlig (manuell) start visar fönstret", c6.sh.vis is True and not c6._is_hidden_to_tray())
        # tray-ikonen saknas först vid inloggning → nytt försök senare
        sys.argv = ["main.pyw", "--autostart"]
        c7 = Ctl(visible=False)
        shots = []
        c7._QTimer = type("Q", (), {"singleShot": staticmethod(lambda ms, f: shots.append((ms, f)))})
        c7._apply_start_minimized()
        ck("ingen tray-ikon ännu → fönstret visas men nytt försök schemaläggs", c7.sh.vis is True and len(shots) == 1 and shots[0][0] == 5000)
        c7._tray.visible = True
        shots[0][1]()
        ck("när tray-ikonen kommit göms fönstret", c7.sh.vis is False)
        # tyst omstart efter uppdatering
        import time as _t
        sys.argv = ["main.pyw"]
        store_ts = {"v": 0.0}

        class St:
            def start_minimized(self):
                return False

            def restart_hidden_until(self):
                return store_ts["v"]

            def set_restart_hidden_until(self, ts):
                store_ts["v"] = ts
        c8 = Ctl()
        c8.settings = St()
        c8._remember_hidden_for_restart()
        ck("inget märke när fönstret inte är gömt", store_ts["v"] == 0.0)
        c8._hide_to_tray(notice=False)
        c8._remember_hidden_for_restart()
        ck("gömt före tyst omstart → märke ~3 min framåt", 150 < store_ts["v"] - _t.time() <= 181)
        c9 = Ctl()
        c9.settings = St()
        c9._apply_start_minimized()
        ck("omstarten efter uppdatering startar gömd", c9.sh.vis is False)
        ck("märket gäller bara EN omstart (nollas)", store_ts["v"] == 0.0)
        c10 = Ctl()
        c10.settings = St()
        c10._apply_start_minimized()
        ck("nästa start visar fönstret", c10.sh.vis is True)
        store_ts["v"] = _t.time() - 5
        c11 = Ctl()
        c11.settings = St()
        c11._apply_start_minimized()
        ck("utgånget märke ignoreras", c11.sh.vis is True)
    finally:
        sys.argv = saved_argv

    # ----- att inget visar fönstret av sig själv medan det är gömt (källkodskontroll) -----
    src = app_source(ROOT)
    for name, guard in (
        ("_maintain_desktop_level", "_is_hidden_to_tray()"),
        ("_check_idle", "_is_hidden_to_tray()"),
        ("_lift_timeout", "_is_hidden_to_tray()"),
    ):
        i = src.index(f"def {name}(")
        ck(f"{name} rör inte ett gömt fönster", guard in src[i:i + 900])
    for name in ("_lift_on_top_temporarily", "bring_all_to_front"):
        i = src.index(f"def {name}(")
        ck(f"{name} (tray-klick m.m.) visar ett gömt fönster", "_restore_from_tray()" in src[i:i + 2500])
    for name in ("_show_existing_window", "_show_window_at_cursor"):
        i = src.index(f"def {name}(")
        ck(f"{name} rensar 'gömd'-märkningen", "_clear_tray_hidden()" in src[i:i + 900])
    wsrc = (ROOT / "ui/widget_parts/qt_events.py").read_text(encoding="utf-8")
    i = wsrc.index("def nativeEvent(")
    ck("nativeEvent släpper igenom hide när fönstret gömts av användaren", "_hidden_to_tray" in wsrc[i:i + 2500])
    fsrc = (ROOT / "ui/widget_parts/focus_timers.py").read_text(encoding="utf-8")
    i = fsrc.index("def _periodic_zorder_check(")
    ck("z-order-timern visar inte igen ett gömt fönster", "_hidden_to_tray" in fsrc[i:i + 1500])

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

    work = Path(tempfile.mkdtemp(prefix="taskbord_trayhidetest_"))
    env, why = qt_env(work)
    if env is None:
        print(f"tray_hide_test: Qt-delen hoppas över ({why})")
    else:
        r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--child"], cwd=ROOT, env=env,
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
            check("barnprocessen körde klart", False, (r.stdout + r.stderr)[-2200:])
    shutil.rmtree(work, ignore_errors=True)
    src = app_source(ROOT)
    asrc = (ROOT / "app/mixins/autostart.py").read_text(encoding="utf-8")
    check("autostart-kommandot får --autostart", "{AUTOSTART_FLAG}" in asrc and "AUTOSTART_FLAG" in asrc.split("def _autostart_build_command")[1][:900])
    cons = (ROOT / "app/constants.py").read_text(encoding="utf-8")
    check("flaggan heter --autostart", 'AUTOSTART_FLAG: Final[str] = "--autostart"' in cons)
    from app.config import parse_args
    cfg, _mode = parse_args(["main.pyw", "--autostart", "--no-splash"])
    check("--autostart förstås av argumentläsaren (ingen SystemExit → övriga flaggor gäller)", cfg.show_splash is False)
    usrc = (ROOT / "app/mixins/updates.py").read_text(encoding="utf-8")
    check("tyst omstart minns gömt läge före omstarten", usrc.index("_remember_hidden_for_restart()") < usrc.index('_flush_window_state("före tyst omstart")'))
    check("TrayHideMixin ingår i AppController", "TrayHideMixin,\n    BackupSyncMixin" in (ROOT / "app/controller.py").read_text(encoding="utf-8"))
    check("signalen kopplas till _hide_to_tray", "hide_to_tray_requested.connect(self._hide_to_tray)" in src)
    check("'Starta minimerad' används vid start", "_apply_start_minimized" in (ROOT / "app/controller.py").read_text(encoding="utf-8"))
    print(f"\ntray_hide_test: {_ok} lyckades, {_fail} misslyckades")
    sys.exit(1 if _fail else 0)
