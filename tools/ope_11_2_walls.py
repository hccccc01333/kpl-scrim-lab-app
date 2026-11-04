"""Read-only boundary analysis for the 2026-11-02 `.ope` operator-stream walls.

The two 11/2 samples used to wall at 0x1991E (type 0x24) and 0x38D26
(type 0x91).  This tool separates three questions:

1. Are the wall bytes record types?  For each wall it finds the varint that
   crosses the boundary (`ed 24` in 11/2a, `91 27` in 11/2b), reports the
   +/-1..4 boundary shifts and the first shift that reaches a valid chain.
2. Are the huge MemoryData records real?  It audits every payload-form `0x10`
   record (frame + byte length) and scans for the alternative `10 <frame
   256..267> <unity>` byte pattern.  The latter is the tail of a preceding
   Move/Skil record: its third field is the unity clock, not a length, so the
   30,116 / 18,748 / 24,946-byte "payloads" are false DP jumps.
3. What is the conservative wall?  It reports the current linear wall, the
   furthest split-tail resync preview (labelled repair, not parser output),
   and the unity-clock monotonicity of the resulting chain.

Read-only.  It never starts/connects to the game, logs in, injects, or
modifies a replay/runtime file.

Usage:
  python tools/ope_11_2_walls.py
  python tools/ope_11_2_walls.py --json out.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools'))

import operator_stream as OS  # noqa: E402
from ope_11_2_diff import read_stream  # noqa: E402

ARTIFACT_LOW, ARTIFACT_HIGH = 256, 267
BIG_PAYLOAD = 1024
ORIGINAL_WALLS = {
    '20261102_161129': 0x1991E,
    '20261102_163751': 0x38D26,
}
# The two records named in the task: 30,116 B (11/2a) and 9,750 B (11/2b).
TARGET_RECORDS = {
    '20261102_161129': [0x12374],
    '20261102_163751': [0x3670B],
}


def uleb(data, pos):
    value = shift = 0
    while True:
        if pos >= len(data):
            raise IndexError
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, pos
        shift += 7
        if shift > 35:
            raise IndexError


def reachable(stream, start=0):
    return OS._reachable(stream, OS._layout_payload_size(stream), start)


def forward_path(stream, start=0):
    """Minimum-uncertainty forward path to the furthest reachable offset."""
    layout = OS._layout_payload_size(stream)
    reach = set()
    stack = [start]
    edges = {}
    while stack:
        pos = stack.pop()
        if pos in reach or pos >= len(stream):
            continue
        reach.add(pos)
        if stream[pos] not in OS.LAYOUTS:
            continue
        options = []
        for tier, plan in OS.LAYOUTS[stream[pos]]:
            record = OS._consume(stream, pos, layout, plan)
            if record is None:
                continue
            options.append((tier, plan, record))
            if record['end'] not in reach:
                stack.append(record['end'])
        edges[pos] = options
    best = {start: (0, 0, 0)}
    prev = {}
    for pos in sorted(reach):
        if pos not in best:
            continue
        base = best[pos]
        for tier, plan, record in edges.get(pos, ()):
            end = record['end']
            size = end - pos
            cost = (base[0] + (size if tier == OS.TENTATIVE else 0),
                    base[1] + (1 if tier == OS.TENTATIVE else 0),
                    base[2] + 1)
            if end not in best or cost < best[end]:
                best[end] = cost
                prev[end] = (pos, tier, plan, record)
    target = max(best)
    chain = []
    cur = target
    while cur != start:
        pos, tier, plan, record = prev[cur]
        record = dict(record)
        record['type'] = stream[pos]
        record['typeName'] = OS.TYPE_NAMES.get(stream[pos], f'0x{stream[pos]:02x}')
        record['size'] = cur - pos
        record['tentative'] = tier == OS.TENTATIVE
        chain.append(record)
        cur = pos
    chain.reverse()
    return chain, target, max(reach)


def shift_scan(stream, wall, back=4, forward=8):
    rows = []
    for shift in range(-back, forward + 1):
        start = wall + shift
        if start < 0 or start >= len(stream):
            continue
        reach = reachable(stream, start)
        furthest = max(reach) if reach else start
        rows.append({
            'shift': shift,
            'start': start,
            'type': f'0x{stream[start]:02x}',
            'validType': stream[start] in OS.LAYOUTS,
            'furthest': furthest,
            'furthestFraction': round(furthest / len(stream), 4),
            'reachablePositions': len(reach),
        })
    return rows


def varint_span_around(stream, wall):
    """Describe varints that touch ``wall``.

    ``completesVarint`` means the wall byte is the final byte of a ULEB that
    started before the wall; ``startsVarint`` means the wall byte is the first
    byte of a multi-byte ULEB that ends after the wall.
    """
    out = {'completesVarint': None, 'startsVarint': None}
    for back in range(1, 5):
        start = wall - back
        if start < 0 or not stream[start] & 0x80:
            continue
        try:
            value, end = uleb(stream, start)
        except IndexError:
            continue
        if end > wall:
            out['completesVarint'] = {
                'start': start, 'end': end, 'value': value,
                'byteOffset': wall - start,
            }
            break
    if stream[wall] & 0x80:
        try:
            value, end = uleb(stream, wall)
            if end > wall + 1:
                out['startsVarint'] = {'value': value, 'end': end}
        except IndexError:
            pass
    return out


def _first_unity(stream, start, end, minimum=1000):
    """First fully-contained UnityFrameOpe record in a window."""
    values = []
    for pos in range(max(0, start), min(len(stream), end)):
        if stream[pos] != 0x01:
            continue
        try:
            value, value_end = uleb(stream, pos + 1)
        except IndexError:
            continue
        if value_end > end:
            continue
        if minimum < value < 10_000_000:
            values.append((pos, value))
    return values


def _last_unity_before(chain, offset):
    for record in reversed(chain):
        if record['offset'] >= offset:
            continue
        if record['type'] == 0x01:
            value = record['fields'].get('unityFrame')
            if isinstance(value, int) and value > 100:
                return value
        if record['type'] in (0x00, 0x02) and 'unityFrame' in record['fields']:
            value = record['fields']['unityFrame']
            if isinstance(value, int) and value > 100:
                return value
        # Move's unity appears as the last/highest m-varint in the 4/5/6/7-var
        # variants; use the max value to avoid picking a small degree/ping.
        if record['type'] == 0x06:
            values = [value for key, value in record['fields'].items()
                      if key != 'frame' and isinstance(value, int) and value > 100]
            if values:
                return max(values)
    return None


def wall_report(stream, name, wall):
    scan = shift_scan(stream, wall)
    best = max(scan, key=lambda row: (row['furthest'], -abs(row['shift'])))
    fragments = varint_span_around(stream, wall)
    first_valid = next((row for row in scan
                        if row['shift'] > 0 and row['validType']
                        and row['reachablePositions'] > 2), None)
    before = _first_unity(stream, wall - 96, wall)
    # Prefer the forward split-record completion for the unity ledger; the
    # closest-to-zero negative shift can be a resync into the payload.
    reference = first_valid or best
    after_position = wall + reference['shift']
    after = _first_unity(stream, after_position, after_position + 96)
    ledger = None
    if before and after:
        ledger = {
            'lastUnityBefore': before[-1][1],
            'firstUnityAfter': after[0][1],
            'monotone': after[0][1] >= before[-1][1],
        }
    return {
        'sample': name,
        'wall': wall,
        'typeByte': stream[wall],
        'context': stream[max(0, wall - 16):wall + 16].hex(' '),
        'varint': fragments,
        'shiftScan': scan,
        'firstValidShift': first_valid,
        'bestShift': best,
        'unityClock': ledger,
    }


def _payload_record_audit(stream, chain, record):
    offset = record['offset']
    frame = record['fields'].get('frame')
    third, header_end = uleb(stream, offset + 3)
    payload = record['fields'].get('data', b'')
    payload_end = header_end + len(payload)
    after = _first_unity(stream, payload_end, payload_end + 96)
    return {
        'offset': offset,
        'frame': frame,
        'thirdField': third,
        'form': 'payload',
        'payloadBytes': len(payload),
        'payloadEnd': payload_end,
        'nextByteValidType': payload_end < len(stream)
                              and stream[payload_end] in OS.LAYOUTS,
        'previousUnity': _last_unity_before(chain, offset),
        'nextUnityAfterPayload': after[0][1] if after else None,
        'thirdEqualsPayloadLength': third == len(payload),
        'payloadHead': payload[:12].hex(' '),
    }


def artifact_scan(stream, limit=64):
    """Find `10 <frame 256..267> <unity>` byte patterns that are not records.

    The third field is compared with the first UnityFrame value after the
    header.  When it matches within +/-16 the bytes are the tail of a
    preceding record whose last varint is the unity clock.
    """
    rows = []
    for pos in range(len(stream) - 6):
        if stream[pos] != 0x10:
            continue
        frame = int.from_bytes(stream[pos + 1:pos + 3], 'little')
        if not (ARTIFACT_LOW <= frame <= ARTIFACT_HIGH):
            continue
        try:
            third, header_end = uleb(stream, pos + 3)
        except IndexError:
            continue
        after = _first_unity(stream, header_end, header_end + 160)
        if not after:
            continue
        next_unity = after[0][1]
        if abs(third - next_unity) > 16:
            continue
        rows.append({
            'offset': pos,
            'frame': frame,
            'thirdField': third,
            'nextUnity': next_unity,
            'delta': third - next_unity,
            'context': stream[max(0, pos - 6):pos + 10].hex(' '),
        })
        if len(rows) >= limit:
            break
    return rows


def target_audit(stream, offsets):
    """Audit the exact records named by the task, whatever the chain does."""
    rows = []
    for offset in offsets:
        if offset + 3 >= len(stream) or stream[offset] != 0x10:
            continue
        frame = int.from_bytes(stream[offset + 1:offset + 3], 'little')
        try:
            third, header_end = uleb(stream, offset + 3)
        except IndexError:
            continue
        record = OS._consume(stream, offset, None, OS.LAYOUTS[0x10][0][1])
        after = _first_unity(stream, header_end, header_end + 160)
        next_unity = after[0][1] if after else None
        rows.append({
            'offset': offset,
            'frame': frame,
            'thirdField': third,
            'payloadFormAccepted': record is not None and 'data' in record['fields'],
            'payloadBytes': (len(record['fields']['data'])
                             if record is not None and 'data' in record['fields']
                             else None),
            'payloadEnd': (record['end'] if record is not None else None),
            'nextByteValidType': (record is not None and record['end'] < len(stream)
                                  and stream[record['end']] in OS.LAYOUTS),
            'nextUnityAfterHeader': next_unity,
            'thirdMinusNextUnity': None if next_unity is None else third - next_unity,
        })
    return rows


def memory_audit(stream):
    chain, _target, _reach = forward_path(stream)
    payloads = [_payload_record_audit(stream, chain, record)
                for record in chain if record['type'] == 0x10]
    return {
        'payloadCount': len(payloads),
        'bigPayloadCount': sum(1 for row in payloads
                               if row['payloadBytes'] > BIG_PAYLOAD),
        'artifacts': artifact_scan(stream),
        'bigPayloads': [row for row in payloads
                        if row['payloadBytes'] > BIG_PAYLOAD],
    }


def resync_preview(stream, max_steps=10):
    """Split-tail repair preview: after a payload-form MemoryData whose payload
    end is not a valid record start, resume at the boundary shift that reaches
    furthest.  This is a labelled repair, not parser output."""
    start = 0
    segments = []
    for _step in range(max_steps):
        _chain, target, _reach = forward_path(stream, start)
        if target >= len(stream):
            segments.append({'start': start, 'end': target, 'eof': True})
            break
        candidates = []
        for pos in range(max(0, target - 70_000), target):
            if stream[pos] != 0x10:
                continue
            record = OS._consume(stream, pos, OS._layout_payload_size(stream),
                                 OS.LAYOUTS[0x10][0][1])
            if (record is not None and 'data' in record['fields']
                    and record['end'] == target
                    and len(record['fields']['data']) > 0):
                candidates.append(pos)
        scan = shift_scan(stream, target, back=4, forward=16)
        best = max(scan, key=lambda row: (row['furthest'], -abs(row['shift'])))
        segments.append({
            'start': start,
            'wall': target,
            'wallType': stream[target],
            'kind': 'memory-data-split' if candidates else 'generic-boundary',
            'payloadFormMemoryData': candidates,
            'resyncShift': best['shift'],
            'resyncStart': best['start'],
            'resyncFurthest': best['furthest'],
            'resyncFraction': best['furthestFraction'],
        })
        if best['furthest'] <= target:
            break
        start = best['start']
    return segments


def repaired_chain(stream, max_steps=12):
    """Concatenate the resync-preview segments for a unity-clock audit."""
    start = 0
    chain = []
    segments = []
    for _step in range(max_steps):
        part, target, _reach = forward_path(stream, start)
        chain.extend(part)
        if target >= len(stream):
            break
        scan = shift_scan(stream, target, back=4, forward=16)
        best = max(scan, key=lambda row: (row['furthest'], -abs(row['shift'])))
        segments.append((target, best['shift'], best['start'], best['furthest']))
        if best['furthest'] <= target:
            break
        start = best['start']
    return chain, segments


def unity_monotonicity(chain, minimum=1000):
    """Unity clock from explicit UnityFrameOpe records only.

    Field names on Skil/SkillUse records are positional and not a clock, so
    only type 0x01 is used here.  Values below ``minimum`` are usually a
    misread of the following record, so they are skipped.
    """
    observations = [(record['offset'], record['fields']['unityFrame'])
                    for record in chain
                    if record['type'] == 0x01
                    and isinstance(record['fields'].get('unityFrame'), int)
                    and record['fields']['unityFrame'] >= minimum]
    decreases = [(prev, cur) for prev, cur in zip(observations, observations[1:])
                 if cur[1] < prev[1]]
    return {
        'minimum': minimum,
        'observations': len(observations),
        'decreases': len(decreases),
        'firstDecreases': [{'from': f'{a[0]:#x}', 'to': f'{b[0]:#x}',
                            'fromUnity': a[1], 'toUnity': b[1]}
                           for a, b in decreases[:5]],
    }


def sample_report(path):
    stream = read_stream(path)
    name = '_'.join(path.stem.split('_')[:2])
    try:
        records, ambiguities, start = OS._parse_with_start(stream)
        parse = {'decoded': True, 'streamStart': start,
                 'recordCount': len(records), 'ambiguities': ambiguities,
                 'tentativeCount': sum(1 for r in records if r['tentative']),
                 'tentativeBytes': sum(r['size'] for r in records if r['tentative'])}
        chain = records
    except OS.OperatorStreamError as error:
        parse = {'decoded': False, 'wall': str(error)}
        chain, _target, _reach = forward_path(stream)
    wall = max(reachable(stream)) if not parse['decoded'] else len(stream)
    repaired, repair_segments = repaired_chain(stream)
    report = {
        'file': path.name,
        'operatorStreamBytes': len(stream),
        'parse': parse,
        'linearWall': wall,
        'linearWallContext': stream[wall:wall + 24].hex(' ') if wall < len(stream) else '',
        'unity': unity_monotonicity(chain),
        'repairedUnity': unity_monotonicity(repaired),
        'repairSegments': len(repair_segments),
        'memory': memory_audit(stream),
        'targetAudit': target_audit(stream, TARGET_RECORDS.get(name, [])),
        'resyncPreview': resync_preview(stream),
    }
    original = ORIGINAL_WALLS.get(name)
    if original is not None and original < len(stream):
        report['originalWall'] = wall_report(stream, name, original)
    if not parse['decoded']:
        report['linearWallReport'] = wall_report(stream, name, wall)
    return report


def sibling_11_1_report():
    matches = sorted((ROOT / 'data' / 'replays' / 'samples').rglob('20261101_182452*.ope'))
    if not matches:
        return None
    stream = read_stream(matches[0])
    try:
        records, ambiguities, start = OS._parse_with_start(stream)
        return {
            'file': matches[0].name,
            'operatorStreamBytes': len(stream),
            'decoded': True,
            'streamStart': start,
            'recordCount': len(records),
            'ambiguities': ambiguities,
            'tentativeCount': sum(1 for r in records if r['tentative']),
            'tentativeBytes': sum(r['size'] for r in records if r['tentative']),
            'memory': memory_audit(stream),
        }
    except OS.OperatorStreamError as error:
        return {'file': matches[0].name, 'decoded': False, 'wall': str(error)}


def print_text(report):
    for sample in report['samples']:
        print('=' * 100)
        print(sample['file'])
        print('  stream bytes:', sample['operatorStreamBytes'])
        print('  parse:', 'EOF' if sample['parse']['decoded'] else 'WALL')
        if sample['parse']['decoded']:
            print(f"    records={sample['parse']['recordCount']} "
                  f"ambiguities={sample['parse']['ambiguities']} "
                  f"tentative={sample['parse']['tentativeCount']}")
        else:
            print('   ', sample['parse']['wall'])
        print(f"  linear wall: {sample['linearWall']:#x} "
              f"context {sample['linearWallContext']}")
        print('  unity clock (UnityFrameOpe only):', sample['unity'])
        print('  repaired unity clock:', sample['repairedUnity'])
        print('  repair segments:', sample['repairSegments'])
        memory = sample['memory']
        print(f"  payload-form MemoryData: {memory['payloadCount']} "
              f"(big={memory['bigPayloadCount']})")
        for row in memory['bigPayloads']:
            print(f"    payload {row['offset']:#08x} frame={row['frame']} "
                  f"len={row['payloadBytes']} end={row['payloadEnd']:#x} "
                  f"endValid={row['nextByteValidType']} "
                  f"third==len={row['thirdEqualsPayloadLength']} "
                  f"head={row['payloadHead']}")
        print(f"  frame 256..267 artifact candidates: {len(memory['artifacts'])}")
        for row in memory['artifacts'][:16]:
            print(f"    artifact {row['offset']:#08x} frame={row['frame']} "
                  f"third={row['thirdField']} nextUnity={row['nextUnity']} "
                  f"delta={row['delta']}")
        for row in sample['targetAudit']:
            print(f"    target {row['offset']:#08x} frame={row['frame']} "
                  f"third={row['thirdField']} payloadForm="
                  f"{row['payloadFormAccepted']} bytes={row['payloadBytes']} "
                  f"end={row['payloadEnd']} endValid={row['nextByteValidType']} "
                  f"dNext={row['thirdMinusNextUnity']}")
        for step in sample['resyncPreview']:
            if step.get('eof'):
                print(f"    resync: EOF at {step['end']:#x}")
            else:
                print(f"    resync [{step['kind']}] wall {step['wall']:#x} "
                      f"type={step['wallType']:#04x} "
                      f"payloadMD={[hex(p) for p in step['payloadFormMemoryData']]} "
                      f"shift={step['resyncShift']:+d} -> {step['resyncStart']:#x} "
                      f"furthest={step['resyncFurthest']:#x} "
                      f"({step['resyncFraction']:.1%})")
        original = sample.get('originalWall')
        if original:
            print(f"  original wall {original['wall']:#x} type={original['typeByte']:#04x}")
            print(f"    varint: {original['varint']}")
            print(f"    first valid shift: {original['firstValidShift']}")
            print(f"    best shift: {original['bestShift']}")
            print(f"    unity: {original['unityClock']}")
            for row in original['shiftScan']:
                if -4 <= row['shift'] <= 8:
                    print(f"      {row['shift']:+d} {row['start']:#x} {row['type']} "
                          f"valid={row['validType']} furthest={row['furthest']:#x} "
                          f"({row['furthestFraction']:.1%})")
        linear = sample.get('linearWallReport')
        if linear:
            print(f"  linear wall scan:")
            for row in linear['shiftScan']:
                if -4 <= row['shift'] <= 8:
                    print(f"      {row['shift']:+d} {row['start']:#x} {row['type']} "
                          f"valid={row['validType']} furthest={row['furthest']:#x} "
                          f"({row['furthestFraction']:.1%})")
    sibling = report.get('sibling20261101')
    if sibling:
        print('=' * 100)
        print(sibling['file'])
        print(f"  decoded={sibling.get('decoded')} records={sibling.get('recordCount')} "
              f"ambiguities={sibling.get('ambiguities')} "
              f"tentative={sibling.get('tentativeCount')} "
              f"tentativeBytes={sibling.get('tentativeBytes')}")
        memory = sibling.get('memory') or {}
        print(f"  payload-form MemoryData: {memory.get('payloadCount')} "
              f"(big={memory.get('bigPayloadCount')}) "
              f"artifactCandidates={len(memory.get('artifacts', []))}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--json', default=None)
    args = parser.parse_args()
    paths = sorted((ROOT / 'data' / 'replays' / 'samples').glob('20261102_*/*.ope'))
    if len(paths) < 2:
        print('expected two 20261102 .ope files', file=sys.stderr)
        return 1
    report = {
        'note': 'read-only static analysis.  Payload-form MemoryData = frame + '
                'byte-length memory dump.  Frames 256..267 are not a payload '
                'form: the third field is the unity clock of the preceding '
                'Move/Skil record, so the 30,116/18,748/24,946-byte spans are '
                'DP artifacts.  resyncPreview is a labelled repair, not parser '
                'output.',
        'samples': [sample_report(path) for path in paths[:2]],
        'sibling20261101': sibling_11_1_report(),
    }
    text = json.dumps(report, ensure_ascii=False, indent=1)
    print_text(report)
    if args.json:
        Path(args.json).write_text(text, encoding='utf-8')
        print('out:', args.json)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
