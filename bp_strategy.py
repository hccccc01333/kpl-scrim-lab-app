"""BP-only tactical studies: side, pick/ban rounds, patch, players and responses.

Pure observation / exact-match study. It does not label historical association as
a causal counter, coach intention, or an optimized multi-round BP policy.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from itertools import combinations
from math import sqrt


def _pct(x, n):
    return round(x / n * 100, 1) if n else None


def _uncertainty(w, n):
    if not n:
        return None
    z = 1.96
    p = w / n
    den = 1 + z*z/n
    mid = (p + z*z/(2*n))/den
    d = z*sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return [round(100*max(0, mid-d), 1), round(100*min(1, mid+d), 1)]


def _evidence(games, n=6):
    seen = set()
    out = []
    for g in sorted(games, key=lambda x: (x.get("date") or "", x["id"]), reverse=True):
        if g["id"] in seen:
            continue
        seen.add(g["id"])
        out.append({"id": g["id"], "date": g["date"], "team": g["team"],
                    "enemy": g["enemy"], "source": g["source"],
                    "result": g["result"], "matchId": g["matchId"],
                    "processMatchKey": g.get("processMatchKey") or ""})
        if len(out) == n:
            break
    return out


def side_round_study(games):
    by_side = []
    round_rows = []
    for side, name in (("1", "蓝方"), ("2", "红方")):
        rows = [g for g in games if g["side"] == side]
        valid = [g for g in rows if g["result"] is not None]
        wins = sum(g["result"] is True for g in valid)
        by_side.append({"side": side, "label": name, "games": len(rows),
                        "decided": len(valid), "wins": wins,
                        "winRate": _pct(wins, len(valid)),
                        "interval": _uncertainty(wins, len(valid)),
                        "evidence": _evidence(rows)})
        grouped = defaultdict(list)
        for g in rows:
            if not g["events"]:
                continue
            # per-side rank, not arbitrary global phase number
            own_pick_index = own_ban_index = 0
            for e in g["events"]:
                if e["actor"] != "team":
                    continue
                if e["action"] == "pick":
                    own_pick_index += 1
                    step = own_pick_index
                else:
                    own_ban_index += 1
                    step = own_ban_index
                if step > 7:
                    continue
                grouped[(e["action"], step, e["hero"])].append(g)
        totals = Counter((action, step) for (action, step, _), bucket in grouped.items()
                         for _g in bucket)
        for (action, step, hero), bucket in grouped.items():
            den = totals[(action, step)]
            if not den:
                continue
            round_rows.append({"side": side, "sideLabel": name,
                               "action": action, "round": step,
                               "hero": hero, "games": len(bucket),
                               "opportunities": den, "share": _pct(len(bucket), den),
                               "evidence": _evidence(bucket)})
    return {
        "sides": by_side,
        "rounds": sorted(round_rows, key=lambda x: (x["side"], x["action"],
                                                   x["round"], -x["games"], x["hero"])),
        "orderedGames": sum(bool(g["events"]) for g in games),
    }


def version_study(games, all_games, selected=""):
    # Version labels must be explicit match metadata. Calendar year != game patch.
    valid = [g for g in games if g.get("version")]
    options = Counter(g["version"] for g in all_games if g.get("version"))
    coverage = {"games": len(games), "knownGames": len(valid)}
    versions = []
    for version in sorted(options):
        rows = [g for g in games if g.get("version") == version]
        if not rows:
            continue
        versions.append({"name": version, "games": len(rows),
                         "lastDate": max([g["date"] for g in rows] or [""])})
    versions.sort(key=lambda r: (r["lastDate"], r["name"]), reverse=True)
    # comparison restricted to same team/scope; version metadata may not exist.
    chosen = versions[0]["name"] if versions else ""
    previous = versions[1]["name"] if len(versions) > 1 else ""
    changes = []
    if previous and chosen:
        old = [g for g in games if g.get("version") == previous]
        cur = [g for g in games if g.get("version") == chosen]
        pick_old = Counter(h for g in old for h in g["picks"])
        pick_cur = Counter(h for g in cur for h in g["picks"])
        ban_old = Counter(h for g in old for h in g["bans"])
        ban_cur = Counter(h for g in cur for h in g["bans"])
        for action, oldcount, curcount in (("pick",pick_old,pick_cur),
                                           ("ban",ban_old,ban_cur)):
            if min(len(old), len(cur)) < 3:
                continue
            for hero in oldcount.keys() | curcount.keys():
                if oldcount[hero] + curcount[hero] < 3:
                    continue
                a = _pct(oldcount[hero],len(old))
                b = _pct(curcount[hero],len(cur))
                previous_records = [g for g in old if hero in
                                    (g["picks"] if action=="pick" else g["bans"])]
                recent_records = [g for g in cur if hero in
                                  (g["picks"] if action=="pick" else g["bans"])]
                old_decided = [g for g in previous_records if g["result"] is not None]
                new_decided = [g for g in recent_records if g["result"] is not None]
                old_wins = sum(g["result"] is True for g in old_decided)
                new_wins = sum(g["result"] is True for g in new_decided)
                changes.append({"hero":hero,"action":action,
                                "before":previous,"after":chosen,
                                "oldWinRate":_pct(old_wins,len(old_decided)),
                                "newWinRate":_pct(new_wins,len(new_decided)),
                                "oldDecided":len(old_decided),
                                "newDecided":len(new_decided),
                                "oldInterval":_uncertainty(old_wins,len(old_decided)),
                                "newInterval":_uncertainty(new_wins,len(new_decided)),
                                "oldGames":len(old),"newGames":len(cur),
                                "oldCount":oldcount[hero],"newCount":curcount[hero],
                                "oldShare":a,"newShare":b,"changePP":round(b-a,1),
                                "evidence":_evidence([g for g in cur if hero in
                                                     (g["picks"] if action=="pick" else g["bans"])])})
    return {"coverage": coverage, "options": versions, "before": previous,
            "after": chosen, "selected": selected,
            "changes": sorted(changes,key=lambda r:(-abs(r["changePP"]),r["hero"]))[:24],
            "available": bool(previous and chosen),
            "note": "缺少准确版本标签时不使用年份、日期或赛事名称冒充游戏版本。"}


def player_pool_study(games):
    # Players identified exclusively from confirmed hero-player roster.
    pool = defaultdict(lambda: defaultdict(list))
    for g in games:
        for p in g["players"]:
            if p.get("name") and p.get("hero"):
                pool[(g["team"],p["name"],p.get("lane") or "")][p["hero"]].append(g)
    rows = []
    for (team, player, lane), heroes in pool.items():
        total = len({g["id"] for bucket in heroes.values() for g in bucket})
        if not total:
            continue
        hero_rows=[]
        for hero, bucket in heroes.items():
            decided = [g for g in bucket if g["result"] is not None]
            wins = sum(g["result"] is True for g in decided)
            hero_rows.append({"hero":hero,"games":len(bucket),
                              "share":_pct(len(bucket),total),
                              "wins":wins,"decided":len(decided),
                              "winRate":_pct(wins,len(decided)),
                              "interval":_uncertainty(wins,len(decided)),
                              "evidence":_evidence(bucket)})
        hero_rows.sort(key=lambda r:(-r["games"],r["hero"]))
        rows.append({"team":team,"player":player,"lane":lane,
                     "games":total,"uniqueHeroes":len(hero_rows),
                     "mainHeroShare":hero_rows[0]["share"],"heroes":hero_rows[:16]})
    return sorted(rows,key=lambda r:(-r["games"],r["player"]))[:35]


def matchup_study(games):
    # Exact historical opponent cores; do NOT fabricate full-lineup counter effects.
    buckets=defaultdict(list)
    enemy_exposure=defaultdict(set)
    for g in games:
        if len(g["enemyPicks"])!=5 or len(g["picks"])!=5:
            continue
        for size in (2,3,5):
            for core in combinations(sorted(g["enemyPicks"]),size):
                exposure=(size,core)
                enemy_exposure[exposure].add(g["id"])
                for hero in g["picks"]:
                    buckets[(size,core,hero)].append(g)
    rows=[]
    for (size,core,hero),bucket in buckets.items():
        if len(bucket)<2:
            continue
        valid=[g for g in bucket if g["result"] is not None]
        wins=sum(g["result"] is True for g in valid)
        rows.append({"size":size,"enemyCore":list(core),"candidate":hero,
                     "games":len(bucket),"opportunities":len(enemy_exposure[(size,core)]),
                     "decided":len(valid),"wins":wins,
                     "winRate":_pct(wins,len(valid)),
                     "interval":_uncertainty(wins,len(valid)),
                     "evidence":_evidence(bucket)})
    rows.sort(key=lambda r:(-r["games"],-r["size"],r["enemyCore"],r["candidate"]))
    return rows[:45]


def draft_two_step_study(games):
    """Observed enemy pick -> own pick -> enemy next pick, with legal action order."""
    chains=defaultdict(dict)
    base=defaultdict(set)
    follow=defaultdict(set)
    for g in games:
        events=g["events"]
        if not events:
            continue
        for idx,e in enumerate(events):
            if e["actor"]!="enemy" or e["action"]!="pick":
                continue
            next_own=next((v for v in events[idx+1:]
                           if v["action"]=="pick" and v["actor"]=="team"),None)
            if not next_own:
                continue
            # A new opponent pick before ours invalidates this specific trigger
            until=events[idx+1:events.index(next_own)]
            if any(v["actor"]=="enemy" and v["action"]=="pick" for v in until):
                continue
            trigger=e["hero"];response=next_own["hero"]
            base[trigger].add(g["id"])
            next_enemy=next((v for v in events[events.index(next_own)+1:]
                             if v["actor"]=="enemy" and v["action"]=="pick"),None)
            if not next_enemy:
                continue
            key=(trigger,response,next_enemy["hero"])
            chains[key][g["id"]]=g
            follow[(trigger,response)].add(g["id"])
    grouped=defaultdict(list)
    for (trigger,response,foe),records in chains.items():
        den=len(follow[(trigger,response)])
        if den==0:
            continue
        grouped[trigger].append({"ownPick":response,"enemyNext":foe,
                                 "games":len(records),"opportunities":den,
                                 "share":_pct(len(records),den),
                                 "evidence":_evidence(records.values())})
    return [{"trigger":trigger,"games":len(base[trigger]),
             "branches":sorted(branches,key=lambda x:(-x["games"],x["ownPick"],x["enemyNext"]))[:12]}
            for trigger,branches in
            sorted(grouped.items(),key=lambda x:(-len(base[x[0]]),x[0]))[:20]]


def coach_brief(studies, games):
    """Only evidence-backed, ranked attention prompts; no synthetic risk score."""
    messages=[]
    version=studies.get("version",{})
    for r in version.get("changes",[])[:1]:
        if abs(r["changePP"])>=20:
            messages.append({"kind":"patch","title":f"版本变化：{r['hero']}",
                             "detail":f"{r['before']} 到 {r['after']} 的选{ '用' if r['action']=='pick' else '禁'}占比变化 {r['changePP']:+.1f} 个百分点",
                             "action":"检查版本环境和选手英雄池，确认是否需要改变优先级。",
                             "evidence":r["evidence"]})
    dr=studies.get("draft",{})
    priorities=[r for r in dr.get("rounds",[])
                if r["action"]=="pick" and r["round"]==1 and
                   r["games"]>=3 and r["share"]>=50]
    if priorities:
        r=max(priorities,key=lambda v:(v["games"],v["share"]))
        messages.append({"kind":"priority","title":f"{r['sideLabel']}优先选用：{r['hero']}",
                         "detail":f"有序 BP 中第 1 次选用该英雄 {r['games']}/{r['opportunities']} 局。",
                         "action":"提前准备该英雄被抢、被禁时的候选选择。",
                         "evidence":r["evidence"]})
    player=studies.get("players",[])
    if player:
        top=next((r for r in player if r["games"]>=4 and r["mainHeroShare"]>=60),None)
        if top:
            h=top["heroes"][0]
            messages.append({"kind":"pool","title":f"选手英雄集中：{top['player']} · {h['hero']}",
                             "detail":f"{top['games']} 局记录中 {h['games']} 局使用该英雄，占 {h['share']}%。",
                             "action":"结合赛制、对位与备选英雄判断是否需要限制。",
                             "evidence":h["evidence"]})
    # Coach brief is intentionally concise; never infer causes or winning counters.
    return messages[:3]
