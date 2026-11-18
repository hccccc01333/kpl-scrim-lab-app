"""三套 BP 格式、身份口径、全局 BP 与巅峰对决的规则测试。"""
import pytest

from bp_formats import (
    BLIND, DRAFT_18, DRAFT_20, RANK_20, FORMATS,
    check_draft, decider_applies, get_format, legal_candidates,
    next_action, pick_key, ban_key, resolve_format, series_used,
)


def build(fmt, blue_picks, red_picks, blue_bans, red_bans):
    """按格式排程把每方队列铺成逐手事件。"""
    picks = {"1": iter(blue_picks), "2": iter(red_picks)}
    bans = {"1": iter(blue_bans), "2": iter(red_bans)}
    rows = []
    for step in fmt.schedule:
        queue = bans if step["action"] == "ban" else picks
        rows.append({"order": step["order"], "phase": step["phase"],
                     "action": step["action"], "camp": step["camp"],
                     "hero": next(queue[step["camp"]]),
                     "parallel": step["parallel"]})
    return rows


BLUE_PICKS = ["花木兰", "镜", "小乔", "孙尚香", "张飞"]
RED_PICKS = ["马超", "暃", "沈梦溪", "狄仁杰", "太乙真人"]
BLUE_BANS_4 = ["大乔", "朵莉亚", "鲁班大师", "司空震"]
RED_BANS_4 = ["亚连", "吕布", "公孙离", "蔡文姬"]
BLUE_BANS_5 = BLUE_BANS_4 + ["嬴政"]
RED_BANS_5 = RED_BANS_4 + ["金蝉"]


def test_three_formats_have_expected_counts():
    assert (DRAFT_18.total_hands, DRAFT_18.bans_per_side, DRAFT_18.picks_per_side) == (
        18, {"1": 4, "2": 4}, {"1": 5, "2": 5})
    assert (DRAFT_20.total_hands, DRAFT_20.bans_per_side, DRAFT_20.picks_per_side) == (
        20, {"1": 5, "2": 5}, {"1": 5, "2": 5})
    assert (RANK_20.total_hands, RANK_20.bans_per_side, RANK_20.picks_per_side) == (
        20, {"1": 5, "2": 5}, {"1": 5, "2": 5})
    assert set(FORMATS) == {"draft-18", "draft-20", "rank-20", "blind"}


def test_draft18_schedule_matches_historical_kpl():
    assert [(row["action"], row["camp"]) for row in DRAFT_18.schedule] == [
        ("ban", "1"), ("ban", "2"), ("ban", "1"), ("ban", "2"),
        ("pick", "1"), ("pick", "2"), ("pick", "2"),
        ("pick", "1"), ("pick", "1"), ("pick", "2"),
        ("ban", "2"), ("ban", "1"), ("ban", "2"), ("ban", "1"),
        ("pick", "2"), ("pick", "1"), ("pick", "1"), ("pick", "2"),
    ]


def test_draft20_schedule_matches_current_kpl():
    assert [(row["action"], row["camp"]) for row in DRAFT_20.schedule] == [
        ("ban", "1"), ("ban", "2"), ("ban", "1"), ("ban", "2"),
        ("pick", "1"), ("pick", "2"), ("pick", "2"),
        ("pick", "1"), ("pick", "1"), ("pick", "2"),
        ("ban", "2"), ("ban", "1"), ("ban", "2"),
        ("ban", "1"), ("ban", "2"), ("ban", "1"),
        ("pick", "2"), ("pick", "1"), ("pick", "1"), ("pick", "2"),
    ]


def test_rank20_has_parallel_bans_then_snake_picks():
    bans = [row for row in RANK_20.schedule if row["action"] == "ban"]
    picks = [row for row in RANK_20.schedule if row["action"] == "pick"]
    assert len(bans) == 10 and all(row["parallel"] for row in bans)
    assert [row["camp"] for row in picks] == ["1", "2", "2", "1", "1", "2", "2", "1", "1", "2"]
    assert all(not row["parallel"] for row in picks)


def test_full_drafts_are_legal():
    for fmt, blue_bans, red_bans in (
            (DRAFT_18, BLUE_BANS_4, RED_BANS_4),
            (DRAFT_20, BLUE_BANS_5, RED_BANS_5),
            (RANK_20, BLUE_BANS_5, RED_BANS_5)):
        events = build(fmt, BLUE_PICKS, RED_PICKS, blue_bans, red_bans)
        result = check_draft(events, fmt)
        assert result["ok"], result["errors"]
        assert result["completed"] == fmt.total_hands
        assert next_action(events, fmt) is None


def test_draft_rejects_cross_side_duplicate_ban_but_rank_allows_it():
    events = build(DRAFT_18, BLUE_PICKS, RED_PICKS,
                   ["大乔", "朵莉亚", "鲁班大师", "司空震"],
                   ["大乔", "吕布", "公孙离", "蔡文姬"])
    result = check_draft(events, DRAFT_18)
    assert not result["ok"] and any("跨方重复 Ban" in e for e in result["errors"])

    rank = build(RANK_20, BLUE_PICKS, RED_PICKS,
                 ["大乔", "朵莉亚", "鲁班大师", "司空震", "嬴政"],
                 ["大乔", "吕布", "公孙离", "蔡文姬", "金蝉"])
    assert check_draft(rank, RANK_20)["ok"]


def test_yuanliu_ban_is_form_but_pick_is_one_hero():
    # Ban 坦克，Pick 射手：合法（Ban 按形态）。
    allowed = build(DRAFT_18, BLUE_PICKS, ["元流之子(射手)"] + RED_PICKS[:4],
                    ["元流之子(坦克)", "朵莉亚", "鲁班大师", "司空震"], RED_BANS_4)
    assert check_draft(allowed, DRAFT_18)["ok"]

    # Ban 坦克，Pick 坦克：非法（同一形态）。
    same = build(DRAFT_18, BLUE_PICKS, ["元流之子(坦克)"] + RED_PICKS[:4],
                 ["元流之子(坦克)", "朵莉亚", "鲁班大师", "司空震"], RED_BANS_4)
    result = check_draft(same, DRAFT_18)
    assert not result["ok"] and any("已 Ban 的形态" in e for e in result["errors"])

    # 双方 Pick 不同形态：非法（Pick 按一个英雄）。
    both = build(DRAFT_18, ["元流之子(坦克)"] + BLUE_PICKS[:4],
                 ["元流之子(射手)"] + RED_PICKS[:4], BLUE_BANS_4, RED_BANS_4)
    result = check_draft(both, DRAFT_18)
    assert not result["ok"] and any("重复 Pick" in e for e in result["errors"])

    # 同一方 Ban 两个不同形态：合法（不同 Ban key）。
    two_bans = build(DRAFT_18, BLUE_PICKS, RED_PICKS,
                     ["元流之子(坦克)", "元流之子(射手)", "鲁班大师", "司空震"],
                     RED_BANS_4)
    assert check_draft(two_bans, DRAFT_18)["ok"]


def test_blind_allows_shared_picks_and_has_no_bans():
    events = build(BLIND, BLUE_PICKS, ["元流之子(坦克)"] + RED_PICKS[:4], [], [])
    assert check_draft(events, BLIND)["ok"]
    both = build(BLIND, BLUE_PICKS, BLUE_PICKS, [], [])
    assert check_draft(both, BLIND)["ok"]
    assert next_action([], BLIND) == {
        "order": None, "phase": "decider", "action": "pick", "parallel": False,
        "blind": True, "camps": ["1", "2"], "remaining": {"1": 5, "2": 5}}


def test_next_action_sequential_and_parallel():
    assert next_action([], DRAFT_18) == {
        "order": 1, "phase": "ban1", "action": "ban", "camp": "1",
        "parallel": False, "blind": False}
    rows = build(DRAFT_18, BLUE_PICKS, RED_PICKS, BLUE_BANS_4, RED_BANS_4)[:4]
    assert next_action(rows, DRAFT_18)["order"] == 5
    assert next_action(rows, DRAFT_18)["action"] == "pick"

    rank = next_action([], RANK_20)
    assert rank["parallel"] and rank["camps"] == ["1", "2"]
    assert rank["remaining"] == {"1": 5, "2": 5}
    rank_rows = build(RANK_20, BLUE_PICKS, RED_PICKS, BLUE_BANS_5, RED_BANS_5)[:3]
    nxt = next_action(rank_rows, RANK_20)
    assert nxt["camps"] == ["1", "2"]
    assert nxt["remaining"] == {"1": 2, "2": 5}
    after_blue = build(RANK_20, BLUE_PICKS, RED_PICKS, BLUE_BANS_5, RED_BANS_5)[:5]
    assert next_action(after_blue, RANK_20)["camps"] == ["2"]


def test_series_used_locks_all_yuanliu_forms():
    history = [{"game": 1, "picks": {
        "甲": ["元流之子(坦克)", "花木兰", "镜", "小乔", "孙尚香"],
        "乙": ["马超", "暃", "沈梦溪", "狄仁杰", "太乙真人"]}}]
    used = series_used(history, teams=("甲", "乙"), bo="BO3", game_number=2)
    assert "元流之子" in used["甲"]
    assert "元流之子" not in used["乙"]

    pool = ["元流之子(坦克)", "元流之子(射手)", "元流之子(法师)", "新英雄"]
    after_bans = build(DRAFT_18, BLUE_PICKS, RED_PICKS,
                       BLUE_BANS_4, RED_BANS_4)[:4]
    first_pick = legal_candidates(after_bans, DRAFT_18, pool, camp="1",
                                  used_pick_keys=used["甲"])
    assert "新英雄" in first_pick
    assert not any(pick_key(hero) == "元流之子" for hero in first_pick)

    after_blue_pick = after_bans + [
        {"order": 5, "phase": "pick1", "action": "pick", "camp": "1", "hero": "新英雄"}]
    opponent_pick = legal_candidates(after_blue_pick, DRAFT_18, pool, camp="2",
                                     used_pick_keys=used["乙"])
    assert "元流之子(射手)" in opponent_pick

    # 系列赛内同队复用任一形态：拒绝。
    replay = [{"game": 1, "picks": {
        "甲": ["元流之子(坦克)", "花木兰", "镜", "小乔", "孙尚香"],
        "乙": ["马超", "暃", "沈梦溪", "狄仁杰", "太乙真人"]}},
              {"game": 2, "picks": {
        "甲": ["元流之子(射手)", "A", "B", "C", "D"],
        "乙": ["E", "F", "G", "H", "I"]}}]
    with pytest.raises(ValueError, match="复用"):
        series_used(replay, teams=("甲", "乙"), bo="BO5", game_number=3)


def test_series_history_must_be_complete():
    with pytest.raises(ValueError):
        series_used([], teams=("甲", "乙"), bo="BO5", game_number=3)
    with pytest.raises(ValueError):
        series_used([{"game": 2, "picks": {}}], teams=("甲", "乙"),
                    bo="BO3", game_number=3)


def test_decider_only_bo7_game_seven():
    assert decider_applies(DRAFT_20, mode="kpl", bo="BO7", game_number=7)
    assert not decider_applies(DRAFT_20, mode="kpl", bo="BO5", game_number=5)
    assert not decider_applies(DRAFT_20, mode="kpl", bo="BO7", game_number=6)
    assert not decider_applies(DRAFT_20, mode="kpl", bo="BO7", game_number=7,
                               score=(3, 2))
    assert not decider_applies(DRAFT_18, mode="scrim", bo="BO7", game_number=7)
    assert decider_applies(DRAFT_18, mode="scrim", bo="BO7", game_number=7,
                           override=True)
    assert not decider_applies(RANK_20, mode="rank", bo="BO7", game_number=7)


def test_resolve_format_by_source_bans_and_map_name():
    assert resolve_format(source="scrim").id == "draft-18"
    assert resolve_format(source="kpl", bans_per_side=4).id == "draft-18"
    assert resolve_format(source="kpl", bans_per_side=5).id == "draft-20"
    assert resolve_format(map_name="排位赛 双排", bans_per_side=5).id == "rank-20"
    assert resolve_format(map_name="巅峰赛", bans_per_side=5).id == "rank-20"
    assert resolve_format(blind=True).id == "blind"
    assert resolve_format(explicit="draft-20").id == "draft-20"
    with pytest.raises(ValueError):
        resolve_format(explicit="scrim-global-20")


def test_record_mode_allows_order_deviation_but_strict_rejects():
    events = build(DRAFT_18, BLUE_PICKS, RED_PICKS, BLUE_BANS_4, RED_BANS_4)
    swapped = [dict(row) for row in events]
    swapped[0], swapped[1] = swapped[1], swapped[0]
    swapped = [dict(row, order=index + 1) for index, row in enumerate(swapped)]
    assert not check_draft(swapped, DRAFT_18, strict=True)["ok"]
    record = check_draft(swapped, DRAFT_18, strict=False)
    assert record["ok"], record["errors"]


def test_ban_after_pick_is_rejected_in_strict_draft():
    events = build(DRAFT_18, BLUE_PICKS, RED_PICKS, BLUE_BANS_4, RED_BANS_4)
    # 第 11 手是 red 的第二轮 Ban；把它换成 red 第一轮 Pick 的同一英雄形态。
    changed = [dict(row) for row in events]
    changed[10]["hero"] = "元流之子(射手)"
    changed[5]["hero"] = "元流之子(射手)"
    result = check_draft(changed, DRAFT_18, strict=True)
    assert not result["ok"]
