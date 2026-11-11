"""从营地面板导出战队 BP 分片（assets/team_bp/index.js + shard_0.js）。

参考站的战队 BP 读取：
  KPL_TEAM_BP_INDEX = {generatedAt, coverage, leagues, heroes, baselines, teams}
  KPL_TEAM_BP_SHARD = {队名: {name, icon, games, wins, scopes:{all:{games,wins,picks,bans,oppBans,heroes,combos}}, evidence}}
英雄行 [英雄索引, 选用次数, 己方禁用, …]；组合行 [A, B, 同队同局, 胜]。
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import team_clusters

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'web' / 'refsite' / 'assets' / 'team_bp'


def build(camp_dir: Path, own_name: str, db_path):
    panels = team_clusters.load_panels(camp_dir)
    clusters = team_clusters.list_teams(camp_dir, db_path, own_name)
    display = {team['id']: team['displayName'] for team in clusters['teams']}
    # 被合并走的签名跟随目标战队名
    overrides = team_clusters.load_overrides(db_path)
    for key, override in overrides.items():
        target = override.get('mergedInto')
        if target and target in display and key not in display:
            display[key] = display[target]
    heroes, hero_index = [], {}

    def idx(name):
        if name not in hero_index:
            hero_index[name] = len(heroes)
            heroes.append(name)
        return hero_index[name]

    # 每支「队」= 对面五人阵容签名的队名，用我们的对手命名（未命名的按序）
    teams = defaultdict(lambda: {'games': 0, 'wins': 0, 'picks': 0, 'bans': 0, 'oppBans': 0,
                                 'hero_picks': defaultdict(int), 'hero_bans': defaultdict(int),
                                 'pairs': defaultdict(lambda: [0, 0])})
    own_bucket = teams[own_name or '我方']

    for panel in panels:
        key = team_clusters.signature(panel)
        enemy = display.get(key, key)
        enemy_bucket = teams[enemy]
        for bucket, roles, win in ((own_bucket, panel['own_roster'], panel['win']),
                                   (enemy_bucket, panel['enemy_roster'], not panel['win'])):
            bucket['games'] += 1
            bucket['wins'] += 1 if win else 0
            picked = [item['hero'] for item in roles if item['hero']]
            bucket['picks'] += len(picked)
            for name in picked:
                bucket['hero_picks'][idx(name)] += 1
            for i, left in enumerate(picked):
                for right in picked[i + 1:]:
                    pair = tuple(sorted((left, right)))
                    bucket['pairs'][pair][0] += 1
                    if win:
                        bucket['pairs'][pair][1] += 1

    shard = {}
    team_rows = []
    for name, bucket in teams.items():
        hero_rows = []
        for hidx, count in bucket['hero_picks'].items():
            hero_rows.append([hidx, count, bucket['hero_bans'].get(hidx, 0), 0, 0, 0])
        hero_rows.sort(key=lambda row: -row[1])
        combos = [[hero_index[a], hero_index[b], n, wins]
                  for (a, b), (n, wins) in bucket['pairs'].items() if n >= 2]
        combos.sort(key=lambda row: -row[2])
        shard[name] = {
            'name': name, 'icon': '', 'games': bucket['games'], 'wins': bucket['wins'],
            'scopes': {'all': {
                'games': bucket['games'], 'wins': bucket['wins'], 'picks': bucket['picks'],
                'bans': bucket['bans'], 'oppBans': bucket['oppBans'],
                'heroes': hero_rows, 'combos': combos[:40],
            }},
            'evidence': {},
        }
        team_rows.append({'name': name, 'icon': '', 'games': bucket['games'],
                          'shard': 0, 'leagues': ['scrim-2026']})

    index = {
        'generatedAt': '', 
        'coverage': {'start': '', 'end': '', 'games': len(panels), 'fullGames': len(panels),
                     'partialGames': 0, 'series': 0, 'leagues': 1, 'teams': len(team_rows),
                     'teams10': len(team_rows), 'scannedBattles': len(panels),
                     'skipped': {}, 'orderSupported': False},
        'leagues': [{'id': 'scrim-2026', 'name': '训练赛', 'year': 2026}],
        'heroes': heroes,
        'baselines': {},
        'teams': team_rows,
    }
    return index, shard


def main():
    camp_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'data' / '_mock' / 'camp_details'
    own_name = sys.argv[2] if len(sys.argv) > 2 else '1'
    db_path = Path(sys.argv[3]) if len(sys.argv) > 3 else ROOT / 'data' / '_mock' / 'training.sqlite3'
    index, shard = build(camp_dir, own_name, db_path)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'index.js').write_text(
        'window.KPL_TEAM_BP_INDEX=' + json.dumps(index, ensure_ascii=False) + ';', encoding='utf-8')
    (OUT / 'shard_0.js').write_text(
        'window.KPL_TEAM_BP_SHARD=' + json.dumps(shard, ensure_ascii=False) + ';', encoding='utf-8')
    for old in OUT.glob('shard_*.js'):
        if old.name != 'shard_0.js':
            old.unlink()
    print(f'teams {len(shard)} · heroes {len(index["heroes"])} -> {OUT}')


if __name__ == '__main__':
    main()
