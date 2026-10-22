#!/usr/bin/env python3
"""
edge_dock_test.py — dockning vid skärmkant: geometrin (core/edge_dock.py) och EdgeDocker på en riktig
TodoWidget (offscreen) med skenskärmar, skenmus och riktiga släpp-händelser.

Kör:  python tester/edge_dock_test.py
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


def geometry_tests() -> None:
    from core import edge_dock as E
    S = (0, 0, 1536, 864)
    check("detect: nära vänster", E.detect_edge((6, 100, 340, 648), S) == "left")
    check("detect: över kanten räknas", E.detect_edge((-30, 100, 340, 648), S) == "left")
    check("detect: höger", E.detect_edge((1536 - 340 - 3, 100, 340, 648), S) == "right")
    check("detect: övre kanten", E.detect_edge((500, 4, 340, 300), S) == "top")
    check("detect: mitt på skärmen → None", E.detect_edge((400, 100, 340, 648), S) is None)
    check("detect: längre än snap → None", E.detect_edge((15, 100, 340, 648), S) is None)
    check("detect: närmaste kant vinner", E.detect_edge((3, 8, 340, 300), S) == "left")
    check("detect: kant som inte är tillåten → None", E.detect_edge((2, 100, 340, 648), S, allowed={"right"}) is None)
    check("detect: för brett fönster dockas inte åt sidan", E.detect_edge((0, 100, 1400, 300), S) is None)
    check("shown: vänster flush", E.shown_rect((9, 100, 340, 648), S, "left") == (0, 100, 340, 648))
    check("shown: höger flush", E.shown_rect((1190, 100, 340, 648), S, "right") == (1196, 100, 340, 648))
    check("shown: överkant + klampad i sidled", E.shown_rect((-50, 9, 340, 300), S, "top") == (0, 0, 340, 300))
    check("shown: klampas i höjd längs kanten", E.shown_rect((0, 500, 340, 648), S, "left") == (0, 216, 340, 648))
    sh = E.shown_rect((0, 100, 340, 648), S, "left")
    check("hidden: vänster, 5 px kvar", E.hidden_rect(sh, S, "left") == (-335, 100, 340, 648))
    shr = E.shown_rect((1190, 100, 340, 648), S, "right")
    check("hidden: höger, 5 px kvar", E.hidden_rect(shr, S, "right") == (1531, 100, 340, 648))
    sht = E.shown_rect((500, 0, 340, 300), S, "top")
    check("hidden: överkant", E.hidden_rect(sht, S, "top") == (500, -295, 340, 300))
    check("reveal: musen vid vänsterkanten på fönstrets höjd", E.reveal_hit((0, 300), sh, S, "left"))
    check("reveal: över list-bredden räcker", E.reveal_hit((4, 300), sh, S, "left"))
    check("reveal: för långt in → nej", not E.reveal_hit((20, 300), sh, S, "left"))
    check("reveal: vid kanten men utanför fönstrets höjd → nej", not E.reveal_hit((0, 5), sh, S, "left"))
    check("reveal: lite tolerans längs kanten", E.reveal_hit((0, 100 - 10), sh, S, "left"))
    check("reveal: höger", E.reveal_hit((1535, 300), shr, S, "right"))
    check("reveal: övre", E.reveal_hit((600, 0), sht, S, "top") and not E.reveal_hit((100, 0), sht, S, "top"))
    check("reveal: utanför skärmen → nej", not E.reveal_hit((-1, 300), sh, S, "left"))
    check("keep_shown: på fönstret", E.keep_shown((100, 300), sh))
    check("keep_shown: nära (marginal)", E.keep_shown((350, 300), sh))
    check("keep_shown: långt bort → nej", not E.keep_shown((600, 300), sh))
    two = [(0, 0, 1920, 1080), (1920, 0, 1920, 1080)]
    check("outer: vänster skärm saknar högerkant", E.outer_edges(two[0], two) == {"left", "top"})
    check("outer: höger skärm saknar vänsterkant", E.outer_edges(two[1], two) == {"right", "top"})
    check("outer: enda skärm har alla", E.outer_edges(S, [S]) == {"left", "right", "top"})
    stacked = [(0, 0, 1920, 1080), (0, -1080, 1920, 1080)]
    check("outer: skärm ovanför stänger överkanten", "top" not in E.outer_edges(stacked[0], stacked))
    check("screen_for: största överlappet", E.screen_for((1900, 100, 340, 600), two) == two[1])
    check("lerp: start/slut", E.lerp_point((0, 0), (100, 50), 0) == (0, 0) and E.lerp_point((0, 0), (100, 50), 1) == (100, 50))
    check("lerp: monoton", E.lerp_point((0, 0), (100, 0), 0.3)[0] < E.lerp_point((0, 0), (100, 0), 0.6)[0])


def child() -> None:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

    app = QApplication([])
    from core.settings import Settings
    from core.store import TaskStore
    import widget as W
    import ui.edge_dock as ED

    res: list = []

    def ck(name, cond, extra=""):
        res.append((name + (" " + str(extra) if not cond and extra else ""), bool(cond)))

    ED.HIDE_DELAY_S = 0.06

    def wait(cond, ms=3000):
        t = 0
        while not cond() and t < ms:
            QTest.qWait(20)
            t += 20
        return cond()

    tmp = Path(tempfile.mkdtemp(prefix="taskbord_dock_"))
    S = (0, 0, 1536, 864)
    screens = [(S, S)]
    cursor = {"p": (700, 400), "btn": False}

    def build(name):
        settings = Settings(str(tmp / f"{name}.json"))
        store = TaskStore(data_dir_override=tmp / f"data_{name}")
        shell = QWidget()
        w = W.TodoWidget(app.primaryScreen(), store, settings, win_id="t", parent=shell)
        lay = QVBoxLayout(shell)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(w)
        w._shell = shell
        shell.resize(340, 648)
        shell.show()
        shell.move(400, 100)
        app.processEvents()
        dk = ED.EdgeDocker(w, settings, "t", screens_fn=lambda: screens,
                           cursor_fn=lambda: cursor["p"], buttons_fn=lambda: cursor["btn"], anim_ms=40)
        w._edge_dock = dk
        return settings, store, shell, w, dk

    def place(sh, x, y, ww, hh):
        sh.resize(ww, hh)
        sh.move(x, y)
        app.processEvents()

    def near(a, b):  # offscreen-plattformen klampar negativa lägen med ±2 px
        return abs(a - b) <= 2

    def saved(settings):
        return [c for c in settings.window_configs() if c.get("id") == "t"][0]

    def release(w):
        w._drag_active = True
        ev = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(5, 5), QPointF(5, 5),
                         Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
        w.mouseReleaseEvent(ev)
        app.processEvents()

    settings, store, shell, w, dk = build("a")

    # --- släpp mitt på skärmen: inget händer ------------------------------------------------------------
    release(w)
    ck("mitt på skärmen: inte dockat", dk.state == "idle" and shell.x() == 400 and settings.edge_dock_edge() == "", (dk.state, shell.x(), settings.edge_dock_edge()))

    # --- släpp nära vänsterkanten → dockas ----------------------------------------------------------------
    shell.move(7, 100)
    release(w)
    ck("släpp nära vänsterkanten dockar", dk.state == "shown" and dk.edge == "left")
    ck("…och fönstret ligger kant i kant (x=0)", shell.x() == 0 and shell.y() == 100)
    ck("…dockningen sparas i inställningarna", settings.edge_dock_edge() == "left")
    ck("…och det synliga läget är sparat (x=0)", saved(settings)["x"] == 0)

    # --- musen kvar på fönstret → gömmer sig inte ----------------------------------------------------------
    cursor["p"] = (100, 300)
    QTest.qWait(300)
    ck("musen på fönstret: det stannar framme", dk.state == "shown" and shell.x() == 0)

    # --- musen går bort → glider ut -------------------------------------------------------------------------
    cursor["p"] = (900, 500)
    ck("musen borta: fönstret gömmer sig", wait(lambda: dk.state == "hidden"))
    ck("…med 5 px kvar vid kanten", near(shell.x(), -335) and near(shell.x() + shell.width(), 5), (shell.x(), shell.width()))
    # det som sparas är ALLTID det synliga läget
    w._save_geometry_now()
    ck("gömt: spara geometri skriver det synliga läget (x=0)", saved(settings)["x"] == 0)
    settings.update_window_position("t", shell.x(), shell.y())
    ck("gömt: spara position skriver det synliga läget", saved(settings)["x"] == 0)
    settings.update_window_geometry("t", -335, 100, 340, 648)
    ck("gömt: update_window_geometry också", saved(settings)["x"] == 0 and saved(settings)["w"] == 340)

    # --- musen nuddar kanten → glider in ---------------------------------------------------------------------
    cursor["p"] = (900, 200)
    QTest.qWait(300)
    ck("musen långt från kanten: förblir gömt", dk.state == "hidden")
    cursor["p"] = (0, 5)
    QTest.qWait(300)
    ck("musen vid kanten men utanför fönstrets höjd: förblir gömt", dk.state == "hidden")
    cursor["p"] = (0, 300)
    cursor["btn"] = True
    QTest.qWait(300)
    ck("musknapp nedtryckt (t.ex. rullist): visas inte", dk.state == "hidden")
    cursor["btn"] = False
    ck("musen nuddar kanten: fönstret glider in", wait(lambda: dk.state == "shown"))
    ck("…och ligger flush igen", shell.x() == 0)
    ck("…det synliga läget är fortfarande sparat", saved(settings)["x"] == 0)
    # svisch förbi kanten (en enda avläsning) räcker inte
    cursor["p"] = (900, 500)
    wait(lambda: dk.state == "hidden")
    cursor["p"] = (0, 300)
    dk._tick()
    cursor["p"] = (900, 500)
    QTest.qWait(250)
    ck("en snabb svisch förbi kanten visar inte fönstret", dk.state == "hidden")

    # --- fönstret är upptaget → gömmer sig inte -----------------------------------------------------------------
    cursor["p"] = (0, 300)
    wait(lambda: dk.state == "shown")
    w.input_field.setText("skriver något")
    shell.activateWindow()
    app.processEvents()
    cursor["p"] = (900, 500)
    QTest.qWait(300)
    ck("text i inmatningsfältet: fönstret gömmer sig inte", dk.state == "shown")
    w.input_field.clear()
    ck("tomt fält igen: gömmer sig", wait(lambda: dk.state == "hidden"))
    dk.reveal()
    wait(lambda: dk.state == "shown")
    dk.pin(True)
    QTest.qWait(300)
    ck("pin (Ctrl+Alt+V hålls): stannar framme", dk.state == "shown")
    dk.pin(False)
    ck("pin av: gömmer sig igen", wait(lambda: dk.state == "hidden"))
    w._edge_dock_reveal()
    ck("reveal() från appen (t.ex. push-to-show) glider fram", wait(lambda: dk.state == "shown"))

    # --- storleksändring medan det är framme: dockas om ----------------------------------------------------------
    shell.resize(380, 648)
    ck("ny bredd medan framme: dockningen behålls och ligger flush", wait(lambda: dk._rect()[2] == 380 and shell.x() == 0 and dk.state == "shown"))

    # --- dra bort → dockningen släpps ------------------------------------------------------------------------------
    shell.move(500, 120)
    release(w)
    ck("släpp mitt på skärmen: dockningen släpps", dk.state == "idle" and settings.edge_dock_edge() == "" and shell.x() == 500)
    QTest.qWait(300)
    ck("…och fönstret gömmer sig aldrig mer", shell.x() == 500)

    # --- höger + överkant ------------------------------------------------------------------------------------------
    place(shell, 1536 - 340 - 4, 100, 340, 648)
    release(w)
    ck("höger: dockad flush (x=1196)", dk.edge == "right" and shell.x() == 1196)
    cursor["p"] = (300, 300)
    ck("höger: gömd med 5 px kvar", wait(lambda: dk.state == "hidden") and shell.x() == 1531)
    cursor["p"] = (1535, 300)
    ck("höger: musen nuddar högerkanten → fram", wait(lambda: dk.state == "shown") and shell.x() == 1196)
    place(shell, 500, 5, 340, 400)
    release(w)
    ck("överkant: dockad (y=0)", dk.edge == "top" and shell.y() == 0)
    cursor["p"] = (300, 600)
    ck("överkant: gömd (y=-395)", wait(lambda: dk.state == "hidden") and near(shell.y(), -395), (dk.state, shell.y(), shell.height()))
    cursor["p"] = (600, 0)
    ck("överkant: musen nuddar överkanten → fram", wait(lambda: dk.state == "shown") and shell.y() == 0)

    # --- avstängt i inställningarna ---------------------------------------------------------------------------------
    cursor["p"] = (300, 600)
    wait(lambda: dk.state == "hidden")
    settings.set_edge_dock_enabled(False)
    ck("avstängt medan gömt: fönstret kommer fram och dockningen släpps", wait(lambda: dk.state == "idle") and shell.y() == 0)
    place(shell, 3, 100, 340, 648)
    release(w)
    ck("avstängt: släpp vid kanten dockar inte", dk.state == "idle" and shell.x() == 3, (dk.state, shell.x()))
    settings.set_edge_dock_enabled(True)

    # --- flera skärmar: bara yttre kanter ----------------------------------------------------------------------------
    two = [((0, 0, 1536, 864), (0, 0, 1536, 864)), ((1536, 0, 1536, 864), (1536, 0, 1536, 864))]
    screens[:] = two
    place(shell, 1536 + 3, 100, 340, 648)
    release(w)
    ck("gräns mellan två skärmar: dockas inte (skulle synas på grannen)", dk.state == "idle")
    place(shell, 3072 - 340 - 3, 100, 340, 648)
    release(w)
    ck("yttre högerkant på skärm 2: dockas", dk.state == "shown" and dk.edge == "right" and shell.x() == 3072 - 340)
    dk.undock()
    screens[:] = [(S, S)]

    # --- start: dockning återupptas efter omstart ------------------------------------------------------------------------
    settings2, store2, shell2, w2, dk2 = build("b")
    place(shell2, 0, 150, 340, 648)
    settings2.set_edge_dock_edge("left")
    ck("adopt_saved: dockning återupptas när fönstret ligger vid sparad kant", dk2.adopt_saved() and dk2.state == "shown" and dk2.edge == "left")
    ck("adopt_saved: ger en nådetid innan det gömmer sig", dk2._outside_since is not None and dk2._outside_since > __import__("time").monotonic())
    settings3, store3, shell3, w3, dk3 = build("c")
    place(shell3, 400, 150, 340, 648)
    settings3.set_edge_dock_edge("left")
    ck("adopt_saved: fönstret inte vid kanten → ingen dockning, sparad kant rensas", not dk3.adopt_saved() and settings3.edge_dock_edge() == "")
    settings3.set_edge_dock_enabled(False)
    settings3.set_edge_dock_edge("left")
    place(shell3, 0, 150, 340, 648)
    ck("adopt_saved: avstängt → ingen dockning", not dk3.adopt_saved())

    # --- inställningarna ----------------------------------------------------------------------------------------------------
    ck("edge_dock_enabled har standardvärde På", Settings(str(tmp / "ny.json")).edge_dock_enabled() is True)
    settings.set_edge_dock_edge("sidan")
    ck("ogiltig kant sparas som tom", settings.edge_dock_edge() == "")
    ck("hjälpen nämner dockningen", "kant" in __import__("core.shortcut_help", fromlist=["x"]).as_text(
        __import__("core.shortcut_help", fromlist=["x"]).build_sections(settings, platform="linux")))

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
    geometry_tests()
    from _qtenv import qt_env

    work = Path(tempfile.mkdtemp(prefix="taskbord_docktest_"))
    env, why = qt_env(work)
    if env is None:
        print(f"edge_dock_test: Qt-delen hoppas över ({why})")
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
    print(f"\nedge_dock_test: {_ok} lyckades, {_fail} misslyckades")
    sys.exit(1 if _fail else 0)
