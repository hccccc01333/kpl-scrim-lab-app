#!/usr/bin/env python3
"""Capture the live GameCore CS command-dispatch table (read-only).

The parser at `base+0x46B8070` reads a 32-bit stream header, uses the low 16
bits as an index into `[base+0x544D340]` (a pointer to a 16-byte-entry table),
and dispatches through the first qword of that entry.  A fresh host process has
`[base+0x544D340] == 0` and the count at `base+0x5272368 == 0` after
`ModuleInit`; the table is populated later by the real match/context path.

This script reads the table and the BSS slots used by its thunks from a live
game process through `/proc/<pid>/mem` and writes a base-relative fixture:

    cmd_table.bin   fixed binary, consumed by host/src/h5_probe.c
    cmd_table.json  human-readable manifest and capture statistics

It is read-only: no injection, no calls into the game, no writes to the
process, no modification of game files.  The captured binary contains code
offsets and flags only; it has no account or player data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from capstone import CS_ARCH_ARM64, CS_MODE_ARM, Cs  # noqa: E402
from tools.gc_export_map import Core  # noqa: E402

MAGIC = b"KCMD"
VERSION = 1
HEADER = struct.Struct("<4sIIQQQ")  # magic, version, count, nslots, table_off, reserved
ENTRY = struct.Struct("<QQ")        # handler_off, flags (16-byte table entries)
SLOT = struct.Struct("<II")         # slot_off, target_off
PAGE = 0x1000
MEGA = 0x100000
DEFAULT_TABLE_SLOT = 0x544D340
DEFAULT_COUNT_SLOT = 0x5272368
DEFAULT_SLOT_WINDOW = 0x4FF5000
DEFAULT_SLOT_WINDOW_SIZE = 0x455478
DEFAULT_LIB_END = 0x544D478


def _read_mem(adb: str, serial: str, pid: int, addr: int, size: int) -> bytes:
    """Read `size` bytes at `addr` from /proc/<pid>/mem via adb (read-only)."""
    page = addr & ~(PAGE - 1)
    inner = (page & (MEGA - 1)) + (addr - page)
    blocks = (inner + size + MEGA - 1) // MEGA
    remote = (
        f"dd if=/proc/{pid}/mem bs={MEGA} skip={page // MEGA} count={blocks} "
        f"2>/dev/null | dd bs=1 skip={inner} count={size} 2>/dev/null"
    )
    result = subprocess.run(
        [adb, "-s", serial, "exec-out", remote],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if result.returncode != 0 or len(result.stdout) != size:
        raise RuntimeError(
            f"read {addr:#x}+{size:#x} failed (rc={result.returncode}, "
            f"got {len(result.stdout)} bytes): {result.stderr.decode(errors='replace').strip()}"
        )
    return result.stdout


def _disasm_slot(blob: bytes, addr: int) -> int | None:
    """Return the BSS slot VA referenced by an `adrp/ldr/br` thunk, if any.

    Typical table entry handler:
        adrp x8, #0x5230000
        ldr  x3, [x8, #0x4d0]
        br   x3
    """
    if len(blob) < 12:
        return None
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    insns = list(md.disasm(blob[:12], addr))
    if len(insns) < 3:
        return None
    adrp, ldr, br = insns[0], insns[1], insns[2]
    if adrp.mnemonic != "adrp" or ldr.mnemonic != "ldr" or br.mnemonic != "br":
        return None
    m_adrp = re.fullmatch(r"(x\d+), #(0x[0-9a-fA-F]+)", adrp.op_str)
    m_ldr = re.fullmatch(r"(x\d+), \[(x\d+), #(0x[0-9a-fA-F]+)\]", ldr.op_str)
    if not m_adrp or not m_ldr:
        return None
    adrp_reg, dst_reg, base_reg = m_adrp.group(1), m_ldr.group(1), m_ldr.group(2)
    if adrp_reg != base_reg or br.op_str != dst_reg:
        return None
    return int(m_adrp.group(2), 16) + int(m_ldr.group(3), 16)


def _scan_slots(blob: bytes, addr: int, lib_end: int) -> set[int]:
    """Collect BSS slots loaded by `adrp` + `ldr` pairs in a code window."""
    out: set[int] = set()
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    insns = list(md.disasm(blob, addr))
    for first, second in zip(insns, insns[1:]):
        if first.mnemonic != "adrp" or second.mnemonic != "ldr":
            continue
        m_adrp = re.fullmatch(r"(x\d+), #(0x[0-9a-fA-F]+)", first.op_str)
        m_ldr = re.fullmatch(r"(x\d+), \[(x\d+), #(0x[0-9a-fA-F]+)\]", second.op_str)
        if not m_adrp or not m_ldr or m_adrp.group(1) != m_ldr.group(2):
            continue
        target = int(m_adrp.group(2), 16) + int(m_ldr.group(3), 16)
        if DEFAULT_SLOT_WINDOW <= target < lib_end:
            out.add(target)
    return out


def capture(adb: str, serial: str, pid: int, base: int, lib_end: int,
            table_slot: int, count_slot: int, slot_window: int,
            slot_window_size: int, scan_depth: int, scan_insns: int,
            max_slots: int) -> tuple[bytes, dict]:
    table_ptr = struct.unpack("<Q", _read_mem(adb, serial, pid, base + table_slot, 8))[0]
    count = struct.unpack("<I", _read_mem(adb, serial, pid, base + count_slot, 4))[0]
    if not 0 < count <= 0x10000:
        raise RuntimeError(f"implausible command count: {count}")
    if not base <= table_ptr < base + lib_end:
        raise RuntimeError(f"table pointer {table_ptr:#x} outside libGameCore")
    table_off = table_ptr - base
    table = _read_mem(adb, serial, pid, table_ptr, count * ENTRY.size)

    core = Core(ROOT / "data/replays/_analysis/libGameCore.so")
    entries = []
    needed_slots: set[int] = set()
    handler_outside = 0
    for index in range(count):
        handler, flags = ENTRY.unpack_from(table, index * ENTRY.size)
        handler_off = 0
        if handler:
            rel = handler - base
            if 0 < rel < lib_end:
                handler_off = rel
            else:
                handler_outside += 1
        entries.append((handler_off, flags))
        if handler_off:
            off = core.va2off(handler_off)
            if off is not None:
                slot = _disasm_slot(core.blob[off:off + 12], handler_off)
                if slot is not None:
                    needed_slots.add(slot)

    window = _read_mem(adb, serial, pid, base + slot_window, slot_window_size)

    def slot_value(slot_off: int) -> int:
        if not slot_window <= slot_off < slot_window + slot_window_size:
            return 0
        return struct.unpack_from("<Q", window, slot_off - slot_window)[0]

    # Follow the registration thunks: a handler usually loads a code pointer
    # from a BSS slot and branches to it.  Those targets are themselves real
    # implementations, so scan them for further BSS slots up to a bounded depth.
    frontier = {
        slot_value(slot) - base for slot in needed_slots
        if 0 < slot_value(slot) - base < lib_end
    }
    scanned_targets = set()
    for _ in range(max(0, scan_depth)):
        next_slots: set[int] = set()
        for target in frontier:
            if target in scanned_targets:
                continue
            scanned_targets.add(target)
            off = core.va2off(target)
            if off is None:
                continue
            for slot in _scan_slots(core.blob[off:off + scan_insns * 4], target, lib_end):
                next_slots.add(slot)
        next_slots -= needed_slots
        if not next_slots:
            break
        needed_slots |= next_slots
        if len(needed_slots) > max_slots:
            needed_slots = set(sorted(needed_slots)[:max_slots])
            break
        frontier = {
            slot_value(slot) - base for slot in next_slots
            if 0 < slot_value(slot) - base < lib_end
        }

    slots = []
    external_slots = []
    for rel_slot in sorted(needed_slots):
        if not 0 <= rel_slot < lib_end:
            external_slots.append({"slot": f"0x{rel_slot:x}", "reason": "outside-lib"})
            continue
        if not slot_window <= rel_slot < slot_window + slot_window_size:
            external_slots.append({"slot": f"0x{rel_slot:x}", "reason": "outside-window"})
            continue
        value = slot_value(rel_slot)
        if value == 0:
            target_off = 0
        elif base <= value < base + lib_end:
            target_off = value - base
        else:
            external_slots.append({"slot": f"0x{rel_slot:x}", "value": f"0x{value:x}",
                                   "reason": "non-lib-pointer"})
            continue
        slots.append((rel_slot, target_off))

    payload = bytearray(HEADER.pack(MAGIC, VERSION, count, len(slots), table_off, 0))
    for handler_off, flags in entries:
        payload += ENTRY.pack(handler_off, flags)
    for slot_off, target_off in slots:
        payload += SLOT.pack(slot_off, target_off)

    manifest = {
        "schema": "kpl-gamecore-cmd-table-v1",
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": {
            "pid": pid, "base": f"0x{base:x}", "lib_end": f"0x{lib_end:x}",
            "table_slot": f"0x{table_slot:x}", "count_slot": f"0x{count_slot:x}",
            "read_only": True,
            "method": "adb exec-out dd /proc/<pid>/mem (no attach, no writes)",
        },
        "table": {
            "pointer": f"0x{table_ptr:x}", "base_relative": f"0x{table_off:x}",
            "count": count, "entry_bytes": ENTRY.size,
            "nonzero_handlers": sum(1 for h, _ in entries if h),
            "handlers_outside_lib": handler_outside,
            "flags_observed": sorted({f for _, f in entries}),
        },
        "slots": {
            "captured": len(slots),
            "zero_targets": sum(1 for _, t in slots if t == 0),
            "scanned_targets": len(scanned_targets),
            "scan_depth": scan_depth,
            "external_or_skipped": external_slots[:32],
            "external_or_skipped_count": len(external_slots),
        },
        "binary": {
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "layout": "KCMD v1: <4sIIQQQ> header, count*<QQ> entries, nslots*<II> slots",
        },
        "notes": [
            "Offsets are base-relative to the captured libGameCore load address.",
            "The table and slots are runtime state; zero slots are preserved as zero.",
            "A fresh host must install this fixture before the CS consumer can dispatch.",
            "The fixture contains no player, account, or match content.",
        ],
    }
    return bytes(payload), manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default="D:/MuMuPlayer/nx_main/adb.exe")
    parser.add_argument("--serial", default="127.0.0.1:16384")
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--base", default="0x400036a00000")
    parser.add_argument("--lib-end", default=hex(DEFAULT_LIB_END))
    parser.add_argument("--table-slot", default=hex(DEFAULT_TABLE_SLOT))
    parser.add_argument("--count-slot", default=hex(DEFAULT_COUNT_SLOT))
    parser.add_argument("--slot-window", default=hex(DEFAULT_SLOT_WINDOW))
    parser.add_argument("--slot-window-size", default=hex(DEFAULT_SLOT_WINDOW_SIZE))
    parser.add_argument("--scan-depth", type=int, default=2)
    parser.add_argument("--scan-insns", type=int, default=96)
    parser.add_argument("--max-slots", type=int, default=4096)
    parser.add_argument("--out-dir", type=Path,
                        default=ROOT / "host/fixtures/20261102_161129/consumer")
    args = parser.parse_args()

    payload, manifest = capture(
        args.adb, args.serial, args.pid, int(args.base, 0), int(args.lib_end, 0),
        int(args.table_slot, 0), int(args.count_slot, 0),
        int(args.slot_window, 0), int(args.slot_window_size, 0),
        args.scan_depth, args.scan_insns, args.max_slots,
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "cmd_table.bin").write_bytes(payload)
    (args.out_dir / "cmd_table.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out_dir), **manifest["table"],
                      "slots": manifest["slots"]["captured"],
                      "sha256": manifest["binary"]["sha256"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
