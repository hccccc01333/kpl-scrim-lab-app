from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parent))
from replay_fixtures import (HERO_IDS,NORMAL_5V5_HERO_IDS,NORMAL_5V5_NAMES,abc_fixture,
                             deflate,normal_5v5_fixture,ope_fixture)
import replay_parser
from replay_parser import (ReplayFormatError,inflate_raw,inspect_abc,inspect_replay,
                           parse_ope_bytes)

NEW_ABC=Path('data/replays/samples/abc_batch/20261101_182452_-1723849936_94263_1793527939_CBDD358E761B15A4DF526A179E8119E2.abc')
NEW_OPE=NEW_ABC.with_suffix('.ope')
NORMAL_ABC=Path('data/replays/samples/20261102_161129/20261102_161129_870343216_95868_1793606215_2B9FAA08A7AD40D09ABDA364F9C1E804.abc')
NORMAL_OPE=NORMAL_ABC.with_suffix('.ope')
NORMAL2_ABC=Path('data/replays/samples/20261102_163751/20261102_163751_-1996438720_96420_1793607470_2B9FAA08A7AD40D09ABDA364F9C1E804.abc')
NORMAL2_OPE=NORMAL2_ABC.with_suffix('.ope')


class ParseCacheTests(unittest.TestCase):
    """One upload must not be parsed twice (upload check + import)."""

    def setUp(self):
        replay_parser.cache_clear()

    def test_second_parse_reuses_the_cached_report(self):
        data = normal_5v5_fixture()
        calls = []
        original = replay_parser.parse_header

        def counting(payload):
            calls.append(1)
            return original(payload)

        with mock.patch.object(replay_parser, 'parse_header', counting):
            replay_parser.inspect_abc(data)
            replay_parser.inspect_abc(data)
        self.assertEqual(len(calls), 1)

    def test_callers_cannot_mutate_the_cached_report(self):
        data = normal_5v5_fixture()
        first = replay_parser.inspect_abc(data)
        first['blocks'][0]['heroName'] = 'MUTATED'
        first['warnings'].append('MUTATED')
        second = replay_parser.inspect_abc(data)
        self.assertNotEqual(second['blocks'][0]['heroName'], 'MUTATED')
        self.assertNotIn('MUTATED', second['warnings'])

    def test_explicit_hero_map_bypasses_the_cache(self):
        data = normal_5v5_fixture()
        calls = []
        original = replay_parser.parse_header

        def counting(payload):
            calls.append(1)
            return original(payload)

        heroes = {hero: f'h{hero}' for hero in NORMAL_5V5_HERO_IDS}
        with mock.patch.object(replay_parser, 'parse_header', counting):
            replay_parser.inspect_abc(data, heroes)
            replay_parser.inspect_abc(data, heroes)
        self.assertEqual(len(calls), 2)


class ReplayParserTests(unittest.TestCase):
    def test_ten_heroes_without_camp_or_position_inference(self):
        r=inspect_replay(abc_fixture())
        self.assertEqual([b['heroId'] for b in r['blocks']],HERO_IDS)
        self.assertTrue(all(b['camp'] is None and b['position'] is None for b in r['blocks']))
        self.assertEqual(r['tlv']['records'],2)
        self.assertEqual(r['tlv']['trailingBytes'],7)
        self.assertFalse(r['gameplayStateDecoded'])

    def test_normal_5v5_human_blocks_with_hidden_name_and_no_red_footer(self):
        r=inspect_replay(normal_5v5_fixture())
        self.assertEqual(r['blocksLayout'],'roster-5247758')
        self.assertEqual([b['heroId'] for b in r['blocks']],NORMAL_5V5_HERO_IDS)
        self.assertEqual([(b['camp'],b['position']) for b in r['blocks']],
                         [(1,0),(1,1),(1,2),(1,3),(1,4),(2,0),(2,1),(2,2),(2,3),(2,4)])
        self.assertEqual([b['name'] for b in r['blocks']],NORMAL_5V5_NAMES)
        self.assertTrue(all(not b['bot'] for b in r['blocks']))
        self.assertEqual([b['self'] for b in r['blocks']],[False]*4+[True]+[False]*5)
        self.assertFalse(r['gameplayStateDecoded'])

    def test_double_deflate_and_metadata(self):
        raw,stream=ope_fixture()
        r=parse_ope_bytes(raw)
        self.assertEqual(r['operatorStreamBytes'],len(stream))
        self.assertEqual(r['secondLayerOffset'],0x8B)
        self.assertEqual(r['timestamp'],'2026-10-28 13:55:16')
        self.assertTrue(r['operatorEventsDecoded'])
        events=r['operatorEvents']
        self.assertTrue(events['decoded'])
        self.assertEqual(events['recordCount'],2)
        self.assertEqual(events['tentativeCount'],0)
        self.assertEqual(events['typeCounts']['Common'],1)
        self.assertEqual(events['typeCounts']['UnityFrameOpe'],1)
        self.assertEqual(inspect_replay(abc_fixture(),raw)['pairingStatus'],'user-selected-unverified')

    def test_ope_stream_wall_is_reported_not_hidden(self):
        raw,_=ope_fixture(extra=b'\xfe\x01')
        r=parse_ope_bytes(raw)
        self.assertFalse(r['operatorEventsDecoded'])
        self.assertFalse(r['operatorEvents']['decoded'])
        self.assertIn('无法',r['operatorEvents']['note'])

    def test_truncation_and_trailing_data(self):
        ope,_=ope_fixture()
        for raw in (ope[:3],ope[:-2],ope+b'extra',b'\x02'+ope[1:]):
            with self.assertRaises(ReplayFormatError):parse_ope_bytes(raw)
        for raw in (b'',b'bad replay',abc_fixture()[:25]):
            with self.assertRaises(ReplayFormatError):inspect_replay(raw)

    def test_decompression_size_limit(self):
        with self.assertRaises(ReplayFormatError):
            inflate_raw(deflate(b'x'*4096),'test',128)

    def test_unknown_version_does_not_reuse_offsets(self):
        raw=abc_fixture().replace(b'12.1.1.',b'13.1.1.')
        r=inspect_replay(raw)
        self.assertFalse(r['header']['layoutSupported'])
        self.assertEqual(r['blocks'],[])
        self.assertIsNone(r['header']['localHeroId'])
        with self.assertRaises(ReplayFormatError):
            inspect_replay(raw,ope_fixture()[0])

    def test_broken_block_does_not_invent_lineup(self):
        raw=bytearray(abc_fixture())
        start=674+4*1517
        raw[start+771:start+775]=b'\xff'*4
        self.assertEqual(inspect_replay(bytes(raw))['blocks'],[])

    @unittest.skipUnless(Path('data/replays/samples/20261028_135516.abc').exists(),'Local research sample unavailable')
    def test_research_sample_counts_and_read_only(self):
        p=Path('data/replays/samples/20261028_135516.abc');o=p.with_suffix('.ope')
        abc,ope=p.read_bytes(),o.read_bytes()
        r=inspect_replay(abc,ope)
        self.assertEqual(len(r['blocks']),10)
        self.assertEqual(r['tlv']['records'],2878)
        self.assertEqual(r['ope']['innerSize'],14349)
        self.assertEqual(r['ope']['operatorStreamBytes'],39634)
        self.assertEqual(p.read_bytes(),abc)
        self.assertEqual(o.read_bytes(),ope)

    @unittest.skipUnless(NEW_ABC.exists() and NEW_OPE.exists(),'Local 2026-11-01 sample unavailable')
    def test_new_season_roster_bots_and_frame_stream(self):
        abc,ope=NEW_ABC.read_bytes(),NEW_OPE.read_bytes()
        r=inspect_replay(abc,ope)
        self.assertEqual(r['header']['versions'],['12.1.1.1','12.1.1.26'])
        self.assertEqual(r['header']['builds'],['4989537','5247758'])
        self.assertEqual(r['header']['nickname'],'佚名(*:')
        self.assertEqual(r['header']['localHeroName'],'大禹')
        self.assertEqual(r['blocksLayout'],'roster-5247758')
        self.assertEqual([b['heroId'] for b in r['blocks']],
                         [162,188,154,141,545,121,531,521,114,174])
        self.assertEqual([(b['camp'],b['position']) for b in r['blocks']],
                         [(1,0),(1,1),(1,2),(1,3),(1,4),(2,0),(2,1),(2,2),(2,3),(2,4)])
        self.assertEqual([b['bot'] for b in r['blocks']],
                         [False,False,True,True,True,True,True,True,True,True])
        self.assertEqual([b['order'] for b in r['blocks']],list(range(10)))
        self.assertEqual([b['self'] for b in r['blocks']], [False,True]+[False]*8)
        self.assertEqual(r['tlv']['status'],'not_matched')
        self.assertEqual(r['frames']['status'],'frame-stream')
        self.assertEqual(r['frames']['start'],32783)
        self.assertEqual(r['frames']['records'],9900)
        self.assertEqual(r['frames']['firstSequence'],1)
        # The wire field is a u8 that wraps every 256 records; the report
        # carries the unwrapped frame number plus the raw byte.
        self.assertEqual(r['frames']['lastSequence'],9900)
        self.assertEqual(r['frames']['lastSequenceByte'],172)
        self.assertTrue(r['frames']['sequenceWraps'])
        self.assertEqual(r['scoreTable']['status'],'score-table')
        self.assertEqual(r['scoreTable']['offset'],201226)
        self.assertEqual(r['header']['totalFrameNum'],10063)
        self.assertEqual(r['mvpScore']['winMvpEntityId'],212)
        self.assertEqual(r['mvpScore']['loseMvpEntityIds'],[2007])
        self.assertEqual(r['mvpScore']['winningCamp'],'blue')
        self.assertEqual([e['scoreRaw'] for e in r['scoreTable']['players']],
                         [1355,790,410,580,630,575,410,240,608,598])
        self.assertEqual([b['score'] for b in r['blocks']],
                         [13.55,7.9,4.1,5.8,6.3,5.75,4.1,2.4,6.08,5.98])
        pe=r['playerEvents']
        self.assertEqual(pe['buyEcho']['records'],47)
        self.assertEqual(pe['buyEcho']['unique'],46)
        self.assertEqual(pe['buyEcho']['duplicates'],1)
        self.assertEqual(pe['buyEcho']['byEntity']['212'],{'events':27})
        self.assertEqual(pe['buyEcho']['byEntity']['1804'],{'events':19})
        self.assertEqual(pe['buyEcho']['events'][0],
                         {'frame':111,'offset':34185,'entityId':212,
                          'equipId':1511,'objectId':8,'flag':0})
        self.assertEqual(pe['skills']['unique'],27)
        self.assertEqual(pe['skills']['byEntity']['212'],{'events':15})
        self.assertEqual(pe['positions']['records'],195)
        self.assertEqual(pe['positions']['byEntity']['1804'],
                         {'samples':156,'kinds':{'1':140,'3':16}})
        self.assertEqual(r['blocks'][0]['buyEvents'],27)
        self.assertEqual(r['blocks'][0]['skillEvents'],15)
        self.assertEqual(r['blocks'][0]['positionSamples'],39)
        self.assertEqual(r['ope']['secondLayerMarkerOffset'],0x90)
        self.assertEqual(r['ope']['secondLayerOffset'],0x91)
        self.assertEqual(r['ope']['declaredRemainingBytes'],16098)
        self.assertEqual(r['ope']['operatorStreamBytes'],46900)
        self.assertTrue(r['ope']['operatorEventsDecoded'])
        self.assertEqual(r['ope']['operatorHeaderBytes'],0)
        self.assertGreater(r['ope']['operatorEvents']['recordCount'],9000)
        self.assertEqual(r['ope']['operatorEvents']['streamStart'],0)
        self.assertEqual(r['pairingStatus'],'recorder-tag-matched')
        self.assertEqual(abc,NEW_ABC.read_bytes())
        self.assertEqual(ope,NEW_OPE.read_bytes())

    @unittest.skipUnless(NORMAL_ABC.exists() and NORMAL_OPE.exists(),'Local 2026-11-02 sample unavailable')
    def test_new_season_normal_5v5_ten_humans(self):
        abc,ope=NORMAL_ABC.read_bytes(),NORMAL_OPE.read_bytes()
        r=inspect_replay(abc,ope)
        self.assertEqual(r['blocksLayout'],'roster-5247758')
        self.assertEqual([b['heroId'] for b in r['blocks']],
                         [175,109,167,140,196,199,123,141,153,156])
        self.assertEqual([b['bot'] for b in r['blocks']],[False]*10)
        self.assertEqual([b['self'] for b in r['blocks']],[False]*4+[True]+[False]*5)
        self.assertEqual([b['score'] for b in r['blocks']],
                         [8.4,10.4,9.1,13.1,10.6,5.9,5.4,5.5,3.6,4.9])
        self.assertEqual([b['blockEnd'] for b in r['blocks']],
                         [5226,9749,14746,19023,23938,27955,31868,35888,39739,None])
        self.assertEqual(r['frames']['records'],10509)
        self.assertEqual(r['header']['totalFrameNum'],10674)
        self.assertEqual(r['scoreTable']['offset'],482879)
        self.assertEqual(r['mvpScore']['winMvpEntityId'],538)
        self.assertEqual(r['mvpScore']['loseMvpEntityIds'],[1031])
        self.assertEqual(r['mvpScore']['winningCamp'],'blue')
        self.assertFalse(r['ope']['operatorEventsDecoded'])
        # 30,116-byte "MemoryData" was a false DP jump; the real linear wall is
        # the Common/SendMsg boundary at 0xECDA (see tools/ope_11_2_walls.py).
        self.assertIn('0xecda',r['ope']['operatorEvents']['note'])
        self.assertEqual(r['pairingStatus'],'recorder-tag-matched')

    @unittest.skipUnless(NORMAL2_ABC.exists() and NORMAL2_OPE.exists(),'Local 2026-11-02 sample unavailable')
    def test_normal_5v5_hidden_name_and_red_blocks_without_footer(self):
        abc,ope=NORMAL2_ABC.read_bytes(),NORMAL2_OPE.read_bytes()
        r=inspect_replay(abc,ope)
        self.assertEqual([b['heroId'] for b in r['blocks']],
                         [166,538,108,152,196,175,107,142,123,132])
        self.assertEqual(r['blocks'][0]['name'],'信则\u2060\u2061有\u2062')
        self.assertEqual([b['bot'] for b in r['blocks']],[False]*10)
        self.assertEqual([b['blockEnd'] for b in r['blocks']],
                         [6303,10962,15123,19931,24846,28680,32452,35933,39437,None])
        self.assertEqual(r['frames']['records'],15379)
        self.assertEqual(r['header']['totalFrameNum'],15540)
        self.assertEqual(r['scoreTable']['offset'],741847)
        self.assertEqual(r['mvpScore']['winMvpEntityId'],1367)
        self.assertEqual(r['mvpScore']['loseMvpEntityIds'],[1279])
        self.assertEqual(r['mvpScore']['winningCamp'],'blue')
        self.assertEqual(r['pairingStatus'],'recorder-tag-matched')
