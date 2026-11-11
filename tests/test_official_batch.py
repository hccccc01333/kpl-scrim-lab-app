import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['TRAINING_DB'] = str(ROOT / 'test-results' / f'test-official-batch-{uuid.uuid4().hex}.sqlite3')

from fastapi.testclient import TestClient

from server import app, camp_replay


def fake_import(url, force=False):
    seq = '1793606215' if 'abc' in url or 'good' in url else '1793606216'
    meta = {'id': f'camp-{seq}', 'gameSeq': seq, 'battleType': '16', 'pvpType': '5',
            'match': {'winCamp': '1', 'durationSec': 693.0,
                      'teamGold': {'blue': 41021, 'red': 29266}, 'goldPoints': 23}}
    return {'id': f'camp-{seq}', 'meta': meta, 'cached': True}


class OfficialBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, base_url='http://localhost')

    def test_split_dedupe_and_summary(self):
        """同一批里重复链接去重；中文标点不混进 URL；返回模式/胜方/时长摘要。"""
        text = ('https://cu.qq.com/abc 王者营地分享\n'
                'https://cu.qq.com/abc\n'
                'https://camp.qq.com/h5/webdist/battle-replay/index.html'
                '?gameseq=1793606216&gamesvrentity=2&relaysvrentity=3&playerid=4，')
        with mock.patch.object(camp_replay, 'import_link', side_effect=fake_import):
            response = self.client.post('/api/official/replays/batch', json={'text': text})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['schema'], 'camp-replay-batch-v1')
        self.assertEqual(data['total'], 2)
        self.assertEqual(data['imported'], 2)
        self.assertEqual(data['failed'], 0)
        first = data['items'][0]
        self.assertTrue(first['ok'])
        self.assertEqual(first['gameSeq'], '1793606215')
        self.assertEqual(first['battleType'], '16')
        self.assertTrue(first['cached'])
        self.assertEqual(data['items'][1]['gameSeq'], '1793606216')

    def test_errors_do_not_break_batch(self):
        """一条失败不影响其它条目，错误信息原样返回。"""
        text = 'https://cu.qq.com/good\nhttps://cu.qq.com/bad'

        def flaky(url, force=False):
            if 'bad' in url:
                raise camp_replay.CampReplayError('短链没有跳转目标（HTTP 404）')
            return fake_import(url)

        with mock.patch.object(camp_replay, 'import_link', side_effect=flaky):
            response = self.client.post('/api/official/replays/batch', json={'text': text})
        data = response.json()
        self.assertEqual(data['imported'], 1)
        self.assertEqual(data['failed'], 1)
        self.assertFalse(data['items'][1]['ok'])
        self.assertIn('没有跳转', data['items'][1]['error'])

    def test_empty_text_and_over_limit(self):
        self.assertEqual(
            self.client.post('/api/official/replays/batch', json={'text': '没有链接的内容'}).status_code, 400)
        self.assertEqual(
            self.client.post('/api/official/replays/batch', json={'text': '   '}).status_code, 400)
        many = '\n'.join(f'https://cu.qq.com/{index:02d}' for index in range(21))
        response = self.client.post('/api/official/replays/batch', json={'text': many})
        self.assertEqual(response.status_code, 400)
        self.assertIn('20', response.json().get('detail', ''))


if __name__ == '__main__':
    unittest.main()
