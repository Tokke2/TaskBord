# 🧪 tester — TaskBords testverktyg

| Fil | Vad den testar | Kräver |
|---|---|---|
| `../core/mail_bridge.py` (`python core/mail_bridge.py`) | Bryggans självtest: HTTP, token, dedup, extras, inkorgsmapp, JSON-sparning | Inget extra (stdlib) |
| `smoke_main_bridge.py` | Att **main.pyw** kopplar upp bryggan rätt: start, token i `settings.json`, widget-flash, watchdog, tray-togglar, `data/inbox/*.json` → uppgift | Inget extra (körs utan Qt) |
| `mock_test.js` | Hela kedjan **Thunderbird-tillägget → bryggan**: meny-klick, popup, snabbuppgift, taggar, dedup, offline-kö, notiser | Node 18+ (`fetch`) + en körande brygga |

## Kör allt

```bash
# 1. Bryggan (självtest + integration mot main.pyw)
python core/mail_bridge.py
python tester/smoke_main_bridge.py

# 2. Tillägget — starta först en fristående brygga i en egen terminal:
python - <<'PY'
from pathlib import Path
from core.store import TaskStore
from core.mail_bridge import MailBridgeService
data = Path("/tmp/bridge/data")
svc = MailBridgeService(TaskStore(data_dir_override=str(data)), data,
                        port=8770, token="e2etoken1234567890")
svc.start()
print("URL:", svc.url, "token:", svc.token, flush=True)
input("Enter för att stoppa…\n")
svc.stop()
PY

# … och i en annan terminal:
node tester/mock_test.js http://127.0.0.1:8770 e2etoken1234567890
```

`mock_test.js` härmar Thunderbirds `messenger.*`-API i en sandbox, laddar den
**riktiga** `thunderbird-tillagg/background.js` och verifierar 21 punkter.
Alla tester städar efter sig (temporära mappar).
