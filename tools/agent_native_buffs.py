"""Decode the native buff tables in dc.db (read-only, no game process).

Key correction to the old "buff 90005 @0x4614" reading
------------------------------------------------------
0x4614 is **not** a row start of a buff table.  The bytes around it belong to
the stdr table at 0x364c (PVE/tutorial level config):

    table 0x364c: stride 656, rows 35, data start 0x36e4
    row 4  @0x4124  key=8   -> +0x25C = 0x4380 = 90000, +0x260 = 0
    row 5  @0x43b4  key=11  -> +0x25C = 0x4610 = 90000, +0x260 = 0x4614 = 90005
    row 6  @0x4644  key=12  -> +0x25C = 0x48a0,        +0x260 = 0x48a4 = 90005
    row 7  @0x48d4  key=15  -> +0x25C = 0x4b30 = 90003, +0x260 = 0x4b34 = 90007

Rows 5 (key 11) and 6 (key 12) have identical bodies, so reading a window at
0x4614 looks like a coherent 90005 row: the "effect count 12" at 0x4644 is
really row 6's row key, the "+0x40 hash refs" are row 6's refs at +0x10, the
"effect IDs 609/610/611" are row 6's values at +0x40, etc.  The shift is 0x30
bytes (0x4614 + 0x30 = row 6 @0x4644).  Table 0x5902c rows 602..611 are
"王者小店" anchor names, not effects; 0xc4ab4 rows 602..611 are loading tips.

Real native buff tables
-----------------------
1) 0x8268ac  stdr, stride 1080, rows 13,558, 16,994 strings
   row: +0x00 buffID, +0x14 parentID, +0x3C childID,
        +0x78 name ref, +0x80 desc ref, +0x90 prefab ref,
        +0xB8 range, +0xD0 type/category, +0xD4/+0xD8/+0xDC params,
        +0x188/+0x240/+0x2F8 three inline effect slots
        (id, p1, p2, p3; 65535 = empty),
        +0x3B8/+0x3C0 group string refs.
   rowID examples: 90000 治疗, 90003 瞬时治疗, 90005 守护者加速部分,
   917010..917020 学识宝石 (辅助装补偿), 600005 增加金钱经验,
   909089 人机挑战-增加金币, 922105 增加金币效果.

2) 0x3ba41a8  stdr, stride 184, rows 1,309, 2,322 strings
   row: +0x00 buffID, +0x10 name ref, +0x18 desc ref, +0x20 prefab ref,
        +0x28 count/type, +0x2C.. +0xB0 parameters/child IDs.
   rowID examples: 50014 死了给全队经验, 91562 龙鳞利剑游击效果,
   91747 分经济, 91815 辅助装解放效果, 91816/91817 辅助装补偿效果.

String refs are (hash32, offset32).  The first-use order of offsets equals the
local pool order when ref count == pool count; for the two buff tables and the
two reference tables the counts match exactly, so names resolve 1:1.  For the
PVE table 0x364c only 76 of 141 pool strings are referenced, so its name refs
are emitted as raw `0xhash:0xoffset` instead of guessing.

Output:
    data/replays/_analysis/datasets/agent_native_buffs.csv
"""
from __future__ import annotations

import csv
import struct
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DC = ROOT / "data" / "replays" / "_analysis" / "device" / "dc.db"
OUT = ROOT / "data" / "replays" / "_analysis" / "datasets" / "agent_native_buffs.csv"

# stdr table offsets (all verified with magic == b'stdr')
T_BUFF = 0x8268AC          # native buff table (large)
T_BUFF_FX = 0x3BA41A8      # native buff/effect table (small)
T_PVE = 0x364C             # PVE/tutorial table that contains 0x4380/0x4614/0x4B30
T_SHOP = 0x5902C           # 王者小店 anchor names (rows 602..611)
T_TIP = 0xC4AB4            # loading tips (rows 602..611)

KEYWORDS = {
    "gold": ("金币", "金钱", "金Qian", "货币"),
    "exp": ("经验",),
    "support": ("辅助",),
    "share": ("分享",),
    "natural": ("自然",),
    "last_hit": ("补刀",),
    "lane": ("兵线",),
    "economy": ("经济",),
    "income": ("收益", "收入"),
    "compensate": ("补偿",),
}


def u32(d: bytes, off: int) -> int:
    return struct.unpack_from("<I", d, off)[0]


def u64(d: bytes, off: int) -> int:
    return struct.unpack_from("<Q", d, off)[0]


def parse_table(d: bytes, pos: int) -> dict:
    if d[pos:pos + 4] != b"stdr":
        raise ValueError(f"no stdr magic at {pos:#x}")
    stride = u32(d, pos + 0x14)
    rows = u32(d, pos + 0x18)
    nstr = u32(d, pos + 0x08)
    pool = pos + u32(d, pos + 0x90)
    return {
        "pos": pos,
        "stride": stride,
        "rows": rows,
        "nstr": nstr,
        "pool": pool,
        "data": pos + 0x98,
    }


def parse_pool(d: bytes, t: dict) -> list[str]:
    """Pool records: hash64 + UTF-8 bytes + NUL + 4-byte alignment."""
    out: list[str] = []
    q = t["pool"]
    for _ in range(t["nstr"]):
        if q + 8 >= len(d):
            break
        z = d.find(b"\x00", q + 8)
        if z < 0:
            break
        raw = d[q + 8:z]
        try:
            s = raw.decode("utf-8")
        except UnicodeDecodeError:
            s = raw.decode("utf-8", "replace")
        out.append(s)
        q = (z + 1 + 3) & ~3
    return out


def build_ref_map(d: bytes, t: dict) -> tuple[int, dict[int, str], int, bool]:
    """Return (main_hash, offset -> string, unique_ref_count, exact)."""
    base, stride, rows = t["data"], t["stride"], t["rows"]
    distinct: dict[int, set[int]] = defaultdict(set)
    for r in range(rows):
        q = base + r * stride
        for off in range(0, stride - 4, 4):
            h = u32(d, q + off)
            o = u32(d, q + off + 4)
            if o and h not in (0, 0xFFFFFFFF):
                distinct[h].add(o)
    if not distinct:
        return 0, {}, 0, False
    main_hash, offs = max(distinct.items(), key=lambda kv: len(kv[1]))

    seen: dict[int, int] = {}
    order: list[int] = []
    for r in range(rows):
        q = base + r * stride
        for off in range(0, stride - 4, 4):
            if u32(d, q + off) != main_hash:
                continue
            o = u32(d, q + off + 4)
            if o and o not in seen:
                seen[o] = len(order)
                order.append(o)

    strings = parse_pool(d, t)
    exact = len(order) == len(strings)
    mapping: dict[int, str] = {}
    limit = min(len(order), len(strings))
    for i in range(limit):
        mapping[order[i]] = strings[i]
    # If counts differ, leave refs unmapped (raw 0xhash:0xoffset is safer).
    if not exact:
        mapping.clear()
    return main_hash, mapping, len(order), exact


def refs_in_row(d: bytes, q: int, stride: int, main_hash: int,
                mapping: dict[int, str]) -> list[tuple[int, int, str | None]]:
    refs = []
    for off in range(0, stride - 4, 4):
        if u32(d, q + off) != main_hash:
            continue
        o = u32(d, q + off + 4)
        if o:
            refs.append((off, o, mapping.get(o)))
    return refs


def raw_ref(main_hash: int, off: int) -> str:
    return f"0x{main_hash:08x}:0x{off:08x}"


def keyword_flags(*texts: str | None) -> str:
    blob = " ".join(x for x in texts if x)
    hits = []
    for name, words in KEYWORDS.items():
        if any(w in blob for w in words):
            hits.append(name)
    return ",".join(hits)


def clean(text: str | None) -> str:
    if not text:
        return ""
    return " ".join(text.replace("\r", "\n").split())


def format_params(d: bytes, q: int, offsets: list[int]) -> str:
    parts = []
    for off in offsets:
        v = u32(d, q + off)
        if v:
            parts.append(f"+{off:#x}={v}")
    return ";".join(parts)


def decode_buff_large(d: bytes, t: dict, main_hash: int, mapping: dict[int, str],
                      exact: bool) -> list[list]:
    base, stride, rows = t["data"], t["stride"], t["rows"]
    ref_slots = (0x78, 0x80, 0x90)
    param_offsets = [0x14, 0x3C, 0x54, 0x58, 0x70, 0xB8, 0xD0, 0xD4, 0xD8,
                     0xDC, 0xE0, 0xE4, 0xE8, 0xEC, 0x128, 0x12C, 0x3D0, 0x3D4, 0x3E0]
    effect_slots = (0x188, 0x240, 0x2F8)
    out = []
    for r in range(rows):
        q = base + r * stride
        rid = u32(d, q)
        refs = refs_in_row(d, q, stride, main_hash, mapping)
        by_off = {off: (o, s) for off, o, s in refs}
        texts = [by_off.get(slot, (0, None))[1] for slot in ref_slots]
        name, desc, prefab = texts
        eff = []
        for slot in effect_slots:
            eid = u32(d, q + slot)
            if eid and eid != 0xFFFF:
                eff.append(f"{eid}:{u32(d, q + slot + 4)}:{u32(d, q + slot + 8)}:"
                           f"{u32(d, q + slot + 12)}")
        group = []
        for slot in (0x3B8, 0x3C0):
            o, s = by_off.get(slot, (0, None))
            group.append(s if s else (raw_ref(main_hash, o) if o else ""))
        out.append([
            "0x8268ac", "native_buff", r, rid,
            clean(name), clean(desc), clean(prefab),
            len(eff), ";".join(eff),
            format_params(d, q, param_offsets),
            u32(d, q + 0x14) or "", u32(d, q + 0x3C) or "",
            ";".join(x for x in group if x),
            "",
            raw_ref(main_hash, by_off[0x78][0]) if 0x78 in by_off else "",
            raw_ref(main_hash, by_off[0x80][0]) if 0x80 in by_off else "",
            raw_ref(main_hash, by_off[0x90][0]) if 0x90 in by_off else "",
            keyword_flags(name, desc, prefab),
            "exact" if exact else "partial",
        ])
    return out


def decode_buff_small(d: bytes, t: dict, main_hash: int, mapping: dict[int, str],
                      exact: bool) -> list[list]:
    base, stride, rows = t["data"], t["stride"], t["rows"]
    ref_slots = (0x10, 0x18, 0x20)
    param_offsets = [0x28, 0x2C, 0x30, 0x4C, 0x50, 0x54, 0x58, 0x5C, 0x60,
                     0x64, 0x84, 0x88, 0x8C, 0x90, 0x94, 0x98, 0x9C, 0xA0,
                     0xA4, 0xA8, 0xAC, 0xB0, 0xB4, 0xB8]
    out = []
    for r in range(rows):
        q = base + r * stride
        rid = u32(d, q)
        refs = refs_in_row(d, q, stride, main_hash, mapping)
        by_off = {off: (o, s) for off, o, s in refs}
        texts = [by_off.get(slot, (0, None))[1] for slot in ref_slots]
        name, desc, prefab = texts
        child = u32(d, q + 0xB0)
        out.append([
            "0x3ba41a8", "native_buff_effect", r, rid,
            clean(name), clean(desc), clean(prefab),
            "", "",  # +0x28 is a count/type candidate, not a proven effect count
            format_params(d, q, param_offsets),
            "", "", "",
            child or "",
            raw_ref(main_hash, by_off[0x10][0]) if 0x10 in by_off else "",
            raw_ref(main_hash, by_off[0x18][0]) if 0x18 in by_off else "",
            raw_ref(main_hash, by_off[0x20][0]) if 0x20 in by_off else "",
            keyword_flags(name, desc, prefab),
            "exact" if exact else "partial",
        ])
    return out


def decode_pve(d: bytes, t: dict, main_hash: int, mapping: dict[int, str],
               exact: bool) -> list[list]:
    """The table that owns 0x4380/0x4614/0x4B30/0x4B34."""
    base, stride, rows = t["data"], t["stride"], t["rows"]
    out = []
    for r in range(rows):
        q = base + r * stride
        rid = u32(d, q)
        refs = refs_in_row(d, q, stride, main_hash, mapping)
        by_off = {off: (o, s) for off, o, s in refs}
        raw = []
        for slot in (0x10, 0x18, 0x20):
            if slot in by_off:
                o, s = by_off[slot]
                raw.append(s if s else raw_ref(main_hash, o))
        eff = [u32(d, q + o) for o in (0x40, 0x44, 0x48, 0x58, 0x5C, 0x60, 0x88)]
        eff += [u32(d, q + o) for o in (0xD8, 0xDC, 0xE0, 0xE4)]
        eff = [x for x in eff if x]
        buff_refs = [u32(d, q + 0x25C), u32(d, q + 0x260)]
        out.append([
            "0x364c", "pve_tutorial", r, rid,
            raw[0] if len(raw) > 0 else "", raw[1] if len(raw) > 1 else "",
            raw[2] if len(raw) > 2 else "",
            len(eff), ";".join(map(str, eff)),
            f"+0x25c={buff_refs[0]};+0x260={buff_refs[1]}",
            "", "", "", "",
            "", "", "",
            keyword_flags(raw[0] if len(raw) > 0 else "",
                          raw[1] if len(raw) > 1 else "",
                          raw[2] if len(raw) > 2 else ""),
            "exact" if exact else "raw_refs",
        ])
    return out


def decode_reference(d: bytes, pos: int, kind: str, rows_wanted: tuple[int, ...]) -> list[list]:
    t = parse_table(d, pos)
    main_hash, mapping, nrefs, exact = build_ref_map(d, t)
    base, stride = t["data"], t["stride"]
    idmap = {}
    for r in range(t["rows"]):
        idmap.setdefault(u32(d, base + r * stride), r)
    out = []
    for rid in rows_wanted:
        r = idmap.get(rid)
        if r is None:
            continue
        q = base + r * stride
        refs = refs_in_row(d, q, stride, main_hash, mapping)
        by_off = {off: (o, s) for off, o, s in refs}
        if kind == "shop_anchor":
            name = by_off.get(0x20, (0, ""))[1]
            desc = by_off.get(0x28, (0, ""))[1]
            name_ref = raw_ref(main_hash, by_off[0x20][0]) if 0x20 in by_off else ""
            desc_ref = raw_ref(main_hash, by_off[0x28][0]) if 0x28 in by_off else ""
        else:
            name = ""
            desc = by_off.get(0x08, (0, ""))[1]
            name_ref = ""
            desc_ref = raw_ref(main_hash, by_off[0x08][0]) if 0x08 in by_off else ""
        out.append([
            f"0x{pos:x}", kind, r, rid,
            clean(name), clean(desc), "",
            "", "", "",
            "", "", "", "",
            name_ref, desc_ref, "",
            keyword_flags(name, desc),
            "exact" if exact else "partial",
        ])
    return out


def main() -> None:
    d = DC.read_bytes()

    rows: list[list] = []

    for pos, decoder in ((T_BUFF, decode_buff_large), (T_BUFF_FX, decode_buff_small)):
        t = parse_table(d, pos)
        main_hash, mapping, nrefs, exact = build_ref_map(d, t)
        rows.extend(decoder(d, t, main_hash, mapping, exact))
        print(f"{pos:#x}: stride={t['stride']} rows={t['rows']} "
              f"strings={t['nstr']} refs={nrefs} exact={exact}")

    t = parse_table(d, T_PVE)
    main_hash, mapping, nrefs, exact = build_ref_map(d, t)
    rows.extend(decode_pve(d, t, main_hash, mapping, exact))
    print(f"{T_PVE:#x}: stride={t['stride']} rows={t['rows']} "
          f"strings={t['nstr']} refs={nrefs} exact={exact} (PVE/tutorial)")

    for pos, kind in ((T_SHOP, "shop_anchor"), (T_TIP, "loading_tip")):
        ref_rows = decode_reference(d, pos, kind, (602, 603, 604, 609, 610, 611))
        rows.extend(ref_rows)
        print(f"{pos:#x}: reference rows {len(ref_rows)} ({kind})")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    header = [
        "source_table", "table_kind", "row_index", "row_id",
        "name", "desc", "prefab",
        "effect_count", "effect_ids", "params",
        "id_0x14", "id_0x3c", "group_ref", "child_id",
        "ref_name", "ref_desc", "ref_prefab",
        "keyword_flags", "decode_confidence",
    ]
    with OUT.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)

    buff_rows = sum(1 for r in rows if r[1] in ("native_buff", "native_buff_effect"))
    kw_rows = sum(1 for r in rows if r[17])
    print(f"total rows={len(rows)} buff_rows={buff_rows} keyword_rows={kw_rows}")
    print(f"wrote {OUT}")

    # Console summary: key gold/exp/support rows.
    for r in rows:
        if r[1] in ("native_buff", "native_buff_effect") and r[17]:
            print(f"  {r[1]:18s} rowID={r[3]:<9d} flags={r[17]:<28s} "
                  f"name={r[4][:40]}")


if __name__ == "__main__":
    main()
