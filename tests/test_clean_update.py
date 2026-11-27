"""自动更新清装阶段：保留数据、重装程序、旧文件不残留。"""
import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import updater


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class CleanBundleTest(unittest.TestCase):
    def test_clean_reinstall_keeps_data_and_removes_stale_program_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            (root / 'version.py').write_text("VERSION = '3.5.4'\n", encoding='utf-8')
            (root / 'server.py').write_text('old server', encoding='utf-8')
            (root / 'v3').mkdir()
            (root / 'v3' / 'serve.py').write_text('old v3', encoding='utf-8')
            (root / 'stale_module.py').write_text('old only', encoding='utf-8')
            (root / 'data').mkdir()
            (root / 'data' / 'keep.txt').write_text('比赛数据', encoding='utf-8')
            (root / '.env').write_text('PORT=8766', encoding='utf-8')
            (root / 'KPLScrimLab.exe').write_bytes(b'launcher')
            (root / '启动工作台.bat').write_text('start', encoding='utf-8')
            (root / 'app.ico').write_bytes(b'icon')
            (root / 'update_config.json').write_text('{"autoDownload": false}',
                                                     encoding='utf-8')
            (root / 'runtime').mkdir()
            (root / 'runtime' / 'python.exe').write_bytes(b'runtime')
            (root / 'logs').mkdir()
            (root / 'logs' / 'run.log').write_text('log', encoding='utf-8')

            new_files = {
                'version.py': "VERSION = '3.5.5'\n".encode('utf-8'),
                'server.py': b'new server',
                'v3/serve.py': b'new v3',
            }
            entries = [{'path': path, 'sha256': _sha(data), 'size': len(data)}
                       for path, data in new_files.items()]
            bundle = root / 'clean_bundle.zip'
            with zipfile.ZipFile(bundle, 'w', zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('manifest.json', json.dumps(entries))
                for path, data in new_files.items():
                    archive.writestr(f'payload/{path}', data)

            part = root / 'clean_bundle.part01'
            part.write_bytes(bundle.read_bytes())
            marker = {
                'version': '3.5.5',
                'bundle': 'clean_bundle.zip',
                'sha256': _sha(bundle.read_bytes()),
                'parts': [{'path': 'clean_bundle.part01',
                           'sha256': _sha(part.read_bytes())}],
            }
            (root / 'clean_request.json').write_text(json.dumps(marker), encoding='utf-8')

            result = updater.apply_clean_bundle_if_requested(root)

            self.assertTrue(result['ok'])
            self.assertEqual((root / 'version.py').read_text(encoding='utf-8').strip(),
                             "VERSION = '3.5.5'")
            self.assertEqual((root / 'server.py').read_text(encoding='utf-8'), 'new server')
            self.assertEqual((root / 'v3' / 'serve.py').read_text(encoding='utf-8'), 'new v3')
            self.assertFalse((root / 'stale_module.py').exists())
            self.assertEqual((root / 'data' / 'keep.txt').read_text(encoding='utf-8'), '比赛数据')
            self.assertEqual((root / '.env').read_text(encoding='utf-8'), 'PORT=8766')
            self.assertEqual((root / 'KPLScrimLab.exe').read_bytes(), b'launcher')
            self.assertEqual((root / '启动工作台.bat').read_text(encoding='utf-8'), 'start')
            self.assertEqual((root / 'app.ico').read_bytes(), b'icon')
            self.assertEqual((root / 'update_config.json').read_text(encoding='utf-8'),
                             '{"autoDownload": false}')
            self.assertTrue((root / 'runtime' / 'python.exe').exists())
            self.assertTrue((root / 'logs' / 'run.log').exists())
            self.assertFalse((root / 'clean_request.json').exists())
            self.assertFalse((root / 'clean_bundle.zip').exists())
            self.assertFalse(part.exists())

    def test_failed_clean_rolls_back_nested_program_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'version.py').write_text("VERSION = '3.5.4'\n", encoding='utf-8')
            (root / 'v3').mkdir()
            (root / 'v3' / 'serve.py').write_text('old nested', encoding='utf-8')
            (root / 'data').mkdir()
            (root / 'data' / 'keep.txt').write_text('keep', encoding='utf-8')

            bundle = root / 'clean_bundle.zip'
            entries = [{'path': 'version.py', 'sha256': _sha(b'bad'), 'size': 3}]
            with zipfile.ZipFile(bundle, 'w') as archive:
                archive.writestr('manifest.json', json.dumps(entries))
                archive.writestr('payload/version.py', b'bad')
            marker = {'version': '3.5.5', 'bundle': 'clean_bundle.zip',
                      'sha256': _sha(bundle.read_bytes())}
            (root / 'clean_request.json').write_text(json.dumps(marker), encoding='utf-8')

            with self.assertRaises(ValueError):
                updater.apply_clean_bundle_if_requested(root)

            self.assertEqual((root / 'version.py').read_text(encoding='utf-8').strip(),
                             "VERSION = '3.5.4'")
            self.assertEqual((root / 'v3' / 'serve.py').read_text(encoding='utf-8'),
                             'old nested')
            self.assertEqual((root / 'data' / 'keep.txt').read_text(encoding='utf-8'), 'keep')

    def test_validation_failure_is_recorded_in_last_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'version.py').write_text("VERSION = '3.5.4'\n", encoding='utf-8')
            (root / 'clean_bundle.part01').write_bytes(b'bad bundle')
            marker = {'version': '3.5.5', 'bundle': 'clean_bundle.zip',
                      'parts': [{'path': 'clean_bundle.part01',
                                 'sha256': '0' * 64}]}
            (root / 'clean_request.json').write_text(json.dumps(marker), encoding='utf-8')

            with self.assertRaises(ValueError):
                updater.apply_clean_bundle_if_requested(root)

            result = json.loads((root / 'data' / 'update' / 'last_result.json').read_text(
                encoding='utf-8'))
            self.assertFalse(result['ok'])
            self.assertIn('清装失败', result['message'])
            self.assertTrue((root / 'clean_request.json').exists(),
                            '标记要保留，方便修复后重试')

    def test_stale_marker_never_downgrades_installed_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'version.py').write_text("VERSION = '3.5.5'\n", encoding='utf-8')
            (root / 'clean_request.json').write_text(json.dumps({
                'version': '3.5.4', 'bundle': 'clean_bundle.zip'}), encoding='utf-8')
            part = root / 'clean_bundle.part01'
            part.write_bytes(b'stale')

            result = updater.apply_clean_bundle_if_requested(root)

            self.assertTrue(result['skipped'])
            self.assertIn('过期', result['message'])
            self.assertFalse((root / 'clean_request.json').exists())
            self.assertFalse(part.exists())
            self.assertEqual(updater.read_installed_version(root), '3.5.5')

    def test_rollback_removes_files_extracted_before_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'version.py').write_text("VERSION = '3.5.4'\n", encoding='utf-8')
            (root / 'v3').mkdir()
            (root / 'v3' / 'serve.py').write_text('old', encoding='utf-8')
            bundle = root / 'clean_bundle.zip'
            new_files = {'version.py': "VERSION = '3.5.5'\n".encode(),
                         'brand_new.py': b'new'}
            entries = [{'path': path, 'sha256': _sha(data), 'size': len(data)}
                       for path, data in new_files.items()]
            with zipfile.ZipFile(bundle, 'w') as archive:
                archive.writestr('manifest.json', json.dumps(entries))
                for path, data in new_files.items():
                    archive.writestr(f'payload/{path}', data)
            (root / 'clean_request.json').write_text(json.dumps({
                'version': '3.5.5', 'bundle': 'clean_bundle.zip',
                'sha256': _sha(bundle.read_bytes())}), encoding='utf-8')

            real = updater._extract_from_zip
            with mock.patch.object(updater, '_extract_from_zip',
                                   side_effect=[None, OSError('disk full')]):
                with self.assertRaises(ValueError):
                    updater.apply_clean_bundle_if_requested(root)

            self.assertFalse((root / 'brand_new.py').exists())
            self.assertEqual((root / 'version.py').read_text(encoding='utf-8').strip(),
                             "VERSION = '3.5.4'")
            self.assertEqual((root / 'v3' / 'serve.py').read_text(encoding='utf-8'), 'old')

    def test_no_marker_is_a_noop(self):
        with tempfile.TemporaryDirectory() as directory:
            result = updater.apply_clean_bundle_if_requested(Path(directory))
            self.assertTrue(result['skipped'])


if __name__ == '__main__':
    unittest.main()
