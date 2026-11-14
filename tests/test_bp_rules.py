"""Training-scrim rules and KPL data must never use each other's format."""
import pytest

from bp_rules import (
    SCRIM_18_SCHEDULE,
    can_assign_to_players,
    legal_scrim_candidates,
    next_scrim_action,
    profile_for,
    validate_scrim_prefix,
)
from bp_intelligence import build_report, normalize_kpl, normalize_scrims


BLUE_PICKS = ["花木兰", "镜", "小乔", "孙尚香", "张飞"]
RED_PICKS = ["马超", "暃", "沈梦溪", "狄仁杰", "太乙真人"]
BLUE_BANS = ["大乔", "朵莉亚", "鲁班大师", "少司缘"]
RED_BANS = ["亚连", "吕布", "关羽", "东皇太一"]


def full_scrim_actions():
    queues = {
        ("pick", "1"): iter(BLUE_PICKS),
        ("pick", "2"): iter(RED_PICKS),
        ("ban", "1"): iter(BLUE_BANS),
        ("ban", "2"): iter(RED_BANS),
    }
    return [{"order": i + 1, "action": action, "camp": camp,
             "hero": next(queues[(action, camp)])}
            for i, (action, camp) in enumerate(SCRIM_18_SCHEDULE)]


def scrim(events=None, rule="scrim-staged-18"):
    return [{
        "key": "scrim-001",
        "day": "2026-11-14",
        "ownSide": "left",
        "opponent": "对手战队",
        "result": "win",
        "ruleProfile": rule,
        "picks": {"own": BLUE_PICKS, "enemy": RED_PICKS},
        "bans": {"own": BLUE_BANS, "enemy": RED_BANS},
        "draftEvents": full_scrim_actions() if events is None else events,
    }]


def test_training_scrim_has_precisely_four_stages_and_18_events():
    assert len(SCRIM_18_SCHEDULE) == 18
    assert list(SCRIM_18_SCHEDULE[:4]) == [
        ("ban", "1"), ("ban", "2"), ("ban", "1"), ("ban", "2")]
    assert list(SCRIM_18_SCHEDULE[4:10]) == [
        ("pick", "1"), ("pick", "2"), ("pick", "2"),
        ("pick", "1"), ("pick", "1"), ("pick", "2")]
    assert list(SCRIM_18_SCHEDULE[10:14]) == [
        ("ban", "2"), ("ban", "1"), ("ban", "2"), ("ban", "1")]
    assert list(SCRIM_18_SCHEDULE[14:]) == [
        ("pick", "2"), ("pick", "1"), ("pick", "1"), ("pick", "2")]
    assert validate_scrim_prefix(full_scrim_actions(), full=True)
    assert next_scrim_action(full_scrim_actions()) is None
    assert next_scrim_action(full_scrim_actions()[:4]) == {
        "order": 5, "action": "pick", "camp": "1", "phase": 2}


def test_scrim_wrong_turn_and_duplicate_hero_both_rejected():
    actions = full_scrim_actions()
    changed = [dict(e) for e in actions]
    changed[0]["camp"] = "2"
    assert not validate_scrim_prefix(changed, full=True)
    changed = [dict(e) for e in actions]
    changed[5]["hero"] = changed[4]["hero"]
    assert not validate_scrim_prefix(changed, full=True)
    with pytest.raises(ValueError):
        next_scrim_action(changed[:6])


def test_normalized_scrim_validated_from_both_team_perspectives():
    games = normalize_scrims(scrim())
    assert len(games) == 2
    assert {g["team"] for g in games} == {"本队", "对手战队"}
    assert all(g["ruleProfile"] == "scrim-staged-18" for g in games)
    assert all(g["ruleValidated"] for g in games)
    assert all(len(g["events"]) == 18 for g in games)
    report = build_report(scrim(), [], source="scrim", team="本队")
    assert report["bpStudies"]["ruleCoverage"]["scrim18"] == 1
    assert report["bpStudies"]["ruleCoverage"]["kplRecorded"] == 0


def test_inconsistent_declared_scrim_rule_never_passes():
    actions = full_scrim_actions()
    changed = [dict(e) for e in actions]
    changed[5], changed[6] = changed[6], changed[5]
    changed = [dict(e, order=i + 1) for i, e in enumerate(changed)]
    # A swap within the same two-red Pick phase is still a valid stage order;
    # a blue/red swap across turns is not.
    changed[4], changed[5] = changed[5], changed[4]
    changed = [dict(e, order=i + 1) for i, e in enumerate(changed)]
    games = normalize_scrims(scrim(changed))
    assert all(not g["ruleValidated"] for g in games)
    assert all(not g["events"] for g in games)
    assert all(g["ruleProfile"] == "scrim-unconfirmed" for g in games)


def test_other_scrim_sequences_remain_usable_as_lineup_facts_only():
    # Shorter historic practice recordings may still be correct for their
    # own format, but cannot be asserted to follow this particular schedule.
    events = full_scrim_actions()[:10] + full_scrim_actions()[14:]
    games = normalize_scrims(scrim(events, rule=""))
    assert all(not g["ruleValidated"] for g in games)
    assert all(g["ruleProfile"] == "scrim-unconfirmed" for g in games)
    assert all(len(g["picks"]) == 5 for g in games)


def test_kpl_records_are_not_validated_against_scrim_schedule():
    # This historical KPL sample intentionally has 2 bans per side
    # (not the 18-event practice schedule).
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
    games = normalize_kpl(rows)
    assert len(games) == 2
    assert all(len(g["events"]) == 14 for g in games)
    assert all(g["ruleProfile"] == "kpl-recorded" for g in games)
    assert all(not g["ruleValidated"] for g in games)
    report = build_report([], rows, source="kpl", team="战队甲")
    assert report["scope"]["orderedGames"] == 1
    assert report["bpStudies"]["ruleCoverage"]["kplRecorded"] == 1
    assert report["bpStudies"]["ruleCoverage"]["scrim18"] == 0


def test_kpl_cannot_request_scrim_rule():
    assert not profile_for("kpl").configured
    assert profile_for("scrim").configured
    with pytest.raises(ValueError):
        profile_for("kpl", "scrim-staged-18")
    with pytest.raises(ValueError):
        profile_for("scrim", "kpl-recorded")


def test_search_filters_used_heroes_series_exclusions_and_player_pool():
    actions = full_scrim_actions()[:4]
    available = ["花木兰", "镜", "小乔", "孙尚香", "张飞",
                 "马超", "大乔", "后羿"]
    # One player per hero, one hero per player, all five player pools known.
    five_pools = [{"花木兰"}, {"镜"}, {"小乔"},
                  {"孙尚香"}, {"张飞"}]
    actual = legal_scrim_candidates(actions, available,
                                    blue_player_pools=five_pools,
                                    series_unavailable={"马超"})
    assert actual == BLUE_PICKS
    assert "大乔" not in actual
    assert "马超" not in actual
    assert "后羿" not in actual
    assert can_assign_to_players(["花木兰", "镜"], five_pools)
    assert not can_assign_to_players(["花木兰", "后羿"], five_pools)
    assert not can_assign_to_players(["花木兰"] * 2, five_pools)
