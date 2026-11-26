"""对局改名 ↔ 战队改名/合并：双向同步的回归用例。"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'v3'))
sys.path.insert(0, str(ROOT / 'tests'))
os.environ['TRAINING_DB'] = str(ROOT / 'test-results' / f'test-rename-sync-{uuid.uuid4().hex}.sqlite3')

import analysis_data  # noqa: E402
import identity_service  # noqa: E402
import opponent_identity  # noqa: E402
import team_clusters  # noqa: E402
from test_team_clusters import panel  # noqa: E402
from workspace_store import Workspace  # noqa: E402

A = ['a1', 'a2', 'a3', 'a4', 'a5']
B = ['b1', 'b2', 'b3', 'b4', 'b5']


def setup_data(root):
    data = root / 'data'
    camp = data / 'camp_details'
    camp.mkdir(parents=True)
    for seq, players in (('101', A), ('102', B)):
        (camp / f'{seq}.json').write_text(
            json.dumps(panel(int(seq), players, f'11-{seq[-2:]} 12:00'), ensure_ascii=False),
            encoding='utf-8')
    db = data / 'training.sqlite3'
    connection = sqlite3.connect(db)
    connection.executescript('''
      CREATE TABLE settings (id INTEGER PRIMARY KEY, body TEXT NOT NULL);
      CREATE TABLE matches (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, body TEXT NOT NULL);
    ''')
    connection.execute('INSERT INTO settings VALUES (1,?)',
                       (json.dumps({'teamName': '本队', 'roster': []}, ensure_ascii=False),))
    def db_match(match_id, opponent, date):
        players = []
        for slot in range(5):
            players.append({'side': 'left', 'slot': slot, 'playerId': f'b{slot + 1}',
                            'hero': f'我方{slot}', 'kills': 3, 'deaths': 1, 'assists': 4,
                            'gold': 10000, 'damage': 30000, 'taken': 20000,
                            'participation': 60, 'rating': '12.0', 'equipment': ''})
            players.append({'side': 'right', 'slot': slot, 'playerId': None,
                            'hero': f'敌方{slot}', 'kills': 2, 'deaths': 3, 'assists': 2,
                            'gold': 9000, 'damage': 25000, 'taken': 22000,
                            'participation': 50, 'rating': '10.0', 'equipment': ''})
        return {'id': match_id, 'status': 'confirmed', 'date': date, 'opponent': opponent,
                'side': 'left', 'winner': 'left', 'duration': 18, 'scores': {'left': 12, 'right': 8},
                'players': players}

    connection.execute('INSERT INTO matches VALUES (?,1,?)',
                       ('m1', json.dumps(db_match('m1', '旧对手', '2026-11-23'), ensure_ascii=False)))
    connection.commit()
    connection.close()
    Workspace(db).ensure_schema()
    return data, camp, db


class SyncUnitTests(unittest.TestCase):
    def test_generation_bump_forces_analysis_repo_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, camp, db = setup_data(Path(tmp))
            repo = analysis_data.AnalysisRepository(db, data / 'matches', data / 'imports', camp.parent)
            first = repo.get()
            self.assertIs(first, repo.get())
            before = opponent_identity.generation()
            opponent_identity.clear_cache()
            self.assertEqual(opponent_identity.generation(), before + 1)
            second = repo.get()
            self.assertIsNot(second, first)

    def test_apply_to_matches_honors_linked_team_without_gameseq(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, camp, db = setup_data(Path(tmp))
            result = team_clusters.list_teams(camp, db, '本队')
            team_id = result['teams'][0]['id']
            identity_service.rename_team(db, team_id, name='青岚')
            opponent_identity.clear_cache()
            resolution = opponent_identity.resolve(db, camp)
            matches = [{'key': 'db-m1', 'opponent': '其它队名', 'opponentTeamId': team_id}]
            opponent_identity.apply_to_matches(matches, resolution)
            self.assertEqual(matches[0]['opponent'], '青岚')
            self.assertEqual(matches[0]['opponentNameSource'], 'team')

    def test_matched_team_name_shows_even_without_opponent_text(self):
        """匹配页把 enemy_team_id 落库后，别处不能再显示「对手未标注」。"""
        with tempfile.TemporaryDirectory() as tmp:
            data, camp, db = setup_data(Path(tmp))
            result = team_clusters.list_teams(camp, db, '本队')
            team_id = result['teams'][0]['id']
            identity_service.rename_team(db, team_id, name='青岚')
            connection = sqlite3.connect(db)
            connection.execute(
                'INSERT INTO match_records(match_key, enemy_team_id) VALUES (?, ?)',
                ('db-m1', team_id))
            connection.commit()
            connection.close()
            opponent_identity.clear_cache()
            repo = analysis_data.AnalysisRepository(db, data / 'matches', data / 'imports', camp.parent)
            matches = repo.get()['matches']
            match = next(item for item in matches if item['key'] == 'db-m1')
            self.assertEqual(match['opponent'], '青岚')
            self.assertEqual(match['opponentNameSource'], 'team')

    def test_team_rename_and_merge_update_resolved_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, camp, db = setup_data(Path(tmp))
            result = team_clusters.list_teams(camp, db, '本队')
            first, second = [team['id'] for team in result['teams']]
            identity_service.rename_team(db, first, name='青岚')
            identity_service.rename_team(db, second, name='白虎')
            team_clusters.merge_team(db, second, first)
            opponent_identity.clear_cache()
            resolution = opponent_identity.resolve(db, camp)
            self.assertEqual(resolution['bySeq']['101'], '青岚')
            self.assertEqual(resolution['bySeq']['102'], '青岚')
            matches = [{'key': 'camp-102', 'opponent': '白虎'}]
            opponent_identity.apply_to_matches(matches, resolution)
            self.assertEqual(matches[0]['opponent'], '青岚')


class ApiSyncTests(unittest.TestCase):
    def setUp(self):
        import importlib
        from fastapi.testclient import TestClient
        import server  # noqa: F401 - 挂载 v3 路由（模块名 kpl_v3_app）
        serve = importlib.import_module('kpl_v3_app')
        from server import app
        self.serve = serve
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.data, self.camp, self.db = setup_data(root)
        (self.data / 'matches').mkdir(exist_ok=True)
        (self.data / 'imports').mkdir(exist_ok=True)
        self.patches = [
            patch.object(serve, 'DB', self.db),
            patch.object(serve, 'ROOT', root),
            patch.object(serve, 'MATCHES', self.data / 'matches'),
            patch.object(serve, 'IMPORTS', self.data / 'imports'),
            patch.object(serve, 'OFFICIAL', self.data / 'official_replays'),
        ]
        for item in self.patches:
            item.start()
        opponent_identity.clear_cache()
        serve.invalidate_snapshot()
        self.client = TestClient(app, base_url='http://127.0.0.1',
                                 client=('127.0.0.1', 50001))

    def tearDown(self):
        for item in self.patches:
            item.stop()
        opponent_identity.clear_cache()
        self.serve.invalidate_snapshot()
        try:
            self.tmp.cleanup()
        except PermissionError:
            pass

    def test_match_side_rename_creates_team_and_links_match(self):
        response = self.client.post('/api/v3/opponent-team',
                                    json={'key': 'db-m1', 'opponent': '新对手'})
        self.assertEqual(response.status_code, 200, response.text[:300])
        body = response.json()
        self.assertTrue(body['ok'])
        self.assertTrue(body['teamId'])
        teams = {team['name'] for team in Workspace(self.db).list_teams()}
        self.assertIn('新对手', teams)
        meta = sqlite3.connect(self.db).execute(
            'SELECT body FROM match_meta WHERE match_key=?', ('db-m1',)).fetchone()
        self.assertIsNotNone(meta)
        saved = json.loads(meta[0])
        self.assertEqual(saved['opponent'], '新对手')
        self.assertEqual(saved['opponentTeamId'], body['teamId'])
        matches = self.client.get('/api/matches').json()['matches']
        match = next(item for item in matches if item['key'] == 'db-m1')
        self.assertEqual(match['opponent'], '新对手')
        self.assertEqual(match['opponentTeamId'], body['teamId'])

    def test_match_side_rename_renames_existing_team(self):
        result = team_clusters.list_teams(self.camp, self.db, '本队')
        team_id = result['teams'][0]['id']
        identity_service.rename_team(self.db, team_id, name='青岚')
        # 这局没有 gameSeq：靠当前对手文本命中已存在的战队
        connection = sqlite3.connect(self.db)
        row = connection.execute('SELECT body FROM matches WHERE id=?', ('m1',)).fetchone()
        body = json.loads(row[0])
        body.update(id='m2', opponent='青岚', date='2026-11-24')
        connection.execute('INSERT INTO matches VALUES (?,1,?)',
                           ('m2', json.dumps(body, ensure_ascii=False)))
        connection.commit()
        connection.close()
        self.serve.invalidate_snapshot()
        response = self.client.post('/api/v3/opponent-team',
                                    json={'key': 'db-m2', 'opponent': '白虎'})
        self.assertEqual(response.status_code, 200, response.text[:300])
        self.assertEqual(response.json()['teamId'], team_id)
        renamed = next(team for team in Workspace(self.db).list_teams(include_archived=True)
                       if team['id'] == team_id)
        self.assertEqual(renamed['name'], '白虎')

    def test_team_side_rename_refreshes_match_view_without_fresh(self):
        result = team_clusters.list_teams(self.camp, self.db, '本队')
        team_id = result['teams'][0]['id']
        identity_service.rename_team(self.db, team_id, name='老名字')
        connection = sqlite3.connect(self.db)
        row = connection.execute('SELECT body FROM matches WHERE id=?', ('m1',)).fetchone()
        body = json.loads(row[0])
        body.update(id='m2', opponent='老名字', date='2026-11-24')
        connection.execute('INSERT INTO matches VALUES (?,1,?)',
                           ('m2', json.dumps(body, ensure_ascii=False)))
        connection.commit()
        connection.close()
        self.serve.invalidate_snapshot()
        before = self.client.get('/api/matches').json()['matches']
        self.assertEqual(next(item for item in before if item['key'] == 'db-m2')['opponent'],
                         '老名字')
        # 战队页改名只 bump opponent_identity，不去动 v3 的 TTL 快照。
        identity_service.rename_team(self.db, team_id, name='青岚')
        opponent_identity.clear_cache()
        after = self.client.get('/api/matches').json()['matches']
        renamed = next(item for item in after if item['key'] == 'db-m2')
        self.assertEqual(renamed['opponent'], '青岚')


if __name__ == '__main__':
    unittest.main()
