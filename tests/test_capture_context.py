"""统一采集上下文：视角校验、playerId 双匹配池、最后 BO 编组（赛事为唯一范围）。"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import capture_context
from test_team_clusters import A, panel, write_panels
from workspace_store import Workspace


def _seed(tmp_path):
    db = tmp_path / 'training.sqlite3'
    ws = Workspace(db).ensure_schema()
    comp_id = ws.save_competition(None, name='春季赛', date='2026-11-01',
                                  end_date='2026-12-31',
                                  formal_from='2026-11-20', formal_to='2026-12-31')
    home = ws.upsert_team(None, name='本队')
    away = ws.upsert_team(None, name='对手')
    for i in range(5):
        key = f'camp:{100 + i}'
        ws.upsert_match(key, date='2026-11-05', match_type='training', status='confirmed')
    batch = ws.create_capture_batch(competition_id=comp_id, own_team_id=home,
                                    opponent_team_id=away, camp_user_id='acc-1')
    camp = tmp_path / 'camp_details'
    write_panels(camp, [('101', panel(101, A, '11-05 19:00')),
                        ('102', panel(102, A, '11-05 20:00'))])
    return db, ws, comp_id, batch, camp


def test_analyze_viewpoint_warning_and_pools(tmp_path):
    db, ws, comp_id, batch, camp = _seed(tmp_path)
    analysis = capture_context.analyze(db, camp, batch=batch,
                                       entries=[{'gameSeq': '101', 'accountId': 'acc-1',
                                                 'ownerName': '采集昵称'}])
    assert len(analysis['rows']) == 1
    assert analysis['rows'][0]['viewpoint'] == 'blue'
    assert {item['side'] for item in analysis['poolRows']} == {'own', 'enemy'}
    assert {item['playerId'] for item in analysis['poolRows'] if item['side'] == 'own'} == {f'own{i}' for i in range(5)}
    # 上下文本队视角给红方 → 蓝方采集视角应报不一致，但不改写数据。
    analysis2 = capture_context.analyze(
        db, camp, batch={**batch, 'expectedOwnSide': 'red'},
        entries=[{'gameSeq': '101', 'accountId': 'acc-1'}])
    assert any('视角' in item['message'] for item in analysis2['warnings'])


def test_commit_and_final_series(tmp_path):
    db, ws, comp_id, batch, camp = _seed(tmp_path)
    analysis = capture_context.analyze(db, camp, batch=batch,
                                       entries=[{'gameSeq': seq} for seq in ('101', '102')])
    report = capture_context.commit(db, batch['id'], analysis)
    assert report['stamped'] == 2 and report['poolRows'] >= 10
    assert ws.get_capture_batch(batch['id'])['status'] == 'committed'
    assert len(ws.nickname_pool(side='own')) >= 5
    assert len(ws.nickname_pool(side='enemy')) >= 5
    assert 'camp:101' in ws.competition_scope_keys(comp_id)
    series = capture_context.group_series(db, batch['id'], ['camp:101', 'camp:102'], best_of=3)
    assert len(series['games']) == 2
    assert series['competitionId'] == comp_id


def test_nickname_pool_is_secondary_match(tmp_path):
    db, ws, comp_id, batch, camp = _seed(tmp_path)
    ws.upsert_nickname_entries([{'side': 'own', 'playerId': 'local-1', 'nickname': '采集昵称',
                                 'matchKey': 'camp:101', 'seenAt': '2026-11-05'}])
    assert ws.find_nickname_player('采集昵称', side='own') == 'local-1'
    assert ws.find_nickname_player('采集昵称', side='enemy') is None, '两侧昵称池不能串'
    analysis = capture_context.analyze(db, camp, batch=batch,
                                       entries=[{'gameSeq': '101', 'ownerName': '采集昵称'}])
    assert analysis['rows'][0]['playerId'] == 'local-1'
    assert analysis['rows'][0]['matchSource'] == 'nickname'


def test_sync_hook_creates_missing_record(tmp_path):
    db, ws, comp_id, batch, camp = _seed(tmp_path)
    saved = capture_context.stamp_synced_entries(
        db, competition_id=comp_id, own_team_id=batch['own_team_id'],
        opponent_team_id=batch['opponent_team_id'], match_type='training',
        entries=[{'gameSeq': '777', 'date': '2026-11-08', 'acntCamp': 1}])
    assert saved == 1
    assert 'camp:777' in ws.competition_scope_keys(comp_id)
    row = ws.connect().execute(
        "SELECT own_side, match_type FROM match_records WHERE match_key='camp:777'").fetchone()
    assert (row['own_side'], row['match_type']) == ('blue', 'training')


def test_capture_api(tmp_path):
    db, ws, comp_id, batch, camp = _seed(tmp_path)
    from studio_api import create_studio_router
    app = FastAPI()
    app.include_router(create_studio_router(db, tmp_path / 'matches', tmp_path / 'imports'))
    client = TestClient(app)
    created = client.post('/api/studio/workspace/capture-batches', json={
        'competitionId': comp_id, 'ownTeamId': batch['own_team_id'],
        'opponentTeamId': batch['opponent_team_id'], 'matchType': 'training'})
    assert created.status_code == 200, created.text
    bid = created.json()['id']
    analyzed = client.post(f'/api/studio/workspace/capture-batches/{bid}/analyze',
                           json={'entries': [{'gameSeq': '101'}]})
    assert analyzed.status_code == 200 and len(analyzed.json()['rows']) == 1
    committed = client.post(f'/api/studio/workspace/capture-batches/{bid}/commit',
                            json={'analysis': analyzed.json()})
    assert committed.status_code == 200 and committed.json()['stamped'] == 1
    assert client.get('/api/studio/workspace/nickname-pool',
                      params={'side': 'own'}).json()['rows']
    series = client.post(f'/api/studio/workspace/capture-batches/{bid}/series',
                         json={'matchKeys': ['camp:101'], 'bestOf': 3})
    assert series.status_code == 200, series.text
