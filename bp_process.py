"""Evidence-only join between scrim BP records and match replay process bundles.

A process match is accepted only when date, own camp, both complete five-hero
lineups and (where available) duration agree, and exactly one candidate matches.
Do not infer lane economy from team gold, raw slot order or final scoreboard.
"""
from __future__ import annotations

from collections import defaultdict
from math import isfinite


CHECKPOINTS = (120, 240, 600)


def _finite(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return number if isfinite(number) else None


def _hero(item):
    return str((item.get("name") or item.get("hero") or "") if isinstance(item, dict)
               else (item or "")).strip()


def _clean_date(value):
    text = str(value or "").strip()
    if len(text) < 10 or text[4] != "-" or text[7] != "-":
        return ""
    return text[:10]


def _team_heroes(picks):
    heroes = [_hero(row) for row in (picks or [])]
    if len(heroes) != 5 or len(set(heroes)) != 5 or not all(heroes):
        return None
    return tuple(sorted(heroes))


def _bp_key(row):
    own = (row.get("picks") or {}).get("own")
    foe = (row.get("picks") or {}).get("enemy")
    own_heroes = _team_heroes(own)
    foe_heroes = _team_heroes(foe)
    side = str(row.get("side") or "").lower()
    day = _clean_date(row.get("day") or row.get("start"))
    if not (own_heroes and foe_heroes and side in ("blue", "red") and day):
        return None
    return day, side, own_heroes, foe_heroes


def _match_key(match):
    date = _clean_date(match.get("date"))
    own = str(match.get("ownCamp") or "").lower()
    if own not in ("blue", "red") or not date:
        return None
    sides = defaultdict(list)
    for player in match.get("players") or []:
        if not isinstance(player, dict):
            continue
        camp = str(player.get("camp") or "").lower()
        if camp in ("blue", "red"):
            sides[camp].append(_hero(player.get("hero")))
    other = "red" if own == "blue" else "blue"
    own_heroes = _team_heroes(sides[own])
    enemy_heroes = _team_heroes(sides[other])
    if not own_heroes or not enemy_heroes:
        return None
    return date, own, own_heroes, enemy_heroes


def _duration_agrees(bp, match):
    a, b = _finite(bp.get("duration")), _finite(match.get("duration"))
    if a is None or b is None or min(a, b) <= 0:
        return True  # never guess a duration; other keys must be uniquely matched
    return abs(a - b) <= 45


def _interpolate(points, at):
    """No distant interpolation, no extrapolation, no false precision."""
    if not points or not points[0][0] <= at <= points[-1][0]:
        return None
    for t, value in points:
        if t == at:
            return round(value, 1)
    for (t0, v0), (t1, v1) in zip(points, points[1:]):
        if t0 <= at <= t1:
            if t1 - t0 > 120 or max(at - t0, t1 - at) > 75:
                return None
            return round(v0 + (v1 - v0) * (at - t0) / (t1 - t0), 1)
    return None


def _gold_diff(match, own):
    process = match.get("process") or {}
    points = []
    duration = _finite(match.get("duration"))
    for item in process.get("timeline") or []:
        if not isinstance(item, dict):
            continue
        t = _finite(item.get("gameTime"))
        blue, red = _finite(item.get("blueGold")), _finite(item.get("redGold"))
        if t is None or blue is None or red is None or t < 0 or min(blue, red) < 0:
            continue
        if duration is not None and t > duration + 1:
            continue
        points.append((t, blue - red if own == "blue" else red - blue))
    # A timestamp appearing twice with contradictory measurements is rejected.
    seen, duplicate = {}, set()
    for t, value in points:
        if t in seen and abs(seen[t] - value) > 1:
            duplicate.add(t)
        else:
            seen[t] = value
    points = sorted((t, value) for t, value in seen.items() if t not in duplicate)
    return {str(check): _interpolate(points, check) for check in CHECKPOINTS}


def _lane_name(value):
    text = str(value or "").strip()
    return {"辅助": "游走", "射手": "发育路", "边路": "对抗路"}.get(text, text)


def _player_pairs(match):
    """Match by verified in-game role, never by lineup position or slot ordering."""
    lanes = defaultdict(lambda: defaultdict(list))
    for player in match.get("players") or []:
        if not isinstance(player, dict):
            continue
        camp, hero = player.get("camp"), _hero(player.get("hero"))
        lane = _lane_name(player.get("position"))
        if camp not in ("blue", "red") or not hero or not lane:
            continue
        lanes[lane][camp].append(hero)
    paired = {}
    for lane, sides in lanes.items():
        if len(sides["blue"]) != 1 or len(sides["red"]) != 1:
            continue
        blue, red = sides["blue"][0], sides["red"][0]
        paired[("blue", blue)] = ("red", red)
        paired[("red", red)] = ("blue", blue)
    return paired


def _snapshot_golds(match, at):
    """One nearest verified snapshot within 30 seconds; complete individual values only."""
    snapshots = []
    for snapshot in (match.get("process") or {}).get("scoreboardSnapshots") or []:
        if not isinstance(snapshot, dict):
            continue
        t = _finite(snapshot.get("gameTime"))
        if t is None or abs(t - at) > 30:
            continue
        rows = defaultdict(list)
        for player in snapshot.get("players") or []:
            if not isinstance(player, dict):
                continue
            camp, hero = str(player.get("camp") or ""), _hero(player.get("hero"))
            gold = _finite(player.get("totalGold"))
            if camp in ("blue", "red") and hero and gold is not None and gold >= 0:
                rows[(camp, hero)].append(gold)
        unique = {key: values[0] for key, values in rows.items() if len(values) == 1}
        if unique:
            snapshots.append((abs(t - at), t, unique))
    if not snapshots:
        return {}
    snapshots.sort(key=lambda item: (item[0], item[1]))
    if len(snapshots) > 1 and snapshots[0][0] == snapshots[1][0]:
        # Ambiguous equidistant snapshots: do not silently choose one.
        return {}
    return snapshots[0][2]


def process_match(match):
    own = str(match.get("ownCamp") or "")
    if own not in ("blue", "red"):
        return None
    paired = _player_pairs(match)
    lane_diff = {}
    for check in (240, 600):
        current = _snapshot_golds(match, check)
        out = {}
        for hero_id, other in paired.items():
            if hero_id in current and other in current:
                out[hero_id[1]] = round(current[hero_id] - current[other], 1)
        lane_diff[str(check)] = out
    return {
        "matchKey": str(match.get("key") or ""),
        "teamDiffOwn": _gold_diff(match, own),
        "laneDiffByHero": lane_diff,
        "source": "verified-match-bundle",
    }


def link_scrim_process(bp_rows, match_rows):
    """Return a map keyed by scrim game id; ambiguous matches are never joined."""
    candidates = defaultdict(list)
    for match in match_rows or []:
        if not isinstance(match, dict):
            continue
        key = _match_key(match)
        if not key or not match.get("key"):
            continue
        candidates[key].append(match)
    # Uniqueness must hold in both directions. Two scrims with identical
    # lineups/day/side may otherwise silently attach the same single replay.
    proposals = defaultdict(list)
    for bp in bp_rows or []:
        if not isinstance(bp, dict):
            continue
        key, identity = _bp_key(bp), str(bp.get("key") or "")
        if not key or not identity:
            continue
        found = [match for match in candidates.get(key, ())
                 if _duration_agrees(bp, match)]
        if len(found) == 1:
            proposals[str(found[0]["key"])].append((identity, found[0]))
    linked = {}
    for proposals_for_match in proposals.values():
        unique_ids = {identity for identity, _ in proposals_for_match}
        if len(unique_ids) != 1:
            continue
        identity, match = proposals_for_match[0]
        result = process_match(match)
        if result:
            linked[identity] = result
    return linked
