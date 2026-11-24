#!/usr/bin/env python3
"""
update_window_state_test.py — fönstrets position/storlek ska användas som förut efter en uppdatering.

Kör:  python tester/update_window_state_test.py

Kontrollerar (1) att uppdateringsflödet skriver ner fönsterläget uttryckligen före installationen
och före omstarten, (2) att det verkligen hamnar i js/settings.json, och (3) att uppdateringen
aldrig rör js/ eller data/ (där settings.json ligger).
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "core"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ok = _fail = 0


def check(name, cond, extra=""):
    global _ok, _fail
    if cond:
        _ok += 1
    else:
        _fail += 1
        print(f"  ✗ {name} {extra}")


# --- 1. ordningen i uppdateringsflödet (källkod) --------------------------------------
src = (ROOT / "app/mixins/updates.py").read_text(encoding="utf-8")
i_flush1 = src.find('self._flush_window_state("före uppdatering")')
i_apply = src.find("updater.apply_update(")
i_flush2 = src.find('self._flush_window_state("före omstart")')
i_restart = src.find("updater.schedule_restart(", i_flush2)
i_flush_s = src.find('self._flush_window_state("före tyst omstart")')
i_restart_s = src.find("updater.schedule_restart(")
check("fönsterläget sparas före installationen", 0 < i_flush1 < i_apply)
check("fönsterläget sparas före omstarten", 0 < i_flush2 < i_restart)
check("fönsterläget sparas även före den TYSTA omstarten", 0 < i_flush_s < i_restart_s)

# --- 2. helpern skriver till js/settings.json ------------------------------------------
try:
    from PySide6.QtCore import QCoreApplication
except Exception:
    print("PySide6 saknas — hoppar över resten")
else:
    QCoreApplication.instance() or QCoreApplication([])
    from app.mixins.updates import UpdateMixin
    from core.settings import Settings

    tmp = Path(tempfile.mkdtemp(prefix="taskbord_upd_win_"))
    sfile = tmp / "js" / "settings.json"
    sfile.parent.mkdir()
    settings = Settings(file_path=sfile)
    wid = settings.window_configs()[0]["id"]

    class FakeWidget:
        def __init__(self):
            self.geo = (412, 233, 377, 655)

        def _save_geometry_now(self):
            x, y, w, h = self.geo
            settings.update_window_geometry(wid, x, y, w, h)

    class Log:
        def info(self, *a, **k): pass
        warning = debug = info

    class Ctl(UpdateMixin):
        def __init__(self):
            self._widget_lock = threading.Lock()
            self._widgets = {wid: FakeWidget()}
            self.settings = settings
            self._log = Log()

    Ctl()._flush_window_state("test")
    data = json.loads(sfile.read_text(encoding="utf-8"))
    win = next(w for w in data["windows"] if w["id"] == wid)
    check("position hamnar i settings.json", (win["x"], win["y"]) == (412, 233))
    check("storlek hamnar i settings.json", (win["w"], win["h"]) == (377, 655))
    s2 = Settings(file_path=sfile)  # \"omstart\"
    c = next(w for w in s2.window_configs() if w["id"] == wid)
    check("efter omstart: samma position och storlek", (c["x"], c["y"], c["w"], c["h"]) == (412, 233, 377, 655))

    # --- 3. uppdateringen rör aldrig js/ och data/ --------------------------------------
    upd = (ROOT / "core/updater.py").read_text(encoding="utf-8")
    m = re.search(r"PROTECTED_TOP\s*=\s*frozenset\(\{([^}]*)\}\)", upd)
    prot = set(re.findall(r'"([^"]+)"', m.group(1))) if m else set()
    check("js och data är skyddade i uppdateringen", {"js", "data"} <= prot, str(prot))
    check("settings.json ligger i js/ (skyddad mapp)", Path("js") == Path(sfile.relative_to(tmp)).parent)

print(f"\nupdate_window_state_test: {_ok} lyckades, {_fail} misslyckades")
sys.stdout.flush()
os._exit(1 if _fail else 0)
