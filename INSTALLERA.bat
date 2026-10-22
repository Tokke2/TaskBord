@echo off
chcp 65001 >nul
title Ledgebord - Installation
echo ==================================================
echo   Ledgebord v7 - INSTALLERA / UPPDATERA
echo   Kalla: %~dp0
echo   Mal:   D:\Program\todo
echo ==================================================
echo.

REM NY v7-fix58: mal-mapp kan anges som argument: INSTALLERA.bat E:\MinMapp
if not "%~1"=="" (set TARGET=%~1) else (set TARGET=D:\Program\todo)

if not exist "%TARGET%" mkdir "%TARGET%"
if not exist "%TARGET%\core" mkdir "%TARGET%\core"
if not exist "%TARGET%\ui"   mkdir "%TARGET%\ui"
if not exist "%TARGET%\app"   mkdir "%TARGET%\app"
if not exist "%TARGET%\app\mixins" mkdir "%TARGET%\app\mixins"
REM NY v7-fix90: Thunderbird-tillagget foljer med installationen
if not exist "%TARGET%\thunderbird-tillagg" mkdir "%TARGET%\thunderbird-tillagg"

echo Kopierar filer ...
copy /Y "%~dp0main.pyw"         "%TARGET%\"      >nul
copy /Y "%~dp0core\*.py"        "%TARGET%\core\" >nul
copy /Y "%~dp0ui\*.py"          "%TARGET%\ui\"   >nul
copy /Y "%~dp0app\*.py"         "%TARGET%\app\"  >nul
copy /Y "%~dp0app\mixins\*.py"  "%TARGET%\app\mixins\" >nul
if exist "%~dp0requirements.txt" copy /Y "%~dp0requirements.txt" "%TARGET%\" >nul

REM NY v7-fix90: e-postbrygga / Thunderbird-tillagg
copy /Y "%~dp0SKAPA_XPI.bat"    "%TARGET%\"      >nul
copy /Y "%~dp0skapa_xpi.py"     "%TARGET%\"      >nul
copy /Y "%~dp0THUNDERBIRD.md"   "%TARGET%\"      >nul
xcopy /Y /E /I "%~dp0thunderbird-tillagg" "%TARGET%\thunderbird-tillagg\" >nul
xcopy /Y /E /I "%~dp0icon" "%TARGET%\icon\" >nul
if exist "%~dp0Ledgebord-Thunderbird.xpi" copy /Y "%~dp0Ledgebord-Thunderbird.xpi" "%TARGET%\" >nul

echo.
echo Kontrollerar versioner:
findstr /C:"v7-fix51" "%TARGET%\app\mixins\windows.py" >nul 2>&1
if %errorlevel%==0 (echo   [OK] app\      = senaste ^(v7-fix51^)) else (echo   [FEL] app\      = GAMMAL eller SAKNAS!)
findstr /C:"attach_window_above_desktop_icons" "%TARGET%\core\desktop.py" >nul 2>&1
if %errorlevel%==0 (echo   [OK] desktop.py  = senaste ^(desktop-lager^)) else (echo   [FEL] desktop.py  = GAMMAL!)
findstr /C:"_save_geometry_now" "%TARGET%\ui\widget_parts\qt_events.py" >nul 2>&1
if %errorlevel%==0 (echo   [OK] widget.py   = senaste ^(las+geometri^)) else (echo   [FEL] widget.py   = GAMMAL!)
findstr /C:"auto_update_plugins" "%TARGET%\core\settings.py" >nul 2>&1
if %errorlevel%==0 (echo   [OK] settings.py = senaste ^(auto-tillagg^)) else (echo   [FEL] settings.py = GAMMAL!)
findstr /C:"MailBridgeService" "%TARGET%\core\mail_bridge.py" >nul 2>&1
if %errorlevel%==0 (echo   [OK] mail_bridge.py = senaste ^(Thunderbird^)) else (echo   [FEL] mail_bridge.py = SAKNAS!)
if exist "%TARGET%\Ledgebord-Thunderbird.xpi" (echo   [OK] Ledgebord-Thunderbird.xpi finns) else (echo   [--] xpi saknas - kor SKAPA_XPI.bat i appmappen)

echo.
echo Skapar skrivbordsgenvag "Ledgebord" med egen ikon ...
powershell -NoProfile -Command "Remove-Item ([Environment]::GetFolderPath('Desktop') + '\\TaskBord.lnk') -ErrorAction SilentlyContinue"
powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $lnk = $ws.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\\Ledgebord.lnk'); $lnk.TargetPath = 'pythonw.exe'; $lnk.Arguments = '"%TARGET%\\main.pyw"'; $lnk.WorkingDirectory = '%TARGET%'; $lnk.IconLocation = '%TARGET%\\icon\\ledgebord.ico'; $lnk.Save()"

echo Startar appen fran %TARGET% ...
start "" pythonw.exe "%TARGET%\main.pyw"

echo.
echo KLAR! Appen startas fran D:\Program\todo
echo.
echo PORTABELT TIPS: vill du kora fran USB/valfri mapp -
echo anvand STARTA_HAR.bat i appmappen istallet (ingen installation).
echo.
pause
