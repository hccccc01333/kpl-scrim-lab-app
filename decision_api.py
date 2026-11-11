"""赛训决策台 API（/api/decision/*）。

只读路由：把 decision_facts 的统一事实表接到五类决策分析上，并为教练首页提供
「今天先看这几个问题」的 briefing。

- 结果按数据签名缓存，谱系变化（新对局/新回放/改名）自动失效。
- 无数据返回 200 + available=false + reason，不 500。
- 参数非法返回 400（日期格式、from>to、result/side 取值）。
"""
from __future__ import annotations

import threading
from datetime import date
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

import decision_facts

ANALYSES = (
    {
        'id': 'loss_chain', 'name': '失利关键链', 'priority': 'P0', 'level': 'B',
        'layer': 'replay', 'gamesKey': 'games',
        'thresholds': {'windowSec': [30, 60, 120], 'minDelta': 1000, 'evidenceWindowSec': 60},
        'note': '经济显著下滑窗口 + 同期候选事件；只列候选，不宣称因果。',
        'link': '/decision?tab=review',
    },
    {
        'id': 'advantage_retention', 'name': '优势保持与回撤', 'priority': 'P0', 'level': 'B',
        'layer': 'replay', 'gamesKey': 'games',
        'thresholds': {'leadThreshold': 500, 'significantLead': 1000, 'landmarkSec': 600,
                       'callbackSec': 120},
        'note': '最大优势回撤 / 领先时长 / 兑现时间 / 被翻盘占比；经济点约 30 秒一个。',
        'link': '/decision?tab=review',
    },
    {
        'id': 'fight_execution', 'name': '团战执行与人员协同', 'priority': 'P0', 'level': 'B',
        'layer': 'replay', 'gamesKey': 'fightGames',
        'thresholds': {'earlyWindowSec': 3, 'lateJoinSec': 5, 'enoughBucket': 8},
        'note': '到位延迟、开局人数差、击杀交换；人数差为 0 击杀时只看到位。',
        'link': '/decision?tab=review',
    },
    {
        'id': 'resource_allocation', 'name': '资源分配与发育效率', 'priority': 'P0', 'level': 'A',
        'layer': 'panel', 'gamesKey': 'panelGames',
        'thresholds': {'quadrantFlagGapPP': 5, 'quadrantFlagMinShare': 20, 'smallSample': 10},
        'note': '终局面板即可运行；象限只用于发现值得复核的资源配置，不评价选手。',
        'link': '/decision?tab=player',
    },
    {
        'id': 'opening_routes', 'name': '对手开局路线与热区', 'priority': 'P0', 'level': 'B',
        'layer': 'replay', 'gamesKey': 'positionGames',
        'thresholds': {'untilSec': 240, 'stepSec': 5, 'clusterThreshold': 0.18,
                       'minGamesForHabit': 3},
        'note': '只描述本批收录回放；每名对手样本不足时只做单局观察。',
        'link': '/decision?tab=prep',
    },
    {
        'id': 'bp_counter', 'name': 'BP 阵容抗针对', 'priority': 'P1', 'level': 'A',
        'layer': 'panel', 'gamesKey': 'panelGames',
        'thresholds': {'thinPoolDepth': 2, 'topBans': 8},
        'note': '对手常禁什么、我方被禁后还剩哪些可用英雄；少量比赛不推断英雄强度。',
        'link': '/bp',
    },
)


def _router_facts(replays_dir, camp_dir, data_dir, db_path):
    cache = {'key': None, 'facts': None}
    lock = threading.Lock()

    def get():
        key = decision_facts.data_signature(replays_dir, camp_dir, db_path)
        with lock:
            if cache['key'] != key or cache['facts'] is None:
                cache['facts'] = decision_facts.load_facts(
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
        'game': optional('game'),
        'opponent': optional('opponent'),
        'from': start,
        'to': end,
        'date_from': date_from.isoformat() if date_from else None,
        'date_to': date_to.isoformat() if date_to else None,
        'result': result,
        'side': side,
        'lane': optional('lane'),
        'player': optional('player'),
        'limit': query.get('limit'),
    }


def _limit(values, default=120):
    raw = values.get('limit')
    if raw in (None, ''):
        return default
    try:
        number = int(raw)
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=400, detail='limit 须为整数') from error
    return max(1, min(500, number))


def _catalog(facts):
    coverage = facts['coverage']
    analyses = []
    for meta in ANALYSES:
        games = coverage.get(meta['gamesKey']) or 0
        available = games > 0
        item = {
            'id': meta['id'], 'name': meta['name'], 'priority': meta['priority'],
            'level': meta['level'], 'layer': meta['layer'],
            'available': available, 'games': games,
            'thresholds': meta['thresholds'], 'note': meta['note'], 'link': meta['link'],
            'emptyReason': None if available else '当前数据范围内没有可用对局',
        }
        if meta['id'] == 'opening_routes':
            if coverage.get('opponents', {}).get('with3Games', 0) == 0:
                item['caveat'] = '每个对手目前只有 1 局回放，只能做单局路线观察，不能输出固定套路。'
        if meta['id'] == 'resource_allocation':
            item['fields'] = ['money', 'totalHeroHurtCnt', 'buildingDamage', 'ctrlTime', 'healCnt',
                              'monsterCoin', 'killSoldier']
        analyses.append(item)

    games = []
    for seq in facts['order']:
        game = facts['games'][seq]
        games.append({
            'id': seq, 'label': game['label'], 'date': game['date'],
            'opponent': game['opponentName'], 'opponentId': game['opponentId'],
            'ownCamp': game['ownCamp'], 'result': game['result'],
            'duration': game['duration'],
            'hasReplay': True, 'hasPositions': game['hasPositions'],
            'hasFights': game['hasFights'], 'hasEconomy': game['hasEconomy'],
            'fights': len(game['fights']), 'deaths': len(game['deaths']),
        })
    opponents = [{
        'id': item['id'], 'name': item['name'], 'games': len(item['seqs']),
        'replayGames': item['replayGames'], 'enough': item['replayGames'] >= 3,
    } for item in facts['opponents']]
    return {
        'generatedAt': facts['generatedAt'],
        'coverage': coverage,
        'layers': [
            {'id': 'A', 'name': '终局面板', 'source': 'data/camp_details',
             'games': coverage['panelGames'], 'rows': coverage['panelRows'],
             'supports': ['resource_allocation'],
             'fields': ['money', 'totalHeroHurtCnt', 'buildingDamage', 'ctrlTime',
                        'healCnt', 'monsterCoin', 'killSoldier', 'joinGamePercent'],
             'limits': '终局值，没有过程；营地昵称未绑定身份时按昵称显示。'},
            {'id': 'B', 'name': '官方回放过程', 'source': 'data/official_replays/camp-*',
             'games': coverage['games'],
             'supports': ['loss_chain', 'advantage_retention', 'fight_execution',
                          'opening_routes'],
             'fields': ['economy.diff', 'battles.fights', 'battles.deaths', 'events.key',
                        'positions.json'],
             'limits': '经济点约 30 秒一个；坐标按本批位置分位定标，不是官方地图尺寸。'},
            {'id': 'C', 'name': '需补录 / 进一步验证', 'source': 'training.sqlite3 / workspace',
             'supports': ['training_verification'],
             'limits': '训练效果只做前后描述；复盘结论→训练目标自动关联尚未打通。'},
        ],
        'analyses': analyses,
        'games': games,
        'opponents': opponents,
        'notes': list(facts.get('notes') or []),
    }


def create_decision_router(replays_dir, camp_dir, data_dir=None, db_path=None):
    replays_dir = Path(replays_dir)
    camp_dir = Path(camp_dir)
    facts_of = _router_facts(replays_dir, camp_dir, data_dir, db_path)
    router = APIRouter(prefix='/api/decision', tags=['decision'])

    @router.get('/catalog')
    def catalog():
        return _catalog(facts_of())

    @router.get('/briefing')
    def briefing(request: Request):
        values = _filters(request)
        import decision_briefing
        return decision_briefing.briefing(
            facts_of(), opponent=values['opponent'], date_from=values['date_from'],
            date_to=values['date_to'], result=values['result'], limit=_limit(values, 5))

    @router.get('/loss')
    def loss(request: Request):
        values = _filters(request)
        import decision_loss
        return decision_loss.loss_report(
            facts_of(), game=values['game'], opponent=values['opponent'],
            date_from=values['date_from'], date_to=values['date_to'],
            result=values['result'], limit=_limit(values, 80))

    @router.get('/advantage')
    def advantage(request: Request):
        values = _filters(request)
        import decision_loss
        return decision_loss.advantage_report(
            facts_of(), opponent=values['opponent'], date_from=values['date_from'],
            date_to=values['date_to'], result=values['result'])

    @router.get('/fights')
    def fights(request: Request):
        values = _filters(request)
        import decision_fights
        return decision_fights.fight_report(
            facts_of(), game=values['game'], opponent=values['opponent'],
            date_from=values['date_from'], date_to=values['date_to'],
            result=values['result'], side=values['side'], limit=_limit(values, 120))

    @router.get('/opening')
    def opening(request: Request):
        values = _filters(request)
        import decision_opening
        return decision_opening.opening_report(
            facts_of(), opponent=values['opponent'], lane=values['lane'],
            date_from=values['date_from'], date_to=values['date_to'],
            side=values['side'] or 'enemy')

    @router.get('/resource')
    def resource(request: Request):
        values = _filters(request)
        import decision_resource
        return decision_resource.resource_report(
            facts_of(), lane=values['lane'], player=values['player'],
            opponent=values['opponent'], date_from=values['date_from'],
            date_to=values['date_to'], result=values['result'],
            side=values['side'] or 'own')

    @router.get('/bp')
    def bp(request: Request):
        values = _filters(request)
        import decision_bp
        return decision_bp.bp_report(
            facts_of(), opponent=values['opponent'], date_from=values['date_from'],
            date_to=values['date_to'])

    return router
