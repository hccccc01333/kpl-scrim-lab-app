"""Frame ↔ seconds for .abc replay streams: one home for every clock constant.

The repository carried the same number in several places and the two frame
rates disagree by 1 % (≈7 s over an 11-minute match), so the constants live
here and nowhere else.  Which one a call site uses is explicit, not implied.

Two clocks, both real, not yet proven to be the same counter
------------------------------------------------------------
``FPS_ENGINE = 15.1515`` — measured from the engine's (frame, ms) pair at
``+0x1664/+0x1668``.  On the paused unit dumps ``unit_钟馗_t0/t1.bin`` and
``unit_张良_t0/t1.bin`` the pair advances 57 frames in 3,762 ms (reproduced
2026-11-10 from the raw files):

    frame 6838 @ 449,228 ms  →  frame 6895 @ 452,990 ms

``FPS = 15`` — the value in ``README.md`` §5.129, derived
from the results page of replay ``20260101_000000`` (11:33 = 693 s) assuming
the last manual buy (frame 10,409) lands at the end of the match.

The open link: the engine measurement is about the *engine's* frame counter.
Nothing in this repository yet proves that the ``sequence`` field of the .abc
record stream is that same counter (``README.md`` §5.133
asserts "条目 seq = 帧号" but does not compare the two on one replay).  Until
that comparison exists, the product keeps the documented 15 fps and the
measured 15.1515 is used only where a research tool already relied on it.

Do not add a third copy of either number: ``tests/test_replay_time_base.py``
fails when one appears outside this file.
"""
from __future__ import annotations

#: Product baseline, from docs §5.129.  Unchanged behaviour.
FPS = 15
#: Engine (frame, ms) clock measured on the 07:29 unit dumps.
FPS_ENGINE = 15.1515
#: Battle start frame under the §5.129 model (F0 ∈ [0..14]).
BATTLE_START_FRAME_APPROX = (0, 14)
#: Battle start frame fitted on the engine dump (frame 6838 ↔ 449.228 s).
BATTLE_START_FRAME_ENGINE = 31.4


def seconds(frame: float, *, fps: float = FPS) -> float:
    """Battle seconds for a frame number under the given clock."""
    return frame / fps


def relative(frame_number: float, first_frame: float = 1,
             *, fps: float = FPS) -> float:
    """Seconds since ``first_frame``; this is the catalog ``time_s`` column."""
    return (frame_number - first_frame) / fps


def engine_seconds(frame: float) -> float:
    """Battle seconds on the measured engine clock (research use)."""
    return (frame - BATTLE_START_FRAME_ENGINE) / FPS_ENGINE
