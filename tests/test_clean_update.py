"""自动更新清装阶段：保留数据、重装程序、旧文件不残留。"""
import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

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

    def test_no_marker_is_a_noop(self):
        with tempfile.TemporaryDirectory() as directory:
            result = updater.apply_clean_bundle_if_requested(Path(directory))
            self.assertTrue(result['skipped'])


if __name__ == '__main__':
    unittest.main()
