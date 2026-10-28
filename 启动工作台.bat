@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 训练赛分析工作台：http://127.0.0.1:8766
echo 请保持此窗口运行。首次使用请先运行“安装依赖.bat”。
python server.py
pause
