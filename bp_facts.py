"""把外部事实表（巅峰千强对位 / KPL 组合）查成本局 BP 复盘要的三块结论。

数据由 `scripts/build_bp_facts.py` 离线生成，落在 `data/facts/`：

* `lane_matchups.json` —— 巅峰千强同分路对位，带**超额胜率**
  （实际对位胜率 − 按两个英雄各自基准算出的期望）。正数＝这对组合本身占优。
* `kpl_combos.json` —— KPL 赛事里同队双人 / 三人 / 整阵容组合的场次与胜率
  （由本项目 `scripts/crawl_kpl_bp.py` 从 KPL 官方接口自抓生成，带 `teams` 归属）。

口径纪律：
* 对位只用**大盘**（巅峰千强），绝不用 KPL——KPL 的英雄对位被「强队选强英雄」污染，
  冷门英雄样本又极少，拿它判克制会把「英雄本身弱」说成「被克制」。
* 组合与赛事命中用 KPL：教练要的是「这套阵容职业赛场见得到」，有就算命中。
* 三张表各带来源与样本，不合成一个分。
"""
from __future__ import annotations

import json
import math
from pathlib import Path

try:
    import hero_roles
except Exception:  # pragma: no cover
    hero_roles = None

ROOT = Path(__file__).resolve().parent
FACTS = ROOT / 'data' / 'facts'
LANES = ('对抗路', '打野', '中路', '发育路', '游走')

_cache: dict[str, tuple[float, dict]] = {}


def _load(name):
    path = FACTS / name
    try:
        stat = path.stat()
    except OSError:
        return None
    hit = _cache.get(name)
    if hit and hit[0] == stat.st_mtime:
        return hit[1]
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    _cache[name] = (stat.st_mtime, value)
    return value


def _lane_pairs():
    data = _load('lane_matchups.json') or {}
    table = {}
    for row in data.get('pairs') or []:
        table[(row['a'], row['b'])] = row
        table[(row['b'], row['a'])] = {**row, 'a': row['b'], 'b': row['a'],
                                       'wr': round(100 - row['wr'], 1),
                                       'expected': round(100 - row['expected'], 1),
                                       'excess': round(-row['excess'], 1)}
    return data, table


def _kpl_combos():
    data = _load('kpl_combos.json') or {}
    pairs, trios, lineups = {}, {}, {}
    for row in data.get('pairs') or []:
        pairs[tuple(row['heroes'])] = row
    for row in data.get('trios') or []:
        trios[tuple(row['heroes'])] = row
    # 整阵容：key 是 5 个英雄名排序后的元组（老文件没有 lineups 时就是空表）
    for row in data.get('lineups') or []:
        heroes = row.get('heroes') or []
        if len(heroes) == 5:
            lineups[tuple(sorted(heroes))] = row
    return data, pairs, trios, lineups


def _latest_year(data, *groups):
    """最近一个赛季年份：组合行里的最大 year，退化为窗口结束年份。"""
    years = []
    for group in groups:
        for row in group:
            try:
                years.append(int(row.get('year') or 0))
            except (TypeError, ValueError):
                continue
    years = [year for year in years if year]
    if years:
        return max(years)
    window_end = str(data.get('windowEnd') or '')
    return int(window_end[:4]) if window_end[:4].isdigit() else None


def _lineup_of(heroes, kpl_lineups):
    """本队 5 人整阵容命中：排序后去 lineups 里查；不足 5 人视为没命中。"""
    if len(heroes) != 5:
        return None
    row = kpl_lineups.get(tuple(heroes))
    if not row:
        return None
    return {'heroes': row.get('heroes') or list(heroes),
            'n': row.get('n'), 'wins': row.get('wins'), 'wr': row.get('wr'),
            'year': row.get('year'), 'teams': row.get('teams') or []}


def _own_side(detail):
    draft = detail.get('draft') or {}
    picks = draft.get('picks') or {}
    own = detail.get('ownCamp') or 'blue'
    own_key = 'right' if own in ('red', 'right') else 'left'
    foe_key = 'left' if own_key == 'right' else 'right'
    def names(key):
        return [str((row or {}).get('name') or '').strip() for row in (picks.get(key) or [])]
    return names(own_key), names(foe_key)


_SHRINK_K = 40.0
_Z95 = 1.959963984540054


def _lane_reliability(n, ci_low, ci_high):
    if not n or n < 200:
        return 'low'
    rating = 'high' if n >= 1000 else 'medium'
    if ci_low is None or ci_high is None or (ci_low <= 0 <= ci_high):
        rating = 'medium' if rating == 'high' else 'low'
    return rating


def _lane_stats(row):
    n = row.get('n') or 0
    wr = row.get('wr')
    expected = row.get('expected')
    excess = row.get('excess')
    if not n or wr is None:
        return {'excessCI': None, 'reliability': 'low',
                'shrunkExcess': excess, 'shrunkWr': wr}
    p = max(0.0, min(1.0, float(wr) / 100.0))
    se = math.sqrt(p * (1 - p) / n)
    lo = p - _Z95 * se
    hi = p + _Z95 * se
    exp = (float(expected) / 100.0) if expected is not None else 0.5
    ci_low = (lo - exp) * 100.0
    ci_high = (hi - exp) * 100.0
    wins = p * n
    alpha = _SHRINK_K * exp
    beta = _SHRINK_K * (1 - exp)
    shrunk_p = (wins + alpha) / (n + alpha + beta)
    shrunk_wr = shrunk_p * 100.0
    base = (expected if expected is not None else 50.0)
    shrunk_excess = shrunk_wr - base
    reliability = _lane_reliability(n, ci_low, ci_high)
    return {
        'excessCI': [round(ci_low, 2), round(ci_high, 2)],
        'reliability': reliability,
        'shrunkExcess': round(shrunk_excess, 2),
        'shrunkWr': round(shrunk_wr, 2),
    }


def _team_gold_at(detail, target_sec):
    """从 detail 的 ownDiff/times 序列取最接近 target_sec 的队伍经济差。"""
    own_diff = detail.get('ownDiff') or []
    times = detail.get('times') or []
    if not own_diff or not times:
        return None
    best = None
    for t, v in zip(times, own_diff):
        if t is None or v is None:
            continue
        if best is None or abs(t - target_sec) < abs(best[0] - target_sec):
            best = (t, v)
    return best[1] if best else None


def for_match(detail):
    """本局三块结论：对位压制（大盘） / 赛事命中 / 联动组合（KPL）。"""
    own_heroes, foe_heroes = _own_side(detail)
    if not own_heroes:
        return None
    lane_data, lane_table = _lane_pairs()
    combo_data, kpl_pairs, kpl_trios, kpl_lineups = _kpl_combos()

    # 1) 对位压制：用营地面板里的位置对齐五路
    by_lane = {}
    for player in detail.get('players') or []:
        lane = player.get('position')
        if lane in LANES and player.get('hero'):
            by_lane.setdefault(lane, {})[(player.get('camp') or '')] = player
    own_camp = detail.get('ownCamp') or 'blue'
    foe_camp = 'red' if own_camp == 'blue' else 'blue'
    lanes = []
    for lane in LANES:
        pair = by_lane.get(lane) or {}
        mine, foe = pair.get(own_camp), pair.get(foe_camp)
        if not mine or not foe:
            continue
        row = lane_table.get((mine.get('hero'), foe.get('hero')))
        if not row:
            # 没对位样本时，把两个英雄在巅峰千强的使用率带出去，解释「为什么没有」
            heroes = lane_data.get('heroes') or {}
            lanes.append({'lane': lane, 'mine': mine.get('hero'), 'foe': foe.get('hero'),
                          'state': 'no-sample', 'n': 0,
                          'minePick': (heroes.get(mine.get('hero')) or {}).get('pick'),
                          'foePick': (heroes.get(foe.get('hero')) or {}).get('pick'),
                          'excessCI': None, 'reliability': 'low',
                          'shrunkExcess': None, 'shrunkWr': None,
                          'hypothesis': 'no-sample',
                          'realisedEarly': None, 'realisedFinal': None,
                          'attribution': '证据不足',
                          'earlyDiff': _team_gold_at(detail, 240),
                          'finalDiff': _team_gold_at(detail, detail.get('duration') or 0)})
            continue
        excess = row['excess']
        stats = _lane_stats(row)
        ci = stats['excessCI']
        if stats['reliability'] == 'low':
            state = 'even'
        elif ci is not None and ci[0] > 0 and excess is not None and excess >= 2:
            state = 'ahead'
        elif ci is not None and ci[1] < 0 and excess is not None and excess <= -2:
            state = 'behind'
        else:
            state = 'even'
        # BP 预期与执行验证：假设（verdict）vs 证据（队伍/个人经济差）
        early_diff = _team_gold_at(detail, 240)
        realised_early = None
        if state in ('ahead', 'behind') and early_diff is not None:
            realised_early = (early_diff > 0) if state == 'ahead' else (early_diff < 0)
        now_diff = None
        # now_diff 由调用方（frontend）的 per-player gold 提供；此处用队伍终局经济差兜底
        final_diff = _team_gold_at(detail, detail.get('duration') or 0)
        realised_final = None
        if state in ('ahead', 'behind') and final_diff is not None:
            realised_final = (final_diff > 0) if state == 'ahead' else (final_diff < 0)
        if state not in ('ahead', 'behind'):
            attribution = '证据不足'
        elif realised_final is True:
            attribution = 'BP兑现'
        elif realised_final is False:
            attribution = 'BP未兑现'
        else:
            attribution = '证据不足'
        lanes.append({'lane': lane, 'mine': mine.get('hero'), 'foe': foe.get('hero'),
                      'state': state, 'n': row['n'], 'wr': row['wr'],
                      'expected': row['expected'], 'excess': excess,
                      'excessCI': stats['excessCI'],
                      'reliability': stats['reliability'],
                      'shrunkExcess': stats['shrunkExcess'],
                      'shrunkWr': stats['shrunkWr'],
                      'hypothesis': state,
                      'realisedEarly': realised_early,
                      'realisedFinal': realised_final,
                      'attribution': attribution,
                      'earlyDiff': early_diff,
                      'finalDiff': final_diff})

    # 2) 赛事命中：本队 5 人里的双人 / 三人组合，在 KPL 出现过几次
    heroes = sorted({h for h in own_heroes if h})
    pair_hits, trio_hits = [], []
    for i in range(len(heroes)):
        for j in range(i + 1, len(heroes)):
            row = kpl_pairs.get((heroes[i], heroes[j]))
            if row:
                pair_hits.append({'heroes': [heroes[i], heroes[j]], 'n': row['n'],
                                  'wr': row['wr'], 'year': row.get('year'),
                                  'teams': row.get('teams') or []})
            for k in range(j + 1, len(heroes)):
                trow = kpl_trios.get((heroes[i], heroes[j], heroes[k]))
                if trow:
                    trio_hits.append({'heroes': [heroes[i], heroes[j], heroes[k]],
                                      'n': trow['n'], 'wr': trow['wr'],
                                      'year': trow.get('year'),
                                      'teams': trow.get('teams') or []})
    pair_hits.sort(key=lambda item: -item['n'])
    trio_hits.sort(key=lambda item: -item['n'])

    # 双方阵容里所有双人组合的 KPL 战绩，供「联动组合」卡片直接查（自家 + 对手）
    combo_index = {}
    for group in (heroes, fh := sorted({h for h in foe_heroes if h})):
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                row = kpl_pairs.get((group[i], group[j]))
                if row:
                    combo_index[f'{group[i]}+{group[j]}'] = {
                        'n': row['n'], 'wr': row['wr'], 'year': row.get('year'),
                        'teams': row.get('teams') or []}
                    combo_index[f'{group[j]}+{group[i]}'] = combo_index[f'{group[i]}+{group[j]}']

    # 对手侧的组合，给 BP 复盘做对照
    foe_pairs = []
    for i in range(len(fh)):
        for j in range(i + 1, len(fh)):
            row = kpl_pairs.get((fh[i], fh[j]))
            if row:
                foe_pairs.append({'heroes': [fh[i], fh[j]], 'n': row['n'],
                                  'wr': row['wr'], 'teams': row.get('teams') or []})
    foe_pairs.sort(key=lambda item: -item['n'])

    # 3) 整阵容命中：本队 5 个 pick 排序后整套查（顺序不同算同一套）
    lineup = _lineup_of(heroes, kpl_lineups)
    latest_year = _latest_year(combo_data, kpl_pairs.values(), kpl_trios.values(),
                               kpl_lineups.values())
    total_trios = len(heroes) * (len(heroes) - 1) * (len(heroes) - 2) // 6 if len(heroes) >= 3 else 0

    # 阵容结构分析（英雄能力标签种子表）
    structure = None
    if hero_roles is not None:
        structure = hero_roles.lineup_structure(heroes)
        structure['source'] = 'hero_roles_seed'

    # BP 预期与执行验证汇总
    attribution_counts = {}
    for ln in lanes:
        attribution_counts[ln.get('attribution', '证据不足')] = attribution_counts.get(ln.get('attribution', '证据不足'), 0) + 1
    hypothesis = {
        'lanes': [{'lane': ln['lane'], 'hypothesis': ln.get('hypothesis'),
                   'attribution': ln.get('attribution'),
                   'realisedEarly': ln.get('realisedEarly'),
                   'realisedFinal': ln.get('realisedFinal')} for ln in lanes],
        'attributionCounts': attribution_counts,
    }

    return {
        'schema': 'bp-match-facts-v1',
        'ladder': {'source': 'ladder', 'bracket': lane_data.get('bracket'),
                   'windowEnd': lane_data.get('windowEnd'),
                   'minN': lane_data.get('minN'), 'minPickRate': lane_data.get('minPickRate'),
                   'lanes': lanes},
        'hypothesis': hypothesis,
        'structure': structure,
        'kpl': {'source': 'kpl', 'sinceYear': combo_data.get('sinceYear'),
                'games': combo_data.get('games'), 'minGames': combo_data.get('minGames'),
                'updatedAt': combo_data.get('updatedAt'),
                'sourceLabel': 'KPL 官方赛事',
                'windowStart': combo_data.get('windowStart'),
                'windowEnd': combo_data.get('windowEnd'),
                'leagueCount': combo_data.get('leagueCount'),
                'latestYear': latest_year,
                'pairs': pair_hits[:6], 'trios': trio_hits[:6], 'foePairs': foe_pairs[:4],
                'hitPairs': len(pair_hits), 'hitTrios': len(trio_hits),
                'totalPairs': len(heroes) * (len(heroes) - 1) // 2,
                'totalTrios': total_trios,
                'comboIndex': combo_index,
                'lineup': lineup, 'lineupSeen': lineup is not None},
    }
