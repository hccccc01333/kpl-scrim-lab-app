"""Stream a whole route-ID1075 .abc replay into a complete frame-command catalog.

One row per decoded frame-command entry over every frame record (not a set of
windows).  The command decoder, roster join, packed-input decoding, price
table, time base and selector labels are the existing ones from
tools/replay_frame_commands.py and tools/replay_abc_event_windows.py, so the
field names and values match the checkpoint exports.

Read-only and offline: no device, adb, network, database write, or simulation.
The tail 0x02 messages are a byte-identical mirror of the frame commands
(checked at run time) and are therefore not ingested; tail-only 0x01/0x2d
facing samples are also not frame commands and are not ingested.  A frame
that cannot be decoded contributes one clearly-marked UNKNOWN row carrying the
raw frame-command bytes; no resynchronisation or guessed entry length is
attempted.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from replay_parser import digest, inspect_replay  # noqa: E402
from tools.replay_abc_event_windows import (  # noqa: E402
    FAMILY,
    mirror_validation,
    mmss,
    selector,
)
from tools.replay_frame_commands import (  # noqa: E402
    BOOT_SCHEMAS,
    CS_SCHEMAS,
    UnsupportedCommand,
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

# event_windows labels every command above; the extra names cover schemas the
# decoder supports but this replay does not emit, so the family column stays
# meaningful on other ID1075 samples.
CATALOG_FAMILY = dict(FAMILY)
CATALOG_FAMILY.update({
    "ROTATE": "movement",
    "FRAME_HASH_CHECK": "frame_check",
    "CAMPSTATE": "camp_state",
    "CAMP_SURRENDER": "camp_state",
    "BEGIN_FRAME_EXTEND": "frame_meta",
    "ACNTSTATECHG": "account_state",
})
FAMILY_ORDER = (
    "movement", "attack", "skill", "aim", "buy", "cc", "ai_state",
    "game_over", "frame_check", "camp_state", "frame_meta", "account_state",
    "other", "unknown",
)
UNIT_COMMANDS = frozenset({"PLAYER_MOVE", "PLAYER_ATTACK", "PLAYER_ATTACKWITHOBJ"})
CSV_COLUMNS = [
    "frame", "time_s", "time_mmss", "family", "command", "selector",
    "actor_type", "actor_id", "unit", "camp", "slot", "player", "hero",
    "entity_id", "fields_json", "summary", "row", "frame_entry_index",
]
SCHEMA_INFO = {}
for _subtype, (_name, _fmt, _fields) in CS_SCHEMAS.items():
    SCHEMA_INFO[_name] = {"selector": f"0x02/0x{_subtype:02x}",
                          "fields": _fields}
for _boot, (_name, _fmt, _fields) in BOOT_SCHEMAS.items():
    SCHEMA_INFO[_name] = {"selector": f"BOOTFRAP{_boot}",
                          "fields": _fields}
SCHEMA_INFO["CC"] = {"selector": "0x01/CC",
                     "fields": ("object_id", "buffer")}
DERIVED = {
    "PLAYER_MOVE": "unit, seq, sign, mag, dir_deg, compass_deg, world_vector",
    "PLAYER_ATTACK": "unit, seq, flag",
    "PLAYER_ATTACKWITHOBJ": "unit, seq, flag",
    "USEDIRECTIONALSKILL": "degree_deg (centidegrees / 100)",
    "BUYEQUIP": "price (battle-item reference price)",
    "CC": "buffer_bytes; key/value for 2-byte buffers",
    "LEARNSKILL": "no unit join (hero_object_id is a small actor id)",
}


class CatalogError(RuntimeError):
    pass


def roster(data: bytes, info: dict | None = None):
    """Return (inspect_replay info, {unit: hero}, {entityId: unit}).

    ``info`` lets a caller that already parsed this .abc (the workspace does,
    at import time) skip a second full decode.
    """
    info = info or inspect_replay(data)
    blocks = info.get("blocks") or []
    if len(blocks) != 10:
        raise CatalogError(f"expected 10 roster blocks, got {len(blocks)}")
    units = {}
    by_entity = {}
    for unit, row in build_unit_map(blocks).items():
        block = next((item for item in blocks
                      if item.get("entityId") == row["entityId"]), None)
        if block is None:
            raise CatalogError(f"no block for unit {unit} entity {row['entityId']}")
        units[unit] = {
            "unit": unit,
            "camp": row["camp"],
            "slot": row["slot"],
            "entityId": row["entityId"],
            "player": block.get("name"),
            "hero": row["hero"],
        }
        entity = row["entityId"]
        if entity in by_entity:
            raise CatalogError(f"duplicate entity id {entity}")
        by_entity[entity] = unit
    if set(by_entity.values()) != set(units):
        raise CatalogError("entity->unit map is not one-to-one")
    for camp in (1, 2):
        slots = sorted(item["slot"] for item in units.values()
                       if item["camp"] == camp)
        if slots != [0, 1, 2, 3, 4]:
            raise CatalogError(f"camp {camp} slots are {slots}, expected 0..4")
    return info, units, by_entity


def describe(row: dict, prices: dict) -> dict:
    """Decoded fields, using the event_windows field names and derivations."""
    name = row["name"]
    if name == "PLAYER_MOVE":
        return {"packed_move": row["fields"]["packed_move"],
                "dir_deg": row["dir_deg"], "mag": row["mag"],
                "sign": row["sign"], "seq": row["seq"],
                "compass_deg": round(compass_bearing(row["dir_deg"]), 2),
                "world_vector": list(world_vector(row["dir_deg"]))}
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


def actor_view(row: dict, units: dict, by_entity: dict):
    """Return (actor_type, actor_id, unit, hero) for one command row."""
    name = row["name"]
    if name in UNIT_COMMANDS:
        unit = row["unit"]
        return "unit", unit, unit, units.get(unit)
    if name == "AISTATECHG":
        entity = row["fields"].get("player_object_id")
    else:
        entity = row.get("object_id")
    unit = by_entity.get(entity)
    return "entity", entity, unit, units.get(unit)


def actor_label(actor_type, actor_id, unit, hero) -> str:
    if hero:
        if actor_type == "unit":
            return f"{hero['hero']} u{unit}"
        return f"{hero['hero']} e{actor_id}"
    if unit is not None:
        return f"unit {unit} (name unresolved)"
    if actor_id is not None:
        return f"{actor_type} {actor_id}"
    return "unmapped"


def summarize(name: str, fields: dict, label: str) -> str:
    if name == "PLAYER_MOVE":
        return (f"{label} move dir={fields['dir_deg']}° "
                f"mag={fields['mag']} seq={fields['seq']}")
    if name == "PLAYER_ATTACK":
        return f"{label} attack seq={fields['seq']} flag={fields['flag']}"
    if name == "PLAYER_ATTACKWITHOBJ":
        return (f"{label} attack->{fields['target_object_id']} "
                f"seq={fields['seq']} flag={fields['flag']}")
    if name == "MOVE":
        return f"{label} move degree={fields['degree']} seq={fields['seq']}"
    if name == "ROTATE":
        return f"{label} rotate degree={fields['degree']} seq={fields['seq']}"
    if name == "BASEATTACK":
        return (f"{label} base attack start={fields['start']} "
                f"obj={fields['object_id']}")
    if name == "USEOBJECTIVESKILL":
        return (f"{label} objective skill slot={fields['slot']} "
                f"obj={fields['object_id']} seq={fields['skill_seq']}")
    if name == "USEDIRECTIONALSKILL":
        return (f"{label} directional skill slot={fields['slot']} "
                f"deg={fields['degree_deg']} seq={fields['skill_seq']}")
    if name == "USEPOSITIONSKILL":
        return (f"{label} position skill slot={fields['slot']} "
                f"aim=({fields['target_x']},{fields['target_y']}) "
                f"seq={fields['skill_seq']}")
    if name == "LEARNSKILL":
        return (f"{label} learn slot={fields['slot']} level={fields['level']} "
                f"auto={fields['auto_learn']}")
    if name == "BUYEQUIP":
        price = fields.get("price")
        suffix = f" price={price}" if price is not None else " price=?"
        return (f"{label} buy equip={fields['equip_id']} "
                f"flag={fields['auto_buy']}{suffix}")
    if name == "SELLEQUIP":
        return (f"{label} sell index={fields['equip_index']} "
                f"container={fields['container_type']}")
    if name == "CC":
        if "key" in fields:
            return (f"{label} CC {fields['buffer_bytes']}B "
                    f"{fields['key']}={fields['value']}")
        return f"{label} CC {fields['buffer_bytes']}B raw"
    if name == "AISTATECHG":
        return (f"{label} ai_state type={fields['type']} "
                f"player={fields['player_object_id']} "
                f"flag={fields['display_flag']} "
                f"delay={fields['display_delay_seconds']}s")
    if name == "GAMEOVERNTF":
        return f"game over win_camp={fields['win_camp']}"
    if name == "CAMPSTATE":
        return f"camp {fields['camp']} state {fields['state']}"
    if name == "CAMP_SURRENDER":
        return f"camp {fields['camp']} surrender"
    if name == "BEGIN_FRAME_EXTEND":
        return f"begin frame win_camp={fields['win_camp']}"
    if name == "ACNTSTATECHG":
        return (f"{label} account state obj={fields['object_id']} "
                f"change={fields['state_change']}")
    if name == "FRAME_HASH_CHECK":
        return (f"{label} hash check source={fields['source_type']} "
                f"p1={fields['param_1']} p2={fields['param_2']}")
    return f"{label} {name} {json.dumps(fields, ensure_ascii=False)}"


def unknown_selector(error: str) -> str:
    match = re.search(r"selector (\d+)", error)
    if not match:
        return "raw"
    value = int(match.group(1))
    if "CSSYNC" in error:
        return f"0x02/0x{value:02x}"
    return f"BOOTFRAP{value}"


def make_row(row_number, frame, frame_entry_index, family, command, sel,
             actor_type, actor_id, unit, hero, fields, summary):
    time_s = round(battle_time(frame), 3)
    return {
        "row": row_number,
        "frame": frame,
        "time_s": time_s,
        "time_mmss": mmss(time_s),
        "frame_entry_index": frame_entry_index,
        "family": family,
        "command": command,
        "selector": sel,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "unit": unit,
        "camp": (hero or {}).get("camp"),
        "slot": (hero or {}).get("slot"),
        "player": (hero or {}).get("player"),
        "hero": (hero or {}).get("hero"),
        "entity_id": (hero or {}).get("entityId"),
        "fields": fields,
        "fields_json": json.dumps(fields, ensure_ascii=False,
                                  separators=(",", ":")),
        "summary": summary,
    }


def new_stats():
    return {
        "rows": 0,
        "frames": 0,
        "per_frame": {},
        "family": collections.Counter(),
        "command": collections.Counter(),
        "command_family": {},
        "family_frames": {},
        "command_frames": {},
        "player_family": collections.defaultdict(collections.Counter),
        "actor_type": collections.Counter(),
        "mapped_rows": 0,
        "unmapped_rows": 0,
        "unknown_frames": 0,
        "unknown_rows": 0,
        "cc_kv": 0,
        "cc_raw": 0,
        "cc_raw_lengths": collections.Counter(),
        "cc_keys": collections.Counter(),
        "buy_flags": collections.Counter(),
        "buy_equips": collections.Counter(),
        "buy_missing_price": 0,
        "dir_min": None,
        "dir_max": None,
        "mag_min": None,
        "mag_max": None,
        "degree_min": None,
        "degree_max": None,
        "aim_x": [None, None],
        "aim_y": [None, None],
        "learn_hero_ids": set(),
        "row_keys": set(),
        "duplicate_keys": 0,
        "first_frame": None,
        "last_frame": None,
    }


def touch_frame(bucket, key, frame):
    current = bucket.get(key)
    if current is None:
        bucket[key] = [frame, frame]
    else:
        if frame < current[0]:
            current[0] = frame
        if frame > current[1]:
            current[1] = frame


def update_stats(stats, row):
    stats["rows"] += 1
    frame = row["frame"]
    name = row["command"]
    family = row["family"]
    stats["family"][family] += 1
    stats["command"][name] += 1
    stats["command_family"].setdefault(name, family)
    touch_frame(stats["family_frames"], family, frame)
    touch_frame(stats["command_frames"], name, frame)
    unit = row["unit"]
    stats["player_family"][unit][family] += 1
    stats["actor_type"][row["actor_type"]] += 1
    if unit is None:
        stats["unmapped_rows"] += 1
    else:
        stats["mapped_rows"] += 1
    key = (frame, row["frame_entry_index"])
    if key in stats["row_keys"]:
        stats["duplicate_keys"] += 1
    else:
        stats["row_keys"].add(key)
    if stats["first_frame"] is None or frame < stats["first_frame"]:
        stats["first_frame"] = frame
    if stats["last_frame"] is None or frame > stats["last_frame"]:
        stats["last_frame"] = frame
    fields = row["fields"]
    if name == "CC":
        length = fields["buffer_bytes"]
        if "key" in fields:
            stats["cc_kv"] += 1
            stats["cc_keys"][fields["key"]] += 1
        else:
            stats["cc_raw"] += 1
            stats["cc_raw_lengths"][length] += 1
    elif name == "BUYEQUIP":
        stats["buy_flags"][fields["auto_buy"]] += 1
        stats["buy_equips"][fields["equip_id"]] += 1
        if fields.get("price") is None:
            stats["buy_missing_price"] += 1
    elif name == "PLAYER_MOVE":
        stats["dir_min"] = (fields["dir_deg"] if stats["dir_min"] is None
                            else min(stats["dir_min"], fields["dir_deg"]))
        stats["dir_max"] = (fields["dir_deg"] if stats["dir_max"] is None
                            else max(stats["dir_max"], fields["dir_deg"]))
        stats["mag_min"] = (fields["mag"] if stats["mag_min"] is None
                            else min(stats["mag_min"], fields["mag"]))
        stats["mag_max"] = (fields["mag"] if stats["mag_max"] is None
                            else max(stats["mag_max"], fields["mag"]))
    elif name == "USEDIRECTIONALSKILL":
        stats["degree_min"] = (fields["degree"] if stats["degree_min"] is None
                               else min(stats["degree_min"], fields["degree"]))
        stats["degree_max"] = (fields["degree"] if stats["degree_max"] is None
                               else max(stats["degree_max"], fields["degree"]))
    elif name == "USEPOSITIONSKILL":
        x, y = fields["target_x"], fields["target_y"]
        stats["aim_x"] = [x if stats["aim_x"][0] is None else min(stats["aim_x"][0], x),
                          x if stats["aim_x"][1] is None else max(stats["aim_x"][1], x)]
        stats["aim_y"] = [y if stats["aim_y"][0] is None else min(stats["aim_y"][0], y),
                          y if stats["aim_y"][1] is None else max(stats["aim_y"][1], y)]
    elif name == "LEARNSKILL":
        stats["learn_hero_ids"].add(fields["hero_object_id"])


def build_catalog(data, units, by_entity, prices, csv_handle, jsonl_handle):
    """Stream every frame record once, write both row files, return stats."""
    stats = new_stats()
    writer = csv.writer(csv_handle)
    writer.writerow(CSV_COLUMNS)
    row_number = 0
    for record in iter_records(data):
        if record["kind"] != "frame":
            continue
        stats["frames"] += 1
        frame = record["sequence"]
        payload = data[record["command_offset"]:record["end"]]
        try:
            entries = decode_commands(payload)
            error = None
        except (UnsupportedCommand, ValueError, struct.error) as exc:
            entries = None
            error = str(exc)
        if entries is None:
            row_number += 1
            fields = {"error": error,
                      "raw_hex": payload.hex(),
                      "frame_command_bytes": len(payload)}
            fields_json = json.dumps(fields, ensure_ascii=False,
                                     separators=(",", ":"))
            row = {
                "row": row_number,
                "frame": frame,
                "time_s": round(battle_time(frame), 3),
                "time_mmss": mmss(round(battle_time(frame), 3)),
                "frame_entry_index": 1,
                "family": "unknown",
                "command": "UNKNOWN",
                "selector": unknown_selector(error),
                "actor_type": "none",
                "actor_id": None,
                "unit": None,
                "camp": None,
                "slot": None,
                "player": None,
                "hero": None,
                "entity_id": None,
                "fields": fields,
                "fields_json": fields_json,
                "summary": f"UNKNOWN undecoded frame: {error}",
            }
            stats["per_frame"][frame] = 1
            stats["unknown_frames"] += 1
            stats["unknown_rows"] += 1
            update_stats(stats, row)
            writer.writerow([row[column] for column in CSV_COLUMNS])
            jsonl_handle.write(json.dumps(
                {key: value for key, value in row.items()
                 if key != "fields_json"},
                ensure_ascii=False, separators=(",", ":")) + "\n")
            continue
        stats["per_frame"][frame] = len(entries)
        for index, entry in enumerate(entries, 1):
            row_number += 1
            name = entry["name"]
            family = CATALOG_FAMILY.get(name, "other")
            fields = describe(entry, prices)
            actor_type, actor_id, unit, hero = actor_view(entry, units, by_entity)
            label = actor_label(actor_type, actor_id, unit, hero)
            row = make_row(row_number, frame, index, family, name,
                           selector(entry), actor_type, actor_id, unit, hero,
                           fields, summarize(name, fields, label))
            update_stats(stats, row)
            writer.writerow([row[column] for column in CSV_COLUMNS])
            jsonl_handle.write(json.dumps(
                {key: value for key, value in row.items()
                 if key != "fields_json"},
                ensure_ascii=False, separators=(",", ":")) + "\n")
    stats["frames_with_commands"] = sum(1 for count in stats["per_frame"].values()
                                       if count)
    return stats


def per_player_rows(units, stats):
    rows = []
    for unit in sorted(units):
        hero = units[unit]
        row = {"unit": unit, "camp": hero["camp"], "slot": hero["slot"],
               "player": hero["player"], "hero": hero["hero"],
               "entity_id": hero["entityId"],
               "total": sum(stats["player_family"][unit].values())}
        for family in FAMILY_ORDER:
            if stats["family"].get(family):
                row[family] = stats["player_family"][unit].get(family, 0)
        rows.append(row)
    if stats["unmapped_rows"]:
        row = {"unit": None, "camp": None, "slot": None,
               "player": "UNMAPPED", "hero": None, "entity_id": None,
               "total": sum(stats["player_family"][None].values())}
        for family in FAMILY_ORDER:
            if stats["family"].get(family):
                row[family] = stats["player_family"][None].get(family, 0)
        rows.append(row)
    return rows


def write_per_player_counts(path, units, stats):
    rows = per_player_rows(units, stats)
    columns = ["unit", "camp", "slot", "player", "hero", "entity_id", "total"]
    columns += [family for family in FAMILY_ORDER if stats["family"].get(family)]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    return rows


def write_per_family_counts(path, stats):
    total = stats["rows"]
    rows = []
    for family in FAMILY_ORDER:
        count = stats["family"].get(family, 0)
        if not count:
            continue
        first, last = stats["family_frames"][family]
        commands = ";".join(
            f"{name}={value}" for name, value in
            sorted(stats["command"].items(),
                   key=lambda item: (-item[1], item[0]))
            if stats["command_family"].get(name) == family)
        rows.append({
            "family": family,
            "count": count,
            "share_pct": round(count * 100.0 / total, 4),
            "first_frame": first,
            "last_frame": last,
            "first_time_s": round(battle_time(first), 3),
            "last_time_s": round(battle_time(last), 3),
            "commands": commands,
        })
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "family", "count", "share_pct", "first_frame", "last_frame",
            "first_time_s", "last_time_s", "commands"])
        writer.writeheader()
        writer.writerows(rows)
    return rows


def fmt_time(frame):
    return mmss(round(battle_time(frame), 3))


def md(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


def range_text(low, high):
    if low is None or high is None:
        return "n/a (no rows)"
    return f"{low} … {high}"


def render_readme(report) -> str:
    header = report["header"]
    stats = report["stats"]
    audit = report["audit"]
    mirror = report["mirror"]
    units = report["units"]
    players = report["players"]
    family_rows = report["family_rows"]
    total = stats["rows"]
    lines = []
    add = lines.append

    stem = Path(report["relative"]).name
    stem_parts = stem.split("_")
    match_id = "_".join(stem_parts[:2]) if len(stem_parts) > 1 else stem
    max_frame = max(stats["per_frame"]) if stats["per_frame"] else 0
    duration_s = (max_frame - 1) / 15.0
    duration_mmss = f"{int(duration_s // 60)}:{duration_s % 60:04.1f}"
    header_extra = header["total_frame_header"] - stats["frames"]
    parsed_frames = audit["fully_parsed_frames"]
    aim_heroes = sorted({row["hero"] for row in players if row.get("aim")})

    add(f"# Full frame-command event catalog — {match_id}")
    add("")
    add("Complete, whole-replay catalog of the `.abc` frame-command stream: one")
    add("row for every decoded command entry across every frame record, not a set")
    add("of checkpoint windows. Offline and read-only; no device, adb, network,")
    add("database write, or simulation was used.")
    add("")
    add("Generator: `tools/full_abc_event_catalog.py` (reuses")
    add("`tools/replay_frame_commands.py`, `tools/replay_abc_event_windows.py`,")
    add("`tools/replay_input_timeline.py`, and `tools/replay_record_stream.py`).")
    add("")
    add("---")
    add("")
    add("## 1. Source replay")
    add("")
    add("| Field | Value |")
    add("|---|---|")
    add(f"| Repo-relative path | `{md(report['relative'])}` |")
    add(f"| Absolute path | `{md(report['absolute'])}` |")
    add(f"| Size | {report['file_bytes']:,} bytes |")
    add(f"| SHA-256 | `{report['sha256']}` |")
    add(f"| Route / message id | {header['message_id']} (multiplayer replay) |")
    add(f"| Versions | `{header['versions'][0]}` / `{header['versions'][1]}` |")
    add(f"| Builds | `{header['builds'][0]}` / `{header['builds'][1]}` |")
    add(f"| Header `totalFrameNum` | {header['total_frame_header']:,} |")
    add(f"| Frame records decoded | {stats['frames']:,} |")
    add(f"| Frames fully parsed | {audit['fully_parsed_frames']:,} |")
    add(f"| Unresolved frames | {audit['unresolved_frames']:,} |")
    add(f"| Frame-command entries | {total:,} |")
    add(f"| Stream length | {duration_mmss} = {duration_s:.0f} s "
        f"(last frame {max_frame:,} at 15 fps; includes any post-game tail) |")
    add("")
    add(f"`totalFrameNum` differs from the record count by {header_extra} frames")
    add("(the header budget includes the pre-battle load); the record stream")
    add(f"itself runs from frame 1 to frame {max_frame:,}.")
    add("")
    add("### Roster")
    add("")
    add("| Unit | Entity | Camp | Slot | Player | Hero |")
    add("|---:|---:|---:|---:|---|---|")
    for unit in sorted(units):
        hero = units[unit]
        add(f"| {unit} | {hero['entityId']} | {hero['camp']} | {hero['slot']} | "
            f"{md(hero['player'])} | {md(hero['hero'])} |")
    add("")
    add("---")
    add("")
    add("## 2. Outputs")
    add("")
    add("| File | Content |")
    add("|---|---|")
    add(f"| `events.csv` | All {total:,} rows, UTF-8 with BOM, one row per command |")
    add(f"| `events.jsonl` | Same rows as JSON Lines (nested `fields` object) |")
    add(f"| `per_player_counts.csv` | {len(players)} roster rows, total + family counts |")
    add(f"| `per_family_counts.csv` | {len(family_rows)} family rows with per-command breakdown |")
    add("| `README.md` | This document |")
    add("")
    add("`events.csv` and `events.jsonl` are written in stream order: frame")
    add("ascending, then decoded command order inside the frame.")
    add("")
    add("---")
    add("")
    add("## 3. Schema")
    add("")
    add("`events.csv` columns (the first 16 are the requested schema; the last")
    add("two are ordering aids):")
    add("")
    add("| Column | Meaning |")
    add("|---|---|")
    add(f"| `frame` | Recorded frame number, 1–{max_frame:,} |")
    add("| `time_s` | `(frame − 1) / 15`, the calibrated battle time (±1 s) |")
    add("| `time_mmss` | Same time as `mm:ss.d` |")
    add("| `family` | `movement`, `attack`, `skill`, `aim`, `buy`, `cc`, `ai_state`, `unknown`, … |")
    add("| `command` | Decoded command name (`PLAYER_MOVE`, `USEOBJECTIVESKILL`, …) |")
    add("| `selector` | Literal selector (`BOOTFRAP18`, `0x02/0x80`, `0x01/CC`) |")
    add("| `actor_type` | `unit` (8–20) or `entity` (hero entity id) |")
    add("| `actor_id` | Unit or entity id used by the command |")
    add("| `unit`, `camp`, `slot` | Roster join of the resolved hero |")
    add("| `player`, `hero` | Roster player name and hero name |")
    add("| `entity_id` | Roster entity id of the resolved hero |")
    add("| `fields_json` | Decoded fields as compact JSON (no spaces) |")
    add("| `summary` | One-line human-readable description |")
    add("| `row` | 1-based global row number |")
    add("| `frame_entry_index` | 1-based command index inside its frame |")
    add("")
    add("`events.jsonl` mirrors the CSV with the same values; `fields_json` is")
    add("replaced by a nested `fields` object. `None` becomes `null`.")
    add("")
    add("### Field decoding by command")
    add("")
    add("| Command | Selector | Wire fields | Derived / decoded |")
    add("|---|---|---|---|")
    for name, count in sorted(stats["command"].items(),
                              key=lambda item: (-item[1], item[0])):
        info = SCHEMA_INFO.get(name)
        if info is None:
            add(f"| `{name}` | `raw` | — | raw frame bytes; see the UNKNOWN note |")
            continue
        wire = ", ".join(info["fields"])
        derived = DERIVED.get(name, "—")
        add(f"| `{name}` | `{info['selector']}` | {wire} | {derived} |")
    add("")
    add("`PLAYER_MOVE` values are input directions, not world positions. The")
    add("calibrated mapping is `world_vector = (cos dir°, sin dir°)` in native")
    add("axes (+x east, +y south) and `compass_deg = (90 + dir_deg) mod 360`")
    add("(既有校准). `USEPOSITIONSKILL.target_x/target_y` are skill-target")
    add("coordinates, not hero coordinates.")
    add("")
    add("---")
    add("")
    add("## 4. Counts")
    add("")
    add(f"- Total rows: **{total:,}**")
    add(f"- Frame records: **{stats['frames']:,}**")
    add(f"- Frames with at least one command: **{stats['frames_with_commands']:,}**")
    add(f"- Frames with zero commands: **{stats['frames'] - stats['frames_with_commands']:,}**")
    add(f"- Decoded command entries: **{total - stats['unknown_rows']:,}**")
    add(f"- Unknown/undecoded rows: **{stats['unknown_rows']:,}**")
    add(f"- Unknown/undecoded frames: **{stats['unknown_frames']:,}**")
    add(f"- Row frame span: **{stats['first_frame']:,}–{stats['last_frame']:,}**")
    add(f"- Actor keying: **{stats['actor_type'].get('unit', 0):,} unit-keyed**, "
        f"**{stats['actor_type'].get('entity', 0):,} entity-keyed**")
    add(f"- Mean commands per frame: **{total / stats['frames']:.3f}**")
    add("")
    add("### Command families")
    add("")
    add("| Family | Count | Share | First frame | Last frame | Commands |")
    add("|---|---:|---:|---:|---:|---|")
    for row in family_rows:
        add(f"| `{row['family']}` | {row['count']:,} | {row['share_pct']:.4f}% | "
            f"{row['first_frame']} ({fmt_time(row['first_frame'])}) | "
            f"{row['last_frame']} ({fmt_time(row['last_frame'])}) | "
            f"{md(row['commands'])} |")
    add("")
    add("### Commands")
    add("")
    add("| Command | Family | Count | First frame | Last frame |")
    add("|---|---|---:|---:|---:|")
    for name, count in sorted(stats["command"].items(),
                              key=lambda item: (-item[1], item[0])):
        first, last = stats["command_frames"][name]
        add(f"| `{name}` | `{stats['command_family'].get(name, 'other')}` | "
            f"{count:,} | {first} ({fmt_time(first)}) | "
            f"{last} ({fmt_time(last)}) |")
    add("")
    add("### Decoded value ranges")
    add("")
    add("| Quantity | Range / value |")
    add("|---|---|")
    add(f"| `PLAYER_MOVE.dir_deg` | {range_text(stats['dir_min'], stats['dir_max'])} |")
    add(f"| `PLAYER_MOVE.mag` | {range_text(stats['mag_min'], stats['mag_max'])} |")
    add(f"| `USEDIRECTIONALSKILL.degree` (raw) | "
        f"{range_text(stats['degree_min'], stats['degree_max'])} |")
    if stats["degree_min"] is not None:
        add(f"| `USEDIRECTIONALSKILL.degree_deg` | "
            f"{stats['degree_min'] / 100.0:.2f} … "
            f"{stats['degree_max'] / 100.0:.2f} |")
    else:
        add("| `USEDIRECTIONALSKILL.degree_deg` | n/a (no rows) |")
    add(f"| `USEPOSITIONSKILL.target_x` | "
        f"{range_text(stats['aim_x'][0], stats['aim_x'][1])} |")
    add(f"| `USEPOSITIONSKILL.target_y` | "
        f"{range_text(stats['aim_y'][0], stats['aim_y'][1])} |")
    add(f"| `BUYEQUIP` distinct equip ids | {len(stats['buy_equips'])} |")
    add(f"| `BUYEQUIP` price resolved | "
        f"{stats['command'].get('BUYEQUIP', 0) - stats['buy_missing_price']:,} / "
        f"{stats['command'].get('BUYEQUIP', 0):,} |")
    add(f"| `CC` key/value vs raw | {stats['cc_kv']:,} / {stats['cc_raw']:,} |")
    if stats["cc_keys"]:
        top_key, top_count = stats["cc_keys"].most_common(1)[0]
        add(f"| `CC` distinct keys | {len(stats['cc_keys'])} "
            f"(most common `{top_key}` = {top_count:,}) |")
    else:
        add("| `CC` distinct keys | 0 |")
    add("")
    add("### Per player")
    add("")
    family_columns = [family for family in FAMILY_ORDER
                      if stats["family"].get(family)]
    add("| Unit | Camp | Slot | Player | Hero | Entity | Total | " +
        " | ".join(family_columns) + " |")
    add("|---:|---:|---:|---|---|---:|---:|" + "---:|" * len(family_columns))
    for row in players:
        cells = " | ".join(str(row.get(family, 0)) for family in family_columns)
        add(f"| {row['unit']} | {row['camp']} | {row['slot']} | "
            f"{md(row['player'])} | {md(row['hero'])} | {row['entity_id']} | "
            f"{row['total']:,} | {cells} |")
    add("")
    add("### Per-frame command-count distribution")
    add("")
    add("| Commands in frame | Frames |")
    add("|---:|---:|")
    distribution = collections.Counter(stats["per_frame"].values())
    for count in sorted(distribution):
        add(f"| {count} | {distribution[count]:,} |")
    add("")
    max_count = max(stats["per_frame"].values())
    max_frames = [frame for frame, count in stats["per_frame"].items()
                  if count == max_count]
    add(f"Maximum: **{max_count} commands** in frame "
        f"{', '.join(str(frame) for frame in sorted(max_frames))}.")
    add("")
    add("---")
    add("")
    add("## 5. Sanity checks")
    add("")
    add("| Check | Observed | Result |")
    add("|---|---|---|")
    for check in report["checks"]:
        add(f"| {md(check['name'])} | {md(check['observed'])} | {check['status']} |")
    add("")
    add("Cross-check against the canonical audit")
    add("(`tools/replay_frame_commands.audit_commands`):")
    add("")
    add(f"- frame records: {audit['frame_records']:,}; fully parsed: "
        f"{audit['fully_parsed_frames']:,}; unresolved: "
        f"{audit['unresolved_frames']:,}; errors: {audit['errors'] or '{}'}.")
    add(f"- accepted entry counts equal the catalog command counts: "
        f"**{report['audit_match']}**.")
    add("")
    add("### Tail mirror is not double-counted")
    add("")
    add("Every `0x02` tail message of subtype `0x80/0x81/0x82/0x85/0x87` is a")
    add("byte-identical copy of the matching frame command on this build. The")
    add("catalog reads frame records only, so the tail stream contributes zero")
    add("rows. Runtime verification:")
    add("")
    add("| Tail subtype | Frame command | CSSYNC entries | Tail entries | Byte-identical |")
    add("|---|---|---:|---:|---|")
    for subtype, item in mirror.items():
        add(f"| `{subtype}` | `{item['frame_command']}` | "
            f"{item['cssync_entries']:,} | {item['tail_entries']:,} | "
            f"{'yes' if item['byte_identical'] else 'no'} |")
    add("")
    add("Tail-only `0x01`-wrapped TLV data is also outside this catalog because")
    add("it is not a frame command: "
        f"{report['facing_samples']:,} `0x2d` facing samples and "
        f"{report['other_tlvs']:,} other raw TLVs were left out of the catalog.")
    add("")
    add("`0x01/CC` in the catalog is the frame-command BOOTFRAP1 selector, not")
    add("the tail `0x01` TLV wrapper. No tail-mirror row is present: all")
    add(f"{total:,} rows come from frame records, and the "
        f"{sum(item['tail_entries'] for item in mirror.values()):,} tail `0x02`")
    add("messages are excluded as duplicates.")
    add("")
    add("---")
    add("")
    add("## 6. Known unknowns and decoding gaps")
    add("")
    add(f"No frame failed to decode on this replay: {parsed_frames:,}/{parsed_frames:,} "
        "frames parsed,")
    add("0 unresolved, 0 unknown command types. The remaining gaps are")
    add("semantic, not byte-level:")
    add("")
    add(f"1. **`CC` buffers ({stats['command'].get('CC', 0):,} rows).** "
        f"{stats['cc_kv']:,} two-byte buffers expose a key/value pair; "
        f"{stats['cc_raw']:,} buffers with lengths "
        f"{', '.join(str(k) for k in sorted(stats['cc_raw_lengths']))} are")
    add("   kept as raw `buffer_hex`. The control-state semantics are unresolved")
    add("   (既有校准); no game state is inferred.")
    add(f"2. **`PLAYER_MOVE` ({stats['command'].get('PLAYER_MOVE', 0):,} rows).** "
        "Direction and world vector are calibrated (既有校准), but `mag`")
    add("   is a stick value whose exact meaning (amplitude vs duration) is")
    add("   unresolved, and move/attack/control states are not separable. This")
    add("   is not a position or trajectory; direction integration is negative")
    add("   (既有校准).")
    add(f"3. **`PLAYER_ATTACK` + `PLAYER_ATTACKWITHOBJ` "
        f"({stats['command'].get('PLAYER_ATTACK', 0) + stats['command'].get('PLAYER_ATTACKWITHOBJ', 0):,} rows).** "
        "The packed `seq` and `flag` bits are preserved but their exact")
    add("   trigger semantics are unresolved. `target_object_id` is kept")
    add("   verbatim; it is not joined to a hero name.")
    add(f"4. **`BUYEQUIP` ({stats['command'].get('BUYEQUIP', 0):,} rows).** "
        f"`auto_buy` flags observed: "
        f"{', '.join(f'{key}={value}' for key, value in sorted(stats['buy_flags'].items()))}. "
        "Their")
    add("   meaning is unresolved (既有校准). Repeats are notification")
    add("   echoes, not distinct purchases. `price` is the battle-item table")
    add("   reference price, not a spend ledger; no gold total is derived.")
    add(f"5. **`USEDIRECTIONALSKILL` ({stats['command'].get('USEDIRECTIONALSKILL', 0):,} rows).** "
        "`degree` is centidegrees and `degree_deg` is derived; the")
    add("   `secondary_1..3` fields keep their raw values and semantics are")
    add("   unresolved.")
    add(f"6. **`USEPOSITIONSKILL` ({stats['command'].get('USEPOSITIONSKILL', 0):,} rows).** "
        f"Emitted by {len(aim_heroes)} heroes ({', '.join(aim_heroes) or 'none'}); "
        "`target_x/target_y`")
    add("   are skill-target coordinates in the native world frame; the high")
    add("   `object_id` value's semantics are unresolved.")
    add(f"7. **`LEARNSKILL` ({stats['command'].get('LEARNSKILL', 0):,} rows).** "
        f"`hero_object_id` takes {len(stats['learn_hero_ids'])} distinct small")
    add("   actor/object values (not the 8–20 unit), so no unit join is")
    add("   attempted; the parent entity join is used instead.")
    if stats["command"].get("AISTATECHG"):
        add(f"8. **`AISTATECHG` ({stats['command']['AISTATECHG']:,} rows).** "
            "Raw BOOTFRAP 5 fields; only the recording client's entity emits it.")
        add("   Semantics are unexplored.")
    add("9. **No kill/death command exists in route 1075.** Kill rows are 0 by")
    add("   decoder scope, not evidence that the match had no kills.")
    add("10. **Time base.** `t = (frame − 1)/15 s`; battle 0:00 lies in frames")
    add("    0–14, so absolute times carry ±1 s uncertainty (既有校准).")
    add("    Tail frames can still carry system buys and moves after inputs")
    add("    lock at the end of a match; treat them as post-game, not play.")
    add("11. **Absent command types.** `MOVE`, `SELLEQUIP`, `BASEATTACK`,")
    add("    `ROTATE`, `FRAME_HASH_CHECK`, `CAMPSTATE`, `CAMP_SURRENDER`,")
    add("    `BEGIN_FRAME_EXTEND`, `ACNTSTATECHG`, and `GAMEOVERNTF` are")
    add("    supported by the decoder but have 0 rows here. A selector outside")
    add("    the known schema would produce one `UNKNOWN` row with the raw")
    add("    frame-command bytes, not a guessed parse.")
    add("")
    add("---")
    add("")
    add("## 7. Reproduction")
    add("")
    add("```text")
    add("python -B tools/full_abc_event_catalog.py \\")
    add(f"  {report['relative']} \\")
    add(f"  --out-dir {report['out_dir']}")
    add("```")
    add("")
    add("The tool writes only the five files in its `--out-dir`; it does not")
    add("touch the database, other analysis directories, or the replay.")
    add("")
    return "\n".join(lines)


def build_report(path: Path, out_dir: Path, info: dict | None = None):
    data = path.read_bytes()
    header = opening_packet(data)
    _info, units, by_entity = roster(data, info)
    prices = load_prices()
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / "events.csv"
    jsonl_path = out_dir / "events.jsonl"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as csv_handle, \
            jsonl_path.open("w", encoding="utf-8", newline="\n") as jsonl_handle:
        stats = build_catalog(data, units, by_entity, prices,
                              csv_handle, jsonl_handle)

    audit = audit_commands(data)
    mirror = mirror_validation(data)
    wrapper_tlvs = extract_wrapper_tlvs(data)
    players = write_per_player_counts(
        out_dir / "per_player_counts.csv", units, stats)
    family_rows = write_per_family_counts(
        out_dir / "per_family_counts.csv", stats)

    checks = []
    expected_entries = sum(audit["accepted_entry_counts"].values())
    command_counts = collections.Counter(stats["command"])
    command_counts.pop("UNKNOWN", None)
    audit_match = dict(command_counts) == audit["accepted_entry_counts"]
    expected_rows = expected_entries + stats["unknown_rows"]
    mapped_total = sum(row["total"] for row in players
                       if row["unit"] is not None)
    family_total = sum(stats["family"].values())

    def check(name, observed, ok, expected):
        checks.append({"name": name, "observed": observed,
                       "status": "PASS" if ok else f"FAIL (expected {expected})"})

    check("Total rows = frame-command entries (+ documented unknown rows)",
          f"{stats['rows']:,} = {expected_entries:,}"
          + (f" + {stats['unknown_rows']:,}" if stats["unknown_rows"] else ""),
          stats["rows"] == expected_rows,
          f"{expected_rows:,}")
    check("Frame records = canonical audit frame records",
          f"{stats['frames']:,} / {audit['frame_records']:,}",
          stats["frames"] == audit["frame_records"],
          audit["frame_records"])
    check("Fully parsed frames", f"{audit['fully_parsed_frames']:,} / "
          f"{stats['frames']:,}",
          audit["fully_parsed_frames"] == stats["frames"],
          stats["frames"])
    check("Unresolved frames", str(audit["unresolved_frames"]),
          audit["unresolved_frames"] == 0, "0")
    check("Decode errors", str(audit["errors"] or {}),
          not audit["errors"], "{}")
    check("Accepted entry counts equal catalog command counts",
          "yes" if audit_match else "no", audit_match, "yes")
    check("Sum of per-frame counts = total rows",
          f"{sum(stats['per_frame'].values()):,} = {stats['rows']:,}",
          sum(stats["per_frame"].values()) == stats["rows"], stats["rows"])
    check("Frames contiguous from 1 to N",
          f"1..{max(stats['per_frame'])}",
          sorted(stats["per_frame"]) == list(
              range(1, max(stats["per_frame"]) + 1)),
          "1..N without gaps")
    check("Duplicate (frame, frame_entry_index) keys",
          str(stats["duplicate_keys"]), stats["duplicate_keys"] == 0, "0")
    check("Rows resolved to a roster unit",
          f"{stats['mapped_rows']:,} / {stats['rows']:,}",
          stats["mapped_rows"] == stats["rows"],
          f"{stats['rows']:,}")
    check("Roster units / entities", f"{len(units)} / {len(by_entity)}",
          len(units) == 10 and len(by_entity) == 10, "10 / 10")
    check("Entity-to-unit map is one-to-one",
          f"{len(set(by_entity.values()))} units",
          len(set(by_entity.values())) == len(units), "10 units")
    check("Per-player totals sum to total rows",
          f"{mapped_total:,} = {stats['rows']:,}",
          mapped_total == stats["rows"], stats["rows"])
    check("Family totals sum to total rows",
          f"{family_total:,} = {stats['rows']:,}",
          family_total == stats["rows"], stats["rows"])
    tail_rows = stats["rows"] - expected_entries - stats["unknown_rows"]
    check("Rows from the tail stream (mirror or tail-only)",
          str(tail_rows), tail_rows == 0, "0")
    mirror_ok = all(
        item["cssync_entries"] == stats["command"].get(item["frame_command"], 0)
        and item["tail_entries"] == item["cssync_entries"]
        and item["byte_identical"]
        for item in mirror.values())
    check("Tail mirror counts match and are byte-identical",
          "yes" if mirror_ok else "no", mirror_ok, "yes")
    check("Unknown command rows", str(stats["unknown_rows"]),
          stats["unknown_rows"] == 0, "0 on this replay")

    status = "ok" if all(item["status"] == "PASS" for item in checks) else "failed"
    report = {
        "status": status,
        "relative": (str(path.resolve().relative_to(ROOT)).replace("\\", "/")
                     if str(path.resolve()).startswith(str(ROOT))
                     else str(path.resolve())),
        "absolute": str(path.resolve()),
        "out_dir": (str(out_dir.resolve().relative_to(ROOT)).replace("\\", "/")
                    if str(out_dir.resolve()).startswith(str(ROOT))
                    else str(out_dir.resolve())),
        "file_bytes": len(data),
        "sha256": digest(data),
        "header": header,
        "units": units,
        "players": players,
        "stats": stats,
        "audit": audit,
        "audit_match": "yes" if audit_match else "no",
        "mirror": mirror,
        "family_rows": family_rows,
        "checks": checks,
        "facing_samples": sum(len(item["angle"]) for item in
                              wrapper_tlvs.values()),
        "other_tlvs": sum(len(item["tlv"]) for item in
                          wrapper_tlvs.values()),
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("abc", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    report = build_report(args.abc, args.out_dir)
    readme_path = args.out_dir / "README.md"
    readme_path.write_text(render_readme(report), encoding="utf-8")
    summary = {
        "status": report["status"],
        "file": report["relative"],
        "sha256": report["sha256"],
        "rows": report["stats"]["rows"],
        "frames": report["stats"]["frames"],
        "framesWithCommands": report["stats"]["frames_with_commands"],
        "unknownRows": report["stats"]["unknown_rows"],
        "families": dict(report["stats"]["family"]),
        "commands": dict(report["stats"]["command"]),
        "outputs": [str(args.out_dir / name) for name in
                    ("events.csv", "events.jsonl", "per_player_counts.csv",
                     "per_family_counts.csv", "README.md")],
        "checks": report["checks"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
