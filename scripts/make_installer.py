"""Build the Windows installer (``KPL-Scrim-Lab-<版本>-setup.exe``).

The installer wraps the *portable* full package instead of rebuilding the
runtime: ``dist/KPL-Scrim-Lab-<版本>-full.zip`` already contains the embedded
Python, dependencies and data skeleton.  Current program files from the working
tree are overlaid on top, so an installer can be produced after ordinary code
changes without a 60 MB runtime rebuild.

Usage::

    python scripts/make_installer.py              # 复用现有 full 包
    python scripts/make_installer.py --rebuild    # 重新生成 full 包再打包
    python scripts/make_installer.py --iscc "C:\\...\\ISCC.exe"

The Inno Setup script lives in ``packaging/installer.iss``.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from make_release import (  # noqa: E402
    PACKAGE_NAME, STARTER_BAT, STOP_BAT, _junk_file, ship_files,
)

DIST = ROOT / 'dist'
PACKAGING = ROOT / 'packaging'
ISS = PACKAGING / 'installer.iss'
ICON = PACKAGING / 'app.ico'
SOURCE_DIR = DIST / '_installer'
ISCC_CANDIDATES = [
    Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs' / 'Inno Setup 6' / 'ISCC.exe',
    Path(r'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'),
    Path(r'C:\Program Files\Inno Setup 6\ISCC.exe'),
]


def read_version() -> str:
    text = (ROOT / 'version.py').read_text(encoding='utf-8')
    match = re.search(r"^VERSION\s*=\s*['\"]([^'\"]+)['\"]", text, re.MULTILINE)
    if not match:
        raise RuntimeError('version.py 中缺少 VERSION')
    return match.group(1)


def find_iscc(explicit: str | None) -> Path:
    for candidate in ([Path(explicit)] if explicit else []) + ISCC_CANDIDATES:
        if candidate and candidate.is_file():
            return candidate
    found = shutil.which('ISCC')
    if found:
        return Path(found)
    raise RuntimeError(
        '未找到 Inno Setup 6 的 ISCC.exe。安装方式：\n'
        '  winget install -e --id JRSoftware.InnoSetup\n'
        '或用 --iscc 指定完整路径。')


def full_zip(version: str) -> Path:
    return DIST / f'{PACKAGE_NAME}-{version}-full.zip'


def build_full(version: str) -> Path:
    print('未找到完整包，先构建（内置 Python + 依赖，约 1-3 分钟）…')
    subprocess.run([sys.executable, str(ROOT / 'scripts' / 'make_release.py'),
                    '--no-patch', '--output', str(DIST)],
                   cwd=str(ROOT), check=True)
    path = full_zip(version)
    if not path.is_file():
        raise RuntimeError(f'完整包构建后仍未找到：{path}')
    return path


def extract(archive: Path) -> Path:
    if SOURCE_DIR.exists():
        shutil.rmtree(SOURCE_DIR)
    SOURCE_DIR.mkdir(parents=True)
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            parts = Path(member.filename).parts
            # 去掉 zip 顶层目录（KPL赛训工具/），让内容直接落在 SOURCE_DIR
            relative = Path(*parts[1:]) if len(parts) > 1 else None
            if relative is None:
                continue
            target = SOURCE_DIR / relative
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(member) as source, open(target, 'wb') as destination:
                shutil.copyfileobj(source, destination)
    return SOURCE_DIR


def overlay(tree: Path) -> None:
    """把当前工作树的程序文件覆盖到解包目录上，保证安装包是最新代码。"""
    files = ship_files()
    for relative in files:
        source = ROOT / relative
        target = tree / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    for extra in ('launcher.py', 'version.py'):
        source = ROOT / extra
        if source.is_file():
            shutil.copy2(source, tree / extra)
    shutil.copy2(ICON, tree / 'app.ico')
    # EXE 启动器（PyInstaller onedir）：exe + _internal 一起落到安装根目录。
    launcher_tree = PACKAGING / 'launcher-dist' / 'KPLScrimLab'
    if not launcher_tree.is_dir():
        raise RuntimeError('缺少 EXE 启动器，先运行 python packaging/make_launcher.py')
    shutil.copytree(launcher_tree, tree, dirs_exist_ok=True)
    # 旧包可能残留作者本机的临时脚本，安装包不要带出去（不碰 runtime）。
    for stale in list(tree.glob('.*.py')) + list(tree.glob('_*.py')):
        stale.unlink(missing_ok=True)
    runtime_dir = (tree / 'runtime').resolve()
    for stale in tree.rglob('*'):
        if not stale.is_file() or runtime_dir in stale.resolve().parents:
            continue
        if _junk_file(stale.name):
            stale.unlink(missing_ok=True)
    # 启动/停止脚本以当前模板为准（旧版是 python.exe 前台运行）。
    (tree / '启动工作台.bat').write_text(STARTER_BAT, encoding='gbk')
    (tree / '停止工作台.bat').write_text(STOP_BAT, encoding='gbk')
    print(f'覆盖 {len(files)} 个程序文件到安装源目录')


def version4(version: str) -> str:
    parts = [part for part in re.split(r'[.\-+]', version) if part.isdigit()]
    while len(parts) < 4:
        parts.append('0')
    return '.'.join(parts[:4])


def write_hash(setup: Path) -> str:
    """Write ``<setup>.sha256`` next to the installer and return the digest.

    没有代码签名时，发布渠道里附一个哈希值是最便宜的「可核对」手段：
    作者在群里发一行哈希，收到包的人本地算一遍就能确认没被替换。
    """
    import hashlib

    digest = hashlib.sha256()
    with open(setup, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    value = digest.hexdigest()
    (setup.parent / (setup.name + '.sha256')).write_text(
        f'{value}  {setup.name}\n', encoding='utf-8')
    return value


def compile_installer(iscc: Path, version: str, output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    command = [
        str(iscc), '/Qp',
        f'/DAppVersion={version}',
        f'/DAppVersion4={version4(version)}',
        f'/DSourceDir={SOURCE_DIR}',
        f'/DOutputDir={output}',
        str(ISS),
    ]
    print('编译安装包：' + ' '.join(command))
    result = subprocess.run(command, cwd=str(ROOT), text=True,
                            encoding='utf-8', errors='replace',
                            capture_output=True)
    if result.returncode != 0:
        raise RuntimeError('ISCC 编译失败：\n' + (result.stdout or '') +
                           (result.stderr or ''))
    if result.stdout.strip():
        print(result.stdout.strip())
    setup = output / f'{PACKAGE_NAME}-{version}-setup.exe'
    if not setup.is_file():
        raise RuntimeError(f'编译完成但未找到安装包：{setup}')
    return setup


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='构建 Windows 安装包')
    parser.add_argument('--rebuild', action='store_true',
                        help='重新构建 full 包（改了依赖或内置 Python 版本时用）')
    parser.add_argument('--iscc', help='ISCC.exe 路径（默认自动查找）')
    parser.add_argument('--output', default=str(DIST))
    parser.add_argument('--keep-source', action='store_true',
                        help='保留 dist/_installer 便于排查')
    args = parser.parse_args(argv)

    version = read_version()
    iscc = find_iscc(args.iscc)
    print(f'版本：{version}')
    print(f'Inno Setup：{iscc}')
    if not ICON.is_file():
        print('缺少图标，先生成…')
        subprocess.run([sys.executable, str(PACKAGING / 'make_icon.py')],
                       cwd=str(ROOT), check=True)

    print('构建 EXE 启动器…')
    subprocess.run([sys.executable, str(PACKAGING / 'make_launcher.py')],
                   cwd=str(ROOT), check=True)

    archive = full_zip(version)
    if args.rebuild or not archive.is_file():
        archive = build_full(version)
    print(f'完整包：{archive.name}（{archive.stat().st_size / 1024 / 1024:.0f} MB）')

    tree = extract(archive)
    overlay(tree)
    setup = compile_installer(iscc, version, Path(args.output).resolve())
    digest = write_hash(setup)
    print(f'安装包：{setup}（{setup.stat().st_size / 1024 / 1024:.0f} MB）')
    print(f'SHA-256：{digest}')

    if not args.keep_source:
        shutil.rmtree(SOURCE_DIR, ignore_errors=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
