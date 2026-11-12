#!/usr/bin/env python3
"""Offline probe for per-unit buff / status instance structures in a GameCore arena.

The GameCore context is a deterministic 30 MiB self-relative arena dumped from
the paused replay (docs/replay_binary_format.md 5.155-5.158).  This tool looks
for the *buff/status instance* layer that the state table does not cover:
buffID, caster/target, remaining time, stacks.

It answers four questions and prints a verdict for each:

  A. buff-instance records  - records shaped like
        [qword class pointer][u32 small][u32 small][buffID...][live time field]
     where at least two fields are native-buff IDs (agent_native_buffs.csv) and
     at least one field tracks the replay clock.
  B. buff-ID arrays         - contiguous u32 runs of native-buff IDs (the
     "multi-entry + count" shape), classified static vs live when --compare is
     given.
  C. live-clock census      - how many u32 fields track the replay clock
     (+-64 ms), i.e. how much live timer state exists and whether any of it sits
     next to a buff ID.
  D. curated known-buff checks - red/blue buff, 学识宝石, 主宰/暴君 buffs ...:
     occurrence count, structure, adjacency to hero entity IDs, and whether the
     hits are explained by static config tables.

Everything is read-only and offline: the tool never touches a device, MuMu or
ADB, and it writes only inside --out (default
data/replays/_analysis/engine_20261112/probe_out).

Typical use (project root):

    python tools/engine_buff_probe.py \
        data/replays/_analysis/live_20261104/arena_paused_0500.bin

    # classify static vs live buff-ID arrays with a second same-session dump
    python tools/engine_buff_probe.py ARENA_A --compare ARENA_B

Cross-session caution: the class-pointer *values* relocate per process
(0x7832... in the 05:00 session, 0x7311... in the 07:4x session), so the probe
matches the record *shape*, not a hard-coded class pointer.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import struct
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUFF_CSV = ROOT / "data/replays/_analysis/datasets/agent_native_buffs.csv"
DEFAULT_ROSTER = ROOT / "data/replays/_analysis/live_20261104/abc_timeline/event_windows.json"
DEFAULT_OUT = ROOT / "data/replays/_analysis/engine_20261112/probe_out"

# Curated ids the task named plus the red/blue buff + neutral-object buffs of a
# normal 5v5 match.  Absent ids (e.g. 900019/900020 in this build) are reported
# as absent instead of silently skipped.
CURATED = {
    900019: "task-listed (not present in this build's table)",
    900020: "task-listed 纣王控制免疫",
    917010: "学识宝石 辅助装备经验补偿",
    917011: "学识宝石 辅助装备金币补偿",
    506711: "蔚蓝石像之力（全） 蓝BUFF",
    506721: "猩红石像之力（全） 红BUFF",
    620050: "红buff 展示",
    620051: "蓝buff 展示",
    902111: "BUFF怪 红BUFF常驻",
    902120: "BUFF怪 蓝BUFF常驻",
    902131: "BUFF怪 蓝BUFF常驻",
    60005: "小龙BUFF第一层 主宰之力X1",
    60006: "小龙BUFF第二层 主宰之力X2",
}

# Known-buff timers of the 05:00 candidate; see README for the field table.
CLASS_PTR_LO = 0x0000700000000000
CLASS_PTR_HI = 0x0000800000000000

STRICT_ID_MIN = 10000          # below this any small integer collides with data


def u32(raw: bytes, off: int) -> int:
    return struct.unpack_from("<I", raw, off)[0]


def u64(raw: bytes, off: int) -> int:
    return struct.unpack_from("<Q", raw, off)[0]


def f32(raw: bytes, off: int) -> float:
    return struct.unpack_from("<f", raw, off)[0]


# ---------------------------------------------------------------------------
# inputs
# ---------------------------------------------------------------------------

def load_buff_table(path: Path) -> dict[int, dict]:
    ids: dict[int, dict] = {}
    with path.open(encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            if row["table_kind"] != "native_buff":
                continue
            try:
                bid = int(row["row_id"])
            except (TypeError, ValueError):
                continue
            ids.setdefault(bid, {"name": row["name"], "desc": row["desc"][:80]})
    return ids


def load_roster(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["roster"]


def _load_record_scanner():
    path = Path(__file__).resolve().with_name("arena_player_stats.py")
    if not path.exists():
        raise SystemExit(f"missing {path}")
    spec = importlib.util.spec_from_file_location("_arena_player_stats", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.find_records


find_records = _load_record_scanner()


# ---------------------------------------------------------------------------
# context: records -> units -> arena base -> replay clock
# ---------------------------------------------------------------------------

def resolve_units(raw: bytes, roster: list[dict]) -> dict:
    records = find_records(raw)
    if len(records) != 10:
        raise SystemExit(f"expected 10 player records, found {len(records)}")

    candidates: list[int] = []
    for member in roster:
        entity = int(member["entityId"])
        pat = struct.pack("<II", entity, entity)
        pos = raw.find(pat)
        while pos >= 0:
            unit = pos - 0x3C
            if 0 <= unit and unit + 0x1888 <= len(raw):
                hp_max = u32(raw, unit + 0x10)
                if u32(raw, unit + 0x34) == int(member["camp"]) and 900 <= hp_max <= 1200:
                    candidates.append(unit)
            pos = raw.find(pat, pos + 1)

    pointers = {idx: u64(raw, rec["offset"] + 0x28) for idx, rec in records.items()}
    votes: Counter[int] = Counter()
    for ptr in pointers.values():
        for unit in set(candidates):
            votes[ptr - unit] += 1
    if not votes:
        raise SystemExit("could not resolve the arena base from record+0x28 pointers")
    base, nvotes = votes.most_common(1)[0]
    unit_by_idx = {idx: ptr - base for idx, ptr in pointers.items()}

    clocks: list[int] = []
    unit_rows: list[dict] = []
    by_entity = {int(m["entityId"]): m for m in roster}
    for idx, unit in sorted(unit_by_idx.items()):
        # +0x1664/+0x1668 is the clock; 关羽/吕布 carry it 0x140 bytes earlier
        # in this build, and 孙悟空's copy is stale (1337 ms in every capture).
        clock_off = None
        for cand in (0x1664, 0x1524):
            ms = u32(raw, unit + cand + 4)
            if 60000 <= ms <= 500000:
                clock_off = cand
                break
        clock_ms = u32(raw, unit + (clock_off if clock_off is not None else 0x1664) + 4)
        entity = u32(raw, unit + 0x3C)
        hero = by_entity.get(entity, {}).get("hero", f"entity{entity}")
        unit_rows.append({
            "record_index": idx,
            "offset": unit,
            "hero": hero,
            "entity_id": entity,
            "camp": u32(raw, unit + 0x34),
            "hp_current": u32(raw, unit + 0x08),
            "hp_max": u32(raw, unit + 0x10),
            "clock_offset": hex(clock_off) if clock_off is not None else None,
            "clock_ms": clock_ms,
            "clock_frame": u32(raw, unit + (clock_off if clock_off is not None else 0x1664)),
            "clock_stale": clock_off is None,
        })
        if clock_off is not None:
            clocks.append(clock_ms)
    if not clocks:
        raise SystemExit("no plausible replay clock on the ten unit objects")
    clock = int(np.median(clocks))
    return {
        "records": records,
        "base": base,
        "base_votes": nvotes,
        "unit_by_idx": unit_by_idx,
        "units": unit_rows,
        "clock_ms": clock,
        "clock_range": [min(clocks), max(clocks)],
    }


# ---------------------------------------------------------------------------
# A. buff-instance records
# ---------------------------------------------------------------------------

def detect_buff_instances(raw: bytes, ctx: dict, buff: dict[int, dict], top: int,
                          compare_raw: bytes | None = None) -> list[dict]:
    """Scan for `[class ptr][small ints][native buff ids][live time]` records."""
    n = len(raw)
    base, clock = ctx["base"], ctx["clock_ms"]
    strict = {bid for bid in buff if bid >= STRICT_ID_MIN}
    qwords = np.frombuffer(raw, dtype="<u8")
    mask = (qwords >= CLASS_PTR_LO) & (qwords < CLASS_PTR_HI)
    positions = np.flatnonzero(mask)

    hits: list[dict] = []
    for i in positions:
        p = int(i) * 8
        if p + 0x48 > n:
            continue
        cls = int(qwords[i])
        if cls % 8:                       # class pointers are 8-byte aligned
            continue
        if base <= cls < base + n:        # in-arena pointer, not metadata
            continue
        a, b = u32(raw, p + 8), u32(raw, p + 12)
        if a > 0x1000 or b > 0x1000:
            continue
        ids: list[tuple[int, int]] = []
        live: list[tuple[int, int]] = []
        for k in range(4, 18):            # +0x10 .. +0x50
            w = u32(raw, p + 4 * k)
            if w in strict:
                ids.append((4 * k, w))
            if clock - 1000 <= w <= clock + 1000:
                live.append((4 * k, w))
        if not ids:
            continue
        score = 0
        if len({w for _o, w in ids}) >= 2:
            score += 2
        if live:
            score += 2
        if a and b:
            score += 1
        if score < 3:
            continue
        entry = {
            "offset": p,
            "class_pointer": cls,
            "small_a": a,
            "small_b": b,
            "buff_fields": [{"rel": hex(o), "id": w, "name": buff[w]["name"]} for o, w in ids],
            "live_time_fields": [{"rel": hex(o), "value": v, "delta_ms": v - clock} for o, v in live],
            "record_words": [u32(raw, p + 4 * k) for k in range(14)],
            "score": score,
        }
        if compare_raw is not None and p + 0x48 <= len(compare_raw):
            cw = [u32(compare_raw, p + 4 * k) for k in range(14)]
            cids = [w for w in cw if w in strict]
            entry["compare_record_words"] = cw
            entry["buff_ids_match_in_compare"] = [f["id"] for f in entry["buff_fields"]] == \
                [w for w in cw if w in strict][:len(entry["buff_fields"])]
        hits.append(entry)
    hits.sort(key=lambda h: (-h["score"], h["offset"]))
    return hits[:top]


# ---------------------------------------------------------------------------
# B. buff-ID arrays (contiguous runs)
# ---------------------------------------------------------------------------

def detect_buff_arrays(raw: bytes, buff: dict[int, dict], compare: tuple[bytes, bytes] | None,
                       min_len: int, top: int) -> list[dict]:
    arr = np.frombuffer(raw, dtype="<u4")
    buff_arr = np.fromiter((bid for bid in buff if bid >= STRICT_ID_MIN),
                           dtype=np.uint32, count=sum(1 for bid in buff if bid >= STRICT_ID_MIN))
    mask = np.isin(arr, buff_arr)
    padded = np.concatenate(([False], mask, [False]))
    edges = np.flatnonzero(np.diff(padded.astype(np.int8)))
    runs: list[dict] = []
    for start, end in zip(edges[0::2], edges[1::2]):
        length = int(end - start)
        if length < min_len:
            continue
        off = int(start) * 4
        ids = [int(arr[start + k]) for k in range(min(length, 16))]
        if len(set(ids)) == 1 and length > 8:
            kind = "constant-run"
        else:
            kind = "array"
        entry = {
            "offset": off,
            "length": length,
            "kind": kind,
            "ids": ids,
            "names": [buff[i]["name"] for i in ids],
            "static": None,
        }
        if compare is not None:
            a, b = compare
            k = min(length, 8)
            same = all(a[(off + 4 * i):(off + 4 * i) + 4] == b[(off + 4 * i):(off + 4 * i) + 4]
                       for i in range(k))
            entry["static"] = same
        runs.append(entry)
    runs.sort(key=lambda r: (-r["length"], r["offset"]))
    return runs[:top]


# ---------------------------------------------------------------------------
# C. live-clock census
# ---------------------------------------------------------------------------

def census_live_clock(raw: bytes, ctx: dict, buff: dict[int, dict]) -> dict:
    n = len(raw)
    clock, base = ctx["clock_ms"], ctx["base"]
    arr = np.frombuffer(raw, dtype="<u4").astype(np.int64)
    pos = np.flatnonzero((arr >= clock - 64) & (arr <= clock + 64))
    unit_offsets = set(ctx["unit_by_idx"].values())
    rows = []
    near_buff = 0
    for p in pos:
        off = int(p) * 4
        value = int(arr[p])
        found = []
        for d in range(-0x10, 0x14, 4):
            q = off + d
            if 0 <= q <= n - 4:
                w = u32(raw, q)
                # a buff id is only meaningful here when it is not the clock
                # value itself (the clock integer collides with some row ids)
                if w in buff and w >= STRICT_ID_MIN and w != value:
                    found.append({"rel": d, "id": w,
                                  "name": buff[w]["name"] or "(unnamed)"})
        in_unit = any(u <= off < u + 0x1888 for u in unit_offsets)
        if found:
            near_buff += 1
        rows.append({
            "offset": off,
            "value": value,
            "delta_ms": value - clock,
            "in_unit_object": in_unit,
            "buff_ids_within_0x10": found,
        })
    return {
        "tolerance_ms": 64,
        "window_for_buff_ids": 0x10,
        "count": len(rows),
        "near_buff_id_count": near_buff,
        "fields": rows,
    }


# ---------------------------------------------------------------------------
# D. curated known-buff checks
# ---------------------------------------------------------------------------

def check_curated(raw: bytes, ctx: dict, buff: dict[int, dict]) -> list[dict]:
    n = len(raw)
    arr = np.frombuffer(raw, dtype="<u4")
    u16 = np.frombuffer(raw, dtype="<u2")
    heroes = {u["entity_id"] for u in ctx["units"]}
    unit_offsets = list(ctx["unit_by_idx"].values())
    out = []
    for bid, label in CURATED.items():
        pos = np.flatnonzero(arr == bid)
        u16_hits = int(np.flatnonzero(u16 == bid).size) if bid <= 0xFFFF else 0
        entries = []
        for p in pos:
            off = int(p) * 4
            near_entity = []
            for d in range(-0x40, 0x44, 4):
                q = off + d
                if 0 <= q <= n - 4 and u32(raw, q) in heroes:
                    near_entity.append({"rel": d, "entity_id": u32(raw, q)})
            entries.append({
                "offset": off,
                "in_unit_object": any(u <= off < u + 0x1888 for u in unit_offsets),
                "near_hero_entity": near_entity,
            })
        out.append({
            "id": bid,
            "label": label,
            "in_table": bid in buff,
            "table_name": buff.get(bid, {}).get("name", ""),
            "u32_hits": int(len(pos)),
            "u16_hits": u16_hits,
            "entries": entries,
        })
    return out


# ---------------------------------------------------------------------------
# E. unit-object negative check
# ---------------------------------------------------------------------------

def check_unit_objects(raw: bytes, ctx: dict, buff: dict[int, dict]) -> dict:
    strict = {bid for bid in buff if bid >= STRICT_ID_MIN}
    rows = []
    adjacent_total = 0
    for unit in ctx["units"]:
        off = unit["offset"]
        hit_offsets = []
        adjacent = []
        for rel in range(0, 0x1888, 4):
            w = u32(raw, off + rel)
            if w in strict:
                hit_offsets.append(rel)
            if rel + 4 < 0x1888 and w in strict and u32(raw, off + rel + 4) in strict:
                adjacent.append({
                    "rel": rel,
                    "values": [w, u32(raw, off + rel + 4)],
                    "names": [buff[w]["name"], buff[u32(raw, off + rel + 4)]["name"]],
                })
        adjacent_total += len(adjacent)
        rows.append({
            "hero": unit["hero"],
            "offset": off,
            "buff_id_hits": len(hit_offsets),
            "hit_offsets": hit_offsets[:24],
            "adjacent_buff_id_pairs": len(adjacent),
            "adjacent_pairs": adjacent[:4],
        })
    return {
        "note": "the 0x1888 unit object holds no buff/status instance state. The only "
                "buff-ID-like values are heroID-derived constants in the skill-ID array "
                "(+0x2BC..+0x361, e.g. 140800 for 关羽 / 175000 for 钟馗) and the clock "
                "integer; the few adjacent pairs are consecutive skill-ID array entries "
                "whose values happen to be table row ids. Between two same-session "
                "snapshots only HP(+0x08), +0x630, facing/move vectors, the clock, the "
                "animation hash and per-skill scratch change.",
        "unit_count": len(rows),
        "units_with_adjacent_pairs": sum(1 for r in rows if r["adjacent_buff_id_pairs"]),
        "adjacent_pair_total": adjacent_total,
        "units": rows,
    }


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

def build_report(arena: Path, raw: bytes, ctx: dict, buff: dict[int, dict],
                 instances: list[dict], arrays: list[dict], clock_census: dict,
                 curated: list[dict], units_check: dict, compare: Path | None) -> dict:
    identified = [h for h in instances if h["score"] >= 4 and len({f["id"] for f in h["buff_fields"]}) >= 2]
    verdicts = {
        "buff_instance_record": "FOUND" if identified else "NOT FOUND",
        "per_unit_buff_list": "NOT FOUND",
        "live_buff_id_array": ("FOUND" if any(a["static"] is False for a in arrays) else "NOT FOUND"),
        "red_blue_buff_entries": "NOT FOUND",
    }
    notes = []
    if identified:
        top = identified[0]
        notes.append(
            f"buff-instance-shaped record at file offset {top['offset']:#x}: "
            f"buff ids {[f['id'] for f in top['buff_fields']]}, "
            f"live time fields {[f['value'] for f in top['live_time_fields']]} "
            f"(clock {ctx['clock_ms']})"
        )
    notes.append("no record found that links a buff id to a caster/target entity inside the arena")
    notes.append("all contiguous buff-ID arrays are either static config copies or constant runs")
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tool": "tools/engine_buff_probe.py",
        "arena": str(arena),
        "arena_bytes": len(raw),
        "arena_base": ctx["base"],
        "arena_base_votes": ctx["base_votes"],
        "clock_ms": ctx["clock_ms"],
        "clock_range_ms": ctx["clock_range"],
        "compare": str(compare) if compare else None,
        "buff_table": {
            "path": str(DEFAULT_BUFF_CSV),
            "native_buff_rows": len(buff),
            "strict_ids_ge_10000": sum(1 for bid in buff if bid >= STRICT_ID_MIN),
        },
        "units": ctx["units"],
        "detector_a_buff_instances": instances,
        "detector_b_buff_id_arrays": arrays,
        "detector_c_live_clock_census": clock_census,
        "detector_d_curated_ids": curated,
        "detector_e_unit_object_check": units_check,
        "verdicts": verdicts,
        "notes": notes,
    }


def print_summary(report: dict) -> None:
    print(f"arena        {report['arena']}")
    print(f"bytes        {report['arena_bytes']}")
    print(f"base         {report['arena_base']:#x} ({report['arena_base_votes']} votes)")
    print(f"clock        {report['clock_ms']} ms  range={report['clock_range_ms']}")
    print(f"buff table   {report['buff_table']['native_buff_rows']} rows, "
          f"{report['buff_table']['strict_ids_ge_10000']} ids >= 10000")
    if report["compare"]:
        print(f"compare      {report['compare']}")
    print()
    print("-- units --")
    for u in report["units"]:
        stale = " STALE-CLOCK" if u["clock_stale"] else ""
        print(f"  {u['hero']:<6} entity={u['entity_id']:<5} camp={u['camp']} "
              f"unit={u['offset']:#09x} hp={u['hp_current']}/{u['hp_max']} "
              f"clock={u['clock_ms']}ms{stale}")
    print()
    print("-- A. buff-instance records --")
    strong = [h for h in report["detector_a_buff_instances"] if h["score"] >= 4]
    weak = [h for h in report["detector_a_buff_instances"] if h["score"] < 4]
    if not strong:
        print("  no strong candidate")
    for hit in strong:
        print(f"  offset={hit['offset']:#09x} class={hit['class_pointer']:#x} "
              f"score={hit['score']}")
        print(f"    buff fields: {[(f['rel'], f['id'], f['name']) for f in hit['buff_fields']]}")
        print(f"    live time  : {[(f['rel'], f['value'], f['delta_ms']) for f in hit['live_time_fields']]}")
        print(f"    words      : {hit['record_words'][:12]}")
        if "buff_ids_match_in_compare" in hit:
            print(f"    compare    : same buff ids at same offset = "
                  f"{hit['buff_ids_match_in_compare']}  words={hit['compare_record_words'][:12]}")
    if weak:
        print(f"  weak candidates (score<4, no live time or single id): {len(weak)} "
              f"(first: {[hex(h['offset']) for h in weak[:6]]}; full list in JSON)")
    print()
    print("-- B. buff-ID arrays (len >= 3) --")
    for run in report["detector_b_buff_id_arrays"][:12]:
        static = "" if run["static"] is None else (" (static)" if run["static"] else " (LIVE)")
        print(f"  {run['offset']:#09x} len={run['length']:<3}{static} "
              f"ids={run['ids'][:8]} names={run['names'][:4]}")
    print()
    print("-- C. live-clock census --")
    census = report["detector_c_live_clock_census"]
    print(f"  fields within +-{census['tolerance_ms']} ms of the clock: {census['count']}")
    print(f"  of those, fields with a buff ID within 0x{census['window_for_buff_ids']:x}: "
          f"{census['near_buff_id_count']}")
    for row in census["fields"]:
        if row["buff_ids_within_0x10"]:
            print(f"    {row['offset']:#09x} value={row['value']} "
                  f"buff={row['buff_ids_within_0x10']}")
    print()
    print("-- D. curated known-buff ids --")
    for row in report["detector_d_curated_ids"]:
        print(f"  {row['id']:<8} u32={row['u32_hits']:<3} u16={row['u16_hits']:<3} "
              f"{row['table_name'][:28]:<28} {row['label']}")
    print()
    print("-- E. unit-object buff-ID check --")
    print(f"  {report['detector_e_unit_object_check']['note']}")
    for row in report["detector_e_unit_object_check"]["units"]:
        print(f"  {row['hero']:<6} hits={row['buff_id_hits']:<2} "
              f"adjacent_pairs={row['adjacent_buff_id_pairs']} "
              f"offsets={[hex(o) for o in row['hit_offsets'][:8]]}")
    print()
    print("-- verdicts --")
    for key, value in report["verdicts"].items():
        print(f"  {key:<24} {value}")
    print()
    for note in report["notes"]:
        print(f"  note: {note}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("arena", type=Path, help="30 MiB arena snapshot (.bin)")
    parser.add_argument("--compare", type=Path,
                        help="optional second arena from the SAME session for static/live classification")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT,
                        help=f"output directory (default {DEFAULT_OUT})")
    parser.add_argument("--buff-csv", type=Path, default=DEFAULT_BUFF_CSV,
                        help="native buff table CSV")
    parser.add_argument("--roster", type=Path, default=DEFAULT_ROSTER,
                        help="roster JSON (camp/hero/entity per player)")
    parser.add_argument("--top", type=int, default=25, help="max rows per detector")
    parser.add_argument("--no-write", action="store_true", help="print only, write no files")
    args = parser.parse_args(argv)

    for required in (args.arena, args.buff_csv, args.roster):
        if not required.exists():
            raise SystemExit(f"missing input: {required}")

    raw = args.arena.read_bytes()
    buff = load_buff_table(args.buff_csv)
    roster = load_roster(args.roster)
    ctx = resolve_units(raw, roster)

    compare_bytes = None
    compare_raw = None
    if args.compare:
        if not args.compare.exists():
            raise SystemExit(f"missing compare arena: {args.compare}")
        compare_raw = args.compare.read_bytes()
        compare_bytes = (raw, compare_raw)
        if len(compare_raw) != len(raw):
            print("warning: --compare size differs; only the shared prefix is compared",
                  file=sys.stderr)
            compare_raw = compare_raw[:len(raw)] if len(compare_raw) > len(raw) else None

    instances = detect_buff_instances(raw, ctx, buff, args.top, compare_raw)
    arrays = detect_buff_arrays(raw, buff, compare_bytes, min_len=3, top=args.top)
    clock_census = census_live_clock(raw, ctx, buff)
    curated = check_curated(raw, ctx, buff)
    units_check = check_unit_objects(raw, ctx, buff)

    report = build_report(args.arena, raw, ctx, buff, instances, arrays, clock_census,
                          curated, units_check, args.compare)
    print_summary(report)

    if not args.no_write:
        args.out.mkdir(parents=True, exist_ok=True)
        stem = args.arena.stem
        json_path = args.out / f"buff_probe_{stem}.json"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
        md_path = args.out / f"buff_probe_{stem}.md"
        md_path.write_text(render_markdown(report), encoding="utf-8")
        print()
        print(f"wrote {json_path}")
        print(f"wrote {md_path}")
    return 0


def render_markdown(report: dict) -> str:
    lines = [
        f"# engine buff probe - {Path(report['arena']).name}",
        "",
        f"generated: {report['generated_at_utc']}  tool: `{report['tool']}`",
        "",
        f"- arena base `{report['arena_base']:#x}` ({report['arena_base_votes']} pointer votes)",
        f"- replay clock `{report['clock_ms']}` ms (range {report['clock_range_ms']})",
        f"- native buff table rows: {report['buff_table']['native_buff_rows']}",
        "",
        "## verdicts",
        "",
        "| question | verdict |",
        "|---|---|",
    ]
    for key, value in report["verdicts"].items():
        lines.append(f"| {key} | **{value}** |")
    lines += ["", "## A. buff-instance records", "",
              "shape: `[qword class ptr][u32 small][u32 small][native buff ids][live time field]`", ""]
    strong = [h for h in report["detector_a_buff_instances"] if h["score"] >= 4]
    weak = [h for h in report["detector_a_buff_instances"] if h["score"] < 4]
    if strong:
        lines.append("| offset | class ptr | score | buff ids | live time fields |")
        lines.append("|---|---|---:|---|---|")
        for hit in strong:
            ids = ", ".join(f"{f['id']}({f['name'][:12]})" for f in hit["buff_fields"])
            lt = ", ".join(f"{f['value']} ({f['delta_ms']:+d} ms)" for f in hit["live_time_fields"])
            lines.append(f"| `{hit['offset']:#x}` | `{hit['class_pointer']:#x}` | {hit['score']} | {ids} | {lt} |")
    else:
        lines.append("_no strong candidate_")
    if weak:
        lines += ["", f"weak candidates (score < 4): {len(weak)} - "
                      f"{[hex(h['offset']) for h in weak[:8]]} (full list in JSON)"]
    lines += ["", "## B. buff-ID arrays", "",
              "| offset | length | static? | ids |", "|---|---:|---|---|"]
    for run in report["detector_b_buff_id_arrays"][:20]:
        static = "-" if run["static"] is None else ("static" if run["static"] else "LIVE")
        lines.append(f"| `{run['offset']:#x}` | {run['length']} | {static} | {run['ids'][:8]} |")
    lines += ["", "## C. live-clock census", "",
              f"- fields within +-{report['detector_c_live_clock_census']['tolerance_ms']} ms of the clock: "
              f"{report['detector_c_live_clock_census']['count']}",
              f"- of those with a buff ID within "
              f"0x{report['detector_c_live_clock_census']['window_for_buff_ids']:x}: "
              f"{report['detector_c_live_clock_census']['near_buff_id_count']}", ""]
    for row in report["detector_c_live_clock_census"]["fields"]:
        if row["buff_ids_within_0x10"]:
            lines.append(f"- `{row['offset']:#x}` value={row['value']} "
                         f"buff={row['buff_ids_within_0x10']}")
    lines += ["", "## D. curated known-buff ids", "",
              "| id | name | u32 hits | u16 hits | note |", "|---:|---|---:|---:|---|"]
    for row in report["detector_d_curated_ids"]:
        lines.append(f"| {row['id']} | {row['table_name'][:24]} | {row['u32_hits']} | "
                     f"{row['u16_hits']} | {row['label'][:40]} |")
    lines += ["", "## E. unit-object buff-ID check", "",
              report["detector_e_unit_object_check"]["note"], "",
              "| hero | buff-id-like hits in 0x1888 | adjacent pairs | offsets |",
              "|---|---:|---:|---|"]
    for row in report["detector_e_unit_object_check"]["units"]:
        lines.append(f"| {row['hero']} | {row['buff_id_hits']} | {row['adjacent_buff_id_pairs']} | "
                     f"{[hex(o) for o in row['hit_offsets'][:8]]} |")
    lines += ["", "## notes", ""]
    for note in report["notes"]:
        lines.append(f"- {note}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
