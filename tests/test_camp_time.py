"""营地时间换算：dtEventTime 是记录发送时间，开赛时间要减去 usedTime。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from camp_time import camp_times


def detail(event='1793804938', used=838):
    return {'_campEntry': {'dtEventTime': event, 'usedTime': used},
            'data': {'battle': {'usedTime': used}}}


class CampTimesTests(unittest.TestCase):

    def test_event_and_start_are_both_beijing_time(self):
        times = camp_times(detail())
        self.assertEqual(times['eventAt'], '2026-11-04T23:08:58+08:00')
        self.assertEqual(times['startedAt'], '2026-11-04T22:55:00+08:00')
        self.assertEqual(times['date'], '2026-11-04')
        self.assertEqual(times['durationSec'], 838)

    def test_millisecond_timestamp_is_normalized(self):
        times = camp_times(detail(event='1793804938000'))
        self.assertEqual(times['startedAt'], '2026-11-04T22:55:00+08:00')

    def test_used_time_prefers_entry_and_falls_back_to_battle(self):
        entry_only = {'_campEntry': {'dtEventTime': '1793804938'}, 'data': {'battle': {}}}
        self.assertEqual(camp_times(entry_only)['startedAt'], '2026-11-04T23:08:58+08:00')
        battle_only = {'_campEntry': {'dtEventTime': '1793804938'},
                       'data': {'battle': {'usedTime': '838'}}}
        self.assertEqual(camp_times(battle_only)['startedAt'], '2026-11-04T22:55:00+08:00')

    def test_missing_epoch_returns_empty(self):
        self.assertEqual(camp_times({'data': {'battle': {'usedTime': 800}}}), {})
        self.assertEqual(camp_times({'data': {'battle': {'usedTime': 800}},
                                     '_campEntry': {'dtEventTime': '11-04 22:55'}}), {})


if __name__ == '__main__':
    unittest.main()
