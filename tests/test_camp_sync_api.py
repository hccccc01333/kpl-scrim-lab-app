import os
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = ROOT / 'test-results' / f'camp-api-{uuid.uuid4().hex}'
TMP.mkdir(parents=True, exist_ok=True)
os.environ['TRAINING_DB'] = str(TMP / 'training.sqlite3')
os.environ['CAMP_CONFIG_FILE'] = str(TMP / 'camp_config.json')
os.environ['CAMP_DETAIL_DIR'] = str(TMP / 'camp_details')
os.environ['CAMP_SYNC_STATE'] = str(TMP / 'camp_sync_state.json')

from fastapi.testclient import TestClient

from server import app


class CampConfigTests(unittest.TestCase):
    """选手白名单的清洗、持久化与同步门槛；不打真实营地接口。"""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, base_url='http://localhost')

    def test_config_roundtrip_and_validation(self):
        response = self.client.post('/api/camp/config', json={'players': [
            {'nickname': '队长', 'campUserId': '540599032'},
            {'nickname': '坏', 'campUserId': 'not-a-number'},
            'not-a-dict',
        ]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([p['campUserId'] for p in response.json()['players']], ['540599032'])
        stored = self.client.get('/api/camp/config').json()
        self.assertEqual(stored['players'][0]['nickname'], '队长')

    def test_sync_requires_whitelist(self):
        self.client.post('/api/camp/config', json={'players': []})
        response = self.client.post('/api/camp/sync')
        self.assertEqual(response.status_code, 400)
        self.assertIn('选手清单', response.json()['detail'])

    def test_status_shapes(self):
        auth = self.client.get('/api/camp/auth').json()
        self.assertIn('authorized', auth)
        status = self.client.get('/api/camp/sync').json()
        for key in ('running', 'result', 'error', 'detailsCount', 'config', 'auth'):
            self.assertIn(key, status)
        self.assertFalse(status['running'])


if __name__ == '__main__':
    unittest.main()
