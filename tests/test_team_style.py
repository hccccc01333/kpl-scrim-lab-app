"""团队风格四象限：分位数、x/y、象限分界、时间窗与缺字段降级。"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import team_clusters  # noqa: E402
import team_style  # noqa: E402

# 营地 battleRecords.position：0=对抗路 1=中路 2=发育路 3=打野 4=游走
OWN_HEROES = ['夏侯惇', '张良', '公孙离', '澜', '张飞']
ENEMY_HEROES = ['吕布', '西施', '马可波罗', '镜', '牛魔']
OWN_IDS = [f'own{i}' for i in range(5)]
ENEMY_IDS = [f'enemy{i}' for i in range(5)]


def roster(ids, heroes, golds, kills=2, deaths=2, assists=4, towers=1):
    rows = []
    for index, (pid, hero, gold) in enumerate(zip(ids, heroes, golds)):
        rows.append({
            'id': pid, 'name': f'选手{pid}', 'hero': hero, 'lane': '',
            'kills': kills, 'deaths': deaths, 'assists': assists, 'gold': gold,
            'damage': gold * 2, 'heroDamage': gold * 2, 'taken': gold,
            'control': 10, 'heal': 100, 'participation': 0.6, 'towers': towers,
        })
    return rows


def team_json(rows, dragons=(1, 0, 0, 0, 0), win=True):
    stats = {
        'killCnt': sum(row['kills'] for row in rows),
        'deadCnt': sum(row['deaths'] for row in rows),
        'assistCnt': sum(row['assists'] for row in rows),
        'money': sum(row['gold'] for row in rows),
        'towerCnt': sum(row['towers'] for row in rows),
        'gameResult': win,
    }
    for key, value in zip(team_clusters.DRAGON_KEYS, dragons):
        stats[key] = value
    return stats


def role_entry(pid, name, hero, position, gold, kills=2, deaths=2, assists=4, towers=1):
    return {
        'basicInfo': {'playerId': pid, 'roleName': name},
        'battleRecords': {'usedHero': {'heroName': hero}, 'position': position},
        'battleStats': {'killCnt': kills, 'deadCnt': deaths, 'assistCnt': assists,
                        'money': gold, 'towerCnt': towers, 'gradeGame': '8.0'},
    }


def camp_panel(seq, start, own_golds, enemy_golds=None, *, duration=900, win=True,
               own_camp=1, dragons=(1, 0, 0, 0, 0), own_kills=None, own_assists=None,
               own_towers=None, enemy_kills=None, enemy_assists=None, enemy_towers=None):
    """合成一份营地详情 JSON：十人面板 + blueTeam/redTeam 的终局合计。"""
    enemy_golds = enemy_golds or [7000, 7100, 7200, 7300, 7400]
    own_rows = [{'id': pid, 'name': f'我方{i}', 'hero': OWN_HEROES[i], 'lane': '',
                 'kills': 2, 'deaths': 2, 'assists': 4, 'gold': gold, 'towers': 1}
                for i, (pid, gold) in enumerate(zip(OWN_IDS, own_golds))]
    enemy_rows = [{'id': pid, 'name': f'对手{i}', 'hero': ENEMY_HEROES[i], 'lane': '',
                   'kills': 2, 'deaths': 2, 'assists': 4, 'gold': gold, 'towers': 1}
                  for i, (pid, gold) in enumerate(zip(ENEMY_IDS, enemy_golds))]
    own_team = team_json(own_rows, dragons=dragons, win=win)
    enemy_team = team_json(enemy_rows, dragons=dragons, win=not win)
    if own_kills is not None:
        own_team['killCnt'] = own_kills
    if own_assists is not None:
        own_team['assistCnt'] = own_assists
    if own_towers is not None:
        own_team['towerCnt'] = own_towers
    if enemy_kills is not None:
        enemy_team['killCnt'] = enemy_kills
    if enemy_assists is not None:
        enemy_team['assistCnt'] = enemy_assists
    if enemy_towers is not None:
        enemy_team['towerCnt'] = enemy_towers
    own_roles = [role_entry(pid, f'我方{i}', OWN_HEROES[i], i, gold)
                 for i, (pid, gold) in enumerate(zip(OWN_IDS, own_golds))]
    enemy_roles = [role_entry(pid, f'对手{i}', ENEMY_HEROES[i], i, gold)
                   for i, (pid, gold) in enumerate(zip(ENEMY_IDS, enemy_golds))]
    blue_roles, red_roles = (own_roles, enemy_roles) if own_camp == 1 else (enemy_roles, own_roles)
    blue_team, red_team = ((own_team, enemy_team) if own_camp == 1
                           else (enemy_team, own_team))
    return {'data': {
        'head': {'acntCamp': own_camp, 'gameResult': win},
        'battle': {'startTime': start, 'usedTime': duration, 'mapName': '王者峡谷'},
        'blueTeam': blue_team, 'redTeam': red_team,
        'blueRoles': blue_roles, 'redRoles': red_roles,
    }}


def write_panels(directory, items):
    directory.mkdir(parents=True, exist_ok=True)
    for seq, payload in items:
        (directory / f'{seq}.json').write_text(json.dumps(payload, ensure_ascii=False),
                                               encoding='utf-8')


def load(directory):
    return team_clusters.load_panels(directory)


# ---------------------------------------------------------------- 面板解析
def test_load_panels_carries_team_totals(tmp_path):
    write_panels(tmp_path / 'camp_details', [
        ('1', camp_panel('1', '11-02 12:00', [7000, 7000, 8000, 9000, 6000],
                         dragons=(1, 1, 0, 1, 0), win=True)),
    ])
    panel = load(tmp_path / 'camp_details')[0]
    own, enemy = panel['own_stats'], panel['enemy_stats']
    # 队伍口径来自 blueTeam / redTeam，不是十人面板硬求和
    assert own['kills'] == 10 and own['gold'] == 37000
    assert own['dragons'] == 3          # 5 个龙字段之和
    assert own['win'] is True
    assert enemy['win'] is False
    assert own['towers'] == 5


def test_load_panels_degrades_when_team_json_missing(tmp_path):
    payload = camp_panel('1', '11-02 12:00', [7000, 7000, 7000, 7000, 7000])
    del payload['data']['blueTeam']
    del payload['data']['redTeam']
    write_panels(tmp_path / 'camp_details', [('1', payload)])
    panel = load(tmp_path / 'camp_details')[0]
    # 缺队伍合计时退回十人面板：控龙没有来源，留 None，不拿 0 冒充
    assert panel['own_stats']['kills'] == 10
    assert panel['own_stats']['dragons'] is None
    assert panel['enemy_stats']['win'] is False


# ---------------------------------------------------------------- 分位数与点位
def test_top1_share_and_x_follow_pool_quantiles():
    shares = [20, 20, 20, 25, 30, 30]          # 六条「队-局」，含我方与对手两个方向
    records = []
    for index, share in enumerate(shares):
        rest_gold = (100 - share) * 100 // 4
        rows = roster([f'p{index}{i}' for i in range(5)], OWN_HEROES,
                      [share * 100] + [rest_gold] * 4)
        rows[0]['lane'] = '发育路'
        records.append(team_style._record(
            str(index), 'enemy', None, 900, rows,
            {'kills': 10, 'assists': 10, 'towers': 5, 'dragons': 1,
             'gold': 10000, 'win': True}, 0))
    thresholds = team_style._thresholds(records)
    pool = team_style._public_pool(records, thresholds)
    low, high = thresholds['top1']
    assert pool['n'] == len(shares)
    assert set(pool) == {'n', 'top1', 'note'}
    assert low < high
    for record in records:
        style = team_style.game_style(record, thresholds)
        expected = max(0.0, min(100.0, 100 * (high - record['top1Share']) / (high - low)))
        assert style['x'] == pytest.approx(round(expected, 1))
        # 经济第一取占比最高的那一路（并列时取第一个）
        assert style['top1']['share'] == record['top1Share']
        assert style['top1']['lane'] == '发育路'


def test_y_balances_fight_and_macro_percentile():
    thresholds = {'top1': [22.0, 24.0], 'fight': [1.0, 2.0, 3.0],
                  'macro': [0.1, 0.2, 0.3]}
    base = {'top1': {'name': 'a', 'lane': '发育路'}, 'top1Share': 23.0,
            'towers': 5, 'dragons': 2, 'goldDiff': 100}
    # 打架最高、运营最低 → y 明显偏打架
    fight_only = team_style.game_style(
        {**base, 'fightPerMin': 3.0, 'macroPerMin': 0.1}, thresholds)
    assert fight_only['y'] == pytest.approx(50 + (100 - 100 / 3) / 2, abs=0.1)
    # 两项都在中间 → y 落在 50 附近（不会被单项拉满）
    balanced = team_style.game_style(
        {**base, 'fightPerMin': 2.0, 'macroPerMin': 0.2}, thresholds)
    assert balanced['y'] == pytest.approx(50.0)
    # 运营最高、打架最低 → y 明显偏运营
    macro_only = team_style.game_style(
        {**base, 'fightPerMin': 1.0, 'macroPerMin': 0.3}, thresholds)
    assert macro_only['y'] == pytest.approx(50 + (100 / 3 - 100) / 2, abs=0.1)
    # 缺 minutes / 击杀助攻 / 推塔控龙 → y 为 None（证据不足），不拿 0 冒充
    missing = team_style.game_style(
        {**base, 'fightPerMin': None, 'macroPerMin': None}, thresholds)
    assert missing['y'] is None and missing['quadrant'] is None


def test_flat_pool_falls_back_to_midline():
    # 全池没有差异（单局/同质样本）时不硬拉边，落在中线；缺占比仍然 None
    thresholds = {'top1': [23.0, 23.0], 'fight': [2.0], 'macro': [0.5]}
    record = {'top1': {'name': 'a', 'lane': '发育路'}, 'top1Share': 23.0,
              'fightPerMin': 2.0, 'macroPerMin': 0.5, 'towers': 5, 'dragons': 1}
    style = team_style.game_style(record, thresholds)
    assert style['x'] == 50.0 and style['y'] == 50.0
    assert style['quadrant'] == '多点进攻'

    blank = team_style.game_style({**record, 'top1Share': None}, thresholds)
    assert blank['x'] is None and blank['y'] == 50.0


def test_quadrant_boundaries():
    assert team_style.quadrant_of(0.0, 50.0) == '单核进攻'
    assert team_style.quadrant_of(49.9, 50.0) == '单核进攻'
    assert team_style.quadrant_of(50.0, 50.0) == '多点进攻'
    assert team_style.quadrant_of(100.0, 100.0) == '多点进攻'
    assert team_style.quadrant_of(49.9, 49.9) == '保核运营'
    assert team_style.quadrant_of(50.0, 49.9) == '多线牵制'
    assert team_style.quadrant_of(None, 50.0) is None
    assert team_style.quadrant_of(50.0, None) is None


def test_x_clamps_at_edges():
    thresholds = {'top1': [22.0, 24.0], 'fight': [1.0], 'macro': [1.0]}
    tight = {'top1': {'name': '', 'lane': ''}, 'top1Share': 10.0,
             'fightPerMin': 1.0, 'macroPerMin': 1.0}
    assert team_style.game_style(tight, thresholds)['x'] == 100.0
    loose = {**tight, 'top1Share': 40.0}
    assert team_style.game_style(loose, thresholds)['x'] == 0.0


# ---------------------------------------------------------------- 时间窗与缺口
def test_windows_anchor_on_team_latest_game(tmp_path):
    write_panels(tmp_path / 'camp_details', [
        ('1', camp_panel('1', '09-01 12:00', [7000, 7000, 8000, 9000, 6000])),
        ('2', camp_panel('2', '11-01 12:00', [7000, 7000, 8000, 9000, 6000])),
        ('3', camp_panel('3', '11-10 12:00', [7000, 7000, 8000, 9000, 6000])),
        ('4', camp_panel('4', '11-20 12:00', [7000, 7000, 8000, 9000, 6000])),
    ])
    panels = load(tmp_path / 'camp_details')
    index = team_style.build_index(panels)
    records = [index['enemy'][panel['seq']] for panel in panels]
    style = team_style.style(records, index)

    assert style['games'] == 4
    assert style['anchor'] == '11-20'       # 锚点是该队最近一局，不是今天
    assert style['windows']['7']['games'] == 1
    assert style['windows']['15']['games'] == 2
    assert style['windows']['30']['games'] == 3
    assert style['windows']['all']['games'] == 4
    assert style['windows']['all']['sufficient'] is True
    assert style['windows']['15']['sufficient'] is False


def test_seven_day_window_is_anchor_minus_six(tmp_path):
    # 「最近 7 天」含锚点共 7 个自然日：11-14（anchor-6）算、11-13（anchor-7）不算
    items = [(str(index), camp_panel(str(index), f'{day} 12:00',
                                    [7000, 7000, 7000, 7000, 7000]))
             for index, day in enumerate(('11-13', '11-14', '11-20'), 1)]
    write_panels(tmp_path / 'camp_details', items)
    panels = load(tmp_path / 'camp_details')
    index = team_style.build_index(panels)
    records = [index['enemy'][panel['seq']] for panel in panels]
    style = team_style.style(records, index)

    assert style['anchor'] == '11-20'
    assert style['windows']['7']['games'] == 2
    assert style['windows']['15']['games'] == 3


def test_quadrant_needs_sample_and_half_share(tmp_path):    # 三局同型号：打架多、推塔少 → 同一个象限；样本不足两局时不给结论
    items = []
    for index, (day, hour) in enumerate((('11-02', 12), ('11-03', 13), ('11-04', 14)), 1):
        items.append((str(index), camp_panel(
            str(index), f'{day} {hour}:00', [9000, 5000, 5000, 5000, 5000],
            [6400, 6400, 6400, 6400, 6400],
            own_kills=2, own_assists=2, own_towers=8,
            enemy_kills=40, enemy_assists=50, enemy_towers=0)))
    write_panels(tmp_path / 'camp_details', items)
    panels = load(tmp_path / 'camp_details')
    index = team_style.build_index(panels)
    records = [index['enemy'][panel['seq']] for panel in panels]

    full = team_style.style(records, index)
    assert full['windows']['all']['games'] == 3
    assert full['windows']['all']['quadrant'] == '多点进攻'
    assert full['main']['quadrant'] == '多点进攻'

    thin = team_style.style(records[:2], index)
    assert thin['windows']['all']['sufficient'] is False
    assert thin['windows']['all']['quadrant'] is None
    assert thin['main']['quadrant'] is None


def test_main_prefers_30_day_window(tmp_path):
    write_panels(tmp_path / 'camp_details', [
        ('1', camp_panel('1', '08-01 12:00', [6000, 6000, 6000, 6000, 6000])),
        ('2', camp_panel('2', '11-02 12:00', [6000, 6000, 6000, 6000, 6000])),
        ('3', camp_panel('3', '11-03 12:00', [6000, 6000, 6000, 6000, 6000])),
        ('4', camp_panel('4', '11-04 12:00', [6000, 6000, 6000, 6000, 6000])),
    ])
    panels = load(tmp_path / 'camp_details')
    index = team_style.build_index(panels)
    records = [index['enemy'][panel['seq']] for panel in panels]
    style = team_style.style(records, index)

    assert style['windows']['30']['games'] == 3
    assert style['windows']['all']['games'] == 4
    assert style['main']['sufficient'] is True
    assert style['main']['quadrant'] == style['windows']['30']['quadrant']
    assert style['main']['x'] == style['windows']['30']['x']
    assert style['main']['y'] == style['windows']['30']['y']


def test_missing_team_totals_keep_point_null(tmp_path):
    payload = camp_panel('1', '11-02 12:00', [7000, 7000, 8000, 9000, 6000])
    del payload['data']['blueTeam']
    del payload['data']['redTeam']
    write_panels(tmp_path / 'camp_details', [('1', payload)])
    panels = load(tmp_path / 'camp_details')
    index = team_style.build_index(panels)
    record = index['enemy']['1']
    assert record['macroPerMin'] is None          # 控龙没有来源 → 不给 0
    assert record['fightPerMin'] is not None      # 击杀/助攻/分钟仍可算
    style = team_style.game_style(record, index['thresholds'])
    assert style['y'] is None and style['quadrant'] is None
    assert style['x'] is not None                 # 经济占比仍可算
    assert any('证据' in item or '时间轴' in item for item in style['missing'])
    assert style['evidence']


def test_list_teams_exposes_style_for_teams_and_own(tmp_path):
    write_panels(tmp_path / 'camp_details', [
        ('1', camp_panel('1', '11-02 12:00', [7000, 7000, 8000, 9000, 6000])),
        ('2', camp_panel('2', '11-03 12:00', [7000, 7000, 8000, 9000, 6000], win=False)),
    ])
    result = team_clusters.list_teams(tmp_path / 'camp_details', tmp_path / 'db.sqlite3', '本队')
    for holder in (result['teams'][0], result['own']):
        style = holder['style']
        assert set(style['windows']) == {'7', '15', '30', 'all'}
        assert style['anchor'] == '11-03'
        assert style['pool']['n'] == 4             # 2 局 × 双向
        assert set(style['pool']) == {'n', 'top1', 'note'}
        assert set(style['main']) == {'quadrant', 'share', 'x', 'y', 'sufficient'}
        assert style['windows']['all']['games'] == 2
    # 既有字段一个不少
    assert result['teams'][0]['matches'] == 2
    assert result['summary']['games'] == 2


def test_resolve_days_handles_cross_year():
    days = team_style.resolve_days([
        '2025-12-20 12:00', '2026-01-05 19:00', '12-25 10:00', '01-02 09:00'])
    assert days['2025-12-20 12:00'].year == 2025
    assert days['2026-01-05 19:00'].year == 2026
    # 无年份：补到不晚于参考日期的最近一年（12-25 在 2025，01-02 在 2026）
    assert days['12-25 10:00'].year == 2025
    assert days['01-02 09:00'].year == 2026


def test_parse_start_accepts_both_formats():
    first = team_style.parse_start('11-04 20:15')
    assert (first['month'], first['day'], first['hour'], first['minute']) == (11, 4, 20, 15)
    second = team_style.parse_start('2026-11-04 20:15')
    assert second['year'] == 2026 and second['month'] == 11
    assert team_style.parse_start('') is None
