"""Parse a .ope operator stream with the observed 12.1.1.x record layouts.

Newer resource versions (e.g. 12.1.1.26) move the raw-DEFLATE payload start
from 0x8B to 0x91, so this tool scans 0x80..0xA0 instead of assuming one
offset. It does not claim field semantics beyond the inferred layouts; it
reports tentative records and ambiguities.

Usage:
  python tools/ope_parse.py --file data/replays/samples/....ope
  python tools/ope_parse.py --file stream.bin --stream
  python tools/ope_parse.py --file ....ope --json out.json
"""
from __future__ import annotations

import argparse
import json
import sys
import zlib
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AN = ROOT / "data" / "replays" / "_analysis"
sys.path.insert(0, str(AN / "tools"))
sys.path.insert(0, str(ROOT))

import operator_stream as OS  # noqa: E402

VALID_TYPES = set(OS.LAYOUTS)


def unwrap(raw: bytes) -> bytes:
    if raw[:1] == b"\x01":
        return zlib.decompressobj(-15).decompress(raw[1:])
    return raw


def find_payload(inner: bytes) -> tuple[int, bytes] | None:
    """Find a raw-DEFLATE member that decompresses to a type-valid stream."""
    best = None
    for off in range(0x80, 0xA1):
        try:
            data = zlib.decompressobj(-15).decompress(inner[off:])
        except Exception:
            continue
        if len(data) < 64 or data[0] not in VALID_TYPES:
            continue
        # Prefer the longest successful decode; ties go to the first offset.
        if best is None or len(data) > len(best[1]):
            best = (off, data)
    return best


def parse_stream(stream: bytes, layout_size: int = 123, header: int = 0):
    OS.HEADER_BYTES = header
    reachable = OS._reachable(stream, layout_size)
    try:
        records, ambiguities = OS._resolve(stream, reachable, layout_size)
        return records, ambiguities, max(reachable) if reachable else 0
    except Exception:
        return None, None, max(reachable) if reachable else 0


def semantic_issues(records) -> list[str]:
    """Obvious impossibilities that mean the boundary path is not trustworthy."""
    issues = []
    for record in records:
        if record["tentative"]:
            continue
        name = record["typeName"]
        fields = record["fields"]
        checks = (
            ("slotType", 0, 31),
            ("slot", 0, 31),
            ("degree", 0, 360),
            ("unityFrame", 0, 10_000_000),
            ("skillId", 0, 1_000_000),
            ("skillSeq", 0, 1_000_000),
        )
        for key, low, high in checks:
            value = fields.get(key)
            if isinstance(value, int) and not low <= value <= high:
                issues.append(f"{name}.{key}={value}@{record['offset']:#x}")
                break
        if len(issues) >= 12:
            break
    return issues


def summarize(records, ambiguities, stream_len, wall):
    types = Counter(record["typeName"] for record in records)
    confirmed = [record for record in records if not record["tentative"]]
    frames = [record["fields"]["frame"] for record in confirmed
              if "frame" in record["fields"]]
    unity = [record["fields"]["unityFrame"] for record in confirmed
             if "unityFrame" in record["fields"]]
    issues = semantic_issues(records)
    return {
        "decoded": True,
        "streamSize": stream_len,
        "recordCount": len(records),
        "confirmedCount": len(confirmed),
        "tentativeCount": len(records) - len(confirmed),
        "ambiguousChoices": ambiguities,
        "semanticOk": not issues,
        "semanticIssues": issues,
        "typeCounts": dict(sorted(types.items())),
        "frameRange": [min(frames), max(frames)] if frames else None,
        "unityFrameRange": [min(unity), max(unity)] if unity else None,
        "wall": wall,
        "note": "record boundaries from the observed layout set; field names "
                "beyond frame/unityFrame/eventId are inferred, not ground truth",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    parser.add_argument("--stream", action="store_true", help="file is already a decoded stream")
    parser.add_argument("--json", default=None)
    args = parser.parse_args()

    path = Path(args.file)
    raw = path.read_bytes()
    if args.stream:
        stream = raw
        payload_off = None
        inner_size = None
    else:
        inner = unwrap(raw)
        found = find_payload(inner)
        if found is None:
            print(f"{path}: no raw-DEFLATE operator payload found in 0x80..0xA0")
            return 1
        payload_off, stream = found
        inner_size = len(inner)

    records, ambiguities, wall = parse_stream(stream)
    if records is None:
        print(f"{path}: parsed to wall 0x{wall:x} (type 0x{stream[wall]:02x})")
        return 1

    summary = summarize(records, ambiguities, len(stream), wall)
    summary["file"] = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
    summary["payloadOffset"] = payload_off
    summary["innerSize"] = inner_size
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if args.json:
        Path(args.json).write_text(json.dumps(summary, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
        print("out:", args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
