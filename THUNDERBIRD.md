# 📧 Ledgebord + Thunderbird — importera mail som uppgifter

**Svar på frågan:** *Ja, man kan göra ett tillägg till Thunderbird som
importerar uppgifter till appen* — och uppgifterna sparas i JSON-fil
(`data/active.json`) så att de **finns kvar efter omstart**.

Den här filen beskriver hela kedjan: Thunderbird-tillägget, appens
e-postbrygga, inkorgsmappen och var allt sparas.

---

## 1. Så funkar det (översikt)

```
   THUNDERBIRD                              TASKBORD (appen)
┌───────────────────────┐            ┌──────────────────────────────┐
│ Högerklicka på mail   │            │  E-postbrygga (localhost)    │
│  📋 Skicka till       │  HTTP      │  http://127.0.0.1:8765       │
│     Ledgebord          │ ─────────► │  POST /eml  (originalmail)   │
│  eller knappen 📋 i   │  token     │  POST /task (JSON)           │
│  meddelandefönstret   │            │            │                 │
└───────────────────────┘            │            ▼                 │
                                     │  Uppgift skapas + SPARAS     │
   data/inbox/  (mapp)               │  i JSON direkt:              │
   släpp .eml/.msg/.json ──────────► │    data/active.json          │
                                     │    data/email…/imported.json │
                                     └──────────────────────────────┘
```

Det finns **tre vägar in** — alla landar i samma kod, samma dedup och samma
JSON-lagring:

| Väg | Kräver att appen körs | Används för |
|---|---|---|
| **1. Thunderbird-tillägget** (HTTP till bryggan) | Ja | Snabbast: högerklick → uppgift |
| **2. Inkorgsmappen** `data/inbox/` | Nej (import sker vid start) | Mail du sparar när appen är avstängd |
| **3. 📧-knappen i widgeten / tray-menyn** | Ja | Vanliga `.eml`/`.msg`-filer från disken |

Om appen inte körs när du klickar i tillägget läggs mailet i tilläggets
**kö** och skickas automatiskt så fort Ledgebord startar — inget tappas.

---

## 2. Snabbstart (3 steg)

### Steg 1 — Starta Ledgebord
Bryggan startar automatiskt med appen. Kontrollera i tray-menyn:

> 📧 E-post & Thunderbird → **Brygga (lokal server)** ✅ och
> **Bevaka inkorgsmappen** ✅

### Steg 2 — Installera Thunderbird-tillägget
1. Kör `SKAPA_XPI.bat` i appmappen (skapar `Ledgebord-Thunderbird.xpi`).
2. I Thunderbird: **Verktyg → Tillägg och teman**.
3. Klicka **kugghjulet ⚙️ → Installera tillägg från fil…**
4. Välj `Ledgebord-Thunderbird.xpi` och godkänn.

### Steg 3 — Koppla ihop dem (token)
1. I Ledgebord: tray-menyn → **📧 E-post & Thunderbird →
   📋 Kopiera inställningar för Thunderbird…**
   (adress + hemlig token läggs på urklipp, en ruta visar dem)
2. I Thunderbird: **Tillägg och teman → Ledgebord → Inställningar**
3. Klistra in i fältet **Klistra in JSON** → **📥 Läs in och spara**
   → knappen **🔌 Testa anslutning** ska visa *✅ Ansluten*.

Klart! Högerklicka på ett mail → **📋 Skicka till Ledgebord (ny uppgift)**.

---

## 3. Så använder du tillägget

| Sätt | Vad som händer |
|---|---|
| **Högerklicka på mail** i listan → 📋 Skicka till Ledgebord | Uppgift skapas direkt (ämne = titel, avsändare = tagg) |
| **Markera flera mail** → högerklicka → 📋 Skicka till Ledgebord | En uppgift per mail (max 100), ETT sammanfattande meddelande; redan importerade hoppas över; är Ledgebord avstängt köas alla |
| **📋-knappen i meddelandefönstret** (message display action) | Popup: välj **prioritet**, **förfallodatum** (`imorgon`, `fredag`, `2026-10-20`) och **taggar** |
| **📋-knappen i huvudfönstrets verktygsfält** | Popup med det visade mailet + fältet *Skapa uppgift direkt* |
| **Popupens snabbuppgift** | Skapa uppgift utan mail (text + anteckning) |

Detaljer:
* **Prioritet** gissas automatiskt från ämne/brödtext om du väljer *Auto*
  (t.ex. ”brådskande”, ”ASAP”, ”viktigt” → hög; ”senare”, ”ingen brådska” → låg).
* **Thunderbirds taggar** blir taggar i Ledgebord (system-taggar som `$label1`
  hoppas över).
* **Brödtexten** sparas som anteckning på uppgiften (`email_body`).
* **Originalmailet** (`.eml`) sparas i `data/emails/<uppgift-id>.eml` och
  öppnas från uppgiftskortets 📧-ikon.
* **Dubletter**: samma mail importeras aldrig två gånger (Message-ID).
  Väljer du ändå prioritet/datum på ett redan importerat mail **uppdateras
  den befintliga uppgiften** i stället för att en dubblett skapas.

---

## 4. Var sparas allting? (JSON — finns kvar efter omstart)

Allt ligger under appens `data/`-mapp:

| Fil | Innehåll |
|---|---|
| `data/active.json` | **Uppgifterna** (schema v5). Skrivs atomiskt och sparas direkt vid varje import (även vid krasch/strömavbrott). |
| `data/archive.json` | Arkiverade uppgifter |
| `data/emails/<id>.eml` | Originalmailet för varje importerad uppgift |
| `data/mail_bridge/token.txt` | Hemlig nyckel mellan appen och tillägget |
| `data/mail_bridge/imported.json` | Dedup-register: `Message-ID → uppgift-id` (så att inget importeras två gånger) |
| `data/mail_bridge/bridge_status.json` | Bryggans status: port, antal importer, senaste import |
| `data/mail_bridge/inbox_status.json` | Inkorgsbevakningens status |
| `data/mail_bridge/tillagg_installningar.json` | Adress + token att klistra in i tillägget |
| `data/inbox/` | Släpp `.eml`, `.msg` eller `.json` här → importeras automatiskt |
| `data/inbox/imported/` | Kvittens: filer som är importerade |
| `data/inbox/failed/` | Filer som inte kunde läsas (inget raderas) |

Exempel på en uppgift som skapats från mail i `active.json`:

```json
{
  "id": "k3f9a2x1",
  "title": "Faktura 2026-10 måste betalas",
  "done": false,
  "priority": "high",
  "due_date": "2026-10-13",
  "tags": ["leverantör-ab", "jobb"],
  "created": "2026-10-12T08:15:36.847+00:00",
  "email_subject": "Faktura 2026-10 måste betalas",
  "email_from": "Leverantör AB <faktura@lev.example>",
  "email_message_id": "<e2e-faktura-1@example.com>",
  "email_path": "data\\emails\\k3f9a2x1.eml",
  "email_body": "Hej! Fakturan för oktober …",
  "email_imported_at": "2026-10-12T08:15:36+00:00"
}
```

---

## 5. Bryggans API (för den som vill integrera själv)

Bryggan lyssnar **bara på `127.0.0.1`** (inte åtkomlig från nätverket) och
kräver token i headern `X-TaskBord-Token`.

| Metod | Sökväg | Beskrivning |
|---|---|---|
| `GET` | `/` | Statussida (öppna i webbläsaren för att testa) |
| `GET` | `/health` | `{"ok":true,"app":"Ledgebord",…}` — ingen token (för att hitta appen) |
| `GET` | `/tasks?limit=50` | Aktiva uppgifter |
| `GET` | `/imported?message_id=<id>` | Är mailet redan importerat? |
| `GET` | `/settings` | Adress + token |
| `POST` | `/task` | Skapa uppgift från JSON |
| `POST` | `/eml` | Skapa uppgift från rå `.eml`-data (originalet sparas) |

**Payload för `/task`:**

```json
{
  "subject": "Möte på torsdag",
  "from": "Anna <anna@example.com>",
  "body": "Kan vi flytta mötet?",
  "priority": "high",
  "due_date": "imorgon",
  "tags": ["kund"],
  "message_id": "<abc@example.com>",
  "date": "2026-10-12T09:00:00+02:00",
  "to": "rickard@example.com",
  "folder": "Inkorgen",
  "source": "thunderbird"
}
```

**Extraval vid `/eml`** (samma fält som popupen) skickas som
headern `X-TaskBord-Extra: {"priority":"high","due_date":"imorgon","tags":["kund"]}`
eller som query-parametrar (`?priority=high&due_date=imorgon&tags=kund`).

**Testa från PowerShell** (fungerar utan Thunderbird):

```powershell
$t = Get-Content .\data\mail_bridge\token.txt          # token
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/task `
  -Headers @{ "X-TaskBord-Token" = $t } `
  -ContentType "application/json" `
  -Body '{"title":"Test från bryggan","note":"Fungerar!","priority":"high"}'
```

**Testa med curl:**

```bash
TOKEN=$(cat data/mail_bridge/token.txt)
curl -X POST http://127.0.0.1:8765/task \
  -H "X-TaskBord-Token: $TOKEN" -H "Content-Type: application/json" \
  -d '{"title":"Test via curl","note":"Hej!","priority":"low"}'
```

---

## 6. Felsökning

| Problem | Lösning |
|---|---|
| *”Kunde inte nå Ledgebord”* i tillägget | Starta appen. Kontrollera tray → 📧 E-post & Thunderbird att **Brygga** är ✅. Testa `http://127.0.0.1:8765` i webbläsaren. |
| *”Token stämmer inte”* | Gör om steg 3: kopiera inställningarna på nytt och klistra in i tillägget. (Om du klickat *Skapa ny token* i appen måste tillägget uppdateras.) |
| Porten 8765 är upptagen | Appen väljer automatiskt nästa lediga port och skriver den till `data/mail_bridge/bridge_status.json` — kopiera inställningarna igen efter bytet, eller sätt `mail_bridge_port` i `data/settings.json`. |
| Uppgiften kommer inte in | Titta i loggen: `data/logs/app_*.log` — sök efter `[MAILBRIDGE]`. Kör även `python core/mail_bridge.py` (självtest) för att verifiera bryggan. |
| Mailet hamnade i kön | Appen kördes inte. Starta den — kön skickas inom en minut (badge på tilläggsikonen visar antalet). |
| Vill börja om från noll | Ta bort `data/mail_bridge/imported.json` (dedup-registret) så kan samma mail importeras igen. Ändringar i `data/active.json` bör ske när appen är avstängd. |

---

## 7. Säkerhet & integritet

* Bryggan lyssnar **endast på `127.0.0.1`** — ingen annan dator kommer in.
* Alla anrop (utom `/health`) kräver **token** (32 tecken, slumpad med
  `secrets.token_hex`), jämförs i konstant tid.
* Token ligger i `data/mail_bridge/token.txt` — byt den när du vill via
  appen (`Skapa ny token`) och uppdatera tillägget.
* Ingen e-post skickas någonstans: bara **lokalt** mellan Thunderbird och
  Ledgebord. Inga molntjänster inblandade.
* Storleksgränser: 25 MB per mail, 512 kB JSON.

---

## 8. Utveckling & tester

```bash
# 1. Bryggans självtest + main.pyw-integrationen (kräver inget extra)
python core/mail_bridge.py
python tester/smoke_main_bridge.py

# 2. E2E-test av det RIKTIGA tillägget utan Thunderbird:
#    starta bryggan fristående …
python - <<'PY'
from pathlib import Path
from core.store import TaskStore
from core.mail_bridge import MailBridgeService
data = Path("/tmp/bridge/data")
store = TaskStore(data_dir_override=str(data))
svc = MailBridgeService(store, data, port=8770, token="e2etoken1234567890")
svc.start()
print("Token:", svc.token, "URL:", svc.url)
input("Tryck Enter för att stoppa…\n")
svc.stop()
PY

# … och kör testet (Node 18+ krävs för fetch):
node tester/mock_test.js http://127.0.0.1:8770 e2etoken1234567890
```

Testet härmar Thunderbirds `messenger.*`-API, laddar den riktiga
`background.js` och verifierar 21 punkter: meny-klick, popup, snabbuppgift,
Thunderbird-taggar, dedup, populens prioritet/datum, notiser, fel token,
offline-kö och att uppgifterna hamnar i `data/active.json`.

**Fler tester:** se [`tester/las_mig.md`](tester/las_mig.md).

**Felsöka tillägget i Thunderbird:** `Verktyg → Utvecklarverktyg →
Felsökningskonsol` (Ctrl+Shift+J) visar tilläggets `console.info`-rader
(`[Ledgebord] …`). Tillfällig laddning utan att bygga xpi: `about:debugging`
→ *Detta Thunderbird* → **Läs in tillfälligt tillägg** → välj
`thunderbird-tillagg/manifest.json`.

---

## 9. Filöversikt (koden)

| Fil | Roll |
|---|---|
| `thunderbird-tillagg/manifest.json` | Tilläggets deklaration (MV3, `messenger.*`) |
| `thunderbird-tillagg/background.js` | All logik: meny, kö, notiser, HTTP mot bryggan |
| `thunderbird-tillagg/popup.html` / `popup.js` | Popupen (prioritet/datum/taggar + snabbuppgift) |
| `thunderbird-tillagg/options.html` / `options.js` | Inställningar (klistra in JSON, testa anslutning) |
| `thunderbird-tillagg/icons/` | Ikoner (genereras av `skapa_ikoner.py`) |
| `core/mail_bridge.py` | Appens brygga: HTTP-server, dedup-register, inkorgsbevakning |
| `core/email_import.py` | Befintlig `.eml`/`.msg`-import (återanvänds av bryggan) |
| `skapa_xpi.py` / `SKAPA_XPI.bat` | Packar tillägget till `Ledgebord-Thunderbird.xpi` |
| `tester/` | Testverktyg: `smoke_main_bridge.py` (main.pyw) och `mock_test.js` (tillägget) |
