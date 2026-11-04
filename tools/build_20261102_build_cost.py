"""Cross-check final 6-slot equipment cost against the 11/2 post-game panel.

The panel gold is cumulative earned gold (external evidence), including the
initial 300.  A valid final inventory must satisfy held_cost < panel_gold
(strictly, because a player cannot spend down to exactly 0).  The final six-item
buy-price sum is compared with that constraint; this is a consistency check,
not a purchase ledger and not an income curve.
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "data/replays/_analysis/datasets"
BUNDLE = ROOT / "web/replay-review-data.js"
PRICES = DATASETS / "agent_equip_prices.csv"
PANEL = DATASETS / "20261102_panel_truth.csv"
OUT = DATASETS / "20261102_build_cost_vs_panel.csv"
SLOTS = 6


def load_bundle() -> dict:
    text = BUNDLE.read_text(encoding="utf-8")
    start = text.index("{")
    return json.loads(text[start:].rstrip().rstrip(";"))


def price_map() -> dict[int, tuple[str, int]]:
    out: dict[int, tuple[str, int]] = {}
    with PRICES.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            if row.get("section") != "battle_item" or not row.get("item_id"):
                continue
            try:
                item_id = int(row["item_id"])
                out.setdefault(item_id, (row["item_name"], int(row["buy_price"])))
            except ValueError:
                continue
    return out


def panel_rows() -> dict[int, dict]:
    out = {}
    with PANEL.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            out[int(row["entity"])] = row
    return out


def main() -> None:
    bundle = load_bundle()
    checks = bundle.get("screenshotChecks", [])
    if not checks:
        raise SystemExit("no screenshot checks in bundle")
    players = checks[0]["identity"]["players"]
    prices = price_map()
    panel = panel_rows()
    rows = []
    for player in players:
        entity = int(player["csvEntity"])
        equip = player.get("manualEquipment") or {}
        items = equip.get("items", [])
        known = []
        unknown = []
        for item in items:
            item_id = int(item.get("itemId") or 0)
            if item_id in prices:
                known.append((item_id, prices[item_id][0], prices[item_id][1],
                              item.get("confidence", "")))
            else:
                unknown.append(item)
        held_cost = sum(price for _, _, price, _ in known)
        panel_gold = int(player.get("panelGold") or panel.get(entity, {}).get("gold") or 0)
        visible = int(equip.get("visible") or len(items))
        identified = int(equip.get("identified") or len([i for i in items if i.get("itemId")]))
        complete = int(visible == SLOTS and identified == SLOTS
                       and not unknown and len(known) == SLOTS)
        conf = Counter(i.get("confidence") for i in items)
        rows.append({
            "file": checks[0].get("matchedFile", ""),
            "entity": entity,
            "player": player.get("csvPlayer") or player.get("nickname", ""),
            "hero": player.get("hero", ""),
            "kda": player.get("panel", {}).get("kda", ""),
            "panel_gold_cumulative": panel_gold,
            "visible_slots": visible,
            "identified_slots": identified,
            "known_price_slots": len(known),
            "unknown_price_slots": len(unknown),
            "complete_6": complete,
            "held_item_ids": " ".join(str(i) for i, _, _, _ in known),
            "held_item_names": " | ".join(n for _, n, _, _ in known),
            "held_cost": held_cost,
            "panel_minus_held": panel_gold - held_cost,
            "panel_covers_held": int(panel_gold > held_cost),
            "high_conf": conf.get("high", 0),
            "medium_conf": conf.get("medium", 0),
            "low_conf": conf.get("low", 0),
            "all_in_buy_set": int(all(i.get("inBuySet") for i in items)) if items else 0,
            "note": equip.get("note", ""),
        })
    rows.sort(key=lambda r: r["entity"])
    with OUT.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {OUT} ({len(rows)} players)")
    print("complete 6/6:", sum(r["complete_6"] for r in rows))
    print("panel > held_cost:", sum(r["panel_covers_held"] for r in rows), "/", len(rows))
    for r in rows:
        print(f'{r["entity"]:>4} {r["player"]:<12} gold={r["panel_gold_cumulative"]:>5} '
              f'held={r["held_cost"]:>5} residual={r["panel_minus_held"]:>5} '
              f'fail={r["panel_minus_held"] < 0} complete={r["complete_6"]}')


if __name__ == "__main__":
    main()
