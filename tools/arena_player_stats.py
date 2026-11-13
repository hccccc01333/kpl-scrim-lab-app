"""Extract the ten per-player gold/KDA records from a saved GameCore arena.

The GameCore context is a 30 MiB self-relative arena (既有校准-5.157).  While
a replay is loaded, it holds ten battle-stat records with a stable header:

    +0x00 u32 16
    +0x08 u32 10000
    +0x0C f32 ~3.32
    +0x20 u32 1000000000 + index      (index 13..4, descending)
    +0x4C u32 gold
    gold+0x158 u32 kills              (duplicate at gold+0x1D8)
    gold+0xB8  u32 deaths             (duplicates at gold+0x138/+0x1DC)
    gold+0xBC  u32 assists            (variable-length records may shift to +0xC0)

Record starts are roughly 0x2C00 apart, with a +-0xD8 jitter from variable
per-skill sub-records, so scan for the header instead of assuming a stride.

Read-only, offline: this reads an arena snapshot produced by
`dd if=/proc/<pid>/mem ...` under `data/`.  It never touches the device.
"""
from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path


def _u32(raw: bytes, off: int) -> int:
    return struct.unpack_from("<I", raw, off)[0]


def _f32(raw: bytes, off: int) -> float:
    return struct.unpack_from("<f", raw, off)[0]


def find_records(raw: bytes) -> dict[int, dict]:
    records: dict[int, dict] = {}
    for off in range(0, len(raw) - 0x1E4, 4):
        if _u32(raw, off) != 16 or _u32(raw, off + 8) != 10000:
            continue
        if not 3.20 <= _f32(raw, off + 0x0C) <= 3.40:
            continue
        index = _u32(raw, off + 0x20)
        if not 1000000000 <= index <= 1000000013:
            continue
        if index in records:
            continue
        gold_at = off + 0x4C
        records[index] = {
            "index": index,
            "offset": off,
            "size_code": _u32(raw, off + 4),
            "gold": _u32(raw, gold_at),
            "level": _u32(raw, off + 0x220),
            "kills": _u32(raw, gold_at + 0x158),
            "deaths": _u32(raw, gold_at + 0xB8),
            "assists": _u32(raw, gold_at + 0xBC),
            "assists_alt": _u32(raw, gold_at + 0xC0),
        }
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("arena", type=Path, help="30 MiB arena snapshot")
    parser.add_argument("--out", type=Path, help="optional JSON output")
    args = parser.parse_args()

    raw = args.arena.read_bytes()
    records = find_records(raw)
    print(f"arena={args.arena} bytes={len(raw)} records={len(records)}")
    print(f"{'idx':>4} {'offset':>12} {'gold':>6} {'lvl':>3} {'kills':>5} "
          f"{'deaths':>6} {'assists':>7} {'alt':>4}")
    for index in sorted(records, reverse=True):
        r = records[index]
        print(f"{index:>4} {r['offset']:#12x} {r['gold']:>6} {r['level']:>3} "
              f"{r['kills']:>5} {r['deaths']:>6} {r['assists']:>7} {r['assists_alt']:>4}")

    if args.out:
        args.out.write_text(
            json.dumps({"arena": str(args.arena), "records": records},
                       ensure_ascii=False, indent=2),
            encoding="utf-8")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
