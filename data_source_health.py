"""外部数据源爬取体检：给「管理 → 外部数据源」页提供状态与重试入口。

只读各数据源自己的状态文件（peak/state.json、kpl/manifest.json、catalog.json、
hero_tags.json、hero_external_stats.json），不另建一套真相；「重试」则复用项目
各自的爬取/同步入口，避免两处逻辑漂移。

自动同步：真实服务启动时 auto_sync_heroes() 会在后台检查外部数据里出现、
但英雄名录还没有的英雄，联网补名字/头像；失败只记录到状态里，不影响启动。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CATALOG = ROOT / 'resources' / 'catalog.json'
TAGS = ROOT / 'resources' / 'hero_tags.json'
HERO_LIST = ROOT / 'data' / 'hero_list.json'
KPL_MANIFEST = ROOT / 'data' / 'kpl' / 'manifest.json'
KPL_MANIFEST_SEED = ROOT / 'resources' / 'builtin' / 'misc' / 'manifest.json'
ROLE_POOLS = ROOT / 'data' / 'peak' / 'matchup_raw' / 'role_pools.json'
ROLE_POOLS_SEED = ROOT / 'resources' / 'builtin' / 'peak' / 'matchup_raw' / 'role_pools.json'

SOURCES = (
    {'key': 'heroes', 'name': '英雄名录与头像', 'icon': 'heroes',
     'description': '官方英雄名、heroId、头像；新英雄自动发现并补齐',
     'auto': '启动时自动检查，发现新英雄即联网同步'},
    {'key': 'kpl', 'name': 'KPL 逐局 BP', 'icon': 'bp',
     'description': '官方逐局禁选与战队归属，每日自动增量补抓',
     'auto': '巅峰千强每日任务内自动增量补抓'},
    {'key': 'peak', 'name': '巅峰千强大盘', 'icon': 'cross',
     'description': '英雄登场 / 胜率 / 对位与分路池（91m）',
     'auto': '每天首次启动自动刷新（可用 PEAK_AUTO_CRAWL=0 关闭）'},
    {'key': 'stats', 'name': '国服战力与英雄榜', 'icon': 'players',
     'description': '国服前十战力分、KPL 胜率与各分位评分',
     'auto': '随巅峰千强每日任务重算'},
)

_STATE = {'running': {}, 'last': {}}
_LOCK = threading.Lock()


def _json(path: Path, fallback=None):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return fallback


def _stamp(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    except OSError:
        return ''


def _age_days(stamp: str) -> float | None:
    if not stamp:
        return None
    try:
        moment = datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - moment).total_seconds() / 86400
    except (TypeError, ValueError):
        return None


def _norm_hero(name) -> str:
    """元流之子(刺客) / 元流之子_刺客 是同一个英雄，只比核心字。"""
    import re
    return re.sub(r'[()（）_\s·\-]', '', str(name or ''))


# 外部数据里以「形态名」出现的条目，不是独立英雄（李信的两种形态）。
FORM_ALIASES = {'光信_统御', '暗信_狂暴'}


def _external_hero_names() -> set[str]:
    """外部数据里出现过的英雄名 —— 名录缺谁，靠这里发现，不靠手工上报。"""
    names: set[str] = set()
    pools = _json(ROLE_POOLS if ROLE_POOLS.is_file() else ROLE_POOLS_SEED, {}) or {}
    for rows in pools.values():
        for row in rows or []:
            name = str(row.get('hero_name') or '').strip()
            if name:
                names.add(name)
    stats_path = ROOT / 'data' / 'facts' / 'hero_external_stats.json'
    stats = _json(stats_path, {}) or {}
    for section in stats.values():
        if isinstance(section, dict):
            names.update(str(k).strip() for k in section if k)
    return {name for name in names if 2 <= len(name) <= 10}


def _card(key, status, label, detail, updated_at, count, auto, hint=''):
    with _LOCK:
        running = dict(_STATE['running'].get(key) or {})
        last = dict(_STATE['last'].get(key) or {})
    if running:
        status, label = 'running', '正在爬取'
        detail = running.get('message') or '后台任务进行中，稍等片刻…'
    return {'key': key, 'name': next(s['name'] for s in SOURCES if s['key'] == key),
            'icon': next(s['icon'] for s in SOURCES if s['key'] == key),
            'description': next(s['description'] for s in SOURCES if s['key'] == key),
            'auto': auto, 'status': status, 'label': label, 'detail': detail,
            'updatedAt': updated_at, 'count': count, 'hint': hint,
            'canRetry': key in ('heroes', 'kpl', 'peak'),
            'running': bool(running), 'lastResult': last}


def _hero_card():
    hint = ''
    catalog = _json(CATALOG, {}) or {}
    heroes = [e for e in catalog.get('entries') or [] if e.get('kind') == 'hero']
    have = {str(e.get('name') or '') for e in heroes}
    tags = _json(TAGS, {}) or {}
    have.update(str(n) for n in (tags.get('heroes') or {}))
    normalized = {_norm_hero(n) for n in have}
    missing = sorted(name for name in _external_hero_names() - FORM_ALIASES
                     if _norm_hero(name) not in normalized)
    count = len(heroes)
    if missing:
        status, label = 'stale', '有新增英雄'
        detail = ('外部数据里已有、但本地名录缺失：' + '、'.join(missing[:6])
                  + ('…' if len(missing) > 6 else ''))
        hint = '点「重新爬取」联网补齐名字与头像；打法类型仍需赛训组在工作簿补一行。'
    elif not heroes:
        status, label, detail = 'error', '名录为空', '没有读到英雄名录文件。'
        hint = '检查随包 resources/catalog.json 是否完整，或点「重新爬取」。'
    else:
        status, label = 'ok', '已同步'
        detail = f'英雄名录 {count} 个 · 外部数据未发现缺失英雄'
    return _card('heroes', status, label, detail, str(catalog.get('updatedAt') or _stamp(CATALOG)),
                 count, next(s['auto'] for s in SOURCES if s['key'] == 'heroes'), hint)


def _kpl_card():
    hint = ''
    doc = _json(KPL_MANIFEST if KPL_MANIFEST.is_file() else KPL_MANIFEST_SEED, {}) or {}
    count = int(doc.get('games') or 0)
    errors = int(doc.get('errors') or 0)
    updated = str(doc.get('updatedAt') or '')
    age = _age_days(updated)
    if not count:
        status, label, detail = 'error', '还没有数据', '没有读到 KPL 逐局 BP 清单。'
        hint = '点「重新爬取」抓取官方逐局数据（首次全量约十几分钟）。'
    elif errors:
        status, label = 'warn', '有少量错误'
        detail = f'已收录 {count:,} 局 · {errors} 局抓取失败（不影响其它局）'
    elif age is not None and age > 14:
        status, label = 'stale', '数据偏旧'
        detail = f'已收录 {count:,} 局 · 最近更新 {updated[:10]}'
        hint = '点「重新爬取」补最近赛事。'
    else:
        status, label = 'ok', '已同步'
        detail = f'已收录 {count:,} 局 · 数据窗口至 {str(doc.get("windowEnd") or "")[:10]}'
    return _card('kpl', status, label, detail, updated, count,
                 next(s['auto'] for s in SOURCES if s['key'] == 'kpl'), hint)


def _peak_card():
    hint = ''
    try:
        import peak_crawl
        snap = peak_crawl.status() or {}
    except (ImportError, OSError, ValueError, AttributeError):
        snap = {}
    running = bool(snap.get('running'))
    error = str(snap.get('lastError') or '')
    error = '' if error.lower() in ('', 'none', 'null') else error
    count = int(snap.get('pairs') or 0)
    if error:
        status, label = 'error', '爬取失败'
        detail = f'最近一次失败：{error}'
        hint = '多半是源站暂时连不上：确认电脑能联网后点「重新爬取」。'
    elif snap.get('available') is False:
        status, label = 'error', '模块缺失'
        detail = '当前安装包缺少巅峰千强抓取模块（依赖 scripts/build_bp_facts.py）。'
        hint = '请用完整安装包重装，或检查 scripts/ 是否随包发布。'
    elif snap.get('stale') and not running:
        status, label = 'stale', '待刷新'
        detail = '今天还没抓过，当前展示的是上一次成功的数据。'
    elif snap.get('enabled') is False:
        status, label = 'warn', '自动刷新已关'
        detail = '检测到 PEAK_AUTO_CRAWL=0，今天的自动任务不会运行。'
    else:
        status, label = 'ok', '已同步'
        detail = f'对位数据 {count:,} 对 · 源站数据窗口至 {str(snap.get("windowEnd") or "")[:10]}'
    return _card('peak', status, label, detail,
                 str(snap.get('finishedAt') or snap.get('startedAt') or _stamp(ROOT / 'data' / 'peak' / 'state.json')),
                 count, next(s['auto'] for s in SOURCES if s['key'] == 'peak'), hint)


def _stats_card():
    hint = ''
    path = ROOT / 'data' / 'facts' / 'hero_external_stats.json'
    doc = _json(path, {}) or {}
    count = sum(len(v) for v in doc.values() if isinstance(v, dict))
    today = date.today().isoformat()
    updated = _stamp(path)
    if not count:
        status, label = 'error', '还没有数据'
        detail = '英雄外部统计文件缺失或为空。'
        hint = '点巅峰千强的「重新爬取」会一起重算。'
    elif updated[:10] != today:
        status, label = 'stale', '待刷新'
        detail = f'共 {count:,} 个英雄条目 · 上次更新 {updated[:10]}'
        hint = '确认联网后点巅峰千强的「重新爬取」，会一并重算国服战力。'
    else:
        status, label = 'ok', '已同步'
        detail = f'共 {count:,} 个英雄条目 · 今天已更新'
    return _card('stats', status, label, detail, updated, count,
                 next(s['auto'] for s in SOURCES if s['key'] == 'stats'), hint)


def snapshot() -> dict:
    """四个数据源的当前体检结果 + 总览。"""
    cards = [_hero_card(), _kpl_card(), _peak_card(), _stats_card()]
    counts = {status: sum(1 for c in cards if c['status'] == status)
              for status in ('ok', 'stale', 'warn', 'error', 'running')}
    needs_action = [c['name'] for c in cards if c['status'] in ('stale', 'error')]
    return {'sources': cards, 'counts': counts, 'needsAction': needs_action,
            'offlineHint': '爬取失败时先确认电脑能上网（公司网络可能拦截 pvp.qq.com / 91m.com），再点卡片上的「重新爬取」。'}


def _run(key: str, func) -> bool:
    with _LOCK:
        if _STATE['running'].get(key):
            return False
        _STATE['running'][key] = {'startedAt': datetime.now(timezone.utc).isoformat(),
                                  'message': '后台任务已启动…'}
        _STATE['last'].pop(key, None)

    def worker():
        try:
            result = func()
            message = str(result.get('message') or '完成')[:300] if isinstance(result, dict) else '完成'
            ok = bool(result.get('ok', True)) if isinstance(result, dict) else True
        except Exception as exc:  # noqa: BLE001 - 后台任务必须把错误带回页面
            message, ok = f'{type(exc).__name__}: {exc}'[:300], False
        with _LOCK:
            _STATE['running'].pop(key, None)
            _STATE['last'][key] = {'ok': ok, 'message': message,
                                   'finishedAt': datetime.now(timezone.utc).isoformat()}

    threading.Thread(target=worker, daemon=True, name=f'data-source-{key}').start()
    return True


def _sync_heroes() -> dict:
    """跑 scripts/sync_new_heroes.py --apply（脚本在 scripts/ 下，不能当顶层模块 import）。"""
    script = ROOT / 'scripts' / 'sync_new_heroes.py'
    if not script.is_file():
        return {'ok': False, 'message': f'缺少英雄同步脚本：{script.name}'}
    try:
        proc = subprocess.run([sys.executable, str(script), '--apply'], cwd=str(ROOT),
                              capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired:
        return {'ok': False, 'message': '英雄同步超时（超过 30 分钟）'}
    out = (proc.stdout or '').strip()
    err = (proc.stderr or '').strip()
    report = None
    start, end = out.find('{'), out.rfind('}')
    if start >= 0 and end > start:
        try:
            report = json.loads(out[start:end + 1])
        except (ValueError, TypeError):
            pass
    added = len(report.get('added') or []) if isinstance(report, dict) else 0
    detail = (err or out).splitlines()[-1] if (err or out) else ''
    return {
        'ok': proc.returncode == 0,
        'message': (f'英雄名录同步完成，新增 {added} 个' if proc.returncode == 0
                    else f'英雄同步失败（退出码 {proc.returncode}）：{detail}')[:300],
        'report': report or {},
    }


def _crawl_kpl() -> dict:
    script = ROOT / 'scripts' / 'crawl_kpl_bp.py'
    if not script.is_file():
        return {'ok': False, 'message': f'缺少抓取脚本：{script.name}'}
    proc = subprocess.run([sys.executable, str(script)], cwd=str(ROOT),
                          capture_output=True, text=True, timeout=7200)
    lines = (proc.stdout or '').strip().splitlines()
    message = ''
    # 抓取脚本最后一行是完整 result JSON；直接贴到卡片上会变成一大坨路径和参数。
    try:
        result = json.loads(lines[-1]) if lines else None
    except (ValueError, TypeError):
        result = None
    if isinstance(result, dict):
        manifest = result.get('manifest') or {}
        crawl = result.get('crawl') or {}
        games = manifest.get('games')
        end = manifest.get('windowEnd') or ''
        added = crawl.get('added')
        parts = ['逐局 BP 同步完成']
        if games is not None:
            parts.append(f'当前 {games} 局')
        if added is not None:
            parts.append(f'本次新增 {added}')
        if end:
            parts.append(f'数据窗口至 {str(end)[:10]}')
        message = ' · '.join(parts)
    if not message:
        message = next((line for line in reversed(lines)
                        if line.startswith(('本次：', 'manifest：', '== 完成 =='))),
                       lines[-1] if lines else (proc.stderr or '').strip())
    return {'ok': proc.returncode == 0, 'message': message[:300]}


def _refresh_peak() -> dict:
    import peak_crawl
    snap = peak_crawl.status() or {}
    if snap.get('running'):
        return {'ok': False, 'message': '已有一轮刷新在跑，请稍后。'}
    peak_crawl.refresh(reason='api')
    return {'ok': True, 'message': '巅峰千强刷新已开始，进度会直接反映在卡片上。'}


def refresh(key: str) -> dict:
    runners = {'heroes': _sync_heroes, 'kpl': _crawl_kpl, 'peak': _refresh_peak}
    func = runners.get(str(key or ''))
    if func is None:
        return {'ok': False, 'message': f'不支持的数据源：{key}'}
    started = _run(key, func)
    return {'ok': started,
            'message': '刷新已开始，进度看卡片状态。' if started else '这一轮还在跑，请稍后。'}


def auto_sync_heroes() -> bool:
    """启动后台自动补齐新英雄；没有缺失时 sync 脚本自己会直接返回、不写文件。"""
    if os.environ.get('HERO_AUTO_SYNC', '1') == '0':
        return False
    normalized = {_norm_hero(n) for n in _have_hero_names()}
    missing = {name for name in _external_hero_names() - FORM_ALIASES
               if _norm_hero(name) not in normalized}
    if not missing:
        return False
    return _run('heroes', _sync_heroes)


def _have_hero_names() -> set[str]:
    names = {str(e.get('name') or '') for e in (_json(CATALOG, {}) or {}).get('entries') or []}
    names.update(str(n) for n in ((_json(TAGS, {}) or {}).get('heroes') or {}))
    return names
