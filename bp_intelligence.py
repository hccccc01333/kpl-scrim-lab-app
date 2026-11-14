"""BP 研究：真实选禁事件、阵容协同、选手英雄与周期变化。

数据源独立分析：训练赛与 KPL 比赛绝不混合胜率；不把相关性写成克制/因果。
本模块是纯计算：输入可复现的事实行，输出附比赛依据的教练可读结果。
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from itertools import combinations
from math import sqrt


def _hero(value):
    if isinstance(value, dict):
        return str(value.get("name") or value.get("hero") or "").strip()
    return str(value or "").strip()


def _heroes(items):
    return list(dict.fromkeys(h for h in (_hero(x) for x in (items or [])) if h))


def _period(value):
    return str(value or "")[:10]


def _percent(num, den):
    return round(num * 100 / den, 1) if den else None


def _wilson(wins, total):
    """Wilson 95% interval; small-sample zero and perfect records remain uncertain."""
    if not total:
        return [None, None]
    p, z = wins / total, 1.96
    d = 1 + z * z / total
    center = (p + z * z / (2 * total)) / d
    radius = z * sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / d
    return [round(100 * max(0, center - radius), 1),
            round(100 * min(1, center + radius), 1)]


def _normalize_events(raw, side):
    """Keep only observed, ordered actions. Never reconstruct order from final lineups."""
    events = []
    if not isinstance(raw, list):
        return events
    for idx, entry in enumerate(raw):
        if not isinstance(entry, dict):
            continue
        action = str(entry.get("action") or entry.get("type") or "").lower()
        hero = _hero(entry.get("hero") or entry.get("heroName") or entry.get("name"))
        camp = str(entry.get("camp") or entry.get("side") or "").lower()
        camp = {"left": "1", "blue": "1", "right": "2", "red": "2"}.get(camp, camp)
        if action not in ("pick", "ban") or camp not in ("1", "2") or not hero:
            continue
        try:
            order = int(entry.get("order", idx + 1))
        except (TypeError, ValueError):
            continue
        if order <= 0:
            continue
        events.append({"order": order, "action": action, "hero": hero,
                       "actor": "team" if camp == side else "enemy"})
    orders = [e["order"] for e in events]
    if len(set(orders)) != len(orders):
        return []
    return sorted(events, key=lambda e: e["order"])


def _checked_events(raw, side, picks, bans, enemy_picks, enemy_bans):
    """Reject partial/inconsistent draft data instead of inferring the missing actions."""
    events = _normalize_events(raw, side)
    if not events:
        return []
    expected = {
        ("team", "pick"): sorted(picks),
        ("team", "ban"): sorted(bans),
        ("enemy", "pick"): sorted(enemy_picks),
        ("enemy", "ban"): sorted(enemy_bans),
    }
    for (actor, action), heroes in expected.items():
        observed = sorted(e["hero"] for e in events
                          if e["actor"] == actor and e["action"] == action)
        if observed != heroes:
            return []
    return events


def normalize_kpl(raw_games):
    """Each match has two perspectives. A team record is never silently renamed."""
    games = []
    for item in raw_games or []:
        if not isinstance(item, dict):
            continue
        identity = str(item.get("battleId") or "").strip()
        if not identity:
            continue
        for side, opposite in (("1", "2"), ("2", "1")):
            team = str((item.get("camp" + side) or {}).get("team") or "").strip()
            foe = str((item.get("camp" + opposite) or {}).get("team") or "").strip()
            if not team:
                continue
            picks = _heroes((item.get("picks") or {}).get(side))
            bans = _heroes((item.get("bans") or {}).get(side))
            enemy_picks = _heroes((item.get("picks") or {}).get(opposite))
            enemy_bans = _heroes((item.get("bans") or {}).get(opposite))
            players = []
            for entry in (item.get("players") or {}).get(side, []):
                if not isinstance(entry, dict):
                    continue
                hero, name = _hero(entry.get("hero")), str(entry.get("player") or "").strip()
                if hero and name and hero in picks:
                    players.append({"name": name, "hero": hero,
                                    "lane": str(entry.get("position") or "")})
            enemy_players = []
            for entry in (item.get("players") or {}).get(opposite, []):
                if not isinstance(entry, dict):
                    continue
                h, name = _hero(entry.get("hero")), str(entry.get("player") or "").strip()
                if h and name and h in enemy_picks:
                    enemy_players.append({"name": name, "hero": h,
                                          "lane": str(entry.get("position") or "")})
            ordered = bool(item.get("pickOrderKnown") and item.get("bansKnown"))
            events = (_checked_events(item.get("draftEvents"), side, picks, bans,
                                     enemy_picks, enemy_bans) if ordered else [])
            winner = str(item.get("winCamp") or "")
            games.append({"id": identity, "date": _period(item.get("date") or item.get("startTime")),
                          "team": team, "enemy": foe, "side": side,
                          "picks": picks, "bans": bans, "enemyPicks": enemy_picks,
                          "enemyBans": enemy_bans, "players": players, "enemyPlayers": enemy_players,
                          "result": (winner == side) if winner in ("1", "2") else None,
                          "events": events, "source": "kpl", "matchId": str(item.get("matchId") or ""),
                          "league": str(item.get("leagueName") or ""),
                          "version": str(item.get("version") or item.get("gameVersion") or "").strip(),
                          "stage": str(item.get("stage") or "").strip(),
                          # KPL: the event sequence is historical evidence only.
                          # Never apply the user's scrim 18-step schedule here.
                          "ruleProfile": "kpl-recorded",
                          "ruleValidated": False,
                          "gameSeq": item.get("gameSeq")})
    return games


def _scrim_players(row, side, picks):
    """Only match a player to a hero when the game record explicitly says which."""
    info = (row.get("roster") or {}).get(side) or []
    players = []
    for entry in info:
        if not isinstance(entry, dict):
            continue
        name, hero = str(entry.get("name") or "").strip(), _hero(entry.get("hero"))
        if name and hero and hero in picks:
            players.append({"name": name, "hero": hero, "lane": str(entry.get("lane") or ""),
                            "gold": entry.get("gold"), "heroDamage": entry.get("heroDamage"),
                            "deaths": entry.get("deaths"), "participation": entry.get("participation")})
    return players


def normalize_scrims(raw_games, process_map=None):
    games = []
    for item in raw_games or []:
        if not isinstance(item, dict):
            continue
        identity = str(item.get("key") or "").strip()
        if not identity:
            continue
        picks = item.get("picks") or {}
        bans = item.get("bans") or {}
        source_events = item.get("draftEvents") or []
        process = (process_map or {}).get(identity) or {}
        perspective = [("own", "enemy", "本队", str(item.get("opponent") or "").strip()),
                       ("enemy", "own", str(item.get("opponent") or "").strip(), "本队")]
        for side, other, team, foe in perspective:
            if not team or team == "未归属对手":
                continue
            own_picks, own_bans = _heroes(picks.get(side)), _heroes(bans.get(side))
            enemy_picks = _heroes(picks.get(other))
            if len(own_picks) != 5 or len(enemy_picks) != 5:
                continue
            # Scrim event contract: actual ordered events must carry camp 1/2.
            camp = "1" if ((side == "own") == (item.get("ownSide") == "left")) else "2"
            events = _checked_events(source_events, camp, own_picks, own_bans,
                                     enemy_picks, _heroes(bans.get(other)))
            from bp_rules import SCRIM_GLOBAL_15, validate_scrim_prefix
            # Absolute camp (blue/red) is not the research team's POV.
            absolute = [{"order": e["order"], "action": e["action"],
                         "camp": camp if e["actor"] == "team"
                                 else ("2" if camp == "1" else "1"),
                         "hero": e["hero"]} for e in events]
            is_scrim_15 = bool(events and validate_scrim_prefix(absolute, full=True))
            # Legacy or malformed 18/14-turn records still support final
            # lineup statistics, but MUST NOT train scrim order predictions.
            if not is_scrim_15:
                events = []
            rule_profile = SCRIM_GLOBAL_15.id if is_scrim_15 else "scrim-unconfirmed"
            result = item.get("result")
            won = (result == "win") if result in ("win", "loss") else None
            if side == "enemy" and won is not None:
                won = not won
            own_diff = process.get("teamDiffOwn") or {}
            flip = 1 if side == "own" else -1
            team_diff = {stamp: (round(value * flip, 1) if isinstance(value, (int, float))
                                 else None) for stamp, value in own_diff.items()}
            games.append({"id": identity, "date": _period(item.get("day") or item.get("start")),
                          "team": team, "enemy": foe, "side": camp,
                          "picks": own_picks, "bans": own_bans,
                          "enemyPicks": enemy_picks, "enemyBans": _heroes(bans.get(other)),
                          "players": _scrim_players(item, side, own_picks),
                          "enemyPlayers": _scrim_players(item, other, enemy_picks),
                          "result": won, "events": events, "source": "scrim",
                          "matchId": identity, "league": "训练赛",
                          "version": str(item.get("version") or "").strip(),
                          "stage": str(item.get("stage") or "").strip(),
                          "ruleProfile": rule_profile,
                          "ruleValidated": is_scrim_15,
                          "gameSeq": None,
                          "processMatchKey": process.get("matchKey") or "",
                          "teamGoldDiff": team_diff,
                          "laneGoldDiffByHero": process.get("laneDiffByHero") or {}})
    return games


def _evidence(games, max_items=8):
    seen, rows = set(), []
    for g in sorted(games, key=lambda x: (x["date"], x["id"]), reverse=True):
        if g["id"] in seen:
            continue
        seen.add(g["id"])
        rows.append({"id": g["id"], "date": g["date"], "team": g["team"],
                     "enemy": g["enemy"], "source": g["source"],
                     "result": g["result"], "matchId": g["matchId"],
                     "processMatchKey": g.get("processMatchKey") or ""})
        if len(rows) >= max_items:
            break
    return rows


def _counts(games, field, baseline=None):
    bucket = defaultdict(list)
    for g in games:
        for hero in g[field]:
            bucket[hero].append(g)
    baseline_counts = Counter(h for g in (baseline if baseline is not None else games)
                              for h in g[field])
    base_total = len(baseline if baseline is not None else games)
    rows = []
    for hero, records in bucket.items():
        valid = [g for g in records if g["result"] is not None]
        wins = sum(g["result"] is True for g in valid)
        n = len(records)
        rows.append({"hero": hero, "games": n, "share": _percent(n, len(games)),
                     "baselineShare": _percent(baseline_counts[hero], base_total),
                     "wins": wins, "decided": len(valid), "winRate": _percent(wins, len(valid)),
                     "interval": _wilson(wins, len(valid)), "evidence": _evidence(records)})
    return sorted(rows, key=lambda x: (-x["games"], x["hero"]))


def _combos(games, baseline, size):
    bucket = defaultdict(list)
    for g in games:
        if len(g["picks"]) != 5:
            continue
        for heroes in combinations(sorted(g["picks"]), size):
            bucket[heroes].append(g)
    base_hero = defaultdict(list)
    for g in baseline:
        for hero in g["picks"]:
            base_hero[hero].append(g)
    result = []
    for heroes, records in bucket.items():
        if len(records) < 2:
            continue
        valid = [g for g in records if g["result"] is not None]
        wins = sum(g["result"] is True for g in valid)
        individual = []
        for hero in heroes:
            valid_base = [g for g in base_hero.get(hero, []) if g["result"] is not None]
            if valid_base:
                individual.append((sum(g["result"] is True for g in valid_base) + 2) /
                                  (len(valid_base) + 4))
        if not individual:
            continue
        # Additive hero benchmark is a descriptive baseline, not a causal synergy.
        expected = sum(individual) / len(individual)
        shrunk = (wins + expected * 6) / (len(valid) + 6) if valid else None
        result.append({"heroes": list(heroes), "games": len(records),
                       "wins": wins, "decided": len(valid),
                       "winRate": _percent(wins, len(valid)),
                       "reference": round(100 * expected, 1),
                       "relativeSignal": (round(100 * (shrunk - expected), 1)
                                          if shrunk is not None and len(valid) >= 3 else None),
                       "evidence": _evidence(records)})
    return sorted(result, key=lambda x: (-x["games"], -abs(x["relativeSignal"] or 0)))[:18]


def _players(games, baseline):
    hero_base = defaultdict(list)
    for g in baseline:
        for p in g["players"]:
            hero_base[p["hero"]].append(g)
    groups = defaultdict(list)
    for g in games:
        for p in g["players"]:
            groups[(g["team"], p["name"], p["hero"], p["lane"])].append(g)
    output = []
    for (team, name, hero, lane), rows in groups.items():
        valid = [g for g in rows if g["result"] is not None]
        base = [g for g in hero_base.get(hero, []) if g["result"] is not None]
        if not valid or not base:
            continue
        base_rate = (sum(g["result"] is True for g in base) + 2) / (len(base) + 4)
        wins = sum(g["result"] is True for g in valid)
        posterior = (wins + base_rate * 6) / (len(valid) + 6)
        samples = [p for g in rows for p in g["players"]
                   if p["name"] == name and p["hero"] == hero]
        damage_gold = [1000 * p["heroDamage"] / p["gold"] for p in samples
                       if isinstance(p.get("heroDamage"), (int, float))
                       and isinstance(p.get("gold"), (int, float)) and p["gold"] > 0]
        avg_efficiency = (round(sum(damage_gold) / len(damage_gold), 1)
                          if damage_gold else None)
        output.append({"player": name, "team": team, "hero": hero, "lane": lane, "games": len(rows),
                       "heroDamagePer1000Gold": avg_efficiency,
                       "wins": wins, "winRate": _percent(wins, len(valid)),
                       "reference": round(base_rate * 100, 1),
                       "relativeSignal": (round((posterior - base_rate) * 100, 1)
                                          if len(valid) >= 3 and len(base) >= 3 else None),
                       "evidence": _evidence(rows)})
    return sorted(output, key=lambda x: (-x["games"], -abs(x["relativeSignal"] or 0), x["player"]))[:28]


def _changes(games):
    ordered = sorted((g for g in games if g["date"]), key=lambda g: (g["date"], g["id"]))
    if len(ordered) < 8:
        return []
    distinct_days = sorted({g["date"] for g in ordered})
    if len(distinct_days) < 2:
        return []
    cut = distinct_days[len(distinct_days) // 2]
    before = [g for g in ordered if g["date"] < cut]
    after = [g for g in ordered if g["date"] >= cut]
    if min(len(before), len(after)) < 3:
        return []
    counts_before = Counter(h for g in before for h in g["picks"])
    counts_after = Counter(h for g in after for h in g["picks"])
    changes = []
    for hero in counts_before.keys() | counts_after.keys():
        previous, current = counts_before[hero], counts_after[hero]
        if previous + current < 3:
            continue
        p = _percent(previous, len(before))
        q = _percent(current, len(after))
        if abs(q - p) < 10:
            continue
        changes.append({"hero": hero, "before": previous, "after": current,
                        "beforeGames": len(before), "afterGames": len(after),
                        "previousShare": p, "recentShare": q, "changePP": round(q-p, 1),
                        "evidence": _evidence([g for g in after if hero in g["picks"]])})
    return sorted(changes, key=lambda x: -abs(x["changePP"]))[:12]



def _average(values):
    values = [v for v in values if isinstance(v, (int, float))
              and not isinstance(v, bool)]
    return round(sum(values) / len(values), 1) if values else None


def _process_analysis(games):
    """Descriptive BP-linked team tempo and per-player lane economy; no inferred CS."""
    available = [g for g in games if g.get("processMatchKey")]
    valid_at = lambda stamp: [g for g in games
                              if isinstance((g.get("teamGoldDiff") or {}).get(stamp),
                                            (int, float))]
    by_checkpoint = {}
    for stamp in ("120", "240", "600"):
        rows = valid_at(stamp)
        ahead = [g for g in rows if g["teamGoldDiff"][stamp] > 0]
        decided = [g for g in ahead if g["result"] is not None]
        by_checkpoint[stamp] = {
            "games": len(rows),
            "meanDiff": _average([g["teamGoldDiff"][stamp] for g in rows]),
            "aheadGames": len(ahead), "aheadRate": _percent(len(ahead), len(rows)),
            "aheadWins": sum(g["result"] is True for g in decided),
            "aheadDecided": len(decided),
            "leadConversion": _percent(sum(g["result"] is True for g in decided),
                                       len(decided)),
            "evidence": _evidence(rows, 8),
        }
    stages = defaultdict(lambda: {"games": [], "240": [], "600": []})
    for game in games:
        lane_gold = game.get("laneGoldDiffByHero") or {}
        for player in game["players"]:
            if not player.get("hero") or not player.get("name"):
                continue
            key = game["team"], player["name"], player["hero"], player.get("lane") or ""
            stage = stages[key]
            if game.get("processMatchKey"):
                stage["games"].append(game)
            for stamp in ("240", "600"):
                diff = (lane_gold.get(stamp) or {}).get(player["hero"])
                if isinstance(diff, (int, float)) and not isinstance(diff, bool):
                    stage[stamp].append((game, diff))
    player_rows = []
    for (team, name, hero, lane), values in stages.items():
        total = len({g["id"] for g in values["games"]})
        n4, n10 = len(values["240"]), len(values["600"])
        if not n4 and not n10:
            continue
        player_rows.append({
            "team": team, "player": name, "hero": hero, "lane": lane,
            "linkedGames": total, "n4": n4, "n10": n10,
            "diff4": _average([value for _, value in values["240"]]),
            "diff10": _average([value for _, value in values["600"]]),
            "ahead4": _percent(sum(v > 0 for _, v in values["240"]), n4),
            "ahead10": _percent(sum(v > 0 for _, v in values["600"]), n10),
            "evidence": _evidence([g for g, _ in values["240"] + values["600"]]),
        })
    player_rows.sort(key=lambda r: (-max(r["n4"], r["n10"]), r["player"], r["hero"]))
    per_hero = []
    for hero in sorted({hero for g in games for hero in g["picks"]}):
        rows = [g for g in games if hero in g["picks"]]
        values = [(g, (g.get("teamGoldDiff") or {}).get("600")) for g in rows]
        checked = [(g, v) for g, v in values if isinstance(v, (int, float))]
        if len(checked) < 2:
            continue
        per_hero.append({"hero": hero, "games": len(rows), "processGames": len(checked),
                         "avgTeamDiff10": _average([v for _, v in checked]),
                         "evidence": _evidence([g for g, _ in checked])})
    per_hero.sort(key=lambda r: (-r["processGames"], r["hero"]))
    return {"linkedGames": len({g["id"] for g in available}),
            "checkpoints": by_checkpoint, "playerLanes": player_rows[:25],
            "heroTempo": per_hero[:20],
            "limitations": [
                "阶段经济来自已匹配录像/回放的双方经济时间轴；过稀或不连续的时间点不插值。",
                "选手对位经济差仅在相同分路、对应英雄身份及个人记分板快照可验证时计算。",
                "队伍经济优势不等于某位选手对线能力，经济差也不等于补刀数量。",
            ]}


def _hero_win_shifts(games):
    """Observed win-rate changes with condition drift, never asserted as causal."""
    dated = sorted((g for g in games if g["date"]), key=lambda g: (g["date"], g["id"]))
    days = sorted({g["date"] for g in dated})
    if len(dated) < 12 or len(days) < 2:
        return []
    cut = days[len(days) // 2]
    before, after = [g for g in dated if g["date"] < cut], [g for g in dated if g["date"] >= cut]
    if min(len(before), len(after)) < 5:
        return []
    heroes = sorted({hero for g in dated for hero in g["picks"]})
    out = []
    for hero in heroes:
        early = [g for g in before if hero in g["picks"] and g["result"] is not None]
        recent = [g for g in after if hero in g["picks"] and g["result"] is not None]
        if min(len(early), len(recent)) < 3:
            continue
        early_win = sum(g["result"] is True for g in early)
        recent_win = sum(g["result"] is True for g in recent)
        prev_rate, new_rate = _percent(early_win, len(early)), _percent(recent_win, len(recent))
        change = round(new_rate - prev_rate, 1)
        if abs(change) < 15:
            continue
        partner_before = Counter(h for g in early for h in g["picks"] if h != hero)
        partner_after = Counter(h for g in recent for h in g["picks"] if h != hero)
        enemy_before = Counter(h for g in early for h in g["enemyPicks"])
        enemy_after = Counter(h for g in recent for h in g["enemyPicks"])
        def drift(old, new):
            return sorted([{"hero": h, "previousGames": old[h], "recentGames": new[h],
                            "previousShare": _percent(old[h], len(early)),
                            "recentShare": _percent(new[h], len(recent)),
                            "changePP": round(_percent(new[h], len(recent)) -
                                              _percent(old[h], len(early)), 1)}
                           for h in old.keys() | new.keys()],
                          key=lambda v: (-abs(v["changePP"]), v["hero"]))[:4]
        def average_diff(rows):
            return _average([(g.get("teamGoldDiff") or {}).get("600") for g in rows])
        out.append({
            "hero": hero, "cutDate": cut,
            "previousGames": len(early), "recentGames": len(recent),
            "previousWins": early_win, "recentWins": recent_win,
            "previousWinRate": prev_rate, "recentWinRate": new_rate,
            "changePP": change, "previousInterval": _wilson(early_win, len(early)),
            "recentInterval": _wilson(recent_win, len(recent)),
            "previousTeamDiff10": average_diff(early),
            "recentTeamDiff10": average_diff(recent),
            "partnerChanges": drift(partner_before, partner_after),
            "enemyChanges": drift(enemy_before, enemy_after),
            "previousEvidence": _evidence(early), "recentEvidence": _evidence(recent),
        })
    return sorted(out, key=lambda x: (-abs(x["changePP"]), x["hero"]))[:12]



def _lineups(games):
    """Actual five-hero lineups, independent of displayed ordering."""
    buckets = defaultdict(list)
    for g in games:
        if len(g["picks"]) == 5:
            buckets[tuple(sorted(g["picks"]))].append(g)
    result = []
    for heroes, records in buckets.items():
        decided = [g for g in records if g["result"] is not None]
        wins = sum(g["result"] is True for g in decided)
        result.append({"heroes": list(heroes), "games": len(records),
                       "wins": wins, "decided": len(decided),
                       "winRate": _percent(wins, len(decided)),
                       "interval": _wilson(wins, len(decided)),
                       "evidence": _evidence(records)})
    return sorted(result, key=lambda x: (-x["games"], x["heroes"]))[:18]


def _ban_responses(games):
    """Observed next own pick after opponent ban, not presumed hero substitution."""
    opportunities = defaultdict(set)
    found = defaultdict(dict)
    for game in games:
        pending, used = set(), set()
        for event in game["events"]:
            if event["actor"] == "enemy" and event["action"] == "ban":
                if event["hero"] not in used:
                    pending.add(event["hero"])
            elif event["actor"] == "team" and event["action"] == "pick":
                for hero in pending:
                    opportunities[hero].add(game["id"])
                    found[(hero, event["hero"])][game["id"]] = game
                    used.add(hero)
                pending.clear()
    output = []
    for (ban, picked), records in found.items():
        denominator = len(opportunities[ban])
        if denominator < 2:
            continue
        output.append({"trigger": ban, "response": picked,
                       "games": len(records), "opportunities": denominator,
                       "share": _percent(len(records), denominator),
                       "evidence": _evidence(records.values())})
    return sorted(output, key=lambda row: (-row["games"], -row["share"],
                                           row["trigger"], row["response"]))[:20]


def _response_samples(g):
    """(trigger, actual pick, unavailable-at-decision) using only past BP events."""
    latest, used, unavailable, rows = None, set(), set(), []
    for event in g["events"]:
        hero = event["hero"]
        if event["actor"] == "enemy" and event["action"] == "pick":
            latest = hero
        elif event["actor"] == "team" and event["action"] == "pick" and latest:
            if latest not in used:
                rows.append((latest, hero, frozenset(unavailable)))
                used.add(latest)
        unavailable.add(hero)
    return rows


def _transitions(games):
    """Actual conditional opponent response; no information from future draft moves."""
    condition_games = defaultdict(set)
    response_games = defaultdict(dict)
    for g in games:
        for trigger, response, _ in _response_samples(g):
            condition_games[trigger].add(g["id"])
            response_games[(trigger, response)][g["id"]] = g
    rows = []
    for (trigger, response), matches in response_games.items():
        den, amount = len(condition_games[trigger]), len(matches)
        if den < 2:
            continue
        rows.append({"trigger": trigger, "response": response, "games": amount,
                     "opportunities": den, "share": _percent(amount, den),
                     "evidence": _evidence(list(matches.values()))})
    return sorted(rows, key=lambda x: (-x["games"], -x["share"], x["trigger"]))[:24]


def _temporal_validation(games):
    """Evaluate historical BP response tendencies on later *unseen dates*."""
    observed = sorted((g for g in games if g["events"] and g["date"]),
                      key=lambda g: (g["date"], g["id"]))
    days = sorted({g["date"] for g in observed})
    if len(observed) < 12 or len(days) < 4:
        return None
    cutoff = days[max(1, int(len(days) * 0.7))]
    train = [g for g in observed if g["date"] < cutoff]
    test = [g for g in observed if g["date"] >= cutoff]
    if len(train) < 8 or len(test) < 3:
        return None
    general, conditional = Counter(), defaultdict(Counter)
    for g in train:
        for trigger, response, _ in _response_samples(g):
            general[response] += 1
            conditional[trigger][response] += 1
    if not general:
        return None
    cases, model_hits, base_hits, covered = 0, 0, 0, 0
    for g in test:
        for trigger, actual, unavailable in _response_samples(g):
            baseline = [hero for hero, _ in general.most_common()
                        if hero not in unavailable][:3]
            bucket = conditional.get(trigger)
            used_context = bool(bucket and sum(bucket.values()) >= 3)
            preferred = bucket if used_context else general
            predicted = [hero for hero, _ in preferred.most_common()
                         if hero not in unavailable][:3]
            cases += 1
            covered += int(used_context)
            base_hits += int(actual in baseline)
            model_hits += int(actual in predicted)
    if cases < 6:
        return None
    return {
        "trainGames": len(train), "testGames": len(test), "testCases": cases,
        "baselineTop3": _percent(base_hits, cases),
        "conditionalTop3": _percent(model_hits, cases),
        "changePP": round(100 * (model_hits - base_hits) / cases, 1),
        "conditionCases": covered,
        "splitDate": cutoff,
    }


def _matchups(games):
    bucket = defaultdict(list)
    for g in games:
        # Only explicit per-player lane mappings; no inferred lane from final pick order.
        for own in g["players"]:
            if not own["lane"]:
                continue
            if own["hero"] not in g["picks"]:
                continue
            # Opposing players may be absent in older scrim records.
            for opponent in g.get("enemyPlayers", []):
                if opponent.get("lane") == own["lane"]:
                    bucket[(own["hero"], opponent["hero"], own["lane"])].append(g)
    result = []
    for (hero, enemy, lane), rows in bucket.items():
        valid = [g for g in rows if g["result"] is not None]
        wins = sum(g["result"] is True for g in valid)
        if len(rows) >= 2:
            result.append({"hero": hero, "enemy": enemy, "lane": lane, "games": len(rows),
                           "winRate": _percent(wins, len(valid)), "evidence": _evidence(rows)})
    return sorted(result, key=lambda x: -x["games"])[:20]


def _counter_candidates(games):
    """Observed own hero choices against an opposing hero, NOT a causal counter rating."""
    buckets = defaultdict(list)
    enemy_exposure = Counter()
    for g in games:
        if len(g["picks"]) != 5 or len(g["enemyPicks"]) != 5:
            continue
        for enemy in g["enemyPicks"]:
            enemy_exposure[enemy] += 1
            for own in g["picks"]:
                buckets[(enemy, own)].append(g)
    selected_enemies = {hero for hero, _ in enemy_exposure.most_common(40)}
    results = defaultdict(list)
    for (enemy, own), records in buckets.items():
        if enemy not in selected_enemies or len(records) < 2:
            continue
        decided = [g for g in records if g["result"] is not None]
        wins = sum(g["result"] is True for g in decided)
        results[enemy].append({
            "enemyHero": enemy, "candidateHero": own, "games": len(records),
            "againstGames": enemy_exposure[enemy], "wins": wins,
            "decided": len(decided), "winRate": _percent(wins, len(decided)),
            "interval": _wilson(wins, len(decided)),
            "evidence": _evidence(records, max_items=6),
        })
    return [row for hero in sorted(results) for row in
            sorted(results[hero], key=lambda r: (-r["games"], r["candidateHero"]))[:8]]


def _series_adjustments(games):
    """Observe sequential BP changes within the same official BO series."""
    groups = defaultdict(list)
    for g in games:
        if g["source"] != "kpl" or not g.get("matchId"):
            continue
        if not isinstance(g.get("gameSeq"), int) or g["gameSeq"] <= 0:
            continue
        groups[(g["team"], g["matchId"])].append(g)
    changes = []
    for (_, series_id), rows in groups.items():
        ordered = sorted(rows, key=lambda g: g["gameSeq"])
        for before, after in zip(ordered, ordered[1:]):
            if after["gameSeq"] != before["gameSeq"] + 1:
                continue
            fresh = [h for h in after["picks"] if h not in before["picks"]]
            bans = [h for h in after["bans"] if h not in before["bans"]]
            changes.append({
                "seriesId": series_id, "team": after["team"],
                "previous": before["gameSeq"], "current": after["gameSeq"],
                "previousResult": before["result"], "currentResult": after["result"],
                "newPicks": fresh, "newBans": bans,
                "evidence": _evidence([before, after]),
            })
    return sorted(changes, key=lambda x: (x["seriesId"], x["current"]), reverse=True)[:20]


def build_report(scrim_rows, kpl_rows, *, source="scrim", team="", start="", end="",
                 version="", process_map=None):
    if source not in ("scrim", "kpl"):
        raise ValueError("未知比赛来源")
    if start:
        date.fromisoformat(start)
    if end:
        date.fromisoformat(end)
    all_games = (normalize_scrims(scrim_rows, process_map=process_map)
                 if source == "scrim" else normalize_kpl(kpl_rows))
    dedup = {(g["id"], g["team"]): g for g in all_games}
    source_games = [g for g in dedup.values()
                    if (not start or g["date"] >= start) and (not end or g["date"] <= end)]
    source_games.sort(key=lambda g: (g["date"], g["id"]), reverse=True)
    unfiltered_team_games = [g for g in source_games if not team or g["team"] == team]
    from bp_strategy import (side_round_study, version_study, player_pool_study,
                             matchup_study, draft_two_step_study, coach_brief)
    versions = version_study(unfiltered_team_games, source_games, selected=version)
    if version:
        source_games = [g for g in source_games if g.get("version") == version]
    teams = Counter(g["team"] for g in source_games)
    team_games = [g for g in source_games if not team or g["team"] == team]
    matches = {g["id"] for g in team_games}
    full = [g for g in team_games if g["events"]]
    decided = [g for g in team_games if g["result"] is not None]
    wins = sum(g["result"] is True for g in decided)
    picks = _counts(team_games, "picks", source_games)
    bans = _counts(team_games, "bans", source_games)
    combos = _combos(team_games, source_games, 2)
    trios = _combos(team_games, source_games, 3)
    full_lineups = _lineups(team_games)
    ban_responses = _ban_responses(team_games)
    players = _players(team_games, source_games)
    changes = _changes(team_games)
    responses = _transitions(team_games)
    bp_studies = {
        "draft": side_round_study(team_games),
        "version": versions,
        "players": player_pool_study(team_games),
        "matchups": matchup_study(team_games),
        "twoStep": draft_two_step_study(team_games),
    }
    # Looking at an opponent in scrim data? Keep the user's own historical
    # responses separate from that opponent's own lineup choices.
    # Never merge official KPL and private scrim win rates.
    own_vs_target = ([g for g in source_games
                      if g["team"] == "本队" and g["enemy"] == team]
                     if source == "scrim" and team and team != "本队" else [])
    own_pool_games = ([g for g in source_games if g["team"] == "本队"]
                      if source == "scrim" else [])
    bp_studies["ownVsTarget"] = {
        "games": len(own_vs_target),
        "candidates": matchup_study(own_vs_target) if own_vs_target else [],
        "ownPool": _counts(own_pool_games, "picks", own_pool_games)[:24]
                   if own_pool_games else [],
        "reason": ("本队对该对手的真实训练赛应对；不存在的阵容未估计效果。"
                   if own_vs_target else
                   "暂无可验证的本队对该对手历史训练赛，不生成个性化反制推荐。")
    }
    bp_studies["brief"] = coach_brief(bp_studies, team_games) if team else []
    from bp_draft_tree import draft_tree, priority_brief
    bp_studies["ruleCoverage"] = {
        "scrim15": sum(g.get("ruleValidated", False) for g in team_games)
                   if source == "scrim" else 0,
        "scrimUnknown": sum(not g.get("ruleValidated", False) for g in team_games)
                        if source == "scrim" else 0,
        "kplRecorded": sum(bool(g["events"]) for g in team_games)
                       if source == "kpl" else 0,
        "profile": ("scrim-global-15" if source == "scrim" else "kpl-recorded"),
        "note": ("训练赛只将符合 5 Ban + 10 Pick 的 15 手模板的完整事件用于顺序研究；"
                 "不符合该模板的旧记录仍可作基础阵容统计。"
                 if source == "scrim" else
                 "KPL 只校验真实历史 BP 事件，不应用训练赛的四阶段规则。")
    }
    bp_studies["draftTree"] = (draft_tree(team_games) if team else
                                {"orderedGames": 0, "indexedGames": 0, "limited": False,
                                 "nodes": [], "description": "请先选择一支战队。"})
    bp_studies["priorities"] = (priority_brief(team_games, source_games, bp_studies["brief"])
                                 if team else [])
    from bp_policy import next_pick_policy
    bp_studies["nextPickPolicy"] = next_pick_policy(team_games) if team else {
        "status": "not-applicable", "reason": "请先选择要研究的战队。",
        "contexts": [], "supported": False,
    }
    from bp_interactions import interaction_study
    # Only compare own-side match outcomes for one team, never opposite labels
    # duplicated from all-league perspective rows.
    bp_studies["interactions"] = interaction_study(team_games) if team else {
        "status": "not-applicable", "reason": "请选择具体战队以研究交互效果。",
        "improved": False, "signals": [],
    }
    # League/whole-dataset views include both sides of the same game; assigning
    # a team advantage or a single-team win-rate trend is meaningless there.
    process_study = _process_analysis(team_games if team else [])
    hero_shifts = _hero_win_shifts(team_games if team else [])
    findings = []
    for item in bp_studies["brief"]:
        findings.append({"kind": item["kind"], "title": item["title"],
                         "detail": item["detail"], "note": item["action"],
                         "evidence": item["evidence"]})
    if hero_shifts:
        change = hero_shifts[0]
        findings.append({"kind": "hero-outcome", "title": "英雄近期战绩波动：" + change["hero"],
                         "detail": f"较早 {change['previousWins']}/{change['previousGames']} 胜，近期 {change['recentWins']}/{change['recentGames']} 胜（变化 {change['changePP']:+.1f} 个百分点）。",
                         "note": "先比较阵容搭配、对位和队伍经济；波动不能直接当作原因。",
                         "evidence": change["recentEvidence"]})
    if process_study["checkpoints"]["600"]["games"] >= 3:
        checkpoint = process_study["checkpoints"]["600"]
        findings.append({"kind": "process", "title": "10 分钟比赛节奏",
                         "detail": f"在 {checkpoint['games']} 局有过程证据的比赛中，平均队伍经济差 {checkpoint['meanDiff']:+,.0f}。",
                         "note": "仅反映双方队伍经济，不能直接定义单人对线强弱。",
                         "evidence": checkpoint["evidence"]})
    if picks and len(team_games) >= 3:
        top = picks[0]
        diff = (top["share"] - top["baselineShare"]) if top["baselineShare"] is not None else None
        findings.append({"kind": "preference", "title": "近期常用：" + top["hero"],
                         "detail": f"在 {top['games']}/{len(team_games)} 局中使用；同来源总体占比 {top['baselineShare']}%。",
                         "note": "是选择习惯，不等于英雄强度。" if diff is None or diff <= 0 else
                                 "相对同来源总体更常使用，建议结合对手和版本核查。",
                         "evidence": top["evidence"]})
    if responses:
        first = next((r for r in responses if r["opportunities"] >= 3 and r["games"] >= 2), None)
        if first:
            findings.append({"kind": "response", "title": "BP 条件回应：" + first["response"],
                             "detail": f"对方先选 {first['trigger']} 后，我方在 {first['games']}/{first['opportunities']} 局的下一次选用是 {first['response']}。",
                             "note": "仅统计顺序已核验的实际选禁；不保证下一场重复。",
                             "evidence": first["evidence"]})
    if changes:
        change = changes[0]
        findings.append({"kind": "change", "title": "近期选人变化：" + change["hero"],
                         "detail": f"前半段 {change['before']}/{change['beforeGames']} 局，后半段 {change['after']}/{change['afterGames']} 局。",
                         "note": "仅为分段变化线索，需核对赛程与版本。",
                         "evidence": change["evidence"]})
    if combos:
        top = next((x for x in combos if x["games"] >= 3), None)
        if top:
            findings.append({"kind": "combo", "title": "常见组合：" + " + ".join(top["heroes"]),
                             "detail": f"共同出场 {top['games']} 局；实际胜率 {top['winRate']}%。",
                             "note": "组合表现受选手、版本和对手影响，不直接判定克制或因果协同。",
                             "evidence": top["evidence"]})
    return {"schema": "bp-research-v1", "source": source, "team": team,
            "teams": [{"name": name, "games": count} for name, count in
                      sorted(teams.items(), key=lambda x: (-x[1], x[0]))],
            "scope": {"start": start, "end": end, "games": len(matches),
                      "decided": len(decided), "wins": wins, "winRate": _percent(wins, len(decided)),
                      "interval": _wilson(wins, len(decided)),
                      "orderedGames": len({g["id"] for g in full}),
                      "playerGames": len({g["id"] for g in team_games if g["players"]})},
            "picks": picks[:24], "bans": bans[:24],
            "pairs": combos, "trios": trios, "fullLineups": full_lineups,
            "banResponses": ban_responses,
            "players": players, "changes": changes,
            "processStudy": process_study, "heroWinShifts": hero_shifts,
            "bpStudies": bp_studies,
            "responses": responses, "matchups": _matchups(team_games),
            "seriesAdjustments": _series_adjustments(team_games),
            "counterCandidates": _counter_candidates(team_games),
            "validation": _temporal_validation(team_games),
            "findings": findings[:5], "evidence": _evidence(team_games, max_items=30),
            "limitations": [
                "训练赛与正式比赛分别计算，不直接混合胜率。",
                "BP 顺序仅来自完整且已核验的实际选禁事件；未取得事件的比赛仍可用于阵容统计。",
                "选手英雄相对表现经分层收缩，但不能据此直接判定对线、团战或因果克制。",
                "组合超额表现为探索性信号，不是可直接证明的协同效果。",
                "胜率异动中阵容与对位变化仅是相关条件，不构成自动因果归因。",
                "分路经济只有在真实逐人快照及明确对位身份可用时才计算；缺失绝不插补。",
                "蓝红方/轮次仅以有效 BP 事件为依据；使用率对比只说明选择习惯。",
                "版本对照只使用明确标注的真实游戏版本，不以年份或日期推断补齐。",
                "历史两步回应是可复查的已发生分支，不是最优博弈策略或模拟胜率。",
            ]}
