import hashlib
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import update_api  # noqa: E402
import update_client  # noqa: E402
import updater  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def make_patch(directory: Path, version: str, files: dict[str, str],
               remove: list[str] | None = None,
               manifest_paths: list[str] | None = None,
               min_version: str | None = None) -> Path:
    entries = []
    for path, text in files.items():
        digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
        entries.append({'path': path, 'sha256': digest, 'size': len(text.encode('utf-8'))})
    if manifest_paths is not None:
        entries = [{'path': path, 'sha256': '0' * 64, 'size': 0}
                   for path in manifest_paths]
    manifest = {
        'schema': 1,
        'version': version,
        'notes': ['测试更新'],
        'patch': {'url': 'patch.zip', 'files': entries, 'remove': remove or []},
    }
    if min_version:
        manifest['minVersion'] = min_version
    archive = directory / f'patch-{version}.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as handle:
        handle.writestr('update.json', json.dumps(manifest, ensure_ascii=False))
        for path, text in files.items():
            handle.writestr(f'payload/{path}', text)
    return archive


class VersionTests(unittest.TestCase):
    def test_compare(self):
        self.assertLess(update_client.compare_versions('1.0.0', '1.0.1'), 0)
        self.assertEqual(update_client.compare_versions('v1.0.1', '1.0.1'), 0)
        self.assertGreater(update_client.compare_versions('1.0.0', '1.0.0-beta.2'), 0)

    def test_invalid(self):
        with self.assertRaises(ValueError):
            update_client.parse_version('latest')


class ManifestTests(unittest.TestCase):
    def test_normalize(self):
        manifest = update_client.normalize_manifest({
            'version': '1.0.1',
            'notes': ['a', 'b'],
            'patch': {
                'url': 'patch.zip',
                'files': [{'path': 'server.py', 'sha256': 'a' * 64, 'size': 1}],
            },
        })
        self.assertEqual(manifest['version'], '1.0.1')
        self.assertEqual(manifest['notes'], ['a', 'b'])

    def test_reject_unsafe_path(self):
        with self.assertRaises(ValueError):
            update_client.normalize_manifest({
                'version': '1.0.1',
                'patch': {
                    'url': 'patch.zip',
                    'files': [{'path': '../evil.py', 'sha256': 'a' * 64, 'size': 1}],
                },
            })

    def test_reject_bad_sha(self):
        with self.assertRaises(ValueError):
            update_client.normalize_manifest({
                'version': '1.0.1',
                'patch': {
                    'url': 'patch.zip',
                    'files': [{'path': 'server.py', 'sha256': 'nope', 'size': 1}],
                },
            })


class StageApplyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.app = self.root / 'app'
        write(self.app / 'version.py', "VERSION = '1.0.0'\n")
        write(self.app / 'server.py', 'old server\n')
        write(self.app / 'web' / 'main.js', 'old script\n')
        write(self.app / 'obsolete.py', 'remove me\n')

    def tearDown(self):
        self.temp.cleanup()

    def test_stage_apply_and_restore(self):
        archive = make_patch(
            self.root, '1.0.1',
            {
                'version.py': "VERSION = '1.0.1'\n",
                'server.py': 'new server\n',
                'web/new.js': 'new script\n',
            },
            remove=['obsolete.py'])
        pending = updater.stage_patch(archive, self.app)
        self.assertEqual(pending['version'], '1.0.1')
        self.assertTrue((self.app / 'data' / 'update' / 'pending.json').is_file())

        result = updater.apply_pending(self.app)
        self.assertTrue(result['ok'])
        self.assertEqual(updater.read_installed_version(self.app), '1.0.1')
        self.assertEqual((self.app / 'server.py').read_text(encoding='utf-8'), 'new server\n')
        self.assertTrue((self.app / 'web' / 'new.js').is_file())
        self.assertFalse((self.app / 'obsolete.py').exists())
        self.assertIsNone(updater.read_pending(self.app))

        updater.restore_backup(Path(result['backupDir']), self.app)
        self.assertEqual(updater.read_installed_version(self.app), '1.0.0')
        self.assertEqual((self.app / 'server.py').read_text(encoding='utf-8'), 'old server\n')
        self.assertTrue((self.app / 'obsolete.py').is_file())
        self.assertFalse((self.app / 'web' / 'new.js').exists())

    def test_apply_with_external_data_dir(self):
        """KPL_DATA_DIR 指到应用目录外时，应用更新不能因相对路径转换而崩掉。"""
        external = self.root / 'external-data'
        archive = make_patch(self.root, '1.0.1', {
            'version.py': "VERSION = '1.0.1'\n",
            'server.py': 'new server\n',
        })
        with mock.patch.dict(os.environ, {'KPL_DATA_DIR': str(external)}):
            pending = updater.stage_patch(archive, self.app)
            self.assertEqual(pending['version'], '1.0.1')
            # 暂存/待应用清单固定在应用目录内；只有备份目录跟随 KPL_DATA_DIR。
            self.assertTrue((self.app / 'data' / 'update' / 'pending.json').is_file())
            result = updater.apply_pending(self.app)
        self.assertTrue(result['ok'])
        self.assertEqual(updater.read_installed_version(self.app), '1.0.1')
        self.assertEqual((self.app / 'server.py').read_text(encoding='utf-8'), 'new server\n')
        backup = Path(result['backupDir'])
        self.assertTrue(backup.is_dir())
        self.assertEqual(backup.parent, external / 'backups')

    def test_tools_runtime_modules_are_updatable(self):
        """tools/ 下随包发布的运行期模块必须可被补丁更新（v1.4.0 曾整体禁写）。"""
        from update_client import normalize_rel_path
        self.assertEqual(normalize_rel_path('tools/camp_sync.py'), 'tools/camp_sync.py')
        with self.assertRaises(ValueError):
            normalize_rel_path('tools/ffmpeg/bin/ffmpeg.exe')
        with self.assertRaises(ValueError):
            normalize_rel_path('data/training.sqlite3')

    def test_reject_patch_below_min_version(self):
        """增量包只含基线之后的差分：低于 minVersion 的安装必须拒装，走完整包。"""
        archive = make_patch(self.root, '1.0.1', {
            'version.py': "VERSION = '1.0.1'\n",
            'server.py': 'new\n',
        }, min_version='1.4.0')
        with self.assertRaises(ValueError) as caught:
            updater.stage_patch(archive, self.app)
        self.assertIn('完整包', str(caught.exception))
        self.assertIsNone(updater.read_pending(self.app))

    def test_accept_patch_at_min_version(self):
        write(self.app / 'version.py', "VERSION = '1.4.0'\n")
        archive = make_patch(self.root, '1.4.1', {
            'version.py': "VERSION = '1.4.1'\n",
            'server.py': 'new\n',
        }, min_version='1.4.0')
        pending = updater.stage_patch(archive, self.app)
        self.assertEqual(pending['version'], '1.4.1')

    def test_reject_downgrade(self):
        archive = make_patch(self.root, '0.9.9', {
            'version.py': "VERSION = '0.9.9'\n",
            'server.py': 'old\n',
        })
        with self.assertRaises(ValueError):
            updater.stage_patch(archive, self.app)

    def test_reject_traversal(self):
        archive = make_patch(self.root, '1.0.1', {
            'version.py': "VERSION = '1.0.1'\n",
        }, manifest_paths=['../evil.py'])
        with self.assertRaises(ValueError):
            updater.stage_patch(archive, self.app)

    def test_reject_missing_version(self):
        archive = make_patch(self.root, '1.0.1', {
            'server.py': 'new\n',
        })
        with self.assertRaises(ValueError):
            updater.stage_patch(archive, self.app)

    def test_hash_mismatch(self):
        archive = make_patch(self.root, '1.0.1', {
            'version.py': "VERSION = '1.0.1'\n",
        })
        with zipfile.ZipFile(archive) as handle:
            data = handle.read('update.json')
        manifest = json.loads(data)
        manifest['patch']['files'][0]['sha256'] = 'f' * 64
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as handle:
            handle.writestr('update.json', json.dumps(manifest))
            handle.writestr('payload/version.py', "VERSION = '1.0.1'\n")
        with self.assertRaises(ValueError):
            updater.stage_patch(archive, self.app)


class CheckTests(unittest.TestCase):
    def test_manifest_urls_from_config(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write(root / 'update_config.json',
                  json.dumps({'manifestUrls': ['https://example.com/update.json']}))
            self.assertEqual(update_client.manifest_urls(root),
                             ['https://example.com/update.json'])
            self.assertEqual(
                update_client.manifest_urls(root, {'UPDATE_MANIFEST_URLS': 'https://env/update.json'}),
                ['https://env/update.json'])

    def test_check_uses_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = update_client.normalize_manifest({
                'version': '1.0.2',
                'notes': ['fix'],
                'patch': {
                    'url': 'patch.zip',
                    'files': [{'path': 'server.py', 'sha256': 'a' * 64, 'size': 2}],
                },
            })
            with mock.patch.object(update_client, 'fetch_manifest',
                                   return_value=(manifest, 'https://example.com/update.json')):
                result = update_client.check_for_update(root, '1.0.0', force=True)
            self.assertTrue(result['updateAvailable'])
            self.assertEqual(result['latestVersion'], '1.0.2')
            self.assertTrue((root / 'data' / 'update_cache.json').is_file())


def manifest_json(version: str) -> str:
    return json.dumps({
        'version': version,
        'notes': [version],
        'patch': {
            'url': f'patch-{version}.zip',
            'files': [{'path': 'server.py', 'sha256': 'a' * 64, 'size': 1}],
        },
    }, ensure_ascii=False)


class MirrorTests(unittest.TestCase):
    def test_prefers_newest_mirror(self):
        """Gitee 停在旧版、GitHub 已发新版时，不能拿先返回的旧清单当结果。"""
        payloads = {
            'https://old.example/update.json': manifest_json('1.0.1'),
            'https://new.example/update.json': manifest_json('1.0.3'),
        }

        def fake_read(url, limit, timeout, allow_http=None):
            if url == 'https://dead.example/update.json':
                raise OSError('connection reset')
            return payloads[url].encode('utf-8')

        with mock.patch.object(update_client, '_read_url', side_effect=fake_read):
            manifest, source = update_client.fetch_manifest(
                list(payloads) + ['https://dead.example/update.json'], timeout=0.1)
        self.assertEqual(manifest['version'], '1.0.3')
        self.assertEqual(source, 'https://new.example/update.json')

    def test_all_mirrors_fail_reports_every_url(self):
        with mock.patch.object(update_client, '_read_url',
                               side_effect=OSError('boom')):
            with self.assertRaises(update_client.UpdateError) as caught:
                update_client.fetch_manifest(['https://a.example', 'https://b.example'])
        message = str(caught.exception)
        self.assertIn('https://a.example', message)
        self.assertIn('https://b.example', message)

    def test_details_carry_per_mirror_status(self):
        payloads = {'https://ok.example/update.json': manifest_json('1.0.2')}

        def fake_read(url, limit, timeout, allow_http=None):
            if url not in payloads:
                raise OSError('blocked')
            return payloads[url].encode('utf-8')

        details = []
        with mock.patch.object(update_client, '_read_url', side_effect=fake_read):
            update_client.fetch_manifest(
                ['https://ok.example/update.json', 'https://bad.example/update.json'],
                timeout=0.1, details=details)
        self.assertEqual(len(details), 2)
        self.assertTrue(details[0]['ok'])
        self.assertFalse(details[1]['ok'])
        self.assertIn('blocked', details[1]['error'])


class SettingsTests(unittest.TestCase):
    def test_defaults(self):
        with tempfile.TemporaryDirectory() as temp:
            settings = update_client.load_settings(Path(temp))
        self.assertTrue(settings['autoDownload'])
        self.assertEqual(settings['autoCheckMinutes'], 30)

    def test_config_overrides_and_clamps(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write(root / 'update_config.json',
                  json.dumps({'autoDownload': False, 'autoCheckMinutes': 1}))
            settings = update_client.load_settings(root, {})
        self.assertFalse(settings['autoDownload'])
        self.assertEqual(settings['autoCheckMinutes'], 5)

    def test_env_can_disable_auto_download(self):
        with tempfile.TemporaryDirectory() as temp:
            settings = update_client.load_settings(
                Path(temp), {'UPDATE_AUTO_DOWNLOAD': '0'})
        self.assertFalse(settings['autoDownload'])

    def test_release_fields_survive_normalization(self):
        manifest = update_client.normalize_manifest({
            'version': '1.0.2',
            'releaseDate': '2026-11-13',
            'releaseName': '测试版',
            'patch': {
                'url': 'patch.zip',
                'files': [{'path': 'version.py', 'sha256': 'a' * 64, 'size': 1}],
            },
        })
        self.assertEqual(manifest['releaseDate'], '2026-11-13')
        self.assertEqual(manifest['releaseName'], '测试版')


class UpdateApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'app'
        write(self.root / 'version.py', "VERSION = '1.0.0'\n")
        self.app = FastAPI()
        self.app.include_router(update_api.create_update_router(self.root, '1.0.0'))
        self.client = TestClient(self.app)

    def tearDown(self):
        self.temp.cleanup()

    def stage(self, version='1.0.1'):
        archive = make_patch(Path(self.temp.name), version, {
            'version.py': f"VERSION = '{version}'\n",
            'server.py': 'new server\n',
        })
        return updater.stage_patch(archive, self.root)

    def test_prepare_reuses_staged_patch_without_network(self):
        self.stage()
        with mock.patch.object(update_client, 'check_for_update',
                               side_effect=AssertionError('不应再查网络')):
            response = self.client.post('/api/update/prepare',
                                        json={'version': '1.0.1'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['pending']['version'], '1.0.1')

    def test_prepare_does_not_reuse_mismatched_pending(self):
        self.stage()
        with mock.patch.object(update_client, 'check_for_update',
                               side_effect=RuntimeError('network down')) as check:
            response = self.client.post('/api/update/prepare',
                                        json={'version': '1.0.2'})
        self.assertEqual(response.status_code, 400, response.text)
        check.assert_called_once()
        self.assertIn('network down', response.json()['detail'])

    def test_apply_reuses_staged_patch_and_requests_restart(self):
        self.stage()
        with mock.patch.object(updater, 'spawn_restart') as spawn, \
                mock.patch.object(update_api, '_schedule_exit') as schedule_exit:
            response = self.client.post('/api/update/apply',
                                        json={'version': '1.0.1'})
        self.assertEqual(response.status_code, 200, response.text)
        spawn.assert_called_once()
        schedule_exit.assert_called_once()

    def test_check_hides_broken_pending(self):
        pending = self.stage()
        staged = self.root / pending['stagedDir']
        for item in staged.joinpath('payload').rglob('*'):
            if item.is_file():
                item.unlink()
        result = {
            'ok': True, 'currentVersion': '1.0.0', 'latestVersion': '1.0.0',
            'updateAvailable': False, 'blocked': False, 'notes': [],
            'source': 'https://example.com/update.json', 'stale': False,
        }
        with mock.patch.object(update_client, 'check_for_update',
                               return_value=result):
            response = self.client.get('/api/update/check?force=1')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()['pending'])


if __name__ == '__main__':
    unittest.main()
