"""针对「继续找 BUG」审计发现的数据口径/缓存回归。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'v3'))

import analysis_data  # noqa: E402
import analysis_profile  # noqa: E402
import depth_api  # noqa: E402
import match_facts  # noqa: E402


def repository():
    return analysis_data.AnalysisRepository(
        ROOT / 'data' / 'training.sqlite3',
        ROOT / 'data' / 'matches',
        ROOT / 'data' / 'imports',
        ROOT / 'data' / 'official_replays')


class BugfixAuditTests(unittest.TestCase):
    def test_overview_ten_min_lead_counts_wins_from_match_result(self):
        overview = repository().overview({})
        lead = overview.get('tenMinLead') or '0/0'
        wins, led = (int(part) for part in lead.split('/'))
        self.assertGreater(led, 0)
        self.assertGreater(wins, 0, '逐局事实没有 result 字段，不能再把胜局算成 0')

    def test_mastery_win_rates_are_not_all_null(self):
        facts = depth_api.build_facts(str(ROOT))
        rows = depth_api.analysis_payload(facts, 'mastery')['players']
        self.assertGreater(sum(r.get('winRate') is not None for r in rows), 0)
        self.assertGreater(sum((r.get('benchWinRate') or 0) != 0 for r in rows), 0)
        self.assertTrue(any(r.get('winDelta') is not None for r in rows))

    def test_data_signature_tracks_every_file_not_only_newest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            camp = root / 'camp'
            camp.mkdir()
            first = camp / 'a.json'
            second = camp / 'b.json'
            first.write_text('{}', encoding='utf-8')
            second.write_text('{}', encoding='utf-8')
            # 让 a 明确早于 b；旧签名只看最大 mtime，改 a 不会变。
            import os
            os.utime(first, (1, 1))
            os.utime(second, (2, 2))
            before = match_facts.data_signature(root / 'replays', camp)
            first.write_text('{"changed": true}', encoding='utf-8')
            os.utime(first, (3, 3))
            after = match_facts.data_signature(root / 'replays', camp)
            self.assertNotEqual(before, after)

    def test_down_metric_target_achievement_is_inverted(self):
        rows = []
        for index in range(12):
            before = '2026-01-01' if index < 6 else '2026-02-01'
            rows.append({'playerId': 'p1', 'date': before,
                         'taken': 2000 if index < 6 else (1800 if index % 2 else 2200),
                         'minutes': 20})
        result = analysis_profile.training_effect(rows, {
            'metric': 'tpm', 'player_ids': ['p1'],
            'start_date': '2026-02-01', 'end_date': '2026-02-01',
            'target': 100})
        self.assertTrue(result['available'])
        self.assertEqual(result['targetRate'], 50.0)

    def test_hero_detail_league_uses_total_over_minutes(self):
        from v3 import serve

        repo = repository()
        hero_rows, _ = repo._aggregate_rows({'sources': list(serve.DEFAULT_SOURCES),
                                             'hero': '铠'})
        hero_rows = [row for row in hero_rows if row.get('isOwn')]
        expected = (round(sum(row['gold'] for row in hero_rows)
                          / sum(row['minutes'] for row in hero_rows))
                    if hero_rows else None)
        payload = serve.hero_detail('铠', repo)
        self.assertEqual(payload['league']['gpm']['hero'], expected)


if __name__ == '__main__':
    unittest.main()
