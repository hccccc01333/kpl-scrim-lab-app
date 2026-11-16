"""按赛训组能力矩阵重建 hero_roles.py 的种子表（一次性工具）。

`resources/hero_tags.json`（scripts/import_hero_tags.py 产物）里有赛训组给的
19 个 0/1 能力维度；本脚本把它们映射到 hero_roles 的 9 个能力口径并整表重写
`hero_roles.py` 的 HERO_ROLES 字典——之后阵容覆盖 / 短板 / 可补英雄全部基于
赛训组官方标签，覆盖 133 个英雄（原先人工种子表只有约 40 个）。

映射（一个源列只喂一个能力口径，不重复计数）：
    engage     ← 开团
    peel       ← 保护
    burst      ← 爆发
    sustained  ← 持续输出
    frontline  ← 前排 或 承伤
    waveclear  ← 清线
    roam       ← 支援 或 入侵
    macro      ← 推进 或 带线
    resilience ← 反开 或 续航

用法：
    python scripts/rebuild_hero_roles.py
"""
from __future__ import annotations

import json
import pathlib
import sys
from collections import OrderedDict

ROOT = pathlib.Path(__file__).resolve().parents[1]
TAGS = ROOT / 'resources' / 'hero_tags.json'
TARGET = ROOT / 'hero_roles.py'

MAPPING = OrderedDict([
    ('engage', ['开团']),
    ('peel', ['保护']),
    ('burst', ['爆发']),
    ('sustained', ['持续输出']),
    ('frontline', ['前排', '承伤']),
    ('waveclear', ['清线']),
    ('roam', ['支援', '入侵']),
    ('macro', ['推进', '带线']),
    ('resilience', ['反开', '续航']),
])

HEADER = '''"""英雄能力标签表（赛训组官方口径，2026-11 版）。

数据来自赛训组《KPL赛训英雄标签及逐局模板》的能力矩阵（133 英雄 × 19 个 0/1
维度），经 scripts/rebuild_hero_roles.py 映射成本模块的 9 个能力口径后整表生成；
手工调整请改工作簿后重跑该脚本，不要直接编辑下面的字典。

能力维度（与 docs/kpl_hit_logic.md / 评估报告 §2.2 对齐）：
- engage:   强开/先手开团        ← 开团
- peel:     保护后排/反开        ← 保护
- burst:    爆发输出             ← 爆发
- sustained: 持续输出            ← 持续输出
- frontline: 前排/承伤           ← 前排、承伤
- waveclear: 清线/转线           ← 清线
- roam:     游走/支援            ← 支援、入侵
- macro:    推塔/控龙/运营       ← 推进、带线
- resilience: 容错/脱战/反打     ← 反开、续航

用法：
    from hero_roles import HERO_ROLES, lineup_profile, gaps, substitutes
"""
from __future__ import annotations

CAPABILITIES = ('engage', 'peel', 'burst', 'sustained', 'frontline',
                'waveclear', 'roam', 'macro', 'resilience')

# 赛训组能力矩阵映射后的种子表（全部 133 个英雄；0/1 表示是否具备该能力）。
HERO_ROLES: dict[str, dict[str, int]] = {
'''


def main() -> int:
    doc = json.loads(TAGS.read_text(encoding='utf-8'))
    heroes = doc['heroes']
    lines = []
    for name in sorted(heroes):
        matrix = heroes[name].get('matrix') or {}
        tags = {cap: int(any(matrix.get(col) for col in cols))
                for cap, cols in MAPPING.items()}
        inner = ', '.join(f"'{cap}': {tags[cap]}" for cap in MAPPING)
        lines.append(f"    '{name}': {{{inner}}},")
    body = '\n'.join(lines)
    with TARGET.open(encoding='utf-8') as fh:
        old = fh.read()
    # 只替换字典段：从 "HERO_ROLES: dict[str, dict[str, int]] = {" 到收尾的 "}"（其后保留其余函数）
    marker_start = 'HERO_ROLES: dict[str, dict[str, int]] = {'
    start = old.index(marker_start)
    # 字典以单独一行 "}" 结束（其后是空行 + def）
    end = old.index('\n}\n', start) + len('\n}\n')
    tail = old[end:]
    new = HEADER + body + '\n}\n\n' + tail
    TARGET.write_text(new, encoding='utf-8')
    print(f'hero_roles.py 重建：{len(lines)} 个英雄')
    return 0


if __name__ == '__main__':
    sys.exit(main())
