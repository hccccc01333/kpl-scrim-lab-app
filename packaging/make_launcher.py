"""Build ``KPLScrimLab.exe`` — the installed copy's double-click entry point.

The launcher is a thin PyInstaller onedir bundle: the exe itself only locates
``runtime\\pythonw.exe`` and forwards to ``launcher.py``.  onedir is chosen over
onefile because it starts instantly and is far less likely to trip antivirus
heuristics; the install package already ships a full runtime, so the extra
~12 MB is acceptable.

Usage::

    python packaging/make_launcher.py            # 复用已构建的 exe
    python packaging/make_launcher.py --force    # 强制重建
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / 'packaging'
DIST = PACKAGING / 'launcher-dist'
WORK = ROOT / 'dist' / '_pyi'
NAME = 'KPLScrimLab'
SOURCE = PACKAGING / 'launcher_exe.py'
ICON = PACKAGING / 'app.ico'


def read_version() -> str:
    text = (ROOT / 'version.py').read_text(encoding='utf-8')
    match = re.search(r"^VERSION\s*=\s*['\"]([^'\"]+)['\"]", text, re.MULTILINE)
    return match.group(1) if match else '0.0.0'


def _version_tuple(version: str) -> tuple[int, int, int, int]:
    parts = [int(p) for p in re.split(r'[.\-+]', version) if p.isdigit()][:4]
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts)  # type: ignore[return-value]


def _write_version_file(version: str) -> Path:
    WORK.mkdir(parents=True, exist_ok=True)
    target = WORK / 'version_info.txt'
    vt = _version_tuple(version)
    target.write_text(f'''VSVersionInfo(
  ffi=FixedFileInfo(filevers={vt}, prodvers={vt}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0,0)),
  kids=[
    StringFileInfo([StringTable('080404B0', [
      StringStruct('CompanyName', 'KPL 赛训工具'),
      StringStruct('FileDescription', 'KPL 赛训工具启动器'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('ProductName', 'KPL 赛训工具'),
      StringStruct('ProductVersion', '{version}'),
      StringStruct('OriginalFilename', '{NAME}.exe')])]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)''', encoding='utf-8')
    return target


def exe_path() -> Path:
    return DIST / NAME / f'{NAME}.exe'


def build(force: bool = False) -> Path:
    target = exe_path()
    if target.is_file() and not force:
        newest = max(SOURCE.stat().st_mtime, ICON.stat().st_mtime,
                     (ROOT / 'version.py').stat().st_mtime)
        if target.stat().st_mtime >= newest:
            return target
    try:
        import PyInstaller  # noqa: F401
    except ImportError as exc:  # pragma: no cover - build-time guidance
        raise SystemExit('缺少 PyInstaller。先运行：\n  python -m pip install pyinstaller') from exc

    version = read_version()
    version_file = _write_version_file(version)
    WORK.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable, '-m', 'PyInstaller',
        '--noconfirm', '--clean', '--onedir', '--noconsole',
        '--name', NAME,
        '--icon', str(ICON),
        '--version-file', str(version_file),
        '--distpath', str(DIST),
        '--workpath', str(WORK),
        '--specpath', str(WORK),
        str(SOURCE),
    ]
    print('构建 EXE 启动器：' + ' '.join(command))
    result = subprocess.run(command, cwd=str(ROOT), text=True,
                            encoding='utf-8', errors='replace', capture_output=True)
    if result.returncode != 0:
        raise RuntimeError('PyInstaller 构建失败：\n' + (result.stdout or '') + (result.stderr or ''))
    if not target.is_file():
        raise RuntimeError(f'构建完成但未找到启动器：{target}')
    print(f'启动器：{target}（{target.stat().st_size / 1024 / 1024:.1f} MB）')
    return target


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='构建安装版 EXE 启动器')
    parser.add_argument('--force', action='store_true', help='忽略缓存强制重建')
    args = parser.parse_args(argv)
    build(force=args.force)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
