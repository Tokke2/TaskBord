# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""
pip_update.py — VECKOUNDERHÅLL: kolla Pythons tillägg (paketen i requirements*.txt) och uppdatera dem. Python själv uppdateras inte.
En gång i veckan — helst måndag morgon kl 08:00 — inte vid varje start.

Hur "måndag 08:00" fungerar: veckan börjar måndag 08:00 (``slot_start``). Är veckans underhåll inte gjort är det
"dags". Står datorn/appen på vid 08:00 sker det då; annars vid första tillfälle därefter (första start via
STARTA_HAR.bat, eller när appen som redan körs är ledig — den startar då om tyst via FORSTA_START.bat /snabb /vecka).
Uppdateringen sker alltid medan Ledgebord är avstängd (inlästa filer går inte att byta på Windows).

Använder den installerade Pythons egna pip — ingen egen miljö (venv); paketen hamnar i samma Python som allt annat.

    python core/pip_update.py --due [--quiet]       exit 10 = veckans underhåll är inte gjort och appen kör inte
    python core/pip_update.py --wait-exit           väntar tills appen avslutats (exit 0), 1 om den fortfarande kör
    python core/pip_update.py --run [--quiet]       uppdatera paketen nu och bocka av veckan (vid fel: nytt försök efter 6 h)
    python core/pip_update.py --mark                bocka av veckan (efter fullständig installation)
    python core/pip_update.py --check               behövs något? (paket), ändrar inget

Regler:
  * Bara standardbiblioteket (körs före appen, så inga paket kan antas finnas).
  * Kraschar eller blockerar aldrig starten: offline, långsamt nät eller pip-fel → loggas och appen startar ändå.
  * Körs appen redan (/health svarar) hoppas uppdateringen över — inlästa .pyd/.dll går inte att byta på Windows.
  * Standardstrategin only-if-needed: ett beroende som andra program delar uppgraderas bara om ett krav kräver det.
  * Allt som händer loggas som en rad i loggar/pip_uppdatering.log (de 300 senaste raderna sparas).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional

LOG_NAME = "pip_uppdatering.log"
STATE_NAME = "veckounderhall.json"
SLOT_WEEKDAY = 0            # måndag
SLOT_HOUR = 8               # 08:00
RETRY_HOURS = 6             # misslyckat försök: nästa försök tidigast efter så här länge (bara via start, aldrig omstart)
KEEP_LINES = 300
PORTS = tuple(range(8765, 8777))
APP_NAMES = ("ledgebord", "taskbord")
PIP_FLAGS = ["--upgrade", "--disable-pip-version-check", "--no-input", "--progress-bar", "off",
             "--timeout", "10", "--retries", "1"]


def slot_start(now: Optional[datetime] = None) -> datetime:
    """Början på den här veckans underhållsfönster: senaste måndag 08:00 (lokal tid) före eller lika med ``now``."""
    now = now or datetime.now()
    mon = (now - timedelta(days=(now.weekday() - SLOT_WEEKDAY) % 7)).replace(hour=SLOT_HOUR, minute=0, second=0, microsecond=0)
    return mon - timedelta(days=7) if mon > now else mon


def _state_path(app_dir) -> Path:
    return Path(app_dir) / "loggar" / STATE_NAME


def read_state(app_dir) -> Dict[str, str]:
    try:
        d = json.loads(_state_path(app_dir).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _write_state(app_dir, **kw: str) -> None:
    try:
        st = read_state(app_dir)
        st.update(kw)
        p = _state_path(app_dir)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, p)
    except Exception:
        pass


def _parse(iso: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(iso) if iso else None
    except ValueError:
        return None


def mark_try(app_dir, now: Optional[datetime] = None) -> None:
    """Ett försök påbörjas (appen gör högst ETT omstartsförsök per vecka)."""
    _write_state(app_dir, last_try=(now or datetime.now()).isoformat(timespec="seconds"))


def mark_ok(app_dir, note: str = "", now: Optional[datetime] = None) -> None:
    """Veckans underhåll är gjort (eller inget behövdes)."""
    iso = (now or datetime.now()).isoformat(timespec="seconds")
    _write_state(app_dir, last_ok=iso, last_try=iso, last_note=note)


def weekly_due(app_dir, now: Optional[datetime] = None) -> bool:
    """
    Är veckans underhåll inte gjort? Dvs senaste lyckade underhåll är före veckans måndag 08:00, och — efter ett
    misslyckat försök — det har gått minst RETRY_HOURS sedan försöket.
    """
    now = now or datetime.now()
    st = read_state(app_dir)
    last_ok = _parse(st.get("last_ok", ""))
    if last_ok is not None and last_ok >= slot_start(now):
        return False
    last_try = _parse(st.get("last_try", ""))
    if last_try is not None and last_try >= slot_start(now) and now - last_try < timedelta(hours=RETRY_HOURS):
        return False
    return True


def app_may_restart_for_it(app_dir, now: Optional[datetime] = None) -> bool:
    """Appen som kör får starta om för underhållet högst en gång per vecka: dags OCH inget försök sedan veckans start."""
    now = now or datetime.now()
    if not weekly_due(app_dir, now):
        return False
    last_try = _parse(read_state(app_dir).get("last_try", ""))
    return last_try is None or last_try < slot_start(now)


def app_running(ports=PORTS, host: str = "127.0.0.1", timeout: float = 0.4) -> bool:
    """Svarar en körande Ledgebord (valfri version) på mail-bryggans /health?"""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for port in ports:
        try:
            with opener.open(f"http://{host}:{int(port)}/health", timeout=timeout) as resp:
                data = json.loads(resp.read(65536).decode("utf-8", "replace"))
            if isinstance(data, dict) and str(data.get("app", "")).lower() in APP_NAMES:
                return True
        except Exception:
            continue
    return False


def log_line(app_dir: Path, text: str) -> None:
    """En rad i loggar/pip_uppdatering.log (skapar mappen; de senaste KEEP_LINES raderna sparas). Kastar aldrig."""
    try:
        d = Path(app_dir) / "loggar"
        d.mkdir(parents=True, exist_ok=True)
        p = d / LOG_NAME
        old = p.read_text(encoding="utf-8", errors="replace").splitlines() if p.exists() else []
        old.append(f"{time.strftime('%Y-%m-%d %H:%M:%S')} | {text}")
        p.write_text("\n".join(old[-KEEP_LINES:]) + "\n", encoding="utf-8")
    except Exception:
        pass


def installed_names(output: str) -> List[str]:
    """'Successfully installed a-1.0 b-2.1' → ['a 1.0', 'b 2.1'] (inget → [])."""
    m = re.search(r"Successfully installed (.+)", output or "")
    if not m:
        return []
    out = []
    for tok in m.group(1).split():
        name, _, ver = tok.rpartition("-")
        out.append(f"{name} {ver}" if name else tok)
    return out


def _run_pip(args: List[str], timeout: float, runner: Optional[Callable] = None) -> subprocess.CompletedProcess:
    run = runner or subprocess.run
    kw: Dict = dict(capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if os.name == "nt":
        kw["creationflags"] = 0x08000000        # CREATE_NO_WINDOW
    return run([sys.executable, "-m", "pip", "install"] + args + PIP_FLAGS, **kw)


def update(app_dir, timeout: float = 120.0, runner: Optional[Callable] = None, running: Optional[bool] = None) -> Dict:
    """
    Kontrollera och uppdatera paketen. Returnerar {"status", "updated": [...], "failed": [...]}; status ∈
    {"hoppade", "ok", "uppdaterade", "fel"}. Kastar aldrig.
    """
    app_dir = Path(app_dir)
    res: Dict = {"status": "ok", "updated": [], "failed": []}
    try:
        if (app_running() if running is None else running):
            res["status"] = "hoppade"
            log_line(app_dir, "hoppade över: Ledgebord körs redan (paket i bruk kan inte bytas)")
            return res
        deadline = time.monotonic() + timeout
        for fname, required in (("requirements.txt", True), ("requirements-optional.txt", False)):
            req = app_dir / fname
            if not req.exists():
                continue
            left = deadline - time.monotonic()
            if left < 5:
                res["failed"].append(fname)
                log_line(app_dir, f"{fname}: tiden tog slut — appen startar ändå")
                continue
            try:
                cp = _run_pip(["-r", str(req)], left, runner)
            except subprocess.TimeoutExpired:
                res["failed"].append(fname)
                log_line(app_dir, f"{fname}: pip tog för lång tid (> {int(timeout)} s) — avbröts, appen startar ändå")
                continue
            if cp.returncode == 0:
                got = installed_names((cp.stdout or "") + (cp.stderr or ""))
                res["updated"] += got
                log_line(app_dir, f"{fname}: " + (("uppdaterade " + ", ".join(got)) if got else "alla paket är aktuella"))
            else:
                res["failed"].append(fname)
                tail = " ".join(((cp.stderr or cp.stdout or "").strip().splitlines() or ["okänt fel"])[-1:])[:200]
                kind = "OBLIGATORISKA paket" if required else "valfria tillägg"
                log_line(app_dir, f"{fname}: kunde inte uppdatera {kind} (offline?) — {tail}")
        res["status"] = "fel" if res["failed"] else ("uppdaterade" if res["updated"] else "ok")
    except Exception as e:      # aldrig blockera start
        res["status"] = "fel"
        log_line(app_dir, f"oväntat fel: {e}")
    return res


def wait_app_exit(max_wait: float = 60.0, step: float = 1.0, probe: Optional[Callable[[], bool]] = None,
                  sleep: Callable[[float], None] = time.sleep) -> bool:
    """Väntar tills ingen Ledgebord svarar på /health. True = avstängd (eller aldrig igång), False = kör fortfarande."""
    probe = probe or app_running
    waited = 0.0
    while True:
        if not probe():
            return True
        if waited >= max_wait:
            return False
        sleep(step)
        waited += step


# ---------------------------------------------------------------------------------------------------------
# Behövs något? (körs av appen i bakgrunden — ändrar ingenting). Python själv uppdateras INTE (Rickards val).
# ---------------------------------------------------------------------------------------------------------
def needs_update(app_dir, runner: Optional[Callable] = None, timeout: float = 90.0) -> Dict:
    """
    Behövs veckoöversynen? {"packages": [...], "error": ""}.
    Paket: pip install --dry-run (installerar inget). Pythons egen version kollas/uppdateras inte.
    Nätfel → "error" (då startar appen inte om i onödan).
    """
    app_dir = Path(app_dir)
    res: Dict = {"packages": [], "error": ""}
    try:
        for fname in ("requirements.txt", "requirements-optional.txt"):
            req = app_dir / fname
            if not req.exists():
                continue
            cp = _run_pip(["-r", str(req), "--dry-run"], timeout, runner)
            out = (cp.stdout or "") + (cp.stderr or "")
            if cp.returncode != 0:
                if fname == "requirements.txt":
                    res["error"] = " ".join((out.strip().splitlines() or ["pip-fel"])[-1:])[:200]
                    return res
                continue                                        # valfria tillägg får inte avgöra
            m = re.search(r"Would install (.+)", out)
            if m:
                res["packages"] += m.group(1).split()
    except subprocess.TimeoutExpired:
        res["error"] = "pip tog för lång tid"
    except Exception as e:
        res["error"] = str(e)[:200]
    return res


_MAINT_PROGRAM = (
    "import subprocess, sys, time\n"
    "time.sleep(float(sys.argv[1]))\n"
    "subprocess.Popen('cmd /c \"\"' + sys.argv[2] + '\" /snabb /vecka\"', cwd=sys.argv[3], close_fds=True, "
    "creationflags=0x08000000)\n"
)


def maintenance_command(app_dir, delay_sec: int = 8) -> Optional[List[str]]:
    """Kommando (frikopplad hjälpare) som efter ``delay_sec`` s kör FORSTA_START.bat /snabb /vecka dolt. None utanför Windows."""
    bat = Path(app_dir) / "FORSTA_START.bat"
    if sys.platform != "win32" or not bat.is_file():
        return None
    exe = sys.executable
    if exe.lower().endswith("python.exe") and Path(exe).with_name("pythonw.exe").is_file():
        exe = str(Path(exe).with_name("pythonw.exe"))
    return [exe, "-c", _MAINT_PROGRAM, str(int(delay_sec)), str(bat), str(app_dir)]


def schedule_maintenance(app_dir, delay_sec: int = 8, popen: Optional[Callable] = None) -> bool:
    """Starta hjälparen (appen avslutar sig själv direkt efteråt). True om hjälparen startade."""
    cmd = maintenance_command(app_dir, delay_sec)
    if cmd is None:
        return False
    try:
        kw: Dict = {"cwd": str(app_dir), "close_fds": True}
        if os.name == "nt":
            kw["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000   # DETACHED | NEW_PROCESS_GROUP | NO_WINDOW
        (popen or subprocess.Popen)(cmd, **kw)
        return True
    except Exception as e:
        log_line(Path(app_dir), f"kunde inte schemalägga veckounderhåll: {e}")
        return False


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    quiet = "--quiet" in argv
    timeout = 120.0
    if "--timeout" in argv:
        try:
            timeout = float(argv[argv.index("--timeout") + 1])
        except (ValueError, IndexError):
            pass
    app_dir = Path(__file__).resolve().parent.parent

    def say(msg: str) -> None:
        if not quiet:
            print(msg)

    if "--due" in argv:                         # exit 10 = dags (och appen kör inte)
        due = weekly_due(app_dir) and not app_running()
        say(f"[PAKET] veckounderhåll: {'dags' if due else 'inte dags'}")
        return 10 if due else 0
    if "--wait-exit" in argv:
        return 0 if wait_app_exit() else 1
    if "--mark" in argv:
        mark_ok(app_dir, "fullständig installation")
        return 0
    if "--check" in argv:
        r = needs_update(app_dir)
        say(f"[PAKET] {json.dumps(r, ensure_ascii=False)}")
        return 0
    # --run (eller utan flagga): uppdatera nu. Veckan bockas av när det gick bra; vid fel (offline m.m.) eller om appen
    # kör bockas den INTE av — nästa försök tidigast efter RETRY_HOURS via en start (appen startar aldrig om för det).
    mark_try(app_dir)
    res = update(app_dir, timeout=timeout)
    if res["status"] in ("ok", "uppdaterade"):
        mark_ok(app_dir, res["status"] + (": " + ", ".join(res["updated"]) if res["updated"] else ""))
    say(f"[PAKET] {res['status']}: " + (", ".join(res["updated"]) or "inget att uppdatera"))
    return 0            # starten får aldrig stoppas av paketkontrollen


if __name__ == "__main__":
    sys.exit(main())
