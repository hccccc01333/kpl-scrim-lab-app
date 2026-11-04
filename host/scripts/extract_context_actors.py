#!/usr/bin/env python3
"""Extract the native 10-player actor table from a GameCore process snapshot.

Read-only, local-only.  The snapshot's `ctx+0x3d0` battle object has `+0x40`
pointing at a 10-entry ``entityID -> actor*`` table.  This tool follows it and
emits only numeric fields (no names, no strings, no account data).

The actor fields are static level/desk descriptors, not per-frame DS state; see
docs/h5_active_context_slot0.md.  The tool is intended as an identity anchor for
DS/HeroData validation.

Usage:
  python host/scripts/extract_context_actors.py \
      data/replays/_analysis/client_probe_20261103/process_snapshot_A_active \
      --out host/build/g5/context_actors.json
"""
from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

FIELDS = (0x08, 0x0C, 0x10, 0x14, 0x18, 0x20, 0x2C, 0x40, 0x64)


def u32(buf: bytes, off: int) -> int:
    return struct.unpack_from("<I", buf, off)[0]


def u64(buf: bytes, off: int) -> int:
    return struct.unpack_from("<Q", buf, off)[0]


def load_context(snapshot: Path) -> tuple[dict, int, bytes, int]:
    meta = json.loads((snapshot / "meta.json").read_text(encoding="utf-8"))
    ctx = int(meta["context"], 16)
    region = next((r for r in meta["regions"]
                   if r["start"] <= ctx < r["end"]), None)
    if region is None:
        raise SystemExit("context is not inside a captured region")
    data = (snapshot / region["file"]).read_bytes()
    return meta, ctx, data, region["start"]


def find_hero_entity_map(data: bytes, ctx: int, region: int,
                         entity_ids: set[int]) -> list[dict]:
    """Find the static 0x10-stride {0, heroID, entityID, slot} table."""
    start = ctx - region
    # The table is in the front part of the context arena; scan a bounded
    # window first, then the whole arena as a fallback.
    windows = [(0, min(len(data), 0x300000)), (0, len(data))]
    for lo, hi in windows:
        for off in range(lo, max(lo, hi - 0x110), 4):
            if off + 0x10 * 10 > len(data):
                break
            rows = []
            for k in range(10):
                p = off + k * 0x10
                _zero, hero, eid, slot = struct.unpack_from("<4I", data, p)
                if not (1 <= hero <= 999) or eid not in entity_ids:
                    rows = []
                    break
                rows.append({"hero_id": hero, "entity_id": eid, "slot": slot})
            if len(rows) == 10 and len({r["entity_id"] for r in rows}) == 10:
                return rows
    return []


def i32(buf: bytes, off: int) -> int:
    return struct.unpack_from("<i", buf, off)[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("snapshot", type=Path)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    meta, ctx, data, region = load_context(args.snapshot)
    ctx_off = ctx - region
    battle = u64(data, ctx_off + 0x3D0)
    if not (region <= battle < region + len(data)):
        raise SystemExit(f"ctx+0x3d0 target {battle:#x} is outside the region")
    table = u64(data, battle - region + 0x40)
    if not (region <= table < region + len(data)):
        raise SystemExit(f"actor table {table:#x} is outside the region")

    actors = []
    for k in range(32):
        off = table - region + k * 0x20
        if off + 0x20 > len(data):
            break
        key = u32(data, off)
        actor = u64(data, off + 8)
        if key == 0 and actor == 0:
            break
        if not (region <= actor < region + len(data)):
            continue
        ao = actor - region
        fields = {f"field_{x:02x}": u32(data, ao + x) for x in FIELDS}
        hero = u64(data, ao + 0xD8)
        hero_info = None
        if region <= hero < region + len(data):
            ho = hero - region
            field_50 = u32(data, ho + 0x50)
            value_5c_q8 = u32(data, ho + 0x5C)
            hero_info = {
                "hero_object": f"0x{hero:x}",
                "hero_id": u32(data, ho + 0x28),
                "camp": u32(data, ho + 0x34),
                "entity_id": u32(data, ho + 0x3C),
                "level_slot_or_account": u32(data, ho + 0x0C),
                "hp_current": u32(data, ho + 0x08),
                "hp_max": u32(data, ho + 0x10),
                "stat_14": u32(data, ho + 0x14),
                # Rejected gold candidate: the 10-player sum looked like the
                # Camp team total, but it does not match the UI-verified
                # arena +0x4C gold.  Keep the raw value as an unknown field.
                "field_50": field_50,
                "field_50_div256": field_50 / 256.0,
                "field_5c_q8": value_5c_q8,
                "anchor": [i32(data, ho + 0x278), i32(data, ho + 0x27C),
                           i32(data, ho + 0x280)],
            }
        actors.append({
            "entity_id": key,
            "actor": f"0x{actor:x}",
            "table_slot": k,
            **fields,
            "hero": hero_info,
        })

    entity_ids = {a["entity_id"] for a in actors}
    mapping = find_hero_entity_map(data, ctx, region, entity_ids)
    hero_by_entity = {r["entity_id"]: r["hero_id"] for r in mapping}
    for a in actors:
        a["hero_id"] = hero_by_entity.get(a["entity_id"])

    out = {
        "schema": "kpl-gamecore-context-actors-v1",
        "snapshot": str(args.snapshot),
        "pid": meta.get("pid"),
        "captured_at": meta.get("captured_at"),
        "context": f"0x{ctx:x}",
        "battle_context": f"0x{battle:x}",
        "actor_table": f"0x{table:x}",
        "actors": actors,
        "hero_entity_map": mapping,
        "note": ("static level/desk descriptors; hp_current/hp_max match the "
                 "state_table; field_50 is a rejected gold candidate and must "
                 "remain unlabeled"),
    }
    text = json.dumps(out, ensure_ascii=False, indent=1)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.out} ({len(actors)} actors)")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
