import unittest

import postgame_analysis as analysis


def field(value):
    return {'value': value, 'raw': str(value), 'confidence': .9, 'box': None}


def player(side, slot, kills, deaths, assists, gold, damage, taken, participation=50):
    return {
        'side': side, 'slot': slot,
        'nickname': {'value': f'{side[0]}{slot}', 'raw': f'{side[0]}{slot}', 'confidence': .9, 'box': None},
        'hero': None, 'heroStatus': 'unreadable', 'heroCandidates': [], 'heroReadings': [],
        'rating': field(8.0), 'title': None, 'mvp': False,
        'fields': {
            'kills': field(kills), 'deaths': field(deaths), 'assists': field(assists),
            'gold': field(gold), 'damageDealt': field(damage), 'damageTaken': field(taken),
            'participation': field(participation),
        },
        'shares': {},
    }


def group(players, score=None):
    return {
        'match': {'date': '2026-06-17', 'durationSec': 1132,
                  'score': score or {'left': 14, 'right': 26}},
        'players': players,
        'pages': [{'pageType': 'data'}, {'pageType': 'farming'}],
    }


class PostgameAnalysisTests(unittest.TestCase):
    def test_complete_team_totals_comparison_and_highlights(self):
        players = [player('left', i, 2 + i, 3, 5, 9000 + i * 100, 50000 + i * 1000, 30000)
                   for i in range(5)]
        players += [player('right', i, 5, 4, 8, 10000 + i * 100, 60000 + i * 1000, 40000)
                    for i in range(5)]
        value = analysis.analyze_group(group(players))
        self.assertEqual(value['teams']['left']['totals']['kills'], 2 + 3 + 4 + 5 + 6)
        self.assertTrue(value['teams']['left']['complete']['kills'])
        self.assertEqual(value['teams']['left']['kdaRatio'], round((20 + 25) / 15, 2))
        self.assertTrue(value['comparisons']['gold']['complete'])
        self.assertEqual(value['comparisons']['gold']['difference'], 46000 - 51000)
        self.assertTrue(any(item['field'] == 'damageDealt' for item in value['highlights']))
        top = next(item for item in value['players'] if item['side'] == 'right' and item['slot'] == 4)
        self.assertEqual(top['analysis']['ranks']['damageDealt'], 1)

    def test_partial_fields_are_not_promoted_to_team_totals(self):
        players = [player('left', i, 1, 2, 3, 9000, 50000, 30000) for i in range(4)]
        players.append(player('left', 4, 1, 2, 3, 9000, 50000, 30000))
        players[-1]['fields'].pop('damageDealt')
        players += [player('right', i, 2, 2, 3, 8000, 40000, 25000) for i in range(5)]
        value = analysis.analyze_group(group(players))
        self.assertFalse(value['teams']['left']['complete']['damageDealt'])
        self.assertEqual(value['teams']['left']['samples']['damageDealt'], 4)
        self.assertFalse(value['comparisons']['damageDealt']['complete'])
        self.assertTrue(any('不计算团队合计' in warning for warning in value['warnings']))

    def test_team_page_without_score_does_not_invent_kills(self):
        players = [player('left', i, 0, 0, 0, 0, 0, 0) for i in range(5)]
        players += [player('right', i, 0, 0, 0, 0, 0, 0) for i in range(5)]
        for item in players:
            item['fields'] = {'participation': field(50), 'control': field(20),
                              'healing': field(9000), 'towerDamage': field(100)}
        value = analysis.analyze_group(group(players, {'left': None, 'right': None}))
        self.assertIsNone(value['teams']['left']['totals']['kills'])
        self.assertEqual(value['teams']['left']['totals']['healing'], 45000)
        self.assertIn('没有完整比分', value['warnings'][0])


if __name__ == '__main__':
    unittest.main()
