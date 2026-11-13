"""Regression tests for the single-pair decode report.

These pin the numbers for the 20261102_161129 pair (the local player is
百里守约 / entity 1611).  They are structural checks, not golden-file copies:
the `.ope` record count may move when the operator-stream layouts improve, so
only the invariants that must always hold are asserted.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from decode_replay_pair import build_report, summarize  # noqa: E402

PAIR_DIR = ROOT / "data/replays/samples/20261102_161129"


def _pair() -> tuple[Path, Path]:
    if not PAIR_DIR.exists():
        pytest.skip("20261102_161129 sample not available")
    abc = sorted(PAIR_DIR.glob("*.abc"))
    ope = sorted(PAIR_DIR.glob("*.ope"))
    if not abc or not ope:
        pytest.skip("20261102_161129 pair incomplete")
    return abc[0], ope[0]


@pytest.fixture(scope="module")
def report():
    abc, ope = _pair()
    return build_report(abc, ope)


def test_container_metadata(report):
    abc = report["abc"]
    assert abc["bytes"] == 482967
    assert abc["sha256"].startswith("d74c2bed")
    assert abc["builds"] == ["4989537", "5247758"]
    assert abc["totalFrames"] == 10674
    assert abc["mapType"] == 3
    assert abc["mapId"] == 20111
    assert abc["localHeroId"] == 196
    assert abc["localHeroName"] == "百里守约"


def test_roster_and_result(report):
    players = report["players"]
    assert len(players) == 10
    assert {player["camp"] for player in players} == {1, 2}
    assert report["match"]["winningCamp"] == "blue"
    assert report["match"]["mvpEntityId"] == 538
    mvp = next(player for player in players if player["entityId"] == 538)
    assert mvp["mvp"] is True and mvp["team"] == "blue"
    local = next(player for player in players if player["hero"] == "百里守约")
    assert local["team"] == "blue" and local["win"] is True
    assert local["rating"] == 10.6


def test_economy_and_skill_ledgers(report):
    assert report["skills"]["learnEvents"] == 120
    assert report["economy"]["uniquePurchases"] > 100
    assert report["economy"]["totalSpend"] > 50000
    for player in report["players"]:
        assert 1 <= player["levelFinal"] <= 15
        assert player["goldSpentFinal"] > 0


def test_ope_is_fully_consumed(report):
    ope = report["ope"]
    assert ope["available"] is True
    assert ope["bytes"] == 113178
    assert ope["consumedPct"] >= 99.9
    assert ope["records"] > 10000          # exact count tracks parser layouts
    assert ope["typeCounts"]["MoveOpe"] > 1000
    assert ope["payloadSemantics"] is None  # field names stay unclaimed


def test_init_block_is_reported_with_only_three_named_words(report):
    init = report["abc"]["initBlock"]
    assert init is not None
    assert init["initialGold"] == 300
    assert init["kvMode"] == 50
    assert init["serverTimeUnixSeconds"] == 1793606215
    assert len(init["kvRulesetSha256"]) == 64
    assert init["anchorScore"] == "11/11"


def test_undecoded_fields_are_declared(report):
    undecoded = report["undecoded"]
    for key in ("kills", "deaths", "assists", "goldIncome", "hp", "positions",
                "opePayloadSemantics"):
        assert key in undecoded and undecoded[key]


def test_cc_family_is_command_sync_not_crowd_control(report):
    """`cc` is CSDT_FRAPBOOT_CC (direction/stop/attack position), not CC effects.

    百里守约 is a sniper with no hard crowd control; the 1,585 `cc` rows on that
    entity used to be shown as "控制", which was a labelling bug.  Pin the real
    breakdown so the misreading cannot come back.
    """
    per_player = report["ccCommands"]["perPlayer"]
    local = next(player for player in report["players"] if player["hero"] == "百里守约")
    breakdown = per_player[str(local["entityId"])]
    assert breakdown["direction"] == 1364
    assert breakdown["stopMove"] == 161
    assert breakdown["attackPos"] == 43
    assert breakdown["positionMove"] == 0
    assert breakdown["other"] == 17
    # Direction command sync is only recorded for the local POV player.
    assert sum(item["direction"] for item in per_player.values()) == breakdown["direction"]
    assert "不是控制效果" in report["ccCommands"]["note"]


def test_summary_does_not_claim_crowd_control(report):
    text = summarize(report)
    assert "CC指令" in text
    assert "不是控制效果" in text
    assert "/控制/" not in text


def test_summary_renders(report):
    text = summarize(report)
    assert "百里守约" in text
    assert "明确解不出" in text
    assert "MVP" in text
