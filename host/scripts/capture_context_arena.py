#!/usr/bin/env python3
"""Capture the full live GameCore context arena (read-only, H4-A).

Raw arena is written only under data/ (gitignored); the JSON metadata contains
addresses/hashes/counts, never raw strings or account fields.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.frapinfo_live_probe import Adb, Reader  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adb", default="D:/MuMuPlayer/nx_main/adb.exe")
    ap.add_argument("--serial", default="127.0.0.1:16384")
    ap.add_argument("--out-dir", type=Path, required=True)
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
        print(f"unexpected arena size {size}", file=sys.stderr)
        return 3

    subprocess.run([args.adb, "-s", args.serial, "shell", "kill", "-STOP", str(pid)],
                   check=False)
    time.sleep(0.3)
    try:
        page = ctx & ~0xFFF
        off = ctx - page
        pages = (off + size + 0xFFF) // 0x1000
        cmd = (f"dd if=/proc/{pid}/mem bs=4096 skip={page // 4096} "
               f"count={pages} 2>/dev/null")
        raw = subprocess.run([args.adb, "-s", args.serial, "exec-out", cmd],
                             capture_output=True, timeout=180).stdout
        if len(raw) != pages * 0x1000:
            print(f"short read {len(raw)} != {pages * 0x1000}", file=sys.stderr)
            return 4
        data = raw[off:off + size]
    finally:
        subprocess.run([args.adb, "-s", args.serial, "shell", "kill", "-CONT", str(pid)],
                       check=False)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = args.out_dir / f"context_arena_{pid}.bin"
    raw_path.write_bytes(data)
    meta = {
        "schema": "kpl-gamecore-context-arena-v1",
        "pid": pid,
        "base": f"0x{base:x}",
        "context": f"0x{ctx:x}",
        "size": size,
        "sha256": hashlib.sha256(data).hexdigest(),
        "raw_file": str(raw_path),
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "boundary": "read-only; raw arena under data/, not committed",
    }
    (args.out_dir / f"context_arena_{pid}.meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in meta.items() if k != "raw_file"},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
