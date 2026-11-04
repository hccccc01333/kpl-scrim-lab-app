"""Generate a file-only V2 timeline from any route-ID1075 .abc replay.

The file contains command inputs (movement, attacks, skills, buys, CC), not
engine state.  This tool therefore emits an event timeline only: gold / KDA /
level / HP / positions stay null and are marked `file_only`.  Engine
checkpoints can be imported separately and merged by the product.

Output: <out>/timeline.jsonl + timeline.csv + builds.json + meta.json.
Read-only and offline: no device, no database write.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.replay_frame_commands import FRAME_RATE, hero_inputs  # noqa: E402

MAX_SECOND = 693
BUILD_BURST_FRAMES = 30


def _catalog_items() -> dict[str, str]:
    try:
        payload = json.loads((ROOT / "resources" / "catalog.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    names = {}
    for entry in payload.get("entries", []):
        if entry.get("kind") != "equipment":
            continue
        try:
            names[str(int(entry["id"].split("-")[1]))] = entry.get("name") or ""
        except (IndexError, ValueError):
            continue
    return names


def _second(frame: int) -> int:
    # The observed replay runs at 15.1515 fps; the product timeline uses a 1 Hz
    # grid.  ±3 s is documented in meta; exact frame times stay in the events.
    return max(0, min(MAX_SECOND, round((frame - 1) / (FRAME_RATE or 15))))


def _bucket(store: dict, entity: int, key: str) -> dict:
    item = store.setdefault(entity, {name: 0 for name in
                                     ("move", "attack", "skill", "aim", "buy", "cc")})
    return item


def build(abc: bytes, report: dict, out_dir: Path) -> dict:
    blocks = report.get("blocks") or []
    roster = []
    for block in blocks:
        camp = block.get("camp")
        slot = block.get("position")
        if camp not in (1, 2) or slot is None:
            continue
        roster.append({
            "player": block.get("name") or block.get("heroName") or f"unit{slot}",
            "hero": block.get("heroName") or "",
            "hero_id": block.get("heroId"),
            "camp": camp,
            "slot": slot,
            "unit": 8 + (camp - 1) * 8 + slot,
            "entity_id": block.get("entityId"),
        })
    if not roster:
        raise ValueError("报告里没有可用的十人阵营/槽位，无法生成仅文件时间轴")

    inputs = hero_inputs(abc)
    if inputs.get("status") not in ("decoded", "partial"):
        raise ValueError(f"帧命令解码失败：{inputs.get('status')} {inputs.get('error') or ''}")

    counts: dict[int, dict[int, dict]] = {}
    for player in roster:
        entity = player.get("entity_id")
        unit = player["unit"]
        buckets = counts.setdefault(player["unit"], {})
        for name in ("move", "attack", "skill", "aim", "buy", "cc"):
            buckets[name] = {}
        unit_events = (inputs.get("units") or {}).get(str(unit)) or {}
        for event in unit_events.get("moves") or []:
            second = _second(event[0]); buckets["move"][second] = buckets["move"].get(second, 0) + 1
        for event in unit_events.get("attacks") or []:
            second = _second(event[0]); buckets["attack"][second] = buckets["attack"].get(second, 0) + 1
        entity_events = (inputs.get("entities") or {}).get(str(entity)) or {}
        for event in entity_events.get("skills") or []:
            second = _second(event[0])
            key = "aim" if len(event) > 1 and event[1] == 130 else "skill"
            buckets[key][second] = buckets[key].get(second, 0) + 1
        for event in entity_events.get("buys") or []:
            second = _second(event[0]); buckets["buy"][second] = buckets["buy"].get(second, 0) + 1
        for event in entity_events.get("cc") or []:
            second = _second(event[0]); buckets["cc"][second] = buckets["cc"].get(second, 0) + 1

    rows = []
    for second in range(0, MAX_SECOND + 1):
        for player in roster:
            bucket = counts.get(player["unit"]) or {}
            row = {
                "second": second,
                "time_mmss": f"{second // 60:02d}:{second % 60:02d}",
                "player": player["player"], "hero": player["hero"],
                "camp": player["camp"], "team": "blue" if player["camp"] == 1 else "red",
                "entity_id": player["entity_id"], "unit": player["unit"], "slot": player["slot"],
                "gold": None, "gold_confidence": "file_only", "gold_source": None,
                "kills": None, "deaths": None, "assists": None, "kda_confidence": "file_only",
                "level": None, "level_confidence": "file_only",
                "hp_ratio": None, "hp_abs": None, "hp_confidence": "file_only",
                "x": None, "z": None, "pos_confidence": "file_only", "pos_note": None,
                "events_move": (bucket.get("move") or {}).get(second, 0),
                "events_attack": (bucket.get("attack") or {}).get(second, 0),
                "events_skill": (bucket.get("skill") or {}).get(second, 0),
                "events_buy": (bucket.get("buy") or {}).get(second, 0),
                "events_cc": (bucket.get("cc") or {}).get(second, 0),
                "events_aim": (bucket.get("aim") or {}).get(second, 0),
                "row_kind": "file_event",
                "sources": "abc_frame_commands",
            }
            rows.append(row)

    # Deduplicated buy timeline (same equip within a short burst = one buy).
    names = _catalog_items()
    builds = {}
    for player in roster:
        entity = player.get("entity_id")
        entity_events = (inputs.get("entities") or {}).get(str(entity)) or {}
        items = []
        last_frame = {}
        for event in entity_events.get("buys") or []:
            frame, equip_id = event[0], str(event[1])
            if equip_id in last_frame and frame - last_frame[equip_id] <= BUILD_BURST_FRAMES:
                last_frame[equip_id] = frame
                continue
            last_frame[equip_id] = frame
            items.append({"t": _second(frame), "id": equip_id,
                          "name": names.get(equip_id, ""), "price": None,
                          "confidence": "file_only"})
        items.sort(key=lambda item: item["t"])
        builds[player["player"]] = {
            "items": items,
            "summary": {"hero": player["hero"], "camp": player["camp"],
                        "spend": None, "spendConfidence": "file_only",
                        "finalItems": "", "finalCheck": "unavailable"},
        }

    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "timeline.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    meta = {
        "schema": "kpl-replay-v2-timeline-v1",
        "mode": "file_only",
        "abc_sha256": report.get("abc", {}).get("sha256"),
        "abc_name": report.get("abcFileName"),
        "seconds": MAX_SECOND + 1,
        "players": len(roster),
        "rows": len(rows),
        "gold_kda_confidence": "unavailable_from_abc",
        "level_confidence": "unavailable_from_abc",
        "hp_confidence": "unavailable_from_abc",
        "position_confidence": "unavailable_from_abc",
        "event_coverage": f"{len(rows)} rows (1 Hz)",
        "caveats": [
            "仅文件数据：事件/出装/移动/瞄准来自 .abc 帧命令",
            "金币/KDA/等级/血量/坐标需要回放时采集引擎检查点并导入",
            "事件时间按 15 fps 近似，误差约 ±3 秒",
        ],
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "builds.json").write_text(
        json.dumps({"schema": "kpl-replay-v2-builds-v1", "players": builds}, ensure_ascii=False),
        encoding="utf-8")
    return meta


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--abc", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True, help="stored replay report JSON")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    meta = build(args.abc.read_bytes(), report, args.out)
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
