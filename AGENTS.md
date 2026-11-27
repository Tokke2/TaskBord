# Hårda regler för TaskBord / Ledgebord

Läs den här filen innan arbete påbörjas i en ny kodsession. Reglerna gäller TaskBord/Ledgebord; i andra appar ska motsvarande `AGENTS.md` anpassas till respektive app och repo.

- När användaren märker en ny instruktion med **`- hård regel`** eller **`regel`**, skriv in den bestående regeln i appens `AGENTS.md`, committa och pusha den på den tillåtna arbetsbranchen. Kontrollera därefter Latest. Vid konflikt eller oklar innebörd: be om förtydligande, skriv inte över befintliga regler i tysthet.

## Git, release och appuppdatering

- Det ska finnas **en enda branch** på GitHub, `arena/5502c203-taskbord`, också standardbranch. Det gäller även efter chattbyte: verifiera aktuell branch och fjärrrepots standardbranch innan ändringar. Arbeta, committa och pusha bara där. Skapa inga sidobrancher. Arbeta aldrig mot `main`, inte heller vid uppdateringar.
- **Merga aldrig och skapa eller använd aldrig en pull request (PR) för att leverera ändringar.** Använd direkta commits på den aktiva branchen och pusha utan force-push. Om branchläget avviker, stoppa och rapportera det i stället för att försöka slå ihop historik eller radera andra refs från en session som inte får ändra dem.
- **Varje push ska publicera en uppdaterad GitHub-release för branchens aktuella commit och markera den som Latest.** `.github/workflows/release.yml` ansvarar för publiceringen. Flytta eller återanvänd aldrig en tidigare tagg. Efter push: verifiera att releasen är Latest och pekar på rätt commit; rapportera om publiceringen misslyckas.
- Appuppdateraren ska **jämföra programfilernas innehåll**, aldrig avgöra om installation behövs utifrån versionsnummer eller releaseetikett. Hämta endast från uppdateringsbranchen, med arkiv bundet till en verifierad commit. Ingen fallback till `main`, standardbranch eller `releases/latest`. `Latest` speglar branchen och hjälper äldre uppdaterare att migrera. Appen får inte skriva över Git-arbetskopior.
- **Produktkrav för automatisk uppdatering:** Kontrollera dagligen kl. 00:00 lokal tid när Ledgebord körs. Installera bara om filjämförelsen visar skillnader och övriga säkerhetsvillkor är uppfyllda. Vid pågående arbete eller blockerad installation ska uppdateringen vänta tills det är säkert. Detta är ett krav, inte en bekräftelse på att schemat är implementerat.
- Uppdateringar får inte störa pågående arbete. Förbered återställning före filändringar. Radera endast den aktuella uppdateringsbackupen efter bekräftad lyckad start. Behåll backupen vid fel eller utebliven bekräftelse och lämna användarens vanliga backuper orörda.
- Behåll två separata loggar: dagens kompletta driftlogg i `loggar/todo_app.log` och samlad felsökning i `loggar/fel.log`. Arkivera gårdagens driftlogg när dagen byts och rensa daterade arkiv efter sju dagar. Rensningen får inte ändra dagens driftlogg eller öppna fel.
- Felloggen ska behålla alla aktiva fel över omstarter. Ta bort en post från den aktiva listan när felet verifierats som åtgärdat eller användaren uttryckligen markerar det som löst. Enbart tiden som gått är inte bevis för en åtgärd. Vanlig logghistorik behöver inte skrivas om när en felpost löses.

## Kompatibilitet och verifiering

- Inga tysta beroende- eller gränssnittsbrott. Informera i förväg om en ändring bryter befintliga integrationer, dataformat eller arbetsflöden. Dokumentera konsekvenser, migrering och verifiering.
- Kör relevanta tester före leverans. För uppdateraren ska även blockering, bevarade användardata och återställning vid fel testas. Beskriv vilka kontroller som passerat och vilka som inte kunnat köras. Påstå inte att Windows, hög DPI eller externa tjänster har verifierats när de inte har testats.
- **REQ-K4:** kravtexten finns inte i det här repot. Be om den exakta lydelsen innan kravet tillämpas eller markeras som uppfyllt; gissa inte innebörden.

## Bestående produktkrav

- Anpassa bredd och maximal användbar starthöjd efter aktuell skärm och arbetsyta. Prioritera synligt innehåll och minimera rullning utan att klippa bort kontroller. Utvärdera layout, kolumner, typsnitt och ikoner vid olika DPI och skärmstorlekar.
- Vid normal start: starta alltid minimerat. Start, skanning och tillhörande bakgrundsjobb får inte öppna något terminalfönster.
- Vid öppning från minimerat läge ska fönstret utnyttja skärmens tillgängliga höjd och anpassa bredden utan att täcka aktivitetsfältet. Håll text, bilder, ikoner och kolumner skarpa och läsbara även vid olika skalning på flera skärmar.
- Daterade händelser: Ledgebord påminner lokalt dagen innan och ungefär var 30:e minut under tillåtna tider på händelsedagen. Upprepningen upphör när påminnelsen stängs av för uppgiften, uppgiften blir klar eller dagens påminnelseperiod tar slut. Google Kalenders aviseringar styrs separat.
- Där appen har kolumner: ge användaren möjlighet att sortera och flytta dem. Gör inte om en vy till tabell bara för att uppfylla den här regeln.
- Håll gränssnittet snabbt och energisnålt, särskilt när appen är dold. Mät innan du påstår att minne, hastighet eller energiförbrukning har förbättrats.
- Använd samma skarpa logotyp och ikonfamilj i appen, tillägget och dokumentationen. Behåll redigerbara SVG-original för tryck.
- **Profiler:** Endast appar som faktiskt använder profiler ska ha en egen underflik **Profiler** i inställningarna, där användaren kan skapa profiler. Lägg inte till en tom profilflik eller ett profilsystem bara för att uppfylla denna regel.
- Återställ valet av ruta i projektskaparen från ttk-versionen endast i appar som faktiskt hade valet, och först efter att det gamla beteendet verifierats. Dokumentation av önskemålet betyder inte att det är implementerat.

## Förslagslistor i chatt

- Efter vart tionde chattmeddelande, räknat över användarens och assistentens meddelanden i chatten, skriv **10 nya, konkreta förslag direkt i chatten** (inte bara i en fil eller länk). Återanvänd inte tidigare idéer eller omskrivningar. Använd tillgänglig historik och påstå inte att förslag i separata chattar är kontrollerade om historiken saknas.
- När användaren ber om **25 nya produktförslag**, skriv alla 25 direkt i chatten. Undersök vad användare efterfrågar och vilka konkurrenter som saknar funktionen; skilj på verifierade fynd och hypoteser. Blanda inte ihop denna lista med tiomeddelanderegeln.
- Märk konkurrensluckor och påstådd efterfrågan som hypoteser tills de har verifierats. Skilj på förslag, beslutade krav och färdiga funktioner.
