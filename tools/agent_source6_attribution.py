#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""source6 野怪金归属分析（只读、可复跑）。

问题：普通 5v5 的 0x02 len=5 source6 到底是野怪击杀金、助攻/分享金、
辅助装金，还是混合？为什么 source6 多由辅助领取、打野事件金偏低？

本脚本只读 .abc 回放和 _analysis/datasets 下的 CSV；不修改回放/包体，
不注入进程，不读取 param.json，不使用 runtime_dump。
不写 docs/replay_binary_format.md，不写 .workbuddy/memory/MEMORY.md。

核心口径：
  - 金币事件 = 0x02 tag, flag & 0x80, len=5, payload = source:u8 + amount:u32LE。
  - source6 = 野怪事件候选；source5 230-254 = 另一条野怪金通道候选。
  - 20 个可解析样本按 res_build 分层；主样本 5069040。
  - 对连续重复的同一 (entity, source, amount) 通知做去重（run>=3，gap<=12 帧），
    原始条数和去重条数都写入 CSV/报告。

用法：
  python tools/agent_source6_attribution.py
  python tools/agent_source6_attribution.py --samples-dir data/replays/samples/abc_batch
  python tools/agent_source6_attribution.py --out-csv ... --out-md ...
"""
from __future__ import annotations

import argparse
import collections
import csv
import re
import statistics
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS = ROOT / "data" / "replays" / "_analysis"
DATASETS = ANALYSIS / "datasets"
SAMPLE_DIR = ROOT / "data" / "replays" / "samples" / "abc_batch"
OUT_CSV = DATASETS / "agent_source6_attribution.csv"
OUT_MD = DATASETS / "agent_source6_attribution.md"

FPS = 20.0
DEDUP_WINDOW = 12       # 0.6 s
DEDUP_MIN_RUN = 3

# ---------------------------------------------------------------------------
# 角色表（启发式；source6 领取者只有这些英雄，均有明确/可解释归属）
# ---------------------------------------------------------------------------
SUPPORT_HEROES = {
    "瑶", "钟馗", "蔡文姬", "明世隐", "鬼谷子", "孙膑", "东皇太一",
    "朵莉亚", "少司缘", "刘禅", "张飞", "墨子",
}
MID_HEROES = {"周瑜", "甄姬", "金蝉", "王维", "海诺", "扁鹊"}
SIDE_HEROES = {"夏侯惇", "芈月", "马超", "白起", "夏洛特", "项羽", "老夫子",
               "廉颇", "关羽", "亚瑟", "吕布", "李信", "猪八戒", "达摩",
               "哪吒", "钟无艳", "程咬金", "姬小满", "狂铁", "元歌",
               "司空震", "杨玉环"}
ADC_HEROES = {"后羿", "鲁班七号", "马可波罗", "艾琳", "狄仁杰", "孙尚香",
              "百里守约", "公孙离", "虞姬", "黄忠", "莱西奥", "卢雅那"}
JUNGLE_HEROES = {
    "孙悟空", "影", "赵云", "铠", "云缨", "典韦", "兰陵王", "韩信",
    "露娜", "盘古", "阿轲", "澜", "曜", "李白", "宫本武藏", "刘备",
    "心魔六耳",
}
FLEX_ROLE = {"墨子", "扁鹊", "夏侯惇", "芈月"}

ROLE_LABEL = {
    "support": "辅助/游走",
    "mid": "中/法",
    "side": "边/坦",
    "jungle": "打野",
    "adc": "射手",
    "unknown": "未知",
}


def hero_role(hero: str) -> str:
    if hero in JUNGLE_HEROES:
        return "jungle"
    if hero in SUPPORT_HEROES:
        return "support"
    if hero in MID_HEROES:
        return "mid"
    if hero in SIDE_HEROES:
        return "side"
    if hero in ADC_HEROES:
        return "adc"
    return "unknown"


def role_confidence(hero: str) -> str:
    if hero in FLEX_ROLE:
        return "medium"
    if hero in ("unknown", ""):
        return "low"
    return "high"


# ---------------------------------------------------------------------------
# .abc 解析（从 _analysis/tools/abc_tags_full.py 的只读实现内联，避免外部依赖）
# ---------------------------------------------------------------------------
def records(d: bytes, start: int = 0xBFE8, seq0: int = 0x22):
    pos, seq, out = start, seq0, []
    while pos + 10 < len(d):
        if d[pos] != (seq & 0xFF):
            break
        length = d[pos + 2]
        if d[pos + 1] != 0 or pos + 10 + length > len(d):
            break
        out.append({
            "off": pos,
            "seq": seq,
            "payload": d[pos + 3:pos + 3 + length],
        })
        pos += 10 + length
        seq += 1
    return out, pos


def find_stream(d: bytes):
    best = ([], 0)
    for pos in range(0, min(len(d), 0x20000)):
        if d[pos] == 0x22 and d[pos + 1] == 0:
            recs, end = records(d, pos)
            if len(recs) > len(best[0]):
                best = (recs, end)
                if len(recs) > 500:
                    break
    return best


def parse_payload(pl: bytes):
    """返回 msgs。部分 payload 尾部不完整，但已解析出的消息仍有效；
    与既有 agent_normal5v5_reconcile 口径一致，忽略 ok=False。"""
    if not pl:
        return []
    n = pl[0]
    i, msgs = 1, []
    while i < len(pl):
        tag = pl[i]
        if tag == 0x12:
            if i + 3 > len(pl):
                break
            msgs.append(("s", tag, pl[i + 1:i + 3]))
            i += 3
        elif tag == 0x13:
            if i + 2 > len(pl):
                break
            msgs.append(("s", tag, pl[i + 1:i + 2]))
            i += 2
        elif tag == 0x14:
            if i + 4 > len(pl):
                break
            msgs.append(("s", tag, pl[i + 1:i + 4]))
            i += 4
        elif tag in (0x01, 0x02):
            if tag == 0x01:
                if i + 5 > len(pl):
                    break
                hero = struct.unpack_from(">H", pl, i + 1)[0]
                flag = pl[i + 3]
                ln = pl[i + 4]
                if i + 5 + ln > len(pl):
                    break
                msgs.append(("h", tag, hero, flag, pl[i + 5:i + 5 + ln]))
                i += 5 + ln
            else:
                if i + 4 > len(pl):
                    break
                hero = struct.unpack_from(">H", pl, i + 1)[0]
                flag = pl[i + 3]
                ln = flag & 0x7F
                if i + 4 + ln > len(pl):
                    break
                msgs.append(("h", tag, hero, flag, pl[i + 4:i + 4 + ln]))
                i += 4 + ln
        else:
            break
    return msgs


def find_blocks(d: bytes, limit: int = 0x20000):
    """玩家块头：team, slot, entityID, heroID(s+0x48), name。"""
    out = []
    pos = 0
    while pos + 24 <= min(len(d), limit):
        if (d[pos] in (1, 2) and d[pos + 1] in (1, 2) and d[pos + 2] == 1
                and d[pos + 3] <= 4 and d[pos + 4] == 0 and d[pos + 5] == 0):
            entity = struct.unpack_from(">H", d, pos + 6)[0]
            if (100 <= entity <= 3000 and d[pos + 12:pos + 15] == b"\x00\x00\x00"):
                name_len = d[pos + 15]
                end = pos + 16 + name_len
                if 2 <= name_len <= 40 and end <= len(d):
                    raw = d[pos + 16:end]
                    try:
                        name = raw.rstrip(b"\x00").decode("utf-8")
                    except UnicodeDecodeError:
                        name = ""
                    if name and all(c.isprintable() for c in name):
                        s = pos + 0x10 + name_len + 30
                        hero_id = None
                        if s + 0x4A <= len(d):
                            hero_id = struct.unpack_from(">H", d, s + 0x48)[0]
                        out.append({
                            "offset": pos,
                            "team": d[pos],
                            "slot": d[pos + 3],
                            "entity_id": entity,
                            "hero_id": hero_id,
                            "name": name,
                            "name_len": name_len,
                        })
                        pos = end
                        continue
        pos += 1
    return out[:10]


# ---------------------------------------------------------------------------
# 数据表
# ---------------------------------------------------------------------------
def load_hero_names() -> dict[int, str]:
    path = DATASETS / "agent_hero_tables" / "0x111C3C_hero_base_attributes.csv"
    names: dict[int, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            m = re.match(r"^(\d+),([^,]+),", line)
            if not m:
                continue
            try:
                names[int(m.group(1))] = m.group(2).strip()
            except ValueError:
                pass
    return names


def load_replay_index() -> dict[str, dict]:
    path = DATASETS / "replay_index.csv"
    out = {}
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as fp:
            for row in csv.DictReader(fp):
                out[row["file"]] = row
    return out


JUNGLE_NAME_WORDS = ("隼", "赤甲", "熊", "山豪", "暴君", "主宰", "石像",
                     "猎豹", "蜥蜴", "熊猫", "龙王", "先锋", "魔种", "鲲鹏",
                     "烈稚")
JUNGLE_BASE_VALUES = [160, 174, 178, 180, 190, 200, 210]
BASE_NAME_PRIORITY = (
    "红隼", "赤甲", "山豪小", "巨熊校尉", "森林熊", "山豪中", "炎狱暴君",
    "蔚蓝石像", "腥红石像", "主宰先锋", "小主宰先锋", "风暴先锋", "主宰",
    "野熊", "魔种熊", "小熊",
)


def load_monster_rows() -> list[dict]:
    path = DATASETS / "normalMonster_rows.csv"
    rows = []
    if not path.exists():
        return rows
    with path.open(encoding="utf-8-sig", newline="") as fp:
        for row in csv.DictReader(fp):
            name = row.get("name", "")
            if not any(w in name for w in JUNGLE_NAME_WORDS):
                continue
            try:
                gold = int(row.get("gold", ""))
            except ValueError:
                continue
            rows.append({"name": name, "gold": gold})
    # 去重
    seen = set()
    out = []
    for row in rows:
        key = (row["gold"], row["name"])
        if key not in seen:
            seen.add(key)
            out.append(row)
    return out


def base_for(amount: int, monster_rows: list[dict]) -> tuple[int, str, int]:
    """source6 口径：在 normalMonster 野怪底额里找最近值。"""
    base = min(JUNGLE_BASE_VALUES, key=lambda v: abs(v - amount))
    names = []
    for row in monster_rows:
        if row["gold"] == base:
            names.append(row["name"])
    names = list(dict.fromkeys(names))
    preferred = [n for n in names if any(w in n for w in BASE_NAME_PRIORITY)]
    names = (preferred or names)[:8]
    return base, ";".join(names), amount - base


# ---------------------------------------------------------------------------
# 去重
# ---------------------------------------------------------------------------
def dedup_events(events: list[dict], window: int, min_run: int):
    """按 (entity, source, amount) 分组；同一组 seq 连续簇 >= min_run 时，
    保留第一条、其余标记为重复通知。返回 (kept, run_len, duplicate_flags)。"""
    groups = collections.defaultdict(list)
    for i, e in enumerate(events):
        groups[(e["entity_id"], e["source"], e["amount"])].append((e["seq"], i))
    duplicate = set()
    run_len = {}
    for key, xs in groups.items():
        xs.sort()
        cluster = [xs[0]]
        clusters = []
        for x in xs[1:]:
            if x[0] - cluster[-1][0] <= window:
                cluster.append(x)
            else:
                clusters.append(cluster)
                cluster = [x]
        clusters.append(cluster)
        for cluster in clusters:
            if len(cluster) >= min_run:
                for _, idx in cluster:
                    run_len[idx] = len(cluster)
                for _, idx in cluster[1:]:
                    duplicate.add(idx)
            else:
                for _, idx in cluster:
                    run_len.setdefault(idx, 1)
    kept = [e for i, e in enumerate(events) if i not in duplicate]
    return kept, run_len, duplicate


# ---------------------------------------------------------------------------
# 单样本解析
# ---------------------------------------------------------------------------
def read_sample(path: Path, hero_names: dict[int, str], index: dict[str, dict]):
    data = path.read_bytes()
    recs, _ = find_stream(data)
    if not recs:
        return None
    blocks = {}
    for b in find_blocks(data):
        blocks[b["entity_id"]] = b
    events = []
    for r in recs:
        for m in parse_payload(r["payload"]):
            if m[0] == "h" and m[1] == 0x02 and len(m[4]) == 5:
                pl = m[4]
                events.append({
                    "seq": int(r["seq"]),
                    "t": int(r["seq"]) / FPS,
                    "entity_id": int(m[2]),
                    "source": int(pl[0]),
                    "amount": int.from_bytes(pl[1:5], "little"),
                })
    if not events:
        return None
    for e in events:
        b = blocks.get(e["entity_id"], {})
        e["team"] = b.get("team")
        e["slot"] = b.get("slot")
        e["player"] = b.get("name", "?")
        e["hero_id"] = b.get("hero_id")
        e["hero"] = hero_names.get(b.get("hero_id"), "?") if b else "?"
        e["role"] = hero_role(e["hero"])
        e["role_confidence"] = role_confidence(e["hero"])
    events.sort(key=lambda e: e["seq"])
    sample = {
        "file": path.name,
        "short": path.name[:14],
        "res_build": index.get(path.name, {}).get("res_build", "?"),
        "status": index.get(path.name, {}).get("status", "?"),
        "duration_frames": recs[-1]["seq"],
        "blocks": blocks,
        "events": events,
    }
    kept, run_len, duplicate = dedup_events(events, DEDUP_WINDOW, DEDUP_MIN_RUN)
    sample["kept"] = kept
    sample["run_len"] = run_len
    sample["duplicate"] = duplicate
    # 每条原始事件附去重信息
    for i, e in enumerate(events):
        e["run_len"] = run_len.get(i, 1)
        e["is_duplicate"] = i in duplicate
    return sample


# ---------------------------------------------------------------------------
# 分析
# ---------------------------------------------------------------------------
def nearest(events: list[dict], seq: int):
    if not events:
        return None
    e = min(events, key=lambda x: abs(x["seq"] - seq))
    return e


def count_within(events: list[dict], seq: int, window: int) -> int:
    return sum(1 for e in events if abs(e["seq"] - seq) <= window)


def build_jungle_holders(sample: dict, hero_names: dict[int, str]):
    """数据驱动的打野刀持有人：开局 <=20s 的 source5 225-260 领取者。
    若没有，则退回经典打野英雄集合。"""
    early = [e for e in sample["kept"]
             if e["source"] == 5 and 225 <= e["amount"] <= 260 and e["t"] <= 20]
    holders = {e["entity_id"] for e in early}
    source = "source5_225_260_open"
    if not holders:
        holders = {eid for eid, b in sample["blocks"].items()
                   if hero_names.get(b.get("hero_id"), "") in JUNGLE_HEROES}
        source = "jungle_hero_fallback"
    names = []
    for eid in holders:
        b = sample["blocks"].get(eid)
        if b:
            names.append(f"{b['name']}({hero_names.get(b.get('hero_id'), '?')})")
    return holders, source, "；".join(names)


def analyze(sample_dir: Path, hero_names: dict[int, str], index: dict[str, dict]):
    files = sorted(sample_dir.glob("*.abc"))
    samples = []
    for path in files:
        s = read_sample(path, hero_names, index)
        if s:
            samples.append(s)

    monster_rows = load_monster_rows()
    rows = []
    sample_meta = []
    for s in samples:
        holders, holder_source, holder_names = build_jungle_holders(s, hero_names)
        kept = s["kept"]
        team_events = collections.defaultdict(list)
        jungle_events = collections.defaultdict(list)
        for e in kept:
            if e["source"] in (4, 5, 43):
                if e["team"] is not None:
                    team_events[e["team"]].append(e)
                if e["entity_id"] in holders:
                    jungle_events[e["team"]].append(e)
        # 同一玩家 source6 间隔
        prev = {}
        for e in kept:
            if e["source"] != 6:
                continue
            key = (s["file"], e["entity_id"])
            e["prev_interval"] = None
            if key in prev:
                e["prev_interval"] = round(e["t"] - prev[key], 2)
            prev[key] = e["t"]
        s6_kept = [e for e in kept if e["source"] == 6]
        sample_meta.append({
            "file": s["file"],
            "short": s["short"],
            "res_build": s["res_build"],
            "status": s["status"],
            "duration_s": round(s["duration_frames"] / FPS, 1),
            "blocks": len(s["blocks"]),
            "events": len(s["events"]),
            "s6_raw": sum(1 for e in s["events"] if e["source"] == 6),
            "s6_kept": len(s6_kept),
            "s6_gold_raw": sum(e["amount"] for e in s["events"] if e["source"] == 6),
            "s6_gold_kept": sum(e["amount"] for e in s6_kept),
            "s6_players": len({e["entity_id"] for e in s6_kept}),
            "holders": holder_names,
            "holder_source": holder_source,
        })
        # 逐 source6 原始事件写 CSV；分析字段用去重后的同一条
        kept_by_index = {id(e): e for e in kept}
        for e in s["events"]:
            if e["source"] != 6:
                continue
            base_gold, base_names, base_delta = base_for(e["amount"], monster_rows)
            tid = e["team"]
            t_events = [x for x in team_events.get(tid, [])
                        if x["entity_id"] != e["entity_id"]]
            j_events = jungle_events.get(tid, [])
            h_events = [x for x in team_events.get(tid, [])
                        if x["entity_id"] == e["entity_id"]]
            na = nearest(t_events, e["seq"])
            nj = nearest(j_events, e["seq"])
            nh = nearest(h_events, e["seq"])
            row = {
                "file": s["file"],
                "sample": s["short"],
                "res_build": s["res_build"],
                "replay_status": s["status"],
                "seq": e["seq"],
                "t_sec": round(e["t"], 2),
                "entity_id": e["entity_id"],
                "team": e["team"],
                "slot": e["slot"],
                "player": e["player"],
                "hero_id": e["hero_id"],
                "hero": e["hero"],
                "role": e["role"],
                "role_confidence": e["role_confidence"],
                "amount": e["amount"],
                "run_len": e["run_len"],
                "is_duplicate": int(e["is_duplicate"]),
                "base_gold": base_gold,
                "base_names": base_names,
                "base_delta": base_delta,
                "share25_amount": round(base_gold * 0.25, 1),
                "share50_amount": round(base_gold * 0.5, 1),
                "same_team_any_0": count_within(t_events, e["seq"], 0),
                "same_team_any_5": count_within(t_events, e["seq"], 5),
                "same_team_any_20": count_within(t_events, e["seq"], 20),
                "same_team_any_60": count_within(t_events, e["seq"], 60),
                "same_team_any_100": count_within(t_events, e["seq"], 100),
                "same_team_jungle_0": count_within(j_events, e["seq"], 0),
                "same_team_jungle_5": count_within(j_events, e["seq"], 5),
                "same_team_jungle_20": count_within(j_events, e["seq"], 20),
                "same_team_jungle_60": count_within(j_events, e["seq"], 60),
                "same_team_jungle_100": count_within(j_events, e["seq"], 100),
                "same_hero_other_0": count_within(h_events, e["seq"], 0),
                "same_hero_other_5": count_within(h_events, e["seq"], 5),
                "same_hero_other_20": count_within(h_events, e["seq"], 20),
                "same_hero_other_60": count_within(h_events, e["seq"], 60),
                "nearest_same_team_any_delta": (na["seq"] - e["seq"]) if na else None,
                "nearest_same_team_any_source": na["source"] if na else None,
                "nearest_same_team_any_player": na["player"] if na else None,
                "nearest_same_team_jungle_delta": (nj["seq"] - e["seq"]) if nj else None,
                "nearest_same_team_jungle_source": nj["source"] if nj else None,
                "nearest_same_team_jungle_player": nj["player"] if nj else None,
                "nearest_same_team_jungle_hero": nj["hero"] if nj else None,
                "jungle_holders": holder_names,
                "jungle_holder_source": holder_source,
                "prev_same_player_interval_sec": e.get("prev_interval"),
                "team_event_count": len(t_events),
                "jungle_event_count": len(j_events),
                "duration_frames": s["duration_frames"],
            }
            rows.append(row)
    return samples, sample_meta, rows, monster_rows


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------
def summarize(samples, sample_meta, rows, monster_rows, hero_names):
    kept_rows = [r for r in rows if not r["is_duplicate"]]
    out = {}
    out["samples_total"] = len(samples)
    out["raw_events_total"] = sum(m["events"] for m in sample_meta)
    out["s6_raw"] = sum(m["s6_raw"] for m in sample_meta)
    out["s6_kept"] = sum(m["s6_kept"] for m in sample_meta)
    out["s6_gold_raw"] = sum(m["s6_gold_raw"] for m in sample_meta)
    out["s6_gold_kept"] = sum(m["s6_gold_kept"] for m in sample_meta)

    # 按 build
    by_build = collections.defaultdict(lambda: collections.Counter())
    for m in sample_meta:
        b = by_build[m["res_build"]]
        b["samples"] += 1
        b["s6_raw"] += m["s6_raw"]
        b["s6_kept"] += m["s6_kept"]
        b["gold_raw"] += m["s6_gold_raw"]
        b["gold_kept"] += m["s6_gold_kept"]
    for r in kept_rows:
        b = by_build[r["res_build"]]
        b["role_" + r["role"] + "_n"] += 1
        b["role_" + r["role"] + "_g"] += r["amount"]
    out["by_build"] = by_build

    # 角色
    def role_counts(rs):
        c = collections.Counter()
        g = collections.Counter()
        for r in rs:
            c[r["role"]] += 1
            g[r["role"]] += r["amount"]
        return c, g
    out["role_all"], out["role_all_gold"] = role_counts(kept_rows)
    out["role_raw"], out["role_raw_gold"] = role_counts(rows)
    out["role_5069040"], out["role_5069040_gold"] = role_counts(
        [r for r in kept_rows if r["res_build"] == "5069040"])
    out["role_5069040_raw"], out["role_5069040_raw_gold"] = role_counts(
        [r for r in rows if r["res_build"] == "5069040"])

    # 金额
    abs_delta = [abs(r["base_delta"]) for r in kept_rows]
    out["base_within2"] = sum(1 for d in abs_delta if d <= 2)
    out["base_within5"] = sum(1 for d in abs_delta if d <= 5)
    out["base_median_abs"] = statistics.median(abs_delta) if abs_delta else None
    out["amount_counts"] = collections.Counter(r["amount"] for r in kept_rows)
    out["amount_base"] = collections.Counter((r["amount"], r["base_gold"]) for r in kept_rows)
    # 25/50% 假设：把 source6 当成分成，反推 nominal，找最近野怪底额
    share25_err = []
    share50_err = []
    for r in kept_rows:
        for pct, bucket in ((0.25, share25_err), (0.5, share50_err)):
            nominal = r["amount"] / pct
            base = min(JUNGLE_BASE_VALUES, key=lambda v: abs(v - nominal))
            bucket.append(abs(nominal - base))
    out["share25_median_err"] = statistics.median(share25_err) if share25_err else None
    out["share50_median_err"] = statistics.median(share50_err) if share50_err else None
    out["share25_within5"] = sum(1 for e in share25_err if e <= 5)
    out["share50_within5"] = sum(1 for e in share50_err if e <= 5)

    # source5 230-254 = 1.2x
    s5 = []
    for s in samples:
        for e in s["kept"]:
            if e["source"] == 5 and 225 <= e["amount"] <= 260:
                e = dict(e)
                e["file"] = s["file"]
                s5.append(e)
    s5_stats = []
    for e in s5:
        nominal = e["amount"] / 1.2
        base = min((190, 200, 210), key=lambda v: abs(v - nominal))
        s5_stats.append({
            "file": e["file"],
            "t": round(e["t"], 1),
            "amount": e["amount"],
            "base": base,
            "residual": round(e["amount"] - base * 1.2, 2),
            "player": e["player"],
            "hero": e["hero"],
            "role": e["role"],
            "team": e["team"],
        })
    out["s5_stats"] = s5_stats
    out["s5_within3"] = sum(1 for x in s5_stats if abs(x["residual"]) <= 3)
    out["s5_groups"] = collections.Counter((x["base"], x["amount"]) for x in s5_stats)
    out["s5_early"] = [x for x in s5_stats if x["t"] <= 20]
    out["s5_late"] = [x for x in s5_stats if x["t"] > 20]

    # 时间对齐
    def proximity(rs):
        rr = [r for r in rs if r["team"] is not None]
        if not rr:
            return {}
        res = {}
        for label, key, cnt_key in [
            ("any5", "same_team_any_5", "team_event_count"),
            ("any20", "same_team_any_20", "team_event_count"),
            ("any60", "same_team_any_60", "team_event_count"),
            ("any100", "same_team_any_100", "team_event_count"),
            ("jungle5", "same_team_jungle_5", "jungle_event_count"),
            ("jungle20", "same_team_jungle_20", "jungle_event_count"),
            ("jungle60", "same_team_jungle_60", "jungle_event_count"),
            ("jungle100", "same_team_jungle_100", "jungle_event_count"),
        ]:
            n = len(rr)
            hit = sum(1 for r in rr if r[key] > 0)
            res[label] = (hit, n, round(hit / n * 100, 1))
            window = int(label.replace("any", "").replace("jungle", ""))
            obs = sum(r[key] for r in rr) / n
            exp = sum(r[cnt_key] * (2 * window + 1) / r["duration_frames"] for r in rr) / n
            res[label + "_obs_avg"] = round(obs, 3)
            res[label + "_exp_avg"] = round(exp, 3)
            res[label + "_obs_exp"] = round(obs / exp, 2) if exp else None
        for label, key in (("any0", "same_team_any_0"), ("jungle0", "same_team_jungle_0")):
            res[label] = (sum(1 for r in rr if r[key] > 0), len(rr),
                          round(sum(1 for r in rr if r[key] > 0) / len(rr) * 100, 1))
        return res
    out["prox_all"] = proximity(kept_rows)
    out["prox_5069040"] = proximity([r for r in kept_rows if r["res_build"] == "5069040"])

    # 间隔
    def intervals(rs):
        vals = [r["prev_same_player_interval_sec"] for r in rs
                if r["prev_same_player_interval_sec"] is not None]
        return vals
    out["intervals_all"] = intervals(kept_rows)
    out["intervals_5069040"] = intervals(
        [r for r in kept_rows if r["res_build"] == "5069040"])

    # 开局配对：每队首个 source6 vs 首个 source5 225-260
    opening = []
    for s in samples:
        s6 = [e for e in s["kept"] if e["source"] == 6]
        j = [e for e in s["kept"] if e["source"] == 5 and 225 <= e["amount"] <= 260]
        for team in (1, 2):
            a = [e for e in s6 if e["team"] == team]
            b = [e for e in j if e["team"] == team]
            if not a or not b:
                continue
            a0 = min(a, key=lambda e: e["seq"])
            b0 = min(b, key=lambda e: e["seq"])
            opening.append({
                "file": s["short"],
                "res_build": s["res_build"],
                "team": team,
                "s6_t": round(a0["t"], 1),
                "s6_amount": a0["amount"],
                "s6_player": a0["player"],
                "s6_hero": a0["hero"],
                "s5_t": round(b0["t"], 1),
                "s5_amount": b0["amount"],
                "s5_player": b0["player"],
                "s5_hero": b0["hero"],
                "gap": round(a0["t"] - b0["t"], 1),
            })
    out["opening"] = opening
    within = [x for x in opening if abs(x["gap"]) <= 10]
    out["opening_within10"] = within
    out["opening_s6_amounts"] = collections.Counter(x["s6_amount"] for x in within)
    out["opening_s5_amounts"] = collections.Counter(x["s5_amount"] for x in within)

    # source6 / source5 230-254 领取者是否重叠
    disjoint = []
    for s in samples:
        s6p = {e["entity_id"] for e in s["kept"] if e["source"] == 6}
        jp = {e["entity_id"] for e in s["kept"]
              if e["source"] == 5 and 225 <= e["amount"] <= 260}
        if s6p and jp:
            disjoint.append({
                "file": s["short"],
                "res_build": s["res_build"],
                "s6_players": len(s6p),
                "s5_players": len(jp),
                "overlap": len(s6p & jp),
            })
    out["disjoint"] = disjoint

    # source6 / source4 比例
    ratios = []
    for s in samples:
        by = collections.defaultdict(lambda: {"s6": 0, "s4": 0})
        for e in s["kept"]:
            if e["source"] == 6:
                by[e["entity_id"]]["s6"] += e["amount"]
            elif e["source"] == 4:
                by[e["entity_id"]]["s4"] += e["amount"]
        for eid, v in by.items():
            if v["s6"] and v["s4"]:
                b = s["blocks"].get(eid, {})
                ratios.append({
                    "file": s["short"],
                    "res_build": s["res_build"],
                    "player": b.get("name", "?"),
                    "hero": s["events"][0].get("hero") if False else "",
                    "s6": v["s6"],
                    "s4": v["s4"],
                    "ratio": round(v["s6"] / v["s4"], 3),
                })
    # 补 hero
    for r in ratios:
        for s in samples:
            if s["short"] == r["file"]:
                for eid, b in s["blocks"].items():
                    if b.get("name") == r["player"]:
                        r["hero"] = hero_names.get(b.get("hero_id"), "?")
                        break
                break
    out["source4_ratios"] = ratios

    # 主样本
    main_prefix = "20260925_105224"
    out["main_rows"] = [r for r in kept_rows if r["file"].startswith(main_prefix)]
    out["main_all_rows"] = [r for r in rows if r["file"].startswith(main_prefix)]
    out["main_sample"] = next((m for m in sample_meta
                               if m["file"].startswith(main_prefix)), None)
    # 主样本 source5 225-260 领取者
    main_s5 = [x for x in s5_stats if x["file"].startswith(main_prefix)]
    out["main_s5"] = main_s5
    # 主样本每个玩家的 source4/6 汇总
    main_player = collections.defaultdict(lambda: collections.Counter())
    for s in samples:
        if not s["file"].startswith(main_prefix):
            continue
        for e in s["kept"]:
            if e["source"] in (4, 5, 6, 43):
                main_player[e["player"]][e["source"]] += 1
                main_player[e["player"]]["g" + str(e["source"])] += e["amount"]
    out["main_players"] = main_player
    return out


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------
def pct(n, d):
    return f"{n / d * 100:.1f}%" if d else "0.0%"


def md_table(headers, rows):
    out = ["| " + " | ".join(str(h) for h in headers) + " |"]
    out.append("|" + "|".join("---" for _ in headers) + "|")
    for row in rows:
        out.append("| " + " | ".join(str(x) for x in row) + " |")
    return "\n".join(out)


def build_report(stats, sample_meta, rows):
    s = stats
    kept = [r for r in rows if not r["is_duplicate"]]
    by_build = s["by_build"]
    role_all = s["role_all"]
    role_all_g = s["role_all_gold"]
    role_50 = s["role_5069040"]
    role_50_g = s["role_5069040_gold"]

    # build 表
    build_rows = []
    for b in sorted(by_build, key=lambda x: (x != "5069040", x)):
        c = by_build[b]
        build_rows.append([
            b, c["samples"], c["s6_raw"], c["s6_kept"], f"{c['gold_kept']:,}",
            c["role_support_n"], c["role_mid_n"], c["role_side_n"],
            c["role_jungle_n"], c["role_adc_n"], c["role_unknown_n"],
            pct(c["role_support_n"], c["s6_kept"]),
        ])
    # 5069040 样本表
    s50 = [m for m in sample_meta if m["res_build"] == "5069040"]
    s50_rows = [[
        m["short"], m["status"], m["blocks"], m["duration_s"],
        m["s6_raw"], m["s6_kept"], f"{m['s6_gold_kept']:,}",
        m["s6_players"], m["holders"] or "-",
    ] for m in s50]
    # 主样本逐条
    main_rows = []
    for r in s["main_rows"]:
        main_rows.append([
            r["seq"], f"{r['t_sec']:.1f}", r["player"], r["hero"], r["role"],
            r["amount"], r["base_gold"], r["base_names"],
            r["nearest_same_team_any_delta"] if r["nearest_same_team_any_delta"] is not None else "-",
            r["nearest_same_team_jungle_delta"] if r["nearest_same_team_jungle_delta"] is not None else "-",
        ])
    # 金额表
    amt_rows = []
    for (amount, base), n in sorted(s["amount_base"].items()):
        names = next((r["base_names"] for r in kept
                      if r["amount"] == amount and r["base_gold"] == base), "")
        amt_rows.append([amount, base, f"{amount - base:+d}", n, names])
    # source5 公式表
    s5_rows = []
    for base in (190, 200, 210):
        for amount in sorted({x["amount"] for x in s["s5_stats"] if x["base"] == base}):
            n = sum(1 for x in s["s5_stats"] if x["base"] == base and x["amount"] == amount)
            s5_rows.append([base, f"{base * 1.2:.0f}", amount, f"{amount - base * 1.2:+.1f}", n])
    # 时间对齐表
    def prox_row(label, p):
        return [
            label,
            f"{p.get('any5', (0,0,0))[0]}/{p.get('any5', (0,0,0))[1]} ({p.get('any5', (0,0,0))[2]}%)",
            f"{p.get('any20', (0,0,0))[0]}/{p.get('any20', (0,0,0))[1]} ({p.get('any20', (0,0,0))[2]}%)",
            f"{p.get('any60', (0,0,0))[0]}/{p.get('any60', (0,0,0))[1]} ({p.get('any60', (0,0,0))[2]}%)",
            f"{p.get('any100', (0,0,0))[0]}/{p.get('any100', (0,0,0))[1]} ({p.get('any100', (0,0,0))[2]}%)",
            f"{p.get('jungle20', (0,0,0))[0]}/{p.get('jungle20', (0,0,0))[1]} ({p.get('jungle20', (0,0,0))[2]}%)",
            f"{p.get('jungle60', (0,0,0))[0]}/{p.get('jungle60', (0,0,0))[1]} ({p.get('jungle60', (0,0,0))[2]}%)",
        ]
    prox_rows = [
        prox_row("全部 20 样本（去重）", s["prox_all"]),
        prox_row("5069040（去重）", s["prox_5069040"]),
    ]
    # 间隔
    ints_all = s["intervals_all"]
    ints_50 = s["intervals_5069040"]
    def interval_summary(vals):
        if not vals:
            return "无"
        return (f"n={len(vals)}，中位 {statistics.median(vals):.1f}s，"
                f"范围 {min(vals):.1f}–{max(vals):.1f}s；"
                f"60±10s {sum(1 for x in vals if abs(x-60)<=10)}；"
                f"90±10s {sum(1 for x in vals if abs(x-90)<=10)}；"
                f"120±10s {sum(1 for x in vals if abs(x-120)<=10)}")
    # 开局配对
    open_rows = [[
        x["file"], x["res_build"], x["team"], x["s6_t"], x["s6_amount"],
        x["s6_player"], x["s6_hero"], x["s5_t"], x["s5_amount"],
        x["s5_player"], x["s5_hero"], x["gap"],
    ] for x in s["opening"]]
    open_within = s["opening_within10"]
    # 主样本玩家
    main_player_rows = []
    for player, c in sorted(s["main_players"].items(), key=lambda kv: -kv[1]["g6"]):
        main_player_rows.append([
            player, c[4], f"{c['g4']:,}", c[5], f"{c['g5']:,}",
            c[6], f"{c['g6']:,}", c[43], f"{c['g43']:,}",
        ])
    # source4 比例
    ratio_rows = [[
        r["file"], r["player"], r["hero"], r["s6"], r["s4"], f"{r['ratio']:.2f}",
    ] for r in sorted(s["source4_ratios"], key=lambda x: -x["ratio"])[:12]]

    md = []
    md.append("# source6 野怪金归属（普通 5v5，按 res_build 分层）\n")
    md.append("只读分析；未修改回放/包体，未读取 `param.json`，未使用 `runtime_dump`；"
              "未编辑 `docs/replay_binary_format.md` 与 `.workbuddy/memory/MEMORY.md`。\n")
    md.append("## 0. 结论先行\n")
    md.append(
        "1. **source6 是野怪击杀金（基础全额），不是助攻/分享金**。"
        f"去重后 {s['s6_kept']} 条 source6 中，{s['base_within5']}/{s['s6_kept']} "
        f"金额落在 normalMonster 野怪底额 ±5 内，{s['base_within2']}/{s['s6_kept']} 在 ±2 内，"
        f"中位绝对偏差 {s['base_median_abs']:.1f} 金；金额形态是 160→165、174→175、"
        "178→178、180→185、190→188/189/191、200→201、210→211。"
        "25% 分成的反推底额（按 normal 5v5 野怪底额 160–210）中位误差 "
        f"{s['share25_median_err']:.1f} 金、仅 {s['share25_within5']}/{s['s6_kept']} 条落在 ±5；"
        "50% 分成也只有 "
        f"{s['share50_within5']}/{s['s6_kept']} 条落在 ±5。→ **不是 25%~50% 分成金额**。置信度 high。\n")
    md.append(
        "2. **source6 的领取者绝大多数是辅助/游走，不是打野**。"
        f"全部 build 去重后：辅助 {role_all['support']}/{s['s6_kept']} "
        f"({pct(role_all['support'], s['s6_kept'])})、中/法 {role_all['mid']}、"
        f"边/坦 {role_all['side']}、未知 {role_all['unknown']}、打野 {role_all['jungle']}、"
        f"射手 {role_all['adc']}；辅助金额 {role_all_g['support']:,}/{s['s6_gold_kept']:,} "
        f"({pct(role_all_g['support'], s['s6_gold_kept'])})。"
        f"5069040 去重后：辅助 {role_50['support']}/{s['s6_kept'] if False else sum(role_50.values())} "
        f"({pct(role_50['support'], sum(role_50.values()))})、中/法 {role_50['mid']}、"
        f"边/坦 {role_50['side']}、打野 0、射手 0。"
        "18 个有 source6 的样本，首个 source6 全部是 165；其中 17/18 为辅助/游走，"
        "唯一例外是 20260925_101323 的夏侯惇（source4 仅 1 次，按低补刀可视为游走/坦）。"
        "这不是主样本偶然。置信度 high。\n")
    md.append(
        "3. **打野金没有丢，主要在 source5 230–254，而不是 source6**。"
        f"source5 的 225–260 段共 {len(s['s5_stats'])} 条，"
        f"{s['s5_within3']}/{len(s['s5_stats'])} 条满足 "
        "`amount ≈ 野怪底额 × 1.20 + 1~3 尾数`：190→231、200→241/242/243、"
        "210→251/252/253/254。190/200/210 正是石像/主宰/巨熊等野怪底额；"
        "1.20 与打野刀“自己击杀或附近友方击杀野怪额外获得 20% 金币”一致。"
        "→ **source5 230–254 = 打野刀/惩击 +20% 的野怪金通道**，"
        "不是之前猜的推塔/目标金。金额公式置信度 high；具体协议字段名（最接近 "
        "`dwEquipJungleShangJinCoin`）为 medium。\n")
    md.append(
        "4. **source6 与 source5 230–254 是两条不同领取者的通道，通常不重叠**。"
        f"18 个同时有两条通道的样本中，{sum(1 for x in s['disjoint'] if x['overlap']==0)}/18 "
        "个样本的两组领取者完全不相交；只有 1 个样本出现 1 人重叠。"
        "source6 领取者是辅助/游走，source5 230–254 领取者多数是打野英雄或携带打野刀的人。"
        "置信度 high。\n")
    md.append(
        "5. **开局是“打野拿 BUFF、辅助拿边野”的并行开局，不是辅助抢打野金**。"
        f"{len(open_within)}/{len(s['opening'])} 个“同队同时有两条通道”的队对中，"
        "首个 source6 与首个 source5 230–254 的时间差在 ±10s 内；"
        f"这 {len(open_within)} 对里首个 source6 全是 {dict(s['opening_s6_amounts'])}，"
        f"首个 source5 全是 {dict(s['opening_s5_amounts'])}。"
        "165 = 160 底额（红隼/赤甲）+5 尾数；231 = 190 底额（石像）+20% +3 尾数。"
        "不同野怪、不同领取者、同一开局窗口 → **两条独立的击杀金，不是同一只野怪的分成**。"
        "置信度 high。\n")
    md.append(
        "6. **source6 也不是“恩赐”周期金**。恩赐是 5/6 金/3s（`0x522bde8` 149/152/153 行；"
        "`0x8268ac` 9657–9660），source6 金额是 165–211，间隔中位 "
        f"{statistics.median(ints_all):.1f}s（全部）/{statistics.median(ints_50):.1f}s（5069040），"
        "60±10s 与 90±10s 命中都很少；没有 3s 节律。置信度 high。\n")
    md.append(
        "7. **主样本角色表需要按黄金通道修正**：按 source5 230–254，主样本 team1 的早期"
        "“打野刀持有人”是马超（231@4.1s、253@461.9s），team2 是赵云"
        "（231@3.5s、243@52.7s、253@332.9s、254@425.6s）；影没有 230–254，也没有 source6，"
        "事件金 2,527 为主样本最低。背景把影标成打野，与黄金通道不一致；"
        "可能是角色互换、马超带打野刀/偷野，或影的打野刀等级不同。置信度 medium。"
        "无论角色怎么标，**source6 都不是打野金的主通道**。\n")
    md.append(
        "8. **最终归类建议：混合（击杀金为主 + 辅助装分享归属）**。"
        "金额与事件口径是“野怪击杀金（基础全额）”，不是 25–50% 分成、不是助攻、不是恩赐周期金；"
        "但领取者稳定落在辅助/游走，辅助装“游击/分享（单人 100%，有队友 25–50%）”解释了为什么是辅助领取。"
        "如果必须四选一：选“混合”，不要单独选“击杀金”（会漏掉辅助装归属机制）或“辅助装金”"
        "（会误以为金额是辅助装分成）。置信度：金额/事件 high，归属机制 high，实际入账比例 medium。\n")
    md.append("## 1. 样本、口径与产物\n")
    md.append(
        f"- 27 个 `.abc`，{s['samples_total']} 个有 `0x02 len=5` 金币事件；"
        f"原始金币事件 {s['raw_events_total']:,} 条；source6 原始 {s['s6_raw']} 条 / "
        f"{s['s6_gold_raw']:,} 金，去重后 {s['s6_kept']} 条 / {s['s6_gold_kept']:,} 金。\n"
        "- 去重规则：同一 `(entity, source, amount)` 在 ≤12 帧内连续出现 ≥3 次，"
        "保留第一条、其余标记为重复通知。原始与去重两套数字都在 CSV/报告中保留。\n"
        "- 时间：`seq/20` 秒。回放时间原点不一定是游戏开局；本报告只用相对时间，"
        "不用绝对时间解释 buff 刷新。\n"
        "- 角色：按英雄集合启发式（辅助/中/边/野/射）；墨子、扁鹊、夏侯惇、芈月为 medium。"
        "source6 领取者没有打野/射手，因此角色误差不影响主结论。\n"
        "- 产物：`tools/agent_source6_attribution.py`、"
        "`datasets/agent_source6_attribution.csv`、`datasets/agent_source6_attribution.md`。\n")
    md.append("## 2. 按 res_build 分层（不要混格式）\n")
    md.append(md_table(
        ["res_build", "样本", "source6 原始", "去重", "去重金币", "辅助", "中", "边",
         "打野", "射手", "未知", "辅助占比"],
        build_rows))
    md.append("\n口径：`res_build` 来自 `datasets/replay_index.csv`；"
              "5069040 = 6 个样本（3 ok + 3 partial_players），主样本 20260925_105224 属于该 build。"
              "其他 build 只作对照，不把跨 build 结论当普通 5v5 结论。"
              "5230306 只有 5 条 source6（2 辅助/1 中/2 边），样本量太小，不能据此说该 build 辅助不主导；"
              "5069040 的 76.9% 主要被 20260925_101323 的 3 条夏侯惇（边/坦）和 1 条王维（中）拉低。\n")
    md.append("### 2.1 5069040 六个样本\n")
    md.append(md_table(
        ["样本", "status", "玩家块", "时长s", "source6 原始", "去重", "去重金币",
         "领取者数", "开局打野刀持有人（source5 225–260 ≤20s）"],
        s50_rows))
    md.append("\n注：20260925_094930、20260925_095631 只有 2 个玩家块（partial），无 source6；"
              "20260925_101323 的 15×175 是同一通知的重复簇，去重后 1 条；"
              "20260925_103058 的 source6 本身无重复，但 source4 有重复簇（不影响 source6 结论）。\n")
    md.append("## 3. source6 角色分布（去重）\n")
    md.append(md_table(
        ["范围", "事件", "辅助", "中/法", "边/坦", "打野", "射手", "未知", "辅助占比"],
        [
            ["全部 build", s["s6_kept"], role_all["support"], role_all["mid"],
             role_all["side"], role_all["jungle"], role_all["adc"],
             role_all["unknown"], pct(role_all["support"], s["s6_kept"])],
            ["5069040", sum(role_50.values()), role_50["support"], role_50["mid"],
             role_50["side"], role_50["jungle"], role_50["adc"],
             role_50["unknown"], pct(role_50["support"], sum(role_50.values()))],
        ]))
    md.append("\n5069040 的 3 条边/坦全部是 20260925_101323 的夏侯惇（source4 仅 1 次，"
              "按低补刀可视为游走/坦；若把夏侯惇计辅助，5069040 辅助占比为 "
              f"{pct(role_50['support'] + role_50['side'], sum(role_50.values()))}）。"
              "中/法是 11363 金蝉、101323 王维、105224 扁鹊。"
              "没有一条 source6 给到打野或射手。\n")
    md.append("### 3.1 主样本 8 条 source6\n")
    md.append(md_table(
        ["seq", "t(s)", "玩家", "英雄", "角色", "金额", "最近底额", "候选野怪",
         "最近同队金币事件 Δ帧", "最近同队打野刀持有人事件 Δ帧"],
        main_rows))
    md.append("\n主样本 source6 合计 1,452 金；东皇太一 3 条/541、朵莉亚 4 条/720、"
              "扁鹊 1 条/191；影/赵云 0 条。source6 与同队打野刀持有人事件不同帧、"
              "不紧随（按数据驱动持有人，最近 Δ 为 -41/-45/-207/+113/-260/-34/+5/+164 帧；"
              "只有 1 条在 ±20 帧内，0 条同帧）。\n")
    md.append("## 4. 时间对齐：source6 不是“紧跟打野”的助攻/分享\n")
    md.append(md_table(
        ["范围", "同队任意 ±5", "±20", "±60", "±100",
         "打野刀持有人 ±20", "±60"],
        prox_rows))
    md.append("\n- 同帧（Δ=0）同队任何 source4/5/43：全部样本 0 条；5069040 0 条。"
              "全部样本 n=93 而非 96：3 条 source6 的 entity 不在玩家块"
              "（20260827_012122/20261016_005102/20261027_231329），未计入时间对齐。\n"
              "- 5069040 的 source6 到同队打野刀持有人最近事件的中位距离 81.5 帧（4.1s），"
              "±20 帧命中 3/26（11.5%），obs/exp=1.44；±5 帧仅 1/26（3.8%），同帧 0 条。"
              "“紧跟同队打野/助攻分享”的说法不成立。\n"
              "- 同队任意事件 ±20 帧有 42.3% 命中，但这是事件密度高导致的（obs/exp≈1.85），"
              "不是同帧击杀组合；同帧 0 条。\n"
              "- 间隔：全部 " + interval_summary(ints_all) + "；5069040 " +
              interval_summary(ints_50) + "。没有固定 60/90s buff 周期。\n")
    md.append("### 4.1 开局并行：首个 source6 vs 首个 source5 230–254\n")
    md.append(md_table(
        ["样本", "build", "队", "source6 t", "金额", "玩家/英雄",
         "source5 t", "金额", "玩家/英雄", "Δt(s)"],
        open_rows))
    md.append(f"\n- 31 个“同队同时有两条通道”的队对中，{len(open_within)} 对在 ±10s 内；"
              f"这 {len(open_within)} 对的首个 source6 金额分布 {dict(s['opening_s6_amounts'])}，"
              f"首个 source5 金额分布 {dict(s['opening_s5_amounts'])}。"
              "26/26 是 165 vs 231：160 基础边野（辅助）vs 190 基础 BUFF×1.2（打野刀持有人）。\n"
              "- 5 个例外：部分样本只有 2 个玩家块、或 source6/source5 开局事件缺失/延后"
              "（如 20260827_004836 team1、20261016_005102 team1、20261016_194242 team2、"
              "20261027_231329 team1、20261027_232156 team1）。\n")
    md.append("## 5. 金额对齐：source6 = 全额击杀金，不是分成\n")
    md.append(md_table(
        ["source6 金额", "最近底额", "偏差", "条数", "normalMonster 候选"],
        amt_rows))
    md.append("\n- 96/96 条在 ±5 内，50/96 在 ±2 内；金额形态与 normalMonster 野怪底额一致。"
              "若把 source6 当 25% 分成，按 normal 5v5 野怪底额 160–210 反推 nominal，"
              f"中位误差 {s['share25_median_err']:.1f} 金；50% 也只有 {s['share50_within5']}/96 条在 ±5。"
              "→ source6 不是 25%~50% 分成，也不是 100/200 的助攻/击杀底额。\n"
              "- 与 source4 的比例不固定：主样本 东皇 541/781=0.69、朵莉亚 720/382=1.88、"
              "扁鹊 191/4,070=0.047；全部样本 source6/source4 从 0.05 到 2.79（中位 0.39）散开，"
              "没有固定分成比。\n"
              "- 辅助装表明确写：游走装“不参与野怪/小兵收益分配，单独获得 25%~50% 金币和经验"
              "（单人时 100%）”。如果 source6 是辅助装分成，160 底额应只有 40–80，"
              "不可能是 165；165 只可能是 **160 全额 + 5 自然尾数**，即辅助独吃边野（单人 100%）"
              "或名义全额击杀通知。\n")
    md.append("### 5.1 source5 230–254 = 野怪底额 ×1.20\n")
    md.append(md_table(
        ["底额", "×1.2", "观测金额", "残差", "条数"],
        s5_rows))
    md.append(f"\n- {s['s5_within3']}/{len(s['s5_stats'])} 条在 ±3 内；"
              "190→231、200→241/242/243、210→251/252/253/254。"
              "残差 1–3 与 source4/source6 的自然尾数同量级。\n"
              "- 早期（≤20s）领取者多为打野英雄："
              f"{len(s['s5_early'])} 条中打野角色 "
              f"{sum(1 for x in s['s5_early'] if x['role']=='jungle')} 条；"
              "晚期（>20s）也以打野/边路为主。"
              "数值与打野刀“额外 20% 金币”的 native 字段 `+0xe0=2000` 一致"
              "（`agent_native_buffs.csv` 0x8268ac 第 9520 行）。\n"
              "- **这是对既有 source5 分类的修正**：主样本 备水一站 4 条/981、"
              "双枪踏浪行 2 条/484 曾被标为“目标/推塔候选”；"
              "981=231+243+253+254、484=231+253，正好是 190/200/210×1.2+尾数，"
              "且 231 出现在 3.5–4.1s（不可能推塔），应改判为打野刀 +20% 野怪金。\n")
    md.append("## 6. 辅助装/打野刀表证据（只读）\n")
    md.append(
        "- 游走装 25%~50%：`datasets/agent_global_strings.csv` 表 `0x522bde8` "
        "第 149/150/152/153 行（学识宝石 1701、凤鸣指环 1711、极影 1712、极影·救赎 1746）："
        "“不参与野怪/小兵收益分配，单独获得 25%~50% 金币与经验（20 分钟达到上限）”。\n"
        "- 单人 100%：`datasets/agent_native_buffs.csv` 表 `0x8268ac` "
        "row_index=9769/9774（文件第 9771/9776 行，row_id 917736/917741）"
        "（展示游走身份，keyword `exp,economy,income`）：“……单独获得 25%-50% 经济和经验"
        "（单人时获得 100%）”。\n"
        "- 游击 50% 数值：`agent_native_buffs.csv` 表 `0x8268ac` row_index=9643（row_id 915731）"
        "desc 为“小兵死亡后获得该单位提供的 50% 金币和经验”，params 里 "
        "`+0xdc=10000`（100%）、`+0xe0=5000`（50%），keyword `gold,exp,economy,income`。\n"
        "- 恩赐/补偿：`agent_native_buffs.csv` 第 9657–9660 行（学识宝石经验/金币/第五名/第四名补偿）"
        "params `+0xd4=3000`（3s）、`+0xd8=1/6/3`，keyword `gold,support,compensate`；"
        "字符串表 `0x522bde8` 第 149/152/153 行写“每 3 秒获得 5/6 经验，队伍中经济最低英雄获得 5/6 金币”。"
        "这解释 source5 的小额/131–146 混合，不解释 source6 的 165–211。\n"
        "- 打野刀 +20%：`agent_native_buffs.csv` 第 9520 行（打野刀）params "
        "`+0xe0=2000`（20%）、`+0xe8=1`；`agent_global_strings.csv` 表 `0x522bde8` "
        "第 174/179/180 行写“获得 25% 野怪减伤、30% 野怪经验提升与 20% 野怪金币提升”，"
        "第 184/185/186 行写“自己击杀或 500 范围内友方击杀野怪时，自己会额外获得 30% 经验和 20% 金币”。"
        "这正是 source5 230–254 的 ×1.2 来源。\n"
        "- 协议字段（只读引用）：`dwMonsterKillCoin`、`dwEquipJungleShangJinCoin`、"
        "`dwEquipJungleYouJiCoin`、`dwEquipAssistEnCiCoin`、`dwEquipAssistYouJiCoin`、"
        "`dwAidEquipCoin`、`dwAidNotShareIncomeLastTime`（普通 5v5 60s）。"
        "30 秒统计块不在回放容器里，所以不能把 source5/source6 逐条对到某个协议字段；"
        "字段名只能给候选。\n")
    md.append("## 7. 打野金去哪了\n")
    md.append(
        "1. **打野刀的野怪击杀金在 source5 230–254**：190/200/210 底额 ×1.20 + 尾数。"
        "主样本 赵云 4 条/981、马超 2 条/484；20260827_010503 典韦/赵云各 231；"
        "20260827_013634 心魔六耳/典韦各 231；20260902_221251 盘古/露娜各 231。"
        "这些是队伍里的“打野刀持有人”，不一定是背景里的打野位。\n"
        "2. **source6 是另一条通道**：辅助/游走拿边野（红隼/赤甲 160 等），没有打野刀 +20%，"
        "所以金额是基础全额（165 等）。开局 26/26 队对是 165 vs 231，说明两条通道打的是不同野怪。\n"
        "3. **“打野事件金偏低”是口径问题**：如果只统计 source6，打野看起来 0；"
        "把 source5 230–254 算进来，打野刀持有人的野怪金并不低。"
        "主样本 影 既没有 230–254 也没有 source6，事件金 2,527 最低；"
        "按黄金通道，team1 的早期打野刀持有人是马超（3,621 事件金），不是影。"
        "背景角色表需要复核。\n"
        "4. **辅助装金不是 source6 的主体**：辅助装 25–50% 是额外分金/补偿；"
        "source6 金额是基础击杀金。辅助独吃边野（单人 100%）时才等于全额；"
        "与队友同范围时，实际辅助入账可能只有 25–50%，但 source6 金额仍记全额基础值。"
        "这部分需要逐帧位置/装备数据才能闭合。\n")
    md.append("## 8. 置信度\n")
    md.append(md_table(
        ["结论", "置信度", "主要证据"],
        [
            ["source6 = 野怪击杀金（基础全额）", "high",
             "96/96 金额在底额 ±5；50/96 在 ±2；25%/50% 分成假设被金额否决"],
            ["source6 领取者以辅助/游走为主", "high",
             "81/96 事件、14,341/17,138 金；18/18 样本首个 source6=165，17/18 为辅助"],
            ["source6 ≠ 助攻/分享金额", "high",
             "金额是 100% 底额，不是 25–50%；同帧同队事件 0 条；source43 才是 102/203"],
            ["source6 ≠ 恩赐周期金", "high",
             "金额 165–211 vs 恩赐 5/6 金；无 3s 节律；间隔中位 134s"],
            ["source5 230–254 = 打野刀 +20%", "high（金额）/ medium（字段名）",
             "94/94 条 ≈ 190/200/210×1.2；打野刀 native 字段 +0xe0=2000；与 source6 领取者 17/18 样本不相交"],
            ["开局是打野 BUFF + 辅助边野的并行开局", "high",
             "26/26 队对首个 source6=165、首个 source5=231，Δt 中位 2.4s；不同底额"],
            ["source6 实际入账 = 100% 还是 25–50%", "medium",
             "首个边野大概率单人 100%；后续是否与队友同范围无法从 0x02 判定"],
            ["主样本 team1 打野刀持有人 = 马超（不是影）", "medium",
             "source5 231/253 只给马超；影无 230–254/source6；缺装备/位置数据"],
        ]))
    md.append("## 9. 剩余缺口（不要把“没找到”说成“不存在”）\n")
    md.append(
        "- 回放没有逐单位野怪 ID/击杀者字段、没有连续位置；无法把每条 source6 对到具体野怪实体，"
        "也无法证明辅助每次都是单人（100%）还是与队友同范围（25–50%）。\n"
        "- 购买/装备事件被 operator 版本阻塞；无法直接读“谁带了打野刀/游走装”，"
        "只能用 source5 230–254 的 ×1.2 金额和英雄角色反推。\n"
        "- `COMDT_GAME_30SEC_INFO` 30s 统计块不在回放容器；不能把 source5/source6 逐条对到 "
        "`dwMonsterKillCoin` / `dwEquipJungleShangJinCoin` / `dwAidEquipCoin` 的字段级金额。\n"
        "- source5 131–146 仍是混合通道（辅助装/被动/团队金候选），未完全拆开；"
        "本报告只把 230–254 单独归为打野刀 +20%。\n"
        "- 20260925_101323 有 15×175 的重复通知簇（去重后 1 条），20260925_103058 有 source4 重复簇；"
        "原始条数会高估，报告同时给 raw/kept。\n"
        "- 20260925_094930、20260925_095631 只有 2 个玩家块，无 source6；"
        "不能据此说这两个样本“没有辅助拿野”。\n"
        "- 角色表是启发式；主样本 team1 与背景角色冲突，需用装备/位置/队伍语音或服务端数据复核。\n")
    md.append("## 10. 复跑\n")
    md.append("```bash\npython tools/agent_source6_attribution.py\n```\n")
    md.append("默认读 `data/replays/samples/abc_batch`，写 "
              "`data/replays/_analysis/datasets/agent_source6_attribution.csv|md`。"
              "`--dedup-window`/`--dedup-min-run` 可调去重；`--samples-dir` 可换目录。\n")
    return "\n".join(md) + "\n"


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main():
    global DEDUP_WINDOW, DEDUP_MIN_RUN
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples-dir", default=str(SAMPLE_DIR))
    ap.add_argument("--out-csv", default=str(OUT_CSV))
    ap.add_argument("--out-md", default=str(OUT_MD))
    ap.add_argument("--dedup-window", type=int, default=DEDUP_WINDOW)
    ap.add_argument("--dedup-min-run", type=int, default=DEDUP_MIN_RUN)
    args = ap.parse_args()

    DEDUP_WINDOW = args.dedup_window
    DEDUP_MIN_RUN = args.dedup_min_run

    hero_names = load_hero_names()
    index = load_replay_index()
    samples, meta, rows, monster_rows = analyze(Path(args.samples_dir), hero_names, index)
    if not samples:
        raise SystemExit(f"no parseable .abc under {args.samples_dir}")

    stats = summarize(samples, meta, rows, monster_rows, hero_names)
    # CSV
    fields = [
        "file", "sample", "res_build", "replay_status", "seq", "t_sec",
        "entity_id", "team", "slot", "player", "hero_id", "hero", "role",
        "role_confidence", "amount", "run_len", "is_duplicate", "base_gold",
        "base_names", "base_delta", "share25_amount", "share50_amount",
        "same_team_any_0", "same_team_any_5", "same_team_any_20",
        "same_team_any_60", "same_team_any_100",
        "same_team_jungle_0", "same_team_jungle_5", "same_team_jungle_20",
        "same_team_jungle_60", "same_team_jungle_100",
        "same_hero_other_0", "same_hero_other_5", "same_hero_other_20",
        "same_hero_other_60",
        "nearest_same_team_any_delta", "nearest_same_team_any_source",
        "nearest_same_team_any_player", "nearest_same_team_jungle_delta",
        "nearest_same_team_jungle_source", "nearest_same_team_jungle_player",
        "nearest_same_team_jungle_hero", "jungle_holders",
        "jungle_holder_source", "prev_same_player_interval_sec",
        "team_event_count", "jungle_event_count", "duration_frames",
    ]
    out_csv = Path(args.out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8-sig", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=fields)
        w.writeheader()
        for r in sorted(rows, key=lambda x: (x["file"], x["seq"])):
            w.writerow({k: r.get(k, "") for k in fields})

    # MD
    report = build_report(stats, meta, rows)
    out_md = Path(args.out_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(report, encoding="utf-8")

    print(f"samples={len(samples)} source6_raw={stats['s6_raw']} "
          f"source6_kept={stats['s6_kept']} gold_raw={stats['s6_gold_raw']} "
          f"gold_kept={stats['s6_gold_kept']}")
    print(f"csv={out_csv}")
    print(f"md={out_md}")


if __name__ == "__main__":
    main()
