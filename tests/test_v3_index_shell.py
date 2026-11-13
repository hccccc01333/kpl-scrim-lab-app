"""V3 外壳的资源版本戳（?v=）与 app-version 注入。

现场问题：1.6.0–1.6.4 的 index.html 一直没变，而旧实现用 index.html 的
mtime 当 ``?v=``，所以每个版本给浏览器的是**同一个 app.js/style.css URL**。
覆盖安装后只要浏览器/标签页还留着旧响应，就会觉得「某些页面还是旧页面」。
这里锁住：URL 必须带版本号，且 public 里任一文件变化都会换戳。
"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = ROOT / 'test-results' / f'v3-shell-{os.getpid()}'
TMP.mkdir(parents=True, exist_ok=True)
os.environ.setdefault('TRAINING_DB', str(TMP / 'training.sqlite3'))
os.environ.setdefault('ANALYSIS_MATCHES', str(TMP / 'matches'))
os.environ.setdefault('ANALYSIS_IMPORTS', str(TMP / 'imports'))
os.environ.setdefault('CAMP_CONFIG_FILE', str(TMP / 'camp_config.json'))
os.environ.setdefault('CAMP_DETAIL_DIR', str(TMP / 'camp_details'))

import server  # noqa: E402

INDEX = """<!doctype html>
<html lang="zh-CN"><head>
  <meta charset="utf-8">
  <link rel="stylesheet" href="static/style.css">
  <script type="module" src="static/app.js"></script>
</head><body><div id="app"></div></body></html>
"""


def version_of(body: str, asset: str) -> str:
    import re
    match = re.search(rf'static/{asset}\?v=([^"\']+)', body)
    return match.group(1) if match else ''


class V3IndexShellTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        public = self.root / 'v3' / 'public'
        public.mkdir(parents=True)
        (public / 'index.html').write_text(INDEX, encoding='utf-8')
        (public / 'app.js').write_text('// app\n', encoding='utf-8')
        (public / 'style.css').write_text('/* css */\n', encoding='utf-8')
        (public / 'capture-page.js').write_text('// page\n', encoding='utf-8')
        self.public = public
        for patch in (mock.patch.object(server, 'ROOT', self.root),
                      mock.patch.object(server, 'VERSION', '9.9.9')):
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(self.temp.cleanup)

    def test_stamp_is_version_based_and_covers_both_assets(self):
        body = server._v3_index_body()
        app = version_of(body, 'app.js')
        css = version_of(body, 'style.css')
        self.assertTrue(app.startswith('9.9.9-'), app)
        self.assertEqual(app, css)

    def test_meta_app_version_is_injected_once(self):
        body = server._v3_index_body()
        self.assertEqual(body.count('name="app-version"'), 1)
        self.assertIn('<meta name="app-version" content="9.9.9">', body)

    def test_touching_any_public_file_changes_the_stamp(self):
        first = version_of(server._v3_index_body(), 'app.js')
        later = time.time() + 300
        os.utime(self.public / 'capture-page.js', (later, later))
        second = version_of(server._v3_index_body(), 'app.js')
        self.assertNotEqual(first, second)
        # 只改了一个页面模块，app.js / style.css 的 URL 也一起换。
        self.assertEqual(second, version_of(server._v3_index_body(), 'style.css'))

    def test_godmode_js_uses_the_same_stamp(self):
        # 页面里写死的 ?v=8.0.0 必须被换成统一戳，否则改了 godmode.js
        # 升级后浏览器仍用旧副本（和 1.6.0–1.6.4 的旧缓存问题是同一类）。
        (self.public / 'godmode.js').write_text('// gm\n', encoding='utf-8')
        (self.public / 'index.html').write_text(
            INDEX.replace('</head>',
                          '  <script type="module" src="static/godmode.js?v=8.0.0"></script>\n</head>'),
            encoding='utf-8')
        body = server._v3_index_body()
        gm = version_of(body, 'godmode.js')
        self.assertTrue(gm.startswith('9.9.9-'), gm)
        self.assertEqual(gm, version_of(body, 'app.js'))

    def test_workspace_home_css_is_versioned_and_in_fallback(self):
        # 首页样式表是独立文件；漏掉它首页会「能用但没样式」，
        # 而且 ?v= 不覆盖它时升级后浏览器还会拿旧 CSS。
        (self.public / 'workspace-home.css').write_text('/* home */\n', encoding='utf-8')
        (self.public / 'index.html').write_text(
            INDEX.replace(
                '<link rel="stylesheet" href="static/style.css">',
                '<link rel="stylesheet" href="static/style.css">\n'
                '  <link rel="stylesheet" href="static/workspace-home.css">'),
            encoding='utf-8')
        body = server._v3_index_body()
        home = version_of(body, 'workspace-home.css')
        self.assertTrue(home.startswith('9.9.9-'), home)
        self.assertEqual(home, version_of(body, 'app.js'))

        # 兜底外壳同样要带首页样式，且同样换成统一版本戳。
        (self.public / 'index.html').write_text('<html><body>坏了</body></html>',
                                                encoding='utf-8')
        fallback = server._v3_index_body()
        self.assertIn('static/workspace-home.css?v=9.9.9-', fallback)

    def test_broken_shell_falls_back_but_keeps_version_markup(self):
        (self.public / 'index.html').write_text('<html><body>坏了</body></html>',
                                                encoding='utf-8')
        body = server._v3_index_body()
        self.assertIn('id="app"', body)
        self.assertIn('name="app-version"', body)
        self.assertTrue(version_of(body, 'app.js').startswith('9.9.9-'))


if __name__ == '__main__':
    unittest.main()
