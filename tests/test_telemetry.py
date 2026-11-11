"""匿名使用统计（telemetry.py）与清单 stats 字段的离线单测。

不联网：所有 HTTP 都 mock ``telemetry.urlopen``；数据目录用 tempfile，并清空
``KPL_DATA_DIR`` / ``KPL_TELEMETRY``，避免误读真实 data/ 或本机环境变量。
"""
import json
import os
import platform
import re
import sys
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import telemetry  # noqa: E402
import update_client  # noqa: E402

INSTALL_ID_RE = re.compile(r'^[0-9a-f]{32}$')


class FakeResponse:
    """足够模拟 ``with urlopen(...) as response`` 的最小对象。"""

    def __init__(self, status: int = 200, body: bytes = b'{"ok": true}'):
        self.status = status
        self._body = body

    def read(self, size: int = -1) -> bytes:
        return self._body if size is None or size < 0 else self._body[:size]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class TelemetryTestCase(unittest.TestCase):
    """公共夹具：临时 data 目录 + 干净环境变量 + 重置心跳线程。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self._env = mock.patch.dict(
            os.environ, {'KPL_DATA_DIR': '', 'KPL_TELEMETRY': ''}, clear=False)
        self._env.start()
        telemetry._thread = None

    def tearDown(self):
        telemetry._thread = None
        self._env.stop()
        self.temp.cleanup()

    @property
    def usage(self) -> Path:
        return self.root / 'data' / 'usage'

    def write_state(self, state: dict) -> None:
        self.usage.mkdir(parents=True, exist_ok=True)
        (self.usage / 'last_ping.json').write_text(
            json.dumps(state), encoding='utf-8')

    def read_state(self) -> dict:
        return json.loads(
            (self.usage / 'last_ping.json').read_text(encoding='utf-8'))

    def stats_result(self, url: str = 'https://stats.example.com/api/ping',
                     period: int | None = 20) -> dict:
        stats = {'url': url}
        if period is not None:
            stats['periodHours'] = period
        return {'ok': True, 'stats': stats}


class IdentityTests(TelemetryTestCase):
    def test_install_id_created_and_persisted(self):
        first = telemetry.load_install_id(self.root)
        self.assertRegex(first, INSTALL_ID_RE)
        path = self.usage / 'install_id.txt'
        self.assertTrue(path.is_file())
        self.assertEqual(path.read_text(encoding='utf-8').strip(), first)
        self.assertEqual(telemetry.load_install_id(self.root), first)

    def test_install_id_corrupted_is_regenerated(self):
        self.usage.mkdir(parents=True, exist_ok=True)
        (self.usage / 'install_id.txt').write_text('not-a-uuid', encoding='utf-8')
        install_id = telemetry.load_install_id(self.root)
        self.assertRegex(install_id, INSTALL_ID_RE)
        self.assertEqual(
            (self.usage / 'install_id.txt').read_text(encoding='utf-8').strip(),
            install_id)

    def test_first_seen_created_and_persisted(self):
        first = telemetry.load_first_seen(self.root)
        datetime.fromisoformat(first)  # 必须是合法 ISO 时间
        self.assertTrue((self.usage / 'first_seen.txt').is_file())
        self.assertEqual(telemetry.load_first_seen(self.root), first)


class OptOutTests(TelemetryTestCase):
    def test_env_values_disable(self):
        for value in ('0', 'false', 'FALSE', 'off', 'no'):
            with self.subTest(value=value):
                self.assertTrue(
                    telemetry.is_disabled(self.root, {'KPL_TELEMETRY': value}))
        for value in ('1', 'true', 'yes', ''):
            with self.subTest(value=value):
                self.assertFalse(
                    telemetry.is_disabled(self.root, {'KPL_TELEMETRY': value}))

    def test_optout_file_disables(self):
        self.usage.mkdir(parents=True, exist_ok=True)
        (self.usage / 'optout').write_text('', encoding='utf-8')
        self.assertTrue(telemetry.is_disabled(self.root, {}))

    def test_ping_is_skipped_when_disabled(self):
        with mock.patch.object(telemetry, 'post_ping') as post:
            result = telemetry.ping_once(
                self.root, '1.6.3', now=1000.0,
                env={'KPL_TELEMETRY': '0'}, update_result=self.stats_result())
        self.assertFalse(result['ok'])
        self.assertEqual(result['reason'], 'disabled')
        post.assert_not_called()
        # 停用状态下连安装 ID 都不应该创建。
        self.assertFalse((self.usage / 'install_id.txt').exists())

    def test_maybe_ping_returns_none_when_disabled(self):
        with mock.patch.dict(os.environ, {'KPL_TELEMETRY': '0'}):
            self.assertIsNone(telemetry.maybe_ping(self.root, '1.6.3', delay=0))


class ThrottleTests(TelemetryTestCase):
    def test_no_state_allows_ping(self):
        self.assertTrue(telemetry.should_ping(self.root, now=1000.0))

    def test_success_throttled_for_period(self):
        self.write_state({'lastSuccess': 1000.0})
        self.assertFalse(telemetry.should_ping(self.root, now=1000.0 + 3600))
        self.assertFalse(telemetry.should_ping(
            self.root, now=1000.0 + 20 * 3600 - 1, period_hours=20))
        self.assertTrue(telemetry.should_ping(
            self.root, now=1000.0 + 20 * 3600 + 1, period_hours=20))
        # periodHours 覆盖默认 20 小时。
        self.assertTrue(telemetry.should_ping(
            self.root, now=1000.0 + 2 * 3600, period_hours=1))

    def test_failure_retried_after_one_hour(self):
        self.write_state({'lastAttempt': 1000.0, 'lastError': 'offline'})
        self.assertFalse(telemetry.should_ping(self.root, now=1000.0 + 1800))
        self.assertTrue(telemetry.should_ping(self.root, now=1000.0 + 3600 + 1))

    def test_corrupt_state_is_treated_as_empty(self):
        self.usage.mkdir(parents=True, exist_ok=True)
        (self.usage / 'last_ping.json').write_text('{not json', encoding='utf-8')
        self.assertTrue(telemetry.should_ping(self.root, now=1000.0))

    def test_period_from_manifest_controls_throttle(self):
        now = 1_700_000_000.0
        self.write_state({'lastSuccess': now - 7200})
        with mock.patch.object(telemetry, 'urlopen', return_value=FakeResponse()) as opened:
            allowed = telemetry.ping_once(
                self.root, '1.6.3', now=now,
                update_result=self.stats_result(period=1))
            blocked = telemetry.ping_once(
                self.root, '1.6.3', now=now,
                update_result=self.stats_result(period=20))
        self.assertTrue(allowed['ok'])
        self.assertEqual(blocked['reason'], 'throttled')
        self.assertEqual(opened.call_count, 1)


class PingTests(TelemetryTestCase):
    def test_no_stats_does_not_send(self):
        cases = [
            {'ok': False, 'reason': '离线'},
            {'ok': True},
            {'ok': True, 'stats': None},
            {'ok': True, 'stats': {'url': ''}},
            {'ok': True, 'stats': {'url': 'ftp://stats.example.com/ping'}},
            {'ok': True, 'manifest': {}},
        ]
        for result in cases:
            with self.subTest(result=result):
                with mock.patch.object(telemetry, 'post_ping') as post:
                    outcome = telemetry.ping_once(
                        self.root, '1.6.3', now=1000.0, update_result=result)
                self.assertFalse(outcome['ok'])
                self.assertEqual(outcome['reason'], 'no-stats')
                post.assert_not_called()
        self.assertFalse((self.usage / 'last_ping.json').exists())

    def test_success_payload_fields(self):
        now = 1_700_000_000.0
        with mock.patch.object(telemetry, 'urlopen',
                               return_value=FakeResponse()) as opened:
            result = telemetry.ping_once(
                self.root, '1.6.3', now=now, update_result=self.stats_result())
        self.assertTrue(result['ok'])
        self.assertEqual(opened.call_count, 1)
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, 'https://stats.example.com/api/ping')
        self.assertEqual(request.get_method(), 'POST')
        self.assertEqual(opened.call_args.kwargs.get('timeout'), 6.0)
        payload = json.loads(request.data.decode('utf-8'))
        # 字段集合固定：多一个都可能泄露隐私，少一个服务端统计不了。
        self.assertEqual(set(payload), {
            'schema', 'app', 'installId', 'version', 'os', 'osVersion',
            'arch', 'startedAt', 'firstSeen',
        })
        self.assertEqual(payload['schema'], 1)
        self.assertEqual(payload['app'], 'kpl-scrim-lab')
        self.assertEqual(payload['version'], '1.6.3')
        self.assertEqual(payload['installId'],
                         telemetry.load_install_id(self.root))
        self.assertEqual(payload['os'], platform.system())
        self.assertEqual(payload['osVersion'], platform.release())
        self.assertEqual(payload['arch'], platform.machine())
        datetime.fromisoformat(payload['startedAt'])
        datetime.fromisoformat(payload['firstSeen'])
        state = self.read_state()
        self.assertEqual(state['lastSuccess'], now)
        self.assertEqual(state['lastAttempt'], now)

    def test_second_ping_within_period_is_throttled(self):
        now = 1_700_000_000.0
        with mock.patch.object(telemetry, 'urlopen',
                               return_value=FakeResponse()) as opened:
            self.assertTrue(telemetry.ping_once(
                self.root, '1.6.3', now=now,
                update_result=self.stats_result())['ok'])
            outcome = telemetry.ping_once(
                self.root, '1.6.3', now=now + 60,
                update_result=self.stats_result())
        self.assertEqual(outcome['reason'], 'throttled')
        self.assertEqual(opened.call_count, 1)

    def test_uses_check_for_update_when_result_not_given(self):
        now = 1_700_000_000.0
        with mock.patch.object(telemetry.update_client, 'check_for_update',
                               return_value=self.stats_result()) as check, \
                mock.patch.object(telemetry, 'urlopen',
                                  return_value=FakeResponse()) as opened:
            result = telemetry.ping_once(self.root, '1.6.3', now=now)
        self.assertTrue(result['ok'])
        check.assert_called_once_with(self.root, '1.6.3')
        self.assertEqual(opened.call_count, 1)

    def test_stats_can_come_from_manifest_block(self):
        now = 1_700_000_000.0
        update_result = {'ok': True,
                         'manifest': {'stats': {'url': 'https://m.example.com/api/ping'}}}
        with mock.patch.object(telemetry, 'urlopen',
                               return_value=FakeResponse()) as opened:
            result = telemetry.ping_once(
                self.root, '1.6.3', now=now, update_result=update_result)
        self.assertTrue(result['ok'])
        self.assertEqual(opened.call_args.args[0].full_url,
                         'https://m.example.com/api/ping')

    def test_network_failure_is_silent_and_recorded(self):
        from urllib.error import URLError
        now = 1_700_000_000.0
        with mock.patch.object(telemetry, 'urlopen',
                               side_effect=URLError('offline')) as opened:
            outcome = telemetry.ping_once(
                self.root, '1.6.3', now=now, update_result=self.stats_result())
        self.assertEqual(outcome['reason'], 'error')
        self.assertEqual(opened.call_count, 1)
        state = self.read_state()
        self.assertEqual(state['lastAttempt'], now)
        self.assertNotIn('lastSuccess', state)
        self.assertIn('lastError', state)
        # 失败后 1 小时内不重试，但超过 1 小时允许。
        self.assertFalse(telemetry.should_ping(self.root, now=now + 1800))
        self.assertTrue(telemetry.should_ping(self.root, now=now + 3601))

    def test_invalid_stats_url_never_sends(self):
        with mock.patch.object(telemetry, 'post_ping') as post:
            outcome = telemetry.ping_once(
                self.root, '1.6.3', now=1000.0,
                update_result=self.stats_result(url='not-a-url'))
        self.assertEqual(outcome['reason'], 'no-stats')
        post.assert_not_called()

    def test_build_payload_is_anonymous(self):
        payload = telemetry.build_payload(self.root, '1.6.3', now=1_700_000_000.0)
        forbidden = ('hostname', 'user', 'path', 'team', 'match', 'ip')
        for key in payload:
            self.assertFalse(any(word in key.lower() for word in forbidden), key)
        # osVersion 只可能是内核版本号，不会带用户名/路径。
        self.assertNotIn(os.sep, payload['osVersion'])

    def test_maybe_ping_starts_single_daemon_thread(self):
        started = threading.Event()
        release = threading.Event()
        calls = []

        def fake_worker(root, version, delay):
            calls.append((root, version, delay))
            started.set()
            release.wait(5)

        with mock.patch.object(telemetry, '_ping_worker', fake_worker):
            first = telemetry.maybe_ping(self.root, '1.6.3', delay=0)
            self.assertTrue(started.wait(2))
            self.assertIsNotNone(first)
            self.assertTrue(first.daemon)
            second = telemetry.maybe_ping(self.root, '1.6.3', delay=0)
            release.set()
            first.join(2)
        self.assertIsNone(second)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], '1.6.3')


class ManifestStatsTests(unittest.TestCase):
    def base_manifest(self, **extra):
        manifest = {'version': '1.6.3', 'notes': ['统计']}
        manifest.update(extra)
        return manifest

    def test_normalize_stats_default_period(self):
        manifest = update_client.normalize_manifest(self.base_manifest(
            stats={'url': 'https://stats.example.com/api/ping'}))
        self.assertEqual(manifest['stats'],
                         {'url': 'https://stats.example.com/api/ping',
                          'periodHours': 20})

    def test_normalize_stats_custom_period(self):
        for period in (1, 24, 168):
            with self.subTest(period=period):
                manifest = update_client.normalize_manifest(self.base_manifest(
                    stats={'url': 'https://stats.example.com/ping',
                           'periodHours': period}))
                self.assertEqual(manifest['stats']['periodHours'], period)

    def test_manifest_without_stats_is_unchanged(self):
        manifest = update_client.normalize_manifest(self.base_manifest())
        self.assertNotIn('stats', manifest)

    def test_reject_invalid_stats(self):
        cases = [
            'https://stats.example.com',
            {'url': ''},
            {'url': 'ftp://stats.example.com/ping'},
            {'url': '/api/ping'},
            {'url': 'https://stats.example.com/ping', 'periodHours': 0},
            {'url': 'https://stats.example.com/ping', 'periodHours': 169},
            {'url': 'https://stats.example.com/ping', 'periodHours': '20'},
            {'url': 'https://stats.example.com/ping', 'periodHours': 20.0},
            {'url': 'https://stats.example.com/ping', 'periodHours': True},
            {'url': 'https://' + 'a' * 600 + '.com/ping'},
        ]
        for stats in cases:
            with self.subTest(stats=stats):
                with self.assertRaises(ValueError):
                    update_client.normalize_manifest(self.base_manifest(stats=stats))

    def test_check_for_update_exposes_stats(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = update_client.normalize_manifest(self.base_manifest(
                stats={'url': 'https://stats.example.com/api/ping'}))
            with mock.patch.object(update_client, 'fetch_manifest',
                                   return_value=(manifest, 'https://example.com/update.json')):
                result = update_client.check_for_update(root, '1.6.2', force=True)
            self.assertTrue(result['ok'])
            self.assertEqual(result['stats']['url'],
                             'https://stats.example.com/api/ping')
            # 缓存回读也要保留 stats，否则 6 小时内重启就丢了统计地址。
            cached = update_client.load_cache(root)
            self.assertEqual(cached['manifest']['stats']['url'],
                             'https://stats.example.com/api/ping')


if __name__ == '__main__':
    unittest.main()
