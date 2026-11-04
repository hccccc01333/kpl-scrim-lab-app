#!/usr/bin/env python3
"""Find live instances of managed il2cpp classes by name and dump their fields.

Read-only /proc/<pid>/mem scan. Reuses the metadata/class-resolution approach
of tools/frapinfo_live_probe.py but parameterized by class name.

Usage:
  python host/scripts/find_managed_objects.py --pid 10833 \
      --class HeroData --class ActorData --max-scan-mb 1024
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
META_MARKER = "global-metadata"


class Reader:
    def __init__(self, adb: str, serial: str, pid: int):
        self.adb, self.serial, self.pid = adb, serial, pid

    MEGA = 0x100000

    def read(self, addr: int, size: int) -> bytes | None:
        # fast path: read whole 1 MiB blocks with one dd, slice locally
        page = addr & ~(self.MEGA - 1)
        inner = addr - page
        blocks = (inner + size + self.MEGA - 1) // self.MEGA
        remote = f"dd if=/proc/{self.pid}/mem bs={self.MEGA} skip={page // self.MEGA} count={blocks} 2>/dev/null"
        r = subprocess.run([self.adb, "-s", self.serial, "exec-out", remote],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        blob = r.stdout
        if len(blob) < inner + size:
            return None
        return blob[inner:inner + size]


def maps_of(adb: str, serial: str, pid: int) -> list[tuple[int, int, str, str]]:
    r = subprocess.run([adb, "-s", serial, "shell", f"cat /proc/{pid}/maps"],
                       capture_output=True, text=True, check=True)
    out = []
    for line in r.stdout.splitlines():
        m = re.match(r"([0-9a-f]+)-([0-9a-f]+) (\S+) \S+ \S+ \S+\s*(.*)", line)
        if m:
            out.append((int(m.group(1), 16), int(m.group(2), 16), m.group(3), m.group(4)))
    return out


def find_metadata_base(reader: Reader, maps) -> int | None:
    # named mapping first
    for s, e, perm, path in maps:
        if META_MARKER in path and "r" in perm:
            head = reader.read(s, 8)
            if head and struct.unpack_from("<I", head)[0] == 0xFAB11BAF:
                return s
    # anonymous rw regions: scan first 0x1000 of each for the magic
    for s, e, perm, path in maps:
        if "rw" in perm and not path:
            head = reader.read(s, 0x100)
            if head and struct.unpack_from("<I", head)[0] == 0xFAB11BAF:
                return s
    return None


def resolve_class(reader: Reader, maps, meta_base: int, name: str,
                  namespace: str | None = None, max_mb: int = 2048,
                  workers: int = 3, chunk_kb: int = 2048) -> dict | None:
    head = reader.read(meta_base, 0xA8)
    if not head:
        return None
    so, ss = struct.unpack_from("<II", head, 24)
    to, ts = struct.unpack_from("<II", head, 160)
    strings = reader.read(meta_base + so, ss)
    typedefs = reader.read(meta_base + to, ts)
    if not strings or not typedefs:
        return None

    def s_at(i):
        e = strings.find(b"\0", i)
        return strings[i:e].decode("utf-8", "replace")

    name_index = None
    ns_index = None
    for idx in range(len(typedefs) // 88):
        row = struct.unpack_from("<16i8H2I", typedefs, idx * 88)
        if s_at(row[0]) == name:
            ns = s_at(row[1])
            if namespace is None or ns == namespace:
                name_index, ns_index = row[0], row[1]
                break
    if name_index is None:
        return None
    name_addr = meta_base + so + name_index
    ns_addr = meta_base + so + ns_index
    needle = struct.pack("<Q", name_addr)
    hits = multi_needle_scan(reader, maps, {needle: name}, max_mb,
                             workers=workers, chunk_kb=chunk_kb)
    for cand_addr in hits.get(name, []):
        cand = cand_addr - 0x10
        klass = reader.read(cand, 0x20)
        if not klass:
            continue
        n_ptr = struct.unpack_from("<Q", klass, 0x10)[0]
        ns_ptr = struct.unpack_from("<Q", klass, 0x18)[0]
        if n_ptr == name_addr and (namespace is None or ns_ptr == ns_addr):
            return {"class": cand, "name_addr": name_addr}
    return None


def scan_instances(reader: Reader, maps, klass: int, max_mb: int) -> list[int]:
    needle = struct.pack("<Q", klass)
    found = []
    budget = max_mb * 1024 * 1024
    used = 0
    for s, e, perm, path in maps:
        if "w" not in perm or e - s > 0x40000000:
            continue
        size = e - s
        for off in range(0, size, 0x100000 - 8):
            if used >= budget:
                return found
            n = min(0x100000, size - off + 8)
            blob = reader.read(s + off, n)
            used += n
            if not blob:
                continue
            pos = 0
            while True:
                i = blob.find(needle, pos)
                if i < 0:
                    break
                found.append(s + off + i)
                pos = i + 8
    return found



def multi_needle_scan(reader: Reader, maps, needles: dict[bytes, str], max_mb: int,
                      workers: int = 3, chunk_kb: int = 2048) -> dict[str, list[int]]:
    """One pass over writable regions, matching all needles; parallel chunks."""
    from concurrent.futures import ThreadPoolExecutor
    found: dict[str, list[int]] = {name: [] for name in needles.values()}
    jobs = []
    budget = max_mb * 1024 * 1024
    used = 0
    for s, e, perm, path in maps:
        if "w" not in perm or e - s > 0x40000000 or e - s < 0x10000:
            continue
        size = e - s
        step = chunk_kb * 1024
        for off in range(0, size, step - 8):
            if used >= budget:
                break
            n = min(step, size - off + 8)
            jobs.append((s + off, n))
            used += n
        if used >= budget:
            break

    def work(job):
        addr, n = job
        blob = reader.read(addr, n)
        if not blob:
            return []
        hits = []
        for needle, name in needles.items():
            pos = 0
            while True:
                i = blob.find(needle, pos)
                if i < 0:
                    break
                hits.append((name, addr + i))
                pos = i + 8
        return hits

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for hits in ex.map(work, jobs):
            for name, addr in hits:
                found[name].append(addr)
    return found

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adb", default="adb")
    ap.add_argument("--serial", default="127.0.0.1:16384")
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--class-name", dest="class_names", action="append", default=[])
    ap.add_argument("--class-ptr", dest="class_ptrs", action="append", default=[],
                    help="NAME=HEX to skip live class resolution")
    ap.add_argument("--namespace", default=None)
    ap.add_argument("--max-scan-mb", type=int, default=1024)
    ap.add_argument("--region-filter", default="scudo")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--chunk-kb", type=int, default=2048)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    reader = Reader(args.adb, args.serial, args.pid)
    all_maps = maps_of(args.adb, args.serial, args.pid)
    maps = all_maps
    if args.region_filter == "anon":
        maps = [m for m in maps if not m[3] or m[3].startswith("[anon:")]
    elif args.region_filter == "scudo:primary":
        maps = [m for m in maps if "scudo:primary" in m[3]]
    elif args.region_filter:
        maps = [m for m in maps if args.region_filter in m[3]]
    meta_base = find_metadata_base(reader, all_maps)
    print("metadata base:", hex(meta_base) if meta_base else None, file=sys.stderr)
    if not meta_base:
        return 2

    known = {}
    for spec in args.class_ptrs:
        nm, _, hv = spec.partition("=")
        known[nm] = int(hv, 16)
    result = {}
    for cname in args.class_names:
        if cname in known:
            klass = {"class": known[cname], "name_addr": 0}
        else:
            klass = resolve_class(reader, all_maps, meta_base, cname, args.namespace,
                                  max_mb=args.max_scan_mb, workers=args.workers,
                                  chunk_kb=args.chunk_kb)
        print(f"{cname}: class = {hex(klass['class']) if klass else None}", file=sys.stderr)
        if not klass:
            continue
        insts = scan_instances(reader, maps, klass["class"], args.max_scan_mb)
        print(f"{cname}: {len(insts)} instances", file=sys.stderr)
        rows = []
        for addr in insts[:64]:
            raw = reader.read(addr, 0x80)
            if raw:
                rows.append({"addr": hex(addr), "raw": raw.hex()})
        result[cname] = {"class": hex(klass["class"]), "instances": rows}
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=1))
    else:
        print(json.dumps(result, indent=1)[:4000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
