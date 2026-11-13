"""Tests for the `.abc` init-block locator (KV array + 443-byte scalar block).

The locator must survive the two build-dependent facts: the block's offset moves
with the header length, and the terminator before the first player block is 1-3
bytes long (``0a`` vs ``00 00 0a``).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from abc_init_block import (  # noqa: E402
    ANCHOR_WORDS, KNOWN_WORDS, SCALAR_BYTES, SCALAR_COUNT,
    kv_pairs, kv_ruleset_sha, known_fields, locate, server_stamp_from_name)


def _samples() -> list[Path]:
    root = ROOT / "data/replays/samples"
    if not root.exists():
        return []
    return sorted(root.rglob("*.abc"))


def _supported() -> list[tuple[Path, dict]]:
    found = []
    for path in _samples():
        located = locate(path.read_bytes())
        if located is not None:
            found.append((path, located))
    return found


def test_locator_returns_none_for_short_or_foreign_buffers():
    assert locate(b"") is None
    assert locate(b"\x00" * 4096) is None
    # A 1..10 confType head without the scalar block must not be accepted.
    entries = b"".join(bytes([step]) + b"\x00\x00\x00" for step in range(1, 11))
    assert locate(b"\x00" * 0x100 + entries + b"\x00" * 512) is None


def test_anchor_words_are_not_field_names():
    # Guard against someone "promoting" alignment anchors into documented names.
    assert set(ANCHOR_WORDS) <= set(range(SCALAR_COUNT))
    assert set(KNOWN_WORDS) == {1, 2, 67}
    assert ANCHOR_WORDS[2] == 300


@pytest.mark.parametrize("path,located", _supported() or [pytest.param(None, None, marks=pytest.mark.skip(reason="no sample"))])
def test_every_supported_sample_pins_the_same_anchors(path, located):
    if located is None:
        pytest.skip("no sample replay checked in")
    for index, value in ANCHOR_WORDS.items():
        assert located["words"][index] == value, f"anchor {index} drifted"
    assert located["score"] == located["anchorTotal"]
    assert located["terminator"] in ("0a", "000a", "00000a")
    assert located["scalarEnd"] - located["scalarStart"] == SCALAR_BYTES
    assert len(located["words"]) == SCALAR_COUNT


@pytest.mark.parametrize("path,located", _supported() or [pytest.param(None, None, marks=pytest.mark.skip(reason="no sample"))])
def test_server_time_word_matches_the_file_timestamp(path, located):
    if located is None:
        pytest.skip("no sample replay checked in")
    stamp = server_stamp_from_name(path.stem)
    if stamp is None:
        pytest.skip("file name carries no plausible server timestamp")
    # One sample differs by exactly 1 s between the file name and the block.
    assert abs(located["words"][67] - stamp) <= 1


@pytest.mark.parametrize("path,located", _supported() or [pytest.param(None, None, marks=pytest.mark.skip(reason="no sample"))])
def test_known_fields_only_claim_three_words(path, located):
    if located is None:
        pytest.skip("no sample replay checked in")
    data = path.read_bytes()
    fields = known_fields(located, kv_pairs(data, located))
    assert fields["initialGold"] == 300
    assert fields["kvMode"] == 50
    assert fields["modeWord"] != 0
    assert fields["serverTimeUnixSeconds"] > 1_600_000_000
    assert fields["scalarBlockSha256"] == located["scalarSha"]
    assert fields["kvKeys"] == located["kvCount"]
    assert len(fields["kvRulesetSha256"]) == 64
    # 4 values + kv mode + ruleset + kv key count + block sha + score + terminator
    assert len(fields) == 9


def test_kv_ruleset_is_constant_across_supported_samples():
    """The 53 KV values are identical on every supported 5v5 sample.

    That makes the ruleset hash a mode/build fingerprint rather than a
    per-match value; if this fails, a rule set changed and cross-match
    comparisons need a note.
    """
    supported = _supported()
    if not supported:
        pytest.skip("no sample replay checked in")
    shas = set()
    for path, located in supported:
        data = path.read_bytes()
        shas.add(kv_ruleset_sha(kv_pairs(data, located)))
    assert len(shas) == 1, f"rule set drifted: {shas}"


def test_scalar_word_pairing_hypothesis_is_disproven():
    """`98/108` and `99/109` looked like value / value<<24 pairs.

    The samples disprove both: on mapId 20041 `w98=1` but `w108=0x20000`, and
    `w109` does not track `w99` at all.  Keeping the negative result pinned here
    stops the hypothesis from being re-derived as a fact.
    """
    supported = _supported()
    if not supported:
        pytest.skip("no sample replay checked in")
    break_108 = break_109 = False
    for path, located in supported:
        words = located["words"]
        if words[108] >> 24 != words[98]:
            break_108 = True
        if words[109] >> 24 != words[99]:
            break_109 = True
    assert break_108, "108 always equals 98<<24 now; revisit the hypothesis"
    assert break_109, "109 always equals 99<<24 now; revisit the hypothesis"

