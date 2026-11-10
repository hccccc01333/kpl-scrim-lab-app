"""Single-match panorama: join a bundle with official positions, events and hero builds.

The official replay event stream (``dragontower``) covers two things only:
resource/monster kills (``dtType=1``) and structure destroys (``dtType=2``).
Hero kills are not in that stream; they live in ``normalized.battles`` —
team-fight ledgers (``fights[].kills[]``) and death coordinates
(``deaths[]``) — and are exposed separately as ``kills`` / ``deaths``.
Final score, KDA and damage still come from the confirmed bundle.  Positions
are per-second grid coordinates from the personal replay; they are used for
area/distance analysis, not as a frame-accurate trajectory.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from fastapi import APIRouter, HTTPException

import official_economy

SCHEMA = 'kpl-match-panorama-v1'
MATCH_SCHEMA = 'kpl-match-data-v1'
MAP_MIN, MAP_MAX = -57.0, 57.0
HEAT_BINS = 12
POSITION_STEP = 2
STILL_RUN = 12
CLOSE_RADIUS = 22.0
PHASE_LABELS = ('对线期', '转线期', '决胜期')


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None


def _num(value):
    if value is None or value == '' or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _int(value):
    number = _num(value)
    return int(round(number)) if number is not None else None


def _camp(value):
    text = str(value or '').strip().lower()
    return {'1': 'blue', '2': 'red', 'blue': 'blue', 'red': 'red',
            'left': 'blue', 'right': 'red'}.get(text)


def _clock(seconds):
    if seconds is None:
        return '—'
    total = int(round(seconds))
    return f'{total // 60:02d}:{total % 60:02d}'


def _name_key(text):
    return ''.join(str(text or '').replace('\ufe0e', '').replace('\ufe0f', '').split())


def _point(value):
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    x, y = _num(value[0]), _num(value[1])
    if x is None or y is None:
        return None
    return (x, y)


def _advance(x, y, camp):
    """Signed progress toward the enemy base in [-1, 1]; blue advances +x/+y."""
    sign = 1 if camp == 'blue' else -1
    return (x + y) * sign / (2 * abs(MAP_MIN))


def _zone(x, y):
    diagonal = x + y
    if abs(diagonal) <= 10:
        return 'river'
    return 'red_half' if diagonal > 0 else 'blue_half'


def _phase_ranges(duration):
    duration = max(1, int(duration or 0))
    if duration >= 600:
        cuts = (0, 300, 600, duration)
    elif duration >= 420:
        cuts = (0, 240, 480, duration)
    else:
        cuts = (0, duration // 3, duration * 2 // 3, duration)
    return [{'key': ('early', 'mid', 'late')[index], 'label': PHASE_LABELS[index],
             'from': cuts[index], 'to': cuts[index + 1]}
            for index in range(3) if cuts[index + 1] > cuts[index]]


def _heat(points):
    grid = [[0] * HEAT_BINS for _ in range(HEAT_BINS)]
    span = MAP_MAX - MAP_MIN
    for x, y in points:
        column = min(HEAT_BINS - 1, max(0, int((x - MAP_MIN) / span * HEAT_BINS)))
        row = min(HEAT_BINS - 1, max(0, int((y - MAP_MIN) / span * HEAT_BINS)))
        grid[row][column] += 1
    return grid


def _active_mask(points):
    """Drop long frozen runs (dead bodies / paused samples) from movement stats."""
    mask, run = [], 0
    for index, point in enumerate(points):
        run = run + 1 if index and point == points[index - 1] else 0
        mask.append(run < STILL_RUN)
    return mask


def _distance(left, right):
    return math.hypot(left[0] - right[0], left[1] - right[1])


def _mean(values):
    return sum(values) / len(values) if values else None


def _load_catalog(root):
    value = _read_json(Path(root) / 'resources' / 'catalog.json') or {}
    icons = {}
    for entry in value.get('entries') or []:
        if entry.get('kind') == 'hero' and entry.get('name') and entry.get('icon'):
            icons[entry['name']] = entry['icon']
    return icons


def _find_bundle(matches_dir, key):
    directory = Path(matches_dir)
    if not directory.is_dir():
        return None, None
    for path in sorted(directory.glob('*.json')):
        value = _read_json(path)
        if not isinstance(value, dict) or value.get('schema') != MATCH_SCHEMA:
            continue
        match = value.get('match') or {}
        if str(match.get('key') or '') == str(key) or path.stem == str(key):
            return path, value
    return None, None


def _official_payload(official_dir, bundle):
    """Resolve the official replay linked by the bundle, or a unique structural match."""
    directory = Path(official_dir)
    match = bundle.get('match') or {}
    linked = (match.get('officialReplay') or {}).get('id')
    folders = [directory / linked] if linked and (directory / linked / 'normalized.json').is_file() else []
    if not folders and directory.is_dir():
        duration = _num(match.get('duration'))
        heroes = {(player.get('camp'), player.get('hero'))
                  for player in bundle.get('players') or [] if player.get('hero')}
        scored = []
        for folder in directory.iterdir():
            if not folder.is_dir() or not (folder / 'normalized.json').is_file():
                continue
            normalized = _read_json(folder / 'normalized.json') or {}
            info = normalized.get('match') or {}
            other_duration = _num(info.get('durationSec'))
            other_heroes = {(('blue' if str(player.get('camp')) == '1' else 'red'),
                             player.get('hero'))
                            for player in normalized.get('players') or [] if player.get('hero')}
            overlap = len(heroes & other_heroes)
            if duration and other_duration and abs(duration - other_duration) > 2:
                continue
            if overlap >= 8:
                scored.append((overlap, folder))
        scored.sort(key=lambda item: item[0], reverse=True)
        if len(scored) == 1 or (scored and scored[0][0] > scored[1][0]):
            folders = [scored[0][1]]
    if not folders:
        return None
    folder = folders[0]
    meta = _read_json(folder / 'meta.json') or {}
    normalized = _read_json(folder / 'normalized.json')
    if not isinstance(normalized, dict):
        return None
    files = meta.get('files') or {}
    raw = _read_json(folder / (files.get('raw') or 'raw.json'))
    positions = _read_json(folder / (files.get('positions') or 'positions.json'))
    return {'folder': folder, 'meta': meta, 'normalized': normalized,
            'raw': raw, 'positions': positions}


def _official_buffs(official):
    """红蓝 BUFF 击杀记录（extendEventArr/killbuff）：归属方 vs 击杀方 → 反野。

    killbuff 事件带 dtID（10=蓝 buff / 11=红 buff）、dtCamp（BUFF 归属地）与
    killerCamp（击杀方）。击杀方 != 归属地即视为反野；只用于有官方回放的局。
    """
    raw = (official or {}).get('raw') or {}
    result = []
    for item in (raw.get('data') or {}).get('extendEventArr') or []:
        for event in item.get('eventList') or []:
            if event.get('eventType') != 'killbuff':
                continue
            data = event.get('dtData') or {}
            seconds = _num(event.get('eventTime')) or _num(data.get('killTime'))
            if seconds is None or seconds <= 0:
                continue
            buff_id = str(data.get('dtID') or '')
            result.append({
                't': round(seconds / 1000.0, 1),
                'name': {'10': '蓝 buff', '11': '红 buff'}.get(buff_id, f'野怪{buff_id}'),
                'owner': _camp(data.get('dtCamp')),
                'killer': _camp(data.get('killerCamp')),
            })
    result.sort(key=lambda row: row['t'])
    return result


def _official_narrations(official):
    """营地复盘的中文叙述（reportData.adviceList，如「恭喜赢得团战…」）。"""
    raw = (official or {}).get('raw') or {}
    items = ((raw.get('data') or {}).get('reportData') or {}).get('adviceList') or []
    result = []
    for item in items:
        seconds = _num(item.get('time'))
        text = str(item.get('msg') or '').strip()
        if seconds is None or not text:
            continue
        result.append({'t': round(seconds / 1000.0, 1), 'text': text[:120]})
    result.sort(key=lambda row: row['t'])
    return result


def _official_entity_aliases(official, players):
    """把击杀事件里的 inBattleObjID 映射到 bundle 的十人 key。

    keyEventArr.kills 的 killerId 是「战斗对象 ID」，而 normalized 的 playerId
    是另一套编号；playBaseInfoArr 同时带 inBattleObjID 与 (acntCamp, heroID)，
    用它经「阵营 + 英雄」桥接到我们的 player，与营地 H5 的做法一致。
    """
    raw = (official or {}).get('raw') or {}
    normalized = (official or {}).get('normalized') or {}
    hero_by = {}
    for item in normalized.get('players') or []:
        camp = _camp(item.get('camp'))
        if camp and item.get('heroId') is not None:
            hero_by[(camp, str(item.get('heroId')))] = item.get('hero')
    aliases = {}
    for info in ((raw.get('data') or {}).get('playBaseInfoArr') or []):
        camp = _camp(info.get('acntCamp'))
        hero = hero_by.get((camp, str(info.get('heroID'))))
        if not camp or not hero:
            continue
        match = next((player for player in players
                      if player.get('camp') == camp and player.get('hero') == hero), None)
        if match:
            aliases[str(info.get('inBattleObjID'))] = match
    return aliases


def _official_events(official):
    """Prefer raw events because they keep viewX/viewY; fall back to normalized."""
    raw = (official or {}).get('raw') or {}
    events, seen = [], set()
    for item in (raw.get('data') or {}).get('keyEventArr') or []:
        data = item.get('dtData') or {}
        if not data or item.get('eventType') == 'battle':
            continue
        seconds = _num(data.get('killTime'))
        if seconds is not None:
            seconds = seconds / 1000.0
        if seconds is None or seconds <= 0:
            continue
        signature = (round(seconds, 1), str(data.get('dtType')), str(data.get('dtID')),
                     str(data.get('killerId')))
        if signature in seen:
            continue
        seen.add(signature)
        events.append({
            't': seconds, 'dtType': str(data.get('dtType') or ''),
            'dtId': str(data.get('dtID') or ''), 'dtCamp': _camp(data.get('dtCamp')),
            'killerCamp': _camp(data.get('killerCamp')),
            'killerId': str(data.get('killerId') or ''),
            'x': _num(data.get('viewX')), 'y': _num(data.get('viewY')),
            'kills': data.get('kills') or [],
        })
    if events:
        return events
    for item in (official or {}).get('normalized', {}).get('events', {}).get('key', []):
        seconds = _num(item.get('timeSec'))
        if seconds is None or seconds <= 0 or item.get('eventType') == 'battle':
            continue
        events.append({
            't': seconds, 'dtType': str(item.get('dtType') or ''),
            'dtId': str(item.get('dtId') or ''), 'dtCamp': _camp(item.get('dtCamp')),
            'killerCamp': _camp(item.get('killerCamp')),
            'killerId': str(item.get('killerId') or ''),
            'x': None, 'y': None, 'kills': item.get('kills') or [],
        })
    return events


def _find_builds(builds_dir, players):
    directory = Path(builds_dir)
    if not directory.is_dir():
        return {}
    heroes = {(player.get('camp'), player.get('hero'))
              for player in players if player.get('hero')}
    names = {_name_key(player.get('nickname')) for player in players}
    best, score = {}, 0
    for path in directory.glob('*/builds.json'):
        value = _read_json(path)
        if not isinstance(value, dict):
            continue
        entries = value.get('players') or {}
        if not isinstance(entries, dict):
            continue
        overlap = 0
        for name, entry in entries.items():
            summary = entry.get('summary') or {}
            if (_camp(summary.get('camp')), summary.get('hero')) in heroes:
                overlap += 1
            elif _name_key(name) in names:
                overlap += 1
        if overlap > score:
            best, score = entries, overlap
    return best if score >= 6 else {}


def _map_builds(entries, players):
    by_pair = {(player.get('camp'), player.get('hero')): player for player in players}
    by_name = {_name_key(player.get('nickname')): player for player in players}
    result = {}
    for name, entry in (entries or {}).items():
        summary = entry.get('summary') or {}
        player = by_pair.get((_camp(summary.get('camp')), summary.get('hero')))
        player = player or by_name.get(_name_key(name))
        if not player:
            continue
        items = []
        for item in entry.get('items') or []:
            seconds = _num(item.get('t'))
            if seconds is None:
                continue
            items.append({'t': int(round(seconds)), 'name': item.get('name') or '',
                          'id': str(item.get('id') or '')})
        items.sort(key=lambda value: value['t'])
        result[player['key']] = {'items': items,
                                 'hero': player.get('hero') or summary.get('hero'),
                                 'camp': player.get('camp')}
    return result


def _player_positions(official, players):
    """player key -> [(second, x, y), ...] using the camp+hero join."""
    value = (official or {}).get('positions') or {}
    by_pair = {(player.get('camp'), player.get('hero')): player for player in players}
    normalized = (official or {}).get('normalized') or {}
    official_players = {str(item.get('playerId')): item for item in normalized.get('players') or []}
    result = {}
    for entry in value.get('players') or []:
        player_id = str(entry.get('playerId') or '')
        official_player = official_players.get(player_id) or {}
        camp = _camp(official_player.get('camp'))
        player = by_pair.get((camp, official_player.get('hero')))
        if not player:
            continue
        points = []
        for second, raw_point in enumerate(entry.get('posArr') or []):
            point = _point(raw_point)
            if point:
                points.append((second, point[0], point[1]))
        if points:
            result[player['key']] = points
    return result


def _position_analysis(position_map, players, phases):
    by_key = {player['key']: player for player in players}
    analysis, team = {}, {'blue': [], 'red': []}
    for key, points in position_map.items():
        player = by_key[key]
        camp = player['camp']
        sequence = [(x, y) for _, x, y in points]
        active = _active_mask(sequence)
        total_distance = sum(_distance(sequence[index], sequence[index - 1])
                             for index in range(1, len(sequence)))
        phase_values = []
        for phase in phases:
            subset = [(x, y, active[index]) for index, (second, x, y) in enumerate(points)
                      if phase['from'] <= second < phase['to']]
            live = [(x, y) for x, y, is_active in subset if is_active]
            if not live:
                live = [(x, y) for x, y, _ in subset]
            distances = [_distance(live[index], live[index - 1])
                         for index in range(1, len(live))]
            advances = [_advance(x, y, camp) for x, y in live]
            zones = [_zone(x, y) for x, y in live]
            own = sum(1 for zone in zones if zone == ('blue_half' if camp == 'blue' else 'red_half'))
            enemy = sum(1 for zone in zones if zone == ('red_half' if camp == 'blue' else 'blue_half'))
            phase_values.append({
                'key': phase['key'], 'n': len(live),
                'avgX': _mean([x for x, _ in live]), 'avgY': _mean([y for _, y in live]),
                'distance': sum(distances),
                'advance': _mean(advances), 'advanceMax': max(advances) if advances else None,
                'ownShare': own / len(zones) if zones else None,
                'enemyShare': enemy / len(zones) if zones else None,
                'riverShare': sum(1 for zone in zones if zone == 'river') / len(zones) if zones else None,
                'heat': _heat(live),
            })
        analysis[key] = {
            'camp': camp, 'hero': player.get('hero'), 'name': player.get('nickname'),
            'distance': total_distance, 'samples': len(sequence),
            'phases': phase_values,
        }
    # Team-level grouping uses each second's active players.
    for camp in ('blue', 'red'):
        keys = [player['key'] for player in players if player['camp'] == camp]
        series = [position_map.get(key) or [] for key in keys]
        length = max((len(item) for item in series), default=0)
        close_rate, enemy_share, spread_values = [], [], []
        for second in range(length):
            points = []
            for item in series:
                if second < len(item):
                    _, x, y = item[second]
                    points.append((x, y))
            if len(points) < 2:
                continue
            centroid = (_mean([x for x, _ in points]), _mean([y for _, y in points]))
            close = sum(1 for point in points if _distance(point, centroid) <= CLOSE_RADIUS)
            close_rate.append(close >= 4)
            enemy_share.append(sum(1 for x, y in points
                                   if _zone(x, y) == ('red_half' if camp == 'blue' else 'blue_half'))
                               / len(points))
            spread_values.append(_distance(centroid, (0, 0)))
        team[camp] = {
            'closeRate': sum(close_rate) / len(close_rate) if close_rate else None,
            'enemyHalfRate': _mean(enemy_share),
            'centroidDistance': _mean(spread_values),
        }
    return analysis, team


def _gold_points(bundle):
    points, seen = [], set()
    for item in (bundle.get('team') or {}).get('timeline') or []:
        seconds = _num(item.get('gameTime'))
        blue, red = _num(item.get('blueGold')), _num(item.get('redGold'))
        if seconds is None or blue is None or red is None:
            continue
        key = int(round(seconds))
        if key in seen:
            continue
        seen.add(key)
        points.append({'t': key, 'blue': blue, 'red': red, 'diff': blue - red})
    points.sort(key=lambda value: value['t'])
    return points


def _landmark(points, seconds):
    candidates = [point for point in points if point['t'] <= seconds + 15]
    return candidates[-1] if candidates and seconds - candidates[-1]['t'] <= 45 else None


# dtType/dtID → 资源类型（营地 H5 前端 getDTInnerEventType 的映射，
# 2026-11-10 从 team-analyzev2 前端包中核实）。
RESOURCE_NAMES = {'8': '暗影主宰', '9': '暴君', '17': '暗影暴君'}
CORE_IDS = {'10', '20'}


def event_display_name(kind, dt_id):
    if kind == 'resource':
        return RESOURCE_NAMES.get(str(dt_id), '野怪')
    return '水晶' if str(dt_id) in CORE_IDS else '防御塔'


def _normalize_events(raw_events, players, extra_entities=None):
    by_entity = {str(player.get('entityId', player.get('replayEntityId'))): player
                 for player in players
                 if player.get('entityId', player.get('replayEntityId')) is not None}
    if extra_entities:
        by_entity.update(extra_entities)
    result = []
    for event in raw_events:
        kind = 'resource' if event['dtType'] == '1' else 'structure'
        killer = by_entity.get(event['killerId'])
        participants, seen = [], set()
        for item in event.get('kills') or []:
            player = by_entity.get(str(item.get('killerId')))
            if player and player['key'] not in seen:
                seen.add(player['key'])
                hurt = item.get('hurtTotal')
                participants.append({'key': player['key'], 'name': player.get('nickname'),
                                     'hero': player.get('hero'), 'camp': player.get('camp'),
                                     'hurtTotal': int(hurt) if str(hurt or '').isdigit() else None})
        x, y = event.get('x'), event.get('y')
        located = x is not None and y is not None and (abs(x) > 0.01 or abs(y) > 0.01)
        result.append({
            't': int(round(event['t'])), 'kind': kind, 'id': event['dtId'],
            'name': event_display_name(kind, event['dtId']),
            'killerCamp': event['killerCamp'],
            'killer': killer.get('nickname') if killer else None,
            'killerHero': killer.get('hero') if killer else None,
            'ownerCamp': event['dtCamp'] if kind == 'structure' else None,
            'x': x if located else None, 'y': y if located else None,
            'zone': _zone(x, y) if located else None,
            'participants': participants,
        })
    result.sort(key=lambda value: value['t'])
    return result


def _battle_ledger(official):
    """英雄击杀、死亡坐标与团战账本。

    ``normalized.battles.fights[]`` 给出团战起止、参战人数与逐人明细，
    ``fights[].kills[]`` 逐次给出击杀时间与击杀/被击杀对象，``battles.deaths[]``
    给出死亡坐标。对象 ID 的类型在不同版本里不一致（int/str），所以查表两种都试。
    """
    empty = {'kills': [], 'deaths': [], 'fights': []}
    battles = ((official or {}).get('normalized') or {}).get('battles') or {}
    if not isinstance(battles, dict):
        return empty
    player_map = battles.get('playerMap') or {}

    def lookup(obj_id):
        return player_map.get(obj_id) or player_map.get(str(obj_id)) or {}

    def info_of(obj_id):
        info = lookup(obj_id)
        return {'hero': info.get('hero') or '', 'camp': _camp(info.get('camp'))}

    kills, deaths, fights = [], [], []
    for fight in battles.get('fights') or []:
        start = _num(fight.get('startSec'))
        tally = {'blue': 0, 'red': 0}
        details = []
        for row in fight.get('details') or []:
            who = info_of(row.get('objID'))
            details.append({
                'hero': who['hero'], 'camp': _camp(row.get('camp')) or who['camp'],
                'hurt': _num(row.get('hurt')), 'taken': _num(row.get('taken')),
                'hardCtrl': _num(row.get('hardCtrl')), 'softCtrl': _num(row.get('softCtrl')),
                'ultimates': _num(row.get('ultimates')),
            })
        for kill in fight.get('kills') or []:
            seconds = _num(kill.get('timeSec'))
            killer = info_of(kill.get('killer'))
            victim = info_of(kill.get('victim'))
            killer_camp = _camp(kill.get('killerCamp')) or killer['camp']
            victim_camp = _camp(kill.get('victimCamp')) or victim['camp']
            if killer_camp in tally:
                tally[killer_camp] += 1
            if seconds is None:
                continue
            kills.append({
                't': seconds, 'fight': str(fight.get('fightId') or ''),
                'killer': killer['hero'], 'killerCamp': killer_camp,
                'victim': victim['hero'], 'victimCamp': victim_camp,
            })
        if start is None:
            continue
        fights.append({
            'id': str(fight.get('fightId') or ''), 't': start,
            'end': _num(fight.get('endSec')),
            'camp1': _int(fight.get('camp1')), 'camp2': _int(fight.get('camp2')),
            'first': _camp(fight.get('firstKillerCamp')),
            'blue': tally['blue'], 'red': tally['red'],
            'details': details,
        })
    for death in battles.get('deaths') or []:
        seconds = _num(death.get('timeSec'))
        if seconds is None:
            continue
        who = info_of(death.get('objID'))
        deaths.append({
            't': seconds, 'hero': who['hero'], 'camp': _camp(death.get('camp')) or who['camp'],
            'x': _num(death.get('x')), 'y': _num(death.get('y')),
        })
    kills.sort(key=lambda value: value['t'])
    deaths.sort(key=lambda value: value['t'])
    fights.sort(key=lambda value: value['t'])
    return {'kills': kills, 'deaths': deaths, 'fights': fights}


def _windows(events, gap=25, minimum=2):
    clusters, current = [], []
    for event in events:
        if current and event['t'] - current[-1]['t'] > gap:
            if len(current) >= minimum:
                clusters.append(current)
            current = []
        current.append(event)
    if len(current) >= minimum:
        clusters.append(current)
    result = []
    for cluster in clusters:
        result.append({
            'start': cluster[0]['t'], 'end': cluster[-1]['t'],
            'resources': sum(1 for event in cluster if event['kind'] == 'resource'),
            'structures': sum(1 for event in cluster if event['kind'] == 'structure'),
            'events': len(cluster),
        })
    return result


def _team_phase(position_map, players, start, end):
    result = {}
    for camp in ('blue', 'red'):
        series = []
        for player in players:
            if player['camp'] != camp:
                continue
            points = position_map.get(player['key']) or []
            sequence = [(x, y) for _, x, y in points]
            series.append((points, _active_mask(sequence)))
        close, enemy = [], []
        for second in range(start, end):
            live = []
            for points, mask in series:
                if second < len(points) and mask[second]:
                    _, x, y = points[second]
                    live.append((x, y))
            if len(live) < 2:
                continue
            centroid = (_mean([x for x, _ in live]), _mean([y for _, y in live]))
            close.append(sum(1 for point in live
                             if _distance(point, centroid) <= CLOSE_RADIUS) >= 4)
            enemy_zone = 'red_half' if camp == 'blue' else 'blue_half'
            enemy.append(sum(1 for x, y in live if _zone(x, y) == enemy_zone) / len(live))
        result[camp] = {'closeRate': sum(close) / len(close) if close else None,
                        'enemyHalfRate': _mean(enemy)}
    return result


def _phase_stats(phases, gold, events, position_analysis, position_map, players):
    result = []
    for phase in phases:
        start, end = phase['from'], phase['to']
        before = [point for point in gold if point['t'] <= start + 15]
        inside = [point for point in gold if start - 15 <= point['t'] <= end + 15]
        first = before[-1]['diff'] if before else (0 if start == 0 else None)
        last = inside[-1]['diff'] if inside else None
        events_inside = [event for event in events if start <= event['t'] < end]
        result.append({
            'key': phase['key'], 'label': phase['label'],
            'from': start, 'to': end,
            'goldStart': first, 'goldEnd': last,
            'goldChange': (last - first) if first is not None and last is not None else None,
            'resources': {'blue': sum(1 for event in events_inside
                                      if event['kind'] == 'resource' and event['killerCamp'] == 'blue'),
                          'red': sum(1 for event in events_inside
                                     if event['kind'] == 'resource' and event['killerCamp'] == 'red')},
            'structures': {'blue': sum(1 for event in events_inside
                                       if event['kind'] == 'structure' and event['killerCamp'] == 'blue'),
                           'red': sum(1 for event in events_inside
                                      if event['kind'] == 'structure' and event['killerCamp'] == 'red')},
            'team': _team_phase(position_map, players, start, end),
            'players': [{'key': key, **{field: value for field, value in
                                         next((item for item in analysis['phases']
                                               if item['key'] == phase['key']), {}).items()
                                         if field != 'heat'}}
                        for key, analysis in position_analysis.items()],
        })
    return result


def _insights(match, gold, events, phases, position_analysis, team, builds, players):
    insights = []
    if gold:
        high = max(gold, key=lambda point: point['diff'])
        low = min(gold, key=lambda point: point['diff'])
        final = gold[-1]
        if high['diff'] > 0:
            insights.append({'tone': 'blue', 'title': '蓝方经济峰值',
                             'value': f"+{round(high['diff']):,}",
                             'detail': f"{_clock(high['t'])} 达到最大领先；终局经济差 "
                                       f"{final['diff']:+,.0f}。", 't': high['t']})
        if low['diff'] < 0:
            insights.append({'tone': 'red', 'title': '红方经济峰值',
                             'value': f"+{round(-low['diff']):,}",
                             'detail': f"{_clock(low['t'])} 达到最大领先。", 't': low['t']})
    resources = [event for event in events if event['kind'] == 'resource']
    structures = [event for event in events if event['kind'] == 'structure']
    if resources:
        blue = sum(1 for event in resources if event['killerCamp'] == 'blue')
        red = len(resources) - blue
        insights.append({'tone': 'neutral', 'title': '资源事件',
                         'value': f'{len(resources)} 次',
                         'detail': f'蓝方 {blue} / 红方 {red}；首次 {_clock(resources[0]["t"])}，'
                                   f'末次 {_clock(resources[-1]["t"])}。',
                         't': resources[0]['t']})
    if structures:
        blue = sum(1 for event in structures if event['killerCamp'] == 'blue')
        red = len(structures) - blue
        insights.append({'tone': 'neutral', 'title': '建筑摧毁',
                         'value': f'{len(structures)} 座',
                         'detail': f'蓝方摧毁 {blue} / 红方摧毁 {red}；首座 '
                                   f'{_clock(structures[0]["t"])}，末座 {_clock(structures[-1]["t"])}。',
                         't': structures[0]['t']})
    if position_analysis:
        ranked = sorted(position_analysis.values(), key=lambda value: value['distance'], reverse=True)
        if ranked:
            top = ranked[0]
            insights.append({'tone': 'neutral', 'title': '移动最多',
                             'value': f"{round(top['distance']):,}",
                             'detail': f"{top['name']}（{top['hero']}）在逐秒坐标中的累计位移最高；"
                                       f"不含静止停留。", 't': None})
    if team.get('blue') and team.get('red'):
        blue_rate, red_rate = team['blue'].get('closeRate'), team['red'].get('closeRate')
        if blue_rate is not None and red_rate is not None:
            insights.append({'tone': 'neutral', 'title': '四人以上同屏',
                             'value': f'{blue_rate * 100:.0f}% / {red_rate * 100:.0f}%',
                             'detail': '蓝方 / 红方：至少四名队员距队伍中心 22 格以内的秒数占比；'
                                       '反映抱团与集结，不是战术评价。', 't': None})
    if builds:
        counts = [(next((player.get('nickname') for player in players
                         if player['key'] == key), key), len(value['items']))
                  for key, value in builds.items()]
        total = sum(count for _, count in counts)
        if counts:
            name, count = max(counts, key=lambda item: item[1])
            insights.append({'tone': 'neutral', 'title': '出装事件',
                             'value': f'{total} 次',
                             'detail': f'{name} 的购买记录最多（{count} 次）；'
                                       f'装备价格为文件未提供，只统计购买时间与顺序。', 't': None})
    if phases:
        first, last = phases[0], phases[-1]
        if first.get('goldEnd') is not None:
            insights.append({'tone': 'neutral', 'title': '阶段经济',
                             'value': f"{first['goldEnd']:+,.0f}",
                             'detail': f"{first['label']}结束时的蓝 − 红经济差；"
                                       f"决胜期结束时 "
                                       f"{last.get('goldEnd'):+,.0f}。" if last.get('goldEnd') is not None
                                       else f"{first['label']}结束时的蓝 − 红经济差。",
                             't': first['to']})
    return insights[:7]


def build_panorama(matches_dir, official_dir, builds_dir, key, root=None):
    bundle_path, bundle = _find_bundle(matches_dir, key)
    if not bundle:
        return None
    match = bundle.get('match') or {}
    players = []
    for player in bundle.get('players') or []:
        final = player.get('final') or {}
        players.append({
            'key': player.get('key'), 'camp': _camp(player.get('camp')),
            'side': player.get('side') or player.get('camp'), 'slot': player.get('slot'),
            'nickname': player.get('nickname'), 'hero': player.get('hero'),
            'entityId': player.get('replayEntityId'),
            'kills': final.get('kills'), 'deaths': final.get('deaths'),
            'assists': final.get('assists'), 'gold': final.get('totalGold'),
            'damage': final.get('damage'), 'taken': final.get('taken'),
            'participation': final.get('participation'), 'rating': final.get('rating'),
            'partial': bool(final.get('partial', not final.get('complete', False))),
            'official': {}, 'mvp': None, 'builds': [],
        })
    by_entity = {str(player['entityId']): player for player in players
                 if player.get('entityId') is not None}
    result = (match.get('result') or {})
    for item in [result.get('winMvp')] + list(result.get('loseMvp') or []):
        target = by_entity.get(str((item or {}).get('entityId')))
        if target:
            target['mvp'] = ('win' if item is result.get('winMvp') else 'lose')
    official = _official_payload(official_dir, bundle)
    if official:
        normalized_players = {str(item.get('playerId')): item
                              for item in (official.get('normalized') or {}).get('players') or []}
        positions = _player_positions(official, players)
        # Attach official ratings by camp+hero join.
        by_pair = {(player['camp'], player['hero']): player for player in players}
        for player_id, item in normalized_players.items():
            camp = _camp(item.get('camp'))
            target = by_pair.get((camp, item.get('hero')))
            if not target:
                continue
            ratings = item.get('ratings') or {}
            target['official'] = {
                'playerId': player_id,
                'grow': _int(ratings.get('grow')), 'battle': _int(ratings.get('battle')),
                'survive': _int(ratings.get('survive')),
                'hurtHero': _int(ratings.get('hurtHero')), 'kda': _int(ratings.get('kda')),
                'defeatRatio': _int(item.get('defeatAcntRatio')),
            }
    else:
        positions = {}
    aliases = _official_entity_aliases(official, players) if official else {}
    events = _normalize_events(_official_events(official), players, aliases) if official else []
    ledger = _battle_ledger(official) if official else {'kills': [], 'deaths': [], 'fights': []}
    kills, deaths, fights = ledger['kills'], ledger['deaths'], ledger['fights']
    gold = _gold_points(bundle)
    if not gold and official:
        # 先入库、后挂官方回放的旧 bundle 没有录制时间轴；直接吃官方
        # 约 30 秒一个点的团队经济，脉搏/阶段/里程碑才不会是空的。
        gold = official_economy.diff_points((official or {}).get('normalized'))
    duration = _int(match.get('duration')) or (gold[-1]['t'] if gold else 0)
    phases = _phase_ranges(duration)
    analysis, team = _position_analysis(positions, players, phases)
    builds_raw = _find_builds(builds_dir, players)
    builds = _map_builds(builds_raw, players)
    for player in players:
        player['builds'] = (builds.get(player['key']) or {}).get('items') or []
        player['official'] = player['official'] or None
    phase_stats = _phase_stats(phases, gold, events, analysis, positions, players)
    icons = _load_catalog(root or Path(matches_dir).resolve().parent)
    for player in players:
        player['icon'] = icons.get(player.get('hero') or '')
    insights = _insights(match, gold, events, phase_stats, analysis, team, builds, players)
    return {
        'schema': SCHEMA,
        'match': {
            'key': match.get('key'), 'title': match.get('title'),
            'date': (match.get('date') or {}).get('text'), 'mode': match.get('mode'),
            'duration': duration, 'scores': match.get('scores') or {},
            'ownCamp': _camp(match.get('ownCamp')), 'winnerCamp': _camp(match.get('winnerCamp')),
            'result': result, 'videoCoverage': match.get('videoCoverage'),
        },
        'players': players,
        'teams': {camp: {'label': '蓝方' if camp == 'blue' else '红方',
                         'players': [player['key'] for player in players if player['camp'] == camp]}
                  for camp in ('blue', 'red')},
        'gold': {'points': gold, 'interval': 30 if gold else None,
                 'landmarks': {str(seconds): (_landmark(gold, seconds) or {}).get('diff')
                               for seconds in (300, 600, 900)}},
        'events': events,
        'buffEvents': _official_buffs(official) if official else [],
        'narrations': _official_narrations(official) if official else [],
        'kills': kills,
        'deaths': deaths,
        'fights': fights,
        'windows': _windows(events),
        'phases': phase_stats,
        'positions': {
            'bounds': [MAP_MIN, MAP_MAX], 'step': POSITION_STEP,
            'players': {key: {
                'points': [[second, round(x, 1), round(y, 1)]
                           for second, x, y in value[::POSITION_STEP]],
                'camp': analysis[key]['camp'], 'hero': analysis[key]['hero'],
                'name': analysis[key]['name'], 'distance': round(analysis[key]['distance'], 1),
                'phases': [{**phase, 'heat': phase['heat']}
                           for phase in analysis[key]['phases']],
            } for key, value in positions.items()},
            'team': team,
        },
        'insights': insights,
        'coverage': {
            'goldPoints': len(gold), 'events': len(events),
            'resources': sum(1 for event in events if event['kind'] == 'resource'),
            'structures': sum(1 for event in events if event['kind'] == 'structure'),
            'positions': {'seconds': max((len(value) for value in positions.values()), default=0),
                          'players': len(positions), 'perSecond': bool(positions)},
            'builds': {'players': len(builds),
                       'items': sum(len(value['items']) for value in builds.values())},
            'heroKills': bool(kills),
        },
        'notes': [
            '官方事件覆盖野区/河道资源与建筑摧毁，不含英雄击杀；比分、KDA 与输出承伤来自终局数据。',
            '英雄击杀与死亡坐标取自团战账本（fights[].kills / deaths），按时间排序，不与资源事件混用。',
            '位置为个人回放逐秒网格坐标（-57 至 57），用于区域、距离和集结分析，不是逐帧轨迹。',
            '连续 12 秒以上完全静止的坐标样本（如死亡停留）不计入移动与热区。',
            '出装时间来自 .abc 帧命令，误差约 ±3 秒；文件未提供装备价格。',
            f'阶段按本局 {duration} 秒自动切分：' + ' / '.join(
                f"{phase['label']} {_clock(phase['from'])}–{_clock(phase['to'])}"
                for phase in phases) + '。',
        ],
    }


class PanoramaRepository:
    def __init__(self, matches_dir, official_dir, builds_dir, root=None):
        self.matches_dir = Path(matches_dir)
        self.official_dir = Path(official_dir)
        self.builds_dir = Path(builds_dir)
        self.root = Path(root) if root else None

    def get(self, key):
        return build_panorama(self.matches_dir, self.official_dir, self.builds_dir, key, self.root)


def create_review_router(matches_dir, official_dir, builds_dir, root=None):
    repository = PanoramaRepository(matches_dir, official_dir, builds_dir, root)
    router = APIRouter(prefix='/api/review', tags=['review'])

    @router.get('/{key:path}')
    def panorama(key: str):
        value = repository.get(key)
        if value is None:
            raise HTTPException(404, '该比赛没有可用的单局全景数据包')
        return value

    return router
