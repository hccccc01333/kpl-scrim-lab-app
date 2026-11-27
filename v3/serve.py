"""V3 路由模块：读取赛训数据、提供分析接口。

路由由 server.py 统一挂进同一个 app —— 采集接口、分析接口、前端静态资源
只有这一套。`/api/health`、`/api/channels`、`/api/camp/*` 与 `/api/v3/*`
在同一张路由表里，所以不会再出现「某个端口只有界面、没有采集接口」的旁支。

要换端口仍然可以 `python v3/serve.py --port 8811`：它只把端口交给 server.py，
起的是同一个 app，而不是另搭一个缺采集接口的服务。
"""

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
from datetime import date, datetime as _datetime, timedelta, timezone
from pathlib import Path
from threading import Lock, Thread
from time import monotonic

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response

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
from series_api import create_series_router
import deep_analysis
import hero_archetypes
import hero_capabilities
import identity_service
try:
    import peak_crawl
except (ImportError, OSError, ValueError):
    # 发布包必须带 scripts/build_bp_facts.py，否则 peak_crawl 整段导不进来：
    # 表现是「英雄榜没 KPL / 国服战力 / 巅峰千强数据，也不会自动爬」。
    # 真出意外时只关掉抓取，别让根路径连带 404。
    peak_crawl = None
import player_profile
import vocab as vocab_store


def data_path(variable, default):
    override = os.environ.get(variable)
    if override:
        return Path(override)
    return data_root(ROOT) / default


DB = data_path('TRAINING_DB', 'training.sqlite3')
# 词表与写入归一化共用数据目录；版本 / 规则 / 赛制 / 训练组都落在这里。
DATA_DIR = DB.parent
# 版本记录（版本名 + 起止日期），教练自己填，全局一份。
VERSIONS_SCHEMA = 'version-records-v1'
MATCHES = data_path('ANALYSIS_MATCHES', 'matches')
IMPORTS = data_path('ANALYSIS_IMPORTS', 'imports')
OFFICIAL = data_path('ANALYSIS_OFFICIAL', 'official_replays')
BUILDS = data_path('ANALYSIS_BUILDS', 'builds')
DEMO_ROOT = Path(os.environ['TRAINING_DEMO_ROOT']) if os.environ.get('TRAINING_DEMO_ROOT') else None
POSITION_STEP = 2  # 位置降采样步长（秒），693 秒的局约 347 点/人
# 单局标签：一局最多几个、单个标签最长几个字。前端只做提示，落地以这里为准。
TAG_LIMIT = 12
TAG_MAX_LEN = 16
IS_DEMO = DEMO_ROOT is not None
panorama = PanoramaRepository(MATCHES, OFFICIAL, BUILDS, ROOT)
router = APIRouter()

# 重量级报告落盘：BP 概览首次全量聚合约 9 秒、BP 工作台约 2.5 秒、选手看板约 1.6 秒，
# 但它们只取决于数据文件与筛选参数。把「最近一次算过的 key + 结果」写到 data/.cache，
# 进程重启后第一次打开同一个视图直接读盘；key 不匹配（数据变了或换了筛选）就照常重算。
_CACHE_DIR = DATA_DIR / '.cache'
_REPORT_DISK_LOCK = Lock()


def _cache_key_id(key):
    return json.dumps(key, ensure_ascii=False, separators=(',', ':'), default=str)


def _report_disk_read(path, key_id, name):
    try:
        doc = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or doc.get('key') != key_id:
        return None
    report = doc.get(name)
    return report if isinstance(report, (dict, list, str)) else None


def _report_disk_write(path, key_id, name, report):
    with _REPORT_DISK_LOCK:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix('.tmp')
            tmp.write_text(json.dumps({'key': key_id, name: report},
                                      ensure_ascii=False, separators=(',', ':')),
                           encoding='utf-8')
            os.replace(tmp, path)
        except (OSError, TypeError, ValueError):
            pass


def _camp_seq(detail):
    """从单局详情取营地 gameSeq；只认纯数字，避免拼出目录穿越路径。"""
    if not isinstance(detail, dict):
        return ''
    camp = detail.get('campBp') if isinstance(detail.get('campBp'), dict) else {}
    seq = str(camp.get('gameSeq') or '')
    if not seq:
        official = detail.get('officialReplay') if isinstance(detail.get('officialReplay'), dict) else {}
        oid = str(official.get('id') or '')
        if oid.startswith('camp-'):
            seq = oid[len('camp-'):]
    return seq if re.fullmatch(r'\d+', seq) else ''


def _camp_detail_payload(seq):
    if not re.fullmatch(r'\d+', str(seq or '')):
        return None
    path = MATCHES.parent / 'camp_details' / f'{seq}.json'
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def camp_draft_events(detail):
    """单局复盘读已核验的逐手事件（camp_details/<seq>.json → data.draftEvents）。

    营地名单本身不携带手序；只有沙盘补录并校验过的事件才写回这里。
    """
    seq = _camp_seq(detail)
    payload = _camp_detail_payload(seq) if seq else None
    if not payload:
        return []
    container = payload.get('data') if isinstance(payload.get('data'), dict) else {}
    events = (container.get('draftEvents') or container.get('bpSequence')
              or payload.get('draftEvents') or [])
    return events if isinstance(events, list) else []


def camp_bp_order(detail):
    """单局复盘读页面手工录入的每侧 Ban/Pick 顺序（受排位规则允许重复 Ban）。"""
    seq = _camp_seq(detail)
    payload = _camp_detail_payload(seq) if seq else None
    if not payload:
        return None
    container = payload.get('data') if isinstance(payload.get('data'), dict) else {}
    order = container.get('bpOrder')
    return order if isinstance(order, dict) else None


async def read_json(request: Request):
    """把非法 JSON 统一变成 400，避免写接口抛 500。"""
    try:
        return await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(400, '请求体不是有效 JSON。') from None


# 这里只导出路由，不再自建 app。
#
# 2026-11-16：历史上 V3 有一套自己的 FastAPI app（只挂分析路由、不挂采集接口），
# `python v3/serve.py` 起出来的就是那半套服务 —— 打开采集页永远 404，
# 页面只能显示「营地数据暂时读不到」。现在分析路由由 server.py 的 _mount_v3()
# 挂进同一个 app，采集 / 分析 / 前端静态资源只有这一套；本文件只剩下这张路由表。



def _series_query(values=None):
    """系列赛侧的统一取数口径：全部合格对局，不受跨局页 200 局窗口影响。"""
    query = {'sources': list(DEFAULT_SOURCES), 'from': None, 'to': None, 'hero': None,
             'opponent': None, 'excludeSeeds': False, 'ownOnly': True, 'competition': None}
    if values:
        for key in ('sources', 'from', 'to', 'hero', 'opponent', 'excludeSeeds',
                    'ownOnly', 'competition'):
            if values.get(key) is not None:
                query[key] = values[key]
    return query


def _series_vectors(repo, values=None):
    """系列赛侧全量向量（V2.0）：不依赖跨局页的 200 局明细窗口，编组候选
    先由全部合格对局确定，选定系列赛再按需取明细。"""
    items = repo.matches(_series_query(values))['matches']
    return [v for v in (_cross_vector(repo, item, 8) for item in items) if v]


def _series_vectors_for(repo, values=None, keys=None):
    """只建指定对局的完整向量。

    系列赛列表 / 汇总只用到已入组那几十局，以前却为此重建全量 396 局向量，
    一次 GET 要 3–8 秒。按 key 过滤后只付这几局的钱。
    """
    wanted = {str(k) for k in (keys or []) if k}
    if not wanted:
        return []
    items = repo.matches(_series_query(values))['matches']
    return [v for item in items if str(item.get('key') or '') in wanted
            for v in [_cross_vector(repo, item, 8)] if v]


_SERIES_BUILDER_CACHE = {}
_MATCH_STAMP_CACHE = {'at': 0.0, 'stamp': None}
_MATCH_STAMP_TTL = 2.0


def _matches_stamp():
    """只算对局包目录的廉价指纹。

    轻量向量的字段全部来自对局包；系列赛写库只改关系表，不该让这份缓存
    失效（否则每次确认编组后的第一次写操作又要重建快照）。
    396 个文件 stat 一次约 30ms，2 秒内复用；新对局最多晚 2 秒出现。
    """
    now = monotonic()
    cached = _MATCH_STAMP_CACHE['stamp']
    if cached is not None and now - _MATCH_STAMP_CACHE['at'] < _MATCH_STAMP_TTL:
        return cached
    try:
        count, latest = 0, 0.0
        for path in MATCHES.glob('*.json'):
            try:
                latest = max(latest, path.stat().st_mtime)
            except OSError:
                continue
            count += 1
        stamp = (count, round(latest, 3))
    except OSError:
        stamp = (0, 0.0)
    _MATCH_STAMP_CACHE.update(at=now, stamp=stamp)
    return stamp


def _series_match_stamp():
    """轻量向量真正依赖的指纹：对局包 + 队名/对局元数据变更。

    `change_log` 里对局只记 series_id / game_no 的写入，系列赛关系不该让
    轻量缓存失效；队名合并、改名、选手/赛程变更必须立即反映到编组行上。
    """
    try:
        with sqlite3.connect(f'file:{DB.as_posix()}?mode=ro', uri=True) as connection:
            count, latest = connection.execute(
                "SELECT COUNT(*), COALESCE(MAX(created_at), 0) FROM change_log "
                "WHERE entity_type IN ('team','player','schedule') "
                "OR (entity_type='match' AND field NOT IN ('series_id','game_no'))"
            ).fetchone()
    except sqlite3.Error:
        count, latest = 0, 0
    return (_matches_stamp(), count, latest)


def _cross_data_stamp():
    """跨局向量的失效指纹：对局包 + 队名/对局元数据 + BP 覆盖。

    系列赛关系（series / match.series_id / match.game_no）不算：跨局页的
    赛制/局序是在向量返回前动态贴上的，不该因此重建几秒的全量向量。
    """
    try:
        with sqlite3.connect(f'file:{DB.as_posix()}?mode=ro', uri=True) as connection:
            log_count, log_latest = connection.execute(
                "SELECT COUNT(*), COALESCE(MAX(created_at), 0) FROM change_log "
                "WHERE entity_type IN ('team','player','schedule','bp') "
                "OR (entity_type='match' AND field NOT IN ('series_id','game_no'))"
            ).fetchone()
            try:
                bp_count, bp_rev = connection.execute(
                    "SELECT COUNT(*), COALESCE(MAX(revision), 0) FROM bp_overrides").fetchone()
            except sqlite3.Error:
                bp_count, bp_rev = 0, 0
    except sqlite3.Error:
        log_count = log_latest = bp_count = bp_rev = 0
    return (_matches_stamp(), log_count, log_latest, bp_count, bp_rev)


_SERIES_VECTOR_SCHEMA = 3
_SERIES_VECTOR_DISK = DATA_DIR / '.cache' / 'series-vectors.json'
_SERIES_VECTOR_DISK_STATE = {'loaded': False, 'key': None, 'vectors': None}


def _series_vector_cache_id(cache_key):
    return json.dumps(cache_key, ensure_ascii=False, separators=(',', ':'))


def _series_default_query(query):
    return not (query.get('from') or query.get('to')
                or query.get('hero') or query.get('opponent'))


def _series_vectors_disk_read(cache_key):
    state = _SERIES_VECTOR_DISK_STATE
    if not state['loaded']:
        state['loaded'] = True
        try:
            doc = json.loads(_SERIES_VECTOR_DISK.read_text(encoding='utf-8'))
            if isinstance(doc, dict) and isinstance(doc.get('vectors'), list):
                state['key'] = doc.get('key')
                state['vectors'] = doc['vectors']
        except (OSError, ValueError):
            pass
    if state['vectors'] is not None and state['key'] == _series_vector_cache_id(cache_key):
        return state['vectors']
    return None


def _series_vectors_disk_write(cache_key, vectors, query):
    if not _series_default_query(query):
        return
    try:
        _SERIES_VECTOR_DISK.parent.mkdir(parents=True, exist_ok=True)
        tmp = _SERIES_VECTOR_DISK.with_suffix('.tmp')
        key = _series_vector_cache_id(cache_key)
        tmp.write_text(json.dumps({'key': key, 'vectors': vectors},
                                  ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        os.replace(tmp, _SERIES_VECTOR_DISK)
        _SERIES_VECTOR_DISK_STATE.update(loaded=True, key=key, vectors=vectors)
    except (OSError, TypeError, ValueError):
        pass


def _series_builder_vectors(repo=None, values=None):
    """编组页专用的轻量向量：时间轴 / 对手 / 胜负 / 比分 / 双方阵容。

    编组页一行一局只看这些字段，不需要经济曲线、回放事件和十人明细。
    轻量版约 0.1 秒（完整 _cross_vector 全量要 3–4 秒），并按对局包指纹缓存；
    缓存命中时连仓库快照都不需要，写操作因此不再等 15 秒快照重建。
    默认查询还会落到 `.cache/series-vectors.json`，服务重启后首次进页也直接读盘。
    """
    query = _series_query(values)
    cache_key = (_SERIES_VECTOR_SCHEMA, _series_match_stamp(),
                 tuple(query['sources']), query['from'], query['to'],
                 bool(query['excludeSeeds']), bool(query['ownOnly']),
                 query.get('competition'))
    cached = _SERIES_BUILDER_CACHE.get(cache_key)
    if cached is not None:
        return cached
    disk = _series_vectors_disk_read(cache_key)
    if disk is not None:
        _SERIES_BUILDER_CACHE[cache_key] = disk
        return disk
    if repo is None:
        repo = AnalysisRepository(DB, MATCHES, IMPORTS, OFFICIAL)
    items = repo.matches(query)['matches']
    out = []
    for item in items:
        key = item.get('key')
        if not key:
            continue
        own = item.get('ownCamp') or 'blue'
        foe = 'red' if own == 'blue' else 'blue'
        scores = item.get('scores') or {}
        lineup = item.get('lineup') or []
        start = str(item.get('startTime') or '')
        clock = next((token for token in start.replace('T', ' ').split(' ') if ':' in token), '')
        out.append({
            'key': str(key),
            'date': item.get('date') or '',
            'clock': clock,
            'order': start,
            'session': item.get('session') or '',
            'version': item.get('version') or '',
            'opponent': item.get('opponent') or '',
            'opponentTeamId': item.get('opponentTeamId') or '',
            'result': item.get('result') or '',
            'duration': item.get('duration') or 0,
            'finalDiff': item.get('goldDiff'),
            'killsOwn': scores.get(own),
            'killsFoe': scores.get(foe),
            'heroes': list(item.get('heroes') or [])[:5],
            'heroesFoe': [x.get('enemy') for x in lineup if x.get('enemy')][:5],
            # 编组页不显示 10 分钟差；保留字段让 _enrich / 前端共用同一套读法。
            'at10': None,
            'hasReplay': bool(item.get('hasPov') or item.get('hasTimeline')),
            'isSeed': bool(item.get('isSeed')),
            'source': item.get('source') or '',
        })
    if len(_SERIES_BUILDER_CACHE) > 3:
        _SERIES_BUILDER_CACHE.clear()
    _SERIES_BUILDER_CACHE[cache_key] = out
    _series_vectors_disk_write(cache_key, out, query)
    return out


def _series_detail(repo, key):
    return repo.match_detail(key)


# 大场挖掘层的全量语料：单局完整向量（经济曲线 / 团战 / 资源 / 十人面板）。
# 冷启动要把 396 局回放聚合一遍（约 3–6 秒），之后按对局包指纹命中；
# 只在单场大场下钻时取，列表 / 汇总不付这份钱。
_SERIES_CORPUS_CACHE = {}


def _series_corpus(repo=None, competition=None):
    """大场挖掘的语料：repo 已按赛事收窄，缓存键必须带赛事——
    否则先请求 A 再请求 B 会命中 A 的缓存，跨赛事串味（P0-2）。"""
    stamp = (_series_match_stamp(), competition or '')
    cached = _SERIES_CORPUS_CACHE.get(stamp)
    if cached:
        return cached
    if repo is None:
        repo = AnalysisRepository(DB, MATCHES, IMPORTS, OFFICIAL)
    vectors = _series_vectors(repo)
    if len(_SERIES_CORPUS_CACHE) > 4:
        _SERIES_CORPUS_CACHE.clear()
    _SERIES_CORPUS_CACHE[stamp] = vectors
    return vectors


# 系列赛编组与分析路由（V2.0）：独立关系实体，不走 studio 白名单。
# 生产入口 server.py 只挂本模块的 router（见 _mount_v3），独立运行走 app；
# 同一组路由在两处都注册，测试用隔离 FastAPI 时直接用工厂。
def _scan_dataset_stamp():
    """扫一遍对局包目录 + 数据库 mtime。"""
    try:
        count, latest = 0, 0.0
        for path in MATCHES.glob('*.json'):
            try:
                latest = max(latest, path.stat().st_mtime)
            except OSError:
                continue
            count += 1
        matches = (count, round(latest, 3))
    except OSError:
        matches = (0, 0.0)
    try:
        db = round(DB.stat().st_mtime, 3) if DB.is_file() else 0.0
    except OSError:
        db = 0.0
    return (matches, db)


def _dataset_stamp():
    """数据文件的廉价指纹（数量 + 最大 mtime），给跨局向量缓存做失效判断。

    只在快照重建时算一次（15 秒一次），不用每次都扫全目录；比「每 15 秒清空
    缓存」好：数据没变就继续命中，改了 bundle / 库才重算。

    2 秒 TTL 是给「缓存命中」这条路径用的：命中时只剩指纹可比，而 396 个
    文件逐个 stat 在本机要 40ms（资源盘 + 杀软过滤驱动），比很多接口本身的
    计算还贵。写接口都会先调 invalidate_snapshot()/drop_stamp_caches()，
    所以录入后第一次请求就能看到新数据，不会被 TTL 拖住。
    """
    return _ttl_stamp(_DATASET_STAMP_STATE, _scan_dataset_stamp)


_STAMP_TTL = 2.0
_DATASET_STAMP_STATE = {'at': float('-inf'), 'value': None}
_CAMP_STAMP_STATE = {'path': None, 'at': float('-inf'), 'value': None}


def _ttl_stamp(state, scan):
    now = monotonic()
    if now - state['at'] < _STAMP_TTL:
        return state['value']
    value = scan()
    state.update(at=now, value=value)
    return value


def drop_stamp_caches():
    """写操作后让目录指纹立刻重扫（否则目录 TTL 缓存会让新数据最多晚 2 秒）。"""
    _DATASET_STAMP_STATE.update(at=float('-inf'), value=None)
    _CAMP_STAMP_STATE.update(path=None, at=float('-inf'), value=None)


_series_router = create_series_router(DB, {
    'repo': lambda request: repository(request),
    'vectors': _series_vectors,
    # 列表 / 汇总按需只建已入组那几局的完整向量（at10 / 终局差仍可用）。
    'vectors_for': _series_vectors_for,
    # 编组建议与编组页 bootstrap 用轻量向量，0.1 秒级。
    'builder_vectors': _series_builder_vectors,
    # 编组页整包缓存用：廉价文件指纹，数据一变自动换 key。
    'data_stamp': _dataset_stamp,
    # 大场挖掘：全量单局完整向量，按对局包指纹缓存。
    'corpus': _series_corpus,
    'detail': _series_detail,
})
router.include_router(_series_router)

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
    for m in data.get('matches',[]) + data.get('sheetMatches',[]):
        if m.get('key') in overrides:
            m['bp'],m['bpRevision']=overrides[m['key']]


def invalidate_snapshot():
    global _snapshot, _loaded_at, _snapshot_generation
    with _lock:
        _snapshot, _loaded_at = None, float('-inf')
        # 代际号：后台重建期间若被写接口作废，这次结果就可能是旧的，提交前丢弃。
        _snapshot_generation += 1
    for name in ('_CROSS_VECTOR_CACHE', '_CROSS_VECTOR_BY_KEY', '_PANORAMA_CACHE',
                 '_POSITIONS_FILE_CACHE', '_CHANNELS_CACHE'):
        cache = globals().get(name)
        if cache is not None:
            cache.clear()
    drop_stamp_caches()


_data_stamp = (0, 0.0)
_snapshot_generation = 0
_refresh_lock = Lock()


def _sync_bundle_records(snapshot):
    """语料 ↔ 归档登记（P1-5）：新对局包首次出现时补一条 match_records，
    recorded_date 取对局日期；归属走训练起止口径，归档区可改直连。
    只在缺行时写入，避免快照重建反复 bump 数据库指纹。"""
    try:
        from workspace_store import Workspace
        ws = Workspace(DB)
        with ws.connect() as connection:
            existing = {row[0] for row in connection.execute(
                'SELECT match_key FROM match_records')}
        for match in (snapshot.get().get('matches') or []):
            key = str(match.get('key') or '')
            if not key or key in existing:
                continue
            date = str(match.get('date') or '')
            ws.upsert_match(key, date=date, recorded_date=date, source='bundle')
            existing.add(key)
            # 双通道统一：正赛包（matchType=formal）转正时，把同指纹的
            # 速记占位行链接过来（让位）。对局包路径 = MATCHES/{key}.json。
            bundle_path = MATCHES / f'{key}.json'
            is_formal = False
            try:
                body = json.loads(bundle_path.read_text(encoding='utf-8'))
                is_formal = (body.get('match') or {}).get('matchType') == 'formal'
            except Exception:
                is_formal = False
            if is_formal:
                opponent = str(match.get('opponent') or '').strip()
                for entry in ws.pending_formal_entries(limit=200):
                    entry_date = str(entry.get('date') or '')
                    entry_opponent = str(entry.get('opponent') or '').strip()
                    if entry_date == date and entry_opponent and (
                            entry_opponent in opponent or opponent in entry_opponent):
                        ws.link_formal_entry(entry['match_key'], key)
                        break
    except Exception:  # noqa: BLE001 - 登记失败不影响分析主链路
        pass


def _rebuild_snapshot():
    """重建快照并提交。重建本身不持状态锁，撞上的请求拿旧快照先走。"""
    global _snapshot, _loaded_at, _data_stamp
    with _lock:
        generation = _snapshot_generation
    snapshot = AnalysisRepository(DB, MATCHES, IMPORTS, OFFICIAL)
    data = snapshot.get()
    apply_bp_overrides(data)
    _sync_bundle_records(snapshot)
    stamp = _dataset_stamp()
    with _lock:
        if generation != _snapshot_generation:
            # 读盘期间有写操作作废了快照：这份可能是旧数据，直接丢弃，
            # 让下一个请求重新读（写接口刚改的内容不会被旧快照盖回去）。
            return
        # 数据指纹进缓存 key：数据没变就命中旧向量，变了自然换 key。
        # 只有指纹真的变了才清缓存（顺便回收旧指纹的条目），不会像
        # 「每次快照刷新都清空」那样每 15 秒重算一遍全量向量。
        if stamp != _data_stamp:
            _CROSS_VECTOR_CACHE.clear()
            _CROSS_VECTOR_BY_KEY.clear()
            _PANORAMA_CACHE.clear()
            _POSITIONS_FILE_CACHE.clear()
            _data_stamp = stamp
        _snapshot, _loaded_at = snapshot, monotonic()


def _start_background_rebuild():
    """后台重建快照（15 秒过期时用）：不阻塞当前请求，重建完自然切换。"""
    if not _refresh_lock.acquire(blocking=False):
        return False

    def work():
        try:
            _rebuild_snapshot()
        finally:
            _refresh_lock.release()

    Thread(target=work, daemon=True).start()
    return True


def _competition_scope_keys(competition_id, data=None):
    """赛事域（M1）统一 scope：数据库归属 + 文件层落在赛事窗口内的对局。

    数据库口径（workspace_store.competition_scope_keys）只覆盖 match_records 里
    登记过的对局。营地采集 / 表格导入的对局可能只落了数据包与营地面板，没在
    match_records 建行（或缺 date 被跳过），于是被带赛事参数的分析页静默过滤；
    首页取数不带赛事参数仍能看到 —— 赛训组反馈的「首页有 26 号，单局 / 大场 /
    跨场都没有」正是这一层漏掉的。这里用分析快照按赛事训练 / 正赛窗口补齐这批
    key，并保留单一归属纪律：已直连其他赛事的对局不拉回本赛事。
    """
    if not competition_id:
        return set()
    try:
        from workspace_store import Workspace
        ws = Workspace(DB)
        keys = set(ws.competition_scope_keys(competition_id))
    except Exception:  # noqa: BLE001 - 老库/IO 异常退回空集，页面保持可用
        ws, keys = None, set()
    if not isinstance(data, dict):
        return keys
    try:
        if ws is None:
            from workspace_store import Workspace
            ws = Workspace(DB)
        competition = ws.get_competition(competition_id)
        if not competition:
            return keys
        training_bounds = ws._collect_bounds(competition)
        formal_bounds = (ws._date_bounds(competition.get('formal_from'),
                                         competition.get('formal_to'))
                         or training_bounds)
        other = set()
        if DB.is_file():
            with closing(sqlite3.connect(f'file:{DB.as_posix()}?mode=ro', uri=True)) as connection:
                other = {str(row[0]) for row in connection.execute(
                    'SELECT match_key FROM match_records '
                    'WHERE competition_id IS NOT NULL AND competition_id != "" '
                    'AND competition_id != ?', (competition_id,))}
        for match in list(data.get('matches') or []) + list(data.get('sheetMatches') or []):
            key = str(match.get('key') or '')
            if not key or key in keys or key in other:
                continue
            day = str(match.get('date') or '')[:10]
            if not day:
                continue
            if ws._in_window(day, training_bounds) or ws._in_window(day, formal_bounds):
                keys.add(key)
    except Exception:  # noqa: BLE001 - 兜底失败不影响既有 DB scope
        pass
    return keys


def repository(request: Request):
    """按请求取分析仓库：带 competition 参数时返回按赛事收窄的视图。

    赛事是全站唯一的数据范围；所有分析源共用 competition_scope_keys 解析出的
    同一份 Match Keys。
    """
    snapshot = _base_repository(request)
    competition = request.query_params.get('competition') \
        or request.query_params.get('competitionId')
    if competition:
        from analysis_api import CompetitionScopedRepository
        return CompetitionScopedRepository(
            DB, MATCHES, IMPORTS, OFFICIAL,
            match_keys=_competition_scope_keys(competition, snapshot.get()),
            shared_data=snapshot.get())
    return snapshot


def _base_repository(request: Request):
    global _snapshot, _loaded_at
    fresh = request.query_params.get('fresh') == '1'
    if _snapshot is None:
        # 冷启动 / 刚被写接口作废：快照不可用，必须等（约 1.8 秒）。
        with _refresh_lock:
            if _snapshot is None:
                _rebuild_snapshot()
        return _snapshot
    if fresh:
        # 手动刷新（fresh=1）要的就是最新数据，同步重建；否则后台重建，
        # 当前请求先用旧快照返回，避免每 15 秒有一个请求莫名慢 1.8 秒。
        with _refresh_lock:
            _rebuild_snapshot()
    elif monotonic() - _loaded_at >= 15:
        _start_background_rebuild()
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
        # 赛事域（M1）：带 competition 时由 repository() 返回按赛事收窄的仓库。
        'competition': q.get('competition') or q.get('competitionId') or None,
    }


@router.get('/')
def v3_index():
    return FileResponse(HERE / 'public' / 'index.html')


_CROSS_LANES = ('对抗路', '打野', '中路', '发育路', '游走')
_CROSS_VECTOR_CACHE = {}
_CROSS_VECTOR_BY_KEY = {}
_CROSS_VECTOR_SCHEMA = 11
_CROSS_VECTOR_DISK = DATA_DIR / '.cache' / 'cross-vectors.json'
_CROSS_VECTOR_DISK_LOCK = Lock()
_CROSS_VECTOR_DISK_STATE = {'loaded': False, 'entries': {}}


def _cross_vector_cache_id(cache_key):
    return json.dumps(cache_key, ensure_ascii=False, separators=(',', ':'))


def _cross_vectors_disk_read(cache_key):
    key = _cross_vector_cache_id(cache_key)
    with _CROSS_VECTOR_DISK_LOCK:
        state = _CROSS_VECTOR_DISK_STATE
        if not state['loaded']:
            state['loaded'] = True
            try:
                doc = json.loads(_CROSS_VECTOR_DISK.read_text(encoding='utf-8'))
                entries = doc.get('entries') if isinstance(doc, dict) else None
                if doc.get('version') == _CROSS_VECTOR_SCHEMA and isinstance(entries, dict):
                    state['entries'] = entries
            except (OSError, ValueError):
                pass
        payload = state['entries'].get(key)
        return payload if isinstance(payload, dict) else None


def _cross_vectors_disk_write(cache_key, payload):
    key = _cross_vector_cache_id(cache_key)
    with _CROSS_VECTOR_DISK_LOCK:
        state = _CROSS_VECTOR_DISK_STATE
        state['loaded'] = True
        state['entries'][key] = payload
        while len(state['entries']) > 3:
            state['entries'].pop(next(iter(state['entries'])), None)
        try:
            _CROSS_VECTOR_DISK.parent.mkdir(parents=True, exist_ok=True)
            tmp = _CROSS_VECTOR_DISK.with_suffix('.tmp')
            tmp.write_text(json.dumps({'version': _CROSS_VECTOR_SCHEMA, 'entries': state['entries']},
                                      ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
            os.replace(tmp, _CROSS_VECTOR_DISK)
        except (OSError, TypeError, ValueError):
            pass
# 全景回放按局缓存：数据指纹没变就直接复用，replay 接口与跨局向量都从这里取。
# 存的是 replay 端点输出的九字段子集（约 40–57KB/局），不存整包 positions。
_PANORAMA_CACHE = {}
# positions.json / raw.json 的解析缓存：文件 mtime 变了才重读。
_POSITIONS_FILE_CACHE = {}


_REPLAY_FIELDS = ('gold', 'events', 'kills', 'deaths', 'fights', 'coverage',
                  'notes', 'buffEvents', 'narrations')

# 全景的磁盘缓存：build_panorama 单局约 350ms 且大头是逐秒坐标的纯计算，
# 进程重启后内存缓存全空，首次进跨局页要重算两百多局（半分钟以上）。
# 落盘一份九字段子集（每局几十 KB），按 bundle + 官方回放目录的 mtime 失效。
_PANORAMA_DISK = DATA_DIR / '.cache' / 'panorama'
_PANORAMA_DISK_FILE = _PANORAMA_DISK / 'all.json'
# 全景九字段子集合成一个磁盘文件：294 个小文件逐个读写会被实时扫描拖慢
# （实测每文件 100–200ms），单文件整存整取只扫一次。
_panorama_disk_data = None                    # 惰性加载 {key: {'sig': mtime, 'replay': {...}}}
_panorama_disk_dirty = False
_panorama_disk_last_write = 0.0
# build 互斥：miss 时只重建一次；缓存命中路径不进锁。并发重建曾让进程硬崩，
# 这里也保证任何时刻至多一个 build 在跑。
_PANORAMA_BUILD_LOCK = Lock()
# channels 表的 body 可能几百 KB，逐局查询+解析不便宜：按代际缓存解析结果。
_CHANNELS_CACHE = {}
# positions 的最终输出（十人降采样点，每局两万上下）也按局缓存：构造要
# 遍历全部点，跨局页每局都要取一次，没有缓存就是每批几十毫秒的重复劳动。
_POSITIONS_OUT_CACHE = {}


def _channel_camp(channel_id):
    """采集通道里的营地源数据（gameSeq / 玩家名单），带代际缓存。"""
    cached = _CHANNELS_CACHE.get(channel_id)
    if cached is not None and cached[0] == _data_stamp:
        return cached[1]
    try:
        with sqlite3.connect(f'file:{DB.as_posix()}?mode=ro', uri=True) as connection:
            row = connection.execute('SELECT body FROM channels WHERE id=?', (channel_id,)).fetchone()
    except sqlite3.Error:
        row = None
    camp = {}
    if row:
        try:
            channel = json.loads(row[0])
            camp = (channel.get('sources') or {}).get('camp') or {}
        except (ValueError, TypeError):
            camp = {}
    if len(_CHANNELS_CACHE) > 600:
        _CHANNELS_CACHE.clear()
    _CHANNELS_CACHE[channel_id] = (_data_stamp, camp)
    return camp


def _panorama_sig(key):
    """缓存新鲜度指纹：bundle 文件 mtime。bundle 变了（重采 / 挂回放）才重建。"""
    try:
        return round((MATCHES / f'{key}.json').stat().st_mtime, 3)
    except OSError:
        return None


def _panorama_disk_load():
    global _panorama_disk_data
    if _panorama_disk_data is None:
        try:
            data = json.loads(_PANORAMA_DISK_FILE.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            data = {}
        _panorama_disk_data = data if isinstance(data, dict) else {}
    return _panorama_disk_data


def _panorama_from_disk(key):
    sig = _panorama_sig(key)
    if sig is None:
        return None
    entry = _panorama_disk_load().get(key)
    if not isinstance(entry, dict) or entry.get('sig') != sig:
        return None
    body = entry.get('replay')
    return body if isinstance(body, dict) else None


def _panorama_to_disk(key, subset):
    """更新磁盘缓存内容；实际写盘有 15 秒节流，攒一批 miss 合并写一次。"""
    global _panorama_disk_dirty
    sig = _panorama_sig(key)
    if sig is None:
        return
    _panorama_disk_load()[key] = {'sig': sig, 'replay': subset}
    _panorama_disk_dirty = True


def _panorama_disk_flush():
    """把攒下的全景缓存写回磁盘（有 15 秒节流，避免冷启动期间反复整写）。"""
    global _panorama_disk_dirty, _panorama_disk_last_write
    if not _panorama_disk_dirty:
        return
    now = monotonic()
    if now - _panorama_disk_last_write < 15:
        return
    _panorama_disk_last_write = now
    _panorama_disk_dirty = False
    try:
        _PANORAMA_DISK.mkdir(parents=True, exist_ok=True)
        tmp = _PANORAMA_DISK_FILE.with_suffix('.tmp')
        tmp.write_text(json.dumps(_panorama_disk_load(), ensure_ascii=False,
                                  separators=(',', ':')), encoding='utf-8')
        os.replace(tmp, _PANORAMA_DISK_FILE)
    except (OSError, TypeError, ValueError):
        pass                                  # 磁盘缓存失败不影响主流程


def _panorama_cached(key):
    """全景回放按局缓存：内存一次命中，磁盘跨重启复用，miss 才重建。

    build_panorama 单次约 350ms（读 bundle、规范化事件、逐秒位置分析），
    跨局页每局都要取一次，没缓存时 200 局就是半分钟以上的重复计算。
    """
    cached = _PANORAMA_CACHE.get(key)
    if cached is not None and cached[0] == _data_stamp:
        return cached[1]
    with _PANORAMA_BUILD_LOCK:
        # 拿到锁后再查一次：刚才等锁期间别的线程可能已经把这局建好。
        cached = _PANORAMA_CACHE.get(key)
        if cached is not None and cached[0] == _data_stamp:
            return cached[1]
        subset = _panorama_from_disk(key)
        if subset is None:
            result = panorama.get(key)
            if result is None:
                return None
            subset = {name: result[name] for name in _REPLAY_FIELDS if name in result}
            _panorama_to_disk(key, subset)
        if len(_PANORAMA_CACHE) > 600:
            _PANORAMA_CACHE.clear()
        _PANORAMA_CACHE[key] = (_data_stamp, subset)
        _panorama_disk_flush()
        return subset


def _panorama_prewarm():
    """后台预热全景缓存：启动后逐局构建并落盘，教练首次进跨局页不再撞冷启动。

    单线程串行、与请求共享 build 锁：预热期间教练正常使用，最多为一局的
    重建等几百毫秒。失败静默，预热不是正确性的前提。
    """
    time.sleep(45)                            # 让启动期的快照重建 / 巅峰刷新先跑
    if IS_DEMO or not MATCHES.is_dir():
        return
    try:
        snapshot = AnalysisRepository(DB, MATCHES, IMPORTS, OFFICIAL)
        keys = [m['key'] for m in snapshot.get().get('matches') or [] if m.get('key')]
    except Exception:                         # noqa: BLE001
        return
    for key in keys:
        try:
            _panorama_cached(key)
        except Exception:                     # noqa: BLE001
            continue


Thread(target=_panorama_prewarm, daemon=True).start()


def _series_page_prewarm():
    """启动后预热编组页：轻量向量依赖仓库快照，先建好，首次进页不再等 3–4 秒。"""
    time.sleep(6)
    try:
        if _snapshot is None or monotonic() - _loaded_at >= 15:
            got = _refresh_lock.acquire(blocking=False)
            if got:
                try:
                    _rebuild_snapshot()
                finally:
                    _refresh_lock.release()
        snapshot = _snapshot
        if snapshot is not None:
            _series_builder_vectors(snapshot)
    except Exception:                         # noqa: BLE001 - 预热不是正确性前提
        pass


Thread(target=_series_page_prewarm, daemon=True).start()


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
    # 数据指纹进 key：bundle / 库文件变了才重算，否则一直复用。
    cache_id = (_data_stamp, key, segments)
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
    fight = {'n': None, 'win': None, 'decidedN': None, 'decidedWin': None}
    # 反野按 BUFF 颜色拆开：教练要看「红被反几个、蓝被反几个」，不只一个总数。
    buff = {'anti': None, 'stolen': None, 'antiRed': None, 'antiBlue': None,
            'stolenRed': None, 'stolenBlue': None}
    # 切 C 拆成「打野切 / 对抗路切 / 被切」：教练要问的是打野切了几次，
    # 一个笼统的 cut.n 看不出是谁干的。
    cut = {'n': None, 'first': None, 'jungle': None, 'top': None, 'suffered': None}
    # 中立资源按类型拆开：暴君 / 主宰 / 暗影暴君 / 暗影主宰 / 风暴龙王，
    # 四种龙的价值完全不同，不能只给一个「龙」总数。
    obj_types = None
    # 一血 / 一龙 / 一塔与 10 分钟前的资源量：跨局「前期节奏」分析要用，
    # 但只在有回放的局里成立；没有回放保持 None，不补 0。
    first = None
    obj_at10 = None
    fk = None
    fs = None
    try:
        replay = _panorama_cached(d.get('bundleKey') or '') if d.get('bundleKey') else None
    except Exception:                                  # noqa: BLE001
        replay = None
    if replay:
        other = 'red' if camp == 'blue' else 'blue'
        events = [e for e in (replay.get('events') or []) if isinstance(e, dict)]
        raw_dragons = [e for e in events if e.get('name') in
                       ('暴君', '暗影暴君', '暗影主宰', '主宰', '风暴龙王')]
        raw_towers = [e for e in events if e.get('name') in ('防御塔', '水晶')]
        # 同一座建筑在回放事件里会出现多次「摧毁」记录（多路伤害 / 重复采集），
        # 直接按事件数会得出「一局推了 39 座塔」。按 (击杀方, 建筑 id) 去重，
        # 只认最早一次；水晶不算推塔。任何建筑重复超过 6 次视为这份回放的
        # 事件流不可信，塔数记 None，前端显示「回放异常」而不是假数字。
        tower_index, tower_repeat, crystal = {}, 0, None
        for event in raw_towers:
            seconds = event.get('t')
            if not isinstance(seconds, (int, float)):
                continue
            if event.get('name') == '水晶':
                if crystal is None or seconds < crystal['t']:
                    crystal = event
                continue
            identity = (event.get('killerCamp'), str(event.get('id')))
            tower_index.setdefault(identity, []).append(seconds)
        for times in tower_index.values():
            tower_repeat = max(tower_repeat, len(times))
        towers_known = tower_repeat <= 6 and bool(tower_index or crystal)
        towers = [{'t': min(times), 'killerCamp': identity[0]}
                  for identity, times in tower_index.items()] if towers_known else []
        if crystal and towers_known:
            towers.append({'t': crystal['t'], 'killerCamp': crystal.get('killerCamp')})
        dragon_index = {}
        for event in raw_dragons:
            seconds = event.get('t')
            if not isinstance(seconds, (int, float)):
                continue
            name = str(event.get('name') or '中立资源')
            dragon_index[(event.get('killerCamp'), str(event.get('id')), round(seconds))] = (seconds, name)
        dragons = [{'t': seconds, 'killerCamp': identity[0], 'name': name}
                   for identity, (seconds, name) in dragon_index.items()]
        dragons_known = bool(dragons) or bool((replay.get('coverage') or {}).get('resources'))
        side_of = lambda c: 'own' if c == camp else 'foe' if c == other else None
        tower_events, dragon_events = towers, dragons

        def first_of(rows):
            timed = [x for x in rows if isinstance(x.get('t'), (int, float))]
            return min(timed, key=lambda x: x['t']) if timed else None

        first_dragon = first_of(dragons)
        first_tower = first_of(towers)
        first_blood = first_of([k for k in (replay.get('kills') or []) if isinstance(k, dict)])
        first = {
            'bloodT': round(float(first_blood['t']), 1) if first_blood else None,
            'bloodSide': side_of(first_blood.get('killerCamp')) if first_blood else None,
            'dragonT': round(float(first_dragon['t']), 1) if first_dragon else None,
            'dragonSide': side_of(first_dragon.get('killerCamp')) if first_dragon else None,
            'dragonName': first_dragon.get('name') if first_dragon else None,
            'towerT': round(float(first_tower['t']), 1) if first_tower else None,
            'towerSide': side_of(first_tower.get('killerCamp')) if first_tower else None,
        }
        early_dragons = [e for e in dragons if isinstance(e.get('t'), (int, float)) and e['t'] <= 600]
        early_towers = [e for e in towers if isinstance(e.get('t'), (int, float)) and e['t'] <= 600]
        obj_at10 = {
            'dragonOwn': sum(1 for e in early_dragons if e.get('killerCamp') == camp) if dragons_known else None,
            'dragonFoe': sum(1 for e in early_dragons if e.get('killerCamp') == other) if dragons_known else None,
            'towerOwn': sum(1 for e in early_towers if e.get('killerCamp') == camp) if towers_known else None,
            'towerFoe': sum(1 for e in early_towers if e.get('killerCamp') == other) if towers_known else None,
        }
        obj['dragonOwn'] = sum(1 for e in dragons if e.get('killerCamp') == camp) if dragons_known else None
        obj['dragonFoe'] = sum(1 for e in dragons if e.get('killerCamp') == other) if dragons_known else None
        obj['towerOwn'] = sum(1 for e in towers if e.get('killerCamp') == camp) if towers_known else None
        obj['towerFoe'] = sum(1 for e in towers if e.get('killerCamp') == other) if towers_known else None
        deaths = [x for x in (replay.get('deaths') or []) if isinstance(x, dict)]
        death['own'] = sum(1 for x in deaths if x.get('camp') == camp)
        death['foe'] = sum(1 for x in deaths if x.get('camp') == other)
        fights = [f for f in (replay.get('fights') or []) if isinstance(f, dict)]
        fight['n'] = len(fights)
        fight['win'] = sum(1 for f in fights if (f.get(camp) or 0) > (f.get(other) or 0))
        # 零击杀团不进胜率分母：跨局页的团战胜率以「有击杀的团」为分母，
        # 否则拉扯/试探团会被算成未胜，拉低所有局的团战胜率。
        decided = [f for f in fights if (f.get(camp) or 0) + (f.get(other) or 0) > 0]
        fight['decidedN'] = len(decided)
        fight['decidedWin'] = sum(1 for f in decided if (f.get(camp) or 0) > (f.get(other) or 0))
        # 分阶段资源与团战：教练按 0–4′ / 4–10′ / 10′+ 三段问「这段拿了什么」，
        # 只有带时间戳的回放能拆；没有回放的局保持整块 None，不补 0。
        phase_of = lambda t: ('early' if t < 240 else 'mid' if t < 600 else 'late') \
            if isinstance(t, (int, float)) else None
        obj_phase = {p: {'dragonOwn': 0 if dragons_known else None,
                         'dragonFoe': 0 if dragons_known else None,
                         'towerOwn': 0 if towers_known else None,
                         'towerFoe': 0 if towers_known else None}
                     for p in ('early', 'mid', 'late')}
        for event in dragon_events:
            if not dragons_known:
                break
            phase = phase_of(event.get('t'))
            if not phase:
                continue
            if event.get('killerCamp') == camp:
                obj_phase[phase]['dragonOwn'] += 1
            elif event.get('killerCamp') == other:
                obj_phase[phase]['dragonFoe'] += 1
        for event in tower_events:
            if not towers_known:
                break
            phase = phase_of(event.get('t'))
            if not phase:
                continue
            if event.get('killerCamp') == camp:
                obj_phase[phase]['towerOwn'] += 1
            elif event.get('killerCamp') == other:
                obj_phase[phase]['towerFoe'] += 1
        fight_phase = {p: {'n': 0, 'decidedN': 0, 'win': 0, 'decidedWin': 0}
                       for p in ('early', 'mid', 'late')}
        for f in fights:
            phase = phase_of(f.get('t'))
            if not phase:
                continue
            cell = fight_phase[phase]
            cell['n'] += 1
            if (f.get(camp) or 0) + (f.get(other) or 0) > 0:
                cell['decidedN'] += 1
                if (f.get(camp) or 0) > (f.get(other) or 0):
                    cell['decidedWin'] += 1
            if (f.get(camp) or 0) > (f.get(other) or 0):
                cell['win'] += 1
        buffs = [b for b in (replay.get('buffEvents') or []) if isinstance(b, dict)]
        buff['anti'] = sum(1 for b in buffs if b.get('owner') == other and b.get('killer') == camp)
        buff['stolen'] = sum(1 for b in buffs if b.get('owner') == camp and b.get('killer') == other)
        is_blue = lambda b: '蓝' in str(b.get('name') or '')
        buff['antiBlue'] = sum(1 for b in buffs if b.get('owner') == other and b.get('killer') == camp and is_blue(b))
        buff['antiRed'] = sum(1 for b in buffs if b.get('owner') == other and b.get('killer') == camp and not is_blue(b))
        buff['stolenBlue'] = sum(1 for b in buffs if b.get('owner') == camp and b.get('killer') == other and is_blue(b))
        buff['stolenRed'] = sum(1 for b in buffs if b.get('owner') == camp and b.get('killer') == other and not is_blue(b))
        # 分阶段反野：教练问「这一段反了几个红/蓝」，按事件时间归到三段。
        buff_phase = {p: {'antiRed': 0, 'antiBlue': 0, 'stolenRed': 0, 'stolenBlue': 0}
                      for p in ('early', 'mid', 'late')}
        for b in buffs:
            phase = phase_of(b.get('t'))
            if not phase:
                continue
            is_blue = '蓝' in str(b.get('name') or '')
            if b.get('owner') == other and b.get('killer') == camp:
                buff_phase[phase]['antiBlue' if is_blue else 'antiRed'] += 1
            elif b.get('owner') == camp and b.get('killer') == other:
                buff_phase[phase]['stolenBlue' if is_blue else 'stolenRed'] += 1
        kills = [k for k in (replay.get('kills') or []) if isinstance(k, dict)]
        pos_of = {p.get('hero'): p.get('position') for p in (d.get('players') or []) if p.get('hero')}

        def cut_count(killer_positions):
            return sum(
                1 for k in kills
                if k.get('killerCamp') == camp
                and pos_of.get(k.get('killer')) in killer_positions
                and pos_of.get(k.get('victim')) in ('中路', '发育路')
            )

        cut['n'] = cut_count(('对抗路', '打野'))
        cut['jungle'] = cut_count(('打野',))
        cut['top'] = cut_count(('对抗路',))
        cut['suffered'] = sum(
            1 for k in kills
            if k.get('killerCamp') == other
            and pos_of.get(k.get('killer')) in ('对抗路', '打野')
            and pos_of.get(k.get('victim')) in ('中路', '发育路')
        )
        # 中立资源分类型：只统计回放里真正出现的类型；没有出现的类型不补 0，
        # 避免前端把「这场没打风暴龙王」当成「0 条」。
        if dragons_known:
            obj_types = {}
            for event in dragons:
                name = str(event.get('name') or '中立资源')
                cell = obj_types.setdefault(name, {'own': 0, 'foe': 0})
                if event.get('killerCamp') == camp:
                    cell['own'] += 1
                elif event.get('killerCamp') == other:
                    cell['foe'] += 1
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
            # 零击杀的拉扯团不进分桶分母：跨局页的团战分桶只回答「打起来的团赢没赢」。
            kills_total = (f.get(camp) or 0) + (f.get(other) or 0)
            if kills_total <= 0:
                continue
            won = (f.get(camp) or 0) > (f.get(other) or 0)
            # 注意：这里不能用 key（外层 key 是对局 match_key，最后要进 vector），
            # 改名 bucket。此前覆盖曾让 330/386 个有团战回放的向量 key 变成
            # adv/even/dis，跨局分析按局链接与系列赛索引全部错位（2026-11-14 修复）。
            bucket = 'adv' if ours > theirs else 'dis' if ours < theirs else 'even'
            buckets[bucket]['n'] += 1
            if won:
                buckets[bucket]['win'] += 1
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
    # 双方各算一份：翻到「敌方视角」时野区不该是空的，对面打野的坐标同样在 positions.json 里。
    jungle = {'crossSec': None, 'crossShare': None, 'firstCross': None, 'deepSec': None, 'deepShare': None}
    jungle_foe = {'crossSec': None, 'crossShare': None, 'firstCross': None, 'deepSec': None, 'deepShare': None}
    replay_id = _safe_key((d.get('officialReplay') or {}).get('id'))
    if replay_id:
        pos_path = OFFICIAL / replay_id / 'positions.json'
        slots = []
        if pos_path.is_file():
            try:
                slots = (json.loads(pos_path.read_text(encoding='utf-8')) or {}).get('players') or []
            except (OSError, ValueError):
                slots = []

        def jungle_of(side_camp):
            if not side_camp:
                return jungle
            idx = None
            for i, p in enumerate(d.get('players') or []):
                if p.get('camp') == side_camp and p.get('position') == '打野':
                    idx = i
                    break
            if idx is None or idx >= len(slots):
                return None
            arr = (slots[idx] or {}).get('posArr') or []
            facing = 1 if side_camp == 'blue' else -1
            e_vals = [(q[0] + q[1]) / 2.0 * facing for q in arr[:600]
                      if isinstance(q, (list, tuple)) and len(q) >= 2]
            if not e_vals:
                return None
            cross_sec = sum(1 for v in e_vals if v > 8)
            deep = sum(1 for v in e_vals if v > 25)
            return {
                'crossSec': cross_sec,
                'crossShare': round(cross_sec / len(e_vals), 3),
                'deepSec': deep,
                'deepShare': round(deep / len(e_vals), 3),
                'firstCross': next((i for i, v in enumerate(e_vals) if v > 8), None),
            }

        own_jungle = jungle_of(camp)
        if own_jungle:
            jungle = own_jungle
        foe_jungle = jungle_of('red' if camp == 'blue' else 'blue')
        if foe_jungle:
            jungle_foe = foe_jungle

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
            'arch': hero_archetypes.archetype_of(p.get('hero') or '', p.get('position')) if p.get('hero') else '',
            # 该分路没登记类型时的兜底：英雄默认分路的类型（前端只在「类型分布」里用，
            # 不写回逐局类型口径）。这样跨局页不再出现「待分类」这种词。
            'archDefault': hero_archetypes.archetype_of(p.get('hero') or '') if p.get('hero') else '',
            'k': p.get('kills'), 'd': p.get('deaths'), 'a': p.get('assists'),
            'gpm': round(number(p.get('gold')) / minutes, 1) if minutes and p.get('gold') is not None else None,
            'dpm': round(number(p.get('damage')) / minutes, 1) if minutes and p.get('damage') is not None else None,
            'part': p.get('participation'),
            # 赛后选手执行还要承伤/控制/推塔：游走不看经济与输出，改看承伤；
            # 对抗路同时看承伤。分均量统一用分钟折算，营地原值保持整数。
            'tpm': round(number(p.get('taken')) / minutes, 1) if minutes and p.get('taken') is not None else None,
            'ctrl': p.get('control'),
            'ctrlpm': round(number(p.get('control')) / minutes, 1) if minutes and p.get('control') is not None else None,
            'heal': round(number(p.get('healing')) / minutes, 1) if minutes and p.get('healing') is not None else None,
            'twr': round(number(p.get('towerDamage')) / minutes, 1) if minutes and p.get('towerDamage') is not None else None,
            'rating': p.get('rating'),
        })
    bp = d.get('campBp') or {}
    bans = [x.get('name') for side in ('left', 'right') for x in ((bp.get('bans') or {}).get(side) or []) if x.get('name')]
    # 双方 ban 拆分：只有营地明确给出 ownSide 时才拆，缺了就留 None，不猜边。
    own_side = str(bp.get('ownSide') or '').strip().lower()
    foe_side = 'right' if own_side == 'left' else 'left' if own_side == 'right' else ''
    bans_own = ([x.get('name') for x in ((bp.get('bans') or {}).get(own_side) or []) if x.get('name')]
                if foe_side else None)
    bans_foe = ([x.get('name') for x in ((bp.get('bans') or {}).get(foe_side) or []) if x.get('name')]
                if foe_side else None)
    comp_own = hero_capabilities.functional_tags(heroes) or None
    comp_foe = hero_capabilities.functional_tags(heroes_foe) or None
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
        'opponentTeamId': d.get('opponentTeamId') or item.get('opponentTeamId') or '',
        'result': d.get('result') or item.get('result') or '',
        'duration': duration, 'camp': camp,
        'at10': g[2], 'finalDiff': final, 'g': g, 'w': w, 's': shape,
        'at4': round(at4, 1) if at4 is not None else None,
        'seg': seg,
        'obj': obj, 'objTypes': obj_types, 'death': death, 'fight': fight, 'buff': buff,
        'objPhase': obj_phase if replay else None,
        'fightPhase': fight_phase if replay else None,
        'buffPhase': buff_phase if replay else None,
        'objKnown': {'dragon': dragons_known, 'tower': towers_known} if replay else None,
        'cut': cut, 'fk': fk, 'jungle': jungle, 'jungleFoe': jungle_foe,
        'first': first, 'objAt10': obj_at10,
        'pl': pl, 'fs': fs,
        'killsOwn': kill_own, 'killsFoe': kill_foe,
        'lanes': lanes, 'heroes': heroes, 'heroesFoe': heroes_foe, 'bans': bans,
        'bansOwn': bans_own, 'bansFoe': bans_foe,
        'compOwn': comp_own, 'compFoe': comp_foe,
        # 覆盖标记：有回放才有事件 / 位置类分析；经济点位数决定过程曲线可不可用。
        'hasReplay': bool(replay), 'ecoPoints': len(econ),
    }
    _CROSS_VECTOR_BY_KEY[cache_id] = vector
    return vector


_SERIES_INDEX_CACHE = {'stamp': None, 'map': {}}


def _cross_series_index():
    """match_key → 所属系列赛 {seriesId, bestOf, gameIndex, seriesStart}。

    跨局分析按 BO3/5/7 与局序筛选要这层关系；系列赛编组写入库即失效
    （按 sqlite mtime），没有编组表时返回空字典，页面按「未编组」处理。
    """
    try:
        stamp = DB.stat().st_mtime if DB.is_file() else 0.0
    except OSError:
        stamp = 0.0
    if _SERIES_INDEX_CACHE['stamp'] == stamp:
        return _SERIES_INDEX_CACHE['map']
    try:
        import workspace_store
        mapping = workspace_store.Workspace(DB).ensure_schema().series_index()
    except Exception:  # noqa: BLE001 - 编组数据异常不应拖垮跨局分析
        mapping = {}
    _SERIES_INDEX_CACHE.update(stamp=stamp, map=mapping)
    return mapping


@router.get('/api/cross/vectors')
def cross_vectors(request: Request, values=Depends(filters)):
    """全量对局的轻量指标向量，供通用跨局分析一次取回。

    每局只带聚合需要的标量（经济检查点、5 分钟净增、分路分均差、阵容、
    BP、结果与分层标签），不含十人明细、位置序列和事件流；逐局明细仍由
    /api/matches/{key} 按需取。局数上万时这里应换成预聚合表／物化视图，
    接口契约（向量字段）保持不变，前端分析内核无需改动。
    """
    # 先查内存 / 磁盘：命中时连仓库快照都不建，跨局页重启后也不再等 5 秒重建。
    cache_key = (_CROSS_VECTOR_SCHEMA, _cross_data_stamp(),
                 values['from'], values['to'], tuple(values['sources']),
                 values['excludeSeeds'], values['hero'], values['opponent'], values['ownOnly'])
    payload = _CROSS_VECTOR_CACHE.get(cache_key)
    if payload is None:
        payload = _cross_vectors_disk_read(cache_key)
        if payload is not None:
            _CROSS_VECTOR_CACHE[cache_key] = payload
    if payload is None:
        repo = repository(request)
        items = repo.matches(values)['matches']
        max_duration = max((float(i.get('duration') or 0) for i in items), default=0.0)
        segments = max(4, min(16, int(max_duration // 300) + 1)) if max_duration else 8
        # 注：试过线程池并行构建（各局独立、纯读），但在 Windows 上会让进程
        # 硬崩（无 Python 异常，疑似底层库非线程安全），保持串行——冷启动靠
        # panorama 按局缓存与 _find_bundle 直取提速，且前端向量一到就先渲染。
        vectors = [v for v in (_cross_vector(repo, item, segments) for item in items) if v]
        payload = {'total': len(items), 'vectors': vectors, 'unit': 'cohort-vectors-v1',
                   'segments': segments, 'windowMin': 5}
        if len(_CROSS_VECTOR_CACHE) > 4:
            _CROSS_VECTOR_CACHE.clear()
        _CROSS_VECTOR_CACHE[cache_key] = payload
        _cross_vectors_disk_write(cache_key, payload)
    # 系列赛关系不进缓存：编组一变就要立刻反映到赛制 / 局序筛选项上，
    # 这里对每局做一次 dict 拷贝再贴字段（几百局的拷贝成本可以忽略）。
    series = _cross_series_index()
    if series:
        payload = dict(payload, vectors=[
            dict(v, **series[str(v.get('key') or '')]) if str(v.get('key') or '') in series else v
            for v in payload['vectors']])
    # 直接 dumps 返回：绕过 jsonable_encoder（vector 数量上千字段时明显慢）。
    return Response(content=json.dumps(payload, ensure_ascii=False, separators=(',', ':')),
                    media_type='application/json')


def json_response(payload):
    """直接 dumps 返回，绕过 FastAPI 的 jsonable_encoder。

    默认返回 dict 时 FastAPI 会递归重建整个响应对象（只为把类型转成 JSON），
    0.5–1.4 MB 的分析结果要多花 60–150ms；cross/vectors、cross/window 早就是
    这么做的。只用于本身就是纯 JSON 结构（dict/list/str/number/bool/None）的载荷。
    """
    return Response(content=json.dumps(payload, ensure_ascii=False, separators=(',', ':')),
                    media_type='application/json')


@router.get('/api/overview')
def overview(repo=Depends(repository), values=Depends(filters)):
    summary = repo.overview(values)
    matches = sorted(repo.matches(values)['matches'], key=lambda item: (bool(item.get('date')), item.get('date') or '', item.get('startTime') or ''), reverse=True)
    process = repo.process(values)
    process['matches'].sort(key=lambda item: (bool(item.get('date')), item.get('date') or '', item.get('startTime') or ''), reverse=True)
    # 十分钟领先兑现：process 已算好 leadAt10 / win
    led = sum(1 for g in (process.get('matches') or []) if g.get('leadAt10'))
    won = sum(1 for g in (process.get('matches') or []) if g.get('leadAt10') and g.get('win'))
    if led:
        summary['tenMinLead'] = f'{won}/{led}'
    return json_response({
        'summary': {key: value for key, value in summary.items() if key != 'profile'},
        'team': repo.team_stats(values),
        'matches': matches,
        'process': process,
    })


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
    result['matches'].sort(key=lambda item: (bool(item.get('date')), item.get('date') or '', item.get('startTime') or ''), reverse=True)
    return result


@router.get('/api/matches/{key:path}')
def match(key: str, repo=Depends(repository)):
    detail = repo.match_detail(key)
    if detail is None:
        raise HTTPException(404, '找不到该局对战记录')
    # 营地名单 + 页面手工顺序 / 已核验逐手事件 / 默认训练赛推定。
    detail['draft'] = merge_bp_sources(detail.get('bp'), detail.get('campBp'), detail,
                                       events=camp_draft_events(detail),
                                       order=camp_bp_order(detail),
                                       assume_scrim=True)
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


@router.get('/api/v3/versions')
def version_records():
    """赛训版本记录：版本名 + 起止日期。

    教练在这里填 S40 / S41 各自的时间段；对局本身带日期，前端据此把每局
    归到版本里，不用再一局一局手填版本。
    """
    return {'schema': VERSIONS_SCHEMA, 'versions': _read_version_records()}


@router.post('/api/v3/versions')
def save_version_records(value: dict = Body(...)):
    """整表覆盖保存（前端一次提交「版本名 / 开始 / 结束」全部行）。"""
    rows = value.get('versions')
    if not isinstance(rows, list):
        raise HTTPException(400, 'versions 必须是数组')
    if len(rows) > 40:
        raise HTTPException(400, '最多 40 条版本记录')
    cleaned, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get('name') or '').strip()
        if not name:
            continue
        if len(name) > 20:
            raise HTTPException(400, f'版本名过长：{name[:20]}…')
        if name in seen:
            raise HTTPException(400, f'版本名重复：{name}')
        seen.add(name)
        start = _iso_day(row.get('start'))
        end = _iso_day(row.get('end'))
        if start and end and start > end:
            raise HTTPException(400, f'{name} 的结束日期早于开始日期')
        cleaned.append({'name': name, 'start': start, 'end': end})
    # 有开始日期的按日期排，没填日期的放最后，顺序稳定（页面直接按这个顺序显示）
    cleaned.sort(key=lambda item: (item['start'] or '9999-99-99', item['name']))
    payload = {'schema': VERSIONS_SCHEMA, 'versions': cleaned, 'updatedAt': int(time.time())}
    path = DATA_DIR / 'versions.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8')
    tmp.replace(path)
    return payload


def _iso_day(value):
    """只接受 YYYY-MM-DD；空值表示不限（开区间）。"""
    text = str(value or '').strip()
    if not text:
        return ''
    match = re.fullmatch(r'(\d{4})-(\d{2})-(\d{2})', text)
    if not match:
        raise HTTPException(400, f'日期格式应为 YYYY-MM-DD：{text}')
    try:
        date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        raise HTTPException(400, f'日期不存在：{text}') from None
    return text


def _read_version_records():
    path = DATA_DIR / 'versions.json'
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    rows = payload.get('versions') if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get('name') or '').strip()
        if not name:
            continue
        out.append({'name': name,
                    'start': str(row.get('start') or '').strip(),
                    'end': str(row.get('end') or '').strip()})
    return out


@router.get('/api/v3/peak/status')
def peak_status():
    """巅峰千强大盘爬取状态：进度、数据窗口、是否自动启用。"""
    if peak_crawl is None:
        return {'available': False, 'running': False, 'phase': '',
                'message': '这份代码里没有巅峰千强抓取模块（它依赖私有数据集，不在公开仓库）。'}
    return peak_crawl.status()


@router.post('/api/v3/peak/refresh')
def peak_refresh():
    """手动触发一轮巅峰千强刷新（后台线程执行，接口立即返回；同一时间只跑一轮）。"""
    if peak_crawl is None:
        raise HTTPException(503, '这份代码里没有巅峰千强抓取模块，无法刷新。')
    if IS_DEMO:
        raise HTTPException(403, '演示数据包环境不联网爬取。')
    if os.environ.get('PEAK_CRAWL') == '0':
        raise HTTPException(403, '巅峰千强爬取已被 PEAK_CRAWL=0 关闭。')
    snapshot = peak_crawl.status()
    if snapshot.get('running'):
        return {'ok': False, 'running': True, 'phase': snapshot.get('phase') or '',
                'message': '已有一轮刷新在跑，请稍后。'}
    Thread(target=peak_crawl.refresh, kwargs={'reason': 'api'}, daemon=True).start()
    return {'ok': True, 'running': True, 'message': '刷新已开始，进度看 /api/v3/peak/status。'}


@router.get('/api/v3/data-source-health')
def data_source_health_status():
    """管理页「外部数据源爬取情况」：汇总各源状态，不触发任何爬取。"""
    import data_source_health as health
    return health.snapshot()


@router.post('/api/v3/data-source-health/refresh')
def data_source_health_refresh(payload: dict = Body(default={})):
    """手动重试某个数据源；后台线程执行，接口立即返回。"""
    import data_source_health as health
    result = health.refresh(str(payload.get('source') or ''))
    if not result.get('ok'):
        raise HTTPException(409, result.get('message') or '刷新失败')
    return result


def start_peak_auto() -> bool:
    """由 server.py 的真实服务入口调用：启动每日自动刷新线程（导入 / 测试不触发）。"""
    if peak_crawl is None:
        return False
    return peak_crawl.start_auto()


# KPL 组合全库约 3.5 万行、序列化后 10 MB 级：过去每次请求都要重建精简行
# 再走一遍 FastAPI 的 jsonable_encoder。按事实表 mtime 缓存已序列化的响应体，
# 命中时直接回字节，省掉重建与编码两步；再落盘一份，重启后第一次打开也不重建。
_KPL_COMBOS_CACHE = {'key': None, 'body': None}


def _facts_stamp(name):
    try:
        stat = (bp_facts.FACTS / name).stat()
        return (stat.st_mtime_ns, stat.st_size)
    except OSError:
        return None


_COMBO_POOL_LOCK = Lock()


@router.get('/api/v3/custom-combos')
def custom_combos_get():
    """赛训组自定义组合池（双人 / 三人），最高优先级，设置页读写这里。"""
    import combo_pool
    return combo_pool.load()


@router.get('/api/v3/custom-combos/builtin')
def custom_combos_builtin():
    """内置默认组合池，供设置页空状态「一键补充」用（不落盘、不参与命中口径）。"""
    import combo_pool
    return combo_pool._default_doc()


@router.post('/api/v3/custom-combos')
def custom_combos_set(payload: dict = Body(...)):
    """整体覆盖保存自定义组合池；revision 不匹配说明别人刚改过，返回 409 让界面提示刷新。"""
    import combo_pool
    try:
        revision = int(payload.get('revision'))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail='revision 必须是整数')
    # load + 乐观锁校验 + save 必须原子，否则两个同 revision 的并发请求都能通过检查。
    with _COMBO_POOL_LOCK:
        current = combo_pool.load()
        if revision != current.get('revision'):
            raise HTTPException(status_code=409,
                                detail='组合池已被其他人更新，请刷新后再改。')
        incoming = {'schema': combo_pool.SCHEMA, 'revision': current.get('revision'),
                    'pairs': payload.get('pairs'), 'trios': payload.get('trios')}
        # updatedAt 不沿用旧值：save() 每次写当前 UTC，时间戳才反映真实保存时刻。
        try:
            saved = combo_pool.save(incoming)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))
        _KPL_COMBOS_CACHE.update(key=None, body=None)   # 组合变了，全库查询缓存要重算
    return {'ok': True, 'revision': saved['revision'], 'updatedAt': saved['updatedAt']}


_GRADE_RULES_LOCK = Lock()


@router.get('/api/v3/grade-rules')
def grade_rules_get():
    """赛训组自定义「分路 × 字段」评级规则，最高优先级，设置页读写这里。"""
    import grade_rules
    doc = grade_rules.load()
    doc['saved'] = grade_rules.has_saved()
    # 设置页「恢复本分路默认」必须恢复内置默认，而不是上次保存值。
    doc['defaults'] = grade_rules.normalize(None)
    return doc


@router.post('/api/v3/grade-rules')
def grade_rules_set(payload: dict = Body(...)):
    """整体覆盖保存评级规则；revision 不匹配返回 409 让界面提示刷新。"""
    import grade_rules
    try:
        revision = int(payload.get('revision'))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail='revision 必须是整数')
    with _GRADE_RULES_LOCK:
        current = grade_rules.load()
        if revision != current.get('revision'):
            raise HTTPException(status_code=409,
                                detail='评级规则已被其他人更新，请刷新后再改。')
        incoming = {'schema': grade_rules.SCHEMA, 'revision': current.get('revision'),
                    'subjects': payload.get('subjects')}
        try:
            saved = grade_rules.save(incoming)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))
    return {'ok': True, 'revision': saved['revision'], 'updatedAt': saved['updatedAt']}


@router.get('/api/v3/kpl/combos')
def kpl_combos():
    """KPL 组合全库（双人 / 三人 / 四人），供复盘大屏的组合查询块筛选。

    行做过精简：只留查询块要展示的字段；整阵容（lineups）不进这块——它只在
    赛事命中里按本局阵容查，不参与自由组合查询。
    """
    stamp = _facts_stamp('kpl_combos.json')
    # 组合池变化时缓存键要跟着变，否则保存后仍拿到旧的纯 KPL body。
    try:
        import combo_pool
        pool_rev = combo_pool.load().get('revision') if combo_pool.has_saved() else None
    except (ImportError, OSError, ValueError):
        pool_rev = None
    cache_key = (stamp, pool_rev)
    if pool_rev is None and stamp is not None and _KPL_COMBOS_CACHE['key'] == cache_key:
        return Response(content=_KPL_COMBOS_CACHE['body'], media_type='application/json')
    key_id = _cache_key_id(stamp)
    if pool_rev is None:                      # 没有组合池才用磁盘缓存（纯 KPL 口径）
        body = _report_disk_read(DATA_DIR / '.cache' / 'kpl-combos.json', key_id, 'body')
        if isinstance(body, str):
            _KPL_COMBOS_CACHE.update(key=cache_key, body=body)
            return Response(content=body, media_type='application/json')
    index = bp_facts.kpl_index()

    def slim(row):
        return {'heroes': row.get('heroes') or [], 'n': row.get('n'),
                'wins': row.get('wins'), 'wr': row.get('wr'),
                'year': row.get('year'), 'lastDate': row.get('lastDate'),
                'teams': (row.get('teams') or [])[:3]}

    pairs_rows = [slim(row) for row in index['pairs'].values()]
    trios_rows = [slim(row) for row in index['trios'].values()]
    # 赛训组组合池已保存时（最高优先级）：双人 / 三人库只认池子名单，
    # KPL 同名行只补背景场次 / 胜率，删掉的组合也不再从 KPL 泄漏回来。
    pool_active = False
    try:
        import combo_pool
        pool_active = combo_pool.has_saved()
        if pool_active:
            for size, rows, target in ((2, combo_pool.rows(2, saved_only=True), pairs_rows),
                                       (3, combo_pool.rows(3, saved_only=True), trios_rows)):
                background = index['pairs' if size == 2 else 'trios']
                rebuilt = []
                for row in rows:
                    heroes = sorted(combo_pool.normalize(h) for h in row['heroes'])
                    base = dict(background.get(tuple(heroes)) or {})
                    rebuilt.append({'heroes': heroes, 'n': base.get('n') or 0,
                                    'wins': base.get('wins'), 'wr': base.get('wr'),
                                    'year': base.get('year'), 'lastDate': base.get('lastDate'),
                                    'teams': (base.get('teams') or [])[:3],
                                    'source': 'custom', 'strength': row.get('strength'),
                                    'name': row.get('name'), 'note': row.get('note')})
                target[:] = rebuilt
    except (ImportError, OSError, ValueError):
        pool_active = False
    payload = {
        'source': '赛训组组合池' if pool_active else index.get('source'),
        'poolActive': pool_active,
        'games': index.get('games'),
        'sinceYear': index.get('sinceYear'),
        'windowStart': index.get('windowStart'),
        'windowEnd': index.get('windowEnd'),
        'updatedAt': index.get('updatedAt'),
        'pairs': pairs_rows,
        'trios': trios_rows,
        'quads': [slim(row) for row in index['quads'].values()],
    }
    body = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
    if pool_rev is None and stamp is not None:
        _KPL_COMBOS_CACHE.update(key=cache_key, body=body)
        _report_disk_write(DATA_DIR / '.cache' / 'kpl-combos.json', key_id, 'body', body)
    return Response(content=body, media_type='application/json')


@router.get('/api/v3/camp/counters')
def camp_counters():
    """营地英雄克制 / 双排 / 三排关系（查询块用；克制命中卡走 bpFacts.counters）。"""
    data = bp_facts._camp_counters()
    if not data:
        return {'source': '', 'capturedAt': '', 'heroes': {}}
    return {'source': data.get('source'), 'capturedAt': data.get('capturedAt'),
            'heroes': data.get('heroes') or {}}


@router.get('/api/replay/{key:path}')
def replay(key: str, repo=Depends(repository)):
    detail = repo.match_detail(key)
    result = _panorama_cached(detail['bundleKey']) if detail and detail.get('bundleKey') else None
    if result is None:
        raise HTTPException(404, '该局没有全景回放数据')
    return {name: result[name] for name in _REPLAY_FIELDS if name in result}


_SAFE_KEY_RE = re.compile(r'^[A-Za-z0-9_:.\-]+$')


def _safe_key(value):
    """只允许单段文件名安全的 key，避免 `{key:path}` 造成路径穿越。"""
    text = str(value or '')
    if not text or text in ('.', '..') or not _SAFE_KEY_RE.match(text):
        return ''
    return text


def _load_camp_files(seq):
    """读营地回放的 positions.json / raw.json，带 mtime 缓存。

    跨局页每局都取一次位置：逐秒坐标文件几十 KB、raw.json 更大，没缓存时
    200 局就是几百次重复读盘解析。返回 (positions 解析结果, 短ID身份映射)。
    """
    folder = OFFICIAL / f'camp-{seq}'
    path = folder / 'positions.json'
    raw_path = folder / 'raw.json'
    try:
        sig = (path.stat().st_mtime if path.is_file() else 0.0,
               raw_path.stat().st_mtime if raw_path.is_file() else 0.0)
    except OSError:
        sig = (0.0, 0.0)
    cached = _POSITIONS_FILE_CACHE.get(seq)
    if cached is not None and cached[0] == sig:
        return cached[1], cached[2]
    data = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            data = {}
    identity_by_short = {}
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
        except (OSError, ValueError):
            identity_by_short = {}
    if len(_POSITIONS_FILE_CACHE) > 600:
        _POSITIONS_FILE_CACHE.clear()
    _POSITIONS_FILE_CACHE[seq] = (sig, data, identity_by_short)
    return data, identity_by_short


def _positions_for_key(key):
    """一局的十人逐秒位置（降采样后）。取不到返回 None，不抛错。

    通道 → 营地 gameSeq → data/official_replays/camp-<seq>/positions.json；
    玩家按 playerId 与通道里的营地十人面板对齐。降采样到每 `POSITION_STEP` 秒一点。
    输出按局缓存（数据代际失效），跨局页 200 局各取一次不再重复构造。
    """
    cached = _POSITIONS_OUT_CACHE.get(key)
    if cached is not None and cached[0] == _data_stamp:
        return cached[1]
    result = _positions_for_key_uncached(key)
    if result is not None:
        if len(_POSITIONS_OUT_CACHE) > 600:
            _POSITIONS_OUT_CACHE.clear()
        _POSITIONS_OUT_CACHE[key] = (_data_stamp, result)
    return result


def _positions_for_key_uncached(key):
    """一局的十人逐秒位置（降采样后）。取不到返回 None，不抛错。

    通道 → 营地 gameSeq → data/official_replays/camp-<seq>/positions.json；
    玩家按 playerId 与通道里的营地十人面板对齐。降采样到每 `POSITION_STEP` 秒一点。
    """
    # 对局 key 带 channel- 前缀，channels 表的 id 不带。
    channel_id = key[len('channel-'):] if key.startswith('channel-') else key
    camp, seq = {}, ''
    bundle_players = []
    if DB.is_file():
        camp = _channel_camp(channel_id)
        seq = str(camp.get('gameSeq') or '')
    if not seq:
        # 没有采集通道（例如演示数据包）时，直接按数据包里挂的 officialReplay 找位置
        safe_key = _safe_key(key)
        bundle_path = MATCHES / f'{safe_key}.json' if safe_key else None
        if bundle_path is None or not bundle_path.is_file():
            return None
        bundle = json.loads(bundle_path.read_text(encoding='utf-8'))
        linked = str(((bundle.get('match') or {}).get('officialReplay') or {}).get('id') or '')
        if linked:
            seq = linked[len('camp-'):] if linked.startswith('camp-') else linked
            bundle_players = bundle.get('players') or []
    seq = _safe_key(seq)
    if not seq:
        return None
    path = OFFICIAL / f'camp-{seq}' / 'positions.json'
    if not path.is_file():
        return None
    data, identity_by_short = _load_camp_files(seq)
    roster = {str(p.get('playerId')): p for p in (camp.get('players') or []) if p.get('playerId')}
    # 位置文件的 playerId 是营地短 ID（与 raw.matchInfo.playerId 同源），通道名单里
    # 存的是游戏内 playID（长 ID），两套 ID 对不上。用 matchInfo 的 heroName /
    # acntcamp 做桥：短 ID → 英雄名 + 阵营 → 通道名单里的 camp+slot+昵称。
    # （raw.json 的解析在 _load_camp_files 里带 mtime 缓存。）
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


@router.get('/api/positions/{key:path}')
def match_positions(key: str):
    result = _positions_for_key(key)
    if result is None:
        raise HTTPException(404, '这一局没有可用的位置数据')
    return result


@router.get('/api/cross/window')
def cross_window(batch: int = 0, size: int = 25, limit: int = 200,
                 repo=Depends(repository), values=Depends(filters)):
    """跨局页逐局明细的批量取数：一次带回一批「详情 + 位置 + 回放摘要」。

    逐局三接口各带 40ms 左右的请求开销，200 局就是 600 个请求、20 秒以上
    的排队收发；这里按批合并成十来个请求，取数逻辑与单局接口完全一致。
    """
    size = max(1, min(60, size))
    limit = max(1, min(400, limit))
    items = repo.matches(values)['matches'][:limit]
    part = items[batch * size:(batch + 1) * size]

    def one(item):
        key = item['key']
        detail = repo.match_detail(key)
        if not detail:
            return None
        replay = _panorama_cached(detail.get('bundleKey') or '') if detail.get('bundleKey') else None
        return {
            'key': key,
            'detail': detail,
            'replay': {name: replay[name] for name in _REPLAY_FIELDS if name in replay} if replay else None,
            'positions': _positions_for_key(key),
        }

    # 保持串行：试过批内并行，在 Windows 上会让进程硬崩（原因未明，表现为
    # 连接被重置、无 Python 异常）；缓存全热时串行一局约 35ms，一批 25 局
    # 一秒内，配合磁盘缓存与预热线程，热路径足够快。
    rows = [row for row in (one(item) for item in part) if row]
    payload = {'total': len(items), 'batch': batch, 'rows': rows}
    # 直接 dumps 返回：FastAPI 默认的 jsonable_encoder 会递归转换几十万个
    # 坐标点（每批 3–4 MB），比 dumps 本身慢一个数量级。
    return Response(content=json.dumps(payload, ensure_ascii=False, separators=(',', ':')),
                    media_type='application/json')


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
    return json_response({'draft': repo.bp_summary(values), 'heroes': repo.hero_stats(values)})


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
    return json_response({'opponents': result, 'unknown': unknown, 'warnings': warnings})


@router.get('/api/sources')
def sources(repo=Depends(repository), values=Depends(filters)):
    stats = repo.overview(values, include_top=False)
    return {
        **repo.sources(), 'quality': stats['dataQuality'], 'coverage': stats['coverage'],
        'inventory': stats['inventory'], 'scopeWarnings': stats['warnings'],
        'validationCount': sum(repo._is_seed_match(match) for match in repo.get()['matches']),
    }


_ICON_META_CACHE = {'stamp': None, 'payload': None}


def _icon_metadata():
    """图标目录 + 英雄分路标签：只读 resources/，不碰仓库快照。

    编组页只需要头像，不应该为了一份图标目录等快照重建（冷启动约 3 秒）。
    """
    catalog_path = ROOT / 'resources' / 'catalog.json'
    tags_path = ROOT / 'resources' / 'hero_tags.json'
    try:
        stamp = (catalog_path.stat().st_mtime_ns, tags_path.stat().st_mtime_ns)
    except OSError:
        stamp = (0, 0)
    if _ICON_META_CACHE['stamp'] == stamp and _ICON_META_CACHE['payload'] is not None:
        return _ICON_META_CACHE['payload']
    entries = json.loads(catalog_path.read_text(encoding='utf-8')).get('entries', []) \
        if catalog_path.is_file() else []
    # 赛训组英雄标签（resources/hero_tags.json，scripts/import_hero_tags.py 产物）：
    # 英雄 × 实际分路 → 该位置建议分类。十人面板的 10 分钟经济评级按它给打野
    # 分野核（800/分钟）与坦野（6800 总量）两套口径。
    hero_types = {}
    if tags_path.is_file():
        try:
            tags_doc = json.loads(tags_path.read_text(encoding='utf-8'))
            hero_types = {name: hero.get('lanes') or {}
                          for name, hero in (tags_doc.get('heroes') or {}).items()}
        except (OSError, ValueError):
            hero_types = {}
    payload = {
        'icons': {entry['name']: entry['icon'] for entry in entries
                  if entry.get('kind') == 'hero' and entry.get('name') and entry.get('icon')},
        'heroTypes': hero_types,
    }
    _ICON_META_CACHE.update(stamp=stamp, payload=payload)
    return payload


@router.get('/api/metadata/icons')
def metadata_icons():
    """编组页轻量元数据：头像目录 + 英雄分路标签，不依赖分析快照。"""
    return {**_icon_metadata(), 'iconsOnly': True}


@router.get('/api/metadata')
def metadata(repo=Depends(repository)):
    return {
        'teamName': repo.get()['teamName'], 'options': repo.filters(), 'demo': IS_DEMO,
        **_icon_metadata(),
    }


_demo_lock = Lock()
DEMO_APPLICATION = 'training-data-v3'
def _demo_port() -> int:
    """演示实例的端口：默认跟着主端口走（8766 → 8773），可用 KPL_DEMO_PORT 覆盖。

    以前写死 8773，主端口换成 9000 时演示实例仍占 8773，看起来就像"端口一直在变"。
    """
    override = os.environ.get('KPL_DEMO_PORT', '').strip()
    if override:
        try:
            return int(override)
        except ValueError:
            pass
    try:
        return int(os.environ.get('TRAINING_PORT', '8766')) + 7
    except ValueError:
        return 8773


DEMO_PORT = _demo_port()


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
            try:
                os.replace(entry, target)
            except PermissionError:
                # 被占用时再强制删旧文件；正常路径不先删，避免中途丢文件。
                if target.exists():
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
            raise HTTPException(409, f'演示端口 {DEMO_PORT} 已被其他程序占用。')
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


# ---------------------------------------------------------------------------
# 回放深度分析（空间 / 经济）：把 official_replays 的 330 份回放逐份聚合。
# 冷跑空间 2.4 秒、经济 0.6 秒，但结果只取决于回放文件、营地面板与地图标定，
# 和页面、筛选、登录状态都无关，所以按文件指纹缓存并落盘一份：重启后首次进页
# 直接读盘，不再把这几秒算在「打开页面」上。
_DEEP_SCHEMA = 1
_DEEP_CACHE = {}
_DEEP_CACHE_MAX = 6
_DEEP_STAMP_TTL = 2.0
_DEEP_STAMP = {'at': float('-inf'), 'value': None}
_DEEP_DISK = DATA_DIR / '.cache' / 'deep-analysis.json'
_DEEP_DISK_STATE = {'loaded': False, 'stamp': None, 'values': {}}


def _dir_fingerprint(path):
    """目录的 (文件数, 最新 mtime)：新增/改动一局就会换指纹。"""
    try:
        count, latest = 0, 0
        for item in path.iterdir():
            try:
                latest = max(latest, item.stat().st_mtime_ns)
            except OSError:
                continue
            count += 1
        return [count, latest]
    except OSError:
        return [0, 0]


def _deep_stamp():
    """回放目录 + 营地目录 + 地图标定的联合指纹，2 秒内复用同一次扫描。"""
    now = monotonic()
    if now - _DEEP_STAMP['at'] < _DEEP_STAMP_TTL:
        return _DEEP_STAMP['value']
    calibration = DB.parent / 'map_calibration.json'
    try:
        calibrated = calibration.stat().st_mtime_ns
    except OSError:
        calibrated = 0
    value = [_dir_fingerprint(OFFICIAL), _dir_fingerprint(DB.parent / 'camp_details'),
             calibrated]
    _DEEP_STAMP.update(at=now, value=value)
    return value


def _deep_stamp_id():
    return json.dumps(_deep_stamp(), ensure_ascii=False, separators=(',', ':'))


def _deep_disk_load(stamp_id):
    state = _DEEP_DISK_STATE
    if not state['loaded']:
        state['loaded'] = True
        try:
            doc = json.loads(_DEEP_DISK.read_text(encoding='utf-8'))
            if isinstance(doc, dict) and isinstance(doc.get('values'), dict):
                state['stamp'] = doc.get('stamp')
                state['values'] = doc['values']
        except (OSError, ValueError):
            pass
    if state['stamp'] == stamp_id:
        return state['values']
    return {}


def _deep_disk_save(stamp_id, values):
    state = _DEEP_DISK_STATE
    try:
        _DEEP_DISK.parent.mkdir(parents=True, exist_ok=True)
        tmp = _DEEP_DISK.with_suffix('.tmp')
        tmp.write_text(json.dumps({'stamp': stamp_id, 'values': values},
                                  ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        os.replace(tmp, _DEEP_DISK)
        state.update(loaded=True, stamp=stamp_id, values=values)
    except (OSError, TypeError, ValueError):
        pass


def _deep_analysis(name, build):
    """按（名字, schema, 文件指纹）缓存一份深度分析结果，并顺手落盘。"""
    stamp_id = _deep_stamp_id()
    key = (name, _DEEP_SCHEMA, stamp_id)
    cached = _DEEP_CACHE.get(key)
    if cached is not None:
        return cached
    persisted = _deep_disk_load(stamp_id).get(name)
    if persisted is not None:
        _DEEP_CACHE[key] = persisted
        return persisted
    value = build()
    if len(_DEEP_CACHE) >= _DEEP_CACHE_MAX:
        _DEEP_CACHE.clear()
    _DEEP_CACHE[key] = value
    values = dict(_DEEP_DISK_STATE['values'] if _DEEP_DISK_STATE['stamp'] == stamp_id else {})
    values[name] = value
    _deep_disk_save(stamp_id, values)
    return value


@router.get('/api/v3/space')
def spatial_analysis():
    return _deep_analysis(
        'space', lambda: deep_analysis.space(OFFICIAL, DB.parent / 'camp_details', DB.parent))


@router.get('/api/v3/economy')
def economy_analysis():
    return _deep_analysis(
        'economy', lambda: deep_analysis.economy(OFFICIAL, DB.parent / 'camp_details'))


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
            # 一个昵称可能对应多个营地账号（小号/改名前后的号）：第一个账号
            # 建/找好选手后，后面的账号必须挂到同一个选手，不能因为没传
            # team_id 在第二次调用时要求「选择所属战队」而半途失败。
            target_player = body.get('playerId') if index == 0 else (
                saved[0]['playerId'] if saved else None)
            saved.append(identity_service.name_account(
                DB, account_id=account, nickname=nickname, positions=positions or None,
                player_id=target_player,
                name=name, position=position,
                team_id=team_id if index == 0 else '', team_name=team_name,
                default_team_id=default_team_id, actor='coach'))
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


@router.get('/api/v3/identity/players')
def identity_players(team_id: str = ''):
    """选手ID 清单：认领时跨战队选人用。

    和 `identity/accounts` 是同一份主数据的两面：那边一行一个游戏账号，
    这边一行一个选手ID（一个ID可以挂多个游戏名，也就是小号/改名前后的号）。
    """
    import workspace_store
    try:
        players = workspace_store.Workspace(DB).list_players(team_id or None)
    except sqlite3.Error:
        players = []
    mapping = camp_accounts()
    accounts = Counter()
    for item in mapping.values():
        if item.get('playerId'):
            accounts[item['playerId']] += 1
    teams = _identity_teams()
    team_names = {team['id']: team['name'] for team in teams}
    return {
        'players': [{
            'id': player['id'],
            'name': player.get('name') or '',
            'teamId': player.get('team_id') or '',
            'teamName': team_names.get(player.get('team_id') or '', ''),
            'position': player.get('position') or '',
            'positions': player.get('positions') or [],
            'role': player.get('role') or '',
            'accounts': accounts.get(player['id'], 0),
        } for player in players],
        'teams': teams,
    }


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
    if not key or len(key) > 200:
        raise HTTPException(404, '找不到该场对局')
    body = await read_json(request)
    if not isinstance(body, dict):
        raise HTTPException(400, '数据格式无效')
    # 标签/备注是覆盖层，周期简报里的局不一定进了 v3 的对局快照；
    # 只写这两项时按 key 落库，其他补录字段仍必须在 v3 里找得到这一局。
    tag_only = set(body).issubset({'tags', 'tagNotes'})
    if not tag_only and repo.match_detail(key) is None:
        raise HTTPException(404, '找不到该场对局')
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
    # 单局标签：教练自己写的，存在覆盖层 tags 字段里；首页/档案/单局页共用同一份。
    tags = body.get('tags')
    if tags is not None:
        if not isinstance(tags, list):
            raise HTTPException(400, '标签必须是数组')
        if len(tags) > TAG_LIMIT:
            raise HTTPException(400, f'一局最多 {TAG_LIMIT} 个标签')
        cleaned = []
        for raw in tags:
            if not isinstance(raw, str):
                raise HTTPException(400, '标签必须是文本')
            text = raw.strip()
            if not text:
                continue
            if len(text) > TAG_MAX_LEN:
                raise HTTPException(400, f'单个标签不超过 {TAG_MAX_LEN} 个字')
            if text not in cleaned:
                cleaned.append(text)
        patch['tags'] = cleaned
    # 备注绑定在「标签 ↔ 对局」这条关联上：同一个标签在不同局可以写不同的原因。
    notes = body.get('tagNotes')
    if notes is not None:
        if not isinstance(notes, dict) or len(notes) > TAG_LIMIT:
            raise HTTPException(400, '标签备注格式无效')
        clean_notes = {}
        for name, note in notes.items():
            tag = str(name or '').strip()
            if not tag or len(tag) > TAG_MAX_LEN:
                raise HTTPException(400, '标签备注的标签名无效')
            note = str(note or '').strip()
            if len(note) > 200:
                raise HTTPException(400, '标签备注不超过 200 个字')
            if note:
                clean_notes[tag] = note
        patch['tagNotes'] = clean_notes
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
        # 备注跟着关联走：标签从这局删掉时，它的备注也一起消失。
        alive = set(previous.get('tags') or [])
        if isinstance(previous.get('tagNotes'), dict):
            previous['tagNotes'] = {k: v for k, v in previous['tagNotes'].items() if k in alive}
        connection.execute('INSERT INTO match_meta(match_key,body,updated_at) VALUES(?,?,?) ON CONFLICT(match_key) DO UPDATE SET body=excluded.body,updated_at=excluded.updated_at',
                           (key,json.dumps(previous,ensure_ascii=False),time.time()))
    return {'ok': True, 'meta': previous}


@router.post('/api/v3/opponent-team')
async def save_opponent_team(request: Request, repo=Depends(repository)):
    """对局界面给对手改名：归到战队主数据，并回链这一局。

    对局档案里点铅笔改对手名时，若这局已归到某支战队（营地面板或此前建档），
    改的是那支战队的队名，战队页与其它对局一起更新；若还没归队，就按新名字
    建一支战队并把这一局挂上去。这样对局与战队的改名是同一条链，不再各写各的。
    """
    body = await read_json(request)
    if not isinstance(body, dict):
        raise HTTPException(400, '数据格式无效')
    key = str(body.get('key') or '').strip()
    name = str(body.get('opponent') or '').strip()
    if not key or len(key) > 200:
        raise HTTPException(404, '找不到该场对局')
    if not name or len(name) > 50:
        raise HTTPException(400, '战队名不能为空且不超过 50 个字')
    match = repo.match_detail(key)
    if match is None:
        raise HTTPException(404, '找不到该场对局')

    import opponent_identity
    resolved = opponent_identity.resolve_names(DB)
    names = resolved.get('names') or {}
    aliases = resolved.get('aliases') or {}

    with sqlite3.connect(DB) as connection:
        connection.execute('CREATE TABLE IF NOT EXISTS match_meta '
                           '(match_key TEXT PRIMARY KEY, body TEXT NOT NULL, updated_at REAL NOT NULL)')
        row = connection.execute('SELECT body FROM match_meta WHERE match_key=?', (key,)).fetchone()
        try:
            meta = json.loads(row[0]) if row else {}
            if not isinstance(meta, dict):
                meta = {}
        except (ValueError, TypeError):
            meta = {}

    # 归属优先级：已建档的回链 > 营地面板归属 > 当前队名/旧名匹配。
    team_id = str(meta.get('opponentTeamId') or '').strip() or str(match.get('opponentTeamId') or '').strip()
    if not team_id:
        current = str(match.get('opponent') or meta.get('opponent') or '').strip()
        target = aliases.get(current, current)
        if target in names.values():
            team_id = next((tid for tid, value in names.items() if value == target), '')
        elif current in names.values():
            team_id = next((tid for tid, value in names.items() if value == current), '')

    if team_id and team_id in names:
        try:
            identity_service.rename_team(DB, team_id, name=name)
        except ValueError as error:
            raise HTTPException(400, str(error))
        result_id = team_id
    else:
        # 新队名恰好已经存在：直接挂过去，不重复建队。
        existing = next((tid for tid, value in names.items() if value == name), '')
        try:
            if existing:
                result_id = existing
            else:
                result_id = identity_service.save_team(DB, name=name, actor='coach')['id']
        except ValueError as error:
            raise HTTPException(400, str(error))

    meta['opponent'] = name
    meta['opponentTeamId'] = result_id
    with sqlite3.connect(DB) as connection:
        connection.execute('INSERT INTO match_meta(match_key,body,updated_at) VALUES(?,?,?) '
                           'ON CONFLICT(match_key) DO UPDATE SET body=excluded.body,updated_at=excluded.updated_at',
                           (key, json.dumps(meta, ensure_ascii=False), time.time()))
    invalidate_snapshot()
    # 只清快照不够：opponent_identity 自己还有 5 秒解析缓存，
    # 不清它改名后别处仍把旧队名折回来（测试与真实页面都会看到旧名）。
    opponent_identity.clear_cache()
    invalidate_players_cache()
    return {'ok': True, 'key': key, 'teamId': result_id, 'name': name,
            'linked': bool(team_id)}


@router.get('/api/v3/match-tags')
def match_tags(repo=Depends(repository)):
    """单局标签一览：每局挂了什么、以及用过的标签和局数。

    首页复盘卡、对局档案、单局复盘页三个入口共用这一份；写入口走得还是
    /api/v3/match-meta，标签只是 match_meta 覆盖层里的一个字段。
    另外给「标签查询」附带每局的日期/对手（labels），这样查到标签后能直接
    列出「哪几局」，而不用前端再拉一次完整的对局列表。
    """
    try:
        with sqlite3.connect(DB) as connection:
            rows = connection.execute('SELECT match_key, body FROM match_meta').fetchall()
    except sqlite3.Error:
        rows = []
    by_match = {}
    counts = {}
    notes = {}
    for key, body in rows:
        try:
            parsed = json.loads(body)
        except (TypeError, ValueError):
            continue
        if not isinstance(parsed, dict):
            continue
        raw = parsed.get('tags')
        if not isinstance(raw, list):
            continue
        cleaned = [str(tag).strip() for tag in raw if str(tag).strip()]
        if not cleaned:
            continue
        by_match[str(key)] = cleaned
        raw_notes = parsed.get('tagNotes')
        if isinstance(raw_notes, dict):
            notes[str(key)] = {str(k): str(v) for k, v in raw_notes.items()
                               if str(k) in cleaned and str(v).strip()}
        for tag in cleaned:
            counts[tag] = counts.get(tag, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    # 标签查询结果的展示名：优先「日期 · 对阵 X」，没日期就用标题，都没有退回 key。
    labels = {}
    search = {}
    try:
        snapshot = repo.get()
        for match in list(snapshot.get('matches') or []) + list(snapshot.get('sheetMatches') or []):
            key = str(match.get('key') or '')
            if not key:
                continue
            date = str(match.get('dateText') or match.get('date') or '').strip()
            opponent = str(match.get('opponent') or '').strip()
            title = str(match.get('title') or '').strip()
            parts = [date]
            if opponent:
                parts.append(f'对阵 {opponent}')
            if title and title not in parts:
                parts.append(title)
            labels[key] = ' · '.join(p for p in parts if p) or key
            search[key] = {
                'date': date,
                'opponent': opponent,
                'heroes': [str(h) for h in (match.get('heroes') or []) if str(h).strip()],
            }
    except Exception:
        labels, search = {}, {}
    return {
        'ok': True,
        'byMatch': by_match,
        'notes': notes,
        'search': search,
        'tags': [{'name': name, 'count': count} for name, count in ordered],
        'labels': labels,
        'limit': TAG_LIMIT,
        'maxLength': TAG_MAX_LEN,
    }


def _mutate_match_tags(mutator):
    """在 match_meta 覆盖层上批量改名/删除/打标签，保持 tags 与 tagNotes 同步。"""
    import time
    changed = 0
    with sqlite3.connect(DB) as connection:
        connection.execute('CREATE TABLE IF NOT EXISTS match_meta (match_key TEXT PRIMARY KEY, body TEXT NOT NULL, updated_at REAL NOT NULL)')
        connection.execute('BEGIN IMMEDIATE')
        rows = connection.execute('SELECT match_key, body FROM match_meta').fetchall()
        for key, body in rows:
            try:
                meta = json.loads(body)
            except (TypeError, ValueError):
                continue
            if not isinstance(meta, dict):
                continue
            tags = meta.get('tags')
            if not isinstance(tags, list):
                continue
            before = list(tags)
            notes = meta.get('tagNotes') if isinstance(meta.get('tagNotes'), dict) else {}
            next_tags, next_notes = mutator(before, notes)
            next_tags = [str(tag).strip() for tag in next_tags if str(tag).strip()][:TAG_LIMIT]
            if next_tags == before:
                continue
            meta['tags'] = next_tags
            meta['tagNotes'] = {k: v for k, v in next_notes.items() if k in next_tags}
            connection.execute('UPDATE match_meta SET body=?, updated_at=? WHERE match_key=?',
                               (json.dumps(meta, ensure_ascii=False), time.time(), key))
            changed += 1
    return changed


@router.post('/api/v3/tags/rename')
async def rename_match_tag(request: Request):
    """标签改名：所有挂过它的对局一起改，备注跟着迁移。"""
    body = await read_json(request)
    old = str((body or {}).get('from') or '').strip()
    new = str((body or {}).get('to') or '').strip()
    if not old or not new or len(new) > TAG_MAX_LEN:
        raise HTTPException(400, '标签名无效')
    if old == new:
        return {'ok': True, 'changed': 0}

    def mutate(tags, notes):
        renamed = [new if tag == old else tag for tag in tags]
        deduped = []
        for tag in renamed:
            if tag not in deduped:
                deduped.append(tag)
        moved = {k: v for k, v in notes.items()}
        if old in moved:
            moved[new] = moved.pop(old)
        return deduped, moved

    return {'ok': True, 'changed': _mutate_match_tags(mutate)}


@router.post('/api/v3/tags/delete')
async def delete_match_tag(request: Request):
    """删除标签：从所有对局摘掉，备注一起清掉，不动其它标签。"""
    body = await read_json(request)
    name = str((body or {}).get('name') or '').strip()
    if not name:
        raise HTTPException(400, '标签名无效')

    def mutate(tags, notes):
        return [tag for tag in tags if tag != name], {k: v for k, v in notes.items() if k != name}

    return {'ok': True, 'changed': _mutate_match_tags(mutate)}


@router.post('/api/v3/tags/bulk')
async def bulk_match_tags(request: Request):
    """批量打标签：教练选一批局，一次性加同一个标签；已有标签不会重复。"""
    body = await read_json(request)
    keys = [str(key).strip() for key in ((body or {}).get('keys') or []) if str(key).strip()]
    add = str((body or {}).get('add') or '').strip()
    remove = str((body or {}).get('remove') or '').strip()
    if not keys or len(keys) > 200 or not add and not remove:
        raise HTTPException(400, '批量打标签的参数无效')
    if add and len(add) > TAG_MAX_LEN:
        raise HTTPException(400, f'单个标签不超过 {TAG_MAX_LEN} 个字')

    def mutate(tags, notes):
        next_tags = [tag for tag in tags if tag != remove] if remove else list(tags)
        if add and add not in next_tags:
            next_tags.append(add)
        return next_tags, notes

    changed = 0
    import time
    for key in keys:
        with sqlite3.connect(DB) as connection:
            connection.execute('CREATE TABLE IF NOT EXISTS match_meta (match_key TEXT PRIMARY KEY, body TEXT NOT NULL, updated_at REAL NOT NULL)')
            row = connection.execute('SELECT body FROM match_meta WHERE match_key=?', (key,)).fetchone()
            try:
                meta = json.loads(row[0]) if row else {}
            except (TypeError, ValueError):
                meta = {}
            if not isinstance(meta, dict):
                meta = {}
            next_tags, notes = mutate(list(meta.get('tags') or []),
                                      meta.get('tagNotes') if isinstance(meta.get('tagNotes'), dict) else {})
            next_tags = next_tags[:TAG_LIMIT]
            meta['tags'] = next_tags
            meta['tagNotes'] = {k: v for k, v in notes.items() if k in next_tags}
            connection.execute('INSERT INTO match_meta(match_key,body,updated_at) VALUES(?,?,?) ON CONFLICT(match_key) DO UPDATE SET body=excluded.body,updated_at=excluded.updated_at',
                               (key, json.dumps(meta, ensure_ascii=False), time.time()))
            changed += 1
    return {'ok': True, 'changed': changed}


@router.post('/api/v3/match-meta-bulk')
async def update_match_meta_bulk(request: Request, repo=Depends(repository)):
    """批量写对手队名：给一批局的覆盖层补同一个字段。

    教练的真实流程是「今天打的这一批都是同一个对手」——逐局点铅笔要 105 次。
    只支持 opponent 一个字段，其余补录仍走单局接口，避免误伤。
    """
    import time
    body = await read_json(request)
    if not isinstance(body, dict):
        raise HTTPException(400, '数据格式无效')
    keys = body.get('keys')
    if not isinstance(keys, list) or not keys or len(keys) > 600:
        raise HTTPException(400, '对局列表无效')
    if not all(isinstance(key, str) and 0 < len(key) <= 200 for key in keys):
        raise HTTPException(400, '对局列表无效')
    opponent = body.get('opponent')
    if not isinstance(opponent, str) or len(opponent.strip()) > 50:
        raise HTTPException(400, '队名格式或长度不正确')
    opponent = opponent.strip()
    if not opponent:
        raise HTTPException(400, '请填写对手队名；要清空请逐局编辑')
    existing = {m.get('key') for m in repo.matches({'sources': [], 'excludeSeeds': False}).get('matches', [])}
    targets = [key for key in dict.fromkeys(keys) if key in existing]
    if not targets:
        raise HTTPException(404, '这些对局都不在当前数据里')
    stamp = time.time()
    updated = 0
    with sqlite3.connect(DB) as connection:
        connection.execute('CREATE TABLE IF NOT EXISTS match_meta (match_key TEXT PRIMARY KEY, body TEXT NOT NULL, updated_at REAL NOT NULL)')
        connection.execute('BEGIN IMMEDIATE')
        for key in targets:
            row = connection.execute('SELECT body FROM match_meta WHERE match_key=?', (key,)).fetchone()
            try:
                previous = json.loads(row[0]) if row else {}
                if not isinstance(previous, dict): previous = {}
            except (ValueError, TypeError):
                previous = {}
            previous['opponent'] = opponent
            connection.execute('INSERT INTO match_meta(match_key,body,updated_at) VALUES(?,?,?) ON CONFLICT(match_key) DO UPDATE SET body=excluded.body,updated_at=excluded.updated_at',
                               (key, json.dumps(previous, ensure_ascii=False), stamp))
            updated += 1
    return {'ok': True, 'updated': updated, 'skipped': len(keys) - updated}


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
    # 与 bp_board 共用同一份营地指纹：改一局 BP 或合并战队后自动重算。
    stamp = bp_board_stamp()
    if stamp[0] is not None:
        cached = _TEAM_BP_CACHE.get(stamp)
        if cached is not None:
            return cached
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
    payload = {'teams': teams}
    if stamp[0] is not None:
        if len(_TEAM_BP_CACHE) >= _TEAM_BP_CACHE_MAX:
            _TEAM_BP_CACHE.clear()
        _TEAM_BP_CACHE[stamp] = payload
    return payload


@router.get('/api/v3/team-deep')
def team_deep(team: str = ''):
    """战队页 v2 的逐局全量数据（docs/team_page_v2.md §2.2）。

    战队 id 来自 studio/teams 的聚类结果；不存在给 404，不返回空壳让前端误以为有数据。
    """
    import team_clusters
    camp_dir = MATCHES.parent / 'camp_details'
    deep = team_clusters.team_deep(camp_dir, DB, team)
    if deep is None:
        raise HTTPException(404, '战队不存在：没有匹配的营地十人面板。')
    return deep


def _roster_entry(player):
    """营地逐人面板 → BP 诊断可用的选手统计；缺失字段保留 None。"""
    return {key: player.get(key) for key in
            ('name', 'hero', 'lane', 'kills', 'deaths', 'assists', 'gold',
             'heroDamage', 'taken', 'participation', 'towers')}


# BP 沙盘 / 教练档案 / 周期监控 / 对手打法共用同一份「营地面板 → 逐局 BP」汇总：
# 104 个 battleDetail 的解析 + 聚类约 2 秒，过去这几个接口各自重算一遍。
# 按（营地目录, 对局包 + DB）指纹缓存：营地新增/改 BP、队名合并、教练改名都会
# 换 key。缓存对象只读，调用方不得原地修改（下面几个接口都是只读消费）。
_BP_BOARD_CACHE = {}
_BP_BOARD_CACHE_MAX = 4

# 战队 BP 名单同样按营地指纹缓存：与 bp_board 读的是同一批 battleDetail。
_TEAM_BP_CACHE = {}
_TEAM_BP_CACHE_MAX = 4

# 选手板块聚合按同一指纹缓存（1.3 MB 的 board，纯 CPU 0.4 秒），并落盘一份：
# 重启后第一次打开选手档案不用再付这 1.6 秒。
_PLAYERS_BOARD_CACHE = {}
_PLAYERS_BOARD_CACHE_MAX = 3
# 身份口径变化（例如补齐 enemy 昵称池）必须让旧磁盘缓存失效。
_PLAYERS_BOARD_CACHE_VERSION = 3  # v3: 分均经济/输出/承伤统一为 Σ总量÷Σ分钟
_PLAYERS_BOARD_DISK = _CACHE_DIR / 'players-board.json'

# 训练台账（按对手归集的排期 + 交手日）同样按营地指纹缓存。
_TEAM_TRAINING_CACHE = {}
_TEAM_TRAINING_CACHE_MAX = 3


def bp_board_stamp():
    """营地目录 + 对局包/DB 的联合指纹，BP 汇总类缓存的统一失效口径。"""
    return (_camp_dir_stamp(MATCHES.parent / 'camp_details'), _dataset_stamp())


def _card_team_by_seq():
    """营地 seq → 赛训组建卡 / 匹配页确认的对手战队卡。

    BP 页以前只按营地五人阵容签名聚类：同一个对手换个人就变成一支新队，
    赛训组在「对方战队」建的卡、匹配页归档时确认的对手卡完全没被读到。
    这里按 channels.body.match.gameSeq → match_meta.opponentTeamId /
    match_records.enemy_team_id 反查，把权威战队卡带进 BP 口径。
    """
    # 与战队分析 / 对手归属页共用同一份解析，避免 BP 与其它功能各读一套口径。
    try:
        import team_clusters
        return team_clusters.card_team_by_seq(DB)
    except Exception:  # noqa: BLE001 - 解析失败时退回空的权威映射
        return {}


@router.get('/api/v3/bp-board')
def bp_board_report():
    return json_response(bp_board())


def bp_board():
    """BP 模块基础数据：终局名单、已知选手，以及经过验证的 BP 顺序事件。

    旧营地记录可能只有最终选禁名单；新采集流程若提供 draftEvents，
    透传给研究引擎逐手校验后使用，不从名单反推顺序。
    """
    import team_clusters
    from bp_camp import parse_camp_bp
    import team_style
    stamp = bp_board_stamp()
    if stamp[0] is not None:
        cached = _BP_BOARD_CACHE.get(stamp)
        if cached is not None:
            return cached
    camp_dir = MATCHES.parent / 'camp_details'
    clusters = team_clusters.list_teams(camp_dir, DB)
    teams = clusters['teams']
    # 赛训组建的对手卡是权威：同一支队的阵容变动不该在 BP 页裂成多支占位队。
    cards = _card_team_by_seq()
    card_ids = {card['id'] for card in cards.values()}
    # 只有人工录入并核实的教练姓名才能用于执教档案。
    # 缺失时留空，不使用开发期的随机姓名填充。
    coach_of = {t['id']: (t.get('coach') or '') for t in teams}
    coach_of.update({card['id']: card.get('coach') or '' for card in cards.values()})
    seq_team = {seq: team for team in teams for seq in team.get('seqs', [])}
    # 营地 startTime 只有「MM-DD HH:MM」；按 team_style.resolve_days 推断年份
    # 补成 ISO 日期，才能与回放/DB 的 YYYY-MM-DD 做 BP↔过程匹配、时间过滤与
    # 前后段切分。推断不出时留空，绝不编造日期。
    panels = list(team_clusters.load_panels(camp_dir))
    day_of = team_style.resolve_days([p.get('start') or '' for p in panels])
    games, hero_meta = [], {}
    for panel in panels:
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
        card = cards.get(seq)
        if card:
            team = dict(team, id=card['id'], displayName=card['name'])
        start = panel.get('start') or ''
        resolved = day_of.get(start)
        day = resolved.isoformat() if resolved else ''
        result = panel.get('win')
        if result is None and bp.get('winnerSide'):
            result = bp['winnerSide'] == own
        hero_meta.update(bp.get('heroMeta') or {})

        def entries(kind, side, bp=bp):
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
            # Only actual patch labels, never derive version from calendar date.
            'version': (bp.get('version') or detail.get('version') or
                        (detail.get('data') or {}).get('version') or ''),
            'stage': bp.get('stage') or '',
            # Optional explicit scrim-only rule label from capture. Do not
            # attach this metadata to KPL games.
            'ruleProfile': (bp.get('ruleProfile') or
                            detail.get('ruleProfile') or
                            (detail.get('data') or {}).get('ruleProfile') or
                            'unknown'),
            'picks': {'own': entries('picks', own), 'enemy': entries('picks', enemy)},
            'bans': {'own': entries('bans', own), 'enemy': entries('bans', enemy)},
            # 顺序由营地每方名单 + 规则自动还原；名单数量不符时 pickOrderKnown=False。
            'banCount': bp.get('banCount') or {},
            'pickOrderKnown': bool(bp.get('pickOrderKnown')),
            'players': {'own': [p.get('name') for p in panel['own_roster']],
                        'enemy': [p.get('name') for p in panel['enemy_roster']]},
            # 选手与英雄仅以营地逐人 usedHero 的事实映射为依据，不按 Pick 顺序猜测。
            'roster': {
                'own': [_roster_entry(p) for p in panel['own_roster']],
                'enemy': [_roster_entry(p) for p in panel['enemy_roster']],
            },
            # 源头已写入的逐手事件，或由每侧名单 + 规则自动还原；没有就为空。
            'draftEvents': bp.get('draftEvents') or [],
            # 终局面板的经济 / 击杀 / 推塔 / 龙，供教练档案与 BP 页做资源口径；
            # 视角固定为「本队 = own」，前端按需要翻转成教练一方。
            'stats': {'own': (bp.get('teamStats') or {}).get(own) or {},
                      'enemy': (bp.get('teamStats') or {}).get(enemy) or {}},
        })
    games.sort(key=lambda g: g['start'], reverse=True)
    # 对手列表按权威战队卡归并：归档时确认成同一张卡的 27 局，不能再按
    # 阵容签名散成 13 个「待命名战队」。没有卡的局保留原来的聚类口径。
    by_seq = {game['key']: game for game in games}
    card_teams = {}
    for game in games:
        tid = game.get('teamId') or ''
        if tid not in card_ids:
            continue
        item = card_teams.setdefault(tid, {
            'id': tid, 'name': game['opponent'], 'coach': coach_of.get(tid, ''),
            'matches': 0, 'wins': 0, 'losses': 0, 'players': [], '_seen': set()})
        item['matches'] += 1
        if game.get('result') is True:
            item['wins'] += 1
        elif game.get('result') is False:
            item['losses'] += 1
        for name in ((game.get('players') or {}).get('enemy') or []):
            if name and name not in item['_seen']:
                item['_seen'].add(name)
                item['players'].append(name)
    for item in card_teams.values():
        item.pop('_seen', None)
        item['players'] = item['players'][:6]
    cluster_teams = []
    for cluster in teams:
        seqs = [seq for seq in cluster.get('seqs', []) if seq not in cards]
        if not seqs:
            continue
        cluster_teams.append({
            'id': cluster['id'], 'name': cluster['displayName'],
            'coach': coach_of.get(cluster['id'], ''),
            'matches': len(seqs),
            'wins': sum(1 for seq in seqs if by_seq.get(seq, {}).get('result') is True),
            'losses': sum(1 for seq in seqs if by_seq.get(seq, {}).get('result') is False),
            'players': [p.get('name') for p in cluster['players'][:6]]})
    payload = {
        'games': games,
        'teams': list(card_teams.values()) + cluster_teams,
        'heroMeta': hero_meta,
        'source': '营地终局名单 · 按规则自动还原（征召 18 / KPL 18|20 / 排位·巅峰 20）',
    }
    if stamp[0] is not None:
        if len(_BP_BOARD_CACHE) >= _BP_BOARD_CACHE_MAX:
            _BP_BOARD_CACHE.clear()
        _BP_BOARD_CACHE[stamp] = payload
    return payload


def _local_scrim_hero_catalog():
    """Repo-pinned hero names; no network or inferred hero identities."""
    path = ROOT / 'resources' / 'catalog.json'
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise HTTPException(503, '本地英雄词表不可用，无法校验 BP 候选。') from error
    items = payload.get('entries') or []
    heroes, icons = [], {}
    seen = set()
    for entry in items:
        if not isinstance(entry, dict) or entry.get('kind') != 'hero':
            continue
        name = str(entry.get('name') or '').strip()
        if not name or name in seen:
            continue
        seen.add(name)
        heroes.append(name)
        icon = str(entry.get('icon') or '')
        if re.fullmatch(r'/catalog/icons/hero-\d+\.png', icon):
            icons[name] = icon
    return {'heroes': heroes, 'icons': icons,
            'catalogUpdatedAt': payload.get('updatedAt') or ''}


@router.get('/api/v3/bp/rules')
def bp_rules_catalog():
    """BP 三格式的排程、身份口径与全局 BP 约束；前端不再自带 20 手模板。"""
    import bp_formats
    formats = []
    for fmt in (bp_formats.DRAFT_18, bp_formats.DRAFT_20,
                bp_formats.RANK_20, bp_formats.BLIND):
        formats.append({
            'id': fmt.id, 'title': fmt.title, 'modes': list(fmt.modes),
            'totalHands': fmt.total_hands,
            'bansPerSide': fmt.bans_per_side,
            'picksPerSide': fmt.picks_per_side,
            'globalBp': fmt.global_bp,
            'allowSharedBans': fmt.allow_shared_bans,
            'allowSharedPicks': fmt.allow_shared_picks,
            'pickIdentity': fmt.pick_identity,
            'banIdentity': fmt.ban_identity,
            'decider': fmt.decider,
            'deciderOverride': fmt.decider_override,
            'phases': [{'key': phase.key, 'action': phase.action,
                        'layout': phase.layout,
                        'steps': [{'camp': camp, 'count': count}
                                  for camp, count in phase.steps],
                        'counts': [{'camp': camp, 'count': count}
                                   for camp, count in phase.counts],
                        'total': phase.total()} for phase in fmt.phases],
            'schedule': fmt.schedule,
        })
    return {'default': bp_formats.DRAFT_18.id, 'formats': formats,
            'yuanliu': {'name': bp_formats.YUANLIU,
                        'forms': list(bp_formats.YUANLIU_FORMS),
                        'pickIdentity': 'canonical', 'banIdentity': 'form'}}


@router.get('/api/v3/bp-scrim/catalog')
def bp_scrim_catalog():
    """本地英雄词表 + 三格式排程；沙盘/BP 板共用，前端不再自带模板。"""
    import bp_formats
    data = _local_scrim_hero_catalog()
    return {**data, 'rule': bp_formats.DRAFT_18.id,
            'rules': [{'id': fmt.id, 'title': fmt.title,
                       'actions': fmt.total_hands,
                       'bansPerSide': fmt.bans_per_side['1'],
                       'picksPerSide': fmt.picks_per_side['1']}
                      for fmt in (bp_formats.DRAFT_18, bp_formats.DRAFT_20,
                                  bp_formats.RANK_20, bp_formats.BLIND)]}


@router.post('/api/v3/bp-scrim/next')
async def bp_scrim_next(request: Request):
    """按 ``rule``（draft-18 / draft-20）做逐手合法动作校验；不把训练赛规则套到 KPL。"""
    from bp_rules import scrim_state_payload
    payload = await read_json(request)
    if not isinstance(payload, dict):
        raise HTTPException(400, 'BP 请求必须是对象')
    if len(json.dumps(payload, ensure_ascii=False)) > 60000:
        raise HTTPException(413, 'BP 请求过大')
    try:
        return scrim_state_payload(payload, _local_scrim_hero_catalog()['heroes'])
    except (ValueError, TypeError, KeyError) as error:
        raise HTTPException(400, str(error)) from error


# KPL 源的情报报告按（数据指纹, 过滤参数）缓存：bp_games.jsonl 没变且参数相同
# 就复用上次完整研究结论，避免每次请求对 4702 局全量重算。训练赛源不缓存——
# 它依赖 repo 快照（15 秒窗口）与 camp_details 实时状态，必须反映最新录入。
_BP_INTEL_KPL_CACHE = {}
_BP_INTEL_KPL_CACHE_MAX = 8
# 训练赛源的同一份报告（营地汇总 + 过程匹配 + 监控 + 研究 + 头像）。
_BP_INTEL_SCRIM_CACHE = {}
_BP_INTEL_SCRIM_CACHE_MAX = 8


# BP 概览十区：按（数据指纹 + 全部筛选参数）缓存。KPL 首次全量聚合约 3 秒，
# 之后切队伍/窗口命中缓存；训练赛数据量小，同样按营地指纹缓存。
_BP_LAB_CACHE = {}
_BP_LAB_CACHE_MAX = 8
_BP_LAB_DISK = _CACHE_DIR / 'bp-lab.json'
_BP_LAB_LOOKUP_CACHE = {}
_BP_LAB_LOOKUP_CACHE_MAX = 16


def _kpl_source_stamp(kpl_bp):
    try:
        stat = kpl_bp.GAMES_PATH.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


# 监控报告按（camp_details 指纹, 过滤参数）缓存：教练反复切窗口/刷新时
# 不必每次重读全部营地面板。营地目录有新增/修改（指纹变化）自动失效。
_MONITOR_CACHE = {}
_MONITOR_CACHE_MAX = 12


def _camp_dir_stamp(camp_dir):
    """营地目录指纹（最新 mtime），同样带 2 秒 TTL；写入口会主动清掉。"""
    state = _CAMP_STAMP_STATE
    now = monotonic()
    if state['path'] == str(camp_dir) and now - state['at'] < _STAMP_TTL:
        return state['value']
    try:
        # 只取最大 mtime 会漏掉「新增/删除的不是最新文件」；带上数量和每个文件指纹。
        files = []
        for path in sorted(camp_dir.glob('*.json')):
            info = path.stat()
            files.append((path.name, info.st_mtime_ns, info.st_size))
        value = (len(files), tuple(files))
    except OSError:
        value = None
    state.update(path=str(camp_dir), at=now, value=value)
    return value


@router.get('/api/v3/monitor')
def monitor_report(request: Request):
    """周期异常监控：英雄/组合/选手/体系的窗口突变清单。"""
    from monitor import monitor as run_monitor, UNITS
    values = request.query_params
    unit = values.get('unit', 'week')
    if unit not in UNITS:
        raise HTTPException(400, '监控窗口必须是 day / week / month')
    player = str(values.get('player') or '').strip()
    camp_dir = MATCHES.parent / 'camp_details'
    # 指纹同时覆盖营地文件与 DB：对手命名/合并写的是 DB，不改营地文件，
    # 缓存键必须跟着变，否则归属完成后页面还会显示旧的「待命名战队」。
    stamp = (_camp_dir_stamp(camp_dir), _dataset_stamp())
    cache_key = (stamp, unit, player, values.get('from') or '', values.get('to') or '')
    cached = _MONITOR_CACHE.get(cache_key)
    if cached is not None:
        return cached
    try:
        report = run_monitor(bp_board()['games'], unit=unit,
                             date_from=(values.get('from') or '').strip() or None,
                             date_to=(values.get('to') or '').strip() or None)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    if player:
        # 选手个人页只要自己的英雄池变化条目，其余异常不必下发
        report['anomalies'] = [a for a in report['anomalies']
                               if a.get('kind') == 'player-pool' and a.get('object') == player]
        report['player'] = player
    if stamp is not None:
        if len(_MONITOR_CACHE) >= _MONITOR_CACHE_MAX:
            _MONITOR_CACHE.pop(next(iter(_MONITOR_CACHE)))
        _MONITOR_CACHE[cache_key] = report
    return report


# 对手打法按（营地指纹 + DB 指纹）缓存：对手命名/合并写 DB 会自动失效。
_TEAM_BEHAVIOR_CACHE = {}
_TEAM_BEHAVIOR_CACHE_MAX = 8


@router.get('/api/v3/team-behavior')
def team_behavior(repo=Depends(repository)):
    """对手打法习惯：阵容/阵营统计 + 对手视角经济检查点；证据缺失留空。"""
    from bp_process import link_scrim_process
    from opponent_behavior import opponent_behavior
    stamp = (_camp_dir_stamp(MATCHES.parent / 'camp_details'), _dataset_stamp())
    cached = _TEAM_BEHAVIOR_CACHE.get(stamp)
    if cached is not None:
        return cached
    rows = bp_board()['games']
    process_map = link_scrim_process(rows, repo.get()['matches'])
    report = opponent_behavior(rows, process_map)
    if stamp[0] is not None or stamp[1]:
        if len(_TEAM_BEHAVIOR_CACHE) >= _TEAM_BEHAVIOR_CACHE_MAX:
            _TEAM_BEHAVIOR_CACHE.pop(next(iter(_TEAM_BEHAVIOR_CACHE)))
        _TEAM_BEHAVIOR_CACHE[stamp] = report
    return report


@router.get('/api/v3/bp-intelligence')
def bp_intelligence_report(request: Request, repo=Depends(repository)):
    """BP 内置研究；严格匹配回放经济证据，避免跨局错配。"""
    from bp_intelligence import build_report
    from monitor import monitor as run_monitor
    from bp_process import link_scrim_process
    from bp_camp import hero_entry
    import kpl_bp
    import re

    values = request.query_params
    source = values.get('source', 'scrim')
    team = str(values.get('team') or '').strip()
    start = str(values.get('from') or '').strip()
    end = str(values.get('to') or '').strip()
    version = str(values.get('version') or '').strip()
    stage = str(values.get('stage') or '').strip()
    # 训练赛源过去每次请求都重跑「营地汇总 + 过程匹配 + 监控 + 研究 + 头像」，
    # 约 0.4 秒；它只取决于营地面板、对局包与筛选参数，和 KPL 源一样按指纹缓存。
    scrim_stamp = bp_board_stamp()
    scrim_key = (scrim_stamp, team, start, end, version, stage)
    if source != 'kpl' and scrim_stamp[0] is not None:
        scrim_cached = _BP_INTEL_SCRIM_CACHE.get(scrim_key)
        if scrim_cached is not None:
            return json_response(scrim_cached)
    try:
        panel_board = bp_board() if source == 'scrim' else None
        # 只按完整日期、双方 10 英雄、阵营与唯一匹配连接；对不上就留空。
        # 仅读仓库已有快照，绝不重新抓取回放或把队伍经济当个人对线经济。
        process_map = (link_scrim_process(panel_board['games'], repo.get()['matches'])
                       if panel_board else {})
        monitor_window = (run_monitor(panel_board['games'], unit='week') if panel_board else None)
        if source == 'kpl':
            stamp = _kpl_source_stamp(kpl_bp)
            cache_key = (stamp, team, start, end, version, stage)
            report = _BP_INTEL_KPL_CACHE.get(cache_key)
            if report is None:
                report = build_report([], kpl_bp.load_games(), source=source,
                                      team=team, start=start, end=end,
                                      version=version, stage=stage, process_map={})
                if stamp is not None:
                    if len(_BP_INTEL_KPL_CACHE) >= _BP_INTEL_KPL_CACHE_MAX:
                        _BP_INTEL_KPL_CACHE.pop(next(iter(_BP_INTEL_KPL_CACHE)))
                    _BP_INTEL_KPL_CACHE[cache_key] = report
        else:
            report = build_report(
                panel_board['games'] if panel_board else [],
                [],
                source=source,
                team=team,
                start=start,
                end=end,
                version=version,
                stage=stage,
                process_map=process_map,
                monitor_window=monitor_window,
            )
        # 头像仅用本机可验证的英雄图，避免 HTML 中嵌入任意远程 URL。
        heroes = set()
        for key in ('picks', 'bans'):
            heroes.update(row['hero'] for row in report[key])
        for key in ('pairs', 'trios'):
            for row in report[key]:
                heroes.update(row['heroes'])
        for row in report['players']:
            heroes.add(row['hero'])
        for row in report['responses']:
            heroes.add(row['trigger'])
            heroes.add(row['response'])
        for section in ('matchups', 'twoStep'):
            for row in (report.get('bpStudies') or {}).get(section) or []:
                if section == 'matchups':
                    heroes.update(row['enemyCore'])
                    heroes.add(row['candidate'])
                else:
                    heroes.add(row['trigger'])
                    for branch in row['branches']:
                        heroes.add(branch['ownPick'])
                        heroes.add(branch['enemyNext'])
        for row in (report.get('bpStudies') or {}).get('draft', {}).get('rounds', []):
            heroes.add(row['hero'])
        for row in (report.get('bpStudies') or {}).get('version', {}).get('changes', []):
            heroes.add(row['hero'])
        # Multi-round explorer includes long-tail Ban/Pick heroes beyond the
        # top-24 aggregate tables; resolve their local icons as well.
        for node in (report.get('bpStudies') or {}).get('draftTree', {}).get('nodes', []):
            if node.get('hero'):
                heroes.add(node['hero'])
        for context in (report.get('bpStudies') or {}).get('nextPickPolicy', {}).get('contexts', []):
            heroes.add(context['opponentHero'])
            heroes.update(pick['hero'] for pick in context['options'])
        icons = {}
        if panel_board:
            for hero, item in (panel_board.get('heroMeta') or {}).items():
                url = (item or {}).get('icon') or ''
                if hero in heroes and re.fullmatch(r'/catalog/icons/hero-\d+\.png', url):
                    icons[hero] = url
        for hero in heroes:
            if hero in icons:
                continue
            url = (hero_entry(hero) or {}).get('icon') or ''
            if re.fullmatch(r'/catalog/icons/hero-\d+\.png', url):
                icons[hero] = url
        report['icons'] = icons
        if source != 'kpl' and scrim_stamp[0] is not None:
            if len(_BP_INTEL_SCRIM_CACHE) >= _BP_INTEL_SCRIM_CACHE_MAX:
                _BP_INTEL_SCRIM_CACHE.pop(next(iter(_BP_INTEL_SCRIM_CACHE)))
            _BP_INTEL_SCRIM_CACHE[scrim_key] = report
        return json_response(report)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@router.get('/api/v3/bp-lab')
def bp_lab_report(request: Request):
    """BP 概览十区：英雄、组合、对抗、对手习惯、演变、稳定性与赛前方案。

    数据源严格分开：KPL（可含挑战者杯）与训练赛各自归一化、各自算胜率；
    不把训练赛的终局名单冒充逐手顺序，也不从日期推断版本。
    """
    from bp_lab import build_report
    import kpl_bp

    values = request.query_params
    source = str(values.get('source') or 'kpl').strip()
    if source not in ('kpl', 'scrim'):
        raise HTTPException(400, 'source 只能是 kpl 或 scrim')
    league = str(values.get('league') or 'all').strip()
    if league not in ('all', 'kpl', 'challenger'):
        raise HTTPException(400, 'league 只能是 all / kpl / challenger')
    team = str(values.get('team') or '').strip()
    opponent = str(values.get('opponent') or '').strip()
    start = str(values.get('from') or '').strip()
    end = str(values.get('to') or '').strip()
    unit = str(values.get('unit') or ('day' if source == 'scrim' else 'month')).strip()
    if unit not in ('day', 'month', 'season', 'stage'):
        raise HTTPException(400, 'unit 只能是 day / month / season / stage')
    target = [part.strip() for part in str(values.get('target') or '').split(',') if part.strip()]
    combo = [part.strip() for part in str(values.get('combo') or '').split(',') if part.strip()]
    rule = str(values.get('rule') or 'draft-18').strip()
    bo = str(values.get('bo') or 'BO5').strip()
    try:
        recent_days = int(values.get('recentDays') or 30)
    except (TypeError, ValueError):
        raise HTTPException(400, 'recentDays 必须是整数')
    if recent_days not in (7, 15, 30):
        raise HTTPException(400, 'recentDays 只能是 7 / 15 / 30')

    stamp = (_kpl_source_stamp(kpl_bp) if source == 'kpl'
             else (_camp_dir_stamp(MATCHES.parent / 'camp_details'), _dataset_stamp()))
    cache_key = (stamp, source, league, team, opponent, start, end,
                 unit, tuple(target), tuple(combo), rule, bo, recent_days)
    cached = _BP_LAB_CACHE.get(cache_key)
    if cached is not None:
        return json_response(cached)
    key_id = _cache_key_id(cache_key)
    persisted = _report_disk_read(_BP_LAB_DISK, key_id, 'report')
    if persisted is not None:
        _BP_LAB_CACHE[cache_key] = persisted
        return json_response(persisted)
    try:
        games = _bp_lab_games(source, league, start, end)
        report = build_report(games, source=source, team=team, opponent=opponent,
                              unit=unit, target=target or None, combo=combo or None,
                              rule=rule, bo=bo, recent_days=recent_days)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    report['filters'] = {'source': source, 'league': league, 'team': team,
                         'opponent': opponent, 'from': start, 'to': end,
                         'unit': unit, 'target': target, 'combo': combo,
                         'rule': rule, 'bo': bo, 'recentDays': recent_days}
    if stamp is not None:
        if len(_BP_LAB_CACHE) >= _BP_LAB_CACHE_MAX:
            _BP_LAB_CACHE.pop(next(iter(_BP_LAB_CACHE)))
        _BP_LAB_CACHE[cache_key] = report
        _report_disk_write(_BP_LAB_DISK, key_id, 'report', report)
    return json_response(report)


# ── BP 工作台（2026-11 重做）：一份页面模型，KPL 与训练赛同题对照 ──────────
_BP_STUDIO_CACHE = {}
_BP_STUDIO_CACHE_MAX = 6
_BP_STUDIO_DISK = _CACHE_DIR / 'bp-studio.json'
# 页面模型加字段时递增，旧磁盘缓存自动失效。
_BP_STUDIO_VERSION = '2026-11-17-a'
_BP_STUDIO_TARGET_CACHE = {}
_BP_STUDIO_TARGET_CACHE_MAX = 24
# 类型博弈报告（英雄类型 × 手序 × BO × 核数），按数据指纹 + 全部筛选参数缓存。
_BP_STUDIO_TYPES_CACHE = {}
_BP_STUDIO_TYPES_CACHE_MAX = 16
_BP_STUDIO_TYPES_DISK = _CACHE_DIR / 'bp-studio-types.json'
_BP_STUDIO_COMBO_CACHE = {}
_BP_STUDIO_COMBO_CACHE_MAX = 24
_BP_STUDIO_RAW = {}
_BP_STUDIO_NORM = {}
_BP_STUDIO_SCRIM = {}


def _bp_studio_raw(leagues):
    """KPL 原始对局：先按赛季过滤，未选赛季 = 全库。按文件指纹缓存解析结果。"""
    import kpl_bp
    stamp = _kpl_source_stamp(kpl_bp)
    key = (stamp, str(leagues or ''))
    cached = _BP_STUDIO_RAW.get(key)
    if cached is not None:
        return cached
    raw = kpl_bp.load_games()
    wanted = [item.strip() for item in str(leagues or '').split(',') if item.strip()]
    if wanted:
        keep = set(wanted)
        raw = [game for game in raw if str(game.get('leagueId') or '') in keep]
    if stamp is not None:
        if len(_BP_STUDIO_RAW) > 8:
            _BP_STUDIO_RAW.clear()
        _BP_STUDIO_RAW[key] = raw
    return raw


def _bp_studio_kpl(leagues):
    """归一化后的 KPL 队-局行；同一份数据只归一化一次。"""
    from bp_intelligence import normalize_kpl
    import kpl_bp
    stamp = _kpl_source_stamp(kpl_bp)
    key = (stamp, str(leagues or ''))
    cached = _BP_STUDIO_NORM.get(key)
    if cached is not None:
        return cached
    games = normalize_kpl(_bp_studio_raw(leagues))
    if stamp is not None:
        if len(_BP_STUDIO_NORM) > 6:
            _BP_STUDIO_NORM.clear()
        _BP_STUDIO_NORM[key] = games
    return games


def _competition_window(competition_id):
    """赛事的训练起止（date/end_date，对应卡片「训练起始 / 训练结束」）；解析失败返回 None。"""
    if not competition_id or not DB.is_file():
        return None
    try:
        from workspace_store import Workspace
        competition = Workspace(DB).get_competition(competition_id)
        if not competition:
            return None
        from workspace_store import Workspace as W
        bounds = W._date_bounds(
            competition.get('date'),
            competition.get('end_date') or competition.get('date'))
        return bounds
    except Exception:  # noqa: BLE001 - 老库/IO 异常退回不过滤
        return None


def _bp_studio_scrim(window=None):
    from bp_intelligence import normalize_scrims
    stamp = (_camp_dir_stamp(MATCHES.parent / 'camp_details'), _dataset_stamp(), window or '')
    cached = _BP_STUDIO_SCRIM.get(stamp)
    if cached is not None:
        return cached
    rows = bp_board().get('games') or []
    games = normalize_scrims(rows)
    if window:
        lo, hi = window
        # 赛事域 P1-4：scrim 语料按当前赛事的训练起止收滤。
        # normalize_scrims 写入的日期字段是 date（_period 截成 YYYY-MM-DD），
        # 不是原始 bp_board 记录里的 day；按 day 收滤会把全部归一化对局都筛掉，
        # 于是选了赛事之后 BP 页永远显示「没有征召 18 手的 BP 记录」。
        games = [g for g in games
                 if (not lo or ((g.get('date') or g.get('day') or '') >= lo))
                 and (not hi or ((g.get('date') or g.get('day') or '') <= hi))]
    if len(_BP_STUDIO_SCRIM) > 4:
        _BP_STUDIO_SCRIM.clear()
    _BP_STUDIO_SCRIM[stamp] = games
    return games


def _team_icons():
    """战队队标：本机缓存目录 resources/icons/teams（scripts/sync_team_icons.py 生成）。"""
    path = ROOT / 'resources' / 'icons' / 'teams' / 'index.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    teams = data.get('teams') if isinstance(data.get('teams'), dict) else data
    return {str(key): value for key, value in teams.items()
            if value and not str(key).startswith('_')}


def _studio_windows(games, start, end, recent_days, compare):
    from bp_studio import comparison_window, _in_window, window_bounds
    bounds = window_bounds(games, start=start, end=end, recent_days=recent_days)
    current = _in_window(games, bounds['from'], bounds['to'])
    windows = []
    for mode in ('prev', 'yoy'):
        span = comparison_window(bounds, mode)
        if not span:
            continue
        rows = _in_window(games, span['from'], span['to'])
        windows.append({'mode': mode, 'label': span['label'], 'from': span['from'],
                        'to': span['to'], 'games': len(rows), 'rows': rows})
    return bounds, current, windows


def _game_matches_rule(game, rule):
    """BP 工作台三模式过滤：只认已核验的记录格式，不靠数组长度猜。

    营地里的排位/巅峰局偶尔只记了 4 个 Ban（缺一手），老代码用
    ``len(bans) == 4`` 把它算成 draft-18，于是「征召」页签一边显示 11 局
    rank-20 数据，一边又写「征召 18 手还没有完整对局」，页头数字也自相矛盾。
    格式只认 normalize_scrims / bp_demo 写入的 ruleProfile（已核验），
    与 docs/bp_rules_v2.md「绝不用 5 Ban 的数据去套 4 Ban 的排程」一致。
    """
    if not rule:
        return True
    profile = str(game.get("ruleProfile") or "")
    if rule in ("draft-18", "draft-20", "rank-20"):
        return profile == rule
    if rule == "blind":
        return str(game.get("bpMode") or "") == "blind"
    return True


_BP_RULE_LABEL = {'draft-18': '征召 18 手', 'draft-20': 'KPL 20 手',
                  'rank-20': '排位 / 巅峰 20 手', 'blind': '巅峰对决盲选'}


def _bp_studio_unavailable(source: str, reason: str) -> dict:
    """一条 BP 记录都没有：回 200 + available=false，让页面画空态。

    以前这里抛 400，前端只能显示「BP 数据暂时读不到 / 请求失败（HTTP 400）」，
    新装的库打开 BP 页就是一句红字报错，既不像空态也没告诉用户下一步做什么。
    """
    return {
        'schema': 'bp-studio-empty-1',
        'available': False,
        'reason': reason,
        'source': source,
        'quality': {'games': 0, 'ordered': 0, 'blind': 0, 'partial': 0},
        'caveats': [],
    }


@router.get('/api/v3/bp-studio')
def bp_studio_page(request: Request):
    """BP 工作台页面模型：目录 + 主数据层 + 对手情报 + 目标对照 + 赛前方案。"""
    from bp_intelligence import normalize_kpl
    from bp_studio import (SCHEMA, build_studio, compare_break, hero_catalog,
                           league_catalog, lineup_diff, opponent_studio, plan,
                           target_break, team_catalog, _hero_rates, _strong_combos)
    import kpl_bp

    values = request.query_params
    source = str(values.get('source') or 'kpl').strip()
    if source not in ('kpl', 'scrim'):
        raise HTTPException(400, 'source 只能是 kpl 或 scrim')
    leagues = str(values.get('leagues') or '').strip()
    rule = str(values.get('rule') or '').strip()
    if rule and rule not in ('draft-18', 'draft-20', 'rank-20', 'blind'):
        raise HTTPException(400, 'rule 只能是 draft-18 / draft-20 / rank-20 / blind')
    demo = str(values.get('demo') or '').strip().lower() in ('1', 'true', 'yes')
    team = str(values.get('team') or '').strip()
    opponent = str(values.get('opponent') or '').strip()
    start = str(values.get('from') or '').strip()
    end = str(values.get('to') or '').strip()
    compare = str(values.get('compare') or 'prev').strip()
    if compare not in ('prev', 'yoy', 'none'):
        raise HTTPException(400, 'compare 只能是 prev / yoy / none')
    try:
        recent_days = int(values.get('recentDays') or 30)
    except (TypeError, ValueError):
        raise HTTPException(400, 'recentDays 必须是整数')
    if recent_days not in (7, 15, 30, 90, 180, 365):
        raise HTTPException(400, 'recentDays 只能是 7 / 15 / 30 / 90 / 180 / 365')
    target = [part.strip() for part in str(values.get('target') or '').split(',')
              if part.strip()]
    if len(target) > 3:
        raise HTTPException(400, '目标最多 3 个英雄')

    kpl_stamp = _kpl_source_stamp(kpl_bp)
    camp_stamp = (_camp_dir_stamp(MATCHES.parent / 'camp_details'), _dataset_stamp())
    cache_key = (kpl_stamp, camp_stamp, source, rule, demo, leagues, team, opponent,
                 start, end, compare, recent_days, tuple(target), _BP_STUDIO_VERSION)
    cached = _BP_STUDIO_CACHE.get(cache_key)
    if cached is not None:
        return cached
    key_id = _cache_key_id(cache_key)
    persisted = _report_disk_read(_BP_STUDIO_DISK, key_id, 'page')
    if persisted is not None:
        _BP_STUDIO_CACHE[cache_key] = persisted
        return persisted

    raw = _bp_studio_raw(leagues)
    kpl_games = _bp_studio_kpl(leagues)
    competition_id = str(values.get('competition') or '').strip()
    own_games = _bp_studio_scrim(window=_competition_window(competition_id))
    if demo and source == 'scrim':
        from bp_demo import scrim_games
        own_games = scrim_games()
    primary = kpl_games if source == 'kpl' else own_games
    if rule:
        primary = [game for game in primary if _game_matches_rule(game, rule)]
        if not primary:
            label = _BP_RULE_LABEL.get(rule, rule)
            return _bp_studio_unavailable(
                source, f'当前数据源还没有{label}的 BP 记录（{rule}）。')
    if not primary:
        return _bp_studio_unavailable(source, '当前数据源还没有可用的 BP 记录。')
    scrim_names = sorted({str(game.get('enemy')) for game in own_games
                          if str(game.get('team')) == '本队' and game.get('enemy')})
    # 首屏不知道默认值：由服务端一次性解析，避免前端先空跑一次再重取。
    if team == '__auto__':
        team = '本队' if source == 'scrim' else ''
    auto_opponent = opponent == '__auto__'
    bounds, current, windows = _studio_windows(primary, start, end, recent_days, compare)
    if auto_opponent:
        # 默认对手取当前窗口里出场最多的队，首屏才有东西可看。
        counts = Counter(str(game.get('team')) for game in current
                         if str(game.get('team')) and str(game.get('team')) != team)
        opponent = counts.most_common(1)[0][0] if counts else ''
    prev = next((item for item in windows if item['mode'] == 'prev'), None)
    yoy = next((item for item in windows if item['mode'] == 'yoy'), None)
    focus = '' if source == 'kpl' else '本队'
    page = build_studio(
        primary, source=source, team=team, opponent=opponent, bounds=bounds,
        compare=compare, recent_days=recent_days,
        prev_games=(prev or {}).get('rows'),
        yoy_games=(yoy or {}).get('rows'),
        opponent_key=opponent, focus_team=focus)
    # KPL 基线：训练赛来源时给同窗口同赛季的联盟大盘，用于对照。
    baseline = None
    if source == 'scrim' and kpl_games:
        baseline = build_studio(
            kpl_games, source='kpl', bounds=bounds, recent_days=recent_days,
            team='', opponent='', compare='none', focus_team='')

    kpl_rates = _hero_rates(_in_scope(kpl_games, bounds))
    meta_bans = {hero: index + 1 for index, (hero, _row) in enumerate(
        sorted(((hero, row) for hero, row in kpl_rates.items()),
               key=lambda item: -(item[1].get('bans') or 0))[:15])}
    strong = _strong_combos(page['combos'].get('pairs') or [])
    opponent_key = opponent or ((baseline or {}).get('opponent') or '')
    if opponent == '__all__':
        opp_scope = [game for game in current if str(game.get('team')) != team]
        opponent_block = opponent_studio(opp_scope, '__all__', strong=strong,
                                         meta_bans=meta_bans)
    elif opponent:
        opponent_block = opponent_studio(current, opponent, strong=strong,
                                         meta_bans=meta_bans)
    else:
        opponent_block = {'available': False, 'reason': '未选择对手。'}

    own_bounds, own_current, _ = _studio_windows(own_games, start, end, recent_days, compare)
    own_team_rows = [game for game in own_current if str(game.get('team')) == '本队']
    target_block = None
    if target:
        kpl_break = target_break(_in_scope(kpl_games, bounds), target)
        own_break = (target_break(own_team_rows, target)
                     if own_team_rows else {'available': False, 'reason': '本队训练赛没有同窗口样本。'})
        target_block = {
            'kpl': kpl_break, 'own': own_break,
            'compare': compare_break(kpl_break, own_break),
        }

    opp_rows = [game for game in current if str(game.get('team')) == opponent] if opponent else []
    diff = lineup_diff(own_team_rows, opp_rows, size=2) if own_team_rows and opp_rows \
        else {'available': False, 'shared': [], 'onlyUs': [], 'onlyThem': []}

    plan_block = {'available': False, 'reason': '未选择对手。'}
    if opponent and opponent != '__all__':
        try:
            plan_block = plan(current, team, opponent, source=source)
        except ValueError:
            plan_block = {'available': False, 'reason': '赛前方案数据不足。'}

    # 手序可用率：盲选 / BP 不完整的局不进第 N 手统计，页头要把它说清楚。
    if source == 'kpl':
        blind = sum(1 for game in current if str(game.get('bpMode') or '') == 'blind')
        partial = sum(1 for game in current if str(game.get('bpMode') or '') == 'partial')
        ordered = sum(1 for game in current
                      if game.get('pickOrderKnown') and game.get('bansKnown'))
    else:
        blind = 0
        ordered = sum(1 for game in current if game.get('pickOrderKnown'))
        partial = max(0, len(current) - ordered)
    quality = {'games': len(current), 'ordered': ordered,
               'blind': blind, 'partial': partial}
    heroes = page['heroes']
    heroes.pop('byLane', None)
    for key in ('pairs', 'size3'):
        rows = page['combos'].get(key) or []
        page['combos'][f'{key}Total'] = len(rows)
        page['combos'][key] = rows[:45]
    catalog = league_catalog(raw)
    scrim_opponents = sorted({str(game.get('enemy')) for game in own_games
                              if str(game.get('team')) == '本队' and game.get('enemy')})
    report = {
        'schema': SCHEMA,
        'source': source,
        'scope': {
            'source': source, 'leagues': leagues, 'team': team, 'opponent': opponent,
            'from': bounds['from'], 'to': bounds['to'], 'days': bounds['days'],
            'anchor': bounds['anchor'], 'compare': compare,
            'games': len(current), 'boardGames': page['boardGames'],
            'prev': ({'from': prev['from'], 'to': prev['to'], 'games': prev['games']}
                     if prev else None),
            'yoy': ({'from': yoy['from'], 'to': yoy['to'], 'games': yoy['games']}
                    if yoy else None),
        },
        'options': {
            'leagues': catalog['leagues'], 'years': catalog['years'],
            'kinds': catalog['kinds'],
            'teams': team_catalog(raw),
            'heroes': hero_catalog(kpl_games),
            'scrimOpponents': scrim_opponents,
            'teamIcons': _team_icons(),
            'recentDays': recent_days,
            'recentOptions': [7, 15, 30, 90, 180, 365],
            'defaultTeam': '重庆狼队' if source == 'kpl' else '本队',
            'defaultOpponent': ('成都AG超玩会' if source == 'kpl'
                                else (scrim_opponents[0] if scrim_opponents else '')),
        },
        'quality': quality,
        'demo': bool(demo),
        'primary': page,
        'baseline': baseline,
        'opponentBlock': opponent_block,
        'targetBlock': target_block,
        'lineupDiff': diff,
        'plan': plan_block,
        'caveats': page['caveats'] + [
            '拆组合 = 目标组合里恰好一个英雄被对手 Ban；第几手只表示该队自己的 Ban 位次。',
            'KPL 先验是历史同队同局记录；训练赛对照只说明我们做过什么，不证明对错。',
        ],
    }
    if kpl_stamp is not None:
        if len(_BP_STUDIO_CACHE) >= _BP_STUDIO_CACHE_MAX:
            _BP_STUDIO_CACHE.pop(next(iter(_BP_STUDIO_CACHE)))
        _BP_STUDIO_CACHE[cache_key] = report
        _report_disk_write(_BP_STUDIO_DISK, key_id, 'page', report)
    return report


def _in_scope(games, bounds):
    from bp_studio import _in_window
    return _in_window(games, bounds['from'], bounds['to'])


@router.get('/api/v3/bp-studio/target')
def bp_studio_target(request: Request):
    """只重算目标（英雄 / 组合）：KPL 怎么应对、本队怎么应对、差在哪。"""
    from bp_intelligence import normalize_kpl
    from bp_studio import (compare_break, _in_window, target_break, window_bounds)
    import kpl_bp

    values = request.query_params
    leagues = str(values.get('leagues') or '').strip()
    team = str(values.get('team') or '').strip()
    start = str(values.get('from') or '').strip()
    end = str(values.get('to') or '').strip()
    target = [part.strip() for part in str(values.get('target') or '').split(',')
              if part.strip()]
    if not target:
        raise HTTPException(400, '请选择目标英雄或组合')
    if len(target) > 3:
        raise HTTPException(400, '目标最多 3 个英雄')
    try:
        recent_days = int(values.get('recentDays') or 30)
    except (TypeError, ValueError):
        raise HTTPException(400, 'recentDays 必须是整数')
    cache_key = (_kpl_source_stamp(kpl_bp),
                 _camp_dir_stamp(MATCHES.parent / 'camp_details'), leagues, team,
                 start, end, recent_days, tuple(target))
    cached = _BP_STUDIO_TARGET_CACHE.get(cache_key)
    if cached is not None:
        return cached
    raw = _bp_studio_raw(leagues)
    kpl_games = _bp_studio_kpl(leagues)
    own_games = _bp_studio_scrim()
    own_team_rows = [game for game in own_games if str(game.get('team')) == '本队']
    kpl_bounds = window_bounds(kpl_games, start=start, end=end, recent_days=recent_days)
    own_bounds = window_bounds(own_team_rows, start=start, end=end,
                               recent_days=recent_days)
    kpl_break = target_break(_in_window(kpl_games, kpl_bounds['from'], kpl_bounds['to']),
                             target)
    own_break = (target_break(_in_window(own_team_rows, own_bounds['from'],
                                         own_bounds['to']), target)
                 if own_team_rows else {'available': False,
                                        'reason': '本队训练赛还没有同窗口样本。'})
    if team:
        own_break['team'] = team
    report = {
        'target': target, 'label': kpl_break.get('label'),
        'kpl': kpl_break, 'own': own_break,
        'compare': compare_break(kpl_break, own_break, kpl_label='KPL',
                                 own_label=team or '本队'),
        'windows': {'kpl': kpl_bounds, 'own': own_bounds if own_team_rows else None},
    }
    if len(_BP_STUDIO_TARGET_CACHE) >= _BP_STUDIO_TARGET_CACHE_MAX:
        _BP_STUDIO_TARGET_CACHE.pop(next(iter(_BP_STUDIO_TARGET_CACHE)))
    _BP_STUDIO_TARGET_CACHE[cache_key] = report
    return report


@router.get('/api/v3/bp-studio/combo')
def bp_studio_combo(request: Request):
    """自选组合的完整战绩卡（同队同局）。"""
    from bp_intelligence import normalize_kpl
    from bp_studio import _in_window, window_bounds
    from bp_lab import combo_detail
    import kpl_bp

    values = request.query_params
    source = str(values.get('source') or 'kpl').strip()
    leagues = str(values.get('leagues') or '').strip()
    team = str(values.get('team') or '').strip()
    start = str(values.get('from') or '').strip()
    end = str(values.get('to') or '').strip()
    heroes = [part.strip() for part in str(values.get('target') or '').split(',')
              if part.strip()]
    if len(heroes) < 2:
        raise HTTPException(400, '至少选择 2 个英雄')
    if len(heroes) > 3:
        raise HTTPException(400, '最多 3 个英雄')
    try:
        recent_days = int(values.get('recentDays') or 30)
    except (TypeError, ValueError):
        raise HTTPException(400, 'recentDays 必须是整数')
    cache_key = (_kpl_source_stamp(kpl_bp),
                 _camp_dir_stamp(MATCHES.parent / 'camp_details'), source, leagues,
                 team, start, end, recent_days, tuple(sorted(heroes)))
    cached = _BP_STUDIO_COMBO_CACHE.get(cache_key)
    if cached is not None:
        return cached
    if source == 'scrim':
        games = [game for game in _bp_studio_scrim()
                 if not team or str(game.get('team')) == team]
    else:
        games = _bp_studio_kpl(leagues)
    bounds = window_bounds(games, start=start, end=end, recent_days=recent_days)
    scoped = _in_window(games, bounds['from'], bounds['to'])
    detail = combo_detail(scoped, heroes, recent_days=recent_days)
    detail['window'] = bounds
    detail['source'] = source
    if len(_BP_STUDIO_COMBO_CACHE) >= _BP_STUDIO_COMBO_CACHE_MAX:
        _BP_STUDIO_COMBO_CACHE.pop(next(iter(_BP_STUDIO_COMBO_CACHE)))
    _BP_STUDIO_COMBO_CACHE[cache_key] = detail
    return detail


@router.get('/api/v3/bp-studio/opponent')
def bp_studio_opponent(request: Request):
    """只取一个对手的情报块，供“对比对手”用，避免再拉整页模型。"""
    from bp_studio import _in_window, opponent_studio, window_bounds
    import kpl_bp

    values = request.query_params
    source = str(values.get('source') or 'kpl').strip()
    if source not in ('kpl', 'scrim'):
        raise HTTPException(400, 'source 只能是 kpl 或 scrim')
    leagues = str(values.get('leagues') or '').strip()
    team = str(values.get('team') or '').strip()
    opponent = str(values.get('opponent') or '').strip()
    if not opponent or opponent == '__all__':
        raise HTTPException(400, '请选择一个具体对手')
    start = str(values.get('from') or '').strip()
    end = str(values.get('to') or '').strip()
    try:
        recent_days = int(values.get('recentDays') or 30)
    except (TypeError, ValueError):
        raise HTTPException(400, 'recentDays 必须是整数')
    games = _bp_studio_scrim() if source == 'scrim' else _bp_studio_kpl(leagues)
    bounds = window_bounds(games, start=start, end=end, recent_days=recent_days)
    scoped = _in_window(games, bounds['from'], bounds['to'])
    block = opponent_studio(scoped, opponent)
    block['window'] = bounds
    return block


@router.get('/api/v3/bp-studio/sequence')
def bp_studio_sequence(request: Request):
    """第 N 手查询：某队第 N 手 Ban/Pick 了什么，对面同手 / 下一手怎么接。"""
    from bp_studio import _in_window, sequence_board, window_bounds
    import kpl_bp

    values = request.query_params
    source = str(values.get('source') or 'kpl').strip()
    if source not in ('kpl', 'scrim'):
        raise HTTPException(400, 'source 只能是 kpl 或 scrim')
    leagues = str(values.get('leagues') or '').strip()
    team = str(values.get('team') or '').strip()
    start = str(values.get('from') or '').strip()
    end = str(values.get('to') or '').strip()
    action = str(values.get('action') or 'pick').strip()
    if action not in ('pick', 'ban'):
        raise HTTPException(400, 'action 只能是 pick / ban')
    try:
        hand = int(values.get('hand') or 1)
        recent_days = int(values.get('recentDays') or 30)
    except (TypeError, ValueError):
        raise HTTPException(400, 'hand / recentDays 必须是整数')
    hand = max(1, min(5, hand))
    hero = str(values.get('hero') or '').strip()
    games = _bp_studio_scrim() if source == 'scrim' else _bp_studio_kpl(leagues)
    bounds = window_bounds(games, start=start, end=end, recent_days=recent_days)
    scoped = _in_window(games, bounds['from'], bounds['to'])
    if source == 'scrim' and not team:
        team = '本队'
    report = sequence_board(scoped, team, action=action, hand=hand, hero=hero)
    report['window'] = bounds
    report['source'] = source
    return report


@router.get('/api/v3/bp-studio/period-compare')
def bp_studio_period_compare(request: Request):
    """按日期切分的前后对照（Pick / Ban / 胜率）；没有版本字段，不冒充版本。"""
    from bp_studio import _in_window, period_compare, season_period_compare, season_cut, window_bounds

    values = request.query_params
    source = str(values.get('source') or 'kpl').strip()
    if source not in ('kpl', 'scrim'):
        raise HTTPException(400, 'source 只能是 kpl 或 scrim')
    leagues = str(values.get('leagues') or '').strip()
    cut = str(values.get('cut') or '').strip()
    season = str(values.get('season') or '').strip()
    if not season and not cut:
        raise HTTPException(400, 'cut 或 season 不能为空')
    if season and not season_cut(season):
        raise HTTPException(400, '未知赛季')
    try:
        days = int(values.get('days') or 30)
    except (TypeError, ValueError):
        raise HTTPException(400, 'days 必须是整数')
    games = _bp_studio_scrim() if source == 'scrim' else _bp_studio_kpl(leagues)
    report = (season_period_compare(games, season, days) if season
              else period_compare(games, cut, days))
    report['source'] = source
    report['season'] = season or ''
    return report


@router.get('/api/v3/bp-studio/hero-ring')
def bp_studio_hero_ring(request: Request):
    """英雄关系环：克制 / 被克制 / 最佳搭档 + 当前范围的基础比率。"""
    from bp_studio import _in_window, hero_ring, window_bounds

    values = request.query_params
    hero = str(values.get('hero') or '').strip()
    if not hero:
        raise HTTPException(400, 'hero 不能为空')
    source = str(values.get('source') or 'kpl').strip()
    if source not in ('kpl', 'scrim'):
        raise HTTPException(400, 'source 只能是 kpl 或 scrim')
    leagues = str(values.get('leagues') or '').strip()
    start = str(values.get('from') or '').strip()
    end = str(values.get('to') or '').strip()
    try:
        recent_days = int(values.get('recentDays') or 30)
    except (TypeError, ValueError):
        raise HTTPException(400, 'recentDays 必须是整数')
    games = _bp_studio_scrim() if source == 'scrim' else _bp_studio_kpl(leagues)
    bounds = window_bounds(games, start=start, end=end, recent_days=recent_days)
    scoped = _in_window(games, bounds['from'], bounds['to'])
    report = hero_ring(hero, scoped)
    report['window'] = bounds
    report['source'] = source
    return report


@router.get('/api/v3/bp-studio/tree')
def bp_studio_tree(request: Request):
    """BP 时序分支：已核验手序的前缀树 + 主路径，给“地铁图”用。"""
    from bp_studio import _in_window, draft_tree, window_bounds

    values = request.query_params
    source = str(values.get('source') or 'kpl').strip()
    if source not in ('kpl', 'scrim'):
        raise HTTPException(400, 'source 只能是 kpl 或 scrim')
    leagues = str(values.get('leagues') or '').strip()
    team = str(values.get('team') or '').strip()
    opponent = str(values.get('opponent') or '').strip()
    start = str(values.get('from') or '').strip()
    end = str(values.get('to') or '').strip()
    side = str(values.get('side') or '').strip()
    if side not in ('', '1', '2'):
        raise HTTPException(400, 'side 只能是 1 / 2 或留空')
    hero = str(values.get('hero') or '').strip()
    try:
        recent_days = int(values.get('recentDays') or 30)
        depth = int(values.get('depth') or 6)
        branch = int(values.get('branch') or 3)
    except (TypeError, ValueError):
        raise HTTPException(400, 'recentDays / depth / branch 必须是整数')
    depth = max(3, min(20, depth))
    branch = max(2, min(5, branch))
    games = _bp_studio_scrim() if source == 'scrim' else _bp_studio_kpl(leagues)
    bounds = window_bounds(games, start=start, end=end, recent_days=recent_days)
    scoped = _in_window(games, bounds['from'], bounds['to'])
    if source == 'scrim' and not team:
        team = '本队'
    report = draft_tree(scoped, team=team, opponent=opponent,
                        depth=depth, branch=branch, side=side, start_hero=hero)
    report['window'] = bounds
    report['source'] = source
    return report


@router.get('/api/v3/bp-studio/counter-chain')
def bp_studio_counter_chain(request: Request):
    """应对分析：按楼层逐层推演「触发 → 回应」，支持战队 / 先后手 / BO 筛选。"""
    from bp_studio import _in_window, window_bounds
    from counter_chain import build_counter_chain

    values = request.query_params
    source = str(values.get('source') or 'kpl').strip()
    if source not in ('kpl', 'scrim'):
        raise HTTPException(400, 'source 只能是 kpl 或 scrim')
    leagues = str(values.get('leagues') or '').strip()
    team = str(values.get('team') or '').strip()
    opponent = str(values.get('opponent') or '').strip()
    start = str(values.get('from') or '').strip()
    end = str(values.get('to') or '').strip()
    side = str(values.get('side') or '').strip()
    if side not in ('', '1', '2'):
        raise HTTPException(400, 'side 只能是 1 / 2 或留空')
    try:
        recent_days = int(values.get('recentDays') or 365)
        bo = int(values.get('bo') or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, 'recentDays / bo 必须是整数')
    if bo not in (0, 3, 5, 7):
        raise HTTPException(400, 'bo 只能是 0 / 3 / 5 / 7')
    prefix = {}
    # 逐手键（red1/red2/blue2/blue3/blue4/blue5）对应前置条件里的单手卡；
    # 合并楼层键保留兼容旧链接/旧缓存。
    for stage in ('blueBan1', 'redBan1', 'blueBan2', 'redBan2', 'blueBan3', 'redBan3',
                  'blueBan4', 'redBan4', 'blueBan5', 'redBan5',
                  'blue1', 'red1', 'red2', 'blue2', 'blue3', 'red3',
                  'red4', 'blue4', 'blue5', 'red5',
                  'red12', 'blue23', 'blue45'):
        raw = str(values.get(f'prefix_{stage}') or '').strip()
        if raw:
            prefix[stage] = [hero.strip() for hero in raw.split(',') if hero.strip()]
    games = _bp_studio_scrim() if source == 'scrim' else _bp_studio_kpl(leagues)
    bounds = window_bounds(games, start=start, end=end, recent_days=recent_days)
    scoped = _in_window(games, bounds['from'], bounds['to'])
    if source == 'scrim' and not team:
        team = '本队'
    report = build_counter_chain(scoped, team=team, opponent=opponent,
                                 side=side, bo=bo, prefix=prefix)
    report['window'] = bounds
    report['source'] = source
    return report


@router.get('/api/v3/bp-studio/types')
def bp_studio_types(request: Request, repo=Depends(repository)):
    """类型博弈：Ban / Pick 的英雄类型 × 手序 × BO × 时间，外加核数与条件反应。"""
    from bp_studio import _in_window, window_bounds
    from bp_types import build_types
    import kpl_bp

    values = request.query_params
    source = str(values.get('source') or 'kpl').strip()
    if source not in ('kpl', 'scrim'):
        raise HTTPException(400, 'source 只能是 kpl 或 scrim')
    leagues = str(values.get('leagues') or '').strip()
    team = str(values.get('team') or '').strip()
    opponent = str(values.get('opponent') or '').strip()
    start = str(values.get('from') or '').strip()
    end = str(values.get('to') or '').strip()
    try:
        recent_days = int(values.get('recentDays') or 30)
        bo = int(values.get('bo') or 0)
        hand = int(values.get('hand') or 0)
        core = int(values.get('core') or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, 'recentDays / bo / hand / core 必须是整数')
    if bo not in (0, 3, 5, 7):
        raise HTTPException(400, 'bo 只能是 0 / 3 / 5 / 7')
    targets = [part.strip() for part in str(values.get('targets') or '').split(',')
               if part.strip()][:3]
    # 类型博弈要在全库（KPL 4700 局 / 训练赛全量）上做英雄类型 × 手序 × BO 的交叉，
    # 一次约 0.9 秒；筛选参数与数据指纹都不变时直接复用上一份报告。
    kpl_stamp = _kpl_source_stamp(kpl_bp)
    camp_stamp = (_camp_dir_stamp(MATCHES.parent / 'camp_details'), _dataset_stamp())
    types_key = (_BP_STUDIO_VERSION, kpl_stamp, camp_stamp, source, leagues, team, opponent, start, end,
                 recent_days, bo, hand, core, tuple(targets))
    types_cached = _BP_STUDIO_TYPES_CACHE.get(types_key)
    if types_cached is not None:
        return types_cached
    types_key_id = _cache_key_id(types_key)
    types_persisted = _report_disk_read(_BP_STUDIO_TYPES_DISK, types_key_id, 'types')
    if types_persisted is not None:
        _BP_STUDIO_TYPES_CACHE[types_key] = types_persisted
        return types_persisted
    hint = {}
    timeline_games = None
    if source == 'scrim':
        from bp_intelligence import normalize_scrims
        from bp_process import link_scrim_process
        rows = bp_board().get('games') or []
        process_map = link_scrim_process(rows, repo.get()['matches'])
        games = normalize_scrims(rows, process_map=process_map)
        # 训练课系列赛登记了 BO3/5/7：按 channel match_key 精确挂到每一局。
        try:
            from contextlib import closing
            with closing(sqlite3.connect(f'file:{DB.as_posix()}?mode=ro', uri=True)) as conn:
                for match_key, best_of in conn.execute(
                        'SELECT g.match_key, s.best_of FROM training_series_games g'
                        ' JOIN training_series s ON s.id = g.series_id'):
                    if best_of in (3, 5, 7):
                        hint[str(match_key)] = int(best_of)
        except sqlite3.Error:
            pass
        for game in games:
            key = str(game.get('processMatchKey') or '')
            if key and hint.get(key):
                hint[game.get('id')] = hint[key]
        timeline_games = games
    else:
        games = _bp_studio_kpl(leagues)
        timeline_games = games
    bounds = window_bounds(games, start=start, end=end, recent_days=recent_days)
    scoped = _in_window(games, bounds['from'], bounds['to'])
    if source == 'scrim' and not team:
        team = '本队'
    # 排期表里的赛制是日期级兜底；series 的 best_of 已经在上面精确挂到局。
    try:
        import workspace_store
        workspace = workspace_store.Workspace(DB).ensure_schema()
        for row in workspace.list_schedules():
            match = re.search(r'([357])', str(row.get('format') or ''))
            if match and str(row.get('date') or ''):
                hint.setdefault(str(row.get('date'))[:10], int(match.group(1)))
    except Exception:  # 排期读不到不影响类型分析
        pass
    report = build_types(scoped, team=team, opponent=opponent, bo=bo, targets=targets,
                         bo_hint=hint, hand=hand, core=core,
                         timeline_games=timeline_games)
    report['window'] = bounds
    report['filters'] = {'source': source, 'leagues': leagues, 'team': team,
                         'opponent': opponent, 'from': start, 'to': end,
                         'recentDays': recent_days, 'bo': bo, 'targets': targets,
                         'hand': hand, 'core': core}
    if kpl_stamp is not None or camp_stamp[0] is not None:
        if len(_BP_STUDIO_TYPES_CACHE) >= _BP_STUDIO_TYPES_CACHE_MAX:
            _BP_STUDIO_TYPES_CACHE.pop(next(iter(_BP_STUDIO_TYPES_CACHE)))
        _BP_STUDIO_TYPES_CACHE[types_key] = report
        _report_disk_write(_BP_STUDIO_TYPES_DISK, types_key_id, 'types', report)
    return report


@router.get('/api/v3/bp-lab/lookup')
def bp_lab_lookup(request: Request):
    """指定英雄 / 组合 / 完整阵容的历史对手与分路类型。"""
    from bp_lab import lookup as run_lookup
    import kpl_bp

    values = request.query_params
    source = str(values.get('source') or 'kpl').strip()
    if source not in ('kpl', 'scrim'):
        raise HTTPException(400, 'source 只能是 kpl 或 scrim')
    league = str(values.get('league') or 'all').strip()
    if league not in ('all', 'kpl', 'challenger'):
        raise HTTPException(400, 'league 只能是 all / kpl / challenger')
    heroes = [part.strip() for part in str(values.get('heroes') or '').split(',')
              if part.strip()]
    if not heroes:
        raise HTTPException(400, '请至少提供一个英雄')
    if len(heroes) > 5:
        raise HTTPException(400, '最多查询 5 个英雄')
    start = str(values.get('from') or '').strip()
    end = str(values.get('to') or '').strip()
    stamp = (_kpl_source_stamp(kpl_bp) if source == 'kpl'
             else (_camp_dir_stamp(MATCHES.parent / 'camp_details'), _dataset_stamp()))
    cache_key = (stamp, source, league, tuple(heroes), start, end)
    cached = _BP_LAB_LOOKUP_CACHE.get(cache_key)
    if cached is not None:
        return cached
    try:
        games = _bp_lab_games(source, league, start, end)
        result = run_lookup(games, heroes)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    result['filters'] = {'source': source, 'league': league, 'heroes': heroes,
                         'from': start, 'to': end}
    if stamp is not None:
        if len(_BP_LAB_LOOKUP_CACHE) >= _BP_LAB_LOOKUP_CACHE_MAX:
            _BP_LAB_LOOKUP_CACHE.pop(next(iter(_BP_LAB_LOOKUP_CACHE)))
        _BP_LAB_LOOKUP_CACHE[cache_key] = result
    return result


@router.get('/api/v3/bp-lab/combo')
def bp_lab_combo(request: Request):
    """自选组合：任意 2–3 个英雄的同队同局战绩与基准。"""
    from bp_lab import combo_detail

    values = request.query_params
    source = str(values.get('source') or 'kpl').strip()
    if source not in ('kpl', 'scrim'):
        raise HTTPException(400, 'source 只能是 kpl 或 scrim')
    league = str(values.get('league') or 'all').strip()
    if league not in ('all', 'kpl', 'challenger'):
        raise HTTPException(400, 'league 只能是 all / kpl / challenger')
    heroes = [part.strip() for part in str(values.get('heroes') or '').split(',')
              if part.strip()]
    if not heroes:
        raise HTTPException(400, '请至少选择一个英雄')
    if len(heroes) > 5:
        raise HTTPException(400, '组合最多 5 个英雄')
    team = str(values.get('team') or '').strip()
    start = str(values.get('from') or '').strip()
    end = str(values.get('to') or '').strip()
    try:
        recent_days = int(values.get('recentDays') or 30)
    except (TypeError, ValueError):
        raise HTTPException(400, 'recentDays 必须是整数')
    if recent_days not in (7, 15, 30):
        raise HTTPException(400, 'recentDays 只能是 7 / 15 / 30')
    import kpl_bp
    stamp = (_kpl_source_stamp(kpl_bp) if source == 'kpl'
             else (_camp_dir_stamp(MATCHES.parent / 'camp_details'), _dataset_stamp()))
    cache_key = ('combo-detail', stamp, source, league, team, tuple(heroes),
                 start, end, recent_days)
    cached = _BP_LAB_LOOKUP_CACHE.get(cache_key)
    if cached is not None:
        return cached
    try:
        result = combo_detail(
            _bp_lab_games(source, league, start, end), heroes,
            team=team, recent_days=recent_days,
        )
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    result['filters'] = {'source': source, 'league': league, 'team': team,
                         'heroes': heroes, 'from': start, 'to': end,
                         'recentDays': recent_days}
    if stamp is not None:
        if len(_BP_LAB_LOOKUP_CACHE) >= _BP_LAB_LOOKUP_CACHE_MAX:
            _BP_LAB_LOOKUP_CACHE.pop(next(iter(_BP_LAB_LOOKUP_CACHE)))
        _BP_LAB_LOOKUP_CACHE[cache_key] = result
    return result


@router.get('/api/v3/bp-lab/counters')
def bp_lab_counters(request: Request):
    """04 区的按需查询：同一目标英雄/组合，各队怎么 Ban / 怎么应对。"""
    from bp_lab import team_counters

    values = request.query_params
    source = str(values.get('source') or 'kpl').strip()
    if source not in ('kpl', 'scrim'):
        raise HTTPException(400, 'source 只能是 kpl 或 scrim')
    league = str(values.get('league') or 'all').strip()
    if league not in ('all', 'kpl', 'challenger'):
        raise HTTPException(400, 'league 只能是 all / kpl / challenger')
    target = [part.strip() for part in str(values.get('target') or '').split(',')
              if part.strip()]
    if not target:
        raise HTTPException(400, '请选择目标英雄或组合')
    start = str(values.get('from') or '').strip()
    end = str(values.get('to') or '').strip()
    import kpl_bp
    stamp = (_kpl_source_stamp(kpl_bp) if source == 'kpl'
             else (_camp_dir_stamp(MATCHES.parent / 'camp_details'), _dataset_stamp()))
    cache_key = ('counters', stamp, source, league, tuple(target), start, end)
    cached = _BP_LAB_LOOKUP_CACHE.get(cache_key)
    if cached is not None:
        return cached
    try:
        result = team_counters(_bp_lab_games(source, league, start, end), target)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    result['filters'] = {'source': source, 'league': league,
                         'target': target, 'from': start, 'to': end}
    if stamp is not None:
        if len(_BP_LAB_LOOKUP_CACHE) >= _BP_LAB_LOOKUP_CACHE_MAX:
            _BP_LAB_LOOKUP_CACHE.pop(next(iter(_BP_LAB_LOOKUP_CACHE)))
        _BP_LAB_LOOKUP_CACHE[cache_key] = result
    return result


@router.get('/api/v3/bp-lab/stability')
def bp_lab_stability(request: Request):
    """09 区的按需查询：组合逐窗口胜率与稳定性判定。"""
    from bp_lab import combo_stability

    values = request.query_params
    source = str(values.get('source') or 'kpl').strip()
    if source not in ('kpl', 'scrim'):
        raise HTTPException(400, 'source 只能是 kpl 或 scrim')
    league = str(values.get('league') or 'all').strip()
    if league not in ('all', 'kpl', 'challenger'):
        raise HTTPException(400, 'league 只能是 all / kpl / challenger')
    combo = [part.strip() for part in str(values.get('combo') or '').split(',')
             if part.strip()]
    if not combo:
        raise HTTPException(400, '请选择组合')
    team = str(values.get('team') or '').strip()
    unit = str(values.get('unit') or ('day' if source == 'scrim' else 'month')).strip()
    if unit not in ('day', 'month', 'season', 'stage'):
        raise HTTPException(400, 'unit 只能是 day / month / season / stage')
    start = str(values.get('from') or '').strip()
    end = str(values.get('to') or '').strip()
    import kpl_bp
    stamp = (_kpl_source_stamp(kpl_bp) if source == 'kpl'
             else (_camp_dir_stamp(MATCHES.parent / 'camp_details'), _dataset_stamp()))
    cache_key = ('stability', stamp, source, league, team, tuple(combo), unit, start, end)
    cached = _BP_LAB_LOOKUP_CACHE.get(cache_key)
    if cached is not None:
        return cached
    try:
        games = _bp_lab_games(source, league, start, end)
        if team:
            games = [g for g in games if str(g.get('team') or '') == team]
        elif source == 'scrim':
            games = [g for g in games if str(g.get('team') or '') == '本队']
        result = combo_stability(games, combo, unit, available=[])
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    result['filters'] = {'source': source, 'league': league, 'team': team,
                         'combo': combo, 'unit': unit, 'from': start, 'to': end}
    if stamp is not None:
        if len(_BP_LAB_LOOKUP_CACHE) >= _BP_LAB_LOOKUP_CACHE_MAX:
            _BP_LAB_LOOKUP_CACHE.pop(next(iter(_BP_LAB_LOOKUP_CACHE)))
        _BP_LAB_LOOKUP_CACHE[cache_key] = result
    return result


@router.get('/api/v3/bp-lab/opponent')
def bp_lab_opponent(request: Request):
    """03 区：指定对手 + 指定 BP 局面的组合/英雄使用与反制。"""
    from bp_lab import opponent_research

    values = request.query_params
    source = str(values.get('source') or 'kpl').strip()
    if source not in ('kpl', 'scrim'):
        raise HTTPException(400, 'source 只能是 kpl 或 scrim')
    league = str(values.get('league') or 'all').strip()
    if league not in ('all', 'kpl', 'challenger'):
        raise HTTPException(400, 'league 只能是 all / kpl / challenger')
    opponent = str(values.get('opponent') or '').strip()
    if not opponent:
        raise HTTPException(400, '请选择对手')
    side = str(values.get('side') or '').strip()
    first_pick = str(values.get('firstPick') or values.get('first_pick') or '').strip()
    combo = [part.strip() for part in str(values.get('combo') or '').split(',')
             if part.strip()]
    hero = str(values.get('hero') or '').strip()
    start = str(values.get('from') or '').strip()
    end = str(values.get('to') or '').strip()
    import kpl_bp
    stamp = (_kpl_source_stamp(kpl_bp) if source == 'kpl'
             else (_camp_dir_stamp(MATCHES.parent / 'camp_details'), _dataset_stamp()))
    cache_key = ('opponent', stamp, source, league, opponent, side, first_pick,
                 tuple(combo), hero, start, end)
    cached = _BP_LAB_LOOKUP_CACHE.get(cache_key)
    if cached is not None:
        return cached
    try:
        result = opponent_research(
            _bp_lab_games(source, league, start, end), opponent,
            side=side, first_pick=first_pick,
            combo=combo or None, hero=hero or None,
        )
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    result['filters'] = {'source': source, 'league': league, 'opponent': opponent,
                         'side': side, 'firstPick': first_pick,
                         'combo': combo, 'hero': hero,
                         'from': start, 'to': end}
    if stamp is not None:
        if len(_BP_LAB_LOOKUP_CACHE) >= _BP_LAB_LOOKUP_CACHE_MAX:
            _BP_LAB_LOOKUP_CACHE.pop(next(iter(_BP_LAB_LOOKUP_CACHE)))
        _BP_LAB_LOOKUP_CACHE[cache_key] = result
    return result


@router.post('/api/v3/bp-lab/simulate')
async def bp_lab_simulate(request: Request):
    """训练赛规则沙盘：合法下一手 + 历史证据候选 + 对手一步回应。"""
    from bp_lab import simulate_scrim

    payload = await read_json(request)
    if not isinstance(payload, dict):
        raise HTTPException(400, 'BP 沙盘请求必须是对象')
    if len(json.dumps(payload, ensure_ascii=False)) > 60000:
        raise HTTPException(413, 'BP 沙盘请求过大')
    evidence_source = str(payload.get('evidenceSource') or 'kpl').strip()
    if evidence_source not in ('kpl', 'scrim'):
        raise HTTPException(400, 'evidenceSource 只能是 kpl 或 scrim')
    league = str(payload.get('league') or 'all').strip()
    if league not in ('all', 'kpl', 'challenger'):
        raise HTTPException(400, 'league 只能是 all / kpl / challenger')
    start = str(payload.get('from') or '').strip()
    end = str(payload.get('to') or '').strip()
    try:
        catalog = _local_scrim_hero_catalog()
        evidence = _bp_lab_games(evidence_source, league, start, end)
        return simulate_scrim(payload, catalog['heroes'], evidence)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@router.get('/api/v3/bp-lab/compare')
def bp_lab_compare(request: Request):
    """时间对比：当前窗口 vs 环比（前一个等长窗口）vs 同比（去年同日期）。"""
    from bp_lab import period_compare

    values = request.query_params
    source = str(values.get('source') or 'kpl').strip()
    if source not in ('kpl', 'scrim'):
        raise HTTPException(400, 'source 只能是 kpl 或 scrim')
    league = str(values.get('league') or 'all').strip()
    if league not in ('all', 'kpl', 'challenger'):
        raise HTTPException(400, 'league 只能是 all / kpl / challenger')
    team = str(values.get('team') or '').strip()
    target = [part.strip() for part in str(values.get('target') or '').split(',')
              if part.strip()]
    start = str(values.get('from') or '').strip()
    end = str(values.get('to') or '').strip()
    try:
        recent_days = int(values.get('recentDays') or 30)
    except (TypeError, ValueError):
        raise HTTPException(400, 'recentDays 必须是整数')
    if recent_days not in (7, 15, 30):
        raise HTTPException(400, 'recentDays 只能是 7 / 15 / 30')
    import kpl_bp
    stamp = (_kpl_source_stamp(kpl_bp) if source == 'kpl'
             else (_camp_dir_stamp(MATCHES.parent / 'camp_details'), _dataset_stamp()))
    cache_key = ('compare', stamp, source, league, team, tuple(target), start, end, recent_days)
    cached = _BP_LAB_LOOKUP_CACHE.get(cache_key)
    if cached is not None:
        return cached
    try:
        result = period_compare(
            _bp_lab_games(source, league, '', ''),
            start=start, end=end, source=source, team=team,
            recent_days=recent_days, target=target or None,
        )
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    result['filters'] = {'source': source, 'league': league, 'team': team,
                         'target': target, 'from': start, 'to': end,
                         'recentDays': recent_days}
    if stamp is not None:
        if len(_BP_LAB_LOOKUP_CACHE) >= _BP_LAB_LOOKUP_CACHE_MAX:
            _BP_LAB_LOOKUP_CACHE.pop(next(iter(_BP_LAB_LOOKUP_CACHE)))
        _BP_LAB_LOOKUP_CACHE[cache_key] = result
    return result


@router.get('/api/v3/bp-lab/diagnose')
def bp_lab_diagnose(request: Request, repo=Depends(repository)):
    """己方英雄诊断 N01–N16：表现、趋势、异常、定位、归因、阵容对比。"""
    from bp_diagnose import build_diagnosis, default_hero

    values = request.query_params
    source = str(values.get('source') or 'kpl').strip()
    if source not in ('kpl', 'scrim'):
        raise HTTPException(400, 'source 只能是 kpl 或 scrim')
    league = str(values.get('league') or 'all').strip()
    if league not in ('all', 'kpl', 'challenger'):
        raise HTTPException(400, 'league 只能是 all / kpl / challenger')
    team = str(values.get('team') or '').strip()
    hero = str(values.get('hero') or '').strip()
    start = str(values.get('from') or '').strip()
    end = str(values.get('to') or '').strip()
    enemy_lineup = [part.strip() for part in
                    str(values.get('enemyLineup') or values.get('enemy_lineup') or '').split(',')
                    if part.strip()]
    try:
        recent_days = int(values.get('recentDays') or 30)
    except (TypeError, ValueError):
        raise HTTPException(400, 'recentDays 必须是整数')
    if recent_days not in (7, 15, 30):
        raise HTTPException(400, 'recentDays 只能是 7 / 15 / 30')
    if len(enemy_lineup) > 5:
        raise HTTPException(400, '敌方阵容最多 5 个英雄')
    import kpl_bp
    stamp = (_kpl_source_stamp(kpl_bp) if source == 'kpl'
             else (_camp_dir_stamp(MATCHES.parent / 'camp_details'), _dataset_stamp()))
    cache_key = ('diagnose', stamp, source, league, team, hero, start, end,
                 tuple(enemy_lineup), recent_days)
    cached = _BP_LAB_LOOKUP_CACHE.get(cache_key)
    if cached is not None:
        return cached
    try:
        games = _bp_lab_games(source, league, '', '', repo=repo)
        from collections import Counter
        names = Counter(str(g.get('team') or '') for g in games if g.get('team'))
        if not team:
            team = ("本队" if source == 'scrim' and names.get("本队")
                    else (names.most_common(1)[0][0] if names else ""))
        if not hero:
            hero = default_hero(games, team=team, recent_days=recent_days,
                                start=start, end=end)
        result = build_diagnosis(
            games, team=team, hero=hero, recent_days=recent_days,
            start=start, end=end, enemy_lineup=enemy_lineup, source=source,
        )
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    result['filters'] = {'source': source, 'league': league, 'team': team,
                         'hero': hero, 'from': start, 'to': end,
                         'enemyLineup': enemy_lineup, 'recentDays': recent_days}
    if stamp is not None:
        if len(_BP_LAB_LOOKUP_CACHE) >= _BP_LAB_LOOKUP_CACHE_MAX:
            _BP_LAB_LOOKUP_CACHE.pop(next(iter(_BP_LAB_LOOKUP_CACHE)))
        _BP_LAB_LOOKUP_CACHE[cache_key] = result
    return result


def _bp_lab_games(source, league, start, end, repo=None):
    """归一化 BP 概览的数据源；KPL 先按联赛类型过滤，再做日期过滤。"""
    from bp_intelligence import normalize_kpl, normalize_scrims
    import kpl_bp

    if source == 'kpl':
        raw = kpl_bp.load_games()
        if league == 'challenger':
            raw = [g for g in raw if '挑战者杯' in str(g.get('leagueName') or '')]
        elif league == 'kpl':
            raw = [g for g in raw if '挑战者杯' not in str(g.get('leagueName') or '')]
        games = normalize_kpl(raw)
    else:
        rows = bp_board().get('games') or []
        process_map = {}
        if repo is not None:
            from bp_process import link_scrim_process
            process_map = link_scrim_process(rows, repo.get()['matches'])
        games = normalize_scrims(rows, process_map=process_map)
    if start:
        games = [g for g in games if str(g.get('date') or '') >= start]
    if end:
        games = [g for g in games if str(g.get('date') or '') <= end]
    return games


@router.get('/api/v3/effect')
def training_effect_analysis():
    import workspace_store
    workspace = workspace_store.Workspace(DB).ensure_schema()
    return deep_analysis.training_effects(DB.parent / 'camp_details', workspace)


@router.get('/api/v3/team-training')
def team_training_ledger():
    """按对手的训练台账：训练计划里的排期 + 营地交手日自动归集。

    台账要读全部营地面板并交叉对局包（500 次文件读 + 605 次 JSON 解析，约
    0.6 秒），但结果只取决于这些文件和排期表；按（营地目录, 对局包 + DB）
    指纹缓存，改一局营地或排期就自动重算。
    """
    import team_clusters
    import workspace_store
    stamp = bp_board_stamp()
    if stamp[0] is not None:
        cached = _TEAM_TRAINING_CACHE.get(stamp)
        if cached is not None:
            return cached
    workspace = workspace_store.Workspace(DB).ensure_schema()
    payload = team_clusters.team_training(MATCHES.parent / 'camp_details', DB,
                                          workspace.list_schedules(), MATCHES)
    if stamp[0] is not None:
        if len(_TEAM_TRAINING_CACHE) >= _TEAM_TRAINING_CACHE_MAX:
            _TEAM_TRAINING_CACHE.clear()
        _TEAM_TRAINING_CACHE[stamp] = payload
    return payload


# ── 选手看板：营地十人面板 → 逐人逐局记录 ──────────────────────────────
# 选手页（选手档案 / 选手对比）共用这一份数据。
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
    global _players_cache, _players_at, _hero_facts_cache, _hero_facts_at
    _players_cache, _players_at = None, 0.0
    # 英雄详情的「选手使用榜」走 depth_api.build_facts；它也吃账号映射，
    # 认领/改名后不能还挂着旧昵称。
    _hero_facts_cache, _hero_facts_at = None, 0.0
    # 选手档案页走另一套带指纹 key 的看板缓存；只清 _players_cache 时，
    # 改名后档案页最长 60 秒仍按旧游戏名聚合。
    _PLAYERS_BOARD_CACHE.clear()


def _depth_identity_profile():
    """depth_api.build_facts 用的身份口径：players / player_accounts 是唯一来源。

    depth_api 原本只认 settings.aliases（旧口径），认领后英雄详情仍显示营地
    昵称。这里把账号映射编译成它认识的 profile 形状，并带一个 DB 指纹让
    facts 缓存跟着失效。
    """
    accounts = camp_accounts()
    home = own_team()
    roster, aliases, enemy_aliases, members = {}, {}, {}, []
    for info in accounts.values():
        player_id = str(info.get('playerId') or '')
        name = str(info.get('name') or '').strip()
        if not player_id or not name:
            continue
        team_name = str(info.get('teamName') or '').strip()
        own = info.get('teamId') == home['id'] or not team_name \
            or team_name.startswith('待命名')
        label = name if own or name.startswith(team_name + '.') else f'{team_name}.{name}'
        if player_id not in roster:
            members.append({'id': player_id, 'name': name, 'label': label,
                            'team': team_name, 'position': info.get('position') or ''})
        roster[player_id] = label
        nickname = _camp_name(info.get('nickname'))
        if nickname:
            (aliases if own else enemy_aliases)[nickname] = player_id
    try:
        stamp = str(DB.stat().st_mtime_ns) if DB.is_file() else ''
    except OSError:
        stamp = ''
    return {'teamName': home['name'], 'roster': roster, 'members': members,
            'aliases': aliases, 'enemyAliases': enemy_aliases, 'stamp': stamp}


def _panel_games():
    """营地面板 id → 对局标题 / 对手 / 日期，用于把面板挂回训练赛。"""
    index = {}
    # 通道删除/重建后旧 bundle 会留在 data/matches；这里只认还活着的通道，
    # 否则面板行可能链到已删除的那一份（打开是重复局或 404）。
    live_channels = set()
    if DB.is_file():
        try:
            with closing(sqlite3.connect(f'file:{DB.as_posix()}?mode=ro', uri=True)) as connection:
                live_channels = {str(row[0]) for row in connection.execute('SELECT id FROM channels')}
        except sqlite3.Error:
            live_channels = set()
    try:
        import opponent_identity
        by_seq = opponent_identity.resolve(DB, opponent_identity.camp_dir_for(MATCHES))['bySeq']
    except Exception:  # noqa: BLE001 - 解析失败退回数据包里的手写队名
        by_seq = {}
    for path in (ROOT / 'data' / 'matches').glob('*.json'):
        try:
            body = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        match = body.get('match') or {}
        key = str(match.get('key') or path.stem)
        if (live_channels and key.startswith('channel-')
                and key[8:] not in live_channels):
            continue
        seq = str((match.get('campBp') or {}).get('gameSeq') or '')
        if not seq:
            continue
        date = match.get('date') or {}
        index[seq] = {'key': key,
                      'title': match.get('title') or '',
                      'opponent': by_seq.get(seq) or (match.get('opponent') or '').strip(),
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
                    'minutes': minutes,  # 聚合口径 Σ总量/Σ分钟，逐局曲线仍用上面的 gpm/dpm/dtpm
                    # 输出两套口径分开存，避免「分均输出」和「输出占比」混用同一个分子。
                    'heroDamage': _camp_number(stats.get('totalHeroHurtCnt')) or 0,
                    'ctrlTime': _camp_number(stats.get('ctrlTime')) or 0,
                    'towerCnt': _camp_number(stats.get('towerCnt')) or 0,
                    'monsterCoin': _camp_number(stats.get('monsterCoin')) or 0,
                    'healCnt': _camp_number(stats.get('healCnt')) or 0,
                    'cs': _camp_number(stats.get('killSoldier')) or 0,
                    'gpm': round(item['gold'] / minutes) if minutes else None,
                    'dpm': round(item['damage'] / minutes) if minutes else None,
                    'hdpm': round((_camp_number(stats.get('totalHeroHurtCnt')) or 0) / minutes) if minutes else None,
                    'ctrlPerMin': round((_camp_number(stats.get('ctrlTime')) or 0) / minutes, 2) if minutes else None,
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
    # 本队名单仍只用于 roster；身份索引要覆盖全部战队，否则 matching 保存的
    # 对手选手会在 players-board 里丢掉 memberId，选手档案只能补出空卡。
    all_players = []
    members = []
    team_names = {}
    try:
        import workspace_store
        workspace = workspace_store.Workspace(DB)
        all_players = [dict(player) for player in workspace.list_players()]
        team_names = {team['id']: team['name'] for team in workspace.list_teams()}
        # 归属战队以选手ID主数据的 team_id 为准。新添加的选手只建了 ID、还没走
        # 过「命名并归队」时 player_accounts 里没有映射，不能因此显示「未归队」。
        members = [dict(player, label=player.get('name') or '',
                        teamName=team_names.get(str(player.get('team_id') or ''), ''))
                   for player in all_players if player.get('team_id') == home['id']]
    except sqlite3.Error:
        pass
    if not members:
        for member in (profile.get('members') or profile.get('roster') or []):
            if member.get('archived') or (member.get('team') and member.get('team') != team_name):
                continue
            item = dict(member)
            item['label'] = item.get('label') or item.get('name') or ''
            item['position'] = item.get('position') or ''
            item['teamName'] = item.get('teamName') or item.get('team') or team_name
            members.append(item)
    aliases = {str(key): str(value) for key, value in (profile.get('aliases') or {}).items()}
    # 选手 ID 索引也要带 teamName：昵称池 / 匹配规则映射走的是 member_by_id，
    # 只带 team_id 会让档案板里已归队的选手显示成「未归队」。
    member_by_id = {str(member['id']): dict(member,
                    teamName=team_names.get(str(member.get('team_id') or ''), ''))
                    for member in all_players if member.get('id')}
    for member in members:
        if member.get('id'):
            member_by_id.setdefault(str(member['id']), member)
    name_to_member = {'own': {}, 'enemy': {}}
    for member in members:
        for label in (member.get('label'), member.get('name')):
            if label:
                name_to_member['own'][_camp_name(label)] = member
    for alias, member_id in aliases.items():
        member = member_by_id.get(str(member_id))
        if member:
            name_to_member['own'][_camp_name(alias)] = member
    # 匹配与编组落在 player_nickname_pool（不是 player_accounts）。own/enemy
    # 分开索引，避免同名双方串人；规则与昵称池都要在连接关闭前读完。
    try:
        with closing(sqlite3.connect(f'file:{DB.as_posix()}?mode=ro', uri=True)) as pool_connection:
            pool_rows = pool_connection.execute(
                "SELECT side, player_id, nickname FROM player_nickname_pool"
                " WHERE player_id IS NOT NULL AND player_id<>''").fetchall()
            rule_rows = pool_connection.execute(
                "SELECT side, player_id, nickname FROM matching_rules"
                " WHERE enabled=1 AND player_id IS NOT NULL AND player_id<>''").fetchall()
        for side, player_id, nickname in pool_rows:
            member = member_by_id.get(str(player_id))
            side_key = 'enemy' if str(side) == 'enemy' else 'own'
            if nickname and member:
                name_to_member[side_key].setdefault(_camp_name(nickname), member)
        # 匹配页最容易用到的动作是「建规则」，它此前只写 matching_rules。
        # 规则就是权威绑定，档案页也要认，否则只建规则不点归档时仍显示未匹配。
        for side, player_id, nickname in rule_rows:
            member = member_by_id.get(str(player_id))
            side_key = 'enemy' if str(side) == 'enemy' else 'own'
            if nickname and member:
                name_to_member[side_key].setdefault(_camp_name(nickname), member)
    except sqlite3.Error:
        pass

    buckets = {}
    for row in records:
        bucket = buckets.setdefault((row['side'], row['name']), {
            'name': row['name'], 'side': row['side'], 'games': 0, 'wins': 0, 'decided': 0,
            '_kda': [], '_gpm': [], '_dpm': [], '_dtpm': [], '_part': [], '_goldShare': [],
            '_damageShare': [], '_takenShare': [], '_rating': [], 'mvp': 0, '_cs': [],
            '_gold': 0.0, '_damage': 0.0, '_taken': 0.0,
            '_gpmMin': 0.0, '_dpmMin': 0.0, '_dtpmMin': 0.0,
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
        # 比率类指标按「总量÷总分钟」聚合，和 /api/players 同一口径；
        # 上面的逐局列表只保留给单局曲线，不再拿来算总览 KPI。
        minutes = row.get('minutes')
        if isinstance(minutes, (int, float)) and minutes > 0:
            for total_field, minute_field, source in (('_gold', '_gpmMin', 'gold'),
                                                      ('_damage', '_dpmMin', 'damage'),
                                                      ('_taken', '_dtpmMin', 'taken')):
                if isinstance(row.get(source), (int, float)):
                    bucket[total_field] += row[source]
                    bucket[minute_field] += minutes
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

    def rate(total, minutes):
        return round(total / minutes) if minutes else None

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
                                         '_damageShare': [], '_rating': [],
                                         '_gold': 0.0, '_damage': 0.0, '_gpmMin': 0.0, '_dpmMin': 0.0})
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
            minutes = row.get('minutes')
            if isinstance(minutes, (int, float)) and minutes > 0:
                if isinstance(row.get('gold'), (int, float)):
                    item['_gold'] += row['gold']
                    item['_gpmMin'] += minutes
                if isinstance(row.get('damage'), (int, float)):
                    item['_damage'] += row['damage']
                    item['_dpmMin'] += minutes
        return {name: {
            'games': item['games'], 'wins': item['wins'], 'decided': item['decided'],
            'winRate': round(item['wins'] / item['decided'] * 100, 1) if item['decided'] else None,
            'kda': mean(item['_kda'], 2), 'gpm': rate(item['_gold'], item['_gpmMin']),
            'dpm': rate(item['_damage'], item['_dpmMin']),
            'participation': mean(item['_part'], 1), 'damageShare': mean(item['_damageShare'], 1),
            'rating': mean(item['_rating'], 1), 'mvp': item['mvp'],
        } for name, item in out.items()}

    for bucket in buckets.values():
        lane = bucket['lanes'].most_common(1)[0][0] if bucket['lanes'] else ''
        mapped = next((accounts[account] for account in bucket['_accounts'] if account in accounts), None)
        member = mapped or name_to_member.get(bucket['side'], {}).get(_camp_name(bucket['name']))
        member_id = (member or {}).get('id') or (member or {}).get('playerId') or None
        players.append({
            'name': bucket['name'], 'lane': lane,
            'laneMix': [{'lane': name, 'games': n} for name, n in bucket['lanes'].most_common()],
            'side': bucket['side'], 'bound': bool(member), 'memberId': member_id,
            'accountIds': bucket['_accounts'],
            'nicknames': [nick for nick, _ in bucket['_nicknames'].most_common()],  # 全量：档案页要按昵称逐个解绑
            'teamName': (mapped or {}).get('teamName') or (member or {}).get('teamName') or '',
            'games': bucket['games'], 'wins': bucket['wins'], 'decided': bucket['decided'],
            'winRate': round(bucket['wins'] / bucket['decided'] * 100, 1) if bucket['decided'] else None,
            'kda': mean(bucket['_kda'], 2), 'gpm': rate(bucket['_gold'], bucket['_gpmMin']),
            'dpm': rate(bucket['_damage'], bucket['_dpmMin']),
            'dtpm': rate(bucket['_taken'], bucket['_dtpmMin']),
            'participation': mean(bucket['_part'], 1),
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
             'pairs': pairs[:24], 'roster': roster,
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


# ── 选手个人页：按实际分路的全量逐局事实 ─────────────────────────────
# 与 players-board 分开：档案与对比共用页读聚合，个人页读这名选手的每一局。
# 分位样本按「实际分路」而不是选手主位置聚合，多位置选手不再被混算。
_CAPABILITY_CN = {
    'engage': '强开', 'peel': '保护', 'burst': '爆发', 'sustained': '持续输出',
    'frontline': '前排', 'waveclear': '清线', 'roam': '支援', 'macro': '运营',
    'resilience': '容错',
}
_hero_meta_cache = None


def _hero_meta():
    """英雄职业 / 默认分路 / 九维战术能力标签，一次读入即可。"""
    global _hero_meta_cache
    if _hero_meta_cache is not None:
        return _hero_meta_cache
    import hero_roles
    meta = {}
    try:
        raw = json.loads((ROOT / 'resources' / 'hero_tags.json').read_text(encoding='utf-8'))
        for hero, item in (raw.get('heroes') or {}).items():
            roles = hero_roles.role_of(hero) or {}
            matrix = item.get('matrix') or {}
            meta[hero] = {
                'type': item.get('defaultType') or '',
                'lane': item.get('defaultLane') or '',
                'compat': item.get('compat') or '',
                'caps': [_CAPABILITY_CN[key] for key, value in roles.items() if value],
                'control': 1 if matrix.get('控制') else 0,
                'support': 1 if matrix.get('支援') else 0,
            }
    except (OSError, ValueError):
        meta = {}
    _hero_meta_cache = meta
    return meta


def _lane_samples(records):
    """每个「选手 × 实际分路」一个样本；分位、排行榜与最低局数门槛都基于它。"""
    fields = ('kda', 'gpm', 'dpm', 'hdpm', 'participation', 'assists', 'taken', 'takenShare',
              'damageShare', 'goldShare', 'rating', 'ctrlPerMin', 'dtpm')
    buckets = {}
    for row in records:
        item = buckets.setdefault((row['name'], row['lane']), {
            'name': row['name'], 'lane': row['lane'], 'side': row['side'],
            'games': 0, 'wins': 0, 'decided': 0, 'mvp': 0,
            **{'_' + key: [] for key in fields}})
        item['games'] += 1
        if row['result'] in ('win', 'loss'):
            item['decided'] += 1
            if row['result'] == 'win':
                item['wins'] += 1
        if row.get('mvp'):
            item['mvp'] += 1
        for key in fields:
            value = row.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                item['_' + key].append(value)
    out = defaultdict(list)
    for item in buckets.values():
        cell = {'name': item['name'], 'lane': item['lane'], 'side': item['side'],
                'games': item['games'], 'wins': item['wins'], 'decided': item['decided'],
                'mvp': item['mvp'],
                'winRate': round(item['wins'] / item['decided'] * 100, 1) if item['decided'] else None}
        for key in fields:
            values = item['_' + key]
            cell[key] = round(sum(values) / len(values), 2) if values else None
        out[item['lane']].append(cell)
    return {lane: sorted(group, key=lambda cell: -cell['games']) for lane, group in out.items()}


def _lane_distributions(records):
    """同分路逐局记录的指标分布。

    这批数据里绝大多数游戏名只出现 1 局，用「选手级均值」做分位会变成自己跟自己比；
    分位参照改用同分路的逐局记录，样本基础在页面上按「N 局」写明。
    """
    keys = ('kda', 'gpm', 'dpm', 'hdpm', 'participation', 'takenShare',
            'damageShare', 'goldShare', 'rating', 'ctrlPerMin', 'dtpm', 'monsterCoin')
    out = defaultdict(lambda: defaultdict(list))
    for row in records:
        for key in keys:
            value = row.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                out[row['lane']][key].append(round(float(value), 2))
    return {lane: dict(groups) for lane, groups in out.items()}


def _player_id_scope(name):
    """把详情页的路由参数解析成取数范围。

    选手档案卡片链过来的是「选手ID」名（不是游戏名）：一个 ID 可能挂多个游戏名，
    这里按 memberId 把这些号全找出来，逐局数据才能合在同一页里看。
    传游戏名时保持老行为（只认那一个号），所以旧的深链不会失效。
    """
    board = _players_board()
    identity = board.get('identity') or {}
    members = identity.get('members') or []
    wanted = str(name or '').strip()
    member = next((m for m in members
                   if str(m.get('label') or m.get('name') or '').strip() == wanted), None)
    if not member:
        # 别的分析页点进来的还是游戏名。只要这个号已经在「匹配与编组」
        # 挂到选手ID上，就自动切到 ID 口径：名字换成 ID，多个号合并统计。
        matched = next((p for p in board.get('players') or []
                        if _camp_name(p.get('name')) == _camp_name(wanted)
                        and p.get('memberId')), None)
        if matched:
            member = next((m for m in members
                           if str(m.get('id')) == str(matched.get('memberId'))), None)
            if member:
                wanted = str(member.get('label') or member.get('name') or wanted)
    if not member:
        # 对手选手也走选手分析：对方战队登记的「名字 / 营地 ID / 内部 ID」
        # 都能作为入口。匹配与编组的昵称池是权威映射，按 playerId 把同一人的
        # 多个游戏号合进来，与本队选手 ID 的口径一致，否则「4」只能查到空页。
        try:
            import workspace_store
            registered = [dict(p) for p in workspace_store.Workspace(DB).list_players()]
            short = wanted.rsplit('.', 1)[-1]
            target = next((p for p in registered
                           if wanted in (str(p.get('name') or '').strip(),
                                         str(p.get('camp_user_id') or '').strip(),
                                         str(p.get('id') or '').strip())
                           or short == str(p.get('name') or '').strip()), None)
            pool_rows = []
            try:
                with closing(sqlite3.connect(f'file:{DB.as_posix()}?mode=ro', uri=True)) as connection:
                    pool_rows = connection.execute(
                        'SELECT side, player_id, nickname FROM player_nickname_pool'
                        " WHERE player_id IS NOT NULL AND player_id<>''").fetchall()
            except sqlite3.Error:
                pass
            if not target:
                by_id = {str(p.get('id') or ''): p for p in registered}
                target = next((by_id.get(str(pid)) for _, pid, nickname in pool_rows
                               if nickname and nickname == wanted and str(pid) in by_id), None)
            if target:
                pid = str(target.get('id') or '')
                names = {str(nickname).strip() for _, player_id, nickname in pool_rows
                         if str(player_id) == pid and nickname}
                for extra in (target.get('name'), target.get('camp_user_id')):
                    if extra:
                        names.add(str(extra).strip())
                names.discard('')
                if not names:
                    names = {wanted}
                display = str(target.get('name') or wanted).strip() or wanted
                return {'display': display, 'names': names, 'member': None,
                        'board': board, 'opponent': True}
        except sqlite3.Error:
            pass
        return {'display': wanted, 'names': {wanted} if wanted else set(),
                'member': None, 'board': board}
    member_id = str(member.get('id') or '')
    names = set()
    for player in board.get('players') or []:
        if str(player.get('memberId') or '') != member_id:
            continue
        if player.get('name'):
            names.add(str(player['name']))
        for nickname in player.get('nicknames') or []:
            if nickname:
                names.add(str(nickname))
    if not names:
        names = {wanted}
    return {'display': wanted, 'names': names, 'member': member, 'board': board}


def _player_detail(name):
    """一名选手的全量逐局事实 + 十人上下文 + 同位置样本 + 英雄标签。

    参数是选手ID时合并其名下所有游戏名的对局，页面上的名字一律换成选手ID；
    参数仍是游戏名时走原来的单号口径。
    """
    scope = _player_id_scope(name)
    display = scope['display']
    wanted = {_camp_name(value) for value in scope['names']}
    facts = _camp_records()
    games_all, records = facts['games'], facts['records']
    mine = [row for row in records if _camp_name(row['name']) in wanted]
    if not mine:
        return {'player': None, 'identity': {}, 'rows': [], 'laneSamples': {},
                'laneDistributions': {}, 'heroMeta': {}, 'opponents': [],
                'summary': {'games': 0, 'name': display}}
    game_by_id = {game['id']: game for game in games_all}
    meta = _hero_meta()
    # 教练在对局里手填的 10 分钟经济存在 match_meta 覆盖层；逐局事实按
    # 「阵营-槽位」索引，这里按对局缓存详情，再按阵营 + 英雄定位到这名选手。
    gold10_detail_cache = {}
    # 打野细分按最终装备（肉刀/红法刀）判定，和单局页/规则中心同口径；
    # 英雄静态标签只在没有 blade 数据时兜底。
    blade_by_game = {}
    for game in games_all:
        seq = str(game.get('id') or '').strip()
        if not seq.isdigit():
            continue
        path = MATCHES.parent / 'camp_details' / f'{seq}.json'
        if not path.is_file():
            continue
        table = camp_tiles.read_detail(path)
        blades = {}
        for (camp, hero), entry in table.items():
            if entry.get('blade'):
                blades[(camp, hero)] = entry['blade']
        if blades:
            blade_by_game[seq] = blades
    match_repo = AnalysisRepository(DB, MATCHES, IMPORTS, OFFICIAL)

    def coach_gold10(game, row):
        match_key = game.get('match') or ''
        if not match_key:
            return None
        if match_key not in gold10_detail_cache:
            try:
                gold10_detail_cache[match_key] = match_repo.match_detail(match_key) or {}
            except Exception:  # noqa: BLE001 - 单局详情读不到就按没填处理
                gold10_detail_cache[match_key] = {}
        detail = gold10_detail_cache[match_key]
        saved = detail.get('gold10') or {}
        if not saved:
            return None
        camp = {'蓝方': 'blue', '红方': 'red'}.get(row.get('camp'), row.get('camp'))
        for player in detail.get('players') or []:
            if player.get('camp') != camp:
                continue
            if (player.get('hero') == row.get('hero')
                    or _camp_name(player.get('name')) == _camp_name(row.get('name'))):
                return saved.get(f"{camp}-{player.get('slot')}")
        return None

    # 系列赛归组：training_series_games.match_key 就是训练赛档案的 key。
    series_by_match = {}
    if DB.is_file():
        try:
            with closing(sqlite3.connect(f'file:{DB.as_posix()}?mode=ro', uri=True)) as connection:
                for match_key, index, sid, best_of, opponent, start_at in connection.execute(
                        'SELECT g.match_key, g.game_index, s.id, s.best_of, s.opponent, s.start_at'
                        ' FROM training_series_games g JOIN training_series s ON s.id = g.series_id'):
                    series_by_match[str(match_key)] = {
                        'id': sid, 'index': index, 'bestOf': best_of,
                        'opponent': opponent or '', 'date': start_at or ''}
        except sqlite3.Error:
            pass

    # 对手强度：本队对该对手的交手胜率，作为分层依据（越低越强）。
    opp = {}
    for game in games_all:
        label = game.get('opponent')
        if not label:
            continue
        item = opp.setdefault(label, {'name': label, 'games': 0, 'wins': 0, 'decided': 0})
        item['games'] += 1
        if game['result'] in ('win', 'loss'):
            item['decided'] += 1
            if game['result'] == 'win':
                item['wins'] += 1
    opponents = [dict(item, winRate=round(item['wins'] / item['decided'] * 100, 1) if item['decided'] else None)
                 for item in sorted(opp.values(), key=lambda cell: -cell['games'])]

    # 同局十人回填完整面板统计，对位 / 搭档 / 阵容分析才不用只看 KDA 与经济。
    record_by_key = {(item['gameId'], item['accountId']): item for item in records}

    # 本队游戏名 → 选手ID名：十人面板里的队友也统一按 ID 显示；
    # 对手没挂选手ID就保留游戏名，不硬套自己战队的 ID。
    board = scope['board']
    members_by_id = {str(m.get('id')): m for m in (board.get('identity') or {}).get('members') or []}
    name_to_display = {}
    for candidate in board.get('players') or []:
        owner = members_by_id.get(str(candidate.get('memberId') or ''))
        if not owner:
            continue
        label = owner.get('label') or owner.get('name')
        if not label:
            continue
        for alias in [candidate.get('name')] + list(candidate.get('nicknames') or []):
            if alias:
                name_to_display[_camp_name(alias)] = label

    def compact(items, game_id):
        out = []
        for cell in items:
            full = record_by_key.get((game_id, str(cell.get('accountId') or ''))) or {}
            out.append({
                'name': name_to_display.get(_camp_name(cell.get('name')), cell.get('name') or ''),
                'hero': cell.get('hero') or '',
                'lane': cell.get('lane') or '', 'gold': cell.get('gold'),
                'kda': cell.get('kda'), 'cs': full.get('cs'),
                'participation': full.get('participation'), 'rating': full.get('rating'),
                'hdpm': full.get('hdpm'), 'gpm': full.get('gpm'),
                'kills': full.get('kills'), 'deaths': full.get('deaths'),
                'assists': full.get('assists'),
            })
        return out

    rows = []
    for row in sorted(mine, key=lambda item: (item['sort'], item['gameId'])):
        game = game_by_id.get(row['gameId']) or {}
        side = row['side']
        own_side = game.get(side) or []
        foe_side = game.get('enemy' if side == 'own' else 'own') or []
        foe = next((cell for cell in foe_side if cell['lane'] == row['lane']), None)
        tag = meta.get(row.get('hero') or '') or {}
        item = dict(row)
        # 逐局事实保留原游戏名供追溯，页面上的名字一律换成选手ID。
        item['gameName'] = row.get('name') or ''
        item['name'] = display
        item.update({
            'duration': game.get('duration'), 'title': game.get('title') or '',
            'match': game.get('match') or '', 'ownCamp': game.get('ownCamp') or '',
            'opponentTeam': game.get('opponent') or '',
            'heroType': tag.get('type') or '', 'heroDefaultLane': tag.get('lane') or '',
            'heroCompat': tag.get('compat') or '', 'caps': tag.get('caps') or [],
            'heroControl': tag.get('control') or 0, 'heroSupport': tag.get('support') or 0,
            'mates': compact([cell for cell in own_side if cell['name'] != row['name']], row['gameId']),
            'foes': compact(foe_side, row['gameId']),
            'foe': compact([foe], row['gameId'])[0] if foe else None,
            'lineup': [cell.get('hero') or '' for cell in own_side],
            'enemyLineup': [cell.get('hero') or '' for cell in foe_side],
            'series': series_by_match.get(game.get('match') or ''),
            'gold10': coach_gold10(game, row),
            'blade': blade_by_game.get(str(game.get('id') or ''), {}).get(
                (('blue' if '蓝' in str(row.get('camp') or '') else
                  'red' if '红' in str(row.get('camp') or '') else ''),
                 str(row.get('hero') or ''))),
        })
        rows.append(item)

    member = scope['member']
    player = next((p for p in board['players'] if _camp_name(p['name']) in wanted), None)
    account_ids, nicknames = [], []
    if member:
        for candidate in board['players']:
            if str(candidate.get('memberId') or '') != str(member.get('id') or ''):
                continue
            for account in candidate.get('accountIds') or []:
                if account not in account_ids:
                    account_ids.append(account)
            for nickname in candidate.get('nicknames') or []:
                if nickname not in nicknames:
                    nicknames.append(nickname)
    identity = {
        'bound': bool(member),
        'playerId': (member or {}).get('id') or (player or {}).get('memberId') or '',
        'teamName': (member or {}).get('teamName') or (player or {}).get('teamName') or '',
        'accountIds': account_ids or (player or {}).get('accountIds') or [],
        'nicknames': nicknames or sorted(scope['names']),
        'ownNames': sorted(scope['names']),
        'side': (player or {}).get('side') or rows[0]['side'],
        'lane': (player or {}).get('lane') or (member or {}).get('position') or '',
        'laneMix': (player or {}).get('laneMix') or [],
    }
    # 英雄替代候选要拿 KPL 职业赛胜率做外部参照；与训练赛分开取，不混算。
    kpl_heroes = match_repo.hero_stats({'sources': ['kpl']})
    kpl_hero_stats = {str(row.get('hero') or ''): {'winRate': row.get('winRate'),
                                                   'picks': row.get('picks')}
                      for row in kpl_heroes if row.get('hero')}
    return {
        'player': player, 'identity': identity, 'rows': rows,
        'laneSamples': _lane_samples(records),
        'laneDistributions': _lane_distributions(records), 'heroMeta': meta,
        # 打野细分主体的英雄标签兜底：选手页拿不到本局打野刀时按这里分野核/坦野。
        'heroLaneTypes': _icon_metadata().get('heroTypes') or {},
        'opponents': opponents, 'kplHeroStats': kpl_hero_stats,
        'summary': {'games': len(rows), 'name': display,
                    'days': len({row['day'] for row in rows if row['day']}),
                    'heroes': len({row['hero'] for row in rows if row['hero']})},
    }


@router.get('/api/v3/player-detail')
def player_detail(player: str = ''):
    """选手个人页数据：全量逐局 + 按实际分路的同位置样本 + 英雄标签。"""
    payload = _player_detail(player)
    return Response(content=json.dumps(payload, ensure_ascii=False, separators=(',', ':')),
                    media_type='application/json; charset=utf-8')


@router.get('/api/v3/players-board')
def players_board():
    """选手板块共用聚合：逐人逐局记录、搭档、认领状态。

    整份 board 约 1.3 MB、纯聚合要 0.4 秒，而它只取决于营地面板与选手主数据；
    按（营地目录, 对局包 + DB）指纹缓存，选手档案 / 对比 / 战队页共用一份。
    """
    stamp = bp_board_stamp() + (_PLAYERS_BOARD_CACHE_VERSION,)
    if stamp[0] is not None:
        cached = _PLAYERS_BOARD_CACHE.get(stamp)
        if cached is not None:
            return json_response(cached)
    key_id = _cache_key_id(stamp)
    persisted = _report_disk_read(_PLAYERS_BOARD_DISK, key_id, 'board')
    if persisted is not None:
        _PLAYERS_BOARD_CACHE[stamp] = persisted
        return json_response(persisted)
    board = _players_board()
    if stamp[0] is not None:
        if len(_PLAYERS_BOARD_CACHE) >= _PLAYERS_BOARD_CACHE_MAX:
            _PLAYERS_BOARD_CACHE.clear()
        _PLAYERS_BOARD_CACHE[stamp] = board
        _report_disk_write(_PLAYERS_BOARD_DISK, key_id, 'board', board)
    return json_response(board)


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
        _hero_facts_cache = depth_api.build_facts(ROOT, profile=_depth_identity_profile())
        _hero_facts_at = monotonic()
    return _hero_facts_cache


@router.get('/api/v3/hero-detail/{hero}')
def hero_detail(hero: str, repo=Depends(repository)):
    """英雄详情页的聚合数据：选手使用榜 / 战队使用 / 本队均值对照 / 成长曲线 / 选手出装。

    全部从同一份营地逐行面板算出，避免前端把多个来源的口径混在一起。
    """
    base = {'sources': list(DEFAULT_SOURCES)}
    # 只算完整局：partial 行没有 gpm/kda，计入场次/胜率会让分母和指标样本对不上。
    hero_rows, _ = repo._aggregate_rows({**base, 'hero': hero})
    all_rows, _ = repo._aggregate_rows(base)
    hero_rows = [row for row in hero_rows if row.get('isOwn')]
    all_rows = [row for row in all_rows if row.get('isOwn')]

    def mean(rows, key):
        values = [row[key] for row in rows if isinstance(row.get(key), (int, float))]
        return round(sum(values) / len(values), 2) if values else None

    def rate(rows, total_key):
        """分均类 KPI 统一 Σ总量/Σ分钟；逐局均值只用于曲线/分布。"""
        total = 0.0
        minutes = 0.0
        found = False
        for row in rows:
            value, span = row.get(total_key), row.get('minutes')
            if isinstance(value, (int, float)) and isinstance(span, (int, float)) and span > 0:
                total += value
                minutes += span
                found = True
        return round(total / minutes) if found and minutes else None

    def group(rows, field):
        buckets = {}
        for row in rows:
            name = row.get(field) or '未标注'
            item = buckets.setdefault(name, {'name': name, 'games': 0, 'wins': 0,
                                            'decided': 0, '_kda': [], '_gold': 0.0,
                                             '_damage': 0.0, '_taken': 0.0, '_minutes': 0.0})
            item['games'] += 1
            if row.get('result') in ('win', 'loss'):
                item['decided'] += 1
                if row['result'] == 'win':
                    item['wins'] += 1
            if isinstance(row.get('kda'), (int, float)):
                item['_kda'].append(row['kda'])
            for key, bucket in (('gold', '_gold'), ('damage', '_damage'),
                                ('taken', '_taken'), ('minutes', '_minutes')):
                if isinstance(row.get(key), (int, float)):
                    item[bucket] += row[key]
        result = [{
            'name': item['name'], 'games': item['games'], 'wins': item['wins'],
            'decided': item['decided'],
            'winRate': round(item['wins'] / item['decided'] * 100, 1) if item['decided'] else None,
            'kda': round(sum(item['_kda']) / len(item['_kda']), 2) if item['_kda'] else None,
            'gpm': round(item['_gold'] / item['_minutes']) if item['_minutes'] else None,
        } for item in buckets.values()]
        return sorted(result, key=lambda x: -x['games'])[:12]

    league = {key: {'hero': mean(hero_rows, key), 'all': mean(all_rows, key)}
              for key in ('kda', 'participation', 'gold', 'cs')}
    league['gpm'] = {'hero': rate(hero_rows, 'gold'), 'all': rate(all_rows, 'gold')}
    league['dpm'] = {'hero': rate(hero_rows, 'damage'), 'all': rate(all_rows, 'damage')}
    league['tpm'] = {'hero': rate(hero_rows, 'taken'), 'all': rate(all_rows, 'taken')}

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


# ── 本队英雄详情（英雄页第三个页签） ─────────────────────────────────
# 三块内容一次给齐：① 本队选手逐英雄使用 / 胜率 / 近期趋势；② 分路 × 英雄
# 按规则中心的指标逐项定档；③ 组合池里的英雄组合按近期窗口算胜率场次。
# 全部只读同一份营地逐人面板，日期用仓库的 dateKey（可能是 MM-DD），
# 用数据里最后一天当锚点补齐年份，避免「今天没有训练赛」时窗口全空。
_THD_PERIODS = (3, 7, 30)


@router.get('/api/v3/team-hero-insight')
def team_hero_insight(repo=Depends(repository)):
    import camp_tiles
    import combo_pool
    import grade_rules
    import hero_external_stats

    rows, _ = repo._selected_rows({'sources': list(DEFAULT_SOURCES)})
    own = [row for row in rows if row.get('isOwn') and row.get('hero')]
    # 平板卡片字段（视野价值、控制时长、有效承伤等）原本只挂在单局详情上。
    # 战队英雄洞察用的是扁平分析行，不补挂这些规则会全部静默跳过。
    seq_by_match = {}
    for match in repo.get().get('matches') or []:
        seq = camp_tiles.game_seq(match) or str(
            (match.get('campBp') or {}).get('gameSeq') or '').strip()
        if seq:
            seq_by_match[str(match.get('key') or '')] = seq
    tile_tables = {}

    def tiles_for(row):
        seq = seq_by_match.get(str(row.get('matchKey') or ''))
        if not seq:
            return None
        if seq not in tile_tables:
            path = MATCHES.parent / 'camp_details' / f'{seq}.json'
            tile_tables[seq] = camp_tiles.read_detail(path) if path.is_file() else {}
        key = (str(row.get('camp') or ''), str(row.get('hero') or ''))
        return (tile_tables[seq].get(key) or {}).get('tiles')

    for row in own:
        tiles = tiles_for(row)
        if tiles:
            row['campTiles'] = tiles
        seq = seq_by_match.get(str(row.get('matchKey') or ''))
        if seq and seq in tile_tables:
            entry = tile_tables[seq].get(
                (str(row.get('camp') or ''), str(row.get('hero') or ''))) or {}
            if entry.get('blade'):
                row['blade'] = entry['blade']
    full_keys = [str(row.get('dateKey') or '') for row in own
                 if len(str(row.get('dateKey') or '')) == 10]
    try:
        base_date = date.fromisoformat(max(full_keys)) if full_keys else date.today()
    except ValueError:
        base_date = date.today()

    def day_of(row):
        key = str(row.get('dateKey') or '')
        if len(key) == 10:
            return key
        if len(key) == 5 and key[2] == '-':
            # 老表格只有 MM-DD：按最近一次完整日期的年份补齐，跨年往前推一年。
            try:
                month, day = int(key[:2]), int(key[3:])
                year = base_date.year - (1 if (month, day) > (base_date.month, base_date.day) else 0)
                return date(year, month, day).isoformat()
            except ValueError:
                return ''
        return ''

    own = [(row, day_of(row)) for row in own]
    days = sorted({day for _, day in own if day})
    anchor = days[-1] if days else base_date.isoformat()
    anchor_date = date.fromisoformat(anchor)

    def bounds(days_count):
        return ((anchor_date - timedelta(days=days_count)).isoformat(), anchor,
                (anchor_date - timedelta(days=2 * days_count)).isoformat(),
                (anchor_date - timedelta(days=days_count)).isoformat())

    def in_span(day, lo, hi):
        return bool(day) and lo < day <= hi

    def stat(items):
        games = len(items)
        decided = sum(1 for row in items if row.get('result') in ('win', 'loss'))
        wins = sum(1 for row in items if row.get('result') == 'win')
        return {'games': games, 'wins': wins, 'decided': decided,
                'winRate': round(wins / decided * 100, 1) if decided else None}

    def change(cur, prev):
        """环比一律给百分比（不用 pp）：(本期-上期)/上期。上期缺失返回 None。"""
        if cur is None or prev in (None, 0):
            return None
        return round((cur - prev) / abs(prev) * 100, 1)

    def spans(items, days_count):
        lo, hi, plo, phi = bounds(days_count)
        return ([row for row, day in items if in_span(day, lo, hi)],
                [row for row, day in items if in_span(day, plo, phi)])

    # ① 逐英雄：整体 / 选手拆分 / 窗口环比 / 近 7 天逐日趋势
    by_hero = defaultdict(list)
    for row, day in own:
        by_hero[row['hero']].append((row, day))
    heroes = []
    for hero, items in by_hero.items():
        lane = Counter((row.get('position') or '') for row, _ in items).most_common(1)
        by_period = {}
        for n in _THD_PERIODS:
            cur, prev = spans(items, n)
            a, b = stat(cur), stat(prev)
            by_period[str(n)] = {'current': a, 'previous': b,
                                 'change': change(a['winRate'], b['winRate'])}
        players = []
        by_player = defaultdict(list)
        for row, day in items:
            by_player[row.get('label') or '未知选手'].append((row, day))
        for name, pitems in by_player.items():
            cur, prev = spans(pitems, 7)
            a, b = stat(cur), stat(prev)
            vs = [row for row, _ in pitems if row.get('opponent')]
            players.append({'name': name, 'games': len(pitems),
                            'winRate': stat([row for row, _ in pitems])['winRate'],
                            'vsWinRate': stat(vs)['winRate'] if vs else None,
                            'recent': a, 'change': change(a['winRate'], b['winRate'])})
        players.sort(key=lambda x: -x['games'])
        trend = []
        for back in range(6, -1, -1):
            day = (anchor_date - timedelta(days=back)).isoformat()
            trend.append({'date': day, **stat([row for row, d in items if d == day])})
        ext = hero_external_stats.hero_fields(hero)
        heroes.append({'hero': hero, 'lane': lane[0][0] if lane else '',
                       **stat([row for row, _ in items]),
                       'vsWinRate': stat([row for row, _ in items if row.get('opponent')])['winRate'],
                       'kplWinRate': ext.get('kplWinRate'), 'kplGames': ext.get('kplGames'),
                       'players': players, 'byPeriod': by_period, 'trend7': trend})
    heroes.sort(key=lambda x: (-x['games'], x['hero']))

    # ② 分路 × 英雄：按规则中心的「分路 × 字段」逐项算均值、环比与定档
    # 只有赛训组保存过的规则才参与评级；未保存时用内置默认档位会让
    # 指标观察出现别的页面都不会给的「卓越/达标」。
    rules_doc = grade_rules.read_saved() or {'saved': False, 'subjects': {}}
    subjects = rules_doc.get('subjects') or {}

    def _avg_minutes(rows):
        """补刀按局时长匹配：用这一组局的平均时长挑标准档。"""
        values = []
        for row, _day in rows:
            raw = row.get('minutes')
            if raw is None and row.get('duration') not in (None, ''):
                try:
                    raw = float(row['duration']) / 60
                except (TypeError, ValueError):
                    raw = None
            try:
                minute = float(raw)
            except (TypeError, ValueError):
                continue
            if minute > 0:
                values.append(minute)
        return sum(values) / len(values) if values else None

    lane_heroes = {}
    for subject, rules in subjects.items():
        # 一个打野主体只收真正属于它的局：打野刀优先、英雄标签兜底，
        # 和选手页 / 对局页 / KPL 基线共用 grade_rules.subject_for，
        # 不再让「野核」「坦野」两页都拿同一批行套不同阈值。
        subject_rows = [(row, day) for row, day in own
                        if grade_rules.subject_for(row.get('position'),
                                                   hero=row.get('hero'), player=row) == subject]
        grouped = defaultdict(list)
        for row, day in subject_rows:
            grouped[row['hero']].append((row, day))
        out = []
        for hero, items in grouped.items():
            by_period = {}
            for n in _THD_PERIODS:
                cur, prev = spans(items, n)
                metrics = []
                for key, rule in rules.items():
                    if rule.get('active') is False:
                        continue        # 设置页没勾选生效的字段，分析里不出现
                    values = [grade_rules.field_value(row, rule) for row in cur]
                    values = [float(v) for v in values if v is not None]
                    old = [grade_rules.field_value(row, rule) for row in prev]
                    old = [float(v) for v in old if v is not None]
                    value = round(sum(values) / len(values), 2) if values else None
                    previous = round(sum(old) / len(old), 2) if old else None
                    grade = grade_rules.grade(subject, key, value, rules_doc,
                                              minutes=_avg_minutes(cur) if key == 'cs' else None)
                    metrics.append({'key': key, 'label': rule.get('label') or key,
                                    'unit': rule.get('unit') or '',
                                    'direction': rule.get('direction') or 'up',
                                    'value': value, 'previous': previous,
                                    'change': change(value, previous),
                                    'estimate': bool(rule.get('estimate')),
                                    'level': grade['level'] if grade else None,
                                    'grade': grade['label'] if grade else None,
                                    'samples': len(values)})
                by_period[str(n)] = {'games': len(cur), 'metrics': metrics}
            out.append({'hero': hero, 'games': by_period['7']['games'], 'byPeriod': by_period})
        out.sort(key=lambda x: (-x['games'], x['hero']))
        lane_heroes[subject] = out

    # ③ 组合池：只认赛训组保存过的名单（没保存过才用内置种子，并在响应里标注）
    saved = combo_pool.read_saved()
    combo_doc = saved or combo_pool.load()
    match_heroes = defaultdict(set)
    match_day, match_result = {}, {}
    for row, day in own:
        key = row.get('matchKey')
        if not key:
            continue
        match_heroes[key].add(row['hero'])
        if day:
            match_day[key] = day
        if row.get('result') in ('win', 'loss'):
            match_result[key] = row['result']
    combos = []
    for kind, label in (('pairs', '双人组合'), ('trios', '三人体系')):
        for row in combo_doc.get(kind) or []:
            combo_heroes = [combo_pool.normalize(h) for h in (row.get('heroes') or [])]
            matched = [(key, match_day.get(key, '')) for key, pool in match_heroes.items()
                       if all(hero in pool for hero in combo_heroes)]
            by_period = {}
            for n in _THD_PERIODS:
                lo, hi, plo, phi = bounds(n)
                cur_keys = [key for key, day in matched if in_span(day, lo, hi)]
                prev_keys = [key for key, day in matched if in_span(day, plo, phi)]
                a = stat([{'result': match_result.get(key)} for key in cur_keys])
                b = stat([{'result': match_result.get(key)} for key in prev_keys])
                by_period[str(n)] = {'current': a, 'previous': b,
                                     'change': change(a['winRate'], b['winRate'])}
            combos.append({'id': row.get('id') or '', 'kind': kind, 'kindLabel': label,
                           'heroes': combo_heroes, 'name': row.get('name') or '',
                           'strength': row.get('strength') or '', 'note': row.get('note') or '',
                           'byPeriod': by_period})
    combos.sort(key=lambda x: (-(x['byPeriod']['7']['current']['games']),
                               -x['byPeriod']['30']['current']['games'], x['heroes']))

    return {'generatedAt': _datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'anchor': anchor,
            'window': {str(n): bounds(n)[0] for n in _THD_PERIODS},
            'sources': {'panels': len(own), 'players': len({row.get('label') for row, _ in own}),
                        'heroes': len(heroes), 'games': len(match_heroes)},
            'comboBuiltin': saved is None,
            'rulesRevision': rules_doc.get('revision'),
            'heroRows': heroes, 'laneHeroes': lane_heroes, 'combos': combos}


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

# ── 选手主页档案：百段 / 巅峰赛分 / 千强 / 实力 ─────────────────────
# 营地对局面板里没有这几项，只存在选手主页上；能采到就预填，采不到就手填。

@router.get('/api/v3/player-profiles')
def player_profiles():
    """整份档案（按游戏名索引）+ 自动采集是否可用。"""
    data = player_profile.all_profiles()
    return {
        'schema': player_profile.SCHEMA,
        'profiles': data['profiles'],
        'count': data['count'],
        'lanes': list(player_profile.POSITIONS),
        'strengths': list(player_profile.STRENGTHS),
        'crawl': {
            'canAuto': bool(player_profile.read_session()),
            'hint': '主页数据要营地网页的登录态：点「扫码登录」开一个窗口扫码即可；不想登就直接手填。',
        },
    }


@router.post('/api/v3/player-profiles')
async def save_player_profile(request: Request):
    """手工档案：分路 1–5 条（主/副）、段数、巅峰分、千强、实力、英雄战力。"""
    body = await read_json(request)
    try:
        saved = player_profile.save(body if isinstance(body, dict) else {})
    except player_profile.ProfileError as error:
        raise HTTPException(400, str(error))
    return {'ok': True, 'profile': saved}


@router.post('/api/v3/player-profiles/clear')
async def clear_player_profile(request: Request):
    body = await read_json(request)
    name = str((body or {}).get('name') or '').strip() if isinstance(body, dict) else ''
    if not name:
        raise HTTPException(400, '缺少游戏名。')
    return {'ok': True, 'cleared': player_profile.clear_profile(name)}


@router.post('/api/v3/player-profiles/web-login')
async def start_player_profile_web_login():
    """打开本机浏览器窗口，用手机扫码登录营地网页；扫完自动把 Cookie 存下来。"""
    return player_profile.start_web_login()


@router.get('/api/v3/player-profiles/web-login')
def player_profile_web_login_status():
    return player_profile.web_login_status()


@router.post('/api/v3/player-profiles/web-login/cancel')
async def cancel_player_profile_web_login():
    return player_profile.cancel_web_login()


@router.post('/api/v3/player-profiles/session')
async def save_player_profile_session(request: Request):
    """存一次营地 Cookie（只在本机 data/ 下，不进仓库）。"""
    body = await read_json(request)
    cookie = str((body or {}).get('cookie') or '').strip() if isinstance(body, dict) else ''
    player_profile.write_session(cookie)
    return {'ok': True, 'canAuto': bool(cookie)}


@router.post('/api/v3/player-profiles/crawl')
async def crawl_player_profile(request: Request):
    """试一次自动采集；失败时把原因和候选字段一起带回来，前端据此提示或预填。"""
    body = await read_json(request)
    if not isinstance(body, dict):
        raise HTTPException(400, '采集参数无效。')
    name = str(body.get('name') or '').strip()
    role_id = str(body.get('roleId') or '').strip()
    if not name:
        raise HTTPException(400, '缺少游戏名。')
    result = player_profile.crawl(name, role_id)
    # 原始返回可能很大，截断后再回给前端展示
    raw = result.get('raw')
    if isinstance(raw, dict):
        text = json.dumps(raw, ensure_ascii=False)
        if len(text) > 20000:
            result['raw'] = text[:20000]
    return result


# ── 阵容标签自定义 + 口述文稿批量导入（模块八）────────────────────────────
# 独立配置：数据落 data/facts/lineup_tags.json，赛事级版本走 rule-snapshots，
# 不改组合池 / 评级规则的口径与缓存。路由集中追加在文件末尾，避免与并行改动冲突。
_LINEUP_TAGS_LOCK = Lock()


@router.get('/api/v3/lineup-tags')
def lineup_tags_get():
    """赛训组自定义阵容标签（标签名 + 5 个英雄），设置页读写这里。"""
    import lineup_tags
    return lineup_tags.load()


@router.post('/api/v3/lineup-tags')
def lineup_tags_set(payload: dict = Body(...)):
    """整体覆盖保存阵容标签；revision 不匹配返回 409，让界面提示刷新。"""
    import lineup_tags
    try:
        revision = int(payload.get('revision'))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail='revision 必须是整数')
    with _LINEUP_TAGS_LOCK:
        current = lineup_tags.load()
        if revision != current.get('revision'):
            raise HTTPException(status_code=409,
                                detail='阵容标签已被其他人更新，请刷新后再改。')
        incoming = {'schema': lineup_tags.SCHEMA, 'revision': current.get('revision'),
                    'tags': payload.get('tags')}
        try:
            saved = lineup_tags.save(incoming)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))
    return {'ok': True, 'revision': saved['revision'], 'updatedAt': saved['updatedAt']}


@router.get('/api/v3/lineup-tags/meta')
def lineup_tags_meta():
    """设置页兜底数据：英雄名录 + 分路（hero_tags.json）+ 内置标签（恢复按钮用）。"""
    import lineup_tags
    return {'heroes': lineup_tags.hero_names(), 'aliases': lineup_tags.ALIASES,
            'lanes': lineup_tags.hero_lanes(), 'defaults': lineup_tags.DEFAULT_TAGS}


# KPL 分路平均：官方 BP + 选手终局字段；没有真实样本的指标不输出。
_KPL_LANE_CACHE = {'stamp': 0.0, 'by_league': {}, 'leagues': []}


def _kpl_lane_baseline(league=''):
    """按 KPL 对局算各分路平均；可按赛事过滤，并返回每个指标的有效样本数。"""
    import kpl_bp

    bp_path = ROOT / 'data' / 'kpl' / 'bp_games.jsonl'
    ext_path = ROOT / 'data' / 'facts' / 'hero_external_stats.json'
    tag_path = ROOT / 'resources' / 'hero_tags.json'
    stamp = max((p.stat().st_mtime_ns for p in (bp_path, ext_path, tag_path) if p.exists()), default=0)
    league = str(league or '').strip()
    key = league or '__all__'
    cached = _KPL_LANE_CACHE
    if cached['stamp'] == stamp and key in cached['by_league']:
        return cached['by_league'][key]
    if cached['stamp'] != stamp:
        cached['stamp'] = stamp
        cached['by_league'] = {}
        cached['leagues'] = []

    external = {}
    if ext_path.exists():
        try:
            doc = json.loads(ext_path.read_text(encoding='utf-8'))
            external = doc.get('kpl') or {}
        except (OSError, ValueError):
            external = {}
    hero_tags = {}
    if tag_path.exists():
        try:
            hero_tags = (json.loads(tag_path.read_text(encoding='utf-8')).get('heroes') or {})
        except (OSError, ValueError):
            hero_tags = {}

    value = kpl_bp.build_lane_baseline(kpl_bp.load_games(bp_path), external, hero_tags, league)
    cached['leagues'] = value['leagues']
    cached['by_league'][key] = value
    return value


@router.get('/api/v3/kpl/lane-baseline')
def kpl_lane_baseline(league: str = ''):
    """KPL 分路平均指标；league 传 leagueName 可只看某一项赛事。"""
    return _kpl_lane_baseline(league)


# ── 赛训组自家克制库（模块九前半）：KPL 初稿 + 教练删改，与营地数据分开 ──
# 独立配置：数据落 data/facts/counter_library.json，赛事级版本走 rule-snapshots；
# 命中克制用 source='own' 标识，和 campHit / kplHit 分来源显示（不做合成分）。
# 路由集中追加在文件末尾，避免与并行改动冲突。
_COUNTER_LIBRARY_LOCK = Lock()


@router.get('/api/v3/counter-library')
def counter_library_get():
    """自家克制库 + 数据源可靠性说明（营地/巅峰千分最不准，贴膜待确认）。"""
    import counter_library
    doc = counter_library.load()
    return {**doc, 'sources': counter_library.SOURCE_RELIABILITY}


@router.post('/api/v3/counter-library')
def counter_library_set(payload: dict = Body(...)):
    """整体覆盖保存自家克制库；revision 不匹配返回 409，让界面提示刷新。"""
    import counter_library
    try:
        revision = int(payload.get('revision'))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail='revision 必须是整数')
    with _COUNTER_LIBRARY_LOCK:
        current = counter_library.load()
        if revision != current.get('revision'):
            raise HTTPException(status_code=409,
                                detail='克制库已被其他人更新，请刷新后再改。')
        incoming = {'schema': counter_library.SCHEMA, 'revision': current.get('revision'),
                    'pairs': payload.get('pairs'),
                    'version': payload.get('version') or current.get('version') or '',
                    'source': payload.get('source') or current.get('source') or 'manual',
                    'sourceNote': payload.get('sourceNote') or current.get('sourceNote') or '',
                    'draftFrom': payload.get('draftFrom') or current.get('draftFrom')}
        try:
            saved = counter_library.save(incoming)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))
    return {'ok': True, 'revision': saved['revision'], 'updatedAt': saved['updatedAt']}


@router.post('/api/v3/counter-library/regenerate')
def counter_library_regenerate(payload: dict = Body(default={})):
    """版本变动后重做克制对：用 KPL 数据重生成初稿并保存（会覆盖人工删改，历史可回滚）。"""
    import counter_library
    opts = payload or {}
    try:
        min_n = int(opts['minN']) if opts.get('minN') is not None else None
        hit_wr = float(opts['hitWr']) if opts.get('hitWr') is not None else None
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail='minN / hitWr 必须是数字')
    with _COUNTER_LIBRARY_LOCK:
        saved = counter_library.regenerate(
            version=str(opts.get('version') or ''), min_n=min_n, hit_wr=hit_wr)
    return {'ok': True, 'revision': saved['revision'],
            'updatedAt': saved['updatedAt'], 'pairs': len(saved['pairs'])}


# === profiles module ===
# 三套档案（本队 / 对手 / 试训）的独立持久化。
# 不复用 workspace/players：players 表只有身份字段，装不下巅峰分、五路分路段数、
# 英雄战力、教练风格标签与试训时间窗；按本次写作用域也不改 workspace_store.py。
# 落盘 data/profiles.json，整份文档 + revision 乐观锁，避免两人同时改互相覆盖。

_PROFILES_PATH = DATA_DIR / 'profiles.json'
_PROFILES_LOCK = Lock()
_PROFILES_SCHEMA = 'profiles-v1'


def _profiles_default():
    return {'schema': _PROFILES_SCHEMA, 'revision': 1, 'updatedAt': '',
            'own': [], 'opponents': [], 'trials': []}


def _profiles_load():
    try:
        doc = json.loads(_PROFILES_PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return _profiles_default()
    if not isinstance(doc, dict):
        return _profiles_default()
    result = _profiles_default()
    for key in ('own', 'opponents', 'trials'):
        value = doc.get(key)
        if isinstance(value, list):
            result[key] = [item for item in value if isinstance(item, dict)]
    try:
        result['revision'] = int(doc.get('revision') or 1)
    except (TypeError, ValueError):
        result['revision'] = 1
    result['updatedAt'] = str(doc.get('updatedAt') or '')
    return result


def _profiles_write(doc):
    tmp = _PROFILES_PATH.with_name(_PROFILES_PATH.name + '.tmp')
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, _PROFILES_PATH)


@router.get('/api/v3/profiles')
def profiles_get():
    with _PROFILES_LOCK:
        return _profiles_load()


@router.put('/api/v3/profiles')
async def profiles_put(request: Request):
    """整份覆盖保存；revision 不匹配返回 409，前端据此提示刷新后重试。"""
    from datetime import datetime, timezone
    payload = await read_json(request)
    if not isinstance(payload, dict):
        raise HTTPException(400, '档案数据无效。')
    incoming = {key: payload.get(key) for key in ('own', 'opponents', 'trials')}
    for key, value in incoming.items():
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise HTTPException(400, f'{key} 必须是对象数组。')
    try:
        revision = int(payload.get('revision') or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, 'revision 必须是整数。')
    with _PROFILES_LOCK:
        current = _profiles_load()
        if revision != current['revision']:
            raise HTTPException(409, '档案已被其他人更新，请刷新后再保存。')
        doc = {'schema': _PROFILES_SCHEMA,
               'revision': current['revision'] + 1,
               'updatedAt': datetime.now(timezone.utc).isoformat(timespec='seconds'),
               **incoming}
        _profiles_write(doc)
    # 本队选手档案 → 选手池：档案页是权威录入口，保存时同步到 players 主数据，
    # 并挂在本队战队下。同步失败不阻塞档案保存，图谱会把未落库的人标出来。
    try:
        import identity_service
        connection = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
        try:
            row = connection.execute('SELECT body FROM settings WHERE id=1').fetchone()
        finally:
            connection.close()
        settings = json.loads(row[0]) if row else {}
        team_name = str(settings.get('teamName') or '').strip() or '我的战队'
        own_team = identity_service.sync_own_team(str(DB), name=team_name, actor='coach')
        for item in doc['own']:
            name = str(item.get('realName') or item.get('matchId') or '').strip()
            if not name:
                continue
            identity_service.save_player(
                str(DB), player_id=str(item.get('id') or ''), name=name,
                position=item.get('mainLane') or None, team_id=own_team['id'],
                team_name=team_name, camp_user_id=item.get('matchId') or None, actor='coach')
    except Exception:
        pass
    return {'ok': True, **doc}


# === rules center ===（2026-11-22）赛训规则中心持久化层
# 六类规则共用一套「读 / 写（revision 乐观锁）」骨架；赛事级版本统一走
# /api/v3/rule-snapshots。刻意不碰 combo_pool.py / grade_rules.py / counter_library.py
# 的数据文件与算法：组合、克制、阵容标签在新文件里独立维护，英雄标签则回写
# resources/hero_tags.json（保留原 schema）。
import tempfile
from datetime import datetime, timezone

_RC_LOCK = Lock()
_RC_SPECS = {
    'combos': {'file': 'rules_combos.json', 'schema': 'rules-center-combos-v1', 'list': 'combos'},
    'hero_tags': {'file': None, 'schema': None, 'list': 'heroes'},  # 直接回写 resources/hero_tags.json
    'counters': {'file': 'rules_counters.json', 'schema': 'rules-center-counters-v1', 'list': None},
    'lineup_tags': {'file': 'rules_lineup_tags.json', 'schema': 'rules-center-lineup-tags-v1', 'list': 'tags'},
    'misc': {'file': 'rules_misc.json', 'schema': 'rules-center-misc-v1', 'list': 'entries'},
}

def _rc_path(kind):
    if kind == 'hero_tags':
        return ROOT / 'resources' / 'hero_tags.json'
    return bp_facts.FACTS / _RC_SPECS[kind]['file']


def _rc_default(kind):
    doc = {'schema': _RC_SPECS[kind]['schema'], 'revision': 0, 'updatedAt': '', 'saved': False}
    if kind == 'combos':
        doc['combos'] = []
    elif kind == 'counters':
        doc['heroPairs'], doc['comboPairs'] = [], []
    elif kind == 'lineup_tags':
        doc['tags'] = []
    elif kind == 'misc':
        doc['entries'] = []
    return doc


def _rc_read(kind):
    file = _rc_path(kind)
    if not file.is_file():
        return None if kind == 'hero_tags' else _rc_default(kind)
    try:
        doc = json.loads(file.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None if kind == 'hero_tags' else _rc_default(kind)
    return doc if isinstance(doc, dict) else None


def _rc_check(kind, doc):
    if not isinstance(doc, dict):
        raise HTTPException(400, '规则文档必须是 JSON 对象')
    if kind == 'hero_tags':
        # 保留原 schema：只校验 heroes 容器，其他字段（capabilityDims / source 等）原样回写。
        if not isinstance(doc.get('heroes'), dict):
            raise HTTPException(400, '英雄标签缺少 heroes 对象，拒绝写回')
        return
    if doc.get('schema') != _RC_SPECS[kind]['schema']:
        raise HTTPException(400, '规则文档 schema 不匹配')
    lists = ('heroPairs', 'comboPairs') if kind == 'counters' else (_RC_SPECS[kind]['list'],)
    for key in lists:
        rows = doc.get(key)
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise HTTPException(400, f'{key} 必须是对象数组')
    if kind == 'counters':
        for row in list(doc.get('heroPairs') or []) + list(doc.get('comboPairs') or []):
            # 兼容旧的单行单英雄，也接受新的「一行一组」aHeroes/bHeroes 集合。
            a_side = row.get('aHeroes')
            b_side = row.get('bHeroes')
            if isinstance(a_side, list) and isinstance(b_side, list):
                if not [str(x) for x in a_side if str(x).strip()] or not [str(x) for x in b_side if str(x).strip()]:
                    raise HTTPException(400, '克制关系每条都要有攻方与受方英雄')
                if set(map(str, a_side)) & set(map(str, b_side)):
                    raise HTTPException(400, '克制关系的攻方与受方不能包含同一个英雄')
            elif not str(row.get('a') or '').strip() or not str(row.get('b') or '').strip():
                raise HTTPException(400, '克制关系每条都要有攻方(a)与受方(b)')
    if kind == 'combos':
        for row in doc.get('combos') or []:
            heroes = row.get('heroes')
            if not isinstance(heroes, list) or len(heroes) > 5:
                raise HTTPException(400, '组合最多 5 个英雄')
    # TODO: 更严格校验（分路枚举 / 强度 / 赛事时间窗先后关系 / 组合人数与英雄数一致）。


def _rc_write(kind, doc):
    """原子写：目标文件与临时文件同目录，避免半截 JSON 破坏既有数据。"""
    file = _rc_path(kind)
    file.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f'rules-{kind}-', suffix='.json', dir=str(file.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(doc, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, file)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# === 赛事快照中心：整份规则按赛事打包，与可自由编辑的「当下内容」分离 ===
# 每个模块（英雄标签 / 克制关系 / 其他规则 / 阵容标签 / 组合池 / 规则设置）
# 都能把整份 doc 存成「当前赛事」的快照；赛训组随时覆盖，也能从快照回滚当下。
_SNAPSHOT_SCHEMA = 'rule-snapshots-v1'
_SNAPSHOT_MODULES = frozenset(('hero_tags', 'counters', 'misc',
                              'lineup_tags', 'combos', 'grade_rules'))
_SNAPSHOT_LOCK = Lock()


def _snapshot_path():
    return bp_facts.FACTS / 'rule_snapshots.json'


def _snapshots_load():
    path = _snapshot_path()
    empty = {'schema': _SNAPSHOT_SCHEMA, 'revision': 0, 'competitions': {}}
    if not path.is_file():
        return empty
    try:
        doc = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return empty
    if not isinstance(doc, dict) or not isinstance(doc.get('competitions'), dict):
        return empty
    doc.setdefault('schema', _SNAPSHOT_SCHEMA)
    doc.setdefault('revision', 0)
    return doc


def _snapshots_write(doc):
    path = _snapshot_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='rule-snapshots-', suffix='.json', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(doc, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


@router.get('/api/v3/rule-snapshots')
def rule_snapshots_get():
    with _SNAPSHOT_LOCK:
        return _snapshots_load()


@router.post('/api/v3/rule-snapshots')
def rule_snapshots_save(payload: dict = Body(...)):
    comp_id = str(payload.get('competitionId') or '').strip()
    module = str(payload.get('module') or '').strip()
    if not comp_id or module not in _SNAPSHOT_MODULES:
        raise HTTPException(400, '赛事或规则模块无效，无法保存快照')
    doc = payload.get('doc')
    if not isinstance(doc, dict):
        raise HTTPException(400, '快照内容必须是对象')
    with _SNAPSHOT_LOCK:
        current = _snapshots_load()
        comps = current.setdefault('competitions', {})
        slot = comps.setdefault(comp_id, {})
        prev = slot.get(module) or {}
        entry = {
            'doc': doc,
            'savedAt': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'summary': str(payload.get('summary') or '')[:200],
            'revision': int(prev.get('revision') or 0) + 1,
        }
        slot[module] = entry
        current['revision'] = int(current.get('revision') or 0) + 1
        _snapshots_write(current)
    return {'ok': True, 'competitionId': comp_id, 'module': module, **entry}


@router.delete('/api/v3/rule-snapshots')
def rule_snapshots_delete(payload: dict = Body(...)):
    comp_id = str(payload.get('competitionId') or '').strip()
    module = str(payload.get('module') or '').strip()
    if not comp_id or module not in _SNAPSHOT_MODULES:
        raise HTTPException(400, '赛事或规则模块无效，无法删除快照')
    with _SNAPSHOT_LOCK:
        current = _snapshots_load()
        comps = current.get('competitions') or {}
        slot = comps.get(comp_id) or {}
        if module not in slot:
            raise HTTPException(404, '这个赛事还没有该模块的快照')
        slot.pop(module, None)
        if not slot:
            comps.pop(comp_id, None)
        current['revision'] = int(current.get('revision') or 0) + 1
        _snapshots_write(current)
    return {'ok': True, 'competitionId': comp_id, 'module': module}


@router.get('/api/v3/unlocks')
def unlocks_get(competition: str = ''):
    """数据解锁（v2）：各分析路由按赛事语料阈值返回解锁状态（锁卡/进度）。"""
    from unlocks import compute
    competition_id = (competition or '').strip()
    try:
        from workspace_store import Workspace
        ws = Workspace(DB)
        return compute(ws, DB, competition_id)
    except Exception:  # noqa: BLE001 - 解析失败按全锁处理，页面退回锁卡
        return {'competition': competition_id, 'routes': {
            'biggame': {'label': '大场分析', 'unlocked': False, 'n': 0, 'need': 1,
                        'unit': '个已确认系列', 'hint': '先在赛事页选择或创建赛事',
                        'cta': [['#competitions', '去选赛事']]},
            'cross': {'label': '跨场分析', 'unlocked': False, 'n': 0, 'need': 1,
                      'unit': '个已确认系列', 'hint': '先在赛事页选择或创建赛事',
                      'cta': [['#competitions', '去选赛事']]}}}


@router.get('/api/v3/tiers')
def tiers_get():
    """使用者等级（联赛）映射表：加新等级只改 tiers.py，不改代码。"""
    import tiers
    return {'leagues': tiers.LEAGUES, 'defaultLeague': tiers.DEFAULT_LEAGUE,
            'capabilities': tiers.CAPABILITIES, 'thresholds': tiers.THRESHOLDS}


# 克制关系不再从 KPL 重新读取 / 生成初稿：随包内置一份种子，赛训组在规则中心
# 直接增删改。生成脚本只作为离线留档（scripts/seed_counter_relations.py）。


@router.get('/api/v3/rules-center/{kind}')
def rules_center_get(kind: str):
    """读取一类规则的当前工作稿；赛事级版本由 /api/v3/rule-snapshots 管理。"""
    if kind not in _RC_SPECS:
        raise HTTPException(404, '未知的规则类型')
    doc = _rc_read(kind)
    if doc is None:
        raise HTTPException(404, '规则文件不存在或无法解析')
    return {**doc, 'saved': _rc_path(kind).is_file()}


@router.post('/api/v3/rules-center/{kind}')
def rules_center_set(kind: str, payload: dict = Body(...)):
    """整体覆盖保存；revision 不匹配返回 409。"""
    if kind not in _RC_SPECS:
        raise HTTPException(404, '未知的规则类型')
    try:
        revision = int(payload.get('revision'))
    except (TypeError, ValueError):
        raise HTTPException(400, 'revision 必须是整数')
    incoming = payload.get('doc')
    if not isinstance(incoming, dict):
        raise HTTPException(400, 'doc 必须是 JSON 对象')
    incoming = {k: v for k, v in incoming.items() if k not in ('saved', 'historyName', 'updatedAt')}
    with _RC_LOCK:
        current = _rc_read(kind) or _rc_default(kind)
        current_rev = int(current.get('revision') or 0)
        if revision != current_rev:
            raise HTTPException(409, '规则已被其他人更新，请刷新后再改。')
        doc = dict(incoming)
        if kind != 'hero_tags':
            doc['schema'] = _RC_SPECS[kind]['schema']
        doc['revision'] = current_rev
        doc['updatedAt'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
        _rc_check(kind, doc)
        doc['revision'] = current_rev + 1
        _rc_write(kind, doc)
    return {'ok': True, 'revision': doc['revision'], 'updatedAt': doc['updatedAt']}


if __name__ == '__main__':
    # 只保留一套服务：把端口交给 server.py 起同一个 app（采集 + 分析 + 前端），
    # 不再自己起一个只有分析路由的旁支 app。
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8771, help='端口（默认 8771）')
    port = parser.parse_args().port
    env = dict(os.environ, TRAINING_PORT=str(port))
    raise SystemExit(subprocess.call([sys.executable, str(ROOT / 'server.py')],
                                     cwd=str(ROOT), env=env))

