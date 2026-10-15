# -*- coding: utf-8 -*-
"""
Håller koll på Thunderbird-tillägget (TaskBord-Thunderbird.xpi) i appmappen.

Thunderbird installerar INTE om tillägget av sig självt när filen byts ut vid en
appuppdatering — användaren måste installera den nya .xpi:n från fil. Den här modulen
avgör (på filinnehåll, inte versionsnummer) om .xpi:n är en annan än den användaren senast
bekräftade, och hjälper till att visa filen i Utforskaren.

Ren Python, inget Qt — testbar överallt.
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger("TaskBord")
LOG_PREFIX = "[ADDON]"

XPI_NAME = "TaskBord-Thunderbird.xpi"
FP_LEN = 40  # tecken av sha256 som sparas i settings (≤ 64)


def xpi_path(app_dir: Path) -> Path:
    return Path(app_dir) / XPI_NAME


def file_fingerprint(path: Path) -> str:
    """Första ``FP_LEN`` tecknen av filens sha256, eller '' om den saknas/inte går att läsa."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 16), b""):
                h.update(chunk)
        return h.hexdigest()[:FP_LEN]
    except OSError:
        return ""


def addon_version(path: Path) -> str:
    """Tilläggets versionsnummer ur manifest.json i .xpi:n ('' om det inte går att läsa)."""
    try:
        with zipfile.ZipFile(path) as z:
            return str(json.loads(z.read("manifest.json").decode("utf-8-sig")).get("version", ""))[:30]
    except Exception:
        return ""


def previous_fingerprint_from_backups(app_dir: Path) -> str:
    """
    Fingeravtryck för .xpi:n i den SENASTE appuppdateringens backup ('' om den inte ändrades där).

    Används första gången funktionen körs: då finns ingen sparad referens, men om den senaste
    uppdateringen bytte ut .xpi:n (gamla filen ligger i backupen) vet vi vad användaren hade.
    """
    root = Path(app_dir) / "data" / "backups" / "app-update"
    try:
        for d in sorted((p for p in root.iterdir() if p.is_dir()), reverse=True):
            cand = d / XPI_NAME
            if cand.is_file():
                return file_fingerprint(cand)
            break  # bara den allra senaste uppdateringen räknas
    except OSError:
        pass
    return ""


@dataclass
class AddonState:
    state: str          # "missing" | "baseline" | "same" | "new"
    fingerprint: str    # nuvarande .xpi
    version: str        # versionsnummer i nuvarande .xpi
    path: Path


def evaluate(app_dir: Path, seen: str) -> AddonState:
    """
    Jämför .xpi:n i appmappen med den som användaren senast bekräftade (``seen``).

    * missing  — ingen .xpi i mappen
    * baseline — ingen referens sparad än och inget tyder på att den ändrats → spara tyst
    * same     — oförändrad
    * new      — en annan .xpi än den användaren bekräftat → påminn
    """
    p = xpi_path(app_dir)
    fp = file_fingerprint(p)
    if not fp:
        return AddonState("missing", "", "", p)
    ver = addon_version(p)
    if not seen:
        old = previous_fingerprint_from_backups(app_dir)
        if old and old != fp:
            return AddonState("new", fp, ver, p)
        return AddonState("baseline", fp, ver, p)
    if seen == fp:
        return AddonState("same", fp, ver, p)
    return AddonState("new", fp, ver, p)


def reveal_in_folder(path: Path) -> bool:
    """Öppna mappen med filen markerad (Utforskaren). Faller tillbaka på att bara öppna mappen."""
    path = Path(path)
    try:
        if sys.platform == "win32":
            if path.is_file():
                # explorer returnerar ofta exit-kod 1 även när det lyckas → ingen check
                subprocess.Popen(["explorer", "/select,", str(path)])
            else:
                import os
                os.startfile(str(path.parent))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)] if path.is_file() else ["open", str(path.parent)])
        else:
            subprocess.Popen(["xdg-open", str(path.parent)])
        return True
    except Exception as e:
        logger.warning(f"{LOG_PREFIX} kunde inte visa {path}: {e}")
        return False
