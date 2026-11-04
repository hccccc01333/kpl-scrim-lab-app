#!/usr/bin/env python3
"""Patch libil2cpp.so so the Android linker does not call DT_INIT.

On the physical ARM64 device the original `DT_INIT` (0xE56145C) hangs during
dlopen (it expects Unity/JNI state).  Setting the DT_INIT *value* to 0 makes the
linker call base+0 and SIGSEGV.  The correct minimal patch is to change the
dynamic entry's tag to DT_NULL, leaving the file size and all other tags intact.

This is a host-only binary patch; it does not touch the game process or files.

Usage:
  python host/scripts/patch_libil2cpp_init_tag.py \
      data/replays/_analysis/libil2cpp.so host/build/libil2cpp_noinit_tag.so
"""
from __future__ import annotations

import argparse
import struct
from pathlib import Path

DT_NULL = 0
DT_INIT = 12
PT_DYNAMIC = 2


def patch(src: Path, dst: Path) -> int:
    data = bytearray(src.read_bytes())
    if data[:4] != b"\x7fELF" or data[4] != 2:
        raise SystemExit("not an ELF64 file")
    phoff = struct.unpack_from("<Q", data, 0x20)[0]
    phentsize = struct.unpack_from("<H", data, 0x36)[0]
    phnum = struct.unpack_from("<H", data, 0x38)[0]
    dyn = None
    for i in range(phnum):
        off = phoff + i * phentsize
        if struct.unpack_from("<I", data, off)[0] == PT_DYNAMIC:
            dyn = (struct.unpack_from("<Q", data, off + 8)[0],
                   struct.unpack_from("<Q", data, off + 32)[0])
            break
    if dyn is None:
        raise SystemExit("PT_DYNAMIC not found")
    start, size = dyn
    patched = 0
    for q in range(start, start + size, 16):
        tag, value = struct.unpack_from("<QQ", data, q)
        if tag == DT_INIT:
            struct.pack_into("<Q", data, q, DT_NULL)
            patched += 1
            print(f"DT_INIT at {q:#x} value {value:#x} -> DT_NULL")
    if not patched:
        raise SystemExit("DT_INIT not found")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(data)
    print(f"wrote {dst} ({len(data)} bytes)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path)
    ap.add_argument("dst", type=Path)
    args = ap.parse_args()
    return patch(args.src, args.dst)


if __name__ == "__main__":
    raise SystemExit(main())
