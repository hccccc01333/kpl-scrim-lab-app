"""Read-only field discovery; no opcode semantics or actor identities are certified.

Run: python tools/replay_field_probe.py --output data/replays/_analysis/field_probe.json
Only complete payloads that reconstruct byte-for-byte are included. Unknown and
incomplete records are counted, never recovered by scanning arbitrary byte values.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'data/replays/_analysis/tools'))
from abc_tags_full import find_stream, parse_payload


def messages(payload):
    """Validate the existing research tokenizer by exact reconstruction."""
    parsed, ok = parse_payload(payload)
    if not ok:
        return None
    rebuilt = bytearray(payload[:1])
    result = []
    for message in parsed:
        offset = len(rebuilt)
        if message[0] == 's':
            _, tag, data = message
            rebuilt.extend(bytes([tag]) + data)
        else:
            _, tag, actor, flag, data = message
            header = bytes([tag]) + actor.to_bytes(2, 'big') + bytes([flag])
            if tag == 1:
                header += bytes([len(data)])
            rebuilt.extend(header + data)
            result.append((offset, tag, actor, flag, data))
    return result if bytes(rebuilt) == payload else None


def header_versions(blob):
    result, pos = [], 0
    for _ in range(4):
        if pos >= len(blob) or pos + 1 + blob[pos] > len(blob):
            break
        size = blob[pos]
        result.append(blob[pos + 1:pos + 1 + size].decode('ascii', 'replace'))
        pos += 1 + size
    return result


def probe(paths):
    files, selected = [], []
    shapes = Counter()
    pairs = []
    by_file_actor = defaultdict(list)
    for path in paths:
        blob = path.read_bytes()
        records, end = find_stream(blob)
        accepted = rejected = count_mismatch = 0
        for record in records:
            payload = record['payload']
            parsed = messages(payload)
            if parsed is None:
                rejected += 1
                continue
            accepted += 1
            original, _ = parse_payload(payload)
            count_mismatch += bool(payload and payload[0] != len(original))
            for offset, tag, actor, flag, data in parsed:
                sub = data[0] if data else None
                shapes[(tag, sub, len(data))] += 1
                if tag != 2 and sub not in (0x39, 0x01, 0x8a, 0x29):
                    continue
                item = dict(file=path.name, recordSeq=record['seq'],
                            offset=record['off'] + 3 + offset,
                            tag=tag, actorKey=actor, flag=flag,
                            dataHex=data.hex())
                if tag == 1 and sub == 0x39 and len(data) == 9:
                    a, b = struct.unpack('>ii', data[1:])
                    item['candidateI32BE'] = [a, b]
                    pairs.append((a, b))
                    by_file_actor[(path.name, actor)].append((a, b))
                selected.append(item)
        files.append(dict(file=path.name, sha256=hashlib.sha256(blob).hexdigest(),
                          versions=header_versions(blob), records=len(records),
                          accepted=accepted, rejected=rejected,
                          declaredCountMismatch=count_mismatch,
                          streamStart=records[0]['off'] if records else None,
                          streamEnd=end, unexaminedSuffixBytes=len(blob)-end))
    deltas = [(b[0]-a[0], b[1]-a[1]) for values in by_file_actor.values()
              for a, b in zip(values, values[1:])]
    candidate = dict(count=len(pairs), groups=len(by_file_actor),
                     rangeA=[min(a for a, _ in pairs), max(a for a, _ in pairs)] if pairs else None,
                     rangeB=[min(b for _, b in pairs), max(b for _, b in pairs)] if pairs else None,
                     adjacentPairs=len(deltas),
                     adjacentWithin2000=sum(abs(a)<=2000 and abs(b)<=2000 for a,b in deltas))
    return dict(schema='replay-field-probe-v1', files=files,
                shapes=[dict(tag=t, sub=s, length=n, count=c)
                        for (t,s,n),c in shapes.most_common()],
                candidate39=candidate, selected=selected,
                limitations=['Actor keys are not certified hero IDs.',
                             'Exact reconstruction validates boundaries, not semantics.',
                             'Stream discovery and grammar are inherited research heuristics.',
                             'Rejected records and bytes outside this stream remain unexamined.',
                             'candidateI32BE is a numeric interpretation, not a position label.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples', type=Path, default=ROOT/'data/replays/samples/abc_batch')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    paths = sorted(args.samples.glob('*.abc'))
    if not paths:
        parser.error('No .abc samples found')
    result = probe(paths)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(files=len(result['files']),
                          accepted=sum(f['accepted'] for f in result['files']),
                          rejected=sum(f['rejected'] for f in result['files']),
                          candidate39=result['candidate39'],
                          selected=len(result['selected']), output=str(args.output)), indent=2))


if __name__ == '__main__':
    main()
