"""KPL 赛训工具 —— 安装版的 EXE 启动器（双击入口）。

这个 exe 只做三件事，保持极薄：

1. 找到安装目录里的 ``runtime\\pythonw.exe`` 与 ``launcher.py``；
2. 把命令行参数原样传过去（``--stop`` / ``--status`` / ``--autostart``）；
3. 启动失败时弹一个原生错误框。

真正的启动、健康检查、打开浏览器、日志与错误提示都在 ``launcher.py``，
这里不重复实现，避免两套逻辑分叉。

构建：``python packaging/make_launcher.py``（PyInstaller onedir）。
"""
from __future__ import annotations

import ctypes
import subprocess
import sys
from pathlib import Path

TITLE = 'KPL 赛训工具'


def _root() -> Path:
    """安装目录。PyInstaller onedir 下 exe 就在安装根目录。"""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _message(text: str, error: bool = True) -> None:
    try:
        flags = 0x10 if error else 0x40  # MB_ICONERROR / MB_ICONINFORMATION
        ctypes.windll.user32.MessageBoxW(None, text, TITLE, flags)
    except Exception:  # noqa: BLE001 - 没有桌面时静默
        pass


def _python(root: Path) -> Path | None:
    runtime = root / 'runtime'
    for name in ('pythonw.exe', 'python.exe'):
        candidate = runtime / name
        if candidate.is_file():
            return candidate
    # 源码目录直接运行（没有内置 runtime）时用于本地验证。
    if not getattr(sys, 'frozen', False) and Path(sys.executable).is_file():
        return Path(sys.executable)
    return None


def main() -> int:
    root = _root()
    script = root / 'launcher.py'
    if not script.is_file():
        _message('找不到 launcher.py，安装可能不完整。\n\n'
                 '请重新安装；如果仍然失败，把安装目录下的 logs 文件夹发给支持人员。')
        return 1
    python = _python(root)
    if python is None:
        _message('找不到内置运行时（runtime\\pythonw.exe）。\n\n'
                 '安装可能不完整，请重新运行安装程序。')
        return 1

    command = [str(python), str(script), *sys.argv[1:]]
    try:
        process = subprocess.Popen(command, cwd=str(root), close_fds=True)
    except Exception as exc:  # noqa: BLE001 - 启动失败要让人看见
        _message(f'工作台没能启动：\n{exc}\n\n日志目录：{root / "logs"}')
        return 1

    # --stop / --status 是开始菜单和脚本调用的，需要把退出码带回去；
    # 普通双击不等待，launcher.py 自己会在服务就绪后打开浏览器。
    if any(arg in ('--stop', '--status') for arg in sys.argv[1:]):
        return process.wait()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
