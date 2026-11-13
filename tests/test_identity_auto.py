"""自动认领规则：≤1 个没见过的昵称自动、≥2 交给教练、教练判断回灌存档。"""
import json
import sqlite3
import unittest
import uuid
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from identity_auto import build_archive, build_plan
from studio_api import create_studio_router
from tests.test_analysis_data import make_db

OWN = '我的训练队'
ENEMY = '星海队'
A = ['我1', '我2', '我3', '我4', '我5']
B = ['敌1', '敌2', '敌3', '敌4', '敌5']


def game(key, blue, red, own_camp='blue', opponent=ENEMY, meta=None, ids=None):
    ids = ids or {}
    players = []
    for camp, nicks in (('blue', blue), ('red', red)):
        for index, nick in enumerate(nicks):
            players.append({'label': nick, 'camp': camp, 'slot': index,
                            'playerId': ids.get(nick)})
    match = {'key': key, 'date': '2026-11-02', 'title': '训练赛',
             'ownCamp': own_camp, 'opponent': opponent, 'players': players}
    if meta:
        match['metaFields'] = meta
    return match


def data(*matches):
    return {'matches': list(matches), 'sheetMatches': []}


def settings(nicks_own=A, nicks_enemy=B):
    roster, aliases, enemy = [], {}, {}
    for index, nick in enumerate(nicks_own):
        player_id = f'p{index + 1}'
        roster.append({'id': player_id, 'name': nick, 'team': OWN, 'position': '', 'tags': []})
        aliases[nick] = player_id
    for index, nick in enumerate(nicks_enemy):
        player_id = f'q{index + 1}'
        roster.append({'id': player_id, 'name': nick, 'team': ENEMY, 'position': '', 'tags': []})
        enemy[nick] = player_id
    return {'teamName': OWN, 'roster': roster, 'aliases': aliases, 'enemyAliases': enemy,
            'teams': [{'id': 'team-1', 'name': ENEMY, 'short': '', 'coach': '', 'note': ''}]}


class AutoClaimTests(unittest.TestCase):
    def test_zero_diff_auto_without_new_identities(self):
        plan = build_plan(data(game('m2', A, B)), settings())
        self.assertEqual(plan['summary']['auto'], 1)
        item = plan['matches'][0]
        self.assertEqual((item['status'], item['ownCampPlan'], item['opponent']), ('auto', 'blue', ENEMY))
        self.assertEqual(plan['deltas']['members'], [])
        self.assertEqual(plan['deltas']['aliases'], {})
        self.assertEqual(plan['deltas']['metas'], [{'key': 'm2', 'ownCamp': 'blue', 'opponent': ENEMY}])

    def test_one_diff_auto_and_infers_smurf(self):
        own_side = A[:4] + ['我5小号']
        plan = build_plan(data(game('m2', own_side, B)), settings())
        item = plan['matches'][0]
        self.assertEqual(item['status'], 'auto')
        self.assertIn('4/5', item['reason'])
        self.assertEqual(plan['deltas']['aliases'].get('我5小号'), 'p5')
        inferred = [b for s in item['sides'] for b in s['binds'] if b['source'] == 'inferred']
        self.assertEqual(len(inferred), 1)

    def test_two_or_more_diffs_go_to_coach(self):
        own_side = A[:3] + ['新人甲', '新人乙']
        plan = build_plan(data(game('m2', own_side, B)), settings())
        item = plan['matches'][0]
        self.assertEqual(plan['summary']['review'], 1)
        self.assertEqual(item['status'], 'review')
        self.assertIn('2 个没见过', item['reason'])
        self.assertIn('新人甲', item['reason'])
        self.assertEqual(plan['deltas']['metas'], [])

    def test_threshold_is_configurable(self):
        own_side = A[:3] + ['新人甲', '新人乙']
        source = data(game('m2', own_side, B))
        self.assertEqual(build_plan(source, settings(), max_diff=2)['summary']['auto'], 1)
        self.assertEqual(build_plan(source, settings(), max_diff=0)['summary']['review'], 1)
        self.assertEqual(build_plan(data(game('m2', A, B)), settings(), max_diff=0)['summary']['auto'], 1)

    def test_sides_can_swap(self):
        plan = build_plan(data(game('m2', B, A, own_camp='red')), settings())
        item = plan['matches'][0]
        self.assertEqual((item['status'], item['ownCampPlan'], item['opponent']), ('auto', 'red', ENEMY))
        self.assertEqual(plan['deltas']['metas'][0]['ownCamp'], 'red')

    def test_conflict_with_original_side_is_review(self):
        # 原始记录说本队在红方，存档名单却整整齐齐落在蓝方：不自动翻边。
        plan = build_plan(data(game('m2', A, B, own_camp='red')), settings())
        self.assertEqual(plan['matches'][0]['status'], 'review')
        self.assertIn('对不上', plan['matches'][0]['reason'])

    def test_cold_start_asks_coach_first(self):
        empty = {'teamName': OWN, 'roster': [], 'aliases': {}, 'enemyAliases': {},
                 'teams': [{'id': 'team-1', 'name': ENEMY}]}
        plan = build_plan(data(game('m1', A, B)), empty)
        self.assertTrue(plan['summary']['coldStart'])
        self.assertEqual(plan['matches'][0]['status'], 'review')

    def test_coach_decision_unlocks_similar_matches(self):
        empty = {'teamName': OWN, 'roster': [], 'aliases': {}, 'enemyAliases': {}, 'teams': []}
        m1 = game('m1', A, B)
        m2 = game('m2', A[:4] + ['我5小号'], B)
        before = build_plan(data(m1, m2), empty)
        self.assertEqual(before['summary']['review'], 2)

        plan = build_plan(data(m1, m2), empty,
                          decisions={'m1': {'ownCamp': 'blue', 'opponent': ENEMY}})
        self.assertEqual(plan['summary']['decided'], 1)
        self.assertEqual(plan['summary']['auto'], 1)
        by_key = {item['key']: item for item in plan['matches']}
        self.assertEqual(by_key['m1']['status'], 'decided')
        self.assertEqual(by_key['m2']['opponent'], ENEMY)
        self.assertEqual(len(plan['deltas']['metas']), 2)
        self.assertGreaterEqual(len(plan['deltas']['members']), 10)
        self.assertEqual(len({m['id'] for m in plan['deltas']['members']}),
                         len(plan['deltas']['members']))

    def test_coach_decision_registers_new_team_and_ignores_bad_keys(self):
        empty = {'teamName': OWN, 'roster': [], 'aliases': {}, 'enemyAliases': {}, 'teams': []}
        plan = build_plan(data(game('m1', A, B)), empty, decisions={
            'm1': {'ownCamp': 'blue', 'opponent': '新对手'},
            '不存在的局': {'ownCamp': 'blue', 'opponent': '幽灵队'},
        })
        self.assertIn('新对手', plan['deltas']['teams'])
        self.assertNotIn('幽灵队', plan['deltas']['teams'])
        self.assertEqual(plan['deltas']['metas'][0]['opponent'], '新对手')
        self.assertEqual(plan['summary']['decided'], 1)

    def test_side_confirmation_alone_seeds_own_lineup(self):
        # 教练只确认了「本队在蓝方」、对手还没命名：本队名单照样学，对手侧不记。
        plain = {'teamName': OWN, 'roster': [], 'aliases': {}, 'enemyAliases': {},
                 'teams': [{'id': 'team-1', 'name': ENEMY}]}
        seed = game('m1', A, B, opponent='', meta=['ownCamp', 'opponent'])
        plan = build_plan(data(seed), plain)
        self.assertEqual(plan['summary']['archiveTeams'], {OWN: 5})
        self.assertEqual(plan['matches'][0]['status'], 'review')

    def test_confirmed_match_is_archive_source(self):
        # 教练只保存过分边、没逐个认领：整局十人名单照样能当存档。
        plain = {'teamName': OWN, 'roster': [], 'aliases': {}, 'enemyAliases': {}, 'teams': []}
        seed = game('m1', A, B, meta=['ownCamp', 'opponent'])
        plan = build_plan(data(seed, game('m2', A, B)), plain)
        self.assertEqual(plan['summary']['auto'], 2)
        self.assertEqual(len(plan['deltas']['members']), 10)

    def test_ambiguous_nickname_is_dropped_from_archive(self):
        mixed = settings()
        mixed['aliases']['通用昵称'] = 'p1'
        seed = game('m1', A, ['通用昵称'] + B[:4], meta=['ownCamp', 'opponent'])
        archive, _ = build_archive(data(seed), mixed)
        self.assertNotIn('通用昵称', archive.get(OWN, {}))
        self.assertNotIn('通用昵称', archive.get(ENEMY, {}))

    def test_roster_cap_sends_match_to_coach(self):
        full = settings(A[:4], B)
        for index in range(30):
            full['roster'].append({'id': f'x{index}', 'name': f'队员{index}',
                                   'team': OWN, 'position': '', 'tags': []})
        self.assertEqual(len(full['roster']), 39)
        # 再补一个到 40，随后「新人甲」无法建档。
        full['roster'].append({'id': 'x99', 'name': '队员99', 'team': OWN, 'position': '', 'tags': []})
        plan = build_plan(data(game('m2', A[:4] + ['新人甲'], B)), full)
        self.assertEqual(plan['matches'][0]['status'], 'review')
        self.assertIn('名单已满', plan['matches'][0]['reason'])

    def test_endpoint_returns_preview_without_writing(self):
        root = Path(__file__).resolve().parents[1] / 'test-results' / ('auto-' + uuid.uuid4().hex)
        root.mkdir(parents=True)
        db = root / 'training.sqlite3'
        make_db(db)
        with sqlite3.connect(db) as connection:
            body = json.loads(connection.execute('SELECT body FROM settings WHERE id=1').fetchone()[0])
            body.update(settings())
            connection.execute('UPDATE settings SET body=? WHERE id=1',
                               (json.dumps(body, ensure_ascii=False),))
        matches = root / 'matches'
        matches.mkdir()
        app = FastAPI()
        app.include_router(create_studio_router(db, matches, root / 'imports'))
        client = TestClient(app)

        response = client.post('/api/studio/identity/auto-claim', json={'maxDiff': 1})
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertIn('summary', payload)
        self.assertIn('deltas', payload)
        self.assertEqual(payload['options']['maxDiffChoices'], [0, 1, 2])
        bad = client.post('/api/studio/identity/auto-claim', json={'decisions': ['bad']})
        self.assertEqual(bad.status_code, 400)


if __name__ == '__main__':
    unittest.main()


def test_eligible_filters_before_limit():
    """limit 是「最多返回几局可用对局」，不能先截断再过滤把合格局挤掉。"""
    import identity_auto

    def incomplete(index):
        return {'key': f'bad-{index}', 'date': '2026-11-10',
                'players': [{'label': f'x{index}', 'camp': 'blue'}]}

    def complete(index):
        return {'key': f'ok-{index}', 'date': '2026-11-01',
                'players': ([{'label': f'b{index}{slot}', 'camp': 'blue'} for slot in range(5)]
                            + [{'label': f'r{index}{slot}', 'camp': 'red'} for slot in range(5)])}

    data = {'matches': [incomplete(index) for index in range(10)] + [complete(0)]}
    picked = identity_auto.eligible(data, limit=1)
    assert [match['key'] for match in picked] == ['ok-0']
