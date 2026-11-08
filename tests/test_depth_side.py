"""深度分析的分边（我方/对方）标注层测试。

覆盖四件事：
  1. 营地 position 编码 → 中文路名映射（0=对抗路 1=中路 2=发育路 3=打野 4=游走）。
  2. 我方阵营自动推断：营地详情 head.acntCamp（取数账号 = 本方选手账号），
     match_meta（match_key = 'camp:<gameSeq>'）可手动覆盖并命名对手。
  3. _apply_side 按 own/opp（可再按对手战队）过滤行级 facts，双边过程数据不动。
  4. 对局分边页用的 camp_games 清单与深度 API 读的是同一份覆盖层。
"""
import json
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from depth_api import (_apply_side, _camp_meta, _filter_matches, _signature, analysis_payload,
                       analyses_catalog, build_facts)
from studio_api import camp_games

ROOT = Path(__file__).resolve().parent.parent


def write_camp_game(directory, game_id, acnt_camp, start='2026-10-01 19:30:00', result=True):
    """最小可解析的营地详情：两方各 2 人，只带 build_facts 必需的字段。"""
    def person(player_id, hero, position):
        return {'basicInfo': {'playerId': player_id},
                'battleRecords': {'usedHero': {'heroName': hero}, 'position': position},
                'battleStats': {}}
    body = {'data': {
        'battle': {'usedTime': 900, 'startTime': start},
        'head': {'acntCamp': acnt_camp, 'gameResult': result},
        'blueTeam': {'acntCamp': 1, 'gameResult': result, 'money': 50000},
        'redTeam': {'acntCamp': 2, 'gameResult': not result, 'money': 48000},
        'blueRoles': [person('b1', '项羽', 0), person('b2', '小乔', 1)],
        'redRoles': [person('r1', '马可波罗', 2), person('r2', '赵云', 3)],
    }}
    (directory / f'{game_id}.json').write_text(json.dumps(body, ensure_ascii=False), encoding='utf-8')


class LaneNamingTest(unittest.TestCase):

    def test_lanes_map_camp_position_codes_to_chinese_names(self):
        from depth_api import LANES
        self.assertEqual(LANES, ['对抗路', '中路', '发育路', '打野', '游走'])

    def test_lane_of_uses_the_mapping(self):
        from depth_api import _lane_of
        self.assertEqual(_lane_of({'lane': 0}), '对抗路')
        self.assertEqual(_lane_of({'lane': 4}), '游走')
        self.assertEqual(_lane_of({'lane': None}), '未标注')
        self.assertEqual(_lane_of({'lane': 9}), '未标注')


class OwnCampInferenceTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / 'data' / 'camp_details').mkdir(parents=True)
        write_camp_game(root / 'data' / 'camp_details', 'g1', acnt_camp=1)
        write_camp_game(root / 'data' / 'camp_details', 'g2', acnt_camp=2, result=False)
        self.root = root

    def tearDown(self):
        self.tmp.cleanup()

    def test_own_camp_inferred_from_acnt_camp(self):
        facts = build_facts(self.root)
        self.assertEqual(facts['ownCamps'], {'g1': '蓝', 'g2': '红'})
        matches = {m['id']: m for m in facts['matches']}
        self.assertEqual(matches['g1']['ownCampSource'], 'auto')
        self.assertEqual(matches['g2']['ownCampSource'], 'auto')
        self.assertEqual(facts['campMeta']['auto'], 2)
        self.assertEqual(facts['campMeta']['manual'], 0)

    def test_date_scope_filters_matches_and_their_player_rows(self):
        write_camp_game(self.root / 'data' / 'camp_details', 'g2', 2, '2026-10-02 19:30:00')
        facts = build_facts(self.root)
        selected = _filter_matches(facts, date_from=date(2026, 10, 2), date_to=date(2026, 10, 2))
        self.assertEqual([item['id'] for item in selected['matches']], ['g2'])
        self.assertEqual({item['match'] for item in selected['players']}, {'g2'})

    def test_manual_override_and_opponent_naming(self):
        facts = build_facts(self.root, {'g2': {'ownCamp': 'blue', 'opponent': '星海队'}})
        self.assertEqual(facts['ownCamps']['g2'], '蓝')
        self.assertEqual(facts['opponents'], {'g2': '星海队'})
        self.assertEqual(facts['campMeta']['manual'], 1)
        self.assertEqual(facts['campMeta']['named'], 1)
        self.assertEqual(facts['campMeta']['opponents'], [{'name': '星海队', 'games': 1}])

    def test_camp_meta_reads_match_meta_overlay_from_sqlite(self):
        db = self.root / 'training.sqlite3'
        connection = sqlite3.connect(db)
        try:
            connection.execute('CREATE TABLE match_meta (match_key TEXT PRIMARY KEY, body TEXT NOT NULL, updated_at REAL NOT NULL)')
            connection.execute("INSERT INTO match_meta VALUES ('camp:g2', ?, 1)",
                               (json.dumps({'ownCamp': 'red', 'opponent': '北辰队'}),))
            connection.commit()
        finally:
            connection.close()
        self.assertEqual(_camp_meta(db), {'g2': {'ownCamp': 'red', 'opponent': '北辰队'}})
        facts = build_facts(self.root, _camp_meta(db))
        self.assertEqual(facts['ownCamps']['g2'], '红')
        self.assertEqual(facts['opponents']['g2'], '北辰队')

    def test_camp_meta_missing_table_is_empty(self):
        self.assertEqual(_camp_meta(None), {})
        self.assertEqual(_camp_meta(self.root / 'nope.sqlite3'), {})

    def test_signature_changes_when_camp_annotation_changes(self):
        db = self.root / 'training.sqlite3'
        connection = sqlite3.connect(db)
        try:
            connection.execute('CREATE TABLE match_meta (match_key TEXT PRIMARY KEY, body TEXT NOT NULL, updated_at REAL NOT NULL)')
            connection.commit()
        finally:
            connection.close()
        before = _signature(self.root, db)
        connection = sqlite3.connect(db)
        try:
            connection.execute("INSERT INTO match_meta VALUES ('camp:g1', '{\"opponent\": \"星海队\"}', 2)")
            connection.commit()
        finally:
            connection.close()
        self.assertNotEqual(_signature(self.root, db), before)


class ApplySideTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.facts = {
            'ownCamps': {'g1': '蓝', 'g2': '红'},
            'opponents': {'g1': '星海队', 'g2': '北辰队'},
            'players': [{'match': 'g1', 'camp': '蓝', 'hero': 'A'}, {'match': 'g1', 'camp': '红', 'hero': 'B'},
                        {'match': 'g2', 'camp': '蓝', 'hero': 'C'}, {'match': 'g2', 'camp': '红', 'hero': 'D'},
                        {'match': 'g3', 'camp': '蓝', 'hero': 'E'}],
            'teams': [{'match': 'g1', 'camp': '蓝'}, {'match': 'g1', 'camp': '红'},
                      {'match': 'g2', 'camp': '蓝'}, {'match': 'g2', 'camp': '红'}],
            'dropWindows': [{'game': 'g1', 'camp': '蓝'}, {'game': 'g1', 'camp': '红'},
                            {'game': 'g2', 'camp': '蓝'}, {'game': 'g2', 'camp': '红'}],
            'killEvents': [{'game': 'g1', 'killerCamp': '1'}, {'game': 'g2', 'killerCamp': '2'}],
            'fightFacts': [{'game': 'g1'}, {'game': 'g2'}],
            'replayGames': [{'id': 'g1'}, {'id': 'g2'}],
            'matches': [{'id': 'g1'}, {'id': 'g2'}],
        }

    def test_own_view_keeps_own_rows_only(self):
        result = _apply_side(self.facts, 'own')
        self.assertEqual([p['hero'] for p in result['players']], ['A', 'D'])
        self.assertEqual([t['camp'] for t in result['teams']], ['蓝', '红'])
        self.assertEqual([w['camp'] for w in result['dropWindows']], ['蓝', '红'])

    def test_opp_view_is_the_mirror(self):
        result = _apply_side(self.facts, 'opp')
        self.assertEqual([p['hero'] for p in result['players']], ['B', 'C'])
        self.assertEqual(len(result['dropWindows']), 2)

    def test_team_filter_narrows_to_one_opponent(self):
        result = _apply_side(self.facts, 'opp', team='北辰队')
        # g2 我方在红方 → 对方是蓝方 C；g1 的对手是星海队，被排除
        self.assertEqual([p['hero'] for p in result['players']], ['C'])
        result = _apply_side(self.facts, 'opp', team='没有的队')
        self.assertEqual(result['players'], [])

    def test_two_sided_process_facts_are_not_filtered(self):
        result = _apply_side(self.facts, 'own')
        self.assertEqual(len(result['killEvents']), 2)
        self.assertEqual(len(result['fightFacts']), 2)
        self.assertEqual(len(result['replayGames']), 2)
        self.assertEqual(len(result['matches']), 2)

    def test_rows_without_a_judgeable_own_camp_are_dropped(self):
        # g3 没有 ownCamp（如缺 acntCamp 又未手动覆盖），单边视图不计入
        result = _apply_side(self.facts, 'own')
        self.assertNotIn('g3', [p['match'] for p in result['players']])

    def test_unknown_side_returns_facts_unchanged(self):
        self.assertIs(_apply_side(self.facts, None), self.facts)
        self.assertIs(_apply_side(self.facts, 'all'), self.facts)


class PayloadSideTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.facts = build_facts(ROOT)
        if not cls.facts.get('players'):
            raise unittest.SkipTest('缺少营地对局详情样本（公开仓库不含对局数据）')

    def test_side_filter_is_symmetric_on_real_data(self):
        total = len(self.facts['players'])
        own = analysis_payload(self.facts, 'cs_conversion', side='own')
        opp = analysis_payload(self.facts, 'cs_conversion', side='opp')
        own_n = sum(l['n'] for l in own['lanes'])
        opp_n = sum(l['n'] for l in opp['lanes'])
        self.assertEqual(own_n + opp_n, total)
        self.assertGreater(own_n, 0)
        self.assertGreater(opp_n, 0)

    def test_points_carry_chinese_lane_labels(self):
        p = analysis_payload(self.facts, 'cross_resource_output')
        groups = {pt['group'] for pt in p['points']}
        self.assertTrue(groups)
        self.assertTrue(groups <= {'对抗路', '中路', '发育路', '打野', '游走', '未标注'})

    def test_catalog_exposes_camp_meta_and_sided_flags(self):
        catalog = analyses_catalog(self.facts)
        meta = {a['id']: a for a in catalog}
        for aid in ('time_cross_match', 'time_economy', 'time_events', 'time_kill_rhythm', 'compare_camp'):
            self.assertFalse(meta[aid]['sided'], f'{aid} 是双边过程/视角体检，不应可分边')
        for aid in ('cs_conversion', 'cross_lane_hero'):
            self.assertTrue(meta[aid]['sided'], f'{aid} 应支持分边')
        self.assertTrue(meta['cs_conversion']['samples'])


class CampGamesHelperTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.details = root / 'camp_details'
        self.details.mkdir(parents=True)
        write_camp_game(self.details, 'g1', acnt_camp=1)
        write_camp_game(self.details, 'g2', acnt_camp=2, start='2026-10-02 14:05:00', result=False)
        self.db = root / 'training.sqlite3'

    def tearDown(self):
        self.tmp.cleanup()

    def test_lists_games_with_auto_side_and_date(self):
        games = camp_games(self.details, self.db)
        self.assertEqual([g['id'] for g in games], ['g1', 'g2'])
        self.assertEqual(games[0]['ownCamp'], 'blue')
        self.assertEqual(games[0]['ownCampSource'], 'auto')
        self.assertEqual(games[0]['ownWin'], True)
        self.assertEqual(games[1]['date'], '2026-10-02')
        self.assertEqual(games[1]['ownWin'], False)
        self.assertIsNone(games[0]['opponent'])

    def test_reads_the_same_overlay_as_depth_api(self):
        connection = sqlite3.connect(self.db)
        try:
            connection.execute('CREATE TABLE match_meta (match_key TEXT PRIMARY KEY, body TEXT NOT NULL, updated_at REAL NOT NULL)')
            connection.execute("INSERT INTO match_meta VALUES ('camp:g2', ?, 3)",
                               (json.dumps({'ownCamp': 'blue', 'opponent': '星海队'}),))
            connection.commit()
        finally:
            connection.close()
        games = {g['id']: g for g in camp_games(self.details, self.db)}
        self.assertEqual(games['g2']['ownCamp'], 'blue')
        self.assertEqual(games['g2']['ownCampSource'], 'manual')
        self.assertEqual(games['g2']['opponent'], '星海队')
        from depth_api import _camp_meta
        self.assertEqual(_camp_meta(self.db)['g2']['opponent'], '星海队')

    def test_entry_epoch_overrides_yearless_text_start(self):
        """新同步的 dtEventTime 精确到秒，优先于只有 MM-DD 的 startTime。"""
        write_camp_game(self.details, 'g3', acnt_camp=1, start='10-02 14:05')
        path = self.details / 'g3.json'
        body = json.loads(path.read_text(encoding='utf-8'))
        body['_campEntry'] = {'dtEventTime': '1790925600', 'usedTime': 900}
        path.write_text(json.dumps(body, ensure_ascii=False), encoding='utf-8')
        games = {g['id']: g for g in camp_games(self.details, None)}
        self.assertEqual(games['g3']['date'], '2026-10-02')
        self.assertEqual(games['g3']['start'], '2026-10-02T15:05:00+08:00')
        self.assertEqual(games['g3']['eventAt'], '2026-10-02T15:20:00+08:00')
        self.assertEqual(games['g3']['durationSec'], 900)

    def test_missing_db_yields_auto_only(self):
        games = camp_games(self.details, None)
        self.assertEqual([g['ownCampSource'] for g in games], ['auto', 'auto'])


class LaneMatchupTest(unittest.TestCase):
    """对位对比：同分路双方各一人时，生成我方 − 对方的经济 / KDA 对照。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        details = root / 'data' / 'camp_details'
        details.mkdir(parents=True)
        self.root = root

        def person(player_id, hero, position, gold, damage):
            return {
                'basicInfo': {'playerId': player_id},
                'battleRecords': {'usedHero': {'heroName': hero}, 'position': position,
                                  'finalEquips': []},
                'battleStats': {'money': gold, 'killCnt': 4, 'deadCnt': 2, 'assistCnt': 6,
                                'totalHeroHurtCnt': damage, 'totalHurtCnt': damage,
                                'totalBehurtCnt': 1200},
            }

        body = {'data': {
            'battle': {'usedTime': 900, 'startTime': '2026-10-01 19:30:00'},
            'head': {'acntCamp': 1, 'gameResult': True},
            'blueTeam': {'acntCamp': 1, 'gameResult': True, 'money': 50000},
            'redTeam': {'acntCamp': 2, 'gameResult': False, 'money': 48000},
            'blueRoles': [person(f'b{i}', f'蓝{i}', i, 10000 + i * 100, 20000 + i * 100)
                          for i in range(5)],
            'redRoles': [person(f'r{i}', f'红{i}', i, 9000 + i * 100, 18000 + i * 100)
                         for i in range(5)],
        }}
        (details / 'm1.json').write_text(json.dumps(body, ensure_ascii=False), encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def test_catalog_exposes_lane_matchup(self):
        facts = build_facts(self.root)
        item = next(a for a in analyses_catalog(facts) if a['id'] == 'lane_matchup')
        self.assertEqual(item['direction'], '对比')
        self.assertEqual(item['viz'], 'matchup')
        self.assertEqual(item['filters'], ['team', 'player'])
        self.assertTrue(item['boundary'])

    def test_payload_pairs_same_lane_and_names_lanes(self):
        facts = build_facts(self.root)
        payload = analysis_payload(facts, 'lane_matchup')
        self.assertEqual(payload['viz'], 'matchup')
        self.assertEqual(len(payload['roads']), 5)
        self.assertEqual([lane['lane'] for lane in payload['lanes']],
                         ['对抗路', '中路', '发育路', '打野', '游走'])
        first = payload['roads'][0]
        self.assertEqual(first['goldDiff'], 1000)
        self.assertEqual(first['ownHero'], '蓝0')
        self.assertEqual(first['enemyHero'], '红0')
        self.assertTrue(first['win'])
        self.assertIn('19:30', first['label'])

    def test_game_labels_never_expose_raw_ids(self):
        from depth_api import _build_game_labels
        labels = _build_game_labels(
            [{'id': '1793595424', 'start': '', 'opponent': '星海队'}], [], {})
        self.assertEqual(labels['1793595424'], 'vs 星海队 · 第1局')
        labels = _build_game_labels(
            [{'id': 'g1', 'start': '', 'opponent': ''}], [], {})
        self.assertEqual(labels['g1'], '训练赛 · 第1局')
        labels = _build_game_labels(
            [{'id': 'g2', 'start': '2026-10-01 19:30:00', 'opponent': ''}], [], {})
        self.assertEqual(labels['g2'], '10-01 19:30 · 训练赛')


if __name__ == '__main__':
    unittest.main()
