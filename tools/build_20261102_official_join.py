"""Join the scraped Camp replay for 20261102_161129 with the .abc/panel data.

The Camp payload is already local under data/official_replays/camp-1793606215;
this script does not fetch anything. It maps official players to panel entities
by (camp, heroId), compares KDA/team gold, and exports the 693 per-second
position samples per player for downstream analysis.
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "data/replays/_analysis/datasets"
OFFICIAL = ROOT / "data/official_replays/camp-1793606215"
PANEL = DATASETS / "20261102_panel_truth.csv"
OUT_PLAYERS = DATASETS / "20261102_official_players.csv"
OUT_POSITIONS = DATASETS / "20261102_official_positions.csv"
OUT_GOLD = DATASETS / "20261102_official_team_gold.csv"


def main() -> None:
    norm = json.loads((OFFICIAL / "normalized.json").read_text(encoding="utf-8"))
    positions = json.loads((OFFICIAL / "positions.json").read_text(encoding="utf-8"))
    panel = list(csv.DictReader(PANEL.open(encoding="utf-8-sig")))
    official = {(str(p["camp"]), str(p["heroId"])): p for p in norm["players"]}
    pos_by_pid = {p["playerId"]: p["posArr"] for p in positions["players"]}

    rows = []
    pos_rows = []
    for r in panel:
        key = (r["team"], r["hero_id"])
        o = official.get(key)
        if not o:
            rows.append({**r, "official_match": 0, "official_note": "camp+heroId not found"})
            continue
        kda_ok = (int(r["kills"]), int(r["deaths"]), int(r["assists"])) == (
            o["kills"], o["deaths"], o["assists"])
        rows.append({
            "entity": r["entity"], "player": r["player"], "hero_id": r["hero_id"],
            "hero": r["hero"], "camp": r["team"], "panel_kda": f"{r['kills']}/{r['deaths']}/{r['assists']}",
            "official_kda": f"{o['kills']}/{o['deaths']}/{o['assists']}",
            "kda_match": int(kda_ok), "panel_gold": r["gold"], "score": r["score"],
            "official_grow": o["ratings"].get("grow"), "official_battle": o["ratings"].get("battle"),
            "official_survive": o["ratings"].get("survive"), "official_hurtHero": o["ratings"].get("hurtHero"),
            "official_kda_rating": o["ratings"].get("kda"),
            "official_player_id": o["playerId"],
        })
        arr = pos_by_pid.get(o["playerId"]) or []
        for t, xy in enumerate(arr):
            if not isinstance(xy, list) or len(xy) < 2:
                continue
            pos_rows.append({
                "entity": r["entity"], "player": r["player"], "hero": r["hero"],
                "camp": r["team"], "t_sec": t, "grid_x": xy[0], "grid_y": xy[1],
            })

    with OUT_PLAYERS.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    with OUT_POSITIONS.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(pos_rows[0]))
        w.writeheader(); w.writerows(pos_rows)

    econ = norm["economy"]
    duration = norm["match"]["durationSec"]
    n = len(econ["blue"])
    gold_rows = []
    for i, (blue, red, diff) in enumerate(zip(econ["blue"], econ["red"], econ["diff"])):
        gold_rows.append({
            "t_approx_sec": min(duration, 30 * (i + 1)),
            "blue": blue, "red": red, "diff": diff,
        })
    with OUT_GOLD.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(gold_rows[0]))
        w.writeheader(); w.writerows(gold_rows)

    panel_sums = Counter()
    for r in panel:
        panel_sums[r["team"]] += int(r["gold"])
    print("official players", len(rows), "positions", len(pos_rows), "gold points", n)
    print("official team gold", norm["match"]["teamGold"], "panel sums", dict(panel_sums))
    print("KDA match", sum(int(r.get("kda_match", 0)) for r in rows), "/", len(panel))
    print("positions per player", Counter(r["entity"] for r in pos_rows))
    print("wrote", OUT_PLAYERS, OUT_POSITIONS, OUT_GOLD)


if __name__ == "__main__":
    main()
