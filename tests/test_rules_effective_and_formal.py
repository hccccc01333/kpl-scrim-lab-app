"""赛事域 M2/M3：规则按赛事 effective、正赛录入、批量归属、等级映射。

全部使用隔离的临时工作区库，不触碰项目 data/ 下的真实数据库。
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import rules_effective  # noqa: E402
import tiers  # noqa: E402
from workspace_store import Workspace  # noqa: E402


@pytest.fixture()
def ws(tmp_path):
    store = Workspace(tmp_path / 'ws.sqlite3')
    store.ensure_schema()
    return store


def test_rules_effective_filters_by_competition():
    comp = {'id': 'comp-1', 'name': '春季赛', 'date': '2026-11-01', 'end_date': '2026-12-01'}
    doc = {'heroPairs': [
        {'id': 'p1', 'a': '张飞', 'b': '貂蝉'},
        {'id': 'p2', 'a': '张飞', 'b': '王昭君', 'effective': {'eventId': 'comp-1'}},
        {'id': 'p3', 'a': '张飞', 'b': '武则天', 'effective': {'eventName': '夏季赛'}},
        {'id': 'p4', 'a': '张飞', 'b': '上官婉儿',
         'effective': {'from': '2026-10-15', 'to': '2026-12-15'}},
        {'id': 'p5', 'a': '张飞', 'b': '不知火舞', 'effective': {'eventId': 'comp-2'}},
    ], 'comboPairs': [
        {'id': 'c1', 'a': '张飞+貂蝉', 'b': '太乙+鲁班', 'sub': 'combo',
         'effective': {'from': '2026-10-01', 'to': '2026-10-31'}},
    ]}
    out = rules_effective.resolve_doc('counters', doc, comp)
    assert [row['id'] for row in out['heroPairs']] == ['p1', 'p2', 'p4']
    assert [row['id'] for row in out['comboPairs']] == []
    assert out['effectiveMeta']['matched'] == 3 and out['effectiveMeta']['skipped'] == 3
    # 全局口径（未选赛事）= 全量
    out_all = rules_effective.resolve_doc('counters', doc, None)
    assert len(out_all['heroPairs']) == 5 and len(out_all['comboPairs']) == 1


def test_formal_match_result_level(ws):
    comp = ws.save_competition(name='春季赛', date='2026-11-01',
                               formal_from='2026-11-01', formal_to='2026-12-01')
    out = ws.save_formal_match(date='2026-11-10', opponent='星辰', score='3:1', winner='blue')
    assert out['dedup'] is False and out['depth'] == 'result' and out['competitionId'] == comp
    row = ws.competition_formal_matches(comp)[0]
    assert row['match_type'] == 'formal' and row['enemy_team_id']
    # 去重：同对手 + 同日期 + 同比分 → 返回已有对局（营地同步优先）
    again = ws.save_formal_match(date='2026-11-10', opponent='星辰', score='3:1')
    assert again['dedup'] is True and again['matchKey'] == out['matchKey']


def test_formal_match_lineup_level(ws):
    comp = ws.save_competition(name='春季赛', date='2026-11-01')
    lineup = ['我方,对抗路,张飞', '对方,中路,貂蝉']
    out = ws.save_formal_match(date='2026-11-12', opponent='星河', score='1:3',
                               winner='red', lineup=lineup, competition_id=comp)
    assert out['depth'] == 'lineup'
    row = ws.competition_formal_matches(comp)[0]
    payload = json.loads(row.get('notes') or '{}')
    assert payload['formalEntry']['depth'] == 'lineup'
    assert len(payload['formalEntry']['lineup']) == 2


def test_formal_match_without_window_fails(ws):
    with pytest.raises(ValueError):
        ws.save_formal_match(date='2026-11-10', opponent='孤赛')


def test_bulk_assign_series(ws):
    ws.upsert_match('m-1', date='2026-11-02', recorded_date='2026-11-02')
    ws.upsert_match('m-2', date='2026-11-03', recorded_date='2026-11-03')
    s1 = ws.create_series(best_of=3, games=['m-1'])
    s2 = ws.create_series(best_of=3, games=['m-2'])
    comp = ws.save_competition(name='春季赛', date='2026-11-01', end_date='2026-11-30')
    unfiled = [item['id'] for item in ws.unfiled_series()]
    assert s1['id'] in unfiled and s2['id'] in unfiled
    report = ws.bulk_assign_series([s1['id'], s2['id']], comp)
    assert report == {'assigned': [s1['id'], s2['id']], 'failed': []}
    assert ws.get_series(s1['id'])['competitionId'] == comp
    assert ws.unfiled_series() == []


def test_tiers_capabilities_and_thresholds():
    assert tiers.capabilities('KPL')['formalSync'] is True
    assert tiers.capabilities('女子联赛')['factsApplies'] == 'meta-only'
    assert tiers.capabilities('未知')['factsApplies'] == 'reference'
    assert tiers.threshold_for('KPL') == 20


def test_formal_match_bp_level_and_order_pending(tmp_path):
    """BP 顺序级：写入 bp_overrides，orderPending 复用采集口径（不满 5 人只标不伪造）。"""
    import sqlite3

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from studio_api import create_studio_router

    store = Workspace(tmp_path / 'ws.sqlite3')
    store.ensure_schema()
    comp = store.save_competition(name='春季赛', date='2026-11-01')
    (tmp_path / 'matches').mkdir(exist_ok=True)
    (tmp_path / 'imports').mkdir(exist_ok=True)
    app = FastAPI()
    app.include_router(create_studio_router(
        tmp_path / 'ws.sqlite3', tmp_path / 'matches', tmp_path / 'imports',
        tmp_path / 'studio.sqlite3'))
    client = TestClient(app)

    full = {'date': '2026-11-10', 'opponent': '星辰', 'score': '3:1',
            'competitionId': comp, 'ownSide': 'blue',
            'bp': {'bans': {'left': ['张飞'], 'right': ['貂蝉']},
                   'picks': {'left': ['英雄A', '英雄B', '英雄C', '英雄D', '英雄E'],
                             'right': ['英雄F', '英雄G', '英雄H', '英雄I', '英雄J']}}}
    saved = client.post('/api/studio/workspace/formal-matches', json=full).json()
    assert saved['bpSaved'] is True and saved['orderPending'] is False
    assert saved['depth'] == 'bp'
    with sqlite3.connect(tmp_path / 'ws.sqlite3') as connection:
        body = json.loads(connection.execute(
            'SELECT body FROM bp_overrides WHERE match_key=?',
            (saved['matchKey'],)).fetchone()[0])
    assert body['orderPending'] is False and len(body['picks']['left']) == 5

    partial = dict(full, date='2026-11-11', opponent='星河', score='1:3',
                   bp={'bans': {'left': [], 'right': []}, 'picks': {'left': ['英雄A'], 'right': []}})
    saved2 = client.post('/api/studio/workspace/formal-matches', json=partial).json()
    assert saved2['bpSaved'] is True and saved2['orderPending'] is True

    echo = client.get(f"/api/studio/workspace/formal-bp/{saved['matchKey']}")
    assert echo.status_code == 200 and echo.json()['bp']['orderPending'] is False


def test_unlocks_compute_thresholds(tmp_path):
    """解锁 v2：大场/跨场都以「1 个已确认系列」为门槛，语料阈值只用于分析置信度。"""
    import unlocks as unlocks_mod
    store = Workspace(tmp_path / 'ws.sqlite3')
    store.ensure_schema()
    # 未选赛事：全部锁 + 引导先选赛事
    none_state = unlocks_mod.compute(store, tmp_path / 'ws.sqlite3', None)
    assert none_state['routes']['biggame']['unlocked'] is False
    assert none_state['routes']['biggame']['cta'] == [['#competitions', '去选赛事']]
    # 有已确认系列：大场与跨场同时解锁（与上手引导口径一致）
    store.upsert_match('m-1', date='2026-11-02', recorded_date='2026-11-02')
    s1 = store.create_series(best_of=3, games=['m-1'], competition_id='comp-a')
    state = unlocks_mod.compute(store, tmp_path / 'ws.sqlite3', 'comp-a')
    assert state['routes']['biggame']['unlocked'] is True
    assert state['routes']['cross']['unlocked'] is True
    assert state['routes']['cross']['need'] == 1
    assert state['routes']['cross']['n'] == 1


def test_competition_lifecycle_archived_readonly(ws):
    """P2-2：archived 只读——重开（改回 planned/ongoing）才放行编辑。"""
    comp = ws.save_competition(name='春季赛', date='2026-11-01', status='ongoing')
    ws.save_competition(comp, name='春季赛', date='2026-11-01', status='archived')
    assert ws.get_competition(comp)['status'] == 'archived'
    with pytest.raises(ValueError):
        ws.save_competition(comp, name='春季赛', date='2026-11-01', notes='改备注')
    # 重开放行
    ws.save_competition(comp, name='春季赛', date='2026-11-01', status='ongoing')
    assert ws.get_competition(comp)['status'] == 'ongoing'
    ws.save_competition(comp, name='春季赛·改', date='2026-11-01')
    assert ws.get_competition(comp)['name'] == '春季赛·改'


def test_formal_entry_linking_and_scope_exclusion(tmp_path):
    """双通道统一：速记占位在 official-entry 正赛包转正时链接让位，
    scope 不再双计；待补全列表只出未转正的占位。"""
    store = Workspace(tmp_path / 'ws.sqlite3')
    store.ensure_schema()
    comp = store.save_competition(name='春季赛', date='2026-11-01', end_date='2026-11-30')
    entry = store.save_formal_match(date='2026-11-10', opponent='星辰', score='2:0',
                                    competition_id=comp, winner='blue')
    assert store.pending_formal_entries()[0]['match_key'] == entry['matchKey']
    # 正牌对局（bundle/channel）登记后转正
    store.upsert_match('channel-abc', date='2026-11-10', recorded_date='2026-11-10',
                       match_type='formal', source='official-entry')
    linked = store.link_formal_entry(entry['matchKey'], 'channel-abc')
    assert linked is True
    conn = store.connect()
    link = conn.execute('SELECT formal_link FROM match_records WHERE match_key=?',
                        (entry['matchKey'],)).fetchone()[0]
    conn.close()
    assert link == 'channel-abc'
    # scope：占位让位，正牌对局按窗口/直连进入
    scope = store.competition_scope_keys(comp, kinds=('formal',))
    assert 'channel-abc' in scope and entry['matchKey'] not in scope
    # 待补全列表不再出已转正的占位
    assert store.pending_formal_entries() == []
    # 重复转正被拒绝
    assert store.link_formal_entry(entry['matchKey'], 'channel-abc') is False


def test_opponent_cross_event_endpoint(tmp_path):
    """跨赛事档案：对手交手时间线按赛事分组，不受当前赛事隔离。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from studio_api import create_studio_router

    ws = Workspace(tmp_path / 'ws.sqlite3')
    ws.ensure_schema()
    ca = ws.save_competition(name='赛事A', date='2026-11-01')
    cb = ws.save_competition(name='赛事B', date='2026-12-01')
    team = ws.upsert_team(name='老对手')
    ws.upsert_match('m-1', date='2026-11-05', competition_id=ca,
                    enemy_team_id=team, own_side='blue', winner='blue')
    ws.upsert_match('m-2', date='2026-12-10', competition_id=cb,
                    enemy_team_id=team, own_side='red', winner='red')

    (tmp_path / 'matches').mkdir(exist_ok=True)
    (tmp_path / 'imports').mkdir(exist_ok=True)
    app = FastAPI()
    app.include_router(create_studio_router(
        tmp_path / 'ws.sqlite3', tmp_path / 'matches', tmp_path / 'imports',
        tmp_path / 'studio.sqlite3'))
    client = TestClient(app)

    response = client.get(f"/api/studio/workspace/opponents/{team}/cross-event")
    assert response.status_code == 200
    body = response.json()
    assert body['team']['id'] == team
    assert len(body['timeline']) == 2
    by_comp = {item['competitionId']: item for item in body['timeline']}
    assert by_comp[ca]['wins'] == 1
    assert by_comp[cb]['wins'] == 1  # winner=red 且 own_side=red → 我方胜
    assert client.get('/api/studio/workspace/opponents/nope/cross-event').status_code == 404
