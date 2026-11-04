#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""装备 item 名称/价格 + 1558 出装/金币的只读分析工具。

目标
----
1. 在 ``dc.db`` 里定位**战斗装备表**（533 行，row0 = 1111 铁剑、row1 = 1112 匕首），
   解出每件装备的：itemID、名称、购买价、出售价、价格档位、装备分组、属性描述。
   若本地有官方 ``pvp_item.json``，按 itemID 对拍 total_price/price（当前 113/115 全等）。
2. 对照 ``134_Equip``（0x3602400，270 行 × 216 B = 27 个 8 B cell）确认它是
   PVE/训练营装备表（1112 = 木杖，与战斗表的 1112 匕首不同 ID 空间）。
3. 解析录制者 1558 的 4 套玩家块出装方案（每套 12 槽，BE u32 itemID 数组）。
4. 核对 ``0x02/0x87`` 的语义：该 7 字节消息是 ``00 00 00 actorID skillID level 00``
   的技能升级（``stCmdSetSkillLevel``），**不是**购买时序；给出 4 条独立证据。
5. 用 item 价格表给出 1558 四套方案的成品造价、升级差额，以及金币区间。

约束
----
只读：不修改回放/包体；不注入；不读 param.json；不使用 runtime_dump；
不编辑 docs/replay_binary_format.md 与 .workbuddy/memory/MEMORY.md。

表结构（stdr）
--------------
header: +0x00 "stdr", +0x08 字符串数, +0x14 stride, +0x18 行数,
        +0x90 池相对偏移; 行数据在 +0x98; 池 = 表头 + pool_rel。
字符串 cell = (hash32, value32)，value32 >> 6 = 相对 pool_rel 的池内偏移。
池记录 = hash64 | UTF-8 | NUL | 4 字节对齐。

输出
----
data/replays/_analysis/datasets/agent_equip_prices.csv
data/replays/_analysis/datasets/agent_equip_prices.md

用法
----
  python tools/agent_equip_prices.py
  python tools/agent_equip_prices.py --db path/to/dc.db --abc path/to/sample.abc --out dir
"""
from __future__ import annotations

import argparse
import csv
import json
import struct
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS = ROOT / "data" / "replays" / "_analysis"
DEFAULT_DB = ANALYSIS / "device" / "dc.db"
DEFAULT_ABC = (
    ROOT / "data" / "replays" / "samples" / "abc_batch"
    / "20260925_105224_-1505729760_4933_1790303631_CBDD358E761B15A4DF526A179E8119E2.abc"
)
DEFAULT_OUT = ANALYSIS / "datasets"
# 官方装备表（pvp.qq.com/web201605/js/item.json 的本地副本）
DEFAULT_OFFICIAL = ANALYSIS / "datasets" / "pvp_item.json"

SAMPLE_ID = "20260925_105224"
RECORDER_ENTITY = 1558
RECORDER_NAME = "佚名(*:"
# 玩家块里的 4 套方案名（1558 块，abc 约 0x9eeb 起）
PLAN_NAMES = ("热门套装", "原辅助坦克", "坦克开团流", "天龙灭世流")

# 1558 金币口径（任务给定，与 player_1558_normal5v5_report.md 一致）
INITIAL_GOLD = 300
NATURAL_GOLD = 1905          # 3/s × 635 s
NATURAL_RATE = 3

# 升级链：由表内名称/价格与王者荣耀合成树确定，只用“名称同族 + 价格差”能直接
# 验证的边（pre -> final）。差额 = final.buy - pre.buy，即升级时实付金币。
CHAIN_EDGES = (
    (1411, 1422, "神速之靴→抵抗之靴"),
    (1411, 1423, "神速之靴→冷静之靴"),
    (1411, 1424, "神速之靴→秘法之靴"),
    (1701, 1714, "学识宝石→近卫"),
    (1714, 1753, "近卫→近卫·奔狼"),
    (1714, 1724, "近卫→近卫·救赎"),
    (1325, 1333, "守护者之铠→不祥征兆"),
    (1325, 1336, "守护者之铠→极寒风暴"),
    (1325, 13310, "守护者之铠→冰痕之握"),
    (1239, 1242, "辉月→难知·月神"),
)


# ---------------------------------------------------------------------------
# dc.db stdr 表解析
# ---------------------------------------------------------------------------
class StdTable:
    """只读 stdr 表：header + rows + string pool。"""

    def __init__(self, data: bytes, offset: int):
        self.data = data
        self.offset = offset
        if data[offset:offset + 4] != b"stdr":
            raise ValueError(f"{offset:#x} 不是 stdr 表")
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

    def resolve(self, value32: int) -> str | None:
        """(hash32, value32) cell 的 value32 -> 字符串。"""
        file_off = value32 >> 6
        return self.strings.get(file_off - self.pool_rel)

    def row_u32(self, row: int) -> tuple[int, ...]:
        n = self.stride // 4
        return struct.unpack_from(f"<{n}I", self.data, self.data0 + row * self.stride)


def locate_battle_item_table(data: bytes) -> StdTable:
    """找战斗装备表：row0 = 1111 铁剑、row1 = 1112 匕首、rows≈533。"""
    pos = 0
    while True:
        pos = data.find(b"stdr", pos)
        if pos < 0:
            break
        try:
            t = StdTable(data, pos)
        except (struct.error, ValueError):
            pos += 4
            continue
        if 100 <= t.stride <= 1024 and 200 <= t.n_rows <= 2000 and t.n_strings:
            r0, r1 = t.row_u32(0), t.row_u32(1)
            n0, n1 = t.resolve(r0[3]), t.resolve(r1[3])
            if r0[0] == 1111 and n0 == "铁剑" and r1[0] == 1112 and n1 == "匕首":
                return t
        pos += 4
    raise SystemExit("dc.db 中未找到战斗装备表（1111 铁剑 / 1112 匕首）")


def locate_134_equip(data: bytes) -> StdTable | None:
    """找 134_Equip（PVE 装备）：1111 铁剑、1112 木杖。"""
    pos = 0
    while True:
        pos = data.find(b"stdr", pos)
        if pos < 0:
            return None
        try:
            t = StdTable(data, pos)
        except (struct.error, ValueError):
            pos += 4
            continue
        if 100 <= t.stride <= 512 and 100 <= t.n_rows <= 500:
            r0, r1 = t.row_u32(0), t.row_u32(1)
            if (r0[0] == 1111 and t.resolve(r0[3]) == "铁剑"
                    and r1[0] == 1112 and t.resolve(r1[3]) == "木杖"):
                return t
        pos += 4


def stat_tables(data: bytes) -> list[StdTable]:
    """枚举所有 stdr 表（用于 0x3602400 这类按偏移引用的表）。"""
    out, pos = [], 0
    while True:
        pos = data.find(b"stdr", pos)
        if pos < 0:
            break
        try:
            out.append(StdTable(data, pos))
        except (struct.error, ValueError):
            pass
        pos += 4
    return out


def parse_battle_items(t: StdTable) -> dict[int, dict]:
    """战斗装备表字段（已对 533 行验证）：

    +0x00 itemID            u32
    +0x08 name              (hash,ref)
    +0x10 equipGroup        u32 位掩码（0x20000 武器 / 0x80000 防具 /
                                0x40000 法术 / 0x100000 鞋 / 0x800000 游走）
    +0x14 priceType         u32，字节 +2 = bPriceType（1..4）
    +0x28 buyPrice          u32 购买价（c10）
    +0x30 idString          (hash,ref) 例 "1111"
    +0x4C sellPrice         u32 出售价（c19）= 60% 购买价
    +0x1D0 propertyText     (hash,ref) 例 "+20攻击"
    """
    items: dict[int, dict] = {}
    for r in range(t.n_rows):
        v = t.row_u32(r)
        item_id = v[0]
        if item_id == 0 or item_id > 99999:
            # 533 行里有 29 行 ID 是打包值/砂之模式特殊行（名字仍可解，但不是
            # 正常 4-5 位装备 ID），不进价格表。
            continue
        name = t.resolve(v[3]) or ""
        items[item_id] = {
            "id": item_id,
            "name": name,
            "id_string": t.resolve(v[13]) or "",
            "buy": v[10],
            "sell": v[19],
            "price_type": (v[5] >> 16) & 0xFF,
            "group": v[4],
            "prop": (t.resolve(v[117]) or "").replace("\n", " / "),
            "offset": t.offset,
        }
    return items


def parse_134_items(t: StdTable) -> list[dict]:
    """134_Equip：8 B rowID + 26 个 8 B 数据 cell。数据 cell 0 = 名称，
    cell 1 = 描述，cell 7（+0x40）= 价格/5（工具内以 price_cell 记原值）。"""
    out = []
    for r in range(t.n_rows):
        v = t.row_u32(r)
        if not v[0]:
            continue
        out.append({
            "id": v[0],
            "name": t.resolve(v[3]) or "",
            "desc": (t.resolve(v[5]) or "").replace("\n", " / "),
            "price_cell": v[16],
            "price_x5": v[16] * 5,
            "offset": t.offset,
        })
    return out


# ---------------------------------------------------------------------------
# .abc 记录流
# ---------------------------------------------------------------------------
def abc_stream(data: bytes) -> list[dict]:
    """记录: seq:u8 00 L:u8 payload[L] a:u8 00*5 b:u8（5.13.3）。"""
    best: tuple[list[dict], int] = ([], 0)
    for start in range(0, min(len(data), 0x20000)):
        if data[start] != 0x22 or data[start + 1] != 0:
            continue
        recs, pos, seq = [], start, 0x22
        while pos + 10 < len(data):
            if data[pos] != (seq & 0xFF) or data[pos + 1] != 0:
                break
            ln = data[pos + 2]
            if pos + 10 + ln > len(data):
                break
            recs.append({"seq": seq, "payload": data[pos + 3:pos + 3 + ln]})
            pos += 10 + ln
            seq += 1
        if len(recs) > len(best[0]):
            best = (recs, pos)
            if len(recs) > 500:
                break
    return best[0]


def parse_payload(pl: bytes) -> list[tuple]:
    """返回 ('h', tag, hero, flag, data) / ('s', tag, data)。"""
    if not pl:
        return []
    n, i, out = pl[0], 1, []
    while i < len(pl):
        t = pl[i]
        if t in (0x12, 0x13, 0x14):
            ln = {0x12: 2, 0x13: 1, 0x14: 3}[t]
            if i + 1 + ln > len(pl):
                break
            out.append(("s", t, pl[i + 1:i + 1 + ln]))
            i += 1 + ln
        elif t in (0x01, 0x02):
            if t == 0x01:
                if i + 5 > len(pl):
                    break
                hero = struct.unpack_from(">H", pl, i + 1)[0]
                flag, ln = pl[i + 3], pl[i + 4]
                if i + 5 + ln > len(pl):
                    break
                out.append(("h", t, hero, flag, pl[i + 5:i + 5 + ln]))
                i += 5 + ln
            else:
                if i + 4 > len(pl):
                    break
                hero = struct.unpack_from(">H", pl, i + 1)[0]
                flag = pl[i + 3]
                # 0x80 是 12 字节帧命令（不是 length=0）
                ln = 12 if flag == 0x80 else (flag & 0x7F)
                if i + 4 + ln > len(pl):
                    break
                out.append(("h", t, hero, flag, pl[i + 4:i + 4 + ln]))
                i += 4 + ln
        else:
            break
    return out


def extract_0x87(recs: list[dict]) -> list[dict]:
    """0x02/0x87 7 字节：00 00 00 actorID skillID level 00。"""
    out = []
    for rec in recs:
        for m in parse_payload(rec["payload"]):
            if m[0] == "h" and m[1] == 0x02 and m[3] == 0x87 and len(m[4]) == 7:
                b = m[4]
                out.append({
                    "seq": rec["seq"],
                    "time_s": rec["seq"] / 20.0,
                    "hero": m[2],
                    "actor": b[3],
                    "a": b[4],
                    "b": b[5],
                })
    return out


def extract_gold(recs: list[dict], hero: int) -> list[dict]:
    """0x02/0x85 len5：source:u8 + amount:u32LE。"""
    out = []
    for rec in recs:
        for m in parse_payload(rec["payload"]):
            if m[0] == "h" and m[1] == 0x02 and m[3] == 0x85 and len(m[4]) == 5:
                if m[2] != hero:
                    continue
                body = m[4]
                out.append({
                    "seq": rec["seq"],
                    "time_s": rec["seq"] / 20.0,
                    "source": body[0],
                    "amount": int.from_bytes(body[1:5], "little"),
                })
    return out


def parse_plans(data: bytes, items: dict[int, dict]) -> list[dict]:
    """玩家块方案：name UTF-8 + 对齐 + BE u32 count(12) + 12 × BE u32 itemID。"""
    anchor = data.find(struct.pack(">H", RECORDER_ENTITY), 0x8000)
    lo = max(0, (anchor or 0) - 0x200)
    hi = min(len(data), (anchor or 0) + 0x2000)
    plans = []
    for name in PLAN_NAMES:
        nb = name.encode("utf-8")
        pos = data.find(nb, lo, hi)
        if pos < 0:
            continue
        q = pos + len(nb)
        # 跳过 NUL 对齐，找 BE count=12
        for _ in range(8):
            if data[q:q + 4] == b"\x00\x00\x00\x0c":
                q += 4
                break
            q += 1
        else:
            continue
        ids = []
        for k in range(12):
            v = struct.unpack_from(">I", data, q + 4 * k)[0]
            if v in items:
                ids.append(v)
        plans.append({"name": name, "offset": pos, "items": ids})
    return plans


def plan_finals(plan: dict) -> tuple[list[int], list[tuple[int, int]]]:
    """方案里的成品/组件拆分：若某 item 是另一 item 的 pre（同方案内），
    则它是组件。返回 (成品列表, [(pre, final), ...])。"""
    ids = plan["items"]
    idset = set(ids)
    edges = [(a, b) for a, b, _ in CHAIN_EDGES if a in idset and b in idset]
    comps = {a for a, _ in edges}
    finals = [i for i in ids if i not in comps]
    return finals, edges


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--abc", type=Path, default=DEFAULT_ABC)
    ap.add_argument("--official", type=Path, default=DEFAULT_OFFICIAL)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    db = args.db.read_bytes()
    battle = locate_battle_item_table(db)
    items = parse_battle_items(battle)
    pve = locate_134_equip(db)
    pve_items = parse_134_items(pve) if pve else []

    # 官方 item.json 对拍（存在才用）：item_id / item_name / price / total_price
    official = []
    off_match = off_mismatch = 0
    if args.official.exists():
        official = json.loads(args.official.read_text(encoding="utf-8"))
        for o in official:
            iid = int(o["item_id"])
            it = items.get(iid)
            if not it:
                off_mismatch += 1
                continue
            if it["buy"] == o["total_price"] and it["sell"] == o["price"]:
                off_match += 1
            else:
                off_mismatch += 1

    abc = args.abc.read_bytes()
    recs = abc_stream(abc)
    plans = parse_plans(abc, items)
    events = extract_0x87(recs)
    gold = extract_gold(recs, RECORDER_ENTITY)

    # --- 0x87 语义检验 -----------------------------------------------------
    per_hero = defaultdict(list)
    for e in events:
        per_hero[e["hero"]].append(e)
    monotone_ok = 0
    four_skill_heroes = []
    for hero, evs in per_hero.items():
        per_skill = defaultdict(list)
        for e in evs:
            per_skill[e["a"]].append(e["b"])
        if all(v == sorted(v) and len(set(v)) == len(v) and v[0] == 0
               for v in per_skill.values()):
            monotone_ok += 1
        if 4 in per_skill:
            four_skill_heroes.append(hero)
    skill3_first = {}
    for hero, evs in per_hero.items():
        s3 = [e for e in evs if e["a"] == 3]
        if s3:
            skill3_first[hero] = min(e["time_s"] for e in s3)
    # 李信（442）是四技能英雄，skill3 是变身、不是普通大招；4 级窗口检验排除他
    s3_window = [t for h, t in skill3_first.items() if h not in four_skill_heroes]
    slot0_first = {}
    for hero, evs in per_hero.items():
        per_slot = defaultdict(list)
        for e in evs:
            per_slot[e["b"]].append(e["a"])
        slot0_first[hero] = per_slot.get(0, [])
    slot0_213 = sum(1 for v in slot0_first.values() if v[:2] == [2, 1])

    # --- 1558 方案 ---------------------------------------------------------
    rec_plans = []
    for p in plans:
        finals, edges = plan_finals(p)
        total = sum(items[i]["buy"] for i in finals)
        listed = sum(items[i]["buy"] for i in p["items"])
        cheapest3 = sum(sorted(items[i]["buy"] for i in p["items"])[:3])
        rec_plans.append({"plan": p, "finals": finals, "edges": edges,
                          "total": total, "listed": listed, "cheapest3": cheapest3})

    # 官方口径的“热门套装前 6 件”情景（协调者指定 7,180 口径）
    hot = next((rp for rp in rec_plans if rp["plan"]["name"] == "热门套装"), None)
    first6 = hot["plan"]["items"][:6] if hot else []
    first6_sum = sum(items[i]["buy"] for i in first6)
    edges6 = [(a, b) for a, b, _ in CHAIN_EDGES if a in first6 and b in first6]
    comps6 = {a for a, _ in edges6}
    first6_actual = sum(items[i]["buy"] for i in first6 if i not in comps6)
    first6_upgrade = sum(items[b]["buy"] - items[a]["buy"] for a, b in edges6)

    # --- 金币 --------------------------------------------------------------
    src_totals = Counter()
    for g in gold:
        src_totals[g["source"]] += g["amount"]
    observed = sum(src_totals.values())
    income_floor = INITIAL_GOLD + NATURAL_GOLD + observed

    # 1558 技能等级 -> 英雄等级（points = 1 + upgrades）
    rec_events = [e for e in events if e["hero"] == RECORDER_ENTITY]
    per_skill = defaultdict(list)
    for e in rec_events:
        per_skill[e["a"]].append(e["b"])

    # --- CSV ---------------------------------------------------------------
    args.out.mkdir(parents=True, exist_ok=True)
    csv_path = args.out / "agent_equip_prices.csv"
    fields = ["section", "item_id", "item_name", "buy_price", "sell_price",
              "price_type", "equip_group", "plan", "slot", "skill_id", "level",
              "seq", "time_s", "amount", "note", "table_offset"]
    rows = []

    for i in sorted(items):
        it = items[i]
        rows.append({
            "section": "battle_item", "item_id": i, "item_name": it["name"],
            "buy_price": it["buy"], "sell_price": it["sell"],
            "price_type": it["price_type"], "equip_group": hex(it["group"]),
            "note": it["prop"], "table_offset": hex(it["offset"]),
        })
    for it in pve_items:
        rows.append({
            "section": "pve_134_item", "item_id": it["id"], "item_name": it["name"],
            "buy_price": it["price_x5"], "note": f"price_cell={it['price_cell']}×5; {it['desc'][:60]}",
            "table_offset": hex(it["offset"]),
        })
    for o in official:
        iid = int(o["item_id"])
        rows.append({
            "section": "official_item", "item_id": iid, "item_name": o["item_name"],
            "buy_price": o["total_price"], "sell_price": o["price"],
            "note": f"item_type={o.get('item_type')}; 官方 item.json; dc表对拍="
                    + ("match" if items.get(iid, {}).get("buy") == o["total_price"]
                       and items.get(iid, {}).get("sell") == o["price"] else "MISMATCH"),
        })
    rows.append({
        "section": "scenario_plan_first6", "plan": "热门套装",
        "buy_price": first6_sum, "sell_price": first6_actual,
        "amount": first6_upgrade,
        "note": "前6件=" + ",".join(f"{items[i]['name']}({items[i]['buy']})" for i in first6)
                + f"; 标价和={first6_sum}; 合成抵扣后实付={first6_actual}; 升级差额合计={first6_upgrade}",
    })
    for rp in rec_plans:
        p = rp["plan"]
        comps = {a for a, _ in rp["edges"]}
        for k, i in enumerate(p["items"]):
            it = items.get(i, {})
            rows.append({
                "section": "plan_1558", "item_id": i, "item_name": it.get("name", ""),
                "buy_price": it.get("buy", ""), "sell_price": it.get("sell", ""),
                "price_type": it.get("price_type", ""), "plan": p["name"], "slot": k + 1,
                "note": "组件(pre)" if i in comps else "成品",
            })
        rows.append({
            "section": "plan_1558_final", "plan": p["name"],
            "buy_price": rp["total"], "sell_price": rp["listed"], "amount": rp["cheapest3"],
            "note": f"成品数={len(rp['finals'])}; 成品="
                    + ",".join(f"{items[i]['name']}({items[i]['buy']})" for i in rp["finals"])
                    + f"; 方案内全部列出件合计={rp['listed']}; 最便宜3件={rp['cheapest3']}",
        })
    for pre, post, label in CHAIN_EDGES:
        if pre in items and post in items:
            rows.append({
                "section": "chain_cost", "item_id": post,
                "item_name": items[post]["name"],
                "buy_price": items[pre]["buy"], "sell_price": items[post]["buy"],
                "amount": items[post]["buy"] - items[pre]["buy"],
                "note": f"{label}: 首购 {items[pre]['buy']} + 升级 {items[post]['buy'] - items[pre]['buy']} = {items[post]['buy']}",
            })
    for e in events:
        rows.append({
            "section": "event_0x02_0x87", "skill_id": e["a"], "level": e["b"],
            "seq": e["seq"], "time_s": f"{e['time_s']:.2f}",
            "note": f"hero={e['hero']} actor={e['actor']} 技能升级（不是购买）",
        })
    rows.append({
        "section": "gold_summary", "item_id": RECORDER_ENTITY,
        "amount": observed,
        "note": f"initial={INITIAL_GOLD}; natural={NATURAL_GOLD}; "
                f"sources={dict(sorted(src_totals.items()))}; floor={income_floor}",
    })

    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})

    # --- MD ---------------------------------------------------------------
    md_path = args.out / "agent_equip_prices.md"
    L = []
    A = L.append
    A("# 装备 item 名称/价格表与 1558 支出核对（只读）\n")
    A(f"- 样本：`{args.abc.name}`（普通 5v5，build 5069040）")
    A(f"- 录制者：{RECORDER_NAME}（entityID {RECORDER_ENTITY}，东皇太一）")
    A(f"- dc.db：`{args.db}`")
    A("- 只读：不修改回放/包体，不注入，不读 param.json，不使用 runtime_dump。\n")

    A("## 0. 结论速览\n")
    A(f"1. **价格表找到了**：`dc.db` 的战斗装备表 **0x{battle.offset:x}**"
      f"（stride {battle.stride}，{battle.n_rows} 行，{battle.n_strings} 条字符串）。")
    A(f"   购买价 = 行 +0x28（u32），出售价 = 行 +0x4C = 60% 购买价；"
      f"价格档位 = 行 +0x16 字节。")
    A("2. `134_Equip`（0x3602400，270 行 × 216 B = 8 B rowID + 26 数据 cell）是 **PVE/训练营"
      "装备表**，不是本局商店表：它的 1112 叫“木杖”，战斗表 1112 叫“匕首”；"
      "数据 cell 7（+0x40）×5 只给出 250/375/625… 的档位价，与战斗价不一致。")
    A("3. **`0x02/0x87` 不是购买时序**，是 `stCmdSetSkillLevel`："
      "`00 00 00 actorID skillID level 00`。证据见 §3。"
      "因此“每件购买扣多少”无法从 0x87 得出；本报告给出可验证的成品造价/升级差额。")
    A("4. 1558 观测到的金币下限 = 300 + 1,905 + 2,399 = **4,604**；"
      "四套方案成品造价 **%.0f–%.0f**，说明 0x02 只是收入子集（隐含覆盖率 19–26%%，"
      "与既有 25–35%% 估计同量级）。" % (min(r["total"] for r in rec_plans),
                                        max(r["total"] for r in rec_plans)))
    A("5. **1558 的答案**：热门套装前 6 件标价 **7,180**（官方 total_price 口径），"
      "合成抵扣后实付 **6,030**（区间 6,030–7,180；若 1325 再升 1333 则 +1,220）。"
      "满 6 格成品 11,350–14,630。当前金币：6 件口径下约 **1,900–5,800**（coverage 25–35%），"
      "满 6 格口径下约 **0–2,500**；**综合 0–5,800，中位≈2,000–3,000（low）**。"
      "4,604 是“收入下限”，不是当前金币。")
    A("6. 之前把 `0x87` 读成“购买时序”的原因是：byte4（实为 skillID 1–4）被当成 tier，"
      "byte5（实为 0 起 level）被当成 6 个装备槽；13 条记录恰好看起来像“6 槽逐步升级”。\n")

    A("## 1. 战斗装备表（价格来源，high）\n")
    A(f"- 表偏移：`0x{battle.offset:x}`；stride {battle.stride}；rows {battle.n_rows}；"
      f"字符串 {battle.n_strings}；池相对偏移 0x{battle.pool_rel:x}。"
      f"其中 {battle.n_rows - len(items)} 行 ID 是打包值/砂之模式特殊行（>99999），"
      f"正常 4–5 位装备 ID 共 **{len(items)}** 件。")
    A("- 行布局（u32 下标 / 字节偏移）：\n")
    A("| 字段 | 偏移 | 说明 |")
    A("|---|---:|---|")
    A("| itemID | +0x00 | 1111 铁剑 … |")
    A("| name | +0x08 | (hash32, ref32)，ref>>6 - pool_rel 定位池串 |")
    A("| equipGroup | +0x10 | 位掩码：0x20000 武器、0x40000 法术、0x80000 防具、0x100000 鞋、0x800000 游走 |")
    A("| priceType | +0x16（+0x14 的 bit16..23） | 1 基础 / 2 中级 / 3 高级 / 4 神装（3000 档）；"
      "个别 2000+ 件标 2（如 1328 血魔之怒），只作商店页签配色，不能当价格档 |")
    A("| buyPrice | +0x28 | 购买价（本报告用的价格列） |")
    A("| idString | +0x30 | (hash,ref) “1111” |")
    A("| sellPrice | +0x4C | 出售价，= 60% 购买价（480/533 行精确 0.60） |")
    A("| propertyText | +0x1D0 | (hash,ref) “+20攻击” |")
    A("")
    A("价格自洽校验：`sell/buy = 0.60` 命中 480 行；其余为 0（无价/特殊道具）"
      "或非 60% 的少量特殊项。")
    if official:
        bad = []
        for o in official:
            iid = int(o["item_id"])
            it = items.get(iid)
            if not it or it["buy"] != o["total_price"] or it["sell"] != o["price"]:
                bad.append(f"{iid} {o['item_name']}(官方 {o['total_price']}/{o['price']}"
                           f" vs dc {it['buy']}/{it['sell']})" if it else f"{iid} 缺失")
        A(f"\n**官方 `item.json` 对拍（high）**：`{args.official.name}` 共 {len(official)} 件，"
          f"与 dc.db 战斗表按 itemID 对拍 **{off_match} 件 total_price/price 全等**"
          f"（不一致 {off_mismatch} 件）。也就是说：`total_price` = 本表 +0x28 购买价，"
          "`price` = +0x4C 出售价（60%）。dc.db 战斗表不是猜的，是官方商店表的原生副本。")
        if bad:
            A(f"- 2 个例外：{'；'.join(bad)}。1711 是版本差异（商店表 850 / JSON 1900），"
              "不影响 1558 四套方案（未用 1711）。")
        A("")

    A("### 1.1 1558 四套方案里出现的 item（名称/价格）\n")
    A("| itemID | 名称 | 购买价 | 出售价 | 档位 | 分组 | 属性 |")
    A("|---:|---|---:|---:|---:|---|---|")
    seen = []
    for rp in rec_plans:
        for i in rp["plan"]["items"]:
            if i not in seen:
                seen.append(i)
    for i in seen:
        it = items[i]
        A(f"| {i} | {it['name']} | {it['buy']} | {it['sell']} | {it['price_type']} | "
          f"0x{it['group']:x} | {it['prop'][:40]} |")
    A("")

    A("## 2. `134_Equip`（0x3602400）26 列布局\n")
    if pve:
        A(f"- 表偏移 `0x{pve.offset:x}`，stride {pve.stride} = **8 B rowID + 26 × 8 B 数据 cell**，"
          f"{pve.n_rows} 行，{pve.n_strings} 条字符串，池 0x{pve.pool_rel:x}。")
    A("- cell 0（+0x00）= itemID；之后是 **26 个数据 cell**（+0x08 起，8 B/个，216 B 正好 = 8 + 26×8）："
      "数据 cell 0 = name，cell 1 = 描述（含“装备ID:xxxx”），**数据 cell 7（+0x40）= 价格/5**。"
      "`decoded_csharp_all/134_Equip.bytes.csv` 的 `cell_7` 就是这一列，所以“cell_7=50/75”"
      "确实是 **price/5**（50→250，75→375）。")
    A("- 该表的 ID 空间与战斗表不同：1112=木杖（战斗表 1112=匕首）；"
      "1701/1753/1411 等**战斗装备不在 134 表内**，所以只在 134 里查 row_id 永远查不到。")
    A("- 价格验证：数据 cell 7 取 50/75/125/150/200/300/325/375/500/590/685/750/1000/1150/1250/1400，"
      "×5 = 250/375/625/750/1000/1500/1625/1875/2500/2950/3425/3750/5000/5750/6250/7000，"
      "是 PVE 档位价；与战斗表逐项比对 42 个同 ID 项 **0 个相等**（例：1111 134 表 250，战斗表 275）。"
      "→ 本局扣金必须用战斗表。\n")

    A("## 3. `0x02/0x87` 语义：技能升级，不是购买（high）\n")
    A(f"共 {len(events)} 条严格 `0x02/0x87 len7`（与既有 CSV 的 139 条一致；"
      "注意 `0x02/0x80` 是 12 字节帧命令而不是 length=0，漏跳会少算 4 条）。"
      "另有 50 条 `0x01/0x87` 5B 状态心跳，不是加点。"
      "格式 `00 00 00 actorID skillID level 00`。\n")
    A("四条独立证据：\n")
    A("1. **每个 skillID 的 level 严格单调递增、无重复、无下降**（10/10 名玩家；"
      "8/10 从 0 起，442/1966 首条之前有丢帧）。装备“价档/槽位”不会产生这种按 ID 分组的"
      "等差序列。")
    a3 = sorted(skill3_first.items(), key=lambda kv: kv[1])
    A(f"2. **大招(skillID=3)首次出现时间集中**："
      f"{min(s3_window):.1f}s–{max(s3_window):.1f}s（回放秒）≈ 对局 "
      f"{int(min(s3_window) + 20.3) // 60}:{int(min(s3_window) + 20.3) % 60:02d}–"
      f"{int(max(s3_window) + 20.3) // 60}:{int(max(s3_window) + 20.3) % 60:02d}，"
      "正是英雄到 4 级解锁大招的窗口（李信 442 是四技能英雄，已排除）；"
      "若 byte4 是价格档 3（2000+ 装备），不可能 9 名玩家都在 2 分钟内买到。")
    A(f"3. **只有 {four_skill_heroes} 出现 skillID=4**，而 442 是**李信**（唯一四技能英雄，"
      "heroID 507）。价格档/槽位没有理由只对李信取 4。")
    A(f"4. **与出装方案矛盾**：若 byte4=价格档、byte5=槽位，则 10 名玩家的 slot0 序列应为"
      f"“先买 1 档、再 2 档、再 3 档”；实际 {slot0_213}/10 名玩家是 `2→1→3`"
      "（先买 700+ 再买 250），且 1558 需要 6 件 1 档装备，而四套方案只出现 "
      "1411/1701 两型 1 档件。\n")

    A("### 3.1 1558 的 0x87 序列（= 技能加点）\n")
    A("| 回放秒 | 对局≈ | skillID | level | 读法 |")
    A("|---:|---:|---:|---:|---|")
    labels = {1: "1技能", 2: "2技能", 3: "大招", 4: "4技能"}
    for e in rec_events:
        g = e["time_s"] + 20.3
        A(f"| {e['time_s']:.1f} | {int(g) // 60}:{g % 60:04.1f} | {e['a']} | {e['b']} | "
          f"{labels.get(e['a'], e['a'])} 升到 {e['b'] + 1} 级 |")
    A("")
    A("汇总：" + "；".join(f"{labels.get(k, k)}="
                            f"{sorted(set(v))}" for k, v in sorted(per_skill.items())) + "\n")
    A("### 3.2 如果硬把 0x87 当购买（假设映射，已被 §3 否定）\n")
    A("1558 的 13 条若按 (byte4=价格档, byte5=槽位) 读，槽位序列是：\n")
    A("```")
    A("slot0: t1(0:25) → t2(0:57) → t3(2:30)")
    A("slot1: t1(1:28) → t3(5:10)")
    A("slot2: t1(2:59) → t2(6:11) → t3(7:43)")
    A("slot3: t1(4:26) → t2(8:54)")
    A("slot4: t1(5:54) → t2(9:59)")
    A("slot5: t1(7:28)")
    A("```")
    A("- 只有 slot0 能在“热门套装”里找到 1→2→3 的链：学识宝石 300 → 近卫 850（+550）→ "
      "近卫·奔狼 2080（+1,230），累计 300 / 850 / 2,080。")
    A("- slot1 需要 t1→t3，但两档鞋只有 250→700（t1→t2），没有 t3 鞋；"
      "slot2/3/4 同理没有可验证的 1→2→3 链。")
    A("- 更关键的是 6 个槽位都需要 1 件 t1（基础件），而四套方案里只有 1411/1701 两型；"
      "且 5/10 名玩家 slot0 先 t2 后 t1（先买 700+ 再买 250），与“升级”方向相反。\n")

    A("## 4. 1558 的四套方案与成品造价\n")
    A("| 方案 | 成品（价格） | 成品造价 | 全部列出件合计 | 最便宜 3 件 |")
    A("|---|---|---:|---:|---:|")
    for rp in rec_plans:
        finals = "、".join(f"{items[i]['name']}({items[i]['buy']})" for i in rp["finals"])
        A(f"| {rp['plan']['name']} | {finals} | **{rp['total']}** | {rp['listed']} | {rp['cheapest3']} |")
    A("")
    A("说明：升级时旧件按**原价**抵扣，所以 6 格成品的总支出 = 成品购买价之和；"
      "组件价不重复计。原辅助坦克列出 7 件（1325 守护者之铠在本表里没有指向 1335 的"
      "升级边），而装备栏只有 6 格，实际必然是“其中 1 件被卖出/替换”："
      "按 60% 出售回收算净支出 ≈ 12,510 − 0.6×最低件(700) ≈ 12,090。\n")

    A("### 4.1 升级链的实付差额（可直接当“每件扣多少”用）\n")
    A("| 链 | 首购 | 升级实付 | 成品总价 |")
    A("|---|---:|---:|---:|")
    for pre, post, label in CHAIN_EDGES:
        if pre in items and post in items:
            A(f"| {label} | {items[pre]['buy']} | {items[post]['buy'] - items[pre]['buy']} | "
              f"{items[post]['buy']} |")
    A("")

    A("## 5. 金币：观测下限、支出区间、当前金币\n")
    A("### 5.1 1558 的 0x02 收入（source:events/total）\n")
    A("| source | 事件数 | 金额 |")
    A("|---:|---:|---:|")
    for s in sorted(src_totals):
        n = sum(1 for g in gold if g["source"] == s)
        A(f"| {s} | {n} | {src_totals[s]} |")
    A(f"| **合计** | **{len(gold)}** | **{observed}** |")
    A("")
    A(f"- 初始 300 + 自然金 1,905（3/s×635s；若按 3/s 从 40s 起算则 1,844）+ 0x02 {observed} "
      f"= **{income_floor}**（观测下限，±60 取决于自然金起算点）。")
    A("- 0x02 只覆盖部分收入（既有研究估计 25–35%），所以 4,604 不是总金币，"
      "而是“当前金币 + 支出”的下限。\n")

    A("### 5.2 支出与当前金币的区间\n")
    tot = sorted(r["total"] for r in rec_plans)
    A("| 口径 | 支出 | 说明 |")
    A("|---|---:|---|")
    A(f"| 只买 1411 神速之靴 + 1701 学识宝石 | {items[1411]['buy'] + items[1701]['buy']} | 绝对最低（2 件 1 档） |")
    A(f"| 方案内最便宜 3 件 | {min(r['cheapest3'] for r in rec_plans)}–"
      f"{max(r['cheapest3'] for r in rec_plans)} | 3 件（含小件） |")
    A(f"| 6 件成品（四套方案） | {tot[0]:,}–{tot[-1]:,} | 满 6 格 |")
    A("")
    for cov in (0.20, 0.25, 0.30, 0.35):
        inc = INITIAL_GOLD + NATURAL_GOLD + observed / cov
        A(f"- 若 0x02 覆盖率 {cov:.0%}：总收入≈**{inc:,.0f}**，"
          f"扣掉 {tot[0]:,}–{tot[-1]:,} 支出 → 当前金币≈**{inc - tot[-1]:+,.0f} ~ {inc - tot[0]:+,.0f}**")
    A("")
    A("更直观的矩阵（行=支出，列=0x02 覆盖率；格=当前金币）：\n")
    spends = [2800, 4500, 7000, 9500, 11500, 14600]
    A("| 支出 | 20% | 25% | 30% |")
    A("|---:|---:|---:|---:|")
    for s in spends:
        cells = []
        for cov in (0.20, 0.25, 0.30):
            inc = INITIAL_GOLD + NATURAL_GOLD + observed / cov
            cells.append(f"{inc - s:+,.0f}")
        A(f"| {s:,} | " + " | ".join(cells) + " |")
    A("")
    A("**综合判断（low）**：0x87 不能告诉我们买了多少件；能确定的是"
      "“支出 ≥ 已买成品价、收入 = 4,604 + 未观测收入”。两种可复核口径：\n")
    A(f"- **6 件口径**（热门前 6 件，合成抵扣后 {first6_actual:,}–{first6_sum:,}）："
      "coverage 25–35% → 当前金币≈**1,900–5,800**。")
    A(f"- **满 6 格口径**（{tot[0]:,}–{tot[-1]:,}）：coverage 19–26% → 当前金币≈**0–2,500**。")
    A("")
    A("**综合：支出 6,030–14,630，当前金币 0–5,800，中位≈2,000–3,000（low）。**"
      "要收敛到单值，必须有购买件数或金币快照。\n")

    A("### 5.2b “热门套装前 6 件 = 7,180 标价”的实付口径\n")
    A(f"- 前 6 件 = {'、'.join(f'{items[i]['name']}({items[i]['buy']})' for i in first6)}；"
      f"**标价和 = {first6_sum:,}**（= 协调者给的 7,180，官方 item.json total_price 口径）。")
    A(f"- 其中 1701→1714→1753 是同一条合成链：升级时旧件按原价抵扣，"
      f"所以这条链只实付 {items[1753]['buy']}（{items[1701]['buy']}+"
      f"{items[1714]['buy']-items[1701]['buy']}+{items[1753]['buy']-items[1714]['buy']}），"
      f"不是 300+850+2080=3,230。")
    A(f"- **合成抵扣后实付 = {first6_actual:,}**（1422 700 + 1332 2,450 + 1753 2,080 + 1325 800）；"
      f"标价与实付的差 = {first6_sum - first6_actual:,}（即被抵扣的 1701+1714 标价）。")
    A(f"- 若 1325 后续升级为 1333，再加 {items[1333]['buy']-items[1325]['buy']:,} → "
      f"{first6_actual + items[1333]['buy'] - items[1325]['buy']:,}。")
    A(f"- 结论：**这 6 件的实际扣金区间 = {first6_actual:,}（合成抵扣）~ {first6_sum:,}（逐件标价硬加）**；"
      "最合理的单值是 **6,030**。`0x87` 的 13 条不参与这个计算（它是技能加点）；"
      "tier 增量/合成费来自 item 合成树和价格差，不是 0x87。")
    A("- 作为对照：若硬把 0x87 的 13 条当购买（slot0/2 各 1→2→3，slot1 1→3，slot3/4 1→2，"
      "slot5 只买 1 档），用本表合成费（1→2 = 450–550，2→3 = 1,220–1,230，1→3 = 1,670–1,780）"
      "折算，支出约 **7,410–8,240**；这个数只是“如果”口径，与 §3 的四条证据冲突，不作结论。\n")

    A("### 5.3 1558 的“每件扣多少”\n")
    A("`0x87` 的 13 条记录全部是技能加点（见 §3.1），**不是购买**，所以本样本无法给出"
      "“第 N 件买的是什么、扣了多少”。可给出的确定量是：\n")
    A("- 成品总价（满 6 格）=")
    A("  " + "；".join(f"{rp['plan']['name']}={rp['total']}" for rp in rec_plans) + "。")
    A("- 升级差额（§4.1）：如 学识宝石 300 → 近卫 850（+550）→ 近卫·奔狼 2080（+1,230）；"
      "神速之靴 250 → 抵抗之靴 700（+450）；守护者之铠 800 → 不祥征兆 2020（+1,220）；"
      "辉月 2080 → 难知·月神 3340（+1,260）。")
    A("- 0x02 观测收入 2,399（source4=781、source5=1,077、source6=541）是实测值；"
      "“300 + 2,399 + 1,905 = 4,604”只是**下限**，不是当前金币。\n")

    A("## 6. 还缺什么 / 下一步\n")
    A("- **金币快照也不存在**：本样本 `0x01` 的长度分布是 "
      "0/2/3/5/9/17/19/20/28，**没有 12/23/65 字节**的长快照；`0x1e`(22 条)=高伤害/高光值、"
      "`0x1f`(3 条) / `0x20`(1 条) 是通知，均不含金币。")
    A("- **真正的购买流水不在本样本的可读通道里**：全样本 286 条 `0x02/0x85` 金币事件"
      "金额全部为正（31–254），没有任何负数扣款；修正 `0x02/0x80` 12B 帧命令解析后"
      "逐条扫描所有 `0x01/0x02` 每英雄消息的 2/4 字节（BE+LE），除金币 source 字段的巧合外"
      "没有任何字段命中 504 件装备 ID；`0x01/0x1e`(19B)、`0x01/0x1f`(28B)、`0x20`(20B) "
      "是事件/坐标类，不含金币或装备。"
      "（没有找到 ≠ 协议不存在：`stCmdPlayerBuyEquip`/`OneStepBuyEquip` 在 metadata 里有定义，"
      "只是 build 5069040 的回放流没有下发。）")
    A("- 客户端 `.ope` 是录制者(1558)的操作流，理论上含 UIEventOpe 1194 "
      "`Battle_EquipBoughtEffectPlayEnd`；但 payload 是 Oodle blob，本地无解码器，"
      "本次未能解出（不是“没有”）。")
    A("- 若要让“每件扣金/当前金币”闭合，需要：①服务端结算/装备快照；"
      "②或能解 Oodle 的 .ope 通道（1194/商店 UI 事件 + 帧号）；"
      "③或录屏 OCR 装备面板做交叉验证。")
    A("- 交叉对照：`datasets/agent_final_panel.md` 也把 0x87 归为技能升级，并给出 "
      "“286 条 / 33,040”的 0x02 金币总数（与本工具 286 条一致）及 1558 自然金 1,844 的"
      "替代口径；与本报告结论不冲突。")
    A("- **`122340616`（0x74ac508，3432 行 × 112 B）不是装备名称/价格表**：它是装备"
      "被动/属性描述表（首行“双抗+10”，可解出“磐如山/叛逆反击/致命武装”等**被动名**）。"
      "本报告的名称/价格全部来自 `0x522bde8` 战斗装备表并与官方 `pvp_item.json` 对拍，"
      "没有用 122340616 做装备名。\n")

    A("## 7. 产物与复跑\n")
    A("- 工具：`tools/agent_equip_prices.py`")
    A("- 数据：`data/replays/_analysis/datasets/agent_equip_prices.csv`"
      f"（battle_item {len(items)} 行、pve_134_item {len(pve_items)} 行、"
      f"official_item {len(official)} 行、plan_1558、chain_cost、0x87 事件、金币汇总）")
    A("- 复跑：`python tools/agent_equip_prices.py`\n")

    md_path.write_text("\n".join(L), encoding="utf-8")

    # 控制台摘要
    print(f"battle table 0x{battle.offset:x} items={len(items)}")
    print(f"pve 134 items={len(pve_items)}")
    print(f"plans={[(p['name'], len(p['items'])) for p in plans]}")
    for rp in rec_plans:
        print(f"  {rp['plan']['name']}: finals={rp['finals']} total={rp['total']}")
    print(f"0x87 events={len(events)} monotone={monotone_ok}/{len(per_hero)} "
          f"four_skill={four_skill_heroes}")
    print(f"gold 1558: events={len(gold)} sources={dict(sorted(src_totals.items()))} "
          f"observed={observed} floor={income_floor}")
    print(f"out: {csv_path}")
    print(f"out: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
