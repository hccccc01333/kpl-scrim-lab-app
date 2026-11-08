"""Tests of V2 migration and reviewed V1 route boundaries."""
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
        self.assertIn('/api/v2/import/preview', paths)
        self.assertIn('/api/v2/workspace/overview', paths)

    def test_migration_inserts_once_and_preserves_existing_manual_values(self):
        uri = 'file:v2-test-' + uuid.uuid4().hex + '?mode=memory&cache=shared'
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
