"""Time-forward next-pick BP policy checks using only information known at selection.

Rank heroes by stage (side + own pick index) and, when there is enough
training evidence, the latest visible opposing pick. Eliminate all heroes
already picked or banned at that instant. Never train on held-out matches.
"""
from __future__ import annotations
from collections import Counter, defaultdict


def _decisions(g):
    unavailable, opposing, own_count = set(), None, 0
    for event in g.get("events") or []:
        actor, action, hero = event["actor"], event["action"], event["hero"]
        if action == "pick" and actor == "enemy":
            opposing = hero
        if action == "pick" and actor == "team":
            own_count += 1
            if hero not in unavailable:
                yield {"side": g["side"], "slot": own_count,
                       "opponentHero": opposing, "hero": hero,
                       "unavailable": frozenset(unavailable), "game": g}
        unavailable.add(hero)


def _choice_counts(games):
    baselines, conditions = defaultdict(Counter), defaultdict(Counter)
    contexts = defaultdict(list)
    for game in games:
        for row in _decisions(game):
            base_key = row["side"], row["slot"]
            baselines[base_key][row["hero"]] += 1
            if row["opponentHero"]:
                cond_key = base_key + (row["opponentHero"],)
                conditions[cond_key][row["hero"]] += 1
                contexts[cond_key].append(row["game"])
    return baselines, conditions, contexts


def _top_n(counts, unavailable, n=3):
    return [hero for hero, _ in counts.most_common()
            if hero not in unavailable][:n]


def next_pick_policy(games):
    from bp_strategy import _pct, _evidence
    rows = sorted(
        [g for g in games if g.get("events") and g.get("date")],
        key=lambda g: (g["date"], g["id"]))
    days = sorted({g["date"] for g in rows})
    result = {"status": "insufficient", "reason": "完整 BP 对局和日期不足，不能开展时间外策略验证。",
              "trainGames": 0, "testGames": 0, "testDecisions": 0,
              "baselineTop3": None, "conditionTop3": None,
              "coverage": None, "gainPP": None, "supported": False,
              "contexts": []}
    if len(rows) < 16 or len(days) < 4:
        return result
    split = days[max(1, int(len(days) * .7))]
    train = [g for g in rows if g["date"] < split]
    holdout = [g for g in rows if g["date"] >= split]
    if len(train) < 10 or len(holdout) < 4:
        return result
    baseline, cond, _ = _choice_counts(train)
    test_decisions, base_hits, context_hits, context_used = 0, 0, 0, 0
    for g in holdout:
        for row in _decisions(g):
            base_key = row["side"], row["slot"]
            base = baseline.get(base_key, Counter())
            condition = cond.get(base_key + (row["opponentHero"],), Counter())
            eligible = bool(row["opponentHero"] and sum(condition.values()) >= 3)
            candidate = condition if eligible else base
            base_top = _top_n(base, row["unavailable"])
            context_top = _top_n(candidate, row["unavailable"])
            if not base_top:
                continue
            test_decisions += 1
            base_hits += int(row["hero"] in base_top)
            context_hits += int(row["hero"] in context_top)
            context_used += int(eligible)
    if test_decisions < 12:
        result["reason"] = "后续比赛中可比较的 BP 决策不足 12 个。"
        return result
    score_a = _pct(base_hits, test_decisions)
    score_b = _pct(context_hits, test_decisions)
    result.update({
        "status": "tested", "trainGames": len(train), "testGames": len(holdout),
        "testDecisions": test_decisions, "splitDate": split,
        "baselineTop3": score_a, "conditionTop3": score_b,
        "gainPP": round(score_b - score_a, 1), "coverage": _pct(context_used, test_decisions),
        "supported": score_b > score_a,
        "reason": ("条件预测优于只按蓝红方和轮次统计的基线。"
                   if score_b > score_a else
                   "条件预测没有超过基线，暂不视为稳定的额外规律。")
    })
    # These descriptive conditional patterns are sampled solely from training
    # games. No future holdout information influences the displayed rankings.
    context_rows = []
    for (side, slot, opponent), options in cond.items():
        total = sum(options.values())
        if total < 4:
            continue
        context_games = [g for g in train if any(
            d["side"] == side and d["slot"] == slot and
            d["opponentHero"] == opponent for d in _decisions(g))]
        context_rows.append({
            "side": side, "slot": slot, "opponentHero": opponent,
            "games": len(context_games), "decisions": total,
            "options": [{"hero": hero, "games": count,
                         "share": _pct(count, total)}
                        for hero, count in options.most_common(4)],
            "evidence": _evidence(context_games, 6),
        })
    result["contexts"] = sorted(context_rows, key=lambda r: (-r["decisions"], r["slot"],
                                                            r["opponentHero"]))[:15]
    return result
