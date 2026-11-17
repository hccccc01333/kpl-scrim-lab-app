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
- corpus(repo) -> 全量单局完整向量（大场挖掘的语料；缺失时降级）
- detail(repo, key) -> 单局完整详情或 None
"""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request

import series_engine
import series_insight
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


# 编组页整包缓存：键是数据文件指纹，数据一变自动换 key，不需要手工失效。
_BOOTSTRAP_CACHE = {}


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

    def _vector_index(repo, values=None, keys=None):
        """按需取向量：传入 keys 时只建这几局（列表 / 汇总 / 写操作都不再全量重建）。"""
        wanted = {str(k) for k in (keys or []) if k}
        if keys is not None and 'vectors_for' in lookup:
            vectors = lookup['vectors_for'](repo, values, sorted(wanted))
        else:
            vectors = lookup['vectors'](repo, values)
            if keys is not None:
                vectors = [v for v in vectors if str(v.get('key') or '') in wanted]
        return {str(v.get('key') or ''): v for v in vectors if v.get('key')}

    def _series_keys(briefs):
        return [str(game.get('matchKey'))
                for brief in briefs for game in (brief.get('games') or [])
                if game.get('matchKey')]

    def _light_vectors(request):
        """编组页轻量向量：优先走对局包指纹缓存，命中时完全不碰仓库快照。"""
        builder = lookup.get('builder_vectors')
        if builder is not None:
            try:
                return builder(repo=None)
            except TypeError:
                return builder(lookup['repo'](request))
        return lookup['vectors'](lookup['repo'](request))

    def _light_index(request):
        return {str(v.get('key') or ''): v for v in _light_vectors(request) if v.get('key')}

    def _team_aliases():
        try:
            import opponent_identity
            return opponent_identity.resolve_names(db_path)['aliases']
        except Exception:  # noqa: BLE001 - 解析失败不影响编组
            return {}

    def _list_series(ws, values):
        """对手筛选放在 enrich 之后做：系列赛的队名可能是按局内对手推出来的，
        数据库里没有这串文本，SQL LIKE 会把它们全部漏掉。"""
        return ws.list_series(
            date_from=values['from'], date_to=values['to'], session=values['session'],
            opponent=None,
            best_of=int(values['bestOf']) if values['bestOf'] else None,
            status=values['status'], completion=values['completion'])

    def _opponent_query(values):
        """筛选词连同它的旧名/新名一起认：改名后旧系列赛不会被筛掉。"""
        query = values['opponent']
        if not query:
            return None
        aliases = _team_aliases()
        current = aliases.get(query, query)
        allowed = {query, current}
        allowed.update(old for old, name in aliases.items() if name == current)
        return {item for item in allowed if item}

    def _opponent_match(brief, allowed):
        if allowed is None:
            return True
        name = str(brief.get('opponent') or '').strip()
        if not name:
            return False
        return any(token in name or name in token for token in allowed)

    def _enrich(ws, brief, index, *, derive_completion=True):
        """给存储层简介补上向量侧信息：逐局日期/时间/胜负/前期差、比分、
        完赛状态与覆盖。完赛状态只在教练没标注 interrupted/incomplete 时推导。"""
        aliases = _team_aliases()
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
        # 系列赛自己存的是建组时手填的自由文本；战队分析改名后要跟着折成新队名，
        # 没填过对手的系列赛直接按局内已解析的对手补齐。
        text = str(brief.get('opponent') or '').strip()
        if text:
            brief['opponent'] = aliases.get(text, text)
        else:
            names = [str(game.get('opponent') or '').strip() for game in games]
            names = [name for name in names if name]
            if names:
                brief['opponent'] = max(set(names), key=names.count)
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
        briefs = _list_series(ws, values)
        allowed = _opponent_query(values)
        repo = lookup['repo'](request)
        # 只建已入组对局的向量：系列赛可能只引用窗口边缘的局，但绝不该为此
        # 把全量几百局都重建一遍。
        index = _vector_index(repo, keys=_series_keys(briefs))
        out = [brief for brief in (_enrich(ws, item, index) for item in briefs)
               if _opponent_match(brief, allowed)]
        return {'series': out, 'total': len(out)}

    @router.get('/api/series/bootstrap')
    def series_bootstrap(request: Request):
        """编组页一次取全：轻量向量 + 系列赛 + 自动候选。

        以前页面要并发打 /api/cross/vectors 与 /api/series，两个请求各自重建
        全量向量；这里共用一份 0.1 秒级的轻量向量，一次返回整页数据。
        """
        values = _series_values(request)
        stamp_fn = lookup.get('data_stamp')
        stamp = stamp_fn() if callable(stamp_fn) else None
        cache_key = (str(db_path), stamp, values['from'], values['to'], values['session'],
                     values['opponent'], values['bestOf'], values['status'],
                     values['completion']) if stamp is not None else None
        if cache_key is not None:
            cached = _BOOTSTRAP_CACHE.get(cache_key)
            if cached is not None:
                return cached
        ws = _workspace()
        briefs = _list_series(ws, values)
        allowed = _opponent_query(values)
        light = _light_vectors(request)
        index = {str(v.get('key') or ''): v for v in light if v.get('key')}
        series = [brief for brief in (_enrich(ws, item, index) for item in briefs)
                  if _opponent_match(brief, allowed)]
        existing = ws.series_for_matches([v.get('key') for v in light if v.get('key')])
        suggested = series_engine.suggest_groups(light, existing)
        payload = {
            'vectors': light,
            'total': len(light),
            'series': series,
            'suggestions': suggested.get('suggestions') or [],
            'blocked': suggested.get('blocked') or [],
        }
        if cache_key is not None:
            if len(_BOOTSTRAP_CACHE) > 3:
                _BOOTSTRAP_CACHE.clear()
            _BOOTSTRAP_CACHE[cache_key] = payload
        return payload

    @router.get('/api/series/{series_id}')
    def get_series(series_id: str, request: Request):
        ws = _workspace()
        brief = ws.get_series(series_id)
        if not brief:
            raise HTTPException(404, f'系列赛不存在：{series_id}')
        repo = lookup['repo'](request)
        index = _vector_index(repo, keys=_series_keys([brief]))
        return {'series': _enrich(ws, brief, index)}

    @router.get('/api/series/{series_id}/analysis')
    def series_analysis(series_id: str, request: Request):
        ws = _workspace()
        brief = ws.get_series(series_id)
        if not brief:
            raise HTTPException(404, f'系列赛不存在：{series_id}')
        repo = lookup['repo'](request)
        index = _vector_index(repo, keys=_series_keys([brief]))
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
        # 大场挖掘层：全量单局向量作历史语料（按对局包指纹缓存，冷启动
        # 首次约 3–6 秒）。取不到语料就降级成只描述本场，不阻断分析。
        corpus = None
        collector = lookup.get('corpus')
        if collector is not None:
            try:
                corpus = collector(repo)
            except Exception:  # noqa: BLE001 - 语料异常不应让单场分析 500
                corpus = None
        briefs = ws.list_series(limit=500)
        insight = series_insight.build_insight(
            brief, games, analysis, corpus=corpus, series_briefs=briefs)
        return {'series': brief, **analysis, 'insight': insight}

    @router.get('/api/cross/series-summary')
    def series_summary(request: Request):
        values = _series_values(request)
        ws = _workspace()
        briefs = _list_series(ws, values)
        allowed = _opponent_query(values)
        repo = lookup['repo'](request)
        index = _vector_index(repo, keys=_series_keys(briefs))
        rows, light = [], []
        for brief in briefs:
            _enrich(ws, brief, index)
            if not _opponent_match(brief, allowed):
                continue
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
                           'usedFoeCount': (g.get('ledger') or {}).get('usedFoeCount'),
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
        values = {
            'from': _date_param(payload.get('from')),
            'to': _date_param(payload.get('to')),
        }
        vectors = _light_vectors(request)
        if values['from']:
            vectors = [v for v in vectors if (v.get('date') or '')[:10] >= values['from']]
        if values['to']:
            vectors = [v for v in vectors if (v.get('date') or '')[:10] <= values['to']]
        session = str(payload.get('session') or '').strip()
        opponent = str(payload.get('opponent') or '').strip()
        if session:
            vectors = [v for v in vectors if (v.get('session') or '') == session]
        if opponent:
            # 队名改过：候选里也认旧名，否则改名前的筛选条件会突然筛不出候选。
            aliases = _team_aliases()
            current = aliases.get(opponent, opponent)
            candidates = {opponent, current}
            candidates.update(old for old, name in aliases.items() if name == current)
            vectors = [v for v in vectors
                       if any(token in str(v.get('opponent') or '') for token in candidates)]
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
        # 完赛状态推导要按局序取结果；games 可能是纯 key 列表，先归一化
        normalized = [{'matchKey': g} if isinstance(g, str) else g for g in games]
        index = _light_index(request)
        # 系列赛起止：优先向量日期（channel 对局不在 match_records 里也能定位），
        # 存储层再用关系表日期兜底
        dates = sorted(str((index.get(g['matchKey']) or {}).get('date') or '')
                       for g in normalized)
        dates = [d for d in dates if d]
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
                start_at=dates[0] if dates else None,
                end_at=dates[-1] if dates else None,
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
        games = None
        if 'games' in payload or 'matchKeys' in payload:
            games = _games_from_payload(payload)
        target_games = games if games is not None else [
            {'matchKey': g['matchKey'], 'gameIndex': g['gameIndex']} for g in current['games']]
        index = _light_index(request)
        completion = payload.get('completion')
        if completion not in ('interrupted', 'incomplete'):
            # 教练没显式标注就重推导：改了局序/赛制/执行方式，完赛状态跟着变
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
