import os
import tempfile
import unittest
from unittest import mock

import video_ocr as v
from vision import catalog


def hero_entries():
    return [entry for entry in catalog()['entries'] if entry['kind'] == 'hero']


def sample(video_time, game_time, blue_kills=0, red_kills=0):
    return {'videoTime': video_time, 'gameTime': game_time,
            'blue': {'kills': {'value': blue_kills}, 'gold': {'value': None}},
            'red': {'kills': {'value': red_kills}, 'gold': {'value': None}}}


class ParserTests(unittest.TestCase):
    def test_clock(self):
        self.assertEqual(v.parse_clock('00:21'), 21)
        self.assertEqual(v.parse_clock('01:45'), 105)
        self.assertEqual(v.parse_clock('0:07'), 7)
        self.assertIsNone(v.parse_clock('00:60'))
        self.assertIsNone(v.parse_clock('abc'))

    def test_gold(self):
        self.assertEqual(v.parse_gold('1.5k'), 1500)
        self.assertEqual(v.parse_gold('者 1.5k'), 1500)
        self.assertEqual(v.parse_gold('9.0k'), 9000)
        self.assertEqual(v.parse_gold('1.2万'), 12000)
        self.assertEqual(v.parse_gold('446'), 446)
        self.assertIsNone(v.parse_gold('1.5k10'))
        self.assertIsNone(v.parse_gold('abc'))

    def test_datetime_without_space(self):
        parsed = v.parse_datetime('10/2813:51')
        self.assertEqual((parsed['month'], parsed['day'], parsed['hour'], parsed['minute']),
                         (10, 28, 13, 51))
        self.assertEqual(v.parse_datetime('10/28 13:51')['text'], '10-28 13:51')
        self.assertEqual(v.parse_datetime('2026/10/28 13:51')['text'], '10-28 13:51')
        self.assertIsNone(v.parse_datetime('13/40 99:99'))

    def test_mode(self):
        self.assertEqual(v.normalize_mode('陕谷一快速赛'), '峡谷—快速赛')

    def test_stats_number(self):
        self.assertEqual(v.parse_stat_number('。'), 0)
        self.assertEqual(v.parse_stat_number('177'), 177)
        self.assertIsNone(v.parse_stat_number('abc'))

    def test_runes(self):
        parsed = v.parse_runes('10宿命、5调和、3狩猎、2狩猎、10虚：')
        self.assertEqual([entry['count'] for entry in parsed['entries']], [10, 5, 3, 2, 10])
        self.assertEqual(parsed['entries'][0]['name'], '宿命')
        self.assertTrue(parsed['entries'][-1]['partial'])
        self.assertTrue(parsed['truncated'])
        self.assertIsNone(v.parse_runes(''))

    def test_scoreboard_kda_text(self):
        self.assertEqual(v.normalize_kda_text('0/0/0'), [0, 0, 0])
        self.assertEqual(v.normalize_kda_text('B/1/0'), [0, 1, 0])
        self.assertEqual(v.normalize_kda_text('0/0.0'), [0, 0, 0])
        self.assertEqual(v.normalize_kda_text('0/0:0'), [0, 0, 0])
        self.assertEqual(v.normalize_kda_text('0/0／1'), [0, 0, 1])
        self.assertIsNone(v.normalize_kda_text('01010'))
        self.assertIsNone(v.normalize_kda_text('0/078'))
        self.assertIsNone(v.normalize_kda_text('0²/0/0'))

    def test_kda_level_duration(self):
        self.assertEqual(v.parse_kda('0/0/1'), [0, 0, 1])
        self.assertEqual(v.parse_kda('12/3/9'), [12, 3, 9])
        self.assertIsNone(v.parse_kda('0/0'))
        self.assertEqual(v.parse_level('5'), 5)
        self.assertEqual(v.parse_level('↑'), 1)
        self.assertIsNone(v.parse_level('0'))
        self.assertEqual(v.parse_duration('02:57'), 177)
        self.assertIsNone(v.parse_duration('02:75'))


class HeroNameTests(unittest.TestCase):
    def test_exact_single_character(self):
        result = v.match_hero_name('影', hero_entries(), 1.0)
        self.assertEqual(result['status'], 'exact')
        self.assertEqual(result['name'], '影')

    def test_exact_accepts_moderate_confidence(self):
        result = v.match_hero_name('姜子牙', hero_entries(), 0.78)
        self.assertEqual(result['name'], '姜子牙')

    def test_ambiguous_single_character_difference_is_not_guessed(self):
        result = v.match_hero_name('孙膜', hero_entries(), 0.84)
        self.assertIsNone(result['name'])
        self.assertIsNone(result['guess'])
        self.assertIn('孙膑', [row['name'] for row in result['candidates']])

    def test_unique_near_name_is_candidate(self):
        result = v.match_hero_name('蚩妊', hero_entries(), 0.4)
        self.assertIsNone(result['name'])
        self.assertEqual(result['guess'], '蚩奼')

    def test_single_character_noise_is_unknown(self):
        result = v.match_hero_name('蛋', hero_entries(), 0.9)
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['candidates'], [])

    def test_split_doubled_name(self):
        self.assertEqual(v.split_doubled_name('影影'), ('影', '影'))
        self.assertEqual(v.split_doubled_name('戈娅戈娅'), ('戈娅', '戈娅'))
        self.assertEqual(v.split_doubled_name('茉莉花与雨'), ('茉莉花与雨', ''))


class ScoreboardKdaTests(unittest.TestCase):
    def test_consensus_prefers_majority_then_confidence(self):
        readings = [{'raw': '0/1/0', 'value': [0, 1, 0], 'confidence': 0.8},
                    {'raw': '0/1/0', 'value': [0, 1, 0], 'confidence': 0.6},
                    {'raw': 'B/1/0', 'value': [0, 1, 0], 'confidence': 0.9}]
        self.assertEqual(v._consensus_kda(readings)['value'], [0, 1, 0])
        tie = [{'raw': '0/0/0', 'value': [0, 0, 0], 'confidence': 0.9},
               {'raw': '0/1/0', 'value': [0, 1, 0], 'confidence': 0.8}]
        self.assertEqual(v._consensus_kda(tie)['value'], [0, 0, 0])

    def rows(self, values):
        return [{'value': value, 'raw': '/'.join(map(str, value)), 'confidence': 0.9} for value in values]

    def test_all_zero_matches_topbar(self):
        result = v._validate_kda(self.rows([[0, 0, 0]] * 5), 0, 0)
        self.assertTrue(result['valid'])

    def test_one_missing_row_is_inferred_when_totals_already_match(self):
        rows = self.rows([[0, 0, 0], [0, 0, 0], [0, 1, 0], [0, 0, 0]]) + [None]
        result = v._validate_kda(rows, 0, 1)
        self.assertTrue(result['valid'])
        self.assertEqual(result['inferred'], 1)
        self.assertEqual(rows[-1]['value'], [0, 0, None])

    def test_mismatch_is_not_validated(self):
        result = v._validate_kda(self.rows([[0, 0, 0]] * 5), 2, 0)
        self.assertFalse(result['valid'])


class TimeMappingTests(unittest.TestCase):
    def test_constant_speed(self):
        mapping = v.build_time_mapping([sample(0, -36), sample(1, -35), sample(2, -34)])
        self.assertEqual(mapping['offset'], -36)
        self.assertEqual(mapping['speed'], 1.0)
        self.assertEqual(mapping['stalls'], [])
        self.assertEqual(mapping['jumps'], [])

    def test_stall_and_jump(self):
        stalled = v.build_time_mapping([sample(0, 0), sample(2, 1), sample(4, 1), sample(6, 2)])
        self.assertTrue(stalled['stalls'])
        jumped = v.build_time_mapping([sample(0, 0), sample(1, 1), sample(2, 10)])
        self.assertTrue(jumped['jumps'])

    def test_counter_regression_is_dropped(self):
        samples = [sample(0, 0), sample(1, 1, blue_kills=2)]
        samples[0]['blue']['gold']['value'] = 9000
        samples[1]['blue']['gold']['value'] = 1500
        dropped = v._stabilize_counters(samples)
        self.assertEqual(dropped, 1)
        self.assertIsNone(samples[1]['blue']['gold']['value'])
        self.assertTrue(samples[1]['blue']['gold']['suspect'])

    def test_kill_events_are_monotonic(self):
        events = v._kill_events([sample(0, 0), sample(1, 1, red_kills=1),
                                 sample(2, 2, red_kills=1), sample(3, 3, red_kills=1),
                                 sample(4, 4, blue_kills=1, red_kills=1)])
        self.assertEqual([(event['gameTime'], event['camp'], event['delta']) for event in events],
                         [(1, 'red', 1), (4, 'blue', 1)])


class SceneTests(unittest.TestCase):
    def test_short_unknown_is_filled(self):
        scenes = v._scenes([{'time': 0, 'scene': 'game'}, {'time': 1, 'scene': 'unknown'},
                            {'time': 2, 'scene': 'game'}, {'time': 10, 'scene': 'loading'}], 20)
        self.assertEqual([scene['type'] for scene in scenes], ['game', 'loading'])
        self.assertEqual(scenes[0]['start'], 0)
        self.assertEqual(scenes[0]['end'], 10)
        self.assertEqual(scenes[1]['end'], 20)


class TopCounterTests(unittest.TestCase):
    def test_counter_names_follow_icon_order(self):
        token = [{'text': '0', 'confidence': 0.9, 'box': [0, 0, 1, 1]}]
        with mock.patch.object(v, '_tokens', return_value=token):
            counters = v.read_outer_counters(None)
        self.assertEqual(list(counters), ['blueDragon', 'blueTower', 'redTower', 'redDragon'])
        self.assertEqual([item['value'] for item in counters.values()], [0, 0, 0, 0])


class TeamPanelTests(unittest.TestCase):
    def test_row_reads_kda_and_cumulative_gold(self):
        def fake(image, box, **kwargs):
            if box[0] == v.TEAM_PANEL_KDA['blue'][0]:
                return [{'text': '0/0/0', 'confidence': 0.9, 'box': [0, 0, 1, 1]}]
            return [{'text': '340', 'confidence': 0.99, 'box': [0, 0, 1, 1]}]
        with mock.patch.object(v, '_tokens', side_effect=fake):
            row = v._team_panel_row(None, 'blue', 0)
        self.assertEqual(row['kda'], [0, 0, 0])
        self.assertEqual(row['gold'], 340)
        self.assertEqual(row['slot'], 0)

    def test_panel_requires_first_row_as_gate(self):
        empty = {'slot': 0, 'kda': None, 'kdaRaw': None, 'gold': None, 'goldRaw': None, 'confidence': None}
        with mock.patch.object(v, '_team_panel_row', return_value=empty):
            self.assertIsNone(v.read_team_panel(None))

    def test_panel_accepts_eight_readable_rows(self):
        def row(image, camp, index):
            readable = index < 4
            return {'slot': index,
                    'kda': [0, 0, 0] if readable else None,
                    'kdaRaw': '0/0/0' if readable else None,
                    'gold': 330 if readable else None,
                    'goldRaw': '330' if readable else None,
                    'confidence': 0.9 if readable else None}
        with mock.patch.object(v, '_team_panel_row', side_effect=row):
            panel = v.read_team_panel(None)
        self.assertIsNotNone(panel)
        self.assertEqual(panel['readableRows'], 8)
        self.assertFalse(panel['complete'])
        self.assertEqual(len(panel['blue']), 5)
        self.assertEqual(len(panel['red']), 5)


class ScoreIdentityTests(unittest.TestCase):
    def pool(self):
        return [{'slot': 0, 'hero': '孙膑', 'nickname': '茉莉花与雨'},
                {'slot': 1, 'hero': '百里守约', 'nickname': '百里守约'},
                {'slot': 2, 'hero': '戈娅', 'nickname': '戈娅'},
                {'slot': 3, 'hero': '影', 'nickname': '影'},
                {'slot': 4, 'hero': '铠', 'nickname': '铠'}]

    def read(self, detected, full):
        def fake(image, box, **kwargs):
            if kwargs.get('det'):
                return [{'text': text, 'confidence': 0.9, 'box': [0, 0, 1, 1]} for text in detected]
            return [{'text': text, 'confidence': 0.9, 'box': [0, 0, 1, 1]} for text in full]
        with mock.patch.object(v, '_tokens', side_effect=fake):
            return v._read_score_identity(None, 567, 'blue', self.pool(), hero_entries())

    def test_full_line_ocr_joins_split_hero_name(self):
        row, method = self.read(['百', '里', '守', '约'], ['百里守约百里守约'])
        self.assertEqual(row['hero'], '百里守约')
        self.assertEqual(method, 'nickname-exact')

    def test_full_line_ocr_matches_nickname_behind_panel(self):
        row, method = self.read(['孙', '雨'], ['孙膜茉莉花与雨'])
        self.assertEqual(row['hero'], '孙膑')
        self.assertEqual(method, 'nickname-partial')

    def test_repeated_name_is_collapsed_once(self):
        self.assertEqual(v._dedupe_repeated_name('百里守约百里守约'), '百里守约')
        self.assertEqual(v._dedupe_repeated_name('戈娅戈娅'), '戈娅')
        self.assertEqual(v._dedupe_repeated_name('影影'), '影')
        self.assertEqual(v._dedupe_repeated_name('孙膜茉莉花与雨'), '孙膜茉莉花与雨')


class LineupMergeTests(unittest.TestCase):
    def card(self, slot, nickname, hero=None):
        return {'slot': slot, 'camp': 'red', 'panelSlot': None, 'nickname': nickname,
                'nicknameRaw': nickname, 'nicknameConfidence': 0.9,
                'heroRaw': hero, 'hero': hero, 'heroGuess': None, 'heroStatus': 'exact' if hero else 'unknown',
                'heroCandidates': []}

    def test_one_unmatched_card_and_side_name_are_paired(self):
        loading = {'red': [self.card(0, 'A', '甲'), self.card(1, 'B', '乙'),
                           self.card(2, 'C', '丙'), self.card(3, 'D', '丁'), self.card(4, 'E')]}
        side = {'red': [{'nickname': 'A', 'confidence': 0.9}, {'nickname': 'B', 'confidence': 0.9},
                        {'nickname': 'Q', 'confidence': 0.5}, {'nickname': 'D', 'confidence': 0.9},
                        {'nickname': 'E', 'confidence': 0.9}]}
        merged = v._merge_lineups(loading, side)
        self.assertEqual(len(merged['red']), 5)
        self.assertEqual([row['panelSlot'] for row in merged['red']], [0, 1, 2, 3, 4])
        self.assertEqual(merged['red'][2]['nicknameMatch'], 'elimination')

    def test_side_only_rows_fill_missing_loading_cards(self):
        loading = {'blue': [self.card(0, 'A', '甲')]}
        side = {'blue': [{'nickname': 'A', 'confidence': 0.9}, {'nickname': 'B', 'confidence': 0.9}]}
        merged = v._merge_lineups(loading, side)
        self.assertEqual(len(merged['blue']), 2)
        self.assertEqual(merged['blue'][1]['nicknameMatch'], 'side-only')


class CrossCheckTests(unittest.TestCase):
    def test_abc_order_fills_two_unknown_heroes(self):
        roster = ['孙膑', '百里守约', '戈娅', '影', '铠',
                  '鲁班七号', '程咬金', '蚩奼', '百里玄策', '姜子牙']
        def row(camp, slot, hero, nickname):
            return {'slot': slot, 'camp': camp, 'panelSlot': slot, 'nickname': nickname,
                    'nicknameConfidence': 0.9, 'heroRaw': hero, 'hero': hero,
                    'heroGuess': None, 'heroStatus': 'exact' if hero else 'unknown',
                    'heroCandidates': []}
        report = {
            'lineups': {
                'blue': [row('blue', 0, None, '茉莉花与雨'), row('blue', 1, '百里守约', '百里守约'),
                         row('blue', 2, '戈娅', '戈娅'), row('blue', 3, '影', '影'),
                         row('blue', 4, '铠', '铠')],
                'red': [row('red', 0, '鲁班七号', '鲁班七号'), row('red', 1, '程咬金', '程咬金'),
                        row('red', 2, None, '蛋好'), row('red', 3, '百里玄策', '百里玄策'),
                        row('red', 4, '姜子牙', '姜子牙')],
            },
            'pov': {'nickname': '茉莉花与雨', 'hero': None},
            'scoreboard': {'snapshots': []},
            'teamPanel': {'samples': [
                {'blue': [{'slot': 0, 'hero': None, 'nickname': '茉莉花与雨'}],
                 'red': [{'slot': 2, 'hero': None, 'nickname': '蛋好'}]}]},
            'coverage': {'lineupHeroes': 8},
            'warnings': [],
        }
        handle = tempfile.NamedTemporaryFile(suffix='.abc', delete=False)
        handle.write(b'x')
        handle.close()
        try:
            with mock.patch('replay_parser.inspect_replay',
                            return_value={'blocks': [{'heroName': name} for name in roster]}):
                result = v.cross_check_abc(report, handle.name)
        finally:
            os.unlink(handle.name)
        self.assertEqual(result['status'], 'matched')
        self.assertEqual(report['lineups']['blue'][0]['hero'], '孙膑')
        self.assertEqual(report['lineups']['red'][2]['hero'], '蚩奼')
        self.assertEqual(report['pov']['hero'], '孙膑')
        self.assertEqual(report['coverage']['lineupHeroes'], 10)
        self.assertEqual(report['teamPanel']['samples'][0]['blue'][0]['hero'], '孙膑')
        self.assertEqual(report['teamPanel']['samples'][0]['red'][0]['hero'], '蚩奼')


class LayoutTests(unittest.TestCase):
    def test_roi_boxes_are_inside_reference(self):
        for name, (x1, y1, x2, y2) in v.ROI.items():
            self.assertTrue(0 <= x1 < x2 <= v.REFERENCE[0], name)
            self.assertTrue(0 <= y1 < y2 <= v.REFERENCE[1], name)

    def test_group_lines_joins_split_title(self):
        tokens = [{'text': '茉莉花与', 'confidence': 0.9, 'box': [0.1, 0.50, 0.15, 0.52]},
                  {'text': '雨', 'confidence': 0.8, 'box': [0.16, 0.50, 0.18, 0.52]},
                  {'text': '10/2813:51', 'confidence': 0.9, 'box': [0.1, 0.55, 0.2, 0.57]}]
        lines = v._group_lines(tokens)
        self.assertEqual(lines[0]['text'], '茉莉花与雨')
        self.assertEqual(lines[1]['text'], '10/2813:51')


if __name__ == '__main__':
    unittest.main()

class FrameStreamTests(unittest.TestCase):
    """stderr 必须被后台排空：否则 ffmpeg 写满管道会卡死整个 OCR 队列。"""

    def test_stderr_is_drained_while_stream_runs(self):
        import sys
        command = [sys.executable, '-c',
                   "import sys; sys.stderr.write('E' * 300000); sys.stderr.flush(); "
                   "sys.stdout.write('OUT'); sys.stdout.flush()"]
        process, stderr_text = v._open_frame_stream(command)
        self.assertEqual(process.stdout.read(3), b'OUT')
        process.stdout.close()
        process.wait(timeout=30)
        self.assertEqual(len(stderr_text()), 300000)

