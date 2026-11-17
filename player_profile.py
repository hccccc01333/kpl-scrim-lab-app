"""选手主页档案：百段 / 巅峰赛分 / 巅峰千强 / 实力 —— 可手工录，也尝试从营地自动采。

为什么要单独一份：`players-board` 里只有营地对局面板算得出的东西（胜率、KDA、参团），
百段、巅峰赛分、英雄战力这些只在选手主页上，营地对局接口不返回。

落盘：`data/player_profiles.json`，按**营地游戏名**存（不是选手ID）。
一个选手ID 可以挂多个游戏名，档案跟着号走；认领之后卡片显示的是 ID 名，
读取时用 `nicknames` 里的营地名回查，改名/合并都不会丢。

自动采集：营地 `kohcamp.qq.com` 的主页接口要求登录态（不带 cookie 返回 -30314 登录态参数不全）。
所以这里做成「有 cookie 就试，没 cookie 就明确告诉用户要什么」，采到的数值字段做一次
泛化扫描后预填，存不下的原始 JSON 一并返回，用户核对后照样能手改。
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from paths import data_root

SCHEMA = 'player-profile-v1'
POSITIONS = ('对抗路', '打野', '中路', '发育路', '游走')
STRENGTHS = ('S', 'A', 'B', 'C')
MAX_LANES = 5
MAX_HEROES = 8
MAX_BYTES = 2 * 1024 * 1024

PROFILE_PATH = Path(os.environ.get('PLAYER_PROFILE_PATH') or (data_root() / 'player_profiles.json'))
SESSION_PATH = Path(os.environ.get('PLAYER_PROFILE_SESSION') or (data_root() / 'player_profile_session.json'))

CAMP_HOST = 'https://kohcamp.qq.com'
# 网页登录：营地网页走微信/QQ 开放平台扫码，登录完成后 Cookie 落在 .qq.com 下。
# 本机开一个真浏览器窗口让用户扫，扫完从那个会话里把 Cookie 取回来 —— 比让人手抠 Cookie 稳。
# camp.qq.com 会跳到下载页，网页版营地实际在 yingdi.qq.com
WEB_LOGIN_URL = 'https://yingdi.qq.com/'
WEB_LOGIN_TTL = 240          # 窗口最多开 4 分钟
WEB_LOGIN_POLL = 1.5         # 每 1.5 秒看一次 Cookie
AUTH_COOKIE_HINTS = ('p_skey', 'skey', 'uin', 'p_uin', 'lskey', 'token', 'userid', 'openid', 'acct')
CAMP_ENDPOINTS = (
    ('POST', '/role/getplayerinfo'),
    ('GET', '/role/getplayerinfo'),
    ('POST', '/game/getplayerinfo'),
    ('POST', '/role/getroleinfo'),
)
CAMP_HEADERS = {
    'h5get': '1',
    'noencrypt': '1',
    'accept': 'application/json, text/plain, */*',
    'accept-encoding': 'identity',
    'content-type': 'application/json',
    'referer': 'https://camp.qq.com/',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36',
}


class ProfileError(ValueError):
    """档案内容不合法。"""


def _now():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')


def _int(value, lo, hi, default=None):
    if value in (None, '', '—'):
        return default
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return default
    if number < lo or number > hi:
        return default
    return number


def _text(value, limit=40):
    return str(value or '').strip()[:limit]


# ── 存储 ────────────────────────────────────────────────────────────

def _read_json(path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def load_all():
    data = _read_json(PROFILE_PATH, {})
    profiles = data.get('profiles') if isinstance(data, dict) else None
    return profiles if isinstance(profiles, dict) else {}


def all_profiles():
    return {'schema': SCHEMA, 'profiles': load_all(), 'count': len(load_all())}


def profile_of(name):
    return load_all().get(_text(name, 60))


def clear_profile(name):
    profiles = load_all()
    key = _text(name, 60)
    if key in profiles:
        profiles.pop(key)
        _write_json(PROFILE_PATH, {'schema': SCHEMA, 'profiles': profiles})
        return True
    return False


# ── 校验与写入 ──────────────────────────────────────────────────────

def normalize(body):
    """把前端提交的东西规整成可落盘的一份档案；不认识的分路直接丢，不静默改数。"""
    if not isinstance(body, dict):
        raise ProfileError('档案内容无效。')
    name = _text(body.get('name'), 60)
    if not name:
        raise ProfileError('缺少游戏名。')
    lanes = []
    for item in (body.get('lanes') or [])[:MAX_LANES]:
        if not isinstance(item, dict):
            continue
        lane = _text(item.get('lane'), 10)
        if lane not in POSITIONS:
            continue
        entry = {
            'lane': lane,
            'primary': bool(item.get('primary')),
            'segments': _int(item.get('segments'), 0, 999),
            'peak': _int(item.get('peak'), 0, 9999),
        }
        if entry['segments'] is None and entry['peak'] is None:
            continue
        lanes.append(entry)
    # 主分路只能有一个：保留第一个被标主的。
    seen_primary = False
    for entry in lanes:
        if entry['primary'] and seen_primary:
            entry['primary'] = False
        elif entry['primary']:
            seen_primary = True
    heroes = []
    for item in (body.get('heroPower') or [])[:MAX_HEROES]:
        if not isinstance(item, dict):
            continue
        hero = _text(item.get('hero'), 20)
        power = _int(item.get('power'), 0, 100000)
        if hero and power:
            heroes.append({'hero': hero, 'power': power})
    heroes.sort(key=lambda x: -x['power'])
    strength = _text(body.get('strength'), 2).upper()
    if strength not in STRENGTHS:
        strength = ''
    return {
        'name': name,
        'lanes': lanes,
        'top1000': bool(body.get('top1000')),
        'strength': strength,
        'heroPower': heroes,
        'note': _text(body.get('note'), 200),
        'source': 'camp' if body.get('source') == 'camp' else 'manual',
        'crawledAt': _text(body.get('crawledAt'), 40),
        'updatedAt': _now(),
    }


def save(body):
    profile = normalize(body)
    profiles = load_all()
    profiles[profile['name']] = profile
    _write_json(PROFILE_PATH, {'schema': SCHEMA, 'profiles': profiles})
    return profile


# ── 网页扫码登录（本机浏览器窗口） ──────────────────────────────────

_web_login = {'state': 'idle', 'message': '', 'startedAt': '', 'updatedAt': '', 'cookie': ''}
_web_login_lock = threading.Lock()
_web_login_cancel = threading.Event()
_web_login_thread = None


def _set_login(state, message=''):
    with _web_login_lock:
        _web_login['state'] = state
        _web_login['message'] = message
        _web_login['updatedAt'] = _now()
        if state in ('starting', 'waiting'):
            _web_login['startedAt'] = _now()


def web_login_status():
    with _web_login_lock:
        data = dict(_web_login)
    data['canAuto'] = bool(read_session())
    return data


def _cookie_header(cookies):
    """把浏览器 Cookie 拼成请求头；只留 .qq.com 系域名，别把无关站点的 Cookie 带出去。"""
    seen = {}
    for item in cookies:
        if 'qq.com' not in str(item.get('domain') or ''):
            continue
        name = str(item.get('name') or '')
        value = str(item.get('value') or '')
        if name and value:
            seen[name] = value
    return '; '.join(f'{key}={value}' for key, value in seen.items())


def _looks_authed(cookies):
    names = {str(item.get('name') or '').lower() for item in cookies if 'qq.com' in str(item.get('domain') or '')}
    return sum(1 for name in names if any(hint in name for hint in AUTH_COOKIE_HINTS)) >= 2


def _run_web_login():
    from playwright.sync_api import sync_playwright   # 只有扫码登录时才依赖它
    browser = None
    try:
        _set_login('waiting', '浏览器已打开营地网页：点右上角「登录」，用微信或 QQ 扫码；扫完这里会自动继续。')
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False, args=['--start-maximized'])
            context = browser.new_context(no_viewport=True)
            page = context.new_page()
            try:
                page.goto(WEB_LOGIN_URL, timeout=60000)
            except Exception:
                pass   # 页面没打开也继续等，用户自己点登录也行；Cookie 还是从会话里取
            deadline = time.time() + WEB_LOGIN_TTL
            while time.time() < deadline:
                if _web_login_cancel.is_set():
                    _set_login('canceled', '已取消扫码。')
                    return
                cookies = context.cookies()
                header = _cookie_header(cookies)
                if header and _looks_authed(cookies):
                    write_session(header)
                    _set_login('success', '已登录，Cookie 存到本机了。')
                    return
                time.sleep(WEB_LOGIN_POLL)
            _set_login('expired', '等了 4 分钟没扫完，窗口已关，再试一次。')
    except Exception as error:   # noqa: BLE001 - 任何异常都要给出可读原因
        _set_login('failed', f'打不开登录窗口：{error}')
    finally:
        try:
            if browser is not None:
                browser.close()
        except Exception:
            pass


def start_web_login():
    global _web_login_thread
    running = _web_login_thread is not None and _web_login_thread.is_alive()
    if running:
        return web_login_status()
    _web_login_cancel.clear()
    _set_login('starting', '正在打开浏览器…')
    _web_login_thread = threading.Thread(target=_run_web_login, name='camp-web-login', daemon=True)
    _web_login_thread.start()
    return web_login_status()


def cancel_web_login():
    _web_login_cancel.set()
    _set_login('canceled', '已取消扫码。')
    return web_login_status()



# ── 营地自动采集 ────────────────────────────────────────────────────

def read_session():
    data = _read_json(SESSION_PATH, {})
    return _text(data.get('cookie'), 4000) if isinstance(data, dict) else ''


def write_session(cookie):
    cookie = _text(cookie, 4000)
    if cookie:
        _write_json(SESSION_PATH, {'cookie': cookie, 'updatedAt': _now()})
    elif SESSION_PATH.exists():
        SESSION_PATH.unlink()
    return bool(cookie)


def _walk(node, path=()):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _walk(value, path + (str(key),))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, path + (str(index),))
    else:
        yield path, node


def _looks_like_peak(key_path):
    key = key_path.lower()
    return 'peak' in key and any(word in key for word in ('score', 'point', 'grade', 'fen'))


def _looks_like_segment(key_path):
    key = key_path.lower()
    return ('segment' in key or 'duan' in key) and not ('title' in key or 'name' in key)


def _looks_like_top(key_path):
    key = key_path.lower()
    return 'strong' in key or 'qianqiang' in key or 'top1000' in key or 'thousand' in key


def extract_fields(payload):
    """在未知结构里找「像巅峰分 / 像段数 / 像千强」的数值。

    营地接口的字段名会随版本变，写死一套映射很容易在某次改版后静默采到 0；
    这里返回候选值和原始路径，前端预填后让用户核对，比猜一个字段名可靠。
    """
    peak, segments, top = [], [], []
    for path, value in _walk(payload):
        key = '.'.join(path)
        if isinstance(value, bool):
            if _looks_like_top(key):
                top.append({'path': key, 'value': value})
            continue
        if not isinstance(value, (int, float)):
            continue
        if _looks_like_peak(key) and 800 <= value <= 6000:
            peak.append({'path': key, 'value': int(value)})
        elif _looks_like_segment(key) and 1 <= value <= 999:
            segments.append({'path': key, 'value': int(value)})
    peak.sort(key=lambda x: -x['value'])
    segments.sort(key=lambda x: -x['value'])
    return {
        'peak': peak[:6],
        'segments': segments[:6],
        'top1000': top[:4],
    }


def _request(method, path, role_id, cookie):
    url = CAMP_HOST + path
    headers = dict(CAMP_HEADERS)
    if cookie:
        headers['cookie'] = cookie
    body = None
    if method == 'POST':
        body = json.dumps({'roleId': role_id}, ensure_ascii=False).encode('utf-8')
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=12) as response:
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ProfileError('营地接口返回过大，已拒绝。')
    return json.loads(raw.decode('utf-8'))


def crawl(name, role_id=''):
    """试着从营地主页接口取一次。失败时把「缺什么」说清楚，前端据此提示。"""
    role_id = _text(role_id, 40)
    cookie = read_session()
    if not role_id:
        return {'ok': False, 'reason': 'no-role', 'message': '这个游戏名还没有营地账号 ID，先在「采集」里同步一次对局。'}
    if not cookie:
        return {'ok': False, 'reason': 'no-session', 'message': '营地主页接口要登录态：粘一次营地网页的 Cookie 就能自动采；不粘就直接手填。'}
    last = '未知错误'
    for method, path in CAMP_ENDPOINTS:
        try:
            payload = _request(method, path, role_id, cookie)
        except (urllib.error.URLError, OSError, ValueError) as error:
            last = f'{method} {path} 请求失败：{error}'
            continue
        if not isinstance(payload, dict):
            last = f'{method} {path} 返回的不是 JSON 对象'
            continue
        code = payload.get('returnCode')
        if str(code) not in ('0', '200'):
            last = f'{method} {path} 被营地拒绝：{payload.get("returnMsg") or code}'
            continue
        fields = extract_fields(payload)
        if not (fields['peak'] or fields['segments'] or fields['top1000']):
            return {'ok': False, 'reason': 'no-fields', 'message': '接口通了，但没认出巅峰分/段数字段（营地改过字段名），已把原始返回带回。',
                    'api': f'{method} {path}', 'fields': fields, 'raw': payload}
        return {'ok': True, 'api': f'{method} {path}', 'fields': fields,
                'raw': payload, 'name': name, 'roleId': role_id}
    return {'ok': False, 'reason': 'rejected', 'message': last}
