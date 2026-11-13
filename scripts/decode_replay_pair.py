"""Full decode report for one `.abc` + `.ope` replay pair.

Scoped tool: point it at the two files for a single replay and it emits every
field this project can currently decode, each with its source tier, plus an
explicit list of what the container does not carry.  Nothing is estimated and no
field is named without evidence.

    python scripts/decode_replay_pair.py \
        --abc "data/replays/samples/20261102_161129/<file>.abc" \
        --ope "data/replays/samples/20261102_161129/<file>.ope" \
        --out test-results/pair-report.json
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from abc_init_block import (  # noqa: E402
    known_fields, kv_pairs, kv_ruleset_sha, locate, server_stamp_from_name)
import operator_stream as ops  # noqa: E402
import replay_parser as rp  # noqa: E402
import build_timings  # noqa: E402
from replay_state_engine import (  # noqa: E402
    build_from_bytes, load_item_names, load_prices)

MISSING = {
    "kills": "回放容器只记录输入命令，没有击杀归属；只有 1251 的胜负/MVP/评分。",
    "deaths": "没有死亡事件时间轴。",
    "assists": "没有助攻记录。",
    "goldIncome": "尾部购买镜像没有金币收入事件，只能重建支出账本。",
    "hp": "容器不含 HP 字段。",
    "positions": "连续轨迹不可得：移动指令积分实测残差/位移 0.94–1.00，无预测力；只有稀疏坐标锚点。",
    "opePayloadSemantics": "操作流结构已消费到流尾，但除 frame/unityFrame 外的字段名是推断，"
                           "没有字段级证据，因此不进入字段表。",
}


def _sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _ope_stream(ope_bytes: bytes) -> bytes | None:
    try:
        inner = zlib.decompressobj(-15).decompress(ope_bytes[1:])
        _pos, _declared, stream = rp._locate_second_layer(inner)
        return stream
    except (zlib.error, rp.ReplayFormatError, ValueError):
        return None


def ope_section(ope_bytes: bytes) -> dict:
    stream = _ope_stream(ope_bytes)
    if stream is None:
        return {"available": False, "reason": "两层解压失败"}
    records, repairs, end = ops.parse_with_repair(stream, 0)
    types = collections.Counter(record["typeName"] for record in records)
    tentative = sum(1 for record in records if record["tentative"])
    frames = [record["fields"]["frame"] for record in records
              if "frame" in record["fields"]]
    unity = [record["fields"]["unityFrame"] for record in records
             if record["typeName"] == "UnityFrameOpe"
             and record["fields"].get("unityFrame", 0) >= 1000]
    return {
        "available": True,
        "sha256": _sha(ope_bytes),
        "bytes": len(ope_bytes),
        "streamBytes": len(stream),
        "records": len(records),
        "tentativeRecords": tentative,
        "typeCounts": dict(types.most_common()),
        "repairPoints": repairs,
        "consumedBytes": end,
        "consumedPct": round(100.0 * end / len(stream), 3),
        "frameFieldRange": [min(frames), max(frames)] if frames else None,
        "frameFieldNote": "只有局部可用：该字段在多种记录里被读成 u16，超出对局帧数即视为不可信。",
        "unitySamples": len(unity),
        "unityRange": [min(unity), max(unity)] if unity else None,
        "unityNote": "UnityFrameOpe 的时钟；回绕周期在本样本内不规整，未用于时间轴。",
        "payloadSemantics": None,
    }


def abc_section(abc_bytes: bytes) -> dict:
    report = rp.inspect_abc(abc_bytes, hero_names=None)
    header = report.get("header") or {}
    blocks = report.get("blocks") or []
    mvp = report.get("mvpScore") or {}
    located = locate(abc_bytes)
    init = None
    if located is not None:
        init = known_fields(located, kv_pairs(abc_bytes, located))
        init["scalarStart"] = located["scalarStart"]
        init["kvCount"] = located["kvCount"]
        init["wordClasses"] = "95 constant / 14 few-variant / 1 per-match (110 words)"
    return {
        "sha256": _sha(abc_bytes),
        "bytes": len(abc_bytes),
        "versions": header.get("versions"),
        "builds": header.get("builds"),
        "localHeroId": header.get("localHeroId"),
        "localHeroName": header.get("localHeroName"),
        "mapType": header.get("mapType"),
        "mapId": header.get("mapId"),
        "totalFrames": header.get("totalFrameNum"),
        "frameRecords": (report.get("frames") or {}).get("records"),
        "durationSec": round(((report.get("frames") or {}).get("records") or 0) / 15.0, 2),
        "winningCamp": mvp.get("winningCamp"),
        "mvpEntityId": mvp.get("winMvpEntityId"),
        "players": [{
            "order": b.get("order"), "entityId": b.get("entityId"),
            "heroId": b.get("heroId"), "hero": b.get("heroName"),
            "camp": b.get("camp"), "slot": b.get("position"),
            "isSelf": b.get("self"), "rating": b.get("score"),
        } for b in blocks],
        "initBlock": init,
        "anchorSamples": len(((report.get("playerEvents") or {}).get("positions")
                              or {}).get("events") or []),
    }


def build_report(abc_path: Path, ope_path: Path | None) -> dict:
    abc_bytes = abc_path.read_bytes()
    ope_bytes = ope_path.read_bytes() if ope_path else None

    state = build_from_bytes(abc_bytes, ope_bytes)
    purchases = state["events"]["purchases"]
    learns = state["events"]["learns"]

    players = []
    for player in state["players"]:
        players.append({
            "entityId": player["entityId"], "hero": player["hero"],
            "player": player["player"], "camp": player["camp"],
            "team": player["team"], "slot": player["slot"],
            "win": player["win"], "mvp": player["mvp"],
            "rating": player["rating"],
            "levelFinal": min(1 + player["learnCount"], 15),
            "skillPoints": player["learnCount"],
            "purchases": player["purchaseCount"],
            "goldSpentFinal": player["goldSpentFinal"],
            "finalItems": player["finalItems"],
            "ccBreakdown": player.get("ccBreakdown") or {
                "direction": 0, "stopMove": 0, "attackPos": 0,
                "positionMove": 0, "other": 0},
        })

    per_player_actions = {}
    for frame in state["timeline"]:
        for cell in frame["p"]:
            bucket = per_player_actions.setdefault(cell["e"], collections.Counter())
            for key in ("m", "a", "s", "c", "am"):
                bucket[key] += cell[key]

    return {
        "schema": "kpl-replay-pair-report-v1",
        "files": {
            "abc": {"name": abc_path.name, "path": str(abc_path)},
            "ope": ({"name": ope_path.name, "path": str(ope_path)}
                    if ope_path else None),
        },
        "abc": abc_section(abc_bytes),
        "ope": ope_section(ope_bytes) if ope_bytes else {"available": False,
                                                         "reason": "未提供 .ope"},
        "match": {
            "durationSec": state["match"]["durationSec"],
            "winningCamp": state["match"]["winningCamp"],
            "mvpEntityId": state["match"]["mvpEntityId"],
            "scoreTable": state["match"]["scoreTable"],
        },
        "players": players,
        "economy": {
            "purchaseEventsRaw": len(purchases),
            "uniquePurchases": len(purchases),
            "totalSpend": sum(player["goldSpentFinal"] or 0 for player in players),
            "perPlayerSpend": {str(p["entityId"]): p["goldSpentFinal"] for p in players},
            "tier": "derived（首次出现的购买价累加；是支出账本，不是收入）",
        },
        "skills": {
            "learnEvents": len(learns),
            "perPlayer": {str(p["entityId"]): p["skillPoints"] for p in players},
            "tier": "decoded（LEARNSKILL 事件）",
        },
        "actions": {
            "perPlayerTotals": {str(entity): dict(counter)
                               for entity, counter in sorted(per_player_actions.items())},
            "tier": "decoded（帧命令计数，15 fps）",
            "ccNote": ("`cc` 是 CSDT_FRAPBOOT_CC 客户端指令同步包（朝向/停止/落点），"
                       "不是控制效果；拆分见 ccCommands。"),
        },
        "ccCommands": {
            "perPlayer": {str(p["entityId"]): p["ccBreakdown"] for p in players},
            "innerCommandNames": {"2d": "direction", "03": "stopMove",
                                  "2c": "attackPos", "01": "positionMove"},
            "note": ("所谓「控制」一栏已拆开：CC 是 CSDT_FRAPBOOT_CC 客户端指令同步包"
                     "（朝向/停止/落点），不是控制效果；回放里没有控制效果记录。"),
        },
        "purchases": purchases,
        "learns": learns,
        "anchors": state["anchors"],
        "matchConfig": state.get("matchConfig"),
        "buildTimings": build_timings.build_report(state),
        "undecoded": MISSING,
    }


def summarize(report: dict) -> str:
    abc = report["abc"]
    ope = report["ope"]
    lines = []
    lines.append(f"ABC  {abc['sha256'][:16]}  {abc['bytes']:,} B  "
                 f"build {'/'.join(abc.get('builds') or [])}  "
                 f"{abc['totalFrames']} 帧 ≈ {abc['durationSec']:.0f}s")
    lines.append(f"     地图 mapType={abc['mapType']} mapId={abc['mapId']}  "
                 f"自身英雄 {abc['localHeroName']}({abc['localHeroId']})  "
                 f"胜方 {abc['winningCamp']}  MVP entity {abc['mvpEntityId']}")
    if ope.get("available"):
        lines.append(f"OPE  {ope['sha256'][:16]}  {ope['bytes']:,} B  "
                     f"流 {ope['streamBytes']:,} B → {ope['records']:,} 条记录  "
                     f"消费 {ope['consumedPct']}%  修复 {len(ope['repairPoints'])} 处")
        top = list(ope["typeCounts"].items())[:6]
        lines.append("     类型 Top: " + ", ".join(f"{k}={v}" for k, v in top))
    lines.append("")
    lines.append("十人：")
    for player in report["players"]:
        mark = "★MVP" if player["mvp"] else ("胜" if player["win"] else "负")
        lines.append(f"  {player['camp']}-{player['slot']} {player['hero']:5s} "
                     f"{player['player'][:10]:12s} 评分{player['rating']:>5} {mark:5s} "
                     f"等级{player['levelFinal']:2d} 加点{player['skillPoints']:2d} "
                     f"购买{player['purchases']:2d} 花费{player['goldSpentFinal'] or 0:>6}")
    lines.append("")
    lines.append(f"经济：{report['economy']['uniquePurchases']} 笔首次购买，"
                 f"合计支出 {report['economy']['totalSpend']}")
    lines.append(f"技能：{report['skills']['learnEvents']} 次加点")
    cmd = report["actions"]["perPlayerTotals"]
    lines.append("动作（移动/攻击/技能/CC指令/瞄准）：")
    for entity, totals in list(cmd.items())[:10]:
        name = next(p["hero"] for p in report["players"]
                    if str(p["entityId"]) == entity)
        lines.append(f"  {name:5s} {totals.get('m', 0):6d}/{totals.get('a', 0):6d}/"
                     f"{totals.get('s', 0):5d}/{totals.get('c', 0):5d}/{totals.get('am', 0):5d}")
    lines.append("  CC 拆分（朝向/停止/落点/位置移动/其他）：")
    for entity, breakdown in report["ccCommands"]["perPlayer"].items():
        if not any(breakdown.values()):
            continue
        name = next(p["hero"] for p in report["players"]
                    if str(p["entityId"]) == entity)
        lines.append(f"    {name:5s} 朝向{breakdown['direction']:5d} 停止{breakdown['stopMove']:5d} "
                     f"落点{breakdown['attackPos']:4d} 位置{breakdown['positionMove']:4d} "
                     f"其他{breakdown['other']:3d}")
    lines.append("  注：CC 是客户端指令同步包，不是控制效果。")
    timings = report.get("buildTimings") or {}
    lines.append("")
    lines.append("成品装备时序（三件套 = 第 3 件成品的购买时刻）：")
    lines.append(f"  {'英雄':<6}{'选手':<12}{'三件套':>7}{'含鞋':>7}{'2000+':>7}  成品序列")
    for info in timings.get("perPlayer", {}).values():
        variant = info.get("variants") or {}
        seq = " > ".join(f"{i['tText']} {i['name']}" for i in info.get("finished") or [])
        lines.append(f"  {info.get('hero') or '':<6}{(info.get('player') or '')[:10]:<12}"
                     f"{(variant.get('noShoes') or {}).get('tText', '—'):>7}"
                     f"{(variant.get('withShoes') or {}).get('tText', '—'):>7}"
                     f"{(variant.get('bigOnly2000') or {}).get('tText', '—'):>7}  {seq}")
    lines.append("    " + (timings.get("caveat") or ""))
    config = report.get("matchConfig") or {}
    lines.append("")
    lines.append(f"初始化：modeWord={config.get('modeWord')} "
                 f"initialGold={config.get('initialGold')} "
                 f"serverTime={config.get('serverTimeUnixSeconds')} "
                 f"KV 规则集={str(config.get('kvRulesetSha256'))[:12]}…")
    lines.append("")
    lines.append("明确解不出（容器里没有，不估算）：")
    for key, why in report["undecoded"].items():
        lines.append(f"  - {key}: {why}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--abc", type=Path, required=True)
    parser.add_argument("--ope", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--json", action="store_true", help="print the full JSON")
    args = parser.parse_args()

    if not args.abc.exists():
        print(f"missing .abc: {args.abc}", file=sys.stderr)
        return 2
    if args.ope and not args.ope.exists():
        print(f"missing .ope: {args.ope}", file=sys.stderr)
        return 2

    report = build_report(args.abc, args.ope)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    if args.json:
        json.dump(report, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        print(summarize(report))
        if args.out:
            print(f"\n完整 JSON → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
