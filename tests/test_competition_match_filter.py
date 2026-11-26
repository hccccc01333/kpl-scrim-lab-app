"""按赛事过滤/归属对局：Workspace 查询、Studio 直连接口、分析 API 过滤。

全部使用隔离的临时工作区库（参照 tests/test_workspace_store.py 的 ws fixture），
不触碰项目 data/ 下的真实数据库。
"""
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis_api import create_analysis_router  # noqa: E402
from studio_api import create_studio_router  # noqa: E402
from workspace_store import Workspace  # noqa: E402
from tests.test_analysis_data import make_db  # noqa: E402


@pytest.fixture()
def ws(tmp_path):
    store = Workspace(tmp_path / 'ws.sqlite3')
    store.ensure_schema()
    return store


def studio_client(ws, tmp_path):
    app = FastAPI()
    app.include_router(create_studio_router(
        ws.db_path, tmp_path / 'matches', tmp_path / 'imports', tmp_path / 'studio.sqlite3'))
    return TestClient(app)


def test_competition_matches_query_uses_direct_column(ws):
    cid = ws.save_competition(name='春季赛', date='2026-11-01')
    other = ws.save_competition(name='夏季赛', date='2026-11-02')
    ws.upsert_match('m-camp:1', date='2026-11-03', competition_id=cid, winner='blue')
    ws.upsert_match('m-camp:2', date='2026-11-04', competition_id=other, winner='red')
    ws.upsert_match('m-camp:3', date='2026-11-05', winner='blue')  # 未归属

    rows = ws.competition_matches(cid)
    assert [row['match_key'] for row in rows] == ['m-camp:1']
    assert rows[0]['competition_id'] == cid and rows[0]['winner'] == 'blue'
    assert ws.competition_matches('missing') == []
    # 取消归属后直连接口不再返回该对局，但对局本身还在
    # （upsert_match 的 None=「本次不改」，解绑由 studio 的整批覆盖/SQL 完成）
    with sqlite3.connect(ws.db_path) as connection:
        connection.execute('UPDATE match_records SET competition_id=NULL WHERE match_key=?',
                           ('m-camp:1',))
    assert ws.competition_matches(cid) == []
    assert any(row['match_key'] == 'm-camp:1' for row in ws.list_matches())


def test_studio_competition_matches_endpoint(ws, tmp_path):
    cid = ws.save_competition(name='春季赛', date='2026-11-01')
    ws.upsert_match('m-camp:1', date='2026-11-03', competition_id=cid, own_side='blue')
    ws.upsert_match('m-camp:2', date='2026-11-04')
    client = studio_client(ws, tmp_path)

    response = client.get(f'/api/studio/workspace/competitions/{cid}/matches')
    assert response.status_code == 200
    body = response.json()
    assert body['competitionId'] == cid and body['count'] == 1
    assert [row['match_key'] for row in body['matches']] == ['m-camp:1']
    assert client.get('/api/studio/workspace/competitions/nope/matches').status_code == 404

    # POST 归属整批覆盖，随后直连接口立即反映新归属
    assigned = client.post(f'/api/studio/workspace/competitions/{cid}/matches',
                           json={'matchKeys': ['m-camp:2']})
    assert assigned.status_code == 200 and assigned.json()['count'] == 1
    keys = [row['match_key'] for row in
            client.get(f'/api/studio/workspace/competitions/{cid}/matches').json()['matches']]
    assert keys == ['m-camp:2']


def test_studio_competition_text_fields_clear_and_preserve(ws, tmp_path):
    """空字符串能清空文本字段，字段缺失则保留原值（save_competition 的合并语义）。"""
    client = studio_client(ws, tmp_path)
    full = {
        'name': '春季赛', 'date': '2026-11-01', 'endDate': '2026-12-31',
        'stage': '常规赛', 'format': 'BO5', 'headCoach': '张教练',
        'assistantCoach': '李教练', 'dataAnalyst': '分析师',
        'owner': '王教练', 'notes': '备注',
    }
    created = client.post('/api/studio/workspace/competitions', json=full)
    assert created.status_code == 200
    cid = created.json()['id']
    keys = ('end_date', 'stage', 'format', 'head_coach', 'assistant_coach',
            'data_analyst', 'owner', 'notes')
    row = ws.get_competition(cid)
    assert row['head_coach'] == '张教练' and row['stage'] == '常规赛'

    # 显式传空字符串：应清空而不是保留旧值
    clear = dict(full, id=cid, endDate='', stage='', format='', headCoach='',
                 assistantCoach='', dataAnalyst='', owner='', notes='')
    assert client.post('/api/studio/workspace/competitions', json=clear).status_code == 200
    assert all(ws.get_competition(cid)[key] == '' for key in keys)

    # 写回后只传必填字段：缺失字段应保留原值
    assert client.post('/api/studio/workspace/competitions',
                       json=dict(full, id=cid)).status_code == 200
    assert client.post('/api/studio/workspace/competitions',
                       json={'id': cid, 'name': '春季赛', 'date': '2026-11-01'}).status_code == 200
    row = ws.get_competition(cid)
    assert row['head_coach'] == '张教练' and row['stage'] == '常规赛'
    assert row['end_date'] == '2026-12-31' and row['notes'] == '备注'
    assert row['format'] == 'BO5' and row['owner'] == '王教练'


def test_analysis_endpoints_filter_matches_by_competition(tmp_path):
    """analysis API 的 competition 参数复用 match_records.competition_id 收窄所有聚合端点。"""
    db = tmp_path / 'training.sqlite3'
    make_db(db)  # 建立 settings + matches(body) 与两局 db-A / db-B
    ws = Workspace(db)
    ws.ensure_schema()  # 在同一库补建 match_records 等表（旧 matches(body) 表会被跳过）
    cid = ws.save_competition(name='春季赛', date='2026-11-01')
    ws.upsert_match('db-A', date='2026-10-01', competition_id=cid)

    matches_dir = tmp_path / 'matches'
    imports_dir = tmp_path / 'imports'
    matches_dir.mkdir(exist_ok=True)
    imports_dir.mkdir(exist_ok=True)
    app = FastAPI()
    app.include_router(create_analysis_router(db, matches_dir, imports_dir))
    client = TestClient(app)

    all_matches = client.get('/api/analysis/matches').json()['matches']
    assert {row['key'] for row in all_matches} == {'db-A', 'db-B'}

    filtered = client.get('/api/analysis/matches', params={'competition': cid})
    assert filtered.status_code == 200
    assert [row['key'] for row in filtered.json()['matches']] == ['db-A']

    # filters 回显同时接受 camelCase 兼容名；未知赛事返回空集而不是全部对局
    assert client.get('/api/analysis/teams',
                      params={'competitionId': cid}).json()['filters']['competition'] == cid
    assert client.get('/api/analysis/matches', params={'competition': 'nope'}).json()['matches'] == []

    # 聚合端点：赛事内只有 A，师父/英雄/选手/对手都只剩 A 的数据
    teams = client.get('/api/analysis/teams', params={'competition': cid}).json()
    heroes = client.get('/api/analysis/heroes', params={'competition': cid}).json()
    players = client.get('/api/analysis/players', params={'competition': cid}).json()
    bp = client.get('/api/analysis/bp', params={'competition': cid}).json()
    assert '对手A' in str(teams['team'])
    assert '对手B' not in str(teams['team'])
    assert 'db-A' in str(heroes['heroes']) and 'db-B' not in str(heroes['heroes'])
    assert 'db-B' not in str(bp)  # BP 汇总没有 BP 数据时不暴露对局 key，至少不能串入 B
    # 选手聚合不暴露 key，用场次与最近日期验证只包含赛事内那局
    assert players['players']
    assert all(item['matches'] == 1 and item['lastDate'] == '2026-10-01'
               for item in players['players'])


def test_analysis_competency_scope_falls_back_to_file_layer(tmp_path):
    """营地采集的对局只在数据包里、没在 match_records 建行时，带赛事参数的
    分析端点仍应按赛事窗口纳入它们（首页本来就看得到）。"""
    db = tmp_path / 'training.sqlite3'
    make_db(db)  # db-A(2026-10-01) / db-B(2026-10-02) 只在 matches(body) 里
    ws = Workspace(db)
    ws.ensure_schema()
    cid = ws.save_competition(name='春季赛', date='2026-10-01', end_date='2026-10-31')
    # 刻意不 upsert_match：模拟营地采集没在权威表登记的局

    app = FastAPI()
    app.include_router(create_analysis_router(db, tmp_path / 'matches', tmp_path / 'imports'))
    client = TestClient(app)

    all_keys = {row['key'] for row in client.get('/api/analysis/matches').json()['matches']}
    assert all_keys == {'db-A', 'db-B'}

    scoped = client.get('/api/analysis/matches', params={'competition': cid}).json()['matches']
    assert {row['key'] for row in scoped} == {'db-A', 'db-B'}

    # 窗口外的赛事不应把这两局拉进去
    other = ws.save_competition(name='其他赛事', date='2026-01-01', end_date='2026-02-01')
    assert client.get('/api/analysis/matches',
                      params={'competition': other}).json()['matches'] == []
