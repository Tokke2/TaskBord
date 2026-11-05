#!/usr/bin/env python3
"""
done_next_test.py — snabbtangent "Klar och nästa" (Ctrl+D): bocka av markerad uppgift, markera nästa.

Kör:  python tester/done_next_test.py
Riktig TodoWidget (offscreen) i en Qt-barnprocess + F1-översikten (utan Qt).
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


def pure() -> None:
    from core import shortcut_help as sh
    from core.settings import Settings
    check("standardtangent finns i Settings", Settings.DEFAULT_SHORTCUTS.get("done_next") == "Ctrl+D")

    class S:  # äldre sparade inställningar: saknar done_next
        def shortcuts(self):
            return {"add_task": "Ctrl+Alt+N"}
    txt = sh.as_text(sh.build_sections(S(), platform="win32"))
    check("F1-översikten nämner Klar och nästa med Ctrl+D (även för äldre inställningar)", "Ctrl+D" in txt and "Klar och nästa" in txt, txt[:200])

    class S2:
        def shortcuts(self):
            return {"done_next": "Ctrl+Shift+D"}
    txt2 = sh.as_text(sh.build_sections(S2(), platform="win32"))
    check("egen tangent visas i översikten", "Ctrl+Shift+D" in txt2 and "Ctrl+D " not in txt2.replace("Ctrl+Shift+D", ""))

    class S3:
        def shortcuts(self):
            return {"done_next": ""}
    check("avstängd tangent visas inte", "Klar och nästa" not in sh.as_text(sh.build_sections(S3(), platform="win32")).split("Styra listan")[0])
    src = (ROOT / "ui/widget_parts/focus_timers.py").read_text(encoding="utf-8")
    check("hotkey-tabellen har en hanterare för done_next", '"done_next": ("_done_and_next"' in src)
    check("Ctrl+Enter lämnas ifred (registrerar uppgift i inmatningsfältet)", "Ctrl+Return" not in src and "Ctrl+Enter" not in (ROOT / "core/settings.py").read_text(encoding="utf-8").split("DEFAULT_SHORTCUTS")[1][:600])


def child() -> None:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtGui import QShortcut
    from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
    app = QApplication([])
    from core.settings import Settings
    from core.store import TaskStore
    import widget as W

    res: list = []

    def ck(name, cond, extra=""):
        res.append((name + (f" {extra}" if not cond and extra else ""), bool(cond)))

    tmp = tempfile.mkdtemp(prefix="ledgebord_donenext_")

    def build(sub, shortcuts=None, n=4):
        settings = Settings(str(Path(tmp) / f"{sub}.json"))
        if shortcuts is not None:
            settings._data["shortcuts"] = shortcuts
        store = TaskStore(data_dir_override=Path(tmp) / sub)
        ids = [store.add_task(f"Uppg{i}", priority="high") for i in range(n)]
        shell = QWidget()
        w = W.TodoWidget(app.primaryScreen(), store, settings, win_id=sub, parent=shell)
        lay = QVBoxLayout(shell)
        lay.addWidget(w)
        w._shell = shell
        shell.resize(460, 600)
        shell.show()
        app.processEvents()
        w._rebuild_task_list()
        app.processEvents()
        return shell, w, store, ids

    shell, w, store, _ids = build("a")
    order = list(w._nav_tids)
    ck("fyra uppgifter i listan", len(order) == 4, order)
    done = lambda: [t["title"] for t in store.archive_tasks()]  # noqa: E731
    w._done_and_next()
    ck("utan markering: väljer bara den översta, klarmarkerar inget", w._sel_tid == order[0] and w._nav_active and len(store.active_tasks()) == 4)
    w._done_and_next()
    ck("andra trycket: översta klar och markeringen på nästa", len(store.active_tasks()) == 3 and w._sel_tid == order[1] and w._nav_active, (w._sel_tid, order))
    ck("den klara hamnade i historiken", len(done()) == 1)
    w._nav_select(order[2])
    w._done_and_next()
    ck("mitt i listan: nästa under markeras", w._sel_tid == order[3] and len(store.active_tasks()) == 2, w._sel_tid)
    w._done_and_next()
    ck("sista uppgiften klar: markeringen går till föregående", w._sel_tid == order[1] and len(store.active_tasks()) == 1, w._sel_tid)
    w._done_and_next()
    ck("allra sista: inga fler → lämnar listan", not w._nav_active and w._sel_tid is None and len(store.active_tasks()) == 0)
    w._done_and_next()
    ck("tom lista: tangenten gör inget och kraschar inte", True)

    # fokusläge och annan flik
    shell, w, store, ids = build("b")
    w._focus_mode = True
    w._done_and_next()
    ck("i fokusläget gör tangenten inget", len(store.active_tasks()) == 4 and not w._nav_active)
    w._focus_mode = False
    w.tabs.setCurrentIndex(1)
    w._done_and_next()
    ck("på Arkiverade-/Kalender-fliken gör tangenten inget", len(store.active_tasks()) == 4)
    w.tabs.setCurrentIndex(2)
    w._done_and_next()
    ck("på kalenderfliken heller inget", len(store.active_tasks()) == 4)
    w.tabs.setCurrentIndex(0)

    # tangenten är registrerad
    seqs = [sc.key().toString() for sc in w._hotkey_shortcuts if isinstance(sc, QShortcut)]
    ck("Ctrl+D är registrerad som kortkommando (även utan sparad inställning)", "Ctrl+D" in seqs, seqs)
    sc = [s for s in w._hotkey_shortcuts if s.key().toString() == "Ctrl+D"][0]
    w._nav_select(w._nav_tids[0])
    n0 = len(store.active_tasks())
    sc.activated.emit()
    ck("kortkommandot klarmarkerar och går vidare", len(store.active_tasks()) == n0 - 1 and w._nav_active)
    # från inmatningsfältet
    w.input_field.setFocus()
    w._nav_exit()
    sc.activated.emit()
    ck("från inmatningsfältet: första trycket markerar översta", w._nav_active and w._sel_tid == w._nav_tids[0])

    # äldre sparade inställningar med EGEN lista utan done_next → tangenten ändå aktiv
    shell, w2, store2, _ = build("c", shortcuts={"add_task": "Ctrl+Alt+N", "next_task": "Down"})
    seqs = [s.key().toString() for s in w2._hotkey_shortcuts if isinstance(s, QShortcut)]
    ck("äldre inställningar utan done_next får standardtangenten", "Ctrl+D" in seqs, seqs)
    # användaren har bytt tangent
    shell, w3, store3, _ = build("d", shortcuts={"done_next": "Ctrl+Shift+K"})
    seqs = [s.key().toString() for s in w3._hotkey_shortcuts if isinstance(s, QShortcut)]
    ck("egen tangent används istället för Ctrl+D", "Ctrl+Shift+K" in seqs and "Ctrl+D" not in seqs, seqs)
    # avstängd
    shell, w4, store4, _ = build("e", shortcuts={"done_next": ""})
    seqs = [s.key().toString() for s in w4._hotkey_shortcuts if isinstance(s, QShortcut)]
    ck("tom tangent = avstängd (inget kortkommando skapas)", "Ctrl+D" not in seqs and not any(s == "" for s in seqs), seqs)
    # Enter i inmatningsfältet påverkas inte (ShortcutOverride-skyddet finns kvar)
    ck("Return/Enter är inte kortkommando", all(s not in ("Return", "Enter") for s in seqs))
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
    _run_parent("done_next_test")
    print(f"\ndone_next_test: {_ok} lyckades, {_fail} misslyckades")
    sys.exit(1 if _fail else 0)
