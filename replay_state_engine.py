"""Build a per-second replay state document from a single ``.abc``/``.ope`` pair.

Everything this module emits is decoded from the replay container and its frame
commands.  The container does **not** carry combat outcomes (kills, deaths,
gold income, HP), so those fields are ``None`` with a reason instead of being
estimated — see ``MISSING`` below.

Decoded and usable per player:

    roster      hero / camp / slot / entity id / end rating / win side / MVP
    purchases   frame-precise BUYEQUIP ledger joined with the item price table
    gold spent  cumulative first-seen purchase value (a spend ledger, not income)
    level       1 + LEARNSKILL count up to that second (HoK caps at 15)
    skills      LEARNSKILL order, per slot
    actions     per-second move / attack / skill / cc / aim counts
    events      the frame-precise command stream itself

Not in the file, therefore not invented:

    kills / deaths / assists over time, gold income, HP, continuous positions.

The output schema is ``kpl-replay-state-v1``; every derived series carries a
``tier`` so a consumer can tell decoded facts from derived ones.

CLI::

    python replay_state_engine.py --abc <file.abc> [--ope <file.ope>] [--out DIR]
    python replay_state_engine.py --abc <file.abc> --print-json
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import io
import json
import sys
import tempfile
from pathlib import Path

SCHEMA = "kpl-replay-state-v1"
ROOT = Path(__file__).resolve().parent
FAMILIES = ("movement", "attack", "skill", "buy", "cc", "aim")

# Inner commands of a CSDT_FRAPBOOT_CC packet.  The family is named `cc` in the
# decoder, but it carries direction / stop / attack-position commands, not crowd
# control; see README.md.
CC_INNER = {
    "2d": "direction", "03": "stopMove", "2c": "attackPos",
    "01": "positionMove",
}
MAX_LEVEL = 15
FRAME_HZ = 15.0

# Reason strings are surfaced in the document so a reader never has to guess why
# a column is empty.
MISSING = {
    "kills": "回放容器只记录输入命令，没有击杀归属；只有 1251 的胜负/MVP/评分。",
    "deaths": "同上：没有死亡事件时间轴。",
    "assists": "同上：没有助攻记录。",
    "goldIncome": "尾部购买镜像没有金币收入事件，无法重建收入账本；只有支出账本。",
    "hp": "容器不含 HP 字段。",
    "positions": "连续轨迹不可得：移动指令积分实测残差/位移 0.94–1.00（无预测力，README.md）；只有稀疏坐标锚点，见 anchors。",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _price_table() -> dict[int, int]:
    """item_id -> buy price, from the two shipped tables (csv wins, json fills)."""
    prices: dict[int, int] = {}
    table = ROOT / "data/replays/_analysis/datasets/pvp_item.json"
    try:
        for row in json.loads(table.read_text(encoding="utf-8")):
            item_id = row.get("item_id")
            price = row.get("total_price")
            if item_id is not None and price:
                prices[int(item_id)] = int(price)
    except (OSError, ValueError):
        pass
    csv_table = ROOT / "data/replays/_analysis/datasets/agent_equip_prices.csv"
    try:
        with csv_table.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                try:
                    item_id = int(row.get("item_id") or 0)
                    price = int(row.get("buy_price") or 0)
                except ValueError:
                    continue
                if item_id and price:
                    prices.setdefault(item_id, price)
    except OSError:
        pass
    return prices


def _item_names() -> dict[int, str]:
    names: dict[int, str] = {}
    table = ROOT / "data/replays/_analysis/datasets/pvp_item.json"
    try:
        for row in json.loads(table.read_text(encoding="utf-8")):
            if row.get("item_id") is not None:
                names[int(row["item_id"])] = row.get("item_name") or ""
    except (OSError, ValueError):
        pass
    return names


KEEP_KEYS = ("time_s", "family", "command", "entity_id", "camp", "slot",
             "player", "hero", "fields")


class _NullSink:
    """Swallow the CSV catalogue: the state document never needs it."""

    def write(self, text):
        return len(text)


class _RowSink:
    """Collect only the compact row fields the builder consumes."""

    def __init__(self):
        self.rows: list[dict] = []

    def write(self, text):
        try:
            row = json.loads(text)
        except ValueError:
            return len(text)
        self.rows.append({key: row.get(key) for key in KEEP_KEYS})
        return len(text)


def _decode_events(data: bytes) -> tuple[list[dict], dict]:
    """Decode the frame-command stream entirely in memory (no temp files).

    ``build_report`` writes ~59 MB of CSV/JSONL per replay, which fails on a
    full disk and is thrown away anyway.  Driving ``build_catalog`` with
    in-memory sinks keeps the same decoder and produces the same rows.
    """
    sys.path.insert(0, str(ROOT / "tools"))
    from full_abc_event_catalog import (  # noqa: WPS433
        build_catalog, load_prices, roster)

    _header, units, by_entity = roster(data, None)
    prices = load_prices()
    rows = _RowSink()
    stats = build_catalog(data, units, by_entity, prices, _NullSink(), rows)
    return rows.rows, {"stats": stats, "units": len(units)}


def _as_int(value, default=0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def scan_bytes(raw: bytes, ope_raw: bytes | None = None) -> dict:
    """Decode one replay given its bytes (no filesystem access)."""
    import replay_parser as rp  # noqa: WPS433

    report = rp.inspect_abc(raw, hero_names=None)
    ope_report = None
    if ope_raw:
        try:
            ope_report = rp.parse_ope_bytes(ope_raw)
        except rp.ReplayFormatError:
            ope_report = None
    rows, _catalog = _decode_events(raw)
    init_block = None
    init_block_error = None
    try:
        from abc_init_block import locate, kv_pairs, known_fields  # noqa: WPS433
        located = locate(raw)
        if located is not None:
            init_block = known_fields(located, kv_pairs(raw, located))
            init_block["scalarStart"] = located["scalarStart"]
            init_block["kvCount"] = located["kvCount"]
    except Exception as error:  # noqa: BLE001 - a different container layout must not break decode
        # 换个容器布局不该让整局解码失败，但也不能静默吞掉：把原因带出去，
        # matchConfig 为 None 时至少能看出是「解析失败」还是「本来没有」。
        init_block = None
        init_block_error = f"{type(error).__name__}: {error}"
    ope_summary = None
    if ope_raw:
        ope_summary = _decode_ope(ope_raw, _as_int((report.get("header") or {}).get("totalFrameNum")))
    return {"abc_report": report, "ope_report": ope_report, "events": rows,
            "abc_sha256": hashlib.sha256(raw).hexdigest(), "abc_bytes": len(raw),
            "ope_bytes": len(ope_raw) if ope_raw else 0,
            "ope_summary": ope_summary, "init_block": init_block,
            "init_block_error": init_block_error}


OPE_GROUPS = {    "TouchOpe": "touch", "MoveOpe": "move", "PredictMoveOpe": "move",
    "SkillUseOpe": "skill", "SkilOpe": "skill", "SkillSlotOpe": "skill",
    "SkillCancelOpe": "skill", "DirSkillOpe": "skill", "SkillBtnForceUpOpe": "skill",
    "RefreshSkillBtnStatusOpe": "skill", "SkillHitRate": "skill",
    "UIEventOpe": "ui", "UIViewChangeOpe": "ui", "UILayout": "ui",
    "BtnBrokenContactOpe": "ui",
}


def _decode_ope(ope_raw: bytes, total_frames: int = 0) -> dict | None:
    """Decode the .ope operator stream into the state document's ``ope`` block.

    The strict layout parse reaches end-of-stream on the observed samples
    (record boundaries are then decode facts).  A stream that still walls
    falls back to the DP-with-repair mode, where every boundary shift is
    reported in ``repairs`` instead of being applied silently.
    """
    import zlib
    import replay_parser as rp  # noqa: WPS433
    import operator_stream as ops  # noqa: WPS433

    try:
        inner = zlib.decompressobj(-15).decompress(ope_raw[1:])
        _pos, _declared, stream = rp._locate_second_layer(inner)
    except (zlib.error, rp.ReplayFormatError, ValueError):
        return None

    try:
        records, ambiguities, _start = ops._parse_with_start(stream, None)
    except ops.OperatorStreamError:
        records = None
    if records is not None:
        return {
            "mode": "strict-layouts",
            "streamBytes": len(stream),
            "records": len(records),
            "typeCounts": dict(sorted(collections.Counter(
                r["typeName"] for r in records).items())),
            "ambiguousChoices": ambiguities,
            "tentativeRecords": sum(1 for r in records if r["tentative"]),
            "tentativeBytes": sum(r["size"] for r in records if r["tentative"]),
            "streamEnd": max((r["offset"] + r["size"] for r in records),
                             default=0),
            "truncatedTail": bool(any(r.get("truncated") for r in records)),
            "caveat": ("记录类型与边界已按 0x00–0x19 布局解码到流尾；"
                       "payload 字段名除 frame/unityFrame 外均为推断，"
                       "因此不按秒分桶，也不把 .ope 记录排成对局时间轴。"),
        }

    summary = ops.repair_summary(stream, 0)
    records, repairs, _end = ops.parse_with_repair(stream, 0)
    with_frame = sum(1 for record in records if "frame" in record["fields"])
    unplaced = len(records) - with_frame
    return {
        "mode": summary["mode"],
        "records": summary["recordCount"],
        "typeCounts": summary["typeCounts"],
        "repairCount": summary["repairCount"],
        "repairs": repairs,
        "coveragePct": summary["coveragePct"],
        "reachedEnd": summary["reachedEnd"],
        "trailingBytes": summary["trailingBytes"],
        "unitySamples": summary["unitySamples"],
        "unityRegressions": summary["unityRegressions"],
        "frameRange": summary["frameRange"],
        "recordsWithFrame": with_frame,
        "recordsWithoutFrame": unplaced,
        "caveat": ("边界修复模式：每个跳过/回退的字节都在 repairs 里记账；"
                   "payload 字段名多为推断，不按秒分桶。"),
        "note": summary["note"],
    }


def scan(abc: Path, ope: Path | None = None) -> dict:
    """Decode one replay from disk."""
    return scan_bytes(abc.read_bytes(),
                      ope.read_bytes() if ope and ope.exists() else None)


def build(state: dict, items: dict[int, int], names: dict[int, str]) -> dict:
    """Turn a :func:`scan` result into the ``kpl-replay-state-v1`` document."""
    report = state["abc_report"]
    rows = state["events"]
    blocks = report.get("blocks") or []
    mvp = report.get("mvpScore") or {}
    winning = mvp.get("winningCamp")

    # --- per-entity identity ------------------------------------------------
    entities: dict[int, dict] = {}
    for block in blocks:
        entity = _as_int(block.get("entityId"))
        if not entity:
            continue
        entities[entity] = {
            "entityId": entity,
            "heroId": block.get("heroId"),
            "hero": block.get("heroName") or "",
            "player": block.get("name") or "",
            "camp": block.get("camp"),
            "team": {1: "blue", 2: "red"}.get(block.get("camp"), ""),
            "slot": block.get("position"),
            "rating": block.get("score"),
            "isSelf": bool(block.get("self")),
            "isBot": bool(block.get("bot")),
            "win": None,
        }
    for entity, info in entities.items():
        if winning:
            info["win"] = info["team"] == winning
        info["mvp"] = entity == mvp.get("winMvpEntityId")

    # --- per-second accumulation -------------------------------------------
    counts: dict[tuple[int, int], collections.Counter] = collections.defaultdict(
        collections.Counter)
    purchases: list[dict] = []
    learns: list[dict] = []
    seen_items: set[tuple[int, int]] = set()
    spend: collections.Counter = collections.Counter()
    skill_track: dict[int, list] = collections.defaultdict(list)
    last_second = 0
    cc_counts: dict[int, collections.Counter] = collections.defaultdict(collections.Counter)

    for row in rows:
        entity = _as_int(row.get("entity_id"))
        if not entity:
            continue
        second = _as_int(row.get("time_s"))
        last_second = max(last_second, second)
        if entity not in entities:
            entities[entity] = {
                "entityId": entity, "heroId": None,
                "hero": row.get("hero") or "", "player": row.get("player") or "",
                "camp": _as_int(row.get("camp")) or None,
                "team": {1: "blue", 2: "red"}.get(_as_int(row.get("camp")), ""),
                "slot": _as_int(row.get("slot")) or None, "rating": None,
                "isSelf": False, "isBot": bool(row.get("actor_type") == "bot"),
                "win": None, "mvp": False,
            }
        family = row.get("family") or ""
        if family in FAMILIES:
            counts[(second, entity)][family] += 1
        fields = row.get("fields")
        if not isinstance(fields, dict):
            fields = {}
        if family == "cc":
            # ``CC`` here is CSDT_FRAPBOOT_CC, a client command-sync packet — not
            # crowd control.  Split it by inner command so the label can never be
            # read as a control effect.
            inner = str(fields.get("buffer_hex") or "")[:2].lower()
            group = CC_INNER.get(inner, "other")
            cc_counts[entity][group] += 1
        command = row.get("command")
        if command == "BUYEQUIP":
            equip = fields.get("equip_id")
            if equip is None:
                continue
            equip = _as_int(equip)
            key = (entity, equip)
            first = key not in seen_items
            price = items.get(equip)
            if first:
                seen_items.add(key)
                if price:
                    spend[entity] += price
                purchases.append({
                    "t": round(float(row.get("time_s") or 0), 3),
                    "entityId": entity, "equipId": equip,
                    "name": names.get(equip, ""),
                    "price": price, "tier": "decoded",
                })
        elif command == "LEARNSKILL":
            slot = _as_int(fields.get("slot"))
            # Every LEARNSKILL is one skill point, including repeated upgrades of
            # the same slot, so hero level = 1 + total learn events.
            learns.append({
                "t": round(float(row.get("time_s") or 0), 3),
                "entityId": entity, "slot": slot, "tier": "decoded",
            })
            skill_track[entity].append(slot)

    # --- assemble the per-second timeline ----------------------------------
    duration = max(last_second + 1, 1)
    timeline: list[dict] = []
    learn_cursor = {entity: 0 for entity in entities}
    buy_cursor = {entity: 0 for entity in entities}
    ordered_learns = collections.defaultdict(list)
    for item in sorted(learns, key=lambda row: row["t"]):
        ordered_learns[item["entityId"]].append(item)
    ordered_buys = collections.defaultdict(list)
    for item in sorted(purchases, key=lambda row: row["t"]):
        ordered_buys[item["entityId"]].append(item)
    running_spend = collections.Counter()

    for second in range(duration):
        players = []
        for entity in sorted(entities):
            while (learn_cursor[entity] < len(ordered_learns[entity])
                   and ordered_learns[entity][learn_cursor[entity]]["t"] <= second):
                learn_cursor[entity] += 1
            while (buy_cursor[entity] < len(ordered_buys[entity])
                   and ordered_buys[entity][buy_cursor[entity]]["t"] <= second):
                item = ordered_buys[entity][buy_cursor[entity]]
                if item["price"]:
                    running_spend[entity] += item["price"]
                buy_cursor[entity] += 1
            level = min(1 + learn_cursor[entity], MAX_LEVEL)
            cell = counts.get((second, entity)) or collections.Counter()
            # Compact keys: the per-second grid is the bulk of the document, and
            # equipment/skill history already lives in ``events``.
            players.append({
                "e": entity,
                "lv": level,
                "gs": running_spend[entity] or None,
                "m": cell["movement"], "a": cell["attack"],
                "s": cell["skill"], "c": cell["cc"], "am": cell["aim"],
            })
        timeline.append({"t": second, "p": players})

    players_out = []
    import roster_tail  # noqa: WPS433
    item_name = roster_tail.item_name
    for entity in sorted(entities):
        info = entities[entity]
        tail = (next((b.get("tail") for b in blocks
                      if _as_int(b.get("entityId")) == entity), None) or {})
        players_out.append({
            **info,
            "purchaseCount": len(ordered_buys[entity]),
            "learnCount": len(ordered_learns[entity]),
            "goldSpentFinal": running_spend[entity] or None,
            "goldSpentTier": "derived",
            "finalItems": [item["equipId"] for item in ordered_buys[entity]],
            "skillOrder": skill_track[entity],
            "loadoutPlans": [
                {"name": p["name"],
                 "items": [{"id": v, "name": item_name(v) if v else ""}
                           for v in p["items"]]}
                for p in tail.get("plans") or []],
            "avatarUrl": tail.get("avatarUrl"),
            "openid": tail.get("openid"),
            # ``cc`` rows are CSDT_FRAPBOOT_CC client command sync, not crowd
            # control; the split keeps that explicit per player.
            "ccBreakdown": {
                "direction": cc_counts[entity]["direction"],
                "stopMove": cc_counts[entity]["stopMove"],
                "attackPos": cc_counts[entity]["attackPos"],
                "positionMove": cc_counts[entity]["positionMove"],
                "other": cc_counts[entity]["other"],
            },
        })

    # --- sparse position anchors (decoded, but only a few entities) ---------
    anchors: list[dict] = []
    anchor_entities: set[int] = set()
    for event in ((report.get("playerEvents") or {}).get("positions") or {}).get("events") or []:
        entity = _as_int(event.get("entityId"))
        if not entity:
            continue
        anchor_entities.add(entity)
        anchors.append({
            "t": round((_as_int(event.get("frame")) - 1) / FRAME_HZ, 3),
            "e": entity,
            "x": event.get("x"),
            "y": event.get("y"),
            "kind": event.get("kind"),
            "tier": "decoded",
        })
    anchors.sort(key=lambda row: (row["t"], row["e"]))

    ope_report = state.get("ope_report") or {}
    ope_summary = state.get("ope_summary")

    return {
        "schema": SCHEMA,
        "source": {
            "abc_sha256": state["abc_sha256"],
            "abcBytes": (state.get("abc_bytes") or 0),
            "opeBytes": (state.get("ope_bytes") or 0),
            "build": (report.get("header") or {}).get("builds") or [],
            "versions": (report.get("header") or {}).get("versions") or [],
            "totalFrames": (report.get("header") or {}).get("totalFrameNum"),
            "frameHz": FRAME_HZ,
            "ope": ope_report.get("matchId"),
            "opeOperatorStreamBytes": ope_report.get("operatorStreamBytes"),
            "opeOperatorEventsDecoded": ope_report.get("operatorEventsDecoded"),
        },
        "match": {
            "durationSec": duration,
            "winningCamp": winning,
            "mvpEntityId": mvp.get("winMvpEntityId"),
            "scoreTable": (report.get("scoreTable") or {}).get("players") or [],
        },
        "players": players_out,
        "events": {
            "purchases": sorted(purchases, key=lambda row: row["t"]),
            "learns": sorted(learns, key=lambda row: row["t"]),
        },
        "anchors": anchors,
        "matchConfig": None if state.get("init_block") is None else {
            **state["init_block"],
            "mapType": (report.get("header") or {}).get("mapType"),
            "mapId": (report.get("header") or {}).get("mapId"),
            "note": ("只映射有证据的三个标量词（modeWord/initialGold/"
                     "serverTimeUnixSeconds）；其余 107 个词语义未定，不命名。"
                     "其中 7 个词已实测与 mapId/mapType 一一对应，属配置并非逐局状态。"),
        },
        "ope": ope_summary,
        "timeline": timeline,
        "tiers": {
            "roster": "decoded",
            "winMvpRating": "decoded",
            "purchases": "decoded",
            "goldSpent": "derived (first-seen purchase prices; a spend ledger)",
            "level": "derived (1 + learn skills, capped at 15)",
            "actions": "decoded (frame commands); the cc family is client command sync, not crowd control",
            "anchors": "decoded sparse position samples (not a trajectory)",
        },
        "coverage": {
            "frameStream": "decoded: every frame record and command is parsed",
            "anchors": {
                "entities": len(anchor_entities),
                "samples": len(anchors),
                "note": "只有回放写入的少数真人消息带坐标，不是十人轨迹。",
            },
            "playerBlocks": {
                "bytes": sum(max(0, (b.get("blockEnd") or 0) - (b.get("start") or 0))
                             for b in blocks),
                "note": "身份/英雄/阵营/槽位/评分/出装方案（名称+12 件装备）/openid/头像 URL/"
                        "平台身份 hash 已解；剩余为分散的小值计数与无名分段表（结构可见，语义未命名）。",
            },
            "ope": {
                "bytes": ope_report.get("operatorStreamBytes") or 0,
                "decoded": bool(ope_summary),
                "mode": (ope_summary or {}).get("mode"),
                "records": (ope_summary or {}).get("records") or 0,
                "note": ("本地玩家操作流：记录类型与边界已按 0x00–0x19 布局解码到流尾，"
                         "统计在 ope 块；payload 字段名多为推断，且这是本地 POV 输入日志，"
                         "不是十人状态。"),
            },
            "scalarBlock": {
                "decoded": state.get("init_block") is not None,
                "error": state.get("init_block_error"),
                "words": 110,
                "note": ("440 B / 110 个 u32 BE：95 个常量、14 个少量变体、1 个逐局"
                         "（服务器时间）。只有 3 个词有证据可命名，其余保持未命名；"
                         "其中 7 个词与 mapId/mapType 一一对应，是配置不是逐局状态。"),
            },
        },
        "missing": MISSING,
    }


def load_prices() -> dict[int, int]:
    """Public alias for the item price table."""
    return _price_table()


def load_item_names() -> dict[int, str]:
    """Public alias for item display names."""
    return _item_names()


def build_from_bytes(raw: bytes, ope_raw: bytes | None = None) -> dict:
    """One-shot helper: ``.abc`` bytes in, ``kpl-replay-state-v1`` out."""
    return build(scan_bytes(raw, ope_raw), _price_table(), _item_names())


def _compact(document: dict) -> dict:
    """Drop the per-second grid when only the summary is wanted."""
    return document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--abc", type=Path, required=True)
    parser.add_argument("--ope", type=Path)
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "replay-states")
    parser.add_argument("--print-json", action="store_true")
    parser.add_argument("--summary", action="store_true",
                        help="omit the per-second timeline")
    args = parser.parse_args(argv)

    if not args.abc.exists():
        print(f"missing replay: {args.abc}", file=sys.stderr)
        return 2
    state = scan(args.abc, args.ope)
    document = build(state, _price_table(), _item_names())
    if args.summary:
        document.pop("timeline", None)
    if args.print_json:
        json.dump(document, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0
    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / f"{document['source']['abc_sha256']}.json"
    target.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "out": str(target),
        "durationSec": document["match"]["durationSec"],
        "players": len(document["players"]),
        "purchases": len(document["events"]["purchases"]),
        "learns": len(document["events"]["learns"]),
        "bytes": target.stat().st_size,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
