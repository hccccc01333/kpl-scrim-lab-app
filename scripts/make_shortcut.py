"""在源码目录生成「一个图标就能打开」的快捷方式（无控制台窗口）。

为什么要这个：源码目录里的 ``启动工作台.bat`` 双击能用，但会留一个命令行窗口；
安装版没有这个问题（``KPLScrimLab.exe`` 是 PyInstaller 薄壳 + 无窗口）。这个脚本让
**源码目录**也具备同样的体验：生成一个带图标、双击即开的 ``.lnk``，
目标直接指向 ``pythonw.exe launcher.py``，不经过 cmd。

用法::

    python scripts/make_shortcut.py              # 在项目根目录生成快捷方式
    python scripts/make_shortcut.py --desktop    # 顺便放到桌面
    python scripts/make_shortcut.py --name 赛训台

生成的文件：``<项目根>/KPL赛训工具.lnk``（图标取 ``packaging/app.ico``）。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ICON = ROOT / 'packaging' / 'app.ico'


def pythonw() -> Path:
    """挑一个不弹控制台的解释器：优先内置 runtime，其次当前解释器旁边的 pythonw。"""
    candidates = [ROOT / 'runtime' / 'pythonw.exe']
    exe = Path(sys.executable)
    candidates.append(exe.with_name('pythonw.exe'))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return exe                        # 没有 pythonw 时退回 python（会有控制台窗口）


def desktop_dir() -> Path | None:
    try:
        return Path(os.path.expanduser('~')) / 'Desktop'
    except Exception:                 # noqa: BLE001
        return None


def make_shortcut(target: Path, link: Path, arguments: str = '',
                  workdir: Path | None = None, icon: Path | None = None) -> None:
    """用 WScript.Shell 写 .lnk；不引入第三方依赖。"""
    script = (
        "$ErrorActionPreference='Stop';"
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:KPL_LNK);"
        "$s.TargetPath=$env:KPL_TARGET;"
        "$s.Arguments=$env:KPL_ARGS;"
        "$s.WorkingDirectory=$env:KPL_WORKDIR;"
        + ("$s.IconLocation=$env:KPL_ICON;" if icon else '')
        + "$s.Description='KPL 赛训工作台';"
        "$s.Save()"
    )
    env = dict(os.environ,
               KPL_LNK=str(link),
               KPL_TARGET=str(target),
               KPL_ARGS=arguments,
               KPL_WORKDIR=str(workdir or ROOT),
               KPL_ICON=str(icon) if icon else '')
    subprocess.run(
        ['powershell', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
         '-Command', script],
        env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='生成无窗口的工作台快捷方式')
    parser.add_argument('--name', default='KPL赛训工具', help='快捷方式显示名')
    parser.add_argument('--desktop', action='store_true', help='同时放到桌面')
    args = parser.parse_args(argv)

    launcher = ROOT / 'launcher.py'
    if not launcher.is_file():
        print(f'找不到 launcher.py：{launcher}')
        return 1
    exe = pythonw()
    # 用 pythonw 时，launcher.py 的日志与错误对话框照旧；控制台不会再出现。
    made: list[Path] = []
    link = ROOT / f'{args.name}.lnk'
    make_shortcut(exe, link, arguments=f'"{launcher}"',
                  workdir=ROOT, icon=ICON if ICON.is_file() else None)
    made.append(link)
    if args.desktop:
        desktop = desktop_dir()
        if desktop and desktop.is_dir():
            other = desktop / f'{args.name}.lnk'
            make_shortcut(exe, other, arguments=f'"{launcher}"',
                          workdir=ROOT, icon=ICON if ICON.is_file() else None)
            made.append(other)
        else:
            print('没找到桌面目录，跳过 --desktop。')
    for path in made:
        print(f'已生成：{path}')
    print(f'双击它即可打开（解释器：{exe}）。命令行等价于：`{exe.name} launcher.py`')
    return 0


if __name__ == '__main__':
    sys.exit(main())
