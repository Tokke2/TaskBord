#!/usr/bin/env python3
"""
no_console_test.py — inga konsolfönster vid start (Windows).

Kör:  python tester/no_console_test.py
Windows-beteendet simuleras med en falsk Popen-klass (Linux saknar CREATE_NO_WINDOW-effekt).
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = _fail = 0


def check(name, cond, extra=""):
    global _ok, _fail
    if cond:
        _ok += 1
    else:
        _fail += 1
        print(f"  ✗ {name} {extra}")


from core import no_console as nc  # noqa: E402

NW = 0x08000000


def fresh():
    class FakePopen:
        calls = []

        def __init__(self, *args, **kwargs):
            FakePopen.calls.append((args, kwargs))
    return FakePopen


F = fresh()
check("icke-Windows: ingen patch", nc.install(F, windows=False) is False and not getattr(F.__init__, nc._MARK, False))
check("Windows: patchen läggs på", nc.install(F, windows=True) is True)
F("schtasks", )
check("CREATE_NO_WINDOW läggs på anrop utan flaggor", F.calls[-1][1]["creationflags"] == NW)
F(["reg", "query"], creationflags=0x00000200)
check("befintliga flaggor behålls", F.calls[-1][1]["creationflags"] == (0x200 | NW))
F(["x"], creationflags=0x00000008 | 0x08000000)
check("redan satt NO_WINDOW/DETACHED ändras inte", F.calls[-1][1]["creationflags"] == (0x8 | NW))
F(["x"], creationflags=None)
check("creationflags=None hanteras", F.calls[-1][1]["creationflags"] == NW)
F(["x"], stdout=1, cwd="c:/")
check("övriga argument orörda", F.calls[-1][1]["stdout"] == 1 and F.calls[-1][1]["cwd"] == "c:/" and F.calls[-1][0] == (["x"],))
args = ("a",) + (None,) * 13 + (0x10,)
F(*args)
check("positionell creationflags rörs inte", F.calls[-1][0] == args and "creationflags" not in F.calls[-1][1])
n = len(F.calls)
check("andra anropet är en no-op (idempotent)", nc.install(F, windows=True) is False)
F("y")
check("inte dubbelpatchad", len(F.calls) == n + 1 and F.calls[-1][1]["creationflags"] == NW)

# riktig Popen på detta system är orörd när det inte är Windows
if sys.platform != "win32":
    check("riktiga subprocess.Popen orörd på Linux/macOS", nc.install() is False and not getattr(subprocess.Popen.__init__, nc._MARK, False))
    r = subprocess.run([sys.executable, "-c", "print(1)"], capture_output=True, text=True)
    check("subprocess fungerar som vanligt", r.stdout.strip() == "1")

# main.pyw anropar det FÖRE app-importerna
main = (ROOT / "main.pyw").read_text(encoding="utf-8")
check("main.pyw importerar no_console", "from core.no_console import install" in main)
check("…och anropar det före app.bootstrap",
      main.index("_no_console()") < main.index("from app.bootstrap import"))

# startfilerna
raw = (ROOT / "STARTA_DOLT.vbs").read_bytes()
check("STARTA_DOLT.vbs: ren ASCII + CRLF", all(b < 128 for b in raw) and b"\r\n" in raw)
vbs = raw.decode("ascii")
check("vbs kör FORSTA_START.bat /snabb dolt (fönsterstil 0)", "FORSTA_START.bat" in vbs and "/snabb" in vbs and re.search(r'", 0, False', vbs))
check("vbs: citattecken ger cmd /c \"\"<mapp>\\FORSTA_START.bat\" /snabb\"",
      'sh.Run "cmd /c """"" & dir & "\\FORSTA_START.bat"" /snabb"""' in vbs)
har = (ROOT / "STARTA_HAR.bat").read_bytes().decode("utf-8")
check("STARTA_HAR.bat startar via wscript (dolt)", "wscript //nologo" in har and "STARTA_DOLT.vbs" in har and "\r\n" in har)
check("STARTA_HAR.bat faller tillbaka på FORSTA_START.bat", 'call "%~dp0FORSTA_START.bat" /snabb' in har)
fs = (ROOT / "FORSTA_START.bat").read_bytes().decode("utf-8")
check("FORSTA_START.bat: saknas Python i snabbläge → synligt fönster (hänger inte dolt)",
      fs.count('if "%SNABB%"=="1" (start "Ledgebord - Installation" "%~f0" & exit /b 1)') == 2)
check("FORSTA_START.bat: startar appen med pythonw", 'start "" "%PYW%" "%APP%"' in fs and "pythonw.exe" in fs)
check("FORSTA_START.bat: CRLF kvar", fs.count("\r\n") > 100 and "\n" not in fs.replace("\r\n", ""))
inst = (ROOT / "INSTALLERA.bat").read_bytes().decode("utf-8")
check("skrivbordsgenvägen använder pythonw", "TargetPath = 'pythonw.exe'" in inst)

print(f"\nno_console_test: {_ok} lyckades, {_fail} misslyckades")
sys.exit(1 if _fail else 0)
