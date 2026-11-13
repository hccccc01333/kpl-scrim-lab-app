"""BP-process join is strict: no cross-game timelines, inferred lanes or fake gold."""
from copy import deepcopy

from bp_intelligence import build_report
from bp_process import (_gold_diff, _interpolate, _snapshot_golds,
                        link_scrim_process, process_match)

OWN = ["夏洛特", "镜", "小乔", "公孙离", "鲁班大师"]
FOE = ["马超", "赵云", "沈梦溪", "孙尚香", "张飞"]
LANES = ["对抗路", "打野", "中路", "发育路", "游走"]


def bp_row(i=1, day="2026-11-02", result="win"):
    return {
        "key": str(i), "day": day, "start": day + " 10:00:00",
        "duration": 1300, "side": "blue", "ownSide": "left",
        "opponent": "对手A", "result": result,
        "picks": {
            "own": [{"name": h} for h in OWN],
            "enemy": [{"name": h} for h in FOE],
        },
        "bans": {"own": [], "enemy": []},
        "roster": {"own": [{"name": "选手A" + str(j), "hero": h, "lane": LANES[j]}
                          for j, h in enumerate(OWN)],
                   "enemy": [{"name": "选手B" + str(j), "hero": h, "lane": LANES[j]}
                             for j, h in enumerate(FOE)]},
    }


def replay(key="channel-1", day="2026-11-02"):
    players = []
    for camp, heroes in (("blue", OWN), ("red", FOE)):
        for i, hero in enumerate(heroes):
            players.append({"camp": camp, "hero": hero, "position": LANES[i]})
    snapshots = []
    for time in (240, 600):
        rows = []
        for camp, heroes in (("blue", OWN), ("red", FOE)):
            for i, hero in enumerate(heroes):
                gold = (2000 if time == 240 else 5100) + i * 100
                if camp == "blue":
                    gold += 300 if time == 240 else 800
                rows.append({"camp": camp, "hero": hero, "totalGold": gold})
        snapshots.append({"gameTime": time, "players": rows})
    return {
        "key": key, "date": day, "duration": 1300, "ownCamp": "blue",
        "players": players,
        "process": {
            "timeline": [
                {"gameTime": 0, "blueGold": 2000, "redGold": 2000},
                {"gameTime": 120, "blueGold": 4900, "redGold": 4600},
                {"gameTime": 240, "blueGold": 8100, "redGold": 7400},
                {"gameTime": 600, "blueGold": 23300, "redGold": 21400},
            ],
            "scoreboardSnapshots": snapshots,
        },
    }


def test_strict_match_returns_true_match_key_and_gold():
    result = link_scrim_process([bp_row()], [replay()])
    assert list(result) == ["1"]
    assert result["1"]["matchKey"] == "channel-1"
    assert result["1"]["teamDiffOwn"]["240"] == 700
    assert result["1"]["teamDiffOwn"]["600"] == 1900
    assert result["1"]["laneDiffByHero"]["240"]["夏洛特"] == 300
    assert result["1"]["laneDiffByHero"]["600"]["马超"] == -800


def test_same_day_different_camp_or_lineup_never_match():
    red = replay()
    red["ownCamp"] = "red"
    wrong = replay()
    wrong["players"][0]["hero"] = "杨玉环"
    date = replay(day="2026-11-03")
    assert link_scrim_process([bp_row()], [red, wrong, date]) == {}


def test_duplicate_candidates_are_ambiguous_no_join():
    assert link_scrim_process([bp_row()], [replay("channel-1"), replay("channel-2")]) == {}


def test_duration_disagreement_rejected():
    item = replay()
    item["duration"] = 1500
    assert link_scrim_process([bp_row()], [item]) == {}


def test_sparse_and_out_of_range_points_do_not_invent_economy():
    assert _interpolate([(0, 0), (600, 3000)], 240) is None
    assert _interpolate([(120, 30), (180, 130)], 240) is None
    assert _interpolate([(120, 30), (180, 130)], 150) == 80
    assert _gold_diff({"ownCamp": "blue", "duration": 700, "process": {
        "timeline": [{"gameTime": 0, "blueGold": 100, "redGold": 100},
                     {"gameTime": 700, "blueGold": 9999, "redGold": 1000}]
    }}, "blue")["240"] is None


def test_missing_snapshot_or_unknown_lane_does_not_infer_player_gold():
    item = replay()
    item["process"]["scoreboardSnapshots"] = []
    assert process_match(item)["laneDiffByHero"]["240"] == {}
    item = replay()
    for row in item["players"]:
        row["position"] = ""
    assert process_match(item)["laneDiffByHero"]["240"] == {}


def test_conflicting_equal_distance_snapshots_are_rejected():
    item = replay()
    item["process"]["scoreboardSnapshots"] = [
        {"gameTime": 230, "players": [{"camp": "blue", "hero": "夏洛特", "totalGold": 1000}]},
        {"gameTime": 250, "players": [{"camp": "blue", "hero": "夏洛特", "totalGold": 3000}]},
    ]
    assert _snapshot_golds(item, 240) == {}


def test_frontend_evidence_uses_replay_key_not_scrim_seq():
    bps = [bp_row(i, day="2026-11-02" if i<4 else "2026-11-03") for i in range(1, 8)]
    linked = link_scrim_process([bps[0]], [replay()])
    report = build_report(bps, [], source="scrim", team="本队", process_map=linked)
    assert report["scope"]["games"] == 7
    assert report["processStudy"]["linkedGames"] == 1
    stage = report["processStudy"]["checkpoints"]["240"]
    assert stage["games"] == 1 and stage["meanDiff"] == 700
    assert stage["evidence"][0]["processMatchKey"] == "channel-1"
    assert report["processStudy"]["playerLanes"][0]["n4"] == 1


def test_process_coverage_avoids_team_gold_as_player_laning():
    bps = [bp_row(i, day="2026-11-02") for i in range(1, 5)]
    item = replay()
    item["process"]["scoreboardSnapshots"] = []
    linked = link_scrim_process([bps[0]], [item])
    report = build_report(bps, [], source="scrim", team="本队", process_map=linked)
    assert report["processStudy"]["checkpoints"]["240"]["games"] == 1
    assert not report["processStudy"]["playerLanes"]


def test_hero_win_rate_changes_are_conditions_not_causal_attribution():
    rows = []
    for i in range(1, 13):
        day = "2026-11-02" if i <= 6 else "2026-11-08"
        win = i <= 5 or i == 7
        item = bp_row(i, day=day, result="win" if win else "loss")
        if i > 6:
            item["picks"]["own"][1] = {"name": "兰陵王"}
            item["roster"]["own"][1]["hero"] = "兰陵王"
        rows.append(item)
    report = build_report(rows, [], source="scrim", team="本队")
    shifts = report["heroWinShifts"]
    row = next(r for r in shifts if r["hero"] == "夏洛特")
    assert row["previousGames"] == 6 and row["recentGames"] == 6
    assert row["previousWinRate"] > row["recentWinRate"]
    assert any(x["hero"] == "兰陵王" and x["changePP"] > 0 for x in row["partnerChanges"])
    assert "cause" not in row


def test_unverified_replay_stays_unlinked_and_does_not_create_misleading_values():
    rows = [bp_row(1)]
    data = link_scrim_process(rows, [replay(day="2026-11-04")])
    report = build_report(rows, [], source="scrim", team="本队", process_map=data)
    assert report["processStudy"]["linkedGames"] == 0
    assert report["processStudy"]["checkpoints"]["240"]["meanDiff"] is None
    assert not report["processStudy"]["playerLanes"]


def test_complete_five_hero_lineup_has_count_and_wilson_interval():
    data = [bp_row(i, result="win" if i < 3 else "loss") for i in range(1, 5)]
    report = build_report(data, [], source="scrim", team="本队")
    lineup = next(row for row in report["fullLineups"]
                  if set(row["heroes"]) == set(OWN))
    assert lineup["games"] == 4 and lineup["wins"] == 2
    assert lineup["interval"][0] < 50 < lineup["interval"][1]
    assert lineup["evidence"][0]["id"] == "4"


def test_ban_followup_uses_only_actual_ordered_actions():
    bans_a = ["吕布", "亚连"]
    bans_b = ["关羽", "朵莉亚"]
    events = []
    draft = [
        ("1", "ban", bans_a[0]), ("2", "ban", bans_b[0]),
        ("1", "ban", bans_a[1]), ("2", "ban", bans_b[1]),
        ("2", "pick", FOE[0]), ("1", "pick", OWN[0]),
        ("1", "pick", OWN[1]), ("2", "pick", FOE[1]),
        ("1", "pick", OWN[2]), ("2", "pick", FOE[2]),
        ("1", "pick", OWN[3]), ("2", "pick", FOE[3]),
        ("1", "pick", OWN[4]), ("2", "pick", FOE[4]),
    ]
    for order, (camp, action, hero) in enumerate(draft, 1):
        events.append({"order": order, "camp": camp, "action": action, "hero": hero})
    games = []
    for i in range(3):
        games.append({
            "battleId": "battle-" + str(i), "date": "2026-11-02",
            "camp1": {"team": "战队A"}, "camp2": {"team": "战队B"},
            "picks": {"1": OWN, "2": FOE},
            "bans": {"1": bans_a, "2": bans_b},
            "bansKnown": True, "pickOrderKnown": True,
            "draftEvents": events, "winCamp": 1,
        })
    report = build_report([], games, source="kpl", team="战队A")
    assert next(x for x in report["banResponses"] if x["trigger"] == bans_b[0])[
        "response"] == OWN[0]
    assert report["banResponses"][0]["games"] == 3
    games[0]["pickOrderKnown"] = False
    report = build_report([], games, source="kpl", team="战队A")
    assert report["banResponses"][0]["games"] == 2


def test_whole_league_view_does_not_assign_one_team_laning_or_trend():
    rows = [bp_row(i) for i in range(1, 15)]
    report = build_report(rows, [], source="scrim", team="")
    assert report["processStudy"]["linkedGames"] == 0
    assert report["heroWinShifts"] == []
