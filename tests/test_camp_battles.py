"""Regression tests for the camp ``battle`` key-event parser.

Bug: ``_key_event()`` used to read ``dtData`` for *every* key event.  Only
``dragontower`` rows have ``dtData``; ``battle`` rows carry ``battle`` and
``battleDetail`` instead, so all team fights were flattened to
``timeSec=0 / kills=[]`` and the per-kill hero ledger was lost.
"""
import json
import unittest
from pathlib import Path

from camp_replay import _battles, _key_event

ROOT = Path(__file__).resolve().parent.parent


def _raw():
    return {
        'playBaseInfoArr': [
            {'acntCamp': '1', 'playID': 'p1', 'heroID': 112, 'inBattleObjID': '1001',
             'deathPosArr': [{'coordX': 27, 'coordY': -12, 'time': '485'}]},
            {'acntCamp': '2', 'playID': 'p2', 'heroID': 515, 'inBattleObjID': '2001',
             'deathPosArr': []},
        ],
        'matchInfo': [
            {'playerId': 'p1', 'heroName': '鲁班七号', 'killCnt': '1',
             'deadCnt': '0', 'assistCnt': '0'},
            {'playerId': 'p2', 'heroName': '嫦娥', 'killCnt': '0',
             'deadCnt': '1', 'assistCnt': '0'},
        ],
        'keyEventArr': [
            {'eventType': 'battle',
             'battle': {'fightId': '7', 'startTime': '650000', 'endTime': '656000',
                        'firstKillerCamp': '1', 'camp1MemNum': 1, 'camp2MemNum': 1,
                        'joinMemInfo': [{'camp': '1', 'objID': '1001',
                                        'time': '652000', 'isBeginner': 1}],
                        'killInfo': [{'camp': '2', 'objID': '2001', 'time': '655000',
                                      'killerCamp': '1', 'killerObjID': '1001'}]},
             'battleDetail': [
                 {'fightId': '7', 'camp': '1', 'objID': '1001', 'isSupport': '0',
                  'killCnt': '1', 'deadCnt': '0', 'assistCnt': '0',
                  'hurtTotal': '5200', 'behurtTotal': '800',
                  'hardctrlTotal': '300', 'softctrlTotal': '0', 'therapicTotal': '0',
                  'lowHP': '3000', 'beginHP': '5000', 'endHP': '4200',
                  'ultimateskillCnt': '1'}]},
            {'eventType': 'dragontower',
             'dtData': {'dtType': '2', 'dtID': '20', 'dtCamp': '2',
                        'killTime': '660000', 'killerId': '1001',
                        'killerCamp': '1', 'kills': []}},
        ],
    }


class CampBattlesTest(unittest.TestCase):

    def test_battle_key_event_keeps_real_timestamp(self):
        event = _key_event(_raw()['keyEventArr'][0])
        self.assertEqual(event['eventType'], 'battle')
        self.assertEqual(event['timeSec'], 650.0)
        self.assertEqual(event['endSec'], 656.0)
        self.assertEqual(event['fightId'], '7')
        self.assertEqual(event['killCount'], 1)

    def test_dragontower_key_event_unchanged(self):
        event = _key_event(_raw()['keyEventArr'][1])
        self.assertEqual(event['timeSec'], 660.0)
        self.assertEqual(event['dtType'], '2')

    def test_battles_extracts_kills_details_and_deaths(self):
        battles = _battles(_raw())
        self.assertEqual(battles['schema'], 'camp-battles-v1')
        self.assertEqual(battles['counts'], {'fights': 1, 'heroKills': 1,
                                             'fightRows': 1, 'deathPoints': 1})
        fight = battles['fights'][0]
        self.assertEqual(fight['startSec'], 650.0)
        self.assertEqual(fight['kills'][0]['timeSec'], 655.0)
        self.assertEqual(fight['kills'][0]['killer'], '1001')
        self.assertEqual(fight['kills'][0]['victim'], '2001')
        self.assertEqual(fight['details'][0]['hurt'], 5200)
        self.assertEqual(fight['details'][0]['hardCtrl'], 300)
        self.assertEqual(battles['deaths'][0],
                         {'objID': '1001', 'camp': '1', 'heroId': 112,
                          'x': 27, 'y': -12, 'timeSec': 485})
        self.assertEqual(battles['playerMap']['1001']['hero'], '鲁班七号')
        # Account ids must never leak into derived assets.
        self.assertNotIn('playId', battles['playerMap']['1001'])
        self.assertNotIn('playerId', battles['playerMap']['1001'])

    def test_real_raw_kill_ledger_matches_final_panel(self):
        files = sorted((ROOT / 'data' / 'official_replays').glob('camp-*/raw.json'))
        if not files:
            self.skipTest('no local camp replay assets')
        for path in files[:5]:
            with self.subTest(replay=path.parent.name):
                data = json.loads(path.read_text(encoding='utf-8'))['data']
                battles = _battles(data)
                panel_kills = sum(int(p.get('killCnt') or 0)
                                  for p in data.get('matchInfo') or [])
                self.assertEqual(battles['counts']['heroKills'], panel_kills)


if __name__ == '__main__':
    unittest.main()
