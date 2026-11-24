#!/usr/bin/env python3
"""
update_removed_test.py — filer som tagits bort i en release raderas även lokalt (med backup + återställning).

Kör:  python tester/update_removed_test.py     (ingen Qt behövs)
"""
from __future__ import annotations

import io
import json
import logging
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "core"))
logging.disable(logging.CRITICAL)

from core import update_watchdog as wd  # noqa: E402
from core import updater  # noqa: E402

ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("  ✗", name, extra)


def make_zip(files):
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as z:
        for k, v in files.items():
            z.writestr("Tokke2-TaskBord-abc1234/" + k, v)
        z.comment = b"abc1234def5678abc1234def5678abc1234def56"
    return bio.getvalue()


def http(zip_bytes):
    def _get(url, max_bytes, timeout=20.0, accept="", progress=None):
        if url == updater.LATEST_API:
            return json.dumps({"tag_name": "v1.0.0", "zipball_url": "https://api.github.com/z"}).encode()
        return zip_bytes
    return _get


def check_release(app, files):
    info = updater.check_for_update(app, http_get=http(make_zip(files)))
    return info


def new_app():
    d = Path(tempfile.mkdtemp(prefix="ledgebord_rm_"))
    return d


def put(app, rel, data=b"x\n"):
    p = app / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


R1 = {"main.pyw": b"print(1)\n", "core/a.py": b"A=1\n", "core/old.py": b"OLD=1\n", "ui/gone/x.py": b"X=1\n", "README.md": b"r\n"}
R2 = {"main.pyw": b"print(2)\n", "core/a.py": b"A=1\n", "README.md": b"r\n"}          # core/old.py och ui/gone/x.py borta

# 1. Första uppdateringen (inget manifest): inget raderas, manifest skrivs
app = new_app()
put(app, "main.pyw", b"print(0)\n")
put(app, "core/old.py", b"OLD=0\n")
put(app, "core/mine.py", b"# min egen fil\n")
info = check_release(app, R1)
check("utan manifest: inget markeras för borttagning (utom fasta listan)", info.removed == [])
bk = updater.apply_update(app, info)
m = updater.read_manifest(app)
check("manifest skrivs vid installation med alla programfiler", sorted(m) == sorted(R1), m)
check("manifestet ligger inuti data/ (inget utanför appmappen)", updater.manifest_path(app) == app / "data" / "installed_files.json" and updater.manifest_path(app).exists())

# 2. Nästa release har tagit bort två filer
info2 = check_release(app, R2)
check("borttagna filer upptäcks via manifestet", info2.removed == ["core/old.py", "ui/gone/x.py"], info2.removed)
check("egen fil som aldrig var programfil rörs inte", "core/mine.py" not in info2.removed)
check("uppdateringen räknas som ny även om bara filer tagits bort", not info2.up_to_date)
only_removed = check_release(app, {**R1, "main.pyw": (app / "main.pyw").read_bytes()})
check("ingenting nytt, ingenting borta → aktuell", only_removed.up_to_date)
fp_a = updater.fingerprint(info2)
info2b = check_release(app, {**R2, "main.pyw": R1["main.pyw"]})
check("fingeravtrycket ändras när borttagningslistan ändras", updater.fingerprint(info2b) != fp_a or info2b.removed != info2.removed)
txt = updater.describe(info2)
check("beskrivningen nämner borttagna filer", "tas bort" in txt and "core/old.py" in txt, txt)

bk2 = updater.apply_update(app, info2)
check("filerna raderades", not (app / "core" / "old.py").exists() and not (app / "ui" / "gone" / "x.py").exists())
check("tom mapp (ui/gone och ui) städades bort", not (app / "ui").exists())
check("programfiler, egen fil och js/data orörda", (app / "main.pyw").read_bytes() == b"print(2)\n" and (app / "core" / "mine.py").exists() and (app / "core" / "a.py").exists())
check("borttagna filer finns kvar i backupen", (bk2 / "core" / "old.py").exists() and (bk2 / "ui" / "gone" / "x.py").exists())
check("UPPDATERING.txt listar borttagna", "core/old.py" in (bk2 / "UPPDATERING.txt").read_text(encoding="utf-8"))
man = json.loads((bk2 / "manifest.json").read_text(encoding="utf-8")) if (bk2 / "manifest.json").exists() else {}
check("väktarens manifest: borttagna med i 'replaced' (återställs vid rollback)", "core/old.py" in man.get("replaced", []) and man.get("removed") == ["core/old.py", "ui/gone/x.py"], man)
check("manifestet uppdaterat till nya releasen", sorted(updater.read_manifest(app)) == sorted(R2))

# 3. Väktaren rullar tillbaka: borttagna filer kommer tillbaka
res = wd.restore_files(app, bk2)
check("väktaren återställer borttagna filer", (app / "core" / "old.py").read_bytes() == b"OLD=1\n" and (app / "ui" / "gone" / "x.py").exists(), res)
check("…och tidigare version av ändrade filer", (app / "main.pyw").read_bytes() == b"print(1)\n")

# 4. Fel mitt i installationen → allt (inkl. borttagna) rullas tillbaka
app = new_app()
put(app, "main.pyw", b"print(0)\n")
info = check_release(app, R1)
updater.apply_update(app, info)
info2 = check_release(app, R2)
real_unlink = Path.unlink
calls = {"n": 0}


def flaky_unlink(self, *a, **k):
    if self.name == "x.py" and self.parent.name == "gone":
        raise OSError("låst")
    return real_unlink(self, *a, **k)


Path.unlink = flaky_unlink  # type: ignore[assignment]
try:
    try:
        updater.apply_update(app, info2)
        check("fel vid radering ger UpdateError", False)
    except updater.UpdateError:
        check("fel vid radering ger UpdateError", True)
finally:
    Path.unlink = real_unlink  # type: ignore[assignment]
check("…och återställer allt: main.pyw, old.py och x.py är som förut", (app / "main.pyw").read_bytes() == b"print(1)\n" and (app / "core" / "old.py").exists() and (app / "ui" / "gone" / "x.py").exists())
check("…manifestet är oförändrat (R1)", sorted(updater.read_manifest(app)) == sorted(R1))

# 5. Skydd: js/, data/, .git, venv rörs aldrig, även om de står i manifestet/den fasta listan
app = new_app()
put(app, "main.pyw", b"print(1)\n")
for rel in ("js/active.json", "data/todo_app.log", ".git/config", ".venv/x.py", "venv/y.py", "core/__pycache__/a.pyc"):
    put(app, rel)
updater.write_manifest(app, ["main.pyw", "js/active.json", "data/todo_app.log", ".git/config", ".venv/x.py", "venv/y.py",
                             "core/__pycache__/a.pyc", "../utanfor.txt", "/etc/passwd", "C:/x.txt"])
info = check_release(app, {"main.pyw": b"print(1)\n"})
check("skyddade mappar och osäkra sökvägar tas aldrig bort", info.removed == [], info.removed)
check("…så releasen räknas som aktuell", info.up_to_date)

# 6. Fasta listan över filer som tagits bort ur repot förr (regelfunktionen m.fl.) — även utan manifest
app = new_app()
put(app, "main.pyw", b"print(1)\n")
put(app, "core/rules.py")
put(app, "ui/rules_dialog.py")
put(app, "TaskBord-Thunderbird.xpi")
info = check_release(app, {"main.pyw": b"print(1)\n"})
check("gamla regelfiler och gamla xpi:n tas bort även utan manifest", sorted(info.removed) == ["TaskBord-Thunderbird.xpi", "core/rules.py", "ui/rules_dialog.py"], info.removed)
check("…men bara om de fortfarande finns lokalt", check_release(new_app() if False else app, {"main.pyw": b"x"}).removed != [] )
info = check_release(app, {"main.pyw": b"print(1)\n", "core/rules.py": b"# tillbaka i releasen\n"})
check("finns filen i releasen tas den inte bort", "core/rules.py" not in info.removed)

# 7. Säkerhetsspärr: orimligt många borttagna → ingenting tas bort
app = new_app()
big = {f"core/m{i}.py": b"x=1\n" for i in range(60)}
big["main.pyw"] = b"print(1)\n"
for rel, data in big.items():
    put(app, rel, data)
updater.write_manifest(app, list(big))
info = check_release(app, {"main.pyw": b"print(1)\n"})                       # releasen "saknar" 60 av 61 filer
check("spärr: 60 av 61 filer saknas → ingenting tas bort", info.removed == [], len(info.removed))
small = {f"core/n{i}.py": b"x=1\n" for i in range(4)}
for rel, data in small.items():
    put(app, rel, data)
updater.write_manifest(app, list(small) + ["main.pyw"])
info = check_release(app, {"main.pyw": b"print(1)\n"})
check("fyra borttagna av fem tas bort (under 25 filer är normalt)", len(info.removed) == 4, info.removed)

# 8. Seed: aktuell installation utan manifest → manifest skrivs vid kontrollen
app = new_app()
for rel, data in R2.items():
    put(app, rel, data)
info = check_release(app, R2)
check("identisk med releasen: inget att göra", info.up_to_date)
check("seed_manifest skriver manifest när installationen är identisk", updater.seed_manifest(app, info) and sorted(updater.read_manifest(app)) == sorted(R2))
check("seed skriver inte över ett befintligt manifest", updater.seed_manifest(app, info) is False)
info_c = check_release(app, {**R2, "core/new.py": b"N=1\n"})
check("seed görs inte när något skiljer sig", updater.seed_manifest(new_app(), info_c) is False)

for d in list(Path(tempfile.gettempdir()).glob("ledgebord_rm_*")):
    shutil.rmtree(d, ignore_errors=True)
print(f"\nupdate_removed_test: {ok} lyckades, {fail} misslyckades")
sys.stdout.flush()
os._exit(1 if fail else 0)
