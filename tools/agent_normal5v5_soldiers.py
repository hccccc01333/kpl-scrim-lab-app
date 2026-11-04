#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""普通 5v5：兵种名、soldierWave 波次结构与 3xxx/4xxx/5xxx 结算条件（只读）。

结论口径
--------
1. 缺失的 ``soldierWave`` 表其实在 ``dc.db`` 内，是服务端 ``stdr`` 表：
   ``@0x1791ad8``，stride **312**，rows **957**，无字符串池。布局与
   ``ResData.ResSoldierWaveInfo``（15 字段）精确闭合：

       +0x000 dwSoldierWaveID                 u32     行键
       +0x004 bRouteType/bCamp/bType/bSpecifyBornPos 4 × u8
       +0x008 astBranchWaves                  5 × 8B  (全 0)
       +0x030 dwNextSoldierWaveID             u32
       +0x034 dwRepeatNum                     u32
       +0x038 dwRepeatTimeTick               u32
       +0x03C dwStartWatiTick                 u32
       +0x040 dwIntervalTick                  u32
       +0x044 iSpawnInterval                  u32
       +0x048 astNormalSoldierInfo            15 × 16B
       total = 0x48 + 240 = 312

   ``astNormalSoldierInfo`` 元素 = ``ResData.ResSoldierTypeInfo``：
   ``dwSoldierID | dwSoldierNum | bBornPosIdx | dwInitRandPassSkillRule``。

2. 普通 5v5 的兵种名来自 ``normalMonster @0x679118``，不是 3xxx/4xxx/5xxx：
   蓝/红方战士 ``bSoldierType=1``（MELEE）、蓝/红方法师 ``=2``（REMOTE）、
   弩车/炮车/机关战士 ``=3``（SUPER）。

3. ``CommonSettle @0x106464`` 的 ``dwSettleByID`` 全部（387 个非零值）
   命中 ``EvaluateCond``（block 143，178 行）。3xxx/4xxx/5xxx 是
   **PVE 星级/结算条件 ID**，不是近战/远程/炮车兵种组。例：
   3041=击败始皇嬴政、4021=击败魔种·炎怒、5041=击败传送机关师孙膑。
   文档 5.77 的“3/4/5/6=单位组”、5.75 的“6xxx=腥红石像/红方弩兵/赤甲”
   都是 ``dvSettleByID`` 与 ``normalMonster.id`` 的同名巧合。

只读边界
--------
* 只读 ``dc.db``、``dtab_blocks/143_EvaluateCond.bytes.bin``、
  ``datasets/normalMonster_rows.csv``（可选校验）；不修改回放，
  不注入进程，不读取 param.json，不使用 runtime_dump 历史内存。
* 所有关键字段自带锚点校验，失败即中止，不静默猜测。

输出
----
* ``data/replays/_analysis/datasets/agent_normal5v5_soldiers.csv``
  wave_slot / evaluate_cond 两类记录
* ``data/replays/_analysis/datasets/agent_normal5v5_soldiers_levels.csv``
  AcntBattleLevel 99 行（含 is_cfg1；不覆盖既有的 63 行 levels.csv）
* ``data/replays/_analysis/datasets/agent_normal5v5_soldiers_report.md``

用法::

    python tools/agent_normal5v5_soldiers.py
    python tools/agent_normal5v5_soldiers.py --db path/to/dc.db --out dir
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
# table anchors
# ---------------------------------------------------------------------------
ACNT_POS = 0x14660
ACNT_STRIDE = 1240
ACNT_ROWS = 99

MONSTER_POS = 0x679118
MONSTER_STRIDE = 584
MONSTER_ROWS = 2625
MONSTER_SOLDIER_TYPE = 0xCE       # +206, validated against RES_SOLDIER_TYPE

SETTLE_POS = 0x106464
SETTLE_STRIDE = 120
SETTLE_ROWS = 388

WAVE_POS = 0x1791AD8
WAVE_STRIDE = 312
WAVE_ROWS = 957

EVAL_STRIDE = 128
EVAL_ROWS = 178

# AcntBattleLevel / ResAcntBattleLevelInfo
C = 0x008            # stLevelCommonInfo
G = 0x350            # stLevelGamePlayInfo
F_SUBTYPE = 0x004
F_PVP = 0x005
F_PVE = 0x006
F_NAME = C + 0x000
F_DESIGN = C + 0x008
F_MAX_ACNT = C + 0x041
F_MAX_CAMP = C + 0x060
F_HERO_NUM = C + 0x088
F_LEVEL_SWITCH = C + 0x1F4
F_GOLD = G + 0x000
F_SOUL_CFG = G + 0x0C4
F_SOLDIER_DELAY1 = G + 0x0C8
F_SOLDIER_DELAY2 = G + 0x0CC
F_SOLDIER_DELAY_MS = G + 0x0D0
F_DYN = G + 0x0DC
F_EXP_BUFF = G + 0x0E0
F_GOLD_BUFF = G + 0x0E4

# RES_SOLDIER_TYPE（ResData）前 37 项，按 metadata 顺序
SOLDIER_TYPES = [
    "OTHERS", "MELEE", "REMOTE", "SUPER", "ANYINGDAJIANG", "HEIANXIANFENG",
    "BAOZOUJIANGSHI", "BAOJUN", "BARON", "BIGDRAGON", "BLUEBA", "REDBA",
    "JIANGSHICHANGMAOSHU", "FireHole", "MONEYBA", "RUNAWAYCAT",
    "DOMINATE_VANGUARD", "DARK_BIGDRAGON", "TRAP", "BEACON", "YELLOWBA",
    "PUPPET", "WATCHTOWER", "MONSTER_DEAD_STATE", "APPARATUS",
    "ACTIVECALLMONSTER", "XIAOZHUZAI", "LEVELMONSTERA", "YUANGUBAOJUN",
    "GEARBALL", "NIAN", "DUIKANG_RIVER_CAT", "MID_RIVER_CAT",
    "FAYU_RIVER_CAT", "FENGBAO_VANGUARD", "ANYING_VANGUARD", "CHIJIA",
]

# normal 5v5 wave series. Bases are the lane heads; the actual set is built by
# following dwNextSoldierWaveID, so child IDs such as 1623211 / 401223211 are
# included even though they are numerically larger than the lane-head range.
SERIES_BASES = {
    "5v5_6000": [320, 322, 324, 326, 328, 330] + list(range(340, 348)) + list(range(364, 370)) + list(range(2346, 2352)),
    "5v5_1660": [162320, 162322, 162324, 162326, 162328, 162330] + list(range(162340, 162358)),
    "5v5_4010": [40102320, 40102322, 40102324, 40102326, 40102328, 40102330] + list(range(40102340, 40102358)),
    "5v5_4012": [40122320, 40122322, 40122324, 40122326, 40122328, 40122330] + list(range(40122340, 40122358)),
    "5v5_10103": [10112320, 10112322, 10112324, 10112326, 10112328, 10112330] + list(range(10112340, 10112358)),
    "5v5_early_1_2": [101, 102, 103, 104],
}
SERIES_NOTES = {
    "5v5_6000": "classic 6000-series: 3 lanes; 7x warrior+2 mages -> warrior+mage+siege; super & boss waves",
    "5v5_1660": "1660-series: 8x early exp-mage -> 11x warrior+mage+siege -> cannon; super & boss waves",
    "5v5_4010": "4010-series: 8x early exp-mage -> 11x siege -> cannon; super & boss waves",
    "5v5_4012": "4012-series: 6x early exp-mage -> 10x siege -> cannon; super & boss waves",
    "5v5_10103": "10103-series: 4x early exp-mage -> 6x siege -> cannon; super & boss waves",
    "5v5_early_1_2": "early 1/2/4/5 template; 9x warrior+mage then cannon",
}


# ---------------------------------------------------------------------------
# stdr helpers
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


def table_at(blob: bytes, pos: int, stride: int, rows: int) -> Table:
    assert blob[pos:pos + 4] == b"stdr", f"no stdr at {pos:#x}"
    st = struct.unpack_from("<I", blob, pos + 0x14)[0]
    nr = struct.unpack_from("<I", blob, pos + 0x18)[0]
    ns = struct.unpack_from("<I", blob, pos + 8)[0]
    pr = struct.unpack_from("<I", blob, pos + 0x90)[0]
    assert (st, nr) == (stride, rows), f"table mismatch at {pos:#x}: {st}/{nr}"
    assert 0x98 + stride * rows == pr, f"pool does not start at row end at {pos:#x}"
    return Table(pos, stride, rows, ns, pr)


def find_table(blob: bytes, stride: int, rows: int, anchors: dict[tuple[int, int], int]) -> Table:
    s = 0
    while True:
        p = blob.find(b"stdr", s)
        if p < 0:
            raise LookupError(f"table stride={stride} rows={rows} not found")
        s = p + 1
        try:
            t = table_at(blob, p, stride, rows)
        except AssertionError:
            continue
        if all(struct.unpack_from("<I", blob, t.row(blob, r) + o)[0] == v
               for (r, o), v in anchors.items()):
            return t
    # unreachable


def parse_pool(blob: bytes, t: Table, limit: int | None = None) -> list[str]:
    out: list[str] = []
    q = t.pool
    limit = limit if limit is not None else max(t.nstr, 1)
    while len(out) < limit and q + 8 < len(blob):
        z = blob.find(b"\x00", q + 8, min(len(blob), q + 8 + 4096))
        if z < 0:
            break
        try:
            out.append(blob[q + 8:z].decode("utf-8"))
        except UnicodeDecodeError:
            break
        q = (z + 1 + 3) & ~3
    return out


def has_cjk(s: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in s)


def resolve_table_string(blob: bytes, t: Table, value32: int) -> str:
    """Positional string ref (5.79): file offset = value32 >> 6; text at +8."""
    if not value32:
        return ""
    rec = t.pos + (value32 >> 6)
    if rec < t.pool or rec + 8 >= len(blob):
        return ""
    z = blob.find(b"\x00", rec + 8, min(len(blob), rec + 8 + 2048))
    if z < 0:
        return ""
    try:
        return blob[rec + 8:z].decode("utf-8")
    except UnicodeDecodeError:
        return ""


# ---------------------------------------------------------------------------
# normalMonster
# ---------------------------------------------------------------------------
def parse_normal_monster(blob: bytes) -> dict[int, dict]:
    t = table_at(blob, MONSTER_POS, MONSTER_STRIDE, MONSTER_ROWS)
    strings = parse_pool(blob, t)
    names = [x for x in strings if has_cjk(x) and "/" not in x and "." not in x]

    first: dict[int, int] = {}
    order: list[int] = []
    rows: list[tuple[int, int, int]] = []
    for i in range(t.rows):
        row = t.row(blob, i)
        ref1 = struct.unpack_from("<I", blob, row + 12)[0]
        if ref1 not in first:
            first[ref1] = len(order)
            order.append(ref1)
        rows.append((i, struct.unpack_from("<I", blob, row)[0], ref1))

    out: dict[int, dict] = {}
    for i, rid, ref1 in rows:
        row = t.row(blob, i)
        oi = first[ref1]
        name = names[oi] if oi < len(names) else f"?{oi}"
        hp, = struct.unpack_from("<i", blob, row + 28)
        hp2, = struct.unpack_from("<i", blob, row + 36)
        gold, = struct.unpack_from("<I", blob, row + 44)
        gold2, = struct.unpack_from("<I", blob, row + 48)
        exp1, = struct.unpack_from("<I", blob, row + 52)
        exp2, = struct.unpack_from("<I", blob, row + 56)
        exp3, = struct.unpack_from("<I", blob, row + 60)
        actor, = struct.unpack_from("<I", blob, row + 68)
        stype = blob[row + MONSTER_SOLDIER_TYPE]
        if rid not in out:
            out[rid] = dict(
                id=rid, row=i, name=name, hp=hp, hp2=hp2, gold=gold,
                gold2=gold2, exp1=exp1, exp2=exp2, exp3=exp3,
                actor_type_id=actor, soldier_type=stype,
            )

    # anchors: names and RES_SOLDIER_TYPE
    anchors = {
        1660002: ("蓝方战士", 1),
        1660032: ("红方战士", 1),
        2: ("蓝方法师", 2),
        5: ("红方法师", 2),
        6002: ("蓝方弩车", 3),
        6011: ("腥红石像", 11),
        6051: ("赤甲", 36),
    }
    for rid, (want_name, want_type) in anchors.items():
        got = out.get(rid)
        if not got or not got["name"].startswith(want_name) or got["soldier_type"] != want_type:
            raise SystemExit(
                f"normalMonster anchor failed id={rid}: "
                f"{got and got['name']!r}/{got and got['soldier_type']} != {want_name}/{want_type}"
            )
    return out


def soldier_type_name(v: int) -> str:
    n = SOLDIER_TYPES[v] if 0 <= v < len(SOLDIER_TYPES) else f"TYPE_{v}"
    return f"{n}({v})"


# ---------------------------------------------------------------------------
# soldierWave
# ---------------------------------------------------------------------------
def parse_soldier_wave(blob: bytes) -> dict[int, dict]:
    t = table_at(blob, WAVE_POS, WAVE_STRIDE, WAVE_ROWS)
    out: dict[int, dict] = {}
    for i in range(t.rows):
        row = t.row(blob, i)
        key, = struct.unpack_from("<I", blob, row + 0x00)
        flags, = struct.unpack_from("<I", blob, row + 0x04)
        nxt, rep, reptick, start, interval, spawn = struct.unpack_from("<6I", blob, row + 0x30)
        arr = []
        for k in range(15):
            o = row + 0x48 + k * 16
            sid, num, born, rule = struct.unpack_from("<IIII", blob, o)
            if sid:
                arr.append(dict(soldier_id=sid, count=num, born_pos=born, rand_rule=rule))
        out[key] = dict(
            key=key, row=i, flags=flags,
            route=flags & 0xFF, camp=(flags >> 8) & 0xFF,
            wtype=(flags >> 16) & 0xFF, specify=(flags >> 24) & 0xFF,
            next=nxt, repeat=rep, repeat_tick=reptick,
            start_ms=start, interval_ms=interval, spawn_interval=spawn,
            soldiers=arr,
        )
    # anchors: 162321 chain and 2346 boss vanguard
    w = out.get(162321)
    assert w and w["next"] == 1623211 and w["repeat"] == 11 and w["interval_ms"] == 33000
    assert [s["soldier_id"] for s in w["soldiers"]] == [1660002, 166001, 166002]
    w = out.get(2346)
    assert w and w["next"] == 0 and w["repeat"] == 2
    assert [s["soldier_id"] for s in w["soldiers"]] == [6023]
    return out


# ---------------------------------------------------------------------------
# EvaluateCond
# ---------------------------------------------------------------------------
def parse_evaluate_cond(blob: bytes) -> dict[int, dict]:
    # dtab_blocks/*.bin may be header+rows only (no string pool); dc.db has the
    # full table incl. pool. Locate it by stride/rows and row-key anchors.
    t = find_table(blob, EVAL_STRIDE, EVAL_ROWS,
                   {(37, 0): 3011, (46, 0): 3041, (73, 0): 5011})
    out: dict[int, dict] = {}
    for i in range(t.rows):
        row = t.row(blob, i)
        key, = struct.unpack_from("<I", blob, row)
        _hash, value = struct.unpack_from("<II", blob, row + 8)
        out[key] = dict(key=key, row=i, text=resolve_table_string(blob, t, value))
    if out.get(3041, {}).get("text") != "击败始皇嬴政":
        raise SystemExit("EvaluateCond anchor 3041 failed")
    if out.get(4021, {}).get("text") != "击败魔种·炎怒":
        raise SystemExit("EvaluateCond anchor 4021 failed")
    return out


# ---------------------------------------------------------------------------
# CommonSettle
# ---------------------------------------------------------------------------
def parse_common_settle(blob: bytes) -> list[dict]:
    t = table_at(blob, SETTLE_POS, SETTLE_STRIDE, SETTLE_ROWS)
    out = []
    for i in range(t.rows):
        row = t.row(blob, i)
        sid, rand, by, exp, exp1, fail, heroexp, coin, coin1, check = struct.unpack_from(
            "<10I", blob, row)
        lvl, = struct.unpack_from("<I", blob, row + 0x50)
        out.append(dict(
            row=i, settle_id=sid, is_random=rand, settle_by_id=by,
            add_exp=exp, add_exp_1st=exp1, fail_exp=fail, add_hero_exp=heroexp,
            add_coin=coin, add_coin_1st=coin1, check_time=check, level_id=lvl,
        ))
    row = out[67]
    assert (row["settle_id"], row["settle_by_id"], row["add_exp"], row["add_coin"]) == (334, 3041, 126, 45)
    return out


# ---------------------------------------------------------------------------
# AcntBattleLevel
# ---------------------------------------------------------------------------
def parse_acnt_levels(blob: bytes) -> list[dict]:
    t = table_at(blob, ACNT_POS, ACNT_STRIDE, ACNT_ROWS)
    out = []
    for i in range(t.rows):
        row = t.row(blob, i)
        lid, = struct.unpack_from("<I", blob, row)
        _hn, name_ref = struct.unpack_from("<II", blob, row + F_NAME)
        _hd, design_ref = struct.unpack_from("<II", blob, row + F_DESIGN)
        out.append(dict(
            row=i, level_id=lid,
            name=resolve_table_string(blob, t, name_ref),
            design=resolve_table_string(blob, t, design_ref),
            subtype=blob[row + F_SUBTYPE],
            can_pvp=blob[row + F_PVP],
            can_pve=blob[row + F_PVE],
            max_acnt=blob[row + F_MAX_ACNT],
            max_camp=blob[row + F_MAX_CAMP],
            hero_num=blob[row + F_HERO_NUM],
            level_switch=struct.unpack_from("<I", blob, row + F_LEVEL_SWITCH)[0],
            gold=struct.unpack_from("<H", blob, row + F_GOLD)[0],
            soul_cfg=struct.unpack_from("<I", blob, row + F_SOUL_CFG)[0],
            soldier_delay1=struct.unpack_from("<i", blob, row + F_SOLDIER_DELAY1)[0],
            soldier_delay2=struct.unpack_from("<i", blob, row + F_SOLDIER_DELAY2)[0],
            soldier_delay_ms=struct.unpack_from("<i", blob, row + F_SOLDIER_DELAY_MS)[0],
            dyn_cfg=struct.unpack_from("<I", blob, row + F_DYN)[0],
            exp_buff=struct.unpack_from("<I", blob, row + F_EXP_BUFF)[0],
            gold_buff=struct.unpack_from("<I", blob, row + F_GOLD_BUFF)[0],
        ))
    cfg1 = [x for x in out if x["dyn_cfg"] == 1]
    assert len(cfg1) == 63, f"cfg1 levels = {len(cfg1)}"
    assert out[0]["name"] == "墨家机关道", out[0]["name"]
    return out


# ---------------------------------------------------------------------------
# wave rows -> CSV
# ---------------------------------------------------------------------------
def wave_role(soldiers: list[dict], monster: dict[int, dict]) -> str:
    names = [monster.get(s["soldier_id"], {}).get("name", "") for s in soldiers]
    if any("机关战士" in n for n in names):
        return "super_wave"
    if any("先锋" in n for n in names):
        return "boss_vanguard_wave"
    if any("炮车" in n for n in names):
        return "cannon_wave"
    if any("弩车" in n for n in names):
        return "siege_wave"
    if any("经验法师" in n for n in names):
        return "early_exp_mage_wave"
    return "normal_wave"


def build_series_map(waves: dict[int, dict]) -> dict[int, str]:
    out: dict[int, str] = {}
    for name, bases in SERIES_BASES.items():
        for base in bases:
            k = base
            while k and k in waves and k not in out:
                out[k] = name
                k = waves[k]["next"]
    return out


def build_wave_rows(waves: dict[int, dict], monster: dict[int, dict],
                    series_map: dict[int, str]) -> list[dict]:
    out = []
    for key in sorted(waves):
        series = series_map.get(key)
        if not series:
            continue
        conf = "medium" if series == "5v5_early_1_2" else "high"
        series_note = SERIES_NOTES[series]
        w = waves[key]
        if not w["soldiers"]:
            continue
        role = wave_role(w["soldiers"], monster)
        camp = {1: "blue", 2: "red"}.get(w["camp"], "")
        for idx, s in enumerate(w["soldiers"]):
            m = monster.get(s["soldier_id"], {})
            name = m.get("name") or f"soldier#{s['soldier_id']}"
            if not camp:
                if name.startswith("蓝"):
                    camp = "blue"
                elif name.startswith("红"):
                    camp = "red"
            out.append(dict(
                record_type="wave_slot",
                wave_id=key,
                series=series,
                camp=camp,
                route=w["route"] or "",
                wave_role=role,
                unit_group=soldier_type_name(m["soldier_type"]) if m else "UNKNOWN",
                name=name,
                count=s["count"],
                gold=m.get("gold", ""),
                exp=m.get("exp3", ""),
                hp=f"{m['hp']}/{m['hp2']}" if m else "",
                next_wave=w["next"] or "",
                repeat=w["repeat"],
                start_ms=w["start_ms"],
                interval_ms=w["interval_ms"],
                source=f"soldierWave@0x1791ad8 row={w['row']} key={key} slot={idx}",
                confidence=conf,
                note=(
                    f"flags=0x{w['flags']:X}; next={w['next']}; repeat={w['repeat']}; "
                    f"start={w['start_ms']}ms; interval={w['interval_ms']}ms; {series_note}"
                ),
            ))
    return out


def _brief(xs: list[int], n: int = 12) -> str:
    return ", ".join(map(str, xs[:n])) + (", ..." if len(xs) > n else "")


def build_eval_rows(settles: list[dict], evals: dict[int, dict]) -> list[dict]:
    by: dict[int, list[dict]] = defaultdict(list)
    for r in settles:
        if 3000 <= r["settle_by_id"] < 7000:
            by[r["settle_by_id"]].append(r)
    out = []
    for sid in sorted(by):
        rs = by[sid]
        ev = evals.get(sid, {})
        coins = sorted({r["add_coin"] for r in rs})
        exps = sorted({r["add_exp"] for r in rs})
        lvls = sorted({r["level_id"] for r in rs if r["level_id"]})
        settle_ids = sorted({r["settle_id"] for r in rs})
        out.append(dict(
            record_type="evaluate_cond",
            wave_id="",
            series="CommonSettle.settle_by_id",
            camp="",
            route="",
            wave_role="",
            unit_group="evaluate_cond",
            name=ev.get("text") or "(no text)",
            count=len(rs),
            gold="/".join(map(str, coins)),
            exp="/".join(map(str, exps)),
            hp="",
            next_wave="",
            repeat="",
            start_ms="",
            interval_ms="",
            source=f"CommonSettle@0x106464 -> EvaluateCond@block143 row={ev.get('row', '')}",
            confidence="high" if ev.get("text") else "medium",
            note=(
                "NOT a soldier group: PVE/结算条件 ID; "
                f"settle_ids=[{_brief(settle_ids)}]; level_ids@+0x50=[{_brief(lvls)}]; "
                "see docs/replay_binary_format.md 5.77 correction"
            ),
        ))
    # EvaluateCond-only rows (e.g. 3042/3043/4022/4023) that CommonSettle does
    # not directly reference; still useful for naming the 3xxx/4xxx/5xxx IDs.
    for sid in sorted(k for k in evals if 3000 <= k < 7000 and k not in by):
        ev = evals[sid]
        out.append(dict(
            record_type="evaluate_cond_only",
            wave_id="",
            series="EvaluateCond",
            camp="",
            route="",
            wave_role="",
            unit_group="evaluate_cond",
            name=ev.get("text") or "(no text)",
            count=0,
            gold="",
            exp="",
            hp="",
            next_wave="",
            repeat="",
            start_ms="",
            interval_ms="",
            source=f"EvaluateCond@block143 row={ev.get('row', '')}",
            confidence="high" if ev.get("text") else "low",
            note="EvaluateCond star/settle condition; NOT referenced by CommonSettle and NOT a soldier group",
        ))
    return out


# ---------------------------------------------------------------------------
# markdown report
# ---------------------------------------------------------------------------
def write_report(path: Path, wave_rows: list[dict], eval_rows: list[dict],
                 levels: list[dict], waves: dict[int, dict], monster: dict[int, dict]) -> None:
    cfg1 = [x for x in levels if x["dyn_cfg"] == 1]
    sub = defaultdict(int)
    for x in cfg1:
        sub[x["subtype"]] += 1
    switch = defaultdict(int)
    for x in cfg1:
        switch[x["level_switch"]] += 1

    def chain(series: str, start: int, limit: int = 6) -> list[str]:
        lines = []
        k = start
        seen = set()
        for _ in range(limit):
            w = waves.get(k)
            if not w:
                break
            comp = ", ".join(
                f"{monster.get(s['soldier_id'], {}).get('name', 'soldier#' + str(s['soldier_id']))}x{s['count']}"
                for s in w["soldiers"]
            )
            lines.append(
                f"| {k} | {comp} | {w['repeat']} | {w['start_ms']} | {w['interval_ms']} | {w['next'] or '-'} |"
            )
            if k in seen:
                break
            seen.add(k)
            k = w["next"]
            if not k:
                break
        return lines

    rep = f"""# 普通 5v5 兵种名 / 波次结构 / 3xxx-5xxx 结算条件

日期：2026-11-01  
范围：`dc.db`、`dtab_blocks`、`global-metadata.dat`、`libGameCore.so`（只读）  
产物：`agent_normal5v5_soldiers.csv`、`agent_normal5v5_soldiers_levels.csv`、本报告  
脚本：`tools/agent_normal5v5_soldiers.py`

## 1. 结论摘要

1. **`soldierWave` 表找到了**：`dc.db @0x1791ad8`，stdr，stride **312**，rows **957**，
   无字符串池。72 字节标量头 + 15 × 16B `ResSoldierTypeInfo` = 312，与
   `ResData.ResSoldierWaveInfo` 的 15 个字段精确闭合。它是服务端表，
   所以不在 825 张客户端 databin / `dtab_all` 里。
2. **普通 5v5 的波次可解**：表内有多套 5v5 波次链（6000 / 1660 / 4010 / 4012 /
   10103 系列），每套给出 `waveID → 下一波 → 重复次数 → 开始等待 → 间隔 →
   每槽兵种与数量`。兵种数量按表内 `dwSoldierNum` 直接读取。
3. **3xxx/4xxx/5xxx 不是兵种组**：`CommonSettle` 388 行里 369 个非零
   `dwSettleByID` 全部命中 `EvaluateCond`（另 19 行为 0）。3041=击败始皇嬴政、
   4021=击败魔种·炎怒、5041=击败传送机关师孙膑。文档 5.77 的
   “3/4/5/6=单位组” 需要修正；6xxx 的“腥红石像/红方弩兵/赤甲”只是
   `normalMonster.id` 同名巧合。
4. **普通 5v5 兵种名**来自 `normalMonster`：蓝/红方战士（MELEE=1）、
   蓝/红方法师（REMOTE=2）、弩车/炮车/机关战士（SUPER=3）。
5. **63 个 cfg1 关卡**全部 `gold=300`、`soulCfg=4`、`soldierDelay1=0`、
   `soldierDelay2=5500`、`soldierDelayMs=10000`；55/63 的
   `dwLevelSwitchID=6`。关卡行内没有 waveID 字段。

## 2. 3xxx/4xxx/5xxx 的真实身份

`CommonSettle @0x106464`（stride 120，388 行）字段：

```
+0x00 dwSettleID | +0x04 bIsRandomAtBegin | +0x08 dwSettleByID
+0x0C dwAddAcntExp | +0x10 dwAddAcntExp1stTime | +0x14 dwFailAddAcntExp
+0x18 dwAddHeroExp | +0x1C dwAddCoin | +0x20 dwAddCoin1stTime
+0x24 dwGameOverCheckTime | +0x50 level_id (empirical)
```

`dwSettleByID` 与 `EvaluateCond`（block `143_EvaluateCond.bytes.bin`，
stride 128，178 行，`+0x08` 字符串 ref）逐行对上：

| settle_by_id | EvaluateCond 文本 | CommonSettle 引用 | 结论 |
|---:|---|---|---|
| 3041 | 击败始皇嬴政 | 是（6 行，含关卡档） | PVE 第三章条件 |
| 3042 | 击败山谷中的高渐离 | 否（仅 EvaluateCond） | PVE 第三章星级条件 |
| 3043 | 保护阿轲不能死亡 | 否（仅 EvaluateCond） | PVE 第三章星级条件 |
| 4021 | 击败魔种·炎怒 | 是（6 行） | PVE 第四章条件 |
| 4022 | 战斗中没有英雄阵亡 | 否（仅 EvaluateCond） | PVE 第四章星级条件 |
| 4023 | 找到躲在洞窟中的廉颇 | 否（仅 EvaluateCond） | PVE 第四章星级条件 |
| 4031 | 击败血族之王徐福 | 是（6 行） | PVE 第四章条件 |
| 5041 | 击败传送机关师孙膑 | 是（6 行） | PVE 第五章条件 |
| 6011 | 击败钟无艳和她的神秘助手 | 是（6 行） | PVE 第六章条件 |
| 6061 | 击败妖后芈月 | 是（2 行） | PVE 第六章条件 |

CommonSettle 实际只引用 24 个 4 位 `settle_by_id`：3011/3021/3031/3041/
3051/3061、4011…4061、5011…5061、6011…6061。3042/3043/4022/4023 等
只存在于 `EvaluateCond` 星级表，未被 CommonSettle 直接引用。

Level ID 证据：3041 的 CommonSettle 行 `level_id=20314/20324/20334/20344`，
6011 行为 `20611/20621/20631/20641`，均落在 PVE 章节关卡段（20xxx）；
不是 PVP 5v5 关卡。5xxx 的 5011–5041 主行同样是 `20511…20544`。

- **不是**“近战/远程/炮车/超级兵”分组；
- `soldierWave` 行键里只有 **4021**（红方防御波：红方战士/后期法师/炮车），
  没有 3041/3042/3043/4022/4023/5011/5041；所以这些 ID 也不是 waveID。
  4021 在 soldierWave 是红方波次，在 EvaluateCond 是“击败魔种·炎怒”，
  属于同名不同命名空间。
- 客户端 `Level.bytes` 的 301–404 行（PVE 第三/四章）在 `+0x74` 存
  `3011/3012/3013 … 4041/4042/4043`，与 `EvaluateCond` 星级条件一一对应，
  所以这些也不是普通 5v5 的 waveID。`AcntBattleLevel` 行内没有该三连。
- 5011 等行在表内复用了别的条件描述串（例如 5011 指向“击败怪医扁鹊”），
  说明 `EvaluateCond` 文本可能被多条条件共用；但 `EvaluateCond` 没有任何
  “兵种组”语义，不能据此给 3xxx/4xxx/5xxx 贴“近战/远程/炮车”标签。
  5xxx 是否为普通 5v5 结算族仍需服务端关卡引用表，当前 dump 不能确认。

## 3. soldierWave 表布局与普通 5v5 波次

### 3.1 表布局

`dc.db @0x1791ad8`，stdr，stride 312，rows 957，`+0x08=0`、`+0x90=0x48EF0`，
`0x98 + 312 × 957 = 0x48EF0`。

| 偏移 | 字段 | 宽度 | 说明 |
|---:|---|---:|---|
| +0x00 | dwSoldierWaveID | 4 | 行键 = waveID |
| +0x04 | bRouteType/bCamp/bType/bSpecifyBornPos | 4×1 | 例 0x010101 = route1/camp1/type1 |
| +0x08 | astBranchWaves | 40 | 5 × `{{dwBranchWaveID,bBranchWaveP}}`，观测全 0 |
| +0x30 | dwNextSoldierWaveID | 4 | 下一波 |
| +0x34 | dwRepeatNum | 4 | 重复次数 |
| +0x38 | dwRepeatTimeTick | 4 | 观测 0 |
| +0x3C | dwStartWatiTick | 4 | 首次等待 ms |
| +0x40 | dwIntervalTick | 4 | 波间隔 ms |
| +0x44 | iSpawnInterval | 4 | 观测 0 |
| +0x48 | astNormalSoldierInfo | 240 | 15 × 16B `ResSoldierTypeInfo` |

`ResSoldierTypeInfo`：`dwSoldierID | dwSoldierNum | bBornPosIdx | dwInitRandPassSkillRule`。
本表所有样本 `bornPos=0, randRule=0`，数量在 `dwSoldierNum`。

**表身份交叉验证**：`normalMonster` 的 Boss 行 `iKillByCampXChange*SoldierWave`
字段直接引用本表行键，且引用目标内容与 Boss 名一致：

| normalMonster 行 | 名称 | 引用 waveID | soldierWave 内容 |
|---:|---|---:|---|
| 6009 | 暗影主宰 | 2346 / 2347 | 主宰先锋 x1 |
| 6018 | 主宰 | 2348 / 2349 | 小主宰先锋 x1 |
| 60221 | 风暴龙王 | 2350 / 2351 | 风暴先锋 x1 |
| 166009 | 暗影主宰 | 162346 / 162347 | 主宰先锋 x1 |
| 166018 | 主宰 | 162348 / 162349 | 小主宰先锋 x1 |
| 1660221 | 风暴龙王 | 162350 / 162351 | 风暴先锋 x1 |

这同时证明 `+0x48` 之后确实是 `ResSoldierTypeInfo` 数组，而不是别的表。

`libGameCore.so` 里只找到 `Databin/data_xls/UGCsoldierwave.bytes`（UGC 自定义
玩法）和 `SoldierWave*` 事件节点；没有普通 5v5 wave 表的文件路径。普通
5v5 的 wave 配置就是上表这张服务端 `dc.db` 表。

### 3.2 1660 系列（代表链，蓝方 route 1）

| waveID | 组成（表内数量） | repeat | start ms | interval ms | next |
|---:|---|---:|---:|---:|---:|
{chr(10).join(chain("5v5_1660", 162320))}

- 红方对应 `162326 → 162327 → 1623271`；route 2/3 为 `162322/162323/1623231`、
  `162324/162325/1623251`（红方 162328/329/3291、162330/331/3311）。
- **分路组成不同**（1660/4010/4012 一致）：route1 前置波 = 1 战士 + 2 经验法师；
  route2 = 2 战士 + 2 法师；route3 = 1 战士 + 2 黄金法师；攻城波 route3 =
  1 战士 + 1 黄金法师 + 1 弩车（炮车波同理）。6000 系列三路相同：
  1 战士 + 2 法师。
- 超兵波：`162340/341/342`（蓝）与 `162343/344/345`（红），
  组成 `机关战士 + 战士 + 法师`。
- 主宰/风暴先锋：`162346–162351`，`repeat=2/3`。
- 同结构系列：`4010`（8+11 次，33s）、`4012`（6+10 次，30s）、
  `10103`（4+6 次，29s）；`6000` 为经典 7 次链（无经验法师前置波）。
- `6000` 系列蓝方 route 1：

| waveID | 组成 | repeat | start ms | interval ms | next |
|---:|---|---:|---:|---:|---:|
{chr(10).join(chain("5v5_6000", 320))}

### 3.3 兵种名与属性（normalMonster）

| normalMonster id | 名称 | bSoldierType | gold | HP | exp3 | actor |
|---:|---|---:|---:|---|---:|---:|
| 1660002 / 1660032 | 蓝/红方战士 | 1 MELEE | 80 | 7000/1860 | 4150 | 10010 |
| 2 / 5 | 蓝/红方法师 | 2 REMOTE | 80 | 5500/1600 | 3000 | 10002 |
| 166001 / 166004 | 蓝/红方法师（1660 波次用） | 2 REMOTE | 90 | 8500/1700 | 4150 | 10012 |
| 166002 / 166005 | 蓝/红方弩车 | 3 SUPER | 192 | 8500/3000 | 4150 | 10020 |
| 1660025 / 1660027 | 蓝/红方炮车 | 3 SUPER | 300 | 8500/3750 | 4150 | 100145 |
| 166014 / 166015 | 蓝/红方机关战士（超级兵） | 3 SUPER | 576 | 7000/4185 | 4150 | 10016 |
| 6000 / 6003 | 蓝/红方战士（6000 波次用） | 1 MELEE | 60 | 7000/1860 | 3850 | 10010 |
| 6001 / 6004 | 蓝/红方法师（6000 波次用） | 2 REMOTE | 90 | 8500/1700 | 3850 | 10012 |
| 6002 / 6005 | 蓝/红方弩车（6000 波次用） | 3 SUPER | 192 | 8500/3000 | 3850 | 10020 |

> `exp3` 是 `normalMonster +0x3C` 字段；文档把它当经验/魂经验使用。  
> `bSoldierType` 在 `+0xCE`，与 metadata `RES_SOLDIER_TYPE` 枚举逐项对上。

## 4. AcntBattleLevel 63 个 cfg1 关卡

- 99 行，`dwDynamicPropertyCfg=1` 的 63 行是普通 5v5 口径；
- 63/63：`wOriginalGoldCoinInBattle=300`、`dwSoulConfigId=4`、
  `iSoldierActivateCountDelay1=0`、`iSoldierActivateCountDelay2=5500`、
  `iSoldierActivateDelay=10000`；
- `dwLevelSwitchID`：6（55）、0（4）、62/63/64/23（各 1）；
- `bBattleMatchSubType`：0（35）、7（16）、11（8）、10（2）、15（2）；
- 行内没有 waveID；`+0x2C8` 的 4022 是 `dwKillEftUseListID`，不是波次。
- 关卡名用字符串位置法解析（`value32 >> 6`），部分行是占位名 `111111`，
  以 `design` 文件名区分。

## 5. 产物与复现

```
python tools/agent_normal5v5_soldiers.py
```

- `agent_normal5v5_soldiers.csv`：`wave_slot`（波次槽位）+
  `evaluate_cond` / `evaluate_cond_only`（3xxx–6xxx 结算条件）三类记录；
- `agent_normal5v5_soldiers_levels.csv`：AcntBattleLevel 99 行，`is_cfg1` 标记 63 行；
- 本报告。

## 6. 限制

- `soldierWave` 表没有关卡/模式引用列，无法把某个系列 100% 绑定到
  主样本关卡；1660/4010 系列与文档 gold=80 行、33s 间隔最吻合，
  4012/10103 为 30s/29s 变体。CSV 的 `series` 列保留全部候选。
- `5v5_early_1_2`（101–104 → 1010/1030）使用 1/4 战士（gold=50）+2/5 法师，
  可能是 1v1/早期 5v5 模板，CSV 保留但 `confidence=medium`；
- `astBranchWaves` 在本表全 0，分支波次无法验证；
- `bBornPosIdx` 全 0，表内数量是“每槽”数量；若游戏按 3 路实例化，
  实际每路总量仍需引擎侧确认。
- 未纳入的波次族：`250–265` 使用 16/17/19/20/22/23（法师 gold=120，
  快速/娱乐族候选）；`350–361/370` 使用 6100/6101/6070 等 normalMonster
  未收录 ID；`620+`/`2621+` 使用 6500 族（法师/经验法师 gold=120，快速赛候选）；
  `5262…` 为 10v10。它们不是普通 5v5 的优先口径。
"""
    path.write_text(rep, encoding="utf-8")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    blob = args.db.read_bytes()
    monster = parse_normal_monster(blob)
    waves = parse_soldier_wave(blob)
    evals = parse_evaluate_cond(blob)
    settles = parse_common_settle(blob)
    levels = parse_acnt_levels(blob)

    series_map = build_series_map(waves)
    wave_rows = build_wave_rows(waves, monster, series_map)
    eval_rows = build_eval_rows(settles, evals)

    args.out.mkdir(parents=True, exist_ok=True)
    csv_path = args.out / "agent_normal5v5_soldiers.csv"
    cols = [
        "record_type", "wave_id", "series", "camp", "route", "wave_role",
        "unit_group", "name", "count", "gold", "exp", "hp",
        "next_wave", "repeat", "start_ms", "interval_ms",
        "source", "confidence", "note",
    ]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(wave_rows + eval_rows)

    levels_path = args.out / "agent_normal5v5_soldiers_levels.csv"
    lcols = [
        "level_id", "name", "design", "is_cfg1", "subtype", "can_pvp", "can_pve",
        "max_acnt", "max_camp", "hero_num", "level_switch", "gold", "soul_cfg",
        "soldier_delay1", "soldier_delay2", "soldier_delay_ms", "dyn_cfg",
        "exp_buff", "gold_buff", "row", "source",
    ]
    with levels_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=lcols)
        w.writeheader()
        for x in levels:
            w.writerow({
                "level_id": x["level_id"], "name": x["name"], "design": x["design"],
                "is_cfg1": int(x["dyn_cfg"] == 1), "subtype": x["subtype"],
                "can_pvp": x["can_pvp"], "can_pve": x["can_pve"],
                "max_acnt": x["max_acnt"], "max_camp": x["max_camp"],
                "hero_num": x["hero_num"], "level_switch": x["level_switch"],
                "gold": x["gold"], "soul_cfg": x["soul_cfg"],
                "soldier_delay1": x["soldier_delay1"],
                "soldier_delay2": x["soldier_delay2"],
                "soldier_delay_ms": x["soldier_delay_ms"],
                "dyn_cfg": x["dyn_cfg"], "exp_buff": x["exp_buff"],
                "gold_buff": x["gold_buff"], "row": x["row"],
                "source": "AcntBattleLevel@0x14660",
            })

    report_path = args.out / "agent_normal5v5_soldiers_report.md"
    write_report(report_path, wave_rows, eval_rows, levels, waves, monster)

    series_counts: dict[str, int] = defaultdict(int)
    for r in wave_rows:
        series_counts[r["series"]] += 1
    print(f"normalMonster rows: {len(monster)}")
    print(f"soldierWave rows: {len(waves)}")
    print(f"wave_slot rows: {len(wave_rows)}  {dict(series_counts)}")
    print(f"evaluate_cond rows: {len(eval_rows)}")
    print(f"AcntBattleLevel rows: {len(levels)} cfg1={sum(1 for x in levels if x['dyn_cfg'] == 1)}")
    print(f"wrote {csv_path}")
    print(f"wrote {levels_path}")
    print(f"wrote {report_path}")


if __name__ == "__main__":
    main()
