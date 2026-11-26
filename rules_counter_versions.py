"""规则中心「克制关系」的赛事定稿版本库。

教练每个赛事里改出来的最后一套克制关系，点「定稿留档」或赛事归档时会被
整份拷进这里。之后复盘旧赛事时，读取的是当时定稿的快照，不会被下一个赛事
的改动串味。live 表 `rules_counters.json` 仍然可继续编辑，两者互不覆盖。
"""
from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 'rules-center-counters-versions-v1'
FILENAME = 'rules_counters_versions.json'

_ROOT = Path(__file__).resolve().parent
try:
    import bp_facts
    FACTS = Path(bp_facts.FACTS)
except Exception:  # pragma: no cover - 独立脚本场景
    FACTS = _ROOT / 'data' / 'facts'

PATH = FACTS / FILENAME
_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _default() -> dict:
    return {'schema': SCHEMA, 'revision': 0, 'updatedAt': '', 'versions': []}


def load() -> dict:
    try:
        doc = json.loads(PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return _default()
    if not isinstance(doc, dict) or not isinstance(doc.get('versions'), list):
        return _default()
    return doc


def _write(doc: dict) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='counter-versions-', suffix='.json', dir=str(PATH.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(doc, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, PATH)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _has_effective(eff: dict) -> bool:
    return any(str((eff or {}).get(key) or '').strip()
               for key in ('eventId', 'eventName', 'from', 'to'))


def matches(row: dict, competition: dict) -> bool:
    """与前端 effectiveMatches 同一口径：常年生效 + 命中赛事 ID / 名称 / 时间窗。"""
    eff = row.get('effective') or {}
    if not _has_effective(eff):
        return True
    comp_id = str(competition.get('id') or '').strip()
    comp_name = str(competition.get('name') or '').strip()
    event_id = str(eff.get('eventId') or '').strip()
    event_name = str(eff.get('eventName') or '').strip()
    if event_id and event_id == comp_id:
        return True
    if event_name and event_name == comp_name:
        return True
    start = str(eff.get('from') or '').strip()
    end = str(eff.get('to') or '').strip()
    date = str(competition.get('date') or competition.get('formal_from') or '').strip()[:10]
    return bool(start and date and date >= start and (not end or date <= end))


def latest(competition_id: str) -> dict | None:
    comp_id = str(competition_id or '').strip()
    if not comp_id:
        return None
    rows = [item for item in load().get('versions') or []
            if isinstance(item, dict) and str(item.get('competitionId') or '') == comp_id]
    if not rows:
        return None
    return max(rows, key=lambda item: str(item.get('finalizedAt') or ''))


def finalize(competition: dict, counters_doc: dict, summary: str = '') -> dict:
    """把当前 live 表里适用于该赛事的克制关系做成一份不可变快照。"""
    comp_id = str(competition.get('id') or '').strip()
    if not comp_id:
        raise ValueError('赛事 ID 不能为空')
    doc = load()
    versions = [item for item in doc.get('versions') or [] if isinstance(item, dict)]
    at = _now()
    hero = [copy.deepcopy(row) for row in (counters_doc.get('heroPairs') or [])
            if isinstance(row, dict) and matches(row, competition)]
    combo = [copy.deepcopy(row) for row in (counters_doc.get('comboPairs') or [])
             if isinstance(row, dict) and matches(row, competition)]
    version = {
        'id': f'{comp_id}-{datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")}',
        'competitionId': comp_id,
        'competitionName': str(competition.get('name') or ''),
        'finalizedAt': at,
        'summary': str(summary or f'{competition.get("name") or comp_id} 克制关系定稿')[:200],
        'sourceRevision': int(counters_doc.get('revision') or 0),
        'doc': {
            'schema': 'rules-center-counters-v1',
            'revision': int(counters_doc.get('revision') or 0),
            'updatedAt': counters_doc.get('updatedAt') or '',
            'heroPairs': hero,
            'comboPairs': combo,
        },
        'counts': {'hero': len(hero), 'combo': len(combo)},
    }
    versions.append(version)
    doc['versions'] = versions[-200:]
    doc['revision'] = int(doc.get('revision') or 0) + 1
    doc['updatedAt'] = at
    with _LOCK:
        _write(doc)
    return version
