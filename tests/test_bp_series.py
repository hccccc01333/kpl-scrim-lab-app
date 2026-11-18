"""BO3/BO5/BO7 训练赛全局 BP 规划：规则引擎与搜索骨架（训练赛口径）。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bp_series as bs  # noqa: E402
from bp_rules import SCRIM_20_SCHEDULE  # noqa: E402


def test_no_peak_unlock_any_game():
    # 训练赛规则：全局 BP 跨局禁复用，**末局也不解禁**
    assert bs.available_heroes(['a', 'b', 'c'], {'a'}) == ['b', 'c']
    # 空已用集 → 全池可选
    assert bs.available_heroes(['a', 'b'], set()) == ['a', 'b']
    assert not hasattr(bs, 'is_peak_duel'), '巅峰对决解禁必须移除'


def test_scrim_rule_delegates_to_bp_rules():
    # 规则唯一档案在 bp_formats；bp_series 只引用不另造
    assert bs.SCRIM_RULE.id == 'draft-18'
    slots = bs.scrim_slots()
    assert len(slots) == 18
    assert [s['phase'] for s in slots] == (
        ['ban1'] * 4 + ['pick1'] * 6 + ['ban2'] * 4 + ['pick2'] * 4)
    assert [(s['action'], s['camp']) for s in slots[:4]] == [
        ('ban', '1'), ('ban', '2'), ('ban', '1'), ('ban', '2')]
    assert [(s['action'], s['camp']) for s in slots[10:14]] == [
        ('ban', '2'), ('ban', '1'), ('ban', '2'), ('ban', '1')]
    pick_camps = [s['camp'] for s in slots if s['action'] == 'pick']
    assert pick_camps == ['1', '2', '2', '1', '1', '2', '2', '1', '1', '2']
    assert sum(1 for s in slots if s['camp'] == '1' and s['action'] == 'pick') == 5
    assert sum(1 for s in slots if s['camp'] == '2' and s['action'] == 'pick') == 5
    assert SCRIM_20_SCHEDULE == tuple((s['action'], s['camp']) for s in slots)


def test_terminal_and_wins_needed():
    assert bs.wins_needed(5) == 3
    assert bs.wins_needed(7) == 4
    assert bs.wins_needed(3) == 2
    assert bs.terminal(3, 1, 5) is True
    assert bs.terminal(2, 2, 5) is False


def test_step_state_global_bp_no_mutation():
    st = bs.SeriesState(max_games=5, our_pool=['a', 'b'], used_us=set())
    nst = bs.step_state(st, our_hero='a', their_hero='x', we_win=True)
    assert nst.score_us == 1 and nst.score_them == 0
    assert nst.game_seq == 2
    assert 'a' in nst.used_us
    assert 'a' not in st.used_us  # 原状态不被修改
    # 全局 BP：used_us 跨局累计；对手选过的我方仍可选（不进 our 约束）
    nst2 = bs.step_state(nst, our_hero='b', their_hero='a', we_win=False)
    assert nst2.used_us == {'a', 'b'}
    assert nst2.used_them == {'x', 'a'}
    assert bs.available_heroes(nst2.our_pool, nst2.used_us) == []


def test_plan_series_basic():
    st = bs.SeriesState(max_games=3, our_pool=['a', 'b'], their_pool=['x', 'y'])
    plans = bs.plan_series(st, beam_width=2)
    assert isinstance(plans, list) and plans
    # BO3 最多 3 局
    assert all(len(p['games']) <= 3 for p in plans)
    # 全局 BP：同一方案内我方不重复用英雄（任何局都不解禁）
    for p in plans:
        heroes = [g['ourHero'] for g in p['games']]
        assert len(heroes) == len(set(heroes)), f'duplicate hero in plan: {heroes}'


def test_plan_series_pool_exhaustion_ends_plan():
    # 池只有 1 个英雄：第 1 局用完后，后续局无可选英雄 → 方案在该局截断
    st = bs.SeriesState(max_games=5, our_pool=['a'], their_pool=['x'])
    plans = bs.plan_series(st, beam_width=2)
    for p in plans:
        assert len(p['games']) <= 1


def test_plan_series_with_game_value():
    # 估值随英雄与局序变化（解禁移除后，固定单英雄估值会让同集合不同排列的总和相同）：
    # base a=0.9 / b=0.6 / c=0.4，随局序衰减 10%，不同路径总和可区分
    base = {'a': 0.9, 'b': 0.6, 'c': 0.4}

    def gv(o, t, s):
        return round(base[o] * (1 - 0.1 * (s.game_seq - 1)), 3)
    st = bs.SeriesState(max_games=3, our_pool=['a', 'b', 'c'], their_pool=['x', 'y'])
    plans = bs.plan_series(st, game_value=gv, beam_width=3)
    assert plans[0]['value'] > plans[-1]['value']
    # 全局 BP：任何方案内我方英雄不重复
    for p in plans:
        heroes = [g['ourHero'] for g in p['games']]
        assert len(heroes) == len(set(heroes))
