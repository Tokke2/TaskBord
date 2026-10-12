# -*- coding: utf-8 -*-
"""
tasks_backup.py — NY v8 (2026-10-12): säkerhetskopiera och återställ uppgifter.

En backup är en enda ZIP-fil med `active.json` (aktiva uppgifter), `archive.json`
(arkiverade) och `manifest.json` (tidpunkt + antal). Ren Python utan Qt, så den
går att testa utan GUI.

* create_backup(store, dest=None)  → skriver ZIP (standard: <data>/backups/uppgifter/)
* inspect_backup(path)             → kontrollerar filen och räknar uppgifter
* restore_backup(store, path)      → tar först en säkerhetskopia av nuläget, återställer sedan
* list_backups(store)              → backuper i standardmappen, nyast först
"""
from __future__ import annotations

import io
import json
import logging
import os
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("TaskBord")
LOG_PREFIX = "[TASKS-BACKUP]"

FILES = ("active.json", "archive.json")
MANIFEST = "manifest.json"
SUBDIR = "uppgifter"
PREFIX = "taskbord-uppgifter-"
KEEP_DEFAULT = 30
MAX_ZIP_BYTES = 200 * 1024 * 1024


class TasksBackupError(Exception):
    """Fel med svensk, användarvänlig text."""


def _data_dir(store: Any) -> Path:
    d = getattr(store, "data_dir", None) or getattr(store, "_data_dir", None)
    if callable(d):
        d = d()
    return Path(str(d))


def _paths(store: Any) -> Dict[str, Path]:
    try:
        return {"active.json": Path(store._active_path), "archive.json": Path(store._archive_path)}
    except Exception:
        d = _data_dir(store)
        return {"active.json": d / "active.json", "archive.json": d / "archive.json"}


def default_dir(store: Any) -> Path:
    return _data_dir(store) / "backups" / SUBDIR


def _count(raw: bytes) -> int:
    data = json.loads(raw.decode("utf-8"))
    if isinstance(data, dict):
        data = data.get("tasks", [])
    if not isinstance(data, list):
        raise ValueError("oväntat format")
    return len(data)


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    for i in range(2, 1000):
        p = path.with_name(f"{path.stem}-{i}{path.suffix}")
        if not p.exists():
            return p
    return path


def create_backup(store: Any, dest: Any = None, label: str = "", prune: bool = True) -> Path:
    """
    Skriv en backup-ZIP. `dest` kan vara en fil (.zip), en mapp eller None
    (= standardmappen). Returnerar sökvägen.
    """
    try:
        store.save()  # se till att disken har senaste läget
    except Exception as e:
        logger.warning(f"{LOG_PREFIX} kunde inte spara före backup: {e}")
    name = f"{PREFIX}{label + '-' if label else ''}{_stamp()}.zip"
    d = Path(str(dest)) if dest else default_dir(store)
    if d.suffix.lower() == ".zip":
        target = d
    else:
        target = _unique(d / name)
    counts: Dict[str, int] = {}
    blobs: Dict[str, bytes] = {}
    for fname, p in _paths(store).items():
        if p.is_file():
            raw = p.read_bytes()
            try:
                counts[fname] = _count(raw)
            except Exception as e:
                raise TasksBackupError(f"{fname} är skadad ({e}) — backup avbröts.")
            blobs[fname] = raw
    if "active.json" not in blobs:
        raise TasksBackupError("Det finns inga sparade uppgifter att säkerhetskopiera ännu.")
    manifest = {
        "app": "TaskBord", "version": 1,
        "created": datetime.now().astimezone().isoformat(timespec="seconds"),
        "active": counts.get("active.json", 0), "archive": counts.get("archive.json", 0),
    }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for fname, raw in blobs.items():
                z.writestr(fname, raw)
            z.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2))
        os.replace(str(tmp), str(target))
    except OSError as e:
        raise TasksBackupError(f"Kunde inte skriva backupen: {e}")
    inspect_backup(target)  # verifiera det vi nyss skrev
    if prune and not dest:
        _prune(default_dir(store))
    logger.info(f"{LOG_PREFIX} backup skapad: {target} ({manifest['active']} aktiva, {manifest['archive']} arkiverade)")
    return target


def _prune(folder: Path, keep: int = KEEP_DEFAULT) -> None:
    try:
        files = sorted(folder.glob(f"{PREFIX}*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[keep:]:
            if "fore-aterstallning" in old.name:
                continue  # säkerhetskopior inför återställning raderas aldrig automatiskt
            old.unlink(missing_ok=True)
    except Exception as e:
        logger.debug(f"{LOG_PREFIX} rensning misslyckades: {e}")


def inspect_backup(path: Any) -> Dict[str, Any]:
    """Kontrollera en backup. Returnerar {active, archive, created}. Kastar TasksBackupError."""
    p = Path(str(path))
    if not p.is_file():
        raise TasksBackupError("Filen finns inte.")
    if p.stat().st_size > MAX_ZIP_BYTES:
        raise TasksBackupError("Filen är orimligt stor för en uppgiftsbackup.")
    try:
        with zipfile.ZipFile(p) as z:
            if z.testzip() is not None:
                raise TasksBackupError("Backupen är skadad (kontrollsumman stämmer inte).")
            names = set(z.namelist())
            if "active.json" not in names:
                raise TasksBackupError("Det här är ingen TaskBord-uppgiftsbackup (active.json saknas).")
            res: Dict[str, Any] = {"active": 0, "archive": 0, "created": ""}
            for fname, key in (("active.json", "active"), ("archive.json", "archive")):
                if fname in names:
                    try:
                        res[key] = _count(z.read(fname))
                    except Exception as e:
                        raise TasksBackupError(f"{fname} i backupen är skadad ({e}).")
            if MANIFEST in names:
                try:
                    res["created"] = str(json.loads(z.read(MANIFEST)).get("created", ""))
                except Exception:
                    pass
            return res
    except zipfile.BadZipFile:
        raise TasksBackupError("Det här är ingen giltig ZIP-fil.")


def restore_backup(store: Any, path: Any) -> Dict[str, Any]:
    """
    Återställ uppgifter från en backup. Först tas en säkerhetskopia av nuläget
    (`...-fore-aterstallning-...zip`), så en felklickad återställning går att ångra.
    """
    info = inspect_backup(path)  # validera INNAN något rörs
    safety: Optional[Path] = None
    try:
        safety = create_backup(store, label="fore-aterstallning", prune=False)
    except TasksBackupError as e:
        logger.info(f"{LOG_PREFIX} ingen säkerhetskopia av nuläget: {e}")
    targets = _paths(store)
    with zipfile.ZipFile(str(path)) as z:
        names = set(z.namelist())
        for fname in FILES:
            if fname not in names and fname != "archive.json":
                continue
            raw = z.read(fname) if fname in names else b'{"tasks": []}'
            dest = targets[fname]
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(f".{dest.name}.{os.getpid()}.restore")
            tmp.write_bytes(raw)
            os.replace(str(tmp), str(dest))
            os.utime(str(dest), None)  # ny mtime → store läser om filen
    for attr in ("_active_mtime", "_archive_mtime"):  # tvinga omläsning (grov mtime-upplösning)
        try:
            setattr(store, attr, 0.0)
        except Exception:
            pass
    store.reload()
    info["safety"] = str(safety) if safety else ""
    logger.info(f"{LOG_PREFIX} återställd från {path} ({info['active']} aktiva)")
    return info


def list_backups(store: Any) -> List[Dict[str, Any]]:
    """Backuper i standardmappen, nyast först: [{path, name, size, mtime}]."""
    out: List[Dict[str, Any]] = []
    try:
        for p in default_dir(store).glob(f"{PREFIX}*.zip"):
            st = p.stat()
            out.append({"path": str(p), "name": p.name, "size": st.st_size, "mtime": st.st_mtime})
    except Exception:
        pass
    return sorted(out, key=lambda d: d["mtime"], reverse=True)
