"""对手开局路线与热区（决策台 P0-5）。

数据只来自 ``decision_facts`` 的统一事实表；口径：

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
from __future__ import annotations

import math
from collections import Counter

import decision_facts

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
    for event in decision_facts.objective_events(game):
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
    minutes = decision_facts.median(top['minutes'])
    options = []
    for (kind, name), group in ordered[:4]:
        options.append({
            'type': kind,
            'name': name,
            'minutes': round(decision_facts.median(group['minutes']), 1),
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

    date_games = decision_facts.filter_games(facts, date_from=date_from, date_to=date_to)
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
        own_code = decision_facts.CAMP_CODE_REV.get(game.get('ownCamp'))
        if own_code not in ('1', '2'):
            continue
        target_code = own_code if side == 'own' else ('2' if own_code == '1' else '1')
        names = {item.get('playerId'): item.get('name') or ''
                 for item in game.get('players') or []}
        for player_id in (game.get('campPlayers') or {}).get(target_code) or []:
            lane_name = (game.get('lanes') or {}).get(player_id) or ''
            if lane_filter and lane_name != lane_filter:
                continue
            points = decision_facts.player_points(
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
        own_code = decision_facts.CAMP_CODE_REV.get(game.get('ownCamp'))
        if own_code not in ('1', '2'):
            continue
        target_code = own_code if side == 'own' else ('2' if own_code == '1' else '1')
        for player_id in (game.get('campPlayers') or {}).get(target_code) or []:
            lane_name = (game.get('lanes') or {}).get(player_id) or ''
            if lane_filter and lane_name != lane_filter:
                continue
            for _, x, y in decision_facts.player_points(
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
