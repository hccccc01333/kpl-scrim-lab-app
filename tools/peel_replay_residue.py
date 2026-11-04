#!/usr/bin/env python3
"""Peel known .abc structures and keep the residual bytes.

Read-only for the input replays. For each replay this writes a working copy
of the classification, never edits the original:

  known     parsed or identified container/field
  opaque    recognized container whose fields are not fully decoded
  residual  bytes not assigned to any identified structure

The peeled regions are:
  * .abc header fields (parsed prefix known; unparsed header tail residual)
  * CSPkg 1075 envelope and its inner beginload prefix/player blocks
  * CSPkg 1077 beginfight
  * frame records: 10-byte framing, payload tags/messages
  * CSPkg 1251 MVP score packet

No semantic conclusion is drawn from the residual. The output is a manifest
plus residual.bin / opaque.bin and offset-labelled segment lists.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import replay_parser as rp  # noqa: E402

# 5247758 0x02 body lengths observed in the normal-5v5 samples.
# 0x84 and 0x86 are 5 bytes here; the older 5069040 profile used 6 for 0x86.
BODY_LENGTHS = {0x00: 0, 0x80: 12, 0x81: 22, 0x82: 16, 0x84: 5,
                0x85: 7, 0x86: 5, 0x87: 7}
# 0x02 bodies whose container is known but whose field semantics are partial.
OPAQUE_02 = {0x81, 0x82, 0x84, 0x86}
# Rare 0x05 top-level message: 12-byte body (normal-5v5 samples).
TOP_LEVEL_LENGTHS = {0x05: 13}
# 0x01 body first-byte subtypes.  Known means the container/header is understood;
# some bodies are still semantically partial and are marked opaque.
KNOWN_01 = {0x01, 0x03, 0x14, 0x1c, 0x1e, 0x1f, 0x23, 0x25, 0x29, 0x2b,
            0x2c, 0x2d, 0x73, 0x78, 0x85, 0x87, 0x8c, 0x8e}
OPAQUE_01 = {0x01, 0x1f, 0x29, 0x8e}
ROSTER_HUMAN_POST = 30
ROSTER_FOOTER = bytes.fromhex('000000000004b000000000')

RESIDUAL, OPAQUE, KNOWN = 0, 1, 2
CAT_NAME = {RESIDUAL: 'residual', OPAQUE: 'opaque', KNOWN: 'known'}


class Peel:
    def __init__(self, size: int):
        self.cat = bytearray(size)
        self.size = size

    def mark(self, start: int, end: int, category: int, why: str, labels: list):
        start = max(0, start)
        end = min(self.size, end)
        if start >= end:
            return
        # Known wins over opaque; opaque wins over residual.
        priority = {RESIDUAL: 0, OPAQUE: 1, KNOWN: 2}
        p = priority[category]
        for i in range(start, end):
            if p >= priority[self.cat[i]]:
                self.cat[i] = category
        labels.append({'start': start, 'end': end, 'length': end - start,
                       'category': CAT_NAME[category], 'why': why})

    def segments(self, category: int):
        out, start = [], None
        for i, value in enumerate(self.cat):
            if value == category and start is None:
                start = i
            elif value != category and start is not None:
                out.append((start, i))
                start = None
        if start is not None:
            out.append((start, self.size))
        return out


def header_fields(data: bytes):
    """Return the parsed header end and labelled ranges."""
    ranges = []
    pos = 0
    for index in range(4):
        start = pos
        text, pos = rp.dotnet_string(data, pos, f'header-string-{index}')
        ranges.append((start, pos, f'header-string-{index}:{text}'))
    start = pos
    pos += 4                                      # localHeroId
    ranges.append((start, pos, 'header-localHeroId'))
    for label, size in (('header-startTime', 8), ('header-mapType', 1),
                        ('header-mapId', 4)):
        start = pos
        pos += size
        ranges.append((start, pos, label))
    for label in ('header-userName', 'header-userHead'):
        start = pos
        _, pos = rp.dotnet_string(data, pos, label)
        ranges.append((start, pos, label))
    start = pos
    pos += 1                                      # rankGrade
    pos += 4                                      # rankClass
    ranges.append((start, pos, 'header-rank'))
    return pos, ranges


def parse_payload(payload: bytes):
    """Yield (tag, start, end, category, label) for one frame payload.

    Stops at the first unknown shape; the caller marks the remaining bytes
    as residual.
    """
    if not payload:
        return [], True
    i, out = 1, []
    while i < len(payload):
        tag = payload[i]
        if tag in TOP_LEVEL_LENGTHS:
            end = i + 1 + TOP_LEVEL_LENGTHS[tag]
            if end > len(payload):
                return out, False
            out.append((tag, i, end, OPAQUE, f'top-level-{tag:#x}'))
            i = end
        elif tag == 0x12:
            if i + 3 > len(payload):
                return out, False
            out.append((tag, i, i + 3, KNOWN, 'scalar-0x12'))
            i += 3
        elif tag == 0x13:
            if i + 2 > len(payload):
                return out, False
            out.append((tag, i, i + 2, KNOWN, 'scalar-0x13'))
            i += 2
        elif tag == 0x14:
            if i + 4 > len(payload):
                return out, False
            out.append((tag, i, i + 4, KNOWN, 'scalar-0x14'))
            i += 4
        elif tag == 0x01:
            if i + 5 > len(payload):
                return out, False
            hero = int.from_bytes(payload[i + 1:i + 3], 'big')
            flag = payload[i + 3]
            length = payload[i + 4]
            end = i + 5 + length
            if end > len(payload):
                return out, False
            out.append((tag, i, i + 5, KNOWN, f'0x01-header hero={hero} flag={flag}'))
            if length:
                subtype = payload[i + 5]
                if subtype in KNOWN_01:
                    category = OPAQUE if subtype in OPAQUE_01 else KNOWN
                    label = f'0x01-body subtype={subtype:#x}'
                else:
                    category = RESIDUAL
                    label = f'0x01-body unknown subtype={subtype:#x}'
                out.append((tag, i + 5, end, category, label))
            i = end
        elif tag == 0x02:
            if i + 4 > len(payload):
                return out, False
            hero = int.from_bytes(payload[i + 1:i + 3], 'big')
            subtype = payload[i + 3]
            out.append((tag, i, i + 4, KNOWN, f'0x02-header hero={hero} subtype={subtype:#x}'))
            if subtype not in BODY_LENGTHS:
                out.append((tag, i + 4, len(payload), RESIDUAL,
                            f'0x02-body unknown subtype={subtype:#x}'))
                return out, False
            length = BODY_LENGTHS[subtype]
            end = i + 4 + length
            if end > len(payload):
                return out, False
            if length:
                category = OPAQUE if subtype in OPAQUE_02 else KNOWN
                out.append((tag, i + 4, end, category, f'0x02-body subtype={subtype:#x}'))
            i = end
        else:
            out.append((tag, i, len(payload), RESIDUAL, f'unknown tag={tag:#x}'))
            return out, False
    return out, True


def peel_replay(path: Path, out_dir: Path):
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    peel = Peel(len(data))
    labels = []

    # Top-level record stream: same grammar as tools/replay_record_stream.py.
    from tools.replay_opening_packet import opening_packet
    header = opening_packet(data)
    if header['message_id'] != 1075:
        raise ValueError('Only observed 1075 streams are supported')
    packet_pos = header['length_offset']
    packets = []
    while packet_pos < len(data):
        length = struct.unpack_from('<i', data, packet_pos)[0]
        start, end = packet_pos + 4, packet_pos + 4 + abs(length)
        if length < 0:
            packets.append((packet_pos, start, end, struct.unpack_from('>I', data, start)[0]))
        packet_pos = end

    # .abc header: parsed fields known; unparsed tail remains residual.
    parsed_end, ranges = header_fields(data)
    for start, end, label in ranges:
        peel.mark(start, end, KNOWN, label, labels)

    # 1075: envelope known; body header known; inner roster blocks peeled.
    p1075 = next(p for p in packets if p[3] == 1075)
    peel.mark(p1075[0], p1075[1], KNOWN, 'cspkg-1075-length', labels)
    peel.mark(p1075[1], p1075[1] + 4, KNOWN, 'cspkg-1075-message-id', labels)
    payload_end = p1075[2]
    report = rp.inspect_replay(data)
    blocks = report['blocks']
    candidates = rp._roster_candidates(data, min(len(data), rp.ROSTER_SCAN_LIMIT))
    by_start = {c['start']: c for c in candidates}
    for index, block in enumerate(blocks):
        start = block['start']
        candidate = by_start.get(start)
        name_len = candidate['nameLen'] if candidate else 0
        name_end = start + 16 + name_len
        post_end = name_end + ROSTER_HUMAN_POST
        hero_end = post_end + 0x48 + 2
        block_end = blocks[index + 1]['start'] if index + 1 < len(blocks) else payload_end
        peel.mark(start, name_end, KNOWN, f'player-block-{index+1}-header', labels)
        peel.mark(name_end, post_end, OPAQUE, f'player-block-{index+1}-post', labels)
        peel.mark(post_end, hero_end, KNOWN, f'player-block-{index+1}-hero', labels)
        profile_start = post_end + 0xC8
        if profile_start < block_end:
            peel.mark(post_end + 0x4A, profile_start, OPAQUE,
                      f'player-block-{index+1}-opaque-fields', labels)
            footer_start = block_end - len(ROSTER_FOOTER)
            if footer_start >= profile_start and data[footer_start:block_end] == ROSTER_FOOTER:
                peel.mark(profile_start, footer_start, OPAQUE,
                          f'player-block-{index+1}-profile', labels)
                peel.mark(footer_start, block_end, KNOWN,
                          f'player-block-{index+1}-footer', labels)
            else:
                peel.mark(profile_start, block_end, OPAQUE,
                          f'player-block-{index+1}-profile-no-footer', labels)
        else:
            peel.mark(post_end + 0x4A, block_end, OPAQUE,
                      f'player-block-{index+1}-opaque-fields', labels)
    # Bytes before the first player block inside 1075 remain residual.

    # 1077 and 1251: whole packets known.
    for msg_id, label in ((1077, 'cspkg-1077-beginfight'), (1251, 'cspkg-1251-mvp-score')):
        p = next(p for p in packets if p[3] == msg_id)
        peel.mark(p[0], p[2], KNOWN, label, labels)

    # Frame records: framing known/opaque; payload tags peeled.
    frames = report['frames']
    if not frames or frames.get('status') != 'frame-stream':
        raise ValueError('No frame stream found')

    # Old GameReplayModule.FlushRecord writes a final
    # CSDT_FRAPBOOT_INFO(dwKFrapsNo=endKFraqNo, bNum=0) shaped as
    # i16 length 7 + u32 dwKFrapsNo + u8 bNum.  The 7-byte gap between
    # 1077 and the frame stream matches that shape with dwKFrapsNo=0.
    p1077 = next(p for p in packets if p[3] == 1077)
    gap_start, gap_end = p1077[2], frames['start']
    if (gap_end - gap_start == 7
            and data[gap_start:gap_start + 2] == b'\x07\x00'
            and data[gap_start + 2:gap_end] == b'\x00' * 5):
        peel.mark(gap_start, gap_end, KNOWN,
                  'csdt-frapboot-info-keyframe(dwKFrapsNo=0,bNum=0)', labels)

    pos = frames['start']
    while pos < frames['end']:
        seq, pad, length = data[pos], data[pos + 1], data[pos + 2]
        payload_start = pos + 3
        payload_end = payload_start + length
        trailer_start = payload_end
        record_end = trailer_start + 7
        peel.mark(pos, payload_start, KNOWN, 'frame-record-header', labels)
        peel.mark(trailer_start, record_end, OPAQUE, 'frame-record-trailer', labels)
        if length:
            peel.mark(payload_start, payload_start + 1, KNOWN, 'frame-payload-count', labels)
            messages, ok = parse_payload(data[payload_start:payload_end])
            for _tag, start, end, category, why in messages:
                peel.mark(payload_start + start, payload_start + end, category, why, labels)
            if not ok:
                # parse_payload already marked the unknown tail; ensure it is
                # not accidentally left known from an overlapping mark.
                last_end = max((e for _t, _s, e, _c, _w in messages), default=0)
                peel.mark(payload_start + last_end, payload_end, RESIDUAL,
                          'frame-payload-unparsed-tail', labels)
        pos = record_end

    # Write category segments and binaries.
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        'file': str(path), 'sha256': sha, 'file_bytes': len(data),
        'parsed_header_end': parsed_end,
        'header_unparsed_bytes': max(0, p1075[0] - parsed_end),
        'packets': [{'offset': p[0], 'payload_offset': p[1], 'payload_bytes': p[2] - p[1],
                     'message_id': p[3]} for p in packets],
        'frames': {'records': frames['records'], 'start': frames['start'], 'end': frames['end']},
        'counts': {},
        'segments': {},
    }
    for category, name in ((KNOWN, 'known'), (OPAQUE, 'opaque'), (RESIDUAL, 'residual')):
        segs = peel.segments(category)
        summary['counts'][name] = sum(end - start for start, end in segs)
        summary['segments'][name] = [
            {'start': start, 'end': end, 'length': end - start,
             'hex': data[start:min(end, start + 32)].hex(' ')}
            for start, end in segs
        ]
        blob = b''.join(data[start:end] for start, end in segs)
        (out_dir / f'{name}.bin').write_bytes(blob)
    (out_dir / 'summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    (out_dir / 'labels.json').write_text(
        json.dumps(labels, ensure_ascii=False, indent=2), encoding='utf-8')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('paths', nargs='+', type=Path)
    parser.add_argument('--out', type=Path, default=ROOT / 'data/replays/_analysis/residue')
    args = parser.parse_args()
    for path in args.paths:
        target = args.out / path.stem
        summary = peel_replay(path, target)
        print(json.dumps({'file': summary['file'], 'sha256': summary['sha256'],
                          'file_bytes': summary['file_bytes'],
                          'counts': summary['counts']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
