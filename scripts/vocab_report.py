"""词表核对：把历史记录里的版本 / 规则 / 赛制 / 训练组列出来，给出规范值与影响面。

用法：
    python scripts/vocab_report.py            # 只出报告（默认，不改任何数据）
    python scripts/vocab_report.py --apply    # 把能改的写成规范值，并登记进词表

覆盖范围：
- `schedules` 表（约定计划的四条字段）——可直接改写
- `match_meta` 表（单局补录 / 预填确认的覆盖层）——可直接改写
- `matches` 表（结构化对局）——可直接改写
- `data/matches/*.json`（抓取来的原始对局）——**只报告**，改写走待确认页

词表逻辑全部在根目录 `vocab.py`，与后端写入路径共用一套归一化。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import vocab  # noqa: E402

DATA = ROOT / 'data'
DB = DATA / 'training.sqlite3'
FIELDS = (('session', 'sessions'), ('format', 'formats'), ('rules', 'rules'), ('version', 'versions'))
TABLE_FIELDS = {
    'schedules': ('session', 'format', 'rules', 'version'),
    'matches': ('session', 'version', 'rules'),
}


def _connect(data: Path):
    db = data / 'training.sqlite3'
    return sqlite3.connect(db) if db.is_file() else None


def _tables(connection):
    return {row[0] for row in connection.execute("select name from sqlite_master where type='table'")}


def _columns(connection, table):
    return [row[1] for row in connection.execute(f'pragma table_info("{table}")')]


def collect_db(connection):
    """按 (来源, 字段) 收集原始值。"""
    buckets = defaultdict(Counter)
    tables = _tables(connection)
    for table, fields in TABLE_FIELDS.items():
        if table not in tables:
            continue
        columns = set(_columns(connection, table))
        for field in fields:
            if field not in columns:
                continue
            for (value,) in connection.execute(
                    f'SELECT "{field}" FROM "{table}" WHERE "{field}" IS NOT NULL AND "{field}" <> ""'):
                buckets[(table, field)][str(value)] += 1
    if 'match_meta' in tables:
        for (body,) in connection.execute('SELECT body FROM match_meta'):
            try:
                meta = json.loads(body) if body else {}
            except (TypeError, ValueError):
                continue
            if not isinstance(meta, dict):
                continue
            for field, _kind in FIELDS:
                value = meta.get(field)
                if value:
                    buckets[('match_meta', field)][str(value)] += 1
    return buckets


def collect_files(data: Path):
    buckets = defaultdict(Counter)
    for path in sorted((data / 'matches').glob('*.json')):
        try:
            body = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        match = body.get('match') or {}
        for field in ('session', 'version', 'rules', 'format'):
            value = match.get(field)
            if value:
                buckets[('data/matches/*.json', field)][str(value)] += 1
    return buckets


def plan_actions(buckets, known):
    """返回 [(source, field, raw, canonical, count, in_vocab)]，只保留需要看的行。"""
    rows = []
    for (source, field), counter in sorted(buckets.items()):
        kind = dict(FIELDS).get(field)
        if not kind:
            continue
        for raw, count in counter.most_common():
            canonical = vocab.normalize(kind, raw, add=False)
            rows.append((source, field, raw, canonical, count, canonical in known.get(kind, [])))
    return rows


def apply_db(connection, buckets):
    """把规范值写回 DB；返回改写的行数。"""
    tables = _tables(connection)
    changed = 0
    if 'schedules' in tables:
        columns = set(_columns(connection, 'schedules'))
        for row_id, *values in connection.execute(
                'SELECT id, session, format, rules, version FROM schedules').fetchall():
            patch = {}
            for field, value in zip(('session', 'format', 'rules', 'version'), values):
                if field not in columns or not value:
                    continue
                canonical = vocab.normalize(dict(FIELDS)[field], value, add=False)
                if canonical and canonical != value:
                    patch[field] = canonical
            if patch:
                assignments = ', '.join(f'"{key}"=?' for key in patch)
                connection.execute(f'UPDATE schedules SET {assignments} WHERE id=?', (*patch.values(), row_id))
                changed += 1
    if 'match_meta' in tables:
        for match_key, body in connection.execute('SELECT match_key, body FROM match_meta').fetchall():
            try:
                meta = json.loads(body) if body else {}
            except (TypeError, ValueError):
                continue
            if not isinstance(meta, dict):
                continue
            touched = False
            for field, kind in FIELDS:
                if meta.get(field):
                    canonical = vocab.normalize(kind, meta[field], add=False)
                    if canonical and canonical != meta[field]:
                        meta[field] = canonical
                        touched = True
            if touched:
                connection.execute('UPDATE match_meta SET body=? WHERE match_key=?',
                                   (json.dumps(meta, ensure_ascii=False), match_key))
                changed += 1
    if 'matches' in tables:
        columns = set(_columns(connection, 'matches'))
        for match_key, *values in connection.execute(
                'SELECT match_key, session, version, rules FROM matches').fetchall():
            patch = {}
            for field, value in zip(('session', 'version', 'rules'), values):
                if field not in columns or not value:
                    continue
                canonical = vocab.normalize(dict(FIELDS)[field], value, add=False)
                if canonical and canonical != value:
                    patch[field] = canonical
            if patch:
                assignments = ', '.join(f'"{key}"=?' for key in patch)
                connection.execute(f'UPDATE matches SET {assignments} WHERE match_key=?', (*patch.values(), match_key))
                changed += 1
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='写回规范值（默认只出报告）')
    parser.add_argument('--data', default=str(DATA), help='数据目录，默认仓库下 data/')
    args = parser.parse_args()
    data = Path(args.data)

    known = vocab.load(data)
    connection = _connect(data)
    merged = defaultdict(Counter)
    if connection is not None:
        for key, counter in collect_db(connection).items():
            merged[key].update(counter)
    for key, counter in collect_files(data).items():
        merged[key].update(counter)

    rows = plan_actions(merged, known)
    if not rows:
        print('没有需要核对的版本 / 规则 / 赛制 / 训练组记录。')
    else:
        width = max(len(row[2]) for row in rows) + 2
        print(f'{"来源":<22}{"字段":<9}{"原始值":<{width}}{"次数":>4}  {"规范值":<{width}}词表')
        print('-' * (22 + 9 + width + 4 + 2 + width + 6))
        for source, field, raw, canonical, count, hit in rows:
            print(f'{source:<22}{field:<9}{raw:<{width}}{count:>4}  {canonical:<{width}}{"已有" if hit else "新增"}')
        changes = [row for row in rows if row[2] != row[3]]
        print(f'\n共 {len(rows)} 种写法，其中 {len(changes)} 种会被归一化。')

    if args.apply:
        if connection is None:
            print('没有找到数据库，跳过写回。')
            return
        with connection:
            changed = apply_db(connection, merged)
        for source, field, raw, canonical, _count, _hit in rows:
            # 原始对局文件只报告不改写；登记词表的只收数据库里的实际记录。
            if canonical and raw != canonical and not str(source).startswith('data/'):
                vocab.prepare(dict(FIELDS)[field], raw, data)
        print(f'已改写 {changed} 条记录，并把规范值登记进词表：{vocab.vocab_path(data)}')
    elif connection is not None:
        connection.close()


if __name__ == '__main__':
    main()
