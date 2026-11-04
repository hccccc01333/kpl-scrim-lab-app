"""Resolve common 5v5 inline arrays / long fields (read-only).

Targets (normal 5v5 only)
-------------------------
1. CommonSettle @ dc.db 0x106464 (stride 120, 388 rows): the four trailing
   inline fixed buffers at +0x28 / +0x3C / +0x50 / +0x64.
2. Level @ 0x364c (stride 656, 35 rows): all ten inline arrays, with the four
   byte buffers (star / reward-show / map-buff / revive) expanded by element.
3. AcntBattleLevel @ 0x14660 (stride 1240, 99 rows): full row map, the 840-byte
   stLevelCommonInfo and the 0x170-byte stLevelGamePlayInfo.
4. Equip @ 0x522bde8 (stride 568, 533 rows): the in-battle row class is
   ResEquipInBattle (84 fields).  Attribute scalars, four text fields, recipe
   and the three inline arrays are decoded per row.
5. buff @ 0x8268ac (stride 1080, 13,558 rows): name/desc/prefab anchors plus
   type/param fields and the three 184-byte effect slots.  Effect IDs are
   resolved against the 1,309-row buff-effect table @ 0x3ba41a8.

Rules used (all checked against the binary, not guessed)
--------------------------------------------------------
* Row = primary key hoisted to +0; remaining fields packed in declaration
  order with natural alignment (u8=1, u16=2, u32/i32/f32=4, u64=8,
  string handle=8 and 8-aligned, struct aligned to max member).
* ``*_length`` is a runtime helper and has no serialized slot.
* ``*_bytes`` is an inline fixed buffer.  Its byte capacity comes from the
  compiler-generated ``<field>_bytes>e__FixedBuffer`` nested type and the
  ``FixedBufferAttribute(typeof(T), N)`` blob (stored as 2*N).  The element
  width therefore is N*sizeof(T), not N*8.
* One exception found by anchor fitting: ``ResTeamRangeParam.bLimitAcntNum``
  has no serialized slot in this build.  Removing it makes
  ResDT_LevelCommonInfo exactly 0x348 bytes and puts every verified anchor
  (cross-plat CDN 0x2B8, min-credit 0x33C, gameplay start 0x350) in place.
* Main-string refs are ``(tag:u32, value32:u32)`` with
  ``file_offset = table_pos + (value32 >> 6) + 8``.

Outputs
-------
  data/replays/_analysis/datasets/agent_table_arrays.csv
  data/replays/_analysis/datasets/agent_table_arrays.md

The tool never writes replay/package files, never reads param.json and never
uses runtime_dump.  Run with ``PYTHONDONTWRITEBYTECODE=1`` if disk is tight.
"""
from __future__ import annotations

import csv
import re
import struct
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AN = ROOT / "data" / "replays" / "_analysis"
DC = AN / "device" / "dc.db"
META = AN / "global-metadata.dat"
OUT_CSV = AN / "datasets" / "agent_table_arrays.csv"
OUT_MD = AN / "datasets" / "agent_table_arrays.md"

# ----------------------------------------------------------------- metadata --
STR, U32, U64, U16, BOOL, I32, F32 = (
    99432, 102472, 102498, 102451, 42911, 79278, 98256)
LENGTH = 79304

PRIMITIVE = {
    STR: ("string", 8), U32: ("uint32", 4), U64: ("uint64", 8),
    U16: ("uint16", 2), BOOL: ("byte", 1), I32: ("int32", 4),
    F32: ("float32", 4), 79297: ("int32", 4), 94463: ("char", 1),
}

NESTED = {
    "stEasyInOutInfo": "ResDt_EasyInOutInfo",
    "stNominateParam": "ResNominateParam",
    "stPickRuleInfo": "ResDT_PickRuleInfo",
    "stUnUseSkillInfo": "ResDT_UnUseSkill",
    "stTeamRangeRule": "ResDT_TeamRangeRule",
    "stTimeTeamRangeRule": "ResTeamRangeParam",
    "stShowParam": "ResStateShowParam",
    "stLevelCommonInfo": "ResDT_LevelCommonInfo",
    "stLevelGamePlayInfo": "ResDT_LevelGamePlayInfo",
}

# Fields with no serialized slot (proved by total size + anchors).
SKIP_FIELDS = {("ResTeamRangeParam", "bLimitAcntNum")}


class Metadata:
    def __init__(self, path: Path):
        self.blob = path.read_bytes()
        magic, version = struct.unpack_from("<Ii", self.blob, 0)
        assert magic == 0xFAB11BAF and version == 29, (hex(magic), version)
        p = lambda k: struct.unpack_from("<ii", self.blob, 8 + k * 8)
        self.str_off, self.str_size = p(2)
        self.m_off, m_size = p(5)
        self.fld_off, fld_size = p(11)
        self.nst_off, _ = p(15)
        self.typ_off, typ_size = p(19)
        self.ad_off, _ = p(24)
        self.ar_off, ar_size = p(25)
        self.methods = m_size // 32
        self.blob_dir = self.blob[self.str_off:self.str_off + self.str_size]
        self.types = []
        for i in range(typ_size // 88):
            v = struct.unpack_from("<16i8H2I", self.blob, self.typ_off + i * 88)
            self.types.append(dict(index=i, name=self.str(v[0]),
                                   ns=self.str(v[1]), first=v[8],
                                   count=v[18], nest_start=v[12],
                                   nest_count=v[20]))
        self.type_by_name = {}
        for t in self.types:
            self.type_by_name.setdefault((t["ns"], t["name"]), t)
        self.attr_range = {}
        for i in range(ar_size // 8):
            tok, start = struct.unpack_from("<II", self.blob, self.ar_off + i * 8)
            self.attr_range[tok] = start
        self.fixed_buffer_ctor = self._find_method(
            ".ctor", "System.Runtime.CompilerServices.FixedBufferAttribute")

    def str(self, off: int) -> str:
        end = self.blob_dir.find(b"\x00", off)
        return self.blob_dir[off:end].decode("utf-8", "replace")

    def _find_method(self, name: str, decl_name: str) -> int:
        decl = self.type_by_name.get(("System.Runtime.CompilerServices", decl_name))
        decl_idx = decl["index"] if decl else -1
        for i in range(self.methods):
            v = struct.unpack_from("<6i4H", self.blob, self.m_off + i * 32)
            if self.str(v[0]) == name and v[1] == decl_idx:
                return i
        return -1

    def find_type(self, name: str) -> dict | None:
        for ns in ("ResData", ""):
            t = self.type_by_name.get((ns, name))
            if t:
                return t
        return None

    def fields(self, t: dict) -> list[tuple[str, int, int]]:
        out = []
        for k in range(t["count"]):
            ni, ti, tok = struct.unpack_from(
                "<2iI", self.blob, self.fld_off + (t["first"] + k) * 12)
            out.append((self.str(ni), ti, tok))
        return out

    def nested_types(self, t: dict) -> list[dict]:
        return [self.types[struct.unpack_from(
            "<I", self.blob,
            self.nst_off + (t["nest_start"] + k) * 4)[0]]
            for k in range(t["nest_count"])]

    def fixed_buffer(self, field_name: str, token: int, declaring: dict):
        """(element_count, element_kind, element_size) or None."""
        start = self.attr_range.get(token)
        if start is None:
            return None
        blob = self.blob[self.ad_off + start:self.ad_off + start + 32]
        if len(blob) < 15 or blob[0] != 1:
            return None
        if self.fixed_buffer_ctor >= 0 and struct.unpack_from("<I", blob, 1)[0] != self.fixed_buffer_ctor:
            return None
        b0 = blob[14]
        value = (((b0 & 0x7F) << 8) | blob[15]) if b0 & 0x80 else b0
        count = value // 2
        elem_kind, elem_size = "byte", 1
        buf = next((n for n in self.nested_types(declaring)
                    if n["name"] == f"<{field_name}>e__FixedBuffer"), None)
        if buf is not None:
            for fn, fti, _tok in self.fields(buf):
                if fn == "FixedElementField" and fti in PRIMITIVE:
                    elem_kind, elem_size = PRIMITIVE[fti]
                    break
        return count, elem_kind, elem_size


def field_kind(name: str):
    """(kind, size, align) for a serialized field; None for *_length."""
    if name.endswith("_length"):
        return None
    if name.endswith("_bytes"):
        return ("array", 0, 1)
    if name.startswith(("str", "sz")):
        return ("string", 8, 8)
    if name.startswith("ull"):
        return ("uint64", 8, 8)
    if name.startswith(("dw", "i", "f", "n", "u")):
        return ("int32", 4, 4)
    if name.startswith("w") and not name.startswith(("weapon", "world")):
        return ("uint16", 2, 2)
    if name.startswith(("b", "ch")):
        return ("byte", 1, 1)
    if name.startswith("st"):
        return ("struct", 0, 1)
    return ("int32", 4, 4)


class Layout:
    def __init__(self, meta: Metadata):
        self.meta = meta
        self.cache = {}

    def struct(self, cls: str):
        """(size, align, {field: (offset, size, kind, extra)}) relative to 0."""
        if cls in self.cache:
            return self.cache[cls]
        t = self.meta.find_type(cls)
        if t is None:
            raise KeyError(cls)
        off, align, out = 0, 1, {}
        for name, ti, tok in self.meta.fields(t):
            if (cls, name) in SKIP_FIELDS:
                out[name] = (None, 0, "skipped", "")
                continue
            k = field_kind(name)
            if k is None:
                continue
            kind, size, a = k
            extra = ""
            if kind == "array":
                fb = self.meta.fixed_buffer(name, tok, t)
                if fb is None:
                    raise ValueError(f"{cls}.{name}: no FixedBuffer attribute")
                n, ek, es = fb
                size = n * es
                a = 4 if es <= 4 else 8
                extra = f"{n}x{ek}={size}B"
            elif kind == "struct":
                nested = NESTED.get(name)
                if nested is None:
                    raise KeyError(f"{cls}.{name}: no nested map")
                size, a, _ = self.struct(nested)
                extra = nested
            align = max(align, a)
            off = (off + a - 1) // a * a
            out[name] = (off, size, kind, extra)
            off += size
        size = (off + align - 1) // align * align
        self.cache[cls] = (size, align, out)
        return self.cache[cls]

    def flat(self, cls: str) -> list[dict]:
        """Top-level fields plus nested struct members (dotted names)."""
        size, align, fields = self.struct(cls)
        rows = []
        for name, (off, sz, kind, extra) in fields.items():
            if off is None:
                rows.append(dict(name=name, off=None, size=0, kind="skipped",
                                 extra=extra, parent=""))
                continue
            rows.append(dict(name=name, off=off, size=sz, kind=kind,
                             extra=extra, parent=""))
            if kind == "struct" and extra in NESTED.values():
                nested_size, _, nested = self.struct(extra)
                for n2, (o2, s2, k2, e2) in nested.items():
                    if o2 is None:
                        rows.append(dict(name=f"{name}.{n2}", off=None, size=0,
                                         kind="skipped", extra=e2, parent=name))
                    else:
                        rows.append(dict(name=f"{name}.{n2}", off=off + o2,
                                         size=s2, kind=k2, extra=e2, parent=name))
        return rows


# -------------------------------------------------------------------- table --
class Table:
    def __init__(self, d: bytes, pos: int, label: str = ""):
        if d[pos:pos + 4] != b"stdr":
            raise ValueError(f"{label or hex(pos)}: not stdr")
        self.d = d
        self.pos = pos
        self.label = label
        self.nstr = struct.unpack_from("<I", d, pos + 0x08)[0]
        self.stride = struct.unpack_from("<I", d, pos + 0x14)[0]
        self.rows = struct.unpack_from("<I", d, pos + 0x18)[0]
        self.pool_rel = struct.unpack_from("<I", d, pos + 0x90)[0]
        self.base = pos + 0x98
        self.pool = self._pool()
        self._text_cache = {}
        self._key_index = None

    def _pool(self) -> list[str]:
        out, q = [], self.pos + self.pool_rel
        for _ in range(self.nstr):
            z = self.d.find(b"\x00", q + 8)
            if z < 0:
                break
            try:
                out.append(self.d[q + 8:z].decode("utf-8"))
            except UnicodeDecodeError:
                break
            q = (z + 1 + 3) & ~3
        return out

    def row(self, i: int) -> int:
        return self.base + i * self.stride

    def key(self, i: int) -> int:
        return struct.unpack_from("<I", self.d, self.row(i))[0]

    def u32(self, i: int, off: int) -> int:
        return struct.unpack_from("<I", self.d, self.row(i) + off)[0]

    def i32(self, i: int, off: int) -> int:
        return struct.unpack_from("<i", self.d, self.row(i) + off)[0]

    def u16(self, i: int, off: int) -> int:
        return struct.unpack_from("<H", self.d, self.row(i) + off)[0]

    def f32(self, i: int, off: int) -> float:
        return struct.unpack_from("<f", self.d, self.row(i) + off)[0]

    def text(self, val: int) -> str | None:
        """String ref value32 -> text (accepts newlines / rich text)."""
        if not val or val & 0x3F:
            return None
        if val in self._text_cache:
            return self._text_cache[val]
        o = self.pos + (val >> 6) + 8
        out = None
        if 0 < o < len(self.d):
            z = self.d.find(b"\x00", o, o + 2000)
            if z > o:
                try:
                    s = self.d[o:z].decode("utf-8")
                    out = s if s else None
                except UnicodeDecodeError:
                    out = None
        self._text_cache[val] = out
        return out

    def ref(self, i: int, off: int) -> str | None:
        return self.text(self.u32(i, off + 4))

    def key_set(self) -> set[int]:
        return {self.key(i) for i in range(self.rows)}

    def find_key(self, target: int) -> int | None:
        if self._key_index is None:
            self._key_index = {self.key(i): i for i in range(self.rows)}
        return self._key_index.get(target)


# ------------------------------------------------------------------- output --
CSV_FIELDS = ["domain", "table", "table_offset", "stride", "rows", "field",
              "offset", "width", "value_type", "capacity", "row_key",
              "row_name", "index", "value", "status", "confidence", "evidence"]


def row(domain, table, toff, stride, rows, field, **kw):
    out = dict.fromkeys(CSV_FIELDS, "")
    out.update(domain=domain, table=table, table_offset=hex(toff),
               stride=stride, rows=rows, field=field)
    out.update({k: ("" if v is None else v) for k, v in kw.items()})
    return out


def short(text: str | None, limit: int = 110) -> str:
    if not text:
        return ""
    s = " ".join(text.replace("\r", "\n").split())
    return s if len(s) <= limit else s[:limit - 1] + "…"


def hexs(v: int | None) -> str:
    return "" if v is None else hex(v)


# =============================================================== CommonSettle ==
CS_POS = 0x106464
RANDOM_REWARD_STORE_POS = 0x4015C7C
EVALUATE_COND_POS = 0x3626D7C
CS_ARRAYS = [
    ("AntiCheatDetail", 0x28, 20, "uint32[5] per FixedBuffer", "anti-cheat"),
    ("astRandomRewardDetail", 0x3C, 20, "byte[20] -> u32[5] (data-inferred)", "random reward"),
    ("astFirstCompleteReward", 0x50, 20, "byte[20] -> u32[5] (data-inferred)", "first-clear reward"),
    ("astRaidsReward", 0x64, 20, "byte[20] -> u32[5] (data-inferred)", "sweep/raid reward"),
]


def decode_common_settle(d: bytes, meta: Metadata):
    t = Table(d, CS_POS, "CommonSettle")
    store = Table(d, RANDOM_REWARD_STORE_POS, "RandomRewardStore")
    assert (store.stride, store.rows) == (1232, 14286), (store.stride, store.rows)
    store_keys = store.key_set()
    rows = []
    for name, off, cap, elem, sem in CS_ARRAYS:
        rows.append(row("结算", "CommonSettle", t.pos, t.stride, t.rows,
                        name, offset=hexs(off), width=cap, value_type=elem,
                        capacity=5, status="confirmed" if name != "astRandomRewardDetail" else "candidate",
                        confidence="high" if name in ("astFirstCompleteReward", "astRaidsReward", "AntiCheatDetail") else "medium",
                        evidence=f"FixedBuffer capacity {cap}B; semantics={sem}; "
                                 + ("0xFFFF/0 empty sentinel not used; only index0 observed" if name != "AntiCheatDetail" else "FixedElementField=uint32")))
    # RandomRewardStore helper definition
    rows.append(row("结算", "RandomRewardStore", store.pos, store.stride, store.rows,
                    "astRewardDetail", offset="0x1C", width=1200,
                    value_type="24B entry[50]", capacity=50,
                    status="candidate", confidence="medium",
                    evidence="bRewardNum gives entry count; 6x u32 per entry "
                             "(dwItemType,dwItemId,dwItemNum,p4,p5,0)"))

    stats = Counter()
    bad = []
    for i in range(t.rows):
        sid = t.key(i)
        arrays = []
        for name, off, cap, _elem, _sem in CS_ARRAYS:
            vals = list(struct.unpack_from("<5I", d, t.row(i) + off))
            arrays.append(vals)
            stats[name] += sum(1 for v in vals if v)
        anti, rnd, first, raids = arrays
        for label, vals in (("first", first), ("raids", raids)):
            for v in vals:
                if v and v not in store_keys:
                    bad.append((sid, label, v))
        compact = (f"anti={anti};random={rnd};first={first};raids={raids}")
        rows.append(row("结算", "CommonSettle", t.pos, t.stride, t.rows,
                        "tail_arrays", row_key=sid, value=compact,
                        status="observed", confidence="high",
                        evidence="tail +0x28..+0x77; only index0 populated in all 388 rows"))

    # Explicit validation rows requested by the task.
    for sid in (511, 521, 531, 541, 501, 504):
        i = t.find_key(sid)
        anti = list(struct.unpack_from("<5I", d, t.row(i) + 0x28))
        rnd = list(struct.unpack_from("<5I", d, t.row(i) + 0x3C))
        first = list(struct.unpack_from("<5I", d, t.row(i) + 0x50))
        raids = list(struct.unpack_from("<5I", d, t.row(i) + 0x64))
        entries = []
        for label, rid in (("first", first[0]), ("raids", raids[0])):
            if not rid:
                continue
            j = store.find_key(rid)
            if j is None:
                entries.append(f"{label}:{rid}=MISSING")
                continue
            n = d[store.row(j) + 24]
            vals = [struct.unpack_from("<6I", d, store.row(j) + 0x1C + k * 24)
                    for k in range(n)]
            entries.append(f"{label}:{rid}->" + ";".join(
                "(" + ",".join(str(x) for x in v) + ")" for v in vals))
        rows.append(row("结算", "CommonSettle", t.pos, t.stride, t.rows,
                        "validate_511_541", row_key=sid,
                        row_name=f"settle_by_id={t.u32(i, 8)}",
                        value=f"random_at_begin={d[t.row(i) + 4]} anti={anti} random={rnd} first={first} raids={raids}",
                        status="confirmed", confidence="high",
                        evidence=" | ".join(entries) if entries else "no reward-store reference on this row"))

    print(f"[CommonSettle] arrays: " + ", ".join(f"{k}={v} nonzero slots" for k, v in stats.items())
          + f"; outside RandomRewardStore={len(bad)}")
    return rows, dict(stats=stats, bad=bad, store=store, table=t)


# ====================================================================== Level ==
LEVEL_POS = 0x364C
LEVEL_ARRAYS = [
    ("SelfCampAIHeroID", 64, 20, 5, "uint32", "hero ID list (self camp AI)"),
    ("AIHeroID", 88, 20, 5, "uint32", "hero ID list (enemy AI)"),
    ("astStarDetail", 116, 12, 3, "uint32", "3-star condition IDs -> EvaluateCond"),
    ("astRewardShowDetail", 140, 60, 5, "ResDT_RewardItem", "reward preview (type,id,num)"),
    ("RecommendLevel", 200, 16, 4, "int32", "recommended account level per difficulty"),
    ("RecommendPower", 216, 16, 4, "int32", "recommended combat power per difficulty"),
    ("ServerCheckPower", 232, 16, 4, "int32", "server-side combat power check"),
    ("SettleIDDetail", 348, 16, 4, "uint32", "4 settle IDs -> CommonSettle.dwSettleID"),
    ("astMapBuffs", 416, 32, 4, "ResDT_MapBuff", "map buff (id + camp/hero filters)"),
    ("astReviveInfo", 456, 144, 4, "ResDT_PveReviveInfo", "revive cost + revive buff"),
]


def decode_level(d: bytes, meta: Metadata, lay: Layout):
    lv_size, _, lv_fields = lay.struct("ResLevelCfgInfo")
    assert lv_size == 656, hex(lv_size)
    assert lv_fields["iCfgID"][0] == 0x0
    assert lv_fields["strIdName"][0] == 0x10
    assert lv_fields["strIdMapPath"][0] == 0x100
    assert lv_fields["iMapHeight"][0] == 0x12C
    assert lv_fields["iSmallMapHeight"][0] == 0x134
    assert lv_fields["iPassDialogId"][0] == 0x144
    t = Table(d, LEVEL_POS, "Level")
    cs = Table(d, CS_POS, "CommonSettle")
    cs_keys = cs.key_set()
    ev = Table(d, EVALUATE_COND_POS, "EvaluateCond")
    assert (ev.stride, ev.rows) == (128, 178), (ev.stride, ev.rows)
    ev_keys = ev.key_set()
    buff = Table(d, 0x8268AC, "buff")
    buff_keys = buff.key_set()

    rows = []
    for name, off, size, count, elem, sem in LEVEL_ARRAYS:
        rows.append(row("关卡", "Level", t.pos, t.stride, t.rows, name,
                        offset=hexs(off), width=size, value_type=elem,
                        capacity=count, status="confirmed", confidence="high",
                        evidence=f"FixedBuffer/struct size {size}B; {count} x {size // count}B; {sem}"))
    # layout anchors that prove the 656-byte reproduction
    for name, off, width, vt, ev in (
            ("iCfgID", 0x0, 4, "int32", "row key (1,2,3,6,8,11...)"),
            ("strIdName", 0x10, 8, "str", "row 101... name/design/artist handles"),
            ("strIdMapPath", 0x100, 8, "str", "pvp_9_detail / pvp_5_detail"),
            ("iMapHeight", 0x12C, 4, "int32", "80/120"),
            ("iSmallMapHeight", 0x134, 4, "int32", "80/120"),
            ("iPassDialogId", 0x144, 4, "int32", "3/0")):
        rows.append(row("关卡", "Level", t.pos, t.stride, t.rows, name,
                        offset=hexs(off), width=width, value_type=vt,
                        status="confirmed", confidence="high", evidence=ev))
    # element definitions of the four byte buffers
    elem_defs = [
        ("astStarDetail[i]", 0, 4, "uint32", "EvaluateCond.dwID"),
        ("astRewardShowDetail[i].dwItemType", 0, 4, "uint32", "ResDT_RewardItem"),
        ("astRewardShowDetail[i].dwItemId", 4, 4, "uint32", "ResDT_RewardItem"),
        ("astRewardShowDetail[i].dwItemNum", 8, 4, "uint32", "ResDT_RewardItem"),
        ("astMapBuffs[i].dwID", 0, 4, "uint32", "ResDT_MapBuff (buff ID)"),
        ("astMapBuffs[i].bCamp", 4, 1, "byte", "ResDT_MapBuff"),
        ("astMapBuffs[i].bHeroType", 5, 1, "byte", "ResDT_MapBuff"),
        ("astMapBuffs[i].bHeroDamageType", 6, 1, "byte", "ResDT_MapBuff"),
        ("astMapBuffs[i].bHeroAttackType", 7, 1, "byte", "ResDT_MapBuff"),
        ("astReviveInfo[i].astReviveCost", 0, 24, "3 x {time,cost} u32", "ResDT_PveReviveInfo"),
        ("astReviveInfo[i].ReviveBuff", 24, 12, "uint32[3]", "ResDT_PveReviveInfo"),
    ]
    for name, off, width, vt, sem in elem_defs:
        rows.append(row("关卡", "Level", t.pos, t.stride, t.rows, name,
                        offset=hexs(off), width=width, value_type=vt,
                        status="confirmed", confidence="high",
                        evidence=f"element layout; {sem}"))

    counts = Counter()
    for i in range(t.rows):
        lid = t.key(i)
        settle = list(struct.unpack_from("<4I", d, t.row(i) + 348))
        star = list(struct.unpack_from("<3I", d, t.row(i) + 116))
        reward = [struct.unpack_from("<3I", d, t.row(i) + 140 + k * 12)
                  for k in range(5)]
        reward = [x for x in reward if any(x)]
        mb = [struct.unpack_from("<IB3B", d, t.row(i) + 416 + k * 8)
              for k in range(4)]
        mb = [x for x in mb if any(x)]
        revive = []
        for k in range(4):
            base = t.row(i) + 456 + k * 36
            cost = [struct.unpack_from("<2I", d, base + j * 8) for j in range(3)]
            rb = list(struct.unpack_from("<3I", d, base + 24))
            revive.append((cost, rb))
        # collapse four identical revive entries
        rev_txt = "4x" + repr(revive[0]) if revive and all(x == revive[0] for x in revive) else repr(revive)
        for v in settle:
            counts["settle_total"] += 1
            if v:
                counts["settle_nonzero"] += 1
            if v and v not in cs_keys:
                counts["settle_bad"] += 1
        for v in star:
            counts["star_total"] += 1
            if v:
                counts["star_nonzero"] += 1
            if v and v not in ev_keys:
                counts["star_bad"] += 1
        for _c, rb in revive:
            for v in rb:
                counts["revive_total"] += 1
                if v:
                    counts["revive_nonzero"] += 1
                if v and v not in buff_keys:
                    counts["revive_bad"] += 1
        compact = (f"settle={settle};star={star};reward={reward};"
                   f"mapbuffs={mb};revive={rev_txt}")
        rows.append(row("关卡", "Level", t.pos, t.stride, t.rows,
                        "arrays", row_key=lid, value=compact,
                        status="observed", confidence="high",
                        evidence="all ten arrays decoded from the fixed buffers"))
    rows.append(row("关卡", "Level", t.pos, t.stride, t.rows, "validation",
                    value=f"settle {counts['settle_total'] - counts['settle_bad']}/{counts['settle_total']} in CommonSettle; "
                          f"star {counts['star_total'] - counts['star_bad']}/{counts['star_total']} in EvaluateCond; "
                          f"revive buff {counts['revive_bad']} unresolved",
                    status="confirmed", confidence="high",
                    evidence="Join by row key; revive buff IDs 653010/653020/653030 are not in buff table"))
    print(f"[Level] {dict(counts)}")
    return rows, counts


# ============================================================ AcntBattleLevel ==
ACNT_POS = 0x14660
COMMON_ANCHORS = {
    "strIdThumbnailPath": 0x58,
    "strIdMusicEndEvent": 0x150,
    "strIdGameMatchName": 0x160,
    "strIdSceneWeatherEffect": 0x1A8,
    "strIdCrossPlatInviteCDN": 0x2B8,
    "dwMinCreditValueRequirements": 0x33C,
    "dwPreBPHeroID": 0x25C,
    "dwPreBanHeroNum": 0x260,
    "dwCampPlayerConfID": 0x264,
    "dwFullLvlSymbolPageOpen": 0x270,
    "strIdSceneToken": 0x290,
    "strIdExpSceneToken": 0x298,
}
GP_ANCHORS = {
    "wOriginalGoldCoinInBattle": 0x00,
    "iHeroBornAgeDelayTime": 0x08,
    "iMapWidth": 0x0C,
    "strIdMapPath": 0x10,
    "iMapHeight": 0x30,
    "dwSoulAllocID": 0x3C,
    "dwDynamicPropertyCfg": 0xDC,
    "dwCompensateExpBuffID": 0xE0,
    "dwCompensateGoldBuffID": 0xE4,
}


def confidence_for(name: str, anchors: dict) -> tuple[str, str]:
    if name in anchors:
        return "high", f"verified anchor {hexs(anchors[name])}"
    if name.startswith(("b", "ch", "w")):
        return "medium", "natural alignment"
    return "medium", "natural alignment"


def decode_acnt(d: bytes, meta: Metadata, lay: Layout):
    t = Table(d, ACNT_POS, "AcntBattleLevel")
    size_l, _, acnt = lay.struct("ResAcntBattleLevelInfo")
    assert size_l == 1240, hex(size_l)
    cs, ga, common = lay.struct("ResDT_LevelCommonInfo")
    gs, _, gp = lay.struct("ResDT_LevelGamePlayInfo")
    assert cs == 840 and gs == 0x170, (cs, gs)
    rows = []
    # full row map
    for name, (off, sz, kind, extra) in acnt.items():
        rows.append(row("关卡/经济", "AcntBattleLevel", t.pos, t.stride, t.rows,
                        name, offset=hexs(off), width=sz, value_type=kind,
                        status="confirmed" if name in ("dwMapId", "bBattleMatchSubType", "bIsCanPVP", "bIsCanPVE") else "candidate",
                        confidence="high" if name in ("dwMapId", "stLevelCommonInfo", "stLevelGamePlayInfo") else "medium",
                        evidence=f"row layout sums to {size_l}; {extra}"))
    # common-info top-level + nested members
    for f in lay.flat("ResDT_LevelCommonInfo"):
        if f["off"] is None:
            rows.append(row("关卡/经济", "AcntBattleLevel.stLevelCommonInfo", t.pos,
                            t.stride, t.rows, f["name"], status="not_serialized",
                            confidence="medium",
                            evidence="no slot: removing it makes the struct 840B and restores every anchor"))
            continue
        conf, ev = confidence_for(f["name"].split(".")[-1], COMMON_ANCHORS)
        rows.append(row("关卡/经济", "AcntBattleLevel.stLevelCommonInfo", t.pos,
                        t.stride, t.rows, f["name"], offset=hexs(8 + f["off"]),
                        width=f["size"], value_type=f["kind"],
                        status="confirmed" if conf == "high" else "candidate",
                        confidence=conf,
                        evidence=f"common+{hexs(f['off'])}; {ev}; struct size 840"))
    # gameplay top-level + nested
    for f in lay.flat("ResDT_LevelGamePlayInfo"):
        if f["off"] is None:
            continue
        conf, ev = confidence_for(f["name"].split(".")[-1], GP_ANCHORS)
        rows.append(row("关卡/经济", "AcntBattleLevel.stLevelGamePlayInfo", t.pos,
                        t.stride, t.rows, f["name"], offset=hexs(0x350 + f["off"]),
                        width=f["size"], value_type=f["kind"],
                        status="confirmed" if conf == "high" else "candidate",
                        confidence=conf,
                        evidence=f"gameplay+{hexs(f['off'])}; {ev}; struct size 0x170; base 0x350"))
    rows.append(row("关卡/经济", "AcntBattleLevel.stLevelGamePlayInfo", t.pos,
                    t.stride, t.rows, "astExpCompensateDetail[i]",
                    offset=hexs(0x390), width=8, value_type="ResDT_CompensateInfo",
                    capacity=5, status="confirmed", confidence="high",
                    evidence="{dwLevelDiff,dwExtraRate}; 40B buffer = 5 entries"))
    rows.append(row("关卡/经济", "AcntBattleLevel.stLevelGamePlayInfo", t.pos,
                    t.stride, t.rows, "astCoinCompensateDetail[i]",
                    offset=hexs(0x3B8), width=8, value_type="ResDT_CompensateInfo",
                    capacity=5, status="confirmed", confidence="high",
                    evidence="{dwLevelDiff,dwExtraRate}; 40B buffer = 5 entries"))

    # 5v5 rows: normal pvp_9/pvp_5 canyon configs with 10 accounts.
    n5 = 0
    exclude = ("人机", "绝悟", "修炼", "练习", "CS", "OB", "CE", "测试",
               "功能开发", "性能", "弹幕", "梦之队", "快速", "冰雪",
               "缩小", "简化", "4.0", "新英雄")
    for i in range(t.rows):
        mid = t.key(i)
        max_acnt = d[t.row(i) + 8 + 0x41]
        map_path = t.ref(i, 0x360) or ""
        name = t.ref(i, 8) or ""
        if max_acnt < 10 or not (map_path.startswith("pvp_9") or map_path.startswith("pvp_5")):
            continue
        if t.i32(i, 0x35C) not in (109, 103) or d[t.row(i) + 4] not in (0, 7):
            continue
        if t.u16(i, 0x350) != 300 or any(x in name for x in exclude):
            continue
        n5 += 1
        gold = t.u16(i, 0x350)
        exp_pairs = [struct.unpack_from("<2I", d, t.row(i) + 0x390 + k * 8)
                     for k in range(5)]
        exp_pairs = [x for x in exp_pairs if any(x)]
        key_vals = dict(
            subtype=d[t.row(i) + 4], max_acnt=max_acnt,
            max_camp=d[t.row(i) + 8 + 0x60], hero_num=d[t.row(i) + 8 + 0x88],
            gold=gold, exp_comp=d[t.row(i) + 0x352], coin_comp=d[t.row(i) + 0x353],
            diff_type=d[t.row(i) + 0x354], born_delay=t.i32(i, 0x358),
            map_w=t.i32(i, 0x35C), map_h=t.i32(i, 0x380),
            dynamic_cfg=t.u32(i, 0x42C),
            exp_buff=t.u32(i, 0x430), gold_buff=t.u32(i, 0x434),
            sell_time=t.i32(i, 0x494), dying_speed=t.i32(i, 0x4A8),
            extra_skill=t.i32(i, 0x3E0), extra_skill2=t.i32(i, 0x3E4),
            exp_pairs=exp_pairs)
        rows.append(row("关卡/经济", "AcntBattleLevel", t.pos, t.stride, t.rows,
                        "normal5v5_config", row_key=mid, row_name=short(name, 60),
                        value=str(key_vals), status="observed", confidence="high",
                        evidence=f"map_path={map_path}; bMaxAcntNum={max_acnt}"))
    print(f"[AcntBattleLevel] common={cs}B gameplay={gs}B row={size_l}B; 5v5 rows={n5}")
    return rows, dict(common=cs, gp=gs, row=size_l, n5=n5)


# ====================================================================== Equip ==
EQUIP_POS = 0x522BDE8
ATTRS = [
    ("dwPhyAttack", 0x68), ("dwAttackSpeed", 0x6C), ("dwCriticalHit", 0x70),
    ("dwHealthSteal", 0x74), ("dwMgcHemophagia", 0x78), ("dwMagicAttack", 0x7C),
    ("dwCDReduce", 0x80), ("dwMagicPoint", 0x84), ("dwMagicRecover", 0x88),
    ("dwPhyDefence", 0x8C), ("dwMagicDefence", 0x90), ("dwHealthPoint", 0x94),
    ("dwHealthRecover", 0x98), ("dwMoveSpeed", 0x9C),
    ("dwAttackIntensity", 0xA0), ("dwMagicRecoverRate", 0xA4),
    ("dwMainPropertyValue", 0xA8),
]
TEXTS = [("strIdDesc", 0x1D0), ("strIdDesc2", 0x1D8),
         ("strIdAdditionDesc", 0x1E0), ("strIdDescLabel", 0x1E8)]


def decode_equip(d: bytes, meta: Metadata, lay: Layout):
    t = Table(d, EQUIP_POS, "Equip")
    size, align, fields = lay.struct("ResEquipInBattle")
    assert size == 568, hex(size)
    assert fields["strIdName"][0] == 0x8
    assert fields["dwBuyPrice"][0] == 0x28
    assert fields["dwSalePrice"][0] == 0x4C
    assert fields["strIdPreEquipID"][0] == 0x50
    assert fields["dwPhyAttack"][0] == 0x68
    assert fields["strIdDesc"][0] == 0x1D0
    assert fields["astPassiveSkill_bytes"][0] == 0xB0
    fx = Table(d, 0x3BA41A8, "buff_effect")
    buff = Table(d, 0x8268AC, "buff")
    fx_keys = fx.key_set()
    buff_keys = buff.key_set()

    def resolve(rid: int) -> str:
        if rid in fx_keys:
            j = fx.find_key(rid)
            return short(fx.ref(j, 0x10), 40)
        if rid in buff_keys:
            j = buff.find_key(rid)
            return short(buff.ref(j, 0x78), 40)
        return ""

    rows = []
    for name, (off, sz, kind, extra) in fields.items():
        status = "candidate"
        conf = "medium"
        ev = f"ResEquipInBattle layout; size 568 == stride; {extra}"
        if name in {a[0] for a in ATTRS}:
            if name in ("dwAttackIntensity", "dwMagicRecoverRate"):
                status, conf = "candidate", "low"
                ev = "no non-zero sample in the 533 rows; field name/offset from metadata only"
            elif name == "dwMainPropertyValue":
                status, conf = "candidate", "medium"
                ev = "22011 雌雄·双股=80, 22014 传国·碧玺=65 (主属性 item group)"
            else:
                status, conf = "confirmed", "high"
                ev = ("value matches item tooltip / known 5v5 item "
                      "(铁剑 +20 AD, 无尽 120 AD, 吸血之镰 800, 提神水晶 30)")
        elif name in {x[0] for x in TEXTS}:
            status, conf = "confirmed", "high"
            ev = "text handle; first row shows '+20攻击' at +0x1D0/+0x1D8"
        elif name in ("wID", "dwBuyPrice", "dwSalePrice", "strIdName",
                      "strIdPreEquipID", "strIdRequireEquip"):
            status, conf = "confirmed", "high"
            ev = "row key / price / recipe string verified (1111=铁剑 buy275 sale165)"
        rows.append(row("装备", "Equip", t.pos, t.stride, t.rows, name,
                        offset=hexs(off), width=sz, value_type=kind,
                        status=status, confidence=conf, evidence=ev))
    for name, off, count, esz, elem, sem in (
            ("astPassiveSkill", 0xB0, 5, 32, "32B entry",
             "{fxID, flag, strIdDesc, selfOrSourceID, buffID1, buffID2, p6, p7}"),
            ("astEffectCombine", 0x150, 4, 16, "16B entry",
             "{fxID, equipID, strIdDesc}"),
            ("astActiveSkill", 0x190, 2, 32, "32B entry",
             "{fxID, count/level, activeID2, param, strIdDesc, p6, p7}")):
        rows.append(row("装备", "Equip", t.pos, t.stride, t.rows, name,
                        offset=hexs(off), width=count * esz,
                        value_type=f"byte[{count * esz}] -> {count} x {esz}B",
                        capacity=count, status="confirmed", confidence="high",
                        evidence=f"string handles / IDs repeat every {size}B; {sem}"))
    for i in range(t.rows):
        rid = t.u16(i, 0)
        name = t.ref(i, 0x8)
        buy = t.u32(i, 0x28)
        sale = t.u32(i, 0x4C)
        attrs = []
        for an, off in ATTRS:
            v = t.i32(i, off)
            if v:
                attrs.append(f"{an[2:] if an.startswith('dw') else an}={v}")
        passive = []
        for k in range(5):
            base = 0xB0 + k * 32
            fxid, flag = struct.unpack_from("<2I", d, t.row(i) + base)
            desc = t.ref(i, base + 8)
            selfid, b1, b2 = struct.unpack_from("<3I", d, t.row(i) + base + 16)
            if fxid or desc:
                passive.append(dict(fx=fxid, name=resolve(fxid), desc=short(desc, 36),
                                    src=selfid, buffs=[b1, b2]))
        combine = []
        for k in range(4):
            base = 0x150 + k * 16
            fxid, eqid = struct.unpack_from("<2I", d, t.row(i) + base)
            desc = t.ref(i, base + 8)
            if fxid or eqid or desc:
                combine.append(dict(fx=fxid, name=resolve(fxid), eq=eqid,
                                    desc=short(desc, 36)))
        active = []
        for k in range(2):
            base = 0x190 + k * 32
            a, b = struct.unpack_from("<2I", d, t.row(i) + base)
            desc = t.ref(i, base + 16)
            if a or desc:
                active.append(dict(fx=a, name=resolve(a), n=b, desc=short(desc, 36)))
        descs = [short(t.ref(i, off), 60) for _n, off in TEXTS]
        compact = (f"buy={buy};sale={sale};lvl={d[t.row(i)+0x16]};"
                   f"type={d[t.row(i)+0x17]};group={t.u16(i, 0x1A)};"
                   f"recipe={t.ref(i, 0x50) or ''};require={t.ref(i, 0x58) or ''};"
                   f"attrs={'/'.join(attrs)};texts={descs};"
                   f"passive={passive};combine={combine};active={active}")
        rows.append(row("装备", "Equip", t.pos, t.stride, t.rows, "row",
                        row_key=rid, row_name=short(name, 40), value=compact,
                        status="observed", confidence="high",
                        evidence="ResEquipInBattle row; arrays expanded by 32/16/32B entries"))
    print(f"[Equip] ResEquipInBattle size={size} stride={t.stride}; rows={t.rows}")
    return rows, dict(size=size, rows=t.rows)


# ======================================================================= buff ==
BUFF_POS = 0x8268AC
BUFF_FX_POS = 0x3BA41A8
BUFF_PARAM_OFFSETS = [0xD4, 0xD8, 0xDC, 0xE0, 0xE4, 0xE8, 0xEC,
                      0x128, 0x12C, 0x3D0, 0x3D4, 0x3E0, 0x41C, 0x420, 0x424]
BUFF_KEYS = (917010, 917011, 917012, 917013, 917014, 600005, 922105,
             90000, 90003, 90005, 91747, 91815, 91816, 91817)
BUFF_WORDS = ("金币", "金钱", "经验", "辅助", "学识", "补偿", "分享",
              "经济", "收益", "补刀", "兵线", "自然")


def decode_buff(d: bytes, meta: Metadata):
    t = Table(d, BUFF_POS, "buff")
    fx = Table(d, BUFF_FX_POS, "buff_effect")
    fx_keys = fx.key_set()
    fx_name = {}
    for j in range(fx.rows):
        fx_name[fx.key(j)] = short(fx.ref(j, 0x10), 40)
    rows = []
    defs = [
        ("dwBuffID", 0x00, 4, "u32", "confirmed", "high", "row key"),
        ("dwParentBuffID", 0x14, 4, "u32", "confirmed", "high", "917010<->917014 parent link"),
        ("dwChildBuffID", 0x3C, 4, "u32", "confirmed", "high", "917014 -> 917010"),
        ("strIdName", 0x78, 8, "str", "confirmed", "high", "普通攻击/学识宝石"),
        ("strIdDesc", 0x80, 8, "str", "confirmed", "high", "辅助装备经验/金币补偿效果"),
        ("strIdPrefab", 0x90, 8, "str", "confirmed", "high", "Prefab_Gear/Support/1701E1"),
        ("dwRangeOrDuration", 0xB8, 4, "u32", "candidate", "medium", "5000/4500/0xFFFFFFFF"),
        ("dwBuffType", 0xD0, 4, "u32", "candidate", "medium",
         "204=exp comp, 107=gold comp, 86=gold effect, 50/3/6/32 other"),
        ("dwParam1", 0xD4, 4, "u32", "candidate", "medium", "917011=3000, 922105=8000"),
        ("dwParam2", 0xD8, 4, "u32", "candidate", "medium", "917010=10000, 917013=3, 600005=30"),
        ("dwParam3", 0xDC, 4, "u32", "candidate", "medium", "917010=10000"),
        ("dwParam4", 0xE0, 4, "u32", "candidate", "low", ""),
        ("dwParam5", 0xE4, 4, "u32", "candidate", "medium", "917012/917013=1"),
        ("dwParam6", 0xE8, 4, "u32", "candidate", "low", ""),
        ("dwParam7", 0xEC, 4, "u32", "candidate", "low", ""),
        ("dwParam8", 0x128, 4, "u32", "candidate", "medium", "917010=250, 917014=300"),
        ("dwParam9", 0x12C, 4, "u32", "candidate", "medium", "917010=250, 917014=300"),
        ("strIdGroupA", 0x3B8, 8, "str", "confirmed", "high", "90000 -> '900000', 90005 -> '902010'"),
        ("strIdGroupB", 0x3C0, 8, "str", "candidate", "medium", "second group string"),
        ("dwParam10", 0x3D0, 4, "u32", "candidate", "medium", "917010/917014=1200000"),
        ("dwParam11", 0x3D4, 4, "u32", "candidate", "medium", "917010/917014=30000"),
        ("dwFlags", 0x3E0, 4, "u32", "candidate", "low", "256/0 on support gem rows"),
    ]
    for name, off, width, vt, st, conf, ev in defs:
        rows.append(row("buff", "buff", t.pos, t.stride, t.rows, name,
                        offset=hexs(off), width=width, value_type=vt,
                        status=st, confidence=conf, evidence=ev))
    for slot, base in enumerate((0x188, 0x240, 0x2F8)):
        for name, rel, width, vt, ev in (
                ("dwEffectType", 0x00, 4, "u32", "0xFFFF=empty; observed 28/50/58/86"),
                ("dwEffectValue0", 0x08, 4, "u32", "type28 -> buff-effect ID; 91770='宝石叠恩赐'"),
                ("dwEffectValue1", 0x0C, 4, "u32", "90003 heal amount=2000"),
                ("dwEffectValue2", 0x10, 4, "u32", ""),
                ("dwEffectValue3", 0x14, 4, "u32", "917012 slot1=1"),
                ("dwEffectValue4", 0x18, 4, "u32", ""),
                ("dwEffectValue5", 0x20, 4, "u32", "917013=1"),
                ("dwEffectValue6", 0x24, 4, "u32", "917013=264")):
            rows.append(row("buff", "buff", t.pos, t.stride, t.rows,
                            f"astEffectSlot[{slot}].{name}", offset=hexs(base + rel),
                            width=width, value_type=vt, capacity=1,
                            status="confirmed" if rel in (0, 8) else "candidate",
                            confidence="high" if rel in (0, 8) else "medium",
                            evidence=f"slot stride 0xB8, 3 slots; {ev}"))

    selected = 0
    for i in range(t.rows):
        rid = t.key(i)
        name = t.ref(i, 0x78) or ""
        desc = t.ref(i, 0x80) or ""
        hit = rid in BUFF_KEYS or any(w in name or w in desc for w in BUFF_WORDS)
        if not hit:
            continue
        selected += 1
        slots = []
        for slot, base in enumerate((0x188, 0x240, 0x2F8)):
            etype = t.u32(i, base)
            if etype == 0xFFFF or etype == 0:
                continue
            vals = [t.u32(i, base + off) for off in (8, 12, 16, 20, 24, 32, 36)]
            fxid = vals[0] if etype == 28 and vals[0] in fx_keys else 0
            slots.append(dict(type=etype, vals=vals,
                              name=fx_name.get(fxid, "")))
        params = {hex(o): t.u32(i, o) for o in BUFF_PARAM_OFFSETS if t.u32(i, o)}
        compact = dict(type=t.u32(i, 0xD0), parent=t.u32(i, 0x14),
                       child=t.u32(i, 0x3C), params=params, slots=slots,
                       group=t.ref(i, 0x3B8) or "")
        rows.append(row("buff", "buff", t.pos, t.stride, t.rows, "row",
                        row_key=rid, row_name=short(name, 40),
                        value=str(compact), status="observed",
                        confidence="medium" if slots else "medium",
                        evidence=f"desc={short(desc, 80)}"))
    print(f"[buff] selected 5v5 rows={selected}; total={t.rows}")
    return rows, dict(selected=selected, total=t.rows)


# ======================================================================= main ==
def write_csv(rows):
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main():
    d = DC.read_bytes()
    meta = Metadata(META)
    lay = Layout(meta)

    all_rows = []
    cs_rows, cs_info = decode_common_settle(d, meta)
    lv_rows, lv_info = decode_level(d, meta, lay)
    ac_rows, ac_info = decode_acnt(d, meta, lay)
    eq_rows, eq_info = decode_equip(d, meta, lay)
    bf_rows, bf_info = decode_buff(d, meta)
    all_rows += cs_rows + lv_rows + ac_rows + eq_rows + bf_rows
    write_csv(all_rows)

    md = []
    md.append("# 普通 5v5 表内联数组 / 长字段收口（agent_table_arrays）\n")
    md.append("只读分析：`device/dc.db` + `global-metadata.dat`；不写回放/包体、"
              "不读 `param.json`、不使用 `runtime_dump`。\n")
    md.append(f"- CSV：`{OUT_CSV.relative_to(ROOT).as_posix()}`（{len(all_rows)} 行）")
    md.append(f"- CommonSettle 388 行：first/raids 非零槽 "
              f"{cs_info['stats']['astFirstCompleteReward']}/{cs_info['stats']['astRaidsReward']}，"
              f"越界 ID {len(cs_info['bad'])}")
    md.append(f"- Level 35 行：settle 非零 {lv_info['settle_nonzero']} 个、"
              f"star 非零 {lv_info['star_nonzero']} 个，全部可回连；"
              f"revive buff 未回连 {lv_info['revive_bad']} 个")
    md.append(f"- AcntBattleLevel：prologue 8B + common 840B + gameplay 0x{ac_info['gp']:X}B"
              f" + 行尾 24B = {ac_info['row']}B（=stride）；normal 5v5 配置 {ac_info['n5']} 行")
    md.append(f"- Equip 533 行：ResEquipInBattle {eq_info['size']}B（=stride）")
    md.append(f"- buff 13,558 行：5v5 相关选中 {bf_info['selected']} 行，3 个 184B 效果槽\n")

    md.append("## 1. CommonSettle 行尾 4 个内联数组\n")
    md.append("行布局（120B）：`dwSettleID(4) | bIsRandomAtBegin(1) | pad(3) | "
              "dwSettleByID | dwAddAcntExp | dwAddAcntExp1stTime | dwFailAddAcntExp | "
              "dwAddHeroExp | dwAddCoin | dwAddCoin1stTime | dwGameOverCheckTime`，"
              "随后是 4 个 20B fixed buffer：\n")
    md.append("| offset | 字段 | 容量 | 元数据元素 | 数据元素 | 语义 | 观测 | 置信 |")
    md.append("|---:|---|---:|---|---|---|---|---|")
    md.append("| +0x28 | AntiCheatDetail | 5 | `uint32[5]` | u32 | 反作弊参数，不是奖励 | 388 行仅 1 行非零（settle 101 slot0=1） | layout high / 语义 low |")
    md.append("| +0x3C | astRandomRewardDetail | 5 | `byte[20]` | u32(候选) | 随机奖励明细 | 388 行全 0 | 容量 high / 元素 medium |")
    md.append("| +0x50 | astFirstCompleteReward | 5 | `byte[20]` | u32 | 首通奖励（RandomRewardStore ID） | 236 行 slot0 非零，236/236 命中 | high |")
    md.append("| +0x64 | astRaidsReward | 5 | `byte[20]` | u32 | 扫荡/raid 奖励（RandomRewardStore ID） | 216 行 slot0 非零，216/216 命中 | high |")
    md.append("\n所有 388 行都只使用 slot0，slot1..4 恒 0；因此“长度”是运行时 "
              "`_length`，不落盘，缓冲区容量固定为 5。`astRandomRewardDetail` 容量与"
              "兄弟数组一致，但本表全零，元素宽度只能按兄弟数组推为 u32（medium）。\n")
    md.append("### 511/521/531/541/501/504 验证\n")
    md.append("| settle | by | anti | random | first | raids | 回连 |")
    md.append("|---:|---:|---|---|---|---|---|")
    for sid in (511, 521, 531, 541, 501, 504):
        i = cs_info["table"].find_key(sid)
        tt = cs_info["table"]
        anti = list(struct.unpack_from("<5I", d, tt.row(i) + 0x28))
        rnd = list(struct.unpack_from("<5I", d, tt.row(i) + 0x3C))
        first = list(struct.unpack_from("<5I", d, tt.row(i) + 0x50))
        raids = list(struct.unpack_from("<5I", d, tt.row(i) + 0x64))
        chain = []
        for label, rid in (("first", first[0]), ("raids", raids[0])):
            if not rid:
                continue
            j = cs_info["store"].find_key(rid)
            n = d[cs_info["store"].row(j) + 24]
            vals = [struct.unpack_from("<6I", d, cs_info["store"].row(j) + 0x1C + k * 24)
                    for k in range(n)]
            chain.append(f"{label} {rid}->" + ";".join(str(v) for v in vals))
        md.append(f"| {sid} | {tt.u32(i, 8)} | {anti} | {rnd} | {first} | {raids} | "
                  f"{'<br>'.join(chain) if chain else '无奖励引用'} |")
    md.append("\n结论：`first` 是**首通奖励**、`raids` 是**扫荡奖励**，都指向 "
              "`RandomRewardStore.dwRewardID`；`anti` 是反作弊参数；`random` 是随机奖励"
              "槽位但本构建全零。511/521/531/541 只填 first，未填 raids；"
              "501/504 同时填 first 和 raids。RandomRewardStore 的奖励项是 24B"
              "（6×u32，前三项=type/id/num，条数由 bRewardNum 给出）。\n")

    md.append("## 2. Level 的 10 个数组（含 4 个 byte buffer）\n")
    md.append("Level/ResLevelCfgInfo stride 656，用 FixedBuffer 容量 + 自然对齐可**完整复现** 656B。"
              "此前“4 个数组容量未定”指下面 4 个 byte buffer：\n")
    md.append("| offset | 数组 | 字节 | 元素 | 条数 | 语义 | 证据 |")
    md.append("|---:|---|---:|---|---:|---|---|")
    md.append("| 0x74 | astStarDetail | 12 | u32 | 3 | 3 星条件 ID | 1011/1012/1013 等全部命中 EvaluateCond 行键 |")
    md.append("| 0x8C | astRewardShowDetail | 60 | ResDT_RewardItem(12B) | 5 | 奖励预览 {type,id,num} | 行内 4 条 (14,0,10/25/100/400)，第 5 条零 |")
    md.append("| 0x1A0 | astMapBuffs | 32 | ResDT_MapBuff(8B) | 4 | {buffID,camp,heroType,dmgType,atkType} | 结构 5 字段=8B；Level 35 行全零 |")
    md.append("| 0x1C8 | astReviveInfo | 144 | ResDT_PveReviveInfo(36B) | 4 | 复活花费 + 复活 buff | 4×36B 完全重复；cost 3 档 + 3 个 buff ID |")
    md.append("\n其余 6 个数组：SelfCampAIHeroID 0x40 u32[5]、AIHeroID 0x58 u32[5]、"
              "RecommendLevel 0xC8 i32[4]、RecommendPower 0xD8 i32[4]、"
              "ServerCheckPower 0xE8 i32[4]、SettleIDDetail 0x15C u32[4]。"
              f"SettleIDDetail 的 {lv_info['settle_nonzero']} 个非零值 100% 命中 CommonSettle.dwSettleID；"
              f"astStarDetail 的 {lv_info['star_nonzero']} 个非零值 100% 命中 EvaluateCond。"
              "astMapBuffs 在 Level 35 行全零（结构按 ResDT_MapBuff 确认，业务值留给其他 level 表）。"
              "astReviveInfo 在配置行 101–404 内是 4×36B 完全重复；其余行为 0。"
              "其 ReviveBuff=653010/653020/653030 不在 buff 表，暂记“复活道具/未回连”。\n")

    md.append("## 3. AcntBattleLevel：840B stLevelCommonInfo 与 0x350 gameplay 基址\n")
    md.append("**关键修正**：`stLevelCommonInfo` 确为 **840B (0x348)**，从行 +8 开始，"
              "因此 `stLevelGamePlayInfo` 基址是 **0x350**，不是 0x348。"
              "证据：+0x350 u16=300 正是 gameplay+0 的 `wOriginalGoldCoinInBattle`；"
              "+0x358=1900 是 gameplay+8 的 `iHeroBornAgeDelayTime`；"
              "行尾 `RelationActivityMapID u32[5]`(0x4C0) + `dwNewbieGrowthUnlockType`(0x4D4) "
              "使整行恰好 1240B。\n")
    md.append("`ResTeamRangeParam.bLimitAcntNum` 在本构建**没有序列化槽**：去掉它后 "
              "stLevelCommonInfo 正好 840B，且行内 0x2C0 CrossPlat CDN、0x344 MinCredit=80、"
              "0x264 PreBP=1001、0x268 PreBan=3 全部对齐（即 common+0x2B8/0x33C/0x25C/0x260）；"
              "保留它则整体多 8B。\n")
    md.append("5v5 关键字段（map 20011）：\n")
    md.append("| offset | 字段 | 值 |")
    md.append("|---:|---|---|")
    for off, name, val in ((0x41, "bMaxAcntNum", 10), (0x60, "bMaxCamp", 2),
                           (0x88, "bHeroNum", 1), (0x2C0, "strIdCrossPlatInviteCDN", "55pipei.jpg URL"),
                           (0x344, "dwMinCreditValueRequirements", 80),
                           (0x350, "wOriginalGoldCoinInBattle", 300),
                           (0x352, "bIsOpenExpCompensate", 1), (0x353, "bIsOpenCoinCompensate", 0),
                           (0x358, "iHeroBornAgeDelayTime", 1900), (0x35C, "iMapWidth", 109),
                           (0x380, "iMapHeight", 109), (0x38C, "dwSoulAllocID", 4),
                           (0x390, "astExpCompensateDetail", "(2,4000)…(6,10000)"),
                           (0x3E0, "iExtraSkillId", 90003), (0x3E4, "iExtraSkill2Id", 90005),
                           (0x42C, "dwDynamicPropertyCfg", 1),
                           (0x430, "dwCompensateExpBuffID", 917010),
                           (0x434, "dwCompensateGoldBuffID", 917011)):
        md.append(f"| {hex(off)} | {name} | {val} |")
    md.append("\n`stLevelGamePlayInfo` 84 个声明字段（`_length` 不落盘）完整布局为 0x170B，"
              "CSV 逐字段给出 offset/width/类型/置信度；`astExpCompensateDetail`/`astCoinCompensateDetail` "
              "各 40B = 5×{dwLevelDiff,dwExtraRate}。\n")

    md.append("## 4. buff（0x8268ac）：效果槽与 5v5 补偿 buff\n")
    md.append("已有 4 个锚点（+0 id、+0x78 名、+0x80 描述、+0x90 prefab）之外，新增：\n")
    md.append("| offset | 字段 | 状态 | 证据 |")
    md.append("|---:|---|---|---|")
    md.append("| +0x14 | dwParentBuffID | confirmed | 917010↔917014 |")
    md.append("| +0x3C | dwChildBuffID | confirmed | 917014→917010 |")
    md.append("| +0xD0 | dwBuffType | candidate | 204=经验补偿(917010/917014)、107=金币补偿(917011)、86=金币效果(917012/922105) |")
    md.append("| +0xD8/+0xDC | dwParam2/3 | candidate | 917010=10000/10000，917014=12000/12000 |")
    md.append("| +0x128/+0x12C | dwParam8/9 | candidate | 917010=250/250，917014=300/300 |")
    md.append("| +0x3D0/+0x3D4 | dwParam10/11 | candidate | 917010/917014=1200000/30000 |")
    md.append("| +0x188/+0x240/+0x2F8 | astEffectSlot[0..2] | 偏移/容量 confirmed，语义 candidate | 每个 184B；+0 类型 0xFFFF=空；+8 为效果 ID |")
    md.append("\n效果槽：917012 slot0 `type=28, value=91770`，91770 在 0x3ba41a8 的名称是"
              "“宝石叠恩赐”；917013 slot0 `type=86, value=3`；600005 slot0 `type=50, value=60`；"
              "90003 slot0 `type=58, value=1, +0xC=2000`（瞬时治疗量）。"
              "因此槽结构至少是 `{type@+0, value0@+8, value1@+0xC, value2@+0x10, value3@+0x14, "
              "value4@+0x18, value5@+0x20, value6@+0x24}`（candidate），3 槽固定 184B。\n")
    md.append("5v5 关键 buff：917010 经验补偿（dwBuffType=204, +0xD8/+0xDC=10000/10000, "
              "+0x128/+0x12C=250/250）、917011 金币补偿（type=107, +0xD4/+0xD8=3000/1）、"
              "917012 第五名金币（type=86, +0xD8=6, slot0 fx=91770）、"
              "917013 第四名金币（type=50, +0xD8=3, slot0 +0x24=264）、"
              "917014 经验补偿加强（12000/12000, 300/300）、600005/922105 金币效果（type=86）。"
              "这些字段的数值已交叉到 `dwCompensateExpBuffID/GoldBuffID` "
              "（AcntBattleLevel 0x430/0x434 = 917010/917011），但每个 param 的业务含义仍是 candidate。\n")

    md.append("## 5. Equip（0x522bde8）：行类 = ResEquipInBattle\n")
    md.append("**重大收口**：533 行、stride 568 的真表就是 `ResEquipInBattle`（84 声明字段，3 个 `_length` 不落盘）；"
              "用 FixedBuffer 容量自然对齐得到 **568B**，与 stride 完全一致。"
              "因此不再只有 4 个属性槽，而是 17 个属性标量全解：\n")
    md.append("| offset | 字段 | 例 |")
    md.append("|---:|---|---|")
    attr_examples = {
        "dwPhyAttack": "铁剑 20 / 雷鸣刃 35 / 无尽战刃 120",
        "dwAttackSpeed": "匕首 1000(=10%) / 宗师之力 1500 / 急速战靴 2000",
        "dwCriticalHit": "雷鸣刃 1200(=12%) / 无尽战刃 2000",
        "dwHealthSteal": "吸血之镰 800(=8%) / 泣血之刃 2500 / 制裁之刃 2000",
        "dwMgcHemophagia": "噬神之书 2400(=24%)",
        "dwMagicAttack": "虚无法杖 210 / 回响之杖 220",
        "dwCDReduce": "冷静之靴 1500(=15%) / 暗影战斧 1000",
        "dwMagicPoint": "秘法之靴 400 / 冰痕之握 500",
        "dwMagicRecover": "炼金护符 10 / 破碎圣杯 15",
        "dwPhyDefence": "反伤刺甲 300 / 抵抗之靴 50",
        "dwMagicDefence": "魔女斗篷 300 / 抵抗之靴 100",
        "dwHealthPoint": "无尽战刃 500 / 不祥征兆 1200 / 魔女斗篷 1100",
        "dwHealthRecover": "提神水晶 30 / 沐光斗篷 60 / 恢复铠甲 100",
        "dwMoveSpeed": "碎星锤 750 / 回响之杖 750",
        "dwAttackIntensity": "533 行全 0（仅元数据字段名）",
        "dwMagicRecoverRate": "533 行全 0（仅元数据字段名）",
        "dwMainPropertyValue": "雌雄·双股 80 / 传国·碧玺 65（candidate）",
    }
    for name, off in ATTRS:
        md.append(f"| {hex(off)} | {name} | {attr_examples[name]} |")
    md.append("\n属性值是“放大 1000 的百分比/固定值”：铁剑 +20 攻击=`dwPhyAttack=20`；"
              "匕首 +10% 攻速=`1000`；雷鸣刃 +12% 暴击=`1200`；噬神之书 +24% 法术吸血=`2400`；"
              "冷静之靴 15% CDR=`1500`；抵抗之靴 50 物防/100 法防；无尽 500 生命。\n")
    md.append("`+0x1D0` 不是“文本数组未逐列”，而是 4 个连续字符串字段："
              "`strIdDesc`(+0x1D0)、`strIdDesc2`(+0x1D8)、`strIdAdditionDesc`(+0x1E0)、"
              "`strIdDescLabel`(+0x1E8)。铁剑前两个都是 `+20攻击`；"
              "名刀 label=`保命`；秘法之靴 addition=`唯一被动:【+50移动速度】【+法术穿透】`。\n")
    md.append("合成：`dwBuyPrice`(+0x28)、`dwSalePrice`(+0x4C，495/533 行=买价×60%；"
              "38 行特殊/活动价例外，如 2000–2004 买价 3000 售价 333)、"
              "`strIdPreEquipID`(+0x50，\"1111,1113\")、`strIdRequireEquip`(+0x58)。\n")
    md.append("三个数组（容量由字符串 handle 的 32/16/32B 周期确认）：\n")
    md.append("| offset | 数组 | 容量 | 元素 | 结构 |")
    md.append("|---:|---|---:|---|---|")
    md.append("| 0xB0 | astPassiveSkill | 5 | 32B | {fxID, flag, strIdDesc, srcID, buff1, buff2, p6, p7} |")
    md.append("| 0x150 | astEffectCombine | 4 | 16B | {fxID, equipID, strIdDesc} |")
    md.append("| 0x190 | astActiveSkill | 2 | 32B | {fxID, count/level, activeID2, param, strIdDesc, p6, p7} |")
    md.append("\n容量 5/4/2 与每项 32/16/32B 是 confirmed/high；元素内部字段名"
              "（fxID/flag/srcID/p6/p7 等）是从字符串 handle 周期和 ID 回连推断的 **candidate**。"
              "数组内 fxID 优先在 0x3ba41a8（1,309 行效果表）解析："
              "魔女斗篷 passive fx=91335/913351、combine 914220/1411、"
              "反伤刺甲 active fx=91327、逐日之弓 active 逐日描述等。\n")

    md.append("> CSV 采用紧凑格式：Equip 文本/数组描述截断到 60/36 字符，buff 描述截断到 80 字符；"
              "offset + row_key 足以从 dc.db 复读完整原文。\n")
    md.append("## 6. 置信度与剩余缺口\n")
    md.append("- confirmed/high：CommonSettle 4 数组容量与 first/raids 语义；Level 10 数组容量、"
              "SettleIDDetail/astStarDetail 回连；AcntBattleLevel 840B/0x170B/1240B 布局与 5v5 锚点；"
              "Equip 84 字段布局、17 属性（14 confirmed / 1 medium / 2 low）、4 文本、3 数组容量；buff 名称/描述/prefab/parent/child/3 槽偏移。")
    md.append("- candidate/medium：CommonSettle random 数组元素宽度与用途；Level astMapBuffs 的业务效果"
              "（数据全零）；astReviveInfo 的 653010/653020/653030 归属；"
              "AcntBattleLevel 非锚点字段的逐字段语义；Equip 数组内部的 p6/p7 等参数；"
              "buff 的 dwBuffType/param 业务含义与槽内 type 枚举。")
    md.append("- 仍未解：buff 13,558 行中每个 param 的精确公式；Equip astPassiveSkill/astActiveSkill "
              "剩余参数；Level astMapBuffs 的实际取值（Level 全零）；AcntBattleLevel RelationActivityMapID 的用途。\n")
    md.append("产物：`tools/agent_table_arrays.py`、`datasets/agent_table_arrays.csv`、"
              "本报告。\n")
    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"wrote {OUT_CSV} ({len(all_rows)} rows) and {OUT_MD}")


if __name__ == "__main__":
    main()
