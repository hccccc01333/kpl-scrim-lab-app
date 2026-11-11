import unittest

from screenshot_fields import SCHEMA, flatten_recognition, render_summary


def field(value, raw=None, confidence=0.9):
    return {'value': value, 'raw': raw or value, 'confidence': confidence,
            'box': [0.1, 0.1, 0.2, 0.2]}


def result(kind='score'):
    players = []
    for side in ('left', 'right'):
        for slot in range(5):
            fields = {
                'hero': field('影' if side == 'left' else '程咬金'),
                'rating': field('12.3'),
                'kills': field(str(slot + 1)),
                'deaths': field(str(slot)),
                'assists': field('4'),
                'gold': field(str(9000 + slot * 100)),
            }
            if kind == 'data':
                fields.update({'damage': field('31.2k'),
                               'taken': field('22.4k'),
                               'participation': field('72%')})
            players.append({'side': side, 'slot': slot, 'fields': fields})
    return {
        'kind': kind, 'version': 'scoreboard-v3-name-first',
        'scores': {'left': '20', 'right': '18'},
        'meta': {'date': '2026-10-28', 'duration': '18.5'},
        'players': players,
        'tokens': [{'text': '胜利', 'confidence': .99},
                   {'text': '王者峡谷', 'confidence': .92}],
        'visuals': [{'side': 'left', 'slot': 0, 'kind': 'equipment', 'index': 0,
                     'status': 'reference', 'candidates': [{'name': '学识宝石', 'similarity': .95}]},
                    {'side': 'left', 'slot': 0, 'kind': 'equipment', 'index': 1,
                     'status': 'unreadable', 'candidates': []}],
        'warnings': ['示例警告'],
    }


class ScreenshotFieldTests(unittest.TestCase):
    def test_score_page_flatten(self):
        flat = flatten_recognition(result('score'), 'score.png')
        self.assertEqual(flat['schema'], SCHEMA)
        self.assertEqual(flat['pageType'], 'score')
        self.assertEqual(flat['match']['date'], '2026-10-28')
        self.assertEqual(flat['match']['durationMinutes'], '18.5')
        self.assertEqual(flat['match']['scores'], {'left': '20', 'right': '18'})
        self.assertEqual(flat['match']['resultCandidate']['value'], 'win')
        self.assertEqual(flat['match']['modeCandidate']['raw'], '王者峡谷')
        self.assertEqual(len(flat['players']), 10)
        first = flat['players'][0]
        self.assertEqual(first['fields']['hero']['value'], '影')
        self.assertEqual(first['fields']['gold']['value'], '9000')
        self.assertNotIn('damage', first['fields'])
        self.assertEqual(flat['equipment'][0]['status'], 'reference')
        self.assertEqual(flat['equipment'][1]['candidates'], [])
        self.assertEqual(flat['warnings'], ['示例警告'])
        self.assertIn('英雄=影', render_summary(flat))

    def test_data_page_flatten(self):
        flat = flatten_recognition(result('data'), 'data.png')
        player = flat['players'][0]
        self.assertEqual(player['fields']['damage']['value'], '31.2k')
        self.assertEqual(player['fields']['taken']['value'], '22.4k')
        self.assertEqual(player['fields']['participation']['value'], '72%')
        self.assertEqual(flat['pageType'], 'data')

    def test_missing_fields_stay_out(self):
        value = result('score')
        value['players'] = [{'side': 'left', 'slot': 0, 'fields': {}}]
        value['meta'] = {}
        value['tokens'] = []
        flat = flatten_recognition(value, 'empty.png')
        self.assertEqual(flat['match']['date'], None)
        self.assertEqual(flat['match']['resultCandidate'], None)
        self.assertEqual(flat['match']['modeCandidate'], None)
        self.assertEqual(flat['players'][0]['fields'], {})


if __name__ == '__main__':
    unittest.main()
