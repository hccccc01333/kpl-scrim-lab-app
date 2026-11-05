"""构建绿色免安装发布包（dist/KPL赛训工具-*.zip）。

包结构 = 当前项目布局（扁平）：runtime/ + 代码 + web/resources/docs + data/（空）。
只包含核心依赖（fastapi/uvicorn/Pillow/numpy/openpyxl/pycryptodome）；
rapidocr/ffmpeg 为可选组件，由包内「安装OCR组件.bat」按需安装。
绝不打包：本机 data/ 数据、内部资料、host/、test-results、docs 的逆向文档。
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = Path(os.environ.get('LOCALAPPDATA', str(ROOT / 'dist'))) / 'kpl-release'
STAMP = time.strftime('%Y%m%d-%H%M%S')
BUILD = DIST / f'build-{STAMP}'
PY_VER = '3.12.10'
PY_URL = f'https://www.python.org/ftp/python/{PY_VER}/python-{PY_VER}-embed-amd64.zip'
CORE_DEPS = ['fastapi>=0.115,<1', 'uvicorn>=0.30,<1', 'Pillow>=10,<13',
             'numpy>=1.26,<3', 'openpyxl>=3.1,<4', 'pycryptodome>=3.20,<4']
CODE_FILES = [
    'server.py', 'domain.py', 'analytics.py', 'analysis_api.py', 'analysis_data.py',
    'bp_input.py', 'camp_replay.py', 'channel_store.py', 'collection_contract.py',
    'focus.py', 'hero_catalog.py', 'hero_names.py', 'identity_rules.py',
    'match_data.py', 'match_review.py', 'mimo_ocr.py', 'ocr.py', 'ocr_jobs.py',
    'operator_stream.py', 'postgame_analysis.py', 'postgame_mimo.py',
    'postgame_ocr.py', 'recording_store.py', 'replay_parser.py', 'replay_profiles.py',
    'replay_v2_api.py', 'replay_v2_build.py', 'runtime_data.py',
    'screenshot_fields.py', 'screenshot_schema.py', 'sheet_import.py',
    'studio_analysis.py', 'studio_api.py', 'studio_pipeline.py', 'studio_research.py',
    'video_mimo.py', 'video_ocr.py', 'vision.py',
]
DOCS_SHIP = ['product_guide.md', 'camp_setup.md']

STARTER_BAT = """@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist data mkdir data
echo KPL 赛训分析：http://127.0.0.1:8766/studio
echo 使用指南见「部署说明.txt」；请保持此窗口运行（关闭窗口即停止服务）。
runtime\\python.exe server.py
pause
"""

STOP_BAT = """@echo off
taskkill /f /im python.exe >nul 2>&1
echo 已尝试停止服务进程（会结束本机所有 python，请注意）。
pause
"""

SOP = """KPL 赛训数据工具 · 部署说明（约 30 分钟）
=============================================

一、解压与启动
  1. 将整个文件夹解压到任意位置（建议 D:\\KPL赛训工具\\，路径不要含中文更好）。
  2. 双击「启动工作台.bat」——第一次运行 Windows 可能弹防火墙提示，选「允许访问」。
  3. 浏览器打开 http://127.0.0.1:8766/studio 即可使用。
     数据全部保存在本机 data 文件夹，不上传任何服务器。

二、教练授权（一次性）
  1. 采集通道页 → 「营地自动同步」→ 扫码授权。
  2. 用打过训练赛的教练微信扫码并在手机上确认。
  3. 授权凭证保存在 data\\camp_auth.json——等同于账号登录态，勿外传。

三、选手白名单（一次性）
  1. 让选手在王者营地分享任意一局到微信，复制链接。
  2. 同步面板把链接粘进「加入清单」，自动识别营地 ID。
  3. 一个稳定上场的选手即可覆盖全队每局（一局详情含双方十人）。

四、每天使用
  1. 选选手 → 「获取对局列表」→ 勾选要的局 → 「拉取选中」。
  2. 数据自动进入采集通道，打开通道即可复盘。
  3. 战绩可见性：选手可在营地隐私设置里把教练加入白名单（不对外公开也可以）。

五、故障处理
  - 提示登录态失效 / 安全参数被拒 → 重新扫码授权。
  - 用户ID不存在 → 营地 ID 填错（应为分享链接 userId= 的数字）。
  - 列表为空但选手打过 → 该营地账号未绑定游戏大区角色。
  - 其他问题联系技术支持。

六、数据备份与迁移
  整个 data 文件夹拷走即完成备份；换电脑时把 data 放进新包即可延续全部数据。

七、可选组件（录屏识别）
  录屏 OCR 需要额外组件：双击「安装OCR组件.bat」按提示安装。
  只用营地同步 + 截图兜底的队伍可以不装。
"""


def download_runtime():
    runtime = BUILD / 'runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    archive = DIST / f'python-{PY_VER}-embed-amd64.zip'
    if not archive.is_file():
        print('下载 Python embeddable…')
        urllib.request.urlretrieve(PY_URL, archive)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(runtime)
    pth = runtime / f'python{PY_VER.rpartition(".")[0].replace(".", "")}._pth'
    pth.write_text('python312.zip\n.\nLib\\site-packages\nimport site\n', encoding='ascii')
    return runtime


def install_deps():
    print('安装核心依赖（fastapi/uvicorn/Pillow/numpy/openpyxl/pycryptodome）…')
    target = BUILD / 'runtime' / 'Lib' / 'site-packages'
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--target', str(target),
                    '--disable-pip-version-check', *CORE_DEPS], check=True)


def copy_code():
    print('拷贝代码与资源…')
    for name in CODE_FILES:
        shutil.copy2(ROOT / name, BUILD / name)
    for folder in ('web', 'resources'):
        shutil.copytree(ROOT / folder, BUILD / folder,
                        ignore=shutil.ignore_patterns('__pycache__', '.git'))
    docs = BUILD / 'docs'
    docs.mkdir(exist_ok=True)
    for name in DOCS_SHIP:
        source = ROOT / 'docs' / name
        if source.is_file():
            shutil.copy2(source, docs / name)
    data = BUILD / 'data'
    for sub in ('official_replays', 'camp_details', 'camp_lists', 'camp_reports',
                'screenshots', 'recordings', 'replays'):
        (data / sub).mkdir(parents=True, exist_ok=True)


def write_launchers():
    (BUILD / '启动工作台.bat').write_text(STARTER_BAT, encoding='gbk')
    (BUILD / '停止工作台.bat').write_text(STOP_BAT, encoding='gbk')
    (BUILD / '部署说明.txt').write_text(SOP, encoding='utf-8')


def make_zip():
    stamp = time.strftime('%Y%m%d')
    out = DIST / f'KPL赛训工具-{stamp}.zip'
    if out.is_file():
        out.unlink()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in BUILD.rglob('*'):
            zf.write(path, Path('KPL赛训工具') / path.relative_to(BUILD))
    return out


def main():
    DIST.mkdir(exist_ok=True)
    started = time.time()
    download_runtime()
    install_deps()
    copy_code()
    write_launchers()
    archive = make_zip()
    size = archive.stat().st_size / 1024 / 1024
    print(f'发布包完成：{archive}（{size:.0f} MB，用时 {time.time() - started:.0f}s）')
    try:
        shutil.rmtree(BUILD)
    except Exception:
        print(f'提示：构建中间目录 {BUILD} 未能自动清理，可手动删除。')


if __name__ == '__main__':
    main()
