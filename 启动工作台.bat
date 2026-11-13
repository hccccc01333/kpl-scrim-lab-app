@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
if exist updater.py python updater.py --apply-pending
echo KPL 赛训分析：http://127.0.0.1:8766/
echo 使用指南：README.md
echo 打开上面的地址即可（/v3/ 为旧链接兼容，/studio 为旧界面回看）。
echo 请保持此窗口运行。首次使用请先运行“安装依赖.bat”。
python server.py
pause
