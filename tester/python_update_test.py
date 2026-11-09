#!/usr/bin/env python3
"""
python_update_test.py — Python uppdateras INTE av FORSTA_START.bat (varken vid start eller i veckounderhållet).
Finns Python används den som den är; bara om den SAKNAS installeras senaste stabila. Pythons tillägg (paket)
uppdateras som förut. Batchfilen går inte att köra på Linux, så testet läser strukturen.

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
check("bat: CRLF och bara ASCII", raw.count(b"\r\n") > 80 and b"\n" not in raw.replace(b"\r\n", b""))
lines = bat.replace("\r\n", "\n").split("\n")
labels = {l[1:].strip().lower() for l in lines if l.startswith(":") and not l.startswith("::")}
jumps = re.findall(r"(?:goto|call)\s+:(\w+)", bat, re.I)
missing = sorted({j for j in jumps if j.lower() not in labels and j.lower() != "eof"})
check("alla goto/call pekar på en etikett som finns", not missing, missing)
code = "\n".join(l for l in lines if not l.lstrip().upper().startswith("REM"))

check("ingen Python-uppdatering: inga upgrade_*-etiketter", not any(l.startswith(":upgrade") for l in lines))
check("ingen vecko_python-etikett och inget anrop", "vecko_python" not in bat)
check("ingen serie-logik (-Serie/SERIE) kvar i batchfilen", not re.search(r"-Serie|SERIE", bat))
check("ingen winget upgrade av Python", "winget upgrade" not in bat)
check("ingen jämförelse installerad vs senaste (PYNUM GEQ LATNUM)", not re.search(r"PYNUM!?%?\s+(GEQ|LSS|LEQ)\s+!?%?LATNUM", code, re.I))
check("rubriken säger att Python inte uppdateras", "Python UPPDATERAS INTE" in bat)

# Finns Python → används direkt, utan att slå upp senaste version
i = lines.index("REM ----- Finns Python? Anvand den som den ar (ingen uppdatering av Python). Saknas den? Installera senaste stabila. -----")
head = "\n".join(lines[i:i + 6])
check("Python finns → rakt till :python_ok (ingen get_latest före)", "if not defined PY goto :python_not_found" in head and "goto :python_ok" in head
      and "get_latest" not in head)
nf = "\n".join(lines[lines.index(":python_not_found"):lines.index(":python_ok")])
check("Python saknas → senaste stabila slås upp och installeras", "call :get_latest" in nf and "call :install_python" in nf)
check("get_latest/install_python finns kvar (för nyinstallation)", "get_latest" in labels and "install_python" in labels and "download_installer" in labels)
check(":snabb_paket → bara paketveckan (--due), ingen Python", "pip_update.py\" --due" in bat)

# paket uppdateras som förut
full = bat
check("full körning: pip + requirements uppgraderas fortfarande", "-m pip install --upgrade pip" in full and "requirements.txt" in full and "--upgrade -r" in full)
check("full körning bockar av veckan (--mark)", "pip_update.py\" --mark" in bat)
vk = "\n".join(lines[lines.index(":vecko_kor"):lines.index(":start_app")])
check("veckounderhåll: väntar på att appen stängs, kör sedan paketen (--run)", vk.index("--wait-exit") < vk.index("--run"))

# Python-koden
src = (ROOT / "core/pip_update.py").read_text(encoding="utf-8")
check("pip_update.py: ingen Python-patchkoll kvar (latest_patch/PY_FTP)", "latest_patch" not in src and "PY_FTP" not in src)
check("pip_update.py: needs_update ger bara paket + fel", '{"packages": [], "error": ""}' in src)
msrc = (ROOT / "app/mixins/maintenance.py").read_text(encoding="utf-8")
check("appens veckokoll bryr sig inte om Python-version", "res.get(\"python\")" not in msrc and "res['python']" not in msrc)
readme = (ROOT / "README.md").read_text(encoding="utf-8")
manual = (ROOT / "docs/MANUAL.md").read_text(encoding="utf-8")
check("README säger att Python inte uppdateras", "Python uppdateras inte" in readme)
check("manualen säger att Python inte uppdateras", "Python uppdateras inte" in manual)

# systemets egen Python: den i PATH vinner, mapparna genomsöks bara om PATH saknar en användbar
fp = bat.split("\n:find_python", 1)[1].split("\n:check_py", 1)[0] if "\n:find_python" in bat else ""
check("find_python: PATH-Python först", fp.find("%~$PATH:X") != -1 and fp.find("%~$PATH:X") < fp.find("LOCALAPPDATA"))
check("find_python: hittad PATH-Python används direkt (ingen jakt på nyare)", "if defined PY exit /b 0" in fp and fp.find("if defined PY exit /b 0") < fp.find("LOCALAPPDATA"))

print(f"\npython_update_test: {ok} lyckades, {fail} misslyckades")
sys.exit(1 if fail else 0)
