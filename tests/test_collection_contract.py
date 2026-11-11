import copy
import unittest
from pathlib import Path
import channel_store as c
from collection_contract import validate_sheet, validate_table, PAGE_TYPES, reject_example_table
from sheet_import import read_workbook
from tests.collection_fixtures import complete_collection


class CollectionContractTests(unittest.TestCase):
    def sheet(self):
        source = Path(__file__).resolve().parents[1] / 'web/capture-guide/match-example.csv'
        sheet = copy.deepcopy(read_workbook(source)['sheets'][0])
        sheet['rows'] = [[str(value).replace('EXAMPLE-请替换','real-match-1') if isinstance(value,str) else value for value in row] for row in sheet['rows']]
        return sheet

    def test_example_is_rejected_until_replaced(self):
        sheet = self.sheet()
        sheet['rows'][0][0] = 'EXAMPLE-请替换'
        with self.assertRaisesRegex(ValueError,'示例数据'):
            validate_sheet(sheet)

    def test_ten_rows_and_optional_null_metrics(self):
        sheet = self.sheet()
        for row in sheet['rows']:
            for column in range(7,16):
                row[column] = None
        validate_sheet(sheet, {'date':'2026-11-04'})
        self.assertIsNone(sheet['rows'][0][7])

    def test_reject_wrong_headers_mixed_matches_and_dates(self):
        for key, value, expected in [('对局ID','other-match','必须一致'),('日期','2026-11-03','必须一致'),('经济','1.2万','原始数值')]:
            sheet = self.sheet()
            sheet['rows'][1][sheet['header'].index(key)] = value
            with self.assertRaisesRegex(ValueError,expected):
                validate_sheet(sheet)
        sheet = self.sheet();sheet['header'][0]='任意编号'
        with self.assertRaisesRegex(ValueError,'请使用本项目'):
            validate_sheet(sheet)

    def test_reject_duplicates_missing_and_invalid_metrics(self):
        for key,value,expected in [('阵营','red','双方|阵营'),('分路','打野','分路'),('击杀',-1,'无效'),('参团率',101,'0–100'),('选手','示例蓝2','重复')]:
            sheet=self.sheet();sheet['rows'][0][sheet['header'].index(key)]=value
            with self.assertRaisesRegex(ValueError,expected):
                validate_sheet(sheet)
        sheet=self.sheet();sheet['rows'].pop()
        with self.assertRaisesRegex(ValueError,'10 行'):
            validate_sheet(sheet)

    def test_example_only_import_is_rejected(self):
        source = Path(__file__).resolve().parents[1] / 'web/capture-guide/match-example.csv'
        sheet = copy.deepcopy(read_workbook(source)['sheets'][0])
        with self.assertRaisesRegex(ValueError, '示例编号'):
            reject_example_table(sheet)
        sheet['rows'][0][0] = 'real-match-1'
        reject_example_table(sheet)

    def test_own_side_is_required_and_consistent(self):
        sheet = self.sheet()
        index = sheet['header'].index('本队阵营')
        sheet['rows'][0][index] = 'red'
        with self.assertRaisesRegex(ValueError, '本队阵营十行必须一致'):
            validate_sheet(sheet)
        sheet = self.sheet()
        sheet['rows'][0][index] = '绿'
        with self.assertRaisesRegex(ValueError, '本队阵营'):
            validate_sheet(sheet)

    def test_multi_match_blocks_each_need_ten_rows(self):
        sheet = self.sheet()
        first = [list(row) for row in sheet['rows']]
        second = [list(row) for row in first]
        for row in second:
            row[0] = 'real-match-2'
        table = {'name': '多局', 'header': list(sheet['header']), 'rows': first + second}
        self.assertEqual(validate_table(table), {'real-match-1': 10, 'real-match-2': 10})
        table['rows'] = first + second[:9]
        with self.assertRaisesRegex(ValueError, '10 行'):
            validate_table(table)

    def test_valid_template_normalizes_metrics(self):
        sheet=self.sheet();validate_sheet(sheet,{'date':'2026-11-04'})
        self.assertEqual(sheet['rows'][0][7],1)
        self.assertEqual(sheet['rows'][0][13],26.7)

    def test_required_sources_and_single_video(self):
        channel=c.blank();channel['id']='test'
        with self.assertRaisesRegex(ValueError,'王者营地'):
            c.set_review(channel,'tester')
        complete_collection(channel)
        status=c.source_status(channel)
        self.assertTrue(status['complete'])
        self.assertEqual(status['required']['video'],0)
        self.assertEqual(status['required']['table'],0)
        self.assertEqual(status['statuses']['table'],'missing')
        c.set_review(channel,'tester')
        self.assertEqual(c.bundle(channel)['schema'],'kpl-match-data-v1')

    def test_legacy_eleven_video_count_is_now_one(self):
        channel=complete_collection(c.blank())
        channel['sources']['video']['required']=11
        self.assertEqual(c.source_status(channel)['statuses']['video'],'completed')

    def test_seven_duplicates_do_not_satisfy_seven_page_types(self):
        channel=complete_collection(c.blank())
        channel['sources']['screenshot']['group']['pages']=[{'pageType':'data'}]*7
        self.assertFalse(c.source_status(channel)['complete'])
        with self.assertRaisesRegex(ValueError,'营地十人面板'):
            c.set_review(channel,'tester')

    def test_direct_save_cannot_bypass_source_gate(self):
        channel=complete_collection(c.blank());channel['id']='test'
        c.set_review(channel,'tester')
        # 去掉营地来源，并把截图/录屏也清空：剩下一条没有任何合规材料的 camp 通道，
        # bundle 必须仍然拒绝（save 不能绕过必采门禁）。
        # 注意：只 pop official 而不清素材，现在会按 OCR 新录入通道识别为合规，
        # 那是另一条路径的正常行为，见 tests/test_channel_entry_api.py。
        channel.pop('official')
        channel['sources']['screenshot'].update({'imageIds': [], 'group': None, 'status': 'missing'})
        channel['sources']['video'].update({'files': [], 'roster': [], 'status': 'missing'})
        c.rebuild(channel)
        with self.assertRaisesRegex(ValueError,'王者营地'):
            c.bundle(channel)


if __name__=='__main__':
    unittest.main()
