"""A1–A7 空间与团战分析。

数据：data/official_replays/camp-*/normalized.json + positions.json
      data/camp_details/<seq>.json（我方阵营、分路）

口径：
- 坐标未做地图定标，所有距离为「相对单位」，页面标 relative=true；R 按数据尺度取固定值。
- 缺失坐标/时间一律跳过并计数，不插值、不补 0。
- 只做描述，不做「失误」或因果判断。
"""
from __future__ import annotations

import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path

R_NEAR = 22.0     # 近身半径（定标前：相对单位）
R_TRIO = 32.0     # 三人集结半径（定标前：相对单位）

# 定标后，距离统一换算成「地图宽度」的比例；这两个值在 load_games 里按标定宽度缩放
_CAL = {'active': False, 'data': None}
WIDTH = 106.0


def _scaled(value):
    return value / (WIDTH or 1.0) if _CAL['active'] else value


def _near():
    return _scaled(R_NEAR)


def _trio_r():
    return _scaled(R_TRIO)
POSITION_LANES = {0: '对抗路', 1: '中路', 2: '发育路', 3: '打野', 4: '游走'}


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def _lane(code):
    try:
        return POSITION_LANES.get(int(code), '')
    except (TypeError, ValueError):
        return ''


def load_games(replays_dir, camp_dir, calibration=None):
    games = []
    for folder in sorted(Path(replays_dir).glob('camp-*')):
        seq = folder.name.split('camp-')[-1]
        normalized = _read(folder / 'normalized.json')
        if not normalized:
            continue
        panel = _read(Path(camp_dir) / f'{seq}.json') or {}
        data = panel.get('data') or {}
        head = data.get('head') or {}
        own_camp = {'1': 'blue', '2': 'red'}.get(str(head.get('acntCamp') or ''))
        if own_camp is None:
            continue

        # 阵营内 objID ↔ playerId 通过 heroId 关联
        hero_to_player = {}
        for player in normalized.get('players') or []:
            hero_to_player[(str(player.get('camp')), player.get('heroId'))] = str(player.get('playerId') or '')
        battles = normalized.get('battles') or {}
        player_map = battles.get('playerMap') or {}
        obj_to_player = {}
        obj_to_camp = {}
        for obj_id, info in player_map.items():
            camp = str(info.get('camp') or '')
            obj_to_camp[obj_id] = camp
            player_id = hero_to_player.get((camp, info.get('heroId')))
            if player_id:
                obj_to_player[obj_id] = player_id

        # 分路：营地面板的 playerId 与回放不是同一套，用「阵营 + 英雄名」对齐
        camp_roles = {'blue': {}, 'red': {}}
        for side_key, side_name in (('blueRoles', 'blue'), ('redRoles', 'red')):
            for role in data.get(side_key) or []:
                records = role.get('battleRecords') or {}
                hero = ((records.get('usedHero') or {}).get('heroName')) or ''
                if hero:
                    camp_roles[side_name][hero] = _lane(records.get('position'))
        lanes = {}
        camp_players = {'1': [], '2': []}
        heroes = {}
        for player in normalized.get('players') or []:
            player_id = str(player.get('playerId') or '')
            camp = str(player.get('camp') or '')
            hero = player.get('hero') or ''
            heroes[player_id] = hero
            if camp in camp_players:
                camp_players[camp].append(player_id)
            side_name = {'1': 'blue', '2': 'red'}.get(camp)
            if side_name and hero and hero in camp_roles[side_name]:
                lanes[player_id] = camp_roles[side_name][hero]

        positions = _read(folder / 'positions.json') or {}
        series = {}
        for player in positions.get('players') or []:
            arr = player.get('posArr') or []
            series[str(player.get('playerId') or '')] = arr

        match = normalized.get('match') or {}
        games.append({
            'seq': seq,
            'calibrated': bool(calibration and calibration.get('calibrated')),
            'ownCamp': own_camp,
            'winner': {'1': 'blue', '2': 'red'}.get(str(match.get('winCamp') or '')),
            'duration': float(match.get('durationSec') or 0),
            'series': _normalize_all(series, calibration),
            'fights': battles.get('fights') or [],
            'deaths': battles.get('deaths') or [],
            'events': (normalized.get('events') or {}).get('key') or [],
            'diff': (normalized.get('economy') or {}).get('diff') or [],
            'objToPlayer': obj_to_player,
            'objToCamp': obj_to_camp,
            'lanes': lanes,
            'campPlayers': camp_players,
            'heroes': heroes,
        })
    return games


def _point(series, player_id, second):
    arr = series.get(player_id) or []
    if not arr or second < 0 or second >= len(arr):
        return None
    point = arr[second]
    if not isinstance(point, (list, tuple)) or len(point) < 2:
        return None
    x, y = point[0], point[1]
    if x == 0 and y == 0:
        return None
    return (float(x), float(y))


def _normalize_all(series, calibration):
    """把逐秒坐标整体映射到 0–1；无定标时原样返回。"""
    if not calibration or not calibration.get('calibrated'):
        return series
    bounds = calibration['bounds']
    width = bounds['xMax'] - bounds['xMin']
    height = bounds['yMax'] - bounds['yMin']
    if width <= 0 or height <= 0:
        return series
    out = {}
    for player_id, arr in series.items():
        converted = []
        for point in arr:
            if not isinstance(point, (list, tuple)) or len(point) < 2 or (point[0] == 0 and point[1] == 0):
                converted.append([0, 0])
                continue
            # 不夹紧：越界点保持越界，夹到边界会把远处的人"拉近"
            u = (float(point[0]) - bounds['xMin']) / width
            v = (float(point[1]) - bounds['yMin']) / height
            converted.append([u, v])
        out[player_id] = converted
    return out


def _distance(a, b):
    return math.dist(a, b) if a and b else None


# ---------------------------------------------------------------- A1 开局路线
def routes(games, *, until=240, step=5, min_points=20, limit=20):
    per_hero = defaultdict(list)
    rows = []
    for game in games:
        for player_id, arr in game['series'].items():
            points = [(t, _point(game['series'], player_id, t)) for t in range(0, min(until, len(arr)), step)]
            points = [(t, p) for t, p in points if p]
            if len(points) < min_points:
                continue
            path = sum(_distance(points[i - 1][1], points[i][1]) for i in range(1, len(points)))
            start, end = points[0][1], points[-1][1]
            lane = game['lanes'].get(player_id) or ''
            hero = game['heroes'].get(player_id) or ''
            row = {
                'game': game['seq'],
                'player': player_id,
                'hero': hero,
                'lane': lane,
                'points': len(points),
                'pathLength': round(path, 1),
                'displacement': round(_distance(start, end) or 0, 1),
                'relative': True,
            }
            per_hero[(hero, lane)].append(row)
            rows.append(row)

    # 同英雄同分路：与组内均值路线比较（用位移与路径长度两个标量近似）
    groups = {}
    for (hero, lane), items in per_hero.items():
        if len(items) < 3:
            continue
        mean_path = statistics.mean(item['pathLength'] for item in items)
        mean_disp = statistics.mean(item['displacement'] for item in items)
        groups[(hero, lane)] = (mean_path, mean_disp)
    for row in rows:
        ref = groups.get((row['hero'], row['lane']))
        if not ref:
            continue
        diff = abs(row['pathLength'] - ref[0]) + abs(row['displacement'] - ref[1])
        row['similarity'] = round(max(0.0, 100 - diff / 2), 1)

    rows.sort(key=lambda item: -item['pathLength'])
    return {'games': len(games), 'rows': rows[:limit], 'total': len(rows),
            'note': '坐标未定标，距离为相对单位；相似度按同英雄同分路的路径长度与位移近似。'}


# ---------------------------------------------------------------- A2 中野辅联动
def trio_link(games):
    rows = []
    for game in games:
        for camp in ('1', '2'):
            trio = [pid for pid in game['campPlayers'].get(camp, [])
                    if game['lanes'].get(pid) in ('中路', '打野', '游走')]
            if len(trio) != 3:
                continue
            seconds = int(min(game['duration'],
                              min((len(game['series'].get(pid) or []) for pid in trio), default=0)))
            assembly = 0
            windows = 0
            in_window = False
            distances = []
            for t in range(seconds):
                points = [_point(game['series'], pid, t) for pid in trio]
                if any(point is None for point in points):
                    in_window = False
                    continue
                spread = max(_distance(a, b) for i, a in enumerate(points) for b in points[i + 1:])
                distances.append(spread)
                close = spread <= _trio_r()
                if close:
                    assembly += 1
                    if not in_window:
                        windows += 1
                    in_window = True
                else:
                    in_window = False
            if not distances:
                continue
            rows.append({
                'game': game['seq'],
                'camp': camp,
                'side': '我方' if (camp == '1') == (game['ownCamp'] == 'blue') else '对方',
                'trio': [game['heroes'].get(pid) or pid for pid in trio],
                'seconds': len(distances),
                'assemblyRate': round(assembly / len(distances) * 100, 1),
                'windows': windows,
                'avgSpread': round(statistics.mean(distances), 1),
                'relative': True,
            })
    rows.sort(key=lambda item: -item['assemblyRate'])
    return {'games': len({row['game'] for row in rows}), 'rows': rows[:20],
            'avgRate': round(statistics.mean(row['assemblyRate'] for row in rows), 1) if rows else None,
            'note': '三人两两距离 ≤ ' + (f"{_trio_r():.3f}（地图宽度比例）" if _CAL['active'] else f'{R_TRIO:.0f}（相对单位）') + ' 记为集结，连续段计一次窗口；两侧各算一组。'}


# ---------------------------------------------------------------- A3 团战到位
def fight_arrival(games):
    rows = []
    for game in games:
        for fight in game['fights']:
            start = fight.get('startSec')
            if not isinstance(start, (int, float)):
                continue
            participants = fight.get('participants') or []
            lags = []
            first = {}
            for person in participants:
                moment = person.get('timeSec')
                if not isinstance(moment, (int, float)):
                    continue
                lag = float(moment) - float(start)
                lags.append(lag)
                camp = str(person.get('camp') or '')
                first[camp] = min(first.get(camp, 1e9), float(moment))
            if not lags:
                continue
            first_side = min(first, key=first.get) if first else ''
            kills = Counter()
            for kill in fight.get('kills') or []:
                kills[str(kill.get('killerCamp') or '')] += 1
            kill_diff = kills.get('1', 0) - kills.get('2', 0)
            opening = [p for p in participants
                       if isinstance(p.get('timeSec'), (int, float)) and p['timeSec'] <= start + 3]
            adv_start = sum(1 for p in opening if str(p.get('camp')) == '1') - \
                sum(1 for p in opening if str(p.get('camp')) == '2')
            rows.append({
                'game': game['seq'],
                'fightId': fight.get('fightId'),
                'start': round(float(start), 1),
                'duration': round(float(fight.get('endSec') or start) - float(start), 1),
                'participants': len(lags),
                'avgLag': round(statistics.mean(lags), 1),
                'lateJoins': sum(1 for lag in lags if lag > 5),
                'firstSide': first_side,
                'advStart': adv_start,
                'killDiff': kill_diff,
            })
    buckets = {}
    for row in rows:
        bucket = buckets.setdefault(row['advStart'], {'adv': row['advStart'], 'n': 0, 'wins': 0})
        bucket['n'] += 1
        bucket['wins'] += 1 if row['killDiff'] > 0 else 0
    summary = [{'advStart': item['adv'], 'n': item['n'],
                'winRate': round(item['wins'] / item['n'] * 100, 1)} for item in sorted(buckets.values(), key=lambda x: -x['adv'])]
    return {'games': len(games), 'fights': len(rows), 'rows': rows[:30], 'buckets': summary,
            'avgLag': round(statistics.mean(row['avgLag'] for row in rows), 1) if rows else None,
            'note': '到位时间 = 参战时刻 − 团战开始；人数差取开局 3 秒内到达的双方人数。'}


# ---------------------------------------------------------------- A4 掉点孤立
def death_isolation(games):
    rows = []
    for game in games:
        by_camp = {'1': list(game['campPlayers'].get('1') or []),
                   '2': list(game['campPlayers'].get('2') or [])}
        for death in game['deaths']:
            moment = death.get('timeSec')
            camp = str(death.get('camp') or '')
            if not isinstance(moment, (int, float)):
                continue
            second = int(moment)
            victim = None
            for obj_id, hero_camp in game['objToCamp'].items():
                if hero_camp == camp and obj_id == str(death.get('objID')):
                    victim = game['objToPlayer'].get(obj_id)
                    break
            # 死亡点必须校验坐标：缺失时 math.dist 会抛 TypeError 让整页 500。
            # 注意 (0,0) 对死亡点不按占位处理（玩家轨迹的 _point 才跳过原点）。
            death_x, death_y = death.get('x'), death.get('y')
            if not isinstance(death_x, (int, float)) or not isinstance(death_y, (int, float)):
                continue
            death_point = (float(death_x), float(death_y))
            if _CAL['active']:
                import map_calibration
                death_point = map_calibration.normalize(death_point, _CAL['data'])
                if death_point is None:
                    continue
            mates = [pid for pid in by_camp.get(camp, []) if pid != victim]
            distances = []
            for pid in mates:
                point = _point(game['series'], pid, second)
                if point is None:
                    continue
                distances.append(_distance(death_point, point))
            if not distances:
                continue
            nearest = min(distances)
            rows.append({
                'game': game['seq'],
                't': round(float(moment), 1),
                'camp': camp,
                'hero': game['heroes'].get(victim) if victim else None,
                'nearest': round(nearest, 1),
                # 定标后距离是 0-1 比例，必须用缩放后的半径；用原始 R_NEAR
                # 会让定标模式下近身人数恒为 0。
                'nearCount': sum(1 for value in distances if value <= _near()),
                'isolated': nearest > _near(),
                'teammatesSeen': len(distances),
            })
    isolated = [row for row in rows if row['isolated']]
    return {'games': len(games), 'deaths': len(rows), 'rows': rows[:30],
            'isolatedRate': round(len(isolated) / len(rows) * 100, 1) if rows else None,
            'isolated': len(isolated),
            'note': '最近队友距离 > ' + (f"{_near():.3f}（地图宽度比例）" if _CAL['active'] else f'{R_NEAR:.0f}（相对单位）') + ' 记为孤立；只看坐标，不判断「失误」。'}


# ---------------------------------------------------------------- A5 团战击杀链
def kill_chains(games, limit=20):
    rows = []
    for game in games:
        for fight in game['fights']:
            kills = [kill for kill in (fight.get('kills') or []) if isinstance(kill.get('timeSec'), (int, float))]
            if len(kills) < 2:
                continue
            kills.sort(key=lambda item: item['timeSec'])
            times = [kill['timeSec'] for kill in kills]
            sequence = [str(kill.get('killerCamp') or '') for kill in kills]
            ambiguous = len(set(times)) != len(times)
            max_run, run = 1, 1
            for index in range(1, len(sequence)):
                run = run + 1 if sequence[index] == sequence[index - 1] else 1
                max_run = max(max_run, run)
            counts = Counter(sequence)
            rows.append({
                'game': game['seq'],
                'fightId': fight.get('fightId'),
                'kills': len(kills),
                'sequence': ''.join(sequence),
                'firstDeath': round(times[0] - float(fight.get('startSec') or 0), 1),
                'maxConsecutive': max_run,
                'pattern': f"{counts.get('1', 0)}-{counts.get('2', 0)}",
                'wipe': counts.get('1', 0) == 5 or counts.get('2', 0) == 5,
                'trade': all(sequence[i] != sequence[i - 1] for i in range(1, len(sequence))),
                'ambiguous': ambiguous,
            })
    rows.sort(key=lambda item: -item['kills'])
    return {'games': len(games), 'fights': len(rows), 'rows': rows[:limit],
            'wipes': sum(1 for row in rows if row['wipe']),
            'note': '同秒击杀不推断先后，标 ambiguous；团灭指一方 5 人全部阵亡。'}


# ---------------------------------------------------------------- A6 团战消耗结构
def fight_consumption(games, limit=15):
    per_hero = defaultdict(lambda: {'hurt': 0, 'taken': 0, 'heal': 0, 'control': 0, 'fights': 0, 'hpLoss': 0.0})
    for game in games:
        for fight in game['fights']:
            details = fight.get('details') or []
            if not details:
                continue
            totals = {
                'hurt': sum(float(item.get('hurt') or 0) for item in details) or 1,
                'taken': sum(float(item.get('taken') or 0) for item in details) or 1,
                'heal': sum(float(item.get('heal') or 0) for item in details) or 1,
                'control': sum(float(item.get('hardCtrl') or 0) + float(item.get('softCtrl') or 0) for item in details) or 1,
            }
            for item in details:
                hero = game['heroes'].get(game['objToPlayer'].get(str(item.get('objID')), '')) or '未知'
                bucket = per_hero[hero]
                bucket['hurt'] += float(item.get('hurt') or 0)
                bucket['taken'] += float(item.get('taken') or 0)
                bucket['heal'] += float(item.get('heal') or 0)
                bucket['control'] += float(item.get('hardCtrl') or 0) + float(item.get('softCtrl') or 0)
                bucket['hpLoss'] += max(0.0, float(item.get('beginHP') or 0) - float(item.get('endHP') or 0))
                bucket['fights'] += 1
                bucket.setdefault('shares', []).append({
                    'damage': float(item.get('hurt') or 0) / totals['hurt'] * 100,
                    'taken': float(item.get('taken') or 0) / totals['taken'] * 100,
                    'heal': float(item.get('heal') or 0) / totals['heal'] * 100,
                    'control': (float(item.get('hardCtrl') or 0) + float(item.get('softCtrl') or 0)) / totals['control'] * 100,
                })
    rows = []
    for hero, bucket in per_hero.items():
        if bucket['fights'] < 3:
            continue
        shares = bucket.get('shares') or []
        rows.append({
            'hero': hero,
            'fights': bucket['fights'],
            'damageShare': round(statistics.mean(item['damage'] for item in shares), 1),
            'takenShare': round(statistics.mean(item['taken'] for item in shares), 1),
            'healShare': round(statistics.mean(item['heal'] for item in shares), 1),
            'controlShare': round(statistics.mean(item['control'] for item in shares), 1),
            'damagePerHp': round(bucket['hurt'] / bucket['hpLoss'], 2) if bucket['hpLoss'] else None,
        })
    rows.sort(key=lambda item: -item['fights'])
    return {'games': len(games), 'heroes': len(rows), 'rows': rows[:limit],
            'note': '占比为该英雄在每场团战内的份额均值；血量缺失时不给「伤害/掉血」。'}


# ---------------------------------------------------------------- A7 资源争夺
def resource_contest(games, limit=20):
    """资源事件发生当秒，双方在锚点 R 内的人数与争夺判定。

    锚点 = 击杀者当秒位置（近似资源点）。
    争夺 = 双方各 ≥2 人在 R 内；单方 ≥2 人记为「单方控制」。
    只取事件当秒，不看 30 秒窗口——「曾经过」会饱和成 100%。
    """
    rows = []
    for game in games:
        for event in game['events']:
            moment = event.get('timeSec')
            killer = event.get('killerId')
            if not isinstance(moment, (int, float)) or killer is None:
                continue
            anchor = _point(game['series'], game['objToPlayer'].get(str(killer), ''), int(moment))
            if anchor is None:
                continue
            near = {'1': set(), '2': set()}
            for obj_id, camp in game['objToCamp'].items():
                point = _point(game['series'], game['objToPlayer'].get(obj_id, ''), int(moment))
                if point and _distance(anchor, point) <= _near():
                    near.setdefault(camp, set()).add(obj_id)
            own, enemy = len(near.get('1', ())), len(near.get('2', ()))
            rows.append({
                'game': game['seq'],
                't': round(float(moment), 1),
                'type': event.get('eventType') or 'unknown',
                'killerCamp': str(event.get('killerCamp') or ''),
                'ownNear': own,
                'enemyNear': enemy,
                'contest': own >= 2 and enemy >= 2,
                'secure': (own >= 2) != (enemy >= 2),
            })
    total = len(rows)
    contested = sum(1 for row in rows if row['contest'])
    secured = sum(1 for row in rows if row['secure'])
    return {
        'games': len(games),
        'events': total,
        'rows': rows[:limit],
        'contestRate': round(contested / total * 100, 1) if total else None,
        'secureRate': round(secured / total * 100, 1) if total else None,
        'medianOwn': statistics.median(row['ownNear'] for row in rows) if rows else None,
        'medianEnemy': statistics.median(row['enemyNear'] for row in rows) if rows else None,
        'note': '锚点用击杀者当秒位置近似资源点；双方各 ≥2 人在 R 内记为争夺，单方 ≥2 记为单方控制。',
    }


def all_analyses(replays_dir, camp_dir, calibration=None):
    global WIDTH
    if calibration and calibration.get('calibrated'):
        _CAL['active'] = True
        _CAL['data'] = calibration
        WIDTH = calibration.get('width') or WIDTH
    else:
        _CAL['active'] = False
    games = load_games(replays_dir, camp_dir, calibration)
    return {
        'games': len(games),
        'calibrated': bool(calibration and calibration.get('calibrated')),
        'calibration': calibration,
        'routes': routes(games),
        'trio': trio_link(games),
        'fights': fight_arrival(games),
        'deaths': death_isolation(games),
        'chains': kill_chains(games),
        'consumption': fight_consumption(games),
        'resources': resource_contest(games),
    }
