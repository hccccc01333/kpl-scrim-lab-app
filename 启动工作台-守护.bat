@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 训练赛数据台守护启动：http://127.0.0.1:8766/studio
echo 关闭窗口或按 Ctrl+C 停止。
python scripts\watch_server.py
pause
