@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist runtime\python.exe (
  runtime\python.exe updater.py --check
) else (
  python updater.py --check
)
pause
