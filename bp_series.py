"""BO5/BO7 全局 BP 规划（规则引擎 + 情景推演骨架）。

编码 2026 KPL 全局 BP 规则：
- 队伍级英雄使用约束：系列赛中同一支队伍用过的英雄不能在后续局复用；
- 巅峰对决（打满最后一局）：解禁，所有英雄重新可用；
- 选边：由调用方传入当前局我方阵营。

本模块只提供规则引擎与搜索骨架，不 pretending 有可靠胜率模型：
对局价值函数 `game_value` 默认中性（0.5），调用方可注入基于 bp_predict / hero_roles
的估值。输出为候选方案（每局我方英雄 + 预期对手应对 + 估值），供教练对照。
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Iterable


def is_peak_duel(game_seq, max_games):
    """打满最后一局 = 巅峰对决（解禁）。"""
    return int(game_seq) == int(max_games) and int(max_games) > 1


def available_heroes(pool, used, *, game_seq=1, max_games=5, peak_override=True):
    """我方可选英雄：巅峰对决解禁；否则剔除已用。"""
    pool = list(pool or [])
    if peak_override and is_peak_duel(game_seq, max_games):
        return list(pool)
    used = set(used or [])
    return [h for h in pool if h not in used]


def wins_needed(max_games):
    return (int(max_games) // 2) + 1


def terminal(score_us, score_them, max_games):
    need = wins_needed(max_games)
    return score_us >= need or score_them >= need


@dataclass
class SeriesState:
    score_us: int = 0
    score_them: int = 0
    game_seq: int = 1
    max_games: int = 5
    used_us: set = field(default_factory=set)
    used_them: set = field(default_factory=set)
    side_us: str = 'blue'  # 'blue' or 'red'
    our_pool: list = field(default_factory=list)
    their_pool: list = field(default_factory=list)


def step_state(state, *, our_hero, their_hero, we_win):
    """应用一局结果，返回新状态（不修改原状态）。"""
    new = SeriesState(
        score_us=state.score_us + (1 if we_win else 0),
        score_them=state.score_them + (0 if we_win else 1),
        game_seq=state.game_seq + 1,
        max_games=state.max_games,
        used_us=set(state.used_us) | ({our_hero} if our_hero else set()),
        used_them=set(state.used_them) | ({their_hero} if their_hero else set()),
        side_us='red' if state.side_us == 'blue' else 'blue',
        our_pool=list(state.our_pool),
        their_pool=list(state.their_pool),
    )
    return new


def plan_series(state, *, enemy_candidates=None, beam_width=4, horizon=None,
                game_value: Callable[[str, str, SeriesState], float] = None):
    """Beam search 生成系列赛英雄使用方案。

    game_value(our_hero, their_hero, state) -> float 胜率估计（0-1）。
    默认 0.5 中性。
    返回 list of plan dict: [{'games':[{'seq','ourHero','theirHero','value'}], 'value':float}]
    """
    if game_value is None:
        game_value = lambda o, t, s: 0.5
    if horizon is None:
        horizon = state.max_games - state.game_seq + 1
    if enemy_candidates is None:
        enemy_candidates = lambda st, our_hero: [None]

    # beam: list of (cumulative_value, state, plan_games)
    beam = [(0.0, state, [])]
    for _ in range(horizon):
        new_beam = []
        for cum, st, plan in beam:
            if terminal(st.score_us, st.score_them, st.max_games):
                new_beam.append((cum, st, plan))
                continue
            our_opts = available_heroes(st.our_pool, st.used_us,
                                        game_seq=st.game_seq, max_games=st.max_games)
            if not our_opts:
                new_beam.append((cum, st, plan))
                continue
            for our in our_opts:
                for their in (enemy_candidates(st, our) or [None]):
                    v = game_value(our, their, st)
                    nst = step_state(st, our_hero=our, their_hero=their,
                                     we_win=v >= 0.5)
                    nplan = plan + [{'seq': st.game_seq, 'ourHero': our,
                                    'theirHero': their, 'value': round(v, 3)}]
                    new_beam.append((cum + v, nst, nplan))
        new_beam.sort(key=lambda x: -x[0])
        seen = set()
        pruned = []
        for cum, st, plan in new_beam:
            key = (st.score_us, st.score_them, st.game_seq, frozenset(st.used_us))
            if key in seen:
                continue
            seen.add(key)
            pruned.append((cum, st, plan))
            if len(pruned) >= beam_width:
                break
        beam = pruned if pruned else new_beam[:beam_width]
        if not beam:
            break

    out = []
    for cum, st, plan in beam:
        out.append({'games': plan, 'value': round(cum, 3),
                    'finalScore': f"{st.score_us}-{st.score_them}"})
    out.sort(key=lambda x: -x['value'])
    return out


def format_plan(plan):
    lines = []
    for g in plan.get('games', []):
        lines.append(f"第{g['seq']}局：我方 {g['ourHero']} vs 对手 {g.get('theirHero') or '?'} "
                     f"(估值 {g.get('value')})")
    lines.append(f"总估值 {plan['value']}，最终比分 {plan['finalScore']}")
    return '\n'.join(lines)


if __name__ == '__main__':
    st = SeriesState(max_games=5, our_pool=['关羽', '马超', '吕布'],
                     their_pool=['花木兰', '赵云'], side_us='blue')
    plans = plan_series(st, beam_width=3)
    for p in plans[:3]:
        print(format_plan(p))
        print('---')