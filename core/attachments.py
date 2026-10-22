# -*- coding: utf-8 -*-
"""
attachments.py — bilagor på uppgifter. Filerna KOPIERAS in i appens datamapp
(``<datamapp>/attachments/<uppgifts-id>/<filnamn>``) — aldrig utanför appmappen — så
bilagan finns kvar även om originalet flyttas eller tas bort. Ingen Qt behövs.

Store sparar bara metadata (``name``, ``file`` = relativ sökväg, ``size``, ``added``).
"""
from __future__ import annotations

import logging
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Union

logger = logging.getLogger("TaskBord")
LOG_PREFIX = "[ATTACH]"

ATTACH_DIRNAME = "attachments"
MAX_ATTACH_BYTES = 50 * 1024 * 1024  # 50 MB per fil
MAX_NAME_LEN = 120

# Filtyper som kan köra kod när de öppnas — appen frågar först
DANGEROUS_EXT = frozenset({
    ".exe", ".bat", ".cmd", ".ps1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".msi",
    ".scr", ".lnk", ".jar", ".com", ".hta", ".reg", ".cpl", ".pif", ".sh", ".command",
    ".app", ".appimage", ".desktop",
})

_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)
_ID_OK = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class AttachmentError(Exception):
    """Fel med svensk text som kan visas för användaren."""


def human_size(n: int) -> str:
    n = int(n or 0)
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f} kB"
    return f"{n / (1024 * 1024):.1f} MB"


def safe_name(name: str) -> str:
    """Gör ett filnamn säkert för alla operativsystem (behåller ändelsen)."""
    base = os.path.basename(str(name or "").replace("\\", "/")).strip()
    base = _BAD_CHARS.sub("_", base).strip(" .")
    stem, ext = os.path.splitext(base)
    if not stem:
        stem, ext = ("fil", ext if base.startswith(".") is False else "")
    if stem.lower() in _RESERVED:
        stem = f"_{stem}"
    ext = ext[:16]
    stem = stem[: max(1, MAX_NAME_LEN - len(ext))].rstrip(" .") or "fil"
    return stem + ext


def is_dangerous(name: str) -> bool:
    return os.path.splitext(str(name or ""))[1].lower() in DANGEROUS_EXT


def _check_id(task_id: str) -> str:
    tid = str(task_id or "")
    if not _ID_OK.match(tid):
        raise AttachmentError("Ogiltigt uppgifts-id.")
    return tid


def attachments_root(data_dir: Union[str, Path]) -> Path:
    return Path(data_dir) / ATTACH_DIRNAME


def task_dir(data_dir: Union[str, Path], task_id: str) -> Path:
    return attachments_root(data_dir) / _check_id(task_id)


def copy_in(data_dir: Union[str, Path], task_id: str, src: Union[str, Path]) -> Dict[str, Any]:
    """Kopiera ``src`` in i appmappen. Returnerar metadata ``{name,file,size,added}``."""
    s = Path(src)
    if not s.is_file():
        raise AttachmentError(f"Hittar inte filen:\n{s}")
    try:
        size = s.stat().st_size
    except OSError as e:
        raise AttachmentError(f"Kan inte läsa filen: {e}") from e
    if size > MAX_ATTACH_BYTES:
        raise AttachmentError(
            f"Filen är för stor ({human_size(size)}). Max {human_size(MAX_ATTACH_BYTES)} per bilaga."
        )
    folder = task_dir(data_dir, task_id)
    name = safe_name(s.name)
    stem, ext = os.path.splitext(name)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        n, target = 1, folder / name
        while True:
            try:
                with open(target, "xb") as out, open(s, "rb") as inp:
                    shutil.copyfileobj(inp, out, 1024 * 1024)
                break
            except FileExistsError:
                n += 1
                target = folder / f"{stem} ({n}){ext}"
                if n > 999:
                    raise AttachmentError("För många filer med samma namn.")
    except AttachmentError:
        raise
    except OSError as e:
        with_suppress_unlink(locals().get("target"))
        raise AttachmentError(f"Kunde inte kopiera filen: {e}") from e
    rel = f"{ATTACH_DIRNAME}/{_check_id(task_id)}/{target.name}"
    logger.info(f"{LOG_PREFIX} kopierade {s.name!r} → {rel} ({human_size(size)})")
    return {
        "name": s.name[:MAX_NAME_LEN] or target.name,
        "file": rel,
        "size": int(target.stat().st_size),
        "added": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def with_suppress_unlink(p: Any) -> None:
    try:
        if p is not None:
            Path(p).unlink(missing_ok=True)
    except OSError:
        pass


def resolve(data_dir: Union[str, Path], rel: str) -> Optional[Path]:
    """Relativ sökväg → absolut sökväg, eller None om den pekar utanför bilagemappen."""
    try:
        root = attachments_root(data_dir).resolve()
        p = (Path(data_dir) / str(rel)).resolve()
        p.relative_to(root)
    except (ValueError, OSError):
        return None
    return p


def exists(data_dir: Union[str, Path], rel: str) -> bool:
    p = resolve(data_dir, rel)
    return bool(p and p.is_file())


def delete_file(data_dir: Union[str, Path], rel: str) -> bool:
    p = resolve(data_dir, rel)
    if p is None or not p.is_file():
        return False
    try:
        p.unlink()
        try:
            p.parent.rmdir()  # tom uppgiftsmapp städas bort
        except OSError:
            pass
        return True
    except OSError as e:
        logger.warning(f"{LOG_PREFIX} kunde inte ta bort {rel}: {e}")
        return False


def delete_task_files(data_dir: Union[str, Path], task_id: str) -> bool:
    """Ta bort ALLA bilagor för en uppgift (när den raderas). Rör bara bilagemappen."""
    try:
        folder = task_dir(data_dir, task_id)
    except AttachmentError:
        return False
    try:
        root = attachments_root(data_dir).resolve()
        if folder.resolve().parent != root or not folder.is_dir():
            return False
        shutil.rmtree(folder)
        logger.info(f"{LOG_PREFIX} tog bort bilagor för {task_id}")
        return True
    except OSError as e:
        logger.warning(f"{LOG_PREFIX} kunde inte ta bort bilagor för {task_id}: {e}")
        return False
