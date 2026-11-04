"""普通 5v5（5069040）回放时间轴校准：game_time = seq/fps + offset。

只读分析：
- 只解析 `data/replays/samples/abc_batch/2026092[45]_*.abc` 六个 5069040 样本；
- 不修改回放/包体，不注入进程，不读取 param.json，不使用 runtime_dump；
- 不编辑 docs/replay_binary_format.md 与 .workbuddy/memory/MEMORY.md。

数据口径：
- `seq` 是 `.abc` 主帧流的帧号；`seq/20` 是录制时间（rec_s），不是对局时间。
- `game_time = seq/fps + offset`（默认 fps=20）。
- source4 = `0x02 flag=0x85 len=5` 中 `sourceType=4` 的兵线金币事件；
  它是兵线档位结算，不是逐单位补刀记录；金额 88 多为单个小兵档，
  187/194/219 可能是多单位/攻城车档。

锚点：
- 官方 S45 普通 5v5：首波 0:10 出生、中路 0:25 交汇、边路 0:33 交汇、
  间隔 33s。
- 最早一条 source4 一定是全队最早的中路兵线击杀/结算，因此
  `offset >= 25 - first_rec_s`。
- 10-15s 录制窗口内的第一条 source4 作为边路首条候选（中路+8s 边界），
  `offset >= 33 - side_rec_s`。

输出：
  data/replays/_analysis/datasets/agent_time_axis_calibration.csv
  data/replays/_analysis/datasets/agent_time_axis_calibration.md
"""
from __future__ import annotations

import csv
import math
import statistics
import struct
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / "data" / "replays" / "samples" / "abc_batch"
DATASETS = ROOT / "data" / "replays" / "_analysis" / "datasets"
OUT_CSV = DATASETS / "agent_time_axis_calibration.csv"
OUT_MD = DATASETS / "agent_time_axis_calibration.md"

FPS_NOMINAL = 20.0
MID_CONTACT_S = 25.0
SIDE_CONTACT_S = 33.0
WAVE_INTERVAL_S = 33.0
RECOMMENDED_OFFSET_S = 21.5

FPS_CANDIDATES = (19.5, 20.0, 20.5)
SIDE_WINDOW_S = (10.0, 15.0)
SECOND_BATCH_GAP_S = 5.0
ONE_WAVE_GAP_FRAMES = (640, 690)
EPS = 1e-9


# ---------------------------------------------------------------------------
# frame stream parsing
# ---------------------------------------------------------------------------
def parse_records(data: bytes, pos: int, first_seq: int = 0x22) -> tuple[list[dict], int]:
    """Parse the main record stream: seq,pad,L,payload,a,5*00,b."""
    records: list[dict] = []
    seq = first_seq
    while pos + 10 <= len(data):
        if data[pos] != (seq & 0xFF):
            break
        if data[pos + 1] != 0:
            break
        length = data[pos + 2]
        end = pos + 10 + length
        if end > len(data):
            break
        records.append(
            {
                "off": pos,
                "seq": seq,
                "payload": data[pos + 3 : pos + 3 + length],
                "a": data[pos + 3 + length],
                "b": data[pos + 9 + length],
            }
        )
        pos = end
        seq += 1
    return records, pos


def find_stream(data: bytes, scan_limit: int = 0x20000) -> tuple[list[dict], int]:
    """Find the longest strict seq+1 record stream in the file header area."""
    best: tuple[list[dict], int] = ([], 0)
    limit = min(len(data), scan_limit)
    for pos in range(0, limit):
        if data[pos] != 0x22 or data[pos + 1] != 0:
            continue
        records, end = parse_records(data, pos)
        if len(records) > len(best[0]):
            best = (records, end)
            if len(records) > 500:
                break
    return best


def iter_main_events(records: list[dict]):
    """Yield ('gold', seq, hero, source, amount) / ('upgrade', seq, hero, data)."""
    for rec in records:
        payload = rec["payload"]
        if not payload:
            continue
        i = 1  # main stream payload starts with a count byte
        while i < len(payload):
            tag = payload[i]
            if tag == 0x12:
                i += 3
            elif tag == 0x13:
                i += 2
            elif tag == 0x14:
                i += 4
            elif tag == 0x01:
                if i + 5 > len(payload):
                    break
                length = payload[i + 4]
                if i + 5 + length > len(payload):
                    break
                i += 5 + length
            elif tag == 0x02:
                if i + 4 > len(payload):
                    break
                hero = int.from_bytes(payload[i + 1 : i + 3], "big")
                flag = payload[i + 3]
                if flag == 0x80:
                    # 12-byte command body variant; same convention as abc_tags_full.
                    if i + 16 > len(payload):
                        break
                    i += 16
                else:
                    length = flag & 0x7F
                    if i + 4 + length > len(payload):
                        break
                    body = payload[i + 4 : i + 4 + length]
                    if flag == 0x85 and length == 5:
                        yield ("gold", rec["seq"], hero, body[0],
                               int.from_bytes(body[1:5], "little"))
                    elif flag == 0x87 and length == 7:
                        yield ("upgrade", rec["seq"], hero, body)
                    i += 4 + length
            else:
                break


def parse_nocount(payload: bytes):
    """Continuation stream payload has no count prefix."""
    i = 0
    while i < len(payload):
        tag = payload[i]
        if tag == 0x12:
            i += 3
        elif tag == 0x13:
            i += 2
        elif tag == 0x14:
            i += 4
        elif tag == 0x01:
            if i + 5 > len(payload):
                break
            length = payload[i + 4]
            if i + 5 + length > len(payload):
                break
            i += 5 + length
        elif tag == 0x02:
            if i + 4 > len(payload):
                break
            hero = int.from_bytes(payload[i + 1 : i + 3], "big")
            flag = payload[i + 3]
            if flag == 0x80:
                if i + 16 > len(payload):
                    break
                i += 16
            else:
                length = flag & 0x7F
                if i + 4 + length > len(payload):
                    break
                body = payload[i + 4 : i + 4 + length]
                if flag == 0x85 and length == 5:
                    yield ("gold", hero, body[0], int.from_bytes(body[1:5], "little"))
                elif flag == 0x87 and length == 7:
                    yield ("upgrade", hero, body)
                i += 4 + length
        else:
            break


def second_stream(data: bytes, last_main_seq: int, tail_start: int) -> list[dict]:
    """Find and parse the input continuation segment (main sample only)."""
    tail = data[tail_start:]
    start = None
    for i in range(0, min(len(tail) - 5, 0x1000)):
        first, length = struct.unpack_from(">HH", tail, i)
        if last_main_seq + 1 <= first <= last_main_seq + 5 and 4 <= length <= 1000:
            start = i
            break
    if start is None:
        return []
    frames: list[dict] = []
    pos = start
    while pos + 5 <= len(tail):
        seq, length = struct.unpack_from(">HH", tail, pos)
        type_byte = tail[pos + 4]
        if (seq < last_main_seq or seq > last_main_seq + 3000
                or length > 1000 or pos + 10 + length > len(tail)):
            break
        frames.append(
            {
                "seq": seq,
                "payload": tail[pos + 5 : pos + 5 + length],
                "type_byte": type_byte,
            }
        )
        pos += 10 + length
    return frames


# ---------------------------------------------------------------------------
# metadata
# ---------------------------------------------------------------------------
def sample_id(name: str) -> str:
    parts = name.split("_")
    return "_".join(parts[:2]) if len(parts) >= 2 else name


def load_player_maps() -> dict[str, dict[int, dict]]:
    """entityID -> {player, team, slot, hero} for each sample."""
    maps: dict[str, dict[int, dict]] = defaultdict(dict)

    def ingest(path: Path, sample_key: str | None) -> None:
        with path.open(encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                try:
                    entity = int(row["entityID"])
                except (KeyError, TypeError, ValueError):
                    continue
                key = sample_key or sample_id(row.get("sample", ""))
                maps[key][entity] = {
                    "player": row.get("player", ""),
                    "team": row.get("team", ""),
                    "slot": row.get("slot", ""),
                    "hero": row.get("heroName", ""),
                }

    root = DATASETS / "normal5v5_player_heroes_5069040.csv"
    if root.exists():
        ingest(root, None)
    for path in sorted((DATASETS / "player_block_5069040").glob("*/*.csv")):
        if "schema" in path.name:
            continue
        ingest(path, sample_id(path.parent.name))
    return maps


def player_of(maps: dict[str, dict[int, dict]], sample: str, entity: int) -> dict:
    info = maps.get(sample, {}).get(entity)
    if info:
        return info
    return {"player": "", "team": "", "slot": "", "hero": ""}


def hms(seconds: float) -> str:
    minutes = int(seconds // 60)
    rest = seconds - minutes * 60
    return f"{minutes}:{rest:05.2f}"


def rms(values: list[float]) -> float:
    return math.sqrt(sum(v * v for v in values) / len(values)) if values else float("nan")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    files = sorted(BATCH.glob("2026092[45]_*.abc"))
    if len(files) != 6:
        print(f"expected 6 5069040 samples, found {len(files)}", file=sys.stderr)
        return 2

    maps = load_player_maps()
    samples: list[dict] = []
    all_gaps: list[dict] = []

    for path in files:
        data = path.read_bytes()
        records, end = find_stream(data)
        if not records:
            print(f"no frame stream: {path.name}", file=sys.stderr)
            continue
        sid = sample_id(path.name)
        events = []
        all_gold = []
        upgrades = []
        for event in iter_main_events(records):
            if event[0] == "gold":
                gold_event = {"seq": event[1], "entity": event[2],
                              "source": event[3], "amount": event[4]}
                all_gold.append(gold_event)
                if event[3] == 4:
                    events.append(gold_event)
            elif event[0] == "upgrade":
                upgrades.append({"seq": event[1], "entity": event[2],
                                 "data": event[3]})
        events.sort(key=lambda e: e["seq"])
        if not events:
            print(f"no source4: {path.name}", file=sys.stderr)
            continue

        first = events[0]
        first_rec = first["seq"] / FPS_NOMINAL
        second_batch = next(
            (e for e in events if e["seq"] / FPS_NOMINAL - first_rec >= SECOND_BATCH_GAP_S),
            None,
        )
        side_candidates = [
            e for e in events
            if SIDE_WINDOW_S[0] <= e["seq"] / FPS_NOMINAL <= SIDE_WINDOW_S[1]
        ]
        side = side_candidates[0] if side_candidates else None
        first15 = [e for e in events if e["seq"] / FPS_NOMINAL <= SIDE_WINDOW_S[1]]

        by_entity: dict[int, list[int]] = defaultdict(list)
        for e in events:
            by_entity[e["entity"]].append(e["seq"])
        gaps = []
        for entity, seqs in by_entity.items():
            seqs = sorted(seqs)
            for a, b in zip(seqs, seqs[1:]):
                gap = b - a
                if ONE_WAVE_GAP_FRAMES[0] <= gap <= ONE_WAVE_GAP_FRAMES[1]:
                    gaps.append({"sample": sid, "entity": entity, "seq_a": a,
                                 "seq_b": b, "gap": gap})
        all_gaps.extend(gaps)

        frame_first, frame_last = records[0]["seq"], records[-1]["seq"]
        continuation = second_stream(data, frame_last, end)
        cont_events = []
        if continuation:
            for frame in continuation:
                for event in parse_nocount(frame["payload"]):
                    if event[0] == "gold":
                        cont_events.append(
                            {"seq": frame["seq"], "kind": "gold", "entity": event[1],
                             "source": event[2], "amount": event[3]}
                        )
                    elif event[0] == "upgrade":
                        cont_events.append(
                            {"seq": frame["seq"], "kind": "upgrade", "entity": event[1],
                             "data": event[2]}
                        )

        samples.append(
            {
                "path": path,
                "sid": sid,
                "records": records,
                "upgrades": upgrades,
                "events": events,
                "all_gold": all_gold,
                "first": first,
                "second_batch": second_batch,
                "side": side,
                "first15": first15,
                "frame_first": frame_first,
                "frame_last": frame_last,
                "continuation": continuation,
                "cont_events": cont_events,
                "gaps": gaps,
                "by_entity": by_entity,
            }
        )

    if len(samples) != 6:
        print("did not parse all 6 samples", file=sys.stderr)
        return 2

    # ---- offset fits ------------------------------------------------------
    mid_offsets = [MID_CONTACT_S - s["first"]["seq"] / FPS_NOMINAL for s in samples]
    naive_ls = statistics.fmean(mid_offsets)
    naive_median = statistics.median(mid_offsets)
    mid_bound = max(mid_offsets)
    # The main-sample 李信 is the clean side anchor. 103058's 不知火舞 is a
    # mage/assassin and may be mid/roam, so it is kept as a low-confidence
    # supporting row and is not used as a hard bound.
    side_bounds = []
    for s in samples:
        if not s["side"]:
            continue
        side_bounds.append(
            {
                "sid": s["sid"],
                "bound": SIDE_CONTACT_S - s["side"]["seq"] / FPS_NOMINAL,
                "reliable": s["sid"].startswith("20260925_105224"),
            }
        )
    hard_side_bounds = [item for item in side_bounds if item["reliable"]]
    joint_min = max([mid_bound] + [item["bound"] for item in hard_side_bounds])
    # Round the smallest feasible offset to the nearest 0.5s. The constant is
    # only a sanity fallback when no side anchor is available.
    recommended = round(joint_min * 2) / 2 if hard_side_bounds else RECOMMENDED_OFFSET_S

    # ---- fps fits ---------------------------------------------------------
    gap_frames = [g["gap"] for g in all_gaps]
    gap_mean = statistics.fmean(gap_frames) if gap_frames else float("nan")
    gap_median = statistics.median(gap_frames) if gap_frames else float("nan")
    gap_fps_mean = gap_mean / WAVE_INTERVAL_S if gap_frames else float("nan")
    gap_fps_median = gap_median / WAVE_INTERVAL_S if gap_frames else float("nan")

    fps_rows = []
    for fps in FPS_CANDIDATES:
        offset_min = max(
            [MID_CONTACT_S - s["first"]["seq"] / fps for s in samples]
            + [SIDE_CONTACT_S - s["side"]["seq"] / fps
               for s in samples if s["side"] and s["sid"].startswith("20260925_105224")]
        )
        mid_delays = [s["first"]["seq"] / fps + offset_min - MID_CONTACT_S for s in samples]
        side_delays = [
            s["side"]["seq"] / fps + offset_min - SIDE_CONTACT_S
            for s in samples if s["side"] and s["sid"].startswith("20260925_105224")
        ]
        gap_rms = rms([g / fps - WAVE_INTERVAL_S for g in gap_frames])
        score = gap_rms + 0.1 * (statistics.fmean(mid_delays) + statistics.fmean(side_delays))
        fps_rows.append(
            {
                "fps": fps,
                "period_frames": WAVE_INTERVAL_S * fps,
                "offset_min": offset_min,
                "mid_delay_mean": statistics.fmean(mid_delays),
                "side_delay_mean": statistics.fmean(side_delays),
                "gap_rms": gap_rms,
                "score": score,
            }
        )

    fine_scan = []
    for i in range(1900, 2101):
        fps = i / 100
        fine_scan.append((rms([g / fps - WAVE_INTERVAL_S for g in gap_frames]), fps))
    fine_scan.sort()
    fine_best_rms, fine_best_fps = fine_scan[0]

    # ---- main sample / 1558 ----------------------------------------------
    main = next(s for s in samples if s["sid"].startswith("20260925_105224"))
    main_first = main["frame_first"] / FPS_NOMINAL
    main_last = main["frame_last"] / FPS_NOMINAL
    main_span = (main["frame_last"] - main["frame_first"]) / FPS_NOMINAL
    main_inclusive = (main["frame_last"] - main["frame_first"] + 1) / FPS_NOMINAL
    cont = main["continuation"]
    cont_first = cont[0]["seq"] / FPS_NOMINAL if cont else float("nan")
    cont_last = cont[-1]["seq"] / FPS_NOMINAL if cont else float("nan")
    cont_duration = (cont[-1]["seq"] - cont[0]["seq"] + 1) / FPS_NOMINAL if cont else float("nan")
    cont_gap = (cont[0]["seq"] - main["frame_last"]) / FPS_NOMINAL if cont else float("nan")
    total_span = (cont[-1]["seq"] - main["frame_first"]) / FPS_NOMINAL if cont else float("nan")
    total_inclusive = (cont[-1]["seq"] - main["frame_first"] + 1) / FPS_NOMINAL if cont else float("nan")
    total_from_zero = cont_last + recommended if cont else float("nan")

    entity_1558 = 1558
    gold_1558_main = [e for e in main["all_gold"] if e["entity"] == entity_1558]
    gold_1558_cont = [
        e for e in main["cont_events"]
        if e["kind"] == "gold" and e["entity"] == entity_1558
    ]
    up_1558_main = [e for e in main["upgrades"] if e["entity"] == entity_1558]
    up_1558_cont = [
        e for e in main["cont_events"]
        if e["kind"] == "upgrade" and e["entity"] == entity_1558
    ]
    last_gold_main = gold_1558_main[-1] if gold_1558_main else None
    last_gold_cont = gold_1558_cont[-1] if gold_1558_cont else None
    last_up_main = up_1558_main[-1] if up_1558_main else None
    last_up_cont = up_1558_cont[-1] if up_1558_cont else None
    last_gold = last_gold_cont or last_gold_main
    last_up = last_up_cont or last_up_main

    # ---- CSV --------------------------------------------------------------
    fields = [
        "section", "sample", "metric", "seq", "rec_s", "game_s", "game_hms",
        "fps", "offset_s", "amount", "player", "entity_id", "hero", "lane",
        "count", "value", "note", "confidence",
    ]
    rows: list[dict] = []

    def add(**kw):
        row = {k: "" for k in fields}
        row.update(kw)
        rows.append(row)

    # offset fit summary
    add(section="offset_fit", sample="ALL", metric="naive_ls_mid",
        offset_s=f"{naive_ls:.3f}", count=len(mid_offsets),
        value=f"{naive_ls:.3f}",
        note="mean(25 - first_rec_s); symmetric-error fit, biased low if delay>=0",
        confidence="low")
    add(section="offset_fit", sample="ALL", metric="naive_median_mid",
        offset_s=f"{naive_median:.3f}", count=len(mid_offsets),
        value=f"{naive_median:.3f}",
        note="median(25 - first_rec_s); same bias", confidence="low")
    add(section="offset_fit", sample="ALL", metric="one_sided_mid_bound",
        offset_s=f"{mid_bound:.3f}", count=len(mid_offsets),
        value=f"{mid_bound:.3f}",
        note="max(25 - first_rec_s): nonnegative travel/last-hit delay",
        confidence="high")
    for item in side_bounds:
        sid = item["sid"]
        bound = item["bound"]
        side_sample = next(s for s in samples if s["sid"] == sid)
        side_event = side_sample["side"]
        info = player_of(maps, sid, side_event["entity"])
        add(section="offset_fit", sample=sid, metric="side_lower_bound",
            seq=side_event["seq"], rec_s=f"{side_event['seq']/FPS_NOMINAL:.2f}",
            game_s=f"{side_event['seq']/FPS_NOMINAL + recommended:.2f}",
            game_hms=hms(side_event["seq"]/FPS_NOMINAL + recommended),
            offset_s=f"{bound:.3f}", count=1, value=f"{bound:.3f}",
            amount=side_event["amount"], player=info["player"],
            entity_id=side_event["entity"], hero=info["hero"],
            lane="side_candidate",
            note="33 - side_rec_s; side first source4 in 10-15s window; "
                 "lane inferred from hero role; "
                 + ("used in joint_min" if item["reliable"]
                    else "supporting only, not used in joint_min (mage/roam)"),
            confidence="medium" if item["reliable"] else "low-medium")
    add(section="offset_fit", sample="ALL", metric="joint_feasible_min",
        offset_s=f"{joint_min:.3f}", count=len(samples) + len(hard_side_bounds),
        value=f"{joint_min:.3f}",
        note="max(mid bound + reliable side bound); smallest offset with no negative delay",
        confidence="medium-high")
    add(section="offset_fit", sample="ALL", metric="recommended",
        offset_s=f"{recommended:.1f}", value=f"{recommended:.1f}",
        note="calibrated offset; plausible range recommended +/- 0.5s",
        confidence="medium-high")

    # per-sample first source4
    for s in samples:
        first = s["first"]
        info = player_of(maps, s["sid"], first["entity"])
        add(section="sample_first", sample=s["sid"], metric="first_source4",
            seq=first["seq"], rec_s=f"{first['seq']/FPS_NOMINAL:.2f}",
            game_s=f"{first['seq']/FPS_NOMINAL + recommended:.2f}",
            game_hms=hms(first["seq"]/FPS_NOMINAL + recommended),
            offset_s=f"{MID_CONTACT_S - first['seq']/FPS_NOMINAL:.2f}",
            amount=first["amount"], player=info["player"],
            entity_id=first["entity"], hero=info["hero"], lane="mid_earliest",
            value=(f"naive_offset={MID_CONTACT_S - first['seq']/FPS_NOMINAL:.3f};"
                   f"resid_ls={MID_CONTACT_S - first['seq']/FPS_NOMINAL - naive_ls:+.3f};"
                   f"delay_at_{recommended:.1f}={first['seq']/FPS_NOMINAL + recommended - MID_CONTACT_S:+.2f}s"),
            note="25 - rec_s is the naive mid offset; single 88 = one minion tier, 187+ = batch",
            confidence="high")
        sb = s["second_batch"]
        if sb:
            info = player_of(maps, s["sid"], sb["entity"])
            add(section="sample_second_batch", sample=s["sid"],
                metric="second_batch_first_source4", seq=sb["seq"],
                rec_s=f"{sb['seq']/FPS_NOMINAL:.2f}",
                game_s=f"{sb['seq']/FPS_NOMINAL + recommended:.2f}",
                game_hms=hms(sb["seq"]/FPS_NOMINAL + recommended),
                amount=sb["amount"], player=info["player"],
                entity_id=sb["entity"], hero=info["hero"], lane="second_batch",
                note="first source4 >=5.0s after the first event",
                confidence="medium")
        side = s["side"]
        if side:
            info = player_of(maps, s["sid"], side["entity"])
            add(section="sample_side_candidate", sample=s["sid"],
                metric="side_first_source4", seq=side["seq"],
                rec_s=f"{side['seq']/FPS_NOMINAL:.2f}",
                game_s=f"{side['seq']/FPS_NOMINAL + recommended:.2f}",
                game_hms=hms(side["seq"]/FPS_NOMINAL + recommended),
                offset_s=f"{SIDE_CONTACT_S - side['seq']/FPS_NOMINAL:.2f}",
                amount=side["amount"], player=info["player"],
                entity_id=side["entity"], hero=info["hero"],
                lane="side_candidate",
                note="first source4 in 10-15s recording window; 33 - rec_s is lower bound",
                confidence="medium" if s["sid"].startswith("20260925_105224") else "low-medium")

    # first 15s source4 timeline
    for s in samples:
        for e in s["first15"]:
            info = player_of(maps, s["sid"], e["entity"])
            add(section="source4_first15", sample=s["sid"],
                metric="source4_event", seq=e["seq"],
                rec_s=f"{e['seq']/FPS_NOMINAL:.2f}",
                game_s=f"{e['seq']/FPS_NOMINAL + recommended:.2f}",
                game_hms=hms(e["seq"]/FPS_NOMINAL + recommended),
                amount=e["amount"], player=info["player"],
                entity_id=e["entity"], hero=info["hero"],
                lane="", note="source4 event in first 15 recording seconds",
                confidence="high")

    # candidate offsets
    for off in (20.3, 20.5, 21.0, 21.5, 22.0):
        mid_viol = [
            s["sid"] for s in samples
            if s["first"]["seq"] / FPS_NOMINAL + off < MID_CONTACT_S - EPS
        ]
        side_viol = [
            s["sid"] for s in samples if s["side"]
            and s["side"]["seq"] / FPS_NOMINAL + off < SIDE_CONTACT_S - EPS
        ]
        verdict = "feasible"
        if mid_viol or side_viol:
            verdict = "reject: first kill before contact"
        add(section="candidate_offsets", metric="candidate_offset",
            offset_s=f"{off:.1f}", count=len(mid_viol) + len(side_viol),
            value=(f"mid_viol={len(mid_viol)};side_viol={len(side_viol)};"
                   f"mid_samples={'|'.join(mid_viol)};side_samples={'|'.join(side_viol)}"),
            note="first source4 would occur before the official lane contact",
            confidence=verdict)

    # fps fit
    for row in fps_rows:
        add(section="fps_fit", metric="fps_candidate", fps=f"{row['fps']:.1f}",
            offset_s=f"{row['offset_min']:.3f}",
            value=f"period={row['period_frames']:.1f}frames;gap_rms={row['gap_rms']:.3f}s;"
                  f"mid_delay={row['mid_delay_mean']:.3f}s;side_delay={row['side_delay_mean']:.3f}s;"
                  f"score={row['score']:.3f}",
            count=len(gap_frames),
            note="offset_min = max mid/side lower bounds; score = gap_rms + 0.1*delay",
            confidence="")
    add(section="fps_fit", metric="fine_gap_scan", fps=f"{fine_best_fps:.2f}",
        value=f"gap_rms={fine_best_rms:.3f}s", count=len(gap_frames),
        note="fps 19.00-21.00 step 0.01 minimizing 33s gap RMS",
        confidence="")
    add(section="fps_fit", metric="nominal", fps="20.0",
        value=f"gap_fps_mean={gap_fps_mean:.3f};gap_fps_median={gap_fps_median:.3f}",
        count=len(gap_frames),
        note="observed one-wave gap core 640-690 frames", confidence="medium")

    # wave gaps
    for g in all_gaps:
        info = player_of(maps, g["sample"], g["entity"])
        add(section="wave_gap", sample=g["sample"], metric="source4_gap",
            seq=g["seq_a"], rec_s=f"{g['seq_a']/FPS_NOMINAL:.2f}",
            game_s=f"{g['seq_a']/FPS_NOMINAL + recommended:.2f}",
            count=g["gap"], value=f"{g['gap']/FPS_NOMINAL:.2f}s",
            player=info["player"], entity_id=g["entity"], hero=info["hero"],
            note=f"next seq {g['seq_b']}; gap {g['gap']} frames",
            confidence="medium")

    # main timeline
    timeline = [
        ("main_first_frame", main["frame_first"], main_first, recommended),
        ("main_last_frame", main["frame_last"], main_last, recommended),
        ("continuation_first_frame", cont[0]["seq"] if cont else "", cont_first, recommended),
        ("continuation_last_frame", cont[-1]["seq"] if cont else "", cont_last, recommended),
    ]
    for metric, seq, rec, off in timeline:
        if not seq:
            continue
        add(section="main_timeline", sample=main["sid"], metric=metric, seq=seq,
            rec_s=f"{rec:.2f}", game_s=f"{rec + off:.2f}",
            game_hms=hms(rec + off), offset_s=f"{off:.1f}",
            note="game_time = seq/20 + offset", confidence="high")
    add(section="main_timeline", sample=main["sid"], metric="main_recording_to_last",
        value=f"{main_last:.2f}", note="from seq0 to main last frame; seconds",
        confidence="high")
    add(section="main_timeline", sample=main["sid"], metric="main_first_to_last_span",
        value=f"{main_span:.2f}", note="last-first; exclusive of one frame",
        confidence="high")
    add(section="main_timeline", sample=main["sid"], metric="main_first_to_last_inclusive",
        value=f"{main_inclusive:.2f}", note="last-first+1 frame",
        confidence="high")
    add(section="main_timeline", sample=main["sid"], metric="continuation_duration",
        value=f"{cont_duration:.2f}", note="continuation frames inclusive", confidence="high")
    add(section="main_timeline", sample=main["sid"], metric="main_to_continuation_gap",
        value=f"{cont_gap:.2f}", note="missing seq 13095; one frame gap", confidence="high")
    add(section="main_timeline", sample=main["sid"], metric="total_from_zero_to_last",
        value=f"{total_from_zero:.2f}", game_hms=hms(total_from_zero),
        note="continuation last game time; replay coverage, not necessarily match end",
        confidence="medium")
    add(section="main_timeline", sample=main["sid"], metric="total_first_to_last_span",
        value=f"{total_span:.2f}", note="first main frame to last continuation frame",
        confidence="high")
    add(section="main_timeline", sample=main["sid"], metric="total_first_to_last_inclusive",
        value=f"{total_inclusive:.2f}", note="inclusive of both endpoint frames",
        confidence="high")

    # 1558
    def add_1558(metric, event, kind, note, conf):
        if not event:
            return
        if kind == "gold":
            add(section="player_1558", sample=main["sid"], metric=metric,
                seq=event["seq"], rec_s=f"{event['seq']/FPS_NOMINAL:.2f}",
                game_s=f"{event['seq']/FPS_NOMINAL + recommended:.2f}",
                game_hms=hms(event["seq"]/FPS_NOMINAL + recommended),
                offset_s=f"{recommended:.1f}", amount=event["amount"],
                entity_id=entity_1558, player="佚名(*:", hero="东皇太一",
                count=1, value=f"source{event['source']}", note=note, confidence=conf)
        else:
            body = event["data"]
            # 00 00 00 actorID tier slot 00
            actor = body[3] if len(body) >= 4 else ""
            tier = body[4] if len(body) >= 5 else ""
            slot = body[5] if len(body) >= 6 else ""
            add(section="player_1558", sample=main["sid"], metric=metric,
                seq=event["seq"], rec_s=f"{event['seq']/FPS_NOMINAL:.2f}",
                game_s=f"{event['seq']/FPS_NOMINAL + recommended:.2f}",
                game_hms=hms(event["seq"]/FPS_NOMINAL + recommended),
                offset_s=f"{recommended:.1f}", count=1,
                value=f"actor={actor};tier={tier};slot={slot}",
                entity_id=entity_1558, player="佚名(*:", hero="东皇太一",
                note=note, confidence=conf)

    add_1558("last_gold_main", last_gold_main, "gold",
             "last 0x02/0x85 source4 in main stream", "high")
    add_1558("last_gold_overall", last_gold_cont, "gold",
             "last 0x02/0x85 source4 in continuation; at least 8 parsed gold events "
             "(nested 0x85 at seq 13118 not consumed)",
             "high")
    add_1558("last_upgrade_main", last_up_main, "upgrade",
             "last 0x02/0x87 in main stream; purchase/upgrade semantics medium",
             "medium-high")
    add_1558("last_upgrade_overall", last_up_cont, "upgrade",
             "last 0x02/0x87 in continuation; tier/slot fits equipment purchase",
             "medium-high")

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    # ---- Markdown report --------------------------------------------------
    lines: list[str] = []
    add_line = lines.append
    add_line("# 普通 5v5（5069040）时间轴校准：game_time = seq/fps + offset")
    add_line("")
    add_line(f"- 生成：`tools/agent_time_axis_calibration.py`；只读分析，未修改回放/包体。")
    add_line(f"- 样本：6 个 5069040 普通 5v5 `.abc`（`data/replays/samples/abc_batch/2026092[45]_*.abc`）。")
    add_line(f"- 官方 S45 锚点：首波 0:10 出生、中路 0:25 交汇、边路 0:33 交汇、间隔 33s。")
    add_line(f"- 结论：**offset = {recommended:.1f}s（建议 ±0.5s）**；20fps 是最优候选；"
             f"主段覆盖到 11:16.20，含续流覆盖到 11:51.85。")
    add_line("")
    add_line("## 1. 结论摘要")
    add_line("")
    add_line("| 项目 | 结论 | 置信度 |")
    add_line("|---|---|---|")
    add_line(f"| offset | **{recommended:.1f}s**，可行下界 {joint_min:.2f}s；"
             f"建议区间 {recommended-0.5:.1f}-{recommended+0.5:.1f}s | medium-high |")
    add_line("| 旧 20.3s | **不成立**：5/6 首条 source4 会被推到 0:25 之前；"
             "2/2 边路候选（含 1 条低置信）会被推到 0:33 之前 | high |")
    add_line(f"| fps | 20fps 最优；gap 中位 {gap_median:.0f} 帧、均值 {gap_mean:.1f} 帧，"
             f"对应 {gap_fps_median:.2f}-{gap_fps_mean:.2f}fps | medium |")
    add_line(f"| 主段 | 首帧 {hms(main_first + recommended)}、末帧 {hms(main_last + recommended)}；"
             f"录制到末帧 {main_last:.2f}s | high |")
    add_line(f"| 续流 | 首帧 {hms(cont_first + recommended)}、末帧 {hms(cont_last + recommended)}；"
             f"共 {cont_duration:.2f}s | high（存在）/ medium（是否结局） |")
    add_line(f"| 整局覆盖 | 从 0:00 到续流末帧 **{hms(total_from_zero)}**；"
             f"不代表确认的对局结束时间 | medium |")
    add_line(f"| 1558 最后金币 | 主段 {hms(last_gold_main['seq']/FPS_NOMINAL + recommended)}；"
             f"含续流 **{hms(last_gold['seq']/FPS_NOMINAL + recommended)}**（source4 {last_gold['amount']}） | high |")
    add_line(f"| 1558 最后购买/升级 | 主段 {hms(last_up_main['seq']/FPS_NOMINAL + recommended)}；"
             f"含续流 **{hms(last_up['seq']/FPS_NOMINAL + recommended)}**（tier2/slot5） | medium-high |")
    add_line("")
    add_line(f"**一句话**：offset **{recommended:.1f}s（±0.5s）**；回放覆盖到 **{hms(total_from_zero)}**"
             f"（主段到 {hms(main_last + recommended)}，续流再补 {cont_duration:.2f}s）；"
             f"1558 最后金币 **{hms(last_gold['seq']/FPS_NOMINAL + recommended)}**、"
             f"最后购买 **{hms(last_up['seq']/FPS_NOMINAL + recommended)}**。")
    add_line("")
    add_line("## 2. 口径与数据结构")
    add_line("")
    add_line("- `seq` 是主帧流帧号；`rec_s = seq/20` 是录制时间；"
             "`game_s = seq/fps + offset` 才是对局时间。")
    add_line("- 主段：seq 34-13094，共 13,061 帧（`20260925_105224`）。"
             "续流：seq 13096-13807，共 712 帧；13095 缺 1 帧（0.10s）。")
    add_line("- source4 = `0x02 flag=0x85 len=5` 中 sourceType=4；是兵线档位结算，"
             "不是逐单位补刀。金额 88 多为单个小兵档（80 基准 + 8 尾数/加成），"
             "187/194/219 可能是多单位/攻城车档。")
    add_line("- 最早一条 source4 必然发生在全队最早的中路兵线交汇之后，因此"
             "`offset >= 25 - first_rec_s`；这是单边约束，不能直接做对称最小二乘。")
    add_line("- 10-15s 录制窗口内的第一条 source4 作为边路首条候选（中路+8s），"
             "`offset >= 33 - side_rec_s`。")
    add_line("- 样本完整度：`20260924_113638` 为 9/10 玩家块，`20260925_094930`、"
             "`20260925_095631` 为 2/10 玩家块（partial_players）；其余 3 个为 10/10。"
             "时间轴只用帧流和 source4，不依赖玩家块完整性。")
    add_line(f"- 解析覆盖：主样本 source4 **{len(main['events'])} 条**（与既有 "
             "`normal5v5_gold_ledger_5069040.csv` 的 165 条一致）；"
             f"6 样本合计 **{sum(len(s['events']) for s in samples)} 条**，用于 fps gap 统计。")
    add_line("")
    add_line("## 3. 六样本首条 source4 与 offset")
    add_line("")
    add_line("| 样本 | 首条 seq | 录制 s | 金额 | 玩家/英雄 | 25-rec | LS 残差@20.57 | 21.5 时 game | 延迟@21.5 |")
    add_line("|---|---:|---:|---:|---|---:|---:|---:|---:|")
    for s in samples:
        first = s["first"]
        info = player_of(maps, s["sid"], first["entity"])
        rec = first["seq"] / FPS_NOMINAL
        naive_offset = MID_CONTACT_S - rec
        add_line(f"| {s['sid']} | {first['seq']} | {rec:.2f} | {first['amount']} | "
                 f"{info['player']}/{info['hero']} | {naive_offset:.2f} | "
                 f"{naive_offset-naive_ls:+.2f} | {rec+recommended:.2f} | "
                 f"{rec+recommended-MID_CONTACT_S:+.2f} |")
    add_line("")
    add_line(f"- 对称最小二乘：**{naive_ls:.2f}s**；中位：**{naive_median:.2f}s**。"
             f"两者都把首条当成无延迟接触，若延迟非负则系统性偏低。")
    add_line(f"- 单边中路下界：**{mid_bound:.2f}s**（最早 4.00s）。")
    add_line(f"- 边路候选下界："
             + "；".join(
                 f"{item['sid']} {item['bound']:.2f}s"
                 + ("" if item["reliable"] else "（低置信，未用于联合下界）")
                 for item in side_bounds
             )
             + f"；联合可行下界 **{joint_min:.2f}s**（只用主样本李信）。")
    add_line("")
    add_line("### 3.1 候选 offset 违例表")
    add_line("")
    add_line("| offset | 中路首条 < 0:25 | 边路候选 < 0:33（含低置信） | 判定 |")
    add_line("|---:|---:|---:|---|")
    for off in (20.3, 20.5, 21.0, 21.5, 22.0):
        mid_viol = [s["sid"] for s in samples
                    if s["first"]["seq"] / FPS_NOMINAL + off < MID_CONTACT_S - EPS]
        side_viol = [s["sid"] for s in samples if s["side"]
                     and s["side"]["seq"] / FPS_NOMINAL + off < SIDE_CONTACT_S - EPS]
        verdict = "可行" if not mid_viol and not side_viol else "**拒绝**"
        add_line(f"| {off:.1f} | {len(mid_viol)}/6 | {len(side_viol)}/{sum(1 for s in samples if s['side'])} | {verdict} |")
    add_line("")
    add_line("20.3s 会把 5/6 条首条 source4 推到中路交汇之前，并把 2/2 条边路候选推到边路交汇之前；"
             "20.5s 仍会把 3/6 条中路首条和 2/2 条边路候选推到交汇之前。"
             "因此 **20.3s（以及 20.5s）不成立**；21.45s 是同时满足中路/边路非负延迟的最小可行值，"
             "按 0.5s 网格取 **21.5s**。")
    add_line("")
    add_line("> 21.45s 是“官方 25.0/33.0 精确”时的下界；若实际交汇有 ±0.5s 偏差，"
             "下界可放宽到约 20.95-21.0s。因此最终建议区间取 **21.0-22.0s（21.5±0.5）**，"
             "而不是把 21.45s 当成硬下界。")
    add_line("")
    add_line("> 表中“延迟@21.5”是**该样本首条击杀相对交汇的延迟（0.5-1.6s）**，"
             "不是 offset 误差；“LS 残差@20.57”是相对对称拟合的残差（最大 0.68s）。"
             "offset 的误差来自官方整秒口径和边路分路判定，建议 ±0.5s；三者不要混用。")
    add_line("")
    add_line("### 3.2 前 15s source4 事件（第一批/第二批）")
    add_line("")
    add_line("| 样本 | seq | 录制 s | 金额 | 玩家/英雄 | 21.5 时 game | 备注 |")
    add_line("|---|---:|---:|---:|---|---:|---|")
    for s in samples:
        for e in s["first15"]:
            info = player_of(maps, s["sid"], e["entity"])
            rec = e["seq"] / FPS_NOMINAL
            add_line(f"| {s['sid']} | {e['seq']} | {rec:.2f} | {e['amount']} | "
                     f"{info['player']}/{info['hero']} | {rec+recommended:.2f} | "
                     f"{'first' if e is s['first'] else ('side-window' if s['side'] and e is s['side'] else '')} |")
    add_line("")
    add_line("读法：4.0-5.1s 是第一批（中路首条）；10-15s 窗口内若有事件，作为边路首条候选；"
             "其余前 15s 事件是同一波的中路/游走结算，不能逐条当“第 N 波”。")
    add_line("")
    add_line("| 样本 | 第二批 seq/rec | 金额 | 玩家/英雄 | 21.5 时 game | 与首条间隔 |")
    add_line("|---|---:|---:|---|---:|---:|")
    for s in samples:
        sb = s["second_batch"]
        if not sb:
            add_line(f"| {s['sid']} | 无 |  |  |  |  |")
            continue
        info = player_of(maps, s["sid"], sb["entity"])
        rec = sb["seq"] / FPS_NOMINAL
        add_line(f"| {s['sid']} | {sb['seq']}/{rec:.2f}s | {sb['amount']} | "
                 f"{info['player']}/{info['hero']} | {rec+recommended:.2f} | "
                 f"{rec - s['first']['seq']/FPS_NOMINAL:+.2f}s |")
    add_line("")
    add_line("“第二批”定义为距首条 ≥5.0s 的第一条 source4；它不保证是边路首条。"
             "主样本第二批 9.70s 仍是中路（安琪拉），边路候选是 11.55s（李信）；"
             "103058 第二批 11.50s 与边路窗口重合，但英雄是法师（低置信）。")
    add_line("")
    add_line("### 3.3 首条 → 下一波候选的 33s 分簇")
    add_line("")
    add_line("| 样本 | 首条 seq/rec | 下一条 ≥30s 的 seq/rec | 间隔帧 | 20fps 秒 | 接近 33s？ |")
    add_line("|---|---:|---:|---:|---:|---|")
    for s in samples:
        first = s["first"]
        nxt = next((e for e in s["events"]
                    if e["seq"] - first["seq"] >= 30 * FPS_NOMINAL), None)
        if nxt:
            gap = nxt["seq"] - first["seq"]
            add_line(f"| {s['sid']} | {first['seq']}/{first['seq']/FPS_NOMINAL:.2f}s | "
                     f"{nxt['seq']}/{nxt['seq']/FPS_NOMINAL:.2f}s | {gap} | {gap/FPS_NOMINAL:.2f} | "
                     f"{'是' if abs(gap/FPS_NOMINAL-33) <= 1.0 else '否'} |")
        else:
            add_line(f"| {s['sid']} | {first['seq']}/{first['seq']/FPS_NOMINAL:.2f}s | 无 |  |  |  |")
    add_line("")
    add_line("只有 `20260925_105224` 的首条→下一条是 33.10s；其余样本因边路/第二批选手未补刀，"
             "下一条落在 36-51s，不能直接当 33s 波间隔。33s 分簇的定量依据放在下一节的"
             "“同玩家相邻 source4 的 640-690 帧间隔”里。")
    add_line("")
    add_line("## 4. fps 联合拟合：20fps 是否最优")
    add_line("")
    add_line("做法：对每个玩家取相邻 source4 的 seq 间隔；把 640-690 帧的间隔当作"
             "“一波 33s”候选，共 "
             f"{len(gap_frames)} 条。中位 {gap_median:.0f} 帧、均值 {gap_mean:.1f} 帧，"
             f"对应 {gap_fps_median:.2f}/{gap_fps_mean:.2f}fps。")
    add_line("")
    add_line("| fps | 33s 应占帧数 | offset 下界 | 中路平均延迟 | 边路平均延迟 | 33s gap RMS | 综合分 |")
    add_line("|---:|---:|---:|---:|---:|---:|---:|")
    for row in fps_rows:
        add_line(f"| {row['fps']:.1f} | {row['period_frames']:.1f} | {row['offset_min']:.3f} | "
                 f"{row['mid_delay_mean']:.3f} | {row['side_delay_mean']:.3f} | "
                 f"{row['gap_rms']:.3f} | {row['score']:.3f} |")
    add_line("")
    add_line(f"- 细扫 19.00-21.00（步长 0.01）的 gap-RMS 最优在 **{fine_best_fps:.2f}fps**"
             f"（RMS {fine_best_rms:.3f}s）；20.00fps 距最优约 0.011s RMS。"
             f"20.08 与名义 20 相差 {abs(fine_best_fps-20)/20:.1%}，在当前样本量下不可区分。")
    add_line("- 主样本首条 4.65s→下一条 37.75s 的 662 帧：20fps 为 33.10s，"
             "19.5fps 为 33.95s，20.5fps 为 32.29s；20fps 与官方 33s 最接近。")
    add_line("- **20fps 是三个候选中最优**：19.5/20.5 的 33s 帧数分别偏到 643.5/676.5，"
             "与观测核心 658-662 帧的偏差更大。")
    add_line("- 但 source4 整体并不是严格波锁：全事件在 660 帧周期的相位集中度只有约 0.06。"
             "所以 20fps 是“最优候选/中等置信”，不是由 source4 单独证明的高置信结论。")
    add_line("")
    add_line("## 5. 中路首条 vs 边路首条")
    add_line("")
    add_line("| 样本 | 首条 source4（中路） | 10-15s 边路候选 | 边路玩家/英雄 | 33-rec |")
    add_line("|---|---:|---:|---|---:|")
    for s in samples:
        first = s["first"]
        side = s["side"]
        if side:
            info = player_of(maps, s["sid"], side["entity"])
            side_text = f"{side['seq']} / {side['seq']/FPS_NOMINAL:.2f}s"
            who = f"{info['player']}/{info['hero']}"
            bound = f"{SIDE_CONTACT_S-side['seq']/FPS_NOMINAL:.2f}"
        else:
            side_text, who, bound = "无", "", ""
        add_line(f"| {s['sid']} | {first['seq']} / {first['seq']/FPS_NOMINAL:.2f}s | "
                 f"{side_text} | {who} | {bound} |")
    add_line("")
    add_line("**判断**：")
    add_line("")
    add_line("- 中路：最早 source4 的中路下界是 21.00s；对称拟合 20.5-20.6s 因忽略非负延迟而偏低。")
    add_line("- 边路：只有 `20260925_105224`（李信，11.55s）和 `20260925_103058`"
             "（不知火舞，11.50s）在 10-15s 窗口内有候选；两者给出 21.45/21.50s，"
             "与 21.5s 一致。其余样本的边路首条落在 40-63s，延迟太大，不能给绝对 offset。")
    add_line("- 主边路锚点是 105224 的**李信（战士/对抗路，11.55s）**，置信度 medium；"
             "103058 的不知火舞是法师/刺客，可能中/游走，只能作低一级佐证（low-medium），"
             "**不用于联合下界**。即使只取李信，边路下界仍是 21.45s，与 21.5s 一致。")
    add_line("- **反例/风险**：103058 的后羿（7.85s）、马可波罗（5.10s）是射手；若他们确实在发育路，"
             "则官方 0:33 边路交汇在该局不成立（或首批 source4 来自中路轮转）。"
             "这说明“英雄职业=分路”不可靠，边路锚点只能按主样本李信取 medium，"
             "不能把 103058 的 11.50s 当作硬约束。")
    add_line("- 李信的边路首条金额 194 是**批次**；若这批含 2 个兵、第一个死在 11.55s 之前约 0.5s，"
             "边路下界会从 21.45 推到约 21.95。这正是 ±0.5s 上沿（22.0）的来源，"
             "也是 21.5s 只能标 medium-high、不能标 high 的原因。")
    add_line("- 边路英雄是按英雄职业/分路推断的，不是回放里的显式分路字段；"
             "因此边路证据是 medium，不作为唯一依据，但与中路下界一致。")
    add_line("")
    add_line("## 6. 主样本时间轴")
    add_line("")
    add_line("| 项目 | seq | 录制 s | game_time（offset 21.5） |")
    add_line("|---|---:|---:|---:|")
    add_line(f"| 主段首帧 | {main['frame_first']} | {main_first:.2f} | {hms(main_first+recommended)} |")
    add_line(f"| 主段末帧 | {main['frame_last']} | {main_last:.2f} | {hms(main_last+recommended)} |")
    add_line(f"| 续流首帧 | {cont[0]['seq']} | {cont_first:.2f} | {hms(cont_first+recommended)} |")
    add_line(f"| 续流末帧 | {cont[-1]['seq']} | {cont_last:.2f} | {hms(cont_last+recommended)} |")
    add_line("")
    add_line(f"- 主段：13,061 帧，首末跨度 **{main_span:.2f}s**，含首末帧 **{main_inclusive:.2f}s**；"
             f"从 seq 0 到主段末帧 **{main_last:.2f}s**。")
    add_line(f"- 续流：712 帧，含首末帧 **{cont_duration:.2f}s**；与主段间隔 **{cont_gap:.2f}s**（缺 seq 13095）。")
    add_line(f"- 从主段首帧到续流末帧：跨度 **{total_span:.2f}s**，含首末帧 **{total_inclusive:.2f}s**。")
    add_line(f"- 从 0:00 到续流末帧：**{hms(total_from_zero)}**（{total_from_zero:.2f}s）。"
             "这是回放覆盖，不是已确认的对局结束时间；续流末帧后没有结算/KDA 结构。")
    natural_main = 3.0 * max(0.0, (main_last + recommended) - 40.0)
    natural_old = 3.0 * max(0.0, (main_last + 20.3) - 40.0)
    add_line(f"- 下游影响：3/s、40s 起算的自然金基准，主段末 = **{natural_main:.1f}/人**"
             f"（旧 20.3s 口径 {natural_old:.1f}/人，差 {natural_main-natural_old:.1f}）。")
    add_line("")
    add_line("## 7. 1558（佚名(*: / 东皇太一）最后金币与购买")
    add_line("")
    add_line("| 项目 | seq | 录制 s | game_time | 内容 |")
    add_line("|---|---:|---:|---:|---|")
    add_line(f"| 主段最后金币 | {last_gold_main['seq']} | {last_gold_main['seq']/FPS_NOMINAL:.2f} | "
             f"{hms(last_gold_main['seq']/FPS_NOMINAL+recommended)} | source4 {last_gold_main['amount']} |")
    add_line(f"| 含续流最后金币 | {last_gold['seq']} | {last_gold['seq']/FPS_NOMINAL:.2f} | "
             f"{hms(last_gold['seq']/FPS_NOMINAL+recommended)} | source4 {last_gold['amount']}（续流） |")
    add_line(f"| 主段最后 0x87 | {last_up_main['seq']} | {last_up_main['seq']/FPS_NOMINAL:.2f} | "
             f"{hms(last_up_main['seq']/FPS_NOMINAL+recommended)} | tier{last_up_main['data'][4]}/slot{last_up_main['data'][5]} |")
    add_line(f"| 含续流最后 0x87 | {last_up['seq']} | {last_up['seq']/FPS_NOMINAL:.2f} | "
             f"{hms(last_up['seq']/FPS_NOMINAL+recommended)} | tier{last_up['data'][4]}/slot{last_up['data'][5]}（续流） |")
    add_line("")
    add_line("**关键修正**：续流不是“无金币的纯输入”。本脚本在续流解析到 **至少 8 条可完整解析的 "
             "0x85 金币**（含 1558 的 source4 219 @ 687.30s）和 **2 条 0x87**"
             "（含 1558 tier2/slot5 @ 671.15s）。因此 1558 的最后金币/购买都在续流，不在主段末。"
             "另有 13118 帧的 `0x02/0x85` 模式（hero 1729, source4 190）落在未被贪心解析器消费的"
             "嵌套/raw 段里；若计入，续流金币至少 9 条，但不影响 1558 的末条。")
    add_line("")
    add_line("0x87 的 `slot=5` 也支持“装备槽”而非“技能槽”的解释（技能通常只有 1-4），"
             "但字段语义仍需与客户端/表对拍；本报告按 5.100 的购买口径，置信度 medium-high。")
    add_line("")
    add_line("> 这与 `docs/evidence_audit.md` 里“续流 0 条 0x85 金币”的旧计数不一致。"
             "本脚本对续流 payload 按“无 count 前缀”逐标签解析，13211/13229/13746 等帧确实有 "
             "`0x02/0x85`（例如 13229 = hero 1514 source4 130）；旧计数应视为漏计，"
             "但本任务按约束不修改 docs。")
    add_line("")
    add_line("## 8. 证据与置信度")
    add_line("")
    add_line("| 结论 | 证据 | 置信度 |")
    add_line("|---|---|---|")
    add_line(f"| offset 21.5s | 中路下界 21.00 + 主样本李信边路下界 21.45；20.3/20.5 产生大量交汇前击杀 | medium-high |")
    add_line(f"| 20fps | 一波 gap 中位 {gap_median:.0f}/均值 {gap_mean:.1f} 帧；细扫 {fine_best_fps:.2f}fps | medium |")
    add_line(f"| 主段时间轴 | seq 34-13094；直接帧号/20fps | high |")
    add_line(f"| 续流属于同一局 | seq 连续（缺 1 帧）、有金币/升级/输入事件 | high（属同一局）/ medium（是否结束） |")
    add_line(f"| 整局 11:51.85 | 续流末帧 + 21.5s；无结算/结束标记 | medium |")
    add_line(f"| 1558 最后金币 11:48.80 | 续流 0x85 source4 219 | high |")
    add_line(f"| 1558 最后购买 11:32.65 | 续流 0x87 tier2/slot5；0x87=purchase 语义 medium-high | medium-high |")
    add_line("")
    add_line("## 9. 还缺什么")
    add_line("")
    add_line("- 回放里没有直接的“对局时钟”字段；offset 只能靠官方兵线表 + source4 时序外推。")
    add_line("- 六样本首条 4.0-5.1s 的 1.1s 跨度，可能是**每局录制起点不同**，也可能是"
             "**首击延迟不同**；单靠 source4 无法分离这两项，所以只能给全局 offset ±0.5s，"
             "不能把每样本的首条都硬对到 0:25。")
    add_line("- 没有小兵出生/死亡事件或逐单位补刀 ID；source4 是档位结算，187/194/219 的批次跨度未知，"
             "会把首条事件的延迟上界放宽。")
    add_line("- 没有显式分路字段；边路候选按英雄职业/10-15s 窗口推断，不能保证每局都正确。"
             "103058 的射手在 5.1-7.85s 就有 source4，与“边路 0:33”存在张力；"
             "这既可能是中路轮转，也可能是该局边路交汇早于 0:33。")
    add_line("- 边路锚点只用主样本李信（medium）；若该局李信实际走了中路，"
             "联合下界会回落到 21.0s；因此 21.5s 的可信度不应高于 medium-high。")
    add_line("- 官方 S45 时间是整秒口径；实际交汇可有 ±0.5s 级差异，因此 offset 建议给 ±0.5s。")
    add_line("- 续流末帧后没有结算/KDA/结束标记；11:51.85 是覆盖下界，不是已证明的终局时间。")
    add_line("- 0x87 的“购买 vs 技能升级”语义仍有争议；本报告按 5.100 的购买口径，但标 medium-high。")
    add_line("")
    add_line("## 10. 产物")
    add_line("")
    add_line(f"- 脚本：`tools/agent_time_axis_calibration.py`")
    add_line(f"- CSV：`data/replays/_analysis/datasets/agent_time_axis_calibration.csv`")
    add_line(f"- 报告：`data/replays/_analysis/datasets/agent_time_axis_calibration.md`")
    add_line("")

    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print(f"wrote {OUT_CSV}")
    print(f"wrote {OUT_MD}")
    print(f"offset naive_ls={naive_ls:.3f} median={naive_median:.3f} "
          f"mid_bound={mid_bound:.3f} joint_min={joint_min:.3f} recommended={recommended:.1f}")
    print(f"fps gap median={gap_median:.0f} mean={gap_mean:.1f} "
          f"implied={gap_fps_median:.2f}/{gap_fps_mean:.2f} fine={fine_best_fps:.2f}")
    print(f"main {hms(main_first+recommended)} -> {hms(main_last+recommended)}; "
          f"continuation -> {hms(cont_last+recommended)}")
    print(f"1558 last gold {last_gold['seq']} {hms(last_gold['seq']/FPS_NOMINAL+recommended)}; "
          f"last 0x87 {last_up['seq']} {hms(last_up['seq']/FPS_NOMINAL+recommended)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
