"""Replayable BP decision tree from verified ordered historical drafts.

Every edge is an actually observed Ban/Pick. The tree does NOT optimize
unseen lineups, infer match win probabilities, or make up a tournament ruleset.
Its goal is to let a coach step through multiple rounds and inspect evidence.
"""
from __future__ import annotations

from collections import defaultdict
from math import exp, fsum, lgamma


def _fisher_greater(a, n_a, b, n_b):
    """One-sided Fisher exact test: is target-team pick share higher?"""
    successes, total = a + b, n_a + n_b
    if not total or a > n_a or b > n_b:
        return 1.0
    def log_choose(n, k):
        return lgamma(n + 1) - lgamma(k + 1) - lgamma(n - k + 1)
    upper = min(n_a, successes)
    tail = [exp(log_choose(successes, x)
                + log_choose(total - successes, n_a - x)
                - log_choose(total, n_a))
            for x in range(a, upper + 1)
            if n_a - x <= total - successes]
    return min(1.0, fsum(tail))


def _bh_adjust(p_values):
    """Benjamini-Hochberg FDR correction across all explored hero hypotheses."""
    count = len(p_values)
    adjusted = [1.0] * count
    next_q = 1.0
    for rank, index in reversed(list(enumerate(sorted(
            range(count), key=lambda i: p_values[i]), start=1))):
        next_q = min(next_q, p_values[index] * count / rank)
        adjusted[index] = next_q
    return adjusted


def draft_tree(games, *, max_games=160, max_nodes=3500):
    eligible = sorted(
        (g for g in games if g.get("events") and g.get("date") and g.get("id")),
        key=lambda g: (g["date"], g["id"]), reverse=True,
    )
    selected = eligible[:max_games]
    nodes = [{"id": 0, "parent": None, "actor": None, "action": None,
              "hero": None, "depth": 0, "games": 0, "decided": 0,
              "wins": 0, "evidence": []}]
    lookup = {}
    counts = defaultdict(set)
    evidence = defaultdict(list)
    wins = defaultdict(int)
    decided = defaultdict(int)
    # If an enormous draft with pathological events appears, drop the full
    # remainder. Never claim a partial sequence has reached the end.
    for g in selected:
        pointer = 0
        path = [0]
        overflow = False
        for e in g["events"]:
            key = (pointer, e["actor"], e["action"], e["hero"])
            nid = lookup.get(key)
            if nid is None:
                if len(nodes) >= max_nodes:
                    overflow = True
                    break
                nid = len(nodes)
                lookup[key] = nid
                nodes.append({"id": nid, "parent": pointer,
                              "actor": e["actor"], "action": e["action"],
                              "hero": e["hero"], "depth": nodes[pointer]["depth"] + 1,
                              "games": 0, "decided": 0, "wins": 0, "evidence": []})
            pointer = nid
            path.append(pointer)
        if overflow:
            continue
        for nid in path:
            if g["id"] in counts[nid]:
                continue
            counts[nid].add(g["id"])
            if g["result"] is not None:
                decided[nid] += 1
                wins[nid] += int(g["result"] is True)
            if len(evidence[nid]) < 6:
                evidence[nid].append({
                    "id": g["id"], "date": g["date"], "team": g["team"],
                    "enemy": g["enemy"], "result": g["result"],
                    "source": g["source"], "matchId": g["matchId"],
                    "processMatchKey": g.get("processMatchKey") or "",
                })
    kept = []
    valid_nodes = set()
    for node in nodes:
        nid = node["id"]
        if not counts[nid]:
            continue
        node["games"] = len(counts[nid])
        node["decided"] = decided[nid]
        node["wins"] = wins[nid]
        node["evidence"] = evidence[nid]
        kept.append(node)
        valid_nodes.add(nid)
    # Parent node is always present for a retained descendant.
    return {"orderedGames": len(eligible), "indexedGames": len(counts[0]),
            "limited": len(eligible) > max_games or len(nodes) >= max_nodes,
            "nodes": kept,
            "description": "可逐手回放的历史 BP 决策树；每一手来自真实记录，未见过的分支不会被推算成必胜选择。"}


def priority_brief(games, all_games, existing=None):
    """Evidence-backed attention ranking without pretending to know a win optimum."""
    current = games or []
    if not current:
        return []
    from bp_strategy import _evidence, _pct, _uncertainty
    from collections import Counter, defaultdict
    others = [g for g in all_games if g["team"] not in {x["team"] for x in current}]
    subject = "本队" if current[0]["team"] == "本队" else "对手"
    heroes = Counter(h for g in current for h in g["picks"])
    other = Counter(h for g in others for h in g["picks"])
    result = []
    tested = sorted(set(heroes) | set(other))
    pvals = [_fisher_greater(heroes[hero], len(current), other[hero], len(others))
             for hero in tested] if current and others else []
    qvals = dict(zip(tested, _bh_adjust(pvals)))
    for hero, n in heroes.items():
        if n < 4 or len(current) < 7 or len(others) < 12:
            continue
        current_rate = n / len(current)
        base_rate = other[hero] / len(others)
        gap = current_rate - base_rate
        # Conservative confidence gate: lower Wilson bound must exceed the
        # comparison point estimate by 5pp. This remains an association.
        low = _uncertainty(n, len(current))[0] / 100
        if gap < 0.15 or low <= base_rate + 0.05:
            continue
        # Do not call a hero "重点" merely because one of many searches
        # happened to yield an impressive historical win/use ratio.
        q = qvals.get(hero, 1.0)
        level = "重点" if q <= 0.10 and n >= 7 else "观察"
        matches = [g for g in current if hero in g["picks"]]
        result.append({
            "kind": "relative-preference", "level": level,
            "fdrQ": round(q, 6),
            "title": subject + "特别偏爱：" + hero,
            "detail": (f"该战队使用 {n}/{len(current)} 局（{_pct(n,len(current))}%）；"
                       f"其他战队使用 {other[hero]}/{len(others)} 局"
                       f"（{_pct(other[hero],len(others))}%）。"),
            "action": ("多英雄同时筛查已做 FDR 校正；再复核版本、蓝红方与选手英雄池。"
                       if level == "重点" else
                       "选人差异尚未通过多重比较校正；建议只作观察，继续收集对局。"),
            "n": n, "referenceGames": len(others),
            "evidence": _evidence(matches),
        })
    # Existing brief uses observed first pick and player pools.
    for row in existing or []:
        if not row.get("evidence"):
            continue
        result.append({
            "kind": row["kind"], "level": "观察",
            "title": row["title"], "detail": row["detail"],
            "action": row["action"], "n": len(row["evidence"]),
            "referenceGames": 0, "evidence": row["evidence"]
        })
    # Stable and deterministic. Only source-backed comparisons can receive
    # the priority label "重点"; the rest remain observation prompts.
    order = {"重点": 0, "观察": 1}
    return sorted(result, key=lambda r: (order[r["level"]], -r["n"], r["title"]))[:7]
