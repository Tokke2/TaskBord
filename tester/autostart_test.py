"""Test: Startup-.bat för autostart ska starta appen (inte citera exe+skript som EN fil)."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "core"))

ok = fail = 0


def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("  ✗", name)


import desktop  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    os.environ["APPDATA"] = tmp
    desktop.IS_WINDOWS = True
    cmd = r'"C:\Users\rl\AppData\Local\Programs\Python\Python314\pythonw.exe" "D:\Program\TaskBord\main.pyw"'
    check("skriver Startup-bat", desktop._enable_autostart_startup(cmd))
    bat = Path(tmp, *desktop.WINDOWS_STARTUP_SUBPATH.split("\\"), f"{desktop.AUTOSTART_VALUE_NAME}.bat")
    txt = bat.read_bytes().decode("utf-8")
    check("bat finns", bat.is_file())
    check("exe och skript citeras var för sig", f"start \"\" {cmd}" in txt)
    check("inte hela kommandot som EN fil", 'pythonw.exe D:\\Program' not in txt)
    check("CRLF-radslut", "\r\n" in txt and "\n" not in txt.replace("\r\n", ""))

# main.pyw: samma format via _autostart_bat_text (hämtas utan att importera Qt)
import ast  # noqa: E402

src = (ROOT / "main.pyw").read_text(encoding="utf-8")
fn = None
for node in ast.walk(ast.parse(src)):
    if isinstance(node, ast.FunctionDef) and node.name == "_autostart_bat_text":
        node.decorator_list = []
        fn = node
ns: dict = {}
exec(compile(ast.Module(body=[fn], type_ignores=[]), "main_bat", "exec"), ns)
t = ns["_autostart_bat_text"](cmd)
check("main.pyw: korrekt start-rad", f'start "" {cmd}\r\n' in t and '"""' not in t)

print(f"\nautostart_test: {ok} lyckades, {fail} misslyckades")
sys.exit(1 if fail else 0)
