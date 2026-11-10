"""Routes for the local analyst workspace and reproducible result snapshots."""
import asyncio
import hashlib
import html
import json
import pickle
import os
import re
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from sheet_import import SheetImportError, infer_profile, read_workbook, rebuild_profile, write_staging
from identity_auto import build_plan
import metric_service
import team_clusters
import vocab
from camp_time import camp_times

from studio_analysis import (DIMENSIONS, METHODS, METRICS, deduplicate, extract_rows,
                             finite, fingerprint, run_analysis, screenshot_rows, StudioRepository)
from studio_pipeline import DatasetStore, prepare
from studio_research import TOPICS, research


def camp_games(camp_details_dir, db_path=None):
    """营地十人面板逐局的「我方在哪边、对手是谁」清单，供对局分边页标注。

    我方阵营默认取 head.acntCamp（营地详情取数账号 = 本方选手账号，1=蓝 2=红，
    自动推断）；match_meta 里 match_key = 'camp:<gameSeq>' 的 ownCamp / opponent
    是教练的手动覆盖与对手命名，与 depth_api._camp_meta 读的是同一份覆盖层。
    """
    directory = Path(camp_details_dir)
    overrides = {}
    if db_path:
        try:
            connection = sqlite3.connect(db_path)
            try:
                rows = connection.execute(
                    "SELECT match_key, body FROM match_meta WHERE match_key LIKE 'camp:%'").fetchall()
            finally:
                connection.close()
        except sqlite3.OperationalError:
            rows = []
        for key, body in rows:
            try:
                overrides[str(key)[len('camp:'):]] = json.loads(body)
            except (TypeError, ValueError):
                continue
    games = []
    for path in sorted(directory.glob('*.json')):
        try:
            body = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        data = body.get('data') or {}
        head = data.get('head') or {}
        battle = data.get('battle') or {}
        override = overrides.get(path.stem) or {}
        own_camp = str(override.get('ownCamp') or '')
        source = 'manual' if own_camp in ('blue', 'red') else None
        if own_camp not in ('blue', 'red'):
            code = str(head.get('acntCamp') or '')
            own_camp = 'blue' if code == '1' else 'red' if code == '2' else ''
            source = 'auto' if own_camp else None
        result = head.get('gameResult')
        own_win = result if (own_camp and isinstance(result, bool)) else None
        times = camp_times(body)
        games.append({
            'key': f'camp:{path.stem}', 'id': path.stem,
            'date': times.get('date') or str(battle.get('startTime') or '')[:10],
            'start': times.get('startedAt') or battle.get('startTime') or '',
            'eventAt': times.get('eventAt'),
            'durationSec': times.get('durationSec'),
            'ownCamp': own_camp or None, 'ownCampSource': source,
            'opponent': str(override.get('opponent') or '') or None,
            'ownWin': own_win,
        })
    return games


def create_studio_router(db_path, matches_dir, imports_dir, results_db=None):
    router = APIRouter(prefix='/api/studio', tags=['studio'])
    results_db = Path(results_db or os.environ.get('STUDIO_RESULTS_DB') or Path(db_path).with_name('studio.sqlite3'))
    datasets = DatasetStore(results_db)
    # 版本 / 规则 / 赛制 / 训练组统一走词表：写库前折成规范值，新值自动登记。
    vocab_dir = Path(db_path).parent

    @router.get('/bp/{key}')
    def get_bp(key: str):
        match = repository().match_detail(key)
        if not match:
            raise HTTPException(404, '比赛不存在')
        return {'bp': match.get('bp') or {}}

    @router.post('/bp/{key}')
    def save_bp(key: str, value: dict):
        from bp_input import validate_bp
        try:
            bp = validate_bp(value.get('bp'))
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        match = repository().match_detail(key)
        if not match:
            raise HTTPException(404, '比赛不存在')
        if 'expectedBp' in value and (match.get('bp') or {}) != value['expectedBp']:
            raise HTTPException(409, 'BP 已在另一处修改，请刷新后核对再保存')
        if match.get('dbId'):
            with sqlite3.connect(db_path) as connection:
                connection.execute('BEGIN IMMEDIATE')
                row = connection.execute('SELECT body,revision FROM matches WHERE id=?', (match['dbId'],)).fetchone()
                if not row:
                    raise HTTPException(409, '比赛已变化，请刷新')
                body = json.loads(row[0])
                body.update(bp=bp, revision=row[1]+1, updatedAt=time.time())
                raw = json.dumps(body, ensure_ascii=False)
                connection.execute('UPDATE matches SET body=?,revision=? WHERE id=?', (raw, row[1]+1, match['dbId']))
                connection.execute('INSERT INTO revisions(match_id,saved_at,body) VALUES(?,?,?)', (match['dbId'],time.time(),raw))
        else:
            found = None
            for path in Path(matches_dir).glob('*.json'):
                try:
                    body = json.loads(path.read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    continue
                if (body.get('match') or {}).get('key', path.stem) == match.get('bundleKey', key):
                    found = (path, body)
                    break
            if not found:
                raise HTTPException(400, '该记录来自表格，请先采集为单局或通过通道补录 BP')
            path, body = found
            # Retain the complete previous file before the narrow BP amendment.
            history = Path(db_path).parent / 'bp-history'
            history.mkdir(parents=True, exist_ok=True)
            (history / f'{uuid.uuid4().hex}.json').write_bytes(path.read_bytes())
            body['match']['bp'] = bp
            temporary = path.with_suffix('.bp-tmp')
            temporary.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding='utf-8')
            temporary.replace(path)
            # Keep its capture draft aligned so a later channel save cannot undo BP.
            with sqlite3.connect(db_path) as connection:
                has_channels = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='channels'").fetchone()
                if has_channels:
                    import channel_store
                    for channel_id, channel_raw in connection.execute('SELECT id,body FROM channels').fetchall():
                        channel = json.loads(channel_raw)
                        if (channel.get('saved') or {}).get('bundleKey') != match.get('bundleKey'):
                            continue
                        channel_store.update_match(channel, {'bp': bp}, 'BP 补录')
                        channel['revision'] = int(channel.get('revision') or 0) + 1
                        connection.execute('UPDATE channels SET body=?,revision=?,updated_at=? WHERE id=?',
                                           (json.dumps(channel, ensure_ascii=False), channel['revision'],time.time(),channel_id))
        repository_cache['value'] = None
        result_cache.clear()
        # File content updates do not change directory mtime on every platform.
        if Path(matches_dir).is_dir():
            os.utime(matches_dir, None)
        return {'bp': bp, 'saved': True}

    repository_cache = {'key': None, 'value': None, 'at': 0.0}
    result_cache = {}
    data_cache_dir = Path(db_path).parent / '.studio-cache'
    data_cache_dir.mkdir(parents=True, exist_ok=True)

    def source_stamp(path):
        path = Path(path)
        try:
            stamp = path.stat().st_mtime_ns
            # Windows 上改写目录内文件不一定刷新目录 mtime；直接把包内 JSON
            # 的最新 mtime 计入，避免营地 BP 回填后仍读旧快照。
            if path.is_dir():
                stamp = max([stamp] + [item.stat().st_mtime_ns
                                       for item in path.glob('*.json')])
            return stamp
        except OSError:
            return 0

    def snapshot_key():
        return ('identity-raw-v7', source_stamp(db_path), source_stamp(matches_dir),
                source_stamp(imports_dir), source_stamp(results_db))

    def cached(key, builder):
        now = time.monotonic()
        entry = result_cache.get(key)
        if entry is not None and now - entry[0] < 30:
            return entry[1]
        value = builder()
        if len(result_cache) > 240:
            result_cache.clear()
        result_cache[key] = (now, value)
        return value

    def repository():
        # Short TTL cache: reuse the parsed snapshot for bursts of page/API calls;
        # any DB, match-file, import-directory or results change invalidates it.
        key = snapshot_key()
        now = time.monotonic()
        if (repository_cache['value'] is not None and repository_cache['key'] == key
                and now - repository_cache['at'] < 10):
            return repository_cache['value']
        value = StudioRepository(Path(db_path), Path(matches_dir), Path(imports_dir))
        cache_dir = data_cache_dir
        digest = hashlib.sha1(repr(key).encode('utf-8', 'replace')).hexdigest()[:16]
        cache_file = cache_dir / f'{digest}.pkl'
        if cache_file.is_file():
            try:
                value._data = pickle.loads(cache_file.read_bytes())
            except (OSError, pickle.PickleError, EOFError, AttributeError, ValueError):
                value._data = None
                cache_file.unlink(missing_ok=True)
        if value._data is None:
            value.get()
            try:
                temporary = cache_dir / f'.{digest}.tmp'
                temporary.write_bytes(pickle.dumps(value._data, protocol=4))
                temporary.replace(cache_file)
                old_files = sorted(cache_dir.glob('*.pkl'), key=lambda path: path.stat().st_mtime, reverse=True)
                for stale in old_files[2:]:
                    stale.unlink(missing_ok=True)
            except (OSError, pickle.PickleError, TypeError, ValueError):
                pass
        repository_cache.update(key=key, value=value, at=now)
        return value

    def dataset(spec):
        dataset_name = spec.get('dataset', 'records')
        filters = spec.get('filters') or {}
        if not isinstance(filters, dict):
            raise ValueError('筛选条件格式无效')
        filters = {k: v for k, v in filters.items() if k in
                   ('from', 'to', 'player', 'hero', 'position', 'opponent', 'version', 'session', 'result', 'camp',
                    'sources', 'includePartial', 'excludeSeeds', 'ownOnly', 'campOnly')}
        if any(not isinstance(v, str) for k, v in filters.items()
               if k not in ('sources', 'includePartial', 'excludeSeeds', 'ownOnly', 'campOnly')):
            raise ValueError('筛选值必须是文本')
        if 'sources' in filters and (not isinstance(filters['sources'], list) or any(s not in ('db', 'bundle', 'sheet') for s in filters['sources'])):
            raise ValueError('数据来源无效')
        if dataset_name == 'screenshots':
            rows = screenshot_rows(db_path)
            for name, key in [('hero', 'hero'), ('camp', 'camp'), ('player', 'label')]:
                if filters.get(name):
                    rows = [r for r in rows if r.get(key) == filters[name]]
            if filters.get('from'):
                rows = [r for r in rows if r.get('date') and r['date'] >= filters['from']]
            if filters.get('to'):
                rows = [r for r in rows if r.get('date') and r['date'] <= filters['to']]
            warnings = ['截图候选仅用于探索，不与比赛记录混算；昵称、阵营及同局关系需复核。']
            if spec.get('method') == 'prediction':
                raise ValueError('赛前模型只使用比赛记录，不使用截图候选')
        elif dataset_name == 'records':
            repo = repository()
            rows, warnings = extract_rows(repo, filters)
            if filters.get('ownOnly'):
                rows = [r for r in rows if r.get('isOwn')]
            if not filters.get('includePartial'):
                rows = [r for r in rows if r.get('full')]
            if filters.get('from') or filters.get('to'):
                rows = [r for r in rows if r.get('dateFull') and r.get('dateKey')]
        elif isinstance(dataset_name, str) and dataset_name.startswith('prepared:'):
            snapshot = datasets.get(dataset_name.split(':', 1)[1])
            if snapshot is None:
                raise ValueError('清洗数据集不存在')
            rows = [dict(r) for r in snapshot['rows']]
            if not filters.get('includePartial'):
                rows = [r for r in rows if r.get('full')]
            for name, key in [('hero', 'hero'), ('camp', 'camp'), ('version', 'version'), ('opponent', 'opponent'), ('player', 'playerKey')]:
                if filters.get(name):
                    rows = [r for r in rows if r.get(key) == filters[name]]
            if filters.get('from'):
                rows = [r for r in rows if r.get('dateFull') and r.get('dateKey') and r['dateKey'] >= filters['from']]
            if filters.get('to'):
                rows = [r for r in rows if r.get('dateFull') and r.get('dateKey') and r['dateKey'] <= filters['to']]
            warnings = [f'清洗数据集：{snapshot["title"]}；指纹 {snapshot["fingerprint"][:12]}。']
            if snapshot.get('exploratory'):
                warnings.append('该数据集由截图候选整理而来，仍属于探索数据。')
                if spec.get('method') == 'prediction':
                    raise ValueError('截图候选清洗后仍不能用于赛前胜负模型')
        else:
            raise ValueError('数据集无效')
        scope = spec.get('scope', 'all')
        if scope not in ('all', 'own'):
            raise ValueError('分析对象无效')
        if scope == 'own':
            rows = [r for r in rows if r.get('isOwn')]
        return rows, warnings

    def workspace_payload():
        repo = repository()
        data = repo.get()
        # Match bundles can carry optional final fields. Only pay to enrich
        # rows when bundles actually exist; the scale path is database-only.
        has_bundles = any(repo.matches_dir.glob('*.json'))
        if has_bundles:
            rows, warnings = extract_rows(repo, {'sources': ['db', 'bundle', 'sheet']})
        else:
            rows, warnings = repo._selected_rows({'sources': ['db', 'bundle', 'sheet']})
        unique, duplicates = deduplicate(rows)
        # Rows normally share one of a few coverage signatures (full record,
        # partial record, imported sheet). Grouping by signature avoids 21
        # numeric coercions per row on a 100k-row workspace.
        metric_keys = list(METRICS)
        coverage = {}
        for row in rows:
            signature = (tuple(row.get(key) is not None for key in metric_keys), bool(row.get('full')))
            coverage[signature] = coverage.get(signature, 0) + 1
        counts = {key: [0, 0] for key in metric_keys}
        for (signature, full), count in coverage.items():
            for index, key in enumerate(metric_keys):
                if signature[index]:
                    counts[key][0] += count
                    if full:
                        counts[key][1] += count
        if not has_bundles:
            # extract_rows normally adds these derived fields. Count them from
            # their source columns instead of copying/enriching every row.
            counts['damageConversion'] = [0, 0]
            counts['takenPerDeath'] = [0, 0]
            for row in rows:
                full = bool(row.get('full'))
                if row.get('damage') is not None and row.get('gold') is not None:
                    counts['damageConversion'][0] += 1
                    if full:
                        counts['damageConversion'][1] += 1
                if row.get('taken') is not None and row.get('deaths') is not None:
                    counts['takenPerDeath'][0] += 1
                    if full:
                        counts['takenPerDeath'][1] += 1
        metrics = [{'key': key, 'label': label, 'unit': unit,
                    'available': counts[key][0], 'complete': counts[key][1]}
                   for key, (label, unit) in METRICS.items()]
        return {'overview': repo.overview({}, include_top=False), 'filters': repo.filters(), 'metrics': metrics,
                'dimensions': [{'key': k, 'label': v} for k, v in DIMENSIONS.items()],
                'methods': [{'key': k, 'name': n, 'description': d, 'category': c} for k, n, d, c in METHODS],
                'duplicates': duplicates, 'uniqueContentMatches': len({r['matchKey'] for r in unique}),
                'identity': {'bound': sum(bool(r.get('bound')) for r in rows), 'rows': len(rows)},
                'recent': repo.matches({}).get('matches', [])[:8],
                'datasets': datasets.list(),
                'topics': [{'key': key, 'name': name, 'description': description} for key, name, description in TOPICS],
                'warnings': list(dict.fromkeys(data['warnings'] + warnings))}

    @router.get('/match-meta')
    def get_match_meta():
        try:
            with sqlite3.connect(db_path) as connection:
                rows = connection.execute('SELECT match_key, body FROM match_meta').fetchall()
        except sqlite3.Error:
            return {'meta': {}}
        meta = {}
        for key, body in rows:
            try:
                meta[key] = json.loads(body)
            except (TypeError, ValueError):
                continue
        return {'meta': meta}

    @router.post('/match-meta/{key:path}')
    def save_match_meta(key: str, value: dict):
        """补录比赛档案：对手、时长、训练组、赛果。原始记录不改，写覆盖层。"""
        if not key or len(key) > 200:
            raise HTTPException(400, '比赛标识无效')
        patch = {}

        def text(name, limit):
            if name in value:
                raw = value.get(name)
                if raw is not None and not isinstance(raw, str):
                    raise HTTPException(400, f'{name} 必须是文本')
                cleaned = (raw or '').strip()
                if len(cleaned) > limit:
                    raise HTTPException(400, '内容过长')
                patch[name] = cleaned

        text('opponent', 50)
        text('session', 40)
        text('title', 120)
        text('version', 40)
        text('mode', 20)
        text('venue', 40)
        text('note', 500)
        if 'duration' in value:
            raw = value.get('duration')
            if raw in (None, ''):
                patch['duration'] = None
            else:
                try:
                    minutes = float(raw)
                except (TypeError, ValueError):
                    raise HTTPException(400, '时长必须是分钟数') from None
                if not 0 < minutes <= 180:
                    raise HTTPException(400, '时长需在 0–180 分钟之间')
                patch['duration'] = round(minutes, 2)
        if 'result' in value:
            if value.get('result') not in ('win', 'loss', 'draw', 'unknown'):
                raise HTTPException(400, '赛果取值无效')
            patch['result'] = value['result']
        if 'ownCamp' in value:
            # 本队这一局在蓝方还是红方；空值表示恢复自动判断。
            if value.get('ownCamp') not in ('blue', 'red', '', None):
                raise HTTPException(400, '阵营取值无效')
            patch['ownCamp'] = value['ownCamp'] or None
        if not patch:
            raise HTTPException(400, '没有需要保存的字段')

        with sqlite3.connect(db_path) as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT body FROM match_meta WHERE match_key=?', (key,)).fetchone()
            merged = {}
            if row:
                try:
                    merged = json.loads(row[0])
                except (TypeError, ValueError):
                    merged = {}
            merged.update(patch)
            connection.execute(
                'INSERT INTO match_meta(match_key, body, updated_at) VALUES(?,?,?) '
                'ON CONFLICT(match_key) DO UPDATE SET body=excluded.body, updated_at=excluded.updated_at',
                (key, json.dumps(merged, ensure_ascii=False), time.time()))
        repository_cache['value'] = None
        result_cache.clear()
        return {'ok': True, 'key': key, 'meta': merged}

    @router.post('/match-meta')
    def save_match_meta_batch(value: dict):
        """批量补录：一次把同一批比赛的对手/训练组写进去。"""
        keys = value.get('keys') or []
        patch = value.get('patch') or {}
        if not isinstance(keys, list) or not keys or len(keys) > 200:
            raise HTTPException(400, '请选择 1–200 场比赛')
        if not isinstance(patch, dict) or not patch:
            raise HTTPException(400, '没有需要保存的字段')
        fail = []
        for key in keys:
            try:
                save_match_meta(str(key), patch)
            except HTTPException as error:
                fail.append({'key': key, 'detail': error.detail})
        return {'ok': not fail, 'saved': len(keys) - len(fail), 'failed': fail}

    @router.post('/profile')
    def save_profile(value: dict):
        """队伍建档：队名、教练、赛季。队员名单仍走 /api/settings，避免两套写入。"""
        with sqlite3.connect(db_path) as connection:
            row = connection.execute('SELECT body FROM settings WHERE id=1').fetchone()
            if not row:
                raise HTTPException(400, '设置尚未初始化')
            settings = json.loads(row[0])
            team_name = value.get('teamName')
            if team_name is not None:
                if not isinstance(team_name, str) or not team_name.strip() or len(team_name.strip()) > 50:
                    raise HTTPException(400, '请填写 1–50 字的战队名称')
                settings['teamName'] = team_name.strip()
            for key, limit in (('coach', 30), ('season', 40), ('organization', 60)):
                if key in value:
                    raw = value.get(key)
                    if raw is not None and not isinstance(raw, str):
                        raise HTTPException(400, f'{key} 必须是文本')
                    cleaned = (raw or '').strip()
                    if len(cleaned) > limit:
                        raise HTTPException(400, '内容过长')
                    settings[key] = cleaned
            connection.execute('UPDATE settings SET body=? WHERE id=1',
                               (json.dumps(settings, ensure_ascii=False),))
        repository_cache['value'] = None
        result_cache.clear()
        return {'ok': True, 'teamName': settings.get('teamName'),
                'coach': settings.get('coach', ''), 'season': settings.get('season', '')}

    @router.get('/workspace')
    def workspace():
        key = ('workspace', snapshot_key())
        now = time.monotonic()
        entry = result_cache.get(key)
        if entry is not None and now - entry[0] < 30:
            return entry[1]
        digest = hashlib.sha1(repr(key).encode('utf-8', 'replace')).hexdigest()[:16]
        path = data_cache_dir / f'workspace-{digest}.json'
        if path.is_file():
            try:
                payload = json.loads(path.read_text(encoding='utf-8'))
                result_cache[key] = (now, payload)
                return payload
            except (OSError, ValueError):
                path.unlink(missing_ok=True)
        payload = workspace_payload()
        try:
            temporary = data_cache_dir / f'.workspace-{digest}.tmp'
            temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
            temporary.replace(path)
            old_files = sorted(data_cache_dir.glob('workspace-*.json'),
                               key=lambda item: item.stat().st_mtime, reverse=True)
            for stale in old_files[2:]:
                stale.unlink(missing_ok=True)
        except (OSError, TypeError, ValueError):
            pass
        result_cache[key] = (now, payload)
        return payload

    @router.post('/dataset')
    def preview(value: dict):
        try:
            rows, warnings = dataset(value)
            if value.get('deduplicate', True):
                rows, duplicates = deduplicate(rows)
            else:
                duplicates = []
            entity = value.get('entity') or {}
            if entity:
                kind, name = entity.get('kind'), entity.get('name')
                if kind not in ('player', 'hero') or not isinstance(name, str) or not name:
                    raise ValueError('实体筛选无效')
                if kind == 'player':
                    rows = [row for row in rows if row.get('label') == name]
                else:
                    rows = [row for row in rows if row.get('hero') == name]
            total = len(rows)
            compact = bool(value.get('compact'))
            result = {'total': total, 'matches': len({r['matchKey'] for r in rows}),
                      'rows': [{k: v for k, v in r.items() if k != 'process'} for r in rows[:1000]],
                      'duplicates': [] if compact else duplicates, 'warnings': warnings,
                      'truncated': len(rows) > 1000, 'compact': compact,
                      'coverage': {} if compact else {key: sum(finite(r.get(key)) is not None for r in rows) for key in METRICS},
                      'groupValues': {} if compact else {key: sorted({str(r.get(key) or '未填写') for r in rows}) for key in DIMENSIONS}}
            return result
        except (ValueError, TypeError) as error:
            raise HTTPException(400, str(error)) from error

    def calculate(value):
        rows, warnings = dataset(value)
        if value.get('topic'):
            repo = repository()
            result = research(rows, value['topic'], value.get('metric', 'damage'),
                              repo.get()['matches'] + repo.get()['sheetMatches'])
            result.update(schema='kpl-studio-result-v1', status='ok' if result['rows'] else 'insufficient',
                          reason='当前样本尚未满足该专题所需的身份、分路、指标或过程覆盖条件', required=1, available=len(result['rows']))
            result['meta'] = {'engineVersion': 'studio-1', 'method': 'topic:'+value['topic'],
                              'metrics': [value.get('metric', 'damage')], 'rows': len(rows),
                              'inputRows': len(rows), 'matches': result['matches'],
                              'fingerprint': fingerprint(rows), 'duplicates': deduplicate(rows)[1],
                              'generatedAt': datetime.now(timezone.utc).isoformat(), 'warnings': []}
        else:
            result = run_analysis(rows, value)
        result['meta']['warnings'] = warnings + result['meta']['warnings']
        result['spec'] = value
        return result

    @router.post('/run')
    def run(value: dict):
        try:
            return calculate(value)
        except (ValueError, TypeError, OverflowError) as error:
            raise HTTPException(400, str(error)) from error

    def prepared(value):
        source = value.get('source') or {'dataset': 'records', 'filters': {'includePartial': True}}
        if not isinstance(source, dict):
            raise ValueError('来源设置无效')
        rows, warnings = dataset(source)
        result = prepare(rows, value.get('rules'), value.get('edits'))
        expected = value.get('sourceFingerprint')
        if expected and expected != result['sourceFingerprint']:
            raise HTTPException(409, '源数据已变化，请重新预览再发布')
        result['warnings'] = warnings
        return result

    @router.post('/clean/preview')
    def clean_preview(value: dict):
        try:
            result = prepared(value)
            return {**result, 'rows': result['rows'][:200], 'truncated': len(result['rows']) > 200}
        except (ValueError, TypeError) as error:
            raise HTTPException(400, str(error)) from error

    @router.get('/datasets')
    def list_datasets():
        return {'datasets': datasets.list()}

    @router.post('/datasets')
    def save_dataset(value: dict):
        title = value.get('title')
        if not isinstance(title, str) or not title.strip() or len(title) > 120:
            raise HTTPException(400, '请填写 1–120 字的数据集名称')
        if not value.get('sourceFingerprint'):
            raise HTTPException(400, '请先预览清洗结果')
        try:
            result = prepared(value)
            if not result['rows']:
                raise ValueError('空数据集不能发布')
            return datasets.save(title.strip(), result, value.get('source') or {})
        except (ValueError, TypeError) as error:
            raise HTTPException(400, str(error)) from error

    @router.get('/datasets/{dataset_id}')
    def dataset_detail(dataset_id: str):
        value = datasets.get(dataset_id)
        if value is None:
            raise HTTPException(404, '数据集不存在')
        return {**value, 'rows': value['rows'][:200]}

    @router.post('/research')
    def topical_research(value: dict):
        try:
            return calculate({**value, 'topic': value.get('topic', 'hero_pool')})
        except (ValueError, TypeError) as error:
            raise HTTPException(400, str(error)) from error

    @router.get('/view/{section}')
    def view(section: str, request: Request):
        methods = {'matches': 'matches', 'players': 'player_stats', 'heroes': 'hero_stats',
                   'process': 'process', 'lane-matchups': 'lane_matchups', 'bp': 'bp_summary',
                   'objectives': 'objectives', 'scouting': 'scouting'}
        if section not in methods:
            raise HTTPException(404, '分析页面不存在')
        filters = {k: request.query_params[k] for k in ('from', 'to', 'player', 'hero', 'position', 'opponent', 'version', 'session', 'result', 'camp') if request.query_params.get(k)}
        filters['sources'] = [s for s in request.query_params.get('source', 'db,bundle').split(',') if s in ('db', 'bundle', 'sheet')]
        filters['includePartial'] = request.query_params.get('includePartial') == '1'
        if request.query_params.get('own') == '1':
            filters['ownOnly'] = True
        if request.query_params.get('campOnly') == '1':
            filters['campOnly'] = True
        if section == 'bp' and request.query_params.get('campFirst') == '1':
            filters['campFirst'] = True
        if request.query_params.get('excludeSeeds') == '1':
            filters['excludeSeeds'] = True
        result = cached(('view', section, json.dumps(filters, sort_keys=True), snapshot_key()),
                        lambda: getattr(repository(), methods[section])(filters))
        if section in ('players', 'heroes'):
            if section == 'heroes' and request.query_params.get('compact') == '1':
                # The hero list/detail UI never consumes the per-hero match-key
                # array; at 10k matches it dominates the payload.
                result = [{key: value for key, value in row.items() if key != 'matches'} for row in result]
            result = {section: result}
        if section == 'matches':
            query = (request.query_params.get('q') or '').strip().lower()
            matches = result.get('matches', [])
            if query:
                matches = [match for match in matches
                           if query in ' '.join(str(match.get(key) or '') for key in
                                                ('title', 'opponent', 'date', 'session', 'key', 'source', 'version')).lower()]
            total = len(matches)
            summary = {
                'total': total,
                'wins': sum(1 for match in matches if match.get('result') == 'win'),
                'losses': sum(1 for match in matches if match.get('result') == 'loss'),
                'unknown': sum(1 for match in matches if match.get('result') not in ('win', 'loss', 'draw')),
                'complete': sum(1 for match in matches if match.get('complete')),
                'sources': len({match.get('source') for match in matches if match.get('source')}),
            }
            try:
                limit = max(0, min(500, int(request.query_params.get('limit', '0') or 0)))
                offset = max(0, int(request.query_params.get('offset', '0') or 0))
            except ValueError as error:
                raise HTTPException(400, '分页参数无效') from error
            if limit:
                matches = matches[offset:offset + limit]
            result = {**result, 'matches': matches, 'total': total, 'summary': summary,
                      'offset': offset, 'limit': limit}
        return result

    @router.get('/rows')
    def rows(request: Request):
        """Lightweight per-row preview for list/detail pages.

        The analysis dataset intentionally deduplicates and computes coverage
        over every row. List pages only need a bounded sample, so they use this
        path instead of paying that cost on every render.
        """
        filters = {k: request.query_params[k] for k in ('from', 'to', 'player', 'hero', 'position', 'opponent', 'version', 'session', 'result', 'camp') if request.query_params.get(k)}
        filters['sources'] = [s for s in request.query_params.get('source', 'db,bundle').split(',') if s in ('db', 'bundle', 'sheet')]
        filters['includePartial'] = request.query_params.get('includePartial') == '1'
        if request.query_params.get('excludeSeeds') == '1':
            filters['excludeSeeds'] = True
        if request.query_params.get('own') == '1':
            filters['ownOnly'] = True
        if request.query_params.get('campOnly') == '1':
            filters['campOnly'] = True
        kind = request.query_params.get('kind') or ''
        name = request.query_params.get('name') or ''
        recent_first = request.query_params.get('sort') == 'recent'
        if kind and kind not in ('player', 'hero'):
            raise HTTPException(400, '实体类型无效')
        try:
            limit = max(1, min(2000, int(request.query_params.get('limit', '200') or 200)))
        except ValueError as error:
            raise HTTPException(400, '行数参数无效') from error

        def build():
            selected, _ = repository()._selected_rows(filters)
            if filters.get('ownOnly'):
                selected = [row for row in selected if row.get('isOwn')]
            if not filters.get('includePartial'):
                selected = [row for row in selected if row.get('full')]
            if filters.get('from') or filters.get('to'):
                selected = [row for row in selected if row.get('dateFull') and row.get('dateKey')]
            if kind == 'player':
                selected = [row for row in selected if row.get('label') == name]
            elif kind == 'hero':
                selected = [row for row in selected if row.get('hero') == name]
            if recent_first:
                selected.sort(key=lambda row: (bool(row.get('dateFull')), row.get('dateKey') or '',
                                               row.get('matchKey') or ''), reverse=True)
            return {'total': len(selected),
                    'matches': len({row.get('matchKey') for row in selected if row.get('matchKey')}),
                    'rows': [{key: value for key, value in row.items() if key != 'process'}
                             for row in selected[:limit]]}

        result = cached(('rows', kind, name, limit, recent_first, json.dumps(filters, sort_keys=True), snapshot_key()), build)
        return {**result, 'truncated': result['total'] > len(result['rows']), 'limit': limit}

    @router.get('/identity')
    def identity():
        data = repository().get()
        camp_list = camp_games(Path(matches_dir).parent / 'camp_details', db_path)
        groups = {}
        for row in data.get('rows', []):
            if not row.get('isOwn') or not row.get('label'):
                continue
            label = row.get('rawLabel') or row['label']
            item = groups.setdefault(label, {'label': label, 'rows': 0,
                                              'matches': set(), 'heroes': set(), 'lastDate': ''})
            item['rows'] += 1
            if row.get('matchKey'):
                item['matches'].add(row['matchKey'])
            if row.get('hero'):
                item['heroes'].add(row['hero'])
            if row.get('date') and row['date'] > item['lastDate']:
                item['lastDate'] = row['date']
        unbound = [{'label': item['label'], 'rows': item['rows'], 'matches': len(item['matches']),
                    'heroes': sorted(item['heroes']), 'lastDate': item['lastDate'],
                    'matchKeys': sorted(item['matches'])}
                   for item in groups.values()]
        unbound.sort(key=lambda item: (-item['matches'], -item['rows'], item['label']))
        aliases = data.get('aliases', {})
        unbound_labels = {row.get('rawLabel') or row.get('label') for row in data.get('rows', []) if row.get('isOwn') and not row.get('bound')}
        match_teams = []
        for match in sorted([item for item in data.get('matches', []) + data.get('sheetMatches', [])
                             if len(item.get('players') or []) >= 2],
                            key=lambda item: (str(item.get('date') or item.get('dateKey') or ''),
                                              len(item.get('players') or [])),
                            reverse=True)[:5]:
            own_camp = match.get('ownCamp')
            camps = []
            for player in match['players']:
                camp = player.get('camp') or player.get('side')
                if camp and camp not in camps:
                    camps.append(camp)
            sides = []
            for camp in camps:
                players = sorted([player for player in match['players']
                                  if (player.get('camp') or player.get('side')) == camp],
                                 key=lambda player: (player.get('slot') is None, player.get('slot') or 0))
                is_own = camp == own_camp
                sides.append({
                    'camp': camp,
                    'side': 'left' if camp in ('blue', 'left') else 'right',
                    'isOwn': is_own,
                    'teamName': ((data.get('teamName') or '我的战队') if is_own else
                                 (match.get('opponent') or '对手待填写') if own_camp else
                                 ('蓝方' if camp in ('blue', 'left') else '红方')),
                    'players': [{'label': player.get('rawLabel') or player.get('label'),
                                 'displayLabel': player.get('label'),
                                 'hero': player.get('hero'), 'position': player.get('position'),
                                 'slot': player.get('slot'), 'playerId': player.get('playerId'),
                                 'bound': bool(player.get('playerId') or player.get('bound'))}
                                for player in players],
                })
            match_teams.append({'key': match.get('key'), 'date': match.get('date'),
                                'title': match.get('title'), 'opponent': match.get('opponent'),
                                'ownCamp': own_camp, 'sides': sides})
        # 场次元数据：前端按对局折叠待认领昵称时，用 matchKeys 关联到日期/标题/开赛时间。
        # startTime 多数历史数据为空；有值时前端据此推断上午 / 下午 / 晚间，无值不臆造。
        match_meta = {}
        for match in list(data.get('matches') or []) + list(data.get('sheetMatches') or []):
            key = match.get('key') or match.get('matchKey')
            if not key:
                continue
            raw_date = match.get('date') or match.get('dateKey') or ''
            if isinstance(raw_date, dict):
                raw_date = raw_date.get('text') or ''
            match_meta[key] = {
                'date': str(raw_date)[:10],
                'title': str(match.get('title') or ''),
                'opponent': str(match.get('opponent') or ''),
                'session': str(match.get('session') or ''),
                'startTime': str(match.get('startTime') or ''),
                'duration': match.get('duration'),
            }
        return {'unbound': [item for item in unbound if item['label'] in unbound_labels], 'identities': unbound, 'aliases': aliases,
                'enemyAliases': (data.get('profile') or {}).get('enemyAliases') or {},
                'teamName': data.get('teamName'), 'roster': data.get('roster', {}),
                'matchTeams': match_teams, 'matchMeta': match_meta,
                'campGames': camp_list,
                'campMeta': {'games': len(camp_list),
                             'named': sum(1 for g in camp_list if g['opponent']),
                             'manual': sum(1 for g in camp_list if g['ownCampSource'] == 'manual')}}

    @router.post('/identity/auto-claim')
    async def identity_auto_claim(request: Request):
        """自动认领预览（只读）：教练的判断作为 decisions 传入，落库由前端走既有接口。"""
        try:
            body = await request.json()
        except (ValueError, TypeError):
            body = {}
        if not isinstance(body, dict):
            raise HTTPException(400, '请求格式无效')
        decisions = body.get('decisions') or {}
        if not isinstance(decisions, dict) or len(decisions) > 200:
            raise HTTPException(400, '教练判断格式无效')
        try:
            with sqlite3.connect(db_path) as connection:
                row = connection.execute('SELECT body FROM settings WHERE id=1').fetchone()
            settings = json.loads(row[0]) if row else {}
        except (sqlite3.Error, ValueError):
            settings = {}
        return build_plan(repository().get(), settings,
                          max_diff=body.get('maxDiff', 1), decisions=decisions)

    @router.post('/import/preview')
    async def import_preview(request: Request, name: str = ''):
        suffix = Path(name).suffix.lower()
        if suffix not in ('.csv', '.tsv', '.xlsx', '.xlsm'):
            raise HTTPException(400, '只支持 CSV、TSV、XLSX 或 XLSM')
        payload = await request.body()
        if len(payload) > 20 * 1024 * 1024:
            raise HTTPException(400, '表格文件请小于 20 MB')
        folder = Path(imports_dir)
        previews = folder / '.previews'
        previews.mkdir(parents=True, exist_ok=True)
        for old in previews.glob('*'):
            try:
                if old.is_file() and time.time() - old.stat().st_mtime > 3600:
                    old.unlink()
            except OSError:
                pass
        preview_id = uuid.uuid4().hex
        temporary = previews / f'{preview_id}{suffix}'
        try:
            temporary.write_bytes(payload)
            workbook = read_workbook(temporary)
            sheets = workbook.get('sheets') or []
            if not sheets:
                raise SheetImportError('表格中没有可读取的工作表')
            result = []
            for sheet in sheets:
                profile = infer_profile(sheet)
                result.append({'name': sheet['name'], 'rows': len(sheet['rows']),
                               'header': sheet['header'], 'sample': sheet['rows'][:5],
                               'grain': profile.get('grain'),
                               'columns': profile.get('columns', []),
                               'unmappedColumns': profile.get('unmappedColumns', []),
                               'warnings': profile.get('warnings', [])})
        except SheetImportError as error:
            temporary.unlink(missing_ok=True)
            raise HTTPException(400, str(error)) from error
        return {'previewId': preview_id, 'source': name, 'sheets': result}

    @router.post('/import/commit')
    def import_commit(value: dict):
        preview_id = str(value.get('previewId') or '')
        mapping = value.get('mapping') or {}
        if not re.fullmatch(r'[a-f0-9]{32}', preview_id) or not isinstance(mapping, dict):
            raise HTTPException(400, '导入预览标识或映射无效')
        previews = Path(imports_dir) / '.previews'
        files = [path for path in previews.glob(preview_id + '*') if path.is_file()]
        if not files:
            raise HTTPException(404, '预览文件已过期，请重新选择表格')
        temporary = files[0]
        try:
            workbook = read_workbook(temporary)
            sheets = workbook.get('sheets') or []
            if not sheets:
                raise SheetImportError('表格中没有可读取的工作表')
            profiles = {}
            for sheet in sheets:
                overrides = mapping.get(sheet['name'])
                if overrides is not None and not isinstance(overrides, dict):
                    raise SheetImportError(f'{sheet["name"]} 的列映射无效')
                profiles[sheet['name']] = rebuild_profile(
                    sheet, infer_profile(sheet), overrides or {})
            out = Path(imports_dir) / workbook['source']['sha256'][:16]
            manifest = write_staging(workbook['source'], sheets, profiles, out, 'manual')
        except SheetImportError as error:
            raise HTTPException(400, str(error)) from error
        finally:
            temporary.unlink(missing_ok=True)
        return {'staged': out.name, 'manifest': manifest, 'quality': manifest.get('quality'),
                'warnings': manifest.get('warnings', []),
                'sheets': [{'name': sheet['name'], 'rows': sheet['rowCount'],
                            'grain': sheet.get('grain'), 'aggregated': sheet.get('aggregated'),
                            'unmappedColumns': sheet.get('unmappedColumns', [])}
                           for sheet in manifest.get('sheets', [])]}

    @router.post('/import/sheet')
    async def import_sheet(request: Request, name: str = ''):
        suffix = Path(name).suffix.lower()
        if suffix not in ('.csv', '.tsv', '.xlsx', '.xlsm'):
            raise HTTPException(400, '只支持 CSV、TSV、XLSX 或 XLSM')
        payload = await request.body()
        if len(payload) > 20 * 1024 * 1024:
            raise HTTPException(400, '表格文件请小于 20 MB')
        folder = Path(imports_dir)
        folder.mkdir(parents=True, exist_ok=True)
        temporary = folder / f'.upload-{uuid.uuid4().hex}{suffix}'
        try:
            temporary.write_bytes(payload)
            workbook = read_workbook(temporary)
            sheets = workbook.get('sheets') or []
            if not sheets:
                raise SheetImportError('表格中没有可读取的工作表')
            profiles = {sheet['name']: infer_profile(sheet) for sheet in sheets}
            out = folder / workbook['source']['sha256'][:16]
            manifest = write_staging(workbook['source'], sheets, profiles, out, 'inferred')
        except SheetImportError as error:
            raise HTTPException(400, str(error)) from error
        finally:
            temporary.unlink(missing_ok=True)
        return {'staged': out.name, 'manifest': manifest, 'quality': manifest.get('quality'),
                'warnings': manifest.get('warnings', []),
                'sheets': [{'name': sheet['name'], 'rows': sheet['rowCount'],
                            'grain': sheet.get('grain'), 'aggregated': sheet.get('aggregated'),
                            'unmappedColumns': sheet.get('unmappedColumns', [])}
                           for sheet in manifest.get('sheets', [])]}

    @router.get('/match/{key:path}')
    def match_detail(key: str):
        result = repository().match_detail(key)
        if result is None:
            raise HTTPException(404, '比赛记录不存在')
        return result

    @router.get('/capture/{key}')
    def capture_detail(key: str):
        rows = [r for r in screenshot_rows(db_path) if r['matchKey'] == key]
        if not rows:
            raise HTTPException(404, '截图组不存在')
        return {'rows': rows, 'images': rows[0].get('evidence', [])}

    def result_connection():
        results_db.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(results_db, timeout=10)
        connection.execute('CREATE TABLE IF NOT EXISTS reports (id TEXT PRIMARY KEY, title TEXT NOT NULL, note TEXT NOT NULL, created_at TEXT NOT NULL, body TEXT NOT NULL)')
        return connection

    @router.get('/reports')
    def reports():
        if not results_db.is_file():
            return {'reports': []}
        with result_connection() as connection:
            values = connection.execute('SELECT id,title,note,created_at,body FROM reports ORDER BY created_at DESC').fetchall()
        return {'reports': [{'id': row[0], 'title': row[1], 'note': row[2], 'createdAt': row[3],
                             'method': json.loads(row[4])['meta']['method'],
                             'matches': json.loads(row[4])['meta']['matches']} for row in values]}

    @router.get('/backup')
    def backup():
        values = []
        if results_db.is_file():
            with result_connection() as connection:
                values = connection.execute('SELECT id,title,note,created_at,body FROM reports ORDER BY created_at').fetchall()
        return JSONResponse({'schema': 'kpl-studio-backup-v1', 'datasets':datasets.backup(), 'reports': [
            {'id': r[0], 'title': r[1], 'note': r[2], 'createdAt': r[3], 'result': json.loads(r[4])} for r in values]},
            headers={'Content-Disposition': 'attachment; filename="studio-research-backup.json"'})

    @router.post('/restore')
    def restore(value: dict):
        reports = value.get('reports')
        if value.get('schema') != 'kpl-studio-backup-v1' or not isinstance(reports, list) or len(reports) > 5000:
            raise HTTPException(400, '不是有效的研究记录备份')
        records = []
        for report in reports:
            if not isinstance(report, dict) or not isinstance(report.get('result'), dict):
                raise HTTPException(400, '备份条目无效')
            result = report['result']
            if result.get('schema') != 'kpl-studio-result-v1' or not isinstance(result.get('meta'), dict) or result.get('status') != 'ok':
                raise HTTPException(400, '备份分析结果无效')
            for key, limit in [('id', 80), ('title', 120), ('note', 4000), ('createdAt', 80)]:
                if not isinstance(report.get(key), str) or len(report[key]) > limit or (key != 'note' and not report[key]):
                    raise HTTPException(400, '备份记录字段无效')
            if (result.get('meta') or {}).get('method') not in ({m[0] for m in METHODS} | {'topic:'+t[0] for t in TOPICS}) or not isinstance(result.get('rows'), list) or not isinstance(result.get('columns'), list):
                raise HTTPException(400, '备份结果结构无效')
            meta = result['meta']
            if not isinstance(meta.get('matches'), int) or meta['matches'] < 0 or not isinstance(meta.get('fingerprint'), str):
                raise HTTPException(400, '备份样本信息无效')
            if not all(isinstance(c, str) for c in result['columns']) or not all(isinstance(r, dict) for r in result['rows']):
                raise HTTPException(400, '备份表格结构无效')
            if not isinstance(meta.get('warnings'), list) or not all(isinstance(w, str) for w in meta['warnings']):
                raise HTTPException(400, '备份说明格式无效')
            records.append((report['id'], report['title'], report['note'], report['createdAt'], json.dumps(result, ensure_ascii=False)))
        try:
            dataset_restore = datasets.restore(value.get('datasets', []))
        except (ValueError, TypeError) as error:
            raise HTTPException(400, str(error)) from error
        added = 0
        with result_connection() as connection:
            for record in records:
                cursor = connection.execute('INSERT OR IGNORE INTO reports VALUES (?,?,?,?,?)', record)
                added += cursor.rowcount
        return {'added': added, 'skipped': len(records)-added, 'datasets': dataset_restore}

    @router.get('/project-backup')
    def project_backup(request: Request):
        provider = getattr(request.app.state, 'source_backup', None)
        if provider is None:
            raise HTTPException(503, '项目备份入口尚未挂载')
        provided = provider()
        source = json.loads(provided.body) if isinstance(provided, Response) else provided
        research_backup = json.loads(backup().body)
        bundles = []
        for path in Path(matches_dir).glob('*.json'):
            try:
                body=json.loads(path.read_text(encoding='utf-8'))
                if body.get('schema')=='kpl-match-data-v1':
                    bundles.append({'name':path.name,'body':body})
            except (ValueError,OSError):
                continue
        return JSONResponse({**source, 'studio':research_backup, 'analysisBundles':bundles,
                             'backupCoverage':'数据库及其材料、分析包、清洗数据集、研究记录；原始录屏目录与 CLI 表格导入目录需单独备份。'},
                            headers={'Content-Disposition':'attachment; filename="scrim-project-backup.json"'})

    @router.post('/project-restore')
    def project_restore(value: dict, request: Request):
        provider = getattr(request.app.state, 'source_restore', None)
        if provider is None:
            raise HTTPException(503, '项目恢复入口尚未挂载')
        bundles=value.get('analysisBundles',[])
        if not isinstance(bundles,list) or len(bundles)>10000:
            raise HTTPException(400,'分析包备份格式无效')
        for item in bundles:
            if not isinstance(item,dict) or not isinstance(item.get('name'),str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}\.json',item['name']):
                raise HTTPException(400,'分析包文件名无效')
            if not isinstance(item.get('body'),dict) or item['body'].get('schema')!='kpl-match-data-v1':
                raise HTTPException(400,'分析包内容无效')
        # Restore immutable research snapshots before the existing merge restore.
        research_result = restore(value['studio']) if value.get('studio') else None
        source_result = provider(value)
        added=0
        for item in bundles:
            path=Path(matches_dir)/item['name']
            path.parent.mkdir(parents=True,exist_ok=True)
            if not path.exists():
                # Exclusive creation preserves existing local source packages.
                try:
                    with path.open('x',encoding='utf-8') as stream:
                        json.dump(item['body'],stream,ensure_ascii=False)
                    added+=1
                except FileExistsError:
                    pass
        return {**source_result, 'studio':research_result, 'bundlesAdded':added}

    @router.post('/reports')
    def save_report(value: dict):
        title, note = value.get('title'), value.get('note', '')
        if not isinstance(title, str) or not title.strip() or len(title) > 120:
            raise HTTPException(400, '标题需为 1–120 个字符')
        if not isinstance(note, str) or len(note) > 4000:
            raise HTTPException(400, '备注需在 4000 字以内')
        try:
            # Save a server-produced snapshot, not an arbitrary client result.
            spec = value.get('spec') or {}
            result = calculate(spec)
            if result['status'] != 'ok':
                raise ValueError('数据不足时不能保存为分析报告')
            expected = value.get('fingerprint')
            if not expected or expected != result['meta']['fingerprint']:
                raise HTTPException(409, '数据或筛选已变化，请重新运行分析后保存')
        except (ValueError, TypeError) as error:
            raise HTTPException(400, str(error)) from error
        report_id, now = uuid.uuid4().hex, datetime.now(timezone.utc).isoformat()
        with result_connection() as connection:
            connection.execute('INSERT INTO reports VALUES (?,?,?,?,?)',
                               (report_id, title.strip(), note, now, json.dumps(result, ensure_ascii=False)))
        return {'id': report_id, 'title': title.strip(), 'createdAt': now}

    def load_report(report_id):
        if not results_db.is_file():
            raise HTTPException(404, '报告不存在')
        with result_connection() as connection:
            row = connection.execute('SELECT title,note,created_at,body FROM reports WHERE id=?', (report_id,)).fetchone()
        if row is None:
            raise HTTPException(404, '报告不存在')
        return {'id': report_id, 'title': row[0], 'note': row[1], 'createdAt': row[2], 'result': json.loads(row[3])}

    @router.get('/reports/{report_id}')
    def report(report_id: str):
        return load_report(report_id)

    @router.get('/reports/{report_id}/export', response_class=HTMLResponse)
    def export(report_id: str):
        report = load_report(report_id)
        result, esc = report['result'], lambda v: html.escape(str(v if v is not None else '—'))
        table = '<table><thead><tr>' + ''.join('<th>'+esc(k)+'</th>' for k in result['columns']) + '</tr></thead><tbody>'
        table += ''.join('<tr>'+''.join('<td>'+esc(row.get(k))+'</td>' for k in result['columns'])+'</tr>' for row in result['rows'])+'</tbody></table>'
        return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>'+esc(report['title'])+'</title><style>body{font:14px/1.7 system-ui;margin:48px;color:#222}table{border-collapse:collapse;width:100%;font-size:12px}td,th{padding:9px;border-bottom:1px solid #ddd;text-align:left}pre{white-space:pre-wrap}small{color:#666}</style><h1>'+esc(report['title'])+'</h1><small>'+esc(report['createdAt'])+' · '+str(result['meta']['matches'])+' 场记录</small><p>'+esc(report['note'])+'</p>'+table+'<p>'+esc(result.get('note',''))+'</p><h2>数据与方法</h2><pre>'+esc(json.dumps(result['spec'], ensure_ascii=False, indent=2))+'</pre><small>数据指纹 '+esc(result['meta']['fingerprint'])+'</small><p>'+esc('；'.join(result['meta']['warnings']))+'</p></html>'

    # ---------------- 对手战队聚类 ----------------
    # 身份来自营地十人面板的阵容签名；命名/合并写覆盖层，不动原始比赛。

    def camp_dir():
        # 允许用环境变量指向别的面板目录（造演示数据、跑回归夹具时用）
        override = os.environ.get('STUDIO_CAMP_DIR')
        if override:
            return Path(override)
        return Path(matches_dir).parent / 'camp_details'

    def own_team_name():
        if not Path(db_path).is_file():
            return ''
        try:
            connection = sqlite3.connect(f'file:{Path(db_path).as_posix()}?mode=ro', uri=True)
            try:
                row = connection.execute('SELECT body FROM settings LIMIT 1').fetchone()
            finally:
                connection.close()
        except sqlite3.Error:
            return ''
        try:
            return str((json.loads(row[0]) if row else {}).get('teamName') or '')
        except (TypeError, ValueError):
            return ''

    @router.get('/teams')
    def teams():
        return team_clusters.list_teams(camp_dir(), db_path, own_team_name())

    # ---------------- 约定计划（教练登记） ----------------
    def plans_connection():
        connection = sqlite3.connect(str(db_path))
        connection.execute('''CREATE TABLE IF NOT EXISTS scrim_plans (
            id TEXT PRIMARY KEY, date TEXT NOT NULL, time TEXT NOT NULL DEFAULT '',
            opponent TEXT NOT NULL DEFAULT '', mode TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending',
            created_at REAL NOT NULL)''')
        return connection

    # ---------------- 工作区主数据（teams / players / schedules / training） ----------------
    def workspace():
        import workspace_store
        return workspace_store.Workspace(db_path).ensure_schema()

    @router.get('/analysis/opponents')
    def opponent_profiles(min: int = 3):
        import analysis_profile
        return analysis_profile.profiles(camp_dir(), db_path, min_games=max(1, min))

    @router.get('/analysis/training-effect')
    def training_effect(session: str = ''):
        import analysis_profile
        rows = workspace().list_training()
        if session:
            rows = [row for row in rows if row['session_id'] == session]
        return {'results': [dict(row, effect=analysis_profile.effect(camp_dir(), row)) for row in rows]}

    @router.get('/analysis/space')
    def space_analyses():
        import analysis_space, map_calibration
        data_dir = Path(matches_dir).parent
        replays = data_dir / 'official_replays'
        calibration = map_calibration.load(data_dir) or map_calibration.compute(replays)
        return analysis_space.all_analyses(replays, camp_dir(), calibration)

    @router.get('/analysis/map-calibration')
    def map_calibration_status(refresh: int = 0):
        import map_calibration
        data_dir = Path(matches_dir).parent
        replays = data_dir / 'official_replays'
        calibration = None if refresh else map_calibration.load(data_dir)
        if calibration is None:
            calibration = map_calibration.compute(replays)
            map_calibration.save(calibration, data_dir)
        return calibration

    @router.get('/analysis/turning-points')
    def turning_points(limit: int = 40):
        import analysis_economy
        replays = Path(matches_dir).parent / 'official_replays'
        return analysis_economy.turning_points(replays, camp_dir(), limit=max(1, min(200, limit)))

    @router.get('/analysis/advantage')
    def advantage():
        import analysis_economy
        replays = Path(matches_dir).parent / 'official_replays'
        return analysis_economy.advantage(replays, camp_dir())

    @router.post('/workspace/prefill/run')
    def wb_prefill_run():
        import prefill
        created = prefill.run(workspace())
        return {'ok': True, 'created': created}

    @router.get('/workspace/pending')
    def wb_pending():
        import prefill
        return prefill.queue(workspace())

    @router.post('/workspace/pending/confirm')
    async def wb_confirm(request: Request):
        payload = await request.json()
        match_key = str(payload.get('matchKey') or '').strip()
        field = str(payload.get('field') or '').strip()
        if not match_key or not field:
            raise HTTPException(400, '缺少对局或字段')
        value = payload.get('value')
        if value is None or str(value).strip() == '':
            raise HTTPException(400, '请填写值')
        # 版本 / 规则 / 赛制 / 训练组确认时统一归一化，避免同一场里两种写法。
        kind = vocab.FIELD_KINDS.get(field)
        if kind:
            value = vocab.prepare(kind, value, vocab_dir)
        workspace().confirm_prefill(match_key, field, value, actor=payload.get('actor') or 'coach')
        return {'ok': True, 'value': value}

    @router.post('/workspace/pending/confirm-batch')
    async def wb_confirm_batch(request: Request):
        payload = await request.json()
        items = payload.get('items') if isinstance(payload, dict) else None
        if not isinstance(items, list) or not 1 <= len(items) <= 200:
            raise HTTPException(400, '请选择 1–200 个待确认字段')
        normalized = []
        for index, item in enumerate(items, 1):
            if not isinstance(item, dict):
                raise HTTPException(400, f'第 {index} 项格式无效')
            match_key = str(item.get('matchKey') or '').strip()
            field = str(item.get('field') or '').strip()
            value = item.get('value')
            if not match_key or not field:
                raise HTTPException(400, f'第 {index} 项缺少对局或字段')
            if value is None or (not isinstance(value, list) and str(value).strip() == ''):
                raise HTTPException(400, f'第 {index} 项缺少值')
            if field == 'pick_order' and isinstance(value, str):
                try:
                    value = json.loads(value)
                except (TypeError, ValueError):
                    raise HTTPException(400, f'第 {index} 项选用顺序须为 JSON 数组')
                if not isinstance(value, list):
                    raise HTTPException(400, f'第 {index} 项选用顺序须为 JSON 数组')
            kind = vocab.FIELD_KINDS.get(field)
            if kind:
                value = vocab.prepare(kind, value, vocab_dir)
            normalized.append({'matchKey': match_key, 'field': field, 'value': value})
        try:
            confirmed = workspace().confirm_prefills(normalized, actor=payload.get('actor') or 'coach')
        except ValueError as error:
            raise HTTPException(400, str(error))
        return {'ok': True, 'confirmed': len(confirmed), 'items': confirmed}

    @router.get('/workspace/teams')
    def wb_teams(q: str = '', include_archived: bool = False):
        ws = workspace()
        return {'teams': ws.search_teams(q) if q else ws.list_teams(include_archived=include_archived)}

    @router.post('/workspace/teams')
    async def wb_save_team(request: Request):
        payload = await request.json()
        import identity_service
        try:
            saved = identity_service.save_team(
                db_path, team_id=payload.get('id'), name=payload.get('name') or '',
                short_name=payload.get('shortName'), aliases=payload.get('aliases'),
                league=payload.get('league'), coach=payload.get('coach'),
                first_seen=payload.get('firstSeen'), status=payload.get('status') or 'active')
        except ValueError as error:
            raise HTTPException(400, str(error))
        return {'ok': True, 'id': saved['id']}

    @router.post('/workspace/teams/merge')
    async def wb_merge_team(request: Request):
        payload = await request.json()
        source = str(payload.get('from') or '').strip()
        target = str(payload.get('into') or '').strip()
        if not source or not target or source == target:
            raise HTTPException(400, '合并参数无效')
        # merge_team 内部同时归档工作区源队、改挂选手并写覆盖层。
        team_clusters.merge_team(db_path, source, target)
        return {'ok': True, 'from': source, 'into': target}

    @router.post('/workspace/teams/reconcile')
    def wb_reconcile_teams(dry_run: bool = False):
        """一次性对账历史覆盖层与工作区主数据；默认只报告，dry_run=false 时写入。"""
        return team_clusters.reconcile_workspace(db_path, dry_run=dry_run)

    @router.get('/workspace/players')
    def wb_players(team: str = ''):
        return {'players': workspace().list_players(team or None)}

    @router.post('/workspace/players')
    async def wb_save_player(request: Request):
        payload = await request.json()
        import identity_service
        try:
            saved = identity_service.save_player(
                db_path, player_id=payload.get('id'), name=payload.get('name') or '',
                position=payload.get('position'), team_id=payload.get('teamId') or '',
                team_name=payload.get('team') or payload.get('teamName') or '',
                camp_user_id=payload.get('campUserId'), role=payload.get('role') or 'main',
                aliases=payload.get('aliases'), actor='coach')
        except ValueError as error:
            raise HTTPException(400, str(error))
        return {'ok': True, 'id': saved['playerId'], **saved}

    @router.post('/workspace/players/delete')
    async def wb_delete_player(request: Request):
        payload = await request.json()
        import identity_service
        player_id = str(payload.get('id') or payload.get('playerId') or '').strip()
        if not player_id:
            raise HTTPException(400, '缺少选手 id')
        try:
            removed = identity_service.delete_player(db_path, player_id, actor='coach')
        except ValueError as error:
            raise HTTPException(404, str(error))
        return {'ok': True, **removed}

    @router.post('/workspace/players/migrate-profile')
    def wb_migrate_profile_players():
        """把旧 settings.roster 一次性迁入工作区选手表；同一旧 id 保留。"""
        with sqlite3.connect(db_path) as connection:
            row = connection.execute('SELECT body FROM settings WHERE id=1').fetchone()
            if not row:
                raise HTTPException(400, '设置尚未初始化')
            try:
                settings = json.loads(row[0])
            except (TypeError, ValueError):
                raise HTTPException(400, '设置格式异常，无法迁移旧名单')
        roster = settings.get('roster')
        if not isinstance(roster, list):
            raise HTTPException(400, '旧名单格式异常，无法迁移')
        try:
            report = workspace().migrate_roster(
                roster, own_team_name=str(settings.get('teamName') or '').strip(), actor='coach')
        except ValueError as error:
            raise HTTPException(400, str(error))
        renamed = report.get('renamed') or {}
        if renamed:
            # 旧名单里的「新选手」也改成「待命名选手 #N」，避免和「待命名战队 #N」混在一起。
            for member in roster:
                new_name = renamed.get(str(member.get('id') or ''))
                if new_name:
                    member['name'] = new_name
            settings['roster'] = roster
        settings['rosterMigratedAt'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
        with sqlite3.connect(db_path) as connection:
            connection.execute('UPDATE settings SET body=? WHERE id=1',
                               (json.dumps(settings, ensure_ascii=False),))
        repository_cache['value'] = None
        result_cache.clear()
        return {'ok': True, **report, 'migratedAt': settings['rosterMigratedAt']}

    @router.get('/workspace/schedules')
    def wb_schedules(status: str = ''):
        return {'schedules': workspace().list_schedules(status=status or None)}

    @router.get('/workspace/competitions')
    def wb_competitions():
        return {'competitions': workspace().list_competitions()}

    @router.get('/workspace/competitions/{competition_id}')
    def wb_competition_detail(competition_id: str):
        value = workspace().competition_detail(competition_id)
        if value is None:
            raise HTTPException(404, '找不到这场比赛')
        return value

    @router.post('/workspace/competitions')
    async def wb_save_competition(request: Request):
        payload = await request.json()
        ws = workspace()
        try:
            competition_id = ws.save_competition(
                payload.get('id'), name=payload.get('name') or '',
                date=payload.get('date') or '',
                opponent_team_id=payload.get('opponentTeamId') or None,
                stage=payload.get('stage') or None,
                format=payload.get('format') or None,
                status=payload.get('status') or 'planned',
                owner=payload.get('owner') or None,
                notes=payload.get('notes') or None)
        except ValueError as error:
            raise HTTPException(400, str(error))
        return {'ok': True, 'id': competition_id}

    @router.post('/workspace/reports/screenshot')
    async def wb_report_screenshot(request: Request):
        payload = await request.json()
        path = str(payload.get('path') or '').strip().lstrip('#')
        if not (path.startswith('session/') or path.startswith('weekly/')):
            raise HTTPException(400, '只支持训练课或训练周报')
        base = str(request.base_url).rstrip('/')
        url = f'{base}/#{path}'
        out_dir = Path(db_path).parent / 'reports' / 'images'
        out_dir.mkdir(parents=True, exist_ok=True)
        name = f'report-{uuid.uuid4().hex[:12]}.png'
        target = out_dir / name

        def render():
            from playwright.sync_api import sync_playwright
            with sync_playwright() as player:
                browser = player.chromium.launch(channel='msedge', headless=True)
                try:
                    page = browser.new_page(viewport={'width': 1200, 'height': 1000},
                                            device_scale_factor=2)
                    page.goto(url, wait_until='networkidle', timeout=30000)
                    page.locator('.report-sheet').wait_for(state='visible', timeout=15000)
                    page.wait_for_timeout(500)
                    page.locator('.report-sheet').screenshot(path=str(target))
                finally:
                    browser.close()
            return name

        try:
            await asyncio.to_thread(render)
        except Exception as error:  # noqa: BLE001
            raise HTTPException(500, f'图片导出失败：{error}')
        return {'ok': True, 'url': f'/api/studio/workspace/reports/image/{name}'}

    @router.get('/workspace/reports/image/{name}')
    def wb_report_image(name: str):
        if not re.fullmatch(r'report-[a-f0-9]{12}\.png', name):
            raise HTTPException(404, '图片不存在')
        path = Path(db_path).parent / 'reports' / 'images' / name
        if not path.is_file():
            raise HTTPException(404, '图片不存在')
        return FileResponse(path, media_type='image/png', filename=name)

    @router.get('/workspace/matches')
    def wb_matches(limit: int = 500):
        return {'matches': workspace().available_matches(limit)}

    @router.get('/workspace/dashboard')
    def wb_dashboard(weeks: int = 8):
        return metric_service.dashboard(workspace(), weeks)

    @router.get('/workspace/metrics/week')
    def wb_week_metrics(start: str = ''):
        return metric_service.compute_week(workspace(), start)

    @router.get('/workspace/metrics/registry')
    def wb_metric_registry(entity: str = ''):
        return {'metrics': metric_service.metrics_registry.list_metrics(entity or None)}

    @router.get('/workspace/inbox')
    def wb_inbox():
        return workspace().inbox()

    @router.get('/workspace/opponents/unmapped')
    def wb_unmapped_opponents():
        ws = workspace()
        return {'opponents': ws.unmapped_opponents(), 'teams': ws.list_teams()}

    @router.post('/workspace/opponents/map')
    async def wb_map_opponent(request: Request):
        payload = await request.json()
        old_id = str(payload.get('oldId') or '').strip() if isinstance(payload, dict) else ''
        team_id = str(payload.get('teamId') or '').strip() if isinstance(payload, dict) else ''
        try:
            return workspace().map_opponent(old_id, team_id, actor='coach')
        except ValueError as error:
            raise HTTPException(400, str(error))

    @router.get('/workspace/sessions/{schedule_id}')
    def wb_session(schedule_id: str):
        ws = workspace()
        schedule = ws.get_schedule(schedule_id)
        if not schedule:
            raise HTTPException(404, '训练课不存在')
        teams = {team['id']: team for team in ws.list_teams(include_archived=True)}
        linked = ws.session_matches(schedule)
        for match in linked['matches']:
            team = teams.get(str(match.get('enemy_team_id') or ''))
            match['enemyName'] = team.get('name') if team else ''
        team = teams.get(str(schedule.get('opponent_team_id') or ''))
        available = ws.available_matches(200)
        for match in available:
            opponent = teams.get(str(match.get('enemy_team_id') or ''))
            match['enemyName'] = opponent.get('name') if opponent else ''
        brief = None
        try:
            brief = team_clusters.team_brief(
                camp_dir(), db_path, str(schedule.get('opponent_team_id') or ''),
                (team or {}).get('name') or '', limit=3)
        except Exception:  # noqa: BLE001 - 简报失败不能挡住训练课
            brief = None
        manual = ws.manual_session_keys(schedule_id)
        schedule_view = metric_service.enrich_schedule(ws, schedule)
        return {
            'schedule': schedule_view,
            'metrics': schedule_view.get('metrics') or {},
            'goalMetrics': metric_service.goal_metrics(),
            'team': {'id': team['id'], 'name': team['name']} if team else None,
            'matches': linked['matches'],
            'matchReason': linked['reason'],
            'manualLinks': bool(manual),
            'manualMatchKeys': manual,
            'availableMatches': available,
            'opponentBrief': brief,
            'players': ws.list_players(),
        }

    @router.post('/workspace/sessions/{schedule_id}/links')
    async def wb_session_links(schedule_id: str, request: Request):
        payload = await request.json()
        keys = payload.get('matchKeys') if isinstance(payload, dict) else None
        if not isinstance(keys, list):
            raise HTTPException(400, '请选择要关联的对局')
        try:
            saved = workspace().save_session_links(schedule_id, keys, actor='coach')
        except ValueError as error:
            raise HTTPException(400, str(error))
        return {'ok': True, 'matchKeys': saved, 'reason': 'manual' if saved else 'auto'}

    @router.post('/workspace/sessions/{schedule_id}/review')
    async def wb_session_review(schedule_id: str, request: Request):
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(400, '复盘内容无效')
        goals = payload.get('goals')
        if isinstance(goals, str):
            goals = [line.strip() for line in goals.splitlines() if line.strip()]
        if not isinstance(goals, list) or len(goals) > 12:
            raise HTTPException(400, '训练目标最多 12 条')
        clean_goals = []
        for item in goals:
            if isinstance(item, str):
                label, target, status = item.strip(), '', 'pending'
            elif isinstance(item, dict):
                label = str(item.get('label') or '').strip()
                target = str(item.get('target') or '').strip()[:80]
                status = str(item.get('status') or 'pending').strip()
            else:
                continue
            if not label:
                continue
            if status not in ('pending', 'achieved', 'partial', 'missed'):
                status = 'pending'
            metric_id = str(item.get('metricId') or '').strip() if isinstance(item, dict) else ''
            comparator = str(item.get('comparator') or '').strip() if isinstance(item, dict) else ''
            clean_goals.append({'label': label[:120], 'target': target, 'status': status,
                                'metricId': metric_id, 'comparator': comparator})
        goals = clean_goals
        attendance = payload.get('attendance')
        if isinstance(attendance, str):
            attendance = [line.strip() for line in attendance.splitlines() if line.strip()]
        if not isinstance(attendance, list) or len(attendance) > 30:
            raise HTTPException(400, '出勤名单无效')
        attendance = [str(item).strip()[:40] for item in attendance if str(item).strip()]
        review_status = str(payload.get('reviewStatus') or 'pending')
        ws = workspace()
        values = metric_service.compute_session(ws, schedule_id, override={
            'review_status': review_status,
            'goals': json.dumps(goals, ensure_ascii=False),
            'attendance': json.dumps(attendance, ensure_ascii=False),
        })
        goals = metric_service.enrich_goals(goals, values)
        try:
            schedule = ws.save_session_review(
                schedule_id, goals=goals, review=str(payload.get('review') or '')[:4000],
                review_status=review_status, attendance=attendance,
                actor=payload.get('actor') or 'coach')
        except ValueError as error:
            raise HTTPException(400, str(error))
        schedule_view = metric_service.enrich_schedule(ws, schedule)
        return {'ok': True, 'schedule': schedule_view, 'metrics': schedule_view.get('metrics') or {}}

    @router.post('/workspace/schedules')
    async def wb_save_schedule(request: Request):
        payload = await request.json()
        ws = workspace()
        schedule_id = ws.save_schedule(
            payload.get('id'), date=payload.get('date') or '', start_time=payload.get('startTime'),
            opponent_team_id=payload.get('opponentTeamId'),
            session=vocab.prepare('sessions', payload.get('session'), vocab_dir),
            format=vocab.prepare('formats', payload.get('format'), vocab_dir),
            rules=vocab.prepare('rules', payload.get('rules'), vocab_dir),
            version=vocab.prepare('versions', payload.get('version'), vocab_dir),
            status=payload.get('status') or 'planned', notes=payload.get('notes'),
            created_by=payload.get('createdBy'),
            competition_id=payload.get('competitionId') or None)
        return {'ok': True, 'id': schedule_id}

    @router.get('/workspace/training')
    def wb_training():
        return {'training': workspace().list_training()}

    @router.post('/workspace/training')
    async def wb_save_training(request: Request):
        payload = await request.json()
        ws = workspace()
        session_id = ws.save_training(
            payload.get('sessionId'), goal=payload.get('goal') or '',
            intervention=payload.get('intervention') or '', start_date=payload.get('startDate') or '',
            end_date=payload.get('endDate'), player_ids=payload.get('playerIds'),
            metric=payload.get('metric') or '', target=payload.get('target'), review=payload.get('review'))
        return {'ok': True, 'id': session_id}

    @router.get('/plans')
    def list_plans():
        with plans_connection() as connection:
            rows = connection.execute(
                'SELECT id, date, time, opponent, mode, note, status FROM scrim_plans ORDER BY date DESC, time DESC').fetchall()
        return {'plans': [{'id': r[0], 'date': r[1], 'time': r[2], 'opponent': r[3],
                           'mode': r[4], 'note': r[5], 'status': r[6]} for r in rows]}

    @router.post('/plans')
    async def save_plan(request: Request):
        payload = await request.json()
        date = str(payload.get('date') or '').strip()
        if not date:
            raise HTTPException(400, '缺少日期')
        plan_id = str(payload.get('id') or '').strip() or uuid.uuid4().hex[:12]
        values = (plan_id, date, str(payload.get('time') or '').strip(),
                  str(payload.get('opponent') or '').strip(), str(payload.get('mode') or '').strip(),
                  str(payload.get('note') or '').strip(), str(payload.get('status') or 'pending'),
                  time.time())
        with plans_connection() as connection:
            connection.execute(
                'INSERT INTO scrim_plans(id,date,time,opponent,mode,note,status,created_at) '
                'VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET date=excluded.date, time=excluded.time, '
                'opponent=excluded.opponent, mode=excluded.mode, note=excluded.note, status=excluded.status',
                values)
            connection.commit()
        return {'ok': True, 'id': plan_id}

    @router.post('/plans/delete')
    async def delete_plan(request: Request):
        payload = await request.json()
        plan_id = str(payload.get('id') or '').strip()
        if not plan_id:
            raise HTTPException(400, '缺少 id')
        with plans_connection() as connection:
            connection.execute('DELETE FROM scrim_plans WHERE id=?', (plan_id,))
            connection.commit()
        return {'ok': True, 'id': plan_id}

    @router.get('/coach')
    def coach_board():
        """教练档案：本队教练 + 各对手战队教练（可填）与阵容。"""
        opponents = team_clusters.opponent_players(camp_dir(), db_path)
        overrides = team_clusters.load_overrides(db_path)
        teams = []
        for team in opponents['teams']:
            override = overrides.get(team['id'], {})
            teams.append({
                'id': team['id'], 'name': team['displayName'], 'named': team['named'],
                'coach': override.get('coach') or '',
                'players': [{'id': p['id'], 'name': p['name'], 'lanes': p['lanes'], 'games': p['games']}
                            for p in team['players']],
            })
        return {'own': {'coach': own_coach_name()}, 'teams': teams}

    def own_coach_name():
        if not Path(db_path).is_file():
            return ''
        try:
            connection = sqlite3.connect(f'file:{Path(db_path).as_posix()}?mode=ro', uri=True)
            try:
                row = connection.execute('SELECT body FROM settings LIMIT 1').fetchone()
            finally:
                connection.close()
        except sqlite3.Error:
            return ''
        try:
            return str((json.loads(row[0]) if row else {}).get('coach') or '')
        except (TypeError, ValueError):
            return ''

    @router.post('/coach')
    async def save_coach(request: Request):
        payload = await request.json()
        team_id = str(payload.get('teamId') or '').strip()
        name = str(payload.get('name') or '').strip()
        if team_id:
            team_clusters.save_override(db_path, team_id, {'coach': name})
            return {'ok': True, 'teamId': team_id, 'name': name}
        if not Path(db_path).is_file():
            raise HTTPException(400, '数据库不存在')
        connection = sqlite3.connect(str(db_path))
        try:
            row = connection.execute('SELECT body FROM settings WHERE id=1').fetchone()
            body = json.loads(row[0]) if row else {}
            body['coach'] = name
            connection.execute('INSERT INTO settings(id, body) VALUES(1, ?) '
                               'ON CONFLICT(id) DO UPDATE SET body=excluded.body',
                               (json.dumps(body, ensure_ascii=False),))
            connection.commit()
        finally:
            connection.close()
        return {'ok': True, 'name': name}

    @router.get('/opponents')
    def opponents():
        """对手战队与其选手归属（教练可手动指派）。"""
        return team_clusters.opponent_players(camp_dir(), db_path)

    @router.post('/opponents/assign')
    async def assign_opponent_player(request: Request):
        """把已命名的对手选手挪到另一支战队。

        未命名的账号没有选手记录可挪 —— 先命名再归队，避免覆盖层和主数据两套归属。
        """
        import identity_service
        payload = await request.json()
        account_id = str(payload.get('playerId') or '').strip()
        team_id = str(payload.get('teamId') or '').strip()
        if not account_id:
            raise HTTPException(400, '缺少选手 id')
        if not team_id:
            raise HTTPException(400, '请选择目标战队')
        ws = workspace()
        rows = ws.list_accounts(account_id=account_id)
        if not rows:
            raise HTTPException(400, '这个游戏账号还没命名，请先命名并归队')
        try:
            saved = identity_service.name_account(
                db_path, account_id=account_id, player_id=rows[0]['player_id'], team_id=team_id)
        except ValueError as error:
            raise HTTPException(400, str(error))
        return {'ok': True, 'playerId': account_id, 'teamId': saved['teamId']}

    @router.get('/camp-compare')
    def camp_compare(team: str = ''):
        """逐人 / 逐英雄对照。不传 team 就是全部对手合并后的口径。"""
        return team_clusters.compare(camp_dir(), team or None)

    @router.get('/camp-combos')
    def camp_combos(min: int = 3):
        """营地面板的双人 / 三人组合，带协同加成。"""
        return team_clusters.combo_sets(camp_dir(), min_games=max(2, min))

    @router.get('/camp-partners')
    def camp_partners(hero: str = '', side: str = 'own'):
        """某英雄的搭档协同；只返回包含该英雄的双人组合。"""
        if not hero.strip():
            raise HTTPException(400, '缺少英雄名')
        return team_clusters.partners(camp_dir(), hero.strip(),
                                      side if side in ('own', 'enemy') else 'own')

    @router.post('/teams/rename-batch')
    async def rename_team_batch(request: Request):
        payload = await request.json()
        items = payload.get('items') if isinstance(payload, dict) else None
        try:
            return team_clusters.rename_many(db_path, items)
        except ValueError as error:
            raise HTTPException(400, str(error))

    @router.post('/teams/rename')
    async def rename_team(request: Request):
        import identity_service
        payload = await request.json()
        key = str(payload.get('id') or '').strip()
        if not key:
            raise HTTPException(400, '缺少战队 id')
        try:
            identity_service.rename_team(db_path, key, name=payload.get('name'),
                                         coach=payload.get('coach'))
        except ValueError as error:
            raise HTTPException(400, str(error))
        return {'ok': True, 'id': key}

    @router.post('/teams/merge')
    async def merge_teams(request: Request):
        payload = await request.json()
        source = str(payload.get('from') or '').strip()
        target = str(payload.get('into') or '').strip()
        if not source or not target or source == target:
            raise HTTPException(400, '合并来源和目标无效')
        team_clusters.merge_team(db_path, source, target)
        return {'ok': True, 'from': source, 'into': target}

    return router
