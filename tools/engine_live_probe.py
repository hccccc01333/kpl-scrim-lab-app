#!/usr/bin/env python3
"""Live GameCore engine-state probe for a paused KPL replay session.

What this tool does
-------------------
While a replay is loaded (and preferably paused) in the MuMu instance, the
GameCore engine keeps a 30 MiB self-relative arena that holds the authoritative
per-player battle state.  This tool **only reads** process memory through
`adb root` + `/proc/<pid>/mem` and writes the captured state under `data/`:

1. finds the game pid (`com.tencent.tmgp.sgame`), reads `/proc/<pid>/maps`;
2. resolves the arena context through the documented chain
   `libGameCore.so base + 0x4FF4520 -> u64 -> u64 -> u64 = ctx`,
   `u32(ctx + 8) = arena size` (~0x1E00000).  If the chain fails it falls back
   to (a) scanning libGameCore's readable mappings for heap pointers into a
   30 MiB arena mapping (the documented `.data` pointer search) and (b) scanning
   the first page of every large rw mapping for the self-referencing arena
   header.  Every candidate is verified and printed as a diagnostic;
3. captures the arena in chunked `dd` reads from the page containing `ctx`
   (`ctx & ~0xFFF`, so file offset 0 is the arena mapping base on this build,
   `ctx = base + 0xFF0`), with per-chunk retries and an exact length check;
4. decodes the ten per-player battle records by header signature
   (README.md 5.157/5.158) and follows each record's
   `+0x28` absolute pointer to the arena-internal unit object, then reads
   HP / hero / camp / entity / clock from the unit (5.157.3/5.157.4);
5. writes `meta.json`, `arena.bin` (optional) and `units.jsonl` (+ per-unit
   0x2000-byte prefixes) and validates the snapshot.

Documented layouts this tool relies on (do not re-derive on device)
-------------------------------------------------------------------
Arena context (5.155, 5.157):

    ctx + 0x00  u64 self pointer  (= ctx)
    ctx + 0x08  u32 arena size    (0x1E00000)
    ctx         = mappings[arena].start + 0xFF0   (page aligned)

Per-player record header (5.157/5.158, scan don't hardcode offset):

    rec + 0x00  u32 16
    rec + 0x04  u32 subtype / variable-length marker
    rec + 0x08  u32 10000
    rec + 0x0C  f32 ~3.32         (3.20 .. 3.40)
    rec + 0x20  u32 1000000000 + idx, idx = 13..4
    rec + 0x28  u64 absolute pointer to the unit object
    rec + 0x4C  u32 gold
    rec + 0x50  u32 x 11 cumulative counters c0..c10
    gold+0x158  u32 kills     (duplicate rec+0x224)
    gold+0xB8   u32 deaths    (duplicate rec+0x228)
    gold+0xBC   u32 assists   (variable-length records may shift to +0xC0)
    rec + 0x218 u32 16, +0x21C u32 8, +0x220 u32 level

Unit object (5.157.3, 5.157.4):

    unit + 0x08  u32 HP current (normalized)
    unit + 0x10  u32 HP max     (normalized, ~1000)
    unit + 0x28  u32 heroID
    unit + 0x34  u32 camp (1 blue, 2 red)
    unit + 0x3C  u32 entityID, +0x40 duplicate
    unit + 0x1664 u32 clock frame, +0x1668 u32 clock ms
    unit + 0x1524/+0x1528 same clock for 关羽(140)/吕布(123), layout -0x140
    unit + 0x278 i32 x, +0x27C i32 y, +0x280 i32 z  (spawn anchor)
    unit + 0x288/+0x290 i32 facing pair

The record <-> player identity is established by the **pointer**, not by the
static idx order (既有校准 order is only a cross-check and is reported as a
warning if a future replay reorders the roster).

Usage
-----
    python tools/engine_live_probe.py \
        --adb D:/MuMuPlayer/nx_main/adb.exe \
        --serial 127.0.0.1:16385 \
        --out data/replays/_analysis/engine_20261112/snap_pause_0134 \
        --label pause_0134 --mode all

    # locate only (no capture, safe device smoke test):
    python tools/engine_live_probe.py --label smoke --locate-only

    # capture the arena and only decode the ten records:
    ... --mode records

Modes: arena (raw capture only) < records (+ ten record headers) <
units (+ unit objects, units.jsonl) < all (+ clock/HP validation; default).
Exit codes: 0 = checks passed (WARN allowed), 2 = device/process/maps/locate
failed, 3 = capture/read failed, 4 = snapshot decoded but validation FAILed,
5 = usage/IO error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

try:  # optional fast path; the pure decoders also work without numpy
    import numpy as np
except ImportError:  # pragma: no cover - environment dependent
    np = None

ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.frapinfo_live_probe import Adb, Mapping, Reader  # noqa: E402

ADB_DEFAULT = "D:/MuMuPlayer/nx_main/adb.exe"
SERIAL_DEFAULT = "127.0.0.1:16385"
SERIAL_ALT_DEFAULT = ("127.0.0.1:16384",)
PACKAGE_DEFAULT = "com.tencent.tmgp.sgame"

#: `[libGameCore_base + 0x4FF4520]` -> u64 -> u64 -> u64 = arena context.
GC_CHAIN_OFFSET = 0x4FF4520
CHAIN_HOPS = 3
#: The context header sits 0xFF0 bytes into the arena mapping on this build.
CTX_PAGE_OFFSET = 0xFF0
ARENA_SIZE_EXPECTED = 0x1E00000
ARENA_SIZE_MIN = 0x100000
ARENA_SIZE_MAX = 0x4000000

# Record header (5.157/5.158).
REC_INDEX_BASE = 1000000000
REC_INDEX_MIN = 1000000004
REC_INDEX_MAX = 1000000013
REC_INDEXES = tuple(range(4, 14))
REC_MAGIC = 16
REC_MAGIC_10000 = 10000
REC_SIG_LO = 3.20
REC_SIG_HI = 3.40
REC_MIN_BYTES = 0x240
REC_POINTER_OFF = 0x28
REC_GOLD_OFF = 0x4C
REC_LEVEL_OFF = 0x220
REC_COUNTER_OFF = 0x50
REC_COUNTERS = 11
REC_GOLD_KILLS = 0x158
REC_GOLD_DEATHS = 0xB8
REC_GOLD_ASSISTS = 0xBC
REC_GOLD_ASSISTS_ALT = 0xC0
REC_LEVEL_KILLS_ALT = 0x224
REC_LEVEL_DEATHS_ALT = 0x228
REC_BLOCK_GAP = 0x40000

# Unit object (5.157.3/5.157.4).
UNIT_HP_CUR_OFF = 0x08
UNIT_HP_MAX_OFF = 0x10
UNIT_HERO_OFF = 0x28
UNIT_CAMP_OFF = 0x34
UNIT_ENTITY_OFF = 0x3C
UNIT_ENTITY_DUP_OFF = 0x40
UNIT_CLOCK_OFF = 0x1664
UNIT_CLOCK_ESCAPE_OFF = 0x1524
UNIT_CLOCK_ESCAPE_HEROES = (123, 140)  # 吕布 / 关羽, record shifted -0x140
UNIT_POS_OFF = 0x278
UNIT_FACING_OFF = 0x288
UNIT_NEED = 0x1700  # bytes needed to read every documented unit field
UNIT_PREFIX = 0x2000  # bytes dumped per unit object
HP_MAX_MIN = 900
HP_MAX_MAX = 1200
HP_CUR_MAX = 1600
CLOCK_TOLERANCE_MS = 500
CLOCK_MIN_VALID = 9
CLOCK_STALE_DEVIATION_MS = 5000

#: heroID -> hero name (既有校准).
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
#: Documented arena record order (idx 13 -> 4, 既有校准).  Only a cross-check.
ARENA_INDEX_HEROES = (
    "兰陵王", "张良", "妲己", "百里守约", "钟馗",
    "公孙离", "孙悟空", "貂蝉", "关羽", "吕布",
)
MODE_RANK = {"arena": 0, "records": 1, "units": 2, "all": 3}

SCHEMA = "kpl-engine-live-snapshot-v1"
TOOL_NAME = "tools/engine_live_probe.py"


# ---------------------------------------------------------------------------
# Errors and small helpers
# ---------------------------------------------------------------------------
class ProbeError(RuntimeError):
    """A probe stage failed; ``code`` is the CLI exit code to use."""

    def __init__(self, code: int, message: str, **info: object) -> None:
        super().__init__(message)
        self.code = code
        self.info = info


def u32(raw: bytes, off: int) -> int:
    return struct.unpack_from("<I", raw, off)[0]


def u64(raw: bytes, off: int) -> int:
    return struct.unpack_from("<Q", raw, off)[0]


def f32(raw: bytes, off: int) -> float:
    return struct.unpack_from("<f", raw, off)[0]


def i32(raw: bytes, off: int) -> int:
    return struct.unpack_from("<i", raw, off)[0]


def hx(value: int | None) -> str | None:
    return f"0x{value:x}" if isinstance(value, int) else None


def sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sane_arena_size(size: int) -> bool:
    return ARENA_SIZE_MIN <= size <= ARENA_SIZE_MAX


def mapping_of(maps: list[Mapping], addr: int) -> Mapping | None:
    for m in maps:
        if m.start <= addr < m.end:
            return m
    return None


def _mapping_summary(m: Mapping | None) -> dict | None:
    if m is None:
        return None
    return {"start": m.start, "end": m.end, "size": m.size,
            "perms": m.perms, "offset": m.offset, "path": m.path}


# ---------------------------------------------------------------------------
# Pure layer: record headers
# ---------------------------------------------------------------------------
def find_record_headers(raw: bytes) -> list[dict]:
    """Every per-player record header in *raw*, including duplicate blocks.

    Unlike :func:`tools.arena_player_stats.find_records` this does not
    deduplicate by index: after seeking, a 30 MiB arena can hold more than one
    block, and the caller must be able to report stale blocks.  The signature
    is the documented one (``16, *, 10000, ~3.32, 1000000000+idx``).
    """
    n = len(raw)
    if n < REC_MIN_BYTES:
        return []
    limit = n - REC_MIN_BYTES

    if np is not None:
        count = n // 4
        a = np.frombuffer(raw, dtype="<u4", count=count)
        # a[k] == 16 and a[k + 2] == 10000  ->  header at offset 4*k.
        if count >= 3:
            mask = (a[:-2] == REC_MAGIC) & (a[2:] == REC_MAGIC_10000)
            positions = [int(k) * 4 for k in np.nonzero(mask)[0]]
        else:  # pragma: no cover - tiny buffers
            positions = []
    else:  # pragma: no cover - exercised only when numpy is unavailable
        positions = range(0, limit + 1, 4)

    headers: list[dict] = []
    for off in positions:
        if off < 0 or off + REC_MIN_BYTES > n:
            continue
        if u32(raw, off) != REC_MAGIC or u32(raw, off + 8) != REC_MAGIC_10000:
            continue
        if not REC_SIG_LO <= f32(raw, off + 0x0C) <= REC_SIG_HI:
            continue
        index = u32(raw, off + 0x20)
        if not REC_INDEX_MIN <= index <= REC_INDEX_MAX:
            continue
        headers.append(_record_header(raw, off, index))
    return headers


def _record_header(raw: bytes, off: int, index: int) -> dict:
    gold_at = off + REC_GOLD_OFF
    return {
        "index": index,
        "record_offset": off,
        "size_code": u32(raw, off + 4),
        "gold": u32(raw, gold_at),
        "level": u32(raw, REC_LEVEL_OFF + off),
        "kills": u32(raw, gold_at + REC_GOLD_KILLS),
        "deaths": u32(raw, gold_at + REC_GOLD_DEATHS),
        "assists": u32(raw, gold_at + REC_GOLD_ASSISTS),
        "assists_alt": u32(raw, gold_at + REC_GOLD_ASSISTS_ALT),
        "kills_alt": u32(raw, off + REC_LEVEL_KILLS_ALT),
        "deaths_alt": u32(raw, off + REC_LEVEL_DEATHS_ALT),
        "pointer": u64(raw, off + REC_POINTER_OFF),
        "counters": [u32(raw, off + REC_COUNTER_OFF + 4 * i)
                     for i in range(REC_COUNTERS)],
    }


def group_record_blocks(headers: list[dict],
                        gap: int = REC_BLOCK_GAP) -> list[list[dict]]:
    """Group headers into blocks; a new block starts after a >*gap* hole.

    A repeated index also starts a new block: after a seek the arena can hold
    two copies of the ten records close together, and each copy must stay a
    candidate block of its own (otherwise a stale copy would shadow the live
    one inside a merged block).
    """
    ordered = sorted(headers, key=lambda h: h["record_offset"])
    blocks: list[list[dict]] = []
    current_indexes: set[int] = set()
    for header in ordered:
        if (blocks and header["index"] not in current_indexes
                and header["record_offset"] - blocks[-1][-1]["record_offset"] <= gap):
            blocks[-1].append(header)
            current_indexes.add(header["index"])
        else:
            blocks.append([header])
            current_indexes = {header["index"]}
    return blocks


def _first_by_index(block: list[dict]) -> tuple[dict[int, dict], list[dict]]:
    by_index: dict[int, dict] = {}
    duplicates: list[dict] = []
    for header in block:
        if header["index"] in by_index:
            duplicates.append(header)
        else:
            by_index[header["index"]] = header
    return by_index, duplicates


# ---------------------------------------------------------------------------
# Pure layer: unit objects
# ---------------------------------------------------------------------------
def parse_unit(raw: bytes, off: int) -> dict | None:
    """Decode a unit object at *off*; ``None`` if it cannot be read safely."""
    if off < 0 or off + UNIT_NEED > len(raw):
        return None
    hero_id = u32(raw, off + UNIT_HERO_OFF)
    camp = u32(raw, off + UNIT_CAMP_OFF)
    entity = u32(raw, off + UNIT_ENTITY_OFF)
    entity_dup = u32(raw, off + UNIT_ENTITY_DUP_OFF)
    hp_current = u32(raw, off + UNIT_HP_CUR_OFF)
    hp_max = u32(raw, off + UNIT_HP_MAX_OFF)
    clock_off = (UNIT_CLOCK_ESCAPE_OFF if hero_id in UNIT_CLOCK_ESCAPE_HEROES
                 else UNIT_CLOCK_OFF)
    unit = {
        "unit_offset": off,
        "hero_id": hero_id,
        "hero": HERO_ID.get(hero_id),
        "camp": camp,
        "entity_id": entity,
        "entity_id_dup": entity_dup,
        "hp_current": hp_current,
        "hp_max": hp_max,
        "hp_ratio": round(hp_current / hp_max, 6) if hp_max else None,
        "clock_offset": clock_off,
        "clock_frame": u32(raw, off + clock_off),
        "clock_ms": u32(raw, off + clock_off + 4),
        "pos_x": i32(raw, off + UNIT_POS_OFF),
        "pos_y": i32(raw, off + UNIT_POS_OFF + 4),
        "pos_z": i32(raw, off + UNIT_POS_OFF + 8),
        "facing_x": i32(raw, off + UNIT_FACING_OFF),
        "facing_z": i32(raw, off + UNIT_FACING_OFF + 8),
    }
    unit["structure_ok"] = bool(
        unit["hero"] is not None
        and camp in (1, 2)
        and entity == entity_dup
        and 0 < entity < 1_000_000
    )
    unit["hp_ok"] = bool(HP_MAX_MIN <= hp_max <= HP_MAX_MAX
                         and 0 <= hp_current <= HP_CUR_MAX)
    return unit


def scan_unit_candidates(raw: bytes) -> list[dict]:
    """Structural scan for unit objects: entity pair + heroID + camp + hp max.

    The record pointers are authoritative; this scan exists to validate them
    (pointer vote for the arena base) and to recover when the capture start is
    offset from the arena base.  Units are 8-byte aligned on this build.
    """
    out: list[dict] = []
    if np is not None:
        count = len(raw) // 4
        need_u32 = UNIT_NEED // 4
        max_i = count - need_u32 - 1
        if max_i <= 0:
            return out
        a = np.frombuffer(raw, dtype="<u4", count=count)
        heroes = np.array(sorted(HERO_ID), dtype=np.uint32)
        chunk = 1 << 21  # 8 MiB of bytes per vector pass
        for i0 in range(0, max_i + 1, chunk):
            i1 = min(i0 + chunk, max_i + 1)
            i = np.arange(i0, i1, 2, dtype=np.int64)  # 8-byte stride
            if i.size == 0:
                continue
            hero = a[i + UNIT_HERO_OFF // 4]
            camp = a[i + UNIT_CAMP_OFF // 4]
            ent = a[i + UNIT_ENTITY_OFF // 4]
            ent_dup = a[i + UNIT_ENTITY_DUP_OFF // 4]
            hp_max = a[i + UNIT_HP_MAX_OFF // 4]
            hp_cur = a[i + UNIT_HP_CUR_OFF // 4]
            mask = (np.isin(hero, heroes)
                    & np.isin(camp, np.array([1, 2], dtype=np.uint32))
                    & (ent == ent_dup)
                    & (ent > 0) & (ent < 1_000_000)
                    & (hp_max >= HP_MAX_MIN) & (hp_max <= HP_MAX_MAX)
                    & (hp_cur <= HP_CUR_MAX))
            for j in np.nonzero(mask)[0]:
                off = int(i[j]) * 4
                unit = parse_unit(raw, off)
                if unit is not None and unit["structure_ok"] and unit["hp_ok"]:
                    out.append(unit)
    else:  # pragma: no cover - exercised only when numpy is unavailable
        for off in range(0, len(raw) - UNIT_NEED, 8):
            unit = parse_unit(raw, off)
            if unit is not None and unit["structure_ok"] and unit["hp_ok"]:
                out.append(unit)
    # Deduplicate by offset, keep insertion order.
    seen: set[int] = set()
    unique: list[dict] = []
    for unit in out:
        if unit["unit_offset"] in seen:
            continue
        seen.add(unit["unit_offset"])
        unique.append(unit)
    return unique


def vote_arena_bases(candidates: list[dict], pointers: list[int],
                     limit: int = 8) -> list[dict]:
    """Rank candidate arena bases as ``pointer - unit_offset`` over all pairs.

    Every pair votes for one base; the documented base wins with ten votes.  A
    single missing unit can tie the true base with a one-unit-shifted base, so
    the caller re-scores the top bases against the record indices (see
    :func:`decode_arena`).  Each entry carries ``matched``:
    ``{pointer: unit_file_offset}`` so the caller can parse the target unit.
    """
    votes: Counter[int] = Counter()
    offsets = {cand["unit_offset"] for cand in candidates}
    for pointer in pointers:
        for cand in candidates:
            votes[pointer - cand["unit_offset"]] += 1
    ranked: list[dict] = []
    for base, count in votes.most_common(limit):
        matched: dict[int, int] = {}
        for pointer in pointers:
            target = pointer - base
            if target in offsets:
                matched[pointer] = target
        ranked.append({"base": base, "votes": count, "matched": matched,
                       "matched_count": len(matched)})
    return ranked


def _pick_base(ranked: list[dict], candidates: list[dict],
               by_index: dict[int, dict]) -> dict | None:
    """Score the top base candidates: votes + pointer match + idx<->hero order."""
    if not ranked:
        return None
    by_offset = {cand["unit_offset"]: cand for cand in candidates}
    best: dict | None = None
    best_score = -1
    for entry in ranked[:8]:
        score = entry["votes"] * 10 + entry["matched_count"] * 5
        for index, header in by_index.items():
            target = entry["matched"].get(header["pointer"])
            if target is None:
                continue
            cand = by_offset.get(target)
            if cand is None:
                continue
            score += 10
            if cand["hero"] == ARENA_INDEX_HEROES[REC_INDEX_MAX - index]:
                score += 5
                if cand["hp_ok"]:
                    score += 1
        if score > best_score:
            best_score = score
            best = entry
    return best


# ---------------------------------------------------------------------------
# Pure layer: context header, capture plan, clocks, HP, roster
# ---------------------------------------------------------------------------
def find_ctx_headers_in_buffer(buf: bytes, buf_abs: int,
                               size_min: int = ARENA_SIZE_MIN,
                               size_max: int = ARENA_SIZE_MAX) -> list[dict]:
    """Find self-referencing arena headers (``u64(ctx)==ctx``, sane size)."""
    found: list[dict] = []
    if len(buf) < 0x10:
        return found
    candidates: list[int] = []
    if np is not None:
        count = len(buf) // 8
        q = np.frombuffer(buf, dtype="<u8", count=count)
        expected = np.uint64(buf_abs) + np.arange(count, dtype=np.uint64) * np.uint64(8)
        candidates = [int(k) * 8 for k in np.nonzero(q == expected)[0]]
    else:  # pragma: no cover - exercised only when numpy is unavailable
        for off in range(0, len(buf) - 0x10, 8):
            if u64(buf, off) == buf_abs + off:
                candidates.append(off)
    for off in candidates:
        if off + 0x10 > len(buf):
            continue
        size = u32(buf, off + 8)
        if not size_min <= size <= size_max:
            continue
        found.append({"offset": off, "ctx_abs": buf_abs + off, "size": size,
                      "self_pointer": u64(buf, off)})
    return found


def plan_capture(maps: list[Mapping], ctx_abs: int,
                 size: int) -> dict:
    """Page-aligned capture window for the arena containing *ctx_abs*."""
    mapping = mapping_of(maps, ctx_abs)
    if mapping is None:
        raise ProbeError(2, f"context {hx(ctx_abs)} is not inside any readable mapping")
    start = ctx_abs & ~0xFFF
    if start < mapping.start:
        start = mapping.start
    end = min(mapping.end, start + size)
    length = end - start
    if length <= 0:
        raise ProbeError(3, f"arena window empty for ctx {hx(ctx_abs)}")
    return {
        "capture_start": start,
        "capture_start_hex": hx(start),
        "ctx_offset": ctx_abs - start,
        "size": size,
        "length": length,
        "truncated": length < size,
        "mapping": _mapping_summary(mapping),
        "mapping_start": mapping.start,
        "mapping_end": mapping.end,
    }


def clock_summary(rows: list[dict]) -> dict:
    """Median replay clock over the resolved units, with stale-unit detection."""
    entries = []
    for row in rows:
        ms = row.get("clock_ms")
        frame = row.get("clock_frame")
        entries.append({"arena_index": row["arena_index"],
                        "hero": row.get("hero"),
                        "clock_frame": frame, "clock_ms": ms,
                        "stale": False})
    values = [e["clock_ms"] for e in entries
              if isinstance(e["clock_ms"], int) and e["clock_ms"] > 0]
    median = _median(values)
    stale: list[int] = []
    if median is not None:
        for _ in range(2):
            stale = [i for i, e in enumerate(entries)
                     if not isinstance(e["clock_ms"], int) or e["clock_ms"] <= 0
                     or abs(e["clock_ms"] - median) > CLOCK_STALE_DEVIATION_MS]
            fresh = [e["clock_ms"] for i, e in enumerate(entries) if i not in stale]
            new_median = _median(fresh)
            if new_median is None or new_median == median:
                break
            median = new_median
    for i in stale:
        entries[i]["stale"] = True
    valid = [e for i, e in enumerate(entries) if i not in stale]
    deviations = [abs(e["clock_ms"] - median) for e in valid
                  if isinstance(e["clock_ms"], int)]
    max_dev = max(deviations) if deviations else None
    frames = [e["clock_frame"] for e in valid
              if isinstance(e["clock_frame"], int) and e["clock_frame"] > 0]
    return {
        "median_ms": median,
        "median_s": round(median / 1000.0, 3) if median is not None else None,
        "median_frame": _median(frames),
        "tolerance_ms": CLOCK_TOLERANCE_MS,
        "stale_deviation_ms": CLOCK_STALE_DEVIATION_MS,
        "valid_count": len(valid),
        "stale_count": len(stale),
        "stale_indexes": [entries[i]["arena_index"] for i in stale],
        "max_deviation_ms": max_dev,
        "ok": bool(len(valid) >= CLOCK_MIN_VALID
                   and max_dev is not None and max_dev <= CLOCK_TOLERANCE_MS),
        "values": entries,
    }


def hp_summary(rows: list[dict]) -> dict:
    pairs = []
    good = 0
    over_max: list[int] = []
    zero: list[int] = []
    for row in rows:
        if row.get("hp_max") is None:
            continue
        current = row.get("hp_current")
        maximum = row.get("hp_max")
        ratio = row.get("hp_ratio")
        ok = bool(isinstance(current, int) and isinstance(maximum, int)
                  and HP_MAX_MIN <= maximum <= HP_MAX_MAX
                  and 0 <= current <= HP_CUR_MAX)
        good += 1 if ok else 0
        if isinstance(current, int) and isinstance(maximum, int):
            if current > maximum:
                over_max.append(row["arena_index"])
            if current == 0:
                zero.append(row["arena_index"])
        pairs.append({"arena_index": row["arena_index"], "hero": row.get("hero"),
                      "hp_current": current, "hp_max": maximum,
                      "hp_ratio": ratio, "ok": ok})
    return {"pairs": pairs, "valid_count": good, "over_max": over_max,
            "zero_current": zero, "ok": good == 10}


def build_roster(rows: list[dict], roster_doc: dict | None) -> list[dict]:
    """Join resolved units to the static idx order and an optional roster file."""
    by_index_players: dict[int, dict] = {}
    by_hero_players: dict[str, dict] = {}
    if isinstance(roster_doc, dict):
        raw_roster = roster_doc.get("roster")
        if isinstance(raw_roster, list):
            for item in raw_roster:
                hero = item.get("hero")
                if hero:
                    by_hero_players[hero] = {
                        "player": item.get("player"),
                        "camp": item.get("camp"),
                        "slot": item.get("slot"),
                        "entity_id": item.get("entityId")
                        or item.get("entity_id"),
                    }
        else:
            for key, item in roster_doc.items():
                try:
                    index = int(key)
                except (TypeError, ValueError):
                    continue
                if isinstance(item, dict):
                    by_index_players[index] = item
    out = []
    for row in rows:
        index = row["arena_index"]
        expected = ARENA_INDEX_HEROES[REC_INDEX_MAX - index]
        player = None
        if index in by_index_players:
            player = by_index_players[index].get("player")
        elif row.get("hero") in by_hero_players:
            player = by_hero_players[row["hero"]].get("player")
        out.append({
            "arena_index": index,
            "expected_hero": expected,
            "hero_id": row.get("hero_id"),
            "hero": row.get("hero"),
            "player": player,
            "camp": row.get("camp"),
            "entity_id": row.get("entity_id"),
            "record_offset": row.get("record_offset"),
            "unit_offset": row.get("unit_offset"),
        })
    return out


def _median(values: list[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return int(ordered[mid])
    return int(round((ordered[mid - 1] + ordered[mid]) / 2))


# ---------------------------------------------------------------------------
# Pure layer: decode one captured arena
# ---------------------------------------------------------------------------
def decode_arena(raw: bytes, *, capture_start_abs: int,
                 expected_ctx_abs: int | None = None,
                 roster: dict | None = None,
                 want_units: bool = True) -> dict:
    """Decode a captured arena buffer into records, units and summaries."""
    captured_len = len(raw)
    errors: list[str] = []

    headers = find_ctx_headers_in_buffer(
        raw[:min(captured_len, 0x10000)], capture_start_abs)
    chosen_header = None
    if expected_ctx_abs is not None:
        chosen_header = next((h for h in headers if h["ctx_abs"] == expected_ctx_abs), None)
    if chosen_header is None:
        chosen_header = next((h for h in headers if h["offset"] == CTX_PAGE_OFFSET), None)
    if chosen_header is None and headers:
        chosen_header = headers[0]
    if chosen_header is not None:
        ctx_abs = chosen_header["ctx_abs"]
        ctx_offset = chosen_header["offset"]
        arena_size = chosen_header["size"]
        header_found = True
    else:
        ctx_abs = expected_ctx_abs
        ctx_offset = (ctx_abs - capture_start_abs) if ctx_abs is not None else None
        arena_size = captured_len
        header_found = False
        errors.append("arena context header (self pointer + size) not found in capture")

    record_headers = find_record_headers(raw)
    blocks = group_record_blocks(record_headers)
    complete = [(b, _first_by_index(b)) for b in blocks]
    complete = [(b, by, dups) for (b, (by, dups)) in complete if len(by) == 10]

    chosen_block: list[dict] = []
    chosen_by_index: dict[int, dict] = {}
    chosen_dups: list[dict] = []
    stale_blocks = 0
    if complete:
        scored = []
        for block, by_index, dups in complete:
            score = _block_score(by_index, raw, capture_start_abs, want_units)
            latest = max(h["record_offset"] for h in block)
            scored.append((score, latest, block, by_index, dups))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        _score, _latest, chosen_block, chosen_by_index, chosen_dups = scored[0]
        stale_blocks = len(scored) - 1
        if stale_blocks:
            errors.append(f"{stale_blocks} extra complete record block(s) kept for "
                          f"diagnostics; selected the best-scoring block")
    elif blocks:
        block = max(blocks, key=lambda b: len(_first_by_index(b)[0]))
        chosen_block = block
        chosen_by_index, chosen_dups = _first_by_index(block)
        errors.append(f"no complete 10-record block; using {len(chosen_by_index)} "
                      f"records from the largest block")
    else:
        errors.append("no record headers found in capture")

    candidates: list[dict] = []
    arena_base_abs: int | None = capture_start_abs
    base_votes: int = 0
    pointer_targets: dict[int, int] = {}
    if want_units:
        candidates = scan_unit_candidates(raw)
        pointers = [h["pointer"] for h in chosen_by_index.values()]
        ranked = vote_arena_bases(candidates, pointers)
        chosen_base = _pick_base(ranked, candidates, chosen_by_index)
        if chosen_base is not None:
            arena_base_abs = chosen_base["base"]
            base_votes = chosen_base["votes"]
            pointer_targets = chosen_base["matched"]
        elif candidates:
            errors.append("unit candidates found but no pointer base vote")
    else:
        errors.append("records-only decode: unit objects were not resolved")

    rows: list[dict] = []
    for index in sorted(chosen_by_index, reverse=True):
        header = chosen_by_index[index]
        row = {
            "arena_index": index,
            "expected_hero": ARENA_INDEX_HEROES[REC_INDEX_MAX - index],
            "record_offset": header["record_offset"],
            "pointer": header["pointer"],
            "gold": header["gold"],
            "level": header["level"],
            "kills": header["kills"],
            "deaths": header["deaths"],
            "assists": header["assists"],
            "assists_alt": header["assists_alt"],
            "kills_alt": header["kills_alt"],
            "deaths_alt": header["deaths_alt"],
            "size_code": header["size_code"],
            "counters": header["counters"],
        }
        unit = None
        unit_file_offset = None
        if want_units and isinstance(header["pointer"], int) and header["pointer"] > 0:
            unit_file_offset = header["pointer"] - capture_start_abs
            unit = parse_unit(raw, unit_file_offset)
            if unit is None or not unit["structure_ok"]:
                unit = None
        if unit is not None:
            target = pointer_targets.get(header["pointer"])
            row.update({
                "unit_offset": unit["unit_offset"],
                "unit_offset_arena": (unit["unit_offset"] + capture_start_abs - arena_base_abs)
                if arena_base_abs is not None else None,
                "hero_id": unit["hero_id"],
                "hero": unit["hero"],
                "camp": unit["camp"],
                "entity_id": unit["entity_id"],
                "entity_id_dup": unit["entity_id_dup"],
                "hp_current": unit["hp_current"],
                "hp_max": unit["hp_max"],
                "hp_ratio": unit["hp_ratio"],
                "clock_offset": unit["clock_offset"],
                "clock_frame": unit["clock_frame"],
                "clock_ms": unit["clock_ms"],
                "pos_x": unit["pos_x"], "pos_y": unit["pos_y"],
                "pos_z": unit["pos_z"],
                "facing_x": unit["facing_x"], "facing_z": unit["facing_z"],
                "structure_ok": unit["structure_ok"],
                "hp_ok": unit["hp_ok"],
                "pointer_ok": target is not None,
                "pointer_in_arena": bool(
                    arena_base_abs is not None
                    and arena_base_abs <= header["pointer"]
                    < arena_base_abs + arena_size),
            })
        elif want_units:
            row.update({"unit_offset": None, "hero_id": None, "hero": None,
                        "camp": None, "entity_id": None, "hp_current": None,
                        "hp_max": None, "hp_ratio": None, "clock_frame": None,
                        "clock_ms": None, "structure_ok": False,
                        "hp_ok": False, "pointer_ok": False,
                        "pointer_in_arena": False})
        rows.append(row)

    units = [r for r in rows if r.get("unit_offset") is not None]
    clocks = clock_summary(units) if want_units else {}
    hp = hp_summary(units) if want_units else {}
    roster_rows = build_roster(rows, roster) if want_units else []

    structural = sum(1 for r in rows if r.get("structure_ok"))
    pointer_match = sum(1 for r in rows if r.get("pointer_ok"))
    roster_static = sum(1 for r in rows if r.get("hero") == r.get("expected_hero"))
    indices_present = sorted(chosen_by_index)
    expected_indices = sorted(REC_INDEX_BASE + i for i in REC_INDEXES)
    indices_complete = indices_present == expected_indices
    return {
        "arena": {
            "capture_start_abs": capture_start_abs,
            "capture_start_hex": hx(capture_start_abs),
            "ctx_abs": ctx_abs,
            "ctx_hex": hx(ctx_abs),
            "ctx_offset": ctx_offset,
            "expected_ctx_abs": expected_ctx_abs,
            "arena_size": arena_size,
            "arena_size_hex": hx(arena_size),
            "captured_len": captured_len,
            "header_found": header_found,
            "header_candidates": [{"offset": h["offset"], "ctx": hx(h["ctx_abs"]),
                                   "size": h["size"]} for h in headers[:8]],
            "base_abs": arena_base_abs,
            "base_hex": hx(arena_base_abs),
            "base_votes": base_votes,
            "base_delta": (arena_base_abs - capture_start_abs)
            if arena_base_abs is not None else None,
        },
        "records": {
            "headers_found": len(record_headers),
            "blocks": [[h["record_offset"] for h in block] for block in blocks],
            "complete_blocks": len(complete),
            "stale_blocks": stale_blocks,
            "duplicate_headers": len(chosen_dups),
            "chosen_block_offset": min((h["record_offset"] for h in chosen_block),
                                       default=None),
            "indices": indices_present,
            "indices_complete": indices_complete,
            "rows": rows,
        },
        "units": units,
        "clocks": clocks,
        "hp": hp,
        "roster": roster_rows,
        "structural_count": structural,
        "pointer_match": pointer_match,
        "roster_static_matches": roster_static,
        "errors": errors,
    }


def _block_score(by_index: dict[int, dict], raw: bytes, capture_start_abs: int,
                 want_units: bool) -> int:
    """Rank duplicate record blocks: structure + documented idx<->hero order."""
    if not want_units:
        return len(by_index)
    score = 0
    for index, header in by_index.items():
        unit_file_off = header["pointer"] - capture_start_abs
        unit = parse_unit(raw, unit_file_off)
        if unit is None or not unit["structure_ok"]:
            continue
        score += 10
        expected = ARENA_INDEX_HEROES[REC_INDEX_MAX - index]
        if unit["hero"] == expected:
            score += 5
        if unit["hp_ok"]:
            score += 1
    return score


# ---------------------------------------------------------------------------
# Pure layer: checks
# ---------------------------------------------------------------------------
def evaluate_snapshot(decoded: dict, mode: str = "all",
                      verify_stable: dict | None = None) -> list[dict]:
    """Turn a decoded snapshot into PASS/WARN/FAIL rows for *mode*."""
    rank = MODE_RANK.get(mode, 3)
    checks: list[dict] = []

    def add(name: str, level: str, detail: str) -> None:
        checks.append({"name": name, "level": level, "detail": detail})

    arena = decoded.get("arena", {})
    size = arena.get("arena_size") or 0
    captured = arena.get("captured_len") or 0
    if arena.get("header_found"):
        add("arena_header", "PASS",
            f"self pointer + size ok at ctx {arena.get('ctx_hex')} "
            f"(offset {hx(arena.get('ctx_offset'))})")
    else:
        add("arena_header", "FAIL",
            "arena context header (u64(ctx)==ctx, u32(ctx+8)==size) not found in capture")
    if sane_arena_size(size):
        if size == ARENA_SIZE_EXPECTED:
            add("arena_size", "PASS", f"arena size {size:#x} (0x1E00000)")
        else:
            add("arena_size", "WARN",
                f"arena size {size:#x} is sane but not the documented 0x1E00000")
    else:
        add("arena_size", "FAIL", f"arena size {size:#x} outside "
                                  f"0x{ARENA_SIZE_MIN:x}..0x{ARENA_SIZE_MAX:x}")
    if captured < size:
        add("arena_capture", "FAIL",
            f"captured {captured} of {size} bytes (short read / mapping clamp)")
    elif captured == size:
        add("arena_capture", "PASS", f"captured {captured} bytes (exact)")
    else:
        add("arena_capture", "WARN",
            f"captured {captured} bytes for declared size {size}")

    if rank < 1:
        return checks

    records = decoded.get("records", {})
    rows = records.get("rows", [])
    indices = records.get("indices", [])
    missing = [i for i in REC_INDEXES if (REC_INDEX_BASE + i) not in indices]
    if len(rows) == 10 and not missing:
        add("records", "PASS", "10/10 records, idx 1000000004..13 all present")
    else:
        add("records", "FAIL",
            f"{len(rows)}/10 records; missing idx {missing or 'none'}")
    if records.get("stale_blocks"):
        add("records_blocks", "WARN",
            f"{records['stale_blocks']} extra complete block(s); "
            f"{records['headers_found']} headers in {len(records.get('blocks', []))} blocks")
    else:
        add("records_blocks", "PASS",
            f"{records.get('headers_found')} header(s) in "
            f"{len(records.get('blocks', []))} block(s), no duplicates")
    bad_fields = [r["arena_index"] for r in rows
                  if not (isinstance(r.get("gold"), int) and 0 <= r["gold"] <= 200000
                          and isinstance(r.get("level"), int) and 1 <= r["level"] <= 30
                          and isinstance(r.get("kills"), int) and r["kills"] <= 200
                          and isinstance(r.get("deaths"), int) and r["deaths"] <= 200
                          and isinstance(r.get("assists"), int) and r["assists"] <= 200)]
    if not bad_fields:
        add("record_fields", "PASS", "gold/level/KDA plausible for all records")
    else:
        add("record_fields", "FAIL", f"implausible record fields at {bad_fields}")
    cross_mismatch = [r["arena_index"] for r in rows
                      if r.get("kills") != r.get("kills_alt")
                      or r.get("deaths") != r.get("deaths_alt")]
    if not cross_mismatch:
        add("record_crosscheck", "PASS",
            "kills/deaths duplicated fields agree (gold+0x158/+0xB8 vs "
            "+0x224/+0x228)")
    else:
        add("record_crosscheck", "WARN",
            f"variable-length shift: duplicated kills/deaths disagree at "
            f"{cross_mismatch}; both copies are kept in units.jsonl")

    if rank < 2:
        return checks

    structural = decoded.get("structural_count", 0)
    if structural == 10:
        add("units", "PASS", "10/10 unit objects structurally valid "
                             "(heroID/camp/entity pair/HP max)")
    else:
        add("units", "FAIL", f"{structural}/10 unit objects valid")
    pointer_match = decoded.get("pointer_match", 0)
    arena_info = decoded.get("arena", {})
    base = arena_info.get("base_abs")
    if pointer_match == 10:
        add("pointer_resolution", "PASS",
            f"10/10 records resolve to a unit at arena base {hx(base)} "
            f"({arena_info.get('base_votes')} vote(s), delta "
            f"{arena_info.get('base_delta')})")
    else:
        add("pointer_resolution", "FAIL",
            f"{pointer_match}/10 record pointers resolve to a scanned unit "
            f"(base {hx(base)})")
    bad_pointers = [r["arena_index"] for r in rows if not r.get("pointer_in_arena")]
    if not bad_pointers:
        add("pointer_range", "PASS", "all record pointers inside [base, base+size)")
    else:
        add("pointer_range", "FAIL", f"pointers outside the arena at {bad_pointers}")
    camps = Counter(r.get("camp") for r in rows if r.get("structure_ok"))
    heroes = [r.get("hero") for r in rows if r.get("structure_ok")]
    if camps == {1: 5, 2: 5} and len(set(heroes)) == 10:
        add("unit_identity", "PASS", "5 blue + 5 red, 10 distinct heroes")
    else:
        add("unit_identity", "WARN",
            f"camp split {dict(camps)}, distinct heroes {len(set(heroes))}")

    if rank < 3:
        return checks

    roster_static = decoded.get("roster_static_matches", 0)
    if roster_static == 10:
        add("roster_order", "PASS",
            "pointer-resolved units match the documented idx 13..4 order")
    else:
        add("roster_order", "WARN",
            f"{roster_static}/10 match the documented idx order; the pointer is "
            f"authoritative, the static order is only a cross-check")

    clocks = decoded.get("clocks", {})
    if clocks.get("ok"):
        detail = (f"median {clocks.get('median_s')}s frame "
                  f"{clocks.get('median_frame')}; {clocks.get('valid_count')}/10 "
                  f"valid, max dev {clocks.get('max_deviation_ms')} ms")
        if clocks.get("stale_count"):
            detail += f"; stale idx {clocks.get('stale_indexes')}"
            add("clock_consistency", "WARN", detail)
        else:
            add("clock_consistency", "PASS", detail)
    else:
        add("clock_consistency", "FAIL",
            f"{clocks.get('valid_count')}/10 valid clocks, max dev "
            f"{clocks.get('max_deviation_ms')} ms (tolerance "
            f"{CLOCK_TOLERANCE_MS} ms); stale idx {clocks.get('stale_indexes')}")

    hp = decoded.get("hp", {})
    if hp.get("ok"):
        detail = "10/10 normalized HP pairs (+0x08/+0x10)"
        if hp.get("over_max"):
            detail += f"; ratio>1 at {hp['over_max']}"
            add("hp_pairs", "WARN", detail)
        else:
            add("hp_pairs", "PASS", detail)
        if hp.get("zero_current"):
            add("hp_zero", "WARN", f"hp_current==0 at {hp['zero_current']} "
                                   f"(dead unit or rounding)")
    else:
        add("hp_pairs", "FAIL", f"{hp.get('valid_count')}/10 valid HP pairs")

    if verify_stable is not None:
        if verify_stable.get("stable"):
            add("freeze_stable", "PASS", verify_stable.get("detail", "unit window "
                                                          "unchanged after capture"))
        else:
            add("freeze_stable", "WARN",
                verify_stable.get("detail", "unit window changed between capture and "
                                            "re-read"))
    return checks


def checks_ok(checks: list[dict]) -> bool:
    return not any(c["level"] == "FAIL" for c in checks)


def checks_status(checks: list[dict]) -> str:
    if any(c["level"] == "FAIL" for c in checks):
        return "failed"
    if any(c["level"] == "WARN" for c in checks):
        return "degraded"
    return "ok"


# ---------------------------------------------------------------------------
# Device layer: adb plumbing
# ---------------------------------------------------------------------------
def _adb_cmd(exe: str, serial: str | None, *args: str,
             timeout: int = 20) -> bytes:
    cmd = [exe] + (["-s", serial] if serial else []) + list(args)
    try:
        return subprocess.run(cmd, capture_output=True,
                              timeout=timeout).stdout
    except (subprocess.TimeoutExpired, OSError):
        return b""


def pick_serial(exe: str, serials: list[str]) -> tuple[str | None, list[dict]]:
    """Connect to the first reachable adb serial; diagnostics for each try."""
    notes: list[dict] = []
    for serial in serials:
        connect_out = _adb_cmd(exe, None, "connect", serial, timeout=15)
        probe = _adb_cmd(exe, serial, "shell", "echo", "probe-ok", timeout=20)
        ok = b"probe-ok" in probe
        notes.append({
            "serial": serial,
            "connect": connect_out.decode("utf-8", "replace").strip()[:160],
            "probe_ok": ok,
        })
        if ok:
            return serial, notes
    return None, notes


def ensure_root(adb: Adb) -> dict:
    ident = adb.shell("id", timeout=15).decode("utf-8", "replace").strip()
    root = "uid=0" in ident
    attempts = [{"step": "id", "output": ident[:200], "root": root}]
    if not root:
        _adb_cmd(adb.exe, adb.serial, "root", timeout=60)
        time.sleep(1.5)
        _adb_cmd(adb.exe, None, "connect", adb.serial, timeout=15)
        ident = adb.shell("id", timeout=15).decode("utf-8", "replace").strip()
        root = "uid=0" in ident
        attempts.append({"step": "adb root", "output": ident[:200], "root": root})
    return {"root": root, "attempts": attempts}


def find_game_pid(adb: Adb, package: str) -> tuple[int, str]:
    pids = adb.pids(package)
    if pids:
        return pids[0], f"pidof {package} -> {pids}"
    ps = adb.shell("ps", "-A", timeout=20).decode("utf-8", "replace")
    for line in ps.splitlines():
        if package in line or "tmgp.sgame" in line or "cent.tmgp.sgame" in line:
            parts = line.split()
            for token in parts:
                if token.isdigit():
                    return int(token), f"ps -A fallback -> {line.strip()[:120]}"
    raise ProbeError(2, f"game process {package} not found",
                     package=package, pidof=pids)


def locate_gamecore_base(maps: list[Mapping]) -> int:
    candidates = [m for m in maps if m.path.endswith("/libGameCore.so")]
    if not candidates:
        candidates = [m for m in maps if "libGameCore.so" in m.path]
    if not candidates:
        raise ProbeError(2, "libGameCore.so is not mapped (game not running?)",
                         module_paths=[m.path for m in maps if ".so" in m.path][:40])
    return min(m.start for m in candidates)


def process_state(adb: Adb, pid: int) -> str | None:
    raw = adb.shell("cat", f"/proc/{pid}/stat", timeout=15)
    text = raw.decode("utf-8", "replace")
    close = text.rfind(")")
    if close < 0 or close + 2 >= len(text):
        return None
    return text[close + 2:close + 3]


def set_process_state(adb: Adb, pid: int, stop: bool, settle: float = 0.3) -> str | None:
    signal = "-STOP" if stop else "-CONT"
    repeats = 1 if stop else 4
    for _ in range(repeats):
        adb.shell("kill", signal, str(pid), timeout=15)
        time.sleep(settle)
    return process_state(adb, pid)


# ---------------------------------------------------------------------------
# Device layer: arena location (chain + fallbacks)
# ---------------------------------------------------------------------------
def _verify_ctx(reader: Reader, addr: int,
                size_hint: int | None = None) -> dict | None:
    """Verify *addr* is an arena context header; ``None`` if it is not."""
    if addr <= 0 or not reader.readable(addr, 0x20):
        return None
    self_ptr = reader.u64(addr)
    size = reader.u32(addr + 8)
    if self_ptr == addr and size is not None and sane_arena_size(size):
        if size_hint is None or abs(size - size_hint) <= size_hint // 4:
            return {"ctx": addr, "size": size, "evidence": "self_pointer"}
    return None


def read_context_chain(reader: Reader, gc_base: int) -> dict:
    """Follow the documented three-hop chain and validate the result."""
    slot = gc_base + GC_CHAIN_OFFSET
    pointer = slot
    hops: list[dict] = []
    error = None
    for hop in range(CHAIN_HOPS):
        value = reader.u64(pointer)
        hops.append({"hop": hop, "read_at": pointer, "read_at_hex": hx(pointer),
                     "value": value, "value_hex": hx(value)})
        if value is None:
            error = f"hop {hop}: {hx(pointer)} unreadable"
            break
        if value == 0:
            error = f"hop {hop}: {hx(pointer)} is null"
            break
        pointer = value
    result: dict = {"slot": slot, "slot_hex": hx(slot), "hops": hops,
                    "ctx": None, "ctx_hex": None, "size": None,
                    "error": error, "verified": None}
    if error is None:
        verified = _verify_ctx(reader, pointer)
        if verified is not None:
            result.update({"ctx": pointer, "ctx_hex": hx(pointer),
                           "size": verified["size"], "verified": verified,
                           "method": "chain"})
        else:
            result["error"] = (f"hop 3 value {hx(pointer)} is not a verified "
                               f"arena context header")
    return result


def _scan_qwords_in_ranges(data: bytes, data_abs: int,
                           ranges: list[tuple[int, int]]) -> list[int]:
    """All u64 values in *data* that point inside any of *ranges*."""
    if not ranges:
        return []
    out: list[int] = []
    if np is not None:
        count = len(data) // 8
        values = np.frombuffer(data, dtype="<u8", count=count)
        mask = np.zeros(count, dtype=bool)
        value_mask = np.zeros(count, dtype=bool)
        for start, end in ranges:
            mask |= (values >= np.uint64(start)) & (values < np.uint64(end))
        value_mask |= mask
        for value in np.nonzero(value_mask)[0]:
            out.append(int(values[value]))
    else:  # pragma: no cover - exercised only when numpy is unavailable
        for off in range(0, len(data) - 7, 8):
            value = u64(data, off)
            for start, end in ranges:
                if start <= value < end:
                    out.append(value)
                    break
    return out


def _scan_size_constant_candidates(data: bytes,
                                   size: int = ARENA_SIZE_EXPECTED) -> list[tuple[int, int]]:
    """Find ``u32 == arena size`` fields and the qword written just before them.

    Used by the .data fallback: an arena size constant in module data is often
    preceded by the context/arena pointer (既有校准 header layout).  Returns
    ``(byte_offset_of_size, preceding_u64)`` pairs with ``offset >= 8``.
    """
    out: list[tuple[int, int]] = []
    if len(data) < 12:
        return out
    if np is not None:
        count = len(data) // 4
        a = np.frombuffer(data, dtype="<u4", count=count)
        for k in np.nonzero(a == np.uint32(size))[0]:
            off = int(k) * 4
            if off >= 8:
                out.append((off, u64(data, off - 8)))
    else:  # pragma: no cover - exercised only when numpy is unavailable
        for off in range(8, len(data) - 3, 4):
            if u32(data, off) == size:
                out.append((off, u64(data, off - 8)))
    return out


def _arena_like_regions(maps: list[Mapping]) -> list[Mapping]:
    """Large rw mappings that could hold the self-relative arena."""
    out = []
    for m in maps:
        if not m.perms.startswith("rw") or m.size < ARENA_SIZE_MIN:
            continue
        path = m.path or ""
        if path.endswith((".so", ".apk", ".dex", ".jar", ".oat", ".vdex",
                          ".art", ".db", ".ttf")):
            continue
        out.append(m)
    return out


def _iter_device_chunks(adb: Adb, pid: int, start: int, length: int,
                        chunk: int = 1 << 22):
    addr = start
    end = start + length
    while addr < end:
        take = min(chunk, end - addr)
        data = adb.read_mem(pid, addr, take)
        if data is None:
            return
        yield addr, data
        addr += take


def fallback_module_pointers(adb: Adb, pid: int, maps: list[Mapping],
                             reader: Reader, gc_base: int,
                             size_hint: int | None,
                             module_scan_mb: int = 64) -> tuple[dict | None, dict]:
    """Fallback A: find heap pointers into a 30 MiB rw mapping in module data.

    The documented chain lives in libGameCore's .data; if the chain slot moved
    we can still find *any* .data qword that points into an arena-like mapping
    and verify whether the pointed page carries the self-referencing header.
    """
    diag: dict = {"method": "fallback_module_pointers", "module_base": hx(gc_base),
                  "regions": [], "pointers": 0, "candidates": [], "errors": []}
    arena_regions = _arena_like_regions(maps)
    if not arena_regions:
        diag["errors"].append("no large rw mapping (>= 1 MiB) for the arena")
        return None, diag
    ranges = [(m.start, m.end) for m in arena_regions]
    diag["arena_like_regions"] = [_mapping_summary(m) for m in arena_regions[:8]]

    def permission_rank(m: Mapping) -> int:
        if m.perms.startswith("rw"):
            return 0  # .data/.bss holds the chain slot and arena pointers
        if m.perms.startswith("r-"):
            return 1
        return 2

    module_maps = sorted((m for m in maps
                          if "libGameCore.so" in m.path and m.perms.startswith("r")),
                         key=permission_rank)
    slot = gc_base + GC_CHAIN_OFFSET
    window = 0x100000  # 1 MiB around the chain slot: cheap, highest signal
    targets: list[tuple[int, int, str]] = [
        (max(0, slot - window), 2 * window, "chain_slot_window")]
    for m in module_maps:
        if any(start <= m.start < start + length for start, length, _ in targets):
            continue
        targets.append((m.start, m.size,
                        "module_rw" if m.perms.startswith("rw") else
                        "module_readable"))
    budget = module_scan_mb * 1048576
    pointers: set[int] = set()
    size_constants = 0
    scanned = 0
    for start, length, kind in targets:
        remaining = budget - scanned
        if remaining <= 0:
            break
        region_started = time.time()
        region_bytes = 0
        for addr, data in _iter_device_chunks(adb, pid, start,
                                              min(length, remaining)):
            pointers.update(_scan_qwords_in_ranges(data, addr, ranges))
            for _off, candidate in _scan_size_constant_candidates(data):
                size_constants += 1
                if candidate and any(lo <= candidate < hi for lo, hi in ranges):
                    pointers.add(candidate)
            scanned += len(data)
            region_bytes += len(data)
            if len(pointers) > 4096 or scanned >= budget:
                break
        diag["regions"].append({
            "kind": kind, "start": hx(start), "length": length,
            "bytes": region_bytes, "pointer_hits": len(pointers),
            "seconds": round(time.time() - region_started, 2)})
        if len(pointers) > 4096 or scanned >= budget:
            diag["errors"].append(f"module pointer scan stopped at {scanned} bytes "
                                  f"(budget {budget})")
            break
    diag["pointers"] = len(pointers)
    diag["size_constants"] = size_constants
    verified: dict | None = None
    for pointer in sorted(pointers)[:512]:
        verdict = _verify_ctx(reader, pointer, size_hint)
        page = (pointer & ~0xFFF) + CTX_PAGE_OFFSET
        if verdict is None and page != pointer:
            verdict = _verify_ctx(reader, page, size_hint)
            source = "page+0xff0"
        else:
            source = "pointer"
        entry = {"pointer": pointer, "pointer_hex": hx(pointer), "via": source,
                 "verified": verdict}
        diag["candidates"].append(entry)
        if verdict is not None and verified is None:
            verified = verdict
    diag["verified"] = verified
    if verified is not None:
        return {"ctx": verified["ctx"], "size": verified["size"],
                "evidence": verified["evidence"]}, diag
    diag["errors"].append(f"{len(pointers)} .data pointer(s) into arena-like "
                          f"mappings, none verified as a context header")
    return None, diag


def fallback_mapping_scan(adb: Adb, pid: int, maps: list[Mapping],
                          size_hint: int | None) -> tuple[dict | None, dict]:
    """Fallback B: scan the first pages of large rw mappings for the header."""
    diag: dict = {"method": "fallback_mapping_scan", "regions": [],
                  "candidates": [], "errors": []}
    verified: dict | None = None
    for m in sorted(_arena_like_regions(maps), key=lambda x: -x.size)[:16]:
        window = min(0x4000, m.size)
        data = adb.read_mem(pid, m.start, window)
        if data is None:
            diag["regions"].append({"start": hx(m.start), "size": m.size,
                                    "path": m.path, "read": False})
            continue
        headers = find_ctx_headers_in_buffer(data, m.start)
        diag["regions"].append({"start": hx(m.start), "size": m.size,
                                "path": m.path, "read": True,
                                "headers": [{"offset": h["offset"],
                                             "ctx": hx(h["ctx_abs"]),
                                             "size": h["size"]}
                                            for h in headers]})
        for header in headers:
            if not sane_arena_size(header["size"]):
                continue
            if size_hint is not None and abs(header["size"] - size_hint) > size_hint // 4:
                continue
            diag["candidates"].append(header)
            if verified is None:
                verified = header
    if verified is not None:
        return {"ctx": verified["ctx_abs"], "size": verified["size"],
                "evidence": "mapping_header_scan"}, diag
    diag["errors"].append("no self-referencing arena header in the first 0x4000 "
                          "bytes of any large rw mapping")
    return None, diag


def locate_arena(adb: Adb, pid: int, maps: list[Mapping], gc_base: int,
                 size_hint: int | None = None,
                 module_scan_mb: int = 64) -> dict:
    """Locate the live arena context; chain first, then documented fallbacks."""
    reader = Reader(adb, pid, maps)
    chain = read_context_chain(reader, gc_base)
    diagnostics: list[str] = []
    diagnostics.append(
        f"chain slot {chain['slot_hex']} (+0x{GC_CHAIN_OFFSET:x}): "
        + " -> ".join(h["value_hex"] or "None" for h in chain["hops"]))
    if chain.get("ctx"):
        mapping = mapping_of(maps, chain["ctx"])
        diagnostics.append(f"chain verified ctx {chain['ctx_hex']} size "
                           f"{chain['size']:#x}; mapping "
                           f"{hx(mapping.start) if mapping else None}"
                           f"-{hx(mapping.end) if mapping else None}")
        return {"method": "chain", "ctx": chain["ctx"], "size": chain["size"],
                "chain": _chain_json(chain), "fallbacks": [],
                "diagnostics": diagnostics,
                "mapping": _mapping_summary(mapping)}

    diagnostics.append(f"chain failed: {chain.get('error')}; trying fallbacks")
    fallbacks: list[dict] = []
    # Fallback C: chain hop values may already be an arena base / context.
    for hop in reversed(chain["hops"]):
        value = hop.get("value")
        if not value:
            continue
        for candidate in (value, (value & ~0xFFF) + CTX_PAGE_OFFSET):
            verdict = _verify_ctx(reader, candidate, size_hint)
            fallbacks.append({"method": "chain_hop_verify",
                              "candidate": hx(candidate),
                              "verified": verdict})
            if verdict is not None:
                diagnostics.append(f"fallback: chain hop value {hx(candidate)} "
                                   f"verified as ctx")
                return {"method": "fallback_chain_hop", "ctx": verdict["ctx"],
                        "size": verdict["size"], "chain": _chain_json(chain),
                        "fallbacks": fallbacks, "diagnostics": diagnostics,
                        "mapping": _mapping_summary(mapping_of(maps, verdict["ctx"]))}

    found, module_diag = fallback_module_pointers(
        adb, pid, maps, reader, gc_base, size_hint, module_scan_mb)
    fallbacks.append(module_diag)
    for entry in module_diag.get("candidates", [])[:8]:
        diagnostics.append(
            f"  .data candidate {entry['pointer_hex']} via {entry['via']} -> "
            f"{'VERIFIED' if entry['verified'] else 'rejected'}")
    for error in module_diag.get("errors", []):
        diagnostics.append(f"  .data scan: {error}")
    if found is not None:
        diagnostics.append(f"fallback: module .data pointer -> ctx {hx(found['ctx'])}")
        return {"method": "fallback_module_pointers", "ctx": found["ctx"],
                "size": found["size"], "chain": _chain_json(chain),
                "fallbacks": fallbacks, "diagnostics": diagnostics,
                "mapping": _mapping_summary(mapping_of(maps, found["ctx"]))}

    found, mapping_diag = fallback_mapping_scan(adb, pid, maps, size_hint)
    fallbacks.append(mapping_diag)
    for error in mapping_diag.get("errors", []):
        diagnostics.append(f"  mapping scan: {error}")
    if found is not None:
        diagnostics.append(f"fallback: mapping header scan -> ctx {hx(found['ctx'])}")
        return {"method": "fallback_mapping_scan", "ctx": found["ctx"],
                "size": found["size"], "chain": _chain_json(chain),
                "fallbacks": fallbacks, "diagnostics": diagnostics,
                "mapping": _mapping_summary(mapping_of(maps, found["ctx"]))}

    raise ProbeError(2, "arena context not located (chain and two fallbacks failed)",
                     chain=_chain_json(chain), fallbacks=fallbacks,
                     diagnostics=diagnostics)


def _chain_json(chain: dict) -> dict:
    return {"slot": chain["slot"], "slot_hex": chain["slot_hex"],
            "hops": [{"hop": h["hop"], "read_at_hex": h["read_at_hex"],
                      "value_hex": h["value_hex"]} for h in chain["hops"]],
            "ctx_hex": chain.get("ctx_hex"), "size": chain.get("size"),
            "error": chain.get("error")}


# ---------------------------------------------------------------------------
# Device layer: capture
# ---------------------------------------------------------------------------
def read_arena_chunks(adb: Adb, pid: int, start: int, length: int,
                      chunk_bytes: int, retries: int,
                      timeout: int = 180) -> tuple[bytes, dict]:
    """Chunked ``dd if=/proc/<pid>/mem`` read with per-chunk retries."""
    if length <= 0:
        raise ProbeError(3, f"empty capture window at {hx(start)}")
    out = bytearray()
    chunk_rows: list[dict] = []
    failures: list[dict] = []
    addr = start
    end = start + length
    started = time.time()
    while addr < end:
        take = min(chunk_bytes, end - addr)
        data = None
        attempts = 0
        chunk_started = time.time()
        for attempt in range(1, retries + 1):
            attempts = attempt
            data = adb.read_mem(pid, addr, take, timeout=timeout)
            if data is not None and len(data) == take:
                break
            data = None
            time.sleep(min(0.5 * attempt, 2.0))
        if data is None:
            failures.append({"addr": addr, "addr_hex": hx(addr), "len": take,
                             "attempts": attempts})
            raise ProbeError(
                3, f"cannot read {take} bytes at {hx(addr)} after {retries} attempts",
                chunk_rows=chunk_rows, failures=failures)
        out += data
        chunk_rows.append({"addr": hx(addr), "len": take, "attempts": attempts,
                           "seconds": round(time.time() - chunk_started, 2)})
        addr += take
    diag = {"start": start, "start_hex": hx(start), "length": length,
            "chunk_bytes": chunk_bytes, "chunks": len(chunk_rows),
            "retries": retries, "seconds": round(time.time() - started, 2),
            "chunk_rows": chunk_rows, "failures": failures}
    return bytes(out), diag


def verify_stable(adb: Adb, pid: int, raw: bytes, capture_start_abs: int,
                  unit_offset: int | None, window: int = UNIT_PREFIX) -> dict:
    """Re-read one unit window and compare it with the capture (paused check)."""
    if unit_offset is None:
        return {"stable": None, "detail": "no resolved unit to re-read"}
    take = min(window, len(raw) - unit_offset)
    if take <= 0:
        return {"stable": None, "detail": "unit window outside the capture"}
    before = raw[unit_offset:unit_offset + take]
    after = adb.read_mem(pid, capture_start_abs + unit_offset, take)
    if after is None:
        return {"stable": None, "detail": "re-read of the unit window failed"}
    if after == before:
        return {"stable": True,
                "detail": f"unit window ({take} B at {hx(capture_start_abs + unit_offset)}) "
                          f"unchanged after capture"}
    diff = sum(1 for a, b in zip(before, after) if a != b)
    return {"stable": False,
            "detail": f"unit window changed after capture ({diff}/{take} bytes "
                      f"differ; replay may not be paused)"}


# ---------------------------------------------------------------------------
# Probe orchestration
# ---------------------------------------------------------------------------
@dataclass
class Options:
    adb: str = ADB_DEFAULT
    serial: str = SERIAL_DEFAULT
    serial_alts: tuple[str, ...] = SERIAL_ALT_DEFAULT
    package: str = PACKAGE_DEFAULT
    pid: int | None = None
    out: Path | None = None
    label: str = ""
    mode: str = "all"
    freeze: bool = False
    freeze_settle: float = 0.3
    keep_arena: bool = True
    unit_blobs: bool = True
    chunk_bytes: int = 4 * 1024 * 1024
    retries: int = 3
    timeout: int = 180
    overwrite: bool = False
    locate_only: bool = False
    verify_stable_window: bool = True
    roster: Path | None = None
    module_scan_mb: int = 64
    quiet: bool = False
    serial_notes: list[dict] = field(default_factory=list)
    root_info: dict = field(default_factory=dict)


def _log(opt: Options, message: str) -> None:
    if not opt.quiet:
        print(message, flush=True)


def _load_roster(path: Path | None) -> tuple[dict | None, dict | None]:
    if path is None:
        return None, None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, {"path": str(path), "error": str(exc)}
    return doc, {"path": str(path), "entries": len(doc.get("roster", doc))
                 if isinstance(doc, dict) else 0}


def run(adb: Adb, opt: Options) -> dict:
    """Full probe: locate -> capture -> decode -> validate -> persist."""
    started = time.time()
    label = opt.label or time.strftime("snap_%Y%m%d_%H%M%S")
    roster_doc, roster_info = _load_roster(opt.roster)

    pid, pid_note = (opt.pid, "explicit --pid") if opt.pid else \
        find_game_pid(adb, opt.package)
    print_note = f"pid={pid} ({pid_note})"
    _log(opt, f"[engine_live_probe] {print_note}")

    maps = adb.read_maps(pid)
    if not maps:
        raise ProbeError(2, f"empty /proc/{pid}/maps", pid=pid)
    gc_base = locate_gamecore_base(maps)
    _log(opt, f"  libGameCore base {hx(gc_base)}; {len(maps)} mappings")

    size_hint = None
    locate = locate_arena(adb, pid, maps, gc_base, size_hint,
                          module_scan_mb=opt.module_scan_mb)
    for line in locate["diagnostics"]:
        _log(opt, f"  locate: {line}")
    _log(opt, f"  locate: method={locate['method']} ctx={hx(locate['ctx'])} "
              f"size={locate['size']:#x}")

    capture_plan = plan_capture(maps, locate["ctx"], locate["size"])
    for warning in ("truncated",):
        if capture_plan[warning]:
            _log(opt, "  locate: capture window truncated by the mapping end "
                      f"({capture_plan['length']} of {locate['size']} bytes)")

    base_meta = {
        "schema": SCHEMA,
        "tool": TOOL_NAME,
        "label": label,
        "mode": opt.mode,
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "device": {
            "adb": opt.adb,
            "serial": opt.serial,
            "serial_notes": opt.serial_notes,
            "root": opt.root_info,
            "package": opt.package,
            "pid": pid,
            "pid_note": pid_note,
        },
        "maps": {
            "regions": len(maps),
            "libgamecore_base": gc_base,
            "libgamecore_base_hex": hx(gc_base),
            "arena_mapping": _mapping_summary(mapping_of(maps, locate["ctx"])),
        },
        "locate": locate,
        "capture_plan": capture_plan,
        "boundary": "read-only /proc/<pid>/mem probe; bytes kept under data/, "
                    "never committed; no game memory was written",
    }

    if opt.locate_only:
        meta = dict(base_meta)
        meta.update({"status": "located", "checks": [], "failures": [],
                     "elapsed_s": round(time.time() - started, 2)})
        _write_outputs(opt, meta=meta, arena=None, decoded=None)
        _log(opt, f"  locate-only: ctx={hx(locate['ctx'])} size={locate['size']:#x} "
                  f"-> {opt.out or '(not written)'}")
        return {"status": "located", "meta": meta, "exit_code": 0,
                "decoded": None, "checks": []}

    state_before = process_state(adb, pid)
    frozen = False
    capture_diag: dict = {}
    raw = b""
    try:
        if opt.freeze:
            state_after_freeze = set_process_state(adb, pid, True, opt.freeze_settle)
            frozen = state_after_freeze == "T"
            _log(opt, f"  freeze: kill -STOP; process state={state_after_freeze}")
            if not frozen:
                _log(opt, "  freeze: WARN process did not enter state T; "
                          "capturing unfrozen")
        else:
            _log(opt, "  freeze: off (paused replay is expected to be static; "
                      "use --freeze to STOP the process during capture)")
        _log(opt, f"  capture: {capture_plan['length']} bytes from "
                  f"{capture_plan['capture_start_hex']} in "
                  f"{opt.chunk_bytes // 1024} KiB chunks")
        raw, capture_diag = read_arena_chunks(
            adb, pid, capture_plan["capture_start"], capture_plan["length"],
            opt.chunk_bytes, opt.retries, opt.timeout)
        _log(opt, f"  capture: {len(raw)} bytes in {capture_diag['seconds']}s "
                  f"({capture_diag['chunks']} chunks)")
    finally:
        if frozen:
            resumed = set_process_state(adb, pid, False)
            _log(opt, f"  freeze: kill -CONT; process state={resumed}")

    state_after = process_state(adb, pid)
    want_units = MODE_RANK.get(opt.mode, 3) >= 2
    decoded = decode_arena(
        raw,
        capture_start_abs=capture_plan["capture_start"],
        expected_ctx_abs=locate["ctx"],
        roster=roster_doc,
        want_units=want_units,
    )
    decoded["arena"]["sha256"] = sha256_hex(raw)
    decoded["arena"]["capture_plan"] = capture_plan
    decoded["arena"]["capture"] = capture_diag
    decoded["arena"]["frozen"] = frozen
    decoded["arena"]["process_state_before"] = state_before
    decoded["arena"]["process_state_after"] = state_after

    verify = None
    if opt.verify_stable_window and want_units and decoded["units"]:
        first = min(decoded["units"], key=lambda u: u["unit_offset"])
        verify = verify_stable(adb, pid, raw, capture_plan["capture_start"],
                               first["unit_offset"])
        decoded["verify_stable"] = verify

    checks = evaluate_snapshot(decoded, opt.mode, verify)
    status = checks_status(checks)
    failures = [f"{c['name']}: {c['detail']}" for c in checks
                if c["level"] == "FAIL"]
    meta = dict(base_meta)
    meta.update({
        "status": status,
        "arena": decoded["arena"],
        "records": {k: v for k, v in decoded["records"].items() if k != "rows"},
        "record_rows": decoded["records"]["rows"],
        "units_count": len(decoded["units"]),
        "clocks": decoded["clocks"],
        "hp": decoded["hp"],
        "roster": decoded["roster"],
        "roster_source": roster_info,
        "structural_count": decoded["structural_count"],
        "pointer_match": decoded["pointer_match"],
        "roster_static_matches": decoded["roster_static_matches"],
        "errors": decoded["errors"],
        "checks": checks,
        "failures": failures,
        "elapsed_s": round(time.time() - started, 2),
    })
    units_jsonl = decoded["units"] if want_units else None
    _write_outputs(opt, meta=meta, arena=raw, decoded=decoded,
                   units_jsonl=units_jsonl)
    exit_code = 0 if checks_ok(checks) else 4
    return {"status": status, "meta": meta, "exit_code": exit_code,
            "decoded": decoded, "checks": checks}


def _write_outputs(opt: Options, *, meta: dict, arena: bytes | None,
                   decoded: dict | None,
                   units_jsonl: list[dict] | None = None) -> dict:
    """Persist meta.json, arena.bin, units.jsonl and unit prefixes."""
    paths: dict = {"out": str(opt.out) if opt.out else None}
    if opt.out is None:
        return paths
    out = Path(opt.out)
    out.mkdir(parents=True, exist_ok=True)
    meta_path = out / "meta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    paths["meta"] = str(meta_path)
    if arena is not None and opt.keep_arena:
        arena_path = out / "arena.bin"
        arena_path.write_bytes(arena)
        paths["arena"] = str(arena_path)
    if units_jsonl is not None:
        units_path = out / "units.jsonl"
        with units_path.open("w", encoding="utf-8") as fh:
            for row in units_jsonl:
                fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        paths["units"] = str(units_path)
    if decoded is not None and opt.unit_blobs and arena is not None:
        blob_dir = out / "units"
        blob_dir.mkdir(exist_ok=True)
        written = 0
        for row in decoded.get("units", []):
            off = row["unit_offset"]
            blob = arena[off:off + UNIT_PREFIX]
            if not blob:
                continue
            (blob_dir / f"unit_{row['arena_index']}.bin").write_bytes(blob)
            written += 1
        paths["unit_blobs"] = written
    return paths


def print_summary(opt: Options, result: dict, paths: dict) -> None:
    if opt.quiet:
        return
    meta = result.get("meta") or {}
    status = meta.get("status") or result.get("status")
    print(f"[engine_live_probe] status={status} label={meta.get('label')} "
          f"mode={meta.get('mode')}")
    aria = meta.get("arena") or {}
    if aria:
        print(f"  pid={meta.get('device', {}).get('pid')} "
              f"ctx={aria.get('ctx_hex')} arena={aria.get('arena_size_hex')} "
              f"sha256={(aria.get('sha256') or '')[:16]}...")
    clocks = meta.get("clocks") or {}
    if clocks:
        print(f"  clock: median={clocks.get('median_s')}s "
              f"frame={clocks.get('median_frame')} "
              f"valid={clocks.get('valid_count')}/10 "
              f"stale={clocks.get('stale_indexes')}")
    records = meta.get("records") or {}
    if records:
        print(f"  records: {len(meta.get('record_rows') or [])}/10 "
              f"idx={records.get('indices')} "
              f"blocks={len(records.get('blocks') or [])}")
    if meta.get("roster"):
        parts = []
        for row in meta["roster"]:
            parts.append(f"{row.get('arena_index')}:{row.get('hero')}"
                         + (f"({row.get('player')})" if row.get("player") else "")
                         + f" c{row.get('camp')}")
        print("  roster: " + " ".join(parts))
    for check in meta.get("checks") or []:
        print(f"  {check['level']:4} {check['name']}: {check['detail']}")
    for failure in meta.get("failures") or []:
        print(f"  FAIL {failure}")
    if paths.get("meta"):
        print(f"  wrote {paths['meta']}"
              + (f", {paths['arena']}" if paths.get("arena") else "")
              + (f", {paths['units']}" if paths.get("units") else ""))
    print(f"  elapsed {meta.get('elapsed_s')}s; exit={result.get('exit_code')}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _inside_data(path: Path) -> bool:
    data_root = (ROOT / "data").resolve()
    try:
        return data_root in path.resolve().parents
    except OSError:  # pragma: no cover - exotic path errors
        return False


def _default_label() -> str:
    return time.strftime("snap_%Y%m%d_%H%M%S")


def build_options(args: argparse.Namespace) -> Options:
    return Options(
        adb=args.adb,
        serial=args.serial,
        serial_alts=tuple(args.serial_alt or ()),
        package=args.package,
        pid=args.pid,
        out=args.out.resolve() if args.out else None,
        label=args.label or _default_label(),
        mode=args.mode,
        freeze=args.freeze,
        freeze_settle=args.freeze_settle,
        keep_arena=args.keep_arena,
        unit_blobs=not args.no_unit_blobs,
        chunk_bytes=args.chunk_mb * 1024 * 1024,
        retries=args.retries,
        timeout=args.timeout,
        overwrite=args.overwrite,
        locate_only=args.locate_only,
        verify_stable_window=not args.no_verify_stable,
        roster=args.roster.resolve() if args.roster else None,
        module_scan_mb=args.module_scan_mb,
        quiet=args.quiet,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--adb", default=ADB_DEFAULT)
    parser.add_argument("--serial", default=SERIAL_DEFAULT,
                        help="primary adb serial (MuMu default 127.0.0.1:16385)")
    parser.add_argument("--serial-alt", nargs="*", default=list(SERIAL_ALT_DEFAULT),
                        help="further serials to try if --serial is unreachable")
    parser.add_argument("--package", default=PACKAGE_DEFAULT)
    parser.add_argument("--pid", type=int, default=None)
    parser.add_argument("--out", type=Path, default=None,
                        help="capture directory (required unless --locate-only)")
    parser.add_argument("--label", default=None, help="snapshot label, e.g. pause_0134")
    parser.add_argument("--mode", choices=("arena", "records", "units", "all"),
                        default="all")
    parser.add_argument("--freeze", action="store_true",
                        help="kill -STOP the game during the arena read (ANR risk; "
                             "a paused replay is normally static)")
    parser.add_argument("--freeze-settle", type=float, default=0.3)
    parser.add_argument("--keep-arena", dest="keep_arena", action="store_true",
                        default=True,
                        help="persist arena.bin (default: keep)")
    parser.add_argument("--no-keep-arena", dest="keep_arena",
                        action="store_false",
                        help="do not persist arena.bin (parse and discard)")
    parser.add_argument("--no-unit-blobs", action="store_true",
                        help="do not write units/unit_<idx>.bin prefixes")
    parser.add_argument("--chunk-mb", type=int, default=4,
                        help="dd chunk size in MiB (default 4)")
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=180,
                        help="per-chunk adb read timeout in seconds")
    parser.add_argument("--module-scan-mb", type=int, default=64,
                        help="budget for the .data fallback pointer scan")
    parser.add_argument("--roster", type=Path, default=None,
                        help="optional roster JSON (event_windows.json or "
                             "{idx: {player, hero, camp}})")
    parser.add_argument("--locate-only", action="store_true",
                        help="resolve pid/maps/arena and print diagnostics; no capture")
    parser.add_argument("--overwrite", action="store_true",
                        help="allow writing into a non-empty --out directory")
    parser.add_argument("--no-verify-stable", action="store_true",
                        help="skip the post-capture unit-window stability re-read")
    parser.add_argument("--no-numpy", action="store_true",
                        help="force the pure-python scan paths (slow; diagnostics)")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover - non-tty stdout
        pass
    if args.no_numpy:
        global np
        np = None  # noqa: F824 - module level switch
    if args.chunk_mb < 1:
        parser.error("--chunk-mb must be >= 1")
    if args.retries < 1:
        parser.error("--retries must be >= 1")
    if args.mode not in MODE_RANK:
        parser.error(f"bad --mode {args.mode}")
    if args.out is not None and not _inside_data(args.out):
        parser.error("--out must be inside the project's data/ directory")
    if args.out is None and not args.locate_only:
        parser.error("--out is required unless --locate-only")
    if args.out is not None and args.out.exists() and any(args.out.iterdir()) \
            and not args.overwrite:
        parser.error("--out already contains files; pass --overwrite to replace")

    serials = [args.serial] + [s for s in (args.serial_alt or [])
                              if s and s != args.serial]
    serial, serial_notes = pick_serial(args.adb, serials)
    if serial is None:
        print(json.dumps({"status": "error", "stage": "adb",
                          "message": f"no reachable adb serial among {serials}",
                          "serial_notes": serial_notes},
                         ensure_ascii=False), flush=True)
        return 2
    adb = Adb(args.adb, serial)
    root_info = ensure_root(adb)
    if not root_info["root"]:
        print(json.dumps({"status": "error", "stage": "root",
                          "message": "adb shell is not uid=0; cannot read "
                                     "/proc/<pid>/mem",
                          "root": root_info}, ensure_ascii=False), flush=True)
        return 2

    opt = build_options(args)
    opt.serial = serial
    opt.serial_notes = serial_notes
    opt.root_info = root_info
    try:
        result = run(adb, opt)
    except ProbeError as exc:
        payload = {"status": "error", "stage": "probe", "code": exc.code,
                   "message": str(exc), "info": exc.info}
        print(json.dumps(payload, ensure_ascii=False), flush=True)
        if opt.out is not None:
            out = Path(opt.out)
            out.mkdir(parents=True, exist_ok=True)
            (out / "meta.json").write_text(
                json.dumps({"schema": SCHEMA, "tool": TOOL_NAME,
                            "label": opt.label, "error": payload},
                           ensure_ascii=False, indent=2),
                encoding="utf-8")
        return exc.code
    paths = _write_outputs_paths(opt)
    print_summary(opt, result, paths)
    return result["exit_code"]


def _write_outputs_paths(opt: Options) -> dict:
    """Recompute written artifact paths for the summary (no extra writes)."""
    if opt.out is None:
        return {"out": None}
    out = Path(opt.out)
    paths = {"out": str(out), "meta": str(out / "meta.json")}
    if (out / "arena.bin").exists():
        paths["arena"] = str(out / "arena.bin")
    if (out / "units.jsonl").exists():
        paths["units"] = str(out / "units.jsonl")
    return paths


if __name__ == "__main__":
    raise SystemExit(main())
