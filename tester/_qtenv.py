"""
_qtenv.py — gemensam hjälpare för tester som behöver riktiga Qt-widgets (offscreen).

``qt_env(work)`` returnerar (env, None) när Qt går att ladda — på Linux utan GL-bibliotek
skapas först tomma stubbar (libGL/libEGL/libdbus/libxkbcommon) med gcc/nm i ``work`` — eller
(None, "orsak") om Qt inte går att få igång (testet ska då hoppa över sig självt).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _qt_ok(env) -> tuple[bool, str]:
    r = subprocess.run([sys.executable, "-c", "from PySide6.QtWidgets import QApplication, QWidget"],
                       capture_output=True, text=True, env=env)
    return r.returncode == 0, r.stderr.strip().splitlines()[-1] if r.stderr.strip() else ""


def qt_env(work: Path):
    try:
        import PySide6
    except ImportError:
        return None, "PySide6 saknas"
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    ok, why = _qt_ok(env)
    if ok:
        return env, None
    if sys.platform != "linux" or not (shutil.which("gcc") and shutil.which("nm")):
        return None, f"Qt går inte att ladda ({why})"
    stubs = Path(work) / "stubs"
    stubs.mkdir(parents=True, exist_ok=True)
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
    ok, why = _qt_ok(env)
    if not ok:
        return None, f"Qt går inte att ladda ens med stubbar ({why})"
    return env, None
