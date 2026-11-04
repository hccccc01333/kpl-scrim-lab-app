import json
import math
import unittest

from runtime_data import MAX_BYTES, RuntimeDataError, analyze_jsonl, parse_jsonl


def player(player_id, camp, slot, hero=100, **stats):
    value = {'playerId': player_id, 'camp': camp, 'slot': slot, 'heroId': hero}
    value.update(stats)
    return value


def frame(number, time, players):
    return {'type': 'frame', 'frame': number, 'time': time, 'players': players}


def lines(*values):
    return ('\n'.join(json.dumps(value, ensure_ascii=False) for value in values) + '\n').encode()


class RuntimeDataTests(unittest.TestCase):
    def full_frame(self, number, time, gold_scale=1):
        blue = [
            player('b1', 'blue', 0, 101, kills=2, deaths=1, assists=3, gold=1200 * gold_scale,
                   exp=2400, damageDealt=6000, damageTaken=3000),
            player('b2', 'blue', 1, 102, kills=3, deaths=0, assists=1, gold=800 * gold_scale,
                   exp=1600, damageDealt=3000, damageTaken=2000),
            player('b3', 'blue', 2, 103, kills=0, deaths=2, assists=2, gold=600 * gold_scale,
                   exp=1200, damageDealt=1000, damageTaken=4000),
            player('b4', 'blue', 3, 104, kills=0, deaths=1, assists=4, gold=600 * gold_scale,
                   exp=1200, damageDealt=1000, damageTaken=2500),
            player('b5', 'blue', 4, 105, kills=0, deaths=0, assists=5, gold=400 * gold_scale,
                   exp=800, damageDealt=1000, damageTaken=1000),
        ]
        red = [
            player(f'r{index + 1}', 'red', index, 200 + index, kills=0, deaths=1, assists=0,
                   gold=500 * gold_scale, exp=1000, damageDealt=1000, damageTaken=1000)
            for index in range(5)
        ]
        return frame(number, time, blue + red)

    def test_full_match_metrics(self):
        data = lines(
            {'type': 'meta', 'schema': 'kpl-runtime-v1', 'source': 'gamecore-shm'},
            self.full_frame(0, 0, 0),
            self.full_frame(120, 120, 1),
            {'type': 'event', 'frame': 30, 'time': 30, 'event': 'skill_use', 'playerId': 'b1', 'camp': 'blue', 'skillSlot': 1},
            {'type': 'event', 'frame': 31, 'time': 31, 'event': 'skill_use', 'playerId': 'b1', 'camp': 'blue', 'skillSlot': 1},
            {'type': 'event', 'frame': 32, 'time': 32, 'event': 'skill_use', 'playerId': 'b1', 'camp': 'blue', 'skillSlot': 2},
            {'type': 'event', 'frame': 33, 'time': 33, 'event': 'skill_hit', 'playerId': 'b1', 'camp': 'blue', 'skillSlot': 1},
            {'type': 'event', 'frame': 34, 'time': 34, 'event': 'skill_hit', 'playerId': 'b1', 'camp': 'blue', 'skillSlot': 2},
            {'type': 'event', 'frame': 35, 'time': 35, 'event': 'kill', 'playerId': 'b1', 'targetId': 'r1', 'camp': 'blue'},
        )
        result = analyze_jsonl(data)
        self.assertEqual(result['schema'], 'kpl-runtime-v1')
        self.assertEqual(result['coverage']['frames'], 2)
        self.assertEqual(result['coverage']['players'], 10)
        self.assertEqual(result['coverage']['timeBasis'], 'time')
        self.assertAlmostEqual(result['coverage']['durationSec'], 120)
        self.assertEqual(result['teams']['blue']['complete'], True)
        self.assertEqual(result['teams']['blue']['totals']['gold'], 3600)
        self.assertAlmostEqual(result['teams']['blue']['perMinute']['gold'], 1800)
        self.assertEqual(result['teams']['red']['totals']['kills'], 0)
        first = next(p for p in result['players'] if p['playerId'] == 'b1')
        self.assertAlmostEqual(first['metrics']['kda'], 5.0)
        self.assertAlmostEqual(first['metrics']['gpm'], 600)
        self.assertAlmostEqual(first['metrics']['xpm'], 1200)
        self.assertAlmostEqual(first['metrics']['participation'], 100)
        self.assertAlmostEqual(first['metrics']['damageShare'], 6000 / 12000 * 100)
        self.assertAlmostEqual(result['events']['skillHitRate'], 200 / 3)
        self.assertEqual(result['events']['counts']['kill'], 1)
        self.assertEqual(len(result['timeline']), 2)
        self.assertEqual(result['timeline'][-1]['blueGold'], 3600)
        self.assertEqual(result['warnings'], [])

    def test_player_lines_and_header_optional(self):
        data = lines(
            {'type': 'player', 'frame': 0, 'time': 0, 'playerId': 'x', 'heroId': 7, 'camp': 'blue', 'gold': 60},
            {'type': 'player', 'frame': 60, 'time': 60, 'playerId': 'x', 'heroId': 7, 'camp': 'blue', 'gold': 120},
        )
        result = analyze_jsonl(data)
        self.assertEqual(result['coverage']['frames'], 2)
        self.assertEqual(result['coverage']['players'], 1)
        self.assertEqual(result['players'][0]['metrics']['gpm'], 120)
        self.assertFalse(result['teams']['blue']['complete'])
        self.assertIsNone(result['teams']['blue']['totals']['gold'])
        self.assertEqual(result['teams']['blue']['partial']['gold'], 120)

    def test_missing_time_uses_frame_basis(self):
        data = lines(frame(60, None, [player('b1', 'blue', 0, gold=120)]))
        result = analyze_jsonl(data)
        self.assertEqual(result['coverage']['timeBasis'], 'frame/30')
        self.assertAlmostEqual(result['coverage']['durationSec'], 2)
        self.assertIn('没有 time 字段，按 30fps 估算时长', result['warnings'])

    def test_events_only(self):
        data = lines({'type': 'event', 'frame': 10, 'event': 'dragon', 'camp': 'blue'})
        result = analyze_jsonl(data)
        self.assertEqual(result['coverage']['frames'], 0)
        self.assertEqual(result['coverage']['players'], 0)
        self.assertEqual(result['events']['counts']['dragon'], 1)
        self.assertIn('只有事件，没有帧数据，队员指标未计算', result['warnings'])

    def test_invalid_rows(self):
        cases = [
            (b'', '没有可分析'),
            (lines({'type': 'event', 'frame': 1, 'event': 'unknown'}), '未知事件类型'),
            (lines(frame(1, 1, [player('a', 'blue', 0), player('a', 'red', 1)])), 'playerId 重复'),
            (lines(frame(1, 1, [player('a', 'blue', 0, gold=-1)])), 'gold 超出范围'),
            (lines({'type': 'frame', 'frame': True, 'players': [player('a', 'blue', 0)]}), 'frame 必须是整数'),
            (lines(frame(1, 1, [{'playerId': 'a', 'camp': 'blue'}])), 'heroId 缺失'),
            (lines({'type': 'meta', 'schema': 'other'}), 'schema'),
        ]
        for data, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(RuntimeDataError, message):
                    parse_jsonl(data)

    def test_bad_time_and_camp(self):
        with self.assertRaisesRegex(RuntimeDataError, 'time 不一致'):
            parse_jsonl(lines(
                frame(1, 1, [player('a', 'blue', 0)]),
                frame(1, 2, [player('b', 'blue', 1)]),
            ))
        with self.assertRaisesRegex(RuntimeDataError, 'camp'):
            parse_jsonl(lines(frame(1, 1, [player('a', 'green', 0)])))

    def test_size_limit(self):
        with self.assertRaisesRegex(RuntimeDataError, '8 MB'):
            parse_jsonl(b'x' * (MAX_BYTES + 1))

    def test_kda_with_zero_deaths(self):
        result = analyze_jsonl(lines(frame(1, 1, [player('a', 'blue', 0, kills=2, deaths=0, assists=1)])))
        self.assertAlmostEqual(result['players'][0]['metrics']['kda'], 3)
        self.assertTrue(result['players'][0]['metrics']['kdaPerfect'])

    def test_timeline_downsampled(self):
        frames = [frame(index, index, [player(f'b{slot}', 'blue', slot, gold=index * 10 + slot) for slot in range(5)] +
                        [player(f'r{slot}', 'red', slot, gold=index * 10 + slot) for slot in range(5)])
                  for index in range(300)]
        result = analyze_jsonl(lines(*frames))
        self.assertLessEqual(len(result['timeline']), 120)
        self.assertEqual(result['timeline'][0]['frame'], 0)
        self.assertEqual(result['timeline'][-1]['frame'], 299)

    def test_zero_duration_warns(self):
        result = analyze_jsonl(lines(frame(0, 0, [player('a', 'blue', 0, gold=60)])))
        self.assertIn('时长为 0，分均指标按 1 秒估算', result['warnings'])
        self.assertEqual(result['players'][0]['metrics']['gpm'], 3600)

    def test_numbers_are_finite(self):
        data = lines(frame(1, 1, [player('a', 'blue', 0, gold=1)]))
        result = analyze_jsonl(data)
        for value in result['players'][0]['metrics'].values():
            if isinstance(value, float):
                self.assertTrue(math.isfinite(value))


if __name__ == '__main__':
    unittest.main()
