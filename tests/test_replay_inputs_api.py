import os
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault('TRAINING_DB', str(ROOT / 'test-results' / f'test-inputs-{uuid.uuid4().hex}.sqlite3'))

from fastapi.testclient import TestClient
from replay_fixtures import abc_fixture, inputs_5v5_fixture
from server import app
from tools.replay_frame_commands import hero_inputs


COMMANDS = (
    bytes.fromhex("0112403c"),                # frame 1: one move, unit 8, dir +60
    bytes.fromhex("021249331340"),            # frame 2: move unit 9 dir -51 + attack 0x40
    bytes.fromhex("010203e98504570000000800"),  # frame 3: BUYEQUIP entity 1001, equip 1111
)


class HeroInputsTests(unittest.TestCase):
    """Unit-level grouping on a synthetic record stream (no game assets)."""

    def test_groups_events_by_unit_and_entity(self):
        result = hero_inputs(inputs_5v5_fixture(COMMANDS))
        self.assertEqual(result["status"], "decoded")
        self.assertEqual(result["frameRecords"], 3)
        self.assertEqual(result["units"]["8"]["moves"], [[1, 60, 60, 0, 0]])
        self.assertEqual(result["units"]["9"]["moves"], [[2, -51, 51, 1, 0]])
        self.assertEqual(result["units"]["8"]["attacks"], [[2, 0, None, 0, 0]])
        self.assertEqual(result["entities"]["1001"]["stats"]["buys"], 1)
        self.assertEqual(result["entities"]["1001"]["buys"], [[3, 1111, 8, 0]])
        self.assertEqual(result["units"]["8"]["stats"]["dirMin"], 60)
        self.assertIsNone(result["entities"]["1001"]["stats"]["dirMin"])

    def test_unsupported_frame_counts_as_unresolved(self):
        result = hero_inputs(inputs_5v5_fixture((bytes.fromhex("01ff1340"),)))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["unresolvedFrames"], 1)
        self.assertEqual(result["fullyParsedFrames"], 0)
        self.assertFalse(result["units"])

    def test_stream_without_id1075_reports_wall(self):
        result = hero_inputs(abc_fixture())
        self.assertEqual(result["status"], "no-record-stream")
        self.assertTrue(result["error"])
        self.assertEqual(result["units"], {})


class ReplayInputsApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, base_url='http://localhost')
        uploaded = cls.client.post('/api/replays/files?name=inputs-fixture.abc',
                                   content=inputs_5v5_fixture(COMMANDS))
        assert uploaded.status_code == 200, uploaded.text
        cls.replay_id = uploaded.json()['id']
        imported = cls.client.post('/api/replays/import', json={'abcFileId': cls.replay_id})
        assert imported.status_code == 200, imported.text
        cls.report = imported.json()['report']
        old_uploaded = cls.client.post('/api/replays/files?name=old-fixture.abc',
                                       content=abc_fixture())
        assert old_uploaded.status_code == 200, old_uploaded.text
        old_imported = cls.client.post('/api/replays/import',
                                       json={'abcFileId': old_uploaded.json()['id']})
        assert old_imported.status_code == 200, old_imported.text
        cls.old_id = old_uploaded.json()['id']

    def test_01_summary_joins_roster_names(self):
        response = self.client.get(f'/api/replays/{self.replay_id}/inputs')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'decoded')
        self.assertEqual(len(data['heroes']), 10)
        by_unit = {row['unit']: row for row in data['heroes']}
        self.assertEqual(by_unit[8]['slot'], 0)
        self.assertEqual(by_unit[8]['moves'], 1)
        self.assertEqual(by_unit[9]['moves'], 1)
        self.assertEqual(by_unit[16]['moves'], 0)
        self.assertEqual(by_unit[9]['buys'], 1)
        self.assertEqual(by_unit[8]['buys'], 0)
        self.assertIn('同角度系', data['schema'])
        self.assertEqual(data['timeBase']['framesPerSecond'], 15)

    def test_02_unit_events_carry_directions(self):
        response = self.client.get(f'/api/replays/{self.replay_id}/inputs?unit=9')
        self.assertEqual(response.status_code, 200)
        hero = response.json()['hero']
        self.assertEqual(hero['hero'], self.report['blocks'][1]['heroName'])
        self.assertEqual(hero['moves'], [[2, -51, 51, 1, 0]])
        self.assertEqual(hero['attacks'], [])
        unit8 = self.client.get(f'/api/replays/{self.replay_id}/inputs?unit=8').json()['hero']
        self.assertEqual(unit8['moves'], [[1, 60, 60, 0, 0]])
        self.assertEqual(unit8['attacks'], [[2, 0, None, 0, 0]])

    def test_03_entity_events_join_roster_entity(self):
        response = self.client.get(f'/api/replays/{self.replay_id}/inputs?unit=9')
        hero = response.json()['hero']
        # equip 1111 = 铁剑, battle-table price 275 (既有校准).
        self.assertEqual(hero['buys'], [[3, 1111, 8, 0, 275]])
        # The synthetic record stream has no 0x01-wrapped TLVs.
        self.assertEqual(hero['angleSamples'], [])
        # Direction-integrated shape estimate: present, honesty-labeled (既有校准).
        self.assertTrue(hero['pathEstimate'])
        self.assertIn('绝非位置', hero['pathNote'])

    def test_04_unknown_unit_and_missing_replay(self):
        response = self.client.get(f'/api/replays/{self.replay_id}/inputs?unit=13')
        self.assertEqual(response.status_code, 404)
        response = self.client.get('/api/replays/missing-id/inputs')
        self.assertEqual(response.status_code, 404)

    def test_05_old_layout_reports_no_record_stream(self):
        response = self.client.get(f'/api/replays/{self.old_id}/inputs')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'no-record-stream')
        self.assertEqual(data['heroes'], [])


if __name__ == '__main__':
    unittest.main()
