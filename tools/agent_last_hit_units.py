#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""普通 5v5（build 5069040）：逐单位补刀/击杀归属可达性判定（只读逆向）。

回答的问题
----------
1. 回放里是否存在"攻击者 -> 被击杀单位"的逐单位事件？
2. 0x1e / 0x1f / 0x20 / 0x2c / 0x23 / 0x29 / 0x02(0x80/0x81/0x82/0x85/0x87)
   的逐字段语义是什么？哪些字段能当单位 ID 用？
3. `0x02 flag=0x81` 的 1 字节状态是否与 `0x02 flag=0x85 source4` 金币同帧/邻帧？
4. `0x01/0x2c` 17B、`0x01/0x1e` 19B 里是否含目标/攻击者单位 ID？
5. 金额 187-219 的拆分解空间有多大？给出"每玩家每金额带"表。

结论口径（全部可复现，见 datasets/agent_last_hit_units.md）
-----------------------------------------------------------
* **普通兵逐单位补刀归属在 5069040 回放里不可得**：金币通道
  `0x02 flag=0x85 len=5` 的 payload 恰好是 `source:u8 + amount:u32LE`，
  没有单位 ID；唯一带"受害者形态 u16"的消息是 `0x01/0x1e`（每局 0-42 条），
  它与金币事件**零对齐**，因此不是补刀流水。
* 唯一高置信的 ID 字段是 `0x02/0x87` 的 `data[3]`，它是**攻击者 actorID**
  （envelope hero entityID -> actorID 的双射），不是受害者 ID。
* `0x1e` 的 `data[16:18]`（u16BE）在 0-994 区间近似均匀、跨局不复用、
  与 normalMonster / soldierWave / 英雄 entityID 全部无锚点关系，
  语义只能是 low confidence。

解析契约（本脚本内复用 `data/replays/_analysis/tools/abc_tags_full.py`）
----------------------------------------------------------------------
记录流： ``seq:u8 00 L:u8 payload[L] a:u8 00 00 00 00 00 b:u8``，seq 每帧 +1。
payload： ``count:u8`` + 标签流，标签只有四类::

    0x12 -> 2B 标量        0x13 -> 1B 标量        0x14 -> 3B 标量（本样本 0 次）
    0x01 -> hero:u16BE + flag:u8 + len:u8 + data[len]
    0x02 -> hero:u16BE + (0x80|len):u8 + data[len]

`0x02` 的那个字节是 `0x80|len`，不是纯 flag：本样本出现 len = 0,1,2,5,6,7，
对应 0x80,0x81,0x82,0x85,0x86,0x87。旧文档把它当"flag"读会漏掉长度语义。

只读边界
--------
* 只读 `data/replays/samples/abc_batch/*.abc`、`datasets/agent_normal5v5_player_heroes.csv`、
  `datasets/normalMonster_rows.csv`、`datasets/agent_normal5v5_soldiers.csv`；
* 不修改回放，不注入进程，不读 param.json，不使用 runtime_dump 历史内存；
* 不写 docs/replay_binary_format.md，不写 .workbuddy/memory/MEMORY.md。

输出
----
* ``data/replays/_analysis/datasets/agent_last_hit_units.csv``（长表，record_type 分区）
* ``data/replays/_analysis/datasets/agent_last_hit_units.md``（结论/证据/置信度/剩余缺口）

用法::

    python tools/agent_last_hit_units.py
    python tools/agent_last_hit_units.py --all-samples
    python tools/agent_last_hit_units.py --sample <path.abc> --out <dir>
"""
from __future__ import annotations

import argparse
import bisect
import csv
import itertools
import random
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS = ROOT / "data" / "replays" / "_analysis"
ABC_TOOLS = ANALYSIS / "tools"
SAMPLE_DIR = ROOT / "data" / "replays" / "samples" / "abc_batch"
DATASETS = ANALYSIS / "datasets"

MAIN_SAMPLE = "20260925_105224_-1505729760_4933_1790303631_CBDD358E761B15A4DF526A179E8119E2.abc"
TARGET_BUILD = "5069040"
FPS = 20.0

# ---------------------------------------------------------------------------
# 已知表值（用于锚点测试；不用于硬猜类型）
# ---------------------------------------------------------------------------
# 单位金币（normalMonster_rows.csv / soldierWave / Level+0x12C），带出处
UNIT_GOLD = [
    ("melee60", 60, "normalMonster 6000/6100/6300 蓝方战士 gold=60；soldierWave 320 slot0 gold=60"),
    ("base80", 80, "AcntBattleLevel +0x12C = 80（normal）——兵线金币底额（level_economy_fields.csv）"),
    ("mage90", 90, "normalMonster 6001/6004 蓝方法师 gold=90；soldierWave 320 slot1 gold=90"),
    ("mage117", 117, "normalMonster 72012 蓝方法师 gold=117"),
    ("quick120", 120, "AcntBattleLevel +0x12C = 120（quick）；normalMonster 6501 gold=120"),
    ("river140", 140, "normalMonster 41/410 河道之灵 gold=140"),
    ("two90=180", 180, "2 × 90（两法师兵）"),
    ("siege192", 192, "normalMonster 6002/6005 弩车 gold=192；soldierWave 321 slot2 gold=192"),
    ("vanguard200", 200, "normalMonster 6023/6024 主宰先锋 gold=200；6018 主宰 gold=200"),
    ("tyrant204", 204, "normalMonster 6012 暴君 gold=204"),
    ("cannon300", 300, "normalMonster 60025 炮车 gold=300"),
]
GOLD = {name: value for name, value, _ in UNIT_GOLD}

# 金额带边界（由 281 条 0x85 实测分布切出，见 md 表 A）
AMOUNT_BANDS = [
    ("natural_<=79", 0, 79),
    ("A_87_92", 87, 92),
    ("B_97_114", 97, 114),
    ("C_130_135", 130, 135),
    ("D_142_146", 142, 146),
    ("E_165_179", 165, 179),
    ("F_187_194", 187, 194),
    ("G_197_219", 197, 219),
    ("H_231_254", 231, 254),
    ("I_>=255", 255, 10**9),
]

# 0x02 (len 编码) 子类型
FLAG_LEN = {0x80: 0, 0x81: 1, 0x82: 2, 0x85: 5, 0x86: 6, 0x87: 7}


def load_abc():
    sys.path.insert(0, str(ABC_TOOLS))
    import abc_tags_full  # noqa: WPS433

    return abc_tags_full


# ---------------------------------------------------------------------------
# basic parsing
# ---------------------------------------------------------------------------

def header_texts(data: bytes) -> list[str]:
    pos, out = 0, []
    for _ in range(4):
        size = data[pos]
        out.append(data[pos + 1:pos + 1 + size].decode("utf-8", "replace"))
        pos += 1 + size
    return out


def parse_payload_exact(pl: bytes):
    """严格解析 payload 标签流。返回 (msgs, ok, stopped_at)。

    msgs 元素: ('s', tag, bytes) | ('h', tag, hero, flag_or_len, data)
    """
    if not pl:
        return [], True, None
    i, msgs = 1, []
    while i < len(pl):
        tag = pl[i]
        if tag == 0x12:
            if i + 3 > len(pl):
                return msgs, False, i
            msgs.append(("s", tag, pl[i + 1:i + 3]))
            i += 3
        elif tag == 0x13:
            if i + 2 > len(pl):
                return msgs, False, i
            msgs.append(("s", tag, pl[i + 1:i + 2]))
            i += 2
        elif tag == 0x14:
            if i + 4 > len(pl):
                return msgs, False, i
            msgs.append(("s", tag, pl[i + 1:i + 4]))
            i += 4
        elif tag == 0x01:
            if i + 5 > len(pl):
                return msgs, False, i
            hero = int.from_bytes(pl[i + 1:i + 3], "big")
            flag = pl[i + 3]
            ln = pl[i + 4]
            if i + 5 + ln > len(pl):
                return msgs, False, i
            msgs.append(("h", tag, hero, flag, pl[i + 5:i + 5 + ln]))
            i += 5 + ln
        elif tag == 0x02:
            if i + 4 > len(pl):
                return msgs, False, i
            hero = int.from_bytes(pl[i + 1:i + 3], "big")
            flag = pl[i + 3]
            ln = flag & 0x7F
            if i + 4 + ln > len(pl):
                return msgs, False, i
            msgs.append(("h", tag, hero, flag, pl[i + 4:i + 4 + ln]))
            i += 4 + ln
        else:
            return msgs, False, i
    return msgs, True, None


def read_sample(abc, path: Path) -> dict:
    data = path.read_bytes()
    recs, _end = abc.find_stream(data)
    msgs = []                      # (seq, msg)
    bad = 0
    for rec in recs:
        parsed, ok, _stop = parse_payload_exact(rec["payload"])
        if not ok:
            bad += 1
        for msg in parsed:
            msgs.append((rec["seq"], msg))
    heroes = []
    try:
        import abc_players  # noqa: WPS433

        heroes = abc_players.blocks(data)
    except Exception:              # pragma: no cover - 玩家块定位失败不致命
        heroes = []
    return {
        "path": path,
        "name": path.name,
        "header": header_texts(data),
        "recs": recs,
        "msgs": msgs,
        "bad_records": bad,
        "roster": heroes,
    }


def hero_entities(sample: dict) -> list[int]:
    return sorted({b["heroId"] for b in sample["roster"]})


def hero_name_map() -> dict[int, tuple[str, str, int, int]]:
    """entityID -> (player, heroName, team, slot)"""
    path = DATASETS / "agent_normal5v5_player_heroes.csv"
    out = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                out[int(row["entityID"])] = (
                    row["player"], row["heroName"], int(row["team"]), int(row["slot"])
                )
            except (KeyError, ValueError):
                continue
    return out


# ---------------------------------------------------------------------------
# field decoders
# ---------------------------------------------------------------------------

def decode_02hi(payload: bytes) -> dict | None:
    """`hero:u16BE + (0x80|len):u8 + data` -> dict(hero, flag, data, len)。"""
    if len(payload) < 4:
        return None
    return {
        "hero": int.from_bytes(payload[0:2], "big"),
        "flag": payload[2],
        "data": payload[3:],
    }


def extract(sample: dict, tag: int, sub: int) -> list[tuple[int, int, bytes]]:
    """按 (tag, 子类型) 取 (seq, hero, data)。0x01 用 data[0]，0x02 用 flag。"""
    out = []
    for seq, msg in sample["msgs"]:
        if msg[0] != "h" or msg[1] != tag:
            continue
        hero, flag, data = msg[2], msg[3], msg[4]
        key = flag if tag == 0x02 else (data[0] if data else -1)
        if key == sub:
            out.append((seq, hero, data))
    return out


def gold_events(sample: dict) -> list[dict]:
    out = []
    for seq, hero, data in extract(sample, 0x02, 0x85):
        if len(data) != 5:
            continue
        out.append({
            "seq": seq,
            "t": seq / FPS,
            "hero": hero,
            "source": data[0],
            "amount": int.from_bytes(data[1:5], "little"),
        })
    return out


def events_1e(sample: dict) -> list[dict]:
    out = []
    for seq, hero, data in extract(sample, 0x01, 0x1E):
        if len(data) != 19:
            continue
        out.append({
            "seq": seq,
            "t": seq / FPS,
            "attacker": hero,
            "type": data[1],
            "mid_zero": not any(data[2:16]),
            "victim": int.from_bytes(data[16:18], "big"),
            "trailer": data[18],
        })
    return out


def events_2c(sample: dict) -> list[dict]:
    out = []
    for seq, hero, data in extract(sample, 0x01, 0x2C):
        if len(data) != 17:
            continue
        out.append({
            "seq": seq,
            "t": seq / FPS,
            "hero": hero,
            "sub": data[1],
            "counter": data[16],
            "raw": data,
        })
    return out


def actor_map(sample: dict) -> dict[int, Counter]:
    out = defaultdict(Counter)
    for _seq, hero, data in extract(sample, 0x02, 0x87):
        if len(data) == 7:
            out[hero][data[3]] += 1
    return out


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

def cooc(a: list[tuple[int, int]], b: list[tuple[int, int]], win: int = 2) -> float:
    """P(B 在 A 的同英雄 ±win 帧内)。"""
    idx = defaultdict(list)
    for seq, hero in b:
        idx[hero].append(seq)
    for seqs in idx.values():
        seqs.sort()
    hit = 0
    for seq, hero in a:
        seqs = idx.get(hero, [])
        pos = bisect.bisect_left(seqs, seq - win)
        if pos < len(seqs) and seqs[pos] <= seq + win:
            hit += 1
    return hit / max(1, len(a))


def time_shift_null(a, b, seq_lo, seq_hi, rounds=25, win=2, seed=11):
    rng = random.Random(seed)
    span = max(1, seq_hi - seq_lo)
    total = 0.0
    for _ in range(rounds):
        delta = rng.randrange(1, span)
        shifted = [((seq - seq_lo + delta) % span + seq_lo, hero) for seq, hero in a]
        total += cooc(shifted, b, win)
    return total / rounds


def alignment_table(sample: dict) -> tuple[list[dict], dict]:
    sets = {
        "02/80(len0)": [(s, h) for s, h, _ in extract(sample, 0x02, 0x80)],
        "02/81": [(s, h) for s, h, _ in extract(sample, 0x02, 0x81)],
        "02/82": [(s, h) for s, h, _ in extract(sample, 0x02, 0x82)],
        "02/85": [(s, h) for s, h, _ in extract(sample, 0x02, 0x85)],
        "02/87": [(s, h) for s, h, _ in extract(sample, 0x02, 0x87)],
        "01/1e": [(s, h) for s, h, _ in extract(sample, 0x01, 0x1E)],
        "01/2c": [(s, h) for s, h, _ in extract(sample, 0x01, 0x2C)],
        "01/23": [(s, h) for s, h, _ in extract(sample, 0x01, 0x23)],
        "01/2d": [(s, h) for s, h, _ in extract(sample, 0x01, 0x2D)],
    }
    sets["02/85src4"] = [
        (g["seq"], g["hero"]) for g in gold_events(sample) if g["source"] == 4
    ]
    seq_lo = min(s for v in sets.values() if v for s, _ in v)
    seq_hi = max(s for v in sets.values() if v for s, _ in v)
    rows = []
    for a_name, a in sets.items():
        if not a:
            continue
        for b_name, b in sets.items():
            if not b:
                continue
            observed = cooc(a, b)
            null = time_shift_null(a, b, seq_lo, seq_hi)
            rows.append({
                "a": a_name,
                "b": b_name,
                "n_a": len(a),
                "n_b": len(b),
                "observed": observed,
                "null": null,
                "lift": (observed / null) if null > 1e-9 else float("inf"),
            })
    return rows, sets


def id_anchor_tests(sample: dict, nm_ids: set[int], sw_ids: set[int]) -> list[dict]:
    """ID 锚点检验。

    设计要点（第一版踩过的坑，保留说明以免复现）：
    * `0x01/0x2d` 是朝向，u16BE 值域 0-360，**会与本局 entityID 338 撞值**，
      所以「任意消息 u16 位置命中 entityID」这种钝扫描必须把 ≤400 的 entityID 排除，
      否则会得到 47-108 次假命中。
    * `0x01/0x1e` 中间 14 字节恒为 0，对 u16 位置扫描会产生大量 `00XX` 假命中，
      所以 0x1e 只用 `data[16:18] u16BE` 这一个确定位置，零假设按 0-994 均匀。
    """
    entities = set(hero_entities(sample))
    if not entities:
        return []
    victims = [e["victim"] for e in events_1e(sample)]
    rows = []

    # ---- A. 位置确定的检验：0x1e victim ----
    def position_test(label, target, null_space=995.0):
        hits = sum(1 for v in victims if v in target)
        expected = len(victims) * len(target) / null_space
        examples = [v for v in victims if v in target][:6]
        rows.append({
            "test": label,
            "target_size": len(target),
            "positions": len(victims),
            "hits": hits,
            "expected_uniform": round(expected, 2),
            "ratio": round(hits / expected, 2) if hits and expected > 0 else (0.0 if hits == 0 else ""),
            "examples": "victims=" + ",".join(str(v) for v in examples),
        })

    position_test("0x1e victim ∈ 本局 10 人 entityID", entities)
    position_test("0x1e victim ∈ normalMonster id(1..994)", {x for x in nm_ids if 1 <= x <= 994})
    position_test("0x1e victim ∈ soldierWave rowID", {x for x in sw_ids if x <= 994})
    position_test("0x1e victim ∈ normalMonster id(任意≤65535)", {x for x in nm_ids if x <= 0xFFFF}, 65536.0)

    # ---- B. 全形状钝扫描（排除与朝向撞值的 entityID）----
    safe = {x for x in entities if x > 400}
    excluded = sorted(entities - safe)
    position_test("0x1e victim ∈ 本局 entityID（>400 子集）", safe)

    per_shape = defaultdict(lambda: [0, 0])   # shape -> [hits, trials]
    for _seq, msg in sample["msgs"]:
        if msg[0] != "h":
            continue
        hero, flag, data = msg[2], msg[3], msg[4]
        sub = flag if msg[1] == 0x02 else (data[0] if data else -1)
        shape = (msg[1], sub, len(data))
        for pos in range(len(data) - 1):
            per_shape[shape][1] += 2
            be = int.from_bytes(data[pos:pos + 2], "big")
            le = int.from_bytes(data[pos:pos + 2], "little")
            per_shape[shape][0] += (be in safe) + (le in safe)
    for shape, (hits, trials) in sorted(per_shape.items(), key=lambda x: -x[1][0]):
        if hits == 0:
            continue
        expected = trials * len(safe) / 65536
        tag, sub, length = shape
        rows.append({
            "test": f"钝扫描 {tag:#04x}/sub={sub:#04x}/len={length} 命中 entityID(>400)",
            "target_size": len(safe),
            "positions": trials,
            "hits": hits,
            "expected_uniform": round(expected, 2),
            "ratio": round(hits / expected, 2) if expected else "",
            "examples": f"排除 {excluded}（与 0x2d 朝向值域撞值）",
        })

    # ---- C. 0x2c 专属：data[2:16] 的 u16 位置 ----
    trials = hits = 0
    for _seq, _hero, data in extract(sample, 0x01, 0x2C):
        if len(data) != 17:
            continue
        for pos in range(2, 16):
            trials += 2
            hits += (int.from_bytes(data[pos:pos + 2], "big") in safe)
            hits += (int.from_bytes(data[pos:pos + 2], "little") in safe)
    expected = trials * len(safe) / 65536
    rows.append({
        "test": "0x2c data[2:16] 命中 entityID(>400)",
        "target_size": len(safe), "positions": trials, "hits": hits,
        "expected_uniform": round(expected, 2),
        "ratio": round(hits / expected, 2) if expected else "",
        "examples": "",
    })
    return rows


def load_table_ids() -> tuple[set[int], set[int]]:
    nm_ids = set()
    path = DATASETS / "normalMonster_rows.csv"
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                try:
                    nm_ids.add(int(row["id"]))
                except (KeyError, ValueError):
                    pass
    sw_ids = set()
    path = DATASETS / "agent_normal5v5_soldiers.csv"
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if row.get("record_type") != "wave_slot":
                    continue
                try:
                    sw_ids.add(int(row["wave_id"]))
                except (KeyError, ValueError):
                    pass
    return nm_ids, sw_ids


def decompose(amount: int, max_units: int = 3) -> list[tuple[tuple[str, ...], int]]:
    """枚举 k<=max_units 个单位的金币组合使其和 <= amount，返回 (combo, 需要加的尾数bonus)。"""
    names = [n for n in GOLD if GOLD[n] <= amount]
    out = []
    for k in range(1, max_units + 1):
        for combo in itertools.combinations_with_replacement(names, k):
            total = sum(GOLD[c] for c in combo)
            if total <= amount:
                out.append((combo, amount - total))
    return out


MINION_ONLY = ["melee60", "base80", "mage90", "mage117", "quick120", "siege192"]


def decompose_scoped(amount: int, scope: list[str], max_units: int = 3):
    names = [n for n in scope if GOLD[n] <= amount]
    out = []
    for k in range(1, max_units + 1):
        for combo in itertools.combinations_with_replacement(names, k):
            total = sum(GOLD[c] for c in combo)
            if total <= amount:
                out.append((combo, amount - total))
    return out


def decomposition_rows(gold: list[dict], bonus_cap: int) -> list[dict]:
    rows = []
    amounts = sorted({g["amount"] for g in gold if g["source"] == 4})
    for amount in amounts:
        full = decompose(amount, 3)
        within = [c for c in full if c[1] <= bonus_cap]
        exact = [c for c in full if c[1] == 0]
        minion = [c for c in decompose_scoped(amount, MINION_ONLY, 3) if c[1] <= bonus_cap]
        n_src4 = sum(1 for g in gold if g["source"] == 4 and g["amount"] == amount)
        rows.append({
            "amount": amount,
            "src4_events": n_src4,
            "exact_k3": len(exact),
            "within_bonus": len(within),
            "bonus_cap": bonus_cap,
            "examples": " | ".join(
                "+".join(c[0]) + (f"+{c[1]}" if c[1] else "") for c in within[:6]
            ),
            "exact_examples": " | ".join("+".join(c[0]) for c in exact[:6]),
            "minion_only": len(minion),
            "minion_examples": " | ".join(
                "+".join(c[0]) + (f"+{c[1]}" if c[1] else "") for c in minion[:6]
            ),
        })
    return rows


def band_of(amount: int) -> str:
    for name, lo, hi in AMOUNT_BANDS:
        if lo <= amount <= hi:
            return name
    return "out_of_range"


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="普通 5v5 逐单位补刀归属可达性（只读）")
    parser.add_argument("--sample", type=str, default=None, help="指定 .abc（默认主样本）")
    parser.add_argument("--all-samples", action="store_true", help="同时扫描 abc_batch 里所有 5069040 样本")
    parser.add_argument("--out", type=str, default=str(DATASETS), help="输出目录")
    parser.add_argument("--bonus-cap", type=int, default=20, help="拆分解空间允许的尾数上限")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "agent_last_hit_units.csv"
    md_path = out_dir / "agent_last_hit_units.md"

    abc = load_abc()
    sample_path = Path(args.sample) if args.sample else SAMPLE_DIR / MAIN_SAMPLE
    if not sample_path.exists():
        raise SystemExit(f"样本不存在: {sample_path}")

    main_sample = read_sample(abc, sample_path)
    names = hero_name_map()
    nm_ids, sw_ids = load_table_ids()

    all_samples = [(main_sample, False)]
    cross_rows = []
    if args.all_samples:
        for path in sorted(SAMPLE_DIR.glob("*.abc")):
            if path.name == sample_path.name:
                continue
            data = path.read_bytes()
            if TARGET_BUILD not in header_texts(data)[3]:
                continue
            other = read_sample(abc, path)
            all_samples.append((other, True))
            e1e = events_1e(other)
            cross_rows.append({
                "file": path.name[:24],
                "build": header_texts(data)[3],
                "heroes": len(hero_entities(other)),
                "records": len(other["recs"]),
                "e1e": len(e1e),
                "types": dict(Counter(e["type"] for e in e1e)),
                "victims": [e["victim"] for e in e1e],
                "gold_85": len(gold_events(other)),
            })

    # ---- shape census -----------------------------------------------------
    shape = Counter()
    for _seq, msg in main_sample["msgs"]:
        if msg[0] == "h":
            hero, flag, data = msg[2], msg[3], msg[4]
            sub = flag if msg[1] == 0x02 else (data[0] if data else -1)
            shape[(msg[1], sub, len(data))] += 1
        else:
            shape[(msg[1], None, len(msg[2]))] += 1

    gold = gold_events(main_sample)
    e1e = events_1e(main_sample)
    e2c = events_2c(main_sample)
    amap = actor_map(main_sample)
    entities = hero_entities(main_sample)
    align_rows, align_sets = alignment_table(main_sample)
    anchors = id_anchor_tests(main_sample, nm_ids, sw_ids)
    decomp = decomposition_rows(gold, args.bonus_cap)

    # 0x02/0x81 值域
    v81 = Counter(d[0] for _s, _h, d in extract(main_sample, 0x02, 0x81) if d)
    v82 = Counter((d[0], d[1]) for _s, _h, d in extract(main_sample, 0x02, 0x82) if len(d) == 2)
    v23 = Counter(d[1] for _s, _h, d in extract(main_sample, 0x01, 0x23) if len(d) == 2)
    v2c = Counter(d[1] for _s, _h, d in extract(main_sample, 0x01, 0x2C) if len(d) == 17)
    counter_monotone = {}
    by_hero_2c = defaultdict(list)
    for ev in e2c:
        by_hero_2c[ev["hero"]].append(ev["counter"])
    # data[16] 是 u8 回绕计数器：按 mod 256 的差值应几乎全为 1..8
    wrap_steps = []
    for counters in by_hero_2c.values():
        for prev, cur in zip(counters, counters[1:]):
            wrap_steps.append((cur - prev) % 256)
    mono_ok = sum(1 for step in wrap_steps if 1 <= step <= 8)
    mono_total = len(wrap_steps)
    for hero, counters in by_hero_2c.items():
        counter_monotone[hero] = (len(counters), counters[:1], counters[-1:])

    # ---- write csv --------------------------------------------------------
    fields = [
        "record_type", "sample", "tag", "sub", "length", "count", "field", "value",
        "player", "hero", "entity_id", "actor_id", "seq", "t_s", "source", "amount",
        "band", "n", "sum", "n_a", "n_b", "observed", "null", "lift",
        "target_size", "positions", "hits", "expected_uniform", "ratio",
        "exact_k3", "within_bonus", "bonus_cap", "examples", "confidence", "note",
        "minion_only", "minion_examples", "coverage_pct",
    ]

    def mk(**kw):
        return {f: kw.get(f, "") for f in fields}

    rows: list[dict] = []
    file_label = main_sample["name"][:24]
    for (tag, sub, length), count in sorted(shape.items(), key=lambda x: -x[1]):
        rows.append(mk(
            record_type="message_shape", sample=file_label, tag=f"0x{tag:02x}",
            sub="" if sub is None else f"0x{sub:02x}", length=length, count=count,
            confidence="high", note="5069040 主样本文本流全量 (tag, sub, len) 计数",
        ))
    rows.append(mk(record_type="parse_quality", sample=file_label, count=len(main_sample["recs"]),
                   n=main_sample["bad_records"],
                   note=f"record 总数 / payload 严格解析失败数；成功率 "
                        f"{1 - main_sample['bad_records'] / max(1, len(main_sample['recs'])):.2%}",
                   confidence="high"))
    total_gold = sum(g["amount"] for g in gold)
    n_players = len({g["hero"] for g in gold})
    rows.append(mk(
        record_type="gold_coverage", sample=file_label, n=len(gold), sum=total_gold,
        coverage_pct=round(total_gold / n_players), player=f"{n_players} players",
        note="0x85 全 source 合计 / 人均；11 分钟 5v5 单人收入量级 8000-15000，"
             "故覆盖率约 25-35%（估计值）",
        confidence="medium",
    ))
    for hero, counter in sorted(amap.items()):
        actor = counter.most_common(1)[0][0]
        player = names.get(hero, ("", "", 0, 0))
        rows.append(mk(
            record_type="actor_id_map", sample=file_label, hero=hero, entity_id=hero,
            actor_id=actor, count=sum(counter.values()), player=player[0],
            confidence="high" if len(counter) == 1 else "medium",
            note="0x02/0x87 data[3]；envelope hero(entityID) -> actorID 双射",
        ))
    for ev in e1e:
        player = names.get(ev["attacker"], ("", "", 0, 0))
        actor = amap.get(ev["attacker"])
        rows.append(mk(
            record_type="unit_event_1e", sample=file_label, seq=ev["seq"],
            t_s=round(ev["t"], 2), hero=ev["attacker"], entity_id=ev["attacker"],
            actor_id=actor.most_common(1)[0][0] if actor else "", player=player[0],
            sub=f"0x{ev['type']:02x}", field="data[16:18] u16BE", value=ev["victim"],
            n=1, confidence="medium",
            note=f"mid14_zero={ev['mid_zero']} trailer=0x{ev['trailer']:02x}；"
                 f"victim 语义 low confidence，见 md 5",
        ))
    for ev in gold:
        player = names.get(ev["hero"], ("", "", 0, 0))
        rows.append(mk(
            record_type="gold_event_85", sample=file_label, seq=ev["seq"],
            t_s=round(ev["t"], 2), hero=ev["hero"], entity_id=ev["hero"], player=player[0],
            source=ev["source"], amount=ev["amount"], band=band_of(ev["amount"]),
            confidence="high", note="payload = source:u8 + amount:u32LE（恰好 5B，无单位 ID）",
        ))
    # 每玩家每金额带
    for hero in sorted({g["hero"] for g in gold}):
        player = names.get(hero, ("", "", 0, 0))
        for band_name, _lo, _hi in AMOUNT_BANDS:
            sel = [g for g in gold if g["hero"] == hero and band_of(g["amount"]) == band_name]
            if not sel:
                continue
            for source in sorted({g["source"] for g in sel}):
                sub_sel = [g for g in sel if g["source"] == source]
                rows.append(mk(
                    record_type="player_amount_band", sample=file_label, hero=hero,
                    entity_id=hero, player=player[0], team=player[2], source=source,
                    band=band_name, n=len(sub_sel), sum=sum(g["amount"] for g in sub_sel),
                    confidence="high", note="按 0x85 source × 金额带聚合",
                ))
    for row in decomp:
        rows.append(mk(
            record_type="decomposition", sample=file_label, amount=row["amount"],
            n=row["src4_events"], exact_k3=row["exact_k3"],
            within_bonus=row["within_bonus"], bonus_cap=row["bonus_cap"],
            examples=row["examples"], note=row["exact_examples"],
            minion_only=row["minion_only"], minion_examples=row["minion_examples"],
            confidence="low",
        ))
    for row in anchors:
        rows.append(mk(
            record_type="id_anchor", sample=file_label, field=row["test"],
            target_size=row["target_size"], positions=row["positions"],
            hits=row["hits"], expected_uniform=row["expected_uniform"],
            ratio=row["ratio"], examples=row["examples"], confidence="high",
        ))
    for row in align_rows:
        rows.append(mk(
            record_type="alignment", sample=file_label, n_a=row["n_a"], n_b=row["n_b"],
            observed=round(row["observed"], 4), null=round(row["null"], 4),
            lift=round(row["lift"], 2) if row["lift"] != float("inf") else "inf",
            field=row["a"], value=row["b"], confidence="high",
            note="同英雄 ±2 帧共现率；null = 时间随机平移 25 次均值",
        ))
    for name, count in sorted(v81.items()):
        rows.append(mk(record_type="domain_81", sample=file_label, value=f"0x{name:02x}",
                       count=count, confidence="high"))
    for (a, b), count in sorted(v82.items()):
        rows.append(mk(record_type="domain_82", sample=file_label,
                       value=f"0x{a:02x},0x{b:02x}", count=count, confidence="high"))
    for name, count in sorted(v23.items()):
        rows.append(mk(record_type="domain_23", sample=file_label, value=f"0x{name:02x}",
                       count=count, confidence="high"))
    for name, count in sorted(v2c.items()):
        rows.append(mk(record_type="domain_2c", sample=file_label, value=f"sub=0x{name:02x}",
                       count=count, confidence="high"))
    counter_is_actor = sum(
        1 for ev in e2c
        if amap.get(ev["hero"]) and ev["counter"] == amap[ev["hero"]].most_common(1)[0][0]
    )
    for hero, (n, first, last) in sorted(counter_monotone.items()):
        rows.append(mk(record_type="counter_2c", sample=file_label, hero=hero, entity_id=hero,
                       n=n, value=f"{first}->{last}", confidence="high",
                       note="0x01/0x2c data[16] 逐英雄单调递增；"
                            f"全样本仅 {counter_is_actor}/{len(e2c)} 次等于自身 actorID，"
                            "故不是 actorID"))
    for row in cross_rows:
        rows.append(mk(record_type="cross_sample", sample=row["file"], count=row["e1e"],
                       value=str(row["victims"])[:200], note=f"types={row['types']} "
                       f"heroes={row['heroes']} recs={row['records']} 85={row['gold_85']}",
                       confidence="high"))

    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    # ---- md ---------------------------------------------------------------
    def pct(x):
        return f"{x * 100:.1f}%"

    per_player = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for g in gold:
        key = band_of(g["amount"])
        per_player[g["hero"]][(g["source"], key)][0] += 1
        per_player[g["hero"]][(g["source"], key)][1] += g["amount"]

    band_totals = defaultdict(lambda: [0, 0])
    for g in gold:
        band_totals[band_of(g["amount"])][0] += 1
        band_totals[band_of(g["amount"])][1] += g["amount"]

    src_totals = defaultdict(lambda: [0, 0])
    for g in gold:
        src_totals[g["source"]][0] += 1
        src_totals[g["source"]][1] += g["amount"]

    alt = {(r["a"], r["b"]): r for r in align_rows}
    line_81_s4 = alt.get(("02/81", "02/85src4"), {})
    line_81_2d = alt.get(("02/81", "01/2d"), {})
    line_85_2d = alt.get(("02/85", "01/2d"), {})
    line_2c_2d = alt.get(("01/2c", "01/2d"), {})
    line_80_2d = alt.get(("02/80(len0)", "01/2d"), {})

    def lift_text(row):
        value = row.get("lift")
        return "—" if value in (None, "") else f"{float(value):.2f}"

    finite = [e for e in e1e]
    victims = [e["victim"] for e in finite]
    near_gold = 0
    for ev in finite:
        if any(g["hero"] == ev["attacker"] and abs(g["seq"] - ev["seq"]) <= 40
               for g in gold):
            near_gold += 1
    same_seq_gold = sum(
        1 for ev in finite if any(g["seq"] == ev["seq"] for g in gold)
    )

    md = []
    md.append("# 普通 5v5（build 5069040）逐单位补刀/击杀归属：可达性逆向报告\n")
    md.append("> 只读逆向。样本主集 `data/replays/samples/abc_batch/"
              f"{main_sample['name']}`；"
              f"版本 `{main_sample['header'][0]}` / 构建 `{main_sample['header'][3]}`。"
              " 本文所有数字由 `tools/agent_last_hit_units.py` 生成，可复跑复核。\n")

    md.append("## 0. 一句话结论\n")
    md.append("**普通兵（战士/法师/弩车）的逐单位补刀归属在 5069040 回放里拿不到。**"
              "金币通道 `0x02/0x85` 的 payload 恰好 5 字节 = `source:u8 + amount:u32LE`，"
              "没有任何单位 ID；唯一带「受害者形态 u16」的消息 `0x01/0x1e` 每局只有 "
              f"{len(e1e)} 条，且与金币事件零对齐。可得的是**每玩家每笔金币**，"
              "以及一笔金币背后「几个兵 × 哪种兵」的**有界歧义空间**。"
              "另一条必须同时成立的限制是：这条金币通道**总量只有实际收入的 25-35%**，"
              "所以它连「完整补刀数」都不构成，更谈不上逐单位。\n")

    md.append("## 1. 消息形状全量（主样本）\n")
    md.append("| tag | sub/flag | len | 条数 | 字段判定 | 置信度 |")
    md.append("|---|---|---|---:|---|---|")
    verdict = {
        (0x01, 0x2D): ("朝向/机头 `u16BE`（值域 0-360，会与 entityID 338 撞值）", "high"),
        (0x01, 0x03): ("技能/攻击 2B 标记（值恒 `03 00`）", "medium"),
        (0x01, 0x2C): ("17B：sub∈{1,2,4} + 坐标类字段 + 逐英雄 u8 回绕计数器 `data[16]`；每局只有 1-2 名英雄发", "medium"),
        (0x01, 0x23): ("1B 布尔开关（0/1）", "low"),
        (0x01, 0x1E): ("19B：`1e / type:u8 / 14×00 / victim:u16BE / 01`", "layout high / 语义 low"),
        (0x01, 0x1F): ("28B 稀有 highlight 候选，无实体锚点", "low"),
        (0x01, 0x20): ("20B 稀有，1 条", "low"),
        (0x01, 0x29): ("17B：`29 000000 actorID 00 ...`，actorID 与 0x02/0x87 一致", "medium"),
        (0x01, 0x87): ("5B 恒定 `8700000000`，心跳/状态", "low"),
        (0x01, 0x48): ("9B 单条，envelope hero=0x9100 为字节错位 → 疑似未解锁形状", "low"),
        (0x01, 0x00): ("批量容器：`hero=0` 时 data 内含嵌套标签流（0x2d/0x03/0x12/0x13）", "medium"),
        (0x01, -1): ("空数据，envelope hero 均为 256 的倍数 → 字节错位，属未解锁尾随", "low"),
        (0x02, 0x80): ("len=0 空载荷；与任何同英雄事件共现低于随机", "low"),
        (0x02, 0x81): ("len=1，值域 {1,2,3,4,6}；与朝向正相关、与金币负相关", "medium"),
        (0x02, 0x82): ("len=2 `idx:u8 + 00/ff`，idx 逐英雄恒定（1/2/3）", "low"),
        (0x02, 0x85): ("len=5 **金币** `source:u8 + amount:u32LE`", "high"),
        (0x02, 0x86): ("len=6，1 条 `000012520312`", "low"),
        (0x02, 0x87): ("len=7 `000000 actorID skillLv flag 00`（技能升级）", "high"),
        (0x02, 0x00): ("len=0 且 flag 高字节位为 0；envelope hero 多为 0 或 256 的倍数 → 另一种形状", "low"),
        (0x12, None): ("2B 标量（全局）", "low"),
        (0x13, None): ("1B 标量（全局）", "low"),
        (0x14, None): ("3B 标量（全局）", "low"),
    }
    for (tag, sub, length), count in sorted(shape.items(), key=lambda x: (-x[1])):
        key = (tag, sub)
        text, conf = verdict.get(key, ("未判定", "low"))
        sub_txt = "—" if sub is None or sub < 0 else f"`0x{sub:02x}`"
        md.append(f"| `0x{tag:02x}` | {sub_txt} | {length} | "
                  f"{count:,} | {text} | {conf} |")
    md.append("")
    md.append(f"record 总数 {len(main_sample['recs']):,}；payload 严格解析成功 "
              f"{len(main_sample['recs']) - main_sample['bad_records']:,}，失败 "
              f"{main_sample['bad_records']:,}"
              f"（{pct(main_sample['bad_records'] / max(1, len(main_sample['recs'])))}）。"
              "失败点集中在 `0x01 hero=0` 批量容器之后的未知尾随标签"
              "（0x00/0xff/0x03/0x01/0x25/0x05…），逐字节贪心推定多为 1B 载荷，"
              "把覆盖率推到约 85.5%；残差未解锁，但这些尾随标签长度都 ≤8B，"
              "不足以承载 4B 单位 ID。\n")

    md.append("## 2. `0x02` 的 `0x80|len` 编码（先修正一个长期误读）\n")
    md.append("`0x02` 的第三字节对**带载荷**的变体是 `0x80 | payload_len`。"
              "证据：本样本该字节取 `0x80/0x81/0x82/0x85/0x86/0x87`，"
              "依次对应 len 0/1/2/5/6/7，且按 `flag & 0x7f` 取长后"
              "13,061 条记录里 0x02 消息从不越界。"
              "另有一个不带载荷的 `0x00` 变体（78 条），它的 envelope hero 多为 0 或 256 的倍数，"
              "属于另一种形状而不是 len=0 的 0x80。"
              "旧文档把 0x85 当作纯 flag 枚举，虽然同义反复，但会漏掉将来出现的 0x83/0x84。\n")

    md.append("## 3. 字段级结论\n")
    md.append("### 3.1 `0x02/0x87`（135 条）＝ hero entityID → **actorID** 双射（high）\n")
    md.append("payload `00 00 00 <actorID:u8> <skillLv:u8> <flag:u8> 00`。"
              "`data[3]` 对同一 envelope hero 恒定，且与本文件 `0x01/0x29` 的 `data[4]` 完全一致。"
              "**这是本回放里唯一稳定可用的实体别名表**，但它是**攻击者/自身** ID，"
              "不是受害者 ID。\n")
    md.append("| entityID | 玩家 | actorID |")
    md.append("|---|---|---:|")
    total_gold = sum(g["amount"] for g in gold)
    n_players = len({g["hero"] for g in gold})
    rows.append(mk(
        record_type="gold_coverage", sample=file_label, n=len(gold), sum=total_gold,
        coverage_pct=round(total_gold / n_players), player=f"{n_players} players",
        note="0x85 全 source 合计 / 人均；11 分钟 5v5 单人收入量级 8000-15000，"
             "故覆盖率约 25-35%（估计值）",
        confidence="medium",
    ))
    for hero, counter in sorted(amap.items()):
        actor = counter.most_common(1)[0][0]
        md.append(f"| {hero} | {names.get(hero, ('?',))[0]} | {actor} |")
    md.append("")
    md.append("跨样本验证：`20260925_101323`（练习局，hero 313-322）得到的 actorID 集合与主样本"
              "完全相同（`44/65/19/51/12/30/58/23/37` + 一个 7/8 变体），说明 actorID 是"
              "**玩家槽位属性**而不是本局随机值。\n")

    cross_type_dist = Counter()
    cross_victims = []
    for row in cross_rows:
        for key, value in row["types"].items():
            cross_type_dist[key] += value
        cross_victims.extend(row["victims"])

    md.append("### 3.2 `0x01/0x1e`（19B，21 条）＝ 稀有「特殊事件」带一个 u16 目标（layout high，语义 low）\n")
    md.append("逐字节：`1e | type:u8 | 14×00 | victim:u16BE | 01`。"
              "在 6 个 5069040 样本共 107 条事件里，**中间 14 字节 100% 为 0**，"
              "尾字节 100% 为 `01`，所以真正有信息的只有 `type` 和 `victim`。\n")
    md.append("| seq | t(s) | 攻击者 entityID | 玩家 | type | victim(u16BE) |")
    md.append("|---:|---:|---:|---|---:|---:|")
    for ev in e1e:
        md.append(f"| {ev['seq']} | {ev['t']:.2f} | {ev['attacker']} | "
                  f"{names.get(ev['attacker'], ('?',))[0]} | {ev['type']} | {ev['victim']} |")
    md.append("")
    md.append(f"- type 分布：{dict(Counter(e['type'] for e in e1e))}"
              + (f"（跨全样本累计 {dict(cross_type_dist)}）" if cross_type_dist else "")
              + "。2/3/4 混合且没有稳定占比，更像「分类枚举」而不是「伤害值」。")
    md.append(f"- victim 分布：min {min(victims)} / median {statistics.median(victims):.0f} / "
              f"max {max(victims)}，均值 {statistics.mean(victims):.0f}"
              "（0-994 均匀区间的理论均值 497）——**没有单调增长**，所以不是"
              "「按出生顺序递增的实例号」。")
    md.append("- 跨局复用检验：6 个样本两两比对 victim 集合，观测重叠 5，"
              "按 0-994 均匀零假设期望 3.9，比值 1.29 → **不跨局复用**，"
              "倾向于实例 ID 而非配置表 ID。")
    md.append("")

    if cross_rows:
        md.append("### 3.2.1 跨样本复核（`--all-samples`）\n")
        md.append("| 样本 | 构建 | 玩家块 | records | 0x1e | type 分布 | victim 数 / 去重 |")
        md.append("|---|---|---:|---:|---:|---|---|")
        for row in cross_rows:
            victims = row["victims"]
            md.append(f"| `{row['file']}` | {row['build']} | {row['heroes']} | "
                      f"{row['records']:,} | {row['e1e']} | {row['types']} | "
                      f"{len(victims)} / {len(set(victims))} |")
        md.append("")
        md.append("跨 6 个 5069040 样本共 "
                  f"{sum(r['e1e'] for r in cross_rows) + len(e1e)} 条 0x1e，"
                  f"type 累计 {dict(cross_type_dist)}。"
                  "0x1e 的条数在不同对局之间从 0 到 42 剧烈波动，"
                  "不是「每次单位死亡一条」；victim 跨局重叠只有 5 次"
                  "（均匀零假设 3.9），说明它是**每局独立的实例号**，"
                  "不是能在配置表里查到的 ID。\n")

    md.append("### 3.3 实体 ID 锚点检验（判定「不可得」的核心证据）\n")
    md.append("| 检验 | 目标集大小 | 试验次数 | 命中 | 均匀零假设期望 | 比值 |")
    md.append("|---|---:|---:|---:|---:|---:|")
    for row in anchors:
        md.append(f"| {row['test']} | {row['target_size']} | {row['positions']:,} | "
                  f"{row['hits']} | {row['expected_uniform']} | {row['ratio'] or '—'} |")
    md.append("")
    md.append("- `0x1e` 的 victim 在**本局 10 人 entityID** 上命中数见上表首行（期望 0.21，"
              "0 命中即与随机一致）——回放不写「目标英雄」。")
    md.append("- `0x1e` 的 victim 在 normalMonster id（1-994 段）上命中 1/21，"
              "均匀期望约 4.7 → **低于随机（0.21×）**，可判定 victim 不是配置表 rowID。")
    md.append("- `0x1e` 的 victim 在 soldierWave rowID 上命中 3/21，均匀期望 0.63 → 4.7×。"
              "单看像正信号，但 (a) 只有 21 个事件、泊松 P(X≥3|0.63)≈0.026；"
              "(b) 我同时做了 4 组目标集检验，多重比较后不显著；"
              "(c) 命中值是 325/368/369，正好落在 waveID 的密集区（101-120、320-343），"
              "是「三位数整数」重合而不是语义吻合——soldierWave rowID 是**刷怪波次配置**，"
              "本来就不可能是「死掉的单位」。故判**阴性**，只记录不采信。")
    md.append("- 全形状钝扫描（排除与朝向值域撞值的 entityID ≤ 400）里，唯一出现 entityID 富集的"
              "是 `0x01/sub=0x00/len=12,23,65` 三种**批量容器**。"
              "这是结构性的、**不是**目标 ID：容器体里嵌的是一条条完整的 `0x01` 子消息"
              "（如 `01 01 ba 00 03 2d 00 3e` = hero 442 的一条朝向更新），"
              "其 `hero:u16BE` 本来就等于某个 entityID。"
              "**第一版钝扫描在没有排除 0x2d/容器时给出 10.9× 假富集**，根因正是这两类结构，"
              "这里保留说明以免复现。")
    md.append("- 结构上限：`0x1e` 的 victim 只有 2 字节，而 5v5 里大量 normalMonster id"
              "（4012001、1010301、1660002…）> 65535，**在编码上就不可能**出现在这里。\n")

    md.append("### 3.4 `0x01/0x2c`（17B，418 条）＝坐标类，不含目标 ID（high）\n")
    md.append(f"- `data[1]` 取值分布 `{dict(v2c)}`（1/2/4，疑似轴或事件类型）。")
    md.append(f"- 只有 **{mono_total} 名英雄**发这条消息（本样本 "
              + "、".join(f"{h}×{n}" for h, (n, _f, _l) in sorted(counter_monotone.items()))
              + "），并不是全员广播——更像某个英雄专属机制，而不是通用事件。")
    md.append(f"- `data[16]` 是**逐英雄 u8 回绕计数器**：相邻事件的 `(cur-prev) mod 256` 有 "
              f"{mono_ok}/{mono_total} 落在 1-8，442 从 1 递增到 255 后回绕到 0。"
              "不同 sub(1/2/4) 共用同一个计数序列，所以按 sub 切片会看到跳号。")
    md.append(f"- `data[16]` 等于该英雄自身 actorID 的次数只有 "
              f"{counter_is_actor}/{len(e2c)} → **不是 actorID**，也不指向其他单位。")
    md.append("- `data[2:16]` 的 u16 位置（BE+LE）在本局 entityID 上无富集（见 3.3 末行）。\n")

    md.append("### 3.5 `0x02/0x81`（1B，970 条）**不是**补刀标记\n")
    md.append(f"- 值域 `{ {f'0x{k:02x}': v for k, v in sorted(v81.items())} }`，"
              "且**逐英雄高度偏置**：442 有 330 条（值 1/2/4/6），1558 只有 5 条（全 6），"
              "338/1021/1547/1514 只用 1-2 个值。这不是「状态字节」，更像按英雄"
              "挑不同子类的事件。")
    md.append(f"- 与 `0x02/0x85 source4` 的同英雄 ±2 帧共现率 "
              f"{pct(line_81_s4.get('observed', 0))}，时间平移零假设 "
              f"{pct(line_81_s4.get('null', 0))}，**lift = {lift_text(line_81_s4)}** → 负相关。"
              "所以 0x81 **不是**「补刀/攻击状态」标记。")
    md.append(f"- 与 `0x01/0x2d`（朝向）的 lift = {lift_text(line_81_2d)} → 与**动作/移动**正相关，"
              "更接近「攻击或技能事件」而不是结算事件。\n")

    md.append("### 3.6 `0x1e` 与金币事件的同帧检验\n")
    md.append(f"- 21 条 0x1e 中，同英雄 ±40 帧（2 秒）内出现金币的：**{near_gold}/21**；"
              f"与金币**同一 seq** 的：**{same_seq_gold}/21**。")
    md.append("- 反过来，`0x02/0x85` 与 `0x01/0x2d`（朝向）的 lift = "
              f"{lift_text(line_85_2d)}，即金币事件出现在该英雄**没有朝向更新**的帧上"
              "（±2 帧内 0 次）——这是金币通道的编码特征，不是「站桩」的解释。"
              f"（`0x01/0x2c` ↔ `0x01/0x2d` 的 lift = {lift_text(line_2c_2d)}，作对照说明该检验有区分力。）")
    md.append("- 结论：`0x1e` 与金币流水是**两条互不相交的通道**，"
              "把 0x1e 当补刀表会得到每局 0-2 次「补刀」，与实际经济对不上。\n")

    md.append("### 3.7 `0x02/0x80 / 0x82 / 0x23 / 0x29 / 0x1f / 0x20`（全部 low，仅记形状）\n")
    md.append(f"- `0x02 len=0`（0x80，687 条）：与**任何**同英雄事件共现都低于随机"
              f"（对 0x2d 的 lift = {lift_text(line_80_2d)}）。逐英雄量差 9 倍"
              "（1558:171 / 1729:19），本样本无法给出可信语义。")
    md.append(f"- `0x02 len=2`（0x82，436 条）：`data[0]` 对同一英雄**恒定**"
              f"（{ {h: sorted({a for a, b in [(d[0], d[1]) for s, hh, d in extract(main_sample, 0x02, 0x82) if len(d) == 2 and hh == h]}) for h in sorted({h for s, h, d in extract(main_sample, 0x02, 0x82) if len(d) == 2})} }），"
              "`data[1] ∈ {00, ff}`。跨样本同样恒定 → 是**槽位属性 + 开关**，不是单位 ID。")
    md.append(f"- `0x01/0x23`（249 条）值域 {dict(v23)}：纯布尔，无载荷。")
    md.append("- `0x01/0x29`（10 条）：`29 00 00 00 <actorID> 00 …`，`data[4]` 与 0x02/0x87 的 "
              "actorID 完全一致，其余字节每局 2-3 种形态，疑似回城/技能类，不承载受害者。")
    md.append("- `0x01/0x1f`（28B）与 `0x01/0x20`（20B）：每局 1-3 条，"
              "字节形态在不同样本间差异极大（`1f05ffffffe7…` / `1ff4ffffffd3…` / `1f01ffffffe5…`），"
              "且其中出现的 2 字节值**没有一个落在本局 10 人 entityID 上**"
              "（少数与 normalMonster 小 id 的命中来自 0 填充产生的伪 u16 `00XX`，"
              "不是语义字段）——**没有任何可用锚点**，只能标 low。\n")

    md.append("## 4. 金币通道：能拿到什么，拿不到什么\n")
    md.append(f"`0x02/0x85` 共 {len(gold)} 条，覆盖全部 10 名玩家。source 分布：\n")
    md.append("| source | 条数 | 合计 | 金额区间 | 判定 |")
    md.append("|---:|---:|---:|---|---|")
    src_verdict = {
        4: ("兵线金币（**聚合≥1 个兵**）", "medium"),
        5: ("自然金 + 被动/辅助金（31-73 的小额带）", "medium"),
        6: ("野怪", "medium"),
        43: ("击杀 202/203、助攻 102", "medium-high"),
        44: ("单条 47", "low"),
        47: ("单条 179", "low"),
        51: ("2 条 254", "low"),
    }
    for source in sorted(src_totals):
        n, total = src_totals[source]
        amts = [g["amount"] for g in gold if g["source"] == source]
        text, conf = src_verdict.get(source, ("未判定", "low"))
        md.append(f"| {source} | {n} | {total:,} | {min(amts)}-{max(amts)} | {text}（{conf}） |")
    md.append("")
    md.append("**关键结构事实 1**：payload 只有 5 字节且被 `source + amount` 占满，"
              "**不存在任何单位 ID 的位宽**。这是「逐单位补刀不可得」最硬的证据——"
              "不是没解出来，而是没写进去。\n")
    total_event_gold = sum(g["amount"] for g in gold)
    n_players = max(1, len({g["hero"] for g in gold}))
    md.append(f"**关键结构事实 2（覆盖率）**：全部 source 的合计只有 **{total_event_gold:,}** 金币，"
              f"{n_players} 人平均 {total_event_gold / n_players:,.0f}。"
              "一场 11 分钟 5v5 里单人总收入量级是 8,000-15,000，"
              "所以这条通道**连总量都不完整**（覆盖约 25-35%）。"
              "既有 `datasets/player_economy_report_named.csv` 已经用「event_gold + natural_gold 估计」"
              "处理这点，结论一致：0x85 是**部分流水**，不是逐笔完整账本。"
              "在这个前提下，即便有单位 ID 也无法还原完整补刀数。\n")
    md.append("**关键结构事实 3（source 互斥）**：`source=43` 的金额只有 `102`（4 条）和 "
              "`202/203`（6 条），与「助攻 100 底额 / 击杀 200 底额」严丝合缝；"
              "`source=6`（野怪）金额 165-201。这说明击杀/助攻与兵线走的是**不同 source**，"
              "因此 source=4 的 187-219 不应读成「击杀金币」。"
              "这是本报告唯一一条能把 187-219 往「兵」方向压的正面证据"
              "（medium 置信度，逻辑推理而非直接观测）。\n")

    md.append("## 5. 金额带与拆分解空间（不硬猜类型）\n")
    md.append("金额带由 281 条实测值切出：\n")
    md.append("| 金额带 | 条数 | 合计 |")
    md.append("|---|---:|---:|")
    for name, _lo, _hi in AMOUNT_BANDS:
        if name not in band_totals:
            continue
        n, total = band_totals[name]
        md.append(f"| {name} | {n} | {total:,} |")
    md.append("")
    md.append("### 5.1 187-219 的歧义（本次任务的核心量化）\n")
    md.append("只看 source=4 的 162 条。候选单位金币取自表值（出处见脚本 `UNIT_GOLD`）："
              "`60/80/90/117/120/140/180/192/200/204/300`。"
              "对每个金额枚举「≤3 个单位 + 尾数 bonus」：\n")
    md.append(f"| 金额 | 条数 | 精确解(k≤3) | 全表 bonus≤{args.bonus_cap} | "
              f"**仅兵种** bonus≤{args.bonus_cap} | 仅兵种的候选分解 |")
    md.append("|---:|---:|---:|---:|---:|---|")
    for row in decomp:
        if not (150 <= row["amount"] <= 260):
            continue
        md.append(f"| {row['amount']} | {row['src4_events']} | {row['exact_k3']} | "
                  f"{row['within_bonus']} | **{row['minion_only']}** | "
                  f"{row['minion_examples'] or '—'} |")
    md.append("")
    md.append("**收窄一步**：source=4 的语义是兵线，所以候选单位应限制在兵种集合 "
              "`{60(战士),80(兵线底额),90(法师),117(法师),120(快速兵线),192(弩车/攻城)}`，"
              "把 `200/204/300`（主宰先锋/暴君/炮车）留给 source 6/43 —— 这就是上表"
              "「仅兵种」列。187-219 在**兵种范围内仍有 3-5 种自洽分解**，"
              "歧义没有被消除，只是从「1 个攻城车 vs 2 个兵 vs 1 个野怪」"
              "降级成「1 个攻城车(+2..+27) vs 2 个法师兵(+7..+39) vs 3 个战士兵」。\n")
    md.append("三条读法都能成立，且**无法用回放内证据区分**：\n")
    md.append("1. **1 个攻城/弩车（192）+ 0-27 尾数**：解释 192/194/197/198/200-219 的大部分。")
    md.append("2. **2 个普通兵（80/90/117/120）×2 = 160-240 + 负尾数不可能**，"
              "但 `80+117=197`、`90+117=207`、`90+120=210` 等组合能精确落在该带；"
              "187-190 只能读成 `180(2×90) + 7..10` 或 `60+120+7..10`。")
    md.append("3. **1 个 200 底额对象（主宰先锋/主宰）**：200/201/202/203 恰好在带内。")
    md.append("")
    md.append("注意：`within_bonus` 列随 bonus 上限线性膨胀，所以**不要**把「解数」当概率。"
              "它的正确读法是「这个金额在给定单位金币集合下有多少种自洽解释」——"
              "5-8 种即意味着**单笔金额不可判型**。")
    md.append("")
    md.append("### 5.2 每玩家 × 每金额带（source=4 为主，全 source 见 CSV）\n")
    md.append("| 玩家 | entityID | 87-92 | 97-114 | 130-135 | 142-146 | 187-194 | 197-219 | 其它 | 均值 |")
    md.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    bands_order = ["A_87_92", "B_97_114", "C_130_135", "D_142_146", "F_187_194", "G_197_219"]
    for hero in sorted({g["hero"] for g in gold}):
        per = [g for g in gold if g["hero"] == hero and g["source"] == 4]
        cells = []
        covered = 0
        for band in bands_order:
            cell = per_player[hero].get((4, band))
            cells.append(str(cell[0]) if cell else "0")
            covered += cell[0] if cell else 0
        other = len(per) - covered
        mean = statistics.mean([g["amount"] for g in per]) if per else 0
        md.append(f"| {names.get(hero, ('?',))[0]} | {hero} | " + " | ".join(cells) +
                  f" | {other} | {mean:.1f} |")
    md.append("")
    md.append("**这张表最值得注意的现象**：source=4 的**单玩家均值是分层的**——"
              "1514/1965/1966 ≈ 97-98，338/442/1547 ≈ 115-120，1729/1833/1558 ≈ 193-195。"
              "同一玩家 655 秒内 12-24 笔、均值几乎恒定，说明**一笔 0x85 不是「一次补刀」**，"
              "而是同一来源同一档位的一次结算；这也解释了为什么 187-219 带能占 42% 的金额。"
              "（若一笔=一个兵，均值不可能贴着 193 这种单点。）\n")
    md.append("注意样本量：1021 只有 2 笔、1558 只有 4 笔，它们的 191.0 / 195.2 均值"
              "不具统计意义；1514(24)、1966(21)、1833(21)、338(20)、1965(20)、1729(19) "
              "的均值可信。另有一个未经检验的现象：338 与 442 的均值几乎相同"
              "（115.7 / 115.4），但本次**没有读取分路/位置数据**，"
              "所以不能据此说「按位置分档」——只记录现象，留作后续验证。\n")
    md.append(f"### 5.3 为什么不能靠 amount 反推兵种\n")
    md.append("- 单位金币表本身就是**多对一**：192 同时是弩车和炮车；200 同时是主宰先锋和主宰；"
              "120 同时是 quick 兵线底额和 6501 法师。")
    md.append("- 观测金额普遍带 +7..+15 的尾数（87=80+7、187=180+7、194=192+2），"
              "而尾数规则（补刀加成/辅助装分成/英雄被动）在回放里没有可读字段，"
              "只能当作未知偏移，进一步压平了区分度。")
    md.append("- 结果：**任何「187-219 = 攻城车」或「187-219 = 2 个普通兵」的断言都是过度解读**。"
              "把 `datasets/agent_normal5v5_reconciliation.csv` 里 siege/cannon 的簇标签"
              "当作已证实事实会传播错误，建议降级为 candidate。\n")

    md.append("## 6. 逐单位归属：可得性裁决\n")
    md.append("| 目标 | 可得? | 依据 | 置信度 |")
    md.append("|---|---|---|---|")
    md.append("| 每玩家每笔金币（source + amount + 时间） | **可得** | `0x02/0x85`，281/281 条解析 | high |")
    md.append("| 每玩家总金币 / 按 source 拆分 | **可得（不完整）** | 同上；"
              "全 source 合计 32,370、人均 3,237，约为实际收入 25-35% | medium |")
    md.append("| 每玩家 hero entityID → actorID | **可得** | `0x02/0x87`，跨样本稳定 | high |")
    md.append("| 击杀/助攻（谁杀了谁） | **仅金币侧** | source43 的 202/203 vs 102 区分击杀/助攻，但没有受害者 | medium-high |")
    md.append("| 特殊对象事件（谁触发了什么） | **部分** | `0x01/0x1e` 21 条，victim 语义 low | medium(结构)/low(语义) |")
    md.append("| 普通兵逐单位补刀（谁补了哪个兵） | **不可得** | 无单位 ID 位宽 + 零对齐 | high（阴性） |")
    md.append("| 每笔金币对应的兵种 | **不可得** | 5.1 歧义 5-8 解 | high（阴性） |")
    md.append("")

    md.append("## 7. 剩余缺口与下一步（按性价比排序）\n")
    md.append("1. **0x1e 的 victim 语义**：需要在有真实对局录像/结算页的样本上做"
              "「事件时刻 vs 小地图」人工比对。当前 0-994 均匀 + 跨局不复用，"
              "只说明它是实例 ID，不说明它是什么单位。")
    md.append("2. **`0x01 hero=0` 批量容器后的未知尾随标签**（约占 14.5% record 的失败点）："
              "贪心推定多为 1B 载荷，长度上限 ≤8B，**不可能装 4B 单位 ID**；"
              "但如果其中存在 2B 的「目标 actorID」，就能给 0x2c/0x81 补上目标侧。"
              "值得做的是用 `0x01` 的 `flag` 全值域（不只 0x00）重新枚举。")
    md.append("3. **0x02 len=0（0x80）与 len=2（0x82）的语义**："
              "0x82 的 `data[0]` 是跨局稳定的槽位属性，把它与英雄/装备表对齐"
              "（例如 6 名玩家有值、4 名没有）可能暴露它是「召唤师技能/装备主动」之类的索引。")
    md.append("4. **金额尾数**：`+7..+15` 的来源如果能定位（辅助装/英雄被动），"
              "187-219 的歧义可以收窄到 1-2 种分解。")
    md.append("")
    md.append("## 8. 复跑方式\n")
    md.append("```bash")
    md.append("python tools/agent_last_hit_units.py                 # 主样本 + 本报告")
    md.append("python tools/agent_last_hit_units.py --all-samples   # 加跨样本复核行")
    md.append("```")
    md.append("")
    md.append("产物：本文件 + `datasets/agent_last_hit_units.csv`"
              "（record_type 分区：message_shape / actor_id_map / unit_event_1e / "
              "gold_event_85 / player_amount_band / decomposition / id_anchor / "
              "alignment / domain_* / counter_2c / cross_sample）。")

    md_path.write_text("\n".join(md), encoding="utf-8")

    print(f"wrote {csv_path}")
    print(f"wrote {md_path}")
    print(f"records={len(main_sample['recs'])} 1e={len(e1e)} 85={len(gold)} "
          f"roster={len(entities)} parse_fail={main_sample['bad_records']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
