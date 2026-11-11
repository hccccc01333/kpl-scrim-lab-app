#!/usr/bin/env python3
"""Capture a transplant-ready closure of the live GameCore context.

`capture_process_snapshot.py` follows one level of pointers out of the context
arena.  That missed the CS staging buffer, so `CommitCsBuffer` wrote into an
address that did not exist on the host and the transplant segfaulted.

This tool captures two sets:

  arena   the context arena + every mapping its pointers reference (leaves;
          this is the old behaviour and carries the game state)
  objects the binder/CS/consumer objects and their direct buffers (two hops),
          which is where the FIFO staging memory lives

Writable heap mappings are kept; code, stacks, reserves and Java heaps are not.
Read-only file images (dataCache.db) are kept as leaves.  Raw bytes stay under
data/ (gitignored); the manifest keeps addresses/sizes/hashes only.
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import subprocess
import sys
import tempfile
import time
from collections import Counter, deque
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.frapinfo_live_probe import Adb, Reader  # noqa: E402

PAGE = 4096
LO, HI = 0x1000000000, 0x800000000000

# Global slots published by the binder / CS init, relative to libGameCore base.
GLOBAL_SLOTS = (
    0x52717B0,  # holder slot -> context
    0x544CC40,  # CS consumer object
    0x544D340,  # command table pointer
    0x52C3250,  # CS slot0
    0x52C3258,  # CS slot1
    0x52C3270,  # CS slot4 (ctx+0x4F0)
    0x52C3278,  # CS slot5 (ctx+0x578)
)


def hx(value: int) -> str:
    return f"0x{value:x}"


def allow_map(mapping, path: str) -> bool:
    """Only reproducible heap/data mappings; never code, stacks or reserves."""
    perms = mapping.perms
    if not perms.startswith("r") or len(perms) < 2 or perms[1] != "w":
        return "dataCache.db" in path
    if "reserve" in path:
        return False
    if path.startswith("["):
        return "scudo" in path or "Mem_" in path
    if not path:
        return True
    return "dataCache.db" in path


def perm_path(mapping) -> str:
    tail = (mapping.path or "[anon]").split("/")[-1][:32]
    return f"{mapping.perms}:{tail}"


def read_region(adb: Adb, pid: int, mapping, timeout: int = 180) -> bytes | None:
    page = mapping.start & ~(PAGE - 1)
    off = mapping.start - page
    pages = (off + mapping.size + PAGE - 1) // PAGE
    cmd = (f"dd if=/proc/{pid}/mem bs=4096 skip={page // PAGE} "
           f"count={pages} 2>/dev/null")
    tmp = Path(tempfile.gettempdir()) / f"region_{pid}_{mapping.start:x}.tmp"
    try:
        for _ in range(3):
            with tmp.open("wb") as handle:
                proc = subprocess.run([adb.exe, "-s", adb.serial, "exec-out", cmd],
                                      stdout=handle, stderr=subprocess.DEVNULL,
                                      timeout=timeout)
            if proc.returncode == 0 and tmp.stat().st_size == pages * PAGE:
                return tmp.read_bytes()[off:off + mapping.size]
            time.sleep(1)
        return None
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


class Mapper:
    """Resolve addresses to mappings with a vectorised batch path."""

    def __init__(self, maps):
        self.maps = maps
        self.starts = np.array([m.start for m in maps], dtype=np.uint64)
        self.ends = np.array([m.end for m in maps], dtype=np.uint64)

    def one(self, value: int):
        idx = int(np.searchsorted(self.starts, np.uint64(value), side="right")) - 1
        return self.maps[idx] if idx >= 0 and value < self.maps[idx].end else None

    def batch(self, blob: bytes) -> tuple[list, int]:
        data = np.frombuffer(blob, dtype="<u8")
        mask = (data >= LO) & (data < HI)
        if not mask.any():
            return [], 0
        values = np.unique(data[mask])
        idx = np.searchsorted(self.starts, values, side="right") - 1
        valid = idx >= 0
        safe = np.clip(idx, 0, len(self.maps) - 1)
        valid &= values < self.ends[safe]
        unmapped = int((~valid).sum())
        kept = np.unique(idx[valid])
        return [self.maps[int(i)] for i in kept], unmapped


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adb", default="D:/MuMuPlayer/nx_main/adb.exe")
    ap.add_argument("--serial", default="127.0.0.1:16384")
    ap.add_argument("--package", default="com.tencent.tmgp.sgame")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed-address", action="append", default=[],
                    help="extra object address to seed (hex)")
    ap.add_argument("--object-hops", type=int, default=1,
                    help="how many pointer hops to follow from CS objects")
    ap.add_argument("--max-bytes", type=lambda v: int(v, 0), default=0x40000000)
    ap.add_argument("--max-regions", type=int, default=512)
    ap.add_argument("--no-freeze", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    adb = Adb(args.adb, args.serial)
    pids = adb.pids(args.package)
    if not pids:
        print("game process not found", file=sys.stderr)
        return 2
    pid, maps = None, None
    for candidate in pids:
        rows = adb.read_maps(candidate)
        if any("libil2cpp.so" in row.path for row in rows):
            pid, maps = candidate, rows
            break
    if pid is None:
        pid, maps = pids[0], adb.read_maps(pids[0])
    base = next((row.start for row in maps
                 if row.path.endswith("/libGameCore.so") and row.offset == 0), None)
    if not base:
        print("libGameCore base not found", file=sys.stderr)
        return 2

    reader = Reader(adb, pid, maps)
    pointer = base + 0x4FF4520
    for _ in range(3):
        pointer = reader.u64(pointer)
    ctx = pointer
    if not ctx:
        print("context not resident", file=sys.stderr)
        return 3
    size = reader.u32(ctx + 8)
    if not size or size > 0x4000000:
        print(f"bad context size {size}", file=sys.stderr)
        return 3
    binder = ctx + 0x1DFFA00
    if reader.u32(binder + 8) is None:
        print("binder context not resident", file=sys.stderr)
        return 3

    mapper = Mapper(maps)
    module_start, module_end = base, base + 0x6000000
    arena_region = mapper.one(ctx)
    if arena_region is None:
        print("context mapping not found", file=sys.stderr)
        return 3

    object_seeds = []
    slots = {}
    for slot in GLOBAL_SLOTS:
        value = reader.u64(base + slot)
        slots[hx(slot)] = hx(value) if value else None
        if value and LO <= value < HI:
            object_seeds.append(value)
    for extra in args.seed_address:
        object_seeds.append(int(extra, 0))
    print(f"pid={pid} context={hx(ctx)} binder={hx(binder)} size={size} "
          f"libgamecore={hx(base)}")
    print("global slots:", json.dumps(slots))

    reasons: Counter = Counter()
    chosen: dict[tuple[int, int], object] = {}
    order: list[tuple[int, int]] = []
    planned = [0]

    def add(mapping) -> bool:
        key = (mapping.start, mapping.end)
        if key in chosen:
            return False
        if len(chosen) >= args.max_regions:
            reasons["region_cap"] += 1
            return False
        if planned[0] + mapping.size > args.max_bytes:
            reasons["budget"] += 1
            return False
        # The host loads its own libGameCore; never shadow that range with
        # snapshot bytes (the loader relocates module pointers itself).
        if mapping.start < module_end and mapping.end > module_start:
            reasons["module"] += 1
            return False
        if not allow_map(mapping, mapping.path or ""):
            reasons[f"skip:{perm_path(mapping)}"] += 1
            return False
        if mapping.size > args.max_bytes:
            reasons["oversize"] += 1
            return False
        chosen[key] = mapping
        order.append(key)
        planned[0] += mapping.size
        return True

    # Phase 1: arena + pointer targets (leaves, not expanded).
    add(arena_region)
    arena = read_region(adb, pid, arena_region)
    if arena is None:
        print("cannot read context arena", file=sys.stderr)
        return 4
    targets, unmapped = mapper.batch(arena)
    reasons["unmapped"] += unmapped
    leaf = 0
    arena_leaf_keys = []
    for target in targets:
        if add(target):
            leaf += 1
            arena_leaf_keys.append((target.start, target.end))
    print(f"arena: {hx(arena_region.start)} {size/1048576:.1f} MiB -> "
          f"{leaf} leaf regions", flush=True)

    # Phase 2: follow the CS/consumer objects for a few hops.
    queue = deque(object_seeds)
    visited: set[tuple[int, int]] = set()
    for hop in range(1, args.object_hops + 1):
        wave, queue = list(queue), deque()
        print(f"--- object hop {hop}: {len(wave)} seeds", flush=True)
        for value in wave:
            mapping = mapper.one(value)
            if mapping is None:
                continue
            key = (mapping.start, mapping.end)
            if key in visited:
                continue
            visited.add(key)
            if not allow_map(mapping, mapping.path or "") \
                    or mapping.size > args.max_bytes:
                reasons[f"skip:{perm_path(mapping)}"] += 1
                continue
            if key not in chosen:
                add(mapping)
            blob = read_region(adb, pid, mapping)
            if blob is None:
                print(f"  read failed {hx(mapping.start)}", file=sys.stderr)
                return 5
            found, unmapped = mapper.batch(blob)
            reasons["unmapped"] += unmapped
            added = 0
            for target in found:
                if add(target):
                    queue.append(target.start)
                    added += 1
            print(f"  {hx(mapping.start):>14} {mapping.size/1048576:7.2f} MiB "
                  f"{perm_path(mapping)[:40]:40s} +{added}", flush=True)

    # Phase 3: module globals are roots too.  The frame-advance path touches
    # objects referenced only from .data/.bss; without them it crashes.
    module_maps = [m for m in maps
                   if m.start >= module_start and m.end <= module_end
                   and m.perms.startswith("rw")]
    globals_blobs = []
    for m in module_maps:
        blob = read_region(adb, pid, m)
        if blob is None:
            print(f"globals read failed {hx(m.start)}", file=sys.stderr)
            return 5
        globals_blobs.append((m, blob))
    def add_root(target) -> bool:
        # Only engine-owned heap objects: managed/GC chunks are huge anon
        # mappings that the host cannot use without libil2cpp.
        if "scudo" in (target.path or "") or target.size <= 0x100000:
            return add(target)
        reasons["skip:root-large"] += 1
        return False

    root_keys = []
    for m, blob in globals_blobs:
        found, unmapped = mapper.batch(blob)
        reasons["unmapped"] += unmapped
        for target in found:
            if add_root(target):
                root_keys.append((target.start, target.end))
    root_set = set(root_keys)
    for key in root_set:
        mapping = chosen.get(key)
        if mapping is None or mapping.size > args.max_bytes:
            continue
        blob = read_region(adb, pid, mapping)
        if blob is None:
            continue
        found, unmapped = mapper.batch(blob)
        reasons["unmapped"] += unmapped
        for target in found:
            add_root(target)
    print(f"globals roots: {len(globals_blobs)} segments -> "
          f"{len(root_set)} regions", flush=True)

    # One hop from the arena leaves.  Shared engine tables are often reached
    # only through player/config objects, not from the arena directly.
    scanned = set(root_set) | {(arena_region.start, arena_region.end)}
    for key in arena_leaf_keys:
        mapping = chosen.get(key)
        if mapping is None or mapping.size > 0x1000000:
            continue
        if "dataCache.db" in (mapping.path or ""):
            continue
        if not mapping.perms.startswith("rw"):
            continue
        if key in scanned:
            continue
        scanned.add(key)
        blob = read_region(adb, pid, mapping)
        if blob is None:
            continue
        found, unmapped = mapper.batch(blob)
        reasons["unmapped"] += unmapped
        for target in found:
            add_root(target)

    # Merge fragmented mappings: a live heap chunk may be split at a boundary,
    # leaving a table half outside the captured interval.
    by_start = {m.start: m for m in maps}
    for _ in range(4):
        grew = False
        for key in list(order):
            mapping = chosen[key]
            nxt = by_start.get(mapping.end)
            if nxt is None:
                continue
            if nxt.perms != mapping.perms or (nxt.path or "") != (mapping.path or ""):
                continue
            if add(nxt):
                grew = True
        if not grew:
            break

    total = sum(chosen[key].size for key in order)
    print(f"selected: {len(order)} regions, {total} bytes "
          f"({total/2**20:.1f} MiB)")
    print("filters:", json.dumps(reasons.most_common(10), ensure_ascii=False))
    if args.dry_run:
        for key in sorted(order):
            mapping = chosen[key]
            print(f"  {hx(mapping.start):>14} {mapping.size/1048576:8.2f} MiB "
                  f"{perm_path(mapping)}")
        return 0

    stopped = False
    if not args.no_freeze:
        subprocess.run([adb.exe, "-s", adb.serial, "shell",
                        "kill", "-STOP", str(pid)], check=False)
        stopped = True
        time.sleep(0.3)
    # Re-read the arena from the frozen process: planning may have taken
    # minutes while the replay was still advancing.
    fresh = read_region(adb, pid, arena_region)
    if fresh is None:
        if stopped:
            subprocess.run([adb.exe, "-s", adb.serial, "shell",
                            "kill", "-CONT", str(pid)], check=False)
        print("cannot re-read arena after freeze", file=sys.stderr)
        return 4
    arena = fresh
    out = args.out
    if not args.dry_run:
        out.mkdir(parents=True, exist_ok=True)
    rows = []
    try:
        for index, key in enumerate(order, 1):
            mapping = chosen[key]
            blob = arena if key == (arena_region.start, arena_region.end) \
                else read_region(adb, pid, mapping)
            if blob is None:
                print(f"read failed {hx(mapping.start)}", file=sys.stderr)
                return 5
            name = f"region_{mapping.start:x}_{mapping.end:x}.bin"
            if not args.dry_run:
                (out / name).write_bytes(blob)
            rows.append({
                "start": mapping.start, "end": mapping.end,
                "perms": mapping.perms, "path": mapping.path or "",
                "file": name, "size": mapping.size,
                "sha256": hashlib.sha256(blob).hexdigest(),
            })
            if index % 20 == 0 or index == len(order):
                print(f"  captured {index}/{len(order)}", flush=True)
    finally:
        if stopped:
            for _ in range(3):
                subprocess.run([adb.exe, "-s", adb.serial, "shell",
                                "kill", "-CONT", str(pid)], check=False)
                time.sleep(0.4)

    # Module globals: without these the host's freshly initialised BSS lacks
    # the replay/level objects and frame advance crashes at a null+offset.
    globals_dir = out / "globals"
    globals_rows = []
    if not args.dry_run and globals_blobs:
        globals_dir.mkdir(parents=True, exist_ok=True)
        for m, blob in globals_blobs:
            name = f"globals_{m.start - base:x}_{m.end - base:x}.bin"
            (globals_dir / name).write_bytes(blob)
            globals_rows.append({
                "rel_start": m.start - base, "rel_end": m.end - base,
                "size": m.size, "perms": m.perms, "path": m.path or "-",
                "file": name, "sha256": hashlib.sha256(blob).hexdigest(),
            })
        with (globals_dir / "manifest.tsv").open("w", encoding="utf-8") as handle:
            sep = chr(9)
            handle.write(sep.join(["rel_start", "rel_end", "size", "perms",
                                   "path", "file", "sha256"]) + chr(10))
            for row in globals_rows:
                handle.write(sep.join([
                    f"{row['rel_start']:#x}", f"{row['rel_end']:#x}",
                    str(row['size']), row['perms'], row['path'],
                    row['file'], row['sha256']]) + chr(10))
        print(f"captured {len(globals_rows)} module globals segments")

    if args.dry_run:
        return 0

    manifest = {
        "schema": "kpl-gamecore-closure-snapshot-v2",
        "pid": pid,
        "context": hx(ctx),
        "binder_context": hx(binder),
        "context_size": size,
        "libgamecore_base": hx(base),
        "libgamecore_end": hx(base + 0x544D478),
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "global_slots": slots,
        "globals_segments": len(globals_rows),
        "object_hops": args.object_hops,
        "regions": rows,
        "total_bytes": total,
        "filter_counts": dict(reasons),
        "boundary": "read-only local snapshot under data/; not committed",
    }
    (out / "meta.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
    with (out / "regions.tsv").open("w", encoding="utf-8", newline="") as handle:
        handle.write("start\tend\tperms\tpath\tfile\tsize\tsha256\n")
        for row in rows:
            handle.write(f"{row['start']:#x}\t{row['end']:#x}\t{row['perms']}\t"
                         f"{row['path'] or '-'}\t{row['file']}\t{row['size']}\t"
                         f"{row['sha256']}\n")
    print(f"wrote {out}/meta.json, {len(rows)} regions, {total} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
