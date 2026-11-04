import copy
import json
import sqlite3
import unittest
import uuid
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from bp_input import validate_bp
from studio_api import create_studio_router
from studio_analysis import StudioRepository
from tests.test_analysis_data import make_db, bundle, C_BLUE, C_RED


BP = {'bans': {'left': ['大乔', ''], 'right': ['镜']},
      'picks': {'left': ['', '关羽'], 'right': ['吕布']}, 'firstPick': 'right', 'notes': '截图核对'}


class BpInputTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1] / 'test-results' / ('bp-' + uuid.uuid4().hex)
        self.root.mkdir(parents=True)
        self.db = self.root / 'training.sqlite3'
        make_db(self.db)
        with sqlite3.connect(self.db) as c:
            c.execute('CREATE TABLE revisions(match_id TEXT,saved_at REAL,body TEXT)')
        self.matches = self.root / 'matches'
        self.matches.mkdir()
        self.original = bundle('independent', '2026-10-09', 900, C_BLUE, C_RED)
        self.original['match'].update(ownCamp='blue', winnerCamp=None)
        self.path = self.matches / 'original.json'
        self.path.write_text(json.dumps(self.original), encoding='utf-8')
        app = FastAPI()
        app.include_router(create_studio_router(self.db, self.matches, self.root / 'imports'))
        self.client = TestClient(app)

    def test_order_gaps_and_rejections(self):
        self.assertEqual(validate_bp(BP)['picks']['left'], ['', '关羽'])
        for kind in ['repeat', 'banned-pick', 'too-many', 'wrong-side']:
            bp = copy.deepcopy(BP)
            if kind == 'repeat': bp['picks']['right'] = ['关羽']
            if kind == 'banned-pick': bp['picks']['right'] = ['镜']
            if kind == 'too-many': bp['bans']['left'] = ['']*5
            if kind == 'wrong-side': bp['firstPick'] = 'blue'
            with self.assertRaises(ValueError): validate_bp(bp)

    def test_bundle_amendment_preserves_evidence_and_unknown_results(self):
        response = self.client.post('/api/studio/bp/independent', json={'bp': BP, 'expectedBp': {}})
        self.assertEqual(response.status_code, 200, response.text)
        saved = json.loads(self.path.read_text(encoding='utf-8'))
        saved['match'].pop('bp')
        self.assertEqual(saved, self.original)
        self.assertEqual(len(list((self.root / 'bp-history').glob('*.json'))), 1)
        self.assertEqual(self.client.get('/api/studio/bp/independent').json()['bp'], BP)
        summary = self.client.get('/api/studio/view/bp').json()
        self.assertEqual(summary['matchesWithBp'], 1)
        self.assertTrue(all(item['hero'] for item in summary['bans']))
        self.assertEqual(summary['ownPicks'][0]['count'], 1)
        self.assertIsNone(summary['ownPicks'][0]['winRate'])
        self.assertTrue(all(item['n'] == 0 for item in summary['orderEffect']))
        conflict = self.client.post('/api/studio/bp/independent', json={'bp': BP, 'expectedBp': {}})
        self.assertEqual(conflict.status_code, 409)

    def test_existing_database_match_only_amends_bp(self):
        with sqlite3.connect(self.db) as c:
            before = json.loads(c.execute("SELECT body FROM matches WHERE id='A'").fetchone()[0])
        response = self.client.post('/api/studio/bp/db-A', json={'bp': BP})
        self.assertEqual(response.status_code, 200, response.text)
        with sqlite3.connect(self.db) as c:
            after = json.loads(c.execute("SELECT body FROM matches WHERE id='A'").fetchone()[0])
            self.assertEqual(c.execute('SELECT COUNT(*) FROM revisions').fetchone()[0], 1)
        self.assertEqual(after['players'], before['players'])
        self.assertEqual(after['status'], before['status'])
        self.assertEqual(after['bp'], BP)
        self.assertEqual(self.client.post('/api/studio/bp/absent', json={'bp': BP}).status_code, 404)

    def test_unknown_team_can_still_contribute_bans(self):
        repo = StudioRepository(self.db, self.matches, self.root / 'imports')
        data = repo.get()
        data['matches'] = [{'key':'x','bp':BP,'ownCamp':None,'winner':None,'players':[], 'source':'bundle', 'sources':['bundle']}]
        repo._selected_matches = lambda filters: (data['matches'], [])
        result = repo.bp_summary({})
        self.assertEqual(result['matchesWithBp'], 1)
        self.assertEqual(len(result['bans']), 2)
        self.assertEqual(result['ownPicks'], [])

    def test_bundle_amendment_keeps_channel_draft_in_sync(self):
        import channel_store
        channel = channel_store.blank()
        channel.update(id='channel-x', revision=1)
        channel['saved'] = {'status': 'saved', 'bundleKey': 'independent'}
        with sqlite3.connect(self.db) as c:
            c.execute('CREATE TABLE channels(id TEXT PRIMARY KEY,revision INTEGER,body TEXT,updated_at REAL)')
            c.execute('INSERT INTO channels VALUES(?,?,?,0)', ('channel-x',1,json.dumps(channel)))
        response = self.client.post('/api/studio/bp/independent', json={'bp': BP})
        self.assertEqual(response.status_code, 200, response.text)
        with sqlite3.connect(self.db) as c:
            body = json.loads(c.execute('SELECT body FROM channels').fetchone()[0])
        self.assertEqual(body['match']['bp'], BP)
        self.assertEqual(body['draft']['match']['bp'], BP)
        self.assertEqual(body['revision'], 2)
