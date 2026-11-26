"""4.0 Alpha2：时间化账号—选手/选手—战队关系、批量建档、合并与撤销。"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from workspace_store import Workspace


@pytest.fixture()
def db(tmp_path):
    return tmp_path / 'training.sqlite3'


def _ws(db):
    return Workspace(db).ensure_schema()


def _player(db_or_ws, player_id):
    ws = db_or_ws if isinstance(db_or_ws, Workspace) else _ws(db_or_ws)
    con = ws.connect()
    try:
        row = con.execute('SELECT * FROM players WHERE id=?', (str(player_id),)).fetchone()
        return dict(row) if row else None
    finally:
        con.close()


def _seed(db):
    ws = _ws(db)
    home = {'id': ws.upsert_team(None, name='本队')}
    away = {'id': ws.upsert_team(None, name='对手A')}
    p1 = {'id': ws.upsert_player(None, team_id=home['id'], name='一诺', position='发育路')}
    p2 = {'id': ws.upsert_player(None, team_id=away['id'], name='对手中路', position='中路')}
    return ws, home, away, p1, p2


def test_membership_timeline_and_undo(db):
    ws, home, away, p1, _ = _seed(db)
    ws.add_membership(p1['id'], home['id'], valid_from='2026-01-01', relation_type='trial')
    ws.add_membership(p1['id'], away['id'], valid_from='2026-03-01', relation_type='formal')
    rows = ws.list_memberships(player_id=p1['id'])
    assert [(r['team_id'], r['validTo']) for r in rows] == [
        (home['id'], '2026-03-01'), (away['id'], None)]
    assert [r['team_id'] for r in ws.list_memberships(player_id=p1['id'], at_date='2026-02-01')] == [home['id']]
    assert [r['team_id'] for r in ws.list_memberships(player_id=p1['id'], at_date='2026-04-01')] == [away['id']]
    assert _player(ws, p1['id'])['team_id'] == away['id']
    ws.undo_membership(rows[1]['membership_id'])
    assert _player(ws, p1['id'])['team_id'] == home['id'], '撤销转会应恢复原战队'
    assert len(ws.list_memberships(player_id=p1['id'])) == 1


def test_account_link_resolution_priority(db):
    ws, home, away, p1, p2 = _seed(db)
    ws.add_account_link('acc-1', p1['id'], valid_from='2026-01-01', valid_to='2026-02-28')
    ws.add_account_link('acc-1', p2['id'], valid_from='2026-03-01')
    assert ws.resolve_player_at('acc-1', at_date='2026-02-01')['playerId'] == p1['id']
    assert ws.resolve_player_at('acc-1', at_date='2026-03-10')['playerId'] == p2['id']
    assert ws.resolve_player_at('acc-1', at_date='2026-03-10')['source'] == 'time'
    ws.add_account_link('acc-1', p1['id'], valid_from='2026-03-05',
                        game_match_key='camp:9001', update_current=False)
    assert ws.resolve_player_at('acc-1', game_match_key='camp:9001')['playerId'] == p1['id']
    assert ws.resolve_player_at('acc-1', game_match_key='camp:9001')['source'] == 'game'
    assert ws.resolve_player_at('acc-1', at_date='2026-03-10')['playerId'] == p2['id']
    with pytest.raises(ValueError):
        ws.add_account_link('acc-1', p1['id'], valid_from='2026-04-01', valid_to='2026-03-01')


def test_batch_roles_idempotent(db):
    ws, home, _, _, _ = _seed(db)
    first = ws.batch_create_role_players(home['id'])
    assert [p['position'] for p in first['players']] == list(Workspace.DEFAULT_LANES)
    second = ws.batch_create_role_players(home['id'])
    assert all(not p['created'] for p in second['players'])
    assert [p['playerId'] for p in first['players']] == [p['playerId'] for p in second['players']]


def test_merge_and_undo(db):
    ws, home, _, p1, p2 = _seed(db)
    ws.map_account('acc-1', player_id=p1['id'])
    ws.add_account_link('acc-1', p1['id'], valid_from='2026-01-01')
    result = ws.merge_players(p1['id'], p2['id'])
    assert result['movedAccounts'] >= 1 and result['movedLinks'] >= 1
    assert ws.resolve_player_at('acc-1')['playerId'] == p2['id']
    assert _player(ws, p1['id'])['status'] == 'archived'
    ws.undo_merge(result['mergeId'])
    assert ws.resolve_player_at('acc-1')['playerId'] == p1['id']
    assert _player(ws, p1['id'])['status'] != 'archived'
    assert _player(ws, p2['id'])['aliases'] == '[]' or '"' not in (_player(ws, p2['id'])['aliases'] or '')


def test_old_db_migration_adds_columns(db):
    con = sqlite3.connect(db)
    con.execute('CREATE TABLE player_team_history (player_id TEXT NOT NULL, team_id TEXT NOT NULL, '
                "start_date TEXT, end_date TEXT, source TEXT, PRIMARY KEY(player_id,team_id,start_date))")
    con.commit(); con.close()
    ws = _ws(db)
    cols = {row[1] for row in ws.connect().execute('PRAGMA table_info(player_team_history)')}
    assert {'membership_id', 'relation_type', 'roster_role', 'undone_at'} <= cols
    assert ws.schema_warnings == []


def test_identity_api(db, tmp_path):
    from studio_api import create_studio_router
    app = FastAPI()
    app.include_router(create_studio_router(db, tmp_path / 'matches', tmp_path / 'imports'))
    client = TestClient(app)
    ws = Workspace(db).ensure_schema()
    home = {'id': ws.upsert_team(None, name='本队')}
    player = {'id': ws.upsert_player(None, team_id=home['id'], name='测试选手')}
    created = client.post('/api/studio/workspace/identity/memberships', json={
        'playerId': player['id'], 'teamId': home['id'], 'validFrom': '2026-01-01'})
    assert created.status_code == 200, created.text
    mid = created.json()['membershipId']
    assert any(m['membership_id'] == mid for m in client.get(
        '/api/studio/workspace/identity/memberships').json()['memberships'])
    assert client.post(f'/api/studio/workspace/identity/memberships/{mid}/undo').status_code == 200
    link = client.post('/api/studio/workspace/identity/account-links', json={
        'accountId': 'acc-api', 'playerId': player['id'], 'validFrom': '2026-01-01'})
    assert link.status_code == 200, link.text
    assert client.get('/api/studio/workspace/identity/resolve',
                      params={'accountId': 'acc-api', 'atDate': '2026-05-01'}).json()['playerId'] == player['id']
    roles = client.post('/api/studio/workspace/identity/players/roles',
                        json={'teamId': home['id']})
    assert roles.status_code == 200 and len(roles.json()['players']) == 5

