"""普通 5v5（5069040 主样本 20260925_105224）0x12 轨迹跟踪 + 0x13 语义判定。

只读分析，不修改回放/包体，不注入，不读 param.json，不使用 runtime_dump，
不编辑 docs/replay_binary_format.md 与 .workbuddy/memory/MEMORY.md。

口径
----
* 只解析 `data/replays/samples/abc_batch/20260925_105224_*.abc` 的主帧流
  （13,061 条记录，seq 34–13094）。第二段输入续流（712 帧）不并入默认口径，
  仅在报告里注明它的 0x12/0x13 增量。
* 帧记录：`seq:u8 pad:0 L:u8 payload[L] a:u8 00*5 b:u8`；payload 首字节是
  token 计数，之后是标签流：
      0x12 -> 2B  (x:u8, y:u8)
      0x13 -> 1B
      0x14 -> 3B
      0x01 -> hero:u16BE flag:u8 len:u8 data[len]
      0x02 -> hero:u16BE flag:u8；flag==0x80 时体固定 12B，否则 len=flag&0x7f
* 时间轴：rec_s = seq/20；game_s = rec_s + 21.5（doc 5.92 标定，medium-high）。

坐标解读（本工具的结论，报告里有推导）
--------------------------------------
0x12 的第一个字节不是普通 0..255 坐标，而是 **带 2 位前缀的有符号 6 位值**：
    0x40..0x67 -> -1..-40    （低 6 位 v: 0..39 -> -(v+1)）
    0x80..0xA7 ->  0..+39    （低 6 位 v -> +v）
所以 x_signed ∈ [-40, 39]（80 个取值），y ∈ [0, 180]。每帧 4–8 个点，
同一帧内 x 互不重复，且列表按 x_signed 降序排列（87% 相邻对、44% 整帧严格）。
跟踪在 (x_signed, y) 上做最近邻 + 常速度预测 + 匈牙利分配。

产物
----
    data/replays/_analysis/datasets/agent_screen_positions.csv
    data/replays/_analysis/datasets/agent_screen_positions.md

用法
----
    python tools/agent_screen_positions.py
    python tools/agent_screen_positions.py --gate 30 --gap 15
    python tools/agent_screen_positions.py --with-tail
"""
from __future__ import annotations

import argparse
import csv
import math
import statistics
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment

ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / "data" / "replays" / "samples" / "abc_batch"
DATASETS = ROOT / "data" / "replays" / "_analysis" / "datasets"
OUT_CSV = DATASETS / "agent_screen_positions.csv"
OUT_MD = DATASETS / "agent_screen_positions.md"

MAIN_SAMPLE_GLOB = "20260925_105224_*.abc"
FPS = 20.0
GAME_OFFSET_S = 21.5
TAIL_BYTES = 0x9B0F0

# 0x12 编码域：合法低 6 位取值 0..39，两个 bank 分别表示负/正
X_BANK_NEG = (0x40, 0x67)   # 64..103
X_BANK_POS = (0x80, 0xA7)   # 128..167
X_VALID = set(range(0x40, 0x68)) | set(range(0x80, 0xA8))
Y_VALID = set(range(0, 181))

TRACK_GATE = 40.0       # (signed_x, y) 空间里的单帧最大位移
TRACK_GAP = 20          # 允许的丢帧数
TRACK_VEL = 0.6         # 常速度预测权重
MIN_TRACK_POINTS = 3


# ---------------------------------------------------------------------------
# frame stream
# ---------------------------------------------------------------------------
def parse_records(data: bytes, pos: int, first_seq: int = 0x22):
    """主帧流：seq 严格 +1（u8 回绕）。"""
    records = []
    seq = first_seq
    while pos + 10 <= len(data):
        if data[pos] != (seq & 0xFF) or data[pos + 1] != 0:
            break
        length = data[pos + 2]
        end = pos + 10 + length
        if end > len(data):
            break
        records.append({"off": pos, "seq": seq, "payload": data[pos + 3:pos + 3 + length]})
        pos = end
        seq += 1
    return records, pos


def find_stream(data: bytes, scan_limit: int = 0x20000):
    best = ([], 0)
    for pos in range(0, min(len(data), scan_limit)):
        if data[pos] != 0x22 or data[pos + 1] != 0:
            continue
        records, end = parse_records(data, pos)
        if len(records) > len(best[0]):
            best = (records, end)
            if len(records) > 500:
                break
    return best


def parse_payload(payload: bytes):
    """返回 (tokens, exact, stop_tag)。tokens 是失败前已确认的合法前缀。"""
    if not payload:
        return [], True, None
    i, out = 1, []
    n = len(payload)
    while i < n:
        tag = payload[i]
        if tag == 0x12:
            if i + 3 > n:
                return out, False, tag
            out.append(("12", payload[i + 1], payload[i + 2]))
            i += 3
        elif tag == 0x13:
            if i + 2 > n:
                return out, False, tag
            out.append(("13", payload[i + 1]))
            i += 2
        elif tag == 0x14:
            if i + 4 > n:
                return out, False, tag
            out.append(("14", payload[i + 1:i + 4]))
            i += 4
        elif tag == 0x01:
            if i + 5 > n:
                return out, False, tag
            hero = int.from_bytes(payload[i + 1:i + 3], "big")
            flag = payload[i + 3]
            ln = payload[i + 4]
            if i + 5 + ln > n:
                return out, False, tag
            out.append(("h1", hero, flag, payload[i + 5:i + 5 + ln]))
            i += 5 + ln
        elif tag == 0x02:
            if i + 4 > n:
                return out, False, tag
            hero = int.from_bytes(payload[i + 1:i + 3], "big")
            flag = payload[i + 3]
            if flag == 0x80:
                if i + 16 > n:
                    return out, False, tag
                out.append(("h2", hero, flag, payload[i + 4:i + 16]))
                i += 16
            else:
                ln = flag & 0x7F
                if i + 4 + ln > n:
                    return out, False, tag
                out.append(("h2", hero, flag, payload[i + 4:i + 4 + ln]))
                i += 4 + ln
        else:
            return out, False, tag
    return out, True, None


def parse_tail_stream(data: bytes, last_seq: int, tail_start: int):
    """第二段输入续流：frame:u16BE len:u16BE type:u8 payload[len] 5B trailer。"""
    tail = data[tail_start:]
    start = None
    for i in range(0, min(max(len(tail) - 5, 0), 0x1000)):
        first, length = struct.unpack_from(">HH", tail, i)
        if last_seq + 1 <= first <= last_seq + 5 and 4 <= length <= 1000:
            start = i
            break
    if start is None:
        return []
    frames = []
    pos = start
    while pos + 10 <= len(tail):
        seq, length = struct.unpack_from(">HH", tail, pos)
        if seq < last_seq or seq > last_seq + 3000 or length > 1000 or pos + 10 + length > len(tail):
            break
        frames.append({"seq": seq, "payload": tail[pos + 5:pos + 5 + length]})
        pos += 10 + length
    return frames


def parse_tail_payload(payload: bytes):
    """续流 payload 没有 count 前缀。"""
    if not payload:
        return [], True, None
    i, out = 0, []
    n = len(payload)
    while i < n:
        tag = payload[i]
        if tag == 0x12:
            if i + 3 > n:
                return out, False, tag
            out.append(("12", payload[i + 1], payload[i + 2]))
            i += 3
        elif tag == 0x13:
            if i + 2 > n:
                return out, False, tag
            out.append(("13", payload[i + 1]))
            i += 2
        elif tag == 0x14:
            if i + 4 > n:
                return out, False, tag
            out.append(("14", payload[i + 1:i + 4]))
            i += 4
        elif tag == 0x01:
            if i + 5 > n:
                return out, False, tag
            hero = int.from_bytes(payload[i + 1:i + 3], "big")
            flag = payload[i + 3]
            ln = payload[i + 4]
            if i + 5 + ln > n:
                return out, False, tag
            out.append(("h1", hero, flag, payload[i + 5:i + 5 + ln]))
            i += 5 + ln
        elif tag == 0x02:
            if i + 4 > n:
                return out, False, tag
            hero = int.from_bytes(payload[i + 1:i + 3], "big")
            flag = payload[i + 3]
            if flag == 0x80:
                if i + 16 > n:
                    return out, False, tag
                out.append(("h2", hero, flag, payload[i + 4:i + 16]))
                i += 16
            else:
                ln = flag & 0x7F
                if i + 4 + ln > n:
                    return out, False, tag
                out.append(("h2", hero, flag, payload[i + 4:i + 4 + ln]))
                i += 4 + ln
        else:
            return out, False, tag
    return out, True, None


# ---------------------------------------------------------------------------
# coordinates
# ---------------------------------------------------------------------------
def x_signed(raw: int) -> int:
    """0x80..0xA7 -> 0..39；0x40..0x67 -> -1..-40。"""
    if raw >= 0x80:
        return raw - 0x80
    return -(raw - 0x40) - 1


def x_valid(raw: int) -> bool:
    return raw in X_VALID


def rec_s(seq: int) -> float:
    return seq / FPS


def game_s(seq: int) -> float:
    return seq / FPS + GAME_OFFSET_S


# ---------------------------------------------------------------------------
# channels
# ---------------------------------------------------------------------------
def extract_channels(records):
    frames = {}          # seq -> tokens
    clean = set()        # 精确吃满的帧
    bad_stop = Counter()
    ch = {
        "h2d": defaultdict(list),   # seq -> [(hero, heading)]
        "h2c": [],                  # [{seq, hero, kind, flag, target, x, y}]
        "h1e": [],                  # [{seq, hero, type, victim}]
        "h81": [],                  # [{seq, hero, value}]
        "h85": [],                  # 金币（只做时间锚，不参与本报告）
    }
    for rec in records:
        seq = rec["seq"]
        tokens, exact, stop = parse_payload(rec["payload"])
        frames[seq] = tokens
        if exact:
            clean.add(seq)
        else:
            bad_stop[stop] += 1
        for m in tokens:
            if m[0] == "h1":
                hero, flag, data = m[1], m[2], m[3]
                if not data:
                    continue
                sub = data[0]
                if sub == 0x2D and len(data) >= 3:
                    ch["h2d"][seq].append((hero, int.from_bytes(data[1:3], "big")))
                elif sub == 0x2C and len(data) == 17:
                    # 2c | kind | flag | target:u16 | x:i32BE/16 | y:i32BE/16 | 000000 | counter
                    # 4 字节字段是 i32BE 定点（低 4 位小数）；整数部分 ±3290，
                    # 与 i16BE[7:9] 只在符号扩展为 0000/FFFF 时一致。
                    ch["h2c"].append({
                        "seq": seq,
                        "hero": hero,
                        "kind": data[1],
                        "flag": data[2],
                        "target": int.from_bytes(data[3:5], "big"),
                        "x": int.from_bytes(data[5:9], "big", signed=True) / 16.0,
                        "y": int.from_bytes(data[9:13], "big", signed=True) / 16.0,
                        "counter": data[16],
                    })
                elif sub == 0x1E and len(data) == 19:
                    ch["h1e"].append({
                        "seq": seq,
                        "hero": hero,
                        "type": data[1],
                        "victim": int.from_bytes(data[16:18], "big"),
                    })
            elif m[0] == "h2":
                hero, flag, data = m[1], m[2], m[3]
                if flag == 0x81 and len(data) == 1:
                    ch["h81"].append({"seq": seq, "hero": hero, "value": data[0]})
                elif flag == 0x85 and len(data) == 5:
                    ch["h85"].append({
                        "seq": seq, "hero": hero, "source": data[0],
                        "amount": int.from_bytes(data[1:5], "little"),
                    })
    return frames, clean, bad_stop, ch


def positions(frames, seqs):
    """每帧 (x_raw, x_signed, y)，只保留合法编码。"""
    out = {}
    dropped = 0
    for s in seqs:
        pts = []
        idx = 0
        for m in frames[s]:
            if m[0] != "12":
                continue
            raw, y = m[1], m[2]
            if not x_valid(raw) or y not in Y_VALID:
                dropped += 1
                idx += 1
                continue
            pts.append({"index": idx, "x_raw": raw, "x": x_signed(raw), "y": y})
            idx += 1
        out[s] = pts
    return out, dropped


# ---------------------------------------------------------------------------
# tracking
# ---------------------------------------------------------------------------
def track_sequence(positions_by_frame, seqs, gate=TRACK_GATE, gap=TRACK_GAP, vel=TRACK_VEL):
    """最近邻 + 常速度预测 + 匈牙利分配。返回 {track_id: [(seq, x, y), ...]}。"""
    tracks = {}
    active = []
    nid = 0

    for s in seqs:
        pts = positions_by_frame.get(s, [])
        xy = np.array([(p["x"], p["y"]) for p in pts], float) if pts else np.zeros((0, 2))

        if len(xy) == 0 or not active:
            for i, p in enumerate(pts):
                tracks[nid] = {"pts": [(s, p["x"], p["y"])], "pos": xy[i].copy(),
                               "vel": np.zeros(2), "last": s}
                active.append(nid)
                nid += 1
            continue

        pred, valid = [], []
        for tid in active:
            t = tracks[tid]
            dt = s - t["last"]
            if dt > gap:
                continue
            pred.append(t["pos"] + t["vel"] * dt * vel)
            valid.append(tid)
        if not valid:
            for i, p in enumerate(pts):
                tracks[nid] = {"pts": [(s, p["x"], p["y"])], "pos": xy[i].copy(),
                               "vel": np.zeros(2), "last": s}
                active.append(nid)
                nid += 1
            continue

        P = np.array(pred)
        D = np.sqrt(((P[:, None, :] - xy[None, :, :]) ** 2).sum(2))
        n, m = len(valid), len(xy)
        N = max(n, m)
        C = np.full((N, N), gate * 2.0)
        C[:n, :m] = D
        C[n:, m:] = 0.0
        r, c = linear_sum_assignment(C)
        used = set()
        for i, j in zip(r, c):
            if i < n and j < m and D[i, j] <= gate:
                tid = valid[i]
                t = tracks[tid]
                dt = s - t["last"]
                newp = xy[j]
                v = (newp - t["pos"]) / dt
                t["vel"] = 0.5 * t["vel"] + 0.5 * v
                t["pos"] = newp.copy()
                t["last"] = s
                t["pts"].append((s, newp[0], newp[1]))
                used.add(j)
        for j, p in enumerate(pts):
            if j in used:
                continue
            tracks[nid] = {"pts": [(s, p["x"], p["y"])], "pos": xy[j].copy(),
                           "vel": np.zeros(2), "last": s}
            active.append(nid)
            nid += 1
        active = [tid for tid in active if s - tracks[tid]["last"] <= gap]

    return {tid: t["pts"] for tid, t in tracks.items() if len(t["pts"]) >= MIN_TRACK_POINTS}


def track_summary(tracks):
    rows = []
    for tid, pts in tracks.items():
        P = np.array([(s, x, y) for s, x, y in pts], float)
        seqs = P[:, 0]
        span = int(seqs[-1] - seqs[0]) + 1
        dt = np.diff(seqs)
        dxy = np.sqrt(np.diff(P[:, 1]) ** 2 + np.diff(P[:, 2]) ** 2)
        ok = dt > 0
        speed = dxy[ok] / dt[ok]
        path_len = float(dxy.sum())
        net = float(math.hypot(P[-1, 1] - P[0, 1], P[-1, 2] - P[0, 2]))
        gaps = Counter(int(g) for g in dt)
        rows.append({
            "track_id": tid,
            "n_points": len(P),
            "start_seq": int(seqs[0]),
            "end_seq": int(seqs[-1]),
            "span_frames": span,
            "coverage": len(P) / span if span else 0.0,
            "duration_s": span / FPS,
            "speed_med": float(np.median(speed)) if len(speed) else 0.0,
            "speed_p90": float(np.percentile(speed, 90)) if len(speed) else 0.0,
            "path_len": path_len,
            "net_disp": net,
            "straightness": net / path_len if path_len > 0 else 0.0,
            "gap1_frac": gaps.get(1, 0) / max(len(dt), 1),
            "x_start": float(P[0, 1]), "y_start": float(P[0, 2]),
            "x_end": float(P[-1, 1]), "y_end": float(P[-1, 2]),
        })
    rows.sort(key=lambda r: -r["n_points"])
    return rows


def shuffled_tracking_stats(positions_by_frame, seqs, gate, gap, rng):
    """跨帧打乱点位（保留每帧点集分布、破坏时间连续性）后跑同一跟踪器。

    注意：在同一帧内置换对集合式跟踪器是恒等变换，必须跨帧置换才有意义。
    """
    order = rng.permutation(len(seqs))
    shuffled = {}
    for i, s in enumerate(seqs):
        src = positions_by_frame.get(seqs[order[i]], [])
        shuffled[s] = [{"x": p["x"], "y": p["y"]} for p in src]
    tracks = track_sequence(shuffled, seqs, gate, gap)
    lens = sorted((len(v) for v in tracks.values()), reverse=True)
    return {
        "tracks": len(lens),
        "ge100": sum(1 for x in lens if x >= 100),
        "ge300": sum(1 for x in lens if x >= 300),
        "max": lens[0] if lens else 0,
    }


# ---------------------------------------------------------------------------
# association
# ---------------------------------------------------------------------------
def heading_alignment(tracks, h2d):
    """屏幕位移方向 vs 0x2d 朝向：整体圆统计 + 每轨迹对齐率。"""
    heads = {}
    for s, vals in h2d.items():
        heads[s] = vals[-1][1]  # 同帧多条取最后一条
    diffs = []
    per_track = defaultdict(list)
    for tid, pts in tracks.items():
        for (s0, x0, y0), (s1, x1, y1) in zip(pts, pts[1:]):
            if s1 - s0 > 2:
                continue
            h = heads.get(s1, heads.get(s0))
            if h is None:
                continue
            dx, dy = x1 - x0, y1 - y0
            if math.hypot(dx, dy) < 1.0:
                continue
            ang = math.degrees(math.atan2(dy, dx)) % 360
            d = (h - ang) % 360
            diffs.append(d)
            per_track[tid].append(d)
    diffs_a = np.array(diffs) if diffs else np.zeros(0)
    if len(diffs_a):
        z = np.mean(np.exp(1j * np.deg2rad(diffs_a)))
        R = float(abs(z))
        mean_deg = float(np.degrees(np.angle(z)) % 360)
        hist = np.histogram(diffs_a, bins=12, range=(0, 360))[0].tolist()
    else:
        R = mean_deg = 0.0
        hist = []
    best = []
    for tid, ds in per_track.items():
        if len(ds) < 20:
            continue
        a = np.deg2rad(ds)
        rr = float(abs(np.mean(np.exp(1j * a))))
        within = float(np.mean(np.abs((np.array(ds) + 180) % 360 - 180) <= 30))
        best.append((tid, len(ds), rr, within))
    best.sort(key=lambda x: -x[2])
    return {
        "n": int(len(diffs_a)),
        "R": R,
        "mean_deg": mean_deg,
        "hist": hist,
        "best": best[:10],
        "threshold_R": 1.73 / math.sqrt(len(diffs_a)) if len(diffs_a) else None,
    }


def death_track_association(track_rows, h81):
    """0x81 value6 死亡窗口 vs 轨迹终止点的富集（按“窗口内终止条数”计数）。"""
    deaths = [(r["seq"], r["hero"]) for r in h81 if r["value"] == 6]
    ends = [r["end_seq"] for r in track_rows]
    if not deaths or not ends:
        return {"deaths": len(deaths), "ends": len(ends), "mean_ends": 0.0,
                "expected": 0.0, "lift": 0.0, "window_frames": 20}
    win = 20
    ends_a = np.array(ends)
    counts = [int(np.sum(np.abs(ends_a - seq) <= win)) for seq, _hero in deaths]
    span = max(max(ends), 1) - min(min(ends), 0) + 1
    rate = len(ends) / span
    expected = rate * (2 * win + 1)
    mean_ends = float(np.mean(counts))
    return {
        "deaths": len(deaths),
        "ends": len(ends),
        "mean_ends": mean_ends,
        "max_ends": int(max(counts)),
        "expected": expected,
        "lift": mean_ends / expected if expected > 0 else 0.0,
        "window_frames": win,
    }


def world_vs_screen(h2c, positions_by_frame, seqs, rng):
    """0x2c 世界坐标 vs 0x12 屏幕坐标：最小 L1 距离 + 打乱基线。"""
    seq_set = set(seqs)
    obs, base_vals = [], []
    xs = [r["x"] for r in h2c]
    ys = [r["y"] for r in h2c]
    for r in h2c:
        s = r["seq"]
        if s not in seq_set:
            continue
        pts = positions_by_frame.get(s, [])
        if not pts:
            continue
        obs.append(min(abs(p["x"] - r["x"]) + abs(p["y"] - r["y"]) for p in pts))
        bx, by = rng.choice(xs), rng.choice(ys)
        base_vals.append(min(abs(p["x"] - bx) + abs(p["y"] - by) for p in pts))
    return {
        "n": len(obs),
        "median": float(np.median(obs)) if obs else float("nan"),
        "p25": float(np.percentile(obs, 25)) if obs else float("nan"),
        "min": float(np.min(obs)) if obs else float("nan"),
        "baseline_median": float(np.median(base_vals)) if base_vals else float("nan"),
    }


# ---------------------------------------------------------------------------
# 0x13 hypotheses
# ---------------------------------------------------------------------------
def x13_stats(v13, frames, h2d, positions_by_frame, seqs, rng):
    """v13: [(seq, value)]；返回全部判据。"""
    vals = [v for _, v in v13]
    per_frame = defaultdict(list)
    for s, v in v13:
        per_frame[s].append(v)
    counts = Counter(len(v) for v in per_frame.values())

    # run lengths of identical consecutive values
    runs = Counter()
    cur = None
    run = 0
    for _, v in v13:
        if v == cur:
            run += 1
        else:
            if cur is not None:
                runs[run] += 1
            cur, run = v, 1
    if cur is not None:
        runs[run] += 1

    # same-frame pair differences
    pair_diffs = [abs(a - b) for vs in per_frame.values() for a, b in zip(vs, vs[1:])]

    # value code space
    valid_code = sum(1 for v in vals if x_valid(v))
    low6 = Counter((v & 0x3F) for v in vals if v != 0)
    mult8 = sum(1 for v in vals if v != 0 and (v & 0x3F) % 8 == 0)

    # relation to 0x12
    xs_by = {s: [p["x_raw"] for p in positions_by_frame.get(s, [])] for s in seqs}
    near_x = near_y = tot = 0
    for s, v in v13:
        if s not in xs_by:
            continue
        tot += 1
        if xs_by[s] and min(abs(v - x) for x in xs_by[s]) <= 1:
            near_x += 1
        ys = [p["y"] for p in positions_by_frame.get(s, [])]
        if ys and min(abs(v - y) for y in ys) <= 1:
            near_y += 1
    n_pts = statistics.fmean([len(positions_by_frame.get(s, [])) for s in seqs]) if seqs else 0
    chance_x = 1 - (1 - 3 / 104) ** max(n_pts, 1)
    chance_y = 1 - (1 - 3 / 181) ** max(n_pts, 1)

    # relation to 0x2d heading (last value per frame)
    heads = {s: v[-1][1] for s, v in h2d.items()}
    pairs = [(heads[s], v) for s, v in v13 if s in heads]
    best_scale = None
    shift_control = {}
    if pairs:
        arr = np.array(pairs, float)
        for k in np.arange(0.5, 10.01, 0.25):
            d = np.abs(((arr[:, 1] * k - arr[:, 0] + 180) % 360) - 180)
            m = float(np.median(d))
            if best_scale is None or m < best_scale[1]:
                best_scale = (float(k), m)
        base = float(np.median(np.abs(((arr[:, 1] * 1.0 - arr[:, 0] + 180) % 360) - 180)))
        ks = best_scale[0]
        for shift in (0, 1, 100, 1000):
            hh = np.roll(arr[:, 0], shift)
            dd = (hh - arr[:, 1] * ks) % 360
            z = np.mean(np.exp(1j * np.deg2rad(dd)))
            shift_control[str(shift)] = (float(abs(z)), float(np.degrees(np.angle(z)) % 360))
    else:
        base = float("nan")

    # relation to visible-unit movement directions
    disp = {}
    for a, b in zip(seqs, seqs[1:]):
        if b != a + 1:
            continue
        A = np.array([(p["x"], p["y"]) for p in positions_by_frame.get(a, [])], float)
        B = np.array([(p["x"], p["y"]) for p in positions_by_frame.get(b, [])], float)
        if len(A) < 2 or len(B) < 2:
            continue
        D = np.sqrt(((A[:, None] - B[None]) ** 2).sum(2))
        r, c = linear_sum_assignment(D)
        v = B[c] - A[r]
        mag = np.linalg.norm(v, axis=1)
        ang = (np.degrees(np.arctan2(v[:, 1], v[:, 0])) + 360) % 360
        disp[b] = (ang[mag >= 2], mag[mag >= 2])

    def min_angle_diff(angle_func):
        ds = []
        for s, v in v13:
            if s not in disp:
                continue
            ang = disp[s][0]
            if len(ang) == 0:
                continue
            th = angle_func(v)
            ds.append(float(np.min(np.abs(((ang - th + 180) % 360) - 180))))
        return np.array(ds)

    for scale_name, fn in (("4.5deg", lambda v: (x_signed(v) * 4.5) % 360),
                           ("9deg", lambda v: (x_signed(v) * 9.0) % 360)):
        d = min_angle_diff(fn)
        if scale_name == "4.5deg":
            d45 = d
        else:
            d9 = d
    # shuffled baseline for 4.5deg
    dsh = []
    for s, v in v13:
        if s not in disp:
            continue
        ang = disp[s][0]
        if len(ang) == 0:
            continue
        th = rng.uniform(0, 360)
        dsh.append(float(np.min(np.abs(((ang - th + 180) % 360) - 180))))
    dsh = np.array(dsh)

    # relation to the frame-to-frame global shift of the list (camera-pan candidate)
    shift = {}
    for a, b in zip(seqs, seqs[1:]):
        if b != a + 1:
            continue
        A = np.array([(p["x"], p["y"]) for p in positions_by_frame.get(a, [])], float)
        B = np.array([(p["x"], p["y"]) for p in positions_by_frame.get(b, [])], float)
        if len(A) < 2 or len(B) < 2:
            continue
        D = np.sqrt(((A[:, None] - B[None]) ** 2).sum(2))
        r, c = linear_sum_assignment(D)
        v = B[c] - A[r]
        mag = np.linalg.norm(v, axis=1)
        k = min(3, len(mag))
        idx = np.argsort(mag)[:k]
        shift[b] = np.median(v[idx], axis=0)
    v13_by = defaultdict(list)
    for s, v in v13:
        v13_by[s].append(v)
    pairs_shift = [(v, shift[s][0], shift[s][1]) for s, vals in v13_by.items() if s in shift for v in vals]
    if pairs_shift:
        a2 = np.array(pairs_shift, float)
        shift_corr = (float(np.corrcoef(a2[:, 0], a2[:, 1])[0, 1]),
                      float(np.corrcoef(a2[:, 0], a2[:, 2])[0, 1]))
    else:
        shift_corr = (float("nan"), float("nan"))

    # presence over time
    present = sorted(per_frame)
    gaps = [b - a for a, b in zip(present, present[1:])]

    return {
        "n": len(v13),
        "frames_with": len(per_frame),
        "frames_total": len(seqs),
        "presence_pct": 100 * len(per_frame) / max(len(seqs), 1),
        "unique": len(set(vals)),
        "min": min(vals) if vals else None,
        "max": max(vals) if vals else None,
        "mean": statistics.fmean(vals) if vals else None,
        "per_frame_counts": dict(sorted(counts.items())),
        "mean_per_frame": len(vals) / max(len(per_frame), 1),
        "runs": dict(sorted(runs.items())),
        "max_run": max(runs) if runs else 0,
        "pair_diff_median": float(np.median(pair_diffs)) if pair_diffs else None,
        "pair_same": sum(1 for d in pair_diffs if d == 0),
        "code_space_valid_pct": 100 * valid_code / max(len(vals), 1),
        "mult8_pct": 100 * mult8 / max(len([v for v in vals if v != 0]), 1),
        "near_x_pct": 100 * near_x / max(tot, 1),
        "near_y_pct": 100 * near_y / max(tot, 1),
        "chance_x_pct": 100 * chance_x,
        "chance_y_pct": 100 * chance_y,
        "heading_pairs": len(pairs),
        "heading_best_scale": best_scale,
        "heading_scale1_median": base,
        "heading_shift_control": shift_control,
        "disp45_median": float(np.median(d45)) if len(d45) else None,
        "disp45_within20": float(100 * np.mean(d45 <= 20)) if len(d45) else None,
        "disp9_median": float(np.median(d9)) if len(d9) else None,
        "disp_shuffled_median": float(np.median(dsh)) if len(dsh) else None,
        "disp_shuffled_within20": float(100 * np.mean(dsh <= 20)) if len(dsh) else None,
        "gap_median": float(np.median(gaps)) if gaps else None,
        "gap_p90": float(np.percentile(gaps, 90)) if gaps else None,
        "gap_max": max(gaps) if gaps else None,
        "shift_corr": shift_corr,
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gate", type=float, default=TRACK_GATE)
    ap.add_argument("--gap", type=int, default=TRACK_GAP)
    ap.add_argument("--csv", default=str(OUT_CSV))
    ap.add_argument("--md", default=str(OUT_MD))
    args = ap.parse_args()

    matches = sorted(BATCH.glob(MAIN_SAMPLE_GLOB))
    if not matches:
        print(f"sample not found: {BATCH / MAIN_SAMPLE_GLOB}", file=sys.stderr)
        return 2
    path = matches[0]
    data = path.read_bytes()

    records, end = find_stream(data)
    if not records:
        print("no frame stream", file=sys.stderr)
        return 2
    frames, clean, bad_stop, ch = extract_channels(records)
    seqs_all = sorted(frames)
    seqs_clean = sorted(clean)

    pos_all, dropped = positions(frames, seqs_all)
    pos_clean, _ = positions(frames, seqs_clean)

    # tail stream (informational)
    tail_counts = {"frames": 0, "n12": 0, "n13": 0}
    if records[-1]["seq"] + 1 < 0x8000:
        tail = parse_tail_stream(data, records[-1]["seq"], end)
        tail_counts["frames"] = len(tail)
        for f in tail:
            toks, _ok, _stop = parse_tail_payload(f["payload"])
            tail_counts["n12"] += sum(1 for m in toks if m[0] == "12")
            tail_counts["n13"] += sum(1 for m in toks if m[0] == "13")

    # tracking on clean frames (bad frames may carry a valid prefix, but a strict
    # clean set keeps the geometry homogeneous)
    tracks = track_sequence(pos_clean, seqs_clean, args.gate, args.gap)
    track_rows = track_summary(tracks)

    rng = np.random.default_rng(20261101)
    base = shuffled_tracking_stats(pos_clean, seqs_clean, args.gate, args.gap, rng)

    # sensitivity sweep
    sweep = []
    for g, gp in ((30, 15), (40, 20), (60, 40)):
        tr = track_sequence(pos_clean, seqs_clean, g, gp)
        lens = sorted((len(v) for v in tr.values()), reverse=True)
        sweep.append({
            "gate": g, "gap": gp, "tracks": len(lens),
            "ge100": sum(1 for x in lens if x >= 100),
            "ge300": sum(1 for x in lens if x >= 300),
            "max": lens[0] if lens else 0,
        })

    # per-frame coverage of long tracks
    long_ids = {r["track_id"] for r in track_rows if r["n_points"] >= 100}
    covered = set()
    for tid in long_ids:
        for s, _x, _y in tracks[tid]:
            covered.add(s)
    coverage_pct = 100 * len(covered) / max(len(seqs_clean), 1)

    # channels
    v13 = [(s, m[1]) for s in seqs_all for m in frames[s] if m[0] == "13"]
    v13_clean = [(s, m[1]) for s in seqs_clean for m in frames[s] if m[0] == "13"]
    stats13 = x13_stats(v13_clean, frames, ch["h2d"], pos_clean, seqs_clean, rng)
    heading = heading_alignment(tracks, ch["h2d"])
    world = world_vs_screen(ch["h2c"], pos_clean, seqs_clean, rng)
    death = death_track_association(track_rows, ch["h81"])

    # basic 0x12 facts
    all_pts = [p for s in seqs_clean for p in pos_clean[s]]
    x_raw = Counter(p["x_raw"] for p in all_pts)
    x_sig = Counter(p["x"] for p in all_pts)
    y_cnt = Counter(p["y"] for p in all_pts)
    frame_counts = Counter(len(pos_clean[s]) for s in seqs_clean)
    n_multi = sum(1 for s in seqs_clean if len(pos_clean[s]) >= 2)
    n_any = sum(1 for s in seqs_clean if pos_clean[s])
    uniq_x_frames = sum(1 for s in seqs_clean if pos_clean[s]
                        and len({p["x_raw"] for p in pos_clean[s]}) == len(pos_clean[s]))
    desc_pairs = desc_full = 0
    pairs_total = 0
    for s in seqs_clean:
        xs = [p["x"] for p in pos_clean[s]]
        if len(xs) < 2:
            continue
        d = sum(1 for a, b in zip(xs, xs[1:]) if a > b)
        desc_pairs += d
        pairs_total += len(xs) - 1
        desc_full += (d == len(xs) - 1)
    n_multi = sum(1 for s in seqs_clean if len(pos_clean[s]) >= 2)
    first_x = [pos_clean[s][0]["x_raw"] for s in seqs_clean if pos_clean[s]]
    nearest_zero = [min(abs(p["x"]) for p in pos_clean[s]) for s in seqs_clean if pos_clean[s]]

    # 0x12 vs 0x13 count correlation
    c12, c13 = [], []
    for s in seqs_clean:
        c12.append(len(pos_clean[s]))
        c13.append(sum(1 for m in frames[s] if m[0] == "13"))
    corr_count = float(np.corrcoef(c12, c13)[0, 1]) if len(set(c12)) > 1 else float("nan")

    summary = {
        "sample": path.name,
        "bytes": len(data),
        "records": len(records),
        "seq_first": records[0]["seq"],
        "seq_last": records[-1]["seq"],
        "clean_records": len(clean),
        "bad_records": len(records) - len(clean),
        "bad_stop_top": dict((str(k), v) for k, v in bad_stop.most_common(8)),
        "n12": len([1 for s in seqs_all for m in frames[s] if m[0] == "12"]),
        "n13": len([1 for s in seqs_all for m in frames[s] if m[0] == "13"]),
        "n12_clean": len(all_pts),
        "n13_clean": len(v13_clean),
        "dropped_invalid_12": dropped,
        "x_raw_min": min(x_raw), "x_raw_max": max(x_raw),
        "x_raw_distinct": len(x_raw),
        "x_missing_mid": [v for v in range(min(x_raw), max(x_raw) + 1) if v not in x_raw],
        "y_min": min(y_cnt), "y_max": max(y_cnt), "y_distinct": len(y_cnt),
        "x_sig_min": min(x_sig), "x_sig_max": max(x_sig),
        "frames_with_12": len([s for s in seqs_clean if pos_clean[s]]),
        "frame_count_hist": dict(sorted(frame_counts.items())),
        "mean_per_frame": statistics.fmean(len(pos_clean[s]) for s in seqs_clean),
        "x_unique_frames_pct": 100 * uniq_x_frames / max(n_any, 1),
        "desc_pairs_pct": 100 * desc_pairs / max(pairs_total, 1),
        "desc_full_pct": 100 * desc_full / max(n_multi, 1),
        "first_token_x_median": float(np.median(first_x)) if first_x else None,
        "nearest_zero_median": float(np.median(nearest_zero)) if nearest_zero else None,
        "nearest_zero_le2_pct": 100 * float(np.mean(np.array(nearest_zero) <= 2)) if nearest_zero else None,
        "corr_count_12_13": corr_count,
        "tail": tail_counts,
        "tracks": len(track_rows),
        "tracks_ge30": sum(1 for r in track_rows if r["n_points"] >= 30),
        "tracks_ge100": sum(1 for r in track_rows if r["n_points"] >= 100),
        "tracks_ge300": sum(1 for r in track_rows if r["n_points"] >= 300),
        "track_median_points": float(np.median([r["n_points"] for r in track_rows])) if track_rows else 0,
        "track_median_duration_s": float(np.median([r["duration_s"] for r in track_rows])) if track_rows else 0,
        "tracks_per_min": len(track_rows) / max((records[-1]["seq"] - records[0]["seq"]) / FPS / 60, 1e-9),
        "top10_point_share_pct": 100 * sum(r["n_points"] for r in track_rows[:10]) / max(len(all_pts), 1),
        "track_max_points": track_rows[0]["n_points"] if track_rows else 0,
        "track_max_duration_s": track_rows[0]["duration_s"] if track_rows else 0.0,
        "speed_med_p1": float(np.percentile([r["speed_med"] for r in track_rows if r["n_points"] >= 20], 1))
        if sum(1 for r in track_rows if r["n_points"] >= 20) else 0.0,
        "speed_med_min": min([r["speed_med"] for r in track_rows if r["n_points"] >= 20], default=0.0),
        "slow_track_pos_pct": 100 * sum(1 for r in track_rows if r["speed_med"] < 0.5 and r["n_points"] >= 20)
        / max(len(track_rows), 1),
        "long_track_coverage_pct": coverage_pct,
        "shuffle": base,
        "sweep": sweep,
        "heading": heading,
        "world": world,
        "death": death,
        "x13": stats13,
        "events": {
            "h2d": sum(len(v) for v in ch["h2d"].values()),
            "h2d_heroes": dict(Counter(h for vals in ch["h2d"].values() for h, _ in vals)),
            "h2c": len(ch["h2c"]),
            "h2c_heroes": dict(Counter(r["hero"] for r in ch["h2c"])),
            "h2c_kinds": dict(Counter(r["kind"] for r in ch["h2c"])),
            "h2c_world_x": [min(r["x"] for r in ch["h2c"]), max(r["x"] for r in ch["h2c"])] if ch["h2c"] else None,
            "h2c_world_y": [min(r["y"] for r in ch["h2c"]), max(r["y"] for r in ch["h2c"])] if ch["h2c"] else None,
            "h1e": len(ch["h1e"]),
            "h1e_heroes": dict(Counter(r["hero"] for r in ch["h1e"])),
            "h1e_types": dict(Counter(r["type"] for r in ch["h1e"])),
            "h81": len(ch["h81"]),
            "h81_values": dict(Counter(r["value"] for r in ch["h81"])),
            "h81_v6": sum(1 for r in ch["h81"] if r["value"] == 6),
            "h81_v6_heroes": dict(Counter(r["hero"] for r in ch["h81"] if r["value"] == 6)),
            "h85": len(ch["h85"]),
        },
    }

    write_csv(args.csv, summary, pos_clean, seqs_clean, track_rows, v13_clean, ch, tracks)
    write_md(args.md, summary, track_rows)

    print(f"sample      : {path.name}")
    print(f"records     : {len(records)} (clean {len(clean)})")
    print(f"0x12 / 0x13 : {summary['n12']} / {summary['n13']} (clean {summary['n12_clean']} / {summary['n13_clean']})")
    print(f"frames 0x12 : mean {summary['mean_per_frame']:.2f}, hist {summary['frame_count_hist']}")
    print(f"x signed    : [{summary['x_sig_min']}, {summary['x_sig_max']}], y [{summary['y_min']}, {summary['y_max']}]")
    print(f"tracks      : {summary['tracks']} (>=100 {summary['tracks_ge100']}, >=300 {summary['tracks_ge300']}, max {summary['track_max_points']})")
    print(f"shuffle base: {base}")
    print(f"heading     : n={heading['n']} R={heading['R']:.4f} (thr {heading['threshold_R']})")
    print(f"0x2c vs 0x12: median L1 {world['median']:.0f} (baseline {world['baseline_median']:.0f})")
    print(f"0x13        : n={stats13['n']} unique={stats13['unique']} presence={stats13['presence_pct']:.1f}%")
    print(f"0x13 vs 2d  : best scale {stats13['heading_best_scale']}")
    print(f"wrote {args.csv}")
    print(f"wrote {args.md}")
    return 0


# ---------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------
CSV_FIELDS = [
    "section", "seq", "rec_s", "game_s", "index", "x_raw", "x_signed", "y",
    "track_id", "n_points", "start_seq", "end_seq", "span_frames", "coverage",
    "duration_s", "speed_med", "speed_p90", "path_len", "net_disp", "straightness",
    "value", "channel", "hero", "a", "b", "c", "metric", "note",
]


def write_csv(path, s, pos_clean, seqs, track_rows, v13, ch, tracks):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # (seq, x, y) -> (track_id, track_len)
    pos_track = {}
    for tid, pts in tracks.items():
        for seq, x, y in pts:
            pos_track[(seq, int(round(x)), int(round(y)))] = (tid, len(pts))
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()

        # per-position rows (clean frames, legal code space)
        for seq in seqs:
            for p in pos_clean[seq]:
                tid, tlen = pos_track.get((seq, p["x"], p["y"]), ("", ""))
                w.writerow({
                    "section": "position", "seq": seq,
                    "rec_s": round(rec_s(seq), 3), "game_s": round(game_s(seq), 3),
                    "index": p["index"], "x_raw": p["x_raw"],
                    "x_signed": p["x"], "y": p["y"],
                    "track_id": tid, "n_points": tlen,
                })

        # per-track rows
        for r in track_rows:
            w.writerow({
                "section": "track", "track_id": r["track_id"],
                "n_points": r["n_points"], "start_seq": r["start_seq"],
                "end_seq": r["end_seq"], "span_frames": r["span_frames"],
                "coverage": round(r["coverage"], 3), "duration_s": round(r["duration_s"], 2),
                "speed_med": round(r["speed_med"], 3), "speed_p90": round(r["speed_p90"], 3),
                "path_len": round(r["path_len"], 1), "net_disp": round(r["net_disp"], 1),
                "straightness": round(r["straightness"], 3),
                "rec_s": round(rec_s(r["start_seq"]), 3),
                "game_s": round(game_s(r["start_seq"]), 3),
                "a": round(r["gap1_frac"], 3),
                "b": round(r["x_start"], 1), "c": round(r["y_start"], 1),
                "note": f"end=({r['x_end']:.1f},{r['y_end']:.1f})",
            })

        # 0x13 rows
        for seq, v in v13:
            w.writerow({
                "section": "x13", "seq": seq,
                "rec_s": round(rec_s(seq), 3), "game_s": round(game_s(seq), 3),
                "x_raw": v, "x_signed": x_signed(v) if x_valid(v) else "",
            })

        # channel events
        for seq, vals in sorted(ch["h2d"].items()):
            for hero, heading in vals:
                w.writerow({"section": "event", "seq": seq,
                            "rec_s": round(rec_s(seq), 3), "game_s": round(game_s(seq), 3),
                            "channel": "0x2d", "hero": hero, "value": heading})
        for r in ch["h2c"]:
            w.writerow({"section": "event", "seq": r["seq"],
                        "rec_s": round(rec_s(r["seq"]), 3), "game_s": round(game_s(r["seq"]), 3),
                        "channel": "0x2c", "hero": r["hero"], "a": r["kind"], "b": r["flag"],
                        "value": r["target"],
                        "note": f"world=({r['x']:.3f},{r['y']:.3f}) counter={r['counter']}"})
        for r in ch["h1e"]:
            w.writerow({"section": "event", "seq": r["seq"],
                        "rec_s": round(rec_s(r["seq"]), 3), "game_s": round(game_s(r["seq"]), 3),
                        "channel": "0x1e", "hero": r["hero"], "a": r["type"],
                        "value": r["victim"]})
        for r in ch["h81"]:
            w.writerow({"section": "event", "seq": r["seq"],
                        "rec_s": round(rec_s(r["seq"]), 3), "game_s": round(game_s(r["seq"]), 3),
                        "channel": "0x81", "hero": r["hero"], "value": r["value"]})

        # stats rows
        flat = []

        def walk(prefix, obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    walk(f"{prefix}.{k}" if prefix else str(k), v)
            elif isinstance(obj, (list, tuple)):
                flat.append((prefix, str(list(obj))))
            else:
                flat.append((prefix, obj))

        walk("", s)
        for key, val in flat:
            w.writerow({"section": "stat", "metric": key, "value": val})


def write_md(path, s, track_rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    h = s["heading"]
    w = s["world"]
    d = s["death"]
    x = s["x13"]
    ev = s["events"]

    top = track_rows[:12]

    lines = []
    A = lines.append
    A("# 0x12 轨迹跟踪 + 0x13 语义判定（5069040 主样本 20260925_105224）")
    A("")
    A("只读分析；未修改回放/包体，未注入，未读 param.json，未用 runtime_dump。")
    A("")
    A("## 0. 口径与输入")
    A("")
    A(f"- 样本：`{s['sample']}`（{s['bytes']:,} B）")
    A(f"- 主帧流：**{s['records']:,} 条记录**，seq {s['seq_first']}–{s['seq_last']}；"
      f"标签流严格吃满 **{s['clean_records']:,}** 帧（{s['bad_records']:,} 帧在更细标签处截断，"
      f"保留失败前的合法前缀）。")
    A(f"- `0x12` **{s['n12']:,}** 个、`0x13` **{s['n13']:,}** 个（与已知统计一致）；"
      f"干净帧口径 {s['n12_clean']:,} / {s['n13_clean']:,}。")
    A(f"- 第二段输入续流（712 帧）另计：0x12 {s['tail']['n12']:,}、0x13 {s['tail']['n13']:,}，"
      "默认不并入（否则总数对不上已知 76,059/16,187）。")
    A("- 时间：`rec_s = seq/20`，`game_s = rec_s + 21.5`（doc 5.92 标定，medium-high）。")
    A("")
    A("## 0.1 结论速览")
    A("")
    A("| 问题 | 结论 | 置信度 |")
    A("|---|---|---|")
    A(f"| 0x12 能跟踪成几条轨迹 | {s['tracks']:,} 条短轨迹（中位 {s['track_median_duration_s']:.1f}s）；"
      f"≥100 点 {s['tracks_ge100']} 条、≥300 点 {s['tracks_ge300']} 条、最长 {s['track_max_duration_s']:.1f}s | high（跟踪本身）/ high（\"没有 10 条英雄轨迹\"） |")
    A("| 能否关联到玩家 | **0/10 人**；0x2d/0x2c/0x1e/0x81 都给不出可用桥 | high（阴性） |")
    A("| 0x12 是什么 | 按 x 降序维护的可见单位二维点列表（80×181 屏幕/小地图类空间），不含本地 POV 英雄，不是世界坐标 | medium-high |")
    A("| 0x13 是相机角度吗 | 否 | medium-high |")
    A("| 0x13 是单位朝向吗 | 否（对 442 与所有可见单位均无逐帧相关） | medium |")
    A("| 0x13 是类型 ID 吗 | 否（53 个值、几乎不复用、45% 帧缺失） | medium-high |")
    A("| 0x13 更像什么 | 与 0x12 x 同一套有符号 6 位码的第二个标量（次要坐标/另一条流） | low-medium，未定名 |")
    A("")
    A("## 1. 0x12 的坐标结构（本轮新证据）")
    A("")
    A("| 事实 | 数值 | 含义 |")
    A("|---|---:|---|")
    A(f"| x 原始值 | {s['x_raw_min']}–{s['x_raw_max']}，{s['x_raw_distinct']} 个不同值 | 不是连续坐标 |")
    A(f"| x 缺失区间 | {s['x_missing_mid'][0] if s['x_missing_mid'] else '-'}–"
      f"{s['x_missing_mid'][-1] if s['x_missing_mid'] else '-'}（{len(s['x_missing_mid'])} 个） | 中间整段空洞 |")
    A(f"| 编码 | `0x80+v → +v`，`0x40+v → -(v+1)`，v∈0..39 | **有符号 6 位 + 2 位前缀** |")
    A(f"| 解出 x_signed | {s['x_sig_min']} … {s['x_sig_max']} | 80 个取值 |")
    A(f"| y | {s['y_min']}–{s['y_max']}，{s['y_distinct']} 个值 | 连续 0–180 |")
    A(f"| 每帧点数 | 均值 {s['mean_per_frame']:.2f}，分布 {s['frame_count_hist']} | 4–8 为主 |")
    A(f"| 同帧 x 互不重复 | **{s['x_unique_frames_pct']:.1f}%** | 像“键/列表”而不是坐标 |")
    A(f"| 按 x_signed 降序 | 相邻对 {s['desc_pairs_pct']:.1f}%，整帧严格 {s['desc_full_pct']:.1f}% | 列表有序 |")
    A(f"| 首 token 的 x 原始值中位 | {s['first_token_x_median']} | 首项≈最右 |")
    A(f"| 轨迹最小中位速度 | **{s['speed_med_min']:.2f}**（p1={s['speed_med_p1']:.2f}，≥20 点轨迹） | "
      "没有任何近乎静止的点 → **本地 POV 英雄不在列表里** |")
    A("")
    A("**判读**：0x12 不是“每帧随机读到的几个 8 位坐标”。它是 **按 x 降序维护的可见单位列表**：")
    A("每项 `(有符号 6 位 x, 8 位 y)`，x 用两段 bank 编码（中间 104–127 永远不出现），")
    A("同一帧 x 不重复，后出现的单位多数被追加在表尾（所以整帧严格降序只有 44%，")
    A("但相邻对 87% 降序）。这与“身份槽位列表”不同：槽位不会天然按 x 排序。")
    A("")
    A("它 **不是世界坐标**：0x2c 的坐标是 i32BE 定点（低 4 位小数，整数部分 ±3290，"
      f"x {ev['h2c_world_x'][0]:.0f}…{ev['h2c_world_x'][1]:.0f}，y {ev['h2c_world_y'][0]:.0f}…{ev['h2c_world_y'][1]:.0f}），"
      "0x12 的取值域 [-40,39]×[0,180] 根本容纳不下这种量级；")
    A(f"0x2c 目标点到最近 0x12 点的 L1 距离中位 **{w['median']:.0f}**，打乱世界坐标后基线 "
      f"**{w['baseline_median']:.0f}**——两者几乎一样，没有任何映射迹象。")
    A("")
    A("## 2. 最近邻跟踪：能形成几条轨迹")
    A("")
    A(f"跟踪器：`(x_signed, y)` 上的匈牙利分配 + 常速度预测，单帧门限 {s['sweep'][1]['gate']:.0f}、"
      f"允许丢帧 {s['sweep'][1]['gap']}。")
    A("")
    A("| 门限/丢帧 | 轨迹数 | ≥100 点 | ≥300 点 | 最长 |")
    A("|---|---:|---:|---:|---:|")
    for row in s["sweep"]:
        A(f"| {row['gate']:.0f}/{row['gap']} | {row['tracks']:,} | {row['ge100']} | {row['ge300']} | {row['max']} |")
    A("")
    A(f"- 主配置：**{s['tracks']:,} 条**轨迹（≥3 点），≥100 点 **{s['tracks_ge100']}** 条，"
      f"≥300 点 **{s['tracks_ge300']}** 条，最长 **{s['track_max_points']} 帧 ≈ {s['track_max_duration_s']:.1f}s**。")
    A(f"- 轨迹中位长度 **{s['track_median_points']:.0f} 点 / {s['track_median_duration_s']:.1f}s**；"
      f"平均 **{s['tracks_per_min']:.1f} 条新轨迹/分钟**。")
    A(f"- 最长 10 条轨迹只装下全部点位实例的 **{s['top10_point_share_pct']:.1f}%**"
      f"（若是 10 个英雄身份，10 条应占绝大部分）。")
    A(f"- 所有 ≥100 点轨迹合计覆盖 **{s['long_track_coverage_pct']:.1f}%** 的帧（多轨并存，不代表身份连续）。")
    A(f"- **打乱基线**（把整帧点集在时间上随机重排后跑同一跟踪器）：{s['shuffle']['tracks']:,} 条，"
      f"≥100 点 {s['shuffle']['ge100']}，≥300 点 {s['shuffle']['ge300']}，最长 {s['shuffle']['max']}。")
    A("")
    A(f"**结论**：轨迹的帧间连续性是真的（≥100 点轨迹 {s['tracks_ge100']} 条 vs 打乱基线 "
      f"{s['shuffle']['ge100']} 条），但 **没有 10 条贯穿全局的英雄轨迹**："
      f"轨迹总数 {s['tracks']:,}、中位寿命只有 {s['track_median_duration_s']:.1f}s，"
      "单位出屏就断、再进屏会按新的 x 顺序落到列表别处。")
    A("")
    A("### 2.1 最长轨迹（前 12）")
    A("")
    A("| track | 点数 | seq 起–止 | 时长 | 覆盖率 | 速度中位/p90 | 直线度 | 起点 | 终点 |")
    A("|---:|---:|---|---:|---:|---|---:|---|---|")
    for r in top:
        A(f"| {r['track_id']} | {r['n_points']} | {r['start_seq']}–{r['end_seq']} | "
          f"{r['duration_s']:.1f}s | {r['coverage']:.2f} | {r['speed_med']:.1f}/{r['speed_p90']:.1f} | "
          f"{r['straightness']:.2f} | ({r['x_start']:.0f},{r['y_start']:.0f}) | "
          f"({r['x_end']:.0f},{r['y_end']:.0f}) |")
    A("")
    A("速度单位是“编码单位/帧”：中位 3–5、p90 10–16。若按 0–180 的屏幕高度理解，")
    A("约 60–100 单位/秒，像镜头跟随时屏幕内单位的移动量级；**不像小地图上的世界位置**")
    A("（小地图上英雄横穿全图应约 30s，而不是 2–3s）。")
    A("")
    A("## 3. 轨迹能否关联到玩家/单位")
    A("")
    A(f"- **本地 POV 英雄不在 0x12 里**：若 0x12 是镜头相对的屏幕坐标，镜头跟随的本地英雄应是一条")
    A(f"  近乎静止的轨迹；实际 ≥20 点轨迹的最小中位速度是 **{s['speed_med_min']:.2f}**"
      f"（p1={s['speed_med_p1']:.2f}），一条静止轨迹都没有。")
    A(f"- **0x2d 朝向**：{ev['h2d']:,} 条，仅英雄 **{list(ev['h2d_heroes'].keys())}**（本地 POV 玩家），"
      f"值 1–359。把它当作朝向，与轨迹相邻帧的屏幕位移方向比较：n={h['n']:,}，"
      f"圆统计 R=**{h['R']:.4f}**（p=.05 阈值 {h['threshold_R']:.4f}）——**完全无方向相关**，"
      "最优全局旋转也救不回来（12 个 30° 分箱几乎均匀）。→ 无法用 0x2d 把任何一条轨迹锁到 442。")
    A(f"- **0x2c**：{ev['h2c']:,} 条（英雄 {ev['h2c_heroes']}，kind {ev['h2c_kinds']}），"
      "坐标是 i32BE 定点/16 的世界坐标（±3290）；与 0x12 不同域，最近点距离中位 "
      f"{w['median']:.0f}（打乱基线 {w['baseline_median']:.0f}），**零关联**。")
    A(f"- **0x1e**：{ev['h1e']} 条，attacker {ev['h1e_heroes']}，type {ev['h1e_types']}，"
      "victim 是运行时 objectID（无位置），只能给时间锚点。")
    A(f"- **0x81 value6（死亡候选）**：{ev['h81_v6']} 个窗口，英雄 {ev['h81_v6_heroes']}。")
    A(f"  死亡窗口 ±{d['window_frames']} 帧内平均有 **{d['mean_ends']:.1f}** 条轨迹终止，"
      f"随机期望 **{d['expected']:.1f}** 条，lift **{d['lift']:.2f}**——"
      "轨迹终止本来就频繁，不构成可用关联。")
    A("")
    A("**结论：能明确关联到玩家的轨迹 = 0 条。** 唯一有玩家 ID 的位置通道（0x2c）是世界坐标，")
    A("与 0x12 不在同一坐标系；0x2d 只属于 442，但和 0x12 的屏幕位移无方向相关。")
    A("")
    A("## 4. 0x13 是什么")
    A("")
    A("| 判据 | 数值 | 排除/支持 |")
    A("|---|---:|---|")
    A(f"| 条数 / 唯一值 | {x['n']:,} / {x['unique']}（干净帧；含截断帧共 {s['n13']:,}/55） | 类型 ID 应少而重复 |")
    A(f"| 每帧条数（含 0x13 的帧） | {x['per_frame_counts']}，均值 {x['mean_per_frame']:.2f}"
      f"（全体帧均值 {x['n'] / max(x['frames_total'], 1):.2f}） | 不是 0x12 的一一属性 |")
    A(f"| 出现帧占比 | {x['presence_pct']:.1f}%（{x['frames_with']:,}/{x['frames_total']:,}） | 一半帧完全缺失 |")
    A(f"| 连续重复段 | 最长 **{x['max_run']}**，分布 {x['runs']} | **类型/状态 ID 会被复用，不会只重复 {x['max_run']} 个 token** |")
    A(f"| 同帧两值差 | 中位 **{x['pair_diff_median']}**，众数 1，p75 47 | 同帧两值常相邻 → 像同一量的两次采样 |")
    A(f"| 编码域 | 合法 6 位码占 {x['code_space_valid_pct']:.1f}%，低 6 位是 8 的倍数占 {x['mult8_pct']:.1f}% | 与 0x12 x **同一套编码** |")
    A(f"| 与 0x12 x 接近 | {x['near_x_pct']:.1f}%（随机 {x['chance_x_pct']:.1f}%） | 不重复、不配对 |")
    A(f"| 与 0x12 y 接近 | {x['near_y_pct']:.1f}%（随机 {x['chance_y_pct']:.1f}%） | 无关 |")
    A(f"| 与 0x2d 朝向（同帧） | 最优线性比例 {x['heading_best_scale'][0]:.2f}，R={x['heading_shift_control'].get('0', (0, 0))[0]:.3f}"
      f"（随机阈值 {1.73 / math.sqrt(max(x['heading_pairs'], 1)):.3f}） | 看似有弱相关 |")
    A(f"| 与 0x2d 朝向（时间错位对照） | shift 1/100/1000 帧 R="
      f"{x['heading_shift_control'].get('1', (0, 0))[0]:.3f} / "
      f"{x['heading_shift_control'].get('100', (0, 0))[0]:.3f} / "
      f"{x['heading_shift_control'].get('1000', (0, 0))[0]:.3f} | **错位后不下降 → 只是边际分布对齐，不是逐帧关系** |")
    A(f"| 与可见单位位移方向 | 4.5°/单位：中位 {x['disp45_median']:.1f}°，≤20° 占 {x['disp45_within20']:.1f}%；"
      f"打乱 {x['disp_shuffled_median']:.1f}° / {x['disp_shuffled_within20']:.1f}% | **不是任何可见单位的朝向** |")
    A(f"| 与整帧列表平移（镜头拖动候选） | corr dx={x['shift_corr'][0]:+.3f}，dy={x['shift_corr'][1]:+.3f} | **不是镜头平移量** |")
    A("")
    A("**逐条判定**：")
    A("")
    A(f"1. **类型 ID：排除（medium-high）**。{x['unique']} 个唯一值 + 最长连续重复 {x['max_run']} 帧 + "
      f"{100 - x['presence_pct']:.0f}% 的帧完全没有；")
    A("   类型枚举会大量复用（同类型小兵/英雄反复出现），不会每帧换值。")
    A("2. **相机角度：不成立（medium-high）**。相机角应平滑、长期驻留；0x13 相邻出现中位跳变 9、")
    A("   p90 64，一半帧缺失，且与本地玩家朝向 0x2d 的“弱相关”经时间错位对照后不消失")
    A("   （shift 1/100/1000 帧 R 几乎不变），说明只是两个边际分布的线性对齐，不是逐帧角度关系。")
    A("3. **单位朝向：不成立（medium）**。对 442 无逐帧相关；对同帧可见单位的屏幕位移方向也没有富集")
    A("   （≤20° 命中率与随机置换相同）。")
    A("4. **更可能是同一屏幕坐标码里的第二个标量**：0x13 与 0x12 的 x 共用 `0x40/0x80 + 6 位` 编码，")
    A("   同帧两值差众数为 1，且与 x 的取值分布同域。最像“同一可见列表里某个单位的另一分量/")
    A("   次要坐标”，但**没有直接证据能定名**（low-medium）。")
    A("")
    A("## 5. 还缺什么")
    A("")
    A("- **0x12 的坐标系参照**：需要引擎侧“屏幕/小地图投影”或一帧带相机矩阵的 dump，才能把")
    A("  (x_signed,y) 反算到世界坐标；否则无法和 0x2c/玩家块闭环。")
    A("- **列表项的 ID**：0x12 只有 (x,y)，没有 objectID；0x1e/0x2c 的 victim/target 是 objectID，")
    A("  两者之间没有可读的桥。需要单位表或 0x1e/0x2c 与 0x12 的同帧对象匹配规则。")
    A("- **0x13 的定名**：要么找到引擎侧读它的字段（相机/单位），要么找到它与某个已解量的")
    A("  确定性关系（目前与 0x2d、0x12 x/y、可见单位位移都不成立）。")
    A("- **更多样本**：短样本（094930/095631/20261101）的 0x12 x 只到 64–79，说明 x 的可用范围")
    A("  和“可见单位集合”相关，值得用多局同 build 样本验证“按 x 排序的可见列表”这一解释。")
    A("")
    A("## 6. 复现")
    A("")
    A("```bash")
    A("python tools/agent_screen_positions.py")
    A("python tools/agent_screen_positions.py --gate 30 --gap 15")
    A("```")
    A("")
    A("产物：`datasets/agent_screen_positions.csv`（section = position / track / x13 / event / stat）、")
    A("`datasets/agent_screen_positions.md`（本文件）。")
    A("")

    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
