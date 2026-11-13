"""A8 经济转折 / A9 优势兑现：分桶、区间、阈值与缺失处理。"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import analysis_economy as ae  # noqa: E402


def make_game(tmp_path, seq, *, diff, duration=1200, win_camp='1', own_camp='1', events=None):
    replay = tmp_path / 'replays' / f'camp-{seq}'
    replay.mkdir(parents=True, exist_ok=True)
    (replay / 'normalized.json').write_text(json.dumps({
        'match': {'durationSec': duration, 'winCamp': win_camp, 'goldPoints': len(diff)},
        'economy': {'diff': diff},
        'events': {'key': events or []},
    }, ensure_ascii=False), encoding='utf-8')
    camp = tmp_path / 'camp_details'
    camp.mkdir(parents=True, exist_ok=True)
    (camp / f'{seq}.json').write_text(json.dumps({
        'data': {'head': {'acntCamp': int(own_camp), 'gameResult': True}}
    }, ensure_ascii=False), encoding='utf-8')


def test_load_games_pairs_panel_and_winner(tmp_path):
    make_game(tmp_path, '1', diff=[0, 100, 200])
    games = ae.load_games(tmp_path / 'replays', tmp_path / 'camp_details')
    assert len(games) == 1
    assert games[0]['ownCamp'] == 'blue'
    assert games[0]['win'] is True


def test_advantage_buckets_and_wilson(tmp_path):
    # 六个大优局全胜 + 一个落后局输
    for index in range(6):
        make_game(tmp_path, f'a{index}', diff=[0, 4000], win_camp='1', own_camp='1')
    make_game(tmp_path, 'b0', diff=[0, -4000], win_camp='2', own_camp='1')

    result = ae.advantage(tmp_path / 'replays', tmp_path / 'camp_details')
    buckets = {item['bucket']: item for item in result['buckets']}
    assert buckets['大优']['n'] == 6 and buckets['大优']['wins'] == 6
    assert buckets['落后']['n'] == 1 and buckets['落后']['wins'] == 0
    # Wilson 区间必须包含点估计且落在 0–100
    assert 0 <= buckets['大优']['ciLow'] <= 100
    assert buckets['大优']['ciLow'] <= buckets['大优']['winRate'] <= buckets['大优']['ciHigh']
    assert buckets['大优']['enough'] is False  # 6 < 10


def test_advantage_flips_red_side_perspective(tmp_path):
    # 我方红方，蓝方经济领先 = 我方落后
    make_game(tmp_path, '1', diff=[0, 6000], win_camp='1', own_camp='2')
    result = ae.advantage(tmp_path / 'replays', tmp_path / 'camp_details')
    assert result['rows'][0]['leadAt10'] < 0
    assert result['rows'][0]['bucket'] == '落后'


def test_turning_points_respects_threshold(tmp_path):
    make_game(tmp_path, '1', diff=[0, 100, 200, 300], duration=600)
    result = ae.turning_points(tmp_path / 'replays', tmp_path / 'camp_details', min_delta=1000)
    assert result['total'] == 0

    make_game(tmp_path, '2', diff=[0, 0, 5000, 5000], duration=600)
    result = ae.turning_points(tmp_path / 'replays', tmp_path / 'camp_details', min_delta=1000)
    assert result['total'] >= 1
    assert abs(result['rows'][0]['delta']) >= 1000


def test_missing_economy_is_skipped(tmp_path):
    replay = tmp_path / 'replays' / 'camp-9'
    replay.mkdir(parents=True)
    (replay / 'normalized.json').write_text(json.dumps({
        'match': {'durationSec': 600, 'winCamp': '1'},
        'economy': {'diff': []},
    }), encoding='utf-8')
    assert ae.load_games(tmp_path / 'replays', tmp_path / 'camp_details') == []
    assert ae.advantage(tmp_path / 'replays', tmp_path / 'camp_details')['games'] == 0

def test_value_at_clamps_short_games():
    """短于取值时刻的对局（8 分钟投降）不能越界，取终局值。"""
    diff = [value * 100 for value in range(17)]
    assert ae._value_at(600, diff, 480) == diff[-1]
    # 正常时长的插值保持不变
    assert ae._value_at(300, [0, 1000], 600) == 500


def test_short_games_do_not_enter_advantage_buckets(tmp_path):
    """8 分钟投降局没有十分钟采样点：不能把终局经济差当成十分钟经济差。"""
    make_game(tmp_path, 'short', diff=[0, 4000], duration=480, win_camp='1', own_camp='1')
    make_game(tmp_path, 'long', diff=[0, 4000], duration=1200, win_camp='1', own_camp='1')
    result = ae.advantage(tmp_path / 'replays', tmp_path / 'camp_details')
    assert result['usableGames'] == 1
    assert result['excludedShortGames'] == 1
    assert [row['game'] for row in result['rows']] == ['long']
    buckets = {item['bucket']: item for item in result['buckets']}
    assert buckets['大优']['n'] == 1
