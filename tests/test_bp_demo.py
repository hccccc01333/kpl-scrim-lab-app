"""征召模拟数据：8 局、18 手、符合 draft-18，且只用于界面验证。"""
from bp_demo import scrim_games
from bp_formats import DRAFT_18, check_draft


def test_demo_games_are_valid_draft18():
    games = scrim_games(8)
    assert len(games) == 8
    for game in games:
        assert game["ruleProfile"] == "draft-18"
        assert game["team"] == "本队"
        assert game["enemy"].startswith("模拟对手")
        assert len(game["events"]) == 18
        assert check_draft(game["events"], DRAFT_18)["ok"]
        assert len(game["picks"]) == 5 and len(game["bans"]) == 4
        assert len(set(game["picks"] + game["enemyPicks"])) == 10
        assert len(set(game["bans"] + game["enemyBans"])) == 8
        assert game["pickOrderKnown"] and game["bansKnown"]


def test_demo_dates_are_recent_and_series_has_four_games():
    games = scrim_games(8)
    assert all(game["date"].startswith("2026-11-") for game in games)
    assert {game["enemy"] for game in games} == {"模拟对手A", "模拟对手B"}
    seqs = [int(game["gameSeq"]) for game in games]
    assert seqs.count(1) == 2 and seqs.count(4) == 2
