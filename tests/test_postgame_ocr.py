import unittest
from pathlib import Path

import postgame_ocr as p
from screenshot_schema import (FIELD_UNITS, PAGE_FIELDS, PLAYER_FIELDS, SCHEMA,
                               SHARE_FIELDS)

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / 'data' / 'screenshots' / 'samples'


def token(text, x=.2, y=.2, confidence=.99):
    return {'text': text, 'confidence': confidence,
            'box': [[x - .01, y - .01], [x + .01, y - .01],
                    [x + .01, y + .01], [x - .01, y + .01]]}


class ParserTests(unittest.TestCase):
    def test_classify_tabs(self):
        cases = {
            'team': [token('控制效果'), token('治疗量'), token('对塔伤害')],
            'survival': [token('承受伤害'), token('每死承伤')],
            'farming': [token('总经济'), token('野怪经济'), token('补刀数')],
            'output': [token('输出伤害'), token('伤害转化比')],
            'kda': [token('击败'), token('死亡'), token('助攻')],
            'data': [token('输出伤害'), token('承受伤害'), token('总经济'), token('参团率')],
            'score': [token('胜利')],
        }
        for expected, tokens in cases.items():
            self.assertEqual(p.classify_page(tokens), expected, expected)


class ImageQualityTests(unittest.TestCase):
    """聊天软件压缩检测：量化表估算画质，低画质提示重传原图。"""

    def test_recompressed_jpeg_warns(self):
        import io

        from PIL import Image
        image = Image.new('RGB', (1600, 720), (40, 60, 90))
        low = io.BytesIO()
        image.save(low, 'JPEG', quality=70)
        low_quality = p.image_quality(image, raw=low.getvalue())
        self.assertIsNotNone(low_quality['jpegQuality'])
        self.assertLess(low_quality['jpegQuality'], 82)
        self.assertTrue(any('压缩' in warning for warning in low_quality['warnings']))

    def test_original_quality_and_png_stay_silent(self):
        import io

        from PIL import Image
        image = Image.new('RGB', (1600, 720), (40, 60, 90))
        high = io.BytesIO()
        image.save(high, 'JPEG', quality=95)
        high_quality = p.image_quality(image, raw=high.getvalue())
        self.assertGreaterEqual(high_quality['jpegQuality'], 82)
        self.assertFalse(any('压缩' in warning for warning in high_quality['warnings']))
        png = io.BytesIO()
        image.save(png, 'PNG')
        png_quality = p.image_quality(image, raw=png.getvalue())
        self.assertIsNone(png_quality['jpegQuality'])
        self.assertFalse(any('压缩' in warning for warning in png_quality['warnings']))

    def test_split_kda_gold(self):
        cases = {
            '9/4/1313171': (9, 4, 13, 13171),
            '11/7/213011': (11, 7, 2, 13011),
            '7/10/710584': (7, 10, 7, 10584),
            '2/8/159790': (2, 8, 15, 9790),
            '5/5/1611435': (5, 5, 16, 11435),
        }
        for raw, expected in cases.items():
            self.assertEqual(tuple(p._split_kda_gold(raw).values()), expected, raw)
        self.assertIsNone(p._split_kda_gold('218/159790'))

    def test_metric_parsing(self):
        self.assertEqual(p._parse_metric('9.3k', 'big'), 9300)
        self.assertEqual(p._parse_metric('134.3k', 'big'), 134300)
        self.assertEqual(p._parse_metric('117', 'big'), 117)
        self.assertEqual(p._parse_metric('56%', 'percent'), 56)
        self.assertEqual(p._parse_metric('1.3', 'ratio'), 1.3)
        self.assertEqual(p._parse_metric('.3', 'ratio'), .3)
        self.assertEqual(p._parse_metric('27', 'int'), 27)
        self.assertIsNone(p._parse_metric('59.2k', 'int'))

    def test_reversed_percent_tokens_are_marked(self):
        merged = p._normalize_row_percentages([token('80', .94, .7), token('%', .95, .7)])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]['text'], '80%')
        self.assertTrue(merged[0]['_repaired'])
        repaired = p._normalize_row_percentages([token('%6', .25, .7)])
        self.assertEqual(repaired[0]['text'], '6%')
        self.assertTrue(repaired[0]['_repaired'])

    def test_schema_profiles_are_fixed(self):
        self.assertEqual(SCHEMA, 'kpl-postgame-screenshot-v1')
        for page, columns in p.PROFILE_COLUMNS.items():
            for column in columns:
                self.assertIn(column['field'], PAGE_FIELDS[page])
                self.assertIn(column['field'], PLAYER_FIELDS)
                self.assertIn(column['field'], FIELD_UNITS)
                if column['share']:
                    self.assertIn(column['share'], PAGE_FIELDS[page])
                    self.assertIn(column['share'], SHARE_FIELDS)
                    self.assertIn(column['share'], FIELD_UNITS)


class SyntheticMergeTests(unittest.TestCase):
    def result(self, page, players, score=None):
        return {'schema': SCHEMA, 'pageType': page, 'tab': p.TABS[page],
                'file': f'{page}.png',
                'match': {'date': None, 'time': None, 'durationSec': None, 'mode': None,
                          'result': None, 'score': score or {'left': None, 'right': None}},
                'players': players, 'warnings': []}

    def player(self, side, slot, nickname, rating, fields=None, shares=None):
        return {'side': side, 'slot': slot,
                'nickname': {'value': nickname, 'raw': nickname, 'confidence': .99, 'box': None},
                'hero': None, 'heroStatus': 'unreadable', 'heroCandidates': [],
                'rating': {'value': rating, 'raw': str(rating), 'confidence': .99, 'box': None},
                'title': None, 'mvp': False, 'fields': fields or {}, 'shares': shares or {},
                'sources': []}

    def test_different_scores_do_not_merge(self):
        players = [self.player('left', i, f'选手{i}', 10.0) for i in range(5)]
        players += [self.player('right', i, f'对手{i}', 9.0) for i in range(5)]
        a = self.result('score', [dict(item) for item in players], {'left': 20, 'right': 18})
        b = self.result('data', [dict(item) for item in players], {'left': 21, 'right': 18})
        bundles = p.merge_pages([a, b])
        self.assertEqual(len(bundles), 2)

    def test_overlapping_roster_without_score_merges(self):
        players = [self.player('left', i, f'选手{i}', 10.0) for i in range(5)]
        players += [self.player('right', i, f'对手{i}', 9.0) for i in range(5)]
        a = self.result('kda', [dict(item) for item in players])
        b = self.result('data', [dict(item) for item in players])
        bundles = p.merge_pages([a, b])
        self.assertEqual(len(bundles), 1)
        self.assertEqual(len(bundles[0]['pages']), 2)


@unittest.skipUnless((SAMPLES / '01-score.png').is_file(), '缺少真实赛后截图样本')
class RealSampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.results = {}
            for name in ('01-score.png', '02-kda.png', '03-farming.png',
                         '04-survival.png', '05-data.png', '06-output.png', '07-team.png'):
                cls.results[name] = p.recognize((SAMPLES / name).read_bytes(), name=name)
        except ImportError as error:
            raise unittest.SkipTest(f'本地 OCR 组件未安装: {error}')

    def player(self, result, side, slot):
        return next(item for item in result['players']
                    if item['side'] == side and item['slot'] == slot)

    def test_score_page(self):
        result = self.results['01-score.png']
        self.assertEqual(result['pageType'], 'score')
        self.assertEqual(result['match']['date'], '2026-06-17')
        self.assertEqual(result['match']['time'], '12:25')
        self.assertEqual(result['match']['durationSec'], 1132)
        self.assertEqual(result['match']['mode'], '5v5排位')
        self.assertEqual(result['match']['result'], 'win')
        self.assertEqual(result['match']['score'], {'left': 33, 'right': 34})
        first = self.player(result, 'left', 0)
        self.assertEqual(first['nickname']['value'], '古可文de悲伤')
        self.assertEqual(first['rating']['value'], 10.8)
        self.assertEqual(first['title']['value'], '银牌中路')
        self.assertEqual({key: first['fields'][key]['value'] for key in ('kills', 'deaths', 'assists', 'gold')},
                         {'kills': 5, 'deaths': 5, 'assists': 16, 'gold': 11435})
        # v1.5 起截图保持原分辨率，英雄名小字可精确命中词表（此前模糊匹配）。
        self.assertEqual(first['heroStatus'], 'exact')
        self.assertEqual(first['hero']['value'], '武则天')
        self.assertIn('武则天', [candidate['name'] for candidate in first['heroCandidates']])
        right_first = self.player(result, 'right', 0)
        self.assertEqual(right_first['fields']['gold']['value'], 13171)
        self.assertEqual(right_first['fields']['assists']['value'], 13)
        left_last = self.player(result, 'left', 3)
        self.assertEqual(left_last['fields']['assists']['value'], 2)
        self.assertEqual(result['coverage']['kills'], 10)
        self.assertEqual(result['coverage']['gold'], 10)

    def test_kda_page(self):
        result = self.results['02-kda.png']
        self.assertEqual(result['pageType'], 'kda')
        first = self.player(result, 'left', 0)
        self.assertEqual({key: first['fields'][key]['value'] for key in ('kills', 'deaths', 'assists')},
                         {'kills': 2, 'deaths': 5, 'assists': 5})
        self.assertEqual({key: first['shares'][key]['value'] for key in ('killsShare', 'deathsShare', 'assistsShare')},
                         {'killsShare': 14, 'deathsShare': 19, 'assistsShare': 28})
        third = self.player(result, 'right', 2)
        self.assertEqual({key: third['fields'][key]['value'] for key in ('kills', 'deaths', 'assists')},
                         {'kills': 10, 'deaths': 3, 'assists': 7})
        self.assertEqual(result['coverage']['killsShare'], 10)
        self.assertEqual(sum(item['fields']['kills']['value'] for item in result['players'] if item['side'] == 'left'), 14)
        self.assertEqual(sum(item['fields']['kills']['value'] for item in result['players'] if item['side'] == 'right'), 26)

    def test_farming_page(self):
        result = self.results['03-farming.png']
        self.assertEqual(result['pageType'], 'farming')
        self.assertEqual(result['match']['score'], {'left': 14, 'right': 26})
        first = self.player(result, 'left', 0)
        self.assertEqual({key: first['fields'][key]['value'] for key in ('gold', 'jungleGold', 'cs')},
                         {'gold': 9300, 'jungleGold': 804, 'cs': 25})
        self.assertEqual({key: first['shares'][key]['value'] for key in ('goldShare', 'jungleShare', 'csShare')},
                         {'goldShare': 20, 'jungleShare': 20, 'csShare': 17})
        second = self.player(result, 'right', 1)
        self.assertEqual(second['fields']['jungleGold']['value'], 1400)
        self.assertEqual(second['fields']['cs']['value'], 59)

    def test_survival_page(self):
        result = self.results['04-survival.png']
        self.assertEqual(result['pageType'], 'survival')
        first = self.player(result, 'left', 0)
        self.assertEqual(first['fields']['damageTaken']['value'], 52700)
        self.assertEqual(first['fields']['takenPerDeath']['value'], 10500)
        self.assertEqual(first['shares']['takenShare']['value'], 13)
        second = self.player(result, 'left', 1)
        self.assertEqual(second['fields']['damageTaken']['value'], 134300)
        self.assertEqual(second['fields']['takenPerDeath']['value'], 19200)

    def test_data_page(self):
        result = self.results['05-data.png']
        self.assertEqual(result['pageType'], 'data')
        first = self.player(result, 'left', 0)
        self.assertEqual({key: first['fields'][key]['value'] for key in
                          ('damageDealt', 'damageTaken', 'gold', 'participation')},
                         {'damageDealt': 59200, 'damageTaken': 52700, 'gold': 9300, 'participation': 50})
        self.assertEqual({key: first['shares'][key]['value'] for key in
                          ('outputShare', 'takenShare', 'goldShare')},
                         {'outputShare': 22, 'takenShare': 13, 'goldShare': 20})
        right_first = self.player(result, 'right', 0)
        self.assertEqual(right_first['fields']['damageDealt']['value'], 106800)
        self.assertEqual(right_first['fields']['participation']['value'], 69)
        last = self.player(result, 'left', 4)
        self.assertEqual(last['shares']['outputShare']['value'], 9)
        self.assertEqual(self.player(result, 'right', 4)['fields']['participation']['value'], 80)

    def test_output_page(self):
        result = self.results['06-output.png']
        self.assertEqual(result['pageType'], 'output')
        self.assertEqual(self.player(result, 'left', 0)['fields']['damageConversion']['value'], 1.0)
        self.assertEqual(self.player(result, 'right', 2)['fields']['damageConversion']['value'], 1.3)
        self.assertEqual(self.player(result, 'right', 0)['fields']['damageConversion']['value'], 1.4)

    def test_team_page(self):
        result = self.results['07-team.png']
        self.assertEqual(result['pageType'], 'team')
        first = self.player(result, 'left', 0)
        self.assertEqual({key: first['fields'][key]['value'] for key in
                          ('participation', 'control', 'healing', 'towerDamage')},
                         {'participation': 56, 'control': 27, 'healing': 8700, 'towerDamage': 117})
        self.assertEqual({key: first['shares'][key]['value'] for key in
                          ('controlShare', 'healingShare', 'towerShare')},
                         {'controlShare': 27, 'healingShare': 13, 'towerShare': 0})
        self.assertTrue(all(item['hero'] for item in result['players']))
        self.assertEqual(self.player(result, 'right', 4)['shares']['healingShare']['value'], 54)

    def test_same_match_merge(self):
        bundles = p.merge_pages(list(self.results.values()), 'samples')
        self.assertEqual(len(bundles), 3)
        by_pages = {frozenset(item['pageType'] for item in bundle['pages']): bundle
                    for bundle in bundles}
        merged = by_pages[frozenset({'kda', 'data', 'output', 'survival', 'farming'})]
        self.assertEqual(merged['match']['score'], {'left': 14, 'right': 26})
        self.assertEqual(len(merged['players']), 10)
        first = next(item for item in merged['players'] if item['side'] == 'left' and item['slot'] == 0)
        self.assertEqual(first['hero']['value'], '虞姬')
        self.assertEqual(first['nickname']['value'], '摇摇阿菠萝')
        self.assertEqual({key: first['fields'][key]['value'] for key in
                          ('kills', 'deaths', 'assists', 'damageDealt', 'damageTaken',
                           'gold', 'participation', 'damageConversion', 'takenPerDeath',
                           'jungleGold', 'cs')},
                         {'kills': 2, 'deaths': 5, 'assists': 5, 'damageDealt': 59200,
                          'damageTaken': 52700, 'gold': 9300, 'participation': 50,
                          'damageConversion': 1.0, 'takenPerDeath': 10500,
                          'jungleGold': 804, 'cs': 25})
        self.assertFalse(any('不符' in warning for warning in merged['warnings']))
        self.assertIn(frozenset({'score'}), by_pages)
        self.assertIn(frozenset({'team'}), by_pages)
        self.assertEqual(by_pages[frozenset({'score'})]['match']['date'], '2026-06-17')
        self.assertIsNone(by_pages[frozenset({'team'})]['match']['score']['left'])


if __name__ == '__main__':
    unittest.main()
