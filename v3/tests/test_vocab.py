"""赛训词表：版本 / 规则 / 赛制 / 训练组 的归一化与登记。"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import vocab


class VocabNormalizeTest(unittest.TestCase):
    def test_version_aliases(self):
        for raw in ('s40', 'S40', 'S40赛季', ' S 40 ', 'v40', '40'):
            self.assertEqual(vocab.normalize('versions', raw), 'S40', raw)
        self.assertEqual(vocab.normalize('versions', '12.1'), '12.1')
        self.assertEqual(vocab.normalize('versions', ''), '')
        self.assertEqual(vocab.normalize('versions', '__custom__'), '')

    def test_rule_aliases(self):
        self.assertEqual(vocab.normalize('rules', 'kpl全局bp'), '全局BP（KPL）')
        self.assertEqual(vocab.normalize('rules', '全局 BP'), '全局BP（KPL）')
        self.assertEqual(vocab.normalize('rules', '常规征召'), '常规BP')
        self.assertEqual(vocab.normalize('rules', '盲选模式'), '盲选')
        self.assertEqual(vocab.normalize('rules', '巅峰对决'), '巅峰对决')

    def test_format_aliases(self):
        self.assertEqual(vocab.normalize('formats', 'bo3'), 'BO3')
        self.assertEqual(vocab.normalize('formats', 'best of 5'), 'BO5')
        self.assertEqual(vocab.normalize('formats', 'BO7'), 'BO7')

    def test_session_keeps_text(self):
        self.assertEqual(vocab.normalize('sessions', '  周中训练  '), '周中训练')


class VocabStoreTest(unittest.TestCase):
    def test_unknown_value_registers_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(vocab.prepare('versions', 's99赛季', tmp), 'S99')
            self.assertIn('S99', vocab.load(tmp)['versions'])
            vocab.prepare('versions', 'S99', tmp)
            self.assertEqual(vocab.load(tmp)['versions'].count('S99'), 1)

    def test_defaults_sorted_with_newest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            values = vocab.load(tmp)['versions']
            self.assertEqual(values[0], 'S42')
            self.assertIn('S40', values)
            self.assertEqual(values, sorted(values, key=vocab._version_key, reverse=True))

    def test_rule_and_session_persist(self):
        with tempfile.TemporaryDirectory() as tmp:
            vocab.prepare('rules', '自定义规则', tmp)
            vocab.prepare('sessions', '周中训练', tmp)
            loaded = vocab.load(tmp)
            self.assertIn('自定义规则', loaded['rules'])
            self.assertIn('周中训练', loaded['sessions'])

    def test_registered_value_not_re_normalized(self):
        """登记时不能再折一次：全角括号不应被写成半角副本。"""
        with tempfile.TemporaryDirectory() as tmp:
            vocab.prepare('rules', 'kpl全局bp', tmp)
            rules = vocab.load(tmp)['rules']
            self.assertIn('全局BP（KPL）', rules)
            self.assertNotIn('全局BP(KPL)', rules)


class VocabRouteTest(unittest.TestCase):
    def test_vocab_route_is_mounted(self):
        import serve
        paths = {getattr(route, 'path', '') for route in serve.router.routes}
        self.assertIn('/api/v3/vocab', paths)


if __name__ == '__main__':
    unittest.main()
