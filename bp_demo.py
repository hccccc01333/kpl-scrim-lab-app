"""征召（draft-18）模拟数据，仅用于界面验证。

本机营地语料是排位/巅峰（rank-20），没有真正的自定义房间征召局。
`bp_studio` 在 ``demo=1`` 时用这里生成的 8 局 18 手对局替换训练赛数据，
让「征召 18 手」页签有可看的样本；不写任何文件、不计入真实统计。

数据形状与 `bp_intelligence.normalize_scrims` 的输出一致，队伍固定为
``本队`` vs ``模拟对手A/B``，日期在近 30 天内。
"""
from __future__ import annotations

import random
from collections import defaultdict

from bp_formats import DRAFT_18
from hero_archetypes import HERO_ARCHETYPES, default_lane

LANES = ("对抗路", "打野", "中路", "发育路", "游走")
TEAM = "本队"
ENEMIES = ("模拟对手A", "模拟对手B")


def _by_lane():
    groups = defaultdict(list)
    for name in HERO_ARCHETYPES:
        lane = default_lane(name) or "其他"
        groups[lane].append(name)
    return groups


def _take_lane(groups, lane, used, rng):
    pool = [hero for hero in groups.get(lane) or [] if hero not in used]
    if not pool:
        pool = [hero for heroes in groups.values() for hero in heroes if hero not in used]
    if not pool:
        raise ValueError("英雄池不足")
    hero = rng.choice(pool)
    used.add(hero)
    return hero


def _side_picks(rng, groups, used):
    picks = []
    for lane in LANES:
        hero = _take_lane(groups, lane, used, rng)
        picks.append({"name": hero, "lane": lane,
                      "archetype": HERO_ARCHETYPES.get(hero, {}).get(lane, "")})
    return picks


def _side_bans(rng, groups, used, count=4):
    pool = [hero for heroes in groups.values() for hero in heroes if hero not in used]
    rng.shuffle(pool)
    bans = pool[:count]
    used.update(bans)
    return [{"name": hero, "lane": default_lane(hero) or "",
             "archetype": HERO_ARCHETYPES.get(hero, {}).get(default_lane(hero), "")}
            for hero in bans]


def _players(team, picks, rng):
    rows = []
    for index, entry in enumerate(picks):
        rows.append({
            "name": f"{team}·{entry['lane']}",
            "hero": entry["name"],
            "lane": entry["lane"],
            "kills": rng.randint(0, 9),
            "deaths": rng.randint(0, 6),
            "assists": rng.randint(1, 14),
            "gold": rng.randint(6000, 12000),
            "heroDamage": rng.randint(12000, 45000),
            "taken": rng.randint(10000, 40000),
            "participation": round(rng.uniform(0.45, 0.85), 3),
            "towers": rng.randint(0, 4),
        })
    return rows


def _build_events(queues, own_camp):
    events = []
    for step in DRAFT_18.schedule:
        hero = queues[step["camp"]][step["action"]].pop(0)
        events.append({
            "order": step["order"], "phase": step["phase"],
            "action": step["action"], "camp": step["camp"], "hero": hero,
            "actor": "team" if step["camp"] == own_camp else "enemy",
        })
    return events


def scrim_games(count=8):
    """生成 ``count`` 局征召 18 手模拟对局（4 局/对手，BO5 形状）。"""
    rng = random.Random(20261118)
    groups = _by_lane()
    games = []
    for index in range(count):
        enemy = ENEMIES[index // 4 % len(ENEMIES)]
        side = "blue" if index % 2 == 0 else "red"
        own_camp = "1" if side == "blue" else "2"
        used = set()

        if own_camp == "1":
            own_picks = _side_picks(rng, groups, used)
            foe_picks = _side_picks(rng, groups, used)
            own_bans = _side_bans(rng, groups, used)
            foe_bans = _side_bans(rng, groups, used)
        else:
            foe_picks = _side_picks(rng, groups, used)
            own_picks = _side_picks(rng, groups, used)
            foe_bans = _side_bans(rng, groups, used)
            own_bans = _side_bans(rng, groups, used)

        queues = {
            own_camp: {"ban": [x["name"] for x in own_bans],
                       "pick": [x["name"] for x in own_picks]},
            ("2" if own_camp == "1" else "1"): {
                "ban": [x["name"] for x in foe_bans],
                "pick": [x["name"] for x in foe_picks],
            },
        }
        events = _build_events(queues, own_camp)
        result = index % 3 != 1
        games.append({
            "id": f"demo-scrim-{index + 1}",
            "date": f"2026-11-{4 + index:02d}",
            "day": f"2026-11-{4 + index:02d}",
            "team": TEAM, "enemy": enemy,
            "side": side, "ownSide": "left" if side == "blue" else "right",
            "picks": [x["name"] for x in own_picks],
            "bans": [x["name"] for x in own_bans],
            "enemyPicks": [x["name"] for x in foe_picks],
            "enemyBans": [x["name"] for x in foe_bans],
            "players": _players(TEAM, own_picks, rng),
            "enemyPlayers": _players(enemy, foe_picks, rng),
            "result": result,
            "events": events,
            "source": "scrim", "matchId": f"demo-{index // 4 + 1}",
            "league": "模拟训练赛", "version": "DEMO", "stage": "模拟",
            "ruleProfile": "draft-18", "ruleValidated": True,
            "bpMode": "scrim", "pickOrderKnown": True, "bansKnown": True,
            "gameSeq": index % 4 + 1,
        })
    return games
