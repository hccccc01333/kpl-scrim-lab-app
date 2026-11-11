"""Decode the frame-command dispatch table of GameLogicHelper.AdvanceFrameCommands.

Build 5247758, libil2cpp.so. The live method pointer is a thunk at file offset
0x6e04fa4; it jumps through a relocated pointer to the real implementation at
0x40002c84cf7c (file offset 0x664bf7c). The implementation loops over
frapInfo+0xc commands, reads a u8 type at command+0xc, and dispatches through a
27-entry u16 jump table at file offset 0x19be5ac.

This script only writes the static dispatch map; it does not run the game,
inject, or claim the field names of each command.
"""
from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "data" / "replays" / "_analysis" / "libil2cpp.so"
OUT = ROOT / "data" / "replays" / "_analysis" / "datasets" / "advance_frame_dispatch.csv"

# Runtime addresses from the 2026-11-03 capture; file offsets are stable for
# this libil2cpp.so copy.
THUNK_FILE_OFFSET = 0x6E04FA4
IMPLEMENTATION_RUNTIME = 0x40002C84CF7C
IMPLEMENTATION_FILE_OFFSET = 0x664BF7C
TABLE_FILE_OFFSET = 0x19BE5AC
JUMP_BASE_RUNTIME = 0x40002C84D03C
DEFAULT_RUNTIME = 0x40002C84D03C
SKIP_RUNTIME = 0x40002C84D050


def main() -> None:
    data = LIB.read_bytes()
    rows = []
    for index in range(27):
        raw = int.from_bytes(data[TABLE_FILE_OFFSET + index * 2:TABLE_FILE_OFFSET + index * 2 + 2], "little")
        target = JUMP_BASE_RUNTIME + raw * 4
        if target == DEFAULT_RUNTIME:
            kind = "default"
        elif target == SKIP_RUNTIME:
            kind = "skip"
        else:
            kind = "handler"
        rows.append({
            "type": index + 1,
            "jump_offset": f"0x{raw:04x}",
            "handler_runtime": f"0x{target:016x}",
            "kind": kind,
        })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"implementation runtime=0x{IMPLEMENTATION_RUNTIME:016x} file=0x{IMPLEMENTATION_FILE_OFFSET:x}")
    print(f"frapInfo: +0xc=command_count, +0x10=command_array")
    print(f"command: +0xc=type (1..27), +0x10=payload/class pointer")
    print(f"wrote {OUT} ({len(rows)} types)")


if __name__ == "__main__":
    main()
