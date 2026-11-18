"""BO3/BO5/BO7 训练赛全局 BP 规划（规则引擎 + 情景推演骨架）。

规则唯一来源见 :mod:`bp_formats`：
- 征召/训练赛 ``draft-18``：4 Ban/方 + 5 Pick/方，18 手；
- KPL ``draft-20``：5 Ban/方 + 5 Pick/方，20 手；
- 排位/巅峰 ``rank-20``：5+5 同时 Ban + 10 Pick。

全局 BP：BO3 / BO5 / BO7 都跨局记录本队已选英雄，后续局不可复用；
元流之子五形态按一个英雄累计。征召默认没有巅峰对决，KPL 只在 BO7 第 7 局
解禁盲选；本规划器只做跨局英雄约束，不做没有依据的胜率建模。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from bp_formats import DRAFT_18, pick_key
from bp_rules import SERIES_LENGTHS

SCRIM_RULE = DRAFT_18  # 训练赛/征召唯一规则（id: draft-18）


def scrim_slots() -> list[dict]:
    """本局逐手序（camp '1'=蓝 '2'=红）。

    顺序来自 ``bp_formats.DRAFT_18.schedule``；本规划器只管跨局英雄约束，
    单局逐手校验用 ``bp_formats.check_draft`` / ``legal_candidates``。
    """
    return [{'order': row['order'], 'action': row['action'],
             'camp': row['camp'], 'phase': row['phase'],
             'parallel': row.get('parallel', False)}
            for row in DRAFT_18.schedule]


def available_heroes(pool, used):
    """我方可选英雄：全局 BP 只剔除本队已选过的英雄（元流五形态合一）。"""
    used = {pick_key(hero) for hero in (used or ())}
    return [hero for hero in (pool or ()) if pick_key(hero) not in used]


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
    side_us: str = 'blue'  # 'blue' or 'red'；局间换边由调用方控制
    our_pool: list = field(default_factory=list)
    their_pool: list = field(default_factory=list)


def step_state(state, *, our_hero, their_hero, we_win):
    """应用一局结果，返回新状态（不修改原状态）。

    全局 BP：used_us / used_them 跨局累计——本队选过的英雄后续局不可复用。
    """
    return SeriesState(
        score_us=state.score_us + (1 if we_win else 0),
        score_them=state.score_them + (0 if we_win else 1),
        game_seq=state.game_seq + 1,
        max_games=state.max_games,
        used_us=set(state.used_us) | ({pick_key(our_hero)} if our_hero else set()),
        used_them=set(state.used_them) | ({pick_key(their_hero)} if their_hero else set()),
        side_us='red' if state.side_us == 'blue' else 'blue',
        our_pool=list(state.our_pool),
        their_pool=list(state.their_pool),
    )


def plan_series(state, *, enemy_candidates=None, beam_width=4, horizon=None,
                game_value: Callable[[str, str, SeriesState], float] = None):
    """Beam search 生成系列赛英雄使用方案。

    game_value(our_hero, their_hero, state) -> float 胜率估计（0-1）。
    默认 0.5 中性。返回 list of plan dict:
    [{'games':[{'seq','ourHero','theirHero','value'}], 'value':float}]
    """
    if game_value is None:
        game_value = lambda o, t, s: 0.5  # noqa: E731
    if horizon is None:
        horizon = state.max_games - state.game_seq + 1
    if enemy_candidates is None:
        enemy_candidates = lambda st, our_hero: [None]  # noqa: E731

    beam = [(0.0, state, [])]
    for _ in range(horizon):
        new_beam = []
        for cum, st, plan in beam:
            if terminal(st.score_us, st.score_them, st.max_games):
                new_beam.append((cum, st, plan))
                continue
            our_opts = available_heroes(st.our_pool, st.used_us)
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
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    st = SeriesState(max_games=5, our_pool=['关羽', '马超', '吕布'],
                     their_pool=['花木兰', '赵云'], side_us='blue')
    plans = plan_series(st, beam_width=3)
    for p in plans[:3]:
        print(format_plan(p))
        print('---')
    print(f"训练赛规则：{SCRIM_RULE.title}（{len(scrim_slots())} 手/局，全局 BP）")
