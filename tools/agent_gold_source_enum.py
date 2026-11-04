#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""局内金币来源枚举 + 自然金投递路径（只读逆向）。

目标（对应 docs/replay_binary_format.md 5.82/5.83/5.85/5.86）：
  1. 在 global-metadata.dat / libGameCore.so 里找完整金币来源枚举；
  2. 把回放 0x02 flag=0x85 len=5 观测到的 source 4/5/6/43/44/47/51/86
     对到枚举/协议字段名，并给证据与置信度；
  3. 判定自然金是"事件流水"还是"隐式累加"；
  4. 解释 source5 小额对自然金理论值覆盖率只有 13.3% 的原因。

口径与证据（全部可复现）：
  - global-metadata.dat：v29 头（0xFAB11BAF, 29）。字段默认值不是裸 int，
    而是 **MSB-first base-128 变长编码**；小枚举逐字节读出即为真实值
    （COM_COIN_TYPE 用 MAX/MIXPAY 自证：0..42）。
  - libGameCore.so：只做只读字符串名池扫描（点分名字池），不做执行。
  - .abc：复用 _analysis/tools/abc_tags_full 的记录流/标签解析；
    金币记录 = tag 0x02, flag 0x85, len=5, payload = source:u8 + amount:u32LE。

只读：不修改回放，不注入进程，不读取 param.json，不使用 runtime_dump。

用法：
  python tools/agent_gold_source_enum.py
  python tools/agent_gold_source_enum.py --limit-samples 5 --no-csv
  python tools/agent_gold_source_enum.py --out-csv data/replays/_analysis/datasets/agent_gold_source_enum.csv
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
META = ANALYSIS / "global-metadata.dat"
GAMECORE = ANALYSIS / "libGameCore.so"
ABC_TOOLS = ANALYSIS / "tools"
SAMPLE_DIR = ROOT / "data" / "replays" / "samples" / "abc_batch"
DATASETS = ANALYSIS / "datasets"
OUT_CSV = DATASETS / "agent_gold_source_enum.csv"

FPS = 20.0
NATURAL_RATE = 3.0          # battleDynamicProperty cfg1：3 金币/秒
NATURAL_START_S = 40.0      # cfg1 第一档 40s 起
SMALL_MAX = 80              # source5 小额带 31..73

# ---------------------------------------------------------------- metadata ---


class Metadata:
    """global-metadata.dat v29 只读访问器（类型/字段/枚举默认值）。"""

    def __init__(self, path: Path = META):
        self.data = path.read_bytes()
        magic, version = struct.unpack_from("<Ii", self.data, 0)
        if magic != 0xFAB11BAF or version != 29:
            raise RuntimeError(f"unexpected metadata header: {magic:#x} v{version}")
        self._pair = lambda k: struct.unpack_from("<ii", self.data, 8 + k * 8)
        str_off, str_size = self._pair(2)
        self.typ_off, typ_size = self._pair(19)
        self.fld_off, fld_size = self._pair(11)
        self.fdv_off, fdv_size = self._pair(7)
        self.blob_off, self.blob_size = self._pair(8)
        self.strings = self.data[str_off : str_off + str_size]

        self.types = []
        for i in range(typ_size // 88):
            v = struct.unpack_from("<16i8H2I", self.data, self.typ_off + i * 88)
            self.types.append(
                {
                    "index": i,
                    "name": self.s(v[0]),
                    "ns": self.s(v[1]),
                    "first_field": v[8],
                    "field_count": v[18],
                    "first_method": v[9],
                    "method_count": v[16],
                }
            )
        self.field_count_max = fld_size // 12
        self._defaults = {}
        for e in range(fdv_size // 12):
            fi, ti, di = struct.unpack_from("<3i", self.data, self.fdv_off + e * 12)
            self._defaults.setdefault(fi, (ti, di))

    def s(self, off: int) -> str:
        end = self.strings.find(b"\x00", off)
        if end < 0:
            end = len(self.strings)
        return self.strings[off:end].decode("utf-8", "replace")

    def field_name(self, idx: int) -> str:
        return self.s(struct.unpack_from("<I", self.data, self.fld_off + idx * 12)[0])

    def type_by_index(self, idx: int):
        return self.types[idx] if 0 <= idx < len(self.types) else None

    def find_types(self, name_exact: str | None = None, ns_exact: str | None = None,
                   name_substr: str | None = None):
        out = []
        low = name_substr.lower() if name_substr else None
        for t in self.types:
            if name_exact is not None and t["name"] != name_exact:
                continue
            if ns_exact is not None and t["ns"] != ns_exact:
                continue
            if low is not None and low not in t["name"].lower():
                continue
            out.append(t)
        return out

    def fields(self, type_index: int) -> list[str]:
        t = self.types[type_index]
        return [
            self.field_name(f)
            for f in range(t["first_field"], t["first_field"] + t["field_count"])
        ]

    # -- 枚举默认值：MSB-first base-128；小值逐字节 = 真实值 ---------------
    def _varint(self, data_index: int) -> tuple[int | None, int]:
        value = 0
        n = 0
        while True:
            if data_index + n >= self.blob_size:
                return None, n
            b = self.data[self.blob_off + data_index + n]
            value = (value << 7) | (b & 0x7F)
            n += 1
            if not (b & 0x80):
                return value, n
            if n > 5:
                return None, n

    def enum_members(self, type_index: int) -> list[tuple[str, int | None]]:
        t = self.types[type_index]
        out = []
        for f in range(t["first_field"], t["first_field"] + t["field_count"]):
            name = self.field_name(f)
            if name == "value__":
                continue
            entry = self._defaults.get(f)
            value = None
            if entry is not None:
                value, n = self._varint(entry[1])
                # 4 组以上（>2^21）基本是默认值表错位/无默认值，标记为未解
                if n >= 4 or (value is not None and value > 0xFFFF):
                    value = None
            out.append((name, value))
        return out


# 期望存在但实际不存在的枚举名（用于"完整枚举"的否定证据）
ENUM_NAME_PROBES = [
    "eGoldSource", "GoldSource", "EGoldSource", "GoldSourceType",
    "CoinSource", "CoinSourceType", "ECoinSource", "eCoinSource",
    "GoldSourceEnum", "CoinSourceEnum", "SystemAddCoin", "SystemAddCoinType",
    "IntervalCoin", "IntervalCoinType", "GoldChannel", "CoinChannel",
    "GET_COIN_CHANNEL_TYPE", "eGoldChannelType",
]

# 协议/配置层已知枚举（会打印成员与值）
ENUM_TARGETS = [
    ("CoreDef", "CoinChangeCustomType"),
    ("ResData", "RES_INCOME_ITEM_TYPE"),
    ("ResData", "RES_INCOME_KILL_TYPE"),
    ("ResData", "RES_INCOME_DIVIDE_TYPE"),
    ("ResData", "RES_INCOME_ATTACKER_TYPE"),
    ("ResData", "RES_INCOME_MEMBER_CHOOSE_TYPE"),
    ("ResData", "RES_ASSIST_INCOME_ALLOC_TYPE"),
    ("CoreDef", "enFloatTextType"),
    ("CSProtocol", "COM_COIN_TYPE"),
]

# 金币统计结构体（字段级枚举）
STAT_STRUCTS = [
    ("CSProtocol", "COMDT_GAME_30SEC_INFO"),
    ("CSProtocol", "COMDT_HERO_BATTLE_STATISTIC_INFO"),
    ("CSProtocolWrapper", "COMDT_HERO_STATISTIC_INFO"),
    ("", "stReportPlayerData"),
]

COIN_WORDS = {"coin", "coins", "gold", "income", "eco"}


def _words(name: str) -> list[str]:
    """CamelCase / 下划线切词，避免 cure+count 里的 'eco' 误命中。"""
    import re

    return re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", name)


def is_coin_field(name: str) -> bool:
    return any(w.lower() in COIN_WORDS for w in _words(name))


def scan_metadata(md: Metadata) -> dict:
    """返回枚举/字段证据字典。"""
    report: dict = {"enum_name_probes": {}, "enums": {}, "structs": {}}

    for probe in ENUM_NAME_PROBES:
        hits = md.find_types(name_exact=probe)
        if not hits:  # 允许 "eGoldSource" 之类带前缀的写法
            hits = md.find_types(name_substr=probe)
        report["enum_name_probes"][probe] = [
            f"{t['ns']}.{t['name']}" for t in hits
        ]

    for ns, name in ENUM_TARGETS:
        hits = md.find_types(name_exact=name, ns_exact=ns)
        if not hits:
            continue
        t = hits[0]
        report["enums"][f"{ns}.{name}"] = md.enum_members(t["index"])

    for ns, name in STAT_STRUCTS:
        hits = md.find_types(name_exact=name, ns_exact=ns)
        if not hits:
            continue
        t = hits[0]
        fields = md.fields(t["index"])
        report["structs"][f"{ns or '(global)'}.{name}"] = {
            "field_count": t["field_count"],
            "coin_fields": [
                (i, f) for i, f in enumerate(fields) if is_coin_field(f)
            ],
            "all_fields": fields,
        }
    return report


# ---------------------------------------------------------------- gamecore ---


GAMECORE_PROBES = [
    "KDAStat::GET_COIN_CHANNEL_TYPE",
    "stHeroGoldCoinInBattleChangeParam",
    "stGoldCoinSourceKillParam",
    "ActorGoldCoinChangeEventNode",
    "goldSource",
    "GoldCoinInBattleIncreaseRate",
    "GoldCoinInBattleAutoIncreaseValue",
    "AssistEquipNaturalGold",
    "CoinChangeEvent",
    "mergeCoinTypes",
    "dwSystemAddIntervalCoin",
    "dwCoinIntervalCnt",
    "dwSoliderKillCoin",
    "dwMonsterKillCoin",
    "SystemAddIntervalCoin",
    "eGoldSource",
    "GoldSourceType",
    "CoinSource",
]


def scan_gamecore(path: Path = GAMECORE) -> dict:
    """只读扫描：字符串名池里的金币/枚举符号，返回 {probe: [offsets]}。"""
    data = path.read_bytes()
    out = {}
    for probe in GAMECORE_PROBES:
        needle = probe.encode()
        offs = []
        start = 0
        while len(offs) < 8:
            j = data.find(needle, start)
            if j < 0:
                break
            offs.append(j)
            start = j + 1
        out[probe] = offs
    # 名池里所有 "Namespace::Type" 形式、与金币相关的枚举/类型名
    scoped = set()
    i = 0
    L = len(data)
    while i < L:
        if 32 <= data[i] < 127:
            j = i
            while j < L and 32 <= data[j] < 127:
                j += 1
            if j - i >= 6:
                for tok in data[i:j].replace(b"\x00", b".").split(b"."):
                    if b"::" in tok:
                        try:
                            scoped.add(tok.decode("ascii"))
                        except UnicodeDecodeError:
                            pass
            i = j
        else:
            i += 1
    coin_words = COIN_WORDS | {"economy", "economic", "ecology"}

    def scoped_is_coin(tok: str) -> bool:
        for part in tok.split("::"):
            for w in _words(part):
                if w.lower() in coin_words:
                    return True
        return False

    out["_scoped_coin"] = sorted(t for t in scoped if scoped_is_coin(t))
    return out


# ------------------------------------------------------------------- replay ---


def load_abc_parser():
    sys.path.insert(0, str(ABC_TOOLS))
    try:
        import abc_tags_full as abc  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            f"无法导入 {ABC_TOOLS / 'abc_tags_full.py'}（金币流水解析依赖）"
        ) from exc
    return abc


def read_gold_events(abc, sample: Path) -> tuple[list[dict], float]:
    data = sample.read_bytes()
    recs, _ = abc.find_stream(data)
    events = []
    last_seq = 0
    for r in recs:
        seq = int(r["seq"])
        last_seq = max(last_seq, seq)
        msgs, _ok = abc.parse_payload(r["payload"])
        for m in msgs:
            if m[0] == "h" and m[1] == 0x02 and len(m[4]) == 5:
                payload = m[4]
                events.append(
                    {
                        "seq": seq,
                        "t": seq / FPS,
                        "hero": int(m[2]),
                        "source": int(payload[0]),
                        "amount": int.from_bytes(payload[1:5], "little"),
                    }
                )
    return events, last_seq / FPS


def scan_replays(limit: int | None) -> dict:
    abc = load_abc_parser()
    files = sorted(SAMPLE_DIR.glob("*.abc"))
    per_source = defaultdict(lambda: {"n": 0, "sum": 0, "min": None, "max": None})
    per_sample = []
    per_player_small = defaultdict(lambda: {"n": 0, "sum": 0, "first": None, "last": None})
    small_before_start = 0
    small_after_start = 0
    pre40_events = []
    parseable = 0
    for f in files:
        if limit is not None and parseable >= limit:
            break
        events, duration = read_gold_events(abc, f)
        if not events:
            continue
        parseable += 1
        by_player = defaultdict(list)
        for ev in events:
            src = ev["source"]
            a = ev["amount"]
            if src in (28,):  # 解析伪命中：amount 为百万级
                continue
            st = per_source[src]
            st["n"] += 1
            st["sum"] += a
            st["min"] = a if st["min"] is None else min(st["min"], a)
            st["max"] = a if st["max"] is None else max(st["max"], a)
            by_player[ev["hero"]].append(ev)
            if src == 5 and a <= SMALL_MAX:
                if ev["t"] < NATURAL_START_S:
                    small_before_start += 1
                    pre40_events.append(
                        (f.name[:14], round(ev["t"], 1), ev["hero"], a)
                    )
                else:
                    small_after_start += 1
                k = (f.name[:14], ev["hero"])
                pp = per_player_small[k]
                pp["n"] += 1
                pp["sum"] += a
                pp["first"] = ev["t"] if pp["first"] is None else min(pp["first"], ev["t"])
                pp["last"] = ev["t"] if pp["last"] is None else max(pp["last"], ev["t"])
        per_sample.append(
            {
                "file": f.name,
                "events": len(events),
                "duration_s": duration,
                "sources": dict(Counter(e["source"] for e in events)),
                "natural_theory": NATURAL_RATE * max(0.0, duration - NATURAL_START_S),
                "source5_sum": sum(e["amount"] for e in events if e["source"] == 5),
                "source5_small_sum": sum(
                    e["amount"]
                    for e in events
                    if e["source"] == 5 and e["amount"] <= SMALL_MAX
                ),
                "source5_small_n": sum(
                    1 for e in events if e["source"] == 5 and e["amount"] <= SMALL_MAX
                ),
                "per_player_source5_small": {
                    h: (len([e for e in evs if e["source"] == 5 and e["amount"] <= SMALL_MAX]),
                        sum(e["amount"] for e in evs if e["source"] == 5 and e["amount"] <= SMALL_MAX))
                    for h, evs in by_player.items()
                },
            }
        )
    return {
        "files_total": len(files),
        "parseable": parseable,
        "per_source": {k: dict(v) for k, v in per_source.items()},
        "per_sample": per_sample,
        "per_player_small": {
            f"{k[0]}|{k[1]}": v for k, v in per_player_small.items()
        },
        "small_before_start": small_before_start,
        "small_after_start": small_after_start,
        "pre40_events": pre40_events,
    }


def main_sample_stats(replay: dict) -> dict:
    main = [s for s in replay["per_sample"] if s["file"].startswith("20260925_105224")]
    if not main:
        return {}
    s = main[0]
    n_players = len(s["per_player_source5_small"]) or 10
    per_player = NATURAL_RATE * max(0.0, s["duration_s"] - NATURAL_START_S)
    team = per_player * n_players
    return {
        "file": s["file"],
        "events": s["events"],
        "duration_s": s["duration_s"],
        "n_players": n_players,
        "natural_theory_per_player": per_player,
        "natural_theory_team": team,
        "source5_sum": s["source5_sum"],
        "source5_small_n": s["source5_small_n"],
        "source5_small_sum": s["source5_small_sum"],
        "coverage": (s["source5_small_sum"] / team) if team else None,
        "source5_coverage": (s["source5_sum"] / team) if team else None,
        "per_player": s["per_player_source5_small"],
    }


# ----------------------------------------------------------------- mapping ---

# 观测 source -> (枚举名/通道名, 协议字段, 证据, 置信度, 备注)
SOURCE_MAP = {
    4: (
        "小兵击杀金币（补刀/兵线）",
        "COMDT_HERO_BATTLE_STATISTIC_INFO.dwSoliderKillCoin / stReportPlayerData.iCoinFromKillSolider",
        "金额只有 87-114 / 130-135 / 187-220 三簇，正好是 normalMonster 小兵 80/90/100/130/190/200/210 底额 + 金币加成；"
        "每局约 110-320 条、10 人全覆盖，人均 ~16-24 条，与补刀数同量级；"
        "主样本 162 条 / 21,184 金 = 事件金最大项（65%）",
        "high",
        "source4 是唯一覆盖全 10 人且条数与补刀同量级的来源，身份最稳",
    ),
    5: (
        "系统金/辅助装类通道（混合：自然金统计口径 + 辅助装/团队金）",
        "COMDT_GAME_30SEC_INFO.dwSystemAddCoin / dwSystemAddIntervalCoin / dwAidEquipCoin / "
        "dwEquipAssistEnCiCoin / dwEquipAssistYouJiCoin",
        "金额三档 31-73 / 131-146 / 231-254（底额 30 / 130,140 / 230,240,250 + 1-4 尾数）；"
        "10 人计数 0-18 不等、人均合计 0-656 不等（自然金应 10 人相同 1,844）；"
        "有 t<40s 的事件（3.5s/4.8s，自然金 rate=0；见 5.82 cfg1 40s 起）；"
        "与队友 source4 小兵金无固定比例（比值 0.1-0.7 散开），不是单纯按比例分成",
        "medium",
        "一字节通道里 source5 是唯一跨 30/130/230 三档的，属'系统加金'聚合通道；"
        "其小额段不是自然金（见 natural_gold_path）",
    ),
    6: (
        "野怪击杀金币",
        "COMDT_HERO_BATTLE_STATISTIC_INFO.dwMonsterKillCoin / stReportPlayerData.iCoinFromKillMonster",
        "金额 165 / 175-192 / 201-211，对应 normalMonster 160/174/190/200 底额 + 加成；"
        "每局只有 2-3 个玩家有记录（打野/反野），单局 5-8 条，全样本 110 条",
        "high",
        "玩家集中度 + 金额簇双重命中",
    ),
    43: (
        "英雄击杀 / 助攻",
        "COMDT_HERO_BATTLE_STATISTIC_INFO.dwHeroKillCoin / stReportPlayerData.iCoinFromKillHero",
        "全样本金额只有 102 / 202 / 203（100=助攻底额、200=击杀底额 + 2-3 尾数）；"
        "主样本 10 条 = 6 杀 + 4 助攻，与 6:4 比分一致；252 条/全样本、每局 2-57 条",
        "medium-high",
        "KDA 条数与底额都吻合；102=助攻、202/203=击杀 仍是候选但已高度一致",
    ),
    44: (
        "河道之灵/小型中立单位（45 底额）",
        "COMDT_GAME_30SEC_INFO.dwDuikanRiverCatCoin/dwMidRiverCatCoin/dwFayuRiverCatCoin",
        "全样本 10 条，金额恒为 47 = 45 + 2（底额 45 的固定奖励，与河蟹 45 金一致）",
        "medium-low",
        "条数极少，无法用时间/位置交叉验证；只有金额底额一条证据",
    ),
    47: (
        "175 底额目标/特殊野怪奖励",
        "COMDT_GAME_30SEC_INFO.dwBountyCoin / dwBigDragonKillCoin 候选",
        "全样本 27 条，金额恒为 179 = 175 + 4；集中在少数玩家",
        "low",
        "底额 175 与 5.85 的'暴君/主宰候选'一致，但无双证据",
    ),
    51: (
        "150/250 底额目标金（推塔/主宰）",
        "COMDT_HERO_BATTLE_STATISTIC_INFO.dwTowerKillCoin / dwDestroyOrganCoin / dwBaronCoin 候选",
        "全样本 13 条，金额只有 155(150+5) 与 254(250+4)；"
        "主样本 2 条 254 在 359.8s / 440.8s（双枪踏浪行 / 李不信有归途）",
        "low",
        "250 底额与推塔/主宰同族，但当前回放无建筑死亡逐条事件可对",
    ),
    86: (
        "小额系统/赏金（13-15）",
        "无对应协议字段（低于任何金币底额）",
        "全样本仅 3 条（13/15），无重复模式",
        "low",
        "可能是解析伪命中或极小额的补偿金",
    ),
    "natural": (
        "自然金（battleDynamicProperty cfg1，3/s、40s 起、1000ms）",
        "GameCore 属性 0x4000 = GoldCoinInBattleIncreaseRate → "
        "COMDT_GAME_30SEC_INFO.dwSystemAddIntervalCoin / dwSystemAddCoin",
        "回放容器里没有 30 秒统计块（5.14/5.56 已验证签名 0 命中）；"
        "0x02 len=5 是事件金通知；自然金由 GameCore 按帧隐式累加，不产生逐笔事件",
        "high",
        "自然金不在 0x02 流水里，需按 3/s ×(duration-40s) 隐式加",
    ),
}


def build_rows(md_report: dict, gc: dict, replay: dict) -> list[dict]:
    rows = []

    # ---- 1) 回放 source 映射 ----
    per_source = replay["per_source"]
    for src in (4, 5, 6, 43, 44, 47, 51, 86):
        name, field, evidence, conf, note = SOURCE_MAP[src]
        st = per_source.get(src, {"n": 0, "sum": 0, "min": "", "max": ""})
        rows.append(
            {
                "kind": "replay_source",
                "source": src,
                "enum_name": name,
                "protocol_field": field,
                "evidence": evidence,
                "confidence": conf,
                "observed_n": st["n"],
                "observed_min": st["min"],
                "observed_max": st["max"],
                "observed_sum": st["sum"],
                "note": note,
            }
        )

    # ---- 2) 自然金路径 ----
    name, field, evidence, conf, note = SOURCE_MAP["natural"]
    main = main_sample_stats(replay)
    rows.append(
        {
            "kind": "natural_gold_path",
            "source": "",
            "enum_name": name,
            "protocol_field": field,
            "evidence": evidence,
            "confidence": conf,
            "observed_n": main.get("source5_small_n", ""),
            "observed_min": "",
            "observed_max": "",
            "observed_sum": main.get("source5_small_sum", ""),
            "note": (
                f"主样本自然金理论 {main.get('natural_theory_team', 0):.0f}"
                f"（{main.get('n_players', 10)} 人 × {main.get('natural_theory_per_player', 0):.0f}）；"
                f"source5 小额 {main.get('source5_small_n', 0)} 条/"
                f"{main.get('source5_small_sum', 0)} = "
                f"{100 * (main.get('coverage') or 0):.1f}% → 该比值无经济含义"
                if main
                else note
            ),
        }
    )

    # ---- 3) 枚举目录（存在/不存在） ----
    for probe, hits in md_report["enum_name_probes"].items():
        rows.append(
            {
                "kind": "enum_name_probe",
                "source": "",
                "enum_name": probe,
                "protocol_field": "",
                "evidence": (
                    "global-metadata.dat 类型表命中: " + ", ".join(hits)
                    if hits
                    else "global-metadata.dat 类型表 0 命中（该枚举名不存在）"
                ),
                "confidence": "high",
                "observed_n": len(hits),
                "observed_min": "",
                "observed_max": "",
                "observed_sum": "",
                "note": "C# 侧没有金币来源枚举" if not hits else "",
            }
        )

    for enum_name, members in md_report["enums"].items():
        members_text = "; ".join(
            f"{n}={v}" for n, v in members if v is not None
        )
        rows.append(
            {
                "kind": "enum_members",
                "source": "",
                "enum_name": enum_name,
                "protocol_field": "",
                "evidence": f"global-metadata.dat 默认值表：{members_text}",
                "confidence": "high",
                "observed_n": len(members),
                "observed_min": "",
                "observed_max": "",
                "observed_sum": "",
                "note": "与局内金币来源相关的协议/配置枚举" ,
            }
        )

    # 30 秒 / 358 字段统计结构
    for struct_name, info in md_report["structs"].items():
        fields_text = "; ".join(f"[{i}]{n}" for i, n in info["coin_fields"])
        rows.append(
            {
                "kind": "protocol_struct",
                "source": "",
                "enum_name": struct_name,
                "protocol_field": f"{len(info['coin_fields'])}/{info['field_count']} 字段为金币类",
                "evidence": fields_text,
                "confidence": "high",
                "observed_n": len(info["coin_fields"]),
                "observed_min": "",
                "observed_max": "",
                "observed_sum": "",
                "note": "这是最权威的金币来源字段枚举（协议层），但回放容器不落盘",
            }
        )

    # ---- 4) GameCore 符号 ----
    for probe, offs in gc.items():
        if probe.startswith("_"):
            continue
        rows.append(
            {
                "kind": "gamecore_symbol",
                "source": "",
                "enum_name": probe,
                "protocol_field": "",
                "evidence": (
                    "libGameCore.so 名池命中 @ " + ", ".join(hex(o) for o in offs)
                    if offs
                    else "libGameCore.so 名池 0 命中"
                ),
                "confidence": "high",
                "observed_n": len(offs),
                "observed_min": "",
                "observed_max": "",
                "observed_sum": "",
                "note": (
                    "原生金币通道枚举类型名（成员名/值不在二进制字符串池，无法离线枚举）"
                    if probe == "KDAStat::GET_COIN_CHANNEL_TYPE"
                    else ""
                ),
            }
        )
    scoped = gc.get("_scoped_coin", [])
    rows.append(
        {
            "kind": "gamecore_symbol",
            "source": "",
            "enum_name": "Namespace::Type 形式的金币相关原生符号",
            "protocol_field": "",
            "evidence": ", ".join(scoped),
            "confidence": "high",
            "observed_n": len(scoped),
            "observed_min": "",
            "observed_max": "",
            "observed_sum": "",
            "note": "只有类型名，没有 enum 成员名 → 原生 source 枚举无法离线定名",
        }
    )
    return rows


# ------------------------------------------------------------------- report ---


def print_report(md_report: dict, gc: dict, replay: dict, md: Metadata) -> None:
    print("=" * 78)
    print("1. 枚举名探针（global-metadata.dat）")
    for probe, hits in md_report["enum_name_probes"].items():
        mark = "命中" if hits else "0"
        print(f"  {probe:28s} {mark:4s} {', '.join(hits)}")

    print("\n2. 金币相关枚举（值 = 默认值表 MSB-first base-128）")
    for enum_name, members in md_report["enums"].items():
        vals = ", ".join(f"{n}={v}" for n, v in members if v is not None)
        print(f"  {enum_name}  n={len(members)}")
        print(f"    {vals}")

    print("\n3. 协议统计结构体的金币字段")
    for struct_name, info in md_report["structs"].items():
        print(f"  {struct_name}: {len(info['coin_fields'])}/{info['field_count']}")
        for i, f in info["coin_fields"]:
            print(f"    [{i:3d}] {f}")

    print("\n4. libGameCore.so 金币/枚举符号")
    for probe in ("KDAStat::GET_COIN_CHANNEL_TYPE", "stHeroGoldCoinInBattleChangeParam",
                  "stGoldCoinSourceKillParam", "goldSource", "GoldCoinInBattleIncreaseRate",
                  "AssistEquipNaturalGold", "mergeCoinTypes"):
        offs = gc.get(probe, [])
        print(f"  {probe:34s} {'@ ' + ', '.join(hex(o) for o in offs) if offs else '0 命中'}")
    print(f"  原生 Namespace::Type 金币符号 {len(gc.get('_scoped_coin', []))} 个")
    for t in gc.get("_scoped_coin", []):
        print(f"    {t}")

    print("\n5. 回放 0x02/0x85 流水（%d 个可解析样本）" % replay["parseable"])
    print(f"  {'source':>6} {'n':>6} {'min':>5} {'max':>5} {'sum':>9}")
    for src in sorted(replay["per_source"]):
        st = replay["per_source"][src]
        print(f"  {src:>6} {st['n']:>6} {str(st['min']):>5} {str(st['max']):>5} {st['sum']:>9}")

    main = main_sample_stats(replay)
    if main:
        print(f"\n6. 主样本 {main['file'][:14]}")
        print(f"  events={main['events']} duration={main['duration_s']:.1f}s")
        print(f"  自然金理论 {main['natural_theory_team']:.0f} "
              f"= {main['n_players']} 人 × {main['natural_theory_per_player']:.1f} "
              f"(3/s × {main['duration_s'] - NATURAL_START_S:.1f}s)")
        print(f"  source5 小额 {main['source5_small_n']} 条/{main['source5_small_sum']} "
              f"= {100 * main['coverage']:.1f}% of theory")
        print(f"  source5 全部 {main['source5_sum']} = {100 * main['source5_coverage']:.1f}%")
        print(f"  per-player source5 小额 (count/sum) 与自然金应得的 "
              f"{main['natural_theory_per_player']:.0f}:")
        for h, (n, s) in sorted(main["per_player"].items(), key=lambda kv: -kv[1][1]):
            print(f"    hero {h:5d}: {n:2d} 条 / {s:4d}")
        print(f"  自然金起算前(<40s)的 source5 小额事件：{replay['small_before_start']} 条 "
              f"(>=40s: {replay['small_after_start']} 条)")
        if replay["pre40_events"]:
            print("    自然金 rate=0 区间内的 source5 小额样本：")
            for fn, t, hero, amt in replay["pre40_events"][:12]:
                print(f"      {fn} t={t:6.1f}s hero={hero:5d} amount={amt}")

        # 自然金证伪：10 人应完全相同，实际离散度
        sums = [s for _n, s in main["per_player"].values()]
        if sums:
            mean = sum(sums) / len(sums)
            var = sum((x - mean) ** 2 for x in sums) / len(sums)
            cv = (var ** 0.5 / mean) if mean else None
            print(f"  10 人 source5 小额合计：min={min(sums)} max={max(sums)} "
                  f"mean={mean:.1f} CV={cv:.2f}（自然金要求 10 人相同）")
            print(f"  自然金覆盖率若按 team 理论：event 流水 {main['source5_sum']}/"
                  f"{main['natural_theory_team']:.0f} = "
                  f"{100 * main['source5_coverage']:.1f}%")

    print("\n7. source 映射")
    for src in (4, 5, 6, 43, 44, 47, 51, 86):
        name, _field, _ev, conf, _note = SOURCE_MAP[src]
        print(f"  {src:3d} -> {name}  [{conf}]")
    print("\n8. 结论：自然金不在 0x02 流水里，按 3/s ×(duration-40s) 隐式加。")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--metadata", type=Path, default=META)
    ap.add_argument("--gamecore", type=Path, default=GAMECORE)
    ap.add_argument("--out-csv", type=Path, default=OUT_CSV)
    ap.add_argument("--limit-samples", type=int, default=None,
                    help="只解析前 N 个可解析样本（调试用）")
    ap.add_argument("--no-csv", action="store_true")
    args = ap.parse_args()

    md = Metadata(args.metadata)
    md_report = scan_metadata(md)
    gc = scan_gamecore(args.gamecore)
    replay = scan_replays(args.limit_samples)

    print_report(md_report, gc, replay, md)

    if not args.no_csv:
        rows = build_rows(md_report, gc, replay)
        args.out_csv.parent.mkdir(parents=True, exist_ok=True)
        with args.out_csv.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "kind", "source", "enum_name", "protocol_field", "evidence",
                    "confidence", "observed_n", "observed_min", "observed_max",
                    "observed_sum", "note",
                ],
            )
            w.writeheader()
            for r in rows:
                w.writerow(r)
        print(f"\n[out] {args.out_csv} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
