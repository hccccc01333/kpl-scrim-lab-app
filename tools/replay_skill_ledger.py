"""Per-cast skill ledger from an .abc record stream (source tier: file-decode).

What this reads
---------------
Every ID1075 frame carries command entries.  Three of them are skill casts:

======================  ======  ===========================================
CSSYNC                    body  fields (TDR big endian)
======================  ======  ===========================================
USEOBJECTIVESKILL  0x80     12  slot, target_object, custom, seq, drag
USEDIRECTIONALSKILL 0x81    22  slot, aim_degree, object, sec1..3, seq, drag
USEPOSITIONSKILL   0x82    16  slot, aim_x, aim_y, seq, object, drag
======================  ======  ===========================================

The outer ``wObjID`` of a 0x02 entry is the casting hero's entity id, the
same value the roster blocks carry, so a cast resolves to unit (8-12 / 16-20)
and then to camp/slot/hero.  Targeted casts carry a *second* id space: the
small battle-object ids (7..65) that LEARNSKILL pins per hero (既有校准, one
constant id per hero).  Cross-referencing the two makes every targeted cast
say whether it was aimed at itself, an allied hero, an enemy hero or a
non-hero object (minion/monster/summon; this ledger does not split those).

What this does NOT read
-----------------------
* No hit, damage, control time or kill: the .abc records inputs, not results.
* No cooldown state, so the same slot may repeat faster than the real kit.
* No world position for the caster.  Only USEPOSITIONSKILL's own target point
  is a coordinate, and 0x82's ``object`` field stays unused (既有校准 marks it
  medium confidence: it is routinely garbage, e.g. 0xD1E00000).
* Slot numbers are the client's raw slot, *not* a hero skill name.  Slots 1-4
  are the hero's kit slots; 5/6/7/9/15 are non-kit keys (item active,
  summoner spell or a kit extension) and are flagged as such rather than
  guessed.  Pass ``catalog`` (heroId -> {slot: name}) to attach names.

Evidence behind the field choices
---------------------------------
* ``skill_seq`` is a per-hero cast ordinal: on every non-POV hero of the two
  11/2 samples it runs 1..N with one message per increment (count == max).
  On the POV hero it can be lossy (20260101_000000: 78 recorded of 174), so
  the ledger reports per-hero counter integrity instead of hiding it.
* ``aim_degree`` is centi-degrees.  All 2,001 directional casts of the two
  samples sit in [-17994, 17920]; divided by 100 they agree with the 0x2d
  heading samples of the same hero at mean |delta| 2.1-2.4 deg (100% within
  20 deg), which is why this module publishes ``aimDeg``.
* A frame is accepted only when its command payload decodes completely; a
  frame that fails contributes nothing and is counted in ``unresolvedFrames``.

Engine-measured outcomes (optional, separate tier)
--------------------------------------------------
The rows above are pure input.  A second, *optional* layer can record what the
client engine actually did per cast (hit / shield / control duration) when a
replay session was paused and the client process memory was read.  That layer
is never produced here: :func:`attach_engine_outcomes` only accepts
caller-supplied measurements keyed by the stable ``(frame, offset)`` pair of an
existing cast.  Missing stays ``null``; nothing is filled in, inferred or
mixed with the file-decode columns.  File-decode and engine-measured are
different tiers and must never be added together or used to validate each
other.  A ``self-anchor`` target on the file-decode side means "the object
field pointed at the caster" (self-cast *or* self-centred area skill); it is
not evidence that the caster hit itself, and an engine ``hit`` target must name
only what the engine actually recorded as touched.

Cellar limit: this is an input ledger.  Counts are cast *attempts*.  Camp
``battledetail`` numbers such as hook hits are a different measure and must
never be mixed with these columns.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import math
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import replay_time  # noqa: E402
from replay_parser import inspect_replay  # noqa: E402
from tools.replay_frame_commands import decode_commands  # noqa: E402
from tools.replay_input_timeline import build_unit_map  # noqa: E402
from tools.replay_opening_packet import opening_packet  # noqa: E402
from tools.replay_record_stream import iter_records  # noqa: E402

TIER = "file-decode"
#: Engine-measured outcome tier.  These three constants are part of the
#: contract: a per-cast ``engine`` block may only ever claim this provenance.
ENGINE_TIER = "engine-measured"
ENGINE_SOURCE = "engine-memory"
ENGINE_CONFIDENCE = "measured"
ENGINE_OUTCOME_FIELDS = ("hit", "shield", "control", "observedAt", "notes")
KIT_SLOTS = (1, 2, 3, 4)
CASTS = {
    "USEOBJECTIVESKILL": "targeted",
    "USEDIRECTIONALSKILL": "directional",
    "USEPOSITIONSKILL": "position",
}
#: Target classes of a USEOBJECTIVESKILL object field.
#:
#: ``self-anchor`` is deliberately NOT called "self": the client writes the
#: caster's own object id for every cast that has no *external unit* target,
#: which covers both true self-buffs (a shield) and self-centred area skills
#: (a slam that still hits everyone around the caster).  This ledger cannot
#: tell those apart and never claims who a self-anchored cast touched.
TARGET_KINDS = ("self-anchor", "ally-hero", "enemy-hero", "other-object", "none")

EMPTY = {"status": "no-record-stream", "frameRecords": 0, "fullyParsedFrames": 0,
         "unresolvedFrames": 0, "entryCounts": {}, "errors": {},
         "roster": [], "casts": [], "heroes": [], "census": {},
         "timeBase": {"framesPerSecond": replay_time.FPS}}


def _empty(status: str, error: str | None = None) -> dict:
    report = dict(EMPTY)
    report["status"] = status
    report["error"] = error
    return report


def load_catalog(path: Path) -> dict:
    """hero_id -> {slot: skill name}, from a two-column CSV (hero_id,slot,name)."""
    catalog: dict[int, dict[int, str]] = {}
    with Path(path).open(encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            try:
                hero_id = int(row["hero_id"])
                slot = int(row["slot"])
            except (KeyError, TypeError, ValueError):
                continue
            name = (row.get("name") or "").strip()
            if name:
                catalog.setdefault(hero_id, {})[slot] = name
    return catalog


def _object_pool(entities: dict) -> tuple[dict, set]:
    """entityId -> battle-object id from LEARNSKILL; plus the ambiguous ids.

    LEARNSKILL pins one constant object id per hero (既有校准).  When two
    entities claim the same id the mapping is unusable, so those ids are
    reported as ambiguous instead of silently resolving to one side.
    """
    pool = {}
    for entity, rows in entities.items():
        ids = {row[1] for row in rows if row[1] is not None}
        if len(ids) == 1:
            pool[entity] = ids.pop()
    counts = collections.Counter(pool.values())
    ambiguous = {value for value, times in counts.items() if times > 1}
    return ({entity: value for entity, value in pool.items() if value not in ambiguous},
            ambiguous)


def _caster_row(unit: int, roster: dict) -> dict:
    row = roster.get(unit) or {}
    return {"unit": unit, "camp": row.get("camp"), "slot": row.get("slot"),
            "entityId": row.get("entityId"), "heroId": row.get("heroId"),
            "hero": row.get("hero"), "self": bool(row.get("self"))}


def _target(kind: str, object_id, unit=None, roster=None) -> dict:
    row = (roster or {}).get(unit) or {}
    return {"kind": kind, "objectId": object_id, "unit": unit,
            "camp": row.get("camp"), "heroId": row.get("heroId"),
            "hero": row.get("hero"), "self": bool(row.get("self"))}


def _relation(caster_entity, caster_camp, target_object, object_entity, entity_unit, roster):
    """Classify a targeted cast's object id against the two id spaces.

    The only claims this returns are about the *object field*: another hero
    on the same/other camp, the caster's own object id (``self-anchor``, which
    is a self-cast **or** a self-centred area skill), a non-hero object, or no
    object at all.  It never says who got hit.
    """
    if target_object in (None, 0):
        return _target("none", target_object)
    entity = object_entity.get(target_object)
    if entity is None:
        return _target("other-object", target_object)
    unit = entity_unit.get(entity)
    target_camp = (roster.get(unit) or {}).get("camp") if unit is not None else None
    if entity == caster_entity:
        return _target("self-anchor", target_object, unit, roster)
    if caster_camp is not None and target_camp is not None:
        kind = "ally-hero" if caster_camp == target_camp else "enemy-hero"
    else:
        kind = "other-object"
    return _target(kind, target_object, unit, roster)


def skill_ledger(abc: bytes, catalog: dict | None = None) -> dict:
    """Decode one .abc into per-cast rows plus per-hero summaries."""
    try:
        header = opening_packet(abc)
    except (ValueError, struct.error) as exc:
        return _empty("no-record-stream", str(exc))
    if header["message_id"] == 1051:
        return _empty("unsupported-route",
                      "ID1051 单局路线：条目级技能语义未解码，无法出技能台账")
    from replay_profiles import resolve_profile
    profile = resolve_profile(header.get("versions"), header.get("builds"))
    if profile is None:
        versions = "/".join(header.get("versions") or [])
        return _empty("unsupported-version", f"未配置解析档案：versions={versions}")
    try:
        info = inspect_replay(abc)
    except (ValueError, struct.error) as exc:
        return _empty("no-record-stream", str(exc))
    roster_map = build_unit_map(info.get("blocks") or [])
    hero_by_entity = {block.get("entityId"): block.get("heroId")
                      for block in info.get("blocks") or []}
    roster = {}
    for unit, row in roster_map.items():
        entity = row.get("entityId")
        roster[unit] = {**row, "unit": unit, "entityId": entity,
                        "heroId": hero_by_entity.get(entity),
                        "hero": row.get("hero")}
    entity_unit = {row["entityId"]: unit for unit, row in roster.items() if row.get("entityId")}

    raw_casts: list[dict] = []
    learn = collections.defaultdict(list)
    counts: collections.Counter = collections.Counter()
    errors: collections.Counter = collections.Counter()
    frames = decoded = 0
    try:
        for record in iter_records(abc):
            if record["kind"] != "frame":
                continue
            frames += 1
            try:
                entries = decode_commands(abc[record["command_offset"]:record["end"]])
            except ValueError as exc:
                errors[str(exc)] += 1
                continue
            decoded += 1
            for entry in entries:
                name = entry["name"]
                counts[name] += 1
                fields = entry.get("fields")
                if not fields:
                    continue
                entity = entry.get("object_id")
                if name == "LEARNSKILL":
                    learn[entity].append((record["sequence"], fields.get("hero_object_id")))
                    continue
                cast_type = CASTS.get(name)
                if cast_type is None:
                    continue
                raw_casts.append({"frame": record["sequence"],
                                  "offset": record["command_offset"] + entry["offset"],
                                  "entity": entity, "type": cast_type,
                                  "slot": fields.get("slot"),
                                  "seq": fields.get("skill_seq"),
                                  "drag": fields.get("drag_flag"),
                                  "target": fields.get("object_id"),
                                  "degree": fields.get("degree"),
                                  "x": fields.get("target_x"),
                                  "y": fields.get("target_y")})
    except (ValueError, struct.error) as exc:
        return _empty("no-record-stream", str(exc))

    pool, ambiguous = _object_pool(learn)
    object_entity = {value: entity for entity, value in pool.items()}

    casts = []
    for row in raw_casts:
        unit = entity_unit.get(row["entity"])
        caster = _caster_row(unit, roster) if unit is not None else \
            {"unit": None, "camp": None, "slot": None, "entityId": row["entity"],
             "heroId": None, "hero": None, "self": False}
        slot = row["slot"]
        cast = {"frame": row["frame"],
                "t": round(replay_time.relative(row["frame"]), 3),
                "offset": row["offset"],
                "entityId": row["entity"],
                **{key: caster[key] for key in ("unit", "camp", "slot", "heroId", "hero", "self")},
                "castType": row["type"],
                "skillSlot": slot,
                "kitSlot": slot in KIT_SLOTS,
                "skillName": ((catalog or {}).get(caster.get("heroId")) or {}).get(slot),
                "seq": row["seq"], "drag": row["drag"],
                #: Engine-measured layer; stays null unless attach_engine_outcomes
                #: is given real paused-frame measurements (never 0, never inferred).
                "engine": None}
        if row["type"] == "targeted":
            cast["target"] = _relation(row["entity"], caster.get("camp"), row["target"],
                                       object_entity, entity_unit, roster)
        elif row["type"] == "directional":
            raw = row["degree"]
            cast["aimRaw"] = raw
            cast["aimDeg"] = round(raw / 100.0, 2) if isinstance(raw, int) else None
            cast["target"] = _target("none", None)
        else:
            cast["aimX"] = row["x"]
            cast["aimY"] = row["y"]
            cast["target"] = _target("none", None)
        casts.append(cast)

    heroes = []
    for unit in sorted(roster):
        row = roster[unit]
        own = [cast for cast in casts if cast["unit"] == unit]
        if not own:
            continue
        by_type = collections.Counter(cast["castType"] for cast in own)
        by_slot = collections.Counter(str(cast["skillSlot"]) for cast in own)
        targets = collections.Counter(cast["target"]["kind"] for cast in own
                                      if cast["castType"] == "targeted")
        by_slot_targets = {}
        for cast in own:
            if cast["castType"] != "targeted":
                continue
            key = str(cast["skillSlot"])
            bucket = by_slot_targets.setdefault(key, collections.Counter())
            bucket[cast["target"]["kind"]] += 1
        seqs = [cast["seq"] for cast in own if isinstance(cast["seq"], int)]
        counter = {"casts": len(own), "maxSeq": max(seqs) if seqs else None,
                   "firstSeq": min(seqs) if seqs else None,
                   "monotonic": all(left <= right for left, right in zip(seqs, seqs[1:]))}
        counter["complete"] = bool(
            counter["monotonic"] and seqs and counter["maxSeq"] == len(seqs)
            and counter["firstSeq"] in (0, 1))
        heroes.append({
            **_caster_row(unit, roster),
            "objectId": pool.get(row.get("entityId")),
            "casts": {"total": len(own), "byType": dict(by_type), "bySlot": dict(by_slot),
                      "kit": sum(count for slot, count in by_slot.items()
                                 if int(slot) in KIT_SLOTS),
                      "nonKit": sum(count for slot, count in by_slot.items()
                                    if int(slot) not in KIT_SLOTS)},
            "targets": {kind: targets.get(kind, 0) for kind in TARGET_KINDS},
            "targetsBySlot": {slot: {kind: bucket.get(kind, 0) for kind in TARGET_KINDS}
                              for slot, bucket in sorted(by_slot_targets.items())},
            "counter": counter,
            "firstFrame": own[0]["frame"], "lastFrame": own[-1]["frame"],
            "firstT": own[0]["t"], "lastT": own[-1]["t"],
        })

    census = {"total": len(casts),
              "byType": dict(collections.Counter(cast["castType"] for cast in casts)),
              "targeted": dict(collections.Counter(
                  cast["target"]["kind"] for cast in casts if cast["castType"] == "targeted")),
              "kitSlots": sum(1 for cast in casts if cast["kitSlot"]),
              "otherObjects": sorted({cast["target"]["objectId"] for cast in casts
                                      if cast["castType"] == "targeted"
                                      and cast["target"]["kind"] == "other-object"})}
    return {"status": "decoded" if decoded == frames else "partial",
            "profileId": profile["id"],
            "tier": TIER,
            "resourceVersions": header.get("versions"),
            "builds": header.get("builds"),
            "frameRecords": frames, "fullyParsedFrames": decoded,
            "unresolvedFrames": frames - decoded,
            "entryCounts": dict(counts), "errors": dict(errors),
            "objectPool": {str(entity): value for entity, value in sorted(pool.items())},
            "ambiguousObjects": sorted(ambiguous),
            "roster": [dict(row) for _, row in sorted(roster.items())],
            "heroes": heroes,
            "casts": casts,
            "census": census,
            "timeBase": {"framesPerSecond": replay_time.FPS,
                         "battleStartFrame": list(replay_time.BATTLE_START_FRAME_APPROX),
                         "note": "t ≈ frame / 15，与产品其它帧→秒换算同源（replay_time.py，±1s）。"},
            "limitations": [
                "来源层级=文件解码（.abc 输入流）：只含技能释放指令，不含命中/伤害/控制时长/冷却。",
                "次数=释放尝试次数，不等于命中次数；营地 battledetail 的命中类字段是另一套口径，不可混用。",
                "targeted 目标用 LEARNSKILL 反推的战斗对象池解析：self / ally-hero / enemy-hero / other-object（小兵/野怪/召唤物，不再细分）。",
                "skillSlot 为客户端原始槽位；1-4 为英雄技能槽，5/6/7/9/15 属非英雄技能槽（装备主动/召唤师技能等，未验证，只标注不解释）。",
                "directional 的 aimDeg = 原始 centi-degree / 100（与 0x2d 朝向样本对拍，平均差 2.1-2.4°）。",
                "position 的 (aimX, aimY) 是该次施法的世界坐标落点；0x82 的 object 字段置信度 medium，未参与目标解析。",
                "counter.complete=false 表示该英雄的技能计数不连续（POV 玩家实录会丢条目，20260101_000000 为 78/174），该行次数视为下限。",
                "engine 字段默认 null：本层只有文件解码。引擎实测（暂停帧只读客户端进程内存）是另一档来源，需由 attach_engine_outcomes 显式挂载；缺测=null，不补 0、不推断，且与文件解码禁止相加/互校。",
            ]}


class EngineOutcomeError(ValueError):
    """Engine-measured outcomes cannot be attached without guessing."""


#: Keys accepted inside one engine target reference.  The vocabulary mirrors
#: the file-decode ``cast['target']`` block so the two tiers can be displayed
#: side by side -- never merged.
ENGINE_TARGET_FIELDS = ("kind", "unit", "heroId", "hero", "objectId")


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _int_field(value, where: str, name: str, minimum: int = 0) -> int:
    if not _is_int(value) or value < minimum:
        raise EngineOutcomeError(f"{where}: {name} 必须是 >= {minimum} 的整数，收到 {value!r}")
    return value


def _number_field(value, where: str, name: str, minimum: float = 0) -> float:
    if not _is_number(value) or value < minimum:
        raise EngineOutcomeError(f"{where}: {name} 必须是 >= {minimum} 的有限数字，收到 {value!r}")
    return value


def _text_field(value, where: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EngineOutcomeError(f"{where}: {name} 必须是非空字符串，收到 {value!r}")
    return value.strip()


def _stable_key(value, where: str) -> tuple[int, int]:
    """Normalise ``(frame, offset)`` / ``"frame:offset"`` into a stable pair."""
    if isinstance(value, (tuple, list)):
        if len(value) != 2:
            raise EngineOutcomeError(f"{where}: 稳定键必须是 (frame, offset) 二元组")
        frame, offset = value
    elif isinstance(value, str):
        parts = value.strip().split(":")
        if len(parts) != 2:
            raise EngineOutcomeError(f"{where}: 稳定键字符串必须是 'frame:offset'，收到 {value!r}")
        try:
            frame, offset = int(parts[0]), int(parts[1])
        except ValueError:
            raise EngineOutcomeError(f"{where}: 稳定键 'frame:offset' 必须都是整数，收到 {value!r}") from None
    else:
        raise EngineOutcomeError(
            f"{where}: 稳定键只支持 (frame, offset) 二元组或 'frame:offset' 字符串，"
            f"收到 {type(value).__name__}")
    return (_int_field(frame, where, "frame"), _int_field(offset, where, "offset"))


def _normalise_target(value, where: str):
    """Validate an engine target reference; never rename ``self-anchor``."""
    if value is None:
        return None
    if isinstance(value, str):
        return _text_field(value, where, "target")
    if _is_int(value):
        return _int_field(value, where, "target")
    if not isinstance(value, dict):
        raise EngineOutcomeError(
            f"{where}: target 只支持字符串 / 整数 / 对象 {ENGINE_TARGET_FIELDS} / null，"
            f"收到 {type(value).__name__}")
    if not value:
        raise EngineOutcomeError(f"{where}: target 对象不能为空")
    unknown = sorted(set(value) - set(ENGINE_TARGET_FIELDS))
    if unknown:
        raise EngineOutcomeError(f"{where}: target 含未知字段 {unknown}，只允许 {list(ENGINE_TARGET_FIELDS)}")
    clean = {}
    for key, item in value.items():
        if item is None:
            clean[key] = None
        elif key in ("kind", "hero"):
            clean[key] = _text_field(item, where, f"target.{key}")
        else:
            clean[key] = _int_field(item, where, f"target.{key}")
    return clean


def _normalise_hit(value, where: str):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise EngineOutcomeError(f"{where}.hit: 必须是对象或 null")
    if not value:
        raise EngineOutcomeError(f"{where}.hit: 空对象无意义，未命中请用 {{'hit': false}}，未采样请用 null")
    unknown = sorted(set(value) - {"hit", "target", "evidence"})
    if unknown:
        raise EngineOutcomeError(f"{where}.hit: 含未知字段 {unknown}，只允许 hit/target/evidence")
    hit = value.get("hit")
    if hit is not None and not isinstance(hit, bool):
        raise EngineOutcomeError(f"{where}.hit.hit: 必须是 true/false/null，收到 {hit!r}")
    target = _normalise_target(value.get("target"), f"{where}.hit.target")
    evidence = value.get("evidence")
    if evidence is not None:
        evidence = _text_field(evidence, f"{where}.hit", "evidence")
    if hit is None and target is None and evidence is None:
        raise EngineOutcomeError(f"{where}.hit: hit/target/evidence 至少要有一项非 null；缺测请用 null")
    return {"hit": hit, "target": target, "evidence": evidence}


def _normalise_shield(value, where: str):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise EngineOutcomeError(f"{where}.shield: 必须是对象或 null")
    if not value:
        raise EngineOutcomeError(f"{where}.shield: 空对象无意义，未给盾请用 null")
    unknown = sorted(set(value) - {"amount", "target"})
    if unknown:
        raise EngineOutcomeError(f"{where}.shield: 含未知字段 {unknown}，只允许 amount/target")
    amount = value.get("amount")
    if amount is not None:
        amount = _number_field(amount, f"{where}.shield", "amount")
    target = _normalise_target(value.get("target"), f"{where}.shield.target")
    if amount is None and target is None:
        raise EngineOutcomeError(f"{where}.shield: amount/target 至少要有一项非 null；缺测请用 null")
    return {"amount": amount, "target": target}


def _normalise_control(value, where: str):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise EngineOutcomeError(f"{where}.control: 必须是对象或 null")
    if not value:
        raise EngineOutcomeError(f"{where}.control: 空对象无意义，未控制请用 null")
    unknown = sorted(set(value) - {"durationS", "target"})
    if unknown:
        raise EngineOutcomeError(f"{where}.control: 含未知字段 {unknown}，只允许 durationS/target")
    duration = value.get("durationS")
    if duration is not None:
        duration = _number_field(duration, f"{where}.control", "durationS")
    target = _normalise_target(value.get("target"), f"{where}.control.target")
    if duration is None and target is None:
        raise EngineOutcomeError(f"{where}.control: durationS/target 至少要有一项非 null；缺测请用 null")
    return {"durationS": duration, "target": target}


def _normalise_observed_at(value, where: str):
    if value is None:
        raise EngineOutcomeError(
            f"{where}: 已采样块必须提供 observedAt（frame/clockMs/snapshot 至少一项），"
            "没有采样证据就不算引擎实测")
    if not isinstance(value, dict) or not value:
        raise EngineOutcomeError(f"{where}: observedAt 必须是非空对象")
    unknown = sorted(set(value) - {"frame", "clockMs", "snapshot"})
    if unknown:
        raise EngineOutcomeError(f"{where}: observedAt 含未知字段 {unknown}，只允许 frame/clockMs/snapshot")
    frame = value.get("frame")
    if frame is not None:
        frame = _int_field(frame, f"{where}.observedAt", "frame")
    clock_ms = value.get("clockMs")
    if clock_ms is not None:
        clock_ms = _number_field(clock_ms, f"{where}.observedAt", "clockMs")
    snapshot = value.get("snapshot")
    if snapshot is not None:
        snapshot = _text_field(snapshot, f"{where}.observedAt", "snapshot")
    if frame is None and clock_ms is None and snapshot is None:
        raise EngineOutcomeError(f"{where}.observedAt: frame/clockMs/snapshot 至少要有一项非 null")
    return {"frame": frame, "clockMs": clock_ms, "snapshot": snapshot}


def _normalise_notes(value, where: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise EngineOutcomeError(f"{where}.notes: 必须是字符串列表")
    return [_text_field(item, f"{where}.notes", "note") for item in value]


def _normalise_outcome(payload, where: str) -> dict:
    """Validate one caller-supplied engine measurement block (fail-closed)."""
    if not isinstance(payload, dict):
        raise EngineOutcomeError(f"{where}: outcome 必须是对象，收到 {type(payload).__name__}")
    unknown = sorted(set(payload) - set(ENGINE_OUTCOME_FIELDS))
    if unknown:
        raise EngineOutcomeError(f"{where}: 含未知字段 {unknown}，只允许 {list(ENGINE_OUTCOME_FIELDS)}")
    block = {"tier": ENGINE_TIER, "source": ENGINE_SOURCE, "confidence": ENGINE_CONFIDENCE,
             "hit": _normalise_hit(payload.get("hit"), where),
             "shield": _normalise_shield(payload.get("shield"), where),
             "control": _normalise_control(payload.get("control"), where),
             "observedAt": _normalise_observed_at(payload.get("observedAt"), where),
             "notes": _normalise_notes(payload.get("notes"), where)}
    if not any(block[field] is not None for field in ("hit", "shield", "control")):
        raise EngineOutcomeError(
            f"{where}: 已采样块至少要包含 hit/shield/control 之一；全 null 请保持 engine=null，"
            "不要伪造一次采样")
    return block


def _row_from_list(item, position: int) -> tuple[str, tuple[int, int], dict]:
    where = f"outcomes.casts[{position}]"
    if not isinstance(item, dict):
        raise EngineOutcomeError(f"{where}: 必须是对象")
    if "frame" not in item or "offset" not in item:
        raise EngineOutcomeError(f"{where}: 缺少 frame/offset 稳定键")
    frame = _int_field(item["frame"], where, "frame")
    offset = _int_field(item["offset"], where, "offset")
    payload = {key: value for key, value in item.items() if key not in ("frame", "offset")}
    return where, (frame, offset), payload


def _rows_from_outcomes(outcomes) -> list[tuple[str, tuple[int, int], dict]]:
    """Accept the three documented injection shapes, all fail-closed."""
    if outcomes is None:
        return []
    if isinstance(outcomes, list):
        return [_row_from_list(item, position) for position, item in enumerate(outcomes)]
    if isinstance(outcomes, dict):
        if "casts" in outcomes:
            unknown = sorted(set(outcomes) - {"casts", "tier", "source", "confidence"})
            if unknown:
                raise EngineOutcomeError(f"outcomes: 未知顶层字段 {unknown}，只允许 casts/tier/source/confidence")
            for field, expected in (("tier", ENGINE_TIER), ("source", ENGINE_SOURCE),
                                    ("confidence", ENGINE_CONFIDENCE)):
                if field in outcomes and outcomes[field] != expected:
                    raise EngineOutcomeError(
                        f"outcomes.{field}: 必须是 {expected!r}，收到 {outcomes[field]!r}；"
                        "其它来源层级禁止挂进 engine 块")
            rows = outcomes["casts"]
            if not isinstance(rows, list):
                raise EngineOutcomeError("outcomes.casts: 必须是列表")
            return [_row_from_list(item, position) for position, item in enumerate(rows)]
        rows = []
        for key, payload in outcomes.items():
            stable = _stable_key(key, f"outcomes[{key!r}]")
            where = f"outcomes[{key!r}]"
            if not isinstance(payload, dict):
                raise EngineOutcomeError(f"{where}: outcome 必须是对象，收到 {type(payload).__name__}")
            rows.append((where, stable, payload))
        return rows
    raise EngineOutcomeError(
        f"outcomes: 只支持列表 / {{'casts': [...]}} / {{'frame:offset': {{...}}}}，"
        f"收到 {type(outcomes).__name__}")


def attach_engine_outcomes(report: dict, outcomes) -> dict:
    """Return a copy of ``report`` with engine-measured blocks on matching casts.

    Pure and order-preserving: ``report`` and ``outcomes`` are never mutated,
    casts stay in their original order, and every cast that was not measured
    keeps ``engine: null``.

    ``outcomes`` is indexed by the stable cast key (``frame`` + ``offset``),
    accepted as any of::

        {"casts": [{"frame": 4212, "offset": 88123, "hit": {...}, ...}, ...]}
        [{"frame": 4212, "offset": 88123, ...}]          # same rows, bare list
        {"4212:88123": {...}, (4212, 88123): {...}}      # direct key mapping

    One block looks like::

        {"hit":     null | {"hit": true|false|null, "target": ..., "evidence": ...},
         "shield":  null | {"amount": number|null, "target": ...},
         "control": null | {"durationS": number|null, "target": ...},
         "observedAt": {"frame": int|null, "clockMs": number|null, "snapshot": str|null},
         "notes": ["..."]}

    Unknown keys / duplicate keys / unknown fields / an all-null outcome all
    raise :class:`EngineOutcomeError` (a ``ValueError``): this function never
    guesses which cast a measurement belongs to, and never fabricates a value.
    """
    if not isinstance(report, dict):
        raise EngineOutcomeError(f"report 必须是对象，收到 {type(report).__name__}")
    casts = report.get("casts")
    if not isinstance(casts, list):
        raise EngineOutcomeError("report['casts'] 必须是列表")
    positions: dict[tuple[int, int], int] = {}
    for position, cast in enumerate(casts):
        where = f"report.casts[{position}]"
        if not isinstance(cast, dict):
            raise EngineOutcomeError(f"{where}: 必须是对象")
        key = (_int_field(cast.get("frame"), where, "frame"),
               _int_field(cast.get("offset"), where, "offset"))
        if key in positions:
            raise EngineOutcomeError(
                f"report.casts[{positions[key]}] 与 {where} 的稳定键重复：frame={key[0]}, offset={key[1]}")
        positions[key] = position

    attached: dict[int, dict] = {}
    for where, key, payload in _rows_from_outcomes(outcomes):
        position = positions.get(key)
        if position is None:
            raise EngineOutcomeError(
                f"{where}: 未知 cast 稳定键 frame={key[0]}, offset={key[1]}；"
                "outcomes 只能挂到报告里已存在的 frame+offset 上")
        if position in attached:
            raise EngineOutcomeError(
                f"{where}: cast frame={key[0]}, offset={key[1]} 已被前面的 outcome 挂载过，禁止重复")
        existing = casts[position].get("engine")
        if existing is not None:
            raise EngineOutcomeError(
                f"{where}: cast frame={key[0]}, offset={key[1]} 已有 engine 实测块，禁止覆盖")
        attached[position] = _normalise_outcome(payload, where)

    new_casts = [dict(cast, engine=attached.get(position, cast.get("engine")))
                 for position, cast in enumerate(casts)]
    measured = sum(1 for cast in new_casts if cast.get("engine"))
    result = dict(report)
    result["casts"] = new_casts
    result["engineOutcomes"] = {
        "tier": ENGINE_TIER, "source": ENGINE_SOURCE, "confidence": ENGINE_CONFIDENCE,
        "castsMeasured": measured, "castsTotal": len(new_casts),
        "note": ("引擎实测=回放暂停帧只读客户端进程内存的离散采样；与文件解码不是同一口径，"
                 "禁止相加或互相校验；未采样的 cast 保持 engine=null。"),
    }
    return result


def engine_outcomes_summary(report: dict) -> dict:
    """Provenance-style summary of the engine layer (works on a bare ledger)."""
    casts = report.get("casts") or []
    measured = sum(1 for cast in casts if isinstance(cast, dict) and cast.get("engine"))
    if measured:
        note = ("引擎实测=回放暂停帧只读客户端进程内存的离散采样；与文件解码不是同一口径，"
                "禁止相加或互相校验；未采样的 cast 保持 engine=null。")
    else:
        note = ("本局未挂载引擎实测数据：逐次施法 engine 均为 null（缺测=null，不补 0、不推断）。"
                "引擎实测与文件解码是两档来源，禁止相加或互校。")
    return {"tier": ENGINE_TIER, "source": ENGINE_SOURCE, "confidence": ENGINE_CONFIDENCE,
            "castsMeasured": measured, "castsTotal": len(casts), "note": note}


def load_engine_outcomes(path: Path):
    """Read an outcomes JSON file (shape validated by attach_engine_outcomes)."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


CSV_COLUMNS = ("frame", "time_s", "camp", "unit", "hero_id", "hero", "entity_id",
               "self", "cast_type", "skill_slot", "kit_slot", "skill_name",
               "skill_seq", "drag", "target_kind", "target_object", "target_unit",
               "target_camp", "target_hero_id", "target_hero", "aim_deg", "aim_x", "aim_y",
               # Engine-measured layer; empty cell = not measured (never 0).
               "engine_hit", "engine_hit_target", "engine_shield",
               "engine_shield_target", "engine_control_s", "engine_control_target",
               "engine_observed_frame", "engine_observed_clock_ms", "engine_snapshot")


def _engine_target_text(value) -> str:
    """CSV rendering of an engine target reference (empty = not measured)."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        return str(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def engine_cells(cast: dict) -> dict:
    """CSV cells of the engine layer; absent measurements stay empty strings."""
    engine = cast.get("engine")
    if not isinstance(engine, dict):
        engine = {}
    hit = engine.get("hit") if isinstance(engine.get("hit"), dict) else {}
    shield = engine.get("shield") if isinstance(engine.get("shield"), dict) else {}
    control = engine.get("control") if isinstance(engine.get("control"), dict) else {}
    observed = engine.get("observedAt") if isinstance(engine.get("observedAt"), dict) else {}
    hit_value = hit.get("hit")
    return {"engine_hit": "" if hit_value is None else int(bool(hit_value)),
            "engine_hit_target": _engine_target_text(hit.get("target")),
            "engine_shield": "" if shield.get("amount") is None else shield.get("amount"),
            "engine_shield_target": _engine_target_text(shield.get("target")),
            "engine_control_s": "" if control.get("durationS") is None else control.get("durationS"),
            "engine_control_target": _engine_target_text(control.get("target")),
            "engine_observed_frame": "" if observed.get("frame") is None else observed.get("frame"),
            "engine_observed_clock_ms": "" if observed.get("clockMs") is None else observed.get("clockMs"),
            "engine_snapshot": observed.get("snapshot") or ""}


def cast_rows(report: dict):
    """Flatten cast dicts into the CSV column order."""
    for cast in report.get("casts") or []:
        target = cast.get("target") or {}
        yield {"frame": cast["frame"], "time_s": cast["t"], "camp": cast["camp"],
               "unit": cast["unit"], "hero_id": cast["heroId"], "hero": cast["hero"],
               "entity_id": cast["entityId"], "self": int(bool(cast["self"])),
               "cast_type": cast["castType"], "skill_slot": cast["skillSlot"],
               "kit_slot": int(bool(cast["kitSlot"])), "skill_name": cast.get("skillName") or "",
               "skill_seq": cast["seq"], "drag": cast["drag"],
               "target_kind": target.get("kind"), "target_object": target.get("objectId"),
               "target_unit": target.get("unit"), "target_camp": target.get("camp"),
               "target_hero_id": target.get("heroId"), "target_hero": target.get("hero") or "",
               "aim_deg": cast.get("aimDeg"), "aim_x": cast.get("aimX"),
               "aim_y": cast.get("aimY"), **engine_cells(cast)}


def write_csv(report: dict, path: Path) -> int:
    rows = list(cast_rows(report))
    with Path(path).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--csv", type=Path, help="每次释放一行的 CSV 导出")
    parser.add_argument("--json", type=Path, help="完整台账 JSON（含逐英雄汇总）")
    parser.add_argument("--catalog", type=Path, help="hero_id,slot,name 技能名表（可选）")
    parser.add_argument("--engine-outcomes", type=Path,
                        help="引擎实测结果 JSON（可选，单文件；按 frame+offset 挂到已有 cast，缺测=null）")
    parser.add_argument("--summary", action="store_true", help="只打印逐英雄汇总")
    args = parser.parse_args()
    catalog = load_catalog(args.catalog) if args.catalog else None
    engine_outcomes = None
    if args.engine_outcomes:
        if len(args.files) != 1:
            parser.error("--engine-outcomes 只支持单文件")
        try:
            engine_outcomes = load_engine_outcomes(args.engine_outcomes)
        except (OSError, ValueError) as exc:
            print(f"[engine-outcomes] 读取失败：{exc}", file=sys.stderr)
            return 2
    reports = []
    for path in args.files:
        try:
            report = skill_ledger(path.read_bytes(), catalog)
        except (ValueError, struct.error) as exc:
            reports.append({"file": str(path), "status": "error", "error": str(exc)})
            continue
        if engine_outcomes is not None:
            try:
                report = attach_engine_outcomes(report, engine_outcomes)
            except EngineOutcomeError as exc:
                print(f"[engine-outcomes] {path}：{exc}", file=sys.stderr)
                return 2
        reports.append({"file": str(path), **report})
    if args.csv:
        if len(reports) != 1:
            parser.error("--csv 只支持单文件")
        written = write_csv(reports[0], args.csv)
        print(f"[csv] {written} casts -> {args.csv}", file=sys.stderr)
    if args.json:
        payload = reports[0] if len(reports) == 1 else reports
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.summary:
        for report in reports:
            print(json.dumps({"file": report["file"], "status": report.get("status"),
                              "frameRecords": report.get("frameRecords"),
                              "census": report.get("census"),
                              "heroes": [{"unit": row["unit"], "camp": row["camp"],
                                          "hero": row["hero"], "objectId": row["objectId"],
                                          "casts": row["casts"], "targets": row["targets"],
                                          "complete": row["counter"]["complete"]}
                                         for row in report.get("heroes") or []]},
                             ensure_ascii=False, indent=1))
    else:
        print(json.dumps([{"file": report["file"], "status": report.get("status"),
                           "error": report.get("error"),
                           "frameRecords": report.get("frameRecords"),
                           "unresolvedFrames": report.get("unresolvedFrames"),
                           "census": report.get("census")} for report in reports],
                          ensure_ascii=False, indent=1))
    return int(any(report.get("status") not in ("decoded",) for report in reports))


if __name__ == "__main__":
    raise SystemExit(main())
