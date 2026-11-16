"""Ban × 英雄池的描述性分析：双向散点、ban 形状、替代结构、池深度。

只做描述与条件关联，不判断“该 ban 谁”，也不做因果推断。
所有比例都带分母；分路未知单列“未标注”，不并入其他分路。
"""
from __future__ import annotations

from collections import Counter, defaultdict

LANES = ('对抗路', '打野', '中路', '发育路', '游走')
UNLABELED = '未标注'
OTHER_TYPE = '其他类型'
_THRESHOLDS = {'pick': 20.0, 'ban': 20.0}
_KPL_HERO_CACHE: dict[tuple, dict] = {}


def _block(game, side):
    return (((game.get('sides') or {}).get(side)) or {})


def _pick_win(game, side):
    return game.get('win') if side == 'own' else game.get('opponentWin')


def _pick_stats(games, side):
    """英雄 × 出场：局数、胜场、结果已知局、主分路/主类型。"""
    rows = {}
    for game in games:
        win = _pick_win(game, side)
        for pick in _block(game, side).get('picks') or []:
            hero = (pick or {}).get('name')
            if not hero:
                continue
            row = rows.setdefault(hero, {
                'hero': hero, 'games': 0, 'wins': 0, 'decided': 0,
                'lanes': Counter(), 'archetypes': Counter(),
            })
            row['games'] += 1
            if win is True:
                row['wins'] += 1
            if win in (True, False):
                row['decided'] += 1
            lane, archetype = (pick.get('lane') or ''), (pick.get('archetype') or '')
            if lane:
                row['lanes'][lane] += 1
            if archetype and archetype != UNLABELED:
                row['archetypes'][archetype] += 1
    for row in rows.values():
        row['lane'] = row['lanes'].most_common(1)[0][0] if row['lanes'] else ''
        row['archetype'] = (row['archetypes'].most_common(1)[0][0]
                            if row['archetypes'] else UNLABELED)
        row['winRate'] = (round(row['wins'] / row['decided'] * 100, 1)
                          if row['decided'] else None)
    return rows


def _ban_stats(games, side):
    """英雄 × 被 ban：出现局数、ban 事件数、主分路/主类型。"""
    rows = {}
    seen = defaultdict(set)
    for index, game in enumerate(games):
        key = str(game.get('seq') or index)
        for ban in _block(game, side).get('bans') or []:
            hero = (ban or {}).get('name')
            if not hero:
                continue
            row = rows.setdefault(hero, {
                'hero': hero, 'games': 0, 'events': 0,
                'lanes': Counter(), 'archetypes': Counter(),
            })
            row['events'] += 1
            if key not in seen[hero]:
                seen[hero].add(key)
                row['games'] += 1
            lane, archetype = (ban.get('lane') or ''), (ban.get('archetype') or '')
            if lane:
                row['lanes'][lane] += 1
            if archetype and archetype != UNLABELED:
                row['archetypes'][archetype] += 1
    for row in rows.values():
        row['lane'] = row['lanes'].most_common(1)[0][0] if row['lanes'] else ''
        row['archetype'] = (row['archetypes'].most_common(1)[0][0]
                            if row['archetypes'] else UNLABELED)
    return rows


def _top(rows, total, limit=5, key='games'):
    ordered = sorted(rows, key=lambda row: (-(row.get(key) or 0),
                                            -(row.get('winRate') or 0),
                                            row.get('hero') or ''))
    out = []
    for row in ordered[:limit]:
        item = {k: row.get(k) for k in
                ('hero', 'games', 'wins', 'winRate', 'events', 'lane', 'archetype')}
        item['rate'] = (round((row.get(key) or 0) / total * 100, 1)
                        if total else None)
        out.append(item)
    return out


def _lane_rows(counter, total):
    rows = [{'key': key, 'games': n,
             'share': round(n / total * 100, 1) if total else None}
            for key, n in counter.most_common() if key]
    seen = sum(row['games'] for row in rows)
    if total and seen < total:
        rows.append({'key': UNLABELED, 'games': total - seen,
                     'share': round((total - seen) / total * 100, 1)})
    return rows


def _type_rows(counter, total, limit=6):
    rows = [{'key': key, 'games': n,
             'share': round(n / total * 100, 1) if total else None}
            for key, n in counter.most_common() if key and key != UNLABELED][:limit]
    used = sum(row['games'] for row in rows) + (counter.get(UNLABELED) or 0)
    if counter.get(UNLABELED):
        rows.append({'key': UNLABELED, 'games': counter[UNLABELED],
                     'share': round(counter[UNLABELED] / total * 100, 1)})
    if total and used < total:
        rows.append({'key': OTHER_TYPE, 'games': total - used,
                     'share': round((total - used) / total * 100, 1)})
    return rows


def _ban_lane_counter(rows):
    counter = Counter()
    for row in rows.values():
        for lane, n in row['lanes'].items():
            counter[lane] += n
    return counter


def _ban_type_counter(rows):
    counter = Counter()
    for row in rows.values():
        for archetype, n in row['archetypes'].items():
            counter[archetype] += n
        counter[UNLABELED] += max(0, row['events'] - sum(row['archetypes'].values()))
    return counter


def _targeting(ban_rows, pick_rows, total_games):
    top = _top(pick_rows.values(), total_games, 5)
    top_heroes = {row['hero'] for row in top}
    ban_events = sum(row['events'] for row in ban_rows.values())
    hit_events = sum(row['events'] for hero, row in ban_rows.items()
                     if hero in top_heroes)
    pick_events = sum(row['games'] for row in pick_rows.values())
    target = round(hit_events / ban_events * 100, 1) if ban_events else None
    random = (round(sum(row['games'] for row in pick_rows.values()
                        if row['hero'] in top_heroes) / pick_events * 100, 1)
              if pick_events else None)
    lift = (round(target / random, 2) if target is not None and random else None)
    return {
        'top': top,
        'banEvents': ban_events,
        'hitEvents': hit_events,
        'pickEvents': pick_events,
        'targetRate': target,
        'randomRate': random,
        'lift': lift,
    }


def _target_rows(games, side, limit=3):
    """按给定局子集统计某侧 ban 的前几个目标（按出现局数去重）。"""
    counter, seen = Counter(), defaultdict(set)
    for index, game in enumerate(games):
        key = str(game.get('seq') or index)
        for ban in _block(game, side).get('bans') or []:
            hero = (ban or {}).get('name')
            if not hero:
                continue
            counter[hero] += 1
            seen[hero].add(key)
    rows = []
    for hero, events in sorted(counter.items(), key=lambda item: (-len(seen[item[0]]),
                                                                  -item[1], item[0]))[:limit]:
        games_n = len(seen[hero])
        rows.append({'hero': hero, 'games': games_n, 'events': events,
                     'rate': round(games_n / len(games) * 100, 1) if games else None})
    return rows


def _side_split(games, side):
    groups = {'blue': [], 'red': [], 'unknown': []}
    for game in games:
        own = game.get('ownSide')
        enemy_side = 'red' if own == 'blue' else 'blue' if own == 'red' else 'unknown'
        groups[enemy_side].append(game)
    out = {}
    for name, subset in groups.items():
        if not subset:
            out[name] = {'games': 0, 'top': [], 'laneDist': []}
            continue
        stats = _ban_stats(subset, side)
        lane_counter = Counter()
        for row in stats.values():
            for lane, n in row['lanes'].items():
                lane_counter[lane] += n
        total_events = sum(row['events'] for row in stats.values())
        out[name] = {
            'games': len(subset),
            'top': _target_rows(subset, side),
            'laneDist': _lane_rows(lane_counter, total_events),
        }
    return out


def _period_split(games, side):
    ordered = sorted(games, key=lambda game: str(game.get('start') or ''))
    first_n = len(ordered) // 2
    first, last = ordered[:first_n], ordered[first_n:]
    return {
        'first': {'games': len(first), 'top': _target_rows(first, side) if first else []},
        'last': {'games': len(last), 'top': _target_rows(last, side) if last else []},
    }


def _points(ban_rows, pick_rows, total_games):
    heroes = set(ban_rows) | set(pick_rows)
    points = []
    for hero in heroes:
        ban = ban_rows.get(hero) or {}
        pick = pick_rows.get(hero) or {}
        points.append({
            'hero': hero,
            'lane': pick.get('lane') or ban.get('lane') or '',
            'archetype': pick.get('archetype') or ban.get('archetype') or UNLABELED,
            'pickGames': pick.get('games') or 0,
            'pickRate': round((pick.get('games') or 0) / total_games * 100, 1) if total_games else None,
            'pickWins': pick.get('wins') or 0,
            'pickWinRate': pick.get('winRate'),
            'banGames': ban.get('games') or 0,
            'banRate': round((ban.get('games') or 0) / total_games * 100, 1) if total_games else None,
            'banEvents': ban.get('events') or 0,
        })
    points.sort(key=lambda point: (-(point['banRate'] or 0), -(point['pickRate'] or 0),
                                   point['hero']))
    return points


def _waste(ban_rows, pick_rows, total_games, limit=5):
    rows = []
    for hero, ban in ban_rows.items():
        pick = pick_rows.get(hero) or {}
        games_n = pick.get('games') or 0
        rate = round(games_n / total_games * 100, 1) if total_games else None
        if rate is not None and rate <= 8 and ban.get('games'):
            rows.append({'hero': hero, 'banGames': ban['games'],
                         'banRate': round(ban['games'] / total_games * 100, 1),
                         'pickGames': games_n, 'pickRate': rate,
                         'lane': ban.get('lane') or '', 'archetype': ban.get('archetype') or UNLABELED})
    rows.sort(key=lambda row: (-row['banGames'], row['hero']))
    return rows[:limit]


def ban_matchup(games):
    """双向 ban×英雄池：他们 ban vs 我们选，我们 ban vs 他们选。"""
    total = len(games)
    if not total:
        return {'games': 0, 'thresholds': _THRESHOLDS}
    their_bans = _ban_stats(games, 'enemy')
    our_picks = _pick_stats(games, 'own')
    our_bans = _ban_stats(games, 'own')
    their_picks = _pick_stats(games, 'enemy')

    their_targeting = _targeting(their_bans, our_picks, total)
    our_targeting = _targeting(our_bans, their_picks, total)
    their_lane = _lane_rows(_ban_lane_counter(their_bans),
                            sum(row['events'] for row in their_bans.values()))
    our_lane = _lane_rows(_ban_lane_counter(our_bans),
                          sum(row['events'] for row in our_bans.values()))
    return {
        'games': total,
        'thresholds': _THRESHOLDS,
        'theirBansVsOurPool': {
            'points': _points(their_bans, our_picks, total),
            'targeting': their_targeting,
            'laneDist': their_lane,
            'sideSplit': _side_split(games, 'enemy'),
            'periodSplit': _period_split(games, 'enemy'),
        },
        'ourBansVsTheirPool': {
            'points': _points(our_bans, their_picks, total),
            'targeting': our_targeting,
            'laneDist': our_lane,
            'typeDist': _type_rows(_ban_type_counter(our_bans),
                                   sum(row['events'] for row in our_bans.values())),
            'waste': _waste(our_bans, their_picks, total),
        },
    }


def replacement_structure(games, ban_outcome=None):
    """我们 ban 后，他们在同一分路的替代结构。"""
    total = len(games)
    outcomes = {row.get('hero'): row for row in (ban_outcome or [])}
    if not total:
        return {'games': 0, 'rows': [], 'matrix': {'rows': [], 'columns': []}}
    detail = {}
    matrix = Counter()
    for index, game in enumerate(games):
        picks = {pick.get('lane'): pick for pick in _block(game, 'enemy').get('picks') or []
                 if pick.get('lane')}
        players = {player.get('lane'): player for player in _block(game, 'enemy').get('players') or []
                   if player.get('lane')}
        for ban in _block(game, 'own').get('bans') or []:
            hero = (ban or {}).get('name')
            if not hero:
                continue
            lane = ban.get('lane') or ''
            archetype = ban.get('archetype') or UNLABELED
            row = detail.setdefault(hero, {
                'hero': hero, 'lane': lane, 'archetype': archetype,
                'games': 0, 'assigned': 0,
                'heroes': Counter(), 'types': Counter(), 'players': Counter(),
                'sameType': 0, 'crossType': 0, 'unknownType': 0,
            })
            row['games'] += 1
            pick = picks.get(lane)
            if not pick:
                continue
            replacement = pick.get('hero') or pick.get('name') or ''
            replacement_type = pick.get('archetype') or UNLABELED
            if not replacement:
                continue
            row['assigned'] += 1
            row['heroes'][replacement] += 1
            row['types'][replacement_type] += 1
            player = players.get(lane) or {}
            if player.get('name'):
                row['players'][player['name']] += 1
            if not archetype or archetype == UNLABELED or replacement_type == UNLABELED:
                row['unknownType'] += 1
            elif archetype == replacement_type:
                row['sameType'] += 1
            else:
                row['crossType'] += 1
            matrix[(archetype, replacement_type)] += 1

    rows = []
    for hero, row in sorted(detail.items(), key=lambda item: (-item[1]['games'], item[0])):
        if row['games'] < 3:
            continue
        assigned = row['assigned']
        hhi = (sum((n / assigned) ** 2 for n in row['heroes'].values())
               if assigned else None)
        effective = round(1 / hhi, 2) if hhi else None
        replacements = [{'hero': name, 'games': n,
                         'share': round(n / assigned * 100, 1) if assigned else None}
                        for name, n in row['heroes'].most_common(3)]
        players = [{'name': name, 'games': n,
                    'share': round(n / assigned * 100, 1) if assigned else None}
                   for name, n in row['players'].most_common(2)]
        outcome = outcomes.get(hero) or {}
        rows.append({
            'hero': hero, 'lane': row['lane'], 'archetype': row['archetype'],
            'games': row['games'], 'assigned': assigned,
            'distinct': len(row['heroes']), 'effective': effective,
            'sameTypeRate': round(row['sameType'] / assigned * 100, 1) if assigned else None,
            'crossTypeRate': round(row['crossType'] / assigned * 100, 1) if assigned else None,
            'unknownTypeRate': round(row['unknownType'] / assigned * 100, 1) if assigned else None,
            'replacements': replacements,
            'players': players,
            'playerCount': len(row['players']),
            'oppWins': outcome.get('oppWins'),
            'oppWinRate': outcome.get('rate'),
            'delta': outcome.get('delta'),
            'wilson': outcome.get('wilson'),
        })
        if len(rows) >= 8:
            break

    row_totals, col_totals = Counter(), Counter()
    for (row_type, col_type), n in matrix.items():
        row_totals[row_type] += n
        col_totals[col_type] += n
    row_keys = [key for key, _ in row_totals.most_common(7)]
    col_keys = [key for key, _ in col_totals.most_common(7)]
    row_set, col_set = set(row_keys), set(col_keys)
    cells = Counter()
    for (row_type, col_type), n in matrix.items():
        rows_key = row_type if row_type in row_set else '其他'
        col_key = col_type if col_type in col_set else '其他'
        cells[(rows_key, col_key)] += n
    if any(row_key == '其他' for row_key, _ in cells) and '其他' not in row_keys:
        row_keys.append('其他')
    if any(col_key == '其他' for _, col_key in cells) and '其他' not in col_keys:
        col_keys.append('其他')
    top_transitions = [{'from': row_type, 'to': col_type, 'games': n}
                       for (row_type, col_type), n in matrix.most_common(8)]
    return {
        'games': total,
        'rows': rows,
        'matrix': {
            'rows': row_keys,
            'columns': col_keys,
            'cells': [{'row': row_key, 'col': col_key, 'games': n}
                      for (row_key, col_key), n in cells.items()],
            'top': top_transitions,
        },
    }


def _kpl_hero_index():
    """从 KPL 五人成阵聚合英雄级出场/胜率；不是官方英雄榜，页面标来源。"""
    try:
        import bp_facts
        index = bp_facts.kpl_index()
    except Exception:  # noqa: BLE001 - 外部事实表缺失时返回空，不影响主分析
        return {}
    key = (index.get('updatedAt'), index.get('games'), len(index.get('lineups') or {}))
    cached = _KPL_HERO_CACHE.get(key)
    if cached is not None:
        return cached
    stats = defaultdict(lambda: {'games': 0, 'wins': 0})
    for row in (index.get('lineups') or {}).values():
        games_n = row.get('n') or 0
        wins = row.get('wins') or 0
        for hero in row.get('heroes') or []:
            stats[hero]['games'] += games_n
            stats[hero]['wins'] += wins
    out = {hero: {'games': row['games'],
                  'wins': row['wins'],
                  'winRate': round(row['wins'] / row['games'] * 100, 1)
                  if row['games'] else None}
           for hero, row in stats.items()}
    _KPL_HERO_CACHE.clear()
    _KPL_HERO_CACHE[key] = out
    return out


def pool_depth(games):
    """对手五路英雄池深度：出场数、有效英雄数、top1/top2、去掉 top1 后。"""
    total = len(games)
    kpl = _kpl_hero_index()
    lanes = []
    for lane in LANES:
        counter = Counter()
        for game in games:
            for pick in _block(game, 'enemy').get('picks') or []:
                if pick.get('lane') == lane and pick.get('name'):
                    counter[pick['name']] += 1
        total_lane = sum(counter.values())
        if not total_lane:
            lanes.append({'lane': lane, 'games': 0, 'heroes': 0, 'effective': None,
                          'top1': None, 'top2': None, 'afterTop1': None, 'backups': []})
            continue
        hhi = sum((n / total_lane) ** 2 for n in counter.values())
        ordered = counter.most_common()
        top1 = ordered[0]
        top2 = ordered[1] if len(ordered) > 1 else None
        remaining = Counter({hero: n for hero, n in ordered[1:]})
        remaining_total = sum(remaining.values())
        remaining_hhi = (sum((n / remaining_total) ** 2 for n in remaining.values())
                         if remaining_total else None)
        backups = []
        for hero, n in ordered[1:4]:
            krow = kpl.get(hero) or {}
            backups.append({
                'hero': hero, 'games': n,
                'share': round(n / total_lane * 100, 1),
                'kplGames': krow.get('games'),
                'kplWins': krow.get('wins'),
                'kplWinRate': krow.get('winRate'),
            })
        lanes.append({
            'lane': lane, 'games': total_lane, 'heroes': len(counter),
            'effective': round(1 / hhi, 2) if hhi else None,
            'top1': {'hero': top1[0], 'games': top1[1],
                     'share': round(top1[1] / total_lane * 100, 1)},
            'top2': ({'hero': top2[0], 'games': top2[1],
                      'share': round(top2[1] / total_lane * 100, 1)}
                     if top2 else None),
            'afterTop1': {
                'games': remaining_total,
                'heroes': len(remaining),
                'effective': round(1 / remaining_hhi, 2) if remaining_hhi else None,
            },
            'backups': backups,
        })
    return {'games': total, 'lanes': lanes,
            'kplNote': 'KPL 英雄出场/胜率由五人成阵聚合，不是官方英雄榜'}
