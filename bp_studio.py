"""BP 工作台数据层（2026-11 重做）。

面向教练的 BP 页面只回答四类问题：

1. 版本里哪些英雄、哪几组组合值得先拿（优先级 / 强度 / 趋势）；
2. 对手（KPL 或训练赛对手）在 BP 上做什么，为什么这么做（Ban 意图 / 手序）；
3. 我们要打的目标，KPL 职业队怎么应对，我们自己怎么应对，差在哪；
4. 最近哪些东西在变（体系 / 英雄池异常）。

与 `bp_lab.py` 的分工：`bp_lab` 保留原有“十区”计算与旧接口，本模块在其上补
时间对比（环比 / 同比）、Ban 轮次与拆组合、KPL 与训练赛同题对照，并统一成
一份给新前端使用的页面模型。所有胜率仍然按来源分开算，不混池。

口径约定（与官方赛制一致，页面会原样标注）：

- 每方 Ban 4 手、Pick 5 手；Ban 数组前 2 个属于第一轮 Ban，后 2 个属于第二轮
  Ban。只使用“每方自己的第 N 手”，不还原全局交错手序（官方接口只给每方数组）。
- 拆组合 = 目标组合里恰好一个英雄被对手 Ban 掉；按被 Ban 的那一手落在第几手、
  第几轮统计。
- 相对基准沿用 `bp_lab`：组合胜率 − 所选英雄单英雄收缩胜率的均值，不是因果协同。
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from itertools import combinations
from pathlib import Path
import json

from bp_lab import (
    LANES,
    _combo_label,
    _evidence,
    _heroes,
    _lane_map,
    _pct,
    _sample_label,
    _top,
    _win_rate,
    _wilson,
    combo_detail,
    draft_habits,
    hero_board,
    plan,
)

SCHEMA = "bp-studio-v1"
MAX_DAYS = 3650

SEASON_KINDS = ("春季赛", "夏季赛", "秋季赛", "年度总决赛", "挑战者杯", "冬季冠军杯",
                "世界冠军杯", "其他")

# Ban / Pick 的数组位次 → 轮次。每方 4 Ban、5 Pick，前两 Ban 在第一轮。
BAN_ROUNDS = ((1, 0), (1, 1), (2, 2), (2, 3))


# ---------------------------------------------------------------------------
# 时间与过滤
# ---------------------------------------------------------------------------

def _day(value):
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _dates(games):
    return sorted(str(g.get("date") or "")[:10] for g in games
                  if _day(g.get("date")) is not None)


def _shift_year(day, years):
    try:
        return day.replace(year=day.year + years)
    except ValueError:  # 2 月 29 日
        return day.replace(year=day.year + years, day=28)


def window_bounds(games, *, start="", end="", recent_days=30):
    """当前窗口：显式起止优先；否则以数据最后一天为锚点向前推 N 天。

    用数据锚点而不是本机今天：KPL 数据往往滞后几天，按今天算会把“近 30 天”
    算成空窗（旧页面的「近 30 天 0 局」就是这样来的）。
    """
    dates = _dates(games)
    if not dates:
        return {"from": "", "to": "", "days": 0, "anchor": ""}
    if start and end:
        first, last = start, end
    elif start:
        first, last = start, dates[-1]
    elif end:
        first, last = dates[0], end
    else:
        last = dates[-1]
        anchor = _day(last)
        first = (anchor - timedelta(days=max(1, int(recent_days)) - 1)).isoformat()
    days = 0
    a, b = _day(first), _day(last)
    if a and b:
        days = (b - a).days + 1
    # 窗口不超出数据本身：选了单赛季还要显示“近 365 天”时会从赛季首日算起。
    if dates[0] and first < dates[0]:
        first = dates[0]
    if dates[-1] and last > dates[-1]:
        last = dates[-1]
    a, b = _day(first), _day(last)
    if a and b:
        days = (b - a).days + 1
    return {"from": first, "to": last, "days": days, "anchor": dates[-1]}


def _in_window(games, start, end):
    if not start and not end:
        return list(games)
    out = []
    for g in games:
        day = str(g.get("date") or "")[:10]
        if not day:
            continue
        if start and day < start:
            continue
        if end and day > end:
            continue
        out.append(g)
    return out


def comparison_window(bounds, mode="prev"):
    """返回上一窗口（环比）或去年同期（同比）的起止。"""
    if not bounds.get("from") or not bounds.get("to"):
        return None
    first, last = _day(bounds["from"]), _day(bounds["to"])
    if not first or not last:
        return None
    span = (last - first).days + 1
    if mode == "yoy":
        return {"from": _shift_year(first, -1).isoformat(),
                "to": _shift_year(last, -1).isoformat(), "label": "同比"}
    prev_end = first - timedelta(days=1)
    prev_start = prev_end - timedelta(days=span - 1)
    return {"from": prev_start.isoformat(), "to": prev_end.isoformat(), "label": "环比"}


# ---------------------------------------------------------------------------
# 赛季 / 战队 / 英雄目录
# ---------------------------------------------------------------------------

def _season_kind(name):
    text = str(name or "")
    if "挑战者杯" in text:
        return "挑战者杯"
    if "年度总决赛" in text:
        return "年度总决赛"
    if "世界冠军杯" in text:
        return "世界冠军杯"
    if "冬季冠军杯" in text:
        return "冬季冠军杯"
    for kind in ("春季赛", "夏季赛", "秋季赛"):
        if kind in text:
            return kind
    return "其他"


def _season_order(kind):
    return SEASON_KINDS.index(kind) if kind in SEASON_KINDS else len(SEASON_KINDS)


def league_catalog(raw_games):
    """KPL 赛季目录：按年份分组，年内按赛季类型排序。"""
    buckets = {}
    for game in raw_games or []:
        league_id = str(game.get("leagueId") or "").strip()
        if not league_id:
            continue
        name = str(game.get("leagueName") or "").strip() or league_id
        item = buckets.get(league_id)
        if item is None:
            item = buckets[league_id] = {
                "id": league_id, "name": name,
                "year": int(game.get("year") or 0) or int(league_id[:4] or 0),
                "kind": _season_kind(name), "games": 0,
                "matches": set(), "from": "", "to": "",
            }
        day = str(game.get("date") or "")[:10]
        item["games"] += 1
        item["matches"].add(str(game.get("matchId") or ""))
        if day and (not item["from"] or day < item["from"]):
            item["from"] = day
        if day and (not item["to"] or day > item["to"]):
            item["to"] = day

    rows = []
    for item in buckets.values():
        rows.append({
            "id": item["id"], "name": item["name"], "year": item["year"],
            "kind": item["kind"], "games": item["games"],
            "matches": len({m for m in item["matches"] if m}),
            "from": item["from"], "to": item["to"],
            "short": _short_season(item["name"], item["year"], item["kind"]),
        })
    rows.sort(key=lambda r: (r["year"], _season_order(r["kind"]), r["from"], r["name"]))
    years = []
    for row in rows:
        if not years or years[-1]["year"] != row["year"]:
            years.append({"year": row["year"], "leagues": [], "games": 0, "matches": 0})
        years[-1]["leagues"].append(row)
        years[-1]["games"] += row["games"]
        years[-1]["matches"] += row["matches"]
    for group in years:
        group["kinds"] = [row["kind"] for row in group["leagues"]]
        group["from"] = min((row["from"] for row in group["leagues"] if row["from"]), default="")
        group["to"] = max((row["to"] for row in group["leagues"] if row["to"]), default="")
    return {"leagues": rows, "years": years,
            "kinds": [kind for kind in SEASON_KINDS
                      if any(row["kind"] == kind for row in rows)]}


def _short_season(name, year, kind):
    """列表里用的短名：2024年KPL春季赛 → 24 春；2024年王者荣耀挑战者杯 → 24 挑杯。"""
    if kind == "其他":
        return str(name)
    suffix = {"春季赛": "春", "夏季赛": "夏", "秋季赛": "秋", "年度总决赛": "年总",
              "挑战者杯": "挑杯", "冬季冠军杯": "冬冠", "世界冠军杯": "世冠"}.get(kind, kind)
    return f"{str(year)[2:] if year else '??'} {suffix}"


def team_catalog(raw_games):
    """KPL 战队目录：名称 / 缩写 / 最近一次出现的赛季。"""
    teams = {}
    for game in raw_games or []:
        for key in ("camp1", "camp2"):
            camp = game.get(key) or {}
            name = str(camp.get("team") or "").strip()
            if not name:
                continue
            item = teams.setdefault(name, {
                "name": name, "abbr": str(camp.get("abbr") or "").strip(),
                "teamId": str(camp.get("teamId") or "").strip(),
                "games": 0, "first": "", "last": "",
            })
            item["games"] += 1
            if not item["abbr"] and camp.get("abbr"):
                item["abbr"] = str(camp.get("abbr")).strip()
            day = str(game.get("date") or "")[:10]
            if day and (not item["first"] or day < item["first"]):
                item["first"] = day
            if day and (not item["last"] or day > item["last"]):
                item["last"] = day
    rows = sorted(teams.values(), key=lambda item: (-item["games"], item["name"]))
    return rows


def hero_catalog(games):
    """英雄 → 主分路（按实际出场分路统计；没有分路时用版本默认分路兜底）。"""
    lanes = defaultdict(Counter)
    seen = set()
    for game in games or []:
        lane_of = _lane_map(game.get("players"))
        for hero in _heroes(game.get("picks")):
            seen.add(hero)
            lane = lane_of.get(hero)
            if lane:
                lanes[hero][lane] += 1
    try:
        from hero_archetypes import default_lane
    except Exception:  # pragma: no cover
        default_lane = lambda hero: ""  # noqa: E731
    rows = []
    for hero in sorted(seen):
        counter = lanes.get(hero) or Counter()
        lane = counter.most_common(1)[0][0] if counter else (default_lane(hero) or "")
        rows.append({"name": hero, "lane": lane,
                     "lanes": [{"lane": key, "count": value}
                               for key, value in counter.most_common()]})
    return rows


# ---------------------------------------------------------------------------
# 指标基元
# ---------------------------------------------------------------------------

def _rate_block(records):
    wins, decided, win_rate, interval = _win_rate(records)
    return {"games": len(records), "wins": wins, "decided": decided,
            "winRate": win_rate, "interval": interval}


def _hero_rates(games):
    """一遍扫完：英雄 → Pick/Ban 次数、胜率。"""
    total = len(games)
    picks, bans = Counter(), Counter()
    wins, decided = Counter(), Counter()
    for game in games:
        for hero in _heroes(game.get("picks")):
            picks[hero] += 1
            if game.get("result") is not None:
                decided[hero] += 1
                if game.get("result") is True:
                    wins[hero] += 1
        for hero in _heroes(game.get("bans")):
            bans[hero] += 1
    out = {}
    for hero in set(picks) | set(bans):
        out[hero] = {
            "picks": picks[hero], "bans": bans[hero],
            "pickRate": _pct(picks[hero], total), "banRate": _pct(bans[hero], total),
            "wins": wins[hero], "decided": decided[hero],
            "winRate": _pct(wins[hero], decided[hero]),
            "total": total,
        }
    return out


def _delta(current, previous):
    if current is None or previous is None:
        return None
    return round(current - previous, 1)


def _month_key(day):
    return str(day or "")[:7]


def _month_index(games, limit=10):
    """月份 → 已解析的 Pick/Ban 集合，供英雄榜和组合榜共用，避免重复解析。

    旧写法对每个英雄、每个组合都重新扫一遍对局并重新拆字符串，组合榜 800 多行
    时会把页面拖到十几秒；这里每月只解析一次。
    """
    buckets = defaultdict(list)
    for game in games:
        key = _month_key(game.get("date"))
        if key:
            buckets[key].append(game)
    keys = sorted(buckets)[-limit:]
    index = []
    for key in keys:
        rows = buckets[key]
        index.append({
            "key": key,
            "total": len(rows),
            "picks": [set(_heroes(game.get("picks"))) for game in rows],
            "bans": [set(_heroes(game.get("bans"))) for game in rows],
            "results": [game.get("result") for game in rows],
        })
    return index


def _spark(series, hero):
    out = []
    for row in series:
        total = row["total"] or 1
        picks = sum(1 for item in row["picks"] if hero in item)
        bans = sum(1 for item in row["bans"] if hero in item)
        out.append({"pickRate": round(100 * picks / total, 1),
                    "banRate": round(100 * bans / total, 1)})
    return out


def _combo_spark(series, heroes):
    wanted = set(heroes)
    out = []
    for row in series:
        total = row["total"] or 1
        hit = 0
        wins = decided = 0
        for picks, result in zip(row["picks"], row["results"]):
            if not wanted <= picks:
                continue
            hit += 1
            if result is not None:
                decided += 1
                if result is True:
                    wins += 1
        out.append({"share": round(100 * hit / total, 1),
                    "winRate": round(100 * wins / decided, 1) if decided else None})
    return out


def _combo_counts(games, size):
    """组合 → 局数 / 胜率 / 覆盖战队；同时记录每个英雄被对手 Ban 的次数。"""
    total = len(games)
    games_count, wins, decided = Counter(), Counter(), Counter()
    teams = defaultdict(set)
    banned_parts = Counter()
    for game in games:
        picks = _heroes(game.get("picks"))
        if len(picks) != 5:
            continue
        enemy_bans = set(_heroes(game.get("enemyBans")))
        team = str(game.get("team") or "")
        for combo in combinations(sorted(picks), size):
            games_count[combo] += 1
            if team:
                teams[combo].add(team)
            if game.get("result") is not None:
                decided[combo] += 1
                if game.get("result") is True:
                    wins[combo] += 1
            for hero in combo:
                if hero in enemy_bans:
                    banned_parts[(combo, hero)] += 1
    out = []
    for combo, count in games_count.items():
        if count < 2:
            continue
        w, d = wins[combo], decided[combo]
        out.append({
            "heroes": list(combo), "label": _combo_label(combo),
            "games": count, "share": _pct(count, total),
            "wins": w, "decided": d, "winRate": _pct(w, d),
            "interval": _wilson(w, d),
            "teams": len(teams.get(combo) or ()),
            "banParts": [{"hero": hero, "count": banned_parts.get((combo, hero), 0),
                          "share": _pct(banned_parts.get((combo, hero), 0), count)}
                         for hero in combo],
        })
    return out


def _combo_reference(rows, hero_rates):
    """相对基准：组合胜率 − 各英雄收缩胜率的均值。"""
    for row in rows:
        refs = []
        for hero in row["heroes"]:
            item = hero_rates.get(hero) or {}
            if item.get("decided"):
                refs.append((item["wins"] + 2) / (item["decided"] + 4))
        expected = round(100 * sum(refs) / len(refs), 1) if refs else None
        row["reference"] = expected
        row["relative"] = (round(row["winRate"] - expected, 1)
                           if row["winRate"] is not None and expected is not None
                           and row["decided"] >= 3 else None)
        row["sample"] = _sample_label(row["games"], row["decided"])
    rows.sort(key=lambda r: (-(r["games"] or 0), -(r["relative"] or -999), r["label"]))
    return rows


# ---------------------------------------------------------------------------
# 01 英雄优先级
# ---------------------------------------------------------------------------

def hero_studio(games, *, prev_games=None, yoy_games=None, team="", recent_days=30,
                series=None):
    board = hero_board(games)
    rows = []
    current = _hero_rates(games)
    prev = _hero_rates(prev_games or [])
    yoy = _hero_rates(yoy_games or [])
    sparks = {}
    if series:
        for hero in {row["hero"] for row in board["rows"]}:
            sparks[hero] = _spark(series, hero)
    for row in board["rows"]:
        hero = row["hero"]
        cur = current.get(hero) or {}
        before = prev.get(hero) or {}
        year = yoy.get(hero) or {}
        rows.append({
            **row,
            "prev": {key: before.get(key) for key in
                     ("pickRate", "banRate", "winRate", "picks", "bans")} if before else None,
            "yoy": {key: year.get(key) for key in
                    ("pickRate", "banRate", "winRate", "picks", "bans")} if year else None,
            "delta": {
                "pick": _delta(cur.get("pickRate"), before.get("pickRate")),
                "ban": _delta(cur.get("banRate"), before.get("banRate")),
                "win": _delta(cur.get("winRate"), before.get("winRate")),
                "pickYoy": _delta(cur.get("pickRate"), year.get("pickRate")),
                "banYoy": _delta(cur.get("banRate"), year.get("banRate")),
                "winYoy": _delta(cur.get("winRate"), year.get("winRate")),
            },
            "spark": sparks.get(hero, []),
        })
    # 版本信号：按 Ban 变化和胜率变化排序，只取样本够的
    movers = [row for row in rows if row["decided"] >= 10]
    risers = sorted(movers, key=lambda r: (-(r["delta"]["ban"] or -99),
                                           -(r["delta"]["win"] or -99)))[:5]
    fallers = sorted(movers, key=lambda r: ((r["delta"]["ban"] if r["delta"]["ban"] is not None else 99),
                                            (r["delta"]["win"] if r["delta"]["win"] is not None else 99)))[:5]
    return {
        **board,
        "rows": rows,
        "top": rows[:24],
        "team": team,
        "recentDays": recent_days,
        "movers": {"up": risers, "down": fallers},
        "games": len(games),
    }


# ---------------------------------------------------------------------------
# 02 组合强度
# ---------------------------------------------------------------------------

def combo_studio(games, *, prev_games=None, yoy_games=None, recent_days=30,
                 sizes=(2, 3), series=None):
    hero_rates = _hero_rates(games)
    result = {"minGames": 2, "sizes": list(sizes), "recentDays": recent_days}
    prev_cache, yoy_cache = {}, {}
    for size in sizes:
        rows = _combo_reference(_combo_counts(games, size), hero_rates)
        before = _combo_reference(_combo_counts(prev_games or [], size), _hero_rates(prev_games or []))
        year = _combo_reference(_combo_counts(yoy_games or [], size), _hero_rates(yoy_games or []))
        prev_map = {tuple(row["heroes"]): row for row in before}
        yoy_map = {tuple(row["heroes"]): row for row in year}
        for index, row in enumerate(rows):
            key = tuple(row["heroes"])
            old = prev_map.get(key) or {}
            old_year = yoy_map.get(key) or {}
            row["prevWinRate"] = old.get("winRate")
            row["prevGames"] = old.get("games")
            row["deltaWin"] = _delta(row["winRate"], old.get("winRate"))
            row["deltaGames"] = _delta(row["games"], old.get("games"))
            row["deltaWinYoy"] = _delta(row["winRate"], old_year.get("winRate"))
            if series and index < 70:
                row["spark"] = _combo_spark(series, row["heroes"])
        result["pairs" if size == 2 else f"size{size}"] = rows
        result["pairsBySignal" if size == 2 else f"size{size}BySignal"] = sorted(
            [row for row in rows if row["relative"] is not None],
            key=lambda r: (-(r["relative"] or 0), -(r["games"] or 0)))[:12]
        prev_cache[size] = prev_map
        yoy_cache[size] = yoy_map
    return result


def _combo_spark_series(series, heroes):
    return _combo_spark(series, heroes)


# ---------------------------------------------------------------------------
# 03 目标拆解：Ban 手序 + KPL 应对 vs 本队应对
# ---------------------------------------------------------------------------

def _ban_positions(hero, bans):
    for index, name in enumerate(bans or []):
        if name == hero:
            return index
    return None


def _ban_round(index):
    if index is None:
        return None
    return 1 if index < 2 else 2


def target_break(games, target, *, team="", label=""):
    """目标英雄 / 组合在 BP 里的拆解方式，以及被对手拿到时的应对。

    - completed：目标完整出现在同一方阵容里（组合被放出来）；
    - broken：目标里恰好一个被对手 Ban 掉，另一个仍在该方阵容里（组合被拆）；
    - blocked：目标全部被 Ban（组合直接被掐死）；
    - split：双方各拿到目标的一部分（一人一个）。
    """
    wanted = _heroes(target)
    wanted_set = set(wanted)
    total = len(games)
    if not wanted_set:
        return {"available": False, "reason": "请选择要研究的目标。", "target": []}

    completed = []
    broken = []
    blocked = []
    split = []
    ban_indexes = Counter()
    ban_rounds = Counter()
    ban_teams = Counter()
    answer_heroes = Counter()
    answer_pairs = Counter()
    answer_rows = []
    opponent_rows = []

    for game in games:
        own = set(_heroes(game.get("picks")))
        enemy = set(_heroes(game.get("enemyPicks")))
        own_bans = _heroes(game.get("bans"))
        enemy_bans = _heroes(game.get("enemyBans"))
        if wanted_set <= own:
            completed.append(game)
        elif wanted_set <= enemy:
            opponent_rows.append(game)
        # Ban 记到“发起 Ban 的一方”：我方 Ban 数组 = 我方主动 Ban 对面。
        for hero in wanted:
            index = _ban_positions(hero, own_bans)
            if index is not None:
                ban_indexes[index] += 1
                ban_rounds[_ban_round(index)] += 1
                ban_teams[str(game.get("team") or "")] += 1
        if len(wanted_set & own) == len(wanted_set) - 1:
            missing = wanted_set - own
            if missing & set(enemy_bans):
                broken.append(game)
        elif 0 < len(wanted_set & own) < len(wanted_set) and \
                0 < len(wanted_set & enemy) < len(wanted_set):
            split.append(game)
        if wanted_set <= set(own_bans) | set(enemy_bans):
            blocked.append(game)
        # 对手拿到目标时，我们的应对（盲选同英雄不算应对）
        if wanted_set <= enemy:
            picks = [hero for hero in _heroes(game.get("picks"))
                     if hero not in wanted_set]
            for hero in picks:
                answer_heroes[hero] += 1
            for pair in combinations(sorted(picks), 2):
                answer_pairs[pair] += 1
            answer_rows.append({
                "id": game.get("id"), "date": game.get("date"),
                "team": game.get("team"), "enemy": game.get("enemy"),
                "result": game.get("result"), "picks": picks,
                "enemyPicks": _heroes(game.get("enemyPicks")),
                "side": game.get("side"), "matchId": game.get("matchId"),
                "label": label or _combo_label(wanted),
            })

    answers = []
    decision_rows = [row for row in answer_rows if row["result"] is not None]
    for hero, count in answer_heroes.most_common(12):
        matched = [row for row in answer_rows if hero in row["picks"]]
        wins = sum(1 for row in matched if row["result"] is True)
        decided = sum(1 for row in matched if row["result"] is not None)
        answers.append({"hero": hero, "count": count,
                        "share": _pct(count, len(answer_rows)),
                        "wins": wins, "decided": decided,
                        "winRate": _pct(wins, decided),
                        "interval": _wilson(wins, decided)})
    combo_answers = []
    for pair, count in answer_pairs.most_common(8):
        matched = [row for row in answer_rows if set(pair) <= set(row["picks"])]
        wins = sum(1 for row in matched if row["result"] is True)
        decided = sum(1 for row in matched if row["result"] is not None)
        if count < 3:
            continue
        combo_answers.append({"heroes": list(pair), "label": _combo_label(pair),
                              "count": count, "wins": wins, "decided": decided,
                              "winRate": _pct(wins, decided),
                              "interval": _wilson(wins, decided)})

    completed_rate = _rate_block(completed)
    broken_rate = _rate_block(broken)
    banned_total = sum(ban_indexes.values())
    hands = [{"hand": index + 1, "count": ban_indexes.get(index, 0),
              "share": _pct(ban_indexes.get(index, 0), banned_total),
              "round": _ban_round(index)} for index in range(4)]
    return {
        "available": True, "target": wanted,
        "label": label or _combo_label(wanted), "team": team,
        "games": total,
        "completed": {**completed_rate, "teams": len({g.get("team") for g in completed}),
                      "share": _pct(len(completed), total)},
        "broken": {**broken_rate, "teams": len({g.get("team") for g in broken}),
                   "share": _pct(len(broken), total),
                   "byEnemy": len(broken)},
        "blocked": {"games": len(blocked), "share": _pct(len(blocked), total)},
        "split": {"games": len(split), "share": _pct(len(split), total)},
        "banned": {"games": banned_total, "share": _pct(banned_total, total),
                   "hands": hands,
                   "firstRound": ban_rounds.get(1, 0), "secondRound": ban_rounds.get(2, 0),
                   "firstRoundShare": _pct(ban_rounds.get(1, 0), banned_total),
                   "secondRoundShare": _pct(ban_rounds.get(2, 0), banned_total),
                   "teams": [{"team": key, "count": value}
                             for key, value in ban_teams.most_common(6)]},
        "answers": answers,
        "answerCombos": combo_answers,
        "answerGames": len(answer_rows),
        "answerWinRate": _pct(sum(1 for row in decision_rows if row["result"] is True),
                              len(decision_rows)),
        "answerInterval": _wilson(sum(1 for row in decision_rows if row["result"] is True),
                                  len(decision_rows)),
        "answerTeams": len({row["team"] for row in answer_rows}),
        "evidence": _evidence(answer_rows, 8),
        "sample": _sample_label(len(answer_rows), len(decision_rows)),
        "opponentGames": len(opponent_rows),
    }


def compare_break(kpl_block, own_block, *, kpl_label="KPL", own_label="本队"):
    """KPL 先验 vs 本队现状：应对命中率、Ban 率差、第几手差。"""
    if not kpl_block or not kpl_block.get("available"):
        return {"available": False, "reason": "KPL 侧没有可比较的样本。"}
    kpl_answers = {row["hero"]: row for row in kpl_block.get("answers") or []}
    top_kpl = [row["hero"] for row in (kpl_block.get("answers") or [])[:8]]
    own_block = own_block or {}
    own_answers = {row["hero"]: row for row in own_block.get("answers") or []}
    own_total = sum(row["count"] for row in own_block.get("answers") or []) or 0
    hit_count = sum(row["count"] for hero, row in own_answers.items() if hero in top_kpl)
    rows = []
    for hero in sorted(set(kpl_answers) | set(own_answers),
                       key=lambda name: (-(kpl_answers.get(name, {}).get("count") or 0),
                                         -(own_answers.get(name, {}).get("count") or 0),
                                         name))[:12]:
        kpl_row = kpl_answers.get(hero) or {}
        own_row = own_answers.get(hero) or {}
        rows.append({
            "hero": hero,
            "kplCount": kpl_row.get("count"), "kplShare": kpl_row.get("share"),
            "kplWinRate": kpl_row.get("winRate"),
            "ownCount": own_row.get("count"), "ownShare": own_row.get("share"),
            "ownWinRate": own_row.get("winRate"),
            "inKplTop": hero in top_kpl,
            "deltaShare": _delta(own_row.get("share"), kpl_row.get("share")),
        })
    kpl_ban = (kpl_block.get("banned") or {}).get("share")
    own_ban = ((own_block.get("banned") or {}).get("share")
               if own_block.get("available") else None)
    hands = []
    kpl_hands = (kpl_block.get("banned") or {}).get("hands") or []
    own_hands = ((own_block.get("banned") or {}).get("hands") or []
                 if own_block.get("available") else [])
    for index in range(4):
        kpl_row = kpl_hands[index] if index < len(kpl_hands) else {}
        own_row = own_hands[index] if index < len(own_hands) else {}
        hands.append({"hand": index + 1,
                      "kplShare": kpl_row.get("share"),
                      "ownShare": own_row.get("share"),
                      "kplCount": kpl_row.get("count"),
                      "ownCount": own_row.get("count")})
    missed = [row for row in rows if row["kplCount"] and not row["ownCount"]][:6]
    return {
        "available": True,
        "kplLabel": kpl_label, "ownLabel": own_label,
        "hit": {
            "value": _pct(hit_count, own_total) if own_total else None,
            "ownPicks": own_total, "kplTop": top_kpl,
            "note": "本队应对里落在 KPL 前 8 常用应对中的比例。",
        },
        "ban": {"kplRate": kpl_ban, "ownRate": own_ban,
                "delta": _delta(own_ban, kpl_ban)},
        "breakRate": {"kpl": (kpl_block.get("broken") or {}).get("share"),
                      "own": ((own_block.get("broken") or {}).get("share")
                              if own_block.get("available") else None)},
        "hands": hands,
        "rows": rows,
        "missed": missed,
    }


# ---------------------------------------------------------------------------
# 04 对手 BP 情报
# ---------------------------------------------------------------------------

def _strong_combos(combo_rows, limit=60):
    return {tuple(row["heroes"]): row for row in (combo_rows or [])[:limit]
            if row.get("games", 0) >= 20 and (row.get("winRate") or 0) >= 51}


def _classify_ban(hero, *, enemy_picks, strong, meta_bans, team_bans):
    labels = []
    if strong:
        for combo, row in strong.items():
            if hero in combo and (set(combo) - {hero}) & set(enemy_picks):
                labels.append({
                    "kind": "拆组合",
                    "detail": f"拆 {_combo_label(combo)}（{row['games']} 局 / {row['winRate']}%）",
                    "weight": 3,
                })
                break
    if meta_bans and hero in meta_bans:
        labels.append({"kind": "版本热门", "detail": f"KPL Ban 率第 {meta_bans[hero]}",
                       "weight": 2})
    if team_bans and team_bans.get(hero, 0) >= 3:
        labels.append({"kind": "惯用针对", "detail": f"该队已 Ban {team_bans[hero]} 次",
                       "weight": 1})
    if not labels:
        labels.append({"kind": "常规", "detail": "", "weight": 0})
    labels.sort(key=lambda item: -item["weight"])
    return labels


def opponent_studio(games, team, *, strong=None, meta_bans=None, phase2_window=None):
    """指定对手的 BP 行为：Ban 意图、手序、组合、反制、条件响应。"""
    rows = (list(games) if team == "__all__"
            else [game for game in games if str(game.get("team") or "") == team])
    if not rows:
        return {"available": False, "reason": f"没有找到 {team or '该对手'} 的 BP 记录。",
                "team": team}
    wins, decided, win_rate, interval = _win_rate(rows)
    order_rows = [game for game in rows
                  if game.get("pickOrderKnown") and game.get("bansKnown")
                  and _heroes(game.get("picks"))]
    total = len(rows)

    ban_usage = Counter(hero for game in rows for hero in _heroes(game.get("bans")))
    pick_usage = Counter(hero for game in rows for hero in _heroes(game.get("picks")))
    first_bans = Counter(_heroes(game.get("bans"))[0] for game in order_rows
                         if _heroes(game.get("bans")))
    second_bans = Counter(_heroes(game.get("bans"))[1] for game in order_rows
                          if len(_heroes(game.get("bans"))) > 1)
    first_picks = Counter(_heroes(game.get("picks"))[0] for game in order_rows)
    first_pick_rows = []
    for hero, count in first_picks.most_common(8):
        matched = [game for game in order_rows
                   if _heroes(game.get("picks"))[0] == hero]
        fw, fd, frate, finterval = _win_rate(matched)
        first_pick_rows.append({"hero": hero, "count": count,
                                "share": _pct(count, len(order_rows)),
                                "wins": fw, "decided": fd,
                                "winRate": frate, "interval": finterval})

    intent_rows = []
    for hero, count in first_bans.most_common(8):
        matched = [game for game in order_rows
                   if _heroes(game.get("bans"))[0] == hero]
        fw, fd, frate, finterval = _win_rate(matched)
        labels = []
        for game in matched:
            tags = _classify_ban(hero, enemy_picks=_heroes(game.get("enemyPicks")),
                                 strong=strong, meta_bans=meta_bans,
                                 team_bans=ban_usage)
            for tag in tags:
                if tag["kind"] not in {item["kind"] for item in labels}:
                    labels.append(tag)
        intent_rows.append({"hero": hero, "count": count,
                            "share": _pct(count, len(order_rows)),
                            "wins": fw, "decided": fd, "winRate": frate,
                            "interval": finterval, "intents": labels})

    second_intent_rows = []
    for hero, count in second_bans.most_common(6):
        second_intent_rows.append({
            "hero": hero, "count": count,
            "share": _pct(count, len(order_rows)),
            "intents": _classify_ban(hero, enemy_picks=[],
                                     strong=strong, meta_bans=meta_bans,
                                     team_bans=ban_usage),
        })

    phases = []
    for round_index in (1, 2):
        indexes = (0, 1) if round_index == 1 else (2, 3)
        counter = Counter()
        games_count = 0
        for game in order_rows:
            bans = _heroes(game.get("bans"))
            if len(bans) <= max(indexes):
                continue
            games_count += 1
            for index in indexes:
                counter[bans[index]] += 1
        phases.append({"round": round_index, "games": games_count,
                       "heroes": _top(counter, games_count * len(indexes), 8)})

    hands = []
    for index in range(4):
        counter = Counter()
        games_count = 0
        for game in order_rows:
            bans = _heroes(game.get("bans"))
            if len(bans) > index:
                games_count += 1
                counter[bans[index]] += 1
        hands.append({"hand": index + 1, "games": games_count,
                      "heroes": _top(counter, games_count, 6)})

    # 我们第一手 → 对手同轮的选人 / 第二轮 Ban
    response_map = defaultdict(list)
    for game in order_rows:
        our_first = _heroes(game.get("enemyPicks"))
        if not our_first:
            continue
        response_map[our_first[0]].append(game)
    responses = []
    for hero, matched in response_map.items():
        if len(matched) < 3:
            continue
        next_picks = Counter()
        next_bans = Counter()
        for game in matched:
            for name in _heroes(game.get("picks"))[:2]:
                next_picks[name] += 1
            bans = _heroes(game.get("bans"))
            for name in bans[2:4]:
                next_bans[name] += 1
        responses.append({
            "ourFirst": hero, "games": len(matched),
            "nextPicks": _top(next_picks, len(matched), 3),
            "nextBans": _top(next_bans, len(matched), 3),
        })
    responses.sort(key=lambda row: (-row["games"], row["ourFirst"]))

    # 组合使用（2 / 3 / 4 人）
    hero_rates = _hero_rates(rows)
    combos = {}
    for size in (2, 3, 4):
        board = _combo_reference(_combo_counts(rows, size), hero_rates)
        combos[size] = board[:10]

    hero_usage = []
    for hero, count in pick_usage.most_common(14):
        matched = [game for game in rows if hero in _heroes(game.get("picks"))]
        hw, hd, hrate, hinterval = _win_rate(matched)
        hero_usage.append({"hero": hero, "picks": count,
                           "pickRate": _pct(count, total),
                           "bans": ban_usage.get(hero, 0),
                           "banRate": _pct(ban_usage.get(hero, 0), total),
                           "wins": hw, "decided": hd,
                           "winRate": hrate, "interval": hinterval,
                           "sample": _sample_label(count, hd)})

    # 对手被反制：面对对手时，对方（我们）的选人
    counter_heroes = Counter()
    counter_records = Counter()
    for game in rows:
        for hero in _heroes(game.get("enemyPicks")):
            counter_heroes[hero] += 1
            if game.get("result") is False:
                counter_records[hero] += 1
    counter_rows = []
    for hero, count in counter_heroes.most_common(12):
        decided_here = sum(1 for game in rows if hero in _heroes(game.get("enemyPicks"))
                           and game.get("result") is not None)
        loses = counter_records.get(hero, 0)
        counter_rows.append({"hero": hero, "games": count,
                             "opponentLossRate": _pct(loses, decided_here),
                             "opponentWinRate": _pct(decided_here - loses, decided_here),
                             "interval": _wilson(decided_here - loses, decided_here)})

    # 系列赛调整
    series = {"afterLoss": None, "afterWin": None}
    groups = defaultdict(list)
    for game in rows:
        groups[str(game.get("matchId") or "")].append(game)
    for key in ("loss", "win"):
        bucket = {"games": 0, "wins": 0, "decided": 0, "changed": 0}
        for group in groups.values():
            if len(group) < 2:
                continue
            group.sort(key=lambda g: int(g.get("gameSeq") or 0))
            for before, after in zip(group, group[1:]):
                if before.get("result") is None:
                    continue
                if ("win" if before["result"] else "loss") != key:
                    continue
                bucket["games"] += 1
                if after.get("result") is True:
                    bucket["wins"] += 1
                if after.get("result") is not None:
                    bucket["decided"] += 1
                old = set(_heroes(before.get("bans")))
                new = set(_heroes(after.get("bans")))
                if new - old or old - new:
                    bucket["changed"] += 1
        bucket["winRate"] = _pct(bucket["wins"], bucket["decided"])
        bucket["changeRate"] = _pct(bucket["changed"], bucket["games"])
        series["afterLoss" if key == "loss" else "afterWin"] = bucket

    return {
        "available": True, "team": team, "games": total,
        "wins": wins, "decided": decided, "winRate": win_rate,
        "interval": interval, "orderGames": len(order_rows),
        "firstBans": intent_rows,
        "secondBans": second_intent_rows,
        "firstPicks": first_pick_rows,
        "banPhases": phases,
        "banHands": hands,
        "responses": responses[:8],
        "combos": {str(size): value for size, value in combos.items()},
        "heroes": hero_usage,
        "counters": counter_rows,
        "series": series,
        "sample": _sample_label(total, decided),
        "caveats": [
            "Ban 意图是按同局条件归类的可能解释，一局可多标签，不是教练访谈。",
            "第一手 / 第 N 手 = 该队自己的 Ban / Pick 数组位次，不还原全局交错手序。",
            "条件是“同局共现”，不是严格的因果后续。",
        ],
    }


# ---------------------------------------------------------------------------
# 05 体系与异常
# ---------------------------------------------------------------------------

def _archetype(hero, lane=""):
    try:
        from hero_archetypes import archetype_of, default_lane
        return archetype_of(hero, lane or default_lane(hero))
    except Exception:  # pragma: no cover
        return "未知"


def system_studio(games, *, prev_games=None, team="", enemy=""):
    """体系（英雄定位标签）视角的 Pick / Ban 分布。"""
    def collect(rows):
        picks, bans = Counter(), Counter()
        for game in rows:
            lane_of = _lane_map(game.get("players"))
            for hero in _heroes(game.get("picks")):
                picks[_archetype(hero, lane_of.get(hero, ""))] += 1
            for hero in _heroes(game.get("bans")):
                lane = lane_of.get(hero) or ""
                bans[_archetype(hero, lane)] += 1
        return picks, bans

    total = len(games) or 1
    picks, bans = collect(games)
    prev_picks, prev_bans = collect(prev_games or [])
    prev_total = len(prev_games or []) or 1
    rows = []
    for system in sorted(set(picks) | set(bans) | set(prev_picks) | set(prev_bans)):
        pick_rate = _pct(picks.get(system, 0), total)
        ban_rate = _pct(bans.get(system, 0), total)
        prev_pick_rate = _pct(prev_picks.get(system, 0), prev_total) if prev_games else None
        prev_ban_rate = _pct(prev_bans.get(system, 0), prev_total) if prev_games else None
        rows.append({
            "system": system,
            "picks": picks.get(system, 0), "pickRate": pick_rate,
            "bans": bans.get(system, 0), "banRate": ban_rate,
            "prevPickRate": prev_pick_rate, "prevBanRate": prev_ban_rate,
            "deltaPick": _delta(pick_rate, prev_pick_rate),
            "deltaBan": _delta(ban_rate, prev_ban_rate),
        })
    rows.sort(key=lambda row: (-(row["pickRate"] or 0), row["system"]))

    # 我方 vs 对手：同一体系谁更爱用
    # 未指定本队时按联盟大盘对照对手；指定本队时只看本队自己的记录。
    own_rows = ([game for game in games if str(game.get("team")) == team]
                if team else list(games))
    enemy_rows = ([game for game in games if str(game.get("team")) == enemy]
                  if enemy else [])
    diff = []
    if own_rows and enemy_rows:
        own_picks, own_bans = collect(own_rows)
        enemy_picks, enemy_bans = collect(enemy_rows)
        own_total = len(own_rows) or 1
        enemy_total = len(enemy_rows) or 1
        for system in sorted(set(own_picks) | set(enemy_picks)):
            diff.append({
                "system": system,
                "ownPickRate": _pct(own_picks.get(system, 0), own_total),
                "enemyPickRate": _pct(enemy_picks.get(system, 0), enemy_total),
                "ownBanRate": _pct(own_bans.get(system, 0), own_total),
                "enemyBanRate": _pct(enemy_bans.get(system, 0), enemy_total),
                "deltaPick": _delta(_pct(own_picks.get(system, 0), own_total),
                                    _pct(enemy_picks.get(system, 0), enemy_total)),
            })
        diff.sort(key=lambda row: -(row["ownPickRate"] or 0))
    return {"rows": rows, "diff": diff, "team": team, "enemy": enemy,
            "games": len(games)}


def anomaly_studio(games, prev_games, *, team="", limit=8):
    """本队英雄池的窗口异动：Pick 率 / Ban 率 / 胜率谁在变。"""
    rows = [game for game in games if not team or str(game.get("team")) == team]
    prev_rows = [game for game in prev_games or [] if not team or str(game.get("team")) == team]
    if not rows or not prev_rows:
        return {"available": False, "rows": [],
                "reason": "当前窗口或上一窗口没有样本。"}
    current = _hero_rates(rows)
    before = _hero_rates(prev_rows)
    hero_lane = {}
    for game in rows:
        for hero, lane in _lane_map(game.get("players")).items():
            hero_lane.setdefault(hero, lane)
    out = []
    for hero in set(current) | set(before):
        cur = current.get(hero) or {}
        old = before.get(hero) or {}
        if (cur.get("decided") or 0) < 3 and (old.get("decided") or 0) < 3:
            continue
        dp = _delta(cur.get("pickRate"), old.get("pickRate"))
        db = _delta(cur.get("banRate"), old.get("banRate"))
        dw = _delta(cur.get("winRate"), old.get("winRate"))
        score = max(abs(dp or 0) * 0.8, abs(db or 0) * 0.6, abs(dw or 0))
        if score < 5:
            continue
        kind = "Pick 率" if abs(dp or 0) >= max(abs(db or 0), abs(dw or 0)) else (
            "Ban 率" if abs(db or 0) >= abs(dw or 0) else "胜率")
        out.append({
            "hero": hero, "lane": hero_lane.get(hero, ""), "kind": kind,
            "current": {"picks": cur.get("picks"), "pickRate": cur.get("pickRate"),
                        "bans": cur.get("bans"), "banRate": cur.get("banRate"),
                        "winRate": cur.get("winRate"), "decided": cur.get("decided")},
            "previous": {"picks": old.get("picks"), "pickRate": old.get("pickRate"),
                         "bans": old.get("bans"), "banRate": old.get("banRate"),
                         "winRate": old.get("winRate"), "decided": old.get("decided")},
            "delta": {"pick": dp, "ban": db, "win": dw},
            "score": round(score, 1),
        })
    out.sort(key=lambda row: -row["score"])
    return {"available": bool(out), "rows": out[:limit], "team": team,
            "currentGames": len(rows), "previousGames": len(prev_rows)}


def lineup_diff(own_games, enemy_games, *, size=2, limit=8):
    """阵容差异：双方最常用组合的交集 / 各自独有。"""
    if not own_games or not enemy_games:
        return {"available": False, "shared": [], "onlyUs": [], "onlyThem": []}
    own = {tuple(row["heroes"]): row for row in
           _combo_reference(_combo_counts(own_games, size), _hero_rates(own_games))[:limit]}
    enemy = {tuple(row["heroes"]): row for row in
             _combo_reference(_combo_counts(enemy_games, size), _hero_rates(enemy_games))[:limit]}
    shared = []
    for key in set(own) & set(enemy):
        shared.append({"heroes": list(key), "label": _combo_label(key),
                       "ownGames": own[key]["games"], "enemyGames": enemy[key]["games"],
                       "ownWinRate": own[key]["winRate"],
                       "enemyWinRate": enemy[key]["winRate"]})
    shared.sort(key=lambda row: -(row["ownGames"] + row["enemyGames"]))
    only_us = [{"heroes": row["heroes"], "label": row["label"],
                "games": row["games"], "winRate": row["winRate"]}
               for key, row in own.items() if key not in enemy]
    only_them = [{"heroes": row["heroes"], "label": row["label"],
                  "games": row["games"], "winRate": row["winRate"]}
                 for key, row in enemy.items() if key not in own]
    only_us.sort(key=lambda row: -row["games"])
    only_them.sort(key=lambda row: -row["games"])
    return {"available": True, "size": size, "shared": shared[:limit],
            "onlyUs": only_us[:limit], "onlyThem": only_them[:limit]}


# ---------------------------------------------------------------------------
# 页面模型
# ---------------------------------------------------------------------------

def sequence_board(games, team, action="pick", hand=1, hero=""):
    """第 N 手查询：某队第 N 手 Ban/Pick 了什么、对面同手/下一手怎么接。

    手序口径：只看该队自己的第 N 个 Ban / Pick，不还原全局交错手序。
    """
    action = "ban" if str(action) == "ban" else "pick"
    hand = max(1, int(hand or 1))
    hero = str(hero or "").strip()
    rows = []
    for game in games or []:
        if team and str(game.get("team")) != team:
            continue
        arr = _heroes(game.get("picks") if action == "pick" else game.get("bans"))
        if len(arr) < hand:
            continue
        if hero and arr[hand - 1] != hero:
            continue
        rows.append(game)
    if not rows:
        return {"available": False, "games": 0, "reason": "这个条件下没有对局。",
                "team": team, "action": action, "hand": hand, "hero": hero}
    wins, decided, win_rate, interval = _win_rate(rows)

    def dist(pick_hero):
        counter = Counter()
        for game in rows:
            arr = _heroes(game.get("picks") if action == "pick" else game.get("bans"))
            if not pick_hero and len(arr) >= hand:
                counter[arr[hand - 1]] += 1
        return counter

    own_counter = dist(False)
    enemy_same = Counter()
    enemy_next = Counter()
    enemy_next_type = Counter()
    for game in rows:
        enemy_arr = _heroes(game.get("enemyPicks") if action == "pick" else game.get("enemyBans"))
        if len(enemy_arr) >= hand:
            enemy_same[enemy_arr[hand - 1]] += 1
        if len(enemy_arr) >= hand + 1:
            enemy_next[enemy_arr[hand]] += 1
            lane_of = _lane_map(game.get("enemyPlayers"))
            enemy_next_type[_archetype(enemy_arr[hand], lane_of.get(enemy_arr[hand], ""))] += 1
    total = len(rows)
    return {
        "available": True, "games": total, "wins": wins, "decided": decided,
        "winRate": win_rate, "interval": interval,
        "team": team, "action": action, "hand": hand, "hero": hero,
        "ownAtHand": [{"hero": name, "count": count, "share": _pct(count, total)}
                      for name, count in own_counter.most_common(10)],
        "enemyAtHand": [{"hero": name, "count": count, "share": _pct(count, total)}
                        for name, count in enemy_same.most_common(8)],
        "enemyNext": [{"hero": name, "count": count, "share": _pct(count, total)}
                      for name, count in enemy_next.most_common(8)],
        "enemyNextTypes": [{"type": name, "count": count, "share": _pct(count, total)}
                           for name, count in enemy_next_type.most_common(6)],
        "sample": _sample_label(total, decided),
    }


_RELATION_CACHE = {}


def _relation_fact(name):
    """读取 data/facts 下的关系表，按 mtime 缓存，避免每次请求重读 20MB JSON。"""
    path = Path(__file__).resolve().parent / 'data' / 'facts' / name
    try:
        stat = path.stat()
        key = (name, stat.st_mtime_ns, stat.st_size)
        cached = _RELATION_CACHE.get(key)
        if cached is not None:
            return cached
        data = json.loads(path.read_text(encoding='utf-8'))
        if len(_RELATION_CACHE) > 8:
            _RELATION_CACHE.clear()
        _RELATION_CACHE[key] = data
        return data
    except (OSError, ValueError):
        return {}


def hero_ring(hero, games=None, *, limit=3, min_games=30):
    """英雄关系环：克制 / 被克制（KPL 对位超额胜率）+ 最佳搭档（KPL 同队同局）。"""
    hero = str(hero or '').strip()
    if not hero:
        return {"available": False, "reason": "先选一个英雄。"}
    matchups = _relation_fact('lane_matchups.json').get('pairs') or []
    combos = _relation_fact('kpl_combos.json').get('pairs') or []
    counters, countered = [], []
    for row in matchups:
        a, b = str(row.get('a') or ''), str(row.get('b') or '')
        if hero not in (a, b):
            continue
        n = int(row.get('n') or 0)
        excess = row.get('excess')
        if n < min_games or not isinstance(excess, (int, float)):
            continue
        other = b if a == hero else a
        value = float(excess) if a == hero else -float(excess)
        item = {"hero": other, "n": n, "excess": round(value, 1),
                "winRate": row.get('wr')}
        if value > 0:
            counters.append(item)
        elif value < 0:
            countered.append({**item, "excess": round(-value, 1)})
    counters.sort(key=lambda item: (-item['excess'], -item['n']))
    countered.sort(key=lambda item: (-item['excess'], -item['n']))
    partners = []
    for row in combos:
        heroes = [str(name) for name in row.get('heroes') or []]
        if hero not in heroes:
            continue
        n = int(row.get('n') or 0)
        if n < min_games:
            continue
        other = next((name for name in heroes if name != hero), '')
        if not other:
            continue
        partners.append({"hero": other, "n": n, "winRate": row.get('wr')})
    partners.sort(key=lambda item: (-item['n'], -(item['winRate'] or 0)))
    stats = {"games": 0, "picks": 0, "bans": 0, "wins": 0, "decided": 0,
             "pickRate": None, "banRate": None, "winRate": None}
    for game in games or []:
        picks = _heroes(game.get('picks'))
        bans = _heroes(game.get('bans'))
        stats['games'] += 1
        if hero in picks:
            stats['picks'] += 1
            if isinstance(game.get('result'), bool):
                stats['decided'] += 1
                if game.get('result'):
                    stats['wins'] += 1
        if hero in bans:
            stats['bans'] += 1
    if stats['games']:
        stats['pickRate'] = _pct(stats['picks'], stats['games'])
        stats['banRate'] = _pct(stats['bans'], stats['games'])
    if stats['decided']:
        stats['winRate'] = _pct(stats['wins'], stats['decided'])
    return {
        "available": True, "hero": hero,
        "counters": counters[:limit],
        "counteredBy": countered[:limit],
        "partners": partners[:limit],
        "stats": stats,
        "source": "KPL 历史对位（lane_matchups）",
        "note": f"对位要求 n≥{min_games}；搭档为同队同局，n≥{min_games}。克制是相对英雄强度的超额胜率，不是因果。",
    }


def period_compare(games, cut, days=30, *, limit=10):
    """按日期切分的前后对照：Pick / Ban / 胜率。没有版本字段，不冒充官方版本。"""
    try:
        cut_day = date.fromisoformat(str(cut)[:10])
    except (TypeError, ValueError):
        return {"available": False, "reason": "切分日期格式应为 YYYY-MM-DD。"}
    days = max(7, min(180, int(days or 30)))
    before_start = cut_day - timedelta(days=days)
    after_end = cut_day + timedelta(days=days)
    before, after = [], []
    for game in games or []:
        try:
            day = date.fromisoformat(str(game.get('date') or '')[:10])
        except (TypeError, ValueError):
            continue
        if before_start <= day < cut_day:
            before.append(game)
        elif cut_day <= day < after_end:
            after.append(game)
    if not before or not after:
        return {"available": False,
                "reason": f"切分点前后各 {days} 天没有足够对局。",
                "cut": cut_day.isoformat(), "days": days,
                "beforeGames": len(before), "afterGames": len(after)}

    def summarize(rows):
        picks, bans, wins, decided = Counter(), Counter(), Counter(), Counter()
        for game in rows:
            won = isinstance(game.get('result'), bool)
            for hero in _heroes(game.get('picks')):
                picks[hero] += 1
                if won:
                    decided[hero] += 1
                    if game.get('result'):
                        wins[hero] += 1
            for hero in _heroes(game.get('bans')):
                bans[hero] += 1
        return picks, bans, wins, decided

    b_picks, b_bans, b_wins, b_decided = summarize(before)
    a_picks, a_bans, a_wins, a_decided = summarize(after)
    heroes = set(b_picks) | set(a_picks) | set(b_bans) | set(a_bans)
    rows = []
    for hero in heroes:
        bp, ap = b_picks[hero], a_picks[hero]
        bb, ab = b_bans[hero], a_bans[hero]
        if bp + bb < 10 and ap + ab < 10:
            continue
        b_wr = _pct(b_wins[hero], b_decided[hero]) if b_decided[hero] >= 5 else None
        a_wr = _pct(a_wins[hero], a_decided[hero]) if a_decided[hero] >= 5 else None
        rows.append({
            "hero": hero,
            "before": {"games": len(before), "picks": bp, "bans": bb,
                       "pickRate": _pct(bp, len(before)), "banRate": _pct(bb, len(before)),
                       "winRate": b_wr, "decided": b_decided[hero]},
            "after": {"games": len(after), "picks": ap, "bans": ab,
                      "pickRate": _pct(ap, len(after)), "banRate": _pct(ab, len(after)),
                      "winRate": a_wr, "decided": a_decided[hero]},
            "delta": {"pick": round((_pct(ap, len(after)) or 0) - (_pct(bp, len(before)) or 0), 1),
                      "ban": round((_pct(ab, len(after)) or 0) - (_pct(bb, len(before)) or 0), 1),
                      "win": (round(a_wr - b_wr, 1) if a_wr is not None and b_wr is not None else None)},
        })
    rows.sort(key=lambda row: (-(abs(row['delta']['ban']) + abs(row['delta']['win'] or 0)), row['hero']))
    return {
        "available": True, "cut": cut_day.isoformat(), "days": days,
        "before": {"from": before_start.isoformat(), "to": cut_day.isoformat(),
                   "games": len(before)},
        "after": {"from": cut_day.isoformat(), "to": after_end.isoformat(),
                  "games": len(after)},
        "rows": rows[:limit],
        "note": "数据里没有官方 patch/version 字段，这里按日期切分，不冒充版本对比；只列前后各至少 10 个 Ban/Pick 样本的英雄，胜率只显示前后各至少 5 个胜负样本。",
    }


def draft_tree(games, team="", opponent="", depth=6, branch=3, limit_games=600, side=""):
    """BP 时序分支树：同一前缀合并，分叉按样本数保留前 N。

    只认已核验的 20 手 `events`（order/action/actor/hero）；没有手序的局不参与，
    不按名单顺序补。节点 `actor` 相对所选队伍：team = 我方，enemy = 对方。
    蓝/红方的第一手行动方不同，默认取样本多的一侧，避免把两个视角混进一棵树。
    """
    depth = max(2, min(20, int(depth or 6)))
    branch = max(2, min(5, int(branch or 3)))
    rows = []
    side_counts = Counter()
    total = 0
    for game in games or []:
        if team and str(game.get("team")) != team:
            continue
        if opponent and opponent != "__all__" and str(game.get("enemy")) != opponent:
            continue
        total += 1
        events = game.get("events") or []
        # KPL 早期是 18 手（4 Ban + 10 Pick），训练赛是 20 手；够画到本页深度即可。
        if len(events) < 4:
            continue
        side_counts[str(game.get("side") or "")] += 1
        rows.append(game)
    if not side:
        side = side_counts.most_common(1)[0][0] if side_counts else ""
    if side:
        rows = [game for game in rows if str(game.get("side") or "") == side]
    rows.sort(key=lambda game: str(game.get("date") or ""), reverse=True)
    rows = rows[:max(1, int(limit_games or 600))]
    actual_depth = min(depth, max((len(game.get("events") or []) for game in rows), default=depth))
    depth = max(2, actual_depth)
    if not rows:
        return {"available": False, "games": 0, "ordered": 0, "total": total,
                "reason": "这个条件下没有足够长的已核验手序；先在采集/沙盘补录。",
                "team": team, "opponent": opponent, "depth": depth, "branch": branch,
                "side": side, "sideCounts": dict(side_counts),
                "nodes": [], "main": [], "paths": []}

    nodes = {"0": {"id": "0", "parent": None, "level": 0, "order": 0,
                   "action": "", "actor": "", "hero": "", "count": 0,
                   "wins": 0, "decided": 0}}
    paths = []
    for game in rows:
        won = game.get("result")
        parent = "0"
        hands = []
        for event in sorted(game.get("events") or [],
                            key=lambda item: int(item.get("order") or 0))[:depth]:
            order = int(event.get("order") or 0)
            action = "ban" if event.get("action") == "ban" else "pick"
            actor = "team" if event.get("actor") == "team" else "enemy"
            hero = str(event.get("hero") or "").strip()
            if not hero:
                break
            key = f"{parent}>{order}:{actor}:{action}:{hero}"
            node = nodes.get(key)
            if node is None:
                node = {"id": key, "parent": parent, "level": order, "order": order,
                        "action": action, "actor": actor, "hero": hero,
                        "count": 0, "wins": 0, "decided": 0}
                nodes[key] = node
            node["count"] += 1
            if isinstance(won, bool):
                node["decided"] += 1
                if won:
                    node["wins"] += 1
            hands.append({"order": order, "action": action, "actor": actor, "hero": hero})
            parent = key
        paths.append({"id": game.get("id"), "date": game.get("date"),
                      "enemy": game.get("enemy"), "result": game.get("result"),
                      "hands": hands})

    # 每个父节点只留前 branch 个分叉；其余分支不画，但父节点数字仍是全量。
    children = defaultdict(list)
    for node in nodes.values():
        if node["parent"] is not None:
            children[node["parent"]].append(node)
    keep = {"0"}
    frontier = ["0"]
    while frontier:
        parent = frontier.pop()
        kids = sorted(children.get(parent, []), key=lambda item: (-item["count"], item["hero"]))
        for child in kids[:branch]:
            keep.add(child["id"])
            frontier.append(child["id"])
    kept = [node for node in nodes.values() if node["id"] in keep]
    for node in kept:
        node["share"] = _pct(node["count"], len(rows))
        node["winRate"] = (_pct(node["wins"], node["decided"])
                           if node["decided"] else None)
    # 主路径 = 每一层样本最多的分叉；前端把它画成地铁主线，其余分叉画成支线。
    main = []
    parent = "0"
    for _ in range(depth):
        kids = sorted(children.get(parent, []),
                      key=lambda item: (-item["count"], item["hero"]))
        if not kids:
            break
        best = kids[0]
        main.append(best["id"])
        parent = best["id"]
    # 子节点按层排好，前端不用再猜纵坐标。
    kept.sort(key=lambda item: (item["level"], -item["count"], item["hero"]))
    return {"available": True, "games": len(rows), "ordered": len(rows), "total": total,
            "team": team, "opponent": opponent, "depth": depth, "branch": branch,
            "side": side, "sideCounts": dict(side_counts),
            "nodes": kept, "main": main, "paths": paths[:12],
            "dropped": sum(len(kids) - min(len(kids), branch)
                           for kids in children.values())}



def build_studio(games, *, source="kpl", team="", opponent="", bounds=None,
                 compare="prev", recent_days=30, month_series=None,
                 prev_games=None, yoy_games=None, baseline_games=None,
                 opponent_key="", focus_team=""):
    """把主数据层组装成页面模型（不含目录与目标下钻）。

    `focus_team` 只影响 01/02 的英雄与组合榜：训练赛看本队，KPL 看联盟大盘。
    对手情报始终按对手自己的记录算。
    """
    bounds = bounds or window_bounds(games, recent_days=recent_days)
    current = _in_window(games, bounds["from"], bounds["to"])
    board_games = [game for game in current
                   if not focus_team or str(game.get("team")) == focus_team]
    board_prev = ([game for game in (prev_games or [])
                   if not focus_team or str(game.get("team")) == focus_team]
                  if prev_games is not None else [])
    board_yoy = ([game for game in (yoy_games or [])
                  if not focus_team or str(game.get("team")) == focus_team]
                 if yoy_games is not None else [])
    series = month_series if month_series is not None else _month_index(board_games)
    heroes = hero_studio(board_games, prev_games=board_prev, yoy_games=board_yoy,
                         team=team, recent_days=recent_days, series=series)
    combos = combo_studio(board_games, prev_games=board_prev, yoy_games=board_yoy,
                          recent_days=recent_days, series=series)
    systems = system_studio(current, prev_games=prev_games or [], team=team,
                            enemy=opponent_key or opponent)
    anomalies = anomaly_studio(current, prev_games or [], team=team)
    return {
        "source": source,
        "team": team, "opponent": opponent,
        "window": bounds,
        "games": len(current),
        "boardGames": len(board_games),
        "compareMode": compare,
        "heroes": heroes,
        "combos": combos,
        "systems": systems,
        "anomalies": anomalies,
        "caveats": [
            "KPL 与训练赛各自归一化、各自算胜率，不混池。",
            "版本字段当前为空；时间变化只作观测，不解释成版本强度。",
            "Ban 数组按每方顺序（前 2 手第一轮、后 2 手第二轮），不还原全局交错手序。",
        ],
    }
