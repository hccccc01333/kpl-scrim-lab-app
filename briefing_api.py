"""赛训周期简报 API（GET /api/briefing）。

只读路由：把统一事实表按周期窗口切片后交给 ``analysis_period.build_briefing``。
- 事实表按数据签名缓存（同一次请求只 load 一次，跨请求复用）。
- 参数非法（period 取值、custom 缺 from/to、日期格式、from>to）返回 400。
- 空库/取数失败返回 200 + available=false + reason，不 500。
- ``next`` 读工作区日程（training.sqlite3 的 schedules），读不到就给
  available=false + note，不影响简报主体。
"""
from __future__ import annotations

import json
import re
import threading
from datetime import date
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

import analysis_period
import match_facts

DEFAULT_SOURCE = 'db,bundle'
MATCH_ROUTE = re.compile(r'^#match/([^?#]+)(.*)$')


def _router_match_keys(matches_dir, signature):
    """营地对局 seq → 前端 `#match/<key>` 的 key。

    事实表用营地 seq 标识一局，前端单局页要的是 data/matches/<key>.json 的 key；
    两个 id 都写在 match 文档里（match.key / match.campBp.gameSeq），这里按数据签名缓存一次。
    """
    cache = {'key': None, 'map': {}}
    lock = threading.Lock()

    def get():
        key = signature()
        with lock:
            if cache['key'] == key:
                return cache['map']
            mapping = {}
            base = Path(matches_dir) if matches_dir else None
            if base and base.is_dir():
                for path in base.glob('*.json'):
                    try:
                        data = json.loads(path.read_text(encoding='utf-8'))
                    except Exception:  # noqa: BLE001 - 单个坏文件不影响其他映射
                        continue
                    match = data.get('match') if isinstance(data, dict) else None
                    if not isinstance(match, dict):
                        continue
                    game_key = str(match.get('key') or path.stem)
                    seq = (match.get('campBp') or {}).get('gameSeq')
                    if seq:
                        mapping[str(seq)] = game_key
            cache['key'], cache['map'] = key, mapping
            return mapping

    return get


def _scope_query(date_from, date_to, opponent, source, validation):
    parts = [f'from={date_from}', f'to={date_to}']
    if opponent:
        parts.append(f'opponent={opponent}')
    parts.append(f'source={source}')
    parts.append(f'validation={validation}')
    return '&'.join(parts)


def _cards(payload):
    """所有带「证据对局」的卡：重点发现 + 复盘区（含各筛选分组）。

    复盘区的 watchFields[].items 与 watch 是同一批对象（默认分组），按 id 去重，
    避免同一张卡被换两次 key。
    """
    cards, seen = [], set()
    buckets = [payload.get('findings') or [], payload.get('watch') or []]
    for field in payload.get('watchFields') or []:
        if isinstance(field, dict):
            buckets.append(field.get('items') or [])
    for bucket in buckets:
        for item in bucket:
            if not isinstance(item, dict) or id(item) in seen:
                continue
            seen.add(id(item))
            cards.append(item)
    return cards


def _apply_match_keys(payload, mapping, *, fallback_query):
    """把简报里的营地 seq 换成真实对局 key；换不到就不给死链。"""
    if not isinstance(payload, dict):
        return payload
    for finding in _cards(payload):
        for bucket in ('evidence', 'counterexamples'):
            for item in finding.get(bucket) or []:
                if not isinstance(item, dict):
                    continue
                seq = str(item.get('game') or '')
                game_key = mapping.get(seq)
                if game_key:
                    item['game'] = game_key
                else:
                    item['game'] = ''
        for field in ('primary_destination', 'deep_destination'):
            value = str(finding.get(field) or '')
            hit = MATCH_ROUTE.match(value)
            if not hit:
                continue
            seq, suffix = hit.group(1), hit.group(2)
            game_key = mapping.get(seq)
            if game_key:
                finding[field] = f'#match/{game_key}{suffix}'
            elif field == 'primary_destination':
                finding[field] = f'#matches?{fallback_query}'
            else:
                finding[field] = f'#matches?{fallback_query}'
    return payload



def _router_facts(replays_dir, camp_dir, data_dir, db_path):
    """事实表缓存：数据签名不变就直接复用，避免每次请求重扫盘。"""
    cache = {'key': None, 'facts': None}
    lock = threading.Lock()

    def get():
        key = match_facts.data_signature(replays_dir, camp_dir, db_path, data_dir)
        with lock:
            if cache['key'] != key or cache['facts'] is None:
                cache['facts'] = match_facts.load_facts(
                    replays_dir, camp_dir, data_dir, db_path)
                cache['key'] = key
            return cache['facts']

    return get


def _schedule_rows(db_path):
    """工作区日程；没有数据库或读失败返回 None（不代表 0 条）。"""
    if not db_path:
        return None
    path = Path(db_path)
    if not path.is_file():
        return None
    try:
        import workspace_store
        workspace = workspace_store.Workspace(path).ensure_schema()
        return workspace.list_schedules()
    except Exception:  # noqa: BLE001 - 训练安排不是简报主体
        return None


def _team_names(db_path):
    if not db_path:
        return {}
    path = Path(db_path)
    if not path.is_file():
        return {}
    try:
        import workspace_store
        workspace = workspace_store.Workspace(path).ensure_schema()
        names = {}
        for team in workspace.list_teams():
            team_id = str(team.get('id') or '')
            if team_id:
                names[team_id] = str(team.get('name') or team.get('display_name') or '')
        return names
    except Exception:  # noqa: BLE001
        return {}


def create_briefing_router(replays_dir, camp_dir, data_dir=None, db_path=None,
                           matches_dir=None):
    replays_dir = Path(replays_dir)
    camp_dir = Path(camp_dir)
    facts_of = _router_facts(replays_dir, camp_dir, data_dir, db_path)
    keys_of = _router_match_keys(
        matches_dir or (Path(data_dir) / 'matches' if data_dir else None),
        lambda: match_facts.data_signature(replays_dir, camp_dir, db_path, data_dir))
    router = APIRouter(prefix='/api/briefing', tags=['briefing'])

    @router.get('')
    def briefing(request: Request):
        query = request.query_params
        period = (query.get('period') or 'week').strip() or 'week'
        date_from = (query.get('from') or '').strip() or None
        date_to = (query.get('to') or '').strip() or None
        opponent = (query.get('opponent') or '').strip() or None
        source = (query.get('source') or DEFAULT_SOURCE).strip() or DEFAULT_SOURCE
        validation = (query.get('validation') or '0').strip() or '0'
        today = date.today()

        # 参数非法一律 400（custom 缺 from/to、格式错、from>to、period 取值）
        try:
            analysis_period.parse_period(
                period, today=today, date_from=date_from, date_to=date_to)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

        try:
            facts = facts_of()
        except Exception as error:  # noqa: BLE001 - 取数失败返回空态而不是 500
            payload = analysis_period.build_briefing(
                {}, period_kind=period, date_from=date_from, date_to=date_to,
                opponent=opponent, source=source, validation=validation, today=today)
            payload['reason'] = f'读取事实表失败：{error}'
            payload['summary']['note'] = '取数失败，请稍后重试。'
            return payload

        rows = _schedule_rows(db_path)
        names = _team_names(db_path) if rows is not None else {}
        payload = analysis_period.build_briefing(
            facts, period_kind=period, date_from=date_from, date_to=date_to,
            opponent=opponent, source=source, validation=validation, today=today,
            schedule_rows=rows, team_names=names)
        return _apply_match_keys(
            payload, keys_of(),
            fallback_query=_scope_query(date_from or '', date_to or '', opponent or '', source, validation))

    return router
