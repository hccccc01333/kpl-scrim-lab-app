import unittest

import channel_store as c
from tests.collection_fixtures import complete_collection


def field(value, raw=None):
    return {'value': value, 'raw': raw or str(value), 'confidence': .9}


def player(side, slot, nickname, hero=None, candidates=None, fields=None):
    return {
        'side': side, 'slot': slot,
        'nickname': {'value': nickname, 'raw': nickname, 'confidence': .9},
        'hero': {'value': hero, 'raw': hero, 'confidence': .9} if hero else None,
        'heroStatus': 'exact' if hero else 'uncertain',
        'heroCandidates': [{'name': name} for name in (candidates or [])],
        'fields': fields or {},
    }


def screenshot_group():
    left = [
        player('left', 0, '甲', '虞姬', fields={'kills': field(2), 'deaths': field(5), 'assists': field(5), 'gold': field(9300), 'damageDealt': field(59200)}),
        player('left', 1, '乙', None, ['夏侯惇'], fields={'kills': field(2)}),
        player('left', 2, '丙', None, ['妲己'], fields={'kills': field(1)}),
        player('left', 3, '丁', None, [], fields={'kills': field(7)}),
        player('left', 4, '戊', None, ['钟馗'], fields={'kills': field(2)}),
    ]
    right = [player('right', i, f'R{i}', '后羿', fields={'kills': field(8), 'deaths': field(4), 'assists': field(10), 'gold': field(11000)}) for i in range(5)]
    return {'match': {'date': '2026-06-17', 'durationSec': 1132, 'score': {'left': 14, 'right': 26}},
            'players': left + right, 'pages': [{'pageType': 'data'}, {'pageType': 'farming'}],
            'coverage': {}, 'warnings': []}


class ChannelStoreTests(unittest.TestCase):
    def test_blank_and_required_source_status(self):
        channel = c.blank({'date': '2026-06-17', 'opponent': '对手'})
        status = c.source_status(channel)
        self.assertFalse(status['complete'])
        self.assertEqual(status['counts']['video'], 0)
        # 营地链接是唯一必采；录屏降级为兜底，所以 required 计数为 0。
        self.assertEqual(status['required']['video'], 0)

    def test_screenshot_roster_and_table_merge(self):
        channel = c.blank({'date': '2026-06-17'})
        channel['id'] = 'test'
        report = {'blocks': [{'heroName': name, 'heroId': index, 'order': index}
                             for index, name in enumerate(['虞姬', '夏侯惇', '妲己', '阿古朵', '钟馗', '后羿'])],
                  'header': {'versions': ['test'], 'localHeroName': '虞姬'}}
        c.attach_replay(channel, 'replay-1', report)
        c.attach_screenshot(channel, screenshot_group(), ['a', 'b'])
        players = channel['draft']['players']
        self.assertEqual(players[0]['hero'], '虞姬')
        self.assertEqual(players[1]['hero'], '夏侯惇')
        self.assertEqual(players[2]['hero'], '妲己')
        self.assertEqual(players[4]['hero'], '钟馗')
        self.assertEqual(players[3]['hero'], '阿古朵')
        self.assertEqual(players[3]['heroStatus'], 'roster-elimination')
        self.assertEqual(players[0]['fields']['damage']['value'], 59200)
        parsed = {'grain': 'match_player', 'quality': {}, 'warnings': [],
                  'rows': [{'keys': {'player': '甲', 'hero': '虞姬'},
                            'metrics': {'gold': {'valid': True, 'value': 12000, 'raw': '12k'},
                                        'kills': {'valid': True, 'value': 2, 'raw': '2'}}}]}
        c.attach_table(channel, {'name': 'x.csv'}, parsed)
        self.assertEqual(channel['draft']['players'][0]['fields']['gold']['source'], 'screenshot')
        self.assertEqual(channel['draft']['players'][0]['fields']['gold']['value'], 9300)
        self.assertTrue(any(item['field'] == 'gold' for item in channel['draft']['conflicts']))

    def test_replay_complete_identity_result_and_rating(self):
        channel = c.blank({})
        channel['id'] = 'replay-test'
        rows = [
            (1, 0, 1168, '胡不喜#', '钟馗', 175, 8.4),
            (1, 1, 1613, '自诩一棵葱', '妲己', 109, 10.4),
            (1, 2, 750, '别吃窝线吖a', '孙悟空', 167, 9.1),
            (1, 3, 538, '狂傲自由魂Z.', '关羽', 140, 13.1),
            (1, 4, 1611, '漂流网咖︎', '百里守约', 196, 10.6),
            (2, 0, 1031, '麻巫喵', '公孙离', 199, 5.9),
            (2, 1, 296, '翳灵崽', '吕布', 123, 5.4),
            (2, 2, 551, '一风舞', '貂蝉', 141, 5.5),
            (2, 3, 1799, '扁鹊耳垂', '兰陵王', 153, 3.6),
            (2, 4, 1760, '谜语星海', '张良', 156, 4.9),
        ]
        report = {
            'header': {'versions': ['12.1.1.1', '12.1.1.26'],
                       'builds': ['4989537', '5247758'],
                       'mapType': 3, 'mapId': 20111,
                       'nickname': '漂流网咖︎', 'localHeroName': '百里守约',
                       'totalFrameNum': 10674},
            'blocks': [{'camp': camp, 'position': slot, 'order': index,
                        'entityId': entity, 'name': nickname, 'heroName': hero,
                        'heroId': hero_id, 'bot': False, 'score': score}
                       for index, (camp, slot, entity, nickname, hero, hero_id, score) in enumerate(rows)],
            'mvpScore': {'winningCamp': 'blue',
                         'winMvp': {'entityId': 538, 'nickname': '狂傲自由魂Z.',
                                    'hero': '关羽', 'rating': 13.1},
                         'loseMvp': [{'entityId': 1031, 'nickname': '麻巫喵',
                                      'hero': '公孙离', 'rating': 5.9}]},
            'frames': {'records': 10509},
            'abcFileName': '20261102_161129_870343216_95868_1793606215_2B9FAA08A7AD40D09ABDA364F9C1E804.abc',
        }
        c.attach_replay(channel, 'replay-1', report)
        players = channel['draft']['players']
        self.assertEqual(players[0]['hero'], '钟馗')
        self.assertEqual(players[0]['nickname'], '胡不喜#')
        self.assertEqual(players[0]['replayEntityId'], 1168)
        self.assertEqual(players[0]['fields']['rating']['value'], 8.4)
        self.assertEqual(players[0]['fields']['rating']['source'], 'replay')
        self.assertEqual(players[5]['hero'], '公孙离')
        self.assertEqual(players[5]['nickname'], '麻巫喵')
        self.assertEqual(channel['draft']['coverage']['rating'], 10)
        self.assertEqual(channel['match']['date'], '2026-11-02')
        self.assertIn('5247758', channel['match']['version'])
        self.assertEqual(channel['sources']['replay']['result']['winningCamp'], 'blue')
        self.assertEqual(channel['draft']['match']['result']['winMvp']['nickname'], '狂傲自由魂Z.')
        complete_collection(channel)
        c.set_review(channel, '教练甲', '已核对')
        data = c.bundle(channel)
        self.assertEqual(data['match']['result']['winningCamp'], 'blue')
        self.assertEqual(data['players'][0]['replayEntityId'], 1168)
        self.assertEqual(data['players'][0]['final']['rating'], 8.4)
        self.assertTrue(data['players'][0]['final']['partial'])

    def test_review_required_for_bundle_and_save_log(self):
        channel = c.blank({'date': '2026-06-17'})
        channel['id'] = 'test'
        c.attach_screenshot(channel, screenshot_group(), ['a'])
        with self.assertRaises(ValueError):
            c.bundle(channel)
        complete_collection(channel)
        c.set_review(channel, '教练甲', '已核对')
        c.apply_draft(channel, [{'side': 'left', 'slot': 0, 'hero': '虞姬',
                                 'fields': {'rating': '9.9'}}], '教练甲')
        self.assertEqual(channel['review']['status'], 'unreviewed')
        self.assertEqual(channel['draft']['players'][0]['fields']['rating']['value'], 9.9)
        complete_collection(channel)
        c.set_review(channel, '教练甲', '已核对')
        data = c.bundle(channel)
        self.assertEqual(data['schema'], 'kpl-match-data-v1')
        self.assertEqual(len(data['players']), 10)
        self.assertEqual(channel['review']['reviewedBy'], '教练甲')
        self.assertTrue(any(log['action'] == 'review' for log in channel['changeLog']))
        self.assertEqual(data['match']['key'], 'channel-test')


if __name__ == '__main__':
    unittest.main()
