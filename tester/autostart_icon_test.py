"""Test: autostart som Startup-genväg med Ledgebords egen ikon (inte pythonw via registret/.bat → Pythons ikon).

Windows kan inte köras i sandboxen: PowerShell-anropet ersätts av en låtsasfunktion som skriver .lnk-filen
och sparar de miljövariabler som skulle skickats (mål, argument, ikon, arbetsmapp)."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "core"))

ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("  ✗", name, extra)


from core import autostart_lnk as al  # noqa: E402
import desktop  # noqa: E402

calls = []
fail_next = {"v": False}


def fake_run(cmd, **kw):
    env = kw.get("env", {})
    calls.append({"cmd": cmd, "env": {k: v for k, v in env.items() if k.startswith("LB_")}, "kw": kw})

    class R:
        returncode = 0 if not fail_next["v"] else 1
        stderr = b"fel"
        stdout = b""
    if not fail_next["v"]:
        Path(env["LB_LNK"]).write_bytes(b"LNK")
    return R()


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    appdata = tmp / "Roaming"
    app = tmp / "Program Files åäö" / "Ledgebord"
    (app / "icon").mkdir(parents=True)
    (app / "icon" / "ledgebord.ico").write_bytes(b"\0" * 2000)
    (app / "main.pyw").write_text("pass")
    os.environ["APPDATA"] = str(appdata)
    al.is_windows = lambda: True
    al.subprocess.run = fake_run
    PY = r"C:\Users\rl\AppData\Local\Programs\Python\Python314\pythonw.exe"
    CMD = f'"{PY}" "{app / "main.pyw"}"'
    startup = al.startup_dir()
    lnk = al.shortcut_path()

    # --- hjälpare
    check("split_command: exe + argument", al.split_command('"C:\\a b\\pythonw.exe" "D:\\x y\\main.pyw" --autostart')
          == ("C:\\a b\\pythonw.exe", '"D:\\x y\\main.pyw" --autostart'))
    check("with_autostart_flag lägger till flaggan en gång", al.with_autostart_flag(CMD).endswith(" --autostart")
          and al.with_autostart_flag(al.with_autostart_flag(CMD)).count("--autostart") == 1)
    check("icon_file hittar icon/ledgebord.ico", al.icon_file(app) == app / "icon" / "ledgebord.ico")
    check("icon_file: None när ingen ikon finns", al.icon_file(tmp / "tom") is None)

    # --- gamla poster finns sedan förut (registret kan inte testas här, .bat kan)
    startup.mkdir(parents=True)
    (startup / "Ledgebord.bat").write_text("start pythonw")
    check("gammal .bat upptäcks", al.old_entries_present())

    # --- install
    check("install lyckas", al.install(CMD, app))
    c = calls[-1]
    check("genvägen ligger i Startup-mappen som Ledgebord.lnk", lnk.is_file() and lnk.parent == startup and lnk.name == "Ledgebord.lnk")
    check("målet är pythonw.exe", c["env"]["LB_TARGET"] == PY, c["env"])
    check("argument: main.pyw + --autostart", c["env"]["LB_ARGS"] == f'"{app / "main.pyw"}" --autostart', c["env"]["LB_ARGS"])
    check("ikonen är Ledgebords ikon", c["env"]["LB_ICON"] == str(app / "icon" / "ledgebord.ico"), c["env"]["LB_ICON"])
    check("arbetsmappen är appmappen (åäö + mellanslag)", c["env"]["LB_WORKDIR"] == str(app))
    check("PowerShell körs utan fönster", c["kw"].get("creationflags", 0) == getattr(__import__("subprocess"), "CREATE_NO_WINDOW", 0))
    check("värden skickas via miljövariabler, inte i skriptet", PY not in " ".join(c["cmd"]) and "LB_ICON" in " ".join(c["cmd"]))
    check("gamla .bat togs bort", not (startup / "Ledgebord.bat").exists())
    check("markeringsfilen skrevs i APPMAPPEN", al.marker_path(app).is_file() and str(al.marker_path(app)).startswith(str(app)))
    check("is_current efter install", al.is_current(CMD, app))
    check("is_current False om Python byts", not al.is_current(CMD.replace("Python314", "Python315"), app))
    check("is_current False om appen flyttas", not al.is_current(CMD, tmp))
    lnk.unlink()
    check("is_current False om genvägen saknas", not al.is_current(CMD, app))
    check("exists False", not al.exists())

    # --- misslyckad PowerShell: inget förstörs
    (startup / "Ledgebord.bat").write_text("start pythonw")
    fail_next["v"] = True
    check("install → False när genvägen inte skapas", not al.install(CMD, app))
    check("…och den gamla .bat står kvar som reserv", (startup / "Ledgebord.bat").exists())
    fail_next["v"] = False

    # --- remove
    al.install(CMD, app)
    n = al.remove(app)
    check("remove tar bort genväg + markering", n >= 1 and not lnk.exists() and not al.marker_path(app).exists())

    # --- genväg i appmappen
    calls.clear()
    check("ensure_folder_shortcut skapar Ledgebord.lnk i appmappen", al.ensure_folder_shortcut(PY, app) and (app / "Ledgebord.lnk").is_file())
    check("…med ikon och arbetsmapp", calls[-1]["env"]["LB_ICON"].endswith("ledgebord.ico") and calls[-1]["env"]["LB_WORKDIR"] == str(app))
    n0 = len(calls)
    al.ensure_folder_shortcut(PY, app)
    check("…och skrivs inte om i onödan", len(calls) == n0)
    check("ensure_folder_shortcut utan main.pyw → False", not al.ensure_folder_shortcut(PY, tmp / "tom"))

    # --- desktop-motorn (settings.set_autostart → desktop.enable_autostart)
    desktop.IS_WINDOWS = True
    calls.clear()
    check("desktop.enable_autostart_windows använder genvägen", desktop.enable_autostart_windows(PY, f'"{app / "main.pyw"}"'))
    check("…med --autostart", calls and calls[-1]["env"]["LB_ARGS"].endswith("--autostart"), calls[-1]["env"] if calls else None)
    check("desktop: är aktiverat när genvägen finns", desktop._is_autostart_enabled_windows())
    check("desktop: get_autostart_command visar pythonw + skript", (desktop.get_autostart_command() or "").startswith(f'"{PY}"'))
    desktop.disable_autostart_startup()
    check("desktop.disable_autostart_startup tar bort genvägen", not lnk.exists())
    check("desktop: inte aktiverat utan genväg/registret", not desktop._is_autostart_enabled_windows())
    fail_next["v"] = True
    desktop.enable_autostart_windows(PY, f'"{app / "main.pyw"}"')
    check("desktop: reserv (.bat) när genvägen inte går", (startup / "Ledgebord.bat").is_file())
    fail_next["v"] = False
    (startup / "Ledgebord.bat").unlink(missing_ok=True)

    # --- appens AutostartMixin (win32 simulerad)
    import app.mixins.autostart as am  # noqa: E402
    from app.mixins.autostart import AutostartMixin  # noqa: E402
    import logging

    class Settings:
        def is_autostart_enabled(self):
            return True

    class S(AutostartMixin):
        _log = logging.getLogger("t")
        settings = Settings()

    am.SCRIPT_DIR = app
    s = S()
    s._autostart_build_command = lambda: CMD
    real_platform = sys.platform
    sys.platform = "win32"
    try:
        calls.clear()
        res = s._autostart_enable_robust()
        check("mixin: aktivering ger genväg med appens ikon", res == {"startup-genväg (appens ikon)": True} and lnk.is_file(), res)
        check("mixin: ingen registerpost/.bat skapas", not (startup / "Ledgebord.bat").exists())
        n0 = len(calls)
        s._autostart_shortcuts_heal(True)
        check("mixin heal: oförändrad genväg skrivs inte om", len(calls) == n0)
        (startup / "Ledgebord.bat").write_text("start pythonw")
        s._autostart_shortcuts_heal(True)
        check("mixin heal: gammal .bat städas bort", not (startup / "Ledgebord.bat").exists())
        s._autostart_build_command = lambda: CMD.replace("Python314", "Python315")
        s._autostart_shortcuts_heal(True)
        check("mixin heal: Python bytt → genvägen skrivs om", calls[-1]["env"]["LB_TARGET"].endswith(r"Python315\pythonw.exe"), calls[-1]["env"])
        s._autostart_build_command = lambda: CMD
        lnk.unlink()
        s._autostart_shortcuts_heal(False)
        check("mixin heal: autostart AV → ingen Startup-genväg skapas", not lnk.exists())
        check("mixin heal: …men genvägen i appmappen finns", (app / "Ledgebord.lnk").is_file())
        # reserv
        fail_next["v"] = True
        res = s._autostart_enable_robust()
        check("mixin: reserv när genvägen misslyckas (Startup-.bat)", res.get("startup-mapp") is True and (startup / "Ledgebord.bat").is_file(), res)
        fail_next["v"] = False
        s._autostart_enable_robust()
        removed = s._autostart_disable_all()
        check("mixin: avaktivering tar bort genvägen", removed >= 1 and not lnk.exists())
    finally:
        sys.platform = real_platform

# källkontroll
src = (ROOT / "app" / "mixins" / "autostart.py").read_text(encoding="utf-8")
check("health check startar genväg-reparationen i bakgrundstråd", "threading.Thread(target=self._autostart_shortcuts_heal" in src)
check("INSTALLERA.bat använder fortfarande ikon på skrivbordsgenvägen", b"IconLocation" in (ROOT / "INSTALLERA.bat").read_bytes())
check(".gitignore tar med den lokala Ledgebord.lnk", "/Ledgebord.lnk" in (ROOT / ".gitignore").read_text(encoding="utf-8"))

print(f"\nautostart_icon_test: {ok} lyckades, {fail} misslyckades")
sys.exit(1 if fail else 0)
