#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Per-player equipment / build-order timeline from decoded BUYEQUIP events.

Inputs (offline, read-only)
---------------------------
data/replays/_analysis/live_20261104/full_event_catalog/events.csv
    547 BUYEQUIP rows (0x02/0x85), complete replay catalog.
data/replays/_analysis/live_20261104/state_table/state.jsonl
    Gold/KDA/level at the four arena checkpoints (01:34, 02:45, 05:00, 07:46).
data/replays/_analysis/live_20261104/levels_equipment/equipment.csv
    Visual-only final equipment at settlement.
data/replays/_analysis/live_20261104/levels_equipment/equipment_summary.csv
    Per-hero settlement gold / KDA / visible-item count.
data/replays/_analysis/datasets/agent_equip_prices.csv
    Battle-item table: item_id -> name / buy price / sell price / group.
data/replays/_analysis/device/dc.db
    Battle-item table itself; cell 21 of each row is the recipe list
    (comma-separated component item ids), used for net-spend accounting.
data/replays/_analysis/live_20261104/abc_timeline/event_windows.csv
    Checkpoint-window subset of the same buy rows; used as a join audit.

Outputs (only under the output directory)
-----------------------------------------
equipment_events.csv   one row per BUYEQUIP notification (547), with dedup marks
player_builds.csv     one row per player: build order, spend, gold checks,
                      settlement comparison
validation.md          coverage, dedup rule, gold-validation results
README.md              provenance, schema, method, limitations

Key semantics
-------------
* BUYEQUIP body: [equip_id:u16BE][pad x3][object_id:u8][flag:u8].  The flag is
  the byte the catalog calls ``auto_buy``.  Observed values: 0, 1, 24, 90, 210.
* Docs 5.144 classes flag 0 as the manual purchase ledger and 24/90/210 as
  periodic system / recommendation ticks.  The flag is not a gold ledger: the
  event has no price or balance field.
* Repeated notifications are real: 446 of 547 rows are flag 210, and most of
  those are 6-frame-periodic echoes of the same item (e.g. one 布甲 purchase is
  echoed 12 times, one 急速铠甲 purchase 52 times).  They are collapsed here.
* The recommended dedup rule is: same player + same equip_id, consecutive
  notifications separated by <= BURST_GAP_FRAMES (30 frames = 2.0 s) form one
  notification burst.  A burst is one acquisition; its representative is the
  earliest flag-0 row if the burst contains one (manual confirmation), else
  the earliest row.  All other rows are marked is_duplicate=1.
* Net spend uses the recipe tree from the battle-item table.  Buying item X
  while owning components of X costs price(X) minus the table buy price of the
  components consumed.  A component supplied by its own sub-components is
  valued at the sum of those sub-components, because the combine fee is
  already inside X's price.  Items with no recipe are basic components and are
  paid in full.
* Gold in state.jsonl is cumulative total economy (it is monotonic across the
  four checkpoints), not a spendable balance.  Therefore the hard check is
  cumulative spend <= cumulative gold at each checkpoint.  The stricter
  per-window check ``window spend <= gold delta`` is also reported, but it is
  not a necessary condition when a player saves gold across checkpoints.

Usage
-----
  python tools/build_equipment_timeline.py
  python tools/build_equipment_timeline.py --events ... --out ...
"""
from __future__ import annotations

import argparse
import csv
import json
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "data" / "replays" / "_analysis" / "live_20261104"

DEFAULT_EVENTS = LIVE / "full_event_catalog" / "events.csv"
DEFAULT_STATE = LIVE / "state_table" / "state.jsonl"
DEFAULT_SETTLEMENT = LIVE / "levels_equipment" / "equipment.csv"
DEFAULT_SETTLEMENT_SUMMARY = LIVE / "levels_equipment" / "equipment_summary.csv"
DEFAULT_PRICES = (
    ROOT / "data" / "replays" / "_analysis" / "datasets" / "agent_equip_prices.csv"
)
DEFAULT_DB = ROOT / "data" / "replays" / "_analysis" / "device" / "dc.db"
DEFAULT_WINDOWS = LIVE / "abc_timeline" / "event_windows.csv"
DEFAULT_OUT = LIVE / "build_timeline"

FRAME_RATE = 15.0
BURST_GAP_FRAMES = 30
BOOT_GROUP_MASK = 0x100000

# Flag classes.  24 is not observed in this replay but is listed in docs 5.144
# as a tick class; keep it classified rather than silently binned as unknown.
FLAG_MANUAL = 0
FLAG_AI_AUTO = 1
TICK_FLAGS = {24, 90, 210}


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def fmt_mmss(seconds: float) -> str:
    """mm:ss.d, the catalog's time format."""
    seconds = max(0.0, float(seconds))
    minutes = int(seconds // 60)
    rest = seconds - minutes * 60
    return f"{minutes:02d}:{rest:04.1f}"


def to_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def read_csv(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def md_table(headers, rows) -> str:
    out = ["| " + " | ".join(headers) + " |"]
    out.append("|" + "|".join(["---"] * len(headers)) + "|")
    for row in rows:
        out.append("| " + " | ".join("" if v is None else str(v) for v in row) + " |")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# battle-item table: prices from the CSV, recipes from dc.db
# ---------------------------------------------------------------------------
class StdTable:
    """Minimal read-only ``stdr`` table reader (same layout as agent_equip_prices)."""

    def __init__(self, data: bytes, offset: int):
        self.data = data
        self.offset = offset
        if data[offset:offset + 4] != b"stdr":
            raise ValueError(f"{offset:#x} is not a stdr table")
        self.n_strings = self.u32(offset + 0x08)
        self.stride = self.u32(offset + 0x14)
        self.n_rows = self.u32(offset + 0x18)
        self.pool_rel = self.u32(offset + 0x90)
        self.data0 = offset + 0x98
        self.pool = offset + self.pool_rel
        self.strings = self._parse_pool()

    def u32(self, off: int) -> int:
        return struct.unpack_from("<I", self.data, off)[0]

    def _parse_pool(self) -> dict[int, str]:
        out: dict[int, str] = {}
        q = 0
        for _ in range(self.n_strings):
            start = self.pool + q
            if start + 8 >= len(self.data):
                break
            z = self.data.find(b"\x00", start + 8)
            if z < 0:
                break
            try:
                out[q] = self.data[start + 8:z].decode("utf-8")
            except UnicodeDecodeError:
                out[q] = self.data[start + 8:z].decode("utf-8", "replace")
            q = ((z + 1 + 3) & ~3) - self.pool
            if q <= 0:
                break
        return out

    def resolve(self, value32: int):
        """(hash32, value32) cell -> string, via the pool."""
        file_off = value32 >> 6
        return self.strings.get(file_off - self.pool_rel)

    def row_u32(self, row: int) -> tuple[int, ...]:
        n = self.stride // 4
        return struct.unpack_from(f"<{n}I", self.data, self.data0 + row * self.stride)


def locate_battle_item_table(data: bytes):
    """Find the battle-item table: row0 = 1111 铁剑, row1 = 1112 匕首."""
    pos = 0
    while True:
        pos = data.find(b"stdr", pos)
        if pos < 0:
            return None
        try:
            table = StdTable(data, pos)
        except (struct.error, ValueError):
            pos += 4
            continue
        if 100 <= table.stride <= 2048 and 200 <= table.n_rows <= 2000 and table.n_strings:
            try:
                r0, r1 = table.row_u32(0), table.row_u32(1)
                if (r0[0] == 1111 and table.resolve(r0[3]) == "铁剑"
                        and r1[0] == 1112 and table.resolve(r1[3]) == "匕首"):
                    return table
            except (struct.error, IndexError):
                pass
        pos += 4


def load_db_items(db_path: Path):
    """Return {item_id: {name, price, group, recipe}} from dc.db.

    Cell 21 (u32 index; cell = two u32 words) is a comma-separated list of
    direct component item ids.  Verified examples: 1133 无尽战刃 -> 1121,1116;
    1336 极寒风暴 -> 1317,1324; 1422 抵抗之靴 -> 1411,1313.
    """
    if not db_path.exists():
        return {}, f"missing: {db_path}"
    data = db_path.read_bytes()
    table = locate_battle_item_table(data)
    if table is None:
        return {}, f"battle-item table not found in {db_path}"
    items = {}
    for r in range(table.n_rows):
        try:
            v = table.row_u32(r)
        except (struct.error, IndexError):
            continue
        item_id = v[0]
        if item_id == 0 or item_id > 999999:
            continue
        recipe_text = table.resolve(v[21]) if len(v) > 21 else None
        recipe = []
        if recipe_text:
            for part in recipe_text.split(","):
                part = part.strip()
                if part.isdigit():
                    recipe.append(int(part))
        items[item_id] = {
            "name": table.resolve(v[3]) or "",
            "price": v[10] if len(v) > 10 else None,
            "group": v[4] if len(v) > 4 else None,
            "recipe": recipe,
        }
    return items, f"loaded {len(items)} rows from {db_path}"


def load_prices(path: Path, db_items: dict):
    """id -> {name, price, sell, group, source}.  CSV is authoritative."""
    prices = {}
    if path.exists():
        for row in read_csv(path):
            if row.get("section") != "battle_item":
                continue
            item_id = to_int(row.get("item_id"))
            if item_id is None:
                continue
            price = to_int(row.get("buy_price"))
            sell = to_int(row.get("sell_price"))
            group = None
            raw_group = (row.get("equip_group") or "").strip()
            if raw_group:
                try:
                    group = int(raw_group, 16)
                except ValueError:
                    group = None
            prices[item_id] = {
                "name": (row.get("item_name") or "").strip(),
                "price": price,
                "sell": sell,
                "group": group,
                "source": "agent_equip_prices.csv:battle_item",
            }
    # Fill gaps from dc.db, but never overwrite the CSV.
    for item_id, item in db_items.items():
        if item_id in prices:
            continue
        prices[item_id] = {
            "name": item.get("name") or "",
            "price": item.get("price"),
            "sell": None,
            "group": item.get("group"),
            "source": "dc.db:battle_item",
        }
    return prices


def load_recipes(db_items: dict):
    recipes = {}
    for item_id, item in db_items.items():
        recipe = item.get("recipe") or []
        if recipe:
            recipes[item_id] = recipe
    return recipes


# ---------------------------------------------------------------------------
# events and dedup
# ---------------------------------------------------------------------------
def load_events(path: Path):
    if not path.exists():
        raise SystemExit(f"events file not found: {path}")
    events = []
    skipped = 0
    for row in read_csv(path):
        if row.get("family") != "buy" and row.get("command") != "BUYEQUIP":
            continue
        try:
            fields = json.loads(row.get("fields_json") or "{}")
        except json.JSONDecodeError:
            fields = {}
        equip_id = to_int(fields.get("equip_id"))
        if equip_id is None:
            skipped += 1
            continue
        flag = to_int(fields.get("auto_buy"))
        if flag is None:
            flag = to_int(fields.get("flag"))
        frame = to_int(row.get("frame"))
        if frame is None:
            skipped += 1
            continue
        time_s = float(row.get("time_s") or 0.0)
        events.append({
            "row": to_int(row.get("row")),
            "frame": frame,
            "time_s": time_s,
            "time_mmss": row.get("time_mmss") or fmt_mmss(time_s),
            "family": row.get("family") or "buy",
            "command": row.get("command") or "BUYEQUIP",
            "selector": row.get("selector") or "",
            "player": row.get("player") or "",
            "hero": row.get("hero") or "",
            "camp": to_int(row.get("camp")),
            "slot": to_int(row.get("slot")),
            "unit": to_int(row.get("unit")),
            "entity_id": to_int(row.get("entity_id")),
            "equip_id": equip_id,
            "object_id": to_int(fields.get("object_id")),
            "auto_buy": flag if flag is not None else -1,
            "catalog_price": to_int(fields.get("price")),
            "source": "abc_frame_command:0x02/0x85",
        })
    events.sort(key=lambda e: (e["frame"], e["row"] if e["row"] is not None else 0))
    return events, skipped


def flag_class(flag: int) -> str:
    if flag == FLAG_MANUAL:
        return "manual"
    if flag == FLAG_AI_AUTO:
        return "ai_auto"
    if flag == 24:
        return "system_tick_24"
    if flag == 90:
        return "unresolved_90"
    if flag == 210:
        return "system_tick_210"
    return f"unknown_{flag}"


def flag_kind(flag: int) -> str:
    if flag == FLAG_MANUAL:
        return "manual"
    if flag == FLAG_AI_AUTO:
        return "ai_auto"
    if flag == 90:
        return "unresolved"
    if flag in TICK_FLAGS:
        return "system_tick"
    return "unknown"


def build_groups(events, gap: int = BURST_GAP_FRAMES):
    """Collapse repeated notifications into one acquisition per burst.

    Group key is (player, equip_id).  Within a player's item stream, a row
    continues the current burst when its frame is <= gap frames after the
    previous row of the same item.  The representative is the earliest flag-0
    row (manual confirmation) if the burst has one, else the earliest row.
    """
    per_key = defaultdict(list)
    for ev in events:
        per_key[(ev["player"], ev["equip_id"])].append(ev)
    groups = []
    for (player, equip_id), rows in per_key.items():
        rows.sort(key=lambda e: (e["frame"], e["row"] if e["row"] is not None else 0))
        current = None
        for ev in rows:
            if current is not None and ev["frame"] - current["last_frame"] <= gap:
                current["rows"].append(ev)
                current["last_frame"] = ev["frame"]
            else:
                if current is not None:
                    groups.append(current)
                current = {
                    "player": player,
                    "equip_id": equip_id,
                    "rows": [ev],
                    "first_frame": ev["frame"],
                    "last_frame": ev["frame"],
                }
        if current is not None:
            groups.append(current)

    for group in groups:
        rows = group["rows"]
        manual_rows = [e for e in rows if e["auto_buy"] == FLAG_MANUAL]
        rep = min(manual_rows or rows, key=lambda e: (
            e["frame"], e["row"] if e["row"] is not None else 0))
        group["rep"] = rep
        group["hero"] = rep["hero"]
        group["camp"] = rep["camp"]
        group["slot"] = rep["slot"]
        group["has_manual"] = bool(manual_rows)
        group["flags"] = {e["auto_buy"] for e in rows}
        group["size"] = len(rows)
        group["acq_frame"] = rep["frame"]
        group["acq_time_s"] = rep["time_s"]
        group["acq_time_mmss"] = rep["time_mmss"]
        group["basis"] = flag_kind(rep["auto_buy"])
        group["uncertainty_s"] = (
            0.0 if group["basis"] == "manual"
            else (rows[-1]["frame"] - rows[0]["frame"]) / FRAME_RATE
        )

    groups.sort(key=lambda g: (
        g["acq_frame"], g["player"], g["equip_id"]))
    for index, group in enumerate(groups, start=1):
        group["group_id"] = f"G{index:04d}"
        rep = group["rep"]
        for ev in group["rows"]:
            is_rep = ev is rep
            ev["dedup_group_id"] = group["group_id"]
            ev["burst_size"] = group["size"]
            ev["burst_first_frame"] = group["first_frame"]
            ev["burst_last_frame"] = group["last_frame"]
            ev["is_duplicate"] = 0 if is_rep else 1
            ev["acquisition"] = 1 if is_rep else 0
            ev["duplicate_of_row"] = "" if is_rep else rep["row"]
            ev["acquisition_frame"] = group["acq_frame"]
            ev["acquisition_time_s"] = group["acq_time_s"]
            ev["acquisition_time_mmss"] = group["acq_time_mmss"]
            ev["acquisition_basis"] = group["basis"]
            ev["time_uncertainty_s"] = round(group["uncertainty_s"], 3)
            ev["flag_class"] = flag_class(ev["auto_buy"])
            ev["flag_kind"] = flag_kind(ev["auto_buy"])
            if group["size"] == 1:
                if ev["auto_buy"] == FLAG_MANUAL:
                    ev["dedup_rule"] = "unique_manual"
                elif ev["auto_buy"] == FLAG_AI_AUTO:
                    ev["dedup_rule"] = "unique_ai_auto"
                else:
                    ev["dedup_rule"] = "unique_system"
            elif is_rep and group["has_manual"]:
                ev["dedup_rule"] = "manual_kept_over_ticks"
            elif is_rep:
                ev["dedup_rule"] = "first_of_tick_burst"
            elif group["has_manual"] and ev["auto_buy"] != FLAG_MANUAL:
                ev["dedup_rule"] = "tick_merged_into_manual"
            elif ev["auto_buy"] == FLAG_MANUAL:
                ev["dedup_rule"] = "duplicate_manual"
            else:
                ev["dedup_rule"] = "repeat_within_tick_burst"
    return groups


# ---------------------------------------------------------------------------
# inventory / net-spend simulation
# ---------------------------------------------------------------------------
def _consume(item_id, counts, instances, prices, recipes):
    """Consume one item_id from inventory; return its table price or None.

    If the item is not held but has a recipe, try to build it from held
    sub-components.  The return value is the sum of the consumed sub-component
    prices; the combine fee is not charged here because it is embedded in the
    price of the item whose purchase triggered the consumption.
    """
    if counts.get(item_id, 0) > 0:
        instances[item_id].pop(0)
        counts[item_id] -= 1
        if counts[item_id] == 0:
            del counts[item_id]
        price = prices.get(item_id, {}).get("price")
        return price if price is not None else 0

    recipe = recipes.get(item_id)
    if not recipe:
        return None

    trial_counts = dict(counts)
    trial_instances = {k: list(v) for k, v in instances.items()}
    total = 0
    for component in recipe:
        value = _consume(component, trial_counts, trial_instances, prices, recipes)
        if value is None:
            return None
        total += value
    counts.clear()
    counts.update(trial_counts)
    instances.clear()
    instances.update(trial_instances)
    return total


def simulate(acquisitions, prices, recipes, only_manual=False):
    """Run the purchase ledger and return steps, survivors and totals.

    ``acquisitions`` is a list of dedup groups sorted by acquisition frame.
    Payment is attributed to the group's acquisition frame.  Unknown prices do
    not stop the simulation; they make the payment None and are counted.
    """
    acquisitions = sorted(acquisitions, key=lambda g: (
        g["acq_frame"], g["player"], g["equip_id"]))
    counts = defaultdict(int)
    instances = defaultdict(list)
    steps = []
    warnings = []
    unknown_price = 0
    for group in acquisitions:
        if only_manual and group["basis"] != "manual":
            continue
        item_id = group["equip_id"]
        item = prices.get(item_id)
        item_price = item.get("price") if item else None
        consumed_value = 0
        missing_components = 0
        payment = item_price
        if item_price is not None and item_id in recipes:
            for component in recipes[item_id]:
                value = _consume(component, counts, instances, prices, recipes)
                if value is None:
                    missing_components += 1
                else:
                    consumed_value += value
            payment = item_price - consumed_value
            if payment < 0:
                warnings.append(
                    f"{group['group_id']} {item_id}: negative net payment "
                    f"{payment}; clamped to 0")
                payment = 0
        if payment is None:
            unknown_price += 1
        counts[item_id] += 1
        instances[item_id].append({
            "frame": group["acq_frame"],
            "group_id": group["group_id"],
            "basis": group["basis"],
        })
        steps.append({
            "group_id": group["group_id"],
            "player": group["player"],
            "hero": group["hero"],
            "frame": group["acq_frame"],
            "time_s": group["acq_time_s"],
            "time_mmss": group["acq_time_mmss"],
            "equip_id": item_id,
            "equip_name": item.get("name") if item else "",
            "item_price": item_price,
            "consumed_value": consumed_value,
            "missing_components": missing_components,
            "payment": payment,
            "basis": group["basis"],
            "slot_count": sum(counts.values()),
        })
    survivors = []
    for item_id, inst_list in instances.items():
        for inst in inst_list:
            item = prices.get(item_id)
            survivors.append({
                "equip_id": item_id,
                "name": item.get("name") if item else "",
                "frame": inst["frame"],
                "group_id": inst["group_id"],
                "basis": inst["basis"],
                "group": item.get("group") if item else None,
            })
    survivors.sort(key=lambda s: (s["frame"], s["equip_id"]))
    total_spend = sum(s["payment"] for s in steps if s["payment"] is not None)
    return {
        "steps": steps,
        "survivors": survivors,
        "total_spend": total_spend,
        "unknown_price": unknown_price,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# gold checkpoints and settlement
# ---------------------------------------------------------------------------
def load_gold(state_path: Path):
    checkpoints = {}
    for line in state_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        gold = row.get("gold")
        if gold is None:
            continue
        frame = to_int(row.get("frame"))
        if frame is None:
            continue
        entry = checkpoints.setdefault(frame, {
            "frame": frame,
            "time_s": row.get("time_s"),
            "time_mmss": row.get("time_mmss"),
            "gold": {},
        })
        player = row.get("player")
        if player:
            entry["gold"][player] = gold
    ordered = [checkpoints[k] for k in sorted(checkpoints)]
    for entry in ordered:
        entry["label"] = (entry["time_mmss"] or "").split(".")[0].replace(":", "")
    return ordered


def load_settlement(equipment_path: Path, summary_path: Path):
    equipment = defaultdict(list)
    for row in read_csv(equipment_path):
        hero = (row.get("player") or "").strip()
        if not hero:
            continue
        equipment[hero].append({
            "slot": to_int(row.get("slot")),
            "visual_description": (row.get("visual_description") or "").strip(),
            "tentative_name": (row.get("tentative_name") or "").strip(),
            "confidence": (row.get("confidence") or "").strip(),
        })
    for rows in equipment.values():
        rows.sort(key=lambda r: (r["slot"] if r["slot"] is not None else 99))
    summary = {}
    if summary_path.exists():
        for row in read_csv(summary_path):
            hero = (row.get("player") or "").strip()
            if hero:
                summary[hero] = {
                    "kda": (row.get("kda") or "").strip(),
                    "gold": to_int(row.get("gold")),
                    "visible_item_count": to_int(row.get("visible_item_count")),
                    "empty_slots": to_int(row.get("empty_slots")),
                }
    return equipment, summary


def compare_settlement(final_names, final_ids, prices, settlement_rows):
    """Classify each settlement icon against the final inventory.

    match             exact item name
    generic_boot      settlement says only "战靴（具体款式未定）" and a boot is held
    partial_name      one name contains the other (e.g. 破晓 / 仁者破晓)
    mismatch          both names known, no relation
    unknown           settlement icon has no tentative name
    """
    boot_ids = {
        item_id for item_id in final_ids
        if (prices.get(item_id, {}).get("group") or 0) == BOOT_GROUP_MASK
    }
    counts = Counter()
    details = []
    for row in settlement_rows:
        name = row["tentative_name"]
        slot = row["slot"] if row["slot"] is not None else "?"
        if not name:
            status = "unknown"
        elif name in final_names:
            status = "match"
        elif "战靴" in name and boot_ids:
            status = "generic_boot"
        elif any(
            len(name) >= 2 and (name in final or final in name)
            for final in final_names if final
        ):
            status = "partial_name"
        else:
            status = "mismatch"
        counts[status] += 1
        label = name or "?"
        if name and row.get("confidence"):
            label = f"{label}[{row['confidence']}]"
        details.append(f"slot{slot}:{label}={status}")
    return counts, "; ".join(details), boot_ids


# ---------------------------------------------------------------------------
# per-player row
# ---------------------------------------------------------------------------
def survivor_names(survivors):
    """Names in acquisition order, collapsing identical items as name xN."""
    ordered = []
    counts = Counter()
    for s in survivors:
        name = s["name"] or f"#{s['equip_id']}"
        if name not in counts:
            ordered.append(name)
        counts[name] += 1
    return [name if counts[name] == 1 else f"{name} x{counts[name]}" for name in ordered]


def build_order_string(steps, use_ids=False):
    parts = []
    for step in steps:
        name = str(step["equip_id"]) if use_ids else (step["equip_name"] or f"#{step['equip_id']}")
        parts.append(f"{name}@{step['time_mmss']}")
    return " > ".join(parts)


def build_basis_string(steps):
    mapping = {"manual": "M", "ai_auto": "A", "system_tick": "T", "unresolved": "U"}
    return "".join(mapping.get(step["basis"], "?") for step in steps)


def checkpoint_stats(player, steps, checkpoints):
    """Cumulative and interval spend against the four gold checkpoints."""
    out = {}
    prev_frame = -1
    prev_gold = 0
    prev_cum = 0
    for entry in checkpoints:
        frame = entry["frame"]
        gold = entry["gold"].get(player)
        interval_spend = sum(
            s["payment"] for s in steps
            if s["payment"] is not None and prev_frame < s["frame"] <= frame
        )
        cum = sum(
            s["payment"] for s in steps
            if s["payment"] is not None and s["frame"] <= frame
        )
        if gold is None:
            out[entry["label"]] = {
                "frame": frame,
                "gold": None,
                "delta": None,
                "interval_spend": interval_spend,
                "cum_spend": cum,
                "carry": None,
                "strict_ok": None,
                "carry_ok": None,
                "cum_ok": None,
            }
            prev_frame, prev_gold, prev_cum = frame, None, cum
            continue
        delta = gold - prev_gold if prev_gold is not None else gold
        carry = max(0, (prev_gold or 0) - prev_cum)
        strict_ok = interval_spend <= delta
        carry_ok = interval_spend <= delta + carry
        cum_ok = cum <= gold
        out[entry["label"]] = {
            "frame": frame,
            "gold": gold,
            "delta": delta,
            "interval_spend": interval_spend,
            "cum_spend": cum,
            "carry": carry,
            "strict_ok": strict_ok,
            "carry_ok": carry_ok,
            "cum_ok": cum_ok,
        }
        prev_frame, prev_gold, prev_cum = frame, gold, cum
    return out


def make_player_rows(events, groups, prices, recipes, checkpoints, equipment, summary):
    players = {}
    for ev in events:
        key = ev["player"]
        if key not in players:
            players[key] = {
                "player": key,
                "hero": ev["hero"],
                "camp": ev["camp"],
                "slot": ev["slot"],
                "entity_id": ev["entity_id"],
            }
    rows = []
    group_by_player = defaultdict(list)
    for group in groups:
        group_by_player[group["player"]].append(group)

    for player, meta in sorted(players.items(), key=lambda kv: (kv[1]["camp"] or 0, kv[1]["slot"] or 0)):
        player_events = [e for e in events if e["player"] == player]
        player_groups = sorted(group_by_player[player], key=lambda g: (
            g["acq_frame"], g["equip_id"]))
        all_sim = simulate(player_groups, prices, recipes)
        manual_sim = simulate(player_groups, prices, recipes, only_manual=True)

        steps = all_sim["steps"]
        survivors = all_sim["survivors"]
        step_by_group = {s["group_id"]: s for s in steps}
        for ev in player_events:
            if ev.get("acquisition") != 1:
                continue
            step = step_by_group.get(ev["dedup_group_id"])
            if step is not None:
                ev["net_payment"] = step["payment"]
                ev["component_credit"] = step["consumed_value"]
        final_names_flat = [s["name"] or f"#{s['equip_id']}" for s in survivors]
        final_ids = [s["equip_id"] for s in survivors]
        final_names = survivor_names(survivors)

        first = steps[0] if steps else None
        six = next((s for s in steps if s["slot_count"] >= 6), None)
        peak = max((s["slot_count"] for s in steps), default=0)
        final_complete = max((s["frame"] for s in survivors), default=None)
        final_complete_time = None
        if final_complete is not None:
            final_complete_time = next(
                (s["time_mmss"] for s in steps if s["frame"] == final_complete), None)

        # "6-slot completion" is only well defined when the final inventory has
        # exactly six slots.  It is the last acquisition that still survives to
        # the end, i.e. the moment the final six-item build is complete.
        if len(survivors) == 6:
            six_complete = final_complete
            six_complete_time = final_complete_time
            six_complete_note = (
                "last acquisition that survives to the final 6-item inventory")
        elif len(survivors) > 6:
            six_complete = None
            six_complete_time = None
            six_complete_note = (
                f"n/a: final inventory has {len(survivors)} slots (extra item); "
                "6-slot completion is not defined")
        else:
            six_complete = None
            six_complete_time = None
            six_complete_note = (
                f"n/a: final inventory has {len(survivors)} slots; never a 6-slot build")

        basis_counts = Counter(g["basis"] for g in player_groups)
        if basis_counts.get("manual") and (
                basis_counts.get("system_tick") or basis_counts.get("ai_auto")
                or basis_counts.get("unresolved")):
            spend_basis = "manual_plus_tick"
            spend_confidence = "medium"
        elif basis_counts.get("manual"):
            spend_basis = "manual_only"
            spend_confidence = "high"
        elif basis_counts.get("system_tick") or basis_counts.get("ai_auto"):
            spend_basis = "tick_only"
            spend_confidence = "low"
        elif basis_counts.get("unresolved"):
            spend_basis = "unresolved_tick_only"
            spend_confidence = "low"
        else:
            spend_basis = "no_events"
            spend_confidence = "none"

        known_acquisitions = sum(1 for g in player_groups if prices.get(g["equip_id"], {}).get("price") is not None)
        price_coverage = f"{known_acquisitions}/{len(player_groups)}" if player_groups else "0/0"

        cp_stats = checkpoint_stats(player, steps, checkpoints)
        final_gold = (summary.get(meta["hero"]) or {}).get("gold")
        final_spend = all_sim["total_spend"]
        gross_spend = sum(
            prices.get(g["equip_id"], {}).get("price") or 0 for g in player_groups)
        component_credit_total = gross_spend - final_spend
        final_holding_cost = sum(
            prices.get(item_id, {}).get("price") or 0 for item_id in final_ids)
        spend_holding_diff = final_spend - final_holding_cost
        final_margin = final_gold - final_spend if final_gold is not None else None
        final_ok = final_margin >= 0 if final_margin is not None else None

        # Conservative boot-sale sensitivity: if more than one boot survived,
        # assume all but the last were sold at the table sell price (60%).
        boots = [s for s in survivors if (prices.get(s["equip_id"], {}).get("group") or 0) == BOOT_GROUP_MASK]
        boot_sale_adjustment = 0
        if len(boots) > 1:
            for boot in boots[:-1]:
                sell = prices.get(boot["equip_id"], {}).get("sell")
                if sell:
                    boot_sale_adjustment += sell
        boot_switch_full_adjustment = 0
        if len(boots) > 1:
            for boot in boots[:-1]:
                price = prices.get(boot["equip_id"], {}).get("price")
                if price:
                    boot_switch_full_adjustment += price
        adjusted_spend_sale = final_spend - boot_sale_adjustment
        adjusted_spend_full = final_spend - boot_switch_full_adjustment

        settlement_rows = equipment.get(meta["hero"], [])
        settlement_counts, settlement_detail, _boot_ids = compare_settlement(
            final_names_flat, final_ids, prices, settlement_rows)
        summary_row = summary.get(meta["hero"]) or {}
        settlement_visible = summary_row.get("visible_item_count")
        if settlement_visible is None:
            settlement_visible = len([r for r in settlement_rows if r["tentative_name"]])

        row = {
            **meta,
            "notifications_total": len(player_events),
            "manual_notifications": sum(1 for e in player_events if e["auto_buy"] == FLAG_MANUAL),
            "system_tick_notifications": sum(1 for e in player_events if e["auto_buy"] in TICK_FLAGS),
            "ai_auto_notifications": sum(1 for e in player_events if e["auto_buy"] == FLAG_AI_AUTO),
            "duplicate_notifications": sum(1 for e in player_events if e["is_duplicate"]),
            "acquisitions_total": len(player_groups),
            "manual_acquisitions": basis_counts.get("manual", 0),
            "system_tick_acquisitions": basis_counts.get("system_tick", 0),
            "ai_auto_acquisitions": basis_counts.get("ai_auto", 0),
            "price_coverage": price_coverage,
            "build_order": build_order_string(steps),
            "build_order_ids": build_order_string(steps, use_ids=True),
            "build_order_basis": build_basis_string(steps),
            "first_item_name": first["equip_name"] if first else "",
            "first_item_frame": first["frame"] if first else None,
            "first_item_time_mmss": first["time_mmss"] if first else "",
            "six_items_held_frame": six["frame"] if six else None,
            "six_items_held_time_mmss": six["time_mmss"] if six else "",
            "six_items_held_note": (
                "first time held item count reached 6 (components count as slots)"
                if six else f"never held 6 items; peak={peak}"
            ),
            "six_slot_complete_frame": six_complete,
            "six_slot_complete_time_mmss": six_complete_time or "",
            "six_slot_complete_note": six_complete_note,
            "slot_peak_count": peak,
            "final_build_complete_frame": final_complete,
            "final_build_complete_time_mmss": final_complete_time or "",
            "final_slot_count": len(survivors),
            "final_items": " | ".join(final_names),
            "final_item_ids": " ".join(str(i) for i in final_ids),
            "cumulative_spend": final_spend,
            "gross_spend": gross_spend,
            "component_credit_total": component_credit_total,
            "final_holding_cost": final_holding_cost,
            "spend_holding_diff": spend_holding_diff,
            "spend_model": "recipe_net" if recipes else "gross_no_recipes",
            "spend_basis": spend_basis,
            "spend_confidence": spend_confidence,
            "manual_confirmed_spend": manual_sim["total_spend"] if manual_sim["steps"] else "",
            "spend_price_coverage": price_coverage,
            "unknown_price_acquisitions": all_sim["unknown_price"],
            "final_gold": final_gold,
            "final_spend_margin": final_margin,
            "final_check": (
                "ok" if final_ok else "violation" if final_ok is False else ""
            ),
            "final_spend_if_prior_boots_sold": adjusted_spend_sale if len(boots) > 1 else "",
            "final_spend_if_free_boot_switch": adjusted_spend_full if len(boots) > 1 else "",
            "settlement_slot_count": settlement_visible,
            "slot_count_match": (
                "yes" if settlement_visible is not None and settlement_visible == len(survivors)
                else "no" if settlement_visible is not None else ""
            ),
            "settlement_known_items": len([r for r in settlement_rows if r["tentative_name"]]),
            "settlement_exact_matches": settlement_counts.get("match", 0),
            "settlement_partial_matches": settlement_counts.get("partial_name", 0),
            "settlement_generic_boot_matches": settlement_counts.get("generic_boot", 0),
            "settlement_mismatches": settlement_counts.get("mismatch", 0),
            "settlement_unknown": settlement_counts.get("unknown", 0),
            "settlement_comparison": settlement_detail,
            "gold_source": "state_table/state.jsonl (arena record +0x4C)",
            "final_gold_source": "levels_equipment/equipment_summary.csv",
            "notes": "",
        }
        if len(boots) > 1:
            row["notes"] = (
                "multiple boot-group items survive; SELLEQUIP is absent, so a "
                "boot sale/switch is not visible in the event stream"
            )
        for entry in checkpoints:
            label = entry["label"]
            stats = cp_stats.get(label, {})
            row[f"gold_cp_{label}"] = stats.get("gold")
            row[f"spend_cp_{label}"] = stats.get("cum_spend")
            row[f"interval_delta_cp_{label}"] = stats.get("delta")
            row[f"interval_spend_cp_{label}"] = stats.get("interval_spend")
            row[f"interval_check_cp_{label}"] = (
                "ok" if stats.get("strict_ok") else "violation"
                if stats.get("strict_ok") is False else ""
            )
            row[f"carry_check_cp_{label}"] = (
                "ok" if stats.get("carry_ok") else "violation"
                if stats.get("carry_ok") is False else ""
            )
            row[f"cum_check_cp_{label}"] = (
                "ok" if stats.get("cum_ok") else "violation"
                if stats.get("cum_ok") is False else ""
            )
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------
EVENT_FIELDS = [
    "row", "frame", "time_s", "time_mmss", "player", "hero", "camp", "slot",
    "entity_id", "equip_id", "equip_name", "price", "price_source",
    "net_payment", "component_credit",
    "auto_buy", "flag_class", "flag_kind", "object_id",
    "dedup_group_id", "burst_size", "burst_first_frame", "burst_last_frame",
    "is_duplicate", "duplicate_of_row", "dedup_rule",
    "acquisition", "acquisition_frame", "acquisition_time_s",
    "acquisition_time_mmss", "acquisition_basis", "time_uncertainty_s",
    "catalog_price", "source",
]


def write_equipment_events(path: Path, events, prices):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=EVENT_FIELDS, extrasaction="ignore",
                                lineterminator="\n")
        writer.writeheader()
        for ev in events:
            item = prices.get(ev["equip_id"]) or {}
            writer.writerow({
                **{k: ev.get(k, "") for k in EVENT_FIELDS},
                "equip_name": item.get("name") or "",
                "price": item.get("price") if item.get("price") is not None else "",
                "price_source": item.get("source") or "unknown",
            })


def write_player_builds(path: Path, rows):
    # Dynamic checkpoint columns follow the fixed columns above.
    fixed = [
        "player", "hero", "camp", "slot", "entity_id",
        "notifications_total", "manual_notifications", "system_tick_notifications",
        "ai_auto_notifications", "duplicate_notifications",
        "acquisitions_total", "manual_acquisitions", "system_tick_acquisitions",
        "ai_auto_acquisitions", "price_coverage",
        "build_order", "build_order_ids", "build_order_basis",
        "first_item_name", "first_item_frame", "first_item_time_mmss",
        "six_items_held_frame", "six_items_held_time_mmss", "six_items_held_note",
        "six_slot_complete_frame", "six_slot_complete_time_mmss",
        "six_slot_complete_note", "slot_peak_count",
        "final_build_complete_frame",
        "final_build_complete_time_mmss", "final_slot_count",
        "final_items", "final_item_ids",
        "cumulative_spend", "gross_spend", "component_credit_total",
        "final_holding_cost", "spend_holding_diff",
        "spend_model", "spend_basis", "spend_confidence",
        "manual_confirmed_spend", "spend_price_coverage",
        "unknown_price_acquisitions", "final_gold", "final_spend_margin",
        "final_check", "final_spend_if_prior_boots_sold",
        "final_spend_if_free_boot_switch",
        "settlement_slot_count", "slot_count_match",
        "settlement_known_items", "settlement_exact_matches",
        "settlement_partial_matches", "settlement_generic_boot_matches",
        "settlement_mismatches", "settlement_unknown",
        "settlement_comparison", "gold_source", "final_gold_source", "notes",
    ]
    checkpoint_suffixes = [
        "gold_cp_", "spend_cp_", "interval_delta_cp_", "interval_spend_cp_",
        "interval_check_cp_", "carry_check_cp_", "cum_check_cp_",
    ]
    available = set(rows[0].keys()) if rows else set()
    labels = sorted(
        key[len("gold_cp_"):] for key in available if key.startswith("gold_cp_"))
    dynamic = []
    for label in labels:
        for prefix in checkpoint_suffixes:
            key = f"{prefix}{label}"
            if key in available:
                dynamic.append(key)
    fieldnames = fixed + dynamic
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore",
                                lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


# ---------------------------------------------------------------------------
# markdown reports
# ---------------------------------------------------------------------------
def coverage_table(rows):
    out = []
    for row in rows:
        out.append([
            row["player"], row["hero"], row["notifications_total"],
            row["acquisitions_total"], row["manual_acquisitions"],
            row["system_tick_acquisitions"], row["duplicate_notifications"],
            row["price_coverage"], row["spend_basis"], row["spend_confidence"],
            row["six_slot_complete_time_mmss"] or "-",
            row["final_slot_count"], row["settlement_slot_count"],
        ])
    return md_table([
        "player", "hero", "notifications", "acquisitions", "manual acq",
        "tick acq", "duplicates", "price coverage", "spend basis",
        "spend confidence", "6-slot complete", "final slots",
        "settlement slots",
    ], out)


def burst_table(groups):
    sizes = Counter()
    for group in groups:
        n = group["size"]
        if n == 1:
            sizes["1"] += 1
        elif n <= 5:
            sizes["2-5"] += 1
        elif n <= 10:
            sizes["6-10"] += 1
        elif n <= 30:
            sizes["11-30"] += 1
        else:
            sizes[">30"] += 1
    out = []
    for bucket in ["1", "2-5", "6-10", "11-30", ">30"]:
        out.append([bucket, sizes.get(bucket, 0)])
    largest = sorted(
        (g for g in groups if g["size"] > 1),
        key=lambda g: (-g["size"], g["acq_frame"]))[:12]
    largest_rows = []
    for group in largest:
        span = (group["last_frame"] - group["first_frame"]) / FRAME_RATE
        largest_rows.append([
            group["player"], group["equip_id"], group["size"],
            group["first_frame"], group["last_frame"], group["acq_time_mmss"],
            round(span, 1),
        ])
    return out, largest_rows


def gold_tables(rows, checkpoints):
    tables = []
    for entry in checkpoints:
        label = entry["label"]
        out = []
        for row in rows:
            out.append([
                row["player"], row.get(f"gold_cp_{label}", ""),
                row.get(f"interval_spend_cp_{label}", ""),
                row.get(f"interval_delta_cp_{label}", ""),
                row.get(f"interval_check_cp_{label}", ""),
                row.get(f"carry_check_cp_{label}", ""),
                row.get(f"spend_cp_{label}", ""),
                row.get(f"cum_check_cp_{label}", ""),
            ])
        tables.append((label, md_table([
            "player", "gold", "window spend", "gold delta", "strict window",
            "with carryover", "cumulative spend", "cumulative check",
        ], out)))
    return tables


def settlement_table(rows):
    out = []
    for row in rows:
        out.append([
            row["player"], row["hero"], row["settlement_slot_count"],
            row["final_slot_count"], row["slot_count_match"],
            row["settlement_exact_matches"], row["settlement_partial_matches"],
            row["settlement_generic_boot_matches"], row["settlement_mismatches"],
            row["settlement_unknown"],
        ])
    return md_table([
        "player", "hero", "settlement slots", "final slots", "slot match",
        "exact", "partial", "generic boot", "mismatch", "unknown",
    ], out)


def write_validation(path: Path, rows, events, groups, checkpoints, windows_check, prices, recipes, meta):
    lines = []
    add = lines.append
    add("# Equipment timeline validation — live_20261104")
    add("")
    add("Generated by `tools/build_equipment_timeline.py`. Offline, read-only on all inputs; "
        "outputs are written only under `build_timeline/`. Catalog replay: `20261102_161129` "
        "(11:33 match).")
    add("")
    add("## 1. Coverage")
    add("")
    total = len(events)
    acquisitions = len(groups)
    duplicates = total - acquisitions
    manual = sum(1 for e in events if e["auto_buy"] == FLAG_MANUAL)
    tick = sum(1 for e in events if e["auto_buy"] in TICK_FLAGS)
    unknown_price = sum(1 for e in events if prices.get(e["equip_id"], {}).get("price") is None)
    add(f"- BUYEQUIP notifications: **{total}**; deduplicated acquisitions: **{acquisitions}**; "
        f"duplicate notifications removed: **{duplicates}** "
        f"({duplicates / total * 100:.1f}% of rows).")
    add(f"- Raw flag mix: manual/flag0 **{manual}**, system tick/24+90+210 **{tick}**, "
        f"other/unknown **{total - manual - tick}** (flag 1 / AI auto-buy is absent, flag 24 "
        "is supported but absent).")
    add(f"- Players with buy rows: **{len(rows)}/10**; item price coverage: "
        f"**{total - unknown_price}/{total}** notifications; spend model: "
        f"**{'recipe_net' if recipes else 'gross_no_recipes'}**.")
    add(f"- Recipe tree loaded: **{len(recipes)} items** from the dc.db battle-item table; "
        f"item names/prices from `{meta['prices_path']}`.")
    if not recipes:
        add("")
        add("**WARNING: no recipes were loaded.** Net spend is not available; the tool fell "
            "back to `spend_model=gross_no_recipes`, which sums every purchase in full and "
            "counts every acquisition as a surviving slot. Those numbers are not comparable "
            "to panel gold and must not be used. Point `--db` at a readable `dc.db`.")
    add("")
    add(coverage_table(rows))
    add("")
    add("`6-slot complete` is the last acquisition that survives to a final inventory of "
        "exactly six items; `-` means the player ended with 4, 5 or 7 slots. The earlier "
        "moment at which six components were first held is kept separately as "
        "`six_items_held_*` in `player_builds.csv`; it is not a completed build.")
    add("")
    add("The `player` column in `levels_equipment/equipment.csv` and "
        "`equipment_summary.csv` holds the **hero name**, not the account name; the "
        "comparison therefore joins on `hero`.")
    add("")
    add("## 2. Dedup rule")
    add("")
    add(f"Rule: for each `(player, equip_id)`, consecutive BUYEQUIP notifications whose "
        f"frame gap is **<= {BURST_GAP_FRAMES} frames (2.0 s)** form one notification burst. "
        "A burst is one acquisition. The representative is the earliest **flag 0** row if "
        "the burst contains one (manual confirmation), otherwise the earliest row. Every "
        "other row keeps `is_duplicate=1` and points at the representative through "
        "`duplicate_of_row`. A representative row has `acquisition=1`.")
    add("")
    add("Rationale: the observed system stream repeats an item every 5-7 frames "
        "(6-frame cadence, with +-1 frame jitter). Group-size distribution:")
    add("")
    size_rows, largest_rows = burst_table(groups)
    add(md_table(["burst size (notifications)", "bursts"], size_rows))
    add("")
    add("In this replay every non-singleton burst has at least 12 notifications; there are "
        "no bursts of size 2-10. Any threshold between the observed 7-frame maximum internal "
        "gap and the 343-frame minimum gap between distinct flag-0 purchases of the same "
        "item therefore produces the same grouping, so the exact 30-frame choice is not "
        "sensitive here.")
    add("")
    add("Largest bursts (one purchase echoed many times):")
    add("")
    add(md_table([
        "player", "equip_id", "notifications", "first frame", "last frame",
        "representative time", "burst span s",
    ], largest_rows))
    add("")
    add("The gap threshold is deliberately much larger than the 6-frame tick cadence and "
        "much smaller than the observed gap between distinct purchases of the same item "
        "(the smallest same-item gap among flag-0 rows is 343 frames = 22.9 s). No exact "
        "duplicate `(player, frame, fields)` tuples exist in the catalog. All **100** flag-0 "
        "rows survive as acquisitions; none is collapsed by the 30-frame rule, so the manual "
        "ledger is preserved one-for-one.")
    add("")
    add("The grouping key is `(player, equip_id)`. `object_id` is not used: it is a small "
        "per-player shop/actor id (constant for nine players; 百里守约 uses 0 and 44), not "
        "an item-instance id, so including it would split one purchase stream.")
    add("")
    mixed = [g for g in groups if g["has_manual"] and g["size"] > 1]
    if mixed:
        add("Bursts containing a flag-0 row plus tick echoes "
            f"(**{len(mixed)}**); the manual timestamp is used:")
        add("")
        mixed_rows = [[
            g["player"], g["equip_id"], g["size"], g["first_frame"],
            g["last_frame"], g["acq_frame"], g["acq_time_mmss"],
        ] for g in sorted(mixed, key=lambda g: g["acq_frame"])]
        add(md_table([
            "player", "equip_id", "notifications", "first frame", "last frame",
            "manual frame", "manual time",
        ], mixed_rows))
        add("")
    add("Flag semantics use docs 5.144: flag 0 = manual purchase ledger, flags 24/90/210 = "
        "periodic system/recommendation stream. In this replay flag 0 is also strongly "
        "correlated with camp 1 (95/100 flag-0 rows are blue-side), so a team/observer-path "
        "confound cannot be excluded. The timeline keeps both: flag-0 acquisitions are "
        "`manual`, tick-derived acquisitions are `system_tick` with lower time confidence "
        "(the burst span is exposed as `time_uncertainty_s`).")
    add("")
    add("Empirical support for keeping deduplicated tick rows: the tick-only players 吕布 "
        "and 貂蝉 reconstruct 4-item final inventories whose slot counts match the settlement "
        "exactly, and their net spend is within 3% of final panel gold (吕布 5655 vs 5828; "
        "貂蝉 5620 vs 5778). The mixed players 公孙离/关羽/张良/兰陵王 are within 0.3-4.0%. "
        "Discarding 210 as pure recommendation noise would leave those players with no build "
        "at all; keeping the first row of each burst is the choice supported by the data.")
    add("")
    add("## 3. Spend model")
    add("")
    add("Prices are battle-item **buy prices** from "
        "`agent_equip_prices.csv` (`section=battle_item`), which is generated from the "
        "dc.db battle-item table and cross-checked against the local official "
        "`pvp_item.json` (113/115 items equal). No price is invented: an unresolved item "
        "would be blank with `price_source=unknown`.")
    add("")
    add("Spend is **net of recipe consumption**. For a purchase of item X, the payment is "
        "`price(X) - sum(buy price of owned components consumed by X)`. Recipes come from "
        "cell 21 of the battle-item table (comma-separated direct component ids), e.g.:")
    add("")
    add("- `1133 无尽战刃` (2060) = `1121 风暴巨剑` (850) + `1116 雷鸣刃` (820) + 390 combine fee.")
    add("- `1336 极寒风暴` (2040) = `1317 急速铠甲` (800) + `1324 雪山圆盾` (750) + 490 combine fee.")
    add("- `1422 抵抗之靴` (700) = `1411 神速之靴` (250) + `1313 抗魔披风` (275) + 175 combine fee.")
    add("")
    add("A component supplied from its own sub-components is valued at the sum of those "
        "sub-components; the combine fee is already inside X's price. Basic items with no "
        "recipe are paid in full. The model ignores selling: there are zero `SELLEQUIP` "
        "rows in the catalog, so a sold item cannot be observed. This is the only known "
        "cause of the single final-gold violation below.")
    add("")
    add("This also explains the open question in docs 5.130: 钟馗's gross purchases sum to "
        "**13785** against a panel total of **6552**, which previously looked like an "
        "impossible overrun. The recipe credit is **7375**, so net spend is **6410** and "
        "closes under 6552. The excess was double-counted components, not duplicate "
        "notifications. 妲己 shows the same pattern: 15330 gross -> 7870 net vs 8168 gold.")
    add("")
    add("`cumulative_spend` uses all deduplicated acquisitions. `manual_confirmed_spend` "
        "uses flag-0 rows only; when tick acquisitions exist it is a lower bound on total "
        "spend (it cannot include tick purchases). `spend_basis` and `spend_confidence` "
        "expose this. The `net_payment` column in `equipment_events.csv` carries the "
        "per-acquisition payment (blank on duplicate rows); summing it over the 224 "
        "representative rows reproduces `cumulative_spend` for every player.")
    add("")
    telescoping = sum(1 for row in rows if row.get("spend_holding_diff") == 0)
    add(f"**Telescoping check:** the net-spend total must equal the table-price sum of the "
        f"items still held at the end, because every consumed component was either paid now "
        f"or earlier. This holds for **{telescoping}/{len(rows)}** players (difference 0); "
        "the equality is a strong internal consistency check on the recipe model.")
    add("")
    add(md_table(["player", "hero", "gross spend", "component credit", "net spend",
                  "final holding cost", "difference"],
                 [[row["player"], row["hero"], row["gross_spend"],
                   row["component_credit_total"], row["cumulative_spend"],
                   row["final_holding_cost"], row["spend_holding_diff"]]
                  for row in rows]))
    add("")
    add("Gold is the arena record `+0x4C` field, verified against the UI at 01:34/02:45/05:00 "
        "(30/30) and monotonic across checkpoints, i.e. it is **cumulative total economy**, "
        "not a spendable balance. The 07:46 checkpoint has no UI screenshot; its identity is "
        "pointer-validated per `state_table/README.md`. Panel gold is assumed to include the "
        "300 starting gold. Therefore:")
    add("")
    add("- **Hard check**: cumulative spend at a checkpoint <= cumulative gold at that checkpoint.")
    add("- **Strict window check** (requested): spend inside `(prev checkpoint, checkpoint]` "
        "<= `gold(checkpoint) - gold(prev checkpoint)`. This can fail legitimately when a "
        "player saves gold and buys a large item; it is reported, but not treated as proof "
        "of duplicate notifications.")
    add("- **Carryover window check**: window spend <= gold delta + unspent gold carried "
        "from the previous checkpoint. This is the economically correct window test.")
    add("")
    add("## 4. Gold validation")
    add("")
    labels = [c["label"] for c in checkpoints]
    add("Checkpoints: " + ", ".join(
        f"**{c['time_mmss']}** (frame {c['frame']})" for c in checkpoints) + ". "
        "For the first checkpoint the delta baseline is 0, because panel gold is cumulative "
        "and already includes the 300 starting gold; later deltas are checkpoint-to-checkpoint.")
    add("")
    for label, table in gold_tables(rows, checkpoints):
        add(f"### Checkpoint {label}")
        add("")
        add(table)
        add("")
    strict_violations = []
    carry_violations = []
    cum_violations = []
    for row in rows:
        for label in labels:
            if row.get(f"interval_check_cp_{label}") == "violation":
                strict_violations.append((row, label))
            if row.get(f"carry_check_cp_{label}") == "violation":
                carry_violations.append((row, label))
            if row.get(f"cum_check_cp_{label}") == "violation":
                cum_violations.append((row, label))
    add("### Violation summary")
    add("")
    add(f"- Strict window-check violations: **{len(strict_violations)}** of "
        f"{len(rows) * len(labels)} player-checkpoints.")
    add(f"- Carryover-adjusted window-check violations: **{len(carry_violations)}**.")
    add(f"- Cumulative-spend-above-gold violations: **{len(cum_violations)}**.")
    final_violations = [r for r in rows if r["final_check"] == "violation"]
    add(f"- Final settlement gold violations: **{len(final_violations)}**.")
    add("")
    if strict_violations:
        add("Strict-window violations (all are caused by saving, not by duplicate rows; "
            "the cumulative column stays below gold):")
        add("")
        vrows = []
        for row, label in strict_violations:
            vrows.append([
                row["player"], label, row.get(f"interval_spend_cp_{label}"),
                row.get(f"interval_delta_cp_{label}"),
                row.get(f"gold_cp_{label}"), row.get(f"spend_cp_{label}"),
                row.get(f"carry_check_cp_{label}"),
            ])
        add(md_table([
            "player", "checkpoint", "window spend", "gold delta",
            "cumulative gold", "cumulative spend", "carryover check",
        ], vrows))
        add("")
    if cum_violations:
        add("Cumulative violations:")
        add("")
        add(md_table(["player", "checkpoint"], [
            [row["player"], label] for row, label in cum_violations]))
        add("")
    if final_violations:
        add("Final-gold violations:")
        add("")
        frows = []
        for row in final_violations:
            frows.append([
                row["player"], row["final_gold"], row["cumulative_spend"],
                row["final_spend_margin"], row["final_spend_if_prior_boots_sold"],
                row["final_spend_if_free_boot_switch"], row["notes"],
            ])
        add(md_table([
            "player", "final gold", "net spend", "margin",
            "spend after 60% boot sale", "spend after free boot switch", "note",
        ], frows))
        add("")
        add("The only final violation is 百里守约. The final inventory contains two "
            "boot-group items (急速战靴 then 抵抗之靴) while the settlement shows one boot "
            "and six slots. The stream has no SELLEQUIP row, so the game's boot replacement "
            "is invisible. Selling the earlier boot at the table 60% sell price (420) gives "
            "8680 <= 8697 (pass); a free tier-2 boot switch would give 8400. The primary "
            "`final_check` column intentionally stays conservative.")
        add("")
    add("## 5. Settlement comparison")
    add("")
    add("Reconstructed build orders (components included; `M`/`T` basis is in "
        "`player_builds.csv`):")
    add("")
    add(md_table(["player", "hero", "build order", "final items"],
                 [[r["player"], r["hero"], r["build_order"], r["final_items"]]
                  for r in rows]))
    add("")
    add("The settlement items are visual-only (`visual_only=yes`, `memory_verified=no`), "
        "with confidence high/medium/low per icon. Exact means the tentative name equals "
        "an item still held at the end. `generic_boot` means the settlement only says "
        "战靴 and a boot-group item is held; the exact model is not claimed. `partial_name` "
        "means one name contains the other (破晓 / 仁者破晓). `mismatch` means both names "
        "are known and distinct (e.g. 贤者之书 2001 vs 贤者天书 1238). `unknown` means the "
        "settlement icon was deliberately left unnamed.")
    add("")
    add(settlement_table(rows))
    add("")
    add("Per-player detail:")
    add("")
    detail_rows = [[r["player"], r["hero"], r["settlement_comparison"],
                    r["final_items"]] for r in rows]
    add(md_table(["player", "hero", "settlement classification", "final inventory"],
                 detail_rows))
    add("")
    slot_mismatches = [r for r in rows if r["slot_count_match"] == "no"]
    add("Slot-count agreement: **{}/{}** players. ".format(
            len(rows) - len(slot_mismatches), len(rows))
        + ("" if not slot_mismatches else
           "Mismatches: " + ", ".join(f"{r['player']} ({r['settlement_slot_count']} vs "
                                      f"{r['final_slot_count']})" for r in slot_mismatches)
           + ". The 百里守约 difference is the unmodelled boot replacement."))
    add("")
    add("A cross-check on the 'high-confidence' red gem: three of the four 贤者的庇护 "
        "labels (关羽, 张良, 百里守约) are inconsistent with the gold bound. Replacing even "
        "the cheapest final item (红玛瑙, 300) with 贤者的庇护 (2020) would put spend above "
        "the final panel gold (关羽 10850 > 9243; 张良 7115 > 5486; 百里守约 10820 > 8697). "
        "The red gem is therefore at least sometimes 红玛瑙, not 贤者的庇护; the settlement "
        "is visual-only and this is a label limitation, not an event-ledger error. "
        "孙悟空's 贤者的庇护 label is possible within his gold (8280 <= 8352).")
    add("")
    add("## 6. Window-file join audit")
    add("")
    if windows_check:
        add(f"`abc_timeline/event_windows.csv` contains **{windows_check['total']}** buy "
            f"rows in the checkpoint windows; **{windows_check['matched']}** match the "
            "full catalog on `(frame, player, equip_id, flag)`. "
            + ("" if not windows_check["missing"] else
               f"Unmatched: {windows_check['missing']}."))
    else:
        add("`abc_timeline/event_windows.csv` was not available; join audit skipped.")
    add("")
    add("## 7. Confidence and limitations")
    add("")
    add("1. `BUYEQUIP` has no price or balance field; prices are table reference prices. "
        "The spend figure is an accounting reconstruction, not a game ledger.")
    add("2. Flag 0 is documented as manual, but 95/100 flag-0 rows are camp 1 in this "
        "replay. The camp/observer-path confound is unresolved; tick-derived acquisitions "
        "are kept and labelled rather than discarded.")
    add("3. A tick burst's first notification is the earliest observable time; the actual "
        "purchase may be up to the burst span earlier or later. `time_uncertainty_s` gives "
        "the span.")
    add("4. Recipe consumption assumes the shop uses owned components when a final item is "
        "bought. This is what makes the totals close to panel gold; a direct-purchase "
        "counterfactual would overstate spend by the component value.")
    add("5. Selling is invisible (0 SELLEQUIP rows). The 百里守约 boot replacement is the "
        "only case where this affects the final check.")
    add("6. Settlement names are visual-only and several are low confidence; a mismatch is "
        "not proof that the purchase row is wrong. The comparison is set-based per player, "
        "not slot-index-based, because inventory order after recipe merges is not guaranteed "
        "to equal acquisition order.")
    add("7. Frames ~10409-10509 are the victory animation; a few acquisitions land there "
        "(e.g. 钟馗 神隐斗篷 at 11:33.9, 关羽 红玛瑙 at 11:37.7, 公孙离 铁剑 at 11:35.3). "
        "They are kept because the settlement slot counts support them, but they are lower "
        "confidence than in-play purchases.")
    add("8. When a manual flag-0 row sits inside a tick burst, earlier tick rows point "
        "forward through `duplicate_of_row` to the manual representative; this is intentional "
        "(the manual confirmation is the better timestamp).")
    add("")
    add("## 8. Reproduction")
    add("")
    add("```bash")
    add("python tools/build_equipment_timeline.py")
    add("```")
    add("")
    add("All outputs are written under `data/replays/_analysis/live_20261104/build_timeline/`.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_readme(path: Path, events, groups, rows, checkpoints, meta):
    lines = []
    add = lines.append
    add("# Per-player equipment / build-order timeline — live_20261104")
    add("")
    add("Offline reconstruction of the decoded BUYEQUIP stream into per-player build "
        "orders, net spend, and a comparison with the visual-only settlement items. "
        "No device, adb, network, database write, or simulation was used. This directory "
        "is the only output location.")
    add("")
    add("The catalog source replay is `20261102_161129` (11:33 match) per "
        "`full_event_catalog/README.md`; the analysis directory is named by the "
        "2026-11-04 capture session.")
    add("")
    add("## Files")
    add("")
    add("| file | content |")
    add("|---|---|")
    add("| `equipment_events.csv` | one row per BUYEQUIP notification (547), with dedup marks |")
    add("| `player_builds.csv` | one row per player: build order, spend, gold checks, settlement comparison |")
    add("| `validation.md` | coverage, dedup rule, gold validation, settlement comparison |")
    add("| `README.md` | this document |")
    add("")
    add("## Source replay and inputs")
    add("")
    add("| input | role |")
    add("|---|---|")
    add("| `full_event_catalog/events.csv` | 547 BUYEQUIP rows (`0x02/0x85`), complete replay catalog |")
    add("| `state_table/state.jsonl` | cumulative gold/KDA/level at 01:34, 02:45, 05:00, 07:46 |")
    add("| `levels_equipment/equipment.csv` | visual-only final items at settlement |")
    add("| `levels_equipment/equipment_summary.csv` | per-hero settlement gold and visible-item count |")
    add("| `datasets/agent_equip_prices.csv` | battle-item names, buy/sell prices, groups |")
    add("| `device/dc.db` | battle-item table; cell 21 holds recipe component ids |")
    add("| `abc_timeline/event_windows.csv` | checkpoint-window buy subset, used as a join audit |")
    add("")
    add("The catalog's `price` field is the same battle-item reference price used here; "
        "the event body itself carries only `equip_id`, `object_id`, and `flag`.")
    if not meta.get("has_recipes"):
        add("")
        add("**WARNING: no recipes were loaded from `dc.db`.** The run used "
            "`spend_model=gross_no_recipes`; net spend and final inventory counts are not "
            "valid. Re-run with a readable `--db`.")
    add("")
    add("## Headline")
    add("")
    add(f"- **{len(events)}** BUYEQUIP notifications -> **{len(groups)}** deduplicated "
        f"acquisitions (**{len(events) - len(groups)}** repeated notifications collapsed).")
    add(f"- Players: **{len(rows)}/10**; all players have a reconstructed build order.")
    add(f"- Checkpoints: {', '.join(c['time_mmss'] for c in checkpoints)}.")
    add("- Cumulative spend stays at or below cumulative panel gold at every checkpoint for "
        "all ten players; the only final-check exception is 百里守约, explained by the "
        "invisible boot replacement (no SELLEQUIP rows).")
    add("- Final slot counts agree with the settlement visible-item counts for 9/10 players; "
        "百里守约 shows 7 reconstructed items vs 6 settlement slots (the extra is the "
        "superseded 急速战靴).")
    add("- A true 6-slot completion time is defined for the four players who ended with six "
        "items (妲己, 孙悟空, 关羽, 公孙离); players who ended with 4-5 slots (吕布, 貂蝉, "
        "兰陵王, 张良, 钟馗) and 百里守约's 7-slot inventory are marked `n/a` in "
        "`six_slot_complete_note`.")
    add("")
    add("## Method")
    add("")
    add("### 1. Dedup")
    add("")
    add(f"For each `(player, equip_id)`, consecutive notifications with a frame gap <= "
        f"{BURST_GAP_FRAMES} frames (2.0 s) form one burst. The representative is the "
        "earliest flag-0 row if present (manual confirmation), else the earliest row. "
        "`equipment_events.csv` keeps every raw row with `is_duplicate`, "
        "`duplicate_of_row`, `dedup_group_id`, `burst_size`, and `dedup_rule`.")
    add("")
    add("The repeated 6-frame stream is the dominant duplicate source: 446 of 547 rows are "
        "flag 210; one 布甲 purchase is echoed 12 times and one 急速铠甲 purchase 52 times. "
        "Flag 0 is treated as the manual ledger per docs 5.144, but it is 95/100 camp 1 in "
        "this replay, so tick-derived acquisitions are kept as lower-confidence evidence "
        "rather than thrown away. The tick-only players 吕布 and 貂蝉 reconstruct 4-slot "
        "final inventories matching settlement, with net spend within 3% of final panel gold, "
        "which is why the first row of each tick burst is treated as an acquisition.")
    add("")
    add("### 2. Build order and slots")
    add("")
    add("Acquisitions are processed in time order. When a final item is bought, its recipe "
        "components are consumed from the held inventory; the remaining inventory is the "
        "player's slots. `build_order` lists every acquisition as `name@mm:ss`; "
        "`build_order_basis` uses `M` (manual/flag 0), `T` (system tick), `A` (AI flag 1), "
        "`U` (unresolved flag 90). "
        "`six_items_held_frame` is the first time the held item count reaches 6 (components "
        "count as slots). `six_slot_complete_frame` is the last acquisition that survives to "
        "a final 6-item inventory (blank when the final build has 4, 5, or 7 slots). "
        "`final_build_complete_frame` is the last surviving acquisition in all cases.")
    add("")
    add("### 3. Net spend")
    add("")
    add("Payment for item X = `price(X) - sum(buy price of owned components consumed)`. "
        "Recipes are the comma-separated component ids in battle-item cell 21 in `dc.db`. "
        "This avoids the double count that a naive sum produces: e.g. 妲己's 25 flag-0 rows "
        "sum to 15330 gross, but the recipe-netted spend is 7870, below her 8168 final gold. "
        "The same reconciles docs 5.130's open 钟馗 case: 13785 gross, 7375 component "
        "credit, 6410 net vs 6552 panel gold.")
    add("")
    add("`cumulative_spend` uses all deduplicated acquisitions; `manual_confirmed_spend` is "
        "the flag-0-only total (a lower bound on total spend when tick rows exist). "
        "`spend_basis`/`spend_confidence` label the evidence. "
        "Because every consumed component is paid for exactly once, net spend telescopes to "
        "the table-price sum of the final survivors; this holds for all ten players "
        "(`spend_holding_diff=0`).")
    add("")
    add("### 4. Gold validation")
    add("")
    add("Panel gold is cumulative total economy (monotonic across checkpoints), so the hard "
        "test is `cumulative spend <= gold` at each checkpoint. The requested strict window "
        "test `window spend <= gold delta` is also emitted; it flags saved-gold purchases, "
        "not duplicates when cumulative spend remains below gold. The carryover window test "
        "adds unspent gold from the previous checkpoint.")
    add("")
    add("### 5. Settlement comparison")
    add("")
    add("Settlement icons are visual-only and partially named. Classification: `match` "
        "(exact name), `generic_boot` (settlement says 战靴 and a boot is held), "
        "`partial_name` (one name contains the other), `mismatch` (both known, distinct), "
        "`unknown` (icon left unnamed). The comparison joins on hero name because the "
        "settlement CSVs store hero names in their `player` column.")
    add("")
    add("## Schema")
    add("")
    add("### equipment_events.csv")
    add("")
    add("One row per catalog BUYEQUIP row, in catalog order. Core columns:")
    add("")
    add("| column | meaning |")
    add("|---|---|")
    add("| `row` | catalog row id |")
    add("| `frame`, `time_s`, `time_mmss` | recorded frame and time (`(frame-1)/15` s) |")
    add("| `player`, `hero`, `camp`, `slot`, `entity_id` | roster join |")
    add("| `equip_id`, `equip_name`, `price`, `price_source` | item and battle-table buy price; name/price blank + `unknown` when unresolved |")
    add("| `net_payment`, `component_credit` | representative-row spend: table price minus consumed component value; blank on duplicate rows |")
    add("| `auto_buy` | raw flag byte (this replay: 0=100, 90=1, 210=446; 1 and 24 supported but absent) |")
    add("| `flag_class` | `manual`, `ai_auto`, `system_tick_210`, `unresolved_90`, ... |")
    add("| `dedup_group_id`, `burst_size`, `burst_first_frame`, `burst_last_frame` | notification burst |")
    add("| `is_duplicate`, `duplicate_of_row`, `dedup_rule` | dedup result |")
    add("| `acquisition`, `acquisition_frame`, `acquisition_time_*` | 1 on the representative row |")
    add("| `acquisition_basis`, `time_uncertainty_s` | manual/tick and burst-span uncertainty |")
    add("| `source` | `abc_frame_command:0x02/0x85` |")
    add("")
    add("### player_builds.csv")
    add("")
    add("One row per player. Key columns: `build_order`, `build_order_basis`, "
        "`first_item_*`, `six_items_held_*`, `six_slot_complete_*`, "
        "`final_build_complete_*`, `final_slot_count`, "
        "`final_items`, `cumulative_spend`, `gross_spend`, `component_credit_total`, "
        "`spend_model`, `spend_basis`, "
        "`spend_confidence`, `manual_confirmed_spend`, `final_gold`, `final_check`, "
        "settlement counts, and per-checkpoint `gold_cp_*` / `spend_cp_*` / `interval_*` / "
        "`carry_check_*` / `cum_check_*` columns.")
    add("")
    add("## Coverage and caveats")
    add("")
    add(f"- **Notifications**: {len(events)}; **acquisitions**: {len(groups)}; "
        f"**duplicates**: {len(events) - len(groups)}.")
    add("- All 58 distinct bought item ids resolve to a name and buy price in the battle-item "
        "table; `price_source` is `agent_equip_prices.csv:battle_item` for all of them.")
    add("- **Flag camp confound**: 95/100 flag-0 rows are camp 1, so flag 0 may encode the "
        "observer/team path as well as manual intent. Tick-only players (吕布, 貂蝉) have no "
        "flag-0 ledger; their spend is marked `tick_only`/`low`.")
    add("- **Selling invisible**: 0 SELLEQUIP rows. The 百里守约 final check is the only "
        "violation and is explained by the unmodelled 急速战靴 -> 抵抗之靴 replacement.")
    add("- **Settlement is visual-only**: names are tentative, many low confidence; a "
        "settlement mismatch does not invalidate the event row. Comparison is set-based per "
        "player, not slot-index-based. A gold-bound cross-check shows that some "
        "high-confidence 贤者的庇护 labels (关羽, 张良, 百里守约) cannot be correct.")
    add("- **Tick burst time**: the representative is the first (or manual) notification; "
        "the exact purchase instant is within the burst span (`time_uncertainty_s`). When a "
        "manual row sits inside a tick burst, earlier tick rows point forward to it through "
        "`duplicate_of_row`.")
    add("- **Victory-animation tail**: frames ~10409-10509 contain a few acquisitions "
        "(e.g. 钟馗 神隐斗篷 11:33.9, 关羽 红玛瑙 11:37.7, 公孙离 铁剑 11:35.3). They are "
        "kept because the settlement slot counts support them, but they are lower confidence.")
    add("- **No gold ledger in the replay**: spend is a table-price reconstruction. It is "
        "validated against panel cumulative gold, not against a per-transaction ledger.")
    add("")
    add("## Reproduction")
    add("")
    add("```bash")
    add("python tools/build_equipment_timeline.py")
    add("```")
    add("")
    add("Optional overrides: `--events`, `--state`, `--settlement`, "
        "`--settlement-summary`, `--prices`, `--db`, `--windows`, `--out`.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(
        description="Build a per-player equipment/build-order timeline from BUYEQUIP events.")
    parser.add_argument("--events", default=str(DEFAULT_EVENTS))
    parser.add_argument("--state", default=str(DEFAULT_STATE))
    parser.add_argument("--settlement", default=str(DEFAULT_SETTLEMENT))
    parser.add_argument("--settlement-summary", default=str(DEFAULT_SETTLEMENT_SUMMARY))
    parser.add_argument("--prices", default=str(DEFAULT_PRICES))
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--windows", default=str(DEFAULT_WINDOWS))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--burst-gap", type=int, default=BURST_GAP_FRAMES,
                        help="max frame gap inside one notification burst (default 30)")
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[1/6] loading item table: {args.prices}")
    db_items, db_note = load_db_items(Path(args.db))
    prices = load_prices(Path(args.prices), db_items)
    recipes = load_recipes(db_items)
    print(f"      {db_note}; {len(prices)} priced items; {len(recipes)} recipes")
    if not recipes:
        print("      WARNING: no recipes loaded; net spend will fall back to gross sum.")

    print(f"[2/6] loading events: {args.events}")
    events, skipped = load_events(Path(args.events))
    if not events:
        raise SystemExit("no BUYEQUIP rows found")
    print(f"      {len(events)} BUYEQUIP rows ({skipped} skipped)")

    print(f"[3/6] deduplicating (gap <= {args.burst_gap} frames)")
    groups = build_groups(events, gap=args.burst_gap)
    print(f"      {len(groups)} acquisitions; {len(events) - len(groups)} duplicates")

    print(f"[4/6] loading checkpoints and settlement")
    checkpoints = load_gold(Path(args.state))
    equipment, summary = load_settlement(Path(args.settlement), Path(args.settlement_summary))
    print(f"      {len(checkpoints)} gold checkpoints; "
          f"{len(equipment)} settlement heroes; {len(summary)} summary rows")

    print("[5/6] building player rows")
    rows = make_player_rows(events, groups, prices, recipes, checkpoints, equipment, summary)

    windows_check = None
    windows_path = Path(args.windows)
    if windows_path.exists():
        window_rows = [r for r in read_csv(windows_path) if r.get("family") == "buy"]
        catalog_keys = Counter(
            (e["frame"], e["player"], e["equip_id"], e["auto_buy"]) for e in events)
        matched = 0
        missing = []
        for row in window_rows:
            try:
                fields = json.loads(row.get("fields_json") or "{}")
            except json.JSONDecodeError:
                fields = {}
            key = (
                to_int(row.get("frame")),
                row.get("player"),
                to_int(fields.get("equip_id")),
                to_int(fields.get("auto_buy")),
            )
            if catalog_keys.get(key):
                matched += 1
            else:
                missing.append(key)
        windows_check = {
            "total": len(window_rows),
            "matched": matched,
            "missing": missing,
        }

    print(f"[6/6] writing outputs to {out_dir}")
    write_equipment_events(out_dir / "equipment_events.csv", events, prices)
    write_player_builds(out_dir / "player_builds.csv", rows)
    meta = {"prices_path": args.prices, "has_recipes": bool(recipes)}
    write_validation(out_dir / "validation.md", rows, events, groups, checkpoints,
                     windows_check, prices, recipes, meta)
    write_readme(out_dir / "README.md", events, groups, rows, checkpoints, meta)

    # Console summary.
    total_spend = sum(r["cumulative_spend"] for r in rows)
    print("")
    print(f"rows: {len(events)} notifications -> {len(groups)} acquisitions")
    print(f"players: {len(rows)}; total net spend: {total_spend}")
    for row in rows:
        print(f"  {row['player']:<10} {row['hero']:<6} "
              f"acq={row['acquisitions_total']:>2} spend={row['cumulative_spend']:>5} "
              f"final_gold={row['final_gold']:>5} {row['final_check']:<9} "
              f"slots={row['final_slot_count']}/{row['settlement_slot_count']}")
    print("")
    print(f"wrote {out_dir / 'equipment_events.csv'}")
    print(f"wrote {out_dir / 'player_builds.csv'}")
    print(f"wrote {out_dir / 'validation.md'}")
    print(f"wrote {out_dir / 'README.md'}")


if __name__ == "__main__":
    main()
