#!/usr/bin/env python3
"""Wait for a replay context, then run the closure capture automatically.

Polling the holder chain is read-only.  As soon as a replay is loaded and the
context size is stable, the normal capture tool runs (it freezes the process
only for the duration of the read, then resumes it).

Usage:
  python host/scripts/watch_and_capture.py --out data/.../closure_live --timeout 1800
"""
from __future__ import annotations

import argparse
import json
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
    ap.add_argument("--package", default="com.tencent.tmgp.sgame")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--stable", type=int, default=2)
    ap.add_argument("--timeout", type=float, default=1800)
    ap.add_argument("--object-hops", type=int, default=1)
    args = ap.parse_args()

    adb = Adb(args.adb, args.serial)
    started = time.time()
    last = None
    stable = 0
    cached_pid, cached_maps, cached_at = None, None, 0.0
    while time.time() - started < args.timeout:
        pids = adb.pids(args.package)
        if not pids:
            time.sleep(args.interval)
            continue
        pid = pids[0]
        try:
            now = time.time()
            if pid != cached_pid or cached_maps is None or now - cached_at > 60:
                cached_maps = adb.read_maps(pid)
                cached_pid, cached_at = pid, now
            maps = cached_maps
            base = next((m.start for m in maps
                         if m.path.endswith("/libGameCore.so") and m.offset == 0), None)
            if not base:
                time.sleep(args.interval)
                continue
            reader = Reader(adb, pid, maps)
            pointer = reader.u64(base + 0x4FF4520)
            for _ in range(2):
                pointer = reader.u64(pointer) if pointer else 0
            ctx = pointer
            size = reader.u32(ctx + 8) if ctx else 0
        except Exception:
            ctx, size = 0, 0
        state = (ctx, size)
        if ctx and size == 0x1E00000:
            stable = stable + 1 if state == last else 1
            last = state
            print(f"context {ctx:#x} size {size:#x} stable={stable}", flush=True)
            if stable >= args.stable:
                print("capturing...", flush=True)
                cmd = [sys.executable, str(ROOT / "host/scripts/capture_closure_snapshot.py"),
                       "--out", str(args.out), "--object-hops", str(args.object_hops)]
                subprocess.run(cmd, check=True)
                return 0
        else:
            stable, last = 0, None
        time.sleep(args.interval)
    print("timeout: no replay context appeared", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
