#!/usr/bin/env python3
"""
archive_history_test.py — arkiverade uppgifter är historik som ligger kvar för alltid.

Ingen väg (store-API, rensa-arkiv, återställning av backup, import, omstart) får ta bort dem.
Kör:  python tester/archive_history_test.py      (ingen Qt behövs)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import tasks_backup as tb  # noqa: E402
from core.store import TaskStore  # noqa: E402

_ok = _fail = 0


def check(name, cond, extra=""):
    global _ok, _fail
    if cond:
        _ok += 1
    else:
        _fail += 1
        print(f"  FAIL: {name} {extra}")


def done(s, title):
    # archive_task i stället för toggle_task: toggle_task emitterar Signal(str, bool), och PySide6 6.12 på
    # Python 3.11 kraschar ("bool_dealloc") efter några dussin anrop. Gäller bara den miljön.
    tid = s.add_task(title)
    s.archive_task(tid)
    return tid


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="tb_hist_"))
    try:
        d = tmp / "d"
        s = TaskStore(data_dir_override=str(d))
        a = done(s, "Klar 1")
        b = done(s, "Klar 2")
        live = s.add_task("Aktiv")
        check("förutsättning: två arkiverade", s.is_archived(a) and s.is_archived(b) and not s.is_archived(live))

        # --- store-API -------------------------------------------------------------------
        check("remove_task nekar arkiverad", s.remove_task(a) is False and s.is_archived(a))
        check("uppgiften finns kvar i arkivet", s.find_task(a) is not None and len(s.archived_tasks()) == 2 if hasattr(s, "archived_tasks") else s.find_task(a) is not None)
        check("clear_archive nekar", s.clear_archive() == 0 and s.is_archived(a) and s.is_archived(b))
        check("remove_task på aktiv fungerar fortfarande", s.remove_task(live) is True and s.find_task(live) is None)
        check("okänt id → False", s.remove_task("finns-inte") is False)

        # --- bakåtkompatibilitet: force bara för underhåll -----------------------------------------
        src_files = [p for p in ROOT.rglob("*.py") if "tester" not in p.parts and "__pycache__" not in p.parts]
        src_files.append(ROOT / "main.pyw")
        bad = []
        for p in src_files:
            txt = p.read_text(encoding="utf-8", errors="replace")
            if re.search(r"(remove_task|clear_archive)\([^)]*force\s*=\s*True", txt):
                bad.append(p.name)
        check("ingen kod i appen använder force=True", not bad, str(bad))
        callers = []
        for p in src_files:
            if p.name == "store.py":
                continue
            for m in re.finditer(r"clear_archive\(", p.read_text(encoding="utf-8", errors="replace")):
                callers.append(p.name)
        check("ingen kod i appen anropar clear_archive", not callers, str(callers))

        # --- ingen automatisk rensning (många arkiverade) -----------------------------------------
        s.save()
        s_big = TaskStore(data_dir_override=str(tmp / "big"))
        ids = [done(s_big, f"Gammal {i}") for i in range(20)]
        for i in range(5):
            s_big.add_task(f"Ny {i}")
        s_big.save()
        s_big2 = TaskStore(data_dir_override=str(tmp / "big"))
        check("20 arkiverade finns kvar efter omstart", sum(1 for i in ids if s_big2.is_archived(i)) == 20)

        # --- omstart ------------------------------------------------------------------------------------
        s_re = TaskStore(data_dir_override=str(d))
        check("arkivet överlever omstart", s_re.is_archived(a) and s_re.is_archived(b))
        s_re.reload()
        check("…och reload()", s_re.is_archived(a) and s_re.is_archived(b))

        # --- återställ backup: gammal backup får inte radera nyare historik ------------------------------
        old_active = s_re.add_task("Var aktiv vid backup")
        keep_a = s_re.add_task("Aktiv kvar")
        zip_path = tb.create_backup(s_re, dest=tmp / "old.zip")   # a,b arkiverade; två aktiva
        newer1 = done(s_re, "Klar efter backup 1")
        newer2 = done(s_re, "Klar efter backup 2")
        s_re.toggle_task(old_active)  # "Var aktiv vid backup" blir klar EFTER backupen
        check("förutsättning: nyare historik finns", s_re.is_archived(newer1) and s_re.is_archived(old_active))
        info = tb.restore_backup(s_re, zip_path)
        for tid, name in ((a, "gammal 1"), (b, "gammal 2"), (newer1, "nyare 1"), (newer2, "nyare 2"), (old_active, "klar efter backup")):
            check(f"efter återställning ligger {name} kvar i arkivet", s_re.is_archived(tid))
        check("…och är inte dubblerad som aktiv", all(t["id"] != old_active for t in s_re.active_tasks()))
        check("backupens aktiva uppgift kom tillbaka", s_re.find_task(keep_a) is not None and not s_re.is_archived(keep_a))
        check("info talar om hur många som behölls", info.get("archive_kept") == 3, str(info))
        ids_arch = [t["id"] for t in s_re.archived_tasks()] if hasattr(s_re, "archived_tasks") else None
        if ids_arch is not None:
            check("inga dubbletter i arkivet", len(ids_arch) == len(set(ids_arch)))

        # återställning utan nyare historik → oförändrat beteende
        s_clean = TaskStore(data_dir_override=str(tmp / "clean"))
        x = s_clean.add_task("X")
        z = tb.create_backup(s_clean, dest=tmp / "clean.zip")
        info2 = tb.restore_backup(s_clean, z)
        check("återställning utan arkiv: ingen 'kept'", not info2.get("archive_kept") and s_clean.find_task(x) is not None)

        # --- import ersätter aldrig arkivet ---------------------------------------------------------------
        other = TaskStore(data_dir_override=str(tmp / "other"))
        other.add_task("Annan")
        other.export_to(str(tmp / "exp")) if hasattr(other, "export_to") else None
        if (tmp / "exp").exists():
            s_re.import_from(str(tmp / "exp"), merge=False)
            check("import (replace) lämnar arkivet orört", s_re.is_archived(a) and s_re.is_archived(newer1))

        # --- återställ till aktiv är fortfarande tillåtet (det är inte radering) ------------------------------
        s_re.toggle_task(a)
        check("markera oklar flyttar tillbaka till aktiv", not s_re.is_archived(a) and s_re.find_task(a) is not None)

        # --- ett exportformat med arkivet i filen ------------------------------------------------------------
        data = json.loads((d / "archive.json").read_text(encoding="utf-8"))
        check("archive.json är giltig och innehåller uppgifterna", len(data["tasks"]) >= 3)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\narchive_history_test: {_ok} lyckades, {_fail} misslyckades")
    return 1 if _fail else 0


if __name__ == "__main__":
    _rc = main()
    sys.stdout.flush()
    # PySide6 6.12 på Python 3.11 kan avbryta vid nedstängning ("bool_dealloc") — miljöbuggen ska inte
    # ändra testets resultat, så avsluta direkt.
    os._exit(_rc)
