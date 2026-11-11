"""/api/decision/* 冒烟：7 个端点、参数校验、空数据降级、缓存。"""
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import decision_api  # noqa: E402
import decision_fixtures as fx  # noqa: E402


def make_client(tmp_path, *, calibration=True):
    fx.write_dataset(tmp_path, [
        {'seq': '1001', 'own_camp': '1', 'own_win': True},
        {'seq': '1002', 'own_camp': '2', 'own_win': False,
         'diff': [0, -200, -600, -1200, -1800, -1400, -900, -300, 200, 600],
         'win_camp': '1'},
        {'seq': '1003', 'own_camp': '1', 'own_win': True,
         'diff': [0, 500, 1200, 2000, 3000, 2400, 1500, 800, 200, -200],
         'win_camp': '1'},
    ], calibration=calibration)
    app = FastAPI()
    app.include_router(decision_api.create_decision_router(
        tmp_path / 'official_replays', tmp_path / 'camp_details', tmp_path, None))
    return TestClient(app)


def empty_client(tmp_path):
    (tmp_path / 'official_replays').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'camp_details').mkdir(parents=True, exist_ok=True)
    app = FastAPI()
    app.include_router(decision_api.create_decision_router(
        tmp_path / 'official_replays', tmp_path / 'camp_details', tmp_path, None))
    return TestClient(app)


def test_catalog_shape(tmp_path):
    client = make_client(tmp_path)
    response = client.get('/api/decision/catalog')
    assert response.status_code == 200
    data = response.json()
    assert data['coverage']['games'] == 3
    assert {item['id'] for item in data['analyses']} == {
        'loss_chain', 'advantage_retention', 'fight_execution',
        'resource_allocation', 'opening_routes', 'bp_counter'}
    assert data['layers'][0]['id'] == 'A'
    assert len(data['games']) == 3
    assert all('label' in game for game in data['games'])
    assert data['opponents']


def test_all_reports_return_200(tmp_path):
    client = make_client(tmp_path)
    for path in ('/api/decision/briefing', '/api/decision/loss',
                 '/api/decision/advantage', '/api/decision/fights',
                 '/api/decision/opening', '/api/decision/resource',
                 '/api/decision/bp'):
        response = client.get(path)
        assert response.status_code == 200, (path, response.text)
        payload = response.json()
        assert isinstance(payload, dict)
        assert 'available' in payload or path.endswith('briefing') or path.endswith('catalog')


def test_loss_game_detail_and_filters(tmp_path):
    client = make_client(tmp_path)
    data = client.get('/api/decision/loss?game=1002').json()
    assert data['game']['id'] == '1002'
    assert data['game']['series']['approx'] is True
    wins = client.get('/api/decision/loss?result=win').json()
    assert wins['filters']['result'] == 'win'
    assert all(row.get('result') == 'win' for row in wins['rows'])


def test_advantage_payload(tmp_path):
    client = make_client(tmp_path)
    data = client.get('/api/decision/advantage').json()
    assert data['summary']['games'] == 3
    assert len(data['buckets']) == 4
    assert 'bands' in data and isinstance(data['bands'], list) and data['bands']
    assert {'minute', 'win', 'loss', 'all'} <= set(data['bands'][0])


def test_fights_selected(tmp_path):
    client = make_client(tmp_path)
    data = client.get('/api/decision/fights?game=1001').json()
    assert data['summary']['fights'] >= 1
    assert data['selected'] is not None
    assert len(data['selected']['members']) == 10
    assert len(data['selected']['arrivalBars']) == 10
    assert {'player', 'hero', 'camp', 'from', 'to'} <= set(data['selected']['arrivalBars'][0])


def test_opening_and_resource(tmp_path):
    client = make_client(tmp_path)
    opening = client.get('/api/decision/opening').json()
    assert opening['coverage']['positionGames'] >= 1
    assert opening['heat']['cells']
    assert opening['routes']
    resource = client.get('/api/decision/resource').json()
    assert resource['coverage']['panelGames'] == 3
    assert len(resource['players']) == 15
    assert resource['metrics']['goldBasis'] == 'battleStats.money'
    assert resource['quadrant']['x'] == 'goldShare'


def test_invalid_params(tmp_path):
    client = make_client(tmp_path)
    assert client.get('/api/decision/loss?from=2026-13-01').status_code == 400
    assert client.get('/api/decision/loss?from=2026-11-05&to=2026-11-02').status_code == 400
    assert client.get('/api/decision/loss?result=draw').status_code == 400
    assert client.get('/api/decision/fights?side=middle').status_code == 400
    assert client.get('/api/decision/fights?limit=x').status_code == 400


def test_empty_dataset_degrades(tmp_path):
    client = empty_client(tmp_path)
    catalog = client.get('/api/decision/catalog').json()
    assert catalog['coverage']['games'] == 0
    assert all(not item['available'] for item in catalog['analyses'])
    briefing = client.get('/api/decision/briefing').json()
    assert briefing['available'] is False and briefing['reason']


def test_catalog_cached(monkeypatch, tmp_path):
    calls = {'count': 0}
    original = decision_api.decision_facts.load_facts

    def counting(*args, **kwargs):
        calls['count'] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(decision_api.decision_facts, 'load_facts', counting)
    client = make_client(tmp_path)
    client.get('/api/decision/catalog')
    client.get('/api/decision/catalog')
    client.get('/api/decision/advantage')
    assert calls['count'] == 1
