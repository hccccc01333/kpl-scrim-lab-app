"""数据根可重定向：KPL_DATA_DIR 必须把所有默认落盘位置切走。

演示实例、截图实例和测试都靠这一条保证不碰真实教练的数据。
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PROBE = r"""
import os, sys
sys.path.insert(0, {root!r})
import paths, server, camp_replay, hero_catalog, mimo_ocr, recording_store
import replay_timeline_build, update_client

root = str(paths.DATA_DIR)
assert root.lower().startswith({expected!r}.lower()), root

checks = {{
    'server.DB_PATH': server.DB_PATH,
    'server.MATCHES_DIR': server.MATCHES_DIR,
    'server.IMPORTS_DIR': server.IMPORTS_DIR,
    'server.CAMP_CONFIG_PATH': server.CAMP_CONFIG_PATH,
    'camp_replay.STORE': camp_replay.STORE,
    'hero_catalog.CACHE_PATH': hero_catalog.CACHE_PATH,
    'mimo_ocr.CACHE_ROOT': mimo_ocr.CACHE_ROOT,
    'recording_store.LIBRARY': recording_store.LIBRARY,
    'replay_timeline_build.DEFAULT_DIR': replay_timeline_build.DEFAULT_DIR,
    'update_client.cache_file': update_client.cache_file(paths.ROOT),
}}
bad = [(name, str(value)) for name, value in checks.items()
       if not str(value).lower().startswith({expected!r}.lower())]
assert not bad, bad
print('ok')
"""


def run_probe(env_overrides: dict, expected: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    # 其它用例可能改过这些覆盖变量；本例只验证 KPL_DATA_DIR 对默认路径的重定向。
    for key in ('TRAINING_DB', 'ANALYSIS_MATCHES', 'ANALYSIS_IMPORTS', 'ANALYSIS_OFFICIAL',
                'ANALYSIS_BUILDS', 'CAMP_CONFIG_FILE', 'CAMP_REPLAY_DIR',
                'KPL_RECORDINGS', 'MIMO_OCR_CACHE', 'HERO_LIST_FILE'):
        env.pop(key, None)
    env.update(env_overrides)
    env['PYTHONUTF8'] = '1'
    code = PROBE.format(root=str(ROOT), expected=expected)
    return subprocess.run([sys.executable, '-c', code], cwd=str(ROOT), env=env,
                          capture_output=True, text=True, encoding='utf-8',
                          errors='replace', timeout=180)


class DataRootTests(unittest.TestCase):
    def test_env_redirects_every_default_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_probe({'KPL_DATA_DIR': tmp}, expected=tmp)
            self.assertEqual(result.returncode, 0,
                             result.stderr or result.stdout)
            self.assertIn('ok', result.stdout)

    def test_default_is_project_data_dir(self):
        env = {key: value for key, value in os.environ.items()
               if key != 'KPL_DATA_DIR'}
        env['PYTHONUTF8'] = '1'
        code = (f'import sys; sys.path.insert(0, {str(ROOT)!r}); import paths; '
                f'print(paths.DATA_DIR)')
        result = subprocess.run([sys.executable, '-c', code], cwd=str(ROOT),
                                env=env, capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(Path(result.stdout.strip()),
                         (ROOT / 'data').resolve())

    def test_env_is_read_at_import_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = os.environ.copy()
            env['KPL_DATA_DIR'] = tmp
            env['PYTHONUTF8'] = '1'
            code = (f'import sys; sys.path.insert(0, {str(ROOT)!r}); import paths; '
                    f'print(paths.data_path("camp_details", "1.json"))')
            result = subprocess.run([sys.executable, '-c', code], cwd=str(ROOT),
                                    env=env, capture_output=True, text=True,
                                    encoding='utf-8', errors='replace', timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(result.stdout.strip().lower()
                            .startswith(str(Path(tmp)).lower()))


if __name__ == '__main__':
    unittest.main()
