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

print(f"\nsingle_instance_test: {ok} lyckades, {fail} misslyckades")
sys.exit(1 if fail else 0)
