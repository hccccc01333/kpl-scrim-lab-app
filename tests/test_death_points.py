"""Regression tests for the 掉点 (death-window) analysis layer.

The window is built from two *official measured* timestamp arrays:
  playBaseInfoArr[].deathPosArr[].time        death second
  reportData.playerPosInfo[].revivePosArr[2]  revive second
Team-gold differences come from ecoDistance (~30s samples) and are linearly
interpolated to the window endpoints.  A death with no following revive is a
终局未复活 window whose endpoint is the end of the replay.
"""
import json
import unittest
from pathlib import Path

from depth_api import _diff_interp, _drop_chains, analysis_payload, analyses_catalog, build_facts

ROOT = Path(__file__).resolve().parent.parent


class DeathWindowFactsTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.facts = build_facts(ROOT)
        if not cls.facts.get('replayGames'):
            raise unittest.SkipTest('缺少营地对局详情样本（公开仓库不含对局数据）')

    def test_interpolation_is_approximate_and_rounded_to_ten(self):
        self.assertEqual(_diff_interp([0, 1000, 2000], 600, 150), 500)
        self.assertEqual(_diff_interp([0, 1000], 600, 0), 0)
        self.assertEqual(_diff_interp([0, 1000], 600, 900), 1000)
        self.assertIsNone(_diff_interp([], 600, 100))

    def test_every_death_becomes_one_window(self):
        counts = self.facts['counts']
        self.assertEqual(counts['dropWindows'], counts['deathPoints'])
        self.assertEqual(counts['dropRevived'] + counts['dropFinal'], counts['dropWindows'])
        self.assertGreater(counts['dropRevived'], 0)
        self.assertGreater(counts['dropFinal'], 0)

    def test_windows_use_measured_revive_or_match_end(self):
        games = {g['id']: g for g in self.facts['replayGames']}
        for w in self.facts['dropWindows']:
            with self.subTest(game=w['game'], hero=w['hero'], t=w['t']):
                self.assertGreaterEqual(w['end'], w['t'])
                self.assertLessEqual(w['windowSec'], 120)
                self.assertEqual(w['loss'], w['diffStart'] - w['diffEnd'])
                self.assertEqual(w['startBlue'], w['diffStart'] if w['camp'] == '蓝' else -w['diffStart'])
                if w['final']:
                    self.assertEqual(w['end'], games[w['game']]['duration'])
                self.assertNotIn('playID', w)
                self.assertNotIn('playerId', w)

    def test_chains_merge_overlapping_windows(self):
        windows = [
            {'game': 'g', 't': 100, 'end': 130, 'camp': '蓝', 'hero': 'A', 'final': False,
             'startBlue': 100, 'endBlue': 400, 'duration': 600},
            {'game': 'g', 't': 105, 'end': 140, 'camp': '红', 'hero': 'B', 'final': False,
             'startBlue': 120, 'endBlue': 500, 'duration': 600},
            {'game': 'g', 't': 300, 'end': 330, 'camp': '蓝', 'hero': 'A', 'final': True,
             'startBlue': 900, 'endBlue': 1000, 'duration': 600},
        ]
        chains = _drop_chains(windows)
        self.assertEqual(len(chains), 2)
        self.assertEqual(chains[0]['n'], 2)
        self.assertEqual(chains[0]['swing'], 400)
        self.assertTrue(chains[1]['final'])

    def test_real_revive_positions_exist_and_follow_deaths(self):
        folders = sorted((ROOT / 'data' / 'official_replays').glob('camp-*/raw.json'))
        if not folders:
            self.skipTest('no local camp replay assets')
        for path in folders[:4]:
            with self.subTest(replay=path.parent.name):
                data = json.loads(path.read_text(encoding='utf-8'))['data']
                deaths, revives = [], []
                for p in data.get('playBaseInfoArr') or []:
                    deaths += [int(x['time']) for x in p.get('deathPosArr') or []]
                for p in (data.get('reportData') or {}).get('playerPosInfo') or []:
                    self.assertTrue(all(len(x) >= 3 for x in p.get('revivePosArr') or []))
                    revives += [int(x[2]) for x in p.get('revivePosArr') or []]
                self.assertGreater(len(deaths), 0)
                self.assertGreater(len(revives), 0)
                self.assertLessEqual(len(revives), len(deaths))


class DeathWindowApiTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.facts = build_facts(ROOT)
        if not cls.facts.get('replayGames'):
            raise unittest.SkipTest('缺少营地对局详情样本（公开仓库不含对局数据）')

    def test_catalog_exposes_two_drop_analyses(self):
        catalog = analyses_catalog(self.facts)
        drops = [a for a in catalog if a['direction'] == '掉点']
        self.assertEqual([a['id'] for a in drops],
                         ['death_point_economy', 'death_point_impact'])
        for a in drops:
            self.assertEqual(a['status'], '可运行')
            self.assertTrue(a['boundary'])
            self.assertTrue(a['fields'])

    def test_single_game_payload_reproduces_per_player_gold_diff(self):
        p = analysis_payload(self.facts, 'death_point_economy')
        self.assertEqual(p['viz'], 'dropwindow')
        self.assertEqual(len(p['teams']), 2)
        for team in p['teams']:
            self.assertEqual(len(team['people']), 5)
            for person in team['people']:
                for w in person['windows']:
                    self.assertEqual(w['loss'], w['diffStart'] - w['diffEnd'])
                    self.assertNotIn('objID', w)
        self.assertEqual(sum(t['deaths'] for t in p['teams']), p['headline']['deaths'])
        self.assertTrue(p['curve'])
        self.assertTrue(p['games'])
        self.assertIn('官方实测', p['note'])
        self.assertIn('插值约数', p['note'])

    def test_game_selector_changes_the_game(self):
        default = analysis_payload(self.facts, 'death_point_economy')
        other = next(g for g in default['games'] if g['id'] != default['selected'])
        p = analysis_payload(self.facts, 'death_point_economy', other['id'])
        self.assertEqual(p['selected'], other['id'])
        self.assertEqual(p['headline']['deaths'], other['deaths'])

    def test_impact_payload_has_honest_aggregation(self):
        p = analysis_payload(self.facts, 'death_point_impact')
        self.assertEqual(p['viz'], 'dropimpact')
        self.assertEqual(p['summary']['n'], self.facts['counts']['dropWindows'])
        self.assertEqual(sum(x['n'] for x in p['phases']), p['summary']['n'])
        self.assertEqual(len(p['points']), p['summary']['n'])
        self.assertLess(p['summary']['chainCount'], p['summary']['n'])
        self.assertEqual(p['summary']['revived'] + p['summary']['final'], p['summary']['n'])
        self.assertEqual(len(p['top']), 20)
        self.assertTrue(p['chains'])
        self.assertIn('不能全记在阵亡头上', p['note'])
        self.assertIn('掉点集群', p['note'])


class DepthEntryRegressionTest(unittest.TestCase):
    """Lock the visible entry point so 掉点 analyses cannot be hidden again.

    2026-11-05 起深度分析只有单条页（#depth/<id>，挂各模块子页签）；原来的
    「全部分析」索引页与各模块页签 100% 重复，已移除，裸 #depth 跳回团队复盘。
    掉点两条分别挂在 比赛（掉点经济）与 战队（掉点代价）的子页签行。
    """

    def test_index_page_is_removed_and_bare_depth_redirects(self):
        js = (ROOT / 'web' / 'studio.js').read_text(encoding='utf-8')
        lines = js.splitlines()
        team_nav = next((l for l in lines if l.strip().startswith("['战队'")), '')
        self.assertNotIn("['depth','深度分析']", team_nav)
        self.assertIn('DEPTH_TABS', js)
        self.assertIn("location.replace('#team')", js)
        self.assertNotIn('renderDepthBlock', js)

    def test_both_drop_analyses_have_module_tabs(self):
        js = (ROOT / 'web' / 'studio.js').read_text(encoding='utf-8')
        lines = js.splitlines()
        match_line = next((l for l in lines if l.strip().startswith("'比赛':[")), '')
        team_line = next((l for l in lines if l.strip().startswith("'战队':[")), '')
        self.assertIn("['death_point_economy','掉点经济']", match_line)
        self.assertIn("['death_point_impact','掉点代价']", team_line)
        self.assertIn("'depth/'+id", js)
        self.assertIn('renderDepthEntry', js)

    def test_single_analysis_page_has_side_tools_and_game_selector(self):
        source = (ROOT / 'web' / 'depth-page.js').read_text(encoding='utf-8')
        css = (ROOT / 'web' / 'depth.css').read_text(encoding='utf-8')
        self.assertIn('export async function renderDepthEntry', source)
        self.assertIn('data-side-select', source)
        self.assertIn("value=\"compare\"", source)
        self.assertIn('.dp-side-tools', css)
        # 掉点经济在单条页也保留 21 局下拉，且切对局要带上当前视角组合重算
        self.assertIn('onGameSelect: value => {gameChoice = value; redraw();}', source)


if __name__ == '__main__':
    unittest.main()
