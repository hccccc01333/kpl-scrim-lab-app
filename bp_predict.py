"""对手条件化 BP 预测（赛训研究层，统计版）。

数据源：`data/kpl/bp_games.jsonl`（KPL 官方赛事，自抓），每局含 picks/bans/draftEvents/
bpMode/pickOrderKnown/camp1/camp2/winCamp。

口径：
- 只用 `bpMode == 'full'`（`bansKnown` 且 `pickOrderKnown` 均为 True）的局做
  **顺序敏感**的条件预测；全量局仍可用于边际频率。
- 预测对象是「对手阵营」的动作；条件变量是「我方先手」（我方第一手选用英雄）
  与选边（红/蓝）。样本不足时回退到边际分布，并标 reliability。
- 输出概率 = 条件频率，附样本数与可靠性；不做黑箱胜率，LLM 只负责解释。
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_GAMES = ROOT / 'data' / 'kpl' / 'bp_games.jsonl'


def load_games(path=None):
    path = Path(path) if path else DEFAULT_GAMES
    games = []
    if not path.exists():
        return games
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            games.append(json.loads(line))
        except (ValueError, json.JSONDecodeError):
            continue
    return games


def _side_team(game, side):
    key = 'camp1' if side == '1' else 'camp2'
    info = game.get(key) or {}
    return str(info.get('team') or '').strip()


def _is_full(game):
    return bool(game.get('bansKnown')) and bool(game.get('pickOrderKnown'))


def build_profile(games, *, target_side='2', team=None, full_only_for_order=True):
    """构建对手（target_side）的条件化 BP 画像。

    target_side: '1' 或 '2'，预测该侧的动作。
    team: 若给定，只保留 target 侧队伍匹配的局。
    """
    other_side = '1' if target_side == '2' else '2'
    profile = {
        'target_side': target_side,
        'other_side': other_side,
        'team_filter': team,
        'n_games': 0,
        'n_full': 0,
        'overall': _empty_bucket(),
        'by_other_first_pick': {},
        'by_team': {},
        'teams': [],
    }
    teams_seen = set()
    for game in games or []:
        tname = _side_team(game, target_side)
        if team and tname != team:
            continue
        bans_t = list((game.get('bans') or {}).get(target_side) or [])
        picks_t = list((game.get('picks') or {}).get(target_side) or [])
        picks_o = list((game.get('picks') or {}).get(other_side) or [])
        ofp = picks_o[0] if picks_o else None
        full = _is_full(game)
        profile['n_games'] += 1
        if full:
            profile['n_full'] += 1
        # overall marginal (all games)
        _add_to_bucket(profile['overall'], bans_t, picks_t, full)
        # conditional on other side's first pick (full games only for order sensitivity)
        if (not full_only_for_order) or full:
            key = ofp if ofp else '__none__'
            bucket = profile['by_other_first_pick'].setdefault(key, _empty_bucket())
            # 传真实 full：顺序不敏感模式下塞进来的非完整局不能计入 n_full，
            # 否则条件预测的可靠性会被高估。
            _add_to_bucket(bucket, bans_t, picks_t, full)
        # by target team
        if tname:
            tb = profile['by_team'].setdefault(tname, _empty_bucket())
            _add_to_bucket(tb, bans_t, picks_t, full)
            teams_seen.add(tname)
    profile['teams'] = sorted(teams_seen)
    return profile


def _empty_bucket():
    return {
        'n': 0,
        'n_full': 0,
        'first_ban': Counter(),
        'first_pick': Counter(),
        'ban_games': Counter(),   # hero -> #games in which it was banned
        'pick_games': Counter(),  # hero -> #games in which it was picked
        'all_bans': Counter(),    # hero -> total ban occurrences
        'all_picks': Counter(),
    }


def _add_to_bucket(bucket, bans_t, picks_t, full):
    bucket['n'] += 1
    if full:
        bucket['n_full'] += 1
    if bans_t:
        bucket['first_ban'][bans_t[0]] += 1
        bucket['ban_games'][bans_t[0]]  # placeholder no-op
    # count ban presence per game
    for h in set(bans_t):
        bucket['ban_games'][h] += 1
    for h in bans_t:
        bucket['all_bans'][h] += 1
    if picks_t:
        bucket['first_pick'][picks_t[0]] += 1
    for h in set(picks_t):
        bucket['pick_games'][h] += 1
    for h in picks_t:
        bucket['all_picks'][h] += 1


def _reliability(n):
    if n is None or n < 5:
        return 'low'
    if n < 20:
        return 'medium'
    return 'high'


def _top_list(counter, n, top):
    out = []
    for hero, c in counter.most_common(top):
        out.append({
            'hero': hero, 'count': c,
            'prob': round(c / n, 3) if n else 0.0,
            'n': n,
        })
    return out


def _freq_list(counter, n, top, threshold=0.3):
    out = []
    for hero, c in counter.most_common():
        rate = c / n if n else 0.0
        if rate < threshold and len(out) >= top:
            break
        out.append({'hero': hero, 'games': c, 'rate': round(rate, 3), 'n': n})
        if len(out) >= top * 2:
            break
    return out[:top * 2]


def predict(profile, *, own_first_pick=None, top=3):
    """给定画像与我方先手，输出对手可能的应对（Top-3 + 频繁 ban/pick）。"""
    bucket = None
    basis = 'overall'
    if own_first_pick:
        cand = profile['by_other_first_pick'].get(own_first_pick)
        if cand and cand['n'] >= 3:
            bucket = cand
            basis = 'conditional'
    if bucket is None:
        bucket = profile['overall']
        if own_first_pick is not None:
            basis = 'fallback'
    n = bucket['n'] or 0
    return {
        'basis': basis,
        'condition': own_first_pick,
        'n': n,
        'reliability': _reliability(n),
        'firstBan': _top_list(bucket['first_ban'], n, top),
        'firstPick': _top_list(bucket['first_pick'], n, top),
        'frequentBans': _freq_list(bucket['ban_games'], n, top),
        'frequentPicks': _freq_list(bucket['pick_games'], n, top),
        'sampleGames': profile['n_games'],
        'fullGames': profile['n_full'],
    }


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description='对手条件化 BP 预测（统计版）')
    ap.add_argument('--games', default=str(DEFAULT_GAMES))
    ap.add_argument('--team', default=None, help='只分析该对手队伍')
    ap.add_argument('--own-first', default=None, help='我方先手英雄')
    ap.add_argument('--top', type=int, default=3)
    ap.add_argument('--out', default=None)
    args = ap.parse_args(argv)
    games = load_games(args.games)
    profile = build_profile(games, target_side='2', team=args.team)
    result = predict(profile, own_first_pick=args.own_first, top=args.top)
    result['teams'] = profile['teams']
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding='utf-8')
    else:
        print(text)
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
