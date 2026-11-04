"""Read-only V2 timeline API.

The V2 timeline is a research artifact keyed by the .abc SHA-256.  It is
served only when the requested replay id matches that SHA, so a replay without
a generated timeline never gets another match's data.
"""
from __future__ import annotations

import csv
import json
import os
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

ROOT = Path(__file__).resolve().parent
DEFAULT_DIR = Path(os.environ.get("ANALYSIS_V2", ROOT / "data" / "v2"))
LEGACY_DIR = ROOT / "data" / "replays" / "_analysis" / "live_20261104" / "v2_timeline"


@lru_cache(maxsize=4)
def _load(directory: str) -> tuple[dict, list[dict]]:
    base = Path(directory)
    meta = json.loads((base / "meta.json").read_text(encoding="utf-8"))
    rows = []
    with (base / "timeline.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return meta, rows


@lru_cache(maxsize=4)
def _load_builds(directory: str) -> dict:
    """Read the deduplicated equipment timeline beside the V2 timeline.

    Deployable layout: data/v2/<sha>/build_timeline/.  Research layout:
    a sibling of the legacy timeline directory.  Missing either way is empty,
    never an error — the page must still render.
    """
    base = Path(directory)
    candidates = [base / "build_timeline", base.parent / "build_timeline"]
    build_dir = next((item for item in candidates if item.exists()), None)
    if build_dir is None:
        return {"schema": "kpl-replay-v2-builds-v1", "players": {}}
    players: dict[str, dict] = {}
    events_path = build_dir / "equipment_events.csv"
    if events_path.exists():
        with events_path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if (row.get("is_duplicate") or "0") != "0":
                    continue
                if (row.get("acquisition") or "0") not in ("1", "True", "true"):
                    continue
                player = row.get("player") or ""
                if not player:
                    continue
                try:
                    second = float(row.get("acquisition_time_s") or row.get("time_s") or 0)
                except ValueError:
                    continue
                price = row.get("price") or row.get("catalog_price")
                try:
                    price_value = int(float(price)) if price not in (None, "") else None
                except ValueError:
                    price_value = None
                players.setdefault(player, {"items": [], "summary": {}})["items"].append({
                    "t": round(second, 1),
                    "id": row.get("equip_id"),
                    "name": row.get("equip_name") or "",
                    "price": price_value,
                    "confidence": row.get("flag_kind") or row.get("acquisition_basis") or "",
                })
    summary_path = build_dir / "player_builds.csv"
    if summary_path.exists():
        with summary_path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                player = row.get("player") or ""
                if not player:
                    continue
                entry = players.setdefault(player, {"items": [], "summary": {}})
                entry["summary"] = {
                    "hero": row.get("hero"),
                    "camp": row.get("camp"),
                    "spend": row.get("cumulative_spend"),
                    "spendConfidence": row.get("spend_confidence"),
                    "finalItems": row.get("final_items"),
                    "finalCheck": row.get("final_check"),
                    "slotMatch": row.get("slot_count_match"),
                }
    for entry in players.values():
        entry["items"].sort(key=lambda item: item["t"])
    return {"schema": "kpl-replay-v2-builds-v1", "players": players}


def create_v2_router(directory: Path | None = None) -> APIRouter:
    base = Path(directory) if directory is not None else DEFAULT_DIR
    router = APIRouter()

    def payload(replay_id: str) -> tuple[dict, list[dict], Path]:
        for directory in (base / replay_id, LEGACY_DIR):
            try:
                meta, rows = _load(str(directory))
            except (OSError, ValueError):
                continue
            if meta.get("abc_sha256") == replay_id:
                return meta, rows, directory
        raise HTTPException(
            404,
            "该回放还没有生成 V2 时间轴。上传后运行 "
            f"`python replay_v2_build.py --abc <回放文件>`，产物写入 "
            f"data/v2/{replay_id[:12]}…/",
        )

    @router.get("/api/replays/{replay_id}/v2-timeline/meta")
    def v2_meta(replay_id: str):
        meta, _, _ = payload(replay_id)
        return {"ok": True, "meta": meta}

    @router.get("/api/replays/{replay_id}/v2-timeline")
    def v2_timeline(replay_id: str,
                    from_s: int = Query(0, ge=0),
                    to_s: int = Query(693, ge=0),
                    entity_id: int | None = None):
        meta, rows, _ = payload(replay_id)
        if to_s < from_s:
            raise HTTPException(400, "to_s 必须 >= from_s")
        selected = [
            row for row in rows
            if from_s <= row["second"] <= to_s
            and (entity_id is None or row.get("entity_id") == entity_id)
        ]
        return {"ok": True, "meta": meta, "from": from_s, "to": to_s,
                "count": len(selected), "rows": selected}

    @router.get("/api/replays/{replay_id}/v2-timeline/builds")
    def v2_builds(replay_id: str):
        _, _, directory = payload(replay_id)
        return {"ok": True, **_load_builds(str(directory))}
    return router
