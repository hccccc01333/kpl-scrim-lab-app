"""Resolve current CSPkg selectors from captured .cctor code and compressed defaults.

Reads existing captures only. Cross-checks immediate dictionary registrations
against CSProtocol CLASS_ID constants; optionally searches ABC for a bounded
negative-i32 CSPkg envelope with the resolved settlement message ID.
"""
from __future__ import annotations

import argparse
import collections
import json
import struct
from pathlib import Path

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM


def compressed_i32(blob: bytes, offset: int) -> int:
    if not 0 <= offset < len(blob):
        raise ValueError("Compressed integer offset outside data")
    head = blob[offset]
    width = 1 if head < 0x80 else 2 if head < 0xC0 else 4 if head < 0xE0 else 5
    if offset + width > len(blob):
        raise ValueError("Truncated compressed integer")
    if head < 0x80:
        value = head
    elif head < 0xC0:
        value = ((head & 0x3F) << 8) | blob[offset + 1]
    elif head < 0xE0:
        tail = blob[offset + 1:offset + 4]
        if len(tail) != 3:
            raise ValueError("Truncated compressed integer")
        value = ((head & 0x1F) << 24) | int.from_bytes(tail, "big")
    elif head == 0xF0:
        value = struct.unpack_from("<I", blob, offset + 1)[0]
    else:
        raise ValueError(f"Unsupported compressed integer marker {head:#x}")
    return (value >> 1) ^ -(value & 1)


def metadata_ids(blob: bytes) -> tuple[dict, dict]:
    if struct.unpack_from("<II", blob) != (0xFAB11BAF, 29):
        raise ValueError("Expected metadata v29")
    so, ss = struct.unpack_from("<II", blob, 24)
    to, ts = struct.unpack_from("<II", blob, 160)
    fo, _ = struct.unpack_from("<II", blob, 96)
    do, ds = struct.unpack_from("<II", blob, 64)
    vo, vs = struct.unpack_from("<II", blob, 72)
    defaults = {f: i for f, _, i in struct.iter_unpack("<iii", blob[do:do + ds])}

    def string(index: int) -> str:
        return blob[so + index:blob.index(b"\0", so + index, so + ss)].decode("utf-8")

    classes = collections.defaultdict(list)
    enums = {}
    for row in struct.iter_unpack("<16i8H2I", blob[to:to + ts]):
        name, namespace = string(row[0]), string(row[1])
        if namespace != "CSProtocol":
            continue
        for field in range(row[8], row[8] + row[18]):
            fname = string(struct.unpack_from("<i", blob, fo + field * 12)[0])
            idx = defaults.get(field, -1)
            if not 0 <= idx < vs:
                continue
            if fname == "CLASS_ID":
                classes[compressed_i32(blob, vo + idx)].append(name)
            elif name == "CSCMD_ID_DEF":
                enums[fname] = compressed_i32(blob, vo + idx)
    return dict(classes), enums


def registrations(code: bytes, address: int) -> list[dict]:
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    regs = {}
    rows = []
    for ins in md.disasm(code, address):
        if ins.mnemonic == "mov" and ins.op_str.startswith(("w1, #", "w2, #")):
            reg, value = ins.op_str.split(", #")
            regs[reg] = int(value, 0)
        elif ins.mnemonic == "movk" and ins.op_str.startswith(("w1, #", "w2, #")):
            parts = ins.op_str.split(", ")
            reg, value = parts[0], int(parts[1][1:], 0)
            shift = int(parts[2].split("#")[1], 0) if len(parts) > 2 else 0
            regs[reg] = (regs.get(reg, 0) & ~(0xFFFF << shift)) | value << shift
        elif ins.mnemonic == "blr":
            if "w1" in regs and "w2" in regs:
                rows.append({"msg_id": regs["w1"], "class_id": regs["w2"],
                             "call": hex(ins.address)})
            regs.clear()
        elif ins.mnemonic == "ret":
            break
        elif ins.op_str.startswith(("w1,", "w2,")):
            regs.pop(ins.op_str.split(",")[0], None)
    if len(rows) != len({r["msg_id"] for r in rows}):
        raise ValueError("Duplicate selector registrations; manual review required")
    return rows


def resolve(folder: Path) -> tuple[list[dict], dict]:
    methods = json.loads((folder / "methods.json").read_text(encoding="utf-8"))
    method = next(r for r in methods["hits"] if r["owner"] == "CSPkgBody" and r["method"] == ".cctor")
    classes, enums = metadata_ids((folder / "metadata.bin").read_bytes())
    rows = registrations((folder / "CSPkgBody_cctor_full.bin").read_bytes(), int(method["pointer"], 16))
    for row in rows:
        row["types"] = classes.get(row["class_id"], [])
        if len(row["types"]) != 1:
            raise ValueError(f'Class ID {row["class_id"]} has no unique protocol type')
    return rows, enums


def scan_envelopes(data: bytes, msg_id: int, max_version: int = 0x2F65) -> list[dict]:
    needle = struct.pack(">I", msg_id)
    pos = 0
    hits = []
    while True:
        pos = data.find(needle, pos)
        if pos < 0:
            return hits
        if pos >= 4 and pos + 16 <= len(data):
            length = struct.unpack_from("<i", data, pos - 4)[0]
            version = struct.unpack_from(">i", data, pos + 4)[0]
            if length <= -16 and pos - length <= len(data) and 0 < version <= max_version:
                hits.append({"offset": pos, "length": -length, "version": version})
        pos += 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--scan-dir", type=Path)
    args = parser.parse_args()
    rows, enums = resolve(args.capture)
    selected = [r for r in rows if r["msg_id"] in (1051, 1075, 1077, 1082, 1126, 1251, 8002)
                or "SETTLE_RESULT_NTF" in r["types"][0]]
    result = {"registered": len(rows), "unique_type_matches": len(rows), "selected": selected,
              "game_over_enum_id": enums["SCID_GAME_OVER_RSP"],
              "token_settle_enum_id": enums["SCID_TOKEN_GAME_SETTLE_RESULT_NTF"]}
    if args.scan_dir:
        reports = []
        for path in sorted(args.scan_dir.rglob("*.abc")):
            data = path.read_bytes()
            reports.append({"file": str(path),
                            "game_over_candidates": scan_envelopes(data, result["game_over_enum_id"]),
                            "token_settle_candidates": scan_envelopes(data, result["token_settle_enum_id"])})
        result["envelope_scan"] = reports
        result["scan_limitation"] = "Only this captured build's ID/framing; no absence claim for other builds, compression, or embedded formats."
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
