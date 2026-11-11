"""团战执行（decision_fights）测试：我方视角、到位差、人数差、热力格、团灭、缺失参与者。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TESTS = Path(__file__).resolve().parent
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

import decision_facts  # noqa: E402
import decision_fights  # noqa: E402
import decision_fixtures as fx  # noqa: E402


# ---------------------------------------------------------------------------
# 造数工具
# ---------------------------------------------------------------------------
def fight(fid, start=300.0, *, own_times=None, enemy_times=None, own_kills=0, enemy_kills=0,
          own_deaths=None, enemy_deaths=None, kills=None, own_beginner=None):
    own_times = own_times if own_times is not None else [float(start)] * 5
    enemy_times = enemy_times if enemy_times is not None else [float(start) + 1.0] * 5
    own_beginner = own_beginner or {}
    participants = []
    for index, moment in enumerate(own_times):
        participants.append({'objID': f'10{index + 1}', 'camp': '1', 'timeSec': moment,
                             'beginner': 1 if index in own_beginner else 0})
    for index, moment in enumerate(enemy_times):
        participants.append({'objID': f'20{index + 1}', 'camp': '2', 'timeSec': moment,
                             'beginner': 0})

    if kills is None:
        kills = []
        for _ in range(own_kills):
            kills.append({'timeSec': start + 5.0, 'killerCamp': '1', 'killer': '104',
                          'victimCamp': '2', 'victim': '201'})
        for _ in range(enemy_kills):
            kills.append({'timeSec': start + 6.0, 'killerCamp': '2', 'killer': '202',
                          'victimCamp': '1', 'victim': '101'})

    details = []
    for index in range(5):
        deaths = (own_deaths[index] if own_deaths else 0)
        details.append({'fightId': fid, 'objID': f'10{index + 1}', 'camp': '1',
                        'kills': 0, 'deaths': deaths, 'assists': 0, 'hurt': 1000,
                        'taken': 800, 'heal': 0, 'hardCtrl': 50, 'softCtrl': 100,
                        'beginHP': 4000, 'endHP': 2500, 'ultimates': 1})
    for index in range(5):
        deaths = (enemy_deaths[index] if enemy_deaths else 0)
        details.append({'fightId': fid, 'objID': f'20{index + 1}', 'camp': '2',
                        'kills': 0, 'deaths': deaths, 'assists': 0, 'hurt': 900,
                        'taken': 1200, 'heal': 0, 'hardCtrl': 0, 'softCtrl': 80,
                        'beginHP': 4200, 'endHP': 3000, 'ultimates': 0})
    return {
        'fightId': fid, 'startSec': float(start), 'endSec': float(start) + 16.0,
        'participants': participants, 'kills': kills, 'details': details,
    }


def write_game(tmp_path, seq='1001', *, fights=None, own_camp='1', own_win=True, **kwargs):
    fx.write_case(tmp_path, seq, fights=fights,
                  own_camp=own_camp, own_win=own_win, **kwargs)
    return fx.load_fixture_facts(tmp_path)


def retag_enemy(root, seq, tag):
    """改掉某局对面五人的营地 playerId，制造「不同对手」。"""
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
# 默认单局：我方蓝方视角
# ---------------------------------------------------------------------------
def test_default_fight_own_blue_perspective(tmp_path):
    facts = write_game(tmp_path)
    report = decision_fights.fight_report(facts)

    assert report['available'] is True
    assert report['filters']['limit'] == 120
    assert report['coverage']['games'] == 1
    assert report['coverage']['fights'] == 1
    assert report['coverage']['analyzedFights'] == 1
    assert report['coverage']['missingParticipants'] == 0

    summary = report['summary']
    assert summary['fights'] == 1
    assert summary['ownParticipants'] == 5
    assert summary['avgArrivalLagSec'] == 0.8  # 我方 300/300/300/302/302 → 0,0,0,2,2
    assert summary['lateJoins'] == 0
    assert summary['lateJoinRate'] == 0.0
    assert summary['firstArrival'] == {'own': 1, 'enemy': 0, 'tie': 0, 'none': 0}
    assert summary['ownKills'] == 2
    assert summary['enemyKills'] == 1

    row = report['rows'][0]
    assert row['game'] == '1001'
    assert row['fightId'] == 'f1'
    assert row['startSec'] == 300.0
    assert row['duration'] == 16.0
    assert row['phase'] == '发育期'
    assert row['timeLabel'] == '5:00'
    assert row['ownParticipants'] == 5
    assert row['enemyParticipants'] == 5
    assert row['missingParticipants'] == 0
    assert row['arrivalDiff'] == -1.0          # 我方最早 300 − 敌方最早 301，负=先到
    assert row['advStart'] == 0                # 3 秒内双方各到 5 人
    assert row['ownKills'] == 2
    assert row['enemyKills'] == 1
    assert row['killDiff'] == 1
    assert row['won'] is True
    assert row['lateJoins'] == 0
    assert row['firstSide'] == 'own'
    assert row['beginnerSide'] == 'own'        # 我方 105 号 participant beginner=1
    assert 'members' not in row               # 成员明细只在 selected 里

    buckets = {item['advStart']: item for item in summary['openingBuckets']}
    assert len(buckets) == 11
    assert list(buckets) == [-5, -4, -3, -2, -1, 0, 1, 2, 3, 4, 5]
    assert buckets[0]['n'] == 1
    assert buckets[0]['wins'] == 1
    assert buckets[0]['winRate'] == 100.0
    assert buckets[0]['enough'] is False
    assert buckets[-5]['n'] == 0
    assert buckets[-5]['winRate'] is None

    assert summary['heat']['max'] == 1
    assert summary['heat']['skippedKillDiff'] == 0
    assert summary['heat']['cells'] == [
        {'x': 0, 'y': 1, 'count': 1, 'ownWins': 1, 'rate': 100.0}]
    assert summary['wipes'] == 0
    assert '5 人全部阵亡' in summary['wipeNote']


def test_selected_members_and_arrival_bars(tmp_path):
    facts = write_game(tmp_path)
    selected = decision_fights.fight_report(facts)['selected']

    assert selected['fightId'] == 'f1'
    assert len(selected['members']) == 10
    members = {member['objId']: member for member in selected['members']}

    first = members['101']
    assert first['camp'] == 'own'
    assert first['campCode'] == '1'
    assert first['player'] == '1-0'
    assert first['hero'] == '关羽'
    assert first['lane'] == '对抗路'
    assert first['arrivalLagSec'] == 0.0
    assert first['joinOrder'] == 1
    assert first['beginner'] == 0
    assert first['kills'] == 0
    assert first['deaths'] == 1
    assert first['assists'] == 1
    assert first['hurt'] == 1200
    assert first['taken'] == 900
    assert first['heal'] == 0
    assert first['hardCtrl'] == 100
    assert first['softCtrl'] == 200
    assert first['beginHP'] == 4000
    assert first['endHP'] == 2500
    assert first['ultimates'] == 1

    beginner = members['105']
    assert beginner['beginner'] == 1
    assert beginner['arrivalLagSec'] == 2.0

    last = members['205']
    assert last['camp'] == 'enemy'
    assert last['player'] == '2-4'
    assert last['hero'] == '张良'
    assert last['arrivalLagSec'] == 3.0
    assert last['joinOrder'] == 10             # 300×3 → 301×4 → 302×2 → 303
    assert last['deaths'] == 0
    assert last['endHP'] == 3000

    bars = selected['arrivalBars']
    assert len(bars) == 10
    own_bar = next(bar for bar in bars if bar['player'] == '1-0')
    assert own_bar == {'player': '1-0', 'hero': '关羽', 'lane': '对抗路',
                       'camp': 'own', 'from': 0, 'to': 0.0}
    enemy_bar = next(bar for bar in bars if bar['player'] == '2-4')
    assert enemy_bar['camp'] == 'enemy'
    assert enemy_bar['from'] == 0
    assert enemy_bar['to'] == 3.0


# ---------------------------------------------------------------------------
# 我方红方视角：符号翻转
# ---------------------------------------------------------------------------
def test_own_red_perspective_flips_arrival_and_kill_diff(tmp_path):
    facts = write_game(tmp_path, own_camp='2', own_win=False, win_camp='2')
    report = decision_fights.fight_report(facts)

    assert report['available'] is True
    row = report['rows'][0]
    assert row['ownCamp'] == 'red'
    assert row['arrivalDiff'] == 1.0            # 我方（红）最早 301，敌方（蓝）最早 300 → 后到
    assert row['advStart'] == 0                 # 双方 3 秒内各到 5 人
    assert row['firstSide'] == 'enemy'
    assert row['ownKills'] == 1
    assert row['enemyKills'] == 2
    assert row['killDiff'] == -1
    assert row['won'] is False
    assert row['beginnerSide'] == 'enemy'       # 蓝方 105 号 beginner=1
    assert report['summary']['firstArrival'] == {'own': 0, 'enemy': 1, 'tie': 0, 'none': 0}
    assert report['summary']['heat']['cells'] == [
        {'x': 0, 'y': -1, 'count': 1, 'ownWins': 0, 'rate': 0.0}]


# ---------------------------------------------------------------------------
# 0 击杀团战：killDiff/won 为 None，不进热力图
# ---------------------------------------------------------------------------
def test_zero_kill_fight_is_not_decided_and_skipped_in_heat(tmp_path):
    facts = write_game(tmp_path, seq='1101', fights=[fight('f1', kills=[])])
    report = decision_fights.fight_report(facts)

    row = report['rows'][0]
    assert row['killDiff'] is None
    assert row['won'] is None
    assert report['summary']['heat'] == {
        'cells': [], 'max': 0, 'skippedKillDiff': 1,
        'xRange': [-5, 5], 'yRange': None,
    }
    bucket = {item['advStart']: item for item in report['summary']['openingBuckets']}[0]
    assert bucket['n'] == 1
    assert bucket['decided'] == 0
    assert bucket['wins'] == 0


# ---------------------------------------------------------------------------
# 热力格 / 分桶 / 迟到率：8 场 advStart=-2 的团战
# ---------------------------------------------------------------------------
def test_heat_buckets_and_late_joins(tmp_path):
    losing_times = dict(own_times=[301, 302, 306, 306, 306],
                        enemy_times=[301, 301, 302, 302, 310])
    winning_times = dict(own_times=[401, 401, 402, 402, 410],
                         enemy_times=[401, 402, 406, 406, 406])
    fights = [fight(f'f{index + 1}', 300.0, own_kills=0, enemy_kills=2, **losing_times)
              for index in range(8)]
    fights.append(fight('f9', 400.0, own_kills=2, enemy_kills=0, **winning_times))
    fights.append(fight('f10', 500.0, own_times=[500] * 5, enemy_times=[500] * 5, kills=[]))

    facts = write_game(tmp_path, seq='1201', fights=fights)
    summary = decision_fights.fight_report(facts)['summary']

    assert summary['fights'] == 10
    buckets = {item['advStart']: item for item in summary['openingBuckets']}
    assert buckets[-2]['n'] == 8
    assert buckets[-2]['wins'] == 0
    assert buckets[-2]['winRate'] == 0.0
    assert buckets[-2]['enough'] is True        # 8 ≥ 8
    assert buckets[2]['n'] == 1
    assert buckets[2]['wins'] == 1
    assert buckets[2]['enough'] is False
    assert buckets[0]['n'] == 1
    assert buckets[0]['decided'] == 0

    heat = summary['heat']
    assert heat['cells'] == [
        {'x': -2, 'y': -2, 'count': 8, 'ownWins': 0, 'rate': 0.0},
        {'x': 2, 'y': 2, 'count': 1, 'ownWins': 1, 'rate': 100.0},
    ]
    assert heat['max'] == 8
    assert heat['skippedKillDiff'] == 1
    assert heat['xRange'] == [-2, 2]
    assert heat['yRange'] == [-2, 2]

    # 迟到率：8 场各 3 人 + f9 的 1 人开始 5 秒后才到 → 25 / 50
    assert summary['lateJoins'] == 25
    assert summary['lateJoinRate'] == 50.0
    assert summary['ownParticipants'] == 50
    # 平均到位延迟：(21×8 + 16 + 0) / 50 = 3.68
    assert summary['avgArrivalLagSec'] == 3.7
    # 行按损失优先：先 8 场 killDiff=-2，最后是 0 击杀的 None
    report = decision_fights.fight_report(facts)
    assert report['rows'][0]['killDiff'] == -2
    assert report['rows'][0]['advStart'] == -2
    assert report['rows'][-1]['killDiff'] is None
    assert all(item['killDiff'] == -2 for item in report['rows'][:8])


# ---------------------------------------------------------------------------
# 缺失参战时间
# ---------------------------------------------------------------------------
def test_missing_participant_time_counted(tmp_path):
    payload = fight('f1', own_times=[300, 300, 300, 302, None],
                    enemy_times=[301, 301, 301, 301, 303], own_kills=2, enemy_kills=1)
    facts = write_game(tmp_path, seq='1301', fights=[payload])
    report = decision_fights.fight_report(facts)

    row = report['rows'][0]
    assert row['ownParticipants'] == 4
    assert row['enemyParticipants'] == 5
    assert row['missingParticipants'] == 1
    assert report['coverage']['missingParticipants'] == 1
    # 缺失的那名成员不出现，但其余 9 人明细完整
    assert len(report['selected']['members']) == 9
    assert '105' not in {member['objId'] for member in report['selected']['members']}


def test_all_participant_times_missing_is_unavailable(tmp_path):
    payload = fight('f1', own_times=[None] * 5, enemy_times=[None] * 5)
    facts = write_game(tmp_path, seq='1302', fights=[payload])
    report = decision_fights.fight_report(facts)

    assert report['available'] is False
    assert '缺少参战时间' in report['reason']
    assert report['coverage']['skippedFights'] == 1
    assert report['rows'] == []
    assert report['selected'] is None


# ---------------------------------------------------------------------------
# 团灭
# ---------------------------------------------------------------------------
def test_wipe_counts_enemy_side(tmp_path):
    payload = fight('f1', 320.0, own_deaths=[0, 0, 0, 0, 0],
                    enemy_deaths=[1, 2, 1, 1, 1], own_kills=0, enemy_kills=0)
    facts = write_game(tmp_path, seq='1401', fights=[payload])
    summary = decision_fights.fight_report(facts)['summary']

    assert summary['wipes'] == 1
    assert summary['wipeSides'] == {'own': 0, 'enemy': 1}
    assert summary['wipeRows'][0]['side'] == 'enemy'
    assert summary['wipeRows'][0]['game'] == '1401'
    assert summary['wipeRows'][0]['t'] == 320.0


# ---------------------------------------------------------------------------
# 过滤：game / result / opponent / 日期
# ---------------------------------------------------------------------------
def test_game_result_and_opponent_filters(tmp_path):
    fx.write_case(tmp_path, '3001')
    fx.write_case(tmp_path, '3002', own_win=False)
    retag_enemy(tmp_path, '3002', 'other')
    facts = fx.load_fixture_facts(tmp_path)

    game_scoped = decision_fights.fight_report(facts, game='3001')
    assert game_scoped['summary']['fights'] == 1
    assert {row['game'] for row in game_scoped['rows']} == {'3001'}

    loss_scoped = decision_fights.fight_report(facts, result='loss')
    assert loss_scoped['summary']['fights'] == 1
    assert {row['game'] for row in loss_scoped['rows']} == {'3002'}
    assert {row['result'] for row in loss_scoped['rows']} == {'loss'}

    win_scoped = decision_fights.fight_report(facts, result='win')
    assert {row['game'] for row in win_scoped['rows']} == {'3001'}

    opponent_id = facts['games']['3002']['opponentId']
    opponent_scoped = decision_fights.fight_report(facts, opponent=opponent_id)
    assert opponent_scoped['summary']['fights'] == 1
    assert {row['game'] for row in opponent_scoped['rows']} == {'3002'}

    empty = decision_fights.fight_report(facts, opponent='no-such-opponent')
    assert empty['available'] is False
    assert empty['rows'] == []

    date_empty = decision_fights.fight_report(facts, date_from='2027-01-01')
    assert date_empty['available'] is False


def test_no_fights_available_false(tmp_path):
    facts = write_game(tmp_path, seq='1501', fights=[])
    report = decision_fights.fight_report(facts)
    assert report['available'] is False
    assert '团战' in report['reason']
    assert report['coverage']['fights'] == 0
    assert report['summary'] is None
    assert report['selected'] is None


def test_empty_dataset_available_false(tmp_path):
    facts = decision_facts.load_facts(tmp_path / 'official_replays',
                                      tmp_path / 'camp_details', tmp_path, None)
    report = decision_fights.fight_report(facts)
    assert report['available'] is False
    assert report['coverage']['games'] == 0


# ---------------------------------------------------------------------------
# selected 指定 fightId / limit / 排序
# ---------------------------------------------------------------------------
def test_selected_by_game_and_fight_reference(tmp_path):
    fights = [
        fight('f1', 300.0, own_kills=3, enemy_kills=0),
        fight('f2', 400.0, own_kills=0, enemy_kills=2),
        fight('f3', 500.0, own_kills=1, enemy_kills=1),
    ]
    facts = write_game(tmp_path, seq='1601', fights=fights)

    default_report = decision_fights.fight_report(facts)
    assert default_report['selected']['fightId'] == 'f2'   # rows[0]：killDiff=-2
    assert default_report['selectedReason'] is None

    picked = decision_fights.fight_report(facts, game='1601::f3')['selected']
    assert picked['fightId'] == 'f3'
    assert picked['killDiff'] == 0
    assert picked['won'] is False

    bad = decision_fights.fight_report(facts, game='1601::nope')
    assert bad['available'] is True
    assert bad['selected'] is None
    assert 'nope' in bad['selectedReason']


def test_rows_sorted_by_loss_then_limit(tmp_path):
    fights = [
        fight('f1', 300.0, own_kills=3, enemy_kills=0),   # killDiff +3
        fight('f2', 400.0, own_kills=0, enemy_kills=2),   # killDiff -2
        fight('f3', 500.0, own_kills=1, enemy_kills=1),   # killDiff 0
    ]
    facts = write_game(tmp_path, seq='1701', fights=fights)
    report = decision_fights.fight_report(facts)

    assert [row['killDiff'] for row in report['rows']] == [-2, 0, 3]
    assert [row['fightId'] for row in report['rows']] == ['f2', 'f3', 'f1']
    assert report['selected']['fightId'] == 'f2'

    limited = decision_fights.fight_report(facts, limit=2)
    assert len(limited['rows']) == 2
    assert limited['filters']['limit'] == 2
    assert limited['coverage']['analyzedFights'] == 3


def test_fight_start_phase_and_clock(tmp_path):
    facts = write_game(tmp_path, seq='1801', fights=[fight('f1', 650.0)])
    row = decision_fights.fight_report(facts)['rows'][0]
    assert row['phase'] == '后期'
    assert row['timeLabel'] == '10:50'
