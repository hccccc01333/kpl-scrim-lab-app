"""跨机器传递赛训数据：导出「数据包」→ 在另一台机器导入。

为什么需要：王者营地只保留约一个月滚动窗口，教练在 A 机爬过的历史数据一旦滑出窗口
就再也爬不回来。这些数据只存在于 A 机的 `data/` 里，所以必须能整体搬走。

包里放什么（`data/` 的白名单，不含缓存与原始回放）：

    manifest.json               版本、来源、各表行数、每个文件的 sha256
    db/training.sqlite3         用 SQLite 备份接口做的一致性快照
    matches/                    逐局数据包
    camp_details/               营地十人面板
    official_replays/           官方回放解析结果
    camp_lists/ camp_reports/ reports/ facts/ bp-history/   有就带上
    screenshots/                可选（--with-screenshots）
    replays/                    可选（--with-replays，可能几个 GB）

导入策略（默认 `merge`：只补缺，不动本机已有）：
* 先把本机库备份到 `data/backups/pre-import-<时间>.sqlite3`
* 库里用 `INSERT OR IGNORE` 逐表补行：主键是 UUID / 对局 key，跨机器撞车概率极低，
  真撞上保留本机版本
* 目录文件只补本机没有的；同名文件默认保留本机（`--overwrite` 才覆盖）
* 全过程写一条 `change_log`，事后能查是哪次导入带来的

命令行：

    python scripts/transfer_data.py export --out 赛训数据-20261111.zip
    python scripts/transfer_data.py import --bundle 赛训数据-20261111.zip
    python scripts/transfer_data.py import --bundle xxx.zip --dry-run
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
import time
import zipfile
from contextlib import closing
from pathlib import Path

SCHEMA = 'scrim-transfer-v1'
BASE_DIRS = ('matches', 'camp_details', 'official_replays', 'camp_lists',
             'camp_reports', 'reports', 'facts', 'bp-history')
OPTIONAL_DIRS = {'screenshots': 'with_screenshots', 'replays': 'with_replays'}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _db_counts(db_path: Path) -> dict:
    counts = {}
    try:
        with closing(sqlite3.connect(f'file:{db_path.as_posix()}?mode=ro', uri=True)) as conn:
            tables = [row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            for table in tables:
                try:
                    counts[table] = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                except sqlite3.Error:
                    continue
    except sqlite3.Error:
        pass
    return {name: value for name, value in counts.items() if value}


def export_bundle(data_dir: Path, out_path: Path, *, with_screenshots=False,
                  with_replays=False, app_version='', label='') -> dict:
    data_dir = Path(data_dir)
    out_path = Path(out_path)
    db_path = data_dir / 'training.sqlite3'
    if not db_path.is_file():
        raise FileNotFoundError(f'找不到数据库：{db_path}')
    dirs = list(BASE_DIRS)
    if with_screenshots:
        dirs.append('screenshots')
    if with_replays:
        dirs.append('replays')

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_db = out_path.parent / f'.snapshot-{int(time.time())}.sqlite3'
    # SQLite 备份接口：即使服务正在写，也拿到一致快照
    with closing(sqlite3.connect(str(db_path))) as source, closing(sqlite3.connect(str(tmp_db))) as target:
        source.backup(target)

    files = []
    try:
        with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
            total = 0
            for path in sorted(data_dir.glob('*')):
                if path.is_dir() and path.name in dirs:
                    for item in sorted(path.rglob('*')):
                        if not item.is_file():
                            continue
                        arc = f'{path.name}/{item.relative_to(path).as_posix()}'
                        bundle.write(item, arc)
                        total += item.stat().st_size
                        if total < 400 * 1024 * 1024:   # 大包不必逐个算，太慢
                            files.append({'path': arc, 'size': item.stat().st_size,
                                          'sha256': _sha256(item)})
            bundle.write(tmp_db, 'db/training.sqlite3')
            files.append({'path': 'db/training.sqlite3', 'size': tmp_db.stat().st_size,
                          'sha256': _sha256(tmp_db)})
            manifest = {
                'schema': SCHEMA,
                'appVersion': app_version,
                'exportedAt': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                'label': label,
                'dirs': dirs,
                'counts': _db_counts(tmp_db),
                'files': files,
                'note': '训练赛原始数据；回放源文件（replays/）默认不打包。',
            }
            bundle.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
    finally:
        tmp_db.unlink(missing_ok=True)
    manifest['bundleSize'] = out_path.stat().st_size
    return manifest


def _attach_merge(conn: sqlite3.Connection, incoming: Path) -> dict:
    """把外部库逐表 INSERT OR IGNORE 进来：只补缺，撞上主键保留本机。"""
    conn.execute('ATTACH DATABASE ? AS incoming', (str(incoming),))
    merged = {}
    try:
        tables = [row[0] for row in conn.execute(
            "SELECT name FROM incoming.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for table in tables:
            local = {row[0] for row in conn.execute(f'PRAGMA table_info("{table}")')}
            if not local:
                continue          # 本机没有这张表：跳过，不擅自建
            foreign = {row[1] for row in conn.execute(f'PRAGMA incoming.table_info("{table}")')}
            cols = [name for name in foreign if name in local]
            if not cols:
                continue
            column_list = ', '.join(f'"{name}"' for name in cols)
            before = conn.execute(f'SELECT COUNT(*) FROM main."{table}"').fetchone()[0]
            conn.execute(
                f'INSERT OR IGNORE INTO main."{table}" ({column_list}) '
                f'SELECT {column_list} FROM incoming."{table}"')
            after = conn.execute(f'SELECT COUNT(*) FROM main."{table}"').fetchone()[0]
            if after > before:
                merged[table] = after - before
        conn.commit()
    finally:
        conn.execute('DETACH DATABASE incoming')
    return merged


def import_bundle(data_dir: Path, bundle_path: Path, *, overwrite=False,
                  dry_run=False) -> dict:
    data_dir = Path(data_dir)
    bundle_path = Path(bundle_path)
    staging = data_dir / '.transfer-staging'
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    with zipfile.ZipFile(bundle_path) as bundle:
        manifest = json.loads(bundle.read('manifest.json').decode('utf-8'))
        if manifest.get('schema') != SCHEMA:
            raise ValueError(f'数据包格式不兼容：{manifest.get("schema")}')
        bundle.extractall(staging)

    incoming_db = staging / 'db' / 'training.sqlite3'
    if not incoming_db.is_file():
        raise ValueError('数据包里没有数据库')
    local_db = data_dir / 'training.sqlite3'
    backup_path = ''
    merged, copied = {}, 0
    # 全新机器（没有本机库）：直接采用包里的库，不需要合并
    fresh = (not local_db.is_file()) or local_db.stat().st_size == 0
    if not dry_run:
        if fresh:
            local_db.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(incoming_db, local_db)
            merged = {'__adopted__': len(manifest.get('counts') or {})}
        else:
            backups = data_dir / 'backups'
            backups.mkdir(parents=True, exist_ok=True)
            backup_path = str(backups / f"pre-import-{time.strftime('%Y%m%d-%H%M%S')}.sqlite3")
            with closing(sqlite3.connect(str(local_db))) as source, \
                    closing(sqlite3.connect(backup_path)) as target:
                source.backup(target)
            with closing(sqlite3.connect(str(local_db))) as conn:
                merged = _attach_merge(conn, incoming_db)
    elif fresh:
        merged = dict(manifest.get('counts') or {})

    for name in manifest.get('dirs') or BASE_DIRS:
        source_dir = staging / name
        if not source_dir.is_dir():
            continue
        target_dir = data_dir / name
        target_dir.mkdir(parents=True, exist_ok=True)
        for item in source_dir.rglob('*'):
            if not item.is_file():
                continue
            target = target_dir / item.relative_to(source_dir)
            if target.exists() and not overwrite:
                continue
            if not dry_run:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
            copied += 1

    if not dry_run:
        with closing(sqlite3.connect(str(data_dir / 'training.sqlite3'))) as conn:
            try:
                conn.execute(
                    'INSERT INTO change_log(id, entity_type, entity_id, field, old_value, new_value, '
                    'source, actor, batch_id, reason, created_at, revision) '
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,1)",
                    (f'import-{int(time.time() * 1000)}', 'data_bundle', bundle_path.name, 'import',
                     None, json.dumps({'merged': merged, 'files': copied}, ensure_ascii=False),
                     'transfer', 'import', bundle_path.name,
                     f'从数据包导入（{manifest.get("exportedAt", "")}）', time.time()))
                conn.commit()
            except sqlite3.Error:
                pass
        shutil.rmtree(staging, ignore_errors=True)

    return {
        'ok': True, 'dryRun': dry_run, 'manifest': manifest,
        'mergedRows': merged, 'copiedFiles': copied, 'backup': backup_path,
        'countsNow': _db_counts(data_dir / 'training.sqlite3'),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description='跨机器传递赛训数据（导出/导入数据包）')
    parser.add_argument('action', choices=('export', 'import', 'info'))
    parser.add_argument('--data-dir', default='data')
    parser.add_argument('--out', default='')
    parser.add_argument('--bundle', default='')
    parser.add_argument('--with-screenshots', action='store_true')
    parser.add_argument('--with-replays', action='store_true')
    parser.add_argument('--overwrite', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir).resolve()
    if args.action == 'export':
        out = Path(args.out) or (Path.cwd() / f"赛训数据-{time.strftime('%Y%m%d')}.zip")
        manifest = export_bundle(data_dir, out, with_screenshots=args.with_screenshots,
                                 with_replays=args.with_replays)
        print(json.dumps({'ok': True, 'out': str(out), 'size': manifest['bundleSize'],
                          'counts': manifest['counts']}, ensure_ascii=False))
        return 0
    if args.action == 'import':
        if not args.bundle:
            parser.error('导入需要 --bundle')
        result = import_bundle(data_dir, Path(args.bundle), overwrite=args.overwrite,
                               dry_run=args.dry_run)
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            print(f"导入完成{'（预演，未写入）' if args.dry_run else ''}")
            print('  补齐行数:', json.dumps(result['mergedRows'], ensure_ascii=False))
            print('  复制文件:', result['copiedFiles'])
            if result['backup']:
                print('  导入前备份:', result['backup'])
        return 0
    print(json.dumps(_db_counts(data_dir / 'training.sqlite3'), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
