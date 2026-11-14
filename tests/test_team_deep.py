"""战队详情 team_deep：逐局结构、双方阵容、经济占比、KPL 命中与缺字段降级。"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import team_clusters  # noqa: E402

KPL_PATH = ROOT / 'data' / 'facts' / 'kpl_combos.json'

OWN_HEROES = ['夏侯惇', '张良', '公孙离', '澜', '张飞']
OWN_IDS = [f'own{i}' for i in range(5)]
OPPONENT_A = ['吕布', '西施', '马可波罗', '镜', '牛魔']
OPPONENT_IDS_A = [f'a{i}' for i in range(5)]
OPPONENT_B = ['关羽', '沈梦溪', '虞姬', '李白', '东皇太一']
OPPONENT_IDS_B = [f'b{i}' for i in range(5)]
BAN_HEROES = ['盾山', '庄周', '海月', '赵云', '朵莉亚']

# 十人面板 position：0=对抗路 1=中路 2=发育路 3=打野 4=游走
POSITIONS = [0, 1, 2, 3, 4]


def role_entry(pid, name, hero, position, gold, kills, deaths, assists, towers):
    return {
        'basicInfo': {'playerId': pid, 'roleName': name},
        'battleRecords': {'usedHero': {'heroName': hero}, 'position': position},
        'battleStats': {'killCnt': kills, 'deadCnt': deaths, 'assistCnt': assists,
                        'money': gold, 'towerCnt': towers, 'gradeGame': '8.0'},
    }


def team_json(rows, *, win, dragons=(1, 0, 0, 0, 0), towers=None, picks=None, bans=None):
    stats = {
        'killCnt': sum(row[1] for row in rows),
        'deadCnt': sum(row[2] for row in rows),
        'assistCnt': sum(row[3] for row in rows),
        'money': sum(row[0] for row in rows),
        'towerCnt': towers if towers is not None else sum(row[4] for row in rows),
        'gameResult': win,
        'pickHeros': [{'heroName': hero} for hero in picks or []],
        'banHeros': [{'heroName': hero} for hero in bans or []],
    }
    for key, value in zip(team_clusters.DRAGON_KEYS, dragons):
        stats[key] = value
    return stats


def camp_panel(seq, start, *, own_camp=1, duration=900, enemy_win=True,
               own_golds=(7000, 7200, 7500, 7800, 8200),
               opp_golds=(6500, 7000, 7500, 8000, 8500),
               opp_heroes=None, own_bans=None, enemy_bans=None,
               dragons=(1, 0, 0, 0, 0), opp_towers=5, opp_kills=(3, 4, 5, 6, 2)):
    """合成一局营地详情：双方十人面板 + blueTeam/redTeam 终局合计。"""
    opp_heroes = opp_heroes or OPPONENT_A
    enemy_bans = enemy_bans if enemy_bans is not None else BAN_HEROES
    own_bans = own_bans if own_bans is not None else ['曹操', '娜可露露', '小乔', '马超', '瑶']
    own_rows = [(gold, 2, 2, 4, 1) for gold in own_golds]
    opp_rows = [(gold, kills, 2, 4, 1) for gold, kills in zip(opp_golds, opp_kills)]
    own_team = team_json(own_rows, win=not enemy_win, dragons=dragons,
                         towers=3, picks=OWN_HEROES, bans=own_bans)
    enemy_team = team_json(opp_rows, win=enemy_win, dragons=dragons,
                           towers=opp_towers, picks=opp_heroes, bans=enemy_bans)
    own_roles = [role_entry(pid, f'我方{i}', OWN_HEROES[i], POSITIONS[i], gold, 2, 2, 4, 1)
                 for i, (pid, gold) in enumerate(zip(OWN_IDS, own_golds))]
    enemy_roles = [role_entry(pid, f'对手{i}', opp_heroes[i], POSITIONS[i], gold,
                              kills, 2, 4, 1)
                   for i, (pid, gold, kills) in enumerate(zip(OPPONENT_IDS_A, opp_golds, opp_kills))]
    blue_roles, red_roles = (own_roles, enemy_roles) if own_camp == 1 else (enemy_roles, own_roles)
    blue_team, red_team = (own_team, enemy_team) if own_camp == 1 else (enemy_team, own_team)
    return {'data': {
        'head': {'acntCamp': own_camp, 'gameResult': not enemy_win},
        'battle': {'startTime': start, 'usedTime': duration, 'mapName': '王者峡谷'},
        'blueTeam': blue_team, 'redTeam': red_team,
        'blueRoles': blue_roles, 'redRoles': red_roles,
    }}


def write_panels(directory, items):
    directory.mkdir(parents=True, exist_ok=True)
    for seq, payload in items:
        (directory / f'{seq}.json').write_text(json.dumps(payload, ensure_ascii=False),
                                               encoding='utf-8')


def three_games(directory, *, opp_heroes=None, own_camp=1):
    items = [
        ('1', camp_panel('1', '11-02 12:00', own_camp=own_camp, enemy_win=True,
                         opp_heroes=opp_heroes)),
        ('2', camp_panel('2', '11-03 12:00', enemy_win=True, opp_heroes=opp_heroes)),
        ('3', camp_panel('3', '11-04 12:00', enemy_win=False, opp_heroes=opp_heroes)),
    ]
    write_panels(directory, items)


def team_id_of(camp_dir, db_path):
    data = team_clusters.list_teams(camp_dir, db_path)
    return data['teams'][0]['id']


# ---------------------------------------------------------------- 结构
def test_team_deep_returns_contract_structure(tmp_path):
    camp = tmp_path / 'camp_details'
    three_games(camp)
    db = tmp_path / 'db.sqlite3'
    team_id = team_id_of(camp, db)

    deep = team_clusters.team_deep(camp, db, team_id)

    assert deep is not None
    assert set(deep) >= {'team', 'own', 'games', 'style', 'taxonomy', 'kpl', 'meta'}
    assert deep['team']['id'] == team_id
    assert deep['team']['matches'] == 3
    assert deep['own']['matches'] == 3
    assert set(deep['games'][0]) >= {'seq', 'start', 'day', 'duration', 'map', 'win',
                                     'opponentWin', 'ownSide', 'sides', 'style'}
    # 逐局按时间倒序
    assert [game['day'] for game in deep['games']] == ['11-04', '11-03', '11-02']
    latest = deep['games'][0]
    assert latest['win'] is True            # 本队视角
    assert latest['opponentWin'] is False
    assert latest['duration'] == 900
    assert latest['map'] == '王者峡谷'
    assert set(latest['sides']) == {'own', 'enemy'}


def test_team_deep_players_picks_bans_and_gold_share(tmp_path):
    camp = tmp_path / 'camp_details'
    three_games(camp)
    db = tmp_path / 'db.sqlite3'
    team_id = team_id_of(camp, db)
    deep = team_clusters.team_deep(camp, db, team_id)
    game = deep['games'][0]

    for side in ('own', 'enemy'):
        block = game['sides'][side]
        assert len(block['players']) == 5
        assert len(block['picks']) == 5
        assert block['bans']
        shares = [player['goldShare'] for player in block['players']]
        assert sum(shares) == pytest.approx(100.0, abs=0.3)
        for player in block['players']:
            assert player['name'] and player['lane'] and player['archetype']
            assert player['minutes'] == 15.0
        for pick in block['picks']:
            assert pick['name'] and pick['lane'] and pick['archetype']
        for ban in block['bans']:
            assert ban['name'] and ban['archetype']
        stats = block['stats']
        assert set(stats) == {'kills', 'deaths', 'assists', 'gold', 'towers',
                              'dragons', 'win'}
        assert stats['dragons'] == 1

    # picks 用十人面板的真实分路：公孙离在发育路 → 游射
    own_picks = {pick['name']: pick for pick in game['sides']['own']['picks']}
    assert own_picks['公孙离']['lane'] == '发育路'
    assert own_picks['公孙离']['archetype'] == '游射'
    # bans 来自营地的终局禁选名单，附类型
    enemy_bans = {ban['name']: ban for ban in game['sides']['enemy']['bans']}
    assert enemy_bans['盾山']['lane'] == '游走'
    assert enemy_bans['盾山']['archetype'] == '开团辅'


def test_team_deep_game_style_matches_style_windows(tmp_path):
    camp = tmp_path / 'camp_details'
    three_games(camp)
    db = tmp_path / 'db.sqlite3'
    team_id = team_id_of(camp, db)
    deep = team_clusters.team_deep(camp, db, team_id)

    for game in deep['games']:
        style = game['style']
        assert set(style) == {'x', 'y', 'quadrant', 'top1', 'fightPerMin',
                              'macroPerMin', 'evidence', 'missing'}
        assert style['top1'] and style['top1']['share'] is not None
        assert style['evidence']
        # 固定三条缺口
        assert len(style['missing']) == 3
    # 每局 point 与顶部 windows 的分布一致：三局里两局同象限，占比 >= 50%
    window = deep['style']['windows']['all']
    counted = sum(window['counts'].values())
    assert window['games'] == 3
    assert counted == sum(1 for game in deep['games'] if game['style']['quadrant'])
    assert deep['style']['main']['quadrant'] == window['quadrant']


def test_own_players_are_per_lane_aggregates(tmp_path):
    camp = tmp_path / 'camp_details'
    three_games(camp)
    db = tmp_path / 'db.sqlite3'
    team_id = team_id_of(camp, db)
    deep = team_clusters.team_deep(camp, db, team_id)

    players = deep['own']['players']
    assert len(players) == 5
    assert {player['lane'] for player in players} == {'对抗路', '打野', '中路', '发育路', '游走'}
    assert [player['lane'] for player in players] == ['对抗路', '打野', '中路', '发育路', '游走']
    for player in players:
        assert player['name'] and player['games'] == 3
        for key in ('gpm', 'dpm', 'dtpm', 'participation', 'towerPerGame',
                    'controlPerMin', 'healPerMin', 'totals'):
            assert key in player
        assert player['totals']['gold'] > 0


def test_team_deep_unknown_team_returns_none(tmp_path):
    camp = tmp_path / 'camp_details'
    three_games(camp)
    assert team_clusters.team_deep(camp, tmp_path / 'db.sqlite3',
                                   'team-not-found') is None
    # 空数据目录同样不会 500：没有战队就返回 None，由路由给 404
    assert team_clusters.team_deep(tmp_path / 'empty', tmp_path / 'db.sqlite3',
                                   'team-6f8df5bf4a0b') is None


def test_team_deep_only_returns_that_team_games(tmp_path):
    camp = tmp_path / 'camp_details'
    write_panels(camp, [
        ('1', camp_panel('1', '11-02 12:00')),
        ('2', camp_panel('2', '11-03 12:00')),
    ])
    # 换一套对手阵容 → 第二个 cluster
    payload = camp_panel('3', '11-04 12:00', opp_heroes=OPPONENT_B)
    data = payload['data']
    data['redTeam']['pickHeros'] = [{'heroName': hero} for hero in OPPONENT_B]
    for index, role in enumerate(data['redRoles']):
        role['battleRecords']['usedHero']['heroName'] = OPPONENT_B[index]
        role['basicInfo']['playerId'] = OPPONENT_IDS_B[index]
    (camp / '3.json').write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')

    db = tmp_path / 'db.sqlite3'
    teams = team_clusters.list_teams(camp, db)['teams']
    assert len(teams) == 2
    deep = team_clusters.team_deep(camp, db, teams[1]['id'])
    assert [game['seq'] for game in deep['games']] == ['3']


# ---------------------------------------------------------------- 缺字段降级
def test_team_deep_degrades_without_team_totals(tmp_path):
    camp = tmp_path / 'camp_details'
    payload = camp_panel('1', '11-02 12:00')
    del payload['data']['blueTeam']
    del payload['data']['redTeam']
    write_panels(camp, [('1', payload)])
    db = tmp_path / 'db.sqlite3'
    team_id = team_id_of(camp, db)
    deep = team_clusters.team_deep(camp, db, team_id)

    game = deep['games'][0]
    assert game['sides']['enemy']['stats']['dragons'] is None
    assert game['sides']['enemy']['stats']['kills'] == 20      # 十人面板兜底求和
    assert game['style']['y'] is None                          # 缺控龙 → 不给 0 冒充
    assert game['style']['x'] is not None                      # 经济占比仍能算
    assert len(game['sides']['own']['picks']) == 5             # 阵容面板仍在
    assert game['sides']['own']['bans'] == []                  # 没有禁选名单就是空表


# ---------------------------------------------------------------- KPL 命中
def _kpl_file():
    if not KPL_PATH.is_file():
        pytest.skip('没有 KPL 组合事实表')
    return json.loads(KPL_PATH.read_text(encoding='utf-8'))


def test_team_deep_kpl_pair_hits_from_real_table(tmp_path):
    table = _kpl_file()
    pair = max(table['pairs'], key=lambda row: row['n'])['heroes']
    heroes = list(pair) + [hero for hero in OWN_HEROES if hero not in pair][:3]
    heroes = heroes[:5]
    camp = tmp_path / 'camp_details'
    three_games(camp, opp_heroes=heroes)
    db = tmp_path / 'db.sqlite3'
    team_id = team_id_of(camp, db)
    deep = team_clusters.team_deep(camp, db, team_id)

    row = max(table['pairs'], key=lambda item: item['n'])
    hits = {tuple(sorted(hit['heroes'])): hit for hit in deep['kpl']['hits']
            if hit['kind'] == 'pair'}
    key = tuple(sorted(pair))
    assert key in hits
    hit = hits[key]
    assert hit['n'] == row['n'] and hit['wr'] == row['wr']
    assert hit['year'] == row['year']
    assert hit['teams'] == row['teams']
    assert hit['oppGames'] == 3
    assert hit['oppWins'] == 2                 # 三局里对手赢了两局
    assert hit['oppWinRate'] == pytest.approx(66.7)
    # 旧的 our* 字段已按契约改名为 opp*，不再出现
    assert 'ourGames' not in hit and 'ourWins' not in hit


def test_team_deep_kpl_lineup_hit_from_real_table(tmp_path):
    table = _kpl_file()
    if not table.get('lineups'):
        pytest.skip('KPL 表没有整阵容数据')
    row = max(table['lineups'], key=lambda item: item['n'])
    heroes = list(row['heroes'])
    assert len(heroes) == 5
    camp = tmp_path / 'camp_details'
    write_panels(camp, [('1', camp_panel('1', '11-02 12:00', opp_heroes=heroes))])
    db = tmp_path / 'db.sqlite3'
    team_id = team_id_of(camp, db)
    deep = team_clusters.team_deep(camp, db, team_id)

    lineup = deep['kpl']['lineup']
    assert sorted(lineup['heroes']) == sorted(heroes)
    assert lineup['n'] == row['n']
    assert lineup['oppGames'] == 1
    assert lineup['oppWins'] == 1              # 这一局对手赢
    assert 'ourGames' not in lineup


def test_kpl_section_reports_source_and_empty_when_no_hits(tmp_path):
    camp = tmp_path / 'camp_details'
    # 五个英雄都不在 KPL 组合表里（自定义占位名）→ 命中为空但结构完整
    heroes = ['不存在的英雄1', '不存在的英雄2', '不存在的英雄3',
              '不存在的英雄4', '不存在的英雄5']
    write_panels(camp, [('1', camp_panel('1', '11-02 12:00', opp_heroes=heroes))])
    db = tmp_path / 'db.sqlite3'
    team_id = team_id_of(camp, db)
    deep = team_clusters.team_deep(camp, db, team_id)

    kpl = deep['kpl']
    assert kpl['source'] == 'KPL 官方赛事'
    assert kpl['games'] and kpl['sinceYear']
    assert kpl['hits'] == []
    assert set(kpl['lineup']) >= {'heroes', 'n', 'wr', 'oppGames', 'oppWins'}
    assert kpl['lineup']['heroes'] == []
    assert kpl['lineup']['oppGames'] == 0


def test_taxonomy_and_meta_follow_contract(tmp_path):
    camp = tmp_path / 'camp_details'
    three_games(camp)
    db = tmp_path / 'db.sqlite3'
    team_id = team_id_of(camp, db)
    deep = team_clusters.team_deep(camp, db, team_id)

    taxonomy = deep['taxonomy']
    assert taxonomy['lanes'] == ['对抗路', '打野', '中路', '发育路', '游走']
    assert taxonomy['groups']['对抗路'] == ['战边', '坦边', '带线边']
    assert taxonomy['other'] == '其他'

    meta = deep['meta']
    assert meta['source'] == '营地终局面板'
    assert meta['days'] == 30
    assert meta['thresholds'] == {'sample': 3, 'quadrantShare': 0.5}
    assert meta['warnings'] == []
    assert len(meta['limits']) == 3
