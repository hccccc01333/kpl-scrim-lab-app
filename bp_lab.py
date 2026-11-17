"""BP 概览十区：英雄、组合、对抗、对手习惯、演变、稳定性与赛前方案。

本模块只做纯计算：输入 bp_intelligence 归一化后的“队-局”行，输出教练可读的
结构化结果。所有胜率按来源分开（KPL / 训练赛），不混池；样本不足时返回
None/空态，不推断缺失的 BP 手序、版本或因果。
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from itertools import combinations
from math import sqrt

LANES = ("对抗路", "打野", "中路", "发育路", "游走")
ORDER_UNITS = ("day", "month", "season", "stage")
DEFAULT_MIN_ORDER = 3


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def _pct(num, den):
    return round(num * 100 / den, 1) if den else None


def _wilson(wins, total):
    """Wilson 95% 区间；空样本返回 [None, None]。"""
    if not total:
        return [None, None]
    p, z = wins / total, 1.96
    d = 1 + z * z / total
    center = (p + z * z / (2 * total)) / d
    radius = z * sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / d
    return [round(100 * max(0, center - radius), 1),
            round(100 * min(1, center + radius), 1)]


def _heroes(items):
    out = []
    seen = set()
    for item in items or []:
        hero = str((item or {}).get("name") if isinstance(item, dict) else item or "").strip()
        if hero and hero not in seen:
            seen.add(hero)
            out.append(hero)
    return out


def _lane_map(players):
    """英雄 → 实际分路；同一英雄多路时保留第一次出现的分路。"""
    out = {}
    for player in players or []:
        hero = str((player or {}).get("hero") or "").strip()
        lane = str((player or {}).get("lane") or "").strip()
        if hero and lane and hero not in out:
            out[hero] = lane
    return out


def _signature(picks, players):
    """五路类型签名；分路缺失时返回 None，不猜。"""
    try:
        from hero_archetypes import archetype_of
        from lineup_stats import signature_of
    except Exception:  # pragma: no cover - 运行环境缺模块时退回空态
        return None
    lane_of = _lane_map(players)
    entries = [{"name": hero,
                "lane": lane_of.get(hero),
                "archetype": archetype_of(hero, lane_of.get(hero))}
               for hero in picks]
    return signature_of(entries)


def _signature_label(sig):
    return " / ".join(sig) if sig else "分路未知"


def _win_rate(records):
    decided = [g for g in records if g.get("result") is not None]
    wins = sum(1 for g in decided if g["result"] is True)
    return wins, len(decided), _pct(wins, len(decided)), _wilson(wins, len(decided))


def _sample_label(games, decided):
    if games >= 30 and decided >= 20:
        return "样本充足"
    if games >= 8:
        return "小样本"
    return "样本不足"


def _evidence(records, max_items=8):
    seen, rows = set(), []
    for g in sorted(records, key=lambda x: (str(x.get("date") or ""), str(x.get("id") or "")), reverse=True):
        key = (g.get("id"), g.get("team"))
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "id": g.get("id"), "date": g.get("date"), "team": g.get("team"),
            "enemy": g.get("enemy"), "result": g.get("result"),
            "source": g.get("source"), "matchId": g.get("matchId"),
            "ownPicks": list(g.get("picks") or []),
            "enemyPicks": list(g.get("enemyPicks") or []),
        })
        if len(rows) >= max_items:
            break
    return rows


def _combo_label(heroes):
    return " + ".join(heroes)


def _combo_key(heroes):
    return tuple(sorted(str(h) for h in heroes if h))


def _window_key(game, unit):
    day = str(game.get("date") or "")
    if unit == "day":
        return day or "日期未记录"
    if unit == "month":
        return day[:7] if len(day) >= 7 else "日期未记录"
    if unit == "season":
        return str(game.get("league") or "未记录赛季")
    if unit == "stage":
        league = str(game.get("league") or "").strip()
        stage = str(game.get("stage") or "").strip()
        return f"{league} · {stage}" if league and stage else (league or stage or "未记录阶段")
    raise ValueError(f"未知时间粒度：{unit}")


def _top(counter, n, limit=5):
    return [{"hero": hero, "count": count, "share": _pct(count, n)}
            for hero, count in counter.most_common(limit)]


# ---------------------------------------------------------------------------
# 01 英雄优先级
# ---------------------------------------------------------------------------

def hero_board(games):
    """英雄 Pick/Ban 率、胜率、分路表现；分母为队-局。"""
    games = list(games or [])
    total = len(games)
    lane_maps = {id(g): _lane_map(g.get("players")) for g in games}
    picks, bans, lanes = defaultdict(list), defaultdict(list), defaultdict(Counter)
    for g in games:
        for hero in g.get("picks") or []:
            picks[hero].append(g)
            lane = lane_maps[id(g)].get(hero)
            if lane:
                lanes[hero][lane] += 1
        for hero in g.get("bans") or []:
            bans[hero].append(g)

    rows = []
    for hero in sorted(set(picks) | set(bans)):
        pick_rows = picks.get(hero, [])
        ban_rows = bans.get(hero, [])
        wins, decided, win_rate, interval = _win_rate(pick_rows)
        pick_rate = _pct(len(pick_rows), total)
        ban_rate = _pct(len(ban_rows), total)
        lane_rows = []
        for lane, count in lanes.get(hero, Counter()).most_common():
            lane_records = [g for g in pick_rows if lane_maps[id(g)].get(hero) == lane]
            lane_wins, lane_decided, lane_rate, lane_interval = _win_rate(lane_records)
            lane_rows.append({"lane": lane, "picks": len(lane_records),
                              "wins": lane_wins, "decided": lane_decided,
                              "winRate": lane_rate, "interval": lane_interval})
        primary_lane = lane_rows[0]["lane"] if lane_rows else ""
        if decided < 10 or len(pick_rows) < 5:
            signal = "样本不足"
        elif (ban_rate or 0) >= 10 and (win_rate or 0) >= 52:
            signal = "高 Ban · 高胜率"
        elif (pick_rate or 0) >= 3 and (win_rate or 0) >= 55:
            signal = "高 Pick · 高胜率"
        elif (pick_rate or 0) >= 3:
            signal = "高 Pick"
        elif (ban_rate or 0) >= 8:
            signal = "高 Ban"
        else:
            signal = "常规"
        rows.append({
            "hero": hero, "lane": primary_lane, "laneRows": lane_rows,
            "picks": len(pick_rows), "pickRate": pick_rate,
            "bans": len(ban_rows), "banRate": ban_rate,
            "wins": wins, "decided": decided, "winRate": win_rate,
            "interval": interval, "teams": len({g.get("team") for g in pick_rows}),
            "sample": _sample_label(len(pick_rows), decided),
            "signal": signal,
            "priority": round((pick_rate or 0) + (ban_rate or 0) * 0.7, 1),
        })

    rows.sort(key=lambda r: (-(r["priority"] or 0), -(r["decided"] or 0), r["hero"]))
    by_lane = {}
    for lane in LANES:
        lane_rows = [r for r in rows if r["lane"] == lane]
        if lane_rows:
            by_lane[lane] = lane_rows
    lane_board = []
    for lane in LANES:
        for row in by_lane.get(lane, []):
            for detail in row["laneRows"]:
                if detail["lane"] == lane:
                    lane_board.append({
                        "lane": lane, "hero": row["hero"],
                        "picks": detail["picks"], "wins": detail["wins"],
                        "decided": detail["decided"], "winRate": detail["winRate"],
                        "interval": detail["interval"],
                        "pickRate": _pct(detail["picks"], total),
                        "share": _pct(detail["picks"], max(1, row["picks"])),
                    })
    lane_board.sort(key=lambda r: (LANES.index(r["lane"]), -(r["picks"] or 0), r["hero"]))
    return {
        "total": total, "rows": rows, "top": rows[:20],
        "byLane": by_lane, "laneBoard": lane_board,
        "lanes": [lane for lane in LANES if by_lane.get(lane)],
        "hasData": bool(rows),
    }


# ---------------------------------------------------------------------------
# 02 组合强度
# ---------------------------------------------------------------------------

def _combo_rows(games, size, recent_days=30):
    games = list(games or [])
    total = len(games)
    dates = sorted(str(g.get("date") or "") for g in games if g.get("date"))
    recent_cutoff = ""
    if dates:
        from datetime import date, timedelta
        try:
            end = date.fromisoformat(dates[-1])
            recent_cutoff = (end - timedelta(days=max(1, int(recent_days)))).isoformat()
        except ValueError:
            recent_cutoff = ""
    counts, decided_counts, win_counts = Counter(), Counter(), Counter()
    recent_counts, recent_decided, recent_wins = Counter(), Counter(), Counter()
    base = defaultdict(list)
    for g in games:
        heroes = _heroes(g.get("picks"))
        if len(heroes) != 5:
            continue
        recent = bool(recent_cutoff) and str(g.get("date") or "") >= recent_cutoff
        for hero in heroes:
            base[hero].append(g)
        for combo in combinations(sorted(heroes), size):
            counts[combo] += 1
            if recent:
                recent_counts[combo] += 1
            if g.get("result") is not None:
                decided_counts[combo] += 1
                if recent:
                    recent_decided[combo] += 1
                if g.get("result") is True:
                    win_counts[combo] += 1
                    if recent:
                        recent_wins[combo] += 1
    base_rate = {}
    for hero, records in base.items():
        wins, decided, _, _ = _win_rate(records)
        base_rate[hero] = (wins + 2) / (decided + 4) if decided else None

    rows = []
    for combo, count in counts.items():
        if count < 2:
            continue
        wins, decided = win_counts.get(combo, 0), decided_counts.get(combo, 0)
        win_rate = _pct(wins, decided)
        refs = [base_rate[hero] for hero in combo if base_rate.get(hero) is not None]
        expected = round(100 * sum(refs) / len(refs), 1) if refs else None
        relative = (round(win_rate - expected, 1)
                    if win_rate is not None and expected is not None and decided >= 3 else None)
        recent_games = recent_counts.get(combo, 0)
        recent_dec = recent_decided.get(combo, 0)
        recent_wr = _pct(recent_wins.get(combo, 0), recent_dec)
        change = (round(recent_wr - win_rate, 1)
                  if recent_wr is not None and win_rate is not None and recent_dec >= 2 else None)
        rows.append({
            "heroes": list(combo), "label": _combo_label(combo),
            "games": count, "share": _pct(count, total),
            "wins": wins, "decided": decided, "winRate": win_rate,
            "interval": _wilson(wins, decided), "reference": expected, "relative": relative,
            "recentGames": recent_games, "recentWinRate": recent_wr,
            "recentChange": change, "recentDays": recent_days,
            "teams": 0, "sample": _sample_label(count, decided),
        })
    rows.sort(key=lambda r: (-(r["games"] or 0), -(r["relative"] or -999), r["label"]))
    selected = rows[:30]
    signal_keys = {tuple(row["heroes"]) for row in sorted(
        [r for r in rows if r["relative"] is not None],
        key=lambda r: (-(r["relative"] or 0), -(r["games"] or 0)))[:12]}
    selected_keys = {tuple(row["heroes"]) for row in selected} | signal_keys
    evidence = defaultdict(list)
    for g in games:
        heroes = _heroes(g.get("picks"))
        if len(heroes) != 5:
            continue
        for combo in combinations(sorted(heroes), size):
            if combo in selected_keys:
                evidence[combo].append(g)
    for row in rows:
        key = tuple(row["heroes"])
        if key not in selected_keys:
            continue
        records = evidence.get(key, [])
        row["teams"] = len({g.get("team") for g in records})
        row["evidence"] = _evidence(records)
    top = [row for row in rows if tuple(row["heroes"]) in selected_keys][:30]
    return {
        "total": total, "rows": top, "top": top,
        "topBySignal": sorted([r for r in top if r["relative"] is not None],
                              key=lambda r: (-(r["relative"] or 0), -(r["games"] or 0)))[:12],
    }


def combo_board(games, recent_days=30):
    pairs = _combo_rows(games, 2, recent_days)
    trios = _combo_rows(games, 3, recent_days)
    spotlight = None
    for row in pairs["rows"]:
        if set(row["heroes"]) == {"鲁班大师", "鲁班七号"}:
            spotlight = row
            break
    return {
        "pairs": pairs["top"], "trios": trios["top"],
        "pairsBySignal": pairs["topBySignal"], "triosBySignal": trios["topBySignal"],
        "spotlight": spotlight,
        "minGames": 2,
    }


def combo_detail(games, heroes, *, team="", recent_days=30):
    """自选组合：精确包含全部所选英雄的同队同局记录。

    与 combo_board 的“热门组合榜”不同，这里不做 Top N 截断，允许任意 2–3 个
    英雄；样本不足时照常返回战绩，但 relative / 稳定性结论留空并标注。
    """
    wanted = _heroes(heroes)
    if not wanted:
        return {"available": False, "reason": "请至少选择一个英雄。",
                "heroes": [], "label": ""}
    rows = [g for g in games if not team or str(g.get("team") or "") == team]
    records = [g for g in rows
               if set(wanted) <= set(_heroes(g.get("picks")))]
    label = _combo_label(wanted)
    if not records:
        return {"available": False, "heroes": wanted, "label": label,
                "team": team, "totalGames": len(rows),
                "reason": "当前范围没有这组英雄同队同局的记录；换时间窗或取消本队筛选。"}

    wins, decided, win_rate, interval = _win_rate(records)
    base = defaultdict(list)
    for g in rows:
        for hero in _heroes(g.get("picks")):
            base[hero].append(g)
    refs = []
    for hero in wanted:
        b_wins, b_decided, _, _ = _win_rate(base.get(hero) or [])
        if b_decided:
            refs.append((b_wins + 2) / (b_decided + 4))
    expected = round(100 * sum(refs) / len(refs), 1) if refs else None
    relative = (round(win_rate - expected, 1)
                if win_rate is not None and expected is not None and decided >= 3
                else None)

    dates = sorted(str(g.get("date") or "")[:10] for g in rows if g.get("date"))
    end = dates[-1] if dates else ""
    recent = []
    for days in (7, 15, 30):
        current, previous = [], []
        if end:
            try:
                end_day = date.fromisoformat(end)
                start_day = end_day - timedelta(days=days - 1)
                prev_end = start_day - timedelta(days=1)
                prev_start = prev_end - timedelta(days=days - 1)
                current = [g for g in records
                           if start_day.isoformat() <= str(g.get("date") or "")[:10] <= end]
                previous = [g for g in records
                            if prev_start.isoformat() <= str(g.get("date") or "")[:10] <= prev_end.isoformat()]
            except ValueError:
                pass
        c_wins, c_decided, c_rate, c_interval = _win_rate(current)
        p_wins, p_decided, p_rate, _ = _win_rate(previous)
        recent.append({"days": days, "games": len(current), "wins": c_wins,
                       "decided": c_decided, "winRate": c_rate,
                       "interval": c_interval,
                       "previousGames": len(previous),
                       "previousWinRate": p_rate,
                       "delta": (round(c_rate - p_rate, 1)
                                 if c_rate is not None and p_rate is not None else None)})

    def bucket(key):
        out = defaultdict(list)
        for g in records:
            out[str(g.get(key) or "未记录")].append(g)
        return out

    sides = []
    for key, group in bucket("side").items():
        s_wins, s_decided, s_rate, s_interval = _win_rate(group)
        sides.append({"side": key, "games": len(group), "wins": s_wins,
                      "decided": s_decided, "winRate": s_rate,
                      "interval": s_interval})
    sides.sort(key=lambda row: row["side"])

    teammate_counts = Counter()
    for g in records:
        for hero in _heroes(g.get("picks")):
            if hero not in wanted:
                teammate_counts[hero] += 1
    teammates = []
    for hero, count in teammate_counts.most_common(8):
        group = [g for g in records if hero in _heroes(g.get("picks"))]
        t_wins, t_decided, t_rate, t_interval = _win_rate(group)
        teammates.append({"hero": hero, "games": count,
                          "share": _pct(count, len(records)),
                          "wins": t_wins, "decided": t_decided,
                          "winRate": t_rate, "interval": t_interval})

    opponents = []
    for enemy, group in bucket("enemy").items():
        o_wins, o_decided, o_rate, o_interval = _win_rate(group)
        opponents.append({"opponent": enemy, "games": len(group),
                          "wins": o_wins, "decided": o_decided,
                          "winRate": o_rate, "interval": o_interval})
    opponents.sort(key=lambda row: (-row["games"], row["opponent"]))

    return {
        "available": True, "mode": "combo" if len(wanted) > 1 else "hero",
        "heroes": wanted, "label": label, "team": team,
        "totalGames": len(rows), "games": len(records),
        "share": _pct(len(records), len(rows)),
        "wins": wins, "decided": decided, "winRate": win_rate,
        "interval": interval, "sample": _sample_label(len(records), decided),
        "teams": len({g.get("team") for g in records}),
        "reference": expected, "relative": relative,
        "recent": recent, "sides": sides,
        "teammates": teammates, "opponents": opponents[:8],
        "evidence": _evidence(records),
        "caveats": [
            "组合 = 同队同局同时出现，不是因果协同。",
            "相对基准 = 组合胜率 − 所选英雄各自胜率的收缩基准；不足 3 局有胜负不计算。",
            "样本不足时只看记录，不输出“强 / 稳”的结论。",
        ],
    }


# ---------------------------------------------------------------------------
# 03 指定英雄 / 组合 / 完整阵容的历史对抗
# ---------------------------------------------------------------------------

def lookup(games, heroes):
    wanted = _heroes(heroes)
    wanted_set = set(wanted)
    if not wanted:
        return {"available": False, "reason": "请至少输入一个英雄。", "heroes": []}
    rows = []
    seen_games = set()
    for g in games:
        game_key = (g.get("source"), g.get("id"))
        if game_key in seen_games:
            continue
        own = _heroes(g.get("picks"))
        enemy = _heroes(g.get("enemyPicks"))
        if len(wanted) == 5:
            if set(own) == wanted_set and len(own) == 5:
                target_side, target_picks, enemy_picks, result = "own", own, enemy, g.get("result")
                target_team, target_enemy = g.get("team"), g.get("enemy")
            elif set(enemy) == wanted_set and len(enemy) == 5:
                target_side, target_picks, enemy_picks, result = "enemy", enemy, own, (
                    None if g.get("result") is None else not g.get("result"))
                target_team, target_enemy = g.get("enemy"), g.get("team")
            else:
                continue
        elif wanted_set <= set(own) and not wanted_set <= set(enemy):
            target_side, target_picks, enemy_picks, result = "own", own, enemy, g.get("result")
            target_team, target_enemy = g.get("team"), g.get("enemy")
        elif wanted_set <= set(enemy):
            target_side, target_picks, enemy_picks, result = "enemy", enemy, own, (
                None if g.get("result") is None else not g.get("result"))
            target_team, target_enemy = g.get("enemy"), g.get("team")
        else:
            continue
        enemy_players = g.get("enemyPlayers") if target_side == "own" else g.get("players")
        sig = _signature(enemy_picks, enemy_players)
        seen_games.add(game_key)
        rows.append({
            "game": g, "targetSide": target_side, "targetPicks": target_picks,
            "targetTeam": target_team, "targetEnemy": target_enemy,
            "enemyPicks": enemy_picks, "result": result, "signature": sig,
        })

    wins, decided, win_rate, interval = _win_rate(rows)
    lineups = defaultdict(list)
    signatures = defaultdict(list)
    for row in rows:
        if len(row["enemyPicks"]) == 5:
            lineups[tuple(sorted(row["enemyPicks"]))].append(row)
        if row["signature"]:
            signatures[row["signature"]].append(row)
    lineup_rows = []
    for lineup, records in lineups.items():
        lw, ld, lr, li = _win_rate(records)
        lineup_rows.append({"heroes": list(lineup), "label": _combo_label(lineup),
                            "games": len(records), "wins": lw, "decided": ld,
                            "winRate": lr, "interval": li,
                            "share": _pct(len(records), len(rows))})
    lineup_rows.sort(key=lambda r: (-(r["games"] or 0), -(r["winRate"] or 0), r["label"]))
    sig_rows = []
    for sig, records in signatures.items():
        sw, sd, sr, si = _win_rate(records)
        sig_rows.append({"signature": list(sig), "label": _signature_label(sig),
                         "games": len(records), "wins": sw, "decided": sd,
                         "winRate": sr, "interval": si,
                         "share": _pct(len(records), len(rows))})
    sig_rows.sort(key=lambda r: (-(r["games"] or 0), -(r["winRate"] or 0), r["label"]))
    mode = "hero" if len(wanted) == 1 else "lineup" if len(wanted) == 5 else "combo"
    evidence = []
    for row in sorted(rows, key=lambda r: (str(r["game"].get("date") or ""),
                                           str(r["game"].get("id") or "")), reverse=True)[:8]:
        g = row["game"]
        evidence.append({"id": g.get("id"), "date": g.get("date"),
                         "team": row["targetTeam"], "enemy": row["targetEnemy"],
                         "result": row["result"], "source": g.get("source"),
                         "matchId": g.get("matchId"),
                         "ownPicks": row["targetPicks"], "enemyPicks": row["enemyPicks"]})
    return {
        "available": bool(rows), "heroes": wanted, "mode": mode,
        "label": _combo_label(wanted),
        "summary": {"games": len(rows), "wins": wins, "decided": decided,
                    "winRate": win_rate, "interval": interval,
                    "teams": len({r["targetTeam"] for r in rows if r["targetTeam"]}),
                    "sources": sorted({r["game"].get("source") for r in rows if r["game"].get("source")}),
                    "from": min((str(r["game"].get("date") or "") for r in rows), default=""),
                    "to": max((str(r["game"].get("date") or "") for r in rows), default="")},
        "opponentLineups": lineup_rows[:10], "signatures": sig_rows[:8],
        "evidence": evidence,
        "caveats": ([] if len(rows) >= 3 else ["命中局数少于 3 局，只能作为单场观察。"]) +
                   (["对手阵容类型只统计分路可定位的局。"] if sig_rows else []),
    }


# ---------------------------------------------------------------------------
# 04 不同战队如何针对同一英雄 / 体系
# ---------------------------------------------------------------------------

def team_counters(games, target):
    target = _heroes(target)
    target_set = set(target)
    if not target_set:
        return {"available": False, "reason": "请选择要研究的英雄或组合。", "rows": []}
    by_team = defaultdict(list)
    for g in games:
        enemy = set(_heroes(g.get("enemyPicks")))
        own = set(_heroes(g.get("picks")))
        if not target_set <= enemy or target_set <= own:
            continue
        by_team[str(g.get("team") or "未知战队")].append(g)
    rows = []
    all_responses = Counter()
    for team, records in by_team.items():
        wins, decided, win_rate, interval = _win_rate(records)
        target_wins = sum(1 for g in records if g.get("result") is False)
        banned = sum(1 for g in records if target_set & set(_heroes(g.get("bans"))))
        response_heroes = Counter(hero for g in records for hero in _heroes(g.get("picks")))
        response_pairs = Counter(
            pair for g in records for pair in combinations(sorted(_heroes(g.get("picks"))), 2))
        all_responses.update(response_heroes)
        rows.append({
            "team": team, "games": len(records), "wins": wins, "decided": decided,
            "winRate": win_rate, "interval": interval,
            "targetWins": target_wins, "targetWinRate": _pct(target_wins, decided),
            "banGames": banned, "banRate": _pct(banned, len(records)),
            "responseHeroes": [{"hero": hero, "count": count, "share": _pct(count, len(records))}
                               for hero, count in response_heroes.most_common(5)],
            "responseCombos": [{"heroes": list(pair), "label": _combo_label(pair), "count": count}
                               for pair, count in response_pairs.most_common(3)],
            "sample": _sample_label(len(records), decided),
            "evidence": _evidence(records, 3),
        })
    rows.sort(key=lambda r: (-(r["games"] or 0), -(r["winRate"] or 0), r["team"]))
    return {
        "available": bool(rows), "target": target, "label": _combo_label(target),
        "rows": rows,
        "summary": {
            "games": sum(r["games"] for r in rows),
            "teams": len(rows),
            "topResponses": [{"hero": hero, "count": count}
                             for hero, count in all_responses.most_common(6)],
        },
        "caveats": ["只统计目标在对手阵容、本队与之交手的局；Ban 率按拆组合（禁任一英雄）计算。"] +
                   ([] if len(rows) >= 3 else ["可比较的战队少于 3 支，结论只作单场观察。"]),
    }


# ---------------------------------------------------------------------------
# 05 选禁习惯 / 阵营 / 第一手 / Ban 后选择
# ---------------------------------------------------------------------------

def draft_habits(games, team):
    rows = [g for g in games if str(g.get("team") or "") == str(team or "")]
    if not rows:
        return {"available": False, "reason": f"没有找到 {team or '该战队'} 的 BP 记录。",
                "team": team, "topBans": [], "topPicks": []}
    order_rows = [g for g in rows
                  if g.get("pickOrderKnown") and g.get("bansKnown")]
    total = len(rows)
    bans = Counter(hero for g in rows for hero in _heroes(g.get("bans")))
    picks = Counter(hero for g in rows for hero in _heroes(g.get("picks")))
    first_picks = Counter(_heroes(g.get("picks"))[0] for g in order_rows
                          if _heroes(g.get("picks")))
    first_bans = Counter(_heroes(g.get("bans"))[0] for g in order_rows
                         if _heroes(g.get("bans")))

    first_pick_win = {}
    for hero in first_picks:
        records = [g for g in order_rows
                   if _heroes(g.get("picks")) and _heroes(g.get("picks"))[0] == hero]
        wins, decided, win_rate, interval = _win_rate(records)
        first_pick_win[hero] = {"wins": wins, "decided": decided,
                                "winRate": win_rate, "interval": interval}

    pick_slots, ban_slots = [], []
    for slot in range(5):
        slot_picks = Counter(_heroes(g.get("picks"))[slot] for g in order_rows
                             if len(_heroes(g.get("picks"))) > slot)
        slot_bans = Counter(_heroes(g.get("bans"))[slot] for g in order_rows
                            if len(_heroes(g.get("bans"))) > slot)
        pick_slots.append({"slot": slot + 1, "heroes": _top(slot_picks, len(order_rows), 5)})
        ban_slots.append({"slot": slot + 1, "heroes": _top(slot_bans, len(order_rows), 5)})

    side_rows = {}
    for side in ("1", "2"):
        side_games = [g for g in rows if str(g.get("side") or "") == side]
        side_order = [g for g in side_games if g.get("pickOrderKnown") and g.get("bansKnown")]
        wins, decided, win_rate, interval = _win_rate(side_games)
        side_first = Counter(_heroes(g.get("picks"))[0] for g in side_order
                             if _heroes(g.get("picks")))
        side_rows[side] = {"games": len(side_games), "wins": wins, "decided": decided,
                           "winRate": win_rate, "interval": interval,
                           "firstPicks": _top(side_first, len(side_order), 3)}

    ban_responses = []
    for ban_hero in sorted({hero for g in order_rows for hero in _heroes(g.get("enemyBans"))}):
        records = [g for g in order_rows if ban_hero in _heroes(g.get("enemyBans"))]
        if len(records) < 3:
            continue
        response = Counter(_heroes(g.get("picks"))[0] for g in records if _heroes(g.get("picks")))
        options = []
        for hero, count in response.most_common(5):
            matched = [g for g in records
                       if _heroes(g.get("picks")) and _heroes(g.get("picks"))[0] == hero]
            wins, decided, win_rate, interval = _win_rate(matched)
            options.append({"hero": hero, "count": count, "share": _pct(count, len(records)),
                            "wins": wins, "decided": decided,
                            "winRate": win_rate, "interval": interval})
        ban_responses.append({"ban": ban_hero, "games": len(records), "options": options})
    ban_responses.sort(key=lambda row: (-(row["games"] or 0), row["ban"]))

    return {
        "available": True, "team": team, "games": total,
        "orderGames": len(order_rows), "orderKnown": bool(order_rows),
        "topBans": _top(bans, total, 12), "topPicks": _top(picks, total, 12),
        "firstPicks": [{"hero": hero, "count": count, "share": _pct(count, len(order_rows)),
                        **first_pick_win.get(hero, {})}
                       for hero, count in first_picks.most_common(8)],
        "firstBans": _top(first_bans, len(order_rows), 8),
        "sides": side_rows, "pickSlots": pick_slots, "banSlots": ban_slots,
        "banResponses": ban_responses[:8],
        "note": (("训练赛按营地默认 20 手顺序；只表示该队第 N 手，不还原全局交错手序。"
                  if rows[0].get("source") == "scrim" else
                  "KPL 用每方 Pick/Ban 数组顺序；只表示该队第 N 手，不还原全局交错手序。")
                 if order_rows else "当前记录没有逐手顺序，第一手 / 轮次 / Ban 后选择不可计算。"),
        "caveats": ([] if order_rows else ["训练赛或盲选局没有逐手 BP 记录，只显示终局常 Ban / 常 Pick。"]),
    }


# ---------------------------------------------------------------------------
# 06 时间窗口下的 BP 策略演变
# ---------------------------------------------------------------------------

def evolution(games, unit="month", team=None):
    if unit not in ORDER_UNITS:
        raise ValueError(f"未知时间粒度：{unit}")
    rows = [g for g in games if not team or str(g.get("team") or "") == str(team)]
    buckets = defaultdict(list)
    for g in rows:
        buckets[_window_key(g, unit)].append(g)
    windows = []
    for key, records in buckets.items():
        wins, decided, win_rate, interval = _win_rate(records)
        order_records = [g for g in records if g.get("pickOrderKnown") and g.get("bansKnown")]
        picks = Counter(hero for g in records for hero in _heroes(g.get("picks")))
        bans = Counter(hero for g in records for hero in _heroes(g.get("bans")))
        first = Counter(_heroes(g.get("picks"))[0] for g in order_records
                        if _heroes(g.get("picks")))
        pair_games = Counter()
        for g in records:
            heroes = _heroes(g.get("picks"))
            if len(heroes) == 5:
                pair_games.update(combinations(sorted(heroes), 2))
        pairs = []
        for combo, count in pair_games.most_common(3):
            matched = [g for g in records
                       if set(combo) <= set(_heroes(g.get("picks")))]
            pw, pd, pr, _ = _win_rate(matched)
            pairs.append({"heroes": list(combo), "label": _combo_label(combo),
                          "games": count, "wins": pw, "decided": pd, "winRate": pr})
        side = {}
        for side_key in ("1", "2"):
            side_games = [g for g in records if str(g.get("side") or "") == side_key]
            sw, sd, sr, si = _win_rate(side_games)
            side[side_key] = {"games": len(side_games), "wins": sw,
                              "decided": sd, "winRate": sr, "interval": si}
        dates = sorted(str(g.get("date") or "") for g in records if g.get("date"))
        windows.append({
            "key": key, "games": len(records), "wins": wins, "decided": decided,
            "winRate": win_rate, "interval": interval,
            "start": dates[0] if dates else "", "end": dates[-1] if dates else "",
            "topPicks": _top(picks, len(records), 6),
            "topBans": _top(bans, len(records), 6),
            "topPairs": pairs, "sides": side,
            "firstPicks": _top(first, len(order_records), 3),
        })
    windows.sort(key=lambda row: (row["start"] or row["key"], row["key"]))
    return {
        "available": bool(windows), "unit": unit, "windows": windows,
        "note": ("KPL 按时间/阶段分桶；版本字段为空，不把时间变化解释成版本变化。"
                 if rows and rows[0].get("source") == "kpl" else
                 "训练赛只覆盖少量日期；这里只做每日观察，不做趋势结论。"),
    }


# ---------------------------------------------------------------------------
# 旧 07 对手摘要（09 区赛前方案仍复用）
# ---------------------------------------------------------------------------

def opponent_dossier(games, opponent):
    rows = [g for g in games if str(g.get("team") or "") == str(opponent or "")]
    if not rows:
        return {"available": False, "reason": f"没有找到 {opponent or '该对手'} 的记录。",
                "team": opponent, "ownPairs": [], "ownTrios": []}
    wins, decided, win_rate, interval = _win_rate(rows)
    pair_rows = _combo_rows(rows, 2)["top"]
    trio_rows = _combo_rows(rows, 3)["top"]
    worst = defaultdict(list)
    for g in rows:
        enemy = _heroes(g.get("enemyPicks"))
        if len(enemy) != 5:
            continue
        for combo in combinations(sorted(enemy), 2):
            worst[combo].append(g)
    worst_rows = []
    for combo, records in worst.items():
        if len(records) < 3:
            continue
        ow, od, orate, oi = _win_rate(records)
        worst_rows.append({"heroes": list(combo), "label": _combo_label(combo),
                           "games": len(records), "opponentWins": ow,
                           "decided": od, "opponentWinRate": orate,
                           "interval": oi})
    worst_rows.sort(key=lambda r: (r["opponentWinRate"] if r["opponentWinRate"] is not None else 101,
                                   -(r["games"] or 0)))
    side = {}
    for side_key in ("1", "2"):
        side_games = [g for g in rows if str(g.get("side") or "") == side_key]
        sw, sd, sr, si = _win_rate(side_games)
        side[side_key] = {"games": len(side_games), "wins": sw,
                          "decided": sd, "winRate": sr, "interval": si}
    threats = [row for row in pair_rows if row["games"] >= 3]
    threats.sort(key=lambda r: (-(r["games"] or 0), -(r["winRate"] or 0)))
    return {
        "available": True, "team": opponent, "games": len(rows),
        "wins": wins, "decided": decided, "winRate": win_rate, "interval": interval,
        "ownPairs": pair_rows[:10], "ownTrios": trio_rows[:8],
        "worstMatchups": worst_rows[:8], "sides": side,
        "threats": threats[:6],
        "summary": {
            "topThreats": [row["label"] for row in threats[:3]],
            "watch": [row["label"] for row in pair_rows
                      if row["winRate"] is not None and row["winRate"] >= 55 and row["games"] >= 5][:3],
        },
        "caveats": ([] if len(rows) >= 8 else ["该对手样本少于 8 局，只作单场/小样本观察。"]) +
                   ["被克制是历史对阵关联，不是因果结论。"],
    }


# ---------------------------------------------------------------------------
# 03 针对指定对手的历史阵容研究
# ---------------------------------------------------------------------------

def _hero_usage_rows(rows):
    total = len(rows)
    bucket = defaultdict(list)
    for g in rows:
        for hero in _heroes(g.get("picks")):
            bucket[hero].append(g)
    out = []
    for hero, records in bucket.items():
        wins, decided, win_rate, interval = _win_rate(records)
        out.append({"hero": hero, "picks": len(records),
                    "pickRate": _pct(len(records), total),
                    "wins": wins, "decided": decided, "winRate": win_rate,
                    "interval": interval,
                    "sample": _sample_label(len(records), decided)})
    out.sort(key=lambda row: (-(row["picks"] or 0), -(row["decided"] or 0), row["hero"]))
    return out


def _counter_rate(records):
    """对手视角记录的胜率 → 反制方（对手的对手）胜率。"""
    wins, decided, win_rate, interval = _win_rate(records)
    counter_wins = max(0, decided - wins)
    return {"opponentWins": wins, "decided": decided,
            "opponentWinRate": win_rate,
            "counterWins": counter_wins,
            "counterWinRate": _pct(counter_wins, decided),
            "interval": interval}


def _first_action_rows(rows, action="pick"):
    bucket = defaultdict(list)
    for g in rows:
        heroes = _heroes(g.get("picks") if action == "pick" else g.get("bans"))
        if heroes:
            bucket[heroes[0]].append(g)
    out = []
    for hero, records in bucket.items():
        wins, decided, win_rate, interval = _win_rate(records)
        out.append({"hero": hero, "count": len(records),
                    "share": _pct(len(records), len(rows)),
                    "wins": wins, "decided": decided,
                    "winRate": win_rate, "interval": interval})
    return sorted(out, key=lambda row: (-(row["count"] or 0), row["hero"]))


def _opponent_behavior(rows):
    """对手条件行为：阵营第一手、看到我方第一手后的第一手、败后调整、选手池。

    只有 KPL 的每方数组顺序可做第一手；所有“回应”都是同局第一手共现，
    不还原全局交错手序，也不声称因果。
    """
    order_rows = [g for g in rows
                  if g.get("pickOrderKnown") and g.get("bansKnown")]
    if not order_rows:
        return {
            "available": False,
            "reason": "当前对手没有逐手顺序；无法做第一手 / 败后调整。",
            "firstPicksBySide": {}, "firstBansBySide": {},
            "conditionalFirstPicks": [], "series": {}, "players": [],
        }

    by_side, first_bans, conditional = {}, {}, defaultdict(list)
    for side in ("1", "2"):
        side_rows = [g for g in order_rows if str(g.get("side")) == side]
        by_side[side] = _first_action_rows(side_rows, "pick")[:6]
        first_bans[side] = _first_action_rows(side_rows, "ban")[:6]
    for g in order_rows:
        own = _heroes(g.get("picks"))
        enemy = _heroes(g.get("enemyPicks"))
        if own and enemy:
            conditional[enemy[0]].append(g)

    conditional_rows = []
    for our_first, records in conditional.items():
        if len(records) < 3:
            continue
        response = defaultdict(list)
        for g in records:
            own = _heroes(g.get("picks"))
            if own:
                response[own[0]].append(g)
        options = []
        for hero, matched in response.items():
            wins, decided, win_rate, interval = _win_rate(matched)
            options.append({"hero": hero, "count": len(matched),
                            "share": _pct(len(matched), len(records)),
                            "wins": wins, "decided": decided,
                            "winRate": win_rate, "interval": interval})
        options.sort(key=lambda row: (-(row["count"] or 0), row["hero"]))
        conditional_rows.append({"ourFirst": our_first, "games": len(records),
                                 "responses": options[:4]})
    conditional_rows.sort(key=lambda row: (-(row["games"] or 0), row["ourFirst"]))

    series_groups = defaultdict(list)
    for g in order_rows:
        series_groups[str(g.get("matchId") or "")].append(g)
    series_stats = {
        "loss": {"games": 0, "wins": 0, "decided": 0,
                 "firstPickChanged": 0, "banChanged": 0},
        "win": {"games": 0, "wins": 0, "decided": 0,
                "firstPickChanged": 0, "banChanged": 0},
    }
    changes = defaultdict(Counter)
    for series_rows in series_groups.values():
        if len(series_rows) < 2:
            continue
        series_rows.sort(key=lambda g: int(g.get("gameSeq") or 0))
        for previous, current in zip(series_rows, series_rows[1:]):
            if previous.get("result") not in (True, False):
                continue
            bucket_name = "win" if previous["result"] else "loss"
            bucket = series_stats[bucket_name]
            bucket["games"] += 1
            if current.get("result") is True:
                bucket["wins"] += 1
            if current.get("result") is not None:
                bucket["decided"] += 1
            prev_pick = _heroes(previous.get("picks"))
            cur_pick = _heroes(current.get("picks"))
            if prev_pick and cur_pick and prev_pick[0] != cur_pick[0]:
                bucket["firstPickChanged"] += 1
                changes[bucket_name][f"{prev_pick[0]} → {cur_pick[0]}"] += 1
            if set(_heroes(previous.get("bans"))) != set(_heroes(current.get("bans"))):
                bucket["banChanged"] += 1
    for bucket in series_stats.values():
        bucket["nextWinRate"] = _pct(bucket["wins"], bucket["decided"])
        bucket["firstPickChangeRate"] = _pct(bucket["firstPickChanged"], bucket["games"])
        bucket["banChangeRate"] = _pct(bucket["banChanged"], bucket["games"])

    player_rows = defaultdict(list)
    for g in rows:
        for player in g.get("players") or []:
            name = str(player.get("name") or "").strip()
            hero = str(player.get("hero") or "").strip()
            if name and hero:
                player_rows[name].append((hero, g))
    players = []
    for name, records in player_rows.items():
        hero_count = Counter(hero for hero, _ in records)
        hero_rows = []
        for hero, count in hero_count.most_common(3):
            matched = [g for h, g in records if h == hero]
            wins, decided, win_rate, interval = _win_rate(matched)
            hero_rows.append({"hero": hero, "games": count,
                              "wins": wins, "decided": decided,
                              "winRate": win_rate, "interval": interval})
        games = len({g.get("id") for _, g in records})
        first_pick = sum(1 for hero, g in records
                         if _heroes(g.get("picks")) and _heroes(g["picks"])[0] == hero)
        players.append({"player": name, "games": games,
                        "heroes": hero_rows, "firstPickCount": first_pick})
    players.sort(key=lambda row: (-(row["games"] or 0), row["player"]))

    return {
        "available": True,
        "firstPicksBySide": by_side,
        "firstBansBySide": first_bans,
        "conditionalFirstPicks": conditional_rows[:8],
        "series": {
            "afterLoss": series_stats["loss"],
            "afterWin": series_stats["win"],
            "topChanges": {key: [{"change": change, "count": count}
                                  for change, count in counter.most_common(5)]
                           for key, counter in changes.items()},
        },
        "players": players[:10],
        "notes": [
            "第一手 = 该队 Pick/Ban 数组第 1 个；不是全局交错手序。",
            "看到我方第一手后的回应 = 同局两队第一手共现，不是严格的后续动作。",
            "败后调整只统计有 matchId/gameSeq 的连续局；训练赛没有系列赛 ID 时不做。",
            "选手池按 KPL 十人面板的 player/hero/position 汇总；训练赛昵称可能轮换。",
        ],
    }


def opponent_research(games, opponent, *, side="", first_pick="", combo=None, hero=None):
    """指定对手 + 指定 BP 局面下的阵容/英雄使用与反制。

    组合反制与英雄反制都只统计“同一局对手选了目标、对面选了该组合/英雄”的历史
    共现，不是因果克制；样本不足不输出胜率。
    """
    rows0 = [g for g in games if str(g.get("team") or "") == str(opponent or "")]
    if not rows0:
        return {"available": False, "reason": f"没有找到 {opponent or '该对手'} 的记录。",
                "team": opponent, "games": 0}
    order_rows = [g for g in rows0
                  if g.get("source") == "kpl" and g.get("pickOrderKnown")
                  and _heroes(g.get("picks"))]
    first_pick_counter = Counter(_heroes(g.get("picks"))[0] for g in order_rows)
    first_pick_options = [{"hero": hero_name, "count": count,
                           "share": _pct(count, len(order_rows))}
                          for hero_name, count in first_pick_counter.most_common(8)]
    side_options = sorted({str(g.get("side")) for g in rows0 if g.get("side")})
    pair_options = _combo_rows(rows0, 2)["top"][:8]
    trio_options = _combo_rows(rows0, 3)["top"][:6]
    combo_options = [{"heroes": row["heroes"], "label": row["label"],
                      "games": row["games"]} for row in pair_options + trio_options]
    hero_options = [{"hero": row["hero"], "picks": row["picks"],
                     "winRate": row["winRate"]} for row in _hero_usage_rows(rows0)[:12]]

    rows = rows0
    if side:
        rows = [g for g in rows if str(g.get("side")) == str(side)]
    if first_pick:
        # 只有 KPL 的每方数组顺序才可当“第一手”；训练赛终局名单没有手序。
        rows = [g for g in rows
                if g.get("source") == "kpl" and g.get("pickOrderKnown")
                and _heroes(g.get("picks")) and _heroes(g.get("picks"))[0] == first_pick]

    pairs = _combo_rows(rows, 2)["top"][:8]
    trios = _combo_rows(rows, 3)["top"][:8]
    hero_usage = _hero_usage_rows(rows)

    selected_combo = _heroes(combo) if combo else (
        pairs[0]["heroes"] if pairs else (trios[0]["heroes"] if trios else []))
    if selected_combo and not any(set(selected_combo) == set(row["heroes"])
                                  for row in combo_options):
        combo_options.insert(0, {"heroes": selected_combo,
                                 "label": _combo_label(selected_combo), "games": 0})
    selected_hero = str(hero or "").strip()
    if not selected_hero:
        selected_hero = hero_usage[0]["hero"] if hero_usage else ""
    if selected_hero and not any(row["hero"] == selected_hero for row in hero_options):
        hero_options.insert(0, {"hero": selected_hero, "picks": 0, "winRate": None})

    combo_counter_rows = []
    if selected_combo:
        target_set = set(selected_combo)
        size = len(selected_combo)
        buckets = defaultdict(list)
        for g in rows:
            if not target_set <= set(_heroes(g.get("picks"))):
                continue
            enemy = _heroes(g.get("enemyPicks"))
            if len(enemy) != 5 or target_set <= set(enemy):
                continue
            for enemy_combo in combinations(sorted(enemy), size):
                buckets[enemy_combo].append(g)
        for enemy_combo, records in buckets.items():
            if len(records) < 3:
                continue
            rate = _counter_rate(records)
            combo_counter_rows.append({
                "heroes": list(enemy_combo),
                "label": _combo_label(enemy_combo),
                "games": len(records), **rate,
                "evidence": _evidence(records, 3),
            })
        combo_counter_rows.sort(key=lambda row: (
            row["opponentWinRate"] if row["opponentWinRate"] is not None else 101,
            -(row["games"] or 0), row["label"]))

    hero_counter_rows = []
    if selected_hero:
        buckets = defaultdict(list)
        for g in rows:
            if selected_hero not in _heroes(g.get("picks")):
                continue
            enemy_heroes = _heroes(g.get("enemyPicks"))
            # 盲选局双方可能拿到同一英雄；排除自己反制自己。
            if selected_hero in enemy_heroes:
                continue
            for enemy_hero in enemy_heroes:
                buckets[enemy_hero].append(g)
        for enemy_hero, records in buckets.items():
            if len(records) < 3:
                continue
            rate = _counter_rate(records)
            hero_counter_rows.append({
                "hero": enemy_hero, "games": len(records), **rate,
                "evidence": _evidence(records, 3),
            })
        hero_counter_rows.sort(key=lambda row: (
            row["opponentWinRate"] if row["opponentWinRate"] is not None else 101,
            -(row["games"] or 0), row["hero"]))

    total_wins, total_decided, total_rate, total_interval = _win_rate(rows)
    threats = pairs[:4]
    watch = [row for row in pairs
             if row["winRate"] is not None and row["winRate"] >= 55 and row["games"] >= 5][:3]
    caveats = ["组合/英雄反制只统计同一局的历史共现，不是因果克制；样本不足 3 局不展示。"]
    if not order_rows:
        caveats.append("当前对手没有逐手顺序，第一手筛选不可用。")
    if len(rows) < 8:
        caveats.append("指定局面下样本少于 8 局，只作单场/小样本观察。")
    return {
        "available": True, "team": opponent, "games": len(rows0),
        "situationGames": len(rows),
        "wins": total_wins, "decided": total_decided,
        "winRate": total_rate, "interval": total_interval,
        "situation": {"side": side, "firstPick": first_pick,
                      "combo": selected_combo, "hero": selected_hero},
        "options": {"sides": side_options, "firstPicks": first_pick_options,
                    "combos": combo_options, "heroes": hero_options},
        "comboUsage": {"pairs": pairs, "trios": trios},
        "comboCounters": {"combo": selected_combo,
                          "label": _combo_label(selected_combo),
                          "rows": combo_counter_rows[:10]},
        "heroUsage": hero_usage[:12],
        "heroCounters": {"hero": selected_hero,
                         "rows": hero_counter_rows[:10]},
        "behavior": _opponent_behavior(rows0),
        "summary": {
            "topThreats": [row["label"] for row in threats[:3]],
            "watch": [row["label"] for row in watch],
        },
        "caveats": caveats,
    }


# ---------------------------------------------------------------------------
# 07 训练赛体系有效性
# ---------------------------------------------------------------------------

def _verdict(row):
    if row["decided"] < 3 or row["games"] < 3 or row["relative"] is None:
        return "样本不足"
    if row["relative"] >= 5:
        return "有效（观察）"
    if row["relative"] <= -5:
        return "未达预期"
    return "持平 / 待验证"


def scrim_systems(games, team="本队"):
    rows = [g for g in games
            if g.get("source") == "scrim" and str(g.get("team") or "") == str(team or "本队")]
    if not rows:
        return {"available": False, "reason": "当前没有训练赛本队记录。",
                "pairRows": [], "trioRows": []}
    pair_rows = _combo_rows(rows, 2)["top"]
    trio_rows = _combo_rows(rows, 3)["top"]
    lane_maps = {id(g): _lane_map(g.get("players")) for g in rows}
    validity = []
    for size, source_rows in ((2, pair_rows), (3, trio_rows)):
        for row in source_rows[:12]:
            heroes = row["heroes"]
            matched = [g for g in rows if set(heroes) <= set(_heroes(g.get("picks")))]
            lanes = Counter()
            players = Counter()
            for g in matched:
                lane_of = lane_maps[id(g)]
                for hero in heroes:
                    if lane_of.get(hero):
                        lanes[lane_of[hero]] += 1
                for player in g.get("players") or []:
                    if player.get("hero") in heroes and player.get("name"):
                        players[player["name"]] += 1
            lane_fit = bool(lanes) and len(set(lanes)) == len(heroes)
            validity.append({**row, "size": size, "verdict": _verdict(row),
                             "lanes": [{"lane": lane, "count": count}
                                       for lane, count in lanes.most_common()],
                             "players": [{"player": name, "count": count}
                                         for name, count in players.most_common(3)],
                             "laneFit": lane_fit})
    validity.sort(key=lambda r: ({"有效（观察）": 0, "持平 / 待验证": 1,
                                  "未达预期": 2, "样本不足": 3}.get(r["verdict"], 9),
                                 -(r["games"] or 0)))
    enemy_pairs = defaultdict(list)
    for g in rows:
        enemy = _heroes(g.get("enemyPicks"))
        if len(enemy) != 5:
            continue
        for combo in combinations(sorted(enemy), 2):
            enemy_pairs[combo].append(g)
    counter_rows = []
    for combo, records in enemy_pairs.items():
        if len(records) < 3:
            continue
        cw, cd, cr, ci = _win_rate(records)
        counter_rows.append({"heroes": list(combo), "label": _combo_label(combo),
                             "games": len(records), "ourWins": cw,
                             "decided": cd, "ourWinRate": cr, "interval": ci})
    counter_rows.sort(key=lambda row: (-(row["games"] or 0), row["label"]))

    wins, decided, win_rate, interval = _win_rate(rows)
    return {
        "available": True, "team": team, "games": len(rows),
        "wins": wins, "decided": decided, "winRate": win_rate, "interval": interval,
        "pairRows": pair_rows[:10], "trioRows": trio_rows[:8],
        "counterRows": counter_rows[:10],
        "validity": validity[:16],
        "summary": {"effective": sum(1 for row in validity if row["verdict"] == "有效（观察）"),
                    "watch": sum(1 for row in validity if row["verdict"] == "持平 / 待验证"),
                    "weak": sum(1 for row in validity if row["verdict"] == "未达预期")},
        "caveats": ["训练赛样本少，组合胜率只作本批观察；不把相对基准差值写成因果。"] +
                   ([] if len(rows) >= 20 else ["本队训练赛少于 20 局，先积累样本再判断体系是否稳定。"]),
    }


# ---------------------------------------------------------------------------
# 08 组合胜率稳定性
# ---------------------------------------------------------------------------

def combo_stability(games, combo, unit="month", available=None):
    combo = _heroes(combo)
    combo_set = set(combo)
    if not combo_set:
        return {"available": False, "reason": "请选择一个组合。", "windows": []}
    rows = [g for g in games if combo_set <= set(_heroes(g.get("picks")))]
    available_rows = []
    if available is not None:
        for row in available:
            if row.get("games", 0) >= 3:
                available_rows.append({"heroes": row["heroes"], "label": row["label"],
                                       "games": row["games"]})
    else:
        pair_rows = _combo_rows(games, 2)["top"]
        trio_rows = _combo_rows(games, 3)["top"]
        for row in pair_rows + trio_rows:
            if row["games"] >= 3:
                available_rows.append({"heroes": row["heroes"], "label": row["label"],
                                       "games": row["games"]})
    available_rows.sort(key=lambda r: (-(r["games"] or 0), r["label"]))
    if not rows:
        return {"available": False, "reason": "该组合在当前范围没有命中局。",
                "combo": combo, "label": _combo_label(combo), "windows": [],
                "availableCombos": available_rows[:16]}
    buckets = defaultdict(list)
    for g in rows:
        buckets[_window_key(g, unit)].append(g)
    windows = []
    for key, records in buckets.items():
        wins, decided, win_rate, interval = _win_rate(records)
        dates = sorted(str(g.get("date") or "") for g in records if g.get("date"))
        windows.append({"key": key, "games": len(records), "wins": wins,
                        "decided": decided, "winRate": win_rate,
                        "interval": interval,
                        "start": dates[0] if dates else "",
                        "end": dates[-1] if dates else ""})
    windows.sort(key=lambda row: (row["start"] or row["key"], row["key"]))
    valid = [row for row in windows if row["decided"] >= 3 and row["winRate"] is not None]
    rates = [row["winRate"] for row in valid]
    total_wins, total_decided, total_rate, total_interval = _win_rate(rows)
    range_pp = round(max(rates) - min(rates), 1) if len(rates) >= 2 else None
    drawdown = None
    if rates:
        peak, drawdown = rates[0], 0
        for rate in rates[1:]:
            peak = max(peak, rate)
            drawdown = max(drawdown, peak - rate)
        drawdown = round(drawdown, 1)
    trend = round(rates[-1] - rates[0], 1) if len(rates) >= 2 else None
    if len(valid) < 3 or total_decided < 9:
        verdict = "样本不足"
    elif (range_pp or 0) <= 15 and (trend is None or abs(trend) <= 10):
        verdict = "稳定"
    elif (range_pp or 0) <= 30:
        verdict = "有波动"
    else:
        verdict = "波动大"
    return {
        "available": True, "combo": combo, "label": _combo_label(combo),
        "unit": unit, "total": len(rows), "wins": total_wins,
        "decided": total_decided, "winRate": total_rate, "interval": total_interval,
        "windows": windows, "validWindows": len(valid),
        "rangePP": range_pp, "maxDrawdown": drawdown, "trend": trend,
        "verdict": verdict, "availableCombos": available_rows[:16],
        "caveats": ["至少 3 个有效窗口（每窗 ≥3 局有胜负）才判断稳定；窗口少时只展示序列。"],
    }


# ---------------------------------------------------------------------------
# 09 赛前方案
# ---------------------------------------------------------------------------

def plan(games, team, opponent, source="kpl", rule="scrim-global-20", bo="BO5"):
    team = str(team or "")
    opponent = str(opponent or "")
    opp_rows = [g for g in games if str(g.get("team") or "") == opponent]
    if not opp_rows:
        return {"available": False, "reason": "请选择有记录的对手。",
                "team": team, "opponent": opponent}
    team_rows = [g for g in games if str(g.get("team") or "") == team] if team else []
    opp_habits = draft_habits(games, opponent)
    opp_dossier = opponent_dossier(games, opponent)

    threats = []
    for row in (opp_dossier.get("ownPairs") or [])[:5]:
        threats.append({"label": row["label"], "games": row["games"],
                        "winRate": row["winRate"], "sample": row.get("sample")})
    for row in (opp_dossier.get("ownTrios") or [])[:3]:
        threats.append({"label": row["label"], "games": row["games"],
                        "winRate": row["winRate"], "sample": row.get("sample")})

    ban_priority = []
    for row in (opp_habits.get("topPicks") or [])[:8]:
        hero = row["hero"]
        facing = [g for g in (team_rows or games) if hero in _heroes(g.get("enemyPicks"))]
        wins, decided, win_rate, interval = _win_rate(facing)
        if len(facing) < 2:
            continue
        ban_priority.append({
            "hero": hero, "oppPicks": row["count"], "oppShare": row["share"],
            "ourGames": len(facing), "ourWins": wins, "ourDecided": decided,
            "ourWinRate": win_rate, "interval": interval,
            "reason": "对手常 Pick" + (f"，我们对位胜率 {win_rate}%" if win_rate is not None else ""),
        })
    ban_priority.sort(key=lambda row: ((row["ourWinRate"] if row["ourWinRate"] is not None else 50),
                                       -(row["oppShare"] or 0)))

    our_habits = draft_habits(games, team) if team else {"available": False}
    branches = []
    for row in (our_habits.get("banResponses") or [])[:5]:
        branches.append({"ban": row["ban"], "games": row["games"],
                         "options": row["options"][:3]})

    responses = []
    for row in (opp_dossier.get("ownPairs") or [])[:5]:
        combo = row["heroes"]
        facing = [g for g in (team_rows or games)
                  if set(combo) <= set(_heroes(g.get("enemyPicks")))]
        if len(facing) < 2:
            continue
        wins, decided, win_rate, interval = _win_rate(facing)
        picks = Counter(hero for g in facing for hero in _heroes(g.get("picks")))
        responses.append({
            "opponentCombo": row["label"], "games": len(facing),
            "ourWins": wins, "ourDecided": decided, "ourWinRate": win_rate,
            "interval": interval,
            "responseHeroes": [{"hero": hero, "count": count}
                               for hero, count in picks.most_common(5)],
        })

    if source == "scrim":
        from bp_rules import SCRIM_RULES, scrim_rule
        selected = scrim_rule(rule)
        rule_notes = {
            "id": selected.id, "title": selected.title,
            "bansPerSide": sum(1 for action, _camp in selected.schedule if action == "ban") // 2,
            "picksPerSide": sum(1 for action, _camp in selected.schedule if action == "pick") // 2,
            "global": True,
            "note": "训练赛 BO 全局 BP：此前局已选英雄按战队身份禁用；本页只给历史证据，不模拟最优解。",
        }
    else:
        rule_notes = {"id": "kpl-recorded", "title": "KPL 赛事记录",
                      "bansPerSide": None, "picksPerSide": None, "global": False,
                      "note": "KPL 不套用训练赛 15/20 手规则；方案只按历史对手证据准备。"}

    our_systems = []
    if source == "scrim":
        scrim = scrim_systems(games)
        our_systems = (scrim.get("validity") or [])[:6]
    elif team_rows:
        for row in _combo_rows(team_rows, 2)["top"][:5]:
            our_systems.append({"label": row["label"], "games": row["games"],
                                "winRate": row["winRate"], "relative": row["relative"],
                                "verdict": _verdict(row)})

    summary = []
    if threats:
        summary.append(f"对手最常用：{threats[0]['label']}（{threats[0]['games']} 局）")
    if ban_priority:
        summary.append(f"优先限制：{ban_priority[0]['hero']}")
    if branches:
        first = branches[0]
        option = first["options"][0] if first["options"] else None
        if option:
            summary.append(f"对手 Ban {first['ban']} 后，本队第一手最常选 {option['hero']}")

    return {
        "available": True, "team": team, "opponent": opponent,
        "source": source, "rule": rule_notes, "bo": bo,
        "threats": threats[:8], "banPriority": ban_priority[:6],
        "branches": branches, "responses": responses[:5],
        "ourSystems": our_systems, "summary": summary,
        "caveats": ["方案是历史证据 + 规则提示，不是最优阵容求解；样本不足的分支必须标待验证。",
                    "KPL 与训练赛胜率不混算；对手样本少时只作单场观察。"],
    }


# ---------------------------------------------------------------------------
# 时间对比：当前窗口 / 环比 / 同比
# ---------------------------------------------------------------------------

def _shift_year(day, years):
    try:
        return day.replace(year=day.year + years)
    except ValueError:  # 2/29
        return day.replace(year=day.year + years, day=28)


def _day(value):
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _delta(current, previous):
    return (round(current - previous, 1)
            if isinstance(current, (int, float)) and isinstance(previous, (int, float))
            else None)


def _period_summary(rows, start, end):
    wins, decided, win_rate, interval = _win_rate(rows)
    board = hero_board(rows)
    combos = combo_board(rows)
    picks = sorted(board["rows"], key=lambda row: (-(row["pickRate"] or 0), row["hero"]))
    bans = sorted(board["rows"], key=lambda row: (-(row["banRate"] or 0), row["hero"]))
    pairs = combos.get("pairs") or []
    order_rows = [g for g in rows if g.get("pickOrderKnown") and g.get("bansKnown")]
    first = Counter(_heroes(g.get("picks"))[0] for g in order_rows if _heroes(g.get("picks")))
    sides = {}
    for side in ("1", "2"):
        side_rows = [g for g in rows if str(g.get("side")) == side]
        sw, sd, sr, si = _win_rate(side_rows)
        sides[side] = {"games": len(side_rows), "wins": sw, "decided": sd,
                       "winRate": sr, "interval": si}
    return {
        "start": start.isoformat(), "end": end.isoformat(),
        "matches": len({g.get("id") for g in rows}),
        "games": len(rows), "wins": wins, "decided": decided,
        "winRate": win_rate, "interval": interval,
        "teams": len({g.get("team") for g in rows if g.get("team")}),
        "topPick": picks[0]["hero"] if picks else None,
        "topPickRate": picks[0]["pickRate"] if picks else None,
        "topBan": bans[0]["hero"] if bans else None,
        "topBanRate": bans[0]["banRate"] if bans else None,
        "topCombo": pairs[0]["label"] if pairs else None,
        "topComboWinRate": pairs[0]["winRate"] if pairs else None,
        "sides": sides,
        "firstPicks": _top(first, len(order_rows), 3),
        "orderGames": len(order_rows),
    }


def _target_metrics(rows, target):
    target = _heroes(target)
    if not target:
        return None
    wanted = set(target)
    if len(target) == 1:
        picked = [g for g in rows if target[0] in _heroes(g.get("picks"))]
        banned = [g for g in rows if target[0] in _heroes(g.get("bans"))]
        wins, decided, win_rate, interval = _win_rate(picked)
        return {"label": target[0], "mode": "hero", "games": len(rows),
                "picks": len(picked), "pickRate": _pct(len(picked), len(rows)),
                "bans": len(banned), "banRate": _pct(len(banned), len(rows)),
                "wins": wins, "decided": decided, "winRate": win_rate,
                "interval": interval}
    picked = [g for g in rows if wanted <= set(_heroes(g.get("picks")))]
    banned = [g for g in rows if wanted & set(_heroes(g.get("bans")))]
    wins, decided, win_rate, interval = _win_rate(picked)
    return {"label": _combo_label(target), "mode": "combo", "games": len(rows),
            "picks": len(picked), "share": _pct(len(picked), len(rows)),
            "bans": len(banned), "banRate": _pct(len(banned), len(rows)),
            "wins": wins, "decided": decided, "winRate": win_rate,
            "interval": interval}


def period_compare(games, *, start="", end="", source="kpl", team="", recent_days=30, target=None):
    """当前窗口 vs 上一个等长窗口（环比）vs 去年同日期（同比）。"""
    rows = [g for g in games if not team or str(g.get("team") or "") == team]
    days = [_day(g.get("date")) for g in rows]
    days = [day for day in days if day]
    if not days:
        return {"available": False, "reason": "当前范围没有日期记录，无法做时间对比。",
                "heroes": [], "combos": []}
    max_day, min_day = max(days), min(days)
    end_day = _day(end) or max_day
    end_day = min(end_day, max_day)
    if start:
        start_day = _day(start) or end_day
    else:
        window_days = 6 if source == "scrim" else max(1, int(recent_days or 30) - 1)
        start_day = end_day - timedelta(days=window_days)
    if start_day > end_day:
        start_day, end_day = end_day, start_day
    span = (end_day - start_day).days + 1
    prev_end = start_day - timedelta(days=1)
    prev_start = prev_end - timedelta(days=span - 1)
    yoy_start = _shift_year(start_day, -1)
    yoy_end = _shift_year(end_day, -1)

    def window(a, b):
        return [g for g in rows if (d := _day(g.get("date"))) and a <= d <= b]

    current_rows, previous_rows, yoy_rows = (
        window(start_day, end_day), window(prev_start, prev_end), window(yoy_start, yoy_end))
    current = _period_summary(current_rows, start_day, end_day)
    previous = _period_summary(previous_rows, prev_start, prev_end)
    yoy = _period_summary(yoy_rows, yoy_start, yoy_end)
    current_board = {row["hero"]: row for row in hero_board(current_rows)["rows"]}
    previous_board = {row["hero"]: row for row in hero_board(previous_rows)["rows"]}
    yoy_board = {row["hero"]: row for row in hero_board(yoy_rows)["rows"]}
    top_heroes = sorted(current_board.values(),
                        key=lambda row: (-(row["pickRate"] or 0), row["hero"]))[:20]
    heroes = []
    for row in top_heroes:
        hero = row["hero"]
        prev = previous_board.get(hero) or {}
        last = yoy_board.get(hero) or {}
        heroes.append({
            "hero": hero, "lane": row.get("lane"),
            "picks": row.get("picks"), "decided": row.get("decided"),
            "pickRate": row.get("pickRate"), "banRate": row.get("banRate"),
            "winRate": row.get("winRate"),
            "prevPickRate": prev.get("pickRate"), "prevWinRate": prev.get("winRate"),
            "yoyPickRate": last.get("pickRate"), "yoyWinRate": last.get("winRate"),
            "pickDelta": _delta(row.get("pickRate"), prev.get("pickRate")),
            "banDelta": _delta(row.get("banRate"), prev.get("banRate")),
            "winDelta": _delta(row.get("winRate"), prev.get("winRate")),
            "pickDeltaYoy": _delta(row.get("pickRate"), last.get("pickRate")),
            "banDeltaYoy": _delta(row.get("banRate"), last.get("banRate")),
            "winDeltaYoy": _delta(row.get("winRate"), last.get("winRate")),
            "sample": row.get("sample"),
        })

    def combo_map(records):
        out = {}
        for row in (records.get("pairs") or []) + (records.get("trios") or []):
            out[row["label"]] = row
        return out

    current_combos = combo_map(combo_board(current_rows))
    previous_combos = combo_map(combo_board(previous_rows))
    yoy_combos = combo_map(combo_board(yoy_rows))
    combo_rows = sorted(current_combos.values(),
                        key=lambda row: (-(row["games"] or 0), row["label"]))[:30]
    combos = []
    for row in combo_rows:
        label = row["label"]
        prev = previous_combos.get(label) or {}
        last = yoy_combos.get(label) or {}
        combos.append({
            "heroes": row["heroes"], "label": label,
            "games": row["games"], "share": row.get("share"),
            "winRate": row.get("winRate"),
            "prevWinRate": prev.get("winRate"), "yoyWinRate": last.get("winRate"),
            "winDelta": _delta(row.get("winRate"), prev.get("winRate")),
            "winDeltaYoy": _delta(row.get("winRate"), last.get("winRate")),
            "prevGames": prev.get("games"), "yoyGames": last.get("games"),
            "sample": row.get("sample"),
        })

    target_rows = None
    if target:
        cur_target = _target_metrics(current_rows, target)
        prev_target = _target_metrics(previous_rows, target)
        yoy_target = _target_metrics(yoy_rows, target)
        if cur_target:
            target_rows = {"heroes": _heroes(target), "label": cur_target["label"],
                           "mode": cur_target["mode"], "current": cur_target,
                           "previous": prev_target, "yoy": yoy_target,
                           "shareDelta": _delta(cur_target.get("share", cur_target.get("pickRate")),
                                                (prev_target or {}).get("share", (prev_target or {}).get("pickRate"))),
                           "shareDeltaYoy": _delta(cur_target.get("share", cur_target.get("pickRate")),
                                                   (yoy_target or {}).get("share", (yoy_target or {}).get("pickRate"))),
                           "banDelta": _delta(cur_target.get("banRate"), (prev_target or {}).get("banRate")),
                           "banDeltaYoy": _delta(cur_target.get("banRate"), (yoy_target or {}).get("banRate")),
                           "winDelta": _delta(cur_target.get("winRate"), (prev_target or {}).get("winRate")),
                           "winDeltaYoy": _delta(cur_target.get("winRate"), (yoy_target or {}).get("winRate"))}
    def first_map(records):
        order = [g for g in records if g.get("pickOrderKnown") and g.get("bansKnown")]
        return Counter(_heroes(g.get("picks"))[0] for g in order if _heroes(g.get("picks"))), len(order)

    cur_first, cur_n = first_map(current_rows)
    prev_first, prev_n = first_map(previous_rows)
    yoy_first, yoy_n = first_map(yoy_rows)
    first_rows = []
    for hero_name, count in cur_first.most_common(8):
        first_rows.append({
            "hero": hero_name,
            "count": count, "share": _pct(count, cur_n),
            "prevShare": _pct(prev_first.get(hero_name, 0), prev_n),
            "yoyShare": _pct(yoy_first.get(hero_name, 0), yoy_n),
            "shareDelta": _delta(_pct(count, cur_n), _pct(prev_first.get(hero_name, 0), prev_n)),
            "shareDeltaYoy": _delta(_pct(count, cur_n), _pct(yoy_first.get(hero_name, 0), yoy_n)),
        })

    previous_available = bool(previous_rows)
    yoy_available = bool(yoy_rows)
    caveats = ["环比 = 当前窗口前一个等长窗口；同比 = 去年同日期，不是自然月/自然年，跨越缺口时会标样本不足。",
               "时间对比是历史关联，不解释为版本/选手/对手造成的因果。"]
    if source == "scrim":
        caveats.append("训练赛当前只有 8 个日期；不足等长窗口或去年同日期的部分显示为空，不做硬同比。")
    if not previous_available:
        caveats.append("上一个等长窗口没有对局：环比不可计算。")
    if not yoy_available:
        caveats.append("去年同日期没有对局：同比不可计算（新数据源或样本跨度不足）。")
    return {
        "available": bool(current_rows), "source": source, "team": team,
        "current": current, "previous": previous, "yoy": yoy,
        "previousAvailable": previous_available, "yoyAvailable": yoy_available,
        "heroes": heroes, "combos": combos, "firstPicks": first_rows,
        "target": target_rows,
        "caveats": caveats,
    }


# ---------------------------------------------------------------------------
# BP 策略沙盘（训练赛规则 + 历史证据；单步候选，不声称最优）
# ---------------------------------------------------------------------------

def _pct_text(value):
    return f"{value}%" if isinstance(value, (int, float)) else "—"


def _shrunk_rate(row):
    """小样本胜率向 50% 收缩，避免 1 局 100% 直接排到最前。"""
    wins = (row or {}).get("wins") or 0
    decided = (row or {}).get("decided") or 0
    return ((wins + 2) / (decided + 4) * 100) if decided else 50.0


def simulate_scrim(payload, hero_pool, evidence_games):
    """训练赛规则下的下一手候选与对手一步回应。

    规则只走训练赛 15/20 手；证据可以来自 KPL 或训练赛（由调用方传
    evidence_games）。候选排序是透明的历史证据加权，不是搜索最优解；
    对手回应只推一步，不做完整多步博弈。
    """
    from bp_rules import (append_legal_scrim_action, build_series_used,
                          legal_scrim_candidates, next_scrim_action,
                          scrim_rule, validate_scrim_prefix,
                          validate_series_context)
    if not isinstance(payload, dict):
        raise ValueError('BP 沙盘请求必须是对象')
    rule = scrim_rule(str(payload.get('rule') or 'scrim-global-20'))
    bo = str(payload.get('bo') or 'BO5')
    try:
        game_number = int(payload.get('gameNumber') or 1)
    except (TypeError, ValueError):
        raise ValueError('局数必须是整数')
    validate_series_context(bo, game_number)
    team = str(payload.get('team') or '').strip()
    opponent = str(payload.get('opponent') or '').strip()
    if not team or not opponent or team == opponent:
        raise ValueError('沙盘需要两支不同的战队')
    side = str(payload.get('side') or '1')
    if side not in ('1', '2'):
        raise ValueError('side 只能是 1 或 2')
    blue_team, red_team = (team, opponent) if side == '1' else (opponent, team)
    events = payload.get('events') or []
    if not isinstance(events, list) or not validate_scrim_prefix(events, rule=rule):
        raise ValueError(f'当前 BP 前缀不符合 {rule.title}')
    used = {}
    if game_number > 1:
        history = payload.get('history')
        if not isinstance(history, list):
            raise ValueError('跨局沙盘需要 history 列表')
        used = build_series_used(history, bo=bo, game_number=game_number,
                                 teams=[team, opponent])
    next_action = next_scrim_action(events, rule=rule)
    if next_action is None:
        return {
            "available": True, "complete": True,
            "rule": {"id": rule.id, "title": rule.title,
                     "actions": len(rule.schedule)},
            "team": team, "opponent": opponent, "side": side,
            "events": events, "nextAction": None,
            "candidates": [], "branches": [],
            "note": "本局 BP 已完成。",
        }
    legal = legal_scrim_candidates(
        events, hero_pool,
        series_used_by_team=used if game_number > 1 else {},
        blue_team=blue_team, red_team=red_team,
        bo=bo, game_number=game_number, rule=rule,
    )
    our_rows = [g for g in evidence_games if str(g.get('team') or '') == team]
    opp_rows = [g for g in evidence_games if str(g.get('team') or '') == opponent]
    our_heroes = {row['hero']: row for row in _hero_usage_rows(our_rows)}
    opp_heroes = {row['hero']: row for row in _hero_usage_rows(opp_rows)}
    our_pairs, opp_pairs = {}, {}
    for size in (2, 3):
        for row in _combo_rows(our_rows, size)['top']:
            our_pairs[frozenset(row['heroes'])] = row
        for row in _combo_rows(opp_rows, size)['top']:
            opp_pairs[frozenset(row['heroes'])] = row
    our_camp = side
    opp_camp = '2' if side == '1' else '1'
    actor_is_ours = str(next_action['camp']) == our_camp
    actor_rows = our_rows if actor_is_ours else opp_rows
    actor_heroes = our_heroes if actor_is_ours else opp_heroes
    threat_heroes = opp_heroes if actor_is_ours else our_heroes
    actor_pairs = our_pairs if actor_is_ours else opp_pairs
    our_picks = [str(e.get('hero')) for e in events
                 if e.get('action') == 'pick' and str(e.get('camp')) == our_camp]
    opp_picks = [str(e.get('hero')) for e in events
                 if e.get('action') == 'pick' and str(e.get('camp')) == opp_camp]
    actor_picks = our_picks if actor_is_ours else opp_picks
    action = next_action['action']

    candidates = []
    for hero in legal:
        reasons, evidence = [], {}
        if action == 'ban':
            threat = threat_heroes.get(hero) or {}
            facing = [g for g in actor_rows if hero in _heroes(g.get('enemyPicks'))]
            fw, fd, fwr, _ = _win_rate(facing)
            score = ((threat.get('pickRate') or 0) * 1.2
                     + _shrunk_rate(threat) * 0.2
                     + max(0, 50 - (fwr if fwr is not None else 50)) * 0.2)
            score *= 0.5 + 0.5 * min(1, (threat.get('picks') or 0) / 20)
            if threat:
                reasons.append(f"对方常用：{threat.get('picks', 0)} 次，胜率 {_pct_text(threat.get('winRate'))}")
            if fd:
                reasons.append(f"该方面对该英雄 {fd} 局，胜率 {_pct_text(fwr)}")
            evidence = {"threatPicks": threat.get('picks'),
                        "threatPickRate": threat.get('pickRate'),
                        "threatWinRate": threat.get('winRate'),
                        "facingGames": fd, "facingWinRate": fwr}
        else:
            actor = actor_heroes.get(hero) or {}
            synergy = []
            for current in actor_picks:
                row = actor_pairs.get(frozenset([hero, current]))
                if row:
                    synergy.append(row)
            best = max(synergy, key=lambda row: row.get('winRate') or 0) if synergy else None
            score = (_shrunk_rate(actor) * 0.45
                     + (actor.get('pickRate') or 0) * 0.2
                     + _shrunk_rate(best) * 0.35)
            score *= 0.5 + 0.5 * min(1, (actor.get('picks') or 0) / 20)
            if actor:
                reasons.append(f"常用：{actor.get('picks', 0)} 次，胜率 {_pct_text(actor.get('winRate'))}")
            if best:
                reasons.append(f"与当前阵容组合 {best.get('label')}：{best.get('winRate')}%")
            evidence = {"actorPicks": actor.get('picks'),
                        "actorPickRate": actor.get('pickRate'),
                        "actorWinRate": actor.get('winRate'),
                        "synergyCombo": best.get('label') if best else None,
                        "synergyWinRate": best.get('winRate') if best else None}
        base_sample = (evidence.get('threatPicks') or evidence.get('actorPicks') or 0)
        candidates.append({
            "hero": hero, "action": action, "score": round(score, 1),
            "actor": "ours" if actor_is_ours else "opponent",
            "reasons": reasons or ["没有足够的同条件历史证据，仅保留规则合法候选。"],
            "evidence": evidence,
            "confidence": ("high" if base_sample >= 20
                           else "medium" if base_sample >= 8 else "low"),
        })
    candidates.sort(key=lambda row: (-(row["score"] or 0), row["hero"]))

    branches = []
    for candidate in (candidates[:3] if actor_is_ours else []):
        try:
            advanced = append_legal_scrim_action(
                events, candidate["hero"], hero_pool,
                series_used_by_team=used if game_number > 1 else {},
                blue_team=blue_team, red_team=red_team,
                bo=bo, game_number=game_number, rule=rule,
            )
        except ValueError:
            continue
        following = next_scrim_action(advanced, rule=rule)
        if following is None:
            branches.append({"candidate": candidate, "opponentNext": None,
                             "note": "本局 BP 结束。"})
            continue
        if str(following["camp"]) != opp_camp:
            branches.append({"candidate": candidate,
                             "opponentNext": {"action": following["action"],
                                              "options": [],
                                              "note": "下一手仍是我方，暂不推演。"}})
            continue
        try:
            legal_opp = legal_scrim_candidates(
                advanced, hero_pool,
                series_used_by_team=used if game_number > 1 else {},
                blue_team=blue_team, red_team=red_team,
                bo=bo, game_number=game_number, rule=rule,
            )
        except ValueError:
            legal_opp = []
        options = []
        total_picks = max(1, len(opp_rows))
        for hero in legal_opp:
            row = opp_heroes.get(hero)
            options.append({"hero": hero,
                            "opponentPicks": row.get('picks') if row else 0,
                            "share": _pct(row.get('picks') if row else 0, total_picks),
                            "winRate": row.get('winRate') if row else None})
        options.sort(key=lambda row: (-(row["opponentPicks"] or 0), row["hero"]))
        branches.append({"candidate": candidate,
                         "opponentNext": {"action": following["action"],
                                          "options": options[:4],
                                          "basis": "对手历史 Pick/Ban 频率，不是预测。"}})

    return {
        "available": True, "complete": False,
        "rule": {"id": rule.id, "title": rule.title,
                 "actions": len(rule.schedule),
                 "bansPerSide": sum(1 for a, _ in rule.schedule if a == "ban") // 2,
                 "picksPerSide": sum(1 for a, _ in rule.schedule if a == "pick") // 2},
        "team": team, "opponent": opponent, "side": side,
        "bo": bo, "gameNumber": game_number,
        "events": events, "nextAction": next_action,
        "actor": "ours" if actor_is_ours else "opponent",
        "ourPicks": our_picks, "opponentPicks": opp_picks,
        "candidates": candidates[:10], "branches": branches,
        "note": "候选按历史证据加权，不是最优解；对手回应只推一步。",
        "caveats": ["规则只走训练赛 15/20 手；KPL 证据只作历史参考，不套用 KPL 规则。",
                    "候选排序不包含选手当天状态、隐藏战术与训练目标，最终由教练决定。",
                    "对手回应是历史频率，不是预测；多步搜索与 BO 系列回测尚未接入。"],
    }


# ---------------------------------------------------------------------------
# 顶层组装
# ---------------------------------------------------------------------------

def build_report(games, *, source="kpl", team="", opponent="", unit="month",
                 target=None, combo=None, rule="scrim-global-20", bo="BO5",
                 recent_days=30):
    games = list(games or [])
    source = "scrim" if source == "scrim" else "kpl"
    team = str(team or "").strip()
    opponent = str(opponent or "").strip()
    unit = unit if unit in ORDER_UNITS else ("day" if source == "scrim" else "month")

    teams = sorted({str(g.get("team") or "") for g in games if g.get("team")})
    team_counts = Counter(str(g.get("team") or "") for g in games
                          if str(g.get("team") or ""))
    if team:
        default_team = team
    elif source == "scrim" and "本队" in teams:
        default_team = "本队"
    else:
        default_team = team_counts.most_common(1)[0][0] if team_counts else ""
    candidates = [name for name, _ in team_counts.most_common() if name and name != default_team]
    default_opponent = opponent or (candidates[0] if candidates else "")

    focus_games = games
    if team:
        focus_games = [g for g in games if str(g.get("team") or "") == team]
    elif source == "scrim":
        focus_games = [g for g in games if str(g.get("team") or "") == "本队"]

    heroes = hero_board(focus_games)
    combos = combo_board(focus_games, recent_days=recent_days)
    target_list = _heroes(target) if target else None
    if not target_list:
        target_list = (combos.get("spotlight") or {}).get("heroes") or (
            combos.get("pairs")[0]["heroes"] if combos.get("pairs") else [])
    combo_list = _heroes(combo) if combo else None
    if not combo_list:
        combo_list = target_list if 2 <= len(target_list) <= 3 else (
            combos.get("pairs")[0]["heroes"] if combos.get("pairs") else [])

    dates = sorted(str(g.get("date") or "") for g in games if g.get("date"))
    versions = sorted({str(g.get("version") or "").strip()
                       for g in games if str(g.get("version") or "").strip()})
    order_games = len({g.get("id") for g in games
                       if g.get("pickOrderKnown") and g.get("bansKnown")})
    caveats = [
        "KPL 与训练赛分源；胜率不混池。",
        "KPL 只按每方 Pick/Ban 数组顺序统计“第 N 手”，不还原全局交错手序。",
        "版本字段当前为空，不按日期推断版本；时间变化只作时间窗口观察。",
        "所有克制、有效、稳定均为历史关联，不写因果，也不替代教练赛前判断。",
    ]
    if source == "scrim":
        caveats.append("训练赛来自本机营地面板；对手多为占位名，组合样本少时只作单场观察。")
    if not versions:
        caveats.append("当前数据没有版本记录：01 区用“当前窗口”而不是“当前版本”。")

    return {
        "schema": "bp-lab-v1",
        "source": source,
        "scope": {
            "matches": len({g.get("id") for g in games}),
            "teamGames": len(games),
            "focusGames": len(focus_games),
            "teams": teams,
            "from": dates[0] if dates else "",
            "to": dates[-1] if dates else "",
            "versions": versions,
            "versionAvailable": bool(versions),
            "orderedGames": order_games,
            "perSideOrder": source == "kpl",
            "leagues": sorted({str(g.get("league") or "") for g in games if g.get("league")}),
        },
        "options": {
            "teams": teams, "opponents": teams,
            "heroes": sorted({hero for g in games
                              for hero in (_heroes(g.get("picks")) + _heroes(g.get("bans")))}),
            "defaultTeam": default_team, "defaultOpponent": default_opponent,
            "target": target_list, "combo": combo_list,
            "unit": unit, "recentDays": recent_days,
            "recentOptions": [7, 15, 30],
            "units": ["day", "month", "season", "stage"] if source == "kpl" else ["day"],
        },
        "heroes": heroes,
        "combos": combos,
        "teamCounters": team_counters(games, target_list),
        "draftHabits": draft_habits(games, default_opponent),
        "evolution": evolution(focus_games, unit, None),
        "opponent": opponent_dossier(games, default_opponent),
        "opponentResearch": opponent_research(games, default_opponent),
        "scrim": (scrim_systems(games) if source == "scrim"
                  else {"available": False, "reason": "当前为 KPL 数据源；切到训练赛看本队体系。"}),
        "stability": combo_stability(
            focus_games, combo_list, unit,
            available=(combos.get("pairs") or []) + (combos.get("trios") or []),
        ),
        "plan": plan(games, default_team, default_opponent, source=source, rule=rule, bo=bo),
        "caveats": caveats,
    }
