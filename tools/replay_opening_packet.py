"""Decode the ABC opening envelope observed in the current client's real reader.

Only reads headers and the first signed-i32-length packet. Does not claim the
remaining frame stream is decoded, or that a file can be played without login.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from replay_parser import dotnet_string  # noqa: E402


def opening_packet(data: bytes, references: dict | None = None) -> dict:
    pos = 0
    versions = []
    for _ in range(4):
        value, pos = dotnet_string(data, pos, "version/build")
        versions.append(value)
    if pos + 17 > len(data):
        raise ValueError("Truncated hero/time/map header")
    pos += 17  # u32 hero, i64 timestamp, u8 map type, u32 map ID
    for _ in range(2):
        _, pos = dotnet_string(data, pos, "user header")
    if pos + 22 > len(data):
        raise ValueError("Truncated rank/extended header or packet length")
    pos += 5  # u8 rank grade + u32 rank class
    extra, guide_level, guide_related, total_frames = struct.unpack_from("<IiBI", data, pos)
    pos += 13
    length = struct.unpack_from("<i", data, pos)[0]
    start = pos + 4
    end = start + abs(length)
    if length >= 0 or abs(length) < 16:
        raise ValueError("Opening packet is not a negative-length CSPkg envelope")
    if end > len(data):
        raise ValueError("Opening packet extends beyond file")
    msg_id = struct.unpack_from(">I", data, start)[0]
    result = {
        "versions": versions[:2], "builds": versions[2:],
        "extended_header_u32": extra, "guide_level": guide_level,
        "guide_related_flag": guide_related, "total_frame_header": total_frames,
        "length_offset": pos, "signed_i32_length": length,
        "body_offset": start, "body_bytes": abs(length), "body_end": end,
        "message_id": msg_id, "bytes_after_opening": len(data) - end,
        "accepted_by_observed_GetBeginLoadMsg_id_check": msg_id in (0x433, 0x1F42),
        "limitations": "Envelope and route-specific ID check only; no CSPkg body, frames, or actual playback executed.",
    }
    if references is not None:
        # The observed comparison strips the last app-version component and
        # compares the resource-version string exactly. No version bypass.
        result["current_version_references_match"] = (
            versions[0].rsplit(".", 1)[0] == references["current_app_version_reference"]
            and versions[1] == references["current_resource_version_reference"])
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--client-references", type=Path)
    args = parser.parse_args()
    references = json.loads(args.client_references.read_text(encoding="utf-8")) if args.client_references else None
    rows = []
    for path in args.files:
        try:
            rows.append({"file": path.name, **opening_packet(path.read_bytes(), references)})
        except (ValueError, struct.error) as exc:
            rows.append({"file": path.name, "error": str(exc)})
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return int(any("error" in row for row in rows))


if __name__ == "__main__":
    raise SystemExit(main())
