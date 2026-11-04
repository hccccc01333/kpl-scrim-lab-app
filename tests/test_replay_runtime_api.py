import json
import os
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault('TRAINING_DB', str(ROOT / 'test-results' / f'test-runtime-{uuid.uuid4().hex}.sqlite3'))

from fastapi.testclient import TestClient
from replay_fixtures import abc_fixture, ope_fixture
from runtime_data import MAX_BYTES
from server import app


def player(player_id, camp, slot, hero, **stats):
    value = {'playerId': player_id, 'camp': camp, 'slot': slot, 'heroId': hero}
    value.update(stats)
    return value


def runtime_bytes():
    rows = [
        {'type': 'meta', 'schema': 'kpl-runtime-v1', 'source': 'fixture', 'gameVersion': '12.1.1.23'},
    ]
    for frame, time, scale in ((0, 0, 0), (120, 120, 1)):
        blue = [
            player('b1', 'blue', 0, 101, kills=2 * scale, deaths=1 * scale, assists=3 * scale,
                   gold=1200 * scale, exp=2400 * scale, damageDealt=6000 * scale,
                   damageTaken=3000 * scale, towerDamage=100 * scale, visionScore=10 * scale),
            player('b2', 'blue', 1, 102, kills=3 * scale, deaths=0, assists=1 * scale,
                   gold=800 * scale, exp=1600 * scale, damageDealt=3000 * scale,
                   damageTaken=2000 * scale, towerDamage=0, visionScore=8 * scale),
            player('b3', 'blue', 2, 103, kills=0, deaths=2 * scale, assists=2 * scale,
                   gold=600 * scale, exp=1200 * scale, damageDealt=1000 * scale,
                   damageTaken=4000 * scale, towerDamage=0, visionScore=6 * scale),
            player('b4', 'blue', 3, 104, kills=0, deaths=1 * scale, assists=4 * scale,
                   gold=600 * scale, exp=1200 * scale, damageDealt=1000 * scale,
                   damageTaken=2500 * scale, towerDamage=0, visionScore=5 * scale),
            player('b5', 'blue', 4, 105, kills=0, deaths=0, assists=5 * scale,
                   gold=400 * scale, exp=800 * scale, damageDealt=1000 * scale,
                   damageTaken=1000 * scale, towerDamage=0, visionScore=4 * scale),
        ]
        red = [
            player(f'r{index + 1}', 'red', index, 200 + index, kills=1 if index < 2 else 0,
                   deaths=1 * scale, assists=0, gold=500 * scale, exp=1000 * scale,
                   damageDealt=1000 * scale, damageTaken=1000 * scale, towerDamage=0,
                   visionScore=5 * scale)
            for index in range(5)
        ]
        rows.append({'type': 'frame', 'frame': frame, 'time': time, 'players': blue + red})
    rows.extend([
        {'type': 'event', 'frame': 30, 'time': 30, 'event': 'skill_use', 'playerId': 'b1', 'camp': 'blue', 'skillSlot': 1},
        {'type': 'event', 'frame': 31, 'time': 31, 'event': 'skill_hit', 'playerId': 'b1', 'camp': 'blue', 'skillSlot': 1},
        {'type': 'event', 'frame': 32, 'time': 32, 'event': 'kill', 'playerId': 'b1', 'targetId': 'r1', 'camp': 'blue'},
    ])
    return ('\n'.join(json.dumps(row, ensure_ascii=False) for row in rows) + '\n').encode()


class ReplayRuntimeApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, base_url='http://localhost')
        uploaded = cls.client.post('/api/replays/files?name=fixture.abc', content=abc_fixture())
        assert uploaded.status_code == 200, uploaded.text
        cls.abc_id = uploaded.json()['id']
        imported = cls.client.post('/api/replays/import', json={'abcFileId': cls.abc_id})
        assert imported.status_code == 200, imported.text
        cls.data = runtime_bytes()

    def test_01_import_and_read_runtime(self):
        response = self.client.post(f'/api/replays/{self.abc_id}/runtime', content=self.data)
        self.assertEqual(response.status_code, 200, response.text)
        runtime = response.json()
        self.assertEqual(runtime['analysis']['coverage']['frames'], 2)
        self.assertEqual(runtime['analysis']['coverage']['players'], 10)
        self.assertEqual(runtime['analysis']['teams']['blue']['totals']['gold'], 3600)
        self.assertEqual(runtime['analysis']['events']['counts']['kill'], 1)
        self.assertEqual(runtime['analysis']['events']['skillHitRate'], 100)

        detail = self.client.get(f'/api/replays/{self.abc_id}').json()
        self.assertEqual(detail['runtime']['fileId'], runtime['fileId'])
        self.assertEqual(self.client.get(f'/api/replays/{self.abc_id}/runtime').json()['fileId'], runtime['fileId'])
        self.assertEqual(self.client.get(f'/api/replays/{self.abc_id}/runtime/file').content, self.data)
        report = self.client.get(f'/api/replays/{self.abc_id}/report').json()
        self.assertIn('runtime', report)

    def test_02_reimport_keeps_runtime(self):
        ope, _ = ope_fixture()
        uploaded = self.client.post('/api/replays/files?name=fixture.ope', content=ope)
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        result = self.client.post('/api/replays/import', json={
            'abcFileId': self.abc_id, 'opeFileId': uploaded.json()['id'],
        })
        self.assertEqual(result.status_code, 200, result.text)
        self.assertIn('runtime', result.json()['report'])
        detail = self.client.get(f'/api/replays/{self.abc_id}').json()
        self.assertIn('runtime', detail)
        self.assertEqual(self.client.get(f'/api/replays/{self.abc_id}/runtime').status_code, 200)

    def test_03_invalid_runtime(self):
        bad = b'{"type":"event","frame":1,"event":"not-a-real-event"}\n'
        response = self.client.post(f'/api/replays/{self.abc_id}/runtime', content=bad)
        self.assertEqual(response.status_code, 422)
        empty = self.client.post(f'/api/replays/{self.abc_id}/runtime', content=b'')
        self.assertEqual(empty.status_code, 422)
        missing = self.client.post('/api/replays/0' * 64 + '/runtime', content=self.data)
        self.assertEqual(missing.status_code, 404)
        oversized = self.client.post(f'/api/replays/{self.abc_id}/runtime', content=b'x' * (MAX_BYTES + 1))
        self.assertEqual(oversized.status_code, 413)
        no_rows = self.client.post(f'/api/replays/{self.abc_id}/runtime', content=b'{"type":"meta","schema":"kpl-runtime-v1"}\n')
        self.assertEqual(no_rows.status_code, 422)

    def test_04_backup_and_restore_keep_runtime(self):
        backup = self.client.get('/api/backup')
        self.assertEqual(backup.status_code, 200)
        value = backup.json()
        entry = next(r for r in value['replays'] if r['abcFileId'] == self.abc_id)
        self.assertTrue(entry['runtimeFileId'])
        restored = self.client.post('/api/restore', json=value)
        self.assertEqual(restored.status_code, 200, restored.text)
        runtime = self.client.get(f'/api/replays/{self.abc_id}/runtime')
        self.assertEqual(runtime.status_code, 200)
        self.assertEqual(runtime.json()['analysis']['coverage']['players'], 10)

    def test_05_runtime_missing_on_fresh_replay(self):
        another_bytes = bytearray(abc_fixture())
        start = 674 + 9 * 1517
        another_bytes[start + 771:start + 775] = (149).to_bytes(4, 'big')
        uploaded = self.client.post('/api/replays/files?name=another.abc', content=bytes(another_bytes))
        self.assertEqual(uploaded.status_code, 200)
        another = uploaded.json()['id']
        self.client.post('/api/replays/import', json={'abcFileId': another})
        missing = self.client.get(f'/api/replays/{another}/runtime')
        self.assertEqual(missing.status_code, 404)


if __name__ == '__main__':
    unittest.main()
