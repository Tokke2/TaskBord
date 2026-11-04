# -*- coding: utf-8 -*-
"""
log_paths.py — var loggarna ligger: appmappen\\loggar\\ (egen undermapp, inget utanför appmappen).

Hit flyttar appen automatiskt de loggar som tidigare låg i data\\ (migrate_old_logs, körs vid varje start innan
loggningen sätts upp). Uppgifter, inställningar och backuper rörs inte — bara loggfiler.

Innehåll i loggar\\:
    todo_app.log (+ dagsroterade .YYYYMMDD)   fel.log (+ .1)   fel_import.json   fel_seen.txt
    update_watchdog.log                       window_failure_report.txt

Beroendefri (bara standardbiblioteket) så att även uppdateringsväktaren kan använda den.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import List

LOGS_DIRNAME = "loggar"
# Det som flyttas från data\ (glob-mönster). Allt annat i data\ lämnas ifred.
MOVE_PATTERNS = (
    "todo_app.log*",
    "fel.log*",
    "fel_import.json",
    "fel_seen.txt",
    "update_watchdog.log*",
    "window_failure_report.txt",
)


def logs_dir(app_dir) -> Path:
    """appmappen/loggar (skapas inte här)."""
    return Path(app_dir) / LOGS_DIRNAME


def ensure_logs_dir(app_dir) -> Path:
    d = logs_dir(app_dir)
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return d


def _append_file(src: Path, dst: Path) -> None:
    """Lägg src sist i dst (båda finns) och ta bort src — ingen logghistorik går förlorad."""
    with open(src, "rb") as fi, open(dst, "ab") as fo:
        shutil.copyfileobj(fi, fo)
    src.unlink()


def migrate_old_logs(app_dir) -> List[str]:
    """
    Flytta gamla loggar från appmappen\\data\\ till appmappen\\loggar\\. Returnerar namnen på de flyttade filerna.
    Finns samma fil redan i loggar\\ läggs den gamla texten FÖRST (loggfiler) respektive hoppas över (tillståndsfiler).
    Kraschar aldrig; en låst fil lämnas kvar och flyttas vid nästa start.
    """
    moved: List[str] = []
    try:
        app_dir = Path(app_dir)
        old = app_dir / "data"
        if not old.is_dir():
            return moved
        new = ensure_logs_dir(app_dir)
        seen = set()
        for pat in MOVE_PATTERNS:
            for src in sorted(old.glob(pat)):
                if src.name in seen or not src.is_file():
                    continue
                seen.add(src.name)
                dst = new / src.name
                try:
                    if not dst.exists():
                        os.replace(src, dst)
                    elif src.suffix == ".json" or src.name == "fel_seen.txt":
                        src.unlink()          # tillståndsfil: den nya gäller
                    else:                      # loggfil: gammal text först, sedan det nya
                        data_new = dst.read_bytes()
                        os.replace(src, dst)
                        with open(dst, "ab") as f:
                            f.write(data_new)
                    moved.append(src.name)
                except OSError:
                    continue
    except Exception:
        pass
    return moved
