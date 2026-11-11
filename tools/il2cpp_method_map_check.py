"""Falsify the old '.data base + metadata index * 8' method-map hypothesis.

Read-only. Uses ELF PT_LOAD/DT_RELA, not old symbol caches or code decodability.
Run: python tools/il2cpp_method_map_check.py --check
Exit 1 means the assumed global map has direct counterexamples.
"""
from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

from elftools.elf.elffile import ELFFile

from replay_evidence_check import ANALYSIS, metadata

ASSUMED_TABLE = 0xD380CE0


def audit(root: Path) -> dict:
    meta_blob = (root / "global-metadata.dat").read_bytes()
    info = metadata(meta_blob)
    blob = (root / "libil2cpp.so").read_bytes()
    with (root / "libil2cpp.so").open("rb") as handle:
        elf = ELFFile(handle)
        loads = [(p["p_vaddr"], p["p_filesz"], p["p_offset"], p["p_flags"])
                 for p in elf.iter_segments() if p["p_type"] == "PT_LOAD"]
        dynamic = {tag.entry.d_tag: tag.entry.d_val
                   for tag in elf.get_section_by_name(".dynamic").iter_tags()}

    def offset(va: int, size: int = 8) -> int:
        for start, length, off, _ in loads:
            if start <= va and va + size <= start + length:
                return off + va - start
        raise ValueError(f"VA {va:#x} outside file-backed load segments")

    def executable(va: int) -> bool:
        return any(flags & 1 and start <= va < start + size
                   for start, size, _, flags in loads)

    methods_off, methods_size = struct.unpack_from("<II", meta_blob, 6 * 8)
    if methods_size // 32 != info["method_count"]:
        raise ValueError("Inconsistent method count")
    abstract_indices = [i for i in range(info["method_count"])
                        if struct.unpack_from("<H", meta_blob, methods_off + i * 32 + 24)[0] & 0x400]
    # Collect only inspected relocation slots; preserve raw non-relocated values.
    n = info["method_count"]
    indices = set(range(35)) | set(abstract_indices) | set(range(n - 3, n + 1000))
    values = {i: struct.unpack_from("<Q", blob, offset(ASSUMED_TABLE + i * 8))[0]
              for i in indices}
    relocated = set()
    rela_off = offset(dynamic["DT_RELA"], dynamic["DT_RELASZ"])
    rela_size = dynamic.get("DT_RELAENT", 24)
    if rela_size != 24 or dynamic["DT_RELASZ"] % 24:
        raise ValueError("Unexpected ELF64 RELA shape")
    for pos in range(rela_off, rela_off + dynamic["DT_RELASZ"], 24):
        target, kind, addend = struct.unpack_from("<QQq", blob, pos)
        if kind & 0xFFFFFFFF != 1027 or target < ASSUMED_TABLE:
            continue
        relative = target - ASSUMED_TABLE
        if relative % 8 == 0 and relative // 8 in indices:
            index = relative // 8
            values[index] = addend & 0xFFFFFFFFFFFFFFFF
            relocated.add(index)

    bad = [{"index": i, "slot": hex(ASSUMED_TABLE + i * 8),
            "value": hex(values[i]), "relocated": i in relocated}
           for i in range(35) if values[i] and not executable(values[i])]
    abstract_bad = [{"index": i, "value": hex(values[i])}
                    for i in abstract_indices if values[i] and not executable(values[i])]
    return {
        "metadata_methods": n, "assumed_table": hex(ASSUMED_TABLE),
        "prefix_nonzero_nonexecutable": bad,
        "abstract_method_count": len(abstract_indices),
        "abstract_nonzero_count": sum(bool(values[i]) for i in abstract_indices),
        "abstract_nonexecutable_examples": abstract_bad[:10],
        "following_1000_executable_slots": sum(executable(values[i]) for i in range(n, n + 1000)),
        "boundary_slots": [{"index": i, "value": hex(values[i])}
                           for i in range(n - 3, n + 3)],
        "assumed_map_accepted": not bad and not abstract_bad,
        "limitations": [
            "Rejects this base/index formula, not every possible method binding.",
            "A continuing pointer region alone does not disprove a subarray boundary.",
            "Does not certify that the local binary and metadata belong to one game build.",
            "Does not identify a replacement method table or execute game code.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis-dir", type=Path, default=ANALYSIS)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = audit(args.analysis_dir)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("Assumed table:", result["assumed_table"])
        print("Non-code values in first 35 slots:", len(result["prefix_nonzero_nonexecutable"]))
        for example in result["prefix_nonzero_nonexecutable"][:6]:
            print(" ", example)
        print("Abstract method slots nonzero:", result["abstract_nonzero_count"],
              "/", result["abstract_method_count"])
        print("Following 1000 slots pointing to executable segments:",
              result["following_1000_executable_slots"])
        print("ACCEPTED" if result["assumed_map_accepted"] else
              "REJECTED: metadata index cannot be used with this base as a certified code address")
    return int(args.check and not result["assumed_map_accepted"])


if __name__ == "__main__":
    raise SystemExit(main())
