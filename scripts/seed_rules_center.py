"""把既有配置里的组合 / 阵容标签 / 自家克制对，初次灌入赛训规则中心的新表。

用途：规则中心（v3/public/rules-center.js）独立维护 2/3/5 人组合、纯表格阵容标签、
按赛事维度的克制关系；本脚本只做**一次性迁移种子**，不改动源文件、不动
counter_library.py 的算法与数据：

  data/facts/combo_pool.json       -> data/facts/rules_combos.json（2 / 3 人）
  data/facts/lineup_tags.json      -> data/facts/rules_lineup_tags.json
  data/facts/counter_library.json  -> data/facts/rules_counters.json（heroPairs）

默认只打印将要写入的条数（dry-run）；确认后加 --write 才落盘。
已非空的规则表不会被覆盖，避免误删教练在规则中心里的手工修改。

用法：
    python scripts/seed_rules_center.py            # 预览
    python scripts/seed_rules_center.py --write    # 落盘
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SPECS = {
    'combos': ('rules_combos.json', 'rules-center-combos-v1', 'combos'),
    'lineup_tags': ('rules_lineup_tags.json', 'rules-center-lineup-tags-v1', 'tags'),
    'counters': ('rules_counters.json', 'rules-center-counters-v1', 'heroPairs'),
}


def load(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def write_atomic(path, doc):
    import os
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='rules-seed-', suffix='.json', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(doc, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--facts', type=pathlib.Path, default=None, help='事实表目录（默认 bp_facts.FACTS）')
    ap.add_argument('--write', action='store_true', help='真正写入；默认只预览')
    args = ap.parse_args(argv)
    import bp_facts
    facts = args.facts or bp_facts.FACTS
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    report = {}

    # 1) 组合池：2 人 pairs + 3 人 trios → 统一 combos 表（按人数分层）。
    src = load(facts / 'combo_pool.json') or {}
    rows = []
    for key, size in (('pairs', 2), ('trios', 3)):
        for old in src.get(key) or []:
            heroes = [str(h) for h in (old.get('heroes') or []) if h]
            if not heroes:
                continue
            rows.append({
                'id': f'seed-{key}-{old.get("id") or len(rows) + 1}',
                'name': str(old.get('name') or '+'.join(heroes)),
                'size': size, 'heroes': heroes[:5], 'note': str(old.get('note') or ''),
                'effective': {'eventId': '', 'eventName': '', 'from': '', 'to': ''},
                'revision': 1,
                'history': [{'at': now, 'revision': 0, 'snapshot': {'source': f'combo_pool.json/{key}'}}],
            })
    report['combos'] = rows

    # 2) 阵容标签：纯表格自填自改（不带口述来源信息）。
    src = load(facts / 'lineup_tags.json') or {}
    tags = [{
        'id': f'seed-lt-{old.get("id") or i + 1}',
        'name': str(old.get('name') or '未命名'),
        'heroes': [str(h) for h in (old.get('heroes') or []) if h][:5],
        'note': str(old.get('note') or ''),
        'effective': {'eventId': '', 'eventName': '', 'from': '', 'to': ''},
        'revision': 1,
        'history': [{'at': now, 'revision': 0, 'snapshot': {'source': 'lineup_tags.json'}}],
    } for i, old in enumerate(src.get('tags') or [])]
    report['lineup_tags'] = tags

    # 3) 自家克制库：只取有向对，强度默认「中」，赛事留空 = 始终生效。
    #    新表与 counter_library.json 相互独立；此处只是把人工口径搬过来做起点。
    src = load(facts / 'counter_library.json') or {}
    pairs = [{
        'id': f'seed-cl-{old.get("id") or i + 1}',
        'a': str(old.get('a') or ''), 'b': str(old.get('b') or ''),
        'strength': '中', 'lane': '全部',
        'note': str(old.get('note') or ''),
        'effective': {'eventId': '', 'eventName': '', 'from': '', 'to': ''},
        'revision': 1,
        'history': [{'at': now, 'revision': 0, 'snapshot': {'source': 'counter_library.json'}}],
    } for i, old in enumerate(src.get('pairs') or []) if old.get('a') and old.get('b')]
    report['counters'] = pairs

    for kind in SPECS:
        file, schema, list_key = SPECS[kind]
        target = facts / file
        existing = load(target) or {}
        rows = report[kind]
        if existing.get(list_key) or (kind == 'counters' and (existing.get('heroPairs') or existing.get('comboPairs'))):
            print(f'{file}: 已有 {len(existing.get(list_key) or [])} 条，跳过（seed {len(rows)} 条未写入）')
            continue
        doc = {'schema': schema, 'revision': int(existing.get('revision') or 0),
               'updatedAt': now}
        if kind == 'counters':
            doc['heroPairs'], doc['comboPairs'] = rows, []
        else:
            doc[list_key] = rows
        if args.write:
            write_atomic(target, doc)
        print(f'{file}: {"已写入" if args.write else "预览"} {len(rows)} 条')

    if not args.write:
        print('（dry-run：加 --write 才落盘）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
