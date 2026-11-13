"""对手条件化 BP 预测：条件频率、回退与可靠性。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

import bp_predict as pp  # noqa: E402
import test_kpl_bp as tf  # noqa: E402


def _game(bans1, picks1, bans2, picks2, *, team2='对手A', full=True):
    g = tf.make_game(picks1, picks2, 1, team2=team2, bp_mode='full' if full else None)
    g['bans'] = {'1': list(bans1), '2': list(bans2)}
    if not full:
        g['bpMode'] = 'partial'
        g['bansKnown'] = False
        g['pickOrderKnown'] = False
    # draftEvents not required for profile (uses picks/bans)
    return g


def test_profile_conditional_and_fallback(tmp_path):
    picks = ['p1', 'p2', 'p3', 'p4', 'p5']
    bans = ['a', 'b', 'c', 'd', 'e']
    games = [
        _game(bans, picks, ['x', 'y', 'z', 'w', 'v'], ['q1', 'q2', 'q3', 'q4', 'q5'], team2='对手A'),
        _game(bans, picks, ['x', 'y', 'z', 'w', 'v'], ['q1', 'q2', 'q3', 'q4', 'q5'], team2='对手A'),
        _game(bans, picks, ['x', 'y', 'z', 'w', 'v'], ['q1', 'q2', 'q3', 'q4', 'q5'], team2='对手A'),
    ]
    path = tmp_path / 'games.jsonl'
    path.write_text('\n'.join(json.dumps(g, ensure_ascii=False) for g in games) + '\n',
                    encoding='utf-8')
    prof = pp.build_profile(pp.load_games(path), target_side='2', team='对手A')
    assert prof['n_games'] == 3
    assert prof['n_full'] == 3
    res = pp.predict(prof, own_first_pick='p1', top=3)
    assert res['basis'] == 'conditional'
    assert res['n'] == 3
    assert res['firstBan'][0]['hero'] == 'x'
    res2 = pp.predict(prof, own_first_pick='nope', top=3)
    assert res2['basis'] == 'fallback'
    assert res2['n'] == 3


def test_empty_and_reliability(tmp_path):
    path = tmp_path / 'empty.jsonl'
    path.write_text('', encoding='utf-8')
    prof = pp.build_profile(pp.load_games(path))
    assert prof['n_games'] == 0
    res = pp.predict(prof, top=3)
    assert res['n'] == 0
    assert res['reliability'] == 'low'
    assert res['firstBan'] == []

    assert pp._reliability(50) == 'high'
    assert pp._reliability(10) == 'medium'
    assert pp._reliability(2) == 'low'


def test_non_full_excluded_from_conditional(tmp_path):
    picks = ['p1', 'p2', 'p3', 'p4', 'p5']
    bans = ['a', 'b', 'c', 'd', 'e']
    g = _game(bans, picks, ['x', 'y', 'z', 'w', 'v'], ['q1', 'q2', 'q3', 'q4', 'q5'],
              team2='对手A', full=False)
    path = tmp_path / 'g.jsonl'
    path.write_text(json.dumps(g, ensure_ascii=False) + '\n', encoding='utf-8')
    prof = pp.build_profile(pp.load_games(path), target_side='2', team='对手A')
    assert prof['n_games'] == 1
    assert prof['n_full'] == 0
    res = pp.predict(prof, own_first_pick='p1', top=3)
    assert res['basis'] == 'fallback'

def test_conditional_bucket_n_full_only_counts_full_games(tmp_path):
    """full_only_for_order=False 时非完整局能进条件桶，但不能算进 n_full。"""
    picks = ['p1', 'p2', 'p3', 'p4', 'p5']
    bans = ['a', 'b', 'c', 'd', 'e']
    full = _game(bans, picks, ['x', 'y', 'z', 'w', 'v'], ['q1', 'q2', 'q3', 'q4', 'q5'],
                 team2='对手A', full=True)
    partial = _game(bans, picks, ['x', 'y', 'z', 'w', 'v'], ['q1', 'q2', 'q3', 'q4', 'q5'],
                    team2='对手A', full=False)
    path = tmp_path / 'g.jsonl'
    path.write_text('\n'.join(json.dumps(g, ensure_ascii=False) for g in (full, partial)) + '\n',
                    encoding='utf-8')
    prof = pp.build_profile(pp.load_games(path), target_side='2', team='对手A',
                            full_only_for_order=False)
    bucket = prof['by_other_first_pick']['p1']
    assert bucket['n'] == 2
    assert bucket['n_full'] == 1
