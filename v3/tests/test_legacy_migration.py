"""旧数据目录搬迁：只在本机、只在空库、失败不留残留。"""
import json
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import serve


def make_legacy(root: Path, *, broken: bool = False) -> Path:
    data = root / 'data'
    (data / 'matches').mkdir(parents=True)
    (data / 'matches' / 'm1.json').write_text('{"schema":"x"}', encoding='utf-8')
    (data / 'camp_auth.json').write_text('{"ok":true}', encoding='utf-8')
    database = data / 'training.sqlite3'
    if broken:
        database.write_text('这不是数据库', encoding='utf-8')
        return data
    connection = sqlite3.connect(database)
    try:
        connection.execute('CREATE TABLE match_records (id TEXT PRIMARY KEY, body TEXT)')
        connection.execute("INSERT INTO match_records VALUES ('m1', '{}')")
        connection.commit()
    finally:
        # Windows 上连接不关会锁住文件，临时目录删不掉。
        connection.close()
    return data


def wait(client, seconds=30):
    deadline = time.time() + seconds
    while time.time() < deadline:
        job = client.get('/api/data/migrate').json()
        if job.get('state') in ('done', 'error'):
            return job
        time.sleep(0.05)
    raise AssertionError('搬迁超时')


class LegacyMigrationTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        # 搬迁接口只认回环地址；测试客户端默认的 testclient 主机名会被挡。
        self.client = TestClient(serve.app, base_url='http://127.0.0.1',
                                 client=('127.0.0.1', 50000))

    def test_copies_library_and_cleans_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = make_legacy(root / 'legacy')
            target = root / 'target'
            target.mkdir()
            with patch.object(serve, 'data_root', return_value=target):
                response = self.client.post('/api/data/migrate', json={'path': str(source)})
                self.assertEqual(response.status_code, 200, response.text[:200])
                job = wait(self.client)
            self.assertEqual(job['state'], 'done', job.get('error'))
            self.assertTrue((target / 'training.sqlite3').is_file())
            self.assertTrue((target / 'matches' / 'm1.json').is_file())
            self.assertTrue((target / 'camp_auth.json').is_file())
            self.assertFalse((target / '.migrate-staging').exists())

    def test_failure_leaves_library_untouched_and_can_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            broken = make_legacy(root / 'broken', broken=True)
            good = make_legacy(root / 'good')
            target = root / 'target'
            target.mkdir()
            with patch.object(serve, 'data_root', return_value=target):
                self.assertEqual(self.client.post(
                    '/api/data/migrate', json={'path': str(broken)}).status_code, 200)
                job = wait(self.client)
                self.assertEqual(job['state'], 'error')
                self.assertFalse((target / 'matches').exists())
                self.assertFalse((target / '.migrate-staging').exists())

                self.assertEqual(self.client.post(
                    '/api/data/migrate', json={'path': str(good)}).status_code, 200)
                job = wait(self.client)
            self.assertEqual(job['state'], 'done', job.get('error'))
            self.assertTrue((target / 'matches' / 'm1.json').is_file())

    def test_refuses_non_library_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / 'empty'
            empty.mkdir()
            response = self.client.post('/api/data/migrate', json={'path': str(empty)})
            self.assertEqual(response.status_code, 400)
            self.assertIn('training.sqlite3', response.json()['detail'])

    def test_refuses_when_current_library_has_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = make_legacy(root / 'legacy')
            target = root / 'target'
            (target / 'matches').mkdir(parents=True)
            (target / 'matches' / 'existing.json').write_text('{}', encoding='utf-8')
            with patch.object(serve, 'data_root', return_value=target):
                response = self.client.post('/api/data/migrate', json={'path': str(source)})
            self.assertEqual(response.status_code, 409)

    def test_welcome_reports_legacy_size_and_match_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            source = make_legacy(home / 'Desktop' / 'KPL赛训工具')
            with patch.object(Path, 'home', return_value=home), \
                    patch.object(serve, 'data_root', return_value=home / 'current'):
                data = self.client.get('/api/welcome').json()
            paths = [item['path'] for item in data['legacy']]
            self.assertIn(str(source), paths)
            entry = next(item for item in data['legacy'] if item['path'] == str(source))
            self.assertEqual(entry['matches'], 1)
            self.assertGreater(entry['size'], 0)


if __name__ == '__main__':
    unittest.main()
