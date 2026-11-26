"""归档纠错：拉错的局可排除、可撤销；原记录保留，所有归集口径统一过滤。"""
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from studio_api import create_studio_router  # noqa: E402
from workspace_store import Workspace  # noqa: E402


@pytest.fixture()
def ws(tmp_path):
    store = Workspace(tmp_path / 'ws.sqlite3')
    store.ensure_schema()
    return store


def client(ws, tmp_path):
    app = FastAPI()
    app.include_router(create_studio_router(
        ws.db_path, tmp_path / 'matches', tmp_path / 'imports', tmp_path / 'studio.sqlite3'))
    return TestClient(app)


def test_exclude_then_restore_match(ws, tmp_path):
    cid = ws.save_competition(name='春季赛', date='2026-11-01', end_date='2026-11-30')
    ws.upsert_match('rank:1', date='2026-11-23', session='排位赛', winner='blue')
    assert [row['match_key'] for row in ws.competition_training_matches(cid)] == ['rank:1']
    assert [row['match_key'] for row in ws.unfiled_training_matches()] == []

    api = client(ws, tmp_path)
    response = api.post('/api/studio/workspace/matches/rank:1/exclude',
                        json={'reason': '排位赛误拉入'})
    assert response.status_code == 200
    assert response.json()['excluded'] is True

    assert ws.competition_training_matches(cid) == []
    assert ws.unfiled_training_matches() == []
    listed = api.get('/api/studio/workspace/matches/excluded').json()
    assert listed['count'] == 1
    assert listed['matches'][0]['excluded_reason'] == '排位赛误拉入'

    # 原记录仍在库里，撤销后按日期重新归集回赛事窗口
    assert ws.list_matches()
    response = api.post('/api/studio/workspace/matches/rank:1/restore')
    assert response.status_code == 200
    assert [row['match_key'] for row in ws.competition_training_matches(cid)] == ['rank:1']
    assert api.get('/api/studio/workspace/matches/excluded').json()['count'] == 0
