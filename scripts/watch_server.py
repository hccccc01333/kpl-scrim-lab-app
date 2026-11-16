"""Run the local server in a restart loop for daily use.

Three restart triggers:
- backend ``*.py`` files changed — finishing an edit is enough, no manual restart;
- the child server exited unexpectedly (restarted);
- the child server exited cleanly (watchdog ends, same as before).

Static JS/CSS are served from disk on every request, so they deliberately do
not trigger a restart. Ctrl+C (or the stop script) ends both the child and the
watchdog. Logs go to ``data/watch_server.log`` so a hidden VBS launch can still
be inspected.

**Attach mode.** Windows lets two processes bind the same port with
``SO_REUSEADDR``, so "start another one" is how you end up with two servers
fighting over 8766 (one gets ``POST /api/shutdown``, the other keeps serving,
and the watchdog then exits because the child exited with code 0). When the port
is already served, this script therefore *attaches* instead of spawning: it only
watches files. On the next code change it asks the running server to stop
gracefully, waits for the port to free up, and then starts the one child it owns.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PID_FILE = ROOT / 'data' / 'watchdog.pid'
LOG_FILE = ROOT / 'data' / 'watch_server.log'
# 只盯会被运行中进程 import 的后端文件；静态资源改了本来就是实时读盘。
WATCH_GLOBS = ('*.py', 'v3/*.py', 'tools/*.py')
POLL_SECONDS = 1.0
QUIET_SECONDS = 1.5
PORT = int(os.environ.get('KPL_PORT', os.environ.get('TRAINING_PORT', '8766')))


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


def _opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def live_pid(port=PORT):
    """端口上已经有服务时返回它的 pid，否则 None。"""
    try:
        with _opener().open(f'http://127.0.0.1:{port}/api/health', timeout=1.5) as response:
            payload = json.loads(response.read().decode('utf-8', 'replace'))
        return payload.get('pid')
    except (OSError, ValueError, urllib.error.URLError):
        return None


def port_free(port=PORT):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.6)
        return probe.connect_ex(('127.0.0.1', port)) != 0


def wait_port_free(port=PORT, timeout=12.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_free(port):
            return True
        time.sleep(0.3)
    return port_free(port)


def ask_existing_to_stop(port=PORT):
    """让当前占用端口的服务优雅退出；它自己会 os._exit(0)。"""
    request = urllib.request.Request(
        f'http://127.0.0.1:{port}/api/shutdown', data=b'{}', method='POST',
        headers={'Content-Type': 'application/json'})
    try:
        with _opener().open(request, timeout=3) as response:
            response.read()
        return True
    except (OSError, urllib.error.URLError):
        return False


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
        running = live_pid()
        if running:
            # 端口已有人守着：不另起，避免两个进程同时绑 8766。
            log(f'端口 {PORT} 已有服务（pid {running}），附着监视，不另起进程。')
        else:
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
                child = None
                if not wait_port_free():
                    if ask_existing_to_stop() and wait_port_free():
                        log('已请现有服务退出。')
                    else:
                        log(f'端口 {PORT} 仍被占用，本轮不重启。')
                        continue
                child = start_child(log_handle)
                log(f'已重启（server {child.pid}）。')
                continue
            if child is None:
                # 附着模式下由别人托管：它挂了就接管，别让页面空着。
                if not live_pid():
                    time.sleep(1.0)
                    if not live_pid() and port_free():
                        child = start_child(log_handle)
                        log(f'现有服务已退出，接管启动（server {child.pid}）。')
                continue
            code = child.poll()
            if code is None:
                continue
            if code == 0:
                # 被别人优雅停掉时，机器上通常紧接着又起来一个（启动器 / 另一个会话在重启，
                # 它自己的流程是「先停、再起」，中间可能空几秒到十几秒）。
                # 给 20 秒窗口：端口上重新出现服务就转附着，一直空着才认定是人为停止。
                deadline = time.time() + 20
                while time.time() < deadline:
                    time.sleep(1.0)
                    if live_pid():
                        break
                if live_pid():
                    log('服务被外部重启，转为附着监视。')
                    child = None
                    state = snapshot()
                    continue
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
