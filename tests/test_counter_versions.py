"""赛事定稿版本：复盘旧赛事必须读到当时的最终版，而不是后来改过的 live 表。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import rules_counter_versions as versions  # noqa: E402


def test_finalize_snapshots_only_matching_rows_and_keeps_them_immutable(tmp_path, monkeypatch):
    monkeypatch.setattr(versions, 'PATH', tmp_path / 'versions.json')
    comp = {'id': 'comp-2025', 'name': '2025 春季赛', 'date': '2025-03-01'}
    live = {
        'revision': 7, 'updatedAt': '2025-03-02T00:00:00+00:00',
        'heroPairs': [
            {'id': 'always', 'a': 'A', 'b': 'B', 'effective': {}},
            {'id': 'bound', 'a': 'C', 'b': 'D',
             'effective': {'eventId': 'comp-2025', 'eventName': '2025 春季赛', 'from': '', 'to': ''}},
            {'id': 'other', 'a': 'E', 'b': 'F',
             'effective': {'eventId': 'comp-2026', 'eventName': '', 'from': '', 'to': ''}},
            {'id': 'window', 'a': 'G', 'b': 'H',
             'effective': {'eventId': '', 'eventName': '', 'from': '2025-01-01', 'to': '2025-06-30'}},
            {'id': 'old-window', 'a': 'I', 'b': 'J',
             'effective': {'eventId': '', 'eventName': '', 'from': '2024-01-01', 'to': '2024-06-30'}},
        ],
        'comboPairs': [],
    }

    version = versions.finalize(comp, live, summary='赛季最终版')
    found = versions.latest('comp-2025')
    assert found is not None
    ids = [row['id'] for row in found['doc']['heroPairs']]
    assert set(ids) == {'always', 'bound', 'window'}
    assert found['counts'] == {'hero': 3, 'combo': 0}
    assert found['sourceRevision'] == 7
    assert found['summary'] == '赛季最终版'

    # 之后 live 表怎么改，已经定稿的快照都不变。
    live['heroPairs'][0]['strength'] = '弱'
    live['heroPairs'].append({'id': 'new', 'a': 'K', 'b': 'L', 'effective': {}})
    again = versions.latest('comp-2025')
    assert again['id'] == version['id']
    assert [row['id'] for row in again['doc']['heroPairs']] == ids
    assert next(row for row in again['doc']['heroPairs'] if row['id'] == 'always').get('strength') != '弱'
    assert versions.latest('comp-2026') is None
