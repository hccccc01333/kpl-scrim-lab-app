"""Export per-frame .abc event windows around live checkpoint times.

Read-only analysis of a route-ID1075 replay: frame commands are decoded by
tools/replay_frame_commands.py, the roster comes from the .abc player blocks,
and the 0x01/0x2d aim-indicator samples are attached from the tail frame
stream.  No device, no database, no simulation: outputs are a CSV and a JSON
under the requested analysis directory.

The 0x02 tail messages are checked against the frame-command stream: on
build 5247758 every 0x80/0x81/0x82/0x85/0x87 body is byte-identical to the
matching CSSYNC payload, so the frame-command rows are the canonical events
and the tail stream is a mirror, not a second event source.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from replay_parser import (  # noqa: E402
    _iter_frame_payloads,
    _iter_payload_messages,
    digest,
    inspect_replay,
)
from tools.replay_frame_commands import (  # noqa: E402
    CS_SCHEMAS,
    FRAME_RATE,
    audit_commands,
    battle_time,
    compass_bearing,
    decode_commands,
    world_vector,
)
from tools.replay_input_timeline import (  # noqa: E402
    build_unit_map,
    extract_wrapper_tlvs,
    load_prices,
)
from tools.replay_opening_packet import opening_packet  # noqa: E402
from tools.replay_record_stream import iter_records  # noqa: E402

DEFAULT_ANCHORS = "94,165,300,446"
DEFAULT_HALF_WINDOW = 45
FAMILY = {
    "PLAYER_MOVE": "movement",
    "MOVE": "movement",
    "PLAYER_ATTACK": "attack",
    "PLAYER_ATTACKWITHOBJ": "attack",
    "BASEATTACK": "attack",
    "USEOBJECTIVESKILL": "skill",
    "USEDIRECTIONALSKILL": "skill",
    "LEARNSKILL": "skill",
    "USEPOSITIONSKILL": "aim",
    "BUYEQUIP": "buy",
    "SELLEQUIP": "buy",
    "CC": "cc",
    "AISTATECHG": "ai_state",
    "GAMEOVERNTF": "game_over",
}
SKILL_MIRROR = {
    "USEOBJECTIVESKILL": 0x80,
    "USEDIRECTIONALSKILL": 0x81,
    "USEPOSITIONSKILL": 0x82,
    "BUYEQUIP": 0x85,
    "LEARNSKILL": 0x87,
}
REQUESTED = ("movement", "aim", "facing", "kill", "buy", "skill")


def mmss(seconds: float) -> str:
    minutes = int(seconds // 60)
    return f"{minutes:02d}:{seconds - minutes * 60:04.1f}"


def selector(row: dict) -> str:
    boot = row["boot_type"]
    if boot == 2:
        return f"0x02/0x{row['sync_type']:02x}"
    if boot == 1:
        return "0x01/CC"
    return f"BOOTFRAP{boot}"


def roster_maps(blocks):
    units = build_unit_map(blocks)
    by_entity = {row["entityId"]: unit for unit, row in units.items()
                 if row.get("entityId") is not None}
    return units, by_entity


def actor_view(row: dict, units: dict, by_entity: dict):
    """Return (actor_type, actor_id, unit, related_unit) for one command row."""
    name = row["name"]
    if name in ("PLAYER_MOVE", "PLAYER_ATTACK", "PLAYER_ATTACKWITHOBJ"):
        return "unit", row["unit"], row["unit"], None
    if name == "AISTATECHG":
        entity = row["fields"].get("player_object_id")
        return "entity", entity, by_entity.get(entity), None
    entity = row.get("object_id")
    unit = by_entity.get(entity)
    return "entity", entity, unit, None


def describe(row: dict, prices: dict, units: dict) -> dict:
    name = row["name"]
    if name == "PLAYER_MOVE":
        out = {"packed_move": row["fields"]["packed_move"],
               "dir_deg": row["dir_deg"], "mag": row["mag"],
               "sign": row["sign"], "seq": row["seq"],
               "compass_deg": round(compass_bearing(row["dir_deg"]), 2),
               "world_vector": list(world_vector(row["dir_deg"]))}
        return out
    if name in ("PLAYER_ATTACK", "PLAYER_ATTACKWITHOBJ"):
        out = {"packed_attack": row["fields"]["packed_attack"],
               "seq": row["seq"], "flag": row["flag"],
               "start": row["fields"].get("start")}
        if "target_object_id" in row["fields"]:
            out["target_object_id"] = row["fields"]["target_object_id"]
        elif "object_id" in row["fields"]:
            out["object_id"] = row["fields"]["object_id"]
        return out
    if name == "BUYEQUIP":
        fields = dict(row["fields"])
        fields["price"] = prices.get(fields["equip_id"])
        return fields
    if name == "LEARNSKILL":
        fields = dict(row["fields"])
        # hero_object_id is a small actor/object id, not the 8-20 input unit:
        # on this replay it takes values 8..65 for entities whose units are
        # 18/19/20, so joining it to the unit table would be false.
        fields["hero_object_id_note"] = (
            "small actor/object id; unit mapping unresolved (既有校准-5.142)")
        return fields
    if name == "USEDIRECTIONALSKILL":
        fields = dict(row["fields"])
        fields["degree_deg"] = round(fields["degree"] / 100.0, 2)
        fields["degree_note"] = "centidegrees, 既有校准"
        return fields
    if name == "CC":
        buf = bytes.fromhex(row["buffer_hex"])
        fields = {"buffer_hex": row["buffer_hex"], "buffer_bytes": len(buf)}
        if len(buf) == 2:
            fields["key"] = f"{buf[0]:02x}"
            fields["value"] = buf[1]
        elif len(buf) == 3 and buf[0] == 0x02:
            fields["key"] = f"{buf[1]:02x}"
            fields["value"] = buf[2]
        return fields
    return dict(row.get("fields") or {})


def collect_events(data: bytes, units: dict, by_entity: dict, prices: dict):
    rows = []
    order = 0
    audit = audit_commands(data)
    for record in iter_records(data):
        if record["kind"] != "frame":
            continue
        frame = record["sequence"]
        try:
            entries = decode_commands(data[record["command_offset"]:record["end"]])
        except ValueError:
            continue
        for entry in entries:
            order += 1
            name = entry["name"]
            actor_type, actor_id, unit, _related = actor_view(entry, units, by_entity)
            hero = units.get(unit, {}) if unit is not None else {}
            rows.append({
                "frame": frame,
                "order": order,
                "family": FAMILY.get(name, "other"),
                "command": name,
                "selector": selector(entry),
                "actor_type": actor_type,
                "actor_id": actor_id,
                "unit": unit,
                "camp": hero.get("camp"),
                "slot": hero.get("slot"),
                "player": hero.get("player"),
                "hero": hero.get("hero"),
                "entity_id": hero.get("entityId"),
                "fields_json": json.dumps(describe(entry, prices, units),
                                          ensure_ascii=False, separators=(",", ":")),
                "source": "frame_command",
                "note": "",
            })
    return rows, audit


def collect_facing(data: bytes, by_entity: dict, units: dict):
    rows = []
    for entity, payload in extract_wrapper_tlvs(data).items():
        unit = by_entity.get(int(entity))
        hero = units.get(unit, {}) if unit is not None else {}
        for frame, angle in payload["angle"]:
            rows.append({
                "frame": frame,
                "order": 0,
                "family": "facing",
                "command": "SET_SKILL_INDICATOR_DIRECTION",
                "selector": "0x01/0x2d",
                "actor_type": "entity",
                "actor_id": int(entity),
                "unit": unit,
                "camp": hero.get("camp"),
                "slot": hero.get("slot"),
                "player": hero.get("player"),
                "hero": hero.get("hero"),
                "entity_id": hero.get("entityId"),
                "fields_json": json.dumps({"angle_deg": angle},
                                          ensure_ascii=False, separators=(",", ":")),
                "source": "tail_tlv",
                "note": "0x2d aim-indicator angle sample; only the recorder entity emits these",
            })
    return rows


def mirror_validation(data: bytes):
    """Compare every tail 0x80/0x81/0x82/0x85/0x87 body with its CSSYNC payload."""
    command_bytes = collections.defaultdict(list)
    for record in iter_records(data):
        if record["kind"] != "frame":
            continue
        for entry in decode_commands(data[record["command_offset"]:record["end"]]):
            name = entry["name"]
            if name in SKILL_MIRROR and entry["boot_type"] == 2:
                _, fmt, fields = CS_SCHEMAS[entry["sync_type"]]
                command_bytes[name].append((
                    record["sequence"], entry["object_id"],
                    struct.pack(">" + fmt, *[entry["fields"][f] for f in fields])))
    tail = collections.defaultdict(list)
    frames = inspect_replay(data)["frames"]
    for frame, _offset, payload in _iter_frame_payloads(data, frames):
        for tag, entity, subtype, body in _iter_payload_messages(payload):
            if tag == "02":
                tail[subtype].append((frame, entity, body))
    out = {}
    for name, subtype in SKILL_MIRROR.items():
        left = sorted(command_bytes[name])
        right = sorted(tail[subtype])
        identical = (len(left) == len(right)
                     and all(a[0] == b[0] and a[1] == b[1] and a[2] == b[2]
                             for a, b in zip(left, right)))
        out[f"0x{subtype:02x}"] = {
            "frame_command": name,
            "cssync_entries": len(left),
            "tail_entries": len(right),
            "byte_identical": identical,
            "verified": "build 5247758; payload packed from the decoded CS_SCHEMAS fields",
        }
    return out


def build(abc_path: Path, anchors: list[float], half_window: int):
    data = abc_path.read_bytes()
    header = opening_packet(data)
    info = inspect_replay(data)
    blocks = info.get("blocks") or []
    if not blocks:
        raise ValueError("no ten-player roster blocks decoded")
    units = {}
    for unit, row in build_unit_map(blocks).items():
        block = None
        for candidate in blocks:
            if candidate.get("entityId") == row["entityId"]:
                block = candidate
                break
        units[unit] = {
            "unit": unit,
            "camp": row["camp"],
            "slot": row["slot"],
            "entityId": row["entityId"],
            "player": (block or {}).get("name"),
            "hero": row["hero"],
        }
    by_entity = {row["entityId"]: unit for unit, row in units.items()}
    prices = load_prices()
    frame_rows, audit = collect_events(data, units, by_entity, prices)
    facing_rows = collect_facing(data, by_entity, units)
    all_rows = sorted(frame_rows + facing_rows, key=lambda r: (r["frame"], r["order"]))
    windows = []
    for anchor in anchors:
        base = int(round(anchor * FRAME_RATE))
        low, high = base - half_window, base + half_window
        rows = [r for r in all_rows if low <= r["frame"] <= high]
        counts = collections.Counter(r["family"] for r in rows)
        requested = {family: counts.get(family, 0) for family in REQUESTED}
        windows.append({
            "label": mmss(anchor),
            "anchorSeconds": anchor,
            "anchorFrameBase": base,
            "anchorFrameRange": [base, base + 14],
            "frameRange": [low, high],
            "timeRangeSeconds": [round((low - 1) / FRAME_RATE, 3),
                                 round((high - 1) / FRAME_RATE, 3)],
            "eventCount": len(rows),
            "framesWithEvents": len({r["frame"] for r in rows}),
            "familyCounts": dict(sorted(counts.items())),
            "requestedFamilyCounts": requested,
            "events": rows,
        })
    full_counts = collections.Counter(r["family"] for r in all_rows)
    report = {
        "match": {
            "replay": abc_path.name,
            "repoRelativePath": str(abc_path.resolve().relative_to(ROOT)),
            "absolutePath": str(abc_path.resolve()),
            "sha256": digest(data),
            "fileBytes": len(data),
            "route": header["message_id"],
            "versions": header["versions"],
            "builds": header["builds"],
            "totalFrameHeader": header["total_frame_header"],
            "frameRecords": audit["frame_records"],
            "fullyParsedFrames": audit["fully_parsed_frames"],
            "unresolvedFrames": audit["unresolved_frames"],
            "resourceVersion": audit["resource_version"],
            "recorder": ({"entityId": facing_rows[0]["entity_id"],
                          "hero": facing_rows[0]["hero"],
                          "player": facing_rows[0]["player"],
                          "evidence": "only entity emitting 0x01/0x2d angle samples"}
                         if facing_rows else None),
            "duration": "11:33 (693 s) per postgame screenshot / 既有校准",
        },
        "timeBase": {
            "framesPerSecond": FRAME_RATE,
            "battleTimeFormula": "t = (frame - 1) / 15 s",
            "battleStartFrame": [0, 14],
            "uncertaintySeconds": 1,
            "windowHalfWindowFrames": half_window,
            "note": "Displayed match clock floors to the second; battle 0:00 lies in "
                    "frames 0..14. Anchor frame ranges and +/-3 s windows bracket that "
                    "uncertainty. Frame-command rows keep decoded stream order inside "
                    "a frame; 0x2d facing samples carry no intra-frame order and are "
                    "placed first at their frame.",
        },
        "roster": [units[u] for u in sorted(units)],
        "commandFamilies": {
            "movement": "PLAYER_MOVE (BOOTFRAP 18, packed unit/seq/sign/magnitude) + MOVE (CSSYNC 131, absent here)",
            "aim": "USEPOSITIONSKILL (CSSYNC 130) = tail 0x02/0x82",
            "facing": "0x01/0x2d aim-indicator angle samples (no 0x83 entry subtype in this route)",
            "kill": "no per-kill command decoded in route 1075; 0 kills emitted",
            "buy": "BUYEQUIP (CSSYNC 133) = tail 0x02/0x85",
            "skill": "USEOBJECTIVESKILL (0x80) + USEDIRECTIONALSKILL (0x81) + LEARNSKILL (0x87)",
            "attack": "PLAYER_ATTACK (BOOTFRAP 19) + PLAYER_ATTACKWITHOBJ (BOOTFRAP 20)",
            "cc": "CC buffers (BOOTFRAP selector 1)",
            "ai_state": "AISTATECHG (BOOTFRAP selector 5)",
            "note": "The requested labels 0x80=movement, 0x83=facing, 0x84=kill do not "
                    "match this replay's decoded taxonomy. In route 1075 the 0x02 channel "
                    "carries CS sync payloads: 0x80=USEOBJECTIVESKILL, 0x81="
                    "USEDIRECTIONALSKILL, 0x82=USEPOSITIONSKILL, 0x85=BUYEQUIP, "
                    "0x87=LEARNSKILL. 0x83 and 0x84 do not occur; per docs, 0x02/0x84 "
                    "is BASEATTACK, not a kill notice.",
            "requestedHexAudit": {
                "0x80": {"requested": "movement", "present": True,
                         "actualCommand": "USEOBJECTIVESKILL (skill)", "count": 641,
                         "verdict": "mismatch; movement is BOOTFRAP 18 PLAYER_MOVE"},
                "0x82": {"requested": "aim", "present": True,
                         "actualCommand": "USEPOSITIONSKILL", "count": 78,
                         "verdict": "match"},
                "0x83": {"requested": "facing", "present": False, "count": 0,
                         "verdict": "absent; facing comes from 0x01/0x2d TLV samples"},
                "0x84": {"requested": "kill", "present": False, "count": 0,
                         "verdict": "absent; docs define 0x02/0x84 as BASEATTACK, not kill"},
                "0x85": {"requested": "buy", "present": True,
                         "actualCommand": "BUYEQUIP", "count": 547,
                         "verdict": "match"},
                "0x87": {"requested": "skill", "present": True,
                         "actualCommand": "LEARNSKILL (level-up)", "count": 120,
                         "verdict": "partial; skill casts also use 0x80/0x81"},
            },
        },
        "audit": {
            "frameRecords": audit["frame_records"],
            "fullyParsedFrames": audit["fully_parsed_frames"],
            "unresolvedFrames": audit["unresolved_frames"],
            "entryCounts": audit["accepted_entry_counts"],
            "errors": audit["errors"],
            "totalLogicalEvents": len(all_rows),
            "familyTotals": dict(sorted(full_counts.items())),
        },
        "tailMirrorValidation": mirror_validation(data),
        "anchors": windows,
        "limitations": [
            "Movement rows are input directions, not world positions; no trajectory is derived.",
            "USEDIRECTIONALSKILL secondary_1..3 and USEPOSITIONSKILL object_id semantics are unresolved; values are kept verbatim.",
            "CC buffers carry unresolved state; only the raw hex and 2/3-byte key-value form are exposed.",
            "No kill/death event is decodable from this route; kill counts are 0, not missing data.",
            "0x2d angle samples exist only for the recorder (百里守约, entity 1611).",
            "Battle time uses the 15 fps calibration with +/-1 s uncertainty; windows are +/-3 s.",
        ],
    }
    return report


def write_csv(report: dict, path: Path) -> None:
    columns = ["window", "anchor_s", "anchor_frame_base", "frame", "time_s",
               "time_mmss", "delta_s", "family", "command", "selector",
               "actor_type", "actor_id", "unit", "camp", "slot", "player",
               "hero", "entity_id", "fields_json", "source", "note"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for window in report["anchors"]:
            for row in window["events"]:
                time_s = round((row["frame"] - 1) / FRAME_RATE, 3)
                writer.writerow({
                    "window": window["label"],
                    "anchor_s": window["anchorSeconds"],
                    "anchor_frame_base": window["anchorFrameBase"],
                    "frame": row["frame"],
                    "time_s": time_s,
                    "time_mmss": mmss(time_s),
                    "delta_s": round(time_s - window["anchorSeconds"], 3),
                    "family": row["family"],
                    "command": row["command"],
                    "selector": row["selector"],
                    "actor_type": row["actor_type"],
                    "actor_id": row["actor_id"],
                    "unit": row["unit"],
                    "camp": row["camp"],
                    "slot": row["slot"],
                    "player": row["player"],
                    "hero": row["hero"],
                    "entity_id": row["entity_id"],
                    "fields_json": row["fields_json"],
                    "source": row["source"],
                    "note": row["note"],
                })


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("abc", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--anchors", default=DEFAULT_ANCHORS,
                        help="comma-separated battle seconds (default 94,165,300,446)")
    parser.add_argument("--half-window", type=int, default=DEFAULT_HALF_WINDOW,
                        help="frames on each side of the anchor (default 45 = 3 s)")
    args = parser.parse_args()
    anchors = [float(value) for value in args.anchors.split(",") if value.strip()]
    report = build(args.abc, anchors, args.half_window)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / "event_windows.json"
    csv_path = args.out_dir / "event_windows.csv"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                         encoding="utf-8")
    write_csv(report, csv_path)
    summary = {
        "file": str(args.abc),
        "sha256": report["match"]["sha256"],
        "json": str(json_path),
        "csv": str(csv_path),
        "windows": [{"label": w["label"], "frames": w["frameRange"],
                     "events": w["eventCount"],
                     "requested": w["requestedFamilyCounts"]}
                    for w in report["anchors"]],
        "totals": report["audit"]["familyTotals"],
        "tailMirror": {k: v["byte_identical"]
                       for k, v in report["tailMirrorValidation"].items()},
    }
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
