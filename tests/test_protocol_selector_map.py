"""Boundary checks for the metadata decoder and bounded packet search."""
import struct
import unittest

from tools.protocol_selector_map import compressed_i32, scan_envelopes


class MetadataIntegerTests(unittest.TestCase):
    def test_encoding_widths_and_sign(self):
        for data, expected in ((b"\x00", 0), (b"\x01", -1), (b"\x7e", 63),
                               (b"\x80\x80", 64), (b"\x9b\x32", 3481),
                               (b"\xc0\x00\x40\x00", 8192),
                               (b"\xf0\xfe\xff\xff\x7f", 1073741823),
                               (b"\xf0\xff\xff\xff\xff", -2147483648)):
            with self.subTest(data=data):
                self.assertEqual(compressed_i32(data, 0), expected)

    def test_invalid_and_truncated(self):
        for data in (b"", b"\x80", b"\xc0\x00", b"\xf0\x01", b"\xe0\x00\x00\x00\x00"):
            with self.subTest(data=data), self.assertRaises(ValueError):
                compressed_i32(data, 0)
        with self.assertRaises(ValueError):
            compressed_i32(b"\x00", -1)


class EnvelopeTests(unittest.TestCase):
    @staticmethod
    def packet(length=-16, version=1):
        return struct.pack("<i", length) + struct.pack(">II", 21704, version) + bytes(8)

    def test_exact_boundary_and_offset(self):
        self.assertEqual(scan_envelopes(b"abc" + self.packet(), 21704),
                         [{"offset": 7, "length": 16, "version": 1}])

    def test_rejects_false_candidates(self):
        for data in (self.packet()[:-1], self.packet(-17), self.packet(16),
                     self.packet(-15), self.packet(version=0),
                     self.packet(version=0x2F66), self.packet()[4:]):
            with self.subTest(data=data):
                self.assertEqual(scan_envelopes(data, 21704), [])


if __name__ == "__main__":
    unittest.main()
