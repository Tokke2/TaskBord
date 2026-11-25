# Hårda regler för TaskBord / Ledgebord

Läs den här filen innan arbete påbörjas i en ny kodsession.

## Git, release och appuppdatering

- Det ska finnas **en enda branch** på GitHub, `arena/5502c203-taskbord`, också standardbranch. Arbeta, committa och pusha bara där. Skapa inga sidobrancher. Arbeta aldrig mot `main`, inte heller vid uppdateringar.
- **Merga aldrig.** Använd direkta commits på den aktiva branchen och pusha utan force-push. Om branchläget avviker, stoppa och rapportera det i stället för att försöka slå ihop historik eller radera andra refs från en session som inte får ändra dem.
- **Varje push ska publicera en uppdaterad GitHub-release för branchens aktuella commit och markera den som Latest.** `.github/workflows/release.yml` ansvarar för publiceringen. Flytta eller återanvänd aldrig en tidigare tagg. Efter push: verifiera att releasen är Latest och pekar på rätt commit; rapportera om publiceringen misslyckas.
- Appuppdateraren ska **jämföra programfilernas innehåll**, aldrig avgöra om installation behövs utifrån versionsnummer eller releaseetikett. Hämta endast från uppdateringsbranchen, med arkiv bundet till en verifierad commit. Ingen fallback till `main`, standardbranch eller `releases/latest`. `Latest` speglar branchen och hjälper äldre uppdaterare att migrera. Appen får inte skriva över Git-arbetskopior.
- Uppdateringar får inte störa pågående arbete. Förbered återställning före filändringar. Radera endast den aktuella uppdateringsbackupen efter bekräftad lyckad start. Behåll backupen vid fel eller utebliven bekräftelse och lämna användarens vanliga backuper orörda.
- Rensa daterade loggarkiv efter sju dagar. Ändra inte dagens driftlogg eller öppna felsökningsposter vid rensningen.

## Kompatibilitet och verifiering

- Inga tysta beroende- eller gränssnittsbrott. Informera i förväg om en ändring bryter befintliga integrationer, dataformat eller arbetsflöden. Dokumentera konsekvenser, migrering och verifiering.
- Kör relevanta tester före leverans. För uppdateraren ska även blockering, bevarade användardata och återställning vid fel testas. Beskriv vilka kontroller som passerat och vilka som inte kunnat köras. Påstå inte att Windows, hög DPI eller externa tjänster har verifierats när de inte har testats.
- **REQ-K4:** kravtexten finns inte i det här repot. Be om den exakta lydelsen innan kravet tillämpas eller markeras som uppfyllt; gissa inte innebörden.

## Bestående produktkrav

- Anpassa bredd och maximal användbar starthöjd efter aktuell skärm och arbetsyta. Prioritera synligt innehåll och minimera rullning utan att klippa bort kontroller. Utvärdera layout, kolumner, typsnitt och ikoner vid olika DPI och skärmstorlekar.
- Håll gränssnittet snabbt och energisnålt, särskilt när appen är dold. Mät innan du påstår att minne, hastighet eller energiförbrukning har förbättrats.
- Använd samma skarpa logotyp och ikonfamilj i appen, tillägget och dokumentationen. Behåll redigerbara SVG-original för tryck.
- Produktönskemål att följa upp: egen underflik **Profiler** i inställningarna; återställ valet av ruta i projektskaparen från ttk-versionen efter att beteendet verifierats. Dokumentation av önskemålen betyder inte att de är implementerade.

## Förslagslistor i chatt

- Efter vart tionde chattmeddelande, räknat över användarens och assistentens meddelanden i chatten, visa **10 nya, konkreta förslag**. Återanvänd inte tidigare idéer eller omskrivningar. Använd tillgänglig historik och påstå inte att förslag i separata chattar är kontrollerade om historiken saknas.
- Märk konkurrensluckor och påstådd efterfrågan som hypoteser tills de har verifierats. Skilj på förslag, beslutade krav och färdiga funktioner.
