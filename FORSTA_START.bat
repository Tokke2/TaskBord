@echo off
REM ============================================================
REM  TaskBord - FORSTA START (for datorer utan Python)
REM  1. Hittar Python 3.10+ eller installerar senaste stabila
REM  2. Installerar alla paket fran requirements.txt
REM  3. Installerar valfria tillagg (requirements-optional.txt)
REM  4. Startar TaskBord
REM  Kor denna fil i TaskBord-mappen. Inga adminrattigheter behovs.
REM ============================================================
chcp 65001 >nul
setlocal EnableDelayedExpansion
title TaskBord - Forsta start

set "APPDIR=%~dp0"
set "APP=%APPDIR%main.pyw"
set "PY="
set "PYW="
set "CAND="
set "PYVER="

echo ==================================================
echo   TaskBord - FORSTA START
echo   Installerar Python (senaste stabila) och alla paket.
echo   Mapp: %APPDIR%
echo ==================================================
echo.

if not exist "%APP%" goto :no_app
if not exist "%APPDIR%requirements.txt" goto :no_req

call :find_python
if defined PY goto :python_ok

echo [1/4] Python saknas eller ar for gammalt - installerar senaste stabila ...
call :install_python
call :find_python
if defined PY goto :python_ok
goto :fail_python

:python_ok
echo [1/4] Python hittades: %PY%
"%PY%" -m pip install --upgrade pip --disable-pip-version-check -q
if errorlevel 1 echo        [INFO] Kunde inte uppgradera pip - fortsatter med befintlig version.

echo [2/4] Installerar alla paket fran requirements.txt (kan ta nagra minuter) ...
"%PY%" -m pip install -r "%APPDIR%requirements.txt" --disable-pip-version-check
if errorlevel 1 goto :fail_pip

echo [3/4] Installerar valfria tillagg (PDF-export, Outlook .msg-import) ...
if exist "%APPDIR%requirements-optional.txt" "%PY%" -m pip install -r "%APPDIR%requirements-optional.txt" --disable-pip-version-check
if errorlevel 1 echo        [VARNING] Valfria tillagg kunde inte installeras. Kernfunktionerna fungerar anda.

echo        Kontrollerar att kravda paket gar att importera ...
"%PY%" -c "import PySide6, psutil" >nul 2>&1
if errorlevel 1 goto :fail_verify

echo [4/4] Startar TaskBord ...
set "PYW=%PY%"
for %%F in ("%PY%") do if exist "%%~dpFpythonw.exe" set "PYW=%%~dpFpythonw.exe"
start "" "%PYW%" "%APP%"
echo.
echo KLART! TaskBord startar. Nasta gang kan du anvanda STARTA_HAR.bat.
exit /b 0


REM ------------------------------------------------------------
REM  Hitta Python 3.10 eller nyare. Satter PY om nagot hittas.
REM ------------------------------------------------------------
:find_python
set "PY="
set "CAND="
for %%X in (python.exe) do set "CAND=%%~$PATH:X"
if defined CAND call :check_py "%CAND%"
if defined PY exit /b 0
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do call :check_py "%%~fD\python.exe"
if defined PY exit /b 0
for /d %%D in ("%ProgramFiles%\Python3*") do call :check_py "%%~fD\python.exe"
exit /b 0

:check_py
if not exist "%~1" exit /b 0
"%~1" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 exit /b 0
if not defined PY set "PY=%~1"
exit /b 0


REM ------------------------------------------------------------
REM  Installera senaste stabila Python (per anvandare, utan admin).
REM  1) Hamta versionsnummer fran python.org (reserv: 3.15.0)
REM  2) Ladda ner och kor officiell installer
REM  3) Reserv: winget
REM ------------------------------------------------------------
:install_python
set "PYVER="
for /f "delims=" %%V in ('powershell -NoProfile -ExecutionPolicy Bypass -File "%APPDIR%hamta_python_version.ps1"') do set "PYVER=%%V"
if not defined PYVER set "PYVER=3.15.0"
echo        Senaste stabila Python: %PYVER%

set "PYURL=https://www.python.org/ftp/python/%PYVER%/python-%PYVER%-amd64.exe"
set "PYSETUP=%TEMP%\python-%PYVER%-amd64-setup.exe"
echo        Laddar ner fran python.org ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri '%PYURL%' -OutFile '%PYSETUP%'"
if not exist "%PYSETUP%" goto :winget_python

echo        Installerar Python %PYVER% (for aktuell anvandare, lagger till i PATH) ...
"%PYSETUP%" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_launcher=1
if errorlevel 1 goto :winget_python
exit /b 0

:winget_python
echo        Forsoker med winget ...
where winget.exe >nul 2>&1
if errorlevel 1 exit /b 1
winget install -e --id Python.Python.3.15 --silent --accept-package-agreements --accept-source-agreements
exit /b %errorlevel%


REM ------------------------------------------------------------
:no_app
echo [FEL] Hittar inte main.pyw i:
echo        %APPDIR%
goto :fail

:no_req
echo [FEL] Hittar inte requirements.txt i:
echo        %APPDIR%
goto :fail

:fail_python
echo.
echo [FEL] Kunde inte installera Python automatiskt.
echo Installera manuellt fran https://www.python.org/downloads/
echo (kryssa i "Add python.exe to PATH") och kor denna fil igen.
goto :fail

:fail_pip
echo.
echo [FEL] Kunde inte installera paketen.
echo Kontrollera internetanslutningen och kor denna fil igen.
goto :fail

:fail_verify
echo.
echo [FEL] Paketen installerades men PySide6 eller psutil gar inte att importera.
echo Forsok manuellt:  "%PY%" -m pip install -r requirements.txt
goto :fail

:fail
echo.
pause
exit /b 1
