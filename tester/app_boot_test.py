"""
app_boot_test.py — startar HELA appen på riktigt (Qt "offscreen") och kontrollerar loggen.

Fångar fel som bara syns när koden körs: saknade importer/namn efter omstrukturering, trasig
uppstart, undantag i AppController.__init__ osv. Körs i en kopia av projektet så ingenting
skrivs i din riktiga js\\ eller data\\.

* Kräver PySide6. På Linux utan GL-bibliotek (t.ex. en server) skapas tomma stubbar med gcc/nm.
* Hoppas över (exit 0) om något saknas, eller om en annan TaskBord redan kör (port 8765).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def skip(msg: str):
    print(f"  (hoppar över app_boot_test: {msg})")
    print("\napp_boot_test: 0 lyckades, 0 misslyckades (överhoppad)")
    sys.exit(0)


try:
    import PySide6  # noqa: F401
except ImportError:
    skip("PySide6 saknas")

env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
env.pop("TASKBORD_BACKUP_DIR", None)
work = Path(tempfile.mkdtemp(prefix="taskbord_boot_"))


def qt_imports_ok(e) -> tuple[bool, str]:
    r = subprocess.run([sys.executable, "-c", "from PySide6.QtWidgets import QApplication, QWidget"],
                       capture_output=True, text=True, env=e)
    return r.returncode == 0, r.stderr.strip().splitlines()[-1] if r.stderr.strip() else ""


ok_qt, why = qt_imports_ok(env)
if not ok_qt:
    if sys.platform != "linux" or not (shutil.which("gcc") and shutil.which("nm")):
        skip(f"Qt går inte att ladda ({why})")
    # tomma stubbar för GL/EGL/dbus/xkbcommon (offscreen ritar aldrig med dem)
    stubs = work / "stubs"
    stubs.mkdir()
    qt_lib = Path(PySide6.__file__).parent / "Qt"
    libs = [str(p) for p in list((qt_lib / "lib").glob("*.so*")) + list((qt_lib / "plugins/platforms").glob("*.so"))]
    und = subprocess.run(["nm", "-D", "--undefined-only", *libs], capture_output=True, text=True).stdout
    syms = sorted({l.split()[-1].split("@")[0] for l in und.splitlines() if l.strip()})
    spec = [("libGL.so.1", lambda s: s.startswith(("gl", "glX")) and s[2:3].isupper() or s.startswith("glX"), None),
            ("libEGL.so.1", lambda s: s.startswith("egl"), None),
            ("libdbus-1.so.3", lambda s: s.startswith("dbus_"), "LIBDBUS_1_3"),
            ("libxkbcommon.so.0", lambda s: s.startswith("xkb_"), "V_0.5.0")]
    for name, pick, ver in spec:
        c = stubs / (name + ".c")
        c.write_text("".join(f"void {s}(void){{}}\n" for s in syms if pick(s)) or "\n")
        cmd = ["gcc", "-shared", "-o", str(stubs / name), str(c), f"-Wl,-soname,{name}"]
        if ver:
            (stubs / (name + ".map")).write_text(f"{ver} {{ global: *; }};\n")
            cmd.append(f"-Wl,--version-script={stubs / (name + '.map')}")
        subprocess.run(cmd, check=True, capture_output=True)
    env["LD_LIBRARY_PATH"] = str(stubs) + os.pathsep + env.get("LD_LIBRARY_PATH", "")
    ok_qt, why = qt_imports_ok(env)
    if not ok_qt:
        skip(f"Qt går inte att ladda ens med stubbar ({why})")

# --- kopia av projektet (utan .git, js, data) ------------------------------------
app_copy = work / "TaskBord"
shutil.copytree(ROOT, app_copy, ignore=shutil.ignore_patterns(".git", "js", "data", "__pycache__", "*.pyc", "node_modules"))

ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("  ✗", name, extra)


proc = subprocess.Popen([sys.executable, "main.pyw"], cwd=app_copy, env=env,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
log = app_copy / "data" / "todo_app.log"
text = ""
t0 = time.time()
while time.time() - t0 < 60:
    if log.exists():
        text = log.read_text(encoding="utf-8", errors="replace")
        if "AppController klar" in text or "startar ingen ny instans" in text or proc.poll() is not None:
            break
    time.sleep(0.5)
time.sleep(1.5)   # låt de första timrarna hinna gå
alive = proc.poll() is None
proc.kill()
out = proc.communicate()[0] or ""
if log.exists():
    text = log.read_text(encoding="utf-8", errors="replace")

if "startar ingen ny instans" in text:
    shutil.rmtree(work, ignore_errors=True)
    skip("en annan TaskBord kör redan (port 8765)")

check("appen startade klart (AppController klar)", "AppController klar" in text, out[-400:])
check("release loggades", "Release: v" in text)
check("e-postbryggan startade", "E-postbrygga: http=PÅ" in text)
check("fönstret ritades (start: N aktiva)", "start: " in text and "aktiva" in text)
check("inga ERROR/CRITICAL i loggen", not any(("| ERROR" in l or "| CRITICAL" in l) for l in text.splitlines()),
      "\n".join(l[:200] for l in text.splitlines() if "| ERROR" in l or "| CRITICAL" in l)[:600])
check("inga ohanterade undantag", "OHANTERAT" not in text)
check("appen levde när testet avslutade den", alive)

shutil.rmtree(work, ignore_errors=True)
print(f"\napp_boot_test: {ok} lyckades, {fail} misslyckades")
sys.exit(1 if fail else 0)
