"""V3 route module: read training data and expose the analysis API."""

import argparse
import json
import re
import shutil
import sqlite3
import os
import sys
import subprocess
import time
import uuid
from urllib.request import urlopen
from urllib.error import URLError
from collections import Counter, defaultdict
from contextlib import closing
from datetime import date
from pathlib import Path
from threading import Lock, Thread
from time import monotonic

import uvicorn
from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from analysis_data import ALL_SOURCES, DEFAULT_SOURCES, AnalysisRepository
from bp_camp import merge_bp_sources
import bp_facts
import camp_tiles
from collection_contract import reject_example_table, validate_table
from match_review import PanoramaRepository
from paths import data_root
from studio_api import create_studio_router
from analysis_api import create_analysis_router
from depth_api import create_depth_router
import deep_analysis
import identity_service
import vocab as vocab_store


def data_path(variable, default):
    override = os.environ.get(variable)
    if override:
        return Path(override)
    return data_root(ROOT) / default


DB = data_path('TRAINING_DB', 'training.sqlite3')
# 词表与写入归一化共用数据目录；版本 / 规则 / 赛制 / 训练组都落在这里。
DATA_DIR = DB.parent
MATCHES = data_path('ANALYSIS_MATCHES', 'matches')
IMPORTS = data_path('ANALYSIS_IMPORTS', 'imports')
OFFICIAL = data_path('ANALYSIS_OFFICIAL', 'official_replays')
BUILDS = data_path('ANALYSIS_BUILDS', 'builds')
DEMO_ROOT = Path(os.environ['TRAINING_DEMO_ROOT']) if os.environ.get('TRAINING_DEMO_ROOT') else None
POSITION_STEP = 2  # 位置降采样步长（秒），693 秒的局约 347 点/人
IS_DEMO = DEMO_ROOT is not None
panorama = PanoramaRepository(MATCHES, OFFICIAL, BUILDS, ROOT)
router = APIRouter()


async def read_json(request: Request):
    """把非法 JSON 统一变成 400，避免写接口抛 500。"""
    try:
        return await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(400, '请求体不是有效 JSON。') from None


app = FastAPI(title='峡谷棱镜 · 赛训数据平台', docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost'])
# Expose only reviewed studio endpoints. Several other V1 routes automatically
# unlink cache/upload files, so they are not mounted here.
_studio = create_studio_router(DB, MATCHES, IMPORTS)
_STUDIO_ALLOWED = {
    '/api/studio/teams', '/api/studio/teams/rename', '/api/studio/teams/rename-batch',
    '/api/studio/teams/merge',
    '/api/studio/opponents', '/api/studio/opponents/assign', '/api/studio/coach',
    '/api/studio/camp-compare', '/api/studio/camp-combos', '/api/studio/camp-partners',
    '/api/studio/analysis/opponents',
    '/api/studio/workspace/teams', '/api/studio/workspace/teams/merge',
    '/api/studio/workspace/teams/reconcile',
    '/api/studio/workspace/players', '/api/studio/workspace/players/migrate-profile',
    '/api/studio/workspace/players/delete',
    '/api/studio/workspace/schedules',
    '/api/studio/workspace/competitions',
    '/api/studio/workspace/competitions/{competition_id}',
    '/api/studio/workspace/matches',
    '/api/studio/workspace/reports/screenshot',
    '/api/studio/workspace/reports/image/{name}',
    '/api/studio/workspace/inbox',
    '/api/studio/workspace/dashboard',
    '/api/studio/workspace/metrics/week',
    '/api/studio/workspace/metrics/registry',
    '/api/studio/workspace/opponents/unmapped',
    '/api/studio/workspace/opponents/map',
    '/api/studio/workspace/sessions/{schedule_id}',
    '/api/studio/workspace/sessions/{schedule_id}/review',
    '/api/studio/workspace/sessions/{schedule_id}/links',
    '/api/studio/workspace/training', '/api/studio/workspace/prefill/run',
    '/api/studio/workspace/pending', '/api/studio/workspace/pending/confirm',
    '/api/studio/workspace/pending/confirm-batch',
    '/api/studio/profile',
}
_studio.routes = [route for route in _studio.routes if route.path in _STUDIO_ALLOWED]
app.include_router(_studio)
app.include_router(create_analysis_router(DB, MATCHES, IMPORTS, OFFICIAL))
app.include_router(create_depth_router(DEMO_ROOT or ROOT, DB))
app.mount('/static', StaticFiles(directory=HERE / 'public'), name='frontend')
app.mount('/catalog/icons', StaticFiles(directory=ROOT / 'resources' / 'icons', check_dir=False),
          name='icons')

_lock = Lock()
_snapshot = None
_loaded_at = float('-inf')


def apply_bp_overrides(data):
    """Attach explicitly entered V3 BP records to the in-memory snapshot."""
    if not DB.is_file(): return
    try:
        with sqlite3.connect(f'file:{DB.as_posix()}?mode=ro', uri=True) as connection:
            rows=connection.execute('SELECT match_key,body,revision FROM bp_overrides').fetchall()
    except sqlite3.Error:
        return
    overrides={}
    for key, body, revision in rows:
        try:
            value=json.loads(body)
            if isinstance(value,dict): overrides[key]=(value,revision)
        except (ValueError,TypeError):
            continue
    for match in data.get('matches',[]) + data.get('sheetMatches',[]):
        if match.get('key') in overrides:
            match['bp'],match['bpRevision']=overrides[match['key']]


def invalidate_snapshot():
    global _snapshot, _loaded_at
    with _lock:
        _snapshot, _loaded_at = None, float('-inf')
    for name in ('_CROSS_VECTOR_CACHE', '_CROSS_VECTOR_BY_KEY'):
        cache = globals().get(name)
        if cache is not None:
            cache.clear()


def repository(request: Request):
    global _snapshot, _loaded_at
    with _lock:
        if request.query_params.get('fresh') == '1' or monotonic() - _loaded_at >= 15:
            snapshot = AnalysisRepository(DB, MATCHES, IMPORTS, OFFICIAL)
            data = snapshot.get()
            apply_bp_overrides(data)
            _snapshot, _loaded_at = snapshot, monotonic()
        return _snapshot


def filters(request: Request):
    q = request.query_params
    sources = [source for source in q.get('source', '').split(',') if source in ALL_SOURCES]
    try:
        start = date.fromisoformat(q['from']) if q.get('from') else None
        end = date.fromisoformat(q['to']) if q.get('to') else None
    except ValueError as error:
        raise HTTPException(400, '日期格式无效') from error
    if start and end and start > end:
        raise HTTPException(400, '开始日期不能晚于结束日期')
    return {
        'sources': sources or list(DEFAULT_SOURCES),
        'from': start.isoformat() if start else None,
        'to': end.isoformat() if end else None,
        'hero': q.get('hero') or None,
        'opponent': q.get('opponent') or None,
        'excludeSeeds': q.get('validation') != '1',
        'ownOnly': q.get('scope') != 'all',
    }


@app.middleware('http')
async def prevent_data_caching(request, call_next):
    global _snapshot, _loaded_at
    response = await call_next(request)
    if request.method not in ('GET', 'HEAD', 'OPTIONS') and response.status_code < 400:
        invalidate_snapshot()
    # 静态资源也要禁用缓存：前端文件改动后，普通刷新就要能看到，不依赖强刷。
    path = request.url.path
    if path.startswith('/api/') or '/static/' in path or path == '/' or path.endswith('/v3/'):
        response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@router.get('/')
def v3_index():
    return FileResponse(HERE / 'public' / 'index.html')


_CROSS_LANES = ('对抗路', '打野', '中路', '发育路', '游走')
_CROSS_VECTOR_CACHE = {}
_CROSS_VECTOR_BY_KEY = {}


def _cross_interp(series, t):
    if not series:
        return None
    if t <= series[0][0]:
        return series[0][1]
    if t >= series[-1][0]:
        return series[-1][1]
    for i in range(1, len(series)):
        t0, v0 = series[i - 1]
        t1, v1 = series[i]
        if t0 <= t <= t1:
            return v1 if t1 == t0 else v0 + (v1 - v0) * (t - t0) / (t1 - t0)
    return series[-1][1]


def _cross_vector(repo, item, segments=8):
    key = item['key']
    cache_id = (key, segments)
    cached = _CROSS_VECTOR_BY_KEY.get(cache_id)
    if cached is not None:
        return cached
    d = repo.match_detail(key)
    if not d:
        return None
    camp = d.get('ownCamp') or 'blue'
    sign = 1 if camp == 'blue' else -1
    duration = float(d.get('duration') or 0) or 0.0
    econ = []
    for point in (d.get('process') or {}).get('timeline') or []:
        t = point.get('gameTime')
        if not isinstance(t, (int, float)):
            continue
        if isinstance(point.get('blueGold'), (int, float)) and isinstance(point.get('redGold'), (int, float)):
            value = (point['blueGold'] - point['redGold']) * sign
        elif isinstance(point.get('goldDiff'), (int, float)):
            value = point['goldDiff'] * sign
        else:
            continue
        econ.append((float(t), float(value)))
    econ.sort(key=lambda pair: pair[0])

    g = [round(_cross_interp(econ, k * 300), 1) if econ and duration >= k * 300 else None for k in range(segments)]
    w = []
    for k in range(segments):
        if econ and duration >= (k + 1) * 300:
            a, b = _cross_interp(econ, k * 300), _cross_interp(econ, (k + 1) * 300)
            w.append(round(b - a, 1) if a is not None and b is not None else None)
        else:
            w.append(None)
    # 相对时长对齐的 6 点轨迹：短局与长局都能比较「形状」，不受绝对时长影响
    shape = [round(_cross_interp(econ, duration * f), 1) for f in (0, .2, .4, .6, .8, 1.0)] if econ and duration else []
    final = econ[-1][1] if econ else None
    if final is None:
        totals = d.get('teamTotals') or {}
        mine = (totals.get(camp) or {}).get('totals') or {}
        other = (totals.get('red' if camp == 'blue' else 'blue') or {}).get('totals') or {}
        if isinstance(mine.get('gold'), (int, float)) and isinstance(other.get('gold'), (int, float)):
            final = mine['gold'] - other['gold']
    # 教练口径的三段：0–4 对线 / 4–10 发育 / 10 分钟后（经济约 30 秒一点，按插值取）
    base = _cross_interp(econ, 0) if econ else None
    at4 = _cross_interp(econ, 240) if econ and duration >= 240 else None
    at10 = _cross_interp(econ, 600) if econ and duration >= 600 else None
    seg = {
        'early': round(at4 - base, 1) if at4 is not None and base is not None else None,
        'mid': round(at10 - at4, 1) if at10 is not None and at4 is not None else None,
        'late': round(final - at10, 1) if final is not None and at10 is not None else None,
    }

    # 资源 / 推塔 / 死亡 / 团战 / BUFF / 切 C：读回放聚合；没有回放的局留 None，不补 0
    obj = {'dragonOwn': None, 'dragonFoe': None, 'towerOwn': None, 'towerFoe': None}
    death = {'own': None, 'foe': None}
    fight = {'n': None, 'win': None}
    buff = {'anti': None, 'stolen': None}
    cut = {'n': None, 'first': None}
    fk = None
    fs = None
    try:
        replay = panorama.get(d.get('bundleKey') or '') if d.get('bundleKey') else None
    except Exception:                                  # noqa: BLE001
        replay = None
    if replay:
        other = 'red' if camp == 'blue' else 'blue'
        events = [e for e in (replay.get('events') or []) if isinstance(e, dict)]
        dragons = [e for e in events if e.get('name') in ('暴君', '暗影暴君', '暗影主宰', '主宰', '风暴龙王')]
        towers = [e for e in events if e.get('name') in ('防御塔', '水晶')]
        obj['dragonOwn'] = sum(1 for e in dragons if e.get('killerCamp') == camp)
        obj['dragonFoe'] = sum(1 for e in dragons if e.get('killerCamp') == other)
        obj['towerOwn'] = sum(1 for e in towers if e.get('killerCamp') == camp)
        obj['towerFoe'] = sum(1 for e in towers if e.get('killerCamp') == other)
        deaths = [x for x in (replay.get('deaths') or []) if isinstance(x, dict)]
        death['own'] = sum(1 for x in deaths if x.get('camp') == camp)
        death['foe'] = sum(1 for x in deaths if x.get('camp') == other)
        fights = [f for f in (replay.get('fights') or []) if isinstance(f, dict)]
        fight['n'] = len(fights)
        fight['win'] = sum(1 for f in fights if (f.get(camp) or 0) > (f.get(other) or 0))
        buffs = [b for b in (replay.get('buffEvents') or []) if isinstance(b, dict)]
        buff['anti'] = sum(1 for b in buffs if b.get('owner') == other and b.get('killer') == camp)
        buff['stolen'] = sum(1 for b in buffs if b.get('owner') == camp and b.get('killer') == other)
        kills = [k for k in (replay.get('kills') or []) if isinstance(k, dict)]
        pos_of = {p.get('hero'): p.get('position') for p in (d.get('players') or []) if p.get('hero')}
        cut['n'] = sum(
            1 for k in kills
            if k.get('killerCamp') == camp
            and pos_of.get(k.get('killer')) in ('对抗路', '打野')
            and pos_of.get(k.get('victim')) in ('中路', '发育路')
        )
        if kills:
            first_kill = min(kills, key=lambda k: k.get('t') or 0)
            cut['first'] = 1 if first_kill.get('killerCamp') == camp else 0
        buckets = {b: {'n': 0, 'win': 0} for b in ('adv', 'even', 'dis', 'first', 'firstAgainst')}
        for f in fights:
            people = {'blue': 0, 'red': 0}
            for detail in (f.get('details') or []):
                if isinstance(detail, dict) and detail.get('camp') in people:
                    people[detail['camp']] += 1
            ours, theirs = people[camp], people[other]
            if not ours and not theirs:
                continue
            won = (f.get(camp) or 0) > (f.get(other) or 0)
            key = 'adv' if ours > theirs else 'dis' if ours < theirs else 'even'
            buckets[key]['n'] += 1
            if won:
                buckets[key]['win'] += 1
            first_side = f.get('first')
            if first_side == camp:
                buckets['first']['n'] += 1
                if won:
                    buckets['first']['win'] += 1
            elif first_side == other:
                buckets['firstAgainst']['n'] += 1
                if won:
                    buckets['firstAgainst']['win'] += 1
        fk = buckets
        # 团战伤害结构：每波团我方十人的伤害/承伤占比，按分路汇总
        hero_pos = {p.get('hero'): p.get('position') for p in (d.get('players') or []) if p.get('hero')}
        acc = {}
        for f in fights:
            ours = [x for x in (f.get('details') or []) if isinstance(x, dict) and x.get('camp') == camp]
            total_h = sum((x.get('hurt') or 0) for x in ours)
            total_t = sum((x.get('taken') or 0) for x in ours)
            if not total_h and not total_t:
                continue
            for x in ours:
                pos = hero_pos.get(x.get('hero')) or '未知'
                cell = acc.setdefault(pos, {'h': 0.0, 't': 0.0, 'n': 0})
                if total_h:
                    cell['h'] += (x.get('hurt') or 0) / total_h
                if total_t:
                    cell['t'] += (x.get('taken') or 0) / total_t
                cell['n'] += 1
        fs = {pos: {'hurtShare': round(v['h'] / v['n'], 3), 'takenShare': round(v['t'] / v['n'], 3), 'n': v['n']}
              for pos, v in acc.items() if v['n']}
    # 打野过河：0–10 分钟逐秒坐标，e>8 算过河、e>25 算深入（口径见 docs/jungle_position_spec.md）
    jungle = {'crossSec': None, 'crossShare': None, 'firstCross': None, 'deepShare': None}
    replay_id = str((d.get('officialReplay') or {}).get('id') or '')
    if replay_id:
        pos_path = OFFICIAL / replay_id / 'positions.json'
        slots = []
        if pos_path.is_file():
            try:
                slots = (json.loads(pos_path.read_text(encoding='utf-8')) or {}).get('players') or []
            except (OSError, ValueError):
                slots = []
        jungle_idx = None
        for i, p in enumerate(d.get('players') or []):
            if p.get('camp') == camp and p.get('position') == '打野':
                jungle_idx = i
                break
        if jungle_idx is not None and jungle_idx < len(slots):
            arr = slots[jungle_idx].get('posArr') or []
            facing = 1 if camp == 'blue' else -1
            e_vals = [(q[0] + q[1]) / 2.0 * facing for q in arr[:600]
                      if isinstance(q, (list, tuple)) and len(q) >= 2]
            if e_vals:
                cross_sec = sum(1 for v in e_vals if v > 8)
                deep = sum(1 for v in e_vals if v > 25)
                jungle['crossSec'] = cross_sec
                jungle['crossShare'] = round(cross_sec / len(e_vals), 3)
                jungle['deepShare'] = round(deep / len(e_vals), 3)
                jungle['firstCross'] = next((i for i, v in enumerate(e_vals) if v > 8), None)

    players = d.get('players') or []
    own = [p for p in players if p.get('camp') == camp]
    foe = [p for p in players if p.get('camp') in ('blue', 'red') and p.get('camp') != camp]
    number = lambda x: float(x) if isinstance(x, (int, float)) else 0.0
    lanes = {}
    for lane in _CROSS_LANES:
        p = next((x for x in own if x.get('position') == lane), None)
        q = next((x for x in foe if x.get('position') == lane), None)
        if p and q and duration:
            lanes[lane] = {key: round((number(p.get(key)) - number(q.get(key))) / duration * 60, 1)
                           for key in ('gold', 'damage', 'taken')}
    heroes = [p.get('hero') for p in own if p.get('hero')][:5]
    heroes_foe = [p.get('hero') for p in foe if p.get('hero')][:5]
    # 逐人一行：选手榜与同位置对位都从这里取；没有时长的局分均留空
    minutes = duration / 60.0 if duration else 0.0
    pl = []
    for p in players:
        if not isinstance(p, dict) or not p.get('camp'):
            continue
        pl.append({
            'name': str(p.get('label') or p.get('name') or ''),
            'camp': p.get('camp'),
            'pos': p.get('position') or '',
            'hero': p.get('hero') or '',
            'k': p.get('kills'), 'd': p.get('deaths'), 'a': p.get('assists'),
            'gpm': round(number(p.get('gold')) / minutes, 1) if minutes and p.get('gold') is not None else None,
            'dpm': round(number(p.get('damage')) / minutes, 1) if minutes and p.get('damage') is not None else None,
            'part': p.get('participation'),
        })
    bp = d.get('campBp') or {}
    bans = [x.get('name') for side in ('left', 'right') for x in ((bp.get('bans') or {}).get(side) or []) if x.get('name')]
    scores = d.get('scores') or {}
    kill_own, kill_foe = scores.get(camp), scores.get('red' if camp == 'blue' else 'blue')
    start_text = str(bp.get('startTime') or '')
    clock_match = re.search(r'(\d{1,2}:\d{2})', start_text)
    clock = clock_match.group(1) if clock_match else ''
    date_text = str(item.get('date') or d.get('date') or '')
    vector = {
        'key': key, 'date': date_text, 'clock': clock,
        'order': f"{date_text} {clock}" if date_text else clock,
        'session': d.get('session') or item.get('session') or '',
        'version': d.get('version') or item.get('version') or '',
        'opponent': d.get('opponent') or item.get('opponent') or '',
        'result': d.get('result') or item.get('result') or '',
        'duration': duration, 'camp': camp,
        'at10': g[2], 'finalDiff': final, 'g': g, 'w': w, 's': shape,
        'at4': round(at4, 1) if at4 is not None else None,
        'seg': seg, 'ecoPoints': len(econ),
        'obj': obj, 'death': death, 'fight': fight, 'buff': buff,
        'cut': cut, 'fk': fk, 'jungle': jungle,
        'pl': pl, 'fs': fs,
        'killsOwn': kill_own, 'killsFoe': kill_foe,
        'lanes': lanes, 'heroes': heroes, 'heroesFoe': heroes_foe, 'bans': bans,
    }
    _CROSS_VECTOR_BY_KEY[cache_id] = vector
    return vector


@router.get('/api/cross/vectors')
def cross_vectors(repo=Depends(repository), values=Depends(filters)):
    """全量对局的轻量指标向量，供通用跨局分析一次取回。

    每局只带聚合需要的标量（经济检查点、5 分钟净增、分路分均差、阵容、
    BP、结果与分层标签），不含十人明细、位置序列和事件流；逐局明细仍由
    /api/matches/{key} 按需取。局数上万时这里应换成预聚合表／物化视图，
    接口契约（向量字段）保持不变，前端分析内核无需改动。
    """
    items = repo.matches(values)['matches']
    max_duration = max((float(i.get('duration') or 0) for i in items), default=0.0)
    segments = max(4, min(16, int(max_duration // 300) + 1)) if max_duration else 8
    cache_key = (tuple(i['key'] for i in items), values['from'], values['to'],
                 tuple(values['sources']), values['excludeSeeds'], segments)
    hit = _CROSS_VECTOR_CACHE.get(cache_key)
    if hit is not None:
        return hit
    vectors = [v for v in (_cross_vector(repo, item, segments) for item in items) if v]
    payload = {'total': len(items), 'vectors': vectors, 'unit': 'cohort-vectors-v1',
               'segments': segments, 'windowMin': 5}
    if len(_CROSS_VECTOR_CACHE) > 4:
        _CROSS_VECTOR_CACHE.clear()
    _CROSS_VECTOR_CACHE[cache_key] = payload
    return payload


@router.get('/api/overview')
def overview(repo=Depends(repository), values=Depends(filters)):
    summary = repo.overview(values)
    matches = sorted(repo.matches(values)['matches'], key=lambda item: (bool(item.get('date')), item.get('date') or ''), reverse=True)
    process = repo.process(values)
    process['matches'].sort(key=lambda item: (bool(item.get('date')), item.get('date') or ''), reverse=True)
    return {
        'summary': {key: value for key, value in summary.items() if key != 'profile'},
        'team': repo.team_stats(values),
        'matches': matches,
        'process': process,
    }


@router.get('/api/matches')
def matches(repo=Depends(repository), values=Depends(filters)):
    result = repo.matches(values)
    # The structured store may contain a confirmed version that predates V3.
    # An explicit per-match override remains authoritative.
    try:
        with sqlite3.connect(f'file:{DB.as_posix()}?mode=ro', uri=True) as connection:
            versions = dict(connection.execute('SELECT match_key, version FROM match_records WHERE version IS NOT NULL AND version != \"\"'))
        for item in result['matches']:
            if not item.get('version') and item['key'] in versions:
                item['version'] = versions[item['key']]
    except sqlite3.Error:
        pass
    result['matches'].sort(key=lambda item: (bool(item.get('date')), item.get('date') or ''), reverse=True)
    return result


@router.get('/api/matches/{key:path}')
def match(key: str, repo=Depends(repository)):
    detail = repo.match_detail(key)
    if detail is None:
        raise HTTPException(404, '找不到该局对战记录')
    detail['draft'] = merge_bp_sources(detail.get('bp'), detail.get('campBp'), detail)
    # 营地十人面板的派生卡片（视野价值 / 经济转有效伤害 / 反野总经济 / 控龙 / 勾中）。
    # 这些字段一直在 camp_details 里，只是从没被读出来过。缺失就不写，前端据此留空。
    camp_tiles.attach(detail, MATCHES.parent / 'camp_details')
    # 外部 BP 事实：对位压制用巅峰千强大盘（带超额胜率），组合与赛事命中用 KPL。
    try:
        detail['bpFacts'] = bp_facts.for_match(detail)
    except Exception:
        detail['bpFacts'] = None
    if not detail.get('version'):
        try:
            with sqlite3.connect(f'file:{DB.as_posix()}?mode=ro', uri=True) as connection:
                row = connection.execute('SELECT version FROM match_records WHERE match_key=?', (key,)).fetchone()
            if row and row[0]: detail['version'] = row[0]
        except sqlite3.Error:
            pass
    return detail


@router.get('/api/replay/{key:path}')
def replay(key: str, repo=Depends(repository)):
    detail = repo.match_detail(key)
    result = panorama.get(detail['bundleKey']) if detail and detail.get('bundleKey') else None
    if result is None:
        raise HTTPException(404, '该局没有全景回放数据')
    return {name: result[name] for name in
            ('gold', 'events', 'kills', 'deaths', 'fights', 'coverage', 'notes',
             'buffEvents', 'narrations')
            if name in result}


@router.get('/api/positions/{key:path}')
def match_positions(key: str):
    """营地回放的逐秒位置（十人）。用于单局的热区与对位深区。

    通道 → 营地 gameSeq → data/official_replays/camp-<seq>/positions.json；
    玩家按 playerId 与通道里的营地十人面板对齐。降采样到每 `STEP` 秒一点。
    """
    # 对局 key 带 channel- 前缀，channels 表的 id 不带。
    channel_id = key[len('channel-'):] if key.startswith('channel-') else key
    try:
        with sqlite3.connect(f'file:{DB.as_posix()}?mode=ro', uri=True) as connection:
            row = connection.execute('SELECT body FROM channels WHERE id=?', (channel_id,)).fetchone()
    except sqlite3.Error:
        row = None

    camp, seq = {}, ''
    bundle_players = []
    if row:
        channel = json.loads(row[0])
        camp = (channel.get('sources') or {}).get('camp') or {}
        seq = str(camp.get('gameSeq') or '')
    else:
        # 没有采集通道（例如演示数据包）时，直接按数据包里挂的 officialReplay 找位置
        bundle_path = MATCHES / f'{key}.json'
        if not bundle_path.is_file():
            raise HTTPException(404, '找不到该局的采集通道')
        bundle = json.loads(bundle_path.read_text(encoding='utf-8'))
        linked = str(((bundle.get('match') or {}).get('officialReplay') or {}).get('id') or '')
        if linked:
            seq = linked[len('camp-'):] if linked.startswith('camp-') else linked
            bundle_players = bundle.get('players') or []
    if not seq:
        raise HTTPException(404, '这一局没有营地回放')
    path = OFFICIAL / f'camp-{seq}' / 'positions.json'
    if not path.is_file():
        raise HTTPException(404, '缺少位置数据文件')
    data = json.loads(path.read_text(encoding='utf-8'))
    roster = {str(p.get('playerId')): p for p in (camp.get('players') or []) if p.get('playerId')}
    # 位置文件的 playerId 是营地短 ID（与 raw.matchInfo.playerId 同源），通道名单里
    # 存的是游戏内 playID（长 ID），两套 ID 对不上。用 matchInfo 的 heroName /
    # acntcamp 做桥：短 ID → 英雄名 + 阵营 → 通道名单里的 camp+slot+昵称。
    identity_by_short = {}
    raw_path = OFFICIAL / f'camp-{seq}' / 'raw.json'
    if raw_path.is_file():
        try:
            raw_value = json.loads(raw_path.read_text(encoding='utf-8'))
            raw_body = raw_value.get('data') if isinstance(raw_value.get('data'), dict) else raw_value
            for item in raw_body.get('matchInfo') or []:
                short = str(item.get('playerId') or '')
                if not short:
                    continue
                identity_by_short[short] = {
                    'hero': str(item.get('heroName') or ''),
                    'camp': 'blue' if str(item.get('acntcamp') or '1') == '1' else 'red',
                }
        except (OSError, json.JSONDecodeError):
            identity_by_short = {}
    roster_by_hero = {(str(p.get('camp')), str(p.get('hero'))): p
                      for p in (camp.get('players') or []) if p.get('hero')}
    step = POSITION_STEP
    players = []
    for index, item in enumerate(data.get('players') or []):
        short_id = str(item.get('playerId') or '')
        info = roster.get(short_id)
        if not info and bundle_players:
            # 数据包玩家按 blue0..4 / red0..4 顺序排列，与位置文件同序
            info = bundle_players[index] if index < len(bundle_players) else None
        if not info:
            identity = identity_by_short.get(short_id)
            if identity:
                info = roster_by_hero.get((identity['camp'], identity['hero']))
                if not info:
                    info = {'hero': identity['hero'], 'camp': identity['camp']}
        info = info or {}
        arr = item.get('posArr') or []
        players.append({
            'camp': info.get('camp'), 'slot': info.get('slot'),
            'nickname': info.get('nickname'), 'hero': info.get('hero'),
            'points': [[int(x), int(y)] for x, y in arr[::step]],
        })
    players.sort(key=lambda p: (0 if p['camp'] == 'blue' else 1, p['slot'] if p['slot'] is not None else 99))
    return {
        'step': step,
        'duration': int(max((len(item.get('posArr') or []) for item in data.get('players') or []), default=0)),
        'players': players,
    }


@router.get('/api/players')
def players(repo=Depends(repository), values=Depends(filters)):
    return {'players': repo.player_stats(values)}


@router.get('/api/v3/players/board')
def players_board(repo=Depends(repository), values=Depends(filters)):
    return repo.player_board(values)


@router.get('/api/players/{key:path}')
def player(key: str, repo=Depends(repository), values=Depends(filters)):
    stats = next((row for row in repo.player_stats(values) if row['playerKey'] == key), None)
    return {'stats': stats, **repo.player_trend(key, values)}


@router.get('/api/bp')
def bp(repo=Depends(repository), values=Depends(filters)):
    return {'draft': repo.bp_summary(values), 'heroes': repo.hero_stats(values)}


@router.get('/api/tempo')
def tempo(repo=Depends(repository), values=Depends(filters)):
    return {'process': repo.process(values), 'objectives': repo.objectives(values)}


@router.get('/api/opponents')
def opponents(repo=Depends(repository), values=Depends(filters)):
    scoped, warnings = repo._selected_matches(values)
    match_rows = {row['key']: row for row in repo.matches(values)['matches']}
    groups = defaultdict(list)
    unknown = 0
    for item in scoped:
        if not item.get('opponent'):
            unknown += 1
            continue
        groups[item['opponent']].append(item)
    result = []
    for name, games in groups.items():
        picks = Counter()
        bans = Counter()
        draft_count = 0
        rows = [match_rows[item['key']] for item in games]
        wins = sum(row['result'] == 'win' for row in rows)
        losses = sum(row['result'] == 'loss' for row in rows)
        for item in games:
            own = item.get('ownCamp')
            enemy = {'blue': 'red', 'red': 'blue', 'left': 'right', 'right': 'left'}.get(own)
            if not enemy:
                continue
            picks.update(p['hero'] for p in item['players'] if p.get('camp') == enemy and p.get('hero'))
            draft = merge_bp_sources(item.get('bp'), item.get('campBp'), item)
            if draft:
                side = 'left' if enemy in ('blue', 'left') else 'right'
                draft_count += 1
                bans.update(hero['name'] for hero in draft['bans'][side])
        result.append({
            'name': name, 'matches': rows, 'wins': wins, 'losses': losses,
            'picks': picks.most_common(), 'bans': bans.most_common(), 'draftCount': draft_count,
        })
    result.sort(key=lambda item: (-len(item['matches']), item['name']))
    return {'opponents': result, 'unknown': unknown, 'warnings': warnings}


@router.get('/api/sources')
def sources(repo=Depends(repository), values=Depends(filters)):
    stats = repo.overview(values, include_top=False)
    return {
        **repo.sources(), 'quality': stats['dataQuality'], 'coverage': stats['coverage'],
        'inventory': stats['inventory'], 'scopeWarnings': stats['warnings'],
        'validationCount': sum(repo._is_seed_match(match) for match in repo.get()['matches']),
    }


@router.get('/api/metadata')
def metadata(repo=Depends(repository)):
    path = ROOT / 'resources' / 'catalog.json'
    entries = json.loads(path.read_text(encoding='utf-8')).get('entries', []) if path.is_file() else []
    return {
        'teamName': repo.get()['teamName'], 'options': repo.filters(), 'demo': IS_DEMO,
        'icons': {entry['name']: entry['icon'] for entry in entries
                  if entry.get('kind') == 'hero' and entry.get('name') and entry.get('icon')},
    }


_demo_lock = Lock()
DEMO_APPLICATION = 'training-data-v3'
DEMO_PORT = 8773


def _demo_status_is_ours(status):
    return bool(status and status.get('demo')
                and status.get('application') == DEMO_APPLICATION)


_LEGACY_FOLDER_NAMES = ('KPL赛训工具', 'KPL训练赛项目', 'KPL赛训工具-windows')


def _legacy_candidates():
    """免安装版常见的落点；只拼路径，不扫全盘。"""
    home = Path.home()
    bases = [home / 'Desktop', home / 'Downloads',
             home / 'OneDrive' / 'Desktop', home / 'OneDrive' / 'Downloads']
    return [base / name / 'data' for base in bases for name in _LEGACY_FOLDER_NAMES]


def _bundle_count(directory):
    try:
        return sum(1 for path in (directory / 'matches').glob('*.json') if path.is_file())
    except OSError:
        return 0


def _legacy_match_count(data_dir):
    """旧库里有多少局；DB 记录与对局包取较大值，读不出来就当 0。"""
    database = data_dir / 'training.sqlite3'
    counted = _bundle_count(data_dir)
    try:
        with closing(sqlite3.connect(f'file:{database.as_posix()}?mode=ro', uri=True)) as connection:
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            for table in ('match_records', 'matches'):
                if table in tables:
                    counted = max(counted, int(connection.execute(
                        f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]))
    except sqlite3.Error:
        return counted
    return counted


def _loopback(request):
    client = request.client.host if request.client else ''
    return client in ('127.0.0.1', '::1', '::ffff:127.0.0.1')


@router.get('/api/welcome')
def welcome_info():
    """First-run facts for the empty home page.

    The workbench ships without match data.  When the library is empty the UI
    shows three ways to bring the first match in, plus the real data directory
    and any old install it can see.  Reading directory names only; no file
    contents are opened.
    """
    data_dir = data_root()
    legacy = []
    seen = set()
    for candidate in _legacy_candidates():
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in seen or resolved == data_dir.resolve():
            continue
        seen.add(resolved)
        database = resolved / 'training.sqlite3'
        if not database.is_file():
            continue
        try:
            stat = database.stat()
        except OSError:
            continue
        legacy.append({'path': str(resolved), 'size': stat.st_size,
                       'modified': int(stat.st_mtime),
                       'matches': _legacy_match_count(resolved)})
    return {
        'dataDir': str(data_dir),
        'campAuthorized': (data_dir / 'camp_auth.json').is_file(),
        'legacy': legacy[:3],
    }


@router.post('/api/data/open')
def open_data_dir(request: Request):
    """Open the local data folder in Explorer (loopback only)."""
    if not _loopback(request):
        raise HTTPException(403, '只允许在本机打开数据目录。')
    target = data_root()
    target.mkdir(parents=True, exist_ok=True)
    try:
        if os.name == 'nt':
            os.startfile(str(target))  # noqa: S606 - local Explorer
        else:
            subprocess.Popen(['xdg-open', str(target)])
    except Exception as exc:  # noqa: BLE001 - 打不开时给可读原因
        raise HTTPException(500, f'没能打开数据目录：{exc}') from exc
    return {'ok': True, 'path': str(target)}


# ------------------------------------------------------------------ 旧数据搬迁
# 免安装版换成安装版后数据目录变了，不该让教练自己去资源管理器里复制 10 GB。
# 这里做一次整库搬迁：SQLite 走 backup API（WAL 里未落盘的部分也带上），
# 其余资产逐文件复制并给出进度；只在本机、且当前库还没有对局时允许执行。
_MIGRATE_LOCK = Lock()
_MIGRATE_JOB = {'state': 'idle'}
# 缓存与一次性中间产物不进新库；旧版本留下的备份也不搬。
_MIGRATE_SKIP = {'.studio-cache', '.migrate-staging', '_tmp', '_channel_work', '_mock',
                 '_oss_probe', 'update', 'backups', 'watchdog.pid', 'ocr_cache'}
# 回放与录屏占九成体积，允许教练选择跳过。
_MIGRATE_HEAVY = {'replays', 'recordings'}


def _migrate_status():
    with _MIGRATE_LOCK:
        return dict(_MIGRATE_JOB)


def _migrate_update(**patch):
    with _MIGRATE_LOCK:
        _MIGRATE_JOB.update(patch)


def _library_is_empty(database):
    if _bundle_count(database.parent):
        return False
    if not database.is_file():
        return True
    try:
        with closing(sqlite3.connect(f'file:{database.as_posix()}?mode=ro', uri=True)) as connection:
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            for table in ('match_records', 'matches'):
                if table in tables and connection.execute(
                        f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]:
                    return False
    except sqlite3.Error:
        return False
    return True


def _migrate_sources(source, include_heavy):
    for entry in source.iterdir():
        name = entry.name
        if name in _MIGRATE_SKIP or name.startswith(('_backup', '_archive')):
            continue
        # SQLite 的旁路文件随主库一起由 backup API 处理，单独复制会带进半写状态。
        if name.endswith(('-wal', '-shm', '-journal')):
            continue
        if not include_heavy and name in _MIGRATE_HEAVY:
            continue
        if entry.is_dir():
            for path in entry.rglob('*'):
                if path.is_file():
                    yield path
        elif entry.is_file():
            yield entry


def _copy_with_progress(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open('rb') as reader, destination.open('wb') as writer:
        while True:
            block = reader.read(4 * 1024 * 1024)
            if not block:
                break
            writer.write(block)
            with _MIGRATE_LOCK:
                _MIGRATE_JOB['bytes'] = _MIGRATE_JOB.get('bytes', 0) + len(block)
    try:
        shutil.copystat(source, destination, follow_symlinks=False)
    except OSError:
        pass


def _copy_sqlite(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_connection = sqlite3.connect(f'file:{source.as_posix()}?mode=ro', uri=True)
    try:
        target_connection = sqlite3.connect(destination)
        try:
            source_connection.backup(target_connection)
            target_connection.commit()
        finally:
            target_connection.close()
    finally:
        source_connection.close()
    try:
        with _MIGRATE_LOCK:
            _MIGRATE_JOB['bytes'] = _MIGRATE_JOB.get('bytes', 0) + destination.stat().st_size
    except OSError:
        pass


def _upgrade_migrated(destination):
    """把旧库升级到当前结构：补缺失的表/列，旧命名归位。"""
    database = destination / 'training.sqlite3'
    if not database.is_file():
        raise RuntimeError('搬迁后的库里没有 training.sqlite3')
    with closing(sqlite3.connect(database)) as connection:
        names = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if 'bp_overrides' not in names:
            for name in names:
                if name != 'bp_overrides' and name.endswith('_bp_overrides'):
                    connection.execute(f'ALTER TABLE "{name}" RENAME TO bp_overrides')
                    break
        connection.commit()
    import workspace_store
    workspace_store.Workspace(database).ensure_schema()


def _merge_staging(staging, destination):
    """把暂存目录整体并进数据目录；同卷 rename，几乎不额外占空间。"""
    for entry in list(staging.iterdir()):
        target = destination / entry.name
        if entry.is_dir() and target.is_dir():
            for path in sorted(entry.rglob('*')):
                if not path.is_file():
                    continue
                output = target / path.relative_to(entry)
                output.parent.mkdir(parents=True, exist_ok=True)
                os.replace(path, output)
            shutil.rmtree(entry, ignore_errors=True)
        else:
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            elif target.exists():
                target.unlink()
            os.replace(entry, target)


def _run_migration(source, destination, include_heavy):
    staging = destination / '.migrate-staging'
    try:
        _migrate_update(state='scanning', current='', error='', bytes=0, totalBytes=0,
                        copied=0, totalFiles=0)
        files = list(_migrate_sources(source, include_heavy))
        total_bytes = 0
        for path in files:
            try:
                total_bytes += path.stat().st_size
            except OSError:
                pass
        databases = [path for path in files if path.suffix == '.sqlite3']
        assets = [path for path in files if path.suffix != '.sqlite3']
        _migrate_update(state='copying', totalBytes=total_bytes, totalFiles=len(files))

        destination.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        for path in assets:
            relative = path.relative_to(source)
            _migrate_update(current=str(relative))
            _copy_with_progress(path, staging / relative)
            with _MIGRATE_LOCK:
                _MIGRATE_JOB['copied'] = _MIGRATE_JOB.get('copied', 0) + 1

        for path in databases:
            if path.name == 'training.sqlite3':
                name = 'training.sqlite3'
            elif path.name.endswith('reports.sqlite3'):
                name = 'reports.sqlite3'
            else:
                continue
            _migrate_update(current=name, state='database')
            _copy_sqlite(path, staging / name)

        _migrate_update(state='upgrading', current='')
        _upgrade_migrated(staging)
        # 全部写完才落进数据目录：中途失败时新库保持为空，可以直接重试。
        _migrate_update(state='merging', current='')
        _merge_staging(staging, destination)
        shutil.rmtree(staging, ignore_errors=True)
        invalidate_snapshot()
        _migrate_update(state='done', current='', finishedAt=time.time())
    except Exception as exc:  # noqa: BLE001 - 迁移失败要原样告诉教练
        shutil.rmtree(staging, ignore_errors=True)
        _migrate_update(state='error', error=str(exc), finishedAt=time.time())


@router.post('/api/data/migrate')
def migrate_legacy(request: Request, payload: dict = Body(default={})):
    """Copy an old portable library into this install (loopback only)."""
    if not _loopback(request):
        raise HTTPException(403, '只允许在本机搬迁数据。')
    with _MIGRATE_LOCK:
        if _MIGRATE_JOB.get('state') in ('scanning', 'copying', 'database', 'upgrading', 'merging'):
            raise HTTPException(409, '已经有一次搬迁在进行中。')
    raw = str(payload.get('path') or '').strip().strip('"')
    if not raw:
        raise HTTPException(400, '请先选择旧数据目录。')
    try:
        source = Path(raw).expanduser().resolve()
    except OSError as exc:
        raise HTTPException(400, f'这个路径读不到：{exc}') from exc
    if not (source / 'training.sqlite3').is_file():
        raise HTTPException(400, '这个目录里没有 training.sqlite3，不像是赛训数据目录。')
    destination = data_root().resolve()
    if source == destination or source in destination.parents or destination in source.parents:
        raise HTTPException(400, '旧目录和当前数据目录是同一个，不需要搬迁。')
    if not _library_is_empty(destination / 'training.sqlite3'):
        raise HTTPException(409, '这台电脑的库里已经有对局了，为避免覆盖不再自动搬迁。')

    include_heavy = bool(payload.get('includeReplays', True))
    with _MIGRATE_LOCK:
        _MIGRATE_JOB.clear()
        _MIGRATE_JOB.update({'state': 'scanning', 'source': str(source),
                             'startedAt': time.time(), 'bytes': 0, 'totalBytes': 0,
                             'copied': 0, 'totalFiles': 0, 'current': '', 'error': ''})
    Thread(target=_run_migration, args=(source, destination, include_heavy),
           daemon=True, name='legacy-migrate').start()
    return {'ok': True, 'job': _migrate_status()}


@router.get('/api/data/migrate')
def migrate_progress():
    return _migrate_status()



@router.get('/api/mode')
def data_mode():
    return {'demo': IS_DEMO, 'application': DEMO_APPLICATION, 'synthetic': IS_DEMO}


@router.post('/api/demo/start')
def start_demo():
    """Open the demo library in the same full single-app workbench.

    Previously the demo spawned a stripped-down read-only module, so it lost
    every capture/import route. V3 is one app: the demo now starts ``server.py`` with
    KPL_DATA_DIR redirected to its own isolated directory. Same features as the
    real workbench, and no write can reach the coach's real data.
    """
    demo_url = f'http://127.0.0.1:{DEMO_PORT}/'
    if IS_DEMO:
        return {'url': demo_url, 'demo': True}
    from urllib.error import HTTPError

    def existing():
        try:
            with urlopen(f'http://127.0.0.1:{DEMO_PORT}/api/mode', timeout=1) as response:
                return json.load(response)
        except HTTPError:
            return {'occupied': True}
        except (OSError, ValueError):
            return None

    with _demo_lock:
        status = existing()
        if status:
            if _demo_status_is_ours(status):
                return {'url': demo_url, 'demo': True}
            raise HTTPException(409, '演示端口 8773 已被其他程序占用。')
        import demo_data
        demo_base = HERE / 'demo-data'
        demo_base.mkdir(exist_ok=True)
        pointer = demo_base / 'active.json'
        demo_root = None
        if pointer.is_file():
            try:
                name = json.loads(pointer.read_text(encoding='utf-8')).get('directory', '')
                if name and Path(name).name == name:
                    candidate = demo_base / name
                    if (candidate / 'DEMO.json').is_file() and (candidate / 'data' / 'training.sqlite3').is_file():
                        demo_root = candidate
            except (OSError, ValueError, AttributeError):
                pass
        if demo_root is None:
            demo_root = demo_base / ('sample-' + uuid.uuid4().hex[:10])
            demo_data.create(demo_root)
            pointer.write_text(json.dumps({'directory':demo_root.name}), encoding='utf-8')
        data = demo_root / 'data'
        # 复用旧演示库时补建统一的 builds/ 目录。
        (data / 'builds').mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        # 清掉所有可能指回真实库的全局覆盖；演示只认自己这一套目录。
        for key in ('STUDIO_CAMP_DIR', 'STUDIO_RESULTS_DB', 'TRAINING_HOST', 'TRAINING_DB',
                    'TRAINING_PORT', 'ANALYSIS_MATCHES', 'ANALYSIS_IMPORTS', 'ANALYSIS_OFFICIAL',
                    'ANALYSIS_BUILDS', 'KPL_DATA_DIR', 'KPL_RECORDINGS', 'MIMO_OCR_CACHE',
                    'HERO_LIST_FILE', 'CAMP_CONFIG_FILE', 'CAMP_REPLAY_DIR'):
            env.pop(key, None)
        env.update({'TRAINING_DEMO_ROOT':str(demo_root), 'KPL_DATA_DIR':str(data),
                    'TRAINING_PORT':str(DEMO_PORT), 'TRAINING_DB':str(data/'training.sqlite3'),
                    'ANALYSIS_MATCHES':str(data/'matches'), 'ANALYSIS_IMPORTS':str(data/'imports'),
                    'ANALYSIS_OFFICIAL':str(data/'official_replays'),
                    'ANALYSIS_BUILDS':str(data/'builds')})
        # 完整单应用：采集、导入、分析路由与真实工作台完全一致。
        subprocess.Popen([sys.executable, str(ROOT/'server.py')], cwd=str(ROOT), env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        import time
        for _ in range(200):            # server.py 冷启动要加载 OCR / 图像模块，留足时间
            status = existing()
            if _demo_status_is_ours(status):
                return {'url': demo_url, 'demo': True}
            if status and status.get('occupied'):
                break
            time.sleep(.15)
        raise HTTPException(503, '演示环境未能启动，请检查端口或重试。')


@router.get('/api/v3/space')
def spatial_analysis():
    return deep_analysis.space(OFFICIAL, DB.parent / 'camp_details', DB.parent)


@router.get('/api/v3/economy')
def economy_analysis():
    return deep_analysis.economy(OFFICIAL, DB.parent / 'camp_details')


def research_result(topic, values):
    from studio_analysis import StudioRepository, extract_rows, fingerprint
    from studio_research import TOPICS, research
    if topic not in {item[0] for item in TOPICS}:
        raise HTTPException(404, '专题不存在')
    source = StudioRepository(DB, MATCHES, IMPORTS)
    rows, warnings = extract_rows(source, values)
    rows = [row for row in rows if row.get('isOwn') and row.get('full')]
    result = research(rows, topic, 'damage', source.get()['matches'] + source.get()['sheetMatches'])
    result['fingerprint'] = fingerprint(rows)
    result['warnings'] = warnings
    result['sourceRows'] = len(rows)
    result['filters'] = values
    return result


@router.get('/api/v3/research/catalog')
def research_catalog():
    from studio_research import TOPICS
    return {'topics': [{'id':key,'name':name,'description':desc} for key,name,desc in TOPICS]}


@router.get('/api/v3/research/reports')
def research_reports():
    path = DB.with_name('reports.sqlite3')
    if not path.is_file(): return {'reports': []}
    with sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True) as conn:
        try: rows = conn.execute('SELECT id,title,created_at,topic FROM reports ORDER BY created_at DESC').fetchall()
        except sqlite3.Error: rows = []
    return {'reports': [{'id':r[0],'title':r[1],'createdAt':r[2],'topic':r[3]} for r in rows]}


@router.get('/api/v3/research/reports/{report_id}')
def research_report(report_id: str):
    path = DB.with_name('reports.sqlite3')
    if not path.is_file(): raise HTTPException(404, '报告不存在')
    with sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True) as conn:
        row=conn.execute('SELECT title,created_at,body FROM reports WHERE id=?', (report_id,)).fetchone()
    if not row: raise HTTPException(404, '报告不存在')
    return {'title':row[0],'createdAt':row[1],'result':json.loads(row[2])}


@router.get('/api/v3/research/{topic}')
def get_research(topic: str, values=Depends(filters)):
    return research_result(topic, values)


@router.post('/api/v3/research/reports')
async def save_research_report(request: Request):
    body=await read_json(request)
    title=str(body.get('title') or '').strip() if isinstance(body,dict) else ''
    if not title or len(title)>120: raise HTTPException(400, '请填写 1–120 字的报告标题。')
    values=body.get('filters')
    if not isinstance(values,dict): raise HTTPException(400, '数据范围无效。')
    values={k:v for k,v in values.items() if k in ('sources','from','to','hero','opponent','excludeSeeds','ownOnly')}
    if not isinstance(values.get('sources'),list) or any(x not in ALL_SOURCES for x in values['sources']):
        raise HTTPException(400, '来源无效。')
    result=research_result(body.get('topic',''), values)
    if not result['rows']: raise HTTPException(400, '当前没有可保存的专题结果。')
    if result['fingerprint'] != body.get('fingerprint'): raise HTTPException(409, '数据已变化，请刷新后再保存。')
    from datetime import datetime, timezone
    report_id=uuid.uuid4().hex; created=datetime.now(timezone.utc).isoformat(timespec='seconds')
    with sqlite3.connect(DB.with_name('reports.sqlite3')) as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS reports (id TEXT PRIMARY KEY,title TEXT NOT NULL,created_at TEXT NOT NULL,topic TEXT NOT NULL,body TEXT NOT NULL)')
        conn.execute('INSERT INTO reports VALUES(?,?,?,?,?)',(report_id,title,created,body['topic'],json.dumps(result,ensure_ascii=False)))
    return {'id':report_id,'title':title,'createdAt':created}


@router.post('/api/v3/import/preview')
async def preview_sheet(request: Request, name: str = ''):
    """Preview an uploaded sheet without deleting or overwriting files."""
    from sheet_import import SheetImportError, infer_profile, read_workbook
    suffix = Path(name).suffix.lower()
    if suffix not in ('.csv', '.tsv', '.xlsx', '.xlsm'):
        raise HTTPException(400, '请选择 CSV、TSV、XLSX 或 XLSM 文件。')
    content = await request.body()
    if not content or len(content) > 20 * 1024 * 1024:
        raise HTTPException(400, '文件为空或超过 20 MB。')
    folder = IMPORTS / '_import_previews'; folder.mkdir(parents=True, exist_ok=True)
    preview_id = uuid.uuid4().hex
    path = folder / (preview_id + suffix)
    with path.open('xb') as out:
        out.write(content)
    with (folder / (preview_id + '.meta.json')).open('x', encoding='utf-8') as out:
        json.dump({'name':Path(name).name, 'suffix':suffix}, out, ensure_ascii=False)
    try:
        workbook = read_workbook(path)
        strict = request.query_params.get('strict') == '1'
        source_sheets = (workbook.get('sheets') or [])[:1] if strict else (workbook.get('sheets') or [])
        sheets = []
        for sheet in source_sheets:
            reject_example_table(sheet)
            if strict:
                validate_table(sheet)
            profile = infer_profile(sheet)
            sheets.append({'name':sheet['name'], 'rows':len(sheet['rows']), 'header':sheet['header'],
                           'sample':sheet['rows'][:5], 'grain':profile.get('grain'),
                           'columns':profile.get('columns', []), 'warnings':profile.get('warnings', []),
                           'unmappedColumns':profile.get('unmappedColumns', [])})
        if not sheets: raise SheetImportError('表格没有可读取的工作表。')
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    except SheetImportError as error:
        raise HTTPException(400, str(error)) from error
    return {'previewId':preview_id, 'name':Path(name).name, 'sheets':sheets}


def _single_match_sheet(sheet, profile):
    """这页是否只有一局（本局十人模板）。多局表不套用单一「本队阵营」。"""
    keys = profile.get('keys') or {}
    header = sheet.get('header') or []
    for field in ('matchId', 'matchNo'):
        column = keys.get(field)
        if not column or column not in header:
            continue
        index = header.index(column)
        values = {str(row[index]).strip() for row in sheet.get('rows') or []
                  if index < len(row) and str(row[index]).strip()}
        return len(values) == 1
    return False


@router.post('/api/v3/import/commit')
async def commit_sheet(request: Request):
    from sheet_import import SheetImportError, infer_profile, read_workbook, write_staging
    body = await read_json(request)
    preview_id = body.get('previewId', '') if isinstance(body, dict) else ''
    if len(preview_id) != 32 or any(c not in '0123456789abcdef' for c in preview_id):
        raise HTTPException(400, '预览标识无效。')
    own_side = str(body.get('ownSide') or '').strip().lower() if isinstance(body, dict) else ''
    if own_side not in ('', 'blue', 'red'):
        raise HTTPException(400, '本队阵营只能是蓝方或红方。')
    folder = IMPORTS / '_import_previews'
    try:
        meta = json.loads((folder/(preview_id+'.meta.json')).read_text(encoding='utf-8'))
        if meta.get('suffix') not in ('.csv','.tsv','.xlsx','.xlsm'): raise ValueError('invalid suffix')
        workbook = read_workbook(folder/(preview_id+meta['suffix']))
        workbook['source']['name'] = meta.get('name') or '表格'
        if isinstance(body, dict) and body.get('strict'):
            workbook['sheets'] = (workbook.get('sheets') or [])[:1]
            if not workbook['sheets']:
                raise ValueError('表格没有可读取的工作表')
            validate_table(workbook['sheets'][0])
        for sheet in workbook['sheets']:
            reject_example_table(sheet)
        for manifest in IMPORTS.glob('*/manifest.json'):
            try:
                existing=json.loads(manifest.read_text(encoding='utf-8'))
                if (existing.get('source') or {}).get('sha256') == workbook['source']['sha256']:
                    raise HTTPException(409, '该文件已经导入；为避免重复统计，不会再次导入。')
            except (OSError, ValueError, AttributeError):
                continue
        profiles={sheet['name']:infer_profile(sheet) for sheet in workbook['sheets']}
        if own_side:
            for sheet in workbook['sheets']:
                if _single_match_sheet(sheet, profiles[sheet['name']]):
                    profiles[sheet['name']]['ownSide'] = own_side
        destination=IMPORTS/('import-'+uuid.uuid4().hex[:16]); destination.mkdir(parents=True,exist_ok=False)
        manifest=write_staging(workbook['source'],workbook['sheets'],profiles,destination,'inferred')
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    except (OSError, SheetImportError) as error:
        raise HTTPException(400, '读取表格失败：'+str(error)) from error
    return {'ok':True,'id':destination.name,'quality':manifest.get('quality',{}),
            'warnings':manifest.get('warnings',[]),'sheets':manifest.get('sheets',[])}


def _settings():
    """本机设置（本队资料 / 旧名单 / 旧别名）；读不到就当空。"""
    if not DB.is_file():
        return {}
    try:
        with closing(sqlite3.connect(DB)) as connection:
            row = connection.execute('SELECT body FROM settings WHERE id=1').fetchone()
    except sqlite3.Error:
        return {}
    try:
        value = json.loads(row[0]) if row else {}
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def own_team():
    """本队档案：settings.teamName 对应的战队，其次 team-own。命名选手时的默认战队。"""
    settings = _settings()
    name = str(settings.get('teamName') or '').strip()
    if DB.is_file():
        try:
            with closing(sqlite3.connect(DB)) as connection:
                if name:
                    row = connection.execute(
                        "SELECT id, name FROM teams WHERE name=? AND status='active' ORDER BY id LIMIT 1",
                        (name,)).fetchone()
                    if row:
                        return {'id': row[0], 'name': row[1]}
                row = connection.execute("SELECT id, name FROM teams WHERE id='team-own'").fetchone()
                if row:
                    return {'id': row[0], 'name': row[1]}
        except sqlite3.Error:
            pass
    return {'id': 'team-own', 'name': name or '我方战队'}


def _identity_teams():
    """命名字段里可选的战队：工作区主数据，待命名的排在后面。"""
    import workspace_store
    try:
        teams = workspace_store.Workspace(DB).list_teams()
    except sqlite3.Error:
        return []
    rows = [{'id': team['id'], 'name': team['name'], 'coach': team.get('coach') or '',
             'named': not str(team['name']).startswith('待命名')} for team in teams]
    rows.sort(key=lambda item: (not item['named'], item['name']))
    return rows


def _label_accounts(label, side='own'):
    """昵称 → 该昵称在营地面板里出现过的账号（供旧版认领接口定位账号）。"""
    label = str(label or '').strip()
    found = []
    for row in _camp_records()['records']:
        if side and row.get('side') != side:
            continue
        if (row.get('nickname') or '') == label and row.get('accountId'):
            if row['accountId'] not in found:
                found.append(row['accountId'])
    return found


@router.get('/api/v3/identity/accounts')
def identity_accounts(side: str = '', state: str = '', q: str = ''):
    """身份对照：一行一个游戏账号，游戏 ID → 选手 → 战队。

    读的是同一份口径：账号出现在哪几局、当时在哪支队、现在挂在谁名下。
    改映射不影响历史对局，这里只负责显示当前状态。
    """
    facts = _camp_records()
    mapping = camp_accounts()
    teams = _identity_teams()
    team_names = {team['id']: team['name'] for team in teams}
    try:
        import team_clusters
        cluster_team = team_clusters.account_team_index(MATCHES.parent / 'camp_details', DB)
    except Exception:
        cluster_team = {}
    home = own_team()

    buckets = {}
    for row in facts['records']:
        account_id = row.get('accountId') or ''
        key = account_id or 'nick:' + (row.get('nickname') or row.get('name') or '')
        item = buckets.get(key)
        if item is None:
            item = buckets[key] = {
                'accountId': account_id,
                'nickname': row.get('nickname') or row.get('name') or '',
                'games': 0, 'own': 0, 'enemy': 0, 'wins': 0, 'decided': 0,
                'lanes': Counter(), 'heroes': Counter(), 'opponents': Counter(),
                'days': set(), 'lastSeen': '',
            }
        item['games'] += 1
        item['own' if row.get('side') == 'own' else 'enemy'] += 1
        if row.get('result') in ('win', 'loss'):
            item['decided'] += 1
            if row['result'] == 'win':
                item['wins'] += 1
        if row.get('lane'):
            item['lanes'][row['lane']] += 1
        if row.get('hero'):
            item['heroes'][row['hero']] += 1
        if row.get('opponent'):
            item['opponents'][row['opponent']] += 1
        if row.get('day'):
            item['days'].add(row['day'])
        stamp = str(row.get('at') or row.get('day') or '')
        if stamp > item['lastSeen']:
            item['lastSeen'] = stamp

    rows = []
    for item in buckets.values():
        account_id = item['accountId']
        mapped = mapping.get(account_id) if account_id else None
        own_side = item['own'] >= item['enemy']
        default_team = home['id'] if own_side else (cluster_team.get(account_id) or '')
        if mapped:
            default_team = mapped.get('teamId') or default_team
        rows.append({
            'accountId': account_id,
            'nickname': item['nickname'],
            'side': 'own' if own_side else 'enemy',
            'games': item['games'], 'own': item['own'], 'enemy': item['enemy'],
            'winRate': round(item['wins'] / item['decided'] * 100, 1) if item['decided'] else None,
            'lane': (item['lanes'].most_common(1)[0][0] if item['lanes'] else ''),
            'lanes': [lane for lane, _ in item['lanes'].most_common()],
            'heroes': [hero for hero, _ in item['heroes'].most_common(3)],
            'opponents': [name for name, _ in item['opponents'].most_common(2)],
            'days': len(item['days']), 'lastSeen': item['lastSeen'],
            'mapped': bool(mapped),
            'playerId': (mapped or {}).get('playerId') or '',
            'name': (mapped or {}).get('name') or '',
            'position': (mapped or {}).get('position') or '',
            'positions': (mapped or {}).get('positions') or [],
            'teamId': (mapped or {}).get('teamId') or '',
            'teamName': (mapped or {}).get('teamName') or '',
            'suggestTeamId': default_team,
            'suggestTeamName': team_names.get(default_team, ''),
        })

    query = str(q or '').strip().lower()
    if side in ('own', 'enemy'):
        rows = [row for row in rows if row['side'] == side]
    if state == 'mapped':
        rows = [row for row in rows if row['mapped']]
    elif state == 'unmapped':
        rows = [row for row in rows if not row['mapped']]
    if query:
        rows = [row for row in rows
                if query in (row['nickname'] + ' ' + row['name'] + ' ' + row['teamName']).lower()]
    # 已命名的排前面：命名完这一行要还在原地，不能沉到几百个待命名后面去。
    rows.sort(key=lambda row: (not row['mapped'], -row['games'], row['nickname']))

    counters = {
        'total': len(rows), 'mapped': sum(1 for row in rows if row['mapped']),
        'unmapped': sum(1 for row in rows if not row['mapped']),
        'own': sum(1 for row in rows if row['side'] == 'own'),
        'enemy': sum(1 for row in rows if row['side'] == 'enemy'),
    }
    return {'rows': rows, 'teams': teams, 'ownTeam': home, 'counters': counters}


@router.get('/api/v3/identity')
def identity_view(repo=Depends(repository), values=Depends(filters)):
    data = repo.get()
    rows, _ = repo._selected_rows(values)
    settings = _settings()
    aliases = {str(key): str(value) for key, value in (settings.get('aliases') or {}).items()}
    mapping = camp_accounts()
    # 名单以选手主数据为准；旧 settings.roster 只在还没迁移时兜底显示。
    try:
        import workspace_store
        members = workspace_store.Workspace(DB).list_players()
    except sqlite3.Error:
        members = []
    if not members:
        team_name = str(settings.get('teamName') or '').strip()
        members = [dict(member, label=member.get('name') or '')
                   for member in (settings.get('members') or settings.get('roster') or [])
                   if not member.get('archived')
                   and (not member.get('team') or member.get('team') == team_name)]
    by_name = {}
    for member in members:
        for label in (member.get('name'), member.get('label')):
            if label:
                by_name[str(label)] = member
    groups = {}
    for row in rows:
        label = row.get('rawLabel') or row.get('label')
        if not row.get('isOwn') or not label:
            continue
        item = groups.setdefault(label, {'label': label, 'matches': set(), 'heroes': set(),
                                         'accountIds': set(), 'bound': False})
        if row.get('matchKey'):
            item['matches'].add(row['matchKey'])
        if row.get('hero'):
            item['heroes'].add(row['hero'])
        if row.get('accountId'):
            item['accountIds'].add(str(row['accountId']))
        item['bound'] = item['bound'] or bool(row.get('bound'))
    entries = []
    for item in groups.values():
        mapped = next((mapping[account] for account in item['accountIds'] if account in mapping), None)
        member = mapped or by_name.get(item['label']) or (
            members[0] if aliases.get(item['label']) else None)
        entries.append({'label': item['label'], 'matches': len(item['matches']),
                        'heroes': sorted(item['heroes']),
                        'accountIds': sorted(item['accountIds']),
                        'bound': bool(mapped or member),
                        'memberId': (member or {}).get('id'),
                        'name': (mapped or {}).get('name') or ''})
    entries.sort(key=lambda x: (x['bound'], -x['matches'], x['label']))
    return {'entries': entries, 'members': members, 'aliases': aliases,
            'teamName': str(settings.get('teamName') or '')}


@router.post('/api/v3/identity/name')
async def name_identity(request: Request):
    """唯一的命名写入口：游戏账号 → 选手 → 战队。建档 / 对手归属 / 选手页都走这里。"""
    body = await read_json(request)
    if not isinstance(body, dict):
        raise HTTPException(400, '命名信息无效。')
    account_id = str(body.get('accountId') or '').strip()
    label = str(body.get('label') or '').strip()
    nickname = str(body.get('nickname') or label or '').strip()
    account_ids = [account_id] if account_id else (_label_accounts(label) if label else [])
    if not account_ids and not body.get('playerId'):
        raise HTTPException(400, '请选择要命名的游戏账号。')
    name = str(body.get('name') or '').strip()
    position = str(body.get('position') or '').strip()
    raw_positions = body.get('positions')
    if isinstance(raw_positions, str):
        raw_positions = [raw_positions]
    positions = [str(item).strip() for item in (raw_positions or []) if str(item).strip()]
    team_id = str(body.get('teamId') or '').strip()
    team_name = str(body.get('team') or body.get('teamName') or '').strip()
    if not name:
        raise HTTPException(400, '请填写选手名称。')
    if len(name) > 40 or len(team_name) > 40:
        raise HTTPException(400, '选手名称或战队名称过长。')
    # 本队侧的号不填战队就落到本队档案；对手侧必须显式选队，不替教练猜。
    default_team_id = ''
    if not team_id and not team_name:
        side = next((row['side'] for row in _camp_records()['records']
                     if row.get('accountId') and row['accountId'] in account_ids), '')
        if side == 'own':
            default_team_id = own_team()['id']
    saved = []
    try:
        for index, account in enumerate(account_ids or ['']):
            saved.append(identity_service.name_account(
                DB, account_id=account, nickname=nickname, positions=positions or None,
                player_id=body.get('playerId') if index == 0 else None,
                name=name, position=position,
                team_id=team_id if index == 0 else '', team_name=team_name,
                default_team_id=default_team_id if index == 0 else '', actor='coach'))
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    invalidate_players_cache()
    return {'ok': True, 'saved': saved, 'count': len(saved)}


@router.post('/api/v3/identity/players')
async def save_identity_player(request: Request):
    """建档页的「添加 / 编辑选手」：不涉及游戏账号。"""
    body = await read_json(request)
    if not isinstance(body, dict):
        raise HTTPException(400, '选手信息无效。')
    try:
        saved = identity_service.save_player(
            DB, player_id=body.get('id') or None, name=body.get('name') or '',
            position=body.get('position') or '', team_id=body.get('teamId') or '',
            team_name=body.get('team') or body.get('teamName') or '',
            camp_user_id=body.get('campUserId') or None, actor='coach')
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    invalidate_players_cache()
    return {'ok': True, 'id': saved['playerId'], **saved}


@router.post('/api/v3/identity/players/delete')
async def delete_identity_player(request: Request):
    """删除选手：连他的游戏账号映射一起删，这些账号回到「待命名」。"""
    body = await read_json(request)
    player_id = str(body.get('playerId') or body.get('id') or '').strip() if isinstance(body, dict) else ''
    if not player_id:
        raise HTTPException(400, '缺少选手 ID。')
    try:
        removed = identity_service.delete_player(DB, player_id, actor='coach')
    except ValueError as error:
        raise HTTPException(404, str(error)) from error
    invalidate_players_cache()
    return {'ok': True, **removed}


@router.post('/api/v3/identity/accounts/unmap')
async def unmap_identity_account(request: Request):
    """解除一个游戏账号的绑定（认错人 / 换号），选手其它账号不动。"""
    body = await read_json(request)
    account_id = str(body.get('accountId') or '').strip() if isinstance(body, dict) else ''
    if not account_id:
        raise HTTPException(400, '缺少游戏账号 ID。')
    try:
        result = identity_service.unmap_account(DB, account_id, actor='coach')
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    invalidate_players_cache()
    return {'ok': True, **result}


@router.post('/api/v3/identity/roster')
async def add_roster_member(request: Request):
    """兼容旧入口：把「添加本队选手」转给同一份 save_player。"""
    body = await read_json(request)
    if not isinstance(body, dict):
        raise HTTPException(400, '请填写选手名称并选择有效位置。')
    home = own_team()
    try:
        saved = identity_service.save_player(
            DB, name=body.get('name') or '', position=body.get('position') or '',
            team_id=home['id'], actor='coach')
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    invalidate_players_cache()
    return {'ok': True, 'id': saved['playerId'], 'playerId': saved['playerId']}


@router.post('/api/v3/identity/claim')
async def claim_identity(request: Request):
    """兼容旧入口：按昵称认领到本队选手，写的是同一条账号映射。"""
    body = await read_json(request)
    if not isinstance(body, dict):
        raise HTTPException(400, '认领信息无效。')
    label = str(body.get('label') or '').strip()
    player_id = str(body.get('playerId') or '').strip()
    if not label or not player_id or len(label) > 100:
        raise HTTPException(400, '请选择昵称和本队选手。')
    account_ids = _label_accounts(label, side='own')
    if not account_ids:
        raise HTTPException(400, '该昵称不在本队记录中，请先确认阵营。')
    try:
        for account in account_ids:
            identity_service.name_account(DB, account_id=account, nickname=label,
                                          player_id=player_id, actor='coach')
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    invalidate_players_cache()
    return {'ok': True, 'playerId': player_id, 'accounts': len(account_ids)}


@router.post('/api/v3/match-bp/{key:path}')

async def update_match_bp(key: str, request: Request, repo=Depends(repository)):
    """Save only explicitly entered BP order in a V3-specific overlay."""
    from bp_input import validate_bp
    import time
    if repo.match_detail(key) is None: raise HTTPException(404, '找不到该场对局')
    body=await read_json(request)
    if not isinstance(body,dict): raise HTTPException(400, 'BP 格式无效')
    try:
        bp=validate_bp(body.get('bp'))
        expected=int(body.get('expectedRevision') or 0)
    except (ValueError,TypeError) as error:
        raise HTTPException(400, str(error)) from error
    if not any(hero for kind in ('bans','picks') for side in ('left','right') for hero in bp[kind][side]):
        raise HTTPException(400, '请至少填写一项已确认的禁选。')
    with sqlite3.connect(DB) as connection:
        connection.execute('CREATE TABLE IF NOT EXISTS bp_overrides (match_key TEXT PRIMARY KEY,body TEXT NOT NULL,revision INTEGER NOT NULL,updated_at REAL NOT NULL)')
        connection.execute('BEGIN IMMEDIATE')
        current=connection.execute('SELECT revision FROM bp_overrides WHERE match_key=?',(key,)).fetchone()
        revision=current[0] if current else 0
        if revision != expected: raise HTTPException(409, 'BP 已被修改，请刷新后重新核对。')
        connection.execute('INSERT INTO bp_overrides VALUES(?,?,?,?) ON CONFLICT(match_key) DO UPDATE SET body=excluded.body,revision=excluded.revision,updated_at=excluded.updated_at',
                           (key,json.dumps(bp,ensure_ascii=False),revision+1,time.time()))
    return {'ok':True,'revision':revision+1}


@router.post('/api/v3/match-meta/{key:path}')
async def update_match_meta(key: str, request: Request, repo=Depends(repository)):
    """Write the verified match overlay without invoking V1 file cleanup."""
    import time
    if not key or len(key) > 200 or repo.match_detail(key) is None:
        raise HTTPException(404, '找不到该场对局')
    body = await read_json(request)
    if not isinstance(body, dict):
        raise HTTPException(400, '数据格式无效')
    patch = {}
    for name, limit in (('opponent',50),('session',40),('version',40),('mode',20)):
        if name in body:
            if not isinstance(body[name], str) or len(body[name].strip()) > limit:
                raise HTTPException(400, '字段格式或长度不正确')
            patch[name] = body[name].strip()
    camp = body.get('ownCamp')
    if camp not in ('blue','red','',None):
        raise HTTPException(400, '阵营无效')
    if 'ownCamp' in body:
        patch['ownCamp'] = camp or None
    # 10 分钟经济：营地没有逐人金币时间轴，只能手填。键是「阵营-槽位」，值是整数金币。
    gold10 = body.get('gold10')
    if gold10 is not None:
        if not isinstance(gold10, dict) or len(gold10) > 10:
            raise HTTPException(400, '10 分钟经济格式无效')
        cleaned = {}
        for name, value in gold10.items():
            text = str(name or '').strip()
            if not text or len(text) > 40:
                raise HTTPException(400, '10 分钟经济的选手标识无效')
            if value in (None, ''):
                continue
            try:
                number = int(float(value))
            except (TypeError, ValueError):
                raise HTTPException(400, f'{text} 的 10 分钟经济不是数字')
            if not 0 <= number <= 100000:
                raise HTTPException(400, f'{text} 的 10 分钟经济超出合理范围')
            cleaned[text] = number
        patch['gold10'] = cleaned
    result = body.get('result')
    if result not in ('win','loss','draw','unknown',None):
        raise HTTPException(400, '赛果无效')
    if result is not None:
        patch['result'] = result
    # 单局补录同样走词表：`S40赛季` / `s40` 落库前折成 `S40`，新值自动登记。
    for name, kind in (('version', 'versions'), ('session', 'sessions')):
        if name in patch:
            patch[name] = vocab_store.prepare(kind, patch[name], DATA_DIR)
    if not patch:
        raise HTTPException(400, '没有要保存的内容')
    with sqlite3.connect(DB) as connection:
        connection.execute('CREATE TABLE IF NOT EXISTS match_meta (match_key TEXT PRIMARY KEY, body TEXT NOT NULL, updated_at REAL NOT NULL)')
        connection.execute('BEGIN IMMEDIATE')
        row = connection.execute('SELECT body FROM match_meta WHERE match_key=?', (key,)).fetchone()
        try:
            previous = json.loads(row[0]) if row else {}
            if not isinstance(previous, dict): previous = {}
        except (ValueError, TypeError):
            previous = {}
        previous.update(patch)
        connection.execute('INSERT INTO match_meta(match_key,body,updated_at) VALUES(?,?,?) ON CONFLICT(match_key) DO UPDATE SET body=excluded.body,updated_at=excluded.updated_at',
                           (key,json.dumps(previous,ensure_ascii=False),time.time()))
    return {'ok': True, 'meta': previous}


@router.get('/api/v3/workspace/overview')
def workspace_overview(repo=Depends(repository)):
    selection = {'sources': list(ALL_SOURCES), 'excludeSeeds': True, 'ownOnly': True}
    return {'overview': repo.overview(selection)}


def migration_candidates(repo):
    """Select real legacy matches without altering existing structured records."""
    import workspace_store
    ws = workspace_store.Workspace(DB).ensure_schema()
    with closing(ws.connect()) as connection:
        existing = {row[0] for row in connection.execute('SELECT match_key FROM match_records')}
        counts = {name: connection.execute('SELECT COUNT(*) FROM ' + name).fetchone()[0]
                  for name in ('match_records', 'match_rosters', 'bp')}
    selection = {'sources': list(ALL_SOURCES), 'excludeSeeds': True, 'ownOnly': True}
    matches = repo.matches(selection).get('matches', [])
    return ws, counts, [m for m in matches if m.get('key') and m['key'] not in existing]


@router.get('/api/v3/workspace/migration')
def migration_preview(repo=Depends(repository)):
    _, counts, candidates = migration_candidates(repo)
    return {'counts': counts, 'candidates': len(candidates),
            'note': '仅新增未迁移的真实对局基本信息；不覆盖现有记录，不推测选手身份、对手归属及 BP 手序。'}


@router.post('/api/v3/workspace/migration')
def migrate_new_matches(repo=Depends(repository)):
    import time
    ws, _, candidates = migration_candidates(repo)
    inserted = 0
    with closing(ws.connect()) as connection, connection:
        connection.execute('BEGIN IMMEDIATE')
        for match in candidates:
            own = match.get('ownCamp') if match.get('ownCamp') in ('blue', 'red') else None
            result = match.get('result')
            winner = (own if result == 'win' else {'blue': 'red', 'red': 'blue'}.get(own)) if own and result in ('win', 'loss') else None
            scores = match.get('scores')
            score = json.dumps(scores, ensure_ascii=False) if isinstance(scores, dict) and any(v is not None for v in scores.values()) else None
            fields = {'date': match.get('date'), 'session': match.get('session'),
                      'mode': match.get('mode'), 'version': match.get('version'),
                      'own_side': own, 'winner': winner, 'score': score, 'duration': match.get('duration')}
            cursor = connection.execute(
                'INSERT OR IGNORE INTO match_records(match_key, date, session, mode, version, own_side, winner, score, duration, status, source) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (match['key'], *fields.values(), 'draft', match.get('source') or 'unknown'))
            if not cursor.rowcount:
                continue
            inserted += 1
            for field, value in fields.items():
                if value is not None and value != '':
                    connection.execute('INSERT INTO provenance(match_key,field,source,confidence,synthetic,updated_at) VALUES(?,?,?,?,?,?)',
                                       (match['key'], field, match.get('source') or 'unknown', 'medium', 0, time.time()))
    return {'ok': True, 'created': inserted}


@router.get('/api/v3/team-bp')
def team_bp():
    """Opponent picks and bans from recorded lineups, without inventing order."""
    import team_clusters
    from bp_camp import parse_camp_bp
    camp_dir = MATCHES.parent / 'camp_details'
    clusters = team_clusters.list_teams(camp_dir, DB)
    teams = []
    for team in clusters['teams']:
        picks, bans = Counter(), Counter()
        available = 0
        for seq in team.get('seqs', []):
            try:
                detail = json.loads((camp_dir / (str(seq) + '.json')).read_text(encoding='utf-8'))
                bp = parse_camp_bp(detail, seq)
            except (OSError, ValueError):
                continue
            if not bp or bp.get('ownSide') not in ('left', 'right'):
                continue
            side = 'right' if bp['ownSide'] == 'left' else 'left'
            available += 1
            for entry in bp['picks'][side]:
                picks[entry['name']] += 1
            for entry in bp['bans'][side]:
                bans[entry['name']] += 1
        teams.append({'id': team['id'], 'name': team['displayName'],
                      'games': team['matches'], 'available': available,
                      'picks': [{'hero': k, 'count': v} for k, v in picks.most_common()],
                      'bans': [{'hero': k, 'count': v} for k, v in bans.most_common()]})
    return {'teams': teams}


@router.get('/api/v3/bp-board')
def bp_board():
    """BP 三页共用的全量聚合：营地面板终局名单 + 战队 / 教练档案。

    营地只给「谁上场 / 谁被禁」的终局名单，没有禁选先后顺序，也不含一手方。
    这里只输出逐局名单与元数据；筛选、画像、风格指标由前端按局实时重算，
    这样 BP 概览 / 战队 BP / 教练档案三页用的是同一份口径，不会混算。
    """
    import team_clusters
    from bp_camp import parse_camp_bp
    camp_dir = MATCHES.parent / 'camp_details'
    clusters = team_clusters.list_teams(camp_dir, DB)
    teams = clusters['teams']
    # 教练由使用者在战队档案里录入；开发期按「已补好」的默认状态在展示层预置一组
    # 稳定姓名，录入真名后自动覆盖。只影响展示，不改写档案数据库。
    preset_coaches = ('陈昱', '林澈', '周砚', '吴珂', '郑霖', '孙骁', '赵衡', '钱越',
                      '李牧', '王铮', '刘屿', '黄铮', '徐墨', '何川', '高岩', '马骁',
                      '沈砚', '许澈', '韩昱', '唐珂', '冯霖', '曹衡', '彭越', '董牧',
                      '袁铮', '邓屿', '傅墨', '苏川', '蒋岩', '卢骁', '余澈', '叶昱')
    coach_of = {t['id']: (t.get('coach') or preset_coaches[i % len(preset_coaches)])
                for i, t in enumerate(teams)}
    seq_team = {seq: team for team in teams for seq in team.get('seqs', [])}
    games, hero_meta = [], {}
    for panel in team_clusters.load_panels(camp_dir):
        seq = panel['seq']
        try:
            detail = json.loads((camp_dir / (seq + '.json')).read_text(encoding='utf-8'))
            bp = parse_camp_bp(detail, seq)
        except (OSError, ValueError):
            continue
        if not bp:
            continue
        own = bp.get('ownSide') if bp.get('ownSide') in ('left', 'right') else (
            'left' if panel['own'] == 'blue' else 'right')
        enemy = 'right' if own == 'left' else 'left'
        team = seq_team.get(seq) or {}
        start = panel.get('start') or ''
        day = start.split(' ')[0]
        result = panel.get('win')
        if result is None and bp.get('winnerSide'):
            result = bp['winnerSide'] == own
        hero_meta.update(bp.get('heroMeta') or {})

        def entries(kind, side):
            return [{'name': e.get('name'), 'icon': e.get('icon'), 'lane': e.get('lane')}
                    for e in (bp.get(kind) or {}).get(side, []) if e.get('name')]

        games.append({
            'key': seq, 'start': start, 'day': day,
            'session': day.replace('-', '/') + ' 训练赛' if day else '训练赛',
            'opponent': team.get('displayName') or '未归属对手',
            'teamId': team.get('id') or '', 'coach': coach_of.get(team.get('id'), ''),
            'result': 'win' if result else ('loss' if result is False else None),
            'side': panel['own'], 'ownSide': own,
            'duration': bp.get('duration'), 'mapName': bp.get('mapName'),
            'picks': {'own': entries('picks', own), 'enemy': entries('picks', enemy)},
            'bans': {'own': entries('bans', own), 'enemy': entries('bans', enemy)},
            'players': {'own': [p.get('name') for p in panel['own_roster']],
                        'enemy': [p.get('name') for p in panel['enemy_roster']]},
            # 终局面板的经济 / 击杀 / 推塔 / 龙，供教练档案与 BP 页做资源口径；
            # 视角固定为「本队 = own」，前端按需要翻转成教练一方。
            'stats': {'own': (bp.get('teamStats') or {}).get(own) or {},
                      'enemy': (bp.get('teamStats') or {}).get(enemy) or {}},
        })
    games.sort(key=lambda g: g['start'], reverse=True)
    return {
        'games': games,
        'teams': [{'id': t['id'], 'name': t['displayName'], 'coach': coach_of[t['id']],
                   'matches': t['matches'], 'wins': t['wins'], 'losses': t['losses'],
                   'players': [p.get('name') for p in t['players'][:6]]} for t in teams],
        'heroMeta': hero_meta,
        'source': '营地终局名单 · 不推断禁选先后顺序',
    }


@router.get('/api/v3/effect')
def training_effect_analysis():
    import workspace_store
    workspace = workspace_store.Workspace(DB).ensure_schema()
    return deep_analysis.training_effects(DB.parent / 'camp_details', workspace)


@router.get('/api/v3/team-training')
def team_training_ledger():
    """按对手的训练台账：训练计划里的排期 + 营地交手日自动归集。"""
    import team_clusters
    import workspace_store
    workspace = workspace_store.Workspace(DB).ensure_schema()
    return team_clusters.team_training(MATCHES.parent / 'camp_details', DB,
                                       workspace.list_schedules(), MATCHES)


# ── 选手看板：营地十人面板 → 逐人逐局记录 ──────────────────────────────
# 四张选手页（名单与状态 / 选手认领 / 选手与位置 / 选手对比）共用这一份数据。
# 只用营地自己的字段：battleStats 的击杀/死亡/助攻/经济/输出/承伤/参团/评分，
# 以及 battleRecords 的 position / usedHero。不推算、不补值。
_CAMP_LANES = {0: '对抗路', 1: '中路', 2: '发育路', 3: '打野', 4: '游走'}
_CAMP_LANE_ORDER = ['对抗路', '打野', '中路', '发育路', '游走']
_CAMP_ALIASES = str.maketrans('', '', ''.join(chr(code) for code in
    (0x2004, 0x200b, 0x200c, 0x200d, 0x200e, 0x200f, 0x2060, 0x2061, 0x2062, 0x2063, 0x2064,
     0xfe00, 0xfe01, 0xfe02, 0xfe03, 0xfe04, 0xfe05, 0xfe06, 0xfe07, 0xfe08, 0xfe09, 0xfe0a,
     0xfe0b, 0xfe0c, 0xfe0d, 0xfe0e, 0xfe0f, 0xfeff)))
_players_cache = None
_players_at = 0.0


def _camp_number(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(',', '').replace('%', '')
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _camp_name(value):
    return str(value or '').translate(_CAMP_ALIASES).strip()


def camp_accounts():
    """游戏账号（营地 playerId）→ 选手 / 战队映射；表还没建或没库时返回空表。

    一次读全表，供给十人面板解析、选手看板与身份对照页；单条查询会拖慢 32 局的全量解析。
    """
    if not DB.is_file():
        return {}
    try:
        with closing(sqlite3.connect(f'file:{DB.as_posix()}?mode=ro', uri=True)) as connection:
            rows = connection.execute(
                'SELECT a.account_id, a.nickname, p.id AS player_id, p.name, p.position,'
                ' p.positions, p.team_id, t.name AS team_name'
                ' FROM player_accounts a JOIN players p ON p.id = a.player_id'
                ' LEFT JOIN teams t ON t.id = p.team_id WHERE a.platform = ?', ('camp',)).fetchall()
    except sqlite3.Error:
        return {}
    index = {}
    for account_id, nickname, player_id, name, position, positions, team_id, team_name in rows:
        try:
            slots = json.loads(positions or '[]')
        except (TypeError, ValueError):
            slots = []
        index[str(account_id)] = {
            'accountId': str(account_id), 'nickname': nickname or '', 'playerId': player_id or '',
            'name': name or '', 'position': position or '', 'positions': slots or [],
            'teamId': team_id or '', 'teamName': team_name or '',
        }
    return index


def invalidate_players_cache():
    """身份 / 战队改名后清掉选手看板缓存，页面刷新立即按新名字聚合。"""
    global _players_cache, _players_at
    _players_cache, _players_at = None, 0.0


def _panel_games():
    """营地面板 id → 对局标题 / 对手 / 日期，用于把面板挂回训练赛。"""
    index = {}
    for path in (ROOT / 'data' / 'matches').glob('*.json'):
        try:
            body = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        match = body.get('match') or {}
        seq = str((match.get('campBp') or {}).get('gameSeq') or '')
        if not seq:
            continue
        date = match.get('date') or {}
        index[seq] = {'key': match.get('key') or path.stem,
                      'title': match.get('title') or '',
                      'opponent': (match.get('opponent') or '').strip(),
                      'date': date.get('text') or ''}
    return index


def _camp_stamp(text, year):
    """面板里的 '11-02 13:10' 只有月日时，补年份成 ISO 日期与排序键。"""
    match = re.match(r'\s*(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})', str(text or ''))
    if not match:
        return '', ''
    month, day, hour, minute = (int(part) for part in match.groups())
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return '', ''
    return f'{year:04d}-{month:02d}-{day:02d}', f'{year:04d}{month:02d}{day:02d}{hour:02d}{minute:02d}'


def _camp_records():
    """解析 data/camp_details 的十人面板，产出逐人逐局记录（60 秒缓存）。"""
    global _players_cache, _players_at
    if _players_cache is not None and monotonic() - _players_at <= 60:
        return _players_cache
    from camp_time import camp_times
    linked = _panel_games()
    accounts = camp_accounts()
    games, records = [], []
    for path in sorted((ROOT / 'data' / 'camp_details').glob('*.json')):
        try:
            body = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        data = body.get('data') or {}
        head = data.get('head') or {}
        camp_code = _camp_number(head.get('acntCamp'))
        if camp_code not in (1, 2):
            continue
        own_camp = int(camp_code)
        won = head.get('gameResult')
        result = 'win' if won is True else 'loss' if won is False else 'unknown'
        times = camp_times(body) or {}
        info = linked.get(path.stem) or {}
        day = times.get('date') or info.get('date') or ''
        year = int(day[:4]) if day[:4].isdigit() else date.today().year
        stamp_text = ((data.get('battle') or {}).get('startTime')
                      or (data.get('battle') or {}).get('dtEventTime') or '')
        stamp_day, stamp_key = _camp_stamp(stamp_text, year)
        if not day:
            day = stamp_day
        at = f'{day} {str(stamp_text).split(" ")[-1]}' if day and stamp_key else day
        duration = _camp_number((data.get('battle') or {}).get('usedTime')) or 0
        minutes = duration / 60 if duration else 0
        map_name = head.get('mapName') or ''
        opponent = info.get('opponent') or ('排位对手' if '排位' in map_name else '')
        game = {'id': path.stem, 'day': day, 'at': at, 'sort': stamp_key or path.stem,
                'title': info.get('title') or '',
                # 已挂到训练赛档案的面板带 matchKey，名单行可以直接跳到该局复盘。
                'match': info.get('key') or '',
                'opponent': opponent, 'map': map_name,
                'ownCamp': '蓝方' if own_camp == 1 else '红方',
                'result': result, 'duration': round(minutes, 1), 'own': [], 'enemy': []}
        for camp, key in ((1, 'blueRoles'), (2, 'redRoles')):
            roles = data.get(key) or []
            if len(roles) != 5:
                continue
            parsed = []
            for role in roles:
                stats = role.get('battleStats') or {}
                parsed.append({
                    'basic': role.get('basicInfo') or {},
                    'record': role.get('battleRecords') or {},
                    'stats': stats,
                    'gold': _camp_number(stats.get('money')) or 0,
                    'damage': _camp_number(stats.get('totalHurtCnt')) or 0,
                    'taken': _camp_number(stats.get('totalBehurtCnt')) or 0,
                })
            team_gold = sum(item['gold'] for item in parsed) or 1
            team_damage = sum(item['damage'] for item in parsed) or 1
            team_taken = sum(item['taken'] for item in parsed) or 1
            for item in parsed:
                stats = item['stats']
                nickname = _camp_name(item['basic'].get('roleName'))
                account_id = str(item['basic'].get('playerId') or '').strip()
                lane = _CAMP_LANES.get(_camp_number(item['record'].get('position')))
                hero = (item['record'].get('usedHero') or {}).get('heroName') or ''
                # 游戏 ID 已经被教练命名过，就直接用真实选手名；否则沿用营地昵称。
                mapped = accounts.get(account_id) if account_id else None
                name = (mapped.get('name') if mapped else '') or nickname
                if not name or not lane:
                    continue
                side = 'own' if camp == own_camp else 'enemy'
                kills = _camp_number(stats.get('killCnt')) or 0
                deaths = _camp_number(stats.get('deadCnt')) or 0
                assists = _camp_number(stats.get('assistCnt')) or 0
                participation = _camp_number(stats.get('joinGamePercent'))
                rating = _camp_number(stats.get('gradeGame'))
                row = {
                    'gameId': path.stem, 'day': day, 'at': at, 'sort': stamp_key or path.stem,
                    'opponent': opponent, 'map': map_name,
                    'side': side, 'camp': '蓝方' if camp == 1 else '红方',
                    'accountId': account_id, 'nickname': nickname,
                    'bound': bool(mapped), 'playerId': (mapped or {}).get('playerId') or '',
                    'teamId': (mapped or {}).get('teamId') or '',
                    'teamName': (mapped or {}).get('teamName') or '',
                    'result': result if side == 'own' else
                              ('loss' if result == 'win' else 'win' if result == 'loss' else 'unknown'),
                    'name': name, 'hero': hero, 'lane': lane,
                    'kills': kills, 'deaths': deaths, 'assists': assists,
                    'kda': round((kills + assists) / deaths, 2) if deaths else round(kills + assists, 2),
                    'gold': item['gold'], 'damage': item['damage'], 'taken': item['taken'],
                    'cs': _camp_number(stats.get('killSoldier')) or 0,
                    'gpm': round(item['gold'] / minutes) if minutes else None,
                    'dpm': round(item['damage'] / minutes) if minutes else None,
                    'dtpm': round(item['taken'] / minutes) if minutes else None,
                    'goldShare': round(item['gold'] / team_gold * 100, 1),
                    'damageShare': round(item['damage'] / team_damage * 100, 1),
                    'takenShare': round(item['taken'] / team_taken * 100, 1),
                    'participation': round(participation * 100, 1) if participation is not None and participation <= 1
                                     else (round(participation, 1) if participation is not None else None),
                    'rating': round(rating, 1) if rating is not None else None,
                    'mvp': bool(stats.get('mvp')),
                }
                records.append(row)
                game[side].append({'name': name, 'hero': hero, 'lane': lane, 'accountId': account_id,
                                   'nickname': nickname, 'bound': row['bound'],
                                   'kda': row['kda'], 'gold': item['gold']})
        if game['own'] and game['enemy']:
            games.append(game)
    _players_cache = {'games': games, 'records': records}
    _players_at = monotonic()
    return _players_cache


def _mean_of(values, digits=0):
    values = [value for value in values if isinstance(value, (int, float))]
    if not values:
        return None
    return round(sum(values) / len(values), digits)


def _percentile(values, value):
    if value is None or not values:
        return None
    below = sum(1 for item in values if item < value)
    equal = sum(1 for item in values if item == value)
    return round((below + equal * 0.5) / len(values) * 100, 1)


def _players_board():
    facts = _camp_records()
    games, records = facts['games'], facts['records']
    profile = {}
    try:
        with closing(sqlite3.connect(DB)) as connection:
            row = connection.execute('SELECT body FROM settings WHERE id=1').fetchone()
            profile = json.loads(row[0]) if row else {}
    except (sqlite3.Error, ValueError):
        profile = {}
    team_name = str(profile.get('teamName') or '').strip()
    home = own_team()
    accounts = camp_accounts()
    # 名单只认选手主数据（players 表）；还没迁移旧名单时才退回 settings。
    try:
        import workspace_store
        members = [dict(player, label=player.get('name') or '')
                   for player in workspace_store.Workspace(DB).list_players(team_id=home['id'])]
    except sqlite3.Error:
        members = []
    if not members:
        for member in (profile.get('members') or profile.get('roster') or []):
            if member.get('archived') or (member.get('team') and member.get('team') != team_name):
                continue
            item = dict(member)
            item['label'] = item.get('label') or item.get('name') or ''
            item['position'] = item.get('position') or ''
            members.append(item)
    aliases = {str(key): str(value) for key, value in (profile.get('aliases') or {}).items()}
    member_by_id = {member['id']: member for member in members}
    name_to_member = {}
    for member in members:
        for label in (member.get('label'), member.get('name')):
            if label:
                name_to_member[str(label)] = member
    for alias, member_id in aliases.items():
        if member_id in member_by_id:
            name_to_member[alias] = member_by_id[member_id]

    buckets = {}
    for row in records:
        bucket = buckets.setdefault(row['name'], {
            'name': row['name'], 'side': row['side'], 'games': 0, 'wins': 0, 'decided': 0,
            '_kda': [], '_gpm': [], '_dpm': [], '_dtpm': [], '_part': [], '_goldShare': [],
            '_damageShare': [], '_takenShare': [], '_rating': [], 'mvp': 0, '_cs': [],
            '_accounts': [], '_nicknames': Counter(),
            'lanes': Counter(), 'heroes': Counter(), 'heroWins': Counter(),
            'heroDecided': Counter(), 'heroRating': defaultdict(list), 'heroKda': defaultdict(list), 'recent': []})
        bucket['games'] += 1
        if row.get('accountId') and row['accountId'] not in bucket['_accounts']:
            bucket['_accounts'].append(row['accountId'])
        if row.get('nickname'):
            bucket['_nicknames'][row['nickname']] += 1
        if row['result'] in ('win', 'loss'):
            bucket['decided'] += 1
            if row['result'] == 'win':
                bucket['wins'] += 1
        bucket['_kda'].append(row['kda'])
        for key, field in (('_gpm', 'gpm'), ('_dpm', 'dpm'), ('_dtpm', 'dtpm'),
                           ('_part', 'participation'), ('_goldShare', 'goldShare'),
                           ('_damageShare', 'damageShare'), ('_takenShare', 'takenShare'),
                           ('_rating', 'rating'), ('_cs', 'cs')):
            if row.get(field) is not None:
                bucket[key].append(row[field])
        if row['mvp']:
            bucket['mvp'] += 1
        bucket['lanes'][row['lane']] += 1
        bucket['heroes'][row['hero']] += 1
        if row['result'] in ('win', 'loss'):
            bucket['heroDecided'][row['hero']] += 1
            if row['result'] == 'win':
                bucket['heroWins'][row['hero']] += 1
        if row.get('rating') is not None:
            bucket['heroRating'][row['hero']].append(row['rating'])
        bucket['heroKda'][row['hero']].append(row['kda'])
        bucket['recent'].append(row)

    def mean(values, digits=1):
        values = [value for value in values if value is not None]
        return round(sum(values) / len(values), digits) if values else None

    players = []
    def split_of(rows, key):
        """按对手 / 训练日切片的个人聚合；只统计该维度下的局，不跨切片平均。"""
        out = {}
        for row in rows:
            name = str(row.get(key) or '').strip()
            if not name:
                continue
            item = out.setdefault(name, {'games': 0, 'wins': 0, 'decided': 0, 'mvp': 0,
                                         '_kda': [], '_gpm': [], '_dpm': [], '_part': [],
                                         '_damageShare': [], '_rating': []})
            item['games'] += 1
            if row['result'] in ('win', 'loss'):
                item['decided'] += 1
                if row['result'] == 'win':
                    item['wins'] += 1
            if row.get('mvp'):
                item['mvp'] += 1
            for bucket_key, field in (('_kda', 'kda'), ('_gpm', 'gpm'), ('_dpm', 'dpm'),
                                      ('_part', 'participation'), ('_damageShare', 'damageShare'),
                                      ('_rating', 'rating')):
                if row.get(field) is not None:
                    item[bucket_key].append(row[field])
        return {name: {
            'games': item['games'], 'wins': item['wins'], 'decided': item['decided'],
            'winRate': round(item['wins'] / item['decided'] * 100, 1) if item['decided'] else None,
            'kda': mean(item['_kda'], 2), 'gpm': mean(item['_gpm'], 0), 'dpm': mean(item['_dpm'], 0),
            'participation': mean(item['_part'], 1), 'damageShare': mean(item['_damageShare'], 1),
            'rating': mean(item['_rating'], 1), 'mvp': item['mvp'],
        } for name, item in out.items()}

    for bucket in buckets.values():
        lane = bucket['lanes'].most_common(1)[0][0] if bucket['lanes'] else ''
        mapped = next((accounts[account] for account in bucket['_accounts'] if account in accounts), None)
        member = mapped or name_to_member.get(bucket['name'])
        member_id = (member or {}).get('id') or (member or {}).get('playerId') or None
        players.append({
            'name': bucket['name'], 'lane': lane,
            'laneMix': [{'lane': name, 'games': n} for name, n in bucket['lanes'].most_common()],
            'side': bucket['side'], 'bound': bool(member), 'memberId': member_id,
            'accountIds': bucket['_accounts'],
            'nicknames': [nick for nick, _ in bucket['_nicknames'].most_common(3)],
            'teamName': (mapped or {}).get('teamName') or '',
            'games': bucket['games'], 'wins': bucket['wins'], 'decided': bucket['decided'],
            'winRate': round(bucket['wins'] / bucket['decided'] * 100, 1) if bucket['decided'] else None,
            'kda': mean(bucket['_kda'], 2), 'gpm': mean(bucket['_gpm'], 0), 'dpm': mean(bucket['_dpm'], 0),
            'dtpm': mean(bucket['_dtpm'], 0), 'participation': mean(bucket['_part'], 1),
            'goldShare': mean(bucket['_goldShare'], 1), 'damageShare': mean(bucket['_damageShare'], 1),
            'takenShare': mean(bucket['_takenShare'], 1), 'cs': mean(bucket['_cs'], 0),
            'rating': mean(bucket['_rating'], 1), 'mvp': bucket['mvp'],
            'splits': {'opponent': split_of(bucket['recent'], 'opponent'),
                       'day': split_of(bucket['recent'], 'day')},
            'heroes': [{'hero': hero, 'games': n,
                        'wins': bucket['heroWins'].get(hero, 0),
                        'decided': bucket['heroDecided'].get(hero, 0),
                        'rating': mean(bucket['heroRating'].get(hero), 1),
                        'kda': mean(bucket['heroKda'].get(hero), 2)}
                       for hero, n in bucket['heroes'].most_common(6)],
            '_recent': sorted(bucket['recent'], key=lambda item: (item['sort'], item['gameId'])),
            '_ratings': [row['rating'] for row in sorted(bucket['recent'], key=lambda item: (item['sort'], item['gameId']))
                         if row.get('rating') is not None],
        })

    # 同位置分位：只和同位置选手比；表现分 = 分位均值，50 即分路平均。
    lanes = {}
    for player in players:
        lanes.setdefault(player['lane'], []).append(player)
    keys = ['kda', 'gpm', 'dpm', 'participation', 'damageShare', 'takenShare', 'goldShare']
    for lane, group in lanes.items():
        for key in keys:
            values = sorted(player[key] for player in group if player.get(key) is not None)
            for player in group:
                player.setdefault('percent', {})[key] = _percentile(values, player.get(key))
    for player in players:
        percent = player.get('percent') or {}
        core = [percent.get(key) for key in ('kda', 'gpm', 'dpm', 'participation') if percent.get(key) is not None]
        player['score'] = round(sum(core) / len(core), 1) if core else None
        ratings = player.pop('_ratings')
        if len(ratings) >= 6:
            prior = sum(ratings[-6:-3]) / 3
            recent = sum(ratings[-3:]) / 3
            delta = recent - prior
            player['form'] = {'available': True, 'prior': round(prior, 1), 'recent': round(recent, 1),
                              'delta': round(delta, 1), 'samples': len(ratings),
                              'tone': 'up' if delta >= 0.5 else 'down' if delta <= -0.5 else 'flat'}
        else:
            player['form'] = {'available': False, 'samples': len(ratings)}
        recent = player.pop('_recent')[-12:]
        player['recent'] = [{key: row.get(key) for key in
                             ('gameId', 'day', 'at', 'opponent', 'hero', 'lane', 'result', 'kda', 'gpm', 'dpm', 'rating', 'mvp')}
                            for row in reversed(recent)]

    # 搭档：同局同阵营双人共现，按有胜负的局算组合胜率。
    pair_map = {}
    for game in games:
        own = [item['name'] for item in game['own']]
        for i in range(len(own)):
            for j in range(i + 1, len(own)):
                key = tuple(sorted((own[i], own[j])))
                item = pair_map.setdefault(key, {'games': 0, 'wins': 0, 'decided': 0})
                item['games'] += 1
                if game['result'] in ('win', 'loss'):
                    item['decided'] += 1
                    if game['result'] == 'win':
                        item['wins'] += 1
    pairs = [{'a': key[0], 'b': key[1], 'games': item['games'], 'wins': item['wins'],
              'winRate': round(item['wins'] / item['decided'] * 100, 1) if item['decided'] else None}
             for key, item in pair_map.items() if item['games'] >= 2]
    pairs.sort(key=lambda item: (-item['games'], -item['wins']))

    # 搭档矩阵用：所有出现过的双人组合（含只同场 1 局的），前端只取前若干行。
    duos = [{'a': key[0], 'b': key[1], 'games': item['games'], 'wins': item['wins'],
             'winRate': round(item['wins'] / item['decided'] * 100, 1) if item['decided'] else None}
            for key, item in pair_map.items()]
    duos.sort(key=lambda item: (-item['games'], -item['wins']))
    # 稳定五人组：同阵营五人完全相同的组合，按出现次数排。
    lineup_map = {}
    for game in games:
        names = tuple(sorted(item['name'] for item in game['own']))
        if len(names) != 5:
            continue
        item = lineup_map.setdefault(names, {'games': 0, 'wins': 0})
        item['games'] += 1
        if game['result'] == 'win':
            item['wins'] += 1
    lineups = [{'names': list(names), 'games': item['games'], 'wins': item['wins']}
               for names, item in lineup_map.items()]
    lineups.sort(key=lambda item: (-item['games'], -item['wins']))

    # 位置对照：本队 / 对手在同一位置的分均与参团。
    lane_rows = []
    for lane in _CAMP_LANE_ORDER:
        rows = [row for row in records if row['lane'] == lane]
        item = {'lane': lane}
        for side in ('own', 'enemy'):
            cells = [row for row in rows if row['side'] == side]
            decided = [row for row in cells if row['result'] in ('win', 'loss')]
            wins = sum(1 for row in decided if row['result'] == 'win')
            item[side] = {
                'games': len(cells), 'winRate': round(wins / len(decided) * 100, 1) if decided else None,
                'gpm': _mean_of([row.get('gpm') for row in cells]),
                'dpm': _mean_of([row.get('dpm') for row in cells]),
                'dtpm': _mean_of([row.get('dtpm') for row in cells]),
                'participation': _mean_of([row.get('participation') for row in cells], 1),
                'players': len({row['name'] for row in cells}),
            }
        lane_rows.append(item)

    # 位置名册：有认领就用认领，否则给该位置出场最多的人（认领页的第一候选）。
    roster = []
    for lane in _CAMP_LANE_ORDER:
        claimed = next((member for member in members if (member.get('position') or '') == lane), None)
        candidate = next((player for player in sorted(players, key=lambda item: -item['games'])
                          if player['lane'] == lane and player['side'] == 'own'), None)
        roster.append({'lane': lane, 'member': (claimed.get('label') or claimed.get('name')) if claimed else '',
                       'memberId': claimed['id'] if claimed else None,
                       'player': candidate['name'] if candidate else '',
                       'games': candidate['games'] if candidate else 0,
                       'winRate': candidate['winRate'] if candidate else None,
                       'bound': bool(claimed)})

    own = [player for player in players if player['side'] == 'own']
    unclaimed = [player for player in own if not player['bound'] and player['games'] >= 2]
    unclaimed.sort(key=lambda item: -item['games'])
    entries = [{'label': player['name'], 'matches': player['games'], 'lane': player['lane'],
                'heroes': [item['hero'] for item in player['heroes'][:3]],
                'winRate': player['winRate'], 'bound': player['bound'],
                'memberId': player['memberId'], 'teamName': player['teamName'],
                'accountIds': player['accountIds'], 'nicknames': player['nicknames']}
               for player in own]
    entries.sort(key=lambda item: (item['bound'], -item['matches'], item['label']))
    decided_games = [game for game in games if game['result'] in ('win', 'loss')]
    summary = {
        'games': len(games), 'decided': len(decided_games),
        'wins': sum(1 for game in decided_games if game['result'] == 'win'),
        'winRate': round(sum(1 for game in decided_games if game['result'] == 'win') / len(decided_games) * 100, 1)
                   if decided_games else None,
        'players': len(players), 'ownPlayers': len(own), 'bound': sum(1 for player in own if player['bound']),
        'unclaimed': sum(1 for player in own if not player['bound']),
        'formReady': sum(1 for player in players if player['form']['available']),
        'rising': sum(1 for player in players if player['form'].get('tone') == 'up'),
        'falling': sum(1 for player in players if player['form'].get('tone') == 'down'),
        'pairs': len(pairs), 'days': len({game['day'] for game in games if game['day']}),
        'positions': len({player['lane'] for player in players if player['lane']}),
        'teamName': team_name,
    }
    board = {'games': sorted(games, key=lambda game: (game['sort'], game['id']), reverse=True),
             'players': sorted(players, key=lambda item: (-item['games'], -item['wins'], item['name'])),
             'lanes': lane_rows, 'pairs': pairs[:24], 'roster': roster,
             'duos': duos[:40], 'lineups': lineups[:12],
             'opponents': [{'name': name, 'games': n}
                           for name, n in Counter(row['opponent'] for row in records if row.get('opponent')).most_common(20)],
             'days': sorted({row['day'] for row in records if row.get('day')}, reverse=True),
             'unclaimed': [{'name': player['name'], 'games': player['games'], 'lane': player['lane'],
                            'winRate': player['winRate'], 'heroes': [item['hero'] for item in player['heroes'][:3]],
                            'teammates': []} for player in unclaimed[:24]],
             'identity': {'entries': entries, 'members': members, 'aliases': aliases, 'teamName': team_name},
             'summary': summary}
    # 认领候选的常见队友：同一批对局里同阵营出场最多的人。
    by_name = {player['name']: player for player in players}
    for item in board['unclaimed']:
        mates = Counter()
        for game in games:
            names = [row['name'] for row in game['own']]
            if item['name'] in names:
                mates.update(name for name in names if name != item['name'])
        item['teammates'] = [{'name': name, 'games': n} for name, n in mates.most_common(3)]
    del by_name
    return board


@router.get('/api/v3/players-board')
def players_board():
    """选手板块四页共用聚合：逐人逐局记录、位置对照、搭档、认领状态。"""
    return _players_board()


@router.get('/api/v3/vocab')
def vocab_board():
    """赛训词表：版本 / 规则 / 赛制 / 训练组。

    表单选项与预填确认共用这一份口径；历史记录里已经出现的值也会并进来，
    避免词表升级后老值从下拉里消失、改一次就被悄悄覆盖。
    """
    base = vocab_store.load(DATA_DIR)
    sessions, versions = list(base.get('sessions') or []), list(base.get('versions') or [])
    try:
        with closing(sqlite3.connect(DB)) as connection:
            sessions += [row[0] for row in connection.execute(
                'SELECT DISTINCT session FROM schedules WHERE session IS NOT NULL AND session <> ""')]
            for row in connection.execute(
                    'SELECT DISTINCT version FROM schedules WHERE version IS NOT NULL AND version <> ""'):
                versions.append(row[0])
            for table in ('matches',):
                try:
                    sessions += [row[0] for row in connection.execute(
                        f'SELECT DISTINCT session FROM {table} WHERE session IS NOT NULL AND session <> ""')]
                    versions += [row[0] for row in connection.execute(
                        f'SELECT DISTINCT version FROM {table} WHERE version IS NOT NULL AND version <> ""')]
                except sqlite3.Error:
                    continue
    except sqlite3.Error:
        pass
    return {
        'versions': vocab_store.sort_values('versions', versions),
        'rules': list(base.get('rules') or []),
        'formats': list(base.get('formats') or []),
        'sessions': vocab_store.sort_values('sessions', sessions),
    }


_hero_facts_cache = None
_hero_facts_at = 0.0


def _hero_facts():
    """营地面板逐人记录（含出装）复用 60 秒，避免详情页每次全量解析。"""
    global _hero_facts_cache, _hero_facts_at
    if _hero_facts_cache is None or monotonic() - _hero_facts_at > 60:
        import depth_api
        _hero_facts_cache = depth_api.build_facts(ROOT)
        _hero_facts_at = monotonic()
    return _hero_facts_cache


@router.get('/api/v3/hero-detail/{hero}')
def hero_detail(hero: str, repo=Depends(repository)):
    """英雄详情页的聚合数据：选手使用榜 / 战队使用 / 本队均值对照 / 成长曲线 / 选手出装。

    全部从同一份营地逐行面板算出，避免前端把多个来源的口径混在一起。
    """
    base = {'sources': list(DEFAULT_SOURCES)}
    hero_rows, _ = repo._selected_rows({**base, 'hero': hero})
    all_rows, _ = repo._selected_rows(base)
    hero_rows = [row for row in hero_rows if row.get('isOwn')]
    all_rows = [row for row in all_rows if row.get('isOwn')]

    def mean(rows, key):
        values = [row[key] for row in rows if isinstance(row.get(key), (int, float))]
        return round(sum(values) / len(values), 2) if values else None

    def group(rows, field):
        buckets = {}
        for row in rows:
            name = row.get(field) or '未标注'
            item = buckets.setdefault(name, {'name': name, 'games': 0, 'wins': 0,
                                            'decided': 0, '_kda': [], '_gpm': []})
            item['games'] += 1
            if row.get('result') in ('win', 'loss'):
                item['decided'] += 1
                if row['result'] == 'win':
                    item['wins'] += 1
            for key, bucket in (('kda', '_kda'), ('gpm', '_gpm')):
                if isinstance(row.get(key), (int, float)):
                    item[bucket].append(row[key])
        result = [{
            'name': item['name'], 'games': item['games'], 'wins': item['wins'],
            'decided': item['decided'],
            'winRate': round(item['wins'] / item['decided'] * 100, 1) if item['decided'] else None,
            'kda': round(sum(item['_kda']) / len(item['_kda']), 2) if item['_kda'] else None,
            'gpm': round(sum(item['_gpm']) / len(item['_gpm'])) if item['_gpm'] else None,
        } for item in buckets.values()]
        return sorted(result, key=lambda x: -x['games'])[:12]

    league = {key: {'hero': mean(hero_rows, key), 'all': mean(all_rows, key)}
              for key in ('kda', 'gpm', 'dpm', 'participation', 'gold', 'cs')}

    match_keys = {row.get('matchKey') for row in hero_rows if row.get('matchKey')}
    curves = [match for match in (repo.process(base).get('matches') or [])
              if match.get('key') in match_keys]
    buckets = defaultdict(list)
    for match in curves:
        for point in match.get('points') or []:
            if isinstance(point, (list, tuple)) and len(point) >= 2 and isinstance(point[1], (int, float)):
                buckets[int(point[0])].append(point[1])
    growth = [{'t': second, 'value': round(sum(values) / len(values))}
              for second, values in sorted(buckets.items()) if values]

    facts = _hero_facts()
    match_result = {str(match.get('id')): match.get('result')
                    for match in (facts.get('matches') or [])}
    builders = {}
    for row in (facts.get('players') or []):
        if row.get('hero') != hero:
            continue
        name = row.get('player') or '未标注'
        item = builders.setdefault(name, {'name': name, 'games': 0, 'wins': 0,
                                         'decided': 0, '_gold': [], '_kda': [],
                                         'equips': Counter(), 'first': Counter(),
                                         'summoner': Counter()})
        item['games'] += 1
        result = match_result.get(str(row.get('match')))
        if result is not None:
            item['decided'] += 1
            if result:
                item['wins'] += 1
        for key, bucket in (('gold', '_gold'), ('kda', '_kda')):
            if isinstance(row.get(key), (int, float)):
                item[bucket].append(row[key])
        equips = [value for value in (row.get('equips') or []) if value]
        for equip in equips:
            item['equips'][equip] += 1
        if equips:
            item['first'][equips[0]] += 1
        if row.get('summoner'):
            item['summoner'][row['summoner']] += 1

    def avg(values, digits=1):
        return round(sum(values) / len(values), digits) if values else None

    def chips(counter, limit):
        return [{'name': name, 'count': count} for name, count in counter.most_common(limit)]

    player_builds = [{
        'name': item['name'], 'games': item['games'], 'wins': item['wins'],
        'decided': item['decided'],
        'winRate': round(item['wins'] / item['decided'] * 100, 1) if item['decided'] else None,
        'gold': avg(item['_gold'], 0), 'kda': avg(item['_kda'], 2),
        'equips': chips(item['equips'], 6), 'first': chips(item['first'], 2),
        'summoner': chips(item['summoner'], 2),
    } for item in builders.values()]
    player_builds.sort(key=lambda x: -x['games'])

    return {'hero': hero, 'games': len(hero_rows), 'players': group(hero_rows, 'label'),
            'teams': group(hero_rows, 'opponent'), 'league': league,
            'growth': growth, 'curveGames': len(curves),
            'playerBuilds': player_builds[:8]}


# ── 数据迁移：把本机爬到的对局数据打包带走 ────────────────────────────
# 王者营地只留约一个月滚动窗口，滑出窗口的数据只存在于本机 data/ 里，
# 换机器/备份只能靠这个包，不能指望重新爬。
@router.get('/api/data/transfer/info')
def transfer_info():
    import data_transfer
    data_dir = MATCHES.parent
    counts = data_transfer._db_counts(DB)
    total = 0
    for name in data_transfer.BASE_DIRS:
        folder = data_dir / name
        if folder.is_dir():
            total += sum(item.stat().st_size for item in folder.rglob('*') if item.is_file())
    return {'ok': True, 'dataDir': str(data_dir), 'counts': counts,
            'estimatedBytes': total, 'dirs': list(data_transfer.BASE_DIRS)}


@router.post('/api/data/transfer/export')
async def transfer_export(request: Request):
    import data_transfer
    body = await read_json(request)
    body = body if isinstance(body, dict) else {}
    data_dir = MATCHES.parent
    out_dir = data_dir / 'export'
    stamp = time.strftime('%Y%m%d-%H%M')
    out = out_dir / f'赛训数据-{stamp}.zip'
    try:
        import version as _version
        _app_version = str(getattr(_version, 'VERSION', '') or '')
    except Exception:  # noqa: BLE001
        _app_version = ''
    try:
        manifest = data_transfer.export_bundle(
            data_dir, out,
            with_screenshots=bool(body.get('withScreenshots')),
            with_replays=bool(body.get('withReplays')),
            app_version=_app_version)
    except Exception as error:  # noqa: BLE001
        raise HTTPException(500, f'导出失败：{error}')
    return {'ok': True, 'path': str(out), 'name': out.name,
            'size': manifest.get('bundleSize') or out.stat().st_size,
            'counts': manifest.get('counts') or {}, 'dataDir': str(data_dir)}


app.include_router(router)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8771, help='V3 dev-only port (default: 8771)')
    uvicorn.run(app, host='127.0.0.1', port=parser.parse_args().port)

