import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'tools' / 'state_series_to_checkpoints.py'


def write_csv(path: Path, rows: list[dict]):
    fields = ['clock', 'second', 'index', 'player', 'hero', 'camp',
              'gold', 'd_gold', 'gold_rate', 'kills', 'deaths', 'assists',
              'level', 'c0', 'c1', 'c2', 'c3', 'c4', 'c5', 'c6', 'c7', 'c8',
              'c9', 'c10', 'd_c3', 'c3_rate', 'source']
    with path.open('w', encoding='utf-8', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class StateSeriesCheckpointTests(unittest.TestCase):
    def test_converts_to_product_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            csv_path = tmp / 'series.csv'
            out = tmp / 'checkpoints.jsonl'
            manifest = tmp / 'manifest.json'
            write_csv(csv_path, [
                {'clock': '01:00', 'second': '60', 'index': '1',
                 'player': 'A', 'hero': '英雄A', 'camp': '1',
                 'gold': '300', 'd_gold': '', 'gold_rate': '',
                 'kills': '0', 'deaths': '0', 'assists': '0', 'level': '1',
                 'c0': '0', 'c1': '10', 'c2': '20', 'c3': '30',
                 'c4': '0', 'c5': '0', 'c6': '0', 'c7': '0', 'c8': '0',
                 'c9': '0', 'c10': '0', 'd_c3': '', 'c3_rate': '',
                 'source': 'engine-measured'},
                {'clock': '02:00', 'second': '120', 'index': '1',
                 'player': 'A', 'hero': '英雄A', 'camp': '1',
                 'gold': '900', 'd_gold': '600', 'gold_rate': '10',
                 'kills': '1', 'deaths': '0', 'assists': '0', 'level': '2',
                 'c0': '0', 'c1': '20', 'c2': '40', 'c3': '60',
                 'c4': '0', 'c5': '0', 'c6': '0', 'c7': '0', 'c8': '0',
                 'c9': '0', 'c10': '0', 'd_c3': '30', 'c3_rate': '0.5',
                 'source': 'engine-measured'},
            ])
            proc = subprocess.run(
                [sys.executable, str(TOOL), str(csv_path), '--out', str(out),
                 '--manifest', str(manifest), '--fail-on-nonmonotonic'],
                cwd=ROOT, capture_output=True, text=True, check=False)
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            rows = [json.loads(line) for line in out.read_text(encoding='utf-8').splitlines()]
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]['time_s'], 60.0)
            self.assertEqual(rows[0]['time_mmss'], '01:00')
            self.assertEqual(rows[0]['sources'], 'arena_stats')
            self.assertEqual(rows[0]['row_kind'], 'state')
            self.assertEqual(rows[0]['c3'], 30)
            self.assertEqual(rows[1]['gold'], 900)
            meta = json.loads(manifest.read_text(encoding='utf-8'))
            self.assertEqual(meta['rows'], 2)
            self.assertEqual(meta['checkpoints'], ['01:00', '02:00'])
            self.assertEqual(meta['monotonicViolations'], [])

    def test_nonmonotonic_can_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            csv_path = tmp / 'bad.csv'
            rows = []
            for clock, second, gold in [('01:00', '60', '500'), ('02:00', '120', '400')]:
                rows.append({'clock': clock, 'second': second, 'index': '1',
                             'player': 'A', 'hero': 'H', 'camp': '1',
                             'gold': gold, 'kills': '0', 'deaths': '0',
                             'assists': '0', 'level': '1'})
            write_csv(csv_path, rows)
            proc = subprocess.run(
                [sys.executable, str(TOOL), str(csv_path),
                 '--out', str(tmp / 'out.jsonl'), '--fail-on-nonmonotonic'],
                cwd=ROOT, capture_output=True, text=True, check=False)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn('monotonicity', proc.stderr + proc.stdout)


if __name__ == '__main__':
    unittest.main()
