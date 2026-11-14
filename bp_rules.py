"""Source-specific BP rules.

The 18-action scrim profile transcribes the user's FOUR STAGES exactly.
Its header mentions two bans per side, but the listed four stages contain
FOUR bans per side (8 total). Do not silently treat it as a KPL template.

KPL schedules vary by event/season; no KPL schedule is invented here.
Its historical actions are validated against observed lineups, not SCRIM_18.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass


def _repeat(action, camp, n):
    return ((action, camp),) * n


SCRIM_18_SCHEDULE = (
    _repeat("ban", "1", 1) + _repeat("ban", "2", 1)
    + _repeat("ban", "1", 1) + _repeat("ban", "2", 1)
    + _repeat("pick", "1", 1) + _repeat("pick", "2", 2)
    + _repeat("pick", "1", 2) + _repeat("pick", "2", 1)
    + _repeat("ban", "2", 1) + _repeat("ban", "1", 1)
    + _repeat("ban", "2", 1) + _repeat("ban", "1", 1)
    + _repeat("pick", "2", 1) + _repeat("pick", "1", 2)
    + _repeat("pick", "2", 1)
)
assert len(SCRIM_18_SCHEDULE) == 18
assert Counter(SCRIM_18_SCHEDULE) == {
    ("ban", "1"): 4, ("ban", "2"): 4,
    ("pick", "1"): 5, ("pick", "2"): 5,
}


@dataclass(frozen=True)
class DraftRule:
    id: str
    source: str
    title: str
    schedule: tuple[tuple[str, str], ...]
    configured: bool = True


SCRIM_STAGED_18 = DraftRule(
    "scrim-staged-18", "scrim", "训练赛 · 四阶段 18 手",
    SCRIM_18_SCHEDULE,
)
KPL_RECORDED = DraftRule(
    "kpl-recorded", "kpl", "KPL · 真实赛事记录（规则待赛事配置）", (),
    configured=False,
)


def profile_for(source: str, profile: str | None = None) -> DraftRule:
    if source == "scrim":
        if profile in (None, "", SCRIM_STAGED_18.id):
            return SCRIM_STAGED_18
        raise ValueError("未知训练赛 BP 规则；不能自动套用 KPL 规则")
    if source == "kpl":
        if profile in (None, "", KPL_RECORDED.id):
            return KPL_RECORDED
        raise ValueError("KPL 未配置对应赛事赛制，不能套用训练赛的 18 手规则")
    raise ValueError("未知 BP 来源")


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
        hero = str(event.get("hero") or "").strip()
        if not hero or hero in used:
            return False
        used.add(hero)
    return not full or len(events) == len(schedule)


def validate_scrim_prefix(events, *, full=False):
    """Input must use actual chronological blue/red camp IDs, not a team POV."""
    return _events_valid(events, SCRIM_18_SCHEDULE, full=full)


def next_scrim_action(events):
    if not validate_scrim_prefix(events):
        raise ValueError("训练赛选禁步骤与四阶段规则不符")
    if len(events) == len(SCRIM_18_SCHEDULE):
        return None
    action, camp = SCRIM_18_SCHEDULE[len(events)]
    return {"order": len(events) + 1, "action": action, "camp": camp,
            "phase": (1 if len(events) < 4 else 2 if len(events) < 10
                      else 3 if len(events) < 14 else 4)}


def can_assign_to_players(chosen, pools):
    """Feasibility check: distinct chosen heroes must fit distinct players.

    pools: exactly five player-to-hero sets. If unknown, caller must declare
    that it is allowing unverified pools, not pretend everyone can play hero.
    """
    if pools is None:
        return True
    if len(pools) != 5 or len(chosen) > 5:
        return False
    if any(not pool for pool in pools):
        return False
    if len(set(chosen)) != len(chosen):
        return False
    # Small bipartite matching (five picks maximum).
    assignments = {}
    def allocate(hero, visited):
        for p, pool in enumerate(pools):
            if p in visited or hero not in pool:
                continue
            visited.add(p)
            if p not in assignments or allocate(assignments[p], visited):
                assignments[p] = hero
                return True
        return False
    return all(allocate(h, set()) for h in chosen)


def legal_scrim_candidates(events, hero_pool, *,
                           blue_player_pools=None, red_player_pools=None,
                           series_unavailable=()):
    """Strict next-action filter for the specified scrim variant only.

    No KPL/global-series rule is assumed. Series exclusions are explicit.
    Ban actions need no player assignment; picks must be feasible for a
    one-hero-per-player lineup when player pools are available.
    """
    nxt = next_scrim_action(events)
    if nxt is None:
        return []
    used = {str(row["hero"]) for row in events} | set(series_unavailable)
    pools = blue_player_pools if nxt["camp"] == "1" else red_player_pools
    selected = [str(row["hero"]) for row in events
                if row["action"] == "pick" and str(row["camp"]) == nxt["camp"]]
    return [
        hero for hero in dict.fromkeys(hero_pool)
        if isinstance(hero, str) and hero and hero not in used
        and (nxt["action"] != "pick" or can_assign_to_players(selected + [hero], pools))
    ]
