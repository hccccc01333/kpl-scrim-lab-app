"""本轮审计修复的回归测试：阈值顺序、并队关系回填、通道正文改名。"""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import grade_rules
import identity_service
import team_clusters


class GradeRuleValidationTest(unittest.TestCase):
    def test_reversed_thresholds_are_rejected(self):
        doc = grade_rules.normalize(None)
        doc['subjects']['中路']['gpm']['thresholds'] = [100, 200, 300]  # up 却倒序
        self.assertFalse(grade_rules._valid(doc))
        doc['subjects']['中路']['gpm']['thresholds'] = [300, 200, 100]
        self.assertTrue(grade_rules._valid(doc))

    def test_down_direction_requires_ascending_thresholds(self):
        doc = grade_rules.normalize(None)
        field = next(f for f, r in doc['subjects']['中路'].items()
                     if r['direction'] == 'down')
        doc['subjects']['中路'][field]['thresholds'] = [900, 500, 100]
        self.assertFalse(grade_rules._valid(doc))


class MergeBackfillTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / 'training.sqlite3')
        connection = sqlite3.connect(self.db)
        try:
            connection.execute('CREATE TABLE schedules (id TEXT, opponent_team_id TEXT)')
            connection.execute('CREATE TABLE training_series (id TEXT, opponent_team_id TEXT)')
            connection.execute('CREATE TABLE match_records (match_key TEXT, enemy_team_id TEXT)')
            connection.execute('CREATE TABLE match_meta (match_key TEXT, body TEXT)')
            connection.execute('CREATE TABLE channels (id TEXT, body TEXT)')
            connection.execute("INSERT INTO schedules VALUES ('s1', 'team-a')")
            connection.execute("INSERT INTO training_series VALUES ('t1', 'team-a')")
            connection.execute("INSERT INTO match_records VALUES ('g1', 'team-a')")
            connection.execute("INSERT INTO match_meta VALUES ('channel-g1', ?)",
                               (json.dumps({'opponentTeamId': 'team-a'}),))
            connection.execute("INSERT INTO channels VALUES ('c1', ?)",
                               (json.dumps({'match': {'opponentTeamId': 'team-a'}}),))
            connection.commit()
        finally:
            connection.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_old_team_id_is_replaced_in_authoritative_refs(self):
        team_clusters._backfill_merged_team_refs(self.db, 'team-a', 'team-b')
        connection = sqlite3.connect(self.db)
        try:
            self.assertEqual(connection.execute(
                'SELECT opponent_team_id FROM schedules').fetchone()[0], 'team-b')
            self.assertEqual(connection.execute(
                'SELECT opponent_team_id FROM training_series').fetchone()[0], 'team-b')
            self.assertEqual(connection.execute(
                'SELECT enemy_team_id FROM match_records').fetchone()[0], 'team-b')
            self.assertEqual(json.loads(connection.execute(
                'SELECT body FROM match_meta').fetchone()[0])['opponentTeamId'], 'team-b')
            self.assertEqual(json.loads(connection.execute(
                'SELECT body FROM channels').fetchone()[0])['match']['opponentTeamId'], 'team-b')
        finally:
            connection.close()


class TeamRenameChannelBodyTest(unittest.TestCase):
    def test_nested_match_opponent_is_renamed(self):
        with tempfile.TemporaryDirectory() as directory:
            db = str(Path(directory) / 'training.sqlite3')
            connection = sqlite3.connect(db)
            try:
                connection.execute('CREATE TABLE channels (id TEXT, body TEXT)')
                connection.execute('CREATE TABLE training_series (id TEXT, opponent TEXT)')
                connection.execute("INSERT INTO channels VALUES ('c1', ?)",
                                   (json.dumps({'match': {'opponent': '旧队'}}),))
                connection.commit()
            finally:
                connection.close()
            identity_service._sync_team_name_refs(db, '旧队', '新队')
            connection = sqlite3.connect(db)
            try:
                body = json.loads(connection.execute(
                    'SELECT body FROM channels').fetchone()[0])
                self.assertEqual(body['match']['opponent'], '新队')
            finally:
                connection.close()


if __name__ == '__main__':
    unittest.main()
