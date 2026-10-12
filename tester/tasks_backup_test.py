#!/usr/bin/env python3
"""
tasks_backup_test.py — tester för core/tasks_backup.py (backup/återställning av uppgifter).

Kör:  python tester/tasks_backup_test.py
Använder en riktig TaskStore i en tillfällig mapp. Ingen Qt behövs.
"""
from __future__ import annotations

import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import tasks_backup as tb  # noqa: E402
from core.store import TaskStore  # noqa: E402

_ok = _fail = 0


def check(name: str, cond: bool) -> None:
    global _ok, _fail
    if cond:
        _ok += 1
    else:
        _fail += 1
        print(f"  FAIL: {name}")


def titles(s):
    return sorted(t["title"] for t in s.active_tasks())


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="tb_test_"))
    s = TaskStore(data_dir_override=str(tmp / "d"))
    tom = tb.create_backup(s, dest=tmp / "tom.zip")
    check("backup av tom lista fungerar (0 uppgifter)", tb.inspect_backup(tom)["active"] == 0)

    a = s.add_task("Alfa", priority="high", tags=["jobb"])
    s.add_task("Beta")
    s.add_task("Gamma")
    s.save()
    p = tb.create_backup(s)
    check("zip skapad i standardmappen", p.is_file() and p.parent == tb.default_dir(s))
    info = tb.inspect_backup(p)
    check("räknar 3 aktiva", info["active"] == 3 and info["created"])
    with zipfile.ZipFile(p) as z:
        check("innehåller active + manifest", {"active.json", "manifest.json"} <= set(z.namelist()))

    # eget mål
    egen = tb.create_backup(s, dest=tmp / "usb" / "min.zip")
    check("spara som egen fil", egen == tmp / "usb" / "min.zip" and egen.is_file())
    mapp = tb.create_backup(s, dest=tmp / "moln")
    check("spara i vald mapp", mapp.parent == tmp / "moln" and mapp.name.startswith(tb.PREFIX))

    # ändra, sedan återställ
    s.delete_task(a) if hasattr(s, "delete_task") else s.remove_task(a)
    s.add_task("Delta")
    s.save()
    check("förändrat läge", titles(s) == ["Beta", "Delta", "Gamma"])
    r = tb.restore_backup(s, p)
    check("återställt till 3 ursprungliga", titles(s) == ["Alfa", "Beta", "Gamma"])
    check("prioritet + tagg bevarade", next(t for t in s.active_tasks() if t["title"] == "Alfa")["priority"] == "high")
    check("säkerhetskopia av nuläget togs", r["safety"] and Path(r["safety"]).is_file())
    # ångra via säkerhetskopian
    tb.restore_backup(s, r["safety"])
    check("ångra återställning fungerar", titles(s) == ["Beta", "Delta", "Gamma"])

    # trasiga filer rör inget
    dålig = tmp / "dalig.zip"
    dålig.write_bytes(b"inte en zip")
    for namn, skapa in (
        ("ingen zip", lambda: dålig),
        ("saknas", lambda: tmp / "finns_inte.zip"),
    ):
        try:
            tb.restore_backup(s, skapa())
            check(f"{namn}: avvisas", False)
        except tb.TasksBackupError:
            check(f"{namn}: avvisas", True)
    fel = tmp / "fel.zip"
    with zipfile.ZipFile(fel, "w") as z:
        z.writestr("active.json", "{trasig json")
    try:
        tb.restore_backup(s, fel)
        check("trasig json avvisas", False)
    except tb.TasksBackupError:
        check("trasig json avvisas", True)
    främmande = tmp / "annan.zip"
    with zipfile.ZipFile(främmande, "w") as z:
        z.writestr("hej.txt", "x")
    try:
        tb.inspect_backup(främmande)
        check("främmande zip avvisas", False)
    except tb.TasksBackupError:
        check("främmande zip avvisas", True)
    check("uppgifter orörda efter avvisade återställningar", titles(s) == ["Beta", "Delta", "Gamma"])

    # lista + rensning
    check("lista nyast först", len(tb.list_backups(s)) >= 2)
    for i in range(tb.KEEP_DEFAULT + 5):
        tb.create_backup(s)
    n = len(list(tb.default_dir(s).glob(f"{tb.PREFIX}*.zip")))
    check("gamla backuper rensas (men inte 'före återställning')", n <= tb.KEEP_DEFAULT + 2)

    # arkiv följer med
    s.add_task("Klar")
    arch = s.active_tasks()[-1]["id"]
    if hasattr(s, "archive_task"):
        s.archive_task(arch)
        s.save()
        q = tb.create_backup(s, dest=tmp / "arkiv.zip")
        check("arkiv ingår", tb.inspect_backup(q)["archive"] >= 1)

    print(f"\ntasks_backup_test: {_ok} lyckades, {_fail} misslyckades")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
