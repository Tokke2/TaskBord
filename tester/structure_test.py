"""
structure_test.py — skyddsnät för kodstrukturen (main.pyw delad i app/-paketet).

* alla moduler i app/ går att importera (inga cirkulära importer, inga trasiga namn vid import)
* AppController har alla mixins och ingen metod definieras två gånger (annars vinner en tyst)
* inga odefinierade namn i app/ (pyflakes, om det finns installerat)
* main.pyw är en liten startfil; sökvägar byggs från SCRIPT_DIR, inte från modulens egen plats
* INSTALLERA.bat kopierar app\\
"""
from __future__ import annotations

import importlib
import inspect
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("  ✗", name, extra)


files = sorted((ROOT / "app").rglob("*.py"))
mods = [".".join(p.relative_to(ROOT).with_suffix("").parts).removesuffix(".__init__") for p in files]
check("app/ innehåller moduler", len(mods) >= 20, str(len(mods)))

for m in mods:
    try:
        importlib.import_module(m)
        check(f"import {m}", True)
    except Exception as e:  # pragma: no cover
        check(f"import {m}", False, f"{type(e).__name__}: {e}")

# --- AppController ---------------------------------------------------------------
from app.controller import AppController  # noqa: E402

mixins = [c for c in AppController.__mro__ if c.__name__.endswith("Mixin")]
mixin_files = sorted(p.stem for p in (ROOT / "app" / "mixins").glob("*.py") if p.stem != "__init__")
check("en mixin per fil i app/mixins/", len(mixins) == len(mixin_files), f"{len(mixins)} mixins, {len(mixin_files)} filer")

seen: dict[str, str] = {}
dups = []
for cls in AppController.__mro__:
    if cls is object:
        continue
    for name, val in vars(cls).items():
        if inspect.isfunction(val) or isinstance(val, (staticmethod, classmethod, property)):
            if name in seen:
                dups.append((name, seen[name], cls.__name__))
            seen[name] = cls.__name__
check("ingen metod definieras i två klasser (skuggning)", not dups, str(dups[:5]))
for must in ("_check_for_updates", "_populate_tray_menu", "_init_mail_bridge", "_toggle_autostart",
             "_export_calendar_ics", "shutdown", "run", "_apply_desktop_shell"):
    check(f"AppController.{must} finns", hasattr(AppController, must))

# --- main.pyw ----------------------------------------------------------------
main_src = (ROOT / "main.pyw").read_text(encoding="utf-8")
check("main.pyw är en liten startfil (<200 rader)", main_src.count("\n") < 200, str(main_src.count("\n")))
check("main.pyw startar run()", "sys.exit(run())" in main_src)
check("main.pyw lägger skriptmappen i sys.path", "sys.path.insert(0, _HERE)" in main_src)

# --- sökvägar: aldrig från modulens egen plats (app/ ligger ett steg ner) -------------
for p in files:
    src = p.read_text(encoding="utf-8")
    uses = [l for l in src.splitlines() if "__file__" in l and '"__file__"' not in l]
    allowed = p.name in ("constants.py", "bootstrap.py")
    bad = [l for l in uses if not (p.name == "constants.py" and "SCRIPT_DIR" in l)
           and not (p.name == "bootstrap.py" and "pathname=__file__" in l)]
    check(f"{p.relative_to(ROOT)}: inga sökvägar från __file__", not bad, str(bad[:2]))
const = (ROOT / "app" / "constants.py").read_text(encoding="utf-8")
check("SCRIPT_DIR = appmappen (ett steg upp från app/)", "Path(__file__).resolve().parent.parent" in const)
from app.constants import SCRIPT_DIR  # noqa: E402
check("SCRIPT_DIR pekar på mappen med main.pyw", (SCRIPT_DIR / "main.pyw").is_file(), str(SCRIPT_DIR))
check("autostart pekar på main.pyw i appmappen", "SCRIPT_DIR / \"main.pyw\"" in (ROOT / "app/mixins/autostart.py").read_text(encoding="utf-8"))

# --- odefinierade namn ------------------------------------------------------------
try:
    r = subprocess.run([sys.executable, "-m", "pyflakes", str(ROOT / "app"), str(ROOT / "main.pyw")],
                       capture_output=True, text=True)
    if "No module named pyflakes" in r.stderr:
        raise FileNotFoundError
    undefined = [l for l in r.stdout.splitlines() if "undefined name" in l and "'QWidget'" not in l]
    check("inga odefinierade namn i app/ och main.pyw", not undefined, "\n".join(undefined[:5]))
except FileNotFoundError:
    print("  (pyflakes saknas — hoppar över kontrollen av odefinierade namn)")

# --- installationsskriptet --------------------------------------------------------
bat = (ROOT / "INSTALLERA.bat").read_text(encoding="utf-8")
check("INSTALLERA.bat kopierar app\\ och app\\mixins\\", "app\\*.py" in bat and "app\\mixins\\*.py" in bat)

print(f"\nstructure_test: {ok} lyckades, {fail} misslyckades")
sys.exit(1 if fail else 0)
