#!/usr/bin/env python3
"""
window_geometry_test.py — fönstrets position/storlek ska överleva omstart.

Kör:  python tester/window_geometry_test.py     (kräver PySide6; hoppar annars över)

Regressionstest: update_window_geometry() satte tidigare bara _dirty och skrev aldrig
filen, så storleken (och ofta positionen) glömdes vid omstart.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QCoreApplication
except ImportError:
    print("PySide6 saknas — hoppar över window_geometry_test")
    sys.exit(0)

from core.settings import Settings  # noqa: E402

_ok = _fail = 0


def check(name: str, cond: bool) -> None:
    global _ok, _fail
    if cond:
        _ok += 1
    else:
        _fail += 1
        print(f"  FAIL: {name}")


def main() -> int:
    QCoreApplication.instance() or QCoreApplication([])
    f = Path(tempfile.mkdtemp(prefix="geo_test_")) / "settings.json"
    s = Settings(file_path=f)
    wid = s.window_configs()[0]["id"]

    s.update_window_geometry(wid, 300, 250, 480, 700)
    t = getattr(s, "_save_thread", None)
    if t is not None:
        t.join(5)
    s2 = Settings(file_path=f)  # "omstart" utan explicit save
    c = next(w for w in s2.window_configs() if w["id"] == wid)
    check("position sparas utan explicit save", (c["x"], c["y"]) == (300, 250))
    check("storlek sparas utan explicit save", (c["w"], c["h"]) == (480, 700))

    s.update_window_geometry(wid, 10, 20, 500, 800)
    s.save()
    s3 = Settings(file_path=f)
    c = next(w for w in s3.window_configs() if w["id"] == wid)
    check("explicit save() ger senaste läget", (c["x"], c["y"], c["w"], c["h"]) == (10, 20, 500, 800))
    check("save() returnerar True", s.save() is True)

    # migrering från äldre schema tappar inte fönsterläget
    import json
    data = json.loads(f.read_text(encoding="utf-8"))
    data["version"] = 10
    data.setdefault("_meta", {})["schema_version"] = 10
    f.write_text(json.dumps(data), encoding="utf-8")
    s4 = Settings(file_path=f)
    c = next(w for w in s4.window_configs() if w["id"] == wid)
    check("fönsterläget överlever migrering", (c["x"], c["y"], c["w"], c["h"]) == (10, 20, 500, 800))

    time.sleep(0.1)
    print(f"\nwindow_geometry_test: {_ok} lyckades, {_fail} misslyckades")
    return 1 if _fail else 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)  # undvik PySide6-avslutskrasch i vissa miljöer
