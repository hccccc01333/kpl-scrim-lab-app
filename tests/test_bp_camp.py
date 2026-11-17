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
from bp_camp import merge_bp_sources, normalize_camp_events, parse_camp_bp, structured_names  # noqa: E402
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
    def test_explicit_bp_order_is_labeled_as_bp_order(self):
        detail = camp_detail()
        data = detail['data']
        left_bans = ['盾山', '芈月', '海月', '孙悟空', '庄周']
        right_bans = ['张良', '大乔', '少司缘', '朵莉亚', '东皇太一']
        data['blueTeam']['banHeros'] = [{'heroName': name} for name in left_bans]
        data['redTeam']['banHeros'] = [{'heroName': name} for name in right_bans]
        data['bpOrder'] = {
            'mode': 'scrim',
            'bans': {'left': left_bans, 'right': right_bans},
            'picks': {'left': ['鲁班七号', '嫦娥', '刘禅', '李元芳', '项羽'],
                      'right': ['瑶', '阿轲', '安琪拉', '虞姬', '钟无艳']},
            'firstPick': 'left',
        }
        bp = parse_camp_bp(detail, 'seq-order')
        self.assertEqual(bp['orderSource'], 'bpOrder')
        self.assertTrue(bp['pickOrderKnown'])
        self.assertFalse(bp['orderAssumed'])
        self.assertEqual(bp['firstPick'], 'left')

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


def test_catalog_index_reloads_after_file_change(tmp_path):
    """catalog.json 改完后不重启进程也要读到新英雄（按 mtime 失效）。"""
    import bp_camp

    catalog = tmp_path / 'catalog.json'
    catalog.write_text(json.dumps({'entries': [
        {'kind': 'hero', 'name': '旧英雄', 'id': 'hero-1', 'icon': None}]},
        ensure_ascii=False), encoding='utf-8')
    original = bp_camp.CATALOG_PATH
    bp_camp.CATALOG_PATH = catalog
    bp_camp._CATALOG_CACHE.update({'stamp': object(), 'value': ({}, {})})
    try:
        assert bp_camp.catalog_name('1') == '旧英雄'
        catalog.write_text(json.dumps({'entries': [
            {'kind': 'hero', 'name': '新英雄', 'id': 'hero-2', 'icon': None}]},
            ensure_ascii=False), encoding='utf-8')
        import os
        os.utime(catalog, ns=(catalog.stat().st_atime_ns, catalog.stat().st_mtime_ns + 10_000_000))
        assert bp_camp.catalog_name('2') == '新英雄'
        assert bp_camp.catalog_name('1') is None
    finally:
        bp_camp.CATALOG_PATH = original
        bp_camp._CATALOG_CACHE.update({'stamp': object(), 'value': ({}, {})})


def short_scrim_events(blue_picks=None, red_picks=None, *, red_bans=None):
    """旧短手序事件；只用于验证 20 手规则会拒绝它。"""
    blue = blue_picks or ['鲁班七号', '嫦娥', '刘禅', '李元芳', '项羽']
    red = red_picks or ['瑶', '阿轲', '安琪拉', '虞姬', '钟无艳']
    ban_blue = ['盾山', '芈月', '海月']
    ban_red = red_bans or ['孙悟空', '庄周']
    pick_order = [('1', blue[0]), ('2', red[0]), ('2', red[1]), ('1', blue[1]), ('1', blue[2]),
                  ('2', red[2]), ('2', red[3]), ('1', blue[3]), ('1', blue[4]), ('2', red[4])]
    events, order = [], 1
    # Ban 排程 B R B R B：蓝方 3 个（第 1/3/5 手），红方 2 个（第 2/4 手）。
    ban_sequence = [('1', ban_blue[0]), ('2', ban_red[0]), ('1', ban_blue[1]),
                    ('2', ban_red[1]), ('1', ban_blue[2])]
    for camp, hero in ban_sequence:
        events.append({'order': order, 'action': 'ban', 'hero': hero, 'camp': camp})
        order += 1
    for camp, hero in pick_order:
        events.append({'order': order, 'action': 'pick', 'hero': hero, 'camp': camp})
        order += 1
    return events


def camp_detail_5ban():
    """双方各 5 个 ban 的面板；选人列表故意反转，用来验证合并按事件重排。"""
    detail = camp_detail()
    blue = detail['data']['blueTeam']
    red = detail['data']['redTeam']
    blue['banHeros'] = blue['banHeros'] + [
        {'heroId': 9001, 'heroName': '盘古'}, {'heroId': 9002, 'heroName': '墨子'}]
    red['banHeros'] = red['banHeros'] + [
        {'heroId': 9003, 'heroName': '女娲'}, {'heroId': 9004, 'heroName': '大乔'}]
    blue['pickHeros'] = list(reversed(blue['pickHeros']))
    return detail


def scrim_events_20(blue_picks=None, red_picks=None):
    """按 20 手排程构造事件：蓝红交替 10 Ban → B1 R2 B2 R2 B2 R1 Pick。"""
    blue = blue_picks or ['鲁班七号', '嫦娥', '刘禅', '李元芳', '项羽']
    red = red_picks or ['瑶', '阿轲', '安琪拉', '虞姬', '钟无艳']
    ban_blue = ['盾山', '芈月', '海月', '盘古', '墨子']
    ban_red = ['孙悟空', '庄周', '张良', '女娲', '大乔']
    sequence = []
    for index in range(5):
        sequence.append(('ban', '1', ban_blue[index]))
        sequence.append(('ban', '2', ban_red[index]))
    pick_order = [('1', blue[0]), ('2', red[0]), ('2', red[1]), ('1', blue[1]), ('1', blue[2]),
                  ('2', red[2]), ('2', red[3]), ('1', blue[3]), ('1', blue[4]), ('2', red[4])]
    sequence.extend(('pick', camp, hero) for camp, hero in pick_order)
    return [{'order': index + 1, 'action': action, 'camp': camp, 'hero': hero}
            for index, (action, camp, hero) in enumerate(sequence)]


class CampEventTests(unittest.TestCase):
    """normalize_camp_events：20 手逐手 BP 的规则与终局名单一致性守卫。"""

    def test_valid_events_pass(self):
        clean, warnings = normalize_camp_events(camp_detail_5ban(), scrim_events_20(), 'seq-20')
        self.assertEqual(len(clean), 20)
        self.assertEqual([e['order'] for e in clean], list(range(1, 21)))
        self.assertEqual(warnings, [])

    def test_camp_alias_blue_left_accepted(self):
        events = scrim_events_20()
        for event in events:
            event['camp'] = {'1': 'blue', '2': 'red'}[event['camp']]
        clean, _ = normalize_camp_events(camp_detail_5ban(), events, 'seq-20')
        self.assertEqual(clean[0]['camp'], '1')

    def test_wrong_action_schedule_rejected(self):
        events = scrim_events_20()
        events[10]['action'] = 'ban'  # 第 11 手必须是 Pick
        with self.assertRaises(ValueError):
            normalize_camp_events(camp_detail_5ban(), events, 'seq-20')

    def test_duplicate_hero_rejected(self):
        events = scrim_events_20()
        events[19]['hero'] = '瑶'
        with self.assertRaises(ValueError):
            normalize_camp_events(camp_detail_5ban(), events, 'seq-20')

    def test_pick_mismatch_rejected(self):
        events = scrim_events_20(blue_picks=['鲁班七号', '嫦娥', '刘禅', '李元芳', '盾山'])
        with self.assertRaises(ValueError):
            normalize_camp_events(camp_detail_5ban(), events, 'seq-20')

    def test_ban_outside_panel_rejected(self):
        events = scrim_events_20()
        events[1]['hero'] = '大乔'
        with self.assertRaises(ValueError):
            normalize_camp_events(camp_detail_5ban(), events, 'seq-20')

    def test_nonsequential_order_rejected(self):
        events = scrim_events_20()
        events[3]['order'] = 9
        with self.assertRaises(ValueError):
            normalize_camp_events(camp_detail_5ban(), events, 'seq-20')

    def test_empty_or_invalid_events_rejected(self):
        with self.assertRaises(ValueError):
            normalize_camp_events(camp_detail_5ban(), [], 'seq-20')
        with self.assertRaises(ValueError):
            normalize_camp_events(camp_detail_5ban(), [{'order': 1}], 'seq-20')

    def test_panel_without_bp_rejected(self):
        with self.assertRaises(ValueError):
            normalize_camp_events({'data': {'blueTeam': {}, 'redTeam': {}}},
                                  scrim_events_20(), 'seq-2')

    def test_import_in_bp_camp_exports(self):
        from bp_camp import normalize_camp_events as fn  # noqa: F401
        self.assertTrue(callable(fn))


class CampEventTwentyTest(unittest.TestCase):
    """5+5 Ban 面板：20 手校验 + 已核验事件套用为 P/B 手序。"""

    def test_twenty_events_pass_on_five_ban_panel(self):
        clean, warnings = normalize_camp_events(camp_detail_5ban(), scrim_events_20(), 'seq-20')
        self.assertEqual(len(clean), 20)
        self.assertEqual([e['order'] for e in clean], list(range(1, 21)))
        self.assertEqual(warnings, [])

    def test_fifteen_events_rejected_on_five_ban_panel(self):
        with self.assertRaises(ValueError) as ctx:
            normalize_camp_events(camp_detail_5ban(), short_scrim_events(), 'seq-20')
        self.assertIn('20 手', str(ctx.exception))

    def test_merge_applies_verified_event_order(self):
        bp = parse_camp_bp(camp_detail_5ban(), 'seq-20')
        # 营地原始排列被反转，合并必须按事件重排而不是照抄
        self.assertEqual(bp['picks']['left'][0]['name'], '项羽')
        record = merge_bp_sources(None, bp, {'ownCamp': 'left'},
                                  events=scrim_events_20())
        self.assertTrue(record['pickOrderKnown'])
        self.assertEqual(record['firstPick'], 'left')
        self.assertEqual([entry['name'] for entry in record['picks']['left']],
                         ['鲁班七号', '嫦娥', '刘禅', '李元芳', '项羽'])
        self.assertEqual([entry['name'] for entry in record['bans']['left']],
                         ['盾山', '芈月', '海月', '盘古', '墨子'])
        self.assertEqual([entry['name'] for entry in record['pickSlots']['left']],
                         ['鲁班七号', '嫦娥', '刘禅', '李元芳', '项羽'])
        self.assertEqual(record['orderSource'], 'draftEvents')

    def test_misaligned_events_keep_order_unknown(self):
        bp = parse_camp_bp(camp_detail_5ban(), 'seq-20')
        events = scrim_events_20(blue_picks=['鲁班七号', '嫦娥', '刘禅', '李元芳', '影'])
        record = merge_bp_sources(None, bp, {}, events=events)
        self.assertFalse(record['pickOrderKnown'])
        self.assertIsNone(record['firstPick'])
        # 不合规的事件（少一手）同样不改记录
        record = merge_bp_sources(None, bp, {}, events=scrim_events_20()[:19])
        self.assertFalse(record['pickOrderKnown'])

    def test_four_ban_panel_rejects_twenty_hand_events(self):
        clean, _ = normalize_camp_events(camp_detail_5ban(), scrim_events_20(), 'seq-20')
        # 同一份 20 手事件套到只有 4 Ban 的面板：规则对不上，不套用。
        from bp_camp import parse_camp_bp
        record = merge_bp_sources(None, parse_camp_bp(camp_detail(), 'seq-1'),
                                  {}, events=clean)
        self.assertFalse(record['pickOrderKnown'])


def test_camp_draft_events_reads_only_game_seq_file(tmp_path):
    """单局复盘只读 gameSeq 指向的 camp_details 文件；非法 seq 不拼路径。"""
    import server
    serve = server.V3_MODULE
    assert serve is not None, 'v3/serve.py 必须能被加载（否则复盘接口不可用）'
    camp_dir = tmp_path / 'camp_details'
    camp_dir.mkdir()
    (camp_dir / '123.json').write_text(json.dumps({'data': {'draftEvents': [
        {'order': 1, 'action': 'ban', 'hero': '盾山', 'camp': '1'}]}}, ensure_ascii=False),
        encoding='utf-8')
    original = serve.MATCHES
    serve.MATCHES = tmp_path / 'matches'
    try:
        by_seq = serve.camp_draft_events({'campBp': {'gameSeq': '123'}})
        assert by_seq[0]['hero'] == '盾山'
        by_replay = serve.camp_draft_events({'officialReplay': {'id': 'camp-123'}})
        assert by_replay[0]['hero'] == '盾山'
        assert serve.camp_draft_events({'campBp': {'gameSeq': '../../etc/passwd'}}) == []
        assert serve.camp_draft_events({}) == []
    finally:
        serve.MATCHES = original


class ManualOrderTest(unittest.TestCase):
    """页面手工录入每侧顺序：Ban 允许跨侧重复，Pick 必须与终局名单一致。"""

    def setUp(self):
        self.detail = camp_detail_5ban()
        # 把红方一个 ban 换成盾山，构造跨侧重复（排位同时禁用的真实情况）。
        self.detail['data']['redTeam']['banHeros'][-1] = {'heroId': 509, 'heroName': '盾山'}
        self.bp = parse_camp_bp(self.detail, 'seq-order')

    def payload(self):
        return {
            'mode': 'scrim',
            'bans': {'left': ['盾山', '芈月', '海月', '盘古', '墨子'],
                     'right': ['盾山', '庄周', '张良', '女娲', '孙悟空']},
            'picks': {'left': ['鲁班七号', '嫦娥', '刘禅', '李元芳', '项羽'],
                      'right': ['瑶', '阿轲', '安琪拉', '虞姬', '钟无艳']},
            'firstPick': 'left',
        }

    def test_order_is_applied_with_duplicate_bans(self):
        from bp_camp import normalize_bp_order
        clean = normalize_bp_order(self.detail, self.payload(), 'seq-order')
        record = merge_bp_sources(None, self.bp, {}, order=clean)
        self.assertTrue(record['pickOrderKnown'])
        self.assertTrue(record['banOrderKnown'])
        self.assertEqual(record['orderSource'], 'manualOrder')
        self.assertEqual([e['name'] for e in record['picks']['left']],
                         ['鲁班七号', '嫦娥', '刘禅', '李元芳', '项羽'])
        self.assertEqual([e['name'] for e in record['bans']['left']],
                         ['盾山', '芈月', '海月', '盘古', '墨子'])
        self.assertEqual([e['name'] for e in record['bans']['right']],
                         ['盾山', '庄周', '张良', '女娲', '孙悟空'])
        self.assertEqual([e['name'] for e in record['banSlots']['right']],
                         ['盾山', '庄周', '张良', '女娲', '孙悟空'])

    def test_manual_order_overrides_default_and_is_not_assumed(self):
        from bp_camp import normalize_bp_order
        clean = normalize_bp_order(self.detail, self.payload(), 'seq-order')
        record = merge_bp_sources(None, self.bp, {}, order=clean, assume_scrim=True)
        self.assertTrue(record['pickOrderKnown'])
        self.assertFalse(record.get('orderAssumed', False))
        self.assertEqual(record['orderSource'], 'manualOrder')

    def test_camp_default_order_is_stamped_as_twenty_hand(self):
        # 教练确认：营地默认顺序就是训练赛 20 手；parse_camp_bp 已在源头生成事件。
        record = merge_bp_sources(None, parse_camp_bp(camp_detail_5ban(), 'seq-default'), {})
        self.assertTrue(record['pickOrderKnown'])
        self.assertTrue(record['banOrderKnown'])
        self.assertTrue(record['orderAssumed'])
        self.assertEqual(record['orderSource'], 'campDefault20')
        self.assertEqual(len(record['draftEvents']), 20)
        self.assertEqual(record['ruleProfile'], 'scrim-global-20')

    def test_pick_mismatch_is_rejected(self):
        from bp_camp import normalize_bp_order
        payload = self.payload()
        payload['picks']['left'][0] = '影'
        with self.assertRaises(ValueError):
            normalize_bp_order(self.detail, payload, 'seq-order')

    def test_ban_outside_panel_is_rejected(self):
        from bp_camp import normalize_bp_order
        payload = self.payload()
        payload['bans']['left'][0] = '大乔'
        with self.assertRaises(ValueError):
            normalize_bp_order(self.detail, payload, 'seq-order')
