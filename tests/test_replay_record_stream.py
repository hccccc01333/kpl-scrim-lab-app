import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from replay_fixtures import single_game_1051_fixture
from tools.replay_record_stream import audit, iter_records


def fixture():
    strings = b"".join(bytes([len(s)]) + s for s in (b"12.1.1.1", b"12.1.1.26", b"5247758", b"5247758"))
    header = strings + bytes(17) + b"\x00\x00" + bytes(5) + struct.pack("<IiBI", 0, 0, 0, 5)
    def cs(mid):
        return struct.pack("<i", -16) + struct.pack(">IIII", mid, 1, 2, 3)
    def frame(seq, commands):
        return struct.pack("<i", 6 + len(commands)) + struct.pack(">IH", seq, len(commands)) + commands
    return header + cs(1075) + cs(1077) + frame(1, b"\0") + frame(2, b"\x01\x02") + cs(1251)


class RecordStreamTests(unittest.TestCase):
    def test_mixed_records_reach_exact_eof(self):
        data = fixture()
        rows = list(iter_records(data))
        self.assertEqual([r["kind"] for r in rows], ["cs", "cs", "frame", "frame", "cs"])
        self.assertEqual(rows[-1]["end"], len(data))
        result = audit(data)
        self.assertEqual(result["frame_records"], 2)
        self.assertEqual(result["total_frame_header"], 5)
        self.assertEqual(result["command_bytes"], 3)

    def test_truncation_and_trailing_bytes(self):
        for data in (fixture()[:-1], fixture() + b"\x01", fixture() + bytes(4)):
            with self.subTest(length=len(data)), self.assertRaises(ValueError):
                audit(data)

    def test_rejects_bad_frame_size_and_sequence(self):
        data = fixture()
        frame = next(r for r in iter_records(data) if r["kind"] == "frame")
        for offset, value in ((frame["payload_offset"], struct.pack(">I", 3)),
                              (frame["payload_offset"] + 4, struct.pack(">H", 20))):
            corrupted = bytearray(data)
            corrupted[offset:offset + len(value)] = value
            with self.assertRaises(ValueError):
                audit(corrupted)

    def test_1051_shaped_body_under_1075_opening_is_rejected(self):
        data = bytearray(fixture())
        first = next(iter_records(data))
        struct.pack_into(">I", data, first["payload_offset"], 1051)
        with self.assertRaises(ValueError):
            audit(data)


class SingleGame1051Tests(unittest.TestCase):
    """Container indexing of the single-game route (docs 5.133)."""

    def test_entries_index_to_eof_with_frame_numbers(self):
        data = single_game_1051_fixture((
            (1, b"\x01\x00\x02\x23\x01\x03\x13\x00\x00"),
            (2, b"\x02\x84\x03\x00\x00\x00\x00\x03\x13\x00\x00"),
            (2, b"\x02\x83\x00\x2a\x2a\x03\x13\x00\x00"),
            (3, b"\x02\x87\x00\x00\x00\x08\x01\x00\x00\x03\x13\x00\x00"),
            (3, b"\x02\x85\x06\xa5\x00\x00\x08\x00\x03\x13\x00\x00"),
        ))
        rows = list(iter_records(data))
        self.assertEqual([r["kind"] for r in rows],
                         ["cs", "entry", "entry", "entry", "entry", "entry"])
        self.assertEqual(rows[0]["message_id"], 1051)
        self.assertEqual([r["sequence"] for r in rows[1:]], [1, 2, 2, 3, 3])
        self.assertEqual(rows[-1]["end"], len(data))
        decoded = [r["decoded"] for r in rows[1:]]
        self.assertEqual(decoded[0]["kind"], "cc")
        self.assertEqual(decoded[0]["buffer"], "022301")
        self.assertEqual(decoded[1]["name"], "kill_notice")
        self.assertEqual(decoded[2]["name"], "facing_angle")
        self.assertEqual(decoded[2]["angle_deg"], 42)
        self.assertEqual(decoded[2]["index"], 42)
        self.assertEqual(decoded[3]["name"], "skill_levelup")
        self.assertEqual(decoded[3]["actor"], 8)
        self.assertEqual(decoded[3]["skill"], 1)
        self.assertEqual(decoded[3]["level_index"], 0)
        self.assertEqual(decoded[4]["name"], "buy_equip")
        self.assertEqual(decoded[4]["equip_id"], 1701)
        self.assertEqual(decoded[4]["rest"], "00000800")
        result = audit(data)
        self.assertEqual(result["route"], 1051)
        self.assertEqual(result["entry_records"], 5)
        self.assertEqual(result["last_sequence"], 3)
        self.assertTrue(result["consumed_to_eof"])
        self.assertEqual(result["entry_types"],
                         {"cc": 1, "kill_notice": 1, "facing_angle": 1,
                          "skill_levelup": 1, "buy_equip": 1})
        self.assertIn("entry-shape indexing", result["limitations"])

    def test_sequence_must_be_monotonic(self):
        data = single_game_1051_fixture(((2, b"\x00"), (1, b"\x00")))
        with self.assertRaises(ValueError):
            audit(data)

    def test_truncated_entry_rejects(self):
        data = single_game_1051_fixture(((1, b"\x01\x00\x02\x23\x01"),))
        with self.assertRaises(ValueError):
            audit(data[:-1])

    def test_hero_inputs_reports_unsupported_route(self):
        from tools.replay_frame_commands import hero_inputs
        result = hero_inputs(single_game_1051_fixture())
        self.assertEqual(result["status"], "unsupported-route")
        self.assertIn("1051", result["error"])


if __name__ == "__main__":
    unittest.main()
