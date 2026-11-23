"""系列赛 API 测试：隔离 FastAPI + 假 lookup（不需要真实仓库）。

覆盖（V2.0 方案 §八 交互层验收）：
- suggest 的各识别情况（同日连续 / 跨午夜 / 缺时间 / 已占用 / 不同对手）；
- 创建确认（含 BO 上限与重复归属 409）、PATCH 调序与换成员、DELETE；
- 分析与汇总端点的基本契约（覆盖说明、账本、下钻）。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'v3'))

from series_api import create_series_router  # noqa: E402
import workspace_store  # noqa: E402


def _vector(key, *, date, clock='19:00', opponent='青岚', session='一队',
            version='S30', result='win', at10=1000.0, heroes=None, heroes_foe=None):
    # 每局默认不同的英雄名：全局 BP 账本按「去重后累计」口径，重名会被误判复用
    return {'key': key, 'date': date, 'clock': clock, 'opponent': opponent,
            'session': session, 'version': version, 'result': result,
            'camp': 'blue', 'duration': 1200, 'at10': at10, 'finalDiff': at10,
            'heroes': heroes or [f'{key}-我{i}' for i in range(1, 6)],
            'heroesFoe': heroes_foe or [f'{key}-敌{i}' for i in range(1, 6)],
            'bans': []}


VECTORS = {
    'k1': _vector('k1', date='2026-11-14', clock='19:00', result='win',
                  heroes=['张飞', '盾山', '刘邦', '廉颇', '庄周'],
                  heroes_foe=['镜', '孙尚香', '不知火舞', '马可波罗', '妲己']),
    'k2': _vector('k2', date='2026-11-14', clock='19:30', result='loss'),
    'k3': _vector('k3', date='2026-11-14', clock='20:05', result='win'),
    'k4': _vector('k4', date='2026-11-14', clock='22:00', result='win', opponent='北屿', session='二队'),
    'k5': _vector('k5', date='2026-11-15', clock='00:20', result='win', opponent='北屿', session='二队'),
    'n1': _vector('n1', date='2026-11-16', clock='', result='loss', opponent='北屿', session='二队'),
    'n2': _vector('n2', date='2026-11-16', clock='', result='win', opponent='北屿', session='二队'),
}

DETAILS = {
    'k1': {'ownCamp': 'blue', 'ownSide': 'left',
           'bp': {'picks': {'left': ['张飞', '盾山', '刘邦', '廉颇', '庄周'],
                            'right': ['镜', '孙尚香', '不知火舞', '马可波罗', '妲己']},
                  'bans': {'left': ['东皇太一'], 'right': ['武则天']}, 'firstPick': 'left'}},
}


def make_client(tmp_path):
    def vectors(repo, values=None):
        out = list(VECTORS.values())
        if values and values.get('from'):
            out = [v for v in out if (v.get('date') or '') >= values['from']]
        if values and values.get('to'):
            out = [v for v in out if (v.get('date') or '')[:10] <= values['to']]
        return out

    lookup = {
        'repo': lambda request: None,
        'vectors': lambda repo, values=None: vectors(repo, values),
        'detail': lambda repo, key: DETAILS.get(key),
    }
    # 先种 match_records：真实流程里对局先入库，系列赛起止日期从对局日期推导
    ws = workspace_store.Workspace(tmp_path / 'ws.sqlite3').ensure_schema()
    for key, v in VECTORS.items():
        ws.upsert_match(key, date=v['date'], session=v['session'], status='confirmed', source='test')
    app = FastAPI()
    app.include_router(create_series_router(tmp_path / 'ws.sqlite3', lookup))
    return TestClient(app)


@pytest.fixture()
def client(tmp_path):
    return make_client(tmp_path)


def test_suggest_groups_same_day(client):
    payload = client.post('/api/series/suggest', json={}).json()
    groups = payload['suggestions']
    assert any(g['matchKeys'] == ['k1', 'k2', 'k3'] and g['opponent'] == '青岚' for g in groups)
    # 北屿两局跨午夜但连续 → 同组
    assert any(g['matchKeys'] == ['k4', 'k5'] for g in groups)
    # 缺开赛时间的组要求确认局序
    missing = [g for g in groups if set(g['matchKeys']) == {'n1', 'n2'}]
    assert missing and missing[0]['needsReview'] is True


def test_suggest_blocked_after_confirm(client):
    created = client.post('/api/series', json={
        'bestOf': 3, 'games': ['k1', 'k2', 'k3'], 'opponent': '青岚'}).json()
    assert created['series']['completion'] == 'completed'  # 2:1 到决胜
    payload = client.post('/api/series/suggest', json={}).json()
    keys = [b['matchKey'] for b in payload['blocked']]
    assert {'k1', 'k2', 'k3'} <= set(keys)


def test_bootstrap_returns_page_payload_in_one_call(client):
    payload = client.get('/api/series/bootstrap').json()
    assert payload['total'] == len(VECTORS)
    assert {v['key'] for v in payload['vectors']} == set(VECTORS)
    assert payload['series'] == []
    # 候选只出建议，不落库
    assert payload['suggestions'] and any(s['matchKeys'] for s in payload['suggestions'])
    assert client.get('/api/series').json()['total'] == 0

    client.post('/api/series', json={'bestOf': 3, 'games': ['k1', 'k2', 'k3']})
    payload = client.get('/api/series/bootstrap').json()
    assert len(payload['series']) == 1
    brief = payload['series'][0]
    assert brief['score'] == {'us': 2, 'them': 1}
    # 编组页每局都带时间轴字段
    assert {g['clock'] for g in brief['games']} == {'19:00', '19:30', '20:05'}


def test_create_series_and_sync(client, tmp_path):
    response = client.post('/api/series', json={
        'bestOf': 3, 'games': ['k1', 'k2', 'k3'], 'opponent': '青岚', 'session': '一队'})
    assert response.status_code == 200
    brief = response.json()['series']
    assert brief['bestOf'] == 3 and brief['opponent'] == '青岚'
    assert [g['gameIndex'] for g in brief['games']] == [1, 2, 3]
    assert brief['score'] == {'us': 2, 'them': 1}
    assert brief['completion'] == 'completed'  # 2:1 到决胜
    ws = workspace_store.Workspace(tmp_path / 'ws.sqlite3')
    rows = {row['match_key']: row for row in ws.list_matches(10)}
    assert rows['k1']['series_id'] == brief['id'] and rows['k1']['game_no'] == 1
    stored = ws.get_series(brief['id'])
    assert [(g['matchKey'], g['gameIndex']) for g in stored['games']] == \
        [(g['matchKey'], g['gameIndex']) for g in brief['games']]


def test_create_conflict_returns_409(client):
    client.post('/api/series', json={'bestOf': 3, 'games': ['k1', 'k2', 'k3']})
    again = client.post('/api/series', json={'bestOf': 3, 'games': ['k1']})
    assert again.status_code == 409
    detail = again.json()['detail']
    assert detail['occupied'][0][0] == 'k1'


def test_create_validations(client):
    assert client.post('/api/series', json={'bestOf': 4, 'games': ['k1']}).status_code == 400
    assert client.post('/api/series', json={'bestOf': 3, 'games': ['k1', 'k1']}).status_code == 400
    assert client.post('/api/series', json={'bestOf': 3, 'games': ['k1', 'k2', 'k3', 'k4']}).status_code == 400
    assert client.post('/api/series', json={'games': ['k1']}).status_code == 400


def test_patch_reorder_and_swap_member(client):
    brief = client.post('/api/series', json={
        'bestOf': 3, 'games': ['k1', 'k2', 'k3']}).json()['series']
    # 调序
    patched = client.patch(f"/api/series/{brief['id']}", json={
        'games': [{'matchKey': 'k3', 'gameIndex': 1},
                  {'matchKey': 'k1', 'gameIndex': 2},
                  {'matchKey': 'k2', 'gameIndex': 3}]})
    assert patched.status_code == 200
    assert [g['matchKey'] for g in patched.json()['series']['games']] == ['k3', 'k1', 'k2']
    # 换成员：移出 k2 换 k4
    patched = client.patch(f"/api/series/{brief['id']}", json={
        'games': ['k3', 'k1', 'k4']})
    assert patched.status_code == 200
    keys = [g['matchKey'] for g in patched.json()['series']['games']]
    assert 'k2' not in keys and 'k4' in keys


def test_patch_conflict_409(client):
    first = client.post('/api/series', json={'bestOf': 3, 'games': ['k1', 'k2', 'k3']}).json()['series']
    second = client.post('/api/series', json={'bestOf': 3, 'games': ['k4', 'k5', 'n1']}).json()['series']
    response = client.patch(f"/api/series/{second['id']}", json={'games': ['k4', 'k5', 'k1']})
    assert response.status_code == 409


def test_patch_status_and_notes(client):
    brief = client.post('/api/series', json={'bestOf': 3, 'games': ['k1', 'k2']}).json()['series']
    assert brief['completion'] == 'open'
    patched = client.patch(f"/api/series/{brief['id']}", json={'completion': 'interrupted',
                                                               'notes': '网络中断，只打了 2 局'})
    body = patched.json()['series']
    assert body['completion'] == 'interrupted'  # 教练标注优先，推导不再覆盖
    assert body['notes'] == '网络中断，只打了 2 局'


def test_delete_series(client):
    brief = client.post('/api/series', json={'bestOf': 3, 'games': ['k1', 'k2', 'k3']}).json()['series']
    response = client.delete(f"/api/series/{brief['id']}")
    assert response.status_code == 200
    assert sorted(response.json()['matchKeys']) == ['k1', 'k2', 'k3']
    assert client.get(f"/api/series/{brief['id']}").status_code == 404


def test_list_and_filters(client):
    client.post('/api/series', json={'bestOf': 3, 'games': ['k1', 'k2', 'k3'],
                                     'opponent': '青岚', 'session': '一队'})
    client.post('/api/series', json={'bestOf': 3, 'games': ['k4', 'k5'],
                                     'opponent': '北屿', 'session': '二队'})
    assert client.get('/api/series').json()['total'] == 2
    assert client.get('/api/series', params={'session': '一队'}).json()['total'] == 1
    assert client.get('/api/series', params={'bestOf': 5}).json()['total'] == 0
    assert client.get('/api/series', params={'from': '2026-11-15'}).json()['total'] == 1


def test_analysis_endpoint(client):
    brief = client.post('/api/series', json={'bestOf': 3, 'games': ['k1', 'k2', 'k3']}).json()['series']
    body = client.get(f"/api/series/{brief['id']}/analysis").json()
    assert body['score'] == {'us': 2, 'them': 1}
    assert len(body['games']) == 3
    assert body['games'][0]['orderKnown'] is True      # k1 有人工 BP
    assert body['games'][1]['orderKnown'] is False     # 其余只有营地/向量口径
    assert body['bpLedger']['ruleset']['id'] == 'scrim-global-team'
    assert body['bpLedger']['perGame'][-1]['usedUsCount'] == 15
    assert any('手序' in c for c in body['caveats'])
    # 大场挖掘层：假 lookup 没有全量语料，也要返回结构化 insight 并降级
    assert body['insight']['version'] == 'series-insight-v1'
    assert body['insight']['sample']['games'] == 3
    assert body['insight']['flow']['model'] is None
    assert client.get('/api/series/ts-missing/analysis').status_code == 404


def test_summary_endpoint(client):
    client.post('/api/series', json={'bestOf': 3, 'games': ['k1', 'k2', 'k3'], 'opponent': '青岚'})
    client.post('/api/series', json={'bestOf': 3, 'games': ['k4', 'k5', 'n1'], 'opponent': '北屿'})
    body = client.get('/api/cross/series-summary').json()
    assert body['summary']['totals']['series'] == 2
    assert body['summary']['totals']['games'] == 6
    assert len(body['series']) == 2
    first = body['series'][0]
    assert first['games'][0]['usedUsCount'] == 5
    assert len(body['rulesets']) == 3


def test_series_competition_scope(tmp_path):
    """赛事域（M1）：系列归属推导、混编拦截、列表过滤与 boBp 跨赛事开关。

    这里自带 lookup（corpus 指向假向量），让 boBp 历史真的有对局可数。
    """
    import sqlite3

    # 第二个 A 赛事系列用 k6（只在本地 lookup 里扩一份向量，不动共享 VECTORS）
    vectors = {**VECTORS, 'k6': _vector('k6', date='2026-11-14', clock='21:00',
                                        opponent='青岚', result='win')}
    lookup = {
        'repo': lambda request: None,
        'vectors': lambda repo, values=None: list(vectors.values()),
        'detail': lambda repo, key: DETAILS.get(key),
        'corpus': lambda repo: list(vectors.values()),
    }
    ws = workspace_store.Workspace(tmp_path / 'ws.sqlite3').ensure_schema()
    for key, v in vectors.items():
        ws.upsert_match(key, date=v['date'], session=v['session'], status='confirmed', source='test')
    app = FastAPI()
    app.include_router(create_series_router(tmp_path / 'ws.sqlite3', lookup))
    client = TestClient(app)
    ws = workspace_store.Workspace(tmp_path / 'ws.sqlite3')
    ca = ws.save_competition(name='赛事A', date='2026-11-01')
    cb = ws.save_competition(name='赛事B', date='2026-12-01')
    with sqlite3.connect(ws.db_path) as connection:
        for key in ('k1', 'k2', 'k3', 'k6'):
            connection.execute('UPDATE match_records SET competition_id=? WHERE match_key=?', (ca, key))
        for key in ('k4', 'k5', 'n1', 'n2'):
            connection.execute('UPDATE match_records SET competition_id=? WHERE match_key=?', (cb, key))

    sa = client.post('/api/series', json={'bestOf': 3, 'games': ['k1', 'k2', 'k3']}).json()['series']
    assert sa['competitionId'] == ca
    sb = client.post('/api/series', json={'bestOf': 3, 'games': ['k4', 'k5']}).json()['series']
    client.post('/api/series', json={'bestOf': 3, 'games': ['n1', 'n2']})
    # 同赛事第二个系列：boBp 历史至少要能数到它
    sa2 = client.post('/api/series', json={'bestOf': 3, 'games': ['k6']}).json()['series']

    # 混编：所选对局分属不同赛事 → 报错（400/409）
    mixed = client.post('/api/series', json={'bestOf': 3, 'games': ['k1', 'k4']})
    assert mixed.status_code in (400, 409)

    # 列表按赛事过滤
    ids_a = [item['id'] for item in
             client.get('/api/series', params={'competition': ca}).json()['series']]
    assert sa['id'] in ids_a and sb['id'] not in ids_a

    # boBp 历史默认只看同一赛事；includeOtherEvents=1 显式跨赛事
    scoped = client.get(f"/api/series/{sa['id']}/analysis",
                        params={'competition': ca}).json()['insight']['boBp']
    assert scoped['available'] is True
    assert [item['id'] for item in scoped['history']] == [sa2['id']]
    other = client.get(f"/api/series/{sa['id']}/analysis",
                       params={'competition': ca, 'includeOtherEvents': '1'}).json()['insight']['boBp']
    assert any(item['id'] == sb['id'] for item in other['history'])
