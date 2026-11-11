#!/usr/bin/env python3
"""Convert a state_series CSV into checkpoint rows accepted by the workbench.

The workbench endpoint `POST /api/replays/{id}/checkpoints` accepts JSONL rows
with at least `time_s` and `player`.  `tools/state_series.py` outputs CSV with
`clock/second/player/hero/camp/gold/kills/deaths/assists/level/c0..c10`.

This converter keeps only fields with a verified meaning:
  time_s, time_mmss, player, hero, entity_id? (not in CSV), camp,
  gold, kills, deaths, assists, level,
  sources='arena_stats', row_kind='state', note.

It also validates per-player monotonicity and writes a manifest with input
hash, row count, checkpoint clocks and the exact snapshot sources.  No
interpolation and no UI-derived values are added.

Usage:
  python tools/state_series_to_checkpoints.py \
      data/replays/_analysis/live_20261104/state_series_161129_10pt.csv \
      --out data/replays/_analysis/live_20261104/checkpoints_161129_10pt.jsonl \
      --manifest data/replays/_analysis/live_20261104/checkpoints_161129_10pt.manifest.json
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

NUMERIC = ("gold", "kills", "deaths", "assists", "level")
CLOCK_ORDER = None


def clock_key(clock: str) -> tuple[int, int]:
    mm, ss = clock.split(":", 1)
    return int(mm), int(ss)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, default=None)
    ap.add_argument("--source-file", action="append", default=[],
                    help="optional input snapshot names/paths for the manifest")
    ap.add_argument("--fail-on-nonmonotonic", action="store_true")
    args = ap.parse_args()

    rows = list(csv.DictReader(args.csv.open(encoding="utf-8-sig")))
    if not rows:
        raise SystemExit("empty CSV")
    required = {"clock", "second", "player", "hero", "camp", *NUMERIC}
    missing = required - set(rows[0])
    if missing:
        raise SystemExit(f"missing columns: {sorted(missing)}")

    clocks = sorted({r["clock"] for r in rows}, key=clock_key)
    # state_series uses blue/red; the workbench checkpoint contract uses
    # camp 1/2.  The 161129 roster maps blue->1 and red->2.
    camp_map = {"blue": 1, "red": 2}
    out_rows = []
    for r in rows:
        raw_camp = str(r["camp"]).strip().lower()
        try:
            camp = int(raw_camp)
        except ValueError:
            if raw_camp not in camp_map:
                raise SystemExit(f"unknown camp: {r['camp']!r}")
            camp = camp_map[raw_camp]
        row = {
            "time_s": float(r["second"]),
            "time_mmss": r["clock"],
            "player": r["player"],
            "hero": r["hero"],
            "camp": camp,
            "gold": int(r["gold"]),
            "kills": int(r["kills"]),
            "deaths": int(r["deaths"]),
            "assists": int(r["assists"]),
            "level": int(r["level"]),
            "sources": "arena_stats",
            "row_kind": "state",
            "time_origin": "arena_unit_clock",
            "note": f"arena record; state_series clock={r['clock']}",
        }
        for i in range(11):
            key = f"c{i}"
            if key in r and r[key] not in (None, ""):
                row[key] = int(r[key])
        out_rows.append(row)

    # Per-player non-decreasing check.
    by_player = defaultdict(list)
    for r in out_rows:
        by_player[r["player"]].append(r)
    violations = []
    for player, rs in by_player.items():
        rs = sorted(rs, key=lambda x: clock_key(x["time_mmss"]))
        for a, b in zip(rs, rs[1:]):
            for field in NUMERIC:
                if b[field] < a[field]:
                    violations.append({
                        "player": player, "field": field,
                        "from": a["time_mmss"], "to": b["time_mmss"],
                        "old": a[field], "new": b[field],
                    })
    if violations and args.fail_on_nonmonotonic:
        raise SystemExit(f"monotonicity violations: {violations[:5]}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in out_rows) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schema": "kpl-state-checkpoints-manifest-v1",
        "sourceCsv": str(args.csv),
        "sourceSha256": sha256(args.csv),
        "output": str(args.out),
        "outputSha256": sha256(args.out),
        "rows": len(out_rows),
        "players": len(by_player),
        "checkpoints": clocks,
        "sources": args.source_file,
        "fields": ["time_s", "time_mmss", "player", "hero", "camp",
                   *NUMERIC, "c0..c10", "sources", "row_kind"],
        "monotonicViolations": violations,
        "note": ("engine arena records only; no interpolation, no UI-derived "
                 "gold/KDA/level"),
    }
    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
        )
    print(f"wrote {args.out}: {len(out_rows)} rows, {len(clocks)} checkpoints")
    print(f"monotonic violations: {len(violations)}")
    if args.manifest:
        print(f"manifest -> {args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
