"""decision_loss 失利关键链 / 优势保持：契约 2.2 的窗口、分类、排序、分位带与样本不足。

全部用 ``tests/decision_fixtures.py`` 的合成数据，不依赖真实赛训库；断言尽量用
手算的具体数值（合成 diff 刻意做成单点跳变，窗口可人工推导）。
"""
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parent
for _path in (str(ROOT), str(TESTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import decision_loss as dl  # noqa: E402
from decision_fixtures import load_fixture_facts, write_dataset  # noqa: E402

YEAR = datetime.now().year


# ---------------------------------------------------------------------------
# 合成数据小工具
# ---------------------------------------------------------------------------
def _step_diff(drop, *, n=21, at=10):
    """第 at 个采样点起整体变化 drop（负=我方吃亏），其余点保持 0。"""
    return [0] * at + [drop] * (n - at)


def _event(t, *, dt_type='1', dt_id='9', killer_camp='1', dt_camp='1'):
    return {
        'eventType': 'dragontower', 'timeSec': float(t), 'dtType': dt_type,
        'dtId': dt_id, 'dtCamp': dt_camp, 'killerCamp': killer_camp,
    }


def _death(camp, t, obj_id):
    return {'objID': obj_id, 'camp': camp, 'heroId': int(obj_id),
            'x': 0.0, 'y': 0.0, 'timeSec': float(t)}


def _fight(*, kills, start=280.0, end=320.0):
    participants = [{'objID': f'1{index}', 'camp': '1', 'timeSec': start}
                    for index in range(5)]
    participants += [{'objID': f'2{index}', 'camp': '2', 'timeSec': start}
                     for index in range(5)]
    kill_list = [{
        'timeSec': float(t), 'killerCamp': camp, 'killer': 'x',
        'victimCamp': '2' if camp == '1' else '1', 'victim': 'y',
    } for camp, t in kills]
    return {'fightId': 'f1', 'startSec': float(start), 'endSec': float(end),
            'camp1': 5, 'camp2': 5, 'participants': participants,
            'kills': kill_list}


def _facts(tmp_path, cases):
    write_dataset(tmp_path, cases=cases)
    return load_fixture_facts(tmp_path)


def _class_cases():
    """六局各触发一个主类；diff 相同：第 10 个采样点起 -1500。"""
    diff = _step_diff(-1500)
    return [
        # 我方 4 人阵亡（全部落在 30 秒窗口 270–300s 内）→ wipe
        {'seq': '1001', 'diff': diff, 'own_win': False, 'fights': [], 'events': [],
         'deaths': [_death('1', 275, '101'), _death('1', 280, '102'),
                    _death('1', 285, '103'), _death('1', 290, '104')]},
        # 我方 2 人阵亡 → multi_death
        {'seq': '1002', 'diff': diff, 'own_win': False, 'fights': [], 'events': [],
         'deaths': [_death('1', 280, '101'), _death('1', 285, '102')]},
        # 团战击杀差 -3 → teamfight_loss
        {'seq': '1003', 'diff': diff, 'own_win': False, 'deaths': [], 'events': [],
         'fights': [_fight(kills=[('2', 305), ('2', 310), ('2', 315)])]},
        # 敌方拿到建筑且我方 0 → objective_lost
        {'seq': '1004', 'diff': diff, 'own_win': False, 'deaths': [], 'fights': [],
         'events': [_event(300, dt_type='2', dt_id='1', killer_camp='2')]},
        # 关联窗口内无我方收益 → no_trade
        {'seq': '1005', 'diff': diff, 'own_win': False, 'fights': [], 'events': [],
         'deaths': []},
        # 我方打赢团战（有收益）但没有其它主类 → unclassified
        {'seq': '1006', 'diff': diff, 'own_win': False, 'deaths': [], 'events': [],
         'fights': [_fight(kills=[('1', 305), ('1', 310)])]},
    ]


def _adv_cases():
    """优势保持指标的手算样本：11/9/8 个经济点 × 4 种时长。"""
    return [
        {'seq': '4001', 'own_win': True, 'duration': 600,
         'diff': [0, 200, 800, 1200, 1500, 1600, 1200, 900, 500, 200, -300],
         'events': [_event(420, dt_type='1', dt_id='9', killer_camp='1')]},
        {'seq': '4002', 'own_win': False, 'duration': 600,
         'diff': [0, 300, 900, 1400, 1800, 1500, 900, 400, 0, -500, -1200],
         'events': []},
        {'seq': '4003', 'own_win': True, 'duration': 600,
         'diff': [100, 200, 400, 800, 2000, 2400, 2200, 2000, 1800, 1600, 1500],
         'events': [_event(300, dt_type='2', dt_id='1', killer_camp='1')]},
        {'seq': '4004', 'own_win': True, 'duration': 480,
         'diff': [0, 500, 1000, 1500, 2000, 2200, 2000, 1800, 1500],
         'events': []},
        {'seq': '4005', 'own_win': True, 'duration': 700,
         'diff': [0, 100, 200, 300, 400, 600, 800, 1000], 'events': []},
    ]


def _patch_opponent(root, seq):
    """把某局面板的敌方 playerId 改掉，造出第二个对手用于过滤测试。"""
    path = Path(root) / 'camp_details' / f'{seq}.json'
    payload = json.loads(path.read_text(encoding='utf-8'))
    for role in payload['data']['redRoles']:
        role['basicInfo']['playerId'] = 'other-' + role['basicInfo']['playerId']
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')


# ---------------------------------------------------------------------------
# 失利关键链
# ---------------------------------------------------------------------------
def test_default_fixture_reports(tmp_path):
    """默认合成局（write_dataset 不传 cases）：两个报告都能给出具体数字。"""
    write_dataset(tmp_path)
    facts = load_fixture_facts(tmp_path)
    assert facts['order'] == ['1001']

    loss = dl.loss_report(facts)
    assert loss['available'] is True
    assert loss['summary']['windows'] == 2            # 只保留 120 秒负向窗口
    assert [row['delta'] for row in loss['rows']] == [-1300, -1300]
    assert {row['windowSec'] for row in loss['rows']} == {120}
    assert {row['phase'] for row in loss['rows']} == {'发育期'}
    assert loss['summary']['enough'] is False
    assert '只做观察' in loss['summary']['reason']

    advantage = dl.advantage_report(facts)
    game = advantage['games'][0]
    assert game['game'] == '1001'
    assert game['maxLead'] == 2400 and game['maxLeadAt'] == 266.7
    assert game['drawdown'] == 2800 and game['drawdownAt'] == 600.0
    assert game['leadDurationSec'] == 400.0
    assert game['conversionSec'] == 160.0             # 200s 领先 → 360s 拿暴君
    assert game['postLead2mDelta'] == 560
    assert game['leadAt10'] == -400 and game['leadAt10Bucket'] == '持平'
    assert game['comeback'] is False
    buckets = {item['bucket']: item for item in advantage['buckets']}
    assert buckets['持平']['n'] == 1 and buckets['持平']['wins'] == 1
    assert advantage['paths'][0]['key'] == 'resource|1|win'


def test_loss_negative_windows_sorted_and_limited(tmp_path):
    """只取负向窗口；rows 按损失从大到小排序；limit 只截 rows 不截 summary。"""
    facts = _facts(tmp_path, [
        {'seq': '2001', 'diff': _step_diff(-3000), 'own_win': True},
        {'seq': '2002', 'diff': _step_diff(-1200), 'own_win': False},
        {'seq': '2003', 'diff': _step_diff(-2000, at=15), 'own_win': True},
    ])
    report = dl.loss_report(facts)
    assert report['available'] is True
    deltas = [row['delta'] for row in report['rows']]
    assert deltas == sorted(deltas)                      # 最伤的在前（-3000 → -1200）
    assert set(deltas[:3]) == {-3000}
    assert report['rows'][0]['game'] == '2001'
    assert report['rows'][0]['confidence'] == 'candidate'
    # 单点跳变在 30/60/120 秒窗口里各命中 1/2/4 个，共 7 条/局
    assert report['summary']['windows'] == 7 * 3
    assert report['summary']['enough'] is True
    limited = dl.loss_report(facts, limit=4)
    assert len(limited['rows']) == 4
    assert limited['summary']['windows'] == report['summary']['windows']
    # 过滤后只剩败局：仍返回该局窗口（不是空图）
    loss_rows = dl.loss_report(facts, result='loss')
    assert loss_rows['available'] is True
    assert loss_rows['summary']['windows'] > 0
    assert {row['game'] for row in loss_rows['rows']} == {'2002'}


def test_loss_primary_types(tmp_path):
    """六个主类各命中一局；candidates 保留全部关联候选。"""
    facts = _facts(tmp_path, _class_cases())
    report = dl.loss_report(facts)
    expected = {
        '1001': 'wipe',
        '1002': 'multi_death',
        '1003': 'teamfight_loss',
        '1004': 'objective_lost',
        '1005': 'no_trade',
        '1006': 'unclassified',
    }
    by_game = {}
    for row in report['rows']:
        by_game.setdefault(row['game'], set()).add(row['type'])
    for seq, kind in expected.items():
        assert by_game[seq] == {kind}, (seq, by_game.get(seq))
    # 40 条以上窗口，六个主类计数一致（每局 7 条）
    assert report['summary']['windows'] == 42
    assert report['summary']['byType'] == {
        'wipe': 7, 'multi_death': 7, 'teamfight_loss': 7,
        'objective_lost': 7, 'no_trade': 7, 'unclassified': 7,
    }
    # 窗口细节：单点跳变在 30 秒窗口里从 270s 到 300s，损失 -1500
    wipe_rows = [row for row in report['rows'] if row['game'] == '1001']
    window30 = next(row for row in wipe_rows if row['windowSec'] == 30)
    assert (window30['start'], window30['end']) == (270.0, 300.0)
    assert window30['delta'] == -1500
    assert window30['phase'] == '发育期'
    assert len(window30['candidates']) == 4
    assert {item['side'] for item in window30['candidates'] if item['kind'] == 'death'} == {'own'}
    # objective_lost 的候选带敌方阵营；teamfight_loss 的团战击杀差为 -3
    objective_row = next(row for row in report['rows'] if row['game'] == '1004')
    objective = next(item for item in objective_row['candidates'] if item['kind'] == 'objective')
    assert objective['camp'] == 'enemy' and objective['name'] == '防御塔'
    fight_row = next(row for row in report['rows'] if row['game'] == '1003')
    fight = next(item for item in fight_row['candidates'] if item['kind'] == 'fight')
    assert fight['killDiff'] == -3
    assert all(row['confidence'] == 'candidate' for row in report['rows'])
    assert '候选事件' in report['note'] and '不证明因果' in report['note']


def test_loss_patterns_and_phase_summary(tmp_path):
    """patterns 按主类汇总、evidence 最多 5 条；阶段统计按窗口起点。"""
    facts = _facts(tmp_path, _class_cases())
    report = dl.loss_report(facts)
    patterns = {item['type']: item for item in report['summary']['patterns']}
    assert set(patterns) == {
        'wipe', 'multi_death', 'teamfight_loss',
        'objective_lost', 'no_trade', 'unclassified',
    }
    wipe = patterns['wipe']
    assert wipe['windows'] == 7 and wipe['games'] == 1
    assert wipe['avgCost'] == -1500.0 and wipe['minCost'] == -1500
    assert wipe['enough'] is False                     # 该主类窗口数 7 < 10
    assert '只做观察' in wipe['reason']
    assert len(wipe['evidence']) == 5                    # 上限 5 条
    evidence = wipe['evidence'][0]
    assert {'game', 'label', 'start', 'end', 'cost', 'text'} <= set(evidence)
    assert evidence['game'] == '1001' and evidence['cost'] == -1500
    phases = {item['phase']: item for item in report['summary']['phases']}
    # 60/120 秒窗口起点在 180–270s：对线期 12 条、发育期 30 条、后期 0 条
    assert phases['对线期']['windows'] == 12
    assert phases['发育期']['windows'] == 30
    assert phases['后期']['windows'] == 0
    assert phases['发育期']['avgCost'] == -1500.0
    assert phases['后期']['avgCost'] is None


def test_loss_game_detail_series_and_chains(tmp_path):
    """game 参数返回单局 series（含 approx）与按 cost 排序的 chains。"""
    facts = _facts(tmp_path, [
        {'seq': '2002', 'diff': _step_diff(-1200), 'own_win': False},
    ])
    report = dl.loss_report(facts, game='2002')
    assert report['available'] is True
    assert len(report['rows']) == 7
    detail = report['game']
    assert detail['id'] == '2002'
    assert detail['result'] == 'loss'
    series = detail['series']
    assert series['approx'] is True
    assert series['times'] == facts['games']['2002']['times']
    assert series['ownDiff'] == facts['games']['2002']['ownDiff']
    assert series['rawDiff'] == facts['games']['2002']['diff']
    assert series['ownDiff'][10] == -1200
    chains = detail['chains']
    assert len(chains) == 7
    assert [chain['delta'] for chain in chains] == sorted(chain['delta'] for chain in chains)
    assert {chain['game'] for chain in chains} == {'2002'}
    # 单局详情的时间必须由 facts.times 推导（近似采样，不做精确声称）
    starts = [chain['start'] for chain in chains]
    assert all(start in series['times'] for start in starts)
    # series 之外再要一局不存在的对局 → available=false
    missing = dl.loss_report(facts, game='nope')
    assert missing['available'] is False and missing['game'] is None
    assert '没有可用对局' in missing['reason']


def test_loss_filters(tmp_path):
    """result / date / opponent / game 过滤，以及过滤为空时的空态。"""
    facts = _facts(tmp_path, [
        {'seq': '2001', 'diff': _step_diff(-3000), 'own_win': True,
         'start': '11-02 12:00'},
        {'seq': '2002', 'diff': _step_diff(-1200), 'own_win': False,
         'start': '11-03 12:00'},
        {'seq': '2003', 'diff': _step_diff(-2000, at=15), 'own_win': True,
         'start': '11-04 12:00'},
    ])
    # result
    loss_only = dl.loss_report(facts, result='loss')
    assert {row['game'] for row in loss_only['rows']} == {'2002'}
    assert loss_only['summary']['results'] == {'win': 0, 'loss': 1, 'unknown': 0}
    assert loss_only['filters']['result'] == 'loss'
    # 日期（面板 startTime 只有月-日，年份按本机当前年补齐）
    ranged = dl.loss_report(facts, date_from=f'{YEAR}-11-03')
    assert {row['game'] for row in ranged['rows']} == {'2002', '2003'}
    assert ranged['summary']['games'] == 2
    ranged_to = dl.loss_report(facts, date_to=f'{YEAR}-11-02')
    assert {row['game'] for row in ranged_to['rows']} == {'2001'}
    # 对手过滤：改掉 2002 敌方 playerId，形成第二个对手
    _patch_opponent(tmp_path, '2002')
    facts = load_fixture_facts(tmp_path)
    opponent_id = facts['games']['2002']['opponentId']
    assert facts['games']['2001']['opponentId'] != opponent_id
    by_opponent = dl.loss_report(facts, opponent=opponent_id)
    assert by_opponent['available'] is True
    assert {row['game'] for row in by_opponent['rows']} == {'2002'}
    assert by_opponent['summary']['games'] == 1
    # 未知对手 / 未来日期 → available=false + reason
    unknown = dl.loss_report(facts, opponent='team-not-exist')
    assert unknown['available'] is False and unknown['rows'] == []
    assert unknown['reason']
    future = dl.loss_report(facts, date_from='2099-01-01')
    assert future['available'] is False and future['reason']


def test_loss_positive_only_has_no_rows(tmp_path):
    """全为正向变化的局：available=true，但窗口数为 0（不伪造失利链）。"""
    facts = _facts(tmp_path, [
        {'seq': '3001', 'own_win': True,
         'diff': [0, 300, 600, 900, 1200, 1500, 1800, 2100, 2400, 2700, 3000],
         'events': []},
    ])
    report = dl.loss_report(facts)
    assert report['available'] is True
    assert report['rows'] == []
    assert report['summary']['windows'] == 0
    assert report['summary']['enough'] is False
    assert '失利窗口仅 0 条' in report['summary']['reason']


def test_loss_empty_facts_and_missing_economy(tmp_path):
    """空事实表 / 有对局但无经济序列：available=false + reason，不 0 填充。"""
    empty_facts = load_fixture_facts(tmp_path / 'empty')
    assert empty_facts['order'] == []
    empty = dl.loss_report(empty_facts)
    assert empty['available'] is False
    assert empty['rows'] == [] and empty['game'] is None
    assert '没有可用对局' in empty['reason']
    assert empty['summary']['windows'] == 0

    no_economy = _facts(tmp_path / 'no-economy', [
        {'seq': '9001', 'diff': [], 'own_win': True},
    ])
    assert no_economy['games']['9001']['hasEconomy'] is False
    report = dl.loss_report(no_economy)
    assert report['available'] is False
    assert '经济序列' in report['reason']
    assert report['coverage']['skippedGames'] == 1


def test_loss_small_sample_reason(tmp_path):
    """样本不足：available 仍为 true，但 enough=false 且给出原因。"""
    facts = _facts(tmp_path, _class_cases()[:1])
    report = dl.loss_report(facts)
    assert report['available'] is True
    assert report['summary']['windows'] == 7       # 1 局 × 7 窗口
    assert report['summary']['enough'] is False
    assert '只做观察' in report['summary']['reason']


def test_loss_rows_have_contract_fields(tmp_path):
    """rows 字段名严格对齐契约 2.2，且 filters 回显过滤条件。"""
    facts = _facts(tmp_path, [{'seq': '2001', 'diff': _step_diff(-3000)}])
    report = dl.loss_report(facts, result='win', limit=3)
    assert {'available', 'filters', 'summary', 'rows', 'game', 'coverage', 'note',
            'reason'} <= set(report)
    required = {'game', 'label', 'opponent', 'result', 'ownCamp', 'phase',
                'start', 'end', 'delta', 'type', 'typeLabel', 'candidates',
                'evidence', 'confidence'}
    for row in report['rows']:
        assert required <= set(row)
        assert row['typeLabel'] == dl.TYPE_LABELS[row['type']]
        assert isinstance(row['evidence'], list) and row['evidence']
        assert row['approx'] is True
    assert report['filters']['result'] == 'win'
    assert report['filters']['limit'] == 3


# ---------------------------------------------------------------------------
# 优势保持
# ---------------------------------------------------------------------------
def test_advantage_game_metrics(tmp_path):
    """maxLead / drawdown / leadDuration / conversion / postLead2mDelta / comeback。"""
    facts = _facts(tmp_path, _adv_cases())
    report = dl.advantage_report(facts)
    assert report['available'] is True
    games = {game['game']: game for game in report['games']}
    assert set(games) == {'4001', '4002', '4003', '4004', '4005'}

    first = games['4001']
    assert first['maxLead'] == 1600 and first['maxLeadAt'] == 300.0
    assert first['drawdown'] == 1900 and first['drawdownAt'] == 600.0
    assert first['leadDurationSec'] == 420.0          # 500+ 的 7 个相邻区间 × 60 秒
    assert first['firstLeadAt'] == 180.0              # 首个 ≥1000 的采样点
    assert first['conversionSec'] == 240.0            # 180s 领先 → 420s 拿暴君
    assert first['postLead2mDelta'] == 400            # 300s(1600) - 180s(1200)
    assert first['comeback'] is False
    assert first['leadAt10'] == -300                  # 十分钟经济差（终局回吐）
    assert first['leadAt10Bucket'] == '持平'

    comeback = games['4002']
    assert comeback['maxLead'] == 1800 and comeback['comeback'] is True
    assert comeback['drawdown'] == 3000 and comeback['leadAt10Bucket'] == '落后'
    assert comeback['postLead2mDelta'] == 100         # 300s(1500) - 180s(1400)
    assert comeback['conversionSec'] is None

    push = games['4003']
    assert push['maxLead'] == 2400 and push['drawdown'] == 900
    assert push['conversionSec'] == 60.0              # 240s 领先 → 300s 推塔
    assert push['leadAt10'] == 1500 and push['leadAt10Bucket'] == '大优'

    # 时长 <600 秒：不参与 leadAt10（不补 0、不给分桶），其它指标按实际时长算
    short = games['4004']
    assert short['duration'] == 480.0
    assert short['leadAt10'] is None and short['leadAt10Bucket'] is None
    assert short['maxLead'] == 2200 and short['drawdown'] == 700
    assert short['leadDurationSec'] == 420.0
    # 没有 120 秒余量的局：postLead2mDelta 为 null
    late = games['4005']
    assert late['maxLead'] == 1000 and late['postLead2mDelta'] is None
    assert late['drawdown'] == 0

    # 回撤排行：games 按 drawdown 降序
    assert [game['game'] for game in report['games']] == [
        '4002', '4001', '4003', '4004', '4005']
    assert report['summary']['maxDrawdownGame']['game'] == '4002'


def test_advantage_summary_and_sample_size(tmp_path):
    """ledGames / comebacks / Wilson 区间 / 均值与各自 n。"""
    facts = _facts(tmp_path, _adv_cases())
    summary = dl.advantage_report(facts)['summary']
    assert summary['games'] == 5
    assert summary['ledGames'] == 5
    assert summary['comebacks'] == 1
    assert summary['comebackRate'] == 20.0
    assert summary['comebackCiLow'] <= 20.0 <= summary['comebackCiHigh']
    assert summary['enough'] is False                  # ledGames 5 < 10
    assert '领先局仅 5 局' in summary['reason']
    assert summary['avgMaxLead'] == 1800.0
    assert summary['medianMaxLead'] == 1800.0
    assert summary['avgDrawdown'] == 1300.0
    assert summary['avgLeadDurationSec'] == 352.0
    assert summary['avgConversionSec'] == 150.0        # 4001:240 + 4003:60，n=2
    assert summary['avgPostLead2mDelta'] == 425.0      # (400+100+200+1000)/4
    assert summary['avgLeadAt10'] == 200.0             # (-300-1200+1500+800)/4
    assert summary['conversionN'] == 2
    assert summary['conversionMissing'] == 3
    assert summary['n'] == {
        'maxLead': 5, 'drawdown': 5, 'leadDurationSec': 5,
        'conversionSec': 2, 'postLead2mDelta': 4, 'leadAt10': 4,
    }


def test_advantage_comeback_rate_enough(tmp_path):
    """领先 ≥1000 共 12 局、其中 3 局被翻 → 翻盘率 25%，样本够时 enough=true。"""
    diff = [0, 300, 1100, 1500, 1600, 1500, 1200, 900, 600, 300, -300]
    cases = [{'seq': f'600{index}', 'own_win': index >= 3, 'diff': diff, 'events': []}
             for index in range(12)]
    facts = _facts(tmp_path, cases)
    summary = dl.advantage_report(facts)['summary']
    assert summary['ledGames'] == 12
    assert summary['comebacks'] == 3
    assert summary['comebackRate'] == 25.0
    assert summary['enough'] is True
    assert summary['reason'] is None
    assert summary['comebackCiLow'] <= 25.0 <= summary['comebackCiHigh']


def test_advantage_buckets(tmp_path):
    """十分钟分桶沿用 analysis_economy.BUCKETS 边界，并带 Wilson 区间。"""
    facts = _facts(tmp_path, _adv_cases())
    report = dl.advantage_report(facts)
    buckets = {item['bucket']: item for item in report['buckets']}
    assert [item['bucket'] for item in report['buckets']] == ['落后', '持平', '小优', '大优']
    assert (buckets['落后']['low'], buckets['落后']['high']) == (-10 ** 9, -500)
    assert (buckets['大优']['low'], buckets['大优']['high']) == (1500, 10 ** 9)
    # leadAt10：4002=-1200 落后、4001=-300 持平、4005=800 小优、4003=1500 大优
    assert buckets['落后']['n'] == 1 and buckets['落后']['wins'] == 0
    assert buckets['落后']['winRate'] == 0.0
    assert buckets['持平']['n'] == 1 and buckets['持平']['winRate'] == 100.0
    assert buckets['小优']['n'] == 1 and buckets['小优']['wins'] == 1
    assert buckets['大优']['n'] == 1 and buckets['大优']['wins'] == 1
    for item in report['buckets']:
        assert item['enough'] is False                 # 每桶 n=1 < 10
        if item['n']:
            assert item['ciLow'] <= item['winRate'] <= item['ciHigh']


def test_advantage_bands(tmp_path):
    """按分钟 0..min(30, ceil(maxDuration/60)) 的 P25/P50/P75；n=0 给 null。"""
    facts = _facts(tmp_path, _adv_cases())
    bands = dl.advantage_report(facts)['bands']
    # 最长局 700 秒 → ceil(700/60)=12 → 13 个分钟档（0..12）
    assert len(bands) == 13
    assert [band['minute'] for band in bands] == list(range(13))
    minute0 = bands[0]
    assert minute0['win']['n'] == 4
    assert minute0['win']['p50'] == 0.0
    assert minute0['win']['p75'] == 25.0
    # 第 9 分钟：480 秒的局已结束，不计入该档；600 秒的局仍在
    minute9 = bands[9]
    assert minute9['seconds'] == 540.0
    assert minute9['win']['n'] == 3
    assert minute9['win']['p25'] == 440.0
    assert minute9['win']['p50'] == 680.0
    assert minute9['win']['p75'] == 1140.0
    assert minute9['loss']['n'] == 1
    assert minute9['all']['n'] == 4
    # 第 11 分钟只剩 700 秒那局
    minute11 = bands[11]
    assert minute11['win']['n'] == 1
    assert minute11['win']['p50'] == 920.0
    # 第 12 分钟所有局都结束了：n=0，分位全部 null（页面不画线）
    minute12 = bands[12]
    assert minute12['all']['n'] == 0
    assert minute12['win'] == {'n': 0, 'p25': None, 'p50': None, 'p75': None}
    assert minute12['loss']['p50'] is None
    assert minute12['all']['p75'] is None


def test_advantage_paths(tmp_path):
    """领先 ≥1000 后的简化路径计数；n<3 返回但标 enough=false。"""
    diff = [0, 200, 1200, 1500, 1800, 2000, 1800, 1500, 1200, 1000, 800]
    resource = _event(300, dt_type='1', dt_id='9', killer_camp='1')
    cases = [{'seq': f'500{index}', 'own_win': True, 'diff': diff,
              'events': [resource]} for index in range(3)]
    cases.append({'seq': '5010', 'own_win': False,
                  'diff': [0, 300, 1100, 1500, 1600, 1500, 1200, 900, 600, 300, -500],
                  'events': []})
    facts = _facts(tmp_path, cases)
    report = dl.advantage_report(facts)
    paths = {path['key']: path for path in report['paths']}
    # 3 局同为「领先 → 拿暴君 → 未推塔 → 胜」
    resource_path = paths['resource|0|win']
    assert resource_path['n'] == 3
    assert resource_path['enough'] is True
    assert resource_path['nextKind'] == 'resource'
    assert resource_path['nextName'] == '暴君'
    assert resource_path['tower'] is False
    assert resource_path['sequence'] == ['下一事件：暴君', '未推塔', '最终胜']
    assert [item['game'] for item in resource_path['games']] == ['5000', '5001', '5002']
    # 只有 1 局的路径仍然返回，但 n<3 → enough=false
    lonely = paths['none|0|loss']
    assert lonely['n'] == 1 and lonely['enough'] is False
    assert lonely['sequence'] == ['下一事件：无我方资源/建筑', '未推塔', '最终负']


def test_advantage_red_perspective(tmp_path):
    """红方视角：蓝方经济领先要翻成我方 ownDiff 为负，领先/回撤/分桶同步翻转。"""
    facts = _facts(tmp_path, [
        {'seq': '7001', 'own_camp': '2', 'own_win': False,
         'diff': _step_diff(1500), 'events': [], 'fights': [], 'deaths': []},
    ])
    game = facts['games']['7001']
    assert game['ownCamp'] == 'red'
    assert game['diff'][-1] == 1500 and game['ownDiff'][-1] == -1500
    report = dl.loss_report(facts)
    assert report['rows']                      # 负向窗口由翻转后的 ownDiff 得到
    assert {row['delta'] for row in report['rows']} == {-1500}
    assert {row['ownCamp'] for row in report['rows']} == {'red'}
    advantage = dl.advantage_report(facts)
    item = advantage['games'][0]
    assert item['ownCamp'] == 'red'
    assert item['maxLead'] == 0
    assert item['drawdown'] == 1500
    assert item['leadAt10'] == -1500 and item['leadAt10Bucket'] == '落后'
    assert item['comeback'] is False            # 从未领先 ≥1000
    assert advantage['paths'] == []             # 没有首次领先 → 无路径


def test_advantage_empty_and_missing_economy(tmp_path):
    """空事实表 / 无经济序列：available=false + reason，各列表为空。"""
    empty_facts = load_fixture_facts(tmp_path / 'empty')
    empty = dl.advantage_report(empty_facts)
    assert empty['available'] is False
    assert empty['games'] == [] and empty['bands'] == [] and empty['paths'] == []
    assert empty['buckets'] == []
    assert '没有可用对局' in empty['reason']

    no_economy = _facts(tmp_path / 'no-economy', [
        {'seq': '9001', 'diff': [], 'own_win': True},
    ])
    report = dl.advantage_report(no_economy)
    assert report['available'] is False
    assert '经济序列' in report['reason']
    assert report['coverage']['skippedGames'] == 1


def test_advantage_output_contract(tmp_path):
    """advantage 顶层字段与 games 明细字段对齐契约 2.2。"""
    facts = _facts(tmp_path, _adv_cases())
    report = dl.advantage_report(facts)
    assert {'available', 'filters', 'summary', 'buckets', 'bands', 'games',
            'paths', 'coverage', 'note', 'reason'} <= set(report)
    required = {'game', 'label', 'opponentName', 'result', 'ownCamp', 'duration',
                'maxLead', 'maxLeadAt', 'drawdown', 'drawdownAt',
                'leadDurationSec', 'conversionSec', 'postLead2mDelta',
                'comeback', 'leadAt10', 'leadAt10Bucket', 'candidates'}
    for item in report['games']:
        assert required <= set(item)
        assert item['approx'] is True
        assert isinstance(item['candidates'], list)
        assert len(item['candidates']) <= dl.MAX_GAME_CANDIDATES
    # note 说明近似采样与小样本口径
    assert '近似' in report['note']
    assert '不证明因果' in report['note']
    # JSON 可序列化（API 直接返回）
    json.dumps(report, ensure_ascii=False)
    json.dumps(dl.loss_report(facts), ensure_ascii=False)
