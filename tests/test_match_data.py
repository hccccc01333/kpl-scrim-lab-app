import unittest

import match_data as m

BLUE = ['影', '铠', '戈娅', '百里守约', '孙膑']
RED = ['程咬金', '百里玄策', '姜子牙', '鲁班七号', '蚩奼']
NICKS = {'孙膑': '茉莉花与雨'}
STATS = {
    '影': {'kills': 7, 'deaths': 4, 'assists': 5, 'gold': '11.7k', 'damage': '31.2k',
           'taken': '22.4k', 'participation': '72.5%', 'rating': '12.8'},
    '铠': {'kills': 4, 'deaths': 5, 'assists': 8, 'gold': '9.2k', 'damage': '20.1k',
           'taken': '30.2k', 'participation': '66.0%', 'rating': '10.9'},
    '戈娅': {'kills': 3, 'deaths': 3, 'assists': 6, 'gold': '10.1k', 'damage': '28.3k',
             'taken': '18.4k', 'participation': '58.0%', 'rating': '11.2'},
    '百里守约': {'kills': 5, 'deaths': 1, 'assists': 4, 'gold': '12.4k', 'damage': '35.6k',
                 'taken': '12.0k', 'participation': '61.0%', 'rating': '13.1'},
    '孙膑': {'kills': 1, 'deaths': 2, 'assists': 12, 'gold': '9.8k', 'damage': '12.5k',
             'taken': '16.0k', 'participation': '80.0%', 'rating': '12.3'},
    '程咬金': {'kills': 2, 'deaths': 6, 'assists': 7, 'gold': '8.9k', 'damage': '18.2k',
               'taken': '38.0k', 'participation': '55.0%', 'rating': '10.2'},
    '百里玄策': {'kills': 5, 'deaths': 5, 'assists': 3, 'gold': '10.3k', 'damage': '26.0k',
                 'taken': '20.0k', 'participation': '50.0%', 'rating': '11.5'},
    '姜子牙': {'kills': 1, 'deaths': 4, 'assists': 11, 'gold': '8.7k', 'damage': '14.0k',
               'taken': '17.0k', 'participation': '70.0%', 'rating': '10.7'},
    '鲁班七号': {'kills': 6, 'deaths': 3, 'assists': 5, 'gold': '12.0k', 'damage': '34.0k',
                 'taken': '14.0k', 'participation': '64.0%', 'rating': '12.4'},
    '蚩奼': {'kills': 4, 'deaths': 4, 'assists': 9, 'gold': '9.5k', 'damage': '21.0k',
             'taken': '19.0k', 'participation': '60.0%', 'rating': '11.0'},
}


def lineup(heroes, camp):
    result = []
    for slot, hero in enumerate(heroes):
        result.append({'slot': slot, 'panelSlot': slot, 'hero': hero, 'heroGuess': None,
                       'heroStatus': 'exact', 'heroRaw': hero,
                       'nickname': NICKS.get(hero, hero), 'nicknameRaw': NICKS.get(hero, hero),
                       'nicknameConfidence': 0.95})
    return result


def video_report(heroes_blue=None, heroes_red=None, gold_shift=0, kills_blue=1, follows=True):
    heroes_blue = heroes_blue or BLUE
    heroes_red = heroes_red or RED
    return {
        'schema': 'kpl-video-ocr-v1',
        'video': {'name': 'v.mp4', 'sha256': 'a' * 64, 'duration': 120, 'width': 1600,
                  'height': 900, 'fps': 30},
        'match': {
            'title': {'value': '茉莉花与雨', 'raw': '茉莉花与雨', 'confidence': 1.0},
            'mode': {'value': '峡谷—快速赛', 'raw': '峡谷—快速赛', 'confidence': 0.9},
            'date': {'value': {'month': 10, 'day': 28, 'hour': 13, 'minute': 51,
                               'text': '10-28 13:51'}},
        },
        'replayDuration': 177,
        'pov': {'camp': 'blue', 'nickname': '茉莉花与雨', 'hero': '孙膑'},
        'lineups': {'blue': lineup(heroes_blue, 'blue'), 'red': lineup(heroes_red, 'red')},
        'timeMapping': {'offset': -36.0, 'speed': 1.0, 'stalls': [], 'jumps': []},
        'timeline': [
            {'gameTime': 0, 'blueGold': 1500 + gold_shift, 'redGold': 1500,
             'blueKills': 0, 'redKills': 0},
            {'gameTime': 60, 'blueGold': 4000 + gold_shift, 'redGold': 4200,
             'blueKills': kills_blue, 'redKills': 1},
        ],
        'killEvents': [],
        'selection': {'segments': [{
            'start': 36, 'end': 100, 'levelFirst': 1, 'levelLast': 5,
            'kdaFirst': [0, 0, 0], 'kdaLast': [1, 0, 0],
            'goldFirst': 300, 'goldLast': 1000,
            'stats': {'attack': {'value': 177}, 'armor': {'value': 164},
                      'magicAttack': {'value': 0}, 'magicResist': {'value': 75}},
            'runes': {'raw': '10宿命', 'entries': [], 'truncated': False},
            'equipment': {'slots': [], 'filled': 0},
        }]},
        'scoreboard': {'snapshots': [{
            'gameTime': 60, 'valid': True, 'kdaValidated': True,
            'blue': {'sum': 1000, 'team': 1000, 'values': [100] * 5,
                     'kdaRows': [{'value': [0, 0, 0]} for _ in range(5)]},
            'red': {'sum': 1000, 'team': 1000, 'values': [100] * 5,
                    'kdaRows': [{'value': [0, 0, 0]} for _ in range(5)]},
            'players': [{'camp': 'blue', 'slot': slot, 'hero': hero,
                         'nickname': NICKS.get(hero, hero), 'kda': [0, 0, 0],
                         'kdaValidated': True, 'gold': 100}
                        for slot, hero in enumerate(heroes_blue)]
                       + [{'camp': 'red', 'slot': slot, 'hero': hero,
                           'nickname': NICKS.get(hero, hero), 'kda': [0, 0, 0],
                           'kdaValidated': True, 'gold': 100}
                          for slot, hero in enumerate(heroes_red)],
        }]},
        'samples': [
            {'gameTime': 0, 'selected': {'kda': {'value': [0, 0, 0]},
                                         'gold': {'value': 300},
                                         'level': {'value': 1}, 'stats': None}},
            {'gameTime': 10, 'selected': {'kda': {'value': [0, 0, 0]},
                                          'gold': {'value': 500},
                                          'level': {'value': 2}, 'stats': None}},
        ],
        'coverage': {'samples': 2},
        'warnings': [],
    }


def postgame_page(kind, order=None, meta=None):
    order = order or [('left', BLUE), ('right', RED)]
    players = []
    for side, heroes in order:
        for slot, hero in enumerate(heroes):
            stats = STATS[hero]
            fields = {'hero': {'value': hero, 'raw': hero, 'confidence': 0.95}}
            if kind == 'score':
                for key in ('kills', 'deaths', 'assists', 'gold', 'rating'):
                    fields[key] = {'value': stats[key], 'confidence': 0.9}
            else:
                for key in ('damage', 'taken', 'gold', 'participation', 'rating'):
                    fields[key] = {'value': stats[key], 'confidence': 0.9}
            players.append({'side': side, 'slot': slot, 'fields': fields})
    page = {'kind': kind, 'players': players, 'warnings': [],
            'meta': meta or {'date': '2026-10-28', 'duration': '2.95'}}
    if kind == 'score':
        page['scores'] = {'left': '20', 'right': '18'}
    else:
        page['scores'] = {}
    return page


class DisplayTests(unittest.TestCase):
    def test_display_values(self):
        self.assertEqual(m._display_value({'value': '41.8k'})['value'], 41800.0)
        self.assertTrue(m._display_value({'value': '41.8k'})['approx'])
        percent = m._display_value({'value': '18.5%'})
        self.assertEqual((percent['value'], percent['unit']), (18.5, '%'))
        self.assertEqual(m._display_value({'value': '12.3'})['value'], 12.3)
        self.assertEqual(m._display_value({'value': '123'})['value'], 123)


class IdentityTests(unittest.TestCase):
    def test_high_identity(self):
        video = video_report()
        meta = m._match_video_meta([video])
        post = m._postgame_meta([postgame_page('score')])
        identity = m.check_identity(meta, post)
        self.assertEqual(identity['confidence'], 'high')
        self.assertEqual(identity['checks']['heroes'], 10)

    def test_mismatch_requires_force(self):
        video = video_report()
        page = postgame_page('score')
        page['meta'] = {'date': '2026-10-29', 'duration': '2.95'}
        with self.assertRaises(m.MatchDataError):
            m.build_match_data([video], [], [page])
        bundle = m.build_match_data([video], [], [page], force=True)
        self.assertEqual(bundle['match']['identity']['confidence'], 'low')
        self.assertTrue(any('日期不一致' in warning for warning in bundle['warnings']))


class TimelineTests(unittest.TestCase):
    def test_different_pov_titles_are_allowed(self):
        second = video_report()
        second['match']['title'] = {'value': '另一个POV'}
        bundle = m.build_match_data([video_report(), second], [None, None])
        self.assertEqual(bundle['match']['title'], '茉莉花与雨')
        self.assertTrue(any('标题不同' in warning for warning in bundle['warnings']))

    def test_multiple_reports_are_merged_and_flagged(self):
        bundle = m.build_match_data([video_report(gold_shift=0, kills_blue=1),
                                     video_report(gold_shift=20, kills_blue=2)], [])
        timeline = bundle['team']['timeline']
        self.assertEqual([point['gameTime'] for point in timeline], [0, 60])
        self.assertEqual(timeline[0]['blueGold'], 1510)  # upper median of 1500/1520
        self.assertTrue(timeline[1].get('disagree'))
        self.assertTrue(any('多路读数差' in warning for warning in bundle['warnings']))


class BundleTests(unittest.TestCase):
    def test_postgame_attaches_by_hero_and_keeps_sources(self):
        bundle = m.build_match_data([video_report()], ['孙膑'],
                                    [postgame_page('score'), postgame_page('data')])
        self.assertEqual(bundle['match']['identity']['confidence'], 'high')
        self.assertEqual(bundle['match']['scores'], {'blue': 20, 'red': 18})
        by_hero = {player['hero']: player for player in bundle['players']}
        ying = by_hero['影']['final']
        self.assertEqual((ying['kills'], ying['deaths'], ying['assists']), (7, 4, 5))
        self.assertEqual(ying['totalGold'], 11700.0)
        self.assertEqual(ying['damage'], 31200.0)
        self.assertTrue(ying['complete'])
        sun = by_hero['孙膑']
        self.assertEqual(len(sun['process']['pov']), 1)
        self.assertEqual(sun['process']['pov'][0]['gameStart'], 0.0)
        self.assertEqual(sun['process']['pov'][0]['gameEnd'], 64.0)
        self.assertGreater(len(sun['process']['series']), 0)
        self.assertEqual(bundle['coverage']['finalPlayers'], 10)
        self.assertEqual(bundle['coverage']['povPlayers'], 1)

    def test_postgame_pages_merge_by_roster_not_row_order(self):
        reversed_blue = [('left', list(reversed(BLUE))), ('right', list(reversed(RED)))]
        bundle = m.build_match_data([video_report()], ['孙膑'],
                                    [postgame_page('score'),
                                     postgame_page('data', order=reversed_blue)])
        by_hero = {player['hero']: player for player in bundle['players']}
        ying = by_hero['影']['final']
        self.assertEqual((ying['kills'], ying['deaths'], ying['assists']), (7, 4, 5))
        self.assertEqual(ying['damage'], 31200.0)
        self.assertEqual(by_hero['孙膑']['final']['damage'], 12500.0)

    def test_swapped_sides_are_mapped_by_heroes(self):
        swapped = [('left', RED), ('right', BLUE)]
        page = postgame_page('score', order=swapped)
        bundle = m.build_match_data([video_report()], ['孙膑'], [page])
        self.assertEqual(bundle['match']['scores'], {'blue': 18, 'red': 20})
        by_hero = {player['hero']: player for player in bundle['players']}
        self.assertEqual(by_hero['影']['final']['kills'], 7)
        self.assertEqual(by_hero['程咬金']['final']['kills'], 2)

    def test_data_only_postgame_leaves_kda_empty(self):
        bundle = m.build_match_data([video_report()], ['孙膑'], [postgame_page('data')])
        ying = next(player for player in bundle['players'] if player['hero'] == '影')['final']
        self.assertIsNone(ying['kills'])
        self.assertEqual(ying['damage'], 31200.0)
        self.assertTrue(ying['partial'])
        self.assertTrue(any('未提供赛后战绩页' in warning for warning in bundle['warnings']))

    def test_score_only_postgame_leaves_damage_empty(self):
        bundle = m.build_match_data([video_report()], ['孙膑'], [postgame_page('score')])
        ying = next(player for player in bundle['players'] if player['hero'] == '影')['final']
        self.assertIsNone(ying['damage'])
        self.assertEqual(ying['kills'], 7)
        self.assertTrue(any('未提供赛后数据页' in warning for warning in bundle['warnings']))

    def test_unlabeled_pov_is_not_attributed(self):
        bundle = m.build_match_data([video_report()], [])
        self.assertEqual(len(bundle['unattributedPov']), 1)
        self.assertEqual(bundle['coverage']['povPlayers'], 0)
        self.assertTrue(any('没有 POV 标签' in warning for warning in bundle['warnings']))

    def test_ambiguous_follow_is_rejected(self):
        report = video_report(heroes_red=['影'] + RED[1:])
        with self.assertRaises(m.MatchDataError):
            m.build_match_data([report], ['影'])

    def test_no_postgame_uses_partial_scoreboard_final(self):
        bundle = m.build_match_data([video_report()], ['孙膑'])
        ying = next(player for player in bundle['players'] if player['hero'] == '影')['final']
        self.assertEqual(ying['source'], 'scoreboard')
        self.assertTrue(ying['partial'])
        self.assertEqual(ying['gameTime'], 60)
        self.assertIsNone(ying['damage'])
        self.assertTrue(any('未提供赛后截图' in warning for warning in bundle['warnings']))

    def test_match_key_uses_postgame_year(self):
        with_post = m.build_match_data([video_report()], ['孙膑'], [postgame_page('score')])
        without = m.build_match_data([video_report()], ['孙膑'])
        self.assertTrue(with_post['match']['key'].startswith('20261028-177-'))
        self.assertTrue(without['match']['key'].startswith('1028-177-'))


if __name__ == '__main__':
    unittest.main()

class GameTimeMappingTests(unittest.TestCase):
    """视频时间 → 游戏时间：倍速录屏不能用恒定 offset（会漂移数分钟）。"""

    def test_doublespeed_uses_nearest_sample_extrapolation(self):
        # 2 倍速：game = 30 + 2 * video
        samples = [{'videoTime': 0, 'gameTime': 30},
                   {'videoTime': 60, 'gameTime': 150},
                   {'videoTime': 120, 'gameTime': 270}]
        mapping = {'offset': 90, 'speed': 2.0}  # offset 是中位数，越早越偏
        # 旧逻辑：game = 30 + offset = 120（真值 90，偏 30 秒）
        self.assertEqual(m._game_time_at(samples, mapping, 30), 90)
        self.assertEqual(m._game_time_at(samples, {'offset': 90, 'speed': 2.0}, 90), 210)

    def test_falls_back_to_offset_without_clock_samples(self):
        self.assertEqual(m._game_time_at([], {'offset': 12.5}, 100), 112.5)
        self.assertIsNone(m._game_time_at([], {}, 100))

