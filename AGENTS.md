# Branchpolicy för Ledgebord

- Arbeta, committa och publicera ändringar enbart på den aktiva arbetsbranchen. Byt inte till, skriv inte till och slå inte ihop ändringar i `main`.
- Den konsoliderade uppdateringsbranchen är `arena/5502c203-taskbord`. Appuppdateraren använder exakt den branchen, med arkiv bundet till dess commit. Ingen fallback till `main`, GitHubs standardbranch eller `releases/latest`.
- Appuppdateraren får aldrig skriva över en Git-arbetskopia. Använd Git på rätt arbetsbranch för att uppdatera källkodscheckouts.
- Varje push till uppdateringsbranchen ska publicera en release för branchens aktuella commit och markera den som **Latest**. `.github/workflows/release.yml` sköter detta. Återanvänd eller flytta inte befintliga taggar. Appen avgör om den behöver uppdateras genom att jämföra programfilernas innehåll, inte versionsetiketten.
