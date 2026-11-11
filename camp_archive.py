"""王者营地原始载荷的字段档案：先把每个字段都留下来，再谈要不要用。

归一化（`camp_replay.normalize`）只挑它认识的键，营地一改版就会把新字段、
新文案、新的描述性文字静默丢掉。这个模块不做归一化，只做两件事：

* ``inventory``：把一份载荷摊平成「路径 → 类型 / 出现次数 / 非空数 / 示例」，
  数组下标折叠成 ``[]``，所以路径数量有限、可检索。
* ``texts``：抽出所有含中文的字符串值及其路径。营地的叙述、队名、标签、
  dtID 名称都在这里——教练说的「前端那些字也有信息量」指的就是这一层。

口径：只读、不改数据、不判断哪个字段有用。档案随 `raw.json` 一起落盘，
营地改版后可以直接对比两次档案找出新增字段。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

SCHEMA = 'camp-fields-v1'
CJK = re.compile(r'[\u4e00-\u9fff]')


def _type(value):
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'bool'
    if isinstance(value, (int, float)):
        return 'number'
    if isinstance(value, str):
        return 'string'
    if isinstance(value, list):
        return 'array'
    if isinstance(value, dict):
        return 'object'
    return type(value).__name__


def walk(value, path=''):
    """深度遍历，产出 (路径, 标量值)。数组下标统一折叠成 ``[]``。"""
    if isinstance(value, dict):
        for key, item in value.items():
            yield from walk(item, f'{path}.{key}' if path else str(key))
    elif isinstance(value, list):
        for item in value:
            yield from walk(item, f'{path}[]')
    else:
        yield path or '$', value


def inventory(payload, samples=3):
    """一份载荷 → 字段表。`count` 是出现次数（数组折叠后），`nonNull` 是非空次数。"""
    fields = {}
    for path, value in walk(payload):
        entry = fields.get(path)
        if entry is None:
            entry = fields[path] = {'path': path, 'types': set(), 'count': 0,
                                    'nonNull': 0, 'samples': []}
        entry['types'].add(_type(value))
        entry['count'] += 1
        if value is None or value == '':
            continue
        entry['nonNull'] += 1
        if len(entry['samples']) < samples:
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            text = str(text)[:80]
            if text not in entry['samples']:
                entry['samples'].append(text)
    rows = []
    for entry in sorted(fields.values(), key=lambda item: item['path']):
        rows.append({'path': entry['path'], 'types': sorted(entry['types']),
                     'count': entry['count'], 'nonNull': entry['nonNull'],
                     'samples': entry['samples']})
    return rows


def texts(payload, min_len=2):
    """所有含中文的字符串值 → [{'path','text'}]，按文本去重并保序。"""
    seen, rows = set(), []
    for path, value in walk(payload):
        if not isinstance(value, str):
            continue
        text = value.strip()
        if len(text) < min_len or not CJK.search(text):
            continue
        if text in seen:
            continue
        seen.add(text)
        rows.append({'path': path, 'text': text[:300]})
    return rows


def summarize(payload):
    rows = inventory(payload)
    return {'fields': len(rows),
            'scalars': sum(row['count'] for row in rows),
            'texts': len(texts(payload)),
            'top': [{'path': row['path'], 'count': row['count'], 'types': row['types']}
                    for row in rows if row['count'] > 1][:40]}


def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def build_for_replay(replay_id, store=None):
    """给一条官方回放生成字段档案，写到 `data/official_replays/<id>/fields.json`。"""
    store = Path(store) if store else None
    folder = (store / replay_id) if store else Path('data') / 'official_replays' / replay_id
    raw = _read(folder / 'raw.json')
    if raw is None:
        return None
    archive = {'schema': SCHEMA, 'replayId': replay_id,
               'fields': inventory(raw), 'texts': texts(raw)}
    (folder / 'fields.json').write_text(
        json.dumps(archive, ensure_ascii=False, indent=1), encoding='utf-8')
    return archive


def scan(store, limit=None):
    """扫一个 official_replays 目录，返回整体字段档案（跨局合并）。"""
    store = Path(store)
    merged, cases = {}, 0
    all_texts = {}
    for folder in sorted(store.glob('camp-*')):
        raw = _read(folder / 'raw.json')
        if raw is None:
            continue
        cases += 1
        archive = build_for_replay(folder.name, store=store)
        for row in archive['fields']:
            entry = merged.setdefault(row['path'], {'path': row['path'], 'types': set(),
                                                    'cases': 0, 'count': 0,
                                                    'samples': []})
            entry['types'].update(row['types'])
            entry['cases'] += 1
            entry['count'] += row['count']
            for sample in row['samples']:
                if len(entry['samples']) < 3 and sample not in entry['samples']:
                    entry['samples'].append(sample)
        for item in archive['texts']:
            all_texts.setdefault(item['text'], item['path'])
        if limit and cases >= limit:
            break
    fields = [{'path': entry['path'], 'types': sorted(entry['types']),
               'cases': entry['cases'], 'count': entry['count'],
               'samples': entry['samples']}
              for entry in sorted(merged.values(), key=lambda item: item['path'])]
    return {'schema': SCHEMA, 'cases': cases, 'fields': fields,
            'texts': [{'text': text, 'path': path} for text, path in sorted(all_texts.items())]}


_LITERAL = re.compile(r"""(?P<q>['"`])((?:\\.|(?!\1).){2,120}?)(?P=q)""", re.S)


def frontend_labels(path, min_len=2):
    """从营地 H5 前端包里抽出中文文案（标签、dtID 名称、提示语）。

    只取字符串字面量里含中文的片段，去重后按文本排序；不执行、不解析 JS 语义。
    """
    try:
        source = Path(path).read_text(encoding='utf-8', errors='ignore')
    except OSError:
        return []
    seen = set()
    for match in _LITERAL.finditer(source):
        text = match.group(2).strip()
        if len(text) < min_len or not CJK.search(text):
            continue
        if '\\n' in text or '<' in text:
            continue
        seen.add(text[:120])
    return sorted(seen)


def write_frontend_labels(source, out):
    labels = frontend_labels(source)
    payload = {'schema': 'camp-frontend-labels-v1', 'source': Path(source).name,
               'count': len(labels), 'labels': labels}
    Path(out).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8')
    return payload


# 营地 H5 前端包是第三方产物，不进仓库；但**从它抽出来的文案**是我们的资料，
# 所以正本放 docs/（可评审、可 diff），运行期副本放 data/。
LABELS_RUNTIME = Path('data') / 'camp_labels.json'
LABELS_DOC = Path('docs') / 'camp_frontend_labels.json'


def load_labels(root=None):
    """读前端文案：先看运行期副本，再退到仓库里的正本；都没有返回空表。"""
    base = Path(root) if root else Path('.')
    for path in (base / LABELS_RUNTIME, base / LABELS_DOC):
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
    return {'schema': 'camp-frontend-labels-v1', 'source': '', 'count': 0, 'labels': []}
