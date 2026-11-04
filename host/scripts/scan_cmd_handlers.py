#!/usr/bin/env python3
"""Scan the captured CS handler table: for each opcode, statically extract
the handler's payload-consume size and call targets from the local
libGameCore.so (same build as the live capture).

Consume-size heuristic: handlers receive (cursor *x0, flag w1, arg w2).  The
common prologue is  ldr xM, [x0]; ... add xN, xM, #imm; str xN, [x0]  where
imm = bytes consumed for the flag==1 path.  Also records the first bl/blr
targets and whether the handler touches slot1 ([0x4ff57c8] chain) or the
handler-table again.

Output: host/build/g5/cmd_handlers_scan.json
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

from elftools.elf.elffile import ELFFile
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "data/replays/_analysis/libGameCore.so"
TABLE = ROOT / "host/fixtures/20261102_161129/consumer/cmd_table.bin"
OUT = ROOT / "host/build/g5/cmd_handlers_scan.json"

RUNTIME_BASE_DELTA = 0  # cmd_table stores base-relative handler offsets


def main() -> int:
    blob = LIB.read_bytes()
    elf = ELFFile(LIB.open("rb"))
    seg = next(p for p in elf.iter_segments() if p["p_type"] == "PT_LOAD" and p["p_flags"] == 5)
    va0, sz0, off0 = seg["p_vaddr"], seg["p_filesz"], seg["p_offset"]

    def code(va: int, n: int) -> bytes:
        if not (va0 <= va < va0 + sz0):
            return b""
        o = va - va0 + off0
        return blob[o:o + n]

    dyn = {t.entry.d_tag: t.entry.d_val for t in elf.get_section_by_name(".dynamic").iter_tags()}

    def off_of(va: int) -> int | None:
        for p in elf.iter_segments():
            if p["p_type"] == "PT_LOAD" and p["p_vaddr"] <= va < p["p_vaddr"] + p["p_filesz"]:
                return p["p_offset"] + va - p["p_vaddr"]
        return None

    rela_off = off_of(dyn["DT_RELA"])
    rela_sz = dyn["DT_RELASZ"]
    rela = {}
    rblob = blob
    for pos in range(rela_off, rela_off + rela_sz, 24):
        t, k, a = struct.unpack_from("<QQq", rblob, pos)
        if (k & 0xFFFFFFFF) == 1027:
            rela[t] = a

    md = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)

    raw = TABLE.read_bytes()
    magic, version, count, nslots, table_off, _ = struct.unpack_from("<4sIIQQQ", raw, 0)
    assert magic == b"KCMD", magic
    entries = []
    base = 36
    for i in range(count):
        h, flags = struct.unpack_from("<QQ", raw, base + i * 16)
        entries.append((h, flags))

    def resolve_thunk(va: int, depth: int = 0) -> tuple[int, bool]:
        """If va is an adrp+ldr+br thunk, resolve the slot target via RELA."""
        ins_list = list(md.disasm(code(va, 0x10), va))
        if len(ins_list) >= 3 and depth < 2:
            a, l, b = ins_list[0], ins_list[1], ins_list[2]
            if (a.mnemonic == "adrp" and l.mnemonic == "ldr" and b.mnemonic in ("br", "blr")):
                reg = a.op_str.split(",")[0]
                parts = l.op_str.split("[")[1].strip("]").split(", ")
                if len(parts) == 2 and parts[0] == reg and parts[1].startswith("#"):
                    try:
                        offv = int(parts[1].replace("#", ""), 16)
                        page = int(a.op_str.split(",")[1].strip().replace("#", ""), 16)
                    except ValueError:
                        return va, False
                    slotva = page + offv
                    tgt = rela.get(slotva)
                    if tgt:
                        return tgt, True
        return va, False

    result = []
    for op, (h, flags) in enumerate(entries):
        if h == 0:
            continue
        va = h  # base-relative
        va, is_thunk = resolve_thunk(va)
        codebytes = code(va, 0x60)
        if not codebytes:
            result.append({"op": op, "handler": hex(va), "thunk": is_thunk, "note": "outside exec seg"})
            continue
        ins_list = list(md.disasm(codebytes, va))
        consume = None
        flag_consumes = {}
        calls = []
        touches_slot1 = False
        cur_mode = None  # track whether we're in flag==1 (tbz w1,#0 not taken) path
        aliases = {"x0"}      # registers that hold the cursor pointer
        cursor_vals = set()   # registers holding *cursor (the data pointer)
        for idx, ins in enumerate(ins_list[:40]):
            ops = ins.op_str.split(", ") if ins.op_str else []
            if ins.mnemonic == "mov" and len(ops) == 2 and ops[1] in aliases:
                aliases.add(ops[0])
            if ins.mnemonic == "tbz" and "#0" in ins.op_str and ins.op_str.startswith("w1"):
                cur_mode = "flag0"  # branch taken when bit0==0
            elif ins.mnemonic == "tbnz" and ins.op_str.startswith("w1"):
                cur_mode = "flag1"
            if ins.mnemonic == "ldr" and "[" in ins.op_str:
                parts = ins.op_str.split("[")[1].strip("]").split(", ")
                if len(parts) >= 1 and parts[0] in aliases:
                    cursor_vals.add(ins.op_str.split()[0].rstrip(","))
            # post-increment consume: ldr wX, [xM], #imm
            if ins.mnemonic == "ldr" and ins.op_str.count(",") >= 2:
                m = ins.op_str.rsplit(", ", 1)
                if m[1].startswith("#"):
                    try:
                        imm = int(m[1].replace("#", ""), 16)
                    except ValueError:
                        imm = None
                    if imm is not None and ("[" in m[0] and m[0].split("[")[1].split(",")[0] in aliases):
                        key = cur_mode or "entry"
                        flag_consumes.setdefault(key, imm)
            if ins.mnemonic == "add" and len(ops) == 3 and ops[2].startswith("#"):
                if ops[1] in cursor_vals:
                    try:
                        imm = int(ops[2].replace("#", ""), 16)
                    except ValueError:
                        continue
                    key = cur_mode or "entry"
                    flag_consumes.setdefault(key, imm)
            if ins.mnemonic == "blr":
                calls.append("indirect")
            if ins.mnemonic == "bl":
                tgt = int(ins.op_str.replace("#", ""), 16)
                calls.append(hex(tgt))
        # adrp+ldr slot refs
        adrp = {}
        for ins in ins_list[:40]:
            if ins.mnemonic == "adrp":
                reg, pg = [x.strip() for x in ins.op_str.split(",")]
                try:
                    adrp[reg] = int(pg.replace("#", ""), 16)
                except ValueError:
                    pass
            elif ins.mnemonic == "ldr" and "[" in ins.op_str:
                parts = ins.op_str.split("[")[1].strip("]").split(", ")
                if len(parts) == 2 and parts[0] in adrp and parts[1].startswith("#"):
                    try:
                        offv = int(parts[1].replace("#", ""), 16)
                    except ValueError:
                        continue
                    slotva = adrp[parts[0]] + offv
                    if slotva == 0x4FF57C8:
                        touches_slot1 = True
        result.append({
            "op": op,
            "handler": hex(va), "thunk": is_thunk,
            "flags_entry": hex(flags),
            "consume": flag_consumes,
            "calls": calls[:4],
            "slot1": touches_slot1,
        })

    OUT.write_text(json.dumps(result, indent=0))
    n_consume = sum(1 for r in result if isinstance(r.get("consume"), dict) and r["consume"])
    print(f"entries={len(result)} with-consume={n_consume} -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
