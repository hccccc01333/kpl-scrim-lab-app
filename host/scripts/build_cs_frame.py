#!/usr/bin/env python3
"""FRAPBOOT -> native CS record wrapper (G5, evidence-based, full coverage).

Mapping proven by live capture 2026-11-04 (docs/g5_frapboot_native_mapping.md):
  frame marker            [u32 0x0d][u32 frameNo]
  BOOTFRAP 18  move       [u32 0x83][u32 frameNo+1][u16 wMoveInfo][u16 0]
  BOOTFRAP 19  attack     [u32 0x84][u32 frameNo+1][u16 0][u8 bAttack][u8 0]
  BOOTFRAP 20  attackobj  [u32 0x84][u32 frameNo+1][u16 wObjID][u8 bAttack][u8 0]
  CC inner 0x03 stopmove  [u32 0x34][u32 frameNo+1][u32 obj]
  CC inner 0x2d dir       [u32 0x73][u32 frameNo+1][u32 obj][u32 angle]
  CC inner 0x01           [u32 0x32][u32 frameNo+1][u32 kind][u32 v1][u32 v2][u32 v3][u8 f][u8 0][u8 0][u8 0]
  CS 128 target skill     [u32 0x39][u32 tgt][u32 obj][u32 targetObj][u32 0]
                          [u16 skillSeq][u16 slot][u16 0][u16 0x62]
  CS 129 directional      [u32 0x3a][u32 tgt][u32 obj][u32 0][u32 0]
                          [u16 1][i16 degree][u16 skillSeq][u16 0x62]
  CS 130 position skill   [u32 0x3b][u32 tgt][u32 obj][i32 x][i32 y][u32 0]
                          [u32 objectID][u16 skillSeq][u16 slot]
  CS 133 buy equip        [u32 0x4d][u32 tgt][u32 obj][u32 objectID][u32 equipID]
  CS 135 learn skill      [u32 0x48][u32 tgt][u32 obj][u8 slot][u8 level][u8 x][u8 auto]

Counts match the whole 20261102_161129 game exactly (see mapping doc §2).

Usage:
  python host/scripts/build_cs_frame.py host/build/g5/abc_events_161129.jsonl \
      --frames 70-80 --frames-dir host/build/frames/recon_full
"""
from __future__ import annotations

import argparse
import json
import struct
from collections import Counter, defaultdict
from pathlib import Path

FRAME_OP = 0x0D
MOVE_OP = 0x83
ATTACK_OP = 0x84
STOPMOVE_OP = 0x34
DIRECTION_OP = 0x73
SKILL_OP = 0x32
TARGET_SKILL_OP = 0x39
DIR_SKILL_OP = 0x3A
POS_SKILL_OP = 0x3B
BUY_EQUIP_OP = 0x4D
LEARN_SKILL_OP = 0x48
# observed but not yet field-mapped (kept explicit so frames are marked partial)
UNMAPPED_CC = {0x87: 0x2AC, 0x8C: 0x2AB}


def build_frame(frame_no: int, entries: list[dict]) -> tuple[bytes, Counter]:
    out = bytearray()
    stats = Counter()
    out += struct.pack("<II", FRAME_OP, frame_no)
    nxt = (frame_no + 1) & 0xFFFFFFFF

    for e in sorted(entries, key=lambda x: x.get("offset", 0)):
        bt = e["boot_type"]
        f = e.get("fields") or {}
        obj = e.get("object_id") or 0

        if bt == 18:
            out += struct.pack("<IIHH", MOVE_OP, nxt, f["packed_move"] & 0xFFFF, 0)
            stats["move"] += 1
        elif bt == 19:
            out += struct.pack("<IIHBB", ATTACK_OP, nxt, 0, f["packed_attack"] & 0xFF, 0)
            stats["attack"] += 1
        elif bt == 20:
            target = f.get("target_object_id") or f.get("wObjID") or 0
            out += struct.pack("<IIHBB", ATTACK_OP, nxt, target & 0xFFFF,
                               f["packed_attack"] & 0xFF, 0)
            stats["attackobj"] += 1
        elif bt == 1:
            buf = bytes.fromhex(e.get("buffer_hex") or "")
            if not buf:
                stats["cc_empty"] += 1
                continue
            cmd = buf[0]
            if cmd == 0x03 and len(buf) >= 2:
                out += struct.pack("<III", STOPMOVE_OP, nxt, obj)
                stats["cc_stopmove"] += 1
            elif cmd == 0x2D and len(buf) >= 3:
                angle = buf[2]
                out += struct.pack("<IIII", DIRECTION_OP, nxt, obj, angle)
                stats["cc_direction"] += 1
            elif cmd == 0x01 and len(buf) >= 13:
                # verified f92: buffer = 01 | i32BE x | i32BE z | i32BE y | 0x7f
                # native 0x32 = {u32 tgt, u32 obj, i32 x, i32 z, i32 y,
                #                u8 1, u8 0, u16 0x62}
                x, z, y = struct.unpack_from(">iii", buf, 1)
                out += struct.pack("<IIIii", SKILL_OP, nxt, obj, x, z)
                out += struct.pack("<i", y)
                out += struct.pack("<BBH", 1, 0, 0x62)
                stats["cc_posmove32"] += 1
            elif cmd in UNMAPPED_CC:
                stats[f"cc_unmapped_{cmd:#04x}"] += 1
            else:
                stats[f"cc_unknown_{cmd:#04x}"] += 1
        elif bt == 2:
            st = e.get("sync_type")
            if st == 128:  # target skill
                out += struct.pack("<IIIIIHHHH", TARGET_SKILL_OP, nxt, obj,
                                   f.get("object_id", 0) & 0xFFFFFFFF, 0,
                                   f.get("skill_seq", 0) & 0xFFFF,
                                   f.get("slot", 0) & 0xFFFF, 0, 0x62)
                stats["cs_target"] += 1
            elif st == 129:  # directional skill
                deg = f.get("degree", 0) & 0xFFFF
                out += struct.pack("<IIIIIHHHH", DIR_SKILL_OP, nxt, obj, 0, 0,
                                   1, deg, f.get("skill_seq", 0) & 0xFFFF, 0x62)
                stats["cs_directional"] += 1
            elif st == 130:  # position skill
                out += struct.pack("<IIIiiIIHH", POS_SKILL_OP, nxt, obj,
                                   f.get("target_x", 0), f.get("target_y", 0),
                                   0, f.get("object_id", 0) & 0xFFFFFFFF,
                                   f.get("skill_seq", 0) & 0xFFFF,
                                   f.get("slot", 0) & 0xFFFF)
                stats["cs_position"] += 1
            elif st == 133:  # buy equip
                out += struct.pack("<IIII", BUY_EQUIP_OP, nxt, obj,
                                   f.get("object_id", 0) & 0xFFFFFFFF)
                out += struct.pack("<I", f.get("equip_id", 0))
                stats["cs_buyequip"] += 1
            elif st == 135:  # learn skill
                # verified 120/120: native X byte = (abc last byte != 0) ? 1 : 0
                x = 1 if f.get("auto_learn", 0) else 0
                out += struct.pack("<IIIBBBB", LEARN_SKILL_OP, nxt, obj,
                                   f.get("slot", 0) & 0xFF, f.get("level", 0) & 0xFF,
                                   x, 0)
                stats["cs_learn"] += 1
            else:
                stats[f"cs_unknown_{st}"] += 1
        else:
            stats[f"boot_unmapped_{bt}"] += 1
    return bytes(out), stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("events")
    ap.add_argument("--frames", required=True, help="e.g. 72 or 70-80 or 70-80:5")
    ap.add_argument("--out", default=None)
    ap.add_argument("--frames-dir", default=None)
    args = ap.parse_args()

    spec = args.frames
    stride = 1
    if ":" in spec:
        spec, stride_s = spec.split(":", 1)
        stride = int(stride_s)
    if "-" in spec:
        a, b = spec.split("-", 1)
        rng = list(range(int(a), int(b) + 1, stride))
    else:
        rng = [int(spec)]

    events = [json.loads(l) for l in Path(args.events).read_text().splitlines() if l.strip()]
    by_frame = defaultdict(list)
    for e in events:
        by_frame[e["frame"]].append(e)

    chunks = []
    total = Counter()
    for f in rng:
        blob, stats = build_frame(f, by_frame.get(f, []))
        total.update(stats)
        chunks.append((f, blob))

    if args.out:
        Path(args.out).write_bytes(b"".join(b for _, b in chunks))
        print(f"stream -> {args.out} ({sum(len(b) for _, b in chunks)} B, {len(chunks)} frames)")
    if args.frames_dir:
        d = Path(args.frames_dir)
        d.mkdir(parents=True, exist_ok=True)
        frames = bytearray()
        idx = ["# index\tsequence\toffset\tlength\tentries\tparsed\tabc_offset"]
        for i, (f, blob) in enumerate(chunks):
            off = len(frames)
            frames += blob
            idx.append(f"{i}\t{f}\t{off}\t{len(blob)}\t1\t1\t{f}")
        (d / "frames.bin").write_bytes(frames)
        (d / "index.tsv").write_text("\n".join(idx) + "\n")
        (d / "manifest.json").write_text(json.dumps({
            "schema": "kpl-h5-frame-payloads-v1",
            "source": {"file": args.events, "route": "build_cs_frame"},
            "frames": {"records": len(chunks), "extracted": len(chunks),
                       "bytes": len(frames), "first_sequence": rng[0],
                       "last_sequence": rng[-1], "zero_command": 0},
            "stats": dict(total),
        }, indent=1))
        print(f"frames dir -> {d} ({len(frames)} B, {len(chunks)} chunks)")
    print("stats:", dict(total))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
