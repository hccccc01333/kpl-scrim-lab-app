#!/usr/bin/env python3
"""Analyze a slot0/slot1 dual capture taken during active replay playback.

1. Reconstruct per-slot, per-epoch streams (init window + deltas).
2. Walk slot0 records using the handler consume table; unknown ops are
   reported with their byte context instead of guessed lengths.
3. Emit an op histogram, per-op payload samples, and a record timeline.
4. Optionally cross-reference .abc events: for a given replay-second window,
   print .abc entry counts per boot type next to slot0 op counts.

Usage:
  python host/scripts/analyze_playback_capture.py host/build/g5/cs_dual_play.jsonl \
      --out-dir host/build/g5/analysis --abc-events host/build/g5/abc_events_161129.jsonl
"""
from __future__ import annotations

import argparse
import json
import struct
from collections import Counter, defaultdict
from pathlib import Path


def load_scan(path: Path) -> dict[int, int]:
    scan = json.loads(path.read_text())
    out = {}
    for e in scan:
        cs = e.get("consume")
        if isinstance(cs, dict) and cs:
            out[e["op"]] = cs.get("entry", cs.get("flag1", next(iter(cs.values()))))
    return out


def build_streams(rows: list[dict]) -> dict[int, dict[int, bytes]]:
    """slot -> epoch -> bytes (init window + ordered deltas)."""
    epochs: dict[int, dict[int, bytearray]] = defaultdict(dict)
    for r in rows:
        slot = r.get("slot")
        if slot is None:
            continue
        ep = r.get("epoch", 0)
        buf = epochs[slot].setdefault(ep, bytearray())
        if "win_hex" in r:
            buf.extend(bytes.fromhex(r["win_hex"]))
        elif "data" in r:
            buf.extend(bytes.fromhex(r["data"]))
    return {slot: {ep: bytes(b) for ep, b in eps.items()} for slot, eps in epochs.items()}


def walk_records(data: bytes, consume: dict[int, int]) -> tuple[list[dict], list[dict]]:
    recs, unknown = [], []
    p, n = 0, len(data)
    while p + 4 <= n:
        hdr = struct.unpack_from("<I", data, p)[0]
        op = hdr & 0xFFFF
        ln = hdr >> 16
        if op in consume:
            sz = consume[op]
            end = p + 4 + sz
            if end > n:
                break
            recs.append({"off": p, "op": op, "hdr": hdr, "len": sz,
                         "payload": data[p + 4:end].hex()})
            p = end
        else:
            # record the unknown header with a short context and advance 4
            unknown.append({"off": p, "op": op, "hdr": hdr, "len_field": ln,
                            "ctx": data[p:p + 24].hex()})
            p += 4
    return recs, unknown


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("jsonl")
    ap.add_argument("--scan", default="host/build/g5/cmd_handlers_scan.json")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--abc-events", default=None)
    ap.add_argument("--window-sec", type=float, default=5.0)
    args = ap.parse_args()

    rows = [json.loads(l) for l in Path(args.jsonl).read_text().splitlines() if l.strip()]
    consume = load_scan(Path(args.scan))
    streams = build_streams(rows)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    report = {"slots": {}}
    for slot, eps in streams.items():
        for ep, data in eps.items():
            info = {"bytes": len(data)}
            if slot == 0:
                recs, unknown = walk_records(data, consume)
                hist = Counter(r["op"] for r in recs)
                info["records"] = len(recs)
                info["unknown_headers"] = len(unknown)
                info["op_histogram"] = {str(op): c for op, c in hist.most_common()}
                samples = {}
                for r in recs:
                    samples.setdefault(r["op"], r["payload"][:64])
                info["payload_samples"] = samples
                (out / f"slot0_epoch{ep}_records.jsonl").write_text(
                    "\n".join(json.dumps(r) for r in recs) + "\n")
                (out / f"slot0_epoch{ep}_unknown.jsonl").write_text(
                    "\n".join(json.dumps(u) for u in unknown) + "\n")
                (out / f"slot0_epoch{ep}.bin").write_bytes(data)
            else:
                (out / f"slot{slot}_epoch{ep}.bin").write_bytes(data)
            report["slots"][f"slot{slot}_epoch{ep}"] = info
            print(f"slot{slot} epoch{ep}: {len(data)} B"
                  + (f", records={info.get('records')}, unknown={info.get('unknown_headers')}"
                     if slot == 0 else ""))

    # .abc cross-reference: per replay-second boot-type counts vs slot0 op counts
    if args.abc_events and 0 in streams:
        events = [json.loads(l) for l in Path(args.abc_events).read_text().splitlines() if l.strip()]
        by_frame = defaultdict(Counter)
        for e in events:
            by_frame[e["frame"]][e["boot_type"]] += 1
        data = next(iter(streams[0].values()))
        recs, _ = walk_records(data, consume)
        # slot0 timeline: records have no timestamps; report global histograms
        # and the first 200 records with payloads for manual correlation.
        cross = {
            "abc_events": len(events),
            "abc_frames": len(by_frame),
            "abc_boot_type_counts": {str(k): v for k, v in
                                     Counter(e["boot_type"] for e in events).most_common()},
            "slot0_records": len(recs),
            "first_records": recs[:200],
        }
        (out / "crossref.json").write_text(json.dumps(cross, indent=1))
        print("crossref written")

    (out / "report.json").write_text(json.dumps(report, indent=1))
    print(f"analysis -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
