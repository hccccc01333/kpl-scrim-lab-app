"""User-provided training-scrim global BP rules are not KPL rules."""
import pytest

from bp_rules import (
    SCRIM_15_SCHEDULE, SERIES_LENGTHS,
    append_legal_scrim_action, build_series_used, can_assign_to_players,
    legal_scrim_candidates, next_scrim_action, profile_for,
    validate_scrim_prefix, validate_series_context,
)
from bp_intelligence import build_report, normalize_kpl, normalize_scrims


BLUE_PICKS = ["花木兰", "镜", "小乔", "孙尚香", "张飞"]
RED_PICKS = ["马超", "暃", "沈梦溪", "狄仁杰", "太乙真人"]
BLUE_BANS = ["大乔", "朵莉亚", "鲁班大师"]
RED_BANS = ["亚连", "吕布"]


def full_scrim_actions():
    queues = {
        ("pick", "1"): iter(BLUE_PICKS), ("pick", "2"): iter(RED_PICKS),
        ("ban", "1"): iter(BLUE_BANS), ("ban", "2"): iter(RED_BANS),
    }
    return [{"order": i + 1, "action": action, "camp": camp,
             "hero": next(queues[(action, camp)])}
            for i, (action, camp) in enumerate(SCRIM_15_SCHEDULE)]


def scrim(events=None, rule="scrim-global-15"):
    return [{
        "key": "scrim-001", "day": "2026-11-14", "ownSide": "left",
        "opponent": "对手战队", "result": "win", "ruleProfile": rule,
        "picks": {"own": BLUE_PICKS, "enemy": RED_PICKS},
        "bans": {"own": BLUE_BANS, "enemy": RED_BANS},
        "draftEvents": full_scrim_actions() if events is None else events,
    }]


def test_actual_scrim_order_five_bans_ten_picks_and_no_second_ban_phase():
    assert len(SCRIM_15_SCHEDULE) == 15
    assert list(SCRIM_15_SCHEDULE[:5]) == [
        ("ban", "1"), ("ban", "2"), ("ban", "1"),
        ("ban", "2"), ("ban", "1"),
    ]
    assert list(SCRIM_15_SCHEDULE[5:]) == [
        ("pick", "1"), ("pick", "2"), ("pick", "2"),
        ("pick", "1"), ("pick", "1"),
        ("pick", "2"), ("pick", "2"),
        ("pick", "1"), ("pick", "1"), ("pick", "2"),
    ]
    assert validate_scrim_prefix(full_scrim_actions(), full=True)
    assert next_scrim_action(full_scrim_actions()) is None
    assert next_scrim_action(full_scrim_actions()[:5]) == {
        "order": 6, "action": "pick", "camp": "1", "phase": "pick"}


def test_scrim_wrong_actor_extra_ban_duplicate_hero_are_rejected():
    changed = [dict(e) for e in full_scrim_actions()]
    changed[5]["action"] = "ban"
    assert not validate_scrim_prefix(changed, full=True)
    changed = [dict(e) for e in full_scrim_actions()]
    changed[3]["camp"] = "1"
    assert not validate_scrim_prefix(changed, full=True)
    changed = [dict(e) for e in full_scrim_actions()]
    changed[7]["hero"] = changed[6]["hero"]
    assert not validate_scrim_prefix(changed, full=True)
    changed = [dict(e) for e in full_scrim_actions()]
    changed[7]["order"] = 9
    assert not validate_scrim_prefix(changed, full=True)
    with pytest.raises(ValueError):
        next_scrim_action(changed[:8])


def test_normalized_scrim_validated_from_both_team_perspectives():
    games = normalize_scrims(scrim())
    assert len(games) == 2
    assert {g["team"] for g in games} == {"本队", "对手战队"}
    assert all(g["ruleProfile"] == "scrim-global-15" for g in games)
    assert all(g["ruleValidated"] for g in games)
    assert all(len(g["events"]) == 15 for g in games)
    report = build_report(scrim(), [], source="scrim", team="本队")
    assert report["scope"]["orderedGames"] == 1
    assert report["bpStudies"]["ruleCoverage"]["scrim15"] == 1
    assert report["bpStudies"]["ruleCoverage"]["kplRecorded"] == 0


def test_wrong_turn_or_old_18_turn_data_is_not_used_as_scrim_order():
    changed = [dict(e) for e in full_scrim_actions()]
    changed[4], changed[5] = changed[5], changed[4]
    changed = [dict(e, order=i + 1) for i, e in enumerate(changed)]
    games = normalize_scrims(scrim(changed))
    assert all(not g["ruleValidated"] and not g["events"] for g in games)
    assert all(g["ruleProfile"] == "scrim-unconfirmed" for g in games)
    old = full_scrim_actions()
    old.insert(6, {"order": 7, "camp": "1", "action": "ban", "hero": "司空震"})
    old = [dict(e, order=i + 1) for i, e in enumerate(old)]
    # Old malformed event data is retained only as final picks/bans evidence.
    report = build_report(scrim(old, rule="scrim-staged-18"), [],
                          source="scrim", team="本队")
    assert report["scope"]["orderedGames"] == 0
    assert report["scope"]["games"] == 1


def test_kpl_recorded_actions_not_forced_into_practice_schedule():
    actions = [
        {"order": i + 1, "action": action, "camp": camp, "hero": hero}
        for i, (action, camp, hero) in enumerate([
            ("ban", "1", "朵莉亚"), ("ban", "2", "亚连"),
            ("ban", "1", "大乔"), ("ban", "2", "吕布"),
            *[("pick", "1", h) for h in BLUE_PICKS],
            *[("pick", "2", h) for h in RED_PICKS],
        ])
    ]
    rows = [{"battleId": "kpl-1", "date": "2026-11-14",
             "camp1": {"team": "战队甲"}, "camp2": {"team": "战队乙"},
             "picks": {"1": BLUE_PICKS, "2": RED_PICKS},
             "bans": {"1": ["朵莉亚", "大乔"], "2": ["亚连", "吕布"]},
             "draftEvents": actions, "bansKnown": True,
             "pickOrderKnown": True, "winCamp": 1}]
    normalized = normalize_kpl(rows)
    assert len(normalized) == 2
    assert all(len(g["events"]) == 14 for g in normalized)
    assert all(g["ruleProfile"] == "kpl-recorded" for g in normalized)
    assert all(not g["ruleValidated"] for g in normalized)
    report = build_report([], rows, source="kpl", team="战队甲")
    assert report["scope"]["orderedGames"] == 1
    assert report["bpStudies"]["ruleCoverage"]["kplRecorded"] == 1
    assert report["bpStudies"]["ruleCoverage"]["scrim15"] == 0


def test_cross_source_profiles_cannot_be_confused():
    assert profile_for("scrim").id == "scrim-global-15"
    assert profile_for("kpl").id == "kpl-recorded"
    assert not profile_for("kpl").configured
    with pytest.raises(ValueError):
        profile_for("kpl", "scrim-global-15")
    with pytest.raises(ValueError):
        profile_for("scrim", "kpl-recorded")
    with pytest.raises(ValueError):
        profile_for("scrim", "scrim-staged-18")


@pytest.mark.parametrize("bo, length", SERIES_LENGTHS.items())
def test_bo3_bo5_bo7_game_number_limits(bo, length):
    assert validate_series_context(bo, length) == length
    with pytest.raises(ValueError):
        validate_series_context(bo, length + 1)
    with pytest.raises(ValueError):
        validate_series_context(bo, 0)


def _previous(game, team_a=None, team_b=None):
    def heroes(prefix):
        return [prefix + str(j) for j in range(5)]
    return {"game": game,
            "picks": {"甲": team_a or heroes("甲" + str(game) + "-"),
                      "乙": team_b or heroes("乙" + str(game) + "-")}}


def test_global_bp_prevents_same_team_reuse_even_after_side_swap():
    # 甲 used A1 in game 1 as blue. In game 2, 甲 plays RED.
    history = [_previous(1)]
    used = build_series_used(history, bo="BO3", game_number=2,
                             teams=("甲", "乙"))
    old_a = history[0]["picks"]["甲"][0]
    old_b = history[0]["picks"]["乙"][0]
    phase = full_scrim_actions()[:5]  # First pick is BLUE (乙 this game).
    candidates = ["新英雄", old_a, old_b]
    blue = legal_scrim_candidates(
        phase, candidates, bo="BO3", game_number=2,
        blue_team="乙", red_team="甲", series_used_by_team=used)
    # 乙 cannot re-pick its own previously used hero; 甲's is available to 乙.
    assert old_b not in blue and old_a in blue
    # Move to the red side's first pick by legally choosing a blue hero.
    progress = append_legal_scrim_action(
        phase, old_a, candidates, bo="BO3", game_number=2,
        blue_team="乙", red_team="甲", series_used_by_team=used)
    red = legal_scrim_candidates(
        progress, candidates, bo="BO3", game_number=2,
        blue_team="乙", red_team="甲", series_used_by_team=used)
    assert old_a not in red  # Picked earlier in THIS game (also 甲 already used).
    assert old_b in red  # Opponent's old hero may be used by 甲.


def test_previous_game_bans_reset_but_pick_reuse_does_not():
    used = build_series_used([_previous(1)], bo="BO3",
                             game_number=2, teams=("甲", "乙"))
    first_ban = legal_scrim_candidates(
        [], ["甲1-0", "全新英雄"], bo="BO3", game_number=2,
        blue_team="甲", red_team="乙", series_used_by_team=used)
    assert "甲1-0" in first_ban  # Cross-game ban remains legal.
    after_bans = full_scrim_actions()[:5]
    picks = legal_scrim_candidates(
        after_bans, ["甲1-0", "全新英雄"], bo="BO3", game_number=2,
        blue_team="甲", red_team="乙", series_used_by_team=used)
    assert "甲1-0" not in picks


def test_history_gaps_and_repeat_picks_must_fail_closed():
    with pytest.raises(ValueError):
        build_series_used([], bo="BO5", game_number=3, teams=("甲", "乙"))
    with pytest.raises(ValueError):
        legal_scrim_candidates([], ["英雄"], bo="BO3", game_number=2)
    history = [_previous(1), _previous(2)]
    history[1]["picks"]["甲"][0] = history[0]["picks"]["甲"][0]
    with pytest.raises(ValueError):
        build_series_used(history, bo="BO5", game_number=3, teams=("甲", "乙"))


def test_global_history_up_to_bo7_last_game_and_player_assignment():
    history = [_previous(i) for i in range(1, 7)]
    used = build_series_used(history, bo="BO7", game_number=7,
                             teams=("甲", "乙"))
    assert len(used["甲"]) == len(used["乙"]) == 30
    all_pools = [{"花木兰"}, {"镜"}, {"小乔"}, {"孙尚香"}, {"张飞"}]
    result = legal_scrim_candidates(
        full_scrim_actions()[:5],
        ["花木兰", "镜", "小乔", "孙尚香", "张飞", "马超"],
        blue_player_pools=all_pools, bo="BO7", game_number=7,
        blue_team="甲", red_team="乙", series_used_by_team=used)
    assert result == BLUE_PICKS
    assert can_assign_to_players(["花木兰", "镜"], all_pools)
    assert not can_assign_to_players(["花木兰", "马超"], all_pools)


def test_invalid_candidate_rejected_during_transition():
    with pytest.raises(ValueError):
        append_legal_scrim_action(
            full_scrim_actions()[:5], "大乔",
            ["大乔", "镜"])
