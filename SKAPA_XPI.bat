@echo off
chcp 65001 >nul
title Ledgebord - bygg Thunderbird-tillagg (xpi)
echo ==================================================
echo   Ledgebord - SKAPA THUNDERBIRD-TILLAGG
echo   Kalla: %~dp0
echo ==================================================
echo.

where python.exe >nul 2>&1
if %errorlevel%==0 goto :withpython

REM Fallback: PowerShell-version (om python saknas)
echo [INFO] Python hittades inte - anvander PowerShell i stallet...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$src = Join-Path '%~dp0' 'thunderbird-tillagg';" ^
  "$out = Join-Path '%~dp0' 'Ledgebord-Thunderbird.xpi';" ^
  "if (Test-Path $out) { Remove-Item $out -Force };" ^
  "$files = Get-ChildItem -Path $src -Recurse -File | Where-Object { $_.FullName -notmatch '\\tester\\' -and $_.FullName -notmatch '__pycache__' };" ^
  "Add-Type -AssemblyName System.IO.Compression.FileSystem;" ^
  "$zip = [System.IO.Compression.ZipFile]::Open($out, 'Create');" ^
  "foreach ($f in $files) { $rel = $f.FullName.Substring($src.Length + 1).Replace('\\','/'); [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $f.FullName, $rel) | Out-Null };" ^
  "$zip.Dispose();" ^
  "Write-Host ('  Klar: ' + $out + ' (' + $files.Count + ' filer)')"
if not exist "%~dp0Ledgebord-Thunderbird.xpi" goto :fail
goto :done

:withpython
echo [1/2] Bygger Ledgebord-Thunderbird.xpi ...
python.exe "%~dp0skapa_xpi.py"
if not exist "%~dp0Ledgebord-Thunderbird.xpi" goto :fail

:done
echo.
echo ==================================================
echo  KLART! Filen ligger i: %~dp0Ledgebord-Thunderbird.xpi
echo.
echo  Installera i Thunderbird:
echo    1. Verktyg - Tillagg och teman
echo    2. Kugghjulet (verktygsmenyn) - "Installera tillagg fran fil..."
echo    3. Valj Ledgebord-Thunderbird.xpi
echo    4. Tillaggets Installningar - klistra in JSON fran Ledgebord:
echo       tray-ikonen - "E-post ^& Thunderbird" -
echo       "Kopiera installningar for Thunderbird"
echo ==================================================
echo.
pause
exit /b 0

:fail
echo.
echo [FEL] Kunde inte skapa Ledgebord-Thunderbird.xpi.
echo Tips: kor "python skapa_xpi.py" i denna mapp och las felmeddelandet.
echo.
pause
exit /b 1
