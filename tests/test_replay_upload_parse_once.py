"""One upload must be decoded once, not three times.

The pipeline used to parse the same .abc three times: the upload check threw
its result away, the import parsed again, and the timeline build parsed a third
time.  These tests pin the single decode.
"""
import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault(
    'TRAINING_DB',
    str(ROOT / 'test-results' / f'test-parse-once-{uuid.uuid4().hex}.sqlite3'))

from fastapi.testclient import TestClient  # noqa: E402
from replay_fixtures import normal_5v5_fixture  # noqa: E402
import replay_parser  # noqa: E402
from server import app  # noqa: E402


class UploadParseOnceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, base_url='http://localhost')

    def setUp(self):
        replay_parser.cache_clear()

    def test_upload_and_import_decode_once(self):
        data = normal_5v5_fixture()
        calls = []
        original = replay_parser.parse_header

        def counting(payload):
            calls.append(1)
            return original(payload)

        with mock.patch.object(replay_parser, 'parse_header', counting):
            uploaded = self.client.post(
                '/api/replays/files?name=once.abc', content=data)
            self.assertEqual(uploaded.status_code, 200, uploaded.text)
            imported = self.client.post(
                '/api/replays/import', json={'abcFileId': uploaded.json()['id']})
            self.assertEqual(imported.status_code, 200, imported.text)
        report = imported.json()['report']
        self.assertEqual(len(report['blocks']), 10)
        self.assertEqual(report['blocks'][0]['heroName'], '亚瑟')
        # Upload fills the cache; import reuses it instead of decoding again.
        self.assertEqual(len(calls), 1)

    def test_bad_abc_is_still_rejected_at_upload(self):
        response = self.client.post(
            '/api/replays/files?name=bad.abc', content=b'not a replay' * 8)
        self.assertEqual(response.status_code, 422)

    def test_bad_ope_is_still_rejected_at_upload(self):
        response = self.client.post(
            '/api/replays/files?name=bad.ope', content=b'\x00' * 32)
        self.assertEqual(response.status_code, 422)

    def test_only_replay_extensions_are_accepted(self):
        response = self.client.post(
            '/api/replays/files?name=notes.txt', content=b'x' * 32)
        self.assertEqual(response.status_code, 400)


if __name__ == '__main__':
    unittest.main()
