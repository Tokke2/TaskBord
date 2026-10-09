@echo off
chcp 65001 >nul
title TaskBord - Installation
echo ==================================================
echo   TaskBord v7 - INSTALLERA / UPPDATERA
echo   Kalla: %~dp0
echo   Mal:   D:\Program\todo
echo ==================================================
echo.

REM NY v7-fix58: mal-mapp kan anges som argument: INSTALLERA.bat E:\MinMapp
if not "%~1"=="" (set TARGET=%~1) else (set TARGET=D:\Program\todo)

if not exist "%TARGET%" mkdir "%TARGET%"
if not exist "%TARGET%\core" mkdir "%TARGET%\core"
if not exist "%TARGET%\ui"   mkdir "%TARGET%\ui"

echo Kopierar filer ...
copy /Y "%~dp0main.pyw"         "%TARGET%\"      >nul
copy /Y "%~dp0core\*.py"        "%TARGET%\core\" >nul
copy /Y "%~dp0ui\*.py"          "%TARGET%\ui\"   >nul
if exist "%~dp0requirements.txt" copy /Y "%~dp0requirements.txt" "%TARGET%\" >nul

echo.
echo Kontrollerar versioner:
findstr /C:"v7-fix51" "%TARGET%\main.pyw" >nul 2>&1
if %errorlevel%==0 (echo   [OK] main.pyw    = senaste ^(v7-fix51^)) else (echo   [FEL] main.pyw    = GAMMAL!)
findstr /C:"attach_window_above_desktop_icons" "%TARGET%\core\desktop.py" >nul 2>&1
if %errorlevel%==0 (echo   [OK] desktop.py  = senaste ^(desktop-lager^)) else (echo   [FEL] desktop.py  = GAMMAL!)
findstr /C:"_save_geometry_now" "%TARGET%\ui\widget.py" >nul 2>&1
if %errorlevel%==0 (echo   [OK] widget.py   = senaste ^(las+geometri^)) else (echo   [FEL] widget.py   = GAMMAL!)
findstr /C:"auto_update_plugins" "%TARGET%\core\settings.py" >nul 2>&1
if %errorlevel%==0 (echo   [OK] settings.py = senaste ^(auto-tillagg^)) else (echo   [FEL] settings.py = GAMMAL!)

echo.
echo Skapar skrivbordsgenvag "TaskBord" med egen ikon ...
powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $lnk = $ws.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\\TaskBord.lnk'); $lnk.TargetPath = 'pythonw.exe'; $lnk.Arguments = '"%TARGET%\\main.pyw"'; $lnk.WorkingDirectory = '%TARGET%'; $lnk.IconLocation = '%TARGET%\\data\\app.ico'; $lnk.Save()"

echo Startar appen fran %TARGET% ...
start "" pythonw.exe "%TARGET%\main.pyw"

echo.
echo KLAR! Appen startas fran D:\Program\todo
echo.
echo PORTABELT TIPS: vill du kora fran USB/valfri mapp -
echo anvand STARTA_HAR.bat i appmappen istallet (ingen installation).
echo.
pause
