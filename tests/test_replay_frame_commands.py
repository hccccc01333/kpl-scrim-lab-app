import struct
import unittest

from tools.replay_frame_commands import (
    FRAME_RATE,
    battle_time,
    compass_bearing,
    decode_attack_byte,
    decode_commands,
    decode_move_info,
    unit_roster_slot,
    world_vector,
    UnsupportedCommand,
)


class FrameCommandTests(unittest.TestCase):
    def test_empty_and_count_boundaries(self):
        self.assertEqual(decode_commands(b"\0"), [])
        for data in (b"", b"\0\0", b"\x51"):
            with self.subTest(data=data), self.assertRaises(ValueError):
                decode_commands(data)

    def test_buy_equipment_golden_bytes(self):
        row, = decode_commands(bytes.fromhex("010200d48504570000000800"))
        self.assertEqual(row["name"], "BUYEQUIP")
        self.assertEqual(row["object_id"], 212)
        self.assertEqual(row["fields"], {"equip_id": 1111, "object_id": 8, "auto_buy": 0})

    def test_position_skill_has_signed_target_and_no_actor_position(self):
        row, = decode_commands(bytes.fromhex("0102070c82010000add4ffff7d2400000000000000"))
        self.assertEqual(row["name"], "USEPOSITIONSKILL")
        self.assertEqual(row["fields"]["target_x"], 44500)
        self.assertEqual(row["fields"]["target_y"], -33500)
        self.assertNotIn("position", row)

    def test_mixed_cc_and_packed_commands(self):
        rows = decode_commands(bytes.fromhex("0401070c00021402124911134014490025"))
        self.assertEqual([row["name"] for row in rows],
                         ["CC", "PLAYER_MOVE", "PLAYER_ATTACK", "PLAYER_ATTACKWITHOBJ"])
        self.assertEqual(rows[0]["buffer_hex"], "1402")
        self.assertEqual(rows[-1]["fields"]["target_object_id"], 37)
        self.assertEqual(rows[1]["fields"], {"packed_move": 0x4911})

    def test_signed_object_id_and_direction(self):
        data = b"\x01\x02\x00\xd4\x80" + struct.pack(">biBHI", 1, -1, 0, 2, 0)
        self.assertEqual(decode_commands(data)[0]["fields"]["object_id"], -1)
        data = b"\x01\x02\x00\xd4\x81" + struct.pack(">bhIiiiHB", 2, -6600, 0, 0, 0, 0, 0, 0)
        self.assertEqual(decode_commands(data)[0]["fields"]["degree"], -6600)

    def test_unknown_selectors_do_not_resynchronize(self):
        for data in (b"\x01\xff\x13\x40", b"\x01\x02\x00\x01\xff\x13\x40"):
            with self.subTest(data=data), self.assertRaises(UnsupportedCommand):
                decode_commands(data)

    def test_truncated_and_wrong_count(self):
        good = bytes.fromhex("010200d48504570000000800")
        for data in (good[:-1], b"\x02" + good[1:], good + b"\0",
                     bytes.fromhex("0101070c00051402")):
            with self.subTest(data=data), self.assertRaises(ValueError):
                decode_commands(data)


class PackedHeroFieldTests(unittest.TestCase):
    def test_move_info_fields_from_real_samples(self):
        # 20261101_182452 first move: unit 8 (camp1 slot0), dir +60.
        self.assertEqual(decode_move_info(0x403C),
                         {"unit": 8, "seq": 0, "sign": 0, "mag": 60, "dir_deg": 60})
        # Same sample, second entry layout with seq bits: 0x441B -> unit 8, seq 2.
        self.assertEqual(decode_move_info(0x441B)["seq"], 2)
        # 20261102_161129 frame 155: 0x4933 -> unit 9, signed direction -51.
        self.assertEqual(decode_move_info(0x4933),
                         {"unit": 9, "seq": 0, "sign": 1, "mag": 51, "dir_deg": -51})

    def test_move_magnitude_beyond_confirmed_maximum_rejects(self):
        self.assertEqual(decode_move_info(0x40B4)["mag"], 180)
        with self.assertRaises(ValueError):
            decode_move_info(0x40B5)

    def test_attack_byte_unit_decode(self):
        self.assertEqual(decode_attack_byte(0x40), {"unit": 8, "seq": 0, "flag": 0})
        self.assertEqual(decode_attack_byte(0x49), {"unit": 9, "seq": 0, "flag": 1})
        self.assertEqual(decode_attack_byte(0x64)["unit"], 12)

    def test_unit_roster_slot_mapping(self):
        self.assertEqual(unit_roster_slot(8), (1, 0))
        self.assertEqual(unit_roster_slot(12), (1, 4))
        self.assertEqual(unit_roster_slot(16), (2, 0))
        self.assertEqual(unit_roster_slot(20), (2, 4))
        for unit in (0, 7, 13, 14, 15, 21, 31):
            self.assertIsNone(unit_roster_slot(unit), unit)

    def test_mixed_commands_carry_decoded_hero_fields(self):
        rows = decode_commands(bytes.fromhex("0401070c00021402124911134014490025"))
        self.assertEqual(rows[1]["unit"], 9)
        self.assertEqual(rows[1]["dir_deg"], -17)
        self.assertEqual(rows[2]["unit"], 8)
        self.assertEqual(rows[2]["flag"], 0)
        self.assertEqual(rows[3]["unit"], 9)
        self.assertEqual(rows[3]["fields"]["target_object_id"], 37)

    def test_bad_move_magnitude_rejects_whole_frame(self):
        with self.assertRaises(ValueError):
            decode_commands(bytes.fromhex("01021240b4"))


class WorldBearingTests(unittest.TestCase):
    """Compass/world mapping calibrated in docs 5.128."""

    def test_world_vector_uses_native_y_down_axes(self):
        # dir -30 = northeast on screen: east + north(-y).
        self.assertEqual(world_vector(-30), (0.866, -0.5))
        # dir +120 = southwest: west + south(+y).
        self.assertEqual(world_vector(120), (-0.5, 0.866))
        self.assertEqual(world_vector(0), (1.0, 0.0))
        self.assertEqual(world_vector(90), (0.0, 1.0))

    def test_compass_bearing_mapping(self):
        self.assertEqual(compass_bearing(0), 90.0)      # east
        self.assertEqual(compass_bearing(-30), 60.0)    # northeast
        self.assertEqual(compass_bearing(120), 210.0)   # southwest
        self.assertEqual(compass_bearing(-90), 0.0)     # north
        self.assertEqual(compass_bearing(180), 270.0)   # west


class BattleTimeTests(unittest.TestCase):
    """Frame-to-seconds clock calibrated in docs 5.129."""

    def test_frame_rate_and_conversion(self):
        self.assertEqual(FRAME_RATE, 15)
        self.assertEqual(battle_time(40, first_frame=40), 0.0)
        self.assertEqual(battle_time(10409, first_frame=1), (10409 - 1) / 15)

    def test_calibrated_match_window(self):
        # 20261102_161129 pairs with a results page showing 693 s; the last
        # manual buy (frame 10409) must land at 692.9-693.9 s for F0 in [0..14].
        for f0 in range(0, 15):
            t = battle_time(10409, first_frame=f0)
            self.assertGreaterEqual(t, 692.9, f0)
            self.assertLess(t, 694.0, f0)


if __name__ == "__main__":
    unittest.main()
