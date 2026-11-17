@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem Stop the watchdog first, otherwise watch_server.py restarts the service.
if exist "data\watchdog.pid" (
  for /f "usebackq delims=" %%p in ("data\watchdog.pid") do taskkill /PID %%p /F >nul 2>nul
  del "data\watchdog.pid" >nul 2>nul
)

set "PY=python"
if exist "runtime\python.exe" set "PY=runtime\python.exe"
"%PY%" launcher.py --stop
if errorlevel 1 (
  echo Stop failed, see logs\launcher.log
) else (
  echo Workbench stopped.
)
timeout /t 2 >nul
