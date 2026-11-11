#!/usr/bin/env python3
"""KPL 官方赛事 BP 抓取 CLI：增量抓 `data/kpl/bp_games.jsonl` 并重建组合事实表。

默认行为：按 `--since-year` 过滤赛季 → 抓已完赛小局的 BP → 重建
`data/kpl/manifest.json` 与 `data/facts/kpl_combos.json`。重复执行幂等（battleId 去重）。

用法：
    python scripts/crawl_kpl_bp.py                          # 2024 起增量，抓完重建
    python scripts/crawl_kpl_bp.py --limit 20               # 只抓 20 局（试跑）
    python scripts/crawl_kpl_bp.py --since-year 2025 --leagues 20260004
    python scripts/crawl_kpl_bp.py --no-build               # 只抓数，不重建 facts
    python scripts/crawl_kpl_bp.py --refresh                # 重抓（覆盖已有行）
    python scripts/crawl_kpl_bp.py --dry-run                # 只算计划，不抓不写
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import kpl_bp  # noqa: E402  （依赖上面的 sys.path 注入）


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description='KPL 官方赛事 BP 抓取（增量落盘 + 组合事实重建）')
    parser.add_argument('--since-year', type=int, default=kpl_bp.DEFAULT_SINCE_YEAR,
                        help='只抓该年份及以后的赛季（默认 2024）')
    parser.add_argument('--leagues', default='',
                        help='逗号分隔的赛季过滤：league_id 精确匹配或名称子串，'
                             '例如 20260004,2026KPL夏季赛（默认全部）')
    parser.add_argument('--limit', type=int, default=0,
                        help='本次最多抓多少局新数据（0=不限；用于试跑）')
    parser.add_argument('--sleep', type=float, default=kpl_bp.DEFAULT_SLEEP,
                        help='每局之间的间隔秒数（默认 0.1，keep-alive 串行）')
    parser.add_argument('--no-build', action='store_true',
                        help='只抓数据，不重建 data/facts/kpl_combos.json')
    parser.add_argument('--build', action='store_true',
                        help='兼容写法：默认就会重建；显式指定无副作用')
    parser.add_argument('--refresh', action='store_true',
                        help='忽略增量跳过，重抓并覆盖已有 battleId 的行')
    parser.add_argument('--dry-run', action='store_true',
                        help='只拉赛季/赛程算抓取计划，不抓小局、不写文件')
    parser.add_argument('--min-games', type=int, default=kpl_bp.DEFAULT_MIN_GAMES,
                        help='双人/三人组合的最小场次门槛（默认 3；整阵容不受限）')
    parser.add_argument('--strict-players', dest='strict_players', action='store_true',
                        default=True, help='用十人面板交叉校验 pick 集合（默认开）')
    parser.add_argument('--no-strict-players', dest='strict_players', action='store_false',
                        help='关闭 pick 集合交叉校验（不建议）')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    only = [item for item in args.leagues.split(',') if item.strip()] if args.leagues else []
    try:
        result = kpl_bp.run_crawl(
            since_year=args.since_year,
            only_leagues=only,
            limit=args.limit,
            sleep=args.sleep,
            refresh=args.refresh,
            dry_run=args.dry_run,
            build=not args.no_build,
            min_games=args.min_games,
            strict_players=args.strict_players,
        )
    except kpl_bp.KplBpError as exc:
        print(f'[FAIL] {exc}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('[中断] 已落盘的部分保留；下次执行会自动续抓', file=sys.stderr)
        return 130

    crawl = result.get('crawl') or {}
    if result.get('dryRun'):
        print(json.dumps({
            'dryRun': True,
            'leagues': crawl.get('leagues'),
            'matches': crawl.get('matches'),
            'gamesPlanned': crawl.get('gamesPlanned'),
            'skippedExisting': crawl.get('skippedExisting'),
            'pending': crawl.get('pending'),
        }, ensure_ascii=False))
        return 0

    print('\n== 完成 ==')
    print(f'数据文件：{result["gamesPath"]}')
    manifest = result.get('manifest') or {}
    print(f'manifest：games={manifest.get("games")}  '
          f'window={manifest.get("windowStart")}~{manifest.get("windowEnd")}  '
          f'leagues={manifest.get("leagues")}  errors={manifest.get("errors")}')
    print(f'本次：新增 {crawl.get("added")}，已存在跳过 {crawl.get("skippedExisting")}，'
          f'错误 {crawl.get("errors")}，无效 {crawl.get("invalid")}，'
          f'mismatch {crawl.get("mismatch")}')
    facts = result.get('facts')
    if facts:
        print(f'facts：games={facts["games"]}  pairs={facts["pairs"]}  '
              f'trios={facts["trios"]}  lineups={facts["lineups"]}  '
              f'window={facts["windowStart"]}~{facts["windowEnd"]}  '
              f'leagues={facts["leagueCount"]}')
    else:
        print('facts：本次未重建（--no-build）')
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
