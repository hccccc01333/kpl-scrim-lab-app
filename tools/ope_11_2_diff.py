"""Reproduce the 2026-11-02 `.ope` operator-stream boundary analysis.

Read-only.  It extracts the two local 11/2 operator streams, then:

1. validates the UILayout shape (u16 tag + exactly 75 ULEB values) and the
   boundary against the following SkillSlotOpe run;
2. re-segments the old fake walls 0xE79/0xCDC with the 4-varint MoveOpe
   layout and shows those bytes are ordinary Move/Common/UnityFrame records,
   not a MemoryData continuation;
3. runs the workspace parser (auto-detected record start) and reports whether
   each stream reaches EOF or where the current structural wall is;
4. checks that small MemoryData payloads are opaque memory dumps and that
   their lenvar is a byte length, not a continuation length.

The 30,116 / 24,946 / 18,748-byte “MemoryData” spans are NOT payloads:
frames 256..267 carry the unity clock in the third field (they are the tail
of a preceding Move/Skil record), so the parser now gates the payload form to
frames outside 256..267.  The dedicated wall/artifact/resync analysis lives in
``tools/ope_11_2_walls.py``.

Usage:
  python tools/ope_11_2_diff.py
  python tools/ope_11_2_diff.py --json out.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import operator_stream as OS  # noqa: E402
import replay_parser as RP  # noqa: E402

WALL_SAMPLES = {
    '20261102_161129': 0x0E79,
    '20261102_163751': 0x0CDC,
}


def read_stream(path: Path) -> bytes:
    inner = RP.inflate_raw(path.read_bytes()[1:], '.ope outer')
    _marker, _declared, stream = RP._locate_second_layer(inner)
    return stream


def uleb_all(buf: bytes):
    values, pos = [], 0
    while pos < len(buf):
        value = shift = 0
        while True:
            if pos >= len(buf):
                return None
            byte = buf[pos]
            pos += 1
            value |= (byte & 0x7F) << shift
            if not byte & 0x80:
                break
            shift += 7
            if shift > 35:
                return None
        values.append(value)
    return values


def uilayout_probe(stream: bytes) -> dict:
    offset = stream.find(bytes.fromhex('16b401'))
    if offset < 0:
        return {'found': False}
    start = offset + 3
    slots = stream.find(bytes.fromhex('13ae010001'), start)
    payload = stream[start:slots] if slots >= 0 else b''
    values = uleb_all(payload) if payload else None
    trailing_zero_varints = 0
    if values:
        for value in reversed(values):
            if value != 0:
                break
            trailing_zero_varints += 1
    return {
        'found': True,
        'offset': f'{offset:#x}',
        'tag': int.from_bytes(stream[offset + 1:offset + 3], 'little'),
        'payloadStart': f'{start:#x}',
        'firstSkillSlot': f'{slots:#x}' if slots >= 0 else None,
        'payloadBytes': len(payload),
        'varintCount': len(values) if values is not None else None,
        'trailingZeros': len(payload) - len(payload.rstrip(b'\x00')),
        'trailingZeroVarints': trailing_zero_varints,
    }


def segment_region(chain: list[dict], start: int, stop: int) -> list[dict]:
    """Show path records that overlap a region (they are ordinary records)."""
    rows = []
    for record in chain:
        record_start = record['offset']
        record_end = record_start + record['size']
        if record_end <= start or record_start >= stop:
            continue
        fields = dict(record['fields'])
        if 'data' in fields and isinstance(fields['data'], bytes):
            fields['dataLen'] = len(fields.pop('data'))
        if 'layout' in fields:
            fields['layout'] = f"<{len(fields['layout'])} varints>"
        rows.append({
            'offset': f'{record_start:#x}',
            'end': f'{record_end:#x}',
            'type': record['typeName'],
            'size': record['size'],
            'tentative': record['tentative'],
            'fields': fields,
        })
    return rows[:14]


def forward_path(stream: bytes, start: int = 0):
    """Any valid record chain from ``start``; returns records and furthest end."""
    layout = OS._layout_payload_size(stream)
    pred = {start: None}
    stack = [start]
    while stack:
        pos = stack.pop()
        if pos >= len(stream):
            continue
        for tier, plan in OS.LAYOUTS.get(stream[pos], ()):
            record = OS._consume(stream, pos, layout, plan)
            if record is None:
                continue
            end = record['end']
            if end not in pred:
                pred[end] = (pos, tier, plan, record)
                stack.append(end)
    furthest = max(pred)
    chain, cur = [], furthest
    while pred.get(cur):
        pos, tier, plan, record = pred[cur]
        record['type'] = stream[pos]
        record['typeName'] = OS.TYPE_NAMES.get(stream[pos], f'0x{stream[pos]:02x}')
        record['size'] = record['end'] - pos
        record['tentative'] = tier == OS.TENTATIVE
        del record['end']
        chain.append(record)
        cur = pos
    chain.reverse()
    return chain, furthest


def memory_probe(stream: bytes) -> dict:
    """MemoryData stats along the furthest structural chain."""
    try:
        records, ambiguities, start = OS._parse_with_start(stream)
        decoded = True
        wall = None
    except OS.OperatorStreamError as error:
        decoded = False
        start = None
        wall = str(error)
        records, furthest = forward_path(stream)
        ambiguities = 0
        wall = f'{wall}；structural chain ends at {furthest:#x}'
    memory = [record for record in records if record['type'] == 0x10]
    payloads = [record['fields'].get('data', b'') for record in memory
                if len(record['fields'].get('data', b'')) <= 2048]
    repeated = max((payloads.count(payload) for payload in payloads), default=0)
    end_valid = end_valid_with_varint = 0
    for record in memory:
        end = record['offset'] + record['size']
        if end >= len(stream):
            continue
        if stream[end] in OS.LAYOUTS:
            end_valid += 1
        try:
            _value, after = OS._varint(stream, end)
        except IndexError:
            continue
        if after < len(stream) and stream[after] in OS.LAYOUTS:
            end_valid_with_varint += 1
    return {
        'decoded': decoded,
        'start': start,
        'ambiguities': ambiguities,
        'tentativeCount': sum(1 for record in records if record['tentative']),
        'tentativeBytes': sum(record['size'] for record in records
                              if record['tentative']),
        'wall': wall,
        'recordCount': len(records),
        'memoryCount': len(memory),
        'memoryPayloadEndOnValidType': end_valid,
        'memoryPayloadEndOnValidTypeAfterOneVarint': end_valid_with_varint,
        'smallMemoryCount': len(payloads),
        'smallMemorySizes': sorted(len(p) for p in payloads),
        'repeatedPayloadCount': repeated,
        'allPayloadsAreByteStrings': all(isinstance(p, bytes) for p in payloads),
    }


def probe(path: Path) -> dict:
    stream = read_stream(path)
    key = next((k for k in WALL_SAMPLES if k in path.name), None)
    wall = WALL_SAMPLES.get(key)
    chain, furthest = forward_path(stream)
    result = {
        'file': path.name,
        'operatorStreamBytes': len(stream),
        'first64': stream[:64].hex(' '),
        'uilayout': uilayout_probe(stream),
        'parse': memory_probe(stream),
        'structuralChain': {
            'recordCount': len(chain),
            'furthestEnd': f'{furthest:#x}',
        },
    }
    if wall is not None and wall < len(stream):
        result['oldWall'] = {
            'offset': f'{wall:#x}',
            'type': f'0x{stream[wall]:02x}',
            'context': stream[wall:wall + 24].hex(' '),
            'segmentation': segment_region(chain, max(0, wall - 48), wall + 48),
        }
    return result


def cross_sample_uilayout_count() -> dict:
    counts = {}
    for path in sorted((ROOT / 'data' / 'replays' / 'samples').rglob('*.ope')):
        try:
            stream = read_stream(path)
        except Exception:
            continue
        info = uilayout_probe(stream)
        if info.get('found') and info.get('varintCount') is not None:
            counts[info['varintCount']] = counts.get(info['varintCount'], 0) + 1
    return {'byVarintCount': counts,
            'samples': sum(counts.values()),
            'filesScanned': len(list((ROOT / 'data' / 'replays' / 'samples').rglob('*.ope')))}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--json', default=None)
    args = parser.parse_args()

    paths = sorted((ROOT / 'data' / 'replays' / 'samples').glob('20261102_*/*.ope'))
    if len(paths) < 2:
        print('expected two 20261102 .ope files', file=sys.stderr)
        return 1
    report = {
        'samples': [probe(path) for path in paths[:2]],
        'uilayoutAcrossCorpus': cross_sample_uilayout_count(),
        'note': 'read-only static analysis; MemoryData payloads are opaque '
                'memory dumps, so lenvar is a byte length, not a continuation.',
    }
    sibling = sorted((ROOT / 'data' / 'replays' / 'samples')
                     .rglob('20261101_182452*.ope'))
    if sibling:
        sibling_stream = read_stream(sibling[0])
        report['sibling20261101'] = {
            'file': sibling[0].name,
            'operatorStreamBytes': len(sibling_stream),
            'parse': memory_probe(sibling_stream),
        }
    text = json.dumps(report, ensure_ascii=False, indent=1)
    print(text)
    if args.json:
        Path(args.json).write_text(text, encoding='utf-8')
        print('out:', args.json)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
