# -*- coding: utf-8 -*-
# Copyright © Rickard Längkvist, 2025–2026
"""
pip_update.py — vid varje start: kolla Pythons tillägg (paketen i requirements*.txt) och uppdatera dem.

Körs av FORSTA_START.bat /snabb (alltså STARTA_HAR.bat / STARTA_DOLT.vbs) INNAN appen startas, med den
installerade Pythons egna pip — ingen egen miljö (venv) skapas, paketen hamnar i samma Python som allt annat.

    python core/pip_update.py [--quiet] [--timeout SEK]

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
from pathlib import Path
from typing import Callable, Dict, List, Optional

LOG_NAME = "pip_uppdatering.log"
KEEP_LINES = 300
PORTS = tuple(range(8765, 8777))
APP_NAMES = ("ledgebord", "taskbord")
PIP_FLAGS = ["--upgrade", "--disable-pip-version-check", "--no-input", "--progress-bar", "off",
             "--timeout", "10", "--retries", "1"]


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


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    timeout = 120.0
    if "--timeout" in argv:
        try:
            timeout = float(argv[argv.index("--timeout") + 1])
        except (ValueError, IndexError):
            pass
    app_dir = Path(__file__).resolve().parent.parent
    res = update(app_dir, timeout=timeout)
    if "--quiet" not in argv:
        print(f"[PAKET] {res['status']}: " + (", ".join(res["updated"]) or "inget att uppdatera"))
    return 0            # starten får aldrig stoppas av paketkontrollen


if __name__ == "__main__":
    sys.exit(main())
