#!/usr/bin/env python3
"""
payment_plan_test.py — delbetalningsplan: datum (månadsklämning, helg/röda dagar), belopp i ören, titlar, dialog.

Kör:  python tester/payment_plan_test.py
Ren logik (core/payment_plan.py) körs direkt; dialogen och menyvägarna i en Qt-barnprocess.
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

from datetime import date  # noqa: E402

from core import holidays_se  # noqa: E402
from core import payment_plan as pp  # noqa: E402

NB = "\u00a0"


def pure() -> None:
    d = date
    # --- månadssteg med klämning ---
    check("31 jan + 1 mån = 28 feb (2026)", pp.add_months(d(2026, 1, 31), 1) == d(2026, 2, 28))
    check("31 jan + 1 mån = 29 feb (skottår 2028)", pp.add_months(d(2028, 1, 31), 1) == d(2028, 2, 29))
    check("31 jan + 2 mån = 31 mars", pp.add_months(d(2026, 1, 31), 2) == d(2026, 3, 31))
    check("31 mars + 1 mån = 30 april", pp.add_months(d(2026, 3, 31), 1) == d(2026, 4, 30))
    check("årsskifte: 15 dec + 2 mån = 15 feb", pp.add_months(d(2026, 12, 15), 2) == d(2027, 2, 15))
    check("12 månader = samma dag nästa år", pp.add_months(d(2026, 5, 17), 12) == d(2027, 5, 17))
    plan = pp.plan_dates(d(2026, 1, 31), 5, "month", "none")
    check("månadsplan från 31:a driver inte (31/1, 28/2, 31/3, 30/4, 31/5)",
          plan == [d(2026, 1, 31), d(2026, 2, 28), d(2026, 3, 31), d(2026, 4, 30), d(2026, 5, 31)], plan)
    check("varannan vecka = 14 dagar", pp.plan_dates(d(2026, 11, 6), 3, "biweekly", "none") == [d(2026, 11, 6), d(2026, 11, 20), d(2026, 12, 4)])
    check("varje vecka = 7 dagar", pp.plan_dates(d(2026, 11, 6), 3, "weekly", "none") == [d(2026, 11, 6), d(2026, 11, 13), d(2026, 11, 20)])
    check("varannan månad", pp.plan_dates(d(2026, 1, 15), 3, "month2", "none") == [d(2026, 1, 15), d(2026, 3, 15), d(2026, 5, 15)])
    check("var tredje månad", pp.plan_dates(d(2026, 1, 15), 3, "month3", "none")[2] == d(2026, 7, 15))
    check("okänt intervall = månad", pp.plan_dates(d(2026, 1, 15), 2, "???", "none")[1] == d(2026, 2, 15))
    # --- vardag ---
    sat, sun, mon, fri = d(2026, 11, 7), d(2026, 11, 8), d(2026, 11, 9), d(2026, 11, 6)
    check("fredag/måndag är vardagar", pp.is_workday(fri) and pp.is_workday(mon))
    check("lördag/söndag är inte vardagar", not pp.is_workday(sat) and not pp.is_workday(sun))
    check("nearest: lördag → fredag, söndag → måndag", pp.shift_to_workday(sat) == fri and pp.shift_to_workday(sun) == mon)
    check("next: lördag → måndag", pp.shift_to_workday(sat, "next") == mon)
    check("prev: söndag → fredag", pp.shift_to_workday(sun, "prev") == fri)
    check("none: lämnas", pp.shift_to_workday(sat, "none") == sat)
    check("vardag lämnas oförändrad i alla lägen", all(pp.shift_to_workday(fri, m) == fri for m in pp.SHIFT_MODES))
    # röda dagar: midsommarafton 2026-06-19 (fredag), Kristi himmelsfärd 2026-05-14 (torsdag)
    check("testets antagande: 14 maj 2026 är röd dag", holidays_se.holiday_on(d(2026, 5, 14)) is not None)
    check("röd dag på vardag flyttas (nearest → onsdag 13/5)", pp.shift_to_workday(d(2026, 5, 14)) == d(2026, 5, 13))
    check("röd dag next → fredag 15/5", pp.shift_to_workday(d(2026, 5, 14), "next") == d(2026, 5, 15))
    check("påsk 2026: långfredag 3/4 nearest → torsdag 2/4", pp.shift_to_workday(d(2026, 4, 3)) == d(2026, 4, 2))
    check("annandag påsk 6/4 next → tisdag 7/4", pp.shift_to_workday(d(2026, 4, 6), "next") == d(2026, 4, 7))
    check("julafton 24/12 räknas som ledig → 23/12", pp.shift_to_workday(d(2026, 12, 24)) == d(2026, 12, 23))
    all_ok = True
    for y in (2025, 2026, 2027, 2028):
        for k in range(366):
            x = d(y, 1, 1).fromordinal(d(y, 1, 1).toordinal() + k)
            for m in ("nearest", "next", "prev"):
                if not pp.is_workday(pp.shift_to_workday(x, m)):
                    all_ok = False
    check("ALLA dagar 2025–2028 landar på en vardag i alla lägen", all_ok)
    far = max(abs((pp.shift_to_workday(d(2026, 1, 1) .fromordinal(d(2026, 1, 1).toordinal() + k), "nearest") - d(2026, 1, 1).fromordinal(d(2026, 1, 1).toordinal() + k)).days) for k in range(365))
    check("flytten är högst 4 dagar", far <= 4, far)
    dates = pp.plan_dates(d(2026, 1, 3), 12, "month", "nearest")
    check("planens datum är strikt stigande", all(a < b for a, b in zip(dates, dates[1:])))
    check("och alla vardagar", all(pp.is_workday(x) for x in dates))

    # --- belopp ---
    P = pp.parse_amount
    check("12 000 kr", P("12 000 kr") == 1200000)
    check("hårt mellanslag + kr", P(f"12{NB}000{NB}kr") == 1200000)
    check("12000", P("12000") == 1200000)
    check("12000,50", P("12000,50") == 1200050)
    check("12.000,50 (punkt som tusenavgränsare)", P("12.000,50") == 1200050)
    check("12,000.50 (engelskt)", P("12,000.50") == 1200050)
    check("12.000 = tolvtusen", P("12.000") == 1200000)
    check("1.234.567", P("1.234.567") == 123456700)
    check("99,5 = 99 kr 50 öre", P("99,5") == 9950)
    check("1 234.5", P("1 234.5") == 123450)
    check("12 000:-", P("12 000:-") == 1200000)
    check("tomt/ogiltigt/noll/negativt → None", all(P(v) is None for v in ("", "abc", "0", "-5", "12 kr kr x", None, "1e5")))
    check("orimligt stort → None", P("99999999999999") is None)
    F = pp.format_amount
    check("format 4000 kr", F(400000) == f"4{NB}000{NB}kr")
    check("format med ören", F(400050) == f"4{NB}000,50{NB}kr")
    check("format miljon", F(123456789) == f"1{NB}234{NB}567,89{NB}kr")
    check("format under tusen", F(9950) == f"99,50{NB}kr")
    S = pp.split_amounts
    check("10 000 / 3: summan exakt, resten på sista", S(1000000, 3) == [333333, 333333, 333334] and sum(S(1000000, 3)) == 1000000)
    check("jämn delning", S(1200000, 4) == [300000] * 4)
    check("handpenning: del 1 = handpenning, resten delas", S(1000000, 3, 400000) == [400000, 300000, 300000])
    check("handpenning med rest", S(1000001, 3, 400000) == [400000, 300000, 300001])
    check("handpenning ≥ total ignoreras", S(1000000, 3, 1000000) == [333333, 333333, 333334])
    check("summan stämmer alltid (slumpad)", all(sum(S(t, n, dp)) == t for t, n, dp in
          [(1234567, 7, 0), (99999, 2, 50000), (5, 3, 0), (100, 2, 1), (10 ** 9 + 7, 60, 12345)]))
    check("inga negativa delar", all(x >= 0 for x in S(5, 3)))
    check("ogiltigt → tom", S(0, 3) == [] and S(100, 0) == [])

    # --- titel och plan ---
    check("titel utan belopp", pp.part_title("Limo Anders", 1, 3) == "Limo Anders — del 1 av 3")
    check("titel med belopp", pp.part_title("Limo", 2, 3, 400000) == f"Limo — del 2 av 3 (4{NB}000{NB}kr)")
    plan = pp.build_plan("Limo Anders", d(2026, 11, 20), 3, "month", "nearest", 1200000)
    check("plan: 3 delar", len(plan) == 3)
    check("plan: titlar med belopp", plan[0]["title"] == f"Limo Anders — del 1 av 3 (4{NB}000{NB}kr)" and plan[2]["title"].endswith(f"(4{NB}000{NB}kr)"))
    check("plan: datum som ISO", [p["due_date"] for p in plan] == ["2026-11-20", "2026-12-21", "2027-01-20"], [p["due_date"] for p in plan])
    check("plan: beloppen summerar till totalen", sum(p["amount_cents"] for p in plan) == 1200000)
    plan = pp.build_plan("Bilstereo", d(2026, 11, 20), 2, total_cents=None)
    check("plan utan belopp: ingen parentes", plan[0]["title"] == "Bilstereo — del 1 av 2" and plan[0]["amount_cents"] is None)
    check("tom rubrik → ingen plan", pp.build_plan("   ", d(2026, 11, 20), 3) == [])
    check("1 del eller 61 delar → ingen plan", pp.build_plan("x", d(2026, 11, 20), 1) == [] and pp.build_plan("x", d(2026, 11, 20), 61) == [])
    check("60 delar går", len(pp.build_plan("x", d(2026, 11, 20), 60, "weekly")) == 60)
    long_plan = pp.build_plan("A" * 900, d(2026, 11, 20), 12, total_cents=1200000)
    check("lång rubrik kortas så suffixet får plats (≤ 500 tecken)", all(len(p["title"]) <= 500 and "del" in p["title"][-30:] for p in long_plan), [len(p["title"]) for p in long_plan][:3])
    check("blanksteg i rubriken normaliseras", pp.build_plan("  Limo   Anders ", d(2026, 11, 20), 2)[0]["title"].startswith("Limo Anders — del"))
    check("base_title tar bort suffixet", pp.base_title(f"Limo — del 2 av 3 (4{NB}000{NB}kr)") == "Limo" and pp.base_title("Faktura 5") == "Faktura 5" and pp.base_title("A - del 1 av 2") == "A")
    check("parse_tags", pp.parse_tags("Delbetalning, #Limo  limo; x") == ["delbetalning", "limo", "x"] and pp.parse_tags("") == [])
    check("max 5 taggar", len(pp.parse_tags("a b c d e f g")) == 5)
    check("modulen har ingen Qt-import", "PySide" not in (ROOT / "core/payment_plan.py").read_text(encoding="utf-8"))
    check("standardtagg", pp.DEFAULT_TAG == "delbetalning" and pp.DEFAULT_SHIFT == "nearest")


def child() -> None:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import QDate
    from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
    app = QApplication([])
    from core.settings import Settings
    from core.store import TaskStore
    import widget as W
    from ui.payment_plan_dialog import PaymentPlanDialog

    res: list = []

    def ck(name, cond, extra=""):
        res.append((name + (f" {extra}" if not cond and extra else ""), bool(cond)))

    tmp = tempfile.mkdtemp(prefix="ledgebord_plan_")
    store = TaskStore(data_dir_override=Path(tmp) / "data")
    dlg = PaymentPlanDialog(None, store, "")
    ck("knappen är avstängd utan rubrik", not dlg.ok_btn.isEnabled() and dlg.plan() == [])
    ck("standardtagg är delbetalning", dlg.f_tags.text() == "delbetalning")
    ck("standard: 3 delar, månadsvis, närmaste vardag", dlg.f_parts.value() == 3 and dlg.f_interval.currentData() == "month" and dlg.f_shift.currentData() == "nearest")
    dlg.f_title.setText("Limo Anders")
    dlg.f_total.setText("12 000")
    dlg.f_first.setDate(QDate(2026, 11, 20))
    ck("förhandsvisning: 3 rader", dlg.preview.count() == 3 and len(dlg.plan()) == 3, dlg.preview.count())
    ck("knappen visar antal", dlg.ok_btn.isEnabled() and "3" in dlg.ok_btn.text())
    ck("förhandsvisningen visar veckodag + titel", "fre 20/11 2026" in dlg.preview.item(0).text() and "del 1 av 3" in dlg.preview.item(0).text(), dlg.preview.item(0).text())
    dlg.f_parts.setValue(4)
    ck("ändrat antal uppdaterar direkt", len(dlg.plan()) == 4 and dlg.preview.count() == 4)
    dlg.f_interval.setCurrentIndex(dlg.f_interval.findData("weekly"))
    ck("ändrat intervall uppdaterar direkt", dlg.plan()[1]["due_date"] == "2026-11-27", dlg.plan()[1])
    dlg.f_total.setText("abc")
    ck("ogiltigt belopp: varning, ingen plan, knapp av", dlg.plan() == [] and "tolkas" in dlg.warn.text() and not dlg.ok_btn.isEnabled())
    dlg.f_total.setText("")
    ck("tomt belopp är tillåtet", len(dlg.plan()) == 4 and "(" not in dlg.plan()[0]["title"])
    dlg.f_down.setText("500")
    ck("handpenning utan total → varning", dlg.plan() == [] and "totalbelopp" in dlg.warn.text())
    dlg.f_total.setText("500")
    ck("handpenning ≥ total → varning", dlg.plan() == [] and "mindre" in dlg.warn.text())
    dlg.f_total.setText("1 000")
    dlg.f_down.setText("400")
    ck("handpenning ger olika belopp", len(dlg.plan()) == 4 and dlg.plan()[0]["amount_cents"] == 40000 and dlg.plan()[1]["amount_cents"] == 20000, [p["amount_cents"] for p in dlg.plan()])
    dlg.f_down.setText("")
    dlg.f_total.setText("12 000")
    dlg.f_parts.setValue(3)
    dlg.f_interval.setCurrentIndex(dlg.f_interval.findData("month"))
    dlg.f_prio.setCurrentIndex(dlg.f_prio.findData("high"))
    dlg.f_tags.setText("Delbetalning, limo")
    n0 = len(store.active_tasks())
    dlg._accept()
    tasks = store.active_tasks()
    new = [t for t in tasks if "del" in t["title"] and "av 3" in t["title"]]
    ck("3 uppgifter skapades", len(tasks) - n0 == 3 and len(new) == 3 and len(dlg.created) == 3, [t["title"] for t in tasks])
    ck("titlarna har del N av 3 + belopp", sorted(t["title"] for t in new)[0].startswith("Limo Anders — del 1 av 3 (4") and "kr)" in new[0]["title"])
    ck("förfallodatum satta", sorted(t["due_date"] for t in new) == ["2026-11-20", "2026-12-21", "2027-01-20"], [t["due_date"] for t in new])
    ck("taggar satta (gemener)", all(t["tags"] == ["delbetalning", "limo"] for t in new), [t["tags"] for t in new])
    ck("prioritet satt", all(t["priority"] == "high" for t in new))
    ck("alla är aktiva, ej klara", all(not t["done"] for t in new))

    # --- fönstret: menyvägar + kalendern ser dem ---
    settings = Settings(str(Path(tmp) / "settings.json"))
    shell = QWidget()
    w = W.TodoWidget(app.primaryScreen(), store, settings, win_id="t", parent=shell)
    lay = QVBoxLayout(shell)
    lay.addWidget(w)
    w._shell = shell
    shell.resize(460, 560)
    shell.show()
    app.processEvents()
    w._rebuild_task_list()
    ck("fönstret har _on_open_payment_plan", hasattr(w, "_on_open_payment_plan") and hasattr(w, "_on_open_tag_colors"))
    wsrc = (ROOT / "ui/widget_parts/window_ops.py").read_text(encoding="utf-8")
    ck("fönstermenyn har 'Delbetalningsplan…'", "💸 Delbetalningsplan…" in wsrc and "_on_open_payment_plan()" in wsrc)
    msrc = (ROOT / "ui/widget_parts/task_menu.py").read_text(encoding="utf-8")
    ck("uppgiftsmenyn har 'Delbetalningsplan från den här…' (fylls i från titeln)", "Delbetalningsplan från den här" in msrc and "_plan_base_title" in msrc)
    tsrc = (ROOT / "app/mixins/tray.py").read_text(encoding="utf-8")
    ck("tray-menyn har 'Delbetalningsplan…'", "_open_payment_plan" in tsrc and "💸" in tsrc)
    asrc = (ROOT / "app/mixins/exports.py").read_text(encoding="utf-8")
    ck("kontrollern har _open_payment_plan", "def _open_payment_plan" in asrc)
    dlg2 = PaymentPlanDialog(None, store, "Limo Anders")
    ck("dialogen kan förifyllas med rubrik", dlg2.f_title.text() == "Limo Anders" and len(dlg2.plan()) == 3)
    # full butik
    class Full:
        calls = 0
        def add_task(self, *a, **k):
            Full.calls += 1
            return f"id{Full.calls}" if Full.calls <= 2 else None
    ids = pp.create_tasks(Full(), pp.build_plan("X", date(2026, 1, 1), 4), "none", [])
    ck("create_tasks stannar när butiken är full", len(ids) == 2)
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
    from datetime import date  # noqa: E402,F811
    from core import payment_plan as pp  # noqa: E402,F811
    child()
else:
    pure()
    _run_parent("payment_plan_test")
    print(f"\npayment_plan_test: {_ok} lyckades, {_fail} misslyckades")
    sys.exit(1 if _fail else 0)
