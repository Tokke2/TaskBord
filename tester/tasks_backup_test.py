#!/usr/bin/env python3
"""
tasks_backup_test.py — tester för core/tasks_backup.py (backup/återställning av uppgifter).

Kör:  python tester/tasks_backup_test.py
Använder en riktig TaskStore i en tillfällig mapp. Ingen Qt behövs.
"""
from __future__ import annotations

import json
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

    # --- automatisk yttre backup + återställning efter "uppdatering" --------------
    app = tmp / "app"          # appmappen (js/ ligger i den)
    ext = tmp / "yttre"        # mappen utanför appen
    js = app / "js"
    js.mkdir(parents=True)
    st = TaskStore(data_dir_override=str(js))
    st.add_task("Överlever uppdatering", priority="high")
    st.add_task("Och den här")
    st.save()
    (js / "settings.json").write_text(json.dumps(
        {"version": 11, "windows": [{"id": "default", "x": 321, "y": 123, "w": 480, "h": 700}],
         "_meta": {"last_modified": "1"}}), encoding="utf-8")
    z1 = tb.snapshot_external(js, dest=ext)
    check("yttre backup skapad", z1 is not None and z1.is_file())
    check("oförändrat → ingen ny kopia", tb.snapshot_external(js, dest=ext) is None)
    st.save()  # ny saved_at men samma innehåll
    (js / "settings.json").write_text(json.dumps(
        {"version": 11, "windows": [{"id": "default", "x": 321, "y": 123, "w": 480, "h": 700}],
         "_meta": {"last_modified": "2"}}), encoding="utf-8")
    check("bara tidsstämplar ändrade → ingen ny kopia", tb.snapshot_external(js, dest=ext) is None)
    st.add_task("Ny uppgift")
    st.save()
    z2 = tb.snapshot_external(js, dest=ext)
    check("ändring → ny kopia", z2 is not None and z2 != z1)

    # befintliga giltiga filer rörs aldrig
    check("inget görs när allt finns", tb.restore_if_missing(js, source=ext) == {"active": False, "settings": False, "from": ""})

    # "uppdatering": hela js/-mappen försvinner
    import shutil
    shutil.rmtree(js)
    r = tb.restore_if_missing(js, source=ext)
    check("återställer uppgifter + inställningar", r["active"] and r["settings"])
    st2 = TaskStore(data_dir_override=str(js))
    check("uppgifterna är tillbaka vid start",
          titles(st2) == sorted(["Överlever uppdatering", "Och den här", "Ny uppgift"]))
    w = json.loads((js / "settings.json").read_text(encoding="utf-8"))["windows"][0]
    check("fönsterläge tillbaka", (w["x"], w["y"], w["w"], w["h"]) == (321, 123, 480, 700))

    # skadad fil ersätts, men originalet sparas undan
    (js / "active.json").write_text("{trasig", encoding="utf-8")
    r = tb.restore_if_missing(js, source=ext)
    check("skadad active.json återställs", r["active"] and not r["settings"])
    check("skadad fil sparades undan", any(p.name.startswith("active.json.skadad") for p in js.iterdir()))

    # skadad backup hoppas över, äldre används
    (js / "active.json").unlink()
    bad = sorted(ext.glob(f"{tb.AUTO_PREFIX}*.zip"), key=lambda p: p.stat().st_mtime)[-1]
    bad.write_bytes(b"skrap")
    r = tb.restore_if_missing(js, source=ext)
    check("hoppar över skadad backup, tar äldre", r["active"])

    # trasig active.json blir inte backup
    (js / "active.json").write_text("{trasig", encoding="utf-8")
    check("skadad uppgiftsfil backas inte upp", tb.snapshot_external(js, dest=tmp / "x") is None)

    # rensning: behåller senaste med uppgifter
    ext2 = tmp / "ext2"
    s3 = TaskStore(data_dir_override=str(tmp / "d3"))
    s3.add_task("Q0")
    s3.save()
    first = tb.snapshot_external(tmp / "d3", dest=ext2, keep=2)
    for i in range(4):
        s3.add_task(f"Q{i + 1}")
        s3.save()
        tb.snapshot_external(tmp / "d3", dest=ext2, keep=2)
    check("rensar till keep", len(list(ext2.glob("*.zip"))) <= 3 and first is not None)

    print(f"\ntasks_backup_test: {_ok} lyckades, {_fail} misslyckades")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
