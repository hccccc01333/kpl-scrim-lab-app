"""Compare a live frapInfo dump with the 11/2 per-frame command baseline.

Live JSON is intentionally flexible: either a list or {"frames": [...]} with
keys frame/count/types or time_sec/command_count/command_types. This tool only
reports count comparisons; it never claims type names.
"""
from __future__ import annotations

import argparse
import csv
import json
from bisect import bisect_left
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "data/replays/_analysis/datasets/20261102_frame_commands.csv"


def load_live(path: Path) -> list[dict]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(value, dict):
        value = value.get("frames") or value.get("samples") or value.get("rows") or []
    rows = []
    for item in value:
        if not isinstance(item, dict):
            continue
        frame = item.get("frame", item.get("frame_index"))
        count = item.get("count", item.get("command_count", item.get("commands")))
        if isinstance(count, list):
            count = len(count)
        types = item.get("types", item.get("command_types"))
        if frame is not None and count is not None:
            rows.append({"frame": int(frame), "count": int(count), "types": types})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("live_json", type=Path)
    parser.add_argument("--sample", default="20261102_161129")
    args = parser.parse_args()
    baseline = {}
    with BASELINE.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            if row["sample"] != args.sample:
                continue
            frame = int(row["frame"])
            baseline[frame] = {
                "frame": frame,
                "total": int(row["total"]),
                "total_no_cc": int(row["total"]) - int(row["CC"]),
                "types": [k for k, v in row.items()
                          if k not in ("sample", "frame", "time_sec", "total") and int(v or 0) > 0],
            }
    frames = sorted(baseline)
    live = load_live(args.live_json)
    if not live:
        raise SystemExit("no live frames with frame+count")
    results = []
    for item in live:
        pos = bisect_left(frames, item["frame"])
        candidates = frames[max(0, pos - 2):pos + 3]
        best = min(candidates, key=lambda f: abs(f - item["frame"]))
        row = baseline[best]
        results.append({
            "live_frame": item["frame"], "nearest_frame": best,
            "delta": item["frame"] - best,
            "live_count": item["count"], "baseline_total": row["total"],
            "baseline_no_cc": row["total_no_cc"],
            "match_total": int(item["count"] == row["total"]),
            "match_no_cc": int(item["count"] == row["total_no_cc"]),
            "baseline_types": row["types"],
        })
    print(json.dumps(results, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
