#!/usr/bin/env python3
"""Sample the live GameCore CS slot0 ring during replay playback (read-only).

Reads /proc/<pid>/mem through `adb exec-out dd` only. No attach, no writes,
no game function calls, no file writes on the device.

Slot0 chain (base-relative, verified against docs/cs_fifo_context.md and the
pid-2052 snapshot):
    [base+0x52488b8] = base+0x52c3250
    [base+0x52c3250] = slot0 ring object
    slot0: +0x08 ring base, +0x10 ring size (pow2), +0x24 pending,
           +0x2c write, +0x30 read, +0x34 committed   (cumulative u32 cursors)

Each poll reads only the NEW produced bytes [last_write, write): ring bytes
are not cleared by the consumer, so anything written since the previous poll
is still physically in the ring as long as production per interval < ring
size (replay ~4 KiB/s vs 64 KiB ring, polled at 1 s).  The JSONL rows are
{"t","write","from","data"} deltas; stitch_cs_stream.py concatenates them.

Usage:
  python host/scripts/sample_cs_stream.py --pid 2052 --interval 1.0 \
      --duration 1500 --out host/build/g5/cs_deltas.jsonl
  python host/scripts/sample_cs_stream.py --pid 2052 --once   # single probe
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
SLOT0_TABLE_SLOT = 0x52488B8   # -> base+0x52c3250
SLOT0_PTR_SLOT = 0x52C3250     # -> slot0 object


class MemReader:
    def __init__(self, adb: str, serial: str, pid: int):
        self.adb = adb
        self.serial = serial
        self.pid = pid
        self.calls = 0

    def read(self, addr: int, size: int) -> bytes:
        start_page = addr // PAGE
        end_page = (addr + size + PAGE - 1) // PAGE
        blocks = end_page - start_page
        remote = (
            f"dd if=/proc/{self.pid}/mem bs={PAGE} skip={start_page} count={blocks} "
            f"2>/dev/null | dd bs=1 skip={addr - start_page * PAGE} count={size} 2>/dev/null"
        )
        r = subprocess.run(
            [self.adb, "-s", self.serial, "exec-out", remote],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        self.calls += 1
        if len(r.stdout) != size:
            raise RuntimeError(
                f"read {addr:#x}+{size:#x}: got {len(r.stdout)} bytes rc={r.returncode} "
                f"{r.stderr.decode(errors='replace').strip()[:120]}"
            )
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
    starts = []
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 6 and parts[5].endswith("libGameCore.so"):
            starts.append(int(parts[0].split("-")[0], 16))
    if not starts:
        raise RuntimeError("libGameCore.so not mapped in target process")
    return min(starts)


class Slot0:
    """Resolved slot0 object; re-resolves cursors each poll (object may be
    re-created if the battle context changes)."""

    def __init__(self, reader: MemReader, base: int):
        self.reader = reader
        self.base = base
        self.resolve()

    def resolve(self) -> None:
        table = self.reader.u64(self.base + SLOT0_TABLE_SLOT)
        if table != self.base + 0x52C3250:
            raise RuntimeError(f"chain check failed: [0x52488b8]={table:#x}")
        slot0 = self.reader.u64(table)
        if slot0 == 0:
            raise RuntimeError("slot0 object is NULL (no battle context installed)")
        f = self.reader.read(slot0, 0x38)
        self.slot0 = slot0
        self.ring = struct.unpack_from("<Q", f, 0x08)[0]
        self.size = struct.unpack_from("<I", f, 0x10)[0]
        self.pending = struct.unpack_from("<I", f, 0x24)[0]
        self.write = struct.unpack_from("<I", f, 0x2C)[0]
        self.read = struct.unpack_from("<I", f, 0x30)[0]
        self.committed = struct.unpack_from("<I", f, 0x34)[0]

    def poll(self) -> dict:
        self.resolve()
        return {
            "slot0": self.slot0, "ring": self.ring, "size": self.size,
            "pending": self.pending, "write": self.write,
            "read": self.read, "committed": self.committed,
        }

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
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--duration", type=float, default=600.0)
    ap.add_argument("--out", default="host/build/g5/cs_deltas.jsonl")
    ap.add_argument("--once", action="store_true", help="single probe, print state")
    args = ap.parse_args()

    reader = MemReader(args.adb, args.serial, args.pid)
    base = find_base(args.adb, args.serial, args.pid)
    s0 = Slot0(reader, base)
    st = s0.poll()
    print(f"base={base:#x} slot0={st['slot0']:#x} ring={st['ring']:#x} size={st['size']:#x} "
          f"pending={st['pending']} cursors w/r/c = {st['write']:#x}/{st['read']:#x}/{st['committed']:#x}",
          file=sys.stderr)

    if args.once:
        backlog = s0.read_range(st["read"], st["committed"])
        print(f"backlog {len(backlog)} B: {backlog.hex()}")
        return 0

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    last_write = st["write"]
    last_size = st["size"]
    n_samples = 0
    holes = 0
    with out.open("a") as fh:
        while time.time() - t0 < args.duration:
            time.sleep(args.interval)
            try:
                st = s0.poll()
                t = time.time()
                delta = (st["write"] - last_write) & 0xFFFFFFFF
                if delta == 0:
                    continue
                if delta > last_size:
                    # window loss: impossible to recover skipped bytes
                    fh.write(json.dumps({"t": round(t, 3), "hole": delta,
                                         "from": last_write, "write": st["write"]}) + "\n")
                    holes += 1
                else:
                    data = s0.read_range(last_write, st["write"])
                    fh.write(json.dumps({
                        "t": round(t, 3), "write": st["write"],
                        "from": last_write, "data": data.hex(),
                        "committed": st["committed"], "read": st["read"],
                    }) + "\n")
                fh.flush()
                last_write = st["write"]
                last_size = st["size"]
                n_samples += 1
                if n_samples % 60 == 0:
                    print(f"t={t-t0:6.1f}s samples={n_samples} write={st['write']:#x} "
                          f"holes={holes}", file=sys.stderr)
            except RuntimeError as e:
                print(f"read error: {e}", file=sys.stderr)
                # game context may have been torn down; keep polling
                time.sleep(1.0)
    print(f"done: {n_samples} samples, {holes} holes -> {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
