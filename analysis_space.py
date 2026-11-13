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
                # 0 击杀的团战没有胜负：只计入 n（覆盖率），不拉低胜率。
                'decided': bool(fight.get('kills')),
            })
    buckets = {}
    for row in rows:
        bucket = buckets.setdefault(row['advStart'], {'adv': row['advStart'], 'n': 0,
                                                      'wins': 0, 'decided': 0})
        bucket['n'] += 1
        if row['decided']:
            bucket['decided'] += 1
            bucket['wins'] += 1 if row['killDiff'] > 0 else 0
    summary = [{'advStart': item['adv'], 'n': item['n'], 'decided': item['decided'],
                'winRate': (round(item['wins'] / item['decided'] * 100, 1)
                            if item['decided'] else None)}
               for item in sorted(buckets.values(), key=lambda x: -x['adv'])]
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



# ===========================================================================
# Merged from merged module (fight_execution)
# ===========================================================================

"""团战执行与人员协同（决策台 P0-3）。

所有数据只从 ``facts`` 的统一事实表读取；指标一律**我方视角**：

- 到位延迟 ``arrivalLagSec`` = 参战时刻 − 团战开始时刻（保留 1 位小数）。
- ``arrivalDiff`` = 我方最早到达 − 敌方最早到达，**负 = 我方先到**。
- ``advStart`` = 团战开始 3 秒内双方到达人数差（我方 − 敌方）。
- ``killDiff`` = 我方击杀 − 敌方击杀；没有击杀记录（0 击杀）时 ``killDiff/won`` 为 None，
  不把「没打起来」判成输。
- ``lateJoins`` = 我方在开始 5 秒之后才到的人数。

边界：只做描述（到位/人数/交换），不判断指挥失误，不宣称因果。
缺失参战时间的人跳过并计入 ``missingParticipants``，不用 0 假填。
"""

import math

import match_facts

EARLY_WINDOW_SEC = 3.0
LATE_JOIN_SEC = 5.0
ENOUGH_BUCKET = 8
DEFAULT_LIMIT = 120
MAX_LIMIT = 500
BUCKET_MIN = -5
BUCKET_MAX = 5
MEMBER_STAT_KEYS = ('kills', 'deaths', 'assists', 'hurt', 'taken', 'heal',
                    'hardCtrl', 'softCtrl', 'beginHP', 'endHP', 'ultimates')


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def _num(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _int(value):
    number = _num(value)
    return int(number) if number is not None else None


def _split_game_ref(game):
    """``game`` 支持 ``seq`` 或 ``seq::fightId``（也接受 ``seq#fightId``）。"""
    text = str(game or '').strip()
    if not text:
        return None, None
    for separator in ('::', '#'):
        if separator in text:
            seq, _, fight_id = text.partition(separator)
            return seq.strip() or None, fight_id.strip() or None
    return text, None


def _camp_side(camp, own_code):
    if camp not in ('1', '2') or own_code not in ('1', '2'):
        return None
    return 'own' if camp == own_code else 'enemy'


def _beginner_side(own_count, enemy_count):
    if own_count > enemy_count:
        return 'own'
    if enemy_count > own_count:
        return 'enemy'
    if own_count or enemy_count:
        return 'tie'
    return None


def _row_sort_key(record):
    """损失优先：击杀差升序（负得越多越前）、开局人数差升序、开始时间升序。"""
    kill_diff = record.get('killDiff')
    advance = record.get('advStart')
    return (
        0 if kill_diff is not None else 1,
        kill_diff if kill_diff is not None else 0,
        advance if advance is not None else 0,
        record.get('startSec') or 0.0,
        record.get('game') or '',
        record.get('fightId') or '',
    )


# ---------------------------------------------------------------------------
# 单场团战
# ---------------------------------------------------------------------------
def _fight_members(game, fight, start, own_code):
    """参战成员明细；缺时间/缺阵营的 participant 跳过并计入 missing。"""
    details = {}
    for item in fight.get('details') or []:
        obj_id = str(item.get('objID') or '')
        if obj_id and obj_id not in details:
            details[obj_id] = item

    member_rows, missing = [], 0
    beginner = {'own': 0, 'enemy': 0}
    obj_to_player = game.get('objToPlayer') or {}
    heroes = game.get('heroes') or {}
    lanes = game.get('lanes') or {}

    for participant in fight.get('participants') or []:
        moment = _num(participant.get('timeSec'))
        camp = str(participant.get('camp') or '')
        side = _camp_side(camp, own_code)
        if moment is None or side is None:
            missing += 1
            continue
        obj_id = str(participant.get('objID') or '')
        player = obj_to_player.get(obj_id) or ''
        is_beginner = 1 if _int(participant.get('beginner')) == 1 else 0
        beginner[side] += is_beginner
        detail = details.get(obj_id) or {}
        member = {
            'objId': obj_id,
            'player': player,
            'hero': heroes.get(player) or '',
            'lane': lanes.get(player) or '',
            'camp': side,
            'campCode': camp,
            'arrivalLagSec': round(moment - start, 1),
            'joinOrder': None,
            'beginner': is_beginner,
        }
        for key in MEMBER_STAT_KEYS:
            member[key] = _int(detail.get(key))
        member_rows.append((moment, camp, member))

    member_rows.sort(key=lambda item: (item[0], item[1], item[2]['objId']))
    for order, row in enumerate(member_rows, 1):
        row[2]['joinOrder'] = order
    return [row[2] for row in member_rows], missing, beginner


def _fight_record(game, base, raw, own_code):
    """团战行：我方视角的关键指标 + 成员明细（rows 输出时会去掉 members）。"""
    start = base['startSec']
    members, member_missing, beginner = _fight_members(game, raw, start, own_code)
    own_lags = [member['arrivalLagSec'] for member in members if member['camp'] == 'own']
    avg_lag = round(match_facts.mean(own_lags), 1) if own_lags else None
    record = {
        'game': game.get('id'),
        'label': game.get('label') or '',
        'date': game.get('date') or '',
        'opponentId': game.get('opponentId'),
        'opponentName': game.get('opponentName') or '',
        'result': game.get('result'),
        'ownCamp': game.get('ownCamp'),
        'enemyCamp': game.get('enemyCamp'),
        'fightId': base['fightId'],
        'startSec': start,
        'endSec': base['endSec'],
        'duration': base['duration'],
        'phase': match_facts.phase_of(start),
        'timeLabel': match_facts.clock(start),
        'ownParticipants': base['ownParticipants'],
        'enemyParticipants': base['enemyParticipants'],
        'missingParticipants': max(member_missing, base['missingParticipants']),
        'arrivalDiff': base['arrivalDiff'],
        'advStart': base['advStart'],
        'ownKills': base['ownKills'],
        'enemyKills': base['enemyKills'],
        'killDiff': base['killDiff'],
        'won': base['won'],
        'lateJoins': base['lateJoins'],
        'firstSide': base['firstSide'],
        'firstKillerSide': _side_of_camp(raw.get('firstKillerCamp'), game.get('ownCamp')),
        'beginnerSide': _beginner_side(beginner['own'], beginner['enemy']),
        'avgArrivalLagSec': avg_lag,
        'members': members,
    }
    return record


def _selected_detail(record):
    detail = dict(record)
    detail['arrivalBars'] = [{
        'player': member['player'],
        'hero': member['hero'],
        'lane': member['lane'],
        'camp': member['camp'],
        'from': 0,
        'to': member['arrivalLagSec'],
    } for member in record.get('members') or []]
    return detail


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------
def _opening_buckets(records):
    counters = {advance: {'n': 0, 'wins': 0, 'decided': 0}
                for advance in range(BUCKET_MIN, BUCKET_MAX + 1)}
    unbucketed = 0
    for record in records:
        advance = record.get('advStart')
        bucket = counters.get(advance)
        if bucket is None:
            unbucketed += 1
            continue
        bucket['n'] += 1
        if record.get('killDiff') is not None:
            bucket['decided'] += 1
            if record.get('won'):
                bucket['wins'] += 1
    buckets = []
    for advance in range(BUCKET_MIN, BUCKET_MAX + 1):
        bucket = counters[advance]
        enough = bucket['n'] >= ENOUGH_BUCKET
        buckets.append({
            'advStart': advance,
            'n': bucket['n'],
            'wins': bucket['wins'],
            'decided': bucket['decided'],
            'winRate': round(bucket['wins'] / bucket['n'] * 100, 1) if bucket['n'] else None,
            'enough': enough,
        })
    return buckets, unbucketed


def _heat(records):
    counts = {}
    skipped = 0
    for record in records:
        kill_diff = record.get('killDiff')
        if kill_diff is None:
            skipped += 1
            continue
        key = (record.get('advStart'), kill_diff)
        cell = counts.setdefault(key, {'count': 0, 'ownWins': 0})
        cell['count'] += 1
        if record.get('won'):
            cell['ownWins'] += 1
    cells = []
    for (advance, kill_diff), cell in sorted(counts.items(),
                                             key=lambda item: (item[0][0], item[0][1])):
        cells.append({
            'x': advance,
            'y': kill_diff,
            'count': cell['count'],
            'ownWins': cell['ownWins'],
            'rate': round(cell['ownWins'] / cell['count'] * 100, 1),
        })
    advance_values = [cell['x'] for cell in cells]
    kill_values = [cell['y'] for cell in cells]
    return {
        'cells': cells,
        'max': max((cell['count'] for cell in cells), default=0),
        'skippedKillDiff': skipped,
        'xRange': [min(advance_values), max(advance_values)] if cells else [BUCKET_MIN, BUCKET_MAX],
        'yRange': [min(kill_values), max(kill_values)] if cells else None,
    }


def _first_arrival_counts(records):
    counts = {'own': 0, 'enemy': 0, 'tie': 0, 'none': 0}
    for record in records:
        side = record.get('firstSide')
        counts[side if side in ('own', 'enemy', 'tie') else 'none'] += 1
    return counts


def _side_of_camp(camp, own_camp):
    """把回放阵营码转成我方视角；未知返回 None。"""
    camp = str(camp or '')
    own_code = '1' if own_camp == 'blue' else ('2' if own_camp == 'red' else None)
    if not camp or not own_code:
        return None
    if camp == own_code:
        return 'own'
    return 'enemy'


def _opener_counts(records):
    """先手方统计：用 firstKillerCamp（首个击杀方）与 beginner 标记。"""
    counts = {'own': 0, 'enemy': 0, 'none': 0}
    beginner = {'own': 0, 'enemy': 0, 'tie': 0, 'none': 0}
    for record in records:
        side = record.get('firstKillerSide')
        counts[side if side in ('own', 'enemy') else 'none'] += 1
        side = record.get('beginnerSide')
        beginner[side if side in ('own', 'enemy', 'tie') else 'none'] += 1
    return counts, beginner


def _wipes(games):
    rows = []
    for game in games:
        for wipe in match_facts.wipes(game):
            item = dict(wipe)
            item['game'] = game.get('id')
            item['label'] = game.get('label') or ''
            rows.append(item)
    rows.sort(key=lambda item: (item.get('game') or '', item.get('t') or 0.0))
    sides = {'own': 0, 'enemy': 0}
    for item in rows:
        if item.get('side') in sides:
            sides[item['side']] += 1
    return rows, sides


def _summary(records, games):
    own_lags = []
    for record in records:
        for member in record.get('members') or []:
            if member['camp'] == 'own':
                own_lags.append(member['arrivalLagSec'])
    own_participants = sum(record.get('ownParticipants') or 0 for record in records)
    late_joins = sum(record.get('lateJoins') or 0 for record in records)
    buckets, unbucketed = _opening_buckets(records)
    wipe_rows, wipe_sides = _wipes(games)
    first_killer, beginner = _opener_counts(records)
    return {
        'fights': len(records),
        'avgArrivalLagSec': round(match_facts.mean(own_lags), 1) if own_lags else None,
        'lateJoins': late_joins,
        'lateJoinRate': round(late_joins / own_participants * 100, 1)
                        if own_participants else None,
        'ownParticipants': own_participants,
        'firstArrival': _first_arrival_counts(records),
        'firstArrivalNote': '本批回放的团战开始时刻就是最早参战时刻，firstArrival 多为 tie，'
                            '先手请改看 firstKiller / beginner。',
        'firstKiller': first_killer,
        'beginner': beginner,
        'openingBuckets': buckets,
        'unbucketedAdvStart': unbucketed,
        'heat': _heat(records),
        'wipes': len(wipe_rows),
        'wipeSides': wipe_sides,
        'wipeNote': '团灭指一方 5 人全部阵亡；同秒击杀不推断先后。',
        'wipeRows': wipe_rows[:20],
        'ownKills': sum(record.get('ownKills') or 0 for record in records),
        'enemyKills': sum(record.get('enemyKills') or 0 for record in records),
    }


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def _unavailable(filters, games, coverage, reason, note=''):
    return {
        'available': False,
        'reason': reason,
        'filters': filters,
        'summary': None,
        'rows': [],
        'selected': None,
        'coverage': coverage,
        'note': note or ('团战数据不足时不画看似完整的图；缺失参战时间的人不会被补成 0。'),
    }


def fight_report(facts, *, game=None, opponent=None, date_from=None, date_to=None,
                 result=None, side=None, limit=120):
    """团战执行报告：我方视角的到位、开局人数差、击杀交换与成员明细。"""
    facts = facts or {}
    seq_ref, fight_ref = _split_game_ref(game)
    try:
        limit_value = max(1, min(MAX_LIMIT, int(limit)))
    except (TypeError, ValueError):
        limit_value = DEFAULT_LIMIT
    side_value = side if side in ('own', 'enemy') else None
    filters = {
        'game': seq_ref,
        'fightId': fight_ref,
        'opponent': opponent or None,
        'dateFrom': date_from or None,
        'dateTo': date_to or None,
        'result': result or None,
        'side': side_value,
        'limit': limit_value,
    }
    note = ('团战指标统一按我方视角：arrivalDiff<0 表示我方先到；advStart 为团战开始 '
            f'{int(EARLY_WINDOW_SEC)} 秒内到达人数差（我方−敌方）；迟到指开始 '
            f'{int(LATE_JOIN_SEC)} 秒后才到。击杀差为 0 击杀的团战不计胜负。'
            '本批回放的 startSec 就是最早参战时刻，arrivalDiff/firstSide 无区分度，'
            '先手看 firstKillerSide/beginnerSide。以上只用于复盘描述，不判断指挥失误。')

    games = match_facts.filter_games(
        facts, game=seq_ref, opponent=opponent, date_from=date_from, date_to=date_to,
        result=result)

    raw_fights = sum(len(item.get('fights') or []) for item in games)
    fight_games = sum(1 for item in games if item.get('fights'))
    coverage = {
        'games': len(games),
        'fightGames': fight_games,
        'fights': raw_fights,
        'analyzedFights': 0,
        'skippedFights': 0,
        'missingParticipants': 0,
        'opponents': len({item.get('opponentId') for item in games if item.get('opponentId')}),
        'calibrated': bool((facts.get('coverage') or {}).get('calibrated')),
    }

    if not games:
        reason = '没有符合筛选条件的对局（需要已配对终局面板的官方回放）。'
        if not (facts.get('order') or []):
            reason = '当前没有可分析的回放对局：' + reason
        return _unavailable(filters, games, coverage, reason, note)
    if raw_fights == 0:
        return _unavailable(filters, games, coverage,
                            '所选对局没有团战段（battles.fights 为空），无法复盘团战执行。', note)

    records = []
    skipped_fights = 0
    missing_total = 0
    for item in games:
        own_code = match_facts.CAMP_CODE_REV.get(item.get('ownCamp'))
        raw_index = {}
        for raw in item.get('fights') or []:
            start = _num(raw.get('startSec'))
            if start is None:
                continue
            key = (str(raw.get('fightId') or ''), round(start, 1))
            raw_index.setdefault(key, raw)
        for base in match_facts.fight_events(item):
            raw = raw_index.get((base['fightId'], base['startSec']))
            if raw is None:
                raw = {'participants': [], 'details': []}
            missing_total += base.get('missingParticipants') or 0
            if (base.get('ownParticipants') or 0) + (base.get('enemyParticipants') or 0) <= 0:
                skipped_fights += 1
                continue
            records.append(_fight_record(item, base, raw, own_code))

    coverage['analyzedFights'] = len(records)
    coverage['skippedFights'] = skipped_fights
    coverage['missingParticipants'] = missing_total

    if not records:
        reason = (f'所选 {len(games)} 局对局里 {raw_fights} 场团战都缺少参战时间，'
                  '无法计算到位与人数差。')
        return _unavailable(filters, games, coverage, reason, note)

    records.sort(key=_row_sort_key)
    rows = []
    for record in records:
        row = dict(record)
        row.pop('members', None)
        rows.append(row)
    limited_rows = rows[:limit_value]

    pool = records
    if fight_ref:
        pool = [record for record in pool if record.get('fightId') == fight_ref]
    selected = _selected_detail(pool[0]) if pool else None
    selected_reason = None
    if selected is None:
        selected_reason = f'没有找到团战「{fight_ref}」的参战记录。' if fight_ref \
            else '没有可展示的团战明细。'

    return {
        'available': True,
        'filters': filters,
        'summary': _summary(records, games),
        'rows': limited_rows,
        'selected': selected,
        'selectedReason': selected_reason,
        'coverage': coverage,
        'note': note,
    }



# ===========================================================================
# Merged from merged module (opening_routes)
# ===========================================================================

"""对手开局路线与热区（决策台 P0-5）。

数据只来自 ``facts`` 的统一事实表；口径：

- 只取有位置的对局，开局 0–240 秒，每 5 秒采样一条路线（t, x, y）；
  同一局里同一侧的每名选手各算一条路线。
- 同一分路内做贪心聚类，距离 = 对齐采样点平均欧氏距离；
  阈值 0.18（已定标，单位为地图宽度）或 18（未定标，回放相对单位）。
  每条路线簇取 medoid（到同簇其他路线平均距离最小）作代表；
  分路样本 < 3 条时不聚类，逐条输出并标 ``enough=false``。
- ``zoneSequence`` 用固定 3×3 九宫格命名描述路线走过的区域，不推断草丛/视野。
- ``nextObjective`` = 开局段（240 秒）之后 4–10 分钟（240–600 秒）内该侧拿到的
  第一个资源/建筑事件，按簇统计频率。
- ``heat`` = 该侧 0–4 分钟位置点的 20×20 网格计数；已定标直接按 0–1 分格，
  未定标用 ``facts['positionBounds']`` 归一化到 0–1 后再分格（仍标 relative）。
- 本批每名对手通常只有 1 局回放：只做单局观察，不输出「固定套路」。
"""

import math
from collections import Counter

import match_facts

OPENING_UNTIL_SEC = 240
SAMPLE_STEP_SEC = 5
NEXT_OBJECTIVE_WINDOW = (240.0, 600.0)
CLUSTER_THRESHOLD_CALIBRATED = 0.18
CLUSTER_THRESHOLD_RELATIVE = 18.0
MIN_CLUSTER_ROUTES = 3
MIN_ROUTE_POINTS = 3
MIN_OVERLAP_POINTS = 4
HEAT_GRID = 20
LANE_ORDER = ('对抗路', '中路', '发育路', '打野', '游走')
UNKNOWN_LANE = '未标注分路'

# 固定命名：列 0=左 1=中 2=右，行 0=上 1=中 2=下（按 0–1 坐标直接三等分）
# 只是描述性命名，不是官方地图区域名，不推断草丛/视野。
ZONE_NAMES = {
    (0, 0): '蓝方野区',
    (1, 0): '上路河道',
    (2, 0): '红方野区',
    (0, 1): '蓝方对抗路',
    (1, 1): '中路',
    (2, 1): '红方对抗路',
    (0, 2): '蓝方发育路',
    (1, 2): '下路河道',
    (2, 2): '红方发育路',
}


# ---------------------------------------------------------------------------
# 坐标归一化 / 九宫格
# ---------------------------------------------------------------------------
def _clamp01(value):
    return min(1.0, max(0.0, value))


def _local_bounds(games):
    xs, ys = [], []
    for game in games:
        for arr in (game.get('positions') or {}).values():
            for point in (arr or [])[:OPENING_UNTIL_SEC]:
                if not point or (point[0] == 0 and point[1] == 0):
                    continue
                xs.append(float(point[0]))
                ys.append(float(point[1]))
    if not xs or not ys:
        return None
    return {'xMin': min(xs), 'xMax': max(xs), 'yMin': min(ys), 'yMax': max(ys)}


def _make_normalizer(facts, games):
    """返回 (calibrated, normalize)；normalize(point) → (u, v) 或 None。"""
    calibration = facts.get('calibration') or {}
    calibrated = bool(calibration.get('calibrated'))
    if calibrated:
        def normalize(point):
            if point is None:
                return None
            return (_clamp01(float(point[0])), _clamp01(float(point[1])))
        return True, normalize

    bounds = facts.get('positionBounds') or _local_bounds(games)
    if not bounds:
        return False, (lambda point: None)
    x_min, x_max = float(bounds['xMin']), float(bounds['xMax'])
    y_min, y_max = float(bounds['yMin']), float(bounds['yMax'])
    x_span = x_max - x_min
    y_span = y_max - y_min
    if x_span <= 0 or y_span <= 0:
        return False, (lambda point: None)

    def normalize(point):
        if point is None:
            return None
        return (_clamp01((float(point[0]) - x_min) / x_span),
                _clamp01((float(point[1]) - y_min) / y_span))

    return False, normalize


def _zone_of(u, v):
    if u is None or v is None:
        return None
    column = min(2, max(0, int(u * 3)))
    row = min(2, max(0, int(v * 3)))
    return ZONE_NAMES.get((column, row))


def _zone_sequence(points):
    """points: [(t, u, v)]；返回 (停留最久前 3 个区域名, 明细)。"""
    counts, first_seen = {}, {}
    for index, (_, u, v) in enumerate(points):
        zone = _zone_of(u, v)
        if not zone:
            continue
        counts[zone] = counts.get(zone, 0) + 1
        first_seen.setdefault(zone, index)
    ordered = sorted(counts, key=lambda zone: (-counts[zone], first_seen[zone]))
    picked = ordered[:3]
    detail = [{'name': zone, 'samples': counts[zone],
               'dwellSec': counts[zone] * SAMPLE_STEP_SEC} for zone in picked]
    return picked, detail


# ---------------------------------------------------------------------------
# 路线聚类
# ---------------------------------------------------------------------------
def _route_distance(first, second):
    """对齐采样点平均欧氏距离；重叠点太少返回 None（不合并）。"""
    common = first['map'].keys() & second['map'].keys()
    if len(common) < MIN_OVERLAP_POINTS:
        return None
    total = 0.0
    for moment in common:
        ax, ay = first['map'][moment]
        bx, by = second['map'][moment]
        total += math.hypot(ax - bx, ay - by)
    return total / len(common)


def _medoid(routes, threshold):
    if len(routes) == 1:
        return routes[0]
    best, best_score = routes[0], None
    for candidate in routes:
        total = 0.0
        for other in routes:
            if other is candidate:
                continue
            distance = _route_distance(candidate, other)
            total += threshold * 4 if distance is None else distance
        if best_score is None or total < best_score:
            best, best_score = candidate, total
    return best


def _cluster_routes(routes, threshold):
    clusters = []
    for route in routes:
        target = None
        for cluster in clusters:
            distance = _route_distance(route, cluster['medoid'])
            if distance is not None and distance <= threshold and \
                    (target is None or distance < target[0]):
                target = (distance, cluster)
        if target is None:
            clusters.append({'routes': [route], 'medoid': route})
        else:
            cluster = target[1]
            cluster['routes'].append(route)
            cluster['medoid'] = _medoid(cluster['routes'], threshold)
    return clusters


def _mean_pair_distance(routes):
    distances = []
    for index, first in enumerate(routes):
        for second in routes[index + 1:]:
            distance = _route_distance(first, second)
            if distance is not None:
                distances.append(distance)
    if not distances:
        return None
    return sum(distances) / len(distances)


# ---------------------------------------------------------------------------
# 后续第一个资源/建筑
# ---------------------------------------------------------------------------
def _route_next_objective(route, game, side):
    for event in match_facts.objective_events(game):
        moment = event.get('t')
        if moment is None:
            continue
        if moment < NEXT_OBJECTIVE_WINDOW[0] or moment > NEXT_OBJECTIVE_WINDOW[1]:
            continue
        if event.get('camp') != side:
            continue
        return {
            'type': event.get('kind') or 'other',
            'name': event.get('name') or '',
            'minutes': round(moment / 60.0, 1),
            't': round(moment, 1),
        }
    return None


def _next_objective(routes, side, games_by_id):
    """同簇频率：该簇路线在开局段后拿到的第一个资源/建筑的分布。"""
    found = []
    for route in routes:
        game = games_by_id.get(route['game'])
        if not game:
            continue
        objective = _route_next_objective(route, game, side)
        if objective:
            found.append((route, objective))
    if not found:
        return None

    groups = {}
    for route, objective in found:
        key = (objective['type'], objective['name'])
        group = groups.setdefault(key, {'routes': [], 'minutes': []})
        group['routes'].append(route)
        group['minutes'].append(objective['minutes'])

    ordered = sorted(groups.items(),
                     key=lambda item: (-len(item[1]['routes']), item[0][0], item[0][1]))
    top_key, top = ordered[0]
    minutes = match_facts.median(top['minutes'])
    options = []
    for (kind, name), group in ordered[:4]:
        options.append({
            'type': kind,
            'name': name,
            'minutes': round(match_facts.median(group['minutes']), 1),
            'count': len(group['routes']),
            'games': len({route['game'] for route in group['routes']}),
        })
    return {
        'type': top_key[0],
        'name': top_key[1],
        'minutes': round(minutes, 1) if minutes is not None else None,
        'count': len(top['routes']),
        'games': len({route['game'] for route in top['routes']}),
        'enough': len(top['routes']) >= MIN_CLUSTER_ROUTES,
        'options': options,
    }


# ---------------------------------------------------------------------------
# 路线输出
# ---------------------------------------------------------------------------
def _render_cluster(cluster, side, calibrated, normalize, games_by_id):
    routes = cluster['routes']
    medoid = cluster['medoid']
    count = len(routes)

    normalized_points = []
    for moment, x, y in medoid['points']:
        point = normalize((x, y))
        if point is None:
            continue
        normalized_points.append((moment, point[0], point[1]))
    zone_sequence, zones = _zone_sequence(normalized_points)
    average = _mean_pair_distance(routes)

    return {
        'lane': medoid['lane'],
        'side': side,
        'count': count,
        'enough': count >= MIN_CLUSTER_ROUTES,
        'games': len({route['game'] for route in routes}),
        'gameIds': sorted({route['game'] for route in routes}),
        'avgDistance': None if average is None
                       else (round(average, 3) if calibrated else round(average, 1)),
        'representative': {
            'game': medoid['game'],
            'label': medoid['gameLabel'],
            'player': medoid['player'],
            'hero': medoid['hero'],
            'name': medoid['name'],
            'lane': medoid['lane'],
            'times': [moment for moment, _, _ in normalized_points],
            'points': [[round(u, 3), round(v, 3)] for _, u, v in normalized_points],
        },
        'zoneSequence': zone_sequence,
        'zones': zones,
        'nextObjective': _next_objective(routes, side, games_by_id),
    }


# ---------------------------------------------------------------------------
# 对手列表 / 样本标记
# ---------------------------------------------------------------------------
def _opponent_list(facts, date_games):
    scope_ids = {game.get('id') for game in date_games}
    games = facts.get('games') or {}
    opponents = []
    for item in facts.get('opponents') or []:
        replay_seqs = [seq for seq in item.get('seqs') or [] if seq in games]
        if not replay_seqs:
            continue
        position_seqs = [seq for seq in replay_seqs if games[seq].get('hasPositions')]
        opponents.append({
            'id': item.get('id') or '',
            'name': item.get('name') or '',
            'replayGames': len(replay_seqs),
            'positionGames': len(position_seqs),
            'games': sum(1 for seq in position_seqs if seq in scope_ids),
            'enough': len(replay_seqs) >= MIN_CLUSTER_ROUTES,
        })
    opponents.sort(key=lambda item: (-(item['games'] or 0), -(item['replayGames'] or 0),
                                     item.get('name') or ''))
    return opponents


def _selected_opponent(opponents, opponent, games):
    if opponent:
        matched = next((item for item in opponents
                        if opponent in (item.get('id'), item.get('name'))), None)
        if matched:
            selected = dict(matched)
        else:
            selected = {'id': opponent, 'name': opponent, 'replayGames': 0,
                        'positionGames': 0, 'games': 0, 'enough': False}
        selected['enough'] = (selected.get('games') or 0) >= MIN_CLUSTER_ROUTES
        selected['note'] = ('样本不足（<3 局回放），只做单局观察，不输出固定套路。'
                            if not selected['enough'] else
                            f"本批 {selected.get('games')} 局回放，可看路线出现次数，仍不代表全部比赛。")
        return selected

    in_scope = [item for item in opponents if (item.get('games') or 0) > 0]
    if len(in_scope) == 1:
        selected = dict(in_scope[0])
        selected['enough'] = (selected.get('games') or 0) >= MIN_CLUSTER_ROUTES
        selected['note'] = ('样本不足（<3 局回放），只做单局观察，不输出固定套路。'
                            if not selected['enough'] else
                            f"本批 {selected.get('games')} 局回放，可看路线出现次数，仍不代表全部比赛。")
        return selected

    replay = sum((item.get('replayGames') or 0) for item in in_scope)
    selected = {
        'id': None,
        'name': '全部对手（本批）',
        'replayGames': replay,
        'positionGames': sum((item.get('positionGames') or 0) for item in in_scope),
        'games': len(games),
        'enough': False,
        'note': '未指定对手：当前是整批对手的落点分布，不是某个战队的固定套路；样本不足，只做观察。',
    }
    return selected


def _notes(facts, coverage, calibrated):
    notes = []
    total_replays = len(facts.get('order') or [])
    notes.append(f'仅收录本批 {total_replays} 局回放，不能推断对手全部比赛习惯。')
    opponents = [item for item in facts.get('opponents') or []
                 if (item.get('replayGames') or 0) > 0]
    most = max((item.get('replayGames') or 0) for item in opponents) if opponents else 0
    if most <= 1:
        notes.append('每名对手目前 1 局回放，样本不足只做单局观察。')
    else:
        notes.append(f'每名对手目前最多 {most} 局回放，不足 3 局的只做单局观察。')
    notes.append('路线与热区只基于开局 0–4 分钟的位置采样，不推断草丛、视野和分路意图。')
    notes.append('九宫格是按地图坐标三等分的固定命名，只用于描述路线走向，不是官方区域名。')
    if calibrated:
        notes.append(f'坐标已按本批位置分位定标：聚类阈值 '
                     f'{CLUSTER_THRESHOLD_CALIBRATED}，单位是地图宽度。')
    else:
        notes.append(f'坐标未定标：路线按回放相对坐标聚类（阈值 '
                     f'{CLUSTER_THRESHOLD_RELATIVE}），热区用 positionBounds 归一化到 0–1 '
                     '展示；相对单位不能当米/格。')
    notes.append('样本 < 3 局的路线不做聚类，页面必须显示「样本不足，仅单局观察」。')
    return notes


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def opening_report(facts, *, opponent=None, lane=None, date_from=None, date_to=None,
                   side='enemy'):
    """对手（或我方）开局路线与热区报告；默认看对手（side='enemy'）。"""
    facts = facts or {}
    side = side if side in ('own', 'enemy') else 'enemy'
    lane_filter = (lane or '').strip() or None
    filters = {
        'opponent': opponent or None,
        'lane': lane_filter,
        'dateFrom': date_from or None,
        'dateTo': date_to or None,
        'side': side,
    }

    date_games = match_facts.filter_games(facts, date_from=date_from, date_to=date_to)
    opponents = _opponent_list(facts, date_games)
    if opponent:
        games = [game for game in date_games
                 if opponent in (game.get('opponentId'), game.get('opponentName'))]
    else:
        games = date_games

    position_games = [game for game in games if game.get('hasPositions')]
    calibrated, normalize = _make_normalizer(facts, position_games)
    threshold = CLUSTER_THRESHOLD_CALIBRATED if calibrated else CLUSTER_THRESHOLD_RELATIVE
    coverage = {
        'games': len(games),
        'positionGames': len(position_games),
        'replayGamesAll': len(facts.get('order') or []),
        'routes': 0,
        'skippedRoutes': 0,
        'clusters': 0,
        'sampleUntilSec': OPENING_UNTIL_SEC,
        'sampleStepSec': SAMPLE_STEP_SEC,
        'clusterThreshold': threshold,
        'minCluster': MIN_CLUSTER_ROUTES,
        'calibrated': calibrated,
        'relative': not calibrated,
        'heatPoints': 0,
        'opponents': sum(1 for item in opponents if item.get('replayGames')),
        'dateRange': (facts.get('coverage') or {}).get('dateRange') or [],
    }
    notes = _notes(facts, coverage, calibrated)
    heat_empty = {'cells': [], 'max': 0, 'grid': HEAT_GRID, 'games': 0, 'total': 0,
                  'unit': 'mapWidth' if calibrated else 'relative-normalized'}

    def unavailable(reason):
        return {
            'available': False,
            'reason': reason,
            'filters': filters,
            'opponents': opponents,
            'selected': _selected_opponent(opponents, opponent, games),
            'lanes': [],
            'routes': [],
            'heat': heat_empty,
            'coverage': coverage,
            'notes': notes,
        }

    if not games:
        return unavailable('没有符合筛选条件的回放对局（需要终局面板 + 官方回放）。')
    if not position_games:
        return unavailable('所选对局没有可用位置数据（positions.json 缺失或为空），'
                           '无法分析开局路线与热区。')
    if normalize((0.0, 0.0)) is None:
        return unavailable('缺少坐标范围，无法把位置归一化到 0–1（未定标且 positionBounds 为空）。')

    games_by_id = {game.get('id'): game for game in position_games}

    # ---- 路线采样 ----
    routes_by_lane = {}
    skipped_routes = 0
    for game in position_games:
        own_code = match_facts.CAMP_CODE_REV.get(game.get('ownCamp'))
        if own_code not in ('1', '2'):
            continue
        target_code = own_code if side == 'own' else ('2' if own_code == '1' else '1')
        names = {item.get('playerId'): item.get('name') or ''
                 for item in game.get('players') or []}
        for player_id in (game.get('campPlayers') or {}).get(target_code) or []:
            lane_name = (game.get('lanes') or {}).get(player_id) or ''
            if lane_filter and lane_name != lane_filter:
                continue
            points = match_facts.player_points(
                game, player_id, until=OPENING_UNTIL_SEC, step=SAMPLE_STEP_SEC)
            if len(points) < MIN_ROUTE_POINTS:
                skipped_routes += 1
                continue
            lane_name = lane_name or UNKNOWN_LANE
            routes_by_lane.setdefault(lane_name, []).append({
                'game': game.get('id'),
                'gameLabel': game.get('label') or '',
                'player': player_id,
                'hero': (game.get('heroes') or {}).get(player_id) or '',
                'name': names.get(player_id) or '',
                'lane': lane_name,
                'side': side,
                'points': points,
                'map': {int(moment): (x, y) for moment, x, y in points},
            })

    def lane_sort_key(name):
        return (LANE_ORDER.index(name) if name in LANE_ORDER else len(LANE_ORDER), name)

    rendered_routes, lane_rows = [], []
    route_total = 0
    for lane_name in sorted(routes_by_lane, key=lane_sort_key):
        group = routes_by_lane[lane_name]
        route_total += len(group)
        if len(group) < MIN_CLUSTER_ROUTES:
            clusters = [{'routes': [route], 'medoid': route} for route in group]
        else:
            clusters = _cluster_routes(group, threshold)
        cluster_rows = [_render_cluster(cluster, side, calibrated, normalize, games_by_id)
                        for cluster in clusters]
        cluster_rows.sort(key=lambda item: (-item['count'],
                                            item['representative']['game'],
                                            item['representative']['player']))
        lane_rows.append({
            'lane': lane_name,
            'routes': len(group),
            'clusters': len(cluster_rows),
            'enough': any(item['enough'] for item in cluster_rows),
        })
        rendered_routes.extend(cluster_rows)

    coverage['routes'] = route_total
    coverage['skippedRoutes'] = skipped_routes
    coverage['clusters'] = len(rendered_routes)
    if not rendered_routes:
        if lane_filter:
            return unavailable(f'当前筛选下没有分路「{lane_filter}」的位置路线。')
        return unavailable('所选对局在该侧没有可用的开局位置路线。')

    # ---- 热区（该侧 0–4 分钟，逐秒）----
    heat_counts = {}
    heat_games = set()
    for game in position_games:
        own_code = match_facts.CAMP_CODE_REV.get(game.get('ownCamp'))
        if own_code not in ('1', '2'):
            continue
        target_code = own_code if side == 'own' else ('2' if own_code == '1' else '1')
        for player_id in (game.get('campPlayers') or {}).get(target_code) or []:
            lane_name = (game.get('lanes') or {}).get(player_id) or ''
            if lane_filter and lane_name != lane_filter:
                continue
            for _, x, y in match_facts.player_points(
                    game, player_id, until=OPENING_UNTIL_SEC, step=1):
                point = normalize((x, y))
                if point is None:
                    continue
                column = min(HEAT_GRID - 1, max(0, int(point[0] * HEAT_GRID)))
                row = min(HEAT_GRID - 1, max(0, int(point[1] * HEAT_GRID)))
                heat_counts[(column, row)] = heat_counts.get((column, row), 0) + 1
                heat_games.add(game.get('id'))
    cells = [{'x': column, 'y': row, 'n': count}
             for (column, row), count in sorted(heat_counts.items(),
                                                key=lambda item: (item[0][1], item[0][0]))]
    total_points = sum(cell['n'] for cell in cells)
    heat = {
        'cells': cells,
        'max': max((cell['n'] for cell in cells), default=0),
        'grid': HEAT_GRID,
        'games': len(heat_games),
        'total': total_points,
        'unit': 'mapWidth' if calibrated else 'relative-normalized',
    }
    coverage['heatPoints'] = total_points

    return {
        'available': True,
        'filters': filters,
        'opponents': opponents,
        'selected': _selected_opponent(opponents, opponent, games),
        'lanes': lane_rows,
        'routes': rendered_routes,
        'heat': heat,
        'coverage': coverage,
        'notes': notes,
    }
