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


def normalize_scrims(raw_games):
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
        perspective = [("own", "enemy", "本队", str(item.get("opponent") or "").strip()),
                       ("enemy", "own", str(item.get("opponent") or "").strip(), "本队")]
        for side, other, team, foe in perspective:
            if not team or team == "未归属对手":
                continue
            own_picks, own_bans = _heroes(picks.get(side)), _heroes(bans.get(side))
            enemy_picks = _heroes(picks.get(other))
            if not own_picks:
                continue
            # Scrim event contract: actual ordered events must carry camp 1/2.
            camp = "1" if ((side == "own") == (item.get("ownSide") == "left")) else "2"
            events = _checked_events(source_events, camp, own_picks, own_bans,
                                     enemy_picks, _heroes(bans.get(other)))
            result = item.get("result")
            won = (result == "win") if result in ("win", "loss") else None
            if side == "enemy" and won is not None:
                won = not won
            games.append({"id": identity, "date": _period(item.get("day") or item.get("start")),
                          "team": team, "enemy": foe, "side": camp,
                          "picks": own_picks, "bans": own_bans,
                          "enemyPicks": enemy_picks, "enemyBans": _heroes(bans.get(other)),
                          "players": _scrim_players(item, side, own_picks),
                          "enemyPlayers": _scrim_players(item, other, enemy_picks),
                          "result": won, "events": events, "source": "scrim",
                          "matchId": identity, "league": "训练赛", "gameSeq": None})
    return games


def _evidence(games, max_items=8):
    seen, rows = set(), []
    for g in sorted(games, key=lambda x: (x["date"], x["id"]), reverse=True):
        if g["id"] in seen:
            continue
        seen.add(g["id"])
        rows.append({"id": g["id"], "date": g["date"], "team": g["team"],
                     "enemy": g["enemy"], "source": g["source"],
                     "result": g["result"], "matchId": g["matchId"]})
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
                                          if shrunk is not None else None),
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
            groups[(p["name"], p["hero"], p["lane"])].append(g)
    output = []
    for (name, hero, lane), rows in groups.items():
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
        output.append({"player": name, "hero": hero, "lane": lane, "games": len(rows),
                       "heroDamagePer1000Gold": avg_efficiency,
                       "wins": wins, "winRate": _percent(wins, len(valid)),
                       "reference": round(base_rate * 100, 1),
                       "relativeSignal": round((posterior - base_rate) * 100, 1),
                       "evidence": _evidence(rows)})
    return sorted(output, key=lambda x: (-x["games"], -abs(x["relativeSignal"])))[:28]


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
        changes.append({"hero": hero, "before": previous, "after": current,
                        "beforeGames": len(before), "afterGames": len(after),
                        "previousShare": p, "recentShare": q, "changePP": round(q-p, 1),
                        "evidence": _evidence([g for g in after if hero in g["picks"]])})
    return sorted(changes, key=lambda x: -abs(x["changePP"]))[:12]


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


def build_report(scrim_rows, kpl_rows, *, source="scrim", team="", start="", end=""):
    if source not in ("scrim", "kpl"):
        raise ValueError("未知比赛来源")
    if start:
        date.fromisoformat(start)
    if end:
        date.fromisoformat(end)
    all_games = normalize_scrims(scrim_rows) if source == "scrim" else normalize_kpl(kpl_rows)
    dedup = {(g["id"], g["team"]): g for g in all_games}
    source_games = [g for g in dedup.values()
                    if (not start or g["date"] >= start) and (not end or g["date"] <= end)]
    source_games.sort(key=lambda g: (g["date"], g["id"]), reverse=True)
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
    players = _players(team_games, source_games)
    changes = _changes(team_games)
    responses = _transitions(team_games)
    findings = []
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
            "pairs": combos, "trios": trios, "players": players, "changes": changes,
            "responses": responses, "matchups": _matchups(team_games),
            "seriesAdjustments": _series_adjustments(team_games),
            "validation": _temporal_validation(team_games),
            "findings": findings[:5], "evidence": _evidence(team_games, max_items=30),
            "limitations": [
                "训练赛与正式比赛分别计算，不直接混合胜率。",
                "BP 顺序仅来自完整且已核验的实际选禁事件；未取得事件的比赛仍可用于阵容统计。",
                "选手英雄相对表现经分层收缩，但不能据此直接判定对线、团战或因果克制。",
                "组合超额表现为探索性信号，不是可直接证明的协同效果。",
            ]}
