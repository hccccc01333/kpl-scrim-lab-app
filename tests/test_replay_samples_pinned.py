"""Pin what the real samples decode to, so format drift is visible.

The synthetic fixtures in ``replay_fixtures.py`` validate the parser against
its own assumptions.  These tests validate it against captured files, and they
skip (rather than fail) on machines that do not have them, because the samples
are coach data and are not in the repository.

Every expected value below is also recorded in ``docs/replay_binary_format.md``
§5.129 (roster, ratings) or ``docs/evidence_audit.md`` (frame counts), so a
change here means the parser or the format moved, not that the number was
arbitrary.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

import replay_parser  # noqa: E402

SAMPLE_DIR = ROOT / 'data' / 'replays' / 'samples' / '20261102_161129'
ABC = SAMPLE_DIR / ('20261102_161129_870343216_95868_1793606215_'
                    '2B9FAA08A7AD40D09ABDA364F9C1E804.abc')

# Ten ratings read off the results page for the same match (docs 5.129), in
# roster order: blue 钟馗 妲己 孙悟空 关羽 百里守约, red 公孙离 吕布 貂蝉 兰陵王 张良.
HEROES = ['钟馗', '妲己', '孙悟空', '关羽', '百里守约',
          '公孙离', '吕布', '貂蝉', '兰陵王', '张良']
RATINGS = [8.4, 10.4, 9.1, 13.1, 10.6, 5.9, 5.4, 5.5, 3.6, 4.9]


@unittest.skipUnless(ABC.is_file(), 'real 2026-11-02 sample not present')
class PinnedSampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = replay_parser.inspect_replay(ABC.read_bytes())

    def test_roster_matches_the_results_page(self):
        blocks = self.report['blocks']
        self.assertEqual(len(blocks), 10)
        self.assertEqual([b['heroName'] for b in blocks], HEROES)
        self.assertEqual([b['score'] for b in blocks], RATINGS)
        self.assertEqual(self.report['blocksLayout'], 'roster-5247758')

    def test_frame_stream_count_is_stable(self):
        frames = self.report['frames']
        self.assertEqual(frames['status'], 'frame-stream')
        self.assertEqual(frames['records'], 10509)
        self.assertEqual(frames['firstSequence'], 1)
        self.assertEqual(frames['lastSequence'], 10509)
        self.assertTrue(frames['sequenceWraps'])

    def test_tail_stream_counts_are_stable(self):
        events = self.report['playerEvents']
        # 0x85 is a BUYEQUIP mirror: no gold amounts, so it cannot build a ledger.
        self.assertEqual(events['buyEcho']['unique'], 547)
        self.assertEqual(events['skills']['unique'], 120)
        self.assertEqual(events['positions']['records'], 78)

    def test_match_outcome_is_stable(self):
        self.assertEqual(self.report['mvpScore']['winningCamp'], 'blue')
        self.assertEqual(self.report['scoreTable']['offset'], 482879)

    def test_layout_is_resolved_from_the_profile_registry(self):
        self.assertEqual(self.report['header']['profile'], 'observed-12.1.1.x-v3')
        self.assertTrue(self.report['header']['layoutSupported'])
        self.assertEqual(self.report['provenance']['gameplayState']['confidence'],
                         'undecoded')


if __name__ == '__main__':
    unittest.main()
