# -*- coding: utf-8 -*-
"""
Självläkande uppdatering: startar den uppdaterade appen och rullar tillbaka om den inte kommer igång.

Flöde
-----
1. ``core.updater.apply_update`` byter filerna och lägger i backupmappen (data/backups/app-update/<stamp>/)
   de ersatta filerna, ``manifest.json`` (vad som ersattes/lades till) och en KOPIA av den här filen
   som ``watchdog.py`` — kopian är från den gamla, fungerande versionen och påverkas därför inte av
   att den nya koden är trasig.
2. ``core.updater.schedule_restart`` skriver ``data/update_pending.json`` och startar kopian som en
   frikopplad process (``python watchdog.py --app-dir … --backup …``).
3. Watchdogen väntar tills den gamla appen stängts, startar ``main.pyw`` och väntar sedan högst
   ``--timeout`` sekunder (60) på att den nya appen bekräftar att den kom igång genom att ta bort
   ``update_pending.json`` (``confirm_healthy`` — appen gör det ~10 s efter uppstart eller vid ren
   avslutning).
4. Uteblir bekräftelsen — appen kraschar, hänger sig eller svarar aldrig — stoppas den, filerna
   återställs från backupen, nya filer tas bort, ``data/update_rollback.json`` skrivs och den
   gamla appen startas igen. Nästa start visar ett meddelande om vad som hänt.

Endast standardbiblioteket, importerar ingen annan TaskBord-kod. Skriver bara i appmappen.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Sequence

GUARD_TIMEOUT_SEC = 60
RESTART_DELAY_SEC = 6
PENDING_NAME = "update_pending.json"
ROLLBACK_NAME = "update_rollback.json"
LOG_NAME = "update_watchdog.log"
MANIFEST_NAME = "manifest.json"
WATCHDOG_COPY_NAME = "watchdog.py"
DEFAULT_PORTS = tuple(range(8765, 8777))
_BACKUP_META_FILES = frozenset({"UPPDATERING.txt", MANIFEST_NAME, WATCHDOG_COPY_NAME})
_PROTECTED_TOP = frozenset({"js", "data", ".git"})


# ---------------------------------------------------------------------------
# Hjälpare som även appen använder
# ---------------------------------------------------------------------------

def data_dir(app_dir: Path) -> Path:
    return Path(app_dir) / "data"


def pending_path(app_dir: Path) -> Path:
    return data_dir(app_dir) / PENDING_NAME


def rollback_path(app_dir: Path) -> Path:
    return data_dir(app_dir) / ROLLBACK_NAME


def write_pending(app_dir: Path, meta: Dict[str, object]) -> bool:
    try:
        data_dir(app_dir).mkdir(parents=True, exist_ok=True)
        tmp = pending_path(app_dir).with_suffix(".tmp")
        tmp.write_text(json.dumps(dict(meta, started=time.time()), ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, pending_path(app_dir))
        return True
    except OSError:
        return False


def read_pending(app_dir: Path) -> Optional[Dict[str, object]]:
    try:
        d = json.loads(pending_path(app_dir).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {}


def confirm_healthy(app_dir: Path) -> bool:
    """Appen anropar den när den kommit igång: tar bort ``update_pending.json``. True om en fanns."""
    try:
        pending_path(app_dir).unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def read_rollback(app_dir: Path) -> Optional[Dict[str, object]]:
    """Meddelande från en återställning som skett sedan senast (None om ingen)."""
    try:
        d = json.loads(rollback_path(app_dir).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def clear_rollback(app_dir: Path) -> None:
    try:
        rollback_path(app_dir).unlink()
    except OSError:
        pass


def write_manifest(backup_root: Path, meta: Dict[str, object]) -> None:
    Path(backup_root).mkdir(parents=True, exist_ok=True)
    (Path(backup_root) / MANIFEST_NAME).write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def copy_self_to(backup_root: Path) -> bool:
    """Lägg en kopia av den här filen i backupmappen (körs av den GAMLA, fungerande versionen)."""
    try:
        Path(backup_root).mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(__file__).resolve(), Path(backup_root) / WATCHDOG_COPY_NAME)
        return True
    except OSError:
        return False


def guard_command(app_dir: Path, backup_root: Path, exe: str, script: Path,
                  delay_sec: int = RESTART_DELAY_SEC, timeout_sec: int = GUARD_TIMEOUT_SEC) -> List[str]:
    return [
        exe, str(Path(backup_root) / WATCHDOG_COPY_NAME),
        "--app-dir", str(app_dir), "--backup", str(backup_root),
        "--exe", exe, "--script", str(script),
        "--delay", str(int(delay_sec)), "--timeout", str(int(timeout_sec)),
    ]


# ---------------------------------------------------------------------------
# Själva väktaren
# ---------------------------------------------------------------------------

def _log(app_dir: Path, text: str) -> None:
    try:
        data_dir(app_dir).mkdir(parents=True, exist_ok=True)
        with open(data_dir(app_dir) / LOG_NAME, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} | {text}\n")
    except OSError:
        pass


def _detached_kwargs() -> Dict[str, object]:
    kw: Dict[str, object] = {
        "close_fds": True, "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        kw["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        )
    else:
        kw["start_new_session"] = True
    return kw


def start_app(app_dir: Path, exe: str, script: Path) -> subprocess.Popen:
    return subprocess.Popen([exe, str(script)], cwd=str(app_dir), **_detached_kwargs())  # type: ignore[arg-type]


def taskbord_answers(ports: Sequence[int], timeout: float = 0.5) -> bool:
    """Svarar någon TaskBord på ``/health`` (mailbryggan, port 8765–8776)?"""
    for port in ports:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{int(port)}/health", timeout=timeout) as r:
                d = json.loads(r.read(65536).decode("utf-8", "replace"))
            if isinstance(d, dict) and str(d.get("app", "")).lower() == "taskbord":
                return True
        except Exception:
            continue
    return False


def _safe_rel(rel: str) -> Optional[Path]:
    p = Path(*str(rel).replace("\\", "/").split("/"))
    if p.is_absolute() or ".." in p.parts or not p.parts or p.parts[0] in _PROTECTED_TOP:
        return None
    return p


def _retry(fn, attempts: int = 6, wait: float = 0.5):
    for i in range(attempts):
        try:
            return fn()
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(wait)


def restore_files(app_dir: Path, backup_root: Path) -> Dict[str, int]:
    """Lägg tillbaka ersatta filer, ta bort tillagda. Returnerar {'restored','removed','failed'}."""
    app_dir, backup_root = Path(app_dir), Path(backup_root)
    res = {"restored": 0, "removed": 0, "failed": 0}
    try:
        manifest = json.loads((backup_root / MANIFEST_NAME).read_text(encoding="utf-8"))
        replaced = [str(x) for x in manifest.get("replaced", [])]
        new = [str(x) for x in manifest.get("new", [])]
    except (OSError, ValueError):
        # Ingen manifest: återställ allt som ligger i backupen (nya filer kan inte tas bort)
        replaced = [
            p.relative_to(backup_root).as_posix() for p in backup_root.rglob("*")
            if p.is_file() and p.name not in _BACKUP_META_FILES
        ]
        new = []
    for rel in replaced:
        sp = _safe_rel(rel)
        if sp is None:
            res["failed"] += 1
            continue
        src, dst = backup_root.joinpath(*sp.parts), app_dir.joinpath(*sp.parts)
        try:
            if not src.is_file():
                raise FileNotFoundError(str(src))
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_name(dst.name + ".rollback.tmp")
            shutil.copy2(src, tmp)
            _retry(lambda: os.replace(tmp, dst))
            res["restored"] += 1
        except OSError:
            res["failed"] += 1
    for rel in new:
        sp = _safe_rel(rel)
        if sp is None:
            res["failed"] += 1
            continue
        dst = app_dir.joinpath(*sp.parts)
        try:
            if dst.is_file():
                _retry(dst.unlink)
                res["removed"] += 1
            # tomma kataloger som uppdateringen skapade (inkl. __pycache__) städas bort
            parent = dst.parent
            while parent != app_dir and parent.is_dir() and app_dir in parent.parents:
                shutil.rmtree(parent / "__pycache__", ignore_errors=True)
                if any(parent.iterdir()):
                    break
                parent.rmdir()
                parent = parent.parent
        except OSError:
            res["failed"] += 1
    return res


def do_rollback(app_dir: Path, backup_root: Path, reason: str) -> Dict[str, object]:
    app_dir, backup_root = Path(app_dir), Path(backup_root)
    _log(app_dir, f"ÅTERSTÄLLER från {backup_root}: {reason}")
    counts = restore_files(app_dir, backup_root)
    meta: Dict[str, object] = {}
    try:
        meta = json.loads((backup_root / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    info: Dict[str, object] = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "reason": reason,
        "backup": str(backup_root),
        "tag": meta.get("tag", ""),
        "commit": meta.get("commit", ""),
        "fingerprint": meta.get("fingerprint", ""),
        **counts,
    }
    try:
        data_dir(app_dir).mkdir(parents=True, exist_ok=True)
        rollback_path(app_dir).write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass
    confirm_healthy(app_dir)           # pending bort
    _log(app_dir, f"klart: {counts}")
    return info


def supervise(app_dir: Path, backup_root: Path, exe: str, script: Path,
              delay_sec: float = RESTART_DELAY_SEC, timeout_sec: float = GUARD_TIMEOUT_SEC,
              ports: Sequence[int] = DEFAULT_PORTS, grace_sec: float = 3.0, poll_sec: float = 0.5) -> str:
    """
    Starta appen och vakta uppstarten. Returnerar 'healthy', 'single' (en annan instans svarade)
    eller 'rolled_back'.
    """
    app_dir, backup_root = Path(app_dir), Path(backup_root)
    _log(app_dir, f"start: väntar {delay_sec}s, vaktar {timeout_sec}s ({script})")
    time.sleep(max(0.0, delay_sec))
    try:
        proc = start_app(app_dir, exe, script)
    except OSError as e:
        do_rollback(app_dir, backup_root, f"appen kunde inte startas: {e}")
        _restart_old(app_dir, exe, script)
        return "rolled_back"
    t0 = time.monotonic()
    exited_at: Optional[float] = None
    reason = ""
    while True:
        if read_pending(app_dir) is None:
            _log(app_dir, "bekräftad: appen kom igång")
            return "healthy"
        rc = proc.poll()
        now = time.monotonic()
        if rc is not None and exited_at is None:
            exited_at = now
            _log(app_dir, f"appen avslutades (kod {rc}) innan den bekräftat")
        if exited_at is not None and now - exited_at >= grace_sec:
            if rc == 0 and taskbord_answers(ports):
                # startade inte nytt eftersom en annan TaskBord redan kör — inget att döma
                _log(app_dir, "en annan TaskBord-instans svarar — ingen återställning")
                confirm_healthy(app_dir)
                return "single"
            reason = f"appen avslutades med kod {rc} innan den kommit igång"
            break
        if now - t0 >= timeout_sec:
            if rc is None and taskbord_answers(ports):
                _log(app_dir, "bekräftelsen uteblev men appen svarar — behålls")
                confirm_healthy(app_dir)
                return "healthy"
            reason = (f"appen kom inte igång inom {int(timeout_sec)} s"
                      if rc is None else f"appen avslutades med kod {rc}")
            break
        time.sleep(poll_sec)
    if proc.poll() is None:
        try:
            proc.kill()
            proc.wait(timeout=10)
        except Exception:
            pass
    do_rollback(app_dir, backup_root, reason)
    _restart_old(app_dir, exe, script)
    return "rolled_back"


def _restart_old(app_dir: Path, exe: str, script: Path) -> None:
    try:
        start_app(app_dir, exe, script)
        _log(app_dir, "den förra versionen startad")
    except OSError as e:
        _log(app_dir, f"kunde inte starta den förra versionen: {e}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="TaskBord uppdateringsväktare")
    ap.add_argument("--app-dir", required=True)
    ap.add_argument("--backup", required=True)
    ap.add_argument("--exe", default=sys.executable)
    ap.add_argument("--script", required=True)
    ap.add_argument("--delay", type=float, default=RESTART_DELAY_SEC)
    ap.add_argument("--timeout", type=float, default=GUARD_TIMEOUT_SEC)
    ap.add_argument("--ports", default=",".join(map(str, DEFAULT_PORTS)))
    ap.add_argument("--grace", type=float, default=3.0)
    ap.add_argument("--poll", type=float, default=0.5)
    a = ap.parse_args(argv)
    ports = [int(p) for p in a.ports.split(",") if p.strip()]
    try:
        supervise(Path(a.app_dir), Path(a.backup), a.exe, Path(a.script), a.delay, a.timeout,
                  ports, a.grace, a.poll)
    except Exception as e:  # väktaren får aldrig lämna användaren utan app
        _log(Path(a.app_dir), f"OVÄNTAT FEL: {e!r}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
