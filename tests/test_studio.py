"""Statistical invariants and local result persistence; artifacts are retained."""
import copy
import json
import sqlite3
import unittest
import uuid
from pathlib import Path

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient

from studio_analysis import (StudioRepository, deduplicate, prediction, rank,
                             regression, run_analysis, temporal_split)
from studio_api import create_studio_router
from tests.test_analysis_data import make_db, bundle, C_BLUE, C_RED

ROOT = Path(__file__).resolve().parents[1]


def row(game, hero='甲', **values):
    return {'matchKey': str(game), 'hero': hero, 'label': hero, 'camp': 'blue',
            'date': f'2026-10-{int(game)%28+1:02d}', 'gold': float(game)*100+500,
            'damage': float(game)*200+1000, 'participation': 50+int(game)%4,
            'result': 'unknown', 'full': True, 'partial': False, **values}


class StatisticalTests(unittest.TestCase):
    def test_missing_values_are_not_zeroes(self):
        rows = [row(1), row(2, gold=None), row(3)]
        result = run_analysis(rows, {'method': 'describe', 'metrics': ['gold']})['rows'][0]
        self.assertEqual(result['n'], 2)
        self.assertEqual(result['missing'], 1)
        self.assertEqual(result['mean'], 700)

    def test_rank_averages_ties(self):
        np.testing.assert_allclose(rank(np.array([2, 1, 2, 4])), [1.5, 0, 1.5, 3])

    def test_correlation_handles_constant_and_perfect_data(self):
        rows = [row(i) for i in range(1, 8)]
        result = run_analysis(rows, {'method': 'correlation', 'metrics': ['gold', 'damage']})
        self.assertEqual(result['rows'][0]['pearson'], 1)
        for item in rows:
            item['damage'] = 1
        result = run_analysis(rows, {'method': 'correlation', 'metrics': ['gold', 'damage']})
        self.assertIsNone(result['rows'][0]['pearson'])
        self.assertIsNone(result['rows'][0]['spearman'])

    def test_deduplicate_only_changes_analysis_view(self):
        source = [row(1), {**row(1), 'matchKey': 'duplicate'}]
        before = copy.deepcopy(source)
        unique, duplicates = deduplicate(source)
        self.assertEqual(len(unique), 1)
        self.assertEqual(duplicates, [{'excluded': 'duplicate', 'retained': '1'}])
        self.assertEqual(source, before)
        source[1]['date'] = '2026-11-01'
        self.assertEqual(len(deduplicate(source)[0]), 2)

    def test_comparison_counts_games_not_players(self):
        rows = [row(g, hero=h, gold=g+offset) for g in range(1, 7)
                for h, offset in [('甲', 20), ('乙', 0)] for _ in range(5)]
        result = run_analysis(rows, {'method': 'compare', 'metrics': ['gold'],
                                    'dimension': 'hero', 'groupA': '甲', 'groupB': '乙'})
        self.assertEqual(result['rows'][0]['nA'], 6)
        self.assertEqual(result['rows'][0]['difference'], 20)
        self.assertEqual(result['rows'][0]['ciLow'], 20)
        self.assertIn('配对', result['rows'][0]['design'])

    def test_comparison_small_sample_does_not_claim_significance(self):
        rows = [row(1, '甲'), row(2, '乙')]
        result = run_analysis(rows, {'method': 'compare', 'metrics': ['gold'],
                                    'groupA': '甲', 'groupB': '乙'})
        self.assertEqual(result['status'], 'insufficient')
        self.assertEqual(result['rows'], [])

    def test_zero_mad_does_not_create_false_anomalies(self):
        result = run_analysis([row(i, gold=1) for i in range(1, 9)],
                              {'method': 'anomaly', 'metrics': ['gold']})
        self.assertTrue(all(r['deviation'] is None for r in result['rows']))
        self.assertTrue(all(r['flag'] == '尺度为零' for r in result['rows']))

    def test_cluster_deterministic_and_pca_variance(self):
        rows = [row(i, damage=i*i) for i in range(1, 22)]
        spec = {'method': 'cluster', 'metrics': ['gold', 'damage'], 'clusters': 3}
        first, second = run_analysis(rows, spec), run_analysis(rows, spec)
        self.assertEqual(first['members'], second['members'])
        self.assertEqual(sum(g['n'] for g in first['rows']), 21)
        result = run_analysis(rows, {**spec, 'method': 'pca'})
        self.assertAlmostEqual(sum(result['variance']), 100, places=3)

    def test_association_support_and_lift(self):
        rows = [row(g, h) for g in range(1, 7) for h in ['甲', '乙', '丙', '丁', '戊']]
        result = run_analysis(rows, {'method': 'association', 'metrics': ['gold']})
        self.assertTrue(result['rows'])
        self.assertEqual(result['rows'][0]['support'], 1)
        self.assertEqual(result['rows'][0]['lift'], 1)

    def test_temporal_split_keeps_matches_and_dates_together(self):
        rows = [row(i, date=f'2026-10-{i:02d}') for i in range(1, 21)]
        rows.append(row(1, date='2026-10-20'))
        rows.append(row(21, date='not-a-date'))
        train, test, cutoff = temporal_split(rows)
        self.assertFalse({r['matchKey'] for r in train} & {r['matchKey'] for r in test})
        self.assertTrue(all(r['date'] < cutoff for r in train))
        self.assertTrue(all(r['date'] >= cutoff for r in test))

    def test_regression_uses_later_games_for_holdout(self):
        rows = [row(i, gold=i, damage=2*i+3, date=f'2026-10-{i:02d}') for i in range(1, 25)]
        result = regression(rows, ['gold', 'damage'])
        self.assertEqual(result['status'], 'ok')
        self.assertLess(result['rows'][0]['mae'], result['rows'][0]['baselineMae'])
        self.assertEqual(result['rows'][0]['trainMatches']+result['rows'][0]['testMatches'], 24)

    def test_prediction_is_real_holdout_and_beats_baseline_on_signal(self):
        rows = []
        from datetime import date, timedelta
        for i in range(80):
            win = i % 2 == 0
            for camp in ('blue', 'red'):
                for j in range(5):
                    hero = ('强' if (win == (camp=='blue')) else '弱') + str(j)
                    rows.append(row(i+1, hero, camp=camp, isOwn=camp=='blue',
                                    result=('win' if win else 'loss') if camp=='blue' else ('loss' if win else 'win'),
                                    date=str(date(2026, 1, 1)+timedelta(days=i))))
        result = prediction(rows)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['rows'][0]['testMatches'], 20)
        self.assertLess(result['rows'][0]['brier'], result['rows'][0]['baselineBrier'])
        # Terminal gold is never a prediction feature.
        for r in rows:
            r['gold'] = 100000 if r['result']=='loss' else -100000
        self.assertEqual(prediction(rows)['rows'], result['rows'])


class StudioApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = ROOT / 'test-results' / ('studio-unit-' + uuid.uuid4().hex)
        cls.root.mkdir(parents=True)
        cls.db_path = cls.root / 'training.sqlite3'
        make_db(cls.db_path)
        with sqlite3.connect(cls.db_path) as c:
            c.execute('CREATE TABLE postgame_images (id TEXT PRIMARY KEY,result TEXT,updated_at REAL)')
        cls.matches = cls.root / 'matches'; cls.matches.mkdir()
        candidate = bundle('score-is-not-outcome', '2026-10-09', 900, C_BLUE, C_RED,
                           scores={'blue': 30, 'red': 1})
        (cls.matches / 'unconfirmed.json').write_text(json.dumps(candidate), encoding='utf-8')
        app = FastAPI()
        app.include_router(create_studio_router(cls.db_path, cls.matches, cls.root/'imports', cls.root/'studio.sqlite3'))
        cls.client = TestClient(app)

    def test_pov_and_kills_do_not_establish_team_or_outcome(self):
        repo = StudioRepository(self.db_path, self.matches, self.root/'imports')
        game = next(m for m in repo.get()['matches'] if m['key']=='score-is-not-outcome')
        self.assertIsNone(game['ownCamp'])
        rows = [r for r in repo.get()['rows'] if r['matchKey']==game['key']]
        self.assertTrue(all(r['result']=='unknown' for r in rows))
        detail = self.client.get('/api/studio/match/score-is-not-outcome').json()
        self.assertEqual(detail['result'], 'unknown')

    def test_dataset_isolation_and_validation(self):
        capture = self.client.post('/api/studio/dataset', json={'dataset':'screenshots'}).json()
        self.assertEqual(capture['total'], 0)
        self.assertEqual(self.client.post('/api/studio/run', json={'dataset':'screenshots','method':'prediction'}).status_code, 400)
        self.assertEqual(self.client.post('/api/studio/run', json={'metrics':['__import__']}).status_code, 400)
        self.assertEqual(self.client.post('/api/studio/run', json={'method':'unknown'}).status_code, 400)
        self.assertEqual(self.client.post('/api/studio/dataset', json={'filters':{'sources':'db'}}).status_code, 400)

    def test_snapshot_save_conflict_and_html_escape(self):
        spec = {'method':'describe','metrics':['gold'],'dimension':'hero'}
        result = self.client.post('/api/studio/run', json=spec).json()
        response = self.client.post('/api/studio/reports', json={'title':'<script>x</script>', 'note':'<img src=x onerror=alert(1)>', 'spec':spec,'fingerprint':result['meta']['fingerprint']})
        self.assertEqual(response.status_code, 200, response.text)
        report_id = response.json()['id']
        snapshot = self.client.get('/api/studio/reports/'+report_id).json()
        self.assertEqual(snapshot['result']['rows'], result['rows'])
        export = self.client.get('/api/studio/reports/'+report_id+'/export').text
        self.assertNotIn('<script>x</script>', export)
        self.assertIn('&lt;script&gt;', export)
        conflict = self.client.post('/api/studio/reports', json={'title':'旧结果','spec':spec,'fingerprint':'stale'})
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(self.client.get('/api/studio/reports/not-found').status_code, 404)

    def test_workspace_and_views(self):
        response = self.client.get('/api/studio/workspace')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['methods']), 10)
        self.assertEqual(response.json()['overview']['wins'], 2)
        for section in ('matches','players','heroes','process','lane-matchups','bp','objectives','scouting'):
            self.assertEqual(self.client.get('/api/studio/view/'+section).status_code, 200)
        identity = self.client.get('/api/studio/identity').json()
        self.assertTrue(identity['matchTeams'])
        self.assertTrue(all(group['sides'] for group in identity['matchTeams']))
        self.assertTrue(all(len(side['players']) >= 2 for group in identity['matchTeams'] for side in group['sides']))
        compact = self.client.get('/api/studio/view/heroes', params={'compact':'1'}).json()['heroes']
        self.assertTrue(compact)
        self.assertTrue(all('matches' not in hero for hero in compact))

    def test_lightweight_rows_filter_and_limit(self):
        response = self.client.get('/api/studio/rows', params={'source':'db,bundle','limit':3})
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertLessEqual(len(payload['rows']), 3)
        self.assertGreater(payload['total'], 0)
        self.assertTrue(all('process' not in row for row in payload['rows']))
        sample = payload['rows'][0]
        for kind, key, name in [('player', 'label', sample['label']), ('hero', 'hero', sample.get('hero'))]:
            if not name:
                continue
            filtered = self.client.get('/api/studio/rows',
                                       params={'source':'db,bundle','limit':3,'kind':kind,'name':name}).json()
            self.assertGreater(filtered['total'], 0)
            self.assertTrue(all(row.get(key) == name for row in filtered['rows']))
        self.assertEqual(self.client.get('/api/studio/rows', params={'kind':'team'}).status_code, 400)

    def test_backup_restore_is_idempotent(self):
        spec = {'method':'describe','metrics':['gold']}
        result = self.client.post('/api/studio/run', json=spec).json()
        self.client.post('/api/studio/reports', json={'title':'用于备份的研究','spec':spec,'fingerprint':result['meta']['fingerprint']})
        backup = self.client.get('/api/studio/backup')
        self.assertEqual(backup.status_code, 200)
        restored = self.client.post('/api/studio/restore', json=backup.json())
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(restored.json()['added'], 0)
        self.assertGreaterEqual(restored.json()['skipped'], 1)
        self.assertEqual(self.client.post('/api/studio/restore', json={'schema':'wrong','reports':[]}).status_code, 400)


if __name__ == '__main__':
    unittest.main()
