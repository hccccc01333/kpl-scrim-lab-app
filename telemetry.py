"""匿名使用统计心跳（客户端）。

作者只想看到「大概多少台机器在用、有多少活跃」，不需要任何可识别身份的信息。
本模块因此在**本地**生成一个随机安装 ID，按固定周期向统计服务发一条不含主机名、
用户名、路径、战队或对局内容的心跳。它遵守三条硬约束：

* **不阻塞启动**：``maybe_ping()`` 只起 daemon 线程，先等几秒再联网；服务端照常起。
* **离线静默**：任何异常（无网络、统计服务没开、清单里没有 ``stats``）都吞掉，
  最多在 ``data/usage/last_ping.json`` 记一笔，方便作者排查，绝不弹窗/报错。
* **可随时停用**：环境变量 ``KPL_TELEMETRY=0`` 或存在 ``data/usage/optout`` 文件
  时完全不联网、也不创建安装 ID。

统计地址来自更新清单（``update.json`` 的可选顶层字段 ``stats``），复用
``update_client.check_for_update`` 的 6 小时缓存；因此以后开统计、换统计服务
都不需要重新发版。协议：``POST <stats.url>``，JSON 字段见 ``build_payload()``。

数据目录遵循 ``paths.data_root()``：默认 ``<应用根>/data/usage/``，设置
``KPL_DATA_DIR`` 时跟着走（测试与多实例用）。
"""
from __future__ import annotations

import json
import os
import platform
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import update_client
from paths import ROOT as APP_ROOT, data_root

# 心跳协议版本。统计服务按 schema 兼容旧客户端；字段只增不改。
SCHEMA = 1
APP_NAME = 'kpl-scrim-lab'
DEFAULT_PERIOD_HOURS = update_client.DEFAULT_STATS_PERIOD_HOURS
# 失败（DNS/超时/5xx）后最多每小时重试一次，避免离线机器每次启动都硬等网络。
RETRY_SECONDS = 3600.0
# 单次 HTTP 超时；心跳线程是 daemon，超时也不会拖住退出。
TIMEOUT_SECONDS = 6.0
# 启动后先等几秒，把网络/CPU 让给工作台本身。
STARTUP_DELAY_SECONDS = 5.0
ENV_NAME = 'KPL_TELEMETRY'
USER_AGENT = 'KPL-Scrim-Lab-Telemetry/1.0'
_OFF_VALUES = ('0', 'false', 'off', 'no')
_INSTALL_ID_RE = re.compile(r'^[0-9a-f]{32}$')
_MAX_TEXT = 128

_thread_lock = threading.Lock()
_identity_lock = threading.Lock()
_thread: threading.Thread | None = None


# ---------------------------------------------------------------------------
# 本地文件：安装 ID / 首次心跳时间 / 节流状态 / opt-out 标记
# ---------------------------------------------------------------------------
def usage_dir(root: Path | str | None = None) -> Path:
    """``<data>/usage``：安装 ID、节流状态与 opt-out 标记都放这里。"""
    return data_root(root) / 'usage'


def install_id_path(root: Path | str | None = None) -> Path:
    return usage_dir(root) / 'install_id.txt'


def first_seen_path(root: Path | str | None = None) -> Path:
    return usage_dir(root) / 'first_seen.txt'


def last_ping_path(root: Path | str | None = None) -> Path:
    return usage_dir(root) / 'last_ping.json'


def optout_path(root: Path | str | None = None) -> Path:
    return usage_dir(root) / 'optout'


def is_disabled(root: Path | str | None = None, env: dict | None = None) -> bool:
    """``KPL_TELEMETRY=0/false/off/no`` 或 ``data/usage/optout`` 存在即停用。"""
    source = env if env is not None else os.environ
    value = str(source.get(ENV_NAME, '') or '').strip().lower()
    if value in _OFF_VALUES:
        return True
    try:
        return optout_path(root).exists()
    except OSError:
        return False


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding='utf-8').strip()
    except OSError:
        return ''


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(text, encoding='utf-8')
    os.replace(temp, path)


def _iso(ts: float | None = None) -> str:
    moment = datetime.fromtimestamp(time.time() if ts is None else ts, tz=timezone.utc)
    return moment.isoformat(timespec='seconds')


def load_install_id(root: Path | str | None = None) -> str:
    """读取（必要时懒创建并持久化）随机安装 ID：uuid4 的 32 位十六进制。"""
    path = install_id_path(root)
    with _identity_lock:
        existing = _read_text(path)
        if _INSTALL_ID_RE.match(existing):
            return existing
        install_id = uuid.uuid4().hex
        try:
            _write_atomic(path, install_id + '\n')
        except OSError:
            pass
        return install_id


def load_first_seen(root: Path | str | None = None) -> str:
    """读取（必要时懒创建）本安装第一次心跳的 ISO 时间（UTC）。"""
    path = first_seen_path(root)
    with _identity_lock:
        existing = _read_text(path)
        if existing:
            return existing
        stamp = _iso()
        try:
            _write_atomic(path, stamp + '\n')
        except OSError:
            pass
        return stamp


def read_state(root: Path | str | None = None) -> dict:
    """读取 ``last_ping.json``；损坏/缺失时当作空状态，绝不抛错。"""
    try:
        payload = json.loads(last_ping_path(root).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _state_number(state: dict, key: str) -> float:
    try:
        return float(state.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def _record_attempt(root: Path | str | None, now: float, *, success: bool,
                    error: str = '') -> None:
    """写节流状态；任何 I/O 失败都吞掉（统计绝不能影响工作台）。"""
    try:
        state = read_state(root)
        state['lastAttempt'] = round(float(now), 3)
        if success:
            state['lastSuccess'] = round(float(now), 3)
            state['lastPingAt'] = _iso(now)
            state.pop('lastError', None)
        else:
            state['lastError'] = str(error)[:200]
        _write_atomic(last_ping_path(root),
                      json.dumps(state, ensure_ascii=False, indent=2) + '\n')
    except Exception:  # noqa: BLE001 - 统计是尽力而为，不允许冒泡
        pass


# ---------------------------------------------------------------------------
# 节流
# ---------------------------------------------------------------------------
def normalize_period_hours(value=None) -> int:
    """``periodHours`` 只接受 1..168 的整数，其余回落到默认 20。"""
    if isinstance(value, bool) or not isinstance(value, int):
        return DEFAULT_PERIOD_HOURS
    return value if 1 <= value <= 168 else DEFAULT_PERIOD_HOURS


def should_ping(root: Path | str | None = None, now: float | None = None,
                period_hours: int | None = None) -> bool:
    """成功后在 ``periodHours`` 内不再发；失败后至少隔 1 小时再试。"""
    moment = time.time() if now is None else float(now)
    period = normalize_period_hours(period_hours)
    state = read_state(root)
    last_success = _state_number(state, 'lastSuccess')
    if last_success > 0 and moment - last_success < period * 3600.0:
        return False
    last_attempt = _state_number(state, 'lastAttempt')
    if last_attempt > 0 and moment - last_attempt < RETRY_SECONDS:
        return False
    return True


# ---------------------------------------------------------------------------
# 清单里的统计配置 + 心跳
# ---------------------------------------------------------------------------
def stats_from_result(result) -> dict | None:
    """从 ``check_for_update`` 结果里取 ``stats``；不合法/未启用返回 ``None``。"""
    if not isinstance(result, dict) or not result.get('ok'):
        return None
    stats = result.get('stats')
    if stats is None:
        manifest = result.get('manifest')
        if isinstance(manifest, dict):
            stats = manifest.get('stats')
    if not isinstance(stats, dict):
        return None
    url = str(stats.get('url', '') or '').strip()
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        return None
    return {'url': url, 'periodHours': normalize_period_hours(stats.get('periodHours'))}


def build_payload(root: Path | str | None = None, version: str = '',
                  now: float | None = None) -> dict:
    """组装心跳 JSON。

    只有下面这些字段，**没有**主机名 / 用户名 / 路径 / 战队 / 对局内容：

    ==========  ==========================================================
    schema      心跳协议版本，固定 1
    app         应用标识，固定 ``kpl-scrim-lab``
    installId   本地随机生成的安装 ID（uuid4 hex，不关联任何账号）
    version     当前应用版本，如 ``1.6.3``
    os          ``platform.system()``，如 ``Windows``
    osVersion   ``platform.release()``，如 ``10``
    arch        ``platform.machine()``，如 ``AMD64``
    startedAt   本次启动后第一次尝试心跳的时间（ISO 8601 UTC）
    firstSeen   本安装第一次心跳的时间（ISO 8601 UTC）
    ==========  ==========================================================
    """
    moment = time.time() if now is None else float(now)
    return {
        'schema': SCHEMA,
        'app': APP_NAME,
        'installId': load_install_id(root),
        'version': str(version or '')[:64],
        'os': str(platform.system() or '')[:64],
        'osVersion': str(platform.release() or '')[:_MAX_TEXT],
        'arch': str(platform.machine() or '')[:64],
        'startedAt': _iso(moment),
        'firstSeen': load_first_seen(root),
    }


def post_ping(url: str, payload: dict, timeout: float = TIMEOUT_SECONDS) -> int:
    """POST 一条心跳；``urlopen`` 在模块级 import，方便测试 mock。"""
    parsed = urlparse(str(url or ''))
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise ValueError(f'统计地址无效：{url!r}')
    body = json.dumps(payload, ensure_ascii=False,
                      separators=(',', ':')).encode('utf-8')
    request = Request(url, data=body, method='POST', headers={
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'User-Agent': USER_AGENT,
    })
    with urlopen(request, timeout=timeout) as response:
        response.read(1024)  # 读完响应，释放连接
        return int(getattr(response, 'status', 0) or 0)


def ping_once(root: Path | str | None = None, version: str = '',
              now: float | None = None, env: dict | None = None,
              update_result: dict | None = None) -> dict:
    """同步执行一次心跳（测试入口；正式启动请用 ``maybe_ping``）。

    返回值仅用于测试/排查，永远不会抛异常：
    ``{'ok': True, 'url': ..., 'periodHours': ...}`` 或
    ``{'ok': False, 'reason': 'disabled' | 'no-stats' | 'throttled' | 'error'}``。
    """
    moment = time.time() if now is None else float(now)
    try:
        if is_disabled(root, env):
            return {'ok': False, 'reason': 'disabled'}
        if update_result is None:
            update_result = update_client.check_for_update(
                Path(root) if root is not None else APP_ROOT, version)
        stats = stats_from_result(update_result)
        if not stats:
            return {'ok': False, 'reason': 'no-stats'}
        if not should_ping(root, moment, stats['periodHours']):
            return {'ok': False, 'reason': 'throttled'}
        payload = build_payload(root, version, moment)
        post_ping(stats['url'], payload)
    except Exception as exc:  # noqa: BLE001 - 离线/服务异常一律静默
        detail = f'{type(exc).__name__}: {exc}'
        _record_attempt(root, moment, success=False, error=detail)
        return {'ok': False, 'reason': 'error', 'error': detail}
    _record_attempt(root, moment, success=True)
    return {'ok': True, 'url': stats['url'], 'periodHours': stats['periodHours']}


def _ping_worker(root: Path, version: str, delay: float | None) -> None:
    try:
        seconds = STARTUP_DELAY_SECONDS if delay is None else float(delay)
        if seconds > 0:
            time.sleep(seconds)
        ping_once(root, version)
    except Exception:  # noqa: BLE001 - daemon 线程里也不允许冒泡
        pass


def maybe_ping(root: Path | str | None = None, version: str = '',
               delay: float | None = None) -> threading.Thread | None:
    """启动后调用：起一个 daemon 线程延迟发心跳，**立即返回**、绝不阻塞。

    同一进程只保留一个心跳线程；停用状态或创建失败返回 ``None``。
    """
    global _thread
    try:
        if is_disabled(root):
            return None
        with _thread_lock:
            if _thread is not None and _thread.is_alive():
                return None
            thread = threading.Thread(
                target=_ping_worker,
                args=(Path(root) if root is not None else APP_ROOT,
                      str(version), delay),
                name='kpl-telemetry', daemon=True)
            _thread = thread
        thread.start()
        return thread
    except Exception:  # noqa: BLE001 - 统计绝不允许影响启动
        return None
