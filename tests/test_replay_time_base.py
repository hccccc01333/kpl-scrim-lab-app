"""The frame→second constants live in exactly one file, and the product keeps
the documented value until the open question is closed.

Background
----------
Two frame rates were in the tree: 15 (``docs/replay_binary_format.md`` §5.129,
derived from the results page of ``20261102_161129``) and 15.1515 (used by
``replay_codec/`` and the trajectory tooling).  At frame 10,409 they disagree
by 6 s, so a figure from one path could not be compared with the other.

The engine's own (frame, ms) pair measures 15.1515 fps — reproduced from the
raw dumps ``live_20261104/unit_钟馗_t0.bin`` / ``unit_张良_t0.bin``:

    frame 6838 @ 449,228 ms  →  frame 6895 @ 452,990 ms    (57 frames / 3,762 ms)

What is *not* established is that the .abc record stream's ``sequence`` is that
same counter.  Until that comparison exists the product stays on 15 fps and the
measured value is kept as ``FPS_ENGINE`` for the research tools that already
used it.  These tests pin that split so neither side drifts silently.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

import replay_time  # noqa: E402
from tools.replay_frame_commands import FRAME_RATE  # noqa: E402

SCAN_DIRS = (ROOT, ROOT / 'tools', ROOT / 'replay_codec')
OWNER = ROOT / 'replay_time.py'
# A literal assignment of a clock constant outside the owner.
PRIVATE_CLOCK = re.compile(
    r'(?m)^\s*(FPS|FPS_ENGINE|FRAME_RATE|F0|BATTLE_START_FRAME[A-Z_]*)\s*=\s*'
    r'(15(?:\.1515)?|31\.4)\s*(?:#.*)?$')


class ClockTests(unittest.TestCase):
    def test_product_keeps_the_documented_baseline(self):
        self.assertEqual(replay_time.FPS, 15)
        self.assertEqual(FRAME_RATE, 15)
        self.assertEqual(replay_time.BATTLE_START_FRAME_APPROX, (0, 14))

    def test_engine_measurement_is_recorded(self):
        # 57 frames over 3,762 ms on the paused unit dumps.
        self.assertAlmostEqual(replay_time.FPS_ENGINE, 57 / 3.762, places=3)
        # Frame 6,838 ↔ 449.228 s, fitted on the same dump.
        self.assertAlmostEqual(
            replay_time.engine_seconds(6838), 449.228, delta=0.01)
        self.assertAlmostEqual(replay_time.BATTLE_START_FRAME_ENGINE, 31.4)

    def test_the_two_clocks_really_differ(self):
        # This is the whole point: 1 % over an 11-minute match is ~7 s.
        self.assertGreater(abs(replay_time.engine_seconds(10509)
                               - (10509 - 1) / 15), 5.0)

    def test_no_private_copy_of_a_clock(self):
        offenders = []
        for base in SCAN_DIRS:
            for path in sorted(base.glob('*.py')):
                if path == OWNER or '__pycache__' in path.parts:
                    continue
                text = path.read_text(encoding='utf-8', errors='replace')
                for match in PRIVATE_CLOCK.finditer(text):
                    offenders.append(f'{path.relative_to(ROOT).as_posix()}: '
                                     f'{match.group(0).strip()}')
        self.assertEqual(offenders, [],
                         '帧率/开局帧常量只能定义在 replay_time.py')

    def test_replay_codec_keeps_its_engine_clock(self):
        source = (ROOT / 'replay_codec' / 'prepare_sample.py').read_text(
            encoding='utf-8')
        self.assertIn('replay_time.engine_seconds(', source)
        self.assertNotIn('FPS_ENGINE =', source)
        # The +3 s offset is a position-join alignment, not a second clock.
        self.assertIn('ALIGN_DT', source)


if __name__ == '__main__':
    unittest.main()
