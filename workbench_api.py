"""赛训分析 API（/api/decision/*）。

只读路由：把 facts 的统一事实表接到「BP 阵容抗针对」上。

- 结果按数据签名缓存，谱系变化（新对局/新回放/改名）自动失效。
- 无数据返回 200 + available=false + reason，不 500。
- 参数非法返回 400（日期格式、from>to、result/side 取值）。
"""
from __future__ import annotations

import threading
from datetime import date
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

import match_facts

def _router_facts(replays_dir, camp_dir, data_dir, db_path):
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


def _filters(request):
    query = request.query_params

    def optional(name):
        value = (query.get(name) or '').strip()
        return value or None

    start = optional('from')
    end = optional('to')
    try:
        date_from = date.fromisoformat(start) if start else None
        date_to = date.fromisoformat(end) if end else None
    except ValueError as error:
        raise HTTPException(status_code=400, detail='日期项须为 YYYY-MM-DD') from error
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=400, detail='开始日期不能晚于结束日期')
    result = optional('result')
    if result and result not in ('win', 'loss'):
        raise HTTPException(status_code=400, detail='result 只能取 win 或 loss')
    side = optional('side')
    if side and side not in ('own', 'enemy'):
        raise HTTPException(status_code=400, detail='side 只能取 own 或 enemy')
    return {
        'opponent': optional('opponent'),
        'from': start,
        'to': end,
        'date_from': date_from.isoformat() if date_from else None,
        'date_to': date_to.isoformat() if date_to else None,
        'result': result,
        'side': side,
        'lane': optional('lane'),
        'player': optional('player'),
    }


def create_workbench_router(replays_dir, camp_dir, data_dir=None, db_path=None):
    replays_dir = Path(replays_dir)
    camp_dir = Path(camp_dir)
    facts_of = _router_facts(replays_dir, camp_dir, data_dir, db_path)
    router = APIRouter(prefix='/api/decision', tags=['decision'])

    @router.get('/bp')
    def bp(request: Request):
        values = _filters(request)
        import bp_camp
        return bp_camp.bp_report(
            facts_of(), opponent=values['opponent'], date_from=values['date_from'],
            date_to=values['date_to'])

    return router
