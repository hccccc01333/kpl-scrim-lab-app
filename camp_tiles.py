"""营地十人面板的派生卡片（`dataBehaviorV2`）。

营地 `battledetail` 除了 KDA/经济/输出/承伤/参团这些固定列，还会按**分路自适应**
下发三组卡片：分路表现 / 团队贡献 / 战斗操作。每名选手 3–9 条，卡片组合随分路与
英雄变化——游走位才常见视野价值与治疗，打野位才常见反野与控龙，钟馗才有勾中。
这些卡片此前没有被任何代码读取，教练点名要的「视野价值 / 经济转有效伤害 /
反野总经济 / 控龙 / 勾中」全都在里面。

口径纪律（与 README「口径先于图表」一致）：

* 营地只给一个数值和一个「同位置对比」百分比（`dataNote`），**没有分母、没有分母
  的时间窗、也没有公开定义**。所以这里只做单位归一与名称对齐，绝不重算、不插值、
  不把百分比当分位、不跨局补 0。
* 卡片是自适应的，同一分路不同局可能完全不同。有就展示，没有就留空——调用方必须
  能接受「这一局这个位置没有这张卡」。
* 没见过的卡片名原样透出，不映射、不丢弃：营地一改版，新卡片会自动出现在面板里。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from paths import data_root

SCHEMA = 'camp-tiles-v1'

# 营地给的三组标题；顺序即展示顺序。
GROUPS = {'分路表现': 'lane', '团队贡献': 'team', '战斗操作': 'fight'}

# 名称对齐：只影响展示时的分组与提示，不改变数值。
# role 是「教练按位置点名要的」标记，用于面板把该位置的卡片排在前面。
KNOWN = {
    '视野价值': ('vision', '营地合成的视野贡献值', ('游走',)),
    '经济转有效伤害': ('gold_to_damage', '有效伤害 / 总经济，营地口径', ('中路', '发育路')),
    '有效伤害': ('effective_damage', '营地过滤掉无效伤害后的输出占比', ()),
    '参与控龙次数': ('dragon_participation', '参与击杀暴君 / 主宰的次数', ('打野',)),
    '中立资源掌控': ('neutral_control', '营地口径的中立资源掌控次数', ('打野',)),
    '反野总经济': ('invade_gold', '在对方野区获得的野怪经济', ('打野',)),
    '单人反野经济': ('invade_gold_solo', '单人入侵对方野区获得的经济', ('打野',)),
    '控制时长': ('control_time', '对敌方施加控制的总秒数', ('游走',)),
    '硬控时长': ('hard_control_time', '眩晕 / 击飞等硬控的秒数', ('游走',)),
    '软控时长': ('soft_control_time', '减速等软控的秒数', ('游走',)),
    '勾中敌方英雄': ('hook_hit', '钟馗二技能命中敌方的次数', ('游走',)),
    '为队友解控数': ('ally_cleanse', '替队友解除控制的次数', ('游走',)),
    '为队友返还生命': ('ally_heal', '给队友回复生命的次数', ('游走',)),
    '带线总经济': ('side_lane_gold', '带线获得的经济', ('对抗路',)),
    '对位经济差': ('lane_gold_diff', '与本分路对位英雄的经济差', ('对抗路', '发育路')),
    '对线期对位经济差': ('lane_gold_diff_early', '对线期（0–4 分钟）与本分路对位英雄的经济差', ('对抗路', '发育路')),
    '对位资源差': ('lane_resource_diff', '与本分路对位英雄的资源差', ('对抗路', '发育路')),
    '有效承伤': ('effective_taken', '营地口径的有效承伤', ('游走', '对抗路')),
    '经济转有效承伤': ('gold_to_taken', '有效承伤 / 总经济', ('游走', '对抗路')),
    '经济转治疗': ('gold_to_heal', '治疗量 / 总经济', ('游走',)),
    '有效治疗': ('effective_heal', '营地口径的有效治疗', ('游走',)),
    '有效护盾': ('effective_shield', '营地口径的有效护盾', ('游走',)),
    '参与推塔': ('tower_participation', '参与推塔的次数', ()),
    '对本分路塔伤害占比': ('own_lane_tower_share', '对本分路防御塔的伤害占比', ()),
    '全局单杀次数': ('solo_kill', '全局单杀（1v1 击杀）次数', ('对抗路', '打野')),
    '高价值死亡占比': ('high_value_death_share', '高价值死亡占全部死亡的比重', ()),
    '关键助攻': ('key_assist', '营地口径的关键助攻次数', ()),
    '防守野区伤害': ('defend_jungle_damage', '防守己方野区时造成的伤害', ('打野',)),
}

_VALUE_RE = re.compile(r'^\s*(-?\d+(?:\.\d+)?)\s*(%|[sS秒]|万|k|K)?\s*$')
_SIZE = {'万': 10000.0, 'k': 1000.0, 'K': 1000.0}


def parse_value(raw):
    """把营地卡片原文拆成 (数值, 单位)。拆不开就返回 (None, '')，原文留给调用方。"""
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw), ''
    text = str(raw if raw is not None else '').strip()
    if not text:
        return None, ''
    match = _VALUE_RE.match(text)
    if not match:
        return None, ''
    number = float(match.group(1))
    suffix = match.group(2) or ''
    if suffix == '%':
        return number, '%'
    if suffix in ('s', 'S', '秒'):
        return number, 's'
    if suffix in _SIZE:
        return number * _SIZE[suffix], ''
    return number, ''


def parse_tiles(role):
    """一名选手的 `dataBehaviorV2` → 扁平卡片列表（保持营地给的分组与顺序）。"""
    tiles = []
    blocks = role.get('dataBehaviorV2') if isinstance(role, dict) else None
    for block in blocks or []:
        if not isinstance(block, dict):
            continue
        group_title = str(block.get('title') or '').strip()
        group = GROUPS.get(group_title, 'other')
        for item in block.get('dataCounts') or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get('name') or '').strip()
            if not name:
                continue
            raw = item.get('data')
            value, unit = parse_value(raw)
            key, hint, roles = KNOWN.get(name, ('', '', ()))
            tiles.append({
                'name': name,
                'key': key or '',
                'group': group,
                'groupTitle': group_title,
                'raw': '' if raw is None else str(raw).strip(),
                'value': value,
                'unit': unit,
                'note': str(item.get('dataNote') or '').strip(),
                'hint': hint,
                'roles': list(roles),
            })
    return tiles


def _position_name(role):
    """营地 `battleRecords.position` → 中文路名（0=对抗路 1=中路 2=发育路 3=打野 4=游走）。"""
    records = role.get('battleRecords') if isinstance(role, dict) else None
    try:
        code = int((records or {}).get('position'))
    except (TypeError, ValueError):
        return ''
    return {0: '对抗路', 1: '中路', 2: '发育路', 3: '打野', 4: '游走'}.get(code, '')


def _hero(role):
    records = role.get('battleRecords') if isinstance(role, dict) else None
    hero = ((records or {}).get('usedHero') or {}).get('heroName')
    return str(hero or '').strip()


def read_detail(path):
    """读一局 `camp_details/<seq>.json` → {(阵营, 英雄): [卡片]} + 元信息。

    阵营用 blue / red，与数据包的 `player.camp` 同一套；英雄名两侧不会重名，
    所以 (阵营, 英雄) 足以对齐到数据包里的选手。
    """
    try:
        payload = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    data = payload.get('data') if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return {}
    result = {}
    for side_key, camp in (('blueRoles', 'blue'), ('redRoles', 'red')):
        for role in data.get(side_key) or []:
            if not isinstance(role, dict):
                continue
            hero = _hero(role)
            if not hero:
                continue
            result[(camp, hero)] = {
                'position': _position_name(role),
                'tiles': parse_tiles(role),
            }
    return result


def detail_dir():
    return Path(data_root() / 'camp_details')


def game_seq(detail):
    """从单局详情里取营地 gameseq：优先 officialReplay.id，其次通道的 sources.camp。

    `sources` 在数据包里是字符串列表（['bundle']），在通道里是字典，两种都要能读。
    """
    sources = (detail or {}).get('sources')
    camp_source = sources.get('camp') if isinstance(sources, dict) else None
    for value in (
        ((detail or {}).get('officialReplay') or {}).get('id'),
        (detail or {}).get('campSeq'),
        (camp_source or {}).get('gameSeq'),
        ((detail or {}).get('match') or {}).get('gameSeq'),
    ):
        text = str(value or '').strip()
        if text.startswith('camp-'):
            text = text[len('camp-'):]
        if text.isdigit():
            return text
    return ''


def attach(detail, base=None):
    """把卡片挂到单局详情的十人上：`player['campTiles']`。

    找不到营地详情、或这一局没同步过面板时，不写空数组，保持字段缺失——
    前端据此显示「这一局没有营地卡片」，而不是显示 0。
    """
    if not isinstance(detail, dict):
        return detail
    seq = game_seq(detail)
    if not seq:
        return detail
    folder = Path(base) if base else detail_dir()
    path = folder / f'{seq}.json'
    if not path.is_file():
        return detail
    table = read_detail(path)
    if not table:
        return detail
    hit = 0
    for player in detail.get('players') or []:
        key = (str(player.get('camp') or ''), str(player.get('hero') or ''))
        entry = table.get(key)
        if not entry or not entry.get('tiles'):
            continue
        player['campTiles'] = entry['tiles']
        if not player.get('position') and entry.get('position'):
            player['position'] = entry['position']
        hit += 1
    if hit:
        detail['campTilesSource'] = {'gameSeq': seq, 'players': hit,
                                     'file': path.name, 'schema': SCHEMA}
    return detail


def summarize(detail):
    """一局卡片覆盖面的短摘要，给空态与调试用。"""
    players = (detail or {}).get('players') or []
    with_tiles = [p for p in players if p.get('campTiles')]
    names = sorted({t['name'] for p in with_tiles for t in p['campTiles']})
    return {'players': len(players), 'withTiles': len(with_tiles), 'names': names}
