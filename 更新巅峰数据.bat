@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
echo ============================================
echo   巅峰千强大盘更新（对位压制用的外部事实）
echo ============================================
echo   流程：英雄日线 → hero_daily → 对位矩阵 → lane_matchups.json
echo   全量约 30-50 分钟（可随时中断，已爬到的对位不会丢）。
echo   工作台服务每天也会自动刷一轮；这个脚本用来手动补刷。
echo.
python peak_crawl.py --all %*
echo.
echo 更新完成，刷新单局复盘页即可看到最新对位胜率。
pause
