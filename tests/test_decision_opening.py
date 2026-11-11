"""对手开局路线与热区（decision_opening）测试。"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TESTS = Path(__file__).resolve().parent
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

import decision_facts  # noqa: E402
import decision_opening  # noqa: E402
import decision_fixtures as fx  # noqa: E402


# ---------------------------------------------------------------------------
# 造数工具
# ---------------------------------------------------------------------------
def segments(spec, seconds=240):
    """spec: [(until_second, (x, y)), ...] → 逐秒坐标列表（0 起）。"""
    points = []
    for until, point in spec:
        while len(points) < until:
            points.append((float(point[0]), float(point[1])))
    assert len(points) == seconds
    return points


def constant(value, seconds=240):
    return [(float(value[0]), float(value[1]))] * seconds


def retag_enemy(root, seq, tag):
    path = Path(root) / 'camp_details' / f'{seq}.json'
    payload = json.loads(path.read_text(encoding='utf-8'))
    data = payload['data']
    own_camp = int(data['head']['acntCamp'])
    key = 'redRoles' if own_camp == 1 else 'blueRoles'
    for role in data[key]:
        basic = role.setdefault('basicInfo', {})
        basic['playerId'] = f"{tag}-{basic.get('playerId') or ''}"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')


# ---------------------------------------------------------------------------
# 单局路线 + 采样点 + 未定标热区
# ---------------------------------------------------------------------------
def test_single_game_route_sample_points_and_relative_heat(tmp_path):
    positions = fx.make_abs_positions({
        '2-0': segments([(80, (-40, -40)), (160, (40, -40)), (240, (40, 40))]),
    })
    fx.write_case(tmp_path, '2001', positions_payload=positions)
    facts = fx.load_fixture_facts(tmp_path)

    report = decision_opening.opening_report(facts)
    assert report['available'] is True
    assert report['filters'] == {'opponent': None, 'lane': None, 'dateFrom': None,
                                 'dateTo': None, 'side': 'enemy'}
    coverage = report['coverage']
    assert coverage['games'] == 1
    assert coverage['positionGames'] == 1
    assert coverage['routes'] == 1
    assert coverage['skippedRoutes'] == 4        # 其余 4 名对手选手没有位置数据
    assert coverage['clusters'] == 1
    assert coverage['calibrated'] is False
    assert coverage['relative'] is True
    assert coverage['clusterThreshold'] == 18.0
    assert coverage['sampleUntilSec'] == 240
    assert coverage['sampleStepSec'] == 5

    assert report['lanes'] == [{'lane': '对抗路', 'routes': 1, 'clusters': 1,
                                'enough': False}]
    assert len(report['routes']) == 1
    route = report['routes'][0]
    assert route['lane'] == '对抗路'
    assert route['side'] == 'enemy'
    assert route['count'] == 1
    assert route['enough'] is False
    assert route['games'] == 1
    assert route['gameIds'] == ['2001']
    assert route['avgDistance'] is None

    representative = route['representative']
    assert representative['game'] == '2001'
    assert representative['player'] == '2-0'
    assert representative['hero'] == '吕布'
    assert representative['lane'] == '对抗路'
    assert representative['times'] == [float(second) for second in range(0, 240, 5)]
    assert len(representative['points']) == 48
    assert representative['points'][0] == [0.0, 0.0]
    assert representative['points'][-1] == [1.0, 1.0]
    # 未定标：按 positionBounds 归一化后三等分 → 左上蓝方野区 / 右上红方野区 / 右下红方发育路
    assert route['zoneSequence'] == ['蓝方野区', '红方野区', '红方发育路']
    assert route['zones'] == [
        {'name': '蓝方野区', 'samples': 16, 'dwellSec': 80},
        {'name': '红方野区', 'samples': 16, 'dwellSec': 80},
        {'name': '红方发育路', 'samples': 16, 'dwellSec': 80},
    ]

    heat = report['heat']
    assert heat['grid'] == 20
    assert heat['games'] == 1
    assert heat['total'] == 240
    assert heat['max'] == 80
    assert heat['unit'] == 'relative-normalized'
    assert heat['cells'] == [
        {'x': 0, 'y': 0, 'n': 80},
        {'x': 19, 'y': 0, 'n': 80},
        {'x': 19, 'y': 19, 'n': 80},
    ]
    assert sum(cell['n'] for cell in heat['cells']) == 240

    # 单局 → 样本不足
    assert report['selected']['games'] == 1
    assert report['selected']['enough'] is False
    assert '样本不足' in report['selected']['note']
    assert len(report['opponents']) == 1
    assert report['opponents'][0]['replayGames'] == 1

    notes = report['notes']
    assert '仅收录本批 1 局回放' in notes[0]
    assert '不能推断对手全部比赛习惯' in notes[0]
    assert '每名对手目前 1 局回放' in notes[1]
    assert '样本不足' in notes[1]
    assert any('positionBounds' in note for note in notes)
    json.dumps(report)  # 必须可序列化给 API


def test_calibrated_positions_use_unit_space(tmp_path):
    positions = fx.make_abs_positions({
        '2-0': segments([(80, (-40, -40)), (160, (40, 40)), (240, (0.5, 0.5))]),
    })
    fx.write_case(tmp_path, '2101', positions_payload=positions, calibration=True)
    facts = fx.load_fixture_facts(tmp_path)

    report = decision_opening.opening_report(facts)
    coverage = report['coverage']
    assert coverage['calibrated'] is True
    assert coverage['relative'] is False
    assert coverage['clusterThreshold'] == 0.18
    assert report['heat']['unit'] == 'mapWidth'
    assert any('地图宽度' in note for note in report['notes'])

    route = report['routes'][0]
    points = route['representative']['points']
    assert len(points) == 48
    assert points[0] == pytest.approx([0.123, 0.123], abs=1e-3)
    assert points[-1] == pytest.approx([0.505, 0.505], abs=1e-3)
    assert route['zoneSequence'] == ['蓝方野区', '红方发育路', '中路']

    heat = report['heat']
    assert heat['total'] == 240
    assert heat['cells'] == [
        {'x': 2, 'y': 2, 'n': 80},
        {'x': 10, 'y': 10, 'n': 80},
        {'x': 17, 'y': 17, 'n': 80},
    ]


def test_missing_position_seconds_are_skipped_and_counted(tmp_path):
    # 只有前 120 秒有坐标（且坐标有跨度，避免 bounds 退化），其余是 (0,0) 占位
    values = [(-30 + index * 0.05, -30 + index * 0.05) for index in range(120)]
    positions = fx.make_abs_positions({'2-0': values})
    fx.write_case(tmp_path, '2201', positions_payload=positions)
    facts = fx.load_fixture_facts(tmp_path)

    report = decision_opening.opening_report(facts)
    assert report['coverage']['skippedRoutes'] == 4
    route = report['routes'][0]
    assert route['representative']['times'] == [float(second) for second in range(0, 120, 5)]
    assert len(route['representative']['points']) == 24
    assert report['heat']['total'] == 120
    assert sum(cell['n'] for cell in report['heat']['cells']) == 120


# ---------------------------------------------------------------------------
# 聚类：3 局样本 → medoid 代表 + 簇频率
# ---------------------------------------------------------------------------
def test_three_games_same_opponent_cluster_and_next_objective(tmp_path):
    fx.write_dataset(tmp_path, [{'seq': '2301'}, {'seq': '2302'}, {'seq': '2303'}])
    facts = fx.load_fixture_facts(tmp_path)
    opponent_id = facts['games']['2301']['opponentId']
    assert facts['games']['2302']['opponentId'] == opponent_id
    assert facts['games']['2303']['opponentId'] == opponent_id

    report = decision_opening.opening_report(facts, opponent=opponent_id)
    coverage = report['coverage']
    assert coverage['games'] == 3
    assert coverage['routes'] == 15              # 3 局 × 5 名对手选手
    assert coverage['clusters'] == 5             # 每分路一条 3 局重复路线
    assert report['selected']['enough'] is True
    assert report['selected']['games'] == 3

    assert len(report['routes']) == 5
    expected_zones = {
        '对抗路': ['红方野区'],
        '中路': ['红方野区'],
        '发育路': ['红方对抗路'],
        '打野': ['红方发育路'],
        '游走': ['红方发育路'],
    }
    for route in report['routes']:
        assert route['count'] == 3
        assert route['enough'] is True
        assert route['games'] == 3
        assert route['gameIds'] == ['2301', '2302', '2303']
        assert route['avgDistance'] == 0.0
        assert route['representative']['game'] == '2301'
        # 默认合成位置：对手五人的开局站位固定，按 3 局重复路线聚成一簇
        assert route['zoneSequence'] == expected_zones[route['lane']]
        # 后续第一个资源/建筑：合成事件里敌方在 470 秒拿防御塔
        objective = route['nextObjective']
        assert objective['type'] == 'building'
        assert objective['name'] == '防御塔'
        assert objective['minutes'] == 7.8
        assert objective['count'] == 3
        assert objective['games'] == 3
        assert objective['enough'] is True

    assert report['heat']['total'] == 3600       # 3 局 × 5 人 × 240 秒
    assert report['heat']['games'] == 3
    lanes = {item['lane']: item for item in report['lanes']}
    assert set(lanes) == {'对抗路', '中路', '发育路', '打野', '游走'}
    assert all(item['enough'] for item in lanes.values())

    own_side = decision_opening.opening_report(facts, side='own')
    assert len(own_side['routes']) == 5
    for route in own_side['routes']:
        assert route['side'] == 'own'
        assert route['count'] == 3
        assert route['representative']['hero'] in {'关羽', '妲己', '百里守约', '孙悟空', '钟馗'}
        # 合成事件里我方在 360 秒拿暴君
        assert route['nextObjective']['name'] == '暴君'
        assert route['nextObjective']['minutes'] == 6.0


def test_two_games_do_not_cluster(tmp_path):
    fx.write_dataset(tmp_path, [{'seq': '2401'}, {'seq': '2402'}])
    facts = fx.load_fixture_facts(tmp_path)
    report = decision_opening.opening_report(facts)

    assert report['coverage']['routes'] == 10
    assert report['coverage']['clusters'] == 10
    assert len(report['routes']) == 10
    assert all(route['count'] == 1 for route in report['routes'])
    assert all(route['enough'] is False for route in report['routes'])
    assert all(route['games'] == 1 for route in report['routes'])


def test_next_objective_none_without_events(tmp_path):
    fx.write_case(tmp_path, '2501', events=[])
    facts = fx.load_fixture_facts(tmp_path)
    route = decision_opening.opening_report(facts)['routes'][0]
    assert route['nextObjective'] is None


# ---------------------------------------------------------------------------
# 分路 / 阵营 / 对手 / 日期过滤
# ---------------------------------------------------------------------------
def test_lane_and_side_filters(tmp_path):
    positions = fx.make_abs_positions({
        '2-0': constant((-40, -40)),     # 对抗路
        '2-1': constant((40, 40)),       # 中路
        '1-0': constant((10, 10)),       # 我方对抗路
    })
    fx.write_case(tmp_path, '2601', positions_payload=positions)
    facts = fx.load_fixture_facts(tmp_path)

    mid_only = decision_opening.opening_report(facts, lane='中路')
    assert mid_only['available'] is True
    assert [route['lane'] for route in mid_only['routes']] == ['中路']
    assert mid_only['routes'][0]['representative']['player'] == '2-1'
    assert mid_only['heat']['total'] == 240
    assert mid_only['lanes'] == [{'lane': '中路', 'routes': 1, 'clusters': 1,
                                  'enough': False}]

    own_side = decision_opening.opening_report(facts, side='own')
    assert [route['lane'] for route in own_side['routes']] == ['对抗路']
    assert own_side['routes'][0]['representative']['player'] == '1-0'
    assert own_side['routes'][0]['representative']['hero'] == '关羽'
    assert own_side['heat']['total'] == 240

    own_mid = decision_opening.opening_report(facts, side='own', lane='中路')
    assert own_mid['available'] is False
    assert '中路' in own_mid['reason']


def test_opponent_and_date_filters(tmp_path):
    fx.write_case(tmp_path, '2701', start='11-02 12:00')
    fx.write_case(tmp_path, '2702', start='11-03 20:00', own_win=False)
    retag_enemy(tmp_path, '2702', 'other')
    facts = fx.load_fixture_facts(tmp_path)

    everything = decision_opening.opening_report(facts)
    assert everything['coverage']['games'] == 2
    assert len(everything['opponents']) == 2
    assert everything['selected']['name'] == '全部对手（本批）'
    assert everything['selected']['enough'] is False
    assert everything['heat']['total'] == 2400

    target_id = facts['games']['2702']['opponentId']
    scoped = decision_opening.opening_report(facts, opponent=target_id)
    assert scoped['coverage']['games'] == 1
    assert scoped['selected']['id'] == target_id
    assert scoped['selected']['games'] == 1
    assert scoped['selected']['enough'] is False
    assert {route['representative']['game'] for route in scoped['routes']} == {'2702'}
    assert scoped['heat']['total'] == 1200

    narrowed = decision_opening.opening_report(facts, date_from='2026-11-03')
    assert narrowed['coverage']['games'] == 1
    assert {route['representative']['game'] for route in narrowed['routes']} == {'2702'}

    future = decision_opening.opening_report(facts, date_from='2027-01-01')
    assert future['available'] is False


# ---------------------------------------------------------------------------
# 无位置 / 无对手回放
# ---------------------------------------------------------------------------
def test_no_positions_available_false(tmp_path):
    fx.write_case(tmp_path, '2801', positions=False)
    facts = fx.load_fixture_facts(tmp_path)

    report = decision_opening.opening_report(facts)
    assert report['available'] is False
    assert '位置' in report['reason']
    assert report['routes'] == []
    assert report['heat']['cells'] == []
    assert report['coverage']['positionGames'] == 0
    assert report['selected']['enough'] is False


def test_unknown_opponent_available_false(tmp_path):
    fx.write_case(tmp_path, '2901')
    facts = fx.load_fixture_facts(tmp_path)

    report = decision_opening.opening_report(facts, opponent='no-such-team')
    assert report['available'] is False
    assert report['coverage']['games'] == 0
    assert report['selected']['id'] == 'no-such-team'
    assert report['selected']['enough'] is False
    assert report['routes'] == []


def test_empty_dataset_available_false(tmp_path):
    facts = decision_facts.load_facts(tmp_path / 'official_replays',
                                      tmp_path / 'camp_details', tmp_path, None)
    report = decision_opening.opening_report(facts)
    assert report['available'] is False
    assert report['coverage']['games'] == 0
    assert '仅收录本批 0 局回放' in report['notes'][0]
