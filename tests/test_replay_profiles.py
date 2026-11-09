from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from replay_fixtures import abc_fixture  # noqa: E402
from replay_parser import inspect_replay  # noqa: E402
from replay_profiles import load_registry, resolve_profile  # noqa: E402


class ReplayProfileTests(unittest.TestCase):
    def test_builtin_profile_matches_observed_versions(self):
        profile = resolve_profile(['12.1.1.1', '12.1.1.26'], ['4989537', '5247758'])
        self.assertIsNotNone(profile)
        self.assertEqual(profile['id'], 'observed-12.1.1.x-v3')
        self.assertEqual(profile['layout']['blockStride'], 1517)
        self.assertEqual(profile['layout']['heroOffsets'], (771, 1415, 1445))

    def test_unknown_version_has_no_profile(self):
        self.assertIsNone(resolve_profile(['13.1.1.1', '13.1.1.0'], ['6000000']))

    def test_config_overrides_builtin_profile(self):
        payload = {'schemaVersion': 1, 'profiles': [{
            'id': 'observed-12.1.1.x-v3',
            'versionPrefixes': ['12.1.1.'],
            'layout': {'blockStride': 1600},
        }]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'profiles.json'
            path.write_text(json.dumps(payload), encoding='utf-8')
            registry = load_registry(path)
        profile = resolve_profile(['12.1.1.1'], ['4989537'], registry)
        self.assertEqual(profile['layout']['blockStride'], 1600)
        # Untouched fields keep the builtin values.
        self.assertEqual(profile['layout']['heroOffsets'], (771, 1415, 1445))

    def test_registry_reports_config_source(self):
        registry = load_registry()
        self.assertIn('profiles', registry)
        self.assertTrue(registry['profiles'])

    def test_report_carries_profile_and_confidence(self):
        report = inspect_replay(abc_fixture())
        self.assertEqual(report['profileId'], 'observed-12.1.1.x-v3')
        self.assertEqual(report['confidence']['events'], 'decoded')
        self.assertEqual(report['confidence']['positions'], 'estimated')
        self.assertEqual(report['provenance']['container']['source'], 'abc-container')
        self.assertFalse(report['gameplayStateDecoded'])

    def test_unknown_version_report_has_no_profile(self):
        report = inspect_replay(abc_fixture().replace(b'12.1.1.', b'13.1.1.'))
        self.assertFalse(report['header']['layoutSupported'])
        self.assertIsNone(report['profileId'])
        self.assertEqual(report['blocks'], [])


if __name__ == '__main__':
    unittest.main()
