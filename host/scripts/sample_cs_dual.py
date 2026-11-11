#!/usr/bin/env python3
"""Dual-slot CS stream sampler: slot0 (CS) + slot1 (Cpp pack), reset-aware.

Extends sample_cs_stream.py to poll both ring channels each interval and to
detect cursor resets (replay restart / battle context change) so the captured
deltas can be split into epochs.  Read-only: /proc/<pid>/mem via adb dd.

JSONL rows:
  {"t", "slot", "epoch", "write", "from", "data"}   delta bytes
  {"t", "slot", "epoch", "reset_from", "reset_to"}  cursor reset detected
  {"t", "meta", "slot0_write", "slot1_write", ...}  periodic full state

Usage:
  python host/scripts/sample_cs_dual.py --pid 2052 --interval 0.7 \
      --duration 1800 --out host/build/g5/cs_dual_run2.jsonl
"""
from __future__ import annotations

import argparse
import json
import struct
import subprocess
import sys
import time
from pathlib import Path

PAGE = 0x1000


class MemReader:
    def __init__(self, adb: str, serial: str, pid: int):
        self.adb = adb
        self.serial = serial
        self.pid = pid

    def read(self, addr: int, size: int) -> bytes:
        start_page = addr // PAGE
        end_page = (addr + size + PAGE - 1) // PAGE
        remote = (
            f"dd if=/proc/{self.pid}/mem bs={PAGE} skip={start_page} count={end_page-start_page} "
            f"2>/dev/null | dd bs=1 skip={addr - start_page*PAGE} count={size} 2>/dev/null"
        )
        r = subprocess.run(
            [self.adb, "-s", self.serial, "exec-out", remote],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        if len(r.stdout) != size:
            raise RuntimeError(f"read {addr:#x}+{size:#x} got {len(r.stdout)}")
        return r.stdout

    def u32(self, addr: int) -> int:
        return struct.unpack("<I", self.read(addr, 4))[0]

    def u64(self, addr: int) -> int:
        return struct.unpack("<Q", self.read(addr, 8))[0]


def find_base(adb: str, serial: str, pid: int) -> int:
    r = subprocess.run(
        [adb, "-s", serial, "shell", f"cat /proc/{pid}/maps"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, text=True,
    )
    starts = [int(l.split()[0].split("-")[0], 16) for l in r.stdout.splitlines()
              if len(l.split()) >= 6 and l.split()[5].endswith("libGameCore.so")]
    if not starts:
        raise RuntimeError("libGameCore.so not mapped")
    return min(starts)


class Channel:
    def __init__(self, reader: MemReader, obj_addr: int):
        self.reader = reader
        self.obj = obj_addr
        self.refresh()

    def refresh(self) -> None:
        f = self.reader.read(self.obj, 0x38)
        self.ring = struct.unpack_from("<Q", f, 0x08)[0]
        self.size = struct.unpack_from("<I", f, 0x10)[0]
        self.pending = struct.unpack_from("<I", f, 0x24)[0]
        self.write = struct.unpack_from("<I", f, 0x2C)[0]
        self.read = struct.unpack_from("<I", f, 0x30)[0]
        self.committed = struct.unpack_from("<I", f, 0x34)[0]

    def read_range(self, lo: int, hi: int) -> bytes:
        out = bytearray()
        pos = lo
        while pos != hi:
            off = pos & (self.size - 1)
            n = min(self.size - off, (hi - pos) & 0xFFFFFFFF)
            out += self.reader.read(self.ring + off, n)
            pos = (pos + n) & 0xFFFFFFFF
        return bytes(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adb", default="adb")
    ap.add_argument("--serial", default="127.0.0.1:16384")
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--interval", type=float, default=0.7)
    ap.add_argument("--duration", type=float, default=1800.0)
    ap.add_argument("--out", default="host/build/g5/cs_dual_run2.jsonl")
    args = ap.parse_args()

    reader = MemReader(args.adb, args.serial, args.pid)
    base = find_base(args.adb, args.serial, args.pid)
    tbl = reader.u64(base + 0x52488B8)
    print(f"base={base:#x} slot table={tbl:#x}", file=sys.stderr)

    chans = {}
    epochs = {}
    last_write = {}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    n = 0
    fh = out.open("a")
    try:
        while time.time() - t0 < args.duration:
            time.sleep(args.interval)
            try:
                tbl_now = reader.u64(base + 0x52488B8)
                for slot in (0, 1):
                    obj = reader.u64(tbl_now + slot * 8)
                    if not obj:
                        continue
                    if slot not in chans or chans[slot].obj != obj:
                        chans[slot] = Channel(reader, obj)
                        ch = chans[slot]
                        ch.refresh()
                        epochs.setdefault(slot, -1)
                        epochs[slot] += 1
                        # dump whatever is still in the ring right now so the
                        # init burst written before detection is not lost
                        lo = (ch.write - min(ch.size, ch.write)) & 0xFFFFFFFF
                        win = ch.read_range(lo, ch.write)
                        fh.write(json.dumps({
                            "t": round(time.time(), 3), "slot": slot,
                            "epoch": epochs[slot], "new_obj": obj,
                            "ring": ch.ring, "size": ch.size,
                            "win_from": lo, "win_hex": win.hex(),
                        }) + "\n")
                        fh.flush()
                        last_write[slot] = ch.write
                        print(f"new slot{slot} obj={obj:#x} epoch={epochs[slot]} "
                              f"init window {len(win)} B (write={ch.write:#x})",
                              file=sys.stderr)
                        continue
                    ch = chans[slot]
                    ch.refresh()
                    t = time.time()
                    t = time.time()
                    delta = (ch.write - last_write[slot]) & 0xFFFFFFFF
                    if delta > ch.size:
                        epochs[slot] += 1
                        fh.write(json.dumps({
                            "t": round(t, 3), "slot": slot, "epoch": epochs[slot],
                            "reset_from": last_write[slot], "reset_to": ch.write,
                        }) + "\n")
                        last_write[slot] = ch.write
                    elif delta > 0:
                        data = ch.read_range(last_write[slot], ch.write)
                        fh.write(json.dumps({
                            "t": round(t, 3), "slot": slot, "epoch": epochs[slot],
                            "write": ch.write, "from": last_write[slot],
                            "data": data.hex(),
                        }) + "\n")
                        last_write[slot] = ch.write
                    if slot == 0:
                        n += 1
                if n and n % 120 == 0:
                    s0 = chans.get(0)
                    s1 = chans.get(1)
                    print(f"t={time.time()-t0:6.1f} "
                          f"w0={s0.write:#x} " if s0 else "t=? ", file=sys.stderr)
                    if s0 and s1:
                        print(f"t={time.time()-t0:6.1f} w0={s0.write:#x} w1={s1.write:#x} "
                              f"epochs={dict(epochs)}", file=sys.stderr)
            except RuntimeError as e:
                print(f"read error: {e}", file=sys.stderr)
                time.sleep(1.0)
    finally:
        fh.close()
    print(f"done -> {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
