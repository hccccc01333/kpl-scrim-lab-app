import json
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from match_review import build_panorama, create_review_router


HEROES = [('百里守约', 1611), ('关羽', 538), ('妲己', 1613), ('孙悟空', 750), ('钟馗', 1168),
          ('公孙离', 1031), ('吕布', 296), ('貂蝉', 551), ('兰陵王', 1799), ('张良', 1760)]


def bundle(duration=60, official=True):
    players = []
    for index, (hero, entity) in enumerate(HEROES):
        camp = 'blue' if index < 5 else 'red'
        players.append({
            'key': f'{camp}-{index % 5}', 'camp': camp, 'side': camp, 'slot': index % 5,
            'hero': hero, 'nickname': f'选手{index}', 'replayEntityId': entity,
            'final': {'kills': 5, 'deaths': 1, 'assists': 4, 'totalGold': 10000,
                      'damage': 30000, 'taken': 20000, 'participation': 60,
                      'rating': 10.5, 'complete': True},
        })
    match = {
        'key': 'm1', 'title': '测试局', 'date': {'text': '2026-01-01'},
        'duration': duration, 'mode': '5v5', 'scores': {'blue': 10, 'red': 5},
        'ownCamp': 'blue', 'winnerCamp': 'blue',
        'result': {'winMvp': {'entityId': 538}, 'loseMvp': [{'entityId': 1031}]},
    }
    if official:
        match['officialReplay'] = {'id': 'camp-1'}
    return {
        'schema': 'kpl-match-data-v1', 'match': match, 'players': players,
        'team': {'timeline': [
            {'gameTime': 0, 'blueGold': 0, 'redGold': 0},
            {'gameTime': 30, 'blueGold': 1200, 'redGold': 1000},
            {'gameTime': 60, 'blueGold': 2600, 'redGold': 1800},
        ]},
    }


def official_files(folder):
    folder.mkdir(parents=True)
    players = [{'playerId': f'p{index}', 'camp': str(1 + index // 5),
                'hero': hero, 'kills': 5, 'deaths': 1, 'assists': 4,
                'ratings': {'grow': '9000', 'battle': '8000', 'survive': '7000',
                            'hurtHero': '6000', 'kda': '5000'}, 'defeatAcntRatio': '50'}
               for index, (hero, _) in enumerate(HEROES)]
    raw = {'data': {'keyEventArr': [
        {'eventType': 'dragontower', 'dtData': {
            'killTime': '39000', 'dtType': '1', 'dtID': '10', 'dtCamp': '2',
            'killerCamp': '1', 'killerId': '750', 'viewX': 24, 'viewY': -2,
            'kills': [{'camp': '1', 'killerId': '750'}]}},
        {'eventType': 'dragontower', 'dtData': {
            'killTime': '50000', 'dtType': '2', 'dtID': '17', 'dtCamp': '2',
            'killerCamp': '1', 'killerId': '1611', 'viewX': 0, 'viewY': 0,
            'kills': []}},
        {'eventType': 'battle', 'dtData': {}},
    ]}}
    normalized = {'match': {'durationSec': 60}, 'players': players,
                  'events': {'key': []}}
    positions = {'players': [
        {'playerId': f'p{index}', 'posArr': [[-50 + second, -50 + second] for second in range(60)]}
        for index in range(10)
    ]}
    (folder / 'meta.json').write_text(json.dumps({'files': {'raw': 'raw.json',
                                                            'positions': 'positions.json'}}),
                                      encoding='utf-8')
    (folder / 'raw.json').write_text(json.dumps(raw, ensure_ascii=False), encoding='utf-8')
    (folder / 'normalized.json').write_text(json.dumps(normalized, ensure_ascii=False),
                                            encoding='utf-8')
    (folder / 'positions.json').write_text(json.dumps(positions, ensure_ascii=False),
                                           encoding='utf-8')


def build_files(folder):
    folder.mkdir(parents=True)
    players = {}
    for index, (hero, _) in enumerate(HEROES):
        players[f'选手{index}'] = {
            'summary': {'hero': hero, 'camp': str(1 + index // 5)},
            'items': [{'t': 10, 'id': '1', 'name': '鞋'},
                      {'t': 30, 'id': '2', 'name': '剑'}],
        }
    (folder / 'builds.json').write_text(json.dumps({'players': players}, ensure_ascii=False),
                                        encoding='utf-8')


class MatchReviewTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.matches = self.root / 'data' / 'matches'
        self.official = self.root / 'data' / 'official_replays'
        self.builds = self.root / 'data' / 'builds'
        self.matches.mkdir(parents=True)
        (self.root / 'resources').mkdir()
        (self.root / 'resources' / 'catalog.json').write_text(json.dumps({'entries': []}),
                                                              encoding='utf-8')
        (self.matches / 'm1.json').write_text(json.dumps(bundle(), ensure_ascii=False),
                                               encoding='utf-8')
        official_files(self.official / 'camp-1')
        build_files(self.builds / 'abc')

    def tearDown(self):
        self.temp.cleanup()

    def test_joins_all_sources(self):
        payload = build_panorama(self.matches, self.official, self.builds, 'm1', self.root)
        self.assertIsNotNone(payload)
        self.assertEqual(payload['schema'], 'kpl-match-panorama-v1')
        self.assertEqual(len(payload['players']), 10)
        self.assertEqual(payload['players'][1]['mvp'], 'win')
        self.assertEqual(payload['players'][5]['mvp'], 'lose')
        self.assertEqual(payload['players'][0]['official']['grow'], 9000)
        self.assertEqual(payload['coverage']['resources'], 1)
        self.assertEqual(payload['coverage']['structures'], 1)
        self.assertEqual(payload['coverage']['positions']['players'], 10)
        self.assertEqual(payload['coverage']['builds']['players'], 10)
        self.assertFalse(payload['coverage']['heroKills'])
        self.assertEqual(len(payload['gold']['points']), 3)
        self.assertEqual(len(payload['phases']), 3)
        self.assertTrue(payload['positions']['players']['blue-0']['points'])
        self.assertTrue(payload['positions']['players']['blue-0']['phases'][0]['heat'])

    def test_events_and_phase_metrics(self):
        payload = build_panorama(self.matches, self.official, self.builds, 'm1', self.root)
        events = payload['events']
        self.assertEqual([event['kind'] for event in events], ['resource', 'structure'])
        self.assertEqual(events[0]['zone'], 'red_half')
        self.assertEqual(events[0]['killer'], '选手3')
        self.assertEqual(events[1]['ownerCamp'], 'red')
        self.assertIsNone(events[1]['x'])
        self.assertEqual(payload['phases'][0]['goldChange'], 200)
        self.assertTrue(payload['insights'])
        self.assertTrue(any('不含英雄击杀' in note for note in payload['notes']))

    def test_missing_optional_sources(self):
        (self.matches / 'm1.json').write_text(
            json.dumps(bundle(official=False), ensure_ascii=False), encoding='utf-8')
        payload = build_panorama(self.matches, self.root / 'missing', self.root / 'missing',
                                 'm1', self.root)
        self.assertIsNotNone(payload)
        self.assertEqual(payload['events'], [])
        self.assertEqual(payload['coverage']['positions']['players'], 0)
        self.assertEqual(payload['coverage']['builds']['players'], 0)
        self.assertEqual(len(payload['players']), 10)
        self.assertTrue(payload['notes'])

    def test_router(self):
        app = FastAPI()
        app.include_router(create_review_router(self.matches, self.official, self.builds, self.root))
        client = TestClient(app)
        self.assertEqual(client.get('/api/review/m1').status_code, 200)
        self.assertEqual(client.get('/api/review/unknown').status_code, 404)


if __name__ == '__main__':
    unittest.main()
