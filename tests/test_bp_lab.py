"""BP 概览十区：英雄/组合/选禁条件/对抗/稳定性/方案纯计算回归。"""
from __future__ import annotations

import bp_lab

LANES = ("对抗路", "打野", "中路", "发育路", "游走")
H1 = ["夏洛特", "镜", "小乔", "公孙离", "鲁班大师"]
H2 = ["马超", "赵云", "沈梦溪", "孙尚香", "张飞"]
B1 = ["吕布", "亚连", "关羽", "朵莉亚", "海月"]
B2 = ["廉颇", "盾山", "鲁班七号", "狄仁杰", "王昭君"]


def _players(team, heroes, offset=0):
    return [{"name": f"{team}-{offset + i}", "hero": hero, "lane": LANES[i]}
            for i, hero in enumerate(heroes)]


def game(i, *, team="战队A", enemy="战队B", date="2026-01-01",
         picks=None, enemy_picks=None, bans=None, enemy_bans=None,
         result=True, source="kpl", league="2026KPL春季赛", stage="常规赛",
         order=True):
    picks = picks or H1
    enemy_picks = enemy_picks or H2
    bans = bans or B1
    enemy_bans = enemy_bans or B2
    return {
        "id": f"{source}-{date}-{team}-{enemy}-{i}",
        "date": date, "team": team, "enemy": enemy, "source": source, "side": "1",
        "league": league, "stage": stage, "matchId": f"m-{i}",
        "picks": list(picks), "bans": list(bans),
        "enemyPicks": list(enemy_picks), "enemyBans": list(enemy_bans),
        "players": _players(team, picks), "enemyPlayers": _players(enemy, enemy_picks),
        "result": result, "events": [], "version": "",
        "bpMode": "full" if order else "scrim",
        "pickOrderKnown": order, "bansKnown": True, "gameSeq": i,
    }


def both(i, **kwargs):
    """一局两个视角；真实归一化数据也是每局两条队-局记录。"""
    first = game(i, **kwargs)
    second = game(
        i, team=first["enemy"], enemy=first["team"],
        picks=first["enemyPicks"], enemy_picks=first["picks"],
        bans=first["enemyBans"], enemy_bans=first["bans"],
        result=(None if first["result"] is None else not first["result"]),
        date=first["date"], source=first["source"], league=first["league"],
        stage=first["stage"], order=first["pickOrderKnown"],
    )
    second["id"] = first["id"]
    second["matchId"] = first["matchId"]
    second["side"] = "2"
    return [first, second]


def test_hero_board_rates_and_lane():
    games = [
        game(1, result=True),
        game(2, result=True),
        game(3, result=False),
    ]
    board = bp_lab.hero_board(games)
    row = next(item for item in board["rows"] if item["hero"] == "夏洛特")
    assert row["picks"] == 3
    assert row["pickRate"] == 100.0
    assert row["winRate"] == 66.7
    assert row["lane"] == "对抗路"
    assert board["byLane"]["对抗路"]
    assert board["laneBoard"][0]["hero"] == "夏洛特"


def test_combo_board_pairs_use_team_game_denominator():
    games = [
        game(1, result=True),
        game(2, result=False),
        game(3, picks=["小乔", "项羽", "镜", "公孙离", "张飞"], enemy_picks=H1,
             result=True),
    ]
    combos = bp_lab.combo_board(games)
    pair = next(row for row in combos["pairs"] if set(row["heroes"]) == {"夏洛特", "镜"})
    assert pair["games"] == 2
    assert pair["share"] == 66.7
    assert pair["wins"] == 1 and pair["decided"] == 2
    assert combos["spotlight"] is None


def test_draft_habits_conditional_first_pick_and_scrim_order_gate():
    games = [
        game(1, picks=["少司缘", "镜", "小乔", "公孙离", "鲁班大师"],
             enemy_bans=["鲁班大师", "亚连", "关羽", "朵莉亚", "海月"], result=True),
        game(2, picks=["少司缘", "镜", "小乔", "公孙离", "鲁班大师"],
             enemy_bans=["鲁班大师", "亚连", "关羽", "朵莉亚", "海月"], result=True),
        game(3, picks=["敖隐", "镜", "小乔", "公孙离", "鲁班大师"],
             enemy_bans=["鲁班大师", "亚连", "关羽", "朵莉亚", "海月"], result=False),
    ]
    habits = bp_lab.draft_habits(games, "战队A")
    assert habits["available"] is True
    assert habits["orderGames"] == 3
    response = next(row for row in habits["banResponses"] if row["ban"] == "鲁班大师")
    assert response["games"] == 3
    assert response["options"][0]["hero"] == "少司缘"
    assert response["options"][0]["count"] == 2
    scrim = bp_lab.draft_habits(
        [game(4, source="scrim", order=False, picks=H1)], "战队A")
    assert scrim["orderGames"] == 0
    assert scrim["firstPicks"] == []
    assert scrim["banResponses"] == []


def test_team_counters_ban_rate_and_response_picks():
    games = [
        game(1, picks=["夏洛特", "镜", "小乔", "公孙离", "鲁班大师"],
             enemy_picks=["马超", "赵云", "沈梦溪", "孙尚香", "张飞"],
             bans=["马超", "亚连", "关羽", "朵莉亚", "海月"], result=True),
        game(2, picks=["夏洛特", "镜", "小乔", "公孙离", "鲁班大师"],
             enemy_picks=["马超", "赵云", "沈梦溪", "孙尚香", "张飞"],
             bans=["廉颇", "亚连", "关羽", "朵莉亚", "海月"], result=False),
    ]
    report = bp_lab.team_counters(games, ["马超", "赵云"])
    assert report["available"] is True
    row = report["rows"][0]
    assert row["team"] == "战队A"
    assert row["games"] == 2
    assert row["banGames"] == 1
    assert row["banRate"] == 50.0
    assert row["responseHeroes"][0]["hero"] in {"夏洛特", "镜", "小乔", "公孙离", "鲁班大师"}


def test_lookup_uses_target_team_not_opponent():
    games = []
    for i in range(1, 4):
        games += both(i, result=i < 3)
    report = bp_lab.lookup(games, ["小乔"])
    assert report["available"] is True
    assert report["summary"]["games"] == 3
    assert report["summary"]["teams"] == 1
    assert report["evidence"][0]["team"] == "战队A"
    assert report["evidence"][0]["ownPicks"]


def test_combo_stability_needs_three_windows():
    games = []
    for month, wins in (("2026-01", 3), ("2026-02", 3), ("2026-03", 3)):
        for index in range(4):
            games.append(game(index, date=f"{month}-0{index + 1}",
                              result=index < wins))
    report = bp_lab.combo_stability(games, ["夏洛特", "镜"], "month", available=[])
    assert report["available"] is True
    assert report["validWindows"] == 3
    assert report["verdict"] == "稳定"
    assert report["rangePP"] == 0.0


def test_plan_branches_and_kpl_rule():
    games = []
    for i in range(1, 4):
        games += both(i, picks=["少司缘", "镜", "小乔", "公孙离", "鲁班大师"],
                      enemy_bans=["鲁班大师", "亚连", "关羽", "朵莉亚", "海月"])
    report = bp_lab.plan(games, "战队A", "战队B", source="kpl")
    assert report["available"] is True
    assert report["rule"]["id"] == "kpl-recorded"
    branch = next(row for row in report["branches"] if row["ban"] == "鲁班大师")
    assert branch["options"]


def test_scrim_counter_rows_track_enemy_combos():
    games = []
    for i in range(1, 4):
        games += both(i, source="scrim", order=False, league="训练赛", stage="",
                      team="本队", enemy="对手X",
                      enemy_picks=["马超", "赵云", "沈梦溪", "孙尚香", "张飞"])
    report = bp_lab.scrim_systems(games)
    assert report["available"] is True
    combo = next(row for row in report["counterRows"]
                 if set(row["heroes"]) == {"马超", "赵云"})
    assert combo["games"] == 3
    assert combo["ourWinRate"] == 100.0


def test_opponent_research_four_blocks():
    games = []
    for i in range(1, 5):
        games += both(i, team="战队A", enemy="战队B", picks=H1, enemy_picks=H2,
                      result=True)
    report = bp_lab.opponent_research(games, "战队B")
    assert report["available"] is True
    assert report["games"] == 4
    assert report["comboUsage"]["pairs"]
    assert report["heroUsage"][0]["hero"] in {"马超", "赵云", "沈梦溪", "孙尚香", "张飞"}
    selected = report["comboCounters"]["combo"]
    assert selected
    assert report["comboCounters"]["rows"]
    counter = report["comboCounters"]["rows"][0]
    assert counter["opponentWinRate"] == 0.0
    assert counter["counterWinRate"] == 100.0
    hero_counter = report["heroCounters"]["rows"][0]
    assert hero_counter["opponentWinRate"] == 0.0
    # BP 局面：阵营 1 只保留该侧；第一手筛选只认逐手顺序。
    side_one = bp_lab.opponent_research(games, "战队B", side="1")
    side_two = bp_lab.opponent_research(games, "战队B", side="2")
    assert side_one["situationGames"] == 0
    assert side_two["situationGames"] == 4
    first = report["options"]["firstPicks"][0]["hero"]
    filtered = bp_lab.opponent_research(games, "战队B", first_pick=first)
    assert filtered["situationGames"] == 4


def test_scrim_simulator_legal_candidates_and_next_actor():
    pool = H1 + H2 + B1 + B2
    games = []
    for i in range(1, 4):
        games += both(i, team="战队A", enemy="战队B", picks=H1, enemy_picks=H2,
                      result=True)
    report = bp_lab.simulate_scrim({
        "rule": "scrim-global-20", "bo": "BO5", "gameNumber": 1,
        "side": "1", "team": "战队A", "opponent": "战队B", "events": [],
    }, pool, games)
    assert report["available"] is True and report["complete"] is False
    assert report["actor"] == "ours"
    assert report["nextAction"]["action"] == "ban"
    assert report["candidates"]
    assert report["branches"]
    first = report["candidates"][0]
    advanced = bp_lab.simulate_scrim({
        "rule": "scrim-global-20", "bo": "BO5", "gameNumber": 1,
        "side": "1", "team": "战队A", "opponent": "战队B",
        "events": [{"order": 1, "action": report["nextAction"]["action"],
                    "camp": report["nextAction"]["camp"], "hero": first["hero"]}],
    }, pool, games)
    assert advanced["actor"] == "opponent"
    assert advanced["nextAction"]["camp"] == "2"


def test_scrim_simulator_requires_distinct_teams():
    try:
        bp_lab.simulate_scrim({"team": "A", "opponent": "A", "events": []},
                              H1 + H2, [])
    except ValueError as error:
        assert "不同" in str(error)
    else:
        raise AssertionError("same team should be rejected")


def test_period_compare_current_previous_and_yoy():
    games = []
    for date, picks in (
        ("2026-10-10", H1), ("2026-10-11", H1),
        ("2026-09-10", H1), ("2026-09-11", H1),
        ("2025-10-10", H2), ("2025-10-11", H2),
    ):
        games += both(1, team="战队A", enemy="战队B", date=date,
                      picks=picks, enemy_picks=H2 if picks == H1 else H1)
    report = bp_lab.period_compare(games, source="kpl", team="战队A", recent_days=30)
    assert report["available"] is True
    assert report["current"]["matches"] == 2
    assert report["previous"]["matches"] == 2
    assert report["yoy"]["matches"] == 2
    row = next(item for item in report["heroes"] if item["hero"] == "夏洛特")
    assert row["pickRate"] == 100.0
    assert row["prevPickRate"] == 100.0
    assert row["yoyPickRate"] is None
    assert row["pickDelta"] == 0.0
    assert row["pickDeltaYoy"] is None


def test_build_report_keeps_sources_separate():
    kpl = []
    for i in range(1, 3):
        kpl += both(i, source="kpl")
    scrim = both(3, source="scrim", order=False, league="训练赛", stage="",
                 team="本队", enemy="对手X")
    kpl_report = bp_lab.build_report(kpl, source="kpl")
    assert kpl_report["source"] == "kpl"
    assert kpl_report["scrim"]["available"] is False
    scrim_report = bp_lab.build_report(scrim, source="scrim")
    assert scrim_report["source"] == "scrim"
    assert scrim_report["scrim"]["available"] is True
    assert scrim_report["scope"]["perSideOrder"] is False


def test_empty_inputs_are_empty_states_not_errors():
    report = bp_lab.build_report([], source="kpl")
    assert report["heroes"]["hasData"] is False
    assert report["combos"]["pairs"] == []
    assert report["teamCounters"]["available"] is False
    assert report["draftHabits"]["available"] is False
    assert report["opponent"]["available"] is False
    assert report["plan"]["available"] is False


def test_combo_detail_custom_pair_and_baseline():
    games = [
        game(1, result=True, date="2026-01-01"),
        game(2, result=False, date="2026-01-02"),
        game(3, result=True, date="2026-01-03", picks=H2, enemy_picks=H1),
        game(4, result=True, date="2026-01-04"),
    ]
    result = bp_lab.combo_detail(games, ["夏洛特", "镜"], team="战队A", recent_days=7)
    assert result["available"] is True
    assert result["games"] == 3
    assert result["wins"] == 2
    assert result["winRate"] == 66.7
    assert result["reference"] is not None
    assert result["relative"] == 9.6
    assert result["recent"][0]["games"] == 3
    assert result["recent"][0]["winRate"] == 66.7
    assert {row["hero"] for row in result["teammates"]} >= {"小乔", "公孙离", "鲁班大师"}


def test_combo_detail_team_filter_and_empty_state():
    games = [
        game(1, result=True, date="2026-01-01", team="战队A"),
        game(2, result=True, date="2026-01-02", team="战队B", enemy="战队C"),
    ]
    filtered = bp_lab.combo_detail(games, ["夏洛特", "镜"], team="战队A")
    assert filtered["games"] == 1
    assert filtered["teams"] == 1
    missing = bp_lab.combo_detail(games, ["夏洛特", "鲁班七号"], team="战队A")
    assert missing["available"] is False
    assert "没有" in missing["reason"]
