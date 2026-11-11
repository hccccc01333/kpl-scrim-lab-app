"""decision_resource.resource_report 单元测试。

全部用 tests/decision_fixtures.py 的合成终局面板（不依赖真实赛训库），
断言具体数值/关系：占比合计、象限分界、quadrantFlag 规则、异常、分路均值、
效率、own/enemy、过滤与空数据降级。
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import decision_fixtures as fx  # noqa: E402
import decision_resource  # noqa: E402

LANES = ['对抗路', '中路', '发育路', '打野', '游走']
SHARE_KEYS = ('goldShare', 'heroDamageShare', 'towerShare',
              'controlShare', 'healShare', 'jungleShare')


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------
def make_facts(tmp_path, cases=None):
    cases = cases or [{'seq': '1001'}]
    root = fx.write_dataset(tmp_path, cases)
    return fx.load_fixture_facts(root)


def own_row(facts, lane, seq=None):
    rows = [row for row in facts['rows']
            if row['side'] == 'own' and row['lane'] == lane
            and (seq is None or row['seq'] == seq)]
    assert len(rows) == 1, (lane, seq, len(rows))
    return rows[0]


def by_lane(report, lane):
    return next(item for item in report['byLane'] if item['lane'] == lane)


def points_of(report, lane):
    return [point for point in report['players'] if point['lane'] == lane]


def player_of(report, lane):
    points = points_of(report, lane)
    assert len(points) == 1, (lane, len(points))
    return points[0]


# ---------------------------------------------------------------------------
# 占比 / GPM / 口径
# ---------------------------------------------------------------------------
def test_shares_gpm_and_basis(tmp_path):
    facts = make_facts(tmp_path)
    report = decision_resource.resource_report(facts)

    assert report['available'] is True
    assert report['reason'] is None
    assert report['filters']['side'] == 'own'
    assert report['quadrantBasis'] == 'fixed'
    assert report['quadrant']['xSplit'] == pytest.approx(20.0)
    assert report['quadrant']['ySplit'] == pytest.approx(20.0)

    coverage = report['coverage']
    assert coverage['panelGames'] == 1
    assert coverage['panelGamesTotal'] == 1
    assert coverage['rows'] == 5
    assert coverage['rowsTotal'] == 10
    assert coverage['ownRows'] == 5
    assert coverage['gamesWithGold'] == 1
    # 与 facts.coverage 一致：dateRange 是 [最早, 最晚]（单日时两端相同）
    assert coverage['dateRange'] == [facts['rows'][0]['date']] * 2

    assert len(report['players']) == 5
    assert [point['lane'] for point in report['players']] == LANES
    for key in SHARE_KEYS:
        assert sum(point[key] for point in report['players']) == pytest.approx(100.0, abs=0.3)
    # 占比分母是同局同阵营五人合计：开发路经济 8800 / 39800 = 22.1%
    farm = player_of(report, '发育路')
    assert 20.0 <= farm['goldShare'] <= 25.0
    assert farm['goldShare'] == pytest.approx(22.1, abs=0.05)
    assert player_of(report, '中路')['goldShare'] == pytest.approx(20.6, abs=0.05)
    assert player_of(report, '游走')['goldShare'] == pytest.approx(15.6, abs=0.05)

    # GPM = gold / minutes（fixture 一局 600 秒 = 10.0 分钟）
    assert player_of(report, '打野')['gpm'] == pytest.approx(900.0, abs=0.1)
    assert player_of(report, '对抗路')['gpm'] == pytest.approx(760.0, abs=0.1)
    assert player_of(report, '游走')['gpm'] == pytest.approx(620.0, abs=0.1)
    # participation 保留面板原值（已是百分数 0.55 → 55.0）
    assert player_of(report, '中路')['participation'] == pytest.approx(55.0, abs=0.1)

    # damage（totalHurtCnt）与 heroDamage（totalHeroHurtCnt）分开保留，不混用
    mid = player_of(report, '中路')
    assert mid['heroDamage'] == pytest.approx(88000)
    assert mid['damage'] == pytest.approx(3 * mid['heroDamage'])
    assert report['metrics']['goldBasis'] == 'battleStats.money'
    assert report['metrics']['damageBasis'] == 'battleStats.totalHeroHurtCnt'
    assert report['metrics']['towerBasis'] == 'battleStats.buildingDamage'
    # 契约 2.5 字面口径字段同时给扁平键，方便前端直接消费
    assert report['goldBasis'] == 'battleStats.money'
    assert report['damageBasis'] == 'battleStats.totalHeroHurtCnt'
    assert report['towerBasis'] == 'battleStats.buildingDamage'
    assert '不混用' in report['metrics']['note']
    assert '游走' in report['note'] and '辅助' in report['note']
    json.dumps(report, ensure_ascii=False)  # 可 JSON 化（API 直接返回）


# ---------------------------------------------------------------------------
# 四象限
# ---------------------------------------------------------------------------
def test_quadrant_fixed_basis_single_game(tmp_path):
    facts = make_facts(tmp_path)
    report = decision_resource.resource_report(facts)
    lanes = {point['lane']: point for point in report['players']}

    assert lanes['中路']['quadrant'] == '高经济·高输出'      # 20.6 / 33.8
    assert lanes['发育路']['quadrant'] == '高经济·高输出'    # 22.1 / 36.9
    assert lanes['打野']['quadrant'] == '高经济·低输出'      # 22.6 / 16.2
    assert lanes['对抗路']['quadrant'] == '低经济·低输出'    # 19.1 / 8.5
    assert lanes['游走']['quadrant'] == '低经济·低输出'      # 15.6 / 4.6


def test_quadrant_median_basis_multi_game(tmp_path):
    facts = make_facts(tmp_path, [{'seq': '2001'}, {'seq': '2002'}, {'seq': '2003'}])
    report = decision_resource.resource_report(facts)

    assert report['quadrantBasis'] == 'median'
    assert report['quadrant']['n'] == 15
    assert report['quadrant']['xSplit'] == pytest.approx(20.6, abs=0.05)
    assert report['quadrant']['ySplit'] == pytest.approx(16.2, abs=0.05)
    # 分界取展示值，页面数字与象限标签一致
    jungle = points_of(report, '打野')
    assert len(jungle) == 3
    assert all(point['quadrant'] == '高经济·高输出' for point in jungle)
    assert all(point['goldShare'] == pytest.approx(22.6, abs=0.05) for point in jungle)
    assert all(point['heroDamageShare'] == pytest.approx(16.2, abs=0.05) for point in jungle)
    assert points_of(report, '对抗路')[0]['quadrant'] == '低经济·低输出'


# ---------------------------------------------------------------------------
# quadrantFlag：仅 中路/发育路/对抗路/打野；goldShare−heroDamageShare≥5pp 且 goldShare≥20
# ---------------------------------------------------------------------------
def test_quadrant_flag_default_rows(tmp_path):
    facts = make_facts(tmp_path)
    report = decision_resource.resource_report(facts)
    flags = {point['lane']: point['quadrantFlag'] for point in report['players']}

    assert flags['打野'] is True                       # 22.6 − 16.2 = 6.4pp，且 22.6 ≥ 20
    assert player_of(report, '打野')['goldDamageGap'] == pytest.approx(6.4, abs=0.05)
    assert flags['中路'] is False                      # 输出占比反而更高
    assert flags['发育路'] is False
    assert flags['对抗路'] is False                    # 经济占比 19.1 < 20
    assert flags['游走'] is False                      # 辅助/游走永不套用输出规则
    assert report['summary']['quadrantFlagCount'] == 1


def test_quadrant_flag_needs_gold_threshold(tmp_path):
    facts = make_facts(tmp_path)
    row = own_row(facts, '对抗路')
    row['gold'] = 7000       # 占比 17.9% < 20
    row['heroDamage'] = 1000  # 占比 0.4%：差 17.5pp，但经济不够高
    report = decision_resource.resource_report(facts, lane='对抗路')
    point = report['players'][0]
    assert point['goldShare'] == pytest.approx(17.9, abs=0.05)
    assert point['goldDamageGap'] >= 5.0
    assert point['quadrantFlag'] is False


def test_quadrant_flag_catches_high_gold_low_damage_mid(tmp_path):
    facts = make_facts(tmp_path)
    row = own_row(facts, '中路')
    row['gold'] = 12000
    row['heroDamage'] = 10000
    report = decision_resource.resource_report(facts, lane='中路')
    point = report['players'][0]
    assert point['goldShare'] == pytest.approx(27.5, abs=0.05)       # 12000 / 43600
    assert point['heroDamageShare'] == pytest.approx(5.5, abs=0.05)  # 10000 / 182000
    assert point['quadrantFlag'] is True
    assert report['anomalies'][0]['kind'] == 'high_gold_low_damage'


def test_support_lane_never_uses_output_rule(tmp_path):
    facts = make_facts(tmp_path)
    row = own_row(facts, '游走')
    row['gold'] = 16000        # 占比 32.3%，全队最高
    row['heroDamage'] = 2000   # 占比 0.8%
    report = decision_resource.resource_report(facts)

    support = player_of(report, '游走')
    assert support['goldShare'] >= 30.0
    assert support['goldShare'] - support['heroDamageShare'] >= 20.0
    assert support['quadrantFlag'] is False
    assert report['summary']['supportLanes'] == ['游走']
    assert all(item['lane'] != '游走' for item in report['anomalies'])


# ---------------------------------------------------------------------------
# anomalies：只列 quadrantFlag 或 发育路死亡≥3，不排名、不评价选手
# ---------------------------------------------------------------------------
def test_anomalies_high_gold_low_damage(tmp_path):
    facts = make_facts(tmp_path)
    report = decision_resource.resource_report(facts)

    assert len(report['anomalies']) == 1
    item = report['anomalies'][0]
    assert item['kind'] == 'high_gold_low_damage'
    assert item['lane'] == '打野'
    assert item['gap'] == pytest.approx(6.4, abs=0.05)
    assert '经济占比 22.6%' in item['text']
    assert '英雄伤害占比 16.2%' in item['text']
    assert '差 6.4pp' in item['text']
    assert item['seq'] == '1001'
    assert item['name'] and item['hero']
    assert '最' not in item['text']  # 只陈述，不排名


def test_anomalies_farm_lane_deaths(tmp_path):
    facts = make_facts(tmp_path)
    row = own_row(facts, '发育路', seq='1001')

    row['deaths'] = 2
    assert decision_resource.resource_report(facts, lane='发育路')['anomalies'] == []

    row['deaths'] = 3
    report = decision_resource.resource_report(facts, lane='发育路')
    assert len(report['anomalies']) == 1
    item = report['anomalies'][0]
    assert item['kind'] == 'farm_lane_deaths'
    assert item['gap'] is None
    assert '本局死亡 3 次' in item['text']


def test_anomalies_combined_reason(tmp_path):
    facts = make_facts(tmp_path)
    row = own_row(facts, '发育路')
    row.update({'gold': 12000, 'heroDamage': 10000, 'deaths': 3})
    report = decision_resource.resource_report(facts, lane='发育路')

    assert len(report['anomalies']) == 1  # 同一行只出一条，不重复列
    item = report['anomalies'][0]
    assert item['kind'] == 'high_gold_low_damage+farm_lane_deaths'
    assert item['gap'] == pytest.approx(22.2, abs=0.1)  # 27.9 − 5.7
    assert '差' in item['text'] and '本局死亡 3 次' in item['text']


# ---------------------------------------------------------------------------
# byLane / efficiency
# ---------------------------------------------------------------------------
def test_by_lane_means(tmp_path):
    facts = make_facts(tmp_path, [{'seq': '2001'}, {'seq': '2002'}, {'seq': '2003'}])
    report = decision_resource.resource_report(facts)

    assert [item['lane'] for item in report['byLane']] == LANES
    assert all(item['n'] == 3 for item in report['byLane'])
    assert by_lane(report, '对抗路')['gpm'] == pytest.approx(760.0, abs=0.1)
    assert by_lane(report, '中路')['heroDamageShare'] == pytest.approx(33.8, abs=0.05)
    assert by_lane(report, '发育路')['towerShare'] == pytest.approx(40.0, abs=0.05)
    assert by_lane(report, '打野')['deaths'] == pytest.approx(2.0, abs=0.05)
    # 辅助的高价值在控制/治疗，不在输出
    assert by_lane(report, '游走')['controlShare'] == pytest.approx(40.6, abs=0.05)
    assert by_lane(report, '游走')['healShare'] == pytest.approx(55.1, abs=0.05)


def test_by_lane_respects_lane_filter(tmp_path):
    facts = make_facts(tmp_path, [{'seq': '2001'}, {'seq': '2002'}, {'seq': '2003'}])
    report = decision_resource.resource_report(facts, lane='打野')
    assert [item['lane'] for item in report['byLane']] == ['打野']
    assert report['byLane'][0]['n'] == 3
    assert report['coverage']['rows'] == 3
    assert report['coverage']['rowsEligible'] == 15


def test_efficiency_ratios(tmp_path):
    facts = make_facts(tmp_path, [{'seq': '2001'}, {'seq': '2002'}, {'seq': '2003'}])
    report = decision_resource.resource_report(facts)
    efficiency = {item['lane']: item for item in report['efficiency']}

    assert set(efficiency) == set(LANES)
    assert efficiency['发育路']['ratio'] == pytest.approx(1.67, abs=0.01)
    assert efficiency['中路']['ratio'] == pytest.approx(1.64, abs=0.01)
    assert efficiency['对抗路']['ratio'] == pytest.approx(0.45, abs=0.01)
    assert efficiency['游走']['ratio'] == pytest.approx(0.29, abs=0.01)
    assert efficiency['中路']['n'] == 3
    assert efficiency['中路']['ratio'] > efficiency['对抗路']['ratio']  # 职责差异，非排名
    assert '不跨分路排名' in report['efficiencyNote']
    assert '不按输出评价' in efficiency['游走']['note']


# ---------------------------------------------------------------------------
# side=own / enemy
# ---------------------------------------------------------------------------
def test_side_enemy_is_reference_only(tmp_path):
    facts = make_facts(tmp_path)
    own = decision_resource.resource_report(facts)
    enemy = decision_resource.resource_report(facts, side='enemy')

    assert enemy['available'] is True
    assert enemy['filters']['side'] == 'enemy'
    assert len(enemy['players']) == 5
    assert all(point['side'] == 'enemy' for point in enemy['players'])
    assert all(point['name'].startswith('对手') for point in enemy['players'])
    assert enemy['coverage']['rows'] == 5
    assert enemy['coverage']['ownRows'] == 5  # 同范围仍统计我方行数，便于对照
    # 敌方经济合计 33300：7700 / 33300 = 23.1%，与 own 的 22.6% 分开算
    enemy_lanes = {point['lane']: point for point in enemy['players']}
    assert enemy_lanes['打野']['goldShare'] == pytest.approx(23.1, abs=0.05)
    assert enemy_lanes['打野']['quadrantFlag'] is True
    assert enemy_lanes['中路']['quadrantFlag'] is False
    own_lanes = {point['lane']: point for point in own['players']}
    assert own_lanes['打野']['goldShare'] == pytest.approx(22.6, abs=0.05)


def test_invalid_side_rejected(tmp_path):
    facts = make_facts(tmp_path)
    with pytest.raises(ValueError):
        decision_resource.resource_report(facts, side='both')


# ---------------------------------------------------------------------------
# 过滤
# ---------------------------------------------------------------------------
def test_filters_and_varied_results(tmp_path):
    facts = make_facts(tmp_path, [
        {'seq': '3001', 'start': '11-02 12:00', 'own_win': True},
        {'seq': '3002', 'start': '11-03 12:00', 'own_win': False},
        {'seq': '3003', 'start': '11-04 12:00', 'own_win': True},
    ])
    # 让 3003 的对手与其他两局不同，便于测 opponent 过滤
    for row in facts['rows']:
        if row['seq'] == '3003':
            row['opponentId'] = 'team-test-b'
            row['opponentName'] = '测试战队B'
    dates = sorted({row['date'] for row in facts['rows'] if row['side'] == 'own'})
    assert len(dates) == 3

    loss = decision_resource.resource_report(facts, result='loss')
    assert {point['seq'] for point in loss['players']} == {'3002'}
    assert all(point['result'] == 'loss' and point['won'] is False
               for point in loss['players'])
    assert loss['coverage']['panelGames'] == 1

    wins = decision_resource.resource_report(facts, result='win')
    assert {point['seq'] for point in wins['players']} == {'3001', '3003'}

    ranged = decision_resource.resource_report(facts, date_from=dates[1])
    assert {point['seq'] for point in ranged['players']} == {'3002', '3003'}
    single = decision_resource.resource_report(facts, date_from=dates[1], date_to=dates[1])
    assert {point['seq'] for point in single['players']} == {'3002'}
    assert decision_resource.resource_report(
        facts, date_from=dates[2], date_to=dates[0])['available'] is False

    custom = decision_resource.resource_report(facts, opponent='测试战队B')
    assert {point['seq'] for point in custom['players']} == {'3003'}
    original_id = next(row['opponentId'] for row in facts['rows'] if row['seq'] == '3001')
    original = decision_resource.resource_report(facts, opponent=original_id)
    assert {point['seq'] for point in original['players']} == {'3001', '3002'}

    lane = decision_resource.resource_report(facts, lane='打野')
    assert len(lane['players']) == 3
    assert {point['lane'] for point in lane['players']} == {'打野'}

    # 同一个 playerId 每局一行；也支持按营地昵称过滤
    pid = next(row['playerId'] for row in facts['rows']
               if row['side'] == 'own' and row['lane'] == '中路')
    name = next(row['name'] for row in facts['rows']
                if row['side'] == 'own' and row['lane'] == '中路')
    by_id = decision_resource.resource_report(facts, player=pid)
    assert len(by_id['players']) == 3
    assert {point['playerId'] for point in by_id['players']} == {pid}
    by_name = decision_resource.resource_report(facts, player=name)
    assert {point['playerId'] for point in by_name['players']} == {pid}

    for kwargs in ({'opponent': '不存在'}, {'lane': '不存在'}, {'player': '不存在'}):
        empty = decision_resource.resource_report(facts, **kwargs)
        assert empty['available'] is False
        assert empty['reason']
        assert empty['players'] == [] and empty['byLane'] == []


def test_lane_aliases(tmp_path):
    facts = make_facts(tmp_path)
    mid = decision_resource.resource_report(facts, lane='中单')
    assert len(mid['players']) == 1
    assert mid['players'][0]['lane'] == '中路'
    support = decision_resource.resource_report(facts, lane='辅助')
    assert len(support['players']) == 1
    assert support['players'][0]['lane'] == '游走'


def test_rows_only_facts_supported(tmp_path):
    """只有 rows（无 games/panels）的事实表也能跑；result 从行内 won 反推。"""
    facts = make_facts(tmp_path)
    slim = {'rows': [dict(row) for row in facts['rows'] if row['side'] == 'own']}
    report = decision_resource.resource_report(slim)
    assert report['available'] is True
    assert len(report['players']) == 5
    assert report['coverage']['panelGames'] == 1
    assert all(point['result'] == 'win' and point['won'] is True
               for point in report['players'])
    assert decision_resource.resource_report(slim, result='loss')['available'] is False
    assert decision_resource.resource_report(
        slim, result='loss')['coverage']['panelGames'] == 0


# ---------------------------------------------------------------------------
# 空数据 / 缺字段：available=false + reason，不 0 填充、不空图
# ---------------------------------------------------------------------------
def test_empty_facts_degrades(tmp_path):
    for facts in ({}, None):
        report = decision_resource.resource_report(facts)
        assert report['available'] is False
        assert report['reason']
        assert report['players'] == []
        assert report['anomalies'] == []
        assert report['byLane'] == []
        assert report['coverage']['panelGames'] == 0
        assert report['metrics']['goldBasis'] == 'battleStats.money'
        json.dumps(report, ensure_ascii=False)

    empty_root = tmp_path / 'empty'
    (empty_root / 'camp_details').mkdir(parents=True)
    (empty_root / 'official_replays').mkdir(parents=True)
    empty = decision_resource.resource_report(fx.load_fixture_facts(empty_root))
    assert empty['available'] is False
    assert empty['reason']


def test_missing_gold_degrades(tmp_path):
    facts = make_facts(tmp_path)
    for row in facts['rows']:
        if row['side'] == 'own':
            row['gold'] = None
    report = decision_resource.resource_report(facts)
    assert report['available'] is False
    assert 'money' in report['reason']
    assert report['players'] == []
    assert report['coverage']['gamesWithGold'] == 0
    assert report['coverage']['missingFields']['gold'] == 5


def test_partial_missing_gold_is_not_zero_filled(tmp_path):
    facts = make_facts(tmp_path)
    own_row(facts, '对抗路')['gold'] = None
    report = decision_resource.resource_report(facts)

    assert report['available'] is True
    top = player_of(report, '对抗路')
    assert top['goldShare'] is None
    assert top['gpm'] is None
    # 其余四人仍按“非缺失值合计”计算占比，合计仍约 100%
    others = [point for point in report['players'] if point['lane'] != '对抗路']
    assert sum(point['goldShare'] for point in others) == pytest.approx(100.0, abs=0.3)
    assert report['coverage']['missingFields']['gold'] == 1
