#!/usr/bin/env python3
"""Build web/replay-review-data.js from the read-only replay datasets.

This script only reads files under data/replays/_analysis/datasets (plus the
local resources catalog for reference names) and writes a compact browser
bundle.  It never writes to the R1 dataset directory and never inlines the
large R1 gzip event stream; the page decompresses that file in the browser.

Usage:
    python scripts/build_replay_review_bundle.py
    python scripts/build_replay_review_bundle.py --skip-screenshot

The page also supports loading the same CSVs / gzip event stream at runtime
through its folder picker or the local data/ path, so this bundle is a
zero-config snapshot, not the only data path.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
import sys
from difflib import SequenceMatcher
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DS = ROOT / "data" / "replays" / "_analysis" / "datasets"
OUT = ROOT / "web" / "replay-review-data.js"
RESOURCES = ROOT / "resources"
SCREENSHOT_ROOT = ROOT / "data" / "screenshots" / "samples"

EVENT_STREAM_GZIP = "replay_event_stream_events.jsonl.gz"
FULL_STREAM_GZIP = "replay_event_stream.jsonl.gz"

# External panel truth supplied for the 20261102_1559 screenshot (27:6 win).
# The number after KDA is the scoreboard cumulative gold; it is not current cash.
# The replay cross-checks it with the final six-item cost; it is never treated as
# income and this bundle does not read or display gold_event_total.
PANEL_TRUTH = {
    "漂流网咖": {"kda": "5/0/8", "gold": 8697},
    "狂傲自由魂Z.": {"kda": "8/1/7", "gold": 9243},
    "自诩一棵葱": {"kda": "6/1/7", "gold": 8168},
    "别吃窝线吖a": {"kda": "5/1/5", "gold": 8352},
    "胡不喜#": {"kda": "3/3/9", "gold": 6540},
    "麻巫喵": {"kda": "1/5/2", "gold": 6191},
    "翳灵崽": {"kda": "2/7/2", "gold": 5828},
    "一风舞": {"kda": "2/3/3", "gold": 5778},
    "扁鹊耳垂": {"kda": "1/6/2", "gold": 5977},
    "谜语星海": {"kda": "0/6/4", "gold": 5474},
}

# Analyst visual review of the 60 icon-only equipment slots in
# 01-score-equipment.jpg, compared against each player's BUYEQUIP unique set.
# Icon art has no name/ID text; confidence is explicit and this is not OCR truth.
MANUAL_EQUIPMENT = {
    "漂流网咖": {
        "visible": 6,
        "items": [
            [1, "无尽战刃", 1133, "high"],
            [2, "抵抗之靴", 1422, "medium"],
            [3, "影刃", 1136, "high"],
            [4, "仁者破晓", 1155, "medium"],
            [5, "血魂刃", 1158, "high"],
            [6, "红玛瑙", 1311, "high"],
        ],
        "note": "1/3/5/6 号与候选图标目测一致；2 号绿色靴按候选图判为抵抗之靴，4 号弓按候选图判为仁者破晓。",
    },
    "狂傲自由魂Z.": {
        "visible": 6,
        "items": [
            [1, "影忍之足", 1421, "high"],
            [2, "红莲斗篷", 1331, "high"],
            [3, "怒龙剑盾", 1534, "high"],
            [4, "冰霜冲击", 1341, "medium"],
            [5, "永夜守护", 1347, "high"],
            [6, "红玛瑙", 1311, "high"],
        ],
        "note": "4 号蓝色护甲按候选图标判为冰霜冲击，置信中等。",
    },
    "自诩一棵葱": {
        "visible": 6,
        "items": [
            [1, "贤者天书", 1238, "high"],
            [2, "疾步之靴", 1426, "high"],
            [3, "博学者之怒", 1232, "high"],
            [4, "血族之书", 1222, "medium"],
            [5, "魔道之石", 1224, "medium"],
            [6, "大棒", 1221, "medium"],
        ],
        "note": "书类图标相近；4/5/6 号按候选图标与颜色判为中置信。",
    },
    "别吃窝线吖a": {
        "visible": 6,
        "items": [
            [1, "追击刀锋", 1523, "medium"],
            [2, "急速战靴", 1425, "high"],
            [3, "无尽战刃", 1133, "medium"],
            [4, "影刃", 1136, "high"],
            [5, "狂暴双刃", 1123, "medium"],
            [6, "陨星", 1124, "high"],
        ],
        "note": "1 号红色打野刀候选追击刀锋；3/5 号与无尽/狂暴双刃的候选图标相近，置信中等。",
    },
    "胡不喜#": {
        "visible": 5,
        "items": [
            [1, "极影·形昭", 1737, "high"],
            [2, "守护者之铠", 1325, "medium"],
            [3, "冰霜冲击", 1341, "medium"],
            [4, "极影", 1711, "low"],
            [5, "蓝色铃铛（候选极影/学识宝石）", 0, "low"],
        ],
        "note": "后两格为蓝色铃铛类辅助装，图标相近，未逐件确认；不据此认定具体 ID。",
    },
    "麻巫喵": {
        "visible": 6,
        "items": [
            [1, "急速战靴", 1425, "high"],
            [2, "影刃", 1136, "high"],
            [3, "无尽战刃", 1133, "medium"],
            [4, "穿云弓", 1154, "high"],
            [5, "匕首", 1112, "medium"],
            [6, "铁剑", 1111, "medium"],
        ],
        "note": "5/6 号为小件武器，按候选图标判为匕首/铁剑，置信中等。",
    },
    "翳灵崽": {
        "visible": 4,
        "items": [
            [1, "影忍之足", 1421, "high"],
            [2, "纯净苍穹", 11311, "high"],
            [3, "强者破军", 1138, "medium"],
            [4, "荆棘护手", 1345, "medium"],
        ],
        "note": "仅 4 格有装备；3/4 号按候选图标判为中置信。",
    },
    "一风舞": {
        "visible": 4,
        "items": [
            [1, "冷静之靴", 1423, "high"],
            [2, "圣杯", 1226, "high"],
            [3, "噬神之书", 1240, "high"],
            [4, "云灵木", 1243, "high"],
        ],
        "note": "4 格装备与候选图标目测一致。",
    },
    "扁鹊耳垂": {
        "visible": 4,
        "items": [
            [1, "贪婪之噬", 1533, "high"],
            [2, "冷静之靴", 1423, "high"],
            [3, "暗影战斧", 1137, "high"],
            [4, "风暴巨剑", 1121, "high"],
        ],
        "note": "4 格装备与候选图标目测一致。",
    },
    "谜语星海": {
        "visible": 5,
        "items": [
            [1, "极影·形昭", 1737, "high"],
            [2, "金色盾牌（候选疾步之靴/守护者之铠）", 0, "low"],
            [3, "急速铠甲", 1317, "medium"],
            [4, "红玛瑙", 1311, "high"],
            [5, "抗魔披风", 1313, "medium"],
        ],
        "note": "2 号金色盾牌与候选图标不一致，保留未知；其余按候选图标判读。",
    },
}


def read_csv(name: str) -> list[dict[str, str]]:
    path = DS / name
    if not path.exists():
        print(f"  skip missing {name}")
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        return list(csv.DictReader(fp))


def as_int(value: str | None, default: int = 0) -> int:
    if value is None or value == "":
        return default
    text = str(value).strip()
    try:
        return int(text, 16) if text.lower().startswith(("0x", "-0x")) else int(text)
    except ValueError:
        try:
            return int(float(text))
        except ValueError:
            return default


def as_float(value: str | None, default: float = 0.0) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def file_label(name: str) -> tuple[str, str]:
    match = re.match(r"(\d{8})_(\d{6})", name)
    if not match:
        return name.rsplit(".", 1)[0], ""
    day, clock = match.groups()
    return f"{day[:4]}-{day[4:6]}-{day[6:]} {clock[:2]}:{clock[2:4]}:{clock[4:]}", day


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_key(text: str | None) -> str:
    """Normalize nicknames for OCR-vs-CSV comparison."""
    return re.sub(r"[\s\u200b-\u200f\u2060\ufe0e\ufe0f\ufffd]", "", str(text or ""))


def load_hero_names() -> dict[str, str]:
    path = RESOURCES / "catalog.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    names: dict[str, str] = {}
    for entry in data.get("entries") or []:
        if entry.get("kind") != "hero":
            continue
        match = re.match(r"hero-(\d+)", str(entry.get("id") or ""))
        if match and entry.get("name"):
            names[match.group(1)] = str(entry["name"])
    return names


def load_equip_prices() -> dict[str, dict[str, object]]:
    prices: dict[str, dict[str, object]] = {}
    for row in read_csv("agent_equip_prices.csv"):
        if row.get("section") != "battle_item":
            continue
        item_id = as_int(row.get("item_id"))
        if not item_id:
            continue
        prices[str(item_id)] = {
            "name": row.get("item_name", ""),
            "buy": as_int(row.get("buy_price")),
            "sell": as_int(row.get("sell_price")),
            "type": as_int(row.get("price_type")),
        }
    return prices


def read_11_2(equip_prices: dict[str, dict[str, object]], hero_names: dict[str, str]):
    """Read the 11/2 buy/skill/action CSVs without inventing aggregates."""
    buy_by_file: dict[str, list[list]] = defaultdict(list)
    skill_by_file: dict[str, list[list]] = defaultdict(list)
    actions_by_file: dict[str, list[list]] = defaultdict(list)
    players_by_file: dict[str, dict[int, dict]] = defaultdict(dict)

    def remember_player(file: str, entity: int, player: str, hero_id: int) -> None:
        if not file or not entity:
            return
        info = players_by_file[file].setdefault(entity, {
            "entity": entity,
            "name": player or "",
            "heroId": hero_id,
            "team": 0,
            "slot": None,
        })
        if player and not info["name"]:
            info["name"] = player
        if hero_id and not info["heroId"]:
            info["heroId"] = hero_id

    for row in read_csv("20261102_buy_events.csv"):
        file = row.get("file", "").strip()
        if not file:
            continue
        frame = as_int(row.get("frame"))
        entity = as_int(row.get("entity"))
        hero_id = as_int(row.get("hero_id"))
        equip_id = as_int(row.get("equip_id"))
        price_info = equip_prices.get(str(equip_id), {})
        equip_name = row.get("equip_name", "") or str(price_info.get("name", ""))
        buy_price = as_int(row.get("buy_price"))
        if not buy_price:
            buy_price = as_int(str(price_info.get("buy", 0)))
        buy_by_file[file].append([
            frame, entity, equip_id, equip_name, buy_price,
            as_int(row.get("auto_buy")), as_int(row.get("first_for_entity")),
        ])
        remember_player(file, entity, row.get("player", ""), hero_id)

    for row in read_csv("20261102_skill_events.csv"):
        file = row.get("file", "").strip()
        if not file:
            continue
        frame = as_int(row.get("frame"))
        entity = as_int(row.get("entity"))
        hero_id = as_int(row.get("hero_id"))
        skill_by_file[file].append([
            frame, entity, as_int(row.get("slot")), as_int(row.get("level")),
            as_int(row.get("auto_learn")),
        ])
        remember_player(file, entity, row.get("player", ""), hero_id)

    for row in read_csv("20261102_player_actions.csv"):
        file = row.get("file", "").strip()
        if not file:
            continue
        entity = as_int(row.get("entity"))
        hero_id = as_int(row.get("hero_id"))
        actions_by_file[file].append([
            entity,
            row.get("player", ""),
            hero_id,
            round(as_float(row.get("score")), 2),
            as_int(row.get("buy_events_raw")),
            as_int(row.get("unique_buy_items")),
            # The CSV header is unique_equip_price_sum_unverified even though the
            # 20261102 report calls it unique_buy_spend_lower_bound.
            as_int(row.get("unique_equip_price_sum_unverified") or row.get("unique_buy_spend_lower_bound")),
            row.get("buy_equip_ids", ""),
            as_int(row.get("learn_events")),
            row.get("learn_slots", ""),
            as_int(row.get("move_events")),
            as_int(row.get("attack_events")),
            as_int(row.get("directional_skill")),
            as_int(row.get("position_skill")),
            as_int(row.get("objective_skill")),
            as_int(row.get("move_events_file_total")),
            as_int(row.get("attack_events_file_total")),
            as_int(row.get("attackwithobj_events_file_total")),
            row.get("per_player_attribution", ""),
        ])
        remember_player(file, entity, row.get("player", ""), hero_id)

    for file, players in players_by_file.items():
        for info in players.values():
            info["heroName"] = hero_names.get(str(info["heroId"]), "")

    for rows in buy_by_file.values():
        rows.sort(key=lambda row: (row[0], row[1], row[2]))
    for rows in skill_by_file.values():
        rows.sort(key=lambda row: (row[0], row[1], row[2]))
    return buy_by_file, skill_by_file, actions_by_file, players_by_file


def build_event_stream_index() -> dict | None:
    path = DS / EVENT_STREAM_GZIP
    if not path.exists():
        return None
    files: Counter[str] = Counter()
    actions: Counter[str] = Counter()
    kinds: Counter[str] = Counter()
    spans: dict[str, list[int]] = {}
    lines = 0
    uncompressed_bytes = 0
    parse_errors = 0
    with gzip.open(path, "rt", encoding="utf-8") as fp:
        for line in fp:
            if not line.strip():
                continue
            lines += 1
            uncompressed_bytes += len(line.encode("utf-8"))
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                parse_errors += 1
                continue
            file = str(record.get("file") or "")
            files[file] += 1
            actions[str(record.get("action") or "")] += 1
            kinds[str(record.get("kind") or "")] += 1
            seq = record.get("seq")
            if isinstance(seq, (int, float)):
                seq = int(seq)
                if file not in spans:
                    spans[file] = [seq, seq]
                else:
                    spans[file][0] = min(spans[file][0], seq)
                    spans[file][1] = max(spans[file][1], seq)
    return {
        "name": path.name,
        "bytes": path.stat().st_size,
        "uncompressedBytes": uncompressed_bytes,
        "lines": lines,
        "parseErrors": parse_errors,
        "files": [
            {
                "file": file,
                "events": count,
                "minSeq": spans.get(file, [None, None])[0],
                "maxSeq": spans.get(file, [None, None])[1],
            }
            for file, count in sorted(files.items())
        ],
        "actions": dict(actions.most_common()),
        "kinds": dict(kinds.most_common()),
        "note": "Browser-side DecompressionStream('gzip') streaming; no event lines are inlined in this bundle.",
    }


def available_streams() -> list[dict]:
    streams = []
    for name in (EVENT_STREAM_GZIP, FULL_STREAM_GZIP):
        path = DS / name
        if path.exists():
            streams.append({
                "name": name,
                "bytes": path.stat().st_size,
                "mtime": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
            })
    return streams


def summarize_buys(rows: list[list], equip_prices: dict[str, dict[str, object]]) -> dict[int, dict]:
    """Unique BUYEQUIP set per entity; spend is a lower bound, never income."""
    summary: dict[int, dict] = {}
    for frame, entity, equip_id, name, price, _auto, _first in rows:
        item = summary.setdefault(entity, {
            "rawNotifications": 0,
            "items": {},
            "spendLowerBound": 0,
            "unknownPriceItems": 0,
            "firstFrame": frame,
            "lastFrame": frame,
        })
        item["rawNotifications"] += 1
        item["firstFrame"] = min(item["firstFrame"], frame)
        item["lastFrame"] = max(item["lastFrame"], frame)
        key = str(equip_id)
        if key not in item["items"]:
            price_info = equip_prices.get(key, {})
            item_name = name or str(price_info.get("name", ""))
            buy_price = price or as_int(str(price_info.get("buy", 0)))
            item["items"][key] = {
                "itemId": equip_id,
                "name": item_name,
                "price": buy_price,
                "firstFrame": frame,
                "notifications": 0,
            }
            if buy_price:
                item["spendLowerBound"] += buy_price
            else:
                item["unknownPriceItems"] += 1
        item["items"][key]["notifications"] += 1
    return summary


def find_action_row(player: dict, rows: list[list], hero_names: dict[str, str]) -> tuple[list | None, bool]:
    """Match one OCR player to a CSV row. Returns (row, exact_or_fuzzy_name)."""
    nickname = normalize_key(player.get("nickname"))
    rating = player.get("rating")
    by_name = {normalize_key(row[1]): row for row in rows}
    if nickname and nickname in by_name:
        return by_name[nickname], True
    if nickname:
        best_row = None
        best_ratio = 0.0
        for row in rows:
            ratio = SequenceMatcher(None, nickname, normalize_key(row[1])).ratio()
            if ratio > best_ratio:
                best_ratio, best_row = ratio, row
        if best_row is not None and best_ratio >= 0.72:
            return best_row, True
    if rating is not None:
        rating_matches = [row for row in rows if abs(float(rating) - float(row[3])) < 0.05]
        if len(rating_matches) == 1:
            return rating_matches[0], False
    hero = str(player.get("hero") or "")
    if hero:
        hero_matches = [row for row in rows if hero_names.get(str(row[2]), "") == hero]
        if len(hero_matches) == 1:
            return hero_matches[0], False
    return None, False


def match_screenshot_to_actions(ocr_players: list[dict], actions_by_file: dict[str, list[list]],
                                hero_names: dict[str, str]):
    best = None
    for file, rows in actions_by_file.items():
        name_hits = 0
        hero_hits = 0
        rating_hits = 0
        details = []
        for player in ocr_players:
            row, name_match = find_action_row(player, rows, hero_names)
            hero = str(player.get("hero") or "")
            rating = player.get("rating")
            hero_name = hero_names.get(str(row[2]), "") if row else ""
            hero_match = bool(row and hero_name and hero == hero_name)
            rating_match = bool(row and rating is not None and abs(float(rating) - float(row[3])) < 0.05)
            name_hits += int(name_match)
            hero_hits += int(hero_match)
            rating_hits += int(rating_match)
            details.append({
                "side": player.get("side"),
                "slot": player.get("slot"),
                "nickname": player.get("nickname"),
                "hero": hero or None,
                "rating": rating,
                "csvEntity": row[0] if row else None,
                "csvPlayer": row[1] if row else None,
                "nameMatch": name_match,
                "heroMatch": hero_match,
                "ratingMatch": rating_match,
            })
        score = (rating_hits, hero_hits, name_hits)
        if best is None or score > best[0]:
            best = (score, file, details)
    return best


def build_screenshot_checks(buy_by_file: dict[str, list[list]],
                            actions_by_file: dict[str, list[list]],
                            equip_prices: dict[str, dict[str, object]],
                            hero_names: dict[str, str]) -> list[dict]:
    checks: list[dict] = []
    if not SCREENSHOT_ROOT.exists():
        return checks

    root_str = str(ROOT)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    for sample_dir in sorted((p for p in SCREENSHOT_ROOT.iterdir() if p.is_dir()), key=lambda p: p.name):
        images = sorted(sample_dir.glob("*.jpg")) + sorted(sample_dir.glob("*.png"))
        if not images:
            checks.append({
                "dir": sample_dir.name,
                "status": "unavailable",
                "reason": "截图目录为空",
            })
            continue
        image = next((p for p in images if re.search(r"score|equip", p.name, re.I)), images[0])
        entry: dict = {
            "dir": sample_dir.name,
            "image": image.relative_to(ROOT).as_posix(),
            "status": "checked",
        }
        ocr_players: list[dict] = []
        try:
            import postgame_ocr  # type: ignore
            result = postgame_ocr.recognize(image.read_bytes(), name=image.name)
            ocr_players = []
            for player in result.get("players") or []:
                nickname = (player.get("nickname") or {}).get("value")
                hero = (player.get("hero") or {}).get("value")
                rating = (player.get("rating") or {}).get("value")
                ocr_players.append({
                    "side": player.get("side"),
                    "slot": player.get("slot"),
                    "nickname": nickname,
                    "hero": hero,
                    "rating": rating,
                })
            entry["ocr"] = {
                "pageType": result.get("pageType"),
                "match": result.get("match"),
                "players": ocr_players,
                "warnings": result.get("warnings") or [],
            }
        except Exception as error:  # OCR is optional; keep the check explicit.
            entry["ocrError"] = f"{type(error).__name__}: {error}"

        matched = match_screenshot_to_actions(ocr_players, actions_by_file, hero_names) if ocr_players else None
        if matched:
            (rating_hits, hero_hits, name_hits), file, details = matched
            summaries = summarize_buys(buy_by_file.get(file, []), equip_prices)
            by_entity = {row[0]: row for row in actions_by_file.get(file, [])}
            for detail in details:
                entity = detail.get("csvEntity")
                if entity is None:
                    continue
                summary = summaries.get(entity) or {}
                items = summary.get("items") or {}
                action_row = by_entity.get(entity) or []
                detail["buyRawNotifications"] = summary.get("rawNotifications", 0)
                detail["buyUniqueItems"] = len(items)
                detail["buySpendLowerBound"] = summary.get("spendLowerBound", 0)
                detail["buyUnknownPriceItems"] = summary.get("unknownPriceItems", 0)
                detail["buyItemIds"] = sorted(items.keys(), key=lambda value: int(value))
                detail["playerActionsUniqueItems"] = action_row[5] if len(action_row) > 5 else None
                detail["playerActionsSpendLowerBound"] = action_row[6] if len(action_row) > 6 else None
                panel = PANEL_TRUTH.get(normalize_key(detail.get("csvPlayer")))
                detail["panel"] = panel
                if panel:
                    detail["panelGold"] = panel["gold"]
                    detail["panelGoldSemantics"] = (
                        "赛后累计金币（外部面板，已含初始 300），不是当前可用余额；"
                        "回放用最终 6 格装备成本做严格一致性检查（成本 < 面板）。"
                    )
                    detail["buySumExceedsPanelGold"] = detail["buySpendLowerBound"] > panel["gold"]
                    detail["spendVsPanelDelta"] = detail["buySpendLowerBound"] - panel["gold"]
                manual = MANUAL_EQUIPMENT.get(normalize_key(detail.get("csvPlayer")))
                if manual:
                    manual_items = []
                    outside = 0
                    high = 0
                    final_cost = 0
                    final_known = 0
                    for slot, name, item_id, confidence in manual.get("items", []):
                        in_buy = (str(item_id) in items) if item_id else None
                        if item_id and not in_buy:
                            outside += 1
                        if confidence == "high":
                            high += 1
                        price_info = equip_prices.get(str(item_id)) or {}
                        buy_price = as_int(str(price_info.get("buy", 0)))
                        if item_id and buy_price:
                            final_cost += buy_price
                            final_known += 1
                        manual_items.append({
                            "slot": slot, "name": name, "itemId": item_id,
                            "confidence": confidence, "inBuySet": in_buy,
                        })
                    complete = (
                        manual.get("visible") == 6 and len(manual_items) == 6
                        and final_known == 6 and outside == 0
                    )
                    detail["manualEquipment"] = {
                        "visible": manual.get("visible"),
                        "identified": len(manual_items),
                        "highConfidence": high,
                        "outsideBuySet": outside,
                        "finalCost": final_cost,
                        "finalCostKnownSlots": final_known,
                        "complete6": complete,
                        "panelMinusFinalCost": (
                            (detail.get("panel") or {}).get("gold", 0) - final_cost
                            if detail.get("panel") else None
                        ),
                        "items": manual_items,
                        "note": manual.get("note", ""),
                    }
            entry["identity"] = {
                "matchedFile": file,
                "ocrPlayers": len(ocr_players),
                "nameHits": name_hits,
                "heroHits": hero_hits,
                "ratingHits": rating_hits,
                "players": details,
                "note": (
                    "OCR 昵称/英雄/评分与 11/2 player_actions 对照；OCR 会漏读右侧昵称、"
                    "并把 Z. 读成乙、诩读成翊，评分与英雄是更稳的同局证据；人工目测截图"
                    "可核对 10/10 昵称与英雄。"
                ),
            }
            if rating_hits >= 8 and (hero_hits + name_hits) >= 8:
                entry["matchedFile"] = file

            valid_details = [item for item in details if item.get("csvEntity") is not None]
            panels = [item["panel"]["gold"] for item in valid_details if item.get("panel")]
            buys = [item.get("buySpendLowerBound", 0) for item in valid_details]
            raw_buys = [item.get("buyRawNotifications", 0) for item in valid_details]
            unique_buys = [item.get("buyUniqueItems", 0) for item in valid_details]
            manual_visible = sum((item.get("manualEquipment") or {}).get("visible") or 0 for item in valid_details)
            manual_identified = sum((item.get("manualEquipment") or {}).get("identified") or 0 for item in valid_details)
            manual_high = sum((item.get("manualEquipment") or {}).get("highConfidence") or 0 for item in valid_details)
            manual_outside = sum((item.get("manualEquipment") or {}).get("outsideBuySet") or 0 for item in valid_details)
            manual_costs = [
                (item.get("manualEquipment") or {}).get("finalCost") or 0
                for item in valid_details if item.get("manualEquipment")
            ]
            complete_costs = [
                (item.get("manualEquipment") or {}).get("finalCost") or 0
                for item in valid_details
                if (item.get("manualEquipment") or {}).get("complete6")
            ]
            residuals = [
                (item.get("manualEquipment") or {}).get("panelMinusFinalCost")
                for item in valid_details
                if (item.get("manualEquipment") or {}).get("panelMinusFinalCost") is not None
            ]
            component_items = 0
            completed_items = 0
            seen_items = set()
            for item in valid_details:
                entity = item.get("csvEntity")
                for item_id in item.get("buyItemIds") or []:
                    key = (entity, item_id)
                    if key in seen_items:
                        continue
                    seen_items.add(key)
                    price_type = as_int(str((equip_prices.get(str(item_id)) or {}).get("type", 0)))
                    if price_type == 3:
                        completed_items += 1
                    elif price_type in (1, 2):
                        component_items += 1
            entry["goldAnalysis"] = {
                "panelSource": "01-score-equipment.jpg 赛后记分板（外部面板真值）",
                "panelGoldSemantics": (
                    "赛后累计金币（外部面板，已含初始 300），不是当前可用余额；"
                    "回放用最终 6 格装备成本做严格一致性检查（成本 < 面板）。"
                ),
                "panelGoldRange": [min(panels), max(panels)] if panels else None,
                "buyUniqueSumRange": [min(buys), max(buys)] if buys else None,
                "panelGoldTotal": sum(panels),
                "buyUniqueSumTotal": sum(buys),
                "buySumGreaterCount": sum(1 for item in valid_details if (item.get("buySpendLowerBound", 0) > ((item.get("panel") or {}).get("gold") or 0))),
                "playersCompared": len(valid_details),
                "finalBuildCostRange": [min(complete_costs), max(complete_costs)] if complete_costs else None,
                "finalBuildCostKnownRange": [min(manual_costs), max(manual_costs)] if manual_costs else None,
                "finalBuildCostCompleteCount": len(complete_costs),
                "panelCoversCostCount": sum(1 for value in residuals if value > 0),
                "panelCoversCostCompared": len(residuals),
                "minPanelMinusCost": min(residuals) if residuals else None,
                "rawBuyNotifications": sum(raw_buys),
                "uniqueBuyItems": sum(unique_buys),
                "duplicateNotifications": sum(raw_buys) - sum(unique_buys),
                "componentPurchaseItems": component_items,
                "completedPurchaseItems": completed_items,
                "note": (
                    "BUYEQUIP 去重集合同时包含合成件与成品（例如铁剑+无尽战刃、"
                    "神速之靴+抵抗之靴），原始通知还有重复；所以 unique 标价和 10/10 大于面板累计金币，"
                    "不能当累计花费。可对拍的是最终 6 格装备成本：5 名 6/6 完整识别玩家成本 6,175–9,130，"
                    "全部严格小于面板；9/10 满足 cost<panel。翳灵崽 4 格 6,130 > 面板 5,828（−302g）"
                    "是唯一异常，需查装备 ID/价格/面板读数或出售，不能加 300 掩盖。"
                    "本页不展示 gold_event_total，不推断收入；最终装备成本也不是逐笔购买账本。"
                ),
            }
            entry["equipmentManual"] = {
                "visibleIcons": manual_visible,
                "identifiedIcons": manual_identified,
                "highConfidenceIcons": manual_high,
                "outsideBuySet": manual_outside,
                "verdict": (
                    f"人工目测可辨认 {manual_identified}/{manual_visible} 个装备图标，"
                    f"其中高置信 {manual_high} 个；可辨认图标均落在各自 BUYEQUIP 去重集合内"
                    if manual_outside == 0 else
                    f"人工目测可辨认 {manual_identified}/{manual_visible} 个图标，"
                    f"其中 {manual_outside} 个不在 BUYEQUIP 集合内，需复核"
                ),
                "note": (
                    "截图装备只有图标、没有名称/ID；自动全库参考匹配未达可靠性阈值，"
                    "这里的结果来自逐格人工对照官方图标与玩家 BUYEQUIP 候选集，置信度已标注。"
                ),
                "players": [
                    {
                        "csvPlayer": item.get("csvPlayer"),
                        "panel": item.get("panel"),
                        **((item.get("manualEquipment") or {})),
                    }
                    for item in valid_details if item.get("manualEquipment")
                ],
            }

        equipment = {
            "regions": 0,
            "reliable": 0,
            "threshold": 0.94,
            "maxSimilarity": None,
            "result": "unavailable",
            "reason": "截图未提供装备面板或本地图像库不可用",
        }
        try:
            import vision  # type: ignore
            prepared, _crop = vision.prepare_image(image.read_bytes())
            regions = vision.visual_regions(prepared, "score")
            equipment_regions = [r for r in regions if r.get("kind") == "equipment"]
            sims = []
            reliable_candidates = []
            for region in equipment_regions:
                try:
                    candidates = vision.rank_icon(vision.crop_box(prepared, region["box"]), "equipment")
                except Exception:
                    candidates = []
                if candidates:
                    sims.append(float(candidates[0]["similarity"]))
                if region.get("status") == "reference" and region.get("candidates"):
                    reliable_candidates.append({
                        "side": region.get("side"),
                        "slot": region.get("slot"),
                        "index": region.get("index"),
                        "name": region["candidates"][0].get("name"),
                        "similarity": region["candidates"][0].get("similarity"),
                    })
            equipment = {
                "regions": len(equipment_regions),
                "reliable": len(reliable_candidates),
                "threshold": 0.94,
                "maxSimilarity": round(max(sims), 4) if sims else None,
                "result": "unverified" if not reliable_candidates else "partial",
                "reason": (
                    "截图装备区只有图标、没有装备名称/ID；本地官方图标参考匹配 "
                    f"{len(reliable_candidates)}/{len(equipment_regions)} 格达到 0.94 可靠性阈值，"
                    "不能据此认定 equip_id。"
                ),
                "reliableCandidates": reliable_candidates[:12],
            }
        except Exception as error:
            equipment["reason"] = f"本地图标参考匹配不可用：{type(error).__name__}: {error}"
        entry["equipment"] = equipment

        identity = entry.get("identity") or {}
        if entry.get("status") == "checked":
            parts = []
            if identity:
                parts.append(
                    f"OCR 同局核对：昵称 {identity['nameHits']}/{identity['ocrPlayers']}（含模糊）、"
                    f"英雄 {identity['heroHits']}/{identity['ocrPlayers']}、"
                    f"评分 {identity['ratingHits']}/{identity['ocrPlayers']}；"
                    "人工目测昵称/英雄 10/10。"
                )
            parts.append(equipment["reason"])
            manual = entry.get("equipmentManual") or {}
            if manual.get("verdict"):
                parts.append(manual["verdict"] + "。")
            gold = entry.get("goldAnalysis") or {}
            if gold:
                parts.append(
                    f"金币对拍：面板金币合计 {gold.get('panelGoldTotal')}，"
                    f"BUYEQUIP 去重标价和合计 {gold.get('buyUniqueSumTotal')}；"
                    f"{gold.get('buySumGreaterCount')}/{gold.get('playersCompared')} 名玩家的标价和大于面板金币。"
                    "即使面板金币是总获得，标价和也不能直接当累计花费；若是当前余额，也同样不能。"
                    "BUYEQUIP 含重复通知（"
                    f"raw {gold.get('rawBuyNotifications')} / unique {gold.get('uniqueBuyItems')}）"
                    "并同时含合成件与成品，因此本页只把它标为去重标价参考，不当作金币收入或累计花费。"
                )
            entry["conclusion"] = "".join(parts)
        checks.append(entry)
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-screenshot", action="store_true", help="skip OCR/icon screenshot checks")
    parser.add_argument("--skip-stream-index", action="store_true", help="skip gzip event-stream index")
    args = parser.parse_args()

    if not DS.exists():
        raise SystemExit(f"dataset directory not found: {DS}")

    players = read_csv("replay_players.csv")
    commands = read_csv("replay_commands.csv")
    headings = read_csv("replay_heading.csv")
    events = read_csv("replay_events.csv")
    tail_roster = read_csv("replay_tail_roster.csv")
    tail_commands = read_csv("replay_tail_commands.csv")
    tail_headings = read_csv("replay_tail_heading.csv")
    tail_events = read_csv("replay_tail_events.csv")
    tail_frames = read_csv("replay_tail_frames.csv")
    skin_rows = read_csv("agent_skin_ids.csv")

    equip_prices = load_equip_prices()
    hero_names = load_hero_names()
    buy_by_file, skill_by_file, actions_by_file, players_11 = read_11_2(equip_prices, hero_names)

    files: dict[str, dict] = {}

    def bucket(name: str) -> dict:
        if name not in files:
            label, day = file_label(name)
            files[name] = {
                "name": name,
                "label": label,
                "date": day,
                "players": [],
                "commands": [],
                "headings": [],
                "events": [],
                "tail": None,
                "heroMeta": [],
                "ratings": [],
                "buyEvents": [],
                "skillEvents": [],
                "actions": [],
                "synthetic": False,
            }
        return files[name]

    # Players: [team, slot, entity, nickname, offset].  In replay_players.csv
    # the "hero_id" column holds the object/entity id used throughout R2.
    for row in players:
        bucket(row["file"])["players"].append(
            [
                as_int(row.get("team")),
                as_int(row.get("slot")),
                as_int(row.get("hero_id")),
                row.get("name", ""),
                row.get("offset", ""),
            ]
        )

    # Commands: [seq, entity, isLocal, type, id, x, y, cmdSeq, segment]
    for row in commands:
        bucket(row["file"])["commands"].append(
            [
                as_int(row.get("seq")),
                as_int(row.get("hero_id")),
                1 if row.get("is_local") == "1" else 0,
                as_int(row.get("type")),
                as_int(row.get("id")),
                as_int(row.get("x")),
                as_int(row.get("y")),
                as_int(row.get("cmd_seq")),
                0,
            ]
        )
    for row in tail_commands:
        bucket(row["file"])["commands"].append(
            [
                as_int(row.get("seq")),
                as_int(row.get("hero_id")),
                -1,
                as_int(row.get("type")),
                as_int(row.get("id")),
                as_int(row.get("x")),
                as_int(row.get("y")),
                as_int(row.get("cmd_seq")),
                1,
            ]
        )

    # Headings: [seq, entity, isLocal, degree, segment]
    for row in headings:
        bucket(row["file"])["headings"].append(
            [
                as_int(row.get("seq")),
                as_int(row.get("hero_id")),
                1 if row.get("is_local") == "1" else 0,
                as_int(row.get("degree")),
                0,
            ]
        )
    for row in tail_headings:
        bucket(row["file"])["headings"].append(
            [
                as_int(row.get("seq")),
                as_int(row.get("hero_id")),
                -1,
                as_int(row.get("degree")),
                1,
            ]
        )

    # Events: [seq, entity, isLocal, tag, sub, dataHex, segment]
    for row in events:
        bucket(row["file"])["events"].append(
            [
                as_int(row.get("seq")),
                as_int(row.get("hero_id")),
                1 if row.get("is_local") == "1" else 0,
                as_int(row.get("tag")),
                as_int(row.get("sub")),
                row.get("data_hex", ""),
                0,
            ]
        )
    for row in tail_events:
        bucket(row["file"])["events"].append(
            [
                as_int(row.get("seq")),
                as_int(row.get("hero_id")),
                -1,
                as_int(row.get("tag")),
                as_int(row.get("sub")),
                row.get("data_hex", ""),
                1,
            ]
        )

    # Tail frame seq ranges (main sample only, but computed generally).
    tail_frame_ranges: dict[str, tuple[int, int, int]] = {}
    seqs_by_file: dict[str, list[int]] = defaultdict(list)
    for row in tail_frames:
        seqs_by_file[row["file"]].append(as_int(row.get("seq")))
    for name, seqs in seqs_by_file.items():
        tail_frame_ranges[name] = (min(seqs), max(seqs), len(seqs))

    # Tail roster / candidate rating pairs.
    for row in tail_roster:
        pairs = []
        for pair in (row.get("hero_skin_pairs") or "").split():
            if ":" not in pair:
                continue
            entity, value = pair.split(":", 1)
            pairs.append([as_int(entity), as_int(value)])
        name = row["file"]
        target = bucket(name)
        start = as_int(row.get("second_start"))
        second_frames = as_int(row.get("second_frames"))
        frame_start, frame_end = "", ""
        if name in tail_frame_ranges:
            frame_start, frame_end, _ = tail_frame_ranges[name]
        target["tail"] = {
            "lastMainSeq": as_int(row.get("last_main_seq")),
            "secondStart": start,
            "secondFrames": second_frames,
            "tailBytes": as_int(row.get("tail_bytes")),
            "footerBytes": as_int(row.get("footer_bytes")),
            "footerExtra": as_int(row.get("footer_extra")),
            "frameStart": frame_start,
            "frameEnd": frame_end,
            "pairs": pairs,
            "localSlot": as_int(row.get("local_slot")) if row.get("local_slot") not in ("", None) else None,
            "localHero": as_int(row.get("local_hero")) if row.get("local_hero") not in ("", None) else None,
            "values": row.get("values", ""),
            "rawPairs": row.get("hero_skin_pairs", ""),
        }

    # Optional hero/skin metadata and trailer ratings from R1's skin analysis.
    # player_skin: [entity, heroId, heroName, skinCompositeId, skinName]
    for row in skin_rows:
        if row.get("record_type") == "player_skin" and row.get("sample") in files:
            bucket(row["sample"])["heroMeta"].append(
                [
                    as_int(row.get("entityID")),
                    as_int(row.get("heroID")),
                    row.get("heroName", ""),
                    row.get("derived", ""),
                    row.get("derived_name", ""),
                ]
            )
        elif row.get("record_type") == "trailer_score" and row.get("sample") in files:
            bucket(row["sample"])["ratings"].append(
                [
                    as_int(row.get("entityID")),
                    round(as_float(row.get("raw")) / 100.0, 2),
                    row.get("verdict", ""),
                    as_int(row.get("team")),
                    as_int(row.get("slot")),
                ]
            )

    # 11/2 buy/skill/action data.  These files are not in replay_players.csv, so
    # a sample bucket is synthesized from the CSV rows; no commands/headings are
    # invented and team/slot stay unknown.
    for name in sorted(set(buy_by_file) | set(skill_by_file) | set(actions_by_file)):
        target = bucket(name)
        target["synthetic"] = target["synthetic"] or not target["players"]
        target["buyEvents"] = buy_by_file.get(name, [])
        target["skillEvents"] = skill_by_file.get(name, [])
        target["actions"] = actions_by_file.get(name, [])
        for entity, info in sorted(players_11.get(name, {}).items()):
            if not any(row[2] == entity for row in target["players"]):
                target["players"].append([0, None, entity, info["name"], "11/2-csv"])
            if info.get("heroName") and not any(row[0] == entity for row in target["heroMeta"]):
                target["heroMeta"].append([entity, info["heroId"], info["heroName"], "", ""])

    # Sort and deduplicate compact rows.
    for entry in files.values():
        entry["players"].sort(key=lambda x: (x[0], x[1] if x[1] is not None else 99, x[2]))
        entry["commands"].sort(key=lambda x: (x[0], x[1], x[8]))
        entry["headings"].sort(key=lambda x: (x[0], x[1], x[4]))
        entry["events"].sort(key=lambda x: (x[0], x[1], x[6]))
        entry["heroMeta"].sort(key=lambda x: x[0])
        entry["ratings"].sort(key=lambda x: x[0])
        entry["buyEvents"].sort(key=lambda x: (x[0], x[1], x[2]))
        entry["skillEvents"].sort(key=lambda x: (x[0], x[1], x[2]))
        entry["actions"].sort(key=lambda x: x[0])

    ordered = sorted(files.values(), key=lambda x: x["label"], reverse=True)

    source_files = []
    for name in (
        "replay_players.csv",
        "replay_commands.csv",
        "replay_heading.csv",
        "replay_events.csv",
        "replay_tail_roster.csv",
        "replay_tail_commands.csv",
        "replay_tail_heading.csv",
        "replay_tail_events.csv",
        "replay_tail_frames.csv",
        "agent_skin_ids.csv",
        "20261102_buy_events.csv",
        "20261102_skill_events.csv",
        "20261102_player_actions.csv",
        "agent_equip_prices.csv",
        EVENT_STREAM_GZIP,
    ):
        path = DS / name
        if path.exists():
            stat = path.stat()
            source_files.append(
                {
                    "name": name,
                    "bytes": stat.st_size,
                    "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                    "sha256": sha256(path)[:16],
                }
            )

    stream_index = None if args.skip_stream_index else build_event_stream_index()
    streams = available_streams()
    screenshot_checks = [] if args.skip_screenshot else build_screenshot_checks(
        buy_by_file, actions_by_file, equip_prices, hero_names
    )

    counts = {
        "files": len(ordered),
        "players": sum(len(x["players"]) for x in ordered),
        "commands": sum(len(x["commands"]) for x in ordered),
        "headings": sum(len(x["headings"]) for x in ordered),
        "events": sum(len(x["events"]) for x in ordered),
        "tailSegments": sum(1 for x in ordered if x["tail"] and x["tail"]["secondFrames"]),
        "tailFrames": sum((x["tail"] or {}).get("secondFrames", 0) for x in ordered),
        "heroMeta": sum(len(x["heroMeta"]) for x in ordered),
        "ratings": sum(len(x["ratings"]) for x in ordered),
        "buyEvents": sum(len(x["buyEvents"]) for x in ordered),
        "skillEvents": sum(len(x["skillEvents"]) for x in ordered),
        "playerActions": sum(len(x["actions"]) for x in ordered),
        "streamIndexed": (stream_index or {}).get("lines", 0),
        "screenshots": len(screenshot_checks),
    }

    bundle = {
        "version": 2,
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "source": "data/replays/_analysis/datasets",
        "schema": {
            "players": ["team", "slot", "entity", "name", "offset"],
            "commands": ["seq", "entity", "isLocal", "type", "id", "x", "y", "cmdSeq", "segment"],
            "headings": ["seq", "entity", "isLocal", "degree", "segment"],
            "events": ["seq", "entity", "isLocal", "tag", "sub", "dataHex", "segment"],
            "heroMeta": ["entity", "heroId", "heroName", "skinCompositeId", "skinName"],
            "ratings": ["entity", "rating", "verdict", "team", "slot"],
            "tailPairs": ["entity", "rawValue"],
            "buyEvents": ["frame", "entity", "equipId", "equipName", "buyPrice", "autoBuyRaw", "firstForEntity"],
            "skillEvents": ["frame", "entity", "slot", "level0", "autoLearnRaw"],
            "playerActions": [
                "entity", "player", "heroId", "score", "buyEventsRaw", "uniqueBuyItems",
                "uniqueEquipPriceSumUnverified", "buyEquipIds", "learnEvents", "learnSlots",
                "moveEvents", "attackEvents", "directionalSkill", "positionSkill", "objectiveSkill",
                "moveEventsFileTotal", "attackEventsFileTotal", "attackWithObjEventsFileTotal",
                "perPlayerAttribution",
            ],
            "stream": ["seq", "entity", "label", "x", "y", "degree", "data", "action", "itemId", "itemName", "price", "slot", "level", "autoRaw"],
        },
        "counts": counts,
        "sourceFiles": source_files,
        "eventStream": None,
        "eventStreamIndex": stream_index,
        "eventStreams": streams,
        "equipPrices": equip_prices,
        "heroNames": hero_names,
        "screenshotChecks": screenshot_checks,
        "files": ordered,
    }

    payload = json.dumps(bundle, ensure_ascii=False, separators=(",", ":"))
    OUT.write_text(
        "/* Generated by scripts/build_replay_review_bundle.py; read-only snapshot. */\n"
        "window.REPLAY_REVIEW_BUNDLE = " + payload + ";\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size:,} bytes)")
    print("counts:", json.dumps(counts, ensure_ascii=False))
    if stream_index:
        print(f"stream index: {stream_index['lines']:,} events / {len(stream_index['files'])} files")
    for check in screenshot_checks:
        print("screenshot:", check.get("dir"), check.get("status"), check.get("equipment", {}).get("result"))
    tag_counts = Counter((e[3], e[4]) for entry in ordered for e in entry["events"] if e[6] == 0)
    print("main event tags:", dict(tag_counts))


if __name__ == "__main__":
    main()
