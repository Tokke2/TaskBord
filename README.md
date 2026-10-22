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
  TaskBord*. **Markera flera mail** (Ctrl/Shift-klick) så blir varje mail en egen uppgift, med
  EN sammanfattande notis (”3 uppgifter skapade · 1 fanns redan”); redan importerade mail
  hoppas över. Eller använd knappen i meddelandefönstret (prioritet,
  förfallodatum, taggar). Källkoden ligger i `thunderbird-tillagg/`,
  färdig fil skapas med `SKAPA_XPI.bat` → `TaskBord-Thunderbird.xpi`.
* **Inkorgsmappen** `data/inbox/` — släpp `.eml`, `.msg` eller `.json` där
  så importeras de automatiskt (även mail som kom när appen var avstängd).
* **📧-knappen i widgeten / tray-menyn** — importera vanliga
  `.eml`/`.msg`-filer från disken.
* **📧 Öppna mejlet** — varje uppgift som kommer från ett mail har en 📧-knapp på kortet (och
  *📧 Öppna mejlet* i högerklicksmenyn). Den öppnar originalmailet (`.eml`) i ditt mailprogram.
  Har appmappen flyttats hittas filen ändå i `js\emails\`; finns den inte kvar visas den sparade
  mailtexten (avsändare, ämne, text) i en ruta i stället för att knappen verkar död.
* **↩ Svara på mejlet** — bredvid 📧 på kortet (och *↩️ Svara på mejlet* i högerklicksmenyn) öppnas
  ett färdigt svar i ditt standard-mailprogram: mottagare (Reply-To om mailet har det, annars
  avsändaren), ämne med *Re:* och originalet citerat. OBS: en `mailto:`-länk kan inte bära
  trådinformation, så svaret hamnar som ett nytt mail i stället för i samma tråd.
* **🧩 Nytt Thunderbird-tillägg** — Thunderbird byter inte ut ett installerat tillägg av sig självt.
  Ändras `TaskBord-Thunderbird.xpi` i appmappen (t.ex. vid en uppdatering) får du en tray-notis och
  en menyrad *🆕 Nytt Thunderbird-tillägg — installera om…* med knapp **📂 Visa filen** (öppnar mappen
  med filen markerad) och **✔ Jag har installerat det**. Jämförs på innehåll, inte versionsnummer.

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
tray → *Sök ny version automatiskt*.

**Manuellt:** tray-menyn → **🔄 Sök ny version…** hämtar GitHub-releasen *Latest* och jämför
filerna med din installation (innehållet, inte versionsnumret — releasen kan heta v1.0.0 och
ändå ha ny kod). Finns skillnader visas vilka filer, och du väljer **Uppdatera nu**.

* **Förlopp hela vägen:** ett förloppsfönster visar sökning och nedladdning (MB, kan avbrytas)
  och sedan installationen ("Installerar filer… 3 av 14"), så det aldrig ser ut som att det hängt sig.
* **Dina uppgifter rörs inte:** `js\` (uppgifter, inställningar, Google-koppling) och `data\`
  (loggar, backuper) hoppas alltid över. Uppgifterna sparas och backas upp före uppdateringen.
* **Ångra:** ersatta filer sparas i `data\backups\app-update\<tid>\`.
* **Självläkande:** efter uppdateringen startar en liten väktare (`core/update_watchdog.py`, en kopia
  av den gamla, fungerande koden i backupmappen) den nya appen och väntar upp till **60 sekunder** på
  att den kommit igång. Kraschar eller hänger den sig återställs de gamla filerna automatiskt, nya
  filer tas bort och den förra versionen startas igen. Nästa start berättar vad som hänt, och just
  den uppdateringen aviseras inte igen. Loggen finns i `data\update_watchdog.log`. (Skyddet kommer
  från den version som kör uppdateringen — den första uppdateringen *till* en version med väktaren
  går alltså utan skydd.)
* **Säkert:** hämtar bara från GitHub över https, kompilerar alla Python-filer först (en trasig
  release installeras aldrig), rullar tillbaka om något går fel och skriver inget utanför
  appmappen. Filer du själv lagt till tas inte bort.
* Appen startar om automatiskt. Ändras `requirements.txt` ska du köra `FORSTA_START.bat`.
* Uppdateringen hämtas alltid från den senaste **releasen** på GitHub – aldrig från `main` och aldrig via `git pull` – även om mappen är en git-mapp (`.git` lämnas orörd; filerna syns då som ändrade i git).

## 🖥️ Windows · macOS · Linux

Appen körs på alla tre. Installation/start på **macOS och Linux** (Python 3.10+):

```bash
./starta.sh              # första gången: skapar .venv i appmappen, installerar paket, startar
./starta.sh --forgrund   # starta i terminalen (visar fel direkt)
```

På macOS kan du också dubbelklicka på `STARTA_TASKBORD.command`. Allt installeras i `.venv` i appmappen
(inget i systemets Python, inget utanför mappen). Uppdateringen via "Sök ny version" rör aldrig `.venv`, och
kör du `./starta.sh` igen installeras nya paket bara om kraven ändrats. Debian/Ubuntu: `sudo apt install python3-venv`
(och vid Qt-fel `libxcb-cursor0`).

| Funktion | Windows | macOS | Linux |
|---|---|---|---|
| Uppgifter, backup, mail-brygga, kalender, uppdatering | ✅ | ✅ | ✅ |
| Start med datorn | Registret/Startup | LaunchAgent | `~/.config/autostart` |
| Skrivbordsläge "Alltid överst" / "Bakom ikonerna" | Win32 (på skrivbordet) | Qt-flaggor (överst; "bakom" ignoreras av macOS) | Qt-flaggor (X11 fullt, Wayland beroende på skrivbord) |
| Globala snabbtangenter (Ctrl+Alt+…) | ✅ | ❌ (använd tray-menyn) | ❌ (använd tray-menyn) |
| Google-nyckel (`token.json`) | krypterad (DPAPI) | filrättighet 0600 | filrättighet 0600 |
| Systemtema | register | Qt | Qt |

Testas av `tester/multios_test.py`. Jag har provat skripten och logiken på Linux; Windows är den plattform appen
utvecklats på, macOS är inte provat på riktig maskin.

## ⌨️ Snabbtangent för ny uppgift

Standard **Ctrl+Alt+N** öppnar rutan för ny uppgift var som helst i Windows. Ändra den:
tray → **⌨️ Ändra snabbtangent för ny uppgift…** — klicka i rutan och *tryck* kombinationen (inget
att skriva). Dialogen säger direkt om den duger (minst två av Ctrl/Alt/Shift eller Win, inte en
Windows-genväg, inte samma som Visa-över-tangenten), *Standard* återställer och *Stäng av* tar bort
den. Är tangenten upptagen av ett annat program behålls den gamla. Gäller direkt, ingen omstart.

## 🖥️ Skrivbordsläge – bakom ikonerna eller alltid överst

Högerklicka på tray-ikonen → **Skrivbordsläge** och välj:

- **Bakom ikonerna (som förut)** – widgeten ligger på skrivbordet och Win+D kan inte gömma den.
- **Alltid överst (ovanpå alla fönster)** – widgeten ligger ovanpå alla andra fönster hela tiden och går att skriva i direkt.

Valet sparas och gäller även efter omstart. Om Windows (t.ex. Win+D) minimerar widgeten i läget *Alltid överst* återställs den automatiskt inom några sekunder.

## ⌨️ Styra listan med tangentbordet

Tryck **↓** (eller **↑**) – även när du står i inmatningsfältet – så markeras en uppgift med en färgad ram. Därefter:

| Tangent | Gör |
|---|---|
| ↑ / ↓ | föregående / nästa uppgift (↑ på den första går tillbaka till inmatningsfältet) |
| Home / End, PgUp / PgDn | första / sista, 5 steg |
| Mellanslag | markera klar |
| E eller F2 | ändra titeln direkt på kortet (Enter sparar, Esc avbryter) |
| P | fäst / lossa |
| 1 / 2 / 3 / 0 | prioritet hög / normal / låg / ingen |
| Delete | ta bort (frågar först) |
| Esc | lämna markeringen (nästa Esc gömmer fönstret som förut) |

**Med musen:** dubbelklicka på en titel (eller högerklicka → *Byt namn*) så blir titeln en textruta på kortet. Enter eller klick utanför sparar, Esc avbryter. F2 fungerar även från musmarkeringen.

Skriver du ett vanligt tecken som inte är en kommandotangent hamnar det i inmatningsfältet. När en uppgift blir klar eller tas bort flyttas markeringen till nästa, så du kan bocka av en hel rad med mellanslag.

## 🔠 Textstorlek (Kompakt · Normal · Stor)

Högerklicka på tray-ikonen → **Textstorlek**: *Kompakt* (mindre text, tätare kort, döljer raden "Tillagd" – du ser fler uppgifter), *Normal* (som förut) eller *Stor* (större text, luftigare). Valet sparas.

**Läsbarhet:** all text har minst 4,5:1 kontrast (WCAG AA) över normala bakgrunder (minst 3:1 vid lägsta transparens över extremt ljus/mörk bakgrund) och ingen text är mindre än 11 px (10 px vid Kompakt). Transparensen kan som mest sänkas till **70 %** (lägre skulle göra texten svårläst över ljusa bakgrunder); *Av* ger en helt ogenomskinlig panel. Testas av `tester/ui_readability_test.py`.

**Markera med mus eller tangentbord:** klicka på ett kort för att markera det – piltangenterna, `1`–`3`, mellanslag m.fl. verkar sedan på det kortet.

**Fönstrets plats efter uppdatering:** position och storlek skrivs ner till `js\settings.json` både före installationen och före omstarten (mappen `js\` rörs aldrig av uppdateringen), så fönstret kommer upp exakt där det stod.

## 📌 Alltid överst – snabbtangent

Standard **Ctrl+Alt+T**: lägger TaskBord **över alla andra appar** (läget *Alltid överst*). Tryck igen så går
fönstret tillbaka till det läge du hade förut (Bakom ikonerna / På skrivbordet). Fungerar var som helst i Windows,
även när en annan app är aktiv. Ändra eller stäng av: tray → **⌨️ Snabbkommandon → 📌 Alltid överst på/av…**.
(Vill du bara titta en stund: håll **Ctrl+Alt+V** – då visas fönstret så länge du håller tangenten.)
**Högerklicka på fönstret → 📌 Alltid överst** (bockruta) – samma sak med musen, fungerar på alla system.
På macOS/Linux finns inga globala tangenter – välj *Alltid överst* i tray-menyn.

## 📋 Lägg till från urklipp

Standard **Ctrl+Alt+K**: markera text i *vilket program som helst* och tryck tangenten — texten
blir en uppgift direkt (första raden = rubrik, resten = anteckning; en lång första rad kortas och
hela texten hamnar i anteckningen). Appen kopierar markeringen åt dig, släpper de tangenter du
håller, och **återställer det som låg i urklippet**. Är inget markerat används det som redan ligger
i urklippet. En tray-notis visar vad som skapades. Ändra/stäng av: tray → **⌨️ Snabbkommandon →
📋 Lägg till från urklipp…**. Utan snabbtangent: tray → *📋 Ny uppgift från urklipp*.

## 🩺 Felrapport

tray → **🩺 Skapa felrapport…** packar en ZIP i `data\felrapporter\` (de 10 senaste behålls) och öppnar
mappen: version/Python/Windows, ett fingeravtryck per programfil (visar exakt vilken kod som körs),
loggens sista rader och inställningarna. Token och mailadresser maskas, och **dina uppgifter,
Google-koppling och mailinnehåll tas aldrig med**. Loggen kan ändå nämna uppgiftstitlar — titta
igenom den innan du skickar den.

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

**Enkel koppling:** trycker du *☁️ Skicka till Google Calendar* på en uppgift öppnas Googles inloggningssida
direkt – logga in, godkänn, och uppgiften skickas. Det kräver att appen levereras med en OAuth-klient
(`core/google_client.json`, läggs dit en gång av utvecklaren – se `GOOGLE_CALENDAR.md` kapitel 1b). Utan den
visas den guidade installationen som förut.

Saknar uppgiften datum öppnas en datumväljare (valet sparas som förfallodatum) i stället för ett felmeddelande. Efter godkännandet sparas en lokal nyckelfil i `js\google\token.json`, krypterad med Windows DPAPI så att bara ditt Windows-konto på den här datorn kan använda den.

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
| `app/mixins/*.py` | en fil per ansvar: `tray`, `updates`, `addon_update`, `mail_bridge_ctl`, `autostart`, `windows`, `desktop_shell`, `hotkeys`, `clip_task`, `reminders`, `backup_sync`, `exports`, `diagnostics`, `app_icon`, `plugin_updates`, `maintenance` |
| `app/constants.py` | version, sökvägar (`SCRIPT_DIR` = appmappen), enums, undantag |
| `app/*.py` (övriga) | loggning, plugin-system, central logg, prestanda, förkontroller, modulladdning |

Själva fönstret (`TodoWidget`) låg förut i en enda fil på ~8 100 rader. `ui/widget.py` är nu en liten
fasad — alla importer (`from widget import TodoWidget`) fungerar som förut:

| Fil | Innehåll |
| --- | --- |
| `ui/widget.py` | `TodoWidget(mixins…, QWidget)` — signaler, `__init__` och diagnostik |
| `ui/widget_base.py` | konstanter, teman, hjälpfunktioner, logg/felhantering, PWM, `parse_natural_input` |
| `ui/widget_atoms.py` | `EditableLabel`, `TagChip`, `PriorityBadge`, `PriorityDot`, `DueDateLabel`, `GlassFrame` |
| `ui/widget_parts/*.py` | metoderna, en mixin per område: `lifecycle`, `task_menu`, `task_actions`, `render`, `task_card`, `theme`, `keys_position`, `focus_timers`, `exports`, `window_ops`, `keynav`, `qt_events` |

Ändra textstorleken via `set_ui_font_scale()` (i `widget_base`), inte genom att skriva till `_UI_FONT_SCALE`.
`tester/widget_split_test.py` vaktar delningen (alla metoder kvar, inga namn saknas, ingen metod i två mixins).

Regler som testerna vaktar (`tester/structure_test.py`): alla moduler går att importera, ingen metod
finns i två mixins (annars vinner en tyst), inga odefinierade namn, sökvägar byggs från `SCRIPT_DIR`
(aldrig från `__file__` i `app/`). `tester/app_boot_test.py` startar hela appen offscreen och läser loggen.

## 💖 Stöd projektet

TaskBord är gratis och utan reklam. Donationer är helt frivilliga och går till utveckling och underhåll. Appen fungerar exakt lika bra utan donation.

- 💙 **PayPal:** https://paypal.me/Rickard3dPrint
- ☕ **Ko-fi:** https://ko-fi.com/tokke2

Du hittar samma länkar i appen: högerklicka på fönstret och välj **💖 Stöd TaskBord…**.
