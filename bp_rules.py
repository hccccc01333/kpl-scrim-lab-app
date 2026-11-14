"""Rules for the USER-PROVIDED scrim BO3/BO5/BO7 global BP.

Scrim (15 actions): B R B R B bans, then B1 R2 B2 R2 B2 R1 picks.
Five bans are TOTAL: blue bans 3, red bans 2. Each side picks 5.
Across games, each TEAM cannot pick a hero THAT TEAM already picked.
Bans reset each game. Camps can swap between games; stable team identity
controls the global no-repeat rule.

KPL is independent and has no assumed search schedule in this module.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass


def _repeat(action, camp, count):
    return ((action, camp),) * count


SCRIM_15_SCHEDULE = (
    _repeat("ban", "1", 1) + _repeat("ban", "2", 1)
    + _repeat("ban", "1", 1) + _repeat("ban", "2", 1)
    + _repeat("ban", "1", 1)
    + _repeat("pick", "1", 1) + _repeat("pick", "2", 2)
    + _repeat("pick", "1", 2) + _repeat("pick", "2", 2)
    + _repeat("pick", "1", 2) + _repeat("pick", "2", 1)
)
assert len(SCRIM_15_SCHEDULE) == 15
assert Counter(SCRIM_15_SCHEDULE) == {
    ("ban", "1"): 3, ("ban", "2"): 2,
    ("pick", "1"): 5, ("pick", "2"): 5,
}
SERIES_LENGTHS = {"BO3": 3, "BO5": 5, "BO7": 7}


@dataclass(frozen=True)
class DraftRule:
    id: str
    source: str
    title: str
    schedule: tuple[tuple[str, str], ...]
    configured: bool = True


SCRIM_GLOBAL_15 = DraftRule(
    "scrim-global-15", "scrim", "训练赛 · 5 Ban + 10 Pick · BO 全局 BP",
    SCRIM_15_SCHEDULE,
)
KPL_RECORDED = DraftRule(
    "kpl-recorded", "kpl", "KPL · 真实赛事记录（按赛事另配规则）", (),
    configured=False,
)


def profile_for(source: str, profile: str | None = None) -> DraftRule:
    if source == "scrim":
        if profile in (None, "", SCRIM_GLOBAL_15.id):
            return SCRIM_GLOBAL_15
        raise ValueError("训练赛规则不是旧四阶段 18 手；请使用 scrim-global-15")
    if source == "kpl":
        if profile in (None, "", KPL_RECORDED.id):
            return KPL_RECORDED
        raise ValueError("KPL 不能套用训练赛 BO 全局 BP 规则")
    raise ValueError("未知 BP 数据来源")


def validate_series_context(bo="BO5", game_number=1):
    if bo not in SERIES_LENGTHS:
        raise ValueError("赛制必须是 BO3、BO5 或 BO7")
    if isinstance(game_number, bool) or not isinstance(game_number, int):
        raise ValueError("局数必须为整数")
    if not 1 <= game_number <= SERIES_LENGTHS[bo]:
        raise ValueError("当前局数超出了赛制范围")
    return SERIES_LENGTHS[bo]


def _events_valid(events, schedule, *, full=False):
    if not isinstance(events, (list, tuple)) or len(events) > len(schedule):
        return False
    used = set()
    for idx, event in enumerate(events):
        if not isinstance(event, dict):
            return False
        action, camp = schedule[idx]
        if event.get("action") != action or str(event.get("camp")) != camp:
            return False
        if "order" in event:
            order = event["order"]
            if isinstance(order, bool) or str(order) != str(idx + 1):
                return False
        hero = str(event.get("hero") or "").strip()
        if not hero or hero in used:
            return False
        used.add(hero)
    return not full or len(events) == len(schedule)


def validate_scrim_prefix(events, *, full=False):
    """Blue=camp 1, red=camp 2; only the screenshot's 15-turn scrim profile."""
    return _events_valid(events, SCRIM_15_SCHEDULE, full=full)


def next_scrim_action(events):
    if not validate_scrim_prefix(events):
        raise ValueError("训练赛选禁顺序不符合 5 Ban + 10 Pick 的 15 手规则")
    if len(events) == len(SCRIM_15_SCHEDULE):
        return None
    action, camp = SCRIM_15_SCHEDULE[len(events)]
    return {"order": len(events) + 1, "action": action, "camp": camp,
            "phase": "ban" if len(events) < 5 else "pick"}


def can_assign_to_players(chosen, pools):
    """Maximum bipartite matching for the five actual player hero pools."""
    if pools is None:
        return True
    if len(pools) != 5 or len(chosen) > 5 or len(set(chosen)) != len(chosen):
        return False
    if any(not pool for pool in pools):
        return False
    assignments = {}
    def allocate(hero, visited):
        for player_id, pool in enumerate(pools):
            if player_id in visited or hero not in pool:
                continue
            visited.add(player_id)
            if player_id not in assignments or allocate(assignments[player_id], visited):
                assignments[player_id] = hero
                return True
        return False
    return all(allocate(hero, set()) for hero in chosen)


def build_series_used(history, *, bo, game_number, teams):
    """Verify every prior completed game, following stable team IDs across swaps.

    history = [{"game":1, "picks":{"TEAM_A":[5], "TEAM_B":[5]}}, ...].
    Never infer completed games from date, BO label or present game's lineup.
    The return value is safe only when all previous games are provided.
    """
    validate_series_context(bo, game_number)
    if not isinstance(teams, (list, tuple)) or len(teams) != 2:
        raise ValueError("必须指定系列赛双方稳定的战队身份")
    a, b = teams
    if not all(isinstance(team, str) and team.strip() for team in teams) or a == b:
        raise ValueError("系列赛双方战队身份必须不同且非空")
    if not isinstance(history, (list, tuple)) or len(history) != game_number - 1:
        raise ValueError("缺少此前某局 BP 选人记录，不能确认全局英雄禁复用")
    used = {a: set(), b: set()}
    for index, row in enumerate(history, 1):
        if not isinstance(row, dict) or row.get("game") != index:
            raise ValueError("系列赛历史必须按真实局序连续排列")
        picks = row.get("picks")
        if not isinstance(picks, dict) or set(picks) != {a, b}:
            raise ValueError("历史每局必须提供双方战队真实选人")
        this_game = set()
        for team in (a, b):
            heroes = picks[team]
            if (not isinstance(heroes, (tuple, list)) or len(heroes) != 5 or
                    any(not isinstance(h, str) or not h.strip() for h in heroes)):
                raise ValueError("历史每方每局必须明确提供五个英雄")
            if len(set(heroes)) != 5 or this_game.intersection(heroes):
                raise ValueError("同局双方不能重复选择英雄")
            if used[team].intersection(heroes):
                raise ValueError("该战队存在跨局复用已选英雄的非法记录")
            used[team].update(heroes)
            this_game.update(heroes)
    return {team: frozenset(heroes) for team, heroes in used.items()}


def legal_scrim_candidates(
    events, hero_pool, *, blue_player_pools=None, red_player_pools=None,
    series_unavailable=(), series_used_by_team=None,
    blue_team="蓝方", red_team="红方", bo="BO5", game_number=1,
):
    """Legal next action for the scrim-only schedule and prior series history.

    In-game bans/picks exclude both sides from the current game.
    Across games only the acting team's previous PICKS are unavailable for
    its next PICK; opponent's earlier picks may be available to our team.
    Previous-game bans do not carry over. A separate generic exclusion list
    can express additional explicitly verified restrictions, for picks only.
    """
    validate_series_context(bo, game_number)
    nxt = next_scrim_action(events)
    if nxt is None:
        return []
    if not isinstance(hero_pool, (list, tuple, set, frozenset)):
        raise ValueError("候选英雄池必须是明确的英雄列表")
    if blue_team == red_team:
        raise ValueError("双方不能使用同一战队身份")
    taken = {str(row["hero"]) for row in events}
    actor_team = blue_team if nxt["camp"] == "1" else red_team
    if game_number > 1 and series_used_by_team is None:
        raise ValueError("第 2 局起必须提供已验证的全局 BP 历史英雄集合")
    used = series_used_by_team or {}
    if not isinstance(used, dict):
        raise ValueError("历史英雄必须按战队身份组织")
    for team in (blue_team, red_team):
        history = used.get(team, ())
        if (not isinstance(history, (set, frozenset, tuple, list)) or
                len(set(history)) != 5 * (game_number - 1) or
                len(history) != 5 * (game_number - 1) or
                any(not isinstance(h, str) or not h for h in history)):
            raise ValueError("全局历史不完整：需要双方此前每局各 5 个真实选人")
    # A previously picked hero cannot appear again in this TEAM's picks,
    # even if someone supplied an already-illegal in-progress prefix.
    for row in events:
        if row["action"] != "pick":
            continue
        team = blue_team if str(row["camp"]) == "1" else red_team
        if row["hero"] in used.get(team, ()):
            raise ValueError("当前 BP 已违反全局禁复用限制")
    blocked = taken.copy()
    if nxt["action"] == "pick":
        blocked.update(used.get(actor_team, ()))
        blocked.update(series_unavailable)
    pools = blue_player_pools if nxt["camp"] == "1" else red_player_pools
    selected = [str(row["hero"]) for row in events
                if row["action"] == "pick" and str(row["camp"]) == nxt["camp"]]
    return [
        hero for hero in dict.fromkeys(hero_pool)
        if isinstance(hero, str) and hero and hero not in blocked
        and (nxt["action"] == "ban" or can_assign_to_players(selected + [hero], pools))
    ]


def append_legal_scrim_action(events, hero, hero_pool, **kwargs):
    """Authoritative state transition for candidate search and UI."""
    nxt = next_scrim_action(events)
    if nxt is None:
        raise ValueError("本局 BP 已完成")
    if hero not in legal_scrim_candidates(events, hero_pool, **kwargs):
        raise ValueError("该英雄在当前 BP 与系列赛状态下不可选择")
    return list(events) + [{"order": nxt["order"], "action": nxt["action"],
                            "camp": nxt["camp"], "hero": hero}]
