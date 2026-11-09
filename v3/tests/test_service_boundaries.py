"""Tests of V3 route boundaries and compatibility aliases."""
import sqlite3
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import serve
import workspace_store


class ServiceBoundaryTests(unittest.TestCase):
    def test_v1_routes_with_file_cleanup_are_not_mounted(self):
        paths = {getattr(route, 'path', '') for route in serve.router.routes}
        paths |= {getattr(route, 'path', '') for route in serve._studio.routes}
        self.assertNotIn('/api/studio/workspace', paths)
        self.assertNotIn('/api/studio/import/preview', paths)
        self.assertNotIn('/api/studio/import/commit', paths)
        self.assertIn('/api/v3/import/preview', paths)
        self.assertIn('/api/v3/workspace/overview', paths)

    def test_malformed_json_returns_400(self):
        from fastapi.testclient import TestClient
        client = TestClient(serve.app, base_url='http://127.0.0.1')
        endpoints = [
            '/api/v3/research/reports',
            '/api/v3/import/commit',
            '/api/v3/identity/roster',
            '/api/v3/identity/claim',
            '/api/v3/identity/name',
        ]
        for path in endpoints:
            with self.subTest(path=path):
                response = client.post(path, content=b'{bad',
                                       headers={'Content-Type': 'application/json'})
                self.assertEqual(response.status_code, 400,
                                 (path, response.status_code, response.text[:120]))
        # 这两个接口先查对局是否存在；有对局时再验证非法 JSON 返回 400。
        matches = client.get('/api/matches').json().get('matches') or []
        if not matches:
            return
        key = matches[0]['key']
        for path in (f'/api/v3/match-bp/{key}', f'/api/v3/match-meta/{key}'):
            with self.subTest(path=path):
                response = client.post(path, content=b'{bad',
                                       headers={'Content-Type': 'application/json'})
                self.assertEqual(response.status_code, 400,
                                 (path, response.status_code, response.text[:120]))

    def test_migration_inserts_once_and_preserves_existing_manual_values(self):
        uri = 'file:boundary-test-' + uuid.uuid4().hex + '?mode=memory&cache=shared'
        keeper = sqlite3.connect(uri, uri=True)
        keeper.executescript(workspace_store.SCHEMA)
        class Workspace:
            def connect(self):
                return sqlite3.connect(uri, uri=True)
        match = {'key':'one', 'date':'2026-01-01', 'session':'晚训', 'mode':'训练赛',
                 'version':'v1', 'ownCamp':'red', 'result':'loss',
                 'scores':{'blue':8, 'red':3}, 'duration':900, 'source':'bundle'}
        with patch.object(serve, 'migration_candidates', return_value=(Workspace(), {}, [match])):
            self.assertEqual(serve.migrate_new_matches(None)['created'], 1)
            keeper.execute("UPDATE match_records SET status='confirmed', version='manual' WHERE match_key='one'")
            keeper.commit()
            self.assertEqual(serve.migrate_new_matches(None)['created'], 0)
        row=keeper.execute("SELECT status,version,own_side,winner FROM match_records WHERE match_key='one'").fetchone()
        self.assertEqual(row, ('confirmed','manual','red','blue'))
        self.assertEqual(keeper.execute("SELECT COUNT(*) FROM provenance WHERE match_key='one'").fetchone()[0], 8)
        keeper.close()


if __name__ == '__main__':
    unittest.main()
