"""09 周期异常监控：窗口突变检测的纯函数守卫。"""
import pytest

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from monitor import monitor  # noqa: E402


def row(key, day, hero, hero2="瑶", result="win", player="选手A"):
    return {"key": key, "day": day, "result": result, "side": "blue",
            "picks": {"own": [{"name": hero}], "enemy": [{"name": hero2}]},
            "roster": {"own": [{"name": player, "hero": hero, "lane": "对抗路",
                                "gold": 8000}]}}


def test_cross_week_shifts_are_detected():
    def two_sided(key, day, own_hero, enemy_hero, enemy_player, result):
        return {"key": key, "day": day, "result": result, "side": "blue",
                "picks": {"own": [{"name": own_hero}], "enemy": [{"name": enemy_hero}]},
                "roster": {"own": [{"name": "选手A", "hero": own_hero, "lane": "对抗路",
                                    "gold": 8000}],
                           "enemy": [{"name": enemy_player, "hero": enemy_hero,
                                      "lane": "对抗路", "gold": 7000}]}}
    rows = [
        two_sided("a1", "2026-11-02", "马超", "瑶", "对手B", "win"),
        two_sided("a2", "2026-11-03", "马超", "瑶", "对手B", "win"),
        two_sided("b1", "2026-11-12", "马超", "孙悟空", "对手B", "loss"),
        two_sided("b2", "2026-11-12", "马超", "孙悟空", "对手B", "loss"),
    ]
    out = monitor(rows, unit="week")
    assert out["windows"] == 2 and out["games"] == 4 and out["undated"] == 0
    kinds = {a["kind"] for a in out["anomalies"]}
    assert {"winrate", "pair-replaced", "player-pool"} <= kinds
    winrate = next(a for a in out["anomalies"] if a["kind"] == "winrate")
    assert winrate["object"].startswith("马超") and winrate["changePP"] == -100.0


def test_small_samples_are_suppressed_by_min_games():
    rows = [row("a1", "2026-11-02", "马超"), row("b1", "2026-11-12", "夏洛特")]
    out = monitor(rows, unit="week")
    assert not any(a["kind"] == "usage" for a in out["anomalies"])


def test_invalid_unit_raises():
    with pytest.raises(ValueError):
        monitor([], unit="fortnight")


def test_undated_rows_are_counted_not_dropped():
    rows = [row("a1", "2026-11-02", "马超"), {"key": "x", "day": None}]
    out = monitor(rows, unit="week")
    assert out["undated"] == 1
    assert out["games"] == 1


def test_date_range_filter():
    rows = [row("a1", "2026-11-02", "马超"), row("b1", "2026-11-12", "夏洛特"),
            row("b2", "2026-11-12", "夏洛特")]
    out = monitor(rows, unit="week", date_from="2026-11-10")
    assert out["windows"] == 1 and out["games"] == 2


def test_monitor_api_player_filter_and_cache_key():
    """serve 路由的 player 过滤：个人页只拿自己的英雄池变化条目。"""
    from fastapi.testclient import TestClient
    from server import app
    client = TestClient(app, base_url='http://localhost')
    resp = client.get('/api/v3/monitor?unit=week&player=不存在的选手')
    assert resp.status_code == 200
    body = resp.json()
    assert body.get('player') == '不存在的选手'
    assert body['anomalies'] == []
