"""营地载荷的字段档案：路径折叠、中文文案抽取、前端文案提取。

这层不做分析，只保证「营地给过的东西不会因为归一化而消失」。
测试全部跑在内存 / 临时目录上，不发网络请求。
"""
import json
import tempfile
import unittest
from pathlib import Path

import camp_archive


class WalkTests(unittest.TestCase):
    def test_array_index_is_folded(self):
        payload = {'data': {'keyEventArr': [{'id': 1}, {'id': 2}]}}
        paths = [path for path, _ in camp_archive.walk(payload)]
        self.assertEqual(paths, ['data.keyEventArr[].id', 'data.keyEventArr[].id'])

    def test_scalars_and_null_paths(self):
        payload = {'a': None, 'b': True, 'c': 'x'}
        rows = {row['path']: row for row in camp_archive.inventory(payload)}
        self.assertEqual(rows['a']['types'], ['null'])
        self.assertEqual(rows['a']['nonNull'], 0)
        self.assertEqual(rows['b']['types'], ['bool'])
        self.assertEqual(rows['c']['samples'], ['x'])


class InventoryTests(unittest.TestCase):
    def test_counts_and_samples(self):
        payload = {'list': [{'n': 1}, {'n': 2}, {'n': None}]}
        row = next(r for r in camp_archive.inventory(payload) if r['path'] == 'list[].n')
        self.assertEqual(row['count'], 3)
        self.assertEqual(row['nonNull'], 2)
        self.assertEqual(row['samples'], ['1', '2'])

    def test_mixed_types_are_all_kept(self):
        payload = {'v': [1, '1']}
        row = next(r for r in camp_archive.inventory(payload) if r['path'] == 'v[]')
        self.assertEqual(row['types'], ['number', 'string'])

    def test_samples_are_capped(self):
        payload = {'v': list(range(10))}
        row = next(r for r in camp_archive.inventory(payload) if r['path'] == 'v[]')
        self.assertEqual(len(row['samples']), 3)


class TextTests(unittest.TestCase):
    def test_only_chinese_strings(self):
        payload = {'a': '孙悟空', 'b': 'abc', 'c': '', 'd': {'e': '击败主宰'}}
        rows = camp_archive.texts(payload)
        self.assertEqual([row['text'] for row in rows], ['孙悟空', '击败主宰'])
        self.assertEqual(rows[0]['path'], 'a')

    def test_duplicates_collapse(self):
        payload = {'a': '主宰', 'b': '主宰'}
        self.assertEqual(len(camp_archive.texts(payload)), 1)

    def test_min_length(self):
        self.assertEqual(camp_archive.texts({'a': '龙'}), [])


class FrontendLabelTests(unittest.TestCase):
    def test_extracts_chinese_literals_only(self):
        with tempfile.TemporaryDirectory() as temp:
            js = Path(temp) / 'app.js'
            js.write_text("var a='暗影主宰';var b='abc';var c='击杀';var d=1;", encoding='utf-8')
            labels = camp_archive.frontend_labels(js)
            self.assertEqual(labels, ['击杀', '暗影主宰'])

    def test_survives_missing_file(self):
        self.assertEqual(camp_archive.frontend_labels(Path('nope.js')), [])


class BuildTests(unittest.TestCase):
    def test_build_writes_fields_json(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Path(temp)
            folder = store / 'camp-1'
            folder.mkdir()
            (folder / 'raw.json').write_text(json.dumps({
                'data': {'matchInfo': [{'heroName': '钟馗'}], 'camp1Gold': 1}}),
                encoding='utf-8')
            archive = camp_archive.build_for_replay('camp-1', store=store)
            self.assertEqual(archive['schema'], camp_archive.SCHEMA)
            self.assertTrue((folder / 'fields.json').is_file())
            self.assertEqual(archive['texts'][0]['text'], '钟馗')

    def test_missing_raw_returns_none(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertIsNone(camp_archive.build_for_replay('camp-x', store=Path(temp)))

    def test_scan_merges_cases(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Path(temp)
            for seq in (1, 2):
                folder = store / f'camp-{seq}'
                folder.mkdir()
                (folder / 'raw.json').write_text(json.dumps({'data': {'x': seq}}), encoding='utf-8')
            index = camp_archive.scan(store)
            self.assertEqual(index['cases'], 2)
            row = next(r for r in index['fields'] if r['path'] == 'data.x')
            self.assertEqual(row['cases'], 2)
            self.assertEqual(row['count'], 2)


if __name__ == '__main__':
    unittest.main()
