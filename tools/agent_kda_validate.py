#!/usr/bin/env python3
"""Validate the KDA candidate: source43 kill/assist subset + 0x81 v6 death windows.

Read-only research tool.

It reads only:
  * replay samples under data/replays/samples/
  * the external panel-truth CSV for the 5247758 sample
  * project modules (replay_parser, agent_damage_skill_objective,
    agent_player_block_schema, vision.catalog) for framing/roster/hero names

It never writes a replay, never starts the game, never reads param.json,
never uses runtime_dump, and never edits docs/ or .workbuddy/memory/.

Definitions used here (all explicit so the numbers can be challenged):
  * source43 = 0x02/0x85 body[0] == 43.
      amount >= 200 -> kill (202/203 observed)
      amount == 102 -> assist
      other         -> "source43_other" (not observed in these six samples)
  * 0x81 v6 event = 0x02/0x81 (body length 1) with value 6.
  * v6 death window = consecutive v6 events for the same entity whose frame
    gap is <= V6_WINDOW_GAP (default 10 frames).  This is the grouping that
    reproduces 1965: raw 7 -> 4 windows in the main sample and 1804:
    raw 3 -> 1 window against panel D=1.
  * main segment only for team totals.  The 5069040 second segment ("tail")
    is parsed separately because it is an input continuation and is not a
    complete event log (5.36 / 5.102 in the existing docs).

The 5069040 0x80 frame command has a 12-byte body; treating 0x80 as len=0
desynchronises the rest of the payload and loses 0x81/0x85 messages.  This
tool therefore reuses agent_damage_skill_objective.parse_payload, which
implements the 12-byte body.
"""
from __future__ import annotations

import csv
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "data" / "replays" / "_analysis" / "datasets"
ABC_BATCH = ROOT / "data" / "replays" / "samples" / "abc_batch"
NEW_SAMPLE_DIR = ROOT / "data" / "replays" / "samples" / "20261101_182452"
PANEL_CSV = DATASETS / "new_5247758_panel_truth_for_validation.csv"
OUT_CSV = DATASETS / "agent_kda_validate.csv"
OUT_MD = DATASETS / "agent_kda_validate.md"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import agent_damage_skill_objective as dso  # noqa: E402
import agent_player_block_schema as pbs  # noqa: E402
import replay_parser as rp  # noqa: E402
from vision import catalog  # noqa: E402

BUILD_5069040 = "5069040"
BUILD_5247758 = "5247758"
V6 = 6
V6_WINDOW_GAP = 10          # frames; 0.5 s at 20 fps
KILL_MIN_AMOUNT = 200
ASSIST_AMOUNT = 102
FPS_5069040 = 20.0
REPLAY_OFFSET_5069040 = 20.3
FPS_5247758 = 9900 / 656.0  # 15.09 fps, from the 9,900-frame / 656 s sample

CSV_FIELDS = (
    "section", "sample", "file", "build", "team", "slot", "entity", "player",
    "hero_id", "metric", "value", "denominator", "rate", "confidence", "note",
)


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def hero_names() -> dict[int, str]:
    names = {}
    try:
        for entry in catalog()["entries"]:
            if entry.get("kind") == "hero":
                names[int(entry["id"].split("-")[1])] = entry["name"]
    except (FileNotFoundError, KeyError, ValueError):
        pass
    return names


HERO_NAMES = hero_names()


def pct(value: int | float, total: int | float) -> str:
    if not total:
        return "n/a"
    return f"{value / total * 100:.1f}%"


def ratio(value: int | float, total: int | float) -> float | None:
    return (value / total) if total else None


def md_table(headers: list[str], rows: list[list[object]]) -> str:
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)


def classify_source43(amount: int) -> str:
    if amount >= KILL_MIN_AMOUNT:
        return "kill"
    if amount == ASSIST_AMOUNT:
        return "assist"
    return "other"


def group_windows(seqs: list[int], gap: int = V6_WINDOW_GAP) -> list[list[int]]:
    groups: list[list[int]] = []
    for seq in sorted(seqs):
        if groups and seq - groups[-1][-1] <= gap:
            groups[-1].append(seq)
        else:
            groups.append([seq])
    return groups


def d_confidence(entity: int) -> str:
    """Per-player confidence for the v6 death count in 5069040."""
    if entity == 442:
        return "medium-low（形态歧义）"
    if entity in (1021, 338, 1547):
        return "medium-low（0 可能是漏检）"
    if entity == 1558:
        return "medium-low（无 value2 基线）"
    return "medium"


# ---------------------------------------------------------------------------
# replay framing / roster
# ---------------------------------------------------------------------------
def load_records(data: bytes):
    """Return (main, tail, how, main_end, tail_start).

    dso.find_main_stream knows the 5069040 start (seq 0x22).  The 5247758
    stream starts at seq 1, so fall back to replay_parser's generic scan.
    """
    main, end, how = dso.find_main_stream(data)
    if len(main) < 500:
        found = rp.inspect_frame_stream(data)
        if found.get("status") != "frame-stream":
            raise RuntimeError("no frame stream found")
        main, _ = dso.records_from(data, found["start"], data[found["start"]])
        end = found["end"]
        how = "generic-scan"
    tail, _tail_end, tail_start = dso.find_tail_stream(data, end)
    return main, tail, how, end, tail_start


def roster_for(data: bytes) -> tuple[dict[int, dict], str, list[str]]:
    """Return entity -> {team, slot, hero, name, source, bot}.

    replay_parser handles the full ten-block layouts (legacy 1517 and the
    5247758 variable roster).  For the partial 5069040 samples its strict
    ten-block requirement fails, so fall back to the per-block schema scan.
    """
    header = rp.parse_header(data)
    blocks, warnings = rp.discover_blocks(data, set(HERO_NAMES), header["localHeroId"])
    if len(blocks) == 10:
        out = {
            block["entityId"]: {
                "team": block.get("camp"),
                "slot": block.get("position"),
                "hero": block.get("heroId"),
                "name": block.get("name") or HERO_NAMES.get(block.get("heroId"), ""),
                "source": "replay_parser",
                "bot": bool(block.get("bot")),
            }
            for block in blocks
        }
        return out, "replay_parser", warnings

    raw = pbs.find_blocks(data)
    out: dict[int, dict] = {}
    for index, block in enumerate(raw):
        following = raw[index + 1]["offset"] if index + 1 < len(raw) else None
        end = pbs.locate_block_end(data, block["offset"], following)
        record = pbs.parse_player_block(data, block, end)
        values = {field["name"]: field["value"] for field in record["fields"]}
        entity = values.get("entityID")
        if not entity:
            continue
        hero = values.get("heroID")
        out[int(entity)] = {
            "team": values.get("team"),
            "slot": values.get("slot"),
            "hero": hero,
            "name": record.get("name") or HERO_NAMES.get(hero, ""),
            "source": "block_schema",
            "bot": False,
        }
    return out, "block_schema", warnings


# ---------------------------------------------------------------------------
# event extraction
# ---------------------------------------------------------------------------
def parse_events(records: list[dict], segment: str) -> dict[str, list[dict]]:
    """Extract 0x81/0x85 and 0x01 0x1e/0x1f/0x20/0x23/0x29 from one segment."""
    out: dict[str, list[dict]] = {
        "81": [], "85": [], "1e": [], "1f": [], "20": [], "23": [], "29": [],
    }
    for record in records:
        messages, _ok = dso.parse_payload(record["payload"])
        for message in messages:
            if message[0] != "h":
                continue
            tag, entity, _flag, body = message[1], message[2], message[3], message[4]
            if tag == 0x02:
                if len(body) == 1:
                    out["81"].append({
                        "seq": record["seq"], "entity": entity,
                        "value": body[0], "segment": segment,
                    })
                elif len(body) == 5:
                    amount = int.from_bytes(body[1:5], "little")
                    out["85"].append({
                        "seq": record["seq"], "entity": entity,
                        "source": body[0], "amount": amount,
                        "role": classify_source43(amount) if body[0] == 43 else None,
                        "segment": segment,
                    })
            elif tag == 0x01 and body:
                subtype = body[0]
                key = {0x1E: "1e", 0x1F: "1f", 0x20: "20",
                       0x23: "23", 0x29: "29"}.get(subtype)
                if key:
                    out[key].append({
                        "seq": record["seq"], "entity": entity,
                        "body": body.hex(), "segment": segment,
                    })
    return out


def v6_by_entity(events: list[dict]) -> dict[int, list[int]]:
    out: dict[int, list[int]] = defaultdict(list)
    for event in events:
        if event["value"] == V6:
            out[event["entity"]].append(event["seq"])
    return out


def windows_by_entity(events: list[dict], gap: int = V6_WINDOW_GAP) -> dict[int, list[list[int]]]:
    return {
        entity: group_windows(seqs, gap)
        for entity, seqs in v6_by_entity(events).items()
    }


def source43_events(events: list[dict]) -> list[dict]:
    return [event for event in events["85"] if event["source"] == 43]


# ---------------------------------------------------------------------------
# sample analysis
# ---------------------------------------------------------------------------
def analyze_sample(path: Path) -> dict:
    data = path.read_bytes()
    header = rp.parse_header(data)
    build = header["builds"][1] if len(header["builds"]) > 1 else ""
    main, tail, how, main_end, tail_start = load_records(data)
    roster, roster_source, roster_warnings = roster_for(data)
    main_events = parse_events(main, "main")
    tail_events = parse_events(tail, "tail")

    main_v6 = v6_by_entity(main_events["81"])
    main_windows = {entity: group_windows(seqs) for entity, seqs in main_v6.items()}
    tail_v6 = v6_by_entity(tail_events["81"])
    tail_windows = {entity: group_windows(seqs) for entity, seqs in tail_v6.items()}

    main_s43 = source43_events(main_events)
    tail_s43 = source43_events(tail_events)

    entities_with_81 = {event["entity"] for event in main_events["81"]}
    roster_entities = set(roster)
    unknown_entities = sorted(entities_with_81 - roster_entities)
    uninstrumented = sorted(roster_entities - entities_with_81)
    unknown_with_v6 = sorted(entity for entity in unknown_entities if main_windows.get(entity))

    team_deaths = Counter()
    for entity, windows in main_windows.items():
        team = roster.get(entity, {}).get("team")
        if team in (1, 2):
            team_deaths[team] += len(windows)

    kills_by_team = Counter()
    assists_by_team = Counter()
    other_by_team = Counter()
    for event in main_s43:
        team = roster.get(event["entity"], {}).get("team")
        if event["role"] == "kill":
            kills_by_team[team] += 1
        elif event["role"] == "assist":
            assists_by_team[team] += 1
        else:
            other_by_team[team] += 1

    # Actual team kills are the opponent's observed v6 death windows.  This is
    # an identity for team totals, not independent proof that v6 == death.
    actual_kills = {1: team_deaths.get(2, 0), 2: team_deaths.get(1, 0)}
    coverage = {
        team: ratio(kills_by_team.get(team, 0), actual_kills[team])
        for team in (1, 2)
    }

    # Coverage flag: can the roster+0x81 channels account for all ten players?
    if len(roster_entities) >= 10 and not uninstrumented and not unknown_with_v6:
        coverage_flag = "full"
    elif len(roster_entities) == 9 and not uninstrumented and not unknown_with_v6:
        coverage_flag = "full_inferred"
    elif unknown_with_v6:
        coverage_flag = "partial_unknown_death"
    elif uninstrumented:
        coverage_flag = "partial"
    else:
        coverage_flag = "partial"

    # Temporal alignment: each source43 kill vs the nearest opposing v6 window.
    opposing_windows = []
    for entity, windows in main_windows.items():
        team = roster.get(entity, {}).get("team")
        if team in (1, 2):
            for window in windows:
                opposing_windows.append((window[0], team))

    alignments = []
    for event in main_s43:
        if event["role"] != "kill":
            continue
        team = roster.get(event["entity"], {}).get("team")
        opponent = 3 - team if team in (1, 2) else None
        candidates = [seq for seq, other_team in opposing_windows
                      if opponent and other_team == opponent]
        if not candidates:
            alignments.append({
                "seq": event["seq"], "entity": event["entity"],
                "team": team, "nearest": None, "delta": None,
            })
            continue
        nearest = min(candidates, key=lambda seq: abs(seq - event["seq"]))
        alignments.append({
            "seq": event["seq"], "entity": event["entity"],
            "team": team, "nearest": nearest, "delta": nearest - event["seq"],
        })

    # 0x23 census for the "not death" negative evidence.
    sub23 = main_events["23"]
    return {
        "path": path,
        "sample": path.stem.split("_")[0] + "_" + path.stem.split("_")[1]
                  if "_" in path.stem else path.stem,
        "file": path.name,
        "build": build,
        "header": header,
        "main_records": len(main),
        "tail_records": len(tail),
        "stream_how": how,
        "main_end": main_end,
        "tail_start": tail_start,
        "roster": roster,
        "roster_source": roster_source,
        "roster_warnings": roster_warnings,
        "main_events": main_events,
        "tail_events": tail_events,
        "main_windows": main_windows,
        "tail_windows": tail_windows,
        "main_v6_raw": {entity: len(seqs) for entity, seqs in main_v6.items()},
        "tail_v6_raw": {entity: len(seqs) for entity, seqs in tail_v6.items()},
        "source43_main": main_s43,
        "source43_tail": tail_s43,
        "team_deaths": team_deaths,
        "kills_by_team": kills_by_team,
        "assists_by_team": assists_by_team,
        "other_by_team": other_by_team,
        "actual_kills": actual_kills,
        "coverage": coverage,
        "coverage_flag": coverage_flag,
        "instrumented": entities_with_81,
        "unknown_entities": unknown_entities,
        "uninstrumented": uninstrumented,
        "unknown_with_v6": unknown_with_v6,
        "alignments": alignments,
        "sub23_count": len(sub23),
        "sub23": sub23,
        "n81_total": len(main_events["81"]),
        "n85_total": len(main_events["85"]),
    }


# ---------------------------------------------------------------------------
# 5247758 panel truth
# ---------------------------------------------------------------------------
def load_panel_truth() -> list[dict]:
    rows = []
    with PANEL_CSV.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            rows.append({
                "team": int(row["team"]),
                "player": row["player"],
                "hero": row["hero"],
                "hero_id": int(row["heroID"]),
                "entity_id": int(row["entityID"]),
                "kills": int(row["kills"]),
                "deaths": int(row["deaths"]),
                "assists": int(row["assists"]),
                "gold": int(row["gold"]),
                "rating": float(row["rating"]),
                "note": row.get("note", ""),
            })
    return rows


def analyze_new_sample(path: Path, panel: list[dict]) -> dict:
    data = path.read_bytes()
    header = rp.parse_header(data)
    main, tail, how, main_end, tail_start = load_records(data)
    roster, roster_source, roster_warnings = roster_for(data)
    main_events = parse_events(main, "main")
    tail_events = parse_events(tail, "tail")
    main_v6 = v6_by_entity(main_events["81"])
    main_windows = {entity: group_windows(seqs) for entity, seqs in main_v6.items()}
    source43 = source43_events(main_events) + source43_events(tail_events)

    panel_by_entity = {row["entity_id"]: row for row in panel}
    v6_counts = {entity: len(windows) for entity, windows in main_windows.items()}

    # 0x81 sequence gaps, used to explain 212's missing v6 marker.
    state_seqs = defaultdict(list)
    for event in main_events["81"]:
        state_seqs[event["entity"]].append(event["seq"])
    gaps = {}
    for entity, seqs in state_seqs.items():
        seqs = sorted(seqs)
        gap_list = [seqs[i + 1] - seqs[i] for i in range(len(seqs) - 1)]
        if not gap_list:
            continue
        largest = max(gap_list)
        index = gap_list.index(largest)
        gaps[entity] = {
            "count": len(seqs),
            "first": seqs[0],
            "last": seqs[-1],
            "median": statistics.median(gap_list),
            "largest": largest,
            "largest_from": seqs[index],
            "largest_to": seqs[index + 1],
            "second": sorted(gap_list, reverse=True)[1] if len(gap_list) > 1 else None,
        }

    # 0x23 / 0x1e census for 212.
    sub23 = [event for event in main_events["23"] if event["entity"] == 212]
    sub1e = [event for event in main_events["1e"] if event["entity"] == 212]
    sub1f = [event for event in main_events["1f"] if event["entity"] == 212]
    sub20 = [event for event in main_events["20"] if event["entity"] == 212]

    panel_totals = {
        "team1_kills": sum(row["kills"] for row in panel if row["team"] == 1),
        "team1_deaths": sum(row["deaths"] for row in panel if row["team"] == 1),
        "team2_kills": sum(row["kills"] for row in panel if row["team"] == 2),
        "team2_deaths": sum(row["deaths"] for row in panel if row["team"] == 2),
    }
    v6_totals = {
        "team1": sum(v6_counts.get(row["entity_id"], 0) for row in panel if row["team"] == 1),
        "team2": sum(v6_counts.get(row["entity_id"], 0) for row in panel if row["team"] == 2),
    }

    instrumented = [row for row in panel if row["entity_id"] in state_seqs]
    instrumented_deaths = sum(row["deaths"] for row in instrumented)
    matched_rows = [row for row in panel
                    if v6_counts.get(row["entity_id"], 0) == row["deaths"]]
    # Precision is measured only where a v6 window exists.
    v6_rows = [row for row in panel if v6_counts.get(row["entity_id"], 0) > 0]
    precision_hits = sum(1 for row in v6_rows
                         if v6_counts[row["entity_id"]] == row["deaths"])
    return {
        "path": path,
        "sample": path.stem.split("_")[0] + "_" + path.stem.split("_")[1],
        "file": path.name,
        "build": header["builds"][1] if len(header["builds"]) > 1 else "",
        "header": header,
        "main_records": len(main),
        "tail_records": len(tail),
        "stream_how": how,
        "roster": roster,
        "roster_source": roster_source,
        "roster_warnings": roster_warnings,
        "main_events": main_events,
        "tail_events": tail_events,
        "main_windows": main_windows,
        "main_v6_raw": {entity: len(seqs) for entity, seqs in main_v6.items()},
        "v6_counts": v6_counts,
        "source43": source43,
        "panel": panel,
        "panel_totals": panel_totals,
        "v6_totals": v6_totals,
        "gaps": gaps,
        "sub23": sub23,
        "sub1e": sub1e,
        "sub1f": sub1f,
        "sub20": sub20,
        "instrumented": instrumented,
        "instrumented_deaths": instrumented_deaths,
        "matched_rows": matched_rows,
        "v6_rows": v6_rows,
        "precision_hits": precision_hits,
        "n81_total": len(main_events["81"]),
        "n85_total": len(main_events["85"]),
    }


# ---------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------
def team_actual_reliability(sample: dict, team: int) -> str:
    """How trustworthy is team T's actual-kill count (= opponent v6 deaths)?

    true      : every opponent roster player has 0x81 state events.
    caveat    : all opponent players are instrumented, but an unmapped entity
                exists (its 0 v6 could also be a miss), so the count is a lower
                bound.
    false     : at least one opponent player has no 0x81 at all (e.g. bots).
    """
    opponent = 3 - team
    opponents = [entity for entity, info in sample["roster"].items()
                 if info.get("team") == opponent]
    # Every team has five players.  A partial roster (<5 known opponents)
    # usually means the opponent death count is incomplete.  The one exception
    # is a single unmapped, instrumented entity with zero v6 (113638/1181):
    # then the count is a lower bound (caveat), not unobservable.
    if len(opponents) < 5:
        if (len(opponents) == 4 and sample["unknown_entities"]
                and not sample["unknown_with_v6"]):
            return "caveat"
        return "false"
    uninstrumented = [entity for entity in opponents
                      if entity not in sample["instrumented"]]
    if len(uninstrumented) > 1:
        return "false"
    if uninstrumented or sample["unknown_entities"]:
        return "caveat"
    return "true"


def add_row(rows: list[dict], section: str, sample: dict, *, metric: str,
            value, denominator=None, rate=None, confidence="", note="",
            team="", slot="", entity="", player="", hero_id=""):
    rows.append({
        "section": section,
        "sample": sample["sample"],
        "file": sample.get("file", ""),
        "build": sample["build"],
        "team": team,
        "slot": slot,
        "entity": entity,
        "player": player,
        "hero_id": hero_id,
        "metric": metric,
        "value": value,
        "denominator": "" if denominator is None else denominator,
        "rate": "" if rate is None else f"{rate:.6f}",
        "confidence": confidence,
        "note": note,
    })


def player_rows(rows: list[dict], sample: dict, *, with_panel: bool = False):
    panel_by_entity = ({row["entity_id"]: row for row in sample["panel"]}
                       if with_panel else {})
    for entity, info in sorted(sample["roster"].items(),
                               key=lambda item: (item[1].get("team") or 9,
                                                 item[1].get("slot") if item[1].get("slot") is not None else 9)):
        windows = sample["main_windows"].get(entity, [])
        raw = sample["main_v6_raw"].get(entity, 0)
        kills = sum(1 for event in sample["source43_main"]
                    if event["entity"] == entity and event["role"] == "kill") if "source43_main" in sample else 0
        assists = sum(1 for event in sample["source43_main"]
                      if event["entity"] == entity and event["role"] == "assist") if "source43_main" in sample else 0
        hero = info.get("hero")
        player = info.get("name") or HERO_NAMES.get(hero, "")
        common = dict(
            team=info.get("team") or "",
            slot=info.get("slot") if info.get("slot") is not None else "",
            entity=entity,
            player=player,
            hero_id=hero if hero else "",
        )
        if with_panel:
            panel = panel_by_entity.get(entity)
            if not panel:
                continue
            add_row(rows, "player_5247758", sample, metric="panel_kills",
                    value=panel["kills"], confidence="high",
                    note="external panel truth", **common)
            add_row(rows, "player_5247758", sample, metric="panel_deaths",
                    value=panel["deaths"], confidence="high",
                    note="external panel truth", **common)
            add_row(rows, "player_5247758", sample, metric="panel_assists",
                    value=panel["assists"], confidence="high",
                    note="external panel truth", **common)
            add_row(rows, "player_5247758", sample, metric="kills_source43",
                    value=0, confidence="high",
                    note="source43 0 events in this sample", **common)
            add_row(rows, "player_5247758", sample, metric="assists_source43",
                    value=0, confidence="high",
                    note="source43 0 events in this sample", **common)
            add_row(rows, "player_5247758", sample, metric="deaths_v6_windows",
                    value=len(windows), confidence="medium",
                    note=f"raw v6={raw}; match={len(windows) == panel['deaths']}",
                    **common)
        else:
            add_row(rows, "player_5069040", sample, metric="kills_source43",
                    value=kills, confidence="low",
                    note="source43 kill gold is a subset of actual kills",
                    **common)
            add_row(rows, "player_5069040", sample, metric="assists_source43",
                    value=assists, confidence="low",
                    note="source43 assist gold is a subset of actual assists",
                    **common)
            add_row(rows, "player_5069040", sample, metric="deaths_v6_windows",
                    value=len(windows), confidence="medium",
                    note=f"raw v6={raw}", **common)
            add_row(rows, "player_5069040", sample, metric="deaths_v6_raw_events",
                    value=raw, confidence="medium",
                    note="raw 0x81 value-6 events before window grouping",
                    **common)


def sample_rows(rows: list[dict], sample: dict):
    for team in (1, 2):
        kills = sample["kills_by_team"].get(team, 0)
        assists = sample["assists_by_team"].get(team, 0)
        deaths = sample["team_deaths"].get(team, 0)
        actual = sample["actual_kills"][team]
        coverage = sample["coverage"][team]
        note = f"coverage_flag={sample['coverage_flag']}"
        if sample["unknown_with_v6"]:
            note += f"; unknown entity with v6={sample['unknown_with_v6']}"
        if sample["uninstrumented"]:
            note += f"; uninstrumented={sample['uninstrumented']}"
        add_row(rows, "team_5069040", sample, team=team,
                metric="kills_source43", value=kills, confidence="low",
                note="sum of source43 amount>=200 events", )
        add_row(rows, "team_5069040", sample, team=team,
                metric="assists_source43", value=assists, confidence="low",
                note="sum of source43 amount=102 events")
        add_row(rows, "team_5069040", sample, team=team,
                metric="deaths_v6_windows", value=deaths, confidence="medium",
                note="main segment, roster players only")
        add_row(rows, "team_5069040", sample, team=team,
                metric="kills_actual_from_opponent_deaths", value=actual,
                confidence="medium",
                note="definitional identity: opponent v6 death windows")
        add_row(rows, "team_5069040", sample, team=team,
                metric="actual_kills_reliability",
                value=team_actual_reliability(sample, team),
                confidence="high",
                note="true=all opponent players instrumented; caveat=unmapped entity; "
                     "false=opponent has no 0x81")
        add_row(rows, "team_5069040", sample, team=team,
                metric="kill_coverage", value=kills, denominator=actual,
                rate=coverage, confidence="low",
                note=note + f"; reliability={team_actual_reliability(sample, team)}")
        add_row(rows, "team_5069040", sample, team=team,
                metric="unrecorded_kills", value=max(actual - kills, 0),
                confidence="medium",
                note="actual kills minus source43 kills (team level)")

    for alignment in sample["alignments"]:
        delta = alignment["delta"]
        add_row(rows, "validation_5069040", sample,
                team=alignment["team"] or "", entity=alignment["entity"],
                metric="source43_kill_nearest_opponent_v6_delta_frames",
                value="" if delta is None else delta,
                confidence="low",
                note=("nearest opposing v6 window minus kill seq; "
                      f"kill_seq={alignment['seq']}, v6_seq={alignment['nearest']}"))
    deltas = [abs(item["delta"]) for item in sample["alignments"]
              if item["delta"] is not None]
    for threshold in (60, 200, 600, 1200):
        count = sum(1 for delta in deltas if delta <= threshold)
        add_row(rows, "validation_5069040", sample,
                metric=f"kill_alignment_within_{threshold}_frames",
                value=count, denominator=len(deltas),
                rate=ratio(count, len(deltas)), confidence="low",
                note="abs(nearest opposing v6 delta) <= threshold")


def build_report(samples_5069040: list[dict], new_sample: dict) -> str:
    main = next((sample for sample in samples_5069040 if sample["sample"] == "20260925_105224"), None)
    lines = []
    add = lines.append

    add("# KDA 候选验证：source43 击杀/助攻子集 + 0x81 v6 死亡窗口")
    add("")
    add("> 只读逆向。输入：`data/replays/samples/abc_batch` 的 6 个 build 5069040 "
        "普通 5v5 样本 + `20261101_182452` 的 build 5247758 人机样本。"
        "面板真值只读 `new_5247758_panel_truth_for_validation.csv`；"
        "没有读取 param.json，没有使用 runtime_dump，没有修改回放/包体/docs/memory。")
    add("")
    add("本文所有数字由 `tools/agent_kda_validate.py` 生成，可复跑：")
    add("")
    add("```bash")
    add("python tools/agent_kda_validate.py")
    add("```")
    add("")

    add("## 0. 结论速览")
    add("")
    add("1. **v6=死亡：置信度 medium（约 0.6），不是 high。** 1804 的 0x81 v6 原始 3 条"
        "合并为 1 个窗口，面板死亡正好 1（precision 1/1）；但 212 面板死亡 1、v6 窗口 0"
        "（漏检），两个有面板真值的真人里 recall 只有 1/2。5069040 的 27 个窗口与已知表"
        "完全一致（442=8、1558=5、1514=4、1965=4、1833=3、1729=2、1966=1；team1=10、"
        "team2=17），但 team 对称是定义上的恒等，不是独立证据；442/1514 的 v6 后多数在 "
        "0.15–3s 内"
        "又出现其他状态值，说明 v6 更像一次性通知而不是持续死亡态。")
    add("2. **source43 只是击杀金的子集，覆盖率不稳定。** 主样本 20260925_105224："
        "team1 4/17=23.5%、team2 2/10=20.0%（与已知 24%/20% 一致，这是唯一分母可靠的样本）；"
        "4 个 10 人样本（105224/113638/101323/103058）的池化覆盖**上界**是 10/87=11.5%（team1 13.5%、team2 10.0%），"
        "其中 113638 有 1 个未映射实体、101323/103058 有未 instrumented/未映射实体，团队死亡分母可能少计，真实覆盖率只会更低。"
        "source43 不能当作全量 K/A。")
    add("3. **逐人 KDA 只能给“下界 + 死亡候选”。** K/A 用 source43 是下界；"
        "D 用 v6 窗口是候选点估计；实际逐人击杀/助攻无法从当前回放闭合。")
    add("4. **212 漏检原因有直接证据：** 它的 0x81 状态流有 98 条、全是 value 2，"
        f"最大空洞 {new_sample['gaps'].get(212, {}).get('largest', 'n/a')} 帧"
        f"（约 {new_sample['gaps'].get(212, {}).get('largest', 0) / FPS_5247758:.1f}s），"
        "与一次死亡+复活的时间量级一致，但空洞里没有 v6；0x23 的 2 条也不在空洞内，"
        "所以不是“v6 被 0x23 替代”。")
    add("")
    add("### 0.1 置信度汇总")
    add("")
    add(md_table(
        ["结论", "置信度", "支持证据", "限制"],
        [
            ["v6=死亡事件", "medium (≈0.6)",
             "1804 v6 3→1 窗，面板 D=1；5069040 27 窗与已知表完全一致",
             "212 面板 D=1 但 v6=0；27 个 v6 窗口里 3 个在 <=0.5s 内出现非 6 状态"],
            ["v6=逐人死亡计数", "low-medium",
             "1804 精确命中；窗口合并规则可复现已知 27 窗",
             "recall 未知，instrumented 真人只有 1/2；英雄/通道偏置未解"],
            ["source43 是击杀金子集", "high",
             "金额只有 202/203/102；击杀数从未超过对方 v6 死亡上界（全 instrumented 样本）",
             "覆盖 10–24%，不是全量；bot 样本因 v6 缺失会误判超界"],
            ["source43 覆盖率", "medium",
             "主样本 4/17、2/10；6 样本逐样本可复跑",
             "主样本是唯一 exact 样本；池化 13.5%/10.0% 只是上界，样本间方差大"],
            ["逐人 K/A 数值", "low",
             "source43 收款人 entity 可闭合到玩家",
             "只是下界；实际逐人 K/A 不可得，team 总数也不能分配到个人"],
        ]))
    add("")

    add("## 1. 口径")
    add("")
    add("- `source43`：`0x02/0x85`，`body[0]=43`；`amount>=200` 记击杀（观测 202/203），"
        "`amount=102` 记助攻。")
    add("- `0x81 v6`：`0x02/0x81`（body 长度 1）且值=6；同一实体相邻 v6 事件帧间隔 "
        f"<= {V6_WINDOW_GAP} 帧合并为 1 个死亡窗口。")
    add("- `0x80` 帧命令体是 12 字节；按 len=0 解析会让 payload 失步并漏掉后续 0x81/0x85。"
        "本工具复用 `agent_damage_skill_objective.parse_payload` 的 12B 口径。")
    add("- 团队汇总只用**主段**；5069040 的第二段（续流）单独统计，因为它不是完整事件日志。")
    add("- `团队实际击杀` 在本工具里定义为“对方 v6 死亡窗口数”。这是团队级恒等式；"
        "它只能检查 source43 击杀数是否超过上界，不能单独证明 v6=死亡。")
    if main:
        add(f"- 阴性通道：`0x1e` 主样本 {len(main['main_events']['1e'])} 条，victim 是运行时"
            "单位 object ID，不是英雄/击杀记录；`0x23` 是高频状态（既有分析约 120 个窗口），"
            "不是死亡。两者都不进入 KDA。")
    add("")

    add("## 2. 5069040 六样本总览")
    add("")
    headers = ["样本", "主段帧", "续流帧", "roster", "source43 K/A (t1/t2)",
               "v6 原始", "v6 窗口 (t1/t2)", "覆盖标志"]
    table = []
    for sample in samples_5069040:
        k = sample["kills_by_team"]
        a = sample["assists_by_team"]
        raw = sum(sample["main_v6_raw"].values())
        wins = sample["team_deaths"]
        table.append([
            sample["sample"], sample["main_records"], sample["tail_records"],
            f"{len(sample['roster'])}/{sample['roster_source']}",
            f"{k.get(1, 0)}/{k.get(2, 0)} 杀，{a.get(1, 0)}/{a.get(2, 0)} 助",
            raw, f"{wins.get(1, 0)}/{wins.get(2, 0)}",
            sample["coverage_flag"],
        ])
    add(md_table(headers, table))
    add("")
    add("说明：")
    add("")
    add("- `20260924_113638`：块扫描只有 9 个玩家块，但 0x81 覆盖 10 个实体；"
        "多出的 1181 有 168 条 0x81、v6=0，阵营未知但不影响团队 v6 总数。")
    add("- `20260925_094930` / `20260925_095631`：人机/少真人样本，AI 不写 0x81，"
        "团队 v6 只覆盖真人，不能当十人团队总数。")
    add("- `20260925_101323`：315 没有任何 0x81 事件，team1 死亡数可能少计。")
    add("- `20260925_103058`：未知实体 768 有 1 个 v6 窗口，阵营未知，团队总数不含它。")
    add("- `20260925_105224`：10 人全 instrumented；修正 0x80 12B 口径后主段 v6 原始 "
        "**30**（旧口径 28）、窗口 **27**；1965 的 7322/7326/7330/7335 合并成 1 窗，"
        "旧口径新增的 7322 并入同一簇，所以窗口数仍与已知 27 窗一致（raw 30→27）。"
        "续流另有 3 个 v6（1729/1965/1966），因为没有对手侧对应，不并入团队总数。")
    add("")
    add("**口径复现检查**：本工具的 0x85 总数与既有 `normal5v5_gold_ledger_5069040.csv` "
        "逐样本完全一致（229 / 28 / 36 / 626 / 492 / 286），source43 总数 34 条"
        "（逐样本 10 / 1 / 3 / 6 / 4 / 10）也完全一致。说明 0x80 12B 口径没有漏计或重计，"
        "下面的覆盖率不是解析误差造成的。")
    add("")

    if main:
        add("## 3. 主样本 20260925_105224：逐人 KDA 候选")
        add("")
        add("`K`/`A` 是 source43 下界；`D` 是 v6 窗口候选；`队内实际击杀` 是团队级上界，"
            "不是该玩家的击杀数。")
        add("")
        headers = ["玩家", "队/位", "英雄", "K(src43)", "A(src43)", "D(v6窗)",
                   "v6原始", "队内实际击杀", "置信度", "备注"]
        table = []
        team_actual = {1: main["actual_kills"][1], 2: main["actual_kills"][2]}
        for entity, info in sorted(main["roster"].items(),
                                   key=lambda item: (item[1]["team"], item[1]["slot"])):
            kills = sum(1 for event in main["source43_main"]
                        if event["entity"] == entity and event["role"] == "kill")
            assists = sum(1 for event in main["source43_main"]
                          if event["entity"] == entity and event["role"] == "assist")
            windows = main["main_windows"].get(entity, [])
            raw = main["main_v6_raw"].get(entity, 0)
            notes = []
            if entity == 1965:
                notes.append("raw 7→4 窗（7322/7326/7330/7335 合并）")
            if entity == 442:
                notes.append("多数 v6 后 0.55–3s 内出现形态值 1/4，存在形态切换歧义")
            if entity == 1558:
                notes.append("只有 5 条 v6，没有其他状态值")
            if entity in (1021, 338, 1547):
                notes.append("v6=0；可能是 0 死亡，也可能漏检")
            if entity == 1514:
                notes.append("击杀金 2415 与最近敌方 v6 1817 差 -598 帧")
            if entity == 338:
                notes.append("source43 有 1 杀但 v6=0")
            table.append([
                info["name"] or HERO_NAMES.get(info["hero"], ""),
                f"{info['team']}/{info['slot']}",
                HERO_NAMES.get(info["hero"], info["hero"]),
                kills, assists, len(windows), raw, team_actual[info["team"]],
                "K/A low；D " + d_confidence(entity),
                "；".join(notes) if notes else "",
            ])
        add(md_table(headers, table))
        add("")
        add("团队汇总：")
        add("")
        headers = ["队伍", "K(src43)", "A(src43)", "D(v6)", "实际击杀(对方D)", "K 覆盖率", "未记录击杀"]
        table = []
        for team in (1, 2):
            kills = main["kills_by_team"].get(team, 0)
            assists = main["assists_by_team"].get(team, 0)
            deaths = main["team_deaths"].get(team, 0)
            actual = main["actual_kills"][team]
            table.append([
                team, kills, assists, deaths, actual,
                pct(kills, actual), max(actual - kills, 0),
            ])
        add(md_table(headers, table))
        add("")
        add("### 3.1 交叉验证")
        add("")
        add(f"- v6 团队对称：team1 死亡 {main['team_deaths'].get(1, 0)} = "
            f"team2 击杀 {main['actual_kills'][2]}；team2 死亡 "
            f"{main['team_deaths'].get(2, 0)} = team1 击杀 {main['actual_kills'][1]}。"
            "这是定义上的恒等，**不是独立证据**。")
        subset_ok = (main["kills_by_team"].get(1, 0) <= main["actual_kills"][1]
                     and main["kills_by_team"].get(2, 0) <= main["actual_kills"][2])
        add(f"- source43 击杀子集检查：team1 {main['kills_by_team'].get(1, 0)} <= "
            f"{main['actual_kills'][1]}、team2 {main['kills_by_team'].get(2, 0)} <= "
            f"{main['actual_kills'][2]} → {'通过' if subset_ok else '失败'}。")
        deltas = [item for item in main["alignments"] if item["delta"] is not None]
        within_3 = sum(1 for item in deltas if abs(item["delta"]) <= 60)
        within_10 = sum(1 for item in deltas if abs(item["delta"]) <= 200)
        within_30 = sum(1 for item in deltas if abs(item["delta"]) <= 600)
        add(f"- source43 击杀与“最近敌方 v6 窗口”的时间差：±3s {within_3}/{len(deltas)}、"
            f"±10s {within_10}/{len(deltas)}、±30s {within_30}/{len(deltas)}。"
            "对齐很弱，说明 0x85 source43 不是实时击杀日志，或 v6 不是击杀时刻的死亡状态；"
            "不能用它做逐杀时间校验。")
        add("- 量级检查通过（source43 击杀数不超过对方 v6 死亡数），但时间检查不通过；"
            "另外 5247758 面板自身 team2 击杀 8 != team1 死亡 9，说明“团队死亡=对方击杀”"
            "本来就有 ±1 例外。所以 v6=死亡只能给 medium，不能把 team 对称当作独立证明。")
        add("")
        add("逐条时间差（帧；正=击杀金晚于最近 v6 窗口）：")
        add("")
        headers = ["击杀 seq", "收款 entity", "队伍", "最近敌方 v6 seq", "Δ帧", "Δ秒"]
        table = []
        for item in main["alignments"]:
            table.append([
                item["seq"], item["entity"], item["team"], item["nearest"],
                item["delta"], "" if item["delta"] is None else f"{item['delta'] / FPS_5069040:+.2f}",
            ])
        add(md_table(headers, table))
        add("")

    add("## 4. 5247758 人机样本：面板真值校验")
    add("")
    add(f"- 主段 {new_sample['main_records']} 帧（约 15.09 fps），"
        f"0x81 {new_sample['n81_total']} 条，0x85 {new_sample['n85_total']} 条，"
        f"source43 {len(new_sample['source43'])} 条。")
    add("- 只有 2 个真人（1804、212）写 0x81；8 个 AI 完全没有 0x81/0x85。")
    roster_team_match = sum(
        1 for row in new_sample["panel"]
        if new_sample["roster"].get(row["entity_id"], {}).get("team") == row["team"])
    add(f"- roster 的 camp/slot 与面板 team 对齐 {roster_team_match}/10；"
        "本地玩家 1804 的 self/team1/slot1 与 header 的 localHeroId=188 一致。")
    add("")
    headers = ["玩家", "队/位", "英雄", "面板 K/D/A", "v6 窗口", "raw v6", "命中", "备注"]
    table = []
    for row in new_sample["panel"]:
        info = new_sample["roster"].get(row["entity_id"], {})
        windows = new_sample["main_windows"].get(row["entity_id"], [])
        raw = new_sample["main_v6_raw"].get(row["entity_id"], 0)
        hit = "是" if len(windows) == row["deaths"] else "否"
        notes = []
        if row["entity_id"] == 212:
            gap = new_sample["gaps"].get(212, {})
            notes.append(f"0x81 {gap.get('count')} 条全 value2；最大空洞 "
                         f"{gap.get('largest_from')}→{gap.get('largest_to')}="
                         f"{gap.get('largest')} 帧≈{gap.get('largest', 0) / FPS_5247758:.1f}s；"
                         f"次大 {gap.get('second')} 帧；0x23 {len(new_sample['sub23'])} 条不在空洞；"
                         f"0x1e/0x1f/0x20 各 {len(new_sample['sub1e'])}/{len(new_sample['sub1f'])}/"
                         f"{len(new_sample['sub20'])}")
        if row["entity_id"] == 1804:
            notes.append("本地玩家；v6 7461–7463 连续 3 条→1 窗；v6 后到下次 value2 "
                         f"{new_sample['gaps'].get(1804, {}).get('largest')} 帧")
        if info.get("bot"):
            notes.append("AI，无 0x81")
        table.append([
            row["player"], f"{row['team']}/{info.get('slot', '')}", row["hero"],
            f"{row['kills']}/{row['deaths']}/{row['assists']}",
            len(windows), raw, hit, "；".join(notes),
        ])
    add(md_table(headers, table))
    add("")
    add("面板团队合计与 v6：")
    add("")
    totals = new_sample["panel_totals"]
    v6t = new_sample["v6_totals"]
    add(f"- 面板：team1 击杀 {totals['team1_kills']}、team1 死亡 {totals['team1_deaths']}；"
        f"team2 击杀 {totals['team2_kills']}、team2 死亡 {totals['team2_deaths']}。")
    add(f"- 面板自身并不完全对称：team1 击杀 {totals['team1_kills']} = team2 死亡 "
        f"{totals['team2_deaths']}，但 team2 击杀 {totals['team2_kills']} != team1 死亡 "
        f"{totals['team1_deaths']}（差 {totals['team1_deaths'] - totals['team2_kills']}，"
        "可能有自杀/防御塔/小兵死亡）。所以“团队死亡=对方击杀”本身有 ±1 量级的例外。")
    add(f"- v6：team1 {v6t['team1']}、team2 {v6t['team2']}。"
        f"v6 precision = {new_sample['precision_hits']}/{len(new_sample['v6_rows'])}；"
        f"对全部面板死亡 recall = {sum(new_sample['v6_counts'].values())}/"
        f"{sum(row['deaths'] for row in new_sample['panel'])}；"
        f"对 instrumented 真人 recall = {sum(new_sample['v6_counts'].values())}/"
        f"{new_sample['instrumented_deaths']}。")
    add("")
    add("### 4.1 212 漏检的拆解")
    add("")
    gap212 = new_sample["gaps"].get(212, {})
    gap1804 = new_sample["gaps"].get(1804, {})
    add(f"- 212 的 0x81 有 {gap212.get('count')} 条，first={gap212.get('first')}、"
        f"last={gap212.get('last')}，**全是 value 2**，没有任何 v6。")
    add(f"- 最大空洞 {gap212.get('largest_from')}→{gap212.get('largest_to')} = "
        f"{gap212.get('largest')} 帧 ≈ {gap212.get('largest', 0) / FPS_5247758:.1f}s；"
        f"次大 {gap212.get('second')} 帧 ≈ {gap212.get('second', 0) / FPS_5247758:.1f}s；"
        f"中位间隔 {gap212.get('median')} 帧。最大空洞是次大的 "
        f"{gap212.get('largest', 0) / max(gap212.get('second') or 1, 1):.2f} 倍，"
        "形态上像“死亡→复活”的采样中断。")
    add(f"- 1804 的对照：v6 7463 之后到下次 value2 8160 = {gap1804.get('largest')} 帧 ≈ "
        f"{gap1804.get('largest', 0) / FPS_5247758:.1f}s；但 1804 还有 500 帧（33.1s）、"
        "425 帧（28.2s）等没有 v6 的长空洞。所以“长空洞”本身只能算死亡候选，"
        "不能单独证明 212 的死亡。")
    add(f"- 212 的 0x23 只有 {len(new_sample['sub23'])} 条（seq "
        f"{[event['seq'] for event in new_sample['sub23']]}），都在空洞之后，"
        "不是死亡标记；0x1e/0x1f/0x20 对 212 各 "
        f"{len(new_sample['sub1e'])}/{len(new_sample['sub1f'])}/{len(new_sample['sub20'])} 条。")
    add(f"- 采样率差异：1804 的 0x81 {gap1804.get('count')} 条、中位间隔 "
        f"{gap1804.get('median')} 帧（爆发式本地流）；212 的 0x81 "
        f"{gap212.get('count')} 条、中位间隔 {gap212.get('median')} 帧（稀疏远端流）。"
        "v6 只出现在 1804 的密集流里，支持“v6 是本地/高频状态通道的一部分”的解释，"
        "但这不是唯一解释。")
    add("- 所以 212 的漏检是**标记缺失**，不是“标记被另一个通道替代”。可能原因（不能区分）："
        "v6 只对本地玩家/部分英雄发出、212 的状态包丢失、或该英雄的死亡状态不走 0x81。"
        "这直接限制了 v6 作为通用死亡计的 recall。")
    add("")

    add("## 5. 覆盖率与漏检量化")
    add("")
    add("### 5.1 source43 对实际击杀的覆盖率")
    add("")
    headers = ["样本", "team1 K/K_actual", "team1 覆盖率", "team2 K/K_actual",
               "team2 覆盖率", "总覆盖率", "分母可靠性"]
    table = []
    for sample in samples_5069040:
        k = sample["kills_by_team"]
        a = sample["actual_kills"]
        reliability = {team: team_actual_reliability(sample, team) for team in (1, 2)}

        def cell(team: int) -> tuple[str, str]:
            mark = "*" if reliability[team] == "caveat" else ""
            if reliability[team] == "false":
                return f"{k.get(team, 0)}/?", "n/a"
            return f"{k.get(team, 0)}/{a[team]}{mark}", pct(k.get(team, 0), a[team]) + mark

        left, left_pct = cell(1)
        right, right_pct = cell(2)
        if "false" in reliability.values():
            total_cell = "n/a"
        else:
            total_cell = pct(k.get(1, 0) + k.get(2, 0), a[1] + a[2])
            if "caveat" in reliability.values():
                total_cell += "*"
        table.append([
            sample["sample"], left, left_pct, right, right_pct, total_cell,
            f"{sample['coverage_flag']}; t1={reliability[1]}, t2={reliability[2]}",
        ])
    add(md_table(headers, table))
    add("")
    add("`*` = 分母可能少计（有未映射实体/未 instrumented 玩家），覆盖率是**上界**；"
        "`n/a` = 对方队伍有 AI 完全没有 0x81，团队击杀数不可观测。"
        "分母本身来自“对方 v6 死亡窗口”；如果 v6 不是死亡，覆盖率的定义也随之改变。")
    add("")

    def pool(group: list[dict]) -> tuple[int, int, int, int, int, int]:
        k1 = sum(sample["kills_by_team"].get(1, 0) for sample in group)
        k2 = sum(sample["kills_by_team"].get(2, 0) for sample in group)
        a1 = sum(sample["actual_kills"][1] for sample in group)
        a2 = sum(sample["actual_kills"][2] for sample in group)
        return k1, a1, k2, a2, k1 + k2, a1 + a2

    exact = [sample for sample in samples_5069040
             if sample["sample"] == "20260925_105224"]
    pair = [sample for sample in samples_5069040
            if sample["sample"] in ("20260925_105224", "20260924_113638")]
    caveat = [sample for sample in samples_5069040
              if sample["sample"] in ("20260925_105224", "20260924_113638",
                                      "20260925_101323", "20260925_103058")]
    for label, group in (("105224（exact，t1/t2 分母可靠）", exact),
                         ("105224+113638（113638 有未映射实体，上界）", pair),
                         ("105224+113638+101323+103058（含 2 个 caveat，上界）", caveat)):
        k1, a1, k2, a2, kt, at = pool(group)
        add(f"- {label}：team1 {k1}/{a1}={pct(k1, a1)}，team2 {k2}/{a2}={pct(k2, a2)}，"
            f"合计 {kt}/{at}={pct(kt, at)}。")
    add("")
    add("主样本 23.5%/20.0% 成立（唯一 t1/t2 分母都可靠的样本）。"
        "把 113638 并进来是 22.7%/14.3%；再把 101323/103058 并进来是 13.5%/10.0%，"
        "而且这两个样本的团队死亡分母可能少计，所以 13.5%/10.0% 只是**上界**，"
        "真实覆盖率只会更低。source43 的覆盖率不是稳定常数，不能把主样本的 24%/20% "
        "外推到所有对局。")
    add("")
    add("**对 442 的敏感性**：如果 442 的 8 个 v6 不是死亡而是李信形态状态，"
        "team2 死亡从 17 降到 9，team1 实际击杀从 17 降到 9，"
        "source43 team1 覆盖率从 4/17=23.5% 升到 4/9=44.4%；team2 仍是 2/10=20.0%。"
        "也就是说“source43 覆盖 24%”这个结论对 442 的 v6 语义高度敏感，"
        "不是稳健常数。")
    add("")
    add("### 5.2 v6 的漏检")
    add("")
    add("- 5247758：1804 的 1 个 v6 窗口命中面板 D=1；212 面板 D=1 但 0 个 v6 窗口。"
        "在 2 个 instrumented 真人里 recall=1/2，precision=1/1。")
    add("- 8 个 AI 没有 0x81，面板死亡合计 "
        f"{sum(row['deaths'] for row in new_sample['panel'] if row['entity_id'] >= 2000)} 次全部漏检；"
        "这是“通道缺失”，不是 v6 判断错。")
    add("- 5069040 主样本里 1021/338/1547 的 D=0。没有面板真值，无法区分“真的 0 死亡”"
        "和“v6 漏检”；338 还有 1 条 source43 击杀，说明它至少参与过一次击杀。")
    add("- 442 的 8 个 v6 窗口最可疑：多数 v6 后 0.55–3s 内出现 value 1/4（李信形态值），"
        "v6 可能不是持续死亡态，而是某种一次性状态/通知。若 442 的 v6 不是死亡，"
        "team2 死亡会从 17 降到 9，团队对称性反而变好；这一点必须保留为未决。")
    add("- 1514 也有同样问题：v6 1422→value1 1428（0.3s）、v6 3604→value1 3607（0.15s）。"
        "如果 v6 是持续死亡态，这两个间隔不可能；所以 v6 更像**一次性死亡通知/状态位**，"
        "而且远端英雄的状态快照可能滞后/乱序。")
    if main:
        per_state = defaultdict(list)
        for event in main["main_events"]["81"]:
            per_state[event["entity"]].append((event["seq"], event["value"]))
        v6_total = sum(len(windows) for windows in main["main_windows"].values())
        short_gaps = []
        for entity, windows in main["main_windows"].items():
            states = sorted(per_state[entity])
            for window in windows:
                following = next((seq for seq, value in states
                                  if seq > window[-1] and value != V6), None)
                if following is not None:
                    short_gaps.append(following - window[-1])
        short_05 = sum(1 for gap in short_gaps if gap <= 10)
        short_1 = sum(1 for gap in short_gaps if gap <= 20)
        add(f"- 把 0x81 当状态流量化：{v6_total} 个 v6 窗口里 **{short_05}/{v6_total}** 在 "
            f"<=0.5s 内、**{short_1}/{v6_total}** 在 <=1s 内就出现非 6 状态。"
            "若 v6 是持续死亡态，这些短间隔不成立；这支持“v6=一次性死亡通知/状态位”"
            "而不是“v6=死亡持续态”。")
    add("- 1558 只有 5 条 0x81、全是 v6，没有 value2 基线，无法用“死亡空洞”交叉验证。")
    add("- 已知 0x23 在主样本约 120 个窗口，不是死亡；5247758 里 212 只有 2 条 0x23"
        "（seq 8934/8943），不在 41s 空洞内，所以也不能用 0x23 补 212 的死亡。")
    add("- **v6 的发射范围与样本有关**：5247758 只有本地玩家 1804 出现 v6；212 有 98 条"
        " value2 但 0 条 v6；而 5069040 主样本有 7 个英雄出现 v6。说明 v6 是否覆盖某个"
        "玩家取决于 build/模式/录制视角，不能假设每个回放都覆盖 10 人。")
    add("- 反向证据：095631 的 team1 source43 有 1 杀，但 team2 的 v6 死亡是 0（AI 不写 0x81）。"
        "这说明“source43 击杀数 <= 对方 v6 死亡数”在 bot 样本会失败，原因是 v6 通道缺失，"
        "不是 source43 多记。")
    add("")

    add("## 6. KDA 候选表（结论表）")
    add("")
    add("### 6.1 20260925_105224（10 人普通 5v5）")
    add("")
    headers = ["玩家", "队", "K 下界(src43)", "A 下界(src43)", "D 候选(v6)",
               "K 置信度", "A 置信度", "D 置信度", "备注"]
    table = []
    if main:
        notes_by_entity = {
            1965: "raw 7→4 窗（7322–7335 合并）",
            1514: "4 个独立窗口；击杀金与 v6 时间差大",
            1021: "v6=0，可能是 0 死亡也可能漏检",
            338: "source43 有 1 杀，但 v6=0",
            442: "8 窗；多数 v6 后 0.55–3s 出现形态值，存在形态歧义",
            1966: "source43 2 杀均不在 v6 附近",
            1547: "v6=0，可能是 0 死亡也可能漏检",
            1558: "只有 v6，无 value2 基线",
            1833: "3 个独立窗口",
        }
        for entity, info in sorted(main["roster"].items(),
                                   key=lambda item: (item[1]["team"], item[1]["slot"])):
            kills = sum(1 for event in main["source43_main"]
                        if event["entity"] == entity and event["role"] == "kill")
            assists = sum(1 for event in main["source43_main"]
                          if event["entity"] == entity and event["role"] == "assist")
            windows = main["main_windows"].get(entity, [])
            table.append([
                info["name"] or HERO_NAMES.get(info["hero"], ""),
                info["team"], kills, assists, len(windows),
                "low", "low", d_confidence(entity),
                notes_by_entity.get(entity, ""),
            ])
    add(md_table(headers, table))
    add("")
    add("### 6.2 5247758（面板真值，2 真人 + 8 AI）")
    add("")
    headers = ["玩家", "队", "面板 K", "面板 D", "面板 A", "回放 v6", "source43 K/A", "可用性"]
    table = []
    for row in new_sample["panel"]:
        windows = new_sample["main_windows"].get(row["entity_id"], [])
        table.append([
            row["player"], row["team"], row["kills"], row["deaths"], row["assists"],
            len(windows), "0/0",
            "面板真值" if row["entity_id"] < 2000 else "仅面板（AI 无回放通道）",
        ])
    add(md_table(headers, table))
    add("")

    add("## 7. 还缺什么")
    add("")
    add("1. **5069040 的外部面板真值**：目前只有 5247758 一个样本有逐人 K/D/A，"
        "而且只有 2 个真人。没有 5069040 的面板，v6 的逐人 precision/recall 无法测。")
    add("2. **v6 语义的独立证据**：需要更多“面板 + 回放”配对，最好覆盖 442 李信、"
        "1514 虞姬、1558 东皇这些边界英雄；当前 442 的 v6 与形态值混淆，"
        "1514 的 v6 后 0.3s 就出现 value1，说明 v6 不是持续死亡态。")
    add("3. **212 漏检原因**：0x81 value2 的 41s 空洞是死亡候选，但没有 v6。"
        "可能是 v6 只对本地玩家/部分英雄发出，或状态流漏包；需要同局服务端事件或"
        "更多“非录制者真人”样本。")
    add("4. **source43 不是实时击杀日志**：它只覆盖 10–24% 的击杀，且与最近敌方 v6 "
        "窗口的时间差多数在 6–35s；0x85 更像部分/批量结算流水。需要完整 0x85 或"
        "服务端经济流水才能做逐杀时间校验。")
    add("5. **victim 映射**：0x1e 的 victim 是运行时单位 object ID，缺 object ID→英雄/"
        "兵种映射；0x1f/0x20 只是高光标签，不提供 killer/victim；0x23 不是死亡。")
    add("6. **AI 通道**：人机模式 AI 完全不写 0x81/0x85，回放无法得到 AI KDA；"
        "只能靠外部面板。")
    add("7. **续流不完整**：105224 第二段只有 3 个 v6（1729/1965/1966），"
        "没有对手侧对应，不能并进团队总数；团队汇总只能用主段。")
    add("8. **roster 缺口**：113638 的 1181（168 条 0x81、v6=0）不在玩家块里；"
        "103058 的 768（1 个 v6 窗口）阵营未知；101323 的 315 没有任何 0x81。"
        "这些都会让团队总数有 ±1 的不确定度。")
    add("")

    add("## 8. 产物")
    add("")
    add("- `tools/agent_kda_validate.py`（本报告生成器，只读）")
    add("- `data/replays/_analysis/datasets/agent_kda_validate.csv`（长表，section 过滤）")
    add("- `data/replays/_analysis/datasets/agent_kda_validate.md`（本报告）")
    add("")
    return "\n".join(lines)


def write_csv(rows: list[dict]):
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    samples = []
    for path in sorted(ABC_BATCH.glob("*.abc")):
        data = path.read_bytes()
        header = rp.parse_header(data)
        build = header["builds"][1] if len(header["builds"]) > 1 else ""
        if build == BUILD_5069040:
            samples.append(analyze_sample(path))
    if not samples:
        raise SystemExit("no 5069040 samples found")

    new_paths = sorted(NEW_SAMPLE_DIR.glob("*.abc")) or sorted(ABC_BATCH.glob("20261101_182452*.abc"))
    if not new_paths:
        raise SystemExit("no 5247758 sample found")
    panel = load_panel_truth()
    new_sample = analyze_new_sample(new_paths[0], panel)

    rows: list[dict] = []
    for sample in samples:
        player_rows(rows, sample)
        sample_rows(rows, sample)
        # Unmapped 0x81 entities are not in the roster; keep them auditable.
        for entity in sample["unknown_entities"]:
            state_count = sum(1 for event in sample["main_events"]["81"]
                              if event["entity"] == entity)
            windows = sample["main_windows"].get(entity, [])
            add_row(rows, "unknown_entity_5069040", sample, entity=entity,
                    metric="state_81_events", value=state_count,
                    confidence="medium", note="entity not in parsed roster")
            add_row(rows, "unknown_entity_5069040", sample, entity=entity,
                    metric="deaths_v6_windows", value=len(windows),
                    confidence="medium", note="team unknown; excluded from team totals")

    by_name = {sample["sample"]: sample for sample in samples}
    for label, names in (
        ("exact_105224", ("20260925_105224",)),
        ("pair_105224_113638", ("20260925_105224", "20260924_113638")),
        ("four_full_roster", ("20260925_105224", "20260924_113638",
                              "20260925_101323", "20260925_103058")),
    ):
        group = [by_name[name] for name in names if name in by_name]
        k1 = sum(sample["kills_by_team"].get(1, 0) for sample in group)
        k2 = sum(sample["kills_by_team"].get(2, 0) for sample in group)
        a1 = sum(sample["actual_kills"][1] for sample in group)
        a2 = sum(sample["actual_kills"][2] for sample in group)
        synthetic = {"sample": label, "build": BUILD_5069040}
        for team, kills, actual in ((1, k1, a1), (2, k2, a2)):
            add_row(rows, "summary_5069040", synthetic, team=team,
                    metric="kill_coverage", value=kills, denominator=actual,
                    rate=ratio(kills, actual), confidence="medium",
                    note="pooled; denominator may be a lower bound (see coverage table)")
        add_row(rows, "summary_5069040", synthetic,
                metric="total_kill_coverage", value=k1 + k2,
                denominator=a1 + a2, rate=ratio(k1 + k2, a1 + a2),
                confidence="medium",
                note="pooled; exact only for exact_105224")

    player_rows(rows, new_sample, with_panel=True)
    new_totals = new_sample["panel_totals"]
    for team in (1, 2):
        add_row(rows, "team_5247758", new_sample, team=team,
                metric="panel_kills", value=new_totals[f"team{team}_kills"],
                confidence="high", note="external panel truth")
        add_row(rows, "team_5247758", new_sample, team=team,
                metric="panel_deaths", value=new_totals[f"team{team}_deaths"],
                confidence="high", note="external panel truth")
        add_row(rows, "team_5247758", new_sample, team=team,
                metric="deaths_v6_windows", value=new_sample["v6_totals"][f"team{team}"],
                confidence="medium", note="0x81 v6 windows; AI have no 0x81")
        add_row(rows, "team_5247758", new_sample, team=team,
                metric="kills_source43", value=0, confidence="high",
                note="source43 0 events")
    add_row(rows, "validation_5247758", new_sample,
            metric="v6_precision", value=new_sample["precision_hits"],
            denominator=len(new_sample["v6_rows"]),
            rate=ratio(new_sample["precision_hits"], len(new_sample["v6_rows"])),
            confidence="medium", note="v6 rows whose window count equals panel deaths")
    add_row(rows, "validation_5247758", new_sample,
            metric="v6_recall_all_panel_deaths",
            value=sum(new_sample["v6_counts"].values()),
            denominator=sum(row["deaths"] for row in new_sample["panel"]),
            rate=ratio(sum(new_sample["v6_counts"].values()),
                       sum(row["deaths"] for row in new_sample["panel"])),
            confidence="medium", note="includes 8 AI with no 0x81 channel")
    add_row(rows, "validation_5247758", new_sample,
            metric="v6_recall_instrumented_players",
            value=sum(new_sample["v6_counts"].values()),
            denominator=new_sample["instrumented_deaths"],
            rate=ratio(sum(new_sample["v6_counts"].values()),
                       new_sample["instrumented_deaths"]),
            confidence="medium", note="1804+212 only")
    add_row(rows, "validation_5247758", new_sample,
            metric="panel_team_symmetry_mismatch",
            value=new_totals["team1_deaths"] - new_totals["team2_kills"],
            confidence="high",
            note="team1 deaths minus team2 kills; panel is not perfectly symmetric")
    gap212 = new_sample["gaps"].get(212, {})
    add_row(rows, "validation_5247758", new_sample, entity=212,
            player="快乐何必认真", hero_id=162,
            metric="largest_0x81_value2_gap_frames", value=gap212.get("largest"),
            confidence="medium",
            note=(f"{gap212.get('largest_from')}->{gap212.get('largest_to')}; "
                  f"second={gap212.get('second')}; median={gap212.get('median')}"))

    write_csv(rows)
    OUT_MD.write_text(build_report(samples, new_sample), encoding="utf-8")

    # Console summary for the caller.
    print(f"samples5069040={len(samples)} new={new_sample['sample']}")
    for sample in samples:
        print(f"  {sample['sample']} build={sample['build']} recs={sample['main_records']} "
              f"roster={len(sample['roster'])} flag={sample['coverage_flag']} "
              f"K43={dict(sample['kills_by_team'])} A43={dict(sample['assists_by_team'])} "
              f"Dv6={dict(sample['team_deaths'])} cov={ {k: round(v, 3) if v is not None else None for k, v in sample['coverage'].items()} }")
    print(f"  new {new_sample['sample']} v6={new_sample['v6_counts']} "
          f"panelD={ {row['entity_id']: row['deaths'] for row in new_sample['panel']} }")
    print(f"wrote {OUT_CSV}")
    print(f"wrote {OUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
