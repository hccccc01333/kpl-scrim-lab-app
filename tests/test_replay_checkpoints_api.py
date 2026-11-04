import hashlib
import json
import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault('TRAINING_DB', str(ROOT / 'test-results' / f'test-checkpoints-{uuid.uuid4().hex}.sqlite3'))

from fastapi.testclient import TestClient
from replay_fixtures import normal_5v5_fixture
import server
from server import app


# Trimmed from data/replays/_analysis/live_20261104/state_table/state.jsonl:
# two arena checkpoints, one HP-only unit window, and two event-only rows.
ROWS = [
    {
        'frame': 1424, 'time_s': 94.858, 'time_mmss': '01:34.8',
        'player': '胡不喜#', 'hero': '钟馗', 'entity_id': 1168, 'camp': 1,
        'unit': 8, 'slot': 0, 'gold': 679, 'kills': 0, 'deaths': 0, 'assists': 0,
        'level': 2, 'hp_current': 546, 'hp_max': 1079, 'hp_ratio': 0.506,
        'abs_hp_estimate': None, 'hp_max_abs': None, 'x': -34337.1, 'z': -50392.6,
        'pos_source': 'idle', 'row_kind': 'state',
        'sources': 'arena_unit_object;arena_stats;trajectories',
        'note': 'arena record idx 1000000009; gold/KDA match t0_ui.png',
    },
    {
        'frame': 1424, 'time_s': 94.858, 'time_mmss': '01:34.8',
        'player': '自诩一棵葱', 'hero': '妲己', 'entity_id': 1613, 'camp': 1,
        'unit': 9, 'slot': 1, 'gold': 890, 'kills': 0, 'deaths': 0, 'assists': 0,
        'level': 3, 'hp_current': None, 'hp_max': None, 'hp_ratio': None,
        'abs_hp_estimate': None, 'hp_max_abs': None, 'pos_source': 'integrated',
        'row_kind': 'state', 'sources': 'arena_stats;trajectories',
        'note': 'arena record idx 1000000011',
    },
    {
        'frame': 6739, 'time_s': 449.219, 'time_mmss': '07:29.2',
        'player': '自诩一棵葱', 'hero': '妲己', 'entity_id': 1613, 'camp': 1,
        'unit': 9, 'slot': 1, 'gold': None, 'kills': None, 'deaths': None,
        'assists': None, 'level': None, 'hp_current': 398, 'hp_max': 1084,
        'hp_ratio': 0.3672, 'abs_hp_estimate': 3702, 'hp_max_abs': 10082,
        'pos_source': 'integrated', 'row_kind': 'state',
        'sources': 'unit_object;trajectories', 'note': 'unit window HP sample',
    },
    {
        'frame': 1424, 'time_s': 94.858, 'time_mmss': '01:34.8',
        'player': '狂傲自由魂Z.', 'hero': '关羽', 'entity_id': 538, 'camp': 1,
        'unit': 11, 'slot': 3, 'gold': None, 'kills': None, 'deaths': None,
        'assists': None, 'level': None, 'hp_current': None, 'hp_max': None,
        'hp_ratio': None, 'abs_hp_estimate': None, 'hp_max_abs': None,
        'pos_source': 'integrated', 'row_kind': 'event',
        'sources': 'event_windows;trajectories', 'note': 'event-only frame',
    },
    {
        'frame': 6739, 'time_s': 449.219, 'time_mmss': '07:29.2',
        'player': '敌方选手', 'hero': '吕布', 'entity_id': 296, 'camp': 2,
        'unit': 16, 'slot': 0, 'gold': None, 'kills': None, 'deaths': None,
        'assists': None, 'level': None, 'hp_current': None, 'hp_max': None,
        'hp_ratio': None, 'abs_hp_estimate': None, 'hp_max_abs': None,
        'pos_source': 'integrated', 'row_kind': 'event',
        'sources': 'event_windows;trajectories', 'note': 'event-only frame',
    },
]


class ReplayCheckpointsApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, base_url='http://localhost')
        uploaded = cls.client.post('/api/replays/files?name=checkpoint-fixture.abc',
                                   content=normal_5v5_fixture())
        assert uploaded.status_code == 200, uploaded.text
        cls.replay_id = uploaded.json()['id']
        imported = cls.client.post('/api/replays/import', json={'abcFileId': cls.replay_id})
        assert imported.status_code == 200, imported.text
        cls.report = imported.json()['report']
        cls.payload = ('\n'.join(json.dumps(row, ensure_ascii=False) for row in ROWS) + '\n').encode()
        cls.url = f'/api/replays/{cls.replay_id}/checkpoints'

    def setUp(self):
        self.client.delete(self.url)

    def import_rows(self, rows=ROWS, **kwargs):
        return self.client.post(self.url, **kwargs)

    def test_01_jsonl_import_and_get_returns_rows_and_confidence(self):
        response = self.import_rows(content=self.payload, params={'name': 'state.jsonl'},
                                    headers={'Content-Type': 'application/x-ndjson'})
        self.assertEqual(response.status_code, 200, response.text)
        summary = response.json()
        self.assertEqual(summary['rowCount'], 5)
        self.assertEqual(summary['source']['fileName'], 'state.jsonl')
        self.assertEqual(summary['counts']['goldRows'], 2)
        self.assertEqual(summary['counts']['hpRows'], 2)

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertTrue(data['imported'])
        self.assertEqual(data['replayId'], self.replay_id)
        self.assertEqual(len(data['rows']), 5)
        self.assertEqual(data['rows'][0]['player'], '胡不喜#')
        self.assertEqual(data['rows'][0]['sources'], ROWS[0]['sources'])
        self.assertEqual(data['rows'][0]['row_kind'], 'state')
        self.assertEqual(data['rows'][0]['note'], ROWS[0]['note'])
        self.assertIsNone(data['rows'][3]['gold'])
        self.assertEqual(data['source']['sha256'], hashlib.sha256(self.payload).hexdigest())
        self.assertEqual(data['source']['size'], len(self.payload))
        self.assertEqual(data['source']['rowCount'], 5)
        self.assertEqual(data['confidence']['gold'], 'engine_measured')
        self.assertEqual(data['confidence']['kills'], 'engine_measured')
        self.assertEqual(data['confidence']['deaths'], 'engine_measured')
        self.assertEqual(data['confidence']['assists'], 'engine_measured')
        self.assertEqual(data['confidence']['level'], 'engine_measured')
        self.assertEqual(data['confidence']['hp_current'], 'measured')
        self.assertEqual(data['confidence']['hp_max'], 'measured')
        self.assertEqual(data['confidence']['hp_ratio'], 'measured')
        self.assertEqual(data['confidence']['abs_hp_estimate'], 'unknown')
        self.assertEqual(data['confidence']['positions'], 'estimated')
        self.assertIn('arena_stats', data['confidenceNote'])
        counts = data['counts']
        self.assertEqual(counts['totalRows'], 5)
        self.assertEqual(counts['stateRows'], 3)
        self.assertEqual(counts['goldRows'], 2)
        self.assertEqual(counts['kdaRows'], 2)
        self.assertEqual(counts['levelRows'], 2)
        self.assertEqual(counts['hpRows'], 2)
        self.assertEqual(counts['engineRows'], 2)
        self.assertEqual(counts['eventOnlyRows'], 2)
        self.assertEqual(counts['checkpointTimes'], [94.858, 449.219])
        self.assertTrue(any('17.8%' in note for note in data['notes']))

    def test_02_json_wrapper_import_replaces_previous_rows(self):
        self.assertEqual(self.import_rows(json={'rows': ROWS}).status_code, 200)
        wrapper = json.dumps({'rows': ROWS[:2], 'fileName': 'checkpoints.json'},
                             ensure_ascii=False).encode()
        response = self.import_rows(content=wrapper, headers={'Content-Type': 'application/json'})
        self.assertEqual(response.status_code, 200, response.text)
        data = self.client.get(self.url).json()
        self.assertEqual(len(data['rows']), 2)
        self.assertEqual(data['source']['fileName'], 'checkpoints.json')
        self.assertEqual(data['source']['sha256'], hashlib.sha256(wrapper).hexdigest())

    def test_03_invalid_rows_are_rejected_without_overwriting(self):
        self.assertEqual(self.import_rows(content=self.payload).status_code, 200)
        invalid_values = [
            {'gold': 'many'},
            {'hp_ratio': 'high'},
            {'level': None, 'kills': True},
        ]
        for patch_value in invalid_values:
            row = dict(ROWS[0], **patch_value)
            response = self.import_rows(json={'rows': [row]})
            self.assertEqual(response.status_code, 422, (patch_value, response.text))
        nan_body = b'{"rows":[{"time_s":1,"player":"x","hp_max":NaN}]}'
        response = self.import_rows(content=nan_body, headers={'Content-Type': 'application/json'})
        self.assertEqual(response.status_code, 422, response.text)
        response = self.import_rows(json={'rows': ['not-an-object']})
        self.assertEqual(response.status_code, 422, response.text)
        response = self.import_rows(content=b'{"time_s":1,"player":"x"}\nnot json\n',
                                    headers={'Content-Type': 'application/x-ndjson'})
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn('第 2 行', response.json()['detail'])
        data = self.client.get(self.url).json()
        self.assertEqual(len(data['rows']), 5)
        self.assertEqual(data['rows'][0]['gold'], 679)

    def test_04_unknown_replay_returns_404(self):
        url = '/api/replays/missing-replay-id/checkpoints'
        self.assertEqual(self.client.post(url, json={'rows': ROWS}).status_code, 404)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.delete(url).status_code, 404)

    def test_05_absent_checkpoint_returns_404(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)
        self.assertIn('尚未导入', response.json()['detail'])

    def test_06_oversized_payload_is_rejected(self):
        with patch.object(server, 'MAX_CHECKPOINT_ROWS', 4):
            response = self.import_rows(json={'rows': ROWS})
        self.assertEqual(response.status_code, 413, response.text)
        self.assertIn('上限', response.json()['detail'])
        self.assertEqual(self.client.get(self.url).status_code, 404)

        with patch.object(server, 'MAX_CHECKPOINT_BYTES', 16):
            response = self.import_rows(content=self.payload)
        self.assertEqual(response.status_code, 413, response.text)
        self.assertIn('64 MB', response.json()['detail'])

    def test_07_delete_removes_checkpoint_rows(self):
        self.assertEqual(self.import_rows(json={'rows': ROWS}).status_code, 200)
        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {'ok': True, 'replayId': self.replay_id})
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.delete(self.url).status_code, 404)

    def test_08_import_does_not_rewrite_replay_report(self):
        before = self.client.get(f'/api/replays/{self.replay_id}').json()
        self.assertEqual(self.import_rows(json={'rows': ROWS}).status_code, 200)
        after = self.client.get(f'/api/replays/{self.replay_id}').json()
        self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main()
