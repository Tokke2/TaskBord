#!/usr/bin/env python3
"""
gcal_easy_connect_test.py — enkel koppling till Google Kalender.

Utan egen Google-installation: finns en medföljande OAuth-klient (core/google_client.json) räcker det att
trycka "Skicka till Google Calendar" → Googles inloggningssida öppnas → logga in + godkänn → uppgiften skickas.

Kör:  python tester/gcal_easy_connect_test.py
"""
from __future__ import annotations

import json
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

CLIENT = {"installed": {
    "client_id": "123-abc.apps.googleusercontent.com", "project_id": "taskbord-test",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token",
    "client_secret": "x", "redirect_uris": ["http://localhost"]}}


def child() -> None:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication

    app = QApplication([])
    import google_calendar_dialog as D
    gcal = D.gcal  # samma modulobjekt som dialogen använder (core.google_calendar)

    res = []

    def ck(name, cond):
        res.append((name, bool(cond)))

    tmp = Path(tempfile.mkdtemp(prefix="taskbord_easy_"))
    bundled = tmp / "google_client.json"
    own_dir = tmp / "data"
    own_dir.mkdir()
    os.environ.pop(gcal.ENV_CREDENTIALS, None)

    # --- upptäckt av medföljande klient ---------------------------------------------------
    gcal.BUNDLED_CLIENT_FILENAME = str(bundled)  # absolut sökväg → Path(...)/abs = abs
    ck("ingen medföljande klient → None", gcal.bundled_client_file() is None)
    ck("ingen klient alls → NOT_CONFIGURED", gcal.get_status(own_dir)["state"] == gcal.ConnectionStatus.NOT_CONFIGURED
       or not gcal.is_google_library_available())
    bundled.write_text(json.dumps(CLIENT), encoding="utf-8")
    ck("medföljande klient hittas", gcal.bundled_client_file() == bundled)
    ck("discover ger medföljande klient", gcal.discover_credentials_file(own_dir) == bundled)
    if gcal.is_google_library_available():
        ck("status: redo att koppla (inte 'saknas')", gcal.get_status(own_dir)["state"] == gcal.ConnectionStatus.DISCONNECTED)
    own = own_dir / "google"
    own.mkdir()
    (own / "credentials.json").write_text(json.dumps(CLIENT), encoding="utf-8")
    ck("egen credentials.json går före den medföljande", gcal.discover_credentials_file(own_dir) == own / "credentials.json")
    (own / "credentials.json").unlink()
    bundled.write_text("{trasig", encoding="utf-8")
    ck("trasig medföljande klient ignoreras", gcal.bundled_client_file() is None)
    bundled.write_text(json.dumps(CLIENT), encoding="utf-8")

    # --- flödet vid "Skicka till Google Calendar" ----------------------------------------
    events: list = []
    shown: list = []

    class FS:
        def __getattr__(self, n):
            return lambda *a, **k: None

    gcal.is_google_library_available = lambda: True
    gcal.is_connected = lambda d, extra_dirs=None: False
    gcal.authenticate_google_calendar = lambda d, **k: events.append(("login", k.get("open_browser"))) or {"ok": True}
    gcal.build_calendar_service = lambda d: events.append("service") or object()
    gcal.push_task = lambda *a, **k: events.append("push") or {"ok": False, "action": "fel", "message": "test"}
    gcal.load_event_map = lambda d: {}
    gcal.load_history = lambda d: []
    D._visa_info = lambda parent, title, text: shown.append((title, text))

    def run_sync(parent, titel, fn, beskrivning="", on_done=None, on_error=None):
        r = fn(lambda t: None)
        if on_done:
            on_done(r)
        return True

    D.run_google_job = run_sync
    task = {"id": "1", "title": "Testa kopplingen", "due_date": "2026-12-01"}

    D.push_task_with_dialog(None, task=task, store=None, settings=FS(), data_dir=own_dir)
    ck("inloggning startas (webbläsaren öppnas) innan uppgiften skickas",
       events[:1] == [("login", True)] and events[1:] == ["service", "push"])

    events.clear()
    D.push_task_with_dialog(None, task={"id": "2", "title": "Utan datum"}, store=None, settings=FS(), data_dir=own_dir)
    ck("uppgift utan datum: ingen inloggning", events == [] and any("Datum" in t for t, _ in shown))

    # redan kopplad → ingen ny inloggning
    gcal.is_connected = lambda d, extra_dirs=None: True
    events.clear()
    D.push_task_with_dialog(None, task=task, store=None, settings=FS(), data_dir=own_dir)
    ck("redan kopplad: ingen ny inloggning", events == ["service", "push"])

    # ingen klient alls → guiden öppnas i stället för en död ände
    gcal.is_connected = lambda d, extra_dirs=None: False
    bundled.unlink()
    wiz: list = []

    class FakeWizard:
        vill_koppla = False
        def __init__(self, data, parent=None, start_key=None): wiz.append(data)
        def exec(self): return 0

    D.GoogleSetupWizard = FakeWizard
    events.clear()
    D.push_task_with_dialog(None, task=task, store=None, settings=FS(), data_dir=own_dir)
    ck("ingen klient: guiden öppnas, ingen inloggning", wiz == [own_dir] and events == [])

    bad = [n for n, ok in res if not ok]
    print("CHILD", len(res) - len(bad), len(bad), flush=True)
    for n in bad:
        print("  ✗", n, flush=True)
    shutil.rmtree(tmp, ignore_errors=True)
    os._exit(0)


if "--child" in sys.argv:
    child()
else:
    from _qtenv import qt_env

    work = Path(tempfile.mkdtemp(prefix="taskbord_easytest_"))
    env, why = qt_env(work)
    if env is None:
        print(f"gcal_easy_connect_test: hoppas över ({why})")
        sys.exit(0)
    r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--child"], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=120)
    line = [l for l in r.stdout.splitlines() if l.startswith("CHILD ")]
    if line:
        _, a, b = line[-1].split()
        a, b = int(a), int(b)
        for l in r.stdout.splitlines():
            if l.strip().startswith("✗"):
                print(l)
    else:
        a, b = 0, 1
        print("  ✗ barnprocessen körde klart", (r.stdout + r.stderr)[-1500:])
    shutil.rmtree(work, ignore_errors=True)
    print(f"\ngcal_easy_connect_test: {a} lyckades, {b} misslyckades")
    sys.exit(1 if b else 0)
