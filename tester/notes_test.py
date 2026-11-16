#!/usr/bin/env python3
"""
notes_test.py — fliken 📝 Anteckningar: lagring (core/notes.py), backup/återställning, vyn och fliken i fönstret.

Kör:  python tester/notes_test.py
Del 1 (ren Python): spara/ändra/radera/sök/fäst, skadad fil, atomär skrivning, sammanslagning, backup.
Del 2 (Qt i egen process): vyn (skapa, skriv → autospar, tillbaka, sök, fäst, kopiera, radera) och fliken i fönstret.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
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
    from core import notes as N
    from core import tasks_backup as TB

    tmp = Path(tempfile.mkdtemp(prefix="ledgebord_notes_"))
    try:
        d = tmp / "js"
        s = N.NotesStore(d)
        check("tom start: inga anteckningar, ingen fil skapad än", s.count() == 0 and not (d / "notes.json").exists())
        a = s.add("Inköp", "mjölk\nbröd")
        check("ny anteckning sparas direkt på disk i datamappen", (d / "notes.json").is_file() and s.count() == 1)
        check("fält: id, rubrik, text, skapad, ändrad, ej fäst", a["title"] == "Inköp" and a["body"] == "mjölk\nbröd" and len(a["id"]) == 12 and a["created"] and a["updated"] and a["pinned"] is False)
        s2 = N.NotesStore(d)
        check("en ny instans läser tillbaka samma anteckning (sparas mellan starter)", s2.count() == 1 and s2.get(a["id"])["body"] == "mjölk\nbröd")
        time.sleep(1.1)
        b = s.add("", "Ring Anders om fakturan\nmer text")
        check("rubrik saknas → första raden i texten används", N.title_of(b) == "Ring Anders om fakturan" and N.preview_of(b) == "mer text")
        check("tom anteckning får ett namn", N.title_of({"title": "", "body": "  \n "}) == "(tom anteckning)")
        check("senast skapad/ändrad ligger överst", [n["id"] for n in s.notes()] == [b["id"], a["id"]])
        time.sleep(1.1)
        s.update(a["id"], body="mjölk\nbröd\nsmör")
        check("redigering sparas och flyttar anteckningen överst (ändrad-tid)", s.notes()[0]["id"] == a["id"] and N.NotesStore(d).get(a["id"])["body"].endswith("smör"))
        upd = s.get(a["id"])["updated"]
        time.sleep(1.1)
        s.update(a["id"], body="mjölk\nbröd\nsmör")
        check("oförändrad text ändrar inte ändrad-tiden", s.get(a["id"])["updated"] == upd)
        s.update(b["id"], pinned=True)
        check("fäst ligger överst även om en annan är nyare", s.notes()[0]["id"] == b["id"] and s.notes()[0]["pinned"])
        check("fästning ändrar inte ändrad-tiden", s.get(b["id"])["updated"] == b["updated"])
        check("sök i rubrik och text, utan hänsyn till versaler", [n["id"] for n in s.notes("SMÖR")] == [a["id"]] and [n["id"] for n in s.notes("inköp")] == [a["id"]] and s.notes("finns inte") == [])
        check("update av okänt id ger None, ingen krasch", s.update("nej", body="x") is None)
        s.update(a["id"], title="x" * 500, body="y" * (N.BODY_MAX + 50))
        n = s.get(a["id"])
        check("gränser: rubrik ≤ 200, text ≤ 200 000 tecken", len(n["title"]) == N.TITLE_MAX and len(n["body"]) == N.BODY_MAX)
        check("radera tar bort och sparar", s.delete(a["id"]) and N.NotesStore(d).get(a["id"]) is None and not s.delete(a["id"]))
        # skriver ingen temp-fil kvar
        check("ingen temporärfil blir kvar efter sparning", [p.name for p in d.iterdir() if p.name.startswith(".")] == [])
        uni = s.add("Åäö ✓ 📞", "Växjö — “citat” 😀")
        check("svenska tecken, emoji och citattecken överlever lagring", N.NotesStore(d).get(uni["id"])["body"] == "Växjö — “citat” 😀")
        raw = (d / "notes.json").read_text(encoding="utf-8")
        check("filen är läsbar JSON med version och notes (inte \\u-escapad)", json.loads(raw)["version"] == 1 and "Åäö" in raw)

        # två fönster/instanser: ingen skriver över den andras anteckningar
        x, y = N.NotesStore(d), N.NotesStore(d)
        nx = x.add("från X", "1")
        time.sleep(0.05)
        os.utime(d / "notes.json", (time.time() + 5, time.time() + 5))
        ny = y.add("från Y", "2")
        ids = {n["id"] for n in N.NotesStore(d).notes()}
        check("två instanser: båda anteckningarna finns kvar (ingen skriver över)", {nx["id"], ny["id"]} <= ids, ids)

        # skadad fil
        bad = tmp / "bad"
        bad.mkdir()
        (bad / "notes.json").write_text("{trasig", encoding="utf-8")
        sb = N.NotesStore(bad)
        check("skadad fil: appen startar med tom lista", sb.count() == 0)
        check("…den skadade filen sparas undan (raderas inte)", any(p.name.startswith("notes.json.skadad-") for p in bad.iterdir()) and "trasig" in next(p for p in bad.iterdir() if ".skadad-" in p.name).read_text(encoding="utf-8"))
        sb.add("efter krasch", "går att skriva")
        check("…och nya anteckningar går att spara", N.NotesStore(bad).count() == 1)
        (bad / "notes.json").write_text(json.dumps({"notes": [{"id": "1", "title": "ok"}, "skräp", {"title": "utan id"}, {"id": "1", "title": "dubblett"}]}), encoding="utf-8")
        check("trasiga poster i filen hoppas över, dubbletter tas bort", [n["id"] for n in N.NotesStore(bad).notes()] == ["1"])

        # sammanslagning
        old = N.dump([{"id": "a", "title": "gammal", "body": "", "created": "2026-01-01T10:00:00+01:00", "updated": "2026-01-01T10:00:00+01:00", "pinned": False},
                      {"id": "b", "title": "bara i backup", "body": "", "created": "2026-01-02T10:00:00+01:00", "updated": "2026-01-02T10:00:00+01:00", "pinned": False}])
        new = N.dump([{"id": "a", "title": "nyare", "body": "", "created": "2026-01-01T10:00:00+01:00", "updated": "2026-03-01T10:00:00+01:00", "pinned": False},
                      {"id": "c", "title": "bara nu", "body": "", "created": "2026-03-01T10:00:00+01:00", "updated": "2026-03-01T10:00:00+01:00", "pinned": False}])
        m = {n["id"]: n for n in N.parse(N.merge_raw(new, old))}
        check("merge: union, nyaste ändringen vinner, inget försvinner", set(m) == {"a", "b", "c"} and m["a"]["title"] == "nyare")
        m2 = {n["id"]: n for n in N.parse(N.merge_raw(old, new))}
        check("merge är oberoende av ordning", m2["a"]["title"] == "nyare" and set(m2) == {"a", "b", "c"})

        # ---- backup ----
        from core.store import TaskStore
        data = tmp / "data"
        store = TaskStore(data_dir_override=data)
        store.add_task("en uppgift")
        store.save()
        ns = N.NotesStore(store.data_dir)
        keep = ns.add("Viktigt", "ska med i backupen")
        z = TB.create_backup(store, dest=tmp / "bk")
        with zipfile.ZipFile(z) as zf:
            names = set(zf.namelist())
        check("manuell backup innehåller notes.json", "notes.json" in names)
        info = TB.inspect_backup(z)
        check("inspect_backup räknar anteckningarna", info["notes"] == 1, info)
        ns.add("Skrivs efter backupen", "")
        ns.delete(keep["id"])
        res = TB.restore_backup(store, z)
        got = {n["title"] for n in N.NotesStore(store.data_dir).notes()}
        check("återställning: den raderade är tillbaka OCH den nyare behålls (sammanslagning)", got == {"Viktigt", "Skrivs efter backupen"}, got)
        check("återställning rapporterar antal anteckningar", res.get("notes") == 2, res)
        # automatisk backup
        auto = tmp / "auto"
        zp = TB.snapshot_external(store.data_dir, dest=auto)
        with zipfile.ZipFile(zp) as zf:
            check("automatisk backup innehåller notes.json", "notes.json" in zf.namelist())
        NotesPath = Path(store.data_dir) / "notes.json"
        before = len(list(auto.glob("*.zip")))
        time.sleep(1.1)
        N.NotesStore(store.data_dir).add("ändring", "ger ny auto-backup")
        TB.snapshot_external(store.data_dir, dest=auto)
        check("ändrade anteckningar utlöser en ny automatisk backup", len(list(auto.glob("*.zip"))) == before + 1)
        notes_now = {n["title"] for n in N.NotesStore(store.data_dir).notes()}
        NotesPath.unlink()
        r = TB.restore_if_missing(store.data_dir, source=auto)
        check("saknas notes.json vid start läses den in från senaste auto-backup", r.get("notes") is True and {n["title"] for n in N.NotesStore(store.data_dir).notes()} == notes_now, r)
        # användare utan anteckningar: ingenting skapas
        clean = tmp / "clean"
        st2 = TaskStore(data_dir_override=clean)
        st2.add_task("x")
        st2.save()
        auto2 = tmp / "auto2"
        TB.snapshot_external(clean, dest=auto2)
        r2 = TB.restore_if_missing(clean, source=auto2)
        check("utan anteckningar i någon backup skapas ingen notes.json", r2.get("notes") is False and not (clean / "notes.json").exists())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ---- källkod ----
    src = (ROOT / "core" / "notes.py").read_text(encoding="utf-8")
    check("core/notes.py importerar inte Qt", "PySide6" not in src)
    check("sparas inte utanför appmappen (inga %APPDATA%/home-sökvägar)", "APPDATA" not in src and "expanduser" not in src and "Path.home" not in src)
    ui_src = (ROOT / "ui" / "notes_view.py").read_text(encoding="utf-8")
    check("fliken skriver ingenting själv (all lagring i core/notes.py)", "open(" not in ui_src and "write_text" not in ui_src)
    check("manualen beskriver fliken", "Anteckningar" in (ROOT / "docs" / "MANUAL.md").read_text(encoding="utf-8") and "notes.json" in (ROOT / "docs" / "MANUAL.md").read_text(encoding="utf-8"))


def child() -> None:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox, QVBoxLayout, QWidget
    app = QApplication([])
    from core import notes as N
    from core import tag_colors as tc
    from core.settings import Settings
    from core.store import TaskStore
    import widget as W
    from ui import notes_view as NV

    res: list = []

    def ck(name, cond, extra=""):
        res.append((name + (f" {extra}" if not cond and extra else ""), bool(cond)))

    tmp = tempfile.mkdtemp(prefix="ledgebord_notesui_")
    ns = N.NotesStore(Path(tmp) / "n")
    v = NV.NotesView(ns)
    v.resize(430, 640)
    v.show()
    app.processEvents()
    ck("tom lista visar en vänlig text och knappen ➕", v.empty.isVisible() and "Inga anteckningar" in v.empty.text() and not v.list.isVisible() and v.btn_new.isVisible())
    v.btn_new.click()
    app.processEvents()
    ck("➕ öppnar redigeraren med en ny, tom anteckning (rubrikfältet har fokus)", v.stack.currentIndex() == 1 and ns.count() == 1 and v.title_edit.hasFocus() or v.stack.currentIndex() == 1 and ns.count() == 1)
    nid = v.current_id()
    v.title_edit.setText("Kundmöte")
    v.body_edit.setPlainText("Ta med offert\nRing före 10")
    ck("text → 'Sparar …' tills den sparats", "Sparar" in v.status.text())
    ck("ännu inte på disk (väntar på autospar)", N.NotesStore(Path(tmp) / "n").get(nid)["body"] == "")
    t0 = time.time()
    while time.time() - t0 < 2.0 and N.NotesStore(Path(tmp) / "n").get(nid)["body"] == "":
        app.processEvents()
        time.sleep(0.05)
    got = N.NotesStore(Path(tmp) / "n").get(nid)
    ck("autospar efter ~0,7 s utan att trycka Spara", got["title"] == "Kundmöte" and got["body"] == "Ta med offert\nRing före 10", got)
    ck("status säger sparat", "✓ Sparat" in v.status.text())
    v.body_edit.setPlainText("Ta med offert\nRing före 10\nSkicka faktura")
    v.btn_back.click()
    ck("← tillbaka sparar direkt (utan att vänta på timern)", N.NotesStore(Path(tmp) / "n").get(nid)["body"].endswith("Skicka faktura") and v.stack.currentIndex() == 0)
    ck("listan visar anteckningen med rubrik och förhandsvisning", v.list.count() == 1 and "Kundmöte" in v.list.item(0).text() and "Ta med offert" in v.list.item(0).text(), v.list.item(0).text())
    ck("antal visas", "1 anteckning" in v.hint.text(), v.hint.text())
    # andra anteckningen + fäst
    v.new_note()
    v.title_edit.setText("Ideer")
    v.body_edit.setPlainText("hemsida")
    v.btn_pin.click()
    ck("📌 fäster anteckningen", ns.get(v.current_id())["pinned"] and v.btn_pin.isChecked())
    pin_id = v.current_id()
    v.show_list()
    ck("fäst ligger överst och har 📌 i listan", v.list.item(0).data(Qt.ItemDataRole.UserRole) == pin_id and "📌" in v.list.item(0).text(), v.list.item(0).text())
    # sök
    v.search.setText("faktura")
    ck("sök filtrerar listan (text, inte bara rubrik)", v.list.count() == 1 and "Kundmöte" in v.list.item(0).text() and "visar 1" in v.hint.text(), v.hint.text())
    v.search.setText("zzz")
    ck("ingen träff: tydligt meddelande", v.empty.isVisible() and "matchar" in v.empty.text() and not v.list.isVisible())
    v.search.clear()
    # öppna via klick
    v.list.itemClicked.emit(v.list.item(1))
    ck("klick på en anteckning öppnar den i redigeraren med text", v.stack.currentIndex() == 1 and v.title_edit.text() == "Kundmöte" and "Skicka faktura" in v.body_edit.toPlainText())
    # kopiera
    v.copy_current()
    from PySide6.QtGui import QGuiApplication
    ck("📋 kopierar rubrik + text", QGuiApplication.clipboard().text().startswith("Kundmöte\n\nTa med offert"), QGuiApplication.clipboard().text()[:40])
    # byte av flik/dölj sparar
    v.body_edit.setPlainText("ändrad vid döljning")
    v.hide()
    ck("döljs vyn (flikbyte/tray) sparas texten direkt", N.NotesStore(Path(tmp) / "n").get(v.current_id())["body"] == "ändrad vid döljning")
    v.show()
    # radera: nej / ja
    orig = QMessageBox.question
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
    try:
        v.delete_current()
    finally:
        QMessageBox.question = orig
    ck("radera: Nej behåller anteckningen", ns.count() == 2 and v.stack.currentIndex() == 1)
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    try:
        v.delete_current()
    finally:
        QMessageBox.question = orig
    ck("radera: Ja tar bort den och går till listan", ns.count() == 1 and v.stack.currentIndex() == 0 and v.list.count() == 1)
    # tangenter i editorn
    v.list.itemClicked.emit(v.list.item(0))
    v.body_edit.setPlainText("")
    v.body_edit.setFocus()
    QTest.keyClicks(v.body_edit, "a b")
    ck("mellanslag och bokstäver skrivs i editorn", v.body_edit.toPlainText() == "a b", v.body_edit.toPlainText())
    ck("flush() utan ändring är ofarligt", v.flush() is True)
    v.flush()
    # tema: kontrast
    for dark, fg, surf in ((False, "#111827", "#ffffff"), (True, "#f3f4f6", "#1f2937")):
        ss = NV.build_stylesheet(dark, "#4F46E5", fg, "#6b7280" if not dark else "#9ca3af", "#cbd5e1", surf, 12)
        ck(f"QSS ({'mörkt' if dark else 'ljust'}) har regler för alla delar", all(k in ss for k in ("notesBody", "notesTitle", "notesList", "notesNew", "notesBtn", "notesSearch")))
        ck(f"text mot yta ≥ 4.5:1 ({'mörkt' if dark else 'ljust'})", tc.contrast(fg, surf) >= 4.5)
    ck("valt objekt i listan: text mot accent ≥ 4.5:1", tc.contrast("#4F46E5", tc.text_color_for("#4F46E5")) >= 4.5)
    v.hide()

    # --- fönstret ---
    settings = Settings(str(Path(tmp) / "settings.json"))
    store = TaskStore(data_dir_override=Path(tmp) / "data")
    store.add_task("En uppgift")
    shell = QWidget()
    w = W.TodoWidget(app.primaryScreen(), store, settings, win_id="t", parent=shell)
    lay = QVBoxLayout(shell)
    lay.addWidget(w)
    w._shell = shell
    shell.resize(460, 640)
    shell.show()
    app.processEvents()
    w._rebuild_task_list()
    ck("flik 4 heter 📝 Anteckningar och ligger efter Kalender", w.tabs.count() == 4 and w.tabs.tabText(3) == "📝 Anteckningar" and w.NOTES_TAB_INDEX == 3 and w.tabs.tabText(2).endswith("Kalender"))
    ck("fliken lagrar i uppgifternas datamapp (notes.json bredvid active.json)", Path(w.notes_store.path).parent == Path(store.data_dir))
    w.tabs.setCurrentIndex(3)
    app.processEvents()
    nv = w.notes_view
    nv.btn_new.click()
    nv.title_edit.setText("Via fönstret")
    nv.body_edit.setPlainText("osparat när jag byter flik")
    w.tabs.setCurrentIndex(0)
    app.processEvents()
    ck("flikbyte sparar osparad text", any(n["title"] == "Via fönstret" and n["body"] == "osparat när jag byter flik" for n in N.NotesStore(store.data_dir).notes()))
    w.tabs.setCurrentIndex(3)
    app.processEvents()
    nv.body_edit.setPlainText("osparat vid avslut")
    w._flush_notes()
    ck("_flush_notes() (avslut/uppdatering) sparar direkt", any(n["body"] == "osparat vid avslut" for n in N.NotesStore(store.data_dir).notes()))
    # kortkommandon som stjäl tangenter? skriv Space/Delete/Backspace i editorn medan fönstret är aktivt
    shell.activateWindow()
    nv.body_edit.setFocus()
    nv.body_edit.setPlainText("")
    QTest.keyClicks(nv.body_edit, "x y")
    QTest.keyClick(nv.body_edit, Qt.Key.Key_Left)
    QTest.keyClick(nv.body_edit, Qt.Key.Key_Delete)
    ck("Space/Delete i anteckningen når editorn (stjäls inte av listans kortkommandon)", nv.body_edit.toPlainText() == "x ", nv.body_edit.toPlainText())
    ck("uppgiftslistans tangentbordsläge påverkas inte av anteckningsfliken", w.tabs.currentIndex() == 3)
    w.tabs.setCurrentIndex(0)
    # tema-växling ritar om anteckningsfliken
    for dark in (False, True):
        settings.set_theme("dark" if dark else "light")
        w._apply_theme()
        ck(f"temabyte ({'mörkt' if dark else 'ljust'}) ger anteckningsfliken egen QSS", "notesBody" in nv.styleSheet())
    shutil.rmtree(tmp, ignore_errors=True)
    bad = [n for n, ok in res if not ok]
    print("CHILD", len(res) - len(bad), len(bad))
    for n in bad:
        print("  ✗", n)
    sys.stdout.flush()
    os._exit(0)


if "--child" in sys.argv:
    child()
else:
    pure()
    from _qtenv import qt_env

    work = Path(tempfile.mkdtemp(prefix="ledgebord_notes_q_"))
    env, why = qt_env(work)
    if env is None:
        print(f"notes_test: Qt-delen hoppas över ({why})")
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
            check("barnprocessen körde klart", False, (r.stdout + r.stderr)[-2500:])
    shutil.rmtree(work, ignore_errors=True)
    print(f"\nnotes_test: {_ok} lyckades, {_fail} misslyckades")
    sys.exit(1 if _fail else 0)
