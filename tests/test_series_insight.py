"""大场挖掘层测试：经济→胜率模型、英雄价值、选手基线、相似局、数据质量。

固定样本是合成的 24 局语料 + 3 局目标大场；覆盖：
- 目标系列赛从英雄价值/模型训练中排除（防泄漏）；
- 过程指纹相同的重复局会被识别，并排在结论最前；
- 缺失语料时降级为只描述本场，不编造模型；
- n<2 的系列比例返回 None，不拿 1 局当 100%。
"""
import series_engine
import series_insight

POSITIONS = ('对抗路', '打野', '中路', '发育路', '游走')


def _players(heroes, heroes_foe, *, win, sign):
    rows = []
    for index, position in enumerate(POSITIONS):
        rows.append({
            'name': f'我-{position}', 'camp': 'blue', 'pos': position,
            'hero': heroes[index],
            'k': 6 if win else 3, 'd': 3 if win else 6, 'a': 8 if win else 4,
            'gpm': 650 + index * 10, 'dpm': 4200 + index * 80,
            'part': 62.0 if win else 48.0,
        })
        rows.append({
            'name': f'敌-{position}', 'camp': 'red', 'pos': position,
            'hero': heroes_foe[index],
            'k': 3 if win else 6, 'd': 6 if win else 3, 'a': 4 if win else 8,
            'gpm': 620 + index * 10, 'dpm': 4000 + index * 80,
            'part': 48.0 if win else 62.0,
        })
    return rows


def _vector(key, result='win', at10=1200.0, final=2500.0, *, duration=1200,
            heroes=None, heroes_foe=None, opponent='青岚', session='一队'):
    win = result == 'win'
    sign = 1 if win else -1
    heroes = heroes or [f'{key}-我{i}' for i in range(5)]
    heroes_foe = heroes_foe or [f'{key}-敌{i}' for i in range(5)]
    path = [at10 * 0.5, at10, at10 + (final - at10) * 0.2,
            at10 + (final - at10) * 0.4, at10 + (final - at10) * 0.6,
            at10 + (final - at10) * 0.8, final]
    shape = [0.0, at10 * 0.5, at10, at10 + (final - at10) * 0.3,
             at10 + (final - at10) * 0.6, final]
    obj10 = {'dragonOwn': 1 if sign > 0 else 0, 'dragonFoe': 1 if sign < 0 else 0,
             'towerOwn': 2 if sign > 0 else 0, 'towerFoe': 2 if sign < 0 else 0}
    obj = {'dragonOwn': 3 if sign > 0 else 1, 'dragonFoe': 1 if sign > 0 else 3,
           'towerOwn': 7 if sign > 0 else 3, 'towerFoe': 3 if sign > 0 else 7}
    return {
        'key': key, 'date': '2026-11-15', 'clock': '19:00', 'order': '2026-11-15 19:00',
        'opponent': opponent, 'session': session, 'version': 'S30', 'result': result,
        'camp': 'blue', 'duration': duration, 'at10': at10, 'finalDiff': final,
        'g': [0.0, *path], 'w': [path[i] - (path[i - 1] if i else 0.0) for i in range(len(path))],
        's': shape,
        'seg': {'early': at10 * 0.3, 'mid': at10 * 0.7, 'late': final - at10},
        'obj': obj, 'objAt10': obj10,
        'first': {'bloodT': 120, 'bloodSide': 'own' if win else 'foe',
                  'dragonT': 260, 'dragonSide': 'own' if win else 'foe',
                  'towerT': 300, 'towerSide': 'own' if win else 'foe'},
        'fight': {'n': 5, 'win': 4 if win else 2, 'decidedN': 5, 'decidedWin': 4 if win else 2},
        'fk': {'adv': {'n': 2, 'win': 2 if win else 1},
               'even': {'n': 2, 'win': 1}, 'dis': {'n': 1, 'win': 1 if win else 0},
               'first': {'n': 1, 'win': 1 if win else 0},
               'firstAgainst': {'n': 1, 'win': 0 if win else 1}},
        'death': {'own': 5 if win else 12, 'foe': 12 if win else 5},
        'buff': {'anti': 1, 'stolen': 0}, 'cut': {'n': 1, 'first': 1 if win else 0},
        'jungle': {'crossSec': 120, 'crossShare': 0.3, 'firstCross': 200, 'deepShare': 0.05},
        'lanes': {position: {'gold': sign * 20, 'damage': sign * 50, 'taken': -sign * 10}
                  for position in POSITIONS},
        'pl': _players(heroes, heroes_foe, win=win, sign=sign),
        'heroes': heroes, 'heroesFoe': heroes_foe,
        'bansOwn': [f'{key}-ban我'], 'bansFoe': [f'{key}-ban敌'],
        'compOwn': ['强开团'], 'compFoe': ['双前排'],
        'hasReplay': True, 'ecoPoints': 8,
    }


def _corpus():
    vectors = []
    for index in range(24):
        win = index % 2 == 0
        sign = 1 if win else -1
        key = f'c{index:02d}'
        vectors.append(_vector(
            key, 'win' if win else 'loss',
            at10=sign * (1100 + index * 30), final=sign * (2400 + index * 40)))
    return vectors


def _target(key='t1', index=1, **kwargs):
    vector = _vector(key, **kwargs)
    return {'matchKey': key, 'gameIndex': index, 'vector': vector, 'detail': None}


def _build(games=None, corpus=None, briefs=None):
    games = games or [
        _target('t1', 1, result='win', at10=1500, final=3200),
        _target('t2', 2, result='loss', at10=-900, final=-2600),
        _target('t3', 3, result='win', at10=2100, final=4100),
    ]
    brief = {'id': 'ts-test', 'bestOf': 3, 'rulesetId': 'scrim-global-team',
             'opponent': '青岚', 'startAt': '2026-11-15',
             'games': [{'matchKey': game['matchKey'], 'gameIndex': game['gameIndex']}
                       for game in games]}
    analysis = series_engine.analyze_series(brief, games)
    insight = series_insight.build_insight(
        brief, games, analysis, corpus=_corpus() if corpus is None else corpus,
        series_briefs=briefs or [])
    return insight


def test_build_insight_contract():
    insight = _build()
    assert insight['version'] == 'series-insight-v1'
    assert insight['available'] is True
    assert insight['sample']['games'] == 3
    assert insight['sample']['corpusGames'] >= 20
    assert len(insight['flow']['games']) == 3
    assert insight['flow']['model'] is not None
    assert all(game['wp'] for game in insight['flow']['games'])
    assert len(insight['phase']['perGame']) == 3
    assert len(insight['draft']['games']) == 3
    assert len(insight['players']['players']) >= 5
    assert len(insight['fight']['perGame']) == 3
    assert len(insight['similar']['games']) == 3
    assert insight['methods']
    assert insight['caveats']
    assert isinstance(insight['insights'], list)


def test_quality_duplicate_games_sorted_first():
    games = [
        _target('t1', 1, result='win', at10=1500, final=3200,
                heroes=['专属', 'A2', 'A3', 'A4', 'A5'],
                heroes_foe=['F1', 'F2', 'F3', 'F4', 'F5']),
        _target('t2', 2, result='win', at10=1500, final=3200,
                heroes=['专属', 'A2', 'A3', 'A4', 'A5'],
                heroes_foe=['F1', 'F2', 'F3', 'F4', 'F5']),
        _target('t3', 3, result='loss', at10=-900, final=-2600),
    ]
    insight = _build(games=games)
    assert insight['quality']['duplicates']
    assert insight['quality']['duplicates'][0]['gameIndexes'] == [1, 2]
    assert insight['insights'][0]['kind'] == 'quality'
    assert insight['insights'][0]['severity'] == 'high'


def test_hero_stats_exclude_target_series():
    games = [_target('t1', 1, result='win', at10=1500, final=3200,
                     heroes=['专属', 'A2', 'A3', 'A4', 'A5'])]
    insight = _build(games=games)
    hero = next(item for item in insight['draft']['heroes'] if item['name'] == '专属')
    assert hero['apps'] == 0
    assert hero['ownApps'] == 0
    assert 'novel' in hero['tags']


def test_wp_model_learns_positive_gold_relation():
    model = series_insight._fit_wp_model(_corpus(), set())
    assert model is not None
    assert model['per1000At10'] > 0
    assert model['auc'] is not None and model['auc'] >= 0.6
    assert series_insight._predict(model, 3000, 10) > series_insight._predict(model, -3000, 10)


def test_knn_smoothing_avoids_100_percent():
    rows = [{'key': f'k{index}', 'result': 'win',
             'vector': {'date': '2026-11-15', 'opponent': 'A', 'at10': 1000, 'duration': 1200},
             'feature': [0.0] * 8, 'z': [0.0] * 8}
            for index in range(7)]
    matrix = {'rows': rows, 'means': [0.0] * 8, 'stds': [1.0] * 8}
    result = series_insight._knn_neighbors([0.0] * 8, matrix, k=7)
    assert result['rawWinRate'] == 100.0
    assert result['expectedWinRate'] < 100.0
    assert result['expectedWinRate'] > 50.0


def test_empty_corpus_degrades_without_crash():
    insight = _build(corpus=[], briefs=[])
    assert insight['flow']['model'] is None
    assert insight['similar']['series']['available'] is False
    assert insight['sample']['corpusGames'] == 0
    assert all(method['reliable'] is False for method in insight['methods']
               if method['id'] in ('wp', 'shape', 'hero', 'knn'))


def test_single_game_never_reports_rates():
    games = [_target('t1', 1, result='win', at10=1500, final=3200)]
    insight = _build(games=games)
    ahead = insight['flow']['leadConversion']['ahead']
    assert ahead['n'] == 1
    assert ahead['rate'] is None
    assert ahead['enough'] is False


def test_overview_contract_for_conclusion_layer():
    """总览前端只排版：覆盖局数、缺失原因、胜负分组必须由后端给全。"""
    insight = _build()
    overview = insight['overview']
    assert len(overview['games']) == 3
    assert all('hasReplay' in game for game in overview['games'])
    for metric in overview['metrics']:
        assert len(metric['missing']) == 3
        assert metric['coverage'] == sum(1 for reason in metric['missing'] if reason is None)
        assert set(metric['byResult']) == {'win', 'loss'}
        assert metric['byResult']['win']['n'] + metric['byResult']['loss']['n'] == metric['coverage']

    # 缺回放的局要能单独标记，不能混进「本局未触发」。
    rows = [_target('t1', 1, result='win', at10=1500, final=3200)]
    rows[0]['vector']['hasReplay'] = False
    insight_no_replay = _build(games=rows)
    assert insight_no_replay['overview']['games'][0]['hasReplay'] is False
