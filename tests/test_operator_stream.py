from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from operator_stream import (HEADER_BYTES, OperatorStreamError, parse_stream, summarize)


def varint(value):
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def stream_header(layout_payload=123):
    return bytes.fromhex('020001f3dd010a'
                         '7b000000'
                         '0001fadd011717000000000000000000')[:HEADER_BYTES]


def with_layout_size(header, size):
    return header[:7] + size.to_bytes(4, 'little') + header[11:]


class OperatorStreamTests(unittest.TestCase):
    def build(self, body, layout_payload=123):
        return with_layout_size(stream_header(), layout_payload) + body

    def test_fixed_shape_records_round_trip(self):
        body = (b'\x00\x8c\x01'                       # Common frame 396
                + b'\x01' + varint(28691)             # UnityFrame
                + b'\x02\x30\x01' + varint(28523)     # GameCoreFrame + inline UnityFrame
                + b'\x02\x8a\x01\x01' + varint(28759)  # GameCoreFrame + separate UnityFrame
                + b'\x13\xae\x01\x00\x01'             # SkillSlot
                + b'\x13\xae\x01\x0b'                 # SkillSlot without value byte
                + b'\x0f\xa6\x01\x06')                # UIViewChange (tentative shape)
        records, ambiguities = parse_stream(self.build(body))
        self.assertEqual(ambiguities, 0)
        self.assertTrue(all(not r['tentative'] or r['typeName'] == 'UIViewChangeOpe'
                            for r in records))
        kinds = [(r['typeName'], r['fields']) for r in records]
        self.assertEqual(kinds[0], ('Common', {'frame': 396}))
        self.assertEqual(kinds[1], ('UnityFrameOpe', {'unityFrame': 28691}))
        self.assertEqual(kinds[2], ('GameCoreFrameOpe', {'frame': 304, 'unityFrame': 28523}))
        self.assertEqual(kinds[3], ('GameCoreFrameOpe', {'frame': 394}))
        self.assertEqual(kinds[4], ('UnityFrameOpe', {'unityFrame': 28759}))
        self.assertEqual(kinds[5], ('SkillSlotOpe', {'frame': 430, 'slot': 0, 'value': 1}))
        self.assertEqual(kinds[6], ('SkillSlotOpe', {'frame': 430, 'slot': 11}))
        self.assertEqual(kinds[7], ('UIViewChangeOpe', {'frame': 422, 'viewType': 6}))

    def test_variable_records_resolved_by_suffix(self):
        touch4 = b'\x05\x7e\x00\x00\x10\xd3\x01\xc3\x01'
        touch5 = b'\x05\x82\x01\x00\x00\x10\xd3\x01\xc3\x01'
        move5 = b'\x06\x88\x01\x00\x10\x01\x02\x71'
        # 第六个 varint 取多字节值，避免与“5 varint + 独立 UnityFrame 记录”形成真歧义
        move7 = b'\x06\x88\x01\x03\x58\x04\x02\x77' + varint(300) + b'\x05'
        tail = b'\x00\x8c\x01'
        records, _ = parse_stream(self.build(touch4 + touch5 + move5 + move7 + tail))
        self.assertEqual([r['type'] for r in records], [0x05, 0x05, 0x06, 0x06, 0x00])
        self.assertEqual(records[0]['fields'], {'frame': 126, 't1': 0, 't2': 16, 't3': 211, 't4': 195})
        self.assertEqual(records[1]['fields']['t5'], 195)
        self.assertEqual(len(records[2]['fields']), 6)
        self.assertEqual(len(records[3]['fields']), 8)

    def test_string_and_memory_records(self):
        path = 'BootObj/CUIManager/Camera_Form'.encode()
        inst = varint(0xFFFFFECA)
        body = (b'\x0e\xa5\x01' + inst + bytes([len(path)]) + path
                + b'\x10\xa8\x01' + varint(3) + b'\x01\x02\x03')
        records, _ = parse_stream(self.build(body))
        self.assertEqual(records[0]['type'], 0x0E)
        self.assertEqual(records[0]['fields']['path'], 'BootObj/CUIManager/Camera_Form')
        self.assertEqual(records[1]['fields']['data'], b'\x01\x02\x03')

    def test_unresolvable_bytes_are_flagged_not_hidden(self):
        body = b'\x00\x8c\x01' + b'\x0f\xa6\x01\x06'
        records, _ = parse_stream(self.build(body))
        self.assertTrue(not records[0]['tentative'])
        self.assertEqual(records[0]['fields'], {'frame': 396})
        self.assertTrue(records[1]['tentative'])
        summary = summarize(self.build(body), start=HEADER_BYTES)
        self.assertTrue(summary['decoded'])
        self.assertEqual(summary['streamStart'], HEADER_BYTES)
        self.assertEqual(summary['tentativeBytes'], 4)
        self.assertEqual(summary['tentativeCount'], 1)

    def test_bytes_outside_enum_cannot_start_records(self):
        # emOperatorDataType 只有 0x00–0x19；0xFE 不可能是记录类型，
        # 出现在流首时必须报错而不是被猜测成某个记录
        with self.assertRaises(OperatorStreamError):
            parse_stream(self.build(b'\xfe\x01\x00\x8c\x01'))

    def test_truncated_varint_raises(self):
        with self.assertRaises(OperatorStreamError):
            parse_stream(self.build(b'\x05\x7e\x00\x00\x10\xd3'))

    def test_missing_tail_raises(self):
        with self.assertRaises(OperatorStreamError):
            parse_stream(self.build(b'\x13\xae\x01'))

    def test_layout_payload_size_from_header(self):
        # Legacy raw-payload fallback still works when the header length is
        # present; the 75-varint layout is impossible on this short body.
        body = b'\x16\xb4\x01' + b'\x00' * 9
        records, _ = parse_stream(self.build(body, layout_payload=9))
        self.assertEqual(records[0]['type'], 0x16)
        self.assertTrue(records[0]['tentative'])
        self.assertEqual(records[0]['size'], 1 + 2 + 9)

    def test_uilayout_is_seventy_five_varints(self):
        # 44/44 local samples: after the u16 tag, UILayout carries exactly 75
        # ULEB values and the next byte starts a SkillSlotOpe run.
        layout = bytes(range(1, 76))
        body = (b'\x16\xb4\x01' + layout
                + b'\x13\xae\x01\x00\x01'
                + b'\x00\x8c\x01')
        records, ambiguities = parse_stream(self.build(body))
        self.assertEqual(ambiguities, 0)
        self.assertEqual(records[0]['typeName'], 'UILayout')
        self.assertEqual(records[0]['fields']['tag'], 436)
        self.assertEqual(records[0]['fields']['layout'], list(range(1, 76)))
        self.assertEqual(records[0]['size'], 1 + 2 + 75)
        self.assertEqual(records[1]['typeName'], 'SkillSlotOpe')
        self.assertFalse(records[0]['tentative'])

    def test_invalid_legacy_layout_payload_is_ignored(self):
        # stream[7:11] no longer gates parsing: the 75-varint UILayout layout
        # does not need it.  A zero there only disables the raw fallback.
        records, _ = parse_stream(with_layout_size(stream_header(), 0) + b'\x00\x8c\x01')
        self.assertEqual(records[0]['fields'], {'frame': 396})

    def parse_with_plans(self, body, plans):
        """Pin selected type layouts so the test asserts the layout itself,
        not the global DP's tie-break against longer look-alike records."""
        import operator_stream as os
        saved = {type_byte: os.LAYOUTS[type_byte] for type_byte in plans}
        for type_byte, plan in plans.items():
            os.LAYOUTS[type_byte] = [(os.CONFIRMED, plan)]
        try:
            return parse_stream(self.build(body))
        finally:
            for type_byte, layouts in saved.items():
                os.LAYOUTS[type_byte] = layouts

    def test_move_four_varint_layout(self):
        # 9-byte MoveOpe runs in 11/2: 06 88 01 + [degree, ping, seq, unity].
        plan = [('frame',), ('varint', 'm1'), ('varint', 'm2'),
                ('varint', 'm3'), ('varint', 'unityFrame')]
        body = (bytes.fromhex('06 88 01 65 99 0a 01 c7 7d')
                + b'\x13\xae\x01\x00\x01'
                + b'\x00\x8c\x01')
        records, _ = self.parse_with_plans(body, {0x06: plan})
        self.assertEqual(records[0]['typeName'], 'MoveOpe')
        self.assertEqual(records[0]['fields'],
                         {'frame': 392, 'm1': 101, 'm2': 1305, 'm3': 1,
                          'unityFrame': 16071})
        self.assertEqual(records[0]['size'], 9)
        self.assertEqual(records[1]['typeName'], 'SkillSlotOpe')

    def test_dirskill_four_varint_layout(self):
        # 11/2 DirSkill: 15 6f 02 + [skillId, seq, param1, param2], then the
        # CppEventOpe whose value repeats the seq (0x0c 04 02 00 01).
        dir_plan = [('frame',), ('varint', 'skillId'), ('varint', 'seq'),
                    ('varint', 'param1'), ('varint', 'param2')]
        cpp_plan = [('u8', 'slotType'), ('varint', 'skillId'),
                    ('varint', 'value'), ('varint', 'extra')]
        body = (b'\x15\x6f\x02\xa4\x99\x01\x01\xb8\xf0\x02\xb3\x03'
                + b'\x0c\x04\x02\x00\x01'
                + b'\x13\xae\x01\x00\x01'
                + b'\x00\x8c\x01')
        records, _ = self.parse_with_plans(body, {0x15: dir_plan, 0x0C: cpp_plan})
        self.assertEqual(records[0]['typeName'], 'DirSkillOpe')
        self.assertEqual(records[0]['fields'],
                         {'frame': 623, 'skillId': 19620, 'seq': 1,
                          'param1': 47160, 'param2': 435})
        self.assertEqual(records[0]['size'], 12)
        self.assertEqual(records[1]['typeName'], 'CppEventOpe')
        self.assertEqual(records[1]['fields'], {'slotType': 4, 'skillId': 2,
                                                'value': 0, 'extra': 1})

    def test_uievent_u8_tag_layout(self):
        # 11/2 UIEventOpe starts with the constant 0x7d tag, then the varint id.
        body = b'\x0b\x7d\xd2\x08' + b'\x00\x8c\x01'
        records, _ = parse_stream(self.build(body))
        self.assertEqual(records[0]['typeName'], 'UIEventOpe')
        self.assertEqual(records[0]['fields'], {'tag': 125, 'eventId': 1106})
        self.assertEqual(records[0]['size'], 4)

    def test_uint_six_byte_layout(self):
        # Both 11/2 games contain `0a 12 00 00 00 00 18 b6 01 6d 9d…`.
        # A six-byte UInt (frame + three value bytes) ends exactly on the
        # following SendMsgToServerOpe; the four-byte varint layout would
        # leave 0x18 inside a Common and wall later.
        plan = [('frame',), ('u24', 'value')]
        body = bytes.fromhex('0a 12 00 00 00 00 00 8c 01')
        records, _ = self.parse_with_plans(body, {0x0A: plan})
        self.assertEqual(records[0]['typeName'], 'UIntOpe')
        self.assertEqual(records[0]['size'], 6)
        self.assertEqual(records[0]['fields'], {'frame': 18, 'value': 0})
        self.assertEqual(records[1]['typeName'], 'Common')

    def test_dirskill_five_varint_layout(self):
        # 11/2b 0x7EF3: the fifth DirSkill varint ends on CppEvent
        # `0c 04 02 00 08`, whose extra value repeats seq (8).
        dir_plan = [('frame',), ('varint', 'skillId'), ('varint', 'seq'),
                    ('varint', 'param1'), ('varint', 'param2'),
                    ('varint', 'extra')]
        cpp_plan = [('u8', 'slotType'), ('varint', 'skillId'),
                    ('varint', 'value'), ('varint', 'extra')]
        body = (bytes.fromhex('15 6f 02 a4 99 01 08 37 e9 02 e2 0c')
                + bytes.fromhex('0c 04 02 00 08')
                + b'\x13\xae\x01\x00\x01'
                + b'\x00\x8c\x01')
        records, _ = self.parse_with_plans(body, {0x15: dir_plan, 0x0C: cpp_plan})
        self.assertEqual(records[0]['typeName'], 'DirSkillOpe')
        self.assertEqual(records[0]['size'], 12)
        self.assertEqual(records[0]['fields'],
                         {'frame': 623, 'skillId': 19620, 'seq': 8,
                          'param1': 55, 'param2': 361, 'extra': 1634})
        self.assertEqual(records[1]['typeName'], 'CppEventOpe')
        self.assertEqual(records[1]['fields']['extra'], 8)

    def test_memory_checkpoint_frame_is_not_a_payload(self):
        # 11/2 `10 03 01 e1 68` (frame 259, third 13,409) is the tail of a
        # preceding Move whose last varint is the unity clock, not a
        # MemoryData payload.  The payload layout is gated to frames outside
        # 256..267, so the bare slice cannot start a record.
        body = b'\x10\x03\x01' + varint(13409) + b'\x00\x8c\x01'
        with self.assertRaises(OperatorStreamError):
            parse_stream(self.build(body))

    def test_memory_artifact_slice_is_a_move_tail(self):
        # Same bytes as the 11/2a 0x1991E jump: the preceding Move starts four
        # bytes earlier and consumes `10 03 01 bc 92 01` as varints
        # 16, 3, 1, 18,748.  The last value is the unity clock, which is why
        # the false "MemoryData" third field looked like a timestamp.
        plan = [('frame',), ('varint', 'm1'), ('varint', 'm2'),
                ('varint', 'm3'), ('varint', 'm4'), ('varint', 'unityFrame')]
        body = bytes.fromhex('06 88 01 61 10 03 01 bc 92 01') + b'\x00\x8c\x01'
        records, _ = self.parse_with_plans(body, {0x06: plan})
        self.assertEqual(records[0]['typeName'], 'MoveOpe')
        self.assertEqual(records[0]['size'], 10)
        self.assertEqual(records[0]['fields']['m1'], 97)
        self.assertEqual(records[0]['fields']['m2'], 16)
        self.assertEqual(records[0]['fields']['unityFrame'], 18748)

    @unittest.skipUnless(Path('data/replays/samples/20261028_135516.ope').exists(),
                         'Local research sample unavailable')
    def test_research_sample_reports_remaining_walls(self):
        from replay_parser import parse_ope_bytes
        ope = Path('data/replays/samples/20261028_135516.ope').read_bytes()
        report = parse_ope_bytes(ope)
        events = report['operatorEvents']
        self.assertFalse(events['decoded'])
        self.assertIn('无法', events['note'])
