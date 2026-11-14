"""把 BPagent 项目抓好的营地英雄克制数据归整成本项目的克制事实表。

输入：王者营地 App 英雄详情页「克制 / 被克制 / 双排组合 / 三排组合」的 UI 抓取结果
（jsonl，每行一个英雄：counters / countered_by / duo / trio，带 index 与 capturedAt），
由外部项目 `scrape_camp_hero_relations_ui.py` 产出（App UI 自动化，仅公开展示数据）。

输出：`data/facts/camp_counters.json`——英雄名（营地口径，与十人面板 / 图标目录一致）
→ 关系列表。名字对不上英雄目录的（如截断的「元流之子...」）跳过并计入报告，不猜。

顺带做一份**交叉校验清单**：营地页面给的 role 字段（如「战士/坦克」）与本项目
`hero_roles.py` 人工种子表的 frontline/engage 标签对照，冲突只打印、不自动改种子表——
给教练/维护者人工复核用。

用法：
    python scripts/build_camp_counters.py \
        --raw "D:/Projects/KPLBPagentRL/data/processed/camp_hero_relations_ui.jsonl"
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / 'data' / 'facts' / 'camp_counters.json'
CATALOG = ROOT / 'resources' / 'catalog.json'

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import hero_names  # noqa: E402  复用编辑距离兜底近似匹配
import hero_roles  # noqa: E402


def load_catalog_heroes():
    """英雄目录：name 集合 + name→id（报告里给人工复核用）。"""
    data = json.loads(CATALOG.read_text(encoding='utf-8'))
    entries = data if isinstance(data, list) else data.get('entries') or []
    return {str(entry.get('name') or '').strip() for entry in entries
            if entry.get('kind') == 'hero' and entry.get('name')}


def normalize(raw, known):
    """营地展示名 → 目录英雄名。精确优先，其次去括号/统一全半角，最后编辑距离兜底。"""
    text = str(raw or '').strip()
    if not text:
        return ''
    if text in known:
        return text
    compact = text.replace('（', '(').replace('）', ')')
    if compact in known:
        return compact
    # 截断省略号（「元流之子...」这类）分不清具体形态，宁缺不猜
    if '…' in text or '...' in text:
        return ''
    # 「元流之子(射手)」↔「元流之子_射手」这类形态差异
    alt = compact.replace('(', '_').replace(')', '')
    if alt in known:
        return alt
    # 编辑距离兜底：只接受完全等长且只差 1 字、且共享字符的近似（复用 OCR 口径）
    for name in sorted(known):
        distance = hero_names.edit_distance(compact, name)
        if distance == 0 or (distance == 1 and len(compact) == len(name)
                             and set(compact) & set(name)):
            return name
    return ''


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--raw', required=True, help='营地英雄关系 jsonl（BPagent 项目产物）')
    ap.add_argument('--out', type=pathlib.Path, default=OUT)
    args = ap.parse_args(argv)

    known = load_catalog_heroes()
    rows = [json.loads(line) for line in
            pathlib.Path(args.raw).read_text(encoding='utf-8').splitlines() if line.strip()]
    captured = sorted({str(row.get('captured_at') or '')[:10] for row in rows if row.get('captured_at')})

    def pack_people(items, *, with_index=True, with_gains=False):
        out = []
        for item in items or []:
            name = normalize(item.get('hero') or item.get('raw_name'), known)
            if not name:
                continue
            entry = {'hero': name}
            if with_index:
                entry['index'] = item.get('index')
            if with_gains:
                entry['pickGain'] = item.get('pick_gain')
                entry['winGain'] = item.get('win_gain')
            out.append(entry)
        return out

    def pack_group(items):
        out = []
        for item in items or []:
            heroes = item.get('heroes') or []
            names = [normalize(h, known) for h in heroes]
            if not names or len(names) != len(heroes) or any(not n for n in names):
                continue
            out.append({'heroes': names, 'index': item.get('index')})
        return out

    def pack_duo(items):
        """双排组合是 a/b 二元关系（{a, b, pickGain, winGain, index}）。"""
        out = []
        for item in items or []:
            a = normalize(item.get('a') or item.get('raw_a'), known)
            b = normalize(item.get('b') or item.get('raw_b'), known)
            if not a or not b or a == b:
                continue
            out.append({'heroes': [a, b], 'index': item.get('index'),
                        'pickGain': item.get('pick_gain'), 'winGain': item.get('win_gain')})
        return out

    doc = {'schema': 'bp-camp-counters-v1',
           'source': '王者营地 App 英雄关系（UI 抓取，公开展示数据）',
           'capturedAt': captured[-1] if captured else '',
           'heroes': {}}
    skipped = Counter()
    for row in rows:
        hero = normalize(row.get('hero_name') or row.get('page_hero_name'), known)
        if not hero:
            skipped[str(row.get('hero_name'))] += 1
            continue
        doc['heroes'][hero] = {
            'counters': pack_people(row.get('counters')),
            'counteredBy': pack_people(row.get('countered_by')),
            'duo': pack_duo(row.get('duo')),
            'trio': pack_group(row.get('trio')),
        }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, ensure_ascii=False), encoding='utf-8')

    # ── 交叉校验清单（只写进报告，不改种子表）────────────────────────
    # 营地页面的 role 字段标在「关系里的那个英雄」身上：把全部页面按英雄聚合
    # （同一英雄在几十个别人的页面上反复出现，role 一致），得到该英雄的职业口径，
    # 再与 hero_roles.py 种子表的 frontline 标签对照。冲突只列出，供人工复核。
    role_claims: dict[str, Counter] = {}
    for row in rows:
        for item in (row.get('counters') or []) + (row.get('countered_by') or []):
            hero = normalize(item.get('hero') or item.get('raw_name'), known)
            role = str(item.get('role') or '').strip()
            if hero and role:
                role_claims.setdefault(hero, Counter())[role] += 1
    conflicts = []
    for hero, claims in sorted(role_claims.items()):
        roles = set()
        for role, count in claims.items():
            if count >= 2:                    # 至少两处页面一致才采信
                roles.update(part.strip() for part in role.split('/') if part.strip())
        if not roles:
            continue
        tags = hero_roles.HERO_ROLES.get(hero)
        if tags is None:
            conflicts.append({'hero': hero, 'roles': sorted(roles), 'tagged': False,
                              'note': '种子表未收录'})
            continue
        tankish = bool(roles & {'坦克', '战士'})
        if tankish != bool(tags.get('frontline')):
            conflicts.append({'hero': hero, 'roles': sorted(roles),
                              'campFrontline': tankish,
                              'seedFrontline': bool(tags.get('frontline'))})

    report = {'heroes': len(doc['heroes']), 'captured': captured,
              'skipped': dict(skipped), 'seedConflicts': conflicts}
    (args.out.parent / 'camp_counters_report.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps({'heroes': report['heroes'], 'skipped': report['skipped'],
                      'seedConflicts': len(conflicts),
                      'out': str(args.out)}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
