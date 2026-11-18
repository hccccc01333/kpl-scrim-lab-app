"""训练系列赛引擎（V2.0）：规则集、完赛判定、自动编组建议与 P0 系列赛分析。

口径（2026-11-14，与 docs/series_builder.md 一致）：
- 系列赛归属由教练确认；自动建议只产出候选，绝不改动已确认编组。
- 全局 BP 以训练赛规则集（RULESETS）为准，不默认套用 KPL 赛事规则；
  规则集只影响「累计不可再选」的账本口径，不参与编组归属判断。
- 营地名单按格式自动还原手序（campBp.pickOrderKnown）；名单不足时按终局名单处理，
  一切「应对 / 针对」类结论降级为「终局阵容对照」；缺数据一律返回 None 并
  写覆盖说明，不用 0 充数。
- BO5 不等于一定有五局：3:0 / 3:1 / 3:2 都是完整 BO5；训练赛还可能约定
  打满（completion_mode='fixed'）。完赛判定只认规则推导与教练标注。
"""
from __future__ import annotations

import math
import re
from datetime import datetime, time

import bp_rules
import hero_capabilities

# BO3/BO5/BO7 的最大局数与决胜目标沿用 bp_rules 的赛训口径。
SERIES_LENGTHS = bp_rules.SERIES_LENGTHS
BEST_OF_VALUES = sorted({int(v) for v in SERIES_LENGTHS.values()})

RULESETS = {
    'scrim-global-team': {
        'name': '全局BP · 队内不复用',
        'note': '本系列赛某队已选英雄不能再由该队选择（换边不重置，上一局禁用不延续）；'
                '对手已选英雄对我方仍然可选。',
    },
    'scrim-global-shared': {
        'name': '全局BP · 双方共同不复用',
        'note': '系列赛内任一方选过的英雄，双方都不能再选。',
    },
    'per-game': {
        'name': '每局独立 BP',
        'note': '各局独立 BP，没有跨局英雄消耗；账本只做记录，不产生「不可再选」。',
    },
}
DEFAULT_RULESET = 'scrim-global-team'

# 自动建议的推荐赛制：选中三局推荐 BO3、五局 BO5、七局 BO7，其余按最接近
# 的赛制给候选，不强行确定——三局也可能是 3:0 打完的 BO5。
BO_RECOMMEND = {1: 3, 2: 3, 3: 3, 4: 5, 5: 5, 6: 7, 7: 7}

# 编组时间连续性：间隔超过 180 分钟拆成两组候选；超过 90 分钟提示核实。
SUGGEST_GAP_SPLIT_MIN = 180
SUGGEST_GAP_WARN_MIN = 90


def ruleset_payload(ruleset_id):
    info = RULESETS.get(ruleset_id)
    if not info:
        return None
    return {'id': ruleset_id, 'name': info['name'], 'note': info['note']}


def derive_completion(best_of, completion_mode='standard', results=()):
    """按规则推导完赛状态。results 是本队视角逐局胜负（win/loss/draw/None）。

    标准决胜：任一方到 ceil(B/2) 胜即完赛（BO5 的 3:0/3:1/3:2 都算完赛）；
    固定打满：打满 B 局才算完赛；推导不出一律 open，不猜。教练可以随后
    PATCH 标注 interrupted / incomplete 覆盖推导结果。"""
    results = [r for r in results or [] if r in ('win', 'loss', 'draw')]
    if not results:
        return 'open'
    if completion_mode == 'fixed':
        return 'completed' if len(results) >= int(best_of) else 'open'
    target = math.ceil(int(best_of) / 2)
    wins = sum(1 for r in results if r == 'win')
    losses = sum(1 for r in results if r == 'loss')
    if max(wins, losses) >= target or len(results) >= int(best_of):
        return 'completed'
    return 'open'


# ---------------------------------------------------------------- 自动编组建议
def _parse_when(vector):
    """对局开始时刻：date 'YYYY-MM-DD' + clock 'HH:MM'。缺时刻返回 (当日零点, False)。"""
    date_text = str((vector or {}).get('date') or '')[:10]
    clock_text = str((vector or {}).get('clock') or '')
    try:
        day = datetime.strptime(date_text, '%Y-%m-%d').date()
    except ValueError:
        return None, False
    match = re.match(r'^(\d{1,2}):(\d{2})', clock_text)
    if not match:
        return datetime.combine(day, time(0, 0)), False
    return datetime.combine(day, time(int(match.group(1)), int(match.group(2)))), True


def suggest_groups(vectors, existing_map=None, *,
                   gap_split_min=SUGGEST_GAP_SPLIT_MIN,
                   gap_warn_min=SUGGEST_GAP_WARN_MIN):
    """从全部合格对局里找候选系列赛。只建议，不落库，不改动已确认编组。

    返回 {suggestions, blocked}：
    - blocked：已在其他系列赛的局（带所属系列，供编组页标红）。
    - suggestions：候选组（按开始时间倒序）。同一对手、同一天、时间连续归一组；
      间隔超过 gap_split_min 拆组、超过 gap_warn_min 提示核实；跨午夜且间隔
      未超阈值保持同组；缺开赛时间的组要求确认局序；对手缺失时按日期与
      训练组退化分组并提示补齐。
    """
    existing_map = existing_map or {}
    blocked, candidates = [], []
    for vector in vectors or []:
        key = str((vector or {}).get('key') or '')
        if not key:
            continue
        if key in existing_map:
            blocked.append({'matchKey': key,
                            'seriesId': existing_map[key].get('seriesId'),
                            'gameIndex': existing_map[key].get('gameIndex'),
                            'reason': '已属于其他系列赛，需先移出再编组'})
            continue
        when, has_clock = _parse_when(vector)
        if when is None:
            continue  # 连日期都没有的对局无法定位到时间轴，编组页不会展示
        candidates.append({'key': key, 'vector': vector, 'when': when, 'hasClock': has_clock})
    candidates.sort(key=lambda c: (c['when'], c['key']))

    buckets = {}
    for c in candidates:
        opponent = str(c['vector'].get('opponent') or '').strip()
        session = str(c['vector'].get('session') or '').strip()
        buckets.setdefault((opponent, session), []).append(c)

    suggestions = []
    for (opponent, session), items in buckets.items():
        groups = []
        for c in items:
            if not groups:
                groups.append([c])
                continue
            last = groups[-1][-1]
            same_group = False
            gap_warn = False
            if c['hasClock'] and last['hasClock']:
                gap = (c['when'] - last['when']).total_seconds() / 60.0
                if gap <= gap_split_min:
                    same_group = True
                    gap_warn = gap > gap_warn_min
            elif str(c['vector'].get('date') or '') == str(last['vector'].get('date') or ''):
                # 同一天但缺开赛时间：先归同组，交由教练确认局序，不擅自拆开
                same_group = True
            if same_group:
                if gap_warn:
                    c['gapWarn'] = True
                groups[-1].append(c)
            else:
                groups.append([c])
        for group in groups:
            suggestions.append(_suggestion_from_group(group, opponent, session))
    suggestions.sort(key=lambda s: (s.get('date') or '', s.get('matchKeys') and s['matchKeys'][0] or ''),
                     reverse=True)
    return {'suggestions': suggestions, 'blocked': blocked}


def _suggestion_from_group(group, opponent, session):
    keys = [c['key'] for c in group]
    count = len(keys)
    best_of = BO_RECOMMEND.get(min(count, max(BO_RECOMMEND)), 7)
    warnings = []
    if any(not c['hasClock'] for c in group):
        warnings.append('部分对局缺少开赛时间，请确认局序')
    if any(c.get('gapWarn') for c in group):
        warnings.append(f'组内存在较长间隔（超过 {SUGGEST_GAP_WARN_MIN} 分钟），请核实是否同一组')
    if not opponent:
        warnings.append('对手未标注，请补齐对手后再分析对手回应')
    versions = {str(c['vector'].get('version') or '').strip() for c in group} - {''}
    if len(versions) > 1:
        warnings.append('组内版本不一致：' + ' / '.join(sorted(versions)))
    sessions = {str(c['vector'].get('session') or '').strip() for c in group} - {''}
    if len(sessions) > 1:
        warnings.append('组内训练组不一致')
    if count > max(BEST_OF_VALUES):
        warnings.append('超过 7 局，无法一次确认为单个 BO，请拆分后再编组')
    confidence = 'high' if not warnings else (
        'medium' if all('开赛时间' not in w and '对手未标注' not in w for w in warnings) else 'low')
    return {
        'matchKeys': keys,
        'count': count,
        'bestOf': best_of,
        'completionMode': 'standard',
        'opponent': opponent or None,
        'session': session or None,
        'date': str(group[0]['vector'].get('date') or '')[:10] or None,
        'version': ' / '.join(sorted(versions)) or None,
        'warnings': warnings,
        'confidence': confidence,
        'needsReview': bool(warnings),
        'results': [str(c['vector'].get('result') or '') or None for c in group],
        'completion': derive_completion(best_of, 'standard',
                                        [c['vector'].get('result') for c in group]),
    }


# ---------------------------------------------------------------- 单局 BP 侧拆分
def _bp_sides(detail, vector=None):
    """detail → 本方/对方的终局选人与禁用名单。

    营地名单按格式自动还原的手序优先；旧人工 bp 只作回退；两者都没有时
    退化用向量里的阵容（来源 'roster'）。orderKnown 只在有手序数据时为 True。"""
    out = {'ownPicks': [], 'foePicks': [], 'ownBans': [], 'foeBans': [],
           'orderKnown': False, 'source': None, 'firstPick': None}

    def side_of(value):
        # 营地 bundle 的 ownSide 可能是 red/blue，也可能是 left/right；
        # 两种都归一到 left/right 再和 campBp 的键对齐。此前只认 left/right，
        # 导致 red 方的 picks 全部落到对手侧（2026-11-15 修复）。
        return {'blue': 'left', 'red': 'right',
                'left': 'left', 'right': 'right'}.get(str(value or '').strip().lower(), '')

    camp_bp = (detail or {}).get('campBp') or {}
    own_side = side_of((detail or {}).get('ownSide')) or side_of(camp_bp.get('ownSide')) \
        or side_of((detail or {}).get('ownCamp')) or side_of((vector or {}).get('camp'))
    foe_side = 'right' if own_side == 'left' else 'left' if own_side == 'right' else ''

    def names(entries):
        result = []
        for entry in entries or []:
            if isinstance(entry, dict) and entry.get('name'):
                result.append(str(entry['name']))
            elif isinstance(entry, str) and entry.strip():
                result.append(entry.strip())
        return result

    bp = (detail or {}).get('bp') or {}
    if any(bp.get(kind, {}).get(side) for kind in ('picks', 'bans') for side in ('left', 'right')):
        out['source'] = 'manual'
        out['orderKnown'] = True
        for kind, target in (('picks', 'Picks'), ('bans', 'Bans')):
            for side in ('left', 'right'):
                out['own' + target if side == own_side else 'foe' + target] = \
                    names((bp.get(kind) or {}).get(side))
        first = side_of(bp.get('firstPick'))
        if first:
            out['firstPick'] = 'own' if first == own_side else 'foe' if first == foe_side else None
        return out

    camp_picks = camp_bp.get('picks') or {}
    if any(camp_picks.get(side) for side in ('left', 'right')):
        out['source'] = 'camp'
        out['orderKnown'] = bool(camp_bp.get('pickOrderKnown'))
        for side in ('left', 'right'):
            target = 'ownPicks' if side == own_side else 'foePicks'
            out[target] = names(camp_picks.get(side))
        for side in ('left', 'right'):
            target = 'ownBans' if side == own_side else 'foeBans'
            out[target] = names((camp_bp.get('bans') or {}).get(side))
        return out

    # 连营地名单都没有：向量里的出场阵容兜底（只够做「曾选」账，禁用为空）
    vector = vector or {}
    if vector.get('heroes') or vector.get('heroesFoe'):
        out['source'] = 'roster'
        out['ownPicks'] = [str(h) for h in (vector.get('heroes') or [])]
        out['foePicks'] = [str(h) for h in (vector.get('heroesFoe') or [])]
    return out


def _median(values):
    nums = sorted(v for v in values or [] if isinstance(v, (int, float)))
    if not nums:
        return None
    mid = len(nums) // 2
    if len(nums) % 2:
        return nums[mid]
    return (nums[mid - 1] + nums[mid]) / 2.0


def _comp_tags(heroes):
    """阵容功能标签（双前排 / 强开团 / 无前排…）。全员无能力数据不猜，返回 None。"""
    tags = hero_capabilities.functional_tags([h for h in heroes or [] if h])
    return '·'.join(tags) if tags else None


def _change_level(changed):
    if changed <= 0:
        return '未变'
    if changed <= 2:
        return '小调整'
    return '大调整'


# ---------------------------------------------------------------- 单组系列赛分析
def analyze_series(series, games):
    """单组系列赛的 P0 分析。games 按 game_index 升序，元素：
    {matchKey, gameIndex, vector, detail}（vector/detail 可为 None）。

    返回 {games, adjustments, bpLedger, opponentResponse, afterLoss,
    compSwitch, score, coverage, caveats}。所有结论带分母；营地名单没有
    手序，调整对照一律按「终局阵容」理解，不虚构 BP 应对顺序。"""
    ruleset_id = series.get('rulesetId') or DEFAULT_RULESET
    rows, caveats = [], []
    used_us, used_foe = [], []          # 累计已选（含当前局，按局推进）
    prev = None
    after_loss, comp_pairs, foe_response = [], [], []
    illegal_reuse = []

    for game in games or []:
        vector = game.get('vector') or {}
        detail = game.get('detail')
        sides = _bp_sides(detail, vector)
        heroes_own = [str(h) for h in (sides['ownPicks'] or vector.get('heroes') or []) if h][:5]
        heroes_foe = [str(h) for h in (sides['foePicks'] or vector.get('heroesFoe') or []) if h][:5]
        result = str(vector.get('result') or '') or None
        at10 = vector.get('at10')
        row = {
            'matchKey': game.get('matchKey'),
            'gameIndex': int(game.get('gameIndex') or 0),
            'date': str(vector.get('date') or '')[:10] or None,
            'clock': vector.get('clock') or None,
            'camp': vector.get('camp') or None,
            'result': result,
            'at10': at10,
            'finalDiff': vector.get('finalDiff'),
            'duration': vector.get('duration'),
            'heroesOwn': heroes_own,
            'heroesFoe': heroes_foe,
            'bansOwn': sides['ownBans'],
            'bansFoe': sides['foeBans'],
            'bpSource': sides['source'],
            'orderKnown': bool(sides['orderKnown']),
            'compOwn': _comp_tags(heroes_own),
            'compFoe': _comp_tags(heroes_foe),
            'processKnown': bool((detail or {}).get('process')),
        }
        # 全局 BP 账本：复用检测在前（当前局先对照历史累计，再并入累计）
        reuse = sorted(set(heroes_own) & set(used_us)) if used_us else []
        if reuse:
            illegal_reuse.append({'gameIndex': row['gameIndex'], 'heroes': reuse})
        new_us = used_us + heroes_own
        new_foe = used_foe + heroes_foe
        shared_block = set(used_us) | set(used_foe)
        if ruleset_id == 'scrim-global-shared':
            block_us, block_foe = set(shared_block), set(shared_block)
        elif ruleset_id == 'per-game':
            block_us, block_foe = set(), set()
        else:  # scrim-global-team：只挡本队已选
            block_us, block_foe = set(used_us), set(used_foe)
        row['ledger'] = {
            'usedUsAfter': list(dict.fromkeys(new_us)),
            'usedFoeAfter': list(dict.fromkeys(new_foe)),
            'usedUsCount': len(set(new_us)),
            'usedFoeCount': len(set(new_foe)),
            'blockUs': sorted(block_us),
            'blockFoe': sorted(block_foe),
            'reuseIllegal': reuse,
        }
        # 与上一局的调整对照（终局阵容口径）
        if prev is not None:
            new_heroes = [h for h in heroes_own if h not in set(prev['heroesOwn'])]
            dropped = [h for h in prev['heroesOwn'] if h not in set(heroes_own)]
            foe_new = [h for h in heroes_foe if h not in set(prev['heroesFoe'])]
            row['adjustment'] = {
                'newOwn': new_heroes,
                'droppedOwn': dropped,
                'changedCount': len(new_heroes),
                'changeLevel': _change_level(len(new_heroes)),
                'changeLabel': _change_level(len(new_heroes)) if new_heroes else '与上一局相同',
                'compChanged': bool(prev['compOwn']) and bool(row['compOwn']) and prev['compOwn'] != row['compOwn'],
            }
            foe_row = {
                'gameIndex': row['gameIndex'],
                'newFoe': foe_new,
                'droppedFoe': [h for h in prev['heroesFoe'] if h not in set(heroes_foe)],
                'compChanged': bool(prev['compFoe']) and bool(row['compFoe']) and prev['compFoe'] != row['compFoe'],
                'banRepeat': sorted(set(row['bansFoe']) & set(prev['bansFoe'])),
            }
            foe_response.append(foe_row)
            if prev['result'] == 'loss' and row['result'] in ('win', 'loss'):
                delta = None
                if isinstance(prev['at10'], (int, float)) and isinstance(at10, (int, float)):
                    delta = round(at10 - prev['at10'], 1)
                after_loss.append({'fromGame': prev['gameIndex'], 'toGame': row['gameIndex'],
                                   'matchKeys': [prev['matchKey'], row['matchKey']],
                                   'nextResult': row['result'], 'at10Delta': delta})
            if prev['compOwn'] and row['compOwn']:
                comp_pairs.append({'continued': prev['compOwn'] == row['compOwn'],
                                   'nextResult': row['result'],
                                   'fromGame': prev['gameIndex'], 'toGame': row['gameIndex']})
        used_us, used_foe = new_us, new_foe
        rows.append(row)
        prev = row

    score = {
        'us': sum(1 for r in rows if r['result'] == 'win'),
        'them': sum(1 for r in rows if r['result'] == 'loss'),
    }
    if score['us'] == 0 and score['them'] == 0 and rows:
        caveats.append('本组对局缺少胜负结果（result 缺失），比分与胜率相关结论一律不给出。')
    coverage = {
        'games': len(rows),
        'withVector': sum(1 for g in games or [] if g.get('vector')),
        'withDetail': sum(1 for r in rows if r['bpSource']),
        'orderKnownGames': sum(1 for r in rows if r['orderKnown']),
        'processKnownGames': sum(1 for r in rows if r['processKnown']),
        'at10Games': sum(1 for r in rows if isinstance(r['at10'], (int, float))),
    }
    if rows and coverage['orderKnownGames'] == 0:
        caveats.append('全部对局仅有终局名单（BP 手序与先后手未知）：不推断对手针对顺序，'
                       '调整对照请按「终局阵容」理解。')
    elif coverage['orderKnownGames'] < len(rows):
        caveats.append(f'仅 {coverage["orderKnownGames"]}/{len(rows)} 局有 BP 手序，'
                       '手序类结论只覆盖有手序的局。')
    if rows and coverage['at10Games'] < len(rows):
        caveats.append(f'仅 {coverage["at10Games"]}/{len(rows)} 局有 10 分钟经济差'
                       '（需要回放/过程数据），前期对比结论按此分母计算。')
    if illegal_reuse:
        detail_text = '；'.join(f"G{item['gameIndex']} 重复 {('、'.join(item['heroes']))}" for item in illegal_reuse)
        caveats.append(f'检测到跨局复用已选英雄（{detail_text}），与规则集'
                       f'「{RULESETS.get(ruleset_id, {}).get("name", ruleset_id)}」不符：'
                       '请核实规则集或该局阵容数据，相关消耗账本已按实际记录展示。')

    next_wins = sum(1 for p in after_loss if p['nextResult'] == 'win')
    deltas = [p['at10Delta'] for p in after_loss if isinstance(p['at10Delta'], (int, float))]
    after_loss_summary = {
        'n': len(after_loss),
        'nextWins': next_wins,
        'nextWinRate': round(next_wins / len(after_loss) * 100, 1) if after_loss else None,
        'medianAt10Delta': _median(deltas),
        'deltaSamples': len(deltas),
        'pairs': after_loss,
    }
    continued = [p for p in comp_pairs if p['continued'] and p['nextResult']]
    switched = [p for p in comp_pairs if not p['continued'] and p['nextResult']]
    comp_switch = {
        'pairs': len(comp_pairs),
        'continued': {'n': len(continued),
                      'nextWins': sum(1 for p in continued if p['nextResult'] == 'win'),
                      'winRate': round(sum(1 for p in continued if p['nextResult'] == 'win') / len(continued) * 100, 1) if continued else None},
        'switched': {'n': len(switched),
                     'nextWins': sum(1 for p in switched if p['nextResult'] == 'win'),
                     'winRate': round(sum(1 for p in switched if p['nextResult'] == 'win') / len(switched) * 100, 1) if switched else None},
    }
    return {
        'games': rows,
        'score': score,
        'bpLedger': {
            'ruleset': ruleset_payload(ruleset_id),
            'perGame': [{'gameIndex': r['gameIndex'], 'usedUsCount': r['ledger']['usedUsCount'],
                         'usedFoeCount': r['ledger']['usedFoeCount'],
                         'usedUsAfter': r['ledger']['usedUsAfter'],
                         'usedFoeAfter': r['ledger']['usedFoeAfter'],
                         'blockUs': r['ledger']['blockUs'], 'blockFoe': r['ledger']['blockFoe']}
                        for r in rows],
        },
        'opponentResponse': foe_response,
        'afterLoss': after_loss_summary,
        'compSwitch': comp_switch,
        'coverage': coverage,
        'caveats': caveats,
    }


# ---------------------------------------------------------------- 多组汇总
def summarize_series(rows):
    """多组系列赛汇总（供跨局分析「系列赛」页签）。

    rows: [{series, games}]，games 是 analyze_series 输出的逐局行（至少含
    gameIndex/result/at10/heroesOwn/heroesFoe/compOwn）。同一系列赛内部
    小局不视为独立实验：所有胜率都标注样本量，n<2 的格一律给 None。
    """
    by_index = {}
    after_loss_all, comp_pairs_all = [], []
    consumption = {}
    totals = {'series': 0, 'completed': 0, 'seriesWins': 0, 'seriesLosses': 0,
              'games': 0, 'gameWins': 0}
    attention = []
    for row in rows or []:
        series = row.get('series') or {}
        games = [g for g in row.get('games') or [] if g.get('result') in ('win', 'loss')]
        totals['series'] += 1
        if series.get('completion') == 'completed':
            totals['completed'] += 1
        score = row.get('score') or {}
        if score.get('us') and score.get('us', 0) > (score.get('them') or 0):
            totals['seriesWins'] += 1
        elif score.get('them'):
            totals['seriesLosses'] += 1
        totals['games'] += len(games)
        totals['gameWins'] += sum(1 for g in games if g['result'] == 'win')
        for game in row.get('games') or []:
            index = int(game.get('gameIndex') or 0)
            if not 1 <= index <= 7:
                continue
            bucket = by_index.setdefault(index, {'games': [], 'used': [], 'at10': []})
            if game.get('result') in ('win', 'loss'):
                bucket['games'].append(game['result'])
            if isinstance(game.get('at10'), (int, float)):
                bucket['at10'].append(game['at10'])
            ledger = game.get('ledger') or {}
            if ledger.get('usedUsCount'):
                bucket['used'].append(ledger['usedUsCount'])
            consumption.setdefault(index, {'us': [], 'foe': []})
            if ledger.get('usedUsCount'):
                consumption[index]['us'].append(ledger['usedUsCount'])
            if ledger.get('usedFoeCount'):
                consumption[index]['foe'].append(ledger['usedFoeCount'])
        after_loss_all.extend((row.get('afterLoss') or {}).get('pairs') or [])
        switch = row.get('compSwitch') or {}
        comp_pairs_all.append(switch)

    def _bucket(index, bucket):
        n = len(bucket['games'])
        wins = sum(1 for r in bucket['games'] if r == 'win')
        return {'gameIndex': index, 'n': n,
                'wins': wins,
                'winRate': round(wins / n * 100, 1) if n else None,
                'medianAt10': _median(bucket['at10']),
                'at10Samples': len(bucket['at10']),
                'avgUsedUs': round(sum(bucket['used']) / len(bucket['used']), 1) if bucket['used'] else None}

    game_sequence = [_bucket(index, by_index[index]) for index in sorted(by_index)]
    next_wins = sum(1 for p in after_loss_all if p.get('nextResult') == 'win')
    deltas = [p['at10Delta'] for p in after_loss_all if isinstance(p.get('at10Delta'), (int, float))]
    after_loss = {
        'n': len(after_loss_all),
        'nextWins': next_wins,
        'nextWinRate': round(next_wins / len(after_loss_all) * 100, 1) if after_loss_all else None,
        'medianAt10Delta': _median(deltas),
        'deltaSamples': len(deltas),
    }
    consumption_pace = [
        {'gameIndex': index,
         'avgUsedUs': round(sum(v['us']) / len(v['us']), 1) if v['us'] else None,
         'avgUsedFoe': round(sum(v['foe']) / len(v['foe']), 1) if v['foe'] else None,
         'n': len(v['us'])}
        for index, v in sorted(consumption.items())]

    totals['seriesWinRate'] = (round(totals['seriesWins'] /
                                     max(totals['seriesWins'] + totals['seriesLosses'], 0) * 100, 1)
                               if totals['seriesWins'] + totals['seriesLosses'] else None)
    totals['gameWinRate'] = (round(totals['gameWins'] / totals['games'] * 100, 1)
                             if totals['games'] else None)
    return {
        'totals': totals,
        'gameSequence': game_sequence,
        'afterLoss': after_loss,
        'consumption': consumption_pace,
        'attention': attention,
    }


def build_attention(rows, summary):
    """「本轮需要关注」清单：只列有明确证据的信号，每条带证据入口。

    信号（宁缺勿滥，样本不足一律不报）：
    - late-drop：G4 及以后的小局胜率显著低于该组整体（差 ≥15pp，且后段 n≥2）。
    - losing-streak：以 ≥3 连败收尾的已确认系列赛。
    - after-loss-flat：≥2 次「输局后下一局」且无一改善（下一局仍输）。
    - needs-review：编组待核实的系列赛。
    - interrupted：教练标注中断的系列赛（提醒补采或确认）。
    """
    attention = []
    overall_wr = (summary.get('totals') or {}).get('gameWinRate')
    for row in rows or []:
        series = row.get('series') or {}
        games = row.get('games') or []
        links = [g.get('matchKey') for g in games if g.get('matchKey')]
        late = [g for g in games if int(g.get('gameIndex') or 0) >= 4 and g.get('result') in ('win', 'loss')]
        early = [g for g in games if int(g.get('gameIndex') or 0) < 4 and g.get('result') in ('win', 'loss')]
        if len(late) >= 2 and len(early) >= 2:
            late_wr = sum(1 for g in late if g['result'] == 'win') / len(late) * 100
            early_wr = sum(1 for g in early if g['result'] == 'win') / len(early) * 100
            if early_wr - late_wr >= 15:
                attention.append({
                    'seriesId': series.get('id'), 'kind': 'late-drop',
                    'title': f"{series.get('opponent') or '未命名对手'} BO{series.get('bestOf')}：后段局明显掉线",
                    'detail': f'前段 {len(early)} 局胜率 {round(early_wr, 1)}%，G4 起后段 {len(late)} 局'
                              f'胜率 {round(late_wr, 1)}%。结合英雄消耗与阵容变化核对是否后段选人空间受限。',
                    'links': links, 'gameIndexes': [g.get('gameIndex') for g in late]})
        streak, streak_end = 0, None
        for game in games:
            if game.get('result') == 'loss':
                streak += 1
                streak_end = game
            else:
                streak, streak_end = 0, None
        if streak >= 3 and streak_end is not None:
            attention.append({
                'seriesId': series.get('id'), 'kind': 'losing-streak',
                'title': f"{series.get('opponent') or '未命名对手'} BO{series.get('bestOf')}：以 {streak} 连败收尾",
                'detail': f'最后 {streak} 局连续失利（G{streak_end.get("gameIndex")} 止）。'
                          '建议优先复盘该段 BP 调整与对手回应。',
                'links': links, 'gameIndexes': [streak_end.get('gameIndex')]})
        pairs = (row.get('afterLoss') or {}).get('pairs') or []
        if len(pairs) >= 2 and all(p.get('nextResult') == 'loss' for p in pairs):
            attention.append({
                'seriesId': series.get('id'), 'kind': 'after-loss-flat',
                'title': f"{series.get('opponent') or '未命名对手'} BO{series.get('bestOf')}：输局后未见改善",
                'detail': f'{len(pairs)} 次输局后的下一局全部仍为失利；调整幅度与 10 分钟经济差变化'
                          '可在该组下钻页核对。',
                'links': links, 'gameIndexes': [p.get('toGame') for p in pairs]})
        if series.get('status') == 'needs_review':
            attention.append({
                'seriesId': series.get('id'), 'kind': 'needs-review',
                'title': f"{series.get('opponent') or '未命名对手'} 的编组待核实",
                'detail': '该系列赛带有待核实标记（自动建议确认或含冲突提示），请确认局序与赛制。',
                'links': links, 'gameIndexes': []})
        if series.get('completion') == 'interrupted':
            attention.append({
                'seriesId': series.get('id'), 'kind': 'interrupted',
                'title': f"{series.get('opponent') or '未命名对手'} BO{series.get('bestOf')} 被标注为中断",
                'detail': '中断的系列赛不计入完赛统计；确认是否补采剩余对局。',
                'links': links, 'gameIndexes': []})
    return attention
