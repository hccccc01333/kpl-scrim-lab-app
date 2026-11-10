"""把外部事实表（巅峰千强对位 / KPL 组合）查成本局 BP 复盘要的三块结论。

数据由 `scripts/build_bp_facts.py` 离线生成，落在 `data/facts/`：

* `lane_matchups.json` —— 巅峰千强同分路对位，带**超额胜率**
  （实际对位胜率 − 按两个英雄各自基准算出的期望）。正数＝这对组合本身占优。
* `kpl_combos.json` —— KPL 赛事里同队双人 / 三人组合的场次与胜率。

口径纪律：
* 对位只用**大盘**（巅峰千强），绝不用 KPL——KPL 的英雄对位被「强队选强英雄」污染，
  冷门英雄样本又极少，拿它判克制会把「英雄本身弱」说成「被克制」。
* 组合与赛事命中用 KPL：教练要的是「这套阵容职业赛场见得到」，有就算命中。
* 三张表各带来源与样本，不合成一个分。
"""
from __future__ import annotations

import json
from pathlib import Path

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
    pairs, trios = {}, {}
    for row in data.get('pairs') or []:
        pairs[tuple(row['heroes'])] = row
    for row in data.get('trios') or []:
        trios[tuple(row['heroes'])] = row
    return data, pairs, trios


def _own_side(detail):
    draft = detail.get('draft') or {}
    picks = draft.get('picks') or {}
    own = detail.get('ownCamp') or 'blue'
    own_key = 'right' if own in ('red', 'right') else 'left'
    foe_key = 'left' if own_key == 'right' else 'right'
    def names(key):
        return [str((row or {}).get('name') or '').strip() for row in (picks.get(key) or [])]
    return names(own_key), names(foe_key)


def for_match(detail):
    """本局三块结论：对位压制（大盘） / 赛事命中 / 联动组合（KPL）。"""
    own_heroes, foe_heroes = _own_side(detail)
    if not own_heroes:
        return None
    lane_data, lane_table = _lane_pairs()
    combo_data, kpl_pairs, kpl_trios = _kpl_combos()

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
                          'foePick': (heroes.get(foe.get('hero')) or {}).get('pick')})
            continue
        excess = row['excess']
        state = 'ahead' if excess >= 2 else 'behind' if excess <= -2 else 'even'
        lanes.append({'lane': lane, 'mine': mine.get('hero'), 'foe': foe.get('hero'),
                      'state': state, 'n': row['n'], 'wr': row['wr'],
                      'expected': row['expected'], 'excess': excess})

    # 2) 赛事命中：本队 5 人里的双人 / 三人组合，在 KPL 出现过几次
    heroes = sorted({h for h in own_heroes if h})
    pair_hits, trio_hits = [], []
    for i in range(len(heroes)):
        for j in range(i + 1, len(heroes)):
            row = kpl_pairs.get((heroes[i], heroes[j]))
            if row:
                pair_hits.append({'heroes': [heroes[i], heroes[j]], 'n': row['n'],
                                  'wr': row['wr'], 'year': row.get('year')})
            for k in range(j + 1, len(heroes)):
                trow = kpl_trios.get((heroes[i], heroes[j], heroes[k]))
                if trow:
                    trio_hits.append({'heroes': [heroes[i], heroes[j], heroes[k]],
                                      'n': trow['n'], 'wr': trow['wr'], 'year': trow.get('year')})
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
                        'n': row['n'], 'wr': row['wr'], 'year': row.get('year')}
                    combo_index[f'{group[j]}+{group[i]}'] = combo_index[f'{group[i]}+{group[j]}']

    # 对手侧的组合，给 BP 复盘做对照
    foe_pairs = []
    for i in range(len(fh)):
        for j in range(i + 1, len(fh)):
            row = kpl_pairs.get((fh[i], fh[j]))
            if row:
                foe_pairs.append({'heroes': [fh[i], fh[j]], 'n': row['n'], 'wr': row['wr']})
    foe_pairs.sort(key=lambda item: -item['n'])

    return {
        'schema': 'bp-match-facts-v1',
        'ladder': {'source': 'ladder', 'bracket': lane_data.get('bracket'),
                   'windowEnd': lane_data.get('windowEnd'),
                   'minN': lane_data.get('minN'), 'minPickRate': lane_data.get('minPickRate'),
                   'lanes': lanes},
        'kpl': {'source': 'kpl', 'sinceYear': combo_data.get('sinceYear'),
                'games': combo_data.get('games'), 'minGames': combo_data.get('minGames'),
                'pairs': pair_hits[:6], 'trios': trio_hits[:6], 'foePairs': foe_pairs[:4],
                'hitPairs': len(pair_hits), 'hitTrios': len(trio_hits),
                'totalPairs': len(heroes) * (len(heroes) - 1) // 2,
                'comboIndex': combo_index},
    }
