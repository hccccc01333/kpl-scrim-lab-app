"""Build a per-frame command baseline from the 11/2 .abc streams.

This is the expected N+1 side of the live frapInfo probe: for every recorded
frame, count the decoded frame commands by category and time (15 fps).  It does
not claim FRAPBOOT_INFO type numbers; the live object's type sequence can be
compared to these counts once captured.
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.replay_frame_commands import battle_time, events  # noqa: E402

FILES = [
    ROOT / "data/replays/samples/20261102_161129/20261102_161129_870343216_95868_1793606215_2B9FAA08A7AD40D09ABDA364F9C1E804.abc",
    ROOT / "data/replays/samples/20261102_163751/20261102_163751_-1996438720_96420_1793607470_2B9FAA08A7AD40D09ABDA364F9C1E804.abc",
]
OUT = ROOT / "data/replays/_analysis/datasets/20261102_frame_commands.csv"
SUMMARY = ROOT / "data/replays/_analysis/datasets/20261102_frame_commands_summary.json"
CATS = ["PLAYER_MOVE", "PLAYER_ATTACK", "PLAYER_ATTACKWITHOBJ", "BUYEQUIP",
        "LEARNSKILL", "USEDIRECTIONALSKILL", "USEPOSITIONSKILL",
        "USEOBJECTIVESKILL", "CC", "BASEATTACK", "SELLEQUIP", "AISTATECHG"]


def main() -> None:
    rows = []
    summaries = {}
    for path in FILES:
        sample = path.name[:15]
        ev = list(events(path.read_bytes()))
        per = {}
        for e in ev:
            frame = int(e["frame"])
            row = per.setdefault(frame, Counter())
            row[e["name"]] += 1
        for frame in sorted(per):
            counts = per[frame]
            rows.append({
                "sample": sample, "frame": frame,
                "time_sec": round(battle_time(frame), 3),
                "total": sum(counts.values()),
                **{name: counts.get(name, 0) for name in CATS},
            })
        totals = Counter(e["name"] for e in ev)
        summaries[sample] = {
            "file": path.name,
            "frames_with_commands": len(per),
            "command_entries": len(ev),
            "max_commands_per_frame": max((sum(c.values()) for c in per.values()), default=0),
            "command_totals": dict(sorted(totals.items())),
        }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    SUMMARY.write_text(json.dumps(summaries, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {OUT} ({len(rows)} frame rows)")
    print(json.dumps(summaries, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
