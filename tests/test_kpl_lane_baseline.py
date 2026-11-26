"""KPL 同位置基线：官方逐人终局字段的聚合口径。"""
import pytest

import kpl_bp


def player(position, hero, stats=None):
    row = {'position': position, 'hero': hero, 'player': hero}
    if stats is not None:
        row['stats'] = stats
    return row


def game(battle_id, league, win_camp, duration_ms, players):
    return {'battleId': battle_id, 'leagueName': league, 'winCamp': win_camp,
            'durationMs': duration_ms, 'players': players}


def test_build_lane_baseline_averages_stats_and_samples():
    games = [
        game('g1', '2026 KPL', 1, 600000, {
            '1': [player('游走', '孙膑', {'kills': 1, 'deaths': 2, 'assists': 5,
                                        'participation': 80, 'gold': 6000, 'damage': 3000,
                                        'heroDamage': 2000, 'taken': 1000})],
            '2': [player('游走', '蔡文姬', {'kills': 2, 'deaths': 1, 'assists': 3,
                                        'participation': 60, 'gold': 5000, 'damage': 2000,
                                        'heroDamage': 1000, 'taken': 2000})],
        }),
        game('g2', '2026 KPL', 2, 720000, {
            '1': [player('游走', '大乔', {'kills': 0, 'deaths': 0, 'assists': 2,
                                        'participation': 90, 'gold': 7000, 'damage': 3500,
                                        'heroDamage': 2500, 'taken': 1200})],
            '2': [player('游走', '张飞')],
        }),
    ]
    external = {'孙膑': {'winRate': 60}, '蔡文姬': {'winRate': 55},
                '大乔': {'winRate': 70}, '张飞': {'winRate': 65}}
    doc = kpl_bp.build_lane_baseline(games, external, {})
    cell = doc['lanes']['游走']

    assert doc['games'] == 2
    assert cell['games'] == 4 and cell['wins'] == 2
    assert cell['winRate'] == 50
    assert cell['heroWinRate'] == 62.5
    assert cell['samples']['winRate'] == 4
    assert cell['samples']['heroWinRate'] == 4
    assert cell['samples']['kda'] == 3
    assert cell['kda'] == pytest.approx(3.33)
    assert cell['participation'] == pytest.approx(76.67)
    assert cell['assists'] == pytest.approx(3.33)
    assert cell['gpm'] == pytest.approx(561.11)
    assert cell['dpm'] == pytest.approx(263.89)
    assert cell['hdpm'] == pytest.approx(169.44)
    assert cell['dtpm'] == pytest.approx(133.33)
    assert cell['taken'] == pytest.approx(1400)
    assert doc['fields'] == list(kpl_bp.BASELINE_FIELDS)


def test_build_lane_baseline_filters_league_and_keeps_old_rows_compatible():
    old = game('old', '2025 KPL', 1, None, {
        '1': [player('游走', '孙膑')], '2': [player('游走', '蔡文姬')],
    })
    new = game('new', '2026 KPL', 1, 600000, {
        '1': [player('游走', '大乔', {'assists': 8, 'taken': 900})],
        '2': [player('游走', '张飞', {'assists': 4, 'taken': 1100})],
    })
    doc = kpl_bp.build_lane_baseline([old, new], {}, {}, '2025 KPL')
    cell = doc['lanes']['游走']
    assert doc['games'] == 1 and cell['games'] == 2
    assert doc['fields'] == ['winRate']
    assert cell['assists'] is None and cell['dtpm'] is None
    assert cell['samples']['assists'] == 0 and cell['samples']['dtpm'] == 0

    missing = kpl_bp.build_lane_baseline([old, new], {}, {}, '不存在的赛事')
    assert missing['games'] == 0 and missing['lanes'] == {}
    assert [row['name'] for row in missing['leagues']] == ['2025 KPL', '2026 KPL']


def test_build_lane_baseline_splits_jungle_and_skips_unknown_positions():
    rows = {
        '1': [player('打野', '阿古朵'), player('未知', '铠')],
        '2': [player('打野', '铠')],
    }
    tags = {'阿古朵': {'lanes': {'打野': '坦野'}}, '铠': {'lanes': {'打野': '野核'}}}
    doc = kpl_bp.build_lane_baseline([game('g', '2026 KPL', 1, 600000, rows)], {}, tags)
    assert set(doc['lanes']) == {'打野·坦野', '打野·野核'}
    assert doc['lanes']['打野·坦野']['games'] == 1
    assert doc['lanes']['打野·野核']['games'] == 1
