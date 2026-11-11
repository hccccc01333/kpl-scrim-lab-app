#!/usr/bin/env python3
"""Extract the exact per-frame command payloads from a `.abc` replay.

The CS slot0 probe (`host/src/h5_probe.c`) consumes `frames.bin` +
`index.tsv`: `frames.bin` is the byte-for-byte concatenation of each frame
record's command buffer (`szInfoBuff`, i.e. the `CSDT_FRAPBOOT_INFO` bytes),
and `index.tsv` gives `(index, sequence, offset, length, entries, parsed,
abc_offset)` for every extracted frame.

This tool does not transform, align, re-encode, or pad payloads.  It uses
`tools.replay_record_stream` for record boundaries and
`tools.replay_frame_commands` only to record whether the payload parses as the
current BOOTFRAP container; a parse failure still writes the exact bytes.

Read-only: only reads the `.abc` and writes the requested output directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.replay_frame_commands import decode_commands  # noqa: E402
from tools.replay_opening_packet import opening_packet  # noqa: E402
from tools.replay_record_stream import iter_records  # noqa: E402

SCHEMA = "kpl-h5-frame-payloads-v1"


def extract(path: Path, out_dir: Path, start: int, limit: int, stride: int,
            require_parsed: bool) -> dict:
    data = path.read_bytes()
    opening = opening_packet(data)
    records = list(iter_records(data))
    frames = [r for r in records if r["kind"] == "frame"]
    if not frames:
        raise ValueError("no ID1075 frame records found")

    selected = []
    for index, record in enumerate(frames):
        if start and index < start:
            continue
        if stride > 1 and (index - start) % stride:
            continue
        if limit and len(selected) >= limit:
            break
        selected.append((index, record))
    if not selected:
        raise ValueError("frame selection is empty")

    out_dir.mkdir(parents=True, exist_ok=True)
    blob = bytearray()
    rows = []
    decoded_count = zero_command = failed = 0
    first_sequence = selected[0][1]["sequence"]
    last_sequence = selected[-1][1]["sequence"]
    for index, record in selected:
        payload = data[record["command_offset"]:record["end"]]
        offset = len(blob)
        blob += payload
        entries = None
        parsed = 0
        try:
            decoded = decode_commands(payload)
            entries = len(decoded)
            parsed = 1
            decoded_count += 1
            if entries == 0:
                zero_command += 1
        except ValueError:
            failed += 1
        if require_parsed and not parsed:
            raise ValueError(f"frame {record['sequence']} failed structural parse")
        rows.append((index, record["sequence"], offset, len(payload),
                     -1 if entries is None else entries, parsed,
                     record["command_offset"]))

    (out_dir / "frames.bin").write_bytes(bytes(blob))
    lines = ["# index\tsequence\toffset\tlength\tentries\tparsed\tabc_offset"]
    for row in rows:
        lines.append("\t".join(str(value) for value in row))
    (out_dir / "index.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")

    header = {
        "schema": SCHEMA,
        "source": {
            "file": str(path),
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "versions": opening["versions"],
            "builds": opening["builds"],
            "route": opening["message_id"],
            "total_frame_header": opening["total_frame_header"],
        },
        "selection": {"start": start, "limit": limit, "stride": stride,
                      "require_parsed": require_parsed},
        "frames": {
            "records": len(frames),
            "extracted": len(rows),
            "bytes": len(blob),
            "first_sequence": first_sequence,
            "last_sequence": last_sequence,
            "zero_command": zero_command,
            "structurally_parsed": decoded_count,
            "structural_failures": failed,
        },
        "output": {
            "frames_bin": str(out_dir / "frames.bin"),
            "index_tsv": str(out_dir / "index.tsv"),
            "frames_bin_sha256": hashlib.sha256(bytes(blob)).hexdigest(),
        },
        "notes": [
            "Payload bytes are copied verbatim from the .abc frame record; no translation or alignment.",
            "The payload is the CSDT_FRAPBOOT_INFO container, not a proven native CS TDR command stream.",
            "parsed=1 only means tools/replay_frame_commands decoded the BOOTFRAP container; it is not gameplay validation.",
            "entries=-1 means structural parsing failed; the bytes are still exact.",
        ],
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(header, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return header


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("abc", type=Path)
    parser.add_argument("--out-dir", type=Path,
                        default=ROOT / "host/build/frames/20261102_161129")
    parser.add_argument("--start", type=int, default=0,
                        help="0-based frame-record index to start at")
    parser.add_argument("--limit", type=int, default=0, help="0 = all")
    parser.add_argument("--stride", type=int, default=1)
    parser.add_argument("--require-parsed", action="store_true")
    args = parser.parse_args()
    if args.start < 0 or args.limit < 0 or args.stride < 1:
        parser.error("start/limit must be >= 0 and stride >= 1")
    header = extract(args.abc, args.out_dir, args.start, args.limit,
                     args.stride, args.require_parsed)
    print(json.dumps(header, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
