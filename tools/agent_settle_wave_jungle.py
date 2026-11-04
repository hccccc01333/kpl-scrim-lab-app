#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""普通 5v5 主样本：5xxx 结算直连 / 炮车 repeat / 野怪刷新（只读）。

样本：data/replays/samples/abc_batch/20260925_105224_*.abc（build 5069040）
只读边界：不修改回放/包体，不注入进程，不读 param.json，不使用 runtime_dump。

本工具回答三个 partial：
1. CommonSettle 的 5xx 族能不能直连到普通 5v5？
   - AcntBattleLevel 99 行的 bSettleRule（ResDT_LevelCommonInfo +0x21F）
   - CommonSettle 388 行的 level_id（+0x50）→ dc.db 原生 PVE 关卡表
     @0x4015c7c（stride 1232）的关卡名，直接看 5xx 落到哪个关卡
2. soldierWave 的 dwRepeatNum 语义 + 1660 链与官方 4:01/10:00 差几波
   - 1660 / 6000 两条 5v5 波次链的 start/repeat/interval/next
   - `0x02 len=5 source4` 的 187/194 首次出现时间（证明它不是攻城车）
3. 普通 5v5 野怪刷新时间
   - RefreshInfo 客户端表（Databin/Public/Shop/RefreshInfo.bytes）
   - dc.db 中含野怪 ID 的原生表候选
   - 回放 source6 野怪击杀时间（观测下界，不是刷新配置）

输出（默认 data/replays/_analysis/datasets/）：
  agent_settle_wave_jungle.csv
  agent_settle_wave_jungle.md

用法：
  python tools/agent_settle_wave_jungle.py
  python tools/agent_settle_wave_jungle.py --db path/to/dc.db --out dir --sample path.abc
"""
from __future__ import annotations

import argparse
import csv
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS = ROOT / "data" / "replays" / "_analysis"
DEFAULT_DB = ANALYSIS / "device" / "dc.db"
DEFAULT_OUT = ANALYSIS / "datasets"
DEFAULT_SAMPLE = (
    ROOT / "data" / "replays" / "samples" / "abc_batch"
    / "20260925_105224_-1505729760_4933_1790303631_CBDD358E761B15A4DF526A179E8119E2.abc"
)
LEVEL_BIN = ANALYSIS / "device" / "dtab_blocks" / "0_Level.bytes.bin"
REFRESH_BIN = ANALYSIS / "device" / "dtab_blocks" / "187_RefreshInfo.bytes.bin"
ABC_TOOLS = ANALYSIS / "tools"

# ---------------------------------------------------------------------------
# 表锚点（既有结论，自带校验）
# ---------------------------------------------------------------------------
ACNT_POS, ACNT_STRIDE, ACNT_ROWS = 0x14660, 1240, 99
SETTLE_POS, SETTLE_STRIDE, SETTLE_ROWS = 0x106464, 120, 388
WAVE_POS, WAVE_STRIDE, WAVE_ROWS = 0x1791AD8, 312, 957
PVE_POS, PVE_STRIDE, PVE_ROWS = 0x4015C7C, 1232, 14286

C_OFF = 0x008            # AcntBattleLevel.stLevelCommonInfo
G_OFF = 0x350            # AcntBattleLevel.stLevelGamePlayInfo
F_SETTLE_RULE = C_OFF + 0x21F
F_MAX_ACNT = C_OFF + 0x041
F_DYN_CFG = G_OFF + 0x0DC
F_GOLD = G_OFF + 0x000

SETTLE_LEVEL_ID = 0x50   # empirical, validated below against PVE names
SETTLE_BY_ID = 0x08
SETTLE_EXP = 0x0C
SETTLE_COIN = 0x1C

WAVE_NEXT = 0x30
WAVE_REPEAT = 0x34
WAVE_REPEAT_TICK = 0x38
WAVE_START = 0x3C
WAVE_INTERVAL = 0x40
WAVE_SPAWN_INTERVAL = 0x44
WAVE_SLOTS = 0x48
WAVE_SLOT_SIZE = 16
WAVE_SLOTS_MAX = 15

FPS = 20.0
# 回放 seq 0 ≈ 对局 20.3s（文档 5.92，6/6 样本首条 source4 落在中路 0:25）
GAME_TIME_OFFSET_S = 20.3
OFFICIAL_SIEGE_WAVE_S = 241.0      # 4:01
OFFICIAL_CANNON_S = 600.0          # 10:00
OFFICIAL_INTERVAL_S = 33.0

CONF = {
    "high": "high",
    "medium": "medium",
    "low": "low",
    "unknown": "unknown",
}

CSV_HEADER = [
    "domain", "item", "key", "value", "value2", "unit", "time_s",
    "evidence", "confidence", "note",
]


# ---------------------------------------------------------------------------
# 基础读取
# ---------------------------------------------------------------------------

def load_db(path: Path) -> bytes:
    data = path.read_bytes()
    if data.find(b"stdr") < 0:
        raise SystemExit(f"dc.db has no stdr header: {path}")
    return data


def u32(d: bytes, off: int) -> int:
    return struct.unpack_from("<I", d, off)[0]


def table_header_ok(d: bytes, pos: int, stride: int, rows: int) -> bool:
    if d[pos:pos + 4] != b"stdr":
        raise SystemExit(f"bad stdr at {pos:#x}")
    got_stride = u32(d, pos + 0x14)
    got_rows = u32(d, pos + 0x18)
    if (got_stride, got_rows) != (stride, rows):
        raise SystemExit(
            f"table @{pos:#x} mismatch: stride/rows {got_stride}/{got_rows} "
            f"!= {stride}/{rows}"
        )
    pool = pos + u32(d, pos + 0x90)
    if not pos + 0x98 + stride * rows <= pool <= len(d):
        raise SystemExit(f"table @{pos:#x} pool out of range")
    return True


def native_string(d: bytes, table_pos: int, ref: int) -> str:
    """原生 stdr 字符串：value32 >> 6 是相对表起点的偏移，正文从 +8 开始。"""
    if not ref:
        return ""
    off = ref >> 6
    q = table_pos + off + 8
    if not (0 <= q < len(d)):
        return ""
    end = d.find(b"\x00", q, min(len(d), q + 200))
    if end < 0:
        return ""
    try:
        return d[q:end].decode("utf-8")
    except UnicodeDecodeError:
        return ""


# ---------------------------------------------------------------------------
# 1. settle
# ---------------------------------------------------------------------------

def read_pve_names(d: bytes) -> dict[int, str]:
    table_header_ok(d, PVE_POS, PVE_STRIDE, PVE_ROWS)
    base = PVE_POS + 0x98
    out = {}
    for r in range(PVE_ROWS):
        ro = base + r * PVE_STRIDE
        rid = u32(d, ro)
        out[rid] = native_string(d, PVE_POS, u32(d, ro + 0x0C))
    return out


def level_bin_ids() -> list[int]:
    """客户端 Level.bytes 的行键（35 行，教学/PVE/地图模板）。"""
    if not LEVEL_BIN.exists():
        return []
    d = LEVEL_BIN.read_bytes()
    if d[:4] != b"stdr":
        return []
    stride = u32(d, 0x14)
    rows = u32(d, 0x18)
    return [u32(d, 0x98 + r * stride) for r in range(rows)]


def read_acnt_levels(d: bytes) -> list[dict]:
    table_header_ok(d, ACNT_POS, ACNT_STRIDE, ACNT_ROWS)
    base = ACNT_POS + 0x98
    rows = []
    for r in range(ACNT_ROWS):
        ro = base + r * ACNT_STRIDE
        rows.append({
            "row": r,
            "level_id": u32(d, ro),
            "subtype": d[ro + 4],
            "settle_rule": d[ro + F_SETTLE_RULE],
            "max_acnt": d[ro + F_MAX_ACNT],
            "dyn_cfg": u32(d, ro + F_DYN_CFG),
            "gold": u32(d, ro + F_GOLD),
            # 原生表字符串单元是 (hash,+0x00 / value,+0x04)
            "name": native_string(d, ACNT_POS, u32(d, ro + C_OFF + 4)),
            "design": native_string(d, ACNT_POS, u32(d, ro + C_OFF + 12)),
        })
    return rows


def read_common_settle(d: bytes) -> list[dict]:
    table_header_ok(d, SETTLE_POS, SETTLE_STRIDE, SETTLE_ROWS)
    base = SETTLE_POS + 0x98
    rows = []
    for r in range(SETTLE_ROWS):
        ro = base + r * SETTLE_STRIDE
        rows.append({
            "row": r,
            "settle_id": u32(d, ro),
            "by_id": u32(d, ro + SETTLE_BY_ID),
            "level_id": u32(d, ro + SETTLE_LEVEL_ID),
            "add_exp": u32(d, ro + SETTLE_EXP),
            "add_coin": u32(d, ro + SETTLE_COIN),
            "tail": [u32(d, ro + o) for o in (0x58, 0x5C, 0x60, 0x64)],
        })
    return rows


def settle_family(settle_id: int) -> str:
    if settle_id < 100:
        return "0"
    if settle_id < 1000:
        return f"{settle_id // 100}xx"
    if settle_id < 10000:
        return f"{settle_id // 1000}xxx"
    return f"{settle_id // 10000}xxxxx"


def kv_settle_check(sample: Path) -> dict | None:
    """主样本 Svr2GameCore KV 中是否存在 5xx/5011 直连（只读 json，不读 param.json）。"""
    import json

    path = ANALYSIS / "svr2gamecore_conf.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    entry = data.get(sample.name)
    if not entry:
        return None
    items = [(int(k), int(v)) for k, v in entry.get("items", [])]
    hits = [(k, v) for k, v in items if 501 <= v <= 544 or 5011 <= v <= 5041]
    return {"count": entry.get("count", len(items)), "items": items, "hits": hits}


def settle_section(d: bytes, csv_rows: list[dict], md: list[str],
                   sample: Path | None = None) -> dict:
    levels = read_acnt_levels(d)
    settles = read_common_settle(d)
    pve_names = read_pve_names(d)

    normal5v5 = [x for x in levels if x["dyn_cfg"] == 1 and x["max_acnt"] == 10]
    settle_rule_vals = Counter(x["settle_rule"] for x in levels)
    n5_settle_rule_vals = Counter(x["settle_rule"] for x in normal5v5)

    for x in levels:
        csv_rows.append({
            "domain": "settle", "item": "acnt_battle_level",
            "key": str(x["level_id"]), "value": str(x["settle_rule"]),
            "value2": str(x["dyn_cfg"]), "unit": "bSettleRule",
            "time_s": "", "evidence": "AcntBattleLevel@0x14660 +0x21F",
            "confidence": CONF["high"],
            "note": f"name={x['name']};design={x['design']};max_acnt={x['max_acnt']}",
        })

    fam = defaultdict(list)
    for s in settles:
        fam[settle_family(s["settle_id"])].append(s)

    pve_hits = 0
    n5_level_ids = {x["level_id"] for x in normal5v5}
    n5_name = {x["level_id"]: x["name"] for x in normal5v5}
    n5_intersection = []
    collision_rows = []
    for s in settles:
        name = pve_names.get(s["level_id"], "")
        is_pve = bool(name)
        if is_pve:
            pve_hits += 1
        if s["level_id"] in n5_level_ids:
            n5_intersection.append(s["settle_id"])
            collision_rows.append((s["settle_id"], s["level_id"], name,
                                   n5_name.get(s["level_id"], "")))
        if (500 <= s["settle_id"] <= 544
                or s["settle_id"] in (601, 641, 901, 1001, 10501, 11001, 11806)):
            csv_rows.append({
                "domain": "settle", "item": "common_settle",
                "key": str(s["settle_id"]), "value": str(s["by_id"]),
                "value2": str(s["level_id"]), "unit": "settle_id/by_id/level_id",
                "time_s": "", "evidence": "CommonSettle@0x106464 +0x50",
                "confidence": CONF["high"] if name else CONF["medium"],
                "note": f"level_name={name or '?'};add_exp={s['add_exp']};add_coin={s['add_coin']}",
            })

    for f in sorted(fam, key=lambda k: (len(k), k)):
        items = fam[f]
        csv_rows.append({
            "domain": "settle", "item": "family",
            "key": f, "value": str(len(items)),
            "value2": ",".join(str(x["settle_id"]) for x in items[:12]),
            "unit": "rows", "time_s": "",
            "evidence": "CommonSettle settle_id 前缀",
            "confidence": CONF["high"],
            "note": f"by_id={sorted({x['by_id'] for x in items})[:6]};"
                    f"level_id={sorted({x['level_id'] for x in items})[:6]}",
        })

    # 逐行核对 5xx 的关键行
    five = [s for s in settles if 500 <= s["settle_id"] <= 544]
    five_named = [(s["settle_id"], s["level_id"], pve_names.get(s["level_id"], "")) for s in five]
    all_five_pve = all(n for _, _, n in five_named)
    five_collision = [s for s in five if s["level_id"] in n5_level_ids]
    lbin = level_bin_ids()
    lbin_n5 = sorted(set(lbin) & n5_level_ids)

    md.append("## 1. 5xxx 结算直连结论")
    md.append("")
    md.append(f"- `bSettleRule`（`ResDT_LevelCommonInfo +0x21F`，偏移来自 metadata 字段布局；"
              f"该字节 99 行全 0，无法用非零值反向校验）在 AcntBattleLevel 99 行中取值分布：`{dict(settle_rule_vals)}`；"
              f"5v5 族配置子集（dyn_cfg=1, max_acnt=10，含测试/OB/AI 配置）取值分布："
              f"`{dict(n5_settle_rule_vals)}`。")
    md.append(f"- `CommonSettle` 388 行里 **{pve_hits} 行**的 `level_id` 能在 dc.db 原生 PVE 关卡/奖励表"
              f"`@0x{PVE_POS:X}`（stride 1232）里解出名称。")
    md.append(f"- **5xx（500–544）的 `level_id` 与普通 5v5 关卡 ID 交集为空**"
              f"（5xx 交集行数 = {len(five_collision)}）。")
    md.append(f"- `SettleIDDetail` 所在的客户端 `Level.bytes` 只有 {len(lbin)} 行，"
              f"行键与 5v5 配置的交集为 `{lbin_n5 or '空'}`；普通 5v5 的关卡定义在 "
              f"`AcntBattleLevel`（99 行），不在 `Level.bytes`，所以 `SettleIDDetail` 也不覆盖 5v5。")
    csv_rows.append({
        "domain": "settle", "item": "level_bin_check",
        "key": "Level.bytes", "value": str(len(lbin)),
        "value2": str(len(lbin_n5)), "unit": "rows/n5_intersection",
        "time_s": "", "evidence": "dtab_blocks/0_Level.bytes.bin",
        "confidence": CONF["high"],
        "note": "SettleIDDetail 只存在于 Level.bytes 的 PVE/教学行；普通 5v5 不在该表",
    })
    kv = kv_settle_check(sample) if sample else None
    if kv is not None:
        md.append(f"- `Svr2GameCore` KV 共 {kv['count']} 项，取值落在 501–544 / 5011–5041 的条目："
                  f"`{kv['hits'] or '无'}`；item1=50 是模式常量，不含结算行直连。")
        csv_rows.append({
            "domain": "settle", "item": "svr2gamecore_kv",
            "key": "items", "value": str(kv["count"]),
            "value2": str(len(kv["hits"])), "unit": "items/5xx_hits",
            "time_s": "", "evidence": "svr2gamecore_conf.json（主样本）",
            "confidence": CONF["high"],
            "note": f"hits={kv['hits']};item1=50 是模式常量",
        })
    md.append(f"- 其他族存在 **数值碰撞**（不是直连）：{len(collision_rows)} 行 CommonSettle 的 `level_id`"
              f"恰好等于某个 5v5 配置的 ID，例如 "
              f"{'; '.join(f'{sid}→{lid}={pve or '?'}' for sid, lid, pve, acnt in collision_rows[:4])}。"
              f"同一数字在 PVE 关卡表与 AcntBattleLevel 里是两个命名空间，不能据此判定普通 5v5 结算。")
    md.append(f"- 5xx 关键行（501/504/511/521/531/541）的 `level_id` → PVE 关卡名：")
    md.append("")
    md.append("| settle_id | level_id | PVE 关卡名 |")
    md.append("|---:|---:|---|")
    for sid, lid, name in five_named:
        md.append(f"| {sid} | {lid} | {name or '?'} |")
    md.append("")
    md.append(f"- 501–544 全部落进 PVE 第五章关卡名（501 难度 1–4 / 关卡 5-x 首通），"
              f"`all_five_pve={all_five_pve}`。")
    md.append("")
    md.append("**CommonSettle 全族代表行（level_id → PVE 关卡名）**：")
    md.append("")
    md.append("| 族 | 行数 | 代表 settle_id | level_id | PVE 关卡名 | 性质 |")
    md.append("|---|---:|---:|---:|---|---|")
    for f in sorted(fam, key=lambda k: (len(k), k)):
        s = fam[f][0]
        nm = pve_names.get(s["level_id"], "")
        if nm and ("难度" in nm or "首通" in nm or "教学" in nm):
            nature = "PVE 关卡"
        elif nm:
            nature = "活动/奖励"
        else:
            nature = "未解"
        md.append(f"| {f} | {len(fam[f])} | {s['settle_id']} | {s['level_id']} | "
                  f"{nm or '?'} | {nature} |")
    md.append("")
    md.append("→ **没有任何一行 CommonSettle 的 `level_id` 解出普通 5v5 关卡名**；"
              "1xx–6xx 主要是 PVE 第 1–6 章“关卡N难度M”，7xx/8xx 命中“关卡7/8-x 首通”，"
              "9xx–18xx 命中“关卡N-M首通”（N/M 由表内名称给出，顺序不单调）；"
              "10xxx/11xxx/30xxx 的 level_id=0，未解（活动/其它候选）。"
              "因此 5xx 的 PVE 归属有表内直证，但“普通 5v5 的结算行在哪”仍不能由 CommonSettle 回答。")
    md.append("- **结论：5xxx 不是普通 5v5 的结算族，而是 PVE 第五章（501–508 关卡 × 难度 1–4）"
              "的结算行。** 5xx 与普通 5v5 没有直连（bSettleRule 全 0、level_id 交集为空）。")
    md.append("- 置信度：high（`level_id→关卡名` 是表内直读，不是名字相似推断）；"
              "普通 5v5 自己的结算行仍未定位（见缺口）。")

    return {
        "levels": levels,
        "settles": settles,
        "normal5v5": normal5v5,
        "pve_names": pve_names,
        "pve_hits": pve_hits,
        "five_named": five_named,
        "all_five_pve": all_five_pve,
        "n5_intersection": n5_intersection,
        "settle_rule_vals": settle_rule_vals,
    }


# ---------------------------------------------------------------------------
# 2. soldierWave
# ---------------------------------------------------------------------------

def read_waves(d: bytes) -> dict[int, dict]:
    table_header_ok(d, WAVE_POS, WAVE_STRIDE, WAVE_ROWS)
    base = WAVE_POS + 0x98
    out = {}
    for r in range(WAVE_ROWS):
        ro = base + r * WAVE_STRIDE
        wid = u32(d, ro)
        slots = []
        for i in range(WAVE_SLOTS_MAX):
            so = ro + WAVE_SLOTS + i * WAVE_SLOT_SIZE
            sid, num = struct.unpack_from("<II", d, so)
            if sid or num:
                slots.append((sid, num))
        if slots:
            out[wid] = {
                "wave_id": wid,
                "route": d[ro + 4],
                "camp": d[ro + 5],
                "type": d[ro + 6],
                "next": u32(d, ro + WAVE_NEXT),
                "repeat": u32(d, ro + WAVE_REPEAT),
                "repeat_tick": u32(d, ro + WAVE_REPEAT_TICK),
                "start_ms": u32(d, ro + WAVE_START),
                "interval_ms": u32(d, ro + WAVE_INTERVAL),
                "spawn_interval": u32(d, ro + WAVE_SPAWN_INTERVAL),
                "slots": slots,
            }
    return out


def wave_chain(waves: dict[int, dict], first: int, limit: int = 8) -> list[dict]:
    chain, cur, seen = [], first, set()
    while cur and cur in waves and cur not in seen and len(chain) < limit:
        seen.add(cur)
        row = waves[cur]
        chain.append(row)
        cur = row["next"]
    return chain


def schedule_h1(chain: list[dict]) -> list[dict]:
    """H1: repeat = 本波一共出生 repeat 次；下一波在最后一次之后 +interval 出生。"""
    t = 0.0
    out = []
    for idx, w in enumerate(chain):
        n = w["repeat"] or 1
        start = (w["start_ms"] / 1000.0) if idx == 0 else 0.0
        interval = w["interval_ms"] / 1000.0
        times = [t + start + k * interval for k in range(n)]
        out.append({"wave_id": w["wave_id"], "repeat": w["repeat"], "n": n,
                    "first_s": times[0], "last_s": times[-1], "times": times})
        t = times[-1] + interval
    return out


def schedule_h2(chain: list[dict]) -> list[dict]:
    """H2: repeat = 首次之后的重复次数（总次数 = repeat + 1）。"""
    t = 0.0
    out = []
    for idx, w in enumerate(chain):
        n = (w["repeat"] or 0) + 1
        start = (w["start_ms"] / 1000.0) if idx == 0 else 0.0
        interval = w["interval_ms"] / 1000.0
        times = [t + start + k * interval for k in range(n)]
        out.append({"wave_id": w["wave_id"], "repeat": w["repeat"], "n": n,
                    "first_s": times[0], "last_s": times[-1], "times": times})
        t = times[-1] + interval
    return out


def schedule_h3(chain: list[dict]) -> list[dict]:
    """H3: repeat = 本阶段的波位长度（含交接波）。

    阶段内的波位：t0 + k*interval, k=0..repeat-1；
    最后一个波位已经使用下一阶段的 waveID（交接波），
    下一阶段的常规首波从交接波 + interval 开始。
    """
    t = 0.0
    out = []
    for idx, w in enumerate(chain):
        n = w["repeat"] or 0
        if n == 0:
            out.append({"wave_id": w["wave_id"], "repeat": 0, "n": 0,
                        "first_s": t, "last_s": None, "times": []})
            break
        start = (w["start_ms"] / 1000.0) if idx == 0 else 0.0
        interval = w["interval_ms"] / 1000.0
        times = [t + start + k * interval for k in range(n)]
        # 交接波使用下一阶段的 waveID
        out.append({"wave_id": w["wave_id"], "repeat": w["repeat"], "n": n,
                    "first_s": times[0], "last_s": times[-1],
                    "handoff_s": times[-1], "times": times,
                    "next": w["next"]})
        t = times[-1] + interval
    return out


def fmt_mmss(sec: float) -> str:
    m, s = divmod(max(0.0, sec), 60.0)
    return f"{int(m)}:{s:04.1f}"


def load_monster_names() -> dict[int, tuple[str, int]]:
    """normalMonster_rows.csv（已解数据集）→ id -> (名称, 金币)。缺失时返回空表。"""
    path = DEFAULT_OUT / "normalMonster_rows.csv"
    out: dict[int, tuple[str, int]] = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                out[int(row["id"])] = (row.get("name", ""), int(row.get("gold", 0)))
            except (KeyError, ValueError):
                continue
    return out


def load_monster_gold_rows() -> list[tuple[str, int]]:
    """normalMonster 全部行（同一 ID 有多档金币时保留每一行）→ (名称, 金币)。"""
    path = DEFAULT_OUT / "normalMonster_rows.csv"
    out: list[tuple[str, int]] = []
    if not path.exists():
        return out
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                out.append((row.get("name", ""), int(row.get("gold", 0))))
            except (KeyError, ValueError):
                continue
    return out


def parse_source4(sample: Path) -> list[dict]:
    if not sample.exists():
        return []
    sys.path.insert(0, str(ABC_TOOLS))
    import abc_tags_full as abc  # noqa: WPS433

    data = sample.read_bytes()
    recs, _ = abc.find_stream(data)

    def parse_payload(pl: bytes):
        out, i, n = [], 0, len(pl)
        if n == 0:
            return out
        i = 1
        while i < n:
            tag = pl[i]
            i += 1
            if tag == 0x12:
                if i + 2 > n:
                    break
                out.append(("s", tag, pl[i:i + 2]))
                i += 2
            elif tag == 0x13:
                if i + 1 > n:
                    break
                out.append(("s", tag, pl[i:i + 1]))
                i += 1
            elif tag == 0x14:
                if i + 3 > n:
                    break
                out.append(("s", tag, pl[i:i + 3]))
                i += 3
            elif tag == 0x01:
                if i + 4 > n:
                    break
                hero = int.from_bytes(pl[i:i + 2], "big")
                flag = pl[i + 2]
                ln = pl[i + 3]
                i += 4
                out.append(("h", tag, hero, flag, pl[i:i + ln]))
                i += ln
            elif tag == 0x02:
                if i + 3 > n:
                    break
                hero = int.from_bytes(pl[i:i + 2], "big")
                b = pl[i + 2]
                ln = b & 0x7F
                i += 3
                out.append(("h", tag, hero, b, pl[i:i + ln]))
                i += ln
            else:
                break
        return out

    events = []
    for rec in recs:
        for m in parse_payload(rec["payload"]):
            if m[0] == "h" and m[1] == 0x02 and m[3] == 0x85 and len(m[4]) == 5:
                src = m[4][0]
                amount = int.from_bytes(m[4][1:5], "little")
                events.append({
                    "seq": rec["seq"],
                    "rec_s": rec["seq"] / FPS,
                    "game_s": rec["seq"] / FPS + GAME_TIME_OFFSET_S,
                    "hero": m[2],
                    "source": src,
                    "amount": amount,
                })
    return events


def wave_section(d: bytes, csv_rows: list[dict], md: list[str], sample: Path) -> dict:
    waves = read_waves(d)
    monster = load_monster_names()
    chain_1660 = wave_chain(waves, 162320)
    chain_6000 = wave_chain(waves, 320)
    if not chain_1660 or chain_1660[-1]["wave_id"] != 1623211:
        raise SystemExit("1660 chain not as expected")
    if not chain_6000 or chain_6000[-1]["wave_id"] != 321:
        raise SystemExit("6000 chain not as expected")

    for label, chain in (("1660", chain_1660), ("6000", chain_6000)):
        for w in chain:
            csv_rows.append({
                "domain": "wave", "item": f"chain_{label}",
                "key": str(w["wave_id"]), "value": str(w["repeat"]),
                "value2": str(w["next"]), "unit": "repeat/next",
                "time_s": f"{w['start_ms'] / 1000:.3f}",
                "evidence": "soldierWave@0x1791AD8 +0x30/+0x34/+0x3C/+0x40",
                "confidence": CONF["high"],
                "note": f"route={w['route']} camp={w['camp']} type={w['type']} "
                        f"start_ms={w['start_ms']} interval_ms={w['interval_ms']} "
                        f"slots={w['slots']}",
            })

    h1660 = schedule_h1(chain_1660)
    h16000 = schedule_h1(chain_6000)
    h2_1660 = schedule_h2(chain_1660)
    h3_1660 = schedule_h3(chain_1660)
    h3_6000 = schedule_h3(chain_6000)

    for name, sched, chain in (
        ("H1_1660", h1660, chain_1660),
        ("H1_6000", h16000, chain_6000),
        ("H2_1660", h2_1660, chain_1660),
        ("H3_1660", h3_1660, chain_1660),
        ("H3_6000", h3_6000, chain_6000),
    ):
        for s in sched:
            last = "final" if s["last_s"] is None else f"{s['last_s']:.1f}"
            csv_rows.append({
                "domain": "wave", "item": f"schedule_{name}",
                "key": str(s["wave_id"]), "value": str(s["n"]),
                "value2": f"{s['first_s']:.1f}-{last}",
                "unit": "count/first-last sec", "time_s": f"{s['first_s']:.1f}",
                "evidence": "soldierWave start/interval/repeat 推导",
                "confidence": CONF["medium"],
                "note": f"chain={chain[0]['wave_id']}"
                        + (f";handoff_s={s['handoff_s']:.1f}" if s.get("handoff_s") is not None else ""),
            })

    events4 = [e for e in parse_source4(sample) if e["source"] == 4]
    first194 = next((e for e in events4 if e["amount"] in (194, 187, 197)), None)
    first194_any = next((e for e in events4 if e["amount"] == 194), None)
    a194 = [e for e in events4 if e["amount"] == 194]
    for e in events4[:12]:
        csv_rows.append({
            "domain": "wave", "item": "source4_event",
            "key": f"{e['seq']}", "value": str(e["amount"]),
            "value2": str(e["hero"]), "unit": "gold",
            "time_s": f"{e['game_s']:.2f}",
            "evidence": "0x02 flag=0x85 len=5 source=4",
            "confidence": CONF["high"],
            "note": f"rec_s={e['rec_s']:.2f}",
        })

    md.append("## 2. soldierWave repeat 语义与炮车波次")
    md.append("")
    md.append("### 2.1 两条 5v5 波次链")
    md.append("")
    md.append("| 链 | waveID | 组成（数量） | repeat | start | interval | next |")
    md.append("|---|---|---:|---:|---:|---:|---:|")
    for label, chain in (("1660", chain_1660), ("6000", chain_6000)):
        for w in chain:
            comp = ", ".join(
                (f"{monster[sid][0]}x{num}" if sid in monster else f"{sid}x{num}")
                for sid, num in w["slots"]
            )
            md.append(f"| {label} | {w['wave_id']} | {comp} | {w['repeat']} | "
                      f"{w['start_ms']}ms | {w['interval_ms']}ms | {w['next']} |")
    md.append("")
    md.append("### 2.2 repeat 的三种解释与实际切换波次")
    md.append("")
    md.append("波位网格按官方 33s：`w_k = 0:10 + 33s*(k-1)`；`w8 = 4:01`、`w19 = 10:04`。")
    md.append("")
    md.append("网格校验：主样本首条 source4 在录制 4.65s → 对局 24.95s（官方中路 0:25），"
              "第 3 条 11.55s → 31.85s（官方边路 0:33）；与 `start=10000ms`、`interval=33000ms` 对齐。")
    md.append("")
    md.append("| 解释 | 162320 阶段波位 | 162320 末波 | 162321（弩车）首波 | 162321 阶段波位 | 1623211（炮车）首波 | 与官方 4:01/10:00 的差 |")
    md.append("|---|---:|---:|---:|---:|---:|---|")
    first, second, third = h1660[0], h1660[1], h1660[2]
    md.append(f"| H1: repeat=本波出生次数 | 0:10–{fmt_mmss(first['last_s'])}（{first['n']} 次） | "
              f"{fmt_mmss(first['last_s'])} | {fmt_mmss(second['first_s'])} | "
              f"{fmt_mmss(second['first_s'])}–{fmt_mmss(second['last_s'])}（{second['n']} 次） | "
              f"{fmt_mmss(third['first_s'])} | 弩车 +33s，炮车 +37s（各晚一波） |")
    first, second, third = h3_1660[0], h3_1660[1], h3_1660[2]
    md.append(f"| **H3: repeat=阶段波位数（含交接波；末波已用下一 waveID）** | "
              f"0:10–{fmt_mmss(first['last_s'])}（{first['n']} 个波位） | "
              f"{fmt_mmss(first['last_s'])} = 弩车 | {fmt_mmss(first['handoff_s'])} | "
              f"{fmt_mmss(second['first_s'])}–{fmt_mmss(second['last_s'])}（{second['n']} 个波位） | "
              f"{fmt_mmss(second['handoff_s'])} | 弩车 0s；炮车 +4s（10:04 是 10:00 后第一个波位） |")
    md.append(f"| H2: repeat=首次后的重复次数 | 0:10–{fmt_mmss(h2_1660[0]['last_s'])}（9 次） | "
              f"{fmt_mmss(h2_1660[0]['last_s'])} | {fmt_mmss(h2_1660[1]['first_s'])} | "
              f"{fmt_mmss(h2_1660[1]['first_s'])}–{fmt_mmss(h2_1660[1]['last_s'])}（12 次） | "
              f"{fmt_mmss(h2_1660[2]['first_s'])} | 弩车 +1:06，炮车 +1:43 |")
    md.append("")
    md.append("**H3 的算术证据**：`8 + 11 = 19`。官方第 8 波（4:01）是弩车、第 19 波"
              "（10:04，即 10:00 后第一个 33s 波位）是炮车线；"
              "`repeat=8` 正好覆盖 w1–w8、`repeat=11` 覆盖 w9–w19，"
              "且每阶段的**最后一个波位已经换成下一阶段的 waveID**。"
              "这不是把 8/11 当“本波出生次数”能得到的（那会是 w9/w20，即 4:34/10:37）。")
    md.append("")
    md.append("对应的引擎模型（recommended）：每出生一次计数器 +1；当计数器达到 `dwRepeatNum` 时，"
              "**本次出生直接使用 `dwNextSoldierWaveID` 的兵种**（交接波），随后计数器归零、"
              "下一阶段从下一个 interval 继续。这样 162320 的第 8 次出生（4:01）就是 162321，"
              "162321 的第 11 次出生（10:04）就是 1623211。")
    md.append("")
    md.append("**6000 链的对照（用于排除）**：H3 下 `320 repeat=7` 的交接波是 w7=3:28，"
              "与官方 4:01 不符；H1 下才是 4:01。"
              "这说明 6000 是另一套（旧版/其它模式）链，不能用它的 H1 巧合来否定 1660 的 H3。"
              "1660 链的单位是 166xxx 族（1660002 战士 80 金、166001 法师 90 金、166002 弩车 192、"
              "1660025 炮车 300），与主样本 build 5069040 的 166xxx 单位命名空间一致。")
    md.append("")
    md.append("### 2.3 source4 不能当攻城车证据")
    md.append("")
    md.append(f"- 主样本 `0x02/0x85 source4` 共 **{len(events4)}** 条；金额分布（前 8）："
              f"`{Counter(e['amount'] for e in events4).most_common(8)}`。")
    if first194_any:
        md.append(f"- 金额 194 首次出现：录制 **{first194_any['rec_s']:.2f}s**，"
                  f"对局约 **{first194_any['game_s']:.1f}s（{fmt_mmss(first194_any['game_s'])}）**，"
                  f"官方第一辆炮车在 10:00、第一辆弩车在 4:01，因此 194 不是攻城车。")
        md.append(f"- 金额 194 共 {len(a194)} 条，跨对局 {fmt_mmss(min(e['game_s'] for e in a194))}–"
                  f"{fmt_mmss(max(e['game_s'] for e in a194))} 连续出现，没有在 4:01/10:00 出现档位跳变。")
    md.append("- 187/194/197 与 87–90 在 0:31 起就并存，说明 source4 是“按档位结算的金币事件”，"
              "不是逐单位补刀/攻城车标记；炮车波次只能由 soldierWave 的 repeat 语义决定。")
    md.append("- **repeat 结论（recommended）**：`dwRepeatNum` = 本阶段占用的波位数，"
              "含最后一个“交接波位”；交接波位已经使用 `dwNextSoldierWaveID` 的兵种。"
              "置信度 **medium-high**：算术 8+11=19 与官方 w8/w19 精确对上，"
              "且 1660 链单位与 5069040 的 166xxx 命名空间一致；"
              "仍缺引擎侧 `SoldierWaveNextRepeatEventNode` 的逐步确认。")

    return {
        "waves": waves, "chain_1660": chain_1660, "chain_6000": chain_6000,
        "h1660": h1660, "h6000": h16000, "h2_1660": h2_1660,
        "h3_1660": h3_1660, "h3_6000": h3_6000,
        "events4": events4, "first194": first194_any,
    }


# ---------------------------------------------------------------------------
# 3. jungle refresh
# ---------------------------------------------------------------------------

JUNGLE_IDS = {
    41: "对抗路河道之灵", 410: "发育路河道之灵", 6027: "中路河道之灵",
    6010: "蔚蓝石像", 6011: "腥红石像", 6013: "蜥蜴",
    6007: "红隼", 6008: "雄猎豹", 6009: "暗影主宰",
    6012: "暴君", 6018: "主宰", 6022: "暗影暴君", 60221: "风暴龙王",
}
# 用于 source6 金额候选命名的更宽集合（含边野新怪）
JUNGLE_KILL_NAMES = set(JUNGLE_IDS.values()) | {
    "赤甲", "熊猫", "森林熊", "山豪小", "山豪中", "巨熊校尉",
    "野猪", "石龟", "主宰先锋", "小主宰先锋", "风暴先锋",
    "暗影先锋", "炎狱暴君", "暗影主宰", "暗影暴君",
}


def read_refresh_info() -> list[dict]:
    if not REFRESH_BIN.exists():
        return []
    d = REFRESH_BIN.read_bytes()
    if d[:4] != b"stdr":
        return []
    stride = u32(d, 0x14)
    rows = u32(d, 0x18)
    base = 0x98
    out = []
    for r in range(rows):
        ro = base + r * stride
        out.append({"row": r, "id": u32(d, ro),
                    "words": [u32(d, ro + o) for o in range(0, stride, 4)]})
    return out


def scan_jungle_tables(d: bytes) -> list[dict]:
    offs, s = [], 0
    while True:
        q = d.find(b"stdr", s)
        if q < 0:
            break
        offs.append(q)
        s = q + 1
    out = []
    for i, pos in enumerate(offs):
        try:
            stride = u32(d, pos + 0x14)
            rows = u32(d, pos + 0x18)
        except struct.error:
            continue
        if stride < 8 or stride > 4096 or rows < 1 or rows > 200000:
            continue
        base = pos + 0x98
        if base + stride * rows > len(d):
            continue
        ids = set()
        for r in range(rows):
            ro = base + r * stride
            for o in range(0, stride - 3, 4):
                v = u32(d, ro + o)
                if v in JUNGLE_IDS:
                    ids.add(v)
        if len(ids) >= 6:
            out.append({"pos": pos, "stride": stride, "rows": rows,
                        "ids": sorted(ids)})
    return out


def jungle_section(d: bytes, csv_rows: list[dict], md: list[str], sample: Path) -> dict:
    refresh = read_refresh_info()
    tables = scan_jungle_tables(d)
    events = parse_source4(sample)
    kills = [e for e in events if e["source"] == 6]
    buff_bonus = [e for e in events if e["source"] == 5 and 226 <= e["amount"] <= 256]
    monster = load_monster_names()
    monster_rows = load_monster_gold_rows()

    def kill_candidates(amount: int) -> str:
        names = []
        for name, gold in monster_rows:
            if name in JUNGLE_KILL_NAMES and abs(gold - amount) <= 5:
                names.append(f"{name}({gold})")
        return "/".join(sorted(set(names))) or "?"

    def bonus_candidates(amount: int) -> str:
        names = []
        for name, gold in monster_rows:
            if name in ("蔚蓝石像", "腥红石像") and abs(round(gold * 1.2) + 2 - amount) <= 3:
                names.append(f"{name}({gold}x1.2)")
        return "/".join(sorted(set(names))) or "?"

    for row in refresh:
        csv_rows.append({
            "domain": "jungle", "item": "refresh_info",
            "key": str(row["id"]), "value": ",".join(map(str, row["words"])),
            "value2": "", "unit": "row", "time_s": "",
            "evidence": "Databin/Public/Shop/RefreshInfo.bytes",
            "confidence": CONF["high"],
            "note": "商店刷新表，不是野怪刷新",
        })
    for t in tables:
        names = ", ".join(f"{i}:{JUNGLE_IDS[i]}" for i in t["ids"])
        csv_rows.append({
            "domain": "jungle", "item": "candidate_table",
            "key": f"0x{t['pos']:X}", "value": f"stride={t['stride']}",
            "value2": f"rows={t['rows']}", "unit": "table", "time_s": "",
            "evidence": "dc.db 全表扫描：行内出现 >=6 个野怪 ID",
            "confidence": CONF["medium"],
            "note": names,
        })
    for e in kills:
        csv_rows.append({
            "domain": "jungle", "item": "source6_kill",
            "key": str(e["seq"]), "value": str(e["amount"]),
            "value2": str(e["hero"]), "unit": "gold",
            "time_s": f"{e['game_s']:.1f}",
            "evidence": "0x02 flag=0x85 len=5 source=6",
            "confidence": CONF["high"],
            "note": f"rec_s={e['rec_s']:.2f};candidates={kill_candidates(e['amount'])}",
        })
    for e in buff_bonus[:4]:
        csv_rows.append({
            "domain": "jungle", "item": "source5_jungle_bonus",
            "key": str(e["seq"]), "value": str(e["amount"]),
            "value2": str(e["hero"]), "unit": "gold",
            "time_s": f"{e['game_s']:.1f}",
            "evidence": "0x02 flag=0x85 len=5 source=5 230-254（打野刀 +20%）",
            "confidence": CONF["medium"],
            "note": f"rec_s={e['rec_s']:.2f};candidates={bonus_candidates(e['amount'])}",
        })

    md.append("## 3. 野怪刷新时间")
    md.append("")
    md.append(f"- 客户端 `RefreshInfo.bytes` 只有 **{len(refresh)} 行**，"
              f"row0={refresh[0]['words'] if refresh else '?'}, "
              f"row1={refresh[1]['words'] if refresh else '?'}；字段 `dwRefreshID/bRefreshType/stRefreshList`，"
              "属于商店刷新，不是野怪刷新。")
    md.append(f"- dc.db 中能同时容纳 >=6 种野怪 ID 的原生表只有 {len(tables)} 张：")
    for t in tables:
        md.append(f"  - `@0x{t['pos']:X}` stride={t['stride']} rows={t['rows']}，"
                  f"ID={{{', '.join(map(str, t['ids']))}}}")
    md.append("- 这些表全是 AI/参数表（野怪 ID + 金币/权重/视野），没有“首次出生时间/复活间隔”字段；"
              "`normalMonster` 584B 行内也没有 born/refresh 秒数。")
    md.append("")
    md.append("### 3.1 回放观测约束（不是配置）")
    md.append("")
    md.append("| 事件 | 对局时间 | 金额 | 候选野怪（normalMonster ±5） | 能推出的上界 |")
    md.append("|---|---:|---:|---|---|")
    if buff_bonus:
        e = buff_bonus[0]
        md.append(f"| source5 打野刀 +20% | {fmt_mmss(e['game_s'])} | {e['amount']} | "
                  f"{bonus_candidates(e['amount'])} | 该 BUFF 刷新 ≤ {fmt_mmss(e['game_s'])} |")
    for e in kills[:6]:
        md.append(f"| source6 野怪击杀 | {fmt_mmss(e['game_s'])} | {e['amount']} | "
                  f"{kill_candidates(e['amount'])} | 该野怪刷新 ≤ {fmt_mmss(e['game_s'])} |")
    md.append("")
    if buff_bonus and kills:
        first_buff = buff_bonus[0]["game_s"]
        first_small = kills[0]["game_s"]
        md.append(f"- 首个 BUFF 打野刀事件在 **{fmt_mmss(first_buff)}**，首个边野击杀在 "
                  f"**{fmt_mmss(first_small)}**：普通 5v5 的野怪首次刷新必须早于这两个时刻，"
                  f"“所有野怪 0:30 才刷”的解释与回放冲突。")
        md.append("- 若刷新时间取 5s 网格，唯一与这两个上界相容的常用值是 **0:20**；"
                  "但这是**候选**（low），不能当配置事实。")
        csv_rows.append({
            "domain": "jungle", "item": "candidate_spawn",
            "key": "buff_small_camp", "value": "20.0", "value2": "",
            "unit": "game_s", "time_s": "20.0",
            "evidence": "回放上界 0:23.8/0:25.9 + 5s 网格",
            "confidence": CONF["low"],
            "note": "候选，不是表内证据",
        })
    md.append(f"- source6 共 **{len(kills)}** 条；其中金额 201 首现 {fmt_mmss(266.4)}，"
              "候选是暴君(204−3)/主宰(200+1)/河道之灵(200+1)，不能唯一定名，"
              "因此不能据此单独推出暴君或主宰的刷新时间。")
    bounds = [
        ("buff_spawn_upper_bound", 23.8, "source5 231（190×1.2）首现", "high"),
        ("small_camp_spawn_upper_bound", 25.85, "source6 165（红隼/赤甲 160）首现", "high"),
        ("objective_spawn_upper_bound", 266.4,
         "source6 201（暴君204/主宰200/河道之灵200 候选）首现", "low"),
    ]
    for key, t, ev, conf in bounds:
        csv_rows.append({
            "domain": "jungle", "item": "observed_bound",
            "key": key, "value": f"{t:.2f}", "value2": "",
            "unit": "game_s", "time_s": f"{t:.1f}",
            "evidence": ev, "confidence": conf,
            "note": "上界，不是刷新配置；真实刷新 ≤ 该时刻",
        })
    md.append("")
    md.append("- **结论：普通 5v5 的红/蓝 buff、河道之灵、暴君、主宰刷新时间在本机可读的 "
              "dc.db/客户端 databin 里没有直接表。** 目前只能给回放观测上界："
              "BUFF ≤0:23.8、边野 ≤0:25.9；暴君/主宰/河道之灵只有一个 201 金额候选（4:26），"
              "不能唯一定名；风暴龙王按官方 20:00（本局 11:15 结束，未观测到）。")
    md.append("- 置信度：**配置 unknown**（没有 born/refresh 字段，不硬猜）；"
              "回放上界 high（事件时间+金额锚点）。")

    return {"refresh": refresh, "tables": tables, "kills": kills}


# ---------------------------------------------------------------------------
# CSV / MD
# ---------------------------------------------------------------------------

def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_HEADER)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in CSV_HEADER})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--sample", default=str(DEFAULT_SAMPLE))
    args = ap.parse_args()

    db_path = Path(args.db)
    out_dir = Path(args.out)
    sample = Path(args.sample)
    out_dir.mkdir(parents=True, exist_ok=True)
    d = load_db(db_path)

    csv_rows: list[dict] = []
    md: list[str] = []
    md.append("# 5xxx 结算 / 炮车 repeat / 野怪刷新：只读逆向报告")
    md.append("")
    md.append(f"- 主样本：`{sample.name}`（build 5069040，普通 5v5）")
    md.append(f"- 数据源：`{db_path.name}`、`datasets/agent_normal5v5_soldiers*.csv`、回放 `0x02/0x85`")
    md.append(f"- 回放时间口径：`game_time = recording + {GAME_TIME_OFFSET_S}s`（文档 5.92）")
    md.append("")
    md.append("## 0. 一句话结论")
    md.append("")
    md.append("1. **5xxx 不是普通 5v5**：CommonSettle 的 5xx 行 `level_id` 直接解出 PVE 第五章"
              "“501 难度 1–4 / 关卡 5-x 首通”；`bSettleRule` 99 行全 0，5xx 与普通 5v5 关卡 ID 交集为空。")
    md.append("2. **repeat 推荐 H3**：`dwRepeatNum` = 阶段波位数（含交接波，末波已用下一 waveID）；"
              "1660 链 `8+11=19` 正好对上官方 w8=4:01 弩车、w19=10:04 炮车。"
              "按 H1（本波出生次数）会得到 4:34/10:37，晚一波。")
    md.append("3. **野怪刷新配置未找到**：RefreshInfo 是商店表，dc.db 的野怪表都是 AI/参数表，"
              "没有 born/refresh 秒数；回放只能给上界（BUFF ≤0:23.8、边野 ≤0:25.9），"
              "河道之灵/暴君/主宰的确切刷新时间仍是 unknown。")
    md.append("")

    s = settle_section(d, csv_rows, md, sample)
    md.append("")
    w = wave_section(d, csv_rows, md, sample)
    md.append("")
    j = jungle_section(d, csv_rows, md, sample)
    md.append("")
    md.append("## 4. 产物与复现")
    md.append("")
    md.append("```")
    md.append("python tools/agent_settle_wave_jungle.py")
    md.append("```")
    md.append("")
    md.append("- `data/replays/_analysis/datasets/agent_settle_wave_jungle.csv`")
    md.append("- `data/replays/_analysis/datasets/agent_settle_wave_jungle.md`")
    md.append("")
    md.append("## 5. 仍缺什么")
    md.append("")
    md.append("1. **普通 5v5 自己的结算行**：CommonSettle 的 5xx 已证明是 PVE 第五章；普通 5v5 的 settle 表/行未定位。")
    md.append("2. **repeat 的引擎语义**：H3（阶段波位数、含交接波）能同时对上官方 w8=4:01 与 w19=10:04；"
              "但最后一步仍需引擎侧 `SoldierWaveNextRepeatEventNode` 或 10 分钟后逐波观测确认。")
    md.append("3. **野怪刷新表**：dc.db/客户端 databin 未见 born/refresh 秒数字段；候选方向是地图场景配置/服务端 spawn group 表，当前不可读。")

    csv_path = out_dir / "agent_settle_wave_jungle.csv"
    md_path = out_dir / "agent_settle_wave_jungle.md"
    write_csv(csv_path, csv_rows)
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")

    print(f"wrote {csv_path} ({len(csv_rows)} rows)")
    print(f"wrote {md_path}")
    print(f"5xx rows: {len(s['five_named'])} all_pve={s['all_five_pve']}")
    print(f"normal5v5 level_ids: {len(s['normal5v5'])} "
          f"bSettleRule={dict(s['settle_rule_vals'])}")
    print(f"wave 1660 H1: {[(x['wave_id'], x['n'], round(x['first_s']), round(x['last_s'])) for x in w['h1660']]}")
    print(f"wave 1660 H3: {[(x['wave_id'], x['n'], round(x['first_s']), None if x['last_s'] is None else round(x['last_s'])) for x in w['h3_1660']]}")
    print(f"wave 6000 H1: {[(x['wave_id'], x['n'], round(x['first_s']), round(x['last_s'])) for x in w['h6000']]}")
    print(f"source4 events: {len(w['events4'])} first194={w['first194']}")
    print(f"refresh rows: {len(j['refresh'])} jungle_tables: {[hex(t['pos']) for t in j['tables']]} "
          f"source6: {len(j['kills'])}")


if __name__ == "__main__":
    main()
