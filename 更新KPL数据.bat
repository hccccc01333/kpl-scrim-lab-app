@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
echo ============================================
echo   KPL 赛事 BP 数据更新（只抓 BP 与胜负）
echo ============================================
echo   增量抓取：已经抓过的小局不会重复请求。
echo   首次全量约 10 分钟，之后每次几秒到几十秒。
echo   抓完自动重建赛事命中用的组合表。
echo.
python scripts\crawl_kpl_bp.py %*
echo.
echo 更新完成，刷新工作台页面即可看到新的赛事命中。
pause
