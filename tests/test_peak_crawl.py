"""peak_crawl 的纯逻辑：分片按 ts 取最新、双方向合成一条对位、lane 文档结构。"""
import json

import peak_crawl
from scripts.build_bp_facts import MIN_PICK_RATE, build_lane_rows, build_ladder_doc


def _hero_stats(pick=MIN_PICK_RATE + 0.1):
    """两个够门槛的英雄基准（wr 相同 → 期望胜率 50%）。"""
    return {
        1: {'name': '英雄甲', 'wr': 0.50, 'pick': pick},
        2: {'name': '英雄乙', 'wr': 0.50, 'pick': pick},
    }


def test_latest_matchup_rows_prefers_new_ts(tmp_path, monkeypatch):
    """同一有序对位在基线分片和新一轮分片各有一条：取 ts 新的。"""
    match_dir = tmp_path / 'matchup_raw'
    match_dir.mkdir()
    (match_dir / 'matchups_baseline.jsonl').write_text(json.dumps(
        {'cid': 1, 'blue_id': 1, 'red_id': 2, 'n': 100, 'blue_win_rate': 48.0,
         'status': 'ok', 'ts': '2026-11-09T00:00:00'}), encoding='utf-8')
    (match_dir / 'matchups_20261113-0900.jsonl').write_text(json.dumps(
        {'cid': 1, 'blue_id': 1, 'red_id': 2, 'n': 120, 'blue_win_rate': 52.0,
         'status': 'ok', 'ts': '2026-11-13T09:00:00'}), encoding='utf-8')
    monkeypatch.setattr(peak_crawl, 'MATCHUP_DIR', match_dir)
    rows = peak_crawl._latest_matchup_rows(log=lambda *_: None)
    assert len(rows) == 1
    assert rows[0]['n'] == 120 and rows[0]['blue_win_rate'] == 52.0


def test_build_lane_rows_combines_both_directions():
    """甲→乙 与 乙→甲 两条对位合成一条无序对位（双方胜率共享）。"""
    rows = [
        {'blue_id': 1, 'red_id': 2, 'n': 800, 'blue_win_rate': 50.0, 'status': 'ok'},
        {'blue_id': 2, 'red_id': 1, 'n': 400, 'blue_win_rate': 60.0, 'status': 'ok'},
    ]
    pairs = build_lane_rows(rows, _hero_stats())
    assert len(pairs) == 1
    row = pairs[0]
    assert (row['a'], row['b']) == ('英雄甲', '英雄乙')
    assert row['n'] == 1200
    # 甲的合并胜率：(800×0.5 + 400×(1−0.6)) / 1200 = 560/1200 ≈ 46.7%
    assert row['wr'] == 46.7
    assert row['expected'] == 50.0
    assert row['excess'] == -3.3


def test_build_lane_rows_drops_thin_and_rare():
    """样本 < 200 局或使用率 < 3% 的对位不进表。"""
    rows = [
        {'blue_id': 1, 'red_id': 2, 'n': 150, 'blue_win_rate': 55.0, 'status': 'ok'},
        {'blue_id': 1, 'red_id': 2, 'n': 300, 'blue_win_rate': 55.0, 'status': 'ok'},
        {'blue_id': 1, 'red_id': 2, 'n': 300, 'blue_win_rate': 55.0,
         'status': 'error'},  # 失败行丢弃
    ]
    thin = build_lane_rows(rows[:1], _hero_stats())
    assert thin == []
    ok = build_lane_rows(rows[1:2], _hero_stats())
    assert len(ok) == 1
    rare = build_lane_rows(rows[1:2], _hero_stats(pick=MIN_PICK_RATE - 0.01))
    assert rare == []


def test_build_ladder_doc_shape():
    rows = build_lane_rows(
        [{'blue_id': 1, 'red_id': 2, 'n': 3200, 'blue_win_rate': 54.0, 'status': 'ok'}],
        _hero_stats())
    doc = build_ladder_doc(rows, _hero_stats(), '2026-11-13')
    assert doc['schema'] == 'bp-lane-facts-v1'
    assert doc['bracket'] == '巅峰千强'
    assert doc['windowEnd'] == '2026-11-13'
    assert doc['minN'] == 200 and doc['minPickRate'] == 0.03
    assert len(doc['pairs']) == 1
    assert set(doc['heroes']) == {'英雄甲', '英雄乙'}


def test_state_roundtrip_and_staleness(tmp_path, monkeypatch):
    """状态文件可写可读；今天没刷过 → 不新鲜。"""
    monkeypatch.setattr(peak_crawl, 'PEAK_DIR', tmp_path)
    monkeypatch.setattr(peak_crawl, 'STATE_PATH', tmp_path / 'state.json')
    monkeypatch.setattr(peak_crawl, 'FACTS_PATH', tmp_path / 'lane_matchups.json')
    monkeypatch.setattr(peak_crawl, '_state', dict(peak_crawl._state))
    (tmp_path / 'lane_matchups.json').write_text(
        json.dumps({'pairs': [1, 2, 3]}), encoding='utf-8')
    assert peak_crawl._is_fresh() is False        # finishedAt 为空
    peak_crawl._state['finishedAt'] = '2020-01-01T08:00:00'
    assert peak_crawl._is_fresh() is False        # 是别天刷的
    peak_crawl._save_state()
    assert json.loads((tmp_path / 'state.json').read_text(encoding='utf-8'))['finishedAt'] \
        == '2020-01-01T08:00:00'
