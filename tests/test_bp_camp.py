"""营地 BP 名单接入 + 双来源聚合的回归测试。"""
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis_data import AnalysisRepository  # noqa: E402
from bp_camp import merge_bp_sources, parse_camp_bp, structured_names  # noqa: E402
import channel_store  # noqa: E402
from test_analysis_data import OWN, ENEMY, ROSTER, bundle, db_match  # noqa: E402


def camp_detail():
    """最小 battledetail：双方 ban/pick 名单 + 十人面板 + 分路位置。"""
    blue = ['鲁班七号', '嫦娥', '刘禅', '李元芳', '项羽']
    red = ['瑶', '阿轲', '安琪拉', '虞姬', '钟无艳']
    ids = {'鲁班七号': 112, '嫦娥': 515, '刘禅': 114, '李元芳': 173, '项羽': 135,
           '瑶': 505, '阿轲': 116, '安琪拉': 142, '虞姬': 174, '钟无艳': 117,
           '盾山': 509, '芈月': 121, '海月': 521, '孙悟空': 167,
           '庄周': 113, '张良': 156}
    # 营地真实 position：0 对抗路 / 1 中路 / 2 发育路 / 3 打野 / 4 游走
    positions = {'鲁班七号': 2, '嫦娥': 1, '刘禅': 4, '李元芳': 3, '项羽': 0,
                 '瑶': 4, '阿轲': 3, '安琪拉': 1, '虞姬': 2, '钟无艳': 0}

    def hero(name):
        return {'heroId': ids[name], 'heroName': name, 'heroIcon': 'https://example.invalid/x.jpg'}

    def role(name, position, camp):
        return {
            'basicInfo': {'playerId': f'p-{camp}-{position}', 'roleName': f'选手{camp}{position}',
                          'acntCamp': camp},
            'battleStats': {'killCnt': '3', 'deadCnt': '1', 'assistCnt': '5',
                            'money': '9000', 'totalHurtCnt': '20000', 'totalBehurtCnt': '15000',
                            'joinGamePercent': '0.6', 'gradeGame': '8.0'},
            'battleRecords': {'usedHero': hero(name), 'position': position, 'finalEquips': []},
        }

    return {'data': {
        'head': {'acntCamp': 1, 'gameResult': True, 'mapName': '排位赛'},
        'battle': {'usedTime': 900, 'startTime': '11-05 20:00', 'mapName': '排位赛'},
        'blueTeam': {'gameResult': True, 'money': 39000, 'killCnt': 28,
                     'banHeros': [hero('盾山'), hero('芈月'), hero('海月')],
                     'pickHeros': [hero(name) for name in blue]},
        'redTeam': {'gameResult': False, 'money': 30000, 'killCnt': 7,
                    'banHeros': [hero('孙悟空'), hero('庄周'), hero('张良')],
                    'pickHeros': [hero(name) for name in red]},
        'blueRoles': [role(name, positions[name], 1) for name in blue],
        'redRoles': [role(name, positions[name], 2) for name in red],
    }}


class ParseCampBpTest(unittest.TestCase):
    def test_ban_pick_lanes_and_local_icons(self):
        bp = parse_camp_bp(camp_detail(), 'seq-1')
        names = structured_names(bp)
        self.assertEqual(names['bans']['left'], ['盾山', '芈月', '海月'])
        self.assertEqual(len(names['picks']['left']), 5)
        self.assertEqual(bp['winnerSide'], 'left')
        self.assertEqual(bp['ownSide'], 'left')
        self.assertFalse(bp['pickOrderKnown'])
        self.assertIsNone(bp['firstPick'])
        self.assertTrue(all(item['icon'].startswith('/catalog/icons/hero-')
                            for group in bp['bans'].values() for item in group))
        self.assertEqual(bp['picks']['left'][4]['lane'], '对抗路')
        self.assertEqual(bp['lanes']['鲁班七号'], '发育路')
        self.assertEqual(bp['teamStats']['left']['killCnt'], 28)

    def test_only_hero_id_uses_local_hero_catalog(self):
        detail = {'data': {'head': {}, 'blueTeam': {'banHeros': [{'heroId': 521}]},
                           'redTeam': {'banHeros': []}}}
        bp = parse_camp_bp(detail, 'seq-2')
        self.assertEqual(structured_names(bp)['bans']['left'], ['海月'])
        self.assertEqual(bp['bans']['left'][0]['icon'], '/catalog/icons/hero-521.png')

    def test_no_bp_returns_none(self):
        self.assertIsNone(parse_camp_bp({'data': {'blueTeam': {}, 'redTeam': {}}}))


class MergeSourcesTest(unittest.TestCase):
    def setUp(self):
        self.camp = parse_camp_bp(camp_detail(), 'seq-1')

    def test_manual_wins_over_camp_and_keeps_order(self):
        manual = {'bans': {'left': ['沈梦溪'], 'right': ['敖隐']},
                  'picks': {'left': ['影', '铠'], 'right': ['程咬金']},
                  'firstPick': 'left'}
        record = merge_bp_sources(manual, self.camp,
                                  {'ownCamp': 'left', 'winnerCamp': 'left'})
        self.assertEqual(record['source'], 'manual')
        self.assertTrue(record['pickOrderKnown'])
        self.assertEqual(record['firstPick'], 'left')
        self.assertEqual([item['name'] for item in record['bans']['left']], ['沈梦溪'])
        self.assertTrue(record['heroMeta']['影']['icon'])

    def test_camp_fallback_has_no_order(self):
        record = merge_bp_sources(None, self.camp, {'ownCamp': 'left'})
        self.assertEqual(record['source'], 'camp')
        self.assertFalse(record['pickOrderKnown'])
        self.assertIsNone(record['firstPick'])
        self.assertEqual(len(record['picks']['right']), 5)

    def test_no_source(self):
        self.assertIsNone(merge_bp_sources('旧文本 BP', None, {}))


class AttachCampBpTest(unittest.TestCase):
    def test_channel_and_source_keep_ban_and_add_pick(self):
        channel = channel_store.blank({'date': '2026-11-05', 'opponent': '测试对手'})
        channel_store.attach_camp_detail(channel, 'seq-1', camp_detail(), None, '测试')
        camp = channel['sources']['camp']
        self.assertEqual(camp['ban']['blue'][0], 509)  # 盾山：原始 heroId 口径不变
        self.assertEqual(len(camp['pickNames']['blue']), 5)
        self.assertEqual(camp['bp']['source'], 'camp-battledetail')
        self.assertEqual(len(camp['bp']['picks']['right']), 5)


class BpSummaryTwoSourcesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db = root / 'training.sqlite3'
        self.matches_dir = root / 'matches'
        self.imports_dir = root / 'imports'
        self.matches_dir.mkdir()
        self.imports_dir.mkdir()
        connection = sqlite3.connect(self.db)
        connection.executescript('''
          CREATE TABLE settings (id INTEGER PRIMARY KEY, body TEXT NOT NULL);
          CREATE TABLE matches (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, body TEXT NOT NULL);
        ''')
        connection.execute('INSERT INTO settings VALUES (1,?)',
                           (json.dumps({'teamName': '测试队', 'roster': ROSTER}, ensure_ascii=False),))
        manual = db_match('A', '2026-10-01', '对手A', 'left', 'left', 1200, OWN, ENEMY)
        manual['bp'] = {'bans': {'left': ['沈梦溪'], 'right': ['敖隐']},
                        'picks': {'left': ['影', '铠'], 'right': ['程咬金']},
                        'firstPick': 'left', 'notes': ''}
        connection.execute('INSERT INTO matches VALUES (?,1,?)',
                           ('A', json.dumps(manual, ensure_ascii=False)))
        connection.commit()
        connection.close()

        value = bundle('camp-1', '2026-10-03', 900,
                       ['鲁班七号', '嫦娥', '刘禅', '李元芳', '项羽'],
                       ['瑶', '阿轲', '安琪拉', '虞姬', '钟无艳'], own='blue')
        body = parse_camp_bp(camp_detail(), 'seq-1')
        value['match'].update({'campBp': body, 'winnerCamp': 'blue',
                               'ownCamp': 'blue', 'opponent': '对手C'})
        (self.matches_dir / 'camp-1.json').write_text(
            json.dumps(value, ensure_ascii=False), encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def test_aggregates_both_sources_without_mixing_order(self):
        repo = AnalysisRepository(self.db, self.matches_dir, self.imports_dir)
        value = repo.bp_summary({'sources': ['db', 'bundle'], 'includePartial': True})
        self.assertEqual(value['matchesWithBp'], 2)
        self.assertEqual(value['campBpMatches'], 1)
        self.assertEqual(value['manualBpMatches'], 1)
        self.assertIn('沈梦溪', {item['hero'] for item in value['bans']})
        self.assertIn('盾山', {item['hero'] for item in value['bans']})
        self.assertIn('影', {item['hero'] for item in value['ownPicks']})
        self.assertIn('鲁班七号', {item['hero'] for item in value['ownPicks']})
        self.assertTrue(value['heroMeta']['盾山']['icon'].startswith('/catalog/icons/'))
        first = next(item for item in value['orderEffect'] if item['order'] == 1)
        self.assertEqual(first['n'], 1)  # 只有人工录入贡献手序
        sources = {row['source'] for row in value['matches']}
        self.assertEqual(sources, {'manual', 'camp'})
        self.assertTrue(any(row['result'] == 'win' for row in value['matches']))
        self.assertIn('lanes', value)
        self.assertIn('pressure', value)
        self.assertIn('pairs', value)

    def test_camp_only_excludes_local_matches_and_prefers_camp_lineup(self):
        path = self.matches_dir / 'camp-1.json'
        bundle_value = json.loads(path.read_text(encoding='utf-8'))
        bundle_value['match']['bp'] = {
            'bans': {'left': ['沈梦溪'], 'right': []},
            'picks': {'left': ['影'], 'right': []},
            'firstPick': 'left',
        }
        path.write_text(json.dumps(bundle_value, ensure_ascii=False), encoding='utf-8')
        repo = AnalysisRepository(self.db, self.matches_dir, self.imports_dir)
        filters = {'sources': ['db', 'bundle'], 'campOnly': True, 'campFirst': True}
        self.assertEqual({item['key'] for item in repo.matches(filters)['matches']}, {'camp-1'})
        bp = repo.bp_summary(filters)
        self.assertEqual(bp['campBpMatches'], 1)
        self.assertEqual(bp['manualBpMatches'], 0)
        self.assertIn('鲁班七号', {item['hero'] for item in bp['ownPicks']})
        self.assertNotIn('影', {item['hero'] for item in bp['ownPicks']})


if __name__ == '__main__':
    unittest.main()
