@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem Create a desktop shortcut that opens the workbench without a console window.
rem Equivalent to: python scripts\make_shortcut.py --desktop
set "PY=python"
if exist "runtime\python.exe" set "PY=runtime\python.exe"
"%PY%" scripts\make_shortcut.py --desktop
if errorlevel 1 pause
timeout /t 3 >nul
