"""Read selected replay MethodInfo records from an already-running offline client.

Requires an existing root ADB shell. Never injects, calls game functions, or writes
device files. Reads metadata and one bounded scudo primary region, not all memory.
Captures stay under ignored data/. No previous capture is overwritten.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import subprocess
from pathlib import Path

TARGETS = {
    "GameReplayModule": {"ListReplayFiles", "ScanReplayFiles", "GetReplayInfoByFilePath",
                         "BeginReplay", "GetBeginLoadMsg", "CheckReplayVersion",
                         "RetriveBeginLoad", "PureReplayLogic", "UpdateFrame",
                         "LoadMsg", "SLoadDefaultMsg", "AnalyseReplayFile", "HandleSinglePkg", "Handle"},
    "FrameWindow": {"HandleFraqBootSingle", "HandleFraqBootInfo", "onFrapBootInfoSingleNtf"},
    "SCPKG_FRAPBOOT_SINGLE": {"unpack"},
    "ReplayMemoryRecover": {"PrepareReplayRecover", "IsValidReplayFile"},
    "CSPkg": {"unpack"},
    "CSPkgHead": {"unpack"},
    "CSPkgBody": {"unpack", "select", ".cctor"},
    "SCPKG_MULTGAME_BEGINLOAD": {"unpack", ".ctor"},
    "SGW": {"BeginLoad", "AsyncBeginLoad", "PureReplayStart", "StartHostReplay"},
}
ROOT = Path(__file__).resolve().parents[1]


def read_maps(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        parts = line.split(maxsplit=5)
        if len(parts) < 5:
            continue
        start, end = (int(x, 16) for x in parts[0].split("-"))
        rows.append({"start": start, "end": end, "perms": parts[1],
                     "offset": int(parts[2], 16), "path": parts[5] if len(parts) > 5 else ""})
    return rows


def targets_from_metadata(blob: bytes, base: int) -> list[dict]:
    if struct.unpack_from("<II", blob) != (0xFAB11BAF, 29):
        raise ValueError("Expected metadata v29")
    so, ss = struct.unpack_from("<II", blob, 24)
    mo, ms = struct.unpack_from("<II", blob, 48)
    to, ts = struct.unpack_from("<II", blob, 160)

    def string(index: int) -> str:
        if not 0 <= index < ss:
            raise ValueError("String outside metadata table")
        end = blob.index(b"\0", so + index, so + ss)
        return blob[so + index:end].decode("utf-8")

    result = []
    for index in range(ts // 88):
        row = struct.unpack_from("<16i8H2I", blob, to + index * 88)
        owner = string(row[0])
        if owner not in TARGETS:
            continue
        for method_index in range(row[9], row[9] + row[16]):
            if not 0 <= method_index < ms // 32:
                raise ValueError("Invalid method range")
            method = struct.unpack_from("<6i4H", blob, mo + method_index * 32)
            name = string(method[0])
            if name in TARGETS[owner]:
                result.append({"owner": owner, "method": name, "token": method[5],
                               "params": method[9], "name_pointer": base + so + method[0],
                               "class_name_pointer": base + so + row[0],
                               "namespace_pointer": base + so + row[1]})
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default="D:/MuMuPlayer/nx_main/adb.exe")
    parser.add_argument("--serial", default="127.0.0.1:16384")
    parser.add_argument("--capture-dir", type=Path, required=True)
    parser.add_argument("--max-heap-mb", type=int, default=96)
    args = parser.parse_args()
    out = args.capture_dir.resolve()
    ignored_root = (ROOT / "data").resolve()
    if ignored_root not in out.parents:
        parser.error("Captures must be inside project data/")
    if out.exists():
        parser.error("Use a new capture directory; existing captures are preserved")
    if not 1 <= args.max_heap_mb <= 128:
        parser.error("Heap limit must be 1..128 MiB")
    prefix = [args.adb, "-s", args.serial]

    def adb(*cmd: str, timeout: int = 15) -> bytes:
        return subprocess.run(prefix + list(cmd), capture_output=True, timeout=timeout,
                              check=True).stdout

    pid = int(adb("shell", "pidof", "com.tencent.tmgp.sgame").split()[0])
    maps_text = adb("shell", "cat", f"/proc/{pid}/maps").decode("utf-8")
    maps = read_maps(maps_text)
    metas = [r for r in maps if "_$$global-metadata$$_" in r["path"]]
    if len(metas) != 1:
        raise ValueError("Expected one current metadata mapping")
    meta_region = metas[0]

    def memory(start: int, size: int) -> bytes:
        page = start & ~4095
        count = (start - page + size + 4095) // 4096
        # exec-out merges the remote stderr stream; suppress dd's statistics.
        # Every interpolated value is an integer, not a file or shell expression.
        raw = adb("exec-out", f"dd if=/proc/{pid}/mem bs=4096 "
                  f"skip={page // 4096} count={count} 2>/dev/null", timeout=25)
        if len(raw) != count * 4096:
            raise ValueError("Incomplete memory read")
        return raw[start - page:start - page + size]

    meta = memory(meta_region["start"], meta_region["end"] - meta_region["start"])
    targets = targets_from_metadata(meta, meta_region["start"])
    heaps = [r for r in maps if r["perms"] == "rw-p" and "scudo:primary" in r["path"]
             and r["end"] - r["start"] <= args.max_heap_mb * 1048576]
    if not heaps:
        raise ValueError("No bounded scudo primary region")
    heap_region = max(heaps, key=lambda r: r["end"] - r["start"])
    print(f'pid={pid}; reading one primary region {(heap_region["end"] - heap_region["start"])/1048576:.1f} MiB', flush=True)
    heap = memory(heap_region["start"], heap_region["end"] - heap_region["start"])

    def read_small(address: int, size: int) -> bytes:
        lo = address - heap_region["start"]
        if 0 <= lo and lo + size <= len(heap):
            return heap[lo:lo + size]
        if not any(r["perms"].startswith("r") and r["start"] <= address
                   and address + size <= r["end"] for r in maps):
            raise ValueError("Object outside readable mappings")
        return memory(address, size)

    hits = []
    code = {}
    for target in targets:
        needle = struct.pack("<Q", target["name_pointer"])
        pos = 0
        while True:
            pos = heap.find(needle, pos)
            if pos < 0:
                break
            start = pos - 0x18
            pos += 1
            if start < 0 or start % 8 or start + 0x58 > len(heap):
                continue
            record = heap[start:start + 0x58]
            if (struct.unpack_from("<I", record, 0x48)[0] != target["token"]
                    or record[0x52] != target["params"]):
                continue
            ptr, klass = struct.unpack_from("<Q", record)[0], struct.unpack_from("<Q", record, 0x20)[0]
            region = next((r for r in maps if "libil2cpp.so" in r["path"]
                           and r["start"] <= ptr < r["end"]), None)
            if not region:
                continue
            if struct.unpack_from("<Q", read_small(klass + 0x10, 8))[0] != target["class_name_pointer"]:
                continue
            if struct.unpack_from("<Q", read_small(klass + 0x18, 8))[0] != target["namespace_pointer"]:
                continue
            row = {"owner": target["owner"], "method": target["method"],
                   "token": hex(target["token"]), "params": target["params"],
                   "methodinfo": hex(heap_region["start"] + start), "class": hex(klass),
                   "pointer": hex(ptr), "mapped_file_offset": hex(region["offset"] + ptr - region["start"])}
            filename = f'{target["owner"]}_{target["method"]}_{target["params"]}_{target["token"]:x}.bin'
            row["code_file"] = filename
            code[filename] = memory(ptr, min(4096, region["end"] - ptr))
            hits.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    out.mkdir(parents=True)
    (out / "maps.txt").write_text(maps_text, encoding="utf-8")
    (out / "metadata.bin").write_bytes(meta)
    for filename, data in code.items():
        (out / filename).write_bytes(data)
    result = {"pid": pid, "metadata_sha256": hashlib.sha256(meta).hexdigest(),
              "heap_bytes_read": len(heap), "heap_saved": False, "hits": hits,
              "unresolved": [t["method"] for t in targets if not any(
                  r["owner"] == t["owner"] and r["token"] == hex(t["token"]) for r in hits)]}
    (out / "methods.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f'Captured {len(hits)} verified MethodInfo records. Device unchanged; heap not saved.')
    return 0 if hits else 1


if __name__ == "__main__":
    raise SystemExit(main())
