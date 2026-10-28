"""Regress the actual 小乔 correction; unknown labels must not become guesses."""
import json
from pathlib import Path
import unittest

from hero_names import resolve_name
from ocr import recognize

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = Path('D:/caches/temp/codex-clipboard-dfbc8fc2-dcd3-4543-b74f-81a9052dfd4d.png')


class NamePolicyTests(unittest.TestCase):
    def setUp(self):
        self.entries = [{'id':name, 'name':name, 'kind':'hero'} for name in ['小乔','大乔','妲己','刘邦','刘备','刘禅']]

    def test_near_text_is_candidate_not_accepted_identity(self):
        result = resolve_name([{'raw':'小还','confidence':.87,'variant':'label'}], self.entries)
        self.assertIsNone(result['accepted'])
        self.assertEqual(result['candidates'][0]['name'], '小乔')
        self.assertNotIn('妲己', [c['name'] for c in result['candidates']])

    def test_exact_name_beats_other_visual_identity(self):
        result = resolve_name([{'raw':'小乔','confidence':.96,'variant':'label'}], self.entries)
        self.assertEqual(result['accepted']['name'], '小乔')

    def test_unclear_or_conflicting_text_does_not_autofill(self):
        for readings in ([{'raw':'刘牌','confidence':.9}], [{'raw':'小乔','confidence':.93},{'raw':'大乔','confidence':.94}], [{'raw':'小乔','confidence':.3}]):
            self.assertIsNone(resolve_name(readings, self.entries)['accepted'])

    @unittest.skipUnless(SAMPLE.exists(), 'Original local screenshot unavailable')
    def test_original_skin_portrait_sample(self):
        result = recognize(SAMPLE.read_bytes())
        truth = {'left':['西施','李信','甄姬','孙尚香','刘禅'], 'right':['小乔','马超','后羿','弈星','大乔']}
        accepted = []
        for p in result['players']:
            if 'hero' in p['fields']:
                self.assertEqual(p['fields']['hero']['value'], truth[p['side']][p['slot']])
                accepted.append((p['side'],p['slot'],p['fields']['hero']['value']))
        region = next(r for r in result['visuals'] if r['side']=='right' and r['slot']==0)
        self.assertEqual(region['method'], 'printed-name')
        self.assertEqual(region['candidates'][0]['name'], '小乔')
        self.assertNotIn('妲己', [c['name'] for c in region['candidates']])
        self.assertEqual(region['status'], 'uncertain')
        report = {'sample':str(SAMPLE),'identitySource':'printed-name','exactAccepted':accepted,
                  'unfilled':10-len(accepted),'xiaoqiaoStatus':region['status'],
                  'note':'Single low-resolution sample; this is not an overall accuracy estimate.'}
        (ROOT/'test-results').mkdir(exist_ok=True)
        (ROOT/'test-results'/'name-first-regression.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__ == '__main__':
    unittest.main()
