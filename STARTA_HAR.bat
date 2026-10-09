@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title TaskBord - Portabel start
echo ==================================================
echo   TaskBord - PORTABEL START
echo   Plats: %~dp0
echo   (Fungerar overallt: USB, skrivbord, valfri mapp)
echo ==================================================
echo.

set "APP=%~dp0main.pyw"

REM ===== Steg 1: Python finns redan? =====
where pythonw.exe >nul 2>&1
if %errorlevel%==0 (
    echo [1/4] Python hittades - startar appen...
    start "" pythonw.exe "%APP%"
    exit /b 0
)
where python.exe >nul 2>&1
if %errorlevel%==0 (
    echo [1/4] Python hittades - startar appen...
    start "" python.exe "%APP%"
    exit /b 0
)

echo [1/4] Python saknas - installerar senaste stabila Python...
echo        (Detta kan ta nagra minuter. Ange JA om Windows fragar.)
echo.

REM ===== Steg 2: Installera Python =====
REM Metod A: winget (inbyggt i Windows 10/11)
where winget.exe >nul 2>&1
if %errorlevel%==0 (
    echo [2/4] Installerar via winget ...
    winget install --id Python.Python.3.13 --silent --accept-package-agreements --accept-source-agreements
    if !errorlevel!==0 goto :found
)

REM Metod B: Ladda ner installer fran python.org (om winget saknas/misslyckas)
echo [2/4] Hundladdar installer fran python.org ...
powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol='Tls12'; try { Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.13.1/python-3.13.1-amd64.exe' -OutFile \"$env:TEMP\py-setup.exe\" } catch { exit 1 }"
if not exist "%TEMP%\py-setup.exe" goto :fail
echo        Installerar (tyst, for aktuell anvandare) ...
start /wait "" "%TEMP%\py-setup.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0

:found
REM ===== Steg 3: Hitta python i standard-installationsmappen =====
REM (PATH uppdateras ej i denna session - sok direkt)
set "PYW="
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python*") do set "PYDIR=%%D"
if exist "!PYDIR!\pythonw.exe" set "PYW=!PYDIR!\pythonw.exe"
if not defined PYW (
    for /d %%D in ("C:\Program Files\Python*") do set "PYDIR=%%D"
    if exist "!PYDIR!\pythonw.exe" set "PYW=!PYDIR!\pythonw.exe"
)
if not defined PYW goto :fail

echo [3/4] Python klar - installerar PySide6 + orjson ...
"!PYDIR!\python.exe" -m pip install --quiet --disable-pip-version-check PySide6 orjson

echo [4/4] Startar DesktopTodoPy ...
start "" "!PYW!" "%APP%"
echo.
echo KLAR! Appen startar (forsta gangen kan det ta en stund).
exit /b 0

:fail
echo.
echo ============================================================
echo [FEL] Kunde inte installera Python automatiskt.
echo Installera manuellt fran https://www.python.org/downloads/
echo (markera "Add Python to PATH"), kors sedan:
echo    pip install PySide6 orjson
echo ...och starta denna fil igen.
echo ============================================================
pause
exit /b 1
