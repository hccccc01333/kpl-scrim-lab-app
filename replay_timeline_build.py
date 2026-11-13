"""把一局回放构建成出装时间轴（可部署版）。

与本地研究脚本的区别：那是研究产物的拼接器，依赖四个
预先存在的目录；这里是**按局生成**——只吃两样东西：

    events.csv            由 .abc 现场解码（Tier 0，任何部署都有）
    checkpoints           可选，来自引擎采样或截图锚定（Tier 2）

缺失的字段一律 null，并带 confidence 标签，绝不插值冒充实测。

产物：data/builds/<abc_sha256>/timeline.jsonl + meta.json

用法：
  python replay_timeline_build.py --abc <path.abc> [--checkpoints <csv>] [--out data/builds]
  python replay_timeline_build.py --events <events.csv> --sha <sha256> [--out data/builds]
"""
from __future__ import annotations

import argparse
import atexit
import collections
import csv
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from paths import data_root

ROOT = Path(__file__).resolve().parent
DEFAULT_DIR = Path(os.environ.get("ANALYSIS_BUILDS") or (data_root() / "builds"))
FAMILIES = ("movement", "attack", "skill", "buy", "cc", "aim")
SCHEMA = "kpl-replay-timeline-v3"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _catalog(abc_path: Path, info: dict | None = None,
             out_dir: Path | None = None) -> Path:
    """Decode the .abc into events.csv using the tested catalog generator.

    ``info`` is the already-parsed report when the caller has one; without it
    the generator decodes the roster itself.

    ``out_dir`` lets the caller own the temporary directory and its cleanup.
    Without it a directory is created here and removed at process exit, so a
    long-lived process that calls the helper directly does not accumulate
    ``timeline-build_*`` directories.
    """
    sys.path.insert(0, str(ROOT / "tools"))
    from full_abc_event_catalog import build_report  # noqa: WPS433

    if out_dir is None:
        tmp = Path(tempfile.mkdtemp(prefix="timeline-build_"))
        atexit.register(shutil.rmtree, tmp, True)
    else:
        tmp = Path(out_dir)
        tmp.mkdir(parents=True, exist_ok=True)
    build_report(abc_path, tmp, info)
    return tmp / "events.csv"


def _load_checkpoints(path: Path) -> dict[int, dict[str, dict]]:
    """t_s(int) -> player name -> row (engine-measured, exact seconds only)."""
    out: dict[int, dict[str, dict]] = collections.defaultdict(dict)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if not row.get("index"):
                continue
            label = row.get("clock") or ""
            parts = label.split(":")
            if len(parts) != 2:
                continue
            second = int(parts[0]) * 60 + int(float(parts[1]))
            key = f"{(row.get('hero') or '').strip()}|{row.get('camp') or ''}"
            if key != "|":
                out[second][key] = row
    return out


def _check_int(row, key):
    """Checkpoint 数值：0 是合法读数，不能按 truthiness 丢掉。"""
    if not row:
        return None
    value = row.get(key)
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def build(events_csv: Path, sha: str, out_root: Path,
          checkpoints: dict[int, dict[str, dict]] | None = None,
          meta_extra: dict | None = None) -> dict:
    seconds: dict[tuple[int, int], dict] = {}
    players: dict[int, dict] = {}
    buys: list[dict] = []
    with events_csv.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            entity = row.get("entity_id") or ""
            if not entity:
                continue
            entity_id = int(float(entity))
            second = int(float(row.get("time_s") or 0))
            if entity_id not in players:
                players[entity_id] = {
                    "player": row.get("player") or "",
                    "hero": row.get("hero") or "",
                    "camp": int(row["camp"]) if row.get("camp") else None,
                    "slot": int(row["slot"]) if row.get("slot") else None,
                    "unit": int(row["unit"]) if row.get("unit") else None,
                }
            key = (second, entity_id)
            cell = seconds.setdefault(key, {family: 0 for family in FAMILIES})
            family = row.get("family") or ""
            if family in cell:
                cell[family] += 1
            if family == "buy" and row.get("command") == "BUYEQUIP":
                try:
                    fields = json.loads(row.get("fields_json") or "{}")
                except ValueError:
                    fields = {}
                equip = fields.get("equip_id")
                if equip is not None:
                    buys.append({
                        "player": row.get("player") or "",
                        "hero": row.get("hero") or "",
                        "camp": int(row["camp"]) if row.get("camp") else None,
                        "equip_id": int(equip),
                        "price": fields.get("price"),
                        "t": round(float(row.get("time_s") or 0), 3),
                    })

    rows = []
    last_second = max((key[0] for key in seconds), default=0)
    for second in range(last_second + 1):
        for entity_id in sorted(players):
            cell = seconds.get((second, entity_id)) or {family: 0 for family in FAMILIES}
            info = players[entity_id]
            side = {1: "blue", 2: "red"}.get(info["camp"], "")
            per_second = (checkpoints or {}).get(second, {})
            check = None
            for key in (str(entity_id), info["player"], f"{info['hero']}|{side}"):
                if key and key in per_second:
                    check = per_second[key]
                    break
            gold = _check_int(check, "gold")
            kills = _check_int(check, "kills")
            deaths = _check_int(check, "deaths")
            assists = _check_int(check, "assists")
            level = _check_int(check, "level")
            rows.append({
            "second": second,
            "time_mmss": f"{second // 60:02d}:{second % 60:02d}",
            "player": info["player"],
            "hero": info["hero"],
            "camp": info["camp"],
            "team": {1: "blue", 2: "red"}.get(info["camp"], ""),
            "entity_id": entity_id,
            "unit": info["unit"],
            "gold": gold,
            "gold_confidence": "engine" if gold is not None else "unknown",
            "gold_source": "checkpoint" if gold is not None else "",
            "kills": kills,
            "deaths": deaths,
            "assists": assists,
            "kda_confidence": "engine" if None not in (kills, deaths, assists) else "unknown",
            "level": level,
            "level_confidence": "engine" if level is not None else "unknown",
            "hp_ratio": None, "hp_abs": None, "hp_confidence": "unknown",
            "x": None, "z": None, "pos_confidence": "unknown",
            "pos_note": "Tier 0: events only; positions need engine capture",
            "events_move": cell["movement"],
            "events_attack": cell["attack"],
            "events_skill": cell["skill"],
            "events_buy": cell["buy"],
            "events_cc": cell["cc"],
            "events_aim": cell["aim"],
        })

    out_dir = out_root / sha
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "timeline.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    build_dir = out_dir / "build_timeline"
    build_dir.mkdir(exist_ok=True)
    seen: set[tuple[str, int]] = set()
    unique: dict[str, list[dict]] = collections.defaultdict(list)
    with (build_dir / "equipment_events.csv").open(
            "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "player", "hero", "camp", "equip_id", "equip_name", "price",
            "time_s", "acquisition_time_s", "is_duplicate", "acquisition",
            "flag_kind", "acquisition_basis"])
        writer.writeheader()
        for item in sorted(buys, key=lambda row: row["t"]):
            key = (item["player"], item["equip_id"])
            first = key not in seen
            if first:
                seen.add(key)
                unique[item["player"]].append(item)
            writer.writerow({
                "player": item["player"], "hero": item["hero"],
                "camp": {1: "blue", 2: "red"}.get(item["camp"], ""),
                "equip_id": item["equip_id"], "equip_name": "",
                "price": item["price"] if item["price"] is not None else "",
                "time_s": item["t"], "acquisition_time_s": item["t"],
                "is_duplicate": 0 if first else 1,
                "acquisition": 1 if first else 0,
                "flag_kind": "file-decoded",
                "acquisition_basis": "first-seen-in-frame-commands",
            })
    with (build_dir / "player_builds.csv").open(
            "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "player", "hero", "camp", "cumulative_spend", "spend_confidence",
            "final_items", "final_check", "slot_count_match"])
        writer.writeheader()
        for entity_id, info in players.items():
            items = unique.get(info["player"], [])
            spend = sum(int(item["price"]) for item in items
                        if item["price"] is not None)
            writer.writerow({
                "player": info["player"], "hero": info["hero"],
                "camp": {1: "blue", 2: "red"}.get(info["camp"], ""),
                "cumulative_spend": spend,
                "spend_confidence": "price-table-partial",
                "final_items": ",".join(str(item["equip_id"]) for item in items),
                "final_check": "unique-items",
                "slot_count_match": "yes" if len(items) == 6 else "no",
            })

    meta = {
        "schema": SCHEMA,
        "abc_sha256": sha,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tier": "events+checkpoints" if checkpoints else "events-only",
        "rows": len(rows),
        "players": len(players),
        "last_second": rows[-1]["second"] if rows else 0,
        "fields_missing": ([] if checkpoints else
                           ["gold", "kills", "deaths", "assists", "level"]),
        "build_items": len(buys),
        **(meta_extra or {}),
    }
    (out_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def build_from_abc_bytes(data: bytes, out_root: Path,
                         name: str = "replay.abc",
                         checkpoints: dict | None = None,
                         info: dict | None = None) -> dict:
    """按局构建：上传接口拿到的字节流直接产出时间轴文件（后台线程用）。"""
    sha = hashlib.sha256(data).hexdigest()
    tmp = Path(tempfile.mkdtemp(prefix="timeline-abc_"))
    try:
        abc = tmp / (name or "replay.abc")
        abc.write_bytes(data)
        events = _catalog(abc, info, out_dir=tmp)
        return build(events, sha, out_root, checkpoints,
                     {"source_abc": abc.name})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--abc", type=Path)
    parser.add_argument("--events", type=Path)
    parser.add_argument("--sha")
    parser.add_argument("--checkpoints", type=Path)
    parser.add_argument("--out", type=Path, default=DEFAULT_DIR)
    args = parser.parse_args()

    tmp_dir = None
    if args.events:
        events_csv = args.events
        sha = args.sha or _sha256(args.events)
    elif args.abc:
        sha = _sha256(args.abc)
        tmp_dir = Path(tempfile.mkdtemp(prefix="timeline-build_"))
        events_csv = _catalog(args.abc, out_dir=tmp_dir)
    else:
        parser.error("需要 --abc 或 --events")

    try:
        checkpoints = _load_checkpoints(args.checkpoints) if args.checkpoints else None
        meta = build(events_csv, sha, args.out, checkpoints,
                     {"source_abc": args.abc.name if args.abc else "",
                      "checkpoints_csv": args.checkpoints.name if args.checkpoints else ""})
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    print(json.dumps(meta, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
