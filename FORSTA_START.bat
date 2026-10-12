@echo off
REM ============================================================
REM  TaskBord - FORSTA START / UPPDATERING (Windows)
REM  Ingen version ar hardkodad:
REM   1. Laser senaste stabila Python-version fran python.org
REM   2. Anvander nyaste installerade Python 3.10+ som finns
REM   3. Installerar Python om det saknas, eller uppdaterar om
REM      installerad version ar aldre an senaste
REM   4. Installerar/uppgraderar alla paket (requirements.txt
REM      och requirements-optional.txt) till senaste version
REM   5. Startar TaskBord
REM
REM  Anvandning:
REM    FORSTA_START.bat        full installation/uppdatering
REM    FORSTA_START.bat /snabb startar direkt med installerad Python
REM                            (installerar bara om Python saknas)
REM  Inga adminrattigheter behovs.
REM ============================================================
chcp 65001 >nul
setlocal EnableDelayedExpansion
title TaskBord - Forsta start

set "APPDIR=%~dp0"
set "APP=%APPDIR%main.pyw"
set "SNABB=0"
if /i "%~1"=="/snabb" set "SNABB=1"
set "PY="
set "PYNUM=0"
set "PYVER="
set "LATNUM=0"

if not exist "%APP%" goto :no_app
if not exist "%APPDIR%requirements.txt" goto :no_req

echo ==================================================
echo   TaskBord - FORSTA START / UPPDATERING
echo   Mapp: %APPDIR%
echo ==================================================
echo.

REM ----- Snabblage: starta med det som redan finns -----
call :find_python
if "%SNABB%"=="1" if defined PY goto :start_app
if "%SNABB%"=="1" echo Ingen Python hittad - kor full installation forst.

REM ----- Senaste stabila version fran python.org -----
call :get_latest
if defined PYVER echo [1/5] Senaste stabila Python enligt python.org: %PYVER%
if not defined PYVER echo [1/5] Kunde inte lasa senaste version fran python.org.

REM ----- Behover vi installera/uppdatera Python? -----
set "NEED=0"
if not defined PY set "NEED=1"
if defined PYVER if !PYNUM! LSS !LATNUM! set "NEED=1"
if "!NEED!"=="0" goto :python_ok
if not defined PYVER goto :python_missing

echo [2/5] Installerar Python %PYVER% (saknas eller ar aldre) ...
call :install_python
call :find_python
if defined PY goto :python_ok
goto :fail_python

:python_missing
echo [FEL] Ingen Python hittad och senaste version kunde inte hamtas.
goto :fail_python

:python_ok
echo [2/5] Anvander Python: %PY%
if "%SNABB%"=="1" goto :start_app

echo [3/5] Uppgraderar pip ...
"%PY%" -m pip install --upgrade pip --disable-pip-version-check -q
if errorlevel 1 echo        [INFO] pip kunde inte uppgraderas - fortsatter med befintlig version.

echo [4/5] Installerar/uppgraderar alla paket fran requirements.txt (kan ta nagra minuter) ...
"%PY%" -m pip install --upgrade -r "%APPDIR%requirements.txt" --disable-pip-version-check
if errorlevel 1 goto :fail_pip

if exist "%APPDIR%requirements-optional.txt" "%PY%" -m pip install --upgrade -r "%APPDIR%requirements-optional.txt" --disable-pip-version-check
if errorlevel 1 echo        [VARNING] Valfria tillagg kunde inte installeras. Kernfunktionerna fungerar anda.

echo        Kontrollerar att kravda paket gar att importera ...
"%PY%" -c "import PySide6, psutil" >nul 2>&1
if errorlevel 1 goto :fail_verify

:start_app
echo [5/5] Startar TaskBord ...
set "PYW=%PY%"
for %%F in ("%PY%") do if exist "%%~dpFpythonw.exe" set "PYW=%%~dpFpythonw.exe"
start "" "%PYW%" "%APP%"
exit /b 0


REM ------------------------------------------------------------
REM  Hitta den NYASTE installerade Python 3.10+.
REM  Satter PY (sokvag) och PYNUM (minor*1000 + micro, t.ex. 15000).
REM ------------------------------------------------------------
:find_python
set "PY="
set "PYNUM=0"
set "CAND="
for %%X in (python.exe) do set "CAND=%%~$PATH:X"
if defined CAND call :check_py "%CAND%"
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do call :check_py "%%~fD\python.exe"
for /d %%D in ("%ProgramFiles%\Python3*") do call :check_py "%%~fD\python.exe"
exit /b 0

:check_py
if not exist "%~1" exit /b 0
set "CMAJ="
set "CMIN="
set "CMIC="
for /f "tokens=1,2,3" %%A in ('"%~1" -c "import sys;print(sys.version_info[0],sys.version_info[1],sys.version_info[2])" 2^>nul') do (set "CMAJ=%%A" & set "CMIN=%%B" & set "CMIC=%%C")
if not defined CMIC exit /b 0
if not "%CMAJ%"=="3" exit /b 0
set /a "CNUM=%CMIN%*1000+%CMIC%"
if %CNUM% LSS 10000 exit /b 0
if %CNUM% LEQ %PYNUM% exit /b 0
set "PY=%~1"
set "PYNUM=%CNUM%"
exit /b 0


REM ------------------------------------------------------------
REM  Hamta senaste stabila version fran python.org (ingen reserv-
REM  version). Satter PYVER (t.ex. 3.15.0) och LATNUM.
REM ------------------------------------------------------------
:get_latest
set "PYVER="
set "LATNUM=0"
for /f "delims=" %%V in ('powershell -NoProfile -ExecutionPolicy Bypass -File "%APPDIR%hamta_python_version.ps1"') do set "PYVER=%%V"
if not defined PYVER exit /b 0
for /f "tokens=1,2,3 delims=." %%A in ("%PYVER%") do set /a "LATNUM=%%B*1000+%%C"
exit /b 0


REM ------------------------------------------------------------
REM  Installera senaste stabila Python per anvandare (utan admin).
REM  1) Officiell installer fran python.org
REM  2) Reserv: winget, med paket-id harlett av PYVER
REM ------------------------------------------------------------
:install_python
set "PYURL=https://www.python.org/ftp/python/%PYVER%/python-%PYVER%-amd64.exe"
set "PYSETUP=%TEMP%\python-%PYVER%-amd64-setup.exe"
echo        Laddar ner Python %PYVER% fran python.org ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri '%PYURL%' -OutFile '%PYSETUP%'"
if not exist "%PYSETUP%" goto :winget_python

echo        Installerar Python %PYVER% (aktuell anvandare, lagger till i PATH) ...
"%PYSETUP%" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_launcher=1
if errorlevel 1 goto :winget_python
exit /b 0

:winget_python
for /f "tokens=1,2 delims=." %%A in ("%PYVER%") do set "WINGET_ID=Python.Python.%%A.%%B"
echo        Forsoker med winget (%WINGET_ID%) ...
where winget.exe >nul 2>&1
if errorlevel 1 exit /b 1
winget install -e --id %WINGET_ID% --silent --accept-package-agreements --accept-source-agreements
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
echo [FEL] Kunde inte installera eller hitta Python automatiskt.
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
