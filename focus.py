"""训练闭环：指标注册表、条目校验与逐场评估。

指标口径见 docs/metric_registry.md；评估只使用已确认比赛，
数据不足时对应字段留空，不做估算。
"""
import re

METRICS = {
    'kda': {'label': 'KDA', 'scope': 'player', 'defaultDirection': 'up'},
    'deaths': {'label': '场均死亡', 'scope': 'player', 'defaultDirection': 'down'},
    'dpm': {'label': '分均输出', 'scope': 'player', 'defaultDirection': 'up'},
    'tpm': {'label': '分均承伤', 'scope': 'player', 'defaultDirection': 'down'},
    'participation': {'label': '参团率', 'scope': 'player', 'defaultDirection': 'up'},
    'laneDiff': {'label': '对线经济差', 'scope': 'position', 'defaultDirection': 'up'},
    'win': {'label': '胜负', 'scope': 'team', 'defaultDirection': 'up'},
    'teamGoldDiff': {'label': '终局经济差', 'scope': 'team', 'defaultDirection': 'up'},
}
STATUSES = ('active', 'watching', 'improved', 'archived')


def validate_item(value, roster_ids=()):
    if not isinstance(value, dict):
        raise ValueError('训练重点格式错误')
    title = str(value.get('title') or '').strip()
    if not title or len(title) > 80:
        raise ValueError('训练重点需要 80 字以内的标题')
    metric = value.get('metric')
    if metric not in METRICS:
        raise ValueError('指标必须来自指标注册表')
    spec = METRICS[metric]
    scope_type = value.get('scopeType') or spec['scope']
    if scope_type != spec['scope']:
        raise ValueError(f'{spec["label"]} 的对象范围应为{ {"player": "队员", "position": "分路", "team": "全队"}[spec["scope"]] }')
    scope_id = value.get('scopeId') or ''
    if spec['scope'] == 'player':
        if scope_id not in roster_ids:
            raise ValueError('请选择名单中的队员')
    elif spec['scope'] == 'position':
        if not isinstance(scope_id, str) or not scope_id.strip():
            raise ValueError('请选择分路')
        scope_id = scope_id.strip()
    else:
        scope_id = ''
    direction = value.get('direction') or spec['defaultDirection']
    if direction not in ('up', 'down'):
        raise ValueError('目标方向无效')
    target = value.get('target')
    if target is not None:
        try:
            target = float(target)
        except (TypeError, ValueError):
            raise ValueError('目标值应为数字')
    status = value.get('status') or 'active'
    if status not in STATUSES:
        raise ValueError('状态无效')
    note = str(value.get('note') or '')
    if len(note) > 500:
        raise ValueError('备注过长')
    return {'title': title, 'metric': metric, 'scopeType': scope_type, 'scopeId': scope_id,
            'direction': direction, 'target': target, 'status': status, 'note': note}


def _player_value(match, scope_id, metric):
    own = match.get('side')
    if own not in ('left', 'right'):
        return None
    player = next((p for p in match.get('players', [])
                   if p.get('side') == own and p.get('playerId') == scope_id), None)
    if player is None:
        return None
    if metric == 'deaths':
        value = number(player.get('deaths'))
        return value
    if metric == 'participation':
        return number(player.get('participation'))
    if metric == 'kda':
        kills, deaths, assists = (number(player.get(key)) for key in ('kills', 'deaths', 'assists'))
        if None in (kills, deaths, assists):
            return None
        return (kills + assists) / max(1, deaths)
    minutes = number(match.get('duration'))
    if metric in ('dpm', 'tpm') and minutes:
        key = 'damage' if metric == 'dpm' else 'taken'
        value = number(player.get(key))
        return value / minutes if value is not None else None
    return None


def _lane_diff(match, position):
    own = match.get('side')
    if own not in ('left', 'right'):
        return None
    enemy = 'right' if own == 'left' else 'left'
    own_players = [p for p in match.get('players', []) if p.get('side') == own and p.get('position') == position]
    enemy_players = [p for p in match.get('players', []) if p.get('side') == enemy and p.get('position') == position]
    if len(own_players) != 1 or len(enemy_players) != 1:
        return None
    own_gold, enemy_gold = number(own_players[0].get('gold')), number(enemy_players[0].get('gold'))
    if own_gold is None or enemy_gold is None:
        return None
    return own_gold - enemy_gold


def _team_value(match, metric):
    own = match.get('side')
    if own not in ('left', 'right'):
        return None
    enemy = 'right' if own == 'left' else 'left'
    if metric == 'win':
        winner = match.get('winner')
        if winner not in ('left', 'right'):
            return None
        return 1 if winner == own else 0
    if metric == 'teamGoldDiff':
        sides = {}
        for camp in (own, enemy):
            members = [p for p in match.get('players', []) if p.get('side') == camp]
            values = [number(p.get('gold')) for p in members]
            sides[camp] = sum(values) if len(members) == 5 and all(v is not None for v in values) else None
        if sides[own] is None or sides[enemy] is None:
            return None
        return sides[own] - sides[enemy]
    return None


def evaluate(matches, items):
    """matches：已确认比赛体，按日期升序；items：闭环条目体列表。"""
    ordered = sorted(matches, key=lambda m: m.get('date') or '')
    out = []
    for item in items:
        spec = METRICS.get(item.get('metric'))
        if not spec:
            continue
        points = []
        for match in ordered:
            if item['scopeType'] == 'player':
                value = _player_value(match, item.get('scopeId'), item['metric'])
            elif item['scopeType'] == 'position':
                value = _lane_diff(match, item.get('scopeId'))
            else:
                value = _team_value(match, item['metric'])
            if value is None:
                continue
            points.append({'matchId': match.get('id'), 'date': match.get('date') or '',
                           'opponent': match.get('opponent') or '', 'value': round(value, 2)})
        baseline = None
        if points:
            head = points[:3]
            baseline = round(sum(point['value'] for point in head) / len(head), 2)
        recent = points[-5:]
        target_rate = None
        if item.get('target') is not None and recent:
            if item.get('direction') == 'down':
                hits = sum(1 for point in recent if point['value'] <= item['target'])
            else:
                hits = sum(1 for point in recent if point['value'] >= item['target'])
            target_rate = round(hits / len(recent) * 100, 1)
        out.append({**item, 'points': points, 'baseline': baseline,
                    'recent': round(sum(point['value'] for point in recent) / len(recent), 2) if recent else None,
                    'targetRate': target_rate})
    return out


def number(value):
    if value is None or value == '':
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
