"""Tests for the opt-in boundary-repair operator-stream parser.

The repair is accounting, not guessing: a clean stream must produce zero
repairs, and a damaged stream must record exactly where it resynchronised.
"""
from __future__ import annotations

import sys
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from operator_stream import (  # noqa: E402
    REPAIR_MAX_SHIFT,
    parse_with_repair,
    repair_summary,
)


def varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def clean_body() -> bytes:
    # Fixed-shape records only: a 2-byte frame followed by a varint is
    # ambiguous with a longer record, and the DP legitimately prefers the longer
    # reading.  Unambiguous shapes keep this test about the repair accounting.
    return (b'\x13\xae\x01\x00\x01'          # SkillSlot (5 B)
            + b'\x01' + varint(28691)        # UnityFrame (4 B)
            + b'\x13\xae\x01\x0b')           # SkillSlot without value (4 B)


def test_clean_stream_needs_no_repair():
    records, repairs, end = parse_with_repair(clean_body(), 0)
    assert repairs == []
    assert end == len(clean_body())
    assert records
    assert all(record['type'] in range(0x20) for record in records)


def test_damaged_stream_records_the_resync_point():
    body = clean_body()
    cut = 5                                    # inside the first SkillSlot record
    damaged = body[:cut] + b'\xff' + body[cut:]
    records, repairs, end = parse_with_repair(damaged, 0)
    assert len(repairs) == 1
    repair = repairs[0]
    # The DP may consume part of the damaged region before it stalls, so the wall
    # lands near -- not exactly at -- the injected byte.
    assert abs(repair['wall'] - cut) <= 3
    assert 0 < abs(repair['shift']) <= REPAIR_MAX_SHIFT
    assert repair['resume'] == repair['wall'] + repair['shift']
    assert repair['dpReachAfter'] > repair['dpReachBefore']
    assert end > cut
    assert records


def test_repair_summary_reports_coverage_and_no_clock_claim_on_clean_stream():
    summary = repair_summary(clean_body(), 0)
    assert summary['mode'] == 'dp-with-repair'
    assert summary['repairCount'] == 0
    assert summary['reachedEnd'] is True
    assert summary['trailingBytes'] == 0
    assert summary['coveragePct'] == 100.0
    assert summary['unityRegressions'] == 0


def _stream_from_ope(path: Path) -> bytes:
    import replay_parser as rp

    raw = path.read_bytes()
    inner = zlib.decompressobj(-15).decompress(raw[1:])
    _pos, _declared, stream = rp._locate_second_layer(inner)
    return stream


def _first_ope(pattern: str) -> Path | None:
    matches = sorted((ROOT / 'data/replays/samples').rglob(pattern))
    return matches[0] if matches else None


@pytest.mark.parametrize('pattern', ['20261101_182452/*.ope'])
def test_single_player_sample_reaches_end_without_repairs(pattern):
    sample = _first_ope(pattern)
    if sample is None:
        pytest.skip('sample replay not available')
    summary = repair_summary(_stream_from_ope(sample), 0)
    assert summary['repairCount'] == 0
    # These streams can end with a single undecodable byte; that is a trailing
    # fragment, not a repair point.
    assert summary['trailingBytes'] <= 1
    assert summary['coveragePct'] > 99.99
    assert summary['recordCount'] > 1000


@pytest.mark.parametrize('pattern', ['20261102_161129/*.ope'])
def test_damaged_two_layer_sample_records_bounded_repairs(pattern):
    sample = _first_ope(pattern)
    if sample is None:
        pytest.skip('sample replay not available')
    summary = repair_summary(_stream_from_ope(sample), 0)
    assert summary['repairCount'] <= 16
    assert summary['coveragePct'] > 99.9
    assert summary['trailingBytes'] <= 2
    for repair in summary['repairs']:
        assert repair['shift'] != 0
        assert abs(repair['shift']) <= REPAIR_MAX_SHIFT
        assert repair['dpReachAfter'] > repair['dpReachBefore']
