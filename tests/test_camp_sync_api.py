import json
import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = ROOT / 'test-results' / f'camp-api-{uuid.uuid4().hex}'
TMP.mkdir(parents=True, exist_ok=True)
os.environ['TRAINING_DB'] = str(TMP / 'training.sqlite3')
os.environ['CAMP_CONFIG_FILE'] = str(TMP / 'camp_config.json')
os.environ['CAMP_DETAIL_DIR'] = str(TMP / 'camp_details')
os.environ['CAMP_SYNC_STATE'] = str(TMP / 'camp_sync_state.json')

from fastapi.testclient import TestClient

import camp_replay
from server import app


def fake_import(url, force=False):
    meta = {'id': 'camp-1793606215', 'gameSeq': '1793606215',
            'match': {'winCamp': '1', 'durationSec': 693.0}}
    return {'id': 'camp-1793606215', 'meta': meta, 'cached': True}


class CampConfigTests(unittest.TestCase):
    """选手白名单的清洗、持久化与同步门槛；不打真实营地接口。"""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, base_url='http://localhost')

    def test_config_roundtrip_and_validation(self):
        response = self.client.post('/api/camp/config', json={'players': [
            {'nickname': '队长', 'campUserId': '540599032'},
            {'nickname': '坏', 'campUserId': 'not-a-number'},
            'not-a-dict',
        ]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([p['campUserId'] for p in response.json()['players']], ['540599032'])
        stored = self.client.get('/api/camp/config').json()
        self.assertEqual(stored['players'][0]['nickname'], '队长')

    def test_sync_requires_whitelist(self):
        self.client.post('/api/camp/config', json={'players': []})
        response = self.client.post('/api/camp/sync', json={'entries': []})
        self.assertEqual(response.status_code, 400)
        self.assertIn('勾选', response.json()['detail'])

    def test_status_shapes(self):
        auth = self.client.get('/api/camp/auth').json()
        self.assertIn('authorized', auth)
        status = self.client.get('/api/camp/sync').json()
        for key in ('running', 'result', 'error', 'detailsCount', 'config', 'auth'):
            self.assertIn(key, status)
        self.assertFalse(status['running'])

    def test_resolve_extracts_user_id_from_share_link(self):
        """分享链接（含 mp-redirect 形态）直接解出营地 ID，不用人工抄。"""
        response = self.client.post('/api/camp/resolve', json={'url':
            'https://camp.qq.com/h5/webdist/mp-redirect/index.html?userId=540599032'
            '&gameSeq=1793795458&battleType=12&gameSvrId=108724&relaySvrId=1260446482'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['userId'], '540599032')
        self.assertEqual(response.json()['gameSeq'], '1793795458')

    def test_resolve_rejects_non_camp_links(self):
        response = self.client.post('/api/camp/resolve', json={'url': 'https://example.com/x'})
        self.assertEqual(response.status_code, 400)

    def test_batch_items_carry_share_user_id(self):
        """批量导入顺便带回分享者的营地 ID，供一键加入同步清单。"""
        text = ('https://camp.qq.com/h5/webdist/battle-replay/index.html?gameseq=1793606215'
                '&gamesvrentity=2&relaysvrentity=3&userId=540599032')
        with mock.patch.object(camp_replay, 'import_link', side_effect=fake_import):
            response = self.client.post('/api/official/replays/batch', json={'text': text})
        self.assertEqual(response.status_code, 200)
        item = response.json()['items'][0]
        self.assertEqual(item['shareUserId'], '540599032')


class CampAuthQrTests(unittest.TestCase):
    """网页扫码会话：手机上点「确定」后必须写凭证并返回 success。

    回归：poll_login_once 曾读 session['xLogUid']（实际键是 xlogUid），
    KeyError 变成 500，前端静默吞掉后永远停在「已扫码，等待确认」。
    """

    def setUp(self):
        sys.path.insert(0, str(ROOT / 'tools'))
        import camp_auth
        self.camp_auth = camp_auth
        self.client = TestClient(app, base_url='http://localhost')
        self.auth_path = TMP / f'camp_auth_{uuid.uuid4().hex}.json'
        self.auth_path.unlink(missing_ok=True)

    def _start_session(self, poll_status=(405, 'wx-code'), login_error=None):
        login = (mock.patch.object(self.camp_auth, 'login_with_code',
                                   side_effect=RuntimeError(login_error))
                 if login_error else
                 mock.patch.object(self.camp_auth, 'login_with_code',
                                   return_value={'token': 'T', 'userId': 'U', 'nickname': 'N'}))
        patches = [
            mock.patch.object(self.camp_auth, 'get_sdk_ticket', return_value='ticket'),
            mock.patch.object(self.camp_auth, 'get_qrcode', return_value=('uuid-test', 'aGVsbG8=')),
            mock.patch.object(self.camp_auth, 'poll_qrcode', return_value=poll_status),
            mock.patch.object(self.camp_auth, 'AUTH_PATH', self.auth_path),
            login,
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        return self.client.post('/api/camp/auth/qr').json()

    def _poll(self, task_id):
        return self.client.get('/api/camp/auth/poll', params={'taskId': task_id})

    def test_confirm_writes_credentials(self):
        qr = self._start_session()
        self.assertTrue(qr.get('taskId'))
        response = self._poll(qr['taskId'])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'success')
        self.assertEqual(response.json()['nickname'], 'N')
        account = json.loads(self.auth_path.read_text(encoding='utf-8'))
        self.assertEqual(account['token'], 'T')
        self.assertTrue(account['xLogUid'])
        self.assertEqual(self.camp_auth.login_with_code.call_args[0][1], account['xLogUid'])
        self.assertNotIn(qr['taskId'], self.camp_auth._login_sessions)

    def test_login_failure_is_structured_not_500(self):
        qr = self._start_session(login_error='营地登录失败：模拟')
        response = self._poll(qr['taskId'])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'error')
        self.assertIn('模拟', response.json()['message'])
        self.assertFalse(self.auth_path.exists())

    def test_confirm_without_code_reports_error(self):
        qr = self._start_session(poll_status=(405, ''))
        result = self._poll(qr['taskId']).json()
        self.assertEqual(result['status'], 'error')
        self.assertIn('重新扫码', result['message'])
        self.assertFalse(self.auth_path.exists())

    def test_scanned_then_cancel(self):
        qr = self._start_session(poll_status=(404, ''))
        self.assertEqual(self._poll(qr['taskId']).json()['status'], 'scanned')
        cancelled = self.client.post('/api/camp/auth/cancel', params={'taskId': qr['taskId']})
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(self._poll(qr['taskId']).json()['status'], 'expired')


class CampResolveModeAgnosticTests(unittest.TestCase):
    """登记选手的链接解析与对局模式无关（开房间征召也要能登记）。"""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, base_url='http://localhost')

    def _resolve(self, url):
        return self.client.post('/api/camp/resolve', json={'url': url})

    def test_any_battle_type_resolves(self):
        base = ('https://camp.qq.com/h5/webdist/mp-redirect/index.html?'
                'userId=361061394&roleId=428521639&gameSeq=1793606215'
                '&gameSvrId=95868&relaySvrId=870343216')
        extras = ['', '&battleType=1', '&battleType=16&pvpType=5',
                  '&battleType=99&pvpType=7', '&kplMatchFlag=1&eId=1&mId=2',
                  '&betaFlag=1', '&router=battleDetail&roomType=draft']
        for extra in extras:
            with self.subTest(extra=extra):
                response = self._resolve(base + extra)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()['userId'], '361061394')

    def test_room_draft_link_without_replay_server_params(self):
        """开房间征召链接可能只带 userId + gameSeq，仍能登记选手。"""
        url = ('https://camp.qq.com/h5/webdist/mp-redirect/index.html?'
               'userId=540599032&gameSeq=1793606215&battleType=32')
        response = self._resolve(url)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['userId'], '540599032')
        self.assertEqual(response.json()['battleType'], '32')

    def test_prefers_user_id_over_role_and_player_ids(self):
        url = ('https://camp.qq.com/h5/webdist/mp-redirect/index.html?'
               'playerid=3686206139544504830&roleId=428521639'
               '&userId=361061394&gameSeq=1793606215')
        response = self._resolve(url)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['userId'], '361061394')

    def test_replay_link_without_user_id_is_rejected_clearly(self):
        url = ('https://camp.qq.com/h5/webdist/battle-replay/index.html?'
               'gameseq=1793606215&gamesvrentity=95868&relaysvrentity=870343216'
               '&playerid=3686206139544504830')
        response = self._resolve(url)
        self.assertEqual(response.status_code, 400)
        self.assertIn('userId', response.json()['detail'])

    def test_non_camp_links_are_still_rejected(self):
        for url in ('https://servicewechat.com/wxascheme/jump_wxa?url=x',
                    'https://example.com/?userId=361061394'):
            with self.subTest(url=url):
                self.assertEqual(self._resolve(url).status_code, 400)


if __name__ == '__main__':
    unittest.main()
