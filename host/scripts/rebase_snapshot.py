"""Rebase a GameCore process snapshot into a 39-bit address space.

The MuMu snapshot was captured with 47/48-bit virtual addresses (0x75d7...,
0x4000...).  A real arm64 phone commonly exposes only 39-bit VA (top ~0x8000000000),
so MAP_FIXED_NOREPLACE at the original addresses returns ENOMEM.

This tool copies every region to a new, page-aligned base inside the target
space and rewrites every aligned qword that points into another snapshot region.
Pointers into the old libGameCore range are intentionally left untouched: the
loader (gc_transplant) relocates them by `new_libgamecore - old_libgamecore`.

Output is a new snapshot directory with regions.tsv / meta_rebased.json.
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import struct
from pathlib import Path

import numpy as np

PAGE = 4096
DEFAULT_BASE = 0x2000000000  # 128 GiB, inside a 39-bit VA


def parse_tsv(path: Path):
    rows = []
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split("\t")
        row = dict(zip(header, parts))
        row["start"] = int(row["start"], 0)
        row["end"] = int(row["end"], 0)
        rows.append(row)
    return rows


def align(value: int, size: int = PAGE) -> int:
    return (value + size - 1) // size * size


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--base", type=lambda v: int(v, 0), default=DEFAULT_BASE)
    args = parser.parse_args()

    rows = parse_tsv(args.snapshot / "regions.tsv")
    rows.sort(key=lambda row: row["start"])
    out = args.out
    out.mkdir(parents=True, exist_ok=True)

    # Allocate a new, contiguous, page-aligned range for each region.
    new_rows = []
    cursor = args.base
    for row in rows:
        size = row["end"] - row["start"]
        new_start = align(cursor)
        new_end = new_start + size
        new_rows.append({**row, "old_start": row["start"], "old_end": row["end"],
                         "new_start": new_start, "new_end": new_end})
        cursor = new_end + PAGE

    # Old -> new ranges for pointer rewriting.  One vectorised pass per region
    # instead of one full-array scan per range (137 ranges x 729 MB otherwise).
    ranges = sorted((row["old_start"], row["old_end"], row["new_start"])
                    for row in new_rows)
    starts_arr = np.array([item[0] for item in ranges], dtype=np.uint64)
    ends_arr = np.array([item[1] for item in ranges], dtype=np.uint64)
    news_arr = np.array([item[2] for item in ranges], dtype=np.uint64)
    old_meta = {}
    meta_path = args.snapshot / "meta.json"
    if meta_path.exists():
        old_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    gc_base = int(str(old_meta.get("libgamecore_base") or "0x0"), 0)
    gc_end = gc_base + 0x544D478 if gc_base else 0

    total_rewrites = 0
    dangling = 0
    dangling_targets: dict[int, int] = {}
    for row in new_rows:
        raw = (args.snapshot / row["file"]).read_bytes()
        n = len(raw) // 8
        buffer = bytearray(raw)
        data = np.frombuffer(buffer, dtype="<u8")  # writable view
        idx = np.searchsorted(starts_arr, data, side="right").astype(np.int64) - 1
        valid = idx >= 0
        safe = np.clip(idx, 0, len(ranges) - 1)
        valid &= data < ends_arr[safe]
        values = data - starts_arr[safe] + news_arr[safe]
        # Packed GameCore structs keep 64-bit pointers at 4-byte alignment
        # (e.g. CS slot0+0x18 at ...0x1114), so scan a second, offset-4 view.
        d4 = np.ndarray(shape=(n - 1,), dtype="<u8", buffer=buffer, offset=4)
        idx4 = np.searchsorted(starts_arr, d4, side="right").astype(np.int64) - 1
        valid4 = idx4 >= 0
        safe4 = np.clip(idx4, 0, len(ranges) - 1)
        valid4 &= d4 < ends_arr[safe4]
        values4 = d4 - starts_arr[safe4] + news_arr[safe4]
        # An offset-4 write overlaps aligned qwords j and j+1; never clobber a
        # qword that was itself translated.
        conflict = valid[:n - 1] | valid[1:]
        do4 = valid4 & ~conflict

        data[valid] = values[valid]
        d4[do4] = values4[do4]
        total_rewrites += int(valid.sum()) + int(do4.sum())

        # Diagnostics: aligned pointers that still point outside the snapshot.
        # libGameCore is excluded because the loader relocates it.
        ptr = (data >= 0x1000000000) & (data < 0x800000000000) & ~valid
        if gc_end:
            ptr &= ~((data >= gc_base) & (data < gc_end))
        if ptr.any():
            uniq, counts = np.unique(data[ptr], return_counts=True)
            for value, hits in zip(uniq.tolist(), counts.tolist()):
                dangling += hits
                dangling_targets[value] = dangling_targets.get(value, 0) + hits
        blob = bytes(buffer)
        out_file = out / row["file"]
        out_file.write_bytes(blob)
        row["new_sha256"] = hashlib.sha256(blob).hexdigest()

    # Rewrite regions.tsv with the new addresses.
    with (out / "regions.tsv").open("w", encoding="utf-8", newline="") as handle:
        handle.write("start\tend\tperms\tpath\tfile\tsize\tsha256\n")
        for row in new_rows:
            handle.write("\t".join([
                f"0x{row['new_start']:x}", f"0x{row['new_end']:x}",
                row["perms"], row["path"] or "-", row["file"],
                str(row["new_end"] - row["new_start"]), row["new_sha256"],
            ]) + "\n")

    def translate(address: int):
        for row in new_rows:
            if row["old_start"] <= address < row["old_end"]:
                return row["new_start"] + (address - row["old_start"])
        return None

    global_slots = old_meta.get("global_slots") or {}
    old_context = int(str(old_meta.get("context", "0x75d7e86e9ff0")), 0)
    old_binder = int(str(old_meta.get("binder_context") or old_context), 0)
    consumer_slot = global_slots.get("0x544cc40")
    old_consumer = int(str(consumer_slot), 0) if consumer_slot else 0

    # Classify dangling pointers against the source process map, if present.
    map_rows = []
    maps_path = args.snapshot / "maps.txt"
    if maps_path.exists():
        for line in maps_path.read_text(encoding="utf-8", errors="replace").splitlines():
            parts = line.split(maxsplit=5)
            if len(parts) < 5:
                continue
            try:
                start, end = (int(x, 16) for x in parts[0].split("-"))
            except ValueError:
                continue
            map_rows.append((start, end, parts[1],
                             parts[5].strip() if len(parts) > 5 else ""))
    map_starts = [row[0] for row in map_rows]

    def where(address: int):
        i = bisect.bisect_right(map_starts, address) - 1
        if i < 0 or address >= map_rows[i][1]:
            return None
        return map_rows[i]

    top = sorted(dangling_targets.items(), key=lambda item: -item[1])[:10]
    dangling_top = []
    for address, hits in top:
        found = where(address)
        dangling_top.append({
            "address": hex(address), "hits": hits,
            "perms": found[2] if found else None,
            "path": (found[3] if found else None),
            "size": (found[1] - found[0]) if found else None,
        })
    meta = {
        "schema": "kpl-gamecore-process-snapshot-rebased-v1",
        "source": str(args.snapshot),
        "old_context": hex(old_context),
        "new_context": hex(translate(old_context)) if translate(old_context) else None,
        "old_binder_context": hex(old_binder),
        "new_binder_context": hex(translate(old_binder)) if translate(old_binder) else None,
        "old_consumer": hex(old_consumer) if old_consumer else None,
        "new_consumer": hex(translate(old_consumer)) if translate(old_consumer) else None,
        "old_libgamecore_base": old_meta.get("libgamecore_base"),
        "base": hex(args.base),
        "regions": len(new_rows),
        "bytes": sum(row["new_end"] - row["new_start"] for row in new_rows),
        "pointer_rewrites": total_rewrites,
        "dangling_pointers": dangling,
        "dangling_unique": len(dangling_targets),
        "dangling_top": dangling_top,
    }
    (out / "meta_rebased.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
