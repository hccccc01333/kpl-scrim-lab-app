#!/usr/bin/env python3
"""Read the replay clock out of a captured snapshot arena.

Units sit in a pool with stride 0x1888; each object has hero/camp/entity at
+0x28/+0x34/+0x3c and the shared replay clock at +0x1664/+0x1668
(关羽/吕布 use +0x1524/+0x1528).  We only trust candidates that have a
neighbour at ±0x1888, which filters static roster tables.

Usage:
  python host/scripts/read_snapshot_clock.py --snapshot data/.../closure_x
"""
from __future__ import annotations

import argparse
import json
import struct
from collections import Counter
from pathlib import Path

import numpy as np

STRIDE = 0x1888


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", type=Path, required=True)
    args = ap.parse_args()

    meta = json.loads((args.snapshot / "meta.json").read_text(encoding="utf-8"))
    ctx = int(str(meta["context"]), 0)
    rows = []
    for line in (args.snapshot / "regions.tsv").read_text(encoding="utf-8").splitlines()[1:]:
        parts = line.split("\t")
        start, end = int(parts[0], 0), int(parts[1], 0)
        if start <= ctx < end:
            rows.append((start, end, parts[4]))
    if not rows:
        print("context region not found", file=__import__("sys").stderr)
        return 2
    start, end, name = rows[0]
    blob = (args.snapshot / name).read_bytes()
    off = ctx - start
    view = memoryview(blob)[off:]

    words = np.frombuffer(view, dtype="<u4")
    if len(words) < 16:
        return 2
    hero = words[:-5]
    camp = words[3:-2]
    entity = words[5:]
    mask = (hero >= 100) & (hero <= 200) & ((camp == 1) | (camp == 2)) \
        & (entity > 0) & (entity < 100000)
    idx = np.where(mask)[0]
    bases = {int(i) * 4 - 0x28 for i in idx}
    cand = []
    for base in bases:
        if base < 0 or base + 0x1700 > len(view):
            continue
        if base + STRIDE not in bases and base - STRIDE not in bases:
            continue
        hero_id = struct.unpack_from("<I", view, base + 0x28)[0]
        camp_id = struct.unpack_from("<I", view, base + 0x34)[0]
        ent_id = struct.unpack_from("<I", view, base + 0x3c)[0]
        frame = struct.unpack_from("<I", view, base + 0x1664)[0]
        ms = struct.unpack_from("<I", view, base + 0x1668)[0]
        alt_frame = struct.unpack_from("<I", view, base + 0x1524)[0]
        alt_ms = struct.unpack_from("<I", view, base + 0x1528)[0]
        # Observed relation: ms ~= (frame - 33.5) * 66.0; frames 0..33 read 0.
        for f, m in ((frame, ms), (alt_frame, alt_ms)):
            if f < 0 or f > 10509:
                continue
            if (f <= 40 and m == 0) or abs(m - (f - 33.5) * 66.0) <= 600:
                cand.append((base, hero_id, camp_id, ent_id, f, m))
    if not cand:
        print("no clock found")
        return 3
    # Alt-clock fields of the -0x140 layout read 0; prefer live ms > 0.
    positive = [item for item in cand if item[5] > 0]
    pool = positive or cand
    frames = Counter(item[4] for item in pool)
    frame, votes = frames.most_common(1)[0]
    print(json.dumps({
        "context": hex(ctx),
        "frame": frame,
        "votes": votes,
        "candidates": len(cand),
        "units": [{"base": hex(b), "hero": h, "camp": c, "entity": e,
                   "frame": f, "ms": m} for b, h, c, e, f, m in cand[:12]],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
