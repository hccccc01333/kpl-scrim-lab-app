"""赛事域 scope 文件层兜底回归：营地采集/表格导入的对局没在 match_records 建行时，
带 competition 参数的分析页（单局/大场/跨场）不能把它静默过滤掉。

赛训组反馈的现象：首页（/api/briefing，不带赛事参数）能看到 26 号导入的对局，
单局分析 / 大场分析 / 跨场分析（带 competition）却看不到。
"""
import os
import sqlite3
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'v3'))

os.environ['TRAINING_DB'] = str(
    ROOT / 'test-results' / f'test-scope-file-fallback-{uuid.uuid4().hex}.sqlite3')

import serve  # noqa: E402
from workspace_store import Workspace  # noqa: E402


@pytest.fixture()
def store(tmp_path):
    db = tmp_path / 'ws.sqlite3'
    ws = Workspace(db)
    ws.ensure_schema()
    return ws, db


def test_file_only_match_in_window_enters_scope(store):
    ws, db = store
    cid = ws.save_competition(name='春季赛', date='2026-10-01', end_date='2027-05-29')
    other = ws.save_competition(name='其他赛事', date='2026-10-01', end_date='2027-05-29')

    # 营地采集的对局只在数据包里，match_records 没有建行；另一局明确直连其他赛事。
    ws.upsert_match('camp:other-event', date='2026-11-26', competition_id=other,
                    recorded_date='2026-11-26')
    data = {
        'matches': [
            {'key': 'camp:26-1', 'date': '2026-11-26'},
            {'key': 'camp:other-event', 'date': '2026-11-26'},
            {'key': 'camp:out-of-window', 'date': '2029-01-01'},
        ],
        'sheetMatches': [{'key': 'import-26-1', 'date': '2026-11-26'}],
    }

    with patch.object(serve, 'DB', db):
        keys = serve._competition_scope_keys(cid, data)

    # 窗口内的文件层对局被补齐；明确归属其他赛事、窗口外的对局仍被排除。
    assert 'camp:26-1' in keys
    assert 'import-26-1' in keys
    assert 'camp:other-event' not in keys
    assert 'camp:out-of-window' not in keys


def test_db_owned_match_keeps_scope_without_file_layer(store):
    ws, db = store
    cid = ws.save_competition(name='春季赛', date='2026-10-01', end_date='2027-05-29')
    ws.upsert_match('camp:db-owned', date='2026-11-25', competition_id=cid,
                    recorded_date='2026-11-25')

    with patch.object(serve, 'DB', db):
        keys = serve._competition_scope_keys(cid, {'matches': []})

    assert 'camp:db-owned' in keys


def test_no_competition_returns_empty(store):
    ws, db = store
    with patch.object(serve, 'DB', db):
        assert serve._competition_scope_keys('', {'matches': []}) == set()


def test_damaged_db_does_not_break_scope(store):
    ws, db = store
    bad = db.parent / 'broken.sqlite3'
    bad.write_text('not a sqlite database', encoding='utf-8')
    with patch.object(serve, 'DB', bad):
        keys = serve._competition_scope_keys('comp-x', {'matches': [
            {'key': 'camp:26-1', 'date': '2026-11-26'}]})
    assert keys == set()


def test_unassigned_series_in_window_enters_competition_view(store):
    """编组时对局没在权威表登记 → 系列赛 competition_id 为空；
    大场/跨场页按赛事筛选时仍应按开赛日窗口把它收进来。"""
    ws, db = store
    cid = ws.save_competition(name='春季赛', date='2026-10-01', end_date='2027-05-29')
    other = ws.save_competition(name='其他赛事', date='2026-01-01', end_date='2026-02-01')

    ws.upsert_match('g1', date='2026-11-26')
    ws.upsert_match('g2', date='2026-11-26')
    ws.upsert_match('g3', date='2026-01-15')
    ws.upsert_match('g4', date='2026-01-15')
    # 无归属的组：模拟当时推不出赛事
    ws.create_series(best_of=3, games=['g1', 'g2'], start_at='2026-11-26',
                     status='confirmed')
    # 明确归属其他赛事的组，不应被拉回本赛事
    ws.create_series(best_of=3, games=['g3', 'g4'], start_at='2026-11-26',
                     competition_id=other, status='confirmed')

    mine = ws.list_series(competition=cid)
    assert any(s['startAt'] == '2026-11-26' for s in mine)
    # 归属其他赛事的组只出现在它自己的赛事视图
    assert all(s.get('competitionId') in (None, '', cid) for s in mine)
