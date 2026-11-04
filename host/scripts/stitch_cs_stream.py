#!/usr/bin/env python3
"""Stitch slot0 ring samples back into one continuous native CS byte stream.

Reads the JSONL written by sample_cs_stream.py and reconstructs the byte
stream between the minimum and maximum observed write cursor, using the
cumulative u32 cursor and the per-sample 64 KiB ring window.  Any gap
(cursor range not covered by any sample's window) is reported honestly as a
hole list; it does not fabricate bytes.

Also parses the stream with the native CS parser record format
(u32 LE header: op = low16, arg = high16) and prints the opcode histogram.

Usage:
  python host/scripts/stitch_cs_stream.py host/build/g5/cs_samples.jsonl \
      --out host/build/g5/cs_stream.bin --report host/build/g5/cs_stream_report.json
"""
from __future__ import annotations

import argparse
import json
import struct
from collections import Counter
from pathlib import Path


def stitch(samples: list[dict]) -> tuple[bytes, int, int, list[dict]]:
    windows = []
    for s in samples:
        w = s["write"]
        lo = s.get("win_from")
        if lo is None:
            lo = (w - s["size"]) & 0xFFFFFFFF
        data = bytes.fromhex(s["win_hex"])
        windows.append((lo, w, data, s))
    # order by write cursor; u32 wraparound handled via first sample anchor
    anchor = windows[0][1]
    def unwarp(c: int) -> int:
        d = (c - anchor) & 0xFFFFFFFF
        return d
    windows.sort(key=lambda x: unwarp(x[1]))
    max_w = unwarp(windows[-1][1])
    if max_w > 1 << 31:
        raise SystemExit("write cursor moved more than 2^31 (u32 wrap) - unsupported")
    total = max_w
    stream = bytearray(total)
    covered = bytearray(total)
    for lo, w, data, s in windows:
        n = unwarp(w) - unwarp(lo)
        if n != len(data):
            raise SystemExit(f"window length mismatch: cursor span {n} vs {len(data)} bytes")
        start = unwarp(lo)
        for i in range(n):
            if not covered[start + i]:
                stream[start + i] = data[i]
                covered[start + i] = 1
    holes = []
    i = 0
    while i < total:
        if not covered[i]:
            j = i
            while j < total and not covered[j]:
                j += 1
            holes.append({"from": i, "to": j, "bytes": j - i})
            i = j
        else:
            i += 1
    return bytes(stream), unwarp(windows[0][0]), total, holes


def parse_records(stream: bytes) -> list[dict]:
    """Parse with the native parser record format: u32 LE header
    (op = hdr & 0xffff, arg = hdr >> 16), then arg bytes payload."""
    recs = []
    p = 0
    n = len(stream)
    while p + 4 <= n:
        hdr = struct.unpack_from("<I", stream, p)[0]
        op = hdr & 0xFFFF
        arg = hdr >> 16
        end = p + 4 + arg
        if end > n:
            recs.append({"off": p, "op": op, "arg": arg, "truncated": True})
            break
        recs.append({"off": p, "op": op, "arg": arg,
                     "payload": stream[p + 4:end].hex()})
        p = end
    return recs, p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("jsonl")
    ap.add_argument("--out", default=None, help="write stitched stream")
    ap.add_argument("--report", default=None, help="write JSON report")
    ap.add_argument("--head", type=int, default=0, help="print first N records")
    args = ap.parse_args()

    samples = [json.loads(l) for l in Path(args.jsonl).read_text().splitlines() if l.strip()]
    if not samples:
        raise SystemExit("no samples")
    stream, lo, hi, holes = stitch(samples)
    print(f"samples={len(samples)} stream range [{lo:#x},{hi:#x}) = {hi-lo} bytes, holes={len(holes)}")
    for h in holes[:20]:
        print(f"  hole [{h['from']:#x},{h['to']:#x}) {h['bytes']} B")
    recs, endp = parse_records(stream)
    hist = Counter(r["op"] for r in recs if not r.get("truncated"))
    print(f"records parsed: {len(recs)} (consumed {endp}/{len(stream)} bytes)")
    print(f"opcodes: {len(hist)} distinct")
    for op, c in hist.most_common(30):
        print(f"  op {op:#06x} ({op}): {c}")
    if args.out:
        Path(args.out).write_bytes(stream)
        print(f"stream -> {args.out}")
    if args.report:
        Path(args.report).write_text(json.dumps({
            "samples": len(samples),
            "range": [lo, hi],
            "bytes": len(stream),
            "holes": holes,
            "records": len(recs),
            "opcode_histogram": {str(op): c for op, c in hist.most_common()},
        }, indent=1))
    if args.head:
        for r in recs[:args.head]:
            print(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
