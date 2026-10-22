#!/usr/bin/env python3
"""
links_ui_test.py — F1-översikten, länkar/bilagor på korten och skyddet för arkiverade uppgifter i UI:t.

Kör:  python tester/links_ui_test.py
Bygger en riktig TodoWidget (offscreen) i en egen process. Dialoger och webbläsare ersätts med spioner.
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
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QVBoxLayout, QWidget

    app = QApplication([])
    from core.settings import Settings
    from core.store import TaskStore
    from core import attachments as att
    import widget as W

    res: list = []

    def ck(name, cond, extra=""):
        res.append((name + (" " + str(extra) if not cond and extra else ""), bool(cond)))

    tmp = Path(tempfile.mkdtemp(prefix="taskbord_links_"))
    settings = Settings(str(tmp / "settings.json"))
    store = TaskStore(data_dir_override=tmp / "data")
    shell = QWidget()
    w = W.TodoWidget(app.primaryScreen(), store, settings, win_id="t", parent=shell)
    lay = QVBoxLayout(shell)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(w)
    w._shell = shell
    shell.resize(420, 640)
    shell.show()
    shell.activateWindow()
    app.processEvents()
    w._rebuild_task_list()
    app.processEvents()
    ck("fönstret är aktivt i testet", app.activeWindow() is shell)

    # --- spioner ----------------------------------------------------------------------------
    opened, dialogs = [], []
    LA = sys.modules["ui.widget_parts.links_attach"]

    class FakeDS:
        @staticmethod
        def openUrl(u):
            opened.append(u.toString())
            return True

    LA.QDesktopServices = FakeDS
    answer = {"q": QMessageBox.StandardButton.No}
    QMessageBox.information = staticmethod(lambda *a, **k: dialogs.append(("info", a[1:3])) or 0)
    QMessageBox.warning = staticmethod(lambda *a, **k: dialogs.append(("warn", a[1:3])) or 0)
    QMessageBox.question = staticmethod(lambda *a, **k: (dialogs.append(("q", a[1:3])), answer["q"])[1])
    menus: list = []

    class FakeMenu(QMenu):
        def exec(self, *a, **k):  # noqa: A003
            menus.append([x.text() for x in self.actions()])
            return None

    for _m in ("window_ops", "task_menu", "links_attach"):
        sys.modules[f"ui.widget_parts.{_m}"].QMenu = FakeMenu

    def wait(cond, ms=3000):
        t = 0
        while not cond() and t < ms:
            QTest.qWait(20)
            t += 20
        return cond()

    # ======================= F1 =======================================================================
    import ui.shortcut_help_dialog as HD
    calls = []
    HD.open_shortcut_help = lambda parent=None, settings=None: calls.append(settings) or True
    f1 = [sc for sc in w._hotkey_shortcuts if sc.key().toString() == "F1"]
    ck("F1 är registrerad som kortkommando", len(f1) == 1)
    QTest.keyClick(w.input_field, Qt.Key.Key_F1)
    app.processEvents()
    ck("F1 i inmatningsfältet öppnar tangentöversikten", len(calls) == 1 and calls[0] is settings)
    QTest.keyClick(w, Qt.Key.Key_F1)
    ck("F1 på fönstret öppnar den också", len(calls) == 2)
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QContextMenuEvent
    w.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(5, 5), QPoint(5, 5)))
    ck("…och den finns i menyn", any(any("Tangentöversikt" in t for t in m) for m in menus))
    ck("…tillsammans med 'Hämta sidtitlar'", any(any("sidtitlar" in t for t in m) for m in menus))
    # äkta dialogen (utan exec) med användarens inställningar
    settings.set_quick_add_hotkey("Ctrl+Shift+Q")
    d = HD.ShortcutHelpDialog(None, settings=settings)
    txt = d.view.toPlainText()
    ck("dialogen visar F1 och F3", "F1" in txt and "F3" in txt)
    ck("dialogen visar listtangenterna", "Mellanslag" in txt and "Dubbelklick" in txt)
    ck("dialogen visar användarens egna kombination (Windows)" if sys.platform == "win32" else "på Linux: ingen global-lista men förklaring",
       ("Ctrl+Shift+Q" in txt) if sys.platform == "win32" else ("Finns bara i Windows" in txt))
    ck("kopiera-som-text innehåller samma rubriker", "Musen" in d.text())
    # en egen F1-tilldelning i inställningarna ska inte krocka (F1 är reserverad)
    settings.set_shortcut("edit_task", "F1")
    w._unregister_hotkeys()
    w._register_hotkeys()
    f1 = [sc for sc in w._hotkey_shortcuts if sc.key().toString() == "F1"]
    ck("F1 tilldelad av användaren ger ingen dubbel-genväg", len(f1) == 1)
    settings.set_shortcut("edit_task", "F2")
    w._unregister_hotkeys()
    w._register_hotkeys()

    # ======================= länk via inmatningsfältet ==================================================
    from ui.link_titles import LinkTitleFetcher
    fetched = []
    w._link_fetcher = LinkTitleFetcher(store, w, fetch=lambda u: fetched.append(u) or "Exempelsidans titel")
    w.input_field.setText("läs https://www.exempel.se/2026-10-22/artikel?x=1 imorgon")
    w._on_input_submit()
    app.processEvents()
    t1 = [t for t in store.active_tasks() if t["title"].startswith("läs")]
    ck("URL:en tas ur titeln", t1 and t1[0]["title"] == "läs" and t1[0].get("due_date"))
    ck("…och blir en länk", t1 and t1[0]["links"][0]["url"] == "https://www.exempel.se/2026-10-22/artikel?x=1")
    ck("datumet i URL:en tolkades inte (due=imorgon)", t1 and str(t1[0]["due_date"])[:10] != "2026-10-22")
    ck("sidtiteln hämtades i bakgrunden", wait(lambda: store.find_task(t1[0]["id"])["links"][0]["title"] == "Exempelsidans titel"))
    ck("titeln på uppgiften är orörd (användaren skrev en egen)", store.find_task(t1[0]["id"])["title"] == "läs")
    w._rebuild_task_list(); app.processEvents()
    chips = w._task_widgets[t1[0]["id"]].findChildren(W.LinkChip)
    ck("kortet visar en länk-chip med sidtiteln", len(chips) == 1 and "Exempelsidans titel" in chips[0].text())
    ck("chipen har klickbar pekare + tooltip med URL", chips and chips[0].cursor().shape() == Qt.CursorShape.PointingHandCursor and "exempel.se" in chips[0].toolTip())
    chips[0].clicked.emit(chips[0].key())
    ck("klick öppnar länken i webbläsaren", opened == ["https://www.exempel.se/2026-10-22/artikel?x=1"])
    QTest.mouseClick(chips[0], Qt.MouseButton.LeftButton)
    ck("riktigt musklick öppnar också", len(opened) == 2)

    # bara en URL → platshållare = värdnamn, sedan sidans titel
    w.input_field.setText("https://www.nyheter.se/a")
    w._on_input_submit()
    t2 = [t for t in store.active_tasks() if t.get("links") and t["links"][0]["url"] == "https://www.nyheter.se/a"][0]
    ck("bara-URL: uppgiften får titeln från sidan", wait(lambda: store.find_task(t2["id"])["title"] == "Exempelsidans titel"))

    # användaren hann byta namn → titeln skrivs inte över
    w._link_fetcher = LinkTitleFetcher(store, w, fetch=lambda u: (QTest.qWait(150), "Sen titel")[1])
    w.input_field.setText("https://slow.example.org/x")
    w._on_input_submit()
    t3 = [t for t in store.active_tasks() if t.get("links") and "slow.example.org" in t["links"][0]["url"]][0]
    ck("platshållaren är värdnamnet", t3["title"] == "slow.example.org")
    store.update_task_title(t3["id"], "Mitt eget namn")
    ck("länktiteln sätts ändå", wait(lambda: store.find_task(t3["id"])["links"][0]["title"] == "Sen titel"))
    ck("…men ett eget namn skrivs aldrig över", store.find_task(t3["id"])["title"] == "Mitt eget namn")

    # inställningen av → ingen hämtning
    settings.set_links_fetch_titles(False)
    n = len(fetched)
    ck("hämtning av: _start_link_title_fetch → False", w._start_link_title_fetch(t3["id"], "https://a.se") is False)
    w.input_field.setText("https://tyst.example.org")
    w._on_input_submit()
    app.processEvents(); QTest.qWait(150)
    ck("hämtning av: inget nätverksanrop gjordes", len(fetched) == n)
    ck("hämtning av: länken finns ändå (värdnamn)", any(t.get("links") and "tyst.example.org" in t["links"][0]["url"] for t in store.active_tasks()))
    settings.set_links_fetch_titles(True)

    # menyvalet 'Lägg till länk…' (dialog ersatt)
    from PySide6.QtWidgets import QInputDialog
    QInputDialog.getText = staticmethod(lambda *a, **k: ("https://via-meny.example.net/p", True))
    tid_menu = store.add_task("Meny")
    w._prompt_add_link(tid_menu)
    ck("Lägg till länk… sparar länken", store.find_task(tid_menu)["links"][0]["url"] == "https://via-meny.example.net/p")
    QInputDialog.getText = staticmethod(lambda *a, **k: ("inte en länk", True))
    w._prompt_add_link(tid_menu)
    ck("ogiltig adress ger ett meddelande, ingen länk", len(store.find_task(tid_menu)["links"]) == 1 and dialogs and dialogs[-1][0] == "info")

    # ======================= bilagor =======================================================================
    f = tmp / "Offert 2026.pdf"
    f.write_bytes(b"%PDF-1.4 test")
    bat = tmp / "kör mig.bat"
    bat.write_text("echo hej")
    ok, errs = w._attach_files(tid_menu, [str(f), str(bat), str(tmp / "finns-inte.txt")])
    ck("två filer bifogades, en saknad gav fel", ok == 2 and len(errs) == 1)
    d_att = Path(store.data_dir) / "attachments" / tid_menu
    ck("filerna KOPIERADES in i appens datamapp", (d_att / "Offert 2026.pdf").is_file() and f.exists())
    ck("…och ligger inte utanför appmappen/datamappen", str(d_att).startswith(str(tmp / "data")))
    w._rebuild_task_list(); app.processEvents()
    achips = [c for c in w._task_widgets[tid_menu].findChildren(W.LinkChip) if c.property("chipKind") == "attachment"]
    ck("kortet visar 📎-chips", len(achips) == 2 and "Offert 2026.pdf" in achips[0].text() and "📎" in achips[0].text())
    opened.clear()
    achips[0].clicked.emit(achips[0].key())
    ck("klick på bilagan öppnar den kopierade filen", len(opened) == 1 and opened[0].startswith("file://") and "Offert" in opened[0])
    opened.clear()
    answer["q"] = QMessageBox.StandardButton.No
    w._open_attachment(tid_menu, "attachments/%s/kör mig.bat" % tid_menu)
    ck("körbar filtyp: frågar först och öppnar inte vid Nej", not opened and dialogs[-1][0] == "q")
    answer["q"] = QMessageBox.StandardButton.Yes
    w._open_attachment(tid_menu, "attachments/%s/kör mig.bat" % tid_menu)
    ck("…öppnar vid Ja", len(opened) == 1)
    (d_att / "Offert 2026.pdf").unlink()
    w._rebuild_task_list(); app.processEvents()
    achips = [c for c in w._task_widgets[tid_menu].findChildren(W.LinkChip) if c.property("chipKind") == "attachment"]
    ck("saknad fil markeras med ⚠", any("⚠" in c.text() and "saknas" in c.toolTip() for c in achips))
    opened.clear(); dialogs.clear()
    w._open_attachment(tid_menu, "attachments/%s/Offert 2026.pdf" % tid_menu)
    ck("saknad fil öppnas inte, ger meddelande", not opened and dialogs and dialogs[-1][0] == "info")
    ck("sökväg utanför bilagemappen öppnas aldrig", (w._open_attachment(tid_menu, "../../settings.json"), not opened)[1])
    answer["q"] = QMessageBox.StandardButton.No
    ck("ta bort bilaga: Nej behåller", w._remove_attachment(tid_menu, "attachments/%s/kör mig.bat" % tid_menu) is False and (d_att / "kör mig.bat").exists())
    answer["q"] = QMessageBox.StandardButton.Yes
    ck("ta bort bilaga: Ja raderar kopian", w._remove_attachment(tid_menu, "attachments/%s/kör mig.bat" % tid_menu) and not (d_att / "kör mig.bat").exists())

    # raderar aktiv uppgift med bilaga: varnar + städar
    f2 = tmp / "extra.txt"; f2.write_text("x")
    w._attach_files(tid_menu, [str(f2)])
    dialogs.clear()
    w._prompt_delete(tid_menu)
    ck("borttagningsdialogen nämner bilagorna", dialogs and "bifogade" in str(dialogs[-1][1]))
    ck("uppgiften och bilagemappen är borta", store.find_task(tid_menu) is None and not d_att.exists())

    # många chips → '+N till'
    tid_many = store.add_task("Många")
    for i in range(9):
        store.add_link(tid_many, f"https://m{i}.example.com", "")
    w._rebuild_task_list(); app.processEvents()
    ch = w._task_widgets[tid_many].findChildren(W.LinkChip)
    ck("högst 6 länkar + '+3 till…'", len(ch) == 7 and "+3" in ch[-1].text())
    ck("långa titlar kortas", len(W.LinkChip.elide("x" * 100, 30)) <= 30)

    # ======================= arkivet är historik ======================================================
    tid_arch = store.add_task("Historik")
    store.add_link(tid_arch, "https://hist.example.com", "Hist")
    store.archive_task(tid_arch)
    menus.clear(); dialogs.clear()
    w._show_task_menu(dict(store.find_task(tid_arch)))
    items = menus[-1] if menus else []
    ck("arkiverad uppgift: menyn saknar 'Ta bort…'", items and not any("Ta bort" in t for t in items), str(items))
    ck("…och visar 'Historik — sparas för alltid'", any("sparas för alltid" in t for t in items))
    ck("…men har 'Lägg till länk…' och 'Bifoga fil…'", any("Lägg till länk" in t for t in items) and any("Bifoga" in t for t in items))
    menus.clear()
    w._show_task_menu(dict(store.find_task(tid_many)))
    ck("aktiv uppgift: menyn har 'Ta bort…'", menus and any("Ta bort" in t for t in menus[-1]))
    answer["q"] = QMessageBox.StandardButton.Yes
    dialogs.clear()
    w._prompt_delete(tid_arch)
    ck("_prompt_delete på arkiverad: förklarar, frågar inte", dialogs and dialogs[-1][0] == "info" and "sparas för alltid" in str(dialogs[-1][1]))
    ck("…uppgiften finns kvar", store.is_archived(tid_arch))
    dialogs.clear()
    w._on_delete_clicked(tid_arch, "Historik")
    ck("_on_delete_clicked på arkiverad: förklarar, frågar inte", dialogs and dialogs[-1][0] == "info")
    ck("…uppgiften finns kvar efter Ja-svar", store.is_archived(tid_arch) and store.find_task(tid_arch) is not None)
    w.keyPressEvent  # Delete via listan går till _prompt_delete (täcks ovan)
    w.tabs.setCurrentIndex(1); app.processEvents()
    w._rebuild_task_list(); app.processEvents()
    ck("arkivfliken förklarar historiken i tooltip", "sparas" in w.tabs.tabToolTip(1))
    ck("arkiverat kort visar sin länk", any("Hist" in c.text() for c in w.findChildren(W.LinkChip)))
    w.tabs.setCurrentIndex(0)

    # ======================= urklipps-snabbtangenten (Ctrl+Alt+K) ===========================
    import logging
    from app.mixins.clip_task import ClipTaskMixin

    class Ctl(ClipTaskMixin):
        _tray = None
        _log = logging.getLogger("TaskBord")

        def __init__(self):
            self.store, self.settings = store, settings

        def _update_tray_tooltip(self):
            pass

    ctl = Ctl()
    ctl._clip_link_fetcher = LinkTitleFetcher(store, None, fetch=lambda u: "Urklippssidan")
    ctl._clip_task_done("https://www.klipp.example.com/a", "urklipp")
    tk = [t for t in store.active_tasks() if t.get("links") and "klipp.example.com" in t["links"][0]["url"]]
    ck("urklipp: en URL blir en uppgift med länk", len(tk) == 1 and tk[0]["title"] == "klipp.example.com")
    ck("urklipp: sidtiteln sätts + byter platshållartiteln", tk and wait(lambda: store.find_task(tk[0]["id"])["title"] == "Urklippssidan"))
    ctl._clip_task_done("ring Anna om https://a.example.com/x", "urklipp")
    tk2 = [t for t in store.active_tasks() if t["title"].startswith("ring Anna")]
    ck("urklipp: text + URL: titeln utan URL, länken separat", tk2 and tk2[0]["title"] == "ring Anna om" and tk2[0].get("links"))

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

    work = Path(tempfile.mkdtemp(prefix="taskbord_linkstest_"))
    env, why = qt_env(work)
    if env is None:
        print(f"links_ui_test: Qt-delen hoppas över ({why})")
    else:
        r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--child"], cwd=ROOT, env=env,
                           capture_output=True, text=True, timeout=300)
        line = [l for l in r.stdout.splitlines() if l.startswith("CHILD ")]
        if line:
            _, a, b = line[-1].split()
            _ok += int(a)
            _fail += int(b)
            for l in r.stdout.splitlines():
                if l.strip().startswith("✗"):
                    print(l)
        else:
            check("barnprocessen körde klart", False, (r.stdout + r.stderr)[-2500:])
    shutil.rmtree(work, ignore_errors=True)
    print(f"\nlinks_ui_test: {_ok} lyckades, {_fail} misslyckades")
    sys.exit(1 if _fail else 0)
