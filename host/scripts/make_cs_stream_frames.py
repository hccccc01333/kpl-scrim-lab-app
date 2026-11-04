#!/usr/bin/env python3
"""Synthesize an h5_probe frames dir from a captured slot0 delta JSONL.

Chunks the reconstructed stream at record boundaries (using the handler
consume table where known; unknown stretches stay attached to the next known
header) and writes frames.bin / index.tsv / manifest.json compatible with
host/src/h5_probe.c.

Usage:
  python host/scripts/make_cs_stream_frames.py host/build/g5/cs_deltas_run1.jsonl \
      --out host/build/frames/cs_live_run1 --scan host/build/g5/cmd_handlers_scan.json
"""
from __future__ import annotations

import argparse
import json
import struct
from collections import Counter
from pathlib import Path


def load_consume(scan_path: Path) -> dict[int, int]:
    scan = json.loads(scan_path.read_text())
    out = {}
    for e in scan:
        cs = e.get("consume")
        if isinstance(cs, dict) and cs:
            # prefer the flag==1/fallthrough ("entry"/"flag1") size, else any
            sz = cs.get("entry", cs.get("flag1", next(iter(cs.values()))))
            out[e["op"]] = sz
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("jsonl")
    ap.add_argument("--out", required=True)
    ap.add_argument("--scan", default="host/build/g5/cmd_handlers_scan.json")
    ap.add_argument("--records-per-frame", type=int, default=40)
    args = ap.parse_args()

    samples = [json.loads(l) for l in Path(args.jsonl).read_text().splitlines() if l.strip()]
    data = b"".join(bytes.fromhex(s["data"]) for s in samples if "data" in s)
    print(f"stream: {len(data)} bytes from {len(samples)} deltas")

    consume = load_consume(Path(args.scan))
    print(f"consume table: {len(consume)} ops")

    # walk records; unknown-op stretches are attached to the next known header
    records = []  # (op, hdr, payload)
    p, n = 0, len(data)
    unknown_run = b""
    while p + 4 <= n:
        hdr = struct.unpack_from("<I", data, p)[0]
        op = hdr & 0xFFFF
        if op in consume:
            sz = consume[op]
            end = p + 4 + sz
            if end > n:
                break
            rec = unknown_run + data[p:end]
            records.append((op, rec))
            unknown_run = b""
            p = end
        else:
            # unknown op: tentatively advance 4 and accumulate; if the next
            # known header appears, flush the accumulated bytes as part of the
            # next record
            unknown_run += data[p:p + 4]
            p += 4
    print(f"walked {len(records)} known-op records, trailing {len(unknown_run)} B unknown")

    # chunk into frames
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    chunks = []
    cur = bytearray()
    ops = []
    for op, rec in records:
        cur += rec
        ops.append(op)
        if len(ops) >= args.records_per_frame and ops[-1] in consume:
            chunks.append((bytes(cur), Counter(ops)))
            cur = bytearray()
            ops = []
    if cur:
        chunks.append((bytes(cur), Counter(ops)))
    print(f"chunks: {len(chunks)}")

    frames = bytearray()
    idx_lines = ["# index\tsequence\toffset\tlength\tentries\tparsed\tabc_offset"]
    for i, (blob_c, ops_c) in enumerate(chunks):
        off = len(frames)
        frames += blob_c
        idx_lines.append(f"{i}\t{i+1}\t{off}\t{len(blob_c)}\t{sum(ops_c.values())}\t1\t0")
    (out / "frames.bin").write_bytes(frames)
    (out / "index.tsv").write_text("\n".join(idx_lines) + "\n")
    manifest = {
        "schema": "kpl-h5-frame-payloads-v1",
        "source": {"file": "<live slot0 capture>", "route": "sample_cs_stream"},
        "selection": {"start": 0, "limit": 0, "stride": 1, "require_parsed": False},
        "frames": {"records": len(chunks), "extracted": len(chunks),
                   "bytes": len(frames), "first_sequence": 1,
                   "last_sequence": len(chunks), "zero_command": 0},
        "op_histogram": {str(op): c for op, c in Counter(
            op for _, cc in chunks for op, _ in cc.items()).most_common()},
        "notes": "chunks are live-captured slot0 records split at known-op boundaries",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"wrote {out}/frames.bin ({len(frames)} B), index.tsv, manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
