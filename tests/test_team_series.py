"""演示系列赛 BO 演变分析：全局 BP 跨局禁复用、调整检测与剩余体系口径。"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import team_clusters  # noqa: E402
from tests.test_team_deep import team_id_of, three_games  # noqa: E402


def test_series_analysis_tracks_global_bp_and_adjust(tmp_path):
    camp = tmp_path / 'camp_details'
    three_games(camp)
    db = tmp_path / 'db.sqlite3'
    team_id = team_id_of(camp, db)
    deep = team_clusters.team_deep(camp, db, team_id)

    defs = [{'seriesId': 's1', 'bo': 'BO3', 'teamId': team_id, 'label': '演示 BO3',
             'games': [{'gameNo': 1, 'seq': '1'}, {'gameNo': 2, 'seq': '2'},
                       {'gameNo': 3, 'seq': '3'}]}]
    out = team_clusters.series_analysis(deep['games'], defs)

    assert len(out) == 1
    s = out[0]
    assert s['seriesId'] == 's1' and s['bo'] == 'BO3' and s['demo'] is True
    assert s['rule']['id'] == 'draft-18' and s['rule']['slots'] == 18
    assert s['score'] == {'wins': 2, 'losses': 1}
    # 全局 BP：fixture 三局同一对手阵容 → 新启用仅 G1，已用恒 5
    assert len(s['games'][0]['newHeroes']) == 5
    assert s['games'][1]['newHeroes'] == [] and s['games'][2]['newHeroes'] == []
    assert s['games'][0]['usedCount'] == 5 and s['games'][2]['usedCount'] == 5
    # 调整检测：同阵容 → 同体系；上下文按上一局胜负
    assert s['games'][0]['adjust'] is None and s['games'][0]['adjustContext'] is None
    assert s['games'][1]['adjust'] == '同体系' and s['games'][1]['adjustContext'] == '赢后'
    assert s['games'][2]['adjust'] == '同体系' and s['games'][2]['adjustContext'] == '赢后'
    # 剩余可组体系恒为正（演示口径下可读的组合上限）
    assert all(g['legalCombos'] > 0 for g in s['games'])


def test_series_analysis_skips_missing_and_unmatched(tmp_path):
    camp = tmp_path / 'camp_details'
    three_games(camp)
    db = tmp_path / 'db.sqlite3'
    team_id = team_id_of(camp, db)
    deep = team_clusters.team_deep(camp, db, team_id)

    # 引用不存在的 seq → 整个系列跳过
    out = team_clusters.series_analysis(
        deep['games'],
        [{'seriesId': 's1', 'bo': 'BO3', 'teamId': team_id,
          'games': [{'gameNo': 1, 'seq': '99999'}]}])
    assert out == []
    # 属于其他战队的 seq 不进本队分析
    out = team_clusters.series_analysis(
        [],
        [{'seriesId': 's2', 'bo': 'BO5', 'teamId': team_id,
          'games': [{'gameNo': 1, 'seq': '1'}]}])
    assert out == []


def test_load_demo_series_defaults_and_missing():
    series = team_clusters.load_demo_series()
    if not series:
        # data/facts/demo_series.json 由私有数据生成，公开仓库不带。
        pytest.skip('演示系列赛定义不在公开仓库（data/ 不入库）')
    assert all(s.get('seriesId') and s.get('teamId') and s.get('games') for s in series)
    assert all(s.get('bo') in ('BO3', 'BO5', 'BO7') for s in series)
    # 缺文件返回空，不抛错
    assert team_clusters.load_demo_series('Z:/not-exist/demo.json') == []
