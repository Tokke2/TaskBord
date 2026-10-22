#!/usr/bin/env python3
"""shortcut_help_test.py — innehållet i F1-översikten (core/shortcut_help.py). Ingen Qt behövs."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import shortcut_help as sh  # noqa: E402

_ok = _fail = 0


def check(name, cond, extra=""):
    global _ok, _fail
    if cond:
        _ok += 1
    else:
        _fail += 1
        print(f"  FAIL: {name} {extra}")


class FakeSettings:
    def __init__(self, **kw):
        self.kw = kw

    def quick_add_hotkey(self): return self.kw.get("quick", "Ctrl+Alt+N")
    def push_show_hotkey(self): return self.kw.get("push", "Ctrl+Alt+V")
    def clip_task_hotkey(self): return self.kw.get("clip", "Ctrl+Alt+K")
    def clip_task_enabled(self): return self.kw.get("clip_on", True)
    def top_toggle_hotkey(self): return self.kw.get("top", "Ctrl+Alt+T")
    def top_toggle_enabled(self): return self.kw.get("top_on", True)

    def shortcuts(self):
        return self.kw.get("shortcuts", {"add_task": "Ctrl+Alt+N", "toggle_visible": "Ctrl+Alt+H",
                                         "open_search": "Ctrl+Alt+F", "next_task": "Down", "prev_task": "Up",
                                         "edit_task": "F2", "delete_task": "Delete", "toggle_done": "Space",
                                         "toggle_inbox": "Ctrl+Alt+I"})


def flat(sections):
    return [(t, k, v) for t, rows in sections for k, v in rows]


def main() -> int:
    st = FakeSettings(quick="Ctrl+Shift+Q", push="Alt+Space", clip="Ctrl+Alt+J", top="Ctrl+Alt+Y")
    win = sh.build_sections(st, platform="win32")
    txt = sh.as_text(win)
    check("Windows: användarens egna globala kombinationer visas",
          all(c in txt for c in ("Ctrl+Shift+Q", "Alt+Space", "Ctrl+Alt+J", "Ctrl+Alt+Y")))
    check("standardkombinationerna visas inte när de bytts", "Ctrl+Alt+K" not in txt and "Ctrl+Alt+T" not in txt)
    check("F1 och F3 finns", ("F1" in txt) and ("F3" in txt))
    check("listtangenter, fokusläge och mus finns", all(w in txt for w in ("Mellanslag", "Fokusläge", "Dubbelklick", "Högerklick")))
    check("kortkommandon utan funktion listas inte (Delete/Space är listtangenter)",
          "Ctrl+Alt+I" not in txt)
    check("kortkommandon från inställningarna listas", "Ctrl+Alt+F" in txt and "F2" in txt)
    check("ett eget kortkommando visas", "Ctrl+Alt+Z" in sh.as_text(sh.build_sections(
        FakeSettings(shortcuts={"open_search": "Ctrl+Alt+Z"}), platform="win32")))

    off = sh.as_text(sh.build_sections(FakeSettings(clip_on=False, top_on=False), platform="win32"))
    check("avstängda snabbtangenter markeras (av)", off.count("(av)") == 2)

    lin = sh.build_sections(st, platform="linux")
    ltxt = sh.as_text(lin)
    check("Linux/macOS: förklarar att globala tangenter är Windows-only", "Finns bara i Windows" in ltxt)
    check("Linux: inga globala kombinationer", "Ctrl+Shift+Q" not in ltxt)
    check("Linux: fönstrets tangenter finns ändå", "F1" in ltxt and "Mellanslag" in ltxt)

    check("F1 i inställningarna visas inte som dubblett",
          sum(1 for _, k, _ in flat(sh.build_sections(FakeSettings(shortcuts={"edit_task": "F1"}), platform="win32")) if k == "F1") == 1)
    check("fungerar utan settings", len(sh.build_sections(None, platform="win32")) >= 4)

    class Broken(FakeSettings):
        def quick_add_hotkey(self): raise RuntimeError("x")
        def shortcuts(self): raise RuntimeError("x")

    b = sh.as_text(sh.build_sections(Broken(), platform="win32"))
    check("trasiga settings → standardvärden, ingen krasch", "Ctrl+Alt+N" in b)

    html_txt = sh.as_html([("<b>Rubrik</b>", [("A&B", "<script>x</script>")])])
    check("HTML escapas", "<script>" not in html_txt and "&lt;script&gt;" in html_txt and "A&amp;B" in html_txt)
    check("HTML har inga egna färger (ärver temat → läsbar)", "color" not in sh.as_html(win).lower())
    check("alla rubriker har minst en rad", all(rows for _, rows in win))
    print(f"\nshortcut_help_test: {_ok} lyckades, {_fail} misslyckades")
    return 1 if _fail else 0


if __name__ == "__main__":
    rc = main()
    sys.stdout.flush()
    os._exit(rc)
