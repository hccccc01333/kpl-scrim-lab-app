"""Index observed ID1075/ID1051 ABC records without simulating their commands.

ID1075 (multiplayer): signed i32 LE lengths; negative for CSPkg, positive for
frame records with a BE u32 sequence and BE u16 size, one record per game
frame.

ID1051 (single game, docs 5.133): the opening CSPkg is followed by per-entry
records `[i32 len][u32 seq][payload = len bytes]`; the u32 is the game frame
number (repeats across the entries of one frame; max matches the header's
totalFrameNum on every sample). Entry-level command semantics for the old
builds are not decoded and stay raw.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.replay_opening_packet import opening_packet  # noqa: E402


def _iter_1075(data: bytes, header: dict):
    pos = header["length_offset"]
    previous = 0
    while pos < len(data):
        if pos + 4 > len(data):
            raise ValueError(f"Truncated record length at {pos}")
        length = struct.unpack_from("<i", data, pos)[0]
        start = pos + 4
        end = start + abs(length)
        if length == 0 or end > len(data):
            raise ValueError(f"Invalid record extent at {pos}: {length}")
        record = {"offset": pos, "payload_offset": start,
                  "payload_bytes": abs(length), "end": end}
        if length < 0:
            if -length < 16:
                raise ValueError(f"Short CSPkg header at {pos}")
            record.update(kind="cs", message_id=struct.unpack_from(">I", data, start)[0])
        else:
            if length < 6:
                raise ValueError(f"Short frame header at {pos}")
            sequence, size = struct.unpack_from(">IH", data, start)
            if size != length - 6:
                raise ValueError(f"Frame payload size mismatch at {pos}: {size} != {length - 6}")
            if sequence != previous + 1:
                raise ValueError(f"Nonconsecutive frame sequence at {pos}: {previous} -> {sequence}")
            previous = sequence
            record.update(kind="frame", sequence=sequence, command_offset=start + 6,
                          command_bytes=size)
        yield record
        pos = end


EVENT_SUBTYPES = {
    0x80: "frame_commands",
    0x81: "directional_skill",
    0x82: "aim_position",
    0x83: "facing_angle",
    0x84: "kill_notice",
    0x85: "buy_equip",
    0x86: "rare",
    0x87: "skill_levelup",
}


def _decode_cc_states(buffer: bytes):
    """`02 key val` repeated = a key-value state broadcast; else None (docs 5.135)."""
    if len(buffer) < 3 or len(buffer) % 3 or buffer[0] != 0x02:
        return None
    states = {}
    for i in range(0, len(buffer), 3):
        if buffer[i] != 0x02:
            return None
        states[f"{buffer[i + 1]:02x}"] = buffer[i + 2]
    return states


def decode_1051_entry(payload: bytes) -> dict:
    """Decode one ID1051 entry payload into its command-layer shape (docs 5.134-5.136).

    Every payload = [message][const:u32BE] where the trailing u32 is a
    per-file constant. Messages: `01 00 <cc-buffer>` (the CC/TLV family also
    seen in ID1075 BOOTFRAP1, obj 0x0100; `02 key val ...` chains decode to a
    key-value state broadcast) or `02 <subtype> <data>` with the 0x02-channel
    subtypes of the docs 5.93 dictionary. Structured fields: 0x83 = POV hero
    facing angle (signed i16BE degrees + rolling index), 0x87 = skill level-up
    (actor u16BE + skill slot + level index), 0x85 = the same buy echo as
    docs 5.130 (equip u16BE + pad + object + flag), 0x82 = aim position with
    an i32BE world-coordinate pair (docs 5.145; the former "mid" i16 was y's
    high half). Unmatched shapes return kind unknown instead of guessing.
    """
    if len(payload) < 5:
        return {"kind": "unknown", "raw": payload.hex(), "const": None}
    const = int.from_bytes(payload[-4:], "big")
    body = payload[:-4]
    if body[:2] == b"\x01\x00":
        entry = {"kind": "cc", "buffer": body[2:].hex(), "const": const}
        states = _decode_cc_states(body[2:])
        if states is not None:
            entry["states"] = states
        return entry
    if body[0] == 0x02 and len(body) >= 2:
        subtype = body[1]
        data = body[2:]
        entry = {"kind": "event", "subtype": subtype,
                 "name": EVENT_SUBTYPES.get(subtype, "unknown"),
                 "data": data.hex(), "const": const}
        if subtype == 0x83 and len(data) >= 3:
            entry["angle_deg"] = int.from_bytes(data[0:2], "big", signed=True)
            entry["index"] = data[2]
        elif subtype == 0x87 and len(data) >= 4:
            entry["actor"] = int.from_bytes(data[2:4], "big")
            entry["skill"] = data[4]
            entry["level_index"] = data[5]
        elif subtype == 0x85 and len(data) >= 2:
            entry["equip_id"] = int.from_bytes(data[0:2], "big")
            # The POV object byte sits at data[4] or data[5] depending on the
            # build; the remaining bytes stay raw instead of claiming fields.
            entry["rest"] = data[2:].hex()
        elif subtype == 0x82 and len(data) >= 11:
            # data = [03][x:i32BE][y:i32BE][counter:u16BE]...; the former
            # "mid" i16 field is the high half of y (sign extension).
            entry["x"] = int.from_bytes(data[1:5], "big", signed=True)
            entry["y"] = int.from_bytes(data[5:9], "big", signed=True)
            entry["counter"] = int.from_bytes(data[9:11], "big")
        elif subtype == 0x80 and len(data) >= 12:
            # Old-build hero-action command (docs 5.111): cmdType is a
            # hero-specific action id, not a global move/attack/skill enum.
            entry["cmd_type"] = int.from_bytes(data[0:2], "little")
            entry["value"] = int.from_bytes(data[2:4], "little")
            entry["actor"] = int.from_bytes(data[4:6], "little")
            entry["cmd_seq"] = int.from_bytes(data[6:10], "little")
            entry["flag"] = int.from_bytes(data[10:12], "little")
        return entry
    return {"kind": "unknown", "raw": payload.hex(), "const": const}


def _iter_1051(data: bytes, header: dict):
    pos = header["length_offset"] + 4 + header["body_bytes"]
    previous = 0
    while pos < len(data):
        if pos + 8 > len(data):
            raise ValueError(f"Truncated entry header at {pos}")
        length = struct.unpack_from("<i", data, pos)[0]
        if length < 0:
            raise ValueError(f"Negative entry length at {pos}: {length}")
        sequence = struct.unpack_from(">I", data, pos + 4)[0]
        if sequence < previous:
            raise ValueError(f"Non-monotonic entry frame at {pos}: {previous} -> {sequence}")
        previous = sequence
        end = pos + 8 + length
        if end > len(data):
            raise ValueError(f"Entry payload overflow at {pos}: {length}")
        payload = data[pos + 8:end]
        yield {"kind": "entry", "offset": pos, "payload_offset": pos + 8,
               "payload_bytes": length, "end": end, "sequence": sequence,
               "decoded": decode_1051_entry(payload)}
        pos = end


def iter_records(data: bytes):
    header = opening_packet(data)
    route = header["message_id"]
    if route == 1075:
        yield from _iter_1075(data, header)
    elif route == 1051:
        yield {"kind": "cs", "message_id": 1051,
               "offset": header["length_offset"], "payload_offset": header["body_offset"],
               "payload_bytes": header["body_bytes"], "end": header["body_end"]}
        yield from _iter_1051(data, header)
    else:
        raise ValueError(f"Only observed ID1075/ID1051 streams supported; got ID{route}")


def audit(data: bytes) -> dict:
    header = opening_packet(data)
    frames = 0
    entries = 0
    commands = 0
    last_sequence = 0
    packets = []
    event_types = collections.Counter()
    for record in iter_records(data):
        if record["kind"] == "frame":
            frames += 1
            commands += record["command_bytes"]
            last_sequence = record["sequence"]
        elif record["kind"] == "entry":
            entries += 1
            last_sequence = record["sequence"]
            decoded = record.get("decoded") or {}
            if decoded.get("kind") == "event":
                event_types[decoded["name"]] += 1
            elif decoded.get("kind") == "cc":
                event_types["cc"] += 1
            else:
                event_types["unknown"] += 1
        else:
            packets.append(record)
    result = {"sha256": hashlib.sha256(data).hexdigest(), "file_bytes": len(data),
              "versions": header["versions"], "builds": header["builds"],
              "route": header["message_id"],
              "total_frame_header": header["total_frame_header"],
              "last_sequence": last_sequence,
              "cs_packets": packets, "consumed_to_eof": True}
    if header["message_id"] == 1075:
        result.update({"frame_records": frames, "command_bytes": commands,
                       "limitations": "Record boundaries and sequence only; commands, world state and playback unverified. Header totalFrame may differ from record count."})
    else:
        result.update({"entry_records": entries, "entry_types": dict(event_types),
                       "limitations": "Container and entry-shape indexing (docs 5.134): entries decode to "
                                      "the 0x02-channel event family (0x80 frame commands, 0x84 kill notices, "
                                      "0x85 buy, ...) and 01/00 CC buffers; per-event field semantics for the "
                                      "old builds stay raw. No playback."})
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()
    reports = []
    for path in args.paths:
        files = sorted(path.rglob("*.abc")) if path.is_dir() else [path]
        for file in files:
            try:
                reports.append({"file": str(file), **audit(file.read_bytes())})
            except (ValueError, struct.error) as exc:
                reports.append({"file": str(file), "error": str(exc)})
    print(json.dumps(reports, ensure_ascii=False, indent=2))
    return int(any("error" in report for report in reports))


if __name__ == "__main__":
    raise SystemExit(main())
