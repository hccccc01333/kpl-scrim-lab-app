"""普通 5v5：AcntBattleLevel 63 个 cfg1 关卡 + CommonSettle 结算映射（只读）。

背景（docs/replay_binary_format.md 5.69 / 5.75 / 5.77 / 5.82 / 5.83）
--------------------------------------------------------------------
* ``AcntBattleLevel``（dc.db ``0x14660``，stdr，stride 1240，99 行）的行类
  是 ``ResData.ResAcntBattleLevelInfo``。用 Il2Cpp metadata 顺序布局可精确
  闭合 1240：

      +0x000 dwMapId                       (iCfgID/关卡 ID)
      +0x004 bBattleMatchSubType
      +0x005 bIsCanPVP
      +0x006 bIsCanPVE
      +0x008 stLevelCommonInfo             (840 = 0x348, ResDT_LevelCommonInfo)
      +0x350 stLevelGamePlayInfo           (368 = 0x170, ResDT_LevelGamePlayInfo)
      +0x4C0 RelationActivityMapID_bytes   (20B)
      +0x4D4 dwNewbieGrowthUnlockType
      => 0x4D8 = 1240

  ``stLevelGamePlayInfo + 0x0DC`` 就是 ``dwDynamicPropertyCfg``，
  绝对行内偏移 0x42C（与 5.82 一致）。

* **字符串位置法**（5.79）：表内字符串单元 = ``(hash32, value32)``；
  ``file_offset = value32 >> 6``，字符串记录在 ``表起点 + file_offset``，
  文本从 ``+8`` 开始（跳过池记录 hash64），UTF-8 到 NUL。hash32 是每表
  唯一的字符串池命名空间，不随行/字段变化。

* ``ResCommonSettle``（dc.db ``0x106464``，stdr，stride 120，388 行）：
  10 个序列化字段 + 4 个内联数组，布局精确闭合 120：

      +0x00 dwSettleID               +0x28 AntiCheatDetail_bytes   (5 x u32)
      +0x04 bIsRandomAtBegin         +0x3C astRandomRewardDetail   (20B)
      +0x08 dwSettleByID             +0x50 astFirstCompleteReward  (20B)
      +0x0C dwAddAcntExp             +0x64 astRaidsReward          (20B)
      +0x10 dwAddAcntExp1stTime
      +0x14 dwFailAddAcntExp
      +0x18 dwAddHeroExp
      +0x1C dwAddCoin
      +0x20 dwAddCoin1stTime
      +0x24 dwGameOverCheckTime

* **结算组归属（本工具的新证据）**：CommonSettle 的 settleByID 首位不是
  兵种，而是"玩法/章节族"。直接证据来自关卡表的 ``SettleIDDetail``：

      Level.bytes cfg 101 召唤师战场  -> 111/121/131/141 (by=1011)
      Level.bytes cfg 102 摘星楼回忆  -> 112/122/132/142 (by=1021)
      ... chapter 1..4 -> by=1xxx/2xxx/3xxx/4xxx
      TrainingLevel cfg 2001          -> 2001          (by=0)
      BurningLevel   cfg 30501        -> 30501         (by=20026)
      ArenaLevel     cfg 30601        -> 30601         (by=20026)

  因此 1xxx-4xxx 是 **PVE 剧情第 1-4 章**（不是近战/远程兵），0 是训练，
  20026/300xx 是 PVE 活动；5xxx-8xxx 没有任何关卡表引用，是仅剩的 PVP
  族（客户端 databin 内不存在 settle->mode 的直连表，服务端才有）。

  5xxx（126 行，含 9xx-18xx / 105xx-118xx 等级段奖励）按行数与结构判定为
  普通 5v5 主族；6xxx 作为第二 PVP 族（更高 exp/coin，排位/10v10 候选）；
  7xxx/8xxx 只有失败行，判为 1v1/3v3/自定义一类的小玩法。

边界
----
* 只读 dc.db / databin 块，不修改回放，不注入进程，不读 param.json，
  不使用 runtime_dump 历史内存。
* 所有字符串按位置法自行解析，不依赖已存在的 CSV。

输出（默认 data/replays/_analysis/datasets/）
--------------------------------------------
* ``agent_normal5v5_levels.csv``   63 个 cfg1 关卡的关键字段
* ``agent_normal5v5_settles.csv``  388 行 CommonSettle 的归类与证据

用法::

    python tools/agent_normal5v5_levels.py
    python tools/agent_normal5v5_levels.py --db path/to/dc.db --out dir
    python tools/agent_normal5v5_levels.py --all-levels   # 99 行全表
"""
from __future__ import annotations

import argparse
import csv
import struct
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "replays" / "_analysis" / "device" / "dc.db"
DEFAULT_OUT = ROOT / "data" / "replays" / "_analysis" / "datasets"

# ---------------------------------------------------------------------------
# AcntBattleLevel layout (ResAcntBattleLevelInfo, verified size == 1240)
# ---------------------------------------------------------------------------
ACNT_STRIDE = 1240
ACNT_ROWS = 99
C = 0x008            # stLevelCommonInfo base
G = 0x350            # stLevelGamePlayInfo base

F_ID = 0x000
F_SUBTYPE = 0x004
F_PVP = 0x005
F_PVE = 0x006
F_NAME = C + 0x000
F_DESIGN = C + 0x008
F_CLASSIFY = C + 0x010
F_ARTIST = C + 0x018
F_ARTIST_EXT = C + 0x020
F_MAX_ACNT = C + 0x041
F_MAX_CAMP = C + 0x060
F_HERO_NUM = C + 0x088
F_LEVEL_SWITCH = C + 0x1F4
F_SETTLE_RULE = C + 0x21F
F_DISABLE_COIN = C + 0x302
F_DISABLE_EXP = C + 0x303
F_REVIVE = C + 0x310

F_GOLD = G + 0x000
F_OPEN_EXP = G + 0x002
F_OPEN_COIN = G + 0x003
F_MAP_W = G + 0x00C
F_MAP_H = G + 0x030
F_MAP = G + 0x010
F_MAP_MIRROR = G + 0x018
F_BIG_MAP = G + 0x020
F_BIG_MAP_MIRROR = G + 0x028
F_EXP_ARR = G + 0x040
F_COIN_ARR = G + 0x068
F_SKILL1 = G + 0x090
F_SOLDIER1 = G + 0x0C8
F_SOLDIER2 = G + 0x0CC
F_SOLDIER_DELAY = G + 0x0D0
F_DYN = G + 0x0DC
F_EXP_BUFF = G + 0x0E0
F_GOLD_BUFF = G + 0x0E4
F_AID_SHARE = G + 0x154

# ResCommonSettle layout, size 120
CS_STRIDE = 120
CS_ROWS = 388
CS_FIELDS = (
    ("dwSettleID", 0x00),
    ("bIsRandomAtBegin", 0x04),
    ("dwSettleByID", 0x08),
    ("dwAddAcntExp", 0x0C),
    ("dwAddAcntExp1stTime", 0x10),
    ("dwFailAddAcntExp", 0x14),
    ("dwAddHeroExp", 0x18),
    ("dwAddCoin", 0x1C),
    ("dwAddCoin1stTime", 0x20),
    ("dwGameOverCheckTime", 0x24),
)
CS_ANTI = 0x28
CS_RANDOM = 0x3C
CS_FIRST = 0x50
CS_RAIDS = 0x64

# ResLevelCfgInfo layout (stride 656), used by Level / BurningLevel / ArenaLevel
# and by TrainingLevel.stBaseLevelCfg (offset 0).
LVL_STRIDE = 656
LVL_ID = 0x000
LVL_CHAPTER = 0x004
LVL_NO = 0x008
LVL_DIFF = 0x009
LVL_NAME = 0x010
LVL_TYPE = 0x030
LVL_SETTLES = 0x15C
LVL_DYN = 0x17C

# battleDynamicProperty @0x2afa49c, stride 76, rows 7603
BDP_STRIDE = 76
BDP_CFG = 0x00
BDP_VAR_TYPE = 0x04
BDP_START = 0x08
BDP_INTERVAL = 0x0C
BDP_RATE = 0x3E          # u16

MODE_LABELS = {
    1: "普通5v5-王者峡谷族(cfg1)",
    1010001: "快速/娱乐族(cfg1010001，排除)",
    5262: "10v10/神祈战场(cfg5262，排除)",
}

PVE_CHAPTERS = {1: "第一章", 2: "第二章", 3: "第三章", 4: "第四章"}


# ---------------------------------------------------------------------------
# stdr table plumbing
# ---------------------------------------------------------------------------
@dataclass
class Table:
    pos: int
    stride: int
    rows: int
    nstr: int
    pool_rel: int

    @property
    def base(self) -> int:
        return self.pos + 0x98

    @property
    def pool(self) -> int:
        return self.pos + self.pool_rel

    def row(self, blob: bytes, i: int) -> int:
        return self.base + i * self.stride

    def u32(self, blob: bytes, i: int, off: int) -> int:
        return struct.unpack_from("<I", blob, self.row(blob, i) + off)[0]

    def u16(self, blob: bytes, i: int, off: int) -> int:
        return struct.unpack_from("<H", blob, self.row(blob, i) + off)[0]

    def u8(self, blob: bytes, i: int, off: int) -> int:
        return blob[self.row(blob, i) + off]


def iter_tables(blob: bytes) -> list[Table]:
    out: list[Table] = []
    s = 0
    while True:
        p = blob.find(b"stdr", s)
        if p < 0:
            break
        s = p + 1
        try:
            stride = struct.unpack_from("<I", blob, p + 0x14)[0]
            rows = struct.unpack_from("<I", blob, p + 0x18)[0]
            nstr = struct.unpack_from("<I", blob, p + 8)[0]
            pool_rel = struct.unpack_from("<I", blob, p + 0x90)[0]
        except struct.error:
            continue
        if not (0 < stride <= 8192 and 0 < rows < 500_000):
            continue
        if p + 0x98 + stride * rows > len(blob):
            continue
        if pool_rel and pool_rel != 0x98 + stride * rows:
            # 5.79: pool starts exactly at 0x98 + stride*rows for these tables
            continue
        out.append(Table(p, stride, rows, nstr, pool_rel))
    return out


def find_table(tables: list[Table], blob: bytes, want: dict) -> Table:
    """Match a table by stride/rows and a few u32 anchors (row index, offset)."""
    for t in tables:
        if t.stride != want["stride"] or t.rows != want["rows"]:
            continue
        ok = True
        for (row, off), val in want["anchors"].items():
            if t.u32(blob, row, off) != val:
                ok = False
                break
        if ok:
            return t
    raise LookupError(f"table not found: {want}")


def table_string_hash(blob: bytes, t: Table) -> int:
    """Dominant string ref hash32 in the table (per-table namespace)."""
    counts: dict[int, int] = defaultdict(int)
    for i in range(t.rows):
        r = t.row(blob, i)
        for off in range(0, t.stride - 7, 4):
            h, v = struct.unpack_from("<II", blob, r + off)
            if not h or not v:
                continue
            file_off = v >> 6
            if not (t.pool_rel <= file_off and t.pos + file_off + 8 < len(blob)):
                continue
            rec = t.pos + file_off
            z = blob.find(b"\x00", rec + 8, min(len(blob), rec + 8 + 512))
            if z < 0:
                continue
            try:
                blob[rec + 8:z].decode("utf-8")
            except UnicodeDecodeError:
                continue
            counts[h] += 1
    return max(counts, key=counts.get) if counts else 0


def resolve_ref(blob: bytes, t: Table, table_hash: int, off: int) -> tuple[str, str]:
    """Positional string resolution: value32 = file_offset << 6."""
    h, v = struct.unpack_from("<II", blob, off)
    if not h and not v:
        return "", "empty"
    if table_hash and h != table_hash:
        return "", f"hash_mismatch:{h:08x}"
    # value32 is already relative to the table asset start; the string pool
    # begins at pool_rel, so valid records are >= pool_rel.
    file_off = v >> 6
    if file_off < t.pool_rel or t.pos + file_off + 8 >= len(blob):
        return "", f"offset_out_of_range:{file_off:#x}"
    rec = t.pos + file_off
    z = blob.find(b"\x00", rec + 8, min(len(blob), rec + 8 + 1024))
    if z < 0:
        return "", "no_nul"
    try:
        return blob[rec + 8:z].decode("utf-8"), "exact"
    except UnicodeDecodeError:
        return "", "bad_utf8"


def sref(blob: bytes, t: Table, table_hash: int, row: int, off: int) -> str:
    text, _conf = resolve_ref(blob, t, table_hash, t.row(blob, row) + off)
    return text


def pair_array(blob: bytes, t: Table, row: int, off: int, count: int = 5) -> str:
    vals = []
    base = t.row(blob, row) + off
    for i in range(count):
        a, b = struct.unpack_from("<II", blob, base + i * 8)
        if a or b:
            vals.append(f"{a}:{b}")
    return ";".join(vals)


def u32_array(blob: bytes, t: Table, row: int, off: int, count: int = 5) -> str:
    base = t.row(blob, row) + off
    vals = [struct.unpack_from("<I", blob, base + i * 4)[0] for i in range(count)]
    while vals and vals[-1] == 0:
        vals.pop()
    return ";".join(str(v) for v in vals)


# ---------------------------------------------------------------------------
# battleDynamicProperty (natural gold)
# ---------------------------------------------------------------------------
def load_natural_gold(blob: bytes, tables: list[Table]) -> tuple[Table, dict[int, dict]]:
    cand = [t for t in tables if t.stride == BDP_STRIDE and t.rows >= 7000]
    table = None
    for t in cand:
        by = defaultdict(list)
        for i in range(t.rows):
            cfg = t.u32(blob, i, BDP_CFG)
            if cfg not in (1, 1010001, 5262):
                continue
            if t.u32(blob, i, BDP_VAR_TYPE) != 2:
                continue
            by[cfg].append((t.u32(blob, i, BDP_START),
                            t.u32(blob, i, BDP_INTERVAL),
                            t.u16(blob, i, BDP_RATE)))
        if by.get(1) and any(r for _s, _iv, r in by[1]):
            table = t
            break
    if table is None:
        raise LookupError("battleDynamicProperty table not found")

    rates: dict[int, dict] = {}
    by = defaultdict(list)
    for i in range(table.rows):
        cfg = table.u32(blob, i, BDP_CFG)
        if table.u32(blob, i, BDP_VAR_TYPE) != 2:
            continue
        by[cfg].append((table.u32(blob, i, BDP_START),
                        table.u32(blob, i, BDP_INTERVAL),
                        table.u16(blob, i, BDP_RATE)))
    for cfg, rows in by.items():
        rows.sort()
        nz = [(s, iv, r) for s, iv, r in rows if r > 0]
        if not nz:
            continue
        rates[cfg] = dict(
            rate_min=min(r for _s, _iv, r in nz),
            rate_max=max(r for _s, _iv, r in nz),
            start_ms=nz[0][0],
            interval_ms=nz[0][1],
            first_rate=nz[0][2],
            last_rate=nz[-1][2],
        )
    return table, rates


# ---------------------------------------------------------------------------
# Level-like tables -> settle evidence
# ---------------------------------------------------------------------------
def level_rows(blob: bytes, t: Table) -> list[dict]:
    h = table_string_hash(blob, t)
    out = []
    for i in range(t.rows):
        sid = struct.unpack_from("<4I", blob, t.row(blob, i) + LVL_SETTLES)
        out.append(dict(
            cfg=t.u32(blob, i, LVL_ID),
            chapter=t.u32(blob, i, LVL_CHAPTER),
            stage=t.u8(blob, i, LVL_NO),
            difficulty=t.u8(blob, i, LVL_DIFF),
            name=sref(blob, t, h, i, LVL_NAME),
            level_type=t.u32(blob, i, LVL_TYPE),
            dyn=t.u32(blob, i, LVL_DYN),
            settles=[s for s in sid if s],
        ))
    return out


def build_settle_evidence(blob: bytes, tables: list[Table]) -> dict[int, list[str]]:
    """settleID -> [human-readable source, ...] from level tables."""
    ev: dict[int, list[str]] = defaultdict(list)
    labels = [
        ("Level.bytes", dict(stride=LVL_STRIDE, rows=35, anchors={(0, 0): 1, (1, 0): 2})),
        ("TrainingLevel", dict(stride=936, rows=33, anchors={(0, 0): 7})),
        ("BurningLevel", dict(stride=LVL_STRIDE, rows=6, anchors={(0, 0): 30501})),
        ("ArenaLevel", dict(stride=LVL_STRIDE, rows=1, anchors={(0, 0): 30601})),
    ]
    for label, want in labels:
        try:
            t = find_table(tables, blob, want)
        except LookupError:
            continue
        for row in level_rows(blob, t):
            if not row["settles"]:
                continue
            ch = row["chapter"]
            chapter = PVE_CHAPTERS.get(ch, f"chapter{ch}" if ch else "")
            desc = f"{label} cfg {row['cfg']} {row['name']}".strip()
            extra = []
            if chapter:
                extra.append(chapter)
            if row["stage"]:
                extra.append(f"第{row['stage']}关")
            if row["difficulty"] and row["difficulty"] != 1:
                extra.append(f"难度{row['difficulty']}")
            if extra:
                desc += "(" + "/".join(extra) + ")"
            for sid in row["settles"]:
                if desc not in ev[sid]:
                    ev[sid].append(desc)
    return ev


# ---------------------------------------------------------------------------
# AcntBattleLevel
# ---------------------------------------------------------------------------
def classify_usage(name: str, subtype: int, level_switch: int, max_acnt: int,
                   dyn: int) -> tuple[str, str]:
    """Return (usage, exclusion_reason)."""
    if dyn == 1010001:
        return "quick_mode", "快速/娱乐模式(cfg1010001)"
    if dyn == 5262:
        return "10v10", "10v10/神祈战场(cfg5262)"
    if level_switch in (62, 63, 64) or "练习场" in name or "修炼" in name:
        return "practice", "英雄练习/修炼模式"
    if "OB" in name or "观战" in name:
        return "live_broadcast", "OB/观战录制"
    if any(k in name for k in ("CE用", "性能测试", "功能开发", "性能测试AB")):
        return "test", "CE/性能测试/功能开发用"
    if "人机" in name or "绝悟" in name:
        return "ai_match", "人机/绝悟 AI 对局"
    if any(k in name for k in ("弹幕", "梦之队", "冰雪", "缩小版", "简化版",
                               "4.0", "2v2", "新英雄", "CS模式")):
        return "special_variant", "娱乐/活动/特殊玩法变体"
    if dyn == 1:
        if max_acnt != 10:
            return "debug", f"cfg1 但 bMaxAcntNum={max_acnt}，非 10 人调试变体"
        if subtype == 0:
            return "draft", ""
        if subtype == 7:
            return "normal_match", ""
        return "variant", f"bBattleMatchSubType={subtype} 普通 5v5 变体"
    if max_acnt == 6:
        return "3v3_mode", f"bMaxAcntNum=6 (3v3)"
    if max_acnt == 4:
        return "2v2_mode", f"bMaxAcntNum=4"
    if max_acnt == 2:
        return "1v1_mode", f"bMaxAcntNum=2 (1v1)"
    if max_acnt == 20:
        return "10v10", "bMaxAcntNum=20 (10v10)"
    return "other_mode", f"cfg{dyn} bMaxAcntNum={max_acnt}"


def decode_levels(blob: bytes, t: Table, rates: dict[int, dict]) -> list[dict]:
    h = table_string_hash(blob, t)
    out = []
    for i in range(t.rows):
        lid = t.u32(blob, i, F_ID)
        dyn = t.u32(blob, i, F_DYN)
        name = sref(blob, t, h, i, F_NAME)
        subtype = t.u8(blob, i, F_SUBTYPE)
        max_acnt = t.u8(blob, i, F_MAX_ACNT)
        lvl_switch = t.u32(blob, i, F_LEVEL_SWITCH)
        usage, exclusion = classify_usage(name, subtype, lvl_switch, max_acnt, dyn)
        rate = rates.get(dyn, {})
        out.append(dict(
            row_index=i,
            level_id=lid,
            name=name,
            name_confidence=resolve_ref(blob, t, h, t.row(blob, i) + F_NAME)[1],
            design_file=sref(blob, t, h, i, F_DESIGN),
            artist=sref(blob, t, h, i, F_ARTIST),
            map_path=sref(blob, t, h, i, F_MAP),
            mirror_map_path=sref(blob, t, h, i, F_MAP_MIRROR),
            big_map_path=sref(blob, t, h, i, F_BIG_MAP),
            mirror_big_map_path=sref(blob, t, h, i, F_BIG_MAP_MIRROR),
            dynamic_property_cfg=dyn,
            mode_class=("normal_5v5" if dyn == 1 else
                        "quick" if dyn == 1010001 else
                        "10v10" if dyn == 5262 else f"other_cfg{dyn}"),
            mode_label=MODE_LABELS.get(dyn, f"其它 cfg{dyn}"),
            bBattleMatchSubType=subtype,
            bIsCanPVP=t.u8(blob, i, F_PVP),
            bIsCanPVE=t.u8(blob, i, F_PVE),
            bMaxAcntNum=max_acnt,
            bMaxCamp=t.u8(blob, i, F_MAX_CAMP),
            bHeroNum=t.u8(blob, i, F_HERO_NUM),
            level_switch_id=lvl_switch,
            bSettleRule=t.u8(blob, i, F_SETTLE_RULE),
            bDisableCoin=t.u8(blob, i, F_DISABLE_COIN),
            bDisableExp=t.u8(blob, i, F_DISABLE_EXP),
            wOriginalGoldCoinInBattle=t.u16(blob, i, F_GOLD),
            bIsOpenExpCompensate=t.u8(blob, i, F_OPEN_EXP),
            bIsOpenCoinCompensate=t.u8(blob, i, F_OPEN_COIN),
            exp_compensate_5pairs=pair_array(blob, t, i, F_EXP_ARR),
            coin_compensate_5pairs=pair_array(blob, t, i, F_COIN_ARR),
            iSoldierActivateCountDelay1=t.u32(blob, i, F_SOLDIER1),
            iSoldierActivateCountDelay2=t.u32(blob, i, F_SOLDIER2),
            iSoldierActivateDelay=t.u32(blob, i, F_SOLDIER_DELAY),
            dwCompensateExpBuffID=t.u32(blob, i, F_EXP_BUFF),
            dwCompensateGoldBuffID=t.u32(blob, i, F_GOLD_BUFF),
            dwAidNotShareIncomeLastTime=t.u32(blob, i, F_AID_SHARE),
            iMapWidth=t.u32(blob, i, F_MAP_W),
            iMapHeight=t.u32(blob, i, F_MAP_H),
            dwReviveTime=t.u32(blob, i, F_REVIVE),
            natural_gold_rate_min=rate.get("rate_min", ""),
            natural_gold_rate_max=rate.get("rate_max", ""),
            natural_gold_start_ms=rate.get("start_ms", ""),
            natural_gold_interval_ms=rate.get("interval_ms", ""),
            usage=usage,
            is_normal5v5_core=0 if exclusion else 1,
            exclusion_reason=exclusion,
        ))
    return out


# ---------------------------------------------------------------------------
# CommonSettle
# ---------------------------------------------------------------------------
def parse_sid(sid: int) -> tuple[int | None, int | None, int | None, str]:
    """Parse settleID digits F/V/T for 3-digit ids (family 1..8)."""
    if 900 <= sid <= 999:
        # 901..906 belong to the 9xx-18xx account/level-band series
        return None, None, None, "level_band"
    if 100 <= sid <= 899:
        return (sid // 100) % 10, (sid // 10) % 10, sid % 10, "tier"
    if 1000 <= sid <= 9999:
        # 10xx..18xx are account/level-band rewards, not F/V/T ids
        return None, None, None, "level_band"
    return None, None, None, "special"


def decode_settles(blob: bytes, t: Table) -> list[dict]:
    out = []
    for i in range(t.rows):
        rec = {name: t.u32(blob, i, off) for name, off in CS_FIELDS}
        fam, var, tier, shape = parse_sid(rec["dwSettleID"])
        out.append(dict(
            row_index=i,
            settle_id=rec["dwSettleID"],
            settle_by_id=rec["dwSettleByID"],
            family=(rec["dwSettleByID"] // 1000) if rec["dwSettleByID"] else 0,
            variant=var,
            tier=tier,
            id_shape=shape,
            add_acnt_exp=rec["dwAddAcntExp"],
            add_acnt_exp_1st=rec["dwAddAcntExp1stTime"],
            fail_add_acnt_exp=rec["dwFailAddAcntExp"],
            add_hero_exp=rec["dwAddHeroExp"],
            add_coin=rec["dwAddCoin"],
            add_coin_1st=rec["dwAddCoin1stTime"],
            game_over_check_time=rec["dwGameOverCheckTime"],
            is_random_at_begin=rec["bIsRandomAtBegin"],
            anti_cheat_detail=u32_array(blob, t, i, CS_ANTI),
            random_reward_detail=u32_array(blob, t, i, CS_RANDOM),
            first_complete_reward=u32_array(blob, t, i, CS_FIRST),
            raids_reward=u32_array(blob, t, i, CS_RAIDS),
        ))
    return out


def classify_settle(r: dict, evidence: dict[int, list[str]]) -> tuple[str, str, str]:
    """Return (category, confidence, evidence_text)."""
    sid, by, fam = r["settle_id"], r["settle_by_id"], r["family"]
    src = evidence.get(sid, [])

    if by == 0:
        return ("excluded_training", "high",
                "; ".join(src) or "TrainingLevel 族(2001-2012/4003-4008/41001/41002)")
    if by == 1011:
        # Group 1011 is shared: small ids are tutorials/basic training,
        # while 111/121/131/141 are PVE chapter-1 stage-1 tiers.
        if (r["id_shape"] == "tier" and 1 <= (r["variant"] or 0) <= 4
                and 1 <= (r["tier"] or 0) <= 4):
            return ("excluded_pve_chapter", "high",
                    "; ".join(src) or "Level.bytes 剧情第一章第1关")
        if src:
            return "excluded_tutorial", "high", "; ".join(src)
        return ("excluded_tutorial_or_test", "medium",
                "Level.bytes 教学族(1011)；本行无直接关卡引用，按组内同族判定")
    if 1000 < by < 5000:
        return ("excluded_pve_chapter", "high",
                "; ".join(src) or f"PVE 剧情第{fam}章(Level.bytes SettleIDDetail)")
    if by == 20026 or 30001 <= by <= 30025:
        return ("excluded_pve_activity", "high" if by == 20026 else "medium",
                "; ".join(src) or "BurningLevel/ArenaLevel 同族活动结算")
    if 5000 <= by < 6000:
        if r["id_shape"] == "tier" and 1 <= (r["variant"] or 0) <= 4:
            conf = "medium"
        else:
            conf = "low"
        return ("normal5v5_primary", conf,
                "无任何关卡表引用；PVP 族中 5xxx 行数最多(126)，含 9xx-18xx/105xx-118xx "
                "等级段奖励，判为普通 5v5 主结算族(结构+数值推断，无直连表)")
    if 6000 <= by < 7000:
        return ("normal5v5_secondary", "low",
                "无任何关卡表引用；第二 PVP 族(exp/coin 高于 5xxx)，10v10 / 排位 5v5 候选")
    if 7000 <= by < 9000:
        return ("pvp_other", "low",
                "只有失败行(participation)，无胜利档；1v1/3v3/自定义等小玩法候选")
    return ("unknown", "low", "")


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------
LEVEL_FIELDS = [
    "row_index", "level_id", "name", "name_confidence", "design_file", "artist",
    "map_path", "mirror_map_path", "big_map_path", "mirror_big_map_path",
    "dynamic_property_cfg", "mode_class", "mode_label",
    "bBattleMatchSubType", "bIsCanPVP", "bIsCanPVE", "bMaxAcntNum", "bMaxCamp",
    "bHeroNum", "level_switch_id", "bSettleRule", "bDisableCoin", "bDisableExp",
    "wOriginalGoldCoinInBattle", "bIsOpenExpCompensate", "bIsOpenCoinCompensate",
    "exp_compensate_5pairs", "coin_compensate_5pairs",
    "iSoldierActivateCountDelay1", "iSoldierActivateCountDelay2",
    "iSoldierActivateDelay", "dwCompensateExpBuffID", "dwCompensateGoldBuffID",
    "dwAidNotShareIncomeLastTime", "iMapWidth", "iMapHeight", "dwReviveTime",
    "natural_gold_rate_min", "natural_gold_rate_max", "natural_gold_start_ms",
    "natural_gold_interval_ms", "usage", "is_normal5v5_core", "exclusion_reason",
]

SETTLE_FIELDS = [
    "row_index", "settle_id", "settle_by_id", "family", "variant", "tier",
    "id_shape", "add_acnt_exp", "add_acnt_exp_1st", "fail_add_acnt_exp",
    "add_hero_exp", "add_coin", "add_coin_1st", "game_over_check_time",
    "is_random_at_begin", "anti_cheat_detail", "random_reward_detail",
    "first_complete_reward", "raids_reward", "group_semantics",
    "category", "confidence", "evidence", "candidate_level_count",
    "candidate_levels_sample", "notes",
]

GROUP_SEMANTICS = {
    0: "training",
    1: "pve_chapter_1",
    2: "pve_chapter_2",
    3: "pve_chapter_3",
    4: "pve_chapter_4",
    5: "pvp_family_5_candidate_normal_5v5",
    6: "pvp_family_6_candidate_10v10_or_ranked",
    7: "pvp_family_7_candidate_small_mode",
    8: "pvp_family_8_candidate_small_mode",
    20: "pve_activity_burning_or_arena",
    30: "pve_activity_event",
}


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--all-levels", action="store_true",
                    help="输出全部 99 行（默认只输出 63 个 cfg1 行）")
    args = ap.parse_args()

    blob = args.db.read_bytes()
    tables = iter_tables(blob)

    acnt = find_table(tables, blob, dict(
        stride=ACNT_STRIDE, rows=ACNT_ROWS,
        anchors={(0, F_ID): 20001, (1, F_ID): 25001, (2, F_ID): 25002}))
    cs = find_table(tables, blob, dict(
        stride=CS_STRIDE, rows=CS_ROWS,
        anchors={(0, 0x00): 1, (0, 0x08): 1011, (1, 0x00): 2}))
    _, rates = load_natural_gold(blob, tables)
    evidence = build_settle_evidence(blob, tables)

    levels = decode_levels(blob, acnt, rates)
    # sanity: positional string resolution must produce the known 5v5 name
    if levels[0]["name"] != "墨家机关道":
        raise RuntimeError(
            f"string resolution failed: row0 name={levels[0]['name']!r} "
            f"conf={levels[0]['name_confidence']}")

    cfg1 = [x for x in levels if x["mode_class"] == "normal_5v5"]
    core = [x for x in cfg1 if not x["exclusion_reason"]]
    csv_levels = levels if args.all_levels else cfg1
    level_ids = [x["level_id"] for x in cfg1]
    sample = ";".join(str(x) for x in level_ids[:12]) + "..."

    settles = decode_settles(blob, cs)
    for r in settles:
        category, conf, ev = classify_settle(r, evidence)
        r["category"] = category
        r["confidence"] = conf
        r["evidence"] = ev
        if category.startswith("excluded_tutorial"):
            r["group_semantics"] = "tutorial_or_basic_training"
        else:
            r["group_semantics"] = GROUP_SEMANTICS.get(r["family"], "unknown")
        if category.startswith(("normal5v5", "pvp_other")):
            r["candidate_level_count"] = len(level_ids)
            r["candidate_levels_sample"] = sample
            r["notes"] = (
                "快速 cfg1010001/10v10 cfg5262 关卡共用 PVP 结算通道；"
                "CommonSettle 无快速/10v10 专属行，模式区分只能落在关卡 cfg 层")
        else:
            r["candidate_level_count"] = 0
            r["candidate_levels_sample"] = ""
            r["notes"] = "已由关卡表 SettleIDDetail/训练表直接排除" if evidence.get(r["settle_id"]) else ""

    write_csv(args.out / "agent_normal5v5_levels.csv", LEVEL_FIELDS, csv_levels)
    write_csv(args.out / "agent_normal5v5_settles.csv", SETTLE_FIELDS, settles)

    groups = defaultdict(list)
    for r in settles:
        groups[r["category"]].append(r)
    print(f"dc.db={args.db}")
    print(f"AcntBattleLevel: {acnt.rows} rows, 63 cfg1 -> {len(cfg1)}, "
          f"core normal 5v5 (no exclusion)={len(core)}")
    print(f"  cfg1 natural-gold rate={rates.get(1)}")
    print(f"  quick rate={rates.get(1010001)}; 10v10 rate={rates.get(5262)}")
    print(f"CommonSettle: {cs.rows} rows / {len(groups)} categories")
    for cat in sorted(groups):
        rows = groups[cat]
        bys = sorted({r["settle_by_id"] for r in rows})
        print(f"  {cat:<28} rows={len(rows):<4} settleByID={bys[:8]}"
              f"{'...' if len(bys) > 8 else ''}")
    print(f"wrote {args.out / 'agent_normal5v5_levels.csv'}")
    print(f"wrote {args.out / 'agent_normal5v5_settles.csv'}")


if __name__ == "__main__":
    main()
