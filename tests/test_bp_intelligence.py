"""BP 研究引擎：时间窗口、事件合法性、证据、同英雄参照与来源隔离。"""
import pytest

from bp_intelligence import build_report, normalize_kpl, normalize_scrims, _wilson


H1 = ["夏洛特", "镜", "小乔", "公孙离", "鲁班大师"]
H2 = ["马超", "赵云", "沈梦溪", "孙尚香", "张飞"]
B1 = ["吕布", "亚连"]
B2 = ["关羽", "朵莉亚"]


def draft():
    events = []
    sequence = [
        (1, "ban", B1[0]), (2, "ban", B2[0]),
        (1, "ban", B1[1]), (2, "ban", B2[1]),
        (2, "pick", H2[0]), (1, "pick", H1[0]),
        (1, "pick", H1[1]), (2, "pick", H2[1]),
        (1, "pick", H1[2]), (2, "pick", H2[2]),
        (1, "pick", H1[3]), (2, "pick", H2[3]),
        (1, "pick", H1[4]), (2, "pick", H2[4]),
    ]
    for index, (camp, action, hero) in enumerate(sequence, 1):
        events.append({"order": index, "camp": str(camp), "action": action, "hero": hero})
    return events


def game(i, date="2026-11-01", full=True, winner=1):
    return {
        "battleId": f"battle-{i}", "matchId": f"series-{i // 3}",
        "date": date, "gameSeq": i % 3 + 1, "winCamp": winner,
        "camp1": {"team": "战队A"}, "camp2": {"team": "战队B"},
        "picks": {"1": H1, "2": H2}, "bans": {"1": B1, "2": B2},
        "players": {
            "1": [{"player": "选手A", "hero": H1[0], "position": "对抗路"}],
            "2": [{"player": "选手B", "hero": H2[0], "position": "对抗路"}],
        },
        "bansKnown": full, "pickOrderKnown": full,
        "draftEvents": draft() if full else [],
    }


def test_kpl_perspectives_and_provenance():
    rows = normalize_kpl([game(1)])
    assert len(rows) == 2
    a = next(row for row in rows if row["team"] == "战队A")
    b = next(row for row in rows if row["team"] == "战队B")
    assert a["result"] is True and b["result"] is False
    assert a["enemy"] == "战队B"
    assert len(a["events"]) == 14
    assert a["players"][0]["name"] == "选手A"
    assert a["enemyPlayers"][0]["name"] == "选手B"


def test_actual_condition_response_does_not_use_future_actions():
    records = [game(i, "2026-11-01" if i < 4 else "2026-11-02")
               for i in range(8)]
    report = build_report([], records, source="kpl", team="战队A")
    assert report["scope"]["games"] == 8
    assert report["scope"]["orderedGames"] == 8
    first = next(r for r in report["responses"]
                 if r["trigger"] == "马超" and r["response"] == "夏洛特")
    assert first["games"] == 8 and first["opportunities"] == 8
    assert first["share"] == 100
    assert report["scope"]["wins"] == 8
    assert report["scope"]["interval"][0] < 100  # no false 100% certainty


def test_partial_and_conflicting_events_never_claim_order():
    incomplete = game(2)
    incomplete["draftEvents"] = incomplete["draftEvents"][:-1]
    report = build_report([], [incomplete], source="kpl", team="战队A")
    assert report["scope"]["orderedGames"] == 0
    assert report["responses"] == []

    unconfirmed = game(3, full=False)
    unconfirmed["draftEvents"] = draft()
    report2 = build_report([], [unconfirmed], source="kpl", team="战队A")
    assert report2["scope"]["orderedGames"] == 0
    assert report2["picks"][0]["games"] == 1


def test_scrim_verified_player_hero_and_performance_without_inventing_phase():
    raw = {
        "key": "channel-x", "day": "2026-11-04", "opponent": "对手X",
        "ownSide": "left", "result": "win",
        "picks": {"own": [{"name": x} for x in H1],
                  "enemy": [{"name": x} for x in H2]},
        "bans": {"own": [{"name": x} for x in B1],
                 "enemy": [{"name": x} for x in B2]},
        "roster": {"own": [{"name": "实训选手", "hero": "夏洛特", "lane": "对抗路",
                           "gold": 10000, "heroDamage": 24000}],
                   "enemy": [{"name": "对位选手", "hero": "马超", "lane": "对抗路"}]},
        "draftEvents": draft(),
    }
    records = normalize_scrims([raw])
    own = next(g for g in records if g["team"] == "本队")
    assert own["players"][0]["hero"] == "夏洛特"
    assert own["enemyPlayers"][0]["hero"] == "马超"
    assert len(own["events"]) == len(draft())
    report = build_report([raw], [], source="scrim", team="本队")
    assert report["scope"]["orderedGames"] == 1
    assert report["players"][0]["heroDamagePer1000Gold"] == 2400.0
    assert report["players"][0]["player"] == "实训选手"


def test_scrim_only_final_lineup_is_not_a_draft_sequence():
    base = {
        "key": "only-panel", "day": "2026-11-04", "opponent": "对手X",
        "ownSide": "right", "result": "loss",
        "picks": {"own": H1, "enemy": H2},
        "bans": {"own": B1, "enemy": B2},
    }
    report = build_report([base], [], source="scrim", team="本队")
    assert report["scope"]["games"] == 1
    assert report["scope"]["orderedGames"] == 0
    assert report["responses"] == []


def test_duplicate_games_and_dates_and_sources():
    records = [game(i, "2026-11-02" if i < 4 else "2026-11-07")
               for i in range(8)]
    report = build_report([], records + [records[1]], source="kpl",
                          team="战队A", start="2026-11-05", end="2026-11-08")
    assert report["scope"]["games"] == 4
    assert report["scope"]["orderedGames"] == 4
    assert report["changes"] == []  # a single day cannot define two periods
    assert all(e["source"] == "kpl" for e in report["evidence"])
    with pytest.raises(ValueError):
        build_report([], records, source="no-such-source")
    with pytest.raises(ValueError):
        build_report([], records, source="kpl", start="invalid")


def test_temporal_changes_and_pair_counts():
    games = [game(i, "2026-10-01" if i < 5 else "2026-11-01")
             for i in range(10)]
    report = build_report([], games, source="kpl", team="战队A")
    assert report["scope"]["games"] == 10
    assert report["changes"]  # descriptive before/after, not a causal claim
    assert report["pairs"]
    pair = next(row for row in report["pairs"] if "夏洛特" in row["heroes"])
    assert pair["games"] == 10
    assert pair["decided"] == 10
    assert pair["relativeSignal"] is not None


def test_wilson_small_samples_are_not_certainty():
    lo, hi = _wilson(1, 1)
    assert lo < 100 and hi == 100
    assert _wilson(0, 0) == [None, None]
