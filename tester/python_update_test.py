#!/usr/bin/env python3
"""
python_update_test.py — FORSTA_START.bat: finns Python uppdateras den i SAMMA serie (ingen ny installation);
bara om den saknas installeras senaste stabila. Batchfilen går inte att köra på Linux, så testet läser
strukturen och simulerar beslutet.

Kör:  python tester/python_update_test.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("  ✗", name, extra)


raw = (ROOT / "FORSTA_START.bat").read_bytes()
bat = raw.decode("ascii")        # ASCII-only: cmd.exe läser filen i systemets teckentabell
check("bat: CRLF och bara ASCII", raw.count(b"\r\n") > 100 and b"\n" not in raw.replace(b"\r\n", b""))
lines = bat.replace("\r\n", "\n").split("\n")
labels = {l[1:].strip().lower() for l in lines if l.startswith(":") and not l.startswith("::")}
jumps = re.findall(r"(?:goto|call)\s+:(\w+)", bat, re.I)
missing = sorted({j for j in jumps if j.lower() not in labels and j.lower() != "eof"})
check("alla goto/call pekar på en etikett som finns", not missing, missing)


def block(label):
    i = next(n for n, l in enumerate(lines) if l.strip().lower() == ":" + label)
    out = []
    for l in lines[i + 1:]:
        if l.startswith(":"):
            break
        out.append(l)
    return "\n".join(out)


main = bat[:bat.index("\r\n:find_python\r\n")]
check("Python finns → serien tas ur den installerade versionen (3.<minor>)", 'set "SERIE=3.!SMIN!"' in main and "PYNUM/1000" in main)
check("serien skickas till hamta_python_version.ps1 (-Serie)", '-Serie !SERIE!' in main and "ps1\" %PSARG%" in bat)
check("är den inte äldre än senaste i serien → ingen uppdatering", "if !PYNUM! GEQ !LATNUM! goto :python_uptodate" in main)
check("kan versionen inte läsas (offline) → fortsätt med installerad", "if not defined PYVER goto :python_noupdate" in main)

# installationen får bara nås när Python SAKNAS
inst_calls = [m.start() for m in re.finditer(r"call :install_python", bat)]
check("install_python anropas på ett ställe", len(inst_calls) == 1)
nf = bat.index(":python_not_found")
check("…och bara under 'Python saknas'", inst_calls and inst_calls[0] > nf)
check("Python finns → hoppar aldrig till installationen (python_not_found nås bara om PY saknas)",
      "if not defined PY goto :python_not_found" in main and main.index("if not defined PY goto :python_not_found") < main.index("call :upgrade_python"))
up = block("upgrade_python")
check("uppdateringen kör inte install_python", "install_python" not in up and "winget install" not in bat[bat.index(":upgrade_python"):bat.index(":download_installer")])
check("alla-användare-installation (Program Files) hoppas över utan admin/ny installation", 'find /i "%ProgramFiles%"' in up and "upgrade_allusers" in up)
check("uppdatering per användare på plats (/quiet InstallAllUsers=0)", "/quiet InstallAllUsers=0" in up)
check("reserv: winget UPGRADE för samma serie", "winget upgrade -e --id Python.Python.%SERIE%" in bat)
check("misslyckad uppdatering stoppar inte starten", block("upgrade_fail").strip().endswith("exit /b 0") and "fortsatter" in block("upgrade_fail"))
check("snabbstart (/snabb) uppdaterar aldrig Python själv (bara paketen, se pip_update_test)", bat.index('if "%SNABB%"=="1" if defined PY goto :snabb_paket') < bat.index("call :get_latest"))
check("fortfarande: pip/paket och start efter Python-steget", "[3/5]" in bat and "[5/5] Startar Ledgebord" in bat)

# PowerShell: serie-läge
ps = (ROOT / "hamta_python_version.ps1").read_text(encoding="utf-8")
check("ps1: -Serie-parameter, validerad som N.N", "param([string]$Serie" in ps and r"'^\d+\.\d+$'" in ps)
check("ps1: tar bara versioner med Windows-installer (HEAD på amd64-exe)", "-Method Head" in ps and "-amd64.exe" in ps)
check("ps1: utan argument oförändrat (senaste stabila)", "Latest Python 3 Release" in ps)

# Simulera ps1:s urval mot en katalogsida (ftp/python/)
listing = '<a href="3.14.0/">3.14.0/</a><a href="3.14.2/">3.14.2/</a><a href="3.14.10/">3.14.10/</a><a href="3.14.0rc1/">x</a><a href="3.140.1/">x</a><a href="3.13.9/">3.13.9/</a>'
found = sorted((int(m.group(2)) for m in re.finditer(r'href="(' + re.escape("3.14") + r'\.(\d+))/"', listing)), reverse=True)
check("serie 3.14: 3.14.10 > 3.14.2 (numerisk sortering) och rc/3.140/3.13 räknas inte", found == [10, 2, 0], found)

# Simulera beslutet
def decide(installed_pynum, latest_in_series, latest_stable, all_users=False):
    if installed_pynum:
        if latest_in_series is None:
            return "fortsätt"
        if installed_pynum >= latest_in_series:
            return "redan senaste"
        return "hoppar över (admin)" if all_users else "uppdatera"
    return "installera" if latest_stable else "fel"

check("sim: 3.14.7 installerad, 3.14.9 finns → uppdatera (inte installera)", decide(14007, 14009, 15000) == "uppdatera")
check("sim: 3.14.9 installerad → redan senaste (3.15 finns men installeras inte)", decide(14009, 14009, 15000) == "redan senaste")
check("sim: offline → fortsätt", decide(14007, None, None) == "fortsätt")
check("sim: alla användare → hoppar över", decide(14007, 14009, 15000, True) == "hoppar över (admin)")
check("sim: saknas → installera senaste stabila", decide(0, None, 15000) == "installera")

print(f"\npython_update_test: {ok} lyckades, {fail} misslyckades")
sys.exit(1 if fail else 0)
