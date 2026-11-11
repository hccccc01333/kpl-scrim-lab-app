import json
import tempfile
import unittest
from pathlib import Path

import sheet_import as s

try:
    from openpyxl import Workbook
except ImportError:
    Workbook = None

MATCH = """日期,对局ID,选手,英雄,击杀,死亡,助攻,经济,输出,承伤,参团率,评分,胜负,备注
2026-10-28,M1,茉莉花与雨,孙膑,1,2,12,9.8k,12.5k,16.0k,80%,12.3,胜,替补
2026-10-28,M1,影,影,7,4,5,11.7k,31.2k,22.4k,72.5%,12.8,胜,首发
"""
AGG = """选手,英雄,场次,胜场,胜率,场均经济,场均伤害,参团率
茉莉花与雨,孙膑,10,7,70%,9.8k,31.2k,72%
"""
EVENT = """日期,对局ID,时间,选手,英雄,事件,技能,x,y
2026-10-28,M1,00:12,影,影,技能命中,1,1200,800
"""
WIDE = """日期,对局ID,蓝方上单_选手,蓝方上单_英雄,蓝方上单_击杀,蓝方上单_死亡,蓝方上单_助攻,蓝方上单_经济,红方射手_选手,红方射手_英雄,红方射手_击杀,红方射手_死亡,红方射手_助攻,红方射手_经济
2026-10-28,M1,影,影,7,4,5,11.7k,鲁班七号,鲁班七号,6,3,5,12.0k
"""


class SheetImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def csv(self, text, name='data.csv', encoding='utf-8-sig'):
        path = self.root / name
        path.write_bytes(text.encode(encoding))
        return path

    def read(self, text, name='data.csv', encoding='utf-8-sig'):
        return s.read_workbook(self.csv(text, name, encoding))

    def test_read_gbk(self):
        workbook = self.read(MATCH, 'gbk.csv', 'gb18030')
        self.assertEqual(workbook['sheets'][0]['name'], 'CSV')
        self.assertEqual(workbook['sheets'][0]['header'][0], '日期')
        self.assertEqual(len(workbook['sheets'][0]['rows']), 2)

    def test_match_player_inference_and_apply(self):
        sheet = self.read(MATCH)['sheets'][0]
        profile = s.infer_profile(sheet)
        self.assertEqual(profile['grain'], 'match_player')
        self.assertEqual(profile['keys']['player'], '选手')
        self.assertIn('kills', profile['metrics'])
        self.assertIn('win', profile['dimensions'])
        self.assertIn('备注', profile['unmappedColumns'])
        applied = s.apply_profile(sheet, profile)
        self.assertEqual(applied['quality']['rows'], 2)
        first = applied['rows'][0]
        self.assertEqual(first['keys']['date'], '2026-10-28')
        self.assertEqual(first['metrics']['gold']['value'], 9800)
        self.assertEqual(first['metrics']['participation']['value'], 80)
        self.assertEqual(first['dimensions']['win'], 1)
        self.assertIn('备注', first['raw'])

    def test_aggregate_inference_marks_aggregated(self):
        sheet = self.read(AGG)['sheets'][0]
        profile = s.infer_profile(sheet)
        self.assertEqual(profile['grain'], 'aggregate_player')
        self.assertIn('games', profile['metrics'])
        self.assertIn('winRate', profile['metrics'])
        applied = s.apply_profile(sheet, profile)
        self.assertTrue(applied['rows'][0]['aggregated'])
        metrics = applied['rows'][0]['metrics']
        self.assertEqual(metrics['games']['value'], 10)
        self.assertEqual(metrics['winRate']['value'], 70)
        self.assertEqual(metrics['avgGold']['value'], 9800)
        self.assertTrue(any('聚合表' in warning for warning in applied['warnings']))

    def test_match_table_treats_cichang_as_match_no(self):
        text = '日期,场次,选手,英雄,击杀\n2026-10-28,3,甲,影,7\n'
        sheet = self.read(text)['sheets'][0]
        profile = s.infer_profile(sheet)
        self.assertEqual(profile['grain'], 'match_player')
        self.assertEqual(profile['keys']['matchNo'], '场次')
        self.assertNotIn('games', profile['metrics'])

    def test_match_table_with_aggregate_column_is_flagged(self):
        text = '日期,对局ID,选手,英雄,击杀,胜率\n2026-10-28,M1,甲,影,7,62%\n'
        sheet = self.read(text)['sheets'][0]
        profile = s.infer_profile(sheet)
        self.assertEqual(profile['grain'], 'match_player')
        self.assertTrue(profile['metrics']['winRate'].get('aggregate'))
        self.assertTrue(any('跨局聚合列' in warning for warning in profile['warnings']))

    def test_date_with_time_and_duration_minutes(self):
        text = '日期,选手,击杀\n2026/10/28 13:51,甲,1\n'
        sheet = self.read(text)['sheets'][0]
        profile = s.infer_profile(sheet)
        applied = s.apply_profile(sheet, profile)
        self.assertEqual(applied['rows'][0]['keys']['date'], '2026-10-28')

        text = '选手,时长(分钟)\n甲,18.5\n'
        sheet = self.read(text, 'duration.csv')['sheets'][0]
        profile = {'profileVersion': 1, 'sheet': 'CSV', 'grain': 'aggregate_player',
                   'keys': {'player': '选手'},
                   'metrics': {'duration': {'column': '时长(分钟)', 'kind': 'total',
                                            'unit': 'minutes'}},
                   'dimensions': {}, 'uniqueBy': ['player']}
        applied = s.apply_profile(sheet, profile)
        self.assertEqual(applied['rows'][0]['metrics']['duration']['value'], 1110)

    def test_event_inference_and_time(self):
        sheet = self.read(EVENT)['sheets'][0]
        profile = s.infer_profile(sheet)
        self.assertEqual(profile['grain'], 'event')
        self.assertEqual(profile['uniqueBy'], [])
        applied = s.apply_profile(sheet, profile)
        row = applied['rows'][0]
        self.assertEqual(row['keys']['time'], 12)
        self.assertEqual(row['keys']['event'], '技能命中')
        self.assertEqual(row['metrics']['x']['value'], 1200)

    def test_wide_detection_and_explicit_expansion(self):
        sheet = self.read(WIDE)['sheets'][0]
        profile = s.infer_profile(sheet)
        self.assertEqual(profile['grain'], 'match_wide')
        self.assertEqual(profile['wide']['players'], [])
        explicit = {
            'profileVersion': 1, 'sheet': 'CSV', 'grain': 'match_wide',
            'keys': {'date': '日期', 'matchId': '对局ID'},
            'metrics': {}, 'dimensions': {}, 'uniqueBy': [],
            'wide': {'players': [
                {'side': 'blue', 'slot': 0, 'columns': {
                    'player': '蓝方上单_选手', 'hero': '蓝方上单_英雄',
                    'kills': '蓝方上单_击杀', 'deaths': '蓝方上单_死亡',
                    'assists': '蓝方上单_助攻', 'gold': '蓝方上单_经济'}},
                {'side': 'red', 'slot': 0, 'columns': {
                    'player': '红方射手_选手', 'hero': '红方射手_英雄',
                    'kills': '红方射手_击杀', 'deaths': '红方射手_死亡',
                    'assists': '红方射手_助攻', 'gold': '红方射手_经济'}},
            ]},
        }
        applied = s.apply_profile(sheet, explicit)
        self.assertEqual(len(applied['rows']), 2)
        blue = applied['rows'][0]
        self.assertEqual((blue['keys']['side'], blue['keys']['slot']), ('blue', 0))
        self.assertEqual(blue['keys']['hero'], '影')
        self.assertEqual(blue['metrics']['kills']['value'], 7)
        self.assertEqual(applied['rows'][1]['keys']['side'], 'red')
        self.assertEqual(applied['rows'][1]['metrics']['gold']['value'], 12000)

    def test_percentage_ratio_units_and_range(self):
        text = 'player,participation,winRate,gold,duration\n甲,120%,0.6,1.2万,18:30\n'
        sheet = self.read(text)['sheets'][0]
        profile = {
            'profileVersion': 1, 'sheet': 'CSV', 'grain': 'aggregate_player',
            'keys': {'player': 'player'},
            'metrics': {
                'participation': {'column': 'participation', 'kind': 'percentage'},
                'winRate': {'column': 'winRate', 'kind': 'percentage'},
                'gold': {'column': 'gold', 'kind': 'total'},
                'duration': {'column': 'duration', 'kind': 'total', 'unit': 'seconds'},
            },
            'dimensions': {}, 'uniqueBy': ['player'],
        }
        applied = s.apply_profile(sheet, profile)
        metrics = applied['rows'][0]['metrics']
        self.assertFalse(metrics['participation']['valid'])
        self.assertEqual(metrics['winRate']['value'], 60)
        self.assertEqual(metrics['gold']['value'], 12000)
        self.assertEqual(metrics['duration']['value'], 1110)
        self.assertEqual(applied['quality']['invalidMetrics'], 1)

    def test_duplicate_keys(self):
        text = '日期,对局ID,选手,英雄,击杀\n2026-10-28,M1,甲,影,1\n2026-10-28,M1,甲,影,2\n'
        sheet = self.read(text)['sheets'][0]
        profile = s.infer_profile(sheet)
        applied = s.apply_profile(sheet, profile)
        self.assertEqual(applied['quality']['duplicates'], 1)
        self.assertTrue(any('重复' in warning for warning in applied['warnings']))

    def test_missing_required_key_warns(self):
        sheet = self.read('选手,击杀\n甲,1\n')['sheets'][0]
        profile = {'profileVersion': 1, 'sheet': 'CSV', 'grain': 'match_player',
                   'keys': {}, 'metrics': {'kills': {'column': '击杀', 'kind': 'total'}},
                   'dimensions': {}, 'uniqueBy': []}
        applied = s.apply_profile(sheet, profile)
        self.assertTrue(any('缺少必需键' in warning for warning in applied['warnings']))

    def test_profile_missing_column_raises(self):
        sheet = self.read(MATCH)['sheets'][0]
        profile = {'profileVersion': 1, 'sheet': 'CSV', 'grain': 'match_player',
                   'keys': {'player': '不存在'}, 'metrics': {}, 'dimensions': {}}
        with self.assertRaises(s.SheetImportError):
            s.apply_profile(sheet, profile)

    def test_write_staging(self):
        workbook = self.read(MATCH)
        sheet = workbook['sheets'][0]
        profile = s.infer_profile(sheet)
        out = self.root / 'import'
        manifest = s.write_staging(workbook['source'], [sheet], {'CSV': profile}, out)
        self.assertEqual(manifest['schema'], s.SCHEMA)
        self.assertEqual(manifest['quality']['rows'], 2)
        self.assertTrue((out / 'manifest.json').is_file())
        self.assertTrue((out / 'profile.json').is_file())
        rows_file = out / manifest['sheets'][0]['rowsFile']
        self.assertTrue(rows_file.is_file())
        first = json.loads(rows_file.read_text(encoding='utf-8').splitlines()[0])
        self.assertEqual(first['metrics']['kills']['value'], 1)

    def test_write_staging_keeps_own_side(self):
        workbook = self.read(MATCH)
        sheet = workbook['sheets'][0]
        profile = s.infer_profile(sheet)
        profile['ownSide'] = 'blue'
        out = self.root / 'import-side'
        manifest = s.write_staging(workbook['source'], [sheet], {'CSV': profile}, out)
        self.assertEqual(manifest['sheets'][0]['ownSide'], 'blue')

    def test_template_own_side_maps_to_key(self):
        path = Path(__file__).resolve().parents[1] / 'web/capture-guide/match-sample.csv'
        sheet = s.read_workbook(path)['sheets'][0]
        profile = s.infer_profile(sheet)
        self.assertEqual(profile['keys'].get('ownSide'), '本队阵营')
        applied = s.apply_profile(sheet, profile)
        self.assertEqual(applied['rows'][0]['keys']['ownSide'], 'blue')

    @unittest.skipUnless(Workbook, 'openpyxl unavailable')
    def test_xlsx(self):
        path = self.root / 'data.xlsx'
        book = Workbook()
        sheet = book.active
        sheet.title = '对局'
        sheet.append(['日期', '对局ID', '选手', '英雄', '击杀', '死亡', '助攻'])
        sheet.append(['2026-10-28', 'M1', '甲', '影', 7, 4, 5])
        book.save(path)
        workbook = s.read_workbook(path)
        self.assertEqual(workbook['sheets'][0]['name'], '对局')
        profile = s.infer_profile(workbook['sheets'][0])
        self.assertEqual(profile['grain'], 'match_player')
        applied = s.apply_profile(workbook['sheets'][0], profile)
        self.assertEqual(applied['rows'][0]['metrics']['kills']['value'], 7)


if __name__ == '__main__':
    unittest.main()
