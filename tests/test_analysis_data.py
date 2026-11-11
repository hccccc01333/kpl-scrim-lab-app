import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from analysis_api import create_analysis_router
from analysis_data import AnalysisRepository
from fastapi import FastAPI
from fastapi.testclient import TestClient


def create_app(db_path=None, matches_dir=None, imports_dir=None):
    """分析路由的测试装配：等价于原 analysis_server.create_app，但不挂独立前端静态目录。"""
    app = FastAPI()
    app.include_router(create_analysis_router(db_path, matches_dir, imports_dir))
    return app


OWN = ['影', '铠', '戈娅', '百里守约', '孙膑']
ENEMY = ['程咬金', '百里玄策', '姜子牙', '鲁班七号', '蚩奼']
C_BLUE = ['李白', '韩信', '貂蝉', '虞姬', '张飞']
C_RED = ['关羽', '赵云', '诸葛亮', '黄忠', '蔡文姬']
D_BLUE = ['哪吒', '杨戬', '嫦娥', '后羿', '太乙真人']
D_RED = ['猪八戒', '孙悟空', '小乔', '狄仁杰', '鬼谷子']
ROSTER = [{'id': f'b{index + 1}', 'name': name} for index, name in enumerate(['甲乙丙丁戊'])]


def db_match(match_id, date, opponent, side, winner, duration, own_heroes, enemy_heroes):
    players = []
    own_side, enemy_side = side, 'right' if side == 'left' else 'left'
    for slot, hero in enumerate(own_heroes):
        players.append({'side': own_side, 'slot': slot, 'playerId': f'b{slot + 1}',
                        'hero': hero, 'position': '', 'kills': 2 + slot, 'deaths': 1,
                        'assists': 4 + slot, 'gold': 10000 - slot * 500,
                        'damage': 30000 - slot * 1000, 'taken': 20000 - slot * 500,
                        'participation': 60, 'rating': '12.0', 'equipment': ''})
    for slot, hero in enumerate(enemy_heroes):
        players.append({'side': enemy_side, 'slot': slot, 'playerId': None, 'hero': hero,
                        'position': '', 'kills': 1 + slot, 'deaths': 3, 'assists': 2,
                        'gold': 8000 - slot * 400, 'damage': 20000 - slot * 500,
                        'taken': 18000 - slot * 300, 'participation': 50, 'rating': '10.0',
                        'equipment': ''})
    left_score, right_score = (12, 8) if winner == 'left' else (8, 12)
    return {'id': match_id, 'status': 'confirmed', 'date': date, 'opponent': opponent,
            'side': side, 'winner': winner, 'duration': duration, 'session': '训练赛',
            'version': '12.1', 'scores': {'left': left_score, 'right': right_score},
            'players': players}


def make_db(path):
    connection = sqlite3.connect(path)
    connection.executescript('''
      CREATE TABLE settings (id INTEGER PRIMARY KEY, body TEXT NOT NULL);
      CREATE TABLE matches (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, body TEXT NOT NULL);
    ''')
    connection.execute('INSERT INTO settings VALUES (1,?)',
                       (json.dumps({'teamName': '测试队', 'roster': ROSTER}, ensure_ascii=False),))
    for body in [
        db_match('A', '2026-10-01', '对手A', 'left', 'left', 20, OWN, ENEMY),
        db_match('B', '2026-10-02', '对手B', 'right', 'right', 18, OWN, ENEMY),
    ]:
        connection.execute('INSERT INTO matches VALUES (?,1,?)',
                           (body['id'], json.dumps(body, ensure_ascii=False)))
    connection.commit()
    connection.close()


def bundle(key, date, duration, blue, red, scores=None, own='blue', partial=False, title='测试录像'):
    players = []
    for camp, heroes in (('blue', blue), ('red', red)):
        for slot, hero in enumerate(heroes):
            final = {'source': 'postgame' if not partial else 'scoreboard',
                     'complete': not partial, 'partial': partial,
                     'kills': 3 + slot, 'deaths': 2, 'assists': 5,
                     'totalGold': 11000 if not partial else 900,
                     'damage': 30000 if not partial else None,
                     'taken': 20000 if not partial else None,
                     'participation': 60 if not partial else None,
                     'rating': 12.0 if not partial else None}
            process = {'pov': [], 'series': [], 'scoreboard': []}
            if camp == own and slot == 0:
                process['pov'] = [{'gameStart': 0, 'gameEnd': 10, 'levelFirst': 1,
                                   'levelLast': 5, 'kdaFirst': [0, 0, 0],
                                   'kdaLast': [1, 0, 0], 'availableGoldFirst': 300,
                                   'availableGoldLast': 1000,
                                   'runes': {'raw': '10宿命'}, 'equipment': {'filled': 1}}]
            players.append({'key': f'{camp}-{slot}', 'camp': camp, 'slot': slot,
                            'hero': hero, 'nickname': hero, 'final': final,
                            'process': process})
    return {
        'schema': 'kpl-match-data-v1',
        'match': {'key': key, 'title': title, 'mode': '峡谷—快速赛',
                  'date': {'text': date}, 'duration': duration,
                  'scores': scores or {}, 'identity': {}},
        'pov': {'camp': own},
        'sources': [{'kind': 'video', 'file': f'{key}.mp4', 'followPlayer': {'camp': own, 'hero': blue[0]}}],
        'team': {'timeline': [
            {'gameTime': 0, 'blueGold': 1500, 'redGold': 1500, 'blueKills': 0, 'redKills': 0},
            {'gameTime': 60, 'blueGold': 5000, 'redGold': 4500, 'blueKills': 2, 'redKills': 1},
        ], 'scoreboardSnapshots': [], 'killEvents': []},
        'players': players,
        'warnings': [],
    }


def write_sheet_import(root):
    import_id = 'sheet1'
    folder = Path(root) / import_id
    rows_dir = folder / 'rows'
    rows_dir.mkdir(parents=True)
    match_rows = []
    for slot, hero in enumerate(['影', '铠', '戈娅']):
        match_rows.append({
            'rowNumber': slot + 2, 'grain': 'match_player', 'aggregated': False, 'raw': {},
            'keys': {'date': '2026-10-04', 'matchId': 'S1', 'player': f'纸面{slot + 1}',
                     'hero': hero, 'side': 'blue', 'opponent': '表格对手', 'position': '对抗路'},
            'dimensions': {'win': 1},
            'metrics': {key: {'value': value} for key, value in {
                'kills': 4, 'deaths': 2, 'assists': 3, 'gold': 10000,
                'damage': 25000, 'taken': 15000, 'participation': 55}.items()},
        })
    (rows_dir / '01-match.jsonl').write_text(
        '\n'.join(json.dumps(row, ensure_ascii=False) for row in match_rows) + '\n', encoding='utf-8')
    (rows_dir / '02-agg.jsonl').write_text(json.dumps({
        'rowNumber': 2, 'grain': 'aggregate_player', 'aggregated': True, 'raw': {'选手': '甲乙'},
        'keys': {'player': '甲乙', 'hero': '影'}, 'dimensions': {},
        'metrics': {'games': {'value': 10}, 'winRate': {'value': 70.0}},
    }, ensure_ascii=False) + '\n', encoding='utf-8')
    manifest = {
        'schema': 'kpl-sheet-import-v1', 'source': {'name': 'sheet.csv'},
        'profileSource': 'provided', 'quality': {'rows': 4, 'duplicates': 0},
        'warnings': [], 'createdAt': '2026-10-30',
        'sheets': [
            {'name': '单局', 'grain': 'match_player', 'aggregated': False, 'rowCount': 3,
             'rowsFile': 'rows/01-match.jsonl', 'keys': {}, 'metrics': ['kills'],
             'unmappedColumns': []},
            {'name': '赛季', 'grain': 'aggregate_player', 'aggregated': True, 'rowCount': 1,
             'rowsFile': 'rows/02-agg.jsonl', 'keys': {}, 'metrics': ['games', 'winRate'],
             'unmappedColumns': []},
        ],
    }
    (folder / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')


def write_single_match_import(root):
    """一局十人、带「本队=蓝方」的表，用来验证导入后的胜负与比分。"""
    import_id = 'own1'
    folder = Path(root) / import_id
    rows_dir = folder / 'rows'
    rows_dir.mkdir(parents=True)
    lanes = ['对抗路', '打野', '中路', '发育路', '游走']
    heroes = {'blue': ['姬小满', '大司命', '甄姬', '公孙离', '张飞'],
              'red': ['曹操', '裴擒虎', '不知火舞', '孙尚香', '少司缘']}
    kills = {'blue': [3, 3, 3, 3, 3], 'red': [2, 2, 2, 2, 1]}
    rows = []
    for camp in ('blue', 'red'):
        for slot in range(5):
            rows.append({
                'rowNumber': len(rows) + 2, 'grain': 'match_player', 'aggregated': False, 'raw': {},
                'keys': {'date': '2026-10-06', 'matchId': 'S9', 'opponent': '表格对手',
                         'position': lanes[slot], 'player': f'{camp}{slot}',
                         'hero': heroes[camp][slot], 'side': camp},
                'dimensions': {'win': 1 if camp == 'blue' else 0},
                'metrics': {'kills': {'value': kills[camp][slot]}, 'deaths': {'value': 2},
                            'assists': {'value': 4}, 'gold': {'value': 12000},
                            'damage': {'value': 50000}, 'taken': {'value': 30000},
                            'duration': {'value': 900}},
            })
    (rows_dir / '01-match.jsonl').write_text(
        '\n'.join(json.dumps(row, ensure_ascii=False) for row in rows) + '\n', encoding='utf-8')
    manifest = {
        'schema': 'kpl-sheet-import-v1', 'source': {'name': 'own.csv'},
        'profileSource': 'provided', 'quality': {'rows': 10, 'duplicates': 0},
        'warnings': [], 'createdAt': '2026-10-30',
        'sheets': [{'name': '单局', 'grain': 'match_player', 'aggregated': False, 'rowCount': 10,
                    'rowsFile': 'rows/01-match.jsonl', 'keys': {}, 'metrics': ['kills'],
                    'unmappedColumns': [], 'ownSide': 'blue'}],
    }
    (folder / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
    return 'sheet-own1-单局-S9'


class AnalysisDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / 'training.sqlite3'
        make_db(self.db)
        self.matches = self.root / 'matches'
        self.matches.mkdir()
        (self.matches / 'a.json').write_text(json.dumps(
            bundle('A-bundle', '2026-10-01', 1200, OWN, ENEMY, partial=True), ensure_ascii=False),
            encoding='utf-8')
        (self.matches / 'c.json').write_text(json.dumps(
            bundle('C-bundle', '2026-10-03', 900, C_BLUE, C_RED, scores={'blue': 12, 'red': 8}),
            ensure_ascii=False), encoding='utf-8')
        (self.matches / 'd.json').write_text(json.dumps(
            bundle('D-bundle', '2026-10-05', 600, D_BLUE, D_RED, partial=True), ensure_ascii=False),
            encoding='utf-8')
        self.imports = self.root / 'imports'
        self.imports.mkdir()
        write_sheet_import(self.imports)
        self.repo = AnalysisRepository(self.db, self.matches, self.imports)

    def tearDown(self):
        self.temp.cleanup()

    def test_link_and_sources(self):
        data = self.repo.get()
        self.assertEqual(len(data['matches']), 4)
        linked = next(match for match in data['matches'] if match['dbId'] == 'A')
        self.assertEqual(linked['sources'], ['db', 'bundle'])
        self.assertIsNotNone(linked['process'])
        self.assertTrue(any(player.get('process', {}).get('pov') for player in linked['players']))
        ying = next(player for player in linked['players'] if player['hero'] == '影')
        self.assertEqual(ying['finalSource'], 'db')
        self.assertEqual(ying['gold'], 10000)
        d = next(match for match in data['matches'] if match['key'] == 'D-bundle')
        self.assertEqual(d['ownCamp'], 'blue')

    def test_overview_and_partial_filter(self):
        default = self.repo.overview({'sources': ['db', 'bundle']})
        self.assertEqual(default['matches'], 4)
        self.assertEqual(default['wins'], 3)
        self.assertEqual(default['coverage']['partialRows'], 10)
        self.assertTrue(any('部分数据' in warning for warning in default['warnings']))
        partial = self.repo.overview({'sources': ['db', 'bundle'], 'includePartial': True})
        self.assertGreaterEqual(partial['players'], 10)

    def test_player_metrics_use_paired_minutes(self):
        players = self.repo.player_stats({'sources': ['db', 'bundle']})
        jia = next(player for player in players if player['playerId'] == 'b1')
        self.assertEqual(jia['matches'], 2)
        self.assertEqual(jia['wins'], 2)
        self.assertAlmostEqual(jia['kda'], 6.0, places=2)
        self.assertAlmostEqual(jia['gpm'], 20000 / 38, places=1)

    def test_own_nickname_is_not_split_by_source_camp_token(self):
        """本机记录写 left/right、数据包写 blue/red；同一个本队昵称不应被拆成两个人。"""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            database = root / 'training.sqlite3'
            make_db(database)
            body = db_match('N', '2026-10-06', '对手N', 'left', 'left', 20, OWN, ENEMY)
            body['players'][0].update({'playerId': None, 'label': '同名队员'})
            connection = sqlite3.connect(database)
            connection.execute('INSERT INTO matches VALUES (?,1,?)',
                               ('N', json.dumps(body, ensure_ascii=False)))
            connection.commit()
            connection.close()
            matches = root / 'matches'
            matches.mkdir()
            data = bundle('N-bundle', '2026-10-07', 900, C_BLUE, C_RED, scores={'blue': 12, 'red': 8})
            data['players'][0]['nickname'] = '同名队员'
            (matches / 'n.json').write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
            (root / 'imports').mkdir()
            repo = AnalysisRepository(database, matches, root / 'imports')
            rows = [row for row in repo.player_stats({'sources': ['db', 'bundle']})
                    if row['label'] == '同名队员']
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['matches'], 2)
            self.assertFalse(rows[0]['bound'])

    def test_hero_and_team_stats(self):
        heroes = self.repo.hero_stats({'sources': ['db', 'bundle']})
        ying = next(hero for hero in heroes if hero['hero'] == '影')
        self.assertEqual(ying['picks'], 2)
        self.assertEqual(ying['wins'], 2)
        team = self.repo.team_stats({'sources': ['db', 'bundle']})
        self.assertEqual(team['fullMatches'], 3)
        self.assertEqual(team['wins'], 3)
        self.assertEqual(team['decided'], 3)
        self.assertIsNotNone(team['avgGold'])
        self.assertEqual(team['samples']['goldDiff'], 3)

    def test_sheet_source_is_opt_in_and_aggregate_is_separate(self):
        default = self.repo.matches({'sources': ['db', 'bundle']})
        self.assertEqual(len(default['matches']), 4)
        with_sheet = self.repo.matches({'sources': ['db', 'bundle', 'sheet']})
        self.assertEqual(len(with_sheet['matches']), 5)
        sheet_match = next(item for item in with_sheet['matches'] if item['source'] == 'sheet')
        self.assertEqual(sheet_match['opponent'], '表格对手')
        sheet_detail = self.repo.match_detail(sheet_match['key'])
        self.assertEqual({player['position'] for player in sheet_detail['players']}, {'对抗路'})
        rows = self.repo.player_stats({'sources': ['sheet']})
        self.assertTrue(rows)
        self.assertTrue(any(player['label'].startswith('纸面') for player in rows))
        imports = self.repo.imports()
        self.assertEqual(len(imports['imports']), 1)
        self.assertEqual(len(imports['aggregates']), 1)
        self.assertTrue(self.repo.import_rows('sheet1', '赛季')['aggregated'])

    def test_sheet_own_side_gives_result_and_score(self):
        imports = self.root / 'imports_own'
        imports.mkdir()
        key = write_single_match_import(imports)
        repo = AnalysisRepository(self.db, self.matches, imports)
        matches = repo.matches({'sources': ['sheet']})['matches']
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['key'], key)
        self.assertEqual(matches[0]['ownCamp'], 'blue')
        self.assertEqual(matches[0]['scores'], {'blue': 15, 'red': 9})
        self.assertEqual(matches[0]['result'], 'win')

    def test_match_meta_own_camp_applies_to_sheet_match(self):
        imports = self.root / 'imports_meta'
        imports.mkdir()
        key = write_single_match_import(imports)
        with closing(sqlite3.connect(self.db)) as connection:
            connection.execute('CREATE TABLE IF NOT EXISTS match_meta '
                               '(match_key TEXT PRIMARY KEY, body TEXT NOT NULL, updated_at REAL NOT NULL)')
            connection.execute('INSERT INTO match_meta VALUES(?,?,?)',
                               (key, json.dumps({'ownCamp': 'red'}, ensure_ascii=False), 0.0))
            connection.commit()
        repo = AnalysisRepository(self.db, self.matches, imports)
        match = repo.matches({'sources': ['sheet']})['matches'][0]
        self.assertEqual(match['ownCamp'], 'red')
        self.assertEqual(match['result'], 'loss')

    def test_match_detail_and_trend(self):
        detail = self.repo.match_detail('db-A')
        self.assertIsNotNone(detail)
        self.assertTrue(detail['process']['timeline'])
        trend = self.repo.player_trend('b1', {'sources': ['db', 'bundle']})
        self.assertEqual(len(trend['points']), 2)

    def test_api(self):
        app = create_app(self.db, self.matches, self.imports)
        client = TestClient(app, base_url='http://127.0.0.1')
        self.assertEqual(client.get('/api/analysis/overview').status_code, 200)
        self.assertEqual(client.get('/api/analysis/players').status_code, 200)
        self.assertGreaterEqual(len(client.get('/api/analysis/players?includePartial=1').json()['players']), 10)
        self.assertEqual(client.get('/api/analysis/heroes').status_code, 200)
        self.assertEqual(client.get('/api/analysis/teams').status_code, 200)
        matches = client.get('/api/analysis/matches').json()['matches']
        self.assertEqual(len(matches), 4)
        detail = client.get('/api/analysis/matches/db-A')
        self.assertEqual(detail.status_code, 200)
        self.assertTrue(detail.json()['process']['timeline'])
        self.assertEqual(client.get('/api/analysis/matches/missing').status_code, 404)
        self.assertEqual(client.get('/api/analysis/sources').status_code, 200)
        imports = client.get('/api/analysis/imports').json()
        self.assertEqual(len(imports['imports']), 1)
        rows = client.get('/api/analysis/imports/sheet1/rows?sheet=赛季')
        self.assertEqual(rows.status_code, 200)
        self.assertTrue(rows.json()['aggregated'])


def db_match_positioned(match_id, date, opponent, side, winner, own_rows, enemy_rows):
    """带实际分路的合成比赛：own_rows / enemy_rows 为 (分路, 英雄, 经济) 列表。"""
    players = []
    enemy_side = 'right' if side == 'left' else 'left'
    for side_name, rows in ((side, own_rows), (enemy_side, enemy_rows)):
        for slot, (position, hero, gold) in enumerate(rows):
            players.append({'side': side_name, 'slot': slot,
                            'playerId': f'b{slot + 1}' if side_name == side else None,
                            'hero': hero, 'position': position, 'kills': 3, 'deaths': 2,
                            'assists': 5, 'gold': gold, 'damage': 20000, 'taken': 15000,
                            'participation': 60, 'rating': '11.0', 'equipment': ''})
    left_score, right_score = (12, 8) if winner == 'left' else (8, 12)
    return {'id': match_id, 'status': 'confirmed', 'date': date, 'opponent': opponent,
            'side': side, 'winner': winner, 'duration': 20, 'session': '训练赛',
            'version': '12.1', 'scores': {'left': left_score, 'right': right_score},
            'players': players}


class DeepAnalyticsTests(unittest.TestCase):
    """对位 / 画像 / 协同 / 过程 四个深度分析端点。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / 'training.sqlite3'
        connection = sqlite3.connect(self.db)
        connection.executescript('''
          CREATE TABLE settings (id INTEGER PRIMARY KEY, body TEXT NOT NULL);
          CREATE TABLE matches (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, body TEXT NOT NULL);
        ''')
        connection.execute('INSERT INTO settings VALUES (1,?)',
                           (json.dumps({'teamName': '测试队', 'roster': ROSTER}, ensure_ascii=False),))
        own_a = [('对抗路', '关羽', 9000), ('打野', '李白', 10000), ('中路', '貂蝉', 9500),
                 ('发育路', '后羿', 11000), ('游走', '张飞', 7000)]
        enemy_a = [('对抗路', '猪八戒', 8000), ('打野', '孙悟空', 9000), ('中路', '小乔', 9800),
                   ('发育路', '狄仁杰', 10500), ('游走', '鬼谷子', 6800)]
        own_b = [('对抗路', '关羽', 8500), ('打野', '李白', 9500), ('中路', '貂蝉', 9000),
                 ('发育路', '后羿', 10000), ('游走', '张飞', 6500)]
        enemy_b = [('对抗路', '猪八戒', 9000), ('打野', '孙悟空', 9200), ('中路', '小乔', 9100),
                   ('发育路', '狄仁杰', 10800), ('游走', '鬼谷子', 6600)]
        bodies = [
            db_match_positioned('M1', '2026-10-01', '对手A', 'left', 'left', own_a, enemy_a),
            db_match_positioned('M2', '2026-10-02', '对手B', 'right', 'left', own_b, enemy_b),
        ]
        bodies[0]['bp'] = {'bans': {'left': ['沈梦溪'], 'right': ['敖隐']},
                           'picks': {'left': ['关羽', '李白'], 'right': ['猪八戒']},
                           'firstPick': 'left', 'notes': ''}
        bodies[0]['events'] = [
            {'type': 'tyrant', 'side': 'left', 't': '2:10'},
            {'type': 'tyrant', 'side': 'right', 't': None},
            {'type': 'tower', 'side': 'left', 't': None},
            {'type': 'tower', 'side': 'left', 't': None},
            {'type': 'tower', 'side': 'right', 't': None},
            {'type': 'firstTower', 'side': 'left', 't': '5:30'},
        ]
        for body in bodies:
            connection.execute('INSERT INTO matches VALUES (?,1,?)',
                               (body['id'], json.dumps(body, ensure_ascii=False)))
        connection.commit()
        connection.close()
        self.matches = self.root / 'matches'
        self.matches.mkdir()
        long_bundle = bundle('P-bundle', '2026-10-06', 600, C_BLUE, C_RED)
        long_bundle['team']['timeline'] = [
            {'gameTime': 0, 'blueGold': 1500, 'redGold': 1500, 'blueKills': 0, 'redKills': 0},
            {'gameTime': 300, 'blueGold': 18000, 'redGold': 16000, 'blueKills': 6, 'redKills': 3},
            {'gameTime': 600, 'blueGold': 40000, 'redGold': 35000, 'blueKills': 12, 'redKills': 7},
        ]
        (self.matches / 'p.json').write_text(json.dumps(long_bundle, ensure_ascii=False), encoding='utf-8')
        short_bundle = bundle('Q-bundle', '2026-10-07', 1200, C_BLUE, C_RED)
        short_bundle['team']['timeline'] = [
            {'gameTime': 0, 'blueGold': 1500, 'redGold': 1500, 'blueKills': 0, 'redKills': 0},
            {'gameTime': 60, 'blueGold': 2200, 'redGold': 2100, 'blueKills': 1, 'redKills': 0},
        ]
        (self.matches / 'q.json').write_text(json.dumps(short_bundle, ensure_ascii=False), encoding='utf-8')
        self.imports = self.root / 'imports'
        self.imports.mkdir()
        self.client = TestClient(create_app(self.db, self.matches, self.imports))

    def tearDown(self):
        self.temp.cleanup()

    def test_lane_matchups(self):
        value = self.client.get('/api/analysis/lane-matchups').json()
        lanes = {item['position']: item for item in value['positions']}
        self.assertEqual(lanes['对抗路']['n'], 2)
        self.assertEqual(lanes['对抗路']['avgDiff'], 250)
        self.assertEqual(lanes['对抗路']['aheadRate'], 50.0)
        self.assertEqual(lanes['对抗路']['winWhenAhead'], 100.0)
        top_lane = next(item for item in value['positions'] if item['position'] == '发育路')
        self.assertEqual(top_lane['avgDiff'], -150)
        rows = value['rows']
        self.assertEqual(len(rows), 10)
        self.assertTrue(all(row['dbId'] in ('M1', 'M2') for row in rows))

    def test_profiles(self):
        value = self.client.get('/api/analysis/profiles').json()
        players = {item['key']: item for item in value['players']}
        self.assertEqual(len(players), 5)
        guanyu = players['b1']
        self.assertEqual(guanyu['games'], 2)
        self.assertEqual(guanyu['mainPosition'], '对抗路')
        self.assertEqual(guanyu['metrics']['kda']['n'], 2)
        self.assertIn('goldShare', guanyu['deviations'])
        lane = next(item for item in value['baselines'] if item['position'] == '对抗路')
        self.assertEqual(lane['n'], 2)

    def test_pairs(self):
        value = self.client.get('/api/analysis/pairs').json()
        pair = next(item for item in value['pairs']
                    if {item['a']['key'], item['b']['key']} == {'b1', 'b2'})
        self.assertEqual(pair['games'], 2)
        self.assertEqual(pair['wins'], 1)
        self.assertEqual(pair['winRate'], 50.0)

    def test_process_gate_and_aggregates(self):
        value = self.client.get('/api/analysis/process').json()
        self.assertEqual(value['aggregate']['games'], 1)  # Q-bundle 覆盖不足被门控排除
        self.assertEqual(value['aggregate']['avgDiffAt']['300'], 2000)
        self.assertEqual(value['aggregate']['avgDiffAt']['600'], 5000)
        self.assertIsNone(value['aggregate']['leadAt10Conversion'])  # 数据包无胜负，不冒充
        entry = value['matches'][0]
        self.assertEqual(entry['coverage'], 100.0)
        self.assertEqual(entry['diffAt']['600'], 5000)

    def test_bp_summary(self):
        value = self.client.get('/api/analysis/bp').json()
        self.assertEqual(value['matchesWithBp'], 1)
        bans = {item['hero']: item for item in value['bans']}
        self.assertEqual(bans['沈梦溪']['byLeft'], 1)
        self.assertEqual(bans['沈梦溪']['leftWinRate'], 100.0)  # 左方禁用且左方获胜
        self.assertEqual(bans['敖隐']['byRight'], 1)
        picks = {item['hero']: item for item in value['ownPicks']}
        self.assertEqual(picks['关羽'], {'hero': '关羽', 'count': 1, 'wins': 1, 'decided': 1, 'winRate': 100.0})
        first_pick = next(item for item in value['orderEffect'] if item['order'] == 1)
        self.assertEqual(first_pick['n'], 1)
        habits = {item['opponent']: item for item in value['opponents']}
        self.assertEqual(habits['对手A']['bans'], [['敖隐', 1]])
        self.assertEqual(habits['对手A']['picks'], [['猪八戒', 1]])

    def test_objectives(self):
        value = self.client.get('/api/analysis/objectives').json()
        agg = value['aggregate']
        self.assertEqual(agg['tyrant']['own'], 1)
        self.assertEqual(agg['tyrant']['enemy'], 1)
        self.assertEqual(agg['tyrant']['rateWhenWin'], 50.0)
        self.assertEqual(agg['towers']['avgDiff'], 1.0)
        self.assertEqual(agg['towers']['diffWhenWin'], 1.0)
        self.assertEqual(agg['firstTower']['winRateWhenOwnFirst'], 100.0)
        row = value['rows'][0]
        self.assertEqual(row['firstTower'], 'own')
        self.assertEqual(row['towerDiff'], 1)


class BundleDurationTests(unittest.TestCase):
    """营地包缺顶层 duration 时：官方回放兜底 + 分钟指标样本对齐。

    线上真实故障：53/64 局 bundle 的 match.duration 为 null，GPM/DPM 把
    「所有局的金币」除以「少数局的总分钟」，指标虚高 5-7 倍且无任何提示。
    """

    def test_official_replay_duration_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            db = root / 'training.sqlite3'
            make_db(db)
            matches = root / 'matches'
            matches.mkdir()
            value = bundle('E-bundle', '2026-10-06', None, OWN, ENEMY)
            value['match']['officialReplay'] = {'id': 'camp-777'}
            (matches / 'e.json').write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
            official = root / 'official_replays' / 'camp-777'
            official.mkdir(parents=True)
            (official / 'normalized.json').write_text(
                json.dumps({'match': {'durationSec': 900.0}}), encoding='utf-8')
            imports = root / 'imports'
            imports.mkdir()
            repo = AnalysisRepository(db, matches, imports, official_dir=root / 'official_replays')
            loaded = [match for match in repo.get()['matches'] if match['bundleKey'] == 'E-bundle'][0]
            self.assertEqual(loaded['duration'], 900)

    def test_minute_metrics_only_use_paired_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            db = root / 'training.sqlite3'
            make_db(db)
            matches = root / 'matches'
            matches.mkdir()
            # 同一选手两局：一局有 10 分钟时长，另一局时长缺失但金币齐全。
            paired = bundle('F1-bundle', '2026-10-06', 600, OWN, ENEMY)
            (matches / 'f1.json').write_text(json.dumps(paired, ensure_ascii=False), encoding='utf-8')
            missing = bundle('F2-bundle', '2026-10-07', None, OWN, ENEMY)
            (matches / 'f2.json').write_text(json.dumps(missing, ensure_ascii=False), encoding='utf-8')
            imports = root / 'imports'
            imports.mkdir()
            repo = AnalysisRepository(db, matches, imports)
            players = repo.player_stats({'sources': ['bundle']})
            player = next(item for item in players if item['label'] == OWN[0])
            # 只统计「时长+金币都存在」的那局：11000 / 10 分钟 = 1100。
            # 修复前会把两局金币 22000 都算进分子 → 2200。
            self.assertAlmostEqual(player['gpm'], 1100, places=1)
            self.assertAlmostEqual(player['gpmMinutes'], 10, places=1)


class WinnerTruthTests(unittest.TestCase):
    """补录本队阵营时不得按击杀数改写胜负。

    王者荣耀的胜负由拆水晶决定：真实数据里存在 25:26 蓝方获胜的对局。
    旧逻辑在应用 ownCamp 补录时按「击杀多的一方获胜」覆盖 winnerCamp，
    会把这类局的结果静默翻转，污染胜率统计。
    """

    def test_own_camp_patch_keeps_official_winner(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            db = root / 'training.sqlite3'
            make_db(db)
            matches = root / 'matches'
            matches.mkdir()
            value = bundle('G-bundle', '2026-10-08', 900, OWN, ENEMY,
                           scores={'blue': 25, 'red': 26})
            value['match']['winnerCamp'] = 'blue'  # 营地真值：蓝方获胜，尽管击杀更少
            (matches / 'g.json').write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
            with closing(sqlite3.connect(db)) as connection:
                connection.execute('CREATE TABLE IF NOT EXISTS match_meta '
                                   '(match_key TEXT PRIMARY KEY, body TEXT NOT NULL, updated_at REAL NOT NULL)')
                connection.execute('INSERT INTO match_meta VALUES(?,?,?)',
                                   ('G-bundle', json.dumps({'ownCamp': 'blue'}), 0.0))
                connection.commit()
            imports = root / 'imports'
            imports.mkdir()
            repo = AnalysisRepository(db, matches, imports)
            match = [item for item in repo.get()['matches'] if item['key'] == 'G-bundle'][0]
            self.assertEqual(match['ownCamp'], 'blue')
            self.assertEqual(match['winnerCamp'], 'blue')


if __name__ == '__main__':
    unittest.main()

