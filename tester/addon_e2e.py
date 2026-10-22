"""
addon_e2e.py — kör tester/mock_test.js (Thunderbird-tillägget mot en MOCKAD Thunderbird) mot en
RIKTIG Ledgebord-brygga som startas här. Kräver Node 18+. Hoppas över (exit 0) om node saknas.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "core")]

node = shutil.which("node")
if not node:
    print("  (hoppar över addon_e2e: node saknas)\n\naddon_e2e: 0 lyckades, 0 misslyckades (överhoppad)")
    sys.exit(0)

from core.store import TaskStore  # noqa: E402
from core.mail_bridge import MailBridgeService  # noqa: E402

PORT, TOKEN = 8770, "e2etoken1234567890"
data = Path("/tmp/bridge_e2e/data")
shutil.rmtree(data.parent, ignore_errors=True)
data.mkdir(parents=True)
svc = MailBridgeService(TaskStore(data_dir_override=str(data)), data, port=PORT, token=TOKEN)
svc.start()
time.sleep(0.5)
try:
    r = subprocess.run([node, str(ROOT / "tester" / "mock_test.js"), f"http://127.0.0.1:{PORT}", TOKEN],
                       capture_output=True, text=True, timeout=180)
finally:
    svc.stop()
out = r.stdout
for line in out.splitlines():
    if "✗" in line :
        print(line)
n_ok = out.count("  ✓")
n_fail = out.count("  ✗")
if r.returncode != 0 and not n_fail:
    print(r.stdout[-800:], r.stderr[-800:])
    n_fail = 1
import os
if not os.environ.get("KEEP"):
    shutil.rmtree(data.parent, ignore_errors=True)
print(f"\naddon_e2e: {n_ok} lyckades, {n_fail} misslyckades")
sys.exit(1 if n_fail else 0)
