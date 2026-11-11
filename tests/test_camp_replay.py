import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import camp_replay
import channel_store
from tests.collection_fixtures import complete_collection

PERSONAL_LINK = (
    'https://camp.qq.com/h5/webdist/battle-replay/index.html?gameseq=1793606215'
    '&relaysvrentity=870343216&gamesvrentity=95868&playerid=3686206139544504830'
)
KPL_LINK = (
    'https://camp.qq.com/h5/webdist/battle-replay/index.html?gameseq=1793441243'
    '&relaysvrentity=48251408&gamesvrentity=50&playerid=undefined'
    '&kplMatchFlag=1&eId=10279&mId=10859969'
)
BETA_LINK = PERSONAL_LINK + '&betaFlag=1'
# 微信里分享营地战绩复制出来的 mp-redirect 链接。字段名不同：
# gameSvrId / relaySvrId / userId，并且带 battleType、pvpType（接口返回里没有）。
MP_REDIRECT_LINK = (
    'https://camp.qq.com/h5/webdist/mp-redirect/index.html?userId=361061394'
    '&roleId=428521639&router=battleDetail&gameSeq=1793606215&acntCamp=1'
    '&relaySvrId=870343216&battleType=16&gameSvrId=95868&pvpType=5'
)
SHORT_LINK = 'https://cu.qq.com/3tuABL90'


def payload():
    return {'result': 0, 'returnCode': 0, 'returnMsg': '', 'data': {
        'winCamp': '1',
        'camp1Gold': 41021, 'camp2Gold': 29266,
        'camp1GoldArr': [3056, 41021], 'camp2GoldArr': [2684, 29266],
        'ecoDistance': [372, 11755],
        'teamMatchInfo': {'teamId1': 1, 'teamTitle1': '蓝队', 'score1': 27,
                          'teamId2': 2, 'teamTitle2': '红队', 'score2': 6},
        'keyEventArr': [
            {'eventType': 'dragontower', 'dtData': {'killTime': '39000', 'dtType': '2',
                                                    'dtID': '20', 'dtCamp': '1',
                                                    'killerCamp': '1', 'killerId': '1',
                                                    'kills': [{'camp': '1', 'killerId': '1',
                                                               'hurtTotal': '10'}]}},
            {'eventType': 'battle', 'dtData': {'killTime': '63000', 'dtType': '1',
                                                'killerCamp': '2', 'killerId': '2'}},
        ],
        'extendEventArr': [{'eventTime': 39000, 'eventList': [
            {'eventType': 'killbuff', 'dtData': {'dtType': '1', 'dtID': '10',
                                                  'dtCamp': '1', 'killerCamp': '1',
                                                  'killerId': '1'}}]}],
        'equipEvent': [],
        'matchInfo': [
            {'acntcamp': '1', 'heroName': '百里守约', 'heroId': 196,
             'playerId': '1', 'killCnt': '5', 'deadCnt': '0', 'assistCnt': '8',
             'newGrow': '9633', 'newBattle': '7313', 'newSurvive': '11688',
             'newHurtHero': '7217', 'newKDA': '10721'},
            {'acntcamp': '2', 'heroName': '公孙离', 'heroId': 199,
             'playerId': '2', 'killCnt': '1', 'deadCnt': '5', 'assistCnt': '2',
             'newGrow': '6239', 'newBattle': '3975', 'newSurvive': '6433',
             'newHurtHero': '6956', 'newKDA': '3053'},
        ],
        'reportData': {'playerPosInfo': [
            {'playerID': '1', 'posArr': [[1, 2], [3, 4], [5, 6]]},
            {'playerID': '2', 'posArr': [[7, 8], [9, 10], [11, 12]]},
        ]},
    }}


class LinkTests(unittest.TestCase):
    def test_personal_kpl_beta(self):
        personal = camp_replay.parse_link(PERSONAL_LINK)
        self.assertEqual(personal['kind'], 'personal')
        self.assertEqual(personal['gameSeq'], '1793606215')
        self.assertEqual(camp_replay.payload_for(personal)['gameSvr'], '95868')
        kpl = camp_replay.parse_link(KPL_LINK)
        self.assertEqual(kpl['kind'], 'kpl')
        kpl_payload = camp_replay.payload_for(kpl)
        self.assertEqual(kpl_payload['eId'], '10279')
        self.assertEqual(kpl_payload['mId'], '10859969')
        self.assertEqual(camp_replay.parse_link(BETA_LINK)['kind'], 'beta')

    def test_rejects_wechat_and_other_hosts(self):
        with self.assertRaises(camp_replay.CampReplayError):
            camp_replay.parse_link('https://servicewechat.com/wxascheme/jump_wxa?url=x')
        with self.assertRaises(camp_replay.CampReplayError):
            camp_replay.parse_link('https://example.com/?gameseq=1&gamesvrentity=2&relaysvrentity=3')

    def test_mp_redirect_share_link(self):
        """微信分享出来的是 mp-redirect 链接，字段名不同但能直接用。"""
        link = camp_replay.parse_link(MP_REDIRECT_LINK)
        self.assertEqual(link['kind'], 'personal')
        self.assertEqual(link['gameSeq'], '1793606215')
        self.assertEqual(link['gameSvr'], '95868')
        self.assertEqual(link['relaySvr'], '870343216')
        self.assertEqual(link['playerId'], '361061394')
        self.assertEqual(link['battleType'], '16')
        self.assertEqual(link['pvpType'], '5')
        payload = camp_replay.payload_for(link)
        self.assertEqual(payload['gameSvr'], '95868')
        self.assertEqual(payload['playerId'], '361061394')

    def test_share_short_links_are_recognised(self):
        self.assertTrue(camp_replay.is_short_link(SHORT_LINK))
        self.assertTrue(camp_replay.is_short_link('https://wxaurl.cn/abc'))
        self.assertFalse(camp_replay.is_short_link('https://camp.qq.com/h5/x'))

    def test_import_link_expands_short_link_before_parsing(self):
        """短链先展开成 mp-redirect，再走原来的解析；展开失败要报错而不是静默。"""
        with mock.patch.object(camp_replay, 'expand_short_link', return_value=MP_REDIRECT_LINK):
            with mock.patch.object(camp_replay, 'fetch') as fake_fetch:
                fake_fetch.return_value = (payload(), payload()['data'])
                with mock.patch.object(camp_replay, 'STORE', Path(tempfile.mkdtemp())):
                    result = camp_replay.import_link(SHORT_LINK)
        self.assertEqual(result['meta']['gameSeq'], '1793606215')
        self.assertEqual(result['meta']['battleType'], '16')
        self.assertEqual(fake_fetch.call_args[0][0]['playerId'], '361061394')


class NormalizeTests(unittest.TestCase):
    def test_normalize(self):
        link = camp_replay.parse_link(PERSONAL_LINK)
        normalized, positions = camp_replay.normalize(payload(), link)
        self.assertEqual(normalized['schema'], camp_replay.SCHEMA)
        self.assertEqual(normalized['match']['goldPoints'], 2)
        self.assertEqual(normalized['match']['teamGold'], {'blue': 41021, 'red': 29266})
        self.assertEqual(normalized['match']['winCamp'], '1')
        self.assertEqual(normalized['players'][0]['hero'], '百里守约')
        self.assertEqual(normalized['players'][0]['kills'], 5)
        self.assertEqual(normalized['positions']['pointsPerPlayer'], 3)
        self.assertEqual(len(positions), 2)
        self.assertEqual(normalized['events']['key'][0]['timeSec'], 39)
        self.assertEqual(normalized['match']['durationSec'], 63)
        self.assertTrue(any('30秒' in warning for warning in normalized['warnings']))


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_store = camp_replay.STORE
        camp_replay.STORE = Path(self.temp.name) / 'official'
        self.old_fetch = camp_replay.fetch
        self.calls = 0

        def fake_fetch(link, timeout=30):
            self.calls += 1
            value = payload()
            return value, value['data']

        camp_replay.fetch = fake_fetch

    def tearDown(self):
        camp_replay.STORE = self.old_store
        camp_replay.fetch = self.old_fetch
        self.temp.cleanup()

    def test_import_cached_files_and_read(self):
        first = camp_replay.import_link(PERSONAL_LINK)
        self.assertEqual(first['id'], 'camp-1793606215')
        self.assertFalse(first['cached'])
        self.assertEqual(self.calls, 1)
        folder = camp_replay.STORE / 'camp-1793606215'
        self.assertTrue((folder / 'raw.json').is_file())
        self.assertTrue((folder / 'normalized.json').is_file())
        self.assertTrue((folder / 'positions.json').is_file())
        cached = camp_replay.import_link(PERSONAL_LINK)
        self.assertTrue(cached['cached'])
        self.assertEqual(self.calls, 1)
        meta, normalized = camp_replay.read_normalized('camp-1793606215')
        self.assertEqual(meta['match']['goldPoints'], 2)
        self.assertEqual(normalized['match']['keyEvents'], 2)
        self.assertEqual(camp_replay.list_replays()[0]['id'], 'camp-1793606215')
        self.assertIsNotNone(camp_replay.positions_path('camp-1793606215'))

    def test_channel_bundle_uses_official_timeline(self):
        result = camp_replay.import_link(PERSONAL_LINK)
        channel = channel_store.blank({'date': '2026-11-02'})
        channel_store.attach_official(channel, result['id'], result['meta'],
                                      result['normalized'])
        complete_collection(channel)
        channel_store.set_review(channel, 'tester')
        bundle = channel_store.bundle(channel)
        self.assertEqual(bundle['team']['timelineSource'], 'official-30s')
        self.assertEqual(bundle['team']['timeline'][0]['gameTime'], 30)
        self.assertEqual(bundle['team']['timeline'][0]['blueGold'], 3056)
        self.assertEqual(bundle['match']['officialReplay']['kind'], 'personal')
        self.assertEqual(bundle['match']['officialReplay']['positions']['pointsPerPlayer'], 3)
        self.assertIn('30秒', ' '.join(bundle['warnings']))


if __name__ == '__main__':
    unittest.main()
