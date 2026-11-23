"""赛训周期简报（docs/period_brief.md）口径与接口测试。

覆盖：周期窗口/上期等长、custom 参数校验、领先兑现/团战/资源/阵容的数值与
方向、本期 0 局与上期 0 局、去重与最多 3 条、小样本降级、空库不 500、
GET /api/briefing 字段齐全且没有统计术语。
"""
from __future__ import annotations

import copy
import json
import re
import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import facts_fixtures as fx

import analysis_period
import briefing_api

YEAR = date.today().year
CURRENT = date(YEAR, 11, 13)


def day(mmdd):
    return f'{YEAR}-{mmdd}'


# 十分钟领先且赢下
LEAD_WIN = [0, 500, 1200, 2000, 3000, 2400, 1500, 800, 1200, 1800]
# 十分钟仍领先但最终告负（被翻盘）
LEAD_LOSS = [0, 800, 1600, 2400, 3000, 2600, 2000, 1500, 1200, 1100]
# 十分钟落后、最终赢下（不算领先兑现）
LATE_WIN = [0, 300, 800, 1600, 2400, 2100, 1500, 900, 200, -400]

PREV_EVENTS = [
    {'eventType': 'dragontower', 'timeSec': 360.0, 'dtType': '1', 'dtId': '9',
     'dtCamp': '2', 'killerCamp': '1', 'killerId': '104', 'kills': []},
    {'eventType': 'dragontower', 'timeSec': 470.0, 'dtType': '2', 'dtId': '1',
     'dtCamp': '2', 'killerCamp': '2', 'killerId': '202', 'kills': []},
]


def behind_fight(*, start=300.0, own_wins=False, fight_id='f2'):
    """开局 3 秒我方 0 人到、对方 5 人到；可控制击杀交换。"""
    participants = [
        {'objID': f'1{index + 1}', 'camp': '1', 'timeSec': start + 5, 'beginner': 0}
        for index in range(5)
    ] + [
        {'objID': f'2{index + 1}', 'camp': '2', 'timeSec': start + 1, 'beginner': 0}
        for index in range(5)
    ]
    if own_wins:
        kills = [{'timeSec': start + 6, 'killerCamp': '1', 'victimCamp': '2'} for _ in range(2)]
    else:
        kills = [{'timeSec': start + 6, 'killerCamp': '2', 'victimCamp': '1'} for _ in range(3)]
    return {
        'fightId': fight_id, 'startSec': start, 'endSec': start + 12,
        'firstKillerCamp': '2', 'participants': participants, 'kills': kills,
        'details': [],
    }


def _cases(cur_games=4, prev_games=3, *, panel_only=False, fights=True):
    cases = []
    cur = [
        {'seq': '2001', 'own_win': True, 'diff': LEAD_WIN, 'start': '11-02 19:00'},
        {'seq': '2002', 'own_win': True, 'diff': LEAD_WIN, 'start': '11-03 19:00'},
        {'seq': '2003', 'own_win': False, 'diff': LEAD_LOSS, 'start': '11-04 19:00'},
        {'seq': '2004', 'own_win': True, 'diff': LATE_WIN, 'start': '11-04 20:00'},
    ]
    prev = [
        {'seq': '1901', 'own_win': True, 'diff': LEAD_WIN,
         'events': PREV_EVENTS, 'start': '10-31 19:00'},
        {'seq': '1902', 'own_win': True, 'diff': LEAD_WIN,
         'events': PREV_EVENTS, 'start': '10-31 19:30'},
        {'seq': '1903', 'own_win': True, 'diff': LEAD_WIN,
         'events': PREV_EVENTS, 'start': '10-31 20:00'},
    ]
    for index, case in enumerate(cur[:cur_games]):
        case = dict(case)
        if fights:
            behind = behind_fight(own_wins=False,
                                  start=300.0 if index != 2 else 320.0)
            case['fights'] = fx.default_fights() + [behind]
        else:
            case['fights'] = []
        cases.append(case)
    if panel_only:
        cases.append({'seq': '2005', 'own_win': True, 'replay': False,
                      'start': '11-04 21:00'})
    for index, case in enumerate(prev[:prev_games]):
        case = dict(case)
        if fights:
            case['fights'] = fx.default_fights() + [
                behind_fight(own_wins=True, start=300.0 + index * 5, fight_id='f2')]
        else:
            case['fights'] = []
        cases.append(case)
    return cases


def make_facts(tmp_path, **kwargs):
    fx.write_dataset(tmp_path, _cases(**kwargs))
    return fx.load_fixture_facts(tmp_path)


def build(facts, **kwargs):
    # 首页默认只出训练赛总览指标；这批用例验证的是底层候选口径，显式走旧指标。
    kwargs.setdefault('classic_metrics', True)
    return analysis_period.build_briefing(
        facts, today=CURRENT, **kwargs) if 'today' not in kwargs else \
        analysis_period.build_briefing(facts, **kwargs)


def metrics_of(payload):
    return {item['id']: item for item in payload['metrics']}


# ---------------------------------------------------------------------------
# 周期窗口
# ---------------------------------------------------------------------------
def test_period_windows_equal_length():
    today = analysis_period.parse_period('today', today=CURRENT)
    assert (today['from'], today['to']) == (day('11-13'), day('11-13'))
    assert (today['prev']['from'], today['prev']['to']) == (day('11-12'), day('11-12'))

    week = analysis_period.parse_period('week', today=CURRENT)
    assert (week['from'], week['to']) == (day('11-09'), day('11-15'))
    # 本周与上周相同进度：今天周五，上周只比到上周五
    assert (week['prev']['from'], week['prev']['to']) == (day('11-02'), day('11-06'))
    assert week['days'] == 7 and week['prev']['days'] == 5
    assert week['prev']['sameProgress'] is True
    assert week['rangeLabel'] == '11-09 ~ 11-15'

    month = analysis_period.parse_period('month', today=CURRENT)
    assert (month['from'], month['to']) == (day('11-01'), day('11-30'))
    # 本月到 13 号，上月只比到上月 13 号
    assert (month['prev']['from'], month['prev']['to']) == (day('10-01'), day('10-13'))
    assert month['days'] == 30 and month['prev']['days'] == 13

    # 跨月同进度：3 月 15 日 → 2 月 1 日 ~ 2 月 15 日
    march = analysis_period.parse_period('month', today=date(YEAR, 3, 15))
    assert (march['from'], march['to']) == (f'{YEAR}-03-01', f'{YEAR}-03-31')
    assert (march['prev']['from'], march['prev']['to']) == (f'{YEAR}-02-01', f'{YEAR}-02-15')
    assert march['prev']['days'] == 15

    custom = analysis_period.parse_period('custom', today=CURRENT,
                                          date_from=day('11-02'), date_to=day('11-06'))
    assert (custom['from'], custom['to']) == (day('11-02'), day('11-06'))
    assert (custom['prev']['from'], custom['prev']['to']) == (day('10-28'), day('11-01'))
    assert custom['prev']['days'] == custom['days'] == 5


@pytest.mark.parametrize('kind,kwargs', [
    ('year', {}),
    ('custom', {}),
    ('custom', {'date_from': '2026-13-01', 'date_to': '2026-11-06'}),
    ('custom', {'date_from': '2026-11-05', 'date_to': '2026-11-02'}),
])
def test_custom_and_period_validation(kind, kwargs):
    with pytest.raises(ValueError):
        analysis_period.parse_period(kind, today=CURRENT, **kwargs)


def test_extra_recent_window(tmp_path):
    """最近 N 场：取日期最新的 N 局，上期是再往前的 N 局。"""
    facts = make_facts(tmp_path)
    payload = analysis_period.build_briefing(
        facts, period_kind='recent', recent_n=2, today=CURRENT)
    assert payload['available'] is True
    period = payload['period']
    assert period['kind'] == 'recent'
    assert period['label'] == '最近 2 场'
    assert period['n'] == 2
    assert (period['from'], period['to']) == (day('11-04'), day('11-04'))
    assert period['rangeLabel'] == '11-04 ~ 11-04'
    # 只数有回放的局，且正好 2 局
    assert payload['coverage']['games'] == 2
    assert payload['record']['decided'] <= 2
    assert period['prev']['label'] == '前 2 场'
    assert period['prev']['from'] == day('11-02')
    # 标题跟着周期走，不是「本期」
    assert payload['watchTitle'] == '重点复盘'
    assert payload['findingsTitle'] == '最近 2 场重点发现'


def test_extra_days_window(tmp_path):
    """最近 D 天：以数据里最新日期为终点，往前 D 个自然日。"""
    facts = make_facts(tmp_path)
    payload = analysis_period.build_briefing(
        facts, period_kind='days', days=2, today=CURRENT)
    period = payload['period']
    assert period['kind'] == 'days'
    assert period['label'] == '最近 2 天'
    assert (period['from'], period['to']) == (day('11-03'), day('11-04'))
    assert period['rangeLabel'] == '11-03 ~ 11-04'
    assert payload['coverage']['games'] == 3
    assert period['prev']['label'] == '前 2 天'
    assert (period['prev']['from'], period['prev']['to']) == (day('11-01'), day('11-02'))


def test_extra_period_empty_facts():
    """没有任何对局时，最近 N 场 / D 天也要给空态而不是 500。"""
    for kind in ('recent', 'days'):
        payload = analysis_period.build_briefing(
            {}, period_kind=kind, today=CURRENT)
        assert payload['available'] is False
        assert payload['period']['kind'] == kind
        assert payload['findings'] == [] and payload['watchFields'] == []


def test_extra_period_api_validation(tmp_path):
    client, _ = make_client(tmp_path)
    assert client.get('/api/briefing?period=recent&n=0').status_code == 400
    assert client.get('/api/briefing?period=recent&n=99').status_code == 400
    assert client.get('/api/briefing?period=days&days=0').status_code == 400
    assert client.get('/api/briefing?period=days&days=99').status_code == 400
    assert client.get('/api/briefing?period=recent&n=3').status_code == 200
    assert client.get('/api/briefing?period=days&days=3').status_code == 200


# ---------------------------------------------------------------------------
# 候选信号数值与方向
# ---------------------------------------------------------------------------
def test_lead_hold(tmp_path):
    facts = make_facts(tmp_path)
    payload = build(facts, period_kind='custom',
                    date_from=day('11-02'), date_to=day('11-04'))
    assert payload['available'] is True
    metrics = metrics_of(payload)

    lead = metrics['lead_hold']
    assert lead['valueText'] == '2/3'
    assert lead['prevValueText'] == '3/3'
    assert lead['tone'] == 'down'
    assert lead['deltaText'] == '少拿下 1 局'
    assert lead['sample'] == 3 and lead['prevSample'] == 3
    assert lead['enough'] is True

    finding = {item['kind']: item for item in payload['findings']}
    assert 'advantage' in finding
    assert finding['advantage']['n'] >= 2
    assert finding['advantage']['evidence']


def test_comeback_direction(tmp_path):
    """领先过但十分钟已落后：只出「被翻盘」，不出「十分钟领先兑现」。"""
    early_lead_loss = [0, 500, 1500, 3000, 2400, 1800, 900, 200, -600, -1200]
    cases = [
        {'seq': '2101', 'own_win': False, 'diff': early_lead_loss,
         'fights': [], 'events': [], 'start': '11-02 19:00'},
        {'seq': '2102', 'own_win': False, 'diff': early_lead_loss,
         'fights': [], 'events': [], 'start': '11-03 19:00'},
        {'seq': '2103', 'own_win': True, 'diff': LEAD_WIN,
         'fights': [], 'events': [], 'start': '10-31 19:00'},
        {'seq': '2104', 'own_win': True, 'diff': LEAD_WIN,
         'fights': [], 'events': [], 'start': '10-31 19:30'},
    ]
    fx.write_dataset(tmp_path, cases)
    facts = fx.load_fixture_facts(tmp_path)
    payload = build(facts, period_kind='custom',
                    date_from=day('11-02'), date_to=day('11-04'))
    metrics = metrics_of(payload)
    assert 'lead_hold' not in metrics
    comeback = metrics['comeback']
    assert comeback['valueText'] == '2/2'
    assert comeback['prevValueText'] == '0/2'
    assert comeback['tone'] == 'down'
    assert comeback['sample'] == 2 and comeback['enough'] is False
    assert payload['findings'][0]['kind'] == 'advantage'


def test_fight_arrival_and_trade(tmp_path):
    facts = make_facts(tmp_path)
    payload = build(facts, period_kind='custom',
                    date_from=day('11-02'), date_to=day('11-04'))
    metrics = metrics_of(payload)

    arrival = metrics['fight_arrival']
    assert arrival['valueText'] == '0/4'
    assert arrival['prevValueText'] == '3/3'
    assert arrival['tone'] == 'down'
    assert '扩大' in arrival['deltaText']
    assert arrival['sample'] == 8

    trade = metrics['fight_trade']
    assert trade['valueText'] == '-1.00'
    assert trade['prevValueText'] == '+1.50'
    assert trade['tone'] == 'down'
    assert trade['sample'] == 8


def test_objective_direction(tmp_path):
    facts = make_facts(tmp_path)
    payload = build(facts, period_kind='custom',
                    date_from=day('11-02'), date_to=day('11-04'))
    objective = metrics_of(payload)['objective']
    assert objective['valueText'] == '2.0 个/局'
    assert objective['prevValueText'] == '1.0 个/局'
    assert objective['tone'] == 'up'
    assert '多拿' in objective['deltaText']
    assert objective['sample'] == 4


def test_comp_direction(tmp_path):
    facts = make_facts(tmp_path)
    facts = copy.deepcopy(facts)
    prev_seqs = {'1901', '1902', '1903'}
    heroes = {
        '1901': ('澜', '小乔'),
        '1902': ('刘备', '妲己'),
        '1903': ('镜', '不知火舞'),
    }
    for row in facts['rows']:
        if row['seq'] not in prev_seqs:
            continue
        if row['lane'] == '打野':
            row['hero'] = heroes[row['seq']][0]
        elif row['lane'] == '中路':
            row['hero'] = heroes[row['seq']][1]
    payload = build(facts, period_kind='custom',
                    date_from=day('11-02'), date_to=day('11-04'))
    comp = metrics_of(payload)['comp']
    assert comp['valueText'] == '4/4 局'
    assert comp['prevValueText'] == '1/3 局'
    assert comp['tone'] == 'up'
    assert '集中' in comp['deltaText']


# ---------------------------------------------------------------------------
# 空态与降级
# ---------------------------------------------------------------------------
def test_empty_period_has_fallback_hint(tmp_path):
    facts = make_facts(tmp_path)
    payload = build(facts, period_kind='week', today=CURRENT)
    assert payload['available'] is False
    assert payload['reason']
    hint = payload['fallback_hint']
    assert hint is not None
    assert hint['from'] == day('11-02') and hint['to'] == day('11-04')
    assert hint['games'] == 4
    assert payload['metrics'] == [] and payload['findings'] == []


def test_prev_empty_degrades_delta(tmp_path):
    facts = make_facts(tmp_path, prev_games=0)
    # 2026-11-05 属于 11-02~11-08 本周；上期 10-26~11-01 没有对局
    payload = build(facts, period_kind='week', today=date(YEAR, 11, 5))
    assert payload['available'] is True
    lead = metrics_of(payload)['lead_hold']
    assert lead['prevValueText'] is None
    assert lead['deltaText'] == '上周暂无可比数据'
    assert lead['tone'] == 'none'
    assert lead['enough'] is False


def test_small_sample_is_not_enough(tmp_path):
    facts = make_facts(tmp_path, cur_games=1, fights=False)
    payload = build(facts, period_kind='custom',
                    date_from=day('11-02'), date_to=day('11-04'))
    assert payload['metrics']
    assert all(item['enough'] is False for item in payload['metrics'])
    assert payload['findings'] == []


def test_empty_database_does_not_crash(tmp_path):
    (tmp_path / 'official_replays').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'camp_details').mkdir(parents=True, exist_ok=True)
    facts = fx.load_fixture_facts(tmp_path)
    payload = build(facts, period_kind='week', today=CURRENT)
    assert payload['available'] is False
    assert payload['fallback_hint'] is None
    assert payload['reason']
    assert payload['coverage']['games'] == 0


# ---------------------------------------------------------------------------
# 排序与去重
# ---------------------------------------------------------------------------
def test_findings_dedup_and_limit(tmp_path):
    facts = make_facts(tmp_path, panel_only=True)
    payload = build(facts, period_kind='custom',
                    date_from=day('11-02'), date_to=day('11-04'))
    findings = payload['findings']
    assert len(findings) >= 1  # 不固定条数：前端区块内滚动，不再截到 3 条
    kinds = [item['kind'] for item in findings]
    assert len(kinds) == len(set(kinds))
    themes = [item['kind'] if item['kind'] in ('objective', 'coverage')
              else ('advantage' if item['kind'] == 'advantage'
                    else 'lineup' if item['kind'] in ('comp', 'roster') else 'fight')
              for item in findings]
    assert len(themes) == len(set(themes))
    assert kinds.count('objective') <= 1
    assert kinds.count('comp') + kinds.count('roster') <= 1

    required = {'id', 'kind', 'title', 'conclusion', 'numbers', 'n', 'enough',
                'evidence', 'counterexamples', 'primary_destination',
                'deep_destination', 'limitation'}
    real_games = set(facts['games']) | set(facts['panels'])
    deep_pages = {
        'advantage': '#matches',
        'fight': '#matches',
        'objective': '#matches',
        'comp': '#bp',
        'roster': '#players',
        'coverage': '#sources',
    }
    for item in findings:
        assert required <= set(item)
        assert item['n'] >= 2
        assert item['evidence'], item['id']
        assert all(ev['game'] in real_games for ev in item['evidence'])
        assert item['primary_destination'].startswith('#match/')
        assert item['deep_destination'].startswith(deep_pages[item['kind']] + '?')
        assert 'from=' in item['deep_destination'] and 'to=' in item['deep_destination']


def test_home_findings_hide_coverage_reminder(tmp_path):
    """「只有面板 / 缺回放」是数据覆盖提醒，不进首页重点发现。"""
    facts = make_facts(tmp_path, panel_only=True)
    payload = build(facts, classic_metrics=False, period_kind='custom',
                    date_from=day('11-02'), date_to=day('11-04'))
    assert payload['findings'], '去掉覆盖类后仍应有比赛内容的发现'
    assert all(item['kind'] != 'coverage' for item in payload['findings'])
    # 覆盖提醒仍然保留在底部的数据覆盖块里，没有被删掉。
    assert payload['coverage']['panelGames'] >= 1
    assert payload['notes']


def test_deep_destinations_are_not_one_fixed_page(tmp_path):
    facts = make_facts(tmp_path, panel_only=True)
    window = analysis_period.parse_period(
        'custom', today=CURRENT, date_from=day('11-02'), date_to=day('11-04'))
    cur = analysis_period._collect_games(facts, window['from'], window['to'])
    prev = analysis_period._collect_games(
        facts, window['prev']['from'], window['prev']['to'])
    cur_only = analysis_period._collect_panel_only(
        facts, window['from'], window['to'], exclude={item['seq'] for item in cur})
    prev_only = analysis_period._collect_panel_only(
        facts, window['prev']['from'], window['prev']['to'],
        exclude={item['seq'] for item in prev})
    ctx = analysis_period._build_context(
        facts, window, cur, prev, opponent=None, source='db,bundle', validation='0',
        cur_panel_only=cur_only, prev_panel_only=prev_only)
    candidates = {item['id']: item for item in analysis_period.build_candidates(ctx)}
    expected = {
        'lead_hold': 'matches',
        'comeback': 'matches',
        'fight_arrival': 'matches',
        'fight_trade': 'matches',
        'objective': 'matches',
        'comp': 'bp',
        'coverage': 'sources',
    }
    for candidate_id, page in expected.items():
        assert candidate_id in candidates, candidate_id
        assert candidates[candidate_id]['deep_destination'].startswith(f'#{page}?')
    pages = {item['deep_destination'].split('?')[0] for item in candidates.values()}
    assert len(pages) >= 3


# ---------------------------------------------------------------------------
# 接口
# ---------------------------------------------------------------------------
def make_client(tmp_path, **cases_kwargs):
    facts_dir = tmp_path
    fx.write_dataset(facts_dir, _cases(**cases_kwargs))
    app = FastAPI()
    app.include_router(briefing_api.create_briefing_router(
        facts_dir / 'official_replays', facts_dir / 'camp_details', facts_dir, None))
    return TestClient(app), facts_dir


def test_api_shape_and_contract(tmp_path):
    client, _ = make_client(tmp_path, panel_only=True)
    response = client.get('/api/briefing', params={
        'period': 'custom', 'from': day('11-02'), 'to': day('11-04'),
        'source': 'db,bundle', 'validation': '0'})
    assert response.status_code == 200
    payload = response.json()
    assert payload['available'] is True
    for key in ('available', 'reason', 'generatedAt', 'period', 'fallback_hint',
                'coverage', 'record', 'summary', 'metrics', 'findings',
                'watch', 'watchField', 'watchFields', 'next', 'sources', 'notes'):
        assert key in payload
    assert payload['period']['from'] == day('11-02')
    assert payload['period']['prev']['from'] == day('10-30')
    assert payload['record']['decided'] >= 1
    assert payload['record']['prev']['decided'] >= 1
    assert payload['summary']['sentence']
    assert payload['summary']['tone'] in ('up', 'down', 'flat', 'none')
    assert payload['coverage']['games'] == 4
    assert payload['coverage']['panelGames'] == 5
    assert payload['coverage']['withReplay'] == 4
    # 战绩含仅有终局面板的局（4 局有回放 + 1 局面板）
    assert payload['record']['decided'] == 5
    assert payload['record']['unknown'] == 0
    assert len(payload['record']['form']) == 5
    assert all(item['result'] in ('win', 'loss') for item in payload['record']['form'])
    assert payload['coverage']['games'] >= payload['coverage']['withReplay']
    assert payload['sources']['panel'] == payload['coverage']['panelGames']
    assert payload['next']['available'] is False
    assert isinstance(payload['notes'], list)
    for metric in payload['metrics']:
        assert {'id', 'label', 'valueText', 'prevValueText', 'deltaText', 'tone',
                'sample', 'prevSample', 'enough', 'note'} <= set(metric)
    # 复盘筛选：10 个字段都能给出来，默认字段的同组卡片与 watch 一致
    assert [item['id'] for item in payload['watchFields']] == [
        'deficit', 'deaths', 'giveback', 'fight', 'at10', 'duration',
        'dragon', 'tower', 'gold', 'damage']
    assert payload['watchDisplayFields'] == ['deficit', 'at10', 'deaths', 'duration']
    default_items = next(item['items'] for item in payload['watchFields']
                         if item['id'] == payload['watchField'])
    assert payload['watch'] == default_items
    scores = [card['reviewScore'] for card in default_items]
    assert scores == sorted(scores, reverse=True)
    for field in payload['watchFields']:
        assert {'id', 'label', 'note', 'unit', 'count', 'items', 'empty'} <= set(field)
        assert field['empty']
        for card in field['items']:
            assert card['field'] == field['id']
            assert 'start' in card
            ids = [value['id'] for value in card['values']]
            assert len(ids) == len(set(ids))
            assert 'duration' in ids
            assert all(plain_value for plain_value in
                       (str(value['value']) for value in card['values']))

    serialized = json.dumps(payload, ensure_ascii=False)
    for term in ('Wilson', '分位', '效应量', '聚类', '模型'):
        assert term not in serialized


def test_api_invalid_params_400(tmp_path):
    client, _ = make_client(tmp_path)
    assert client.get('/api/briefing?period=custom').status_code == 400
    assert client.get('/api/briefing?period=custom&from=2026-13-01&to=2026-11-06').status_code == 400
    assert client.get('/api/briefing?period=custom&from=2026-11-05&to=2026-11-02').status_code == 400
    assert client.get('/api/briefing?period=year').status_code == 400


def test_api_empty_database_returns_200(tmp_path):
    (tmp_path / 'official_replays').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'camp_details').mkdir(parents=True, exist_ok=True)
    app = FastAPI()
    app.include_router(briefing_api.create_briefing_router(
        tmp_path / 'official_replays', tmp_path / 'camp_details', tmp_path, None))
    response = TestClient(app).get('/api/briefing?period=week')
    assert response.status_code == 200
    payload = response.json()
    assert payload['available'] is False
    assert payload['reason']
    assert payload['metrics'] == [] and payload['findings'] == []


def test_api_empty_period_state(tmp_path):
    client, _ = make_client(tmp_path)
    response = client.get('/api/briefing', params={
        'period': 'custom', 'from': '2026-12-01', 'to': '2026-12-03'})
    assert response.status_code == 200
    payload = response.json()
    assert payload['available'] is False
    assert payload['reason']
    assert payload['fallback_hint'] is None or payload['fallback_hint']['games'] >= 1


def test_single_app_mounts_briefing_router():
    """首页简报挂在唯一的那套 app 上（server.py），只为它挂一次。

    以前 v3/serve.py 有独立的 FastAPI app（只有分析路由、没有采集接口），
    简报得在那儿再挂一遍；两套并成一套后，旁支 app 已删除。
    """
    import ast
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    server = (root / 'server.py').read_text(encoding='utf-8')
    serve = (root / 'v3' / 'serve.py').read_text(encoding='utf-8')
    assert 'create_briefing_router' in server, 'server.py 没有挂 /api/briefing'
    tree = ast.parse(serve)
    own_app = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, 'id', '') == 'FastAPI'
    ]
    assert not own_app, 'v3/serve.py 又自建了 app：分析接口应挂在 server.py 的同一套 app 上'


def test_scrim_metrics_fixed_six_and_dynamic_two(tmp_path):
    """首页 10 项：基本盘 + 比率 + 一塔率 + 四种资源控制率。

    本期胜率已在顶部一句话里给出，十分钟领先兑现率与顶部信息重复，不再单列。
    """
    facts = make_facts(tmp_path)
    payload = analysis_period.build_briefing(
        facts, today=CURRENT, period_kind='custom',
        date_from=day('11-02'), date_to=day('11-04'))
    metrics = payload['metrics']
    ids = [item['id'] for item in metrics]
    expected = ('record', 'lead_rate', 'lead_econ', 'fight_rate', 'first_blood_rate',
                'first_tower_rate', 'tyrant_rate', 'elder_dragon_rate',
                'baron_rate', 'elder_baron_rate')
    assert ids == list(expected)
    assert 'win_rate' not in ids and 'lead_hold_rate' not in ids
    for item in metrics:
        assert item['valueText']
        assert item['coverage']
        assert item['deltaText']
        assert isinstance(item['sample'], int) and isinstance(item['total'], int)
        assert item['href'].startswith('#matches?') and 'from=' in item['href']
    by_id = {item['id']: item for item in metrics}
    # 比例类变化用百分点，经济类用金币
    assert '个百分点' in by_id['lead_rate']['deltaText']
    assert '金币' in by_id['lead_econ']['deltaText']
    # 比率卡面仍带分子分母与百分比，前端只展示百分比、分母放到 title
    assert by_id['lead_rate']['valueText'].count('/') == 1
    assert by_id['lead_rate']['valueSub'].endswith('%')
    for mid in ('tyrant_rate', 'elder_dragon_rate', 'baron_rate', 'elder_baron_rate'):
        if by_id[mid]['sample']:
            assert by_id[mid]['valueSub'] and by_id[mid]['valueSub'].endswith('%')
    assert by_id['lead_econ']['valueText'].endswith('金币')
    # 同批对手排名：x/xx + 领先/中等/落后三档，样本不足时不给排名（字段仍在）
    assert all('rank' in item for item in metrics)
    # 最值得复盘的比赛不能退化成只有标题的空白卡，标题要跟着周期变
    assert payload['watchTitle'] == '重点复盘'
    assert payload['watchCountText'].startswith('发现 ')
    assert payload['findingsTitle'] == '本期重点发现'
    assert payload['watch']
    assert all(card['conclusion'] for card in payload['watch'])
    for card in payload['watch']:
        assert card['rosterPlayers'], card['id']
        assert card['problem'] and card['reviewType']
        assert isinstance(card['reviewScore'], (int, float))
        assert 'foePlayers' in card and 'focusValue' in card
        assert all(player['icon'].startswith('/catalog/icons/')
                   for player in card['rosterPlayers'])
        assert all(player['name'] for player in card['rosterPlayers'])
        assert any(number['label'] == '10 分钟经济差'
                   for number in card['numbers'])


def _peer(value_at10, *, wins=0, decided=1):
    """一支同期对手的镜像数据：十分钟经济差、胜负、龙/塔都给齐字段。"""
    return {'games': decided, 'decided': decided, 'wins': wins,
            'at10': [value_at10], 'lead': 1 if value_at10 > 0 else 0,
            'leadHold': 1 if value_at10 > 0 and wins else 0,
            'fightWins': 0, 'fightTotal': 0,
            'dragons': 0, 'dragonTotal': 0, 'towers': 0, 'towerTotal': 0}


def test_rank_uses_same_period_opponents():
    """排名 = 本期一起训练的战队同口径比较；三档颜色按 25/75 分界。"""
    peers = [_peer(value) for value in (3000, 2500, 2200, 1800, 1500, 900)]
    middle = analysis_period._rank_of('lead_econ', 2000, peers)
    assert (middle['pos'], middle['total']) == (4, 7)
    assert middle['percentile'] == 50.0 and middle['tier'] == 'mid'
    assert middle['text'] == '中等 4/7'
    top = analysis_period._rank_of('lead_econ', 4000, peers)
    assert top['pos'] == 1 and top['percentile'] == 100.0 and top['tier'] == 'lead'
    low = analysis_period._rank_of('lead_econ', 100, peers)
    assert low['pos'] == 7 and low['percentile'] == 0.0 and low['tier'] == 'behind'
    # 对手太少不给排名，避免「1/3」这种假精确
    assert analysis_period._rank_of('lead_econ', 2000, peers[:3]) is None


def test_metrics_prev_empty_says_no_comparison(tmp_path):
    """上期没有对局：指标写「上期暂无可比数据」，不算假变化。"""
    facts = make_facts(tmp_path, prev_games=0)
    payload = analysis_period.build_briefing(
        facts, today=CURRENT, period_kind='custom',
        date_from=day('11-02'), date_to=day('11-04'))
    assert payload['metrics']
    for item in payload['metrics']:
        assert item['deltaText'] in ('上期暂无可比数据', '本期暂无数据')


def test_today_without_games_returns_empty_state(tmp_path):
    """今日无比赛：不回退历史，走空态 + 最近一批入口。"""
    facts = make_facts(tmp_path)
    payload = analysis_period.build_briefing(facts, today=CURRENT, period_kind='today')
    assert payload['available'] is False
    assert payload['metrics'] == [] and payload['findings'] == []
    assert payload['fallback_hint'] and payload['fallback_hint']['games'] >= 1
    assert '11-13' in payload['reason']


def test_panel_only_period_counts_record_only(tmp_path):
    """仅有终局面板：可以算战绩，但时间轴指标没有有效样本。"""
    facts = make_facts(tmp_path, cur_games=0, panel_only=True)
    payload = analysis_period.build_briefing(
        facts, today=CURRENT, period_kind='custom',
        date_from=day('11-04'), date_to=day('11-04'))
    assert payload['available'] is True
    assert payload['record']['decided'] >= 1
    by_id = {item['id']: item for item in payload['metrics']}
    for mid in ('lead_rate', 'lead_econ', 'fight_rate', 'tyrant_rate'):
        assert by_id[mid]['sample'] == 0
        assert by_id[mid]['valueText'] == '—'
    assert len(payload['metrics']) == 10


def test_duplicate_games_are_deduped(tmp_path):
    """重复记录：同一天 / 开赛时间 / 时长 / 对手只算一局。"""
    facts = make_facts(tmp_path)
    order = list(facts['order'])
    facts['order'] = order + [order[0], order[1]]
    payload = analysis_period.build_briefing(
        facts, today=CURRENT, period_kind='custom',
        date_from=day('11-02'), date_to=day('11-04'))
    assert payload['coverage']['games'] == 4
    assert payload['record']['decided'] == 4


def test_missing_process_data_reduces_metric_sample(tmp_path):
    """比赛过程缺失：缺经济曲线的局不进十分钟指标，但仍算战绩。"""
    facts = make_facts(tmp_path)
    seq = next(str(key) for key, game in facts['games'].items()
               if str(game.get('date')) == day('11-02'))
    facts['games'][seq]['ownDiff'] = []
    facts['games'][seq]['hasEconomy'] = False
    payload = analysis_period.build_briefing(
        facts, today=CURRENT, period_kind='custom',
        date_from=day('11-02'), date_to=day('11-04'))
    by_id = {item['id']: item for item in payload['metrics']}
    assert by_id['lead_rate']['sample'] == 3
    assert by_id['lead_rate']['total'] == 4
    assert payload['record']['decided'] == 4


def test_custom_range_across_month_boundary(tmp_path):
    """自定义跨月：上期按等长回退到上月，不丢日期。"""
    facts = make_facts(tmp_path)
    window = analysis_period.parse_period(
        'custom', today=CURRENT, date_from=day('10-28'), date_to=day('11-02'))
    assert (window['prev']['from'], window['prev']['to']) == (day('10-22'), day('10-27'))
    payload = analysis_period.build_briefing(
        facts, today=CURRENT, period_kind='custom',
        date_from=day('10-28'), date_to=day('11-02'))
    assert payload['available'] is True
    assert payload['coverage']['games'] >= 1


def test_unknown_opponent_keeps_system_name(tmp_path):
    """对手未知：用「对阵 #N」，不编造队名、不出现 None。"""
    facts = make_facts(tmp_path)
    for seq in facts['order']:
        facts['games'][seq]['opponentName'] = '待命名战队 #9'
    payload = analysis_period.build_briefing(
        facts, today=CURRENT, period_kind='custom',
        date_from=day('11-02'), date_to=day('11-04'))
    titles = [item['title'] for item in payload['watch']]
    assert titles
    assert all('None' not in title for title in titles)
    assert all('对阵 #9' in title for title in titles)


def _watch_entry(seq, diff, *, date='2026-11-04', deaths=0, fights=(), result='loss'):
    """构造一局只带经济曲线的最小数据，用来验复盘区的排序。"""
    return {
        'seq': str(seq), 'label': f'{date[5:]} · 对阵 #{seq}', 'date': date,
        'result': result, 'opponentId': str(seq), 'opponentName': f'#{seq}',
        'hasReplay': True, 'hasTimeline': True,
        'game': {
            'duration': 1200, 'ownDiff': list(diff),
            'times': [float(i * 60) for i in range(len(diff))],
            # 掉点按「死亡事件的 objID 归属我方」统计，这里造同等数量的死亡事件
            'deaths': [{'objID': f'd{index}'} for index in range(deaths)],
            'objToCamp': {f'd{index}': '1' for index in range(deaths)},
            'fights': list(fights), 'players': [], 'ownCamp': 'blue',
        },
    }


def test_watch_focus_rules():
    """4 个筛选字段各自的成立条件：没落后 / 没掉点 / 没被反超就不进那一组。"""
    stats = {'low': -3000, 'peak': 2500, 'deaths': 5, 'fightLosses': 3,
             'fightTotal': 8, 'at10': -500, 'duration': 1200, 'drawdown': 5500}
    assert analysis_period._watch_focus('deficit', stats)[0] == 3000
    assert analysis_period._watch_focus('deaths', stats)[0] == 5
    assert analysis_period._watch_focus('fight', stats)[0] == 3
    # 领先被反超：领先 ≥1000 且后来真的落后，严重度 = 峰值到谷底
    assert analysis_period._watch_focus('giveback', stats)[0] == 5500
    assert analysis_period._watch_focus('giveback', {**stats, 'low': 200}) is None
    assert analysis_period._watch_focus('giveback', {**stats, 'peak': 600}) is None
    assert analysis_period._watch_focus('deficit', {**stats, 'low': 800}) is None
    # 落后不到 1000 金币不进「最多落后」组：-75 / -999 是噪声，不占复盘位。
    assert analysis_period._watch_focus('deficit', {**stats, 'low': -999}) is None
    assert analysis_period._watch_focus('deficit', {**stats, 'low': -1000})[0] == 1000
    assert analysis_period._watch_focus('deaths', {**stats, 'deaths': 0}) is None
    assert analysis_period._watch_focus('fight', {**stats, 'fightLosses': 0}) is None


def test_watch_groups_sort_by_selected_field():
    """每组按自己那一项从差到好排，主数字排第一并标记 focus。"""
    entries = [
        _watch_entry('a', [0, 2000, 500, -200], deaths=2),
        _watch_entry('b', [0, 800, -5000, -800], deaths=9),
        _watch_entry('c', [0, 600, -3000, -100], deaths=5),
    ]
    groups = analysis_period.build_watch_groups({'cur': entries})
    by_id = {item['id']: item for item in groups['fields']}
    assert [item['id'] for item in groups['fields']] == [
        'deficit', 'deaths', 'giveback', 'fight', 'at10', 'duration',
        'dragon', 'tower', 'gold', 'damage']
    assert groups['display'] == ['deficit', 'at10', 'deaths', 'duration']
    assert groups['field'] == 'deficit'

    deficit = by_id['deficit']['items']
    assert by_id['deficit']['count'] == 2
    assert [card['title'] for card in deficit] == [
        '11-04 · 对阵 #b', '11-04 · 对阵 #c']
    assert [card['numbers'][0]['value'] for card in deficit] == [
        '-5,000 金币', '-3,000 金币']

    deaths = by_id['deaths']['items']
    assert [card['numbers'][0]['value'] for card in deaths] == ['9 次', '5 次', '2 次']

    for field in by_id.values():
        assert field['count'] == len(field['items'])
        for card in field['items']:
            assert card['field'] == field['id']
            assert card['numbers'][0]['focus'] is True
            assert sum(1 for number in card['numbers'] if number.get('focus')) == 1
            assert len(card['numbers']) <= 4
            assert card['conclusion'].startswith('打了 20 分钟')


def test_findings_cards_carry_fold_and_pair_data(tmp_path):
    """重点发现卡要能独立渲染：标签、折叠摘要、建议、双条件对位都在 payload 里。"""
    facts = make_facts(tmp_path)
    payload = analysis_period.build_briefing(
        facts, today=CURRENT, period_kind='custom',
        date_from=day('11-02'), date_to=day('11-04'))
    findings = payload['findings']
    assert findings
    for item in findings:
        assert item['statusTag'] and item['categoryTag']
        assert item['foldSummary']
        assert isinstance(item['heroes'], list)
    paired = [item for item in findings if item.get('pair')]
    assert paired
    for item in paired:
        for side in ('left', 'right'):
            block = item['pair'][side]
            assert block['label'] and block['value'] and block['fraction']
            assert isinstance(block['ratio'], (int, float))
    hold = next((item for item in findings if item['id'].startswith('lead_hold')), None)
    assert hold is not None
    assert [entry['label'] for entry in hold['stats']] == ['本期兑现', '上期兑现']
    assert hold['relatedMatches']
    for match in hold['relatedMatches']:
        assert match['id'] and match['label']
        assert isinstance(match['rosterPlayers'], list)
        assert isinstance(match['foePlayers'], list)


def test_summary_is_one_plain_sentence():
    """顶部一句话只说局数、胜负、胜率：不带日期区间，也不跟上期比较。"""
    window = {'kind': 'week'}
    record = {'decided': 9, 'wins': 4, 'losses': 5, 'unknown': 0, 'winRate': 44.4}
    prev = {'decided': 81, 'wins': 54, 'losses': 27, 'unknown': 0, 'winRate': 66.7}
    sentence, tone = analysis_period._sentence(window, record, prev)
    assert sentence == '本周 9 局训练赛，4 胜 5 负，胜率 44.4%。'
    assert tone == 'none'
    assert '少赢 50 局' not in sentence and '个百分点' not in sentence

    # 样本接近时也不追加「少赢 2 局」，上期信息由指标表的「上期/变化」列承担。
    near = {'decided': 10, 'wins': 6, 'losses': 4, 'unknown': 0, 'winRate': 60.0}
    sentence, tone = analysis_period._sentence(window, record, near)
    assert sentence == '本周 9 局训练赛，4 胜 5 负，胜率 44.4%。'
    assert tone == 'none'


def test_watch_card_marks_comeback_and_throw():
    """落后翻盘的赢局与领先被翻的输局，文案和标签都要分开。"""
    entries = [
        _watch_entry('w', [0, -4000, -5000, 3000], result='win'),
        _watch_entry('t', [0, 4000, 5000, -3000], result='loss'),
    ]
    groups = analysis_period.build_watch_groups({'cur': entries})
    cards = next(item for item in groups['fields'] if item['id'] == 'deficit')['items']
    by_seq = {card['title'].rsplit('#', 1)[-1]: card for card in cards}
    win_card = by_seq['w']
    assert win_card['resultTag'] == '翻盘'
    assert '最后翻回来了' in win_card['conclusion']
    assert '中段怎么被拉开、后期怎么打回来' in win_card['conclusion']
    throw_card = by_seq['t']
    assert throw_card['resultTag'] == '被翻盘'
    assert '先看优势是怎么丢的' in throw_card['conclusion']


def test_watch_catalog_values_cover_new_fields():
    """10 个字段：卡片 values 覆盖丢龙 / 被推塔 / 终局经济 / 输出占比等新口径。"""
    own_diff = [0, 800, 1200, 1500, 1800, -2500, -3000, -3500, -4000, -4200, -4500]
    game = {
        'duration': 1200,
        'ownDiff': own_diff,
        'times': [float(index * 120) for index in range(len(own_diff))],
        'deaths': [{'objID': f'd{index}'} for index in range(2)],
        'objToCamp': {f'd{index}': '1' for index in range(2)},
        'ownCamp': 'blue',
        'players': [],
        'events': [
            {'dtType': '1', 'dtId': '8', 'killerCamp': '2', 'timeSec': 420},
            {'dtType': '1', 'dtId': '9', 'killerCamp': '1', 'timeSec': 500},
            {'dtType': '1', 'dtId': '17', 'killerCamp': '2', 'timeSec': 900},
            {'dtType': '2', 'dtId': '11', 'killerCamp': '2', 'timeSec': 1000},
        ],
        'fights': [
            {'startSec': 300, 'endSec': 320,
             'kills': [{'killerCamp': '2'}, {'killerCamp': '2'}]},
            {'startSec': 600, 'endSec': 620, 'kills': [{'killerCamp': '1'}]},
        ],
    }
    panel = {
        'ownRoster': [{'gold': 40000, 'heroDamage': 200000},
                      {'gold': 32000, 'heroDamage': 120000}],
        'enemyRoster': [{'gold': 46000, 'heroDamage': 260000},
                        {'gold': 38000, 'heroDamage': 160000}],
    }
    entries = [{
        'seq': '9001', 'label': '11-04 · 对阵 #9', 'date': '2026-11-04',
        'result': 'loss', 'opponentId': '9', 'opponentName': '#9',
        'hasReplay': True, 'hasTimeline': True, 'panel': panel, 'game': game,
    }]
    groups = analysis_period.build_watch_groups({'cur': entries})
    by_id = {field['id']: field for field in groups['fields']}
    card = by_id['deficit']['items'][0]
    values = {value['id']: value['value'] for value in card['values']}
    assert values['deficit'] == '-4,500 金币'
    assert values['at10'] == '-2,500 金币'
    assert values['deaths'] == '2 次'
    assert values['duration'] == '20:00'
    assert values['dragon'] == '2 条'
    assert values['tower'] == '1 座'
    assert values['gold'] == '-12,000 金币'
    assert values['damage'] == '43.2%'
    # 每个异常字段都能单独成组，且主数字就是这一项
    for field_id, expected in (
            ('deficit', '-4,500 金币'), ('at10', '-2,500 金币'),
            ('deaths', '2 次'), ('giveback', '-6,300 金币'),
            ('fight', '1 波'), ('duration', '20:00'),
            ('dragon', '2 条'), ('tower', '1 座'),
            ('gold', '-12,000 金币'), ('damage', '43.2%')):
        assert by_id[field_id]['count'] == 1, field_id
        assert by_id[field_id]['items'][0]['numbers'][0]['value'] == expected, field_id
    # 十分钟领先 / 零丢龙的局不进「异常」组
    assert analysis_period._watch_focus(
        'at10', {**analysis_period._game_stats(game, panel), 'at10': 1200}) is None
    assert analysis_period._watch_focus('deficit', {'low': 500}) is None
    assert analysis_period._watch_focus('gold', {'goldDiff': 3000}) is None
    assert analysis_period._watch_focus('damage', {'damagePct': 55.0}) is None
    assert analysis_period._watch_focus('dragon', {'dragonsLost': 0}) is None
    # 没有面板 / 没有事件时不补 0，直接不给这一项
    bare = analysis_period._game_stats({'duration': 1200, 'ownDiff': own_diff})
    assert bare['goldDiff'] is None and bare['damagePct'] is None
    assert bare['dragonsLost'] == 0 and bare['towersLost'] == 0
    assert analysis_period._watch_value('gold', bare) is None


def test_findings_not_capped_at_three():
    """重点发现不再固定 3 条：不同 kind / 主题的候选全部返回（前端区块内滚动）。"""
    candidates = []
    for index, (kind, theme) in enumerate((
            ('advantage', 'lead'), ('fight', 'fight'), ('objective', 'objective'),
            ('comp', 'lineup_a'), ('roster', 'lineup_b'), ('training', 'arrange'))):
        candidates.append({
            'kind': kind, 'theme': theme, 'id': f'c{index}', 'tone': 'down',
            'title': f'标题 {index}', 'conclusion': '结论', 'numbers': [],
            'sample': 5, 'enough': True, 'score': 10 - index,
            'evidence': [{'game': '1', 'label': 'x'}],
            'counterexamples': [],
            'primary_destination': '#match/1',
            'deep_destination': '#matches?from=a&to=b',
            'limitation': '',
        })
    out = analysis_period.select_findings(candidates)
    assert len(out) == 6
    assert [item['kind'] for item in out] == [
        'advantage', 'fight', 'objective', 'comp', 'roster', 'training']


def test_findings_dedup_and_limit_removed_from_payload(tmp_path):
    """payload 的 findingsCountText 跟实际条数走，没有 3 条上限。"""
    facts = make_facts(tmp_path, panel_only=True)
    payload = build(facts, period_kind='custom', classic_metrics=False,
                    date_from=day('11-02'), date_to=day('11-04'))
    assert payload['findingsCountText'] == f'{len(payload["findings"])} 项发现'


def test_watch_group_not_capped_at_three():
    """复盘分组不再固定 3 局：最多给 WATCH_LIMIT 局，count 仍是本项总局数。"""
    entries = [_watch_entry(str(index), [0, -1000 * (index + 1)], deaths=10 + index)
               for index in range(8)]
    groups = analysis_period.build_watch_groups({'cur': entries})
    by_id = {field['id']: field for field in groups['fields']}
    assert len(by_id['deaths']['items']) == 8
    assert by_id['deaths']['count'] == 8

    many = [_watch_entry(str(index), [0, -1000], deaths=1) for index in range(60)]
    groups = analysis_period.build_watch_groups({'cur': many})
    by_id = {field['id']: field for field in groups['fields']}
    assert analysis_period.WATCH_LIMIT == 50
    assert len(by_id['deaths']['items']) == 50
    assert by_id['deaths']['count'] == 60


def test_watch_card_moments():
    """关键时间点：最多 3 个、时间升序、clock 是 m:ss；没有事实就不编。"""
    own_diff = [0, 800, 1200, 1500, 1800, -2500, -3000, -3500, -4000, -4200, -4500]
    game = {
        'duration': 1200,
        'ownDiff': own_diff,
        'times': [float(index * 120) for index in range(len(own_diff))],
        'deaths': [{'objID': f'd{index}'} for index in range(2)],
        'objToCamp': {f'd{index}': '1' for index in range(2)},
        'ownCamp': 'blue',
        'players': [],
        'events': [
            {'dtType': '1', 'dtId': '8', 'killerCamp': '2', 'timeSec': 420},
            {'dtType': '1', 'dtId': '17', 'killerCamp': '2', 'timeSec': 900},
            {'dtType': '2', 'dtId': '11', 'killerCamp': '2', 'timeSec': 1000},
        ],
        'fights': [
            {'startSec': 300, 'endSec': 320,
             'kills': [{'killerCamp': '2'}, {'killerCamp': '2'}]},
        ],
    }
    stats = analysis_period._game_stats(game)
    moments = analysis_period._watch_moments({'game': game}, stats, 'deficit')
    assert 1 <= len(moments) <= analysis_period.MOMENT_LIMIT == 3
    assert [item['t'] for item in moments] == sorted(item['t'] for item in moments)
    assert all(re.fullmatch(r'\d{1,2}:\d{2}', item['clock']) for item in moments)
    assert all(item['t'] > 0 for item in moments)
    assert any('最多落后' in item['label'] or '领先被反超' in item['label']
               for item in moments)

    dragon = analysis_period._watch_moments({'game': game}, stats, 'dragon')
    assert any(item['label'].startswith('丢') for item in dragon)

    # 没有任何回放事实：返回空数组，不编时间点
    bare = {'game': {'duration': 0, 'ownDiff': [], 'times': []}}
    bare_stats = analysis_period._game_stats({'duration': 0})
    assert analysis_period._watch_moments(bare, bare_stats, 'deficit') == []

    # 复盘卡里要带 moments 字段（每组每张卡都有，可能是空数组）
    entries = [{
        'seq': '9001', 'label': '11-04 · 对阵 #9', 'date': '2026-11-04',
        'result': 'loss', 'opponentId': '9', 'opponentName': '#9',
        'hasReplay': True, 'hasTimeline': True, 'panel': None, 'game': game,
    }]
    groups = analysis_period.build_watch_groups({'cur': entries})
    for field in groups['fields']:
        for card in field['items']:
            assert 'moments' in card and isinstance(card['moments'], list)


def test_watch_payload_links_use_match_keys():
    """复盘卡（含各筛选分组）也要换成真实对局 key，不能指向营地 seq。"""
    card = {'id': 'watch_2001_deficit', 'evidence': [{'game': '2001', 'label': '这局过程'}],
            'primary_destination': '#match/2001', 'deep_destination': ''}
    payload = {'findings': [], 'watch': [card],
               'watchFields': [{'id': 'deficit', 'items': [card]}]}
    mapped = briefing_api._apply_match_keys(
        payload, {'2001': 'channel-abc'}, fallback_query='from=a&to=b')
    assert mapped['watch'][0]['primary_destination'] == '#match/channel-abc'
    assert mapped['watch'][0]['evidence'][0]['game'] == 'channel-abc'
    assert mapped['watchFields'][0]['items'][0] is card
