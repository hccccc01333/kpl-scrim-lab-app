"""Derive selected runtime field offsets from named ELF exports, without execution.

Only accepts an export with one direct BL whose target is exactly a load + RET.
Does not use metadata-index address caches, XOR guesses, or historical snapshots.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
from capstone.arm64 import ARM64_OP_IMM, ARM64_OP_MEM, ARM64_OP_REG
from elftools.elf.elffile import ELFFile

from replay_evidence_check import ANALYSIS

GETTERS = {
    "il2cpp_method_get_name": "MethodInfo.name",
    "il2cpp_method_get_token": "MethodInfo.token",
    "il2cpp_method_get_param_count": "MethodInfo.parameter_count",
    "il2cpp_method_get_class": "MethodInfo.declaring_class",
    "il2cpp_class_get_name": "Il2CppClass.name",
    "il2cpp_class_get_namespace": "Il2CppClass.namespace",
    "il2cpp_class_get_image": "Il2CppClass.image",
}
RESOLVERS = ("il2cpp_class_get_methods", "il2cpp_class_get_method_from_name")


def audit(path: Path) -> dict:
    blob = path.read_bytes()
    with path.open("rb") as handle:
        elf = ELFFile(handle)
        loads = [(p["p_vaddr"], p["p_filesz"], p["p_offset"])
                 for p in elf.iter_segments() if p["p_type"] == "PT_LOAD"]
        symbols = {s.name: (s["st_value"], s["st_size"])
                   for s in elf.get_section_by_name(".dynsym").iter_symbols()
                   if s.name and s["st_value"]}
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    md.detail = True

    def read(va: int, size: int) -> bytes:
        for start, length, off in loads:
            if start <= va and va + size <= start + length:
                pos = off + va - start
                return blob[pos:pos + size]
        raise ValueError(f"Unmapped read {va:#x}")

    def wrapper(name: str) -> tuple[int, int]:
        va, size = symbols[name]
        if not 0 < size <= 64:
            raise ValueError(f"Unexpected wrapper size for {name}")
        ins = list(md.disasm(read(va, size), va))
        calls = [i.operands[0].imm for i in ins
                 if i.mnemonic == "bl" and i.operands[0].type == ARM64_OP_IMM]
        if len(calls) != 1 or not ins or ins[-1].mnemonic != "ret":
            raise ValueError(f"Not a single-call wrapper: {name}")
        return va, calls[0]

    fields = []
    for name, field in GETTERS.items():
        va, target = wrapper(name)
        ins = list(md.disasm(read(target, 8), target))
        if len(ins) != 2 or ins[0].mnemonic not in ("ldr", "ldrb", "ldrh") or ins[1].mnemonic != "ret":
            raise ValueError(f"Getter body not certified for {name}")
        load = ins[0]
        if (len(load.operands) != 2 or load.operands[0].type != ARM64_OP_REG
                or load.operands[1].type != ARM64_OP_MEM):
            raise ValueError(f"Unexpected load operands for {name}")
        dest = load.reg_name(load.operands[0].reg)
        mem = load.operands[1].mem
        if dest not in ("x0", "w0") or load.reg_name(mem.base) != "x0" or mem.index:
            raise ValueError(f"Not a direct object-field getter: {name}")
        fields.append({"field": field, "offset": hex(mem.disp), "export": name,
                       "export_va": hex(va), "getter_va": hex(target),
                       "instruction": f"{load.mnemonic} {load.op_str}"})
    resolvers = []
    for name in RESOLVERS:
        va, target = wrapper(name)
        resolvers.append({"export": name, "export_va": hex(va),
                          "direct_call_target": hex(target)})
    return {"binary_sha256": hashlib.sha256(blob).hexdigest(),
            "verified_fields": fields, "verified_export_calls": resolvers,
            "limitations": [
                "Offsets apply to this binary only; snapshot layouts remain unverified.",
                "Export identity verifies these getter fields, not metadata-index method pointers.",
                "No gameplay methods, resources, or game processes were loaded.",
            ]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ANALYSIS / "libil2cpp.so")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = audit(args.binary)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for field in result["verified_fields"]:
            print(f'{field["field"]}: {field["offset"]} '
                  f'({field["export_va"]} -> {field["getter_va"]})')
        for call in result["verified_export_calls"]:
            print(f'{call["export"]}: {call["export_va"]} -> {call["direct_call_target"]}')
        print("PASS: named export chains and direct getter bodies verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
