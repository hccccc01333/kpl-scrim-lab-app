"""Tests for the .abc/.ope replay state engine.

The engine only reports what the container carries.  These tests pin that
contract: the decoded facts are present, and the fields the container does not
carry stay declared as missing instead of being guessed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SAMPLES = ROOT / "data/replays/samples"


def _first_abc() -> Path | None:
    if not SAMPLES.exists():
        return None
    for path in sorted(SAMPLES.rglob("*.abc")):
        if path.stat().st_size > 200_000:
            return path
    return None


@pytest.fixture(scope="module")
def document():
    abc = _first_abc()
    if abc is None:
        pytest.skip("no .abc sample checked in")
    from replay_state_engine import build_from_bytes

    return build_from_bytes(abc.read_bytes())


def test_schema_and_source(document):
    assert document["schema"] == "kpl-replay-state-v1"
    source = document["source"]
    assert len(source["abc_sha256"]) == 64
    assert source["totalFrames"] and source["totalFrames"] > 0
    assert source["frameHz"] == 15.0


def test_roster_has_ten_players_with_camps(document):
    players = document["players"]
    assert len(players) == 10
    assert {p["camp"] for p in players} == {1, 2}
    for player in players:
        assert player["entityId"]
        assert player["hero"]
        assert player["team"] in {"blue", "red"}


def test_win_side_matches_mvp_camp(document):
    match = document["match"]
    mvp_id = match["mvpEntityId"]
    mvp = next(p for p in document["players"] if p["entityId"] == mvp_id)
    assert mvp["mvp"] is True
    assert mvp["team"] == match["winningCamp"]
    assert all(p["win"] == (p["team"] == match["winningCamp"])
               for p in document["players"])


def test_timeline_is_one_frame_per_second(document):
    timeline = document["timeline"]
    assert len(timeline) == document["match"]["durationSec"]
    assert [frame["t"] for frame in timeline] == list(range(len(timeline)))
    for frame in timeline[:5] + timeline[-5:]:
        assert len(frame["p"]) == 10
        for cell in frame["p"]:
            assert 1 <= cell["lv"] <= 15
            assert cell["gs"] is None or cell["gs"] >= 0


def test_level_and_spend_are_monotonic(document):
    timeline = document["timeline"]
    for entity in (p["entityId"] for p in document["players"]):
        levels, spends = [], []
        for frame in timeline:
            cell = next(c for c in frame["p"] if c["e"] == entity)
            levels.append(cell["lv"])
            spends.append(cell["gs"] or 0)
        assert levels == sorted(levels), f"level regressed for {entity}"
        assert spends == sorted(spends), f"spend regressed for {entity}"


def test_purchases_carry_decoded_price_and_time(document):
    purchases = document["events"]["purchases"]
    assert purchases
    for item in purchases:
        assert item["tier"] == "decoded"
        assert item["entityId"]
        assert item["equipId"]
        assert item["t"] >= 0
    assert all(item["t"] <= document["match"]["durationSec"] + 1
               for item in purchases)


def test_learns_are_decoded_and_bounded_by_level_cap(document):
    learns = document["events"]["learns"]
    assert learns
    per_entity: dict[int, int] = {}
    for item in learns:
        assert item["tier"] == "decoded"
        per_entity[item["entityId"]] = per_entity.get(item["entityId"], 0) + 1
    for entity, count in per_entity.items():
        assert count <= 20, f"implausible skill-point count for {entity}: {count}"


def test_missing_combat_fields_are_declared_not_invented(document):
    missing = document["missing"]
    for key in ("kills", "deaths", "assists", "goldIncome", "hp", "positions"):
        assert key in missing and missing[key]
    # Nothing in the timeline may pretend to carry them.
    for frame in document["timeline"][:3]:
        for cell in frame["p"]:
            assert set(cell) == {"e", "lv", "gs", "m", "a", "s", "c", "am"}


def test_sparse_anchors_are_decoded_but_not_a_trajectory(document):
    anchors = document["anchors"]
    assert anchors
    for item in anchors:
        assert item["tier"] == "decoded"
        assert item["e"]
        assert isinstance(item["x"], int) and isinstance(item["y"], int)
    times = [item["t"] for item in anchors]
    assert times == sorted(times)
    coverage = document["coverage"]["anchors"]
    assert coverage["samples"] == len(anchors)
    # The file only carries anchors for a couple of players; the document must
    # say so instead of implying full coverage.
    assert coverage["entities"] <= len(document["players"])


def test_coverage_reports_the_ope_stream(document):
    coverage = document["coverage"]
    assert coverage["frameStream"].startswith("decoded")
    assert coverage["playerBlocks"]["bytes"] > 0
    ope = coverage["ope"]
    assert ope["bytes"] >= 0
    assert set(ope) == {"bytes", "decoded", "mode", "records", "note"}
    assert document["source"]["opeBytes"] >= 0


def test_document_is_json_serialisable(document):
    payload = json.dumps(document, ensure_ascii=False)
    assert len(payload) > 1000
    assert json.loads(payload)["schema"] == "kpl-replay-state-v1"
