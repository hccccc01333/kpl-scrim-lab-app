"""把已入库通道的营地 ban/pick 名单回填到通道与比赛包（一次性 / 幂等）。

背景：早期 attach_camp_detail 只抽了 banHeros，没抽 pickHeros，导出的比赛包
也不带 BP 字段，所以 BP 页一直显示 0 场。本脚本直接从本地
`data/camp_details/<gameSeq>.json` 重放，不需要重新爬取、不需要重新审核。

    python tools/backfill_camp_bp.py            # 备份后回填
    python tools/backfill_camp_bp.py --dry-run  # 只看会改什么
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import channel_store  # noqa: E402
from bp_camp import parse_camp_bp, structured_names  # noqa: E402

DB = Path(os.environ.get('TRAINING_DB', ROOT / 'data' / 'training.sqlite3'))
MATCHES_DIR = Path(os.environ.get('ANALYSIS_MATCHES', ROOT / 'data' / 'matches'))
DETAIL_DIR = Path(os.environ.get('CAMP_DETAIL_DIR', ROOT / 'data' / 'camp_details'))


def backup(root: Path) -> Path:
    stamp = time.strftime('%Y%m%d_%H%M%S')
    target = root / f'_backup_camp_bp_{stamp}'
    target.mkdir(parents=True, exist_ok=False)
    shutil.copy2(DB, target / DB.name)
    if MATCHES_DIR.is_dir():
        shutil.copytree(MATCHES_DIR, target / 'matches')
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description='回填营地 BP 名单')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--no-backup', action='store_true', help='已有备份时跳过')
    args = parser.parse_args(argv)

    if not DB.is_file():
        raise SystemExit(f'找不到数据库 {DB}')
    connection = sqlite3.connect(DB, timeout=30)
    channels = [(row[0], json.loads(row[1])) for row in
                connection.execute('SELECT id,body FROM channels').fetchall()]
    report = {'channels': len(channels), 'withCamp': 0, 'backfilled': 0,
              'bundles': 0, 'skipped': []}

    if not args.dry_run and not args.no_backup:
        report['backup'] = str(backup(DB.parent))
        print(f"已备份 → {report['backup']}")

    for channel_id, channel in channels:
        camp = (channel.get('sources') or {}).get('camp') or {}
        seq = str(camp.get('gameSeq') or '')
        if not seq:
            continue
        report['withCamp'] += 1
        detail_path = DETAIL_DIR / f'{seq}.json'
        if not detail_path.is_file():
            report['skipped'].append(f'{channel_id[:8]}: 缺 {detail_path.name}')
            continue
        try:
            detail = json.loads(detail_path.read_text(encoding='utf-8'))
            bp = parse_camp_bp(detail, seq)
        except (OSError, ValueError) as error:
            report['skipped'].append(f'{channel_id[:8]}: {error}')
            continue
        if not bp:
            report['skipped'].append(f'{channel_id[:8]}: 详情无 ban/pick')
            continue

        names = structured_names(bp)
        if not args.dry_run:
            camp['bp'] = bp
            camp['pickNames'] = {'blue': names['picks']['left'],
                                 'red': names['picks']['right']}
            channel.setdefault('sources', {})['camp'] = camp
            channel_store.append_log(
                channel, 'backfill-camp-bp', 'tools/backfill_camp_bp.py',
                {'gameSeq': seq,
                 'bans': sum(len(v) for v in names['bans'].values()),
                 'picks': sum(len(v) for v in names['picks'].values())})
            connection.execute(
                'UPDATE channels SET body=?,updated_at=? WHERE id=?',
                (json.dumps(channel, ensure_ascii=False), time.time(), channel_id))
        report['backfilled'] += 1

        bundle_path = MATCHES_DIR / f'channel-{channel_id}.json'
        if not bundle_path.is_file():
            report['skipped'].append(f'{channel_id[:8]}: 缺比赛包')
            continue
        body = json.loads(bundle_path.read_text(encoding='utf-8'))
        match = body.setdefault('match', {})
        changes = {'campBp': bp,
                   'opponent': match.get('opponent') or (channel.get('match') or {}).get('opponent'),
                   'session': match.get('session') or (channel.get('match') or {}).get('session'),
                   'winnerCamp': match.get('winnerCamp') or bp.get('winnerSide'),
                   'ownCamp': match.get('ownCamp') or bp.get('ownSide')}
        if not args.dry_run:
            for key, value in changes.items():
                if key == 'campBp' or value:
                    match[key] = value
            temporary = bundle_path.with_suffix('.bp-tmp')
            temporary.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding='utf-8')
            temporary.replace(bundle_path)
        report['bundles'] += 1
        print(f"  {channel_id[:8]} · {seq} · ban {sum(len(v) for v in names['bans'].values())}"
              f" / pick {sum(len(v) for v in names['picks'].values())}")

    if not args.dry_run:
        connection.commit()
        os.utime(MATCHES_DIR, None)
    connection.close()
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return report


if __name__ == '__main__':
    main()
