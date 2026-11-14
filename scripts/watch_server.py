"""Run the local server in a restart loop for daily use.

Two restart triggers:
- backend ``*.py`` files changed — finishing an edit is enough, no manual restart;
- the child server exited unexpectedly.

Static JS/CSS are served from disk on every request, so they deliberately do
not trigger a restart. Ctrl+C (or the stop script) ends both the child and the
watchdog. Logs go to ``data/watch_server.log`` so a hidden VBS launch can still
be inspected.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PID_FILE = ROOT / 'data' / 'watchdog.pid'
LOG_FILE = ROOT / 'data' / 'watch_server.log'
# 只盯会被运行中进程 import 的后端文件；静态资源改了本来就是实时读盘。
WATCH_GLOBS = ('*.py', 'v3/*.py', 'tools/*.py')
POLL_SECONDS = 1.0
QUIET_SECONDS = 1.5


_LOG_HANDLE = None


def log(message):
    """隐藏窗口启动时 stdout 可能是无效句柄，只写日志文件，绝不因打印终止守护。"""
    line = f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] {message}\n'
    handle = _LOG_HANDLE
    if handle is not None:
        try:
            handle.write(line)
            handle.flush()
            return
        except (OSError, ValueError):
            pass
    try:
        with LOG_FILE.open('a', encoding='utf-8', errors='replace') as fallback:
            fallback.write(line)
    except OSError:
        pass


def snapshot():
    state = {}
    for pattern in WATCH_GLOBS:
        for path in ROOT.glob(pattern):
            if not path.is_file():
                continue
            try:
                info = path.stat()
            except OSError:
                continue
            state[str(path)] = (info.st_mtime_ns, info.st_size)
    return state


def start_child(log_handle):
    env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    return subprocess.Popen(
        [sys.executable, str(ROOT / 'server.py')], cwd=str(ROOT), env=env,
        stdout=log_handle, stderr=subprocess.STDOUT)


def stop_child(child):
    if child is None or child.poll() is not None:
        return
    try:
        child.terminate()
    except OSError:
        return
    try:
        child.wait(timeout=6)
    except subprocess.TimeoutExpired:
        try:
            child.kill()
            child.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            pass


def apply_pending_update():
    updater = ROOT / 'updater.py'
    if not updater.is_file():
        return
    try:
        code = subprocess.call([sys.executable, str(updater), '--apply-pending'],
                               cwd=str(ROOT))
        if code != 0:
            log('待应用更新未生效，继续启动当前版本。')
    except OSError as exc:
        log(f'更新器启动失败：{exc}')


def main():
    global _LOG_HANDLE
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()), encoding='ascii')
    apply_pending_update()
    log_handle = LOG_FILE.open('a', encoding='utf-8', errors='replace')
    _LOG_HANDLE = log_handle
    child = None
    try:
        state = snapshot()
        child = start_child(log_handle)
        log(f'守护已启动（watchdog {os.getpid()} / server {child.pid}），监视后端 .py 变更。')
        while True:
            time.sleep(POLL_SECONDS)
            current = snapshot()
            if current != state:
                # 连续写文件时等一小段静默期，避免一次改动重启好几轮
                time.sleep(QUIET_SECONDS)
                state = snapshot()
                log('检测到后端代码变更，重启服务…')
                stop_child(child)
                child = start_child(log_handle)
                log(f'已重启（server {child.pid}）。')
                continue
            code = child.poll()
            if code is None:
                continue
            if code == 0:
                log('服务正常退出，守护结束。')
                return 0
            log(f'服务异常退出（{code}），2 秒后重启…')
            time.sleep(2)
            child = start_child(log_handle)
    except KeyboardInterrupt:
        log('收到 Ctrl+C，正在停止。')
        return 0
    finally:
        stop_child(child)
        try:
            log_handle.close()
        except OSError:
            pass
        PID_FILE.unlink(missing_ok=True)


if __name__ == '__main__':
    raise SystemExit(main())
