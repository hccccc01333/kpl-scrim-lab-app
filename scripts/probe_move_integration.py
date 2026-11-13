"""Decide whether `.abc` move commands can be integrated into a trajectory.

The replay is a lockstep input log: positions are *computed* by the client's
deterministic simulation and never stored.  The only position evidence in the
file is a handful of sparse anchors (2 of 10 players in the 20261102_161129
sample).  This tool asks a falsifiable question:

    Can per-frame PLAYER_MOVE directions, integrated with a fitted constant
    speed, reproduce the displacement between consecutive anchors?

Method: for every anchor interval, sum the unit direction vectors of the move
commands in that interval, then fit one angle offset and one speed over all
intervals (grid search on the offset, closed form for the speed).  The score is
``residual / total displacement``:

    ~0.0  integration works, positions are recoverable from the file
    ~1.0  no predictive power, the file cannot yield a trajectory

Result on the sample: **0.94-1.00** — no predictive power.  That is why the
state document only carries anchors and never a reconstructed path.

    python scripts/probe_move_integration.py --abc <file.abc>
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from replay_state_engine import _decode_events  # noqa: E402

FPS = 15.0
MIN_DISPLACEMENT = 800       # ignore intervals where the player barely moved
MIN_INTERVALS = 5


def load(abc: Path) -> tuple[dict, dict]:
    """entity -> [(t, angle 0..2047)] and entity -> [(t, x, y)]."""
    data = abc.read_bytes()
    rows, _meta = _decode_events(data)

    moves: dict[int, list] = collections.defaultdict(list)
    for row in rows:
        if row.get("family") != "movement":
            continue
        fields = row.get("fields") or {}
        packed = fields.get("packed_move")
        entity = row.get("entity_id")
        if packed is None or entity is None:
            continue
        moves[int(entity)].append((float(row.get("time_s") or 0), int(packed) & 0x7FF))

    import replay_parser as rp  # noqa: WPS433
    report = rp.inspect_abc(data)
    anchors: dict[int, list] = collections.defaultdict(list)
    events = ((report.get("playerEvents") or {}).get("positions") or {}).get("events") or []
    for event in events:
        anchors[event["entityId"]].append(
            ((event["frame"] - 1) / FPS, event["x"], event["y"]))
    for items in anchors.values():
        items.sort()
    return moves, anchors


def fit_entity(anchors: list, moves: list, y_sign: int = 1) -> dict | None:
    intervals = []
    for (t0, x0, y0), (t1, x1, y1) in zip(anchors, anchors[1:]):
        if t1 - t0 <= 0:
            continue
        actual = (x1 - x0, y_sign * (y1 - y0))
        if math.hypot(*actual) < MIN_DISPLACEMENT:
            continue
        segment = [(t, a) for t, a in moves if t0 <= t < t1]
        if not segment:
            continue
        intervals.append((t0, t1, actual, segment))
    if len(intervals) < MIN_INTERVALS:
        return None

    best = None
    for offset_deg in range(0, 360, 2):
        offset = math.radians(offset_deg)
        predictions = []
        actuals = []
        for t0, t1, actual, segment in intervals:
            sx = sy = 0.0
            for index, (stamp, angle) in enumerate(segment):
                dt = (segment[index + 1][0] - stamp) if index + 1 < len(segment) else (t1 - stamp)
                theta = math.radians(angle / 2048 * 360) + offset
                sx += dt * math.cos(theta)
                sy += dt * math.sin(theta)
            predictions.append((sx, sy))
            actuals.append(actual)
        numerator = sum(px * ax + py * ay
                        for (px, py), (ax, ay) in zip(predictions, actuals))
        denominator = sum(px * px + py * py for px, py in predictions)
        if denominator <= 0:
            continue
        speed = numerator / denominator
        residual = sum(math.hypot(speed * px - ax, speed * py - ay)
                       for (px, py), (ax, ay) in zip(predictions, actuals))
        total = sum(math.hypot(*actual) for actual in actuals)
        if total <= 0:
            continue
        score = residual / total
        if best is None or score < best["ratio"]:
            best = {
                "entity": None,
                "ratio": round(score, 3),
                "offsetDeg": offset_deg,
                "speed": round(speed, 1),
                "intervals": len(intervals),
                "ySign": y_sign,
            }
    return best


def probe(abc: Path) -> dict:
    moves, anchors = load(abc)
    results = []
    for entity, items in sorted(anchors.items()):
        for y_sign in (1, -1):
            fitted = fit_entity(items, moves.get(entity) or [], y_sign)
            if fitted:
                fitted["entity"] = entity
                results.append(fitted)
    best = min(results, key=lambda item: item["ratio"]) if results else None
    return {
        "schema": "kpl-abc-move-integration-probe-v1",
        "abc": str(abc),
        "anchorsPerEntity": {str(k): len(v) for k, v in sorted(anchors.items())},
        "fits": results,
        "best": best,
        "verdict": ("integration works" if best and best["ratio"] < 0.2
                    else "no predictive power" if best and best["ratio"] > 0.8
                    else "inconclusive"),
        "note": ("ratio = residual / total displacement.  ~1.0 means the move "
                 "commands cannot reproduce the anchors, so the file alone "
                 "cannot yield a 15 fps trajectory."),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--abc", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if not args.abc.exists():
        print(f"missing .abc: {args.abc}", file=sys.stderr)
        return 2
    report = probe(args.abc)
    if args.json:
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0
    print(f"anchors per entity: {report['anchorsPerEntity']}")
    for fit in report["fits"]:
        print(f"  entity {fit['entity']:5d} ySign {fit['ySign']:+d}  "
              f"ratio {fit['ratio']:.3f}  offset {fit['offsetDeg']:3d}°  "
              f"speed {fit['speed']:8.1f}  intervals {fit['intervals']}")
    print(f"verdict: {report['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
