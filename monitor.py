"""周期异常监控（需求 09）：按自然周/月/日窗口监控英雄、组合、选手、体系的突变。

每条异常都带：对象、窗口、变化幅度、有效场次、对应比赛证据、可疑因素线索。
只报告统计突变并提示「需要人工核对」；绝不把相关现象写成确定原因。
Ban 位/出装等尚未采集的维度如实标注未实现。
"""
from __future__ import annotations

from collections import Counter, defaultdict
from itertools import combinations

from analysis_period import bucket_rows

UNITS = ("day", "week", "month")
SHARE_DELTA = 10.0
MIN_GAMES = 3


def _pct(w, n):
    return round(w / n * 100, 1) if n else None


def _window_stats(games):
    """单个窗口内：英雄出场/胜率、双人组合、选手英雄、体系标签的原始统计。"""
    picks = Counter()
    wins = Counter()
    decided = Counter()
    pairs = Counter()
    player_heroes = defaultdict(set)
    systems = Counter()
    for g in games:
        own = [str(e.get("name") or "") for e in (g.get("picks") or {}).get("own", [])
               if e.get("name")]
        enemy = [str(e.get("name") or "") for e in (g.get("picks") or {}).get("enemy", [])
                 if e.get("name")]
        result = g.get("result")
        for hero in own:
            picks[hero] += 1
            if result in ("win", "loss"):
                decided[("own", hero)] += 1
                if result == "win":
                    wins[("own", hero)] += 1
        for hero in enemy:
            picks[hero] += 1
            if result in ("win", "loss"):
                decided[("enemy", hero)] += 1
                if result == "loss":
                    wins[("enemy", hero)] += 1  # 对手视角：本队负 = 对手胜
        for heroes in combinations(sorted(own + enemy), 2):
            pairs[heroes] += 1
        for side_roster in (g.get("roster") or {}).values():
            for entry in side_roster:
                if entry.get("name") and entry.get("hero"):
                    player_heroes[str(entry["name"])].add(str(entry["hero"]))
        gold_players = [p for side_roster in (g.get("roster") or {}).values()
                        for p in side_roster
                        if isinstance(p.get("gold"), (int, float)) and p["gold"] > 0]
        if len(gold_players) == 5:
            total = sum(p["gold"] for p in gold_players)
            top = max(gold_players, key=lambda p: p["gold"])
            lane_names = {"打野": "野核", "发育路": "射核", "中路": "中核"}
            systems.append(lane_names.get(str(top.get("lane") or ""), "其他单核")
                           if top["gold"] / total * 100 >= 28 else "多核/均衡")
    return {"games": len(games), "picks": picks, "wins": wins, "decided": decided,
            "pairs": pairs, "playerHeroes": player_heroes, "systems": systems}


def monitor(rows, *, unit="week", date_from=None, date_to=None):
    """rows: bp_board games[]。unit: day/week/month。返回异常清单。"""
    if unit not in UNITS:
        raise ValueError("监控窗口必须是 day / week / month")
    undated = 0
    dated = []
    for row in rows or []:
        day = str(row.get("day") or "").strip()
        if not day:
            undated += 1
            continue
        if date_from and day < date_from:
            continue
        if date_to and day > date_to:
            continue
        dated.append(row)
    windows = bucket_rows(dated, "day", unit)
    windows = [w for w in windows if w["key"] != "undated"]
    stats = [(w, _window_stats(w["rows"])) for w in windows]
    anomalies = []
    for index in range(1, len(stats)):
        prev_window, prev = stats[index - 1]
        cur_window, cur = stats[index]
        if not prev["games"] or not cur["games"]:
            continue
        # 1. 英雄使用率 / 胜率突变（出场与胜率分开报，不合并成一个分数）
        for hero in set(prev["picks"]) | set(cur["picks"]):
            before, after = prev["picks"].get(hero, 0), cur["picks"].get(hero, 0)
            if before + after < MIN_GAMES:
                continue
            p_share, q_share = before / prev["games"] * 100, after / cur["games"] * 100
            if abs(q_share - p_share) >= SHARE_DELTA:
                anomalies.append({
                    "kind": "usage", "object": hero,
                    "window": f"{prev_window['key']} → {cur_window['key']}",
                    "previous": f"{before} 局（{p_share:.1f}%）",
                    "current": f"{after} 局（{q_share:.1f}%）",
                    "changePP": round(q_share - p_share, 1),
                    "games": after,
                    "note": "使用率突变需先核对赛程与版本，再查阵容搭配变化。",
                    "evidence": [str(g.get("key")) for g in cur_window["rows"]][:6]})
        for side in ("own", "enemy"):
            heroes = {h for (_, h) in cur["decided"] if _ == side} | \
                     {h for (_, h) in prev["decided"] if _ == side}
            for hero in heroes:
                key = (side, hero)
                before_d, after_d = prev["decided"].get(key, 0), cur["decided"].get(key, 0)
                if before_d < 2 or after_d < 2:
                    continue
                p_rate = prev["wins"].get(key, 0) / before_d * 100
                q_rate = cur["wins"].get(key, 0) / after_d * 100
                if abs(q_rate - p_rate) >= 15:
                    anomalies.append({
                        "kind": "winrate", "object": f"{hero}（{side}）",
                        "window": f"{prev_window['key']} → {cur_window['key']}",
                        "previous": f"{prev['wins'].get(key, 0)}/{before_d} 胜（{p_rate:.1f}%）",
                        "current": f"{cur['wins'].get(key, 0)}/{after_d} 胜（{q_rate:.1f}%）",
                        "changePP": round(q_rate - p_rate, 1), "games": after_d,
                        "note": "胜率突变需按 04 号流程核对阵容、对位、选手与过程变化。",
                        "evidence": [str(g.get("key")) for g in cur_window["rows"]][:6]})
        # 2. 常用组合被替换：上一窗口 ≥2 局、本窗口 0 局
        for pair, count in prev["pairs"].items():
            if count >= 2 and cur["pairs"].get(pair, 0) == 0:
                anomalies.append({
                    "kind": "pair-replaced", "object": " + ".join(pair),
                    "window": f"{prev_window['key']} → {cur_window['key']}",
                    "previous": f"{count} 局", "current": "0 局",
                    "changePP": None, "games": 0,
                    "note": "组合消失可能只是没排到对手，需核对赛程。",
                    "evidence": []})
        # 3. 选手英雄池变化：上一窗口出现过的英雄在本窗口不再出现
        for player in set(prev["playerHeroes"]) | set(cur["playerHeroes"]):
            dropped = prev["playerHeroes"].get(player, set()) - cur["playerHeroes"].get(player, set())
            added = cur["playerHeroes"].get(player, set()) - prev["playerHeroes"].get(player, set())
            if dropped or added:
                anomalies.append({
                    "kind": "player-pool", "object": player,
                    "window": f"{prev_window['key']} → {cur_window['key']}",
                    "previous": "用过的英雄：" + ("、".join(sorted(dropped)) or "无"),
                    "current": "新出现的英雄：" + ("、".join(sorted(added)) or "无"),
                    "changePP": None,
                    "games": len(cur_window["rows"]),
                    "note": "英雄池变化只描述事实；是否轮换需人工确认。",
                    "evidence": [str(g.get("key")) for g in cur_window["rows"]][:6]})
        # 4. 体系尝试：本窗口出现、上一窗口没出现过的体系标签
        for system, count in cur["systems"].items():
            if count >= 2 and prev["systems"].get(system, 0) == 0:
                anomalies.append({
                    "kind": "system", "object": system,
                    "window": f"{prev_window['key']} → {cur_window['key']}",
                    "previous": "0 局", "current": f"{count} 局",
                    "changePP": None, "games": count,
                    "note": "体系标签按经济占比判定，是结构观察；是否刻意尝试需教练确认。",
                    "evidence": [str(g.get("key")) for g in cur_window["rows"]][:6]})
    return {"unit": unit, "windows": len(windows),
            "games": sum(s["games"] for _w, s in stats), "undated": undated,
            "anomalies": anomalies[:40],
            "limitations": [
                "监控只报告统计突变：需要人工核对赛程、版本与阵容后再找原因。",
                "对手固定 Ban 位变化需要逐手 draftEvents（当前未录入）；出装顺序变化需要装备事件覆盖。",
                "英雄胜率突变按本队/对手视角分开计算，不混池。",
                "窗口数量不足 2 个时无法对照；数据时间跨度越长，周/月对照越有意义。",
            ]}
