"""系列赛编组与分析 API（V2.0 阶段 01/03，见 docs/series_builder.md）。

边界约束：
- 全部写操作都停在「关系层」：只动 training_series / training_series_games
  两张新表，以及 match_records / matches 的 series_id、game_no 两个关系列；
  原始对局数据一律不改。DELETE 只删编组关系，保留对局。
- 分析结论可追溯：逐局带 matchKey，缺数据为 None 并写覆盖说明，不补 0。
- 编组建议（suggest）只产出候选，不落库；重复归属返回 409 并带出占用方。

lookup 注入数据侧依赖（隔离测试时传假实现）：
- repo(request) -> AnalysisRepository 快照
- vectors(repo, values) -> 全量轻量向量列表（同 /api/cross/vectors 的向量）
- detail(repo, key) -> 单局完整详情或 None
"""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request

import series_engine
import workspace_store


async def _json_body(request: Request):
    try:
        return await request.json()
    except Exception:
        raise HTTPException(400, '请求体不是有效 JSON。') from None


def _date_param(value):
    text = str(value or '').strip()
    if not text:
        return None
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', text):
        raise HTTPException(400, '日期格式无效，应为 YYYY-MM-DD。')
    return text


def create_series_router(db_path, lookup):
    router = APIRouter(tags=['series'])

    def _workspace():
        return workspace_store.Workspace(db_path).ensure_schema()

    def _series_values(request: Request):
        """系列赛自己的筛选参数（与全局筛选独立，系列赛按开赛日归档）。"""
        q = request.query_params
        return {
            'from': _date_param(q.get('from')),
            'to': _date_param(q.get('to')),
            'session': (q.get('session') or '').strip() or None,
            'opponent': (q.get('opponent') or '').strip() or None,
            'bestOf': (q.get('bestOf') or '').strip() or None,
            'status': (q.get('status') or '').strip() or None,
            'completion': (q.get('completion') or '').strip() or None,
        }

    def _vector_index(repo, values=None):
        vectors = lookup['vectors'](repo, values)
        return {str(v.get('key') or ''): v for v in vectors if v.get('key')}

    def _enrich(ws, brief, index, *, derive_completion=True):
        """给存储层简介补上向量侧信息：逐局日期/时间/胜负/前期差、比分、
        完赛状态与覆盖。完赛状态只在教练没标注 interrupted/incomplete 时推导。"""
        games = brief.get('games') or []
        results = []
        missing = []
        for game in games:
            vector = index.get(game['matchKey'])
            if vector is None:
                missing.append(game['matchKey'])
            game['date'] = (vector or {}).get('date')
            game['clock'] = (vector or {}).get('clock')
            game['result'] = (vector or {}).get('result') or None
            game['at10'] = (vector or {}).get('at10')
            game['duration'] = (vector or {}).get('duration')
            game['opponent'] = (vector or {}).get('opponent') or None
            game['session'] = (vector or {}).get('session') or None
            game['version'] = (vector or {}).get('version') or None
            results.append(game.get('result'))
        brief['ruleset'] = series_engine.ruleset_payload(brief.get('rulesetId'))
        brief['score'] = {
            'us': sum(1 for r in results if r == 'win'),
            'them': sum(1 for r in results if r == 'loss'),
        }
        if derive_completion and brief.get('completion') not in ('interrupted', 'incomplete'):
            brief['completion'] = series_engine.derive_completion(
                brief.get('bestOf') or 3, brief.get('completionMode') or 'standard', results)
        brief['coverage'] = {'games': len(games), 'missingGames': missing}
        return brief

    def _completion_from_payload(payload, index, games, current=None):
        """教练显式标注（interrupted/incomplete）优先；否则按向量结果推导。"""
        explicit = payload.get('completion')
        if explicit in ('interrupted', 'incomplete'):
            return explicit
        if explicit in ('completed', 'open'):
            return explicit
        keys = [game if isinstance(game, str) else game.get('matchKey') for game in games]
        results = [(index.get(key) or {}).get('result') for key in keys]
        return series_engine.derive_completion(
            payload.get('bestOf') or (current or {}).get('bestOf') or 3,
            payload.get('completionMode') or (current or {}).get('completionMode') or 'standard',
            results)

    def _games_from_payload(payload):
        games = payload.get('games')
        if games is None:
            games = payload.get('matchKeys') or []
        if not isinstance(games, list):
            raise HTTPException(400, 'games 必须是局次列表。')
        return games

    # ---------------------------------------------------------------- 查询
    @router.get('/api/series')
    def list_series(request: Request):
        values = _series_values(request)
        ws = _workspace()
        briefs = ws.list_series(
            date_from=values['from'], date_to=values['to'], session=values['session'],
            opponent=values['opponent'],
            best_of=int(values['bestOf']) if values['bestOf'] else None,
            status=values['status'], completion=values['completion'])
        repo = lookup['repo'](request)
        # 索引不按 from/to 过滤：单组系列的局可能落在窗口边缘，逐局信息要全
        index = _vector_index(repo)
        out = [_enrich(ws, brief, index) for brief in briefs]
        return {'series': out, 'total': len(out)}

    @router.get('/api/series/{series_id}')
    def get_series(series_id: str, request: Request):
        ws = _workspace()
        brief = ws.get_series(series_id)
        if not brief:
            raise HTTPException(404, f'系列赛不存在：{series_id}')
        repo = lookup['repo'](request)
        index = _vector_index(repo)
        return {'series': _enrich(ws, brief, index)}

    @router.get('/api/series/{series_id}/analysis')
    def series_analysis(series_id: str, request: Request):
        ws = _workspace()
        brief = ws.get_series(series_id)
        if not brief:
            raise HTTPException(404, f'系列赛不存在：{series_id}')
        repo = lookup['repo'](request)
        index = _vector_index(repo)
        _enrich(ws, brief, index)
        games = []
        for game in brief.get('games') or []:
            games.append({
                'matchKey': game['matchKey'],
                'gameIndex': game['gameIndex'],
                'vector': index.get(game['matchKey']),
                # 下钻才取完整详情（每系列 ≤7 局）：手序/禁用/过程覆盖都在这
                'detail': lookup['detail'](repo, game['matchKey']),
            })
        analysis = series_engine.analyze_series(brief, games)
        return {'series': brief, **analysis}

    @router.get('/api/cross/series-summary')
    def series_summary(request: Request):
        values = _series_values(request)
        ws = _workspace()
        briefs = ws.list_series(
            date_from=values['from'], date_to=values['to'], session=values['session'],
            opponent=values['opponent'],
            best_of=int(values['bestOf']) if values['bestOf'] else None,
            status=values['status'], completion=values['completion'])
        repo = lookup['repo'](request)
        index = _vector_index(repo)
        rows, light = [], []
        for brief in briefs:
            _enrich(ws, brief, index)
            # 汇总不取完整详情：账本退化为向量出场阵容口径（来源 roster），
            # 每组下钻时才补 detail 拿手序与禁用。
            games = [{'matchKey': g['matchKey'], 'gameIndex': g['gameIndex'],
                      'vector': index.get(g['matchKey']), 'detail': None}
                     for g in brief.get('games') or []]
            analysis = series_engine.analyze_series(brief, games)
            rows.append({'series': brief, 'games': analysis['games'],
                         'score': analysis['score'], 'afterLoss': analysis['afterLoss']})
            light.append({
                'id': brief['id'], 'bestOf': brief['bestOf'], 'status': brief['status'],
                'completion': brief['completion'], 'completionMode': brief['completionMode'],
                'rulesetId': brief['rulesetId'], 'ruleset': brief.get('ruleset'),
                'opponent': brief['opponent'], 'session': brief['session'],
                'version': brief['version'], 'startAt': brief['startAt'],
                'endAt': brief['endAt'], 'score': brief['score'], 'notes': brief['notes'],
                'games': [{'matchKey': g['matchKey'], 'gameIndex': g['gameIndex'],
                           'date': g.get('date'), 'clock': g.get('clock'),
                           'result': g.get('result'), 'at10': g.get('at10'),
                           'usedUsCount': (g.get('ledger') or {}).get('usedUsCount'),
                           'changeLevel': (g.get('adjustment') or {}).get('changeLevel')}
                          for g in analysis['games']],
                'coverage': brief.get('coverage'),
            })
        summary = series_engine.summarize_series(rows)
        summary['attention'] = series_engine.build_attention(rows, summary)
        return {
            'summary': summary,
            'series': light,
            'rulesets': [{'id': key, **payload} for key, payload in series_engine.RULESETS.items()],
        }

    # ---------------------------------------------------------------- 编组建议
    @router.post('/api/series/suggest')
    async def suggest(request: Request):
        payload = await _json_body(request)
        ws = _workspace()
        repo = lookup['repo'](request)
        values = {
            'from': _date_param(payload.get('from')),
            'to': _date_param(payload.get('to')),
        }
        vectors = lookup['vectors'](repo, values)
        session = str(payload.get('session') or '').strip()
        opponent = str(payload.get('opponent') or '').strip()
        if session:
            vectors = [v for v in vectors if (v.get('session') or '') == session]
        if opponent:
            vectors = [v for v in vectors if opponent in str(v.get('opponent') or '')]
        existing = ws.series_for_matches([v.get('key') for v in vectors if v.get('key')])
        result = series_engine.suggest_groups(vectors, existing)
        result['params'] = {'from': values['from'], 'to': values['to'],
                            'session': session or None, 'opponent': opponent or None}
        return result

    # ---------------------------------------------------------------- 写操作
    @router.post('/api/series')
    async def create_series(request: Request):
        payload = await _json_body(request)
        ws = _workspace()
        games = _games_from_payload(payload)
        best_of = payload.get('bestOf')
        if not best_of:
            raise HTTPException(400, '缺少 bestOf（3 / 5 / 7）。')
        repo = lookup['repo'](request)
        index = _vector_index(repo)
        # 完赛状态推导要按局序取结果；games 可能是纯 key 列表，先归一化
        normalized = [{'matchKey': g} if isinstance(g, str) else g for g in games]
        try:
            brief = ws.create_series(
                best_of=int(best_of),
                games=games,
                ruleset_id=payload.get('rulesetId'),
                opponent=payload.get('opponent'),
                opponent_team_id=payload.get('opponentTeamId'),
                session=payload.get('session'),
                schedule_id=payload.get('scheduleId'),
                version=payload.get('version'),
                completion_mode=payload.get('completionMode'),
                completion=_completion_from_payload(payload, index, normalized),
                status=payload.get('status'),
                notes=payload.get('notes'),
                series_id=payload.get('id'),
                actor=payload.get('actor') or 'coach')
        except workspace_store.SeriesConflict as error:
            raise HTTPException(409, detail={
                'message': str(error), 'occupied': error.occupied}) from None
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
        except TypeError as error:
            raise HTTPException(400, f'参数不完整：{error}') from None
        return {'series': _enrich(ws, brief, index)}

    @router.patch('/api/series/{series_id}')
    async def update_series(series_id: str, request: Request):
        payload = await _json_body(request)
        ws = _workspace()
        current = ws.get_series(series_id)
        if not current:
            raise HTTPException(404, f'系列赛不存在：{series_id}')
        repo = lookup['repo'](request)
        index = _vector_index(repo)
        games = None
        if 'games' in payload or 'matchKeys' in payload:
            games = _games_from_payload(payload)
        completion = payload.get('completion')
        if completion not in ('interrupted', 'incomplete'):
            # 教练没显式标注就重推导：改了局序/赛制/执行方式，完赛状态跟着变
            target_games = games if games is not None else [
                {'matchKey': g['matchKey'], 'gameIndex': g['gameIndex']} for g in current['games']]
            completion = _completion_from_payload(payload, index, target_games, current)
        try:
            brief = ws.update_series(
                series_id,
                best_of=payload.get('bestOf'),
                games=games,
                ruleset_id=payload.get('rulesetId'),
                opponent=payload.get('opponent'),
                opponent_team_id=payload.get('opponentTeamId'),
                session=payload.get('session'),
                schedule_id=payload.get('scheduleId'),
                version=payload.get('version'),
                completion_mode=payload.get('completionMode'),
                completion=completion,
                status=payload.get('status'),
                notes=payload.get('notes'),
                actor=payload.get('actor') or 'coach')
        except workspace_store.SeriesConflict as error:
            raise HTTPException(409, detail={
                'message': str(error), 'occupied': error.occupied}) from None
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
        return {'series': _enrich(ws, brief, index)}

    @router.delete('/api/series/{series_id}')
    def delete_series(series_id: str, request: Request):
        ws = _workspace()
        try:
            freed = ws.delete_series(series_id, actor='coach')
        except ValueError as error:
            raise HTTPException(404, str(error)) from None
        return {'ok': True, 'matchKeys': freed, 'message': '编组关系已删除，原始对局保留。'}

    return router
