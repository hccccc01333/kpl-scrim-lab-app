"""给本机所有王者营地载荷建字段档案（只读 AI 之外的原始 JSON）。

用法：
    python scripts/archive_camp_fields.py                 # 全量重建
    python scripts/archive_camp_fields.py --json          # 只打印摘要
    python scripts/archive_camp_fields.py --labels-only   # 只抽 H5 前端文案

产出：
    data/official_replays/<id>/fields.json    每条回放的字段表与中文文案
    data/official_replays/_fields-index.json  跨局合并的字段索引
    data/camp_labels.json                     营地 H5 前端的中文文案（含 dtID 名称）

营地接口只增字段、很少删；有这份档案，改版后可以直接 diff 出新增字段，
而不是等某个功能「读不到数」才发现。
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import camp_archive  # noqa: E402

REPLAYS = ROOT / 'data' / 'official_replays'
DETAILS = ROOT / 'data' / 'camp_details'
LISTS = ROOT / 'data' / 'camp_lists'
H5 = ROOT / '_h5' / 'app.js'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--json', action='store_true', help='只输出摘要 JSON')
    parser.add_argument('--labels-only', action='store_true', help='只重建前端文案')
    parser.add_argument('--limit', type=int, default=0, help='最多扫描多少条回放')
    args = parser.parse_args()

    labels = None
    if H5.is_file():
        labels = camp_archive.write_frontend_labels(H5, ROOT / 'data' / 'camp_labels.json')
        # 正本进仓库（前端包本身是第三方产物，不提交），便于评审与 diff
        (ROOT / 'docs' / 'camp_frontend_labels.json').write_text(
            json.dumps(labels, ensure_ascii=False, indent=1), encoding='utf-8')
    if args.labels_only:
        print(json.dumps({'labels': labels['count'] if labels else 0}, ensure_ascii=False))
        return 0

    index = camp_archive.scan(REPLAYS, limit=args.limit or None)
    (REPLAYS / '_fields-index.json').write_text(
        json.dumps(index, ensure_ascii=False, indent=1), encoding='utf-8')

    # 十人面板与战局清单同样存一份：三份载荷用同一套路径语法，便于一起检索。
    side = {}
    for name, folder, pattern in (('camp_details', DETAILS, '*.json'),
                                  ('camp_lists', LISTS, '*.json')):
        cases, fields = 0, {}
        for path in sorted(folder.glob(pattern))[: args.limit or None]:
            try:
                payload = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            cases += 1
            for row in camp_archive.inventory(payload):
                entry = fields.setdefault(row['path'], {'path': row['path'], 'cases': 0,
                                                        'count': 0, 'types': set()})
                entry['cases'] += 1
                entry['count'] += row['count']
                entry['types'].update(row['types'])
        side[name] = {'cases': cases, 'fields': len(fields)}

    summary = {'replays': index['cases'], 'replayFields': len(index['fields']),
               'replayTexts': len(index['texts']),
               'labels': labels['count'] if labels else 0, 'sources': side}
    (ROOT / 'data' / 'camp_fields_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
