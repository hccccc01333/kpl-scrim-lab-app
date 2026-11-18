"""BP 时序分支树：只认已核验 events，前缀合并，主路径取样本最多。"""
from __future__ import annotations

from bp_studio import draft_tree

SCHEDULE = [("ban", "team"), ("ban", "enemy"), ("ban", "team"), ("ban", "enemy"),
            ("pick", "team"), ("pick", "enemy"), ("pick", "enemy"), ("pick", "team")]


def game(index, heroes, *, team="A队", enemy="B队", result=True, events=True):
    hands = [{"order": order, "action": action, "actor": actor, "hero": hero}
             for order, ((action, actor), hero) in enumerate(zip(SCHEDULE, heroes), 1)]
    return {"id": f"g{index}", "date": f"2026-11-{10 + index:02d}",
            "team": team, "enemy": enemy, "result": result,
            "events": hands if events else []}


def test_tree_main_path_and_branch_counts():
    games = [
        game(1, ["盾山", "大乔", "澜", "张飞", "沈梦溪", "鲁班", "孙尚香", "张良"]),
        game(2, ["盾山", "大乔", "澜", "张飞", "沈梦溪", "鲁班", "孙尚香", "张良"]),
        game(3, ["盾山", "大乔", "澜", "张飞", "海月", "鲁班", "孙尚香", "张良"]),
    ]
    tree = draft_tree(games, team="A队", depth=6, branch=2)
    assert tree["available"] is True
    assert tree["games"] == 3 and tree["total"] == 3
    main = [node for node in tree["nodes"] if node["id"] in tree["main"]]
    assert [node["hero"] for node in main[:2]] == ["盾山", "大乔"]
    assert tree["main"][0].endswith("盾山")


def test_tree_skips_games_without_events():
    games = [game(1, ["盾山"] * 8, events=False),
             game(2, ["大乔"] * 8)]
    tree = draft_tree(games, team="A队", depth=6, branch=2)
    assert tree["available"] is True
    assert tree["games"] == 1 and tree["total"] == 2


def test_tree_empty_reports_reason():
    tree = draft_tree([game(1, ["盾山"] * 8, events=False)], team="A队")
    assert tree["available"] is False
    assert tree["reason"]
    assert tree["nodes"] == []
