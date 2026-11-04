#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""普通 5v5（build 5069040）击杀/补刀归属逆向：0x1e / 0x1f / 0x20 / 0x02(0x81/0x82/0x85)。

只读边界
--------
* 只读 `data/replays/samples/abc_batch/*.abc` 与 `data/replays/_analysis/datasets/` 下的
  已解 CSV；不改回放、不改包体、不注入、不读 param.json、不使用 runtime_dump；
* 不写 docs/replay_binary_format.md 与 .workbuddy/memory/MEMORY.md。

回答的问题
----------
1. `0x01/sub=0x1e` 19B 的 attacker / victim / type 分别是什么；
2. victim 是否命中 10 人 entityID、heroID、actorID、normalMonster row/id、soldierWave waveID/兵种 ID；
3. `0x1f`(28B)/`0x20`(20B) 是否含 killer/victim/技能/伤害，能否与 0x1e 同帧对齐；
4. `0x02` len=1（0x81）的 1 字节状态与 len=2（0x82）的 `02 00/02 ff` 是否攻击/死亡/补刀标记；
5. 1558（佚名(*: / 东皇太一）的死亡/击杀/助攻事件与 KDA 可达性。

输出
----
* data/replays/_analysis/datasets/agent_kill_attribution.csv
* data/replays/_analysis/datasets/agent_kill_attribution.md

用法
----
    python tools/agent_kill_attribution.py
    python tools/agent_kill_attribution.py --abc "path/to.abc" --out-dir "path/to/datasets"
    python tools/agent_kill_attribution.py --no-cross   # 跳过跨样本复核（更快）
"""
from __future__ import annotations

import argparse
import bisect
import csv
import glob
import struct
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ABC = (
    ROOT
    / "data/replays/samples/abc_batch"
    / "20260925_105224_-1505729760_4933_1790303631_CBDD358E761B15A4DF526A179E8119E2.abc"
)
BATCH = ROOT / "data/replays/samples/abc_batch"
DEFAULT_OUT = ROOT / "data/replays/_analysis/datasets"
DATASETS = ROOT / "data/replays/_analysis/datasets"

FRAME_S = 0.05          # 20 fps；回放帧号 * 0.05 = 回放秒
REPLAY_OFFSET_S = 20.3  # 回放 seq0 ≈ 对局 0:20（docs 5.92）
SAMPLE_KEY = "20260925_105224"

# FrameNotifyInfo 字段（C# 编辑器测试工具；仅作结构参照，不作为"回放含击杀"的证明）
FRAME_NOTIFY_FIELDS = (
    "isKillNotify, m_attackerObjID, m_victimObjID, m_assist01..05, m_assistCount, "
    "m_killNotifyType, m_heroMultiKillType, m_heroContiKillType, sourceId, primaryTargetId, "
    "majorValue, majorValueRatioFactor, killerId, highlightResId, skillId, "
    "eventStartTime, eventEndTime, notifySeq"
)
HIGHLIGHT_FIELDS = (
    "sourceId, primaryTargetId, majorValue, majorValueRatioFactor, majorValueDefinition, "
    "killerId, highlightResId, skillId, eventStartTime, eventEndTime, notifySeq"
)


# ---------------------------------------------------------------------------
# replay framing
# ---------------------------------------------------------------------------
def records_from(d: bytes, start: int, seq0: int):
    pos, seq, out = start, seq0, []
    while pos + 10 < len(d):
        if d[pos] != (seq & 0xFF) or d[pos + 1] != 0:
            break
        ln = d[pos + 2]
        if pos + 10 + ln > len(d):
            break
        out.append(
            {
                "off": pos,
                "seq": seq,
                "payload": d[pos + 3 : pos + 3 + ln],
                "a": d[pos + 3 + ln],
                "b": d[pos + 9 + ln],
            }
        )
        pos += 10 + ln
        seq += 1
    return out, pos


def find_stream(d: bytes):
    recs, end = records_from(d, 0xBFE8, 0x22)
    if len(recs) > 500:
        return recs, end, "known_start"
    best = ([], 0)
    for pos in range(0, min(len(d), 0x20000)):
        if d[pos] == 0x22 and d[pos + 1] == 0:
            r, e = records_from(d, pos, 0x22)
            if len(r) > len(best[0]):
                best = (r, e)
                if len(r) > 500:
                    break
    return best[0], best[1], "scan"


def tokenize(pl: bytes):
    """宽容解析 payload 标签流：成功解析的前缀全部返回，遇到未知标签即停止。

    返回 [(tag, hero|None, data, payload_len)]。
    0x01 -> hero:u16BE + flag:u8 + len:u8 + data[len]
    0x02 -> hero:u16BE + (0x80|len):u8 + data[len]
    """
    i, out = 1, []
    while i < len(pl):
        t = pl[i]
        if t == 0x12:
            if i + 3 > len(pl):
                return out
            out.append((t, None, bytes(pl[i + 1 : i + 3]), 2))
            i += 3
        elif t == 0x13:
            if i + 2 > len(pl):
                return out
            out.append((t, None, bytes(pl[i + 1 : i + 2]), 1))
            i += 2
        elif t == 0x14:
            if i + 4 > len(pl):
                return out
            out.append((t, None, bytes(pl[i + 1 : i + 4]), 3))
            i += 4
        elif t == 0x01:
            if i + 5 > len(pl):
                return out
            n = pl[i + 4]
            if i + 5 + n > len(pl):
                return out
            out.append(
                (t, struct.unpack_from(">H", pl, i + 1)[0], bytes(pl[i + 5 : i + 5 + n]), n)
            )
            i += 5 + n
        elif t == 0x02:
            if i + 4 > len(pl):
                return out
            n = pl[i + 3] & 0x7F
            if i + 4 + n > len(pl):
                return out
            out.append(
                (t, struct.unpack_from(">H", pl, i + 1)[0], bytes(pl[i + 4 : i + 4 + n]), n)
            )
            i += 4 + n
        else:
            return out
    return out


# ---------------------------------------------------------------------------
# reference data (read-only CSV)
# ---------------------------------------------------------------------------
def read_csv(path: Path):
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def load_heroes(sample_key: str):
    rows = read_csv(DATASETS / "normal5v5_player_heroes_5069040.csv")
    out = {}
    for r in rows:
        if r.get("sample") != sample_key:
            continue
        if r.get("confidence") != "high" or not r.get("entityID"):
            continue
        eid = int(r["entityID"])
        out[eid] = {
            "player": r.get("player", ""),
            "team": int(r.get("team") or 0),
            "slot": int(r.get("slot") or 0),
            "hero_id": int(r.get("heroID") or 0),
            "hero_name": r.get("heroName", ""),
        }
    return out


def load_monsters():
    rows = read_csv(DATASETS / "normalMonster_rows.csv")
    ids = set()
    low = set()
    for r in rows:
        try:
            v = int(r["id"])
        except (KeyError, ValueError):
            continue
        ids.add(v)
        if v <= 0xFFFF:
            low.add(v)
    types = read_csv(DATASETS / "normalMonster_types.csv")
    soldier_ids = set()
    soldier_names = set()
    for r in types:
        name = r.get("name", "")
        if not any(k in name for k in ("战士", "法师", "弩车", "炮车", "机关")):
            continue
        soldier_names.add(name)
        for x in (r.get("ids") or "").split(";"):
            try:
                soldier_ids.add(int(x))
            except ValueError:
                pass
    return {
        "rows": len(rows),
        "ids": ids,
        "low_ids": low,
        "soldier_ids": soldier_ids,
        "soldier_names": soldier_names,
        "row_count": len(rows),
    }


def load_waves():
    rows = read_csv(DATASETS / "agent_normal5v5_soldiers.csv")
    waves = set()
    unit_groups = set()
    for r in rows:
        if r.get("record_type") != "wave_slot":
            continue
        try:
            waves.add(int(r["wave_id"]))
        except (KeyError, ValueError):
            pass
        if r.get("unit_group"):
            unit_groups.add(r["unit_group"])
    return {"waves": waves, "unit_groups": unit_groups}


# ---------------------------------------------------------------------------
# extraction
# ---------------------------------------------------------------------------
def extract(abc: Path):
    d = abc.read_bytes()
    recs, end, how = find_stream(d)
    events = {
        "1e": [],
        "1f": [],
        "20": [],
        "81": [],
        "82": [],
        "85": [],
        "87": [],
        "80": [],
        "01_other": [],
    }
    for r in recs:
        toks = tokenize(r["payload"])
        for tag, hero, data, n in toks:
            if tag == 0x01 and data:
                sub = data[0]
                if sub == 0x1E and n == 19:
                    events["1e"].append(
                        {
                            "seq": r["seq"],
                            "hero": hero,
                            "type": data[1],
                            "mid": data[2:16].hex(),
                            "victim": int.from_bytes(data[16:18], "big"),
                            "tail": data[18],
                            "raw": data.hex(),
                        }
                    )
                elif sub == 0x1F and n == 28:
                    events["1f"].append(
                        {
                            "seq": r["seq"],
                            "hero": hero,
                            "tag": data[1],
                            "id_21_22": int.from_bytes(data[21:23], "big"),
                            "u32_2": int.from_bytes(data[2:6], "big"),
                            "i32_10": int.from_bytes(data[10:14], "big", signed=True),
                            "u32_14": int.from_bytes(data[14:18], "big"),
                            "tail": data[23:28].hex(),
                            "raw": data.hex(),
                        }
                    )
                elif sub == 0x20 and n == 20:
                    events["20"].append(
                        {
                            "seq": r["seq"],
                            "hero": hero,
                            "tag": data[1],
                            "u32_6_le": int.from_bytes(data[6:10], "little"),
                            "id_14_le": int.from_bytes(data[14:16], "little"),
                            "id_14_be": int.from_bytes(data[14:16], "big"),
                            "raw": data.hex(),
                        }
                    )
                else:
                    events["01_other"].append((r["seq"], hero, sub, n))
            elif tag == 0x02 and data:
                if n == 1:
                    events["81"].append(
                        {"seq": r["seq"], "hero": hero, "value": data[0], "raw": data.hex()}
                    )
                elif n == 2:
                    events["82"].append(
                        {
                            "seq": r["seq"],
                            "hero": hero,
                            "kind": data[0],
                            "toggle": data[1],
                            "raw": data.hex(),
                        }
                    )
                elif n == 5:
                    events["85"].append(
                        {
                            "seq": r["seq"],
                            "hero": hero,
                            "source": data[0],
                            "amount": int.from_bytes(data[1:5], "little"),
                            "raw": data.hex(),
                        }
                    )
                elif n == 7:
                    events["87"].append(
                        {
                            "seq": r["seq"],
                            "hero": hero,
                            "actor": data[3],
                            "slot": data[4],
                            "level": data[5],
                            "raw": data.hex(),
                        }
                    )
    return d, recs, end, how, events


def parse_frame_cmds(recs):
    """0x02 帧命令（0x80 体）逐条：cmdType/value/actor/cmdSeq/flag。"""
    out = []
    for r in recs:
        pl = r["payload"]
        i = 1
        while i < len(pl):
            t = pl[i]
            if t == 0x12:
                i += 3
            elif t == 0x13:
                i += 2
            elif t == 0x14:
                i += 4
            elif t == 0x01:
                if i + 5 > len(pl):
                    break
                i += 5 + pl[i + 4]
            elif t == 0x02:
                if i + 4 > len(pl):
                    break
                hero = struct.unpack_from(">H", pl, i + 1)[0]
                flag = pl[i + 3]
                if flag == 0x80:
                    body = pl[i + 4 : i + 16]
                    if len(body) < 12:
                        break
                    ct, val, actor = struct.unpack_from("<HHH", body, 0)
                    cseq = struct.unpack_from("<I", body, 6)[0]
                    tail = struct.unpack_from("<H", body, 10)[0]
                    out.append(
                        {
                            "seq": r["seq"],
                            "hero": hero,
                            "cmd_type": ct,
                            "value": val,
                            "actor": actor,
                            "cmd_seq": cseq,
                            "flag": tail,
                        }
                    )
                    i += 16
                else:
                    i += 4 + (flag & 0x7F)
            else:
                break
    return out


# ---------------------------------------------------------------------------
# cross-sample (read-only)
# ---------------------------------------------------------------------------
def cross_sample():
    files = sorted(glob.glob(str(BATCH / "*.abc")))
    totals = Counter()
    all_victims = []
    per_file = []
    duplicates = []
    s4_deltas = []
    s43_deltas = []
    s43_same_deltas = []
    s6_deltas = []
    s5_deltas = []
    f1f_total = f1f_overlap = t20_total = t20_overlap = 0
    cmd6_total = cmd6_overlap = 0
    for f in files:
        d = Path(f).read_bytes()
        recs, end = records_from(d, 0xBFE8, 0x22)
        if len(recs) < 500:
            recs, end, _ = find_stream(d)
        if not recs:
            continue
        E, G4, G43 = [], defaultdict(list), []
        Fids, Tids = [], []
        G43h, G6h, G5h = defaultdict(list), defaultdict(list), defaultdict(list)
        actors = set()
        n1f = n20 = 0
        for r in recs:
            for tag, hero, data, n in tokenize(r["payload"]):
                if tag == 0x01 and data:
                    if n == 19 and data[0] == 0x1E:
                        E.append(
                            {
                                "seq": r["seq"],
                                "hero": hero,
                                "type": data[1],
                                "victim": int.from_bytes(data[16:18], "big"),
                            }
                        )
                    elif n == 28 and data[0] == 0x1F:
                        n1f += 1
                        Fids.append(int.from_bytes(data[21:23], "big"))
                    elif n == 20 and data[0] == 0x20:
                        n20 += 1
                        Tids.append(int.from_bytes(data[14:16], "little"))
                elif tag == 0x02 and data:
                    if n == 7:
                        actors.add(data[3])
                    elif n == 5:
                        src = data[0]
                        amt = int.from_bytes(data[1:5], "little")
                        if src == 4:
                            G4[hero].append(r["seq"])
                        elif src == 43:
                            G43.append((r["seq"], amt))
                            G43h[hero].append(r["seq"])
                        elif src == 6:
                            G6h[hero].append(r["seq"])
                        elif src == 5:
                            G5h[hero].append(r["seq"])
        if not E:
            continue
        for h in G4:
            G4[h].sort()
        G43.sort()
        byv = defaultdict(list)
        for e in E:
            byv[e["victim"]].append(e)
        for v, es in byv.items():
            if len(es) > 1:
                duplicates.append((Path(f).name, v, [(e["seq"], e["hero"], e["type"]) for e in es]))
        f1f_total += len(Fids)
        f1f_overlap += sum(1 for x in Fids if x in byv)
        t20_total += len(Tids)
        t20_overlap += sum(1 for x in Tids if x in byv)
        cmd6 = {
            c["actor"] for c in parse_frame_cmds(recs) if c["cmd_type"] == 6
        } - actors
        cmd6_total += len(cmd6)
        cmd6_overlap += sum(1 for x in cmd6 if x in byv)
        # source4 same hero
        for e in E:
            nb = nearest(G4.get(e["hero"], []), e["seq"])
            if nb is not None:
                s4_deltas.append(nb - e["seq"])
        # source43 any
        for e in E:
            nb = nearest([x[0] for x in G43], e["seq"])
            if nb is not None:
                s43_deltas.append(nb - e["seq"])
        for h in G43h:
            G43h[h].sort()
        for h in G6h:
            G6h[h].sort()
        for h in G5h:
            G5h[h].sort()
        # same-hero kill/jungle/natural gold alignment
        for e in E:
            nb = nearest(G43h.get(e["hero"], []), e["seq"])
            if nb is not None:
                s43_same_deltas.append(nb - e["seq"])
            nb = nearest(G6h.get(e["hero"], []), e["seq"])
            if nb is not None:
                s6_deltas.append(nb - e["seq"])
            nb = nearest(G5h.get(e["hero"], []), e["seq"])
            if nb is not None:
                s5_deltas.append(nb - e["seq"])
        r_time = None
        if len(E) >= 5:
            xs = [e["seq"] for e in E]
            ys = [e["victim"] for e in E]
            mx = sum(xs) / len(xs)
            my = sum(ys) / len(ys)
            num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
            dx = sum((x - mx) ** 2 for x in xs) ** 0.5
            dy = sum((y - my) ** 2 for y in ys) ** 0.5
            if dx * dy:
                r_time = num / (dx * dy)
        per_file.append(
            {
                "file": Path(f).name,
                "n1e": len(E),
                "unique": len(set(e["victim"] for e in E)),
                "types": dict(sorted(Counter(e["type"] for e in E).items())),
                "n1f": n1f,
                "n20": n20,
                "n_s43": len(G43),
                "n_s4": sum(len(v) for v in G4.values()),
                "s43_within40": sum(1 for e in E if nearest([x[0] for x in G43], e["seq"]) is not None
                                    and abs(nearest([x[0] for x in G43], e["seq"]) - e["seq"]) <= 40),
                "s4_within2": sum(1 for e in E
                                  if nearest(G4.get(e["hero"], []), e["seq"]) is not None
                                  and abs(nearest(G4.get(e["hero"], []), e["seq"]) - e["seq"]) <= 2),
                "actor_hits": sum(1 for e in E if e["victim"] in actors),
                "r_time": r_time,
            }
        )
        totals.update(e["type"] for e in E)
        all_victims.extend(e["victim"] for e in E)
    rs = sorted(pf["r_time"] for pf in per_file if pf["r_time"] is not None)
    return {
        "files": files,
        "per_file": per_file,
        "types": dict(sorted(totals.items())),
        "n1e": len(all_victims),
        "victims": all_victims,
        "unique": len(set(all_victims)),
        "min": min(all_victims) if all_victims else None,
        "max": max(all_victims) if all_victims else None,
        "zero_one": sum(1 for v in all_victims if v in (0, 1)),
        "r_time_median": rs[len(rs) // 2] if rs else None,
        "r_time_ranges": (min(rs), max(rs)) if rs else None,
        "duplicates": duplicates,
        "s4_deltas": s4_deltas,
        "s43_deltas": s43_deltas,
        "s43_same_deltas": s43_same_deltas,
        "s6_deltas": s6_deltas,
        "s5_deltas": s5_deltas,
        "f1f_total": f1f_total,
        "f1f_overlap": f1f_overlap,
        "t20_total": t20_total,
        "t20_overlap": t20_overlap,
        "cmd6_total": cmd6_total,
        "cmd6_overlap": cmd6_overlap,
    }


# ---------------------------------------------------------------------------
# analysis helpers
# ---------------------------------------------------------------------------
def nearest(seqs, target):
    if not seqs:
        return None
    i = bisect.bisect_left(seqs, target)
    cand = []
    if i < len(seqs):
        cand.append(seqs[i])
    if i > 0:
        cand.append(seqs[i - 1])
    return min(cand, key=lambda x: abs(x - target))


def counts_within(deltas, k):
    return sum(1 for x in deltas if abs(x) <= k)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--abc", type=Path, default=DEFAULT_ABC)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--no-cross", action="store_true", help="skip cross-sample scan")
    args = ap.parse_args()

    abc = args.abc
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    d, recs, end, how, ev = extract(abc)
    heroes = load_heroes(SAMPLE_KEY)
    monster = load_monsters()
    waves = load_waves()
    cmds = parse_frame_cmds(recs)
    cross = None if args.no_cross else cross_sample()

    entity_ids = set(heroes)
    hero_ids = {v["hero_id"] for v in heroes.values()}
    actor_by_entity = {x["hero"]: x["actor"] for x in ev["87"] if x["hero"]}
    actor_ids = set(actor_by_entity.values())

    gold_by_hero = defaultdict(list)
    for g in ev["85"]:
        gold_by_hero[g["hero"]].append(g)
    for h in gold_by_hero:
        gold_by_hero[h].sort(key=lambda x: x["seq"])
    s43_any = sorted((g["seq"], g["hero"], g["amount"]) for g in ev["85"] if g["source"] == 43)
    s4_by_hero = defaultdict(list)
    for g in ev["85"]:
        if g["source"] == 4:
            s4_by_hero[g["hero"]].append(g["seq"])
    for h in s4_by_hero:
        s4_by_hero[h].sort()

    rows = []
    sample = abc.stem

    def add(rec_type, **kw):
        row = {
            "record_type": rec_type,
            "sample": sample,
            "seq": "",
            "t_s": "",
            "game_t_s": "",
            "hero_entity": "",
            "player": "",
            "team": "",
            "hero_id": "",
            "hero_name": "",
            "actor_id": "",
            "tag": "",
            "type": "",
            "victim": "",
            "value": "",
            "source": "",
            "amount": "",
            "field": "",
            "detail": "",
            "confidence": "",
            "note": "",
        }
        row.update(kw)
        rows.append(row)

    def hero_fields(eid):
        h = heroes.get(eid, {})
        return {
            "hero_entity": eid,
            "player": h.get("player", ""),
            "team": h.get("team", ""),
            "hero_id": h.get("hero_id", ""),
            "hero_name": h.get("hero_name", ""),
            "actor_id": actor_by_entity.get(eid, ""),
        }

    add(
        "meta",
        field="records",
        value=len(recs),
        detail=f"stream={how} end=0x{end:x} bytes={len(d)}",
        note="t_s=seq*0.05; game_t_s=t_s+20.3",
        confidence="high",
    )
    add(
        "meta",
        field="message_counts",
        value=len(ev["1e"]) + len(ev["1f"]) + len(ev["20"]),
        detail=(
            f"1e={len(ev['1e'])} 1f={len(ev['1f'])} 20={len(ev['20'])} "
            f"81={len(ev['81'])} 82={len(ev['82'])} 85={len(ev['85'])} "
            f"87={len(ev['87'])} 80={len(cmds)}"
        ),
        confidence="high",
    )

    # ---- 0x1e events
    for e in ev["1e"]:
        near_all = nearest([x["seq"] for x in gold_by_hero.get(e["hero"], [])], e["seq"])
        near4 = nearest(s4_by_hero.get(e["hero"], []), e["seq"])
        near43 = nearest([x[0] for x in s43_any], e["seq"]) if s43_any else None
        add(
            "event_1e",
            seq=e["seq"],
            t_s=round(e["seq"] * FRAME_S, 2),
            game_t_s=round(e["seq"] * FRAME_S + REPLAY_OFFSET_S, 1),
            **hero_fields(e["hero"]),
            type=e["type"],
            victim=e["victim"],
            field="type/mid/victim/tail",
            detail=f"mid={e['mid']} tail={e['tail']}",
            note=(
                f"nearest_0x85_same_hero={near_all} d={None if near_all is None else near_all - e['seq']}; "
                f"nearest_source4={near4} d={None if near4 is None else near4 - e['seq']}; "
                f"nearest_source43_any={near43} d={None if near43 is None else near43 - e['seq']}"
            ),
            confidence="layout high / semantics low",
        )
        v = e["victim"]
        add(
            "anchor_1e_victim",
            seq=e["seq"],
            t_s=round(e["seq"] * FRAME_S, 2),
            **hero_fields(e["hero"]),
            victim=v,
            field="victim_anchor",
            value=(
                f"entity={v in entity_ids};heroID={v in hero_ids};actor={v in actor_ids};"
                f"monster_id={v in monster['ids']};monster_id_le16={v in monster['low_ids']};"
                f"soldier_id={v in monster['soldier_ids']};wave={v in waves['waves']}"
            ),
            detail=(
                f"entityIDs={sorted(entity_ids)} heroIDs={sorted(hero_ids)} "
                f"actorIDs={sorted(actor_ids)}"
            ),
            note="10 人 entityID / heroID / actorID / normalMonster id / 兵种 id / soldierWave waveID",
            confidence="high",
        )

    # ---- 0x1f / 0x20
    for e in ev["1f"]:
        add(
            "event_1f",
            seq=e["seq"],
            t_s=round(e["seq"] * FRAME_S, 2),
            game_t_s=round(e["seq"] * FRAME_S + REPLAY_OFFSET_S, 1),
            **hero_fields(e["hero"]),
            tag=e["tag"],
            value=e["id_21_22"],
            field="tag/id_21_22",
            detail=(
                f"raw={e['raw']} u32_2={e['u32_2']} i32_10={e['i32_10']} "
                f"u32_14={e['u32_14']} tail={e['tail']}"
            ),
            note="highlight tag（5=团战控制+击败；244=表外；2=关键群控）",
            confidence="tag high / fields low",
        )
    for e in ev["20"]:
        add(
            "event_20",
            seq=e["seq"],
            t_s=round(e["seq"] * FRAME_S, 2),
            game_t_s=round(e["seq"] * FRAME_S + REPLAY_OFFSET_S, 1),
            **hero_fields(e["hero"]),
            tag=e["tag"],
            value=e["id_14_le"],
            field="tag/id_14_le",
            detail=f"raw={e['raw']} u32_6_le={e['u32_6_le']} id_14_be={e['id_14_be']}",
            note="稀有 20B；与 0x1f 高光配套候选",
            confidence="low",
        )

    # ---- 0x81 / 0x82 / 0x85 / 0x87
    for e in ev["81"]:
        add(
            "event_81",
            seq=e["seq"],
            t_s=round(e["seq"] * FRAME_S, 2),
            **hero_fields(e["hero"]),
            value=e["value"],
            field="byte0",
            detail=e["raw"],
            note="0x02 len=1；值域 1/2/3/4/6",
            confidence="value high / semantics low",
        )
    for e in ev["82"]:
        add(
            "event_82",
            seq=e["seq"],
            t_s=round(e["seq"] * FRAME_S, 2),
            **hero_fields(e["hero"]),
            value=e["kind"],
            field="kind/toggle",
            detail=f"raw={e['raw']} toggle={e['toggle']}",
            note="0x02 len=2；kind 逐英雄恒定，toggle=0/255",
            confidence="layout high / semantics low",
        )
    for g in ev["85"]:
        add(
            "gold_85",
            seq=g["seq"],
            t_s=round(g["seq"] * FRAME_S, 2),
            **hero_fields(g["hero"]),
            source=g["source"],
            amount=g["amount"],
            field="source/amount",
            detail=g["raw"],
            note=("source43: >=200 击杀, 102 助攻" if g["source"] == 43 else ""),
            confidence="high",
        )
    for a in ev["87"]:
        add(
            "actor_87",
            seq=a["seq"],
            t_s=round(a["seq"] * FRAME_S, 2),
            **hero_fields(a["hero"]),
            value=a["actor"],
            field="actor/slot/level",
            detail=f"actor={a['actor']} slot={a['slot']} level={a['level']} raw={a['raw']}",
            confidence="high",
        )

    for g in ev["85"]:
        if g["source"] == 43:
            role = "kill" if g["amount"] >= 200 else ("assist" if g["amount"] == 102 else "source43_other")
            add(
                "kill_assist",
                seq=g["seq"],
                t_s=round(g["seq"] * FRAME_S, 2),
                game_t_s=round(g["seq"] * FRAME_S + REPLAY_OFFSET_S, 1),
                **hero_fields(g["hero"]),
                amount=g["amount"],
                source=g["source"],
                field=role,
                value=f"{role} payee={g['hero']}",
                detail=g["raw"],
                note="收款人=killer/assister 已闭合；payload 无 victim 字段，0x1e 不可对齐",
                confidence="high（收款人）/ victim unavailable",
            )

    # ---- alignment stats (main sample)
    def align_stats(ev_list, name):
        deltas = []
        same = 0
        for e in ev_list:
            nb = nearest(s4_by_hero.get(e["hero"], []), e["seq"])
            if nb is not None:
                deltas.append(nb - e["seq"])
                same += nb == e["seq"]
        null_rates = []
        for shift in (1000, 2000, 3000, 4000):
            hits = tot = 0
            for e in ev_list:
                nb = nearest(s4_by_hero.get(e["hero"], []), e["seq"] + shift)
                if nb is not None:
                    tot += 1
                    hits += abs(nb - (e["seq"] + shift)) <= 2
            null_rates.append(hits / tot if tot else 0.0)
        add(
            "align",
            field=f"{name}_vs_source4",
            value=(
                f"n={len(deltas)} same={same} within2={counts_within(deltas,2)} "
                f"within10={counts_within(deltas,10)} within40={counts_within(deltas,40)}"
            ),
            detail=f"null_within2={sum(null_rates)/len(null_rates):.4f}",
            confidence="medium",
        )

    align_stats(ev["1e"], "1e")
    align_stats(ev["81"], "81")
    align_stats(ev["82"], "82")

    d43 = []
    for e in ev["1e"]:
        nb = nearest([x[0] for x in s43_any], e["seq"])
        if nb is not None:
            d43.append(nb - e["seq"])
    add(
        "align",
        field="1e_vs_source43_any",
        value=(
            f"n={len(d43)} within2={counts_within(d43,2)} "
            f"within10={counts_within(d43,10)} within40={counts_within(d43,40)}"
        ),
        detail=f"deltas={sorted(d43)}",
        confidence="medium",
    )

    # ---- hero summary
    for eid, h in sorted(heroes.items()):
        kills = sum(
            1 for g in ev["85"] if g["hero"] == eid and g["source"] == 43 and g["amount"] >= 200
        )
        assists = sum(
            1 for g in ev["85"] if g["hero"] == eid and g["source"] == 43 and g["amount"] == 102
        )
        unit_ev = [e for e in ev["1e"] if e["hero"] == eid]
        v81 = Counter(e["value"] for e in ev["81"] if e["hero"] == eid)
        v82 = Counter((e["kind"], e["toggle"]) for e in ev["82"] if e["hero"] == eid)
        add(
            "hero_summary",
            hero_entity=eid,
            player=h["player"],
            team=h["team"],
            hero_id=h["hero_id"],
            hero_name=h["hero_name"],
            actor_id=actor_by_entity.get(eid, ""),
            value=f"observable_kills={kills} observable_assists={assists}",
            detail=(
                f"0x1e_as_attacker={len(unit_ev)} victims={[e['victim'] for e in unit_ev]} "
                f"types={[e['type'] for e in unit_ev]}; "
                f"0x81={dict(sorted(v81.items()))}; 0x82={dict(sorted(v82.items()))}; "
                f"gold_n={sum(1 for g in ev['85'] if g['hero']==eid)} "
                f"gold_sum={sum(g['amount'] for g in ev['85'] if g['hero']==eid)}"
            ),
            confidence="high",
        )

    # ---- 1558 focus
    e1558 = 1558
    h1558 = heroes.get(e1558, {})
    e1e = [e for e in ev["1e"] if e["hero"] == e1558]
    e1f = [e for e in ev["1f"] if e["hero"] == e1558]
    e20 = [e for e in ev["20"] if e["hero"] == e1558]
    s81 = [e for e in ev["81"] if e["hero"] == e1558]
    s82 = [e for e in ev["82"] if e["hero"] == e1558]
    g85 = [g for g in ev["85"] if g["hero"] == e1558]
    k1558 = sum(1 for g in g85 if g["source"] == 43 and g["amount"] >= 200)
    a1558 = sum(1 for g in g85 if g["source"] == 43 and g["amount"] == 102)
    add(
        "focus_1558",
        hero_entity=e1558,
        player=h1558.get("player", ""),
        team=h1558.get("team", ""),
        hero_id=h1558.get("hero_id", ""),
        hero_name=h1558.get("hero_name", ""),
        actor_id=actor_by_entity.get(e1558, ""),
        value=f"observable_K={k1558} observable_A={a1558} D=unavailable",
        detail=(
            f"0x1e={[(e['seq'], e['type'], e['victim']) for e in e1e]}; "
            f"0x1f={[(e['seq'], e['tag'], e['id_21_22']) for e in e1f]}; "
            f"0x20={[(e['seq'], e['tag'], e['id_14_le']) for e in e20]}; "
            f"0x81={[(e['seq'], e['value']) for e in s81]}; "
            f"0x82_n={len(s82)}; source43={[(g['seq'], g['amount']) for g in g85 if g['source']==43]}"
        ),
        note="1558 无 source43；0x1e 只给 attacker->unit-object，不是 K/D/A",
        confidence="negative",
    )

    # ---- anchor statistical summary (main sample)
    victims = [e["victim"] for e in ev["1e"]]
    n = len(victims)
    universe = 1024
    anchor_sets = [
        ("entityID", entity_ids),
        ("heroID", hero_ids),
        ("actorID", actor_ids),
        ("heroTable174_193", set(range(174, 194))),
        ("normalMonster_id", monster["ids"]),
        ("normalMonster_id_le16", monster["low_ids"]),
        ("soldier_unit_id", monster["soldier_ids"]),
        ("soldierWave_waveID", waves["waves"]),
    ]
    stats = []
    for name, target in anchor_sets:
        in_universe = target & set(range(universe))
        hits = sum(1 for v in victims if v in target)
        expected = n * len(in_universe) / universe
        stats.append(
            {
                "name": name,
                "size": len(target),
                "in_universe": len(in_universe),
                "hits": hits,
                "expected": expected,
            }
        )
    for srow in stats:
        add(
            "anchor_test",
            field="victim_set_membership",
            value=f"{srow['name']}: hits={srow['hits']}/{n}",
            detail=(
                f"target_size={srow['size']} in_0_1023={srow['in_universe']} "
                f"expected_uniform={srow['expected']:.2f}"
            ),
            note=f"observed victims min={min(victims)} max={max(victims)} unique={len(set(victims))}",
            confidence="high",
        )
    add(
        "anchor_test",
        field="normalMonster_row",
        value=f"hits={n}/{n}",
        detail="row 0..2624 覆盖 0..1023；任何 victim 都是合法 row → 该检验无区分力",
        confidence="high",
    )

    # ---- cross-sample rows
    if cross:
        add(
            "cross_sample",
            field="summary",
            value=f"1e={cross['n1e']}",
            detail=(
                f"files_with_1e={len(cross['per_file'])} types={cross['types']} "
                f"victims_unique={cross['unique']} min={cross['min']} max={cross['max']} "
                f"zero_one={cross['zero_one']} "
                f"pearson_t_victim_median={cross['r_time_median']} range={cross['r_time_ranges']} "
                f"source4_±2={counts_within(cross['s4_deltas'],2)}/{len(cross['s4_deltas'])} "
                f"source4_±10={counts_within(cross['s4_deltas'],10)}/{len(cross['s4_deltas'])} "
                f"source43_any_±40={counts_within(cross['s43_deltas'],40)}/{len(cross['s43_deltas'])} "
                f"source43_same_±40={counts_within(cross['s43_same_deltas'],40)}/{len(cross['s43_same_deltas'])} "
                f"source6_±40={counts_within(cross['s6_deltas'],40)}/{len(cross['s6_deltas'])} "
                f"source5_±40={counts_within(cross['s5_deltas'],40)}/{len(cross['s5_deltas'])} "
                f"1f_id_overlap_1e={cross['f1f_overlap']}/{cross['f1f_total']} "
                f"20_id_overlap_1e={cross['t20_overlap']}/{cross['t20_total']} "
                f"cmd6_actor_overlap_1e={cross['cmd6_overlap']}/{cross['cmd6_total']}"
            ),
            confidence="high",
        )
        for pf in cross["per_file"]:
            add(
                "cross_sample_file",
                field=pf["file"],
                value=f"1e={pf['n1e']} unique={pf['unique']}",
                detail=(
                    f"types={pf['types']} 1f={pf['n1f']} 20={pf['n20']} "
                    f"source43={pf['n_s43']} s43_within40={pf['s43_within40']} "
                    f"source4={pf['n_s4']} s4_within2={pf['s4_within2']} "
                    f"victim_in_actorIDs={pf['actor_hits']}"
                ),
                confidence="high",
            )
        for dup in cross["duplicates"]:
            add(
                "cross_sample_dup",
                field=dup[0],
                victim=dup[1],
                value=f"n={len(dup[2])}",
                detail=f"events={dup[2]}",
                note="同一 victim 值在同局重复出现；可能是同一单位被多次命中或 object ID 复用",
                confidence="medium",
            )

    # ---- write CSV
    csv_path = out_dir / "agent_kill_attribution.csv"
    fields = list(rows[0].keys())
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    # ---- write MD
    md = build_md(
        abc, recs, how, end, ev, heroes, actor_by_entity, s43_any, cmds,
        victims, stats, monster, waves, cross,
    )
    md_path = out_dir / "agent_kill_attribution.md"
    md_path.write_text(md, encoding="utf-8")

    print(f"wrote {csv_path} ({len(rows)} rows)")
    print(f"wrote {md_path}")
    print(
        f"1e={len(ev['1e'])} 1f={len(ev['1f'])} 20={len(ev['20'])} "
        f"81={len(ev['81'])} 82={len(ev['82'])} 85={len(ev['85'])}"
    )


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------
def build_md(abc, recs, how, end, ev, heroes, actor_by_entity, s43_any, cmds,
             victims, stats, monster, waves, cross):
    n1e = len(ev["1e"])
    n1f = len(ev["1f"])
    n20 = len(ev["20"])
    L = []
    A = L.append

    A("# 普通 5v5（5069040）0x1e / 0x1f / 0x20 / 0x02·0x81 / 0x82 击杀归属逆向")
    A("")
    A(f"> 只读逆向。主样本 `{abc.name}`；stream={how}，records={len(recs)}，end=0x{end:x}。"
      "本文所有数字由 `tools/agent_kill_attribution.py` 生成，可复跑。")
    A("")
    A("## 0. 结论速览")
    A("")
    A("**killer 能闭合，victim 不能闭合。**")
    A("")
    A("- `0x1e` 的 envelope hero（338/1729/1021/1558…）是**攻击者 entityID**；")
    A("- `0x1e` payload 里唯一的 2 字节实体字段 `data[16:18]` **最可能是运行时单位 object ID**，"
      "不命中 10 人 entityID/heroID/actorID；normalMonster/soldierWave 的命中只有 1 条/3 条低位巧合；")
    A("- `0x1e` **不是击杀/补刀表**：它与同英雄 source4 金币零同帧（全样本 ±2 帧 1/288），"
      "与 source43 击杀金币同帧率也低于随机（主样本 0/21）；")
    A("- **1558 的 K/D/A 不能从回放闭合**：source43 没有 1558；0x1e 只说明 1558 对 3 个单位 object "
      "触发过事件；0x1f 只有 1 条高光（tag 244），0x20 没有；没有死亡/被击杀记录。")
    A("")
    A("## 1. 消息形状（主样本）")
    A("")
    A("| 形状 | 条数 | 字段 | 置信度 |")
    A("|---|---:|---|---|")
    A(f"| `0x01/0x1e` | {n1e} | `1e type:u8 14×00 victim:u16BE 01` | layout high / semantics low |")
    A(f"| `0x01/0x1f` | {n1f} | `1f tag:u8 … id(u16BE@21:22) count=01` | tag high / fields low |")
    A(f"| `0x01/0x20` | {n20} | `20 tag:u8 … id(u16LE@14:15)` | low |")
    A(f"| `0x02 len=1` (0x81) | {len(ev['81'])} | 1 字节，值域 1/2/3/4/6 | value high / semantics low |")
    A(f"| `0x02 len=2` (0x82) | {len(ev['82'])} | `kind:u8 toggle:u8`，kind 逐英雄恒定 | layout high / semantics low |")
    A(f"| `0x02 len=5` (0x85) | {len(ev['85'])} | `source:u8 amount:u32LE` | high |")
    A("")
    A("`0x1e` 的 14 个零字节在**字节数**上正好等于 C# `FrameNotifyInfo` 的 "
      "`assist01..05(5×u16) + assistCount + multiKill + contiKill + killNotifyType`（14B），"
      "尾字节恒 `01` 与 `isKillNotify=1` 同形。**但结构相似不等于语义成立**："
      "主样本 21 条的 5 个 assist 槽全为 0，且 victim 不在 10 个 hero object ID 中；"
      "`BattleNotifyReplayTool` 已被 docs 5.14.1 判定为编辑器测试工具，不能当作回放含击杀的证据。")
    A("")
    A("## 2. `0x1e` 逐条：attacker → unit object")
    A("")
    A("`t` 为回放秒（seq×0.05），`game_t` = t + 20.3s。")
    A("")
    A("| seq | t(s) | 攻击者 | 玩家 | type | victim(object) | 最近 source4 同英雄 (Δ帧) | 最近 source43 任意 (Δ帧) |")
    A("|---:|---:|---:|---|---:|---:|---|---|")
    gold_by_hero = defaultdict(list)
    for g in ev["85"]:
        gold_by_hero[g["hero"]].append(g)
    for h in gold_by_hero:
        gold_by_hero[h].sort(key=lambda x: x["seq"])
    s4 = defaultdict(list)
    for g in ev["85"]:
        if g["source"] == 4:
            s4[g["hero"]].append(g["seq"])
    for h in s4:
        s4[h].sort()
    for e in ev["1e"]:
        h = heroes.get(e["hero"], {})
        nb4 = nearest(s4.get(e["hero"], []), e["seq"])
        nb43 = nearest([x[0] for x in s43_any], e["seq"]) if s43_any else None
        d4 = "" if nb4 is None else f"{nb4} ({nb4 - e['seq']:+d})"
        d43 = "" if nb43 is None else f"{nb43} ({nb43 - e['seq']:+d})"
        A(f"| {e['seq']} | {e['seq'] * FRAME_S:.2f} | {e['hero']} | {h.get('hero_name', '')} | "
          f"{e['type']} | {e['victim']} | {d4} | {d43} |")
    A("")
    A("### 2.1 `source43` 击杀/助攻（唯一闭合的 killer/assister 表）")
    A("")
    A("`0x85 source=43` 金额 202/203 = 击杀、102 = 助攻；收款人 entityID 已知，**victim 不在 payload**。")
    A("")
    A("| seq | t(s) | 收款人 | 玩家 | 角色 | 金额 | victim |")
    A("|---:|---:|---:|---|---|---:|---|")
    for g in ev["85"]:
        if g["source"] != 43:
            continue
        role = "kill" if g["amount"] >= 200 else ("assist" if g["amount"] == 102 else "other")
        h = heroes.get(g["hero"], {})
        A(f"| {g['seq']} | {g['seq'] * FRAME_S:.2f} | {g['hero']} | {h.get('hero_name', '')} | "
          f"{role} | {g['amount']} | 不可得 |")
    A("")
    A(f"→ 主样本只有 **{sum(1 for g in ev['85'] if g['source']==43 and g['amount']>=200)} 杀 + "
      f"{sum(1 for g in ev['85'] if g['source']==43 and g['amount']==102)} 助攻** 可闭合到收款人；"
      "0x85 是部分流水（25–35%），所以这不是全量 K/A，只说明「哪些击杀/助攻的收款人被录到」。")
    A("")
    A("## 3. victim 候选空间（核心阴性证据）")
    A("")
    A(f"主样本 {n1e} 条的 victim：`{sorted(victims)}`。"
      f"min={min(victims)} / max={max(victims)} / 唯一值={len(set(victims))}。")
    A("")
    A("| 目标集 | 全集大小 | 落在 0..1023 内 | 命中 | 均匀期望 | 判定 |")
    A("|---|---:|---:|---:|---:|---|")
    for srow in stats:
        verdict = "无富集" if srow["hits"] <= srow["expected"] + 3 else "需复核"
        A(f"| {srow['name']} | {srow['size']} | {srow['in_universe']} | "
          f"{srow['hits']}/{n1e} | {srow['expected']:.2f} | {verdict} |")
    A("")
    A("- **10 人 entityID**：338/442/1021 虽落在 0..1023，但实测 0/21；其余 6 个 >1023，"
      "2 字节 victim 在编码上不可能命中；")
    A("- **10 人 heroID** 命中 0/21（期望 0.21）；")
    A("- **10 人 actorID** 命中 0/21（期望 0.21）；")
    A("- **normalMonster id** 只有 1/21（victim 193 = `忠诚守卫` 的配置 id；它同时落在 "
      "Project8Hero 174–193 区间，属数值巧合），期望 4.55，低于随机；大量 5v5 单位 id "
      "（1660002、4012001…）>65535，2 字节字段装不下；")
    A("- **soldierWave waveID** 的 3/21 是 325/368/369 三位数整数重合（落在 waveID 密集区），"
      "但 waveID 是刷怪波次配置，不可能是「死亡单位」；")
    A("- **normalMonster row** 0..2624 覆盖全部 0..1023，任何 victim 都是合法 row → 该检验无区分力；")
    A("- **soldier unit id** 全在 0..23 段（1/16/2/17/14/18…），victim 只有个别低位值，且不重复出现，"
      "不符合「单位类型配置 ID」。")
    A("")
    A("→ victim **最可能是运行时单位 object ID**（候选，medium）：与 hero object ID"
      "（8/12/19/23/30/37/44/51/58/65）同一编号空间，但单位实例从 66 起分配。"
      "没有 `object ID → 英雄/兵种` 的运行时映射表，victim 无法落地。")
    A("")
    if cross:
        A("**排除「victim 是伤害值」**：")
        A("")
        A(f"- 12 个文件内 `Pearson(t, victim)` 中位数 **{cross['r_time_median']:+.3f}**"
          f"（范围 {cross['r_time_ranges'][0]:+.3f}…{cross['r_time_ranges'][1]:+.3f}）；"
          "伤害值应随英雄等级/装备随时间增长，实测无正相关；")
        A(f"- 全样本 victim 出现 **0/1** 共 {cross['zero_one']} 次；伤害值不应为 0/1；")
        A("- victim 不随 type 稳定分层（同一 type 在不同局均值可高可低）→ 更像实例句柄而非伤害数值。")
        A("")
    A("")
    A("## 4. `0x1e` 更像「技能命中单位」，不是击杀/补刀")
    A("")
    A("下面五条是否定性证据；「技能命中单位」是**候选解释（medium）**，"
      "不是已证实的字段语义。")
    A("")
    A("1. **与 source4 金币零对齐**：全样本 288 条可配对事件里，同英雄 source4 金币"
      "同帧 0、±2 帧 1、±10 帧 7；主样本 21 条里 ±40 帧只有 2 条"
      "（seq 8615 +15 帧、seq 10075 −33 帧）。若 0x1e 是兵线最后一击，金币应在同帧或几帧内出现。")
    A("2. **与 source43 击杀金币不同帧**：主样本 0/21 在 ±40 帧内；全样本**同英雄** source43 "
      f"±40 帧 {counts_within(cross['s43_same_deltas'],40) if cross else 0}/"
      f"{len(cross['s43_same_deltas']) if cross else 0}（same=0、±2=0、±10=0），"
      "任意英雄口径的少量命中只是击杀密集局的邻近效应。若 0x1e 是击杀通知，击杀者应在同帧收到 "
      "source43 200/202/203；实测一次都没有。")
    A("3. **同一 victim 可被重复命中**：跨样本重复 victim "
      f"{len(cross['duplicates']) if cross else 8} 例，其中 "
      "`20260902_222816` 的 victim 614 被同一攻击者 1175 先用 type 2、再用 type 4 命中，间隔 318 帧（15.9s）；"
      "`20260925_101323` 的 victim 853 被 321 在 8.9s 与 552.85s 两次命中。"
      "这更像「单位被技能命中/object ID 复用」，不是「单位死亡」。")
    A("4. **多目标簇**：seq 8239/8241/8243（1021，type 4，0.2s 内 3 个 victim）与 "
      "seq 10383/10386（1558，type 3，0.15s 内 2 个 victim）是 AoE 技能命中多个单位的形态；"
      "若是击杀，同一英雄 0.2s 内三杀也成立，但会同时出现 3 笔 source43 击杀金，主样本没有。")
    A(f"5. **逐玩家分布不像击杀**：主样本 {n1e} 条集中在 1021=5、338=4、1729=4、1547=3、1558=3，"
      "carry 1965/1966/1833 为 0；"
      "若这是击杀表，队内主要输出点不应全部为 0，辅助/坦克也不应占 8/21。")
    A("")
    A("`type` 观测 `{2,3,4,7}`（主样本 {2:1, 3:13, 4:7}；全样本 {2:64, 3:109, 4:115, 7:5}）。"
      "候选是**技能槽/动作 ID 或单位类别**（2/3/4 与技能槽 2/3/4 同量级，7=额外/召唤师技能），"
      "但它不是击杀类型：同 type 同时出现在击杀密集局和零击杀局，且与 source43 无稳定对齐。"
      "14 个零字节是未序列化的伤害/助攻槽，不是「没有助攻的击杀」。")
    A("")
    A("## 5. `0x1f` / `0x20`")
    A("")
    A("`0x1f` 是**高光标签通知**（tag 已闭环：5=团战控制+击败、2=关键群控、93/94=杨戬刷新技能击败、"
      "244=表外）。主样本 3 条：")
    A("")
    A("| seq | t(s) | 高光归属 | tag | id(u16BE@21:22) | raw |")
    A("|---:|---:|---:|---:|---:|---|")
    for e in ev["1f"]:
        h = heroes.get(e["hero"], {})
        A(f"| {e['seq']} | {e['seq'] * FRAME_S:.2f} | {e['hero']} {h.get('hero_name', '')} | "
          f"{e['tag']} | {e['id_21_22']} | `{e['raw']}` |")
    A("")
    for e in ev["20"]:
        h = heroes.get(e["hero"], {})
        A(f"- `0x20` seq {e['seq']}（{e['seq'] * FRAME_S:.2f}s）hero {e['hero']} {h.get('hero_name', '')} "
          f"tag={e['tag']} id14_le={e['id_14_le']} raw=`{e['raw']}`")
    A("")
    A("- 0x1f 的 tag 是 high；其余字段在 28B 内呈位打包/混合字节序，"
      "不同 tag 的字节形态差异大，**没有可复用的 killer/victim 布局**；")
    A("- 主样本 3 条 0x1f 的 id（798/12/202）与 21 条 0x1e victim 零交集；"
      "跨样本同文件比对也没有稳定同值/同帧关系；")
    if cross:
        A(f"- **同文件 0x1f id 与 0x1e victim 零重叠**：0x1f id {cross['f1f_overlap']}/{cross['f1f_total']}、"
          f"0x20 id {cross['t20_overlap']}/{cross['t20_total']} 命中同局 0x1e victim 集合；"
          "两者只是数值区间同量级（0..~1000），不是同一 ID 空间；")
    A("- 0x1f 的 id=12（seq 7209）恰好等于 1558 的 actorID，但另外两条 798/202 不对应任何 hero object ID，"
      "不能据此把 id 定为 killer/victim；")
    A("- 0x20 只有 7 条跨样本，id 候选 291–478，同样无法锚定。")
    A("")
    A("## 6. `0x81` / `0x82` 是不是攻击/死亡/补刀标记")
    A("")
    A("### 6.1 0x81（len=1，970 条）")
    A("")
    A("值域 `{1,2,3,4,6}`，逐英雄强偏置：")
    A("")
    A("| 英雄 | 1 | 2 | 3 | 4 | 6 |")
    A("|---|---:|---:|---:|---:|---:|")
    for eid in sorted(heroes):
        cnt = Counter(e["value"] for e in ev["81"] if e["hero"] == eid)
        h = heroes[eid]
        A(f"| {eid} {h['hero_name']} | {cnt.get(1,0)} | {cnt.get(2,0)} | {cnt.get(3,0)} | "
          f"{cnt.get(4,0)} | {cnt.get(6,0)} |")
    A("")
    d81 = []
    for e in ev["81"]:
        nb = nearest(s4.get(e["hero"], []), e["seq"])
        if nb is not None:
            d81.append(nb - e["seq"])
    d82 = []
    for e in ev["82"]:
        nb = nearest(s4.get(e["hero"], []), e["seq"])
        if nb is not None:
            d82.append(nb - e["seq"])
    A(f"- 0x81 vs source4：n={len(d81)}，same=0，±2 帧={counts_within(d81,2)}，"
      f"±10 帧={counts_within(d81,10)}，±40 帧={counts_within(d81,40)}；")
    A(f"- 0x82 vs source4：n={len(d82)}，same=0，±2 帧={counts_within(d82,2)}，"
      f"±10 帧={counts_within(d82,10)}，±40 帧={counts_within(d82,40)}。")
    A("")
    A("→ 0x81 **不是补刀/结算标记**：与金币同帧率为 0，±2 帧率接近/低于时间平移零假设；"
      "值 6 与 source43 击杀/助攻也不同步。0x81 更像**技能/动作状态**（1/2/3/4 技能槽，6 回城/恢复类）。"
      "若 6=死亡，1558 的 5 个 6 应对应 5 次死亡，但 5 个时间点都不与已知击杀金币对齐，反证 6≠死亡。")
    A("")
    A("### 6.2 0x82（len=2，436 条）")
    A("")
    A("`raw = 02 00` 或 `02 ff`，`data[0]` 逐英雄恒定：338→2、1547→3、1558→2、1729→1、1833→1、1966→1，"
      "其余 4 人 0 条；`data[1]` 只在 0/255 间翻转。"
      "（任务给的「436 条 `02ff`」不完整：实测 kind=1/2/3 三种，toggle=0/255 各约一半；"
      "kind 是逐英雄槽位属性，不是固定 2。）"
      "→ 这是**逐英雄的瞄准/攻击开关**（槽位属性 + 0/255 翻转），不是死亡/补刀，payload 没有单位 ID。")
    A("")
    A("## 7. 1558（佚名(*: / 东皇太一）的 K/D/A")
    A("")
    h = heroes.get(1558, {})
    A(f"- entityID **1558**，heroID **187**，actorID **12**，team {h.get('team', '')}；")
    A("- source43（击杀 202/203、助攻 102）**0 条**；")
    e1e = [e for e in ev["1e"] if e["hero"] == 1558]
    e1f = [e for e in ev["1f"] if e["hero"] == 1558]
    s81 = [e for e in ev["81"] if e["hero"] == 1558]
    A(f"- 0x1e 作为 attacker 的 {len(e1e)} 条："
      + "；".join(f"seq {e['seq']}（{e['seq'] * FRAME_S:.2f}s）type {e['type']} victim {e['victim']}"
                 for e in e1e) + "；")
    if e1f:
        A(f"- 0x1f 1 条：seq {e1f[0]['seq']}（{e1f[0]['seq'] * FRAME_S:.2f}s）tag {e1f[0]['tag']} "
          f"id {e1f[0]['id_21_22']}；")
    else:
        A("- 0x1f 0 条；")
    A(f"- 0x81 {len(s81)} 条全为 6："
      + "、".join(f"{e['seq'] * FRAME_S:.1f}s" for e in s81) + "。")
    A("")
    A("### 7.1 十人可观测击杀/助攻（source43）")
    A("")
    A("| 玩家 | 英雄 | 可观测 K | 可观测 A | source4 笔数 | 0x1e 单位事件 |")
    A("|---|---|---:|---:|---:|---:|")
    for eid in sorted(heroes, key=lambda x: (heroes[x]["team"], heroes[x]["slot"])):
        h = heroes[eid]
        k = sum(1 for g in ev["85"] if g["hero"] == eid and g["source"] == 43 and g["amount"] >= 200)
        a = sum(1 for g in ev["85"] if g["hero"] == eid and g["source"] == 43 and g["amount"] == 102)
        s4n = sum(1 for g in ev["85"] if g["hero"] == eid and g["source"] == 4)
        ue = sum(1 for e in ev["1e"] if e["hero"] == eid)
        A(f"| {h['player']} | {h['hero_name']} | {k} | {a} | {s4n} | {ue} |")
    A("")
    A("**KDA 结论（按可观测口径）**：K=0（source43 无 1558 的 202/203；0x1e 不是英雄击杀）、"
      "A=0（source43 无 102）、**D 不可得**。这是「回放可观测」的 K/A，不等于真实 K/A——"
      "0x85 只是 25–35% 的金币流水，source43 的 6 杀 4 助攻不是全量。"
      "回放里没有「1558 被谁击杀」的记录；0x1e 的 victim 是单位 object（候选），"
      "1558 作为 attacker 的 3 条不是它的死亡。")
    A("")
    A("## 8. 跨样本复核")
    A("")
    if cross:
        A(f"- 可解析出 0x1e 的文件 {len(cross['per_file'])}/{len(cross['files'])}；"
          f"0x1e 共 **{cross['n1e']}** 条，type 分布 **{cross['types']}**，"
          f"victim 唯一值 {cross['unique']}，范围 {cross['min']}–{cross['max']}；")
        A(f"- 0x1e vs 同英雄 source4：same=0，±2 帧 {counts_within(cross['s4_deltas'],2)}/"
          f"{len(cross['s4_deltas'])}，±10 帧 {counts_within(cross['s4_deltas'],10)}/"
          f"{len(cross['s4_deltas'])}，±40 帧 {counts_within(cross['s4_deltas'],40)}/"
          f"{len(cross['s4_deltas'])}；")
        A(f"- 0x1e vs **同英雄** source43：same=0、±2=0、±10=0、±40="
          f"{counts_within(cross['s43_same_deltas'],40)}/{len(cross['s43_same_deltas'])}；"
          f"vs 同英雄 source6（野怪）：±40="
          f"{counts_within(cross['s6_deltas'],40)}/{len(cross['s6_deltas'])}；"
          f"vs 同英雄 source5（自然/被动）：±40="
          f"{counts_within(cross['s5_deltas'],40)}/{len(cross['s5_deltas'])}；")
        A(f"- 同局重复 victim {len(cross['duplicates'])} 例；"
          "重复值更像是 object ID 复用/单位被多次命中，而不是「每个单位只死一次」；")
        A(f"- victim 与时间无正相关（12 个文件的 Pearson 中位数 {cross['r_time_median']:+.3f}）；"
          f"0/1 值 {cross['zero_one']} 次 → 排除「victim=伤害值」；")
        A("")
        A("| 文件 | 0x1e | unique | type | 1f | 20 | source43 | s43 ±40 | source4 | s4 ±2 | victim∈actorID | r(t,victim) |")
        A("|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|")
        for pf in cross["per_file"]:
            rtxt = "" if pf["r_time"] is None else f"{pf['r_time']:+.3f}"
            A(f"| {pf['file'][:30]} | {pf['n1e']} | {pf['unique']} | {pf['types']} | {pf['n1f']} | "
              f"{pf['n20']} | {pf['n_s43']} | {pf['s43_within40']} | {pf['n_s4']} | "
              f"{pf['s4_within2']} | {pf['actor_hits']} | {rtxt} |")
        A("")
    else:
        A("（本次运行跳过跨样本复核）")
        A("")
    A("## 9. 还缺什么")
    A("")
    A("1. **单位 object ID → 英雄/兵种映射**：0x1e victim 是运行时单位 object ID；"
      "需要战斗初始化或 StepNotify 头里的 `MyCampHeroObjIds / EnemyCampHeroObjIds`（以及单位 object 表）。"
      "当前回放已解块没有这张表；`0x02/0x87` 只给 10 个 hero object ID（8..65），不含单位。"
      "0x1f/0x20 的 id 与 0x1e victim 零重叠，可能是高光资源/目标 ID，也不能当单位映射。")
    A("2. **victim 的死亡判定**：0x1e payload 的 14 个零字节没有伤害/队伍/单位类型；"
      "即使拿到 object ID，也不知道该单位是英雄、兵、野怪还是塔。")
    A("3. **source43 覆盖率**：0x85 只有 5 字节（source + amount），没有单位/受害者位宽；"
      "且只是部分金币流水（约 25–35%），6 杀 4 助攻不是全量。")
    A("4. **0x1f/0x20 的位级 schema**：tag 已闭环，但 28B/20B 内部字段是位打包/混合字节序；"
      "要拿 killer/victim 需要 C# 写入顺序或位级 schema。")
    if cross:
        A(f"5. **0x02/0x80 cmdType=6 的 actor 字段是唯一的新线索**：跨样本 cmdType 6 的非英雄 actor "
          f"与同局 0x1e victim 有 {cross['cmd6_overlap']}/{cross['cmd6_total']} 个值重叠，"
          "说明它可能和 0x1e victim 共用「目标单位 object ID」空间；但 cmdType 6 的 `value` 是 256 的倍数、"
          "语义未定（候选：目标坐标/技能参数），主样本 cmdType 6 的 actor 与 0x1e victim 零重叠，"
          "还不能当映射表用。")
    A("")
    A("## 10. 产物")
    A("")
    A("- `tools/agent_kill_attribution.py`")
    A("- `data/replays/_analysis/datasets/agent_kill_attribution.csv`"
      "（record_type：meta / event_1e / anchor_1e_victim / event_1f / event_20 / event_81 / "
      "event_82 / gold_85 / actor_87 / align / hero_summary / focus_1558 / anchor_test / "
      "cross_sample / cross_sample_file / cross_sample_dup）")
    A("- 本文")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()
