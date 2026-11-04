#!/usr/bin/env python3
"""Extract a complete 10-player state checkpoint from a GameCore arena snapshot.

Combines:
  - arena record gold/KDA/level (tools/arena_player_stats.py layout), and
  - hero object HP (compact actor +0xD8 -> hero +0x08/+0x10).

Read-only, offline.  No names/account strings are read or written.

Usage:
  python host/scripts/extract_state_checkpoint.py \
      data/replays/_analysis/client_probe_20261103/process_snapshot_A_active \
      --time-s 463.2 --frame 7030 --out host/build/g5/state_0743.json
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from arena_player_stats import find_records  # noqa: E402


def u32(b: bytes, o: int) -> int:
    return struct.unpack_from("<I", b, o)[0]


def u64(b: bytes, o: int) -> int:
    return struct.unpack_from("<Q", b, o)[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("snapshot", type=Path)
    ap.add_argument("--time-s", type=float, default=None)
    ap.add_argument("--frame", type=int, default=None)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    meta = json.loads((args.snapshot / "meta.json").read_text(encoding="utf-8"))
    ctx = int(meta["context"], 16)
    region = next((r for r in meta["regions"]
                   if r["start"] <= ctx < r["end"]), None)
    if region is None:
        raise SystemExit("context not in snapshot regions")
    raw = (args.snapshot / region["file"]).read_bytes()
    base = region["start"]
    records = find_records(raw)

    players = []
    for index, rec in sorted(records.items(), reverse=True):
        off = rec["offset"]
        hero = u64(raw, off + 0x28)
        if not (base <= hero < base + len(raw)):
            continue
        ho = hero - base
        hp = u32(raw, ho + 0x08)
        hp_max = u32(raw, ho + 0x10)
        players.append({
            "arena_index": index,
            "entity_id": u32(raw, ho + 0x3C),
            "hero_id": u32(raw, ho + 0x28),
            "camp": u32(raw, ho + 0x34),
            "gold": rec["gold"],
            "kills": rec["kills"],
            "deaths": rec["deaths"],
            "assists": rec["assists"],
            "level": rec["level"],
            "hp_current": hp,
            "hp_max": hp_max,
            "hp_ratio": round(hp / hp_max, 4) if hp_max else None,
            "arena_offset": f"0x{off:x}",
            "hero_object": f"0x{hero:x}",
        })

    out = {
        "schema": "kpl-gamecore-state-checkpoint-v1",
        "snapshot": str(args.snapshot),
        "pid": meta.get("pid"),
        "captured_at": meta.get("captured_at"),
        "context": f"0x{ctx:x}",
        "time_s": args.time_s,
        "frame": args.frame,
        "players": players,
        "sources": {
            "gold_kda_level": "arena record +0x4C/+0x158/+0xB8/+0xBC/+0x220",
            "hp": "compact actor +0xD8 -> hero +0x08/+0x10",
        },
    }
    text = json.dumps(out, ensure_ascii=False, indent=1)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.out} ({len(players)} players)")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
