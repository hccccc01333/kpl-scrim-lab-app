"""Skill ledger decode tests on a synthetic record stream (no game assets).

The fixture builds the same ID1075 container the product reads, so the tests
pin the two id spaces (roster entity id vs the small battle-object id learned
from LEARNSKILL) without shipping any original replay.
"""
import copy
import csv
import io
import os
import struct
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault('TRAINING_DB', str(ROOT / 'test-results' / f'test-ledger-{uuid.uuid4().hex}.sqlite3'))

from replay_fixtures import abc_fixture, inputs_5v5_fixture  # noqa: E402
from tools.replay_skill_ledger import (CSV_COLUMNS, EngineOutcomeError,  # noqa: E402
                                       attach_engine_outcomes, cast_rows,
                                       engine_outcomes_summary, skill_ledger,
                                       write_csv)

ENTITY = {8: 1000, 9: 1001, 10: 1002, 11: 1003, 12: 1004,
          16: 1005, 17: 1006, 18: 1007, 19: 1008, 20: 1009}
OBJECT = {8: 12, 9: 25, 10: 65, 11: 58, 12: 44,
          16: 33, 17: 8, 18: 20, 19: 37, 20: 51}


def entry(sync_type, entity, payload):
    return b'\x02' + entity.to_bytes(2, 'big') + bytes([sync_type]) + payload


def learn(entity, object_id, slot=1, level=0, auto=0):
    return entry(135, entity, struct.pack('>IBBB', object_id, slot, level, auto))


def targeted(entity, slot, object_id, seq, drag=0):
    return entry(128, entity, struct.pack('>biBHI', slot, object_id, 0, seq, drag))


def directional(entity, slot, degree, seq, drag=0):
    return entry(129, entity, struct.pack('>bhIiiiHB', slot, degree, 0, 0, 0, 0, seq, drag))


def positioned(entity, slot, x, y, seq, drag=0):
    return entry(130, entity, struct.pack('>biiHIB', slot, x, y, seq, 0, drag))


def frame(*entries):
    return bytes([len(entries)]) + b''.join(entries)


LEARN_FRAME = frame(*[learn(ENTITY[unit], OBJECT[unit], slot=1) for unit in sorted(ENTITY)])
CAST_FRAMES = (
    frame(targeted(ENTITY[8], 1, OBJECT[16], 1),        # enemy hero (camp 2)
          targeted(ENTITY[8], 1, OBJECT[8], 2)),        # self
    frame(targeted(ENTITY[8], 2, 4092, 3),              # non-hero object
          directional(ENTITY[8], 2, 9000, 4)),          # aim 90.0 deg
    frame(targeted(ENTITY[8], 7, OBJECT[8], 5),          # non-kit slot
          positioned(ENTITY[16], 3, 1000, -2000, 1)),    # ground target point
)


class SkillLedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = skill_ledger(inputs_5v5_fixture((LEARN_FRAME,) + CAST_FRAMES))

    def test_01_decodes_every_frame(self):
        self.assertEqual(self.report['status'], 'decoded')
        self.assertEqual(self.report['tier'], 'file-decode')
        self.assertEqual(self.report['frameRecords'], 4)
        self.assertEqual(self.report['unresolvedFrames'], 0)
        self.assertEqual(self.report['entryCounts']['LEARNSKILL'], 10)
        self.assertEqual(self.report['census']['total'], 6)

    def test_02_object_pool_pins_one_id_per_hero(self):
        pool = self.report['objectPool']
        self.assertEqual(len(pool), 10)
        self.assertEqual(pool[str(ENTITY[8])], OBJECT[8])
        self.assertEqual(pool[str(ENTITY[16])], OBJECT[16])
        self.assertEqual(self.report['ambiguousObjects'], [])

    def test_03_targeted_cast_resolves_enemy_hero(self):
        enemy = self.report['casts'][0]
        self.assertEqual(enemy['unit'], 8)
        self.assertEqual(enemy['castType'], 'targeted')
        self.assertEqual(enemy['target']['kind'], 'enemy-hero')
        self.assertEqual(enemy['target']['unit'], 16)
        self.assertEqual(enemy['target']['camp'], 2)

    def test_04_targeted_cast_resolves_self_and_non_hero(self):
        casts = self.report['casts']
        self.assertEqual(casts[1]['target']['kind'], 'self-anchor')
        self.assertEqual(casts[1]['target']['unit'], 8)
        self.assertEqual(casts[2]['target']['kind'], 'other-object')
        self.assertEqual(casts[2]['target']['objectId'], 4092)

    def test_05_directional_degree_is_centi_degrees(self):
        cast = self.report['casts'][3]
        self.assertEqual(cast['castType'], 'directional')
        self.assertEqual(cast['aimRaw'], 9000)
        self.assertEqual(cast['aimDeg'], 90.0)
        self.assertEqual(cast['target']['kind'], 'none')

    def test_06_position_cast_keeps_ground_point(self):
        cast = self.report['casts'][5]
        self.assertEqual(cast['castType'], 'position')
        self.assertEqual(cast['unit'], 16)
        self.assertEqual((cast['aimX'], cast['aimY']), (1000, -2000))

    def test_07_hero_summary_splits_kit_from_non_kit_slots(self):
        by_unit = {row['unit']: row for row in self.report['heroes']}
        zhongkui = by_unit[8]
        self.assertEqual(zhongkui['objectId'], OBJECT[8])
        self.assertEqual(zhongkui['casts']['total'], 5)
        self.assertEqual(zhongkui['casts']['byType'], {'targeted': 4, 'directional': 1})
        self.assertEqual(zhongkui['casts']['kit'], 4)
        self.assertEqual(zhongkui['casts']['nonKit'], 1)
        self.assertEqual(zhongkui['targets'],
                         {'self-anchor': 2, 'ally-hero': 0, 'enemy-hero': 1,
                          'other-object': 1, 'none': 0})
        self.assertEqual(zhongkui['targetsBySlot']['1']['self-anchor'], 1)
        self.assertEqual(zhongkui['targetsBySlot']['1']['enemy-hero'], 1)
        self.assertEqual(by_unit[16]['casts']['byType'], {'position': 1})

    def test_08_counter_completeness_is_reported_not_hidden(self):
        by_unit = {row['unit']: row for row in self.report['heroes']}
        self.assertTrue(by_unit[8]['counter']['complete'])
        self.assertEqual(by_unit[8]['counter']['maxSeq'], 5)
        lossy = skill_ledger(inputs_5v5_fixture((
            LEARN_FRAME,
            frame(targeted(ENTITY[8], 1, OBJECT[8], 1),
                  targeted(ENTITY[8], 1, OBJECT[8], 3)),
        )))
        unit8 = {row['unit']: row for row in lossy['heroes']}[8]
        self.assertFalse(unit8['counter']['complete'])
        self.assertEqual(unit8['counter']['maxSeq'], 3)
        self.assertEqual(unit8['counter']['casts'], 2)

    def test_09_catalog_attaches_skill_names_without_inventing_them(self):
        report = skill_ledger(inputs_5v5_fixture((LEARN_FRAME,) + CAST_FRAMES),
                              {166: {1: '测试技能'}})
        named = [row['skillName'] for row in report['casts'] if row['unit'] == 8]
        self.assertEqual(named[0], '测试技能')     # slot 1
        self.assertIsNone(named[2])               # slot 2 stays unnamed
        self.assertTrue(all(row['skillName'] is None for row in self.report['casts']))

    def test_10_csv_rows_are_flat(self):
        rows = list(cast_rows(self.report))
        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[0]['target_kind'], 'enemy-hero')
        self.assertEqual(rows[0]['target_unit'], 16)
        self.assertEqual(rows[3]['aim_deg'], 90.0)
        self.assertEqual(rows[5]['aim_x'], 1000)

    def test_11_container_without_record_stream_reports_the_wall(self):
        report = skill_ledger(abc_fixture())
        self.assertEqual(report['status'], 'no-record-stream')
        self.assertTrue(report['error'])
        self.assertEqual(report['casts'], [])


class EngineOutcomeTests(unittest.TestCase):
    """Engine-measured layer: attach contract, fail-closed checks, CSV cells.

    The engine tier is *not* decoded here: these tests feed synthetic paused-
    frame measurements and pin that unknown data is rejected instead of being
    guessed onto a cast, and that missing stays null (never 0).
    """

    @classmethod
    def setUpClass(cls):
        cls.report = skill_ledger(inputs_5v5_fixture((LEARN_FRAME,) + CAST_FRAMES))
        cls.keys = [(cast['frame'], cast['offset']) for cast in cls.report['casts']]
        cls.k0, cls.k1, cls.k2 = cls.keys[0], cls.keys[1], cls.keys[2]

    @staticmethod
    def _row(key, **fields):
        row = {'frame': key[0], 'offset': key[1]}
        row.update(fields)
        return row

    def test_01_defaults_stay_null_and_tier_unchanged(self):
        self.assertEqual(self.report['tier'], 'file-decode')
        self.assertTrue(all(cast['engine'] is None for cast in self.report['casts']))
        summary = engine_outcomes_summary(self.report)
        self.assertEqual(summary['tier'], 'engine-measured')
        self.assertEqual(summary['source'], 'engine-memory')
        self.assertEqual(summary['confidence'], 'measured')
        self.assertEqual(summary['castsMeasured'], 0)
        self.assertEqual(summary['castsTotal'], 6)
        self.assertIn('未挂载', summary['note'])

    def test_02_attach_engine_blocks_by_stable_key(self):
        outcomes = {'casts': [
            self._row(self.k0,
                      hit={'hit': True, 'target': 'enemy-hero',
                           'evidence': 'unit+0x1664 hit flag'},
                      control={'durationS': 0.8, 'target': {'kind': 'enemy-hero', 'unit': 16}},
                      observedAt={'frame': self.k0[0] + 1, 'clockMs': 280866,
                                  'snapshot': 'snap_pause_1'},
                      notes=['暂停帧读 unit 对象 +0x1664']),
            self._row(self.k1, shield={'amount': 320, 'target': 'self-anchor'},
                      observedAt={'clockMs': 280900, 'snapshot': 'snap_pause_1'}),
            self._row(self.k2, hit={'hit': False, 'target': 'other-object'},
                      observedAt={'snapshot': 'snap_pause_1'}),
        ]}
        attached = attach_engine_outcomes(self.report, outcomes)
        block = attached['casts'][0]['engine']
        self.assertEqual((block['tier'], block['source'], block['confidence']),
                         ('engine-measured', 'engine-memory', 'measured'))
        self.assertEqual(block['hit']['hit'], True)
        self.assertEqual(block['hit']['target'], 'enemy-hero')
        self.assertEqual(block['control']['durationS'], 0.8)
        self.assertEqual(block['control']['target'], {'kind': 'enemy-hero', 'unit': 16})
        self.assertIsNone(block['shield'])          # absent measurement is null
        self.assertEqual(block['observedAt']['clockMs'], 280866)
        self.assertEqual(block['notes'], ['暂停帧读 unit 对象 +0x1664'])
        self.assertIsNone(attached['casts'][3]['engine'])   # not measured -> null
        self.assertEqual(attached['casts'][2]['engine']['hit'],
                         {'hit': False, 'target': 'other-object', 'evidence': None})
        self.assertEqual(attached['engineOutcomes']['castsMeasured'], 3)
        self.assertEqual(attached['engineOutcomes']['castsTotal'], 6)
        self.assertEqual(engine_outcomes_summary(attached)['castsMeasured'], 3)

    def test_03_mapping_string_and_tuple_keys_are_accepted(self):
        outcomes = {f'{self.k0[0]}:{self.k0[1]}': {
                        'hit': {'hit': True, 'target': {'kind': 'enemy-hero', 'unit': 16}},
                        'observedAt': {'snapshot': 'snap_a'}},
                    (self.k1[0], self.k1[1]): {
                        'shield': {'amount': 0, 'target': 'self-anchor'},
                        'observedAt': {'snapshot': 'snap_a'}}}
        attached = attach_engine_outcomes(self.report, outcomes)
        self.assertEqual(attached['casts'][0]['engine']['hit']['target'],
                         {'kind': 'enemy-hero', 'unit': 16})
        self.assertEqual(attached['engineOutcomes']['castsMeasured'], 2)

    def test_04_unknown_and_duplicate_keys_are_rejected(self):
        with self.assertRaises(EngineOutcomeError):
            attach_engine_outcomes(self.report, {
                f'{self.k0[0]}:{self.k0[1] + 1}': {
                    'hit': {'hit': True}, 'observedAt': {'snapshot': 'snap_x'}}})
        with self.assertRaises(EngineOutcomeError):
            attach_engine_outcomes(self.report, [
                self._row(self.k0, hit={'hit': True}, observedAt={'snapshot': 'snap_x'}),
                self._row(self.k0, shield={'amount': 1}, observedAt={'snapshot': 'snap_x'})])
        attached = attach_engine_outcomes(self.report, [
            self._row(self.k0, hit={'hit': True}, observedAt={'snapshot': 'snap_x'})])
        with self.assertRaises(EngineOutcomeError):   # never overwrite an existing block
            attach_engine_outcomes(attached, [
                self._row(self.k0, hit={'hit': False}, observedAt={'snapshot': 'snap_y'})])

    def test_05_unknown_fields_and_invalid_payloads_are_rejected(self):
        cases = {
            'unknown outcome field': {'casts': [self._row(
                self.k0, observedAt={'snapshot': 'x'}, damage={'amount': 1})]},
            'unknown hit field': {'casts': [self._row(
                self.k0, hit={'hit': True, 'note': 'x'}, observedAt={'snapshot': 'x'})]},
            'all-null sampled block': {'casts': [self._row(self.k0)]},
            'missing observedAt': {'casts': [self._row(self.k0, hit={'hit': True})]},
            'empty observedAt': {'casts': [self._row(
                self.k0, hit={'hit': True}, observedAt={})]},
            'tier spoofing': {'tier': 'file-decode', 'casts': []},
            'missing offset': {'casts': [{'frame': self.k0[0],
                                          'hit': {'hit': True},
                                          'observedAt': {'snapshot': 'x'}}]},
            'negative shield': {'casts': [self._row(
                self.k0, shield={'amount': -1}, observedAt={'snapshot': 'x'})]},
            'negative control': {'casts': [self._row(
                self.k0, control={'durationS': -0.5}, observedAt={'snapshot': 'x'})]},
            'bad key string': {'casts': [{'frame': 'x', 'offset': 1,
                                          'hit': {'hit': True},
                                          'observedAt': {'snapshot': 'x'}}]},
            'bad mapping key': {'12:notanint': {'hit': {'hit': True},
                                                'observedAt': {'snapshot': 'x'}}},
        }
        for name, case in cases.items():
            with self.subTest(name), self.assertRaises(EngineOutcomeError):
                attach_engine_outcomes(self.report, case)

    def test_06_attach_is_pure_and_order_preserving(self):
        report_before = copy.deepcopy(self.report)
        outcomes = {'casts': [self._row(
            self.k0, hit={'hit': True}, observedAt={'snapshot': 'snap_pure'})]}
        outcomes_before = copy.deepcopy(outcomes)
        attached = attach_engine_outcomes(self.report, outcomes)
        self.assertEqual(self.report, report_before)      # input untouched
        self.assertEqual(outcomes, outcomes_before)       # outcomes untouched
        self.assertEqual([cast['frame'] for cast in attached['casts']],
                         [cast['frame'] for cast in self.report['casts']])
        attached['casts'][0]['engine']['notes'].append('later edit')
        self.assertEqual(outcomes, outcomes_before)       # no write-through

    def test_07_csv_columns_carry_engine_measurements(self):
        outcomes = {'casts': [
            self._row(self.k0,
                      hit={'hit': True, 'target': 'enemy-hero'},
                      shield={'amount': 0, 'target': 'self-anchor'},
                      control={'durationS': 1.25,
                               'target': {'kind': 'enemy-hero', 'unit': 16}},
                      observedAt={'frame': 42, 'clockMs': 700, 'snapshot': 'snap_csv'}),
            self._row(self.k2, hit={'hit': False},
                      observedAt={'snapshot': 'snap_csv'}),
        ]}
        for column in ('engine_hit', 'engine_hit_target', 'engine_shield',
                       'engine_shield_target', 'engine_control_s',
                       'engine_control_target', 'engine_observed_frame',
                       'engine_observed_clock_ms', 'engine_snapshot'):
            self.assertIn(column, CSV_COLUMNS)
        attached = attach_engine_outcomes(self.report, outcomes)
        rows = list(cast_rows(attached))
        self.assertEqual(rows[0]['engine_hit'], 1)
        self.assertEqual(rows[0]['engine_hit_target'], 'enemy-hero')
        self.assertEqual(rows[0]['engine_shield'], 0)      # measured 0 is a value
        self.assertEqual(rows[0]['engine_control_s'], 1.25)
        self.assertEqual(rows[0]['engine_control_target'],
                         '{"kind": "enemy-hero", "unit": 16}')
        self.assertEqual(rows[0]['engine_observed_clock_ms'], 700)
        self.assertEqual(rows[0]['engine_snapshot'], 'snap_csv')
        self.assertEqual(rows[2]['engine_hit'], 0)         # measured miss
        self.assertEqual(rows[1]['engine_hit'], '')        # not measured -> empty
        self.assertEqual(rows[1]['engine_shield'], '')
        self.assertEqual(rows[3]['engine_hit'], '')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'ledger.csv'
            self.assertEqual(write_csv(attached, path), 6)
            text = path.read_text(encoding='utf-8-sig')
        header = list(csv.reader(io.StringIO(text)))[0]
        self.assertEqual(header, list(CSV_COLUMNS))
        written = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(written[0]['engine_hit'], '1')
        self.assertEqual(written[0]['engine_snapshot'], 'snap_csv')
        self.assertEqual(written[1]['engine_hit'], '')
        self.assertEqual(written[1]['engine_snapshot'], '')


class SkillLedgerApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from server import app
        cls.client = TestClient(app, base_url='http://localhost')
        uploaded = cls.client.post('/api/replays/files?name=ledger-fixture.abc',
                                   content=inputs_5v5_fixture((LEARN_FRAME,) + CAST_FRAMES))
        assert uploaded.status_code == 200, uploaded.text
        cls.replay_id = uploaded.json()['id']
        imported = cls.client.post('/api/replays/import',
                                   json={'abcFileId': cls.replay_id})
        assert imported.status_code == 200, imported.text

    def test_01_ledger_endpoint_serves_casts_and_census(self):
        response = self.client.get(f'/api/replays/{self.replay_id}/skill-ledger')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'decoded')
        self.assertEqual(data['tier'], 'file-decode')
        self.assertEqual(data['census']['total'], 6)
        self.assertEqual(len(data['casts']), 6)
        self.assertEqual(data['casts'][0]['target']['kind'], 'enemy-hero')
        self.assertEqual(data['provenance']['casts']['tier'], 'file-decode')
        self.assertTrue(data['limitations'])

    def test_02_unit_filter_returns_one_heroes_casts(self):
        response = self.client.get(f'/api/replays/{self.replay_id}/skill-ledger?unit=8')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['hero']['unit'], 8)
        self.assertEqual(data['castsTotal'], 5)
        self.assertTrue(all(cast['unit'] == 8 for cast in data['casts']))
        self.assertEqual(data['hero']['casts']['kit'], 4)

    def test_03_unknown_unit_and_missing_replay(self):
        self.assertEqual(self.client.get(
            f'/api/replays/{self.replay_id}/skill-ledger?unit=13').status_code, 404)
        self.assertEqual(self.client.get(
            '/api/replays/missing-id/skill-ledger').status_code, 404)

    def test_04_provenance_declares_engine_tier_without_data(self):
        data = self.client.get(
            f'/api/replays/{self.replay_id}/skill-ledger').json()
        engine = data['provenance']['engine']
        self.assertEqual(engine['tier'], 'engine-measured')
        self.assertEqual(engine['source'], 'engine-memory')
        self.assertEqual(engine['confidence'], 'measured')
        self.assertEqual(engine['castsMeasured'], 0)
        self.assertEqual(engine['castsTotal'], 6)
        self.assertIn('未挂载', engine['note'])
        self.assertTrue(all(cast['engine'] is None for cast in data['casts']))
        # provenance is additive: the file-decode entries keep their tier
        self.assertEqual(data['provenance']['casts']['tier'], 'file-decode')
        self.assertEqual(data['tier'], 'file-decode')

    def test_05_attached_engine_blocks_pass_through_api_and_unit_filter(self):
        import tools.replay_skill_ledger as ledger_module
        fixture = inputs_5v5_fixture((LEARN_FRAME,) + CAST_FRAMES)
        base = ledger_module.skill_ledger(fixture)
        first = base['casts'][0]
        outcomes = {'casts': [{'frame': first['frame'], 'offset': first['offset'],
                               'hit': {'hit': True, 'target': 'enemy-hero'},
                               'observedAt': {'frame': first['frame'] + 1,
                                              'clockMs': 1234,
                                              'snapshot': 'snap_api'}}]}
        original = ledger_module.skill_ledger

        def with_engine(abc):
            return ledger_module.attach_engine_outcomes(original(abc), outcomes)

        with mock.patch.object(ledger_module, 'skill_ledger', with_engine):
            data = self.client.get(
                f'/api/replays/{self.replay_id}/skill-ledger').json()
            filtered = self.client.get(
                f'/api/replays/{self.replay_id}/skill-ledger?unit=8').json()
        self.assertEqual(data['provenance']['engine']['castsMeasured'], 1)
        self.assertEqual(data['casts'][0]['engine']['tier'], 'engine-measured')
        self.assertEqual(data['casts'][0]['engine']['hit']['hit'], True)
        self.assertIsNone(data['casts'][1]['engine'])
        self.assertEqual(filtered['castsTotal'], 5)
        self.assertEqual(filtered['casts'][0]['engine']['observedAt']['snapshot'],
                         'snap_api')
        self.assertEqual(filtered['provenance']['engine']['castsMeasured'], 1)


if __name__ == '__main__':
    unittest.main()
