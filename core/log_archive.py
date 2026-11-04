# -*- coding: utf-8 -*-
"""
log_archive.py — loggar från dagar före dagens datum arkiveras (zip) i loggar/arkiv/. Inget raderas.

    loggar/arkiv/2026-11-03.zip      allt som loggades den dagen:
        todo_app.log                 dagens huvudlogg (todo_app.log.20261103)
        update_watchdog.log          dagens rader ur uppdateringsväktarens logg
        fel-varningar.log            dagens VARNINGAR ur fel.log (se core/error_log.py)
    loggar/arkiv/fel_atgardade.log   fel som markerats som åtgärdade (se core/error_log.py)

Felposter (FEL/KRASCH) arkiveras INTE per dag — de ligger kvar i loggar/fel.log tills de markeras som åtgärdade.

Bara standardbiblioteket. Kraschar aldrig; allt som inte går (låst fil, trasig zip) provas igen nästa gång.
"""
from __future__ import annotations

import os
import re
import threading
import time
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Union

ARCHIVE_DIRNAME = "arkiv"
MAIN_LOG = "todo_app.log"
WATCHDOG_LOG = "update_watchdog.log"
_DATED_RX = re.compile(r"^todo_app\.log\.(\d{4})(\d\d)(\d\d)$")
_LINE_DAY_RX = re.compile(r"^(\d{4}-\d\d-\d\d)[ T]\d\d:\d\d:\d\d")
_LOCK = threading.RLock()


def archive_dir(logs_dir) -> Path:
    return Path(logs_dir) / ARCHIVE_DIRNAME


def day_zip(logs_dir, day_iso: str) -> Path:
    return archive_dir(logs_dir) / f"{day_iso}.zip"


def add_to_zip(zip_path: Path, arcname: str, data: Union[bytes, Path]) -> str:
    """Lägg till en post i zip-filen (skapas vid behov). Finns namnet redan blir det 'namn (2).ext'. Returnerar postnamnet."""
    zip_path = Path(zip_path)
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in (1, 2):
        try:
            with zipfile.ZipFile(zip_path, "a", zipfile.ZIP_DEFLATED) as z:
                names = set(z.namelist())
                name, n = arcname, 2
                stem, ext = os.path.splitext(arcname)
                while name in names:
                    name = f"{stem} ({n}){ext}"
                    n += 1
                if isinstance(data, Path):
                    z.write(data, name)
                else:
                    z.writestr(name, data)
            return name
        except zipfile.BadZipFile:
            if attempt == 2:
                raise OSError("trasig zip")
            os.replace(zip_path, zip_path.with_suffix(f".trasig-{int(time.time())}"))   # sparas, ny zip påbörjas
    raise OSError("zip")


def _mtime_day(p: Path) -> date:
    return datetime.fromtimestamp(p.stat().st_mtime).date()


def prepare_active(logs_dir, today: Optional[date] = None) -> bool:
    """
    Före loggningen startar: ligger huvudloggen kvar från en tidigare dag (appen var stängd vid midnatt) döps den om
    till todo_app.log.ÅÅÅÅMMDD — då börjar dagens logg på en ny, tom fil. True om något döptes om.
    """
    try:
        today = today or date.today()
        active = Path(logs_dir) / MAIN_LOG
        if not active.is_file() or _mtime_day(active) >= today:
            return False
        dst = active.with_name(f"{MAIN_LOG}.{_mtime_day(active):%Y%m%d}")
        if dst.exists():
            with open(active, "rb") as fi, open(dst, "ab") as fo:
                fo.write(fi.read())
            active.unlink()
        else:
            os.replace(active, dst)
        return True
    except OSError:
        return False


def _split_by_day(lines: List[str], default_day: str) -> Dict[str, List[str]]:
    """Gruppera rader per datum; rader utan datum (stacktrace m.m.) följer raden före."""
    out: Dict[str, List[str]] = {}
    cur = None
    for ln in lines:
        m = _LINE_DAY_RX.match(ln)
        if m:
            cur = m.group(1)
        out.setdefault(cur or default_day, []).append(ln)
    return out


def archive_watchdog_log(logs_dir, today: Optional[date] = None) -> int:
    """Rader i update_watchdog.log från tidigare dagar → zip per dag; filen behåller bara dagens rader. Returnerar antal rader arkiverade."""
    try:
        today_iso = (today or date.today()).isoformat()
        p = Path(logs_dir) / WATCHDOG_LOG
        if not p.is_file():
            return 0
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        by_day = _split_by_day(lines, today_iso)
        old = {d: v for d, v in by_day.items() if d < today_iso}
        if not old:
            return 0
        n = 0
        for d in sorted(old):
            add_to_zip(day_zip(logs_dir, d), WATCHDOG_LOG, "".join(old[d]).encode("utf-8"))
            n += len(old[d])
        keep = "".join(by_day.get(today_iso, []))
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(keep, encoding="utf-8")
        os.replace(tmp, p)
        return n
    except (OSError, ValueError):
        return 0


def archive_dated_logs(logs_dir, today: Optional[date] = None) -> int:
    """todo_app.log.ÅÅÅÅMMDD för dagar före idag → arkiv/ÅÅÅÅ-MM-DD.zip, originalet tas bort först när zippen skrivits."""
    today = today or date.today()
    n = 0
    try:
        files = sorted(Path(logs_dir).glob(f"{MAIN_LOG}.*"))
    except OSError:
        return 0
    for p in files:
        m = _DATED_RX.match(p.name)
        if not m or not p.is_file():
            continue
        try:
            day = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
        if day >= today:
            continue
        try:
            add_to_zip(day_zip(logs_dir, day.isoformat()), MAIN_LOG, p)
            p.unlink()
            n += 1
        except OSError:
            continue
    return n


def archive_day_logs(logs_dir, today: Optional[date] = None) -> Dict[str, int]:
    """Allt som loggats före dagens datum arkiveras. Returnerar {'files': n, 'watchdog_lines': n}."""
    with _LOCK:
        try:
            return {"files": archive_dated_logs(logs_dir, today), "watchdog_lines": archive_watchdog_log(logs_dir, today)}
        except Exception:
            return {"files": 0, "watchdog_lines": 0}


def archive_in_background(logs_dir, today: Optional[date] = None) -> None:
    """Zippa i en bakgrundstråd (stora loggar ska inte fördröja start eller gränssnittet)."""
    threading.Thread(target=archive_day_logs, args=(logs_dir, today), name="LogArchive", daemon=True).start()
