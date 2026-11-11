import hashlib
import json
import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "host" / "fixtures" / "20261102_161129" / "consumer"
HEADER = struct.Struct("<4sIIQQQ")
ENTRY = struct.Struct("<QQ")
SLOT = struct.Struct("<II")


class CommandTableFixtureTests(unittest.TestCase):
    def test_binary_layout_and_manifest(self):
        raw = (FIXTURE / "cmd_table.bin").read_bytes()
        manifest = json.loads((FIXTURE / "cmd_table.json").read_text(encoding="utf-8"))
        magic, version, count, nslots, table_off, reserved = HEADER.unpack_from(raw)
        self.assertEqual(magic, b"KCMD")
        self.assertEqual(version, 1)
        self.assertEqual(reserved, 0)
        self.assertEqual(count, 857)
        self.assertEqual(nslots, 1368)
        self.assertEqual(table_off, 0x53F6F40)
        self.assertEqual(len(raw), HEADER.size + count * ENTRY.size + nslots * SLOT.size)
        self.assertEqual(manifest["binary"]["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(manifest["table"]["count"], count)
        self.assertEqual(manifest["slots"]["captured"], nslots)

        entries = [ENTRY.unpack_from(raw, HEADER.size + i * ENTRY.size) for i in range(count)]
        self.assertEqual(entries[0], (0x46D6040, 1))
        self.assertEqual(entries[257], (0x4703BC4, 0))
        self.assertEqual(sum(1 for handler, _ in entries if handler), 792)

        slots = [SLOT.unpack_from(raw, HEADER.size + count * ENTRY.size + i * SLOT.size)
                 for i in range(nslots)]
        slot_map = dict(slots)
        self.assertEqual(slot_map[0x52304D0], 0x46D5FF0)
        self.assertEqual(slot_map[0x5232430], 0x4703B48)
        self.assertEqual(sum(1 for _, target in slots if target == 0), 5)


if __name__ == "__main__":
    unittest.main()
