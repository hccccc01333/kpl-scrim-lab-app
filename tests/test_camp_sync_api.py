import datetime
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
os.environ['ANALYSIS_MATCHES'] = str(TMP / 'matches')
os.environ['CAMP_CONFIG_FILE'] = str(TMP / 'camp_config.json')
os.environ['CAMP_DETAIL_DIR'] = str(TMP / 'camp_details')
os.environ['CAMP_SYNC_STATE'] = str(TMP / 'camp_sync_state.json')

from fastapi.testclient import TestClient

import camp_replay
import server
from server import app, db


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


class CampListImportedTests(unittest.TestCase):
    """营地同步的自动入库与缺失值策略。

    无缺失值：建通道后直接复核并写入正式统计；
    有缺失值：只建审查记录，列表标成待审查，不重复拉详情。
    """

    SEQ = '1793900001'
    MISSING_SEQ = '1793900002'

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, base_url='http://localhost')
        sys.path.insert(0, str(ROOT / 'tools'))
        import camp_client
        cls.camp_client = camp_client
        # server 可能被更早的测试模块导入，MATCHES_DIR 已在导入时定死；
        # 在测试里显式指向临时目录，避免把测试 bundle 写进真实 data/matches。
        cls.matches_dir_patch = mock.patch.object(server, 'MATCHES_DIR', TMP / 'matches')
        cls.matches_dir_patch.start()
        cls.addClassCleanup(cls.matches_dir_patch.stop)

    def _list_entry(self, seq=None):
        entry = {
            'gameSeq': seq or self.SEQ, 'dtEventTime': 1793804938, 'usedTime': 838,
            'gametime': '11-04 22:55', 'mapName': '排位赛', 'battleType': 1,
            'gameresult': 1, 'winCamp': '1', 'AcntCamp': '1',
            'killcnt': 3, 'deadcnt': 1, 'assistcnt': 8,
            'heroName': '孙悟空', 'gradeGame': '9.2', 'roleJobName': '打野',
            'gameSvrId': '95868', 'relaySvrId': '870343216',
            'battleDetailUrl': 'https://x/?toAppRoleId=428521639',
        }
        body = {'returnCode': 0, 'data': {'list': [entry], 'hasMore': False, 'lastTime': 0}}
        with mock.patch.object(self.camp_client, 'call', return_value={'body': body}):
            response = self.client.post('/api/camp/list', json={'campUserId': '540599032'})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['entries'][0]

    def _detail(self, seq, stats):
        head_id = '3686206139544504830'

        def role(index, camp, player_id, hero):
            return {
                'basicInfo': {'roleId': f'role-{index}', 'roleName': f'选手{index}',
                              'playerId': player_id, 'acntCamp': camp},
                'battleStats': stats,
                'battleRecords': {'usedHero': {'heroId': 196, 'heroName': hero,
                                               'heroIcon': ''},
                                  'position': index % 5, 'finalEquips': []},
                'heroBehavior': {}, 'dataBehavior': [],
            }

        blue_heroes = ['孙悟空', '关羽', '妲己', '钟馗', '百里守约']
        red_heroes = ['吕布', '兰陵王', '张良', '貂蝉', '公孙离']
        blue = [role(i, 1, head_id if i == 0 else f'90000000000000000{i}', blue_heroes[i])
                for i in range(5)]
        red = [role(i + 5, 2, f'80000000000000000{i}', red_heroes[i]) for i in range(5)]
        return {
            '_campEntry': {'dtEventTime': 1793804938, 'usedTime': 838,
                           'mapName': '排位赛', 'gametime': '11-04 22:55',
                           'battleType': 1, 'winCamp': 1,
                           'killcnt': 3, 'deadcnt': 1, 'assistcnt': 8},
            'data': {'head': {'gameResult': True, 'acntCamp': 1,
                              'mapName': '排位赛', 'heroId': 196,
                              'heroName': '孙悟空', 'gradeGame': '9.2',
                              'matchDesc': '伯仲局', 'userId': '540599032',
                              'playerId': head_id,
                              'killCnt': 3, 'deadCnt': 1, 'assistCnt': 8},
                     'blueRoles': blue, 'redRoles': red,
                     'blueTeam': {'banHeros': []}, 'redTeam': {'banHeros': []}},
        }

    def _write_detail(self, seq, stats):
        detail_dir = TMP / 'camp_details'
        detail_dir.mkdir(parents=True, exist_ok=True)
        (detail_dir / f'{seq}.json').write_text(
            json.dumps(self._detail(seq, stats), ensure_ascii=False), encoding='utf-8')

    def test_complete_detail_enters_stats_without_manual_review(self):
        self._write_detail(self.SEQ, {
            'killCnt': '3', 'deadCnt': '1', 'assistCnt': '8',
            'gradeGame': '9.2', 'money': '9000',
            'totalHurtCnt': '30000', 'totalBehurtCnt': '20000',
            'joinGamePercent': '0.6',
        })

        entry = self._list_entry()
        self.assertFalse(entry['imported'])
        self.assertFalse(entry['channelExists'])
        self.assertTrue(entry['detailCached'])
        self.assertEqual(entry['startedAt'], '2026-11-04T22:55:00+08:00')
        self.assertEqual(entry['gameresult'], 1)

        server._camp_backfill_state['at'] = 0
        report = server._camp_backfill_channels()
        self.assertEqual(report['created'], 1, report)
        self.assertEqual(report['saved'], 1, report)
        with db() as c:
            row = c.execute(
                'SELECT body FROM channels WHERE body LIKE ?',
                (f'%camp-{self.SEQ}%',)).fetchone()
        self.assertIsNotNone(row)
        channel = json.loads(row['body'])
        match = channel['match']
        for key, value in (('heroName', '孙悟空'), ('gameresult', 1),
                           ('kda', [3, 1, 8]), ('date', '2026-11-04'),
                           ('startedAt', '2026-11-04T22:55:00+08:00')):
            self.assertEqual(match.get(key), value, key)
        self.assertEqual(len(channel['sources']['camp']['players']), 10)
        self.assertEqual(channel['saved']['status'], 'saved')
        self.assertEqual(channel['review']['status'], 'reviewed')
        self.assertTrue((TMP / 'matches' / f"channel-{channel['id']}.json").is_file())

        refreshed = self._list_entry()
        self.assertTrue(refreshed['imported'])
        self.assertTrue(refreshed['channelExists'])
        self.assertTrue(refreshed['channelReady'])

    def test_missing_detail_stays_in_review(self):
        self._write_detail(self.MISSING_SEQ, {
            'killCnt': '3', 'deadCnt': '1', 'assistCnt': '8',
            'gradeGame': '9.2', 'money': '9000',
        })
        server._camp_backfill_state['at'] = 0
        report = server._camp_backfill_channels()
        self.assertEqual(report['created'], 1, report)
        self.assertEqual(report['review'], 1, report)
        self.assertEqual(report['saved'], 0, report)

        entry = self._list_entry(self.MISSING_SEQ)
        self.assertFalse(entry['imported'])
        self.assertTrue(entry['channelExists'])
        self.assertTrue(entry['channelReady'])

        server._camp_finalize_state['at'] = 0
        finalized = server._camp_auto_finalize_channels()
        self.assertEqual(finalized['passed'], 0, finalized)
        with db() as c:
            row = c.execute(
                'SELECT body FROM channels WHERE body LIKE ?',
                (f'%camp-{self.MISSING_SEQ}%',)).fetchone()
        channel = json.loads(row['body'])
        self.assertEqual(channel['saved']['status'], 'not-saved')
        self.assertTrue(channel['draft']['missing'])

        # 不能在批量「一键通过」里被带走；必须逐条 allowMissing 明确确认。
        bulk = self.client.post('/api/channels/approve', json={}).json()
        self.assertEqual(len(bulk['passed']), 0)
        skipped_ids = {item['id'] for item in bulk['skipped']}
        self.assertIn(channel['id'], skipped_ids)
        refused = self.client.post('/api/channels/approve',
                                   json={'channelIds': [channel['id']]}).json()
        self.assertEqual(len(refused['passed']), 0)
        confirmed = self.client.post('/api/channels/approve', json={
            'channelIds': [channel['id']], 'allowMissing': True,
            'reviewedBy': '测试确认',
        }).json()
        self.assertEqual(len(confirmed['passed']), 1, confirmed)
        with db() as c:
            row = c.execute('SELECT body FROM channels WHERE body LIKE ?',
                            (f'%camp-{self.MISSING_SEQ}%',)).fetchone()
        saved = json.loads(row['body'])
        self.assertEqual(saved['saved']['status'], 'saved')
        self.assertEqual(saved['review']['reviewedBy'], '测试确认')


class CampSyncWorkerResilienceTests(unittest.TestCase):
    """同步失败必须看得见：旧版 tools 或单局异常都不能把整批悄悄吞掉。

    现场问题：安装包只更新了主程序、tools/camp_sync.py 还是旧版，
    sync_entries 不认 on_progress → TypeError → 127 局一局没进，
    页面却按「勾选数」提示「已同步 127 局」。这类失败要能降级、能报出来。
    """

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, base_url='http://localhost')

    def _worker(self, fake_sync):
        stub = {'created': 0, 'updated': 0, 'attached': 0, 'saved': 0, 'review': 0,
                'failed': 0, 'skipped': 0, 'channelIds': [], 'items': []}
        with mock.patch.dict(sys.modules, {'camp_sync': fake_sync}), \
                mock.patch.object(server, '_camp_tools', lambda: None), \
                mock.patch.object(server, '_camp_ensure_channels',
                                  lambda entries, nickname, progress=None: dict(stub)):
            return server._camp_sync_worker('540599032', '队长', [{'gameSeq': '1793900009'}])

    def test_legacy_tools_without_on_progress_still_sync(self):
        calls = []

        class LegacyCampSync:
            @staticmethod
            def sync_entries(camp_user_id, entries):
                calls.append((camp_user_id, len(entries)))
                return {'fetched': 1, 'saved': 0, 'cached': 0, 'failed': 0, 'gameSeqs': []}

        results, _ids = self._worker(LegacyCampSync)
        self.assertTrue(results[0]['ok'], results[0])
        self.assertEqual(calls, [('540599032', 1)])

    def test_sync_error_is_reported_not_swallowed(self):
        def boom(camp_user_id, entries, on_progress=None):
            raise RuntimeError('营地接口 502')

        results, _ids = self._worker(mock.Mock(sync_entries=boom))
        self.assertFalse(results[0]['ok'])
        self.assertIn('502', results[0]['error'])
        self.assertEqual(results[0]['stage'], 'detail')

    def test_channels_only_built_when_detail_exists(self):
        seqs = [f'77{uuid.uuid4().int % 10 ** 8:08d}' for _ in range(2)]
        report = server._camp_ensure_channels([{'gameSeq': seq} for seq in seqs], '队长')
        self.assertEqual(report['created'], 0, report)
        self.assertEqual(report['skipped'], 2, report)
        self.assertEqual([item['status'] for item in report['items']], ['skipped', 'skipped'])
        with db() as c:
            for seq in seqs:
                row = c.execute('SELECT 1 FROM channels WHERE body LIKE ?',
                                (f'%camp-{seq}%',)).fetchone()
                self.assertIsNone(row)


class CampDetailWindowTests(unittest.TestCase):
    """营地只给最近一个月的战局详情（-30457）：更早的局要提前标出来，不反复重试。

    现场问题：8 月到 9 月初的 127 局全部返回 -30457「暂不支持查看一个月前的战绩详情」，
    被当成网络失败连续 5 局后整批停下，教练以为还能重试。
    """

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT / 'tools'))
        import camp_sync
        cls.camp_sync = camp_sync

    def _entry(self, seq, days_ago):
        moment = datetime.datetime.now() - datetime.timedelta(days=days_ago)
        return {'gameSeq': seq, 'startedAt': moment.strftime('%Y-%m-%dT%H:%M:%S+08:00'),
                'dtEventTime': int(moment.timestamp()), 'usedTime': 900,
                'gameSvrId': '1', 'relaySvrId': '2', 'battleType': 32,
                'uniqueRoleId': '428521639'}

    def test_detail_expired_boundary(self):
        self.assertTrue(self.camp_sync.detail_expired(self._entry('a', 40)))
        self.assertFalse(self.camp_sync.detail_expired(self._entry('b', 10)))
        self.assertFalse(self.camp_sync.detail_expired({}))

    def test_expired_entries_skip_network_and_are_reported(self):
        calls = []
        old = self._entry('1700000001', 60)
        with mock.patch.object(self.camp_sync, 'battle_detail',
                               side_effect=lambda *a, **k: calls.append(a) or {'body': {}}):
            summary = self.camp_sync.sync_entries('540599032', [old], interval=0)
        self.assertEqual(calls, [], '超出一个月的局不该再发详情请求')
        self.assertEqual(summary['unsupported'], 1)
        self.assertEqual(summary['unsupportedSeqs'], ['1700000001'])
        self.assertEqual(summary['failed'], 0)

    def test_api_30457_is_marked_unsupported_not_failed(self):
        recent = self._entry('1700000002', 2)
        body = {'returnCode': -30457, 'returnMsg': '-30457:暂不支持查看一个月前的战绩详情'}
        with mock.patch.object(self.camp_sync, 'battle_detail', return_value={'body': body}):
            summary = self.camp_sync.sync_entries('540599032', [recent], interval=0)
        self.assertEqual(summary['unsupported'], 1)
        self.assertEqual(summary['unsupportedSeqs'], ['1700000002'])
        self.assertEqual(summary['failed'], 0)
        self.assertEqual(summary['aborted'], '')


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
