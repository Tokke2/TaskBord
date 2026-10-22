"""bugreport_test.py — felrapporten innehåller det som behövs, och ALDRIG uppgifter/hemligheter."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for sub in ("", "core"):
    sys.path.insert(0, str(ROOT / sub))
from core import bugreport as br  # noqa: E402

ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("  ✗", name, extra)


tmp = Path(tempfile.mkdtemp(prefix="taskbord_br_"))
app = tmp / "app"
(app / "js" / "google").mkdir(parents=True)
(app / "data").mkdir()
(app / "core").mkdir()
(app / "main.pyw").write_text("print(1)\n", encoding="utf-8")
(app / "core" / "x.py").write_text("A=1\n", encoding="utf-8")
(app / "Ledgebord-Thunderbird.xpi").write_bytes(b"PK")
(app / "js" / "active.json").write_text(json.dumps({"tasks": [{"title": "HEMLIG UPPGIFT om lönen"}]}), encoding="utf-8")
(app / "js" / "google" / "token.json").write_text("GOOGLE-REFRESH-TOKEN-xyz", encoding="utf-8")
(app / "js" / "settings.json").write_text(json.dumps({
    "mail_bridge_token": "abcdef1234567890SECRET", "theme": "dark", "mail_bridge_port": 8765,
    "google_client_secret": "GOCSPX-hemlig", "update_notified": "", "nested": {"api_key": "KEY123456789", "ok": 1},
}), encoding="utf-8")
log = "\n".join(
    [f"rad {i}" for i in range(5000)]
    + ["POST /task token=abcdef1234567890SECRET ok",
       "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig",
       "mail från anna.svensson@foretag.se ämne Rapport"]
)
(app / "data" / "todo_app.log").write_text(log, encoding="utf-8")
(app / "data" / "update_watchdog.log").write_text("watchdog rad\n", encoding="utf-8")

out = br.create_report(app, extra={"Release": "6.4.1 v7"})
check("zip skapad i data/felrapporter i appmappen", out.parent == app / "data" / "felrapporter" and out.is_file(), str(out))
with zipfile.ZipFile(out) as z:
    names = set(z.namelist())
    blob = b"".join(z.read(n) for n in names).decode("utf-8", "replace")
    check("innehåller info, filer, logg, inställningar, väktarlogg, läs-mig",
          {"info.txt", "filer.txt", "todo_app.log", "settings.json", "update_watchdog.log", "LÄS_MIG.txt"} <= names, str(names))
    info = z.read("info.txt").decode("utf-8")
    logtxt = z.read("todo_app.log").decode("utf-8")
    st = json.loads(z.read("settings.json").decode("utf-8"))
    files = z.read("filer.txt").decode("utf-8")
check("uppgifter tas inte med", "HEMLIG UPPGIFT" not in blob and "active.json" not in files)
check("Google-token tas inte med", "GOOGLE-REFRESH-TOKEN" not in blob)
check("token i loggen maskad", "abcdef1234567890SECRET" not in blob and "token=***" in logtxt)
check("Bearer maskad", "eyJhbGciOiJIUzI1NiJ9" not in blob and "Bearer ***" in logtxt)
check("mailadress maskad men domänen kvar", "anna.svensson" not in blob and "***@foretag.se" in logtxt)
check("inställningar: hemligheter ***, resten kvar",
      st["mail_bridge_token"] == "***" and st["google_client_secret"] == "***" and st["nested"]["api_key"] == "***"
      and st["theme"] == "dark" and st["mail_bridge_port"] == 8765 and st["nested"]["ok"] == 1, str(st))
check("tom hemlig inställning lämnas (visar att den INTE är satt)", st["update_notified"] == "")
check("loggen kortas till de sista raderna", "rad 4999" in logtxt and "rad 0\n" not in logtxt and len(logtxt.splitlines()) <= br.LOG_TAIL_LINES)
check("filtabell har fingeravtryck för programfiler", "main.pyw" in files and "core/x.py" in files and "Ledgebord-Thunderbird.xpi" in files)
check("info har release, Python och xpi", "6.4.1 v7" in info and "Python:" in info and "xpi sha256" in info)

# tom mapp / saknad logg och settings kraschar inte
empty = tmp / "empty"
empty.mkdir()
o2 = br.create_report(empty)
with zipfile.ZipFile(o2) as z:
    check("tom installation: rapport ändå", "info.txt" in z.namelist() and "kunde inte läsas" in z.read("settings.json").decode())
# unika namn + rotation
for i in range(14):
    br.create_report(app, now=1_700_000_000 + i * 60)
check("bara de senaste 10 behålls", len(list((app / "data" / "felrapporter").glob("*.zip"))) == br.KEEP_REPORTS)
a = br.create_report(app, now=1_800_000_000)
b = br.create_report(app, now=1_800_000_000)
check("samma sekund ger olika filer", a != b and a.exists() and b.exists())
shutil.rmtree(tmp, ignore_errors=True)
print(f"\nbugreport_test: {ok} lyckades, {fail} misslyckades")
sys.exit(1 if fail else 0)
