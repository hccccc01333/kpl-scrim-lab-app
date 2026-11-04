#!/usr/bin/env python3
"""A1: capture the live context's reachable process mappings by original address.

Read-only and local-only. Raw snapshot bytes go under data/ (gitignored); the
manifest contains addresses/sizes/hashes, never raw strings or account fields.
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.frapinfo_live_probe import Adb, Reader  # noqa: E402


def hx(v: int) -> str:
    return f"0x{v:x}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adb", default="D:/MuMuPlayer/nx_main/adb.exe")
    ap.add_argument("--serial", default="127.0.0.1:16384")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--no-freeze", action="store_true")
    ap.add_argument("--extra-region", action="append", default=[],
                    help="start-end hex pair to force include")
    args = ap.parse_args()

    adb = Adb(args.adb, args.serial)
    pids = adb.pids("com.tencent.tmgp.sgame")
    if not pids:
        print("game process not found", file=sys.stderr)
        return 2
    pid = pids[0]
    maps = adb.read_maps(pid)
    base = next((m.start for m in maps
                 if m.path.endswith("/libGameCore.so") and m.offset == 0), None)
    if not base:
        print("libGameCore base not found", file=sys.stderr)
        return 2
    r = Reader(adb, pid, maps)
    p = base + 0x4FF4520
    for _ in range(3):
        p = r.u64(p)
    ctx = p
    if not ctx:
        print("context not resident", file=sys.stderr)
        return 3
    size = r.u32(ctx + 8)
    if not size or size > 0x4000000:
        print(f"bad context size {size}", file=sys.stderr)
        return 3

    def dd_read(start: int, length: int, timeout: int = 180) -> bytes | None:
        page = start & ~0xFFF
        off = start - page
        pages = (off + length + 0xFFF) // 0x1000
        cmd = (f"dd if=/proc/{pid}/mem bs=4096 skip={page // 4096} "
               f"count={pages} 2>/dev/null")
        raw = subprocess.run([args.adb, "-s", args.serial, "exec-out", cmd],
                             capture_output=True, timeout=timeout).stdout
        if len(raw) != pages * 0x1000:
            return None
        return raw[off:off + length]

    print(f"pid={pid} context={hx(ctx)} size={size}; reading arena", flush=True)
    arena = dd_read(ctx, size)
    if arena is None:
        print("cannot read context arena", file=sys.stderr)
        return 4
    a = np.frombuffer(arena, dtype="<u8", count=size // 8)
    keep = ((a >= 0x400000000000) & (a < 0x800000000000)
            & ~((a >= ctx) & (a < ctx + size))
            & ~((a >= base) & (a < base + 0x544D478)))
    targets = np.unique(a[keep])
    starts = [m.start for m in maps]

    def region_of(v: int):
        i = bisect.bisect_right(starts, v) - 1
        return maps[i] if i >= 0 and v < maps[i].end else None

    selected: dict[tuple[int, int], object] = {}
    # context's own mapping
    cm = region_of(ctx)
    if cm:
        selected[(cm.start, cm.end)] = cm
    for v in targets.tolist():
        m = region_of(v)
        if not m:
            continue
        path = m.path or ""
        if ".so" in path or "framework-res.apk" in path:
            continue
        if m.perms.startswith("r") and ("dataCache.db" in path or "scudo" in path
                                        or "Mem_" in path or not path):
            selected[(m.start, m.end)] = m
    for item in args.extra_region:
        try:
            s, e = (int(x, 16) for x in item.split("-"))
        except ValueError:
            continue
        for m in maps:
            if m.start <= s and e <= m.end:
                selected[(m.start, m.end)] = m
                break

    regions = sorted(selected.values(), key=lambda m: m.start)
    total = sum(m.size for m in regions)
    print(f"pid={pid} context={hx(ctx)} size={size} regions={len(regions)} "
          f"bytes={total}", flush=True)

    stopped = False
    if not args.no_freeze:
        subprocess.run([args.adb, "-s", args.serial, "shell", "kill", "-STOP", str(pid)],
                       check=False)
        stopped = True
        time.sleep(0.3)

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    try:
        for idx, m in enumerate(regions):
            page = m.start & ~0xFFF
            off = m.start - page
            pages = (off + m.size + 0xFFF) // 0x1000
            fn = out / f"region_{m.start:x}_{m.end:x}.bin"
            cmd = (f"dd if=/proc/{pid}/mem bs=4096 skip={page // 4096} "
                   f"count={pages} 2>/dev/null")
            print(f"[{idx+1}/{len(regions)}] {hx(m.start)}-{hx(m.end)} "
                  f"{m.size/1048576:.1f} MiB {m.path or '[anon]'}", flush=True)
            ok = False
            for attempt in range(1, 4):
                with fn.open("wb") as fh:
                    proc = subprocess.run([args.adb, "-s", args.serial, "exec-out", cmd],
                                          stdout=fh, stderr=subprocess.DEVNULL, timeout=300)
                if proc.returncode == 0 and fn.stat().st_size == pages * 0x1000:
                    ok = True
                    break
                print(f"  retry {attempt}/3: {fn.name} size={fn.stat().st_size} "
                      f"expected={pages*0x1000}", flush=True)
                time.sleep(1)
            if not ok:
                print(f"short/failed read {fn} after retries", file=sys.stderr)
                return 5
            data = fn.read_bytes()[off:off + m.size]
            if len(data) != m.size:
                print(f"truncated region {fn}", file=sys.stderr)
                return 5
            rows.append({
                "start": m.start, "end": m.end, "perms": m.perms,
                "path": m.path or "", "file": fn.name,
                "size": m.size, "sha256": hashlib.sha256(data).hexdigest(),
            })
            # keep only exact region bytes; remove page padding
            if off or pages * 0x1000 != m.size:
                fn.write_bytes(data)
    finally:
        if stopped:
            for _ in range(4):
                subprocess.run([args.adb, "-s", args.serial, "shell", "kill", "-CONT", str(pid)],
                               check=False)
                time.sleep(0.5)

    manifest = {
        "schema": "kpl-gamecore-process-snapshot-v1",
        "pid": pid,
        "context": hx(ctx),
        "context_size": size,
        "libgamecore_base": hx(base),
        "libgamecore_end": hx(base + 0x544D478),
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "regions": rows,
        "total_bytes": total,
        "boundary": "read-only local snapshot under data/; not committed",
    }
    (out / "meta.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
    with (out / "regions.tsv").open("w", encoding="utf-8") as fh:
        fh.write("start\tend\tperms\tpath\tfile\tsize\tsha256\n")
        for row in rows:
            fh.write(f"{row['start']:#x}\t{row['end']:#x}\t{row['perms']}\t"
                     f"{row['path']}\t{row['file']}\t{row['size']}\t{row['sha256']}\n")
    print(f"wrote {out}/meta.json, {len(rows)} regions, {total} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
