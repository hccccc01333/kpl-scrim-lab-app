"""Read-only derived analysis for a merged post-game screenshot group.

The screenshots already contain per-player values and shares.  This module only
sums/averages complete fields and marks partial coverage; it never fills a
missing value or turns a partial team into a full team total.
"""
SCHEMA = 'kpl-postgame-analysis-v1'

TEAM_TOTAL_FIELDS = (
    'kills', 'deaths', 'assists', 'gold', 'damageDealt', 'damageTaken',
    'healing', 'towerDamage', 'control', 'cs', 'jungleGold',
)
TEAM_AVERAGE_FIELDS = ('participation', 'rating', 'damageConversion', 'takenPerDeath')
COMPARE_FIELDS = ('kills', 'gold', 'damageDealt', 'damageTaken', 'healing', 'towerDamage', 'control')
RANK_FIELDS = ('damageDealt', 'gold', 'participation', 'kills', 'healing', 'towerDamage', 'control')
LABELS = {
    'kills': '击杀', 'deaths': '死亡', 'assists': '助攻', 'gold': '总经济',
    'damageDealt': '输出伤害', 'damageTaken': '承受伤害', 'healing': '治疗量',
    'towerDamage': '对塔伤害', 'control': '控制效果', 'cs': '补刀数',
    'jungleGold': '野怪经济', 'participation': '参团率', 'rating': '评分',
    'damageConversion': '伤害转化比', 'takenPerDeath': '每死承伤',
}


def _field(player, key):
    value = (player.get('fields') or {}).get(key)
    if not value or value.get('value') is None:
        return None
    return value.get('value')


def _team(players, side, score):
    team_players = [player for player in players if player.get('side') == side]
    totals, samples, complete, averages = {}, {}, {}, {}
    for field in TEAM_TOTAL_FIELDS:
        values = [value for value in (_field(player, field) for player in team_players) if value is not None]
        samples[field] = len(values)
        totals[field] = sum(values) if values else None
        complete[field] = len(values) == 5
    for field in TEAM_AVERAGE_FIELDS:
        values = [value for value in (_field(player, field) for player in team_players) if value is not None]
        samples[field] = len(values)
        averages[field] = round(sum(values) / len(values), 2) if values else None
    kda_ratio = None
    if complete['kills'] and complete['deaths'] and complete['assists']:
        kda_ratio = round((totals['kills'] + totals['assists']) / max(totals['deaths'], 1), 2)
    return {
        'side': side,
        'players': len(team_players),
        'totals': totals,
        'averages': averages,
        'samples': samples,
        'complete': complete,
        'kdaRatio': kda_ratio,
        'score': score,
        'killsMatchScore': (totals['kills'] == score) if complete['kills'] and score is not None else None,
    }


def analyze_group(group):
    players = [dict(player) for player in (group.get('players') or [])]
    match = group.get('match') or {}
    score = match.get('score') or {}
    teams = {side: _team(players, side, score.get(side)) for side in ('left', 'right')}
    warnings = []

    if score.get('left') is None or score.get('right') is None:
        warnings.append('该组没有完整比分，无法做击杀合计校验。')
    else:
        for side in ('left', 'right'):
            if teams[side]['killsMatchScore'] is False:
                warnings.append(f'{"左" if side == "left" else "右"}方五人击杀合计与比分不符。')

    for side in ('left', 'right'):
        label = '左' if side == 'left' else '右'
        for field in COMPARE_FIELDS:
            if teams[side]['samples'][field] and not teams[side]['complete'][field]:
                warnings.append(f'{label}方 {LABELS[field]} 仅 {teams[side]["samples"][field]}/5 人有值，不计算团队合计。')

    for player in players:
        kills, deaths, assists = (_field(player, key) for key in ('kills', 'deaths', 'assists'))
        player['analysis'] = {
            'kda': f'{kills}/{deaths}/{assists}' if all(value is not None for value in (kills, deaths, assists)) else None,
            'kdaRatio': round((kills + assists) / max(deaths, 1), 2)
            if all(value is not None for value in (kills, deaths, assists)) else None,
        }
        if player.get('shares'):
            player['analysis']['shares'] = dict(player['shares'])

    for field in RANK_FIELDS:
        ranked = sorted(
            (player for player in players if _field(player, field) is not None),
            key=lambda player: _field(player, field), reverse=True,
        )
        for index, player in enumerate(ranked, 1):
            player['analysis'].setdefault('ranks', {})[field] = index

    comparisons = {}
    for field in COMPARE_FIELDS:
        left, right = teams['left'], teams['right']
        complete = left['complete'][field] and right['complete'][field]
        comparisons[field] = {
            'left': left['totals'][field],
            'right': right['totals'][field],
            'difference': (left['totals'][field] - right['totals'][field]) if complete else None,
            'complete': complete,
        }

    highlights = []
    for field, label in (('damageDealt', '最高输出'), ('gold', '最高经济'),
                         ('participation', '最高参团率'), ('healing', '最高治疗'),
                         ('towerDamage', '最高对塔伤害')):
        ranked = sorted(
            (player for player in players if _field(player, field) is not None),
            key=lambda player: _field(player, field), reverse=True,
        )
        if ranked:
            best = ranked[0]
            highlights.append({
                'field': field, 'label': label,
                'player': {'side': best.get('side'), 'slot': best.get('slot'),
                           'nickname': (best.get('nickname') or {}).get('value'),
                           'hero': (best.get('hero') or {}).get('value')},
                'value': _field(best, field),
            })

    coverage = {field: sum(1 for player in players if _field(player, field) is not None)
                for field in TEAM_TOTAL_FIELDS + TEAM_AVERAGE_FIELDS}
    page_types = [page.get('pageType') for page in (group.get('pages') or [])]
    if not any(comparisons[field]['complete'] for field in COMPARE_FIELDS):
        warnings.append('没有左右双方各 5 人齐全的可比字段；只能看单页候选。')

    return {
        'schema': SCHEMA,
        'match': match,
        'teams': teams,
        'comparisons': comparisons,
        'highlights': highlights,
        'coverage': coverage,
        'players': players,
        'pages': page_types,
        'warnings': _dedupe(warnings),
    }


def _dedupe(values):
    seen, result = set(), []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
