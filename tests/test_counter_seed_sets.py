"""KPL 高准确率克制初稿：集合对集合的基本口径测试。"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import seed_counter_relations as seed  # noqa: E402


def _game(bid: str, day: int, side1, side2, win_camp: int):
    return {'battleId': bid, 'year': 2024, 'date': f'2024-01-{day:02d}',
            'winCamp': win_camp,
            'picks': {'1': list(side1), '2': list(side2)}}


def test_two_vs_two_counter_is_one_set_relation(tmp_path):
    """A+B 克 C+D 只出一条集合关系，不拆成四条一对一。"""
    games = []
    # 6 局核心对位：A+B 全胜 C+D。
    for i in range(6):
        games.append(_game(f'core-{i}', i + 1,
                           ['A', 'B', 'E', 'F', 'G'], ['C', 'D', 'H', 'I', 'J'], 1))
    # 6 局 filler：A/B 输、C/D 赢，让四个英雄的基准胜率都回到 50% 左右；
    # 否则「克制」只是「A/B 本身强」，超额胜率会把这类噪音滤掉。
    for i in range(6):
        games.append(_game(f'fill-a-{i}', 7 + i,
                           ['A', 'B', 'E', 'F', 'G'], ['X', 'Y', 'Z', 'W', 'V'], 2))
        games.append(_game(f'fill-c-{i}', 13 + i,
                           ['X', 'Y', 'Z', 'W', 'V'], ['C', 'D', 'H', 'I', 'J'], 2))
    path = tmp_path / 'games.jsonl'
    path.write_text('\n'.join(json.dumps(g, ensure_ascii=False) for g in games),
                    encoding='utf-8')

    all_games = seed.load_games(path)
    logits = seed.hero_logits(all_games)
    store, included, window = seed.mine_pairs(all_games, 2024)
    cands = seed.candidates(store, logits)
    hero_rows, combo_rows, n_hero, n_combo = seed.split_rows(cands, 0, 'now', window)

    assert included == len(games)
    target = [row for row in combo_rows
              if set(row['aHeroes']) == {'A', 'B'} and set(row['bHeroes']) == {'C', 'D'}]
    assert target, f'未挖到 A+B 克 C+D，combo 候选={n_combo}'
    row = target[0]
    assert row['a'] in ('A+B', 'B+A')
    assert row['b'] in ('C+D', 'D+C')
    assert row['aHeroes'] != row['bHeroes']
    assert row['evidence']['n'] == 6
    assert row['evidence']['wr'] == 100.0
    assert row['evidence']['excess'] >= seed.MIN_EXCESS_PP
    assert row['source'] == seed.SOURCE
    # 不应该被拆成 A→C / A→D / B→C / B→D 四条一对一。
    assert not any(set(r['aHeroes']) == {'A'} and set(r['bHeroes']) == {'C'}
                   for r in hero_rows + combo_rows)
