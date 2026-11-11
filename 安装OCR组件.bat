@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY=runtime\python.exe"
if not exist "%PY%" set "PY=python"
echo 正在安装可选 OCR 组件（RapidOCR）…
"%PY%" -m pip install --disable-pip-version-check -r requirements-ocr.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
  echo 国内镜像失败，尝试官方源…
  "%PY%" -m pip install --disable-pip-version-check -r requirements-ocr.txt
)
if errorlevel 1 (
  echo 安装失败，请检查网络后重试。
) else (
  echo OCR 组件安装完成，重启工作台后生效。
)
pause
