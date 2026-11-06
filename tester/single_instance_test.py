"""Test: en körande Ledgebord upptäcks (även äldre kopior) och ingen andra brygga/instans startas."""
import socket
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _src import app_files, app_source  # noqa: E402
sys.path.insert(0, str(ROOT / "core"))

ok = fail = 0


def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("  ✗", name)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


from core.single_instance import probe_taskbord, find_running_taskbord  # noqa: E402
from core.mail_bridge import MailBridgeServer  # noqa: E402
from core.store import TaskStore  # noqa: E402

port = free_port()
check("inget körs först", probe_taskbord(port) is False and find_running_taskbord(port, 3) is None)

with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
    s1 = TaskStore(data_dir_override=d1)
    b1 = MailBridgeServer(s1, Path(d1), port=port, version="t")
    check("första bryggan startar", b1.start())
    check("körande Ledgebord upptäcks", probe_taskbord(port) is True)
    check("find_running hittar porten", find_running_taskbord(port, 3) == port)

    # en andra instans (annan datamapp) får INTE starta en andra brygga på nästa port
    s2 = TaskStore(data_dir_override=d2)
    b2 = MailBridgeServer(s2, Path(d2), port=port, version="t")
    check("andra bryggan startar inte", b2.start() is False)
    check("ingen brygga på nästa port", probe_taskbord(port + 1) is False)
    b1.stop()

# en annan tjänst (inte Ledgebord) på porten räknas inte
import http.server  # noqa: E402
import threading  # noqa: E402


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"app": "SomethingElse"}')

    def log_message(self, *a):
        pass


p2 = free_port()
srv = http.server.HTTPServer(("127.0.0.1", p2), H)
t = threading.Thread(target=srv.serve_forever, daemon=True)
t.start()
check("annan tjänst är inte Ledgebord", probe_taskbord(p2) is False)
srv.shutdown()

main = app_source(ROOT)
check("main.pyw avbryter om Ledgebord redan kör", "find_running_taskbord(8765, 12)" in main and "startar ingen ny instans" in main)

check("bryggan startar alltid vid appstart", "_init_mail_bridge(at_startup=True)" in main and "_http_on = _watch_on = True" in main)
check("brygg-omstart om porten var upptagen", "_retry_mail_bridge_start" in main)

# --- andra start öppnar den som kör (tell_running_instance) ---------------------------------------------------------
from core.single_instance import tell_running_instance  # noqa: E402

calls = []
check("andra start: levereras direkt → True, ett försök", tell_running_instance(notify=lambda k: calls.append(k) or True, sleep=lambda s: None) is True and len(calls) == 1)
t = [0.0]
tries = []
def _late(k):
    tries.append(t[0])
    return t[0] >= 6.0          # den körande appen börjar lyssna först efter 6 s (fönstren byggs)
def _sleep(s):
    t[0] += s
check("andra start: den körande appen är inte klar än → provar om tills den lyssnar (ingen ruta)",
      tell_running_instance(notify=_late, sleep=_sleep, clock=lambda: t[0], total=15, step=0.5) is True and len(tries) == 13)
t[0] = 0.0
check("andra start: ingen lyssnar på 15 s → False (då visas rutan)", tell_running_instance(notify=lambda k: False, sleep=_sleep, clock=lambda: t[0], total=15, step=0.5) is False and t[0] >= 15)
check("andra start: notify som kastar tas om hand", tell_running_instance(notify=lambda k: (_ for _ in ()).throw(OSError("x")), sleep=lambda s: None, clock=iter([0, 99]).__next__, total=1) is False)
calls.clear()
check("fördröjd autostart som kommer efter din egen start: inget SHOW (fönstret hoppar inte fram)", tell_running_instance(autostart=True, notify=lambda k: calls.append(k) or True) is True and not calls)
bsrc = (ROOT / "app" / "bootstrap.py").read_text(encoding="utf-8")
check("bootstrap: alla tre vägarna använder tell_running_instance", bsrc.count("tell_running_instance(") == 3 and ".notify(default_key()" not in bsrc)
check("bootstrap: --autostart skickas vidare", bsrc.count('"--autostart" in sys.argv') == 3)

print(f"\nsingle_instance_test: {ok} lyckades, {fail} misslyckades")
sys.exit(1 if fail else 0)
