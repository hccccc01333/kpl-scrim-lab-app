@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
if exist updater.py python updater.py --apply-pending
echo KPL 赛训分析：http://127.0.0.1:8766/studio
echo 使用指南：docs\product_guide.md
echo 导入比赛、比赛复盘和选手分析均从同一页面进入。
echo 请保持此窗口运行。首次使用请先运行“安装依赖.bat”。
python server.py
pause
