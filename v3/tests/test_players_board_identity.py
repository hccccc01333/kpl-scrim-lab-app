"""选手档案身份回归：matching 保存的对手选手必须进入 players-board。"""
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

STATS = {'killCnt': 3, 'deadCnt': 2, 'assistCnt': 5, 'money': 7200,
         'totalHurtCnt': 24000, 'totalBehurtCnt': 18000, 'ctrlTime': 120,
         'healCnt': 800, 'joinGamePercent': 0.6, 'towerCnt': 1, 'gradeGame': 8.5}
LANES = ['对抗路', '打野', '中路', '发育路', '游走']


def panel(seq, own_names, enemy_names, start='11-02 12:00', win=True):
    def role(player_id, name, camp, position, hero):
        return {'basicInfo': {'playerId': player_id, 'roleName': name, 'acntCamp': camp},
                'battleRecords': {'usedHero': {'heroName': hero}, 'position': position},
                'battleStats': dict(STATS)}
    own = [role(f'own-camp-{i}', name, 1, i, '吕布') for i, name in enumerate(own_names)]
    enemy = [role(f'enemy-camp-{i}', name, 2, i, '瑶') for i, name in enumerate(enemy_names)]
    return {'data': {'head': {'acntCamp': 1, 'gameResult': win},
                     'battle': {'startTime': start, 'usedTime': 900, 'mapName': '排位赛'},
                     'blueRoles': own, 'redRoles': enemy}}


class PlayersBoardIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.data = root / 'data'
        self.details = self.data / 'camp_details'
        self.details.mkdir(parents=True)
        (self.data / 'matches').mkdir()
        self.db = self.data / 'training.sqlite3'
        self.ws = workspace_store.Workspace(self.db).ensure_schema()
        with sqlite3.connect(self.db) as connection:
            connection.execute('CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, body TEXT NOT NULL)')
            connection.execute('INSERT OR REPLACE INTO settings(id, body) VALUES(1, ?)',
                               (json.dumps({'teamName': '测试本队', 'roster': [], 'aliases': {}},
                                           ensure_ascii=False),))
        self.own_team = self.ws.upsert_team(None, name='测试本队')
        self.enemy_team = self.ws.upsert_team(None, name='高校队12')
        self.ws.upsert_player('own-1', team_id=self.own_team, name='本队选手', position='对抗路')
        for index, lane in enumerate(LANES, 1):
            self.ws.upsert_player(str(index), team_id=self.enemy_team,
                                  name=f'高校选手{index}', position=lane)
        self.patches = [patch.object(serve, 'DB', self.db),
                        patch.object(serve, 'ROOT', root),
                        patch.object(serve, 'MATCHES', self.data / 'matches')]
        for item in self.patches:
            item.start()
        serve.invalidate_players_cache()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        serve.invalidate_players_cache()
        try:
            self.tmp.cleanup()
        except PermissionError:
            pass

    def write_panel(self, seq, own_names, enemy_names, start='11-02 12:00'):
        (self.details / f'{seq}.json').write_text(
            json.dumps(panel(seq, own_names, enemy_names, start), ensure_ascii=False), encoding='utf-8')
        serve.invalidate_players_cache()

    def bind_nicknames(self, side, names, player_ids):
        self.ws.upsert_nickname_entries([
            {'side': side, 'playerId': player_id, 'nickname': name,
             'accountId': None, 'matchKey': None, 'lane': '', 'confidence': 'manual'}
            for name, player_id in zip(names, player_ids)
        ])
        serve.invalidate_players_cache()

    def test_enemy_nickname_pool_binds_high_school_players(self):
        own_names = [f'我方{i}' for i in range(5)]
        enemy_names = [f'敌{i}' for i in range(5)]
        self.write_panel('101', own_names, enemy_names, '11-02 12:00')
        self.write_panel('102', own_names, enemy_names, '11-02 12:20')
        self.bind_nicknames('enemy', enemy_names, ['1', '2', '3', '4', '5'])
        self.bind_nicknames('own', [own_names[0]], ['own-1'])

        board = serve._players_board()
        enemy = {player['name']: player for player in board['players'] if player['side'] == 'enemy'}
        for index, name in enumerate(enemy_names, 1):
            with self.subTest(name=name):
                self.assertEqual(enemy[name]['memberId'], str(index))
                self.assertTrue(enemy[name]['bound'])
                self.assertEqual(enemy[name]['games'], 2)
        member_ids = {member['id'] for member in board['identity']['members']}
        self.assertEqual(member_ids, {'own-1'})

    def test_same_nickname_on_both_sides_does_not_cross_bind(self):
        own_names = ['同名', '我方1', '我方2', '我方3', '我方4']
        enemy_names = ['同名', '敌1', '敌2', '敌3', '敌4']
        self.write_panel('201', own_names, enemy_names)
        self.bind_nicknames('own', ['同名'], ['own-1'])
        self.bind_nicknames('enemy', ['同名'], ['1'])

        board = serve._players_board()
        same = [player for player in board['players'] if player['name'] == '同名']
        self.assertEqual(len(same), 2)
        by_side = {player['side']: player for player in same}
        self.assertEqual(by_side['own']['memberId'], 'own-1')
        self.assertEqual(by_side['enemy']['memberId'], '1')

    def test_enabled_enemy_rule_is_consumed(self):
        enemy_names = [f'敌{i}' for i in range(5)]
        self.write_panel('301', [f'我方{i}' for i in range(5)], enemy_names)
        with sqlite3.connect(self.db) as connection:
            connection.execute(
                'INSERT INTO matching_rules(id, side, nickname, player_id, team_id, scope, enabled, created_at, updated_at) '
                "VALUES('rule-enemy', 'enemy', '敌0', '1', ?, '高校队12', 1, 0, 0)",
                (self.enemy_team,))
        serve.invalidate_players_cache()

        board = serve._players_board()
        enemy = next(player for player in board['players']
                     if player['side'] == 'enemy' and player['name'] == '敌0')
        self.assertEqual(enemy['memberId'], '1')
        self.assertTrue(enemy['bound'])
