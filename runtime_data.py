"""导入并分析 GameCore 运行时导出的赛训数据。

采集器不在本模块内：工作台只消费一份稳定的 JSONL 契约，数据可以来自共享
内存、帧回调或人工导出。这样回放文件始终只读，采集方式可以替换。
"""
import json
import math

SCHEMA = 'kpl-runtime-v1'
MAX_BYTES = 8 * 1024 * 1024
MAX_LINES = 200_000
MAX_PLAYERS = 10
MAX_EVENTS = 50_000
MAX_TIMELINE_POINTS = 120
CAMP_NAMES = {'blue', 'red', 'unknown'}
EVENT_TYPES = {
    'kill', 'death', 'assist', 'tower', 'dragon', 'tyrant', 'overlord',
    'teamfight_start', 'teamfight_end', 'skill_use', 'skill_hit', 'skill_miss',
    'recall', 'revive', 'objective',
}
META_KEYS = {'schema', 'gameVersion', 'matchId', 'source', 'exportedAt', 'note'}
PLAYER_RANGES = {
    'hp': (0, 1_000_000), 'maxHp': (0, 1_000_000), 'mana': (0, 1_000_000),
    'level': (0, 100), 'gold': (0, 10_000_000), 'exp': (0, 10_000_000),
    'kills': (0, 1000), 'deaths': (0, 1000), 'assists': (0, 1000),
    'damageDealt': (0, 10_000_000), 'damageTaken': (0, 10_000_000),
    'healing': (0, 10_000_000), 'towerDamage': (0, 10_000_000),
    'visionScore': (0, 100_000),
}


class RuntimeDataError(ValueError):
    """运行时数据不符合契约。"""


def _integer(value, name, low=0, high=None, default=None, required=False):
    if value is None:
        if required:
            raise RuntimeDataError(f'{name} 缺失')
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeDataError(f'{name} 必须是整数')
    if isinstance(value, float):
        if not value.is_integer():
            raise RuntimeDataError(f'{name} 必须是整数')
        value = int(value)
    if value < low or (high is not None and value > high):
        raise RuntimeDataError(f'{name} 超出范围')
    return value


def _number(value, name, low=None, high=None, default=None):
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeDataError(f'{name} 必须是数字')
    if not math.isfinite(value):
        raise RuntimeDataError(f'{name} 不是有限数字')
    if low is not None and value < low:
        raise RuntimeDataError(f'{name} 超出范围')
    if high is not None and value > high:
        raise RuntimeDataError(f'{name} 超出范围')
    return float(value)


def _text(value, name, limit=80, required=True):
    if value is None:
        if required:
            raise RuntimeDataError(f'{name} 缺失')
        return None
    if not isinstance(value, str) or not value.strip():
        raise RuntimeDataError(f'{name} 必须是非空字符串')
    value = value.strip()
    if len(value) > limit:
        raise RuntimeDataError(f'{name} 过长')
    if any(ord(ch) < 32 for ch in value):
        raise RuntimeDataError(f'{name} 含控制字符')
    return value


def _meta_text(value, name):
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = str(value)
    return _text(value, name, limit=200, required=False)


def _camp(value, default='unknown'):
    if value is None:
        return default
    if not isinstance(value, str) or value.lower() not in CAMP_NAMES:
        raise RuntimeDataError('camp 只能是 blue、red 或 unknown')
    return value.lower()


def _player(value, where):
    if not isinstance(value, dict):
        raise RuntimeDataError(f'{where} 队员记录必须是对象')
    player = {
        'playerId': _text(value.get('playerId'), f'{where} playerId'),
        'heroId': _integer(value.get('heroId'), f'{where} heroId', 1, 9999, required=True),
        'camp': _camp(value.get('camp')),
        'slot': _integer(value.get('slot'), f'{where} slot', 0, 4),
        'x': _number(value.get('x'), f'{where} x', -1_000_000, 1_000_000),
        'y': _number(value.get('y'), f'{where} y', -1_000_000, 1_000_000),
    }
    if value.get('alive') is not None:
        if not isinstance(value['alive'], bool):
            raise RuntimeDataError(f'{where} alive 必须是布尔值')
        player['alive'] = value['alive']
    for key, (low, high) in PLAYER_RANGES.items():
        if key in ('x', 'y'):
            continue
        if value.get(key) is not None:
            player[key] = _integer(value[key], f'{where} {key}', low, high)
    return player


def _event(value, frame, time, seq):
    event = {
        'event': _text(value.get('event'), 'event', limit=40),
        'frame': frame,
        'time': time,
        'seq': seq,
        'playerId': _text(value.get('playerId'), 'playerId', required=False),
        'targetId': _text(value.get('targetId'), 'targetId', required=False),
        'camp': _camp(value.get('camp')),
        'skillId': _integer(value.get('skillId'), 'skillId', 1, 99999),
        'skillSlot': _integer(value.get('skillSlot'), 'skillSlot', 0, 20),
        'x': _number(value.get('x'), 'x'),
        'y': _number(value.get('y'), 'y'),
    }
    if event['event'] not in EVENT_TYPES:
        raise RuntimeDataError(f"未知事件类型：{event['event']}")
    if value.get('success') is not None:
        if not isinstance(value['success'], bool):
            raise RuntimeDataError('success 必须是布尔值')
        event['success'] = value['success']
    return event


def _merge_time(existing, incoming, frame):
    if incoming is None:
        return existing
    incoming = float(incoming)
    if existing is None:
        return incoming
    if abs(existing - incoming) > 0.001:
        raise RuntimeDataError(f'第 {frame} 帧的 time 不一致')
    return existing


def parse_jsonl(data):
    """解析 JSONL，返回 ``(meta, frames, events)``。

    支持四种行：``meta``、``frame``（一帧多名队员）、``player``（一行一名
    队员）与 ``event``。未知字段忽略，已知字段严格校验。
    """
    if not isinstance(data, (bytes, bytearray)):
        raise RuntimeDataError('运行时数据必须是字节流')
    if len(data) > MAX_BYTES:
        raise RuntimeDataError('运行时数据请小于 8 MB')
    try:
        text = bytes(data).decode('utf-8-sig')
    except UnicodeDecodeError as error:
        raise RuntimeDataError('运行时数据不是 UTF-8') from error

    meta = None
    frame_map = {}
    events = []
    non_blank = 0
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        non_blank += 1
        if non_blank > MAX_LINES:
            raise RuntimeDataError('运行时数据行数过多')
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise RuntimeDataError(f'第 {number} 行不是合法 JSON') from error
        if not isinstance(value, dict):
            raise RuntimeDataError(f'第 {number} 行必须是 JSON 对象')
        kind = value.get('type')
        if kind is None:
            if 'players' in value:
                kind = 'frame'
            elif 'event' in value:
                kind = 'event'
            elif 'playerId' in value:
                kind = 'player'
            else:
                raise RuntimeDataError(f'第 {number} 行缺少 type')
        if kind == 'meta':
            if meta is not None:
                raise RuntimeDataError('meta 只能出现一次')
            meta = {key: value[key] for key in META_KEYS if key in value}
            if meta.get('schema') is not None and not str(meta['schema']).startswith('kpl-runtime-'):
                raise RuntimeDataError('不支持的运行时数据 schema')
            for key in META_KEYS - {'schema'}:
                if key in meta:
                    meta[key] = _meta_text(meta[key], key)
            continue

        frame = _integer(value.get('frame'), f'第 {number} 行 frame', 0, 10_000_000, required=True)
        time = _number(value.get('time'), f'第 {number} 行 time', 0, 1_000_000)

        if kind == 'frame':
            players = value.get('players')
            if not isinstance(players, list) or not 1 <= len(players) <= MAX_PLAYERS:
                raise RuntimeDataError(f'第 {number} 行 players 必须是 1–{MAX_PLAYERS} 人')
            bucket = frame_map.setdefault(frame, {'frame': frame, 'time': None, 'players': {}})
            bucket['time'] = _merge_time(bucket['time'], time, frame)
            for index, item in enumerate(players):
                player = _player(item, f'第 {number} 行第 {index + 1} 人')
                if player['playerId'] in bucket['players']:
                    raise RuntimeDataError(f'第 {number} 行 playerId 重复')
                bucket['players'][player['playerId']] = player
        elif kind == 'player':
            player = _player(value, f'第 {number} 行')
            bucket = frame_map.setdefault(frame, {'frame': frame, 'time': None, 'players': {}})
            bucket['time'] = _merge_time(bucket['time'], time, frame)
            if player['playerId'] in bucket['players']:
                raise RuntimeDataError(f'第 {number} 行同一帧 playerId 重复')
            bucket['players'][player['playerId']] = player
        elif kind == 'event':
            events.append(_event(value, frame, time, len(events)))
            if len(events) > MAX_EVENTS:
                raise RuntimeDataError('事件数量过多')
        else:
            raise RuntimeDataError(f'第 {number} 行 type 无效')

    if not frame_map and not events:
        raise RuntimeDataError('没有可分析的帧或事件')
    frames = []
    for frame in sorted(frame_map):
        bucket = frame_map[frame]
        players = sorted(bucket['players'].values(), key=lambda p: (p['slot'] is None, p['slot'], p['playerId']))
        frames.append({'frame': frame, 'time': bucket['time'], 'players': players})
    events.sort(key=lambda e: (e['frame'], e['time'] if e['time'] is not None else -1, e['seq']))
    return meta or {}, frames, events


def _duration(frames, events):
    times = [f['time'] for f in frames if f['time'] is not None]
    times += [e['time'] for e in events if e['time'] is not None]
    if times:
        return max(times), 'time'
    last = max([f['frame'] for f in frames] + [e['frame'] for e in events] + [0])
    return last / 30.0, 'frame/30'


def _team_metric(players, key, count=5):
    values = [p.get(key) for p in players]
    if len(players) != count or any(value is None for value in values):
        return None
    return sum(values)


def analyze(meta, frames, events):
    """从帧和事件计算赛训摘要；缺字段时保持 None，不补零。"""
    duration, time_basis = _duration(frames, events)
    warnings = []
    if duration <= 0:
        warnings.append('时长为 0，分均指标按 1 秒估算')
    duration = duration if duration > 0 else 1.0
    minutes = duration / 60.0
    if time_basis == 'frame/30':
        warnings.append('没有 time 字段，按 30fps 估算时长')

    latest = {}
    samples = {}
    for frame in frames:
        for player in frame['players']:
            player_id = player['playerId']
            previous = latest.get(player_id)
            if previous:
                if previous['camp'] != 'unknown' and player['camp'] == 'unknown':
                    player['camp'] = previous['camp']
                if previous['camp'] not in ('unknown', player['camp']):
                    warnings.append(f'{player_id} 的阵营发生变化，按最新帧计算')
                if previous['heroId'] != player['heroId']:
                    warnings.append(f'{player_id} 的英雄发生变化，按最新帧计算')
            latest[player_id] = player
            samples[player_id] = samples.get(player_id, 0) + 1

    teams = {}
    for name in ('blue', 'red'):
        members = [p for p in latest.values() if p['camp'] == name]
        complete = len(members) == 5
        totals = {}
        for key in ('kills', 'deaths', 'assists', 'gold', 'exp', 'damageDealt', 'damageTaken', 'towerDamage', 'visionScore'):
            totals[key] = _team_metric(members, key)
        partial = {}
        known = {}
        for key in totals:
            values = [p[key] for p in members if p.get(key) is not None]
            known[key] = len(values)
            partial[key] = sum(values) if values else None
        teams[name] = {
            'players': len(members),
            'complete': complete,
            'totals': totals,
            'perMinute': {key: (value / minutes if value is not None else None) for key, value in totals.items()},
            'partial': partial,
            'knownPlayers': known,
        }
        if members and not complete:
            warnings.append(f'{name} 方仅 {len(members)} 名队员，团队合计未计算')

    blue_kills = teams['blue']['totals']['kills']
    red_kills = teams['red']['totals']['kills']
    if blue_kills is None and teams['blue']['players']:
        warnings.append('蓝方击杀数不完整，参团率未计算')
    if red_kills is None and teams['red']['players']:
        warnings.append('红方击杀数不完整，参团率未计算')

    players = []
    for player_id, player in latest.items():
        values = {key: player.get(key) for key in PLAYER_RANGES}
        team = teams.get(player['camp'], {})
        team_kills = team.get('totals', {}).get('kills')
        kills, deaths, assists = values['kills'], values['deaths'], values['assists']
        metrics = {
            'kda': ((kills or 0) + (assists or 0)) / max(1, deaths or 0)
            if kills is not None and assists is not None and deaths is not None else None,
            'kdaPerfect': bool(kills is not None and assists is not None and deaths == 0),
            'gpm': (values['gold'] / minutes) if values['gold'] is not None else None,
            'xpm': (values['exp'] / minutes) if values['exp'] is not None else None,
            'damagePerMin': (values['damageDealt'] / minutes) if values['damageDealt'] is not None else None,
            'takenPerMin': (values['damageTaken'] / minutes) if values['damageTaken'] is not None else None,
            'participation': (((kills or 0) + (assists or 0)) / team_kills * 100.0) if team_kills else None,
            'goldShare': (values['gold'] / team['totals']['gold'] * 100.0) if values['gold'] is not None and team.get('totals', {}).get('gold') else None,
            'damageShare': (values['damageDealt'] / team['totals']['damageDealt'] * 100.0) if values['damageDealt'] is not None and team.get('totals', {}).get('damageDealt') else None,
        }
        players.append({
            'playerId': player_id,
            'camp': player['camp'],
            'heroId': player['heroId'],
            'slot': player['slot'],
            'samples': samples.get(player_id, 0),
            'latest': {key: value for key, value in player.items() if key not in ('playerId', 'camp', 'heroId', 'slot')},
            'metrics': metrics,
        })
    players.sort(key=lambda p: (p['camp'] != 'blue', p['slot'] is None, p['slot'], p['playerId']))

    timeline = []
    for frame in frames:
        point = {'frame': frame['frame'], 'time': frame['time']}
        usable = False
        for name in ('blue', 'red'):
            members = [p for p in frame['players'] if p['camp'] == name]
            gold = _team_metric(members, 'gold')
            kills = _team_metric(members, 'kills')
            point[f'{name}Gold'] = gold
            point[f'{name}Kills'] = kills
            usable = usable or gold is not None or kills is not None
        if usable:
            timeline.append(point)
    if len(timeline) > MAX_TIMELINE_POINTS:
        step = (len(timeline) - 1) / (MAX_TIMELINE_POINTS - 1)
        timeline = [timeline[round(index * step)] for index in range(MAX_TIMELINE_POINTS)]

    counts = {}
    by_camp = {'blue': {}, 'red': {}, 'unknown': {}}
    for event in events:
        counts[event['event']] = counts.get(event['event'], 0) + 1
        camp_counts = by_camp[event['camp']]
        camp_counts[event['event']] = camp_counts.get(event['event'], 0) + 1
    uses, hits = counts.get('skill_use', 0), counts.get('skill_hit', 0)
    event_summary = {
        'total': len(events),
        'counts': counts,
        'byCamp': by_camp,
        'skillUses': uses,
        'skillHits': hits,
        'skillHitRate': (hits / uses * 100.0) if uses else None,
        'firstFrame': events[0]['frame'] if events else None,
        'lastFrame': events[-1]['frame'] if events else None,
    }

    if not frames:
        warnings.append('只有事件，没有帧数据，队员指标未计算')
    for player in players:
        missing = [key for key in ('gold', 'damageDealt', 'damageTaken') if player['latest'].get(key) is None]
        if missing:
            warnings.append(f"{player['playerId']} 缺少 {', '.join(missing)}")

    coverage = {
        'frames': len(frames),
        'players': len(players),
        'events': len(events),
        'durationSec': duration,
        'timeBasis': time_basis,
        'teams': {name: teams[name]['players'] for name in teams},
        'metricPlayers': {
            key: sum(1 for p in players if p['latest'].get(key) is not None)
            for key in ('gold', 'exp', 'kills', 'damageDealt', 'damageTaken')
        },
    }
    return {
        'schema': meta.get('schema', SCHEMA),
        'meta': meta,
        'warnings': list(dict.fromkeys(warnings)),
        'coverage': coverage,
        'players': players,
        'teams': teams,
        'events': event_summary,
        'timeline': timeline,
    }


def analyze_jsonl(data):
    """解析并分析一份 JSONL，返回可直接写入回放报告的摘要。"""
    meta, frames, events = parse_jsonl(data)
    return analyze(meta, frames, events)
