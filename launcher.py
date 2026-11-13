"""Start the workbench without a console window.

The installed shortcut points at ``KPLScrimLab.exe``, a thin launcher that
forwards to this module.  This file owns the real startup sequence: no black
window, no "keep this window open" instruction, and a readable message box
when startup fails.

Typical use (called by the EXE launcher, or manually during development)::

    runtime\\pythonw.exe launcher.py

Also supports::

    runtime\\python.exe launcher.py --stop        # graceful stop
    runtime\\python.exe launcher.py --status      # 0 running / 1 not running

Design notes
------------
* Only the standard library: the embedded Python runtime has no GUI toolkit.
* The server runs detached, so closing the browser never stops the service and
  the launcher can exit as soon as the UI is ready.
* Startup failures are written to ``logs/launcher.log`` *and* shown in a native
  message box, because a windowless process that dies silently is the worst
  possible failure mode for a coach on match day.
"""
from __future__ import annotations

import ctypes
import json
import os
import re
import socket
import subprocess
import sys
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

from paths import DATA_DIR

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / 'logs'
LAUNCHER_LOG = LOG_DIR / 'launcher.log'
SERVER_LOG = LOG_DIR / 'server.log'
MAX_LOG_BYTES = 4 * 1024 * 1024
STARTUP_TIMEOUT = 90.0
MUTEX_NAME = 'Local\\KPLScrimLab.Launcher'
ERROR_ALREADY_EXISTS = 183


def _port() -> int:
    try:
        return int(os.environ.get('TRAINING_PORT', '8766'))
    except ValueError:
        return 8766


def _host() -> str:
    return os.environ.get('TRAINING_HOST', '127.0.0.1')


def _base_url() -> str:
    host = _host()
    if host in ('0.0.0.0', '::'):
        host = '127.0.0.1'
    return f'http://{host}:{_port()}'


_VERSION_RE = re.compile(r"^VERSION\s*=\s*['\"]([^'\"]+)['\"]", re.MULTILINE)


def installed_version() -> str:
    """应用目录里 version.py 声明的版本；读不到时返回空串。"""
    try:
        text = (ROOT / 'version.py').read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return ''
    match = _VERSION_RE.search(text)
    return match.group(1).strip() if match else ''


def stale_running_version(payload: dict | None) -> str:
    """8766 上跑着的服务如果和已安装版本不一致，返回它的版本号。

    覆盖安装/手动替换文件时，如果旧服务进程没退出，Python 还在内存里跑
    旧代码；启动器这时看到 /api/health 有响应就直接开浏览器，界面就还是
    旧版本（「某些页面还是旧的」）。这里让启动器先停掉旧服务再起新的。
    任何一边版本读不出来时返回空串：宁可不动，也不要误杀正常服务。
    """
    if not isinstance(payload, dict):
        return ''
    running = str(payload.get('version') or '').strip()
    expected = installed_version()
    if running and expected and running != expected:
        return running
    return ''


def log(message: str) -> None:
    """Append one line to logs/launcher.log; never raise."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        if LAUNCHER_LOG.is_file() and LAUNCHER_LOG.stat().st_size > MAX_LOG_BYTES:
            backup = LAUNCHER_LOG.with_suffix('.log.1')
            LAUNCHER_LOG.replace(backup)
        stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(LAUNCHER_LOG, 'a', encoding='utf-8') as handle:
            handle.write(f'[{stamp}] {message}\n')
    except Exception:  # noqa: BLE001 - logging must never break startup
        pass


def message_box(text: str, title: str = 'KPL 赛训工具', error: bool = True) -> None:
    """Native message box that also works under pythonw.exe."""
    try:
        flags = 0x10 if error else 0x40  # MB_ICONERROR / MB_ICONINFORMATION
        ctypes.windll.user32.MessageBoxW(None, text, title, flags)
    except Exception:  # noqa: BLE001 - non-Windows or restricted desktop
        log(f'[message] {text}')


def health(timeout: float = 2.0) -> dict | None:
    url = f'{_base_url()}/api/health'
    try:
        with urlopen(Request(url, headers={'Accept': 'application/json'}),
                     timeout=timeout) as response:
            payload = json.loads(response.read().decode('utf-8'))
        return payload if isinstance(payload, dict) and payload.get('ok') else None
    except Exception:  # noqa: BLE001 - any failure means "not ready yet"
        return None


def port_open(port: int, host: str = '127.0.0.1') -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex((host, port)) == 0


def ensure_layout() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    for name in ('matches', 'imports', 'backups', 'update'):
        (DATA_DIR / name).mkdir(parents=True, exist_ok=True)


_MUTEX_HANDLE = None


def single_instance() -> bool:
    """True when this process owns the launcher lock.

    The handle is kept in a module global on purpose: the mutex must stay open
    while the launcher works, and Windows releases it when the process exits.
    """
    global _MUTEX_HANDLE
    try:
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_bool,
                                          ctypes.c_wchar_p)
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        if not handle:
            return True
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        _MUTEX_HANDLE = handle
        return True
    except Exception:  # noqa: BLE001 - non-Windows
        return True


def server_python() -> Path:
    """Prefer the bundled runtime; fall back to whatever launched us."""
    runtime = ROOT / 'runtime' / ('pythonw.exe' if os.name == 'nt' else 'python')
    return runtime if runtime.is_file() else Path(sys.executable)


def _rotate(path: Path) -> None:
    try:
        if path.is_file() and path.stat().st_size > MAX_LOG_BYTES:
            path.replace(path.with_suffix('.log.1'))
    except OSError:
        pass


def apply_pending_update() -> None:
    """Apply a staged patch before booting, like the old .bat wrapper did."""
    if not (ROOT / 'updater.py').is_file():
        return
    try:
        _rotate(SERVER_LOG)
        with open(SERVER_LOG, 'ab') as handle:
            subprocess.run(
                [str(server_python()), str(ROOT / 'updater.py'), '--apply-pending'],
                cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=handle,
                stderr=subprocess.STDOUT, timeout=180,
                creationflags=0x08000000 if os.name == 'nt' else 0)
    except Exception as exc:  # noqa: BLE001 - a failed update must not block boot
        log(f'应用待安装更新失败：{exc}')


def start_server() -> subprocess.Popen:
    env = os.environ.copy()
    env.setdefault('PYTHONUTF8', '1')
    env.setdefault('PYTHONIOENCODING', 'utf-8')
    _rotate(SERVER_LOG)
    handle = open(SERVER_LOG, 'ab')
    kwargs = {
        'cwd': str(ROOT),
        'env': env,
        'stdin': subprocess.DEVNULL,
        'stdout': handle,
        'stderr': subprocess.STDOUT,
        'close_fds': True,
    }
    if os.name == 'nt':
        # DETACHED_PROCESS keeps the server alive after the launcher exits;
        # CREATE_NO_WINDOW is what removes the black console for good.
        kwargs['creationflags'] = (0x00000008 | 0x08000000)  # DETACHED | NO_WINDOW
    else:
        kwargs['start_new_session'] = True
    try:
        log(f'启动服务：{server_python()} server.py')
        return subprocess.Popen([str(server_python()), str(ROOT / 'server.py')],
                                **kwargs)
    finally:
        handle.close()


def wait_ready(process: subprocess.Popen | None, timeout: float = STARTUP_TIMEOUT) -> dict | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        payload = health()
        if payload:
            return payload
        if process is not None and process.poll() is not None:
            log(f'服务进程提前退出，返回码 {process.returncode}')
            return None
        time.sleep(0.5)
    return None


def open_ui() -> None:
    url = _base_url()
    if os.environ.get('KPL_LAUNCHER_NO_BROWSER', '').strip().lower() in (
            '1', 'true', 'yes', 'on'):
        log(f'跳过打开浏览器：{url}')
        return
    try:
        if webbrowser.open(url, new=2):
            return
    except Exception:  # noqa: BLE001
        pass
    try:
        os.startfile(url)  # noqa: S606 - Windows default browser
        return
    except Exception as exc:  # noqa: BLE001
        log(f'打开浏览器失败：{exc}')
        message_box(f'服务已启动，但没能自动打开浏览器。\n\n请手动访问：{url}',
                    error=False)


def stop_server() -> int:
    payload = health()
    if not payload:
        log('停止：没有发现运行中的服务')
        return 0
    try:
        request = Request(f'{_base_url()}/api/shutdown', method='POST', data=b'',
                          headers={'Content-Type': 'application/json'})
        with urlopen(request, timeout=3) as response:
            response.read()
    except Exception as exc:  # noqa: BLE001 - fall back to the pid below
        log(f'优雅停止失败，改用结束进程：{exc}')
        try:
            subprocess.run(['taskkill', '/PID', str(payload.get('pid')), '/F'],
                           capture_output=True, timeout=10)
        except Exception as kill_exc:  # noqa: BLE001
            log(f'结束进程失败：{kill_exc}')
            return 1
    log('已请求停止服务')
    return 0


def _tail_server_log(lines: int = 12) -> str:
    try:
        content = SERVER_LOG.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return ''
    return '\n'.join(content.splitlines()[-lines:]).strip()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ensure_layout()
    # --autostart: boot the service silently at login, never steal focus.
    quiet = '--autostart' in argv

    if '--stop' in argv:
        return stop_server()
    if '--status' in argv:
        return 0 if health() else 1

    log('启动器启动')
    payload = health()
    if payload:
        stale = stale_running_version(payload)
        if not stale:
            log('服务已在运行，直接打开界面')
            if not quiet:
                open_ui()
            return 0
        # 程序文件已经换成新版本，但旧服务进程还占着 8766：先停掉再重启。
        # 旧进程的 Python 代码在内存里不会跟着文件更新，直接开浏览器就是旧界面。
        log(f'旧版本服务 v{stale} 仍在运行，先停止再启动 v{installed_version()}')
        if not stop_server() and port_open(_port()):
            if not quiet:
                message_box(f'旧版本工作台（v{stale}）没有停下，新版本无法启动。\n\n'
                            '请从开始菜单打开「停止工作台」后重试，或重启电脑。')
            log('旧服务未能停止')
            return 1

    if not single_instance():
        log('已有启动器在跑，等待服务就绪')
        if wait_ready(None, timeout=45):
            if not quiet:
                open_ui()
            return 0
        if not quiet:
            message_box('另一个启动器正在启动服务，请稍后再试。\n\n'
                        f'日志：{LAUNCHER_LOG}')
        return 1

    if port_open(_port()):
        if not quiet:
            message_box(f'端口 {_port()} 已被其他程序占用，工作台无法启动。\n\n'
                        '请关闭占用该端口的程序后重试，或设置环境变量 '
                        'TRAINING_PORT 换一个端口。')
        log(f'端口 {_port()} 被占用')
        return 1

    apply_pending_update()
    process = start_server()
    payload = wait_ready(process)
    if not payload:
        if process.poll() is None:
            try:
                process.kill()
            except Exception:  # noqa: BLE001
                pass
        detail = _tail_server_log()
        log('启动失败')
        if not quiet:
            message_box('工作台启动失败。\n\n'
                        f'日志：{SERVER_LOG}\n'
                        + (f'\n最后几行：\n{detail}' if detail else ''),
                        error=True)
        return 1

    log(f'服务就绪 v{payload.get("version", "?")} pid={payload.get("pid")}')
    if not quiet:
        open_ui()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
