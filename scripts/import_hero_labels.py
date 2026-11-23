"""从赛训组英雄标签工作簿导入 hero_archetypes / hero_capabilities（P0-1）。

用法：
    python scripts/import_hero_labels.py "<工作簿.xlsx 路径>" --stamp 2026-11-12类

做四件事：
1. 读取「133英雄赛事标签 / 英雄分路候选 / 能力矩阵_0-1」三张表；
2. 与当前 hero_archetypes 对账（默认类型变化、默认分路变化、副分路增删），
   写入 docs/hero_labels_import_<月份>.md 备查；
3. 重写 hero_archetypes.py（新词表 + 133 英雄 + 治理字段，「其他」=「待分类」）；
4. 重写 hero_capabilities.py（19 维能力矩阵 + 功能标签规则）。

硬规则（docs/team_dossier_p0.md §1）：
- 副分路只登记工作簿给出具体类型的条目；标「待按实际分路及版本确认」的不入表；
- 默认类型以「待」开头的英雄（如「射手待细分」）不入 HERO_ARCHETYPES，
  走「待分类」路径，known 由 HERO_LABEL_META 判定；
- 本脚本不修改 hero_roles.py（九维并行保留，映射见 hero_capabilities）。
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from collections import Counter
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LANES = ('对抗路', '打野', '中路', '发育路', '游走')

# 类型词典（工作簿「类型词典」+ 按英雄表现状回补的「爆发法师/推进法师」）。
# 本局角色型（功能边/蓝领野/节奏辅/法伤射手）不进默认词表。
# 五路 12 类精简版（2026-11 工作簿「类型词典」）：默认层与本局层同一套词表。
GAME_LANE_TYPES: dict[str, tuple[str, ...]] = {
    '对抗路': ('战边', '坦边'),
    '打野': ('刺野', '战野', '坦野'),
    '中路': ('工具人', '法刺'),
    '发育路': ('游射', '呆射'),
    '游走': ('开团辅', '保护辅', '功能辅'),
}
LANE_GROUP_ORDER: dict[str, tuple[str, ...]] = GAME_LANE_TYPES

DIMS19 = ('前排', '承伤', '开团', '反开', '保护', '控制', '爆发', '持续输出',
          '消耗', '机动', '切入', '清线', '带线', '续航', '推进', '支援',
          '入侵', '收割', '团队增益')

SOURCE_URL = 'https://pvp.qq.com/web201605/js/herolist.json'
PENDING_PREFIX = '待'


def _cell(value) -> str:
    return '' if value is None else str(value).strip()


def _is_pending(text: str) -> bool:
    return text.startswith(PENDING_PREFIX)


def load_workbook_tables(xlsx_path: Path):
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)

    rows = [r for r in wb['133英雄赛事标签'].iter_rows(values_only=True) if any(v is not None for v in r)]
    header = [_cell(h) for h in rows[0]]
    heroes: dict[str, dict] = {}
    for r in rows[1:]:
        d = dict(zip(header, r))
        name = _cell(d.get('英雄名称'))
        if not name:
            continue
        heroes[name] = {
            'id': int(d.get('英雄ID') or 0),
            'lane': _cell(d.get('默认分路')),
            'type': _cell(d.get('默认赛训类型')),
            'side_lanes': [s for s in _cell(d.get('可选分路')).replace('，', ',').split(',') if s],
            'confidence': _cell(d.get('分类置信度')) or '待复核',
            'note': _cell(d.get('复核说明')),
        }

    rows = [r for r in wb['英雄分路候选'].iter_rows(values_only=True) if any(v is not None for v in r)]
    header = [_cell(h) for h in rows[0]]
    side_confirmed: dict[tuple[str, str], str] = {}
    side_pending: list[tuple[str, str]] = []
    default_mismatch: list[str] = []
    for r in rows[1:]:
        d = dict(zip(header, r))
        name, lane = _cell(d.get('英雄名称')), _cell(d.get('实际分路候选'))
        kind = _cell(d.get('来源层级'))
        raw_type = _cell(d.get('该位置建议分类'))
        if kind == '默认建议':
            info = heroes.get(name)
            if info and lane == info['lane'] and raw_type != info['type']:
                default_mismatch.append(f'{name}: 主表 {info["type"]} / 候选表 {raw_type}')
            continue
        if kind == '副分路候选':
            if _is_pending(raw_type):
                side_pending.append((name, lane))
            else:
                side_confirmed[(name, lane)] = raw_type

    rows = [r for r in wb['能力矩阵_0-1'].iter_rows(values_only=True) if any(v is not None for v in r)]
    header = [_cell(h) for h in rows[0]]
    caps: dict[str, tuple[str, ...]] = {}
    for r in rows[1:]:
        d = dict(zip(header, r))
        name = _cell(d.get('英雄'))
        if not name:
            continue
        caps[name] = tuple(dim for dim in DIMS19 if _cell(d.get(dim)) in ('1', 1, '1.0'))
    return heroes, side_confirmed, side_pending, default_mismatch, caps


def build_archetypes(heroes, side_confirmed):
    """hero → {lane: type}，默认分路在前；返回 (entries, skipped_pending)。"""
    entries: dict[str, dict[str, str]] = {}
    skipped: list[str] = []
    for name, info in heroes.items():
        lane, raw_type = info['lane'], info['type']
        if lane not in LANES or _is_pending(raw_type):
            skipped.append(f'{name}（默认 {lane}/{raw_type or "空"}）')
            continue
        if raw_type not in LANE_GROUP_ORDER[lane]:
            skipped.append(f'{name}（默认 {lane}/{raw_type} 不在词表）')
            continue
        lanes: dict[str, str] = {lane: raw_type}
        for side in info['side_lanes']:
            confirmed = side_confirmed.get((name, side))
            if confirmed and side not in lanes and confirmed in LANE_GROUP_ORDER.get(side, ()):
                lanes[side] = confirmed
        entries[name] = lanes
    return entries, skipped


def build_meta(heroes):
    meta: dict[str, dict] = {}
    for name, info in heroes.items():
        item = {'id': info['id'], 'confidence': info['confidence']}
        if info['note']:
            item['note'] = info['note']
        meta[name] = item
    return meta


def reconcile(old_mod, entries):
    """与旧 hero_archetypes 对账：默认标签变化 / 副分路增删 / 覆盖差集。"""
    old = getattr(old_mod, 'HERO_ARCHETYPES', {})
    old_default = {h: next(iter(lanes)) for h, lanes in old.items()}
    label_changes, lane_changes, side_removed, side_added = [], [], [], []
    for name, lanes in entries.items():
        if name not in old:
            continue
        new_default = next(iter(lanes))
        old_default_lane = old_default[name]
        if old_default_lane != new_default:
            lane_changes.append((name, old_default_lane, old[name][old_default_lane],
                                 new_default, lanes[new_default]))
        elif old[name][old_default_lane] != lanes[new_default]:
            label_changes.append((name, old_default_lane, old[name][old_default_lane],
                                  lanes[new_default]))
        for side, side_type in lanes.items():
            if side != new_default and old[name].get(side) != side_type:
                side_added.append((name, side, old[name].get(side) or '—', side_type))
        for side, side_type in old[name].items():
            if side != old_default_lane and lanes.get(side) is None:
                side_removed.append((name, side, side_type))
    only_old = sorted(set(old) - set(entries))
    only_new = sorted(set(entries) - set(old))
    return label_changes, lane_changes, side_removed, side_added, only_old, only_new


def data_coverage(entries, meta, old_mod):
    """扫 data/matches：选用/禁用英雄级覆盖率与槽位级「待分类」数（旧 vs 新）。

    英雄级「无档案」判定：新表按 HERO_LABEL_META（含默认类型待细分者），
    旧表按 HERO_ARCHETYPES 键集。
    """
    import glob
    picks: Counter = Counter()
    slots: Counter = Counter()
    for f in glob.glob(str(ROOT / 'data' / 'matches' / 'channel-*.json')):
        try:
            data = json.loads(Path(f).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        bp = (data.get('match') or {}).get('campBp') or {}
        for side in ('left', 'right'):
            for p in (bp.get('picks') or {}).get(side, []) or []:
                if isinstance(p, dict) and p.get('name'):
                    picks[p['name']] += 1
            for p in (bp.get('bans') or {}).get(side, []) or []:
                nm = p.get('name') if isinstance(p, dict) else p
                if nm:
                    picks[nm] += 0  # bans 计覆盖、不计出场
        for hero, lane in (bp.get('lanes') or {}).items():
            slots[(hero, lane)] += 1

    def slot_pending(table, known):
        games = pairs = 0
        unknown_heroes = set()
        for (hero, lane), n in slots.items():
            if hero not in known:
                unknown_heroes.add(hero)
            elif lane not in table.get(hero, {}):
                games += n
                pairs += 1
        return games, pairs, sorted(unknown_heroes)

    old_known = set(getattr(old_mod, 'HERO_ARCHETYPES', {}))
    new_known = set(meta)
    old_unknown = sorted(h for h in picks if h not in old_known)
    new_unknown = sorted(h for h in picks if h not in new_known)
    old_games, old_pairs, _old_slots = slot_pending(old_mod.HERO_ARCHETYPES, old_known)
    new_games, new_pairs, _new_slots = slot_pending(entries, new_known)
    return {
        'picks_heroes': len(picks),
        'old_unknown': old_unknown,
        'new_unknown': new_unknown,
        'old_slot_pending_games': old_games, 'old_slot_pending_pairs': old_pairs,
        'new_slot_pending_games': new_games, 'new_slot_pending_pairs': new_pairs,
    }


def format_archetypes(entries, meta):
    lines = []
    for lane in LANES:
        block = [(name, lanes) for name, lanes in entries.items()
                 if next(iter(lanes)) == lane]
        if not block:
            continue
        lines.append(f'    # ── {lane}（默认分路）─────────────────────────────')
        for name, lanes in block:
            conf = meta.get(name, {}).get('confidence', '')
            mark = '' if conf == '高' else f'  # 置信度:{conf}'
            pair = ', '.join(f'{k!r}: {v!r}' for k, v in lanes.items())
            lines.append(f'    {name!r}: {{{pair}}},{mark}')
        lines.append('')
    return '\n'.join(lines)


def format_meta(meta, entries):
    lines = []
    for name, info in meta.items():
        # 待细分默认类型的英雄不入 HERO_ARCHETYPES，但元数据仍保留（known 判定）
        parts = [f"'id': {info['id']}", f"'confidence': {info['confidence']!r}"]
        if info.get('note'):
            parts.append(f"'note': {info['note']!r}")
        lines.append(f'    {name!r}: {{{", ".join(parts)}}},')
    return '\n'.join(lines)


ARCHETYPES_TEMPLATE = '''"""英雄位置与打法类型标签（赛训口径 · 工作簿导入版 2026-11）。

权威来源：赛训组《王者荣耀_KPL赛训英雄标签_五路12类精简版_2026-11.xlsx》
（133 英雄，英雄 ID 对齐 resources/catalog.json；置信度 / 复核说明等治理
字段见 HERO_LABEL_META）。导入工具：scripts/import_hero_labels.py，
重新导入会整体替换本文件；人工微调请直接改表并同步 docs/team_dossier_p0.md。

类型语义（docs/team_dossier_p0.md §1.1）：
  对抗路：战边 / 坦边
  打野：  刺野 / 战野 / 坦野
  中路：  工具人 / 法刺
  发育路：游射 / 呆射
  游走：  开团辅 / 保护辅 / 功能辅

用法约束（与 docs/team_dossier_p0.md §1.3 一致）：
- 按该局实际分路取类型；实际分路未登记时返回「待分类」，不猜；
- 只有分路缺失时才退回默认分路（字典第一个分路）；
- 「待分类」不计入类型占比分母，且必须单独计数展示。
"""
from __future__ import annotations

LANES = {lanes!r}

# 前端展示顺序（默认层词表）；「待分类」永远排最后，不参与类型占比分母。
LANE_ARCHETYPES: dict[str, tuple[str, ...]] = {lane_groups!r}

# 本局标注词表（五路 12 类，与默认层一致）。
GAME_LANE_TYPES: dict[str, tuple[str, ...]] = {game_types!r}

OTHER = {other!r}
SOURCE_URL = {source_url!r}

# 英雄 → {{分路: 类型}}，第一个分路即默认分路。副分路只登记工作簿给出具体
# 类型的条目；「待按实际分路及版本确认」的副分路不入表，对局出现时落「待分类」。
HERO_ARCHETYPES: dict[str, dict[str, str]] = {{
{archetype_body}}}

# 治理字段（工作簿 2026-11 交付）：id=官方英雄 ID；confidence=分类置信度；
# note=复核说明（仅非空收录）。赛事核验状态当前全部为「待逐局赛事核验」。
# 默认类型待细分的英雄（如「射手待细分」）只在此表登记，不入 HERO_ARCHETYPES。
HERO_LABEL_META: dict[str, dict] = {{
{meta_body}}}


def default_lane(hero: str) -> str | None:
    """英雄的默认分路（表里登记的第一个分路）；未收录返回 None。"""
    lanes = HERO_ARCHETYPES.get(str(hero or ''))
    return next(iter(lanes), None) if lanes else None


def archetype_of(hero: str, lane: str | None = None) -> str:
    """按实际分路取打法类型。

    有实际分路但表里没登记该分路时返回「待分类」，不拿默认分路的类型硬套
    （例如元歌出现在发育路，不能标成战边）。只有分路未知时才退回默认分路。
    """
    lanes = HERO_ARCHETYPES.get(str(hero or ''))
    if not lanes:
        return OTHER
    if lane:
        return lanes.get(lane, OTHER)
    return next(iter(lanes.values()))


def describe(hero: str, lane: str | None = None) -> dict:
    """统一输出：{{hero, lane, archetype, known}}。lane 缺失时用默认分路。

    known = 该英雄在赛训组标签工作簿有档案（含默认类型待细分者）；
    分类置信度与复核说明见 HERO_LABEL_META。
    """
    hero = str(hero or '').strip()
    lane = lane or default_lane(hero)
    return {{'hero': hero, 'lane': lane, 'archetype': archetype_of(hero, lane),
            'known': hero in HERO_LABEL_META}}


def taxonomy() -> dict:
    """前端渲染用的分类元数据（分路 → 默认层类型顺序 + 本局类型词典）。"""
    return {{
        'lanes': list(LANES),
        'groups': {{lane: list(types) for lane, types in LANE_ARCHETYPES.items()}},
        'gameTypes': {{lane: list(types) for lane, types in GAME_LANE_TYPES.items()}},
        'other': OTHER,
        'note': '赛训组标签工作簿导入（2026-11 五路 12 类精简版）：按实际分路取类型；未收录或分路未登记归「待分类」，不猜。',
    }}
'''


CAPABILITIES_TEMPLATE = '''"""英雄能力标签（赛训口径 · 工作簿「能力矩阵_0-1」导入版，19 维 0/1）。

权威来源：赛训组《王者荣耀_KPL赛训英雄标签_五路12类精简版_2026-11.xlsx》能力矩阵，
133 英雄全覆盖；维度为教练可读词，不用统计术语。导入工具：
scripts/import_hero_labels.py。

与 hero_roles.py 九维的关系（docs/team_dossier_p0.md §1.2）：本表是权威层；
hero_roles 九维并行保留供 BP 模块过渡，映射见 hero_roles_compat()。
「双核 / 单核」不由能力标签派生，必须用十人面板资源占比计算（工作簿
「使用说明」口径）；本模块的功能标签也只包含纯能力求和可解释的条目。
"""
from __future__ import annotations

CAPABILITIES = {dims!r}

# 英雄 → 具备的能力维度（0/1 矩阵的展开形式，只列 1 项）。
HERO_CAPABILITIES: dict[str, tuple[str, ...]] = {{
{cap_body}}}

# 阵容级功能标签规则：标签名 → (维度表达式, 阈值)。「+」表示两维求和。
FUNCTIONAL_RULES: tuple[tuple[str, str, int], ...] = (
    ('双前排', '前排', 2),
    ('强开团', '开团', 2),
    ('保护链', '保护+反开', 2),
    ('清线转线', '清线', 3),
)


def capability_of(hero: str) -> dict[str, int]:
    """单英雄 19 维向量；未收录返回全 0（不猜）。"""
    caps = {{caps: 0 for caps in CAPABILITIES}}
    for dim in HERO_CAPABILITIES.get(str(hero or ''), ()):
        caps[dim] = 1
    return caps


def lineup_capabilities(heroes) -> dict[str, int]:
    """阵容 5 人能力求和。"""
    total = {{caps: 0 for caps in CAPABILITIES}}
    for hero in heroes or []:
        for dim, value in capability_of(hero).items():
            total[dim] += value
    return total


def functional_tags(heroes) -> list[str]:
    """可解释的功能标签；含负面标签「无前排」。双核不在此列（资源口径）。

    负面标签只在阵容中有已收录英雄时给出——全员无能力数据不猜短板。
    """
    total = lineup_capabilities(heroes)
    tags: list[str] = []
    for name, expr, threshold in FUNCTIONAL_RULES:
        value = sum(total[dim] for dim in expr.split('+'))
        if value >= threshold:
            tags.append(name)
    has_data = any(h in HERO_CAPABILITIES for h in (heroes or []))
    if has_data and total['前排'] == 0:
        tags.append('无前排')
    return tags


# hero_roles 九维 → 19 维映射（docs/team_dossier_p0.md §1.2）。控龙/运营无
# 对应维度，随九维退役；本函数只做迁移期兼容，不回写 hero_roles.py。
_ROLE_MAP = (('engage', ('开团',), 1), ('peel', ('保护', '反开'), 1),
             ('burst', ('爆发',), 1), ('sustained', ('持续输出',), 1),
             ('frontline', ('前排', '承伤'), 1), ('waveclear', ('清线',), 1),
             ('roam', ('支援', '机动'), 1), ('macro', ('推进',), 1),
             ('resilience', ('反开',), 1))


def hero_roles_compat(hero: str) -> dict[str, int]:
    """由 19 维推导 hero_roles 九维近似值（迁移期兼容）。"""
    total = capability_of(hero)
    return {{name: int(any(total[dim] for dim in dims))
            for name, dims, _min in _ROLE_MAP}}
'''


def write_module(path: Path, text: str) -> None:
    path.write_text(text, encoding='utf-8', newline='\n')


def write_reconcile_doc(out_path: Path, workbook_name: str, heroes, skipped,
                        label_changes, lane_changes, side_removed, side_added,
                        only_old, only_new, coverage, default_mismatch) -> None:
    conf = Counter(i['confidence'] for i in heroes.values())
    in_table = sum(1 for h in heroes.values()
                   if h['type'] in LANE_GROUP_ORDER.get(h['lane'], ()))
    lines = [
        '# 英雄标签导入对账清单',
        '',
        f'- 来源：{workbook_name}（133 英雄 / 能力矩阵 19 维 / 分路候选 176 条）',
        f'- 导入结果：类型表 {in_table} 条 + 默认类型待细分 {len(skipped)} 条（不入类型表，档案保留）；'
        f'置信度 高 {conf.get("高", 0)} / 中 {conf.get("中", 0)} / 待复核 {conf.get("待复核", 0)}',
        f'- 候选表默认建议不一致：{len(default_mismatch)} 条' + ('；'.join(default_mismatch) if default_mismatch else ''),
        '',
        '## 数据覆盖（data/matches 全量）',
        '',
        f'- 选用+禁用英雄数：{coverage["picks_heroes"]}',
        f'- 导入前未收录：{coverage["old_unknown"] or "无"}',
        f'- 导入后未收录：{coverage["new_unknown"] or "无"}',
        f'- 槽位级「待分类」（已收录英雄但该分路未登记，可见、不计入类型分母）：'
        f'导入前 {coverage["old_slot_pending_games"]} 局 / {coverage["old_slot_pending_pairs"]} 组合 → '
        f'导入后 {coverage["new_slot_pending_games"]} 局 / {coverage["new_slot_pending_pairs"]} 组合',
        '',
        '## 默认分路变化（旧 → 新，以工作簿为准）',
        '',
        '| 英雄 | 旧默认 | 新默认 |',
        '| --- | --- | --- |',
    ]
    for name, old_lane, old_type, new_lane, new_type in lane_changes:
        lines.append(f'| {name} | {old_lane}/{old_type} | {new_lane}/{new_type} |')
    lines += ['', '## 默认类型变化（分路不变）', '', '| 英雄 | 分路 | 旧类型 | 新类型 |', '| --- | --- | --- | --- |']
    for name, lane, old_type, new_type in label_changes:
        lines.append(f'| {name} | {lane} | {old_type} | {new_type} |')
    lines += ['', '## 副分路登记变化', '',
              '| 英雄 | 分路 | 旧 | 新 |', '| --- | --- | --- | --- |']
    for name, side, old_type, new_type in side_added:
        lines.append(f'| {name} | {side} | {old_type} | {new_type}（新增登记） |')
    for name, side, old_type in side_removed:
        lines.append(f'| {name} | {side} | {old_type} | 移除（工作簿未确认） |')
    if only_old:
        lines += ['', f'## 仅存在于旧表的英雄（工作簿缺失，需赛训组确认）：{ "、".join(only_old)}']
    if only_new:
        lines += ['', f'## 工作簿净新增英雄：{ "、".join(only_new)}']
    if skipped:
        lines += ['', f'## 默认类型待细分（不入 HERO_ARCHETYPES）：{ "；".join(skipped)}']
    out_path.write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('xlsx', help='赛训组英雄标签工作簿路径')
    parser.add_argument('--stamp', default='2026-11', help='对账文档月份/版本后缀（默认 2026-11）')
    args = parser.parse_args()
    xlsx_path = Path(args.xlsx)

    heroes, side_confirmed, side_pending, default_mismatch, caps = load_workbook_tables(xlsx_path)
    missing_caps = sorted(set(heroes) - set(caps))
    if missing_caps:
        print(f'[warn] 能力矩阵缺失英雄：{missing_caps}')

    entries, skipped = build_archetypes(heroes, side_confirmed)
    meta = build_meta(heroes)

    # 对账要在覆盖旧文件之前完成；旧表损坏或缺失时降级为跳过对账
    try:
        import hero_archetypes as old_mod
        label_changes, lane_changes, side_removed, side_added, only_old, only_new = reconcile(old_mod, entries)
        coverage = data_coverage(entries, meta, old_mod)
    except (SyntaxError, ImportError, AttributeError):
        old_mod = None
        label_changes = lane_changes = side_removed = side_added = []
        only_old = only_new = []
        coverage = {'picks_heroes': 0, 'old_unknown': ['<旧表不可用，跳过对账>'], 'new_unknown': [],
                    'old_slot_pending_games': 0, 'old_slot_pending_pairs': 0,
                    'new_slot_pending_games': 0, 'new_slot_pending_pairs': 0}

    arch_body = format_archetypes(entries, meta)
    meta_body = format_meta(meta, entries)
    cap_lines = []
    for name in heroes:
        if name in caps:
            cap_lines.append(f'    {name!r}: {tuple(caps[name])!r},')
    cap_body = '\n'.join(cap_lines)

    write_module(ROOT / 'hero_archetypes.py', ARCHETYPES_TEMPLATE.format(
        lanes=LANES, lane_groups=LANE_GROUP_ORDER, game_types=GAME_LANE_TYPES,
        other='待分类', source_url=SOURCE_URL,
        archetype_body=arch_body + '\n', meta_body=meta_body + '\n'))
    write_module(ROOT / 'hero_capabilities.py', CAPABILITIES_TEMPLATE.format(
        dims=DIMS19, cap_body=cap_body + '\n'))

    stamp = args.stamp
    doc_path = ROOT / 'docs' / f'hero_labels_import_{stamp}.md'
    write_reconcile_doc(doc_path, xlsx_path.name, heroes, skipped,
                        label_changes, lane_changes, side_removed, side_added,
                        only_old, only_new, coverage, default_mismatch)

    print(f'[ok] hero_archetypes.py：{len(entries)} 英雄入表，{len(skipped)} 条默认待细分')
    print(f'[ok] hero_capabilities.py：{len(cap_lines)} 英雄 19 维能力')
    print(f'[ok] 副分路登记 {len(side_confirmed)} 条（待确认 {len(side_pending)} 条未入表）')
    print(f'[ok] 对账清单 → {doc_path.relative_to(ROOT)}')
    print(f'[ok] 覆盖：导入前未收录 {coverage["old_unknown"]} → 导入后 {coverage["new_unknown"]}')
    print(f'[ok] 槽位级待分类：{coverage["old_slot_pending_games"]} 局 / {coverage["old_slot_pending_pairs"]} 组合'
          f' → {coverage["new_slot_pending_games"]} 局 / {coverage["new_slot_pending_pairs"]} 组合')
    return 0


if __name__ == '__main__':
    sys.exit(main())
