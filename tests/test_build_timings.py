"""Tests for finished-item / "三件套" timing derived from decoded purchases.

The timestamps are decoded; the "finished item" label is a rule (price >= 1000,
shoes excluded).  These tests pin both the rule and the resulting numbers for
the 20261102_161129 replay so a threshold change cannot silently move the
reported three-piece times.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import build_timings as bt  # noqa: E402
from replay_state_engine import build_from_bytes  # noqa: E402

ABC = (ROOT / "data/replays/samples/20261102_161129"
       / "20261102_161129_870343216_95868_1793606215_2B9FAA08A7AD40D09ABDA364F9C1E804.abc")


@pytest.fixture(scope="module")
def timings():
    if not ABC.exists():
        pytest.skip("sample replay not available")
    state = build_from_bytes(ABC.read_bytes())
    return bt.build_report(state), state


def _by_hero(report, hero):
    for info in report["perPlayer"].values():
        if info["hero"] == hero:
            return info
    raise AssertionError(f"hero {hero} not in report")


def test_rule_constants():
    assert bt.FINISHED_PRICE == 1000
    assert bt.BIG_PRICE == 2000
    assert bt.is_shoe(1411) and bt.is_shoe(1426)
    assert not bt.is_shoe(1133)


def test_baili_shouyue_three_piece(timings):
    report, _state = timings
    info = _by_hero(report, "百里守约")
    assert info["finishedCount"] == 3
    assert [item["name"] for item in info["finished"]] == ["无尽战刃", "影刃", "仁者破晓"]
    assert info["finished"][0]["t"] == pytest.approx(260.3, abs=0.1)   # 4:20.3
    assert info["finished"][0]["tText"] == "4:20"
    assert info["threePieceTimeSec"] == pytest.approx(649.3, abs=0.1)   # 10:49.3
    assert info["threePieceTimeText"] == "10:49"
    assert info["threePieceItem"] == "仁者破晓"
    # boots-first convention puts the third slot at the second core item
    assert info["variants"]["withShoes"]["tText"] == "8:42"


def test_milestones_are_monotonic_and_shoes_excluded(timings):
    report, _state = timings
    for info in report["perPlayer"].values():
        times = [item["t"] for item in info["finished"]]
        assert times == sorted(times)
        for item in info["finished"]:
            assert not bt.is_shoe(item["equipId"])
            assert item["price"] >= bt.FINISHED_PRICE
        labels = [info["milestones"][label] for label in bt.MILESTONE_LABELS]
        seen_none = False
        for mark in labels:
            if mark is None:
                seen_none = True
            else:
                assert not seen_none, "milestone filled after a gap"


def test_players_without_three_items_report_none(timings):
    report, _state = timings
    daji = _by_hero(report, "妲己")
    assert daji["finishedCount"] == 2
    assert daji["threePieceTimeSec"] is None
    assert daji["milestones"]["third"] is None
    assert daji["variants"]["bigOnly2000"] is None  # only two >=2000 items
    # 含鞋口径下她有三件（两件大件 + 升级鞋），说明两个口径不是一回事
    assert daji["variants"]["withShoes"] is not None


def test_report_carries_threshold_and_caveat(timings):
    report, _state = timings
    assert report["finishedPriceThreshold"] == 1000
    assert report["shoeIdRange"] == [1400, 1499]
    assert "合成树" in report["caveat"]
    assert len(report["perPlayer"]) == 10
