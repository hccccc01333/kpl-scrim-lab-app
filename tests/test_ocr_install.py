"""Mimo / 主 OCR 一键安装：后台跑、可切页面、状态可查。

真实安装会下载数 GB 依赖，测试里只替换 pip 与模型下载，验证任务状态机：
开始 → 运行中（再次点击 409）→ 完成 / 失败，以及 rapid 不触发模型下载。
"""
import os
import pathlib
import sys
import threading
import time
import unittest
import uuid
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = ROOT / 'test-results' / f'ocr-install-{uuid.uuid4().hex}'
TMP.mkdir(parents=True, exist_ok=True)
os.environ.setdefault('TRAINING_DB', str(TMP / 'training.sqlite3'))
os.environ.setdefault('ANALYSIS_MATCHES', str(TMP / 'matches'))
os.environ.setdefault('CAMP_CONFIG_FILE', str(TMP / 'camp_config.json'))
os.environ.setdefault('CAMP_DETAIL_DIR', str(TMP / 'camp_details'))
os.environ.setdefault('CAMP_SYNC_STATE', str(TMP / 'camp_sync_state.json'))

from fastapi.testclient import TestClient

import server
from server import app


class OcrInstallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, base_url='http://localhost')

    def setUp(self):
        with server._OCR_INSTALL_LOCK:
            server._OCR_INSTALL_JOB.clear()
            server._OCR_INSTALL_JOB.update({
                'running': False, 'target': '', 'phase': '', 'message': '', 'percent': 0,
                'error': '', 'startedAt': None, 'finishedAt': None,
                'bytes': 0, 'totalBytes': 0, 'log': [],
            })
        # 默认给足磁盘空间；磁盘不足的用例自己覆盖。
        disk = mock.patch.object(server.shutil, 'disk_usage',
                                 return_value=mock.Mock(free=50 * 1024 ** 3))
        disk.start()
        self.addCleanup(disk.stop)

    def _wait_done(self, timeout=5.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            status = self.client.get('/api/ocr/install').json()
            if not status['running']:
                return status
            time.sleep(0.03)
        self.fail('安装任务没有在预期时间内结束')

    def test_mimo_install_runs_in_background_then_done(self):
        release = threading.Event()
        calls = []
        fake_usage = mock.Mock(free=50 * 1024 ** 3, used=10 * 1024 ** 3, total=60 * 1024 ** 3)

        def fake_pip(name):
            calls.append(name)
            release.wait(3)
            return True, 'Successfully installed'

        with mock.patch.object(server, '_pip_install', side_effect=fake_pip), \
                mock.patch.object(server, '_download_mimo_model',
                                  side_effect=lambda: calls.append('model')), \
                mock.patch.object(server.shutil, 'disk_usage', return_value=fake_usage), \
                mock.patch.object(server.mimo_ocr, 'model_path', return_value=None):
            first = self.client.post('/api/ocr/install', params={'target': 'mimo'})
            self.assertEqual(first.status_code, 200, first.text)
            running = self.client.get('/api/ocr/install').json()
            self.assertTrue(running['running'])
            self.assertEqual(running['target'], 'mimo')
            # 安装中再点一次：明确拒绝，不重复开线程
            again = self.client.post('/api/ocr/install', params={'target': 'mimo'})
            self.assertEqual(again.status_code, 409)
            release.set()
            done = self._wait_done()

        self.assertEqual(done['phase'], 'done')
        self.assertEqual(done['percent'], 100)
        self.assertEqual(calls, ['requirements-mimo.txt', 'model'])

    def test_rapid_install_does_not_touch_model(self):
        downloaded = []
        with mock.patch.object(server, '_pip_install', return_value=(True, 'ok')), \
                mock.patch.object(server, '_download_mimo_model',
                                  side_effect=lambda: downloaded.append(1)):
            response = self.client.post('/api/ocr/install', params={'target': 'rapid'})
            self.assertEqual(response.status_code, 200)
            done = self._wait_done()
        self.assertEqual(done['phase'], 'done')
        self.assertEqual(downloaded, [])

    def test_failure_is_reported_not_swallowed(self):
        with mock.patch.object(server, '_pip_install', return_value=(False, '网络错误')):
            self.client.post('/api/ocr/install', params={'target': 'rapid'})
            done = self._wait_done()
        self.assertEqual(done['phase'], 'error')
        self.assertIn('网络错误', done['error'])

    def test_insufficient_disk_is_reported(self):
        with mock.patch.object(server.shutil, 'disk_usage',
                               return_value=mock.Mock(free=200 * 1024 ** 2)):
            response = self.client.post('/api/ocr/install', params={'target': 'rapid'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('磁盘', response.json()['detail'])

    def test_unknown_target_is_rejected(self):
        response = self.client.post('/api/ocr/install', params={'target': 'tensorrt'})
        self.assertEqual(response.status_code, 400)

    def test_missing_requirement_file_is_rejected(self):
        with mock.patch.object(server, 'ROOT', TMP):
            response = self.client.post('/api/ocr/install', params={'target': 'rapid'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('requirements-ocr.txt', response.json()['detail'])


class AutoInstallTests(unittest.TestCase):
    """首次启动自动补装主 OCR：只装一次、失败每天重试一次、可关闭。"""

    def test_skips_when_available(self):
        called = []
        result = server.maybe_auto_install_ocr(available=True, start=lambda: called.append(1))
        self.assertEqual(result, {'started': False, 'reason': 'already-installed'})
        self.assertEqual(called, [])

    def test_disabled_by_env(self):
        called = []
        with mock.patch.dict(os.environ, {'KPL_OCR_AUTO_INSTALL': '0'}):
            result = server.maybe_auto_install_ocr(available=False, start=lambda: called.append(1))
        self.assertEqual(result, {'started': False, 'reason': 'disabled'})
        self.assertEqual(called, [])

    def test_starts_once_then_throttles(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            marker = pathlib.Path(folder) / 'ocr_auto_install.json'
            called = []
            first = server.maybe_auto_install_ocr(available=False, start=lambda: called.append(1), marker=marker)
            self.assertEqual(first, {'started': True, 'reason': 'started'})
            self.assertEqual(len(called), 1)
            self.assertTrue(marker.is_file())
            second = server.maybe_auto_install_ocr(available=False, start=lambda: called.append(1), marker=marker)
            self.assertEqual(second, {'started': False, 'reason': 'throttled'})
            self.assertEqual(len(called), 1)


if __name__ == '__main__':
    unittest.main()
