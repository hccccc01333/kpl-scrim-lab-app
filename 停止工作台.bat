@echo off
chcp 65001 >nul
echo Stopping KPL training server...
%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -Command "$pidfile=Join-Path (Get-Location) 'data\watchdog.pid'; if(Test-Path $pidfile){$w=Get-Content $pidfile; Stop-Process -Id $w -Force -ErrorAction SilentlyContinue; Remove-Item $pidfile -ErrorAction SilentlyContinue}; $h=Invoke-RestMethod -Uri 'http://127.0.0.1:8766/api/health' -ErrorAction SilentlyContinue; if($h){$proc=Get-CimInstance Win32_Process -Filter ('ProcessId=' + $h.pid); if($proc -and $proc.ParentProcessId){Stop-Process -Id $proc.ParentProcessId -Force -ErrorAction SilentlyContinue}; Stop-Process -Id $h.pid -Force -ErrorAction SilentlyContinue}"
echo Stopped.
pause
