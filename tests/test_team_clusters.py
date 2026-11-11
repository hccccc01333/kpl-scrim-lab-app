"""对手战队聚类：签名、建议合并、命名与合并覆盖层。"""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import team_clusters  # noqa: E402
from workspace_store import Workspace  # noqa: E402


def panel(seq, players, start, win=True, heroes=None, own_camp=1):
    heroes = heroes or ['瑶'] * 5
    names = [f'队员{i}' for i in range(5)]
    enemy_camp = 2 if own_camp == 1 else 1
    stats = {'killCnt': 3, 'deadCnt': 2, 'assistCnt': 5, 'money': 7200,
             'totalHurtCnt': 24000, 'totalBehurtCnt': 18000, 'ctrlTime': 120,
             'healCnt': 800, 'joinGamePercent': 0.6, 'towerCnt': 1, 'gradeGame': 8.5}
    roles = [{'basicInfo': {'playerId': pid, 'roleName': names[i], 'acntCamp': enemy_camp},
              'battleRecords': {'usedHero': {'heroName': heroes[i]}, 'position': i},
              'battleStats': dict(stats)} for i, pid in enumerate(players)]
    own = [{'basicInfo': {'playerId': f'own{i}', 'roleName': f'我方{i}', 'acntCamp': own_camp},
            'battleRecords': {'usedHero': {'heroName': '吕布'}, 'position': i},
            'battleStats': dict(stats)} for i in range(5)]
    blue, red = (own, roles) if own_camp == 1 else (roles, own)
    return {'data': {'head': {'acntCamp': own_camp, 'gameResult': win},
                     'battle': {'startTime': start, 'usedTime': 900, 'mapName': '排位赛'},
                     'blueRoles': blue, 'redRoles': red}}


A = ['a1', 'a2', 'a3', 'a4', 'a5']
B = ['b1', 'b2', 'b3', 'b4', 'b5']


def write_panels(directory, items):
    directory.mkdir(parents=True, exist_ok=True)
    for seq, payload in items:
        (directory / f'{seq}.json').write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')


def test_clean_name_strips_zero_width():
    assert team_clusters.clean_name('信则\u2060\u2061有\u2062 ') == '信则有'
    assert team_clusters.clean_name(None) == ''


def test_same_roster_is_one_cluster_and_overlap_is_suggested(tmp_path):
    items = [
        ('1', panel(1, A, '11-02 12:00')),
        ('2', panel(2, A, '11-02 13:00', win=False)),
        ('3', panel(3, ['a1', 'a2', 'a3', 'a4', 'sub'], '11-02 14:00')),
    ]
    write_panels(tmp_path / 'camp_details', items)
    result = team_clusters.list_teams(tmp_path / 'camp_details', tmp_path / 'db.sqlite3', '本队')

    assert result['summary']['teams'] == 2
    first = result['teams'][0]
    assert first['matches'] == 2 and first['wins'] == 1 and first['losses'] == 1
    assert first['number'] == 1
    # 4/5 重合只给建议，不自动合并
    assert len(result['suggestions']) == 1
    assert result['suggestions'][0]['overlap'] == 4


def test_rename_and_merge_stay_consistent_with_workspace(tmp_path):
    write_panels(tmp_path / 'camp_details', [
        ('1', panel(1, A, '11-02 12:00')),
        ('2', panel(2, ['a1', 'a2', 'a3', 'a4', 'sub'], '11-02 14:00')),
    ])
    db = tmp_path / 'db.sqlite3'
    result = team_clusters.list_teams(tmp_path / 'camp_details', db, '本队')
    assert [team['displayName'] for team in result['teams']] == ['待命名战队 #1', '待命名战队 #2']

    team_clusters.rename_team(db, result['teams'][0]['id'], '青岚', '张教练')
    renamed = team_clusters.list_teams(tmp_path / 'camp_details', db, '本队')
    assert renamed['teams'][0]['displayName'] == '青岚'
    assert renamed['teams'][0]['coach'] == '张教练'
    assert renamed['teams'][0]['named'] is True
    assert renamed['summary']['pending'] == 1
    workspace = Workspace(db)
    synced = next(team for team in workspace.list_teams() if team['id'] == result['teams'][0]['id'])
    assert synced['name'] == '青岚' and synced['coach'] == '张教练'

    team_clusters.merge_team(db, result['teams'][1]['id'], result['teams'][0]['id'])
    merged = team_clusters.list_teams(tmp_path / 'camp_details', db, '本队')
    assert merged['summary']['teams'] == 1
    assert merged['teams'][0]['matches'] == 2
    assert merged['suggestions'] == []
    # 原始面板一个字节都没动
    assert len(list((tmp_path / 'camp_details').glob('*.json'))) == 2


def test_rename_many_writes_workspace_and_is_all_or_nothing(tmp_path):
    db = tmp_path / 'db.sqlite3'
    workspace = Workspace(db).ensure_schema()
    workspace.upsert_team('cluster-a', name='待命名战队 #1')
    workspace.upsert_team('cluster-b', name='待命名战队 #2')
    result = team_clusters.rename_many(db, [
        {'id': 'cluster-a', 'name': '青岚', 'coach': '张教练'},
        {'id': 'cluster-b', 'name': '白虎'},
    ])
    assert result['updated'] == 2
    names = {team['id']: team['name'] for team in workspace.list_teams()}
    assert names == {'cluster-a': '青岚', 'cluster-b': '白虎'}
    overrides = team_clusters.load_overrides(db)
    assert overrides['cluster-a']['name'] == '青岚'
    with pytest.raises(ValueError):
        team_clusters.rename_many(db, [
            {'id': 'cluster-a', 'name': '朱雀'},
            {'id': 'cluster-b', 'name': '青岚'},
        ])
    names = {team['id']: team['name'] for team in workspace.list_teams()}
    assert names == {'cluster-a': '青岚', 'cluster-b': '白虎'}


def test_reconcile_moves_override_name_into_workspace(tmp_path):
    db = tmp_path / 'db.sqlite3'
    team_clusters.save_override(db, 'cluster-1', {'name': '青岚', 'coach': '张教练'})
    report = team_clusters.reconcile_workspace(db)
    assert report['count'] >= 1
    workspace = Workspace(db)
    team = next(team for team in workspace.list_teams() if team['id'] == 'cluster-1')
    assert team['name'] == '青岚' and team['coach'] == '张教练'
    # 反向：工作区改名后，再对账把覆盖层补齐
    workspace.upsert_team('cluster-1', name='青岚战队')
    team_clusters.reconcile_workspace(db)
    overrides = team_clusters.load_overrides(db)
    assert overrides['cluster-1']['name'] == '青岚战队'


def test_numbering_follows_first_seen(tmp_path):
    write_panels(tmp_path / 'camp_details', [
        ('1', panel(1, B, '11-03 12:00')),
        ('2', panel(2, A, '11-02 12:00')),
    ])
    result = team_clusters.list_teams(tmp_path / 'camp_details', tmp_path / 'db.sqlite3', '本队')
    assert [team['firstSeen'] for team in result['teams']] == ['11-02 12:00', '11-03 12:00']
    assert [team['number'] for team in result['teams']] == [1, 2]


def test_missing_panels_is_reported_not_faked(tmp_path):
    result = team_clusters.list_teams(tmp_path / 'empty', tmp_path / 'db.sqlite3', '本队')
    assert result['teams'] == []
    assert result['summary']['teams'] == 0
    assert result['warnings']


def test_compare_aligns_lanes_and_skips_missing_fields(tmp_path):
    write_panels(tmp_path / 'camp_details', [
        ('1', panel(1, A, '11-02 12:00')),
        ('2', panel(2, A, '11-02 13:00')),
    ])
    result = team_clusters.compare(tmp_path / 'camp_details')
    assert result['games'] == 2
    lanes = [row['lane'] for row in result['lanes']]
    assert lanes == ['对抗路', '中路', '发育路', '打野', '游走']
    for row in result['lanes']:
        assert row['own'] and row['enemy']
        # 分路两侧都有人，且不是同一个 ID
        assert row['own']['id'] != row['enemy']['id']
    # 面板里的对方 5 人聚成 5 个选手记录
    assert len(result['players']['enemy']) == 5
    # 每个选手的名次字段是均值，不是累计
    assert result['players']['enemy'][0]['games'] == 2


def test_compare_filters_by_team(tmp_path):
    write_panels(tmp_path / 'camp_details', [
        ('1', panel(1, A, '11-02 12:00')),
        ('2', panel(2, B, '11-02 13:00')),
    ])
    first = team_clusters.build(team_clusters.load_panels(tmp_path / 'camp_details'))['clusters'][0]
    scoped = team_clusters.compare(tmp_path / 'camp_details', first['id'])
    assert scoped['games'] == 1
    assert len(scoped['players']['enemy']) == 5
    assert scoped['teamId'] == first['id']


def test_combos_marks_small_samples_and_computes_synergy(tmp_path):
    heroes = ['瑶', '吕布', '马可波罗', '小乔', '张飞']
    write_panels(tmp_path / 'camp_details', [
        ('1', panel(1, A, '11-02 12:00', win=True, heroes=heroes)),
        ('2', panel(2, A, '11-02 13:00', win=True, heroes=heroes)),
        ('3', panel(3, A, '11-02 14:00', win=False, heroes=heroes)),
    ])
    result = team_clusters.combos(tmp_path / 'camp_details', min_games=3)
    enemy = result['enemy']['combos']
    # 固定五人阵容 → C(5,2)=10 组，每组 3 局
    assert len(enemy) == 10
    assert all(row['games'] == 3 and not row['small'] for row in enemy)
    # 全员同胜同负时，组合胜率与单独期望相同，协同为 0
    assert all(abs(row['synergy']) < 0.01 for row in enemy)

    one = team_clusters.combos(tmp_path / 'camp_details', min_games=99)
    assert all(row['small'] for row in one['enemy']['combos'])


def test_hero_pool_depth_uses_inverse_hhi(tmp_path):
    heroes = ['瑶', '吕布', '马可波罗', '小乔', '张飞']
    write_panels(tmp_path / 'camp_details', [
        ('1', panel(1, A, '11-02 12:00', heroes=heroes)),
        ('2', panel(2, A, '11-02 13:00', heroes=heroes)),
    ])
    depth = team_clusters.hero_pool_depth(tmp_path / 'camp_details')['enemy']
    assert depth['heroes'] == 5 and depth['picks'] == 10
    # 五人平分 → HHI = 5 × 0.2² = 0.2 → 有效英雄数 5
    assert depth['effective'] == 5.0


def test_partners_only_returns_pairs_with_the_hero(tmp_path):
    heroes = ['瑶', '吕布', '马可波罗', '小乔', '张飞']
    write_panels(tmp_path / 'camp_details', [
        ('1', panel(1, A, '11-02 12:00', win=True, heroes=heroes)),
        ('2', panel(2, A, '11-02 13:00', win=True, heroes=heroes)),
        ('3', panel(3, A, '11-02 14:00', win=False, heroes=heroes)),
    ])
    result = team_clusters.partners(tmp_path / 'camp_details', '马可波罗', side='enemy', min_games=3)
    assert result['pairs'] == 4          # 五指阵容里，马可波罗有 4 个搭档
    assert len(result['partners']) == 4
    assert all(row['partner'] != '马可波罗' for row in result['partners'])
    assert {row['partner'] for row in result['partners']} == {'瑶', '吕布', '小乔', '张飞'}

    missing = team_clusters.partners(tmp_path / 'camp_details', '不存在的英雄', side='enemy', min_games=1)
    assert missing['pairs'] == 0 and missing['partners'] == []


def test_trio_combos_need_more_games(tmp_path):
    heroes = ['瑶', '吕布', '马可波罗', '小乔', '张飞']
    write_panels(tmp_path / 'camp_details', [
        ('1', panel(1, A, '11-02 12:00', heroes=heroes)),
        ('2', panel(2, A, '11-02 13:00', heroes=heroes)),
        ('3', panel(3, A, '11-02 14:00', heroes=heroes)),
    ])
    panels = team_clusters.load_panels(tmp_path / 'camp_details')
    trios = team_clusters._combos_from(panels, min_games=5, limit=None, size=3)
    # C(5,3)=10 组，每组 3 局，低于 5 局门槛 → 全部标记样本偏少
    assert trios['enemy']['pairs'] == 10
    assert all(row['small'] for row in trios['enemy']['combos'])
    assert all(len(row['heroes']) == 3 for row in trios['enemy']['combos'])

# ---------------------------------------------------------------- 阵容 / 风格 / 训练台账
def test_roster_reports_lineups_stability_and_lanes(tmp_path):
    write_panels(tmp_path / 'camp_details', [
        ('1', panel(1, A, '11-02 12:00')),
        ('2', panel(2, A, '11-02 13:00', win=False)),
    ])
    result = team_clusters.list_teams(tmp_path / 'camp_details', tmp_path / 'db.sqlite3', '本队')
    roster = result['teams'][0]['roster']

    assert roster['games'] == 2
    assert roster['players'] == 5
    assert len(roster['lineups']) == 1          # 五人组相同 → 一套
    assert roster['lineups'][0]['games'] == 2
    assert roster['stability'] == 100
    assert roster['rotation'] == 0
    assert roster['anomalies'] == []
    lanes = {row['lane']: row['players'] for row in roster['lanes']}
    assert len(lanes) == 5
    assert all(len(players) == 1 for players in lanes.values())
    assert lanes['对抗路'][0]['kda'] == 4.0     # (3+5)/2


def test_roster_flags_duplicate_lane_without_calling_it_rotation(tmp_path):
    duplicate = panel(1, A, '11-02 12:00')
    roles = duplicate['data']['redRoles']
    roles[0]['battleRecords']['position'] = 1   # 两人都在中路，没人游走
    write_panels(tmp_path / 'camp_details', [('1', duplicate)])
    result = team_clusters.list_teams(tmp_path / 'camp_details', tmp_path / 'db.sqlite3', '本队')
    roster = result['teams'][0]['roster']

    assert roster['anomalies'] == ['中路']
    assert roster['rotation'] == 0
    assert roster['lineups'][0]['games'] == 1


def test_team_metrics_expose_style_inputs(tmp_path):
    write_panels(tmp_path / 'camp_details', [
        ('1', panel(1, A, '11-02 12:00')),
        ('2', panel(2, B, '11-02 13:00', win=False)),
    ])
    result = team_clusters.list_teams(tmp_path / 'camp_details', tmp_path / 'db.sqlite3', '本队')
    metrics = result['teams'][0]['metrics']

    for key in ('duration', 'killsPerMin', 'assistsPerMin', 'controlPerMin', 'participation', 'conversion'):
        assert key in metrics and metrics[key] is not None
    assert metrics['duration'] == 900
    assert metrics['participation'] == 60.0     # joinGamePercent 0.6
    # 新指标同样进分位池，风格页据此换算
    assert 'killsPerMin' in result['teams'][0]['percentiles']


def test_team_training_merges_plans_and_camp_days(tmp_path):
    write_panels(tmp_path / 'camp_details', [
        ('1', panel(1, A, '11-02 12:00')),
        ('2', panel(2, A, '11-03 12:00', win=False)),
    ])
    result = team_clusters.list_teams(tmp_path / 'camp_details', tmp_path / 'db.sqlite3', '本队')
    team_id = result['teams'][0]['id']
    schedules = [{
        'id': 'sch-1', 'date': '2026-11-02', 'start_time': '12:00', 'opponent_team_id': team_id,
        'session': '周中训练', 'format': 'BO3', 'status': 'completed',
        'goals': json.dumps([{'label': '前 10 分钟领先', 'target': '+1000', 'status': 'achieved'},
                             '控龙率'], ensure_ascii=False),
        'review_status': 'done', 'review': '执行到位',
    }]

    ledger = team_clusters.team_training(
        tmp_path / 'camp_details', tmp_path / 'db.sqlite3', schedules)
    team = ledger['teams'][0]

    assert ledger['summary']['plans'] == 1
    assert ledger['summary']['goals'] == 2
    assert team['planCount'] == 1 and team['reviewed'] == 1
    plan = next(item for item in team['sessions'] if item['source'] == 'plan')
    assert plan['date'] == '2026-11-02'
    assert plan['goals'][0]['status'] == 'achieved'
    assert plan['goals'][1] == {'label': '控龙率', 'target': '', 'status': 'pending'}
    assert plan['matches'] == 1 and plan['wins'] == 1
    # 没有计划的交手日单独归集，不伪造目标
    camp = [item for item in team['sessions'] if item['source'] == 'camp']
    assert len(camp) == 1 and camp[0]['date'] == '11-03'
    assert camp[0]['goals'] == [] and camp[0]['losses'] == 1


def test_team_training_keeps_unassigned_plans(tmp_path):
    write_panels(tmp_path / 'camp_details', [('1', panel(1, A, '11-02 12:00'))])
    ledger = team_clusters.team_training(
        tmp_path / 'camp_details', tmp_path / 'db.sqlite3',
        [{'id': 'sch-9', 'date': '2026-11-05', 'opponent_team_id': '', 'status': 'planned',
          'goals': '[]'}])
    assert ledger['summary']['unassigned'] == 1
    assert ledger['unassigned'][0]['id'] == 'sch-9'
    assert ledger['teams'][0]['planCount'] == 0
