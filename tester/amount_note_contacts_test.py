#!/usr/bin/env python3
"""
amount_note_contacts_test.py — 💰 belopp + summor, 📝 längre anteckningar, 📞/📍 klickbara telefonnummer och adresser.

Kör:  python tester/amount_note_contacts_test.py
Ren logik (core/contacts.py, core/amounts.py) körs direkt; butik, kort, menyer och dialoger i en Qt-barnprocess.
"""
from __future__ import annotations

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


from core import amounts as am  # noqa: E402
from core import contacts as ct  # noqa: E402


def pure() -> None:
    P = lambda t: [p["tel"] for p in ct.find_phones(t)]  # noqa: E731
    # --- telefonnummer ---
    check("mobil med bindestreck", P("Ring Kalle 070-123 45 67") == ["+46701234567"])
    check("mobil utan avgränsare", P("0701234567") == ["+46701234567"])
    check("+46 med (0)", P("Tel +46 (0)70-123 45 67") == ["+46701234567"])
    check("0046-form", P("0046 70 123 45 67") == ["+46701234567"])
    check("+46 utan nolla", P("+46701234567") == ["+46701234567"])
    check("riktnummer Stockholm", P("08-123 456 78") == ["+46812345678"])
    check("utländskt nummer med +", P("+47 912 34 567") == ["+4791234567"])
    check("visningstexten behåller skrivsättet", ct.find_phones("ring 070-123 45 67 nu")[0]["text"] == "070-123 45 67")
    check("två nummer i samma text", P("070-1234567, kvällstid 0708-99 88 77") == ["+46701234567", "+46708998877"])
    check("samma nummer två gånger → ett", P("070-123 45 67 eller 0701234567") == ["+46701234567"])
    check("telefon efter ett datum hittas", P("Faktura 2026-11-06 070-123 45 67") == ["+46701234567"])
    check("telefon före ett datum hittas", P("Ring 070-123 45 67 före 2026-11-06") == ["+46701234567"])
    check("telefon följd av årtal hittas", P("070-123 45 67 2026") == ["+46701234567"])
    check("datum är inget telefonnummer", P("Förfaller 2026-11-06 och 06-11-2026") == [])
    check("organisationsnummer är inget telefonnummer", P("Org 556677-8899") == [])
    check("personnummer som börjar på 0 är inget telefonnummer", P("010101-1234") == [])
    check("OCR-/fakturanummer utan avgränsare är inget telefonnummer", P("OCR 0123456789 faktura 20261106") == [])
    check("belopp är inget telefonnummer", P("12 000 kr + 4 500,50 kr") == [])
    check("för kort nummer räknas inte", P("070 123 45") == [] and P("kl 08-12") == [])
    check("för långt nummer räknas inte", P("0701234567890") == [])
    check("högst 3 nummer", len(ct.find_phones(" ".join(f"070-123 45 {i:02d}" for i in range(10)))) == 3)
    check("tom/None tål", ct.find_phones("") == [] and ct.find_phones(None) == [])
    check("tel-länken har bara siffror och +", ct.tel_url("+46 70-123 45 67") == "tel:+46701234567" and ct.sms_url("070-123") == "sms:070123")
    # --- adresser ---
    A = lambda t: [a["text"] for a in ct.find_addresses(t)]  # noqa: E731
    check("gata + nummer + postnummer + ort", A("Hämta bil på Storgatan 12 B, 111 22 Stockholm") == ["Storgatan 12 B, 111 22 Stockholm"])
    check("två ord i gatunamnet", A("Montera hos Norra Hamngatan 4 i morgon") == ["Norra Hamngatan 4"])
    check("nummerintervall", A("Vasavägen 5-7") == ["Vasavägen 5-7"])
    check("liten bokstav direkt efter numret", A("Östra Storgatan 14b") == ["Östra Storgatan 14b"])
    check("'5 i' (ord efter numret) tas inte med", A("Odengatan 5 i morgon") == ["Odengatan 5"])
    check("belopp efter gatunamn är ingen adress", A("Storgatan 12 000 kr") == [])
    check("gemener (vanligt ord) räknas inte", A("lagt på storgatan 5") == [])
    check("ord utan gatuändelse räknas inte", A("Kalle 12, Stockholm 123") == [])
    check("högst 2 adresser", len(ct.find_addresses("Storgatan 1, Vasagatan 2, Odengatan 3")) == 2)
    check("maps-länk kodar adressen och lägger till Sverige", ct.maps_url("Storgatan 12") == "https://www.google.com/maps/search/?api=1&query=Storgatan%2012%2C%20Sverige")
    check("maps-länk med postnummer behöver inte Sverige", "Sverige" not in ct.maps_url("Storgatan 12, 111 22 Stockholm"))
    check("vägbeskrivning använder destination", ct.directions_url("Storgatan 12").startswith("https://www.google.com/maps/dir/?api=1&destination="))
    # --- belopp ---
    today = date(2026, 11, 6)
    T = [{"amount_cents": 400000, "due_date": "2026-11-03", "tags": ["limo"]},
         {"amount_cents": 120050, "due_date": "2026-11-20", "tags": ["limo", "x"]},
         {"amount_cents": 50000, "due_date": "2026-12-01"},
         {"amount_cents": 10000, "done": True, "due_date": "2026-11-01"},
         {"amount_cents": True}, {"amount_cents": -5}, {"amount_cents": "100"}, {"title": "utan"}]
    s = am.summarize(T, today)
    check("summa kvar = ej klarmarkerade", s["open"] == 570050 and s["open_count"] == 3, s)
    check("klarmarkerat räknas separat", s["done"] == 10000 and s["count"] == 4)
    check("ogiltiga belopp (bool, negativt, text) räknas inte", s["no_amount"] == 4)
    check("försenat = förfallodatum före idag", s["overdue"] == 400000 and s["overdue_count"] == 1)
    check("denna månad / nästa månad", s["this_month"] == 520050 and s["next_month"] == 50000)
    check("per månad i tidsordning", list(s["by_month"]) == ["2026-11", "2026-12"] and s["by_month"]["2026-11"] == 520050)
    check("per tagg (flera taggar räknas under varje) + 'utan tagg'", s["by_tag"] == {"limo": 520050, "x": 120050, "utan tagg": 50000}, s["by_tag"])
    check("december → nästa månad är januari", am.summarize([{"amount_cents": 100, "due_date": "2027-01-15"}], date(2026, 12, 20))["next_month"] == 100)
    check("uppgift utan datum hamnar under 'utan datum' sist", list(am.summarize([{"amount_cents": 1}, {"amount_cents": 1, "due_date": "2026-11-01"}], today)["by_month"]) == ["2026-11", "utan datum"])
    check("raden: kvar, försenat, denna månad, klarmarkerat",
          am.summary_line(s) == "💰 5\u00a0700,50\u00a0kr kvar (3 uppgifter) · försenat 4\u00a0000\u00a0kr · denna månad 5\u00a0200,50\u00a0kr · klarmarkerat 100\u00a0kr", am.summary_line(s))
    check("raden är tom utan belopp", am.summary_line(am.summarize([{"title": "x"}], today)) == "")
    check("allt klart när bara klarmarkerat finns", am.summary_line(am.summarize([{"amount_cents": 5000, "done": True}], today)).startswith("💰 allt klart"))
    arch = am.summarize_archive([{"amount_cents": 100000, "completed": "2026-10-05T10:00:00", "tags": ["limo"]},
                                 {"amount_cents": 50000, "completed": "2026-10-20T10:00:00"}, {"amount_cents": 7000}])
    check("arkivet: per klarmånad och totalt", arch["total"] == 157000 and arch["by_month"]["2026-10"] == 150000 and arch["by_month"]["utan datum"] == 7000, arch)
    txt = am.overview_text(s, arch)
    check("översiktstexten har månader, taggar och arkivet", "november 2026" in txt and "limo" in txt and "Arkivet" in txt and "oktober 2026" in txt)
    check("månadsnamn", am.month_label("2026-03") == "mars 2026" and am.month_label("skräp") == "skräp")


def child() -> None:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication, QDialog, QInputDialog, QMenu, QMessageBox, QVBoxLayout, QWidget
    app = QApplication([])
    from core.settings import Settings
    from core.store import TaskStore
    import widget as W
    from ui import extras_dialogs as ED

    res: list = []

    def ck(name, cond, extra=""):
        res.append((name + (f" {extra}" if not cond and extra else ""), bool(cond)))

    tmp = tempfile.mkdtemp(prefix="ledgebord_anc_")
    data = Path(tmp) / "data"
    store = TaskStore(data_dir_override=data)
    a = store.add_task("Limo Kalle", due_date="2026-11-03", tags=["limo"])
    b = store.add_task("Bil Olle", tags=["bil"])
    # --- butik ---
    ck("set_amount sparar ören", store.set_amount(a, 400000) and store.find_task(a)["amount_cents"] == 400000)
    ck("samma belopp igen → False", store.set_amount(a, 400000) is False)
    ck("ogiltigt belopp tar bort det", store.set_amount(b, 5) and store.set_amount(b, -1) and "amount_cents" not in store.find_task(b))
    ck("set_amount(None) tar bort", store.set_amount(b, 100) and store.set_amount(b, None) and "amount_cents" not in store.find_task(b))
    ck("set_amount på okänt id → False", store.set_amount("nope", 5) is False)
    ck("set_note sparar flera rader", store.set_note(a, "Rad 1\r\nRad 2\n\n  Rad 4  ") and store.find_task(a)["note"] == "Rad 1\nRad 2\n\n  Rad 4")
    ck("tom anteckning tar bort", store.set_note(b, "x") and store.set_note(b, "   ") and "note" not in store.find_task(b))
    ck("anteckning kortas vid 50 000 tecken", store.set_note(b, "x" * 60000) and len(store.find_task(b)["note"]) == 50000)
    store.set_note(b, None)
    # --- sökning i anteckning ---
    store.set_note(b, "Hämta nycklar hos grannen")
    ck("sökning hittar text i anteckningen", [t["id"] for t in store.active_tasks_filtered(query="nycklar")] == [b])
    ck("sökning hittar fortfarande titel", [t["id"] for t in store.active_tasks_filtered(query="limo")] == [a])
    store.set_note(b, None)
    # --- överlever omstart ---
    store.save() if hasattr(store, "save") else None
    store.flush() if hasattr(store, "flush") else None
    s2 = TaskStore(data_dir_override=data)
    t = s2.find_task(a)
    ck("belopp och anteckning överlever omstart (läses in igen)", t and t.get("amount_cents") == 400000 and t.get("note") == "Rad 1\nRad 2\n\n  Rad 4", t)
    # --- arkiv: belopp/anteckning följer med och kan ändras ---
    c = s2.add_task("Arkivera mig", tags=["x"])
    s2.set_amount(c, 25000)
    s2.archive_task(c)
    ck("arkiverad uppgift behåller beloppet", s2.find_task(c).get("amount_cents") == 25000)
    ck("belopp går att ändra på arkiverad", s2.set_amount(c, 30000) and s2.find_task(c)["amount_cents"] == 30000)
    ck("arkivet finns kvar (historik)", any(x["id"] == c for x in s2.archive_tasks()))
    # --- delbetalningsplan ger belopp ---
    from core import payment_plan as pp
    ids = pp.create_tasks(s2, pp.build_plan("Limo", date(2026, 12, 1), 3, total_cents=1000000), tags=["delbetalning"])
    ck("delbetalningarna får belopp (summan = totalen)", sum(s2.find_task(i)["amount_cents"] for i in ids) == 1000000 and len(ids) == 3)
    # --- kalenderbeskrivning + PDF ---
    from core import calendar_export as ce
    ck("kalenderposten nämner beloppet", "Belopp: 4 000 kr" in ce.build_description(s2.find_task(a)))
    from core import pdf_export as pe
    html = pe.render_checklist_html(s2.active_tasks())
    ck("PDF-listan visar beloppet", "4\u00a0000\u00a0kr" in html or "4 000 kr" in html)

    # --- fönstret ---
    settings = Settings(str(Path(tmp) / "settings.json"))
    shell = QWidget()
    w = W.TodoWidget(app.primaryScreen(), s2, settings, win_id="t", parent=shell)
    lay = QVBoxLayout(shell)
    lay.addWidget(w)
    w._shell = shell
    shell.resize(480, 640)
    shell.show()
    app.processEvents()
    d = s2.add_task("Montera hos Odengatan 9", tags=["jobb"])
    s2.set_note(d, "Ring Olle 070-123 45 67 före 2026-11-06\nPorten är grön")
    w._rebuild_task_list()
    app.processEvents()
    card = w._task_widgets.get(a)
    kinds = lambda cd: sorted(x.property("chipKind") for x in cd.findChildren(W.LinkChip))  # noqa: E731
    ck("kort med belopp + anteckning får båda chips", card is not None and kinds(card) == ["amount", "note"], kinds(card) if card else None)
    ck("beloppschipet visar 4 000 kr", any("4 000 kr" in x.text() for x in card.findChildren(W.LinkChip)))
    ck("anteckningschipet visar första raden och '+' för fler", any(x.text().startswith("📝 Rad 1") and x.text().endswith("+") for x in card.findChildren(W.LinkChip)))
    note_chip = [x for x in card.findChildren(W.LinkChip) if x.property("chipKind") == "note"][0]
    ck("anteckningschipets tooltip har hela texten", "Rad 4" in note_chip.toolTip())
    dcard = w._task_widgets.get(d)
    ck("kort med telefon i anteckning + adress i titel får 📞 och 📍", kinds(dcard) == ["address", "note", "phone"], kinds(dcard))
    ck("chipens stil kommer från temat (objectNames)", {x.objectName() for x in dcard.findChildren(W.LinkChip)} == {"noteChip", "contactChip"})
    qss = w.styleSheet()
    ck("temat har stil för amountChip/noteChip/contactChip/amountSummary", all(k in qss for k in ("QLabel#amountChip", "QLabel#noteChip", "QLabel#contactChip", "QPushButton#amountSummary")))
    plain = w._task_widgets.get(b)
    ck("kort utan extra har inga extra-chips", plain is not None and kinds(plain) == [])

    # klick: adress → Maps, telefon → meny
    opened: list = []
    w._open_url = lambda u: opened.append(u)
    adr = [x for x in dcard.findChildren(W.LinkChip) if x.property("chipKind") == "address"][0]
    adr.clicked.emit(adr.key())
    ck("klick på adress öppnar Google Maps", opened and opened[-1].startswith("https://www.google.com/maps/search/") and "Odengatan" in opened[-1], opened)
    menus: list = []
    trig = {"first": True}

    class FakeMenu(QMenu):
        def exec(self, *a, **k):  # noqa: A003
            menus.append([x.text() for x in self.actions()])
            if trig["first"]:
                self.actions()[0].trigger()
            return None

    for _m in ("extras", "task_menu"):
        sys.modules[f"ui.widget_parts.{_m}"].QMenu = FakeMenu
    try:
        ph = [x for x in dcard.findChildren(W.LinkChip) if x.property("chipKind") == "phone"][0]
        ph.clicked.emit(ph.key())
        ck("klick på telefon visar menyn Ring/SMS/Kopiera", menus and any("Ring" in m for m in menus[-1]) and any("SMS" in m for m in menus[-1]) and any("Kopiera" in m for m in menus[-1]), menus)
        ck("'Ring' öppnar tel:-länken", opened[-1] == "tel:+46701234567", opened)
        w._address_menu({"text": "Odengatan 9"}, None)
        ck("adressmenyn har Maps, vägbeskrivning och kopiera", len(menus[-1]) == 3)
        # kopiera
        w._copy_text("070-123 45 67", "numret")
        from PySide6.QtGui import QGuiApplication
        ck("kopiera lägger numret i urklipp", QGuiApplication.clipboard().text() == "070-123 45 67")
        # uppgiftsmenyn har nya posterna
        trig["first"] = False
        w._show_task_menu(s2.find_task(a))
        ck("uppgiftsmenyn har 💰 Belopp och 📝 anteckning", any("Belopp" in x for x in menus[-1]) and any("anteckning" in x.lower() for x in menus[-1]), menus[-1])
    finally:
        trig["first"] = False

    # belopp: dialog
    orig_gt = QInputDialog.getText
    seen_prompts: list = []
    QInputDialog.getText = staticmethod(lambda *a, **k: seen_prompts.append(k.get("text")) or ("1 234,50 kr", True))
    try:
        w._edit_amount(b)
        ck("_edit_amount tolkar '1 234,50 kr' till ören", s2.find_task(b)["amount_cents"] == 123450)
        ck("dialogen förifylls med nuvarande belopp", (w._edit_amount(b) or True) and seen_prompts[-1] == "1 234,50 kr", seen_prompts)
        QInputDialog.getText = staticmethod(lambda *a, **k: ("", True))
        w._edit_amount(b)
        ck("tomt svar tar bort beloppet", "amount_cents" not in s2.find_task(b))
        calls = []
        answers = iter([("abc", True), ("5000", True)])
        QInputDialog.getText = staticmethod(lambda *a, **k: next(answers))
        orig_w = QMessageBox.warning
        QMessageBox.warning = staticmethod(lambda *a, **k: calls.append(a[2]) or 0)
        try:
            w._edit_amount(b)
        finally:
            QMessageBox.warning = orig_w
        ck("ogiltigt belopp: varnar och frågar igen", len(calls) == 1 and s2.find_task(b)["amount_cents"] == 500000, (calls, s2.find_task(b)))
        QInputDialog.getText = staticmethod(lambda *a, **k: ("1", False))
        w._edit_amount(b)
        ck("Avbryt ändrar inget", s2.find_task(b)["amount_cents"] == 500000)
    finally:
        QInputDialog.getText = orig_gt

    # summaraden
    app.processEvents()
    w._rebuild_task_list()
    btn = w.amount_summary
    ck("summaraden syns när belopp finns", not btn.isHidden() and "kvar" in btn.text(), btn.text())
    ck("summaraden stämmer: 4 000 + 5 000 (+3 delbetalningar)", "💰" in btn.text() and "000" in btn.text())
    w.search_input.setText("odengatan")
    app.processEvents()
    w._do_search() if hasattr(w, "_do_search") else None
    app.processEvents()
    ck("sökning utan belopp i träffarna → raden döljs", btn.isHidden(), btn.text())
    w.search_input.setText("")
    app.processEvents()
    w._rebuild_task_list()
    ck("raden tillbaka när sökningen töms", not btn.isHidden())
    for tid in [t["id"] for t in s2.active_tasks()]:
        s2.set_amount(tid, None)
    w._rebuild_task_list()
    ck("inget belopp någonstans → raden dold", btn.isHidden())
    s2.set_amount(a, 400000)
    w._rebuild_task_list()

    # dialoger
    dlg = ED.NoteDialog(None, "Titel", "Hej\nvärlden")
    ck("NoteDialog visar texten och ger tillbaka den", dlg.text() == "Hej\nvärlden")
    dlg.edit.setPlainText("ny\ntext")
    ck("NoteDialog ger ändrad text", dlg.text() == "ny\ntext")
    ov = ED.AmountOverviewDialog(None, "Rad A\nRad B", "Vy: test")
    ck("översiktsdialogen visar texten (skrivskyddad)", ov.view.toPlainText() == "Rad A\nRad B" and ov.view.isReadOnly())
    ov._copy()
    ck("översiktens Kopiera lägger texten i urklipp", QGuiApplication.clipboard().text() == "Rad A\nRad B")
    # anteckning via fönstret
    orig_exec_d = ED.NoteDialog.exec
    ED.NoteDialog.exec = lambda self: (self.edit.setPlainText("Sparad via dialog\nrad 2"), QDialog.DialogCode.Accepted)[1]
    try:
        w._edit_note(b)
    finally:
        ED.NoteDialog.exec = orig_exec_d
    ck("_edit_note sparar anteckningen", s2.find_task(b)["note"] == "Sparad via dialog\nrad 2")
    ED.NoteDialog.exec = lambda self: QDialog.DialogCode.Rejected
    try:
        w._edit_note(b)
    finally:
        ED.NoteDialog.exec = orig_exec_d
    ck("Avbryt i anteckningsdialogen ändrar inget", s2.find_task(b)["note"] == "Sparad via dialog\nrad 2")
    shown = []
    from ui import extras_dialogs as _ed
    orig_ov = _ed.AmountOverviewDialog.exec
    _ed.AmountOverviewDialog.exec = lambda self: shown.append(self.view.toPlainText()) or 0
    try:
        w._show_amount_overview()
    finally:
        _ed.AmountOverviewDialog.exec = orig_ov
    ck("klick på summaraden öppnar översikten med månader + taggar + arkiv", shown and "Per förfallomånad" in shown[0] and "Per tagg" in shown[0] and "Arkivet" in shown[0], shown)
    # sökindex tar med anteckningen
    w._build_search_index()
    ck("sökindex innehåller ord ur anteckningen", "sparad" in w._search_index and b in w._search_index["sparad"])
    # cache: ändrad anteckning ritar om kortet
    before = w._task_widgets.get(b)
    s2.set_note(b, "Helt ny text")
    w._rebuild_task_list()
    after = w._task_widgets.get(b)
    ck("ändrad anteckning ger nytt kort (cache-nyckel)", after is not None and after is not before and any("Helt ny" in x.text() for x in after.findChildren(W.LinkChip)))

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
    _run_parent("amount_note_contacts_test")
    # --- källkontroller ---
    card = (ROOT / "ui/widget_parts/task_card.py").read_text(encoding="utf-8")
    check("kortet bygger extra-raderna", "self._add_extra_rows(container, vbox, task, archived)" in card)
    rsrc = (ROOT / "ui/widget_parts/render.py").read_text(encoding="utf-8")
    check("render: cache-nyckeln har belopp/anteckning och summan uppdateras", "self._extra_state(task)" in rsrc and rsrc.count("_update_amount_summary") == 2)
    store_src = (ROOT / "core/store.py").read_text(encoding="utf-8")
    check("store: belopp läses in igen (coerce)", 'raw.get("amount_cents")' in store_src and "def set_note" in store_src and "def set_amount" in store_src)
    check("manualen beskriver belopp, anteckningar och kontaktuppgifter", all(k in (ROOT / "docs/MANUAL.md").read_text(encoding="utf-8") for k in ("## 💰 Belopp", "## 📝 Anteckningar", "klickbara telefonnummer")))
    print(f"\namount_note_contacts_test: {_ok} lyckades, {_fail} misslyckades")
    sys.exit(1 if _fail else 0)
