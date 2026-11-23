# Ledgebord — manual

> Det här är den **fullständiga** beskrivningen. Vill du bara komma igång: se [README](../README.md).

## Innehåll

- [🚀 Installation (Windows)](#-installation-windows)
- [📧 Importera uppgifter från mail (Thunderbird, Outlook m.m.)](#-importera-uppgifter-från-mail-thunderbird-outlook-mm)
- [🔄 Uppdatera appen (Sök ny version)](#-uppdatera-appen-sök-ny-version)
- [🖥️ Windows · macOS · Linux](#-windows--macos--linux)
- [⌨️ Snabbtangent för ny uppgift](#-snabbtangent-för-ny-uppgift)
- [🖥️ Visa över andra appar (kryssruta)](#-visa-över-andra-appar-kryssruta)
- [⌨️ Styra listan med tangentbordet](#-styra-listan-med-tangentbordet)
- [✅ Klar och nästa (Ctrl+D)](#-klar-och-nästa-ctrld)
- [📆 Kalender – se vilka dagar som är tunga](#-kalender--se-vilka-dagar-som-är-tunga)
- [📝 Fliken Anteckningar (egna anteckningar)](#-fliken-anteckningar-egna-anteckningar)
- [💸 Delbetalningsplan (faktura i flera betalningar)](#-delbetalningsplan-faktura-i-flera-betalningar)
- [📋 Jobbmallar (ett klick → alla uppgifter, ev. direkt till Google Calendar)](#-jobbmallar-ett-klick--alla-uppgifter-ev-direkt-till-google-calendar)
- [🏷 Taggfärger](#-taggfärger)
- [🌗 Temat följer Windows (live)](#-temat-följer-windows-live)
- [⌨️ F1 – tangentöversikt](#-f1--tangentöversikt)
- [🔗 Länkar och 📎 bilagor](#-länkar-och--bilagor)
- [📜 Arkivet är historik som ligger kvar för alltid](#-arkivet-är-historik-som-ligger-kvar-för-alltid)
- [💰 Belopp](#-belopp)
- [📝 Anteckningar](#-anteckningar)
- [📞 Klickbara telefonnummer och 📍 adresser](#-klickbara-telefonnummer-och--adresser)
- [🔠 Textstorlek (Kompakt · Normal · Stor)](#-textstorlek-kompakt--normal--stor)
- [📌 Visa över andra appar – snabbtangent](#-visa-över-andra-appar--snabbtangent)
- [🗕 Stäng och minimera → systemfältet](#-stäng-och-minimera--systemfältet)
- [🔴 Röda dagar i veckan](#-röda-dagar-i-veckan)
- [📅 Datum i importerade mail → påminnelser](#-datum-i-importerade-mail--påminnelser)
- [🔔 Påminnelser med knappar + siffra på ikonen](#-påminnelser-med-knappar--siffra-på-ikonen)
- [🎨 Namn och ikon](#-namn-och-ikon)
- [1️⃣ Bara en instans – starta igen = öppna den som kör](#1-bara-en-instans--starta-igen--öppna-den-som-kör)
- [↔ Dockning vid skärmkant](#-dockning-vid-skärmkant)
- [📋 Lägg till från urklipp](#-lägg-till-från-urklipp)
- [🧯 Felloggen — alla fel på ett ställe (`loggar\fel.log`)](#-felloggen--alla-fel-på-ett-ställe-loggarfellog)
- [🩺 Felrapport](#-felrapport)
- [💾 Backup av uppgifter](#-backup-av-uppgifter)
- [📅 Exportera uppgifter till kalendern (Google Calendar m.fl.)](#-exportera-uppgifter-till-kalendern-google-calendar-mfl)
- [☁️ Google Calendar (lokal koppling)](#-google-calendar-lokal-koppling)
- [🧱 Kodstruktur (för den som ändrar koden)](#-kodstruktur-för-den-som-ändrar-koden)
- [🗣 Naturliga datum (fre 14, om 3 dagar, nästa mån)](#-naturliga-datum-fre-14-om-3-dagar-nästa-mån)
- [🌙 Tysta timmar och påminnelseljud](#-tysta-timmar-och-påminnelseljud)
- [👋 Välkomstguide (första start)](#-välkomstguide-första-start)
- [🎨 Teman och utseende (+ ♿ tillgänglighet)](#-teman-och-utseende--tillgänglighet)
- [💖 Stöd projektet](#-stöd-projektet)
- [📄 Licens](#-licens)

## 🚀 Installation (Windows)

1. Ladda ner eller klona repot och öppna appmappen.
2. Dubbelklicka på **`FORSTA_START.bat`**. Filen:
   - **kollar först om Python redan finns.** Finns den används den som den är: **Python uppdateras inte** (varken
     här, vid start eller i veckounderhållet) och ingen ny Python installeras bredvid. **Bara om Python saknas**
     *frågar* filen (J/N) om senaste stabila ska installeras från python.org (bara för ditt konto, ingen admin; inget
     versionsnummer är hårdkodat). Säger du nej installeras inget. Finns Python frågar filen aldrig,
   - installerar eller uppgraderar alla paket i `requirements.txt` och `requirements-optional.txt` till senaste version,
   - startar Ledgebord med systemets egen Python (den som ligger först i `PATH`, samma som `python` i ett kommandofönster; bara om den saknas letas standardmapparna igenom).
3. Nästa gång: dubbelklicka på **`STARTA_HAR.bat`**. Den startar med systemets egen Python och installerar bara om Python saknas. **En gång i veckan — helst måndag 08:00, inte vid varje start — kollas Pythons tillägg** (paketen i `requirements.txt` / `requirements-optional.txt`; Python själv uppdateras inte) och uppdateras, tyst, med den installerade Pythons egen pip (`core/pip_update.py`). **Ingen egen miljö (venv)**: allt ligger i samma Python som övriga program. Veckan börjar måndag 08:00; är veckans underhåll inte gjort är det "dags":
  - *Ledgebord körs sedan före måndag 08:00:* ca 10 min in i appens körning efter 08:00, eller så snart du inte skriver/redigerar, kollar appen i bakgrunden om något finns att uppdatera. Finns något startar den om tyst (fönsterläge och uppgifter sparas som vid en uppdatering), `FORSTA_START.bat /snabb /vecka` uppdaterar medan appen är avstängd och startar den igen. Finns inget bockas veckan av utan omstart. Högst ett omstartsförsök per vecka.
  - *Datorn var avstängd på måndagen:* första start via `STARTA_HAR.bat` efter 08:00 gör underhållet först (några sekunder).
  - *Offline/fel:* appen startar ändå; nytt försök vid en start först efter 6 timmar (aldrig en omstart för det).
  Beroenden som andra program delar uppgraderas bara om ett krav i Ledgebord kräver det. Resultatet står i `loggar\pip_uppdatering.log`, veckans status i `loggar\veckounderhall.json`. Underhållet görs bara på Windows. Vill du köra det direkt: `FORSTA_START.bat` (full uppdatering av tilläggen). Inget svart konsollfönster visas: `STARTA_HAR.bat` startar via `STARTA_DOLT.vbs` (dolt), och själva appen körs med `pythonw.exe`, där alla underprogram (schtasks, reg, pip …) startas utan fönster (`core/no_console.py`). Saknas Python öppnas ett synligt installationsfönster. Allra utan blink: använd skrivbordsgenvägen "Ledgebord" eller dubbelklicka `main.pyw`.

> Plattform: Ledgebord är idag gjord för Windows. Den använder Windows-specifika funktioner för fönsterlägen och skrivbordsikoner.

## 📧 Importera uppgifter från mail (Thunderbird, Outlook m.m.)

Det finns ett **Thunderbird-tillägg** som skickar mail till appen och
skapar uppgifter. Uppgifterna sparas i **JSON** (`data/active.json`) och
finns kvar efter omstart.

* **Thunderbird-tillägget** — högerklicka på ett mail → *📋 Skicka till
  Ledgebord*. **Markera flera mail** (Ctrl/Shift-klick) så blir varje mail en egen uppgift, med
  EN sammanfattande notis (”3 uppgifter skapade · 1 fanns redan”); redan importerade mail
  hoppas över. Eller använd knappen i meddelandefönstret (prioritet,
  förfallodatum, taggar). Källkoden ligger i `thunderbird-tillagg/`,
  färdig fil skapas med `SKAPA_XPI.bat` → `Ledgebord-Thunderbird.xpi`.
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
  Ändras `Ledgebord-Thunderbird.xpi` i appmappen (t.ex. vid en uppdatering) får du en tray-notis och
  en menyrad *🆕 Nytt Thunderbird-tillägg — installera om…* med knapp **📂 Visa filen** (öppnar mappen
  med filen markerad) och **✔ Jag har installerat det**. Jämförs på innehåll, inte versionsnummer.

Full guide (installation, API, felsökning, JSON-format):
**[THUNDERBIRD.md](../THUNDERBIRD.md)**

Snabbstart:

```text
1. Kör SKAPA_XPI.bat                        → Ledgebord-Thunderbird.xpi
2. Thunderbird → Tillägg och teman → ⚙️ → Installera tillägg från fil…
3. Ledgebord: tray → 📧 E-post & Thunderbird → 📋 Kopiera inställningar
4. Thunderbird: tilläggets Inställningar → klistra in JSON → spara
5. Högerklicka på ett mail → 📋 Skicka till Ledgebord
```

## 🔄 Uppdatera appen (Sök ny version)

**Automatiskt och tyst:** vid start (efter ca 30 s) och därefter **2 gånger per dygn** (var 12:e timme) kollar
Ledgebord i bakgrunden. Är allt aktuellt märker du ingenting. Finns en ny version installeras den **tyst** och
Ledgebord **startar om sig själv utan några fönster**:

* uppgifter, inställningar och fönstrets plats sparas först (och en backup tas), `js\` och `data\` rörs inte;
* skriver du en uppgift, redigerar en titel, drar ett kort eller har en dialog/meny öppen väntar omstarten
  tills du är klar (högst 3 timmar, därefter en vanlig notis);
* kommer den nya versionen inte igång inom 60 s återställs den förra automatiskt, och just den uppdateringen
  installeras aldrig tyst igen;
* samma uppdatering installeras aldrig automatiskt två gånger (skydd mot omstartsloop);
* ändras `requirements.txt` (nya paket) installeras inget tyst – du får en notis och kör `INSTALLERA.bat`.

Vill du själv godkänna varje uppdatering: tray → avkryssa **Installera nya versioner tyst (omstart)** – då får
du bara en tray-notis (klicka för att uppdatera) och menyraden **🆕 Ny version finns — uppdatera…**.
Stäng av hela kollen med tray → *Sök ny version automatiskt*.

**Manuellt:** tray-menyn (högerklick) → översta raden **🔄 Uppdatera appen…** (blir **🆕 Ny version finns — uppdatera nu (N filer)** när det finns något; ett klick då frågar och installerar direkt; grånad med status medan den söker/installerar) — hämtar GitHub-releasen *Latest* och jämför
filerna med din installation (innehållet, inte versionsnumret — releasen kan heta v1.0.0 och
ändå ha ny kod). Finns skillnader visas vilka filer, och du väljer **Uppdatera nu**.

**Knappen i fönstret:** i titelraden (mellan statistiken och 🔒) sitter en uppdateringsknapp.
`⟳` = sök ny version (tooltip visar *Senast kollat*), `⏳` = söker/installerar, `✓` = du har senaste i 8 s efter en manuell koll,
och `⬆` (grön) = ny version finns. Då visas också en grön rad under titeln — **🆕 Ny version finns (N filer) [Uppdatera nu]**.
Klick på `⬆`/Uppdatera nu inom 30 min efter att uppdateringen hittades frågar direkt och installerar utan ny nätverkskoll;
annars görs en ny manuell koll. Tysta bakgrundskollar blinkar aldrig i knappen — den lyser bara grönt om en uppdatering
väntar (t.ex. när `requirements.txt` ändrats och tyst installation därför inte sker).

* **Förlopp hela vägen:** ett förloppsfönster visar sökning och nedladdning (MB, kan avbrytas)
  och sedan installationen ("Installerar filer… 3 av 14"), så det aldrig ser ut som att det hängt sig.
* **Dina uppgifter rörs inte:** `js\` (uppgifter, inställningar, Google-koppling) och `data\`
  (loggar, backuper) hoppas alltid över. Uppgifterna sparas och backas upp före uppdateringen.
* **Ångra:** ersatta filer sparas i `data\backups\app-update\<tid>\`.
* **Självläkande:** efter uppdateringen startar en liten väktare (`core/update_watchdog.py`, en kopia
  av den gamla, fungerande koden i backupmappen) den nya appen och väntar upp till **60 sekunder** på
  att den kommit igång. Kraschar eller hänger den sig återställs de gamla filerna automatiskt, nya
  filer tas bort och den förra versionen startas igen. Nästa start berättar vad som hänt, och just
  den uppdateringen aviseras inte igen. Loggen finns i `loggar\update_watchdog.log`. (Skyddet kommer
  från den version som kör uppdateringen — den första uppdateringen *till* en version med väktaren
  går alltså utan skydd.)
* **Säkert:** hämtar bara från GitHub över https, kompilerar alla Python-filer först (en trasig
  release installeras aldrig), rullar tillbaka om något går fel och skriver inget utanför
  appmappen. Filer du själv lagt till tas inte bort.
* **Borttagna filer städas:** raderar en release en programfil (t.ex. en gammal modul) tas den bort hos dig också —
  men bara filer som appen *vet* är programfiler: listan `data\installed_files.json` som skrivs efter varje
  installation (och första gången när en koll visar att allt är identiskt med releasen), plus en fast lista över
  filer som tagits bort ur projektet förr (regelfunktionen m.fl.). Därför tar *första* uppdateringen efter att
  funktionen kom bara bort den fasta listan; resten gäller från nästa uppdatering. `js\`, `data\`, `.git` och
  venv rörs aldrig, tomma mappar städas, och en spärr (max 25 filer / 40 %) stoppar raderingen om en release-zip ser
  trasig ut. Borttagna filer sparas i backupen först, återställs om installationen eller starten misslyckas och
  räknas som en riktig uppdatering (”N filer”) även om inget annat ändrats.
* Appen startar om automatiskt. Ändras `requirements.txt` ska du köra `FORSTA_START.bat`.
* Uppdateringen hämtas alltid från den senaste **releasen** på GitHub – aldrig från `main` och aldrig via `git pull` – även om mappen är en git-mapp (`.git` lämnas orörd; filerna syns då som ändrade i git).

## 🖥️ Windows · macOS · Linux

Appen körs på alla tre. Installation/start på **macOS och Linux** (Python 3.10+):

```bash
./starta.sh              # första gången: skapar .venv i appmappen, installerar paket, startar
                         # (saknas Python frågar skriptet om den ska installeras — brew/apt/dnf/pacman/zypper/apk;
                         #  finns Python frågar det aldrig; utan terminal: LEDGEBORD_SVAR=j)
./starta.sh --forgrund   # starta i terminalen (visar fel direkt)
```

På macOS kan du också dubbelklicka på `STARTA_LEDGEBORD.command`. Allt installeras i `.venv` i appmappen
(inget i systemets Python, inget utanför mappen). Uppdateringen via "Sök ny version" rör aldrig `.venv`, och
kör du `./starta.sh` igen installeras nya paket bara om kraven ändrats. Debian/Ubuntu: `sudo apt install python3-venv`
(och vid Qt-fel `libxcb-cursor0`).

| Funktion | Windows | macOS | Linux |
|---|---|---|---|
| Uppgifter, backup, mail-brygga, kalender, uppdatering | ✅ | ✅ | ✅ |
| Stäng/minimera → systemfältet | ✅ tray | ✅ menyraden | ✅ om skrivbordet har ett systemfält (GNOME behöver tillägget *AppIndicator*); annars se nedan |
| Start med datorn | Startup-genväg med ikon | LaunchAgent | `~/.config/autostart` (med ikon) |
| "Visa över andra appar" (kryssruta) / på skrivbordet | Win32 (på skrivbordet) | Qt-flaggor (överst; "bakom" ignoreras av macOS) | Qt-flaggor (X11 fullt, Wayland beroende på skrivbord) |
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

## 🖥️ Visa över andra appar (kryssruta)

Kryssrutan **Visa över andra appar** finns i tray-menyn och när du högerklickar på fönstret:

- **Urkryssad (standard)** – Ledgebord ligger på skrivbordet (bakom ikonerna). Andra appar hamnar ovanpå, och Win+D kan inte gömma det.
- **Ikryssad** – Ledgebord ligger över alla andra appar hela tiden och går att skriva i direkt.

Valet sparas och gäller även efter omstart (snabbtangent: **Ctrl+Alt+T**). Är rutan urkryssad rättar appen själv till
om fönstret mot förmodan har blivit liggande överst.

**Ikryssat läge ligger alltid överst:** appen lägger sig överst igen **direkt när en annan app tar fokus** och **när ett
nytt fönster öppnas** (även appar som visar sig utan att ta fokus, Win11-appar som ”avtäcks” och fönster som återställs
från aktivitetsfältet). Windows meddelar händelserna; appen lägger sig överst ca 0,1 s senare och sedan en gång till efter
0,4 s, 1,2 s och 3 s — nya appar visar ofta sitt fönster i flera steg (startbild → huvudfönster). Dessutom var
**1,5:e sekund** som reserv. Det gäller också över andra fönster som själva är ”alltid överst”. Gömmer eller minimerar Windows widgeten (Win+D, skärmlås …)
visas den igen inom 1,5 s; fönster du själv gömt till tray lämnas ifred. Tray-lyftet (klick på ikonen) släpper
inte längre toppläget i det här läget, och påminnelsekortet ligger fortsatt överst.

**Dialogrutor ligger alltid framför tills du är klar:** frågor (t.ex. ”Flytta även förfallodatumet?”), datumväljaren,
inställningar, felmeddelanden och alla andra rutor som Ledgebord öppnar läggs överst — över Thunderbird, webbläsaren och
Ledgebords eget fönster (även om du öppnade dem från tray-menyn) — och stannar där tills du stänger dem. Efter varje
omläggning av huvudfönstret läggs de överst igen. Gäller i båda lägena. (Windows egna ”Öppna fil”-rutor styrs av Windows.)

## ⌨️ Styra listan med tangentbordet

Tryck **↓** (eller **↑**) – även när du står i inmatningsfältet – så markeras en uppgift med en färgad ram. Därefter:

| Tangent | Gör |
|---|---|
| ↑ / ↓ | föregående / nästa uppgift (↑ på den första går tillbaka till inmatningsfältet) |
| Home / End, PgUp / PgDn | första / sista, 5 steg |
| Mellanslag | markera klar |
| Ctrl+D | klar **och nästa** (se nedan) |
| E eller F2 | ändra titeln direkt på kortet (Enter sparar, Esc avbryter) |
| P | fäst / lossa |
| 1 / 2 / 3 / 0 | prioritet hög / normal / låg / ingen |
| Delete | ta bort (frågar först) |
| Esc | lämna markeringen (nästa Esc gömmer fönstret som förut) |

**Med musen:** dubbelklicka på en titel (eller högerklicka → *Byt namn*) så blir titeln en textruta på kortet. Enter eller klick utanför sparar, Esc avbryter. F2 fungerar även från musmarkeringen.

Skriver du ett vanligt tecken som inte är en kommandotangent hamnar det i inmatningsfältet. När en uppgift blir klar eller tas bort flyttas markeringen till nästa, så du kan bocka av en hel rad med mellanslag.

## ✅ Klar och nästa (Ctrl+D)

**Ctrl+D** bockar av den markerade uppgiften och flyttar markeringen direkt till nästa, så du kan jobba dig nedåt listan utan musen. Är det den sista går markeringen till föregående; finns inga fler uppgifter hamnar du i inmatningsfältet. Finns ingen markering än väljer första trycket bara den översta (så inget klarmarkeras av misstag) – tryck igen för att klarmarkera den. Fungerar även medan du står i inmatningsfältet, men inte i fokusläget (F3, där Enter gör samma sak) eller på andra flikar.

Tangenten kan bytas eller stängas av i `settings.json` (`shortcuts` → `done_next`; tom text = av). Ctrl+Enter är medvetet **inte** vald: den registrerar en ny uppgift i inmatningsfältet.

## 📆 Kalender – se vilka dagar som är tunga

Tredje fliken **📆 Kalender** visar en månad i taget (mån–sön, med veckonummer). Varje dag visar **antal uppgifter** med förfallodatum den dagen (även extra påminnelsedatum från importerade mail, märkta 🔔). Hur tung dagen är syns som en svag färgton och ett färgstreck i botten (1 · 2–3 · 4–5 · 6+ uppgifter) – men antalet står alltid som text, så färgen är aldrig det enda tecknet. Röda dagar har röd siffra, idag har accentram, och en förfluten dag med öppna uppgifter har röd ram.

* Klicka på en dag → dagens uppgifter listas under (hög prioritet först). **Dubbelklicka** på en uppgift → du hamnar i *Aktiva* med uppgiften markerad.
* **➕ Ny uppgift den här dagen** skapar en uppgift med dagen som förfallodatum.
* ◀ ▶ byter månad, **Idag** hoppar tillbaka. Kalendern bara visar – uppgifterna ändras i *Aktiva*. Klara uppgifter räknas inte.

## 📝 Fliken Anteckningar (egna anteckningar)

Fliken **📝 Anteckningar** (längst till höger) är till för egna anteckningar som inte hör till en viss uppgift — mötesanteckningar, idéer,
inköpslistor, telefonnummer. (Anteckningen *på en uppgift*, 📝 på kortet, finns kvar och beskrivs under [📝 Anteckningar](#-anteckningar).)

- **Skapa:** klicka **➕ Ny anteckning** (eller `Ctrl+N` i fliken). Skriv en rubrik (valfri) och texten.
- **Redigera:** klicka på en anteckning i listan. Texten får vara hur lång som helst (upp till 200 000 tecken) och ha flera rader.
- **Spara:** tryck **✓ Spara** (eller `Ctrl+S` / `Ctrl+Retur`) när du skrivit klart — anteckningen sparas och du kommer tillbaka till
  **listan**, där den ligger med rubrik och förhandsvisning. Klicka på den för att öppna den igen. En helt tom anteckning (ingen
  rubrik, ingen text) sparas inte utan städas bort.
- **Sparas även av sig själv:** ca 0,7 sekunder efter sista tangenttryckningen, när du går tillbaka (← eller `Esc`), byter flik, gömmer
  fönstret, avslutar eller uppdaterar appen. Glömmer du att trycka Spara försvinner alltså ingenting. Under texten ser du "✓ Sparat".
- **📌 Fäst** lägger anteckningen överst. Annars ligger den senast ändrade först.
- **🔍 Sök** filtrerar på rubrik och text. **📋 Kopiera** lägger rubrik + text i urklipp. **🗑 Radera** frågar först.
- **Var:** `notes.json` i samma datamapp som uppgifterna (`js\`, inne i appmappen). Filen skrivs säkert (temporärfil → byt ut), så en krasch
  mitt i en sparning förstör den inte. Är den ändå skadad flyttas den undan som `notes.json.skadad-<tid>` och en tom lista startar.
- **Backup:** anteckningarna ingår i både egna och automatiska backuper. Vid återställning *slås de ihop* med dem du har nu — ingen
  anteckning försvinner, och den senast ändrade versionen vinner.

## 💸 Delbetalningsplan (faktura i flera betalningar)

Högerklicka på fönstret → **💸 Delbetalningsplan…** (finns också i tray-menyn, och i högerklicksmenyn på en uppgift som **Delbetalningsplan från den här…** – då fylls rubriken i). Fyll i:

* **Rubrik / kund**, valfritt **totalbelopp** (och **handpenning** = del 1, resten delas lika), **antal delar** (2–60), **första förfallodag** och **intervall** (varje månad · varannan vecka · varje vecka · varannan/var tredje månad).
* **Helg / röd dag:** standard är *flytta till närmaste vardag* (lördag → fredag, söndag → måndag, röd dag → närmaste arbetsdag; annars *nästa* / *föregående* vardag eller *flytta inte*). Röda dagar kommer från appens egen helgkalender.
* Förhandsvisningen uppdateras medan du skriver. **Skapa** lägger N uppgifter, t.ex. `Limo Anders — del 1 av 3 (4 000 kr)`, med förfallodatum, vald prioritet och taggen `delbetalning`.

Månadssteg räknas från första datumet och dagen kläms till månadens längd (31 jan → 28 feb → 31 mar → 30 apr – dagen driver inte nedåt). Belopp räknas i ören; resten läggs på sista delen så summan alltid blir exakt. Belopp skrivs som `12 000`, `12000,50` eller `12.000,50`. Delbetalningsuppgifterna är vanliga uppgifter – ändra eller ta bort enskilda delar som vanligt.


## 📋 Jobbmallar (ett klick → alla uppgifter, ev. direkt till Google Calendar)

Högerklicka på fönstret (eller tray-menyn) → **📋 Ny uppgift från mall…**. Välj en mall, skriv kundens namn och **jobbdagen** — alla uppgifterna för jobbet skapas med förfallodatum räknat från jobbdagen. Förhandsvisningen visar exakt vad som skapas.

Två startmallar följer med: **Limojobb** (bekräfta bokning −3 dagar · utför jobbet · skicka faktura +1 · bevaka betalning +31) och **Bilstereo-installation**. De är bara förslag — ändra eller ta bort dem fritt.

**✏ Hantera mallar…** — skapa, duplicera, byt namn på och ta bort mallar. Varje steg har:

| Fält | Betydelse |
|---|---|
| Uppgift | Titeln. Skriv `{kund}` där kundens namn ska stå (utan platshållare läggs ” — kund” till; utan namn försvinner den). |
| Dagar från jobbdag | −3 = tre dagar före, 0 = jobbdagen, 30 = en månad efter. |
| Prioritet, Taggar, Belopp | Följer med till uppgiften (belopp räknas in i summorna). |
| Bara vardag | Hamnar dagen på helg eller röd dag flyttas den framåt till nästa vardag (bra för fakturadatum). |

**Automatisk export till Google Calendar:** i mallen finns valet *Skicka uppgifterna automatiskt till Google Calendar när mallen används*, och samma ruta finns när du skapar (du kan alltså ändra den varje gång). Är den ikryssad skickas just de nya uppgifterna till din kalender i bakgrunden direkt efter att de skapats — fönstret väntar aldrig på Google. Får du ett nätfel provas det igen efter 30 sekunder, 2 minuter och 10 minuter; sedan kommer en notis i tray. Är Google inte kopplat skapas uppgifterna ändå, rutan är avstängd och förklarar varför. Det är bara uppgifter från en mall där du själv kryssat i rutan som skickas — inget annat skickas av sig självt. De skickade uppgifterna följer sedan med om du ändrar datum. Kalender, färgkodning och ”klar”-stil är de du valt i ☁️ Google Calendar-dialogen.

Mallarna ligger i `mallar.json` i datamappen (inne i appmappen).

## 🏷 Taggfärger

Varje tagg har **en egen färg som är densamma på alla uppgifter** (förut avgjordes färgen av platsen i uppgiftens taggslista, så samma tagg kunde ha olika färg). Standardfärgen räknas ur taggnamnet (versaler spelar ingen roll) och är densamma på alla datorer.

* **Högerklicka på en tagg** → välj färg ur paletten, **🖌 Egen färg…** eller **↩ Standardfärg**. **🏷 Taggfärger…** (i menyn och i fönstermenyn) listar alla taggar med förhandsvisning.
* Valen sparas i `settings.json` (`tag_colors`) och slår igenom direkt i alla fönster.
* Chipet är heltäckande och texten svart eller vit – den som ger minst 4,5:1 kontrast – så även en egen färg är läsbar i både ljust och mörkt tema.

## 🌗 Temat följer Windows (live)

Standardtemat är **🖥️ Följ Windows**. Byter du Windows mellan ljust och mörkt läge byter Ledgebord **direkt** (inget omstart): appen lyssnar på Qt:s färgschema-signal och kontrollerar dessutom läget var 5:e sekund. **🌗 Auto** (ljust 07–19, mörkt kväll/natt) byts också live. Fast *Ljust* eller *Mörkt* påverkas inte. Tray-menyns rubrik visar vilket läge som gäller just nu.

## ⌨️ F1 – tangentöversikt

Tryck **F1** (i fönstret) så visas alla tangenter och snabbkommandon, **med dina egna inställningar** – t.ex. de globala snabbtangenter du bytt (Windows) och de du stängt av. Även under tray-menyn (**⌨️ Tangentöversikt…**) och i högerklicksmenyn på fönstret. F1 är reserverad och kan inte tilldelas något annat. Översikten kan kopieras som text.

## 🔗 Länkar och 📎 bilagor

- **Klistra in en webbadress** i inmatningsfältet (eller använd Ctrl+Alt+K / högerklicka → *🔗 Lägg till länk…*) – den blir en klickbar länk på kortet. Skriver du bara adressen blir uppgiftens titel sidans titel; skriver du text + adress behålls din text. Titeln hämtas i bakgrunden (ett anrop till just den sidan, högst 6 s). Stäng av under högerklick på fönstret → *🔗 Hämta sidtitlar för länkar*; då visas värdnamnet.
- **Bifoga fil** (högerklick på uppgiften → *📎 Bifoga fil…*): filen **kopieras in i appmappen** (`<datamapp>/attachments/<uppgift>/`, alltså `js\attachments` i Windows-installationen) – originalet rörs inte och inget skrivs utanför appmappen. Max 50 MB per fil.
- Klicka på chipen för att öppna (länk i webbläsaren, fil i sitt program – körbara filtyper som `.exe`/`.bat` frågar först). Högerklick: kopiera, visa i mappen, ta bort.
- Tar du bort en uppgift raderas dess bilagor också. **Bilagorna ingår inte i backup-zip:en** (bara uppgifterna) – kopiera mappen `attachments` om du vill ha dem med.

## 📜 Arkivet är historik som ligger kvar för alltid

Klara uppgifter hamnar i *Arkiverade* och **tas aldrig bort** – varken av appen, av „rensa arkiv“ (finns inte längre), av automatisk städning (finns ingen) eller av att återställa en äldre backup (nyare arkiverade uppgifter läggs då till i arkivet). Arkiverade uppgifter har ingen „Ta bort“-knapp. Du kan fortfarande markera en arkiverad uppgift som oklar, då blir den aktiv igen. Länkar/bilagor kan läggas till på arkiverade uppgifter men inte tas bort.

## 💰 Belopp

Högerklicka på en uppgift → **💰 Belopp…** och skriv t.ex. `4000`, `4 000 kr` eller `1 234,50` (tomt = ta bort). Beloppet
visas som en grön chip på kortet (klick = ändra) och sparas i ören, så summorna blir exakta. Uppgifterna som en
**delbetalningsplan** skapar får sina belopp automatiskt.

* **Summaraden** ovanför listan visar summan i den vy du ser: *kvar* (ej klarmarkerade), *försenat* (förfallodatum före
  idag), *denna månad* och *klarmarkerat*. Söker du eller klickar på en tagg följer summan med — skriv `limo` i sökfältet
  och se vad som ligger kvar att fakturera för limo. Raden syns bara när någon uppgift har belopp.
* **Klicka på summaraden** för fördelningen: per förfallomånad, per tagg (en uppgift med flera taggar räknas under varje
  tagg) och i arkivet *klart per månad* (efter klardatum).
* Beloppet följer med till kalenderposten ("Belopp: 4 000 kr") och PDF-checklistan. Arkiverade uppgifter behåller
  sitt belopp (och det går att ändra, arkivet raderas aldrig).

## 📝 Anteckningar

Högerklicka → **📝 Anteckning…** öppnar en ruta för längre text med flera rader (Ctrl+Retur sparar, upp till 50 000
tecken). Kortet visar en lila chip med första raden (`+` om det finns fler rader; hovra för hela texten, klicka för att
redigera). Sökfältet söker även i anteckningar. Anteckningen skickas med när uppgiften läggs i kalendern, och mail- och
urklippsuppgifter som redan har en anteckning visar den nu också.

## 📞 Klickbara telefonnummer och 📍 adresser

Appen letar i titeln och anteckningen och gör **klickbara telefonnummer och adresser** av det den hittar:

* **📞 Telefon** (070-123 45 67, 0701234567, 08-123 456 78, +46 70 123 45 67, +47 …): klick ger en meny — *Ring* (`tel:`),
  *Skicka SMS* eller *Kopiera numret*. Menyn finns eftersom `tel:` inte är kopplat till något program på alla datorer;
  *Kopiera* fungerar alltid.
* **📍 Adress** (`Storgatan 12 B, 111 22 Stockholm`, `Norra Hamngatan 4`): klick öppnar **Google Maps**; högerklick ger
  *Vägbeskrivning hit* och *Kopiera adressen*. En adress behöver gatunamn med stor bokstav och typisk ändelse (…gatan,
  …vägen, …gränd, …torget …) plus husnummer.
* Datum, belopp, organisations- och personnummer och OCR-/fakturanummer tolkas **inte** som telefonnummer. Högst 3 nummer
  och 2 adresser visas per kort. Ingenting skickas någonstans förrän du klickar.

## 🔠 Textstorlek (Kompakt · Normal · Stor)

Högerklicka på tray-ikonen → **Textstorlek**: *Kompakt* (mindre text, tätare kort, döljer raden "Tillagd" – du ser fler uppgifter), *Normal* (som förut) eller *Stor* (större text, luftigare). Valet sparas.

**Läsbarhet:** all text har minst 4,5:1 kontrast (WCAG AA) över normala bakgrunder (minst 3:1 vid lägsta transparens över extremt ljus/mörk bakgrund) och ingen text är mindre än 11 px (10 px vid Kompakt). Transparensen kan som mest sänkas till **70 %** (lägre skulle göra texten svårläst över ljusa bakgrunder); *Av* ger en helt ogenomskinlig panel. Testas av `tester/ui_readability_test.py`.

**Markera med mus eller tangentbord:** klicka på ett kort för att markera det – piltangenterna, `1`–`3`, mellanslag m.fl. verkar sedan på det kortet.

**Fönstrets plats efter uppdatering:** position och storlek skrivs ner till `js\settings.json` både före installationen och före omstarten (mappen `js\` rörs aldrig av uppdateringen), så fönstret kommer upp exakt där det stod.

## 📌 Visa över andra appar – snabbtangent

Standard **Ctrl+Alt+T**: lägger Ledgebord **över alla andra appar** (kryssrutan *Visa över andra appar* ikryssad). Tryck igen så går
fönstret tillbaka till det läge du hade förut (Bakom ikonerna / På skrivbordet). Fungerar var som helst i Windows,
även när en annan app är aktiv. Ändra eller stäng av: tray → **⌨️ Snabbkommandon → 📌 Alltid överst på/av…**.
(Vill du bara titta en stund: håll **Ctrl+Alt+V** – då visas fönstret så länge du håller tangenten.)
**Högerklicka på fönstret → Visa över andra appar** (kryssruta) – samma sak med musen, fungerar på alla system.
På macOS/Linux finns inga globala tangenter – kryssa i *Visa över andra appar* i tray-menyn.

## 🗕 Stäng och minimera → systemfältet

Knapparna **–** (minimera) och **✕** (stäng) uppe till höger, högerklicksmenyn (*Minimera till systemfältet*) och en
stäng-förfrågan (Alt+F4) **gömmer fönstret till tray**. Ledgebord fortsätter köra (påminnelser, mailbrygga,
snabbtangenter). Tillbaka: klicka på **tray-ikonen**, tray-menyn → *Visa*, snabbtangenten för ny uppgift eller starta
appen igen. **Avsluta** helt: tray-menyn → ❌ Avsluta. Win+D gömmer fortfarande inte fönstret — bara dessa knappar.
Finns ingen tray-ikon göms inget (så du aldrig blir utelåst) — i stället frågar Ledgebord om du vill **avsluta** (så går appen
alltid att stänga, även på ett skrivbord utan systemfält). Du kan också högerklicka i fönstret → **❌ Avsluta Ledgebord**.

**Start med datorn → i skärmkanten:** när Ledgebord startar med Windows (tray → *Starta med datorn*, kommandot får
flaggan `--autostart`) lägger sig fönstret i en skärmkant som en smal flik — tray-ikonen finns kvar — och fälls ut när
du för musen mot kanten (se *Dölj i skärmkanten*). Kanten är den du senast använde, annars den ytterkant som ligger
närmast fönstret (en kant som gränsar mot din andra skärm används aldrig). Går det inte att docka, eller är dockningen
avstängd, göms fönstret i tray i stället. Inget terminalfönster visas vid start.

**Startar alltid minimerad:** vid manuell start ligger Ledgebord direkt i systemfältet, utan fönster. Fönstret tvingas inte fram och göms så fort tray-ikonen finns.
Klicka på ikonen (eller använd snabbtangenten) när du vill se det. Vill du hellre se fönstret vid start: tray → ta
bort bocken vid *Starta minimerad i tray* (valet respekteras därefter). Äldre inställningar slås på en gång första
gången efter uppdateringen. Ligger fönstret i tray när en tyst uppdatering startar om appen kommer den nya versionen
också upp gömd.

**Inget terminalfönster:** `FORSTA_START.bat` (utan argument), `STARTA_HAR.bat` och `STARTA_DOLT.vbs` kör sökningen
efter Python, paketkontrollen och starten dolt — ingenting synligt öppnas. Ett synligt fönster visas bara när du måste
svara eller se något: Python saknas (J/N-frågan), PySide6/psutil saknas (första start på en ny dator, paketen
installeras) eller du själv kör `FORSTA_START.bat /full`. En `.bat` som dubbelklickas kan inte döljas av Windows och
blinkar till en bråkdels sekund — dubbelklicka `STARTA_DOLT.vbs` (eller använd skrivbordsgenvägen / *Starta med
datorn*) för att slippa även det.

**Fördröjd autostart:** med `--autostart` (alltså bara när appen startas med datorn) väntar Ledgebord **ca 45 s** innan
den laddar något, så att inloggning, skrivbord och nätverk hinner bli klara och datorn känns snabb. (Windows väntar
dessutom själv ~10 s med genvägar i Startup-mappen.) Har datorn redan kört i 20 min blir pausen bara 8 s. Manuell start
väntar aldrig. Under väntan finns ingen tray-ikon och inga snabbtangenter. Ändra tiden med miljövariabeln
`LEDGEBORD_AUTOSTART_DELAY=<sekunder>` (0 = ingen fördröjning).

**Startmätning:** varje start loggas (`⏱ Start 0.46 s: importer … → beroenden … → controller + fönster …`, långsammaste
steget anges) och sparas — de senaste 30 — i `data\startup_times.json` med tid per steg. Fördröjningen räknas inte
med. Själva starten blev snabbare: diagnostik/städning körs 2,5 s *efter* att fönstret kommit upp i stället för före,
och appen sover inte längre i onödan vid start utan splash (t.ex. under pythonw).

## 🔴 Röda dagar i veckan

Högst upp i fönstret (under titelraden) visas en **röd ruta** när veckan (mån–sön) har en röd dag på en **vardag** som
inte redan passerat: `🔴 Röd dag: Kristi himmelsfärdsdag torsdag 14 maj (om 3 dagar)` — *imorgon* respektive *idag* när
det är dags. Flera dagar radas upp (t.ex. nyårsafton + nyårsdagen). Lördags-/söndagshelger visas inte, och veckor utan
röd vardag har ingen ruta. **✕** döljer rutan för resten av dagen. Dagarna räknas ut i appen (`core/holidays_se.py`,
påsk enligt gregorianska algoritmen, inget nätverk): nyårsdagen, trettondedag jul, långfredag, annandag påsk, första maj,
Kristi himmelsfärd, nationaldagen, juldagen, annandag jul — samt midsommarafton, julafton och nyårsafton, som inte är
lagstadgade men lediga för de flesta (märkta *ledig för de flesta*).

## 📅 Datum i importerade mail → påminnelser

Står det ett datum eller en månad i mailet läggs en påminnelse på det datumet — popup-kortet på skärmen med **✓ Klar** /
**Skjut 1 h**, samma som för förfallodatum (från 08:00, var 30:e minut tills du klickar):

* igenkänns: `15/11`, `15/11-2026`, `2026-11-15`, `15.11.2026`, `15 november`, `15:e nov`, `november 15` och enbart
  månadsnamn (`i november`, `december`);
* månadsnamn utan dag (`i november`, `december`) → månadens **första vardag** (måndag–fredag, ej röd dag; t.ex. december
  2026 → tis 1/12, januari 2027 → mån 4/1). Är månaden redan igång och den dagen passerad: idag;
* ignoreras: `november 2/3` och `1 av 3` (delbetalning, inte 2 mars), klockslag, belopp, citerade rader (`>`) och datum som
  redan passerat;
* alla datum sparas på uppgiften (`remind_dates`) och raden ur mailet visas på kortet (*📅 idag: Betalning 2 · 15/11 …*);
* har uppgiften inget förfallodatum får den det tidigaste datumet — väljer du själv ett datum i Thunderbird vinner ditt, och
  mailets datum påminner ändå;
* **✓ Klar** på kortet betyder "det här datumet är klart" — ett datum i taget, äldsta först (inget obesvarat datum sväljs
  i smyg). Uppgiften väntar sedan på nästa datum (*Klar → nästa 15/12*) och bockas av först när inga datum återstår. Bockar
  du av den i listan är den förstås klar direkt.

## 🔔 Påminnelser med knappar + siffra på ikonen

När en uppgift är **försenad eller förfaller idag** visas ett litet kort nere till höger (tar inte fokus, så du kan
skriva vidare i en annan app). Varje rad har knapparna **✓ Klar** (bockar av uppgiften) och **Skjut 1 h**
(uppgiften döljs en timme och påminner igen när tiden gått). Dessutom **Öppna listan** och **Stäng**.
Kortet försvinner av sig självt efter ca 30 s (står kvar medan musen är över det) och flera påminnelser slås ihop.
Av/på: tray → påminnelser.

**När kommer påminnelserna?** Har uppgiften ett datum (t.ex. `261030` = 2026-10-30) visas kortet **på förfallodagens
morgon kl 08:00** och sedan **var 30:e minut tills du markerat uppgiften som klar** (✓ Klar på kortet eller i listan).
Har du angett ett klockslag kommer dessutom en påminnelse exakt då, och kortet fortsätter efteråt. Nattro: inga
påminnelser från 22:00 (de fortsätter nästa morgon). Startas appen senare på dagen kommer första påminnelsen direkt.
Försenade uppgifter påminns på samma sätt varje dag tills de är klara. *Skjut 1 h* pausar uppgiften en timme.

**Datum utan streck:** `ÅÅMMDD` (`261030`) och `ÅÅÅÅMMDD` (`20261030`) funkar i fönstrets inmatningsfält, i
snabbuppgiften (Ctrl+Alt+N) och i datumrutan (”Sätt datum…”) — även med klockslag, `!prio` och `#tagg`:
`Fakturera Andreas 261030 15:00 !hög #jobb`. Klockslaget kan skrivas `15:00`, `15.30`, `kl 15`, `klockan 15` eller bara
`15` direkt efter datumet (`261030 15`, `imorgon 15`) — ett ensamt tal utan datum räknas aldrig som tid. Ett vanligt nummer (fakturanummer o.d.) tolkas inte som datum om det inte
är ett riktigt datum i rimligt år.

**Ctrl+Alt+N** öppnar dialogen för ny uppgift **överst över alla andra fönster** med fokus direkt. Fönstret flyttas
inte när uppgiften lagts till (positionen behålls) — listan lyfts bara en stund över andra appar. Ligger fönstret i
tray förblir det där.

**Tray-ikonen** visar antalet försenade + dagens uppgifter som en siffra (röd om något är försenat, annars orange).
Inga uppgifter att bevaka → ren ikon. En liten **röd prick uppe till höger** betyder att nya *fel* (FEL/KRASCH, inte
varningar) har loggats i `loggar\fel.log` sedan du senast öppnade felloggen; menyraden blir då
”🧯 Öppna felloggen — N nya fel” och tooltipen nämner dem. Öppnar du felloggen släcks pricken
(`loggar\fel_seen.txt` kommer ihåg när). Första gången (innan filen finns) räknas bara fel som kommer *efter* det.

**🔔 Datum från mail på uppgiften:** har appen hittat datum i ett importerat mail visas ett märke `🔔 3` på uppgiften;
hovra för datumen (`Påminner: 2/11, 15/11, 1/12` + raden ur mailet). Klicka märket, eller högerklicka →
**🔔 Påminnelsedatum…**, för att avmarkera datum som inte ska påminna eller lägga till egna. Tray-notisen vid import
(och dialogen vid manuell import av .eml) nämner datumen. Tom lista = inga extra påminnelser (förfallodatumet
påverkas inte).

## 🎨 Namn och ikon

Appen heter **Ledgebord** (tidigare TaskBord). Ikonen – en indigo ruta med en gul *kantlist* och ett bockat
uppgiftskort – ligger i `icon\ledgebord.ico` och används överallt: fönster, tray, aktivitetsfält, Alt+Tab,
genvägen som `INSTALLERA.bat` skapar, autostart-genvägen och README-bilderna. Appen ger sig själv ett eget
*AppUserModelID* (annars visar Windows Pythons ikon för `pythonw.exe`).

* **Logotyp som vektor (för tryck):** ligger som filer på **GitHub-releasen** (under *Assets*), inte i appens mapp eller i
  nedladdningen av programmet: `Ledgebord-logotyp.zip` (alla logotyper som **SVG** + PNG) samt `ledgebord-logo.svg` och
  `ledgebord-ikon.svg` direkt. Ikon, liggande och stående logotyp finns i färg, vit (för mörk botten) och svart
  (enfärgat tryck). SVG:erna är rena former och toningar (inga filter, inga bilder, ingen typsnittsfil): ordet
  "Ledgebord" är omritat till banor (Inter ExtraBold, SIL OFL 1.1), så filerna ser likadana ut överallt och kan
  skickas direkt till tryckeriet. Färger: indigo `#4F46E5`, violett `#7C3AED`, mörk indigo `#2A2370`, gul `#FBBF24`/`#F59E0B`.
  För CMYK-tryck: öppna SVG:n i Inkscape/Illustrator och konvertera till tryckeriets färgprofil.
* **Allt byggs från en ritning:** `icon/ledgebord_svg.py` (ren text, inga paket). `python icon/bygg_ikoner.py` (kräver
  `pip install pillow resvg-py`, bara för den som ändrar ikonen) skriver om `icon/ledgebord.ico` + `.png`, bygger tryckfilerna i `logotyp/` (mappen ligger i `.gitignore`)
  (varje storlek ritas direkt från vektorn; 16–64 px använder en grövre variant som syns i aktivitetsfältet),
  Thunderbird-tilläggets `icon-16…128.png` och README-bilderna `docs/img/ikon.png` och `docs/img/banner.png`.
* **Reservikon:** saknas ikonfilen eller går den inte att läsa ritar appen en liknande ikon själv
  (`core/icon_art.py`, bara standardbiblioteket) till `data/ledgebord.ico` — aldrig en Python-ikon.
* **Aktivitetshanteraren:** i *Processer* och *Detaljer* kommer ikonen från programfilen `pythonw.exe`, som Windows
  visar med Pythons ikon. Det går bara att ändra med en egen `.exe` — appens fönster, tray, aktivitetsfält och
  Autostart-fliken använder Ledgebord-ikonen.
* **Autostart med rätt ikon:** *Starta med datorn* skapar en genväg `Ledgebord.lnk` i Startup-mappen med Ledgebords ikon
  (inte en registerpost/`.bat` som pekar på `pythonw.exe` – de visar Pythons ikon i Aktivitetshanterarens *Autostart*-flik
  och i Inställningar → Appar → Autostart). De gamla posterna tas bort automatiskt vid nästa start; går det inte att
  skapa genvägen används registret som reserv. Dessutom skapas `Ledgebord.lnk` i själva appmappen – starta därifrån i
  stället för från `main.pyw` (som Windows visar med Pythons filikon).
* **Autostart följer med:** posten "Starta med datorn" flyttas till nya namnet vid första start (den gamla
  tas bort först när den nya är skapad). Gamla backupfiler (`taskbord-…zip`) hittas och rensas som förut.
* **Oförändrat med flit** (så att inget går sönder): HTTP-huvudet `X-TaskBord-Token`, Thunderbird-tilläggets id,
  Google-token (kopplingen behålls), miljövariablerna `TASKBORD_*` och GitHub-repots namn `Tokke2/TaskBord`
  (uppdateringar hämtas därifrån tills repot döps om på GitHub).
* **Thunderbird:** tillägget heter nu *Ledgebord* (v1.2.0) – installera `Ledgebord-Thunderbird.xpi` en gång
  till (samma id, så det ersätter det gamla). Appen påminner om det.

## 1️⃣ Bara en instans – starta igen = öppna den som kör

Ledgebord kan bara köra **en gång åt gången** (namngivet lås + fillås i datamappen + koll av mail-bryggan). Startar du
appen igen – genväg, `STARTA_HAR.bat`, Thunderbird-tillägget eller dubbelklick på `main.pyw` – startas ingen ny kopia:
den nya starten säger till den som kör, och **den öppnar sitt fönster** (även om det låg i tray eller var dockat), ett
kort tray-meddelande bekräftar. Är den första kopian fortfarande på väg upp (fönstren byggs några sekunder) väntar den
nya starten upp till 15 s och försöker igen, så att du aldrig får en ruta i stället för fönstret. Den fördröjda
Windows-starten (`--autostart`) som kommer efter att du redan startat själv avslutar sig tyst utan att flytta fönstret.
Först om den körande kopian inte svarar alls (t.ex. en mycket gammal version) visas en ruta som pekar på tray-ikonen.

## ↔ Dockning vid skärmkant

**Enklast: högerklicka fönstret → ↔ Dölj i skärmkanten → välj ◀ vänster, ▶ höger eller ▲ övre kanten.** Fönstret
flyttas till kanten och gömmer sig när musen lämnar det. Du kan också **dra fönstret mot kanten och släppa** – då
dockas det av sig självt. (*✖ Visa som vanligt* avslutar dockningen.)

**Fliken i kanten.** När fönstret är gömt blir en liten **flik** kvar i skärmkanten (22 px tjock, mitt för fönstret):
*Ledgebord · 6* (antal aktiva uppgifter) – eller röd **"3 försenade"** om något har passerat sitt datum. Fliken ligger
alltid överst och är det enda som visar fönstret: **håll musen på den en kort stund, eller klicka** så glider fönstret
fram (längs kanten ▲ ◀ ▶). Dra musen från fönstret så gömmer det sig igen.
* **Andra program stör inte längre.** Förut räckte det att musen nuddade kanten – t.ex. Thunderbirds eller webbläsarens
  flikrad och rullister – för att fönstret skulle åka fram, och ett gömt fönster kunde hamna bakom dem. Nu räknas bara
  fliken, och så länge fönstret är dockat läggs det **över andra program** (samma som *Visa över andra appar*). Släpper du
  dockningen återställs ditt tidigare val automatiskt (om du inte ändrat det själv under tiden).
* Är fönstret nerskickat till tray syns ingen flik. Hög kontrast-läget ger en svart flik med vit kant.
* Fungerar för **övre**, vänster och höger kant (vänster/höger får lodrät text). Ett högt fönster kan också gömmas uppåt.
* Gömmer sig inte medan en dialog/meny är öppen, du drar i fönstret, redigerar en titel eller har text i
  inmatningsfältet. Håller du **Ctrl+Alt+V** glider det fram och stannar så länge tangenten hålls.
* Fönstret visas inte om du håller en musknapp nedtryckt (så att dra-och-släpp i andra program inte råkar trigga det).
* Dra bort fönstret från kanten (eller *Centrera*) så är det vanligt igen. Stäng av helt:
  **högerklicka → ↔ Dölj i skärmkanten → Dockning på** (urkryssad).
* Med flera skärmar dockas bara **yttre** kanter (aldrig kanten mot grannskärmen — väljer du den får du en förklaring). Underkanten används inte.
* Det *synliga* läget sparas alltid (aldrig det utglidna), och dockningen återupptas efter omstart/uppdatering.

## 📋 Lägg till från urklipp

Standard **Ctrl+Alt+K**: markera text i *vilket program som helst* och tryck tangenten — texten
blir en uppgift direkt (första raden = rubrik, resten = anteckning; en lång första rad kortas och
hela texten hamnar i anteckningen). Appen kopierar markeringen åt dig, släpper de tangenter du
håller, och **återställer det som låg i urklippet**. Är inget markerat används det som redan ligger
i urklippet. En tray-notis visar vad som skapades. Ändra/stäng av: tray → **⌨️ Snabbkommandon →
📋 Lägg till från urklipp…**. Utan snabbtangent: tray → *📋 Ny uppgift från urklipp*.

## 🧯 Felloggen — alla fel på ett ställe (`loggar\fel.log`)

**Alla loggar ligger i en egen undermapp i appmappen: `loggar\`** (`todo_app.log`, `fel.log`, `update_watchdog.log`,
`window_failure_report.txt` m.fl.). Loggar som tidigare låg i `data\` flyttas dit automatiskt vid start (finns samma fil
redan läggs den gamla texten först). Uppgifter, inställningar och backuper ligger kvar där de var. `loggar\` rörs aldrig av
uppdateringar och ingår inte i git.

Felen låg tidigare utspridda (`todo_app.log` med tusentals rader, `update_watchdog.log` från uppdateringsväktaren,
`window_failure_report.txt`, äldre dagsfiler). Nu samlas allt som gått fel i **en** fil — börja alltid där:

* tray → **🧯 Öppna felloggen** (öppnas i Anteckningar), eller öppna `loggar\fel.log` direkt;
* **live:** varje varning/fel/krasch från *alla* moduler skrivs direkt, med tid, modul (fil:rad) och stacktrace;
  likadana fel i följd samlas ("ovanstående upprepades N gånger");
* **import:** 10 s efter start och varje gång du öppnar filen hämtas fel ur de andra loggarna — nya felrader ur
  `update_watchdog.log` (återställning, appen avslutades …), nödrapporten `window_failure_report.txt` och, första gången,
  ERROR/CRITICAL ur `todo_app.log` + de roterade dagsfilerna (rader märkta `IMPORT`). Samma rad tas aldrig två gånger
  (`loggar\fel_import.json` håller reda på var vi är);
* token och mailadresser maskas; inget skrivs utanför appmappen;
* den ingår också i **felrapporten** (ZIP) som `fel.log`.

### 🗄️ Arkiv — gårdagens loggar zippas, felen ligger kvar tills de är åtgärdade

* **Loggar från dagar före idag arkiveras** (inget raderas): vid start, och sedan var 5:e minut så att en app som står
  öppen över midnatt också arkiverar igår. Varje dag blir en zip: `loggar\arkiv\ÅÅÅÅ-MM-DD.zip` med `todo_app.log`,
  `update_watchdog.log` (den dagens rader) och `fel-varningar.log` (den dagens VARNINGAR ur `fel.log`). Zipparna sparas
  för alltid och rörs inte av uppdateringar. Den gamla raderingen av loggar efter 3 dagar är borttagen.
* **Felposter (FEL, KRASCH och importerade fel) arkiveras inte per dag.** De ligger kvar i `loggar\fel.log` — även när de
  är flera dagar gamla — tills du markerar dem som åtgärdade: tray → **✅ Markera fel som åtgärdade — N öppna**
  (grå när det inte finns några). Då flyttas de (med stacktrace) till `loggar\arkiv\fel_atgardade.log` och `fel.log`
  visar "Inga fel loggade". Kommer samma fel tillbaka efter markeringen loggas det på nytt.
* **Appen städar själv bort fel som är åtgärdade** (vid start, när du öppnar felloggen och var 5:e minut). Två fall:
  felet är **rättat i koden** (appen känner igen det, t.ex. Qt:s infoblock som förut loggades som KRASCH), eller
  **samma fel har inte kommit tillbaka på 14 dagar**. De flyttas (med stacktrace) till `loggar\\arkiv\\fel_atgardade.log`
  under rubriken *Automatiskt åtgärdade* — inget raderas. Fel som nyligen inträffat eller upprepats ligger kvar tills
  du själv markerar dem.
* `fel.log` får inte längre någon `.1`-rotation (den kunde slänga felposter). Blir filen ändå större än ca 6 MB flyttas de
  *äldsta* felposterna till `loggar\arkiv\fel_overflod.log` — ingen post går förlorad.

## 🩺 Felrapport

tray → **🩺 Skapa felrapport…** packar en ZIP i `data\felrapporter\` (de 10 senaste behålls) och öppnar
mappen: version/Python/Windows, ett fingeravtryck per programfil (visar exakt vilken kod som körs),
loggens sista rader och inställningarna. Token och mailadresser maskas, och **dina uppgifter,
Google-koppling och mailinnehåll tas aldrig med**. Loggen kan ändå nämna uppgiftstitlar — titta
igenom den innan du skickar den.

## 💾 Backup av uppgifter

Högerklicka på fönstret (eller tray-ikonen) → **💾 Backup av uppgifter…**

* **Säkerhetskopiera nu** — sparar alla aktiva och arkiverade uppgifter (och fliken 📝 Anteckningar) i en ZIP-fil i
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
**[GOOGLE_CALENDAR.md](../GOOGLE_CALENDAR.md)** beskriver varje klick.

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
| `ui/extras_dialogs.py`, `ui/widget_parts/extras.py` | anteckningsdialogen, beloppsöversikten och mixinen för belopp, anteckningar och klickbara kontaktuppgifter (logiken ligger Qt-fri i `core/amounts.py` och `core/contacts.py`) |
| `ui/widget_base.py` | konstanter, teman, hjälpfunktioner, logg/felhantering, PWM, `parse_natural_input` |
| `ui/widget_atoms.py` | `EditableLabel`, `TagChip`, `LinkChip`, `PriorityBadge`, `PriorityDot`, `DueDateLabel`, `GlassFrame` |
| `ui/calendar_view.py`, `ui/payment_plan_dialog.py`, `ui/tag_colors_dialog.py` | kalenderfliken, delbetalningsdialogen, taggfärgsdialogen (logiken ligger Qt-fri i `core/calendar_grid.py`, `core/payment_plan.py`, `core/tag_colors.py`) |
| `ui/widget_parts/*.py` | metoderna, en mixin per område: `lifecycle`, `task_menu`, `task_actions`, `render`, `task_card`, `theme`, `keys_position`, `focus_timers`, `exports`, `window_ops`, `keynav`, `qt_events`, `links_attach` |

Ändra textstorleken via `set_ui_font_scale()` (i `widget_base`), inte genom att skriva till `_UI_FONT_SCALE`.
`tester/widget_split_test.py` vaktar delningen (alla metoder kvar, inga namn saknas, ingen metod i två mixins).

Regler som testerna vaktar (`tester/structure_test.py`): alla moduler går att importera, ingen metod
finns i två mixins (annars vinner en tyst), inga odefinierade namn, sökvägar byggs från `SCRIPT_DIR`
(aldrig från `__file__` i `app/`). `tester/app_boot_test.py` startar hela appen offscreen och läser loggen.

## 🗣 Naturliga datum (fre 14, om 3 dagar, nästa mån)

Överallt där du skriver ett datum för hand förstår Ledgebord vanlig svenska — i fältet för ny uppgift, i hotkey-rutan och i **📅 → ✍️ Skriv datum…**:

| Skriv | Betyder |
|---|---|
| `fre 14` | närmaste fredag som också är den 14:e (finns ingen inom tre månader används närmaste den 14:e) |
| `fredag` · `fre` · `på fredag` | närmaste fredag (idag räknas) |
| `nästa mån` · `nästa fredag` | närmaste måndag/fredag **efter** idag |
| `nästa vecka` · `nästa månad` | måndag nästa vecka · den 1:a nästa månad |
| `om 3 dagar` · `om en vecka` · `om 2 månader` | räknat från idag (siffror eller ord: en, två, tre …) |
| `15 nov` · `15 november 2026` · `vecka 47` | datum med månadsnamn · måndag i vecka 47 |
| `slutet av månaden` · `14` | månadens sista dag · närmaste den 14:e |
| `imorgon` · `övermorgon` · `261030` · `2026-10-30` · `15/3` | som förut |

Klockslag går också: `imorgon kl 15`, `fre 20 9:30`. I uppgiftsfältet kan allt blandas: `Ring kund nästa mån kl 9 !hög #jobb`.
Inne i en titel räknas bara tydliga uttryck — ett ensamt `mån` eller `14` i en titel blir aldrig ett datum, och `fredag 15` betyder som förut fredag kl 15.
Datum som redan passerat (`15 nov` i december) tolkas som nästa år. Samma uttryck funkar efter `start` (`start nästa mån`, `start om en vecka`).

## 🌙 Tysta timmar och påminnelseljud

Påminnelserna tystnar på natten (och om du vill på helgerna) — det som väntar kommer som första påminnelse när tystnaden är slut.

Högerklicka tray-ikonen → **🌙 Tysta timmar och ljud**:

| Val | Vad det gör |
|---|---|
| **Tysta timmar på** | Standard: tyst 22:00–08:00 (som förut). Av = påminnelser dygnet runt. |
| **Tyst från / till** | Välj när natten börjar (18:00–00:00) och slutar (05:00–10:00). |
| **Tysta lördag och söndag** | Inga påminnelser på helgen. Måndag morgon kommer det som väntar. |
| **🔊 Ljud vid påminnelse** | Inget ljud · 🔔 Pling · 🛎 Klocka · 🎵 Mjukt (standard). Du hör ljudet direkt när du väljer det. |

Ljudet spelas när påminnelsekortet visas, aldrig under tysta timmar. Ljuden skapas av appen själv och sparas i datamappen (`js\sounds\`). Inställningarna sparas och följer med vid uppdatering och backup av inställningar.
Obs: en uppgift med klockslag före tysta timmars slut (t.ex. kl 06 när tystnaden är till 08) påminns först när tystnaden är slut.

## 👋 Välkomstguide (första start)

Första gången du startar Ledgebord på en ny dator öppnas en kort **👋 Välkomstguide** (sju tips: skriv och Enter, Ctrl+Alt+N, högerklick, påminnelser, ✕ = gömmer bara, mail, F1) och en **exempeluppgift** läggs i listan. Bocka av den eller ta bort den när du vill — den kommer inte tillbaka.

* Guiden visas **en enda gång**, bara när fönstret syns (inte vid tyst autostart) och aldrig för dig som redan har uppgifter (t.ex. efter en uppdatering).
* Den finns alltid kvar: högerklicka fönstret eller tray-ikonen → **👋 Välkomstguide**.
* Är listan tom visar den en förklarande vy (hur du skriver en uppgift, Ctrl+Alt+N, högerklick) i stället för bara "Inga uppgifter".

### 🔄 Ändra datum → händelsen flyttas med

Har du redan skickat en uppgift till Google Calendar följer händelsen med när du ändrar datum — du behöver inte skicka om den.

*Exempel: ”Vindrutebyte idag”, kunden är sjuk → högerklicka → **📅 Förfallodatum** (eller **▶ Startdatum**) → *Nästa vecka*. Händelsen i kalendern flyttas av sig själv och en liten notis i tray visar nya dagen.*

* **Gäller bara det du själv skickat.** En uppgift som aldrig skickats till kalendern skapas inte av sig själv — du väljer fortfarande vad som skickas.
* **Bara datumet ändras.** Rubrik, beskrivning och färg som du ändrat inne i Google lämnas orörda.
* **Startdatum efter förfallodatum:** flyttar du *start* till nästa vecka men förfallodatumet ligger kvar frågar Ledgebord om förfallodatumet ska följa med — annars visar kalendern fortfarande den gamla dagen.
* **Inget nät?** Ledgebord provar igen efter 30 s, 2 min och 10 min, och sedan nästa gång programmet startar. Appen väntar aldrig på Google.
* **Borttagen i Google?** Då skapas den inte på nytt — kopplingen släpps bara och du får en notis.
* Alla flyttar syns i **Historik** (”Datum flyttades automatiskt till …”).
* **Stäng av:** tray-menyn → ☁️ Google Calendar → *Flytta händelsen när datum ändras*.

## 🎨 Teman och utseende (+ ♿ tillgänglighet)

Högerklicka fönstret eller tray-ikonen → **🎨 Teman och utseende…**. Allt slår igenom direkt medan du drar och sparas.

| Val | Vad det gör |
|---|---|
| **Färgtema** | Standard · Hav · Skog · Solnedgång · Grafit · Midnatt · Lavendel · Sand · Hög kontrast. Byter panelens och kortens färgton — texten är alltid minst 4,5:1 mot bakgrunden. |
| **Typsnitt** | Standard (Segoe UI) · Lättläst (Verdana) · Rundad (Trebuchet) · Klassisk (Calibri) · Serif (Georgia). Byter typsnitt i hela fönstret; saknas ett typsnitt används närmaste reserv. |
| **Glasstyrka** | 0–30 % genomskinlighet. Mer glas släpper igenom skrivbordet, men panelen blir aldrig mer genomskinlig än 70 % så texten förblir läsbar. |
| **Bakgrundsdjup** | 0–60 %: mörkare bakgrund i mörkt tema, ljusare i ljust — mer kontrast mot texten. |
| **Hög kontrast** | Svart/vitt, heltäckande ytor, tjocka kanter, tydliga röda/gula varningsfärger och text med minst 7:1 (WCAG AAA). Följer ljust/mörkt tema. |
| **Skarp bild** | På som standard: full hinting på texten (glyferna läggs på hela bildpunkter) och ingen mjuk accentglöd över panelens överdel. |
| **Solid panel** | Ingen genomskinlighet alls = skarpast text. Genomskinliga fönster får grånyans-kantutjämning i stället för Windows ClearType, och skrivbordet skimrar igenom texten — välj solid panel om texten känns grumlig. |
| **Textstorlek** | 80–200 % (se nedan). |
| **↺ Återställ utseendet** | Tillbaka till standard. |

Temat följer fortfarande ljust/mörkt/auto/Följ Windows — färgtemat läggs ovanpå.

**Bredd och ikoner:** standardfönstret är nu 420×700 (förut 340×648), så titelraden, de fyra flikarna och inmatningsfältet ryms utan att kapas. Tray → *Fönsterstorlek* har Smal (340), Standard (420), Bred (560) och Extra bred (720) — eget val av storlek ändras aldrig. Ett fönster som fortfarande har den gamla standardstorleken görs bredare en gång vid första starten efter uppdateringen. Knapparna i titelraden (uppdatera, lås, minimera, stäng) är ritade vektorikoner i textfärgen, så de är skarpa, följer temat och ser likadana ut på alla datorer.

**Anpassar sig till skärmen:** tray → *Fönsterstorlek* → *🖥 Anpassa till skärmen* väljer en storlek efter den skärm fönstret ligger på (ca 24 % av bredden, 400–560 px, och ca 90 % av höjden) avrundad nedåt till **hela bildpunkter** — vid 125 % eller 175 % skalning ger udda storlekar annars en halv bildpunkts kant och suddig text. Om en skärm kopplas ur, byter upplösning eller skalning flyttas och krymps fönstret automatiskt så att det alltid ryms (ett fönster som ligger gömt i skärmkanten eller i tray rörs inte). Appen använder dessutom Qts exakta skalfaktor (125 % = 1,25) i stället för en avrundad.

### ♿ Tillgänglighet
* **Textstorlek upp till 200 %:** reglaget i temadialogen eller **Ctrl + Plus / Ctrl + Minus**, **Ctrl + 0** = 100 %. Ligger ovanpå Kompakt/Normal/Stor.
* **Tydlig fokusring:** allt som har tangentbordsfokus får en 2–3 px ring (gul på mörkt, mörkblå på ljust). **Tab / Skift+Tab** flyttar mellan knappar och fält — även fönstrets ✕, – och uppdateringsknappar.
* **Skärmläsare:** varje knapp och fält har ett namn, och varje uppgiftskort läses som en mening (”Uppgift: Ring Anna. Hög prioritet. Förfaller 2026-11-20. Ej klar. Taggar: jobb.”).
* **Tangentbord överallt:** pilar/Space/E/P/1–3/Delete i listan, **Ctrl + 1–4** byter flik, **Meny-tangenten eller Skift + F10** öppnar menyn för den markerade uppgiften. F1 listar allt.

## 💖 Stöd projektet

Ledgebord är gratis och utan reklam. Donationer är helt frivilliga och går till utveckling och underhåll. Appen fungerar exakt lika bra utan donation.

Allt görs i appen — det finns ingen egen donationssida. Öppna den egna dialogrutan **💖 Stöd Ledgebord…** direkt under
hjälpen (**⌨️ Tangentöversikt**) i högerklicksmenyn och i tray-menyn, eller med knappen längst ner i F1-hjälpen.
Dialogen har en kort text om varför, belopp-genvägar (25/50/100/200 kr) och eget belopp (1–99 999 kr), och tre kort:
**Swish** har en QR-kod enligt Swishs officiella format (numret visas aldrig som text — skanna med Swish-appen; koden ritas om
när du ändrar belopp). **PayPal** (med valt belopp) och **Ko-fi** (valfritt belopp, engångs eller månadsvis) är bara knappar — de
har ingen QR-kod. Knapparna öppnar betaltjänsten i webbläsaren.
**Mottagarna är låsta:** de står bara inbyggda i koden (`core/donate_info.py`), finns ingen inställning eller datafil
för dem, och en kontrollsumma kontrolleras varje gång dialogen öppnas — är filen ändrad stängs betalknapparna av och
dialogen varnar. Uppdateringen från releasen lägger tillbaka originalfilen. (Ledgebord är öppen källkod, så den som
själv ändrar koden kan förstås göra en egen version — låset skyddar mot oavsiktliga och tysta ändringar.)
QR-koden ritas lokalt med paketet `segno` (ingen tjänst på nätet anlitas). Ägaren ändrar mottagare i `core/donate_info.py`
och kör filen för att få en ny kontrollsumma.

## 📄 Licens

MIT (filen `LICENSE`): fri användning **privat och kommersiellt**, ändring och vidaredelning är tillåten så länge
copyright- och licenstexten behålls. Ingen garanti.

---

Copyright © Rickard Längkvist, 2025–2026. Licens: MIT (se `LICENSE`).
