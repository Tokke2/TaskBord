# ☁️ TaskBord + Google Calendar — koppla kontot lokalt (OAuth)

**Svar på frågan:** *Ja — appen kan koppla upp sig mot Google Calendar direkt,
och hela inloggningen sker lokalt på din dator.* Ingen server hos mig, inget
konto hos någon mellanhand och ingen synk-tjänst. Du godkänner en gång i din
webbläsare, sedan kan uppgifter skickas rakt in i din kalender.

Den här filen är guiden: engångssteget hos Google, kopplingen i appen och
felsökning.

---

## 1. Så funkar det (och varför det är säkert)

```
   DIN DATOR                                                GOOGLE
┌───────────────────────────────┐                    ┌──────────────────┐
│ TaskBord                      │  1. öppnar         │  Inloggning +    │
│  ☁️ Koppla Google-konto       │ ────────────────►  │  godkänn skärm   │
│                               │    webbläsare      │                  │
│  Tillfällig server på         │  2. skickar svar   │                  │
│  127.0.0.1:<slumpad port>  ◄──┼────────────────────┤                  │
│                               │   (bara under      └──────────────────┘
│  Sparar åtkomstbevis:         │    inloggningen)
│  js/google/token.json (0600)  │
└───────────────────────────────┘
```

* **Allt körs lokalt.** Appen startar en tillfällig server på `127.0.0.1`
  (loopback = bara din dator) medan du loggar in, och stänger den direkt efteråt.
* **Åtkomstbeviset sparas bara hos dig** — `js/google/token.json` med
  filrättigheter `0600` (bara din användare kan läsa den). Filen är dessutom
  undantagen i `.gitignore` så att den aldrig kan råka hamna i git.
* **Snävaste möjliga behörigheter:** `calendar.events` (skapa/ändra händelser)
  och `calendar.readonly` (läsa kalenderlistan). Appen kan inte läsa din Gmail,
  inte röra andra Google-tjänster och inte ta bort kalendrar.
* **Koppla från när du vill:** menyvalet *🗑 Koppla från* raderar beviset från
  datorn. Uppgifterna i TaskBord påverkas inte, och händelserna som redan
  skickats ligger kvar i kalendern.
* **Du kan återkalla åtkomsten hos Google** när som helst:
  <https://myaccount.google.com/permissions>

---

## 2. Engångssteg hos Google (5 minuter)

Det här görs en gång. Google kräver att *du* skaffar en egen nyckel till ditt
eget konto — det är därför ingen kan "låna" någon annans.

1. **Skapa ett projekt** (gratis): <https://console.cloud.google.com/projectcreate>
   Namnet spelar ingen roll, t.ex. `TaskBord`.
2. **Aktivera Google Calendar API:**
   <https://console.cloud.google.com/apis/library/calendar-json.googleapis.com>
   Klicka **Aktivera**.
3. **Godkännandeskärmen** (OAuth consent screen):
   <https://console.cloud.google.com/apis/credentials/consent>
   * Välj **Extern** (External) → **Skapa**.
   * Fyll i appnamn (`TaskBord`) och din e-post.
   * Under **Testanvändare** (Test users): lägg till **din egen Gmail-adress**.
     (Utan detta får du felet *403 – access_denied*.)
4. **Skapa nyckel:** <https://console.cloud.google.com/apis/credentials>
   * **Skapa inloggningsuppgifter** → **OAuth-klient-ID**
   * Programmtyp: **Datorapp** (Desktop app) — viktigt!
   * **Skapa** → **Ladda ner JSON**.
5. **Lägg filen i TaskBord-mappen:**
   ```
   js\google\credentials.json
   ```
   Appen hittar den även om du lägger den direkt i `js\` eller i appmappen,
   och den hittar namn som `client_secret_*.json`.

> 💡 Namnet `credentials.json` är bara det appen letar efter först — innehållet
> är det som räknas. Klicka **📂 Öppna mappen** i appens dialog för att komma rätt.

---

## 3. Koppla i appen (2 klick)

1. Högerklicka på TaskBord-fönstret (eller tray-ikonen) → **☁️ Google Calendar
   (koppla konto)…**
   Statusraden ska säga *Inte ansluten* och hitta din `credentials.json`.
2. Klicka **🔑 Koppla Google-konto…**

Sedan:
* Webbläsaren öppnas → välj ditt konto → **Tillåt**.
* Fliken visar *"TaskBord är kopplat!"* → stäng den.
* Statusraden i appen blir **✅ Ansluten — din@adress**.

Klart. Nu kan du skicka uppgifter.

---

## 4. Skicka uppgifter till kalendern

| Så gör du | Vad som händer |
|---|---|
| **Högerklicka på en uppgift → ☁️ Skicka till Google Calendar** | Uppgiften blir en heldagshändelse på sitt förfallodatum |
| **☁️ Välj uppgifter att skicka…** (i dialogen) | Du kryssar i vilka uppgifter som ska skickas — inget skickas utan ditt val |
| **📅 Lägg till i Google Calendar** (i uppgiftsmenyn) | Öppnar Google Calendar med händelsen förifylld — utan konto |
| **📅 Exportera till kalender (.ics)…** | Kalenderfil för Outlook/Apple Kalender/Google |

Detaljer:
* **Prioritet** blir färg i kalendern: 🔴 hög (Tomat), 🟡 normal (Banan),
  🟢 låg (Basilika). Går att stänga av med kryssrutan i dialogen.
* **Titel** = uppgiftens titel. **Beskrivning** innehåller taggar, delmoment
  (som krysslista), mailinfo och anteckningen om uppgiften kom från ett mail.
* **Dubbletter är omöjliga:** varje händelse märks med uppgiftens id, och
  appen kommer ihåg kopplingen i `js/google/event_map.json`. Skickar du samma
  uppgift igen **uppdateras** händelsen i stället för att en ny skapas — även
  om du skulle ha installerat om appen (märket finns kvar i händelsen).
* **Klara uppgifter** markeras med genomskinlig tid, så de inte bokar upp
  kalendern som "upptagen".
* **Kalenderval:** klicka **🔄 Hämta lista** och välj vilken kalender
  (t.ex. en delad "Arbete"-kalender) händelserna ska hamna i. Valet sparas.

---

## 5. Var ligger allting?

Allt hamnar i appens datamapp (`js\` i en vanlig installation — samma mapp som
`active.json`):

| Fil | Vad | Känslig? |
|---|---|---|
| `js/google/credentials.json` | Din nedladdade OAuth-nyckel (från Google) | Ja — dela inte |
| `js/google/token.json` | Åtkomstbeviset som skapas vid inloggning (0600) | **Ja — som ett lösenord** |
| `js/google/account.json` | E-post + tidszon (för statusraden) | Nej |
| `js/google/event_map.json` | Uppgift-id → händelse-id (dubblettskyddet) | Nej |

`token.json`, `credentials.json` och `client_secret*.json` ligger i
`.gitignore` — de kan inte råka följa med i en commit.

---

## 6. Felsökning

| Problem | Lösning |
|---|---|
| *"Google-paketen är inte installerade"* | Kör `pip install google-api-python-client google-auth-oauthlib` — eller starta appen med `FORSTA_START.bat` som installerar dem automatiskt. |
| *"credentials.json saknas"* | Steg 2 ovan. Klicka **📂 Öppna mappen** i appen och lägg filen där. |
| **403 – access_denied** vid inloggning | Lägg till din adress under **Testanvändare** i Godkännandeskärmen (steg 3). |
| **403 – API har inte aktiverats** | Aktivera Google Calendar API i projektet (steg 2). |
| **"Google säger att inloggningen inte längre gäller"** | Koppla från och koppla igen. (Händer om åtkomsten återkallats hos Google, eller efter mycket lång tid.) |
| **Ingenting händer när jag klickar Koppla** | Brandväggen kan blockera den tillfälliga localhost-servern. Tillåt Python i Windows Defender, eller kör om och godkänn snabbare (5 minuters tidsgräns). |
| **Webbläsaren öppnas inte** | Öppna adressen som visas i rutan för hand och logga in där. |
| **"Uppgiften behöver ett förfallodatum"** | Sätt ett datum först (⋯-menyn → 📅 Förfallodatum) — bara händelser med datum kan hamna i kalendern. |
| **Händelsen ligger på fel dag** | Heldagshändelser använder förfallodatumet; kontrollera att uppgiftens datum är rätt (tidszoner spelar ingen roll för heldagar). |

**Loggen:** allt skrivs till `js/logs/` och sök efter `[GCAL]`. Känsliga värden
(token, klienthemlighet) loggas **aldrig** — det kontrolleras av testerna.

---

## 7. Fler konton?

Just nu **ett konto i taget**. Fil-lagret är förberett för flera
(`discover_token_file` letar redan efter `token*.json` och väljer den senaste),
så flerkonto kan läggas till utan att ändra hur tokens sparas — säg till om du
vill ha en kontoväxlare.

Vill du i stället ha en **riktig tvåvägssynk** (händelser som ändras i Google
ska komma tillbaka till TaskBord) krävs mer: `calendar.readonly` för alla
händelser, ett tillstånd per händelse, konfliktregler och en synk som körs
regelbundet. Det är ett större bygge — men grunden (OAuth, service, mappning)
är redan på plats.

---

## 8. För utvecklare

```bash
# Enhetstester för kalenderlogiken (kräver google-paketen, rör inte nätet)
python tester/google_calendar_test.py

# Snabbkoll utan paket installerade
python core/google_calendar.py
```

Modulerna:

| Fil | Roll |
|---|---|
| `core/google_calendar.py` | All logik: OAuth-flöde, token, service, CRUD, mappning, retry, felöversättning |
| `ui/google_calendar_dialog.py` | Dialogen + trådningen (nätverket körs aldrig i UI-tråden) |
| `tester/google_calendar_test.py` | Kontroller mot riktiga Google-bibliotek med fejkad tjänst |

API:t är namnlikt det gamla `Script/API.py` (samma namn på funktionerna), så
vanan sitter kvar: `authenticate_google_calendar`, `build_calendar_service`,
`create_event`, `patch_event`, `update_event`, `delete_event`, `get_event`,
`list_upcoming_events`, `list_calendars`, `get_calendar_info`,
`test_connection`, `discover_token_file`, `discover_credentials_file`,
`with_retry`, `handle_http_error`, `ConnectionStatus`.
