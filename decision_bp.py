"""P1-6 BP 阵容抗针对：先看对手常禁什么，再看我方选手被禁后还剩什么。

数据：
- `data/camp_details/*.json` 的 blueTeam/redTeam.banHeros（每局双方禁 5 手）
- 同一份面板的 my-side 五名选手：姓名/分路/英雄（营地昵称，未绑定名单时按昵称）
- decision_facts 的 rows/panels/opponents 做日期、对手过滤

输出：
- `bans`：对手禁选排行（总体 / 指定对手）
- `players`：我方每名选手的英雄池、被对手常禁命中数、被禁后剩余可用池深度、
  thin 标记（剩余可用 ≤2）与补练建议
- `team`：我方与对手 ban 位重合的“弱点英雄”、本周补练建议
- `coverage/caveats`：样本与身份口径

口径：
- 只描述禁选频率，不把少量比赛的胜率当英雄强度；
- 每名对手目前多为 1 局，对手维度只做单场观察；
- 选手身份按营地昵称聚合，未绑定名单时明确提示。
"""
from __future__ import annotations

from collections import Counter, defaultdict

MIN_POOL_GAMES = 1
MIN_PLAYER_GAMES = 3
THIN_DEPTH = 2


def _filter_rows(facts, *, opponent=None, date_from=None, date_to=None):
    rows = []
    for row in facts.get('rows') or []:
        if row.get('side') != 'own':
            continue
        if opponent and row.get('opponentId') != opponent:
            continue
        if date_from and (row.get('date') or '') < date_from:
            continue
        if date_to and (row.get('date') or '') > date_to:
            continue
        rows.append(row)
    return rows


def _panel_scope(facts, *, opponent=None, date_from=None, date_to=None):
    out = []
    for seq, panel in (facts.get('panels') or {}).items():
        if opponent and facts.get('seqToOpponent', {}).get(seq) != opponent:
            continue
        if date_from and (panel.get('date') or '') < date_from:
            continue
        if date_to and (panel.get('date') or '') > date_to:
            continue
        out.append((seq, panel))
    return out


def _ban_list(panel, side):
    bans = (panel.get('bans') or {}).get(side) or []
    return [hero for hero in bans if hero]


def _player_pool(rows):
    players = {}
    for row in rows:
        name = (row.get('name') or row.get('playerId') or '').strip()
        if not name:
            continue
        lane = row.get('lane') or '未标注'
        key = (name, lane)
        player = players.setdefault(key, {
            'name': name, 'lane': lane, 'games': 0, 'wins': 0,
            'heroes': defaultdict(lambda: {'games': 0, 'wins': 0}),
            'opponents': Counter(),
        })
        player['games'] += 1
        player['wins'] += 1 if row.get('won') else 0
        player['opponents'][row.get('opponentName') or '待命名对手'] += 1
        hero = (row.get('hero') or '').strip()
        if hero:
            player['heroes'][hero]['games'] += 1
            player['heroes'][hero]['wins'] += 1 if row.get('won') else 0
    return players


def _hero_rows(player):
    heroes = []
    for hero, stat in player['heroes'].items():
        if stat['games'] < MIN_POOL_GAMES:
            continue
        heroes.append({
            'hero': hero, 'games': stat['games'],
            'winRate': round(stat['wins'] / stat['games'] * 100, 1) if stat['games'] else None,
        })
    heroes.sort(key=lambda item: (-item['games'], -(item['winRate'] or 0), item['hero']))
    return heroes


def bp_report(facts, *, opponent=None, date_from=None, date_to=None, top=8):
    """返回 BP 抗针对报告；无面板/无 ban 数据时 available=false。"""
    rows = _filter_rows(facts, opponent=opponent, date_from=date_from, date_to=date_to)
    panels = _panel_scope(facts, opponent=opponent, date_from=date_from, date_to=date_to)
    ban_counter = Counter()
    ban_opponents = defaultdict(Counter)  # hero -> opponents
    games_with_bans = 0
    for seq, panel in panels:
        enemy_side = panel.get('enemy')
        bans = _ban_list(panel, enemy_side)
        if bans:
            games_with_bans += 1
        for hero in bans:
            ban_counter[hero] += 1
            ban_opponents[hero][panel.get('opponentName') or '待命名对手'] += 1

    if not rows or not panels:
        return {
            'available': False,
            'reason': '当前数据范围没有可分析的终局面板（需要营地十人面板，含 BP 禁选）',
            'filters': {'opponent': opponent, 'from': date_from, 'to': date_to},
            'coverage': {'panelGames': len(panels), 'gamesWithBans': games_with_bans,
                         'ownRows': len(rows)},
            'caveats': [],
        }

    players = []
    all_players = _player_pool(rows)
    rotated = 0
    for (name, lane), player in all_players.items():
        if player['games'] < MIN_PLAYER_GAMES:
            rotated += 1
            continue
        heroes = _hero_rows(player)
        top_heroes = heroes[:5]
        opponent_top_bans = [hero for hero, _ in ban_counter.most_common(top)]
        banned_hits = [item for item in top_heroes if item['hero'] in opponent_top_bans]
        remaining = [item for item in heroes if item['hero'] not in opponent_top_bans]
        depth = len({item['hero'] for item in remaining})
        players.append({
            'name': name, 'lane': lane, 'games': player['games'],
            'wins': player['wins'],
            'winRate': round(player['wins'] / player['games'] * 100, 1) if player['games'] else None,
            'heroes': heroes,
            'bannedHits': [item['hero'] for item in banned_hits],
            'bannedHitCount': len(banned_hits),
            'poolDepth': depth,
            'thin': depth <= THIN_DEPTH,
            'recommendations': [item['hero'] for item in remaining[:3]],
            'topHero': heroes[0]['hero'] if heroes else '',
            'opponents': [name for name, _ in player['opponents'].most_common(3)],
        })
    players.sort(key=lambda item: (
        0 if item['thin'] else 1, -item['bannedHitCount'], item['poolDepth'], item['lane'], item['name']))

    # 本批我方轮换很多（大量只打 1 局的试训/临时队员），按分路做稳定英雄池，
    # 个人页只保留 ≥MIN_PLAYER_GAMES 局的稳定样本，避免把 100 多个一次性昵称当成主力。
    lane_rows = defaultdict(list)
    for row in rows:
        lane_rows[row.get('lane') or '未标注'].append(row)
    lane_order = ['对抗路', '打野', '中路', '发育路', '游走', '未标注']
    lanes = []
    for lane in sorted(lane_rows, key=lambda item: lane_order.index(item) if item in lane_order else 99):
        items = lane_rows[lane]
        hero_stats = defaultdict(lambda: {'games': 0, 'wins': 0})
        for row in items:
            hero = (row.get('hero') or '').strip()
            if not hero:
                continue
            hero_stats[hero]['games'] += 1
            hero_stats[hero]['wins'] += 1 if row.get('won') else 0
        heroes = [{
            'hero': hero, 'games': stat['games'],
            'winRate': round(stat['wins'] / stat['games'] * 100, 1) if stat['games'] else None,
        } for hero, stat in hero_stats.items() if stat['games'] >= MIN_POOL_GAMES]
        heroes.sort(key=lambda item: (-item['games'], -(item['winRate'] or 0), item['hero']))
        opponent_top_bans = [hero for hero, _ in ban_counter.most_common(top)]
        banned_hits = [item['hero'] for item in heroes[:5] if item['hero'] in opponent_top_bans]
        remaining = [item for item in heroes if item['hero'] not in opponent_top_bans]
        depth = len({item['hero'] for item in remaining})
        lanes.append({
            'lane': lane, 'games': len(items),
            'players': len({row.get('name') for row in items if row.get('name')}),
            'heroes': heroes,
            'bannedHits': banned_hits,
            'bannedHitCount': len(banned_hits),
            'poolDepth': depth,
            'thin': depth <= THIN_DEPTH,
            'recommendations': [item['hero'] for item in remaining[:3]],
        })

    own_heroes = Counter()
    for row in rows:
        if row.get('hero'):
            own_heroes[row['hero']] += 1
    weak = []
    for hero, count in own_heroes.most_common(20):
        ban_count = ban_counter.get(hero, 0)
        if ban_count:
            weak.append({
                'hero': hero, 'ownGames': count, 'bannedGames': ban_count,
                'share': round(ban_count / max(1, games_with_bans) * 100, 1),
                'opponents': [name for name, _ in ban_opponents[hero].most_common(3)],
            })
    weak.sort(key=lambda item: (-item['bannedGames'], -item['ownGames']))

    thin_players = [item for item in players if item['thin']]
    thin_lanes = [item for item in lanes if item['thin']]
    suggestions = []
    if thin_lanes:
        names = '、'.join(item['lane'] for item in thin_lanes[:3])
        suggestions.append(f"按分路看，{names} 被对手常禁后可用英雄只剩 ≤{THIN_DEPTH} 个，优先补这几个位置的替代英雄。")
    if thin_players:
        names = '、'.join(f"{item['name']}（{item['lane']}）" for item in thin_players[:3])
        suggestions.append(f"稳定样本里 {names} 的可 Ban 英雄集中，赛前准备至少一套不依赖其常用英雄的阵容。")
    if weak:
        suggestions.append('对手常禁我方常用英雄：' +
                           '、'.join(f"{item['hero']}（禁 {item['bannedGames']} 局）" for item in weak[:3]) +
                           '；赛前准备至少一套不依赖这些英雄的阵容。')

    return {
        'available': True,
        'filters': {'opponent': opponent, 'from': date_from, 'to': date_to},
        'coverage': {
            'panelGames': len(panels),
            'gamesWithBans': games_with_bans,
            'ownRows': len(rows),
            'players': len(players),
            'rotatedPlayers': rotated,
            'lanes': len(lanes),
            'opponents': len({row.get('opponentId') for row in rows if row.get('opponentId')}),
        },
        'bans': {
            'overall': [{
                'hero': hero, 'games': count,
                'share': round(count / max(1, games_with_bans) * 100, 1),
                'opponents': [name for name, _ in ban_opponents[hero].most_common(3)],
            } for hero, count in ban_counter.most_common(top)],
            'byOpponent': [
                {'opponent': item.get('name'), 'id': item.get('id'),
                 'replayGames': item.get('replayGames'), 'enough': (item.get('replayGames') or 0) >= 3}
                for item in facts.get('opponents') or []
                if not opponent or item.get('id') == opponent
            ][:20],
        },
        'lanes': lanes,
        'players': players,
        'team': {'weakHeroes': weak[:8], 'suggestions': suggestions,
                 'thinLanes': [item['lane'] for item in thin_lanes],
                 'thinPlayers': len(thin_players)},
        'caveats': [
            '禁选来自营地终局面板；当前每名对手大约 1 局，对手 Ban 习惯只做单场观察，不能当稳定套路。',
            f'本批我方轮换较多（{rotated} 个只打 <{MIN_PLAYER_GAMES} 局的昵称未单独列出），'
            '选手按营地昵称 + 分路聚合；未绑定名单时可能同名合并，补练建议只基于本批英雄出场，不等于英雄强度。',
            'BP 手序仅部分对局有记录，本页不推断先后手。',
        ],
    }
