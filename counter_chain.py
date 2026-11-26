"""应对分析：按 BP 楼层顺序逐层推演「触发 → 回应」。

无策 BP 的应对分析只给「蓝方 1L → 红方 1L+2L」一条链，且固定阵营、
不筛战队、不看 BO 赛制。这里按同样的楼层口径展开成完整链条，并补上：

* 战队筛选（本队 + 对手）；
* 我方蓝方 / 我方红方（``side='1'|'2'``）；
* BO3 / BO5 / BO7（由 ``bp_types.infer_bo`` 推导，训练赛没登记赛制就不猜）。

口径：每方 5 手 Pick 用各自数组下标（``picks[0]`` 是该方第 1 手），
不把 Ban 数组顺序当全局先后；只有已核验手序的局参与逐层推演。
本模块只算证据，不碰展示、不读写文件。
"""
from __future__ import annotations

from collections import Counter, defaultdict

from bp_formats import pick_key
from bp_types import infer_bo

# (key, 展示名, 归属阵营, 取该方第几手)。楼层口径与无策 BP 的 phaseGroups 一致：
# 蓝 1L → 红 1L+2L → 蓝 2L+3L → 红 3L → 红 4L → 蓝 4L+5L → 红 5L。
STAGES = (
    ('blue1',  '蓝方 1L',     '1', (0,)),
    ('red12',  '红方 1L+2L',  '2', (0, 1)),
    ('blue23', '蓝方 2L+3L',  '1', (1, 2)),
    ('red3',   '红方 3L',     '2', (2,)),
    ('red4',   '红方 4L',     '2', (3,)),
    ('blue45', '蓝方 4L+5L',  '1', (3, 4)),
    ('red5',   '红方 5L',     '2', (4,)),
)

# 前置条件里的 Ban：按 KPL draft-20 真实 BP 顺序逐手拆开，和 Pick 混在一起。
# (key, 展示名, 归属阵营, 该方第几手 Ban，全局第几手)。
BAN_STAGES = (
    ('blueBan1', '蓝方 Ban 1', '1', 0, 1),
    ('redBan1',  '红方 Ban 1', '2', 0, 2),
    ('blueBan2', '蓝方 Ban 2', '1', 1, 3),
    ('redBan2',  '红方 Ban 2', '2', 1, 4),
    ('redBan3',  '红方 Ban 3', '2', 2, 11),
    ('blueBan3', '蓝方 Ban 3', '1', 2, 12),
    ('redBan4',  '红方 Ban 4', '2', 3, 13),
    ('blueBan4', '蓝方 Ban 4', '1', 3, 14),
    ('redBan5',  '红方 Ban 5', '2', 4, 15),
    ('blueBan5', '蓝方 Ban 5', '1', 4, 16),
)

# 逐手 Pick 的前置键：前端把 18/20 手拆成一张张卡，后端按该方 pick 下标取值。
# STAGES 的合并楼层（red12 / blue23 / blue45）仍用于「触发 → 回应」链，两者不冲突。
# (key, 归属阵营, 该方第几手 pick)
SINGLE_PICK_STAGES = (
    ('blue1', '1', 0), ('red1', '2', 0), ('red2', '2', 1),
    ('blue2', '1', 1), ('blue3', '1', 2), ('red3', '2', 2),
    ('red4', '2', 3), ('blue4', '1', 3), ('blue5', '1', 4),
    ('red5', '2', 4),
)

# Pick 的全局手序（draft-20 口径；draft-18 在后 4 手整体前移 2 手）。
PICK_HANDS = {'blue1': 5, 'red1': 6, 'red2': 7, 'blue2': 8, 'blue3': 9,
              'red3': 10, 'red4': 17, 'blue4': 18, 'blue5': 19, 'red5': 20}
PICK_LABELS = {'blue1': '蓝方 1L', 'red1': '红方 1L', 'red2': '红方 2L',
               'blue2': '蓝方 2L', 'blue3': '蓝方 3L', 'red3': '红方 3L',
               'red4': '红方 4L', 'blue4': '蓝方 4L', 'blue5': '蓝方 5L',
               'red5': '红方 5L'}

# 前置槽位的完整展示顺序：按全局手序把 Ban 与 Pick 逐手混排（1~20，不跳 19）。
DRAFT_ORDER = tuple(
    sorted(
        [(key, 'ban', hand, camp, label) for key, label, camp, _step, hand in BAN_STAGES]
        + [(key, 'pick', PICK_HANDS[key], camp, PICK_LABELS[key])
           for key, camp, _slot in SINGLE_PICK_STAGES],
        key=lambda row: row[2],
    )
)

# 相邻两层构成一条「触发 → 回应」链（6 段，和无策的表格一一对应）
CHAINS = tuple((STAGES[i], STAGES[i + 1]) for i in range(len(STAGES) - 1))
MIN_SAMPLE = 1  # 全部列出，包含只出现 1 场的小样本；小样本只做标记，不隐藏


def oriented_chains(side=""):
    """始终给完整六段真实 BP 楼层链；选边只改变「我方 / 对手」的标注口径。

    蓝方永远先手、红方回应，不能因为站红方就少看三段。前端按 fromCamp/toCamp
    给每一段单独标注是谁，不再整张表共用一套左右称谓。
    """
    return CHAINS


def _heroes(value):
    if isinstance(value, (list, tuple)):
        return [pick_key(str(x)) for x in value if str(x or '').strip()]
    return []


def _stage_value(picks, slots):
    """slots 是 pick 数组下标组合；返回按抽取顺序的英雄元组。"""
    out = []
    for slot in slots:
        if slot >= len(picks):
            return ()
        out.append(picks[slot])
    return tuple(out)


def _key(value):
    """同组英雄不区分先后（红方 1L+2L 互换算同一组合）。"""
    return tuple(sorted(value))


def _label(value):
    return ' + '.join(value)


def _win_rates(game):
    """返回 {camp: 该阵营是否取胜}，None 表示胜负未知。"""
    result = game.get('result')
    if result is None:
        return {}
    side = str(game.get('side') or '')
    if side not in ('1', '2'):
        return {}
    return {'1': (result if side == '1' else not result),
            '2': ((not result) if side == '1' else result)}


def _rate(wins):
    if not wins:
        return None
    return round(100.0 * sum(1 for won in wins if won) / len(wins), 1)


def build_counter_chain(games, team='', opponent='', side='', bo=0, limit=0, prefix=None):
    """按触发英雄/组合分组，返回每层的回应 Top-N。

    ``side`` 限定我方所在阵营（1=蓝方 / 2=红方）；``bo`` 为 3/5/7 或 0=全部。
    ``prefix`` 是已选英雄条件：key 为 STAGES 的楼层 key，value 为该层英雄列表，
    先按条件筛掉不含这组英雄的对局，再逐层推演后面的回应。
    """
    wanted_prefix = {}
    valid_keys = ({stage[0] for stage in STAGES}
                  | {stage[0] for stage in BAN_STAGES}
                  | {stage[0] for stage in SINGLE_PICK_STAGES})
    for key, value in (prefix or {}).items():
        if key in valid_keys and _heroes(value):
            wanted_prefix[key] = _heroes(value)
    rows = list(games or [])
    if team:
        rows = [game for game in rows if str(game.get('team') or '') == str(team)]
    if opponent:
        rows = [game for game in rows if str(game.get('enemy') or '') == str(opponent)]
    if side in ('1', '2'):
        rows = [game for game in rows if str(game.get('side') or '') == side]
    # 逐层推演必须知道每一手是谁，盲选/缺 Ban 的局剔除。
    rows = [game for game in rows
            if game.get('pickOrderKnown') and game.get('bansKnown')]
    if not rows:
        return {'available': False, 'reason': '这个筛选条件下没有已核验手序的对局。',
                'scope': {'games': 0, 'orderGames': 0, 'team': team,
                          'opponent': opponent, 'side': side, 'bo': bo,
                          'prefix': wanted_prefix},
                'chains': []}

    bo_map = infer_bo(rows)
    if bo in (3, 5, 7):
        rows = [game for game in rows if bo_map.get(game.get('id')) == bo]
    if not rows:
        return {'available': False, 'reason': f'这个窗口里没有 BO{bo} 的已核验对局。',
                'scope': {'games': 0, 'orderGames': 0, 'team': team,
                          'opponent': opponent, 'side': side, 'bo': bo,
                          'prefix': wanted_prefix},
                'chains': []}

    records = []
    for game in rows:
        own = _heroes(game.get('picks'))
        foe = _heroes(game.get('enemyPicks'))
        if len(own) < 5 or len(foe) < 5:
            continue
        own_bans = _heroes(game.get('bans'))
        foe_bans = _heroes(game.get('enemyBans'))
        # 记录里的 draftEvents 才是已核验的手序；没有就退回名单原顺序。
        events = game.get('events') or []
        own_ban_order = [event['hero'] for event in events
                         if event.get('action') == 'ban' and event.get('actor') == 'team']
        foe_ban_order = [event['hero'] for event in events
                         if event.get('action') == 'ban' and event.get('actor') == 'enemy']
        if len(own_ban_order) != len(own_bans):
            own_ban_order = own_bans
        if len(foe_ban_order) != len(foe_bans):
            foe_ban_order = foe_bans
        if str(game.get('side')) == '1':
            blue, red = own, foe
            blue_bans, red_bans = own_ban_order, foe_ban_order
        else:
            blue, red = foe, own
            blue_bans, red_bans = foe_ban_order, own_ban_order
        values = {}
        for stage_key, _, camp, step, _hand in BAN_STAGES:
            bans = blue_bans if camp == '1' else red_bans
            values[stage_key] = (bans[step],) if step < len(bans) else ()
        for stage_key, _, camp, slots in STAGES:
            picks = blue if camp == '1' else red
            values[stage_key] = _stage_value(picks, slots)
        # 逐手前置键：每张手序卡只锁定该方这一手的实际英雄。
        for stage_key, camp, slot in SINGLE_PICK_STAGES:
            picks = blue if camp == '1' else red
            values[stage_key] = (picks[slot],) if slot < len(picks) else ()
        if any(not values[stage[0]] for stage in STAGES):
            continue
        records.append({'values': values, 'wins': _win_rates(game)})

    if not records:
        return {'available': False, 'reason': '这些局的手序不足以推演完整楼层。',
                'scope': {'games': 0, 'orderGames': 0, 'team': team,
                          'opponent': opponent, 'side': side, 'bo': bo,
                          'prefix': wanted_prefix},
                'chains': []}

    ban_keys = {stage[0] for stage in BAN_STAGES}
    for key, heroes in wanted_prefix.items():
        expected = frozenset(heroes)
        if key in ban_keys:
            # Ban 条件只要求「这些英雄都被禁」，不限制同方还禁了谁。
            records = [record for record in records
                       if expected <= frozenset(record['values'].get(key, ()))]
        else:
            records = [record for record in records
                       if frozenset(record['values'].get(key, ())) == expected]
    if not records:
        return {'available': False, 'reason': '这些前置英雄组合在窗口里没有对局，换一组或放宽窗口。',
                'scope': {'games': len(rows), 'orderGames': len(rows), 'team': team,
                          'opponent': opponent, 'side': side, 'bo': bo,
                          'prefix': wanted_prefix, 'prefixGames': 0},
                'chains': []}

    chains = []
    for from_stage, to_stage in oriented_chains(side):
        groups = defaultdict(list)
        for record in records:
            value = record['values'][from_stage[0]]
            groups[_key(value)].append(record)
        rows_out = []
        for from_key, members in groups.items():
            if len(members) < MIN_SAMPLE:
                continue
            display = next(r['values'][from_stage[0]] for r in members)
            responses = defaultdict(list)
            for record in members:
                responses[_key(record['values'][to_stage[0]])].append(record)
            options = []
            for to_key, matched in responses.items():
                if len(matched) < MIN_SAMPLE:
                    continue
                display_to = next(r['values'][to_stage[0]] for r in matched)
                wins = [r['wins'].get(to_stage[2]) for r in matched
                        if to_stage[2] in r['wins']]
                options.append({
                    'heroes': list(display_to), 'label': _label(display_to),
                    'games': len(matched),
                    'share': round(100.0 * len(matched) / len(members), 1),
                    'winRate': _rate(wins),
                })
            options.sort(key=lambda row: (-row['games'], row['label']))
            from_wins = [r['wins'].get(from_stage[2]) for r in members
                         if from_stage[2] in r['wins']]
            rows_out.append({
                'heroes': list(display), 'label': _label(display),
                'games': len(members),
                'share': round(100.0 * len(members) / len(records), 1),
                'winRate': _rate(from_wins),
                'responses': options[:limit] if limit > 0 else options,
                'responseTotal': len(options),
            })
        rows_out.sort(key=lambda row: (-row['games'], row['label']))
        chains.append({
            'key': f'{from_stage[0]}-{to_stage[0]}',
            'title': f'{from_stage[1]} → {to_stage[1]}',
            'fromLabel': from_stage[1].split(' ', 1)[-1],
            'toLabel': to_stage[1].split(' ', 1)[-1],
            'fromCamp': from_stage[2], 'toCamp': to_stage[2],
            'rows': rows_out[:limit] if limit > 0 else rows_out,
        })

    return {
        'available': True,
        'scope': {'games': len(rows), 'orderGames': len(rows), 'team': team,
                  'opponent': opponent, 'side': side, 'viewSide': side, 'bo': bo,
                  'prefix': wanted_prefix, 'prefixGames': len(records),
                   'draftOrder': [{'key': key, 'action': action, 'hand': hand,
                                   'camp': camp, 'label': label}
                                  for key, action, hand, camp, label in DRAFT_ORDER],
                  'chains': len(records)},
        'chains': chains,
    }
