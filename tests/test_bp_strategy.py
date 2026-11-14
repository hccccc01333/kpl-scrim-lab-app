"""BP-exclusive behavior studies: no invented patches, turns or counter effects."""
from bp_strategy import (side_round_study, version_study, player_pool_study,
                         matchup_study, draft_two_step_study, coach_brief)
from bp_interactions import interaction_study
from bp_intelligence import build_report


OWN = ["夏洛特", "镜", "小乔", "公孙离", "鲁班大师"]
ENEMY = ["马超", "赵云", "沈梦溪", "孙尚香", "张飞"]


def game(i, *, date="2026-11-01", side="1", version="V1", win=True):
    return {
        "id": "m"+str(i), "date": date, "team": "战队A", "enemy": "战队B",
        "side":side, "picks":list(OWN), "bans":["吕布","亚连"],
        "enemyPicks":list(ENEMY),"enemyBans":["关羽","朵莉亚"],
        "players":[{"name":"选手A","hero":"夏洛特","lane":"对抗路"}],
        "enemyPlayers":[{"name":"选手B","hero":"马超","lane":"对抗路"}],
        "events":[
            {"order":1,"actor":"enemy","action":"ban","hero":"关羽"},
            {"order":2,"actor":"team","action":"ban","hero":"吕布"},
            {"order":3,"actor":"enemy","action":"pick","hero":"马超"},
            {"order":4,"actor":"team","action":"pick","hero":"夏洛特"},
            {"order":5,"actor":"enemy","action":"pick","hero":"赵云"},
            {"order":6,"actor":"team","action":"pick","hero":"镜"},
        ],
        "result":win,"source":"kpl","matchId":"series"+str(i),"gameSeq":1,
        "version":version,"processMatchKey":"",
    }


def test_side_uses_actual_team_blue_red_and_first_round():
    rows=[game(i,side="1" if i<4 else "2") for i in range(8)]
    result=side_round_study(rows)
    assert [r["games"] for r in result["sides"]]==[4,4]
    blue=next(r for r in result["rounds"] if r["side"]=="1" and
              r["action"]=="pick" and r["round"]==1 and r["hero"]=="夏洛特")
    assert blue["games"]==4 and blue["opportunities"]==4 and blue["share"]==100
    ban=next(r for r in result["rounds"] if r["side"]=="1" and
              r["action"]=="ban" and r["hero"]=="吕布")
    assert ban["round"]==1


def test_missing_patch_never_inferred_from_year():
    rows=[game(i,version="") for i in range(6)]
    r=version_study(rows,rows)
    assert r["coverage"]=={"games":6,"knownGames":0}
    assert r["options"]==[] and r["changes"]==[] and not r["available"]


def test_genuine_patch_transition_and_narrow_period_filter():
    rows=[game(i,date="2026-11-01",version="V1") for i in range(4)]
    rows += [game(i+4,date="2026-11-05",version="V2") for i in range(4)]
    for row in rows[4:]:
        row["picks"][2]="王昭君"
    report=version_study(rows,rows)
    assert report["available"] and report["before"]=="V1" and report["after"]=="V2"
    assert any(x["hero"]=="王昭君" and x["changePP"]>0 for x in report["changes"])


def test_player_pool_uses_only_verified_player_records():
    rows=[game(i) for i in range(5)]
    rows[4]["players"]=[]
    report=player_pool_study(rows)
    player=report[0]
    assert player["player"]=="选手A" and player["games"]==4
    assert player["mainHeroShare"]==100
    assert player["uniqueHeroes"]==1


def test_opponent_core_lineups_and_recorded_two_step_responses():
    rows=[game(i) for i in range(4)]
    report=matchup_study(rows)
    found=next(r for r in report if r["size"]==3 and
               r["candidate"]=="夏洛特" and r["enemyCore"]==["孙尚香","张飞","沈梦溪"])
    assert found["games"]==4 and found["winRate"]==100
    assert found["interval"][0]<100
    tree=draft_two_step_study(rows)
    branch=next(r for r in tree if r["trigger"]=="马超")
    assert branch["games"]==4
    assert any(b["ownPick"]=="夏洛特" and b["enemyNext"]=="赵云" and
               b["opportunities"]==4 for b in branch["branches"])


def test_brief_not_fake_best_pick_or_causal_counter():
    rows=[game(i,version="V1") for i in range(6)]
    study={"draft":side_round_study(rows),"version":version_study(rows,rows),
           "players":player_pool_study(rows)}
    results=coach_brief(study,rows)
    assert all("胜率最优" not in x["title"] for x in results)
    assert any(x["kind"]=="priority" for x in results)


def test_interaction_model_rejects_insufficient_and_has_forward_split():
    small=interaction_study([game(i) for i in range(20)])
    assert small["status"]=="insufficient" and not small["signals"]
    rows=[]
    for i in range(60):
        item=game(i,date="2026-11-"+str(i//10+1).zfill(2),
                  win=(i % 4 in (0,1)))
        # In some matches the heroes vary, but avoid ever using simulated
        # counterfactual winner as a positive label.
        if i%3==0:
            item["picks"][0]="花木兰"
        if i%5==0:
            item["enemyPicks"][0]="孙策"
        rows.append(item)
    result=interaction_study(rows)
    assert result["status"]=="tested"
    assert result["train"]==40 and result["test"]==20
    assert 0<=result["baseline"]["brier"]<=1
    assert 0<=result["extended"]["brier"]<=1
    if not result["improved"]:
        assert result["signals"]==[]


def test_version_filter_keeps_patch_comparison_and_selected_scope():
    def raw(i,patch):
        picks1=list(OWN) if patch=="V1" else [OWN[0],OWN[1],"王昭君",OWN[3],OWN[4]]
        events=[]
        order=0
        for camp,action,hero in ([(1,"ban","吕布"),(2,"ban","关羽")]
                                  +[(1,"pick",h) for h in picks1]
                                  +[(2,"pick",h) for h in ENEMY]):
            order+=1
            events.append({"order":order,"camp":str(camp),"action":action,"hero":hero})
        return {"battleId":"b"+str(i), "date":"2026-11-01" if patch=="V1" else "2026-11-06",
                "camp1":{"team":"战队A"},"camp2":{"team":"战队B"},
                "picks":{"1":picks1,"2":ENEMY},"bans":{"1":["吕布"],"2":["关羽"]},
                "winCamp":1, "version":patch,"bansKnown":True,"pickOrderKnown":True,
                "draftEvents":events}
    games=[raw(i,"V1" if i<4 else "V2") for i in range(8)]
    report=build_report([],games,source="kpl",team="战队A",version="V2")
    assert report["scope"]["games"]==4
    assert report["bpStudies"]["version"]["before"]=="V1"
    assert report["bpStudies"]["version"]["after"]=="V2"
    assert all(x["hero"] not in ("小乔",) for x in report["picks"])
