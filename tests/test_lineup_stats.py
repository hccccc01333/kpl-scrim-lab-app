"""lineup_stats 单元测试：五路签名、组合统计、Wilson 区间与展示分层口径。

口径见 docs/team_dossier_p0.md §2；「双核」不由能力标签派生；结果已知 <3 局不输出胜率。
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import lineup_stats as ls

HERO5 = {'对抗路': '吕布', '打野': '云缨', '中路': '貂蝉', '发育路': '艾琳', '游走': '张飞'}
TYPE5 = {'对抗路': '战边', '打野': '战野', '中路': '法刺', '发育路': '呆射', '游走': '保护辅'}


def _picks(hero=HERO5, types=None):
    types = types or TYPE5
    return [{'name': hero[lane], 'lane': lane, 'archetype': types[lane]}
            for lane in ls.LANES]


def _game(seq, win, picks, side='blue'):
    return {'seq': seq, 'win': win, 'side': side, 'picks': picks}


# ------------------------------------------------------------- Wilson 区间
def test_wilson_interval_basics():
    assert ls.wilson(0, 0) is None
    lo, hi = ls.wilson(6, 9)
    assert 30 <= lo <= 45 and 75 <= hi <= 95  # p=0.667, n=9 → 区间宽
    assert ls.wilson(10, 10)[0] > 60          # 全胜下界仍显著高于随机
    assert ls.wilson(0, 10)[1] < 40           # 全负上界显著低于随机
    for wins, games in ((1, 3), (7, 12), (0, 1)):
        lo, hi = ls.wilson(wins, games)
        assert 0 <= lo <= 100 and 0 <= hi <= 100 and lo <= hi


# ------------------------------------------------------------- 五路签名
def test_signature_lane_order_and_none_cases():
    sig = ls.signature_of(_picks())
    assert sig == tuple(TYPE5[lane] for lane in ls.LANES)
    # 分路缺失 / 重复 → None
    assert ls.signature_of(_picks()[:4]) is None
    dup = _picks()
    dup[1]['lane'] = '对抗路'
    assert ls.signature_of(dup) is None
    assert ls.signature_of([]) is None
    assert ls.signature_of(None) is None


def test_unknown_type_becomes_pending_marker():
    picks = _picks()
    picks[1]['archetype'] = '其他'          # 旧口径的「其他」统一按待分类处理
    sig = ls.signature_of(picks)
    assert sig[1] == '待分类'
    picks[2]['archetype'] = None
    assert ls.signature_of(picks)[2] == '待分类'


# ------------------------------------------------------------- 统计主表
def test_n_eff_unknown_and_incomplete_counts():
    games = [
        _game('a', True, _picks()),
        _game('b', False, _picks()),
        _game('c', None, _picks()),
        _game('d', True, _picks(types={**TYPE5, '打野': '待分类'})),
        _game('e', True, _picks()[:4]),   # 缺一路 → 无效局
    ]
    out = ls.team_lineups(games)
    assert out['nEff'] == 4
    assert out['nIncomplete'] == 1
    assert out['nUnknown'] == 1
    # 有效签名只有一行；unknownRow 汇总待分类局
    assert len(out['signature']) == 1
    assert out['signature'][0]['games'] == 3
    assert out['unknownRow']['games'] == 1 and out['unknownRow']['wins'] == 1
    assert out['unknownRow']['sigs'][0]['sig'] == list(
        tuple(TYPE5[l] if l != '打野' else '待分类' for l in ls.LANES))
    assert out['unknownRow']['sigKinds'] == 1


def test_wr_gate_requires_three_decided():
    games = [_game(f'g{i}', i == 0, _picks()) for i in range(2)]       # 1 胜 1 负
    out = ls.team_lineups(games)
    row = out['signature'][0]
    assert row['games'] == 2 and row['wr'] is None and row['wilson'] is None
    games.append(_game('g2', True, _picks()))
    row = ls.team_lineups(games)['signature'][0]
    assert row['wr'] == 66.7 and row['wilson'] is not None
    # 结果未知局只计场次，不影响胜率分母
    games.append(_game('g3', None, _picks()))
    row = ls.team_lineups(games)['signature'][0]
    assert row['games'] == 4 and row['wins'] + row['losses'] == 3
    assert row['wr'] == round(100 * 2 / 3, 1)


def test_pair_and_triad_exclusion_only_involved_lanes():
    # 对抗路待分类：边野组合不计，中野 / 射辅等其余家族照常累计
    picks = _picks(types={**TYPE5, '对抗路': '待分类'})
    out = ls.team_lineups([_game('a', True, picks)])
    families = {row['family'] for row in out['pairs']}
    assert '边野' not in families
    assert {'中野', '射辅', '中辅', '野辅'} <= families
    mid_jungle = next(r for r in out['pairs'] if r['family'] == '中野')
    assert mid_jungle['pair'] == ['战野', '法刺'] and mid_jungle['games'] == 1
    # 三人组合同理：涉对抗路的「边野辅 / 边中野」不计
    triad_families = {row['family'] for row in out['triads']}
    assert '边野辅' not in triad_families and '边中野' not in triad_families
    assert '中野辅' in triad_families


def test_signature_rows_exclude_pending_and_sort_by_games():
    other = {**HERO5, '打野': '韩信'}
    games = [
        _game('a', True, _picks()),
        _game('b', True, _picks()),
        _game('c', False, _picks(hero=other)),   # 换打野 → 同类型签名，不同英雄组
        _game('d', False, _picks(hero=other)),
        _game('e', True, _picks(types={**TYPE5, '中路': '工具人'})),
    ]
    out = ls.team_lineups(games)
    rows = out['signature']
    assert len(rows) == 2
    assert rows[0]['games'] == 4 and rows[1]['games'] == 1
    assert rows[0]['heroSets'] == [list(HERO5[l] for l in ls.LANES),
                                   list(other[l] for l in ls.LANES)]


def test_five_hero_rows_are_lane_ordered():
    # picks 乱序输入，输出英雄按固定分路序
    picks = list(reversed(_picks()))
    out = ls.team_lineups([_game('a', True, picks)])
    assert out['fiveHero'][0]['heroes'] == [HERO5[l] for l in ls.LANES]


def test_side_split():
    games = [_game('a', True, _picks(), side='blue'),
             _game('b', False, _picks(), side='red'),
             _game('c', True, _picks(), side=None)]
    out = ls.team_lineups(games)
    assert out['side']['blue'] == {'games': 1, 'wins': 1, 'losses': 0}
    assert out['side']['red'] == {'games': 1, 'wins': 0, 'losses': 1}
    assert out['side']['unknown']['games'] == 1


def test_function_tags_require_known_capabilities():
    # 五人能力全部收录 → 功能标签按 19 维规则派生；双核绝不出现
    caps5 = {'对抗路': '廉颇', '打野': '项羽', '中路': '王昭君', '发育路': '公孙离', '游走': '张飞'}
    types5 = {'对抗路': '坦边', '打野': '坦野', '中路': '工具人', '发育路': '游射', '游走': '保护辅'}
    picks = [{'name': caps5[l], 'lane': l, 'archetype': types5[l]} for l in ls.LANES]
    out = ls.team_lineups([_game('a', True, picks)])
    tags = out['functions'][0]['tags']
    assert '双前排' in tags and '强开团' in tags and '保护链' in tags
    assert '双核' not in tags
    # 含未收录英雄 → 不猜，功能标签为空
    mixed = _picks()
    mixed[0]['name'] = '不存在的英雄'
    out2 = ls.team_lineups([_game('b', True, mixed)])
    assert out2['functions'] == []


def test_empty_input_shape():
    out = ls.team_lineups([])
    # side 恒含 blue / red 两个桶（前端免判缺键）；unknown 只在有局时出现
    assert out == {'nEff': 0, 'nIncomplete': 0, 'nUnknown': 0, 'signature': [],
                   'unknownRow': {'games': 0, 'wins': 0, 'losses': 0, 'wr': None,
                                  'wilson': None, 'gamesRef': [], 'sigs': [], 'sigKinds': 0},
                   'pairs': [], 'triads': [], 'functions': [], 'fiveHero': [],
                   'side': {'blue': {'games': 0, 'wins': 0, 'losses': 0},
                            'red': {'games': 0, 'wins': 0, 'losses': 0}}}


# ------------------------------------------------------------- P2 资源对照
def _panel_players(gold=(1000, 2000, 3000, 2500, 1500),
                   dmg=(10, 20, 30, 30, 10), taken=(30, 20, 10, 20, 20)):
    return [{'lane': lane, 'gold': gold[i], 'heroDamage': dmg[i], 'taken': taken[i]}
            for i, lane in enumerate(ls.LANES)]


def test_lineup_resources_panel_subset_and_shares():
    picks = _picks()
    games = [
        {'seq': 'a', 'win': True, 'side': 'blue', 'picks': picks,
         'players': _panel_players(),
         'stats': {'gold': 10000, 'towers': 5, 'dragons': 2}, 'oppStats': {'gold': 9000}},
        {'seq': 'b', 'win': False, 'side': 'red', 'picks': picks},   # 无面板局：不计资源
    ]
    rows = ls.lineup_resources(games)
    assert len(rows) == 1
    row = rows[0]
    assert row['games'] == 2 and row['panelGames'] == 1
    assert row['lanes']['对抗路']['goldShare'] == 10.0          # 1000 / 10000
    assert sum((row['lanes'][l]['goldShare'] or 0) for l in ls.LANES) == pytest.approx(100.0)
    assert sum((row['lanes'][l]['dmgShare'] or 0) for l in ls.LANES) == pytest.approx(100.0)
    assert row['top1Share'] == 30.0                             # 打野 3000 / 10000
    assert row['towers'] == 5.0 and row['dragons'] == 2.0
    assert row['goldDiff'] == 1000.0                            # 10000 − 9000
    assert row['wr'] is None                                    # 结果已知 2 局 <3 不给胜率
    assert row['gamesRef'] == ['a', 'b']


def test_lineup_resources_excludes_pending_and_empty():
    players = _panel_players()
    pending = _picks(types={**TYPE5, '打野': '待分类'})
    assert ls.lineup_resources([{'seq': 'c', 'win': True, 'picks': pending,
                                 'players': players}]) == []
    assert ls.lineup_resources([]) == []


def test_lineup_resources_missing_values_not_zero_filled():
    players = _panel_players()
    players[4]['gold'] = None                                   # 游走缺经济
    games = [{'seq': 'a', 'win': True, 'picks': _picks(), 'players': players,
              'stats': {'towers': None, 'dragons': None}, 'oppStats': {}}]
    row = ls.lineup_resources(games)[0]
    assert row['lanes']['游走']['goldShare'] is None
    # 其余四路按已知值归一
    assert sum((row['lanes'][l]['goldShare'] or 0) for l in ls.LANES) == pytest.approx(100.0)
    assert row['towers'] is None and row['goldDiff'] is None


# ------------------------------------------------------------- P2 对抗矩阵
SIG_A = tuple(TYPE5[l] for l in ls.LANES)
SIG_X = ('坦边', '坦野', '法刺', '呆射', '保护辅')
SIG_Y = ('战边', '战野', '工具人', '呆射', '保护辅')


def test_matchup_matrix_levels_and_baseline():
    picks_a = _picks()
    picks_x = _picks(types=dict(zip(ls.LANES, SIG_X)))
    picks_y = _picks(types=dict(zip(ls.LANES, SIG_Y)))
    games = [{'seq': f'x{i}', 'win': i < 2, 'side': 'blue', 'picks': picks_a,
              'oppPicks': picks_x} for i in range(3)]
    games.append({'seq': 'y0', 'win': False, 'side': 'red', 'picks': picks_a,
                  'oppPicks': picks_y})
    out = ls.matchup_matrix(games)
    ax = next(c for c in out['cells'] if tuple(c['col']) == SIG_X)
    assert ax['n'] == 3 and ax['wins'] == 2 and ax['losses'] == 1
    assert ax['wr'] == 66.7 and ax['evidenceLevel'] == 'initial'   # n<10 只算初步观察
    # 基准 = A 体系对全体对手：4 局 2 胜 → 50.0；diff = +16.7
    assert ax['baseline'] == 50.0 and ax['baselineDiff'] == 16.7
    ay = next(c for c in out['cells'] if tuple(c['col']) == SIG_Y)
    assert ay['n'] == 1 and ay['wr'] is None and ay['evidenceLevel'] == 'insufficient'
    assert out['rowBaselines'][0]['games'] == 4 and out['rowBaselines'][0]['wr'] == 50.0


def test_matchup_matrix_established_requires_clean_interval():
    picks_a = _picks()
    picks_x = _picks(types=dict(zip(ls.LANES, SIG_X)))
    picks_y = _picks(types=dict(zip(ls.LANES, SIG_Y)))
    games = [{'seq': str(i), 'win': True, 'side': 'blue', 'picks': picks_a,
              'oppPicks': picks_x} for i in range(10)]
    # 全胜且基准同为 100% → 区间跨基准 → 只算初步观察（胜率 100 的下界 ~72 < 基准 100）
    out = ls.matchup_matrix(games)
    cell = out['cells'][0]
    assert cell['n'] == 10 and cell['wr'] == 100.0
    assert cell['baseline'] == 100.0 and cell['evidenceLevel'] == 'initial'
    # 加 4 场对其他对手的败局，基准拉低到 71.4 → 100% 胜率下界 72.2 高于基准 → 倾向性发现
    games += [{'seq': f'y{i}', 'win': False, 'side': 'red', 'picks': picks_a,
               'oppPicks': picks_y} for i in range(4)]
    out = ls.matchup_matrix(games)
    ax = next(c for c in out['cells'] if len(c['gamesRef']) == 10)
    assert ax['baseline'] == 71.4 and ax['baselineDiff'] == 28.6
    assert ax['evidenceLevel'] == 'established'


def test_matchup_matrix_skips_pending_and_splits_side():
    picks_a = _picks()
    pending = _picks(types={**TYPE5, '打野': '待分类'})
    games = [{'seq': 'p1', 'win': True, 'side': 'blue', 'picks': picks_a, 'oppPicks': pending},
             {'seq': 'p2', 'win': False, 'side': 'red', 'picks': pending, 'oppPicks': picks_a}]
    assert ls.matchup_matrix(games)['cells'] == []
    games_ok = [{'seq': 's1', 'win': True, 'side': 'blue', 'picks': picks_a,
                 'oppPicks': _picks(types=dict(zip(ls.LANES, SIG_X)))},
                {'seq': 's2', 'win': False, 'side': 'red', 'picks': picks_a,
                 'oppPicks': _picks(types=dict(zip(ls.LANES, SIG_X)))}]
    out = ls.matchup_matrix(games_ok)
    cell = out['cells'][0]
    assert cell['side']['blue'] == {'games': 1, 'wins': 1}
    assert cell['side']['red'] == {'games': 1, 'wins': 0}
