"""对局复盘 API 回归：外部事实里的 NaN 不能把严格 JSON 响应打成 500。"""
import json
import math
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bp_facts  # noqa: E402


def detail():
    return {
        'key': 'channel-regression',
        'ownCamp': 'blue',
        'duration': 600,
        'players': [
            {'camp': 'blue', 'position': '对抗路', 'hero': '甲'},
            {'camp': 'red', 'position': '对抗路', 'hero': '乙'},
        ],
        'draft': {'picks': {'left': [{'name': '甲'}], 'right': [{'name': '乙'}]},
                  'bans': {'left': [], 'right': []}},
    }


def test_lane_strength_ignores_non_finite_scores_in_ranking():
    heroes = {
        '甲': {'wr': math.nan, 'wrAdj': math.nan, 'wrAdj30d': 52.0, 'pick': 8.0},
        '乙': {'wr': 50.0, 'wrAdj': math.nan, 'wrAdj30d': math.nan, 'pick': 6.0},
        '丙': {'wr': 53.0, 'wrAdj': 53.0, 'wrAdj30d': 53.0, 'pick': 7.0},
    }
    pools = {'对抗路': ['甲', '乙', '丙']}

    top = bp_facts._lane_strength(heroes, pools, '对抗路', '甲')

    assert top['rank'] == 2 and top['size'] == 2  # 丙 > 甲；乙的 NaN 不冒充 0 分垫底
    assert top['role'] == '对抗路'
    assert top['wr'] is None and top['wrAdj'] is None
    assert top['wrAdj30d'] == 52.0
    json.dumps(top, allow_nan=False)


def test_all_nan_strength_row_has_no_strength_card():
    heroes = {'甲': {'wr': math.nan, 'wrAdj': math.nan, 'wrAdj30d': math.nan,
                     'wr7d': math.nan, 'pick': 8.0, 'tier': 'T3'}}

    assert bp_facts._lane_strength(heroes, {'对抗路': ['甲']}, '对抗路', '甲') is None


def test_match_facts_endpoint_returns_200_with_null_metrics(monkeypatch):
    ladder = {
        'heroes': {
            '甲': {'wr': math.nan, 'wrAdj': math.nan, 'wrAdj30d': math.nan,
                   'wr7d': math.nan, 'pick': 8.0},
            '乙': {'wr': math.nan, 'wrAdj': math.nan, 'wrAdj30d': math.nan,
                   'wr7d': math.nan, 'pick': 6.0},
        },
        'rolePools': {'对抗路': ['甲', '乙']},
        'pairs': [],
        'bracket': '巅峰千强',
        'windowEnd': '2026-11-27',
    }
    monkeypatch.setattr(bp_facts, '_load', lambda name: ladder if name == 'lane_matchups.json' else {})
    app = FastAPI()

    @app.get('/api/matches/{key}')
    def match_api(key: str):
        # 与 v3/serve.py 的单局接口一样，直接返回事实字典，走 FastAPI 的严格 JSON 编码。
        return {'key': key, 'bpFacts': bp_facts.for_match(detail())}

    with TestClient(app) as client:
        response = client.get('/api/matches/channel-regression')

    assert response.status_code == 200
    body = response.json()
    lane = body['bpFacts']['ladder']['lanes'][0]
    assert lane['strength'] == {'mine': None, 'foe': None}
    assert lane['minePick'] == 8.0 and lane['foePick'] == 6.0
    json.dumps(body, allow_nan=False)


def test_nested_non_finite_values_are_normalized_at_facts_boundary():
    payload = {'values': [math.nan, math.inf, -math.inf, 1.0], 'nested': {'x': math.nan}}
    assert bp_facts._json_safe(payload) == {'values': [None, None, None, 1.0], 'nested': {'x': None}}
