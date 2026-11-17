#!/usr/bin/env python3
"""同步 KPL 战队队标到本机（resources/icons/teams）。

官方赛程接口的 camp 字段带 `team_icon`；一次抓全部赛季的赛程即可覆盖所有出场
战队。图片按 team_id 落盘，`index.json` 以战队名索引，前端按名字取图；没有
队标的战队前端会退回字母徽章，不影响任何统计口径。

用法：
    python scripts/sync_team_icons.py            # 增量：缺失才下载
    python scripts/sync_team_icons.py --refresh  # 全部重下
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import kpl_bp  # noqa: E402

TARGET = ROOT / 'resources' / 'icons' / 'teams'
INDEX = TARGET / 'index.json'


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='同步 KPL 战队队标')
    parser.add_argument('--refresh', action='store_true', help='已存在也重新下载')
    parser.add_argument('--since-year', type=int, default=2019,
                        help='只抓该年份及以后的赛季（默认 2019）')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    TARGET.mkdir(parents=True, exist_ok=True)
    session = kpl_bp.make_session()
    leagues = kpl_bp.fetch_leagues(session)
    selected = kpl_bp.select_leagues(leagues, since_year=args.since_year)
    teams = {}
    for league in selected:
        league_id = str(league.get('league_id') or league.get('id') or '')
        if not league_id:
            continue
        try:
            matches = kpl_bp.fetch_matches(session, league_id)
        except kpl_bp.KplBpError as error:
            print(f'[WARN] {league_id}: {error}', file=sys.stderr)
            continue
        for match in matches or []:
            for key in ('camp1', 'camp2'):
                camp = match.get(key) or {}
                name = str(camp.get('team_name') or '').strip()
                team_id = str(camp.get('team_id') or '').strip()
                icon = str(camp.get('team_icon') or '').strip()
                if not name or not team_id or not icon:
                    continue
                teams.setdefault(team_id, {
                    'name': name, 'abbr': str(camp.get('team_abbreviation') or ''),
                    'icon': icon,
                })
    index = {}
    downloaded = skipped = failed = 0
    for team_id, item in sorted(teams.items(), key=lambda pair: pair[1]['name']):
        suffix = Path(item['icon']).suffix or '.png'
        path = TARGET / f'{team_id}{suffix}'
        if args.refresh or not path.is_file() or path.stat().st_size == 0:
            try:
                response = session.get(item['icon'], timeout=30)
                response.raise_for_status()
                path.write_bytes(response.content)
                downloaded += 1
            except Exception as error:  # noqa: BLE001 - 单个队标失败不影响其余
                failed += 1
                print(f'[WARN] {item["name"]}: {error}', file=sys.stderr)
                continue
        else:
            skipped += 1
        index[item['name']] = f'/catalog/icons/teams/{path.name}'
        index.setdefault('_abbr', {})[item['name']] = item['abbr']
    payload = {'updatedAt': kpl_bp.now_iso(), 'teams': index,
               'count': len(index) - 1}
    INDEX.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                     encoding='utf-8')
    print(f'队标：{len(index) - 1} 支（下载 {downloaded} / 复用 {skipped} / '
          f'失败 {failed}）→ {TARGET}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
