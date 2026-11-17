"""Build a per-checkpoint state series from saved GameCore arena snapshots.

Read-only and offline: every input is a `dd if=/proc/<pid>/mem` dump taken
during a replay session.  Nothing here touches a device.

Each snapshot holds ten per-player battle-stat records with a stable header
(docs 5.157):

    +0x00 u32 16
    +0x08 u32 10000
    +0x0C f32 ~3.32
    +0x20 u32 1000000000 + index
    +0x4C u32 gold
    +0x220 u32 level          (+0x224 kills, +0x228 deaths)
    gold+0x158 kills, gold+0xB8 deaths, gold+0xBC assists
    +0x50 .. +0x78  eleven u32 cumulative counters

The counters are unnamed: `c3` behaves like total damage dealt (it tracks
role and kill participation, and team totals hold a stable c3/c1 ratio), but
no panel anchor has confirmed it yet.  Treat every `c*` column as
`engine-measured, semantics unconfirmed`.

Usage:

    python tools/state_series.py \
        --snapshot data/replays/_analysis/live_20261104/arena_t0_0134.bin@01:34 \
        --snapshot data/replays/_analysis/live_20261104/arena_t2_0245.bin@02:45 \
        --roster data/replays/_analysis/live_20261104/roster_161129.json \
        --out data/replays/_analysis/live_20261104/state_series_161129.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import struct
from pathlib import Path

from arena_player_stats import find_records

COUNTERS = 11


def clock_seconds(label: str) -> float:
    parts = label.strip().split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    raise ValueError(f"bad clock label: {label!r}")


def u32(raw: bytes, off: int) -> int:
    return struct.unpack_from("<I", raw, off)[0]


def extract(raw: bytes) -> dict[int, dict]:
    records = find_records(raw)
    out: dict[int, dict] = {}
    for index, record in records.items():
        start = record["offset"]
        row = {
            "index": index,
            "record_offset": start,
            "gold": record["gold"],
            "level": record["level"],
            "kills": record["kills"],
            "deaths": record["deaths"],
            "assists": record["assists"],
        }
        for i in range(COUNTERS):
            row[f"c{i}"] = u32(raw, start + 0x50 + i * 4)
        out[index] = row
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", action="append", required=True,
                        metavar="PATH@MM:SS", help="repeatable, in time order")
    parser.add_argument("--roster", type=Path,
                        help="JSON: index -> {player, hero, camp}")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    roster = {}
    if args.roster and args.roster.exists():
        roster = json.loads(args.roster.read_text(encoding="utf-8"))

    points: list[tuple[float, str, dict[int, dict]]] = []
    for item in args.snapshot:
        path_text, _, label = item.rpartition("@")
        if not path_text:
            raise SystemExit(f"--snapshot needs PATH@MM:SS, got {item!r}")
        path = Path(path_text)
        raw = path.read_bytes()
        points.append((clock_seconds(label), label, extract(raw)))
    points.sort(key=lambda p: p[0])

    columns = ["clock", "second", "index", "player", "hero", "camp",
               "gold", "d_gold", "gold_rate", "kills", "deaths", "assists",
               "level"] + [f"c{i}" for i in range(COUNTERS)] + [
               "d_c3", "c3_rate", "source"]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    previous: dict[int, dict] = {}
    previous_second: float | None = None
    rows = 0
    with args.out.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for second, label, table in points:
            for index in sorted(table, reverse=True):
                row = table[index]
                info = roster.get(str(index), {})
                delta_gold = delta_c3 = ""
                gold_rate = c3_rate = ""
                if index in previous and previous_second is not None:
                    span = second - previous_second
                    if span > 0:
                        delta_gold = row["gold"] - previous[index]["gold"]
                        delta_c3 = row["c3"] - previous[index]["c3"]
                        gold_rate = round(delta_gold / span, 2)
                        c3_rate = round(delta_c3 / span, 2)
                writer.writerow({
                    "clock": label,
                    "second": second,
                    "index": index,
                    "player": info.get("player", ""),
                    "hero": info.get("hero", ""),
                    "camp": info.get("camp", ""),
                    "gold": row["gold"],
                    "d_gold": delta_gold,
                    "gold_rate": gold_rate,
                    "kills": row["kills"],
                    "deaths": row["deaths"],
                    "assists": row["assists"],
                    "level": row["level"],
                    **{f"c{i}": row[f"c{i}"] for i in range(COUNTERS)},
                    "d_c3": delta_c3,
                    "c3_rate": c3_rate,
                    "source": "engine-measured",
                })
                rows += 1
            previous = table
            previous_second = second

    print(f"wrote {args.out} rows={rows} snapshots={len(points)}")
    for second, label, table in points:
        total_gold = sum(r["gold"] for r in table.values())
        total_c3 = sum(r["c3"] for r in table.values())
        total_c1 = sum(r["c1"] for r in table.values())
        ratio = f"{total_c3 / total_c1:.3f}" if total_c1 else "n/a"
        print(f"  {label:>7} gold={total_gold:>6,} c1={total_c1:>8,} "
              f"c3={total_c3:>8,} c3/c1={ratio}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
