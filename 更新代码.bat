@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .git (
  echo 当前目录不是 git 仓库。
  echo 如果你使用的是免安装包，请双击「检查更新.bat」或在工作台右下角更新。
  pause
  exit /b 1
)
echo 正在获取远程更新…
git fetch --tags origin
for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD') do set "BRANCH=%%b"
echo 待更新提交：
git log --oneline HEAD..origin/%BRANCH%
echo.
git pull --ff-only
if errorlevel 1 (
  echo.
  echo 更新失败：请先提交或暂存本地改动，再重新运行本脚本。
  pause
  exit /b 1
)
echo.
echo 检查依赖…
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo 依赖安装失败，请检查网络或 Python 环境。
  pause
  exit /b 1
)
echo.
echo 更新完成，请重新启动工作台。
pause
