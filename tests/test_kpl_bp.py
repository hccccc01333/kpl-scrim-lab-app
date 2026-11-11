"""KPL BP 自抓管线的离线单测（不联网）。

覆盖：bp_list 解析 / pick-ban 分流（实测语义 PICK=1）/ 十人面板交叉校验 /
增量去重与原子落盘 / 组合聚合（含胜率、年份、teams、minGames）/ 整阵容 /
manifest 统计 / bp_facts 新字段与老文件兜底。
"""
from __future__ import annotations

import json
import unittest.mock

import pytest

import bp_facts
import kpl_bp

# ---------------------------------------------------------------------------
# 构造夹具
# ---------------------------------------------------------------------------

PICKS_1 = ['关羽', '百里守约', '钟馗', '马超', '公孙离']
PICKS_2 = ['鲁班大师', '盾山', '阿古朵', '橘右京', '夏侯惇']
BANS_1 = ['敖隐', '女娲', '苏烈', '裴擒虎', '达摩']
BANS_2 = ['张飞', '海月', '赵云', '夏洛特', '百里守约']


def make_bp_list(picks, bans, *, interleave=True):
    """拼一个 20 条的 bp_list；`is_ban_or_pick==1` 是选用、`==0` 是禁用（实测语义）。"""
    rows = []
    if interleave:
        # 真实终局结构近似：ban×4 → pick×6 → ban×6 → pick×4
        order = [('1', 0), ('2', 0), ('1', 0), ('2', 0),
                 ('1', 1), ('2', 1), ('1', 1), ('2', 1), ('1', 1), ('2', 1),
                 ('2', 0), ('1', 0), ('2', 0), ('1', 0), ('2', 0), ('1', 0),
                 ('2', 1), ('1', 1), ('2', 1), ('1', 1)]
        cursors = {('1', 0): 0, ('2', 0): 0, ('1', 1): 0, ('2', 1): 0}
        for camp, kind in order:
            source = picks if kind == 1 else bans
            index = cursors[(camp, kind)]
            cursors[(camp, kind)] = index + 1
            hero = source[camp][index % len(source[camp])]
            rows.append({'camp': int(camp), 'is_ban_or_pick': kind,
                         'hero_name': hero, 'hero_id': 1, 'position': 0})
        return rows
    for camp in ('1', '2'):
        rows.extend({'camp': int(camp), 'is_ban_or_pick': 0, 'hero_name': hero}
                    for hero in bans[camp])
    for camp in ('1', '2'):
        rows.extend({'camp': int(camp), 'is_ban_or_pick': 1, 'hero_name': hero}
                    for hero in picks[camp])
    return rows


def battle_payload(picks=None, bans=None, *, win_camp=1, battle_id='111_1_222', seq=1,
                   with_players=True, status=2, bp_list=None, player_heroes=None):
    picks = picks or {'1': PICKS_1, '2': PICKS_2}
    bans = bans or {'1': BANS_1, '2': BANS_2}
    data = {
        'battle_id': battle_id,
        'status': status,
        'win_camp': win_camp,
        'game_duration': 1200000,
        'battle_seq': seq,
        'camp1': {'team_id': '10003', 'team_name': '北京WB', 'team_abbreviation': 'WB'},
        'camp2': {'team_id': '10017', 'team_name': '广州TTG', 'team_abbreviation': 'TTG'},
        'bp_list': list(bp_list) if bp_list is not None else make_bp_list(picks, bans),
    }
    if with_players:
        heroes = player_heroes or picks
        players = []
        for camp in ('1', '2'):
            for index, hero in enumerate(heroes[camp]):
                players.append({'camp': int(camp), 'hero_name': hero,
                                'player_name': f'P{camp}{index}',
                                'position_desc': kpl_bp.LANE_ORDER[index % 5]})
        data['battle_player_list'] = players
    return {'code': 200, 'data': data}


MATCH = {'match_id': '2026100201', 'start_time': '2026-10-02 14:00:00',
         'match_stage_desc': '擂台赛'}
LEAGUE = {'league_id': '20260004', 'league_name': '2026年KPL年度总决赛', 'year': 2026}


def make_match(battle_ids, *, score1=4, score2=3, bo=7, match_id='2026100201',
               start_time='2026-10-02 14:00:00', stage='擂台赛'):
    """赛程行：带 bo / 双方最终大比分 / 小局列表，用于巅峰对决判定。"""
    return {'match_id': match_id, 'start_time': start_time, 'match_stage_desc': stage,
            'bo': bo,
            'camp1': {'team_name': '北京WB', 'score': score1},
            'camp2': {'team_name': '广州TTG', 'score': score2},
            'match_battle_video_list': [{'battle_id': battle_id, 'battle_seq': index + 1}
                                        for index, battle_id in enumerate(battle_ids)]}


def make_game(picks1, picks2, win_camp, *, year=2026, date='2026-10-02',
              team1='队A', team2='队B', battle_id=None, match_id=None,
              league_id='20260004', league_name='2026年KPL年度总决赛', bp_mode=None):
    battle_id = battle_id or f'b-{date}-{team1}-{abs(hash((tuple(picks1), tuple(picks2))))}'
    game = {
        'schema': kpl_bp.SCHEMA_GAME,
        'battleId': battle_id,
        'matchId': match_id or f'm-{date}',
        'leagueId': league_id,
        'leagueName': league_name,
        'year': year,
        'stage': '擂台赛',
        'startTime': f'{date} 14:00:00',
        'date': date,
        'gameSeq': 1,
        'camp1': {'teamId': '1', 'team': team1, 'abbr': team1[:2]},
        'camp2': {'teamId': '2', 'team': team2, 'abbr': team2[:2]},
        'winCamp': win_camp,
        'winner': team1 if win_camp == 1 else team2,
        'picks': {'1': list(picks1), '2': list(picks2)},
        'bans': {'1': [], '2': []},
        'players': {'1': [], '2': []},
        'fetchedAt': '2026-11-11T14:20:00',
    }
    if bp_mode:
        game['bpMode'] = bp_mode
        game['bansKnown'] = bp_mode == kpl_bp.BP_MODE_FULL
        game['pickOrderKnown'] = bp_mode == kpl_bp.BP_MODE_FULL
    return game


def detail_for(own_picks, foe_picks=('甲', '乙', '丙', '丁', '戊')):
    return {'ownCamp': 'blue', 'players': [],
            'draft': {'picks': {'left': [{'name': hero} for hero in own_picks],
                                'right': [{'name': hero} for hero in foe_picks]}}}


@pytest.fixture
def facts_dir(tmp_path, monkeypatch):
    """把 bp_facts 的事实目录指向临时目录，并清空 mtime 缓存。"""
    monkeypatch.setattr(bp_facts, 'FACTS', tmp_path)
    bp_facts._cache.clear()
    yield tmp_path
    bp_facts._cache.clear()


# ---------------------------------------------------------------------------
# 1. bp_list 解析 / pick-ban 分流
# ---------------------------------------------------------------------------

def test_split_bp_uses_measured_semantics_and_keeps_order():
    payload = battle_payload()
    picks, bans = kpl_bp.split_bp(payload['data']['bp_list'])
    assert picks['1'] == PICKS_1          # is_ban_or_pick == 1 才是选用
    assert picks['2'] == PICKS_2
    assert bans['1'] == BANS_1            # == 0 是禁用
    assert bans['2'] == BANS_2


def test_split_bp_skips_bad_rows():
    rows = [
        {'camp': 1, 'is_ban_or_pick': 1, 'hero_name': '关羽'},
        {'camp': 9, 'is_ban_or_pick': 1, 'hero_name': '乱入'},
        {'camp': 2, 'is_ban_or_pick': 1, 'hero_name': ''},
        {'camp': 2, 'is_ban_or_pick': 'x', 'hero_name': '妲己'},
        {'camp': 2, 'is_ban_or_pick': 0, 'hero_name': '钟馗'},
        'not-a-dict',
    ]
    picks, bans = kpl_bp.split_bp(rows)
    assert picks == {'1': ['关羽'], '2': []}
    assert bans == {'1': [], '2': ['钟馗']}


def test_parse_battle_builds_schema_row():
    game = kpl_bp.parse_battle(battle_payload(), battle_id='111_1_222',
                               match=MATCH, league=LEAGUE, fetched_at='2026-11-11T14:20:00')
    assert game['schema'] == kpl_bp.SCHEMA_GAME
    assert game['battleId'] == '111_1_222'
    assert game['matchId'] == '2026100201'
    assert game['leagueId'] == '20260004'
    assert game['leagueName'] == '2026年KPL年度总决赛'
    assert game['year'] == 2026
    assert game['stage'] == '擂台赛'
    assert game['date'] == '2026-10-02'
    assert game['gameSeq'] == 1
    assert game['camp1'] == {'teamId': '10003', 'team': '北京WB', 'abbr': 'WB'}
    assert game['winCamp'] == 1 and game['winner'] == '北京WB'
    assert game['bpMode'] == kpl_bp.BP_MODE_FULL
    assert game['bansKnown'] is True and game['pickOrderKnown'] is True
    assert game['picks'] == {'1': PICKS_1, '2': PICKS_2}
    assert game['bans'] == {'1': BANS_1, '2': BANS_2}
    assert game['players']['1'][0] == {'hero': '关羽', 'player': 'P10', 'position': '对抗路'}
    assert len(game['players']['1']) == 5 and len(game['players']['2']) == 5
    assert game['fetchedAt'] == '2026-11-11T14:20:00'
    json.dumps(game)  # 必须可 JSON 序列化


def test_parse_battle_unfinished_and_no_winner():
    with pytest.raises(kpl_bp.BattleParseError) as exc:
        kpl_bp.parse_battle(battle_payload(status=1), match=MATCH, league=LEAGUE)
    assert exc.value.reason == 'not-finished'

    with pytest.raises(kpl_bp.BattleParseError) as exc:
        kpl_bp.parse_battle(battle_payload(win_camp=0), match=MATCH, league=LEAGUE)
    assert exc.value.reason == 'no-win-camp'


def test_parse_battle_partial_when_bp_list_truncated():
    """bp_list 不完整但十人面板齐全 → partial（picks 用面板兜底），不再整局丢掉。"""
    payload = battle_payload()
    payload['data']['bp_list'] = payload['data']['bp_list'][:10]
    game = kpl_bp.parse_battle(payload, match=MATCH, league=LEAGUE)
    assert game['bpMode'] == kpl_bp.BP_MODE_PARTIAL
    assert game['bansKnown'] is False and game['pickOrderKnown'] is False
    assert game['bans'] == {'1': [], '2': []}
    assert game['picks'] == {'1': PICKS_1, '2': PICKS_2}      # 来自十人面板
    combos = kpl_bp.build_combos([game], since_year=2024, min_games=1)
    assert combos['games'] == 1 and combos['lineups']


def test_parse_battle_blind_decider_uses_player_panel():
    """巅峰对决最后一局：bp_list 空 + 十人面板 10 人 → blind，picks 正确且进组合统计。"""
    payload = battle_payload(bp_list=[], battle_id='b3')
    match = make_match(['b1', 'b2', 'b3'], score1=4, score2=3, bo=7)   # BO7 打满 4:3
    game = kpl_bp.parse_battle(payload, battle_id='b3', match=match, league=LEAGUE)
    assert game['bpMode'] == kpl_bp.BP_MODE_BLIND
    assert game['bansKnown'] is False and game['pickOrderKnown'] is False
    assert game['bans'] == {'1': [], '2': []}
    assert game['picks'] == {'1': PICKS_1, '2': PICKS_2}      # 十人面板按分路顺序
    # 盲选也是选：照常进 pairs / trios / lineups
    combos = kpl_bp.build_combos([game], since_year=2024, min_games=1)
    assert combos['games'] == 1
    assert len(combos['lineups']) == 2
    assert combos['pairs']


def test_parse_battle_blind_only_on_series_decider():
    """不是系列赛最后一局 / 没打满，都不能判成 blind。"""
    # 同一场里第 2 局（不是最后一局）bp_list 空 → partial
    payload = battle_payload(bp_list=[], battle_id='b2')
    match = make_match(['b1', 'b2', 'b3'], score1=4, score2=3, bo=7)
    game = kpl_bp.parse_battle(payload, battle_id='b2', match=match, league=LEAGUE)
    assert game['bpMode'] == kpl_bp.BP_MODE_PARTIAL
    # 最后一局但系列赛没打满（4:1）→ partial
    payload = battle_payload(bp_list=[], battle_id='b3')
    match = make_match(['b1', 'b2', 'b3'], score1=4, score2=1, bo=7)
    game = kpl_bp.parse_battle(payload, battle_id='b3', match=match, league=LEAGUE)
    assert game['bpMode'] == kpl_bp.BP_MODE_PARTIAL


def test_parse_battle_partial_when_bp_has_19_entries():
    """实测那局 19 条 bp_list：picks 5/4、bans 5/5 → 不完整，记 partial 用面板兜底。"""
    full = battle_payload()
    bp_list = list(full['data']['bp_list'])
    victim = next(index for index, item in enumerate(bp_list)
                  if int(item['camp']) == 2 and int(item['is_ban_or_pick']) == 1)
    bp_list.pop(victim)
    assert len(bp_list) == 19
    payload = battle_payload(bp_list=bp_list)
    match = make_match(['b1', 'b2'], score1=3, score2=1, bo=7)       # 未打满，非盲选
    game = kpl_bp.parse_battle(payload, battle_id='b1', match=match, league=LEAGUE)
    assert game['bpMode'] == kpl_bp.BP_MODE_PARTIAL
    assert game['bansKnown'] is False
    assert game['picks'] == {'1': PICKS_1, '2': PICKS_2}            # 面板补齐 5/5


def test_parse_battle_invalid_only_when_player_panel_incomplete():
    """只有十人面板也不全才是 invalid；bp_list 空不算错。"""
    payload = battle_payload()
    payload['data']['battle_player_list'] = payload['data']['battle_player_list'][:-1]  # 9 人
    with pytest.raises(kpl_bp.BattleParseError) as exc:
        kpl_bp.parse_battle(payload, match=MATCH, league=LEAGUE)
    assert exc.value.reason == 'invalid'

    short = battle_payload()
    rows = short['data']['battle_player_list']
    rows[:] = [row for row in rows
               if not (int(row['camp']) == 1 and row['hero_name'] == PICKS_1[0])]
    rows.append({'camp': 2, 'hero_name': '多余人', 'player_name': 'X',
                 'position_desc': '对抗路'})                       # 10 人但一侧 4 人一侧 6 人
    with pytest.raises(kpl_bp.BattleParseError) as exc:
        kpl_bp.parse_battle(short, match=MATCH, league=LEAGUE)     # bp_list 完整也没用
    assert exc.value.reason == 'invalid'


def test_parse_battle_mismatch_when_pick_ban_semantics_flip():
    """契约硬要求：bp_list 的 pick 集合必须等于同 camp 十人面板英雄集合，否则计 mismatch。"""
    payload = battle_payload()
    for item in payload['data']['bp_list']:
        item['is_ban_or_pick'] = 1 - int(item['is_ban_or_pick'])   # 故意把 pick/ban 反过来
    with pytest.raises(kpl_bp.BattleParseError) as exc:
        kpl_bp.parse_battle(payload, match=MATCH, league=LEAGUE)
    assert exc.value.reason == 'mismatch'
    # 关掉校验后能解析出来（但 picks 是错的）——说明校验确实是保险丝
    game = kpl_bp.parse_battle(payload, match=MATCH, league=LEAGUE, strict_players=False)
    assert game['bpMode'] == kpl_bp.BP_MODE_FULL
    assert game['picks']['1'] == BANS_1


# ---------------------------------------------------------------------------
# 2. 增量落盘 / 原子替换
# ---------------------------------------------------------------------------

def test_game_store_incremental_dedupe(tmp_path):
    path = tmp_path / 'bp_games.jsonl'
    store = kpl_bp.GameStore(path)
    game1 = make_game(PICKS_1, PICKS_2, 1, battle_id='b1')
    game2 = make_game(PICKS_1, PICKS_2, 2, battle_id='b2')
    assert store.add(game1) is True
    assert store.add(game1) is False           # 同 battleId 不重复
    assert store.add(game2) is True
    store.flush()
    assert len(path.read_text(encoding='utf-8').splitlines()) == 2
    assert not list(tmp_path.glob('*.tmp'))     # 临时文件已原子替换掉

    reopened = kpl_bp.GameStore(path)
    assert reopened.ids == {'b1', 'b2'}
    assert reopened.add(game1) is False
    assert reopened.add(make_game(PICKS_1, PICKS_2, 1, battle_id='b3')) is True
    reopened.flush()
    lines = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    assert [line['battleId'] for line in lines] == ['b1', 'b2', 'b3']
    assert len(kpl_bp.load_games(path)) == 3


def test_game_store_refresh_replaces_rows(tmp_path):
    path = tmp_path / 'bp_games.jsonl'
    store = kpl_bp.GameStore(path)
    store.add(make_game(PICKS_1, PICKS_2, 1, battle_id='b1'))
    store.add(make_game(PICKS_1, PICKS_2, 1, battle_id='b2'))
    store.flush()

    refreshed = kpl_bp.GameStore(path, refresh=True)
    assert refreshed.ids == {'b1', 'b2'}
    assert refreshed.add(make_game(PICKS_1, PICKS_2, 2, battle_id='b1')) is True
    refreshed.flush()
    rows = kpl_bp.load_games(path)
    assert len(rows) == 2
    assert {row['battleId']: row['winCamp'] for row in rows} == {'b1': 2, 'b2': 1}


def test_load_games_skips_corrupt_lines(tmp_path):
    path = tmp_path / 'bp_games.jsonl'
    good = json.dumps(make_game(PICKS_1, PICKS_2, 1, battle_id='b1'), ensure_ascii=False)
    path.write_text('\n'.join([good, '{broken', '', good]) + '\n', encoding='utf-8')
    assert [row['battleId'] for row in kpl_bp.load_games(path)] == ['b1', 'b1']


# ---------------------------------------------------------------------------
# 3. 组合聚合：口径 / 胜率 / teams / minGames / 整阵容
# ---------------------------------------------------------------------------

def test_build_combos_counts_wins_year_and_teams():
    games = [
        make_game(PICKS_1, PICKS_2, 1, date='2025-03-01', team1='队A', battle_id='g1'),
        make_game(PICKS_1, PICKS_2, 2, date='2026-03-01', team1='队A', battle_id='g2'),
        make_game(PICKS_1, PICKS_2, 2, date='2026-04-01', team1='队B', battle_id='g3'),
    ]
    combos = kpl_bp.build_combos(games, since_year=2024, min_games=3)
    assert combos['games'] == 3
    pair = next(row for row in combos['pairs'] if set(row['heroes']) == {'关羽', '百里守约'})
    assert pair['heroes'] == ['关羽', '百里守约']        # 排序后的英雄名
    assert pair['n'] == 3 and pair['wins'] == 1
    assert pair['wr'] == 33.3
    assert pair['year'] == 2026
    assert pair['size'] == 2
    assert pair['teams'] == [{'team': '队A', 'n': 2, 'wins': 1},
                             {'team': '队B', 'n': 1, 'wins': 0}]
    trio = next(row for row in combos['trios'] if set(row['heroes']) == {'关羽', '百里守约', '钟馗'})
    assert trio['n'] == 3 and trio['wins'] == 1 and trio['size'] == 3


def test_build_combos_min_games_and_dedupe_heroes():
    # 只出现 2 次的组合被 minGames=3 过滤
    games = [make_game(['关羽', '马超', '妲己', '孙悟空', '嫦娥'], PICKS_2, 1, battle_id='g1'),
             make_game(['关羽', '马超', '妲己', '孙悟空', '嫦娥'], PICKS_2, 1, battle_id='g2')]
    combos = kpl_bp.build_combos(games, since_year=2024, min_games=3)
    assert all(row['n'] >= 3 for row in combos['pairs'])
    # 同队同场重复英雄先去重：双方 5 个槽位里都只有 4 个不同英雄 → 不产出整阵容
    dup = make_game(['关羽', '关羽', '妲己', '孙悟空', '嫦娥'],
                    ['鲁班大师', '鲁班大师', '盾山', '阿古朵', '橘右京'], 1, battle_id='g3')
    combos = kpl_bp.build_combos([dup], since_year=2024, min_games=1)
    assert combos['lineups'] == []
    assert all(len(row['heroes']) == 5 for row in combos['lineups'])
    pair = next(row for row in combos['pairs'] if set(row['heroes']) == {'关羽', '妲己'})
    assert pair['n'] == 1


def test_build_combos_teams_top5_sorted():
    games = []
    for index in range(6):
        games.append(make_game(PICKS_1, PICKS_2, 1, team1=f'队{index}', battle_id=f'g{index}'))
    combos = kpl_bp.build_combos(games, since_year=2024, min_games=3)
    pair = next(row for row in combos['pairs'] if set(row['heroes']) == {'关羽', '百里守约'})
    assert len(pair['teams']) == 5
    assert [row['n'] for row in pair['teams']] == [1, 1, 1, 1, 1]


def test_build_combos_since_year_filter():
    old = make_game(PICKS_1, PICKS_2, 1, year=2023, date='2023-05-01', battle_id='old')
    new = make_game(PICKS_1, PICKS_2, 1, year=2024, date='2024-05-01', battle_id='new')
    combos = kpl_bp.build_combos([old, new], since_year=2024, min_games=1)
    assert combos['games'] == 1
    pair = next(row for row in combos['pairs'] if set(row['heroes']) == {'关羽', '百里守约'})
    assert pair['n'] == 1


def test_lineups_ignore_order_and_keep_single_occurrence():
    order_a = ['关羽', '百里守约', '钟馗', '孙悟空', '妲己']
    order_b = ['妲己', '钟馗', '孙悟空', '关羽', '百里守约']      # 同一套，顺序不同
    games = [make_game(order_a, PICKS_2, 1, team1='成都AG超玩会', battle_id='g1'),
             make_game(order_b, PICKS_2, 2, team1='广州TTG', battle_id='g2')]
    combos = kpl_bp.build_combos(games, since_year=2024, min_games=3)   # minGames 不卡整阵容
    lineup = next(row for row in combos['lineups'] if set(row['heroes']) == set(order_a))
    assert lineup['heroes'] == sorted(order_a)
    assert lineup['n'] == 2 and lineup['wins'] == 1 and lineup['wr'] == 50.0
    assert 'size' not in lineup
    # teams 按 n 倒序；n 相同时按队名排序（确定性输出）
    assert lineup['teams'] == [{'team': '广州TTG', 'n': 1, 'wins': 0},
                               {'team': '成都AG超玩会', 'n': 1, 'wins': 1}]
    # 对手那套也各自成组（整阵容按 pick 方队伍分别统计）
    foe = next(row for row in combos['lineups'] if set(row['heroes']) == set(PICKS_2))
    assert foe['n'] == 2 and foe['teams'] == [{'team': '队B', 'n': 2, 'wins': 1}]


def test_build_facts_top_level_fields():
    games = [
        make_game(PICKS_1, PICKS_2, 1, year=2024, date='2024-01-05', league_id='20240001',
                  league_name='2024KPL春季赛', battle_id='g1'),
        make_game(PICKS_1, PICKS_2, 2, year=2025, date='2025-05-01', league_id='20250001',
                  league_name='2025KPL春季赛', battle_id='g2'),
        make_game(PICKS_1, PICKS_2, 2, year=2026, date='2026-11-10', league_id='20260004',
                  league_name='2026年KPL年度总决赛', battle_id='g3'),
        make_game(PICKS_1, PICKS_2, 1, year=2023, date='2023-01-01', battle_id='g4'),
    ]
    facts = kpl_bp.build_facts(games, since_year=2024, min_games=3,
                               generated_at='2026-11-11T14:30:00')
    assert facts['schema'] == 'bp-kpl-combos-v1'
    assert facts['source'] == 'kpl-official'
    assert facts['sinceYear'] == 2024
    assert facts['games'] == 3
    assert facts['minGames'] == 3
    assert facts['updatedAt'] == '2026-11-11T14:30:00'
    assert facts['windowStart'] == '2024-01-05'
    assert facts['windowEnd'] == '2026-11-10'
    assert facts['leagueCount'] == 3
    assert facts['leagueNames'] == ['2024KPL春季赛', '2025KPL春季赛', '2026年KPL年度总决赛']
    assert facts['pairs'] and facts['trios'] and facts['lineups']
    json.dumps(facts, ensure_ascii=False)


def test_build_manifest_counts_and_errors(tmp_path):
    games = [
        make_game(PICKS_1, PICKS_2, 1, date='2026-10-02', match_id='m1', battle_id='g1',
                  bp_mode=kpl_bp.BP_MODE_FULL),
        make_game(PICKS_1, PICKS_2, 2, date='2026-10-02', match_id='m1', battle_id='g2',
                  bp_mode=kpl_bp.BP_MODE_BLIND),
        make_game(PICKS_1, PICKS_2, 1, date='2026-11-08', match_id='m2', battle_id='g3',
                  bp_mode=kpl_bp.BP_MODE_PARTIAL),
        make_game(PICKS_1, PICKS_2, 1, date='2026-10-02', match_id='m1', battle_id='g4'),
    ]
    manifest = kpl_bp.build_manifest(
        games, since_year=2024,
        stats={'errors': 2, 'errorBattleIds': ['bad1', 'bad2'], 'invalid': 1},
        previous={'leagues': [{'leagueId': '20260004', 'crawledAt': '2026-10-01T00:00:00'}]},
        crawled_league_ids=['20260004'], generated_at='2026-11-11T14:30:00')
    assert manifest['schema'] == 'kpl-bp-manifest-v1'
    assert manifest['games'] == 4
    assert manifest['windowStart'] == '2026-10-02'
    assert manifest['windowEnd'] == '2026-11-08'
    # 四类计数：老行没有 bpMode 时按 full 兜底
    assert manifest['full'] == 2
    assert manifest['blind'] == 1
    assert manifest['partial'] == 1
    assert manifest['invalid'] == 1
    assert manifest['errors'] == 2
    assert manifest['errorBattleIds'] == ['bad1', 'bad2']
    assert manifest['leagues'] == [{'leagueId': '20260004',
                                    'leagueName': '2026年KPL年度总决赛', 'year': 2026,
                                    'matches': 2, 'games': 4,
                                    'crawledAt': '2026-11-11T14:30:00'}]


def test_backfill_game_modes_adds_fields_for_old_rows():
    full_bans = {'1': ['a', 'b', 'c', 'd'], '2': ['e', 'f', 'g', 'h']}
    old = {'battleId': 'old1', 'picks': {'1': ['关羽'], '2': ['妲己']}, 'bans': full_bans}
    rows, changed = kpl_bp.backfill_game_modes([old])
    assert changed == 1
    row = rows[0]
    assert row['bpMode'] == kpl_bp.BP_MODE_FULL
    assert row['bansKnown'] is True and row['pickOrderKnown'] is True
    keys = list(row.keys())
    assert keys.index('bpMode') == keys.index('picks') - 3   # 字段插在 picks 前
    assert kpl_bp.backfill_game_modes(rows)[1] == 0          # 幂等

    # 老行没有 ban（bp_list 只有 picks）→ 降级 partial，bans 清空
    no_bans, changed = kpl_bp.backfill_game_modes(
        [{'battleId': 'old2', 'picks': {'1': ['a'], '2': ['b']}, 'bans': {'1': [], '2': []}}])
    assert changed == 1
    assert no_bans[0]['bpMode'] == kpl_bp.BP_MODE_PARTIAL
    assert no_bans[0]['bansKnown'] is False and no_bans[0]['pickOrderKnown'] is False

    # 早期版本把 ban 不全（19 条 bp_list）的局存成了 full → 校正为 partial
    stale = {'battleId': 'old3', 'bpMode': 'full', 'bansKnown': True, 'pickOrderKnown': True,
             'picks': {'1': ['a'], '2': ['b']},
             'bans': {'1': ['c', 'd', 'e', 'f'], '2': ['g', 'h', 'i']}}
    fixed, changed = kpl_bp.backfill_game_modes([stale])
    assert changed == 1
    assert fixed[0]['bpMode'] == kpl_bp.BP_MODE_PARTIAL
    assert fixed[0]['bansKnown'] is False and fixed[0]['pickOrderKnown'] is False
    assert fixed[0]['bans'] == {'1': [], '2': []}
    assert fixed[0]['picks'] == {'1': ['a'], '2': ['b']}      # picks 不动
    assert kpl_bp.backfill_game_modes(fixed)[1] == 0


def test_select_leagues_by_year_and_filter():
    leagues = [
        {'league_id': '20230001', 'league_name': '2023KPL春季赛', 'year': 2023},
        {'league_id': '20240001', 'league_name': '2024KPL春季赛', 'year': 2024},
        {'league_id': '20260004', 'league_name': '2026年KPL年度总决赛', 'year': 2026},
    ]
    assert [row['league_id'] for row in kpl_bp.select_leagues(leagues, 2024)] == \
        ['20240001', '20260004']
    assert [row['league_id'] for row in kpl_bp.select_leagues(leagues, 2024, ['20260004'])] == \
        ['20260004']
    assert [row['league_id'] for row in kpl_bp.select_leagues(leagues, 2024, ['2024KPL'])] == \
        ['20240001']


# ---------------------------------------------------------------------------
# 4. api_get 重试（用假 session，不联网）
# ---------------------------------------------------------------------------

class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def get(self, url, params=None, timeout=None):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(outcome)


def test_api_get_retries_then_succeeds():
    session = FakeSession([OSError('boom'), {'code': 500}, {'code': 200, 'results': [1]}])
    payload = kpl_bp.api_get(session, 'http://x', attempts=4, sleep=lambda _s: None)
    assert payload == {'code': 200, 'results': [1]}
    assert session.calls == 3


def test_api_get_gives_up_after_attempts():
    session = FakeSession([OSError('boom')] * 5)
    assert kpl_bp.api_get(session, 'http://x', attempts=4, sleep=lambda _s: None) is None
    assert session.calls == 4


# ---------------------------------------------------------------------------
# 5. 端到端：假 session 跑一次增量抓取（离线）
# ---------------------------------------------------------------------------

def _install_fake_api(monkeypatch, *, fail_battle=None):
    leagues = [{'league_id': '20260004', 'league_name': '2026年KPL年度总决赛', 'year': 2026},
               {'league_id': '20230001', 'league_name': '2023KPL春季赛', 'year': 2023}]
    matches = [{'match_id': 'm1', 'status': 2, 'start_time': '2026-10-02 14:00:00',
                'match_stage_desc': '擂台赛', 'camp1': {'team_name': '北京WB'},
                'camp2': {'team_name': '广州TTG'},
                'match_battle_video_list': [{'battle_id': 'b1', 'battle_seq': 1},
                                            {'battle_id': 'b2', 'battle_seq': 2}]},
               {'match_id': 'm2', 'status': 0, 'start_time': '2026-11-15 14:00:00',
                'match_battle_video_list': [{'battle_id': 'b9', 'battle_seq': 1}]}]
    payloads = {
        'b1': battle_payload(win_camp=1, battle_id='b1'),
        'b2': battle_payload(win_camp=2, battle_id='b2'),
    }
    calls = {'battles': []}

    monkeypatch.setattr(kpl_bp, 'fetch_leagues', lambda session, log=None: leagues)
    monkeypatch.setattr(kpl_bp, 'fetch_matches', lambda session, league_id, log=None: matches)
    monkeypatch.setattr(kpl_bp, 'fetch_match_battles', lambda session, match_id, log=None: [])

    def fake_fetch_battle(session, battle_id, log=None):
        calls['battles'].append(battle_id)
        if battle_id == fail_battle:
            return None
        return payloads.get(battle_id)

    monkeypatch.setattr(kpl_bp, 'fetch_battle', fake_fetch_battle)
    return calls


def test_run_crawl_end_to_end_idempotent(tmp_path, monkeypatch):
    calls = _install_fake_api(monkeypatch, fail_battle='b2')
    paths = {'games_path': tmp_path / 'bp_games.jsonl',
             'manifest_path': tmp_path / 'manifest.json',
             'facts_path': tmp_path / 'kpl_combos.json'}
    result = kpl_bp.run_crawl(since_year=2024, sleep=0, session=object(), log=lambda *a, **k: None,
                              sleep_fn=lambda _s: None, min_games=1, **paths)
    assert result['crawl']['leagues'] == 1            # 2023 赛季被 since-year 过滤
    assert result['crawl']['gamesPlanned'] == 2       # status==0 的比赛不抓
    assert result['crawl']['added'] == 1              # b2 抓取失败
    assert result['crawl']['errors'] == 1
    assert result['crawl']['errorBattleIds'] == ['b2']
    rows = kpl_bp.load_games(paths['games_path'])
    assert [row['battleId'] for row in rows] == ['b1']
    manifest = json.loads(paths['manifest_path'].read_text(encoding='utf-8'))
    assert manifest['games'] == 1 and manifest['errors'] == 1
    assert manifest['full'] == 1 and manifest['blind'] == 0
    assert manifest['partial'] == 0 and manifest['invalid'] == 0
    facts = json.loads(paths['facts_path'].read_text(encoding='utf-8'))
    assert facts['games'] == 1 and facts['pairs']

    # 第二次执行：b1 已存在跳过，只剩 b2 会重试失败 → 不重复写行
    calls['battles'].clear()
    result2 = kpl_bp.run_crawl(since_year=2024, sleep=0, session=object(),
                               log=lambda *a, **k: None, sleep_fn=lambda _s: None, **paths)
    assert result2['crawl']['skippedExisting'] == 1
    assert result2['crawl']['added'] == 0
    assert calls['battles'] == ['b2']
    assert len(kpl_bp.load_games(paths['games_path'])) == 1


def test_run_crawl_dry_run_writes_nothing(tmp_path, monkeypatch):
    calls = _install_fake_api(monkeypatch)
    paths = {'games_path': tmp_path / 'bp_games.jsonl',
             'manifest_path': tmp_path / 'manifest.json',
             'facts_path': tmp_path / 'kpl_combos.json'}
    result = kpl_bp.run_crawl(since_year=2024, dry_run=True, sleep=0, session=object(),
                              log=lambda *a, **k: None, sleep_fn=lambda _s: None, **paths)
    assert result['dryRun'] is True
    assert result['crawl']['pending'] == 2
    assert calls['battles'] == []
    assert not paths['games_path'].exists()
    assert not paths['manifest_path'].exists()


# ---------------------------------------------------------------------------
# 6. bp_facts：新字段 / teams 透传 / 整阵容 / 老文件兜底
# ---------------------------------------------------------------------------

NEW_FACTS = {
    'schema': 'bp-kpl-combos-v1', 'source': 'kpl-official', 'sinceYear': 2024,
    'games': 100, 'minGames': 3, 'updatedAt': '2026-11-11T14:30:00',
    'windowStart': '2024-01-05', 'windowEnd': '2026-11-10',
    'leagueCount': 9, 'leagueNames': ['2024KPL春季赛', '2026年KPL年度总决赛'],
    'pairs': [{'heroes': ['关羽', '百里守约'], 'n': 45, 'wins': 20, 'wr': 44.4, 'year': 2026,
               'size': 2, 'teams': [{'team': '广州TTG', 'n': 6, 'wins': 3}]}],
    'trios': [{'heroes': ['关羽', '百里守约', '钟馗'], 'n': 3, 'wins': 3, 'wr': 100.0,
               'year': 2026, 'size': 3, 'teams': [{'team': '北京WB', 'n': 2, 'wins': 2}]}],
    'lineups': [{'heroes': ['关羽', '妲己', '孙悟空', '百里守约', '钟馗'], 'n': 2, 'wins': 1,
                 'wr': 50.0, 'year': 2026,
                 'teams': [{'team': '成都AG超玩会', 'n': 1, 'wins': 1}]}],
}

OWN_SHUFFLED = ['妲己', '钟馗', '关羽', '孙悟空', '百里守约']


def test_bp_facts_new_fields_and_lineup(facts_dir):
    (facts_dir / 'kpl_combos.json').write_text(json.dumps(NEW_FACTS, ensure_ascii=False),
                                               encoding='utf-8')
    facts = bp_facts.for_match(detail_for(OWN_SHUFFLED))
    kpl = facts['kpl']
    assert kpl['lineupSeen'] is True
    assert kpl['lineup']['n'] == 2 and kpl['lineup']['wins'] == 1
    assert kpl['lineup']['heroes'] == sorted(OWN_SHUFFLED)      # 顺序打乱也能命中
    assert kpl['lineup']['teams'][0]['team'] == '成都AG超玩会'
    assert kpl['totalTrios'] == 10
    assert kpl['updatedAt'] == '2026-11-11T14:30:00'
    assert kpl['sourceLabel'] == 'KPL 官方赛事'
    assert kpl['windowStart'] == '2024-01-05' and kpl['windowEnd'] == '2026-11-10'
    assert kpl['leagueCount'] == 9 and kpl['latestYear'] == 2026
    # teams 透传到命中组合与 comboIndex
    pair = next(row for row in kpl['pairs'] if set(row['heroes']) == {'关羽', '百里守约'})
    assert pair['teams'][0]['team'] == '广州TTG'
    assert kpl['comboIndex']['关羽+百里守约']['teams'][0]['team'] == '广州TTG'
    assert kpl['comboIndex']['百里守约+关羽'] == kpl['comboIndex']['关羽+百里守约']
    trio = next(row for row in kpl['trios'] if set(row['heroes']) == {'关羽', '百里守约', '钟馗'})
    assert trio['teams'][0]['team'] == '北京WB'


def test_bp_facts_lineup_miss_when_fewer_than_five(facts_dir):
    (facts_dir / 'kpl_combos.json').write_text(json.dumps(NEW_FACTS, ensure_ascii=False),
                                               encoding='utf-8')
    facts = bp_facts.for_match(detail_for(['关羽', '百里守约', '钟馗', '妲己']))
    assert facts['kpl']['lineup'] is None
    assert facts['kpl']['lineupSeen'] is False
    assert facts['kpl']['totalTrios'] == 4


def test_bp_facts_old_file_fallback(facts_dir):
    old = {
        'schema': 'bp-kpl-combos-v1', 'source': 'kpl', 'sinceYear': 2024,
        'games': 4586, 'minGames': 3,
        'pairs': [{'heroes': ['关羽', '百里守约'], 'n': 45, 'wins': 20, 'wr': 44.4,
                   'year': 2026, 'size': 2}],
        'trios': [{'heroes': ['关羽', '百里守约', '钟馗'], 'n': 3, 'wins': 3, 'wr': 100.0,
                   'year': 2026, 'size': 3}],
    }
    (facts_dir / 'kpl_combos.json').write_text(json.dumps(old, ensure_ascii=False),
                                               encoding='utf-8')
    facts = bp_facts.for_match(detail_for(OWN_SHUFFLED))       # 老文件不能报错
    kpl = facts['kpl']
    assert kpl['lineup'] is None and kpl['lineupSeen'] is False
    assert kpl['updatedAt'] is None and kpl['windowStart'] is None
    assert kpl['leagueCount'] is None
    assert kpl['latestYear'] == 2026                            # 从组合行 year 兜底
    assert kpl['sourceLabel'] == 'KPL 官方赛事'
    assert all(row['teams'] == [] for row in kpl['pairs'])
    assert all(value['teams'] == [] for value in kpl['comboIndex'].values())


def test_bp_facts_handles_missing_facts_file(facts_dir):
    facts = bp_facts.for_match(detail_for(OWN_SHUFFLED))       # 连文件都没有
    assert facts['kpl']['lineupSeen'] is False
    assert facts['kpl']['games'] is None
    assert facts['kpl']['pairs'] == [] and facts['kpl']['trios'] == []


def test_bp_facts_returns_none_without_own_heroes(facts_dir):
    assert bp_facts.for_match({'ownCamp': 'blue', 'draft': {'picks': {}}, 'players': []}) is None


# ---------------------------------------------------------------------------
# 7. scripts/build_bp_facts.py：格式识别（不跑 lane / 不联网）
# ---------------------------------------------------------------------------

def test_build_bp_facts_detects_local_and_legacy(tmp_path):
    import importlib.util
    build_script = kpl_bp.ROOT / 'scripts' / 'build_bp_facts.py'
    if not build_script.is_file():
        # 该脚本的巅峰千强部分依赖私有数据集，公开仓库不带；KPL 部分仍可单独测试。
        pytest.skip('scripts/build_bp_facts.py 仅随源码工作区提供')
    spec = importlib.util.spec_from_file_location('build_bp_facts_test', build_script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    local_path = tmp_path / 'local.jsonl'
    local_path.write_text(json.dumps(make_game(PICKS_1, PICKS_2, 1), ensure_ascii=False) + '\n',
                          encoding='utf-8')
    legacy_path = tmp_path / 'legacy.jsonl'
    legacy_path.write_text(json.dumps({'year': 2026, 'y': 1,
                                       'picks1': [{'hero_name': '关羽'}, {'hero_name': '百里守约'}],
                                       'picks2': [{'hero_name': '妲己'}]},
                                      ensure_ascii=False) + '\n', encoding='utf-8')
    assert module.detect_kpl_format(local_path) == 'local'
    assert module.detect_kpl_format(legacy_path) == 'legacy'
    local_facts = module.build_kpl_facts(local_path, 2024, 1)
    assert local_facts['source'] == 'kpl-official' and local_facts['pairs']
    legacy_facts = module.build_kpl_facts(legacy_path, 2024, 1)
    assert legacy_facts['source'] == 'kpl' and legacy_facts['pairs']
    assert 'lineups' not in legacy_facts          # 旧格式不产出整阵容
