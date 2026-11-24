# TaskBord
📋 TaskBord — A lightweight, portable desktop todo widget for Windows, built with Python and PySide6. Features reminders, recurring tasks, email import, snooze, natural-language task entry and customizable desktop modes.

## 🚀 Installation (Windows)

1. Ladda ner eller klona repot och öppna mappen `TaskBord`.
2. Dubbelklicka på **`FORSTA_START.bat`**. Filen:
   - hämtar senaste stabila Python-versionen från python.org (inget versionsnummer är hårdkodat),
   - installerar Python om det saknas, eller uppgraderar det om installerad version är äldre än senaste,
   - installerar eller uppgraderar alla paket i `requirements.txt` och `requirements-optional.txt` till senaste version,
   - startar TaskBord med den nyaste Python som finns.
3. Nästa gång: dubbelklicka på **`STARTA_HAR.bat`**. Den startar direkt med nyaste installerade Python och installerar bara om Python saknas.

> Plattform: TaskBord är idag gjord för Windows. Den använder Windows-specifika funktioner för fönsterlägen och skrivbordsikoner.

## 📧 Importera uppgifter från mail (Thunderbird, Outlook m.m.)

Det finns ett **Thunderbird-tillägg** som skickar mail till appen och
skapar uppgifter. Uppgifterna sparas i **JSON** (`data/active.json`) och
finns kvar efter omstart.

* **Thunderbird-tillägget** — högerklicka på ett mail → *📋 Skicka till
  TaskBord*, eller använd knappen i meddelandefönstret (prioritet,
  förfallodatum, taggar). Källkoden ligger i `thunderbird-tillagg/`,
  färdig fil skapas med `SKAPA_XPI.bat` → `TaskBord-Thunderbird.xpi`.
* **Inkorgsmappen** `data/inbox/` — släpp `.eml`, `.msg` eller `.json` där
  så importeras de automatiskt (även mail som kom när appen var avstängd).
* **📧-knappen i widgeten / tray-menyn** — importera vanliga
  `.eml`/`.msg`-filer från disken.

Full guide (installation, API, felsökning, JSON-format):
**[THUNDERBIRD.md](THUNDERBIRD.md)**

Snabbstart:

```text
1. Kör SKAPA_XPI.bat                        → TaskBord-Thunderbird.xpi
2. Thunderbird → Tillägg och teman → ⚙️ → Installera tillägg från fil…
3. TaskBord: tray → 📧 E-post & Thunderbird → 📋 Kopiera inställningar
4. Thunderbird: tilläggets Inställningar → klistra in JSON → spara
5. Högerklicka på ett mail → 📋 Skicka till TaskBord
```

## 📅 Exportera uppgifter till kalendern (Google Calendar m.fl.)

Vill du se vissa uppgifter i Google Calendar? Högerklicka på en uppgift:

* **📅 Lägg till i Google Calendar** — öppnar Google Calendar med uppgiften
  förifylld (förfallodatumet blir en heldagshändelse). Inget konto eller
  någon nyckel behövs i appen — du trycker bara *Spara*.
* **📅 Exportera uppgiften (.ics)…** — sparar uppgiften som kalenderfil.

Flera på en gång? Högerklicka på fönstret eller använd tray-menyn →
**📅 Exportera till kalender (.ics)…** Alla uppgifter med förfallodatum blir
då händelser i en kalenderfil. Importera den i Google Calendar via
*⚙️ Inställningar → Importera och exportera → Importera* — filen fungerar
också i Outlook och Apple Kalender. Uppgifter utan förfallodatum kan inte
bli händelser och hoppas över (antalet visas i dialogen).

> En full tvåvägssynk mot Google Calendar kräver OAuth-uppsättning i Google
> Cloud (klient-id/hemlighet) — det här är den nyckelfria vägen, som täcker
> "exportera vissa uppgifter dit".

## 💖 Stöd projektet

TaskBord är gratis och utan reklam. Donationer är helt frivilliga och går till utveckling och underhåll. Appen fungerar exakt lika bra utan donation.

- 💙 **PayPal:** https://paypal.me/Rickard3dPrint
- ☕ **Ko-fi:** https://ko-fi.com/tokke2

Du hittar samma länkar i appen: högerklicka på fönstret och välj **💖 Stöd TaskBord…**.

## Loggar och felsökning

- **Dagens logg:** `data/todo_app.log`. Vanlig loggsökning och loggstatistik visar den aktiva loggen, inte arkivet.
- **Historik:** äldre loggfiler flyttas till `data/logs/archive/`. Dagsloggen roteras vid första logghändelsen efter lokal midnatt eller när appen startas nästa dag. Arkivet raderas inte automatiskt.
- **Olösta fel:** `data/felsokning.json` skapas när ett fel loggas (`ERROR` eller `CRITICAL`). Upprepningar sammanförs med antal, första och senaste tidpunkt samt senaste feldetaljer. Listan finns kvar efter omstart. Redan arkiverade loggar läses inte in som olösta fel.
- **Automatisk rensning:** när appen kan bekräfta att samma operation lyckades tas dess felpost bort, till exempel när en tidigare misslyckad inkorgsfil importeras på nytt med samma namn. Utan ett uttryckligt besked om att felet är löst ligger posten kvar. Logghistoriken ändras inte när en felpost rensas.

För kod med en verifierbar återhämtning: logga felet med `extra={"issue_key": "stabilt-fel-id"}` och anropa `resolve_log_issue("stabilt-fel-id")` endast efter bekräftad framgång för samma operation.
