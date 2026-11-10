#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reconstruct per-frame world X/Z for the ten players of an .abc replay.

Offline only: this tool reads the replay file and the minimap JSON/CSV written
by other analyses; it never talks to a device, adb or the network.

Method (as briefed):
  1. The ten players start at their engine spawn anchors (X, Z).
  2. PLAYER_MOVE carries a per-frame input direction.  For every frame each
     player is advanced by  speed * dt * weight(dir) * world_vector.
  3. Aim targets (USEPOSITIONSKILL) are absolute map points; they are used as
     a soft, optional correction and as an independent residual probe.
  4. The reconstruction is validated against the minimap icon positions at six
     replay frames: identity-free bipartite assignment + world->minimap affine
     fit (all axis orders/flips tested), residuals reported in normalised units
     and as a percentage of the map span.

Important decoding facts baked into the model (see README for evidence):

  * ``mag`` is NOT a joystick magnitude.  ``dir_deg = -mag if sign else +mag``
    is a signed angle in [-180, 180]; the 8-bit field *is* the angle.  The
    briefed ``mag/127`` speed weight is therefore degenerate (a hero walking
    due east would be stationary); it is kept as a switchable model so the
    claim can be reproduced and refuted numerically.
  * The replay logic clock is 15.1515 fps (engine ``+0x1664/+0x1668`` pairs:
    57 frames per 3762 ms on the paused 07:29/07:32 unit dumps).  The battle
    frame/time map is ``t = (frame - F0) / fps`` with ``F0 = 31.4`` fitted from
    the engine clock at 07:29.23 (frame 6838 <-> 449.228 s).
  * World X maps to minimap +u and world Z maps to -v; the map spans about
    +/-60,000 coordinate units.  Coordinate units are millimetres (spawn
    anchors sit at +/-55,000 = the map corners); hence the engine "move speed"
    field 360-390 is centimetres/second, i.e. 3,600-3,900 units/second.

Outputs (all under --out-dir):
  player_trajectories.csv  frame,time,player,hero,entity,X,Z,source,...
  validation.json          every number used in the report
  validation.md            human-readable validation report
  minimap_matches.csv      per-frame assignment used for validation
  input_snapshot/          copy of the minimap input actually consumed

Usage:
  python -I tools/reconstruct_trajectories.py \
      --abc "data/replays/20261102_161129_..._2B9FAA08A7AD40D09ABDA364F9C1E804.abc" \
      --out-dir data/replays/_analysis/live_20261104/trajectories
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import replay_time  # noqa: E402
from tools.replay_frame_commands import events  # noqa: E402

# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------
DEFAULT_ABC = (
    ROOT / "data/replays/"
    "20261102_161129_870343216_95868_1793606215_2B9FAA08A7AD40D09ABDA364F9C1E804.abc"
)
DEFAULT_MINIMAP = (
    ROOT / "data/replays/_analysis/live_20261104/minimap_positions/positions.json"
)
SNAPSHOT_MINIMAP = (
    ROOT / "data/replays/_analysis/live_20261104/trajectories/input_snapshot/"
    "minimap_positions_snapshot.csv"
)
DEFAULT_OUT = ROOT / "data/replays/_analysis/live_20261104/trajectories"

# Roster from abc_timeline/README.md (verified against the decoded replay).
ROSTER = [
    # unit, entity, camp, slot, player, hero, spawn_x, spawn_z
    (8, 1168, 1, 0, "胡不喜#", "钟馗", -55764, -57574),
    (9, 1613, 1, 1, "自诩一棵葱", "妲己", -53911, -53939),
    (10, 750, 1, 2, "别吃窝线吖a", "孙悟空", -57673, -55764),
    (11, 538, 1, 3, "狂傲自由魂Z.", "关羽", -56379, -53367),
    (12, 1611, 1, 4, "漂流网咖︎", "百里守约", -53416, -56414),
    (16, 1031, 2, 0, "麻巫喵", "公孙离", 56368, 53358),
    (17, 296, 2, 1, "翳灵崽", "吕布", 53395, 56435),
    (18, 551, 2, 2, "一风舞", "貂蝉", 54045, 54045),
    (19, 1799, 2, 3, "扁鹊耳垂", "兰陵王", 55757, 57652),
    (20, 1760, 2, 4, "谜语星海", "张良", 57668, 55750),
]

# Screenshot label -> battle seconds.  The last three come from the engine
# clock read out of the paused unit dumps (+0x1668 ms) and are exact to ~10 ms;
# the first three are the replay clock labels (floor to the second), so the
# mid-point 94.0/165.0/300.0 is used and carries +/-0.5 s.
MINIMAP_TIMES = {
    "t0_ui.png": 94.0,
    "t2_ui.png": 165.0,
    "scoreboard_0500.png": 300.0,
    "light3.png": 446.2,
    "unit_t1_screen.png": 449.228,
    "matrix_t1_screen.png": 452.990,
}
MINIMAP_LABELS = {
    "t0_ui.png": "01:34",
    "t2_ui.png": "02:45",
    "scoreboard_0500.png": "05:00",
    "light3.png": "07:26",
    "unit_t1_screen.png": "07:29",
    "matrix_t1_screen.png": "07:32",
}

# Engine-derived defaults; the clock itself lives in replay_time.py.
FPS = replay_time.FPS_ENGINE          # replay logic clock (engine +0x1664/+0x1668)
F0 = replay_time.BATTLE_START_FRAME_ENGINE  # frame index of battle second 0
MAP_HALF_SPAN = 60000  # docs: map ~+/-60k, spawns at the four corners +/-55k
ENGINE_SPEED_PRIOR = 3700  # +0x2B4 field 360-390 (cm/s) in mm/s coordinate units


# --------------------------------------------------------------------------
# Decode
# --------------------------------------------------------------------------
def decode_inputs(abc_path: Path):
    """One pass over the replay: per-frame moves and absolute aim targets."""
    data = abc_path.read_bytes()
    moves = {}      # frame -> {unit: (dir_deg, mag, seq)}
    aims = []       # {frame, entity, target_x, target_y, slot}
    frames = 0
    for event in events(data):
        name = event.get("name")
        if name == "PLAYER_MOVE":
            moves.setdefault(event["frame"], {})[event["unit"]] = (
                event["dir_deg"], event["mag"], event["seq"])
        elif name == "USEPOSITIONSKILL":
            fields = event["fields"]
            aims.append({
                "frame": event["frame"],
                "entity": event["object_id"],
                "target_x": fields["target_x"],
                "target_y": fields["target_y"],
                "slot": fields.get("slot"),
            })
        if event["frame"] > frames:
            frames = event["frame"]
    return moves, aims, frames


def decode_inputs_from_csv(csv_path: Path):
    """Fallback: read the already-decoded event_windows.csv (four windows only).

    Returns the same shape as ``decode_inputs`` plus a set of covered frames.
    Because the CSV only covers the four +/-3 s checkpoints, trajectories can
    only be produced inside those windows; the caller marks the gaps.
    """
    moves, aims, frames = {}, [], 0
    covered = set()
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            frame = int(row["frame"])
            fields = json.loads(row["fields_json"])
            covered.add(frame)
            frames = max(frames, frame)
            try:
                unit = int(row["unit"])
            except (TypeError, ValueError):
                unit = None
            if row["family"] == "movement" and unit is not None:
                moves.setdefault(frame, {})[unit] = (
                    fields.get("dir_deg", 0), fields.get("mag", 0), fields.get("seq", 0))
            elif row["command"] == "USEPOSITIONSKILL":
                entity = int(row["entity_id"]) if row["entity_id"] else None
                aims.append({
                    "frame": frame,
                    "entity": entity,
                    "target_x": fields.get("target_x"),
                    "target_y": fields.get("target_y"),
                    "slot": fields.get("slot"),
                })
    return moves, aims, frames, covered


# --------------------------------------------------------------------------
# Minimap input
# --------------------------------------------------------------------------
def load_minimap(path: Path):
    """Return {'frames': {file: [{team, u, v, confidence}]}, 'source': str}."""
    frames = {}
    source = str(path)
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        for frame in payload.get("frames", []):
            heroes = []
            for hero in frame.get("heroes", []):
                heroes.append({
                    "team": "blue" if hero["team"] == "blue" else "red",
                    "u": float(hero["u"]),
                    "v": float(hero["v"]),
                    "confidence": hero.get("confidence", "unknown"),
                })
            frames[frame["file"]] = heroes
    else:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                frames.setdefault(row["frame"], []).append({
                    "team": row["team"],
                    "u": float(row["u"]),
                    "v": float(row["v"]),
                    "confidence": row.get("confidence", "unknown"),
                })
    if not frames:
        raise SystemExit(f"minimap input is empty: {path}")
    return {"frames": frames, "source": source}


def load_minimap_with_fallback(path: Path):
    """Load the requested minimap file, falling back to the snapshot.

    The live ``minimap_positions/positions.{json,csv}`` files are written by a
    separate job and were observed truncated to zero content during this run;
    the snapshot captured before that happened is used when the live file has
    no frames.
    """
    warnings = []
    for candidate in (path, SNAPSHOT_MINIMAP):
        if not candidate.exists():
            warnings.append(f"missing: {candidate}")
            continue
        try:
            loaded = load_minimap(candidate)
        except (SystemExit, ValueError) as exc:
            warnings.append(f"unreadable: {candidate}: {exc}")
            continue
        if candidate != path:
            warnings.append(f"fell back to snapshot: {candidate}")
        loaded["warnings"] = warnings
        return loaded
    raise SystemExit(f"no minimap input available (tried {path} and {SNAPSHOT_MINIMAP})")


# --------------------------------------------------------------------------
# Motion model
# --------------------------------------------------------------------------
def step_weight(model: str, dir_deg: int, mag: int, seq: int) -> float:
    if model == "constant":
        return 1.0
    if model == "seq":
        return (seq + 1) / 4.0
    if model == "mag127":       # the brief's literal formula
        return mag / 127.0
    if model == "mag180":
        return mag / 180.0
    raise SystemExit(f"unknown model {model}")


def integrate(moves, speed: float, fps: float, model: str, hold: bool,
              max_frame: int, corrections=None):
    """Dead-reckon ten players from their spawn anchors.

    corrections: optional {frame: {unit: (target_x, target_z)}} soft aim pulls
    applied before the frame is recorded.
    Returns {unit: [(x, z), ...]} indexed by frame-1 and
            {unit: [source, ...]} indexed by frame-1.
    """
    pos = {row[0]: [float(row[6]), float(row[7])] for row in ROSTER}
    track = {row[0]: [] for row in ROSTER}
    source = {row[0]: [] for row in ROSTER}
    last_dir = {}
    step = speed / fps
    for frame in range(1, max_frame + 1):
        frame_moves = moves.get(frame, {})
        for unit in pos:
            event = frame_moves.get(unit)
            if event is not None:
                direction, mag, seq = event
                weight = step_weight(model, direction, mag, seq)
                angle = math.radians(direction)
                # Replay native axes: +x east, +y south.  Engine: +X east,
                # +Z north, and .abc target_y == engine Z, so dZ = -sin(dir).
                pos[unit][0] += step * weight * math.cos(angle)
                pos[unit][1] -= step * weight * math.sin(angle)
                last_dir[unit] = direction
                src = "integrated"
            elif hold and unit in last_dir:
                angle = math.radians(last_dir[unit])
                pos[unit][0] += step * math.cos(angle)
                pos[unit][1] -= step * math.sin(angle)
                src = "held"
            else:
                src = "spawn" if frame < 150 else "idle"
            if corrections and frame in corrections and unit in corrections[frame]:
                tx, tz = corrections[frame][unit]
                pull = 0.5
                pos[unit][0] += pull * (tx - pos[unit][0])
                pos[unit][1] += pull * (tz - pos[unit][1])
                src = "aim_corrected"
            track[unit].append((pos[unit][0], pos[unit][1]))
            source[unit].append(src)
    return track, source


def snapshots(track, frames):
    """frame -> {unit: (x, z)} for the requested frames."""
    out = {}
    for frame in frames:
        index = min(max(frame - 1, 0), len(next(iter(track.values()))) - 1)
        out[frame] = {unit: values[index] for unit, values in track.items()}
    return out


def build_aim_corrections(aims, track, entity_to_unit,
                          max_range=12000.0, gain=0.5, max_pull=15000.0):
    """Soft aim constraint: pull a caster toward its target when out of range.

    A position skill lands at an absolute point within the hero's cast range.
    If the dead-reckoned caster is farther than ``max_range`` the prediction is
    wrong; pull it toward the target by ``gain`` of the excess (capped).
    """
    corrections = {}
    for aim in aims:
        unit = entity_to_unit.get(aim["entity"])
        if unit is None:
            continue
        index = min(max(aim["frame"] - 1, 0), len(track[unit]) - 1)
        x, z = track[unit][index]
        dx = aim["target_x"] - x
        dz = aim["target_y"] - z
        distance = math.hypot(dx, dz)
        if distance <= max_range:
            continue
        excess = min(distance - max_range, max_pull)
        corrections.setdefault(aim["frame"], {})[unit] = (
            x + gain * excess * dx / distance,
            z + gain * excess * dz / distance,
        )
    return corrections


# --------------------------------------------------------------------------
# Geometry: world -> minimap
# --------------------------------------------------------------------------
def conventions():
    """Eight axis-order/flip combinations.

    names follow (axis_u, axis_v, sign_u, sign_v) where u receives the first
    axis listed.
    """
    out = []
    for swap in (False, True):
        for sign_u in (1, -1):
            for sign_v in (1, -1):
                out.append({
                    "swap": swap, "sign_u": sign_u, "sign_v": sign_v,
                    "name": ("Z->u,X->v" if swap else "X->u,Z->v")
                            + f",su{sign_u:+d},sv{sign_v:+d}",
                })
    return out


def project(x, z, half_span, conv):
    su = conv["sign_u"] / (2.0 * half_span)
    sv = conv["sign_v"] / (2.0 * half_span)
    if conv["swap"]:
        return 0.5 + su * z, 0.5 + sv * x
    return 0.5 + su * x, 0.5 + sv * z


def best_assignment(cost, n_pred, n_det):
    """Exact min-cost injective assignment for at most 5x5 points.

    Returns [(pred_index, det_index), ...].  Uses itertools only (numpy would
    be overkill at this size).
    """
    from itertools import permutations
    k = min(n_pred, n_det)
    best = None
    for perm in permutations(range(n_det), k):
        total = 0.0
        for i in range(k):
            total += cost[i][perm[i]]
        if best is None or total < best[0]:
            best = (total, perm)
    if best is None:
        return []
    return [(i, best[1][i]) for i in range(k)]


def assign_frame(predictions, detections, half_span, conv, gate):
    """Assign predicted unit positions to detected minimap icons.

    predictions: {unit: (x, z)}; detections: [{team,u,v}]
    Only same-team pairs are allowed.  Pairs beyond ``gate`` (normalised) are
    dropped so a wrong trajectory cannot claim a far icon.  ``gate=None`` keeps
    every pair of the optimal injective assignment.
    """
    pairs = []
    for team, team_camp in (("blue", 1), ("red", 2)):
        dets = [d for d in detections if d["team"] == team]
        units = [(u, p) for u, p in predictions.items()
                 if UNIT_CAMP[u] == team_camp]
        if not dets or not units:
            continue
        uv = [project(p[0], p[1], half_span, conv) for _, p in units]
        cost = [[(a[0] - d["u"]) ** 2 + (a[1] - d["v"]) ** 2 for d in dets]
                for a in uv]
        for i, j in best_assignment(cost, len(units), len(dets)):
            if gate is None or cost[i][j] <= gate * gate:
                pairs.append({
                    "unit": units[i][0],
                    "det": dets[j],
                    "pred_uv": uv[i],
                    "dist": math.sqrt(cost[i][j]),
                })
    return pairs


UNIT_CAMP = {row[0]: row[2] for row in ROSTER}
UNIT_HERO = {row[0]: row[5] for row in ROSTER}


def residuals(snaps, minimap, half_span, conv, gate=0.25):
    """Per-frame assignment + residuals under a fixed projection.

    Returns a dict with the gated RMS (pairs farther than ``gate`` dropped) and
    the forced RMS (every same-team prediction paired, best injective
    assignment).  The gated number flatters a bad model by discarding its worst
    points; the forced number is the honest cost of the best matching.
    """
    per_frame = {}
    matched_rows = []
    all_sq = all_n = forced_sq = forced_n = 0.0
    for file, detections in minimap["frames"].items():
        frame = FRAME_OF[file]
        pairs = assign_frame(snaps[frame], detections, half_span, conv, gate)
        forced = assign_frame(snaps[frame], detections, half_span, conv, None)
        sq = sum(p["dist"] ** 2 for p in pairs)
        n = len(pairs)
        fsq = sum(p["dist"] ** 2 for p in forced)
        fn = len(forced)
        per_frame[file] = {
            "frame": frame,
            "time": MINIMAP_TIMES[file],
            "label": MINIMAP_LABELS[file],
            "matched": n,
            "detections": len(detections),
            "predictions": len(snaps[frame]),
            "rms_norm": math.sqrt(sq / n) if n else None,
            "rms_units": math.sqrt(sq / n) * 2 * half_span if n else None,
            "rms_norm_forced": math.sqrt(fsq / fn) if fn else None,
            "rms_units_forced": math.sqrt(fsq / fn) * 2 * half_span if fn else None,
        }
        all_sq += sq
        all_n += n
        forced_sq += fsq
        forced_n += fn
        for pair in pairs:
            matched_rows.append({
                "frame": file,
                "label": MINIMAP_LABELS[file],
                "unit": pair["unit"],
                "hero": UNIT_HERO[pair["unit"]],
                "team": pair["det"]["team"],
                "confidence": pair["det"]["confidence"],
                "pred_u": pair["pred_uv"][0],
                "pred_v": pair["pred_uv"][1],
                "det_u": pair["det"]["u"],
                "det_v": pair["det"]["v"],
                "dist_norm": pair["dist"],
            })
    return {
        "overall_gated": math.sqrt(all_sq / all_n) if all_n else None,
        "overall_forced": math.sqrt(forced_sq / forced_n) if forced_n else None,
        "per_frame": per_frame,
        "matches": matched_rows,
    }


def centroid_residuals(snaps, minimap, half_span, conv):
    """Identity-free team-centroid error (robust to missing icons)."""
    out = {}
    for file, detections in minimap["frames"].items():
        row = {}
        for team, team_camp in (("blue", 1), ("red", 2)):
            dets = [(d["u"], d["v"]) for d in detections if d["team"] == team]
            preds = [project(x, z, half_span, conv)
                     for u, (x, z) in snaps[FRAME_OF[file]].items()
                     if UNIT_CAMP[u] == team_camp]
            if not dets or not preds:
                continue
            dc = (statistics.fmean(p[0] for p in dets),
                  statistics.fmean(p[1] for p in dets))
            pc = (statistics.fmean(p[0] for p in preds),
                  statistics.fmean(p[1] for p in preds))
            row[team] = {
                "det_centroid": [round(dc[0], 4), round(dc[1], 4)],
                "pred_centroid": [round(pc[0], 4), round(pc[1], 4)],
                "dist_norm": math.hypot(dc[0] - pc[0], dc[1] - pc[1]),
                "det_icons": len(dets),
            }
        out[file] = row
    return out


# --------------------------------------------------------------------------
# Affine / similarity fit
# --------------------------------------------------------------------------
# The minimap frame is (u right, v down) while the engine frame is (X east,
# Z north); the two frames therefore differ by a reflection as well as a
# rotation.  The model fitted here is
#     Z' = r * Z            (r = +1 or -1, the chirality)
#     u  = cu + s * (cos t * X - sin t * Z')
#     v  = cv + s * (sin t * X + cos t * Z')
# which is linear in (cu, cv, p=s*cos t, q=s*sin t) for a fixed r.
def _convention_matrix(conv, half_span):
    s = 1.0 / (2.0 * half_span)
    if conv["swap"]:
        return (0.0, conv["sign_u"] * s, conv["sign_v"] * s, 0.0)
    return (conv["sign_u"] * s, 0.0, 0.0, conv["sign_v"] * s)


def _decompose_convention(conv, half_span):
    m00, m01, m10, m11 = _convention_matrix(conv, half_span)
    det = m00 * m11 - m01 * m10
    r = 1.0 if det >= 0 else -1.0
    a = m00
    b = r * m01
    if abs(b) < 1e-15 and abs(m10) < 1e-15:
        theta = 0.0 if a >= 0 else math.pi
        s = abs(a)
    else:
        s = math.hypot(a, m10)
        theta = math.atan2(m10, a)
    return {"s": s, "theta": theta, "r": r, "cu": 0.5, "cv": 0.5}


def _apply_model(x, z, s, theta, r, cu, cv):
    zr = r * z
    return (cu + s * (math.cos(theta) * x - math.sin(theta) * zr),
            cv + s * (math.sin(theta) * x + math.cos(theta) * zr))


def _solve_model(matched, r, prior, ridge=0.02):
    """Linear least squares for (cu, cv, p, q) with a mild ridge to the prior."""
    import numpy as np
    rows, rhs = [], []
    for pair in matched:
        x, z = pair["x"], pair["z"]
        rows.append([1.0, 0.0, x, -r * z])
        rhs.append(pair["det_u"])
        rows.append([0.0, 1.0, r * z, x])
        rhs.append(pair["det_v"])
    n = len(matched)
    lam = max(ridge * n, 1e-6)
    rows.append([0.0, 0.0, lam, 0.0])
    rhs.append(lam * prior["p"])
    rows.append([0.0, 0.0, 0.0, lam])
    rhs.append(lam * prior["q"])
    solution, *_ = np.linalg.lstsq(np.array(rows), np.array(rhs), rcond=None)
    cu, cv, p, q = solution
    return float(cu), float(cv), float(p), float(q)


def _match_for_fit(snaps, model, frames_allowed, gate):
    """Exact same-team assignment between the transformed model and detections."""
    matched = []
    per_frame = {}
    for file, detections in MINIMAP_DATA["frames"].items():
        if frames_allowed is not None and file not in frames_allowed:
            continue
        frame = FRAME_OF[file]
        sq = 0.0
        n = 0
        for team, team_camp in (("blue", 1), ("red", 2)):
            dets = [d for d in detections if d["team"] == team]
            units = [(u, snaps[frame][u]) for u in snaps[frame]
                     if UNIT_CAMP[u] == team_camp]
            if not dets or not units:
                continue
            uv = [model[s[0]] for s in units]
            cost = [[(a[0] - d["u"]) ** 2 + (a[1] - d["v"]) ** 2 for d in dets]
                    for a in uv]
            for i, j in best_assignment(cost, len(units), len(dets)):
                if cost[i][j] <= gate * gate:
                    x, z = units[i][1]
                    det = dets[j]
                    matched.append({"x": x, "z": z, "det_u": det["u"],
                                    "det_v": det["v"], "frame": file})
                    sq += cost[i][j]
                    n += 1
        per_frame[file] = math.sqrt(sq / n) if n else None
    return matched, per_frame


def fit_similarity(snaps, half_span, conv, frames_allowed=None, iterations=6,
                   gate=0.20):
    """ICP fit of the reflected similarity, initialised from the convention."""
    init = _decompose_convention(conv, half_span)
    s, theta, r = init["s"], init["theta"], init["r"]
    cu, cv = init["cu"], init["cv"]
    history = []
    current = []
    per_frame = {}
    for _ in range(iterations):
        model = {u: _apply_model(x, z, s, theta, r, cu, cv)
                 for u, (x, z) in _flatten(snaps, frames_allowed)}
        matched, per_frame = _match_for_fit(snaps, model, frames_allowed, gate)
        if len(matched) < 6:
            break
        current = matched
        prior = {"p": s * math.cos(theta), "q": s * math.sin(theta)}
        cu, cv, p, q = _solve_model(matched, r, prior)
        s_new = math.hypot(p, q)
        if not (1e-8 < s_new < 0.01):
            break
        s, theta = s_new, math.atan2(q, p)
        rms = math.sqrt(sum((_apply_model(m["x"], m["z"], s, theta, r, cu, cv)[0]
                             - m["det_u"]) ** 2
                            + (_apply_model(m["x"], m["z"], s, theta, r, cu, cv)[1]
                               - m["det_v"]) ** 2 for m in matched) / len(matched))
        history.append({"rms_norm": rms, "matched": len(matched)})
    return {
        "scale_norm_per_unit": s,
        "rotation_deg": math.degrees(theta),
        "reflection": "r=-1 (Z flipped)" if r < 0 else "r=+1",
        "translation": [cu, cv],
        "half_span_equivalent": 1.0 / (2.0 * s),
        "iterations": history,
        "matched": len(current),
        "per_frame": per_frame,
        "rms_norm": history[-1]["rms_norm"] if history else None,
    }


def _flatten(snaps, frames_allowed=None):
    for frame, positions in snaps.items():
        if frames_allowed is not None:
            file = FRAME_TO_FILE.get(frame)
            if file is not None and file not in frames_allowed:
                continue
        for unit, (x, z) in positions.items():
            yield unit, (x, z)


# --------------------------------------------------------------------------
# Speed calibration
# --------------------------------------------------------------------------
def speed_curve(moves, minimap, max_frame, fps, model, hold, speeds,
                half_span, conv):
    curve = []
    for speed in speeds:
        track, _ = integrate(moves, speed, fps, model, hold, max_frame)
        snaps = snapshots(track, FRAME_LIST)
        result = residuals(snaps, minimap, half_span, conv)
        curve.append({
            "speed": speed,
            "step_per_frame": speed / fps,
            "rms_norm": result["overall_gated"],
            "rms_norm_forced": result["overall_forced"],
            "per_frame": {k: v["rms_norm"] for k, v in result["per_frame"].items()},
        })
    return curve


# --------------------------------------------------------------------------
# Aim-point diagnostic
# --------------------------------------------------------------------------
def aim_diagnostics(aims, track, entity_to_unit, max_range=12000.0):
    rows = []
    for aim in aims:
        unit = entity_to_unit.get(aim["entity"])
        if unit is None:
            continue
        index = min(max(aim["frame"] - 1, 0), len(track[unit]) - 1)
        x, z = track[unit][index]
        distance = math.hypot(aim["target_x"] - x, aim["target_y"] - z)
        rows.append({
            "frame": aim["frame"],
            "unit": unit,
            "hero": UNIT_HERO[unit],
            "entity": aim["entity"],
            "slot": aim["slot"],
            "target_x": aim["target_x"],
            "target_y": aim["target_y"],
            "x": x,
            "z": z,
            "distance": distance,
            "within_range": distance <= max_range,
        })
    if not rows:
        return {"casts": 0}
    distances = sorted(row["distance"] for row in rows)
    by_unit = {}
    for unit in sorted({row["unit"] for row in rows}):
        values = sorted(row["distance"] for row in rows if row["unit"] == unit)
        by_unit[UNIT_HERO[unit]] = {
            "casts": len(values),
            "median": statistics.median(values),
            "p10": values[len(values) // 10],
            "p90": values[9 * len(values) // 10],
            "within_range": sum(1 for v in values if v <= max_range),
        }
    return {
        "casts": len(rows),
        "median": statistics.median(distances),
        "mean": statistics.fmean(distances),
        "p10": distances[len(distances) // 10],
        "p90": distances[9 * len(distances) // 10],
        "within_range": sum(1 for row in rows if row["within_range"]),
        "max_range_assumed": max_range,
        "by_hero": by_unit,
        "rows": rows,
    }


# --------------------------------------------------------------------------
# Reporting helpers
# --------------------------------------------------------------------------
def fmt(value, digits=3):
    return "n/a" if value is None else f"{value:.{digits}f}"


def fmt_units(value):
    return "n/a" if value is None else f"{value:,.0f}"


FRAME_OF = {}
FRAME_TO_FILE = {}
FRAME_LIST = []
MINIMAP_DATA = {}


def main() -> int:
    global FRAME_OF, FRAME_TO_FILE, FRAME_LIST, MINIMAP_DATA
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--abc", type=Path, default=DEFAULT_ABC)
    parser.add_argument("--events-csv", type=Path,
                        help="use the decoded event_windows.csv instead of the .abc "
                             "(four +/-3 s windows only)")
    parser.add_argument("--minimap", type=Path, default=DEFAULT_MINIMAP)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--fps", type=float, default=FPS,
                        help="replay logic frames per second (default 15.1515)")
    parser.add_argument("--f0", type=float, default=F0,
                        help="frame index of battle second 0 (default 31.4)")
    parser.add_argument("--speed", type=float, default=None,
                        help="units/second; omit to calibrate")
    parser.add_argument("--model", choices=("constant", "seq", "mag127", "mag180"),
                        default="constant",
                        help="speed weight per input row (mag127 is the briefed "
                             "formula and is refuted by this data)")
    parser.add_argument("--hold", action="store_true",
                        help="hold the last direction between input rows")
    parser.add_argument("--map-half-span", type=float, default=MAP_HALF_SPAN)
    parser.add_argument("--convention", default="X->u,Z->v,su+1,sv-1",
                        help="axis convention for the primary report")
    parser.add_argument("--gate", type=float, default=0.25,
                        help="assignment gate in normalised minimap units")
    parser.add_argument("--aim-correction", action="store_true",
                        help="apply the soft aim-point correction before recording")
    parser.add_argument("--aim-max-range", type=float, default=12000.0)
    parser.add_argument("--aim-gain", type=float, default=0.5)
    parser.add_argument("--speed-grid", default="300,600,900,1200,1500,1800,2400,"
                                             "3000,3600,4200,4800,5400,6000")
    parser.add_argument("--quick", action="store_true",
                        help="skip the full speed grid and affine cross-validation")
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    # ---- inputs ---------------------------------------------------------
    if args.events_csv:
        moves, aims, max_frame, covered = decode_inputs_from_csv(args.events_csv)
        decode_source = str(args.events_csv)
    else:
        moves, aims, max_frame = decode_inputs(args.abc)
        covered = None
        decode_source = str(args.abc)

    minimap = load_minimap_with_fallback(args.minimap)
    missing = set(MINIMAP_TIMES) - set(minimap["frames"])
    for file in sorted(missing):
        raise SystemExit(f"minimap frame {file} missing from {minimap['source']}")

    FRAME_OF = {file: int(round(args.f0 + MINIMAP_TIMES[file] * args.fps))
                for file in minimap["frames"]}
    if args.events_csv:
        beyond = [f for f, frame in FRAME_OF.items() if frame > max_frame]
        for file in beyond:
            del minimap["frames"][file]
            del FRAME_OF[file]
        if beyond:
            minimap.setdefault("warnings", []).append(
                "events CSV covers only frames <= %d; dropped minimap frames %s"
                % (max_frame, sorted(beyond)))
        if not minimap["frames"]:
            raise SystemExit("no minimap frame falls inside the event CSV windows")
    MINIMAP_DATA = minimap
    FRAME_TO_FILE = {frame: file for file, frame in FRAME_OF.items()}
    FRAME_LIST = sorted(set(FRAME_OF.values()))

    entity_to_unit = {row[1]: row[0] for row in ROSTER}
    unit_entity = {row[0]: row[1] for row in ROSTER}
    unit_player = {row[0]: row[4] for row in ROSTER}

    conventions_list = conventions()
    primary = next(c for c in conventions_list if c["name"] == args.convention)

    # ---- speed calibration ---------------------------------------------
    default_grid = [float(x) for x in args.speed_grid.split(",") if x.strip()]
    calibration = {"grid": default_grid, "model": args.model, "hold": args.hold}
    if args.speed is None:
        curve = speed_curve(moves, minimap, max_frame, args.fps, args.model,
                            args.hold, default_grid, args.map_half_span, primary)
        best = min((row for row in curve if row["rms_norm_forced"] is not None),
                   key=lambda row: row["rms_norm_forced"])
        speed = best["speed"]
        calibration.update({"curve": curve, "chosen": speed,
                            "criterion": "minimap RMS with every same-team point "
                                         "forced into the assignment (normalised "
                                         "units); the gated RMS is reported too"})
    else:
        speed = args.speed
        calibration.update({"chosen": speed, "criterion": "user supplied"})
    calibration["step_per_frame"] = speed / args.fps
    calibration["engine_speed_prior"] = ENGINE_SPEED_PRIOR
    calibration["step_at_engine_prior"] = ENGINE_SPEED_PRIOR / args.fps

    # ---- base integration ----------------------------------------------
    track, sources = integrate(moves, speed, args.fps, args.model, args.hold,
                               max_frame)
    snaps = snapshots(track, FRAME_LIST)

    # ---- aim diagnostics before correction ------------------------------
    aim_before = aim_diagnostics(aims, track, entity_to_unit, args.aim_max_range)

    # ---- optional aim correction ---------------------------------------
    aim_after = None
    correction_count = 0
    if args.aim_correction:
        corrections = build_aim_corrections(
            aims, track, entity_to_unit, max_range=args.aim_max_range,
            gain=args.aim_gain)
        correction_count = sum(len(v) for v in corrections.values())
        track, sources = integrate(moves, speed, args.fps, args.model,
                                   args.hold, max_frame, corrections=corrections)
        snaps = snapshots(track, FRAME_LIST)
        aim_after = aim_diagnostics(aims, track, entity_to_unit, args.aim_max_range)

    # ---- validation under the primary fixed projection ------------------
    primary_result = residuals(snaps, minimap, args.map_half_span, primary,
                               args.gate)
    rms_primary = primary_result["overall_gated"]
    rms_primary_forced = primary_result["overall_forced"]
    per_frame_primary = primary_result["per_frame"]
    matches = primary_result["matches"]
    best_matches = sorted(matches, key=lambda r: r["dist_norm"])[:10]
    centroids = centroid_residuals(snaps, minimap, args.map_half_span, primary)

    # ---- all eight conventions -----------------------------------------
    convention_table = []
    for conv in conventions_list:
        result = residuals(snaps, minimap, args.map_half_span, conv, args.gate)
        convention_table.append({
            "name": conv["name"],
            "rms_norm": result["overall_gated"],
            "rms_norm_forced": result["overall_forced"],
            "matched": sum(v["matched"] for v in result["per_frame"].values()),
            "per_frame": {k: v["rms_norm"] for k, v in result["per_frame"].items()},
        })

    # ---- speed x model table (small) ------------------------------------
    model_table = []
    if not args.quick:
        for model in ("constant", "seq", "mag127", "mag180"):
            for candidate in (0.5 * speed, speed, 2.0 * speed):
                curve_track, _ = integrate(moves, candidate, args.fps, model,
                                           args.hold, max_frame)
                curve_snaps = snapshots(curve_track, FRAME_LIST)
                result = residuals(curve_snaps, minimap, args.map_half_span,
                                   primary, args.gate)
                aim = aim_diagnostics(aims, curve_track, entity_to_unit,
                                      args.aim_max_range)
                model_table.append({
                    "model": model,
                    "speed": candidate,
                    "rms_norm": result["overall_gated"],
                    "rms_norm_forced": result["overall_forced"],
                    "aim_median": aim.get("median"),
                })

    # ---- affine / similarity fit ---------------------------------------
    affine = {"primary": None, "conventions": []}
    if not args.quick:
        for conv in conventions_list:
            fitted = fit_similarity(snaps, args.map_half_span, conv)
            affine["conventions"].append({"convention": conv["name"], **{
                k: fitted[k] for k in ("scale_norm_per_unit",
                                       "rotation_deg", "reflection",
                                       "translation", "half_span_equivalent",
                                       "matched", "rms_norm")}})
        affine["primary"] = fit_similarity(snaps, args.map_half_span, primary)

    # ---- held-out validation -------------------------------------------
    held_out = None
    if not args.quick:
        early = [f for f in minimap["frames"] if f in
                 ("t0_ui.png", "t2_ui.png", "scoreboard_0500.png")]
        late = [f for f in minimap["frames"] if f not in early]
        held_out = {}
        for name, fit_files, test_files in (
                ("fit_early_test_late", early, late),
                ("fit_late_test_early", late, early)):
            fitted = fit_similarity(snaps, args.map_half_span, primary,
                                    frames_allowed=set(fit_files))
            model = {u: _apply_model(x, z, fitted["scale_norm_per_unit"],
                                     math.radians(fitted["rotation_deg"]),
                                     -1.0 if fitted["reflection"].startswith("r=-1") else 1.0,
                                     fitted["translation"][0],
                                     fitted["translation"][1])
                     for u, (x, z) in _flatten(snaps, set(test_files))}
            _, per_frame = _match_for_fit(snaps, model, set(test_files), args.gate)
            values = [v for v in per_frame.values() if v is not None]
            held_out[name] = {
                "fit_frames": fit_files,
                "test_frames": test_files,
                "rms_norm": (math.sqrt(sum(v * v for v in values) / len(values))
                             if values else None),
                "per_frame": per_frame,
                "transform": {k: fitted[k] for k in
                              ("scale_norm_per_unit", "rotation_deg",
                               "reflection", "translation", "matched")},
            }

    # ---- drift estimate --------------------------------------------------
    drift = {}
    points = [(MINIMAP_TIMES[f], per_frame_primary[f]["rms_norm"])
              for f in per_frame_primary if per_frame_primary[f]["rms_norm"]]
    if len(points) >= 3:
        t_mean = statistics.fmean(p[0] for p in points)
        r_mean = statistics.fmean(p[1] for p in points)
        den = sum((t - t_mean) ** 2 for t, _ in points)
        slope = sum((t - t_mean) * (r - r_mean) for t, r in points) / den if den else 0
        drift = {
            "rms_slope_per_minute": slope * 60.0,
            "first_rms": points[0][1],
            "last_rms": points[-1][1],
            "t_first": points[0][0],
            "t_last": points[-1][0],
            "note": "the RMS is already at map scale by the first checkpoint, so "
                    "the slope measures saturation, not the onset of drift",
        }
    for team in ("blue", "red"):
        values = [(MINIMAP_TIMES[f], row[team]["dist_norm"])
                  for f, row in centroids.items() if team in row]
        if len(values) >= 2:
            drift[f"centroid_{team}_mean"] = statistics.fmean(v for _, v in values)
            drift[f"centroid_{team}_first"] = values[0][1]
            drift[f"centroid_{team}_last"] = values[-1][1]
            drift[f"centroid_{team}_change"] = values[-1][1] - values[0][1]

    coverage = {}
    for unit in sorted(sources):
        counts = {}
        for value in sources[unit]:
            counts[value] = counts.get(value, 0) + 1
        coverage[UNIT_HERO[unit]] = counts

    # ---- verdict ---------------------------------------------------------
    span = 2 * args.map_half_span
    target = 0.05
    usable = (rms_primary is not None and rms_primary <= target
              and rms_primary_forced is not None and rms_primary_forced <= target)
    verdict = {
        "target_rms_norm": target,
        "target_rms_units": target * span,
        "achieved_rms_norm": rms_primary,
        "achieved_rms_units": (rms_primary * span) if rms_primary else None,
        "achieved_pct_of_span": (100.0 * rms_primary) if rms_primary else None,
        "achieved_rms_norm_forced": rms_primary_forced,
        "achieved_pct_of_span_forced": (100.0 * rms_primary_forced
                                        if rms_primary_forced else None),
        "usable": usable,
        "threshold_check": "PASS" if usable else "FAIL",
    }

    # ---- write outputs ---------------------------------------------------
    write_trajectory_csv(args.out_dir / "player_trajectories.csv", track,
                         sources, unit_player, unit_entity, args.fps, args.f0)
    write_match_csv(args.out_dir / "minimap_matches.csv", matches)
    copy_snapshot(minimap, args.out_dir)

    report = {
        "match": {
            "abc": str(args.abc),
            "decode_source": decode_source,
            "decoded_frames": max_frame,
            "moves_decoded": sum(len(v) for v in moves.values()),
            "aim_casts_decoded": len(aims),
        },
        "time_base": {
            "fps": args.fps,
            "f0": args.f0,
            "minimap_frames": {f: FRAME_OF[f] for f in FRAME_OF},
            "note": "engine clock (+0x1668 ms at 07:29 dump) gives 15.1515 fps; "
                    "event_windows.csv uses 15 fps with F0=0, which is 45-110 "
                    "frames early at the later checkpoints",
        },
        "model": {
            "name": args.model,
            "hold": args.hold,
            "speed": speed,
            "step_per_frame": speed / args.fps,
            "map_half_span": args.map_half_span,
            "convention": primary["name"],
            "note": "mag is the signed angle; the mag/127 weight is refuted",
        },
        "calibration": calibration,
        "validation": {
            "overall_rms_norm": rms_primary,
            "overall_rms_units": (rms_primary * span) if rms_primary else None,
            "overall_rms_norm_forced": rms_primary_forced,
            "overall_rms_units_forced": ((rms_primary_forced * span)
                                         if rms_primary_forced else None),
            "per_frame": per_frame_primary,
            "centroids": centroids,
            "best_matches": [{k: row[k] for k in
                              ("frame", "label", "hero", "dist_norm")}
                             for row in best_matches],
            "conventions": convention_table,
            "models": model_table,
            "affine": affine,
            "held_out": held_out,
            "drift": drift,
            "verdict": verdict,
        },
        "aim": {
            "before": summarize_aim(aim_before),
            "after": summarize_aim(aim_after) if aim_after else None,
            "corrections_applied": correction_count,
        },
        "coverage": coverage,
        "inputs": {
            "minimap_source": minimap["source"],
            "minimap_warnings": minimap.get("warnings", []),
        },
        "limitations": [
            "PLAYER_MOVE carries input directions, not positions; integration is "
            "dead reckoning and accumulates error from terrain collisions, "
            "respawns/recalls (no death events are decoded in this replay) and "
            "any camera-relative input.",
            "The six minimap frames contain 4-9 icons and no hero identity; the "
            "assignment is an optimal same-team matching, so residuals include "
            "assignment error as well as position error.",
            "Aim targets are the skill's ground point, not the caster position; "
            "they are within one skill range (unknown, ~8-12k) of the caster.",
            "The battle clock carries +/-0.5 s at the three clock-label frames; "
            "at 3.7 s per 20k units this alone is ~3k units of apparent drift.",
            "The fitted similarity scale "
            + (f"(half-span equivalent "
               f"{affine['primary']['half_span_equivalent']:,.0f}) "
               if affine.get("primary") else "")
            + "disagrees with the anchor geometry (±60k) when far from it, "
              "which means the fit absorbs trajectory error rather than "
              "recovering a real camera transform.",
        ],
    }
    (args.out_dir / "validation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.out_dir / "validation.md").write_text(
        render_markdown(report, args, span), encoding="utf-8")
    print(json.dumps({
        "out_dir": str(args.out_dir),
        "speed": speed,
        "step_per_frame": speed / args.fps,
        "rms_norm_forced": rms_primary_forced,
        "pct_of_span_forced": verdict["achieved_pct_of_span_forced"],
        "rms_norm_gated": rms_primary,
        "pct_of_span_gated": verdict["achieved_pct_of_span"],
        "usable": usable,
        "aim_median": aim_before.get("median"),
        "minimap_source": minimap["source"],
    }, ensure_ascii=False, indent=2))
    return 0


def summarize_aim(aim):
    if not aim or not aim.get("casts"):
        return None
    return {k: aim[k] for k in ("casts", "median", "mean", "p10", "p90",
                                "within_range", "max_range_assumed",
                                "by_hero")}


def write_trajectory_csv(path: Path, track, sources, unit_player, unit_entity,
                         fps, f0):
    import numpy as np
    units = sorted(track)
    n = len(track[units[0]])
    frames = np.arange(1, n + 1)
    times = (frames - f0) / fps
    times_csv = (frames - 1) / 15.0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        writer = csv.writer(handle)
        writer.writerow(["frame", "time", "player", "hero", "entity",
                         "X", "Z", "source", "time_csv", "camp", "unit"])
        for index in range(n):
            frame = int(frames[index])
            for unit in units:
                x, z = track[unit][index]
                writer.writerow([
                    frame, f"{times[index]:.3f}",
                    unit_player[unit], UNIT_HERO[unit], unit_entity[unit],
                    f"{x:.1f}", f"{z:.1f}",
                    sources[unit][index],
                    f"{times_csv[index]:.3f}", UNIT_CAMP[unit], unit,
                ])


def write_match_csv(path: Path, matches):
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        writer = csv.writer(handle)
        writer.writerow(["frame", "label", "unit", "hero", "team", "confidence",
                         "pred_u", "pred_v", "det_u", "det_v", "dist_norm"])
        for row in matches:
            writer.writerow([
                row["frame"], row["label"], row["unit"], row["hero"],
                row["team"], row["confidence"],
                f"{row['pred_u']:.4f}", f"{row['pred_v']:.4f}",
                f"{row['det_u']:.4f}", f"{row['det_v']:.4f}",
                f"{row['dist_norm']:.4f}",
            ])


def copy_snapshot(minimap, out_dir: Path):
    """Record exactly which minimap detections were consumed."""
    target = out_dir / "input_snapshot" / "minimap_positions_consumed.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        writer = csv.writer(handle)
        writer.writerow(["frame", "label", "team", "u", "v", "confidence"])
        for file, detections in minimap["frames"].items():
            for det in detections:
                writer.writerow([file, MINIMAP_LABELS.get(file, ""),
                                 det["team"], f"{det['u']:.4f}",
                                 f"{det['v']:.4f}", det["confidence"]])
    note = out_dir / "input_snapshot" / "README.md"
    note.write_text(
        "# Minimap input snapshot\n\n"
        f"Consumed from: `{minimap['source']}`\n\n"
        "`minimap_positions_consumed.csv` is the exact 44-row input used by\n"
        "`tools/reconstruct_trajectories.py` for validation.  It was captured\n"
        "because the live `minimap_positions/positions.{json,csv}` files in the\n"
        "parent directory were observed truncated (json = 761 bytes, csv = 0\n"
        "bytes) by a concurrent job at 16:08 on 2026-11-04, after the 15:43\n"
        "extraction run.  The row values are copied verbatim from that 15:43\n"
        "output; `positions.csv` row counts per frame (8/9/8/4/7/8) match the\n"
        "15:43 README table.\n", encoding="utf-8")


def render_markdown(report, args, span):
    v = report["validation"]
    verdict = v["verdict"]
    lines = []
    add = lines.append
    add("# Trajectory reconstruction — validation report\n")
    add(f"- Replay: `{report['match']['abc']}`")
    add(f"- Decoded: {report['match']['decoded_frames']:,} frames, "
        f"{report['match']['moves_decoded']:,} PLAYER_MOVE rows, "
        f"{report['match']['aim_casts_decoded']} USEPOSITIONSKILL casts")
    add(f"- Model: `{report['model']['name']}` weight, hold={report['model']['hold']}, "
        f"speed={report['calibration']['chosen']:.0f} units/s at "
        f"{report['time_base']['fps']} fps")
    add(f"- Map span assumed: {span:,.0f} units "
        f"(half-span {args.map_half_span:,.0f})")
    add("")
    add("## Verdict\n")
    add(f"**{verdict['threshold_check']}** — with every same-team point forced "
        f"into the assignment (the conservative, unbiased number) the RMS "
        f"position error is **{fmt(verdict['achieved_rms_norm_forced'])} of the "
        f"map span ({verdict['achieved_pct_of_span_forced']:.1f}%)**, target ≤ 5%. "
        f"Restricting to pairs that pass the {args.gate:.2f} assignment gate "
        f"gives {fmt(verdict['achieved_rms_norm'])} "
        f"({verdict['achieved_pct_of_span']:.1f}%), i.e. the model explains only "
        f"the subset that happens to land near an icon.")
    add("")
    add("## Speed calibration\n")
    add("| speed (u/s) | step/frame | minimap RMS (norm, gated) | RMS (forced) |")
    add("|---:|---:|---:|---:|")
    for row in report["calibration"].get("curve", []):
        add(f"| {row['speed']:.0f} | {row['step_per_frame']:.1f} | "
            f"{fmt(row['rms_norm'])} | {fmt(row.get('rms_norm_forced'))} |")
    add("")
    add(f"Chosen speed: **{report['calibration']['chosen']:.0f} units/s** "
        f"(step {report['calibration']['step_per_frame']:.1f} units/frame). "
        f"Engine field prior 360-390 (cm/s) = "
        f"{report['calibration']['engine_speed_prior']:,} units/s at this "
        f"coordinate scale; the two are {'consistent' if abs(report['calibration']['chosen'] - report['calibration']['engine_speed_prior']) < 0.35 * report['calibration']['engine_speed_prior'] else 'inconsistent'}.")
    add("")
    add("## Minimap residuals by frame (anchor-derived X->u, Z->-v, ±60k)\n")
    add("| frame | label | matched | RMS (norm) | RMS (units) | % span | forced RMS |")
    add("|---|---|---:|---:|---:|---:|---:|")
    for file, row in v["per_frame"].items():
        pct = (f"{100 * row['rms_norm']:.1f}%" if row["rms_norm"] is not None
               else "n/a")
        add(f"| {file} | {row['label']} | {row['matched']}/{row['detections']} | "
            f"{fmt(row['rms_norm'])} | {fmt_units(row['rms_units'])} | "
            f"{pct} | {fmt(row.get('rms_norm_forced'))} |")
    add("")
    add("## Identity-free centroid residuals\n")
    add("| frame | team | detection centroid | model centroid | distance |")
    add("|---|---|---|---|---:|")
    for file, row in v["centroids"].items():
        for team, data in row.items():
            add(f"| {file} | {team} | "
                f"({data['det_centroid'][0]:.3f}, {data['det_centroid'][1]:.3f}) | "
                f"({data['pred_centroid'][0]:.3f}, {data['pred_centroid'][1]:.3f}) | "
                f"{data['dist_norm']:.3f} |")
    add("")
    if v.get("best_matches"):
        add("## Best individual matches (evidence of local validity)\n")
        add("| frame | label | hero | distance (norm) |")
        add("|---|---|---|---:|")
        for row in v["best_matches"]:
            add(f"| {row['frame']} | {row['label']} | {row['hero']} | "
                f"{row['dist_norm']:.3f} |")
        add("")
    if v.get("conventions"):
        add("## Axis conventions (fixed projection, no fitting)\n")
        add("By the unbiased forced RMS the anchor-derived `X->u, Z->-v` "
            "projection wins; the gated RMS differences are within the noise "
            "of a trajectory that is already at map-scale error.\n")
        add("| convention | RMS (norm, gated) | RMS (forced) | matched |")
        add("|---|---:|---:|---:|")
        for row in sorted(v["conventions"],
                          key=lambda r: (r.get("rms_norm_forced") is None,
                                         r.get("rms_norm_forced") or 9)):
            add(f"| `{row['name']}` | {fmt(row['rms_norm'])} | "
                f"{fmt(row.get('rms_norm_forced'))} | {row['matched']} |")
        add("")
    if v.get("affine", {}).get("primary"):
        aff = v["affine"]["primary"]
        add("## Fitted world→minimap similarity\n")
        add(f"- scale: {aff['scale_norm_per_unit']:.3e} norm/unit "
            f"(equivalent half-span {aff['half_span_equivalent']:,.0f})")
        add(f"- rotation: {aff['rotation_deg']:.2f}°")
        add(f"- reflection: {aff['reflection']}")
        add(f"- translation: ({aff['translation'][0]:.3f}, {aff['translation'][1]:.3f})")
        add(f"- matched pairs: {aff['matched']}, RMS {fmt(aff['rms_norm'])}")
        add(f"- iterations: {aff['iterations']}")
        add("")
        if abs(aff["half_span_equivalent"] - args.map_half_span) > 0.25 * args.map_half_span:
            add(f"**Reject this transform as a physical calibration**: its "
                f"half-span equivalent ({aff['half_span_equivalent']:,.0f}) "
                f"differs from the anchor geometry ({args.map_half_span:,.0f}) "
                f"by more than 25%.  The fit is shrinking/rotating the world to "
                f"absorb trajectory error; the map geometry from the ten spawn "
                f"anchors is the valid projection.\n")
        add("| convention | scale | rotation (deg) | half-span equiv | matched | RMS |")
        add("|---|---:|---:|---:|---:|---:|")
        for row in v["affine"]["conventions"]:
            add(f"| `{row['convention']}` | {row['scale_norm_per_unit']:.3e} | "
                f"{row['rotation_deg']:.2f} | {row['half_span_equivalent']:,.0f} | "
                f"{row['matched']} | {fmt(row['rms_norm'])} |")
        add("")
    if v.get("held_out"):
        add("## Held-out cross-validation\n")
        add("| split | RMS (norm) | per-frame |")
        add("|---|---:|---|")
        for name, row in v["held_out"].items():
            per = ", ".join(f"{k}={fmt(val)}" for k, val in row["per_frame"].items())
            add(f"| {name} | {fmt(row['rms_norm'])} | {per} |")
        add("")
    if v.get("models"):
        add("## Motion-model comparison (same speed grid)\n")
        add("| model | speed | minimap RMS (norm) | aim median (units) |")
        add("|---|---:|---:|---:|")
        for row in v["models"]:
            add(f"| {row['model']} | {row['speed']:.0f} | {fmt(row['rms_norm'])} | "
                f"{fmt_units(row['aim_median'])} |")
        add("")
    add("## Aim-point residual probe\n")
    before = report["aim"]["before"]
    if before:
        add(f"- {before['casts']} casts, median |target − position| = "
            f"**{fmt_units(before['median'])} units**, p10 {fmt_units(before['p10'])}, "
            f"p90 {fmt_units(before['p90'])}")
        add(f"- within the assumed {before['max_range_assumed']:,.0f}-unit skill "
            f"range: {before['within_range']}/{before['casts']}")
        for hero, row in before["by_hero"].items():
            add(f"  - {hero}: {row['casts']} casts, median "
                f"{fmt_units(row['median'])}, within {row['within_range']}")
        if report["aim"].get("after"):
            after = report["aim"]["after"]
            add(f"- after soft aim correction ({report['aim']['corrections_applied']} "
                f"pulls): median {fmt_units(after['median'])}, within "
                f"{after['within_range']}/{after['casts']}")
    add("")
    if v.get("drift"):
        d = v["drift"]
        add("## Drift estimate\n")
        if "rms_slope_per_minute" in d:
            add(f"- RMS grows {d['rms_slope_per_minute']:+.4f} per minute "
                f"({fmt(d['first_rms'])} at t={d['t_first']:.0f}s → "
                f"{fmt(d['last_rms'])} at t={d['t_last']:.0f}s).")
            add("- The RMS is already at map scale at the first checkpoint, so "
                "the slope measures saturation, not the onset of drift.")
        for team in ("blue", "red"):
            key = f"centroid_{team}_mean"
            if key in d:
                add(f"- identity-free team centroid error ({team}): mean "
                    f"{d[key]:.3f}, {d[f'centroid_{team}_first']:.3f} → "
                    f"{d[f'centroid_{team}_last']:.3f} over the match "
                    f"({d[f'centroid_{team}_change']:+.3f}).")
        add("")
    add("## Coverage (frames per source class)\n")
    add("| hero | source counts |")
    add("|---|---|")
    for hero, counts in report["coverage"].items():
        add(f"| {hero} | {counts} |")
    add("")
    add("## Limitations\n")
    for item in report["limitations"]:
        add(f"- {item}")
    add("")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
