import json
import tempfile
import unittest
from pathlib import Path

import official_economy
from analysis_data import AnalysisRepository


class OfficialEconomyTests(unittest.TestCase):
    def test_timeline_uses_30_second_points(self):
        normalized = {'match': {'goldIntervalSecApprox': 30},
                      'economy': {'blue': [3056, 4332], 'red': [2684, 3865]}}
        points = official_economy.timeline(normalized)
        self.assertEqual([point['gameTime'] for point in points], [30, 60])
        self.assertEqual(points[0]['blueGold'], 3056)
        self.assertEqual(points[0]['goldDiff'], 372)
        self.assertEqual(points[1]['goldDiff'], 467)
        self.assertEqual(points[0]['source'], 'official-30s')

    def test_arrays_are_aligned_to_the_shorter_side(self):
        normalized = {'economy': {'blue': [100, 200], 'red': [90, 210, 220]}}
        self.assertEqual(len(official_economy.series(normalized)), 2)

    def test_repository_falls_back_to_official_economy(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            matches = root / 'matches'
            official = root / 'official_replays'
            matches.mkdir()
            (official / 'camp-test').mkdir(parents=True)
            (official / 'camp-test' / 'normalized.json').write_text(json.dumps({
                'schema': 'camp-replay-v1',
                'match': {'goldIntervalSecApprox': 30},
                'economy': {'blue': [3000, 4500], 'red': [2800, 5000]},
            }), encoding='utf-8')
            (matches / 'channel-a.json').write_text(json.dumps({
                'schema': 'kpl-match-data-v1',
                'match': {'key': 'channel-a', 'duration': 120,
                          'officialReplay': {'id': 'camp-test'}},
                'team': {'timeline': []},
                'players': [],
                'sources': [],
            }), encoding='utf-8')
            repo = AnalysisRepository(root / 'unused.sqlite3', matches, root / 'imports',
                                      official)
            timeline = repo.get()['matches'][0]['process']['timeline']
            self.assertEqual([point['gameTime'] for point in timeline], [30, 60])
            self.assertEqual(timeline[1]['goldDiff'], -500)

    def test_existing_timeline_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            matches = root / 'matches'
            matches.mkdir()
            (matches / 'channel-a.json').write_text(json.dumps({
                'schema': 'kpl-match-data-v1',
                'match': {'key': 'channel-a', 'duration': 60,
                          'officialReplay': {'id': 'camp-missing'}},
                'team': {'timeline': [{'gameTime': 60, 'blueGold': 1, 'redGold': 2}]},
                'players': [],
                'sources': [],
            }), encoding='utf-8')
            repo = AnalysisRepository(root / 'unused.sqlite3', matches, root / 'imports',
                                      root / 'official_replays')
            timeline = repo.get()['matches'][0]['process']['timeline']
            self.assertEqual(timeline, [{'gameTime': 60, 'blueGold': 1, 'redGold': 2}])


if __name__ == '__main__':
    unittest.main()
