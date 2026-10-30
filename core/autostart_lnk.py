# -*- coding: utf-8 -*-
"""
Autostart och genvägar med Ledgebords egen ikon (Windows) — aldrig Pythons ikon.

Varför: en autostart-post i registret (``Run``) eller en .bat pekar på ``pythonw.exe`` och Windows visar då
Pythons ikon i Aktivitetshanterarens *Autostart*-flik och i Inställningar → Appar → Autostart. En genväg
(.lnk) i Startup-mappen har däremot en EGEN ikon: ``icon\\ledgebord.ico``. Därför skapas genvägen
``Ledgebord.lnk`` i Startup-mappen och de gamla posterna (registret + .bat) tas bort när genvägen finns.

Allt här är ren stdlib. Genvägar skapas via PowerShell/WScript.Shell (som INSTALLERA.bat gör) med värdena i
miljövariabler (inga citatproblem med mellanslag/å/ä/ö). Markeringsfilen ``data/autostart_lnk.txt`` i APPMAPPEN
minns vad genvägen pekar på, så att den kan skrivas om om appen flyttas eller Python byts. Inget skrivs utanför
appmappen utom själva Startup-genvägen (den användaren själv slår på med "Starta med datorn").
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from contextlib import suppress
from pathlib import Path
from typing import Dict, Optional, Tuple

log = logging.getLogger("ledgebord.autostart_lnk")

APP_NAME = "Ledgebord"
LEGACY_NAMES = ("TaskBord",)
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_ROOT = Path(__file__).resolve().parent.parent
MARKER_NAME = "autostart_lnk.txt"
AUTOSTART_FLAG = "--autostart"

_PS_SCRIPT = (
    "$ws = New-Object -ComObject WScript.Shell; "
    "$l = $ws.CreateShortcut($env:LB_LNK); "
    "$l.TargetPath = $env:LB_TARGET; "
    "$l.Arguments = $env:LB_ARGS; "
    "$l.WorkingDirectory = $env:LB_WORKDIR; "
    "$l.Description = $env:LB_DESC; "
    "if ($env:LB_ICON) { $l.IconLocation = $env:LB_ICON + ',0' }; "
    "$l.WindowStyle = 7; "
    "$l.Save()"
)


def is_windows() -> bool:
    return sys.platform == "win32"


def startup_dir() -> Path:
    return Path(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", "Startup")


def shortcut_path(name: str = APP_NAME) -> Path:
    return startup_dir() / f"{name}.lnk"


def marker_path(app_root: Optional[Path] = None) -> Path:
    return Path(app_root or APP_ROOT) / "data" / MARKER_NAME


def icon_file(app_root: Optional[Path] = None) -> Optional[Path]:
    """``icon/ledgebord.ico`` (eller den omritade ``data/ledgebord.ico``) — None om ingen finns."""
    root = Path(app_root or APP_ROOT)
    for p in (root / "icon" / "ledgebord.ico", root / "data" / "ledgebord.ico"):
        with suppress(OSError):
            if p.is_file() and p.stat().st_size > 500:
                return p
    return None


def split_command(cmd: str) -> Tuple[str, str]:
    """'"C:\\Py\\pythonw.exe" "D:\\app\\main.pyw" --autostart' → (exe, '"D:\\app\\main.pyw" --autostart')."""
    cmd = (cmd or "").strip()
    m = re.match(r'^"([^"]+)"\s*(.*)$', cmd)
    if m:
        return m.group(1), m.group(2).strip()
    exe, _, rest = cmd.partition(" ")
    return exe, rest.strip()


def with_autostart_flag(cmd: str) -> str:
    return cmd if AUTOSTART_FLAG in cmd else f"{cmd} {AUTOSTART_FLAG}".strip()


def _wanted(cmd: str, icon: Optional[Path], workdir: Path) -> Dict[str, str]:
    exe, args = split_command(cmd)
    return {"target": exe, "args": args, "icon": str(icon) if icon else "", "workdir": str(workdir)}


def create_shortcut(lnk: Path, target: str, args: str = "", workdir: str = "", icon: str = "",
                    description: str = APP_NAME, timeout: int = 40) -> bool:
    """Skapar en .lnk via PowerShell. True om filen finns efteråt."""
    if not is_windows():
        return False
    env = dict(os.environ)
    env.update({"LB_LNK": str(lnk), "LB_TARGET": target, "LB_ARGS": args, "LB_WORKDIR": workdir,
                "LB_ICON": icon, "LB_DESC": description})
    try:
        Path(lnk).parent.mkdir(parents=True, exist_ok=True)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", _PS_SCRIPT],
            env=env, capture_output=True, timeout=timeout, creationflags=flags,
        )
        ok = Path(lnk).is_file()
        if not ok:
            log.warning("genväg skapades inte (%s): %s", r.returncode, (r.stderr or b"")[:300])
        return ok
    except Exception as e:  # noqa: BLE001
        log.warning("create_shortcut: %s", e)
        return False


def is_current(cmd: str, app_root: Optional[Path] = None) -> bool:
    """Finns Startup-genvägen och pekar den på exakt detta kommando + denna ikon?"""
    try:
        root = Path(app_root or APP_ROOT)
        if not shortcut_path().is_file():
            return False
        want = _wanted(with_autostart_flag(cmd), icon_file(root), root)
        have = json.loads(marker_path(root).read_text(encoding="utf-8"))
        return have == want
    except Exception:  # noqa: BLE001
        return False


def exists() -> bool:
    with suppress(Exception):
        return shortcut_path().is_file()
    return False


def install(cmd: str, app_root: Optional[Path] = None) -> bool:
    """Skapar Startup-genvägen (med ikon) för ``cmd`` och städar de gamla posterna. True vid lyckat."""
    if not is_windows():
        return False
    root = Path(app_root or APP_ROOT)
    cmd = with_autostart_flag(cmd)
    want = _wanted(cmd, icon_file(root), root)
    if not create_shortcut(shortcut_path(), want["target"], want["args"], want["workdir"], want["icon"]):
        return False
    with suppress(Exception):
        mp = marker_path(root)
        mp.parent.mkdir(parents=True, exist_ok=True)
        mp.write_text(json.dumps(want, ensure_ascii=False, indent=1), encoding="utf-8")
    cleanup_old_entries()
    log.info("autostart-genväg skapad: %s → %s", shortcut_path(), cmd)
    return True


def remove(app_root: Optional[Path] = None) -> int:
    """Tar bort Startup-genvägen (och markeringsfilen). Returnerar antal borttagna filer."""
    n = 0
    for name in (APP_NAME,) + LEGACY_NAMES:
        p = shortcut_path(name)
        with suppress(OSError):
            if p.is_file():
                p.unlink()
                n += 1
    with suppress(OSError):
        mp = marker_path(app_root)
        if mp.is_file():
            mp.unlink()
    return n


def cleanup_old_entries() -> int:
    """Tar bort registerposten ``Run\\Ledgebord`` och Startup-.bat (de visar Pythons ikon). Antal borttagna."""
    n = 0
    if not is_windows():
        return 0
    with suppress(Exception):
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            with suppress(OSError):
                winreg.DeleteValue(k, APP_NAME)
                n += 1
    p = startup_dir() / f"{APP_NAME}.bat"
    with suppress(OSError):
        if p.is_file():
            p.unlink()
            n += 1
    return n


def old_entries_present() -> bool:
    """Finns den gamla registerposten eller .bat kvar?"""
    if not is_windows():
        return False
    with suppress(Exception):
        if (startup_dir() / f"{APP_NAME}.bat").is_file():
            return True
    with suppress(Exception):
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    return False


def ensure_folder_shortcut(python_exe: str, app_root: Optional[Path] = None) -> bool:
    """
    ``Ledgebord.lnk`` i appmappen — klicka på den i stället för på main.pyw (som visar Pythons filikon).
    Skrivs bara om när något ändrats. Returnerar True om genvägen finns efteråt.
    """
    if not is_windows():
        return False
    root = Path(app_root or APP_ROOT)
    script = root / "main.pyw"
    if not script.is_file():
        return False
    icon = icon_file(root)
    want = {"target": python_exe, "args": f'"{script}"', "icon": str(icon) if icon else "", "workdir": str(root)}
    lnk = root / f"{APP_NAME}.lnk"
    mp = root / "data" / "folder_lnk.txt"
    with suppress(Exception):
        if lnk.is_file() and json.loads(mp.read_text(encoding="utf-8")) == want:
            return True
    if not create_shortcut(lnk, want["target"], want["args"], want["workdir"], want["icon"]):
        return False
    with suppress(Exception):
        mp.parent.mkdir(parents=True, exist_ok=True)
        mp.write_text(json.dumps(want, ensure_ascii=False, indent=1), encoding="utf-8")
    return True
