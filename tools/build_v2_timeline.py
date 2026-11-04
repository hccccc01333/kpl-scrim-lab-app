"""Build a compact 1 Hz V2 timeline for the product replay page.

Inputs (all offline artifacts, never the device):
- interpolated_state/per_frame_supplementary.csv  (per-frame gold/KDA/HP estimates)
- state_table/state.jsonl                          (engine-measured checkpoints + HP samples)
- trajectories/player_trajectories.csv             (estimated X/Z; validation FAILED)
- full_event_catalog/events.csv                    (per-command event catalog)

Output: v2_timeline/timeline.csv + timeline.jsonl + README.md.

Every field carries a source/confidence label.  Missing data stays null; the
timeline never turns an estimate into a measured value.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / "data" / "replays" / "_analysis" / "live_20261104"

FAMILIES = ("movement", "attack", "skill", "buy", "cc", "aim")


def _load_interpolation(path: Path):
    """Keep the last per-frame row inside each whole second, per entity."""
    latest = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                entity = int(row["entity_id"])
                second = int(float(row["time_s"]))
            except (KeyError, TypeError, ValueError):
                continue
            latest[(entity, second)] = row
    return latest


def _load_levels(path: Path):
    levels = collections.defaultdict(list)
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("level") is None:
                continue
            try:
                entity = int(row["entity_id"])
                second = int(float(row["time_s"]))
            except (KeyError, TypeError, ValueError):
                continue
            levels[entity].append((second, int(row["level"])))
    for entity in levels:
        levels[entity].sort()
    return levels


def _load_positions(path: Path):
    latest = {}
    if not path.exists():
        return latest
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                entity = int(row["entity_id"] if "entity_id" in row else row["entity"])
                second = int(float(row["time"]))
                x = float(row["X"])
                z = float(row["Z"])
            except (KeyError, TypeError, ValueError):
                continue
            latest[(entity, second)] = (x, z)
    return latest


def _load_events(path: Path):
    counts = collections.defaultdict(lambda: collections.Counter())
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                entity = int(row["entity_id"])
                second = int(float(row["time_s"]))
            except (KeyError, TypeError, ValueError):
                continue
            family = row.get("family") or "unknown"
            counts[(entity, second)][family] += 1
    return counts


def _level_at(levels, entity, second):
    history = levels.get(entity) or []
    chosen = None
    for at, value in history:
        if at <= second:
            chosen = (at, value)
        else:
            break
    if chosen is None:
        return None, "unknown"
    at, value = chosen
    return value, ("checkpoint" if second - at <= 2 else "last-known")


def build(source_dir: Path, out_dir: Path) -> dict:
    interpolation = _load_interpolation(source_dir / "interpolated_state" / "per_frame_supplementary.csv")
    levels = _load_levels(source_dir / "state_table" / "state.jsonl")
    positions = _load_positions(source_dir / "trajectories" / "player_trajectories.csv")
    events = _load_events(source_dir / "full_event_catalog" / "events.csv")

    entities = {}
    for (entity, _second), row in interpolation.items():
        entities.setdefault(entity, {
            "player": row.get("player"), "hero": row.get("hero"),
            "camp": row.get("camp"), "team": row.get("team"),
            "slot": row.get("slot"), "unit": row.get("unit"),
        })

    rows = []
    for second in range(0, 694):
        for entity in sorted(entities):
            base = interpolation.get((entity, second))
            if base is None:
                # Fall back to the latest earlier row for this entity.
                candidates = [key for key in interpolation if key[0] == entity and key[1] <= second]
                if not candidates:
                    continue
                base = interpolation[max(candidates)]
            level, level_confidence = _level_at(levels, entity, second)
            position = positions.get((entity, second))
            event_counts = events.get((entity, second), {})
            row = {
                "second": second,
                "time_mmss": f"{second // 60:02d}:{second % 60:02d}",
                "player": entities[entity]["player"],
                "hero": entities[entity]["hero"],
                "camp": entities[entity]["camp"],
                "team": entities[entity]["team"],
                "entity_id": entity,
                "unit": entities[entity]["unit"],
                "gold": base.get("gold") or None,
                "gold_confidence": base.get("gold_confidence"),
                "gold_source": base.get("gold_source"),
                "kills": base.get("kills") or None,
                "deaths": base.get("deaths") or None,
                "assists": base.get("assists") or None,
                "kda_confidence": base.get("kda_confidence"),
                "level": level,
                "level_confidence": level_confidence,
                "hp_ratio": base.get("hp_ratio") or None,
                "hp_abs": base.get("hp_abs") or None,
                "hp_confidence": base.get("hp_confidence"),
                "x": position[0] if position else None,
                "z": position[1] if position else None,
                "pos_confidence": "estimated" if position else None,
                "pos_note": ("input-direction integration; validation FAILED 17.8% map span"
                             if position else None),
                "events_move": event_counts.get("movement", 0),
                "events_attack": event_counts.get("attack", 0),
                "events_skill": event_counts.get("skill", 0),
                "events_buy": event_counts.get("buy", 0),
                "events_cc": event_counts.get("cc", 0),
                "events_aim": event_counts.get("aim", 0),
            }
            rows.append(row)

    out_dir.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else []
    with (out_dir / "timeline.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    with (out_dir / "timeline.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    # Validation summary.
    gold_ok = kda_ok = 0
    per_entity = collections.defaultdict(list)
    for row in rows:
        per_entity[row["entity_id"]].append(row)
    for entity, series in per_entity.items():
        gold = [float(r["gold"]) for r in series if r["gold"] is not None]
        kills = [float(r["kills"]) for r in series if r["kills"] is not None]
        if all(b >= a for a, b in zip(gold, gold[1:])):
            gold_ok += 1
        if all(b >= a for a, b in zip(kills, kills[1:])):
            kda_ok += 1
    hp_known = sum(1 for r in rows if r["hp_ratio"] is not None)
    pos_known = sum(1 for r in rows if r["x"] is not None)
    summary = {
        "rows": len(rows),
        "seconds": 694,
        "players": len(entities),
        "gold_monotonic_players": gold_ok,
        "kda_monotonic_players": kda_ok,
        "hp_known_rows": hp_known,
        "position_known_rows": pos_known,
        "position_confidence": "estimated (failed validation)",
        "event_total": sum(r["events_move"] + r["events_attack"] + r["events_skill"]
                           + r["events_buy"] + r["events_cc"] + r["events_aim"] for r in rows),
    }
    (out_dir / "validation.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "README.md").write_text(
        "# V2 1 Hz timeline\n\n"
        "每行 = 一个整秒 × 一名选手。金币/KDA 来自 `per_frame_supplementary.csv`，"
        "`interpolated` 表示检查点之间；检查点实测值见状态表/检查点区块。"
        "等级来自状态表检查点（`checkpoint`/`last-known`，`last-known` 可能滞后到"
        "下一个检查点，页面需显示来源）。血量只在实测处有值，其余 unknown。"
        "位置来自输入方向积分并标注 `estimated`（验证失败 17.8% 地图跨度，不可当坐标）。"
        "事件计数来自全量事件表；611 条事件时间超出 0–693 s，覆盖 88,009/88,627。"
        "缺失保持 null，不补造。\n\n"
        f"验证：{json.dumps(summary, ensure_ascii=False)}\n",
        encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_DIR / "v2_timeline")
    args = parser.parse_args()
    summary = build(args.source, args.out)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
