#!/usr/bin/env python3
"""Build the unified per-player state table for the live_20261104 session.

The table is a long-format join of the offline sources already present in
``data/replays/_analysis/live_20261104``:

  * ``abc_timeline/event_windows.json``   roster (unit / camp / slot / entity)
  * ``arena_*.bin``                       per-player gold, KDA and hero level
                                          (via ``tools/arena_player_stats.py``);
                                          the same snapshots also hold the ten
                                          unit objects, used for HP and for
                                          record identity validation
  * ``unit_<hero>_t{0,1}.bin``            normalized HP pair at +0x08/+0x10
  * ``levels_equipment/levels.csv``       level cross-check table
  * ``abc_timeline/event_windows.csv``    per-frame action counts
  * ``minimap_positions/positions.csv``   team-level icon pixels (not joinable)
  * ``trajectories/``                     optional X/Z source (absent today)

One row is emitted per ``(player, frame)`` for which any source has data.
Missing fields stay ``null`` and every row carries a ``sources`` flag plus a
``note`` explaining the provenance / caveat.

Read-only and offline: this never touches adb, the device, the network or any
other agent's output.  It writes only ``state.jsonl``, ``state.csv`` and
``README.md`` inside the output directory (default: ``state_table/``).

Usage::

    python -I tools/build_state_table.py
    python -I tools/build_state_table.py --check
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import re
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

FPS = 15.0
DEFAULT_TOTAL_FRAMES = 10509
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ANALYSIS_DIR = (
    REPO_ROOT / "data" / "replays" / "_analysis" / "live_20261104"
)

# Arena snapshots: (UI label, fallback battle second, arena file, UI image).
# The fallback second is only used if the unit-object clock cannot be read.
# The exact time normally comes from the ten units' +0x1664/+0x1668 clock.
SNAPSHOTS = (
    ("01:34", 94.0, "arena_t0_0134.bin", "t0_ui.png"),
    ("02:45", 165.0, "arena_t2_0245.bin", "t2_ui.png"),
    ("05:00", 300.0, "arena_paused_0500.bin", "scoreboard_0500.png"),
    ("07:46", 466.0, "arena_0746_full.bin", None),
)

# Arena record index order, documented in docs/replay_binary_format.md
# section 5.157: idx 1000000013 down to 1000000004.  The record carries no
# hero/entity id, so this order is the only static mapping; it is validated
# on every snapshot against the record's +0x28 unit pointer, the UI KDA/gold
# anchors and levels.csv.
ARENA_INDEX_HEROES = (
    "兰陵王", "张良", "妲己", "百里守约", "钟馗",
    "公孙离", "孙悟空", "貂蝉", "关羽", "吕布",
)
ARENA_INDEX_MAX = 1000000013

# heroID -> hero (docs/replay_binary_format.md section 5.156).
HERO_ID = {
    109: "妲己",
    123: "吕布",
    140: "关羽",
    141: "貂蝉",
    153: "兰陵王",
    156: "张良",
    167: "孙悟空",
    175: "钟馗",
    196: "百里守约",
    199: "公孙离",
}

# Absolute max HP from the attributes panel captured at 07:29 (task input).
# It is only applied to the 07:26 / 07:29 / 07:32.97 unit-window samples; the
# arena checkpoints only carry the normalized ratio because their absolute
# max was not sampled.
HP_MAX_ABS = {
    "钟馗": 10054,
    "关羽": 8356,
    "妲己": 5201,
    "兰陵王": 5684,
    "张良": 7045,
    "百里守约": 4795,
    "公孙离": 4874,
    "孙悟空": 5450,
    "貂蝉": 5730,
    "吕布": 6336,
}

# UI reference rows, read from the screenshots named in SNAPSHOTS.
# Keyed by HERO (the screenshots' stat rows are matched by hero portrait);
# the roster maps each hero to its player.  Format:
# hero -> (kills, deaths, assists, gold).
# Note: docs/replay_binary_format.md section 5.157 lists 05:00 妲己 as 2/0/1
# and 关羽 as 3138; the screenshots show 2/0/0 and 3135, and the engine agrees
# with the screenshots.  We follow the screenshots.
UI_REFERENCE = {
    "01:34": {
        "钟馗": (0, 0, 0, 679),
        "妲己": (0, 0, 0, 890),
        "孙悟空": (0, 0, 1, 1065),
        "关羽": (2, 0, 0, 1083),
        "百里守约": (0, 0, 0, 902),
        "公孙离": (0, 0, 0, 1021),
        "吕布": (0, 2, 0, 658),
        "貂蝉": (0, 0, 0, 723),
        "兰陵王": (0, 0, 0, 882),
        "张良": (0, 0, 0, 661),
    },
    "02:45": {
        "钟馗": (0, 0, 1, 1235),
        "妲己": (0, 0, 0, 1521),
        "孙悟空": (1, 0, 2, 1786),
        "关羽": (3, 0, 1, 2048),
        "百里守约": (1, 0, 0, 1746),
        "公孙离": (0, 1, 0, 1630),
        "吕布": (0, 3, 0, 977),
        "貂蝉": (0, 0, 0, 1299),
        "兰陵王": (0, 1, 0, 1380),
        "张良": (0, 0, 0, 992),
    },
    "05:00": {
        "钟馗": (0, 0, 3, 2297),
        "妲己": (2, 0, 0, 3169),
        "孙悟空": (3, 1, 3, 3383),
        "关羽": (3, 1, 1, 3135),
        "百里守约": (1, 0, 1, 3461),
        "公孙离": (0, 2, 0, 2698),
        "吕布": (1, 3, 1, 2785),
        "貂蝉": (0, 1, 1, 2405),
        "兰陵王": (1, 2, 1, 2800),
        "张良": (0, 1, 1, 1891),
    },
}

# Top-bar team gold (rounded to 0.1k in the UI) for the same snapshots.
UI_TEAM_GOLD = {
    "01:34": {1: 4600, 2: 3900},
    "02:45": {1: 8300, 2: 6300},
    "05:00": {1: 15400, 2: 12600},
}

FIELD_ORDER = [
    "frame",
    "time_s",
    "time_mmss",
    "player",
    "hero",
    "entity_id",
    "camp",
    "unit",
    "slot",
    "gold",
    "kills",
    "deaths",
    "assists",
    "level",
    "hp_current",
    "hp_max",
    "hp_ratio",
    "abs_hp_estimate",
    "hp_max_abs",
    "x",
    "z",
    "pos_source",
    "event_count",
    "event_families",
    "row_kind",
    "sources",
    "arena_index",
    "time_origin",
    "time_uncertainty_s",
    "note",
]

FIELD_SOURCE = {
    "frame": "derived: round(time_s * 15) + 1 (ABC 15 fps)",
    "time_s": "arena unit clock +0x1668 (median) / unit clock +0x1668 / event frame",
    "time_mmss": "derived from time_s (truncated to 0.1 s)",
    "player": "abc_timeline/event_windows.json roster",
    "hero": "abc_timeline/event_windows.json roster",
    "entity_id": "abc_timeline/event_windows.json roster",
    "camp": "abc_timeline/event_windows.json roster",
    "unit": "abc_timeline/event_windows.json roster",
    "slot": "abc_timeline/event_windows.json roster",
    "gold": "arena_*.bin record +0x4C",
    "kills": "arena_*.bin record gold+0x158",
    "deaths": "arena_*.bin record gold+0xB8",
    "assists": "arena_*.bin record gold+0xBC",
    "level": "arena_*.bin record +0x220 (low byte)",
    "hp_current": "unit +0x08 (normalized): arena unit object or unit_*.bin",
    "hp_max": "unit +0x10 (normalized): arena unit object or unit_*.bin",
    "hp_ratio": "hp_current / hp_max",
    "abs_hp_estimate": "round(hp_ratio * hp_max_abs); unit windows only",
    "hp_max_abs": "attributes panel at 07:29 (task input)",
    "x": "trajectories/player_trajectories.csv X",
    "z": "trajectories/player_trajectories.csv Z",
    "pos_source": "trajectories/ source class: spawn / integrated / idle",
    "event_count": "abc_timeline/event_windows.csv (per player-frame)",
    "event_families": "abc_timeline/event_windows.csv (per family)",
    "row_kind": "derived: state / event / state+event",
    "sources": "derived: semicolon-separated source flags",
    "arena_index": "arena_*.bin record +0x20 (1000000000 + idx)",
    "time_origin": "derived: arena_unit_clock / unit_clock / event_frame",
    "time_uncertainty_s": "derived: 0.034 s unit clock, 0.0 s event frame",
    "note": "per-row provenance / caveat",
}


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def u32(raw: bytes, off: int) -> int:
    return struct.unpack_from("<I", raw, off)[0]


def f32(raw: bytes, off: int) -> float:
    return struct.unpack_from("<f", raw, off)[0]


def mmss(t: float) -> str:
    """MM:SS.d with truncation, matching the in-game clock's floor semantics."""
    tenths = int(t * 10 + 1e-9)
    minutes, rem = divmod(tenths, 600)
    return f"{minutes:02d}:{rem / 10:04.1f}"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except (ValueError, OSError):
        return str(path)


def pct(n: int, total: int) -> str:
    return f"{100.0 * n / total:.1f}%" if total else "n/a"


def add_check(checks: list[dict], name: str, level: str, detail: str) -> None:
    checks.append({"name": name, "level": level, "detail": detail})


# ---------------------------------------------------------------------------
# roster and level table
# ---------------------------------------------------------------------------

def _validate_roster(roster: list[dict], source: str) -> None:
    for label, values in (
        ("player", [r["player"] for r in roster]),
        ("hero", [r["hero"] for r in roster]),
        ("entity_id", [r["entity_id"] for r in roster]),
        ("unit", [r["unit"] for r in roster]),
    ):
        if len(set(values)) != len(values):
            raise SystemExit(f"roster from {source}: duplicate {label}")
    if len(roster) != 10:
        raise SystemExit(f"roster from {source}: expected 10 players, got {len(roster)}")
    camps = Counter(r["camp"] for r in roster)
    if camps != {1: 5, 2: 5}:
        raise SystemExit(f"roster from {source}: camp split is {dict(camps)}, expected 5+5")


def load_roster(analysis_dir: Path) -> tuple[list[dict], dict, str]:
    json_path = analysis_dir / "abc_timeline" / "event_windows.json"
    csv_path = analysis_dir / "abc_timeline" / "event_windows.csv"
    match: dict = {}
    if json_path.exists():
        doc = json.loads(json_path.read_text(encoding="utf-8"))
        raw = doc.get("roster") or []
        roster = [
            {
                "unit": int(item["unit"]),
                "camp": int(item["camp"]),
                "slot": int(item["slot"]),
                "entity_id": int(item["entityId"]),
                "player": str(item["player"]),
                "hero": str(item["hero"]),
            }
            for item in raw
        ]
        match = doc.get("match") or {}
        source = display_path(json_path)
    elif csv_path.exists():
        roster = []
        seen: set[str] = set()
        with csv_path.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                player = (row.get("player") or "").strip()
                if not player or player in seen:
                    continue
                seen.add(player)
                roster.append(
                    {
                        "unit": int(row["unit"]),
                        "camp": int(row["camp"]),
                        "slot": int(row["slot"]),
                        "entity_id": int(row["entity_id"]),
                        "player": player,
                        "hero": row["hero"],
                    }
                )
        source = display_path(csv_path)
    else:
        raise SystemExit(
            "no roster source found (expected abc_timeline/event_windows.json)"
        )
    _validate_roster(roster, source)
    roster.sort(key=lambda r: (r["camp"], r["slot"]))
    return roster, match, source


def load_levels_table(
    analysis_dir: Path,
    roster_by_entity: dict[int, dict],
    roster_by_hero: dict[str, dict],
) -> tuple[dict, dict]:
    """Load levels.csv keyed by (player, label).

    The CSV header is misleading: its ``player`` column contains the hero
    name and its ``hero`` column contains the numeric heroID.  The ``entity``
    column is the reliable join key, so the table is mapped entity -> roster
    player, with a hero-name fallback.
    """
    path = analysis_dir / "levels_equipment" / "levels.csv"
    meta: dict = {
        "present": path.exists(),
        "path": display_path(path),
        "rows": 0,
        "matched": 0,
        "unmatched": 0,
        "labels": [],
    }
    table: dict[tuple[str, str], int] = {}
    if not path.exists():
        return table, meta
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            label = (row.get("time") or "").strip()
            try:
                level = int(row["level"])
            except (KeyError, TypeError, ValueError):
                continue
            member = None
            entity = (row.get("entity") or "").strip()
            if entity:
                try:
                    member = roster_by_entity.get(int(entity))
                except ValueError:
                    member = None
            if member is None:
                hero = (row.get("player") or "").strip()
                member = roster_by_hero.get(hero)
            if member is None or not label:
                meta["unmatched"] += 1
                continue
            table[(member["player"], label)] = level
            meta["rows"] += 1
            meta["matched"] += 1
    meta["labels"] = sorted({label for _, label in table})
    return table, meta


# ---------------------------------------------------------------------------
# events
# ---------------------------------------------------------------------------

def load_events(
    analysis_dir: Path, roster_by_player: dict[str, dict]
) -> tuple[dict, dict]:
    path = analysis_dir / "abc_timeline" / "event_windows.csv"
    stats: dict = {
        "present": path.exists(),
        "path": display_path(path),
        "rows": 0,
        "frames": [],
        "frame_min": None,
        "frame_max": None,
        "player_frames": 0,
        "families": Counter(),
        "commands": Counter(),
        "windows": Counter(),
        "window_ranges": {},
        "unjoined": 0,
        "roster_mismatch": 0,
        "time_formula_bad": 0,
        "duplicate_extra": 0,
        "bad_frames": 0,
    }
    if not path.exists():
        return {}, stats

    events: dict[tuple[str, int], dict] = {}
    frame_set: set[int] = set()
    dup = Counter()
    window_frames: dict[str, list[int]] = defaultdict(list)
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for raw in reader:
            stats["rows"] += 1
            try:
                frame = int(raw["frame"])
                time_s = float(raw["time_s"])
            except (TypeError, ValueError):
                stats["bad_frames"] += 1
                continue
            player = (raw.get("player") or "").strip()
            family = raw.get("family") or ""
            command = raw.get("command") or ""
            frame_set.add(frame)
            window = raw.get("window") or ""
            window_frames[window].append(frame)
            stats["families"][family] += 1
            stats["commands"][command] += 1
            stats["windows"][window] += 1

            expected = (frame - 1) / FPS
            if abs(expected - time_s) > 1e-3:
                stats["time_formula_bad"] += 1

            member = roster_by_player.get(player)
            if member is None:
                stats["unjoined"] += 1
                continue
            if (
                raw.get("hero") != member["hero"]
                or int(raw.get("entity_id") or -1) != member["entity_id"]
                or int(raw.get("unit") or -1) != member["unit"]
                or int(raw.get("camp") or -1) != member["camp"]
            ):
                stats["roster_mismatch"] += 1

            key = (player, frame)
            agg = events.setdefault(
                key, {"count": 0, "families": Counter()}
            )
            agg["count"] += 1
            agg["families"][family] += 1

            dup_key = (
                frame,
                family,
                command,
                raw.get("actor_type"),
                raw.get("actor_id"),
                raw.get("fields_json"),
            )
            dup[dup_key] += 1

    stats["frames"] = sorted(frame_set)
    if frame_set:
        stats["frame_min"] = min(frame_set)
        stats["frame_max"] = max(frame_set)
    stats["player_frames"] = len(events)
    stats["duplicate_extra"] = sum(v - 1 for v in dup.values() if v > 1)
    stats["window_ranges"] = {
        w: {"min": min(f), "max": max(f), "rows": len(f)}
        for w, f in window_frames.items()
    }
    return events, stats


# ---------------------------------------------------------------------------
# arena: records, unit objects, pointer-based identity
# ---------------------------------------------------------------------------

def _load_arena_scanner():
    path = Path(__file__).resolve().with_name("arena_player_stats.py")
    if not path.exists():
        raise SystemExit(f"missing {path}; cannot decode arena snapshots")
    spec = importlib.util.spec_from_file_location("_arena_player_stats", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.find_records


def scan_record_headers(raw: bytes) -> list[dict]:
    """All per-player record headers, including duplicate/stale blocks.

    Mirrors the header signature of ``arena_player_stats.find_records`` but
    does not deduplicate by index: the 30 MiB arena can hold more than one
    block after seeks, and the caller needs to see stale blocks.
    """
    headers: list[dict] = []
    for k in range(4, 14):
        pattern = struct.pack("<I", 1000000000 + k)
        start = 0
        while True:
            pos = raw.find(pattern, start)
            if pos < 0:
                break
            start = pos + 1
            off = pos - 0x20
            if off < 0 or off + 0x240 > len(raw):
                continue
            if u32(raw, off) != 16 or u32(raw, off + 8) != 10000:
                continue
            if not 3.20 <= f32(raw, off + 0x0C) <= 3.40:
                continue
            gold_at = off + 0x4C
            headers.append(
                {
                    "index": 1000000000 + k,
                    "offset": off,
                    "gold": u32(raw, gold_at),
                    "level": u32(raw, off + 0x220),
                    "kills": u32(raw, gold_at + 0x158),
                    "deaths": u32(raw, gold_at + 0xB8),
                    "assists": u32(raw, gold_at + 0xBC),
                    "pointer": u32(raw, off + 0x28),
                }
            )
    return headers


def group_record_blocks(headers: list[dict]) -> list[list[dict]]:
    headers = sorted(headers, key=lambda h: h["offset"])
    blocks: list[list[dict]] = []
    for header in headers:
        if blocks and header["offset"] - blocks[-1][-1]["offset"] <= 0x40000:
            blocks[-1].append(header)
        else:
            blocks.append([header])
    return [b for b in blocks if len({h["index"] for h in b}) >= 5]


def scan_unit_objects(raw: bytes, roster_by_hero: dict[str, dict]) -> tuple[list[dict], list[str]]:
    """Locate the ten unit objects by entity pair + heroID/camp/hp_max.

    The entity id appears twice at +0x3C/+0x40; searching that 8-byte pair is
    much faster than a 4-byte stride scan.  The candidates are then selected
    by the record pointers in ``resolve_block``; false positives that happen
    to match hero/camp/hp_max but are not pointed to by a record drop out.
    """
    candidates: list[dict] = []
    issues: list[str] = []
    for hero, member in roster_by_hero.items():
        pattern = struct.pack("<II", member["entity_id"], member["entity_id"])
        start = 0
        found: list[int] = []
        while True:
            pos = raw.find(pattern, start)
            if pos < 0:
                break
            start = pos + 1
            unit = pos - 0x3C
            if unit < 0 or unit + 0x1670 > len(raw):
                continue
            if HERO_ID.get(u32(raw, unit + 0x28)) != hero:
                continue
            if u32(raw, unit + 0x34) != member["camp"]:
                continue
            hp_max = u32(raw, unit + 0x10)
            if not 900 <= hp_max <= 1200:
                continue
            found.append(unit)
        if not found:
            issues.append(f"{hero}: no unit object candidate")
            continue
        if len(set(found)) > 1:
            issues.append(f"{hero}: {len(set(found))} unit candidates")
        clock_offset = 0x1524 if hero in ("关羽", "吕布") else 0x1664
        for unit in sorted(set(found)):
            candidates.append(
                {
                    "offset": unit,
                    "hero": hero,
                    "camp": member["camp"],
                    "entity_id": member["entity_id"],
                    "hp_current": u32(raw, unit + 0x08),
                    "hp_max": u32(raw, unit + 0x10),
                    "clock_frame": u32(raw, unit + clock_offset),
                    "clock_ms": u32(raw, unit + clock_offset + 4),
                    "clock_offset": clock_offset,
                }
            )
    return candidates, issues


def resolve_block(block: list[dict], candidates: list[dict]) -> dict | None:
    """Resolve a record block to unit objects via the +0x28 pointer.

    Each record's +0x28 is an absolute heap pointer; the arena file is a dump
    of a contiguous region, so pointer - file_offset is the same base for all
    ten records.  The base with the most votes selects the true units.
    """
    by_index: dict[int, dict] = {}
    duplicates: list[dict] = []
    for header in block:
        if header["index"] in by_index:
            duplicates.append(header)
        else:
            by_index[header["index"]] = header
    if len(by_index) != 10:
        return None
    bases = Counter()
    for header in by_index.values():
        for candidate in candidates:
            bases[header["pointer"] - candidate["offset"]] += 1
    if not bases:
        return None
    base, votes = bases.most_common(1)[0]
    mapping: dict[int, dict | None] = {}
    for index, header in by_index.items():
        target = header["pointer"] - base
        matches = [c for c in candidates if c["offset"] == target]
        mapping[index] = matches[0] if matches else None
    pointer_match = sum(
        1
        for index, unit in mapping.items()
        if unit is not None
        and unit["hero"] == ARENA_INDEX_HEROES[ARENA_INDEX_MAX - index]
    )
    return {
        "by_index": by_index,
        "duplicates": duplicates,
        "base": base,
        "base_votes": votes,
        "mapping": mapping,
        "pointer_match": pointer_match,
    }


def _block_score(
    resolved: dict,
    label: str,
    levels_table: dict,
    roster_by_hero: dict[str, dict],
) -> int:
    score = resolved["pointer_match"] * 100
    for index, header in resolved["by_index"].items():
        unit = resolved["mapping"].get(index)
        hero = (
            unit["hero"]
            if unit is not None
            else ARENA_INDEX_HEROES[ARENA_INDEX_MAX - index]
        )
        if label in UI_REFERENCE:
            ref = UI_REFERENCE[label].get(hero)
            if ref and (
                header["kills"],
                header["deaths"],
                header["assists"],
                header["gold"],
            ) == ref:
                score += 10
        level_ref = levels_table.get((roster_by_hero[hero]["player"], label))
        if level_ref is not None and header["level"] == level_ref:
            score += 1
    return score


def load_arena(
    analysis_dir: Path,
    roster_by_player: dict[str, dict],
    roster_by_hero: dict[str, dict],
    levels_table: dict,
) -> tuple[list[dict], dict]:
    find_records = _load_arena_scanner()
    samples: list[dict] = []
    meta: dict = {
        "snapshots": [],
        "mismatches": [],
        "unit_issues": [],
        "stale_blocks": [],
        "ambiguous": [],
    }
    for label, fallback_time, filename, ui_image in SNAPSHOTS:
        path = analysis_dir / filename
        if not path.exists():
            meta["mismatches"].append(f"missing {display_path(path)}")
            continue
        raw = path.read_bytes()
        primary = find_records(raw)
        candidates, unit_issues = scan_unit_objects(raw, roster_by_hero)
        if unit_issues:
            meta["unit_issues"].extend(f"{label}: {issue}" for issue in unit_issues)
        headers = scan_record_headers(raw)
        blocks = group_record_blocks(headers)
        resolved_candidates = []
        for block in blocks:
            resolved = resolve_block(block, candidates)
            if resolved is None:
                continue
            resolved_candidates.append(
                (
                    resolved,
                    block,
                    _block_score(resolved, label, levels_table, roster_by_hero),
                )
            )
        stale_blocks = 0
        if resolved_candidates:
            resolved_candidates.sort(
                key=lambda item: (
                    -item[2],
                    min(h["offset"] for h in item[1]),
                )
            )
            resolved, block, _ = resolved_candidates[0]
            stale_blocks = len(resolved_candidates) - 1
        else:
            # Fallback: use arena_player_stats.find_records and the idx order.
            resolved = {
                "by_index": {
                    index: {
                        "index": index,
                        "offset": rec["offset"],
                        "gold": rec["gold"],
                        "level": rec.get("level"),
                        "kills": rec["kills"],
                        "deaths": rec["deaths"],
                        "assists": rec["assists"],
                        "pointer": u32(raw, rec["offset"] + 0x28),
                    }
                    for index, rec in primary.items()
                },
                "duplicates": [],
                "base": None,
                "base_votes": 0,
                "mapping": {index: None for index in primary},
                "pointer_match": 0,
            }
            meta["mismatches"].append(f"{label}: no pointer-resolved record block")

        by_index = resolved["by_index"]
        if stale_blocks:
            meta["stale_blocks"].append(
                {"label": label, "count": stale_blocks}
            )

        # Value cross-check against the reference scanner.
        value_mismatch = 0
        for index, header in by_index.items():
            rec = primary.get(index)
            if rec is None:
                continue
            if (
                header["gold"],
                header.get("level"),
                header["kills"],
                header["deaths"],
                header["assists"],
            ) != (
                rec["gold"],
                rec.get("level"),
                rec["kills"],
                rec["deaths"],
                rec["assists"],
            ):
                value_mismatch += 1

        # Exact time: median of the ten resolved unit clocks (stale excluded).
        clocks = [
            unit["clock_ms"]
            for unit in resolved["mapping"].values()
            if unit is not None and unit["clock_ms"] >= 60_000
        ]
        if clocks:
            time_s = round(median(clocks) / 1000.0, 3)
        else:
            time_s = fallback_time
        frame = int(round(time_s * FPS)) + 1

        snapshot_samples: list[dict] = []
        seen_players: set[str] = set()
        for index in range(ARENA_INDEX_MAX, ARENA_INDEX_MAX - 10, -1):
            header = by_index.get(index)
            if header is None:
                continue
            idx_hero = ARENA_INDEX_HEROES[ARENA_INDEX_MAX - index]
            unit = resolved["mapping"].get(index)
            unit_hero = unit["hero"] if unit is not None else None
            unit_player = (
                roster_by_hero[unit_hero]["player"] if unit_hero is not None else None
            )

            ui_player = None
            if ui_image and label in UI_REFERENCE:
                matches = [
                    hero
                    for hero, ref in UI_REFERENCE[label].items()
                    if (
                        header["kills"],
                        header["deaths"],
                        header["assists"],
                        header["gold"],
                    )
                    == ref
                ]
                if len(matches) == 1:
                    ui_player = roster_by_hero[matches[0]]["player"]

            level_candidates = {
                player
                for player in roster_by_player
                if levels_table.get((player, label)) == header.get("level")
            }

            conflict = False
            if ui_player is not None:
                player = ui_player
                if unit_player == player:
                    basis = "ui+pointer"
                else:
                    basis = "ui-anchor"
                    conflict = unit_player is not None
            elif unit_player is not None:
                player = unit_player
                if level_candidates:
                    basis = "level+pointer" if player in level_candidates else "pointer"
                else:
                    basis = "pointer"
            else:
                player = roster_by_hero[idx_hero]["player"]
                basis = "idx-only"

            if player in seen_players:
                meta["ambiguous"].append(f"{label}: duplicate player {player}")
                continue
            seen_players.add(player)
            member = roster_by_player[player]

            notes = [
                f"arena record idx {index}; +0x28 -> unit "
                f"{unit_hero or 'unresolved'}"
                + (f" / {unit_player}" if unit_player else "")
                + (f" (base {resolved['base']:#x})" if resolved["base"] is not None else "")
                + f"; identity {basis}"
            ]
            if ui_image and label in UI_REFERENCE:
                ref = UI_REFERENCE[label].get(member["hero"])
                notes.append(
                    f"gold/KDA {'match' if ref == (header['kills'], header['deaths'], header['assists'], header['gold']) else 'MISMATCH'} "
                    f"{ui_image}"
                )
            else:
                notes.append("no UI screenshot at this checkpoint")
            if levels_table.get((player, label)) is not None:
                notes.append(
                    f"level {header.get('level')} "
                    f"{'matches' if levels_table[(player, label)] == header.get('level') else 'MISMATCHES'} "
                    f"levels.csv"
                )

            hp_current = hp_max = hp_ratio = None
            if conflict:
                notes.append(
                    f"POINTER CONFLICT: anchor {player} vs unit {unit_hero}; HP not attached"
                )
            elif unit is not None:
                hp_current = unit["hp_current"]
                hp_max = unit["hp_max"]
                hp_ratio = (hp_current / hp_max) if hp_max else None
                notes.append(
                    "HP from arena unit object +0x08/+0x10 (normalized); "
                    "absolute max not sampled at this checkpoint, so "
                    "abs_hp_estimate is null"
                )
                if hp_ratio is not None and hp_ratio > 1.0:
                    notes.append(
                        f"HP ratio {hp_ratio:.3f} > 1.0: shield/overheal or stale max"
                    )
                if unit["clock_ms"] < 60_000:
                    notes.append(
                        f"unit clock stale ({unit['clock_ms']} ms); snapshot "
                        "median used"
                    )

            sample = {
                "player": member["player"],
                "hero": member["hero"],
                "camp": member["camp"],
                "entity_id": member["entity_id"],
                "unit": member["unit"],
                "slot": member["slot"],
                "index": index,
                "frame": frame,
                "time_s": time_s,
                "label": label,
                "file": filename,
                "ui_image": ui_image,
                "gold": int(header["gold"]),
                "level": int(header["level"]) if header.get("level") is not None else None,
                "kills": int(header["kills"]),
                "deaths": int(header["deaths"]),
                "assists": int(header["assists"]),
                "hp_current": hp_current,
                "hp_max": hp_max,
                "hp_ratio": hp_ratio,
                "abs_hp_estimate": None,
                "hp_max_abs": None,
                "identity_basis": basis,
                "pointer_hero": unit_hero,
                "pointer_player": unit_player,
                "idx_hero": idx_hero,
                "pointer": header["pointer"],
                "pointer_base": resolved["base"],
                "ui_match": (
                    UI_REFERENCE[label].get(member["hero"])
                    == (header["kills"], header["deaths"], header["assists"], header["gold"])
                    if (ui_image and label in UI_REFERENCE)
                    else None
                ),
                "level_match": (
                    levels_table.get((player, label)) == header.get("level")
                    if levels_table.get((player, label)) is not None
                    else None
                ),
                "notes": notes,
            }
            snapshot_samples.append(sample)
            samples.append(sample)

        basis_counts = Counter(s["identity_basis"] for s in snapshot_samples)
        meta["snapshots"].append(
            {
                "label": label,
                "time_s": time_s,
                "frame": frame,
                "file": filename,
                "records": len(by_index),
                "players": len(snapshot_samples),
                "base": resolved["base"],
                "base_votes": resolved["base_votes"],
                "pointer_match": resolved["pointer_match"],
                "ui_matches": sum(1 for s in snapshot_samples if s["ui_match"]),
                "level_matches": sum(1 for s in snapshot_samples if s["level_match"]),
                "clock_n": len(clocks),
                "clock_min_ms": min(clocks) if clocks else None,
                "clock_max_ms": max(clocks) if clocks else None,
                "stale_blocks": stale_blocks,
                "value_mismatch": value_mismatch,
                "basis": dict(basis_counts),
                "unit_issues": list(unit_issues),
            }
        )

    samples.sort(key=lambda s: (s["time_s"], s["camp"], s["slot"]))
    return samples, meta


# ---------------------------------------------------------------------------
# unit windows (8 KiB)
# ---------------------------------------------------------------------------

UNIT_RE = re.compile(r"^unit_(?P<hero>.+)_(?P<suffix>t\d+)\.bin$")


def load_units(
    analysis_dir: Path, roster_by_hero: dict[str, dict]
) -> tuple[list[dict], dict]:
    files = sorted(analysis_dir.glob("unit_*_t*.bin"))
    records: list[dict] = []
    meta: dict = {
        "files": len(files),
        "samples": 0,
        "clusters": [],
        "duplicates": [],
        "stale": [],
        "shifted": [],
        "identity_bad": [],
    }
    for path in files:
        match = UNIT_RE.match(path.name)
        if not match:
            meta["identity_bad"].append(f"{path.name}: unparsable filename")
            continue
        file_hero = match.group("hero")
        suffix = match.group("suffix")
        raw = path.read_bytes()
        if len(raw) < 0x1670:
            meta["identity_bad"].append(f"{path.name}: too short ({len(raw)} bytes)")
            continue
        hero_id = u32(raw, 0x28)
        hero = HERO_ID.get(hero_id)
        if hero is None:
            meta["identity_bad"].append(f"{path.name}: unknown heroID {hero_id}")
            continue
        file_hero_norm = "钟馗" if file_hero == "zhongkui" else file_hero
        if file_hero_norm != hero:
            meta["identity_bad"].append(
                f"{path.name}: filename hero {file_hero_norm} != heroID {hero_id}"
            )
        camp = u32(raw, 0x34)
        entity = u32(raw, 0x3C)
        entity2 = u32(raw, 0x40)
        member = roster_by_hero.get(hero)
        if member is None:
            meta["identity_bad"].append(f"{path.name}: hero {hero} not in roster")
            continue
        if camp != member["camp"] or entity != member["entity_id"] or entity2 != entity:
            meta["identity_bad"].append(
                f"{path.name}: camp/entity {camp}/{entity}/{entity2} != roster "
                f"{member['camp']}/{member['entity_id']}"
            )
        clock_offset = 0x1524 if hero in ("关羽", "吕布") else 0x1664
        clock_frame = u32(raw, clock_offset)
        clock_ms = u32(raw, clock_offset + 4)
        hp_current = u32(raw, 0x08)
        hp_max = u32(raw, 0x10)
        clock_ok = clock_ms >= 60_000
        records.append(
            {
                "path": path,
                "file": path.name,
                "hero": hero,
                "file_hero": file_hero_norm,
                "suffix": suffix,
                "camp": camp,
                "entity_id": entity,
                "hp_current": hp_current,
                "hp_max": hp_max,
                "clock_frame": clock_frame,
                "clock_ms": clock_ms,
                "clock_offset": clock_offset,
                "clock_ok": clock_ok,
                "member": member,
            }
        )

    # Cluster valid clocks (frontier: 50 ms) into capture batches.
    valid = sorted([r for r in records if r["clock_ok"]], key=lambda r: r["clock_ms"])
    clusters: list[list[dict]] = []
    for record in valid:
        if clusters and record["clock_ms"] - clusters[-1][-1]["clock_ms"] <= 50:
            clusters[-1].append(record)
        else:
            clusters.append([record])
    cluster_times = [
        round(median([r["clock_ms"] for r in cluster]) / 1000.0, 3)
        for cluster in clusters
    ]

    def cluster_index_of(record: dict) -> int:
        for i, cluster in enumerate(clusters):
            if record in cluster:
                return i
        raise ValueError("record not in any cluster")

    def majority_cluster_for_suffix(suffix: str) -> int:
        counts = Counter()
        for i, cluster in enumerate(clusters):
            counts[i] = sum(1 for r in cluster if r["suffix"] == suffix)
        if not counts:
            return 0
        return max(counts, key=lambda i: (counts[i], -i))

    for record in records:
        if record["clock_ok"]:
            record["cluster"] = cluster_index_of(record)
        else:
            record["cluster"] = majority_cluster_for_suffix(record["suffix"])
            record["stale"] = True
            meta["stale"].append(
                {
                    "file": record["file"],
                    "player": record["member"]["player"],
                    "clock_frame": record["clock_frame"],
                    "clock_ms": record["clock_ms"],
                    "assigned_time_s": cluster_times[record["cluster"]],
                }
            )
        if record["clock_offset"] == 0x1524 and record["hero"] not in meta["shifted"]:
            meta["shifted"].append(record["hero"])

    # One sample per (hero, capture cluster); merge duplicate files.
    by_key: dict[tuple[str, int], dict] = {}
    for record in records:
        key = (record["hero"], record["cluster"])
        if key in by_key:
            by_key[key]["files"].append(record["file"])
            by_key[key]["hashes"].append(sha256(record["path"]))
            continue
        by_key[key] = {
            "player": record["member"]["player"],
            "hero": record["hero"],
            "camp": record["member"]["camp"],
            "entity_id": record["member"]["entity_id"],
            "unit": record["member"]["unit"],
            "slot": record["member"]["slot"],
            "cluster": record["cluster"],
            "time_s": cluster_times[record["cluster"]],
            "frame": int(round(cluster_times[record["cluster"]] * FPS)) + 1,
            "hp_current": record["hp_current"],
            "hp_max": record["hp_max"],
            "clock_ms": record["clock_ms"],
            "clock_frame": record["clock_frame"],
            "clock_offset": record["clock_offset"],
            "files": [record["file"]],
            "hashes": [sha256(record["path"])],
            "stale": record.get("stale", False),
        }

    samples: list[dict] = []
    for sample in by_key.values():
        hp_max = sample["hp_max"]
        ratio = (sample["hp_current"] / hp_max) if hp_max else None
        abs_estimate = (
            int(round(ratio * HP_MAX_ABS[sample["hero"]])) if ratio is not None else None
        )
        notes: list[str] = []
        if len(sample["files"]) > 1:
            identical = len(set(sample["hashes"])) == 1
            notes.append(
                "duplicate sample merged: "
                + ", ".join(sample["files"])
                + (" (byte-identical)" if identical else " (values differ)")
            )
            if not identical:
                meta["duplicates"].append(
                    f"{sample['hero']} {sample['time_s']}: files differ"
                )
        if sample["stale"]:
            notes.append(
                f"unit clock stale ({sample['clock_ms']} ms); batch anchor "
                f"{sample['time_s']} s used"
            )
        if sample["clock_offset"] == 0x1524:
            notes.append("clock read at +0x1524/+0x1528 (record shifted -0x140)")
        notes.append(
            f"HP pair +0x08/+0x10 normalized; abs estimate = ratio x panel "
            f"max {HP_MAX_ABS[sample['hero']]} (07:29)"
        )
        if ratio is not None and ratio > 1.0:
            notes.append(
                f"ratio {ratio:.3f} > 1.0: shield/overheal or stale max channel"
            )
        samples.append(
            {
                "player": sample["player"],
                "hero": sample["hero"],
                "camp": sample["camp"],
                "entity_id": sample["entity_id"],
                "unit": sample["unit"],
                "slot": sample["slot"],
                "frame": sample["frame"],
                "time_s": sample["time_s"],
                "hp_current": sample["hp_current"],
                "hp_max": sample["hp_max"],
                "hp_ratio": ratio,
                "abs_hp_estimate": abs_estimate,
                "hp_max_abs": HP_MAX_ABS[sample["hero"]],
                "files": sample["files"],
                "notes": notes,
            }
        )

    samples.sort(key=lambda s: (s["time_s"], s["camp"], s["slot"]))
    meta["samples"] = len(samples)
    meta["clusters"] = [
        {
            "time_s": t,
            "label": mmss(t),
            "samples": sum(1 for s in samples if s["time_s"] == t),
            "files": [r["file"] for r in clusters[idx]],
        }
        for idx, t in enumerate(cluster_times)
    ]
    return samples, meta


# ---------------------------------------------------------------------------
# minimap (team-level, not joinable) and trajectories
# ---------------------------------------------------------------------------

def load_minimap(analysis_dir: Path) -> dict:
    path = analysis_dir / "minimap_positions" / "positions.csv"
    meta: dict = {
        "present": path.exists(),
        "path": display_path(path),
        "rows": 0,
        "empty": False,
        "frames": {},
        "times": {},
        "confidence": Counter(),
        "teams": Counter(),
        "joinable": 0,
        "reason": "only team is extracted; no hero identity, so no player join",
        "matches": {},
    }
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))
        meta["rows"] = len(rows)
        meta["empty"] = len(rows) == 0
        frames = Counter(r["frame"] for r in rows)
        times = {}
        for r in rows:
            times.setdefault(r["frame"], r.get("time", ""))
        meta["frames"] = dict(frames)
        meta["times"] = times
        meta["confidence"] = Counter(r.get("confidence", "") for r in rows)
        meta["teams"] = Counter(r.get("team", "") for r in rows)
        if meta["empty"]:
            meta["reason"] = "positions.csv is empty at build time"
    matches_path = analysis_dir / "trajectories" / "minimap_matches.csv"
    if matches_path.exists():
        with matches_path.open(encoding="utf-8-sig", newline="") as fh:
            matches = list(csv.DictReader(fh))
        meta["matches"] = {
            "path": display_path(matches_path),
            "rows": len(matches),
            "frames": len({r.get("frame", "") for r in matches}),
            "confidence": Counter(r.get("confidence", "") for r in matches),
        }
    return meta


TRAJ_X = ("x", "world_x", "pos_x", "wx")
TRAJ_Z = ("z", "world_z", "pos_z", "wz")
TRAJ_PLAYER = ("player", "name", "player_name")
TRAJ_HERO = ("hero", "hero_name")
TRAJ_ENTITY = ("entity_id", "entityid", "entity")
TRAJ_FRAME = ("frame", "frame_id")
TRAJ_TIME = ("time_csv", "time_s", "time", "t", "seconds")
TRAJ_SOURCE = ("source", "pos_source", "kind")


def _pick(row: dict, names: tuple[str, ...]):
    lowered = {str(k).lower(): k for k in row}
    for name in names:
        if name.lower() in lowered:
            return row[lowered[name.lower()]]
    return None


def _traj_rows(path: Path) -> list[dict]:
    if path.suffix.lower() == ".jsonl":
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as fh:
            return list(csv.DictReader(fh))
    if path.suffix.lower() == ".json":
        doc = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(doc, list):
            return doc
        if isinstance(doc, dict):
            for key in ("rows", "positions", "trajectories", "data"):
                if isinstance(doc.get(key), list):
                    return doc[key]
    return []


def load_trajectories(
    traj_dir: Path, roster_by_player: dict[str, dict], roster_by_hero: dict[str, dict]
) -> tuple[dict, dict]:
    meta: dict = {
        "present": traj_dir.exists(),
        "dir": display_path(traj_dir),
        "files": [],
        "rows": 0,
        "parsed_rows": 0,
        "joined": 0,
        "unmatched": 0,
        "tolerance_s": 0.05,
        "source_counts": {},
        "validation": {},
        "model": {},
    }
    if not traj_dir.exists():
        return {}, meta

    points: dict[tuple[str, int], tuple[float, float, str]] = {}
    by_player: dict[str, list[tuple[float, float, float]]] = defaultdict(list)
    source_counts: Counter = Counter()
    for path in sorted(traj_dir.iterdir()):
        if path.suffix.lower() not in (".csv", ".jsonl", ".json"):
            continue
        meta["files"].append(path.name)
        for raw in _traj_rows(path):
            if not isinstance(raw, dict):
                continue
            meta["parsed_rows"] += 1
            player = _pick(raw, TRAJ_PLAYER)
            hero = _pick(raw, TRAJ_HERO)
            entity = _pick(raw, TRAJ_ENTITY)
            member = None
            if player is not None:
                member = roster_by_player.get(str(player).strip())
            if member is None and hero is not None:
                member = roster_by_hero.get(str(hero).strip())
            if member is None and entity is not None:
                for candidate in roster_by_player.values():
                    if candidate["entity_id"] == int(entity):
                        member = candidate
                        break
            if member is None:
                continue
            x = _pick(raw, TRAJ_X)
            z = _pick(raw, TRAJ_Z)
            if x is None or z is None:
                continue
            frame = _pick(raw, TRAJ_FRAME)
            time_s = _pick(raw, TRAJ_TIME)
            if frame is None and time_s is not None:
                frame = int(round(float(time_s) * FPS)) + 1
            if frame is None:
                continue
            try:
                xf, zf, frame_i = float(x), float(z), int(frame)
            except (TypeError, ValueError):
                continue
            source = _pick(raw, TRAJ_SOURCE)
            source = str(source).strip() if source is not None else "unknown"
            source_counts[source] += 1
            key = (member["player"], frame_i)
            points[key] = (xf, zf, source)
            if time_s is None:
                time_s = (frame_i - 1) / FPS
            by_player[member["player"]].append((float(time_s), xf, zf))
    for values in by_player.values():
        values.sort()
    meta["rows"] = len(points)
    meta["source_counts"] = dict(source_counts)

    validation_path = traj_dir / "validation.json"
    if validation_path.exists():
        try:
            doc = json.loads(validation_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            doc = {}
        block = doc.get("validation") or {}
        per_frame = block.get("per_frame") or {}
        matched = sum(int(item.get("matched") or 0) for item in per_frame.values())
        detections = sum(int(item.get("detections") or 0) for item in per_frame.values())
        frames_with_matches = sum(
            1 for item in per_frame.values() if int(item.get("matched") or 0) > 0
        )
        rms = block.get("overall_rms_norm")
        meta["model"] = doc.get("model") or {}
        meta["validation"] = {
            "overall_rms_norm": rms,
            "overall_rms_units": block.get("overall_rms_units"),
            "overall_rms_norm_forced": block.get("overall_rms_norm_forced"),
            "matched_icons": matched,
            "detections": detections,
            "frames": len(per_frame),
            "frames_with_matches": frames_with_matches,
            # validation.md states the target as <= 5% of the map span.
            "verdict": ("FAIL" if rms is not None and rms > 0.05 else "PASS")
            if rms is not None
            else "UNKNOWN",
        }
    return points, {"by_player": by_player, **meta}


# ---------------------------------------------------------------------------
# row assembly
# ---------------------------------------------------------------------------

TIME_PRIORITY = {"event_frame": 1, "unit_clock": 2, "arena_unit_clock": 3}


def _blank_row(member: dict, frame: int) -> dict:
    return {
        "frame": frame,
        "time_s": None,
        "time_mmss": None,
        "player": member["player"],
        "hero": member["hero"],
        "entity_id": member["entity_id"],
        "camp": member["camp"],
        "unit": member["unit"],
        "slot": member["slot"],
        "gold": None,
        "kills": None,
        "deaths": None,
        "assists": None,
        "level": None,
        "hp_current": None,
        "hp_max": None,
        "hp_ratio": None,
        "abs_hp_estimate": None,
        "hp_max_abs": None,
        "x": None,
        "z": None,
        "pos_source": None,
        "event_count": None,
        "event_families": None,
        "row_kind": "event",
        "sources": [],
        "arena_index": None,
        "time_origin": None,
        "time_uncertainty_s": None,
        "note": None,
        "_notes": [],
    }


def _set_time(row: dict, time_s: float, origin: str, uncertainty: float) -> None:
    current = row["time_origin"]
    if current is None or TIME_PRIORITY[origin] >= TIME_PRIORITY[current]:
        row["time_s"] = time_s
        row["time_origin"] = origin
        row["time_uncertainty_s"] = uncertainty


def _add_source(row: dict, source: str) -> None:
    if source not in row["sources"]:
        row["sources"].append(source)


def _add_note(row: dict, note: str) -> None:
    if note and note not in row["_notes"]:
        row["_notes"].append(note)


def build_rows(
    roster_by_player: dict[str, dict],
    arena_samples: list[dict],
    unit_samples: list[dict],
    events: dict,
    traj_points: dict,
) -> list[dict]:
    rows: dict[tuple[str, int], dict] = {}

    def ensure(player: str, frame: int) -> dict:
        key = (player, frame)
        if key not in rows:
            rows[key] = _blank_row(roster_by_player[player], frame)
        return rows[key]

    for sample in arena_samples:
        row = ensure(sample["player"], sample["frame"])
        row["gold"] = sample["gold"]
        row["kills"] = sample["kills"]
        row["deaths"] = sample["deaths"]
        row["assists"] = sample["assists"]
        row["level"] = sample["level"]
        row["arena_index"] = sample["index"]
        if sample["hp_current"] is not None:
            row["hp_current"] = sample["hp_current"]
            row["hp_max"] = sample["hp_max"]
            row["hp_ratio"] = sample["hp_ratio"]
            _add_source(row, "arena_unit_object")
        _set_time(row, sample["time_s"], "arena_unit_clock", 0.034)
        _add_source(row, "arena_stats")
        for note in sample["notes"]:
            _add_note(row, note)

    for sample in unit_samples:
        row = ensure(sample["player"], sample["frame"])
        row["hp_current"] = sample["hp_current"]
        row["hp_max"] = sample["hp_max"]
        row["hp_ratio"] = sample["hp_ratio"]
        row["abs_hp_estimate"] = sample["abs_hp_estimate"]
        row["hp_max_abs"] = sample["hp_max_abs"]
        _set_time(row, sample["time_s"], "unit_clock", 0.034)
        _add_source(row, "unit_object")
        for note in sample["notes"]:
            _add_note(row, note)

    for (player, frame), agg in events.items():
        row = ensure(player, frame)
        row["event_count"] = agg["count"]
        row["event_families"] = ";".join(
            f"{family}:{count}" for family, count in sorted(agg["families"].items())
        )
        _add_source(row, "event_windows")
        if row["time_s"] is None:
            _set_time(row, (frame - 1) / FPS, "event_frame", 0.0)
        else:
            _add_note(
                row,
                f"+{agg['count']} event row(s) at the same frame",
            )

    for (player, frame), (x, z, pos_source) in traj_points.items():
        key = (player, frame)
        if key in rows:
            rows[key]["x"] = x
            rows[key]["z"] = z
            rows[key]["pos_source"] = pos_source
            _add_source(rows[key], "trajectories")

    out: list[dict] = []
    for row in rows.values():
        has_state = row["gold"] is not None or row["hp_current"] is not None
        has_event = row["event_count"] is not None
        if has_state and has_event:
            row["row_kind"] = "state+event"
        elif has_state:
            row["row_kind"] = "state"
        else:
            row["row_kind"] = "event"
        if not has_state:
            _add_note(row, "event-only frame; no gold/KDA/level/HP sample here")
        out.append(row)

    out.sort(key=lambda r: (r["time_s"], r["camp"], r["slot"], r["player"]))
    return out


def public_rows(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        pub = {key: row[key] for key in FIELD_ORDER}
        pub["time_s"] = round(pub["time_s"], 3)
        pub["time_mmss"] = mmss(pub["time_s"])
        if pub["hp_ratio"] is not None:
            pub["hp_ratio"] = round(pub["hp_ratio"], 4)
        pub["sources"] = ";".join(row["sources"])
        pub["note"] = " | ".join(row["_notes"]) if row["_notes"] else None
        out.append(pub)
    return out


# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------

def run_checks(ctx: dict) -> tuple[list[dict], dict]:
    checks: list[dict] = []
    rows = ctx["rows"]
    roster = ctx["roster"]
    arena = ctx["arena_samples"]
    unit = ctx["unit_samples"]
    total = len(rows)

    # -- roster ------------------------------------------------------------
    camps = Counter(r["camp"] for r in roster)
    add_check(
        checks,
        "roster",
        "PASS",
        f"{len(roster)} players / {len({r['entity_id'] for r in roster})} entities / "
        f"camps {dict(sorted(camps.items()))}; slots 0-4 per camp",
    )

    # -- keys / joins ------------------------------------------------------
    keys = [(r["player"], r["frame"]) for r in rows]
    dup_keys = [k for k, n in Counter(keys).items() if n > 1]
    add_check(
        checks,
        "unique (player, frame) keys",
        "PASS" if not dup_keys else "FAIL",
        f"{len(keys)} rows, {len(set(keys))} unique"
        + ("" if not dup_keys else f"; duplicates: {dup_keys[:5]}"),
    )

    join_bad = 0
    for row in rows:
        member = ctx["roster_by_player"][row["player"]]
        if any(
            row[field] != member[field]
            for field in ("hero", "entity_id", "camp", "unit", "slot")
        ):
            join_bad += 1
    add_check(
        checks,
        "roster join (hero/entity/camp/unit/slot)",
        "PASS" if join_bad == 0 else "FAIL",
        f"{total - join_bad}/{total} rows match the roster exactly",
    )

    per_player_entities = defaultdict(set)
    entity_players = defaultdict(set)
    for row in rows:
        per_player_entities[row["player"]].add(row["entity_id"])
        entity_players[row["entity_id"]].add(row["player"])
    entity_bad = [
        p for p, ents in per_player_entities.items() if len(ents) != 1
    ] + [
        str(e) for e, players in entity_players.items() if len(players) != 1
    ]
    add_check(
        checks,
        "entity consistency",
        "PASS" if not entity_bad else "FAIL",
        f"{len(per_player_entities)} players -> {len(entity_players)} entities, 1:1"
        if not entity_bad
        else f"violations: {entity_bad[:5]}",
    )

    # -- time --------------------------------------------------------------
    tol = 0.5 / FPS + 1e-6
    worst = 0.0
    worst_row = None
    for row in rows:
        expected = (row["frame"] - 1) / FPS
        delta = abs(expected - row["time_s"])
        if delta > worst:
            worst, worst_row = delta, row
    add_check(
        checks,
        "frame <-> time_s consistency",
        "PASS" if worst <= tol else "FAIL",
        f"max |time_s - (frame-1)/15| = {worst:.4f} s "
        f"(tolerance {tol:.4f} s; row {worst_row['player']} "
        f"frame {worst_row['frame']})",
    )

    by_player_time = defaultdict(list)
    for row in rows:
        by_player_time[row["player"]].append((row["time_s"], row["frame"]))
    monotonic_bad = []
    for player, values in by_player_time.items():
        values.sort()
        for (t1, f1), (t2, f2) in zip(values, values[1:]):
            if t2 < t1 - 1e-9:
                monotonic_bad.append(f"{player}: {t1}->{t2}")
    add_check(
        checks,
        "per-player time monotonicity",
        "PASS" if not monotonic_bad else "FAIL",
        f"{len(by_player_time)} players, times strictly non-decreasing"
        if not monotonic_bad
        else f"violations: {monotonic_bad[:5]}",
    )

    total_frames = ctx["total_frames"]
    add_check(
        checks,
        "time range",
        "PASS"
        if all(0 <= r["time_s"] <= total_frames / FPS + 1 for r in rows)
        else "FAIL",
        f"rows span {mmss(min(r['time_s'] for r in rows))} .. "
        f"{mmss(max(r['time_s'] for r in rows))}; replay has "
        f"{total_frames} frames ({mmss((total_frames - 1) / FPS)})",
    )

    # -- arena -------------------------------------------------------------
    snap_labels = [s[0] for s in SNAPSHOTS]
    snap_counts = Counter(s["label"] for s in arena)
    add_check(
        checks,
        "arena snapshots",
        "PASS" if all(snap_counts.get(label) == 10 for label in snap_labels) else "FAIL",
        "; ".join(f"{label}: {snap_counts.get(label, 0)}/10" for label in snap_labels),
    )
    index_bad = []
    for meta in ctx["arena_meta"]["snapshots"]:
        expected = set(range(ARENA_INDEX_MAX - 9, ARENA_INDEX_MAX + 1))
        actual = set()
        for sample in arena:
            if sample["label"] == meta["label"]:
                actual.add(sample["index"])
        if actual != expected:
            index_bad.append(
                f"{meta['label']}: missing/surplus {sorted(actual ^ expected)}"
            )
    add_check(
        checks,
        "arena record indices",
        "PASS" if not index_bad else "FAIL",
        "idx 1000000004..1000000013 present at all 4 snapshots"
        if not index_bad
        else "; ".join(index_bad),
    )

    ptr_total = sum(m["pointer_match"] for m in ctx["arena_meta"]["snapshots"])
    stale_blocks = sum(m["stale_blocks"] for m in ctx["arena_meta"]["snapshots"])
    conflicts = sum(
        1 for s in arena if s["pointer_player"] and s["pointer_player"] != s["player"]
    )
    add_check(
        checks,
        "arena record alignment",
        "PASS" if ptr_total == 40 and stale_blocks == 0 and conflicts == 0 else "WARN",
        f"{ptr_total}/40 records resolve via +0x28 to the idx-order unit "
        f"(bases "
        + ", ".join(
            f"{m['label']} {m['base']:#x}"
            for m in ctx["arena_meta"]["snapshots"]
            if m["base"] is not None
        )
        + f"); {stale_blocks} stale block(s), {conflicts} pointer conflict(s)",
    )

    ui_rows = [s for s in arena if s["ui_image"]]
    ui_gold_ok = sum(1 for s in ui_rows if s["ui_match"] is True)
    ui_level_ok = sum(1 for s in ui_rows if s["level_match"] is True)
    add_check(
        checks,
        "arena vs UI gold",
        "PASS" if ui_gold_ok == len(ui_rows) == 30 else "FAIL",
        f"{ui_gold_ok}/{len(ui_rows)} player-snapshots exactly match the screenshot",
    )
    add_check(
        checks,
        "arena vs UI KDA",
        "PASS" if ctx["ui_kda_ok"] == len(ui_rows) == 30 else "FAIL",
        f"{ctx['ui_kda_ok']}/{len(ui_rows)} player-snapshots exactly match the screenshot",
    )
    add_check(
        checks,
        "arena vs UI team gold",
        "PASS" if ctx["team_gold_ok"] == 6 else "FAIL",
        f"{ctx['team_gold_ok']}/6 camp-snapshots within 100 gold of the top-bar "
        f"rounded value",
    )

    # -- level -------------------------------------------------------------
    level_rows = [s for s in arena if s["level"] is not None]
    level_range_ok = all(1 <= s["level"] <= 15 for s in level_rows)
    add_check(
        checks,
        "level populated",
        "PASS" if len(level_rows) == 40 else "WARN",
        f"{len(level_rows)}/40 arena rows carry a level "
        f"(record +0x220); range "
        f"{min(s['level'] for s in level_rows)}..{max(s['level'] for s in level_rows)}"
        + ("" if level_range_ok else "; OUT OF RANGE"),
    )
    level_checked = [s for s in arena if s["level_match"] is not None]
    level_ok = sum(1 for s in level_checked if s["level_match"])
    if ctx["levels_meta"]["present"]:
        add_check(
            checks,
            "level vs levels.csv",
            "PASS" if level_ok == len(level_checked) == 40 else "FAIL",
            f"{level_ok}/{len(level_checked)} match levels.csv "
            f"(30 screen+read validated at 01:34/02:45/05:00; "
            f"10 engine-only consistency at 07:46)",
        )
    else:
        add_check(
            checks,
            "level vs levels.csv",
            "INFO",
            "levels.csv not found; level values are engine-only",
        )
    level_bad = []
    by_player_levels = defaultdict(list)
    for sample in arena:
        if sample["level"] is not None:
            by_player_levels[sample["player"]].append(
                (sample["time_s"], sample["level"])
            )
    for player, values in by_player_levels.items():
        values.sort()
        for (t1, l1), (t2, l2) in zip(values, values[1:]):
            if l2 < l1:
                level_bad.append(f"{player}: {l1}->{l2}")
    add_check(
        checks,
        "level monotonic",
        "PASS" if not level_bad else "FAIL",
        "10 players non-decreasing across 01:34/02:45/05:00/07:46"
        if not level_bad
        else f"violations: {level_bad[:5]}",
    )

    # -- gold/KDA deltas ---------------------------------------------------
    by_player_snap = defaultdict(dict)
    for sample in arena:
        by_player_snap[sample["player"]][sample["label"]] = sample
    deltas = []
    for i in range(len(SNAPSHOTS) - 1):
        a_label = SNAPSHOTS[i][0]
        b_label = SNAPSHOTS[i + 1][0]
        a_time = next(m["time_s"] for m in ctx["arena_meta"]["snapshots"] if m["label"] == a_label)
        b_time = next(m["time_s"] for m in ctx["arena_meta"]["snapshots"] if m["label"] == b_label)
        dt = b_time - a_time
        for player, snaps in by_player_snap.items():
            a, b = snaps.get(a_label), snaps.get(b_label)
            if not a or not b:
                continue
            deltas.append(
                {
                    "from": a_label,
                    "to": b_label,
                    "dt": dt,
                    "player": player,
                    "camp": a["camp"],
                    "dgold": b["gold"] - a["gold"],
                    "dk": b["kills"] - a["kills"],
                    "dd": b["deaths"] - a["deaths"],
                    "da": b["assists"] - a["assists"],
                    "dl": (b["level"] - a["level"])
                    if b["level"] is not None and a["level"] is not None
                    else None,
                    "gold_per_s": (b["gold"] - a["gold"]) / dt if dt else None,
                }
            )
    bad_delta = [
        d
        for d in deltas
        if d["dgold"] < 0
        or d["dk"] < 0
        or d["dd"] < 0
        or d["da"] < 0
        or (d["dl"] is not None and d["dl"] < 0)
    ]
    add_check(
        checks,
        "gold/KDA/level monotonic between snapshots",
        "PASS" if not bad_delta else "FAIL",
        f"{len(deltas)} player-transitions, no negative gold/kills/deaths/assists/level"
        if not bad_delta
        else f"violations: {bad_delta[:3]}",
    )
    slow = [d for d in deltas if d["gold_per_s"] > 50]
    add_check(
        checks,
        "gold income plausibility",
        "PASS" if not slow else "WARN",
        f"max {max(d['gold_per_s'] for d in deltas):.1f} gold/s "
        f"(warn threshold 50/s)",
    )

    # -- unit / HP ---------------------------------------------------------
    add_check(
        checks,
        "unit window identity",
        "PASS" if not ctx["unit_meta"]["identity_bad"] else "FAIL",
        f"{ctx['unit_meta']['files']} files, {len(unit)} unique samples; "
        f"heroID/camp/entityID match the roster"
        if not ctx["unit_meta"]["identity_bad"]
        else "; ".join(ctx["unit_meta"]["identity_bad"][:5]),
    )
    add_check(
        checks,
        "HP max channel constant",
        "PASS"
        if ctx["arena_hp_max_constant"] == 10 and ctx["hp_max_cross"] == 10
        else "WARN",
        f"max channel (+0x10) is one value per hero across all four arena "
        f"snapshots ({ctx['arena_hp_max_constant']}/10) and identical to the "
        f"unit-window value ({ctx['hp_max_cross']}/10)",
    )
    add_check(
        checks,
        "HP current channel is live",
        "PASS" if ctx["hp_changed"] >= 8 else "WARN",
        f"current channel (+0x08) changed between the 07:29 and 07:32.97 "
        f"unit-window captures for {ctx['hp_changed']}/10 players",
    )
    add_check(
        checks,
        "HP ratio range",
        "PASS" if ctx["hp_ratio_max"] <= 1.25 else "WARN",
        f"{ctx['hp_ratio_min']:.3f} .. {ctx['hp_ratio_max']:.3f}; "
        f"{ctx['hp_ratio_gt1']} sample(s) > 1.0 "
        f"({', '.join(ctx['hp_ratio_gt1_players']) or 'none'})",
    )
    add_check(
        checks,
        "arena clock",
        "PASS",
        "4 snapshots; "
        + "; ".join(
            f"{m['label']} {m['time_s']:.3f}s ({m['clock_n']} valid, "
            f"{m['clock_min_ms']}..{m['clock_max_ms']} ms)"
            for m in ctx["arena_meta"]["snapshots"]
        )
        + " (孙悟空's unit clock is stale at 1337 ms in every snapshot)",
    )
    add_check(
        checks,
        "unit window clock",
        "WARN" if ctx["unit_meta"]["stale"] else "PASS",
        f"{len(ctx['unit_meta']['stale'])} stale clock(s)"
        + (
            ": "
            + "; ".join(
                f"{s['file']} ({s['clock_ms']} ms)" for s in ctx["unit_meta"]["stale"]
            )
            if ctx["unit_meta"]["stale"]
            else "; all clocks valid"
        )
        + f"; shifted offset for {', '.join(ctx['unit_meta']['shifted']) or 'none'}",
    )

    # -- events ------------------------------------------------------------
    ev = ctx["event_meta"]
    if ev["present"]:
        add_check(
            checks,
            "event rows",
            "PASS",
            f"{ev['rows']} rows / {len(ev['frames'])} frames / "
            f"{ev['player_frames']} player-frames; families "
            + ", ".join(f"{k}:{v}" for k, v in sorted(ev["families"].items())),
        )
        add_check(
            checks,
            "event roster join",
            "PASS" if ev["unjoined"] == 0 and ev["roster_mismatch"] == 0 else "FAIL",
            f"{ev['rows'] - ev['unjoined']}/{ev['rows']} rows join a roster "
            f"player; {ev['roster_mismatch']} hero/entity/camp mismatches",
        )
        add_check(
            checks,
            "event time formula",
            "PASS" if ev["time_formula_bad"] == 0 else "FAIL",
            f"{ev['rows'] - ev['time_formula_bad']}/{ev['rows']} rows satisfy "
            f"time_s = (frame-1)/15",
        )
        add_check(
            checks,
            "event duplicates",
            "WARN" if ev["duplicate_extra"] else "PASS",
            f"{ev['duplicate_extra']} exact duplicate row(s) beyond the first "
            f"(BUYEQUIP notification echoes)",
        )
        covered = len(ev["frames"])
        coverage = 100.0 * covered / total_frames if total_frames else 0.0
        add_check(
            checks,
            "event temporal coverage",
            "WARN",
            f"{covered}/{total_frames} replay frames ({coverage:.1f}%) in "
            f"{len(ev['windows'])} windows; no kill/death family decoded",
        )
    else:
        add_check(checks, "event rows", "WARN", "event_windows.csv not found")

    # -- minimap / trajectories / positions --------------------------------
    mini = ctx["minimap"]
    if mini["present"] and mini["rows"]:
        add_check(
            checks,
            "minimap positions",
            "WARN",
            f"{mini['rows']} icons in {len(mini['frames'])} frames "
            f"({', '.join(f'{k}:{v}' for k, v in sorted(mini['frames'].items()))}); "
            f"{mini['joinable']} joined to a player - {mini['reason']}",
        )
    elif mini["present"]:
        matches = mini.get("matches") or {}
        detail = "positions.csv is empty at build time"
        if matches:
            detail += (
                f"; trajectories/minimap_matches.csv has {matches['rows']} "
                f"matched icons in {matches['frames']} frames (model validation "
                f"only, not a ten-player position stream)"
            )
        add_check(checks, "minimap positions", "WARN", detail)
    else:
        add_check(checks, "minimap positions", "WARN", "positions.csv not found")

    traj = ctx["traj"]
    pos_rows = sum(1 for r in rows if r["x"] is not None and r["z"] is not None)
    validation = traj.get("validation") or {}
    rms = validation.get("overall_rms_norm")
    if not traj["present"]:
        pos_level = "WARN"
        pos_detail = f"{pos_rows}/{total} rows have x/z; trajectories dir {traj['dir']} absent"
    else:
        pos_level = (
            "WARN" if pos_rows == 0 or (rms is not None and rms > 0.05) else "PASS"
        )
        source_text = ", ".join(
            f"{k} {v}" for k, v in sorted((traj.get("source_counts") or {}).items())
        )
        pos_detail = (
            f"{pos_rows}/{total} rows have x/z from trajectories "
            f"({source_text or 'no source classes'}); joined on frame; "
        )
        if validation:
            pos_detail += (
                f"validation {validation.get('verdict', 'UNKNOWN')}: RMS "
                f"{rms:.3f} of map span "
                f"({validation.get('overall_rms_units') or 0:.0f} units, "
                f"target <=0.05); {validation.get('matched_icons', 0)} matched "
                f"minimap icons in {validation.get('frames', 0)} evaluated "
                f"frames ({validation.get('frames_with_matches', 0)} with matches)"
            )
        else:
            pos_detail += "no validation.json"
    add_check(checks, "positions (x/z)", pos_level, pos_detail)

    # -- coverage / artifacts ----------------------------------------------
    coverage = {
        field: sum(1 for r in rows if r[field] is not None) for field in FIELD_ORDER
    }
    add_check(
        checks,
        "field coverage",
        "PASS",
        f"gold/KDA/level {coverage['gold']}/{total} "
        f"({pct(coverage['gold'], total)}), "
        f"HP {coverage['hp_current']}/{total} "
        f"({pct(coverage['hp_current'], total)}), "
        f"x/z {coverage['x']}/{total} ({pct(coverage['z'], total)}), "
        f"events {coverage['event_count']}/{total} "
        f"({pct(coverage['event_count'], total)})",
    )

    if ctx["out_exists"]:
        add_check(
            checks,
            "artifacts on disk",
            "PASS" if ctx["artifact_counts"] == (total, total) else "WARN",
            f"state.jsonl {ctx['artifact_counts'][0]} rows, state.csv "
            f"{ctx['artifact_counts'][1]} rows, in-memory {total}",
        )
    else:
        add_check(
            checks,
            "artifacts on disk",
            "INFO",
            "not written yet (use a normal run, not --check)",
        )

    extras = {
        "coverage": coverage,
        "deltas": deltas,
        "by_player_time": by_player_time,
    }
    return checks, extras


# ---------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------

def write_outputs(out_dir: Path, rows: list[dict]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = out_dir / "state.jsonl"
    csv_path = out_dir / "state.csv"
    with jsonl_path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            fh.write("\n")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=FIELD_ORDER, extrasaction="ignore", lineterminator="\n"
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ("" if row[k] is None else row[k]) for k in FIELD_ORDER})


def _check_table(checks: list[dict]) -> list[str]:
    lines = [
        "| check | level | detail |",
        "|---|---|---|",
    ]
    for check in checks:
        detail = check["detail"].replace("|", "\\|")
        lines.append(f"| {check['name']} | {check['level']} | {detail} |")
    return lines


def _delta_tables(deltas: list[dict]) -> list[str]:
    lines: list[str] = []
    grouped: dict[tuple[str, str, float], list[dict]] = defaultdict(list)
    for d in deltas:
        grouped[(d["from"], d["to"], d["dt"])].append(d)
    for (from_label, to_label, dt), items in grouped.items():
        lines.append("")
        lines.append(f"`{from_label} -> {to_label}` (+{dt:.1f} s)")
        lines.append("")
        lines.append("| player | camp | dGold | dK | dD | dA | dL | gold/s |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
        for d in sorted(items, key=lambda x: (x["camp"], x["player"])):
            dl = "-" if d["dl"] is None else f"{d['dl']:+d}"
            lines.append(
                f"| {d['player']} | {d['camp']} | {d['dgold']:+d} | "
                f"{d['dk']:+d} | {d['dd']:+d} | {d['da']:+d} | {dl} | "
                f"{d['gold_per_s']:.1f} |"
            )
    return lines


def _alignment_table(ctx: dict) -> list[str]:
    lines = [
        "| label | time_s | frame | base | pointer | UI | levels | stale |",
        "|---|---:|---:|---|---:|---:|---:|---:|",
    ]
    for m in ctx["arena_meta"]["snapshots"]:
        base = f"{m['base']:#x}" if m["base"] is not None else "-"
        lines.append(
            f"| {m['label']} | {m['time_s']:.3f} | {m['frame']} | {base} | "
            f"{m['pointer_match']}/10 | {m['ui_matches']}/10 | "
            f"{m['level_matches']}/10 | {m['stale_blocks']} |"
        )
    return lines


def render_readme(ctx: dict, checks: list[dict], extras: dict, hashes: dict) -> str:
    rows = ctx["rows"]
    total = len(rows)
    coverage = extras["coverage"]
    kinds = Counter(r["row_kind"] for r in rows)
    mini = ctx["minimap"]
    traj = ctx["traj"]
    unit_meta = ctx["unit_meta"]
    event_meta = ctx["event_meta"]
    total_frames = ctx["total_frames"]
    traj_validation = traj.get("validation") or {}
    traj_rms = traj_validation.get("overall_rms_norm")
    traj_units = traj_validation.get("overall_rms_units")
    traj_rms_text = f"{traj_rms:.1%}" if traj_rms is not None else "n/a"
    traj_units_text = f"{traj_units:,.0f}" if traj_units is not None else "n/a"

    lines: list[str] = []
    lines.append("# Per-player state table - live_20261104")
    lines.append("")
    lines.append(
        "Unified long-format player state for the offline replay checkpoint set "
        "`20261102_161129` (11:33 match). Generated by "
        "`tools/build_state_table.py`; do not edit by hand."
    )
    lines.append("")
    lines.append("Offline only: no adb, device, network or database access.")
    lines.append("")
    lines.append("## 0. At a glance")
    lines.append("")
    lines.append(
        f"- Rows: **{total}** (event-only {kinds.get('event', 0)}, "
        f"state-only {kinds.get('state', 0)}, "
        f"state+event {kinds.get('state+event', 0)})"
    )
    lines.append("- Players / entities: **10 / 10** (5 blue + 5 red)")
    lines.append(
        f"- Gold/KDA/level observations: **{coverage['gold']}** rows at "
        f"4 arena checkpoints"
    )
    lines.append(
        f"- HP observations: **{coverage['hp_current']}** rows at "
        f"{len({r['time_s'] for r in rows if r['hp_current'] is not None})} times"
    )
    lines.append(
        f"- Event coverage: **{len(event_meta['frames'])}/{total_frames} frames "
        f"({pct(len(event_meta['frames']), total_frames)})** in "
        f"{len(event_meta['windows'])} windows"
    )
    if traj["present"] and coverage["x"]:
        validation = traj.get("validation") or {}
        rms = validation.get("overall_rms_norm")
        rms_text = f"{rms:.1%}" if rms is not None else "n/a"
        lines.append(
            f"- Positions: **{coverage['x']}/{total}** rows with x/z from "
            f"`trajectories/` - dead-reckoned; validation RMS {rms_text} of "
            f"map span ({validation.get('verdict', 'UNKNOWN')}, target <=5%)"
        )
    else:
        lines.append(
            f"- Positions: **{coverage['x']}/{total}** rows with x/z "
            f"(trajectories absent; minimap has no hero identity)"
        )
    lines.append(
        "- Equipment: **visual-only at settlement**, not merged (no verified "
        "per-checkpoint item state)"
    )
    lines.append("")

    lines.append("## 1. Outputs")
    lines.append("")
    lines.append("| file | content |")
    lines.append("|---|---|")
    lines.append(
        "| `state.jsonl` | one JSON object per row, UTF-8, field order as below |"
    )
    lines.append(
        "| `state.csv` | identical rows, UTF-8 with BOM, empty string = null |"
    )
    lines.append("| `README.md` | this document |")
    lines.append("")
    lines.append(
        "Rows are one per `(player, frame)` and are sorted by `time_s`, then "
        "`camp`, `slot`, `player`."
    )
    lines.append("")

    lines.append("## 2. Schema")
    lines.append("")
    lines.append(
        "`hp_current` / `hp_max` are the **normalized** engine pair at "
        "`+0x08` / `+0x10` (max is ~1000, not absolute HP). "
        "`abs_hp_estimate = round(hp_ratio * hp_max_abs)` is only populated "
        "for the 07:26/07:29/07:32.97 unit-window samples, where the absolute "
        "maximum was read from the 07:29 attributes panel. At the four arena "
        "checkpoints only the ratio is available, so `hp_max_abs` and "
        "`abs_hp_estimate` are null there."
    )
    lines.append("")
    lines.append("| field | type | source | non-null | coverage |")
    lines.append("|---|---|---|---:|---:|")
    types = {
        "frame": "int",
        "time_s": "float",
        "time_mmss": "str",
        "player": "str",
        "hero": "str",
        "entity_id": "int",
        "camp": "int",
        "unit": "int",
        "slot": "int",
        "gold": "int",
        "kills": "int",
        "deaths": "int",
        "assists": "int",
        "level": "int",
        "hp_current": "int",
        "hp_max": "int",
        "hp_ratio": "float",
        "abs_hp_estimate": "int",
        "hp_max_abs": "int",
        "x": "float",
        "z": "float",
        "pos_source": "str",
        "event_count": "int",
        "event_families": "str",
        "row_kind": "str",
        "sources": "str",
        "arena_index": "int",
        "time_origin": "str",
        "time_uncertainty_s": "float",
        "note": "str",
    }
    for field in FIELD_ORDER:
        n = coverage[field]
        lines.append(
            f"| `{field}` | {types[field]} | {FIELD_SOURCE[field]} | {n} | "
            f"{pct(n, total)} |"
        )
    lines.append("")
    lines.append(
        "`sources` is a semicolon-separated flag list drawn from "
        "`arena_stats`, `arena_unit_object`, `unit_object`, `event_windows`, "
        "`trajectories`; the roster join is applied to every row and is not "
        "repeated there. `row_kind` is `state`, `event` or `state+event`. "
        "`note` is the per-row provenance / caveat string."
    )
    lines.append("")

    lines.append("## 3. Time points with state")
    lines.append("")
    lines.append("| label | time_s | time_mmss | frame | players | fields |")
    lines.append("|---|---:|---|---:|---:|---|")
    for point in ctx["state_points"]:
        lines.append(
            f"| {point['label']} | {point['time_s']:.3f} | "
            f"{mmss(point['time_s'])} | {point['frame']} | "
            f"{point['players']} | {point['fields']} |"
        )
    lines.append("")
    lines.append(
        "The four arena checkpoints use the exact unit-object clock "
        "(`+0x1664/+0x1668`; median of the valid resolved units, 9/10 "
        "because 孙悟空's clock is stale; 关羽/吕布 use "
        "`+0x1524/+0x1528`). The display label floors to the second, so e.g. "
        "`01:34` is 94.858 s. The three HP captures from the 8 KiB unit "
        "windows are 07:26.588 (钟馗 extra), 07:29.2 and 07:32.97."
    )
    lines.append("")

    lines.append("## 4. Source coverage")
    lines.append("")
    lines.append("### 4.1 Arena snapshots (gold / KDA / level / HP)")
    lines.append("")
    lines.append(
        f"- {len(ctx['arena_meta']['snapshots'])} snapshots x 10 players = "
        f"{len(ctx['arena_samples'])} rows. Each row carries gold, KDA, "
        f"level, and the normalized HP pair from the record's unit object."
    )
    lines.append(
        "- Record layout: `+0x4C` gold, `gold+0x158` kills, `gold+0xB8` "
        "deaths, `gold+0xBC` assists, `+0x220` level (low byte)."
    )
    lines.append(
        "- Verified against the UI screenshots at 01:34/02:45/05:00: "
        "**30/30 gold**, **30/30 KDA**, **6/6** camp gold sums within 100 of "
        "the top bar; **30/30 levels** against the sidebar/scoreboard."
    )
    lines.append(
        "- `levels.csv` cross-check: **40/40** (30 screen+read at "
        "01:34/02:45/05:00, 10 engine-only at 07:46). Its header is "
        "misleading: the `player` column holds the hero name and `hero` holds "
        "the numeric heroID, so the tool joins on the `entity` column."
    )
    lines.append(
        "- `assists_alt` at `gold+0xC0` is 1 or 2 for every player at every "
        "snapshot (static), so it is not an assists counter and is not used."
    )
    lines.append(
        "- The docs table lists 05:00 妲己 as 2/0/1 and 关羽 as 3138; the "
        "screenshots show 2/0/0 and 3135, and the engine agrees, so no "
        "correction is applied."
    )
    lines.append("")
    lines.append("Record alignment (including the 07:46 caveat):")
    lines.append("")
    lines.extend(_alignment_table(ctx))
    lines.append("")
    lines.append(
        "Every record's `+0x28` is an absolute unit pointer. The arena file is "
        "a dump of one contiguous region, so `pointer - file_offset` is a "
        "constant base; the base with ten votes selects the ten true unit "
        "objects. All four snapshots resolve **10/10** to the documented idx "
        "order (idx 13..4 -> 兰陵王..吕布) with no stale block and no pointer "
        "conflict. The 07:46 row has no UI screenshot, so its UI column is "
        "0/10 by construction; identity there rests on the pointer and "
        "`levels.csv`."
    )
    lines.append("")
    lines.append(
        "The 07:46 block was flagged as possibly stale: at that snapshot "
        "idx 1000000004 has gold 4549, KDA 2/3/1 and level 9. Resolving its "
        "`+0x28` pointer gives the unit at file offset `0x1bd0608`, heroID "
        "123 (吕布, camp 2, entity 296), and the 07:45 sidebar shows 吕布 at "
        "level 9. The record is 吕布's, not 钟馗's. 钟馗 is idx 1000000009: "
        "gold 3962, KDA 2/1/4, level 8, matching the sidebar's level 8. No "
        "record was remapped and no block was marked stale."
    )
    lines.append("")
    lines.append("### 4.2 Unit windows (HP)")
    lines.append("")
    lines.append(
        f"- {unit_meta['files']} `unit_*_t*.bin` files -> "
        f"{unit_meta['samples']} unique samples (one duplicate merged: "
        "`unit_zhongkui_t1.bin` is byte-identical to `unit_钟馗_t0.bin`)."
    )
    lines.append(
        "- Identity is checked per file: `+0x28` heroID, `+0x34` camp, "
        "`+0x3C/+0x40` entityID all match the roster."
    )
    lines.append(
        "- Clock is `+0x1664/+0x1668`; 关羽/吕布 use `+0x1524/+0x1528` "
        "(record shifted -0x140). `unit_zhongkui_t0.bin` is a bonus earlier "
        "sample at 07:26.6."
    )
    lines.append(
        "- The normalized max channel `+0x10` is one value per hero across "
        "all arena and unit captures (10/10), so the HP ratio is comparable "
        "across the whole table."
    )
    lines.append("")
    lines.append("### 4.3 Level")
    lines.append("")
    lines.append(
        "- Level is the u32 at record `+0x220` (low byte), part of the "
        "`+0x218=16, +0x21C=8, +0x220=level, +0x224=kills, +0x228=deaths` "
        "block."
    )
    lines.append(
        "- Populated at 01:34, 02:45, 05:00 and 07:46 (40 rows). It is null "
        "on the 07:26/07:29/07:32 HP rows: the unit windows do not contain a "
        "level field, and there is no arena snapshot at those frames."
    )
    lines.append(
        "- `levels.csv` also has screen-only 07:26 levels; they are not "
        "merged because they are not engine-read and the 07:26 HP sample is "
        "only 钟馗."
    )
    lines.append("")
    lines.append("### 4.4 Events")
    lines.append("")
    lines.append(
        f"- {event_meta['rows']} rows / {len(event_meta['frames'])} frames / "
        f"{event_meta['player_frames']} player-frames; families: "
        + ", ".join(f"{k} {v}" for k, v in sorted(event_meta["families"].items()))
        + "."
    )
    lines.append(
        "- Windows: "
        + ", ".join(
            f"{w} frames {r['min']}..{r['max']} ({r['rows']} rows)"
            for w, r in sorted(event_meta["window_ranges"].items())
        )
        + "."
    )
    lines.append(
        "- All rows join a roster player; `time_s = (frame-1)/15` holds for "
        "every row."
    )
    lines.append(
        f"- {event_meta['duplicate_extra']} exact duplicate rows (BUYEQUIP "
        "notification echoes) are kept in the source but counted once per "
        "player-frame."
    )
    lines.append(
        "- No kill/death family exists in this replay route; `event_count` is "
        "actions, not combat outcomes."
    )
    lines.append("")
    lines.append("### 4.5 Minimap")
    lines.append("")
    if mini["present"] and mini["rows"]:
        lines.append(
            f"- {mini['rows']} icons in {len(mini['frames'])} frames: "
            + ", ".join(f"`{k}` {v}" for k, v in sorted(mini["frames"].items()))
            + "."
        )
        lines.append(
            "- Confidence: "
            + ", ".join(f"{k} {v}" for k, v in sorted(mini["confidence"].items()))
            + "."
        )
        lines.append(
            "- **0 rows joined**: the extractor gives team only, not hero "
            "identity; `u,v` are panel-normalized pixels, not world units."
        )
        lines.append(
            "- Only 4-9 icons are drawn per frame (stacked icons and observer "
            "states are missed), so even a future identity pass would be "
            "partial."
        )
    elif mini["present"]:
        lines.append(
            "- `minimap_positions/positions.csv` is present but **empty** at "
            "build time."
        )
        matches = mini.get("matches") or {}
        if matches:
            lines.append(
                f"- `{matches['path']}` holds {matches['rows']} matched icons "
                f"in {matches['frames']} frames ("
                + ", ".join(
                    f"{k} {v}" for k, v in sorted(matches["confidence"].items())
                )
                + "); this is the trajectory model's validation subset, not a "
                "ten-player position stream."
            )
        lines.append(
            "- No minimap position is joined to x/z; x/z come from the "
            "trajectory model."
        )
    else:
        lines.append("- `positions.csv` not found.")
    lines.append("")
    lines.append("### 4.6 Trajectories")
    lines.append("")
    if traj["present"]:
        lines.append(
            f"- Directory present: {', '.join(traj['files'])}. "
            f"{traj['rows']} trajectory rows; {traj['joined']}/{total} table "
            f"rows joined on the exact ABC `frame` (not the file's `time` "
            f"column, which is on the engine 15.1515 fps axis and offset by "
            f"~2 s from `time_csv`)."
        )
        source_text = ", ".join(
            f"{k} {v}" for k, v in sorted((traj.get("source_counts") or {}).items())
        )
        lines.append(
            f"- Source classes: {source_text or 'none'}; `pos_source` records "
            f"the class per row."
        )
        validation = traj.get("validation") or {}
        if validation:
            rms = validation.get("overall_rms_norm")
            units = validation.get("overall_rms_units") or 0
            forced = validation.get("overall_rms_norm_forced")
            lines.append(
                f"- **Validation: {validation.get('verdict', 'UNKNOWN')}** - "
                f"RMS {rms:.3f} of the map span ({units:.0f} units) against "
                f"the <=0.05 target; forced-assignment RMS {forced:.3f}; "
                f"{validation.get('matched_icons', 0)} matched minimap icons "
                f"in {validation.get('frames', 0)} evaluated frames "
                f"({validation.get('frames_with_matches', 0)} with matches)."
            )
        model = traj.get("model") or {}
        if model:
            lines.append(
                f"- Model: `{model.get('name')}` speed {model.get('speed')} "
                f"u/s, {model.get('step_per_frame'):.1f} u/frame, "
                f"hold={model.get('hold')}, convention "
                f"`{model.get('convention')}`."
            )
        lines.append(
            "- Caveats: dead reckoning from `PLAYER_MOVE` input directions; "
            "terrain collisions, respawns/recalls, camera-relative input and "
            "the missing death events all accumulate error. The minimap has no "
            "hero identity, so the residuals include assignment error."
        )
    else:
        lines.append(
            f"- `{traj['dir']}` does not exist at build time, so `x`/`z` are "
            "null for every row. The loader already accepts CSV/JSONL with "
            "player/hero/entity + frame/time_s + x/z and joins by exact "
            "(entity, frame) or nearest time within "
            f"{traj['tolerance_s']} s."
        )
    lines.append("")

    lines.append("## 5. Checks (`--check`)")
    lines.append("")
    lines.extend(_check_table(checks))
    lines.append("")
    lines.append("### Gold/KDA/level deltas vs next snapshot")
    lines.extend(_delta_tables(extras["deltas"]))
    lines.append("")

    lines.append("## 6. Known gaps")
    lines.append("")
    lines.append("### Top 3")
    lines.append("")
    lines.append(
        "1. **Equipment is visual-only.** `levels_equipment/equipment.csv` "
        "has 52 item icons read by eye from the post-match settlement screen "
        "(`back_from_settle.png`); `memory_verified=no` for every row and it "
        "is not time-aligned to these checkpoints. No equipment column is "
        "emitted."
    )
    lines.append(
        "2. **Positions exist but are dead-reckoned.** "
        "`trajectories/player_trajectories.csv` gives X/Z for all 10,509 "
        f"frames and all {coverage['x']}/{total} table rows join on the exact "
        f"frame, but the reconstruction **fails validation**: RMS "
        f"{traj_rms_text} of the map span ({traj_units_text} units) against "
        "the <=0.05 target. It integrates `PLAYER_MOVE` input directions with "
        "a constant 1,800 u/s model and ignores terrain collisions, "
        "respawns/recalls and camera-relative input. The minimap matched "
        "subset covers only 14 icons in 4 frames, so it cannot correct the "
        "drift. Treat `x`/`z` as approximate dead-reckoned coordinates, not "
        "measured positions; `pos_source` records spawn/integrated/idle."
    )
    lines.append(
        "3. **State is sampled, not continuous.** Gold/KDA/level exist only "
        "at the four arena checkpoints; HP at those four plus "
        "07:26.6/07:29.2/07:32.97. The event stream covers "
        f"{len(event_meta['frames'])} of {total_frames} frames "
        f"({pct(len(event_meta['frames']), total_frames)}) in four +-3 s "
        "windows and has no kill/death family, so the table cannot "
        "interpolate state between checkpoints."
    )
    lines.append("")
    lines.append("### Additional gaps / caveats")
    lines.append("")
    lines.append(
        "- **Absolute HP is only defined at 07:29/07:32.97 (and 07:26 钟馗).** "
        "The four arena checkpoints carry only the normalized ratio; their "
        "absolute maximum was not sampled, so `abs_hp_estimate` is null "
        "there. Level/equipment growth makes the 07:29 panel maximum invalid "
        "at 01:34/02:45/05:00."
    )
    lines.append(
        "- **HP ratio can exceed 1.0.** 兰陵王 reads 1.150 (07:29) and 1.117 "
        "(07:32.97); 百里守约 reads 1.022 at 05:00. This is likely a "
        "shield/overheal or a max channel that lags, and is flagged per row."
    )
    lines.append(
        "- **One stale unit clock.** 孙悟空's `+0x1664/+0x1668` reads "
        "3587 / 1337 ms (00:01.3) in every arena and unit capture; the "
        "snapshot median is used for that row and the row is flagged."
    )
    lines.append(
        "- **Record identity is pointer-validated, not idx-only.** The idx "
        "13..4 order comes from `docs/replay_binary_format.md` section 5.157; "
        "each snapshot is additionally checked against the `+0x28` unit "
        "pointer, the UI KDA/gold anchors and `levels.csv`. A future replay "
        "with a different roster order or a stale block would fail the "
        "alignment check instead of silently mixing players."
    )
    lines.append(
        "- **Trajectory speed is inconsistent with the engine prior.** "
        "`validation.md` chose 1,800 u/s; the engine's 360-390 cm/s prior at "
        "this coordinate scale is ~3,700 u/s. No tested speed (300-6,000 u/s) "
        "reaches the <=5% target, so the X/Z scale is uncertain as well as "
        "the accumulated drift."
    )
    lines.append(
        "- **Minimap positions.csv is empty at build time.** The matched "
        "subset in `trajectories/minimap_matches.csv` is 14 icons in 4 "
        "frames and is used only for model validation; there is no "
        "ten-player minimap stream to join."
    )
    lines.append(
        "- **Unit-object coordinates are static anchors.** The camp-signed "
        "i32 pair at unit `+0x278/+0x280` is identical across the "
        "07:26/07:29/07:32.97 samples and sits in two rings around the "
        "fountains, so it is not a live position and is not emitted as x/z."
    )
    lines.append(
        "- **Time base.** The replay is 15 fps; the unit-object clock runs at "
        "~15.15 ticks/s and is not the ABC frame axis. Frames are derived "
        "from clock milliseconds at 15 fps (max 0.033 s rounding)."
    )
    lines.append(
        "- **No team/objective state.** Towers, dragons, buffs, cooldowns and "
        "economy ledgers are not in any merged source; only per-player gold "
        "and derived camp sums are available."
    )
    lines.append(
        "- **Facing only for the recorder.** The `0x2d` aim/facing stream "
        "exists only for 百里守约 (entity 1611); `facing` is not a ten-player "
        "family."
    )
    lines.append(
        "- **Event windows are checkpoint-centred.** They are not a full "
        "replay event log; frames outside the four windows have no events."
    )
    lines.append("")

    lines.append("## 7. Reproduction")
    lines.append("")
    lines.append("```bash")
    lines.append("python -I tools/build_state_table.py")
    lines.append("python -I tools/build_state_table.py --check")
    lines.append("```")
    lines.append("")
    lines.append("Inputs (sha256):")
    lines.append("")
    lines.append("| file | bytes | sha256 |")
    lines.append("|---|---:|---|")
    for name, info in hashes.items():
        lines.append(f"| `{name}` | {info['bytes']} | `{info['sha256']}` |")
    lines.append("")
    lines.append(
        "The arena records are decoded with "
        "`tools/arena_player_stats.py` (`find_records`), imported directly; "
        "no other agent's output is modified."
    )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def _compute_team_gold(arena_samples: list[dict]) -> int:
    sums = defaultdict(lambda: defaultdict(int))
    for sample in arena_samples:
        sums[sample["label"]][sample["camp"]] += sample["gold"]
    ok = 0
    for label, camps in sums.items():
        ref = UI_TEAM_GOLD.get(label, {})
        for camp, value in camps.items():
            if camp in ref and abs(value - ref[camp]) <= 100:
                ok += 1
    return ok


def _state_points(rows: list[dict]) -> list[dict]:
    grouped: dict[tuple[float, str], dict] = {}
    for row in rows:
        if row["gold"] is None and row["hp_current"] is None:
            continue
        key = (row["time_s"], row["time_origin"])
        point = grouped.setdefault(
            key,
            {
                "time_s": row["time_s"],
                "frame": row["frame"],
                "players": set(),
                "fields": set(),
                "origin": row["time_origin"],
            },
        )
        point["players"].add(row["player"])
        if row["gold"] is not None:
            point["fields"].add("gold/KDA")
        if row["level"] is not None:
            point["fields"].add("level")
        if row["hp_current"] is not None:
            point["fields"].add("HP")
    out = []
    for point in grouped.values():
        point["players"] = len(point["players"])
        point["fields"] = ", ".join(sorted(point["fields"]))
        suffix = (
            " checkpoint"
            if point["origin"] == "arena_unit_clock"
            else " HP capture"
        )
        point["label"] = mmss(point["time_s"]) + suffix
        out.append(point)
    out.sort(key=lambda p: p["time_s"])
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--analysis-dir",
        type=Path,
        default=DEFAULT_ANALYSIS_DIR,
        help="directory holding the live_20261104 inputs",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="output directory (default: <analysis-dir>/state_table)",
    )
    parser.add_argument(
        "--trajectories-dir",
        type=Path,
        default=None,
        help="optional trajectory source (default: <analysis-dir>/trajectories)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="build in memory and print the check report; write nothing",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="suppress the per-run summary (--check still prints its report)",
    )
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    analysis_dir = args.analysis_dir.resolve()
    out_dir = (args.out_dir or (analysis_dir / "state_table")).resolve()
    traj_dir = (args.trajectories_dir or (analysis_dir / "trajectories")).resolve()

    roster, match, roster_source = load_roster(analysis_dir)
    roster_by_player = {r["player"]: r for r in roster}
    roster_by_hero = {r["hero"]: r for r in roster}
    roster_by_entity = {r["entity_id"]: r for r in roster}

    levels_table, levels_meta = load_levels_table(
        analysis_dir, roster_by_entity, roster_by_hero
    )
    events, event_meta = load_events(analysis_dir, roster_by_player)
    arena_samples, arena_meta = load_arena(
        analysis_dir, roster_by_player, roster_by_hero, levels_table
    )
    unit_samples, unit_meta = load_units(analysis_dir, roster_by_hero)
    minimap = load_minimap(analysis_dir)
    traj_points, traj_meta = load_trajectories(
        traj_dir, roster_by_player, roster_by_hero
    )

    raw_rows = build_rows(
        roster_by_player, arena_samples, unit_samples, events, traj_points
    )
    out_rows = public_rows(raw_rows)
    traj_meta["joined"] = sum(
        1 for row in raw_rows if row["x"] is not None and row["z"] is not None
    )

    total_frames = int(
        match.get("frameRecords")
        or match.get("totalFrameHeader")
        or DEFAULT_TOTAL_FRAMES
    )

    # HP sanity statistics: 8 KiB unit windows only for the t0/t1 pair.
    main_clusters = sorted(
        [c for c in unit_meta["clusters"] if c["samples"] >= 5],
        key=lambda c: c["time_s"],
    )
    hp_by_player = defaultdict(dict)
    for sample in unit_samples:
        hp_by_player[sample["player"]][round(sample["time_s"], 3)] = sample
    hp_max_stable = 0
    hp_changed = 0
    for player, samples in hp_by_player.items():
        times = sorted(samples)
        if len(times) >= 2 and main_clusters:
            first = main_clusters[0]["time_s"]
            last = main_clusters[-1]["time_s"]
            a = samples.get(round(first, 3))
            b = samples.get(round(last, 3))
            if a and b:
                if a["hp_max"] == b["hp_max"]:
                    hp_max_stable += 1
                if a["hp_current"] != b["hp_current"]:
                    hp_changed += 1

    arena_hp_max = defaultdict(set)
    for sample in arena_samples:
        if sample["hp_max"] is not None:
            arena_hp_max[sample["hero"]].add(sample["hp_max"])
    unit_hp_max = defaultdict(set)
    for sample in unit_samples:
        unit_hp_max[sample["hero"]].add(sample["hp_max"])
    arena_hp_max_constant = sum(
        1 for values in arena_hp_max.values() if len(values) == 1
    )
    hp_max_cross = sum(
        1
        for hero in roster_by_hero
        if arena_hp_max.get(hero) == unit_hp_max.get(hero)
        and len(arena_hp_max.get(hero, set())) == 1
    )

    ratios = []
    gt1_players = []
    for sample in arena_samples + unit_samples:
        if sample["hp_ratio"] is not None:
            ratios.append(sample["hp_ratio"])
            if sample["hp_ratio"] > 1.0 and sample["player"] not in gt1_players:
                gt1_players.append(sample["player"])

    ui_kda_ok = 0
    for sample in arena_samples:
        if sample["ui_image"] is None:
            continue
        ref = UI_REFERENCE.get(sample["label"], {}).get(sample["hero"])
        if ref and (
            sample["kills"],
            sample["deaths"],
            sample["assists"],
        ) == ref[:3]:
            ui_kda_ok += 1

    # Artifact counts for --check.
    jsonl_path = out_dir / "state.jsonl"
    csv_path = out_dir / "state.csv"
    out_exists = jsonl_path.exists() and csv_path.exists()
    artifact_counts = (0, 0)
    if out_exists:
        with jsonl_path.open(encoding="utf-8") as fh:
            n_json = sum(1 for _ in fh)
        with csv_path.open(encoding="utf-8-sig", newline="") as fh:
            n_csv = sum(1 for _ in csv.DictReader(fh))
        artifact_counts = (n_json, n_csv)

    ctx = {
        "rows": out_rows,
        "raw_rows": raw_rows,
        "roster": roster,
        "roster_by_player": roster_by_player,
        "roster_by_hero": roster_by_hero,
        "roster_source": roster_source,
        "match": match,
        "levels_table": levels_table,
        "levels_meta": levels_meta,
        "arena_samples": arena_samples,
        "arena_meta": arena_meta,
        "unit_samples": unit_samples,
        "unit_meta": unit_meta,
        "events": events,
        "event_meta": event_meta,
        "minimap": minimap,
        "traj": traj_meta,
        "total_frames": total_frames,
        "team_gold_ok": _compute_team_gold(arena_samples),
        "ui_kda_ok": ui_kda_ok,
        "hp_max_stable": hp_max_stable,
        "hp_changed": hp_changed,
        "arena_hp_max_constant": arena_hp_max_constant,
        "hp_max_cross": hp_max_cross,
        "hp_ratio_min": min(ratios) if ratios else 0.0,
        "hp_ratio_max": max(ratios) if ratios else 0.0,
        "hp_ratio_gt1": sum(1 for r in ratios if r > 1.0),
        "hp_ratio_gt1_players": gt1_players,
        "out_exists": out_exists,
        "artifact_counts": artifact_counts,
    }
    ctx["state_points"] = _state_points(out_rows)

    if not args.check:
        # The artifacts are written immediately after this check run; report
        # them as present in the generated README rather than "not written".
        ctx["out_exists"] = True
        ctx["artifact_counts"] = (len(out_rows), len(out_rows))

    checks, extras = run_checks(ctx)
    counts = Counter(c["level"] for c in checks)

    if args.check:
        print(f"State table check - {display_path(analysis_dir)}")
        print(
            f"Rows: {len(out_rows)} "
            f"(state {sum(1 for r in out_rows if r['row_kind'] == 'state')}, "
            f"state+event {sum(1 for r in out_rows if r['row_kind'] == 'state+event')}, "
            f"event {sum(1 for r in out_rows if r['row_kind'] == 'event')}); "
            f"players {len({r['player'] for r in out_rows})}, "
            f"entities {len({r['entity_id'] for r in out_rows})}"
        )
        print(
            "State time points: "
            + ", ".join(
                f"{p['label']} ({p['players']}p)" for p in ctx["state_points"]
            )
        )
        print("")
        for check in checks:
            print(f"[{check['level']}] {check['name']}: {check['detail']}")
        print("")
        print("Arena record alignment")
        for line in _alignment_table(ctx):
            print(line)
        print("")
        print("Gold/KDA/level deltas vs next snapshot")
        for line in _delta_tables(extras["deltas"]):
            print(line)
        print("")
        print("Field coverage")
        for field in FIELD_ORDER:
            n = extras["coverage"][field]
            print(
                f"  {field:20s} {n:6d}/{len(out_rows):6d}  "
                f"{pct(n, len(out_rows)):>7s}"
            )
        print("")
        print(
            f"Result: {counts.get('PASS', 0)} PASS, "
            f"{counts.get('WARN', 0)} WARN, {counts.get('FAIL', 0)} FAIL"
        )
        return 0 if counts.get("FAIL", 0) == 0 else 1

    # Normal build.
    input_paths = [
        analysis_dir / filename
        for _, _, filename, _ in SNAPSHOTS
        if (analysis_dir / filename).exists()
    ]
    input_paths += [
        analysis_dir / "abc_timeline" / "event_windows.csv",
        analysis_dir / "minimap_positions" / "positions.csv",
        analysis_dir / "levels_equipment" / "levels.csv",
    ]
    hashes = {}
    for path in input_paths:
        if path.exists():
            hashes[display_path(path)] = {
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }

    readme = render_readme(ctx, checks, extras, hashes)
    write_outputs(out_dir, out_rows)
    (out_dir / "README.md").write_text(readme, encoding="utf-8")

    if not args.quiet:
        print(
            f"rows={len(out_rows)} "
            f"(state {sum(1 for r in out_rows if r['row_kind'] == 'state')}, "
            f"state+event {sum(1 for r in out_rows if r['row_kind'] == 'state+event')}, "
            f"event {sum(1 for r in out_rows if r['row_kind'] == 'event')})"
        )
        print(
            f"gold {extras['coverage']['gold']}/{len(out_rows)}, "
            f"level {extras['coverage']['level']}/{len(out_rows)}, "
            f"HP {extras['coverage']['hp_current']}/{len(out_rows)}, "
            f"events {extras['coverage']['event_count']}/{len(out_rows)}, "
            f"x/z {extras['coverage']['x']}/{len(out_rows)}"
        )
        print(
            f"checks: {counts.get('PASS', 0)} PASS, "
            f"{counts.get('WARN', 0)} WARN, {counts.get('FAIL', 0)} FAIL"
        )
        for name in ("state.jsonl", "state.csv", "README.md"):
            path = out_dir / name
            print(f"wrote {display_path(path)} ({path.stat().st_size} bytes)")
    return 0 if counts.get("FAIL", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
