"""BP 页对手口径回归：匹配页确认的战队卡必须盖过营地阵容聚类。"""
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import serve
import workspace_store


class BpBoardTeamCardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / 'data').mkdir()
        self.db = root / 'data' / 'training.sqlite3'
        ws = workspace_store.Workspace(self.db).ensure_schema()
        self.team_id = ws.upsert_team(None, name='测试对手')
        with sqlite3.connect(self.db) as connection:
            connection.execute(
                'CREATE TABLE channels (id TEXT PRIMARY KEY, revision INTEGER, '
                'body TEXT, created_at REAL, updated_at REAL)')
            connection.execute(
                'CREATE TABLE match_meta (match_key TEXT PRIMARY KEY, body TEXT, updated_at REAL)')
            connection.execute(
                'INSERT INTO channels(id, body) VALUES(?, ?)',
                ('abc123', json.dumps({'match': {'gameSeq': '1795435122'}})))
            connection.execute(
                'INSERT INTO match_meta(match_key, body) VALUES(?, ?)',
                ('channel-abc123', json.dumps({
                    'opponentTeamId': self.team_id, 'matchingArchived': True})))
        self.patches = [patch.object(serve, 'DB', self.db), patch.object(serve, 'ROOT', root)]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        try:
            self.tmp.cleanup()
        except PermissionError:
            pass

    def test_card_from_channels_seq_and_match_meta(self):
        mapping = serve._card_team_by_seq()
        self.assertEqual(mapping.get('1795435122') or {}, {
            'id': self.team_id, 'name': '测试对手', 'coach': ''})

    def test_cluster_key_uses_confirmed_card_before_lineup_signature(self):
        import team_clusters
        cards = team_clusters.card_team_by_seq(self.db)
        self.assertEqual(cards['1795435122']['id'], self.team_id)
        key_of = team_clusters.cluster_key_of(self.db, [])
        self.assertEqual(key_of({'seq': '1795435122', 'enemy_roster': []}), self.team_id)

    def test_placeholder_team_without_card_is_not_mapped(self):
        with sqlite3.connect(self.db) as connection:
            connection.execute(
                'INSERT INTO channels(id, body) VALUES(?, ?)',
                ('def456', json.dumps({'match': {'gameSeq': '1795433661'}})))
        mapping = serve._card_team_by_seq()
        self.assertNotIn('1795433661', mapping)


if __name__ == '__main__':
    unittest.main()
