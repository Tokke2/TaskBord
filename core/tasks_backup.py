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

Automatisk yttre säkerhetskopia (överlever uppdatering/ominstallation):

* snapshot_external(data_dir)      → kopierar uppgifter + inställningar (fönsterläge m.m.) till
                                     en mapp UTANFÖR appmappen (%APPDATA%\\TaskBord\\backup eller
                                     ~/.local/share/TaskBord/backup)
* restore_if_missing(data_dir)     → vid start: saknas/är skadade uppgifter eller inställningar
                                     läses de in igen från senaste yttre backup
"""
from __future__ import annotations

import hashlib
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
    """Backuper (egna + automatiska), nyast först: [{path, name, size, mtime, auto}]."""
    out: List[Dict[str, Any]] = []
    for folder, pattern, auto in ((default_dir(store), f"{PREFIX}*.zip", False),
                                  (external_dir(), f"{AUTO_PREFIX}*.zip", True)):
        try:
            for p in folder.glob(pattern):
                st = p.stat()
                out.append({"path": str(p), "name": p.name, "size": st.st_size,
                            "mtime": st.st_mtime, "auto": auto})
        except Exception:
            pass
    return sorted(out, key=lambda d: d["mtime"], reverse=True)


# --------------------------------------------------------------------------
# Automatisk yttre säkerhetskopia (överlever uppdatering av appen)
# --------------------------------------------------------------------------
AUTO_PREFIX = "taskbord-auto-"
AUTO_FILES = ("active.json", "archive.json", "settings.json")
AUTO_KEEP = 20


def external_dir() -> Path:
    """Mapp UTANFÖR appmappen, så att en uppdatering/ominstallation inte tar den."""
    env = os.environ.get("TASKBORD_BACKUP_DIR")
    if env:
        return Path(env)
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "TaskBord" / "backup"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "TaskBord" / "backup"


def _read_valid(path: Path, tasks: bool) -> Optional[bytes]:
    """Filens innehåll om det är giltig JSON (för uppgiftsfiler: med en uppgiftslista)."""
    try:
        if not path.is_file() or path.stat().st_size == 0:
            return None
        raw = path.read_bytes()
        if tasks:
            _count(raw)
        else:
            if not isinstance(json.loads(raw.decode("utf-8")), dict):
                return None
        return raw
    except Exception:
        return None


def _content_hash(blobs: Dict[str, bytes]) -> str:
    """Hash utan fält som ändras vid varje sparning (saved_at, _meta) — så oförändrat = samma."""
    h = hashlib.sha256()
    for name in sorted(blobs):
        try:
            data = json.loads(blobs[name].decode("utf-8"))
            if isinstance(data, dict):
                data = {k: v for k, v in data.items() if k not in ("saved_at", "_meta")}
            h.update(name.encode() + json.dumps(data, sort_keys=True, ensure_ascii=False).encode())
        except Exception:
            h.update(name.encode() + blobs[name])
    return h.hexdigest()


def _auto_zips(folder: Path) -> List[Path]:
    try:
        return sorted(folder.glob(f"{AUTO_PREFIX}*.zip"), key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
    except Exception:
        return []


def _auto_manifest(path: Path) -> Dict[str, Any]:
    try:
        with zipfile.ZipFile(path) as z:
            return json.loads(z.read(MANIFEST))
    except Exception:
        return {}


def snapshot_external(data_dir: Any, dest: Any = None, keep: int = AUTO_KEEP) -> Optional[Path]:
    """
    Kopiera uppgifter + inställningar (fönsterposition/storlek m.m.) till den yttre mappen.

    Hoppar över om inget ändrats sedan senaste kopian och om uppgiftsfilen är skadad
    (en trasig fil får aldrig ersätta en bra backup). Returnerar ny zip eller None.
    """
    dd = Path(str(data_dir))
    folder = Path(str(dest)) if dest else external_dir()
    blobs: Dict[str, bytes] = {}
    active = _read_valid(dd / "active.json", tasks=True)
    if active is None:
        logger.info(f"{LOG_PREFIX} yttre backup hoppas över: active.json saknas/är skadad")
        return None
    blobs["active.json"] = active
    arch = _read_valid(dd / "archive.json", tasks=True)
    if arch is not None:
        blobs["archive.json"] = arch
    sett = _read_valid(dd / "settings.json", tasks=False)
    if sett is not None:
        blobs["settings.json"] = sett
    digest = _content_hash(blobs)
    zips = _auto_zips(folder)
    if zips and _auto_manifest(zips[0]).get("hash") == digest:
        return None  # oförändrat
    manifest = {
        "app": "TaskBord", "version": 1, "kind": "auto", "hash": digest,
        "created": datetime.now().astimezone().isoformat(timespec="seconds"),
        "active": _count(active), "archive": _count(arch) if arch else 0,
    }
    target = _unique(folder / f"{AUTO_PREFIX}{_stamp()}.zip")
    try:
        folder.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for name, raw in blobs.items():
                z.writestr(name, raw)
            z.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2))
        os.replace(str(tmp), str(target))
    except OSError as e:
        logger.warning(f"{LOG_PREFIX} yttre backup misslyckades: {e}")
        return None
    _prune_auto(folder, keep)
    logger.info(f"{LOG_PREFIX} yttre backup: {target} ({manifest['active']} aktiva)")
    return target


def _prune_auto(folder: Path, keep: int) -> None:
    """Behåll de `keep` senaste + alltid den senaste som innehåller uppgifter."""
    zips = _auto_zips(folder)
    keepers = set(zips[:keep])
    for z in zips:
        if _auto_manifest(z).get("active", 0) > 0:
            keepers.add(z)
            break
    for z in zips:
        if z not in keepers:
            try:
                z.unlink()
            except OSError:
                pass


def restore_if_missing(data_dir: Any, source: Any = None) -> Dict[str, Any]:
    """
    Körs vid start, FÖRE att inställningar och uppgifter läses in.

    Saknas `active.json` (eller är tom/skadad) läses uppgifterna in från senaste yttre
    backup; samma sak för `settings.json` (fönsterposition, storlek, val). Befintliga,
    giltiga filer rörs aldrig. En skadad fil sparas undan som `.skadad-<tid>`.
    Returnerar {"active": bool, "settings": bool, "from": str}.
    """
    dd = Path(str(data_dir))
    folder = Path(str(source)) if source else external_dir()
    res: Dict[str, Any] = {"active": False, "settings": False, "from": ""}
    need_active = _read_valid(dd / "active.json", tasks=True) is None
    need_settings = _read_valid(dd / "settings.json", tasks=False) is None
    if not (need_active or need_settings):
        return res
    for z in _auto_zips(folder):
        try:
            with zipfile.ZipFile(z) as zf:
                if zf.testzip() is not None:
                    continue
                names = set(zf.namelist())
                todo: Dict[str, bytes] = {}
                if need_active and not res["active"] and "active.json" in names:
                    raw = zf.read("active.json")
                    _count(raw)
                    todo["active.json"] = raw
                    todo["archive.json"] = zf.read("archive.json") if "archive.json" in names else b'{"tasks": []}'
                if need_settings and not res["settings"] and "settings.json" in names:
                    raw = zf.read("settings.json")
                    if isinstance(json.loads(raw.decode("utf-8")), dict):
                        todo["settings.json"] = raw
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} hoppar över skadad yttre backup {z.name}: {e}")
            continue
        for name, raw in todo.items():
            dest = dd / name
            try:
                dd.mkdir(parents=True, exist_ok=True)
                if dest.exists() and dest.stat().st_size > 0:
                    os.replace(str(dest), str(dest.with_name(f"{dest.name}.skadad-{_stamp()}")))
                tmp = dest.with_name(f".{dest.name}.{os.getpid()}.restore")
                tmp.write_bytes(raw)
                os.replace(str(tmp), str(dest))
            except OSError as e:
                logger.warning(f"{LOG_PREFIX} kunde inte återställa {name}: {e}")
                continue
            if name == "active.json":
                res["active"] = True
            elif name == "settings.json":
                res["settings"] = True
            res["from"] = str(z)
        if (res["active"] or not need_active) and (res["settings"] or not need_settings):
            break
    if res["active"] or res["settings"]:
        logger.warning(
            f"{LOG_PREFIX} återställde från yttre backup {res['from']}: "
            f"uppgifter={res['active']}, inställningar={res['settings']}"
        )
    return res
