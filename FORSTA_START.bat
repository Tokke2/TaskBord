@echo off
REM ============================================================
REM  Ledgebord - FORSTA START / UPPDATERING (Windows)
REM  Ingen version ar hardkodad:
REM   1. Kollar FORST om Python 3.10+ finns installerad
REM   2. Finns den: anvands den som den ar. Python UPPDATERAS INTE har
REM      (ingen patch-uppdatering, ingen ny version) - det sker inte vid
REM      start och inte i veckounderhallet.
REM   3. Saknas Python: installerar senaste stabila fran python.org
REM   4. Installerar/uppgraderar alla paket (requirements.txt
REM      och requirements-optional.txt) till senaste version
REM   5. Startar Ledgebord
REM
REM  Anvandning:
REM    FORSTA_START.bat        full installation/uppdatering
REM    FORSTA_START.bat /snabb startar direkt med installerad Python
REM                            (installerar bara om Python saknas). En
REM                            gang i veckan (manda 08:00, annars forsta
REM                            start efter det) uppdateras Pythons tillagg
REM                            (paketen, core\pip_update.py)
REM    FORSTA_START.bat /snabb /vecka   (appen startar om for veckounderhall)
REM  Inga adminrattigheter behovs.
REM ============================================================
chcp 65001 >nul
setlocal EnableDelayedExpansion
title Ledgebord - Forsta start

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
echo   Ledgebord - FORSTA START / UPPDATERING
echo   Mapp: %APPDIR%
echo ==================================================
echo.

REM ----- Snabblage: starta med det som redan finns -----
call :find_python
if "%SNABB%"=="1" if defined PY goto :snabb_paket
REM Snabbstart utan Python: oppna en synlig ruta for full installation (annars hanger den dolda)
if "%SNABB%"=="1" (start "Ledgebord - Installation" "%~f0" & exit /b 1)

REM ----- Finns Python? Anvand den som den ar (ingen uppdatering av Python). Saknas den? Installera senaste stabila. -----
set "PSARG="
if not defined PY goto :python_not_found
echo [1/5] Python finns redan: %PY% - Python uppdateras inte, den installerade anvands.
goto :python_ok

REM -- Python saknas: installera senaste stabila --
:python_not_found
call :get_latest
if not defined PYVER goto :python_missing
echo [1/5] Python saknas. Senaste stabila enligt python.org: %PYVER%
echo [2/5] Installerar Python %PYVER% ...
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
if exist "%APPDIR%core\pip_update.py" "%PY%" "%APPDIR%core\pip_update.py" --mark --quiet
goto :start_app

:snabb_paket
REM VECKOUNDERHALL (helst manda 08:00, inte vid varje start): Pythons tillagg (paket). Python uppdateras inte. Bara om veckans
REM underhall inte ar gjort och Ledgebord inte kor. Anropad med /vecka (appen har startat om for det) kors det direkt
REM efter att appen avslutats. Tyst, loggas i loggar\pip_uppdatering.log, blockerar aldrig starten.
if not exist "%APPDIR%core\pip_update.py" goto :start_app
if /i "%~2"=="/vecka" goto :vecko_kor
"%PY%" "%APPDIR%core\pip_update.py" --due --quiet
if errorlevel 10 goto :vecko_kor
goto :start_app

:vecko_kor
"%PY%" "%APPDIR%core\pip_update.py" --wait-exit --quiet
if errorlevel 1 goto :start_app
"%PY%" "%APPDIR%core\pip_update.py" --run --quiet
goto :start_app


:start_app
echo [5/5] Startar Ledgebord ...
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
REM  Hamta version fran python.org (ingen reservversion). PSARG tom =
REM  senaste stabila (anvands bara nar Python saknas).
REM  Satter PYVER (t.ex. 3.14.9) och LATNUM (minor*1000 + micro).
REM ------------------------------------------------------------
:get_latest
set "PYVER="
set "LATNUM=0"
for /f "delims=" %%V in ('powershell -NoProfile -ExecutionPolicy Bypass -File "%APPDIR%hamta_python_version.ps1" %PSARG%') do set "PYVER=%%V"
if not defined PYVER exit /b 0
for /f "tokens=1,2,3 delims=." %%A in ("%PYVER%") do set /a "LATNUM=%%B*1000+%%C"
exit /b 0



:download_installer
set "PYURL=https://www.python.org/ftp/python/%PYVER%/python-%PYVER%-amd64.exe"
set "PYSETUP=%TEMP%\python-%PYVER%-amd64-setup.exe"
if exist "%PYSETUP%" del "%PYSETUP%" >nul 2>&1
echo        Laddar ner Python %PYVER% fran python.org ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri '%PYURL%' -OutFile '%PYSETUP%'"
exit /b 0


REM ------------------------------------------------------------
REM  INSTALLERA senaste stabila Python per anvandare (utan admin) -
REM  bara nar Python SAKNAS.
REM  1) Officiell installer fran python.org
REM  2) Reserv: winget, med paket-id harlett av PYVER
REM ------------------------------------------------------------
:install_python
call :download_installer
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
REM Dold snabbstart som gick fel: visa full installation i ett synligt fonster
if "%SNABB%"=="1" (start "Ledgebord - Installation" "%~f0" & exit /b 1)
echo.
pause
exit /b 1
