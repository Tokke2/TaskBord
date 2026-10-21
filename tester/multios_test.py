#!/usr/bin/env python3
"""
multios_test.py — TaskBord ska fungera på Windows, macOS och Linux.

Kör:  python tester/multios_test.py

Kontrollerar start-/installationsskripten för macOS/Linux (starta.sh, STARTA_TASKBORD.command), OS-anpassade
texter, fönsternivå via Qt-flaggor utanför Windows, autostart på Linux (XDG) och att uppdateringen aldrig rör .venv.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "ui"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

_ok = _fail = 0


def check(name, cond, extra=""):
    global _ok, _fail
    if cond:
        _ok += 1
    else:
        _fail += 1
        print(f"  ✗ {name} {extra}")


def child() -> None:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QWidget

    app = QApplication([])
    from app.mixins.desktop_shell import DesktopShellMixin

    res = []

    class Log:
        def __getattr__(self, n): return lambda *a, **k: None

    class Ctl(DesktopShellMixin):
        mode = "behind"
        _log = Log()
        def _desktop_mode(self): return self.mode

    c = Ctl()
    T = Qt.WindowType
    shell = QWidget()
    shell.show()
    app.processEvents()
    if sys.platform != "win32":
        c._apply_desktop_shell(shell, "w1")           # ska inte krascha utan windll
        f = shell.windowFlags()
        res.append(("behind → WindowStaysOnBottomHint", bool(f & T.WindowStaysOnBottomHint) and not (f & T.WindowStaysOnTopHint)))
        res.append(("fönstret är tool-fönster (ej i aktivitetsfältet)", bool(f & T.Tool)))
        res.append(("fönstret är fortfarande synligt efter flaggbyte", shell.isVisible()))
        res.append(("skalet markeras med lager 'behind'", getattr(shell, "_desktop_layer_mode", "") == "behind"))
        c.mode = "top"
        c._apply_desktop_shell(shell, "w1")
        f = shell.windowFlags()
        res.append(("top → WindowStaysOnTopHint", bool(f & T.WindowStaysOnTopHint) and not (f & T.WindowStaysOnBottomHint)))
        res.append(("skalet markeras med lager 'top'", getattr(shell, "_desktop_layer_mode", "") == "top"))
        c.mode = "behind"
        c._apply_desktop_shell(shell, "w1")
        res.append(("tillbaka till behind tar bort Top-flaggan", not (shell.windowFlags() & T.WindowStaysOnTopHint)))
    bad = [n for n, ok in res if not ok]
    print("CHILD", len(res) - len(bad), len(bad), flush=True)
    for n in bad:
        print("  ✗", n, flush=True)
    os._exit(0)


if "--child" in sys.argv:
    child()

# ---------------------------------------------------------------- skript ------------------
sh = ROOT / "starta.sh"
cmd = ROOT / "STARTA_TASKBORD.command"
check("starta.sh finns", sh.is_file())
check("starta.sh har shebang", sh.read_text(encoding="utf-8").startswith("#!/usr/bin/env bash"))
check("STARTA_TASKBORD.command finns och anropar starta.sh", cmd.is_file() and "starta.sh" in cmd.read_text(encoding="utf-8"))
check("skripten använder LF-radslut (inte CRLF)", b"\r" not in sh.read_bytes() and b"\r" not in cmd.read_bytes())
if shutil.which("git") and (ROOT / ".git").exists():
    ls = subprocess.run(["git", "ls-files", "-s", "starta.sh", "STARTA_TASKBORD.command"], cwd=ROOT, capture_output=True, text=True).stdout
    check("skripten är körbara i git (100755)", ls.count("100755") == 2, ls)
if shutil.which("bash"):
    r = subprocess.run(["bash", "-n", str(sh)], capture_output=True, text=True)
    check("starta.sh har giltig bash-syntax", r.returncode == 0, r.stderr)
    r = subprocess.run(["bash", str(sh), "--hjalp"], capture_output=True, text=True)
    check("starta.sh --hjalp fungerar", r.returncode == 0 and "första start" in r.stdout)
    r = subprocess.run(["bash", str(sh), "--okant"], capture_output=True, text=True)
    check("okänt val avvisas", r.returncode == 2)

    # Hela flödet i en tillfällig kopia: venv + paketinstallation + start + ingen ominstallation
    if os.name == "posix":
        tmp = Path(tempfile.mkdtemp(prefix="taskbord_sh_"))
        try:
            shutil.copy(sh, tmp / "starta.sh")
            (tmp / "main.pyw").write_text('import sys\nprint("hej från main", sys.prefix)\n', encoding="utf-8")
            (tmp / "requirements.txt").write_text("six\n", encoding="utf-8")
            r1 = subprocess.run(["bash", str(tmp / "starta.sh"), "--forgrund"], cwd=tmp, capture_output=True, text=True, timeout=240)
            if "Paketinstallationen misslyckades" in r1.stdout:
                print("  (ingen internetåtkomst för pip — hoppar över installationstesterna)")
            else:
                check("första start: skapar .venv i appmappen och startar appen",
                      r1.returncode == 0 and (tmp / ".venv" / "bin" / "python").exists() and "hej från main" in r1.stdout and str(tmp / ".venv") in r1.stdout,
                      r1.stdout + r1.stderr)
                check("första start: installerar paketen", "Installerar paket" in r1.stdout)
                check("paketen finns i .venv (inte i systemets Python)",
                      subprocess.run([str(tmp / ".venv/bin/python"), "-c", "import six"], capture_output=True).returncode == 0)
                r2 = subprocess.run(["bash", str(tmp / "starta.sh"), "--forgrund"], cwd=tmp, capture_output=True, text=True, timeout=60)
                check("andra start: ingen ominstallation", "Installerar" not in r2.stdout and "hej från main" in r2.stdout)
                (tmp / "requirements.txt").write_text("six\npackaging\n", encoding="utf-8")
                r3 = subprocess.run(["bash", str(tmp / "starta.sh"), "--forgrund"], cwd=tmp, capture_output=True, text=True, timeout=240)
                check("ändrade krav → installerar om", "Installerar paket" in r3.stdout and "hej från main" in r3.stdout)
                r4 = subprocess.run(["bash", str(tmp / "starta.sh"), "--snabb", "--forgrund"], cwd=tmp, capture_output=True, text=True, timeout=60)
                check("--snabb hoppar över installation", "Installerar" not in r4.stdout)
                check("inget skrivs utanför appmappen (bara .venv, data, filerna)",
                      {p.name for p in tmp.iterdir()} <= {".venv", "main.pyw", "requirements.txt", "starta.sh", "data", "__pycache__"},
                      str(sorted(p.name for p in tmp.iterdir())))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

# ------------------------------------------------------- OS-anpassade texter ---------------
from app import platform_utils as pu  # noqa: E402

real = sys.platform
try:
    for plat, want_inst, want_xpi in (("win32", "FORSTA_START.bat", "SKAPA_XPI.bat"),
                                      ("darwin", "./starta.sh", "python3 skapa_xpi.py"),
                                      ("linux", "./starta.sh", "python3 skapa_xpi.py")):
        sys.platform = plat
        check(f"{plat}: installationsskript = {want_inst}", pu.install_script_name() == want_inst)
        check(f"{plat}: xpi-kommando = {want_xpi}", pu.xpi_script_hint() == want_xpi)
finally:
    sys.platform = real

# ------------------------------------------------------- uppdatering rör inte .venv ---------
from core import updater  # noqa: E402

check("uppdateringen skyddar .venv", {".venv", "js", "data"} <= set(updater.PROTECTED_TOP))
check(".venv ligger i .gitignore", ".venv/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines())
req = (ROOT / "requirements.txt").read_text(encoding="utf-8")
check("pywin32 krävs bara på Windows", any("pywin32" in l and 'sys_platform == "win32"' in l for l in req.splitlines()))

# ------------------------------------------------------- Linux: autostart (XDG) ------------
if real.startswith("linux"):
    home = Path(tempfile.mkdtemp(prefix="taskbord_home_"))
    try:
        env = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"))
        code = ("import sys; sys.path.insert(0,'core'); sys.path.insert(0,'.'); import desktop as d; "
                "a=d.enable_autostart(); b=d.is_autostart_enabled(); c=d.disable_autostart(); e=d.is_autostart_enabled(); "
                "print('R', a, b, c, e)")
        r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
        line = [l for l in r.stdout.splitlines() if l.startswith("R ")]
        check("Linux: autostart på → .desktop skapas, av → tas bort", line and line[-1] == "R True True True False", r.stdout[-300:] + r.stderr[-300:])
    finally:
        shutil.rmtree(home, ignore_errors=True)

# ------------------------------------------------------- Qt: fönsternivå utan Win32 ---------
if real != "win32":
    from _qtenv import qt_env

    work = Path(tempfile.mkdtemp(prefix="taskbord_mos_"))
    env, why = qt_env(work)
    if env is None:
        print(f"  (Qt-testerna hoppas över: {why})")
    else:
        r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--child"], cwd=ROOT, env=env,
                           capture_output=True, text=True, timeout=120)
        line = [l for l in r.stdout.splitlines() if l.startswith("CHILD ")]
        if line:
            _, a, b = line[-1].split()
            _ok += int(a)
            _fail += int(b)
            for l in r.stdout.splitlines():
                if l.strip().startswith("✗"):
                    print(l)
        else:
            check("Qt-barnprocessen körde klart", False, (r.stdout + r.stderr)[-1200:])
    shutil.rmtree(work, ignore_errors=True)

print(f"\nmultios_test: {_ok} lyckades, {_fail} misslyckades")
sys.exit(1 if _fail else 0)
