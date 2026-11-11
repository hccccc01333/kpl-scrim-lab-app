"""Audited preparation of immutable local analysis datasets."""
import copy
import json
import math
import sqlite3
import uuid
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from studio_analysis import METRICS, deduplicate, finite, fingerprint

TEXT_FIELDS = ('label', 'hero', 'position', 'opponent', 'version')
PERCENT_FIELDS = ('participation', 'goldShare', 'damageShare', 'takenShare')


def identify(rows):
    result = copy.deepcopy(rows)
    for i, row in enumerate(result):
        row['_rowId'] = fingerprint([row.get('matchKey'), row.get('camp'), row.get('playerKey'), i])[:24]
    return result


def invalid(value, metric):
    number = finite(value)
    return value is not None and (number is None or number < 0 or (metric in PERCENT_FIELDS and number > 100))


def profile(rows):
    issues = []
    fields = []
    for key, (label, unit) in METRICS.items():
        missing = sum(r.get(key) is None for r in rows)
        invalid_count = sum(invalid(r.get(key), key) for r in rows)
        fields.append({'key': key, 'label': label, 'unit': unit, 'valid': len(rows)-missing-invalid_count,
                       'missing': missing, 'invalid': invalid_count})
    for row in rows:
        for key in METRICS:
            if invalid(row.get(key), key):
                issues.append({'rowId': row['_rowId'], 'label': row.get('label'), 'hero': row.get('hero'),
                               'metric': key, 'value': row.get(key), 'reason': '数值非有限、为负或占比超出 0–100'})
    _, duplicates = deduplicate(rows)
    return {'rows': len(rows), 'matches': len({r['matchKey'] for r in rows}), 'fields': fields,
            'invalidCells': sum(f['invalid'] for f in fields), 'duplicates': duplicates,
            'partialRows': sum(bool(r.get('partial')) for r in rows),
            'unboundRows': sum(not r.get('bound') for r in rows), 'issues': issues[:200]}


def recalculate(rows):
    teams = defaultdict(list)
    for row in rows:
        teams[(row['matchKey'], row.get('camp'))].append(row)
        k, d, a = [finite(row.get(key)) for key in ('kills', 'deaths', 'assists')]
        row['kda'] = (k+a)/max(1, d) if None not in (k, d, a) else None
        if any(finite(row.get(key)) is None for key in ('kills', 'deaths', 'assists', 'gold', 'damage', 'taken')):
            row.update(partial=True, full=False, complete=False)
        minutes = finite(row.get('minutes'))
        for rate, total in [('gpm', 'gold'), ('dpm', 'damage'), ('tpm', 'taken')]:
            value = finite(row.get(total))
            row[rate] = value/minutes if (row.get('full') or row.get('source') == 'capture') and value is not None and minutes and minutes > 0 else None
        gold, damage = finite(row.get('gold')), finite(row.get('damage'))
        if row.get('damageConversion') is None or 'damageConversion' in row.get('derivedFields', []):
            row['damageConversion'] = damage/gold if gold and damage is not None else None
        taken = finite(row.get('taken'))
        if row.get('takenPerDeath') is None or 'takenPerDeath' in row.get('derivedFields', []):
            row['takenPerDeath'] = taken/d if taken is not None and d and d > 0 else None
    for members in teams.values():
        for share, metric in [('goldShare', 'gold'), ('damageShare', 'damage'), ('takenShare', 'taken')]:
            values = [finite(r.get(metric)) for r in members]
            total = sum(values) if len(values) == 5 and all(v is not None for v in values) else None
            for row in members:
                if row.get('source') == 'capture' and row.get(share) is not None:
                    continue
                row[share] = finite(row[metric])/total*100 if (row.get('full') or row.get('source') == 'capture') and total and total > 0 else None


def json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


def prepare(rows, rules=None, edits=None):
    rules, edits = rules or {}, edits or []
    if not isinstance(rules, dict) or not isinstance(edits, list) or len(edits) > 3000:
        raise ValueError('清洗规则或修订列表无效')
    if len(rows) > 30000:
        raise ValueError('单次清洗最多 30,000 行，请先筛选')
    required = rules.get('required', [])
    if not isinstance(required, list) or any(k not in METRICS for k in required):
        raise ValueError('必需字段无效')
    if rules.get('dropMissing') and not required:
        raise ValueError('请先选择必需指标')
    if rules.get('invalid', 'null') not in ('keep', 'null', 'drop'):
        raise ValueError('异常值处理方式无效')
    identified = identify(rows)
    before = profile(identified)
    source_fingerprint = fingerprint(rows)
    original = {r['_rowId']: r for r in identified}
    logs = []
    for edit in edits:
        if not isinstance(edit, dict) or edit.get('rowId') not in original:
            raise ValueError('修订引用的原始行不存在，请重新读取数据')
        key, value = edit.get('field'), edit.get('value')
        if key not in (*METRICS, *TEXT_FIELDS, 'date'):
            raise ValueError('该字段不支持在清洗表中修订')
        if key in METRICS:
            if value not in (None, '') and (finite(value) is None or invalid(value, key)):
                raise ValueError('修订数值无效，计数非负、占比为 0–100')
            value = finite(value)
        elif not isinstance(value, str) or len(value) > 200:
            raise ValueError('文本修订需在 200 字以内')
        if key == 'date':
            if value:
                date.fromisoformat(value)
            original[edit['rowId']]['dateFull'] = bool(value)
            original[edit['rowId']]['dateKey'] = value or None
        row = original[edit['rowId']]
        if row.get(key) != value:
            logs.append({'rowId': edit['rowId'], 'field': key, 'before': row.get(key), 'after': value,
                         'reason': str(edit.get('reason') or '人工修订')[:500], 'action': 'edit'})
            row[key] = value
    retained = []
    for row in identified:
        for key in TEXT_FIELDS if rules.get('trim', True) else ():
            if isinstance(row.get(key), str) and row[key] != row[key].strip():
                logs.append({'rowId': row['_rowId'], 'field': key, 'before': row[key], 'after': row[key].strip(), 'action': 'trim'})
                row[key] = row[key].strip()
        bad = [key for key in METRICS if invalid(row.get(key), key)]
        policy = rules.get('invalid', 'null')
        if bad and policy == 'drop':
            logs.append({'rowId': row['_rowId'], 'action': 'exclude', 'reason': '异常值：'+','.join(bad)})
            continue
        if policy == 'null':
            for key in bad:
                logs.append({'rowId': row['_rowId'], 'field': key, 'before': row[key], 'after': None, 'action': 'invalid-to-null'})
                row[key] = None
        if rules.get('dropMissing', False) and any(finite(row.get(k)) is None for k in required):
            logs.append({'rowId': row['_rowId'], 'action': 'exclude', 'reason': '必需字段缺失'})
            continue
        retained.append(row)
    folded = []
    if rules.get('deduplicate', True):
        retained, folded = deduplicate(retained)
        logs += [{'action': 'fold-content', **pair} for pair in folded]
    derived = ('kda', 'gpm', 'dpm', 'tpm', 'damageConversion', 'takenPerDeath', 'goldShare', 'damageShare', 'takenShare')
    old_derived = {r['_rowId']: {key: r.get(key) for key in derived} for r in retained}
    recalculate(retained)
    for row in retained:
        for key in derived:
            old = old_derived[row['_rowId']][key]
            if row.get(key) != old:
                logs.append({'rowId': row['_rowId'], 'field': key, 'before': old, 'after': row.get(key), 'action': 'recompute'})
    retained = json_safe(retained)
    after = profile(retained)
    return json_safe({'schema': 'kpl-prepared-dataset-v1', 'sourceFingerprint': source_fingerprint,
            'fingerprint': fingerprint(retained), 'before': before, 'after': after,
            'rows': retained, 'logs': logs, 'rules': rules, 'edits': edits,
            'exploratory': any(r.get('source') == 'capture' for r in retained)})


class DatasetStore:
    def __init__(self, path):
        self.path = Path(path)

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=15)
        connection.execute('CREATE TABLE IF NOT EXISTS prepared_datasets (id TEXT PRIMARY KEY,title TEXT NOT NULL,created_at TEXT NOT NULL,body TEXT NOT NULL)')
        return connection

    def exists(self):
        if not self.path.is_file():
            return False
        with sqlite3.connect(self.path) as c:
            return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='prepared_datasets'").fetchone())

    def list(self):
        if not self.exists():
            return []
        with self.connect() as c:
            values = c.execute('SELECT id,title,created_at,body FROM prepared_datasets ORDER BY created_at DESC').fetchall()
        # 备份恢复只校验 schema/rows/after/fingerprint，不强制 exploratory；旧版或手工编辑的
        # 备份可能缺这个字段。这里容错取值，避免一条历史记录让 /api/studio/workspace 500，
        # 进而让整个工作台的数据页都读不出来。
        return [{'id': key, 'title': title, 'createdAt': created,
                 'after': body.get('after') or {},
                 'fingerprint': body.get('fingerprint') or '',
                 'exploratory': bool(body.get('exploratory', False))}
                for key, title, created, raw in values for body in [json.loads(raw)]]

    def get(self, key):
        if not self.exists():
            return None
        with self.connect() as c:
            value = c.execute('SELECT title,created_at,body FROM prepared_datasets WHERE id=?', (key,)).fetchone()
        return {'id': key, 'title': value[0], 'createdAt': value[1], **json.loads(value[2])} if value else None

    def save(self, title, prepared, spec):
        key, now = uuid.uuid4().hex, datetime.now(timezone.utc).isoformat()
        body = {**prepared, 'sourceSpec': spec}
        with self.connect() as c:
            c.execute('INSERT INTO prepared_datasets VALUES (?,?,?,?)',
                      (key, title, now, json.dumps(body, ensure_ascii=False, allow_nan=False)))
        return {'id': key, 'title': title, 'createdAt': now, 'rows': prepared['after']['rows']}

    def backup(self):
        if not self.exists():
            return []
        with self.connect() as c:
            values = c.execute('SELECT id,title,created_at,body FROM prepared_datasets').fetchall()
        return [{'id':key,'title':title,'createdAt':created,'body':json.loads(body)} for key,title,created,body in values]

    def restore(self, records):
        if not isinstance(records, list) or len(records)>5000:
            raise ValueError('数据集备份格式无效')
        validated=[]
        for record in records:
            if not isinstance(record,dict) or not all(isinstance(record.get(k),str) and 0<len(record[k])<=200 for k in ('id','title','createdAt')):
                raise ValueError('数据集备份条目无效')
            body=record.get('body')
            if not isinstance(body,dict) or body.get('schema')!='kpl-prepared-dataset-v1' or not isinstance(body.get('rows'),list) or not isinstance(body.get('after'),dict):
                raise ValueError('清洗结果备份无效')
            if fingerprint(body['rows'])!=body.get('fingerprint'):
                raise ValueError('数据集备份指纹不匹配')
            validated.append((record['id'],record['title'],record['createdAt'],json.dumps(body,ensure_ascii=False,allow_nan=False)))
        added=0
        if validated:
            with self.connect() as c:
                for record in validated:
                    added+=c.execute('INSERT OR IGNORE INTO prepared_datasets VALUES (?,?,?,?)',record).rowcount
        return {'added':added,'skipped':len(records)-added}
