import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = ROOT / 'test-results' / f'camp-api-{uuid.uuid4().hex}'
TMP.mkdir(parents=True, exist_ok=True)
os.environ['TRAINING_DB'] = str(TMP / 'training.sqlite3')
os.environ['CAMP_CONFIG_FILE'] = str(TMP / 'camp_config.json')
os.environ['CAMP_DETAIL_DIR'] = str(TMP / 'camp_details')
os.environ['CAMP_SYNC_STATE'] = str(TMP / 'camp_sync_state.json')

from fastapi.testclient import TestClient

import camp_replay
from server import app


def fake_import(url, force=False):
    meta = {'id': 'camp-1793606215', 'gameSeq': '1793606215',
            'match': {'winCamp': '1', 'durationSec': 693.0}}
    return {'id': 'camp-1793606215', 'meta': meta, 'cached': True}


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
        response = self.client.post('/api/camp/sync', json={'entries': []})
        self.assertEqual(response.status_code, 400)
        self.assertIn('勾选', response.json()['detail'])

    def test_status_shapes(self):
        auth = self.client.get('/api/camp/auth').json()
        self.assertIn('authorized', auth)
        status = self.client.get('/api/camp/sync').json()
        for key in ('running', 'result', 'error', 'detailsCount', 'config', 'auth'):
            self.assertIn(key, status)
        self.assertFalse(status['running'])

    def test_resolve_extracts_user_id_from_share_link(self):
        """分享链接（含 mp-redirect 形态）直接解出营地 ID，不用人工抄。"""
        response = self.client.post('/api/camp/resolve', json={'url':
            'https://camp.qq.com/h5/webdist/mp-redirect/index.html?userId=540599032'
            '&gameSeq=1793795458&battleType=12&gameSvrId=108724&relaySvrId=1260446482'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['userId'], '540599032')
        self.assertEqual(response.json()['gameSeq'], '1793795458')

    def test_resolve_rejects_non_camp_links(self):
        response = self.client.post('/api/camp/resolve', json={'url': 'https://example.com/x'})
        self.assertEqual(response.status_code, 400)

    def test_batch_items_carry_share_user_id(self):
        """批量导入顺便带回分享者的营地 ID，供一键加入同步清单。"""
        text = ('https://camp.qq.com/h5/webdist/battle-replay/index.html?gameseq=1793606215'
                '&gamesvrentity=2&relaysvrentity=3&userId=540599032')
        with mock.patch.object(camp_replay, 'import_link', side_effect=fake_import):
            response = self.client.post('/api/official/replays/batch', json={'text': text})
        self.assertEqual(response.status_code, 200)
        item = response.json()['items'][0]
        self.assertEqual(item['shareUserId'], '540599032')


if __name__ == '__main__':
    unittest.main()
