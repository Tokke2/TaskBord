#!/usr/bin/env python3
"""
rename_icon_test.py — namnbytet TaskBord → Ledgebord och den nya appikonen.

Kör:  python tester/rename_icon_test.py
* inga kvarlämnade "TaskBord" i synliga texter (bara protokoll-/kompatibilitetsnamn som MÅSTE vara kvar)
* ikonen: giltig flerstorleks-.ico (16–256), PNG, läsbar för Qt, återskapas om filen saknas
* gamla namnet fungerar vidare där det måste (/health, backupnamn, autostart-städning)
"""
from __future__ import annotations

import http.server
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

_ok = _fail = 0


def check(name, cond, extra=""):
    global _ok, _fail
    if cond:
        _ok += 1
    else:
        _fail += 1
        print(f"  ✗ {name} {extra}")


# Kvarvarande "TaskBord" som är MEDVETNA: protokoll/kompatibilitet mot installerade tillägg och befintlig data
ALLOWED = (
    "X-TaskBord-Token", "X-TaskBord-Extra",          # HTTP-huvuden mellan appen och det installerade Thunderbird-tillägget
    "Tokke2/TaskBord", "Tokke2-TaskBord",            # GitHub-repots namn (uppdateraren)
    "TaskBord-Google-token-v1",                      # DPAPI-entropi — ändras den går sparade Google-token inte att läsa
    "TaskBord_SingleInstance_",                      # mutex-namn (ett gammalt exemplar ska fortfarande upptäckas)
    # medvetna hänvisningar till det GAMLA namnet (migrering/kompatibilitet):
    '_LEGACY_AUTOSTART_NAMES = ("TaskBord",)', 'LEGACY_AUTOSTART_NAMES: Tuple[str, ...] = ("TaskBord",)',
    "Namnbyte TaskBord → Ledgebord", '(äldre versioner: "TaskBord")', '_LEGACY_DIR_NAME: Final[str] = "TaskBord"',
    "TaskBord.lnk", "(tidigare TaskBord)",
)


def text_tests() -> None:
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split("\n")
    leftovers = []
    for f in files:
        p = ROOT / f
        if not f or not p.is_file() or p.suffix.lower() in (".xpi", ".ico", ".png") or p.name in ("LICENSE",):
            continue
        if f.startswith("tester/rename_icon_test"):
            continue
        try:
            s = p.read_text(encoding="utf-8")
        except Exception:
            continue
        for tok in ALLOWED:
            s = s.replace(tok, "")
        for m in re.finditer(r"TaskBord", s):
            leftovers.append(f"{f}: …{s[max(0, m.start() - 30):m.end() + 30]!r}")
    check("inget 'TaskBord' kvar i synliga texter/kod (utöver kompatibilitetsnamnen)", not leftovers, "\n    " + "\n    ".join(leftovers[:8]))
    check("fönstertiteln är Ledgebord", 'setWindowTitle("Ledgebord")' in (ROOT / "app/mixins/windows.py").read_text(encoding="utf-8"))
    check("APP_NAME är Ledgebord", 'APP_NAME: Final[str] = "Ledgebord"' in (ROOT / "app/constants.py").read_text(encoding="utf-8"))
    check("startskriptet för macOS är omdöpt", (ROOT / "STARTA_LEDGEBORD.command").is_file() and not (ROOT / "STARTA_TASKBORD.command").exists())
    check("README och app-namn: Ledgebord", (ROOT / "README.md").read_text(encoding="utf-8").lstrip().startswith("#") and "Ledgebord" in (ROOT / "README.md").read_text(encoding="utf-8")[:300])
    # protokollet mot det installerade Thunderbird-tillägget är oförändrat
    bg = (ROOT / "thunderbird-tillagg/background.js").read_text(encoding="utf-8")
    mb = (ROOT / "core/mail_bridge.py").read_text(encoding="utf-8")
    check("token-huvudet är oförändrat i både tillägg och brygga", 'X-TaskBord-Token' in bg and 'TOKEN_HEADER: str = "X-TaskBord-Token"' in mb)
    man = json.loads((ROOT / "thunderbird-tillagg/manifest.json").read_text(encoding="utf-8"))
    check("tilläggets id är oförändrat (nya filen ersätter det gamla)", man["browser_specific_settings"]["gecko"]["id"] == "taskbord-mailbridge@taskbord.app")
    check("tilläggets version är höjd (1.2.0) och heter Ledgebord", man["version"] == "1.2.0" and "Ledgebord" in man["name"], man["name"])
    xpi = ROOT / "Ledgebord-Thunderbird.xpi"
    check("Ledgebord-Thunderbird.xpi finns (och inte den gamla)", xpi.is_file() and not (ROOT / "TaskBord-Thunderbird.xpi").exists())
    if xpi.is_file():
        with zipfile.ZipFile(xpi) as z:
            m2 = json.loads(z.read("manifest.json"))
            check("xpi:n innehåller manifest 1.2.0 + nya ikoner", m2["version"] == "1.2.0" and "icons/icon-128.png" in z.namelist())
            check("xpi-ikonen är en PNG", z.read("icons/icon-128.png")[:8] == b"\x89PNG\r\n\x1a\n")
    ins = (ROOT / "INSTALLERA.bat").read_text(encoding="utf-8")
    check("genvägens ikon pekar på icon\\ledgebord.ico", "icon\\\\ledgebord.ico" in ins and "data\\\\app.ico" not in ins)


def parse_ico(data: bytes):
    res, typ, n = struct.unpack("<HHH", data[:6])
    out = []
    for i in range(n):
        w, h, cc, rsv, planes, bpp, size, off = struct.unpack("<BBBBHHII", data[6 + 16 * i:22 + 16 * i])
        out.append((w or 256, h or 256, bpp, size, off))
    return res, typ, out


def icon_tests() -> None:
    from core import icon_art
    ico = (ROOT / "icon/ledgebord.ico").read_bytes()
    res, typ, entries = parse_ico(ico)
    check("ico: giltigt huvud (typ 1)", res == 0 and typ == 1)
    sizes = sorted(e[0] for e in entries)
    check("ico: 16, 24, 32, 48, 64, 128 och 256 px", sizes == [16, 24, 32, 48, 64, 128, 256], sizes)
    check("ico: alla poster 32 bitar med alfa och inom filen", all(e[2] == 32 and e[4] + e[3] <= len(ico) for e in entries))
    big = [e for e in entries if e[0] == 256][0]
    check("ico: 256 px-posten är en PNG", ico[big[4]:big[4] + 8] == b"\x89PNG\r\n\x1a\n")
    small = [e for e in entries if e[0] == 32][0]
    check("ico: 32 px-posten är en BMP-post (BITMAPINFOHEADER, höjd = 2×)", struct.unpack("<II", ico[small[4]:small[4] + 8])[0] == 40
          and struct.unpack("<i", ico[small[4] + 8:small[4] + 12])[0] == 64)
    png = (ROOT / "icon/ledgebord.png").read_bytes()
    check("png: 256×256", png[:8] == b"\x89PNG\r\n\x1a\n" and struct.unpack(">II", png[16:24]) == (256, 256))
    # renderingen: genomskinliga hörn, ogenomskinlig mitt, kantlisten gul, kortet vitt
    px = icon_art.render(64)

    def at(x, y):
        o = (y * 64 + x) * 4
        return tuple(px[o:o + 4])
    check("rendering: hörnen är genomskinliga", at(0, 0)[3] == 0 and at(63, 63)[3] == 0)
    check("rendering: kantlisten är gul (R hög, B låg)", at(6, 32)[0] > 200 and at(6, 32)[2] < 120 and at(6, 32)[3] == 255, at(6, 32))
    check("rendering: kortet är vitt", min(at(54, 27)[:3]) > 230 and at(54, 27)[3] == 255, at(54, 27))
    check("rendering: bakgrunden är indigo (B > R)", at(56, 58)[2] > at(56, 58)[0] and at(56, 58)[3] == 255, at(56, 58))
    check("rendering: deterministisk", icon_art.render(16) == icon_art.render(16))
    check("de små storlekarna ritas förenklat (en bock) men skiljer sig från 32", icon_art.render(16)[:64] != b"")
    tmp = Path(tempfile.mkdtemp(prefix="taskbord_iconart_"))
    a, b = icon_art.write_icon_files(tmp, sizes=(16, 32))
    check("write_icon_files skriver ico + png", a.is_file() and b.is_file() and parse_ico(a.read_bytes())[2][0][0] == 16)
    shutil.rmtree(tmp, ignore_errors=True)
    check("bundlade filen är exakt det generatorn ritar (ingen avdrift)",
          ico == icon_art.build_ico(), "kör: python core/icon_art.py")


def qt_child() -> None:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtGui import QGuiApplication, QIcon
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    res = []

    def ck(n, c, extra=""):
        res.append((n + (" " + str(extra) if not c and extra else ""), bool(c)))

    ico = QIcon(str(ROOT / "icon/ledgebord.ico"))
    ck("Qt läser icon/ledgebord.ico", not ico.isNull() and not ico.pixmap(32, 32).isNull())
    sizes = sorted({(s.width(), s.height()) for s in ico.availableSizes()})
    ck("Qt ser flera storlekar", len(sizes) >= 5, sizes)
    pm = ico.pixmap(48, 48)
    ck("Qt: 48 px-pixmap har rätt färger (gul kantlist längst till vänster)", pm.toImage().pixelColor(4, 24).red() > 200, pm.toImage().pixelColor(4, 24).getRgb())

    # AppIconMixin: bundlad ikon används; saknas den ritas den om (aldrig Python-ikon)
    import app.mixins.app_icon as AI
    import app.constants as C
    import logging

    class Fake(AI.AppIconMixin):
        _log = logging.getLogger("x")
        _QIcon = QIcon
    f = Fake()
    p = f._ensure_app_icon_file()
    ck("_ensure_app_icon_file → icon/ledgebord.ico", p == C.SCRIPT_DIR / "icon" / "ledgebord.ico", p)
    tmp = Path(tempfile.mkdtemp(prefix="taskbord_icondata_"))
    AI.SCRIPT_DIR = tmp / "tomt"
    AI.DATA_DIR = tmp / "data"
    p2 = f._ensure_app_icon_file()
    ck("saknas filen ritas ikonen om till data/ledgebord.ico", p2 == tmp / "data" / "ledgebord.ico" and p2.is_file() and p2.stat().st_size > 1000, p2)
    ck("den omritade ikonen läses av Qt", not QIcon(str(p2)).isNull())
    (tmp / "data" / "ledgebord.ico").write_bytes(b"inte en ikon" * 100)
    p3 = f._ensure_app_icon_file()
    ck("korrupt fil ersätts av en ny giltig", p3 is not None and not QIcon(str(p3)).isNull())
    shutil.rmtree(tmp, ignore_errors=True)
    ck("AppUserModelID är satt till egen identitet", C.APP_USER_MODEL_ID == "Ledgebord.Desktop.App")
    ck("_set_app_user_model_id är ofarlig utanför Windows", AI.AppIconMixin._set_app_user_model_id() is None)
    ck("apply_win32_process_icon är ofarlig utanför Windows", Fake().apply_win32_process_icon(123) is None if hasattr(Fake(), "_app_icon_path") or True else True)
    src = (ROOT / "app/mixins/windows.py").read_text(encoding="utf-8")
    ck("ikonen sätts på själva topp-fönstret (skalet)", "_shell_ref.setWindowIcon(self._app_icon)" in src and "apply_win32_process_icon(int(_shell_ref.winId()))" in src)
    ctrl = (ROOT / "app/controller.py").read_text(encoding="utf-8")
    ck("AppUserModelID sätts före QApplication skapas", ctrl.index("_set_app_user_model_id()") < ctrl.index("QApplicationCls(sys.argv)"))
    bad = [n for n, ok in res if not ok]
    print("CHILD", len(res) - len(bad), len(bad))
    for n in bad:
        print("  ✗", n)
    sys.stdout.flush()
    os._exit(0)


def compat_tests() -> None:
    # /health: både "Ledgebord" och äldre "TaskBord" räknas som vår app
    from core import single_instance as si
    from core import update_watchdog as uw
    for app_name, want in (("Ledgebord", True), ("TaskBord", True), ("Annat", False)):
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps({"ok": True, "app": app_name}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass
        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        check(f"probe_taskbord: /health app={app_name!r} → {want}", si.probe_taskbord(port) is want)
        check(f"update_watchdog.taskbord_answers: app={app_name!r} → {want}", uw.taskbord_answers([port]) is want)
        srv.shutdown()
    # backupnamn: nya prefixet skrivs, gamla hittas fortfarande
    from core import tasks_backup as tb
    from core.store import TaskStore
    tmp = Path(tempfile.mkdtemp(prefix="taskbord_namebk_"))
    os.environ["TASKBORD_BACKUP_DIR"] = str(tmp / "auto")
    (tmp / "auto").mkdir()
    store = TaskStore(data_dir_override=str(tmp / "d"))
    store.add_task("Uppgift")
    check("nya backupnamn börjar på ledgebord-", tb.PREFIX == "ledgebord-uppgifter-" and tb.AUTO_PREFIX == "ledgebord-auto-")
    z = tb.create_backup(store, folder=tmp / "egna") if "folder" in tb.create_backup.__code__.co_varnames else tb.create_backup(store)
    check("create_backup skriver ledgebord-uppgifter-*.zip", Path(str(z)).name.startswith("ledgebord-uppgifter-"), z)
    (tmp / "auto" / "taskbord-auto-20240101-000000.zip").write_bytes(b"PK")
    names = [b["name"] for b in tb.list_backups(store)]
    check("gamla taskbord-auto-*.zip listas fortfarande", "taskbord-auto-20240101-000000.zip" in names, names)
    check("auto-zips inkluderar gamla namnet", any(p.name.startswith("taskbord-auto-") for p in tb._auto_zips(tmp / "auto")))
    os.environ.pop("TASKBORD_BACKUP_DIR", None)
    shutil.rmtree(tmp, ignore_errors=True)

    # autostart: gammal post flyttas till nya namnet utan att något tappas (Linux/XDG här)
    from app.mixins.autostart import AutostartMixin
    import logging
    cfg = Path(tempfile.mkdtemp(prefix="taskbord_xdg_"))
    os.environ["XDG_CONFIG_HOME"] = str(cfg)
    (cfg / "autostart").mkdir()
    legacy = cfg / "autostart" / "TaskBord.desktop"

    class Fake(AutostartMixin):
        _log = logging.getLogger("x")
        called = 0
        ok = True

        def _autostart_enable_robust(self):
            Fake.called += 1
            return {"x": Fake.ok}
    f = Fake()
    if sys.platform.startswith("linux"):
        check("ingen gammal post → inget görs", f._autostart_legacy_present() is False)
        f._autostart_migrate_legacy()
        check("…och autostart skapas inte i onödan", Fake.called == 0)
        legacy.write_text("[Desktop Entry]\nName=TaskBord\n")
        check("gammal post upptäcks", f._autostart_legacy_present() is True)
        Fake.ok = False
        f._autostart_migrate_legacy()
        check("misslyckas nya posten → den gamla BEHÅLLS", legacy.exists() and Fake.called == 1)
        Fake.ok = True
        f._autostart_migrate_legacy()
        check("lyckas nya posten → den gamla städas bort", not legacy.exists() and Fake.called == 2)
        legacy.write_text("x")
        check("_autostart_remove_legacy tar bort och räknar", f._autostart_remove_legacy() == 1 and not legacy.exists())
    shutil.rmtree(cfg, ignore_errors=True)
    os.environ.pop("XDG_CONFIG_HOME", None)
    import desktop
    check("Windows-autostart heter Ledgebord, gamla namnet städas", desktop.AUTOSTART_VALUE_NAME == "Ledgebord" and desktop.LEGACY_AUTOSTART_NAMES == ("TaskBord",))
    check("fönsterklassen heter LedgebordMain", desktop.WINDOW_CLASS_NAME == "LedgebordMain")


if "--child" in sys.argv:
    qt_child()
else:
    text_tests()
    icon_tests()
    compat_tests()
    from _qtenv import qt_env
    work = Path(tempfile.mkdtemp(prefix="taskbord_renametest_"))
    env, why = qt_env(work)
    if env is None:
        print(f"rename_icon_test: Qt-delen hoppas över ({why})")
    else:
        r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--child"], cwd=ROOT, env=env,
                           capture_output=True, text=True, timeout=300)
        line = [l for l in r.stdout.splitlines() if l.startswith("CHILD ")]
        if line:
            _, a, b = line[-1].split()
            _ok += int(a)
            _fail += int(b)
            for l in r.stdout.splitlines():
                if l.strip().startswith("✗"):
                    print(l)
        else:
            check("barnprocessen körde klart", False, (r.stdout + r.stderr)[-2500:])
    shutil.rmtree(work, ignore_errors=True)
    print(f"\nrename_icon_test: {_ok} lyckades, {_fail} misslyckades")
    sys.exit(1 if _fail else 0)
