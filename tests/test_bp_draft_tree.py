"""Complete historical BP traversal and conservative pre-match priorities."""
from bp_draft_tree import draft_tree, priority_brief
from bp_intelligence import build_report


def record(i, *, team="战队甲", hero="马超", first_ban="朵莉亚", win=True):
    own = [hero, "镜", "小乔", "孙尚香", "张飞"]
    enemy = ["夏洛特", "暃", "沈梦溪", "狄仁杰", "太乙真人"]
    events = [
        {"order": 1, "actor": "team", "action": "ban", "hero": first_ban},
        {"order": 2, "actor": "enemy", "action": "ban", "hero": "亚连"},
        {"order": 3, "actor": "enemy", "action": "pick", "hero": enemy[0]},
        {"order": 4, "actor": "team", "action": "pick", "hero": own[0]},
        {"order": 5, "actor": "team", "action": "pick", "hero": own[1]},
        {"order": 6, "actor": "enemy", "action": "pick", "hero": enemy[1]},
    ]
    return {"id": "match"+str(i), "team": team, "date": "2026-11-"+str((i%16)+1).zfill(2),
            "enemy": "对手队", "side": "1", "picks": own,
            "enemyPicks": enemy, "bans": [first_ban], "enemyBans": ["亚连"],
            "events": events, "source": "kpl", "matchId": "series"+str(i//2),
            "players": [], "result": win, "version": "patch-1",
            "processMatchKey": ""}


def test_multi_round_draft_tree_is_real_prefix_traversal():
    games = [record(i,first_ban="朵莉亚" if i < 7 else "大乔") for i in range(10)]
    tree=draft_tree(games)
    assert tree["orderedGames"] == tree["indexedGames"] == 10
    nodes=tree["nodes"]
    root=next(r for r in nodes if r["id"]==0)
    assert root["games"]==10
    bans=[r for r in nodes if r["parent"]==0]
    assert sorted(r["games"] for r in bans)==[3,7]
    assert {r["action"] for r in bans} == {"ban"}
    chosen=next(r for r in bans if r["hero"]=="朵莉亚")
    assert chosen["games"]==7
    path=[chosen]
    while path[-1]["depth"] < 6:
        child=next(r for r in nodes if r["parent"]==path[-1]["id"])
        path.append(child)
    assert [r["hero"] for r in path[-3:]]==["马超","镜","暃"]
    assert path[-1]["games"]==7
    assert all("id" in item for item in path[-1]["evidence"])


def test_only_verified_ordered_matches_indexed():
    games=[record(1),record(2)]
    games[1]["events"]=[]
    tree=draft_tree(games)
    assert tree["orderedGames"] == 1 and tree["indexedGames"] == 1
    assert tree["nodes"][0]["games"]==1


def test_historical_tree_is_limited_and_reports_coverage():
    games=[record(i) for i in range(11)]
    result=draft_tree(games,max_games=3)
    assert result["orderedGames"]==11 and result["indexedGames"]==3
    assert result["limited"] is True
    assert all(r["games"]<=3 for r in result["nodes"])


def test_priority_compares_selected_team_to_other_teams_with_evidence():
    focus=[record(i) for i in range(12)]
    other=[record(i+40,team="战队乙",hero="马超" if i<2 else "花木兰")
           for i in range(40)]
    findings=priority_brief(focus,focus+other)
    candidate=next(x for x in findings if x["kind"]=="relative-preference"
                   and "马超" in x["title"])
    assert candidate["level"]=="重点"
    assert "12/12" in candidate["detail"]
    assert len(candidate["evidence"])<=6
    assert candidate["referenceGames"]==40


def test_priorities_decline_to_compare_when_no_other_team_exists():
    focus=[record(i) for i in range(12)]
    assert not priority_brief(focus,focus)
    extra=[{"kind":"priority","title":"观察首抢","detail":"样本","action":"研究",
            "evidence":[{"id":"match-1"}]}]
    result=priority_brief(focus,focus,extra)
    assert result and result[0]["level"]=="观察"


def test_report_keeps_a_replayable_tree_for_selected_team_only():
    games=[]
    for i in range(8):
        row=record(i)
        # normalized KPL input uses camp/actors and fully checked final picks
        events=[{"order":e["order"],"camp":"1" if e["actor"]=="team" else "2",
                 "action":e["action"],"hero":e["hero"]} for e in row["events"]]
        # Fill the missing final actions to satisfy the strict input validator.
        idx=len(events)
        for h in row["picks"][2:]:
            idx+=1
            events.append({"order":idx,"camp":"1","action":"pick","hero":h})
        for h in row["enemyPicks"][2:]:
            idx+=1
            events.append({"order":idx,"camp":"2","action":"pick","hero":h})
        games.append({
            "battleId":row["id"],"date":row["date"],"matchId":row["matchId"],
            "camp1":{"team":"战队甲"},"camp2":{"team":"对手队"},
            "picks":{"1":row["picks"],"2":row["enemyPicks"]},
            "bans":{"1":row["bans"],"2":row["enemyBans"]},
            "draftEvents":events,"bansKnown":True,"pickOrderKnown":True,
            "winCamp":1,
        })
    report=build_report([],games,source="kpl",team="战队甲")
    tree=report["bpStudies"]["draftTree"]
    assert tree["indexedGames"]==8 and len(tree["nodes"])>4
    assert report["scope"]["orderedGames"]==8
    assert all(x["team"]=="战队甲" for x in tree["nodes"][0]["evidence"])
    league=build_report([],games,source="kpl",team="")
    assert league["bpStudies"]["draftTree"]["nodes"]==[]
