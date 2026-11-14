"""08 对手打法：阵营/阵容统计与对手视角检查点的纯函数守卫。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from opponent_behavior import opponent_behavior  # noqa: E402


def test_opponent_aggregation_and_perspective_flip():
    rows = [
        {"key": "k1", "opponent": "对手A", "result": "win", "side": "blue",
         "day": "2026-11-02", "picks": {"enemy": [{"name": "马超"}, {"name": "赵云"}]}},
        {"key": "k2", "opponent": "对手A", "result": "loss", "side": "red",
         "day": "2026-11-03", "picks": {"enemy": [{"name": "马超"}]}},
        {"key": "k3", "opponent": "未归属对手", "result": "win", "side": "blue",
         "day": "2026-11-04", "picks": {"enemy": []}},
    ]
    process = {"k1": {"teamDiffOwn": {"240": -300, "600": 800}}}
    out = opponent_behavior(rows, process)
    teams = out["teams"]
    assert len(teams) == 1 and teams[0]["opponent"] == "对手A"  # 未归属不入榜
    t = teams[0]
    assert t["games"] == 2 and t["winRate"] == 50.0
    assert t["blueGames"] == 1 and t["redGames"] == 1
    assert t["topPicks"][0] == {"hero": "马超", "games": 2}
    # k1 本队 -300 → 对手 +300 领先；本队赢 → 对手兑现失败
    cp = t["checkpoints"]["240"]
    assert cp["games"] == 1 and cp["meanDiff"] == 300.0
    assert cp["leadRate"] == 100.0 and cp["leadConversion"] == 0.0
    assert t["linkedGames"] == 1
    assert any("未实现" in x for x in out["limitations"])


def test_opponent_without_process_evidence_stays_empty():
    rows = [{"key": "k9", "opponent": "对手B", "result": "win", "side": "blue",
             "day": "2026-11-05", "picks": {"enemy": []}}]
    out = opponent_behavior(rows, {})
    t = out["teams"][0]
    assert t["checkpoints"]["600"]["games"] == 0
    assert t["checkpoints"]["600"]["meanDiff"] is None
