"""BP 英雄关系环与日期前后对照的纯函数回归。"""
from __future__ import annotations

import bp_studio


def _game(day, picks, bans, result=True):
    return {"id": day, "date": day, "result": result,
            "picks": picks, "bans": bans, "team": "A队", "enemy": "B队"}


def test_period_compare_rates_and_min_sample():
    games = []
    for index in range(12):
        games.append(_game(f"2026-10-{index + 1:02d}", ["盾山"], ["鲁班大师"], index % 2 == 0))
    for index in range(6):
        picks = ["盾山"] if index < 3 else ["大乔"]
        games.append(_game(f"2026-10-{20 + index}", picks, ["鲁班大师"], index % 2 == 0))
    report = bp_studio.period_compare(games, "2026-10-15", days=30, limit=10)
    assert report["available"] is True
    row = next(item for item in report["rows"] if item["hero"] == "盾山")
    assert row["before"]["pickRate"] == 100.0
    assert row["after"]["pickRate"] == 50.0
    assert row["delta"]["pick"] == -50.0
    assert row["before"]["winRate"] is not None
    # 后段只有 3 个胜负样本，按口径不显示胜率
    assert row["after"]["winRate"] is None


def test_season_compare_shifts_to_mid_when_season_has_no_before():
    games = []
    for index in range(8):
        games.append(_game(f"2026-11-{index + 2:02d}", ["盾山"], ["鲁班大师"], index % 2 == 0))
    report = bp_studio.season_period_compare(games, "S45", days=30)
    assert report["available"] is True
    assert report.get("autoShifted") is True
    assert report["season"] == "S45"
    assert report["before"]["games"] > 0 and report["after"]["games"] > 0


def test_hero_ring_uses_relation_tables(monkeypatch):
    monkeypatch.setattr(bp_studio, "_relation_fact", lambda name: {
        "lane_matchups.json": {"pairs": [
            {"a": "盾山", "b": "鲁班大师", "n": 50, "wr": 55.0, "excess": 4.2},
            {"a": "大乔", "b": "盾山", "n": 40, "wr": 54.0, "excess": 3.1},
        ]},
        "kpl_combos.json": {"pairs": [
            {"heroes": ["盾山", "大乔"], "n": 30, "wr": 56.0},
        ]},
    }[name])
    report = bp_studio.hero_ring("盾山", [_game("2026-10-01", ["盾山"], [], True)])
    assert report["available"] is True
    assert report["counters"][0]["hero"] == "鲁班大师"
    assert report["counteredBy"][0]["hero"] == "大乔"
    assert report["partners"][0]["hero"] == "大乔"
    assert report["stats"]["picks"] == 1
