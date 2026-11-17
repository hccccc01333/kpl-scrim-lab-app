@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

rem Single entry: launcher.py reuses a running instance, starts one if needed,
rem opens the browser, and holds a single-instance mutex. The old wrapper ran
rem "python server.py" directly, so a second double-click fought for port 8766.
rem Started through pythonw so no console window is left behind; failures show a
rem native message box and are logged to logs\launcher.log.
set "PY=python"
if exist "runtime\python.exe" set "PY=runtime\python.exe"
set "PYW=pythonw"
if exist "runtime\pythonw.exe" set "PYW=runtime\pythonw.exe"

where %PYW% >nul 2>nul
if errorlevel 1 goto console
start "" %PYW% launcher.py
exit /b 0

:console
echo No pythonw found; starting with a console window (closing it stops the workbench).
%PY% launcher.py
if errorlevel 1 pause
