"""把赛训组的「KPL 赛训英雄标签（五路 12 类精简版）」工作簿导入为项目英雄标签表。

来源：教练提供的 xlsx（133 英雄，与 resources/catalog.json 同目录口径），
含三张本脚本消费的表：
  * 「133英雄赛事标签」 —— 英雄 ID / 默认分路 / 默认赛训类型（坦边、刺客野、工具人法师…）
  * 「英雄分路候选」   —— (英雄, 实际分路) → 该位置建议分类（打野位分野核系/坦野等）
  * 「能力矩阵_0-1」   —— 19 个 0/1 能力维度（前排/承伤/开团/反开/保护/控制/…）

产物 `resources/hero_tags.json`：十人面板的 10 分钟经济评级要按英雄类型给打野
分野核（800/分钟）与坦野（6800 总量）两套口径，游走不记录；`hero_roles.py` 的
能力种子表也按能力矩阵重新生成（见 scripts/rebuild_hero_roles.py）。

用法：
    python scripts/import_hero_tags.py --xlsx "<工作簿路径>"
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import date

from urllib.parse import unquote

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / 'resources' / 'hero_tags.json'


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--xlsx', required=True, help='赛训组英雄标签工作簿路径')
    ap.add_argument('--out', type=pathlib.Path, default=OUT)
    args = ap.parse_args(argv)

    import openpyxl

    wb = openpyxl.load_workbook(args.xlsx, data_only=True, read_only=True)

    def rows(sheet):
        for row in wb[sheet].iter_rows(min_row=2, values_only=True):
            if row and row[0] is not None:
                yield row

    # 1) 133 英雄赛事标签：默认分路 / 默认赛训类型 / 兼容定位
    heroes: dict[str, dict] = {}
    for row in rows('133英雄赛事标签'):
        hero_id, name, lane, _alt, dtype, compat = row[0], str(row[1]).strip(), row[2], row[3], row[4], row[5]
        if not name:
            continue
        heroes[name] = {'id': int(hero_id), 'defaultLane': lane or '',
                        'defaultType': str(dtype or '').strip(),
                        'compat': str(compat or '').strip(), 'lanes': {}}

    # 2) 英雄分路候选：(英雄, 实际分路) → 该位置建议分类
    for row in rows('英雄分路候选'):
        name, lane, dtype = str(row[1]).strip(), row[2], row[3]
        if name in heroes and lane and dtype:
            heroes[name]['lanes'][str(lane)] = str(dtype).strip()

    # 3) 能力矩阵：19 个 0/1 维度
    matrix_rows = list(rows('能力矩阵_0-1'))
    header = [c.value for c in next(wb['能力矩阵_0-1'].iter_rows(min_row=1, max_row=1))]
    dims = [str(col) for col in header[4:] if col]
    for row in matrix_rows:
        name = str(row[1]).strip()
        if name not in heroes:
            continue
        heroes[name]['matrix'] = {dim: int(bool(row[4 + i])) for i, dim in enumerate(dims)}

    doc = {
        'schema': 'scrim-hero-tags-v1',
        'source': '赛训组《KPL赛训英雄标签及逐局模板》2026-11',
        'sourceFile': unquote(pathlib.Path(args.xlsx).name),
        'importedAt': date.today().isoformat(),
        'capabilityDims': dims,
        'heroes': heroes,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, ensure_ascii=False), encoding='utf-8')
    jungle = {name: h['lanes'].get('打野') for name, h in heroes.items()
              if h['lanes'].get('打野')}
    print(json.dumps({'heroes': len(heroes), 'dims': len(dims),
                      'jungleTyped': len(jungle),
                      'jungleTypes': dict(sorted((t, sum(1 for v in jungle.values() if v == t))
                                                 for t in set(jungle.values()))),
                      'out': str(args.out)}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
