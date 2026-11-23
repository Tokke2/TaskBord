#!/usr/bin/env python3
"""
job_templates_test.py — jobbmallar: logik (core/job_templates.py), dialogerna och den automatiska
Google Calendar-exporten (med falsk Google-tjänst — inget nätverk).

Kör:  python tester/job_templates_test.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from datetime import date
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
    from core import google_calendar as gcal
    from core import job_templates as jt
    from core.store import TaskStore

    tmp = Path(tempfile.mkdtemp(prefix="ledgebord_mall_"))
    # --- startmallar och filen ------------------------------------------------------------------------------------
    d = jt.default_templates()
    check("två startmallar, Limojobb först", len(d) == 2 and d[0]["name"] == "Limojobb" and len(d[0]["steps"]) == 4)
    check("startmallarna är giltiga och oförändrade av coerce", [jt.coerce_template(t) for t in d] == d)
    check("ingen fil → startmallar (utan att skapa filen)", jt.load_templates(tmp) == d and not jt.templates_path(tmp).exists())
    check("spara → fil i datamappen", jt.save_templates(tmp, d) and jt.templates_path(tmp).exists()
          and jt.templates_path(tmp).parent == tmp)
    check("spara → läsa ger samma", jt.load_templates(tmp) == d)
    check("ingen .tmp-fil kvar", not list(tmp.glob("*.tmp")))
    jt.save_templates(tmp, [])
    check("tom lista sparas och ger INTE startmallarna igen", jt.load_templates(tmp) == [])
    jt.templates_path(tmp).write_text("{trasig", encoding="utf-8")
    check("trasig fil → startmallar", jt.load_templates(tmp) == d)
    jt.templates_path(tmp).write_text(json.dumps({"templates": "nej"}), encoding="utf-8")
    check("fel format → startmallar", jt.load_templates(tmp) == d)

    # --- rensning --------------------------------------------------------------------------------------------------
    s = jt.coerce_step({"title": "  Faktura   {kund} ", "days": "7", "priority": "hög", "tags": "Faktura, #Limo,faktura",
                        "amount_cents": 500000, "workday": 1})
    check("steg: blanksteg städas, prio okänd → none, taggar rensas", s["title"] == "Faktura {kund}" and s["priority"] == "none"
          and s["tags"] == ["faktura", "limo"] and s["days"] == 7 and s["workday"] is True and s["amount_cents"] == 500000)
    check("steg utan titel kasseras", jt.coerce_step({"title": "  ", "days": 1}) is None and jt.coerce_step("x") is None)
    check("dagar klipps till −365…3650", jt.coerce_step({"title": "a", "days": -9999})["days"] == -365
          and jt.coerce_step({"title": "a", "days": 99999})["days"] == 3650 and jt.coerce_step({"title": "a", "days": "x"})["days"] == 0)
    check("negativt/skumt belopp → 0", jt.coerce_step({"title": "a", "amount_cents": -5})["amount_cents"] == 0
          and jt.coerce_step({"title": "a", "amount_cents": True})["amount_cents"] == 0
          and jt.coerce_step({"title": "a", "amount_cents": "5"})["amount_cents"] == 0)
    t = jt.coerce_template({"name": "x" * 200, "steps": [{"title": f"s{i}"} for i in range(80)], "gcal": 1})
    check("mall: namn ≤ 60, max 30 steg, gcal bool", len(t["name"]) == 60 and len(t["steps"]) == 30 and t["gcal"] is True)
    check("mall utan namn kasseras", jt.coerce_template({"name": " ", "steps": []}) is None and jt.coerce_template(5) is None)
    check("mall: id saneras/skapas", len(jt.coerce_template({"name": "a"})["id"]) == 8
          and jt.coerce_template({"name": "a", "id": "../x y"})["id"] == "xy")
    check("namn: unique_name / duplicate_name", jt.unique_name(d, "Limojobb") == "Limojobb 2" and jt.unique_name(d, "Ny") == "Ny"
          and jt.duplicate_name(d, "Limojobb") == "Limojobb (kopia)")
    jt.save_templates(tmp, [{"name": "A", "id": "same", "steps": []}, {"name": "B", "id": "same", "steps": []}])
    check("dubbla id:n i filen → bara första", [x["name"] for x in jt.load_templates(tmp)] == ["A"])

    # --- titlar ----------------------------------------------------------------------------------------------------
    check("{kund} ersätts", jt.render_title("Faktura — {kund}", "Anna") == "Faktura — Anna")
    check("utan namn försvinner platshållaren snyggt", jt.render_title("Faktura — {kund}", "") == "Faktura"
          and jt.render_title("{kund}: ring", " ") == ": ring" or jt.render_title("{kund}: ring", " ").strip(": ") == "ring")
    check("saknas platshållare läggs namnet efter", jt.render_title("Faktura", "Anna") == "Faktura — Anna" and jt.render_title("Faktura", "") == "Faktura")
    check("flera platshållare", jt.render_title("{kund} / {kund}", "A") == "A / A")

    # --- datum -----------------------------------------------------------------------------------------------------
    lj = d[0]
    items = jt.build_tasks(lj, date(2026, 11, 20), "Anna")      # fredag
    check("4 uppgifter, rätt titlar", [i["title"] for i in items] == ["Bekräfta bokning — Anna", "Utför jobbet — Anna",
                                                                          "Skicka faktura — Anna", "Bevaka betalning — Anna"])
    check("datum: −3, 0, +1 (lördag → måndag, 'bara vardag'), +31 (måndag)",
          [i["due_date"] for i in items] == ["2026-11-17", "2026-11-20", "2026-11-23", "2026-12-21"], [i["due_date"] for i in items])
    check("prio och taggar följer med", items[1]["priority"] == "high" and items[2]["tags"] == ["faktura"])
    tt = {"steps": [{"title": "a", "days": 0, "workday": False}]}
    check("utan 'bara vardag' stannar en söndag", jt.build_tasks(tt, date(2026, 11, 22))[0]["due_date"] == "2026-11-22")
    check("röd dag flyttas (juldagen → 28 dec)", jt.build_tasks({"steps": [{"title": "a", "days": 0, "workday": True}]},
                                                                 date(2026, 12, 25))[0]["due_date"] == "2026-12-28")
    check("mall utan steg → inget", jt.build_tasks({"steps": []}, date.today()) == [] and jt.build_tasks(None, date.today()) == [])

    # --- skapa i butiken --------------------------------------------------------------------------------------------
    store = TaskStore(data_dir_override=tmp / "store")
    items[1]["amount_cents"] = 1250000
    ids = jt.create_tasks(store, items)
    check("4 uppgifter skapade", len(ids) == 4 and len(store.active_tasks()) == 4)
    tk = store.find_task(ids[1])
    check("uppgiftens titel, datum, prio, belopp", tk["title"] == "Utför jobbet — Anna" and tk["due_date"] == "2026-11-20"
          and tk["priority"] == "high" and tk.get("amount_cents") == 1250000, tk)
    check("taggar sparade", store.find_task(ids[2])["tags"] == ["faktura"])

    # --- Google-export (falsk tjänst, inget nätverk) -----------------------------------------------------------------
    events = []
    calls = []

    class GErr(gcal.GoogleCalendarError):
        pass

    orig = (gcal.push_tasks, gcal.load_event_map, gcal.load_history)
    gcal.load_event_map = lambda dd: object()
    gcal.load_history = lambda dd: object()
    state = {"fail": 0, "partial": False}

    def fake_push(service, cid, tasks, em, color_by_priority=True, done_style="x", history=None):
        calls.append((cid, [t["title"] for t in tasks], color_by_priority, done_style))
        if state["fail"] > 0:
            state["fail"] -= 1
            raise gcal.GoogleCalendarError("Inget nät just nu", "timeout")
        if state["partial"]:
            state["partial"] = False
            return {"total": len(tasks), "skapade": len(tasks) - 1, "uppdaterade": 0, "hoppade": 0, "misslyckade": 1, "results": []}
        return {"total": len(tasks), "skapade": len(tasks), "uppdaterade": 0, "hoppade": 0, "misslyckade": 0, "results": []}

    gcal.push_tasks = fake_push
    opts = {"calendar_id": "primary", "color": False, "done_style": "strike"}
    naps = []
    kw = dict(notify=events.append, service_factory=lambda dd: object(), connected=lambda dd: True, sleep=naps.append)
    try:
        r = jt.export_worker(tmp, store.find_task, ids, opts, "Limojobb — Anna", **kw)
        check("export: alla fyra skickas med valen (kalender, färg, klar-stil)", r["ok"] and calls[-1] == ("primary", [store.find_task(i)["title"] for i in ids], False, "strike"), calls)
        check("export: tray-notis 'N uppgifter skickade'", events and events[-1]["ok"] and "4 uppgifter" in events[-1]["message"]
              and events[-1]["title"] == "Limojobb — Anna" and events[-1]["action"] == "mall", events)
        check("export: inget nätverk i första försöket → ingen väntan", naps == [])

        events.clear(); state["fail"] = 2; naps.clear(); calls.clear()
        r = jt.export_worker(tmp, store.find_task, ids, opts, "M", **kw)
        check("export: nätfel → försöker igen (30 s, 2 min) och lyckas", r["ok"] and len(calls) == 3 and naps == [30.0, 120.0] and events[-1]["ok"], (calls, naps))

        events.clear(); state["fail"] = 99; naps.clear(); calls.clear()
        r = jt.export_worker(tmp, store.find_task, ids, opts, "M", **kw)
        check("export: ger upp efter 4 försök med en tydlig notis", not r["ok"] and len(calls) == 4 and naps == [30.0, 120.0, 600.0]
              and not events[-1]["ok"] and "Kunde inte skicka" in events[-1]["message"], (calls, events))
        state["fail"] = 0

        events.clear(); state["partial"] = True; calls.clear(); naps.clear()
        r = jt.export_worker(tmp, store.find_task, ids, opts, "M", **kw)
        check("export: delvis misslyckat → nytt försök, sedan klart", r["ok"] and len(calls) == 2 and naps == [30.0], (calls, naps))

        events.clear(); calls.clear()
        kw2 = dict(kw, connected=lambda dd: False)
        r = jt.export_worker(tmp, store.find_task, ids, opts, "M", **kw2)
        check("export: Google inte kopplat → inget skickas, tydlig notis, uppgifterna finns kvar",
              not r["ok"] and not calls and not events[-1]["ok"] and "inte kopplat" in events[-1]["message"] and len(store.active_tasks()) == 4)

        events.clear(); calls.clear()
        r = jt.export_worker(tmp, store.find_task, ids[:1], opts, "M", **kw)
        check("export: bara de valda id:na skickas (aldrig resten av listan)", len(calls[-1][1]) == 1)
        r = jt.export_worker(tmp, lambda i: None, ids, opts, "M", **kw)
        check("export: borttagna uppgifter hoppas över utan fel", r["ok"] and r["total"] == 0)

        # tråden: startar, kör klart, rör inget Qt
        events.clear(); calls.clear()
        th = jt.export_async(tmp, store.find_task, ids, opts, "Tråd", **kw)
        th.join(5)
        check("export_async: daemon-tråd som körs klart", isinstance(th, threading.Thread) and th.daemon and not th.is_alive() and events and events[-1]["ok"])
        check("export_async: inga id → ingen tråd", jt.export_async(tmp, store.find_task, [], opts, "x") is None)
        jt.EVENTS.clear()
        th = jt.export_async(tmp, store.find_task, ids, opts, "Standardkö", service_factory=lambda dd: object(), connected=lambda dd: True, sleep=naps.append)
        th.join(5)
        check("utan eget notify hamnar notisen i jt.EVENTS (töms av appen)", len(jt.EVENTS) == 1 and jt.EVENTS[0]["title"] == "Standardkö")
        jt.EVENTS.clear()
    finally:
        gcal.push_tasks, gcal.load_event_map, gcal.load_history = orig

    check("google_ready utan token → False (ingen krasch)", jt.google_ready(tmp) is False)

    # --- källkodskontroller ---------------------------------------------------------------------------------------
    src = lambda p: (ROOT / p).read_text(encoding="utf-8")
    check("fönstermenyn har 'Ny uppgift från mall'", "act_tmpl" in src("ui/widget_parts/window_ops.py") and "_on_open_job_templates" in src("ui/widget_parts/exports.py"))
    check("tray-menyn har 'Ny uppgift från mall'", "_open_job_templates" in src("app/mixins/tray.py") and "def _open_job_templates" in src("app/mixins/exports.py"))
    check("tray-notiserna töms från jt.EVENTS", "_jt.EVENTS" in src("app/mixins/exports.py"))
    check("mallfilen ligger i datamappen (inget utanför appmappen)", "APPDATA" not in src("core/job_templates.py") and ".local" not in src("core/job_templates.py"))
    check("Google-anropet sker aldrig i GUI-koden (bara via tråd)", "export_async" in src("ui/job_template_dialog.py") and "push_tasks" not in src("ui/job_template_dialog.py"))
    shutil.rmtree(tmp, ignore_errors=True)


def child() -> None:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication, QMessageBox
    import time
    app = QApplication([])
    from core import job_templates as jt
    from core.settings import Settings
    from core.store import TaskStore
    import ui.job_template_dialog as JD
    res = []

    def ck(name, cond, extra=""):
        res.append((name + (f" {extra}" if not cond and extra else ""), bool(cond)))

    def spin(sec=0.2):
        t = time.time()
        while time.time() - t < sec:
            app.processEvents()

    tmp = Path(tempfile.mkdtemp(prefix="ledgebord_malld_"))
    settings = Settings(str(tmp / "s.json"))
    store = TaskStore(data_dir_override=tmp / "store")
    dd = tmp / "store"
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)

    # --- använd mall -------------------------------------------------------------------------------------------
    dlg = JD.JobTemplateDialog(None, store, settings)
    ck("dialogen listar startmallarna", dlg.f_template.count() == 2 and "Limojobb" in dlg.f_template.itemText(0))
    ck("förhandsvisning: 4 rader", dlg.preview.count() == 4 and dlg.ok_btn.isEnabled() and "4" in dlg.ok_btn.text())
    dlg.f_customer.setText("Anna")
    ck("kundnamnet slår igenom i förhandsvisningen", "Anna" in dlg.preview.item(1).text())
    from PySide6.QtCore import QDate
    dlg.f_date.setDate(QDate(2026, 11, 20))
    ck("jobbdagen styr datumen", "20/11 2026" in dlg.preview.item(1).text() and "17/11 2026" in dlg.preview.item(0).text(), dlg.preview.item(1).text())
    ck("Google ej kopplat → rutan avstängd, med förklaring", not dlg.f_gcal.isEnabled() and not dlg.f_gcal.isChecked() and "inte kopplat" in dlg.gcal_note.text())
    dlg.f_template.setCurrentIndex(1)
    ck("byte av mall byter förhandsvisning", "Installation" in dlg.preview.item(1).text())

    sent = []
    jt_orig = jt.export_async
    jt.export_async = lambda data_dir, find, ids, opts, label, **k: sent.append((list(ids), label, opts)) or None
    dlg.f_template.setCurrentIndex(0)
    dlg._google_ok = True
    dlg._template_changed()
    ck("Google kopplat → rutan går att använda (förval = mallens val, av)", dlg.f_gcal.isEnabled() and not dlg.f_gcal.isChecked())
    dlg._accept()
    ck("skapar 4 uppgifter i butiken", len(dlg.created) == 4 and len(store.active_tasks()) == 4)
    ck("rutan av → inget skickas till Google", sent == [] and dlg.sent is False)

    dlg2 = JD.JobTemplateDialog(None, store, settings)
    dlg2._google_ok = True
    dlg2._template_changed()
    dlg2.f_customer.setText("Bo")
    dlg2.f_gcal.setChecked(True)
    dlg2._accept()
    ck("rutan på → exporten startas för EXAKT de nya uppgifterna", len(sent) == 1 and sent[0][0] == dlg2.created and len(dlg2.created) == 4 and dlg2.sent)
    ck("exporten får kalender/färg-valen och mallens namn + kund", sent[0][1] == "Limojobb — Bo" and "calendar_id" in sent[0][2], sent[0][1:])
    jt.export_async = jt_orig

    # --- mallens eget Google-val ---------------------------------------------------------------------------------
    tpls = jt.load_templates(dd)
    tpls[0]["gcal"] = True
    jt.save_templates(dd, tpls)
    dlg3 = JD.JobTemplateDialog(None, store, settings)
    dlg3._google_ok = True
    dlg3._template_changed()
    ck("mall med 'skicka automatiskt' → rutan förkryssad", dlg3.f_gcal.isChecked())
    dlg3._google_ok = False
    dlg3._template_changed()
    ck("…men inte om Google saknas (skickar aldrig i blindo)", not dlg3.f_gcal.isChecked() and not dlg3.f_gcal.isEnabled())

    # --- tom mallista ------------------------------------------------------------------------------------------
    jt.save_templates(dd, [])
    dlg4 = JD.JobTemplateDialog(None, store, settings)
    ck("inga mallar → Skapa avstängd och hjälptext", not dlg4.ok_btn.isEnabled() and "inga mallar" in dlg4.preview.item(0).text().lower())
    jt.save_templates(dd, jt.default_templates())

    # --- redigeraren ---------------------------------------------------------------------------------------------
    ed = JD.TemplateEditorDialog(None, dd)
    ck("redigeraren visar mallarna och stegen", ed.list.count() == 2 and ed.table.rowCount() == 4 and ed.f_name.text() == "Limojobb")
    ck("stegens kolumner", ed.table.item(0, 0).text() == "Bekräfta bokning — {kund}" and ed.table.cellWidget(0, 1).value() == -3
       and ed.table.cellWidget(2, 5).isChecked() and ed.table.item(2, 3).text() == "faktura")
    ed.f_name.setText("Limo VIP")
    ed.f_gcal.setChecked(True)
    ed._add_step()
    r = ed.table.rowCount() - 1
    ed.table.item(r, 0).setText("Tacka kunden — {kund}")
    ed.table.cellWidget(r, 1).setValue(2)
    ed.table.item(r, 4).setText("1 500")
    ed._move(-1)
    ck("flytta upp ett steg", ed.table.item(r - 1, 0).text().startswith("Tacka") and ed.table.currentRow() == r - 1)
    ed.table.setCurrentCell(0, 0)
    ed._del_step()
    ck("ta bort steg", ed.table.rowCount() == 4 and ed.table.item(0, 0).text().startswith("Utför"))
    ed._dup()
    ck("duplicera → ny mall 'Limo VIP (kopia)' med samma steg", ed.list.count() == 3 and ed.templates[2]["name"] == "Limo VIP (kopia)"
       and len(ed.templates[2]["steps"]) == 4 and ed.templates[2]["id"] != ed.templates[0]["id"], [t["name"] for t in ed.templates])
    ed._new()
    ck("ny mall får ett steg och unikt namn", ed.list.count() == 4 and ed.templates[3]["name"] == "Ny mall" and ed.table.rowCount() == 1)
    ed.list.setCurrentRow(1)
    ck("byta mall behåller ändringarna i minnet", ed.templates[0]["name"] == "Limo VIP" and ed.templates[0]["gcal"] is True and len(ed.templates[0]["steps"]) == 4)
    ed.list.setCurrentRow(3)
    ed._delete()
    ck("ta bort mall", ed.list.count() == 3)
    ed._save()
    saved = jt.load_templates(dd)
    ck("Spara skriver filen", [t["name"] for t in saved] == ["Limo VIP", "Bilstereo-installation", "Limo VIP (kopia)"], [t["name"] for t in saved])
    st = saved[0]["steps"]
    ck("sparade steg: ordning, dagar, belopp", st[2]["title"].startswith("Tacka") and st[2]["days"] == 2 and st[2]["amount_cents"] == 150000 and saved[0]["gcal"] is True, st)

    ed2 = JD.TemplateEditorDialog(None, dd)
    ed2.f_name.setText("Kasseras")
    ed2.reject()
    ck("Avbryt sparar inget", jt.load_templates(dd)[0]["name"] == "Limo VIP")
    ed3 = JD.TemplateEditorDialog(None, dd)
    for _ in range(3):
        ed3.list.setCurrentRow(0)
        ed3._delete()
    ck("alla mallar borta → redigeraren avstängd utan fel", ed3.list.count() == 0 and not ed3.table.isEnabled() and not ed3.f_name.isEnabled())
    ed3._new()
    ck("…och går att börja om", ed3.list.count() == 1 and ed3.table.isEnabled())
    ed3.f_name.setText("Z")
    ed3.table.item(0, 0).setText("")
    ed3._save()
    ck("steg utan titel sparas inte", jt.load_templates(dd)[0]["steps"] == [])

    # --- publika ingången ------------------------------------------------------------------------------------------
    ck("open_job_template_dialog utan butik → inget, ingen krasch", JD.open_job_template_dialog(None, None, None) == [])
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
    _run_parent("job_templates_test")
    print(f"\njob_templates_test: {_ok} lyckades, {_fail} misslyckades")
    sys.exit(1 if _fail else 0)
