import csv
import json
import tempfile
import unittest
from pathlib import Path

import replay_panels

ROOT = Path(__file__).resolve().parents[1]
ABC = ROOT / 'data/replays/samples/20261102_161129' / (
    '20261102_161129_870343216_95868_1793606215_2B9FAA08A7AD40D09ABDA364F9C1E804.abc')
OPE = ABC.with_suffix('.ope')
CAMP = ROOT / 'data/camp_details/1793606215.json'
TRUTH = ROOT / 'replay_codec/sample_data/20261102_panel_truth.csv'


@unittest.skipUnless(ABC.is_file() and CAMP.is_file(), 'sample replay / camp detail not present')
class ReplayPanelsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        detail = json.loads(CAMP.read_text(encoding='utf-8'))
        cls.bundle = replay_panels.build_bundle(ABC, OPE, detail, str(CAMP))
        cls.players = {(player['camp'], player['hero']): player
                       for player in cls.bundle['players']}

    def test_match_key(self):
        key = replay_panels.parse_match_key(ABC)
        self.assertEqual(key['gameSeq'], '1793606215')
        self.assertEqual(key['gameSvr'], '95868')
        self.assertEqual(key['relaySvr'], '870343216')
        self.assertEqual(key['date'], '2026-11-02')

    def test_match_summary(self):
        match = self.bundle['match']
        self.assertEqual(match['gameSeq'], '1793606215')
        self.assertEqual(match['score'], {'blue': 27, 'red': 6})
        self.assertEqual(match['winningCamp'], 'blue')
        self.assertEqual(match['result'], 'win')
        self.assertEqual(match['durationSec'], 694)

    def test_panel_truth_kda_gold_rating(self):
        truth = list(csv.DictReader(TRUTH.open(encoding='utf-8')))
        self.assertEqual(len(truth), 10)
        for row in truth:
            camp = 'blue' if row['team'] == '1' else 'red'
            player = self.players[(camp, row['hero'])]
            fields = player['fields']
            self.assertEqual(fields['kills'], int(row['kills']))
            self.assertEqual(fields['deaths'], int(row['deaths']))
            self.assertEqual(fields['assists'], int(row['assists']))
            self.assertEqual(fields['gold'], int(row['gold']))
            self.assertAlmostEqual(float(fields['rating']), float(row['score']), places=2)
            self.assertFalse(player['bot'])

    def test_hero_damage_and_support_fields(self):
        player = self.players[('blue', '百里守约')]
        fields = player['fields']
        self.assertEqual(fields['damageDealt'], 66056)
        self.assertEqual(fields['damageTaken'], 25746)
        self.assertAlmostEqual(fields['participation'], 48.1, places=1)
        self.assertEqual(fields['takenPerDeath'], 25746)
        self.assertAlmostEqual(fields['damageConversion'], 1.2, places=2)
        self.assertEqual(fields['jungleGold'], 542)
        self.assertEqual(fields['cs'], 38)
        self.assertEqual(fields['control'], 1)
        self.assertEqual(fields['healing'], 12072)
        self.assertEqual(fields['towerDamage'], 20212)
        self.assertEqual(fields['mvp'], None)

    def test_six_panels(self):
        self.assertEqual(tuple(self.bundle['panels']), replay_panels.PAGES)
        self.assertEqual(len(self.bundle['panels']['kda']['rows']), 10)
        self.assertIn('kills', self.bundle['panels']['kda']['fields'])
        self.assertIn('damageDealt', self.bundle['panels']['output']['fields'])
        self.assertIn('healing', self.bundle['panels']['team']['fields'])
        blue = [row for row in self.bundle['panels']['kda']['rows'] if row['camp'] == 'blue']
        self.assertAlmostEqual(sum(row['values']['killsShare'] for row in blue), 100.0, delta=0.2)
        self.assertAlmostEqual(sum(row['values']['deathsShare'] for row in blue), 100.0, delta=0.2)

    def test_missing_camp_keeps_fields_null(self):
        bundle = replay_panels.build_bundle(ABC, OPE, None, None)
        self.assertTrue(any('营地面板' in warning for warning in bundle['warnings']))
        player = next(item for item in bundle['players'] if item['hero'] == '百里守约')
        self.assertIsNone(player['fields']['kills'])
        self.assertIsNone(player['fields']['damageDealt'])
        self.assertEqual(player['fields']['rating'], 10.6)
        self.assertEqual(bundle['match']['winningCamp'], 'blue')
        self.assertEqual(bundle['match']['result'], 'win')
        self.assertIsNone(bundle['match']['score']['blue'])

    def test_render_six_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            for page in replay_panels.PAGES:
                path = replay_panels.render_page(self.bundle, page, Path(directory) / f'{page}.png')
                self.assertTrue(path.is_file())
                self.assertGreater(path.stat().st_size, 10_000)


if __name__ == '__main__':
    unittest.main()
