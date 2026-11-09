"""Regression tests for V3 data-scope and replay analysis corrections."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import deep_analysis


class AnalysisCorrections(unittest.TestCase):
    def test_advantage_excludes_short_and_unknown_games(self):
        games = [
            dict(seq='short', ownCamp='blue', win=True, duration=599, diff=[0, 5000]),
            dict(seq='at-mark', ownCamp='red', win=True, duration=600, diff=[0, -4000]),
            dict(seq='no-result', ownCamp='blue', win=None, duration=900, diff=[0, 1000]),
            dict(seq='one-point', ownCamp='blue', win=True, duration=900, diff=[500]),
        ]
        result = deep_analysis.advantage_from_games(games)
        self.assertEqual(result['overall']['n'], 1)
        self.assertEqual(result['rows'][0]['game'], 'at-mark')
        self.assertEqual(result['rows'][0]['leadAt10'], 4000)

    def test_resources_only_count_monster_objectives_and_scale_raw_distances(self):
        data = {'routes': {'rows': [{'pathLength': 53, 'displacement': 106}]},
                'trio': {'rows': [{'avgSpread': 53}]}, 'deaths': {'rows': [{'nearest': 26.5}]}}
        games = [{'events': [{'eventType': 'dragontower', 'dtType': '1'},
                             {'eventType': 'dragontower', 'dtType': '2'},
                             {'eventType': 'battle'}]}]
        captured = []
        def resource(g):
            captured.extend(g[0]['events'])
            return {'rows': []}
        with patch.object(deep_analysis.map_calibration, 'load', return_value={'calibrated': True, 'width': 106}), \
             patch.object(deep_analysis.analysis_space, 'all_analyses', return_value=data), \
             patch.object(deep_analysis.analysis_space, 'load_games', return_value=games), \
             patch.object(deep_analysis.analysis_space, 'resource_contest', side_effect=resource):
            result = deep_analysis.space('replays', 'camp', 'data')
        self.assertEqual(captured, [{'eventType': 'dragontower', 'dtType': '1'}])
        self.assertEqual(result['routes']['rows'][0]['pathLength'], .5)
        self.assertEqual(result['deaths']['rows'][0]['nearest'], .25)

    def test_training_comparison_uses_only_own_and_verified_years(self):
        import analysis_profile
        from unittest.mock import MagicMock
        rows = [{'seq': 'known', 'side': 'own', 'date': '2026-01-01'},
                {'seq': 'unknown', 'side': 'own', 'date': '2026-01-01'},
                {'seq': 'known', 'side': 'enemy', 'date': '2026-01-01'}]
        known, unknown = MagicMock(), MagicMock()
        known.stem, unknown.stem = 'known', 'unknown'
        known.read_text.return_value = '{"data":{"battle":{"startTime":"2024-01-01 10:00"}}}'
        unknown.read_text.return_value = '{"data":{"battle":{"startTime":"01-01 10:00"}}}'
        workspace = MagicMock(); workspace.list_training.return_value = [{'goal': 'test'}]
        captured = []
        def effect(filtered, training):
            captured.extend(filtered)
            return {'available': False}
        with patch.object(analysis_profile, 'load_rows', return_value=rows), \
             patch.object(analysis_profile, 'training_effect', side_effect=effect), \
             patch.object(Path, 'glob', return_value=[known, unknown]):
            deep_analysis.training_effects('camp', workspace)
        self.assertEqual([(x['seq'], x['date']) for x in captured],
                         [('known', '2024-01-01'), ('unknown', '')])


if __name__ == '__main__':
    unittest.main()
