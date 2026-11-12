"""launcher.py 与打包脚本的回归测试（不启动真实工作台）。"""
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

import launcher  # noqa: E402
import make_installer  # noqa: E402
import make_release  # noqa: E402


class AddressTests(unittest.TestCase):
    def test_wildcard_host_becomes_loopback(self):
        with mock.patch.dict(os.environ,
                             {'TRAINING_HOST': '0.0.0.0', 'TRAINING_PORT': '9001'}):
            self.assertEqual(launcher._base_url(), 'http://127.0.0.1:9001')

    def test_bad_port_falls_back(self):
        with mock.patch.dict(os.environ, {'TRAINING_PORT': 'not-a-port'}):
            self.assertEqual(launcher._port(), 8766)

    def test_server_python_always_resolves(self):
        self.assertTrue(str(launcher.server_python()))


class HealthTests(unittest.TestCase):
    def _serve(self, payload: dict):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - stdlib naming
                body = json.dumps(payload).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):  # noqa: D401 - silence test output
                return

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def test_health_returns_payload(self):
        port = self._serve({'ok': True, 'pid': 4242, 'version': '1.0.0'})
        with mock.patch.dict(os.environ, {'TRAINING_PORT': str(port)}):
            payload = launcher.health()
        self.assertEqual(payload['pid'], 4242)

    def test_health_ignores_not_ok(self):
        port = self._serve({'ok': False})
        with mock.patch.dict(os.environ, {'TRAINING_PORT': str(port)}):
            self.assertIsNone(launcher.health())

    def test_closed_port_is_not_ready(self):
        with mock.patch.dict(os.environ, {'TRAINING_PORT': '9'}):
            self.assertIsNone(launcher.health(timeout=0.3))


class VersionDriftTests(unittest.TestCase):
    """覆盖安装后旧服务还占着端口时，启动器要先停掉旧服务。

    现场问题：程序文件已经被覆盖成新版，但 8766 上还是旧进程（Python 代码
    在内存里不会跟着文件更新）。启动器原来只看 /api/health 有没有响应，
    有响应就直接开浏览器，界面于是还是旧版本。
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        patch = mock.patch.object(launcher, 'ROOT', self.root)
        patch.start()
        self.addCleanup(patch.stop)

    def _write_version(self, version: str) -> None:
        (self.root / 'version.py').write_text(
            f"VERSION = '{version}'\nRELEASE_DATE = '2026-11-11'\n", encoding='utf-8')

    def test_same_version_is_not_stale(self):
        self._write_version('1.6.4')
        self.assertEqual(launcher.installed_version(), '1.6.4')
        self.assertEqual(launcher.stale_running_version({'version': '1.6.4'}), '')

    def test_older_running_service_is_stale(self):
        self._write_version('1.6.4')
        self.assertEqual(launcher.stale_running_version({'version': '1.6.2'}), '1.6.2')

    def test_unknown_version_never_triggers_restart(self):
        self._write_version('1.6.4')
        self.assertEqual(launcher.stale_running_version({}), '')
        self.assertEqual(launcher.stale_running_version(None), '')
        (self.root / 'version.py').unlink()
        self.assertEqual(launcher.installed_version(), '')
        self.assertEqual(launcher.stale_running_version({'version': '1.6.2'}), '')


class PackagingTests(unittest.TestCase):
    def test_version4_pads_to_four_parts(self):
        self.assertEqual(make_installer.version4('1.0.0'), '1.0.0.0')
        self.assertEqual(make_installer.version4('2.3'), '2.3.0.0')

    def test_ship_files_skips_editor_and_temp_dotfiles(self):
        names = make_release.ship_files()
        self.assertIn('launcher.py', names)
        self.assertIn('server.py', names)
        # 作者本机的 .tmp_*.py 和编辑器 .TMP 曾被打进安装包，这里守住这条线。
        self.assertFalse([name for name in names
                          if name.startswith('.') and name.endswith('.py')])
        self.assertFalse([name for name in names if '~RF' in name])
        self.assertFalse([name for name in names if name.endswith('.TMP')])

    def test_full_package_contains_launcher(self):
        self.assertIn('launcher.py', make_release.ship_files())


if __name__ == '__main__':
    unittest.main()
