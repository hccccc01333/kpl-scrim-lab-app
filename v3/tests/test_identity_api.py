"""身份对照：游戏 ID → 选手 → 战队。

三条规则在这里落成用例：
1. 一处命名处处生效——账号映射是唯一口径，改一次名不会再冒出第二个选手；
2. 对手也能命名——不再只有本队有入口；
3. 可删——删选手连他的账号映射一起删，账号回到「待命名」。
"""
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


def panel(seq, enemy_ids, own_ids, start='11-02 12:00', win=True):
    def role(player_id, name, camp, position, hero):
        return {'basicInfo': {'playerId': player_id, 'roleName': name, 'acntCamp': camp},
                'battleRecords': {'usedHero': {'heroName': hero}, 'position': position},
                'battleStats': dict(STATS)}
    own = [role(pid, f'我方{i}', 1, i, '吕布') for i, pid in enumerate(own_ids)]
    enemy = [role(pid, f'敌{i}', 2, i, '瑶') for i, pid in enumerate(enemy_ids)]
    return {'data': {'head': {'acntCamp': 1, 'gameResult': win},
                     'battle': {'startTime': start, 'usedTime': 900, 'mapName': '排位赛'},
                     'blueRoles': own, 'redRoles': enemy}}


class IdentityApiTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.data = root / 'data'
        details = self.data / 'camp_details'
        details.mkdir(parents=True)
        (details / '101.json').write_text(
            json.dumps(panel('101', [f'e{i}' for i in range(5)], [f'o{i}' for i in range(5)]),
                       ensure_ascii=False), encoding='utf-8')
        self.db = self.data / 'training.sqlite3'
        ws = workspace_store.Workspace(self.db).ensure_schema()
        connection = sqlite3.connect(self.db)
        try:
            connection.execute('CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, body TEXT NOT NULL)')
            connection.execute('INSERT OR REPLACE INTO settings(id, body) VALUES(1, ?)',
                               (json.dumps({'teamName': '测试本队', 'roster': [], 'aliases': {}},
                                           ensure_ascii=False),))
            connection.commit()
        finally:
            connection.close()
        ws.upsert_team(None, name='测试本队')
        self.patches = [patch.object(serve, 'DB', self.db),
                        patch.object(serve, 'ROOT', root),
                        patch.object(serve, 'MATCHES', self.data / 'matches')]
        for item in self.patches:
            item.start()
        serve.invalidate_players_cache()
        self.client = TestClient(serve.app, base_url='http://127.0.0.1',
                                 client=('127.0.0.1', 50000))

    def tearDown(self):
        for item in self.patches:
            item.stop()
        serve.invalidate_players_cache()
        try:
            self.tmp.cleanup()
        except PermissionError:
            # Windows 上残留的连接会锁住 sqlite 文件；测试目录留给系统清理即可。
            pass

    # ---------------------------------------------------------------- 读
    def accounts(self, **params):
        response = self.client.get('/api/v3/identity/accounts', params=params)
        self.assertEqual(response.status_code, 200, response.text[:300])
        return response.json()

    def test_lists_every_game_account_with_side(self):
        value = self.accounts()
        self.assertEqual(value['counters']['total'], 10)
        self.assertEqual(value['counters']['unmapped'], 10)
        self.assertEqual(value['counters']['own'], 5)
        self.assertEqual(value['counters']['enemy'], 5)
        row = next(item for item in value['rows'] if item['accountId'] == 'e0')
        self.assertEqual(row['side'], 'enemy')
        self.assertFalse(row['mapped'])
        # 敌方默认归属来自营地聚类，不是空的
        self.assertTrue(row['suggestTeamId'])

    # ---------------------------------------------------------------- 写
    def test_names_opponent_account_and_creates_team(self):
        response = self.client.post('/api/v3/identity/name',
                                    json={'accountId': 'e0', 'nickname': '敌0', 'name': '小义',
                                          'position': '发育路', 'team': '重庆狼队'})
        self.assertEqual(response.status_code, 200, response.text[:300])
        row = next(item for item in self.accounts()['rows'] if item['accountId'] == 'e0')
        self.assertTrue(row['mapped'])
        self.assertEqual(row['name'], '小义')
        self.assertEqual(row['teamName'], '重庆狼队')
        teams = [team['name'] for team in workspace_store.Workspace(self.db).list_teams()]
        self.assertIn('重庆狼队', teams)

    def test_renaming_same_account_updates_instead_of_duplicating(self):
        self.client.post('/api/v3/identity/name',
                         json={'accountId': 'e0', 'nickname': '敌0', 'name': '小义', 'team': '重庆狼队'})
        self.client.post('/api/v3/identity/name',
                         json={'accountId': 'e0', 'nickname': '敌0', 'name': '小义·改', 'team': '重庆狼队'})
        players = workspace_store.Workspace(self.db).list_players()
        self.assertEqual(len(players), 1)
        self.assertEqual(players[0]['name'], '小义·改')
        self.assertIn('敌0', players[0]['aliases'])

    def test_own_side_defaults_to_own_team(self):
        response = self.client.post('/api/v3/identity/name',
                                    json={'accountId': 'o0', 'nickname': '我方0', 'name': '信则有',
                                          'position': '对抗路'})
        self.assertEqual(response.status_code, 200, response.text[:300])
        row = next(item for item in self.accounts()['rows'] if item['accountId'] == 'o0')
        self.assertEqual(row['teamName'], '测试本队')

    def test_unmap_keeps_player_but_returns_account_to_unnamed(self):
        self.client.post('/api/v3/identity/name',
                         json={'accountId': 'e0', 'nickname': '敌0', 'name': '小义', 'team': '重庆狼队'})
        response = self.client.post('/api/v3/identity/accounts/unmap', json={'accountId': 'e0'})
        self.assertEqual(response.status_code, 200, response.text[:300])
        row = next(item for item in self.accounts()['rows'] if item['accountId'] == 'e0')
        self.assertFalse(row['mapped'])
        self.assertEqual(len(workspace_store.Workspace(self.db).list_players()), 1)

    def test_delete_player_removes_mappings(self):
        self.client.post('/api/v3/identity/name',
                         json={'accountId': 'e0', 'nickname': '敌0', 'name': '小义', 'team': '重庆狼队'})
        player_id = workspace_store.Workspace(self.db).list_players()[0]['id']
        response = self.client.post('/api/v3/identity/players/delete', json={'playerId': player_id})
        self.assertEqual(response.status_code, 200, response.text[:300])
        self.assertEqual(workspace_store.Workspace(self.db).list_players(), [])
        self.assertEqual(workspace_store.Workspace(self.db).account_index(), {})
        row = next(item for item in self.accounts()['rows'] if item['accountId'] == 'e0')
        self.assertFalse(row['mapped'])
        self.assertEqual(row['nickname'], '敌0')

    def test_add_player_without_account_and_reuse_same_name(self):
        first = self.client.post('/api/v3/identity/players',
                                 json={'name': '替补甲', 'position': '游走', 'team': '测试本队'})
        self.assertEqual(first.status_code, 200, first.text[:300])
        second = self.client.post('/api/v3/identity/players',
                                  json={'name': '替补甲', 'position': '游走', 'team': '测试本队'})
        self.assertEqual(second.status_code, 200, second.text[:300])
        self.assertEqual(first.json()['id'], second.json()['id'])
        self.assertEqual(len(workspace_store.Workspace(self.db).list_players()), 1)

    def test_claim_label_maps_every_account_with_that_nickname(self):
        created = self.client.post('/api/v3/identity/players',
                                   json={'name': '信则有', 'team': '测试本队'})
        player_id = created.json()['id']
        response = self.client.post('/api/v3/identity/claim',
                                    json={'label': '我方0', 'playerId': player_id})
        self.assertEqual(response.status_code, 200, response.text[:300])
        self.assertEqual(response.json()['accounts'], 1)
        self.assertEqual(workspace_store.Workspace(self.db).account_index()['o0']['playerId'], player_id)

    # ---------------------------------------------------------------- 门禁
    def test_rejects_placeholder_team_and_missing_name(self):
        response = self.client.post('/api/v3/identity/name',
                                    json={'accountId': 'e0', 'nickname': '敌0', 'name': '小义',
                                          'team': '待命名战队 #1'})
        self.assertEqual(response.status_code, 400)
        response = self.client.post('/api/v3/identity/name',
                                    json={'accountId': 'e0', 'nickname': '敌0', 'name': ''})
        self.assertEqual(response.status_code, 400)

    def test_rejects_bad_position(self):
        response = self.client.post('/api/v3/identity/name',
                                    json={'accountId': 'e0', 'nickname': '敌0', 'name': '小义',
                                          'position': '打野位', 'team': '测试本队'})
        self.assertEqual(response.status_code, 400)

    def test_unknown_account_cannot_be_named_from_nothing(self):
        response = self.client.post('/api/v3/identity/name', json={'name': '小义'})
        self.assertEqual(response.status_code, 400)


if __name__ == '__main__':
    unittest.main()
