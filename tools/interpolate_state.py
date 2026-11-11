#!/usr/bin/env python3
"""Per-frame gold / KDA / HP estimates for the ten players of 20261102_161129.

Offline, stdlib-only.  The tool reads the verified anchors that were collected
from the GameCore arena snapshots, the replay UI team panel, the attributes
panel and the settlement screen, then builds two per-frame (15.1515 fps)
piecewise-linear estimates:

  * ``per_frame.csv`` / ``per_frame.jsonl``
        Strictly the primary anchors listed in the task (01:34, 02:45, 05:00,
        settlement at 11:33, plus a model start at 00:00 with 300 g).
  * ``per_frame_supplementary.csv`` / ``per_frame_supplementary.jsonl.gz``
        The same primary anchors plus the independently read team-panel
        snapshots at 01:27 / 03:32 / 05:56 / 09:01 / 11:10.  This variant is
        more accurate but relies on the supplementary UI samples.

HP is handled separately: only the ``unit_<player>_t0/t1.bin`` snapshots at
07:29.x / 07:32.x carry a normalised HP pair.  HP is interpolated only inside
the sampled 3.8 s window (6.4 s for 钟馗); everywhere else it is explicitly
``unknown``.  Absolute HP is ``panel max HP at 07:29 * normalised ratio``.

The tool never invents kill events.  Fractional KDA between anchors is the
expected cumulative count, not a claim that a kill happened at that frame.
Purchase/skill events from the full ``.abc`` timeline are attached as context
columns only; they are never used to move gold or KDA.

Outputs are written to ``data/replays/_analysis/live_20261104/interpolated_state``
by default.  The tool writes nothing outside that directory.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import json
import math
import statistics
import struct
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import replay_time  # noqa: E402

LIVE_DIR = ROOT / "data" / "replays" / "_analysis" / "live_20261104"
DEFAULT_OUT = LIVE_DIR / "interpolated_state"
ABC_TIMELINE = DEFAULT_OUT / "abc_input_timeline.json"
ABC_REPLAY = (
    ROOT
    / "data"
    / "replays"
    / "20261102_161129_870343216_95868_1793606215_2B9FAA08A7AD40D09ABDA364F9C1E804.abc"
)
OFFICIAL_TEAM_GOLD = (
    ROOT / "data" / "replays" / "_analysis" / "datasets" / "20261102_official_team_gold.csv"
)

FPS = replay_time.FPS_ENGINE
END_S = 693.0
FRAME_COUNT = int(round(END_S * FPS))

CONF_ANCHOR = "anchor"
CONF_INTERP = "interpolated"
CONF_MODEL = "model"
CONF_UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Roster
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Player:
    unit: int
    camp: int
    slot: int
    name: str
    hero: str
    entity: int
    aliases: tuple[str, ...] = ()

    @property
    def team(self) -> str:
        return "blue" if self.camp == 1 else "red"


PLAYERS: tuple[Player, ...] = (
    Player(8, 1, 0, "胡不喜#", "钟馗", 1168, ("胡不喜",)),
    Player(9, 1, 1, "自诩一棵葱", "妲己", 1613),
    Player(10, 1, 2, "别吃窝线吖a", "孙悟空", 750),
    Player(11, 1, 3, "狂傲自由魂Z.", "关羽", 538),
    Player(12, 1, 4, "漂流网咖", "百里守约", 1611),
    Player(16, 2, 0, "麻巫喵", "公孙离", 1031),
    Player(17, 2, 1, "翳灵崽", "吕布", 296),
    Player(18, 2, 2, "一风舞", "貂蝉", 551, ("一帆舞",)),
    Player(19, 2, 3, "扁鹊耳垂", "兰陵王", 1799, ("翩鹊耳垂",)),
    Player(20, 2, 4, "谜语星海", "张良", 1760),
)
HEROES: tuple[str, ...] = tuple(p.hero for p in PLAYERS)
PLAYER_BY_HERO = {p.hero: p for p in PLAYERS}
HERO_ALIASES: dict[str, str] = {}
for _p in PLAYERS:
    HERO_ALIASES[_p.hero] = _p.hero
    for _a in _p.aliases:
        HERO_ALIASES[_a] = _p.hero


# ---------------------------------------------------------------------------
# Verified anchors
# ---------------------------------------------------------------------------


@dataclass
class Anchor:
    aid: str
    time_s: float
    tier: str  # primary | supplementary | supplementary_unsaved | model_start
    source: str
    note: str
    gold: dict[str, float]
    kda: dict[str, tuple[int, int, int]]

    @property
    def is_measured(self) -> bool:
        return self.tier != "model_start"


def _anchor(
    aid: str,
    time_s: float,
    tier: str,
    source: str,
    note: str,
    gold_values: Sequence[float],
    kda_values: Sequence[tuple[int, int, int]],
) -> Anchor:
    if len(gold_values) != len(HEROES) or len(kda_values) != len(HEROES):
        raise ValueError(f"anchor {aid}: expected {len(HEROES)} values")
    return Anchor(
        aid=aid,
        time_s=float(time_s),
        tier=tier,
        source=source,
        note=note,
        gold={h: float(v) for h, v in zip(HEROES, gold_values)},
        kda={h: tuple(int(x) for x in v) for h, v in zip(HEROES, kda_values)},
    )


# Player order is HEROES: 钟馗 妲己 孙悟空 关羽 百里守约 公孙离 吕布 貂蝉 兰陵王 张良.
A_START = _anchor(
    "A000_model_start",
    0.0,
    "model_start",
    "docs/economy_rules.md 开局经济 300g (model assumption, not measured)",
    "All players assumed to start at 300 g; KDA 0/0/0.",
    [300, 300, 300, 300, 300, 300, 300, 300, 300, 300],
    [(0, 0, 0)] * 10,
)

A87 = _anchor(
    "S087_team_panel",
    87.0,
    "supplementary",
    "docs/replay_team_snapshot_20261102.md + screenshots/team_0127.png",
    "Team-panel UI read at 01:27; blue/red gold sums 4,302/3,830 match the top bar 4.3k/3.8k.",
    [648, 869, 977, 927, 881, 1000, 632, 702, 861, 635],
    [
        (0, 0, 0),
        (0, 0, 0),
        (0, 0, 0),
        (1, 0, 0),
        (0, 0, 0),
        (0, 0, 0),
        (0, 1, 0),
        (0, 0, 0),
        (0, 0, 0),
        (0, 0, 0),
    ],
)

A94 = _anchor(
    "P094_engine",
    94.0,
    "primary",
    "arena_t0_0134.bin + t0_ui.png (engine readback, docs 5.157.1)",
    "01:34 paused frame; engine gold/KDA 10/10 match the UI.",
    [679, 890, 1065, 1083, 902, 1021, 658, 723, 882, 661],
    [
        (0, 0, 0),
        (0, 0, 0),
        (0, 0, 1),
        (2, 0, 0),
        (0, 0, 0),
        (0, 0, 0),
        (0, 2, 0),
        (0, 0, 0),
        (0, 0, 0),
        (0, 0, 0),
    ],
)

A165 = _anchor(
    "P165_engine",
    165.0,
    "primary",
    "arena_t2_0245.bin + t2_ui.png (engine readback, docs 5.157.1)",
    "02:45 paused frame; engine gold 10/10 (关羽 2048 vs panel 2046, +2 passive growth).",
    [1235, 1521, 1786, 2048, 1746, 1630, 977, 1299, 1380, 992],
    [
        (0, 0, 1),
        (0, 0, 0),
        (1, 0, 2),
        (3, 0, 1),
        (1, 0, 0),
        (0, 1, 0),
        (0, 3, 0),
        (0, 0, 0),
        (0, 1, 0),
        (0, 0, 0),
    ],
)

A212 = _anchor(
    "S212_team_panel",
    212.0,
    "supplementary",
    "docs/replay_team_snapshot_20261102.md + screenshots/team_0332.png",
    "Team-panel UI read at 03:32; blue/red gold sums 10,409/8,428 match the top bar 10.4k/8.4k.",
    [1517, 1878, 2243, 2479, 2292, 2151, 1481, 1705, 1822, 1269],
    [
        (0, 0, 1),
        (0, 0, 0),
        (1, 0, 2),
        (3, 0, 1),
        (1, 0, 0),
        (0, 1, 0),
        (0, 3, 0),
        (0, 0, 0),
        (0, 1, 0),
        (0, 0, 0),
    ],
)

A300 = _anchor(
    "P300_ui",
    300.0,
    "primary",
    "arena_paused_0500.bin + scoreboard_0500.png (UI; docs 5.157)",
    "05:00 paused frame. UI gold used (关羽 3138; engine read 3135, -3 timing). "
    "妲己 assist 1 lives in +0xC0 (engine +0xBC reads 0).",
    [2297, 3169, 3383, 3138, 3461, 2698, 2785, 2405, 2800, 1891],
    [
        (0, 0, 3),
        (2, 0, 1),
        (3, 1, 3),
        (3, 1, 1),
        (1, 0, 1),
        (0, 2, 0),
        (1, 3, 1),
        (0, 1, 1),
        (1, 2, 1),
        (0, 1, 1),
    ],
)

A356 = _anchor(
    "S356_team_panel",
    356.0,
    "supplementary",
    "docs/replay_team_snapshot_20261102.md + screenshots/team_0556.png",
    "Team-panel UI read at 05:56; blue/red gold sums 18,258/14,864 match the top bar 18.3k/14.9k.",
    [2940, 3649, 3798, 3850, 4021, 3244, 3492, 2625, 3108, 2395],
    [
        (1, 0, 3),
        (2, 1, 1),
        (3, 1, 3),
        (4, 1, 1),
        (1, 0, 2),
        (0, 2, 1),
        (2, 3, 1),
        (0, 1, 2),
        (1, 3, 1),
        (0, 2, 2),
    ],
)

A541 = _anchor(
    "S541_team_panel",
    541.0,
    "supplementary",
    "docs/replay_team_snapshot_20261102.md + screenshots/team_0901.png",
    "Team-panel UI read at 09:01. Ten-player gold sum 28,277 vs top bar 28.1k: 177 residual unresolved.",
    [4700, 5695, 5864, 6358, 5660, 5204, 5008, 4664, 4764, 4450],
    [
        (2, 2, 5),
        (4, 1, 1),
        (3, 1, 3),
        (5, 1, 3),
        (1, 0, 3),
        (1, 3, 1),
        (2, 4, 1),
        (1, 1, 3),
        (1, 4, 2),
        (0, 3, 3),
    ],
)

A670 = _anchor(
    "S670_team_panel_unsaved",
    670.0,
    "supplementary_unsaved",
    "screen observation at 11:10 (no screenshot saved)",
    "Team-panel UI observed at 11:10; lower verification than the saved screenshots. "
    "Blue/red gold sums 38,481/28,765 match the top bar 38.5k/28.8k.",
    [6247, 7572, 7820, 8653, 8189, 6077, 5714, 5709, 5908, 5357],
    [
        (3, 3, 9),
        (5, 1, 6),
        (5, 1, 5),
        (7, 1, 7),
        (5, 0, 6),
        (1, 4, 2),
        (2, 6, 2),
        (2, 3, 3),
        (1, 6, 2),
        (0, 6, 4),
    ],
)

A693 = _anchor(
    "P693_settlement",
    693.0,
    "primary",
    "docs/replay_binary_format.md 5.155 settlement final stats",
    "11:33 settlement screen. Gold treated as the final displayed gold value; "
    "the docs call it cumulative earned while the team panel is current gold. "
    "Team sums 41,012/29,260 match the official 690 s team curve 41,021/29,266 within 9/6.",
    [6552, 8168, 8352, 9243, 8697, 6191, 5828, 5778, 5977, 5486],
    [
        (3, 3, 9),
        (6, 1, 7),
        (5, 1, 5),
        (8, 1, 7),
        (5, 0, 8),
        (1, 5, 2),
        (2, 7, 2),
        (2, 3, 3),
        (1, 6, 2),
        (0, 6, 4),
    ],
)

ALL_ANCHORS: tuple[Anchor, ...] = (
    A_START,
    A87,
    A94,
    A165,
    A212,
    A300,
    A356,
    A541,
    A670,
    A693,
)
PRIMARY_ANCHORS: tuple[Anchor, ...] = (A_START, A94, A165, A300, A693)

# Attributes-panel maximum HP read at 07:29 (docs 5.157.3 / task anchor list).
PANEL_MAX_HP = {
    "钟馗": 10054,
    "关羽": 8356,
    "妲己": 5201,
    "兰陵王": 5684,
    "张良": 7045,
    "百里守约": 4795,
    "公孙离": 4874,
    "孙悟空": 5450,
    "貂蝉": 5730,
    "吕布": 6336,
}

# Level context (levels_equipment/levels.csv); used only in hp_samples.csv notes.
LEVEL_0726 = {
    "钟馗": 7,
    "妲己": 9,
    "孙悟空": 10,
    "关羽": 9,
    "百里守约": 9,
    "公孙离": 8,
    "吕布": 9,
    "貂蝉": 9,
    "兰陵王": 9,
    "张良": 8,
}
LEVEL_0746 = {
    "钟馗": 8,
    "妲己": 9,
    "孙悟空": 11,
    "关羽": 9,
    "百里守约": 9,
    "公孙离": 9,
    "吕布": 9,
    "貂蝉": 9,
    "兰陵王": 10,
    "张良": 8,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def mmss(t: float) -> str:
    t = max(0.0, float(t))
    tenths = int(round(t * 10.0))
    minutes = tenths // 600
    rest = tenths % 600
    return f"{minutes:02d}:{rest // 10:02d}.{rest % 10}"


def mmss2(t: float) -> str:
    t = max(0.0, float(t))
    hundredths = int(round(t * 100.0))
    minutes = hundredths // 6000
    rest = hundredths % 6000
    return f"{minutes:02d}:{rest // 100:02d}.{rest % 100:02d}"


def pct(part: int, whole: int) -> float:
    return (100.0 * part / whole) if whole else 0.0


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Piecewise interpolation
# ---------------------------------------------------------------------------


def piecewise(
    xs: Sequence[float],
    ys: Sequence[float],
    t: float,
) -> tuple[float, int, int]:
    """Return (value, left_index, right_index) for a piecewise-linear curve.

    At an exact knot the knot value is returned verbatim, so anchor rows are
    reproduced with zero error.
    """
    if not xs:
        raise ValueError("empty series")
    if t <= xs[0]:
        return float(ys[0]), 0, 0
    if t >= xs[-1]:
        n = len(xs) - 1
        return float(ys[-1]), n, n

    i = bisect.bisect_left(xs, t)
    if i < len(xs) and abs(xs[i] - t) <= 1e-12:
        return float(ys[i]), i, i
    lo = i - 1
    hi = i
    span = xs[hi] - xs[lo]
    if span <= 0:
        return float(ys[hi]), hi, hi
    frac = (t - xs[lo]) / span
    return float(ys[lo] + frac * (ys[hi] - ys[lo])), lo, hi


def series_for(
    anchors: Sequence[Anchor],
    hero: str,
    field_name: str,
    component: int | None = None,
) -> tuple[list[float], list[float]]:
    if field_name != "gold" and component is None:
        raise ValueError(f"field {field_name!r} requires a KDA component index")
    xs: list[float] = []
    ys: list[float] = []
    for a in anchors:
        xs.append(a.time_s)
        if field_name == "gold":
            ys.append(float(a.gold[hero]))
        else:
            ys.append(float(a.kda[hero][component]))  # type: ignore[index]
    return xs, ys


# ---------------------------------------------------------------------------
# HP unit-object samples
# ---------------------------------------------------------------------------


@dataclass
class HPSample:
    player: str
    hero: str
    team: str
    tag: str
    file: str
    frame: int
    ms: int
    time_s: float
    clock_time_s: float
    current: int
    maximum: int
    ratio: float
    max_ref: int
    hp_abs: float
    clock_quality: str
    flags: list[str]
    note: str

    @property
    def source(self) -> str:
        return f"{self.file} +0x08/+0x10 @ {self.time_s:.3f}s"


def _i32(raw: bytes, off: int) -> int:
    return struct.unpack_from("<i", raw, off)[0]


def _build_hp_samples() -> tuple[list[HPSample], dict[str, float]]:
    specs: list[tuple[str, str, str]] = []
    for p in PLAYERS:
        specs.append((p.hero, "t0", f"unit_{p.hero}_t0.bin"))
        specs.append((p.hero, "t1", f"unit_{p.hero}_t1.bin"))
    # 钟馗 has one earlier extra snapshot; unit_zhongkui_t1.bin is byte-identical
    # to unit_钟馗_t0.bin, so only the earlier sample is added.
    specs.append(("钟馗", "t-1", "unit_zhongkui_t0.bin"))
    specs.append(("钟馗", "dup", "unit_zhongkui_t1.bin"))

    raw_samples: list[HPSample] = []
    seen: set[tuple[str, int, int, int, int]] = set()

    for hero, tag, filename in specs:
        path = LIVE_DIR / filename
        if not path.exists():
            continue
        raw = path.read_bytes()
        player = PLAYER_BY_HERO[hero]
        clock_off = 0x1524 if hero in {"关羽", "吕布"} else 0x1664
        frame = _i32(raw, clock_off)
        ms = _i32(raw, clock_off + 4)
        current = _i32(raw, 0x08)
        maximum = _i32(raw, 0x10)
        clock_t = ms / 1000.0
        key = (hero, frame, ms, current, maximum)
        duplicate = key in seen
        if duplicate:
            # Keep a note in the report by attaching a synthetic sample record
            # only if this is the first duplicate encountered.
            pass
        else:
            seen.add(key)
        ratio = (current / maximum) if maximum else float("nan")
        max_ref = PANEL_MAX_HP[hero]
        hp_abs = max_ref * ratio if math.isfinite(ratio) else float("nan")
        quality = "ok"
        flags: list[str] = []
        note_parts: list[str] = []
        if duplicate:
            flags.append("duplicate_content")
            note_parts.append("byte-identical to another snapshot; excluded from interpolation")
        if frame < 1000 or clock_t < 10.0:
            quality = "stale_clock"
            flags.append("stale_clock")
            note_parts.append(
                f"unit clock reads frame {frame} / {ms} ms ({clock_t:.3f}s), "
                "inconsistent with the 07:29/07:32 capture; nominal time used"
            )
        if ratio > 1.0 + 1e-9:
            flags.append("ratio_gt_1")
            note_parts.append(
                f"normalised current {current} > max {maximum} (ratio {ratio:.4f}); "
                "possible shield/overheal or scale mismatch"
            )
        if current == maximum:
            flags.append("current_eq_max")
        raw_samples.append(
            HPSample(
                player=player.name,
                hero=hero,
                team=player.team,
                tag=tag,
                file=filename,
                frame=frame,
                ms=ms,
                time_s=clock_t if quality == "ok" else float("nan"),
                clock_time_s=clock_t,
                current=current,
                maximum=maximum,
                ratio=ratio,
                max_ref=max_ref,
                hp_abs=hp_abs,
                clock_quality=quality,
                flags=flags,
                note="; ".join(note_parts),
            )
        )

    # Nominal capture times for stale-clock samples: median of the healthy
    # t0 / t1 clocks from the other players.
    healthy_t0 = [
        s.clock_time_s
        for s in raw_samples
        if s.tag == "t0" and s.clock_quality == "ok"
    ]
    healthy_t1 = [
        s.clock_time_s
        for s in raw_samples
        if s.tag == "t1" and s.clock_quality == "ok"
    ]
    nominal = {
        "t0": statistics.median(healthy_t0) if healthy_t0 else 449.2,
        "t1": statistics.median(healthy_t1) if healthy_t1 else 452.97,
        "t-1": min(healthy_t0) - 2.64 if healthy_t0 else 446.6,
    }
    for s in raw_samples:
        if s.clock_quality == "stale_clock":
            s.time_s = nominal.get(s.tag, nominal["t0"])
            s.note = (
                (s.note + "; " if s.note else "")
                + f"nominal time {s.time_s:.3f}s from the other players' capture clock"
            )

    samples = [s for s in raw_samples if "duplicate_content" not in s.flags]
    # Sort by hero then time.
    samples.sort(key=lambda s: (HEROES.index(s.hero), s.time_s))
    return samples, nominal


def _hp_series(samples: Sequence[HPSample], hero: str) -> list[HPSample]:
    return sorted([s for s in samples if s.hero == hero], key=lambda s: s.time_s)


def hp_at(
    ss: Sequence[HPSample], t: float
) -> tuple[float | None, HPSample | None, str]:
    """Return (ratio, exact_sample_or_None, confidence)."""
    if not ss:
        return None, None, CONF_UNKNOWN
    if t < ss[0].time_s - 1e-9 or t > ss[-1].time_s + 1e-9:
        return None, None, CONF_UNKNOWN
    for s in ss:
        if abs(s.time_s - t) <= 1e-9:
            return s.ratio, s, CONF_ANCHOR
    xs = [s.time_s for s in ss]
    ys = [s.ratio for s in ss]
    value, _lo, _hi = piecewise(xs, ys, t)
    return value, None, CONF_INTERP


def nearest_hp(ss: Sequence[HPSample], t: float) -> HPSample:
    return min(ss, key=lambda s: (abs(s.time_s - t), s.time_s))


# ---------------------------------------------------------------------------
# ABC event context
# ---------------------------------------------------------------------------


@dataclass
class EventContext:
    buy0: dict[str, dict[int, int]] = field(default_factory=dict)
    buy_tick: dict[str, dict[int, int]] = field(default_factory=dict)
    skills: dict[str, dict[int, int]] = field(default_factory=dict)
    attacks: dict[str, dict[int, int]] = field(default_factory=dict)
    totals: dict[str, Counter] = field(default_factory=dict)
    intervals: list[dict[str, Any]] = field(default_factory=list)
    flags: Counter = field(default_factory=Counter)
    past_end: dict[str, Counter] = field(default_factory=dict)
    available: bool = False
    path: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


def _map_abc_frame(frame: int) -> int | None:
    t = (frame - 1) / 15.0
    if t > END_S + 1e-9:
        return None
    return max(0, min(FRAME_COUNT, int(round(t * FPS))))


def load_events(path: Path, anchors: Sequence[Anchor]) -> EventContext:
    ctx = EventContext()
    if not path.exists():
        return ctx
    data = load_json(path)
    ctx.available = True
    ctx.path = str(path)
    ctx.meta = {
        "abc": data.get("abc"),
        "audit": data.get("audit"),
        "timeBase": data.get("timeBase"),
    }
    roster = data.get("roster", {})
    by_hero: dict[str, dict[str, Any]] = {}
    for _unit, rec in roster.items():
        hero = HERO_ALIASES.get(rec.get("hero", ""), rec.get("hero", ""))
        if hero in PLAYER_BY_HERO:
            by_hero[hero] = rec

    for hero, rec in by_hero.items():
        ctx.buy0[hero] = {}
        ctx.buy_tick[hero] = {}
        ctx.skills[hero] = {}
        ctx.attacks[hero] = {}
        ctx.totals[hero] = Counter()
        ctx.past_end[hero] = Counter()

        for row in rec.get("buys", []):
            if len(row) < 5:
                continue
            frame, equip_id, object_id, flag, price = row[:5]
            flag = int(flag)
            ctx.flags[flag] += 1
            mapped = _map_abc_frame(int(frame))
            bucket = ctx.buy0 if flag == 0 else ctx.buy_tick
            if mapped is None:
                if flag == 0:
                    ctx.past_end[hero]["buy0"] += 1
                else:
                    ctx.past_end[hero]["buy_tick"] += 1
                continue
            bucket[hero][mapped] = bucket[hero].get(mapped, 0) + 1
            ctx.totals[hero]["buy0" if flag == 0 else "buy_tick"] += 1
            if flag == 0:
                ctx.totals[hero]["buy0_price_sum"] += float(price)

        for row in rec.get("skills", []):
            if not row:
                continue
            mapped = _map_abc_frame(int(row[0]))
            if mapped is None:
                ctx.past_end[hero]["skill"] += 1
                continue
            ctx.skills[hero][mapped] = ctx.skills[hero].get(mapped, 0) + 1
            ctx.totals[hero]["skill"] += 1

        for row in rec.get("attacks", []):
            if not row:
                continue
            mapped = _map_abc_frame(int(row[0]))
            if mapped is None:
                ctx.past_end[hero]["attack"] += 1
                continue
            ctx.attacks[hero][mapped] = ctx.attacks[hero].get(mapped, 0) + 1
            ctx.totals[hero]["attack"] += 1

    # Per-interval event counts, using the union of all anchor times.
    times = sorted({a.time_s for a in anchors if a.is_measured})
    boundaries = [0.0] + times
    for p in PLAYERS:
        for lo, hi in zip(boundaries, boundaries[1:]):
            if hi <= lo:
                continue
            lo_f = int(round(lo * FPS))
            hi_f = int(round(hi * FPS))
            b0 = sum(v for f, v in ctx.buy0[p.hero].items() if lo_f <= f < hi_f)
            bt = sum(v for f, v in ctx.buy_tick[p.hero].items() if lo_f <= f < hi_f)
            sk = sum(v for f, v in ctx.skills[p.hero].items() if lo_f <= f < hi_f)
            at = sum(v for f, v in ctx.attacks[p.hero].items() if lo_f <= f < hi_f)
            ctx.intervals.append(
                {
                    "player": p.name,
                    "hero": p.hero,
                    "unit": p.unit,
                    "interval": f"{mmss(lo)}-{mmss(hi)}",
                    "start_s": round(lo, 3),
                    "end_s": round(hi, 3),
                    "buy_flag0": b0,
                    "buy_tick": bt,
                    "skills": sk,
                    "attacks": at,
                }
            )
    return ctx


# ---------------------------------------------------------------------------
# Series building
# ---------------------------------------------------------------------------


@dataclass
class SeriesResult:
    name: str
    anchors: tuple[Anchor, ...]
    rows: int = 0
    measured_rows: int = 0
    interpolated_rows: int = 0
    model_rows: int = 0
    gold_anchor_rows: int = 0
    kda_anchor_rows: int = 0
    hp_measured_rows: int = 0
    hp_interp_rows: int = 0
    hp_unknown_rows: int = 0
    monotonicity_violations: list[dict[str, Any]] = field(default_factory=list)
    anchor_exactness: list[dict[str, Any]] = field(default_factory=list)
    per_player: dict[str, dict[str, Any]] = field(default_factory=dict)


def _bracket(
    anchors: Sequence[Anchor], t: float
) -> tuple[Anchor, Anchor]:
    xs = [a.time_s for a in anchors]
    if t <= xs[0]:
        return anchors[0], anchors[0]
    if t >= xs[-1]:
        return anchors[-1], anchors[-1]
    i = bisect.bisect_left(xs, t)
    if i < len(anchors) and abs(xs[i] - t) <= 1e-12:
        return anchors[i], anchors[i]
    return anchors[i - 1], anchors[i]


def _quality(gap_s: float, is_anchor: bool, is_model: bool) -> str:
    if is_anchor:
        return "measured"
    if is_model:
        return "model"
    if gap_s <= 60:
        return "high"
    if gap_s <= 180:
        return "medium"
    return "low"


def build_series(
    name: str,
    anchors: Sequence[Anchor],
    out_csv: Path,
    out_jsonl: Path,
    hp_samples: Sequence[HPSample],
    events: EventContext,
    gzip_jsonl: bool = False,
) -> SeriesResult:
    result = SeriesResult(name=name, anchors=tuple(anchors))
    anchors = tuple(sorted(anchors, key=lambda a: a.time_s))
    anchor_by_frame: dict[int, Anchor] = {}
    for a in anchors:
        f = max(0, min(FRAME_COUNT, int(round(a.time_s * FPS))))
        # choose the closer anchor if two map to the same frame
        if f in anchor_by_frame and abs(anchor_by_frame[f].time_s - f / FPS) < abs(a.time_s - f / FPS):
            continue
        anchor_by_frame[f] = a

    hp_by_hero = {p.hero: _hp_series(hp_samples, p.hero) for p in PLAYERS}
    hp_sample_by_frame: dict[tuple[str, int], HPSample] = {}
    for hero, ss in hp_by_hero.items():
        for s in ss:
            f = max(0, min(FRAME_COUNT, int(round(s.time_s * FPS))))
            hp_sample_by_frame[(hero, f)] = s

    first_measured = min(a.time_s for a in anchors if a.is_measured)
    last_current_anchor = max(
        (a for a in anchors if a.is_measured and a.aid != A693.aid),
        key=lambda a: a.time_s,
    )

    fields = [
        "frame",
        "time_s",
        "time_mmss",
        "player",
        "hero",
        "camp",
        "team",
        "slot",
        "unit",
        "entity_id",
        "gold",
        "gold_measure",
        "gold_confidence",
        "gold_quality",
        "gold_anchor_id",
        "gold_anchor_tier",
        "gold_gap_s",
        "gold_source",
        "kills",
        "deaths",
        "assists",
        "kda_confidence",
        "kda_quality",
        "kda_anchor_id",
        "kda_anchor_tier",
        "kda_gap_s",
        "kda_source",
        "hp_ratio",
        "hp_abs",
        "hp_max_ref",
        "hp_confidence",
        "hp_class",
        "hp_source",
        "hp_note",
        "hp_nearest_ratio",
        "hp_nearest_abs",
        "hp_nearest_time_s",
        "hp_nearest_age_s",
        "hp_nearest_source",
        "abc_buy_flag0",
        "abc_buy_tick",
        "abc_skills",
        "abc_attacks",
        "row_class",
        "confidence",
        "source",
        "measured",
        "measured_fields",
        "notes",
    ]

    csv_fh = out_csv.open("w", encoding="utf-8", newline="")
    if gzip_jsonl:
        jsonl_fh = gzip.open(out_jsonl, "wt", encoding="utf-8")
    else:
        jsonl_fh = out_jsonl.open("w", encoding="utf-8")
    writer = csv.DictWriter(csv_fh, fieldnames=fields, lineterminator="\n")
    writer.writeheader()

    violations = result.monotonicity_violations

    try:
        for p in PLAYERS:
            gp = series_for(anchors, p.hero, "gold")
            kp = series_for(anchors, p.hero, "kills", 0)
            dp = series_for(anchors, p.hero, "deaths", 1)
            ap = series_for(anchors, p.hero, "assists", 2)
            ss = hp_by_hero[p.hero]
            player_counts = Counter()
            last_gold = last_k = last_d = last_a = None

            for frame in range(FRAME_COUNT + 1):
                t = END_S if frame == FRAME_COUNT else frame / FPS
                anchor = anchor_by_frame.get(frame)
                anchor_measured = anchor is not None and anchor.is_measured
                left, right = _bracket(anchors, t)
                is_anchor = anchor is not None
                is_model_start = anchor is not None and not anchor.is_measured
                is_model = is_model_start or (
                    (not is_anchor) and (t < first_measured - 1e-9)
                )
                gap = 0.0 if is_anchor or left.aid == right.aid else (right.time_s - left.time_s)

                if anchor is not None:
                    gold = float(anchor.gold[p.hero])
                    kills, deaths, assists = (float(x) for x in anchor.kda[p.hero])
                    if anchor_measured:
                        gold_conf = kda_conf = CONF_ANCHOR
                    else:
                        gold_conf = kda_conf = CONF_MODEL
                else:
                    gold = piecewise(*gp, t)[0]
                    kills = piecewise(*kp, t)[0]
                    deaths = piecewise(*dp, t)[0]
                    assists = piecewise(*ap, t)[0]
                    gold_conf = kda_conf = CONF_MODEL if is_model else CONF_INTERP

                gold_quality = _quality(gap, anchor_measured, is_model)
                kda_quality = gold_quality

                if anchor is not None:
                    gold_aid = anchor.aid
                    gold_tier = anchor.tier
                    gold_source = f"{'anchor' if anchor_measured else 'model'}:{anchor.aid}"
                    kda_aid = anchor.aid
                    kda_tier = anchor.tier
                    kda_source = f"{'anchor' if anchor_measured else 'model'}:{anchor.aid}"
                else:
                    gold_aid = kda_aid = ""
                    gold_tier = kda_tier = ""
                    gold_source = f"seg:{left.aid}->{right.aid}"
                    kda_source = f"seg:{left.aid}->{right.aid}"

                # HP
                hp_ratio, hp_exact, hp_conf = hp_at(ss, t)
                hp_sample = hp_sample_by_frame.get((p.hero, frame))
                if hp_sample is not None:
                    hp_ratio = hp_sample.ratio
                    hp_conf = CONF_ANCHOR
                    hp_class = "measured"
                    hp_abs = hp_sample.hp_abs
                    hp_source = f"unit:{hp_sample.file}@{hp_sample.time_s:.3f}"
                    hp_note = hp_sample.note
                elif hp_ratio is not None:
                    hp_class = "interpolated"
                    hp_abs = PANEL_MAX_HP[p.hero] * hp_ratio
                    hp_source = f"interp:{ss[0].file}->{ss[-1].file}"
                    hp_note = "abs=max0729*ratio"
                else:
                    hp_class = "unknown"
                    hp_abs = None
                    hp_source = "none"
                    hp_note = ""

                if hp_sample is not None and hp_sample.clock_quality != "ok":
                    hp_note = (hp_note + "; " if hp_note else "") + "stale unit clock"
                if hp_ratio is not None and hp_ratio > 1.0 + 1e-9:
                    hp_note = (
                        (hp_note + "; " if hp_note else "")
                        + "ratio > 1 (normalised current exceeds max)"
                    )

                near = nearest_hp(ss, t) if ss else None
                if near is not None:
                    near_ratio = near.ratio
                    near_abs = near.hp_abs
                    near_time = near.time_s
                    near_age = abs(t - near.time_s)
                    near_source = f"{near.file}@{near.time_s:.3f}"
                else:
                    near_ratio = None
                    near_abs = None
                    near_time = None
                    near_age = None
                    near_source = ""

                buy0 = events.buy0.get(p.hero, {}).get(frame, 0) if events.available else 0
                buy_tick = events.buy_tick.get(p.hero, {}).get(frame, 0) if events.available else 0
                skills = events.skills.get(p.hero, {}).get(frame, 0) if events.available else 0
                attacks = events.attacks.get(p.hero, {}).get(frame, 0) if events.available else 0

                if anchor_measured:
                    row_class = "measured"
                elif is_model:
                    row_class = "model"
                else:
                    row_class = "interpolated"

                measured_fields: list[str] = []
                if anchor_measured:
                    measured_fields.extend(["gold", "kills", "deaths", "assists"])
                if hp_sample is not None:
                    measured_fields.extend(["hp_ratio", "hp_abs"])
                measured = 1 if measured_fields else 0

                confidence = "anchor" if row_class == "measured" else row_class

                notes: list[str] = []
                if is_anchor:
                    notes.append(anchor.note)
                else:
                    if gap > 180:
                        notes.append("long_gap")
                    if right.aid == A693.aid and left.aid != A693.aid:
                        notes.append("settlement_endpoint")
                if buy0:
                    notes.append("manual_buy")
                if buy_tick:
                    notes.append("tick_buy")
                if hp_sample is not None and hp_note:
                    notes.append(hp_note)

                source = f"gold:{gold_source}; kda:{kda_source}; hp:{hp_source}"

                if t >= A693.time_s - 1e-9:
                    gold_measure = "settlement_final"
                elif anchor is not None and anchor.aid == last_current_anchor.aid:
                    gold_measure = "ui_current"
                elif t > last_current_anchor.time_s + 1e-9:
                    gold_measure = "bridge_ui_current_to_settlement"
                else:
                    gold_measure = "ui_current"

                row = {
                    "frame": frame,
                    "time_s": round(t, 4),
                    "time_mmss": mmss(t),
                    "player": p.name,
                    "hero": p.hero,
                    "camp": p.camp,
                    "team": p.team,
                    "slot": p.slot,
                    "unit": p.unit,
                    "entity_id": p.entity,
                    "gold": round(gold, 2),
                    "gold_measure": gold_measure,
                    "gold_confidence": gold_conf,
                    "gold_quality": gold_quality,
                    "gold_anchor_id": gold_aid,
                    "gold_anchor_tier": gold_tier,
                    "gold_gap_s": round(gap, 2),
                    "gold_source": gold_source,
                    "kills": round(kills, 3),
                    "deaths": round(deaths, 3),
                    "assists": round(assists, 3),
                    "kda_confidence": kda_conf,
                    "kda_quality": kda_quality,
                    "kda_anchor_id": kda_aid,
                    "kda_anchor_tier": kda_tier,
                    "kda_gap_s": round(gap, 2),
                    "kda_source": kda_source,
                    "hp_ratio": None if hp_ratio is None else round(hp_ratio, 6),
                    "hp_abs": None if hp_abs is None else round(hp_abs, 1),
                    "hp_max_ref": PANEL_MAX_HP[p.hero],
                    "hp_confidence": hp_conf,
                    "hp_class": hp_class,
                    "hp_source": hp_source,
                    "hp_note": hp_note,
                    "hp_nearest_ratio": None if near_ratio is None else round(near_ratio, 6),
                    "hp_nearest_abs": None if near_abs is None else round(near_abs, 1),
                    "hp_nearest_time_s": None if near_time is None else round(near_time, 3),
                    "hp_nearest_age_s": None if near_age is None else round(near_age, 3),
                    "hp_nearest_source": near_source,
                    "abc_buy_flag0": buy0,
                    "abc_buy_tick": buy_tick,
                    "abc_skills": skills,
                    "abc_attacks": attacks,
                    "row_class": row_class,
                    "confidence": confidence,
                    "source": source,
                    "measured": measured,
                    "measured_fields": ";".join(measured_fields),
                    "notes": "; ".join(n for n in notes if n),
                }
                csv_row = dict(row)
                for key, digits in (
                    ("time_s", 4),
                    ("gold", 2),
                    ("gold_gap_s", 2),
                    ("kills", 3),
                    ("deaths", 3),
                    ("assists", 3),
                    ("kda_gap_s", 2),
                    ("hp_ratio", 6),
                    ("hp_abs", 1),
                    ("hp_nearest_ratio", 6),
                    ("hp_nearest_abs", 1),
                    ("hp_nearest_time_s", 3),
                    ("hp_nearest_age_s", 3),
                ):
                    value = row[key]
                    csv_row[key] = "" if value is None else f"{value:.{digits}f}"

                writer.writerow(csv_row)
                jsonl_fh.write(json.dumps(row, ensure_ascii=False) + "\n")

                # counts
                result.rows += 1
                player_counts["rows"] += 1
                if row_class == "measured":
                    result.measured_rows += 1
                    player_counts["measured"] += 1
                elif row_class == "interpolated":
                    result.interpolated_rows += 1
                    player_counts["interpolated"] += 1
                else:
                    result.model_rows += 1
                    player_counts["model"] += 1
                if is_anchor:
                    result.gold_anchor_rows += 1
                    result.kda_anchor_rows += 1
                    player_counts["gold_anchor"] += 1
                if hp_class == "measured":
                    result.hp_measured_rows += 1
                    player_counts["hp_measured"] += 1
                elif hp_class == "interpolated":
                    result.hp_interp_rows += 1
                    player_counts["hp_interpolated"] += 1
                else:
                    result.hp_unknown_rows += 1
                    player_counts["hp_unknown"] += 1

                # exactness at measured anchor row
                if anchor_measured:
                    result.anchor_exactness.append(
                        {
                            "series": name,
                            "anchor": anchor.aid,
                            "time_s": anchor.time_s,
                            "player": p.name,
                            "hero": p.hero,
                            "gold_row": gold,
                            "gold_anchor": anchor.gold[p.hero],
                            "gold_error": gold - anchor.gold[p.hero],
                            "kills_row": kills,
                            "deaths_row": deaths,
                            "assists_row": assists,
                            "kda_error": max(
                                abs(kills - anchor.kda[p.hero][0]),
                                abs(deaths - anchor.kda[p.hero][1]),
                                abs(assists - anchor.kda[p.hero][2]),
                            ),
                        }
                    )
                if hp_sample is not None:
                    result.anchor_exactness.append(
                        {
                            "series": name,
                            "anchor": f"HP:{p.hero}:{hp_sample.tag}",
                            "time_s": hp_sample.time_s,
                            "player": p.name,
                            "hero": p.hero,
                            "gold_row": None,
                            "gold_anchor": None,
                            "gold_error": 0.0,
                            "kills_row": None,
                            "deaths_row": None,
                            "assists_row": None,
                            "kda_error": 0.0,
                            "hp_ratio_row": hp_ratio,
                            "hp_ratio_anchor": hp_sample.ratio,
                            "hp_ratio_error": (
                                None
                                if hp_ratio is None
                                else abs(hp_ratio - hp_sample.ratio)
                            ),
                        }
                    )

                # monotonicity (gold and KDA)
                if last_gold is not None:
                    for field_name, prev_v, cur_v in (
                        ("gold", last_gold, gold),
                        ("kills", last_k, kills),
                        ("deaths", last_d, deaths),
                        ("assists", last_a, assists),
                    ):
                        delta = cur_v - prev_v
                        if delta < -1e-9:
                            if len(violations) < 200:
                                violations.append(
                                    {
                                        "series": name,
                                        "player": p.name,
                                        "hero": p.hero,
                                        "frame": frame,
                                        "time_s": round(t, 4),
                                        "field": field_name,
                                        "previous": prev_v,
                                        "current": cur_v,
                                        "delta": delta,
                                    }
                                )
                last_gold, last_k, last_d, last_a = gold, kills, deaths, assists

            result.per_player[p.hero] = dict(player_counts)
    finally:
        csv_fh.close()
        jsonl_fh.close()

    return result


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def anchor_exactness_summary(checks: Sequence[dict[str, Any]]) -> dict[str, Any]:
    gold_checks = [c for c in checks if c.get("gold_anchor") is not None]
    hp_checks = [c for c in checks if c.get("hp_ratio_anchor") is not None]
    gold_errors = [abs(c["gold_error"]) for c in gold_checks]
    kda_errors = [abs(c["kda_error"]) for c in gold_checks]
    hp_errors = [abs(c["hp_ratio_error"]) for c in hp_checks if c.get("hp_ratio_error") is not None]
    return {
        "gold_checks": len(gold_checks),
        "gold_max_abs_error": max(gold_errors) if gold_errors else 0.0,
        "gold_failures": [c for c in gold_checks if abs(c["gold_error"]) > 1e-9][:20],
        "kda_checks": len(gold_checks),
        "kda_max_abs_error": max(kda_errors) if kda_errors else 0.0,
        "kda_failures": [c for c in gold_checks if abs(c["kda_error"]) > 1e-9][:20],
        "hp_checks": len(hp_checks),
        "hp_ratio_max_abs_error": max(hp_errors) if hp_errors else 0.0,
        "hp_failures": [c for c in hp_checks if (c.get("hp_ratio_error") or 0) > 1e-9][:20],
    }


def monotonicity_summary(violations: Sequence[dict[str, Any]]) -> dict[str, Any]:
    by_field: dict[str, int] = defaultdict(int)
    for v in violations:
        by_field[v["field"]] += 1
    return {
        "violations": len(violations),
        "by_field": dict(by_field),
        "max_negative_delta": min((v["delta"] for v in violations), default=0.0),
        "details": list(violations[:50]),
    }


def anchor_monotonicity(anchors: Sequence[Anchor]) -> dict[str, Any]:
    ordered = sorted(anchors, key=lambda a: a.time_s)
    problems: list[dict[str, Any]] = []
    for hero in HEROES:
        prev = None
        for a in ordered:
            cur = (a.gold[hero],) + a.kda[hero]
            if prev is not None:
                names = ("gold", "kills", "deaths", "assists")
                for idx, name in enumerate(names):
                    if cur[idx] < prev[1][idx] - 1e-9:
                        problems.append(
                            {
                                "hero": hero,
                                "from": prev[0].aid,
                                "to": a.aid,
                                "field": name,
                                "previous": prev[1][idx],
                                "current": cur[idx],
                            }
                        )
            prev = (a, cur)
    return {"violations": len(problems), "details": problems}


def team_reconciliation(anchors: Sequence[Anchor]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for a in sorted(anchors, key=lambda x: x.time_s):
        blue_kills = sum(a.kda[p.hero][0] for p in PLAYERS if p.camp == 1)
        blue_deaths = sum(a.kda[p.hero][1] for p in PLAYERS if p.camp == 1)
        blue_assists = sum(a.kda[p.hero][2] for p in PLAYERS if p.camp == 1)
        red_kills = sum(a.kda[p.hero][0] for p in PLAYERS if p.camp == 2)
        red_deaths = sum(a.kda[p.hero][1] for p in PLAYERS if p.camp == 2)
        red_assists = sum(a.kda[p.hero][2] for p in PLAYERS if p.camp == 2)
        blue_gold = sum(a.gold[p.hero] for p in PLAYERS if p.camp == 1)
        red_gold = sum(a.gold[p.hero] for p in PLAYERS if p.camp == 2)
        out.append(
            {
                "anchor": a.aid,
                "time_s": a.time_s,
                "tier": a.tier,
                "blue_kills": blue_kills,
                "red_deaths": red_deaths,
                "blue_kills_minus_red_deaths": blue_kills - red_deaths,
                "red_kills": red_kills,
                "blue_deaths": blue_deaths,
                "red_kills_minus_blue_deaths": red_kills - blue_deaths,
                "blue_assists": blue_assists,
                "red_assists": red_assists,
                "blue_gold_sum": blue_gold,
                "red_gold_sum": red_gold,
            }
        )
    return out


def primary_only_residuals(
    supplementary: Sequence[Anchor],
    primary: Sequence[Anchor],
) -> list[dict[str, Any]]:
    """Compare primary-only interpolation with independently measured UI samples."""
    out: list[dict[str, Any]] = []
    for a in supplementary:
        per_player: list[dict[str, Any]] = []
        gold_errors: list[float] = []
        kda_errors: list[float] = []
        for p in PLAYERS:
            gx, gy = series_for(primary, p.hero, "gold")
            gold_est = piecewise(gx, gy, a.time_s)[0]
            kx, ky = series_for(primary, p.hero, "kills", 0)
            dx, dy = series_for(primary, p.hero, "deaths", 1)
            ax, ay = series_for(primary, p.hero, "assists", 2)
            k_est = piecewise(kx, ky, a.time_s)[0]
            d_est = piecewise(dx, dy, a.time_s)[0]
            a_est = piecewise(ax, ay, a.time_s)[0]
            gold_err = gold_est - a.gold[p.hero]
            kda_err = max(
                abs(k_est - a.kda[p.hero][0]),
                abs(d_est - a.kda[p.hero][1]),
                abs(a_est - a.kda[p.hero][2]),
            )
            gold_errors.append(gold_err)
            kda_errors.append(kda_err)
            per_player.append(
                {
                    "player": p.name,
                    "hero": p.hero,
                    "gold_measured": a.gold[p.hero],
                    "gold_primary_only": round(gold_est, 3),
                    "gold_error": round(gold_err, 3),
                    "kda_measured": list(a.kda[p.hero]),
                    "kda_primary_only": [round(k_est, 3), round(d_est, 3), round(a_est, 3)],
                    "kda_max_error": round(kda_err, 3),
                }
            )
        worst_gold = max(per_player, key=lambda r: abs(r["gold_error"]))
        worst_kda = max(per_player, key=lambda r: r["kda_max_error"])
        out.append(
            {
                "anchor": a.aid,
                "time_s": a.time_s,
                "source": a.source,
                "tier": a.tier,
                "max_abs_gold_error": round(max(abs(x) for x in gold_errors), 3),
                "mean_abs_gold_error": round(sum(abs(x) for x in gold_errors) / len(gold_errors), 3),
                "max_abs_kda_error": round(max(kda_errors), 3),
                "worst_gold_player": worst_gold["player"],
                "worst_gold_error": worst_gold["gold_error"],
                "worst_kda_player": worst_kda["player"],
                "worst_kda_error": worst_kda["kda_max_error"],
                "per_player": per_player,
            }
        )
    return out


def leave_one_out(
    anchors: Sequence[Anchor],
) -> list[dict[str, Any]]:
    ordered = sorted(anchors, key=lambda a: a.time_s)
    out: list[dict[str, Any]] = []
    for i, target in enumerate(ordered):
        if len(ordered) <= 2:
            continue
        remaining = ordered[:i] + ordered[i + 1 :]
        gold_errors: list[dict[str, Any]] = []
        kda_errors: list[dict[str, Any]] = []
        for p in PLAYERS:
            gx, gy = series_for(remaining, p.hero, "gold")
            gold_est = piecewise(gx, gy, target.time_s)[0]
            gold_err = gold_est - target.gold[p.hero]
            gold_errors.append(
                {
                    "player": p.name,
                    "measured": target.gold[p.hero],
                    "loo": round(gold_est, 3),
                    "error": round(gold_err, 3),
                }
            )
            errs = []
            for comp, name in ((0, "kills"), (1, "deaths"), (2, "assists")):
                xs, ys = series_for(remaining, p.hero, name, comp)
                est = piecewise(xs, ys, target.time_s)[0]
                errs.append((name, target.kda[p.hero][comp], round(est, 3), round(est - target.kda[p.hero][comp], 3)))
            max_err = max(abs(e[3]) for e in errs)
            kda_errors.append(
                {
                    "player": p.name,
                    "kda_measured": list(target.kda[p.hero]),
                    "kda_loo": [e[2] for e in errs],
                    "max_error": round(max_err, 3),
                }
            )
        worst_gold = max(gold_errors, key=lambda r: abs(r["error"]))
        worst_kda = max(kda_errors, key=lambda r: r["max_error"])
        if i == 0:
            kind = "extrapolation_before_first"
        elif i == len(ordered) - 1:
            kind = "extrapolation_after_last"
        else:
            kind = "interpolation"
        out.append(
            {
                "anchor": target.aid,
                "time_s": target.time_s,
                "tier": target.tier,
                "kind": kind,
                "max_abs_gold_error": worst_gold["error"] if False else round(
                    max(abs(r["error"]) for r in gold_errors), 3
                ),
                "mean_abs_gold_error": round(
                    sum(abs(r["error"]) for r in gold_errors) / len(gold_errors), 3
                ),
                "max_abs_kda_error": worst_kda["max_error"],
                "worst_gold_player": worst_gold["player"],
                "worst_gold_error": worst_gold["error"],
                "worst_kda_player": worst_kda["player"],
                "worst_kda_error": worst_kda["max_error"],
                "gold_errors": gold_errors,
                "kda_errors": kda_errors,
            }
        )
    return out


def official_team_gold_residuals(
    anchors: Sequence[Anchor],
    path: Path,
) -> dict[str, Any]:
    if not path.exists():
        return {"available": False}
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for rec in reader:
            try:
                t = float(rec["t_approx_sec"])
                blue = float(rec["blue"])
                red = float(rec["red"])
            except (KeyError, TypeError, ValueError):
                continue
            blue_sum = 0.0
            red_sum = 0.0
            for p in PLAYERS:
                xs, ys = series_for(anchors, p.hero, "gold")
                g = piecewise(xs, ys, t)[0]
                if p.camp == 1:
                    blue_sum += g
                else:
                    red_sum += g
            rows.append(
                {
                    "time_s": t,
                    "official_blue": blue,
                    "model_blue": round(blue_sum, 3),
                    "blue_error": round(blue_sum - blue, 3),
                    "official_red": red,
                    "model_red": round(red_sum, 3),
                    "red_error": round(red_sum - red, 3),
                }
            )
    blue_errors = [abs(r["blue_error"]) for r in rows]
    red_errors = [abs(r["red_error"]) for r in rows]
    return {
        "available": True,
        "path": str(path),
        "rows": rows,
        "blue_mean_abs_error": round(sum(blue_errors) / len(blue_errors), 3) if blue_errors else 0.0,
        "blue_max_abs_error": round(max(blue_errors), 3) if blue_errors else 0.0,
        "red_mean_abs_error": round(sum(red_errors) / len(red_errors), 3) if red_errors else 0.0,
        "red_max_abs_error": round(max(red_errors), 3) if red_errors else 0.0,
        "note": (
            "Official team gold is an independent 30-second curve. Residuals are "
            "team-aggregate differences, not per-player errors; they include timing, "
            "rounding and possible definition differences."
        ),
    }


def segment_gaps(anchors: Sequence[Anchor]) -> list[dict[str, Any]]:
    ordered = sorted(anchors, key=lambda a: a.time_s)
    out: list[dict[str, Any]] = []
    for left, right in zip(ordered, ordered[1:]):
        out.append(
            {
                "from": left.aid,
                "from_time_s": left.time_s,
                "to": right.aid,
                "to_time_s": right.time_s,
                "gap_s": round(right.time_s - left.time_s, 3),
                "from_tier": left.tier,
                "to_tier": right.tier,
            }
        )
    return sorted(out, key=lambda r: -r["gap_s"])


def hp_unknown_intervals(
    samples: Sequence[HPSample],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in PLAYERS:
        ss = _hp_series(samples, p.hero)
        if not ss:
            out.append(
                {
                    "player": p.name,
                    "hero": p.hero,
                    "from_s": 0.0,
                    "to_s": END_S,
                    "duration_s": END_S,
                    "reason": "no HP samples",
                }
            )
            continue
        if ss[0].time_s > 0:
            out.append(
                {
                    "player": p.name,
                    "hero": p.hero,
                    "from_s": 0.0,
                    "to_s": round(ss[0].time_s, 3),
                    "duration_s": round(ss[0].time_s, 3),
                    "reason": "before first HP sample",
                }
            )
        if ss[-1].time_s < END_S:
            out.append(
                {
                    "player": p.name,
                    "hero": p.hero,
                    "from_s": round(ss[-1].time_s, 3),
                    "to_s": END_S,
                    "duration_s": round(END_S - ss[-1].time_s, 3),
                    "reason": "after last HP sample",
                }
            )
    return sorted(out, key=lambda r: -r["duration_s"])


# ---------------------------------------------------------------------------
# Report writing
# ---------------------------------------------------------------------------


def write_anchors_csv(path: Path, anchors: Sequence[Anchor]) -> None:
    fields = [
        "anchor_id",
        "time_s",
        "time_mmss",
        "tier",
        "used_in_primary",
        "used_in_supplementary",
        "source",
        "note",
        "player",
        "hero",
        "team",
        "gold",
        "kills",
        "deaths",
        "assists",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for a in sorted(anchors, key=lambda x: x.time_s):
            for p in PLAYERS:
                writer.writerow(
                    {
                        "anchor_id": a.aid,
                        "time_s": f"{a.time_s:.3f}",
                        "time_mmss": mmss(a.time_s),
                        "tier": a.tier,
                        "used_in_primary": 1 if a in PRIMARY_ANCHORS else 0,
                        "used_in_supplementary": 1,
                        "source": a.source,
                        "note": a.note,
                        "player": p.name,
                        "hero": p.hero,
                        "team": p.team,
                        "gold": f"{a.gold[p.hero]:.0f}",
                        "kills": a.kda[p.hero][0],
                        "deaths": a.kda[p.hero][1],
                        "assists": a.kda[p.hero][2],
                    }
                )


def write_hp_samples_csv(path: Path, samples: Sequence[HPSample]) -> None:
    fields = [
        "player",
        "hero",
        "team",
        "tag",
        "file",
        "unit_frame",
        "unit_ms",
        "time_s",
        "time_mmss",
        "clock_time_s",
        "clock_quality",
        "hp_current_norm",
        "hp_max_norm",
        "hp_ratio",
        "hp_max_ref_0729",
        "hp_abs",
        "level_0726",
        "level_0746",
        "flags",
        "note",
        "source",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for s in sorted(samples, key=lambda x: (HEROES.index(x.hero), x.time_s)):
            writer.writerow(
                {
                    "player": s.player,
                    "hero": s.hero,
                    "team": s.team,
                    "tag": s.tag,
                    "file": s.file,
                    "unit_frame": s.frame,
                    "unit_ms": s.ms,
                    "time_s": f"{s.time_s:.3f}",
                    "time_mmss": mmss2(s.time_s),
                    "clock_time_s": f"{s.clock_time_s:.3f}",
                    "clock_quality": s.clock_quality,
                    "hp_current_norm": s.current,
                    "hp_max_norm": s.maximum,
                    "hp_ratio": f"{s.ratio:.6f}",
                    "hp_max_ref_0729": s.max_ref,
                    "hp_abs": f"{s.hp_abs:.1f}",
                    "level_0726": LEVEL_0726.get(s.hero, ""),
                    "level_0746": LEVEL_0746.get(s.hero, ""),
                    "flags": ";".join(s.flags),
                    "note": s.note,
                    "source": s.source,
                }
            )


def write_events_csv(path: Path, events: EventContext) -> None:
    fields = [
        "player",
        "hero",
        "unit",
        "interval",
        "start_s",
        "end_s",
        "buy_flag0",
        "buy_tick",
        "skills",
        "attacks",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for rec in events.intervals:
            writer.writerow(rec)
        for p in PLAYERS:
            totals = events.totals.get(p.hero, Counter())
            writer.writerow(
                {
                    "player": p.name,
                    "hero": p.hero,
                    "unit": p.unit,
                    "interval": "TOTAL_0_693",
                    "start_s": 0.0,
                    "end_s": END_S,
                    "buy_flag0": totals.get("buy0", 0),
                    "buy_tick": totals.get("buy_tick", 0),
                    "skills": totals.get("skill", 0),
                    "attacks": totals.get("attack", 0),
                }
            )
            past = events.past_end.get(p.hero, Counter())
            if past:
                writer.writerow(
                    {
                        "player": p.name,
                        "hero": p.hero,
                        "unit": p.unit,
                        "interval": "PAST_END",
                        "start_s": END_S,
                        "end_s": "",
                        "buy_flag0": past.get("buy0", 0),
                        "buy_tick": past.get("buy_tick", 0),
                        "skills": past.get("skill", 0),
                        "attacks": past.get("attack", 0),
                    }
                )


def write_validation_markdown(
    path: Path,
    report: dict[str, Any],
) -> None:
    lines: list[str] = []
    add = lines.append

    add("# Interpolated state — validation report")
    add("")
    add(f"Generated: {report['generated_at']}")
    add("")
    add("## 1. Time base and coverage")
    add("")
    tb = report["time_base"]
    add(
        f"- FPS: {tb['fps']} · end: {tb['end_s']} s ({tb['end_mmss']}) · "
        f"frames per player per series: {tb['frames_per_player']} · "
        f"rows per series: {tb['rows_per_series']} · combined rows: {tb['total_rows']}"
    )
    for sname, cov in report["coverage"].items():
        add(
            f"- `{sname}`: measured rows {cov['measured_rows']} "
            f"({cov['measured_pct']:.2f}%), interpolated {cov['interpolated_rows']} "
            f"({cov['interpolated_pct']:.2f}%), model {cov['model_rows']} "
            f"({cov['model_pct']:.2f}%)"
        )
        add(
            f"  - gold/KDA non-null: {cov['gold_non_null']}/{cov['rows']} "
            f"({cov['gold_non_null_pct']:.2f}%)"
        )
        add(
            f"  - HP measured {cov['hp_measured_rows']} rows, interpolated "
            f"{cov['hp_interpolated_rows']} rows, unknown {cov['hp_unknown_rows']} "
            f"({cov['hp_unknown_pct']:.2f}%)"
        )
    add("")
    add("## 2. Anchor exactness")
    add("")
    for sname, ex in report["exactness"].items():
        add(
            f"- `{sname}`: gold checks {ex['gold_checks']}, max |error| "
            f"{ex['gold_max_abs_error']:.6g}; KDA checks {ex['kda_checks']}, max "
            f"|error| {ex['kda_max_abs_error']:.6g}; HP checks {ex['hp_checks']}, "
            f"max ratio |error| {ex['hp_ratio_max_abs_error']:.6g}."
        )
    add("")
    add("## 3. Monotonicity")
    add("")
    for sname, mono in report["monotonicity"].items():
        add(
            f"- `{sname}`: {mono['violations']} violations "
            f"(by field: {mono['by_field'] or 'none'})"
        )
    add("")
    add("## 4. Team reconciliation at anchors")
    add("")
    add("| anchor | t | tier | blue K | red D | Δ | red K | blue D | Δ | blue gold | red gold |")
    add("|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in report["team_reconciliation"]:
        add(
            f"| {r['anchor']} | {mmss(r['time_s'])} | {r['tier']} | "
            f"{r['blue_kills']} | {r['red_deaths']} | "
            f"{r['blue_kills_minus_red_deaths']:+d} | {r['red_kills']} | "
            f"{r['blue_deaths']} | {r['red_kills_minus_blue_deaths']:+d} | "
            f"{r['blue_gold_sum']:.0f} | {r['red_gold_sum']:.0f} |"
        )
    add("")
    add("All listed checkpoints close exactly (Δ=0) for both kill/death pairs; "
        "settlement is 27/27 and 6/6. A non-zero Δ in another dataset would be "
        "an attribution/timing mismatch, not a monotonicity violation.")
    add("")
    add("## 5. Primary-only interpolation vs supplementary UI samples")
    add("")
    add("These are the errors the strict primary-anchor series makes at the "
        "independently measured team-panel times.")
    add("")
    add("| supplementary anchor | t | max abs gold error | worst player | max abs KDA error | worst player |")
    add("|---|---:|---:|---|---:|---|")
    for r in report["primary_only_residuals"]:
        add(
            f"| {r['anchor']} | {mmss(r['time_s'])} | {r['max_abs_gold_error']:.1f} | "
            f"{r['worst_gold_player']} ({r['worst_gold_error']:+.1f}) | "
            f"{r['max_abs_kda_error']:.3f} | "
            f"{r['worst_kda_player']} ({r['worst_kda_error']:+.3f}) |"
        )
    add("")
    add("## 6. Leave-one-out interpolation error")
    add("")
    for sname, rows in report["leave_one_out"].items():
        add(f"### {sname}")
        add("")
        add("| removed anchor | t | kind | max abs gold error | worst player | max abs KDA error |")
        add("|---|---:|---|---:|---|---:|")
        for r in rows:
            add(
                f"| {r['anchor']} | {mmss(r['time_s'])} | {r.get('kind', 'interpolation')} | "
                f"{r['max_abs_gold_error']:.1f} | "
                f"{r['worst_gold_player']} | {r['max_abs_kda_error']:.3f} |"
            )
        add("")
    add("Endpoint leave-one-out rows are extrapolations (before the first or after "
        "the last remaining anchor), not interpolation errors. Use §5 for the "
        "primary-only curvature error inside 05:00→11:33.")
    add("")
    add("## 6b. Official team-gold cross-check")
    add("")
    add("The official 30 s team curve is an independent measurement. Its level is "
        "roughly 1.0k-3.0k above the per-player UI current sums for most of the match, "
        "then converges at 690 s to the settlement sum. That is a gold-definition "
        "difference (current vs cumulative), not a per-player interpolation error. "
        "The primary series is closer in team aggregate only because it ends on the "
        "cumulative settlement value; use §5 for per-player accuracy.")
    add("")
    add("| series | blue mean abs | blue max abs | red mean abs | red max abs |")
    add("|---|---:|---:|---:|---:|")
    for sname, off in report["official_team_gold_residuals"].items():
        if not off.get("available"):
            continue
        add(
            f"| {sname} | {off['blue_mean_abs_error']:.1f} | {off['blue_max_abs_error']:.1f} | "
            f"{off['red_mean_abs_error']:.1f} | {off['red_max_abs_error']:.1f} |"
        )
    add("")
    add("## 7. Largest uncertainty intervals")
    add("")
    add("Largest anchor gaps (temporal resolution):")
    add("")
    for r in report["largest_gaps"]["supplementary"]:
        add(
            f"- {r['from']} → {r['to']}: {r['gap_s']:.1f} s "
            f"({mmss(r['from_time_s'])} → {mmss(r['to_time_s'])})"
        )
    add("")
    add("Primary-only series gaps:")
    add("")
    for r in report["largest_gaps"]["primary"]:
        add(
            f"- {r['from']} → {r['to']}: {r['gap_s']:.1f} s "
            f"({mmss(r['from_time_s'])} → {mmss(r['to_time_s'])})"
        )
    if report["primary_only_residuals"]:
        worst = max(
            report["primary_only_residuals"],
            key=lambda r: r["max_abs_gold_error"],
        )
        add("")
        add(
            f"Largest single-point error of the strict primary series: "
            f"{worst['max_abs_gold_error']:.1f} gold at {worst['anchor']} "
            f"({mmss(worst['time_s'])}, {worst['worst_gold_player']}); "
            f"max KDA error {worst['max_abs_kda_error']:.3f} "
            f"({worst['worst_kda_player']})."
        )
    add("")
    add(
        "HP coverage is only 3.8 s per player (6.4 s for 钟馗). For every other "
        "frame HP is unknown: roughly 449 s before the first sample and 240 s "
        "after the last sample. This is the largest uncertainty interval in the "
        "whole deliverable."
    )
    add("")
    add("HP unknown intervals (longest first):")
    add("")
    add("| player | from | to | duration | reason |")
    add("|---|---:|---:|---:|---|")
    for r in report["hp"]["unknown_intervals"][:12]:
        add(
            f"| {r['player']} | {mmss(r['from_s'])} | {mmss(r['to_s'])} | "
            f"{r['duration_s']:.1f} s | {r['reason']} |"
        )
    add("")
    add("## 8. HP flags")
    add("")
    hp = report["hp"]
    add(f"- Samples: {hp['sample_count']} (钟馗 has three; `unit_zhongkui_t1.bin` "
        "is byte-identical to `unit_钟馗_t0.bin` and was deduplicated).")
    add(f"- Stale unit clocks: {', '.join(hp['stale_clock']) or 'none'} — "
        "nominal 07:29/07:32 times used.")
    add(f"- Normalised current > max: {', '.join(hp['ratio_gt_1']) or 'none'} — "
        "absolute HP may exceed the panel max reference.")
    add("- Absolute HP = panel max HP at 07:29 × normalised ratio. Max HP changes "
        "with level/items; the reference is not re-read at 07:32.")
    add("")
    add("## 9. Warnings and assumptions")
    add("")
    for w in report["warnings"]:
        add(f"- {w}")
    add("")
    add("## 10. Output files")
    add("")
    for name, meta in report["outputs"].items():
        add(f"- `{name}` — {meta['rows']} rows, {meta['bytes']} bytes")
    add("")

    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    global FPS, END_S, FRAME_COUNT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT,
        help=f"output directory (default: {DEFAULT_OUT})",
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=FPS,
        help=f"frame rate for the per-frame grid (default: {FPS})",
    )
    parser.add_argument(
        "--end-s",
        type=float,
        default=END_S,
        help=f"battle end in seconds (default: {END_S})",
    )
    parser.add_argument(
        "--no-events",
        action="store_true",
        help="do not read the full .abc timeline for event context columns",
    )
    args = parser.parse_args(argv)

    FPS = float(args.fps)
    END_S = float(args.end_s)
    FRAME_COUNT = int(round(END_S * FPS))
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Keep the default timeline next to the outputs; if the caller changed the
    # output directory, still look in the canonical analysis directory.
    timeline_path = ABC_TIMELINE if ABC_TIMELINE.exists() else (DEFAULT_OUT / "abc_input_timeline.json")

    hp_samples, nominal_times = _build_hp_samples()
    events = (
        EventContext()
        if args.no_events
        else load_events(timeline_path, ALL_ANCHORS)
    )

    series_specs = [
        (
            "primary",
            PRIMARY_ANCHORS,
            out_dir / "per_frame.csv",
            out_dir / "per_frame.jsonl",
            False,
        ),
        (
            "supplementary",
            ALL_ANCHORS,
            out_dir / "per_frame_supplementary.csv",
            out_dir / "per_frame_supplementary.jsonl.gz",
            True,
        ),
    ]

    results: dict[str, SeriesResult] = {}
    for name, anchors, csv_path, jsonl_path, gzip_jsonl in series_specs:
        results[name] = build_series(
            name,
            anchors,
            csv_path,
            jsonl_path,
            hp_samples,
            events,
            gzip_jsonl=gzip_jsonl,
        )

    # ---- validation -------------------------------------------------------
    exactness = {
        name: anchor_exactness_summary(res.anchor_exactness)
        for name, res in results.items()
    }
    monotonicity = {
        name: monotonicity_summary(res.monotonicity_violations)
        for name, res in results.items()
    }
    anchor_mono = {
        name: anchor_monotonicity(anchors)
        for name, anchors in (
            ("primary", PRIMARY_ANCHORS),
            ("supplementary", ALL_ANCHORS),
        )
    }
    team_rec = team_reconciliation(ALL_ANCHORS)
    prim_resid = primary_only_residuals(
        [a for a in ALL_ANCHORS if a.tier in {"supplementary", "supplementary_unsaved"}],
        PRIMARY_ANCHORS,
    )
    loo = {
        "primary": leave_one_out(PRIMARY_ANCHORS),
        "supplementary": leave_one_out(ALL_ANCHORS),
    }
    official = {
        "primary": official_team_gold_residuals(PRIMARY_ANCHORS, OFFICIAL_TEAM_GOLD),
        "supplementary": official_team_gold_residuals(ALL_ANCHORS, OFFICIAL_TEAM_GOLD),
    }
    gaps = {
        "primary": segment_gaps(PRIMARY_ANCHORS),
        "supplementary": segment_gaps(ALL_ANCHORS),
    }
    hp_unknown = hp_unknown_intervals(hp_samples)

    # Coverage per series.
    coverage: dict[str, Any] = {}
    total_rows = 0
    for name, res in results.items():
        total_rows += res.rows
        gold_non_null = res.rows  # every row has a gold estimate
        coverage[name] = {
            "rows": res.rows,
            "players": len(PLAYERS),
            "frames_per_player": FRAME_COUNT + 1,
            "measured_rows": res.measured_rows,
            "measured_pct": pct(res.measured_rows, res.rows),
            "interpolated_rows": res.interpolated_rows,
            "interpolated_pct": pct(res.interpolated_rows, res.rows),
            "model_rows": res.model_rows,
            "model_pct": pct(res.model_rows, res.rows),
            "gold_non_null": gold_non_null,
            "gold_non_null_pct": pct(gold_non_null, res.rows),
            "gold_anchor_rows": res.gold_anchor_rows,
            "kda_anchor_rows": res.kda_anchor_rows,
            "hp_measured_rows": res.hp_measured_rows,
            "hp_interpolated_rows": res.hp_interp_rows,
            "hp_unknown_rows": res.hp_unknown_rows,
            "hp_unknown_pct": pct(res.hp_unknown_rows, res.rows),
            "per_player": res.per_player,
        }

    stale_clock = sorted({s.hero for s in hp_samples if s.clock_quality != "ok"})
    ratio_gt_1 = sorted({s.hero for s in hp_samples if s.ratio > 1.0 + 1e-9})

    warnings = [
        "HP is measured only at the 07:29.x / 07:32.x unit-object snapshots "
        "(plus one 07:26.6 sample for 钟馗). Every other frame is explicitly "
        "unknown; `hp_nearest_*` is a stale nearest sample, not an estimate.",
        "Absolute HP uses the 07:29 attributes-panel max HP. Max HP changes with "
        "level and items, and was not re-read at 07:32.",
        "孙悟空's unit-object clock is stale (frame 3587 / 1.337 s in both dumps); "
        "nominal 07:29/07:32 times from the other players were used.",
        "兰陵王's normalised current HP exceeds its normalised max (1252/1089 and "
        "1217/1089). Absolute HP is therefore above the 07:29 panel max; a shield, "
        "overheal or scale mismatch is possible.",
        "KDA between anchors is a fractional cumulative count. It is not an event "
        "log and does not assert that a kill happened at a particular frame.",
        "The primary series has only four measured gold/KDA anchors plus a model "
        "start. The 05:00→11:33 segment is a 393 s straight line and is the "
        "largest gold/KDA uncertainty interval; HP outside the 07:26-07:33 "
        "window is the largest overall uncertainty. The supplementary series uses the "
        "independently measured team-panel samples at 01:27/03:32/05:56/09:01/11:10 "
        "and is materially better (see §5).",
        "`.abc` BUYEQUIP flag 0 is the manual-purchase notification layer; flags "
        "24/90/210 are system/recommendation ticks. Purchase prices are reference "
        "prices, not a spend ledger, and are attached as context only.",
        "The settlement gold field is labeled 'cumulative earned' in docs 5.155, "
        "while the team panel is labeled current gold. The official 30 s team curve "
        "is roughly 1.0k-3.0k above the per-player UI current sums for most of the match but "
        "matches the settlement team sum within 9/6 at 690 s. The anchors therefore "
        "bridge two gold definitions; `gold_measure` marks the bridge segment. Do not "
        "read the per-frame gold column as a literal wallet balance.",
    ]

    report: dict[str, Any] = {
        "generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "tool": str(Path(__file__).resolve()),
        "inputs": {
            "arena_0134": str(LIVE_DIR / "arena_t0_0134.bin"),
            "arena_0245": str(LIVE_DIR / "arena_t2_0245.bin"),
            "arena_0500": str(LIVE_DIR / "arena_paused_0500.bin"),
            "ui_0134": str(LIVE_DIR / "t0_ui.png"),
            "ui_0245": str(LIVE_DIR / "t2_ui.png"),
            "ui_0500": str(LIVE_DIR / "scoreboard_0500.png"),
            "unit_objects": [
                str(LIVE_DIR / f"unit_{p.hero}_{tag}.bin")
                for p in PLAYERS
                for tag in ("t0", "t1")
            ]
            + [
                str(LIVE_DIR / "unit_zhongkui_t0.bin"),
                str(LIVE_DIR / "unit_zhongkui_t1.bin"),
            ],
            "abc_timeline": str(timeline_path) if events.available else "",
            "abc_replay": str(ABC_REPLAY) if ABC_REPLAY.exists() else "",
            "official_team_gold": str(OFFICIAL_TEAM_GOLD),
        },
        "time_base": {
            "fps": FPS,
            "end_s": END_S,
            "end_mmss": mmss(END_S),
            "frames_per_player": FRAME_COUNT + 1,
            "rows_per_series": results["primary"].rows,
            "total_rows": total_rows,
            "note": "frame t = frame / fps; the final frame is pinned to end_s",
        },
        "nominal_hp_times": nominal_times,
        "anchors": [
            {
                "anchor_id": a.aid,
                "time_s": a.time_s,
                "time_mmss": mmss(a.time_s),
                "tier": a.tier,
                "used_in_primary": a in PRIMARY_ANCHORS,
                "source": a.source,
                "note": a.note,
            }
            for a in sorted(ALL_ANCHORS, key=lambda x: x.time_s)
        ],
        "coverage": coverage,
        "exactness": exactness,
        "monotonicity": monotonicity,
        "anchor_monotonicity": anchor_mono,
        "team_reconciliation": team_rec,
        "primary_only_residuals": prim_resid,
        "leave_one_out": loo,
        "official_team_gold_residuals": official,
        "largest_gaps": {
            "primary": gaps["primary"],
            "supplementary": gaps["supplementary"],
        },
        "hp": {
            "sample_count": len(hp_samples),
            "samples": [
                {
                    "player": s.player,
                    "hero": s.hero,
                    "tag": s.tag,
                    "file": s.file,
                    "time_s": s.time_s,
                    "clock_time_s": s.clock_time_s,
                    "clock_quality": s.clock_quality,
                    "current": s.current,
                    "maximum": s.maximum,
                    "ratio": round(s.ratio, 6),
                    "max_ref": s.max_ref,
                    "hp_abs": round(s.hp_abs, 1),
                    "flags": s.flags,
                    "note": s.note,
                }
                for s in hp_samples
            ],
            "stale_clock": stale_clock,
            "ratio_gt_1": ratio_gt_1,
            "unknown_intervals": hp_unknown,
        },
        "events": {
            "available": events.available,
            "path": events.path,
            "flags": dict(events.flags),
            "totals": {hero: dict(counter) for hero, counter in events.totals.items()},
            "past_end": {hero: dict(counter) for hero, counter in events.past_end.items()},
            "meta": events.meta,
            "usage_note": (
                "Events are attached as per-frame context columns and interval "
                "counts. They are never used to move gold or KDA, and no kill "
                "event is fabricated."
            ),
        },
        "warnings": warnings,
        "outputs": {},
    }

    # Write auxiliary files.
    anchors_csv = out_dir / "anchors.csv"
    hp_csv = out_dir / "hp_samples.csv"
    events_csv = out_dir / "events_used.csv"
    write_anchors_csv(anchors_csv, ALL_ANCHORS)
    write_hp_samples_csv(hp_csv, hp_samples)
    write_events_csv(events_csv, events)

    validation_json = out_dir / "validation_report.json"
    validation_md = out_dir / "validation_report.md"

    # Collect output sizes after all writes.
    for path, rows in (
        (out_dir / "per_frame.csv", results["primary"].rows),
        (out_dir / "per_frame.jsonl", results["primary"].rows),
        (out_dir / "per_frame_supplementary.csv", results["supplementary"].rows),
        (out_dir / "per_frame_supplementary.jsonl.gz", results["supplementary"].rows),
        (anchors_csv, len(ALL_ANCHORS) * len(PLAYERS)),
        (hp_csv, len(hp_samples)),
        (
            events_csv,
            len(events.intervals)
            + len(PLAYERS)
            + sum(1 for p in PLAYERS if events.past_end.get(p.hero)),
        ),
    ):
        report["outputs"][path.name] = {
            "rows": rows,
            "bytes": path.stat().st_size if path.exists() else 0,
        }

    write_json(validation_json, report)
    report["outputs"][validation_json.name] = {
        "rows": 1,
        "bytes": validation_json.stat().st_size,
    }
    write_validation_markdown(validation_md, report)
    report["outputs"][validation_md.name] = {
        "rows": 1,
        "bytes": validation_md.stat().st_size,
    }
    # Rewrite JSON with the final output sizes (markdown size included).
    write_json(validation_json, report)

    # ---- console summary --------------------------------------------------
    print(f"out_dir: {out_dir}")
    print(f"frames/player: {FRAME_COUNT + 1}  rows/series: {results['primary'].rows}")
    for name, cov in coverage.items():
        print(
            f"{name:13s} measured={cov['measured_rows']:5d} "
            f"interp={cov['interpolated_rows']:6d} model={cov['model_rows']:5d} "
            f"hp_meas={cov['hp_measured_rows']:4d} hp_interp={cov['hp_interpolated_rows']:4d} "
            f"hp_unknown={cov['hp_unknown_rows']:6d}"
        )
    for name, mono in monotonicity.items():
        print(f"{name:13s} monotonicity violations: {mono['violations']}")
    for name, ex in exactness.items():
        print(
            f"{name:13s} anchor gold max|err|={ex['gold_max_abs_error']:.6g} "
            f"kda max|err|={ex['kda_max_abs_error']:.6g} "
            f"hp max|err|={ex['hp_ratio_max_abs_error']:.6g}"
        )
    if prim_resid:
        print("primary-only vs supplementary:")
        for r in prim_resid:
            print(
                f"  {r['anchor']} @{mmss(r['time_s'])}: "
                f"max gold err {r['max_abs_gold_error']:.1f} "
                f"({r['worst_gold_player']}), max KDA err {r['max_abs_kda_error']:.3f} "
                f"({r['worst_kda_player']})"
            )
    print(f"wrote {validation_json}")
    print(f"wrote {validation_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
