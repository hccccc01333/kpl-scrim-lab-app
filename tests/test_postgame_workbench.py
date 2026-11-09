import io
import json
import os
import unittest
import uuid
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient
from PIL import Image

import server

OUT = Path(__file__).resolve().parents[1] / 'test-results'
OUT.mkdir(exist_ok=True)


def player(side, slot, nickname, kills=2, deaths=3, assists=4, gold=9000):
    return {
        'side': side, 'slot': slot,
        'nickname': {'value': nickname, 'raw': nickname, 'confidence': .99, 'box': None},
        'hero': {'value': '虞姬' if side == 'left' else '后羿', 'raw': '虞姬', 'confidence': .95, 'box': None},
        'heroStatus': 'exact', 'heroCandidates': [], 'heroReadings': [],
        'rating': {'value': 6.0 + slot / 10, 'raw': '6.0', 'confidence': .99, 'box': None},
        'title': None, 'mvp': False,
        'fields': {
            'kills': {'value': kills, 'raw': str(kills), 'confidence': .9, 'box': None},
            'deaths': {'value': deaths, 'raw': str(deaths), 'confidence': .9, 'box': None},
            'assists': {'value': assists, 'raw': str(assists), 'confidence': .9, 'box': None},
            'gold': {'value': gold, 'raw': '9.0k', 'confidence': .9, 'box': None},
            'damageDealt': {'value': 50000, 'raw': '50.0k', 'confidence': .9, 'box': None},
        },
        'shares': {'outputShare': {'value': 20.0, 'raw': '20%', 'confidence': .9, 'box': None}},
        'sources': ['data'],
    }


def result(page='data', score=None, nicknames=None, warnings=None):
    nicknames = nicknames or {('left', i): f'选手{i}' for i in range(5)} | {('right', i): f'对手{i}' for i in range(5)}
    players = [player(side, slot, nicknames[(side, slot)]) for side in ('left', 'right') for slot in range(5)]
    return {
        'schema': 'kpl-postgame-screenshot-v1',
        'version': 'postgame-tabbed-v3', 'layout': 'postgame-tabbed-v3',
        'file': f'{page}.png', 'pageType': page, 'tab': {'data': '数据', 'farming': '发育'}.get(page, page),
        'match': {'date': None, 'time': None, 'durationSec': None, 'mode': None, 'result': None,
                  'score': score or {'left': None, 'right': None}},
        'players': players, 'coverage': {'players': 10}, 'warnings': warnings or [],
        'crop': {'top': 0, 'bottom': 100}, 'imageSize': [320, 200],
    }


class CaptureApiTests(unittest.TestCase):
    def setUp(self):
        self.old_path = server.DB_PATH
        server.DB_PATH = OUT / f'postgame-api-{uuid.uuid4().hex}.sqlite3'
        server.init_db()
        self.client = TestClient(server.app, base_url='http://localhost')
        assert self.client.put('/api/settings', json={
            'teamName': '采集测试队', 'roster': [{'id': str(i), 'name': f'队员{i}'} for i in range(5)]}).status_code == 200

    def tearDown(self):
        server.DB_PATH = self.old_path

    def upload(self, color):
        stream = io.BytesIO()
        Image.new('RGB', (320, 200), color).save(stream, format='PNG')
        response = self.client.post('/api/images?name=capture.png', content=stream.getvalue())
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['id']

    def test_collection_ocr_cache_group_and_delete(self):
        image_id = self.upload((20, 30, 40))
        with mock.patch('server.recognize_postgame', return_value=result('data', {'left': 14, 'right': 26})) as patched:
            response = self.client.post(f'/api/postgame/images/{image_id}/ocr')
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['pageType'], 'data')
            self.assertEqual(patched.call_count, 1)
            cached = self.client.post(f'/api/postgame/images/{image_id}/ocr')
            self.assertEqual(cached.status_code, 200)
            self.assertEqual(patched.call_count, 1)
            refreshed = self.client.post(f'/api/postgame/images/{image_id}/ocr?refresh=true')
            self.assertEqual(refreshed.status_code, 200)
            self.assertEqual(patched.call_count, 2)
        collection = self.client.get('/api/postgame/images').json()
        self.assertEqual(collection['schema'], 'kpl-postgame-collection-v1')
        self.assertEqual(len(collection['images']), 1)
        self.assertEqual(collection['images'][0]['pageType'], 'data')
        self.assertEqual(len(collection['groups']), 1)
        self.assertEqual(collection['groups'][0]['pages'][0]['imageId'], image_id)
        self.assertIn('analysis', collection['groups'][0])
        self.assertIn('teams', collection['groups'][0]['analysis'])
        self.assertEqual(self.client.delete(f'/api/postgame/images/{image_id}').status_code, 200)
        self.assertEqual(self.client.delete(f'/api/postgame/images/{image_id}').status_code, 404)
        self.assertEqual(self.client.get('/api/postgame/images').json()['groups'], [])

    def test_fixed_capture_guides_are_served(self):
        names = ('score-equipment', 'score-kda', 'data', 'output', 'survival', 'farming', 'team')
        for name in names:
            response = self.client.get(f'/assets/capture-guide/{name}.svg')
            self.assertEqual(response.status_code, 200, name)
            self.assertIn(b'<svg', response.content)
        # 旧版截图页已归档；V3 素材页由 v3/public/sources-page.js 提供。

    @unittest.skipUnless((OUT.parent / 'data' / 'screenshots' / 'samples' / '01-score.png').is_file(),
                        '缺少真实示例截图')
    def test_demo_data_can_be_loaded_and_cleared(self):
        with mock.patch('server.recognize_postgame', side_effect=[result('data', {'left': 14, 'right': 26}) for _ in range(7)]):
            response = self.client.post('/api/postgame/demo')
            self.assertEqual(response.status_code, 200, response.text)
            collection = response.json()
            self.assertEqual(len(collection['images']), 7)
            self.assertTrue(all(image['demo'] for image in collection['images']))
            self.assertTrue(collection['groups'])
            self.assertTrue(all(group['demo'] for group in collection['groups']))
            self.assertIn('analysis', collection['groups'][0])
        cleared = self.client.delete('/api/postgame/demo')
        self.assertEqual(cleared.status_code, 200, cleared.text)
        self.assertEqual(cleared.json()['removed'], 7)
        self.assertEqual(self.client.get('/api/postgame/images').json()['images'], [])

    def test_different_matches_stay_in_different_groups(self):
        one = self.upload((41, 50, 60))
        two = self.upload((61, 70, 80))
        left_names = {('left', i): f'甲{i}' for i in range(5)}
        right_names = {('right', i): f'乙{i}' for i in range(5)}
        other_names = {('left', i): f'丙{i}' for i in range(5)} | {('right', i): f'丁{i}' for i in range(5)}
        with mock.patch('server.recognize_postgame', side_effect=[
                result('data', {'left': 14, 'right': 26}, left_names | right_names),
                result('farming', {'left': 33, 'right': 34}, other_names)]):
            self.assertEqual(self.client.post(f'/api/postgame/images/{one}/ocr').status_code, 200)
            self.assertEqual(self.client.post(f'/api/postgame/images/{two}/ocr').status_code, 200)
        collection = self.client.get('/api/postgame/images').json()
        self.assertEqual(len(collection['groups']), 2)
        self.assertEqual(sum(len(group['pages']) for group in collection['groups']), 2)

    def test_backup_restores_postgame_results(self):
        image_id = self.upload((90, 100, 110))
        with mock.patch('server.recognize_postgame', return_value=result('data', {'left': 14, 'right': 26})):
            self.assertEqual(self.client.post(f'/api/postgame/images/{image_id}/ocr').status_code, 200)
        backup = self.client.get('/api/backup').json()
        self.assertTrue(any(item['id'] == image_id for item in backup['postgameImages']))
        old_path = server.DB_PATH
        try:
            server.DB_PATH = OUT / f'postgame-restore-{uuid.uuid4().hex}.sqlite3'
            server.init_db()
            restored = self.client.post('/api/restore', json=backup)
            self.assertEqual(restored.status_code, 200, restored.text)
            collection = self.client.get('/api/postgame/images').json()
            self.assertEqual(len(collection['images']), 1)
            self.assertEqual(collection['images'][0]['id'], image_id)
        finally:
            server.DB_PATH = old_path


if __name__ == '__main__':
    unittest.main()
