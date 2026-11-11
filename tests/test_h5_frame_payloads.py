import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "host" / "scripts"))

from replay_fixtures import inputs_5v5_fixture  # noqa: E402
import extract_frame_payloads as extractor  # noqa: E402


def fixture(commands):
    return inputs_5v5_fixture(commands=commands)


class ExtractFramePayloadsTests(unittest.TestCase):
    def run_extract(self, data, **kwargs):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        abc = Path(tmp.name) / "sample.abc"
        abc.write_bytes(data)
        out = Path(tmp.name) / "out"
        manifest = extractor.extract(abc, out, kwargs.pop("start", 0),
                                     kwargs.pop("limit", 0),
                                     kwargs.pop("stride", 1),
                                     kwargs.pop("require_parsed", False))
        return out, manifest

    def test_exact_payload_bytes_and_index(self):
        commands = (b"\x00", b"\x01\x02\x03\x04", b"\x12\x34\x56")
        out, manifest = self.run_extract(fixture(commands))
        self.assertEqual((out / "frames.bin").read_bytes(), b"".join(commands))
        lines = (out / "index.tsv").read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0].split("\t")[0], "# index")
        rows = [line.split("\t") for line in lines[1:]]
        self.assertEqual([r[1] for r in rows], ["1", "2", "3"])
        self.assertEqual([int(r[2]) for r in rows], [0, 1, 5])
        self.assertEqual([int(r[3]) for r in rows], [1, 4, 3])
        self.assertEqual(manifest["frames"]["extracted"], 3)
        self.assertEqual(manifest["frames"]["structural_failures"], 2)
        self.assertEqual(manifest["schema"], "kpl-h5-frame-payloads-v1")

    def test_selection_is_applied_to_frame_records(self):
        commands = (b"\x00", b"\x01", b"\x02", b"\x03", b"\x04")
        out, manifest = self.run_extract(fixture(commands), start=1, limit=2, stride=2)
        self.assertEqual((out / "frames.bin").read_bytes(), b"\x01\x03")
        rows = [line.split("\t") for line in
                (out / "index.tsv").read_text(encoding="utf-8").splitlines()[1:]]
        self.assertEqual([r[1] for r in rows], ["2", "4"])
        self.assertEqual(manifest["selection"]["start"], 1)
        self.assertEqual(manifest["frames"]["first_sequence"], 2)
        self.assertEqual(manifest["frames"]["last_sequence"], 4)

    def test_require_parsed_rejects_but_default_keeps_bytes(self):
        commands = (b"\x00", b"\x01\x02")
        out, _ = self.run_extract(fixture(commands))
        self.assertEqual((out / "frames.bin").read_bytes(), b"\x00\x01\x02")
        with self.assertRaises(ValueError):
            self.run_extract(fixture(commands), require_parsed=True)


if __name__ == "__main__":
    unittest.main()
