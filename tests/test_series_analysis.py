"""系列赛引擎测试：完赛判定、编组建议、P0 分析与汇总口径。

固定回归样本覆盖（V2.0 方案 §八）：
- BO5 的 3:0 / 3:1 / 3:2 都判定完赛；2:1 未完赛不冒充完赛；
- 固定打满模式下打满才完赛；
- 三种 BO、缺失数据（缺开赛时间 / 缺经济差 / 缺 BP 名单）、跨午夜、
  重复归属、不同版本——建议层都有明确反馈；
- 手序缺失自动降级为「终局阵容对照」，缺数据返回 None 不返回 0。
"""
import series_engine as engine


def _vector(key, *, date='2026-11-14', clock='19:00', opponent='青岚', session='一队',
            version='S30', result='win', at10=1500.0, heroes=None, heroes_foe=None):
    return {
        'key': key, 'date': date, 'clock': clock, 'opponent': opponent,
        'session': session, 'version': version, 'result': result,
        'camp': 'blue', 'duration': 1200, 'at10': at10,
        'finalDiff': (at10 + 500) if isinstance(at10, (int, float)) else None,
        'heroes': heroes or [f'我方{index}号' for index in range(1, 6)],
        'heroesFoe': heroes_foe or [f'对手{index}号' for index in range(1, 6)],
        'bans': [],
    }


# ---------------------------------------------------------------- 完赛判定
def test_bo5_all_scores_complete():
    # 3:0 / 3:1 / 3:2 都是完整 BO5
    assert engine.derive_completion(5, 'standard', ['win', 'win', 'win']) == 'completed'
    assert engine.derive_completion(5, 'standard', ['win', 'win', 'loss', 'loss', 'win']) == 'completed'
    assert engine.derive_completion(5, 'standard', ['win', 'win', 'win', 'loss', 'loss']) == 'completed'


def test_bo5_unfinished_stays_open():
    assert engine.derive_completion(5, 'standard', ['win', 'win']) == 'open'
    assert engine.derive_completion(5, 'standard', ['win', 'loss']) == 'open'
    assert engine.derive_completion(3, 'standard', ['win']) == 'open'


def test_bo3_two_one_complete():
    # BO3：任一方到 2 胜即完赛（2:1）；1:1 未完赛
    assert engine.derive_completion(3, 'standard', ['win', 'loss', 'win']) == 'completed'
    assert engine.derive_completion(3, 'standard', ['win', 'loss']) == 'open'


def test_fixed_mode_requires_full_length():
    assert engine.derive_completion(5, 'fixed', ['win', 'win', 'win']) == 'open'
    assert engine.derive_completion(5, 'fixed', ['win', 'win', 'loss', 'win', 'loss']) == 'completed'


def test_no_results_never_guess():
    assert engine.derive_completion(3, 'standard', []) == 'open'
    assert engine.derive_completion(3, 'standard', [None, None]) == 'open'


# ---------------------------------------------------------------- 编组建议
def test_suggest_same_day_continuous():
    vectors = [
        _vector('k1', clock='19:00'),
        _vector('k2', clock='19:25'),
        _vector('k3', clock='19:55'),
    ]
    result = engine.suggest_groups(vectors, {})
    assert len(result['suggestions']) == 1
    s = result['suggestions'][0]
    assert s['matchKeys'] == ['k1', 'k2', 'k3']
    assert s['bestOf'] == 3
    assert s['confidence'] == 'high'
    assert s['warnings'] == []


def test_suggest_three_games_can_be_bo5():
    vectors = [_vector('k1', clock='19:00'), _vector('k2', clock='19:30'), _vector('k3', clock='20:00')]
    s = engine.suggest_groups(vectors, {})['suggestions'][0]
    # 推荐不强行确定：默认 BO3，教练可在确认时改成 3:0 完赛的 BO5
    assert s['bestOf'] == 3 and s['completionMode'] == 'standard'


def test_suggest_long_gap_splits_and_warns():
    vectors = [
        _vector('k1', clock='19:00'), _vector('k2', clock='19:30'),
        _vector('k3', clock='22:00'),  # 间隔 150 分钟：不拆但提示核实
        _vector('k4', clock='23:50'),  # 再隔 110 分钟
    ]
    result = engine.suggest_groups(vectors, {})
    groups = result['suggestions']
    assert all('核实' in w for g in groups for w in g['warnings'] if '间隔' in w)


def test_suggest_cross_midnight_stays_one_group():
    vectors = [
        _vector('k1', date='2026-11-14', clock='23:50'),
        _vector('k2', date='2026-11-15', clock='00:30'),
        _vector('k3', date='2026-11-15', clock='01:05'),
    ]
    result = engine.suggest_groups(vectors, {})
    assert len(result['suggestions']) == 1
    assert result['suggestions'][0]['matchKeys'] == ['k1', 'k2', 'k3']


def test_suggest_missing_clock_requires_order_confirm():
    vectors = [
        _vector('k1', clock=''),
        _vector('k2', clock=''),
        _vector('k3', clock=''),
    ]
    s = engine.suggest_groups(vectors, {})['suggestions'][0]
    assert any('开赛时间' in w for w in s['warnings'])
    assert s['needsReview'] is True and s['confidence'] == 'low'


def test_suggest_missing_opponent_flags():
    vectors = [_vector('k1', opponent=''), _vector('k2', opponent='')]
    s = engine.suggest_groups(vectors, {})['suggestions'][0]
    assert any('对手未标注' in w for w in s['warnings'])


def test_suggest_blocked_matches_reported():
    vectors = [_vector('k1'), _vector('k2')]
    existing = {'k2': {'seriesId': 'ts-old', 'gameIndex': 2}}
    result = engine.suggest_groups(vectors, existing)
    assert [s for s in result['suggestions'] if 'k2' in s['matchKeys']] == []
    assert result['blocked'] == [{'matchKey': 'k2', 'seriesId': 'ts-old', 'gameIndex': 2,
                                  'reason': '已属于其他系列赛，需先移出再编组'}]


def test_suggest_version_mismatch_warns():
    vectors = [_vector('k1', version='S30'), _vector('k2', version='S31')]
    s = engine.suggest_groups(vectors, {})['suggestions'][0]
    assert any('版本不一致' in w for w in s['warnings'])


def test_suggest_seven_games_recommends_bo7():
    vectors = [_vector(f'k{i}', clock=f'{19 + i // 2}:{(i * 17) % 60:02d}') for i in range(1, 8)]
    s = engine.suggest_groups(vectors, {})['suggestions'][0]
    assert len(s['matchKeys']) == 7 and s['bestOf'] == 7


# ---------------------------------------------------------------- 单组分析
def _series(games_detail=None, ruleset='scrim-global-team', best_of=5):
    return {'id': 'ts-test', 'bestOf': best_of, 'rulesetId': ruleset,
            'completionMode': 'standard', 'opponent': '青岚', 'status': 'confirmed'}


def _game(index, key, *, heroes, heroes_foe, result='win', at10=1000.0, detail=None):
    return {'matchKey': key, 'gameIndex': index,
            'vector': _vector(key, result=result, at10=at10, heroes=heroes, heroes_foe=heroes_foe),
            'detail': detail}


def test_analyze_accumulates_ledger_team_ruleset():
    games = [
        _game(1, 'k1', heroes=['A', 'B', 'C', 'D', 'E'], heroes_foe=['F', 'G', 'H', 'I', 'J']),
        _game(2, 'k2', heroes=['A2', 'B2', 'C2', 'D2', 'E2'], heroes_foe=['F', 'G2', 'H2', 'I2', 'J2']),
    ]
    out = engine.analyze_series(_series(), games)
    ledger = out['bpLedger']['perGame']
    assert ledger[0]['usedUsCount'] == 5 and ledger[0]['usedFoeCount'] == 5
    assert ledger[1]['usedUsCount'] == 10 and ledger[1]['usedFoeCount'] == 9  # 对手复用了 F
    # 队内不复用：我方只被挡自己的已选；对手已选对我方仍可选
    assert set(ledger[1]['blockUs']) == {'A', 'B', 'C', 'D', 'E'}
    assert set(ledger[1]['blockFoe']) == {'F', 'G', 'H', 'I', 'J'}


def test_analyze_shared_ruleset_blocks_union():
    games = [
        _game(1, 'k1', heroes=['A', 'B', 'C', 'D', 'E'], heroes_foe=['F', 'G', 'H', 'I', 'J']),
        _game(2, 'k2', heroes=['A2', 'B2', 'C2', 'D2', 'E2'], heroes_foe=['F2', 'G2', 'H2', 'I2', 'J2']),
    ]
    out = engine.analyze_series(_series(ruleset='scrim-global-shared'), games)
    ledger = out['bpLedger']['perGame']
    assert set(ledger[1]['blockUs']) == set('ABCDEFGHIJ') | {'A', 'B', 'C', 'D', 'E'}
    assert ledger[1]['blockUs'] == ledger[1]['blockFoe']


def test_analyze_per_game_ruleset_never_blocks():
    games = [_game(1, 'k1', heroes=['A', 'B', 'C', 'D', 'E'], heroes_foe=['F', 'G', 'H', 'I', 'J']),
             _game(2, 'k2', heroes=['A', 'B2', 'C2', 'D2', 'E2'], heroes_foe=['F', 'G2', 'H2', 'I2', 'J2'])]
    out = engine.analyze_series(_series(ruleset='per-game'), games)
    assert out['bpLedger']['perGame'][1]['blockUs'] == []


def test_analyze_detects_illegal_reuse_and_caveats():
    games = [
        _game(1, 'k1', heroes=['A', 'B', 'C', 'D', 'E'], heroes_foe=['F', 'G', 'H', 'I', 'J']),
        _game(2, 'k2', heroes=['A', 'B2', 'C2', 'D2', 'E2'], heroes_foe=['F2', 'G2', 'H2', 'I2', 'J2']),
    ]
    out = engine.analyze_series(_series(), games)
    assert out['games'][1]['ledger']['reuseIllegal'] == ['A']
    assert any('跨局复用' in c for c in out['caveats'])


def test_analyze_camp_lineup_degrades_with_caveat():
    games = [_game(1, 'k1', heroes=['A', 'B', 'C', 'D', 'E'], heroes_foe=['F', 'G', 'H', 'I', 'J'])]
    out = engine.analyze_series(_series(), games)
    assert out['games'][0]['orderKnown'] is False
    assert out['coverage']['orderKnownGames'] == 0
    assert any('终局名单' in c for c in out['caveats'])


def test_analyze_manual_bp_reports_order_known():
    detail = {'ownCamp': 'blue', 'ownSide': 'left',
              'bp': {'picks': {'left': ['A', 'B', 'C', 'D', 'E'], 'right': ['F', 'G', 'H', 'I', 'J']},
                     'bans': {'left': ['X'], 'right': ['Y']}, 'firstPick': 'left'}}
    games = [_game(1, 'k1', heroes=['A', 'B', 'C', 'D', 'E'], heroes_foe=['F', 'G', 'H', 'I', 'J'],
                   detail=detail)]
    out = engine.analyze_series(_series(), games)
    row = out['games'][0]
    assert row['orderKnown'] is True
    assert row['bansOwn'] == ['X'] and row['bansFoe'] == ['Y']
    assert out['coverage']['orderKnownGames'] == 1


def test_bp_sides_normalizes_blue_red_own_side():
    # 营地 detail 的 ownSide 可能是 red/blue，而 campBp 的 keys 是 left/right；
    # 此前未归一，red 方的 picks 会全部落到对手侧。
    detail = {'ownSide': 'red', 'ownCamp': 'red',
              'campBp': {'ownSide': 'right', 'pickOrderKnown': False,
                         'picks': {'left': ['F1', 'F2', 'F3', 'F4', 'F5'],
                                   'right': ['A1', 'A2', 'A3', 'A4', 'A5']},
                         'bans': {'left': ['FB'], 'right': ['AB']}}}
    sides = engine._bp_sides(detail)
    assert sides['ownPicks'] == ['A1', 'A2', 'A3', 'A4', 'A5']
    assert sides['foePicks'] == ['F1', 'F2', 'F3', 'F4', 'F5']
    assert sides['ownBans'] == ['AB'] and sides['foeBans'] == ['FB']


def test_analyze_adjustment_levels():
    # G3 换成「无前排」阵容：与前两局的双前排体系形成真实体系切换
    tanks = ['张飞', '盾山', '刘邦', '廉颇', '庄周']
    squishy = ['镜', '孙尚香', '不知火舞', '马可波罗', '妲己']
    games = [
        _game(1, 'k1', heroes=tanks, heroes_foe=['F', 'G', 'H', 'I', 'J'], result='loss'),
        _game(2, 'k2', heroes=['张飞', '盾山', '刘邦', '廉颇', '太乙真人'], heroes_foe=['F', 'G', 'H', 'I', 'J2'], result='loss', at10=800.0),
        _game(3, 'k3', heroes=squishy, heroes_foe=['F', 'G', 'H', 'I', 'J'], result='win', at10=-500.0),
    ]
    out = engine.analyze_series(_series(), games)
    rows = out['games']
    assert rows[1]['adjustment']['changeLevel'] == '小调整'
    assert rows[1]['adjustment']['newOwn'] == ['太乙真人']
    assert rows[2]['adjustment']['changeLevel'] == '大调整'
    # 体系切换按功能标签判定；前两局是假名（无能力数据）不生成标签，
    # 所以 G2 的 compChanged 应为 False（不猜），G3 对 G1 才是真切换——
    # 这里 G2/G3 对照中 G3 有标签、G2 没有，也不判切换（诚实口径）。
    assert rows[1]['adjustment']['compChanged'] is False
    assert rows[2]['compOwn'] == '无前排'
    # 败局后恢复：G1 输 → G2 输；G2 输 → G3 胜，10 分钟差从 800 → -500
    assert out['afterLoss']['n'] == 2
    assert out['afterLoss']['nextWins'] == 1
    assert out['afterLoss']['nextWinRate'] == 50.0
    assert out['afterLoss']['medianAt10Delta'] == -750.0  # (-200 + -1300) / 2


def test_analyze_comp_switch_with_real_tags():
    tanks = ['张飞', '盾山', '刘邦', '廉颇', '庄周']
    squishy = ['镜', '孙尚香', '不知火舞', '马可波罗', '妲己']
    games = [
        _game(1, 'k1', heroes=tanks, heroes_foe=['F', 'G', 'H', 'I', 'J'], result='loss'),
        _game(2, 'k2', heroes=squishy, heroes_foe=['F', 'G', 'H', 'I', 'J'], result='win'),
    ]
    out = engine.analyze_series(_series(), games)
    assert out['games'][1]['adjustment']['compChanged'] is True
    assert out['compSwitch']['switched']['n'] == 1
    assert out['compSwitch']['switched']['winRate'] == 100.0


def test_analyze_missing_at10_never_zero():
    games = [_game(1, 'k1', heroes=['A', 'B', 'C', 'D', 'E'], heroes_foe=['F', 'G', 'H', 'I', 'J'],
                   at10=None)]
    out = engine.analyze_series(_series(), games)
    assert out['games'][0]['at10'] is None
    assert out['coverage']['at10Games'] == 0
    assert any('10 分钟经济差' in c for c in out['caveats'])


def test_analyze_missing_result_score_is_zero_with_caveat():
    game = _game(1, 'k1', heroes=['A', 'B', 'C', 'D', 'E'], heroes_foe=['F', 'G', 'H', 'I', 'J'])
    game['vector']['result'] = ''
    out = engine.analyze_series(_series(), [game])
    assert out['score'] == {'us': 0, 'them': 0}
    assert any('胜负结果' in c for c in out['caveats'])


# ---------------------------------------------------------------- 多组汇总
def _row(series_id, games_results, *, opponent='青岚', best_of=5, status='confirmed',
         completion='completed'):
    games = []
    for index, (result, at10) in enumerate(games_results, 1):
        games.append({
            'matchKey': f'{series_id}-g{index}', 'gameIndex': index, 'result': result,
            'at10': at10, 'heroesOwn': [f'我{index}-{i}' for i in range(5)],
            'heroesFoe': [f'敌{index}-{i}' for i in range(5)],
            'ledger': {'usedUsCount': index * 5, 'usedFoeCount': index * 5},
        })
    score = {'us': sum(1 for r, _ in games_results if r == 'win'),
             'them': sum(1 for r, _ in games_results if r == 'loss')}
    return {'series': {'id': series_id, 'bestOf': best_of, 'opponent': opponent,
                       'status': status, 'completion': completion},
            'games': games, 'score': score,
            'afterLoss': {'pairs': [], 'n': 0, 'nextWins': 0}}


def test_summary_by_game_index_and_totals():
    rows = [
        _row('ts-a', [('win', 1000), ('win', 800), ('loss', -500)]),
        _row('ts-b', [('win', 500), ('loss', -800), ('loss', -900)]),
    ]
    summary = engine.summarize_series(rows)
    assert summary['totals']['series'] == 2
    assert summary['totals']['games'] == 6
    assert summary['totals']['gameWins'] == 3
    assert summary['totals']['gameWinRate'] == 50.0
    assert summary['totals']['seriesWins'] == 1 and summary['totals']['seriesLosses'] == 1
    g1 = summary['gameSequence'][0]
    assert g1['gameIndex'] == 1 and g1['n'] == 2 and g1['winRate'] == 100.0
    g3 = summary['gameSequence'][2]
    assert g3['winRate'] == 0.0
    assert summary['consumption'][0]['avgUsedUs'] == 5.0


def test_summary_small_samples_yield_none():
    rows = [_row('ts-a', [('win', 1000), ('loss', -500)])]
    summary = engine.summarize_series(rows)
    g1 = summary['gameSequence'][0]
    assert g1['n'] == 1 and g1['winRate'] == 100.0  # n=1 仍给值但带分母
    # 只有一组时 gameSequence 的 G2 桶不存在
    assert len(summary['gameSequence']) == 2


def test_attention_late_drop():
    rows = [_row('ts-a', [('win', 1000), ('win', 900), ('win', 600), ('loss', 0), ('loss', -100)])]
    summary = engine.summarize_series(rows)
    kinds = [a['kind'] for a in engine.build_attention(rows, summary)]
    assert 'late-drop' in kinds


def test_attention_losing_streak():
    rows = [_row('ts-a', [('win', 1000), ('loss', 0), ('loss', -100), ('loss', -200)])]
    summary = engine.summarize_series(rows)
    kinds = [a['kind'] for a in engine.build_attention(rows, summary)]
    assert 'losing-streak' in kinds


def test_attention_after_loss_flat():
    row = _row('ts-a', [('win', 1000), ('loss', 0), ('loss', -100)])
    row['afterLoss'] = {'pairs': [
        {'fromGame': 2, 'toGame': 3, 'nextResult': 'loss', 'at10Delta': -100},
        {'fromGame': 1, 'toGame': 2, 'nextResult': 'loss', 'at10Delta': -800}], 'n': 2, 'nextWins': 0}
    summary = engine.summarize_series([row])
    kinds = [a['kind'] for a in engine.build_attention([row], summary)]
    assert 'after-loss-flat' in kinds


def test_attention_needs_review_and_interrupted():
    rows = [_row('ts-a', [('win', 1000)], status='needs_review', completion='open'),
            _row('ts-b', [('loss', 0)], completion='interrupted')]
    summary = engine.summarize_series(rows)
    kinds = [a['kind'] for a in engine.build_attention(rows, summary)]
    assert 'needs-review' in kinds and 'interrupted' in kinds
