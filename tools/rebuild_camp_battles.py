"""Rebuild team-fight details in camp replay normalized.json from local raw.json.

Why this exists
---------------
``camp_replay._key_event()`` used to read ``dtData`` for *every* key event.
Only ``dragontower`` rows have ``dtData``; ``battle`` rows carry ``battle`` and
``battleDetail`` instead.  As a result all 504 team fights in the existing
normalized files were flattened to ``timeSec=0 / kills=[]``, hiding the
per-kill hero ledger and per-fight per-player damage/taken/control numbers.

This script re-runs the corrected ``camp_replay._battles()`` against the raw
responses already on disk (no network, no account data), writes the result to
``normalized.json['battles']`` and repairs the ``events.key`` battle rows.

Safe by design
--------------
* read-only on raw.json / positions.json / meta.json
* idempotent (second run reports 0 changes)
* --dry-run prints the plan without writing
* backs up every normalized.json it is about to touch
* carries no account ids into the output (see _battles docstring)
"""
import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from camp_replay import _battles, _key_event, _int  # noqa: E402

REPLAYS = ROOT / 'data' / 'official_replays'
BACKUPS = ROOT / 'data' / 'backups'


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='只打印将要发生的变更，不写任何文件')
    args = parser.parse_args()

    folders = sorted(p for p in REPLAYS.glob('camp-*') if (p / 'raw.json').is_file())
    if not folders:
        parser.error(f'没有找到含 raw.json 的回放目录：{REPLAYS}')

    plan, totals = [], {'folders': 0, 'fights': 0, 'heroKills': 0,
                        'fightRows': 0, 'deathPoints': 0, 'fixedRows': 0}
    for folder in folders:
        raw = read_json(folder / 'raw.json')
        data = raw.get('data') or {}
        battles = _battles(data)
        norm_path = folder / 'normalized.json'
        norm = read_json(norm_path)

        # Repair the flattened battle rows in events.key, keeping order alignment.
        fixed = iter(_key_event(e) for e in data.get('keyEventArr') or []
                     if e.get('eventType') == 'battle' and isinstance(e.get('battle'), dict))
        old_key = norm.get('events', {}).get('key') or []
        new_key, fixed_rows = [], 0
        for event in old_key:
            if event.get('eventType') == 'battle':
                new_key.append(next(fixed, event))
                fixed_rows += 1
            else:
                new_key.append(event)
        new_key.extend(list(fixed))

        changed = norm.get('battles') != battles or new_key != old_key
        counts = battles['counts']
        plan.append((folder, norm_path, norm, battles, new_key, changed, fixed_rows, counts))

        # Cross-check: the per-kill ledger must reproduce final panel kill totals.
        panel_kills = sum(_int(p.get('killCnt')) for p in data.get('matchInfo') or [])
        if panel_kills != counts['heroKills']:
            print(f'  ! {folder.name}: 逐次击杀 {counts["heroKills"]} != 面板总击杀 {panel_kills}',
                  file=sys.stderr)

        if changed:
            totals['folders'] += 1
            for key in ('fights', 'heroKills', 'fightRows', 'deathPoints'):
                totals[key] += counts[key]
            totals['fixedRows'] += fixed_rows

    print(f'{"回放":<22}{"团战":>6}{"击杀":>7}{"明细行":>8}{"死亡点":>8}{"修复行":>8}  状态')
    for folder, _path, _norm, _b, _key, changed, fixed_rows, c in plan:
        print(f'{folder.name:<22}{c["fights"]:>6}{c["heroKills"]:>7}'
              f'{c["fightRows"]:>8}{c["deathPoints"]:>8}{fixed_rows:>8}  '
              f'{"将更新" if changed else "已是最新"}')
    print(f'\n合计：{len(folders)} 局，{totals["folders"]} 局将更新，'
          f'{totals["fights"]} 场团战 / {totals["heroKills"]} 次逐次英雄击杀 / '
          f'{totals["fightRows"]} 行团战明细 / {totals["deathPoints"]} 个死亡坐标 / '
          f'{totals["fixedRows"]} 行事件时间戳修复')
    if args.dry_run or not totals['folders']:
        return

    backup = BACKUPS / ('camp-battles-' + time.strftime('%Y%m%d-%H%M%S'))
    backup.mkdir(parents=True, exist_ok=False)
    for folder, path, norm, battles, new_key, changed, _fixed, _c in plan:
        if not changed:
            continue
        shutil.copy2(path, backup / f'{folder.name}__normalized.json')
        norm['battles'] = battles
        norm.setdefault('events', {})['key'] = new_key
        path.write_text(json.dumps(norm, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'已写入 {totals["folders"]} 个 normalized.json；备份在 {backup}')


if __name__ == '__main__':
    main()
