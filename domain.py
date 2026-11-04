"""Validation and summaries; unknown measurements stay unknown."""
import copy
import math
import re
from collections import defaultdict
from datetime import date

POSITIONS = ['对抗路', '打野', '中路', '发育路', '游走']
METRICS = ['kills', 'deaths', 'assists', 'gold', 'damage', 'taken', 'participation', 'rating']


def number(value):
    if value is None or value == '':
        return None
    if isinstance(value, bool):
        raise ValueError('数值不能为布尔值')
    text = str(value).strip().lower().replace(',', '')
    if not re.fullmatch(r'\d+(?:\.\d+)?(?:k|万|%)?', text):
        raise ValueError(f'无效数值：{value}')
    multiplier = 1000 if text.endswith('k') else 10000 if text.endswith('万') else 1
    n = float(text.rstrip('k万%')) * multiplier
    if not math.isfinite(n) or n < 0 or n > 100000000:
        raise ValueError('数值超出范围')
    return n


EVENT_TYPES = ('tyrant', 'dominator', 'storm', 'tower', 'firstTower')


def validate_bp(value):
    """BP 既兼容旧自由文本，也接受结构化字典；结构不入库前不清洗旧数据。"""
    if isinstance(value, str):
        if len(value) > 12000:
            raise ValueError('BP 文本过长')
        return value
    if not isinstance(value, dict):
        raise ValueError('BP 格式错误')
    notes = value.get('notes', '')
    if not isinstance(notes, str) or len(notes) > 12000:
        raise ValueError('BP 备注过长')
    if value.get('firstPick') not in ('left', 'right', ''):
        raise ValueError('一手方标记无效')
    bp = {'bans': {}, 'picks': {}, 'firstPick': value.get('firstPick') or '', 'notes': notes}
    for side in ('left', 'right'):
        section = value.get('bans', {}).get(side, []) if isinstance(value.get('bans'), dict) else []
        if not isinstance(section, list) or len(section) > 4:
            raise ValueError('每侧禁用最多 4 个')
        picks = value.get('picks', {}).get(side, []) if isinstance(value.get('picks'), dict) else []
        if not isinstance(picks, list) or len(picks) > 5:
            raise ValueError('每侧选用最多 5 个')
        for group, limit in ((section, 4), (picks, 5)):
            for hero in group:
                if not isinstance(hero, str) or len(hero.strip()) > 50:
                    raise ValueError('BP 英雄名称格式错误')
        bp['bans'][side] = [hero.strip() for hero in section]
        bp['picks'][side] = [hero.strip() for hero in picks]
    return bp


def validate_events(value):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 80:
        raise ValueError('资源事件数量无效')
    events = []
    for event in value:
        if not isinstance(event, dict) or event.get('type') not in EVENT_TYPES:
            raise ValueError('资源事件类型无效')
        if event.get('side') not in ('left', 'right'):
            raise ValueError('资源事件阵营无效')
        t = event.get('t')
        if t is not None and (not isinstance(t, str) or not re.fullmatch(r'\d{1,3}(:\d{2})?', t or '')):
            raise ValueError('事件时间格式应为 分 或 分:秒')
        events.append({'type': event['type'], 'side': event['side'], 't': t or None})
    return events


def validate_match(raw, roster):
    m = copy.deepcopy(raw)
    if not isinstance(m, dict):
        raise ValueError('比赛格式错误')
    if m.get('id') and (not isinstance(m['id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', m['id'])):
        raise ValueError('比赛 ID 格式错误')
    status = m.get('status', 'draft')
    if status not in ('draft', 'confirmed', 'archived'):
        raise ValueError('比赛状态无效')
    m['status'] = status
    if m.get('side') not in ('left', 'right', ''):
        raise ValueError('请确认本队在截图中的阵营')
    if m.get('winner') not in ('left', 'right', ''):
        raise ValueError('请确认胜方')
    if m.get('date'):
        date.fromisoformat(m['date'])
    for key in ('opponent', 'version', 'session', 'notes'):
        if not isinstance(m.get(key, ''), str) or len(m.get(key, '')) > 12000:
            raise ValueError('文字字段过长或格式错误')
    m['bp'] = validate_bp(m.get('bp', ''))
    m['events'] = validate_events(m.get('events'))
    focus_ids = m.get('focusIds', [])
    if not isinstance(focus_ids, list) or len(focus_ids) > 20 or \
            any(not isinstance(item, str) or len(item) > 80 for item in focus_ids):
        raise ValueError('训练重点关联格式错误')
    m['focusIds'] = [item for item in focus_ids if item]
    duration = number(m.get('duration'))
    if duration is not None and duration <= 0:
        raise ValueError('时长应大于零')
    scores = m.get('scores', {})
    if not isinstance(scores, dict):
        raise ValueError('比分格式错误')
    for side in ('left', 'right'):
        n = number(scores.get(side))
        if n is not None and (n != int(n) or n > 500):
            raise ValueError('比分应为 0 至 500 的整数')
    players = m.get('players')
    if not isinstance(players, list) or len(players) != 10:
        raise ValueError('需要保留双方十个选手栏位')
    slots = set()
    for p in players:
        if not isinstance(p, dict):
            raise ValueError('选手记录格式错误')
        slot = (p.get('side'), p.get('slot'))
        if slot[0] not in ('left', 'right') or slot[1] not in range(5) or slot in slots:
            raise ValueError('选手栏位重复或无效')
        slots.add(slot)
        if not isinstance(p.get('hero', ''), str) or len(p.get('hero', '')) > 50:
            raise ValueError('英雄名称格式错误')
        if p.get('position', '') not in POSITIONS + ['']:
            raise ValueError('分路无效')
        for metric in METRICS:
            n = number(p.get(metric))
            if metric in ('kills', 'deaths', 'assists') and n is not None and (n != int(n) or n > 500):
                raise ValueError('KDA 必须为 0 至 500 的整数')
            if metric == 'participation' and n is not None and n > 100:
                raise ValueError('参团率应为 0 至 100%')
        if len(str(p.get('equipment', ''))) > 500:
            raise ValueError('装备记录过长')
    if status != 'confirmed':
        return m
    if not all(m.get(k) for k in ('side', 'winner', 'date', 'opponent')):
        raise ValueError('正式入库前请填写日期、对手、本队阵营和胜方')
    own = [p for p in players if p['side'] == m['side']]
    valid_ids = {p['id'] for p in roster}
    ids = [p.get('playerId') for p in own]
    if any(i not in valid_ids for i in ids) or len(set(ids)) != 5:
        raise ValueError('请为本队五人分别关联不同的名单队员')
    if any(not p.get('hero', '').strip() for p in own):
        raise ValueError('请补齐本队五人的英雄')
    if len({p['hero'].strip() for p in own}) != 5:
        raise ValueError('本队英雄不能重复，请检查识别结果')
    if not m.get('reviewed'):
        raise ValueError('请勾选已核对截图、阵营与选手数据')
    for side in ('left', 'right'):
        team = [p for p in players if p['side'] == side]
        kills = [number(p.get('kills')) for p in team]
        score = number(scores.get(side))
        if score is not None and all(k is not None for k in kills) and sum(kills) != score:
            raise ValueError(f'{"左" if side == "left" else "右"}侧五人击杀合计与比分不符')
    return m


def summarize(matches, roster, player_filter=None):
    from analytics import aggregate_measures
    active = [m for m in matches if m['status'] == 'confirmed']
    groups = {k: defaultdict(list) for k in ('heroes', 'players', 'opponents', 'lineups')}
    wins = 0
    for m in active:
        won = m['side'] == m['winner']
        wins += won
        own = [p for p in m['players'] if p['side'] == m['side']]
        for p in own:
            if player_filter and not player_filter(p):
                continue
            row = (m, p, won)
            groups['heroes'][p['hero'].strip()].append(row)
            groups['players'][p['playerId']].append(row)
        groups['opponents'][m['opponent'].strip()].append((m, None, won))
        groups['lineups'][' / '.join(sorted(p['hero'].strip() for p in own))].append((m, None, won))
    names = {p['id']: p['name'] for p in roster}
    output = {'games': len(active), 'wins': wins, 'drafts': sum(m['status'] == 'draft' for m in matches)}
    for kind, buckets in groups.items():
        rows = []
        for key, items in buckets.items():
            row = {'key': key, 'name': names.get(key, key) if kind == 'players' else key,
                   'games': len(items), 'wins': sum(w for _, _, w in items),
                   'matchIds': [m['id'] for m, _, _ in items]}
            for metric in METRICS:
                values = [number(p.get(metric)) for _, p, _ in items if p]
                values = [v for v in values if v is not None]
                row[metric] = sum(values) / len(values) if values else None
                row[metric + 'Samples'] = len(values)
            row.update(aggregate_measures(items))
            rows.append(row)
        output[kind] = sorted(rows, key=lambda r: (-r['games'], r['name']))
    return output
