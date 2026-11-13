"""营地授权失效检测：接口报登录态失效时，页面要能在拉取前提示补充授权。"""
import json
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = ROOT / 'test-results' / f'camp-auth-health-{uuid.uuid4().hex}'
TMP.mkdir(parents=True, exist_ok=True)

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
from server import app  # noqa: E402


class FakeResponse:
    """够用的 urllib 响应替身：camp_client 只用到 read() 和 headers.items()。"""

    def __init__(self, payload, headers=None, raw=None):
        self._raw = raw if raw is not None else json.dumps(payload).encode('utf-8')
        self.headers = headers or {'returncode': '0'}

    def read(self, size=-1):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class CampAuthHealthTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(ROOT / 'tools'))
        import camp_auth
        import camp_client
        self.camp_auth = camp_auth
        self.camp_client = camp_client
        self.auth_path = TMP / f'auth-{uuid.uuid4().hex}.json'
        self.health_path = self.auth_path.with_name(self.auth_path.stem + '_health.json')
        self.auth_path.write_text(json.dumps({
            'token': 'T', 'userId': '1604610457', 'nickname': 'L.L.',
            'loginAt': '2026-11-07T14:51:29',
        }), encoding='utf-8')
        for module in (camp_auth, camp_client):
            patch = mock.patch.object(module, 'AUTH_PATH', self.auth_path)
            patch.start()
            self.addCleanup(patch.stop)

    def _call(self, payload, headers):
        with mock.patch.object(self.camp_client.request, 'urlopen',
                               return_value=FakeResponse(payload, headers)):
            return self.camp_client.call('/game/morebattlelist', {})

    def test_auth_error_detection_matches_code_and_text(self):
        self.assertTrue(self.camp_client.looks_like_auth_error('-30003', ''))
        self.assertTrue(self.camp_client.looks_like_auth_error('', '登录态失效，请重新登录'))
        self.assertFalse(self.camp_client.looks_like_auth_error('-102', '用户ID不存在'))

    def test_expired_code_marks_invalid_then_success_clears(self):
        with self.assertRaises(self.camp_client.CampAuthError) as caught:
            self._call({'returnCode': '-30003', 'returnMsg': '登录态失效，请重新登录'},
                       {'returncode': '-30003', 'returnmsg': 'x'})
        self.assertEqual(caught.exception.code, '-30003')
        account = self.camp_auth.read_account()
        self.assertTrue(account['expired'])
        self.assertIn('登录态失效', account['reason'])
        self.assertTrue(account['checkedAt'])

        self._call({'returnCode': 0, 'data': {}}, {'returncode': '0'})
        account = self.camp_auth.read_account()
        self.assertFalse(account['expired'])
        self.assertEqual(account['reason'], '')

    def test_encryptparamerr_marks_invalid(self):
        with self.assertRaises(self.camp_client.CampAuthError):
            self._call({'returnCode': 0}, {'encryptparamerr': 'blocked'})
        account = self.camp_auth.read_account()
        self.assertTrue(account['expired'])
        self.assertIn('安全参数被拒', account['reason'])

    def test_business_error_is_not_auth_failure(self):
        with self.assertRaises(self.camp_client.CampAuthError):
            self._call({'returnCode': '-30003'}, {'returncode': '-30003'})
        result = self._call({'returnCode': '-102', 'returnMsg': '用户ID不存在'}, {'returncode': '0'})
        self.assertEqual(result['body']['returnCode'], '-102')
        self.assertFalse(self.camp_auth.read_account()['expired'])

    def test_sync_worker_flags_auth_failure(self):
        import camp_sync
        with mock.patch.object(camp_sync, 'sync_entries',
                               side_effect=self.camp_client.CampAuthError('登录态失效', '-30003')):
            results, attached = server._camp_sync_worker('100000001', '队长', [{'gameSeq': '1'}])
        self.assertEqual(attached, [])
        self.assertFalse(results[0]['ok'])
        self.assertTrue(results[0]['authInvalid'])


class CampAuthApiTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(ROOT / 'tools'))
        import camp_auth
        import camp_client
        self.camp_auth = camp_auth
        self.camp_client = camp_client
        self.auth_path = TMP / f'auth-{uuid.uuid4().hex}.json'
        self.health_path = self.auth_path.with_name(self.auth_path.stem + '_health.json')
        self.auth_path.write_text(json.dumps({
            'token': 'T', 'userId': '1604610457', 'nickname': 'L.L.',
            'loginAt': '2026-11-07T14:51:29',
        }), encoding='utf-8')
        for module in (camp_auth, camp_client):
            patch = mock.patch.object(module, 'AUTH_PATH', self.auth_path)
            patch.start()
            self.addCleanup(patch.stop)
        self.client = TestClient(app, base_url='http://localhost')

    def test_auth_status_reports_expired_state(self):
        self.camp_auth.mark_invalid('营地登录态已失效（-30003），请重新扫码授权。', '-30003')
        payload = self.client.get('/api/camp/auth').json()
        self.assertTrue(payload['authorized'])
        self.assertTrue(payload['expired'])
        self.assertEqual(payload['code'], '-30003')
        self.assertIn('重新扫码', payload['reason'])

    def test_camp_list_returns_401_with_auth_flag(self):
        def fail(*args, **kwargs):
            raise self.camp_client.CampAuthError('营地登录态已失效（-30003），请重新扫码授权。', '-30003')
        with mock.patch.object(self.camp_client, 'call', side_effect=fail):
            response = self.client.post('/api/camp/list', json={'campUserId': '100000001'})
        self.assertEqual(response.status_code, 401)
        payload = response.json()
        self.assertTrue(payload['authInvalid'])
        self.assertIsInstance(payload['detail'], str)
        self.assertIn('重新扫码', payload['detail'])

    def test_auth_check_probe_and_cache(self):
        def fail(*args, **kwargs):
            raise self.camp_client.CampAuthError('营地登录态已失效（-30003），请重新扫码授权。', '-30003')
        with mock.patch.object(self.camp_client, 'call', side_effect=fail) as probe:
            first = self.client.post('/api/camp/auth/check?force=1').json()
        self.assertFalse(first['valid'])
        self.assertFalse(first['cached'])
        self.assertTrue(probe.called)
        self.assertTrue(self.client.get('/api/camp/auth').json()['expired'])

        def okay(*args, **kwargs):
            return {'body': {'returnCode': 0, 'data': {'list': []}}}
        with mock.patch.object(self.camp_client, 'call', side_effect=okay) as probe:
            second = self.client.post('/api/camp/auth/check?force=1').json()
            cached = self.client.post('/api/camp/auth/check').json()
        self.assertTrue(second['valid'])
        self.assertEqual(probe.call_count, 1)
        self.assertTrue(cached['cached'])
        self.assertTrue(cached['valid'])
        self.assertFalse(self.client.get('/api/camp/auth').json()['expired'])


if __name__ == '__main__':
    unittest.main()
