"""attach_camp_detail：营地详情映射进通道草稿的单元测试。"""
import json
import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['TRAINING_DB'] = str(ROOT / 'test-results' / f'camp-attach-{uuid.uuid4().hex}.sqlite3')

import channel_store


def sample_detail():
    """结构对齐真实 battledetail 返回（detail-1793795458.json），数值取图 1。"""
    def role(basic, stats):
        return {'basicInfo': basic, 'battleStats': stats,
                'battleRecords': {'finalEquips': []}, 'dataBehavior': [], 'heroBehavior': {}}

    def basic(role_id, player_id, name, camp):
        return {'roleId': role_id, 'roleName': name, 'playerId': player_id, 'acntCamp': camp}

    def stats(kills, deaths, assists, money, hurt, taken, join, grade):
        # 真实 battledetail 的数值全是字符串，且含小数（hurtTransRate 0.5）。
        # 保留这些格式，防止映射层把小数当字符串塞进统计口径。
        # 营地同时给「总伤害」和「对英雄伤害」：契约的 damage/taken 用后者，
        # 与赛后截图的输出/承伤同口径（见 README.md）。
        total_hurt, hero_hurt = int(hurt), int(hurt) - 8000
        total_taken, hero_taken = int(taken), int(taken) - 500
        return {'killCnt': kills, 'deadCnt': deaths, 'assistCnt': assists, 'money': money,
                'totalHurtCnt': total_hurt, 'totalHeroHurtCnt': hero_hurt,
                'totalBehurtCnt': total_taken, 'totalBeheroHurtCnt': hero_taken,
                'joinGamePercent': join,
                'gradeGame': grade, 'killSoldier': '13', 'ctrlTime': '22', 'healCnt': '100',
                'buildingDamage': '0', 'monsterCoin': '270',
                'hurtTransRate': '0.5', 'behurtPerDeath': '26792.5'}

    blue_stats = [stats(5, 1, 5, 9000, 30000, 20000, 0.6, '8.1'),
                  stats(8, 1, 7, 11000, 28000, 18000, 0.9, '9.0'),
                  stats(6, 1, 7, 9500, 26000, 21000, 0.7, '8.5'),
                  stats(3, 3, 9, 8000, 15000, 30000, 0.6, '7.0'),
                  stats(5, 0, 8, 8700, 52000, 12000, 0.48, '10.6')]
    red_stats = [stats(2, 7, 2, 6000, 12000, 40000, 0.0, '3.0'),
                 stats(1, 6, 2, 5500, 9000, 35000, 0.0, '2.5'),
                 stats(0, 6, 4, 5000, 8000, 33000, 0.0, '2.0'),
                 stats(2, 3, 3, 5200, 10000, 28000, 0.0, '4.0'),
                 stats(1, 5, 2, 4800, 7000, 30000, 0.0, '3.5')]
    heroes_blue = ['孙悟空', '关羽', '妲己', '钟馗', '百里守约']
    heroes_red = ['吕布', '兰陵王', '张良', '貂蝉', '公孙离']
    data = {'head': {'gameResult': True, 'mapName': '排位赛', 'gradeGame': '8.0'},
            'blueTeam': {'money': 41021, 'banHeros': [{'heroId': 521}, {'heroId': 519}]},
            'redTeam': {'money': 29266, 'banHeros': [{'heroId': 135}], 'banCnt': 1},
            'blueRoles': [], 'redRoles': []}
    for index in range(5):
        data['blueRoles'].append(role(
            basic(f'rid-b{index}', f'900000000000000000{index}', f'蓝方选手{index + 1}', '1'),
            blue_stats[index]))
        data['redRoles'].append(role(
            basic(f'rid-r{index}', f'800000000000000000{index}', f'红方选手{index + 1}', '2'),
            red_stats[index]))
    return {'result': 0, 'returnCode': 0, 'data': data}


OFFICIAL_PLAYERS = (
    [{'playerId': f'900000000000000000{index}', 'heroName': hero, 'heroId': 100 + index,
      'acntcamp': '1', 'killCnt': 0} for index, hero in enumerate(['孙悟空', '关羽', '妲己', '钟馗', '百里守约'])]
    + [{'playerId': f'800000000000000000{index}', 'heroName': hero, 'heroId': 200 + index,
        'acntcamp': '2', 'killCnt': 0} for index, hero in enumerate(['吕布', '兰陵王', '张良', '貂蝉', '公孙离'])]
)


class AttachCampDetailTests(unittest.TestCase):
    def setUp(self):
        self.channel = channel_store.blank({'date': '2026-11-02', 'opponent': '测试对手'})

    def test_ten_players_mapped_with_camp_source(self):
        with mock.patch('hero_catalog._load',
                        return_value={521: '海月', 519: '敖隐', 135: '项羽'}):
            channel_store.attach_camp_detail(self.channel, '1793795458', sample_detail(),
                                             OFFICIAL_PLAYERS, '测试')
        players = self.channel['draft']['players']
        self.assertEqual(len(players), 10)
        sun = next(p for p in players if p.get('hero') == '孙悟空')
        self.assertEqual(sun['side'], 'left')
        self.assertEqual(sun['nickname'], '蓝方选手1')
        self.assertEqual(sun['fields']['kills']['value'], 5)
        self.assertEqual(sun['fields']['kills']['source'], 'camp')
        self.assertEqual(sun['fields']['gold']['value'], 9000)
        self.assertEqual(sun['fields']['participation']['value'], 60.0)
        self.assertEqual(sun['fields']['rating']['value'], 8.1)
        self.assertIn('camp', sun['sources'])
        # BP 禁用：heroId 原始值 + 名称映射（缺失的保底 #ID）
        self.assertEqual(self.channel['sources']['camp']['ban']['blue'], [521, 519])
        self.assertEqual(self.channel['sources']['camp']['banNames']['blue'], ['海月', '敖隐'])
        self.assertEqual(self.channel['sources']['camp']['banNames']['red'], ['项羽'])

    def test_conflict_preserved_against_screenshot(self):
        """先放截图值再导入营地，不一致时保留冲突而不是静默覆盖。"""
        channel = self.channel
        group = {'players': [{'side': 'left', 'slot': 0,
                              'nickname': {'value': '蓝方选手1'},
                              'hero': {'value': '孙悟空'},
                              'heroStatus': 'exact',
                              'rating': {'value': 8.2},
                              'fields': {key: {'value': 999, 'raw': '999', 'confidence': 0.9}
                                         for key in ('kills', 'deaths', 'assists', 'gold',
                                                     'damage', 'taken', 'participation')}}],
                 'match': {}, 'pages': [], 'coverage': {}, 'warnings': []}
        channel_store.attach_screenshot(channel, group, [str(i) for i in range(7)], '测试')
        before = channel['draft']['players'][0]['fields']['kills']['value']
        self.assertEqual(before, 999)
        channel_store.attach_camp_detail(channel, '1793795458', sample_detail(),
                                         OFFICIAL_PLAYERS, '测试')
        player = channel['draft']['players'][0]
        self.assertEqual(player['fields']['kills']['value'], 5)
        self.assertEqual(player['fields']['kills']['source'], 'camp')
        conflict = next(c for c in player['conflicts'] if c['field'] == 'kills')
        self.assertEqual(conflict['screenshot'], 999)
        self.assertEqual(conflict['camp'], 5)

    def test_camp_damage_uses_hero_damage(self):
        """契约的 damage/taken 是对英雄口径：营地 totalHurtCnt 不能顶替。"""
        with mock.patch('hero_catalog._load', return_value={}):
            channel_store.attach_camp_detail(self.channel, '1793795458', sample_detail(),
                                             OFFICIAL_PLAYERS, '测试')
        sun = next(p for p in self.channel['draft']['players'] if p.get('hero') == '孙悟空')
        # sample_detail：蓝方1 总伤害 30000 / 总承伤 20000；对英雄 -8000 / -500
        self.assertEqual(sun['fields']['damage']['value'], 22000)
        self.assertEqual(sun['fields']['taken']['value'], 19500)
        self.assertEqual(sun['fields']['damage']['source'], 'camp')

    def test_display_precision_is_not_a_conflict(self):
        """截图只有显示精度（66.1k / 25.7k / 48% / 9k）时，与营地原值不算冲突。"""
        channel = self.channel
        detail = sample_detail()
        stats = detail['data']['blueRoles'][0]['battleStats']
        stats.update({'money': 9000, 'totalHeroHurtCnt': '66056',
                      'totalBeheroHurtCnt': '25746', 'joinGamePercent': '0.481'})
        group = {'players': [{'side': 'left', 'slot': 0,
                              'nickname': {'value': '蓝方选手1'},
                              'hero': {'value': '孙悟空'},
                              'heroStatus': 'exact',
                              'rating': {'value': 8.1},
                              'fields': {'kills': {'value': 5, 'raw': '5'},
                                         'damageDealt': {'value': 66100, 'raw': '66.1k'},
                                         'damageTaken': {'value': 25700, 'raw': '25.7k'},
                                         'participation': {'value': 48.0, 'raw': '48%'},
                                         'gold': {'value': 9000, 'raw': '9k'}}}],
                 'match': {}, 'pages': [], 'coverage': {}, 'warnings': []}
        channel_store.attach_screenshot(channel, group, [str(i) for i in range(7)], '测试')
        with mock.patch('hero_catalog._load', return_value={}):
            channel_store.attach_camp_detail(channel, '1793795458', detail,
                                             OFFICIAL_PLAYERS, '测试')
        self.assertEqual(channel['draft']['conflicts'], [])
        sun = next(p for p in channel['draft']['players'] if p.get('hero') == '孙悟空')
        self.assertEqual(sun['fields']['damage']['value'], 66056)
        self.assertEqual(sun['fields']['participation']['value'], 48.1)

    def test_table_percent_precision_is_not_a_conflict(self):
        """表格里参团率抄成整数（48）时，营地面板 48.1 不算冲突。"""
        channel = self.channel
        detail = sample_detail()
        detail['data']['blueRoles'][0]['battleStats']['joinGamePercent'] = '0.481'
        channel_store.attach_table(channel, {'name': 'x.csv', 'size': 1, 'sha256': 'x'},
                                   {'grain': 'match_player', 'quality': {}, 'warnings': [],
                                    'rows': [{'keys': {'player': '蓝方选手1', 'hero': '孙悟空'},
                                              'metrics': {'participation': {'valid': True, 'value': 48,
                                                                            'raw': 48}}}]},
                                   '测试')
        with mock.patch('hero_catalog._load', return_value={}):
            channel_store.attach_camp_detail(channel, '1793795458', detail,
                                             OFFICIAL_PLAYERS, '测试')
        self.assertFalse(any(c['field'] == 'participation' for c in channel['draft']['conflicts']))

    def test_exact_value_mismatch_still_conflicts(self):
        """差一个档位以上是真不一致，仍然留痕，不静默覆盖。"""
        channel = self.channel
        group = {'players': [{'side': 'left', 'slot': 0,
                              'nickname': {'value': '蓝方选手1'},
                              'hero': {'value': '孙悟空'},
                              'heroStatus': 'exact',
                              'rating': {'value': 8.1},
                              'fields': {'damageDealt': {'value': 120000, 'raw': '120.0k'}}}],
                 'match': {}, 'pages': [], 'coverage': {}, 'warnings': []}
        channel_store.attach_screenshot(channel, group, [str(i) for i in range(7)], '测试')
        with mock.patch('hero_catalog._load', return_value={}):
            channel_store.attach_camp_detail(channel, '1793795458', sample_detail(),
                                             OFFICIAL_PLAYERS, '测试')
        conflict = next(c for c in channel['draft']['conflicts'] if c['field'] == 'damage')
        self.assertEqual(conflict['screenshot'], 120000)
        self.assertEqual(conflict['camp'], 22000)

    def _reviewable_channel(self, detail=None):
        """凑齐唯一必采 official + 营地十人面板，使通道可审核。"""
        with mock.patch('hero_catalog._load', return_value={}):
            channel_store.attach_camp_detail(self.channel, '1793795458',
                                             detail or sample_detail(), OFFICIAL_PLAYERS, '测试')
        channel_store.attach_official(
            self.channel, 'camp-1793795458',
            {'gameSeq': '1793795458', 'gameSvr': '1', 'relaySvr': '2',
             'playerId': '100000001'},
            {'match': {}, 'economy': {}, 'events': {}, 'positions': {},
             'players': [], 'warnings': [], 'source': {'kind': 'personal'}},
            '测试')
        return self.channel

    def test_extended_fields_mapped_as_numbers(self):
        """营地 B 组 7 字段进草稿；小数必须解析成 float 而非字符串。"""
        with mock.patch('hero_catalog._load', return_value={}):
            channel_store.attach_camp_detail(self.channel, '1793795458',
                                             sample_detail(), OFFICIAL_PLAYERS, '测试')
        sun = next(p for p in self.channel['draft']['players'] if p.get('hero') == '孙悟空')
        fields = sun['fields']
        self.assertEqual(fields['cs']['value'], 13)
        self.assertEqual(fields['jungleGold']['value'], 270)
        self.assertEqual(fields['control']['value'], 22)
        self.assertEqual(fields['healing']['value'], 100)
        self.assertEqual(fields['towerDamage']['value'], 0)
        self.assertEqual(fields['damageConversion']['value'], 0.5)
        self.assertIsInstance(fields['damageConversion']['value'], float)
        self.assertEqual(fields['takenPerDeath']['value'], 26792.5)
        self.assertIsInstance(fields['takenPerDeath']['value'], float)
        self.assertEqual(fields['cs']['source'], 'camp')
        # 契约一致性：扩展键必须同时有中文标签、且不与核心必采字段重叠
        self.assertEqual(set(channel_store.ALL_FIELDS),
                         set(channel_store.CORE_FIELDS) | set(channel_store.CAMP_EXTENDED_FIELDS))
        for key in channel_store.CAMP_EXTENDED_FIELDS:
            self.assertIn(key, channel_store.FIELD_LABELS)
            self.assertNotIn(key, channel_store.CORE_FIELDS)

    def test_extended_fields_survive_bundle_and_analysis(self):
        """bundle.final 与跨局分析 rows 都要拿到扩展字段。"""
        import tempfile
        from analysis_data import AnalysisRepository
        channel = self._reviewable_channel()
        channel_store.set_review(channel, '教练甲', '已核对')
        data = channel_store.bundle(channel)
        final = data['players'][0]['final']
        self.assertEqual(final['cs'], 13)
        self.assertEqual(final['jungleGold'], 270)
        self.assertEqual(final['healing'], 100)
        self.assertEqual(final['damageConversion'], 0.5)
        self.assertEqual(final['takenPerDeath'], 26792.5)
        self.assertTrue(final['complete'])  # 扩展字段不参与必填判定
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'matches').mkdir()
            (root / 'imports').mkdir()
            (root / 'matches' / 'sample.json').write_text(
                json.dumps(data, ensure_ascii=False), encoding='utf-8')
            repo = AnalysisRepository(root / 'unused.sqlite3',
                                      root / 'matches', root / 'imports')
            bundles = repo._load_bundles([])
            flat_rows = repo.get()['rows']
        self.assertEqual(len(bundles), 1)
        row = bundles[0]['players'][0]
        self.assertEqual(row['cs'], 13)
        self.assertEqual(row['healing'], 100)
        self.assertEqual(row['damageConversion'], 0.5)
        self.assertEqual(row['takenPerDeath'], 26792.5)
        # 跨局分析真正消费的是扁平化 rows，不是 bundle.players
        self.assertTrue(flat_rows, '扁平化行不能为空')
        self.assertTrue(any(r.get('cs') == 13 and r.get('healing') == 100
                            for r in flat_rows))
        self.assertTrue(any(r.get('damageConversion') == 0.5
                            and r.get('takenPerDeath') == 26792.5
                            for r in flat_rows))

    def test_extended_fields_optional_for_review(self):
        """旧版营地面板没有扩展字段时，审核门槛与 complete 判定不受影响。"""
        detail = sample_detail()
        for roles_key in ('blueRoles', 'redRoles'):
            for role in detail['data'][roles_key]:
                for field in ('killSoldier', 'monsterCoin', 'ctrlTime', 'healCnt',
                              'buildingDamage', 'hurtTransRate', 'behurtPerDeath'):
                    role['battleStats'].pop(field, None)
        channel = self._reviewable_channel(detail)
        self.assertTrue(channel['sourceStatus']['complete'])
        channel_store.set_review(channel, '教练甲', '已核对')
        final = channel_store.bundle(channel)['players'][0]['final']
        self.assertTrue(final['complete'])
        for key in channel_store.CAMP_EXTENDED_FIELDS:
            self.assertIsNone(final[key])  # 缺失保持 None，不估算补数

    def test_missing_detail_raises(self):
        channel = channel_store.blank()
        with self.assertRaises(ValueError):
            channel_store.attach_camp_detail(channel, '000', {'data': {'blueRoles': [], 'redRoles': []}},
                                             None, '测试')

    def test_camp_entry_time_fills_match_and_bundle(self):
        """dtEventTime 是发送时间；开赛时间 = dtEventTime - usedTime，按北京时间落库。"""
        detail = sample_detail()
        detail['_campEntry'] = {'dtEventTime': '1793804938', 'usedTime': 838}
        channel = channel_store.blank({'opponent': '测试对手'})
        with mock.patch('hero_catalog._load', return_value={}):
            channel_store.attach_camp_detail(channel, '1793804938', detail,
                                             OFFICIAL_PLAYERS, '测试')
        self.assertEqual(channel['match']['date'], '2026-11-04')
        self.assertEqual(channel['match']['startedAt'], '2026-11-04T22:55:00+08:00')
        self.assertEqual(channel['match']['eventAt'], '2026-11-04T23:08:58+08:00')
        self.assertEqual(channel['sources']['camp']['times']['eventAt'],
                         '2026-11-04T23:08:58+08:00')
        channel_store.attach_official(channel, 'camp-1793804938',
                                      {'gameSeq': '1793804938', 'gameSvr': '1', 'relaySvr': '2',
                                       'playerId': '100000001'},
                                      {'match': {}, 'economy': {}, 'events': {}, 'positions': {},
                                       'players': [], 'warnings': [], 'source': {'kind': 'personal'}},
                                      '测试')
        channel_store.set_review(channel, '教练甲', '已核对')
        bundle = channel_store.bundle(channel)
        self.assertEqual(bundle['match']['startTime'], '2026-11-04T22:55:00+08:00')
        self.assertEqual(bundle['match']['date']['text'], '2026-11-04')

    def test_manual_date_survives_camp_time(self):
        detail = sample_detail()
        detail['_campEntry'] = {'dtEventTime': '1793804938', 'usedTime': 838}
        with mock.patch('hero_catalog._load', return_value={}):
            channel_store.attach_camp_detail(self.channel, '1793804938', detail,
                                             OFFICIAL_PLAYERS, '测试')
        self.assertEqual(self.channel['match']['date'], '2026-11-02')
        self.assertEqual(self.channel['match']['startedAt'], '2026-11-04T22:55:00+08:00')

    def test_required_only_official_plus_camp(self):
        channel_store.attach_camp_detail(self.channel, '1793795458', sample_detail(),
                                         OFFICIAL_PLAYERS, '测试')
        self.assertFalse(self.channel['sourceStatus']['complete'])  # 还差 official
        channel_store.attach_official(self.channel, 'camp-1793795458',
                                      {'gameSeq': '1793795458', 'gameSvr': '1', 'relaySvr': '2',
                                       'playerId': '100000001'},
                                      {'match': {}, 'economy': {}, 'events': {}, 'positions': {},
                                       'players': [], 'warnings': [], 'source': {'kind': 'personal'}},
                                      '测试')
        status = self.channel['sourceStatus']
        self.assertTrue(status['complete'])  # 截图/录屏缺失不再挡审核
        self.assertEqual(status['required']['screenshot'], 0)
        self.assertEqual(status['required']['video'], 0)


if __name__ == '__main__':
    unittest.main()
