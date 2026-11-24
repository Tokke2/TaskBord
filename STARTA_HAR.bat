@echo off
REM Startar Ledgebord UTAN svart konsollfonster (via STARTA_DOLT.vbs).
REM Hittas Python inte oppnas full installation (FORSTA_START.bat) i ett synligt fonster.
if exist "%~dp0STARTA_DOLT.vbs" (
    start "" wscript //nologo "%~dp0STARTA_DOLT.vbs"
    exit /b 0
)
call "%~dp0FORSTA_START.bat" /snabb
