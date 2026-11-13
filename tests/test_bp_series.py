"""BO5/BO7 全局 BP 规划：规则引擎与搜索骨架。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bp_series as bs  # noqa: E402


def test_peak_duel_and_available():
    assert bs.is_peak_duel(5, 5) is True
    assert bs.is_peak_duel(4, 5) is False
    # 非巅峰：剔除已用
    assert bs.available_heroes(['a', 'b', 'c'], {'a'}, game_seq=2, max_games=5) == ['b', 'c']
    # 巅峰：解禁
    assert bs.available_heroes(['a', 'b', 'c'], {'a'}, game_seq=5, max_games=5) == ['a', 'b', 'c']


def test_terminal_and_wins_needed():
    assert bs.wins_needed(5) == 3
    assert bs.wins_needed(7) == 4
    assert bs.terminal(3, 1, 5) is True
    assert bs.terminal(2, 2, 5) is False


def test_step_state_no_mutation():
    st = bs.SeriesState(max_games=5, our_pool=['a', 'b'], used_us=set())
    nst = bs.step_state(st, our_hero='a', their_hero='x', we_win=True)
    assert nst.score_us == 1 and nst.score_them == 0
    assert nst.game_seq == 2
    assert 'a' in nst.used_us
    assert 'a' not in st.used_us  # 原状态不被修改
    assert nst.side_us == 'red'


def test_plan_series_basic():
    st = bs.SeriesState(max_games=3, our_pool=['a', 'b'], their_pool=['x', 'y'])
    plans = bs.plan_series(st, beam_width=2)
    assert isinstance(plans, list) and plans
    # BO3 最多 3 局
    assert all(len(p['games']) <= 3 for p in plans)
    # 英雄使用约束：同一方案内我方不重复用英雄（巅峰除外；BO3 第3局非巅峰）
    for p in plans:
        heroes = [g['ourHero'] for g in p['games']]
        assert len(heroes) == len(set(heroes)), f'duplicate hero in plan: {heroes}'


def test_plan_series_with_game_value():
    def gv(o, t, s):
        return 0.9 if o == 'a' else 0.3
    st = bs.SeriesState(max_games=3, our_pool=['a', 'b'], their_pool=['x'])
    plans = bs.plan_series(st, game_value=gv, beam_width=2)
    assert plans[0]['value'] > plans[-1]['value']