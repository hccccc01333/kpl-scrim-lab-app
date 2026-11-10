"""构建 BP 复盘用的外部事实表（离线脚本，产物进 data/facts/）。

三个数据源，三种口径，**永不合并成一个分**：

* 对位压制  ← 巅峰千强对位表（`matchup_raw`）+ 同分段的英雄基准胜率（`hero_daily`）
              输出「超额胜率」＝实际对位胜率 − 按两个英雄各自水平算出的预期胜率。
              不这么做就会把「英雄本来就弱」错判成「被克制」。
* 联动组合  ← KPL 赛事 picks（同队两人/三人同场）
* 赛事命中  ← 同上；本局阵容里的双人/三人组合在 KPL 出现过就算命中

用法：
    python scripts/build_bp_facts.py \
        --bp-project "D:/Projects/KPLBPagentRL" \
        --kpl "D:/AI数据分析/项目作品集/02-KPL实时胜率预测系统/data/processed/prematch_games_raw.jsonl"
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys
from collections import defaultdict
from datetime import date, timedelta

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / 'data' / 'facts'

# 巅峰千强：高分段大盘的基准人群（和 KPL、自家训练赛都不是一回事）
BRACKET = '巅峰千强'
MIN_PAIR_N = 200        # 单条对位的样本门槛
MIN_PICK_RATE = 0.03    # 双方使用率门槛：冷门英雄的样本没有代表性
MAX_EXCESS = 0.30       # 超额超过 30 个点基本是样本噪声，截断
WIN_WINDOW_DAYS = 90    # 基准胜率只看最近 90 天（版本滚动）


def _load_hero_daily(path, today):
    """hero_id -> (win_rate, pick_rate)，取窗口内均值。"""
    import pandas as pd
    frame = pd.read_parquet(path)
    frame = frame[frame['bracket'] == BRACKET]
    frame['date'] = pd.to_datetime(frame['date'], errors='coerce')
    today = pd.Timestamp(today)
    since = today - pd.Timedelta(days=WIN_WINDOW_DAYS)
    recent = frame[frame['date'] >= since]
    if recent.empty:                       # 窗口内没数据就退回全量最近一批
        cutoff = frame['date'].max() - timedelta(days=WIN_WINDOW_DAYS)
        recent = frame[frame['date'] >= cutoff]
    stats = {}
    for hero_id, group in recent.groupby('hero_id'):
        stats[int(hero_id)] = {
            'name': str(group['hero_name'].iloc[-1]),
            'wr': float(group['win_rate'].mean()),
            'pick': float(group['pick_rate'].mean()),
        }
    latest = recent['date'].max()
    return stats, (latest.date().isoformat() if latest is not None else '')


def _expected(a_wr, b_wr):
    """Bradley-Terry：两个英雄各自的胜率推这一对的期望胜率。"""
    if not a_wr or not b_wr:
        return None
    num = a_wr * (1 - b_wr)
    den = num + (1 - a_wr) * b_wr
    return num / den if den > 0 else None


def build_lane_matchups(matchup_dir, hero_stats):
    """巅峰千强对位 → 超额胜率表。"""
    pairs = defaultdict(lambda: [0, 0.0])      # (a,b) -> [n, weighted_win]
    for path in sorted(matchup_dir.glob('matchups_*.jsonl')):
        with path.open(encoding='utf-8') as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get('status') not in (None, 'ok'):
                    continue
                a, b, n = row.get('blue_id'), row.get('red_id'), int(row.get('n') or 0)
                wr = row.get('blue_win_rate')
                if not a or not b or n <= 0 or wr is None:
                    continue
                a, b = int(a), int(b)
                key = (a, b) if a <= b else (b, a)
                share = wr / 100.0 if a <= b else 1 - wr / 100.0
                pairs[key][0] += n
                pairs[key][1] += n * share

    rows = []
    for (a, b), (n, weighted) in pairs.items():
        ha, hb = hero_stats.get(a), hero_stats.get(b)
        if not ha or not hb:
            continue
        if n < MIN_PAIR_N:
            continue
        if ha['pick'] < MIN_PICK_RATE or hb['pick'] < MIN_PICK_RATE:
            continue
        raw = weighted / n
        exp = _expected(ha['wr'], hb['wr'])
        if exp is None:
            continue
        excess = max(-MAX_EXCESS, min(MAX_EXCESS, raw - exp))
        rows.append({
            'a': ha['name'], 'b': hb['name'], 'n': n,
            'wr': round(raw * 100, 1),
            'expected': round(exp * 100, 1),
            'excess': round(excess * 100, 1),
            'aRank': round(ha['wr'] * 100, 1), 'bRank': round(hb['wr'] * 100, 1),
        })
    rows.sort(key=lambda item: -item['n'])
    # 同名组合只保留样本最大的一条（跨分路重复出现时）
    seen, deduped = set(), []
    for row in rows:
        key = (row['a'], row['b'])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def build_kpl_combos(path, since_year, min_games):
    """KPL picks → 双人 / 三人组合的场次与胜率。"""
    pairs = defaultdict(lambda: [0, 0, 0])     # (a,b) -> [n, wins, last_year]
    trios = defaultdict(lambda: [0, 0, 0])
    games = 0
    with path.open(encoding='utf-8') as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            year = int(row.get('year') or 0)
            if year and year < since_year:
                continue
            y = row.get('y')
            if y not in (0, 1):
                continue
            games += 1
            for side in ('picks1', 'picks2'):
                heroes = [str(h.get('hero_name') or '').strip()
                          for h in (row.get(side) or []) if h.get('hero_name')]
                heroes = sorted({h for h in heroes if h})
                win = 1 if (side == 'picks1') == (y == 1) else 0
                for i in range(len(heroes)):
                    for j in range(i + 1, len(heroes)):
                        key = (heroes[i], heroes[j])
                        pairs[key][0] += 1
                        pairs[key][1] += win
                        pairs[key][2] = max(pairs[key][2], year)
                        for k in range(j + 1, len(heroes)):
                            tkey = (heroes[i], heroes[j], heroes[k])
                            trios[tkey][0] += 1
                            trios[tkey][1] += win
                            trios[tkey][2] = max(trios[tkey][2], year)

    def pack(source, size):
        out = []
        for heroes, (n, wins, year) in source.items():
            if n < min_games:
                continue
            out.append({'heroes': list(heroes), 'n': n, 'wins': wins,
                        'wr': round(wins / n * 100, 1), 'year': year, 'size': size})
        out.sort(key=lambda item: -item['n'])
        return out

    return pack(pairs, 2), pack(trios, 3), games


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--bp-project', required=True)
    ap.add_argument('--kpl', required=True)
    ap.add_argument('--since-year', type=int, default=2024)
    ap.add_argument('--min-combo-games', type=int, default=3)
    args = ap.parse_args()

    bp = pathlib.Path(args.bp_project)
    kpl = pathlib.Path(args.kpl)
    OUT.mkdir(parents=True, exist_ok=True)

    hero_stats, window_end = _load_hero_daily(bp / 'data/processed/91m/hero_daily.parquet', date.today())
    lane_rows = build_lane_matchups(bp / 'data/processed/91m/matchup_raw', hero_stats)
    ladder = {
        'schema': 'bp-lane-facts-v1',
        'source': 'ladder', 'bracket': BRACKET,
        'windowDays': WIN_WINDOW_DAYS, 'windowEnd': window_end,
        'minN': MIN_PAIR_N, 'minPickRate': MIN_PICK_RATE,
        'note': '超额胜率 = 实际对位胜率 − 按两个英雄各自基准胜率算出的期望；正数表示这对组合本身占优。',
        'pairs': lane_rows,
    }
    (OUT / 'lane_matchups.json').write_text(json.dumps(ladder, ensure_ascii=False), encoding='utf-8')

    pairs, trios, games = build_kpl_combos(kpl, args.since_year, args.min_combo_games)
    combos = {
        'schema': 'bp-kpl-combos-v1', 'source': 'kpl', 'sinceYear': args.since_year,
        'games': games, 'minGames': args.min_combo_games,
        'note': '场次 = 该组合在 KPL 同队同场出现过的局数；胜率 = 这些局的胜率。不含版本换算。',
        'pairs': pairs, 'trios': trios,
    }
    (OUT / 'kpl_combos.json').write_text(json.dumps(combos, ensure_ascii=False), encoding='utf-8')

    print(json.dumps({
        'ladder': {'pairs': len(lane_rows), 'window': window_end, 'bracket': BRACKET},
        'kpl': {'games': games, 'pairs': len(pairs), 'trios': len(trios), 'since': args.since_year},
    }, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
