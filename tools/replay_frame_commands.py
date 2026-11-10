"""Decode a subset of the captured client's TDR frame-command schemas.

Every accepted frame must consume exactly its declared entry count and bytes.
Unsupported selectors reject the whole frame; no resynchronization or guessed
entry lengths. PLAYER_MOVE/PLAYER_ATTACK packed values are decoded into
(hero unit, seq, sign, direction); CC buffers and skill-target semantics stay
input-only: no world positions, no simulation.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import replay_time  # noqa: E402
from tools.replay_opening_packet import opening_packet  # noqa: E402
from tools.replay_record_stream import iter_records  # noqa: E402

# Current CSProtocol field order, using TDR big endian. These are the schemas
# observed in metadata and independently checked against complete frame extents.
CS_SCHEMAS = {
    128: ("USEOBJECTIVESKILL", "biBHI", ("slot", "object_id", "custom", "skill_seq", "drag_flag")),
    129: ("USEDIRECTIONALSKILL", "bhIiiiHB", ("slot", "degree", "object_id", "secondary_1", "secondary_2", "secondary_3", "skill_seq", "drag_flag")),
    130: ("USEPOSITIONSKILL", "biiHIB", ("slot", "target_x", "target_y", "skill_seq", "object_id", "drag_flag")),
    131: ("MOVE", "hB", ("degree", "seq")),
    132: ("BASEATTACK", "BI", ("start", "object_id")),
    133: ("BUYEQUIP", "HIB", ("equip_id", "object_id", "auto_buy")),
    134: ("SELLEQUIP", "BB", ("equip_index", "container_type")),
    135: ("LEARNSKILL", "IBBB", ("hero_object_id", "slot", "level", "auto_learn")),
    150: ("ROTATE", "hB", ("degree", "seq")),
    151: ("FRAME_HASH_CHECK", "Bii", ("source_type", "param_1", "param_2")),
}
BOOT_SCHEMAS = {
    3: ("ACNTSTATECHG", "IB", ("object_id", "state_change")),
    5: ("AISTATECHG", "BIii", ("type", "player_object_id", "display_flag", "display_delay_seconds")),
    6: ("GAMEOVERNTF", "B", ("win_camp",)),
    8: ("CAMPSTATE", "BB", ("camp", "state")),
    9: ("CAMP_SURRENDER", "B", ("camp",)),
    16: ("BEGIN_FRAME_EXTEND", "B", ("win_camp",)),
    18: ("PLAYER_MOVE", "H", ("packed_move",)),
    19: ("PLAYER_ATTACK", "B", ("packed_attack",)),
    20: ("PLAYER_ATTACKWITHOBJ", "BH", ("packed_attack", "target_object_id")),
}


class UnsupportedCommand(ValueError):
    pass


# Packed hero fields (BOOTFRAP 18/19/20), validated on 5247758 samples
# 20261101_182452 (2 human movers), 20261102_161129 and 20261102_163751
# (10 movers each): u16 = unit:5 | seq:2 | sign:1 | magnitude:8. The
# magnitude never exceeded 180 in 158k entries; larger values mean the
# layout does not hold for that sample and must stop the parse.
MOVE_MAGNITUDE_MAX = 180


def decode_move_info(packed: int) -> dict:
    if not 0 <= packed <= 0xFFFF:
        raise ValueError(f"packed move out of u16 range: {packed}")
    magnitude = packed & 0xFF
    if magnitude > MOVE_MAGNITUDE_MAX:
        raise ValueError(
            f"move magnitude {magnitude} exceeds confirmed maximum "
            f"{MOVE_MAGNITUDE_MAX}; packed-move layout unverified")
    sign = (packed >> 8) & 1
    return {"unit": packed >> 11, "seq": (packed >> 9) & 0b11,
            "sign": sign, "mag": magnitude,
            "dir_deg": -magnitude if sign else magnitude}


def decode_attack_byte(byte: int) -> dict:
    if not 0 <= byte <= 0xFF:
        raise ValueError(f"packed attack out of u8 range: {byte}")
    return {"unit": byte >> 3, "seq": (byte >> 1) & 0b11, "flag": byte & 1}


# Hero units in the input stream, observed on build 5247758: camp 1 slots
# map to units 8-12, camp 2 slots to units 16-20. Units 0-7 and 13-15 never
# carried a move or attack in any sample; their owners are unresolved.
UNIT_BASE_CAMP1 = 8
UNIT_BASE_CAMP2 = 16
UNITS_PER_CAMP = 5


def unit_roster_slot(unit: int):
    """Return (camp, slot) for a hero unit, or None when outside the mapped range."""
    if UNIT_BASE_CAMP1 <= unit < UNIT_BASE_CAMP1 + UNITS_PER_CAMP:
        return 1, unit - UNIT_BASE_CAMP1
    if UNIT_BASE_CAMP2 <= unit < UNIT_BASE_CAMP2 + UNITS_PER_CAMP:
        return 2, unit - UNIT_BASE_CAMP2
    return None


# dir_deg shares the client's directional-skill angle frame (docs 5.128:
# paired cast-vs-move median delta ≈ 0° over 400+ pairs, two matches) and the
# world frame is screen-like with +y pointing down (docs 5.128: 0x82 kind-2
# displacement bearings match move headings under (cos d, sin d), r≈0.5-0.58).
def world_vector(dir_deg: int) -> tuple[float, float]:
    """Unit world vector of an input direction, in native replay axes.

    Native axes match the skill-target/0x82 coordinate space: +x is screen
    east, +y is screen south. North is -y.
    """
    angle = math.radians(dir_deg)
    return (round(math.cos(angle), 4), round(math.sin(angle), 4))


def compass_bearing(dir_deg: int) -> float:
    """Compass bearing (0=north, clockwise) of an input direction.

    Blue base sits bottom-left of the minimap and the camera is unmirrored,
    so blue walking to lanes spans compass [0..90] and red [180..270]
    (docs 5.128 camp-arc evidence).
    """
    return (90.0 + dir_deg) % 360.0


# Frame→second calibration lives in replay_time.py so the product, the tools
# and replay_codec/ cannot drift apart again.  FRAME_RATE stays the documented
# §5.129 baseline (15 fps); the engine-measured 15.1515 fps is a separate
# constant there and is not used here until the record-stream sequence is
# proven to be the same counter as the engine frame number.
FRAME_RATE = replay_time.FPS


def battle_time(frame: int, first_frame: int = 1) -> float:
    """Approximate battle seconds for a record-stream frame number."""
    return replay_time.relative(frame, first_frame)


def decode_commands(data: bytes) -> list[dict]:
    pos = 0

    def take(fmt):
        nonlocal pos
        size = struct.calcsize(">" + fmt)
        if pos + size > len(data):
            raise ValueError(f"Truncated command field at {pos}")
        values = struct.unpack_from(">" + fmt, data, pos)
        pos += size
        return values

    count, = take("B")
    entries = []
    for _ in range(count):
        start = pos
        selector, = take("B")
        row = {"offset": start, "boot_type": selector}
        if selector == 1:
            obj, length = take("HH")
            if pos + length > len(data):
                raise ValueError(f"Truncated CC buffer at {pos}")
            row.update(name="CC", object_id=obj, buffer_hex=data[pos:pos + length].hex())
            pos += length
        elif selector == 2:
            obj, subtype = take("HB")
            if subtype not in CS_SCHEMAS:
                raise UnsupportedCommand(f"Unsupported CSSYNC selector {subtype}")
            name, fmt, fields = CS_SCHEMAS[subtype]
            row.update(name=name, object_id=obj, sync_type=subtype,
                       fields=dict(zip(fields, take(fmt))))
        elif selector == 18:
            name, fmt, fields = BOOT_SCHEMAS[selector]
            row.update(name=name, fields=dict(zip(fields, take(fmt))))
            row.update(decode_move_info(row["fields"]["packed_move"]))
        elif selector in (19, 20):
            name, fmt, fields = BOOT_SCHEMAS[selector]
            row.update(name=name, fields=dict(zip(fields, take(fmt))))
            row.update(decode_attack_byte(row["fields"]["packed_attack"]))
        elif selector in BOOT_SCHEMAS:
            name, fmt, fields = BOOT_SCHEMAS[selector]
            row.update(name=name, fields=dict(zip(fields, take(fmt))))
        else:
            raise UnsupportedCommand(f"Unsupported BOOTFRAP selector {selector}")
        row["bytes"] = pos - start
        entries.append(row)
    if pos != len(data):
        raise ValueError(f"Trailing command bytes: consumed {pos} of {len(data)}")
    return entries


def audit_commands(data: bytes) -> dict:
    header = opening_packet(data)
    counts = collections.Counter()
    errors = collections.Counter()
    examples = {}
    decoded = 0
    total = 0
    route = None
    for record in iter_records(data):
        if record["kind"] == "cs" and route is None:
            route = record["message_id"]
        if record["kind"] != "frame":
            continue
        total += 1
        try:
            entries = decode_commands(data[record["command_offset"]:record["end"]])
        except ValueError as exc:
            errors[str(exc)] += 1
            continue
        decoded += 1
        for row in entries:
            counts[row["name"]] += 1
            examples.setdefault(row["name"], {"frame": record["sequence"], **row})
    return {"route": route,
            "resource_version": header["versions"][1],
            "matches_captured_resource_version": header["versions"][1] == "12.1.1.26",
            "frame_records": total, "fully_parsed_frames": decoded,
            "unresolved_frames": total - decoded, "accepted_entry_counts": dict(counts),
            "errors": dict(errors), "examples": examples,
            "limitations": "Subset of current TDR schemas; older builds are exploratory. Unknown or malformed frames contribute no accepted entries. PLAYER_MOVE/PLAYER_ATTACK packed values decode to hero unit + signed direction (5247758 samples); CC buffers, move seq semantics and skill targets stay opaque/input-only. No simulation or gameplay-state validation."}


def events(data: bytes):
    """Yield input events indexed by recorded frame, without inferring game time."""
    for record in iter_records(data):
        if record["kind"] == "frame":
            for entry in decode_commands(data[record["command_offset"]:record["end"]]):
                yield {"frame": record["sequence"],
                       "file_offset": record["command_offset"] + entry["offset"], **entry}


def hero_inputs(data: bytes) -> dict:
    """One pass over the record stream: per-unit/per-entity stats and event lists.

    Robust to per-frame walls: a frame that fails to decode counts into
    unresolvedFrames and contributes nothing. Unit-keyed events (move/attack)
    use the packed hero unit; entity-keyed events (buy/learn/skill/cc) use the
    outer wObjID entity. No roster knowledge here; the caller joins names.
    """
    header = None
    try:
        header = opening_packet(data)
    except (ValueError, struct.error) as exc:
        return {"status": "no-record-stream", "error": str(exc),
                "frameRecords": 0, "fullyParsedFrames": 0, "unresolvedFrames": 0,
                "entryCounts": {}, "errors": {}, "units": {}, "entities": {}}
    if header["message_id"] == 1051:
        return {"status": "unsupported-route",
                "error": "ID1051 单局路线：容器已索引（docs 5.133），旧构建条目命令语义未解码",
                "frameRecords": 0, "fullyParsedFrames": 0, "unresolvedFrames": 0,
                "entryCounts": {}, "errors": {}, "units": {}, "entities": {}}
    from replay_profiles import resolve_profile
    profile = resolve_profile(header.get("versions"), header.get("builds"))
    if profile is None:
        versions = "/".join(header.get("versions") or [])
        builds = "/".join(header.get("builds") or [])
        return {"status": "unsupported-version",
                "error": (f"未配置解析档案：versions={versions} builds={builds}；"
                          "请在 resources/replay_profiles.json 增加版本，并按 "
                          "docs/replay_profiles.md 重跑 selector 映射后验证"),
                "frameRecords": 0, "fullyParsedFrames": 0, "unresolvedFrames": 0,
                "entryCounts": {}, "errors": {}, "units": {}, "entities": {}}
    units: dict[int, dict] = {}
    entities: dict[int, dict] = {}
    counts: collections.Counter = collections.Counter()
    errors: collections.Counter = collections.Counter()
    total = decoded = 0

    def bucket(store, key):
        return store.setdefault(key, {
            "stats": {"moves": 0, "attacks": 0, "attacksWithObj": 0, "buys": 0,
                      "learnSkill": 0, "skills": 0, "cc": 0,
                      "firstFrame": None, "lastFrame": None,
                      "dirMin": None, "dirMax": None},
            "moves": [], "attacks": [], "buys": [], "learnSkill": [],
            "skills": [], "cc": []})

    try:
        for record in iter_records(data):
            if record["kind"] != "frame":
                continue
            total += 1
            try:
                entries = decode_commands(data[record["command_offset"]:record["end"]])
            except ValueError as exc:
                errors[str(exc)] += 1
                continue
            decoded += 1
            frame = record["sequence"]
            for row in entries:
                name = row["name"]
                counts[name] += 1
                if name == "PLAYER_MOVE":
                    item = bucket(units, row["unit"])
                    item["stats"]["moves"] += 1
                    item["moves"].append([frame, row["dir_deg"], row["mag"], row["sign"], row["seq"]])
                elif name == "PLAYER_ATTACK":
                    item = bucket(units, row["unit"])
                    item["stats"]["attacks"] += 1
                    item["attacks"].append([frame, 0, None, row["seq"], row["flag"]])
                elif name == "PLAYER_ATTACKWITHOBJ":
                    item = bucket(units, row["unit"])
                    item["stats"]["attacksWithObj"] += 1
                    item["attacks"].append([frame, 1, row["fields"]["target_object_id"],
                                            row["seq"], row["flag"]])
                elif name == "BUYEQUIP":
                    item = bucket(entities, row["object_id"])
                    item["stats"]["buys"] += 1
                    item["buys"].append([frame, row["fields"]["equip_id"],
                                         row["fields"]["object_id"], row["fields"]["auto_buy"]])
                elif name == "LEARNSKILL":
                    item = bucket(entities, row["object_id"])
                    item["stats"]["learnSkill"] += 1
                    item["learnSkill"].append([frame, row["fields"]["slot"], row["fields"]["level"]])
                elif name in ("USEDIRECTIONALSKILL", "USEOBJECTIVESKILL", "USEPOSITIONSKILL"):
                    item = bucket(entities, row["object_id"])
                    item["stats"]["skills"] += 1
                    item["skills"].append([frame, row["sync_type"], row["fields"].get("slot")])
                elif name == "CC":
                    item = bucket(entities, row["object_id"])
                    item["stats"]["cc"] += 1
                    item["cc"].append([frame, row.get("buffer_hex")])
    except ValueError as exc:
        return {"status": "no-record-stream", "error": str(exc),
                "frameRecords": 0, "fullyParsedFrames": 0, "unresolvedFrames": 0,
                "entryCounts": {}, "errors": {}, "units": {}, "entities": {}}
    # first/last frame above only track frames that contributed events; that is
    # the honest activity window, not the parsed stream extent.
    for store in (units, entities):
        for item in store.values():
            stats = item["stats"]
            firsts = [e[0] for events_list in ("moves", "attacks", "buys", "learnSkill", "skills", "cc")
                      for e in item[events_list]]
            stats["firstFrame"] = min(firsts) if firsts else None
            stats["lastFrame"] = max(firsts) if firsts else None
            dirs = [e[1] for e in item["moves"]]
            stats["dirMin"] = min(dirs) if dirs else None
            stats["dirMax"] = max(dirs) if dirs else None
    return {"status": "decoded" if decoded == total else "partial",
            "profileId": profile["id"],
            "frameRecords": total, "fullyParsedFrames": decoded,
            "unresolvedFrames": total - decoded,
            "entryCounts": dict(counts), "errors": dict(errors),
            "units": {str(key): value for key, value in sorted(units.items())},
            "entities": {str(key): value for key, value in sorted(entities.items())}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--events-out", type=Path, help="New JSONL file for one fully decoded input")
    args = parser.parse_args()
    if args.events_out and len(args.files) != 1:
        parser.error("--events-out requires exactly one ABC file")
    reports = []
    for path in args.files:
        try:
            reports.append({"file": str(path), **audit_commands(path.read_bytes())})
        except ValueError as exc:
            reports.append({"file": str(path), "error": str(exc)})
    if args.events_out and not any("error" in row or row.get("unresolved_frames") for row in reports):
        # Validate the entire stream before creating the export; preserve existing files.
        output = "".join(json.dumps(row, ensure_ascii=False) + "\n"
                         for row in events(args.files[0].read_bytes()))
        with args.events_out.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(output)
    print(json.dumps(reports, ensure_ascii=False, indent=2))
    return int(any("error" in row or row.get("unresolved_frames") for row in reports))


if __name__ == "__main__":
    raise SystemExit(main())
