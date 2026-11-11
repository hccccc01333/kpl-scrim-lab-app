"""Check replay reverse-engineering evidence without loading code or contacting a device.

Prints metadata identity checks, ELF mappings and bounded code-anchor comparisons.
Method names are discovery leads; this tool does not certify method-pointer slots.
Run: python tools/replay_evidence_check.py --check
An exit status of 1 means the old snapshot must not validate the current metadata.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS = ROOT / "data/replays/_analysis"


def metadata(blob: bytes) -> dict:
    if struct.unpack_from("<II", blob) != (0xFAB11BAF, 29):
        raise ValueError("Expected IL2CPP metadata v29")

    def table(pair: int, stride: int) -> tuple[int, int]:
        start, size = struct.unpack_from("<II", blob, pair * 8)
        if size % stride or start + size > len(blob):
            raise ValueError(f"Invalid metadata table {pair}")
        return start, size // stride

    strings_start, strings_size = table(3, 1)
    strings = blob[strings_start:strings_start + strings_size]

    def name(index: int) -> str:
        if not 0 <= index < len(strings):
            raise ValueError("Invalid string index")
        end = strings.find(b"\0", index)
        if end < 0:
            raise ValueError("Unterminated metadata string")
        return strings[index:end].decode("utf-8")

    method_start, method_count = table(6, 32)
    param_start, param_count = table(11, 12)
    type_start, type_count = table(20, 88)
    targets = {
        "GameReplayModule": {"BeginReplay", "GetBeginLoadMsg", "RetriveBeginLoad",
                             "SkipReadReplayHead", "CheckReplayVersion",
                             "ListReplayFiles", "ScanReplayFiles", "GetReplayInfoByFilePath"},
        "SGW": {"StartHostReplay", "PureReplayStart", "StartLevel"},
    }
    leads = []
    for i in range(type_count):
        row = struct.unpack_from("<16i8H2I", blob, type_start + i * 88)
        type_name = name(row[0])
        if type_name not in targets:
            continue
        first, count = row[9], row[16]
        if first < 0 or first + count > method_count:
            raise ValueError("Invalid method range")
        for index in range(first, first + count):
            method = struct.unpack_from("<6i4H", blob, method_start + index * 32)
            method_name = name(method[0])
            if method_name not in targets[type_name]:
                continue
            first_param, count_params = method[3], method[9]
            if count_params and (first_param < 0 or first_param + count_params > param_count):
                raise ValueError("Invalid parameter range")
            params = [name(struct.unpack_from("<i", blob, param_start + p * 12)[0])
                      for p in range(first_param, first_param + count_params)]
            leads.append({"type": type_name, "method": method_name,
                          "index": index, "parameters": params})
    return {"method_count": method_count, "type_count": type_count,
            "sha256": hashlib.sha256(blob).hexdigest(), "leads": leads}


def elf_loads(blob: bytes) -> list[dict]:
    if blob[:6] != b"\x7fELF\x02\x01":
        raise ValueError("Expected little-endian ELF64")
    phoff = struct.unpack_from("<Q", blob, 32)[0]
    stride, count = struct.unpack_from("<HH", blob, 54)
    if stride < 56 or phoff + stride * count > len(blob):
        raise ValueError("Invalid program headers")
    result = []
    for i in range(count):
        kind, flags, off, va, _, size, memsize, _ = struct.unpack_from(
            "<II6Q", blob, phoff + i * stride)
        if kind == 1:
            result.append({"va": hex(va), "file_offset": hex(off),
                           "delta": hex(va - off), "file_size": size,
                           "memory_size": memsize, "flags": flags})
    return result


def anchor_comparison(blob: bytes, snapshot: bytes, va: int) -> list[dict]:
    """Compare fixed candidate offsets; instruction decodability is not a validator."""
    rows = []
    for delta in (0x1000, 0x51000):
        off = va - delta
        raw = blob[off:off + len(snapshot)]
        if off < 0 or len(raw) != len(snapshot):
            raise ValueError("Code anchor outside ELF")
        pages = []
        for start in range(0, len(snapshot), 0x1000):
            end = min(start + 0x1000, len(snapshot))
            plain = xor = 0
            for pos in range(start, end - 3, 4):
                src, dst = raw[pos:pos + 4], snapshot[pos:pos + 4]
                plain += src == dst
                xor += bytes(x ^ 0xE3 for x in src) == dst
            pages.append({"relative_page": hex(start), "words": (end - start) // 4,
                          "plain_matches": plain, "xor_e3_matches": xor})
        rows.append({"candidate_delta": hex(delta), "pages": pages})
    return rows


def audit(root: Path) -> dict:
    current_blob = (root / "global-metadata.dat").read_bytes()
    old_blob = (root / "runtime_dump/metadata_mem.bin").read_bytes()
    current, old = metadata(current_blob), metadata(old_blob)
    prefix_equal = old_blob[:len(current_blob)] == current_blob
    binary = (root / "libil2cpp.so").read_bytes()
    anchors = []
    for filename, va in (("code_blob.bin", 0x5976000), ("code_5977000.bin", 0x5977000)):
        data = (root / "runtime_dump" / filename).read_bytes()
        if not data or len(data) % 4:
            raise ValueError("Invalid code anchor length")
        anchors.append({"file": filename, "historical_va_label": hex(va),
                        "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                        "comparisons": anchor_comparison(binary, data, va)})
    return {
        "current_metadata": current,
        "historical_metadata": {k: v for k, v in old.items() if k != "leads"},
        "snapshot_metadata_prefix_matches_current": prefix_equal,
        "cross_snapshot_index_validation_allowed": prefix_equal,
        "binary_sha256": hashlib.sha256(binary).hexdigest(),
        "elf_loads": elf_loads(binary), "code_anchors": anchors,
        "limitations": [
            "Different metadata does not by itself prove which game build produced each file.",
            "ELF mapping describes file segments; matching historical bytes is a local anchor only.",
            "No global offset correction or method-address mapping is certified.",
            "Metadata method names do not prove calls, file extensions, or account requirements.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis-dir", type=Path, default=ANALYSIS)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true", help="Print evidence as JSON")
    args = parser.parse_args()
    result = audit(args.analysis_dir)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("Current metadata methods:", result["current_metadata"]["method_count"])
        print("Historical metadata methods:", result["historical_metadata"]["method_count"])
        print("Metadata prefix matches:", result["snapshot_metadata_prefix_matches_current"])
        for anchor in result["code_anchors"]:
            for candidate in anchor["comparisons"]:
                counts = [f'{p["plain_matches"]}/{p["xor_e3_matches"]}/{p["words"]}'
                          for p in candidate["pages"]]
                print(anchor["file"], candidate["candidate_delta"],
                      "plain/xor/words by page:", ", ".join(counts))
        print("Method leads (addresses NOT certified):")
        for lead in result["current_metadata"]["leads"]:
            print(f'  {lead["index"]} {lead["type"]}.{lead["method"]}'
                  f'({", ".join(lead["parameters"])})')
        print("PASS" if result["cross_snapshot_index_validation_allowed"] else
              "BLOCKED: historical snapshot cannot validate current method indices")
    return int(args.check and not result["cross_snapshot_index_validation_allowed"])


if __name__ == "__main__":
    raise SystemExit(main())
