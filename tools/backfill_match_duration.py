"""把营地十人面板的对局时长回填到通道与已入库比赛包。

背景
----
`web/match-archive.js` 的比赛卡片读 `match.duration` 显示时长，
`analysis_data.py` 也用它算分均指标、时间轴覆盖率、场均时长与档案缺口。
但本机 11 局是早期采集的：`data/matches/channel-*.json` 里只有 1 局有
`match.duration`（693，来自官方回放挂载），其余 10 局是 `null`；通道
`match.durationSec` 同样只有 1 局有值。

`channel_store.bundle()` 用 `channel.match.durationSec` 生成比赛包的
`match.duration`，所以只改比赛包会在下次重建 bundle 时丢掉 —— 两处都要补。

真值来源是营地官方十人面板 `data/camp_details/<gameSeq>.json` 的
`data.battle.usedTime`（秒，官方结算时长），通过 `sources.camp.gameSeq`
精确关联。这是**实测值，不是估算、不是从时间轴外推**。

口径说明
--------
官方回放 `normalized.json` 的 `match.durationSec` 是回放长度，与结算时长
可能差 3–4 秒（例：面板 820 / 回放 816）。两者不是同一口径，本脚本
**只用营地面板 usedTime，不与回放时长混用**；已存在的值一律不覆盖。

用法
----
    python tools/backfill_match_duration.py --dry-run   # 只看会改什么
    python tools/backfill_match_duration.py             # 备份后写入

安全约束
--------
* 只读真值来源；写入前把 sqlite 与所有受影响的比赛包复制到
  `data/backups/match-duration-<时间戳>/`。
* 只填补 `None` / 0，绝不覆盖已有时长，不碰比分、胜负、身份、审核状态。
* 幂等：重复执行不会产生新变更。
* 通道保存语义与 `server._save_channel` 一致（revision + 1、append_log、
  updated_at），避免乐观锁或缓存不一致。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import channel_store as cs  # noqa: E402

DB = ROOT / 'data' / 'training.sqlite3'
DETAILS = ROOT / 'data' / 'camp_details'
MATCHES = ROOT / 'data' / 'matches'
BACKUPS = ROOT / 'data' / 'backups'
MIN_SEC, MAX_SEC = 180, 3600
SOURCE_TAG = 'camp-battledetail:usedTime'


def panel_seconds(detail):
    """读取营地 battledetail 的结算时长（秒），异常值一律拒绝。"""
    battle = ((detail or {}).get('data') or {}).get('battle') or {}
    value = cs._camp_number(battle.get('usedTime'))
    if value is None or not MIN_SEC <= value <= MAX_SEC:
        return None
    return int(round(value))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='只打印将要发生的变更，不写任何文件')
    args = parser.parse_args()

    if not DB.is_file():
        parser.error(f'找不到数据库 {DB}')
    connection = sqlite3.connect(DB)
    connection.row_factory = sqlite3.Row
    rows = connection.execute('SELECT id, revision, body, updated_at FROM channels').fetchall()

    changed_channels = []
    match_writes = {}
    report = []

    for row in rows:
        channel_id, body = row['id'], json.loads(row['body'])
        camp = (body.get('sources') or {}).get('camp') or {}
        game_seq = camp.get('gameSeq')
        panel_path = DETAILS / f'{game_seq}.json' if game_seq else None
        detail = json.loads(panel_path.read_text(encoding='utf-8')) if panel_path and panel_path.is_file() else None
        seconds = panel_seconds(detail)

        channel_match = body.setdefault('match', {})
        match_path = MATCHES / f'channel-{channel_id}.json'
        bundle = json.loads(match_path.read_text(encoding='utf-8')) if match_path.is_file() else None
        bundle_match = (bundle or {}).get('match') or {}

        # 通道已有的时长优先作为兜底（例如只有官方回放挂载、没有十人面板的局）
        existing = cs._camp_number(channel_match.get('durationSec'))
        if existing is not None and not MIN_SEC <= existing <= MAX_SEC:
            existing = None
        value = seconds if seconds is not None else (int(round(existing)) if existing is not None else None)
        tag = SOURCE_TAG if seconds is not None else 'channel:match.durationSec'

        channel_added = 0
        if value is not None and channel_match.get('durationSec') in (None, 0, ''):
            channel_match['durationSec'] = value
            channel_match['durationSource'] = tag
            channel_added += 1
        if seconds is not None and camp.get('usedTime') is None:
            camp['usedTime'] = seconds
            channel_added += 1

        match_added = 0
        if value is not None and bundle is not None:
            if bundle_match.get('duration') in (None, 0, ''):
                bundle_match['duration'] = value
                bundle_match['durationSource'] = tag
                match_added += 1
            bundle['match'] = bundle_match
            if match_added:
                match_writes[match_path] = bundle

        if channel_added:
            cs.append_log(body, 'backfill-match-duration', 'backfill-tool')
            body['revision'] = int(row['revision'] or 0) + 1
            changed_channels.append((channel_id, body, int(row['revision'] or 0) + 1))

        report.append((channel_id[:12], str(game_seq or '—')[:12],
                       seconds if seconds is not None else '—',
                       channel_added, match_added,
                       (channel_match.get('durationSec') or '—'),
                       (bundle_match.get('duration') or '—')))

    print(f'{"通道":<14}{"gameSeq":<14}{"面板秒":>7}{"通道写":>7}{"包写":>6}'
          f'{"最终通道":>10}{"最终比赛包":>12}')
    for channel_id, seq, seconds, a, b, cdur, mdur in report:
        print(f'{channel_id:<14}{seq:<14}{str(seconds):>7}{a:>7}{b:>6}{str(cdur):>10}{str(mdur):>12}')
    print(f'合计：{len(changed_channels)} 个通道、{len(match_writes)} 个比赛包将更新；'
          f'已有值一律不覆盖。真值来源：营地 battledetail usedTime（官方结算秒数）。')

    if args.dry_run:
        print('DRY RUN：未写入任何文件。')
        connection.close()
        return

    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    backup = BACKUPS / f'match-duration-{stamp}'
    backup.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DB, backup / 'training.sqlite3')
    (backup / 'matches').mkdir(exist_ok=True)
    for path in match_writes:
        shutil.copy2(path, backup / 'matches' / path.name)
    print(f'已备份到 {backup}')

    now = time.time()
    for channel_id, body, revision in changed_channels:
        connection.execute(
            'INSERT INTO channels(id,revision,body,created_at,updated_at) VALUES(?,?,?,?,?) '
            'ON CONFLICT(id) DO UPDATE SET revision=excluded.revision, '
            'body=excluded.body, updated_at=excluded.updated_at',
            (channel_id, revision, json.dumps(body, ensure_ascii=False),
             body.get('_createdAt') or now, now))
    connection.commit()
    for path, bundle in match_writes.items():
        path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    connection.close()
    print(f'已写入：{len(changed_channels)} 个通道、{len(match_writes)} 个比赛包。'
          f'需重启服务进程让内存缓存失效。')


if __name__ == '__main__':
    main()
