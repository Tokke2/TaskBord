#!/usr/bin/env python3
"""
calendar_view_test.py — kalenderfliken: månadsrutnät, belastning per dag, klick, läsbarhet i båda teman.

Kör:  python tester/calendar_view_test.py
Rutnätslogiken (core/calendar_grid.py) körs direkt; vyn och fliken i fönstret i en Qt-barnprocess.
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

from datetime import date, timedelta  # noqa: E402

from core import calendar_grid as cg  # noqa: E402
from core import tag_colors as tc  # noqa: E402


def _blend(fg_rgba, bg_rgb):
    r, g, b, a = fg_rgba
    return tuple(round(a * f + (1 - a) * k) for f, k in zip((r, g, b), bg_rgb))


def _rgba(s):
    s = s.strip()
    if s.startswith("#"):
        return (int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16), 1.0)
    parts = [float(p) for p in s[s.index("(") + 1:s.rindex(")")].split(",")]
    a = parts[3] if len(parts) > 3 else 1.0
    return (parts[0], parts[1], parts[2], a if a <= 1.0 else a / 255.0)


def _hex(rgb):
    return "#%02x%02x%02x" % tuple(int(x) for x in rgb)


def pure() -> None:
    w = cg.month_grid(2026, 11)
    check("nov 2026 har 6 veckor (1 nov är söndag)", len(w) == 6 and w[0][0] == date(2026, 10, 26) and w[-1][-1] == date(2026, 12, 6))
    check("feb 2027 har exakt 4 veckor (1 feb är måndag, 28 dagar)", len(cg.month_grid(2027, 2)) == 4)
    check("varje vecka har 7 dagar och börjar på måndag", all(len(x) == 7 and x[0].weekday() == 0 for x in cg.month_grid(2026, 11)))
    ok = True
    for y in (2026, 2027, 2028):
        for m in range(1, 13):
            g = cg.month_grid(y, m)
            days = [d for wk in g for d in wk]
            ok &= all(b - a == timedelta(days=1) for a, b in zip(days, days[1:]))
            ok &= date(y, m, 1) in days and (date(y, m + 1, 1) - timedelta(days=1) if m < 12 else date(y, 12, 31)) in days
            ok &= 4 <= len(g) <= 6
    check("alla månader 2026–2028: sammanhängande, hela månaden med, 4–6 rader", ok)
    check("shift_month över årsskiftet", cg.shift_month(2026, 12, 1) == (2027, 1) and cg.shift_month(2026, 1, -1) == (2025, 12) and cg.shift_month(2026, 5, 14) == (2027, 7))
    check("månadstitel på svenska", cg.month_title(2026, 11) == "november 2026" and cg.month_title(2026, 3) == "mars 2026")
    check("heat-nivåer", [cg.heat(n) for n in (0, 1, 2, 3, 4, 5, 6, 20)] == [0, 1, 2, 2, 3, 3, 4, 4])
    T = lambda id, due=None, **k: dict({"id": id, "title": id, "due_date": due}, **k)  # noqa: E731
    by = cg.tasks_by_day([
        T("a", "2026-11-20"), T("b", "2026-11-20", priority="high"), T("c", "2026-11-20T09:30:00"),
        T("d", "2026-11-21", done=True), T("e", None), T("f", "skräp"),
        T("g", "2026-11-25", remind_dates=["2026-11-20", "2026-11-25", "2026-12-01"]), "inte en dict", None,
    ])
    d20 = by[date(2026, 11, 20)]
    check("tre förfallna + en påminnelse 20/11", len(d20) == 4 and sum(1 for e in d20 if e["kind"] == "due") == 3)
    check("klara uppgifter räknas inte", date(2026, 11, 21) not in by)
    check("uppgift utan/med ogiltigt datum syns inte", not any(e["task"]["id"] in ("e", "f") for lst in by.values() for e in lst))
    check("datum med klockslag tolkas", any(e["task"]["id"] == "c" for e in d20))
    check("förfallodag + samma påminnelsedag räknas EN gång", sum(1 for e in by[date(2026, 11, 25)] if e["task"]["id"] == "g") == 1)
    check("påminnelse 1/12 finns som 'remind'", by[date(2026, 12, 1)][0]["kind"] == "remind")
    check("sortering: förfall före påminnelse, hög prio först", d20[0]["task"]["id"] == "b" and d20[-1]["kind"] == "remind", [e["task"]["id"] for e in d20])
    check("include_remind=False", date(2026, 12, 1) not in cg.tasks_by_day([T("g", "2026-11-25", remind_dates=["2026-12-01"])], include_remind=False))
    check("include_done=True", date(2026, 11, 21) in cg.tasks_by_day([T("d", "2026-11-21", done=True)], include_done=True))
    check("busiest = 20/11 med 4", cg.busiest(by, 2026, 11) == (date(2026, 11, 20), 4))
    check("busiest tom månad = None", cg.busiest(by, 2026, 3) is None)
    check("month_total november", cg.month_total(by, 2026, 11) == 5, cg.month_total(by, 2026, 11))
    check("röd dag: juldagen + söndag, inte lördag", cg.day_info(date(2026, 12, 25))["red"] and cg.day_info(date(2026, 11, 8))["red"] and not cg.day_info(date(2026, 11, 7))["red"])
    check("helgdagsnamn", cg.day_info(date(2026, 12, 25))["holiday"] == "Juldagen")
    check("ISO-vecka", cg.iso_week(date(2026, 11, 5)) == 45)
    check("modulen har ingen Qt-import", "PySide" not in (ROOT / "core/calendar_grid.py").read_text(encoding="utf-8"))

    # --- läsbarhet: alla textfärger mot alla cellnivåer, båda teman, som i ui_readability_test:
    # mot mellangrå bakgrund alltid ≥ 4,5:1; mot värsta bakgrund 4,5 (opak) / 4,0 (standard 0,85) / 3,0 (lägre)
    from ui import calendar_view as cv
    import widget as W
    GLASS_DARK, GLASS_LIGHT = W.GLASS_DARK, W.GLASS_LIGHT

    def worst(tokens, heat, red, factor, backdrop):
        t = W._tokens_with_transparency(tokens, factor)
        out = {"fg": 99.0, "muted": 99.0, "röd": 99.0}
        for pk in ("bg_top", "bg_bottom"):
            p = _rgba(t[pk])
            panel = _blend((p[0], p[1], p[2], p[3]), backdrop)
            for lvl in (0, 1, 2, 3, 4):
                cell = _blend(_rgba(heat[lvl]), panel) if lvl else _blend(_rgba(t["surface"]), panel)
                for label, col in (("fg", t["fg"]), ("muted", t["muted"]), ("röd", red)):
                    if label == "muted" and lvl:
                        continue  # muted används bara för grannmånadens dagar (får aldrig färgton)
                    out[label] = min(out[label], tc.contrast(_hex(cell), _hex(_rgba(col)[:3])))
        return out

    for name, tok, heat, red, extreme in (("mörkt", GLASS_DARK, cv.HEAT_DARK, cv.RED_TEXT_DARK, (255, 255, 255)),
                                          ("ljust", GLASS_LIGHT, cv.HEAT_LIGHT, cv.RED_TEXT_LIGHT, (0, 0, 0))):
        for f in (1.0, 0.85, 0.70, 0.0):
            mid = worst(tok, heat, red, f, (128, 128, 128))
            ext = worst(tok, heat, red, f, extreme)
            lim = 4.5 if f in (1.0, 0.0) else (4.0 if f >= 0.85 else 3.0)
            for label in ("fg", "muted", "röd"):
                check(f"kalendern {name}, transparens {f}: {label}-text ≥ 4,5:1 mot mellangrå", mid[label] >= 4.5, round(mid[label], 2))
                check(f"kalendern {name}, transparens {f}: {label}-text ≥ {lim}:1 mot värsta bakgrund", ext[label] >= lim, round(ext[label], 2))
    # kraftigt färgstreck längst ner: grafik ska ha ≥ 3:1 mot panelen (WCAG 1.4.11) i båda teman
    for name, tok, bars in (("mörkt", GLASS_DARK, cv.HEAT_BAR_DARK), ("ljust", GLASS_LIGHT, cv.HEAT_BAR_LIGHT)):
        for lvl, bar in bars.items():
            base = _blend(_rgba(tok["bg_bottom"])[:3] + (1.0,), (0, 0, 0))
            check(f"färgstrecket nivå {lvl} syns mot panelen ({name}, ≥ 3:1)", tc.contrast(bar, _hex(base)) >= 3.0, round(tc.contrast(bar, _hex(base)), 2))
    css = cv.build_stylesheet(True, "#818cf8", "#eef1fb", "#cfd6ec", "rgba(0,0,0,0.2)", "rgba(0,0,0,0.3)")
    check("stapeln ligger sist i QSS (slår igen idag/vald-ramarna)", css.rstrip().splitlines()[-1].startswith('QPushButton[calCell="true"][heat="4"]') and "border-bottom: 5px" in css)
    sel = cv.build_stylesheet(True, "#818cf8", "#eef1fb", "#cfd6ec", "rgba(0,0,0,0.2)", "rgba(0,0,0,0.3)")
    check("vald dagslistrad får text med kontrast mot accenten", tc.contrast("#818cf8", tc.text_color_for("#818cf8")) >= 4.5 and "calDayList::item:selected" in sel)
    check("alla textstorlekar i kalender-QSS ≥ 11 px", all(int(x) >= 11 for x in __import__("re").findall(r"font-size: (\d+)px", sel)))


def child() -> None:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QInputDialog, QVBoxLayout, QWidget
    app = QApplication([])
    from core.settings import Settings
    from core.store import TaskStore
    import widget as W
    from ui.calendar_view import CalendarView

    res: list = []

    def ck(name, cond, extra=""):
        res.append((name + (f" {extra}" if not cond and extra else ""), bool(cond)))

    tmp = tempfile.mkdtemp(prefix="ledgebord_cal_")
    today = date(2026, 11, 5)
    tasks = [
        {"id": "a", "title": "Faktura Anders", "due_date": "2026-11-20", "priority": "high"},
        {"id": "b", "title": "Limo Bertil", "due_date": "2026-11-20", "priority": "low"},
        {"id": "c", "title": "Bilstereo", "due_date": "2026-11-20"},
        {"id": "d", "title": "Gammal", "due_date": "2026-11-02"},
        {"id": "e", "title": "Mailpåminnelse", "due_date": "2026-11-30", "remind_dates": ["2026-11-20"]},
        {"id": "f", "title": "December", "due_date": "2026-12-24"},
        {"id": "g", "title": "Idag", "due_date": "2026-11-05"},
    ]
    v = CalendarView()
    v.resize(430, 640)
    v.show()
    v.show_month(2026, 11)
    v._today = today
    v.set_tasks(tasks, today=today)
    v.select_date(date(2026, 11, 20))
    app.processEvents()
    ck("titeln visar månad och år", v.title.text() == "november 2026")
    i = v.cell_info(date(2026, 11, 20))
    ck("20/11: 4 poster (3 förfall + 1 påminnelse), nivå 3", i["count"] == 4 and i["due"] == 3 and i["heat"] == 3, i)
    ck("5/11: idag", v.cell_info(date(2026, 11, 5))["today"] and not v.cell_info(date(2026, 11, 6))["today"])
    ck("2/11: förfallen dag med öppen uppgift", v.cell_info(date(2026, 11, 2))["overdue"] and not v.cell_info(date(2026, 11, 20))["overdue"])
    ck("25/12 är röd dag med namn (dec ligger utanför, men info räknas)", v.cell_info(date(2026, 12, 25))["red"])
    ck("dagar från grannmånad markeras", v.cell_info(date(2026, 10, 30))["other"] and not v.cell_info(date(2026, 11, 30))["other"])
    cell = v._cells[date(2026, 11, 20)]
    ck("cellen visar dagens nummer och antal som text", "20" in cell.text() and "4 st" in cell.text(), cell.text())
    ck("cellens egenskaper: heat=3, vald", cell.property("heat") == "3" and cell.property("selected") is True)
    ck("tom dag visar bara numret", v._cells[date(2026, 11, 10)].text().strip() == "10")
    ck("söndag har röd siffra (redDay)", v._cells[date(2026, 11, 8)].property("redDay") is True)
    ck("vardag är inte röd", v._cells[date(2026, 11, 10)].property("redDay") is False)
    ck("verktygstips listar uppgifterna", "Faktura Anders" in cell.toolTip() and "Limo Bertil" in cell.toolTip() and "🔔" in cell.toolTip())
    ck("tillgängligt namn säger antal", "4 uppgifter" in cell.accessibleName())
    ck("dagslistan har 4 rader, hög prio först", v.day_list.count() == 4 and "Faktura Anders" in v.day_list.item(0).text(), [v.day_list.item(k).text() for k in range(v.day_list.count())])
    ck("påminnelsen är markerad", "påminnelse" in v.day_list.item(3).text())
    ck("dagsrubriken säger veckodag + datum + antal", "fredag 20 november" in v.day_title.text() and "4 uppgifter" in v.day_title.text(), v.day_title.text())
    ck("sammanfattning: tyngsta dagen", "tyngsta dagen" in v.summary.text() and "20/11" in v.summary.text() and "(4 st)" in v.summary.text(), v.summary.text())
    # klick
    v._cell_buttons[2 * 7 + 3].click()  # rad 2, torsdag
    sel = v.selected_date()
    ck("klick väljer dagen", sel == v._cells and False or sel == cg_date(v, 2, 3), sel)
    v.select_date(date(2026, 11, 20))
    # signaler
    got: list = []
    v.task_activated.connect(got.append)
    v.day_list.itemDoubleClicked.emit(v.day_list.item(0))
    ck("dubbelklick på uppgift skickar id", got == ["a"], got)
    adds: list = []
    v.add_requested.connect(adds.append)
    v.add_btn.click()
    ck("➕ skickar vald dag som ISO", adds == ["2026-11-20"])
    # navigering
    v.step_month(1)
    ck("nästa månad: december, 24/12 syns", v.title.text() == "december 2026" and v.cell_info(date(2026, 12, 24))["count"] == 1 and v.month() == (2026, 12))
    ck("valt datum följer med till nya månaden", v.selected_date().month == 12)
    v.step_month(-2)
    ck("två tillbaka: oktober", v.title.text() == "oktober 2026")
    v.show_month(2027, 2)
    ck("feb 2027: 4 rader synliga, rad 5–6 dolda", v._cell_buttons[3 * 7].isVisible() and not v._cell_buttons[4 * 7].isVisible() and not v._week_labels[5].isVisible())
    ck("tom månad: tydlig text", "Inga uppgifter" in v.summary.text())
    v.show_month(2026, 11)
    ck("nov 2026: 6 rader synliga", v._cell_buttons[5 * 7].isVisible() and v._week_labels[5].isVisible())
    ck("veckonummer visas", v._week_labels[0].text() == "44", v._week_labels[0].text())
    v.go_today()
    ck("Idag hoppar till dagens månad", v.selected_date() == date.today() and v.month() == (date.today().year, date.today().month))
    v.set_tasks([])
    ck("inga uppgifter: ingen krasch, tom lista", v.day_list.count() == 0 and "inga uppgifter" in v.day_title.text())
    ck("knappar har tillgängliga namn", bool(v.prev_btn.accessibleName()) and bool(v.next_btn.accessibleName()))

    # --- fönstret ---
    settings = Settings(str(Path(tmp) / "settings.json"))
    store = TaskStore(data_dir_override=Path(tmp) / "data")
    t_due = (date.today() + timedelta(days=3)).isoformat()
    ta = store.add_task("Kalenderuppgift", due_date=t_due)
    tb = store.add_task("Utan datum")
    shell = QWidget()
    w = W.TodoWidget(app.primaryScreen(), store, settings, win_id="t", parent=shell)
    lay = QVBoxLayout(shell)
    lay.addWidget(w)
    w._shell = shell
    shell.resize(460, 640)
    shell.show()
    app.processEvents()
    w._rebuild_task_list()
    ck("tre flikar: Aktiva, Arkiverade, Kalender", w.tabs.count() == 3 and "Kalender" in w.tabs.tabText(2))
    ck("Arkiverade-flikens räknare fungerar fortfarande på index 1", (w._update_archive_tab_count(3), w.tabs.tabText(1))[1].startswith("Arkiverade"))
    ck("kalenderfliken ritas inte medan den är dold (smutsflagga)", getattr(w, "_calendar_dirty", False) is True)
    w.tabs.setCurrentIndex(2)
    app.processEvents()
    d3 = date.fromisoformat(t_due)
    w.calendar_view.select_date(d3)
    ck("öppnad flik visar uppgiften på rätt dag", w.calendar_view.cell_info(d3)["count"] == 1 and w.calendar_view.day_list.count() == 1)
    ck("uppgift utan datum ger ingen post", sum(len(x) for x in w.calendar_view._by_day.values()) == 1)
    t2 = store.add_task("Ny samma dag", due_date=t_due)
    w._rebuild_task_list()
    ck("kalendern följer med när listan ändras medan den syns", w.calendar_view.cell_info(d3)["count"] == 2)
    # dubbelklick → Aktiva
    w.calendar_view.task_activated.emit(ta)
    app.processEvents()
    ck("dubbelklick byter till Aktiva och markerar uppgiften", w.tabs.currentIndex() == 0 and w._sel_tid == ta and w._nav_active, (w.tabs.currentIndex(), w._sel_tid))
    # ➕ ny uppgift
    orig = QInputDialog.getText
    QInputDialog.getText = staticmethod(lambda *a, **k: ("Skapad i kalendern", True))
    try:
        w._on_calendar_add("2027-01-15")
    finally:
        QInputDialog.getText = orig
    made = [t for t in store.active_tasks() if t["title"] == "Skapad i kalendern"]
    ck("➕ skapar uppgift med dagen som förfallodatum", len(made) == 1 and made[0]["due_date"] == "2027-01-15")
    # tema
    ss = w.calendar_view.styleSheet()
    ck("kalendern har egen QSS efter _apply_theme", "calCell" in ss and "QListWidget#calDayList" in ss)
    for dark in (False, True):
        settings.set_theme("dark" if dark else "light")
        w._apply_theme()
        ss = w.calendar_view.styleSheet()
        from ui import calendar_view as cvm
        want = cvm.RED_TEXT_DARK if dark else cvm.RED_TEXT_LIGHT
        ck(f"temabyte ({'mörkt' if dark else 'ljust'}) uppdaterar kalenderns färger", want in ss, ss[:120])
    # taggfärg ritar om (anropas via signalen)
    ck("taggfärgsändring uppdaterar kalendern utan fel", w._on_tag_colors_changed({}) is None)
    _finish_child(res, tmp)


def cg_date(v, r, c):
    return cg.month_grid(*v.month())[r][c]


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
    _run_parent("calendar_view_test")
    print(f"\ncalendar_view_test: {_ok} lyckades, {_fail} misslyckades")
    sys.exit(1 if _fail else 0)
