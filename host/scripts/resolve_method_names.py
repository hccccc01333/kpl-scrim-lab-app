#!/usr/bin/env python3
"""Resolve managed method names for libil2cpp code VAs via the live process.

For each target code VA, scan libil2cpp's writable mappings for a qword equal
to the VA (MethodInfo.methodPointer), then read the MethodInfo name pointer
and decode the string from the live global-metadata mapping.  Read-only.

Usage:
  python host/scripts/resolve_method_names.py --pid 2052 --va 0x664cf7c [--va ...]
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import subprocess
import sys
from pathlib import Path

PAGE = 0x1000
CHUNK = 0x10000


class MemReader:
    def __init__(self, adb: str, serial: str, pid: int):
        self.adb, self.serial, self.pid = adb, serial, pid

    def read(self, addr: int, size: int) -> bytes:
        sp = addr // PAGE
        ep = (addr + size + PAGE - 1) // PAGE
        remote = (f"dd if=/proc/{self.pid}/mem bs={PAGE} skip={sp} count={ep-sp} "
                  f"2>/dev/null | dd bs=1 skip={addr - sp*PAGE} count={size} 2>/dev/null")
        r = subprocess.run([self.adb, "-s", self.serial, "exec-out", remote],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if len(r.stdout) != size:
            raise RuntimeError(f"read {addr:#x}+{size:#x} got {len(r.stdout)}")
        return r.stdout

    def maps(self) -> list[tuple[int, int, str, str]]:
        r = subprocess.run([self.adb, "-s", self.serial, "shell", f"cat /proc/{self.pid}/maps"],
                           capture_output=True, text=True, check=True)
        out = []
        for line in r.stdout.splitlines():
            m = re.match(r"([0-9a-f]+)-([0-9a-f]+) (\S+) \S+ \S+ \S+\s*(.*)", line)
            if m:
                out.append((int(m.group(1), 16), int(m.group(2), 16), m.group(3), m.group(4).strip()))
        return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adb", default="adb")
    ap.add_argument("--serial", default="127.0.0.1:16384")
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--va", action="append", required=True, help="libil2cpp VA (hex)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    reader = MemReader(args.adb, args.serial, args.pid)
    maps = reader.maps()
    il2cpp_rw = [(s, e, name) for s, e, perm, name in maps
                 if "libil2cpp.so" in name and "w" in perm]
    # metadata mapping (name contains global-metadata)
    meta_maps = [(s, e) for s, e, perm, name in maps if "global-metadata" in name]
    if not meta_maps:
        # metadata may be mapped anonymously after decryption; fall back to
        # scanning rw anon regions later if needed
        print("warning: no global-metadata mapping found", file=sys.stderr)
    print("il2cpp rw regions:", [(hex(s), hex(e)) for s, e, _ in il2cpp_rw], file=sys.stderr)

    targets = [int(v, 16) for v in args.va]
    found: dict[int, list[tuple[int, int]]] = {t: [] for t in targets}
    total = 0
    for s, e, _ in il2cpp_rw:
        size = e - s
        total += size
        for off in range(0, size, CHUNK - 8):
            n = min(CHUNK, size - off + 8)
            try:
                blob = reader.read(s + off, n)
            except RuntimeError:
                continue
            for t in targets:
                needle = struct.pack("<Q", t)
                pos = 0
                while True:
                    i = blob.find(needle, pos)
                    if i < 0:
                        break
                    found[t].append((s + off + i, i + off))
                    pos = i + 1
    print(f"scanned {total/1e6:.1f} MB of rw regions", file=sys.stderr)

    result = {}
    for t in targets:
        hits = found[t]
        print(f"\nVA {t:#x}: {len(hits)} pointer hits")
        for addr, _ in hits[:8]:
            try:
                st = reader.read(addr, 0x58)
                name_ptr = struct.unpack_from("<Q", st, 0x10)[0]
                klass_ptr = struct.unpack_from("<Q", st, 0x18)[0]
                name = None
                if name_ptr:
                    try:
                        raw = reader.read(name_ptr, 128)
                        cand = raw.split(b"\x00")[0]
                        if cand and all(32 <= b < 127 or b >= 0x80 for b in cand[:60]):
                            name = cand.decode("utf-8", "replace")
                    except RuntimeError:
                        name = None
                print(f"  MethodInfo@{addr:#x} name_ptr={name_ptr:#x} klass={klass_ptr:#x} name={name!r}")
                result.setdefault(hex(t), []).append({
                    "addr": hex(addr), "name_ptr": hex(name_ptr),
                    "klass": hex(klass_ptr), "name": name,
                })
            except RuntimeError as e:
                print(f"  {addr:#x}: read failed {e}")
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=1, ensure_ascii=False))
        print(f"saved {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
