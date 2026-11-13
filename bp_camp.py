"""营地 battledetail → 结构化 BP 名单（含本地英雄头像与分路）。

口径：营地返回的是**终局名单**（谁被禁、谁上场），不含 pick 手序、不含
一手方，ban 数量随模式变化（排位 5 ban / 训练赛征召 4 ban）。本模块只产出
「名单类」BP 数据，供 analysis_data.bp_summary 与 BP 页消费；1–5 楼手序、
先后手仍然只认比赛校对页的人工录入（bp_input.validate_bp）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ICON_DIR = ROOT / 'resources' / 'icons'
CATALOG_PATH = ROOT / 'resources' / 'catalog.json'
LANES_JS = ROOT / 'web' / 'hero-lanes.js'

# 营地 battleRecords.position：31 局实测
# 0=对抗路 / 1=中路 / 2=发育路 / 3=打野 / 4=游走（按该位置高频英雄核对）
POSITION_LANES = {0: '对抗路', 1: '中路', 2: '发育路', 3: '打野', 4: '游走'}
SOURCE = 'camp-battledetail'


_CATALOG_CACHE = {'stamp': object(), 'value': ({}, {})}
_LANES_CACHE = {'stamp': object(), 'value': {}}


def _stamp(path):
    """文件 mtime；不存在时返回 None（不是 0，避免与「刚写入」混淆）。"""
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


def catalog_index():
    """({name → {id, icon}}, {id → name})，让人工名与只有 heroId 的营地条目互通。

    按文件 mtime 缓存：catalog.json 更新后不必重启进程就能读到新英雄。
    """
    stamp = _stamp(CATALOG_PATH)
    if stamp is not None and _CATALOG_CACHE['stamp'] == stamp:
        return _CATALOG_CACHE['value']
    meta, by_id = {}, {}
    try:
        entries = json.loads(CATALOG_PATH.read_text(encoding='utf-8')).get('entries') or []
    except (OSError, ValueError):
        entries = []
    for entry in entries:
        if entry.get('kind') != 'hero' or not entry.get('name'):
            continue
        name = str(entry['name'])
        hid = str(entry.get('id', '')).replace('hero-', '') or None
        meta[name] = {'id': hid, 'icon': entry.get('icon') or None}
        if hid:
            by_id[hid] = name
    if stamp is not None:
        _CATALOG_CACHE.update({'stamp': stamp, 'value': (meta, by_id)})
    return meta, by_id


def catalog_meta():
    return catalog_index()[0]


def catalog_name(hero_id):
    return catalog_index()[1].get(str(hero_id))


def static_lanes():
    """复用前端 BP 录入的「英雄→主分路」参考表，给从未出场的禁用英雄补分路。

    同样按 mtime 缓存：hero-lanes.js 改完立即生效。
    """
    stamp = _stamp(LANES_JS)
    if stamp is not None and _LANES_CACHE['stamp'] == stamp:
        return _LANES_CACHE['value']
    try:
        text = LANES_JS.read_text(encoding='utf-8')
    except OSError:
        return {}
    result = {}
    for name, values in re.findall(r"'([^']+)'\s*:\s*\[([^\]]*)\]", text):
        lanes = re.findall(r"'([^']+)'", values)
        if lanes:
            result[name] = lanes[0]
    if stamp is not None:
        _LANES_CACHE.update({'stamp': stamp, 'value': result})
    return result


def hero_icon(hero_id):
    """优先本地头像库，避免工作台依赖外网。"""
    if hero_id in (None, ''):
        return None
    path = ICON_DIR / f'hero-{hero_id}.png'
    return f'/catalog/icons/hero-{hero_id}.png' if path.is_file() else None


def hero_entry(name, hero_id=None, icon=None, lane=None):
    """统一条目：{name, id, icon, lane}。"""
    name = str(name or '').strip()
    if not name:
        return None
    meta = catalog_meta().get(name) or {}
    hid = str(hero_id) if hero_id not in (None, '') else meta.get('id')
    # 本地头像优先，营地远程 heroIcon 只在本地图标库缺该英雄时兜底。
    return {
        'name': name,
        'id': hid,
        'icon': hero_icon(hid) or meta.get('icon') or icon,
        'lane': lane or static_lanes().get(name),
    }


def normalize_entries(items, lanes=None):
    """营地 banHeros / pickHeros 或已经规范化的条目 → 统一条目列表。"""
    result, seen = [], set()
    for item in items or []:
        if isinstance(item, str):
            entry = hero_entry(item, lane=(lanes or {}).get(item))
        elif isinstance(item, dict):
            hid = item.get('id') or item.get('heroId')
            name = (item.get('name') or item.get('heroName')
                    or catalog_name(hid) or '')
            entry = hero_entry(name, hid,
                               item.get('icon') or item.get('heroIcon'),
                               item.get('lane') or (lanes or {}).get(name))
        else:
            continue
        if not entry or entry['name'] in seen:
            continue
        seen.add(entry['name'])
        result.append(entry)
    return result


def slot_entries(items, lanes=None):
    """保留槽位的规范化：空 ban 占位为 None，不压缩后面的位置。

    营地 banHeros / pickHeros 数组下标就是该侧手序；排位赛会有空 ban，
    解析层必须保留空位，否则首 ban、第几手 ban 会整体前移。
    """
    result = []
    for item in items or []:
        entry = normalize_entries([item], lanes)
        result.append(entry[0] if entry else None)
    return result


def _data_of(detail):
    if not isinstance(detail, dict):
        return {}
    if isinstance(detail.get('data'), dict):
        return detail['data']
    body = detail.get('body')
    if isinstance(body, dict) and isinstance(body.get('data'), dict):
        return body['data']
    return {}


def _lane_map(data):
    """英雄 → 实测主分路：按本批营地 battleRecords.position 的众数。"""
    counts = {}
    for key in ('blueRoles', 'redRoles'):
        for role in data.get(key) or []:
            record = role.get('battleRecords') or {}
            name = (record.get('usedHero') or {}).get('heroName')
            try:
                lane = POSITION_LANES[int(record.get('position'))]
            except (TypeError, ValueError, KeyError):
                continue
            if name:
                counts.setdefault(str(name), {})
                counts[str(name)][lane] = counts[str(name)].get(lane, 0) + 1
    return {name: max(lanes, key=lanes.get) for name, lanes in counts.items()}


def _winner_side(data):
    for team_key, side in (('blueTeam', 'left'), ('redTeam', 'right')):
        team = data.get(team_key) or {}
        if team.get('gameResult') is True:
            return side
    head = data.get('head') or {}
    camp = str(head.get('acntCamp') or '')
    if head.get('gameResult') is True and camp in ('1', '2'):
        return 'left' if camp == '1' else 'right'
    if head.get('gameResult') is False and camp in ('1', '2'):
        return 'right' if camp == '1' else 'left'
    return None


def _own_side(data):
    camp = str((data.get('head') or {}).get('acntCamp') or '')
    return {'1': 'left', '2': 'right'}.get(camp)


def _team_stats(team):
    keys = ('money', 'killCnt', 'deadCnt', 'assistCnt', 'towerCnt',
            'ldragon1', 'ldragon2', 'bdragon1', 'bdragon2', 'bdragon3')
    result = {}
    for key in keys:
        value = team.get(key)
        try:
            result[key] = int(float(value))
        except (TypeError, ValueError):
            pass
    result['win'] = team.get('gameResult') is True
    return result


def parse_camp_bp(detail, game_seq=None):
    """把一局营地详情解析为名单口径的 BP 记录；没有 ban/pick 时返回 None。"""
    data = _data_of(detail)
    if not data:
        return None
    blue, red = data.get('blueTeam') or {}, data.get('redTeam') or {}
    lanes = _lane_map(data)
    bans = {'left': normalize_entries(blue.get('banHeros'), lanes),
            'right': normalize_entries(red.get('banHeros'), lanes)}
    picks = {'left': normalize_entries(blue.get('pickHeros'), lanes),
             'right': normalize_entries(red.get('pickHeros'), lanes)}
    ban_slots = {'left': slot_entries(blue.get('banHeros'), lanes),
                 'right': slot_entries(red.get('banHeros'), lanes)}
    pick_slots = {'left': slot_entries(blue.get('pickHeros'), lanes),
                  'right': slot_entries(red.get('pickHeros'), lanes)}
    if not any(bans.values()) and not any(picks.values()):
        return None
    heroes = {}
    for group in (bans, picks):
        for entries in group.values():
            for entry in entries:
                heroes[entry['name']] = {'id': entry['id'], 'icon': entry['icon'],
                                        'lane': entry['lane']}
    battle = data.get('battle') or {}
    head = data.get('head') or {}
    entry_meta = detail.get('_campEntry') if isinstance(detail, dict) else None
    try:
        duration = int(float(battle.get('usedTime') or 0)) or None
    except (TypeError, ValueError):
        duration = None
    return {
        'source': SOURCE,
        'gameSeq': str(game_seq or ''),
        'mapName': head.get('mapName') or battle.get('mapName') or (entry_meta or {}).get('mapName'),
        'duration': duration,
        'startTime': battle.get('startTime') or '',
        'winnerSide': _winner_side(data),
        'ownSide': _own_side(data),
        'bans': bans,
        'picks': picks,
        'banSlots': ban_slots,
        'pickSlots': pick_slots,
        'lanes': lanes,
        'heroMeta': heroes,
        'teamStats': {'left': _team_stats(blue), 'right': _team_stats(red)},
        'banCount': {'left': len(bans['left']), 'right': len(bans['right'])},
        'pickOrderKnown': False,
        'firstPick': None,
    }


def merge_bp_sources(manual, camp, match=None):
    """统一人工手序 BP 与营地名单 BP：人工优先，营地兜底，来源不混算。

    返回 None 表示这局没有任何 BP 记录。人工录入的 picks 被视为 1–5 楼有序；
    营地 picks 只是终局阵容，pickOrderKnown=False，不参与手序类统计。
    """
    match = match or {}

    def has_heroes(bp):
        return isinstance(bp, dict) and any(
            value for kind in ('bans', 'picks')
            for values in (bp.get(kind) or {}).values() for value in values)

    if has_heroes(manual):
        names = structured_names(manual)
        raw_names = names
        bp = {
            'bans': {side: normalize_entries(names['bans'][side]) for side in ('left', 'right')},
            'picks': {side: normalize_entries(names['picks'][side]) for side in ('left', 'right')},
        }
        source, order_known = 'manual', True
        first_pick = manual.get('firstPick') or None
    elif has_heroes(camp):
        raw_names = structured_names(camp)
        bp = {
            'bans': {side: normalize_entries((camp.get('bans') or {}).get(side),
                                             camp.get('lanes'))
                     for side in ('left', 'right')},
            'picks': {side: normalize_entries((camp.get('picks') or {}).get(side),
                                              camp.get('lanes'))
                      for side in ('left', 'right')},
        }
        source, order_known = 'camp', False
        first_pick = None
    else:
        return None

    lanes_map = (camp.get('lanes') or {}) if isinstance(camp, dict) else {}

    def slot_from_names(items):
        result = []
        for name in items or []:
            text = str(name or '').strip()
            result.append(hero_entry(text, lane=lanes_map.get(text)) if text else None)
        return result

    camp_slots = isinstance(camp, dict) and isinstance(camp.get('banSlots'), dict)
    if source == 'camp' and camp_slots:
        ban_slots = camp.get('banSlots') or {}
        pick_slots = camp.get('pickSlots') or {}
    else:
        ban_slots = {side: slot_from_names(raw_names['bans'][side]) for side in ('left', 'right')}
        pick_slots = {side: slot_from_names(raw_names['picks'][side]) for side in ('left', 'right')}

    meta = {}
    for group in (bp['bans'], bp['picks']):
        for entries in group.values():
            for entry in entries:
                meta[entry['name']] = {'id': entry['id'], 'icon': entry['icon'],
                                      'lane': entry['lane']}
    camp_meta = (camp.get('heroMeta') or {}) if isinstance(camp, dict) else {}
    for name, value in camp_meta.items():
        merged = dict(value or {})
        if name in meta:
            merged['lane'] = meta[name].get('lane') or merged.get('lane')
            meta[name] = {**meta[name], **{k: v for k, v in merged.items() if v}}
        else:
            meta.setdefault(name, merged)
    side_map = {'blue': 'left', 'red': 'right', 'left': 'left', 'right': 'right'}
    return {
        'source': source,
        'bans': bp['bans'], 'picks': bp['picks'],
        'banSlots': ban_slots, 'pickSlots': pick_slots,
        'pickOrderKnown': order_known, 'firstPick': first_pick,
        'heroMeta': meta,
        'lanes': (camp.get('lanes') or {}) if isinstance(camp, dict) else {},
        'winnerSide': side_map.get((camp or {}).get('winnerSide')) or side_map.get(match.get('winnerCamp')),
        'ownSide': side_map.get((camp or {}).get('ownSide')) or side_map.get(match.get('ownCamp')),
        'gameSeq': (camp or {}).get('gameSeq') or '',
        'mapName': (camp or {}).get('mapName') or match.get('mode') or '',
        'duration': (camp or {}).get('duration') or match.get('duration'),
        'teamStats': (camp or {}).get('teamStats') or {},
    }


def structured_names(bp):
    """名单口径 → 旧的 {bans:{left:[name]}, picks:{...}} 形状，便于兼容展示。"""
    if not isinstance(bp, dict):
        return {'bans': {'left': [], 'right': []}, 'picks': {'left': [], 'right': []}}
    return {kind: {side: [item['name'] if isinstance(item, dict) else str(item)
                          for item in (bp.get(kind) or {}).get(side, [])]
                   for side in ('left', 'right')}
            for kind in ('bans', 'picks')}



# ===========================================================================
# Merged from merged module (bp_counter)
# ===========================================================================

"""P1-6 BP 阵容抗针对：先看对手常禁什么，再看我方选手被禁后还剩什么。

数据：
- `data/camp_details/*.json` 的 blueTeam/redTeam.banHeros（每局双方禁 5 手）
- 同一份面板的 my-side 五名选手：姓名/分路/英雄（营地昵称，未绑定名单时按昵称）
- facts 的 rows/panels/opponents 做日期、对手过滤

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
