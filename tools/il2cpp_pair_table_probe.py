"""Probe .rodata/.data (code_address, method_index) pair tables.

These tables are NOT the old .data index formula.  They map metadata method
indices to code-range labels/thunks; class clusters are visible, but entries
are not guaranteed to be method-body starts.  Read-only, no execution.

Run: python tools/il2cpp_pair_table_probe.py
"""
from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

from elftools.elf.elffile import ELFFile

from replay_evidence_check import ANALYSIS, metadata


def scan(path: Path) -> dict:
    blob = path.read_bytes()
    with path.open("rb") as handle:
        elf = ELFFile(handle)
        loads = [(p["p_vaddr"], p["p_vaddr"] + p["p_filesz"], p["p_offset"], p["p_flags"])
                 for p in elf.iter_segments() if p["p_type"] == "PT_LOAD"]
        text = [(a, b) for a, b, _, flags in loads if flags & 1]
        sections = []
        for name in (".rodata", ".data", ".data.rel.ro"):
            section = elf.get_section_by_name(name)
            if section is None or section["sh_type"] == "SHT_NOBITS":
                continue
            sections.append((name, section.data(), section["sh_addr"]))

    def is_text(value: int) -> bool:
        return any(a <= value < b for a, b in text)

    info = metadata((path.parent / "global-metadata.dat").read_bytes())
    method_count = info["method_count"]
    index_to_address: dict[int, int] = {}
    duplicates = 0
    pairs = 0
    for _, data, _ in sections:
        for pos in range(0, len(data) - 7, 8):
            address, index = struct.unpack_from("<II", data, pos)
            if is_text(address) and index < method_count:
                pairs += 1
                if index in index_to_address:
                    duplicates += 1
                else:
                    index_to_address[index] = address

    def cluster(first: int, count: int) -> dict:
        entries = [(i, index_to_address[i]) for i in range(first, first + count)
                   if i in index_to_address]
        return {"first": first, "count": count, "mapped": len(entries),
                "first_address": hex(entries[0][1]) if entries else None,
                "last_address": hex(entries[-1][1]) if entries else None}

    types = {row["type"]: row for row in info.get("type_ranges", [])}
    return {
        "binary": path.name,
        "method_count": method_count,
        "pair_count": pairs,
        "mapped_methods": len(index_to_address),
        "coverage": round(len(index_to_address) / method_count, 6),
        "duplicate_indices": duplicates,
        "SGW": cluster(166627, 580),
        "GameReplayModule": cluster(227947, 104),
        "limitations": [
            "Pair entries are code-range labels/thunks, not certified method bodies.",
            "String.get_Length maps to 0xc217aa8, which is not the expected getter body.",
            "Addresses are static-file VAs; runtime relocation/patching is not modelled.",
            "Coverage is partial; absence is not evidence that a method has no pointer.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=ANALYSIS / "libil2cpp.so")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = scan(args.binary)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for key in ("method_count", "pair_count", "mapped_methods", "coverage",
                    "duplicate_indices", "SGW", "GameReplayModule"):
            print(f"{key}: {result[key]}")
        print("NOTE: pair entries are thunk/label candidates, not certified method bodies")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
