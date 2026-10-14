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

## 🔄 Uppdatera appen (Sök ny version)

**Automatiskt:** vid start (efter ca 30 s) och därefter högst en gång per dygn kollar TaskBord
tyst i bakgrunden. Är allt aktuellt märker du ingenting. Finns en ny version får du *en*
tray-notis (klicka på den för att uppdatera), och menyraden ändras till
**🆕 Ny version finns — uppdatera…**. Inget installeras utan att du godkänner. Stäng av med
tray → *Sök ny version automatiskt*. (Hoppas över i en git-mapp.)

**Manuellt:** tray-menyn → **🔄 Sök ny version…** hämtar GitHub-releasen *Latest* och jämför
filerna med din installation (innehållet, inte versionsnumret — releasen kan heta v1.0.0 och
ändå ha ny kod). Finns skillnader visas vilka filer, och du väljer **Uppdatera nu**.

* **Förlopp hela vägen:** ett förloppsfönster visar sökning och nedladdning (MB, kan avbrytas)
  och sedan installationen ("Installerar filer… 3 av 14"), så det aldrig ser ut som att det hängt sig.
* **Dina uppgifter rörs inte:** `js\` (uppgifter, inställningar, Google-koppling) och `data\`
  (loggar, backuper) hoppas alltid över. Uppgifterna sparas och backas upp före uppdateringen.
* **Ångra:** ersatta filer sparas i `data\backups\app-update\<tid>\`.
* **Säkert:** hämtar bara från GitHub över https, kompilerar alla Python-filer först (en trasig
  release installeras aldrig), rullar tillbaka om något går fel och skriver inget utanför
  appmappen. Filer du själv lagt till tas inte bort.
* Appen startar om automatiskt. Ändras `requirements.txt` ska du köra `FORSTA_START.bat`.
* Kör du från en git-mapp (`.git`) används `git pull` i stället.

## 💾 Backup av uppgifter

Högerklicka på fönstret (eller tray-ikonen) → **💾 Backup av uppgifter…**

* **Säkerhetskopiera nu** — sparar alla aktiva och arkiverade uppgifter i en ZIP-fil i
  `backups/uppgifter/` bredvid `active.json` (de 30 senaste behålls).
* **Spara kopia som…** — lägg en kopia på ett USB-minne eller i en molnmapp (OneDrive, Dropbox …).
* **Återställ** — välj en backup i listan eller en egen ZIP-fil. Filen kontrolleras först, och
  innan något ersätts sparas en säkerhetskopia av nuläget (`…-fore-aterstallning-….zip`), så
  du kan ångra dig. Dessa rensas aldrig automatiskt.

**Automatisk backup:** uppgifter, arkiv och inställningar (fönsterposition och storlek)
kopieras vid avslut och var 5:e minut till `data/backups/auto/` — allt stannar i appmappen,
inget skrivs någon annanstans. Bara ändringar sparas, de 20 senaste behålls. Saknas eller är
`js/active.json` / `js/settings.json` skadade vid start (till exempel om en uppdatering tagit
`js/`) läses de in från den senaste kopian automatiskt. Mappen kan flyttas med miljövariabeln
`TASKBORD_BACKUP_DIR`. OBS: byts *hela* appmappen ut följer kopiorna med — spara då en kopia
med **Spara kopia som…**.

Test: `python tester/tasks_backup_test.py`.

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
också i Outlook och Apple Kalender. Uppgifter utan förfallodatum **och** utan
startdatum kan inte bli händelser och hoppas över (antalet visas i dialogen).

**Startdatum:** helt valfritt, och du kan ange det direkt när du skriver uppgiften —
t.ex. *"Byt vindruta start nästa vecka"* (läggs in idag, men hamnar i kalendern nästa vecka).
Det går att skriva `start nästa vecka` (= måndag), `start måndag`, `start 19/10`,
`start 2026-10-19`, `start om 5 dagar` eller `från imorgon`. Efteråt: högerklicka på en
uppgift → **▶ Startdatum → 📆 Välj i kalender…** (eller snabbval). Så blir det i kalendern:
* bara förfallodatum → heldagshändelse den dagen (som förut)
* bara startdatum → heldagshändelse på startdagen — förfallodatum behövs alltså inte
* båda → en flerdagarshändelse från start till och med förfallodatum
  (ligger starten efter förfallodatum används bara förfallodatum)

> En full tvåvägssynk mot Google Calendar kräver OAuth-uppsättning i Google
> Cloud (klient-id/hemlighet) — det här är den nyckelfria vägen, som täcker
> "exportera vissa uppgifter dit".

## ☁️ Google Calendar (lokal koppling)

Vill du ha uppgifterna i din riktiga kalender? Högerklicka i fönstret eller
tray-ikonen → **☁️ Google Calendar (koppla konto)…**

Kopplingen sker **helt lokalt**: inloggningen öppnas i din webbläsare och
svaret kommer tillbaka till en tillfällig server på `127.0.0.1`. Åtkomstbeviset
sparas bara i din egen mapp (`js/google/token.json`, rättigheter 0600) och
appen kan bara skapa/ändra händelser — inget annat. Inga konton hos mellanhänder.

Ett engångssteg krävs hos Google (skapa en egen nyckel, ca 5 minuter):
**[GOOGLE_CALENDAR.md](GOOGLE_CALENDAR.md)** beskriver varje klick.

Sedan:
* **Högerklicka på en uppgift → ☁️ Skicka till Google Calendar** — uppgiften blir
  en heldagshändelse på sitt förfallodatum, eller från startdatum till förfallodatum
  (prioritet blir färg).
* **☁️ Välj uppgifter att skicka…** i dialogen — du kryssar själv i vilka som ska med (inget skickas utan ditt val).
* Dubbletter är omöjliga: samma uppgift **uppdaterar** sin händelse.
* **🧭 Guidad installation** i dialogen leder dig genom engångsstegen hos Google och
  kontrollerar `credentials.json` innan inloggningen.
* **🕘 Historik** visar vad som skickats, när och med vilket resultat — med knapp
  för att öppna händelsen i Google Calendar.
* **Klara uppgifter** blir grå (✅ framför titeln, eller överstruken) i kalendern.
* Vill du hellre ha en fil att importera? **📅 Exportera till kalender (.ics)…**
  fungerar utan konto (Outlook, Apple Kalender och Google Calendar).

## 🧱 Kodstruktur (för den som ändrar koden)

`main.pyw` är bara startfilen (~130 rader). Allt annat ligger i paketet `app/`:

| Fil | Innehåll |
| --- | --- |
| `app/bootstrap.py` | `run()` — hela uppstartsflödet, global felhanterare |
| `app/controller.py` | `AppController`, sätts ihop av mixins |
| `app/mixins/*.py` | en fil per ansvar: `tray`, `updates`, `mail_bridge_ctl`, `autostart`, `windows`, `desktop_shell`, `hotkeys`, `reminders`, `backup_sync`, `exports`, `diagnostics`, `app_icon`, `plugin_updates`, `maintenance` |
| `app/constants.py` | version, sökvägar (`SCRIPT_DIR` = appmappen), enums, undantag |
| `app/*.py` (övriga) | loggning, plugin-system, central logg, prestanda, förkontroller, modulladdning |

Regler som testerna vaktar (`tester/structure_test.py`): alla moduler går att importera, ingen metod
finns i två mixins (annars vinner en tyst), inga odefinierade namn, sökvägar byggs från `SCRIPT_DIR`
(aldrig från `__file__` i `app/`). `tester/app_boot_test.py` startar hela appen offscreen och läser loggen.

## 💖 Stöd projektet

TaskBord är gratis och utan reklam. Donationer är helt frivilliga och går till utveckling och underhåll. Appen fungerar exakt lika bra utan donation.

- 💙 **PayPal:** https://paypal.me/Rickard3dPrint
- ☕ **Ko-fi:** https://ko-fi.com/tokke2

Du hittar samma länkar i appen: högerklicka på fönstret och välj **💖 Stöd TaskBord…**.
