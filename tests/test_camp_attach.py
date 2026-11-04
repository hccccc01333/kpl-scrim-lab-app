"""attach_camp_detail：营地详情映射进通道草稿的单元测试。"""
import json
import os
import sys
import unittest
import uuid
from pathlib import Path

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
        return {'killCnt': kills, 'deadCnt': deaths, 'assistCnt': assists, 'money': money,
                'totalHurtCnt': hurt, 'totalBehurtCnt': taken, 'joinGamePercent': join,
                'gradeGame': grade, 'killSoldier': 13, 'ctrlTime': 22, 'healCnt': 100,
                'buildingDamage': 0, 'monsterCoin': 0}

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
        # BP 原始禁用落库（heroId→名称映射后续做）
        self.assertEqual(self.channel['sources']['camp']['ban']['blue'], [521, 519])

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
        self.assertEqual(player['fields']['kills']['value'], 999)  # 截图值保留
        self.assertEqual(player['fields']['kills']['source'], 'screenshot')
        conflict = next(c for c in player['conflicts'] if c['field'] == 'kills')
        self.assertEqual(conflict['screenshot'], 999)
        self.assertEqual(conflict['camp'], 5)

    def test_missing_detail_raises(self):
        channel = channel_store.blank()
        with self.assertRaises(ValueError):
            channel_store.attach_camp_detail(channel, '000', {'data': {'blueRoles': [], 'redRoles': []}},
                                             None, '测试')

    def test_required_only_official_plus_camp(self):
        channel_store.attach_camp_detail(self.channel, '1793795458', sample_detail(),
                                         OFFICIAL_PLAYERS, '测试')
        self.assertFalse(self.channel['sourceStatus']['complete'])  # 还差 official
        channel_store.attach_official(self.channel, 'camp-1793795458',
                                      {'gameSeq': '1793795458', 'gameSvr': '1', 'relaySvr': '2',
                                       'playerId': '540599032'},
                                      {'match': {}, 'economy': {}, 'events': {}, 'positions': {},
                                       'players': [], 'warnings': [], 'source': {'kind': 'personal'}},
                                      '测试')
        status = self.channel['sourceStatus']
        self.assertTrue(status['complete'])  # 截图/录屏缺失不再挡审核
        self.assertEqual(status['required']['screenshot'], 0)
        self.assertEqual(status['required']['video'], 0)


if __name__ == '__main__':
    unittest.main()
