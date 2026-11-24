#!/usr/bin/env python3
"""
edge_handle_test.py — fliken som sitter kvar i skärmkanten när Ledgebord är gömt (ui/edge_handle.py + core/edge_dock.py)
och att dockat fönster läggs över andra program. Kör:  python tester/edge_handle_test.py
"""
from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import suppress
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


def lum(h):
    v = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    v = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in v]
    return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]


def cr(a, b):
    hi, lo = max(lum(a), lum(b)), min(lum(a), lum(b))
    return (hi + 0.05) / (lo + 0.05)


def pure() -> None:
    from core import edge_dock as E
    S = (0, 0, 1536, 816)
    shown_top = (500, 0, 340, 700)
    r = E.handle_rect(shown_top, S, "top", 150)
    check("topp: fliken mitt för fönstret, tätt mot kanten", r == (595, 0, 150, E.HANDLE_THICK), r)
    check("topp: hålls inom skärmen (vänster)", E.handle_rect((0, 0, 340, 700), S, "top", 400)[0] == 0 or E.handle_rect((0, 0, 100, 700), S, "top", 400)[0] == 0)
    check("topp: hålls inom skärmen (höger)", E.handle_rect((1400, 0, 136, 700), S, "top", 300)[0] + 300 == 1536)
    rl = E.handle_rect((0, 100, 340, 600), S, "left", 150)
    check("vänster: mitt för fönstrets höjd", rl == (0, 325, E.HANDLE_THICK, 150), rl)
    rr = E.handle_rect((1196, 100, 340, 600), S, "right", 150)
    check("höger: tätt mot högerkanten", rr == (1536 - E.HANDLE_THICK, 325, E.HANDLE_THICK, 150), rr)
    check("minsta längd", E.handle_rect(shown_top, S, "top", 10)[2] == E.HANDLE_MIN_LEN)
    check("okänd kant ger fel", _raises(lambda: E.handle_rect(shown_top, S, "bottom", 100)))
    check("point_in: innanför/utanför/tolerans", E.point_in((600, 5), r) and not E.point_in((594, 5), r) and E.point_in((594, 5), r, 1) and not E.point_in((600, 22), r))
    tasks = [{"title": "a", "due_date": "2026-11-01"}, {"title": "b", "due_date": "2026-11-20"}, {"title": "c", "done": True, "due_date": "2026-01-01"},
             {"title": "d"}, {"title": "e", "due_date": "2026-11-17T09:00"}]
    check("antal: aktiva och försenade (klara räknas inte, idag är inte försenad)", E.handle_counts(tasks, "2026-11-17") == (4, 1), E.handle_counts(tasks, "2026-11-17"))
    check("antal: tomt", E.handle_counts([], "2026-11-17") == (0, 0))
    check("text: aktiva", E.handle_text(6, 0) == "Ledgebord · 6" and E.handle_text(0, 0) == "Ledgebord")
    check("text: försenade (singular/plural)", E.handle_text(6, 1) == "1 försenad" and E.handle_text(6, 3) == "3 försenade")
    from ui import edge_handle as H
    for nm, bg in (("normal", H.COLORS["normal"]), ("hover", H.COLORS["hover"]), ("överdue", H.COLORS["overdue"]),
                   ("överdue hover", H.COLORS["overdue_hover"]), ("kontrast", H.COLORS["contrast"])):
        check(f"fliken läsbar ({nm}): vit text ≥ 4,5:1 ({cr(H.TEXT, bg):.1f})", cr(H.TEXT, bg) >= 4.5)
    check("bg_color väljer rätt", H.bg_color(False, False, False) == H.COLORS["normal"] and H.bg_color(True, True, False) == H.COLORS["overdue_hover"]
          and H.bg_color(True, False, True) == H.COLORS["contrast"])
    # nivån: controller-metoden
    src = (ROOT / "app/mixins/top_toggle.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for c in tree.body if isinstance(c, ast.ClassDef) for n in c.body if isinstance(n, ast.FunctionDef) and n.name == "_on_dock_level")
    ns = {"suppress": suppress, "LOG_PREFIX": "[T]"}
    exec(compile(ast.Module([fn], []), "x", "exec"), ns)

    class Log:
        def warning(self, *a, **k): pass
        def info(self, *a, **k): pass

    class Set:
        def __init__(self, mode):
            self.mode = mode
            self.prefs = {"dock_forced_top": False}
            self.prev = "behind"

        def pref(self, k): return self.prefs[k]
        def set_pref(self, k, v): self.prefs[k] = v; return True
        def set_top_toggle_prev_mode(self, m): self.prev = m
        def top_toggle_prev_mode(self): return self.prev

    class Stub:
        _log = Log()
        _on_dock_level = ns["_on_dock_level"]

        def __init__(self, mode):
            self.settings = Set(mode)
            self.mode = mode

        def _desktop_mode(self): return self.mode
        def _set_desktop_mode(self, m): self.mode = m

    s = Stub("above")
    s._on_dock_level(True)
    check("dockat från skrivbordsläge → läget blir 'top' och minns förra", s.mode == "top" and s.settings.prev == "above" and s.settings.prefs["dock_forced_top"])
    s._on_dock_level(False)
    check("dockning släppt → förra läget tillbaka", s.mode == "above" and not s.settings.prefs["dock_forced_top"])
    s = Stub("top")
    s._on_dock_level(True)
    s._on_dock_level(False)
    check("redan 'top': dockning ändrar inget", s.mode == "top" and not s.settings.prefs["dock_forced_top"])
    s = Stub("behind")
    s._on_dock_level(True)
    s.settings.prefs["dock_forced_top"] = False   # användaren växlade själv under tiden
    s._on_dock_level(False)
    check("användaren växlade själv → läget lämnas som det är", s.mode == "top")
    tt = (ROOT / "app/mixins/top_toggle.py").read_text(encoding="utf-8")
    check("manuell växling nollställer minnet", 'set_pref("dock_forced_top", False)' in tt)
    wn = (ROOT / "app/mixins/windows.py").read_text(encoding="utf-8")
    check("signalen är kopplad till controllern", "dock_level_requested.connect(self._on_dock_level)" in wn)
    doc = (ROOT / "docs/MANUAL.md").read_text(encoding="utf-8")
    check("MANUAL beskriver fliken", "flik" in doc and "Dölj i skärmkanten" in doc and "över andra program" in doc)


def _raises(f):
    try:
        f()
    except Exception:
        return True
    return False


def child() -> None:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
    app = QApplication([])
    from core.settings import Settings
    from core.store import TaskStore
    import widget as W
    import ui.edge_dock as ED
    from ui import edge_handle as H
    res = []

    def ck(n, c, e=""):
        res.append((n + (f" {e}" if not c and e else ""), bool(c)))
    ED.HIDE_DELAY_S = 0.06

    def wait(cond, ms=3000):
        t = 0
        while not cond() and t < ms:
            QTest.qWait(20)
            t += 20
        return cond()

    tmp = Path(tempfile.mkdtemp(prefix="ledgebord_handle_"))
    S = (0, 0, 1536, 864)
    screens = [(S, S)]
    cur = {"p": (700, 400)}
    settings = Settings(str(tmp / "s.json"))
    store = TaskStore(data_dir_override=tmp / "d")
    store.add_task("Försenad", due_date="2020-01-01")
    store.add_task("Idag-ish", due_date="2999-01-01")
    store.add_task("Utan datum")
    shell = QWidget()
    w = W.TodoWidget(app.primaryScreen(), store, settings, win_id="t", parent=shell)
    lay = QVBoxLayout(shell)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(w)
    w._shell = shell
    shell.resize(340, 648)
    shell.show()
    shell.move(500, 100)
    app.processEvents()
    levels = []
    w.dock_level_requested.connect(levels.append)
    fronts = []
    dk = ED.EdgeDocker(w, settings, "t", screens_fn=lambda: screens, cursor_fn=lambda: cur["p"], buttons_fn=lambda: False, anim_ms=40)
    w._edge_dock = dk

    ck("ingen flik innan dockning", dk.handle_zone() is None)
    ck("dock_now top ok", dk.dock_now("top") == "" and dk.state == "shown")
    ck("dockning ber appen lägga fönstret över andra program", levels == [True], levels)
    ck("flik syns inte medan fönstret är framme", dk.handle_zone() is None)
    cur["p"] = (300, 700)
    ck("fönstret gömmer sig", wait(lambda: dk.state == "hidden"))
    ck("…och då syns fliken", wait(lambda: dk.handle_zone() is not None))
    z = dk.handle_zone()
    h = dk._handle
    ck("fliken ligger i övre kanten mitt för fönstret", z[1] == 0 and z[3] == 22 and abs((z[0] + z[2] // 2) - (shell.x() + shell.width() // 2)) <= 3, (z, shell.x()))
    ck("fliken är ett eget, ofokuserbart verktygsfönster överst", bool(h.windowFlags() & Qt.WindowType.WindowStaysOnTopHint) and bool(h.windowFlags() & Qt.WindowType.Tool)
       and bool(h.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus))
    ck("texten visar försenade (röd flik)", h._text == "1 försenad" and h._overdue, h._text)
    ck("tooltip förklarar", "2 aktiva" in h.toolTip() and "1 försenade" in h.toolTip() or "försenade" in h.toolTip(), h.toolTip())
    ck("tillgängligt namn finns", h.accessibleName().startswith("Ledgebord"))
    # ritning
    img = h.grab().toImage()
    mid = img.pixelColor(img.width() // 2, img.height() - 3).name().upper()
    ck("fliken ritas i rött när något är försenat", mid in ("#B91C1C", "#991B1B") or abs(int(mid[1:3], 16) - 0xB9) < 40, mid)
    # kanten utanför fliken visar INTE fönstret längre
    cur["p"] = (shell.x() + 5, 2) if z[0] > shell.x() + 40 else (z[0] + z[2] + 60, 2)
    QTest.qWait(400)
    ck("musen i kanten utanför fliken visar inte fönstret", dk.state == "hidden", dk.state)
    cur["p"] = (z[0] + z[2] // 2, 5)
    ck("musen på fliken visar fönstret", wait(lambda: dk.state == "shown"))
    ck("…fliken försvinner när fönstret är framme", dk.handle_zone() is None)
    cur["p"] = (300, 700)
    wait(lambda: dk.handle_zone() is not None)
    h.clicked.emit()
    ck("klick på fliken visar fönstret direkt", wait(lambda: dk.state == "shown"))
    # tray-gömt fönster → ingen flik
    cur["p"] = (300, 700)
    wait(lambda: dk.handle_zone() is not None)
    shell.hide()
    ck("fönstret gömt till tray → fliken försvinner", wait(lambda: dk.handle_zone() is None))
    shell.show()
    ck("fönstret visas igen → fliken tillbaka", wait(lambda: dk.handle_zone() is not None))
    # hög kontrast
    settings.set_pref("high_contrast", True)
    a_, o_ = dk._handle_counts()
    h.set_info(a_, o_, dk._contrast())
    img = h.grab().toImage()
    ck("hög kontrast: svart flik med vit kant", img.pixelColor(img.width() // 2, img.height() - 4).name().upper() in ("#000000", "#0A0A0A") or img.pixelColor(img.width() // 2, img.height() - 4).lightness() < 40)
    settings.set_pref("high_contrast", False)
    # vänster och höger: lodrät flik
    dk.undock()
    ck("sluta docka → fliken borta och nivån återställs", dk.handle_zone() is None and levels[-1] is False, levels)
    shell.move(500, 100)
    app.processEvents()
    ck("dock_now left", dk.dock_now("left") == "")
    cur["p"] = (900, 500)
    wait(lambda: dk.handle_zone() is not None)
    zl = dk.handle_zone()
    ck("vänster: lodrät flik i vänsterkanten", zl and zl[0] == 0 and zl[2] == 22 and zl[3] >= 96, zl)
    img = dk._handle.grab().toImage()
    ck("lodrät flik ritas (inte tom)", any(img.pixelColor(x, y).alpha() > 0 for x in range(0, img.width(), 3) for y in range(0, img.height(), 6)))
    dk.undock()
    shell.move(500, 100)
    app.processEvents()
    ck("dock_now right", dk.dock_now("right") == "")
    wait(lambda: dk.handle_zone() is not None)
    zr = dk.handle_zone()
    ck("höger: flik i högerkanten", zr and zr[0] + zr[2] == 1536, zr)
    dk.undock()
    # antal utan försenade
    for t in list(store.active_tasks()):
        if t.get("due_date") == "2020-01-01":
            store.remove_task(t["id"])
    shell.move(500, 100)
    app.processEvents()
    dk.dock_now("top")
    cur["p"] = (300, 700)
    wait(lambda: dk.handle_zone() is not None)
    ck("utan försenade: 'Ledgebord · 2' i indigo", dk._handle._text == "Ledgebord · 2" and not dk._handle._overdue, dk._handle._text)
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
    work = Path(tempfile.mkdtemp(prefix="ledgebord_handleq_"))
    env, why = qt_env(work)
    if env is None:
        print(f"Qt-delen hoppas över ({why})")
    else:
        r = subprocess.run([sys.executable, str(Path(sys.argv[0]).resolve()), "--child"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=200)
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
    print(f"\nedge_handle_test: {_ok} lyckades, {_fail} misslyckades")
    sys.exit(1 if _fail else 0)
