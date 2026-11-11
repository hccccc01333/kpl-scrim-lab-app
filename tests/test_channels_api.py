import io
import json
import unittest
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

import server
from tests.collection_fixtures import complete_collection
from collection_contract import PAGE_TYPES
from analysis_data import AnalysisRepository

OUT = Path(__file__).resolve().parents[1] / 'test-results'
OUT.mkdir(exist_ok=True)


def field(value):
    return {'value': value, 'raw': str(value), 'confidence': .9, 'box': None}


def postgame_result():
    players = []
    for side in ('left', 'right'):
        for slot in range(5):
            players.append({
                'side': side, 'slot': slot,
                'nickname': {'value': f'{side}{slot}', 'raw': f'{side}{slot}', 'confidence': .9},
                'hero': {'value': '虞姬' if side == 'left' else '后羿', 'raw': '虞姬', 'confidence': .9},
                'heroStatus': 'exact', 'heroCandidates': [], 'heroReadings': [],
                'rating': field(8.0), 'title': None, 'mvp': False,
                'fields': {'kills': field(2), 'deaths': field(3), 'assists': field(4),
                           'gold': field(9000), 'damageDealt': field(50000), 'damageTaken': field(30000),
                           'participation': field(50)},
                'shares': {}, 'sources': ['data'],
            })
    return {'schema': 'kpl-postgame-screenshot-v1', 'version': 'postgame-tabbed-v3',
            'layout': 'postgame-tabbed-v3', 'file': 'data.png', 'pageType': 'data', 'tab': '数据',
            'match': {'date': '2026-06-17', 'time': None, 'durationSec': 1132, 'mode': None,
                      'result': None, 'score': {'left': 14, 'right': 26}},
            'players': players, 'coverage': {}, 'warnings': []}


class ChannelApiTests(unittest.TestCase):
    def setUp(self):
        self.old_path = server.DB_PATH
        self.old_matches = server.MATCHES_DIR
        server.MATCHES_DIR = OUT / ('channel-matches-' + uuid.uuid4().hex)
        self.image_counter = 0
        server.DB_PATH = OUT / f'channel-api-{uuid.uuid4().hex}.sqlite3'
        server.init_db()
        self.client = TestClient(server.app, base_url='http://localhost')
        self.client.put('/api/settings', json={'teamName': '通道测试队', 'roster': []})
        self.channel = self.client.post('/api/channels', json={'match': {
            'date': '2026-06-17', 'opponent': '测试对手', 'session': '通道验收'}}).json()
        self.channel_id = self.channel['id']

    def tearDown(self):
        server.DB_PATH = self.old_path
        server.MATCHES_DIR = self.old_matches

    def upload_image(self):
        stream = io.BytesIO()
        self.image_counter += 1
        Image.new('RGB', (320, 200), (10, 20, self.image_counter)).save(stream, format='PNG')
        response = self.client.post('/api/images?name=shot.png', content=stream.getvalue())
        return response.json()['id']

    def test_empty_channel_is_rejected(self):
        response = self.client.post('/api/channels', json={'match': {'date': '', 'opponent': '', 'session': ''}})
        self.assertEqual(response.status_code, 400)
        self.assertIn('至少填写', response.json()['detail'])

    def test_create_table_video_replay_screenshot_review_and_save(self):
        csv = (Path(__file__).resolve().parents[1] / 'web/capture-guide/match-example.csv').read_text(encoding='utf-8-sig').replace('EXAMPLE-请替换','api-match').replace('2026-11-04','2026-06-17')
        response = self.client.post(f'/api/channels/{self.channel_id}/table?name=t.csv', content=csv.encode())
        self.assertEqual(response.status_code, 200, response.text)
        channel = response.json()
        self.assertEqual(channel['sources']['table']['status'], 'parsed')
        self.assertGreater(channel['sources']['table']['summary']['rows'], 0)

        report = {'lineups': {'blue': [{'hero': '虞姬', 'nickname': 'left0'}],
                              'red': [{'hero': '后羿', 'nickname': 'right0'}]},
                  'coverage': {}}
        response = self.client.post(f'/api/channels/{self.channel_id}/video?name=v.json', content=json.dumps(report).encode())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['sources']['video']['status'], 'completed')

        with server.db() as c:
            c.execute('INSERT INTO replays(id,abc_file_id,ope_file_id,body,created_at,updated_at) VALUES(?,?,?,?,?,?)',
                      ('replay-1', 'abc', None,
                       json.dumps({'blocks': [{'heroName': '虞姬', 'heroId': 1, 'order': 0},
                                              {'heroName': '后羿', 'heroId': 2, 'order': 1}],
                                   'header': {'versions': ['test'], 'localHeroName': '虞姬'}}),
                       0, 0))
        response = self.client.post(f'/api/channels/{self.channel_id}/replay', json={'replayId': 'replay-1'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['sources']['replay']['status'], 'parsed')

        image_ids=[]
        for page_type in PAGE_TYPES:
            image_id=self.upload_image();image_ids.append(image_id)
            result=postgame_result();result['pageType']=page_type
            with server.db() as db:
                db.execute('INSERT INTO postgame_images(id,result,updated_at) VALUES(?,?,?)',(image_id,json.dumps(result),0))
        response=self.client.post(f'/api/channels/{self.channel_id}/screenshot',json={'imageIds':image_ids})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['sources']['screenshot']['imageIds'],image_ids)
        with server.db() as db:
            channel=server._load_channel(db,self.channel_id)
            complete_collection(channel)
            server._save_channel(db,channel)

        response = self.client.post(f'/api/channels/{self.channel_id}/review',
                                    json={'reviewedBy': '教练甲', 'notes': '已核对'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['review']['reviewedBy'], '教练甲')

        response = self.client.post(f'/api/channels/{self.channel_id}/save')
        self.assertEqual(response.status_code, 200, response.text)
        bundle = response.json()['bundle']
        self.assertEqual(bundle['schema'], 'kpl-match-data-v1')
        self.assertTrue((server.MATCHES_DIR / f'channel-{self.channel_id}.json').is_file())
        repository = AnalysisRepository(Path(server.DB_PATH), server.MATCHES_DIR, Path('data/imports'))
        loaded = [item for item in repository.get()['matches'] if item.get('bundleKey') == bundle['match']['key']]
        self.assertEqual(len(loaded), 1)
        self.assertEqual(len(loaded[0]['players']), 10)

        listing = self.client.get('/api/channels').json()
        self.assertEqual(len(listing['channels']), 1)
        self.assertTrue(listing['channels'][0]['review']['reviewedBy'])

    def test_missing_materials_block_review_and_save(self):
        review = self.client.post(f'/api/channels/{self.channel_id}/review',json={'reviewedBy':'tester'})
        save = self.client.post(f'/api/channels/{self.channel_id}/save')
        self.assertEqual(review.status_code,400)
        self.assertEqual(save.status_code,400)
        self.assertIn('王者营地',review.json()['detail'])
        self.assertFalse(server.MATCHES_DIR.exists())

    def test_bad_sheet_is_rejected_before_attachment(self):
        response=self.client.post(f'/api/channels/{self.channel_id}/table?name=wrong.csv',content='随意表头\n不能导入'.encode())
        self.assertEqual(response.status_code,400)
        self.assertIn('请使用本项目',response.json()['detail'])
        channel=self.client.get(f'/api/channels/{self.channel_id}').json()
        self.assertEqual(channel['sources']['table']['files'],[])

    def test_backup_contains_channels(self):
        self.client.post(f'/api/channels/{self.channel_id}/review', json={'reviewedBy': '教练乙'})
        backup = self.client.get('/api/backup').json()
        self.assertTrue(any(item['id'] == self.channel_id for item in backup['channels']))
        old_path = server.DB_PATH
        try:
            server.DB_PATH = OUT / f'channel-restore-{uuid.uuid4().hex}.sqlite3'
            server.init_db()
            first_channel = self.channel_id
            restored = self.client.post('/api/restore', json=backup)
            self.assertEqual(restored.status_code, 200, restored.text)
            channels = self.client.get('/api/channels').json()['channels']
            self.assertTrue(any(item['id'] == first_channel for item in channels))
        finally:
            server.DB_PATH = old_path


if __name__ == '__main__':
    unittest.main()
