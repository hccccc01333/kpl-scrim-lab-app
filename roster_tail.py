"""Decode the roster-block tail: loadout plans, identity strings, hash lists.

The ten-player blocks carry, after the fixed hero/skin prefix (s+0x00..s+0x7E),
a variable tail that holds the player's saved equipment plans, platform
identity strings and small counters.  Everything here is decoded from the
bytes themselves; field names below `slots*` arrays stay positional.

Structures (validated on the 2026-11-02 ten-human sample, 10/10 blocks):

- equipment plan:  u32BE nameLen + UTF-8 name + u32BE(12) + 12 × u32BE itemID.
  Item IDs join against pvp_item.json / agent_equip_prices.csv.
- raw slot arrays: u32BE item ids at a 4-byte stride without a name — the
  same 12-slot layout for players whose plans were never named in this blob.
- avatar URL:      `https://…` (DimBust / wx.qlogo); the DimBust path carries
  the player's 32-hex identity hash.
- WeChat openid:   `o` + 20-40 chars of [A-Za-z0-9_-].
- identity hash:   `!` + 32 hex chars (same value as the DimBust path).

Read-only; used by replay_parser.inspect_abc and replay_state_engine.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
_PRICE_PATHS = (
    ROOT / "data/replays/_analysis/datasets/pvp_item.json",
    ROOT / "data/replays/_analysis/datasets/agent_equip_prices.csv",
)

_ITEM_NAMES: dict[int, str] | None = None


def _item_names() -> dict[int, str]:
    global _ITEM_NAMES
    if _ITEM_NAMES is not None:
        return _ITEM_NAMES
    names: dict[int, str] = {}
    try:
        for row in json.loads(_PRICE_PATHS[0].read_text(encoding="utf-8")):
            if row.get("item_id") is not None:
                names[int(row["item_id"])] = row.get("item_name") or ""
    except (OSError, ValueError):
        pass
    _ITEM_NAMES = names
    return names


def item_name(item_id: int) -> str:
    return _item_names().get(item_id, "")


_U32BE_MIN, _U32BE_MAX = 0x400, 0xFFFF  # plausible item-id window


def _u32be(blob, off):
    return int.from_bytes(blob[off:off + 4], "big")


def _plan_at(blob, off, min_known=4):
    """Try to read one equipment plan at ``off``; None when it does not fit."""
    if off + 8 > len(blob):
        return None
    name_len = _u32be(blob, off)
    if not 2 <= name_len <= 48 or off + 4 + name_len + 4 > len(blob):
        return None
    try:
        name = blob[off + 4:off + 4 + name_len].decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not name or not all(c.isprintable() for c in name):
        return None
    count_off = off + 4 + name_len
    count = _u32be(blob, count_off)
    if count != 12 or count_off + 4 + 48 > len(blob):
        return None
    items = [_u32be(blob, count_off + 4 + 4 * k) for k in range(12)]
    known = sum(1 for v in items if v == 0 or v in _item_names())
    if known < min_known:
        return None
    return {"name": name, "items": items}


def _scan_plans(blob, start=0x80, max_plans=4):
    plans, pos = [], start
    while len(plans) < max_plans:
        found = None
        for off in range(pos, len(blob) - 60):
            plan = _plan_at(blob, off)
            if plan:
                found = (off, plan)
                break
        if found is None:
            break
        off, plan = found
        plan["offset"] = off
        plans.append(plan)
        pos = off + 4 + len(plan["name"].encode("utf-8")) + 4 + 48
    return plans


_AVATAR_RE = re.compile(rb"https://[\x21-\x7e]{10,240}")
_OPENID_RE = re.compile(rb"\bo[A-Za-z0-9_-]{19,43}")
_HASH_RE = re.compile(rb"[\x20-\x21]?([0-9A-F]{32})")
_URLHASH_RE = re.compile(rb"/DimBust(?:_new)?/([0-9A-F]{32})/")


def parse_tail(blob):
    """Decode one roster block tail (from s+0x80 to block end).

    Returns a dict with ``plans``, ``avatarUrl``, ``openid``, ``identityHash``
    and ``slotsArrays`` (unnamed 12-slot item arrays).  All offsets are
    block-relative.
    """
    tail = blob[0x80:]
    plans = _scan_plans(blob)
    out: dict = {"plans": plans, "unnamedArrays": []}

    avatar = _AVATAR_RE.search(tail)
    if avatar:
        out["avatarUrl"] = avatar.group().decode()
        url_hash = _URLHASH_RE.search(avatar.group())
        if url_hash:
            out["identityHash"] = url_hash.group(1).decode()
    if "identityHash" not in out:
        m = _HASH_RE.search(tail)
        if m:
            out["identityHash"] = m.group(1).decode()
    openid = _OPENID_RE.search(tail)
    if openid:
        out["openid"] = openid.group().decode()

    # Unnamed structures stay unnamed: grouped u16BE runs at a 4-byte stride
    # (values not in any item table) are counted in ``unnamedArrays`` with
    # tier=partial rather than guessed at.
    consumed = {(p["offset"], p["offset"] + 8 + len(p["name"].encode("utf-8")) + 48)
                for p in plans}
    arrays = []
    pos = 0x80
    while pos + 4 <= len(blob):
        if any(lo <= pos < hi for lo, hi in consumed):
            pos += 4
            continue
        run = []
        scan = pos
        while scan + 4 <= len(blob):
            v = int.from_bytes(blob[scan:scan + 2], "big")
            if v == 0 or blob[scan + 2:scan + 4] != b"\x00\x00":
                break
            run.append(v)
            scan += 4
        if len(run) >= 4:
            arrays.append({"offset": pos, "values": run})
            pos = scan
            continue
        pos += 4
    out["unnamedArrays"] = arrays
    return out
