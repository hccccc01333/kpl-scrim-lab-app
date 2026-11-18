"""BP 规则兼容层：新实现见 :mod:`bp_formats`。

旧调用方（``bp_series`` / ``bp_lab`` / ``bp_intelligence`` / ``v3.serve``）仍可用
``scrim_rule`` / ``validate_scrim_prefix`` / ``next_scrim_action`` /
``legal_scrim_candidates`` / ``build_series_used`` / ``scrim_state_payload``。

默认规则改为：
* 征召 / 训练赛：``draft-18``（4 Ban/方 + 5 Pick/方）
* KPL：``draft-20``（5 Ban/方 + 5 Pick/方）
* 排位/巅峰：``rank-20``（5+5 同时 Ban + 10 Pick）

旧 id ``scrim-global-20`` 只作为兼容别名映射到 ``draft-18``；不再代表 20 手。
"""
from __future__ import annotations

from bp_formats import (
    BLIND, DRAFT_18, DRAFT_20, FORMATS, RANK_20, DraftFormat,
    can_assign_to_players, check_draft, decider_applies, get_format,
    legal_candidates, next_action, pick_key, resolve_format, series_used,
)

__all__ = [
    'SERIES_LENGTHS', 'SCRIM_RULE', 'SCRIM_RULES', 'SCRIM_GLOBAL_20',
    'KPL_RECORDED', 'SCRIM_20_SCHEDULE', 'scrim_rule', 'profile_for',
    'validate_series_context', 'validate_scrim_prefix', 'next_scrim_action',
    'build_series_used', 'legal_scrim_candidates', 'append_legal_scrim_action',
    'scrim_state_payload', 'can_assign_to_players',
]

SERIES_LENGTHS = {"BO3": 3, "BO5": 5, "BO7": 7}

# 兼容旧名字：训练赛默认征召 18 手；KPL 用 20 手。
SCRIM_GLOBAL_20 = DRAFT_18
SCRIM_RULE = DRAFT_18
KPL_RECORDED = DRAFT_20
SCRIM_RULES = {DRAFT_18.id: DRAFT_18, DRAFT_20.id: DRAFT_20,
               RANK_20.id: RANK_20, BLIND.id: BLIND}
SCRIM_20_SCHEDULE = tuple(
    (step['action'], step['camp']) for step in DRAFT_18.schedule)


def scrim_rule(rule=None):
    """取规则；``None``/旧 id → 征召 18 手。"""
    if rule in (None, '', 'scrim-global-20'):
        return DRAFT_18
    if isinstance(rule, DraftFormat):
        return rule
    return get_format(str(rule))


def profile_for(source, profile=None):
    if source == 'scrim':
        if profile in (None, '', DRAFT_18.id, 'scrim-global-20'):
            return DRAFT_18
        raise ValueError('未知训练赛规则；训练赛/征召只有 draft-18')
    if source == 'kpl':
        if profile in (None, '', DRAFT_20.id, 'kpl-recorded'):
            return DRAFT_20
        raise ValueError('KPL 规则只有 draft-20（历史 18 手按记录格式显示）')
    raise ValueError('未知 BP 数据来源')


def validate_series_context(bo='BO5', game_number=1):
    if bo not in SERIES_LENGTHS:
        raise ValueError('赛制必须是 BO3、BO5 或 BO7')
    if isinstance(game_number, bool) or not isinstance(game_number, int):
        raise ValueError('局数必须为整数')
    if not 1 <= game_number <= SERIES_LENGTHS[bo]:
        raise ValueError('当前局数超出了赛制范围')
    return SERIES_LENGTHS[bo]


def validate_scrim_prefix(events, *, rule=None, full=False, strict=True):
    fmt = scrim_rule(rule)
    result = check_draft(events, fmt, strict=strict)
    if not result['ok']:
        return False
    return (not full) or len(events or []) == fmt.total_hands


def next_scrim_action(events, *, rule=None):
    fmt = scrim_rule(rule)
    nxt = next_action(events, fmt)
    if nxt is None:
        return None
    if nxt.get('parallel') or nxt.get('blind'):
        return {'order': None, 'action': nxt['action'],
                'camp': nxt['camps'][0], 'camps': list(nxt['camps']),
                'remaining': dict(nxt['remaining']),
                'phase': nxt['phase'], 'parallel': bool(nxt.get('parallel'))}
    return {'order': nxt['order'], 'action': nxt['action'],
            'camp': nxt['camp'], 'phase': nxt['phase']}


def build_series_used(history, *, bo, game_number, teams):
    return series_used(history, teams=teams, bo=bo, game_number=game_number)


def _acting_camp(nxt):
    if nxt is None:
        return None
    if nxt.get('camps'):
        return str(nxt['camps'][0])
    return str(nxt.get('camp'))


def legal_scrim_candidates(events, hero_pool, *,
                           blue_player_pools=None, red_player_pools=None,
                           series_unavailable=(), series_used_by_team=None,
                           blue_team='蓝方', red_team='红方', bo='BO5',
                           game_number=1, rule=None):
    fmt = scrim_rule(rule)
    nxt = next_action(events, fmt)
    if nxt is None:
        return []
    camp = _acting_camp(nxt)
    used = series_used_by_team or {}
    if game_number > 1 and not used:
        raise ValueError('第 2 局起必须提供已验证的全局 BP 历史英雄集合')
    team = blue_team if camp == '1' else red_team
    for row in events or []:
        if row.get('action') != 'pick':
            continue
        side_team = blue_team if str(row.get('camp')) == '1' else red_team
        if pick_key(row.get('hero')) in used.get(side_team, ()):
            raise ValueError('当前 BP 已违反全局禁复用限制')
    pools = blue_player_pools if camp == '1' else red_player_pools
    candidates = legal_candidates(
        events, fmt, hero_pool, camp=camp,
        used_pick_keys=used.get(team, ()), player_pools=pools)
    if series_unavailable:
        blocked = {pick_key(hero) for hero in series_unavailable}
        candidates = [hero for hero in candidates if pick_key(hero) not in blocked]
    return candidates


def append_legal_scrim_action(events, hero, hero_pool, **kwargs):
    fmt = scrim_rule(kwargs.get('rule'))
    nxt = next_action(events, fmt)
    if nxt is None:
        raise ValueError('本局 BP 已完成')
    camp = _acting_camp(nxt)
    if hero not in legal_scrim_candidates(events, hero_pool, **kwargs):
        raise ValueError('该英雄在当前 BP 与系列赛状态下不可选择')
    return list(events) + [{
        'order': nxt.get('order') or len(events) + 1,
        'action': nxt['action'], 'camp': camp, 'hero': hero,
        'phase': nxt.get('phase'),
    }]


def scrim_state_payload(payload, catalog):
    """只读合法动作服务；不再限定 20 手，按 ``rule`` 返回对应排程。"""
    if not isinstance(payload, dict) or payload.get('source', 'scrim') != 'scrim':
        raise ValueError('该规则仅用于训练赛/征召，不能用于 KPL')
    fmt = scrim_rule(payload.get('rule'))
    bo = payload.get('bo', 'BO3')
    game_number = payload.get('gameNumber', 1)
    validate_series_context(bo, game_number)
    blue_team = payload.get('blueTeam', '本队')
    red_team = payload.get('redTeam', '对手')
    if (not isinstance(blue_team, str) or not isinstance(red_team, str)
            or not 0 < len(blue_team) <= 60 or not 0 < len(red_team) <= 60
            or blue_team == red_team):
        raise ValueError('蓝红方必须对应两支不同战队')
    events = payload.get('events', [])
    if not validate_scrim_prefix(events, rule=fmt):
        raise ValueError(f'选禁记录不符合当前规则：{fmt.title}')
    history = payload.get('history', [])
    used = build_series_used(history, bo=bo, game_number=game_number,
                             teams=(blue_team, red_team))
    candidates = legal_scrim_candidates(
        events, catalog, bo=bo, game_number=game_number,
        blue_team=blue_team, red_team=red_team, rule=fmt,
        series_used_by_team=used,
        blue_player_pools=payload.get('bluePlayerPools'),
        red_player_pools=payload.get('redPlayerPools'))
    nxt = next_scrim_action(events, rule=fmt)
    return {
        'rule': fmt.id,
        'ruleTitle': fmt.title,
        'bo': bo, 'gameNumber': game_number,
        'totalGames': SERIES_LENGTHS[bo],
        'blueTeam': blue_team, 'redTeam': red_team,
        'schedule': fmt.schedule,
        'nextAction': nxt,
        'legalCandidates': candidates,
        'completedActions': len(events),
        'historyPickCounts': {team: len(heroes) for team, heroes in used.items()},
        'playerPoolsVerified': bool(
            payload.get('bluePlayerPools') is not None
            and payload.get('redPlayerPools') is not None),
        'notes': [
            f"{fmt.title}：{fmt.bans_per_side['1']} Ban/方 + "
            f"{fmt.picks_per_side['1']} Pick/方，共 {fmt.total_hands} 手。",
            '全局 BP：己方本系列赛已选英雄不能再选；元流之子五形态按一个英雄累计，Ban 按形态。',
            '上一局 Ban 不延续；本局双方已 Ban/Pick 的英雄均不可再选择。',
            '未提供五名选手的真实英雄池时，只校验规则合法性，不代表选手一定会用。',
        ],
    }
