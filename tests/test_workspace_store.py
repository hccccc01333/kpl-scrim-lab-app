"""工作区数据模型：建表、战队/选手/约训/训练 CRUD、变更日志。"""
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from workspace_store import Workspace  # noqa: E402


@pytest.fixture()
def ws(tmp_path):
    store = Workspace(tmp_path / 'ws.sqlite3')
    store.ensure_schema()
    return store


def test_schema_is_idempotent(tmp_path):
    store = Workspace(tmp_path / 'ws.sqlite3')
    store.ensure_schema()
    store.ensure_schema()
    connection = sqlite3.connect(str(tmp_path / 'ws.sqlite3'))
    try:
        names = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        connection.close()
    for table in ('teams', 'players', 'schedules', 'competitions', 'matches', 'match_rosters', 'bp',
                  'training', 'provenance', 'change_log'):
        assert table in names


def test_team_create_and_rename(ws):
    team_id = ws.upsert_team(name='青岚', coach='张教练', league='KPL')
    teams = ws.list_teams()
    assert len(teams) == 1
    assert teams[0]['name'] == '青岚' and teams[0]['coach'] == '张教练'

    ws.upsert_team(team_id, name='青岚战队')
    assert ws.list_teams()[0]['name'] == '青岚战队'
    log = ws.change_log('team', team_id)
    assert any(item['field'] == 'name' and item['new_value'] == '青岚战队' for item in log)


def test_team_name_required(ws):
    with pytest.raises(ValueError):
        ws.upsert_team(name='  ')


def test_players_belong_to_team_and_alias(ws):
    team_id = ws.upsert_team(name='白虎')
    player_id = ws.upsert_player(team_id=team_id, name='白虎·刀', position='对抗路')
    assert ws.list_players(team_id)[0]['name'] == '白虎·刀'

    assert ws.alias_player(player_id, '小刀') is True
    assert ws.alias_player(player_id, '小刀') is False
    assert ws.list_players(team_id)[0]['aliases'] == ['小刀']


def test_merge_moves_players_and_archives_source(ws):
    target = ws.upsert_team(name='青岚')
    source = ws.upsert_team(name='待命名战队 #3')
    ws.upsert_player(team_id=source, name='队员甲')

    ws.merge_teams(source, target)

    assert [player['team_id'] for player in ws.list_players()] == [target]
    active = {team['name'] for team in ws.list_teams()}
    assert '青岚' in active and '待命名战队 #3' not in active
    assert any(team['name'] == '待命名战队 #3' for team in ws.list_teams(include_archived=True))


def test_schedule_and_training_roundtrip(ws):
    team_id = ws.upsert_team(name='赤霄')
    schedule_id = ws.save_schedule(date='2026-11-08', start_time='19:00', opponent_team_id=team_id,
                                    format='BO3', rules='全局BP', version='B')
    schedules = ws.list_schedules()
    assert schedules[0]['id'] == schedule_id and schedules[0]['opponent_team_id'] == team_id

    ws.save_schedule(schedule_id, date='2026-11-09', opponent_team_id=team_id)
    assert ws.list_schedules()[0]['date'] == '2026-11-09'

    training_id = ws.save_training(goal='提升十分钟经济差', intervention='对线专项',
                                   start_date='2026-11-01', metric='goldDiff10', target=500,
                                   player_ids=['player-a'])
    assert ws.list_training()[0]['session_id'] == training_id


def test_competition_aggregates_schedules_and_matches(ws):
    """比赛是赛训中心：训练计划挂到比赛下，详情聚合训练课与对局。"""
    foe = ws.upsert_team(name='青岚')
    competition_id = ws.save_competition(
        name='KPL 2026 春季赛', date='2026-11-15', opponent_team_id=foe,
        stage='常规赛第 1 轮', format='BO7', owner='张教练')
    competition = ws.get_competition(competition_id)
    assert competition['name'] == 'KPL 2026 春季赛' and competition['owner'] == '张教练'

    schedule_id = ws.save_schedule(date='2026-11-08', opponent_team_id=foe,
                                   session='赛前冲刺', competition_id=competition_id)
    ws.upsert_match('comp-match-1', date='2026-11-08', session='赛前冲刺',
                    enemy_team_id=foe, own_side='blue', winner='blue', duration=900)
    listed = ws.list_competitions()
    assert listed[0]['session_count'] == 1

    detail = ws.competition_detail(competition_id)
    assert detail['competition']['id'] == competition_id
    assert [row['id'] for row in detail['schedules']] == [schedule_id]
    assert [row['match_key'] for row in detail['matches']] == ['comp-match-1']
    assert ws.competition_detail('missing') is None

    # 取消关联后，比赛列表与详情都不再包含这条训练计划
    ws.save_schedule(schedule_id, date='2026-11-08', opponent_team_id=foe,
                     session='赛前冲刺', competition_id=None)
    assert ws.list_competitions()[0]['session_count'] == 0
    assert ws.competition_detail(competition_id)['schedules'] == []


def test_missing_fields_stay_null(ws):
    team_id = ws.upsert_team(name='苍梧')
    assert ws.list_teams()[0]['coach'] is None
    assert ws.list_players(team_id) == []


def test_match_upsert_keeps_manual_fields(ws):
    team = ws.upsert_team(name='青岚')
    ws.upsert_match('camp:1', date='2026-11-02', own_side='blue', winner='blue',
                    status='confirmed', reviewer='张教练', source='bundle')
    # 第二次只带营地字段，不应清掉人工填的 reviewer / notes
    ws.upsert_match('camp:1', date='2026-11-02', own_side='blue', winner='red', notes='复盘')
    row = ws.list_matches()[0]
    assert row['reviewer'] == '张教练'
    assert row['notes'] == '复盘'
    assert row['winner'] == 'red'
    assert ws.list_matches()[0]['enemy_team_id'] is None


def test_migrate_roster_creates_teams_and_skips_duplicates(ws):
    ws.upsert_team('team-own', name='本队')
    roster = [
        {'id': 'p-old-1', 'name': '甲', 'team': '本队', 'position': '对抗路', 'campUserId': ''},
        {'id': 'p-old-2', 'name': '乙', 'team': '对手队', 'position': '打野', 'campUserId': '9001'},
        {'id': 'p-old-3', 'name': '乙', 'team': '对手队', 'position': '打野', 'campUserId': '9001'},
        {'id': 'p-old-4', 'name': '丙', 'team': '本队', 'archived': True},
    ]
    report = ws.migrate_roster(roster, own_team_name='本队')
    assert report['found'] == 4
    assert report['imported'] == 2
    assert report['skipped'] == 2
    assert report['teamsCreated'] == 1
    players = ws.list_players()
    assert {p['id'] for p in players} == {'p-old-1', 'p-old-2'}
    assert any(team['name'] == '对手队' for team in ws.list_teams())
    # 再跑一次不会重复写入
    again = ws.migrate_roster(roster, own_team_name='本队')
    assert again['imported'] == 0
    assert len(ws.list_players()) == 2


def test_migrate_roster_renames_player_placeholders(ws):
    ws.upsert_team('team-own', name='本队')
    roster = [
        {'id': 'p-new-1', 'name': '新选手', 'team': '本队', 'position': '中路'},
        {'id': 'p-new-2', 'name': '新选手', 'team': '本队', 'position': '打野'},
        {'id': 'p-new-3', 'name': '待命名选手 #9', 'team': '本队', 'position': '游走'},
    ]
    report = ws.migrate_roster(roster, own_team_name='本队')
    assert report['imported'] == 3
    assert report['placeholders'] == 3
    names = {player['id']: player['name'] for player in ws.list_players()}
    assert names == {
        'p-new-1': '待命名选手 #1',
        'p-new-2': '待命名选手 #2',
        'p-new-3': '待命名选手 #3',
    }
    assert report['renamed']['p-new-1'] == '待命名选手 #1'
    # 与战队占位名严格分开
    assert all(not name.startswith('待命名战队') for name in names.values())


def test_inbox_and_opponent_alias(ws):
    team_id = ws.upsert_team(name='青岚')
    ws.upsert_match('old-opponent-match', date='2026-11-02', enemy_team_id='old-opponent-id')
    inbox = ws.inbox()
    assert any(group['key'] == 'unmapped' and group['count'] == 1 for group in inbox['groups'])
    assert ws.unmapped_opponents()[0]['oldId'] == 'old-opponent-id'
    mapped = ws.map_opponent('old-opponent-id', team_id)
    assert mapped['updated'] == 1
    row = ws.list_matches()[0]
    assert row['enemy_team_id'] == team_id
    assert ws.inbox()['total'] >= 0


def test_session_manual_match_links(ws):
    ws.upsert_match('link-a', date='2026-11-02', session='验证数据')
    ws.upsert_match('link-b', date='2026-11-02', session='验证数据')
    schedule_id = ws.save_schedule(date='2026-11-02', session='验证数据')
    auto = ws.session_matches(ws.get_schedule(schedule_id))
    assert {row['match_key'] for row in auto['matches']} == {'link-a', 'link-b'}
    ws.save_session_links(schedule_id, ['link-b'])
    manual = ws.session_matches(ws.get_schedule(schedule_id))
    assert manual['reason'] == 'manual'
    assert [row['match_key'] for row in manual['matches']] == ['link-b']
    ws.save_session_links(schedule_id, [])
    restored = ws.session_matches(ws.get_schedule(schedule_id))
    assert restored['reason'] == 'date_session'
    assert {row['match_key'] for row in restored['matches']} == {'link-a', 'link-b'}


def test_session_matches_and_review_roundtrip(ws):
    ws.upsert_match('session-match-1', date='2026-11-02', session='验证数据',
                    enemy_team_id='team-x', winner='blue')
    schedule_id = ws.save_schedule(date='2026-11-02', session='验证数据', format='BO3')
    schedule = ws.get_schedule(schedule_id)
    linked = ws.session_matches(schedule)
    assert linked['reason'] == 'date_session'
    assert [row['match_key'] for row in linked['matches']] == ['session-match-1']

    saved = ws.save_session_review(
        schedule_id, goals=['前 10 分钟经济领先'], review='前期节奏不错',
        review_status='done', attendance=[])
    assert saved['review_status'] == 'done'
    assert saved['status'] == 'completed'
    assert saved['goals'] == '["前 10 分钟经济领先"]'
    assert saved['review'] == '前期节奏不错'


def test_confirm_prefills_is_atomic(ws):
    ws.upsert_match('camp:atomic', date='2026-11-02')
    ws.add_prefill('camp:atomic', 'version', None)
    ws.add_prefill('camp:atomic', 'rules', None)
    with pytest.raises(ValueError):
        ws.confirm_prefills([
            {'matchKey': 'camp:atomic', 'field': 'version', 'value': 'S40'},
            {'matchKey': 'missing', 'field': 'rules', 'value': 'KPL'},
        ])
    row = ws.list_matches()[0]
    assert row['version'] is None
    assert len(ws.list_prefill('camp:atomic')) == 2

    confirmed = ws.confirm_prefills([
        {'matchKey': 'camp:atomic', 'field': 'version', 'value': 'S40'},
        {'matchKey': 'camp:atomic', 'field': 'rules', 'value': 'KPL'},
    ])
    assert len(confirmed) == 2
    row = ws.list_matches()[0]
    assert row['version'] == 'S40' and row['rules'] == 'KPL'
    assert ws.list_prefill('camp:atomic') == []
    with sqlite3.connect(str(ws.db_path)) as connection:
        assert connection.execute(
            'SELECT COUNT(*) FROM provenance WHERE match_key=?', ('camp:atomic',)).fetchone()[0] == 2


def test_rosters_and_bp_replaced(ws):
    ws.upsert_match('camp:2', date='2026-11-03')
    ws.upsert_rosters('camp:2', [
        {'teamId': 't1', 'playerId': 'p1', 'side': 'blue', 'slot': 1, 'hero': '瑶'},
        {'teamId': 't1', 'playerId': 'p2', 'side': 'blue', 'slot': 2, 'hero': '吕布'},
    ])
    ws.upsert_bp('camp:2', bans={'blue': ['瑶']}, picks={'blue': ['吕布']})
    connection = sqlite3.connect(str(ws.db_path))
    try:
        assert connection.execute('select count(*) from match_rosters where match_key=?',
                                  ('camp:2',)).fetchone()[0] == 2
        assert connection.execute('select count(*) from bp where match_key=?',
                                  ('camp:2',)).fetchone()[0] == 1
    finally:
        connection.close()
