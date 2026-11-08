"""B1 对手画像 / B3 训练效果：胜场去重、样本门槛、前后切分。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import analysis_profile as ap  # noqa: E402


def row(seq, *, side='enemy', won=False, date='2026-11-02', player='p1', hero='瑶',
        lane='游走', kda=(3, 2, 6), gold=700, minutes=15, hero_damage=60000, taken=40000,
        participation=0.6):
    kills, deaths, assists = kda
    return {'seq': seq, 'date': date, 'camp': 'red', 'side': side,
            'playerId': player, 'name': player, 'lane': lane, 'hero': hero,
            'minutes': minutes, 'kills': kills, 'deaths': deaths, 'assists': assists,
            'gold': gold, 'damage': hero_damage, 'heroDamage': hero_damage, 'taken': taken,
            'participation': participation, 'won': won}


def test_opponent_profiles_counts_games_not_rows():
    # 一局 5 名对手选手，全部 won=True，只应算 1 个胜场
    games = [row('1', player=f'p{i}', won=True) for i in range(5)]
    games += [row('2', player=f'p{i}', won=False) for i in range(5)]
    games += [row('3', player=f'p{i}', won=True) for i in range(5)]
    result = ap.opponent_profiles(games, [{'id': 't1', 'name': '青岚', 'rows': games}], min_games=3)
    profile = result['profiles'][0]
    assert profile['available'] is True
    assert profile['games'] == 3
    assert profile['wins'] == 2
    assert profile['winRate'] == 66.7


def test_opponent_profiles_reports_missing_sample():
    games = [row('1'), row('2')]
    result = ap.opponent_profiles(games, [{'id': 't1', 'name': '赤霄', 'rows': games}], min_games=3)
    profile = result['profiles'][0]
    assert profile['available'] is False
    assert '样本不足' in profile['reason']


def test_training_effect_splits_by_date():
    rows = [row(str(i), won=True, date='2026-11-01', gold=600) for i in range(6)]
    rows += [row(str(10 + i), won=True, date='2026-11-05', gold=900) for i in range(6)]
    training = {'metric': 'gpm', 'start_date': '2026-11-03', 'end_date': '2026-11-04',
                'player_ids': [], 'target': 50}
    effect = ap.training_effect(rows, training)
    assert effect['available'] is True
    assert effect['nPre'] == 6 and effect['nPost'] == 6
    assert effect['preMean'] == 40.0 and effect['postMean'] == 60.0
    assert effect['delta'] == 20.0
    assert effect['targetRate'] == 100.0


def test_training_effect_refuses_small_sample():
    rows = [row(str(i), gold=600) for i in range(2)]
    training = {'metric': 'gpm', 'start_date': '2026-11-03', 'end_date': '2026-11-04',
                'player_ids': [], 'target': 800}
    effect = ap.training_effect(rows, training)
    assert effect['available'] is False
    assert '样本不足' in effect['reason']


def test_training_effect_rejects_unknown_metric():
    effect = ap.training_effect([row('1')], {'metric': '不存在', 'start_date': '2026-11-01'})
    assert effect['available'] is False
    assert '不支持' in effect['reason']
