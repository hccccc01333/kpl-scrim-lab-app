import os

os.environ.setdefault('TRAINING_ALLOW_REMOTE', '1')

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from studio_api import create_studio_router  # noqa: E402
from workspace_store import Workspace  # noqa: E402


def _client(tmp_path):
    app = FastAPI()
    app.include_router(create_studio_router(
        tmp_path / 'studio.sqlite3', tmp_path / 'media', tmp_path / 'settings'))
    return TestClient(app)


def test_matching_rules_crud_and_scope(tmp_path):
    ws = Workspace(tmp_path / 'ws.sqlite3').ensure_schema()
    ws.upsert_team(team_id='team-a', name='高校队')
    ws.upsert_team(team_id='team-b', name='青岚')
    client = _client(tmp_path)

    assert client.get('/api/studio/matching/rules').json()['rules'] == []
    created = client.post('/api/studio/matching/rules', json={
        'side': 'enemy', 'nickname': '起起灵喵', 'playerId': 'p-1', 'teamId': 'team-a',
    })
    assert created.status_code == 200
    rule = created.json()['rule']
    assert rule['scope'] == 'team-a'
    assert rule['enabled'] is True

    updated = client.post('/api/studio/matching/rules', json={
        'id': rule['id'], 'side': 'enemy', 'nickname': '起起灵喵',
        'playerId': 'p-2', 'teamId': 'team-a', 'enabled': False,
    })
    assert updated.json()['rule']['playerId'] == 'p-2'
    assert updated.json()['rule']['enabled'] is False

    own = client.post('/api/studio/matching/rules', json={
        'side': 'own', 'nickname': '游走喵', 'playerId': 'p-own',
    }).json()['rule']
    assert own['scope'] == ''

    assert [r['nickname'] for r in client.get(
        '/api/studio/matching/rules?side=own').json()['rules']] == ['游走喵']
    assert client.post('/api/studio/matching/rules/delete',
                       json={'id': rule['id']}).json()['deleted'] == 1
    assert [r['id'] for r in client.get(
        '/api/studio/matching/rules').json()['rules']] == [own['id']]


def test_matching_rule_rejects_bad_payload(tmp_path):
    client = _client(tmp_path)
    bad = client.post('/api/studio/matching/rules', json={
        'side': 'other', 'nickname': 'x', 'playerId': 'p',
    })
    assert bad.status_code == 400
