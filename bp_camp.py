"""营地 battledetail → 结构化 BP 名单（含本地英雄头像与分路）。

口径：营地返回的是**终局名单**（谁被禁、谁上场），不含 pick 手序、不含
一手方，ban 数量随模式变化（排位 5 ban / 训练赛征召 4 ban）。本模块只产出
「名单类」BP 数据，供 analysis_data.bp_summary 与 BP 页消费；1–5 楼手序、
先后手仍然只认比赛校对页的人工录入（bp_input.validate_bp）。
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ICON_DIR = ROOT / 'resources' / 'icons'
CATALOG_PATH = ROOT / 'resources' / 'catalog.json'
LANES_JS = ROOT / 'web' / 'hero-lanes.js'

# 营地 battleRecords.position：31 局实测
# 0=对抗路 / 1=中路 / 2=发育路 / 3=打野 / 4=游走（按该位置高频英雄核对）
POSITION_LANES = {0: '对抗路', 1: '中路', 2: '发育路', 3: '打野', 4: '游走'}
SOURCE = 'camp-battledetail'


@lru_cache(maxsize=1)
def catalog_index():
    """({name → {id, icon}}, {id → name})，让人工名与只有 heroId 的营地条目互通。"""
    meta, by_id = {}, {}
    try:
        entries = json.loads(CATALOG_PATH.read_text(encoding='utf-8')).get('entries') or []
    except (OSError, ValueError):
        return meta, by_id
    for entry in entries:
        if entry.get('kind') != 'hero' or not entry.get('name'):
            continue
        name = str(entry['name'])
        hid = str(entry.get('id', '')).replace('hero-', '') or None
        meta[name] = {'id': hid, 'icon': entry.get('icon') or None}
        if hid:
            by_id[hid] = name
    return meta, by_id


def catalog_meta():
    return catalog_index()[0]


def catalog_name(hero_id):
    return catalog_index()[1].get(str(hero_id))


@lru_cache(maxsize=1)
def static_lanes():
    """复用前端 BP 录入的「英雄→主分路」参考表，给从未出场的禁用英雄补分路。"""
    try:
        text = LANES_JS.read_text(encoding='utf-8')
    except OSError:
        return {}
    result = {}
    for name, values in re.findall(r"'([^']+)'\s*:\s*\[([^\]]*)\]", text):
        lanes = re.findall(r"'([^']+)'", values)
        if lanes:
            result[name] = lanes[0]
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
        bp = {
            'bans': {side: normalize_entries(names['bans'][side]) for side in ('left', 'right')},
            'picks': {side: normalize_entries(names['picks'][side]) for side in ('left', 'right')},
        }
        source, order_known = 'manual', True
        first_pick = manual.get('firstPick') or None
    elif has_heroes(camp):
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
