#!/usr/bin/env python3
"""Read-only settle-packet probe for .abc files.

It looks for two things:
1. CSPkg records encoded as a negative little-endian int16 length followed
   by CSPkgHead (msgID/version/seq/reserve, big-endian).
2. Raw big-endian occurrences of candidate settle msgIDs (1140 / 1082),
   with context, for files whose outer framing is not the 2021 one.

Usage:
    python tools/settle_packet_probe.py path/to/file.abc
    python tools/settle_packet_probe.py data/replays/samples/**/*.abc
"""
from __future__ import annotations

import argparse
import csv
import glob
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "data/replays/_analysis/datasets/settle_packet_probe.csv"
CANDIDATE_IDS = {1140: "SCID_GAME_OVER_RSP", 1082: "old_SCID_MULTGAME_SETTLEGAIN"}


def scan_cspkg(data: bytes):
    """Yield plausible CSPkg records: negative int16 length + CSPkgHead."""
    for pos in range(0, len(data) - 20):
        length = struct.unpack_from("<h", data, pos)[0]
        if length >= 0:
            continue
        body_len = -length
        if body_len < 16 or pos + 2 + body_len > len(data):
            continue
        msg_id, version, seq, reserve = struct.unpack_from(">IiiI", data, pos + 2)
        if not (1000 <= msg_id <= 20000):
            continue
        if version not in (0, 1, 2, 3, 4, 5):
            continue
        if seq > 10_000_000:
            continue
        if reserve not in (0, 0xFFFFFFFF):
            continue
        yield {
            "kind": "cspkg",
            "offset": pos,
            "length": body_len,
            "msg_id": msg_id,
            "msg_name": CANDIDATE_IDS.get(msg_id, ""),
            "version": version,
            "seq": seq,
            "reserve": reserve,
            "hex": data[pos:pos + min(64, 2 + body_len)].hex(),
        }


def scan_raw_ids(data: bytes):
    for msg_id, name in CANDIDATE_IDS.items():
        needle = struct.pack(">I", msg_id)
        start = 0
        while True:
            pos = data.find(needle, start)
            if pos < 0:
                break
            yield {
                "kind": "raw_id",
                "offset": pos,
                "length": "",
                "msg_id": msg_id,
                "msg_name": name,
                "version": "",
                "seq": "",
                "reserve": "",
                "hex": data[max(0, pos - 16):pos + 48].hex(),
            }
            start = pos + 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    paths = []
    for pattern in args.paths:
        matches = glob.glob(pattern, recursive=True)
        paths.extend(Path(m) for m in matches) if matches else paths.append(Path(pattern))
    rows = []
    for path in paths:
        data = path.read_bytes()
        for row in scan_cspkg(data):
            row["file"] = path.name
            rows.append(row)
        for row in scan_raw_ids(data):
            row["file"] = path.name
            rows.append(row)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "file", "kind", "offset", "length", "msg_id", "msg_name",
            "version", "seq", "reserve", "hex",
        ])
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows to {args.out}")
    by_id = {}
    for row in rows:
        if row["kind"] == "cspkg":
            by_id[row["msg_id"]] = by_id.get(row["msg_id"], 0) + 1
    print("CSPkg candidates by msgID:", sorted(by_id.items(), key=lambda kv: -kv[1])[:20])
    print("settle-like candidates:", [r for r in rows if r["msg_id"] in CANDIDATE_IDS and r["kind"] == "cspkg"][:10])


if __name__ == "__main__":
    main()
