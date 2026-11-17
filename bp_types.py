"""BP 类型博弈层：把“谁 Ban / 谁 Pick”落到英雄类型、手序、赛制与核数上。

教练要看的不是“Ban 了鲁班大师”，而是：

- 这个队第一手 Ban 的是战边还是坦边？打野位先 Ban 刺野还是坦野？
- 他先选对抗路时，优先出战边还是坦边？我们呢？
- 打某个组合（例如大乔体系）时，对面第一手出什么类型？我们先出什么类型？
- 这套阵容是四核、三核还是单核？核多核少胜率差多少？
- 放到 BO3 / BO5 / BO7 和不同时间窗里，上面的规律变不变？

类型口径直接复用 `hero_archetypes`（五路 12 类），不另造标签；分路缺失或
未收录归“待分类”，不猜。核数口径：战边 / 刺野 / 战野 / 法核 / 游射 / 呆射
算核，坦边 / 坦野 / 工具人 / 辅助不算；战野单独标“可转肉”，页面会注明。
"""
from __future__ import annotations

from collections import Counter, defaultdict

from bp_lab import _heroes, _lane_map, _pct, _win_rate, _wilson

LANES = ("对抗路", "打野", "中路", "发育路", "游走")
GROUPS = {
    "对抗路": ["战边", "坦边"],
    "打野": ["刺野", "战野", "坦野"],
    "中路": ["工具人", "法核"],
    "发育路": ["游射", "呆射"],
    "游走": ["开团辅", "保护辅", "功能辅"],
}
ALL_TYPES = [item for lane in LANES for item in GROUPS[lane]]
CORE_TYPES = {"战边", "刺野", "战野", "法核", "游射", "呆射"}
FLEX_TYPES = {"战野"}  # 可能转肉，页面标注
TYPE_LANE = {item: lane for lane in LANES for item in GROUPS[lane]}


def type_of(hero, lane=""):
    try:
        from hero_archetypes import archetype_of, default_lane
        return archetype_of(hero, lane or default_lane(hero))
    except Exception:  # pragma: no cover - 缺模块时退回待分类
        return "待分类"


def _type_lane(hero_type):
    return TYPE_LANE.get(hero_type, "")


def infer_bo(games, hint=None):
    """给每局标一个 BO：KPL 按 matchId 的最大局数；训练赛优先用训练课里登记的赛制。

    `hint` = {date: 3|5|7}，来自排期表的 format 字段（教练登记 BO3/BO5/BO7）。
    训练赛没有赛制时再退回“同日同对手局数”，无法判断记 0（不进 BO 筛选）。
    返回 {game_id: 3|5|7|0}，不改原字典。
    """
    kpl_groups = defaultdict(set)
    scrim_groups = defaultdict(int)
    for game in games or []:
        if game.get("source") == "kpl":
            key = str(game.get("matchId") or "")
            if key:
                try:
                    kpl_groups[key].add(int(game.get("gameSeq") or 0))
                except (TypeError, ValueError):
                    pass
        else:
            day = str(game.get("date") or "")[:10]
            if hint and hint.get(day):
                continue
            key = f"{game.get('date')}|{game.get('enemy')}"
            scrim_groups[key] += 1
    bo_by_match = {}
    for key, seqs in kpl_groups.items():
        size = max(seqs) if seqs else 0
        bo_by_match[key] = 3 if size <= 3 else 5 if size <= 5 else 7 if size <= 7 else 0
    out = {}
    for game in games or []:
        if game.get("source") == "kpl":
            out[game.get("id")] = bo_by_match.get(str(game.get("matchId") or ""), 0)
        else:
            day = str(game.get("date") or "")[:10]
            if hint and hint.get(game.get("id")):
                out[game.get("id")] = hint[game.get("id")]
                continue
            if hint and hint.get(day):
                out[game.get("id")] = hint[day]
                continue
            # 没登记赛制就不猜：训练赛一天打十几局，按局数推 BO 会全是“BO7”。
            out[game.get("id")] = 0
    return out


def _filter_bo(games, bo_map, bo):
    if not bo:
        return list(games or [])
    return [game for game in games or [] if bo_map.get(game.get("id")) == bo]


def _type_samples(games):
    """每局每方的类型集合：picks / bans 都转成类型，带手序。"""
    rows = []
    for game in games or []:
        lane_of = _lane_map(game.get("players"))
        enemy_lane = _lane_map(game.get("enemyPlayers"))
        own = [type_of(hero, lane_of.get(hero, "")) for hero in _heroes(game.get("picks"))]
        bans = [type_of(hero, lane_of.get(hero, "")) for hero in _heroes(game.get("bans"))]
        enemy = [type_of(hero, enemy_lane.get(hero, ""))
                 for hero in _heroes(game.get("enemyPicks"))]
        enemy_bans = [type_of(hero, enemy_lane.get(hero, ""))
                      for hero in _heroes(game.get("enemyBans"))]
        rows.append({"game": game, "own": own, "bans": bans, "enemy": enemy,
                     "enemy_bans": enemy_bans})
    return rows


def _count_rows(counter, total, limit=None):
    rows = []
    for key, count in counter.most_common(limit):
        rows.append({"key": key, "count": count, "share": _pct(count, total)})
    return rows


def ban_profile(games, *, bo=0, hand=0):
    """Ban 的类型 × 手序分布。分母 = 有该手 Ban 的局数。"""
    samples = _type_samples(games)
    hands = [Counter() for _ in range(4)]
    hand_games = [0] * 4
    rounds = {1: Counter(), 2: Counter()}
    first = Counter()
    timeline = defaultdict(Counter)
    for item in samples:
        bans = item["bans"]
        for index, hero_type in enumerate(bans[:4]):
            if hand and index != hand - 1:
                continue
            hands[index][hero_type] += 1
            hand_games[index] += 1
            rounds[1 if index < 2 else 2][hero_type] += 1
        if bans:
            first[bans[hand - 1] if hand and len(bans) >= hand else bans[0]] += 1
        month = str(item["game"].get("date") or "")[:7]
        if month and bans:
            timeline[month][bans[0]] += 1
    rows = []
    for index in range(4):
        total = hand_games[index] or 1
        rows.append({
            "hand": index + 1,
            "round": 1 if index < 2 else 2,
            "games": hand_games[index],
            "types": [{"type": key, "lane": _type_lane(key), "count": count,
                       "share": _pct(count, total)}
                      for key, count in hands[index].most_common()],
        })
    first_total = sum(first.values()) or 1
    return {
        "games": len(samples),
        "handRows": rows,
        "firstTypes": [{"type": key, "lane": _type_lane(key), "count": count,
                        "share": _pct(count, first_total)}
                       for key, count in first.most_common()],
        "rounds": [
            {"round": 1, "games": sum(hand_games[:2]),
             "types": [{"type": key, "lane": _type_lane(key), "count": count,
                        "share": _pct(count, sum(rounds[1].values()) or 1)}
                       for key, count in rounds[1].most_common()]},
            {"round": 2, "games": sum(hand_games[2:]),
             "types": [{"type": key, "lane": _type_lane(key), "count": count,
                        "share": _pct(count, sum(rounds[2].values()) or 1)}
                       for key, count in rounds[2].most_common()]},
        ],
        "timeline": [{"month": month,
                      "types": [{"type": key, "count": count,
                                 "share": _pct(count, sum(counter.values()) or 1)}
                                for key, count in counter.most_common(4)]}
                     for month, counter in sorted(timeline.items())[-8:]],
    }


def pick_profile(games, *, bo=0, slot=0):
    """Pick 位次 × 类型：第 1–5 手各先出什么类型。"""
    samples = _type_samples(games)
    slots = [Counter() for _ in range(5)]
    slot_games = [0] * 5
    order_types = []
    first_by_month = defaultdict(Counter)
    for item in samples:
        picks = item["own"]
        for index, hero_type in enumerate(picks[:5]):
            if slot and index != slot - 1:
                continue
            slots[index][hero_type] += 1
            slot_games[index] += 1
        month = str(item["game"].get("date") or "")[:7]
        if picks and month:
            first_by_month[month][picks[0]] += 1
    rows = []
    for index in range(5):
        total = slot_games[index] or 1
        rows.append({
            "slot": index + 1,
            "games": slot_games[index],
            "types": [{"type": key, "lane": _type_lane(key), "count": count,
                       "share": _pct(count, total)}
                      for key, count in slots[index].most_common(5)],
        })
    return {
        "games": len(samples),
        "slotRows": rows,
        "firstByMonth": [{"month": month,
                          "types": [{"type": key, "count": count,
                                     "share": _pct(count, sum(counter.values()) or 1)}
                                    for key, count in counter.most_common(4)]}
                         for month, counter in sorted(first_by_month.items())[-8:]],
    }


def core_profile(games):
    """阵容核数：每局算己方核数，给出核数分布与胜率。"""
    samples = _type_samples(games)
    buckets = defaultdict(list)
    rows = []
    for item in samples:
        types = item["own"]
        cores = [hero_type for hero_type in types if hero_type in CORE_TYPES]
        flex = sum(1 for hero_type in types if hero_type in FLEX_TYPES)
        key = len(cores)
        buckets[key].append(item["game"])
        rows.append({"cores": key, "flex": flex})
    out = []
    for count in sorted(buckets):
        records = buckets[count]
        wins, decided, win_rate, interval = _win_rate(records)
        out.append({"cores": count, "games": len(records),
                    "wins": wins, "decided": decided,
                    "winRate": win_rate, "interval": interval,
                    "share": _pct(len(records), len(samples)),
                    "flexGames": sum(1 for row in rows
                                     if row["cores"] == count and row["flex"])})
    return {"games": len(samples), "rows": out,
            "avgCores": round(sum(row["cores"] for row in rows) / len(rows), 2) if rows else None}


def conditional_profile(games, targets, *, limit=6):
    """目标被对面拿到时，己方第一手出什么类型（反过来也看对面）。"""
    wanted = set(_heroes(targets))
    if not wanted:
        return {"available": False, "rows": []}
    facing = []
    for game in games or []:
        if wanted <= set(_heroes(game.get("enemyPicks"))):
            facing.append(game)
    own_first = Counter()
    own_slots = [Counter() for _ in range(3)]
    enemy_first = Counter()
    for game in facing:
        own_types = _type_samples([game])[0]["own"]
        enemy_types = _type_samples([game])[0]["enemy"]
        if own_types:
            own_first[own_types[0]] += 1
            for index, hero_type in enumerate(own_types[:3]):
                own_slots[index][hero_type] += 1
        if enemy_types:
            enemy_first[enemy_types[0]] += 1
    total = len(facing) or 1
    return {
        "available": bool(facing),
        "targets": sorted(wanted),
        "games": len(facing),
        "ownFirstTypes": [{"type": key, "count": count, "share": _pct(count, total)}
                          for key, count in own_first.most_common(limit)],
        "ownSlotTypes": [{"slot": index + 1,
                          "types": [{"type": key, "count": count,
                                     "share": _pct(count, sum(counter.values()) or 1)}
                                    for key, count in counter.most_common(4)]}
                         for index, counter in enumerate(own_slots)],
        "enemyFirstTypes": [{"type": key, "count": count, "share": _pct(count, total)}
                            for key, count in enemy_first.most_common(limit)],
    }


def type_counter_matrix(games, *, min_games=3):
    """类型克制矩阵：对面出现类型 E 时，我们出类型 R 的局数与胜率。

    只统计“同一局双方阵容都存在”的共现；胜率是己方视角。样本小于 min_games
    的格子留空，避免 1 局 100% 被当成克制。
    """
    samples = _type_samples(games)
    enemy_count = Counter()
    own_count = Counter()
    cells = defaultdict(lambda: [0, 0, 0])  # games, wins, decided
    for item in samples:
        enemy = {t for t in item["enemy"] if t and t != "待分类"}
        own = {t for t in item["own"] if t and t != "待分类"}
        result = item["game"].get("result")
        for et in enemy:
            enemy_count[et] += 1
        for ot in own:
            own_count[ot] += 1
        for et in enemy:
            for ot in own:
                cell = cells[(et, ot)]
                cell[0] += 1
                if result is not None:
                    cell[2] += 1
                    if result is True:
                        cell[1] += 1
    rows = [t for t in ALL_TYPES if enemy_count[t] >= 5]
    cols = [t for t in ALL_TYPES if own_count[t] >= 5]
    if not rows:
        rows = [et for et, _ in enemy_count.most_common(8)]
    if not cols:
        cols = [ot for ot, _ in own_count.most_common(8)]
    matrix = []
    for et in rows:
        line = []
        for ot in cols:
            games_n, wins, decided = cells.get((et, ot), [0, 0, 0])
            line.append({
                "games": games_n,
                "decided": decided,
                "winRate": _pct(wins, decided) if decided else None,
            })
        matrix.append(line)
    # 每个敌方类型下，胜率最高且样本够的应对
    best = []
    for ri, et in enumerate(rows):
        candidates = [(cols[ci], matrix[ri][ci]) for ci in range(len(cols))]
        candidates = [(name, cell) for name, cell in candidates
                      if (cell["decided"] or 0) >= min_games and cell["winRate"] is not None]
        if not candidates:
            continue
        name, cell = max(candidates, key=lambda pair: pair[1]["winRate"])
        base = [cell for _, cell in candidates]
        overall = (sum(c["winRate"] * c["decided"] for c in base)
                   / max(1, sum(c["decided"] for c in base)))
        best.append({"enemy": et, "response": name, "games": cell["games"],
                     "decided": cell["decided"], "winRate": cell["winRate"],
                     "baseline": round(overall, 1),
                     "delta": round(cell["winRate"] - overall, 1)})
    return {"available": bool(rows and cols), "rows": rows, "cols": cols,
            "matrix": matrix, "best": best,
            "games": len(samples),
            "caveats": ["格子 = 同一局共现；胜率是己方视角，样本 <5 局不排最佳应对。",
                        "类型克制是历史关联，不是因果结论。"]}


def type_ban_counter_matrix(games, *, hand=0, min_games=3):
    """对面 Ban 的类型 × 我们出的类型：对面在这个 Ban 位按掉什么，我们怎么接、胜率多少。"""
    samples = _type_samples(games)
    row_count = Counter()
    col_count = Counter()
    cells = defaultdict(lambda: [0, 0, 0])
    for item in samples:
        banned = item.get("enemy_bans") or []
        if hand:
            banned = [banned[hand - 1]] if len(banned) >= hand else []
        banned = {t for t in banned if t and t != "待分类"}
        own = {t for t in item["own"] if t and t != "待分类"}
        result = item["game"].get("result")
        for bt in banned:
            row_count[bt] += 1
            for ot in own:
                col_count[ot] += 1
                cell = cells[(bt, ot)]
                cell[0] += 1
                if result is not None:
                    cell[2] += 1
                    if result is True:
                        cell[1] += 1
    rows = [t for t in ALL_TYPES if row_count[t] >= 3]
    cols = [t for t in ALL_TYPES if col_count[t] >= 5]
    if not rows:
        rows = [t for t, _ in row_count.most_common(8)]
    if not cols:
        cols = [t for t, _ in col_count.most_common(8)]
    matrix = []
    for bt in rows:
        line = []
        for ot in cols:
            games_n, wins, decided = cells.get((bt, ot), [0, 0, 0])
            line.append({"games": games_n, "decided": decided,
                         "winRate": _pct(wins, decided) if decided else None})
        matrix.append(line)
    best = []
    for ri, bt in enumerate(rows):
        candidates = [(cols[ci], matrix[ri][ci]) for ci in range(len(cols))]
        candidates = [(name, cell) for name, cell in candidates
                      if (cell["decided"] or 0) >= min_games and cell["winRate"] is not None]
        if not candidates:
            continue
        name, cell = max(candidates, key=lambda pair: pair[1]["winRate"])
        base = [c for _, c in candidates]
        overall = (sum(c["winRate"] * c["decided"] for c in base)
                   / max(1, sum(c["decided"] for c in base)))
        best.append({"enemy": bt, "response": name, "games": cell["games"],
                     "decided": cell["decided"], "winRate": cell["winRate"],
                     "baseline": round(overall, 1),
                     "delta": round(cell["winRate"] - overall, 1)})
    return {"available": bool(rows and cols), "rows": rows, "cols": cols,
            "matrix": matrix, "best": best, "hand": hand, "games": len(samples),
            "caveats": ["行为 = 对面 Ban 的类型，列为 = 我们出的类型；样本 <5 局不排最佳应对。"]}


def build_types(games, *, team="", opponent="", bo=0, targets=None, bo_hint=None,
                hand=0, core=0, timeline_games=None):
    """页面用的类型块：对手 / 自己 / 条件反应 / 核数。"""
    bo_map = infer_bo(games, hint=bo_hint)
    scoped = _filter_bo(games, bo_map, bo) if bo else list(games or [])
    if core:
        # 只保留该方阵容为 N 核的局（视角行；KPL 两边都会出现，各算各的）。
        scoped = [game for game in scoped
                  if len([t for t in _type_samples([game])[0]["own"] if t in CORE_TYPES]) == core]
    own_rows = [game for game in scoped if not team or str(game.get("team")) == team]
    if opponent == "__all__":
        opp_rows = [game for game in scoped if str(game.get("team")) != team]
    else:
        opp_rows = [game for game in scoped if opponent and str(game.get("team")) == opponent]
    bo_counts = Counter(bo_map.get(game.get("id"), 0) for game in games or [])
    # 时间轴用整段历史（不受窗口影响），否则 30 天窗口只有 2 个月，看不出趋势。
    source = list(timeline_games) if timeline_games is not None else list(scoped)
    def _timeline(rows):
        return ban_profile(rows, hand=hand).get("timeline") or []
    if opponent == "__all__":
        opp_timeline_rows = [g for g in source if str(g.get("team")) != team]
    elif opponent:
        opp_timeline_rows = [g for g in source if str(g.get("team")) == opponent]
    else:
        opp_timeline_rows = []
    timelines = {
        "opponent": _timeline(opp_timeline_rows) if opp_timeline_rows else [],
        "own": _timeline([g for g in source if not team or str(g.get("team")) == team]) if team else [],
        "league": _timeline(source),
    }
    payload = {
        "schema": "bp-types-v1",
        "timelines": timelines,
        "bo": {"filter": bo,
               "available": [size for size in (3, 5, 7) if bo_counts.get(size)],
               "counts": {str(size): count for size, count in sorted(bo_counts.items()) if size}},
        "taxonomy": {"lanes": list(LANES), "groups": GROUPS,
                     "coreTypes": sorted(CORE_TYPES), "flexTypes": sorted(FLEX_TYPES)},
        "games": len(scoped),
        "team": team, "opponent": opponent,
        "opponentProfile": ({"games": len(opp_rows),
                             "ban": ban_profile(opp_rows, hand=hand), "banFull": ban_profile(opp_rows),
                             "pick": pick_profile(opp_rows),
                             "cores": core_profile(opp_rows)}
                            if opp_rows else None),
        "ownProfile": ({"games": len(own_rows),
                        "ban": ban_profile(own_rows, hand=hand), "banFull": ban_profile(own_rows),
                        "pick": pick_profile(own_rows),
                        "cores": core_profile(own_rows)}
                       if own_rows else None),
        "leagueProfile": {"games": len(scoped),
                          "ban": ban_profile(scoped, hand=hand), "banFull": ban_profile(scoped),
                          "pick": pick_profile(scoped),
                          "cores": core_profile(scoped)},
        "conditional": (conditional_profile(scoped, targets) if targets else None),
        "counters": type_counter_matrix(scoped if not team else
                                        [g for g in scoped if str(g.get("team")) == team]),
        "banCounters": type_ban_counter_matrix(
            scoped if not team else [g for g in scoped if str(g.get("team")) == team],
            hand=hand),
        "filters": {"bo": bo, "hand": hand, "core": core},
    }
    return payload
