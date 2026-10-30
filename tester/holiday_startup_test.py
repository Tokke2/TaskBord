#!/usr/bin/env python3
"""
holiday_startup_test.py — (1) röda dagar + rutan högst upp (kommande röd dag på en vardag i samma vecka),
(2) fördröjd autostart (--autostart väntar ~45 s), (3) startmätning (data/startup_times.json) + snabbare start.

Kör:  python tester/holiday_startup_test.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date
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


def pure_tests() -> None:
    from core import holidays_se as hs
    from app import startup_timing as st

    # ---- påsk + röda dagar
    check("påskdagen 2024/2025/2026/2027", [hs.easter(y) for y in (2024, 2025, 2026, 2027)]
          == [date(2024, 3, 31), date(2025, 4, 20), date(2026, 4, 5), date(2027, 3, 28)])
    h26 = hs.holidays(2026)
    names = {d: n for d, (n, _o) in h26.items()}
    check("2026: långfredag 3/4, annandag påsk 6/4", names[date(2026, 4, 3)] == "Långfredagen" and names[date(2026, 4, 6)] == "Annandag påsk")
    check("2026: Kristi himmelsfärd torsdag 14/5, pingstdagen 24/5", names[date(2026, 5, 14)] == "Kristi himmelsfärdsdag" and names[date(2026, 5, 24)] == "Pingstdagen")
    check("2026: nationaldagen 6/6, midsommarafton fre 19/6, midsommardagen lör 20/6",
          names[date(2026, 6, 6)] == "Nationaldagen" and names[date(2026, 6, 19)] == "Midsommarafton" and names[date(2026, 6, 20)] == "Midsommardagen")
    check("2026: alla helgons dag lör 31/10, jul 24–26/12", names[date(2026, 10, 31)] == "Alla helgons dag"
          and all(date(2026, 12, d) in names for d in (24, 25, 26)))
    h25 = {d: n for d, (n, _o) in hs.holidays(2025).items()}
    check("2025: Kristi himmelsfärd 29/5, midsommarafton 20/6, midsommardagen 21/6, alla helgons 1/11",
          h25[date(2025, 5, 29)] == "Kristi himmelsfärdsdag" and h25[date(2025, 6, 20)] == "Midsommarafton"
          and h25[date(2025, 6, 21)] == "Midsommardagen" and h25[date(2025, 11, 1)] == "Alla helgons dag")
    check("officiell vs praktiskt ledig", h26[date(2026, 5, 1)][1] is True and h26[date(2026, 12, 24)][1] is False)

    # ---- veckans röda dagar på vardagar
    t = lambda d: hs.banner_text(d)  # noqa: E731
    check("måndag 11/5: Kristi himmelsfärd om 3 dagar", "torsdag 14 maj" in t(date(2026, 5, 11)) and "om 3 dagar" in t(date(2026, 5, 11)), t(date(2026, 5, 11)))
    check("rutan börjar med 🔴 Röd dag", t(date(2026, 5, 11)).startswith("🔴 Röd dag: Kristi himmelsfärdsdag"))
    check("onsdag 13/5: imorgon", "imorgon (torsdag)" in t(date(2026, 5, 13)), t(date(2026, 5, 13)))
    check("torsdag 14/5: idag", t(date(2026, 5, 14)).endswith("idag"), t(date(2026, 5, 14)))
    check("fredag 15/5: den har passerat → ingen ruta", t(date(2026, 5, 15)) == "")
    check("veckan 26–30/10 har bara en lördag (alla helgons) → ingen ruta", all(t(date(2026, 10, d)) == "" for d in range(26, 31)))
    check("lördag 4/4 (efter långfredag, före annandag påsk nästa vecka) → ingen ruta", t(date(2026, 4, 4)) == "")
    check("långfredag 3/4: idag", "Långfredagen idag" in t(date(2026, 4, 3)))
    check("annandag påsk måndag 6/4: idag", "Annandag påsk idag" in t(date(2026, 4, 6)))
    check("tisdag 7/4: ingen ruta (måndagen har gått)", t(date(2026, 4, 7)) == "")
    midsommar = t(date(2026, 6, 15))
    check("midsommarveckan visar fredagen men inte lördagens midsommardag", "Midsommarafton" in midsommar and "Midsommardagen" not in midsommar and "ledig för de flesta" in midsommar, midsommar)
    jul = t(date(2026, 12, 28))
    check("veckan över årsskiftet: nyårsafton (tors) + nyårsdagen (fre 2027)", "Nyårsafton" in jul and "Nyårsdagen" in jul and "  •  " in jul, jul)
    check("1 maj (fredag 2026) visas veckan innan", "Första maj" in t(date(2026, 4, 27)) and "fredag 1 maj" in t(date(2026, 4, 27)))
    check("week_items: bara mån–fre, sorterade", [d.weekday() < 5 for d, *_ in hs.week_items(date(2026, 12, 28))] == [True, True]
          and hs.week_items(date(2026, 12, 28))[0][0] < hs.week_items(date(2026, 12, 28))[1][0])

    # ---- fördröjd autostart
    check("ingen fördröjning utan --autostart", st.autostart_delay_sec(["main.pyw"], {}, 60) == 0)
    check("--autostart vid datorstart (uptime 1 min) → 45 s", st.autostart_delay_sec(["main.pyw", "--autostart"], {}, 60) == 45)
    check("--autostart när datorn kört länge → kort paus", st.autostart_delay_sec(["main.pyw", "--autostart"], {}, 3600) == st.AUTOSTART_DELAY_LATE_SEC)
    check("--autostart, uptime okänd → 45 s", st.autostart_delay_sec(["--autostart"], {}, None) in (45, st.AUTOSTART_DELAY_LATE_SEC))
    check("miljövariabel 0 = ingen fördröjning", st.autostart_delay_sec(["--autostart"], {st.ENV_DELAY: "0"}, 60) == 0)
    check("miljövariabel 12,5 → 12,5 s", st.autostart_delay_sec(["--autostart"], {st.ENV_DELAY: "12,5"}, 60) == 12.5)
    check("miljövariabel tak 600 s", st.autostart_delay_sec(["--autostart"], {st.ENV_DELAY: "99999"}, 60) == 600)
    check("ogiltig miljövariabel ignoreras", st.autostart_delay_sec(["--autostart"], {st.ENV_DELAY: "abc"}, 60) == 45)
    slept = []
    d = st.wait_for_autostart(["--autostart"], sleep=slept.append, env={}, uptime=30)
    check("wait_for_autostart sover i korta steg som summerar till 45 s", d == 45 and abs(sum(slept) - 45) < 1e-6 and max(slept) <= 1.0 and len(slept) == 45, (d, len(slept)))
    slept.clear()
    check("manuell start sover aldrig", st.wait_for_autostart(["main.pyw"], sleep=slept.append, env={}, uptime=30) == 0 and not slept)
    check("mätklockan nollställs efter väntan (fördröjningen räknas inte som starttid)", st.marks() == [])

    # ---- mätning
    st.mark("a"); st.mark("b")
    check("summary nämner stegen", "a " in st.summary() and "b " in st.summary() and st.summary().startswith("Start "))
    check("slowest ger ett steg", st.slowest()[0] in ("a", "b"))
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(35):
            st.record(Path(tmp) / "data", autostart=bool(i % 2))
        runs = json.loads((Path(tmp) / "data" / "startup_times.json").read_text(encoding="utf-8"))
        check("startup_times.json sparar de senaste 30 starterna", len(runs) == 30, len(runs))
        check("posten har totalt, steg och autostart", {"totalt_s", "steg_s", "autostart", "tid"} <= set(runs[-1]) and set(runs[-1]["steg_s"]) == {"a", "b"})
    check("record ger None (ingen krasch) vid ogiltig sökväg", st.record(Path("/proc/finns/inte/här")) is None)

    # ---- källkod
    main_src = (ROOT / "main.pyw").read_text(encoding="utf-8")
    check("main.pyw väntar (autostart) INNAN app.bootstrap importeras", 0 < main_src.index("wait_for_autostart") < main_src.index("from app.bootstrap import"))
    check("main.pyw < 200 rader", main_src.count("\n") < 200)
    ctl = (ROOT / "app" / "controller.py").read_text(encoding="utf-8")
    check("startdiagnostiken körs efter att fönstret kommit upp (singleShot)", "singleShot(DIAGNOSTICS_DELAY_MS, self._run_diagnostics_deferred)" in ctl
          and "self._run_diagnostics_on_startup()\n        except" not in ctl.split("def run(")[1].split("def _run_diagnostics_deferred")[0])
    boot = (ROOT / "app" / "bootstrap.py").read_text(encoding="utf-8")
    check("splash-väntan bara när en splash visats", "if splash_shown and elapsed < Timeouts.SPLASH_MIN_DURATION" in boot)
    check("mätpunkter i bootstrap", all(f'_startup.mark("{n}")' in boot for n in ("beroenden", "controller + fönster")))
    check("--autostart finns som flagga i config", '"--autostart"' in (ROOT / "app" / "config.py").read_text(encoding="utf-8"))
    print("PURE", flush=True)


def child() -> None:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

    app = QApplication([])
    from core.settings import Settings
    from core.store import TaskStore
    import widget as W

    res: list = []

    def ck(name, cond, extra=None):
        res.append((name, bool(cond)))

    tmp = tempfile.mkdtemp(prefix="taskbord_holiday_")
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
    w._rebuild_task_list()
    app.processEvents()

    def at(d):
        w._holiday_today = lambda: d
        w._update_holiday_banner()
        app.processEvents()

    box = w.holiday_banner
    root = w.layout()
    at(date(2026, 10, 30))
    ck("ingen röd dag på en vardag den här veckan → rutan är dold", not box.isVisible())
    at(date(2026, 5, 11))
    ck("måndag 11/5 → rutan syns", box.isVisible())
    ck("texten: röd dag torsdag 14 maj", "Kristi himmelsfärdsdag" in w.holiday_label.text() and "torsdag 14 maj" in w.holiday_label.text(), w.holiday_label.text())
    # högst upp: direkt efter titelraden (layout-index 1)
    ck("rutan ligger högst upp (direkt under titelraden)", root.indexOf(box) == 1 and root.itemAt(0).layout() is not None, root.indexOf(box))
    ck("rutan är bred som fönstret", box.width() >= w.width() - 40, (box.width(), w.width()))
    ss = box.styleSheet()
    ck("läsbar: vit text på mörkröd botten", "#ffffff" in ss and "#7f1d1d" in ss)
    ck("textstorlek ≥ 11 px", "font-size: 12px" in ss)
    ck("✕ har förklarande tooltip/namn", "idag" in w.holiday_close_btn.toolTip() and w.holiday_close_btn.accessibleName())
    w.holiday_close_btn.click()
    app.processEvents()
    ck("✕ döljer rutan", not box.isVisible())
    at(date(2026, 5, 11))
    ck("…och den förblir dold samma dag", not box.isVisible())
    at(date(2026, 5, 12))
    ck("nästa dag (veckan har fortfarande röd dag) kommer den tillbaka", box.isVisible() and "om 2 dagar" in w.holiday_label.text())
    at(date(2026, 5, 15))
    ck("fredag efter → dold igen", not box.isVisible())
    at(date(2026, 12, 28))
    ck("årsskiftesveckan: flera röda dagar på en rad", box.isVisible() and "Nyårsafton" in w.holiday_label.text() and "Nyårsdagen" in w.holiday_label.text())
    ck("uppdateras av en timer (dygnsskifte)", w._holiday_timer.isActive() and w._holiday_timer.interval() == 15 * 60 * 1000)
    w._holiday_today = W.TodoWidget._holiday_today.__get__(w)
    w._rebuild_task_list()
    app.processEvents()
    ck("ombyggd lista förstör inte rutan", w.holiday_banner is box)

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
    pure_tests()
    from _qtenv import qt_env

    work = Path(tempfile.mkdtemp(prefix="taskbord_holtest_"))
    env, why = qt_env(work)
    if env is None:
        print(f"holiday_startup_test: Qt-delen hoppas över ({why})")
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
    print(f"\nholiday_startup_test: {_ok} lyckades, {_fail} misslyckades")
    sys.exit(1 if _fail else 0)
