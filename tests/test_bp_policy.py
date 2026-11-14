"""Temporal BP prediction guardrails: no future data in training, no illegal picks."""
from copy import deepcopy

from bp_policy import _decisions, _top_n, next_pick_policy


def record(i, date, first="马超", trigger="夏洛特"):
    own = [first,"镜","小乔","孙尚香","张飞"]
    foe = [trigger,"暃","沈梦溪","狄仁杰","太乙真人"]
    sequence = []
    sequence.append(("team","ban","朵莉亚"))
    sequence.append(("enemy","ban","亚连"))
    sequence.append(("enemy","pick",foe[0]))
    sequence.append(("team","pick",own[0]))
    sequence.append(("team","pick",own[1]))
    sequence.append(("enemy","pick",foe[1]))
    sequence.append(("team","pick",own[2]))
    sequence.append(("enemy","pick",foe[2]))
    sequence.append(("team","pick",own[3]))
    sequence.append(("enemy","pick",foe[3]))
    sequence.append(("team","pick",own[4]))
    sequence.append(("enemy","pick",foe[4]))
    events=[{"order":i+1,"actor":actor,"action":action,"hero":hero}
            for i,(actor,action,hero) in enumerate(sequence)]
    return {"id":"m"+str(i),"date":date,"team":"战队甲","enemy":"战队乙",
            "side":"1", "picks":own,"enemyPicks":foe,"events":events,
            "result":True,"matchId":"series"+str(i),
            "source":"kpl","version":"patch-a"}


def test_pick_context_cannot_see_future_action_or_repick_occupied_hero():
    game=record(1,"2026-11-01")
    actions=list(_decisions(game))
    assert len(actions)==5
    first=actions[0]
    assert first["opponentHero"]=="夏洛特"
    assert "夏洛特" in first["unavailable"]
    assert "镜" not in first["unavailable"]
    assert first["hero"]=="马超"
    assert _top_n(__import__("collections").Counter({"夏洛特":99,"马超":20,"镜":18}),
                  first["unavailable"])==["马超","镜"]


def test_policy_requires_real_dated_out_of_sample_games():
    rows=[record(i,"2026-11-01") for i in range(50)]
    assert next_pick_policy(rows)["status"]=="insufficient"
    assert next_pick_policy([])["status"]=="insufficient"


def test_conditioned_policy_reports_holdout_scores_without_claiming_optimum():
    rows=[record(i,"2026-11-"+str(i//4+1).zfill(2)) for i in range(24)]
    result=next_pick_policy(rows)
    assert result["status"]=="tested"
    assert result["trainGames"]==16
    assert result["testGames"]==8
    assert result["testDecisions"]>=20
    assert result["baselineTop3"]==100
    assert result["conditionTop3"]==100
    assert result["gainPP"]==0
    assert not result["supported"]
    assert result["contexts"][0]["options"][0]["games"]>=4


def test_training_contexts_do_not_change_when_future_games_are_edited():
    rows=[record(i,"2026-11-"+str(i//4+1).zfill(2)) for i in range(24)]
    baseline=next_pick_policy(rows)
    changed=deepcopy(rows)
    for row in changed[16:]:
        row["events"][3]["hero"]="花木兰"
        row["picks"][0]="花木兰"
    updated=next_pick_policy(changed)
    assert updated["trainGames"]==baseline["trainGames"]
    assert updated["contexts"]==baseline["contexts"]
    assert updated["conditionTop3"] < baseline["conditionTop3"]
