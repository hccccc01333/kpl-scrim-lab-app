"""赛训组配置（组合池 / 评级规则）的变更历史。

每次保存前把「旧版本快照 + 时间 + 变更摘要」记一条，供设置页展示与回滚。
- 系统没有登录身份，所以摘要由调用方自动生成（如「删除 1 个组合」「修改游走参团率阈值」），
  历史里记的是「时间 + 做了什么」，不记人名。
- 文件落在配置同目录 <name>_history.json，尊重 KPL_DATA_DIR 覆盖。
- 只保留最近 MAX_ENTRIES 条，避免无限增长。
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import bp_facts

SCHEMA = 'config-history-v1'
MAX_ENTRIES = 50


def history_path(name: str) -> Path:
    """name 为 'combo_pool' / 'grade_rules'；文件名 <name>_history.json。"""
    base = name.replace('/', '_').replace('\\', '_')
    return bp_facts.FACTS / f'{base}_history.json'


def _read(name: str) -> dict:
    file = history_path(name)
    if file.exists():
        try:
            doc = json.loads(file.read_text(encoding='utf-8'))
            if isinstance(doc, dict) and doc.get('schema') == SCHEMA and isinstance(doc.get('entries'), list):
                return doc
        except (OSError, ValueError):
            pass
    return {'schema': SCHEMA, 'entries': []}


def _write(name: str, doc: dict) -> None:
    file = history_path(name)
    file.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='config-history-', suffix='.json', dir=str(file.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(doc, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, file)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def record(name: str, old_doc: dict | None, new_doc: dict, summary: str = '') -> dict:
    """保存前调用：把旧快照记一条。new_doc 只用于取 revision，不入库。

    old_doc 为 None（首次保存，之前只有内置默认）时也记一条，快照为空对象，
    这样「撤销上次修改」能回到未保存状态。
    """
    doc = _read(name)
    entry = {
        'id': uuid.uuid4().hex[:12],
        'at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        # 记「保存后」的修订号：调用方 save() 会把 revision +1，撤销时要用这个新号做乐观锁。
        'revision': int((new_doc or {}).get('revision') or 0) + 1,
        'summary': str(summary or '配置已更新'),
        'doc': old_doc or None,   # None 表示之前未保存（只有内置默认）
    }
    doc['entries'].append(entry)
    doc['entries'] = doc['entries'][-MAX_ENTRIES:]
    _write(name, doc)
    return entry


def list_entries(name: str, limit: int = 50) -> list[dict]:
    """返回历史摘要（不含大快照 doc），供设置页列表展示。"""
    entries = _read(name)['entries']
    out = []
    for e in entries[-limit:]:
        out.append({k: e.get(k) for k in ('id', 'at', 'revision', 'summary')})
        out[-1]['hasSnapshot'] = e.get('doc') is not None
    return list(reversed(out))   # 最新在前


def get_snapshot(name: str, entry_id: str):
    """按 id 取旧快照，用于回滚。找不到返回 None。"""
    for e in _read(name)['entries']:
        if e.get('id') == entry_id:
            return e.get('doc')
    return None


def clear(name: str) -> None:
    _write(name, {'schema': SCHEMA, 'entries': []})


def diff_summary(name: str, old: dict | None, new: dict) -> str:
    """对比新旧配置，生成一句中文摘要（赛训组看得懂的「做了什么」）。"""
    if old is None:
        return '首次保存（由内置默认转为自定义）'
    parts = []
    if name == 'combo_pool':
        for key, label in (('pairs', '双人组合'), ('trios', '三人体系')):
            before = old.get(key) or []
            after = new.get(key) or []
            if before == after:
                continue
            def sig(row):
                return (tuple(sorted((row.get('heroes') or []))), row.get('name'), row.get('strength'))
            b, a = {sig(r) for r in before}, {sig(r) for r in after}
            added, removed = len(a - b), len(b - a)
            bits = []
            if added: bits.append(f'新增 {added}')
            if removed: bits.append(f'删除 {removed}')
            if not added and not removed and before != after: bits.append('修改若干')
            if bits: parts.append(f'{label}·' + '、'.join(bits))
    elif name == 'grade_rules':
        ob, nb = old.get('subjects') or {}, new.get('subjects') or {}
        changed = []
        for subject, fields in nb.items():
            ofs = ob.get(subject) or {}
            for field, rule in (fields or {}).items():
                if ofs.get(field) != rule:
                    label = (rule or {}).get('label') or field
                    changed.append(f'{subject}·{label}')
        if changed:
            shown = '、'.join(changed[:3])
            more = f' 等 {len(changed)} 项' if len(changed) > 3 else ''
            parts.append(f'调整阈值：{shown}{more}')
    return '；'.join(parts) if parts else '配置已更新'
