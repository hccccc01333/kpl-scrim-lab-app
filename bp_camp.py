"""营地 battledetail → 结构化 BP 名单（含本地英雄头像与分路）。

口径（2026-11-18 教练确认）：赛后数据里每方 Ban/Pick 名单就是最终手序，
**不需要人工录入**。本模块按 `bp_formats` 判定的格式（征召 18 / KPL 18|20 /
排位·巅峰 20）把每侧名单直接铺成 `draftEvents`，并写 `ruleProfile=<format>`；
数量与格式不符只标 `orderPending`，不改写名单、不伪造顺序。

"""
from __future__ import annotations

import json
import re
from pathlib import Path
from time import monotonic

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


def _icon_dir_stamp():
    try:
        return ICON_DIR.stat().st_mtime_ns
    except OSError:
        return None


# 静态资源联合指纹（catalog.json / hero-lanes.js / 头像目录）。三者都是随程序
# 发布的文件，不跟对局变化，所以最多每 _STATIC_TTL 秒校验一次；指纹一变就丢掉
# 条目缓存，最多 2 秒后生效——和 v3 的对局包指纹同样的新鲜度口径。
#
# 为什么必须这样做：一次 hero_entry 要 stat 三个文件，本机一次 stat 约 90µs
# （资源盘 + 杀软过滤驱动）。一页 BP 名单是上万条 hero_entry，光这三行校验
# 就占 1–2 秒：剖析里 /api/bp 的 2.7 秒有 2.0 秒是 nt.stat。
_STATIC_TTL = 2.0
_STATIC_STAMP = {'at': float('-inf'), 'value': None}
_ENTRY_CACHE = {}
_ENTRY_CACHE_MAX = 8192


def _static_stamp():
    now = monotonic()
    if now - _STATIC_STAMP['at'] < _STATIC_TTL:
        return _STATIC_STAMP['value']
    value = (_stamp(CATALOG_PATH), _stamp(LANES_JS), _icon_dir_stamp())
    if value != _STATIC_STAMP['value']:
        _ENTRY_CACHE.clear()
    _STATIC_STAMP.update(at=now, value=value)
    return value


def hero_entry(name, hero_id=None, icon=None, lane=None):
    """统一条目：{name, id, icon, lane}。

    结果按入参记忆：同样的（名字, id, 远程图, 分路）在 2 秒窗口内只解析一次，
    调用方拿到的是一份浅拷贝，改自己的条目不会污染缓存。
    """
    name = str(name or '').strip()
    if not name:
        return None
    key = (name, str(hero_id) if hero_id not in (None, '') else None,
           icon or None, lane or None)
    _static_stamp()
    cached = _ENTRY_CACHE.get(key)
    if cached is not None:
        return dict(cached)
    meta = catalog_meta().get(name) or {}
    hid = key[1] or meta.get('id')
    # 本地头像优先，营地远程 heroIcon 只在本地图标库缺该英雄时兜底。
    entry = {
        'name': name,
        'id': hid,
        'icon': hero_icon(hid) or meta.get('icon') or icon,
        'lane': lane or static_lanes().get(name),
    }
    if len(_ENTRY_CACHE) >= _ENTRY_CACHE_MAX:
        _ENTRY_CACHE.clear()
    _ENTRY_CACHE[key] = entry
    return dict(entry)


def events_from_lists(bans, picks, fmt):
    """按规则排程把每侧有序 Ban/Pick 名单铺成逐手事件。

    不再要求手工录入：营地名单本身就是每方手序，格式由 ``fmt`` 决定。
    数量不符、有重复/交叉时返回 ``[]``，由调用方标「名单不完整」。
    """
    queues = {}
    for side, camp in (('left', '1'), ('right', '2')):
        ban_names = [str(entry.get('name') if isinstance(entry, dict) else entry or '').strip()
                     for entry in (bans.get(side) or [])]
        pick_names = [str(entry.get('name') if isinstance(entry, dict) else entry or '').strip()
                      for entry in (picks.get(side) or [])]
        if (len(ban_names) != fmt.bans_per_side[camp]
                or len(pick_names) != fmt.picks_per_side[camp]
                or any(not name for name in ban_names + pick_names)):
            return []
        queues[camp] = {'ban': list(ban_names), 'pick': list(pick_names)}
    events = []
    for step in fmt.schedule:
        queue = queues[step['camp']][step['action']]
        if not queue:
            return []
        events.append({'order': step['order'], 'phase': step['phase'],
                       'action': step['action'], 'camp': step['camp'],
                       'hero': queue.pop(0),
                       'parallel': bool(step.get('parallel'))})
    return events


def camp_format(map_name, bans):
    """营地记录 → 格式。排位/巅峰 → rank-20；4 Ban/方 → draft-18；5 Ban/方 → draft-20。

    两边 Ban 数不一致（采集不完整）时仍按地图名和较大的一边给出格式，
    只用于标记规则与「待补录」，不生成事件。
    """
    from bp_formats import DRAFT_18, DRAFT_20, RANK_20
    text = str(map_name or '')
    counts = [len((bans or {}).get(side) or []) for side in ('left', 'right')]
    if '排位' in text or '巅峰' in text:
        return RANK_20
    if counts[0] == counts[1] == 4:
        return DRAFT_18
    if max(counts or [0]) >= 5:
        return DRAFT_20
    return DRAFT_18


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

    注意：空 ban 占位为 None，不压缩后面的位置；营地名单按规则自动铺成逐手。
    使用（教练 2026-11-15 确认），空位不参与事件生成。
    """
    result = []
    for item in items or []:
        entry = normalize_entries([item], lanes)
        result.append(entry[0] if entry else None)
    return result


def rule_id_for_bp(bp):
    """营地记录 → 规则 id。

    新记录直接带 ``ruleProfile``（draft-18 / draft-20 / rank-20）；
    旧记录按地图名与 Ban 数判定，不再默认 20 手。
    """
    from bp_formats import FORMATS
    profile = str((bp or {}).get('ruleProfile') or '').strip()
    if profile in FORMATS:
        return profile
    return camp_format((bp or {}).get('mapName'), (bp or {}).get('bans') or {}).id


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
    map_name = (head.get('mapName') or battle.get('mapName')
                or (entry_meta or {}).get('mapName'))
    fmt = camp_format(map_name, bans)
    source_events = []
    order_source = ''
    raw_events = data.get('draftEvents') or data.get('bpSequence') or []
    if isinstance(raw_events, list) and len(raw_events) == fmt.total_hands:
        source_events = raw_events
        order_source = 'draftEvents'
    if not source_events:
        source_events = events_from_lists(bans, picks, fmt)
        if source_events:
            order_source = f'campDefault:{fmt.id}'
    try:
        duration = int(float(battle.get('usedTime') or 0)) or None
    except (TypeError, ValueError):
        duration = None
    return {
        'source': SOURCE,
        'gameSeq': str(game_seq or ''),
        'mapName': map_name,
        'duration': duration,
        'startTime': battle.get('startTime') or '',
        'winnerSide': _winner_side(data),
        'ownSide': _own_side(data),
        'bans': bans,
        'picks': picks,
        'banSlots': ban_slots,
        'pickSlots': pick_slots,
        # 顺序不再手工录入：营地每方名单就是手序，按 fmt 的排程自动铺成逐手事件。
        'draftEvents': source_events,
        'bpOrder': None,
        'ruleProfile': fmt.id,
        'pickOrderKnown': bool(source_events),
        'firstPick': next((('left' if event['camp'] == '1' else 'right')
                           for event in source_events if event.get('action') == 'pick'), None),
        'orderSource': order_source,
        'orderAssumed': order_source.startswith('campDefault:'),
        'orderPending': not bool(source_events),
        'lanes': lanes,
        'heroMeta': heroes,
        'teamStats': {'left': _team_stats(blue), 'right': _team_stats(red)},
        'banCount': {'left': len(bans['left']), 'right': len(bans['right'])},
    }


def clean_scrim_events(events):
    """逐手事件的形状归一化：camp 别名、order 连续递增、action/hero 合法。"""
    if not isinstance(events, list) or not events:
        raise ValueError('缺少逐手选禁事件')
    clean = []
    for idx, event in enumerate(events):
        if not isinstance(event, dict):
            raise ValueError('逐手事件必须是对象')
        action = str(event.get('action') or '').lower()
        hero = str(event.get('hero') or '').strip()
        camp = str(event.get('camp') or '').lower()
        camp = {'left': '1', 'blue': '1', 'right': '2', 'red': '2'}.get(camp, camp)
        raw_order = event.get('order', idx + 1)
        if isinstance(raw_order, bool):
            raise ValueError('order 不能是布尔值')
        try:
            order = int(raw_order)
        except (TypeError, ValueError) as error:
            raise ValueError('order 必须是整数') from error
        if action not in ('pick', 'ban') or camp not in ('1', '2') or not hero:
            raise ValueError('事件缺少 action/hero/camp 或取值非法')
        clean.append({'order': order, 'action': action, 'hero': hero, 'camp': camp})
    clean.sort(key=lambda event: event['order'])
    if any(event['order'] != idx + 1 for idx, event in enumerate(clean)):
        raise ValueError('order 必须从 1 连续递增')
    return clean


def apply_order_events(record, events):
    """把逐手事件套到名单记录上；对不齐就原样返回（保持顺序未知）。

    事件按记录自己的 ``ruleProfile`` 校验（draft-18 / draft-20 / rank-20），
    且每侧 Pick/Ban 与终局名单逐一对上。任何一处对不齐都不改记录。
    """
    if not record or not events:
        return record
    from bp_formats import FORMATS, get_format
    rule_id = rule_id_for_bp(record)
    if rule_id not in FORMATS:
        return record
    fmt = get_format(rule_id)
    try:
        clean = clean_scrim_events(events)
    except ValueError:
        return record
    if len(clean) != fmt.total_hands:
        return record
    side_of = {'1': 'left', '2': 'right'}
    ordered = {camp: {'pick': [], 'ban': []} for camp in ('1', '2')}
    for event in clean:
        ordered[event['camp']][event['action']].append(event['hero'])
    picks = {side: list((record.get('picks') or {}).get(side) or [])
             for side in ('left', 'right')}
    bans = {side: list((record.get('bans') or {}).get(side) or [])
            for side in ('left', 'right')}
    for camp, side in side_of.items():
        for kind, target in (('pick', picks), ('ban', bans)):
            rows = {entry['name']: entry for entry in target[side]}
            names = ordered[camp][kind]
            # 事件与终局名单必须一一对上（数量与英雄集合都一致）。
            if len(names) != len(target[side]) or any(name not in rows for name in names):
                return record
            target[side] = [rows[name] for name in names]
    first = next((event for event in clean if event['action'] == 'pick'), None)
    if first is None:
        return record
    out = dict(record)
    out['picks'] = picks
    out['bans'] = bans
    out['pickOrderKnown'] = True
    out['banOrderKnown'] = True
    out['firstPick'] = side_of[first['camp']]
    out['orderSource'] = 'draftEvents'
    out['draftEvents'] = clean
    # 槽位数组跟着手序一起排；有空位（None）对不齐时保持原样。
    for kind_key, slot_key in (('picks', 'pickSlots'), ('bans', 'banSlots')):
        slots = record.get(slot_key)
        if not isinstance(slots, dict):
            continue
        aligned = {}
        for side in ('left', 'right'):
            rows = slots.get(side) or []
            names = [entry['name'] for entry in out[kind_key][side]]
            if len(rows) != len(names) or any(not isinstance(row, dict) for row in rows):
                aligned = None
                break
            by_name = {row.get('name'): row for row in rows}
            if any(name not in by_name for name in names):
                aligned = None
                break
            aligned[side] = [by_name[name] for name in names]
        if aligned:
            out[slot_key] = aligned
    return out


def apply_default_scrim_order(record):
    """营地名单顺序 → 逐手事件（按记录自己的格式）。

    无手工录入：营地每方 ban/pick 名单就是手序；数量与格式不符时保持
    顺序未知（采集不完整，不猜）。
    """
    if not record or record.get('source') != 'camp' or record.get('pickOrderKnown'):
        return record
    from bp_formats import FORMATS, get_format
    rule_id = rule_id_for_bp(record)
    if rule_id not in FORMATS:
        return record
    fmt = get_format(rule_id)
    events = events_from_lists(record.get('bans') or {}, record.get('picks') or {}, fmt)
    if not events:
        return record
    first = next((event for event in events if event['action'] == 'pick'), None)
    out = dict(record)
    out['draftEvents'] = events
    out['ruleProfile'] = fmt.id
    out['pickOrderKnown'] = True
    out['banOrderKnown'] = True
    out['firstPick'] = ('left' if first and first['camp'] == '1' else 'right') if first else None
    out['orderSource'] = f'campDefault:{fmt.id}'
    out['orderAssumed'] = True
    out['bpOrderMode'] = fmt.id
    return out


def stamp_camp_order(detail):
    """在源头把营地名单顺序写成逐手 draftEvents（按自动判定的格式）。

    用于 camp_sync 入库：名单数量与格式相符才生成；不符只标 ``orderPending``，
    不伪造顺序，也不再要求人工补录。
    """
    bp = parse_camp_bp(detail)
    if not bp:
        return detail
    data = _data_of(detail)
    if not isinstance(data, dict):
        return detail
    data['ruleProfile'] = bp.get('ruleProfile') or 'unknown'
    events = bp.get('draftEvents') or []
    if events:
        data['draftEvents'] = events
        data['bpOrderSource'] = bp.get('orderSource') or 'source'
        data.pop('orderPending', None)
    else:
        data['orderPending'] = True
    return detail


def merge_bp_sources(manual, camp, match=None, events=None, order=None,
                     assume_scrim=False):
    """统一人工手序 BP 与营地名单 BP：人工优先，营地兜底，来源不混算。

    返回 None 表示这局没有任何 BP 记录。人工录入的 picks 被视为 1–5 楼有序；
    顺序 = 营地每方名单按规则自动铺开；页面手工顺序已移除，``bpOrder`` 只作旧字段忽略。
    ``assume_scrim`` 保留
    只为兼容旧调用，不再改变行为。
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
        source, order_known, ban_order_known = 'manual', True, True
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
        source, order_known, ban_order_known = 'camp', False, False
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
    record = {
        'source': source,
        'bans': bp['bans'], 'picks': bp['picks'],
        'banSlots': ban_slots, 'pickSlots': pick_slots,
        'pickOrderKnown': order_known, 'banOrderKnown': ban_order_known,
        'firstPick': first_pick,
        'ruleProfile': (camp or {}).get('ruleProfile') or (
            'draft-18' if source == 'manual' else 'unknown'),
        'heroMeta': meta,
        'lanes': (camp.get('lanes') or {}) if isinstance(camp, dict) else {},
        'winnerSide': side_map.get((camp or {}).get('winnerSide')) or side_map.get(match.get('winnerCamp')),
        'ownSide': side_map.get((camp or {}).get('ownSide')) or side_map.get(match.get('ownCamp')),
        'gameSeq': (camp or {}).get('gameSeq') or '',
        'mapName': (camp or {}).get('mapName') or match.get('mode') or '',
        'duration': (camp or {}).get('duration') or match.get('duration'),
        'teamStats': (camp or {}).get('teamStats') or {},
    }
    if source == 'camp':
        # 顺序 = 营地名单按规则铺开；不接受手工顺序，也不再拿名单反推。
        verified = events if events is not None else (
            (camp or {}).get('draftEvents') if isinstance(camp, dict) else [])
        record = apply_order_events(record, verified)
        camp_order_source = str((camp or {}).get('orderSource') or '')
        if (events is None and record.get('pickOrderKnown')
                and camp_order_source.startswith('campDefault:')):
            record['orderSource'] = camp_order_source
            record['orderAssumed'] = True
        if not record.get('pickOrderKnown') and not verified:
            record = apply_default_scrim_order(record)
    return record


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
