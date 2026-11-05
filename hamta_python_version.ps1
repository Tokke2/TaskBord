# Ledgebord - hamtar Python-version fran python.org.
#   Utan argument:   senaste stabila Python 3-version (t.ex. 3.15.0)  - anvands nar Python SAKNAS.
#   -Serie 3.14:     senaste patch-version i just den serien som har en Windows-installer (t.ex. 3.14.9)
#                    - anvands nar Python redan finns: uppdatera inom samma serie, aldrig en ny serie bredvid.
# Skriver ut versionsnumret eller ingenting vid fel. Anvands av FORSTA_START.bat.
param([string]$Serie = '')
$ErrorActionPreference = 'Stop'
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    if ($Serie) {
        if ($Serie -notmatch '^\d+\.\d+$') { exit 0 }
        $dir = (Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/ftp/python/').Content
        $found = @()
        foreach ($m in [regex]::Matches($dir, 'href="(' + [regex]::Escape($Serie) + '\.(\d+))/"')) {
            $found += [pscustomobject]@{ V = $m.Groups[1].Value; N = [int]$m.Groups[2].Value }
        }
        foreach ($v in ($found | Sort-Object N -Descending)) {
            $url = 'https://www.python.org/ftp/python/' + $v.V + '/python-' + $v.V + '-amd64.exe'
            try {
                $r = Invoke-WebRequest -UseBasicParsing -Method Head -Uri $url
                if ($r.StatusCode -eq 200) { Write-Output $v.V; break }
            } catch { }
        }
    } else {
        $html = (Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/downloads/windows/').Content
        if ($html -match 'Latest Python 3 Release[^0-9]{0,120}(\d+\.\d+\.\d+)') {
            Write-Output $matches[1]
        }
    }
} catch {
    # Tyst: batchfilen fortsatter med installerad Python om detta misslyckas.
}
