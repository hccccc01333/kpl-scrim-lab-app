"""赛事域（M1）：统一 scope 口径 + 系列赛赛事归属。

全部使用隔离的临时工作区库（参照 tests/test_competition_match_filter.py 的 ws fixture），
不触碰项目 data/ 下的真实数据库。
"""
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from workspace_store import Workspace  # noqa: E402


@pytest.fixture()
def ws(tmp_path):
    store = Workspace(tmp_path / 'ws.sqlite3')
    store.ensure_schema()
    return store


def test_competition_scope_keys_covers_direct_window_manual_formal(ws):
    cid = ws.save_competition(name='春季赛', date='2026-11-01', end_date='2026-11-10',
                              key_match_keys=['m-manual'])
    other = ws.save_competition(name='夏季赛', date='2026-11-20')
    # 直连 / 归集窗口 / 手动挂载：训练赛口径的三个来源
    ws.upsert_match('m-direct', date='2026-11-02', competition_id=cid,
                    recorded_date='2026-11-02')
    ws.upsert_match('m-window', date='2026-11-05', recorded_date='2026-11-05')
    ws.upsert_match('m-manual', date='2026-12-01', recorded_date='2026-12-01')
    # 其他赛事直连（录入日期在夏季赛窗口内）、试训、正赛类型
    ws.upsert_match('m-other', date='2026-11-06', competition_id=other,
                    recorded_date='2026-11-21')
    ws.upsert_match('m-trial', date='2026-11-07', in_trial=1, recorded_date='2026-11-07')
    ws.upsert_match('m-formal', date='2026-11-03', match_type='formal')

    training = ws.competition_scope_keys(cid, kinds=('training',))
    assert training == {'m-direct', 'm-window', 'm-manual'}
    formal = ws.competition_scope_keys(cid, kinds=('formal',))
    assert formal == {'m-formal'}
    assert ws.competition_scope_keys(cid) == training | formal
    # 每个赛事只含自己的对局：试训排除，混不进别的赛事
    assert ws.competition_scope_keys(other) == {'m-other'}
    assert ws.competition_scope_keys('missing') == set()


def test_competition_start_only_window_covers_later_days(ws):
    """赛训组回归：赛事只填训练起始时间（结束留空）时，起始日之后的所有对局
    与系列赛都要落在 scope 内——此前 end_date 缺省被补成 start，窗口塌成单日，
    导致次日/第三天的营地采集对局在单局/大场/跨场里整批消失。"""
    cid = ws.save_competition(name='王者荣耀女子公开赛', date='2026-11-24')
    assert ws._collect_bounds(ws.get_competition(cid)) == ('2026-11-24', '')

    # 起始日 + 之后两天；全部按窗口归属本赛事
    for key, day in (('m-d1', '2026-11-24'), ('m-d2', '2026-11-25'), ('m-d3', '2026-11-26')):
        ws.upsert_match(key, date=day, recorded_date=day)
    scope = ws.competition_scope_keys(cid, kinds=('training',))
    assert scope == {'m-d1', 'm-d2', 'm-d3'}

    # 窗口解析到本赛事：编组后的系列赛也能归入（第二天开赛）
    assert ws._window_competition_for({'date': '2026-11-25'}) == cid
    ws.create_series(best_of=3, games=['m-d2'])
    assert [item['games'][0]['matchKey']
            for item in ws.list_series(competition=cid)] == ['m-d2']

    # 更早的对局不被吞并；直连其他赛事的仍不串味
    ws.upsert_match('m-old', date='2026-11-20', recorded_date='2026-11-20')
    other = ws.save_competition(name='下一赛事', date='2026-12-01')
    ws.upsert_match('m-other', date='2026-12-05', competition_id=other,
                    recorded_date='2026-12-05')
    scope = ws.competition_scope_keys(cid, kinds=('training',))
    assert 'm-old' not in scope
    assert 'm-other' not in scope


def test_series_competition_derive_and_mixed_error(ws):
    ws.upsert_match('m-a1', date='2026-11-02', competition_id='comp-a',
                    recorded_date='2026-11-02')
    ws.upsert_match('m-a2', date='2026-11-03', competition_id='comp-a',
                    recorded_date='2026-11-03')
    ws.upsert_match('m-b1', date='2026-11-04', competition_id='comp-b',
                    recorded_date='2026-11-04')

    # 归属自动取所选对局的直连赛事
    series = ws.create_series(best_of=3, games=['m-a1', 'm-a2'])
    assert series['competitionId'] == 'comp-a'

    # 混编（对局分属不同赛事）直接报错，不允许靠猜
    with pytest.raises(ValueError):
        ws.create_series(best_of=3, games=['m-a1', 'm-b1'])

    # 显式赛事与对局冲突
    with pytest.raises(ValueError):
        ws.create_series(best_of=3, games=['m-a1'], competition_id='comp-b')

    # 换局到 B 赛事：按新对局重新推导归属
    updated = ws.update_series(series['id'], games=['m-b1'])
    assert updated['competitionId'] == 'comp-b'


def test_series_list_filter_and_lazy_backfill(ws):
    ws.upsert_match('m-a1', date='2026-11-02', competition_id='comp-a',
                    recorded_date='2026-11-02')
    ws.upsert_match('m-b1', date='2026-11-04', competition_id='comp-b',
                    recorded_date='2026-11-04')
    ws.create_series(best_of=3, games=['m-a1'])
    ws.create_series(best_of=3, games=['m-b1'])

    assert [item['games'][0]['matchKey']
            for item in ws.list_series(competition='comp-a')] == ['m-a1']
    assert len(ws.list_series()) == 2

    # P2-1：GET 无写副作用——归属清空后 filtered 列表为空，
    # 回填由写路径（批量归属工具）完成
    with sqlite3.connect(ws.db_path) as connection:
        connection.execute('UPDATE training_series SET competition_id=NULL')
    assert ws.list_series(competition='comp-a') == []
    for item in ws.list_series():
        ws.bulk_assign_series([item['id']], 'comp-a' if
                              item['games'][0]['matchKey'] == 'm-a1' else 'comp-b')
    assert [item['games'][0]['matchKey']
            for item in ws.list_series(competition='comp-a')] == ['m-a1']


def test_competition_scope_no_cross_domain_swallow(ws):
    """P0 回归：直连归属 B 的对局，即使录入日期落在 A 的归集窗口内，
    也不得再进入 A 的 scope（窗口口径必须让位于直连归属）。"""
    a = ws.save_competition(name='A', date='2026-11-01', end_date='2026-11-30')
    b = ws.save_competition(name='B', date='2026-12-01', end_date='2026-12-31')
    # 训练赛：直连 B、日期在 A 窗口内
    ws.upsert_match('m-train-x', date='2026-11-15', competition_id=b,
                    recorded_date='2026-11-15')
    # 正赛：直连 B、比赛日期在 A 的 formal 窗口内
    ws.save_competition(name='A2', date='2026-11-01',
                        formal_from='2026-11-01', formal_to='2026-11-30')
    ws.upsert_match('m-formal-x', date='2026-11-20', competition_id=b,
                    match_type='formal')

    assert 'm-train-x' not in ws.competition_scope_keys(a, kinds=('training',))
    assert 'm-train-x' in ws.competition_scope_keys(b, kinds=('training',))
    assert 'm-formal-x' not in ws.competition_scope_keys(a, kinds=('formal',))
    assert 'm-formal-x' in ws.competition_scope_keys(b, kinds=('formal',))
    # 直连本赛事不受影响
    ws.upsert_match('m-a-direct', date='2026-11-16', competition_id=a,
                    recorded_date='2026-11-16')
    assert 'm-a-direct' in ws.competition_scope_keys(a, kinds=('training',))


def test_series_corpus_cache_keyed_by_competition(monkeypatch):
    """P0 回归：大场语料缓存键必须含赛事，A/B 请求不得互相串味。"""
    sys.path.insert(0, str(ROOT / 'v3'))
    import serve

    calls = []

    def fake_vectors(repo):
        calls.append(1)
        return [{'key': f'k-{len(calls)}'}]

    monkeypatch.setattr(serve, '_series_vectors', fake_vectors)
    serve._SERIES_CORPUS_CACHE.update(stamp=None, vectors=[])

    class Repo:
        pass

    v1 = serve._series_corpus(repo=Repo(), competition='comp-a')
    v2 = serve._series_corpus(repo=Repo(), competition='comp-b')
    v1b = serve._series_corpus(repo=Repo(), competition='comp-a')
    assert [item[0]['key'] for item in (v1, v2, v1b)] == ['k-1', 'k-2', 'k-1']
    assert len(calls) == 2  # 第三次命中缓存


def test_bundle_records_sync_and_competition_window(tmp_path, monkeypatch):
    """P1-5：语料包首次出现时补 match_records 登记（窗口口径自动归属）；
    P1-4：赛事窗口解析。"""
    sys.path.insert(0, str(ROOT / 'v3'))
    import serve

    store = Workspace(tmp_path / 'ws.sqlite3')
    store.ensure_schema()
    comp = store.save_competition(name='A', date='2026-11-01', end_date='2026-11-30')
    monkeypatch.setattr(serve, 'DB', tmp_path / 'ws.sqlite3')

    class FakeSnapshot:
        def get(self):
            return {'matches': [
                {'key': 'channel-new1', 'date': '2026-11-05'},
                {'key': 'channel-new2', 'date': '2026-12-20'},
                {'key': 'channel-new1', 'date': '2026-11-05'},  # 重复包不重复登记
            ]}

    serve._sync_bundle_records(FakeSnapshot())
    conn = store.connect()
    rows = {r[0]: r[1] for r in conn.execute(
        'SELECT match_key, competition_id FROM match_records')}
    conn.close()
    # 归属走窗口口径（查询时动态判定，不写死直连列）
    assert 'channel-new1' in store.competition_scope_keys(comp)
    assert 'channel-new2' not in store.competition_scope_keys(comp)
    assert rows['channel-new2'] is None
    # 幂等：重复登记不产生新行
    serve._sync_bundle_records(FakeSnapshot())
    conn = store.connect()
    count = conn.execute('SELECT COUNT(*) c FROM match_records').fetchone()[0]
    conn.close()
    assert count == 2
    # 窗口解析
    assert serve._competition_window(comp) == ('2026-11-01', '2026-11-30')
    assert serve._competition_window('missing') is None
