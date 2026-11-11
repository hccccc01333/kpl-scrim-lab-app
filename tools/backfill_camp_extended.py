"""把营地十人面板的 B 组扩展指标回填到已审核通道与已入库比赛包。

背景
----
`channel_store.CAMP_STAT_MAP` 与 `analysis_data` 已支持 7 项 B 组字段，
`docs/metric_registry.md` 也已把 B 组标为 ✅。但本机 11 局是在映射扩宽
**之前**采集的：`channels` 表里的 `sources.camp.players[].stats` 只有旧的
A 组 8 项，`data/matches/*.json` 的 `players[].final` 同样没有 B 组值，
所以正式分析行里 B 组覆盖率是 0/110。

原始面板 `data/camp_details/<gameSeq>.json` 仍完整保留 `battleStats`，可按
通道的 `sources.camp.gameSeq` 精确关联，按 (camp, slot) 逐人回填真值——
**不是估算、不是派生**。

用法
----
    python tools/backfill_camp_extended.py --dry-run   # 只看会改什么
    python tools/backfill_camp_extended.py             # 备份后写入

安全约束
--------
* 只读真值来源 `data/camp_details/*.json`；写入前把 sqlite 与所有受影响
  的比赛包复制到 `data/backups/camp-extended-<时间戳>/`。
* 只填补缺失 / None 的 B 组键，绝不覆盖已有值，绝不改 A 组、身份、昵称、
  比分、胜负、审核状态。
* 不把 `roleName` / `playerId` / `roleIcon` 等个人信息写进比赛包。
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
SIDE_TO_CAMP = {'left': 'blue', 'right': 'red'}
EXTENDED = tuple(cs.CAMP_EXTENDED_FIELDS)


def extended_panel(detail):
    """从营地 battledetail 抽出十人 B 组实测值：{(camp, slot): {field: value}}。"""
    data = (detail or {}).get('data') or {}
    out = {}
    for roles_key, camp in (('blueRoles', 'blue'), ('redRoles', 'red')):
        for slot, role in enumerate(data.get(roles_key) or []):
            stats = role.get('battleStats') or {}
            fields = {}
            for src, dst in cs.CAMP_STAT_MAP.items():
                if dst not in EXTENDED:
                    continue
                value = cs._camp_number(stats.get(src))
                if value is not None:
                    fields[dst] = value
            if fields:
                out[(camp, slot)] = fields
    return out


def fill(mapping, values):
    """只补缺失键，返回新增键数。"""
    added = 0
    for key, value in values.items():
        if mapping.get(key) is None:
            mapping[key] = value
            added += 1
    return added


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
        if not game_seq or not panel_path.is_file():
            report.append((channel_id[:12], '无营地面板', 0, 0, 0))
            continue

        detail = json.loads(panel_path.read_text(encoding='utf-8'))
        panel = extended_panel(detail)
        camp_players = camp.get('players') or []
        draft_players = (body.get('draft') or {}).get('players') or []

        # 1) 通道：原始 camp 面板（供以后 rebuild 复算）
        channel_added = 0
        for item in camp_players:
            values = panel.get((item.get('camp'), item.get('slot')))
            if values:
                channel_added += fill(item.setdefault('stats', {}), values)

        # 2) 通道：草稿 fields（供直接 bundle，不 rebuild 也不丢）
        draft_added = 0
        for item in draft_players:
            key = (SIDE_TO_CAMP.get(item.get('side')), item.get('slot'))
            values = panel.get(key)
            if not values:
                continue
            fields = item.setdefault('fields', {})
            for name, value in values.items():
                current = fields.get(name)
                if current is None or (isinstance(current, dict) and current.get('value') is None):
                    fields[name] = {'value': value, 'raw': str(value),
                                    'source': 'camp', 'confidence': 'high'}
                    draft_added += 1
        if 'sources' in body and camp:
            camp['extendedBackfilledAt'] = datetime.now().astimezone().isoformat()

        if channel_added or draft_added:
            cs.append_log(body, 'backfill-camp-extended', 'backfill-tool')
            body['revision'] = int(row['revision'] or 0) + 1
            changed_channels.append((channel_id, body, row['revision'], int(row['revision'] or 0) + 1))

        # 3) 已入库比赛包：players[].final —— analysis_data 直接读这里
        match_path = MATCHES / f'channel-{channel_id}.json'
        match_added = 0
        if match_path.is_file():
            match = json.loads(match_path.read_text(encoding='utf-8'))
            for player in match.get('players') or []:
                values = panel.get((player.get('camp'), player.get('slot')))
                if values:
                    match_added += fill(player.setdefault('final', {}), values)
            coverage = match.setdefault('coverage', {})
            for name in EXTENDED:
                coverage[name] = sum(
                    1 for player in match.get('players') or []
                    if (player.get('final') or {}).get(name) is not None
                )
            if match_added:
                match_writes[match_path] = match

        report.append((channel_id[:12], str(game_seq), channel_added, draft_added, match_added))

    # 报告
    print(f'{"通道":<14}{"gameSeq":<13}{"通道面板":>8}{"草稿":>7}{"比赛包":>8}')
    total = [0, 0, 0]
    for channel_id, seq, a, b, c in report:
        print(f'{channel_id:<14}{seq:<13}{a:>8}{b:>7}{c:>8}')
        total[0] += a
        total[1] += b
        total[2] += c
    print(f'合计：通道面板 +{total[0]}、草稿 +{total[1]}、比赛包 +{total[2]} 个字段；'
          f'{len(changed_channels)} 个通道、{len(match_writes)} 个比赛包将更新')
    print(f'预期正式分析行 B 组覆盖率：{total[2]} 个非零值（7 项 × 100 人 = 700 为满分）')

    if args.dry_run:
        print('DRY RUN：未写入任何文件。')
        connection.close()
        return

    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    backup = BACKUPS / f'camp-extended-{stamp}'
    backup.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DB, backup / 'training.sqlite3')
    (backup / 'matches').mkdir(exist_ok=True)
    for path in match_writes:
        shutil.copy2(path, backup / 'matches' / path.name)
    print(f'已备份到 {backup}')

    now = time.time()
    for channel_id, body, _old_revision, revision in changed_channels:
        connection.execute(
            'INSERT INTO channels(id,revision,body,created_at,updated_at) VALUES(?,?,?,?,?) '
            'ON CONFLICT(id) DO UPDATE SET revision=excluded.revision, '
            'body=excluded.body, updated_at=excluded.updated_at',
            (channel_id, revision, json.dumps(body, ensure_ascii=False),
             body.get('_createdAt') or now, now))
    connection.commit()
    for path, match in match_writes.items():
        path.write_text(json.dumps(match, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    connection.close()
    print(f'已写入：{len(changed_channels)} 个通道、{len(match_writes)} 个比赛包。'
          f'需重启服务进程让内存缓存失效。')


if __name__ == '__main__':
    main()
