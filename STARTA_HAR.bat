@echo off
REM Startar TaskBord med nyaste installerade Python (ingen version hardkodad).
REM Installerar Python/paket via FORSTA_START.bat om Python saknas.
call "%~dp0FORSTA_START.bat" /snabb
