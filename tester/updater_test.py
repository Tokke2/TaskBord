"""Test: 🔄 Sök ny version (core/updater.py) — utan nätverk (falsk http_get)."""
import io
import json
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ok = fail = 0


def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("  ✗", name)


from core import updater  # noqa: E402
from core.updater import UpdateError  # noqa: E402


def make_zip(files, top="Tokke2-TaskBord-abc1234", comment=b"abc1234def5678abc1234def5678abc1234def56"):
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as z:
        z.writestr(top + "/", "")
        for k, v in files.items():
            z.writestr(f"{top}/{k}", v)
        z.comment = comment
    return bio.getvalue()


def fake_http(zip_bytes, tag="v1.0.0"):
    def _get(url, max_bytes, timeout=20.0, accept=""):
        if url == updater.LATEST_API:
            return json.dumps({
                "tag_name": tag, "name": "TaskBord " + tag, "published_at": "2026-10-13T08:28:09Z",
                "html_url": "https://github.com/x/y/releases/tag/" + tag,
                "zipball_url": "https://api.github.com/repos/x/y/zipball/" + tag,
            }).encode()
        return zip_bytes
    return _get


NEW_MAIN = b"print('ny version')\n"
REL = {
    "main.pyw": NEW_MAIN,
    "core/a.py": b"X = 2\n",
    "core/b.py": b"Y = 1\n",          # ny fil
    "README.md": b"hej\n",
    "js/active.json": b"{}",          # ska ALDRIG skrivas
    "data/backups/x.zip": b"zzz",     # ska ALDRIG skrivas
    "core/__pycache__/a.pyc": b"zz",  # hoppas över
}

with tempfile.TemporaryDirectory() as d:
    app = Path(d)
    (app / "core").mkdir()
    (app / "js").mkdir()
    (app / "data").mkdir()
    (app / "main.pyw").write_bytes(b"print('gammal')\n")
    (app / "core" / "a.py").write_bytes(b"X = 1\n")
    (app / "README.md").write_bytes(b"hej\n")                 # oförändrad
    (app / "js" / "active.json").write_bytes(b'{"tasks": [1,2,3]}')
    (app / "lokal_extra.txt").write_bytes(b"min fil")          # finns inte i releasen

    info = updater.check_for_update(app, fake_http(make_zip(REL)))
    check("tag + commit lästes", info.tag == "v1.0.0" and info.commit.startswith("abc1234"))
    check("toppmappen togs bort", "main.pyw" in info.files and not any(k.startswith("Tokke2") for k in info.files))
    check("js/ och data/ ingår aldrig", not any(k.startswith(("js/", "data/")) for k in info.files))
    check("pycache hoppas över", not any("__pycache__" in k for k in info.files))
    check("ändrade + nya hittades", info.changed == ["core/a.py", "core/b.py", "main.pyw"])
    check("ny fil markerad", info.new_files == ["core/b.py"])
    check("oförändrad README räknas inte", "README.md" not in info.changed)
    check("inte up_to_date", not info.up_to_date)
    check("beskrivning nämner filer", "core/a.py" in updater.describe(info))

    # CRLF-skillnad ensam är ingen uppdatering
    (app / "README.md").write_bytes(b"hej\r\n")
    info2 = updater.check_for_update(app, fake_http(make_zip(REL)))
    check("radslut räknas inte som ändring", "README.md" not in info2.changed)

    # installera
    bk = updater.apply_update(app, info)
    check("main.pyw uppdaterad", (app / "main.pyw").read_bytes() == NEW_MAIN)
    check("ny fil skapad", (app / "core" / "b.py").read_bytes() == b"Y = 1\n")
    check("uppgifter orörda", (app / "js" / "active.json").read_bytes() == b'{"tasks": [1,2,3]}')
    check("lokal extrafil kvar", (app / "lokal_extra.txt").read_bytes() == b"min fil")
    check("inget i data/ skrevs av uppdateringen utom backup", not (app / "data" / "backups" / "x.zip").exists())
    check("gammal fil i backup", (bk / "main.pyw").read_bytes() == b"print('gammal')\n")
    check("backup ligger i appmappen", str(bk).startswith(str(app)))
    check("inga tmp-filer kvar", not list(app.rglob("*.update.tmp")))
    again = updater.check_for_update(app, fake_http(make_zip(REL)))
    check("efter uppdatering: allt aktuellt", again.up_to_date)

    # återställ från backup
    n = updater.restore_backup(app, bk)
    check("restore_backup lägger tillbaka gamla filer", n == 2 and (app / "main.pyw").read_bytes() == b"print('gammal')\n")

# trasig release installeras inte
with tempfile.TemporaryDirectory() as d:
    app = Path(d)
    (app / "main.pyw").write_bytes(b"print('ok')\n")
    bad = make_zip({"main.pyw": b"def (:\n"})
    try:
        updater.check_for_update(app, fake_http(bad))
        check("syntaxfel stoppar uppdateringen", False)
    except UpdateError as e:
        check("syntaxfel stoppar uppdateringen", "main.pyw" in str(e))
    check("trasig release rörde inget", (app / "main.pyw").read_bytes() == b"print('ok')\n")

# zip-slip
with tempfile.TemporaryDirectory() as d:
    evil = make_zip({"../../evil.py": b"x=1\n"})
    try:
        updater.check_for_update(Path(d), fake_http(evil))
        check("zip-slip nekas", False)
    except UpdateError:
        check("zip-slip nekas", True)
    check("inget skrevs utanför", not (Path(d).parent / "evil.py").exists())

# git-mapp uppdateras inte
with tempfile.TemporaryDirectory() as d:
    (Path(d) / ".git").mkdir()
    try:
        updater.check_for_update(Path(d), fake_http(make_zip(REL)))
        check("git-mapp nekas", False)
    except UpdateError as e:
        check("git-mapp nekas", "git" in str(e).lower())

# bara GitHub över https
for bad_url in ("http://api.github.com/x", "https://evil.example.com/x", "file:///etc/passwd"):
    try:
        updater._check_url(bad_url)
        check(f"nekar {bad_url}", False)
    except UpdateError:
        check(f"nekar {bad_url}", True)
check("godkänner codeload", updater._check_url("https://codeload.github.com/a/b/zip") is None)

# rollback vid fel mitt i installationen
with tempfile.TemporaryDirectory() as d:
    app = Path(d)
    (app / "a.txt").write_bytes(b"gammal a")
    info = updater.UpdateInfo(tag="t", files={"a.txt": b"ny a", "sub/b.txt": b"ny b"},
                              changed=["a.txt", "sub/b.txt"])
    real = updater.os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk full")
        return real(src, dst)

    updater.os.replace = flaky
    try:
        updater.apply_update(app, info)
        check("fel under installation ger UpdateError", False)
    except UpdateError:
        check("fel under installation ger UpdateError", True)
    finally:
        updater.os.replace = real
    check("a.txt återställd efter fel", (app / "a.txt").read_bytes() == b"gammal a")
    check("halvskriven ny fil borttagen", not (app / "sub" / "b.txt").exists())

# omstartskommando
cmd = updater.restart_command(ROOT, 3)
check("omstartskommando innehåller main.pyw", "main.pyw" in " ".join(cmd) or "main.py" in " ".join(cmd))

# main.pyw: meny + hanterare
main = (ROOT / "main.pyw").read_text(encoding="utf-8")
check("tray-menyn har Sök ny version", "Sök ny version" in main and "self._check_for_updates" in main)
check("uppdateringen sparar uppgifter först", "self.store.save()" in main.split("def _poll_update_check")[1][:2500])

print(f"\nupdater_test: {ok} lyckades, {fail} misslyckades")
sys.exit(1 if fail else 0)
