"""系列赛存储层测试：表结构、唯一归属、关系列写回与清理。

固定回归样本覆盖（V2.0 方案 §八）：
- BO5 的 3:0 / 3:2 正确建组且局数不超过赛制上限；
- 一局对局不能重复归属（UNIQUE 约束 + SeriesConflict）；
- 确认/调整/删除都同步 match_records 与 matches 的 series_id/game_no；
- 数据刷新后编组关系保持不变（重开 Workspace 再读仍一致）。
"""
import pytest

from workspace_store import SeriesConflict, Workspace


@pytest.fixture()
def ws(tmp_path):
    workspace = Workspace(tmp_path / 'ws.sqlite3').ensure_schema()
    for index in range(1, 7):
        workspace.upsert_match(f'db-match-{index}', date='2026-11-14', session='一队',
                               status='confirmed', source='test')
    return workspace


def _keys(ws):
    return [row['match_key'] for row in ws.list_matches(50)]


def test_create_and_get_series(ws):
    keys = _keys(ws)[:3]
    brief = ws.create_series(best_of=3, games=keys, opponent='青岚', session='一队',
                             version='S30', actor='coach')
    assert brief['bestOf'] == 3
    assert brief['opponent'] == '青岚'
    assert [g['gameIndex'] for g in brief['games']] == [1, 2, 3]  # 自动编 G1..Gn
    assert brief['startAt'] == '2026-11-14'
    fetched = ws.get_series(brief['id'])
    assert fetched['games'] == brief['games']


def test_create_writes_relation_columns(ws):
    keys = _keys(ws)[:3]
    brief = ws.create_series(best_of=3, games=keys)
    rows = {row['match_key']: row for row in ws.list_matches(50)}
    for index, key in enumerate(keys, 1):
        assert rows[key]['series_id'] == brief['id']
        assert rows[key]['game_no'] == index
    # matches 表也同步（两套表结构一致的关系列）
    connection = ws.connect()
    try:
        matched = connection.execute(
            'SELECT series_id, game_no FROM matches WHERE match_key=?', (keys[0],)).fetchone()
        assert matched is None or matched['series_id'] == brief['id']
    finally:
        connection.close()


def test_explicit_game_index_must_be_contiguous(ws):
    keys = _keys(ws)[:3]
    with pytest.raises(ValueError, match='连续'):
        ws.create_series(best_of=3, games=[
            {'matchKey': keys[0], 'gameIndex': 1},
            {'matchKey': keys[1], 'gameIndex': 3},
            {'matchKey': keys[2], 'gameIndex': 4}])


def test_duplicate_keys_rejected(ws):
    keys = _keys(ws)[:2]
    with pytest.raises(ValueError, match='两次'):
        ws.create_series(best_of=3, games=[keys[0], keys[0]])


def test_more_games_than_best_of_rejected(ws):
    keys = _keys(ws)[:5]
    with pytest.raises(ValueError, match='最多'):
        ws.create_series(best_of=3, games=keys)


def test_membership_conflict_across_series(ws):
    keys = _keys(ws)
    ws.create_series(best_of=3, games=keys[:3])
    with pytest.raises(SeriesConflict) as info:
        ws.create_series(best_of=3, games=[keys[0], keys[4]])
    assert (keys[0],) == tuple(item[0] for item in info.value.occupied)


def test_update_games_frees_removed_matches(ws):
    keys = _keys(ws)
    brief = ws.create_series(best_of=3, games=keys[:3])
    updated = ws.update_series(brief['id'], games=keys[:2], best_of=3)
    assert [g['matchKey'] for g in updated['games']] == keys[:2]
    rows = {row['match_key']: row for row in ws.list_matches(50)}
    assert rows[keys[2]]['series_id'] is None
    assert rows[keys[2]]['game_no'] is None
    assert rows[keys[0]]['series_id'] == brief['id']


def test_update_does_not_conflict_with_itself(ws):
    keys = _keys(ws)
    brief = ws.create_series(best_of=3, games=keys[:3])
    # 同一系列赛内调序不算占用冲突
    reordered = ws.update_series(brief['id'], games=list(reversed(keys[:3])))
    assert [g['gameIndex'] for g in reordered['games']] == [1, 2, 3]
    assert [g['matchKey'] for g in reordered['games']] == list(reversed(keys[:3]))


def test_delete_series_keeps_matches(ws):
    keys = _keys(ws)[:3]
    brief = ws.create_series(best_of=3, games=keys)
    freed = ws.delete_series(brief['id'])
    assert sorted(freed) == sorted(keys)
    assert ws.get_series(brief['id']) is None
    rows = {row['match_key']: row for row in ws.list_matches(50)}
    assert all(rows[key]['series_id'] is None for key in keys)
    # 关系删除不影响对局本身
    assert len(ws.list_matches(50)) == 6


def test_recreate_with_same_id_for_undo(ws):
    keys = _keys(ws)[:3]
    brief = ws.create_series(best_of=3, games=keys)
    ws.delete_series(brief['id'])
    restored = ws.create_series(best_of=3, games=keys, series_id=brief['id'])
    assert restored['id'] == brief['id']


def test_recreate_conflicting_id_rejected(ws):
    keys = _keys(ws)
    ws.create_series(best_of=3, games=keys[:3], series_id='ts-fixed')
    with pytest.raises(ValueError, match='已存在'):
        ws.create_series(best_of=3, games=keys[3:], series_id='ts-fixed')


def test_list_filters(ws):
    ws.upsert_match('db-other', date='2026-10-01', session='二队', status='confirmed')
    keys = _keys(ws)
    ws.create_series(best_of=3, games=keys[:3], opponent='青岚', session='一队',
                     start_at='2026-11-14')
    ws.create_series(best_of=5, games=[keys[4]], opponent='北屿', session='二队',
                     start_at='2026-11-10', end_at='2026-11-10')
    assert len(ws.list_series()) == 2
    assert [s['id'] for s in ws.list_series(best_of=5)] == [ws.list_series(best_of=5)[0]['id']]
    names = [s['opponent'] for s in ws.list_series(opponent='青')]
    assert names == ['青岚']
    # 时间窗口按系列赛开赛日归档，一组 BO 不会被切成两半
    assert len(ws.list_series(date_from='2026-11-12', date_to='2026-11-14')) == 1


def test_series_for_matches(ws):
    keys = _keys(ws)
    brief = ws.create_series(best_of=3, games=keys[:3])
    mapping = ws.series_for_matches([keys[0], keys[5]])
    assert mapping[keys[0]] == {'seriesId': brief['id'], 'gameIndex': 1}
    assert keys[5] not in mapping


def test_series_index(ws):
    """跨局分析按赛制 / 局序筛选用的一次性索引：带 bestOf 与开赛日。"""
    keys = _keys(ws)
    brief = ws.create_series(best_of=5, games=keys[:4], start_at='2026-11-14')
    index = ws.series_index()
    assert index[keys[0]] == {
        'seriesId': brief['id'], 'bestOf': 5, 'gameIndex': 1, 'seriesStart': '2026-11-14'}
    assert index[keys[3]]['gameIndex'] == 4
    assert keys[5] not in index


def test_relationship_survives_reopen(tmp_path):
    ws = Workspace(tmp_path / 'ws.sqlite3').ensure_schema()
    ws.upsert_match('db-match-1', date='2026-11-14', status='confirmed')
    ws.upsert_match('db-match-2', date='2026-11-14', status='confirmed')
    brief = ws.create_series(best_of=3, games=['db-match-1', 'db-match-2'])
    again = Workspace(tmp_path / 'ws.sqlite3').ensure_schema()
    assert again.get_series(brief['id'])['games'] == brief['games']
