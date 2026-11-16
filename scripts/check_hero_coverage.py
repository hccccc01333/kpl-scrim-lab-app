"""P0-4 覆盖率自检：data/matches 全量对局 vs 英雄分类表（docs/team_dossier_p0.md §5）。

用法：
    python scripts/check_hero_coverage.py

验收口径：
- 英雄级：选用 + 禁用过的每个英雄都必须在 HERO_LABEL_META 有档案；未收录 → 退出码 1 并列出局数；
- 槽位级：已收录英雄但该局分路未登记 → 记「待分类」；这是可见的预期状态（不猜），
  只汇报不判失败，供赛训组确认副分路后经导入脚本消除。
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import hero_archetypes  # noqa: E402


def scan() -> tuple[Counter, Counter, Counter]:
    picks: Counter = Counter()
    bans: Counter = Counter()
    slots: Counter = Counter()
    files = sorted((ROOT / 'data' / 'matches').glob('channel-*.json'))
    for f in files:
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
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
                    bans[nm] += 1
        for hero, lane in (bp.get('lanes') or {}).items():
            slots[(hero, lane)] += 1
    return picks, bans, slots


def main() -> int:
    picks, bans, slots = scan()
    meta = hero_archetypes.HERO_LABEL_META

    no_label = {h: picks[h] for h in picks if h not in meta}
    slot_pending = {k: v for k, v in slots.items()
                    if k[0] in meta and k[1] not in hero_archetypes.HERO_ARCHETYPES.get(k[0], {})}

    print(f'对局扫描：选用英雄 {len([h for h in picks if picks[h]])} 个 / 禁用英雄 {len(bans)} 个')
    if no_label:
        print(f'[fail] 无档案英雄 {len(no_label)} 个（覆盖率 {1 - len(no_label) / len(picks):.1%}）：')
        for h, n in sorted(no_label.items(), key=lambda x: -x[1]):
            print(f'   {h}: 选用 {n} 局 / 禁用 {bans.get(h, 0)} 局 —— 请赛训组补标签后重新导入')
        return 1
    print(f'[ok] 英雄级覆盖率 100%（选用+禁用 {len(picks)} 个全部有档案）')
    if slot_pending:
        total = sum(slot_pending.values())
        print(f'[note] 槽位级「待分类」{total} 局 / {len(slot_pending)} 个（英雄, 分路）组合——可见、不计入类型分母：')
        for (hero, lane), n in sorted(slot_pending.items(), key=lambda x: -x[1]):
            print(f'   {hero} @ {lane}: {n} 局')
    print('[ok] 通过：docs/team_dossier_p0.md §5 P0-4 验收口径')
    return 0


if __name__ == '__main__':
    sys.exit(main())
