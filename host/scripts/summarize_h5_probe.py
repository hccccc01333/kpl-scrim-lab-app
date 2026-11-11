#!/usr/bin/env python3
"""Summarize `h5_probe` JSONL output (one JSON object per line)."""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path


def summarize(rows: list[dict]) -> dict:
    frames = [r for r in rows if r.get("event") == "frame"]
    skips = [r for r in rows if r.get("event") == "skip"]
    crashed = [r for r in frames if r.get("status") == "crash"]
    dispatched = [r for r in frames if r.get("in_range") == 1]
    returned = [r for r in dispatched if r.get("status") == "ok"
                and (r.get("consumer") or {}).get("returned") == 1]
    drain_ok = [r for r in frames
                if (r.get("consumer") or {}).get("drained") == r.get("bytes")]
    byte_ok = [r for r in frames
               if (r.get("consumer") or {}).get("bytes_match") == 1]
    bytes_field = any("bytes_match" in (r.get("consumer") or {}) for r in frames)
    short = [r for r in frames if r.get("preflight") == 0]
    out_of_range = [r for r in frames if r.get("preflight") == 1]

    crash_pc = collections.Counter(r.get("crash_pc", "0x0") for r in crashed)
    crash_site = collections.Counter(
        (r.get("opcode"), r.get("flag"), r.get("crash_pc")) for r in crashed)
    returned_sites = collections.Counter(
        (r.get("opcode"), r.get("flag")) for r in returned)
    return {
        "schema": "kpl-h5-probe-summary-v1",
        "lines": len(rows),
        "frames": len(frames),
        "skips": len(skips),
        "bytes_pushed": sum(r.get("bytes", 0) for r in frames),
        "drain_exact": len(drain_ok),
        "drain_mismatch": len(frames) - len(drain_ok),
        "short_header": len(short),
        "bytes_match": len(byte_ok) if bytes_field else None,
        "bytes_mismatch": (len(frames) - len(byte_ok)) if bytes_field else None,
        "out_of_range": len(out_of_range),
        "dispatched": len(dispatched),
        "handler_returned": len(returned),
        "crash": len(crashed),
        "status": dict(collections.Counter(r.get("status") for r in frames)),
        "crash_pc_top": crash_pc.most_common(16),
        "crash_sites": crash_site.most_common(24),
        "returned_sites": returned_sites.most_common(16),
        "returned_frames": [
            {"frame": r.get("frame"), "seq": r.get("seq"), "bytes": r.get("bytes"),
             "opcode": r.get("opcode"), "arg": r.get("arg"), "flag": r.get("flag"),
             "handler": r.get("handler")}
            for r in returned[:32]
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    rows = []
    for path in args.paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    result = summarize(rows)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.json:
        args.json.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
