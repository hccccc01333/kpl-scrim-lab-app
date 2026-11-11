"""Build the portable package plus incremental update assets.

Outputs (in ``dist/`` by default):

* ``KPL-Scrim-Lab-<version>-full.zip``  first install, includes embedded Python
* ``patch-<version>.zip``             changed files only, for one-click updates
* ``update.json``                     manifest consumed by ``/api/update/check``

The file list is collected from the working tree instead of a hand-maintained
whitelist, so new modules cannot silently fall out of the package.  The full
build runs an import smoke test with the embedded Python before zipping.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from update_client import normalize_rel_path, sha256_file  # noqa: E402

DIST = ROOT / 'dist'
PY_VER = '3.12.10'
PY_URL = f'https://www.python.org/ftp/python/{PY_VER}/python-{PY_VER}-embed-amd64.zip'
PYTHON_URLS = [
    PY_URL,
    f'https://mirrors.huaweicloud.com/python/{PY_VER}/python-{PY_VER}-embed-amd64.zip',
    f'https://registry.npmmirror.com/-/binary/python/{PY_VER}/python-{PY_VER}-embed-amd64.zip',
]
DEFAULT_PIP_INDEX = 'https://pypi.tuna.tsinghua.edu.cn/simple'
CORE_DEPS = [
    'fastapi>=0.115,<1',
    'uvicorn>=0.30,<1',
    'Pillow>=10,<13',
    'numpy>=1.26,<3',
    'openpyxl>=3.1,<4',
    'pycryptodome>=3.20,<4',
    # 主 OCR 是日常识别的必需组件：随包内置，装完即用，不让用户再点安装。
    # 代价是完整包约 +80–100 MB；可选增强（Mimo 模型、ffmpeg）仍按需一键装。
    'rapidocr-onnxruntime>=1.4.4,<1.5',
]
DOCS_SHIP = [
    'product_guide.md',
    'collection_sop.md',
    'camp_setup.md',
    'deploy.md',
    'ocr_engine.md',
    'camp_replay.md',
]
# server.py 运行期会把 tools/ 插进 sys.path 再 import 营地同步模块；
# 这几个文件必须随包发布，否则安装版一进采集就 ModuleNotFoundError。
TOOLS_SHIP = [
    'tools/camp_auth.py',
    'tools/camp_client.py',
    'tools/camp_sync.py',
    'tools/xxtea_algo.py',
    # replay_timeline_build 解码 .abc 时懒加载这几个（出装时间轴要用）。
    'tools/full_abc_event_catalog.py',
    'tools/replay_abc_event_windows.py',
    'tools/replay_frame_commands.py',
    'tools/replay_input_timeline.py',
    'tools/replay_opening_packet.py',
    'tools/replay_record_stream.py',
]
ROOT_FILES = [
    'CHANGELOG.md',
    'LICENSE',
    'requirements.txt',
    'requirements-ocr.txt',
    'requirements-mimo.txt',
    '.env.example',
    'update_config.json',
]
PATCH_EXCLUDE = {'update_config.json'}
PACKAGE_NAME = 'KPL-Scrim-Lab'

STARTER_BAT = """@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
if not exist data mkdir data
if exist runtime\\pythonw.exe (
  rem 无窗口启动：由 launcher.py 起服务、等健康检查、再打开浏览器
  start "" runtime\\pythonw.exe launcher.py
  exit /b 0
)
echo 未找到内置 Python，请重新解压完整包。
pause
"""

STOP_BAT = """@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY=runtime\\python.exe"
if not exist "%PY%" set "PY=python"
echo 正在停止工作台…
"%PY%" launcher.py --stop
timeout /t 1 >nul
echo 已停止。如果界面仍可访问，请稍等几秒后刷新。
pause
"""

OCR_BAT = """@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY=runtime\\python.exe"
if not exist "%PY%" set "PY=python"
echo 正在安装可选 OCR 组件（RapidOCR）…
"%PY%" -m pip install --disable-pip-version-check --target "%CD%\\runtime\\Lib\\site-packages" -r requirements-ocr.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
  echo 国内镜像失败，尝试官方源…
  "%PY%" -m pip install --disable-pip-version-check --target "%CD%\\runtime\\Lib\\site-packages" -r requirements-ocr.txt
)
if errorlevel 1 (
  echo 安装失败，请检查网络后重试。
) else (
  echo OCR 组件安装完成，重启工作台后生效。
)
pause
"""

CHECK_BAT = """@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY=runtime\\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" updater.py --check
pause
"""

SOP = """KPL 赛训数据工具 · 部署说明
================================

一、启动
  安装版：双击桌面「KPL 赛训工具」；开始菜单同一文件夹里还有
         「停止工作台」「检查更新」「打开数据目录」「打开日志目录」。
  免安装版：解压到固定目录（例如 D:\\KPL赛训工具\\，不要放桌面或
         Program Files），双击「启动工作台.bat」。
  两种情况都会自动打开浏览器；服务在后台运行，关掉浏览器不会停止。
  数据全部保存在本机 data 文件夹，不上传任何服务器。

二、教练授权（一次性）
  1. 采集通道页 →「营地自动同步」→ 扫码授权。
  2. 用打过训练赛的教练微信扫码并在手机上确认。
  3. 授权凭证保存在 data\\camp_auth.json，等同于账号登录态，勿外传。

三、选手白名单（一次性）
  1. 让选手在王者营地分享任意一局到微信，复制链接。
  2. 同步面板把链接粘进「加入清单」，自动识别营地 ID。
  3. 一个稳定上场的选手即可覆盖全队每局（一局详情含双方十人）。

四、每天使用
  1. 选选手 →「获取对局列表」→ 勾选要的局 →「拉取选中」。
  2. 数据自动进入采集通道，打开通道即可复盘。
  3. 战绩可见性：选手可在营地隐私设置里把教练加入白名单。

五、更新
  - 启动后工作台会自动检查新版本，右下角出现提示时点「立即更新」。
  - 也可以双击「检查更新.bat」或开始菜单的「检查更新」查看当前版本。
  - 更新只替换程序文件，不会修改 data 目录；失败会自动回滚。
  - 完全离线时，可以让作者发来 patch-版本号.zip，在提示里选「选择本地更新包」。
  - 内置 Python 或依赖有变化的大版本会提供新安装包，直接覆盖安装即可，数据不丢。

六、数据备份与迁移
  整个 data 文件夹拷走即完成备份；换电脑时把 data 放进新包即可延续全部数据。

七、可选组件（截图 / 录屏 OCR）
  双击「安装OCR组件.bat」按提示安装；需要联网，已配置国内镜像。
  只用营地同步、不需要截图兜底的队伍可以不装。

八、故障处理
  - 双击图标没反应或提示启动失败 → 开始菜单「打开日志目录」，把
    launcher.log 和 server.log 发给作者。
  - 提示登录态失效（-30003 / -30314）/ 安全参数被拒 → 工作台会显示「补充授权」，重新扫码即可。
  - 用户ID不存在 → 营地 ID 填错（应为分享链接 userId= 的数字）。
  - 列表为空但选手打过 → 该营地账号未绑定游戏大区角色。
  - 端口被占用 → 关闭占用 8766 的程序，或设置环境变量 TRAINING_PORT 换端口。
"""

AUTH_NOTE = """授权说明
========

本软件按仓库 LICENSE（PolyForm Noncommercial License 1.0.0）发布。
非商业用途可直接使用；商业用途（含职业俱乐部、付费服务）需另行取得作者授权。

联系：rainfun446@gmail.com
https://github.com/hccccc01333
"""


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec='seconds')


def read_meta() -> dict:
    text = (ROOT / 'version.py').read_text(encoding='utf-8')

    def field(name: str) -> str:
        match = re.search(rf"^{name}\s*=\s*['\"]([^'\"]*)['\"]", text, re.MULTILINE)
        return match.group(1) if match else ''

    version = field('VERSION')
    if not version:
        raise RuntimeError('version.py 中缺少 VERSION')
    return {'version': version, 'releaseDate': field('RELEASE_DATE'),
            'releaseName': field('RELEASE_NAME')}


SUMMARY_HEADINGS = ('更新摘要', '本次更新')


def changelog_notes(version: str) -> list[str]:
    path = ROOT / 'CHANGELOG.md'
    if not path.is_file():
        return [f'版本 {version}']
    lines = path.read_text(encoding='utf-8').splitlines()
    header = re.compile(r'^##\s+\[' + re.escape(version) + r'\]')
    start = next((index + 1 for index, line in enumerate(lines)
                  if header.match(line.strip())), None)
    if start is None:
        return [f'版本 {version}']
    notes = []
    summary = []
    in_summary = False
    for line in lines[start:]:
        stripped = line.strip()
        if stripped.startswith('## '):
            break
        if stripped.startswith('### '):
            in_summary = stripped[4:].strip() in SUMMARY_HEADINGS
            continue
        if not stripped or stripped.startswith('#') or stripped.startswith('---'):
            continue
        if stripped.startswith('- '):
            item = stripped[2:].strip()
            notes.append(item)
            if in_summary:
                summary.append(item)
        else:
            notes.append(stripped)
    # 有「更新摘要」段时，更新弹窗只读摘要；完整明细仍留在 CHANGELOG / 官网。
    return (summary[:12] or notes[:30]) or [f'版本 {version}']


def _junk_file(name: str) -> bool:
    """编辑器/系统留下的临时文件，永远不要进发布包。"""
    return (name.startswith(('~$', '.tmp'))
            or name.endswith(('.TMP', '.tmp', '.bak', '.swp', '~'))
            or '~RF' in name)


def ship_files() -> list[str]:
    files = []
    for path in sorted(ROOT.glob('*.py')):
        if path.name.startswith(('_', '.')) or _junk_file(path.name):
            continue
        files.append(path.name)
    for folder in ('web', 'resources'):
        base = ROOT / folder
        if not base.is_dir():
            continue
        for path in sorted(base.rglob('*')):
            if not path.is_file():
                continue
            if '__pycache__' in path.parts or path.suffix in ('.pyc', '.map'):
                continue
            if _junk_file(path.name):
                continue
            files.append(path.relative_to(ROOT).as_posix())
    # 单一 V3 应用：server.py 随包发布，根路径才能正常打开。
    v3 = ROOT / 'v3'
    if v3.is_dir():
        for name in ('serve.py', 'deep_analysis.py', 'demo_data.py'):
            if (v3 / name).is_file():
                files.append(f'v3/{name}')
        public = v3 / 'public'
        if public.is_dir():
            for path in sorted(public.rglob('*')):
                if not path.is_file():
                    continue
                if '__pycache__' in path.parts or path.suffix in ('.pyc', '.map'):
                    continue
                if _junk_file(path.name):
                    continue
                files.append(path.relative_to(ROOT).as_posix())
    for name in DOCS_SHIP:
        if (ROOT / 'docs' / name).is_file():
            files.append(f'docs/{name}')
    for name in TOOLS_SHIP:
        if (ROOT / name).is_file():
            files.append(name)
    for name in ROOT_FILES:
        if (ROOT / name).is_file():
            files.append(name)
    return sorted(dict.fromkeys(files))


def _git(*args: str) -> list[str]:
    result = subprocess.run(['git', *args], cwd=str(ROOT), capture_output=True,
                            text=True, encoding='utf-8', errors='replace')
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f'git {" ".join(args)} 失败')
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def previous_tag(version: str) -> str | None:
    try:
        tags = _git('tag', '--merged', 'HEAD', '--sort=-v:refname')
    except Exception:
        return None
    current = f'v{version}'
    for tag in tags:
        if re.fullmatch(r'v\d+\.\d+\.\d+.*', tag) and tag != current:
            return tag
    return None


def _shippable_path(path: str) -> bool:
    if path in ROOT_FILES:
        return True
    if path.startswith(('web/', 'resources/', 'docs/', 'v3/')):
        return True
    return '/' not in path and path.endswith('.py')


def diff_paths(since: str | None, ship: list[str]) -> tuple[list[str], list[str]]:
    if not since:
        return list(ship), []
    try:
        changed = set(_git('diff', '--name-only', '--diff-filter=ACMRT',
                           since, 'HEAD', '--', '.'))
        changed |= set(_git('ls-files', '--others', '--exclude-standard'))
        deleted = [path for path in _git(
            'diff', '--name-only', '--diff-filter=D', since, 'HEAD', '--', '.')
            if _shippable_path(path)]
    except Exception as exc:
        print(f'提示：无法读取 git 变更（{exc}），本次补丁包含全部文件。')
        return list(ship), []
    paths = [path for path in ship if path in changed]
    return paths, deleted


def hash_entries(paths: list[str]) -> list[dict]:
    entries = []
    for path in paths:
        full = ROOT / path
        if not full.is_file():
            raise RuntimeError(f'发布文件缺失：{path}')
        entries.append({'path': path, 'sha256': sha256_file(full),
                        'size': full.stat().st_size})
    return entries


def asset_url(base: str | None, name: str) -> str:
    if base:
        return f'{base.rstrip("/")}/{name}'
    return name


def build_patch(version: str, paths: list[str], removed: list[str],
                notes: list[str], args) -> tuple[dict, Path]:
    paths = sorted(set(paths) | {'version.py'})
    if 'version.py' in removed:
        raise RuntimeError('删除列表不能包含 version.py')
    entries = hash_entries(paths)
    patch_name = f'patch-{version}.zip'
    patch_path = DIST / patch_name

    embedded = {
        'schema': 1,
        'version': version,
        'publishedAt': now_iso(),
        'channel': args.channel,
        'minVersion': args.min_version,
        'notes': notes,
        'patch': {'url': patch_name, 'files': entries, 'remove': removed},
    }
    with zipfile.ZipFile(patch_path, 'w', zipfile.ZIP_DEFLATED,
                         compresslevel=6) as archive:
        archive.writestr('update.json',
                         json.dumps(embedded, ensure_ascii=False, indent=2))
        for path in paths:
            archive.write(ROOT / path, f'payload/{path}')

    manifest = json.loads(json.dumps(embedded, ensure_ascii=False))
    manifest['patch'] = {
        'url': asset_url(args.base_url, patch_name),
        'sha256': sha256_file(patch_path),
        'size': patch_path.stat().st_size,
        'files': entries,
        'remove': removed,
    }
    print(f'增量包：{patch_path.name}（{patch_path.stat().st_size / 1024:.0f} KB，'
          f'{len(paths)} 个文件，删除 {len(removed)} 个）')
    return manifest, patch_path


def download_runtime(build: Path, archive_override: str | None = None) -> Path:
    runtime = build / 'runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    cache = DIST / 'cache'
    cache.mkdir(parents=True, exist_ok=True)
    archive = Path(archive_override) if archive_override else (
        cache / f'python-{PY_VER}-embed-amd64.zip')
    if archive_override:
        if not archive.is_file():
            raise RuntimeError(f'指定的 Python 压缩包不存在：{archive_override}')
    elif not archive.is_file():
        errors = []
        for url in PYTHON_URLS:
            candidate = cache / f'python-{PY_VER}-embed-amd64.zip'
            temporary = candidate.with_suffix('.part')
            try:
                print(f'下载 Python embeddable：{url}')
                request = urllib.request.Request(
                    url, headers={'User-Agent': 'KPL-Scrim-Lab-Builder/1.0'})
                with urllib.request.urlopen(request, timeout=90) as source, \
                        open(temporary, 'wb') as destination:
                    shutil.copyfileobj(source, destination, length=1024 * 1024)
                with zipfile.ZipFile(temporary) as probe:
                    probe.testzip()
                    if 'python.exe' not in probe.namelist():
                        raise ValueError('压缩包内缺少 python.exe')
                os.replace(temporary, candidate)
                archive = candidate
                break
            except Exception as exc:  # noqa: BLE001 - try the next mirror
                errors.append(f'{url}: {exc}')
                temporary.unlink(missing_ok=True)
        else:
            raise RuntimeError(
                '无法下载 Python embeddable，请手动下载后使用 '
                '--python-archive 指定；尝试记录：\n' + '\n'.join(errors))
    with zipfile.ZipFile(archive) as source:
        source.extractall(runtime)
    pth = runtime / f'python{PY_VER.rpartition(".")[0].replace(".", "")}._pth'
    # ``..`` is the application root: embeddable Python does not add the
    # script directory to sys.path, so without it ``server.py`` cannot import
    # its sibling modules.
    pth.write_text('python312.zip\n.\nLib\\site-packages\n..\nimport site\n',
                   encoding='ascii')
    (runtime / 'Lib' / 'site-packages').mkdir(parents=True, exist_ok=True)
    return runtime


def install_deps(runtime: Path, index_url: str | None = None,
                 deps_dir: str | None = None, with_ocr: bool = True) -> None:
    target = runtime / 'Lib' / 'site-packages'
    if deps_dir:
        source = Path(deps_dir)
        if not source.is_dir():
            raise RuntimeError(f'依赖目录不存在：{deps_dir}')
        print(f'复用本地依赖：{source}')
        shutil.copytree(source, target, dirs_exist_ok=True)
        return
    deps = list(CORE_DEPS) if with_ocr else [
        item for item in CORE_DEPS if not item.lower().startswith('rapidocr')]
    print('安装核心依赖' + ('（含主 OCR 运行时）' if with_ocr else '（精简：不含主 OCR，'
          '首次打开用「安装主 OCR」一键补装）') + '…')
    # 构建机可能是 3.13，而内置运行时固定 3.12：不指定 ABI 的话 pip 会装
    # cp313 的二进制轮子，装进 3.12 后 import pydantic_core 直接失败。
    target_python = '.'.join(PY_VER.split('.')[:2])
    base = [sys.executable, '-m', 'pip', 'install', '--target', str(target),
            '--disable-pip-version-check', '--only-binary=:all:',
            '--python-version', target_python, '--platform', 'win_amd64', *deps]
    if index_url:
        try:
            subprocess.run([*base, '-i', index_url], check=True)
            return
        except subprocess.CalledProcessError:
            print('镜像安装失败，尝试官方 PyPI…')
    subprocess.run(base, check=True)


def ensure_pip(runtime: Path) -> None:
    """Make ``runtime\\python.exe -m pip`` usable for optional components.

    The Python embeddable distribution does not ship pip.  Copy the builder's
    pip package into the runtime so the OCR installer works without a system
    Python on the coach's machine.
    """
    target = runtime / 'Lib' / 'site-packages'
    if (target / 'pip').is_dir():
        return
    try:
        import importlib.metadata as metadata
        import pip

        source = Path(pip.__file__).resolve().parent
        shutil.copytree(source, target / 'pip', dirs_exist_ok=True)
        for dist in metadata.distributions():
            if (dist.metadata.get('Name') or '').lower() != 'pip':
                continue
            path = getattr(dist, '_path', None)
            if path and Path(path).is_dir():
                shutil.copytree(Path(path), target / Path(path).name,
                                dirs_exist_ok=True)
            break
        print('已内置 pip，供「安装OCR组件.bat」使用。')
    except Exception as exc:  # noqa: BLE001
        print(f'提示：未能内置 pip（{exc}），OCR 组件需要手动安装。')


def copy_ship_files(build: Path, paths: list[str]) -> None:
    print(f'拷贝 {len(paths)} 个程序文件…')
    for path in paths:
        source = ROOT / path
        destination = build / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def write_data_dirs(build: Path) -> None:
    for name in ('official_replays', 'camp_details', 'camp_lists', 'camp_reports',
                 'screenshots', 'recordings', 'replays', 'matches', 'imports',
                 'builds', 'backups', 'update'):
        (build / 'data' / name).mkdir(parents=True, exist_ok=True)


def write_launchers(build: Path) -> None:
    (build / '启动工作台.bat').write_text(STARTER_BAT, encoding='gbk')
    (build / '停止工作台.bat').write_text(STOP_BAT, encoding='gbk')
    (build / '安装OCR组件.bat').write_text(OCR_BAT, encoding='gbk')
    (build / '检查更新.bat').write_text(CHECK_BAT, encoding='gbk')
    (build / '部署说明.txt').write_text(SOP, encoding='utf-8')
    (build / '授权说明.txt').write_text(AUTH_NOTE, encoding='utf-8')


def smoke_test(build: Path, runtime: Path | None, enabled: bool = True) -> None:
    python = runtime / ('python.exe' if os.name == 'nt' else 'python') if runtime else None
    if not enabled or not python or not python.is_file():
        print('提示：跳过冒烟测试（未打包内置 Python）。')
        return
    print('冒烟测试：用内置 Python 导入 server…')
    smoke = build / '_smoke'
    smoke.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({
        'TRAINING_DB': str(smoke / 'training.sqlite3'),
        'ANALYSIS_MATCHES': str(smoke / 'matches'),
        'ANALYSIS_IMPORTS': str(smoke / 'imports'),
        'ANALYSIS_OFFICIAL': str(smoke / 'official'),
        'ANALYSIS_BUILDS': str(smoke / 'builds'),
        'KPL_RECORDINGS': str(smoke / 'recordings'),
        'MIMO_OCR_CACHE': str(smoke / 'ocr_cache'),
        'PYTHONUTF8': '1',
        'PYTHONIOENCODING': 'utf-8',
    })
    # 第二段检查 server.py 与 tools/ 的函数签名是否对得上：升级包只覆盖了一半文件时
    # `import server` 照样成功，真正炸在教练点「同步」的那一刻（v1.1.0 丢过整批对局）。
    script = '\n'.join([
        'import sys, inspect',
        f'sys.path.insert(0, {str(build)!r})',
        f'sys.path.insert(0, {str(build / "tools")!r})',
        'import server',
        'import camp_sync',
        '_sig = inspect.signature(camp_sync.sync_entries)',
        'assert "on_progress" in _sig.parameters, (',
        '    "tools/camp_sync.py 与 server.py 不同步：sync_entries 缺少 on_progress 参数，"',
        '    "发布包会在同步营地时整批失败。签名：" + str(_sig))',
    ])
    result = subprocess.run(
        [str(python), '-c', script],
        cwd=str(build), env=env, capture_output=True, text=True,
        encoding='utf-8', errors='replace', timeout=180)
    shutil.rmtree(smoke, ignore_errors=True)
    if result.returncode != 0:
        raise RuntimeError('冒烟测试失败：\n' + (result.stderr or result.stdout))
    print('冒烟测试通过。')


def zip_dir(build: Path, out: Path, root_name: str) -> None:
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(build.rglob('*')):
            arcname = (Path(root_name) / path.relative_to(build)).as_posix()
            if path.is_dir():
                info = zipfile.ZipInfo(arcname.rstrip('/') + '/')
                info.external_attr = (0o40775 << 16) | 0x10
                archive.writestr(info, '')
            else:
                archive.write(path, arcname)


def build_full(version: str, manifest: dict, args) -> dict:
    stamp = time.strftime('%Y%m%d-%H%M%S')
    build = DIST / f'build-{stamp}'
    if build.exists():
        shutil.rmtree(build)
    build.mkdir(parents=True)
    try:
        runtime = None
        if not args.skip_runtime:
            runtime = download_runtime(build, args.python_archive)
            install_deps(runtime, args.pip_index_url, args.deps_dir,
                     with_ocr=not args.no_ocr_runtime)
            ensure_pip(runtime)
        paths = ship_files()
        copy_ship_files(build, paths)
        write_data_dirs(build)
        write_launchers(build)
        (build / 'update.json').write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        smoke_test(build, runtime, enabled=not args.no_smoke)
        suffix = 'code' if args.skip_runtime else 'full'
        out = DIST / f'{PACKAGE_NAME}-{version}-{suffix}.zip'
        out.unlink(missing_ok=True)
        zip_dir(build, out, PACKAGE_NAME)
        print(f'完整包：{out.name}（{out.stat().st_size / 1024 / 1024:.0f} MB）')
        return {'url': asset_url(args.base_url, out.name),
                'sha256': sha256_file(out), 'size': out.stat().st_size}
    finally:
        shutil.rmtree(build, ignore_errors=True)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='构建免安装包与增量更新清单')
    parser.add_argument('--output', default=str(ROOT / 'dist'),
                        help='输出目录（默认 dist/）')
    parser.add_argument('--since', help='生成补丁的起始 git tag；默认自动取上一个 tag')
    parser.add_argument('--all', action='store_true', help='补丁包含全部程序文件')
    parser.add_argument('--no-patch', action='store_true', help='不生成增量包')
    parser.add_argument('--no-full', action='store_true', help='不生成完整包')
    parser.add_argument('--no-ocr-runtime', action='store_true',
                        help='精简包：不内置主 OCR 运行时（Gitee 通道 100MB 附件限制时使用）')
    parser.add_argument('--skip-runtime', action='store_true',
                        help='完整包不内置 Python（仅用于本地验证）')
    parser.add_argument('--python-archive',
                        help='本地 Python embeddable zip 路径（离线构建时使用）')
    parser.add_argument('--pip-index-url', default=DEFAULT_PIP_INDEX,
                        help=f'pip 镜像地址（默认 {DEFAULT_PIP_INDEX}）')
    parser.add_argument('--deps-dir',
                        help='离线构建时复用的 site-packages 目录，跳过 pip')
    parser.add_argument('--no-smoke', action='store_true', help='跳过冒烟测试')
    parser.add_argument('--base-url', help='更新资产的下载前缀；默认使用相对路径')
    parser.add_argument('--channel', default='stable', help='更新通道')
    parser.add_argument('--min-version', default=None,
                        help='允许增量更新的最低版本；默认=补丁基线版本'
                             '（--all 打全量补丁时为 1.0.0）')
    parser.add_argument('--plan', action='store_true', help='只打印发布内容，不构建')
    args = parser.parse_args(argv)
    return args


def main(argv=None) -> int:
    global DIST
    args = parse_args(argv)
    DIST = Path(args.output).resolve()
    DIST.mkdir(parents=True, exist_ok=True)
    meta = read_meta()
    version = meta['version']
    notes = changelog_notes(version)
    ship = ship_files()

    since = args.since
    if since is None:
        since = previous_tag(version)
    if args.min_version is None:
        # 增量包只是 since 之后的差分。门槛默认设成补丁基线版本：更老的
        # 客户端必须走完整包，否则装完后版本号是新的、内容却缺一截
        #（1.0-1.3 的用户曾能通过 1.0.0 门槛装上只含 1.4→1.5.12 差异的补丁）。
        args.min_version = '1.0.0' if args.all or not since else since.lstrip('v')
    paths, removed = (ship, []) if args.all else diff_paths(since, ship)
    paths = [path for path in paths if path not in PATCH_EXCLUDE]
    removed = [path for path in removed if path not in PATCH_EXCLUDE]
    if since and any(path in ('requirements.txt', 'requirements-ocr.txt', 'requirements-mimo.txt')
                     for path in paths):
        print('注意：依赖文件有变化。增量包不会安装新依赖；'
              '如需升级依赖，请提供完整包并提高 --min-version。')
    if not paths and not args.no_patch:
        raise SystemExit('没有检测到可发布的文件变更（可加 --all 重发全量补丁）')

    if args.plan:
        print(f"版本：{version}（{meta.get('releaseName') or '未命名'}）")
        print(f"起始 tag：{since or '全量'}")
        print(f"程序文件：{len(ship)} 个")
        print(f"补丁文件：{len(paths)} 个，删除 {len(removed)} 个")
        print(f"更新说明：{len(notes)} 条")
        for path in paths:
            print(f'  + {path}')
        for path in removed:
            print(f'  - {path}')
        return 0

    manifest = {
        'schema': 1,
        'version': version,
        'publishedAt': now_iso(),
        'channel': args.channel,
        'minVersion': args.min_version,
        'notes': notes,
        'releaseName': meta.get('releaseName', ''),
        'releaseDate': meta.get('releaseDate', ''),
    }
    if not args.no_patch:
        manifest, _ = build_patch(version, paths, removed, notes, args)
        manifest['releaseName'] = meta.get('releaseName', '')
        manifest['releaseDate'] = meta.get('releaseDate', '')
    if not args.no_full:
        manifest['full'] = build_full(version, manifest, args)
    manifest_path = DIST / 'update.json'
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                             encoding='utf-8')
    print(f'更新清单：{manifest_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
