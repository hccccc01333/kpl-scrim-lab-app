"""Lightweight 2026-11-02 `.ope` operator-stream probe.

Read-only.  Extracts the second-layer operator stream from both 11/2 samples
and reports:

- the UILayout record shape (u16 tag + 75 ULEB values) and the following
  SkillSlotOpe boundary;
- the legacy `stream[7:11]` value (kept only as a legacy hint);
- whether the workspace parser consumes the stream to EOF, or the current
  structural wall and its context.

For the full old-wall/MemoryData differential see tools/ope_11_2_diff.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import operator_stream as OS  # noqa: E402
import replay_parser as RP  # noqa: E402


def uleb_count(buf: bytes):
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


def probe(path: Path) -> dict:
    inner = RP.inflate_raw(path.read_bytes()[1:], '.ope outer')
    marker, declared, stream = RP._locate_second_layer(inner)
    report = {
        'file': path.name,
        'innerBytes': len(inner),
        'secondLayerMarker': hex(marker),
        'declaredRemaining': declared,
        'operatorStreamBytes': len(stream),
        'legacyStream7to11': int.from_bytes(stream[7:11], 'little'),
        'first64': stream[:64].hex(' '),
    }
    uilayout = stream.find(bytes.fromhex('16b401'))
    if uilayout >= 0:
        start = uilayout + 3
        slots = stream.find(bytes.fromhex('13ae010001'), start)
        payload = stream[start:slots] if slots >= 0 else b''
        values = uleb_count(payload) if payload else None
        report['uilayout'] = {
            'offset': hex(uilayout),
            'tag': int.from_bytes(stream[uilayout + 1:uilayout + 3], 'little'),
            'payloadStart': hex(start),
            'payloadBytes': len(payload),
            'varintCount': len(values) if values is not None else None,
            'firstSkillSlot': hex(slots) if slots >= 0 else None,
        }
    try:
        summary = OS.summarize(stream)
        report['parse'] = {
            'decoded': True,
            'streamStart': summary['streamStart'],
            'recordCount': summary['recordCount'],
            'tentativeCount': summary['tentativeCount'],
            'tentativeBytes': summary['tentativeBytes'],
            'ambiguousChoices': summary['ambiguousChoices'],
        }
    except OS.OperatorStreamError as error:
        report['parse'] = {'decoded': False, 'wall': str(error)}
    return report


def main() -> int:
    paths = sorted((ROOT / 'data' / 'replays' / 'samples').glob('20261102_*/*.ope'))
    if len(paths) < 2:
        print('expected two 20261102 .ope files', file=sys.stderr)
        return 1
    print(json.dumps([probe(path) for path in paths[:2]],
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
