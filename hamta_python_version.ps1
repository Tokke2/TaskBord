# Ledgebord - hamtar senaste stabila Python-version for Windows fran python.org.
# Skriver ut versionsnumret (t.ex. 3.15.0) eller ingenting vid fel.
# Anvands av FORSTA_START.bat.
$ErrorActionPreference = 'Stop'
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $html = (Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/downloads/windows/').Content
    if ($html -match 'Latest Python 3 Release[^0-9]{0,120}(\d+\.\d+\.\d+)') {
        Write-Output $matches[1]
    }
} catch {
    # Tyst: batchfilen använder en känd reservversion om detta misslyckas.
}
