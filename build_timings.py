"""Turn decoded purchase events into finished-item milestones ("三件套" time).

The replay records every ``BUYEQUIP`` at frame precision, so the *time* of a
purchase is decoded.  What is **not** in the file is the shop's recipe tree, so
"finished item" has to be defined by a rule rather than by the client's own
classification.  This module makes the rule explicit and auditable:

    finished  = buy price >= FINISHED_PRICE and not a shoe

Why this rule for the local samples: across the 135 first-seen purchases of the
20260101_000000 replay, prices cluster into <=399 (basic components), 700-999
(mid components) and >=1500 (top-tier items), with nothing bought in 1000-1499.
A shoe (id 1400-1499) is a finished slot of its own but is excluded here because
"三件套" conventionally counts core items, not boots.

Everything is derived: the timestamps are decoded, the classification is a rule.
Definitions that could be gamed by a different client build are reported with the
threshold in the output, never hard-coded into a claim.
"""
from __future__ import annotations

import collections

FINISHED_PRICE = 1000
BOOT_MIN_PRICE = 500
BIG_PRICE = 2000
SHOE_ID_LO, SHOE_ID_HI = 1400, 1500
MILESTONE_LABELS = ("first", "second", "third", "fourth", "fifth", "sixth")


def is_shoe(equip_id: int) -> bool:
    return SHOE_ID_LO <= int(equip_id) < SHOE_ID_HI


def mmss(seconds) -> str:
    total = int(seconds or 0)
    return f"{total // 60}:{total % 60:02d}"


def _select(purchases: list[dict], min_price: int, exclude_shoes: bool,
            include_upgraded_boots: bool = False) -> list[dict]:
    kept = []
    for item in purchases:
        price = item.get("price")
        if not price:
            continue
        shoe = is_shoe(item.get("equipId") or 0)
        if shoe:
            # An upgraded boot (>= 500) is a real finished slot; the 250 starter
            # boot is not counted even in the "with boots" convention.
            if exclude_shoes or not include_upgraded_boots or price < BOOT_MIN_PRICE:
                continue
        elif price < min_price:
            continue
        kept.append(item)
    kept.sort(key=lambda item: item["t"])
    return kept


def milestones(purchases: list[dict]) -> dict:
    """First six finished items and the derived 'three-piece' moment."""
    finished = _select(purchases, FINISHED_PRICE, exclude_shoes=True)
    entries = [{
        "t": round(item["t"], 3),
        "tText": mmss(item["t"]),
        "equipId": item["equipId"],
        "name": item.get("name") or "",
        "price": item.get("price"),
    } for item in finished]

    marks: dict = {}
    for index, label in enumerate(MILESTONE_LABELS):
        marks[label] = entries[index] if index < len(entries) else None

    three = marks["third"]
    return {
        "finishedCount": len(entries),
        "finished": entries,
        "milestones": marks,
        "threePieceTimeSec": three["t"] if three else None,
        "threePieceTimeText": three["tText"] if three else None,
        "threePieceItem": three["name"] if three else None,
        "note": (f"成品判定 = 购买价 ≥ {FINISHED_PRICE} 且非鞋（id {SHOE_ID_LO}-"
                 f"{SHOE_ID_HI - 1}）；三件套 = 第 3 件成品的购买时刻。"),
    }


def variants(purchases: list[dict]) -> dict:
    """The same milestones under the other conventions people use."""
    with_shoes = _select(purchases, FINISHED_PRICE, exclude_shoes=False,
                         include_upgraded_boots=True)
    big = _select(purchases, BIG_PRICE, exclude_shoes=True)

    def third(items):
        return {"t": round(items[2]["t"], 3), "tText": mmss(items[2]["t"]),
                "name": items[2].get("name") or ""} if len(items) >= 3 else None

    return {
        "noShoes": third(_select(purchases, FINISHED_PRICE, exclude_shoes=True)),
        "withShoes": third(with_shoes),
        "bigOnly2000": third(big),
    }


def timing_split(purchases: list[dict], entity_by_equip: dict | None = None) -> dict:
    """Group the decoded timestamps into build phases (grounded on the data)."""
    ordered = sorted(purchases, key=lambda item: item["t"])
    first = ordered[0]["t"] if ordered else None
    last = ordered[-1]["t"] if ordered else None
    return {
        "firstPurchase": {"t": round(first, 3), "tText": mmss(first)} if first else None,
        "lastPurchase": {"t": round(last, 3), "tText": mmss(last)} if last else None,
        "averageGapSec": (round((last - first) / max(1, len(ordered) - 1), 2)
                          if first is not None and len(ordered) > 1 else None),
    }


def build_report(state: dict) -> dict:
    """Attach build timings to every player of a replay state document."""
    by_entity: dict[int, list[dict]] = collections.defaultdict(list)
    for item in state.get("events", {}).get("purchases") or []:
        by_entity[item["entityId"]].append(item)

    per_player = {}
    for player in state.get("players") or []:
        entity = player["entityId"]
        purchases = by_entity.get(entity) or []
        info = milestones(purchases)
        info["variants"] = variants(purchases)
        info["profile"] = timing_split(purchases)
        info["hero"] = player.get("hero")
        info["player"] = player.get("player")
        per_player[str(entity)] = info

    return {
        "finishedPriceThreshold": FINISHED_PRICE,
        "bigPriceThreshold": BIG_PRICE,
        "shoeIdRange": [SHOE_ID_LO, SHOE_ID_HI - 1],
        "perPlayer": per_player,
        "caveat": ("购买时刻是解码出来的（帧级）；「成品」是按价格规则判定的，"
                   "本地没有商店合成树，换客户端版本后需要重新核对该阈值。"),
    }
