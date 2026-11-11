#!/usr/bin/env python3
"""Read-only live probe for the client's frapInfo frame-command structure.

Why this tool exists
--------------------
`GameLogicHelper.AdvanceFrameCommands(frameNo, frapInfo)` receives a
CSDT_FRAPBOOT_INFO object whose live layout is (docs/advance_frame_binding.md):

    frapInfo + 0x00  Il2CppClass*  (8-byte object header on this build)
    frapInfo + 0x0c  u8            command count (1..27 while processing)
    frapInfo + 0x10  ptr           command container
    command  + 0x0c  u8            command type (1..27)
    command  + 0x10  ptr           payload / concrete command object

The object is allocated, filled and released inside
FrameWindow.HandleFraqBootInfo around the AdvanceFrameCommands call, so a
random heap snapshot usually cannot see it.  This tool therefore does three
things, all read-only:

1. resolves the live Il2CppClass* of CSDT_FRAPBOOT_INFO and FrameWindow from
   /proc/<pid>/maps metadata + /proc/<pid>/mem (no captured-address constants);
2. scans scudo / anonymous heap regions for (a) resident CSDT_FRAPBOOT_INFO
   instances and (b) class-agnostic frapInfo-shaped structs, with a score and
   explicit rejection reasons;
3. locates the live FrameWindow instance and samples its 900-slot packet ring,
   which is the persistent per-frame evidence left by the same code path.

Only an ADB root shell + `/proc/<pid>/mem` reads are used.  Nothing is
injected, no game function is called and no device file is written.  Heap bytes
stay in memory; the JSON written under data/ contains addresses, counts,
command type sequences and rejection counters only, never a heap dump.

Usage
-----
    python tools/frapinfo_live_probe.py --out data/replays/_analysis/.../frap_live
    python tools/frapinfo_live_probe.py --mode resolve
    python tools/frapinfo_live_probe.py --mode heap --max-scan-mb 1024
    python tools/frapinfo_live_probe.py --mode ring --samples 5
    python tools/frapinfo_live_probe.py --mode auto --abc <file>.abc

Exit codes: 0 = probe ran (findings may be negative), 2 = game/IL2CPP/metadata
unavailable, 3 = scan or metadata read failed.
"""
from __future__ import annotations

import argparse
import bisect
import json
import struct
import subprocess
import sys
import time
from collections import Counter, OrderedDict
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path

try:  # optional fast path; class and ring scans work without numpy
    import numpy as np
except ImportError:  # pragma: no cover - environment dependent
    np = None

ROOT = Path(__file__).resolve().parents[1]
ADB_DEFAULT = "D:/MuMuPlayer/nx_main/adb.exe"
SERIAL_DEFAULT = "127.0.0.1:16384"
PACKAGE_DEFAULT = "com.tencent.tmgp.sgame"
META_MARKER = "_$$global-metadata$$_"
METADATA_VERSION = 29
TYPE_DEF_SIZE = 88
FRAP_NAME = "CSDT_FRAPBOOT_INFO"
FRAP_NAMESPACE = "CSProtocol"
FRAME_WINDOW_NAME = "FrameWindow"
FRAME_WINDOW_NAMESPACE = "Assets.Scripts.Framework"
COMMAND_TYPES = range(1, 28)
MAX_COMMANDS = 27
MAX_ARRAY_LEN = 4096
MAX_FRAME_NO = 2_000_000
STATIC_STRIDES = (8, 12, 16, 20, 24, 28, 32, 36, 40, 44, 48, 52, 56, 60,
                  64, 72, 80, 96, 112, 128, 160, 192, 256)
# Two Il2CppArray header layouts are seen in this client: the compact 8-byte
# object header used by the protocol wrappers (+0x10 length, +0x18 elements)
# and the classic 16-byte header (+0x18 length, +0x20 elements).
ARRAY_LAYOUTS = ((0x10, 0x18, 4), (0x18, 0x20, 4), (0x18, 0x20, 8))


# ---------------------------------------------------------------------------
# ADB + process maps
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Mapping:
    start: int
    end: int
    perms: str
    offset: int
    path: str

    @property
    def size(self) -> int:
        return self.end - self.start


def parse_maps(text: str) -> list[Mapping]:
    rows: list[Mapping] = []
    for line in text.splitlines():
        parts = line.split(maxsplit=5)
        if len(parts) < 5:
            continue
        try:
            start, end = (int(x, 16) for x in parts[0].split("-"))
            offset = int(parts[2], 16)
        except ValueError:
            continue
        rows.append(Mapping(start, end, parts[1], offset,
                            parts[5].strip() if len(parts) > 5 else ""))
    return rows


class Adb:
    def __init__(self, exe: str, serial: str) -> None:
        self.exe = exe
        self.serial = serial

    def _run(self, *args: str, timeout: int = 60) -> bytes:
        try:
            proc = subprocess.run([self.exe, "-s", self.serial, *args],
                                  capture_output=True, timeout=timeout)
        except (subprocess.TimeoutExpired, OSError):
            return b""
        return proc.stdout

    def shell(self, *args: str, timeout: int = 30) -> bytes:
        return self._run("shell", *args, timeout=timeout)

    def pids(self, package: str) -> list[int]:
        raw = self.shell("pidof", package, timeout=15).decode("ascii", "replace")
        out = []
        for token in raw.split():
            try:
                out.append(int(token))
            except ValueError:
                pass
        return out

    def read_maps(self, pid: int) -> list[Mapping]:
        text = self.shell("cat", f"/proc/{pid}/maps", timeout=30).decode(
            "utf-8", "replace")
        return parse_maps(text)

    def read_mem(self, pid: int, addr: int, size: int,
                 timeout: int = 90) -> bytes | None:
        """Read exactly `size` bytes at `addr` through /proc/<pid>/mem."""
        if size <= 0:
            return b""
        page = addr & ~0xFFF
        pages = (addr - page + size + 0xFFF) // 0x1000
        cmd = (f"dd if=/proc/{pid}/mem bs=4096 skip={page // 4096} "
               f"count={pages} 2>/dev/null")
        raw = self._run("exec-out", cmd, timeout=timeout)
        if len(raw) != pages * 0x1000:
            return None
        off = addr - page
        return raw[off:off + size]


def find_pid(adb: Adb, package: str) -> tuple[int | None, str]:
    pids = adb.pids(package)
    if not pids:
        return None, "pidof returned no process"
    if len(pids) > 1:
        for pid in pids:
            maps = adb.read_maps(pid)
            if any("libil2cpp.so" in m.path for m in maps):
                return pid, f"pidof -> {pids}; selected {pid} (libil2cpp mapped)"
    maps = adb.read_maps(pids[0])
    note = "libil2cpp mapped" if any("libil2cpp.so" in m.path for m in maps) \
        else "no libil2cpp mapping in first pid"
    return pids[0], f"pidof -> {pids}; using {pids[0]} ({note})"


# ---------------------------------------------------------------------------
# Page reader with bounded cache
# ---------------------------------------------------------------------------
class Reader:
    def __init__(self, adb: Adb, pid: int, maps: list[Mapping],
                 cache_pages: int = 512) -> None:
        self.adb = adb
        self.pid = pid
        self.maps = maps
        self.cache_pages = cache_pages
        self._cache: OrderedDict[int, bytes | None] = OrderedDict()
        ranges = sorted((m.start, m.end) for m in maps if m.perms.startswith("r"))
        self.starts = [r[0] for r in ranges]
        self.ends = [r[1] for r in ranges]
        self.failures = 0

    def readable(self, addr: int, size: int = 1) -> bool:
        if addr < 0 or size < 0:
            return False
        idx = bisect.bisect_right(self.starts, addr) - 1
        return 0 <= idx < len(self.starts) and addr + size <= self.ends[idx]

    def region(self, addr: int) -> Mapping | None:
        for m in self.maps:
            if m.start <= addr < m.end:
                return m
        return None

    def page(self, page: int) -> bytes | None:
        if page in self._cache:
            self._cache.move_to_end(page)
            return self._cache[page]
        data = self.adb.read_mem(self.pid, page, 0x1000)
        if data is None:
            self.failures += 1
        self._cache[page] = data
        if len(self._cache) > self.cache_pages:
            self._cache.popitem(last=False)
        return data

    def read_bulk(self, addr: int, size: int) -> bytes | None:
        """One large dd read (metadata tables); bypasses the page cache."""
        if size <= 0:
            return b""
        if not self.readable(addr, size):
            return None
        return self.adb.read_mem(self.pid, addr, size, timeout=180)

    def read(self, addr: int, size: int) -> bytes | None:
        if size <= 0:
            return b""
        if not self.readable(addr, size):
            return None
        out = bytearray()
        while size > 0:
            page = addr & ~0xFFF
            off = addr - page
            take = min(0x1000 - off, size)
            data = self.page(page)
            if data is None:
                return None
            out += data[off:off + take]
            addr += take
            size -= take
        return bytes(out)

    def u8(self, addr: int) -> int | None:
        raw = self.read(addr, 1)
        return raw[0] if raw else None

    def u16(self, addr: int) -> int | None:
        raw = self.read(addr, 2)
        return struct.unpack("<H", raw)[0] if raw else None

    def u32(self, addr: int) -> int | None:
        raw = self.read(addr, 4)
        return struct.unpack("<I", raw)[0] if raw else None

    def u64(self, addr: int) -> int | None:
        raw = self.read(addr, 8)
        return struct.unpack("<Q", raw)[0] if raw else None

    def cstring(self, addr: int, limit: int = 96) -> str | None:
        raw = self.read(addr, limit)
        if raw is None:
            return None
        return raw.split(b"\0", 1)[0].decode("utf-8", "replace")


class ChunkView:
    """In-buffer reader for one scanned chunk (no extra device reads)."""

    def __init__(self, base: int, data: bytes) -> None:
        self.base = base
        self.data = data

    def read(self, addr: int, size: int) -> bytes | None:
        off = addr - self.base
        if off < 0 or off + size > len(self.data):
            return None
        return self.data[off:off + size]

    def u8(self, addr: int) -> int | None:
        raw = self.read(addr, 1)
        return raw[0] if raw else None

    def u32(self, addr: int) -> int | None:
        raw = self.read(addr, 4)
        return struct.unpack("<I", raw)[0] if raw else None

    def u64(self, addr: int) -> int | None:
        raw = self.read(addr, 8)
        return struct.unpack("<Q", raw)[0] if raw else None


class Source:
    """Read from the local chunk first, then through the paged device reader."""

    def __init__(self, reader: Reader, chunk: ChunkView | None = None) -> None:
        self.reader = reader
        self.chunk = chunk
        self.remote_reads = 0

    def read(self, addr: int, size: int) -> bytes | None:
        if self.chunk is not None:
            raw = self.chunk.read(addr, size)
            if raw is not None:
                return raw
        self.remote_reads += 1
        return self.reader.read(addr, size)

    def u8(self, addr: int) -> int | None:
        raw = self.read(addr, 1)
        return raw[0] if raw else None

    def u32(self, addr: int) -> int | None:
        raw = self.read(addr, 4)
        return struct.unpack("<I", raw)[0] if raw else None

    def u64(self, addr: int) -> int | None:
        raw = self.read(addr, 8)
        return struct.unpack("<Q", raw)[0] if raw else None


# ---------------------------------------------------------------------------
# Region selection and chunked scanning
# ---------------------------------------------------------------------------
def region_kind(m: Mapping) -> str | None:
    if m.perms != "rw-p":
        return None
    path = m.path
    if "scudo:primary" in path:
        return "scudo_primary"
    if "scudo:secondary" in path:
        return "scudo_secondary"
    if path == "":
        return "anonymous"
    if path.startswith("[anon:Mem_"):
        return "unity_mem"
    return None


def regions_of_kind(maps: list[Mapping], kind: str,
                    budget_bytes: int = 0) -> list[tuple[int, int, str]]:
    out = []
    total = 0
    for m in sorted((m for m in maps if region_kind(m) == kind),
                    key=lambda x: -x.size):
        if budget_bytes and total >= budget_bytes:
            break
        end = m.end
        if budget_bytes:
            end = min(end, m.start + (budget_bytes - total))
        if end <= m.start:
            break
        out.append((m.start, end, kind))
        total += end - m.start
    return out


def select_heap_regions(maps: list[Mapping], budget_bytes: int,
                        min_region: int = 64 * 1024) -> list[tuple[int, int, str]]:
    """Pick scudo + anonymous GC + Unity regions, biggest-first per kind."""
    priority = {"scudo_primary": 0, "anonymous": 1, "scudo_secondary": 2,
                "unity_mem": 3}
    picked: list[tuple[int, int, str]] = []
    total = 0
    buckets: dict[str, list[Mapping]] = {k: [] for k in priority}
    for m in maps:
        kind = region_kind(m)
        if kind is None or m.size < min_region:
            continue
        buckets[kind].append(m)
    for kind in sorted(priority, key=priority.get):
        for m in sorted(buckets[kind], key=lambda x: -x.size):
            if budget_bytes and total >= budget_bytes:
                break
            end = m.end
            if budget_bytes:
                remaining = budget_bytes - total
                if remaining < min_region:
                    break
                end = min(end, m.start + remaining)
            picked.append((m.start, end, kind))
            total += end - m.start
    return picked


def iter_chunks(regions: list[tuple[int, int, str]], chunk: int):
    for start, end, kind in regions:
        a = start
        while a < end:
            b = min(a + chunk, end)
            yield a, b, kind
            a = b


def scan_chunks(adb: Adb, pid: int, chunks, workers: int, budget_bytes: int,
                on_chunk, label: str) -> dict:
    """Read chunks with a bounded worker window and feed on_chunk(base, data)."""
    stats = Counter()
    bytes_read = 0
    started = time.time()
    tasks = iter(chunks)
    pool = ThreadPoolExecutor(max_workers=max(1, workers))
    outstanding: dict = {}

    def submit_next() -> None:
        while len(outstanding) < max(1, workers) * 2:
            if budget_bytes and bytes_read >= budget_bytes:
                return
            try:
                a, b, _kind = next(tasks)
            except StopIteration:
                return
            future = pool.submit(adb.read_mem, pid, a, b - a)
            outstanding[future] = a

    submit_next()
    try:
        while outstanding:
            done, _ = wait(set(outstanding), return_when=FIRST_COMPLETED)
            for future in done:
                base = outstanding.pop(future)
                try:
                    data = future.result()
                except Exception:  # noqa: BLE001 - device reads can fail
                    data = None
                if not data:
                    stats["chunks_failed"] += 1
                    continue
                bytes_read += len(data)
                stats["chunks_ok"] += 1
                on_chunk(base, data)
            submit_next()
            if stats["chunks_ok"] and stats["chunks_ok"] % 64 == 0:
                print(f"  {label}: {stats['chunks_ok']} chunks, "
                      f"{bytes_read / 1048576:.0f} MiB, "
                      f"{time.time() - started:.1f}s", flush=True)
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    stats["bytes_read"] = bytes_read
    stats["seconds"] = round(time.time() - started, 1)
    return dict(stats)


# ---------------------------------------------------------------------------
# Metadata + class resolution
# ---------------------------------------------------------------------------
def find_metadata(maps: list[Mapping]) -> list[Mapping]:
    return [m for m in maps if META_MARKER in m.path and m.perms.startswith("r")]


def read_metadata_header(reader: Reader, base: int) -> dict | None:
    raw = reader.read(base, 0xA8)
    if raw is None or len(raw) < 0xA8:
        return None
    magic, version = struct.unpack_from("<Ii", raw, 0)
    if magic != 0xFAB11BAF or version != METADATA_VERSION:
        return None
    so, ss = struct.unpack_from("<II", raw, 24)
    to, ts = struct.unpack_from("<II", raw, 160)
    return {"base": base, "version": version, "string_offset": so,
            "string_size": ss, "typedef_offset": to, "typedef_size": ts}


def read_metadata_tables(reader: Reader, meta: Mapping,
                         header: dict) -> tuple[bytes | None, bytes | None, str | None]:
    base = header["base"]
    if base != meta.start:
        return None, None, "metadata header does not start at the mapping base"
    if header["string_offset"] + header["string_size"] > meta.size:
        return None, None, "metadata string table outside mapping"
    if header["typedef_offset"] + header["typedef_size"] > meta.size:
        return None, None, "metadata type table outside mapping"
    strings = reader.read_bulk(base + header["string_offset"], header["string_size"])
    typedefs = reader.read_bulk(base + header["typedef_offset"], header["typedef_size"])
    if strings is None:
        return None, None, "metadata string table unreadable"
    if typedefs is None:
        return None, None, "metadata type table unreadable"
    return strings, typedefs, None


def meta_string(strings: bytes, index: int) -> str | None:
    if index < 0 or index >= len(strings):
        return None
    end = strings.find(b"\0", index)
    if end < 0:
        return None
    return strings[index:end].decode("utf-8", "replace")


def find_type_indices(strings: bytes, typedefs: bytes, name: str,
                      namespace: str) -> tuple[int, int] | None:
    limit = len(typedefs) // TYPE_DEF_SIZE
    for idx in range(limit):
        row = struct.unpack_from("<16i8H2I", typedefs, idx * TYPE_DEF_SIZE)
        if meta_string(strings, row[0]) != name:
            continue
        if meta_string(strings, row[1]) != namespace:
            continue
        return row[0], row[1]
    return None


def resolve_classes(adb: Adb, pid: int, maps: list[Mapping], reader: Reader,
                    targets: list[tuple[str, str]], workers: int, chunk: int,
                    resolve_mb: int) -> tuple[dict, dict, list[str]]:
    """Resolve live Il2CppClass* pointers using metadata name/namespace strings."""
    errors: list[str] = []
    meta_maps = find_metadata(maps)
    if not meta_maps:
        return {}, {"error": "no global-metadata mapping"}, ["no global-metadata mapping"]
    meta = None
    header = None
    for candidate in meta_maps:
        header = read_metadata_header(reader, candidate.start)
        if header:
            meta = candidate
            break
    if not meta or not header:
        return {}, {"error": "metadata header missing/invalid"}, errors + [
            "metadata header missing (expected magic 0xFAB11BAF, version 29)"]
    strings, typedefs, err = read_metadata_tables(reader, meta, header)
    if err or strings is None or typedefs is None:
        return {}, {"error": err or "metadata unreadable"}, errors + [err or "metadata unreadable"]

    needles: dict[bytes, tuple[str, str, int, int]] = {}
    resolved_meta: dict[str, dict] = {}
    for name, namespace in targets:
        found = find_type_indices(strings, typedefs, name, namespace)
        if not found:
            errors.append(f"type {namespace}.{name} not found in metadata")
            continue
        name_idx, ns_idx = found
        name_addr = header["base"] + header["string_offset"] + name_idx
        ns_addr = header["base"] + header["string_offset"] + ns_idx
        needles[struct.pack("<Q", name_addr)] = (name, namespace, name_addr, ns_addr)
        resolved_meta[name] = {
            "name": name, "namespace": namespace,
            "metadata_base": header["base"],
            "name_string": name_addr, "namespace_string": ns_addr,
            "name_index": name_idx, "namespace_index": ns_idx,
        }
    if not needles:
        return {}, {"error": "no resolvable targets"}, errors

    primary = regions_of_kind(maps, "scudo_primary")
    hits: dict[str, list[dict]] = {name: [] for name, _ in targets}
    budget = resolve_mb * 1048576 if resolve_mb > 0 else 0

    def on_chunk(base: int, data: bytes) -> None:
        for needle, (name, namespace, name_addr, ns_addr) in needles.items():
            pos = 0
            while True:
                pos = data.find(needle, pos)
                if pos < 0:
                    break
                addr = base + pos
                pos += 1
                if addr % 8:
                    continue
                start = addr - 0x10
                if start < 0 or start % 8:
                    continue
                if reader.u64(start + 0x10) != name_addr:
                    continue
                if reader.u64(start + 0x18) != ns_addr:
                    continue
                if reader.cstring(name_addr, len(name) + 8) != name:
                    continue
                region = reader.region(start)
                if region is None or region_kind(region) not in (
                        "scudo_primary", "scudo_secondary"):
                    continue
                if any(h["class"] == start for h in hits[name]):
                    continue
                hits[name].append({
                    "class": start,
                    "verified_name": reader.cstring(name_addr, len(name) + 8),
                    "verified_namespace": reader.cstring(ns_addr, len(namespace) + 8),
                    "image": reader.u64(start),
                })

    print(f"resolve: scanning {sum(e - s for s, e, _ in primary) / 1048576:.0f} MiB "
          f"of scudo primary for name strings", flush=True)
    scan_stats = scan_chunks(adb, pid, iter_chunks(primary, chunk), workers,
                             budget, on_chunk, "resolve")
    missing = [name for name, _ in targets if not hits.get(name)]
    secondary_stats = None
    if missing:
        secondary = regions_of_kind(maps, "scudo_secondary")
        remaining = budget - scan_stats.get("bytes_read", 0) if budget else 0
        if secondary and (not budget or remaining > 0):
            print(f"resolve: {len(missing)} class(es) missing; scanning "
                  f"{sum(e - s for s, e, _ in secondary) / 1048576:.0f} MiB "
                  f"of scudo secondary", flush=True)
            secondary_stats = scan_chunks(adb, pid, iter_chunks(secondary, chunk),
                                          workers, remaining, on_chunk,
                                          "resolve-secondary")

    resolved: dict[str, dict] = {}
    for name, _namespace in targets:
        if hits.get(name):
            best = hits[name][0]
            resolved[name] = {**resolved_meta[name], **best,
                              "candidates": hits[name][:8]}
        elif name in resolved_meta:
            errors.append(f"class {name}: name string found in metadata but no "
                          f"verified Il2CppClass in scudo primary/secondary")
    return resolved, {"meta": resolved_meta, "scan": scan_stats,
                      "scan_secondary": secondary_stats,
                      "metadata_mapping": {
                          "start": meta.start, "end": meta.end, "path": meta.path,
                          "header": header}}, errors


# ---------------------------------------------------------------------------
# Candidate validation
# ---------------------------------------------------------------------------
def check_commands(src: Source, elems: int, count: int, stride: int,
                   pointer_array: bool) -> tuple[list[int], list[int], int] | None:
    types: list[int] = []
    payloads: list[int] = []
    nulls = 0
    for i in range(count):
        slot = elems + i * (8 if pointer_array else stride)
        if pointer_array:
            base = src.u64(slot)
            if not base or base % 8 or not src.reader.readable(base, 0x18):
                return None
        else:
            base = slot
            if not src.reader.readable(base, 0x18):
                return None
        ctype = src.u8(base + 0xC)
        payload = src.u64(base + 0x10)
        if ctype is None or ctype not in COMMAND_TYPES:
            return None
        if payload and not src.reader.readable(payload, 8):
            return None
        if not payload:
            nulls += 1
        types.append(ctype)
        payloads.append(payload or 0)
    return types, payloads, nulls


def validate_candidate(addr: int, count: int, src: Source,
                       scudo_ranges: list[tuple[int, int]],
                       frap_class: int | None = None) -> tuple[dict | None, str]:
    """Validate one frapInfo-shaped address.  Returns (candidate, reason)."""
    if not 1 <= count <= MAX_COMMANDS:
        return None, "count_out_of_range"
    klass = src.u64(addr)
    if not klass:
        return None, "klass_null"
    array = src.u64(addr + 0x10)
    if not array or array % 8:
        return None, "array_pointer_invalid"
    if not src.reader.readable(array, 8):
        return None, "array_unreadable"
    array_klass = src.u64(array)
    if not array_klass or not src.reader.readable(array_klass, 0x20):
        return None, "array_klass_unreadable"
    if not in_ranges_py(array_klass, scudo_ranges):
        return None, "array_klass_outside_scudo"

    layouts = []
    for len_off, elem_off, len_size in ARRAY_LAYOUTS:
        length = src.u32(array + len_off) if len_size == 4 else src.u64(array + len_off)
        if length is None or not (count <= length <= MAX_ARRAY_LEN):
            continue
        found = []
        result = check_commands(src, array + elem_off, count, 8, True)
        if result:
            kinds, payloads, nulls = result
            found.append({"kind": "pointer_array", "stride": 8, "length": length,
                          "types": kinds, "payloads": payloads, "null_payloads": nulls})
        for stride in STATIC_STRIDES:
            result = check_commands(src, array + elem_off, count, stride, False)
            if not result:
                continue
            kinds, payloads, nulls = result
            found.append({"kind": "inline", "stride": stride, "length": length,
                          "types": kinds, "payloads": payloads,
                          "null_payloads": nulls})
        layouts.extend(found)
    if not layouts:
        return None, "command_chain_invalid"

    def score(item: dict) -> int:
        value = 10 * count
        if item["length"] == count:
            value += 8
        if item["stride"] % 8 == 0:
            value += 5
        value += 3 * (count - item["null_payloads"])
        if item["kind"] == "pointer_array":
            value += 2
        if frap_class is not None and klass == frap_class:
            value += 40
        if in_ranges_py(klass, scudo_ranges):
            value += 4
        return value

    best = max(layouts, key=score)
    best.update({
        "addr": addr,
        "count": count,
        "klass": klass,
        "klass_name": class_name(src.reader, klass),
        "array": array,
        "array_klass": array_klass,
        "array_klass_name": class_name(src.reader, array_klass),
        "field_08": src.u32(addr + 8),
        "score": score(best),
        "remote_reads": src.remote_reads,
    })
    return best, "accepted"


def plausible_empty_object(reader: Reader, addr: int,
                           scudo: list[tuple[int, int]]) -> bool:
    """A released CSDT object must still hold a command-array reference.

    Count is zeroed by OnRelease, so the array header/class is the only
    structural evidence left.  False hits in type tables have array pointers
    that are not FRAME_CMD_INFO[] arrays.
    """
    array = reader.u64(addr + 0x10)
    if not array or not reader.readable(array, 8):
        return False
    array_klass = reader.u64(array)
    if not array_klass or not reader.readable(array_klass, 0x20):
        return False
    if not in_ranges_py(array_klass, scudo):
        return False
    name = class_name(reader, array_klass) or ""
    if "FRAME_CMD" not in name:
        return False
    for len_off, _elem_off, len_size in ARRAY_LAYOUTS:
        length = reader.u32(array + len_off) if len_size == 4 else \
            reader.u64(array + len_off)
        if length is not None and 0 <= length <= MAX_ARRAY_LEN:
            return True
    return False


def class_name(reader: Reader, klass: int | None) -> str | None:
    if not klass:
        return None
    name_ptr = reader.u64(klass + 0x10)
    if not name_ptr:
        return None
    return reader.cstring(name_ptr, 96)


def in_ranges_py(value: int, ranges: list[tuple[int, int]]) -> bool:
    for start, end in ranges:
        if start <= value < end:
            return True
    return False


def scudo_ranges(maps: list[Mapping]) -> list[tuple[int, int]]:
    return [(m.start, m.end) for m in maps
            if m.perms == "rw-p" and "scudo:" in m.path]


# ---------------------------------------------------------------------------
# Heap scan: class anchors + class-agnostic signature
# ---------------------------------------------------------------------------
def range_index(ranges: list[tuple[int, int]]):
    ordered = sorted(ranges)
    starts = np.array([r[0] for r in ordered], dtype=np.uint64)
    ends = np.array([r[1] for r in ordered], dtype=np.uint64)
    return starts, ends


def in_ranges_np(values, starts, ends):
    if len(starts) == 0:
        return np.zeros(len(values), dtype=bool)
    idx = np.searchsorted(starts, values, side="right") - 1
    safe = np.clip(idx, 0, len(ends) - 1)
    return (idx >= 0) & (values >= starts[safe]) & (values < ends[safe])


def signature_candidates(base: int, data: bytes,
                         scudo_idx, heap_idx,
                         max_per_chunk: int) -> list[tuple[int, int]]:
    if np is None:
        return []
    n = len(data)
    m = (n - 24) // 8
    if m <= 0:
        return []
    klass = np.frombuffer(data, dtype="<u8", count=m, offset=0)
    counts = np.frombuffer(data, dtype=np.uint8, count=m, offset=12)
    arrays = np.frombuffer(data, dtype="<u8", count=m, offset=16)
    # +0x08 is not proven to be a frame number for CSDT_FRAPBOOT_INFO; it is
    # recorded as field_08 during validation instead of being a hard filter.
    mask = ((counts >= 2) & (counts <= MAX_COMMANDS)
            & ((arrays & 7) == 0) & (arrays != 0) & (klass != 0))
    mask &= in_ranges_np(klass, *scudo_idx)
    mask &= in_ranges_np(arrays, *heap_idx)
    idx = np.nonzero(mask)[0]
    if len(idx) > max_per_chunk:
        idx = idx[:max_per_chunk]
    return [(base + int(i) * 8, int(counts[i])) for i in idx]


def heap_scan(adb: Adb, pid: int, maps: list[Mapping], reader: Reader,
              regions: list[tuple[int, int, str]], class_pointers: dict[str, int],
              workers: int, chunk: int, max_mb: int,
              signature: bool, max_per_chunk: int,
              max_validations: int) -> dict:
    budget = max_mb * 1048576 if max_mb > 0 else 0
    scudo = scudo_ranges(maps)
    scudo_idx = range_index(scudo)
    heap_idx = range_index([(s, e) for s, e, _ in regions])
    class_needles = {struct.pack("<Q", ptr): name
                     for name, ptr in class_pointers.items() if ptr}
    class_hits: dict[str, list[int]] = {name: [] for name in class_pointers}
    raw_signatures = 0
    validations = 0
    validated: list[dict] = []
    rejected = Counter()
    reject_examples: dict[str, list[str]] = {}
    skipped = 0

    def on_chunk(base: int, data: bytes) -> None:
        nonlocal raw_signatures, validations, skipped
        view = ChunkView(base, data)
        for needle, name in class_needles.items():
            pos = 0
            while True:
                pos = data.find(needle, pos)
                if pos < 0:
                    break
                addr = base + pos
                pos += 1
                if addr % 8 == 0 and addr not in class_hits[name]:
                    class_hits[name].append(addr)
        if not signature:
            return
        for addr, count in signature_candidates(base, data, scudo_idx,
                                                heap_idx, max_per_chunk):
            raw_signatures += 1
            if validations >= max_validations:
                skipped += 1
                continue
            validations += 1
            src = Source(reader, view)
            candidate, reason = validate_candidate(
                addr, count, src, scudo,
                class_pointers.get(FRAP_NAME))
            if candidate:
                validated.append(candidate)
            else:
                rejected[reason] += 1
                examples = reject_examples.setdefault(reason, [])
                if len(examples) < 6:
                    examples.append(hex(addr))

    stats = scan_chunks(adb, pid, iter_chunks(regions, chunk), workers,
                        budget, on_chunk, "heap")
    return {
        "regions": len(regions),
        "scan_bytes": stats.get("bytes_read", 0),
        "scan_seconds": stats.get("seconds"),
        "chunks_ok": stats.get("chunks_ok"),
        "chunks_failed": stats.get("chunks_failed"),
        "class_pointer_hits": {name: [hex(a) for a in hits[:32]]
                               for name, hits in class_hits.items()},
        "class_pointer_hit_counts": {name: len(hits)
                                     for name, hits in class_hits.items()},
        "signature_enabled": signature,
        "signature_raw_candidates": raw_signatures,
        "signature_validations": validations,
        "signature_skipped_over_limit": skipped,
        "signature_validated": sorted(validated,
                                      key=lambda c: -c["score"])[:20],
        "signature_rejected_reasons": dict(rejected),
        "signature_reject_examples": reject_examples,
        "_class_hits": class_hits,
        "_validated": validated,
    }


# ---------------------------------------------------------------------------
# FrameWindow packet-ring anchor
# ---------------------------------------------------------------------------
def ring_state(reader: Reader, addr: int) -> dict | None:
    ring = reader.u64(addr + 8)
    if not ring or not reader.readable(ring, 0x20):
        return None
    length = reader.u32(ring + 0x10)
    if length is None or not 1 <= length <= 4096:
        return None
    current = reader.u32(addr + 0x14)
    base = reader.u32(addr + 0x10)
    max_seen = reader.u32(addr + 0x18)
    nonnull = 0
    packets = []
    for i in range(min(length, 64)):
        packet = reader.u64(ring + 0x18 + 8 * i)
        if packet:
            nonnull += 1
            packets.append((i, packet))
    score = (2 if length == 900 else 0) + min(nonnull, 40)
    score += 10 if (current or 0) > 0 else 0
    score += 5 if (max_seen or 0) > 0 else 0
    return {"addr": addr, "ring": ring, "length": length, "current": current,
            "base": base, "max_seen": max_seen, "nonnull_first64": nonnull,
            "sample_packets": packets, "score": score}


def decode_packet(payload: bytes) -> dict:
    """Decode a FRAPBOOT payload with the repo's TDR frame-command decoder."""
    try:
        sys.path.insert(0, str(ROOT))
        from tools.replay_frame_commands import decode_commands  # noqa: WPS433
    except Exception as exc:  # noqa: BLE001
        return {"error": f"decoder unavailable: {exc}"}
    try:
        entries = decode_commands(payload)
        return {"count": len(entries),
                "names": [e.get("name") or f"sel{e.get('boot_type')}"
                          for e in entries],
                "selectors": [e.get("boot_type") for e in entries]}
    except Exception as exc:  # noqa: BLE001 - strict decoder rejects unknown frames
        return {"error": str(exc)[:160],
                "first_count": payload[0] if payload else None,
                "first_bytes": payload[:16].hex()}


def probe_ring(reader: Reader, instances: list[dict], samples: int,
               interval: float, max_packets: int) -> dict:
    best = None
    for item in instances:
        state = ring_state(reader, item["addr"])
        if state is None:
            continue
        if best is None or state["score"] > best["score"]:
            best = state
    if best is None:
        return {"found": False, "instance_found": False, "active": False,
                "reason": "no FrameWindow instance with a readable 1..4096-slot ring",
                "instances": [hex(i["addr"]) for i in instances[:8]]}

    sample_rows = []
    for _ in range(max(1, samples)):
        state = ring_state(reader, best["addr"])
        if state is None:
            break
        ring = state["ring"]
        length = state["length"]
        packets = []
        # The ring is filled around (current - base) % length; read both the
        # newest slots and the first non-null slots without walking all 900
        # packets (bounded read-only work).
        start = 0
        if state["current"] is not None and state["base"] is not None:
            start = (state["current"] - state["base"]) % max(1, length)
        slots = list(range(start, min(start + max_packets, length)))
        slots += list(range(0, min(max_packets, length)))
        seen = set()
        for i in slots:
            if i in seen:
                continue
            seen.add(i)
            packet = reader.u64(ring + 0x18 + 8 * i)
            if not packet:
                continue
            frame = reader.u32(packet + 0xC)
            plen = reader.u16(packet + 0x10)
            payload = reader.read(packet + 0x18, min(plen or 0, 512)) if plen else b""
            entry = {"slot": i, "packet": hex(packet), "frame": frame,
                     "payload_len": plen, "payload_bytes": len(payload or b"")}
            if payload:
                entry["decode"] = decode_packet(payload)
            packets.append(entry)
            if len(packets) >= max_packets:
                break
        sample_rows.append({
            "current": state["current"], "base": state["base"],
            "max_seen": state["max_seen"], "length": length,
            "packets": packets,
        })
        time.sleep(max(0.0, interval))

    frames = [p["frame"] for row in sample_rows for p in row["packets"]
              if isinstance(p.get("frame"), int)]
    has_packets = any(row["packets"] for row in sample_rows)
    return {"found": has_packets, "instance_found": True, "active": has_packets,
            "instance": best, "samples": sample_rows,
            "reason": None if has_packets else
            "ring instance found but the sampled slots contain no packets "
            "(replay may use the batch path, not HandleFraqBootSingle)",
            "observed_frames": {"min": min(frames) if frames else None,
                                "max": max(frames) if frames else None,
                                "distinct": len(set(frames))}}


# ---------------------------------------------------------------------------
# Optional .abc comparison
# ---------------------------------------------------------------------------
def load_abc_frames(path: Path) -> tuple[dict | None, str | None]:
    try:
        sys.path.insert(0, str(ROOT))
        from tools.replay_frame_commands import decode_commands  # noqa: WPS433
        from tools.replay_record_stream import iter_records  # noqa: WPS433
    except Exception as exc:  # noqa: BLE001
        return None, f"abc decoder unavailable: {exc}"
    try:
        data = path.read_bytes()
    except OSError as exc:
        return None, f"abc unreadable: {exc}"
    frames: dict[int, dict] = {}
    for record in iter_records(data):
        if record.get("kind") != "frame":
            continue
        try:
            entries = decode_commands(data[record["command_offset"]:record["end"]])
        except ValueError:
            continue
        frames[record["sequence"]] = {
            "count": len(entries),
            "names": [e.get("name") or f"sel{e.get('boot_type')}"
                      for e in entries],
        }
    return frames, None


def compare_abc(ring_result: dict, frames: dict) -> dict:
    matches = 0
    compared = 0
    rows = []
    for sample in ring_result.get("samples", []):
        for packet in sample.get("packets", []):
            frame = packet.get("frame")
            if not isinstance(frame, int) or frame not in frames:
                continue
            decoded = packet.get("decode", {})
            live_names = decoded.get("names")
            if live_names is None:
                continue
            expected = frames[frame]
            compared += 1
            exact = (live_names == expected["names"])
            matches += 1 if exact else 0
            if len(rows) < 32:
                rows.append({"frame": frame, "live_count": len(live_names),
                             "abc_count": expected["count"], "exact": exact,
                             "live_names": live_names[:12],
                             "abc_names": expected["names"][:12]})
    return {"compared_packets": compared, "exact_matches": matches,
            "match_rate": round(matches / compared, 3) if compared else None,
            "rows": rows}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def default_out() -> Path:
    day = time.strftime("%Y%m%d")
    stamp = time.strftime("%H%M%S")
    return (ROOT / "data" / "replays" / "_analysis" / f"client_probe_{day}"
            / f"frapinfo_live_{stamp}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--adb", default=ADB_DEFAULT)
    parser.add_argument("--serial", default=SERIAL_DEFAULT)
    parser.add_argument("--package", default=PACKAGE_DEFAULT)
    parser.add_argument("--pid", type=int, default=None)
    parser.add_argument("--out", type=Path, default=None,
                        help="New capture directory inside data/ (default: timestamped)")
    parser.add_argument("--mode", choices=("auto", "resolve", "heap", "ring",
                                           "signature"), default="auto")
    parser.add_argument("--max-scan-mb", type=int, default=1024,
                        help="Heap read budget for heap/ring scans; 0 = unlimited")
    parser.add_argument("--resolve-scan-mb", type=int, default=512,
                        help="Budget for the scudo-primary class-resolution scan")
    parser.add_argument("--chunk-kb", type=int, default=4096)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--no-signature", action="store_true",
                        help="Skip the class-agnostic signature scan")
    parser.add_argument("--max-per-chunk", type=int, default=256)
    parser.add_argument("--max-validations", type=int, default=1024)
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--sample-interval", type=float, default=0.8)
    parser.add_argument("--max-packets", type=int, default=32)
    parser.add_argument("--abc", type=Path, default=None,
                        help="Optional .abc file for a preliminary frame comparison")
    args = parser.parse_args()

    if args.chunk_kb < 64:
        parser.error("--chunk-kb must be >= 64")
    if args.workers < 1 or args.workers > 8:
        parser.error("--workers must be 1..8")
    out = (args.out or default_out()).resolve()
    data_root = (ROOT / "data").resolve()
    if data_root not in out.parents:
        parser.error("--out must be inside project data/")
    if out.exists() and any(out.iterdir()):
        parser.error("--out must be a new or empty directory; captures are preserved")

    adb = Adb(args.adb, args.serial)
    pid = args.pid
    pid_note = "explicit --pid"
    if pid is None:
        pid, pid_note = find_pid(adb, args.package)
    if pid is None:
        print(json.dumps({"status": "error", "pid_note": pid_note}, ensure_ascii=False))
        return 2

    maps = adb.read_maps(pid)
    if not maps:
        print(json.dumps({"status": "error", "pid": pid,
                          "reason": "empty /proc/pid/maps"}, ensure_ascii=False))
        return 2
    reader = Reader(adb, pid, maps)
    has_il2cpp = any("libil2cpp.so" in m.path for m in maps)
    meta_maps = find_metadata(maps)
    summary: dict = {
        "tool": "tools/frapinfo_live_probe.py",
        "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mode": args.mode,
        "pid": pid,
        "pid_note": pid_note,
        "package": args.package,
        "maps": {"regions": len(maps), "libil2cpp_mapped": has_il2cpp,
                 "metadata_mappings": [
                     {"start": hex(m.start), "end": hex(m.end), "path": m.path}
                     for m in meta_maps]},
        "budgets": {"max_scan_mb": args.max_scan_mb,
                    "resolve_scan_mb": args.resolve_scan_mb,
                    "chunk_kb": args.chunk_kb, "workers": args.workers},
        "errors": [],
    }
    if not has_il2cpp:
        summary["status"] = "il2cpp-not-mapped"
        summary["notes"] = [
            "The process has no libil2cpp.so mapping: the game is not running an "
            "active Unity/IL2CPP session (background stub or still starting).",
            "frapInfo is created per frame inside FrameWindow.HandleFraqBootInfo; "
            "there is no replay frame to probe in this state.",
        ]
        out.mkdir(parents=True, exist_ok=True)
        (out / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": summary["status"], "pid": pid,
                          "out": str(out)}, ensure_ascii=False))
        return 2

    targets = [(FRAP_NAME, FRAP_NAMESPACE),
               (FRAME_WINDOW_NAME, FRAME_WINDOW_NAMESPACE)]
    resolved: dict = {}
    meta_info: dict = {}
    if args.mode != "signature":
        resolved, meta_info, resolve_errors = resolve_classes(
            adb, pid, maps, reader, targets, args.workers,
            args.chunk_kb * 1024, args.resolve_scan_mb)
        summary["resolve"] = {"classes": resolved, "details": meta_info,
                              "errors": resolve_errors}
        summary["errors"].extend(resolve_errors)
        if not resolved:
            summary["status"] = "class-resolution-failed"
            out.mkdir(parents=True, exist_ok=True)
            (out / "summary.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"status": summary["status"], "pid": pid,
                              "errors": resolve_errors, "out": str(out)},
                             ensure_ascii=False))
            return 3

    class_pointers = {name: info["class"] for name, info in resolved.items()}
    heap_result: dict = {}
    if args.mode in ("auto", "heap", "ring", "signature"):
        budget_mb = args.max_scan_mb
        regions = select_heap_regions(maps, budget_mb * 1048576 if budget_mb > 0 else 0)
        print(f"heap: {len(regions)} regions, "
              f"{sum(e - s for s, e, _ in regions) / 1048576:.0f} MiB budget", flush=True)
        heap_result = heap_scan(
            adb, pid, maps, reader, regions, class_pointers, args.workers,
            args.chunk_kb * 1024, budget_mb,
            signature=not args.no_signature and args.mode != "ring",
            max_per_chunk=args.max_per_chunk,
            max_validations=args.max_validations)
        summary["heap"] = {k: v for k, v in heap_result.items()
                           if not k.startswith("_")}

        # Validate class-anchored hits explicitly (including released count=0).
        validated: list[dict] = []
        released: list[dict] = []
        empty_rejected = 0
        rejected = Counter()
        examples: dict[str, list[str]] = {}
        for name, addresses in heap_result.get("_class_hits", {}).items():
            for addr in addresses[:64]:
                count = reader.u8(addr + 0xC)
                if count is None:
                    continue
                if count == 0:
                    if not plausible_empty_object(reader, addr, scudo_ranges(maps)):
                        empty_rejected += 1
                        continue
                    array = reader.u64(addr + 0x10)
                    released.append({
                        "addr": hex(addr),
                        "klass_name": class_name(reader, reader.u64(addr)),
                        "count": 0, "array": hex(array) if array else None,
                        "array_readable": bool(array and reader.readable(array, 8)),
                    })
                    continue
                src = Source(reader)
                candidate, reason = validate_candidate(
                    addr, count, src, scudo_ranges(maps),
                    class_pointers.get(FRAP_NAME))
                if candidate:
                    candidate["anchor"] = name
                    validated.append(candidate)
                else:
                    rejected[reason] += 1
                    if len(examples.setdefault(reason, [])) < 8:
                        examples[reason].append(hex(addr))
        summary["class_anchored"] = {
            "validated": sorted(validated, key=lambda c: -c["score"])[:20],
            "released_count_zero": released[:20],
            "released_rejected_not_frame_cmd": empty_rejected,
            "rejected_reasons": dict(rejected),
            "reject_examples": examples,
        }
        summary["resident_found"] = bool(validated)

        if args.mode in ("auto", "ring") and FRAME_WINDOW_NAME in resolved:
            instances = [{"addr": addr} for addr in
                         heap_result.get("_class_hits", {}).get(FRAME_WINDOW_NAME, [])]
            summary["ring"] = probe_ring(reader, instances, args.samples,
                                         args.sample_interval, args.max_packets)
            if args.abc:
                frames, err = load_abc_frames(args.abc)
                if err:
                    summary["abc"] = {"error": err}
                else:
                    summary["abc"] = {"file": str(args.abc),
                                      "frames_loaded": len(frames),
                                      "comparison": compare_abc(summary["ring"], frames)}
            if not summary["ring"].get("found"):
                if summary["ring"].get("instance_found"):
                    summary.setdefault("notes", []).append(
                        "FrameWindow ring instance found but all sampled slots are "
                        "empty; the replay path may use batch FRAPBOOT packets "
                        "instead of HandleFraqBootSingle.")
                else:
                    summary.setdefault("notes", []).append(
                        "No FrameWindow ring instance inside the scan budget: "
                        "the replay is not playing or the active object is elsewhere.")

    pids_now = adb.pids(args.package)
    summary["process_alive_after_scan"] = pid in pids_now
    if pid not in pids_now:
        summary["status"] = "process-exited-during-scan"
        summary.setdefault("notes", []).append(
            f"pid {pid} was not in pidof after the scan (now {pids_now}); "
            "read-only results are a partial snapshot of a process that restarted.")
    elif summary.get("heap", {}).get("scan_bytes", 0) == 0:
        summary["status"] = "scan-read-failed"
        summary.setdefault("notes", []).append(
            "The heap scan read zero bytes; /proc/pid/mem was not readable "
            "(wrong pid, permissions, or process exit).")

    if "status" not in summary:
        summary["status"] = "ok"
    summary["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": summary["status"],
        "pid": pid,
        "resident_found": summary.get("resident_found"),
        "class_pointers": {k: hex(v) for k, v in class_pointers.items()},
        "heap_scan_bytes": summary.get("heap", {}).get("scan_bytes"),
        "signature_validated": len(summary.get("heap", {}).get(
            "signature_validated", [])),
        "ring_found": summary.get("ring", {}).get("found"),
        "ring_instance_found": summary.get("ring", {}).get("instance_found"),
        "out": str(out),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
