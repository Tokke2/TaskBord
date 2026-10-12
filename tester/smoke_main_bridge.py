# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
"""
smoke_main_bridge.py — testar main.pyw:s e-postbrygg-integration.

Körs UTAN Qt/Windows (allt tungt är utbytt mot små låtsasobjekt):

    python tester/smoke_main_bridge.py

Verifierar: bryggan startar på 127.0.0.1, token skapas och sparas i
settings.json, notiskön flashar uppgifter i widgeten, watchdog startar om
bryggan, tray-togglarna sparas, samt att en .json-fil i data/inbox blir en
uppgift med prioritet/datum/taggar.
"""
import importlib.util
import json
import sys
import tempfile
import threading
import time
from importlib.machinery import SourceFileLoader
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

loader = SourceFileLoader("taskbord_main", str(ROOT / "main.pyw"))
spec = importlib.util.spec_from_loader("taskbord_main", loader)
main = importlib.util.module_from_spec(spec)
sys.modules["taskbord_main"] = main      # dataclass kräver detta
loader.exec_module(main)
print("✓ main.pyw importerad utan fel (modul-nivå)")

from core.store import TaskStore
from core.settings import Settings

data = Path(tempfile.mkdtemp()) / "data"
data.mkdir(parents=True)
settings = Settings(file_path=str(data / "settings.json"))
store = TaskStore(data_dir_override=str(data))

class FakeSignal:
    def connect(self, *a, **k): pass
class FakeTimer:
    def __init__(self, *a, **k): self.timeout = FakeSignal()
    def setInterval(self, ms): self.ms = ms
    def setSingleShot(self, b): pass
    def start(self, *a): self.running = True
    def stop(self): self.running = False

C = main.AppController

class Fake:
    pass

f = Fake()
f._log = main.logging.getLogger("SmokeTest")
f._mode = main.AppMode.NORMAL
f.settings = settings
f.store = store
f._app = None
f._QTimer = FakeTimer
f._widgets = {}
f._widget_lock = threading.RLock()
f._tray = None
f._QSystemTrayIcon = None
f._SCRIPT_DIR = Path("/tmp")
f._update_tray_tooltip = lambda: None
f._populate_tray_menu = lambda: None
f._QMessageBox = None

# Bind riktiga hjälpmetoder till låtsas-objektet
import types
for _name in ("_mail_bridge_data_dir", "_flash_task_in_widgets",
              "_mail_bridge_notify", "_poll_mail_bridge", "_stop_mail_bridge",
              "_mail_bridge_watchdog", "_toggle_mail_bridge",
              "_toggle_inbox_watch", "_mail_bridge_config_json",
              "_mail_bridge_status_text", "_init_mail_bridge"):
    setattr(f, _name, types.MethodType(getattr(C, _name), f))

# 1. Initiera bryggan
C._init_mail_bridge(f)
assert getattr(f, "_mail_bridge", None) is not None, "bryggan startades inte"
st = f._mail_bridge.status()
print(f"  ✓ _init_mail_bridge: http={st['http_running']} (port {st['port']}), watch={st['watch_running']}")
assert st["http_running"] and st["watch_running"]
assert settings.mail_bridge_token() == f._mail_bridge.token, "token sparades inte i settings"
print(f"  ✓ token sparad i settings.json ({len(settings.mail_bridge_token())} tecken)")

# 2. Inställningar till urklipp/tillägget (JSON)
cfg_json = C._mail_bridge_config_json(f)
cfg = json.loads(cfg_json)
assert cfg["url"].startswith("http://127.0.0.1:") and cfg["token"]
print(f"  ✓ _mail_bridge_config_json: {cfg['url']} token={cfg['token'][:6]}…")

# 3. Simulera import från brygg-tråden -> notiskö -> GUI-poll
f._widget_flash = []
class FakeWidget:
    def _show_task_in_active(self, tid): f._widget_flash.append(tid)
f._widgets = {"default": FakeWidget()}
tid = store.add_task("Uppgift från mail", priority="high")
f._mail_bridge_notify({"source": "bridge",
                       "results": [{"ok": True, "task_id": tid,
                                    "title": "Uppgift från mail", "duplicate": False}]})
before = store.count()[0]
C._poll_mail_bridge(f)
assert f._widget_flash == [tid], f._widget_flash
assert store.count()[0] == before
print(f"  ✓ _mail_bridge_notify + _poll_mail_bridge: uppgift {tid!r} flashades i widgeten")

# 4. Watchdog
f._mail_bridge.server.stop()
time.sleep(0.4)
assert not f._mail_bridge.server.running
C._mail_bridge_watchdog(f)
time.sleep(0.5)
assert f._mail_bridge.server.running, "watchdog startade inte om bryggan"
print("  ✓ _mail_bridge_watchdog återstartade bryggan efter avbrott")

# 5. Toggla av/på
C._toggle_mail_bridge(f, False)
assert not f._mail_bridge.server.running and settings.mail_bridge_enabled() is False
C._toggle_mail_bridge(f, True)
assert f._mail_bridge.server.running and settings.mail_bridge_enabled() is True
print("  ✓ _toggle_mail_bridge: av → på fungerar och sparas i settings")

C._toggle_inbox_watch(f, False)
assert not f._mail_bridge.watch_running and settings.inbox_watch_enabled() is False
C._toggle_inbox_watch(f, True)
assert f._mail_bridge.watch_running and settings.inbox_watch_enabled() is True
print("  ✓ _toggle_inbox_watch: av → på fungerar och sparas i settings")

# 6. Stoppa
C._stop_mail_bridge(f)
assert not f._mail_bridge.http_running and not f._mail_bridge.watch_running
print("  ✓ _stop_mail_bridge stoppade brygga + bevakning")

# 7. Statusrad
print(f"  ✓ tray-statusrad: {C._mail_bridge_status_text(f)}")

# 8. JSON-fil i inkorgen -> automatisk uppgift
C._init_mail_bridge(f)
inbox = f._mail_bridge.paths["inbox"]
(inbox / "fran_tillagg.json").write_text(json.dumps({
    "subject": "Inkorgsfil: boka möte", "from": "Anna <anna@example.com>",
    "note": "Skapad via data/inbox", "priority": "high",
    "due_date": "fredag", "message_id": "<inbox-1@example.com>"},
    ensure_ascii=False), encoding="utf-8")
deadline = time.time() + 15
while time.time() < deadline and not any(
        t["title"] == "Inkorgsfil: boka möte" for t in store.active_tasks()):
    time.sleep(0.4)
assert any(t["title"] == "Inkorgsfil: boka möte" for t in store.active_tasks())
assert list((inbox / "imported").glob("fran_tillagg.json")), "filen flyttades inte"
t = [x for x in store.active_tasks() if x["title"] == "Inkorgsfil: boka möte"][0]
print(f"  ✓ data/inbox/*.json → uppgift (prio={t['priority']}, due={t['due_date']}, taggar={t['tags']})")
C._stop_mail_bridge(f)

print("=" * 62)
print("✓ ALLA SMOKE-TESTER AV main.pyw-INTEGRATIONEN PASSERADE")
print("=" * 62)
