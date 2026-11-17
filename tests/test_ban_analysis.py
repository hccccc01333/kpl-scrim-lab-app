"""双向 ban×英雄池、替代结构、池深度的口径测试。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ban_analysis  # noqa: E402


def pick(hero, lane, archetype):
    return {'name': hero, 'lane': lane, 'archetype': archetype}


def ban(hero, lane, archetype):
    return {'name': hero, 'lane': lane, 'archetype': archetype}


def game(seq, start, own_side, own_win, own_picks, enemy_picks, own_bans, enemy_bans,
         enemy_names=None):
    enemy_names = enemy_names or [f'对手{i}' for i in range(5)]
    return {
        'seq': seq, 'start': start, 'ownSide': own_side,
        'win': own_win, 'opponentWin': not own_win,
        'sides': {
            'own': {'picks': own_picks, 'bans': own_bans, 'players': []},
            'enemy': {'picks': enemy_picks, 'bans': enemy_bans,
                      'players': [{'name': name, 'lane': p['lane'], 'hero': p['name']}
                                  for name, p in zip(enemy_names, enemy_picks)]},
        },
    }


def make_games():
    games = []
    own_bans = [ban('瑶', '游走', '保护辅'), ban('盾山', '游走', '保护辅'),
                ban('海月', '中路', '法核'), ban('大乔', '游走', '功能辅'),
                ban('哪吒', '对抗路', '战边')]
    enemy_bans = [ban('墨子', '游走', '功能辅'), ban('扁鹊', '中路', '法核'),
                  ban('盾山', '游走', '保护辅'), ban('大乔', '游走', '功能辅'),
                  ban('张良', '中路', '工具人')]
    for index in range(6):
        own_picks = [
            pick('扁鹊' if index < 4 else '小乔', '中路', '法核'),
            pick('赵云', '打野', '战野'),
            pick('钟馗', '游走', '开团辅'),
            pick('百里守约', '发育路', '游射'),
            pick('吕布' if index < 3 else '白起', '对抗路', '战边' if index < 3 else '坦边'),
        ]
        enemy_picks = [
            pick('关羽', '对抗路', '战边'),
            pick('安琪拉', '中路', '法核'),
            pick('虞姬', '发育路', '呆射'),
            pick('娜可露露', '打野', '刺野'),
            pick('蔡文姬' if index < 2 else '朵莉亚', '游走', '保护辅'),
        ]
        games.append(game(str(index), f'11-0{index + 1} 12:00',
                          'blue' if index % 2 == 0 else 'red',
                          index < 4, own_picks, enemy_picks, own_bans, enemy_bans,
                          [f'边{index}', f'中{index}', f'射{index}', f'打{index}', f'辅{index}']))
    return games


def test_ban_matchup_rates_points_and_splits():
    block = ban_analysis.ban_matchup(make_games())
    their = block['theirBansVsOurPool']
    ours = block['ourBansVsTheirPool']

    assert block['games'] == 6
    assert len(their['points']) >= 5
    assert their['targeting']['banEvents'] == 30
    assert their['targeting']['pickEvents'] == 30
    top_heroes = {row['hero'] for row in their['targeting']['top']}
    assert '扁鹊' in top_heroes
    # 他们 ban 扁鹊 6 次（每局 1 次），命中我方 top5 里的 6 次。
    assert their['targeting']['hitEvents'] == 6
    assert their['targeting']['targetRate'] == 20.0
    assert their['targeting']['randomRate'] == round(
        sum(row['games'] for row in their['targeting']['top']) / 30 * 100, 1)
    assert their['targeting']['lift'] == round(
        their['targeting']['targetRate'] / their['targeting']['randomRate'], 2)

    # 他们 ban 墨子 6 次、扁鹊 6 次；分路事件共 30。
    lanes = {row['key']: row for row in their['laneDist']}
    assert lanes['游走']['games'] == 18
    assert lanes['中路']['games'] == 12
    assert sum(row['games'] for row in their['laneDist']) == 30

    # 我方蓝方 3 局、红方 3 局；两个时间段各 3 局。
    assert their['sideSplit']['blue']['games'] == 3
    assert their['sideSplit']['red']['games'] == 3
    assert their['periodSplit']['first']['games'] == 3
    assert their['periodSplit']['last']['games'] == 3

    # 镜像：我方 ban 瑶等 30 次；他们 top5 是安琪拉/虞姬/蔡文姬/朵莉亚/娜可露露？
    assert ours['targeting']['banEvents'] == 30
    assert ours['targeting']['hitEvents'] >= 0
    assert ours['laneDist']
    assert ours['typeDist']


def test_replacement_structure_same_lane_hhi_and_matrix():
    games = make_games()[:3]
    outcome = [{'hero': '瑶', 'games': 3, 'oppWins': 2, 'rate': 66.7, 'delta': 20.0,
                'wilson': [20.0, 90.0]}]
    block = ban_analysis.replacement_structure(games, outcome)
    row = next(item for item in block['rows'] if item['hero'] == '瑶')

    assert row['games'] == 3
    assert row['assigned'] == 3
    assert row['distinct'] == 2
    # 2 次蔡文姬 + 1 次朵莉亚：HHI=5/9，有效替代=1.8。
    assert row['effective'] == 1.8
    assert row['sameTypeRate'] == 100.0
    assert row['players'][0]['name'] == '辅0'
    assert row['playerCount'] == 3
    assert row['oppWinRate'] == 66.7
    assert block['matrix']['top'][0]['from'] == '保护辅'
    assert block['matrix']['top'][0]['to'] == '保护辅'
    # 瑶 + 盾山都是保护辅，3 局各一次 → 保护辅→保护辅 6 次。
    assert block['matrix']['top'][0]['games'] == 6


def test_pool_depth_effective_and_after_top1():
    games = make_games()[:3]
    block = ban_analysis.pool_depth(games)
    lanes = {row['lane']: row for row in block['lanes']}

    mid = lanes['中路']
    assert mid['games'] == 3
    assert mid['heroes'] == 1
    assert mid['effective'] == 1.0
    assert mid['top1']['hero'] == '安琪拉'
    assert mid['afterTop1']['heroes'] == 0
    assert mid['afterTop1']['effective'] is None

    support = lanes['游走']
    assert support['heroes'] == 2
    assert support['top1']['hero'] == '蔡文姬'
    assert support['top1']['games'] == 2
    assert support['backups'][0]['hero'] == '朵莉亚'
    assert support['afterTop1']['heroes'] == 1
