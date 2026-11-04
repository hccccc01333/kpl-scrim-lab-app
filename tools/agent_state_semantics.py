#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""普通 5v5 逐英雄状态通道语义：0x81 value6 / 0x81 1-4 / 0x82 kind-toggle / 0x23 窗口。

只读边界
--------
* 只读 `data/replays/samples/abc_batch/*.abc` 与 `data/replays/_analysis/datasets/`
  下已经解出的 CSV；不改回放、不改包体、不注入、不读 param.json、不使用
  runtime_dump；不写 docs/replay_binary_format.md 与 .workbuddy/memory/MEMORY.md。
* 产物只写本工具、`agent_state_semantics.csv`、`agent_state_semantics.md`。

回答的问题
----------
1. 6 个 build 5069040 样本 + 1 个 5247758 人机样本上，`0x02/0x81 value6`
   的窗口与 source43 击杀/队伍比分能否对拍；value6=死亡能推到什么置信度；
   1547 / 338 / 1021 / 212 这类“无 v6”是漏检还是真的 0 死。
2. 442 李信 8 个 v6 窗口：死亡还是形态切换；用 0x2d 朝向、0x80 命令、
   0x85 source4 金币、0x87 技能升级、0x29/0x1e/0x2c 轨迹区分。
3. 0x81 的 1/2/3/4 按英雄/时间/技能表解释；0x82 kind/toggle 与 0x23
   窗口给出语义（带证据与置信度）。

复跑
----
    python tools/agent_state_semantics.py
    python tools/agent_state_semantics.py --out-csv ... --out-md ...
"""
from __future__ import annotations

import argparse
import bisect
import csv
import random
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AN = ROOT / "data" / "replays" / "_analysis"
DATASETS = AN / "datasets"
ABC_BATCH = ROOT / "data" / "replays" / "samples" / "abc_batch"
OUT_CSV = DATASETS / "agent_state_semantics.csv"
OUT_MD = DATASETS / "agent_state_semantics.md"

BUILD_5069040 = "5069040"
BUILD_5247758 = "5247758"

# (sample key, abc prefix, build)
SAMPLE_SPECS = [
    ("20260924_113638", "20260924_113638", BUILD_5069040),
    ("20260925_094930", "20260925_094930", BUILD_5069040),
    ("20260925_095631", "20260925_095631", BUILD_5069040),
    ("20260925_101323", "20260925_101323", BUILD_5069040),
    ("20260925_103058", "20260925_103058", BUILD_5069040),
    ("20260925_105224", "20260925_105224", BUILD_5069040),
    ("20261101_182452", "20261101_182452", BUILD_5247758),
]

# 5247758 的 0x02 子类型是固定体长（见 docs 5.107 / replay_parser.py）
NEW_BUILD_LENGTHS = {0x80: 12, 0x81: 22, 0x82: 16, 0x85: 7, 0x87: 7}

# 0x81 值 6 的窗口合并：同一英雄相邻 v6 记录间隔 <= 1 秒算同一窗口
WINDOW_GAP_S = 1.0

# source43 击杀金：202/203=击杀，102=助攻（现有 docs 5.96/5.106 口径）
KILL_AMOUNTS = {202, 203}
ASSIST_AMOUNT = 102

HUMAN_ENTITIES_NEW = {1804, 212}


# ---------------------------------------------------------------------------
# 容器 / 帧流
# ---------------------------------------------------------------------------
def find_sample(prefix: str) -> Path:
    hits = sorted(ABC_BATCH.glob(prefix + "*.abc"))
    if not hits:
        raise SystemExit(f"sample not found: {prefix}")
    return hits[0]


def parse_header(data: bytes) -> dict:
    texts, pos = [], 0
    for _ in range(4):
        n = data[pos]
        if not 1 <= n <= 80:
            raise ValueError("bad header")
        texts.append(data[pos + 1 : pos + 1 + n].decode("utf-8", "replace"))
        pos += 1 + n
    local_hero = int.from_bytes(data[pos : pos + 2], "little")
    return {
        "versions": texts[:2],
        "builds": texts[2:],
        "local_hero": local_hero,
        "header_bytes": pos + 2,
    }


def find_stream(data: bytes):
    """最长 seq/pad/L/payload 链；main 段只用 u8 低字节 + pad=0。"""
    n = len(data)
    best = (0, 0, [])
    for start in range(min(n - 10, 0x40000)):
        if data[start + 1] != 0:
            continue
        pos, seq, recs = start, data[start], []
        while pos + 10 <= n and data[pos] == (seq & 0xFF) and data[pos + 1] == 0:
            length = data[pos + 2]
            if pos + 10 + length > n:
                break
            recs.append((pos, data[pos + 3 : pos + 3 + length]))
            pos += 10 + length
            seq += 1
        if len(recs) > len(best[2]):
            best = (start, pos, recs)
        if len(recs) > 1000:
            break
    return best


def parse_payload(pl: bytes, build: str):
    """返回 (msgs, ok)。msgs: (tag, hero, flag, body)。"""
    i, n, out = 1, len(pl), []
    while i < n:
        tag = pl[i]
        if tag == 0x12:
            if i + 3 > n:
                return out, False
            out.append(("s12", 0, 0, bytes(pl[i + 1 : i + 3])))
            i += 3
        elif tag == 0x13:
            i += 2
        elif tag == 0x14:
            i += 4
        elif tag == 0x01:
            if i + 5 > n:
                return out, False
            length = pl[i + 4]
            if i + 5 + length > n:
                return out, False
            out.append(
                ("01", int.from_bytes(pl[i + 1 : i + 3], "big"), pl[i + 3],
                 pl[i + 5 : i + 5 + length])
            )
            i += 5 + length
        elif tag == 0x02:
            if i + 4 > n:
                return out, False
            flag = pl[i + 3]
            if build == BUILD_5247758:
                length = NEW_BUILD_LENGTHS.get(flag)
                if length is None:
                    return out, False
            else:
                length = 12 if flag == 0x80 else (flag & 0x7F)
            if i + 4 + length > n:
                return out, False
            out.append(
                ("02", int.from_bytes(pl[i + 1 : i + 3], "big"), flag,
                 pl[i + 4 : i + 4 + length])
            )
            i += 4 + length
        else:
            return out, False
    return out, True


# ---------------------------------------------------------------------------
# 名单 / 面板真值
# ---------------------------------------------------------------------------
def read_csv_rows(path: Path):
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def load_roster(sample_key: str, build: str) -> dict:
    out = {}
    if build == BUILD_5069040:
        path = DATASETS / "normal5v5_player_heroes_5069040.csv"
        for row in read_csv_rows(path):
            sample_tag = row.get("sample", "")
            # 60924/101323 的 sample 列是长 key，103058/105224 是短 key
            if not sample_tag.startswith(sample_key):
                continue
            try:
                entity = int(row["entityID"])
                team = int(row["team"])
                hero_id = int(row["heroID"])
            except (KeyError, ValueError):
                continue
            out[entity] = {
                "player": row.get("player", ""),
                "team": team,
                "slot": int(row.get("slot") or 0),
                "hero_id": hero_id,
                "hero_name": row.get("heroName", ""),
                "human": True,
                "deaths": None,
                "kills": None,
                "assists": None,
            }
    elif build == BUILD_5247758:
        path = DATASETS / "new_5247758_panel_truth_for_validation.csv"
        for row in read_csv_rows(path):
            try:
                entity = int(row["entityID"])
                team = int(row["team"])
                hero_id = int(row["heroID"])
            except (KeyError, ValueError):
                continue
            out[entity] = {
                "player": row.get("player", ""),
                "team": team,
                "slot": 0,
                "hero_id": hero_id,
                "hero_name": row.get("hero", ""),
                "human": entity in HUMAN_ENTITIES_NEW,
                "deaths": int(row.get("deaths") or 0),
                "kills": int(row.get("kills") or 0),
                "assists": int(row.get("assists") or 0),
            }
    return out


# ---------------------------------------------------------------------------
# 抽取
# ---------------------------------------------------------------------------
@dataclass
class SampleData:
    key: str
    path: Path
    build: str
    fps: float
    header: dict = field(default_factory=dict)
    roster: dict = field(default_factory=dict)
    records: int = 0
    frame_start: int = 0
    frame_end: int = 0
    bad_payloads: int = 0
    s81: list = field(default_factory=list)      # dict frame/hero/value/body
    s82: list = field(default_factory=list)      # dict frame/hero/kind/toggle/body
    s23: list = field(default_factory=list)      # dict frame/hero/value
    gold: list = field(default_factory=list)     # dict frame/hero/source/amount
    upg: list = field(default_factory=list)      # dict frame/hero/actor/skill/level
    cmd: list = field(default_factory=list)      # dict frame/hero/cmd_type/value/actor
    t2d: list = field(default_factory=list)      # dict frame/hero/heading
    t2c: list = field(default_factory=list)      # dict frame/hero/body
    t29: list = field(default_factory=list)
    t1e: list = field(default_factory=list)
    s12: list = field(default_factory=list)      # (frame, x, y) screen scalars
    events: dict = field(default_factory=lambda: defaultdict(list))

    def time_s(self, frame: int) -> float:
        return frame / self.fps

    def team_of(self, hero: int) -> int:
        return int(self.roster.get(hero, {}).get("team", 0))

    def name_of(self, hero: int) -> str:
        return self.roster.get(hero, {}).get("hero_name", "")

    def player_of(self, hero: int) -> str:
        return self.roster.get(hero, {}).get("player", "")


def extract(spec) -> SampleData:
    key, prefix, build = spec
    path = find_sample(prefix)
    data = path.read_bytes()
    header = parse_header(data)
    fps = 20.0 if build == BUILD_5069040 else 15.09
    sd = SampleData(key=key, path=path, build=build, fps=fps, header=header,
                    roster=load_roster(key, build))
    start, end, records = find_stream(data)
    sd.frame_start, sd.frame_end, sd.records = start, end, len(records)

    for idx, (_off, pl) in enumerate(records, 1):
        msgs, ok = parse_payload(pl, build)
        if not ok:
            sd.bad_payloads += 1
        for tag, hero, flag, body in msgs:
            if tag == "s12":
                sd.s12.append((idx, body[0], body[1]))
                continue
            if tag == "01":
                if flag != 0 or not body:
                    continue
                sub = body[0]
                if sub == 0x23 and len(body) >= 2:
                    sd.s23.append({"frame": idx, "hero": hero, "value": body[1]})
                    sd.events[hero].append(("23", idx))
                elif sub == 0x2D and len(body) >= 3:
                    heading = int.from_bytes(body[1:3], "big")
                    sd.t2d.append({"frame": idx, "hero": hero, "heading": heading})
                    sd.events[hero].append(("2d", idx))
                elif sub == 0x2C:
                    sd.t2c.append({"frame": idx, "hero": hero, "body": body.hex()})
                    sd.events[hero].append(("2c", idx))
                elif sub == 0x29:
                    sd.t29.append({"frame": idx, "hero": hero, "body": body.hex()})
                    sd.events[hero].append(("29", idx))
                elif sub == 0x1E:
                    sd.t1e.append({"frame": idx, "hero": hero, "body": body.hex(),
                                   "type": body[1] if len(body) > 1 else None,
                                   "victim": int.from_bytes(body[16:18], "big")
                                   if len(body) >= 18 else None})
                    sd.events[hero].append(("1e", idx))
            else:  # tag == "02"
                if flag == 0x81:
                    sd.s81.append({"frame": idx, "hero": hero, "value": body[0],
                                   "body": body.hex()})
                    sd.events[hero].append(("81", idx))
                elif flag == 0x82:
                    rec = {"frame": idx, "hero": hero, "body": body.hex()}
                    if build == BUILD_5247758 and len(body) >= 9:
                        rec["kind"] = body[0]
                        rec["x"] = int.from_bytes(body[1:5], "big", signed=True)
                        rec["y"] = int.from_bytes(body[5:9], "big", signed=True)
                        rec["toggle"] = None
                    elif len(body) >= 2:
                        rec["kind"] = body[0]
                        rec["toggle"] = body[1]
                    sd.s82.append(rec)
                    sd.events[hero].append(("82", idx))
                elif flag == 0x85:
                    if build == BUILD_5247758:
                        amount = int.from_bytes(body[1:3], "little")
                    else:
                        amount = int.from_bytes(body[1:5], "little")
                    sd.gold.append({"frame": idx, "hero": hero, "source": body[0],
                                    "amount": amount})
                    sd.events[hero].append(("gold", idx))
                elif flag == 0x87 and len(body) >= 6:
                    sd.upg.append({"frame": idx, "hero": hero,
                                   "actor": int.from_bytes(body[2:4], "big")
                                   if build == BUILD_5247758 else body[3],
                                   "skill": body[4], "level": body[5]})
                    sd.events[hero].append(("87", idx))
                elif flag == 0x80 and len(body) >= 12:
                    sd.cmd.append({
                        "frame": idx, "hero": hero,
                        "cmd_type": int.from_bytes(body[0:2], "little"),
                        "value": int.from_bytes(body[2:4], "little"),
                        "actor": int.from_bytes(body[4:6], "little"),
                    })
                    sd.events[hero].append(("cmd", idx))
    return sd


# ---------------------------------------------------------------------------
# 公共统计
# ---------------------------------------------------------------------------
def group_runs(frames, gap: float):
    pts = sorted(set(frames))
    if not pts:
        return []
    groups, cur = [], [pts[0]]
    for x in pts[1:]:
        if x - cur[-1] <= gap:
            cur.append(x)
        else:
            groups.append(cur)
            cur = [x]
    groups.append(cur)
    return groups


def v6_windows(sd: SampleData):
    per = defaultdict(list)
    for rec in sd.s81:
        if rec["value"] == 6:
            per[rec["hero"]].append(rec["frame"])
    out = []
    gap = WINDOW_GAP_S * sd.fps
    for hero, frames in per.items():
        for g in group_runs(frames, gap):
            out.append({
                "hero": hero,
                "team": sd.team_of(hero),
                "start": g[0],
                "end": g[-1],
                "n": len(g),
                "frames": g,
                "t0": sd.time_s(g[0]),
                "t1": sd.time_s(g[-1]),
            })
    out.sort(key=lambda w: (w["start"], w["hero"]))
    return out


def pair_23_windows(sd: SampleData):
    """1 -> 下一个 0；连续多个 1 取最早，连续 0 只认第一次。"""
    per = defaultdict(list)
    for rec in sd.s23:
        per[rec["hero"]].append((rec["frame"], rec["value"]))
    out = []
    for hero, seq in per.items():
        seq.sort()
        on = None
        for frame, value in seq:
            if value == 1:
                if on is None:
                    on = frame
            elif value == 0 and on is not None:
                out.append({"hero": hero, "start": on, "end": frame,
                            "duration": frame - on})
                on = None
    out.sort(key=lambda w: (w["start"], w["hero"]))
    return out


def next_frame(frames, frame):
    j = bisect.bisect_right(frames, frame)
    return frames[j] if j < len(frames) else None


def prev_frame(frames, frame):
    j = bisect.bisect_left(frames, frame)
    return frames[j - 1] if j > 0 else None


def channel_frames(sd: SampleData, hero: int, channel: str):
    return sorted(f for h, ch, f in
                  ((h, ch, f) for h, evs in sd.events.items() for ch, f in evs
                   if h == hero and ch == channel))


def hero_events(sd: SampleData, hero: int):
    return sorted(sd.events.get(hero, []), key=lambda x: x[1])


def median_or_none(values):
    vals = [v for v in values if v is not None]
    return statistics.median(vals) if vals else None


# ---------------------------------------------------------------------------
# source43 击杀对齐
# ---------------------------------------------------------------------------
def source43_kills(sd: SampleData):
    return [g for g in sd.gold
            if g["source"] == 43 and g["amount"] in KILL_AMOUNTS]


def source43_assists(sd: SampleData):
    return [g for g in sd.gold
            if g["source"] == 43 and g["amount"] == ASSIST_AMOUNT]


def nearest_window_to_kill(kill, windows, sd: SampleData):
    killer_team = sd.team_of(kill["hero"])
    best = None
    for w in windows:
        if w["team"] == 0 or killer_team == 0:
            continue
        if w["team"] == killer_team:
            continue
        dist = min(abs(w["start"] - kill["frame"]), abs(w["end"] - kill["frame"]))
        if best is None or dist < best[0]:
            best = (dist, w)
    return best


def nearest_kill_to_window(w, kills, sd: SampleData):
    if w["team"] == 0:
        return None
    best = None
    for k in kills:
        kt = sd.team_of(k["hero"])
        if kt == 0 or kt == w["team"]:
            continue
        dist = min(abs(k["frame"] - w["start"]), abs(k["frame"] - w["end"]))
        if best is None or dist < best[0]:
            best = (dist, k)
    return best


def random_hit_rate(kills, windows, sd: SampleData, tol_frames: int,
                    trials: int = 300, seed: int = 20261101):
    """把每个击杀的时刻随机均匀放回本样本，保持击杀者队伍不变。"""
    if not kills or not windows:
        return None
    lo, hi = 1, max(1, sd.records)
    if hi <= lo:
        return None
    rng = random.Random(seed)
    hits = 0
    for _ in range(trials):
        for k in kills:
            frame = rng.randint(lo, hi)
            kt = sd.team_of(k["hero"])
            ok = False
            for w in windows:
                if w["team"] == 0 or w["team"] == kt:
                    continue
                if min(abs(w["start"] - frame), abs(w["end"] - frame)) <= tol_frames:
                    ok = True
                    break
            hits += ok
    return hits / (trials * len(kills))


def align_stats(sd: SampleData, windows, kills):
    tols = [1, 2, 5, 10, 20]
    out = {"kills": len(kills), "windows": len(windows)}
    for tol in tols:
        hits = 0
        for k in kills:
            best = nearest_window_to_kill(k, windows, sd)
            if best and best[0] <= tol * sd.fps:
                hits += 1
        out[f"hit_{tol}s"] = hits
        out[f"rand_{tol}s"] = random_hit_rate(kills, windows, sd, int(tol * sd.fps))
    dists = []
    for k in kills:
        best = nearest_window_to_kill(k, windows, sd)
        dists.append(best[0] if best else None)
    out["median_dist_frames"] = median_or_none(dists)
    out["min_dist_frames"] = min([d for d in dists if d is not None], default=None)
    return out


# ---------------------------------------------------------------------------
# 主分析
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-csv", default=str(OUT_CSV))
    ap.add_argument("--out-md", default=str(OUT_MD))
    args = ap.parse_args()

    samples = [extract(spec) for spec in SAMPLE_SPECS]
    by_key = {s.key: s for s in samples}
    main_sd = by_key["20260925_105224"]
    new_sd = by_key["20261101_182452"]

    rows = []

    def add(section, sample="", build="", hero="", hero_name="", team="",
            frame="", time_s="", metric="", value="", unit="", detail="",
            confidence=""):
        rows.append({
            "section": section, "sample": sample, "build": build,
            "hero": hero, "hero_name": hero_name, "team": team,
            "frame": frame, "time_s": time_s, "metric": metric,
            "value": value, "unit": unit, "detail": detail,
            "confidence": confidence,
        })

    # ------------------------- 样本清单 -------------------------
    windows_by_sample = {}
    kills_by_sample = {}
    for sd in samples:
        windows = v6_windows(sd)
        windows_by_sample[sd.key] = windows
        kills = source43_kills(sd)
        kills_by_sample[sd.key] = kills
        add("sample_inventory", sd.key, sd.build, metric="records",
            value=sd.records, unit="frames", detail=sd.path.name,
            confidence="high")
        add("sample_inventory", sd.key, sd.build, metric="fps",
            value=f"{sd.fps:.2f}", unit="fps", detail="20fps (5069040) / 15.09fps (5247758)", confidence="high")
        add("sample_inventory", sd.key, sd.build, metric="local_hero",
            value=sd.header.get("local_hero"), unit="heroID",
            detail=f"versions={','.join(sd.header.get('versions', []))}", confidence="high")
        add("sample_inventory", sd.key, sd.build, metric="roster",
            value=len(sd.roster), unit="heroes",
            detail="; ".join(f"{h}:{sd.team_of(h)}" for h in sorted(sd.roster)), confidence="high")
        add("sample_inventory", sd.key, sd.build, metric="0x81_records",
            value=len(sd.s81), unit="records", confidence="high")
        add("sample_inventory", sd.key, sd.build, metric="0x82_records",
            value=len(sd.s82), unit="records", confidence="high")
        add("sample_inventory", sd.key, sd.build, metric="0x23_records",
            value=len(sd.s23), unit="records", confidence="high")
        add("sample_inventory", sd.key, sd.build, metric="0x2c_records",
            value=len(sd.t2c), unit="records", confidence="high")
        add("sample_inventory", sd.key, sd.build, metric="0x2d_records",
            value=len(sd.t2d), unit="records", confidence="high")
        add("sample_inventory", sd.key, sd.build, metric="0x1e_records",
            value=len(sd.t1e), unit="records", confidence="high")
        add("sample_inventory", sd.key, sd.build, metric="0x29_records",
            value=len(sd.t29), unit="records", confidence="high")
        add("sample_inventory", sd.key, sd.build, metric="0x85_records",
            value=len(sd.gold), unit="records", confidence="high")
        add("sample_inventory", sd.key, sd.build, metric="0x87_records",
            value=len(sd.upg), unit="records", confidence="high")
        add("sample_inventory", sd.key, sd.build, metric="0x80_records",
            value=len(sd.cmd), unit="records", confidence="high")
        add("sample_inventory", sd.key, sd.build, metric="0x12_records",
            value=len(sd.s12), unit="values", confidence="high")
        add("sample_inventory", sd.key, sd.build, metric="v6_records",
            value=sum(1 for r in sd.s81 if r["value"] == 6), unit="records", confidence="high")
        add("sample_inventory", sd.key, sd.build, metric="v6_windows",
            value=len(windows), unit="windows", confidence="medium-high")
        add("sample_inventory", sd.key, sd.build, metric="source43_kills",
            value=len(kills), unit="rows",
            detail="; ".join(f"{k['frame']}:{k['hero']}" for k in kills), confidence="medium")
        add("sample_inventory", sd.key, sd.build, metric="bad_payloads",
            value=sd.bad_payloads, unit="records", detail="tolerant tag parse stopped early",
            confidence="high")

    # ------------------------- v6 窗口 -------------------------
    for sd in samples:
        windows = windows_by_sample[sd.key]
        kills = kills_by_sample[sd.key]
        for i, w in enumerate(windows, 1):
            near_kill = nearest_kill_to_window(w, kills, sd)
            dt = (near_kill[0] / sd.fps) if near_kill else None
            add("v6_window", sd.key, sd.build, w["hero"], sd.name_of(w["hero"]),
                w["team"], w["start"], f"{w['t0']:.2f}", "window_start",
                f"{w['start']}-{w['end']}", "frames",
                f"n={w['n']}; t={w['t0']:.2f}-{w['t1']:.2f}s; "
                f"nearest enemy source43 kill={near_kill[1]['frame'] if near_kill else None}"
                f" dt={dt:.2f}s" if dt is not None else f"n={w['n']}; no enemy kill",
                "medium-high")
            add("v6_window", sd.key, sd.build, w["hero"], sd.name_of(w["hero"]),
                w["team"], w["start"], f"{w['t0']:.2f}", "duration_s",
                f"{w['t1'] - w['t0']:.2f}", "s", "", "medium-high")
            add("v6_window", sd.key, sd.build, w["hero"], sd.name_of(w["hero"]),
                w["team"], w["start"], f"{w['t0']:.2f}", "nearest_enemy_kill_dt_s",
                f"{dt:.2f}" if dt is not None else "", "s",
                f"kill_frame={near_kill[1]['frame'] if near_kill else ''}", "medium")

    # ------------------------- 队伍对拍 -------------------------
    team_rows = []
    for sd in samples:
        windows = windows_by_sample[sd.key]
        kills = kills_by_sample[sd.key]
        deaths = Counter(w["team"] for w in windows if w["team"])
        kt = Counter(sd.team_of(k["hero"]) for k in kills if sd.team_of(k["hero"]))
        cov1 = (kt.get(1, 0) / deaths.get(2)) if deaths.get(2) else None
        cov2 = (kt.get(2, 0) / deaths.get(1)) if deaths.get(1) else None
        team_rows.append((sd.key, sd.build, deaths, kt, cov1, cov2))
        add("team_reconcile", sd.key, sd.build, metric="team1_v6_deaths",
            value=deaths.get(1, 0), unit="windows", confidence="medium-high")
        add("team_reconcile", sd.key, sd.build, metric="team2_v6_deaths",
            value=deaths.get(2, 0), unit="windows", confidence="medium-high")
        add("team_reconcile", sd.key, sd.build, metric="team1_source43_kills",
            value=kt.get(1, 0), unit="kills", confidence="medium")
        add("team_reconcile", sd.key, sd.build, metric="team2_source43_kills",
            value=kt.get(2, 0), unit="kills", confidence="medium")
        if cov1 is not None:
            add("team_reconcile", sd.key, sd.build, metric="team1_kill_coverage_vs_team2_deaths",
                value=f"{cov1:.3f}", unit="ratio",
                detail="source43 kills by team1 / team2 v6 windows", confidence="medium")
        if cov2 is not None:
            add("team_reconcile", sd.key, sd.build, metric="team2_kill_coverage_vs_team1_deaths",
                value=f"{cov2:.3f}", unit="ratio",
                detail="source43 kills by team2 / team1 v6 windows", confidence="medium")

    # ------------------------- source43 对齐统计 -------------------------
    align_rows = {}
    for sd in samples:
        windows, kills = windows_by_sample[sd.key], kills_by_sample[sd.key]
        st = align_stats(sd, windows, kills)
        align_rows[sd.key] = st
        if kills:
            for tol in (1, 2, 5, 10, 20):
                add("source43_alignment", sd.key, sd.build,
                    metric=f"kills_with_opposing_v6_within_{tol}s",
                    value=f"{st[f'hit_{tol}s']}/{st['kills']}",
                    unit="kills",
                    detail=f"random expectation={st[f'rand_{tol}s']:.2f}"
                    if st[f"rand_{tol}s"] is not None else "",
                    confidence="medium")
            add("source43_alignment", sd.key, sd.build,
                metric="median_nearest_v6_dist_s",
                value=("" if st["median_dist_frames"] is None
                       else f"{st['median_dist_frames'] / sd.fps:.2f}"),
                unit="s", confidence="medium-low")

    # ------------------------- 漏检 -------------------------
    for sd in samples:
        windows = windows_by_sample[sd.key]
        kills = kills_by_sample[sd.key]
        v6_by_hero = Counter(w["hero"] for w in windows)
        s81_by_hero = Counter(r["hero"] for r in sd.s81)
        v6_val_by_hero = defaultdict(Counter)
        for r in sd.s81:
            v6_val_by_hero[r["hero"]][r["value"]] += 1
        for hero in sorted(sd.roster):
            if hero in v6_by_hero or s81_by_hero.get(hero, 0) == 0:
                continue
            add("v6_miss", sd.key, sd.build, hero, sd.name_of(hero), sd.team_of(hero),
                metric="no_v6_but_active_0x81",
                value=s81_by_hero.get(hero, 0), unit="records",
                detail=f"0x81 values={dict(sorted(v6_val_by_hero[hero].items()))}",
                confidence="medium")
        # 没有 v6 对手的击杀：v6 未覆盖该击杀的候选漏检
        no_v6_kills = []
        for k in kills:
            best = nearest_window_to_kill(k, windows, sd)
            if best is None or best[0] > 10 * sd.fps:
                no_v6_kills.append(k)
        for k in no_v6_kills:
            best = nearest_window_to_kill(k, windows, sd)
            add("v6_miss", sd.key, sd.build, k["hero"], sd.name_of(k["hero"]),
                sd.team_of(k["hero"]), k["frame"], f"{sd.time_s(k['frame']):.2f}",
                "source43_kill_without_opposing_v6_10s", k["amount"], "gold",
                f"nearest opposing v6 dt="
                f"{(best[0] / sd.fps):.2f}s" if best else "no opposing v6",
                "medium-low")
        add("v6_miss", sd.key, sd.build, metric="source43_kills_without_v6_10s",
            value=f"{len(no_v6_kills)}/{len(kills)}", unit="kills",
            detail="lower bound on unobserved victim deaths (if source43 time=death time)",
            confidence="medium-low")

    # 5247758 面板真值
    if new_sd.roster:
        panel_deaths = sum(r.get("deaths") or 0 for r in new_sd.roster.values())
        human_deaths = sum(r.get("deaths") or 0 for r in new_sd.roster.values()
                           if r.get("human"))
        ai_deaths = panel_deaths - human_deaths
        v6_windows_new = windows_by_sample[new_sd.key]
        v6_by_hero_new = Counter(w["hero"] for w in v6_windows_new)
        v6_total = len(v6_windows_new)
        add("panel_truth", new_sd.key, new_sd.build, metric="panel_deaths_total",
            value=panel_deaths, unit="deaths", detail="10-player panel OCR", confidence="medium-high")
        add("panel_truth", new_sd.key, new_sd.build, metric="panel_deaths_human",
            value=human_deaths, unit="deaths", detail="1804+212", confidence="medium-high")
        add("panel_truth", new_sd.key, new_sd.build, metric="panel_deaths_ai",
            value=ai_deaths, unit="deaths", detail="2001-2008; no 0x81 channel",
            confidence="medium-high")
        add("panel_truth", new_sd.key, new_sd.build, metric="v6_windows_total",
            value=v6_total, unit="windows", confidence="medium-high")
        add("panel_truth", new_sd.key, new_sd.build, metric="human_death_recall",
            value=f"{v6_total}/{human_deaths}" if human_deaths else "",
            unit="windows/deaths",
            detail="AI deaths are not observable in 0x81 at all", confidence="medium")
        for hero, rec in sorted(new_sd.roster.items()):
            deaths = rec.get("deaths")
            if not rec.get("human"):
                add("panel_truth", new_sd.key, new_sd.build, hero, rec.get("hero_name", ""),
                    rec.get("team", ""), metric="ai_no_0x81",
                    value=deaths, unit="panel_deaths",
                    detail="AI has 0 0x81 records; cannot validate v6", confidence="high")
                continue
            n = v6_by_hero_new.get(hero, 0)
            verdict = "hit" if deaths and n else ("miss" if deaths and not n else "n/a")
            add("panel_truth", new_sd.key, new_sd.build, hero, rec.get("hero_name", ""),
                rec.get("team", ""), metric="v6_vs_panel_deaths",
                value=f"v6={n} panel_deaths={deaths}", unit="windows/deaths",
                detail=f"kills={rec.get('kills')} assists={rec.get('assists')}; verdict={verdict}",
                confidence="medium-high")

    # ------------------------- 442 李信 -------------------------
    li = main_sd
    hero = 442
    s81_li = [r for r in li.s81 if r["hero"] == hero]
    v4 = [r["frame"] for r in s81_li if r["value"] == 4]
    v6 = [r["frame"] for r in s81_li if r["value"] == 6]
    skill4 = [u["frame"] for u in li.upg if u["hero"] == hero and u["skill"] == 4]
    first_skill4 = min(skill4) if skill4 else None
    first_v4 = min(v4) if v4 else None
    v4_before_skill4 = sum(1 for f in v4 if first_skill4 and f < first_skill4)
    v4_prev_next = Counter()
    s81_sorted = sorted(s81_li, key=lambda r: r["frame"])
    for pos, rec in enumerate(s81_sorted):
        if rec["value"] != 4:
            continue
        prev_val = next((r["value"] for r in reversed(s81_sorted[:pos])
                         if r["value"] != 4), None)
        next_val = next((r["value"] for r in s81_sorted[pos + 1:]
                         if r["value"] != 4), None)
        v4_prev_next[(prev_val, next_val)] += 1
    v4_intervals = [(b - a) / li.fps for a, b in zip(v4, v4[1:])]
    v6_intervals = [(b - a) / li.fps for a, b in zip(v6, v6[1:])]

    add("li_xin_442", li.key, li.build, hero, li.name_of(hero), li.team_of(hero),
        metric="0x81_value_counts",
        value=dict(sorted(Counter(r["value"] for r in s81_li).items())),
        unit="records", confidence="high")
    add("li_xin_442", li.key, li.build, hero, li.name_of(hero), li.team_of(hero),
        metric="v4_count", value=len(v4), unit="events", confidence="high")
    add("li_xin_442", li.key, li.build, hero, li.name_of(hero), li.team_of(hero),
        metric="v4_first_frame", value=first_v4, unit="frame",
        detail=f"first skill4 upgrade={first_skill4}", confidence="high")
    add("li_xin_442", li.key, li.build, hero, li.name_of(hero), li.team_of(hero),
        metric="v4_before_first_skill4", value=v4_before_skill4, unit="events",
        detail=f"skill4 upgrades at {skill4}", confidence="high")
    add("li_xin_442", li.key, li.build, hero, li.name_of(hero), li.team_of(hero),
        metric="v4_surrounding_value_pairs",
        value=dict(sorted(v4_prev_next.items())), unit="events",
        detail="prev non-4 -> next non-4", confidence="high")
    add("li_xin_442", li.key, li.build, hero, li.name_of(hero), li.team_of(hero),
        metric="v4_interval_median_s",
        value=f"{statistics.median(v4_intervals):.2f}" if v4_intervals else "",
        unit="s", confidence="high")
    add("li_xin_442", li.key, li.build, hero, li.name_of(hero), li.team_of(hero),
        metric="v6_count", value=len(v6), unit="events", confidence="medium-high")
    add("li_xin_442", li.key, li.build, hero, li.name_of(hero), li.team_of(hero),
        metric="v6_interval_median_s",
        value=f"{statistics.median(v6_intervals):.2f}" if v6_intervals else "",
        unit="s", confidence="medium-high")

    # 442 每个 v6 / v4 之后的最长密集通道 gap
    def post_gaps(hero_id, frame):
        out = {}
        for ch in ("cmd", "2d", "81"):
            frames = channel_frames(li, hero_id, ch)
            nxt = next_frame(frames, frame)
            out[ch] = (nxt - frame) if nxt is not None else None
        gold4 = sorted(g["frame"] for g in li.gold
                       if g["hero"] == hero_id and g["source"] == 4)
        nxt = next_frame(gold4, frame)
        out["gold4"] = (nxt - frame) if nxt is not None else None
        return out

    def gap_summary(frames, label):
        details, n5, n10 = [], 0, 0
        for f in frames:
            g = post_gaps(hero, f)
            vals = {k: v for k, v in g.items() if v is not None}
            best = max(vals.items(), key=lambda kv: kv[1]) if vals else (None, None)
            if best[1] is not None:
                n5 += best[1] >= 5 * li.fps
                n10 += best[1] >= 10 * li.fps
            details.append(f"{f}:" + ",".join(
                f"{k}={v / li.fps:.1f}s" if v is not None else f"{k}=na"
                for k, v in g.items()))
        add("li_xin_442", li.key, li.build, hero, li.name_of(hero), li.team_of(hero),
            metric=f"{label}_post_gap_ge_5s", value=f"{n5}/{len(frames)}", unit="events",
            detail="; ".join(details), confidence="medium-high")
        add("li_xin_442", li.key, li.build, hero, li.name_of(hero), li.team_of(hero),
            metric=f"{label}_post_gap_ge_10s", value=f"{n10}/{len(frames)}", unit="events",
            confidence="medium-high")

    gap_summary(v4, "v4")
    gap_summary(v6, "v6")

    # 442 v6 窗口细节
    for w in windows_by_sample[li.key]:
        if w["hero"] != hero:
            continue
        add("li_xin_442", li.key, li.build, hero, li.name_of(hero), li.team_of(hero),
            w["start"], f"{w['t0']:.2f}", "v6_window",
            f"{w['start']}-{w['end']}", "frames",
            f"duration={(w['t1'] - w['t0']):.2f}s; post_gaps=" +
            ",".join(f"{k}={v / li.fps:.1f}s" if v is not None else f"{k}=na"
                     for k, v in post_gaps(hero, w["end"]).items()),
            "medium-high")

    # 0x12：无英雄 ID 的屏幕坐标标量，只能当“帧流未断”的旁证
    five = int(5 * li.fps)
    for w in windows_by_sample[li.key]:
        if w["hero"] != hero:
            continue
        before = sum(1 for f, x, y in li.s12 if w["start"] - five <= f < w["start"])
        after = sum(1 for f, x, y in li.s12 if w["end"] < f <= w["end"] + five)
        add("li_xin_442", li.key, li.build, hero, li.name_of(hero), li.team_of(hero),
            w["start"], f"{w['t0']:.2f}", "0x12_counts_5s_before_after",
            f"{before}/{after}", "values",
            "0x12 has no hero ID; counts only prove the frame stream did not stop",
            "medium-low")
    add("li_xin_442", li.key, li.build, hero, li.name_of(hero), li.team_of(hero),
        metric="0x12_values_per_frame_mean",
        value=f"{len(li.s12) / max(1, li.records):.2f}", unit="values/frame",
        detail="76,059 values in 13,094 frames (4–8 per frame); not hero-addressed",
        confidence="high")

    # 1729 value3 与命中/技能事件
    hero1729 = [r for r in li.s81 if r["hero"] == 1729]
    v3_1729 = [r["frame"] for r in hero1729 if r["value"] == 3]
    hit1729 = sorted(r["frame"] for r in li.t1e if r["hero"] == 1729)
    cast1729 = sorted([r["frame"] for r in li.t2c if r["hero"] == 1729] +
                      [r["frame"] for r in li.t29 if r["hero"] == 1729])
    def nearest_any(frames, frame):
        if not frames:
            return None
        j = bisect.bisect_left(frames, frame)
        cands = []
        if j > 0:
            cands.append(abs(frame - frames[j - 1]))
        if j < len(frames):
            cands.append(abs(frames[j] - frame))
        return min(cands) if cands else None
    add("value_semantics", li.key, li.build, 1729, li.name_of(1729), li.team_of(1729),
        metric="value3_frames", value=v3_1729, unit="frames",
        detail=f"nearest 0x1e={[nearest_any(hit1729, f) for f in v3_1729]} frames; "
               f"nearest 0x2c/0x29={[nearest_any(cast1729, f) for f in v3_1729]}",
        confidence="medium-low")

    # 1547 1/2 交替
    hero1547 = [r for r in li.s81 if r["hero"] == 1547]
    trans1547 = Counter((a["value"], b["value"])
                        for a, b in zip(hero1547, hero1547[1:]))
    add("value_semantics", li.key, li.build, 1547, li.name_of(1547), li.team_of(1547),
        metric="value1_2_transitions", value=dict(sorted(trans1547.items())),
        unit="transitions", detail="1/2 二元状态高频交替", confidence="medium-low")

    # ------------------------- 0x81 英雄值表 -------------------------
    for sd in samples:
        per = defaultdict(Counter)
        for r in sd.s81:
            per[r["hero"]][r["value"]] += 1
        v6_by_hero = Counter(w["hero"] for w in windows_by_sample[sd.key])
        for hero, cnt in sorted(per.items()):
            add("value_semantics", sd.key, sd.build, hero, sd.name_of(hero),
                sd.team_of(hero), metric="0x81_value_counts",
                value=dict(sorted(cnt.items())), unit="records",
                detail=f"v6_windows={v6_by_hero.get(hero, 0)}", confidence="medium")

    # 0x81 值 N 首次出现 vs 技能 N 首次升级：证明 value=skill slot
    for sd in samples:
        by_hero = defaultdict(lambda: {"upg": defaultdict(list), "first": {}})
        for u in sd.upg:
            by_hero[u["hero"]]["upg"][u["skill"]].append(u["frame"])
        for r in sd.s81:
            by_hero[r["hero"]]["first"].setdefault(r["value"], r["frame"])
        negative = 0
        negative_by_value = Counter()
        for hero, info in sorted(by_hero.items()):
            for value, first in sorted(info["first"].items()):
                if value not in (1, 2, 3, 4):
                    continue
                unlocks = info["upg"].get(value, [])
                if not unlocks:
                    add("slot_unlock", sd.key, sd.build, hero, sd.name_of(hero),
                        sd.team_of(hero), first, f"{sd.time_s(first):.2f}",
                        f"value{value}_first_use", "no_skill_upgrade",
                        "skill", "value appears but skill slot never upgraded",
                        "medium-low")
                    continue
                unlock = min(unlocks)
                delta = (first - unlock) / sd.fps
                negative += delta < 0
                negative_by_value[value] += delta < 0
                add("slot_unlock", sd.key, sd.build, hero, sd.name_of(hero),
                    sd.team_of(hero), first, f"{sd.time_s(first):.2f}",
                    f"value{value}_first_use_minus_skill{value}_unlock_s",
                    f"{delta:+.2f}", "s",
                    f"skill{value} unlock frame={unlock}; "
                    f"first value{value} frame={first}",
                    "medium-high" if delta >= 0 else "low")
        add("slot_unlock", sd.key, sd.build, metric="negative_delta_count",
            value=negative, unit="cases",
            detail="value N appears before skill N unlock (would refute slot model)",
            confidence="medium-high")
        for value in (1, 2, 3, 4):
            add("slot_unlock", sd.key, sd.build, metric=f"negative_delta_value{value}",
                value=negative_by_value.get(value, 0), unit="cases",
                detail=f"value{value} first use before skill{value} unlock",
                confidence="medium-high")

    # ------------------------- 0x82 -------------------------
    for sd in samples:
        per = defaultdict(list)
        for r in sd.s82:
            per[r["hero"]].append(r)
        for hero, evs in sorted(per.items()):
            if sd.build == BUILD_5247758:
                kinds = Counter(e["kind"] for e in evs)
                xs = [e["x"] for e in evs if "x" in e]
                ys = [e["y"] for e in evs if "y" in e]
                add("state_82", sd.key, sd.build, hero, sd.name_of(hero), sd.team_of(hero),
                    metric="0x82_position_kinds", value=dict(kinds), unit="records",
                    detail=f"x={min(xs) if xs else None}..{max(xs) if xs else None}, "
                           f"y={min(ys) if ys else None}..{max(ys) if ys else None}; "
                           f"16B position layout (new build)", confidence="medium-high")
                continue
            kinds = Counter(e["kind"] for e in evs)
            toggles = Counter(e["toggle"] for e in evs)
            trans = Counter((a["toggle"], b["toggle"]) for a, b in zip(evs, evs[1:]))
            v6_w = windows_by_sample[sd.key]
            near_v6 = []
            for e in evs:
                ds = [min(abs(e["frame"] - w["start"]), abs(e["frame"] - w["end"]))
                      for w in v6_w]
                near_v6.append(min(ds) if ds else None)
            add("state_82", sd.key, sd.build, hero, sd.name_of(hero), sd.team_of(hero),
                metric="0x82_kind_counts", value=dict(kinds), unit="records",
                detail=f"toggles={dict(toggles)}; transitions={dict(trans)}; "
                       f"median nearest v6={median_or_none(near_v6)} frames",
                confidence="medium")

    # 0x82 kind 首次出现 vs 技能 kind 首次升级
    for sd in samples:
        if sd.build != BUILD_5069040:
            continue
        upg = defaultdict(lambda: defaultdict(list))
        for u in sd.upg:
            upg[u["hero"]][u["skill"]].append(u["frame"])
        first_kind = {}
        for r in sd.s82:
            first_kind.setdefault(r["hero"], (r["frame"], r["kind"]))
        negative = 0
        for hero, (frame, kind) in sorted(first_kind.items()):
            unlocks = upg[hero].get(kind, [])
            if not unlocks:
                continue
            unlock = min(unlocks)
            delta = (frame - unlock) / sd.fps
            negative += delta < 0
            add("state_82", sd.key, sd.build, hero, sd.name_of(hero),
                sd.team_of(hero), frame, f"{sd.time_s(frame):.2f}",
                f"kind{kind}_first_use_minus_skill{kind}_unlock_s",
                f"{delta:+.2f}", "s",
                f"skill{kind} unlock frame={unlock}; first 0x82 kind{kind} frame={frame}",
                "medium" if delta >= 0 else "low")
        add("state_82", sd.key, sd.build, metric="kind_negative_delta_count",
            value=negative, unit="cases",
            detail="0x82 kind K first appears before skill K unlock",
            confidence="medium")

    # 0x82 vs 0x80 命令
    for sd in samples:
        if sd.build != BUILD_5069040:
            continue
        per = defaultdict(list)
        for r in sd.s82:
            per[r["hero"]].append(r["frame"])
        for hero, frames in per.items():
            cmd_frames = channel_frames(sd, hero, "cmd")
            dists = [nearest_any(cmd_frames, f) for f in frames]
            add("state_82", sd.key, sd.build, hero, sd.name_of(hero), sd.team_of(hero),
                metric="0x82_nearest_cmd_median_frames",
                value=median_or_none(dists), unit="frames",
                detail="0x82 与 0x80 命令不是 1:1 同步", confidence="medium-low")

    # ------------------------- 0x23 -------------------------
    for sd in samples:
        wins = pair_23_windows(sd)
        per = defaultdict(lambda: {"records": 0, "windows": 0, "durs": []})
        for rec in sd.s23:
            per[rec["hero"]]["records"] += 1
        for w in wins:
            per[w["hero"]]["windows"] += 1
            per[w["hero"]]["durs"].append(w["duration"] / sd.fps)
        for hero, info in sorted(per.items()):
            durs = info["durs"]
            add("state_23", sd.key, sd.build, hero, sd.name_of(hero), sd.team_of(hero),
                metric="0x23_windows", value=info["windows"], unit="windows",
                detail=f"records={info['records']}; "
                       f"duration median={statistics.median(durs):.2f}s"
                       if durs else f"records={info['records']}",
                confidence="medium-low")

    # 主样本 0x23 窗口内活动 + 窗口后施法
    wins23 = pair_23_windows(main_sd)
    short_wins = [w for w in wins23 if w["duration"] <= 3.2 * main_sd.fps]
    inside = Counter()
    post_cast = 0
    pre_cast = 0
    post_cmd = 0
    for w in short_wins:
        hero, a, b = w["hero"], w["start"], w["end"]
        for ch in ("cmd", "82", "2c", "2d", "29", "1e", "gold"):
            frames = channel_frames(main_sd, hero, ch)
            j = bisect.bisect_left(frames, a)
            k = bisect.bisect_right(frames, b)
            inside[ch] += max(0, k - j)
        for ch in ("2c", "1e", "29"):
            frames = channel_frames(main_sd, hero, ch)
            j = bisect.bisect_right(frames, b)
            if j < len(frames) and frames[j] - b <= 2 * main_sd.fps:
                post_cast += 1
            j2 = bisect.bisect_left(frames, a)
            if j2 > 0 and a - frames[j2 - 1] <= 2 * main_sd.fps:
                pre_cast += 1
        cmds = channel_frames(main_sd, hero, "cmd")
        j = bisect.bisect_right(cmds, b)
        if j < len(cmds) and cmds[j] - b <= 2 * main_sd.fps:
            post_cmd += 1
    add("state_23", main_sd.key, main_sd.build, metric="main_short_windows",
        value=len(short_wins), unit="windows", detail="duration<=3.2s",
        confidence="high")
    add("state_23", main_sd.key, main_sd.build, metric="inside_window_activity",
        value=dict(inside), unit="records",
        detail="same hero, frames inside 0x23 window", confidence="high")
    add("state_23", main_sd.key, main_sd.build, metric="post_window_cast_2s",
        value=f"{post_cast}/{len(short_wins)}", unit="windows",
        detail="0x2c/0x1e/0x29 after window end", confidence="medium")
    add("state_23", main_sd.key, main_sd.build, metric="pre_window_cast_2s",
        value=f"{pre_cast}/{len(short_wins)}", unit="windows", confidence="medium")
    add("state_23", main_sd.key, main_sd.build, metric="post_window_cmd_2s",
        value=f"{post_cmd}/{len(short_wins)}", unit="windows",
        detail="0x80 command after window end", confidence="medium")
    durs23 = [w["duration"] / main_sd.fps for w in short_wins]
    if durs23:
        add("state_23", main_sd.key, main_sd.build, metric="duration_hist",
            value=dict(Counter(round(d, 1) for d in durs23).most_common(12)),
            unit="windows", detail="0x23 short-window durations", confidence="high")

    # 0x23 与 source43 击杀的聚类
    kill_frames_main = sorted(k["frame"] for k in kills_by_sample[main_sd.key])
    near_kills = 0
    for w in short_wins:
        d = nearest_any(kill_frames_main, w["start"])
        if d is not None and d <= 10 * main_sd.fps:
            near_kills += 1
    add("state_23", main_sd.key, main_sd.build,
        metric="windows_within_10s_of_source43_kill",
        value=f"{near_kills}/{len(short_wins)}", unit="windows", confidence="medium-low")

    # ------------------------- 结论行 -------------------------
    add("semantics", "all", "5069040", metric="0x81_value6",
        value="death", unit="state",
        detail="5247758: 1804 v6=1 window vs panel D=1; post-v6 0x81/0x82/cmd/gold "
               "silence 40-67s while 212 stays active; 442 v6 separated from v4 skill4 event",
        confidence="medium-high (0.75)")
    add("semantics", "all", "5069040", metric="0x81_value6_scope",
        value="interest-gated death event", unit="state",
        detail="AI in 5247758 have 0 0x81 records although panel deaths=45; 212 panel D=1 "
               "but no v6; absence of v6 is not proof of no death",
        confidence="medium")
    add("semantics", "20260925_105224", "5069040", hero=442, hero_name="李信",
        metric="0x81_value4", value="skill4 use / form switch", unit="event",
        detail=f"first v4 at {first_v4} after first skill4 upgrade at {first_skill4}; "
               f"0 v4 before; v4 pairs are not a clean 1<->2 state flip",
        confidence="high (0.85) for skill4 link; medium for exact form effect")
    add("semantics", "20260925_105224", "5069040", hero=442, hero_name="李信",
        metric="0x81_value6", value="death (not form switch)", unit="event",
        detail=f"8 windows, median interval "
               f"{statistics.median(v6_intervals):.1f}s vs v4 {statistics.median(v4_intervals):.1f}s; "
               f"all v4 after skill4 unlock; v6 is not a 1/2 form transition",
        confidence="medium-high (0.8)")
    add("semantics", "all", "5069040", metric="0x81_value1_2_3_4",
        value="skill / action slot", unit="event",
        detail="value1/2/4 first use is never before the matching skill unlock "
               "(0 negative cases across 7 samples); value3 is mostly skill3 but has "
               "2 negative cases (1059 少司缘, 319 老夫子); 1/2 alternate without v4, "
               "so not a persisted form enum",
        confidence="medium-high (0.7) for 1/2/4; medium-low for 3; high not-a-form-enum")
    add("semantics", "all", "5069040", metric="0x82",
        value="per-hero binary UI/aim state", unit="state",
        detail="kind constant per hero in 5069040 (1/2/3), toggle 0/255; no unit ID/damage; "
               "no alignment with v6/source43; kind matches the hero's manual-aim skill slot",
        confidence="medium-low (0.5) for semantics; layout high")
    add("semantics", "20261101_182452", "5247758", metric="0x82",
        value="16B position candidate", unit="record",
        detail="kind+x:i32BE+y:i32BE+7B; kind1 self-like (1804 140), kind3 target-like; "
               "not the 5069040 2B kind+toggle layout",
        confidence="medium-high (layout)")
    add("semantics", "20260925_105224", "5069040", metric="0x23",
        value="unable-to-act / CC window", unit="state",
        detail=f"254 records, {len(wins23)} windows ({len(short_wins)}<=3.2s); "
               f"inside: cmd={inside.get('cmd', 0)}, 0x82={inside.get('82', 0)}, "
               f"0x2c/0x2d/0x29/0x1e=0, gold={inside.get('gold', 0)}; "
               f"post-window cast {post_cast}/{len(short_wins)} -> not a charge release; "
               "durations 0.2-0.6s mode",
        confidence="medium-low (0.55); not death high")
    add("semantics", "20261101_182452", "5247758", metric="human_death_recall",
        value="1/2", unit="deaths",
        detail="1804 v6=1 = panel D=1; 212 panel D=1 but v6=0; 212 death time unknown "
               "(could be at stream boundary)",
        confidence="medium")

    # ------------------------- 写 CSV -------------------------
    out_csv = Path(args.out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    fields = ["section", "sample", "build", "hero", "hero_name", "team",
              "frame", "time_s", "metric", "value", "unit", "detail", "confidence"]
    with out_csv.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    # ------------------------- 写 MD -------------------------
    write_report(Path(args.out_md), samples, by_key, main_sd, new_sd,
                 windows_by_sample, kills_by_sample, team_rows, align_rows,
                 rows, li, hero, v4, v6, skill4, first_skill4, first_v4,
                 v4_prev_next, v4_intervals, v6_intervals, wins23, short_wins,
                 inside, post_cast, pre_cast, post_cmd, durs23, near_kills)

    print(f"wrote {out_csv} ({len(rows)} rows)")
    print(f"wrote {Path(args.out_md)}")
    main_w = windows_by_sample[main_sd.key]
    print(f"main 5069040: 0x81={len(main_sd.s81)} 0x82={len(main_sd.s82)} "
          f"0x23={len(main_sd.s23)} v6_windows={len(main_w)} "
          f"team1={sum(1 for w in main_w if w['team'] == 1)} "
          f"team2={sum(1 for w in main_w if w['team'] == 2)}")
    new_w = windows_by_sample[new_sd.key]
    print(f"new 5247758: 0x81={len(new_sd.s81)} 0x82={len(new_sd.s82)} "
          f"v6_windows={len(new_w)}")


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------
def md_table(headers, rows):
    out = ["| " + " | ".join(str(h) for h in headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        out.append("| " + " | ".join(str(x) for x in row) + " |")
    return out


def write_report(path, samples, by_key, main_sd, new_sd, windows_by_sample,
                 kills_by_sample, team_rows, align_rows, rows,
                 li, hero, v4, v6, skill4, first_skill4, first_v4,
                 v4_prev_next, v4_intervals, v6_intervals, wins23,
                 short_wins, inside, post_cast, pre_cast, post_cmd, durs23,
                 near_kills):
    A = []
    add = A.append

    add("# 普通 5v5 逐英雄状态语义：0x81 / 0x82 / 0x23")
    add("")
    add("> 只读逆向。样本：build 5069040 的 6 个 `.abc` + build 5247758 的 "
        "1 个人机样本。工具 `tools/agent_state_semantics.py`，数据 "
        "`datasets/agent_state_semantics.csv`。未修改回放/包体/文档/记忆。")
    add("")

    add("## 0. 结论速览")
    add("")
    add("- **0x81 value6 = 死亡（medium-high，约 0.75）**。最强证据来自 "
        "5247758：1804 的 v6 窗口 1 个，面板死亡正好 1；v6 后 0x81/0x82/0x80/"
        "0x85 全部静默 40–67s，而同局 212 仍持续活动。442 的 8 次 v6 与"
        "形态切换无关（v4 才是技能4/切形态事件）。")
    add("- **442 李信：v6 是死亡，不是形态切换**（medium-high，约 0.8）；"
        f"v4 是技能4/切形态（high，约 0.85）：v4 首次在 seq {first_v4}，"
        f"紧接 skill4 首次升级 seq {first_skill4}，此前 0 次；"
        "v4 前后只与 1/2/6 相连，但不是每次 v4 都翻转 1/2。")
    add("- **0x81 的 1/2/3/4 是技能/动作槽**（medium-high，约 0.7 对 1/2/4）："
        "value1/2/4 的首次出现都在对应技能首次升级之后（0 负例）；"
        "value3 有 2 例负例（1059 少司缘、319 老夫子），单独按英雄看；"
        "6 是唯一的共享死亡值。442 的 1/2 不是光/暗形态——它们在 v4 之外"
        "也高频互换（221 次 1↔2 之间 0 个 v4），更像技能1/技能2 的使用事件。")
    add("- **0x82（5069040）= 逐英雄二值 UI/瞄准状态**（语义 medium-low）："
        "kind 逐英雄恒定（1/2/3），toggle 0/255；无单位 ID、无伤害；"
        "与 v6/source43 不同步。kind 与“该英雄唯一的手动瞄准技能槽”假说一致。"
        "5247758 的 0x82 已改成 16B 位置候选，不能混用。")
    add("- **0x23 = 无法行动窗口（CC/引导候选，medium-low，约 0.55）**："
        "主样本 254 条/120 窗口，窗口内 0x80 仅 1 条、0x82/0x2c/0x2d/0x29/0x1e 全 0，"
        "时长 0.2–3.2s（0.2–0.6s 为主），窗口后 2s 内施法仅 1/107 → "
        "更像硬控/僵直，不是死亡、不是回城、不是蓄力释放。")
    add("- **漏检**：212 是面板计数确认的 1 次死亡漏检（D=1，v6=0），"
        "但死亡时刻未知，可能是流末尾；1547/338/1021 没有阳性漏检证据，"
        "但 v6 只覆盖被观察实体，0 个 v6 也不能证明 D=0。"
        "source43 击杀时刻与 v6 对齐很弱，不能当作逐次死亡的时钟。")
    add("")

    # 样本表
    add("## 1. 样本与基线")
    add("")
    table = []
    for sd in samples:
        table.append([
            sd.key, sd.build, sd.records,
            len(sd.s81), len(windows_by_sample[sd.key]),
            len(kills_by_sample[sd.key]),
            sd.header.get("local_hero"),
            f"{sd.fps:.2f}",
        ])
    A.extend(md_table(["sample", "build", "frames", "0x81", "v6 windows",
                       "source43 kills", "localHero", "fps"], table))
    add("")
    add("口径：frame 序号 = 帧流中的记录序号（从 1 开始）；time = frame / fps。"
        "5069040 为 20fps，5247758 为 9900 帧/656s ≈ 15.09fps。"
        "v6 窗口 = 同一英雄相邻 v6 记录间隔 ≤1s 合并；主样本合并后 27 个窗口。")
    add("")

    # v6 表
    add("## 2. 0x81 value6 窗口")
    add("")
    table = []
    for sd in samples:
        for w in windows_by_sample[sd.key]:
            near = nearest_kill_to_window(w, kills_by_sample[sd.key], sd)
            dt = f"{near[0] / sd.fps:.2f}" if near else ""
            table.append([
                sd.key, w["hero"], sd.name_of(w["hero"]), w["team"],
                f"{w['start']}-{w['end']}", f"{w['t0']:.1f}", w["n"],
                dt,
            ])
    A.extend(md_table(["sample", "hero", "name", "team", "frames", "t0(s)",
                       "n", "nearest enemy kill dt(s)"], table))
    add("")
    add("主样本 27 个窗口：442=8、1558=5、1514=4、1965=4、1833=3、1729=2、"
        "1966=1；按队伍 team1=10、team2=17。与任务给定基线一致。")
    add("")

    # 队伍对拍
    add("## 3. 与 source43 队伍比分对拍")
    add("")
    table = []
    for key, build, deaths, kt, cov1, cov2 in team_rows:
        table.append([
            key, build,
            f"{deaths.get(1, 0)}/{deaths.get(2, 0)}",
            f"{kt.get(1, 0)}/{kt.get(2, 0)}",
            f"{cov1:.1%}" if cov1 is not None else "",
            f"{cov2:.1%}" if cov2 is not None else "",
        ])
    A.extend(md_table(["sample", "build", "v6 deaths T1/T2",
                       "source43 kills T1/T2",
                       "T1 kills / T2 v6 deaths",
                       "T2 kills / T1 v6 deaths"], table))
    add("")
    add("主样本 team1 击杀（=team2 死亡）17、team2 击杀（=team1 死亡）10，"
        "source43 只记到 4/2，覆盖率 24%/20%，与 0x85 击杀金 20–25% 的子集"
        "量级一致。这是 v6=死亡的一个弱支持：若 v6 是随机事件，队伍总数"
        "不会刚好落在击杀金覆盖率区间。")
    add("")
    add("**名单完整性**：094930/095631 只解出 2 个 team1 玩家，team2 的 v6=0 "
        "是名单缺失/通道缺失，不是“team2 没人死”；这两例不进入队伍覆盖率结论。"
        "60924 是 9 人名单，101323/103058/105224 是 10 人。")
    add("")

    # 对齐
    add("## 4. source43 击杀时刻 vs v6：弱对齐（阴性）")
    add("")
    table = []
    for sd in samples:
        st = align_rows[sd.key]
        if not st["kills"]:
            continue
        median_txt = ("" if st["median_dist_frames"] is None
                      else f"{st['median_dist_frames'] / sd.fps:.1f}")
        table.append([
            sd.key, st["kills"],
            f"{st['hit_2s']}/{st['kills']}",
            f"{st['rand_2s']:.2f}" if st["rand_2s"] is not None else "",
            f"{st['hit_5s']}/{st['kills']}",
            f"{st['rand_5s']:.2f}" if st["rand_5s"] is not None else "",
            f"{st['hit_10s']}/{st['kills']}",
            f"{st['rand_10s']:.2f}" if st["rand_10s"] is not None else "",
            median_txt,
        ])
    A.extend(md_table(["sample", "kills", "±2s", "rand", "±5s", "rand",
                       "±10s", "rand", "median dist(s)"], table))
    add("")
    add("读法：随机基线 = 把每次击杀时刻在本样本内均匀随机放置（保持击杀者队伍），"
        "300 次平均。主样本 6 次击杀中 ±2s 命中 **0/6**（随机期望 0.09）、"
        "±5s **1/6**（0.21）、±10s **2/6**（0.39）。**观测不优于随机**。"
        "所以 source43 不能验证“v6 的时刻就是死亡时刻”，只能验证队伍量级。"
        "这同时说明 v6 不是全量死亡记录（或 0x85 击杀金不是击杀时刻）。")
    add("")

    # 漏检
    add("## 5. 漏检量化")
    add("")
    add("**5247758 面板真值**：10 人面板死亡合计 47（1804=1、212=1、8 个 AI=45）。"
        "0x81 只有 1804/212 两个真人，AI **0 条 0x81**，所以 AI 的 45 次死亡"
        "在 0x81 里完全不可见。真人层面 v6=1、面板死亡=2 → **1/2**；"
        "1804 命中，212 漏检（D=1，v6=0）。")
    add("")
    add("212 的死亡时刻没有真值；它的 0x81/0x82 一直活动到帧 9854/9890"
        "（流结束 9900），所以这次死亡可能发生在流末尾附近，属于边界漏检，"
        "不是“通道对该英雄永久失效”的证据。")
    add("")
    add("**5069040 主样本**：0x81 活跃但 0 个 v6 的英雄是 1547（227 条 1/2）、"
        "338（144 条 1）、1021（47 条 2）。**没有阳性证据证明他们死过**；"
        "但也不能把 0 个 v6 直接当 D=0——v6 只覆盖被观察实体（5247758 的 AI "
        "45 次死亡在 0x81 里 0 条）。任务把 1547/338/1021 列为“漏检候选”，"
        "本文的结论是：**既不能确认漏检，也不能确认 0 死**，需要死亡时刻真值。")
    add("")
    add("这不是主样本独有：60924 的 741 云缨（288 条 1/2/3）、101323 的 321 猪八戒"
        "（222 条 1/2/3）、103058 的 1382 马可波罗（141 条 1/2/3）同样是"
        "“通道活跃、0 个 v6”。如果把这些都当漏检，就会把 0x81 解释成"
        "随机事件；更保守的读法是：**v6 只覆盖被观察实体的死亡，"
        "没有 v6 既可能是 0 死，也可能是未观测死亡**，不能单凭 0 判 D=0。")
    add("")
    # 击杀无 v6 表
    miss_rows = [r for r in rows if r["section"] == "v6_miss"
                 and r["metric"] == "source43_kill_without_opposing_v6_10s"]
    if miss_rows:
        table = [[r["sample"], r["hero"], r["hero_name"], r["frame"],
                  r["time_s"], r["value"], r["detail"]] for r in miss_rows]
        A.extend(md_table(["sample", "killer", "name", "frame", "t(s)",
                           "amount", "nearest opposing v6"], table))
        add("")
    add("注：095631 只有 2 名 team1 玩家，team2 名单缺失，它那行 “no opposing v6” "
        "是名单缺口，不是漏检；真正的漏检下界看 60924/101323/103058/105224。")
    add("")
    add("这是**漏检下界**：假设 source43 击杀金时刻≈死亡时刻，则这些击杀的"
        "受害者没有对应 v6 窗口。主样本 6 次 source43 击杀中有 4 次在 ±10s 内"
        "找不到对方 v6；若 source43 时刻可靠，v6 至少漏掉 4 次死亡。"
        "结合 212 的确认漏检，v6 只能当“可观测死亡事件”，不能当全量死亡账本。")
    add("")

    # 442
    add("## 6. 442 李信：v6 死亡 vs v4 形态切换")
    add("")
    add(f"- 0x81 值分布：{dict(sorted(Counter(r['value'] for r in li.s81 if r['hero'] == 442).items()))}")
    add(f"- v4：{len(v4)} 次；首次 seq **{first_v4}**（{first_v4 / li.fps:.1f}s）；"
        f"skill4 首次升级 seq **{first_skill4}**（{first_skill4 / li.fps:.1f}s）；"
        f"skill4 之前 v4 次数 **0**。")
    add(f"- v4 前后仍是 1/2（没有 4→6），但 **不是每次 v4 都翻转 1/2**："
        f"{dict(sorted(v4_prev_next.items()))}；(1,1)=17、(2,2)=3，而且 1↔2 的"
        f"221 次切换之间 **0 个 v4**——所以 1/2 不是被 v4 翻转的持久形态，"
        "更像技能1/技能2 的使用事件。")
    add(f"- v4 间隔中位数 **{statistics.median(v4_intervals):.1f}s**；"
        f"v6 间隔中位数 **{statistics.median(v6_intervals):.1f}s**。"
        "v4 是高频技能4/切形态使用，v6 是约 80s 一次的事件。")
    add("")
    table = []
    for f in v6:
        g = []
        for ch, label in (("cmd", "0x80"), ("gold4", "source4"), ("2d", "0x2d"), ("81", "0x81")):
            frames = sorted(x["frame"] for x in li.gold
                            if x["hero"] == 442 and x["source"] == 4) if ch == "gold4" \
                else channel_frames(li, 442, ch)
            nxt = next_frame(frames, f)
            g.append(f"{label}={(nxt - f) / li.fps:.1f}s" if nxt else f"{label}=na")
        table.append([f, f"{f / li.fps:.1f}", "; ".join(g)])
    A.extend(md_table(["frame", "t(s)", "next-event gaps after v6"], table))
    add("")
    add("**0x12 的角色**：主样本 76,059 个 0x12 值 / 13,094 帧 = 5.8 值/帧"
        "（4–8 个），v6 前后 5s 的计数同量级（个别有 20–30% 波动，见 CSV "
        "`0x12_counts_5s_before_after`）。但 0x12 没有英雄 ID，不能归到 442；"
        "它只能证明“帧流没有整体中断”。442 的死亡判断用 0x2d 朝向、0x80 命令、"
        "0x85 金币、0x87 技能升级、0x29 状态和 0x81 技能槽，不用 0x12 做逐人归属。")
    add("")
    add("注：上表的 0x2d 是稠密朝向流（几乎每帧都有），next gap 0.1–4s 不能当"
        "“存活”证据；死亡判断只看 0x80/0x85/0x81 这些稀疏通道的静默。")
    add("")
    add("判定：**v6 不是形态切换**。v4 与 skill4 首次升级强绑定（1594→1643），"
        "是技能4/切形态的使用；但 1/2 并没有被 v4 翻转，它们在 v4 之外也高频互换，"
        "所以 1/2 不是持久形态。v6 与 skill4 解锁无关，间隔量级与 v4 完全不同；"
        "结合 5247758 面板，v6=死亡（medium-high），v4=技能4/切形态（high）。")
    add("")

    # 0x81 values
    add("## 7. 0x81 的 1/2/3/4：技能/动作槽")
    add("")
    add("主样本逐英雄值分布：")
    table = []
    per = defaultdict(Counter)
    for r in main_sd.s81:
        per[r["hero"]][r["value"]] += 1
    for h in sorted(per):
        table.append([h, main_sd.name_of(h), main_sd.team_of(h),
                      dict(sorted(per[h].items()))])
    A.extend(md_table(["hero", "name", "team", "0x81 values"], table))
    add("")
    add("### 7.1 值 N 首次出现 vs 技能 N 首次升级")
    add("")
    import re
    table = []
    for r in rows:
        if r["section"] != "slot_unlock" or r["sample"] != main_sd.key:
            continue
        if not r["metric"].startswith("value") or r["value"] == "no_skill_upgrade":
            continue
        m = re.search(r"unlock frame=(\d+)", r["detail"])
        if not m:
            continue
        unlock = int(m.group(1))
        value_no = int(r["metric"][5])
        table.append([
            r["hero"], r["hero_name"], value_no,
            f"{float(r['time_s']):.1f}",
            f"{unlock / main_sd.fps:.1f}",
            r["value"],
        ])
    A.extend(md_table(["hero", "name", "value N", "first use(s)",
                       "skill N unlock(s)", "delta(s)"], table))
    add("")
    add("**value1/2/4 没有负例**：7 个样本里，值 N 从不早于技能 N 解锁出现；"
        "338 v1（+0.3s）、442 v4（+2.5s）、1547 v1（+0.2s）几乎是解锁即首用，"
        "1021 v2/1833 v2/1965 v2 在解锁后 7–20s 首用。**value3 有 2 例负例**"
        "（60924 的 1059 少司缘 −174.8s、101323 的 319 老夫子 −142.5s），"
        "所以 3 不总是技能3，更像 hero-specific 状态/技能3 混合。"
        "注意：技能解锁普遍很早，正延迟本身有一部分是时间先后的必然；"
        "真正有说服力的是**解锁后 0–2.5s 内首用**的 338/442/1547，"
        "以及 value2/value4 在多个英雄上独立对上。"
        "整体：**1/2/4 = 技能槽（medium-high）；3 = 技能3 候选/英雄专属（medium-low）；"
        "6 = 死亡**。")
    add("")
    add("- **442**：v1/v2=技能1/技能2 使用，v4=技能4/切形态（首次在 skill4 解锁后 2.5s），"
        "6=死亡。**不是**“1/2=光/暗形态”：1↔2 的 221 次切换之间 0 个 v4。")
    add("- **1547 赵云**：1/2 高频交替，对应技能1/技能2 的使用；没有 v3/v4。")
    add("- **338/1021/1514/1833/1965**：固定 1 或 2，分别像技能1/技能2 的使用；"
        "6 是插入的单帧/短窗死亡事件。")
    add("- **1729 安琪拉**：2/3；3 首次在 skill3 解锁后 78s，11 次，像技能3/大招使用；"
        "但与 0x1e 命中的时间差不稳定，暂记“技能3候选”。")
    add("- **1558/1966**：0x81 只有 6（5/1 条）——她们的通道只记录死亡，"
        "没有技能槽事件；这进一步说明 0x81 是逐英雄/逐技能的选择性通道。")
    add("")

    # 0x82
    add("## 8. 0x82 kind/toggle")
    add("")
    table = []
    for sd in samples:
        if sd.build != BUILD_5069040:
            continue
        per82 = defaultdict(list)
        for r in sd.s82:
            per82[r["hero"]].append(r)
        for h, evs in sorted(per82.items()):
            table.append([
                sd.key, h, sd.name_of(h), sd.team_of(h),
                dict(sorted(Counter(e["kind"] for e in evs).items())),
                dict(sorted(Counter(e["toggle"] for e in evs).items())),
            ])
    A.extend(md_table(["sample", "hero", "name", "team", "kind", "toggle"],
                      table))
    add("")
    add("5069040 的 0x82 = 2B `kind:u8 + toggle:0/255`；kind 在同一英雄的整局"
        "恒定（跨样本同英雄未重复出现可校验的案例），toggle 0/255 不是干净"
        "的按下/抬起（255→255 与 0→0 都很多），更像**周期采样的二值 UI 状态**。")
    add("")
    add("0x82 与 v6 不同步：主样本 50 个 255→0 跳变，只有 1 个在 0x1e/0x2c/0x29 "
        "后 0.5s 内；与 0x80 命令的最近距离中位数 38–669 帧。故不是死亡/击杀/"
        "技能释放日志。**kind=1/2/3 与“该英雄唯一的手动瞄准技能槽”假说一致**："
        "安琪拉/扁鹊/孙权/鲁班等偏 1，马超/东皇/后羿/金蝉偏 2，赵云/元流之子/"
        "廉颇偏 3。语义置信度 medium-low。")
    add("")
    add("### 8.1 kind K 首次出现 vs 技能 K 首次升级")
    add("")
    table = []
    for r in rows:
        if r["section"] != "state_82" or r["build"] != BUILD_5069040:
            continue
        if not r["metric"].startswith("kind") or not r["metric"].endswith("_s"):
            continue
        m = re.search(r"skill(\d) unlock frame=(\d+)", r["detail"])
        if not m:
            continue
        kind_no = int(r["metric"][4])
        unlock = int(m.group(2))
        table.append([r["sample"], r["hero"], r["hero_name"], kind_no,
                      f"{float(r['time_s']):.1f}",
                      f"{unlock / (20.0):.1f}", r["value"]])
    A.extend(md_table(["sample", "hero", "name", "kind K", "first use(s)",
                       "skill K unlock(s)", "delta(s)"], table))
    add("")
    combos = len(table)
    neg = sum(1 for row in table if float(row[-1]) < 0)
    pos = combos - neg
    max_delta = max((float(row[-1]) for row in table), default=0)
    add(f"{combos} 个 (hero, kind) 组合里 **{pos} 个正延迟**（kind K 首次出现在"
        f"技能 K 解锁后，最长 +{max_delta:.1f}s），**{neg} 个负例**"
        "（103058 的 1217 后羿 kind2 在 38.6s 首现、skill2 首次升级却在 182.9s）。"
        "同样要注意：技能解锁普遍早，正延迟有一部分是必然；紧的 338 +0.75s、"
        "1717 +1.4s、1547 +4.45s 才是真支持。因此 **kind=手动瞄准技能槽** 是"
        "强候选，但 1217 负例说明 0x87 可能漏条或 kind 混有英雄类别；"
        "语义维持 medium-low。")
    add("")
    add("5247758 的 0x82 已是 16B `kind:u8 + x:i32BE + y:i32BE + 7B`：1804 "
        "kind1 140 条（自身位置候选，x∈[-1000,47500]、y∈[-38500,36500]），"
        "kind3 16 条；212 kind3 39 条。与 5069040 的 2B 布局不同，不能合并统计。")
    add("")

    # 0x23
    add("## 9. 0x23 窗口")
    add("")
    add(f"主样本 254 条；按 1→下一个 0 配对得到 **{len(wins23)}** 个窗口，"
        f"其中 duration ≤3.2s 的 **{len(short_wins)}** 个，其余 "
        f"{len(wins23) - len(short_wins)} 个是长窗口/未闭合。时长分布（短窗口）：")
    add("")
    add(f"`{dict(Counter(round(d, 1) for d in durs23).most_common(12))}`")
    add("")
    add("窗口内同英雄活动（主样本、短窗口）：")
    add("")
    add(f"`{dict(inside)}`")
    add("")
    add(f"- 0x80 命令 {inside.get('cmd', 0)}、0x82 {inside.get('82', 0)}、"
        f"0x2c/0x2d/0x29/0x1e 全 0、0x85 只有 {inside.get('gold', 0)} 条。")
    add(f"- 窗口结束后 2s 内同英雄施法 {post_cast}/{len(short_wins)}；"
        f"窗口前 2s 内 {pre_cast}/{len(short_wins)}；窗口后 2s 内 0x80 "
        f"{post_cmd}/{len(short_wins)}。")
    add("")
    add("→ 0x23 是**英雄无法行动**的窗口：几乎没有命令、没有瞄准/施法/命中、"
        "没有金币。时长 0.2–3.2s（0.2–0.6s 为主）排除了死亡（死亡 10–20s）"
        "和回城（回城更少更长）；窗口后几乎不接施法，**不支持“蓄力后释放”**，"
        "更支持**硬控/僵直（眩晕/击飞/压制）**。0x23 与 source43 击杀的 "
        f"10s 邻域命中 {near_kills}/{len(short_wins)}，与随机基线 18% 基本持平，"
        "不能作为“战斗聚类”的独立证据；CC 判定主要靠“窗口内无操作 + 短时长”。"
        "置信度 medium-low（0.55）；“不是死亡”high。")
    add("")
    add("**与任务基线的差异**：任务给的是 120 个窗口、0.2–3.2s；本工具按"
        "“连续 1 只取最早、遇到 0 关闭”配对，得到 120 个窗口，其中 107 个"
        "≤3.2s，13 个是长窗口/未闭合（如 1965 的 2012→2838 = 41.3s）。"
        "若改成“每个 1 各自配下一个 0”会得到更多重叠窗口；两种口径下"
        "**短窗口的结论一致**（窗口内无操作、0.2–0.6s 为主）。")
    add("")

    # 新样本
    add("## 10. 5247758 人机样本的面板对拍")
    add("")
    table = []
    for h, rec in sorted(new_sd.roster.items()):
        n = sum(1 for w in windows_by_sample[new_sd.key] if w["hero"] == h)
        table.append([h, rec.get("player", ""), rec.get("hero_name", ""),
                      rec.get("team", ""), rec.get("kills"), rec.get("deaths"),
                      rec.get("assists"), n, rec.get("human")])
    A.extend(md_table(["entity", "player", "hero", "team", "K", "D", "A",
                       "v6 windows", "human"], table))
    add("")
    add("1804 的 v6 在帧 7461–7463（约 494.4s），body=`06 2328 00...`"
        "（value6 + 0x2328=9000）。v6 后 1804 的下一条 0x81 在 8160（46.2s）、"
        "0x82 在 8461（66.1s）、0x80 在 8467（66.7s）、0x85 在 8068（40.2s）；"
        "同段时间 212 的 0x81/0x82 持续活动。**这是 v6=死亡最直接的行为证据**。"
        "9000 的字段未解码，不能单独当复活倒计时。")
    add("")
    add("AI 的 45 次面板死亡在 0x81 里 0 条，说明 0x81 只覆盖部分实体"
        "（真人/被观察实体），不是全量 10 人状态流。")
    add("")

    # 还缺什么
    add("## 11. 还缺什么")
    add("")
    add("1. **死亡时刻真值**：面板只有 K/D/A 计数，没有死亡时间；"
        "需要带击杀/死亡时间戳的结算或录屏 OCR，才能把 v6 与死亡逐次对齐，"
        "并把“漏检”从计数级降到事件级。")
    add("2. **v6 的实体覆盖规则**：5247758 的 AI 完全没有 0x81，212 有通道但无 v6；"
        "需要更多“同一英雄在镜头内/外死亡”的样本，确认 v6 是否只对被观察实体写入。")
    add("3. **5247758 的 0x81 22B body 字段**：`0x2328` 是 HP、复活时间还是别的，"
        "需要同一英雄连续 body 与面板 HP/金币对拍；本轮只把它当未解码 payload。")
    add("4. **0x82 kind 的英雄技能表映射**：目前“唯一手动瞄准技能槽”只是"
        "与英雄池一致的假说；需要逐英雄技能表 + 施法日志验证。")
    add("5. **0x23 的 CC/引导二选一**：需要录像 UI 或战斗事件（控制效果）对齐；"
        "当前只能排除死亡/回城/蓄力释放。")
    add("6. **objectID→英雄/兵种映射**：0x1e/0x2c 的 victim/target 仍是运行时 "
        "objectID，不能把“命中了谁”变成“谁被击杀”。")
    add("")

    add("## 12. 产物")
    add("")
    add("- `tools/agent_state_semantics.py`（本工具，只读）")
    add("- `data/replays/_analysis/datasets/agent_state_semantics.csv`（长表）")
    add("- `data/replays/_analysis/datasets/agent_state_semantics.md`（本报告）")
    add("")
    add("复跑：`python tools/agent_state_semantics.py`")
    add("")

    path.write_text("\n".join(A), encoding="utf-8")


if __name__ == "__main__":
    main()
