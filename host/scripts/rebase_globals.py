#!/usr/bin/env python3
"""Translate heap pointers inside a captured libGameCore globals window.

The globals fixture was captured on the 47-bit MuMu address space, where the
process snapshot was mapped at its original addresses.  The ARM64 phone uses a
39-bit space, so the snapshot is rebased; globals that point into it must be
translated with the same old -> new mapping.

Module pointers are left alone: the host loader rebases `libGameCore` itself.

Usage:
  python host/scripts/rebase_globals.py \
    --globals DIR --old-tsv SNAP/regions.tsv --new-tsv SNAP_REBASED/regions.tsv \
    --out DIR
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

PAGE = 4096
LO, HI = 0x1000000000, 0x800000000000


def parse_tsv(path: Path):
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines()[1:]:
        if not line.strip():
            continue
        parts = line.split("\t")
        rows.append({"start": int(parts[0], 0), "end": int(parts[1], 0),
                     "file": parts[4]})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--globals", type=Path, required=True)
    ap.add_argument("--old-tsv", type=Path, required=True)
    ap.add_argument("--new-tsv", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    old_rows = {row["file"]: row for row in parse_tsv(args.old_tsv)}
    new_rows = {row["file"]: row for row in parse_tsv(args.new_tsv)}
    ranges = []
    for name, old in old_rows.items():
        new = new_rows.get(name)
        if new:
            ranges.append((old["start"], old["end"], new["start"]))
    ranges.sort()
    starts = np.array([r[0] for r in ranges], dtype=np.uint64)
    ends = np.array([r[1] for r in ranges], dtype=np.uint64)
    news = np.array([r[2] for r in ranges], dtype=np.uint64)

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    manifest = (args.globals / "manifest.tsv").read_text(encoding="utf-8")
    lines = manifest.splitlines()
    header = lines[0]
    out_lines = [header]
    total_rewrites = 0
    total_dangling = 0
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split("\t")
        name = parts[5]
        src = args.globals / name
        raw = src.read_bytes()
        n = len(raw) // 8
        buffer = bytearray(raw)
        data = np.frombuffer(buffer, dtype="<u8")
        idx = np.searchsorted(starts, data, side="right").astype(np.int64) - 1
        valid = idx >= 0
        safe = np.clip(idx, 0, len(ranges) - 1)
        valid &= data < ends[safe]
        values = data - starts[safe] + news[safe]
        d4 = np.ndarray(shape=(n - 1,), dtype="<u8", buffer=buffer, offset=4)
        idx4 = np.searchsorted(starts, d4, side="right").astype(np.int64) - 1
        valid4 = idx4 >= 0
        safe4 = np.clip(idx4, 0, len(ranges) - 1)
        valid4 &= d4 < ends[safe4]
        values4 = d4 - starts[safe4] + news[safe4]
        conflict = valid[:n - 1] | valid[1:]
        do4 = valid4 & ~conflict
        data[valid] = values[valid]
        d4[do4] = values4[do4]
        total_rewrites += int(valid.sum()) + int(do4.sum())

        ptr = (data >= LO) & (data < HI) & ~valid
        total_dangling += int(ptr.sum())
        blob = bytes(buffer)
        (out / name).write_bytes(blob)
        parts[6] = hashlib.sha256(blob).hexdigest()
        out_lines.append("\t".join(parts))
    (out / "manifest.tsv").write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    stats = {
        "schema": "kpl-globals-rebase-v1",
        "globals": str(args.globals),
        "ranges": len(ranges),
        "rewrites": total_rewrites,
        "dangling_pointer_slots": total_dangling,
        "note": "module pointers are left for the host loader; only heap ranges are translated",
    }
    (out / "rebase.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
