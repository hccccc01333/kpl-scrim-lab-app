"""Identify what the eleven per-player counters mean, using a panel anchor.

The record at `record+0x50` holds eleven cumulative u32 counters whose
semantics are unconfirmed (docs 5.158).  This tool lines them up with a
settlement "data" panel (damage dealt / damage taken / healing) for the same
match and reports, for every counter, its rank correlation with each panel
column plus the median ratio.

Read-only and offline: one arena snapshot plus one CSV.  No device.

Panel CSV columns (header required, extra columns ignored):

    player,damage_dealt,damage_taken,healing

`player` must match the roster JSON used for the snapshot.  Rows may be in
any order; players missing from either side are reported, not guessed.

Usage:

    python tools/panel_anchor.py \
        --snapshot data/replays/_analysis/live_20261104/arena_paused_0500.bin \
        --roster data/replays/_analysis/live_20261104/roster_161129.json \
        --panel panel_0500.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import struct
from pathlib import Path

from arena_player_stats import find_records

COUNTERS = 11
PANEL_COLUMNS = ("damage_dealt", "damage_taken", "healing")


def rank(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        shared = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = shared
        i = j + 1
    return ranks


def pearson(x: list[float], y: list[float]) -> float:
    n = len(x)
    if n < 2:
        return 0.0
    mx, my = sum(x) / n, sum(y) / n
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    den = (sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y)) ** 0.5
    return num / den if den else 0.0


def spearman(x: list[float], y: list[float]) -> float:
    return pearson(rank(x), rank(y))


def read_snapshot(path: Path) -> dict[int, dict]:
    raw = path.read_bytes()
    records = find_records(raw)
    out: dict[int, dict] = {}
    for index, record in records.items():
        start = record["offset"]
        row = {"gold": record["gold"], "level": record["level"]}
        for i in range(COUNTERS):
            row[f"c{i}"] = struct.unpack_from("<I", raw, start + 0x50 + i * 4)[0]
        out[index] = row
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--roster", type=Path, required=True)
    parser.add_argument("--panel", type=Path, required=True)
    args = parser.parse_args()

    roster = json.loads(args.roster.read_text(encoding="utf-8"))
    panel_rows = list(csv.DictReader(args.panel.open(encoding="utf-8-sig")))
    panel = {row["player"]: row for row in panel_rows}
    snapshot = read_snapshot(args.snapshot)

    paired: list[tuple[str, dict, dict]] = []
    missing_panel, missing_snapshot = [], []
    for index, row in sorted(snapshot.items(), reverse=True):
        info = roster.get(str(index))
        if not info:
            continue
        player = info["player"]
        if player not in panel:
            missing_panel.append(player)
            continue
        paired.append((player, row, panel[player]))
    for player in panel:
        if not any(p[0] == player for p in paired):
            missing_snapshot.append(player)

    print(f"snapshot={args.snapshot.name} records={len(snapshot)} "
          f"paired={len(paired)}")
    if missing_panel:
        print(f"  in snapshot, no panel row: {', '.join(missing_panel)}")
    if missing_snapshot:
        print(f"  in panel, no snapshot row: {', '.join(missing_snapshot)}")
    if len(paired) < 4:
        print("  not enough pairs for a correlation; aborting")
        return 1

    header = f"{'player':10}" + "".join(f"{f'c{i}':>9}" for i in range(COUNTERS))
    header += "".join(f"{name[:9]:>11}" for name in PANEL_COLUMNS)
    print(header)
    for player, row, panel_row in paired:
        line = f"{player:10}" + "".join(f"{row[f'c{i}']:>9,}" for i in range(COUNTERS))
        for name in PANEL_COLUMNS:
            raw = panel_row.get(name, "")
            try:
                line += f"{int(float(raw)):>11,}"
            except (TypeError, ValueError):
                line += f"{'-':>11}"
        print(line)

    print("\nrank correlation (Spearman) between counter and panel column:")
    print(f"{'counter':8}" + "".join(f"{name:>16}" for name in PANEL_COLUMNS)
          + f"{'median ratio':>14}")
    best = None
    for i in range(COUNTERS):
        x = [row[f"c{i}"] for _, row, _ in paired]
        line = f"c{i:<7}"
        scores = []
        for name in PANEL_COLUMNS:
            try:
                y = [float(panel_row[name]) for _, _, panel_row in paired]
            except (KeyError, TypeError, ValueError):
                line += f"{'-':>16}"
                scores.append(None)
                continue
            rho = spearman(x, y)
            line += f"{rho:>16.3f}"
            scores.append(rho)
        if scores[0] is not None:
            ratios = []
            for _, row, panel_row in paired:
                try:
                    value = float(panel_row["damage_dealt"])
                except (KeyError, TypeError, ValueError):
                    continue
                if value:
                    ratios.append(row[f"c{i}"] / value)
            median = statistics.median(ratios) if ratios else float("nan")
            line += f"{median:>14.3f}"
            if best is None or scores[0] > best[1]:
                best = (f"c{i}", scores[0], median)
        else:
            line += f"{'-':>14}"
        print(line)

    if best:
        name, rho, median = best
        print(f"\nbest match for damage_dealt: {name} "
              f"(rho={rho:.3f}, median ratio={median:.3f})")
        if rho >= 0.9:
            print("  -> strong: treat as confirmed only after a second match")
        else:
            print("  -> weak: keep the counter unnamed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
