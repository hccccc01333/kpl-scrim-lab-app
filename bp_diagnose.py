"""己方英雄诊断：N01–N16。

输入是 bp_intelligence 归一化后的队-局行。所有结论都按“当前窗口 vs 前一个
等长窗口”计算；KPL 没有逐人经济/回放时，N13/N14 显式返回不可用，不编数。
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from itertools import combinations
from math import erf, sqrt

from bp_lab import _combo_label, _heroes, _lane_map, _pct, _sample_label, _win_rate


def _day(value):
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _window(games, start, end):
    return [g for g in games if (d := _day(g.get("date"))) and start <= d <= end]


def _hero_games(rows, hero):
    return [g for g in rows if hero in _heroes(g.get("picks"))]


def _stats(rows):
    wins, decided, rate, interval = _win_rate(rows)
    return {"games": len(rows), "wins": wins, "decided": decided,
            "winRate": rate, "interval": interval,
            "sample": _sample_label(len(rows), decided)}


def _p_value(z):
    return round(2 * (1 - 0.5 * (1 + erf(abs(z) / sqrt(2)))), 4)


def _z_test(wins_a, n_a, wins_b, n_b):
    if not n_a or not n_b:
        return None, None
    p_a, p_b = wins_a / n_a, wins_b / n_b
    pooled = (wins_a + wins_b) / (n_a + n_b)
    se = sqrt(pooled * (1 - pooled) * (1 / n_a + 1 / n_b))
    z = (p_a - p_b) / se if se else None
    return (round(z, 2) if z is not None else None,
            _p_value(z) if z is not None else None)


def _rows_from_bucket(bucket, total):
    rows = []
    for key, records in bucket.items():
        wins, decided, rate, interval = _win_rate(records)
        rows.append({"key": key, "games": len(records), "wins": wins,
                     "decided": decided, "winRate": rate, "interval": interval,
                     "share": _pct(len(records), total),
                     "sample": _sample_label(len(records), decided)})
    rows.sort(key=lambda row: (-(row["games"] or 0), str(row["key"])))
    return rows


def _counter_rows(hero_games, enemy_lineup=None):
    wanted = set(_heroes(enemy_lineup or []))
    bucket = defaultdict(list)
    for g in hero_games:
        enemy = _heroes(g.get("enemyPicks"))
        if wanted and not wanted <= set(enemy):
            continue
        for hero in enemy:
            bucket[hero].append(g)
    rows = _rows_from_bucket(bucket, len(hero_games))
    for row in rows:
        row["hero"] = row.pop("key")
    return rows


def _enemy_combo_rows(hero_games, size=2):
    bucket = defaultdict(list)
    for g in hero_games:
        enemy = _heroes(g.get("enemyPicks"))
        if len(enemy) == 5:
            for combo in combinations(sorted(enemy), size):
                bucket[combo].append(g)
    rows = []
    for combo, records in bucket.items():
        if len(records) < 2:
            continue
        wins, decided, rate, interval = _win_rate(records)
        rows.append({"heroes": list(combo), "label": _combo_label(combo),
                     "games": len(records), "wins": wins, "decided": decided,
                     "winRate": rate, "interval": interval,
                     "sample": _sample_label(len(records), decided)})
    rows.sort(key=lambda row: (-(row["games"] or 0), row["label"]))
    return rows


def _counter_volatility(hero_games, enemy_heroes, limit=5):
    """N04：各敌方英雄按周的我方胜率序列，衡量反制效果是否在波动。"""
    rows = []
    week_starts = sorted({(_day(g.get("date")) - timedelta(days=_day(g.get("date")).weekday())).isoformat()
                          for g in hero_games if _day(g.get("date"))})
    for enemy_hero in enemy_heroes[:limit]:
        series = []
        for week in week_starts:
            d = _day(week)
            end = d + timedelta(days=6)
            subset = [g for g in hero_games
                      if enemy_hero in _heroes(g.get("enemyPicks"))
                      and (gd := _day(g.get("date"))) and d <= gd <= end]
            if not subset:
                continue
            wins, decided, rate, interval = _win_rate(subset)
            if decided:
                series.append({"weekStart": d.isoformat(), "games": len(subset),
                               "decided": decided, "winRate": rate,
                               "interval": interval})
        rates = [item["winRate"] for item in series if item["winRate"] is not None]
        rows.append({"hero": enemy_hero, "weeks": len(series),
                     "range": round(max(rates) - min(rates), 1) if len(rates) >= 2 else None,
                     "series": series[-8:]})
    return rows


def _lane_opponents(hero_games, hero):
    lane_counter = Counter()
    for g in hero_games:
        lane = _lane_map(g.get("players")).get(hero)
        if lane:
            lane_counter[lane] += 1
    hero_lane = lane_counter.most_common(1)[0][0] if lane_counter else ""
    if not hero_lane:
        return {"lane": "", "available": False,
                "reason": "该英雄没有可定位的分路记录。", "heroes": []}
    bucket = defaultdict(list)
    for g in hero_games:
        for player in g.get("enemyPlayers") or []:
            if player.get("lane") == hero_lane and player.get("hero"):
                bucket[player["hero"]].append(g)
    rows = _rows_from_bucket(bucket, len(hero_games))
    for row in rows:
        row["hero"] = row.pop("key")
    return {"lane": hero_lane, "available": True, "heroes": rows[:10]}


def _partner_rows(hero_games, hero):
    bucket = defaultdict(list)
    for g in hero_games:
        for partner in _heroes(g.get("picks")):
            if partner != hero:
                bucket[partner].append(g)
    rows = _rows_from_bucket(bucket, len(hero_games))
    for row in rows:
        row["hero"] = row.pop("key")
    return rows


def _player_rows(hero_games, hero):
    bucket = defaultdict(list)
    for g in hero_games:
        for player in g.get("players") or []:
            if player.get("hero") == hero and player.get("name"):
                bucket[(player["name"], player.get("lane") or "")].append(g)
    rows = _rows_from_bucket(bucket, len(hero_games))
    for row in rows:
        name, lane = row.pop("key")
        row["player"], row["lane"] = name, lane
    return rows


def _context_rows(hero_games, all_rows=None):
    def rows(key):
        bucket = defaultdict(list)
        for g in hero_games:
            bucket[str(g.get(key) or "未记录")].append(g)
        out = _rows_from_bucket(bucket, len(hero_games))
        if key == "enemy" and all_rows is not None:
            overall = defaultdict(list)
            for g in all_rows:
                overall[str(g.get("team") or "未记录")].append(g)
            for row in out:
                records = overall.get(row["key"]) or []
                wins, decided, rate, interval = _win_rate(records)
                row["opponentGames"] = len(records)
                row["opponentWinRate"] = rate
                row["opponentInterval"] = interval
        return out
    return {"opponents": rows("enemy"), "sides": rows("side"),
            "leagues": rows("league")}


def _performance(rows, hero):
    """N13：只在有逐人统计的营地数据上计算。"""
    fields = {"kills": [], "assists": [], "deaths": [], "gold": [],
              "heroDamage": [], "taken": [], "participation": [], "towers": []}
    stat_games = set()
    for g in rows:
        for player in g.get("players") or []:
            if player.get("hero") != hero:
                continue
            for key in fields:
                value = player.get(key)
                if isinstance(value, (int, float)):
                    # 营地 joinGamePercent 是 0–1 的小数；页面统一按百分比点展示。
                    if key == "participation" and 0 <= value <= 1:
                        value *= 100
                    fields[key].append(value)
                    stat_games.add(g.get("id") or id(g))
    if not any(fields[key] for key in ("gold", "heroDamage", "deaths", "kills")):
        return {"available": False, "reason": "当前来源没有逐人经济/KDA/输出统计。",
                "metrics": {}}

    def mean(values):
        return round(sum(values) / len(values), 1) if values else None

    deaths = mean(fields["deaths"]) or 0
    kills, assists = mean(fields["kills"]), mean(fields["assists"])
    return {"available": True, "games": len(stat_games),
            "metrics": {
                "kda": (round(((kills or 0) + (assists or 0)) / deaths, 2)
                        if deaths else None),
                "kills": kills, "assists": assists, "deaths": mean(fields["deaths"]),
                "gold": mean(fields["gold"]), "heroDamage": mean(fields["heroDamage"]),
                "taken": mean(fields["taken"]),
                "participation": mean(fields["participation"]),
                "towers": mean(fields["towers"])},
            "note": "按该英雄对应选手的逐局统计取均值；KPL 没有逐人统计。"}


def _tempo(rows):
    """N14：只做已有回放匹配的队级经济检查点；团战/资源控制需要事件。"""
    checkpoints = ("120", "240", "600")
    collected = {stamp: [] for stamp in checkpoints}
    for g in rows:
        diff = g.get("teamGoldDiff") or {}
        for stamp in checkpoints:
            value = diff.get(stamp)
            if isinstance(value, (int, float)):
                collected[stamp].append(value)
    if not any(collected.values()):
        return {"available": False,
                "reason": "该批对局没有匹配到官方回放经济曲线；团战与资源控制需要事件数据。",
                "checkpoints": {}}

    def mean(values):
        return round(sum(values) / len(values), 1) if values else None

    return {"available": True,
            "checkpoints": {stamp: {"games": len(values), "avgGoldDiff": mean(values)}
                            for stamp, values in collected.items()},
            "note": "队级经济差；正数表示本队领先。团战与资源控制仍需回放事件。"}


def _lineup_row(g):
    return {"date": g.get("date"), "opponent": g.get("enemy"),
            "side": g.get("side"), "result": g.get("result"),
            "own": _heroes(g.get("picks")),
            "enemy": _heroes(g.get("enemyPicks"))}


def _lineup_periods(hero_rows, limit=8):
    buckets = defaultdict(list)
    for g in hero_rows:
        d = _day(g.get("date"))
        if d:
            buckets[d.strftime("%Y-%m")].append(g)
    periods = []
    for key in sorted(buckets, reverse=True)[:limit]:
        rows = sorted(buckets[key], key=lambda g: str(g.get("date") or ""), reverse=True)
        periods.append({"period": key, "games": len(rows),
                        "lineups": [_lineup_row(g) for g in rows[:6]]})
    return periods


def _share_delta(share, old, previous_available):
    """前窗有同英雄记录时，缺席按 0% 计；前窗整体为空则不做变化。"""
    if not previous_available or share is None:
        return None
    old_share = old.get("share") if old else 0
    return round(share - (old_share or 0), 1)


def default_hero(games, *, team="", recent_days=30, start="", end=""):
    """默认诊断英雄：优先当前窗口出场最多，窗口为空再退回全期。"""
    rows = [g for g in games if not team or str(g.get("team") or "") == team]
    days = [d for d in (_day(g.get("date")) for g in rows) if d]
    if not days:
        return ""
    end_day = min(_day(end) or max(days), max(days))
    start_day = _day(start) or (end_day - timedelta(days=max(1, int(recent_days or 30) - 1)))
    if start_day > end_day:
        start_day, end_day = end_day, start_day
    for pool in (_window(rows, start_day, end_day), rows):
        counts = Counter(h for g in pool for h in _heroes(g.get("picks")))
        if counts:
            return counts.most_common(1)[0][0]
    return ""


def build_diagnosis(games, *, team="", hero="", recent_days=30,
                    start="", end="", enemy_lineup=None, source=""):
    all_rows = list(games or [])
    rows = [g for g in all_rows if not team or str(g.get("team") or "") == team]
    if not hero:
        return {"available": False, "reason": "请选择一个英雄。",
                "hero": hero, "team": team}
    days = [d for d in (_day(g.get("date")) for g in rows) if d]
    if not days:
        return {"available": False, "reason": "当前范围没有日期记录。",
                "hero": hero, "team": team}
    max_day = max(days)
    end_day = min(_day(end) or max_day, max_day)
    start_day = _day(start) or (end_day - timedelta(days=max(1, int(recent_days or 30) - 1)))
    if start_day > end_day:
        start_day, end_day = end_day, start_day
    span = (end_day - start_day).days + 1
    prev_end = start_day - timedelta(days=1)
    prev_start = prev_end - timedelta(days=span - 1)
    current_rows = _window(rows, start_day, end_day)
    previous_rows = _window(rows, prev_start, prev_end)
    current_hero = _hero_games(current_rows, hero)
    previous_hero = _hero_games(previous_rows, hero)
    all_hero = _hero_games(rows, hero)
    current_stats = _stats(current_hero)
    previous_stats = _stats(previous_hero)
    total_stats = _stats(all_hero)

    # N03：近 7/15/30 天 + 周趋势
    trend = []
    for days_window in (7, 15, 30):
        a = end_day - timedelta(days=days_window - 1)
        prev = _stats(_hero_games(_window(rows, a - timedelta(days=days_window),
                                          a - timedelta(days=1)), hero))
        current = _stats(_hero_games(_window(rows, a, end_day), hero))
        trend.append({"days": days_window, "start": a.isoformat(),
                      "end": end_day.isoformat(), **current,
                      "previousWinRate": prev["winRate"],
                      "delta": (round(current["winRate"] - prev["winRate"], 1)
                                if current["winRate"] is not None
                                and prev["winRate"] is not None else None)})
    weeks = defaultdict(list)
    for g in all_hero:
        d = _day(g.get("date"))
        if d:
            weeks[d.isocalendar()[:2]].append(g)
    weekly = []
    last_rate = None
    for (year, week), records in sorted(weeks.items())[-10:]:
        wins, decided, rate, interval = _win_rate(records)
        weekly.append({"key": f"{year}-W{week:02d}", "games": len(records),
                       "wins": wins, "decided": decided, "winRate": rate,
                       "interval": interval,
                       "delta": (round(rate - last_rate, 1)
                                 if rate is not None and last_rate is not None else None)})
        last_rate = rate if rate is not None else last_rate

    # N05/N06：异常与显著性
    baseline = previous_hero
    if len(previous_hero) < 3 and len(all_hero) > len(current_hero):
        baseline = [g for g in all_hero
                    if _day(g.get("date")) and _day(g.get("date")) < start_day]
    b_w, b_d, b_rate, b_interval = _win_rate(baseline)
    c_w, c_d, c_rate, c_interval = _win_rate(current_hero)
    z, p = _z_test(c_w, c_d, b_w, b_d)
    drop = (round(c_rate - b_rate, 1)
            if c_rate is not None and b_rate is not None else None)
    baseline_stats = _stats(baseline)
    baseline_scope = "previous" if baseline is previous_hero else "history"
    baseline_days = sorted(d.isoformat() for d in
                           (_day(g.get("date")) for g in baseline) if d)
    baseline_start = baseline_days[0] if baseline_days else prev_start.isoformat()
    baseline_end = baseline_days[-1] if baseline_days else prev_end.isoformat()
    weekly_rates = [row["winRate"] for row in weekly if row["winRate"] is not None]
    volatility = (round(max(weekly_rates) - min(weekly_rates), 1)
                  if len(weekly_rates) >= 2 else None)
    significant = bool(p is not None and p < 0.05 and (drop or 0) <= -10
                       and c_d >= 5)
    severity = ("未触发" if not significant else
                "高" if (drop or 0) <= -30 else
                "中" if (drop or 0) <= -15 else "低")
    anomaly = {
        "current": {"start": start_day.isoformat(), "end": end_day.isoformat(),
                    **current_stats},
        "baseline": {"start": baseline_start, "end": baseline_end,
                     "scope": baseline_scope, **baseline_stats},
        "drop": drop, "z": z, "pValue": p, "significant": significant,
        "severity": severity, "volatility": volatility,
        "verdict": ("显著下降" if significant else "未达到显著下降"),
        "caveats": ["显著性用两比例 z 检验；低于 5 局不做结论。",
                    "历史波动为周胜率极差；它只帮助判断幅度，不替代样本门槛。"],
    }

    # N07/N08/N09/N10/N11：定位
    partner_current = _partner_rows(current_hero, hero)
    partner_previous = _partner_rows(previous_hero, hero)
    partner_map = {row["hero"]: row for row in partner_previous}
    partner_diff = []
    for row in partner_current[:8]:
        old = partner_map.get(row["hero"]) or {}
        partner_diff.append({**row, "previousShare": old.get("share", 0) if previous_hero else None,
                             "shareDelta": _share_delta(row.get("share"), old,
                                                        bool(previous_hero))})
    enemy_current = _counter_rows(current_hero)
    enemy_previous = _counter_rows(previous_hero)
    wanted = set(_heroes(enemy_lineup or []))
    lineup_current = [g for g in current_hero
                      if wanted and wanted <= set(_heroes(g.get("enemyPicks")))]
    lineup_previous = [g for g in previous_hero
                       if wanted and wanted <= set(_heroes(g.get("enemyPicks")))]

    enemy_prev_map = {row["hero"]: row for row in enemy_previous}
    enemy_diff = []
    for row in enemy_current[:8]:
        old = enemy_prev_map.get(row["hero"]) or {}
        enemy_diff.append({**row, "previousShare": old.get("share", 0) if previous_hero else None,
                           "shareDelta": _share_delta(row.get("share"), old,
                                                      bool(previous_hero)),
                           "previousWinRate": old.get("winRate"),
                           "winDelta": (round(row["winRate"] - old["winRate"], 1)
                                        if row.get("winRate") is not None and old.get("winRate") is not None else None)})
    lane_current = _lane_opponents(current_hero, hero)
    lane_previous = _lane_opponents(previous_hero, hero)
    lane_prev_map = {row["hero"]: row for row in lane_previous.get("heroes", [])}
    lane_diff = []
    for row in lane_current.get("heroes", [])[:8]:
        old = lane_prev_map.get(row["hero"]) or {}
        lane_diff.append({**row, "previousShare": old.get("share", 0) if previous_hero else None,
                          "shareDelta": _share_delta(row.get("share"), old,
                                                     bool(previous_hero)),
                          "previousWinRate": old.get("winRate"),
                          "winDelta": (round(row["winRate"] - old["winRate"], 1)
                                       if row.get("winRate") is not None and old.get("winRate") is not None else None)})
    players_current = _player_rows(current_hero, hero)
    players_previous = _player_rows(previous_hero, hero)
    player_prev_map = {(row["player"], row["lane"]): row for row in players_previous}
    player_diff = []
    for row in players_current:
        old = player_prev_map.get((row["player"], row["lane"])) or {}
        player_diff.append({**row, "previousShare": old.get("share", 0) if previous_hero else None,
                            "shareDelta": _share_delta(row.get("share"), old,
                                                       bool(previous_hero))})
    context_current = _context_rows(current_hero, all_rows)
    context_previous = _context_rows(previous_hero, all_rows)

    # N12：把搭档/敌方变化与胜率变化并列，只做关联
    associations = []
    shared_factors = ({row["hero"] for row in partner_current}
                      | {row["hero"] for row in enemy_current}) & (
                     {row["hero"] for row in partner_previous}
                     | {row["hero"] for row in enemy_previous})
    association_available = len(previous_hero) >= 5 and bool(shared_factors)
    if association_available:
        for label, rows_now, rows_before in (("搭档", partner_current, partner_previous),
                                             ("敌方英雄", enemy_current, enemy_previous)):
            before_map = {row["hero"]: row for row in rows_before}
            for row in rows_now[:6]:
                old = before_map.get(row["hero"]) or {}
                share_delta = (round(row["share"] - old["share"], 1)
                               if row.get("share") is not None and old.get("share") is not None
                               else None)
                if share_delta is None:
                    share_delta = round(
                        row.get("games", 0) / max(1, len(current_hero)) * 100
                        - old.get("games", 0) / max(1, len(previous_hero)) * 100, 1)
                win_delta = (round(row["winRate"] - old["winRate"], 1)
                             if row.get("winRate") is not None and old.get("winRate") is not None else None)
                associations.append({"kind": label, "object": row["hero"],
                                     "currentGames": row["games"], "previousGames": old.get("games"),
                                     "shareDelta": share_delta,
                                     "currentWinRate": row.get("winRate"),
                                     "previousWinRate": old.get("winRate"),
                                     "winDelta": win_delta})
        associations.sort(key=lambda row: (-(abs(row["shareDelta"] or 0)), row["object"]))

    performance_current = _performance(current_hero, hero)
    performance_previous = _performance(previous_hero, hero)
    perf_diff = {}
    if performance_current.get("available") and performance_previous.get("available"):
        for key, value in performance_current["metrics"].items():
            old = performance_previous["metrics"].get(key)
            perf_diff[key] = (round(value - old, 2)
                              if isinstance(value, (int, float)) and isinstance(old, (int, float))
                              else None)

    current_sorted = sorted(current_hero, key=lambda g: str(g.get("date") or ""), reverse=True)
    previous_sorted = sorted(previous_hero, key=lambda g: str(g.get("date") or ""), reverse=True)
    lineups = {
        "current": [_lineup_row(g) for g in current_sorted[:12]],
        "previous": [_lineup_row(g) for g in previous_sorted[:12]],
    }
    partner_sets = {"current": {row["hero"] for row in partner_current},
                    "previous": {row["hero"] for row in partner_previous}}
    enemy_sets = {"current": {row["hero"] for row in enemy_current},
                  "previous": {row["hero"] for row in enemy_previous}}
    lane_sets = {"current": {row["hero"] for row in lane_current.get("heroes", [])},
                 "previous": {row["hero"] for row in lane_previous.get("heroes", [])}}
    diff_available = bool(current_hero) and len(previous_hero) >= 5
    if diff_available:
        diff = {
            "available": True,
            "partner": {"added": sorted(partner_sets["current"] - partner_sets["previous"]),
                        "removed": sorted(partner_sets["previous"] - partner_sets["current"]),
                        "common": sorted(partner_sets["current"] & partner_sets["previous"])},
            "enemy": {"added": sorted(enemy_sets["current"] - enemy_sets["previous"]),
                      "removed": sorted(enemy_sets["previous"] - enemy_sets["current"]),
                      "common": sorted(enemy_sets["current"] & enemy_sets["previous"])},
            "lane": {"added": sorted(lane_sets["current"] - lane_sets["previous"]),
                     "removed": sorted(lane_sets["previous"] - lane_sets["current"]),
                     "common": sorted(lane_sets["current"] & lane_sets["previous"])},
        }
    else:
        empty_diff = {"added": [], "removed": [], "common": []}
        reason = ("当前窗口没有使用该英雄，无法识别阵容差异。"
                  if not current_hero else
                  f"前窗仅 {len(previous_hero)} 局同英雄记录，不足 5 局，不做新增 / 消失判断。")
        diff = {"available": False, "previousGames": len(previous_hero),
                "reason": reason,
                "partner": empty_diff, "enemy": dict(empty_diff), "lane": dict(empty_diff)}
    return {
        "available": True, "team": team, "hero": hero,
        "source": source or ("scrim" if any(g.get("source") == "scrim" for g in rows) else "kpl"),
        "period": {"start": start_day.isoformat(), "end": end_day.isoformat(),
                   "previousStart": prev_start.isoformat(),
                   "previousEnd": prev_end.isoformat(), "recentDays": recent_days},
        "heroGames": {"current": len(current_hero), "previous": len(previous_hero),
                      "total": len(all_hero)},
        "compareAvailable": bool(previous_hero),
        "performance": {"current": current_stats, "previous": previous_stats,
                        "total": total_stats, "trend": trend, "weekly": weekly},
        "counters": {"current": enemy_current[:10], "previous": enemy_previous[:10],
                     "enemyCombos": _enemy_combo_rows(current_hero)[:8],
                     "enemyLineup": {"heroes": sorted(wanted),
                                     "current": _stats(lineup_current),
                                     "previous": _stats(lineup_previous)},
                     "volatility": _counter_volatility(current_hero, [r["hero"] for r in enemy_current])},
        "anomaly": anomaly,
        "locate": {"partners": partner_diff, "enemyHeroes": enemy_diff,
                   "laneOpponents": {**lane_current, "heroes": lane_diff},
                   "players": player_diff,
                   "context": {"current": context_current, "previous": context_previous}},
        "associations": associations[:10],
        "associationAvailable": association_available,
        "associationReason": ("" if association_available else
                              (f"前窗仅 {len(previous_hero)} 局同英雄记录，不足 5 局，不做阵容关联。"
                               if len(previous_hero) < 5 else
                               "前窗与当前没有相同的搭档 / 敌方英雄，无法做前后关联。")),
        "performanceStats": {"current": performance_current,
                             "previous": performance_previous, "delta": perf_diff},
        "tempo": {"current": _tempo(current_hero), "previous": _tempo(previous_hero)},
        "lineups": lineups,
        "lineupPeriods": _lineup_periods(all_hero),
        "diff": diff,
        "caveats": [
            "N01–N02：按本队视角统计；KPL 与训练赛不混算。",
            "N03：7/15/30 天窗口都截至当前结束日，周趋势按自然周分桶。",
            "N04：反制波动按周胜率极差；每周至少 1 局才进入序列。",
            "N05–N06：显著下降需要当前≥5局且 p<0.05；否则只作观察。",
            "N07–N11：比较当前窗口与前一个等长窗口；对手/选手缺失时留空。",
            "N12：搭档/敌方变化只做历史关联，不写成因果。",
            "N13–N14：KPL 无逐人经济和回放事件；训练赛也只在有营地统计/回放匹配时可用。",
            "N15–N16：阵容明细按时间倒序；差异是集合差异，不代表战术优劣。",
        ],
    }
