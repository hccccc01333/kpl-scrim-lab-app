"""Direct poller for the live FrameWindow packet ring (docs 5.151-5.152).

Reads the FrameWindow instance found via the class static field (il2cpp
objects do not move, so the addresses are stable across polls), tracks the
ring's base/current/max_seen, and dumps every NEW ring slot's packet object.
Read-only: /proc/<pid>/mem reads over an ADB root shell only.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

ADB = ["adb", "-s", "127.0.0.1:16384"]
PID = 2052
FW_KLASS = 0x75DB8938D4D0
FW_STATICS = 0x75DB1DBC6B20
FW_INSTANCE = 0x75D84ABFF960


def mem(addr: int, size: int) -> bytes:
    page = addr & ~4095
    count = (addr - page + size + 4095) // 4096
    raw = subprocess.run(
        ADB + ["exec-out", f"dd if=/proc/{PID}/mem bs=4096 skip={page // 4096} "
               f"count={count} 2>/dev/null"],
        capture_output=True, timeout=60).stdout
    if len(raw) < (addr - page) + size:
        raise ValueError(f"short read at {addr:#x}: {len(raw)}/{size}")
    return raw[addr - page: addr - page + size]


def u64(addr: int) -> int:
    return int.from_bytes(mem(addr, 8), "little")


def u32(addr: int) -> int:
    return int.from_bytes(mem(addr, 4), "little")


def resolve_instance() -> int:
    """Re-resolve the FrameWindow instance from the class static fields."""
    statics = mem(FW_STATICS, 0x400)
    for i in range(0, 0x400, 8):
        v = int.from_bytes(statics[i:i + 8], "little")
        if 0x10000 < v < 0x800000000000:
            try:
                if int.from_bytes(mem(v, 8), "little") == FW_KLASS:
                    return v
            except ValueError:
                continue
    return FW_INSTANCE  # fall back to the known address


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=200)
    parser.add_argument("--interval", type=float, default=3.0)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    ignored_root = (Path(__file__).resolve().parents[1] / "data").resolve()
    if ignored_root not in out.parents:
        parser.error("--out must stay inside project data/")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)

    instance = resolve_instance()
    print(f"FrameWindow instance: {instance:#x}", flush=True)
    seen_packets: set[int] = set()
    rows: list[dict] = []
    log = open(out.with_suffix(".jsonl"), "w", encoding="utf-8")
    for sample in range(args.samples):
        try:
            base = u32(instance + 0x10)
            current = u32(instance + 0x14)
            max_seen = u32(instance + 0x18)
            ring = u64(instance + 0x08)
            new_packets = []
            if ring:
                # bounded slot read: up to 4096 slots, only new pointers kept
                slots = mem(ring, 4096 * 8)
                for i in range(4096):
                    p = int.from_bytes(slots[i * 8:i * 8 + 8], "little")
                    if p > 0x10000 and p not in seen_packets:
                        seen_packets.add(p)
                        new_packets.append((i, p))
            row = {"sample": sample, "time": time.time(), "base": base,
                   "current": current, "max_seen": max_seen,
                   "ring": hex(ring), "new_packets": len(new_packets)}
            for i, p in new_packets[:64]:
                try:
                    obj = mem(p, 0x40)
                    frame = int.from_bytes(obj[0x0C:0x10], "little")
                    plen = int.from_bytes(obj[0x10:0x12], "little")
                    payload = obj[0x18:0x18 + min(plen or 0, 96)] if plen else b""
                    row.setdefault("packets", []).append(
                        {"slot": i, "packet": hex(p), "frame": frame,
                         "plen": plen, "payload_head": payload.hex()})
                except ValueError:
                    row.setdefault("packets", []).append(
                        {"slot": i, "packet": hex(p), "error": "unreadable"})
            rows.append(row)
            log.write(json.dumps(row, ensure_ascii=False) + "\n")
            log.flush()
            if sample % 10 == 0:
                print(f"sample {sample}: base={base} current={current} "
                      f"max_seen={max_seen} new={len(new_packets)}", flush=True)
        except (ValueError, subprocess.TimeoutExpired) as exc:
            print(f"sample {sample}: read failed: {exc}", flush=True)
        time.sleep(args.interval)
    log.close()
    (out / "poll_summary.json").write_text(
        json.dumps({"instance": hex(instance), "samples": len(rows),
                    "packets_seen": len(seen_packets)}, ensure_ascii=False),
        encoding="utf-8")
    print(f"done: {len(rows)} samples, {len(seen_packets)} distinct packets", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
