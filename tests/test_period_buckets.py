"""03 补齐：自然周 / 自然月分桶与 _lineups 经济核心的守卫。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis_period import bucket_key, bucket_rows  # noqa: E402
from bp_intelligence import _lineups  # noqa: E402


def test_bucket_key_week_and_month():
    assert bucket_key("2026-11-14", "week").startswith("W2026-W46-2026-11-09")
    assert bucket_key("2026-11-14", "month") == "M2026-11"
    assert bucket_key("2026-11-14", "day") == "2026-11-14"
    assert bucket_key("not-a-date", "week") is None
    assert bucket_key(None, "month") is None


def test_bucket_rows_keeps_undated_last():
    rows = [{"d": "2026-11-10"}, {"d": "2026-11-14"}, {"d": None}, {"d": "2026-10-28"}]
    buckets = bucket_rows(rows, "d", "month")
    assert [b["key"] for b in buckets] == ["M2026-10", "M2026-11", "undated"]
    assert buckets[-1]["rows"] == [{"d": None}]


def test_lineups_gold_core_and_tempo():
    games = [
        {"id": "g1", "date": "2026-11-02", "picks": ["A", "B", "C", "D", "E"], "result": True,
         "players": [{"hero": "A", "lane": "打野", "gold": 9000},
                     {"hero": "B", "lane": "发育路", "gold": 5000},
                     {"hero": "C", "lane": "中路", "gold": 4500},
                     {"hero": "D", "lane": "对抗路", "gold": 4000},
                     {"hero": "E", "lane": "游走", "gold": 3000}],
         "teamGoldDiff": {"600": 800}, "team": "本队", "enemy": "对手A", "source": "scrim", "matchId": None},
        {"id": "g2", "date": "2026-11-02", "picks": ["A", "B", "C", "D", "E"], "result": False,
         "players": [{"hero": "A", "lane": "打野", "gold": 8500},
                     {"hero": "B", "lane": "发育路", "gold": 5200},
                     {"hero": "C", "lane": "中路", "gold": 4300},
                     {"hero": "D", "lane": "对抗路", "gold": 3900},
                     {"hero": "E", "lane": "游走", "gold": 2800}],
         "teamGoldDiff": {"600": -200}, "team": "本队", "enemy": "对手A", "source": "scrim", "matchId": None},
    ]
    lineups = _lineups(games)
    assert len(lineups) == 1
    row = lineups[0]
    assert row["goldCore"]["hero"] == "A" and row["goldCore"]["games"] == 2
    assert row["goldCore"]["system"] == "野核"
    assert row["tempo"]["games"] == 2 and row["tempo"]["meanDiff600"] == 300.0
    assert row["tempo"]["leadRate"] == 50.0 and row["tempo"]["leadWinRate"] == 100.0


def test_lineups_without_gold_or_process_stays_honest():
    games = [{"id": "g1", "date": "2026-11-02", "picks": ["A", "B", "C", "D", "E"], "result": True,
              "players": [], "team": "本队", "enemy": "对手A", "source": "scrim", "matchId": None}]
    row = _lineups(games)[0]
    assert row["goldCore"] is None and row["tempo"] is None
