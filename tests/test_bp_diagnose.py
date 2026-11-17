import pytest

from bp_diagnose import build_diagnosis


def game(day, result, *, hero="甄姬", partners=("张飞",), enemies=("小乔",),
         players=None, enemy_players=None, gold_diff=None):
    picks = [hero, *partners, "狄仁杰", "铠", "牛魔"]
    picks = list(dict.fromkeys(picks))[:5]
    enemy_picks = [*enemies, "吕布", "赵云", "张良", "孙膑"]
    enemy_picks = list(dict.fromkeys(enemy_picks))[:5]
    own_players = players or [{"name": "中单", "hero": hero, "lane": "中路"}]
    return {
        "id": f"{day}-{result}-{len(partners)}-{len(enemies)}",
        "date": day, "team": "本队", "enemy": "对手A", "side": "1",
        "picks": picks, "enemyPicks": enemy_picks,
        "players": own_players, "enemyPlayers": enemy_players or [],
        "result": result, "source": "scrim", "league": "训练赛",
        "teamGoldDiff": gold_diff or {},
    }


@pytest.fixture
def rows():
    rows = []
    # 前窗：10 局 8 胜，搭档 张飞，敌方 小乔
    for index in range(10):
        players = [{"name": "中单", "hero": "甄姬", "lane": "中路",
                    "kills": 2, "deaths": 4, "assists": 5, "gold": 7000,
                    "heroDamage": 30000, "taken": 12000,
                    "participation": 55, "towers": 1}]
        rows.append(game(f"2026-09-{21 + index:02d}", index < 8, players=players))
    # 当前窗：10 局 2 胜，搭档换成 大乔，敌方换成 王昭君；每局有逐人统计
    for index in range(10):
        players = [{"name": "中单", "hero": "甄姬", "lane": "中路",
                    "kills": 2, "deaths": 4, "assists": 5, "gold": 7000,
                    "heroDamage": 30000, "taken": 12000,
                    "participation": 55, "towers": 1}]
        enemies = [{"name": "敌中", "hero": "王昭君", "lane": "中路"}]
        rows.append(game(f"2026-10-{1 + index:02d}", index < 2,
                         partners=("大乔",), enemies=("王昭君",),
                         players=players, enemy_players=enemies,
                         gold_diff={"120": -500, "240": -900, "600": -1500}))
    return rows


def test_performance_counters_and_trend(rows):
    report = build_diagnosis(rows, team="本队", hero="甄姬", recent_days=30,
                             start="2026-10-01", end="2026-10-10")
    assert report["available"]
    assert report["heroGames"] == {"current": 10, "previous": 10, "total": 20}
    assert report["performance"]["current"]["winRate"] == 20.0
    assert report["performance"]["previous"]["winRate"] == 80.0
    trend = {row["days"]: row for row in report["performance"]["trend"]}
    assert trend[30]["games"] == 20
    assert trend[7]["games"] == 7
    counters = {row["hero"]: row for row in report["locate"]["enemyHeroes"]}
    assert counters["王昭君"]["winRate"] == 20.0
    assert counters["王昭君"]["shareDelta"] == 100.0


def test_anomaly_is_significant_on_large_drop(rows):
    report = build_diagnosis(rows, team="本队", hero="甄姬",
                             start="2026-10-01", end="2026-10-10")
    anomaly = report["anomaly"]
    assert anomaly["drop"] == -60.0
    assert anomaly["pValue"] is not None and anomaly["pValue"] < 0.05
    assert anomaly["significant"] is True
    assert anomaly["verdict"] == "显著下降"
    assert anomaly["severity"] == "高"


def test_location_lane_player_and_context(rows):
    report = build_diagnosis(rows, team="本队", hero="甄姬",
                             start="2026-10-01", end="2026-10-10")
    locate = report["locate"]
    partners = {row["hero"]: row for row in locate["partners"]}
    assert "大乔" in partners and partners["大乔"]["games"] == 10
    lane = locate["laneOpponents"]
    assert lane["available"] and lane["lane"] == "中路"
    assert lane["heroes"][0]["hero"] == "王昭君"
    assert locate["players"][0]["player"] == "中单"
    assert locate["context"]["current"]["sides"][0]["key"] == "1"


def test_associations_performance_tempo_and_diff(rows):
    report = build_diagnosis(rows, team="本队", hero="甄姬",
                             start="2026-10-01", end="2026-10-10")
    assert report["compareAvailable"] is True
    assert any(row["object"] == "大乔" for row in report["associations"])
    performance = report["performanceStats"]
    assert performance["current"]["available"] is True
    assert performance["current"]["metrics"]["kda"] == 1.75
    assert performance["delta"]["gold"] == 0.0
    tempo = report["tempo"]["current"]
    assert tempo["available"] is True
    assert tempo["checkpoints"]["600"]["avgGoldDiff"] == -1500
    assert report["diff"]["partner"]["added"] == ["大乔"]
    assert report["diff"]["partner"]["removed"] == ["张飞"]
    assert report["lineupPeriods"][0]["period"] == "2026-10"


def test_kpl_without_player_stats_is_explicit(rows):
    kpl_rows = [{**row, "players": [], "enemyPlayers": [], "teamGoldDiff": {},
                 "source": "kpl"} for row in rows]
    report = build_diagnosis(kpl_rows, team="本队", hero="甄姬",
                             start="2026-10-01", end="2026-10-10")
    assert report["performanceStats"]["current"]["available"] is False
    assert "没有逐人" in report["performanceStats"]["current"]["reason"]
    assert report["tempo"]["current"]["available"] is False


def test_enemy_lineup_specific_counter(rows):
    report = build_diagnosis(rows, team="本队", hero="甄姬",
                             start="2026-10-01", end="2026-10-10",
                             enemy_lineup=["王昭君"])
    lineup = report["counters"]["enemyLineup"]
    assert lineup["heroes"] == ["王昭君"]
    assert lineup["current"]["games"] == 10
    assert lineup["current"]["winRate"] == 20.0
    assert lineup["previous"]["games"] == 0


def test_no_previous_window_marks_compare_unavailable(rows):
    old = [game("2026-08-01", True)]
    current = [row for row in rows if row["date"] >= "2026-10-01"]
    report = build_diagnosis(old + current, team="本队", hero="甄姬",
                             start="2026-10-01", end="2026-10-10")
    assert report["heroGames"]["current"] == 10
    assert report["heroGames"]["previous"] == 0
    assert report["compareAvailable"] is False
    assert report["anomaly"]["baseline"]["scope"] == "history"


def test_empty_and_missing_hero():
    assert build_diagnosis([], team="本队", hero="甄姬")["available"] is False
    assert build_diagnosis([], team="本队", hero="")["reason"] == "请选择一个英雄。"


def test_single_previous_game_disables_association_and_diff(rows):
    current = [row for row in rows if row["date"] >= "2026-10-01"]
    previous_one = [game("2026-09-30", True)]
    report = build_diagnosis(current + previous_one, team="本队", hero="甄姬",
                             start="2026-10-01", end="2026-10-10")
    assert report["heroGames"]["previous"] == 1
    assert report["associationAvailable"] is False
    assert report["associations"] == []
    assert report["diff"]["available"] is False
    assert "不足 5 局" in report["diff"]["reason"]
