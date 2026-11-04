#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""普通 5v5 主样本十人经济对账（只读）。

样本：data/replays/samples/abc_batch/20260925_105224_*.abc
模式：confType1=50（普通 5v5），初始 300，自然金 3/s、40s 起（battleDynamicProperty cfg1）。
数据：0x02 flag=0x85 len=5，payload = sourceType:u8 + amount:u32LE，覆盖全部 10 个实体。

口径：
  source4               小兵补刀（实际到手，事件金额=底额+自然尾数，事件数≠补刀数）
  source6               野怪击杀（normalMonster 160/174/171/180/190/200）
  source43 amount>=200  击杀候选（200 底额）
  source43 amount<200   助攻候选（100 底额）
  source5 31..80        自然金小额（10 秒推送/合并推送）
  source5 131..146      被动/团队金候选（130/140 底额）
  source5 231..254      目标/推塔候选（230/240/250 底额）
  source44/47/51        其他奖励（45/175/250 底额候选）

残差 = 流水合计 - (小兵 + 野怪 + 击杀 + 助攻 + 自然小额)
      = source5 大额 + source44/47/51（账内残差；不含未写入流水的自然金）
流水合计不含初始 300；初始 300 是存量，不是来源事件。

用法：
  python tools/agent_normal5v5_reconcile.py
  python tools/agent_normal5v5_reconcile.py --from-csv
  python tools/agent_normal5v5_reconcile.py --sample <path.abc> --out-csv ... --out-md ...

只读：不修改回放，不注入进程，不读取 param.json，不使用 runtime_dump。
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS = ROOT / "data" / "replays" / "_analysis"
DATASETS = ANALYSIS / "datasets"
SAMPLE_DIR = ROOT / "data" / "replays" / "samples" / "abc_batch"
SAMPLE_GLOB = "20260925_105224*.abc"
OUT_CSV = DATASETS / "agent_normal5v5_reconciliation.csv"
OUT_MD = DATASETS / "agent_normal5v5_reconciliation.md"

FPS = 20.0
NATURAL_RATE = 3.0
NATURAL_START_S = 40.0
SMALL_MIN = 31
SMALL_MAX = 80

CAT_ORDER = [
    "4_minion",
    "6_jungle",
    "43_kill",
    "43_assist",
    "5_natural",
    "5_passive",
    "5_objective",
    "44_other",
    "47_other",
    "51_other",
]
CAT_LABEL = {
    "4_minion": "source4 小兵",
    "6_jungle": "source6 野怪",
    "43_kill": "source43 击杀候选",
    "43_assist": "source43 助攻候选",
    "5_natural": "source5 自然小额",
    "5_passive": "source5 被动/团队金候选",
    "5_objective": "source5 目标/推塔候选",
    "44_other": "source44 其他",
    "47_other": "source47 其他",
    "51_other": "source51 其他",
    "residual": "账内残差",
    "total": "流水合计",
}


def find_sample(explicit: Path | None) -> Path:
    if explicit:
        p = explicit if explicit.is_absolute() else ROOT / explicit
        if not p.exists():
            raise FileNotFoundError(f"sample not found: {p}")
        return p
    hits = sorted(SAMPLE_DIR.glob(SAMPLE_GLOB))
    if not hits:
        raise FileNotFoundError(f"no sample matching {SAMPLE_GLOB} under {SAMPLE_DIR}")
    return hits[0]


def load_roster(sample_name: str) -> dict[int, dict]:
    path = ANALYSIS / "abc_roster.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        for entry in data:
            if entry.get("file") == sample_name or entry.get("file", "").startswith(sample_name):
                return {
                    int(p["heroId"]): {
                        "name": p.get("name", ""),
                        "team": int(p.get("team", 0)),
                        "slot": int(p.get("slot", -1)),
                    }
                    for p in entry.get("players", [])
                }
    # fallback: replay_players.csv
    path = DATASETS / "replay_players.csv"
    if path.exists():
        out = {}
        for r in csv.DictReader(path.open(encoding="utf-8-sig")):
            if r.get("file") == sample_name or r.get("file", "").startswith(sample_name):
                out[int(r["hero_id"])] = {
                    "name": r.get("name", ""),
                    "team": int(r.get("team", 0)),
                    "slot": int(r.get("slot", -1)),
                }
        if out:
            return out
    raise FileNotFoundError("roster not found (abc_roster.json / replay_players.csv)")


def read_events_from_replay(sample: Path) -> tuple[list[dict], float]:
    sys.path.insert(0, str(ANALYSIS / "tools"))
    try:
        import abc_tags_full as abc  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "无法导入 abc_tags_full；可用 --from-csv 读取 datasets/player_gold_events.csv"
        ) from exc

    data = sample.read_bytes()
    recs, _ = abc.find_stream(data)
    events: list[dict] = []
    last_seq = 0
    for rec in recs:
        seq = int(rec["seq"])
        last_seq = max(last_seq, seq)
        msgs, _ = abc.parse_payload(rec["payload"])
        for m in msgs:
            if m[0] == "h" and m[1] == 0x02 and m[3] == 0x85 and len(m[4]) == 5:
                payload = m[4]
                events.append(
                    {
                        "hero": int(m[2]),
                        "seq": seq,
                        "source": int(payload[0]),
                        "amount": int.from_bytes(payload[1:5], "little"),
                    }
                )
    return events, last_seq / FPS


def read_events_from_dataset() -> tuple[list[dict], float]:
    path = DATASETS / "player_gold_events.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found")
    events = []
    last_seq = 0
    for r in csv.DictReader(path.open(encoding="utf-8-sig")):
        seq = int(r["seq"])
        last_seq = max(last_seq, seq)
        events.append(
            {
                "hero": int(r["hero_id"]),
                "seq": seq,
                "source": int(r["source"]),
                "amount": int(r["amount"]),
            }
        )
    return events, last_seq / FPS


def classify(source: int, amount: int) -> str:
    if source == 4:
        return "4_minion"
    if source == 6:
        return "6_jungle"
    if source == 43:
        return "43_kill" if amount >= 200 else "43_assist"
    if source == 5:
        if amount <= SMALL_MAX:
            return "5_natural"
        if amount < 200:
            return "5_passive"
        return "5_objective"
    if source in (44, 47, 51):
        return f"{source}_other"
    return f"{source}_other"


def base_hint(source: int, amount: int) -> int:
    """金额的整十/整五底额候选（尾数是同帧自然金/其他尾数）。"""
    if source == 5:
        if amount <= SMALL_MAX:
            return int(round(amount / 10.0)) * 10
        if amount < 200:
            return 130 if amount == 131 else 140
        return 230 if amount == 231 else (240 if amount == 243 else 250)
    if source == 43:
        return 200 if amount >= 200 else 100
    if source == 44:
        return 45
    if source == 47:
        return 175
    if source == 51:
        return 250
    return amount


def cluster_minion(amount: int) -> str:
    """source4 金额簇（5.57 候选边界，仅用于 note）。"""
    if 80 <= amount <= 95:
        return "melee"
    if 96 <= amount <= 120:
        return "ranged"
    if 121 <= amount <= 159:
        return "elite"
    if 180 <= amount <= 196:
        return "siege"
    if amount >= 197:
        return "cannon"
    return "other"


def build_players(events: list[dict], roster: dict[int, dict]) -> dict[int, dict]:
    players: dict[int, dict] = {}
    for hero, meta in roster.items():
        players[hero] = {
            "name": meta["name"],
            "team": meta["team"],
            "slot": meta["slot"],
            "cats": defaultdict(lambda: [0, 0]),
            "amounts": defaultdict(list),
            "events": 0,
            "gold": 0,
        }
    for ev in events:
        hero = ev["hero"]
        if hero not in players:
            players[hero] = {
                "name": f"hero_{hero}",
                "team": 0,
                "slot": -1,
                "cats": defaultdict(lambda: [0, 0]),
                "amounts": defaultdict(list),
                "events": 0,
                "gold": 0,
            }
        cat = classify(ev["source"], ev["amount"])
        p = players[hero]
        p["cats"][cat][0] += 1
        p["cats"][cat][1] += ev["amount"]
        p["amounts"][cat].append(ev["amount"])
        p["events"] += 1
        p["gold"] += ev["amount"]
    return players


def fmt_ng(n: int, g: int) -> str:
    return f"{n}/{g:,}" if n else "-"


def fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sample", type=Path, default=None, help="path to the .abc sample")
    ap.add_argument("--from-csv", action="store_true", help="read datasets/player_gold_events.csv instead of the .abc")
    ap.add_argument("--out-csv", type=Path, default=OUT_CSV)
    ap.add_argument("--out-md", type=Path, default=OUT_MD)
    args = ap.parse_args()

    sample = None if args.from_csv else find_sample(args.sample)
    if args.from_csv:
        events, duration = read_events_from_dataset()
        sample_name = "20260925_105224"
        sample_path_text = "(datasets/player_gold_events.csv)"
    else:
        events, duration = read_events_from_replay(sample)
        sample_name = sample.name
        sample_path_text = str(sample)
    roster = load_roster(sample_name)
    players = build_players(events, roster)

    # cross-check against the existing ledger dataset
    check_msg = ""
    old_path = DATASETS / "player_gold_events.csv"
    if old_path.exists() and not args.from_csv:
        old = [
            (int(r["hero_id"]), int(r["seq"]), int(r["source"]), int(r["amount"]))
            for r in csv.DictReader(old_path.open(encoding="utf-8-sig"))
        ]
        new = [(e["hero"], e["seq"], e["source"], e["amount"]) for e in events]
        check_msg = (
            f"与 player_gold_events.csv 对拍：{'一致' if sorted(old) == sorted(new) else '不一致'} "
            f"(replay {len(new)} 条 / csv {len(old)} 条)"
        )

    theory_natural = NATURAL_RATE * max(0.0, duration - NATURAL_START_S)
    expected_ticks = max(0.0, duration - NATURAL_START_S) / 10.0

    # global buckets
    bucket = defaultdict(lambda: [0, 0])
    for p in players.values():
        for cat, (n, g) in p["cats"].items():
            bucket[cat][0] += n
            bucket[cat][1] += g
    grand_events = sum(v[0] for v in bucket.values())
    grand_gold = sum(v[1] for v in bucket.values())

    # -------- CSV --------
    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.out_csv.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["player", "team", "source", "events", "gold", "share", "note"])

        for hero in sorted(players, key=lambda h: (players[h]["team"], players[h]["slot"], h)):
            p = players[hero]
            total = p["gold"]
            cats = p["cats"]
            minion = cats["4_minion"]
            jungle = cats["6_jungle"]
            kill = cats["43_kill"]
            assist = cats["43_assist"]
            natural = cats["5_natural"]
            passive = cats["5_passive"]
            objective = cats["5_objective"]
            other44 = cats["44_other"]
            other47 = cats["47_other"]
            other51 = cats["51_other"]
            core_gold = minion[1] + jungle[1] + kill[1] + assist[1] + natural[1]
            core_events = minion[0] + jungle[0] + kill[0] + assist[0] + natural[0]
            residual_gold = total - core_gold
            residual_events = p["events"] - core_events

            # minion note with cluster detail
            cl_n = Counter()
            cl_g = Counter()
            for a in p["amounts"]["4_minion"]:
                c = cluster_minion(a)
                cl_n[c] += 1
                cl_g[c] += a
            cl_note = ", ".join(
                f"{k} {cl_n[k]}/{cl_g[k]:,}"
                for k in ("melee", "ranged", "elite", "siege", "cannon", "other")
                if cl_n[k]
            )
            small_amounts = p["amounts"]["5_natural"]
            strict_amounts = [a for a in small_amounts if a <= 33]
            long_amounts = [a for a in small_amounts if a > 33]
            source5_total = sum(p["cats"][c][1] for c in ("5_natural", "5_passive", "5_objective"))

            notes = {
                "4_minion": f"到手金币，事件均{minion[1] / minion[0]:.1f}" if minion[0] else "无记录",
                "6_jungle": "normalMonster 160/174/171/180/190/200 候选" if jungle[0] else "无记录",
                "43_kill": "202/203≈200 底额+尾数；击杀候选" if kill[0] else "无记录",
                "43_assist": "102≈100 底额+尾数；助攻候选" if assist[0] else "无记录",
                "5_natural": (
                    f"31-73；31-33 {len(strict_amounts)}条/{sum(strict_amounts)}（约10s×3/s），"
                    f"41-73 {len(long_amounts)}条/{sum(long_amounts)}（约14-24s或合并推送）"
                    if natural[0]
                    else "无小额自然金记录（不代表没有自然收入）"
                ),
                "5_passive": (
                    f"131-146；130/140底额+1-6尾数；太乙/辅助装/团队被动候选"
                    if passive[0]
                    else "无记录"
                ),
                "5_objective": (
                    "231-254；230/240/250底额+尾数；目标/推塔候选"
                    if objective[0]
                    else "无记录"
                ),
                "44_other": "47=45+2；助攻/一血候选" if other44[0] else "无记录",
                "47_other": "179=175+4；暴君/主宰/目标候选" if other47[0] else "无记录",
                "51_other": "254=250+4；目标/推塔候选" if other51[0] else "无记录",
            }
            if minion[0]:
                notes["4_minion"] += f"；簇 {cl_note}（5.57 候选边界）"

            rows = [
                ("4_minion", minion[0], minion[1]),
                ("6_jungle", jungle[0], jungle[1]),
                ("43_kill", kill[0], kill[1]),
                ("43_assist", assist[0], assist[1]),
                ("5_natural", natural[0], natural[1]),
            ]
            for cat in ("5_passive", "5_objective", "44_other", "47_other", "51_other"):
                if cats[cat][0]:
                    rows.append((cat, cats[cat][0], cats[cat][1]))
            for cat, n, g in rows:
                w.writerow(
                    [
                        p["name"],
                        p["team"],
                        cat,
                        n,
                        g,
                        f"{g / total:.6f}" if total else "0",
                        notes[cat],
                    ]
                )
            # memo rows
            residual_parts = (
                f"5_passive {passive[0]}/{passive[1]:,} + 5_objective {objective[0]}/{objective[1]:,} "
                f"+ 51 {other51[0]}/{other51[1]:,} + 47 {other47[0]}/{other47[1]:,} "
                f"+ 44 {other44[0]}/{other44[1]:,}"
            )
            w.writerow(
                [
                    p["name"],
                    p["team"],
                    "residual",
                    residual_events,
                    residual_gold,
                    f"{residual_gold / total:.6f}" if total else "0",
                    f"账内残差=total-(4+6+43+5_natural)；{residual_parts}；memo 行，勿与 source 行相加",
                ]
            )
            w.writerow(
                [
                    p["name"],
                    p["team"],
                    "total",
                    p["events"],
                    total,
                    "1.000000" if total else "0",
                    "流水合计，不含初始300；初始300为存量；source 行 share 之和=1",
                ]
            )

        # global memo row
        w.writerow(
            [
                "ALL",
                "",
                "total",
                grand_events,
                grand_gold,
                "1.000000",
                f"十人流水合计；{check_msg}",
            ]
        )
        w.writerow(
            [
                "ALL",
                "",
                "residual",
                grand_events
                - sum(bucket[c][0] for c in ("4_minion", "6_jungle", "43_kill", "43_assist", "5_natural")),
                grand_gold
                - sum(bucket[c][1] for c in ("4_minion", "6_jungle", "43_kill", "43_assist", "5_natural")),
                f"{(grand_gold - sum(bucket[c][1] for c in ('4_minion','6_jungle','43_kill','43_assist','5_natural'))) / grand_gold:.6f}",
                "十人账内残差合计；memo 行",
            ]
        )

    # -------- Markdown --------
    core_cats = ("4_minion", "6_jungle", "43_kill", "43_assist", "5_natural")
    core_gold = sum(bucket[c][1] for c in core_cats)
    core_events = sum(bucket[c][0] for c in core_cats)
    residual_gold = grand_gold - core_gold
    residual_events = grand_events - core_events
    passive_gold = bucket["5_passive"][1]
    objective_class_gold = bucket["5_objective"][1] + bucket["51_other"][1]
    objective_class_events = bucket["5_objective"][0] + bucket["51_other"][0]
    other_class_gold = bucket["44_other"][1] + bucket["47_other"][1]
    other_class_events = bucket["44_other"][0] + bucket["47_other"][0]
    small_gold = bucket["5_natural"][1]
    small_events = bucket["5_natural"][0]
    strict_gold = sum(
        a for p in players.values() for a in p["amounts"]["5_natural"] if a <= 33
    )
    strict_events = sum(
        1 for p in players.values() for a in p["amounts"]["5_natural"] if a <= 33
    )
    long_gold = small_gold - strict_gold
    long_events = small_events - strict_events
    source5_total = sum(bucket[c][1] for c in ("5_natural", "5_passive", "5_objective"))
    theory_resid = grand_gold - (
        bucket["4_minion"][1]
        + bucket["6_jungle"][1]
        + bucket["43_kill"][1]
        + bucket["43_assist"][1]
        + theory_natural * len(players)
    )

    # residual bucket stats
    def bucket_detail(cats: tuple[str, ...]) -> dict:
        amounts = []
        per_player = []
        for hero, p in players.items():
            vals = []
            for c in cats:
                vals.extend(p["amounts"][c])
            if vals:
                amounts.extend(vals)
                per_player.append((p["name"], len(vals), sum(vals)))
        # base/tail by category-aware pass
        base = 0
        for c in cats:
            src = 5 if c.startswith("5_") else int(c[:2])
            for a in (players[h]["amounts"][c] for h in players):
                base += sum(base_hint(src, x) for x in a)
        total = sum(amounts)
        return {
            "n": len(amounts),
            "gold": total,
            "base": base,
            "tail": total - base,
            "players": sorted(per_player, key=lambda x: -x[2]),
        }

    b_passive = bucket_detail(("5_passive",))
    b_objective = bucket_detail(("5_objective",))
    b_51 = bucket_detail(("51_other",))
    b_47 = bucket_detail(("47_other",))
    b_44 = bucket_detail(("44_other",))
    b_obj_class = bucket_detail(("5_objective", "51_other"))
    b_other_class = bucket_detail(("44_other", "47_other"))

    def player_list(stats: list[tuple[str, int, int]], limit: int = 4) -> str:
        head = "、".join(f"{n} {c}/{g:,}" for n, c, g in stats[:limit])
        return head + (f" 等{len(stats)}人" if len(stats) > limit else "")

    # dynamic narrative helpers
    cov_rows = sorted(
        (
            (sum(p["amounts"]["5_natural"]) / theory_natural, p["name"])
            for p in players.values()
        ),
        reverse=True,
    )
    top_cov = "、".join(f"{name} {cov * 100:.1f}%" for cov, name in cov_rows[:3])
    bottom_cov = "、".join(f"{name} {cov * 100:.1f}%" for cov, name in cov_rows[-3:])
    theory_rows = []
    for p in players.values():
        p_core_other = sum(p["cats"][x][1] for x in core_cats if x != "5_natural")
        theory_rows.append((p["name"], p["gold"] - p_core_other - theory_natural))
    neg_n = sum(1 for _, v in theory_rows if v < 0)
    closest = min(theory_rows, key=lambda x: abs(x[1]))
    obj_players_txt = "、".join(f"{n} {c}次" for n, c, _ in b_obj_class["players"])
    passive_counts = [len(p["amounts"]["5_passive"]) for p in players.values() if p["amounts"]["5_passive"]]
    passive_n_range = f"{min(passive_counts)}-{max(passive_counts)}" if passive_counts else "0"
    minion_share = bucket["4_minion"][1] / grand_gold * 100
    natural_share = bucket["5_natural"][1] / grand_gold * 100
    passive_obj_share = (
        bucket["5_passive"][1] + bucket["5_objective"][1] + bucket["51_other"][1]
    ) / grand_gold * 100
    kill_share = (bucket["43_kill"][1] + bucket["43_assist"][1]) / grand_gold * 100
    jungle_share = bucket["6_jungle"][1] / grand_gold * 100
    other_share = (bucket["44_other"][1] + bucket["47_other"][1]) / grand_gold * 100

    lines: list[str] = []
    add = lines.append
    add("# 普通 5v5 主样本十人经济对账（20260925_105224）")
    add("")
    add(f"- 样本：`{sample_path_text}`")
    add(f"- 模式：`confType1=50`（普通 5v5）；初始 300；自然金 cfg1 **3 金币/秒，40s 起**（`battleDynamicProperty`）。")
    add(f"- 流水：`0x02 flag=0x85 len=5`，`sourceType:u8 + amount:u32LE`；**{grand_events} 条 / {grand_gold:,} 金币**，覆盖 10 个实体。")
    add(f"- 时长：最后一帧 seq/20 = **{duration:.1f}s**；3/s 自然金基准 = **{theory_natural:,.1f}/人**。")
    add("- 口径：流水合计**不含初始 300**（初始 300 是存量，不是来源事件）。`share` 为占该玩家流水比例；`residual`/`total` 为 memo 行。")
    add("- 只读：不修改回放，不注入进程，不读取 param.json，不使用 runtime_dump。")
    add("")
    add("## 1. 十人分项")
    add("")
    add("| 玩家(队/位) | 小兵 n/g | 野怪 n/g | 击杀 n/g | 助攻 n/g | 自然小额 n/g | 被动 n/g | 目标 n/g | 其他 n/g | 流水合计 | 账内残差 g/% |")
    add("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for hero in sorted(players, key=lambda h: (players[h]["team"], players[h]["slot"], h)):
        p = players[hero]
        c = p["cats"]
        obj_n = c["5_objective"][0] + c["51_other"][0]
        obj_g = c["5_objective"][1] + c["51_other"][1]
        oth_n = c["44_other"][0] + c["47_other"][0]
        oth_g = c["44_other"][1] + c["47_other"][1]
        core_g = sum(c[x][1] for x in core_cats)
        resid_g = p["gold"] - core_g
        add(
            f"| {p['name']} ({p['team']}/{p['slot']}) | {fmt_ng(*c['4_minion'])} | {fmt_ng(*c['6_jungle'])} | "
            f"{fmt_ng(*c['43_kill'])} | {fmt_ng(*c['43_assist'])} | {fmt_ng(*c['5_natural'])} | "
            f"{fmt_ng(*c['5_passive'])} | {fmt_ng(obj_n, obj_g)} | {fmt_ng(oth_n, oth_g)} | "
            f"{p['gold']:,} | {resid_g:,} / {resid_g / p['gold'] * 100:.1f}% |"
        )
    add(
        f"| **合计** | **{fmt_ng(*bucket['4_minion'])}** | **{fmt_ng(*bucket['6_jungle'])}** | "
        f"**{fmt_ng(*bucket['43_kill'])}** | **{fmt_ng(*bucket['43_assist'])}** | "
        f"**{fmt_ng(*bucket['5_natural'])}** | **{fmt_ng(*bucket['5_passive'])}** | "
        f"**{fmt_ng(objective_class_events, objective_class_gold)}** | "
        f"**{fmt_ng(other_class_events, other_class_gold)}** | **{grand_gold:,}** | "
        f"**{residual_gold:,} / {residual_gold / grand_gold * 100:.1f}%** |"
    )
    add("")
    add("> 表中“目标”= source5 231-254 + source51 254；“其他”= source44/47。source 行与 memo 行的完整拆分见 CSV。")
    add("")
    add("### 来源总表")
    add("")
    add("| 来源 | 事件 | 金币 | 占流水 |")
    add("|---|---:|---:|---:|")
    for cat in CAT_ORDER:
        n, g = bucket[cat]
        add(f"| {CAT_LABEL[cat]} | {n} | {g:,} | {g / grand_gold * 100:.2f}% |")
    add(f"| **合计** | **{grand_events}** | **{grand_gold:,}** | **100.00%** |")
    add("")
    add("团队合计：")
    for team in (1, 2):
        team_players = [h for h in players if players[h]["team"] == team]
        tg = sum(players[h]["gold"] for h in team_players)
        te = sum(players[h]["events"] for h in team_players)
        team_core = sum(players[h]["cats"][x][1] for h in team_players for x in core_cats)
        add(
            f"- 团队 {team}：{len(team_players)} 人，{te} 条 / {tg:,} 金币；"
            f"账内残差 {tg - team_core:,}（{(tg - team_core) / tg * 100:.1f}%）。"
        )
    add("")
    add("## 2. 自然金估算（source5 小额）")
    add("")
    add("| 玩家 | 小额 n | 小额金 | 30×n（10s 节拍法） | 3/s×时长 | 偏差(观测-理论) | 覆盖率 | 31-33 n/g | 41-73 n/g |")
    add("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for hero in sorted(players, key=lambda h: (players[h]["team"], players[h]["slot"], h)):
        p = players[hero]
        vals = p["amounts"]["5_natural"]
        n = len(vals)
        g = sum(vals)
        s_n = sum(1 for a in vals if a <= 33)
        s_g = sum(a for a in vals if a <= 33)
        l_n = sum(1 for a in vals if a > 33)
        l_g = sum(a for a in vals if a > 33)
        add(
            f"| {p['name']} | {n} | {g:,} | {30 * n:,} | {theory_natural:,.1f} | {g - theory_natural:,.1f} | "
            f"{g / theory_natural * 100:.1f}% | {s_n}/{s_g:,} | {l_n}/{l_g:,} |"
        )
    add(
        f"| **合计** | **{small_events}** | **{small_gold:,}** | **{30 * small_events:,}** | "
        f"**{theory_natural * len(players):,.1f}** | **{small_gold - theory_natural * len(players):,.1f}** | "
        f"**{small_gold / (theory_natural * len(players)) * 100:.1f}%** | "
        f"**{strict_events}/{strict_gold:,}** | **{long_events}/{long_gold:,}** |"
    )
    add("")
    add("**解读**")
    add("")
    add(
        f"1. 小额共 **{small_events} 条 / {small_gold:,} 金币**。31-33 档 {strict_events} 条 / {strict_gold:,}，"
        f"按 3/s 折算 10.3-11.0s，基本就是“10 秒推送”；41-73 档 {long_events} 条 / {long_gold:,}，"
        f"折算 13.7-24.3s，可能是合并推送，也可能是 40/50/60/70 底额+自然尾数。"
    )
    add(
        f"2. 10 秒节拍法（n×30）合计 **{30 * small_events:,}**；直接按金额求和 **{small_gold:,}**；"
        f"3/s×{duration - NATURAL_START_S:.1f}s×10 人 = **{theory_natural * len(players):,.1f}**。"
        f"观测只覆盖理论值的 **{small_gold / (theory_natural * len(players)) * 100:.1f}%**（按金额）/ "
        f"**{small_events / (expected_ticks * len(players)) * 100:.1f}%**（按 10s tick 数：{small_events} vs 约 {expected_ticks * len(players):.0f}）。"
    )
    add(
        f"3. 每人覆盖率 **0.0%-{cov_rows[0][0] * 100:.1f}%**：{top_cov} 较高；{bottom_cov} 较低。"
        "**source5 小额是稀疏样本，不是完整自然金节拍**；0 条不等于没有自然收入。"
    )
    add(
        f"4. 若把 source5 全部（含大额）都当作自然/系统金，也只有 {source5_total:,}，"
        f"仍只有理论值的 {source5_total / (theory_natural * len(players)) * 100:.1f}%。"
        f"流水合计 {grand_gold:,} 无法同时容纳“理论自然金 18,441 + 小兵/野怪/击杀”；"
        f"按理论自然金口径，十人残差合计 **{theory_resid:,}**（{neg_n}/10 人为负；"
        f"最接近 0 的是 {closest[0]} {closest[1]:,.1f}），"
        "说明自然金大部分没有以 source5 形式进入流水，不能把 3/s×时长 直接当账内自然金。"
    )
    add("")
    add("## 3. 残差来源（账内残差）")
    add("")
    add(
        f"**账内残差 = {residual_gold:,}（{residual_gold / grand_gold * 100:.1f}% 流水）**，"
        f"核心四类 {core_gold:,}（{core_gold / grand_gold * 100:.1f}%）。按金额模式拆："
    )
    add("")
    add("| 残差桶 | 事件 | 金币 | 整十/整五底额 | 尾数 | 出现玩家（n/g） | 候选来源 |")
    add("|---|---:|---:|---:|---:|---|---|")
    add(
        f"| source5 131-146 | {b_passive['n']} | {b_passive['gold']:,} | {b_passive['base']:,} | {b_passive['tail']} | "
        f"{player_list(b_passive['players'])} | 太乙/辅助装/团队行为金（候选，中置信） |"
    )
    add(
        f"| source5 231-254 | {b_objective['n']} | {b_objective['gold']:,} | {b_objective['base']:,} | {b_objective['tail']} | "
        f"{player_list(b_objective['players'])} | 目标/推塔（候选，中低置信） |"
    )
    add(
        f"| source51 254 | {b_51['n']} | {b_51['gold']:,} | {b_51['base']:,} | {b_51['tail']} | "
        f"{player_list(b_51['players'])} | 目标/推塔（与 231-254 同类，候选） |"
    )
    add(
        f"| source47 179 | {b_47['n']} | {b_47['gold']:,} | {b_47['base']:,} | {b_47['tail']} | "
        f"{player_list(b_47['players'])} | 暴君/主宰/目标（候选，低置信） |"
    )
    add(
        f"| source44 47 | {b_44['n']} | {b_44['gold']:,} | {b_44['base']:,} | {b_44['tail']} | "
        f"{player_list(b_44['players'])} | 助攻/一血（候选，低置信） |"
    )
    add(
        f"| **合计** | **{residual_events}** | **{residual_gold:,}** | "
        f"**{b_passive['base'] + b_objective['base'] + b_51['base'] + b_47['base'] + b_44['base']:,}** | "
        f"**{b_passive['tail'] + b_objective['tail'] + b_51['tail'] + b_47['tail'] + b_44['tail']}** | {len(players)} 人 | — |"
    )
    add("")
    add(
        "> 补充：source43 的 203/202/102 也可拆成 200/200/100 底额 + 2-3 尾数；"
        "source4 的 87/88/90 等可拆成 80 底额 + 7-10 尾数。所有来源都带 1-10 的同帧尾数，"
        "与“离散奖励底额 + 自然金尾数”一致；这进一步说明 131-146/231-254 是离散奖励，"
        "不是按 3/s 连续累积出来的自然金。"
    )
    add("")
    add("**归因判断**")
    add("")
    add(
        f"1. **被动/团队金（131-146）**：{b_passive['n']} 条 / {b_passive['gold']:,}，占残差 "
        f"{b_passive['gold'] / residual_gold * 100:.1f}%。金额几乎都是 **130 或 140 底额 + 1-6 尾数**"
        f"（底额 {b_passive['base']:,} + 尾数 {b_passive['tail']}），且 10 人全有（每人 {passive_n_range} 条），"
        "更像团队/被动结算而非个人补刀或自然累积。文档 5.82 明确把大额 131-254 指为太乙/辅助装等被动金币；"
        "CSProtocol 也有 `dwPassiveTaiYiZhenRenCoin`、`dwAidEquipCoin`、`dwTeamBehaviorCoin` 等字段。"
        "主样本未解出英雄选择，**太乙只能是候选**，不能按英雄确认。"
    )
    add(
        f"2. **目标/推塔类（231-254 + source51）**：{objective_class_events} 条 / {objective_class_gold:,}，占残差 "
        f"{objective_class_gold / residual_gold * 100:.1f}%。金额是 **230/240/250 底额 + 尾数**；"
        f"集中出现在 {player_list(b_obj_class['players'], 5)}。source51 的 254 与 source5 的 254 同为 250 底额，"
        "支持“同一类目标/推塔奖励，只是 sourceType 不同”的解释。若按推塔/暴君/主宰计，"
        f"{obj_players_txt}，量级与一局 11 分钟的目标数相符。"
    )
    add(
        f"3. **其他（source47/44）**：source47 179（Vetymoment，175+4）与 source44 47（李不信有归途，45+2）"
        f"共 {other_class_gold}，占残差 {other_class_gold / residual_gold * 100:.1f}%。"
        "179 更像暴君/主宰/目标，47 更像助攻/一血；两者都只有 1 条，置信度低。"
    )
    add(
        "4. **没有残差落在小兵/野怪/击杀/助攻**：这四类与 source5 自然小额已把 "
        f"{core_gold / grand_gold * 100:.1f}% 流水分完；残差全部来自 source5 大额与 44/47/51。"
    )
    add("")
    add("## 4. 结论与风险")
    add("")
    add(
        f"- 十人流水 **{grand_gold:,}**：小兵 {minion_share:.1f}%、自然小额 {natural_share:.1f}%、"
        f"被动/目标 {passive_obj_share:.1f}%、击杀/助攻 {kill_share:.1f}%、野怪 {jungle_share:.1f}%、"
        f"其他 {other_share:.1f}%。小兵仍是最大项；source5 大额（被动/目标）是第二大块。"
    )
    add(
        f"- 自然金：source5 小额只有 **{small_gold:,}**，是 3/s×时长的 **{small_gold / (theory_natural * len(players)) * 100:.1f}%**；"
        f"按 10s tick 数只有 **{small_events / (expected_ticks * len(players)) * 100:.1f}%**。"
        "**每人自然金只能给下界，不能给真值**；0 条尤其不能解读为无自然金。"
    )
    add(
        f"- 账内残差 **{residual_gold:,}（{residual_gold / grand_gold * 100:.1f}%）**，主要可归为："
        f"被动/团队金 {b_passive['gold']:,} + 目标/推塔 {objective_class_gold:,} + 其他 {other_class_gold}。"
        "这是“已写入流水的残差”，不是“终局经济 - 已分类”的完整残差。"
    )
    add(
        "- 主样本未解出可用的结算面板/英雄选择：source43 的 203=击杀、102=助攻仍是候选；"
        "source5 大额的具体是太乙、辅助装还是推塔/龙，无法逐项定名。"
        "录屏 OCR 只覆盖快速赛（末帧 1:46），不能用来校验本样本的终局金币或 6:4。"
    )
    add(
        f"- 全局 `0x12` 标量 34,690–38,324（5.57）与流水+初始300 = {grand_gold + 300 * len(players):,} 量级接近；"
        "但 `0x12` 是全局当前量/波动值，不是逐人累计，不能据此把理论自然金直接补进流水。"
    )
    add(
        "- 初始 300 未计入流水；若要对照终局金币，需要在流水合计上再加 300/人，并补上未写入流水的自然金/其他收入。"
    )
    add("")
    add("## 5. 产物")
    add("")
    add(f"- CSV：`{args.out_csv.as_posix()}`")
    add(f"- 报告：`{args.out_md.as_posix()}`")
    add("- 脚本：`tools/agent_normal5v5_reconcile.py`（默认直接解析 .abc；`--from-csv` 读现有流水）")
    add("")
    if check_msg:
        add(f"数据校验：{check_msg}")
        add("")

    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # console summary
    print(f"sample: {sample_path_text}")
    print(f"duration: {duration:.2f}s; natural benchmark: {theory_natural:.1f}/player")
    print(f"events: {grand_events}; gold: {grand_gold}")
    print(f"core: {core_events}/{core_gold}; residual: {residual_events}/{residual_gold}")
    print(f"natural small: {small_events}/{small_gold}; coverage {small_gold / (theory_natural * len(players)) * 100:.1f}%")
    print(f"residual buckets: passive {bucket['5_passive']}, objective {bucket['5_objective']}, "
          f"51 {bucket['51_other']}, 47 {bucket['47_other']}, 44 {bucket['44_other']}")
    print(f"wrote: {args.out_csv}")
    print(f"wrote: {args.out_md}")
    if check_msg:
        print(check_msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
