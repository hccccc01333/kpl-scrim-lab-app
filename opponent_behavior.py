"""对手打法习惯：把对手的历史阵容与真实比赛过程关联（需求 08）。

每个指标都来自营地/回放的真实字段；缺少过程证据的对手不编造行为画像。
这是体系 × 行为的观察口径：相关条件并排呈现，不写成因果结论。
前 4 分钟交战率、中野辅联动、换塔/资源置换需要回放击杀与位置事件的
跨局聚合，当前管线只透传队伍经济检查点——这些维度如实标注未实现。
"""
from __future__ import annotations

from collections import Counter, defaultdict


def _pct(wins, n):
    return round(wins / n * 100, 1) if n else None


def opponent_behavior(rows, process_map):
    """rows: bp_board 的 games[]（对手、终局名单、结果已知）。
    process_map: bp_process.link_scrim_process 输出（键 = 局 id）。
    返回 {"teams": [...], "limitations": [...]}；按对手聚合。"""
    grouped = defaultdict(list)
    for row in rows or []:
        opponent = str(row.get("opponent") or "").strip()
        if not opponent or opponent == "未归属对手":
            continue
        grouped[opponent].append(row)
    output = []
    for opponent, games in sorted(grouped.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        decided = [g for g in games if g.get("result") in ("win", "loss")]
        wins = sum(g["result"] == "win" for g in decided)
        sides = Counter(str(g.get("side") or "") for g in games)
        picks = Counter(str(entry.get("name") or "") for g in games
                        for entry in (g.get("picks") or {}).get("enemy", [])
                        if entry.get("name"))
        # 对手视角检查点：bp_process 的 diff 是本队视角，取反即对手视角
        linked = [(g, (process_map or {}).get(str(g.get("key")))) for g in games]
        checkpoints = {}
        for stamp in ("240", "600"):
            diffs, conversions = [], []
            for g, process in linked:
                diff = ((process or {}).get("teamDiffOwn") or {}).get(stamp)
                if not isinstance(diff, (int, float)):
                    continue
                theirs = -diff
                diffs.append(theirs)
                if g.get("result") in ("win", "loss"):
                    conversions.append((theirs > 0) == (g["result"] == "loss"))
            checkpoints[stamp] = {
                "games": len(diffs),
                "meanDiff": round(sum(diffs) / len(diffs), 1) if diffs else None,
                "leadRate": _pct(sum(1 for d in diffs if d > 0), len(diffs)) if diffs else None,
                "leadConversion": _pct(sum(1 for c in conversions if c), len(conversions))
                                  if conversions else None,
            }
        output.append({
            "opponent": opponent, "games": len(games),
            "winRate": _pct(wins, len(decided)), "decided": len(decided),
            "blueGames": sides.get("blue", 0), "redGames": sides.get("red", 0),
            "topPicks": [{"hero": hero, "games": count}
                         for hero, count in picks.most_common(6)],
            "checkpoints": checkpoints,
            "linkedGames": sum(1 for _g, p in linked if p),
            "evidence": [{"id": g.get("key"), "day": g.get("day"),
                          "result": g.get("result"), "side": g.get("side")}
                         for g in sorted(games, key=lambda x: str(x.get("day") or ""))[-6:]],
        })
    return {"teams": output,
            "limitations": [
                "经济检查点来自回放/面板时间轴；无过程证据的对手不生成经济行为画像。",
                "前 4 分钟交战率、中野辅联动、换塔/资源置换需要回放击杀与位置事件跨局聚合，当前未实现。",
                "蓝红方偏好只说明选择习惯；体系标签（经济占比口径）见 BP 情报的体系分布。",
                "相关条件并排呈现，不构成克制或因果结论。",
            ]}
