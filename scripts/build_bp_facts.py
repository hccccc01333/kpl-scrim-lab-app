"""构建 BP 复盘用的外部事实表（离线脚本，产物进 data/facts/）。

三个数据源，三种口径，**永不合并成一个分**：

* 对位压制  ← 巅峰千强对位表（`matchup_raw`）+ 同分段的英雄基准胜率（`hero_daily`）
              输出「超额胜率」＝实际对位胜率 − 按两个英雄各自水平算出的预期胜率。
              不这么做就会把「英雄本来就弱」错判成「被克制」。
* 联动组合  ← KPL 赛事 picks（同队两人/三人同场 + 整阵容）
* 赛事命中  ← 同上；本局阵容里的双人/三人/整阵容组合在 KPL 出现过就算命中

KPL 数据源已改为**本项目自抓**的 `data/kpl/bp_games.jsonl`
（`python scripts/crawl_kpl_bp.py --since-year 2024 --build` 产出），不再依赖外部数据包。
`--kpl` 仍可指向旧的外部 `prematch_games_raw.jsonl`（自动识别旧格式，走旧逻辑）。
巅峰千强 lane_matchups 仍依赖外部 bp-project 路径，不传 `--bp-project` 就保留现有文件。

用法：
    python scripts/build_bp_facts.py --kpl data/kpl/bp_games.jsonl          # 只重建 KPL 组合
    python scripts/build_bp_facts.py \
        --bp-project "<巅峰千强项目目录>" \
        --kpl data/kpl/bp_games.jsonl                                      # 同时重建对位表
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
LOCAL_KPL = ROOT / 'data' / 'kpl' / 'bp_games.jsonl'
ROLE_POOLS = ROOT / 'data' / 'peak' / 'matchup_raw' / 'role_pools.json'

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import kpl_bp  # noqa: E402  （本项目自抓管线：本地 jsonl → 组合事实表）

# 巅峰千强：高分段大盘的基准人群（和 KPL、自家训练赛都不是一回事）
BRACKET = '巅峰千强'
MIN_PAIR_N = 50         # 收录门槛：50 局起；50–199 只作「初步观察」，≥200 才判优势/劣势
MIN_PICK_RATE = 0.0     # 不按使用率过滤：冷门对位也保留，由 n 和 CI 决定证据等级
MAX_EXCESS = 0.30       # 超额超过 30 个点基本是样本噪声，截断
WIN_WINDOW_DAYS = 56    # 基准胜率取最近 8 周（按周聚合后取中位数）
PICK_PRIOR = 0.02       # 登场率先验：pick 越低，胜率越向 50% 收缩（绝活哥/小样本）
LOW_PICK_RATE = 0.01    # 双方登场率低于 1%：只作初步观察，不判优势/劣势
# 英雄强度梯度（教练 2026-11-17）：一对一的对位样本对冷门英雄永远凑不够，
# 所以再给一条「这个英雄在巅峰千强本身是什么强度」的窗口数据——近 7 天看当下，
# 近 30 天看稳定，两个窗口都按登场率收缩后再排同路档位（T1 最强）。
STRENGTH_WINDOWS = ((7, '7d'), (30, '30d'))


def _shrink(wr, pick):
    """胜率按登场率向 50% 收缩（与对位期望同一套折扣）。"""
    weight = pick / (pick + PICK_PRIOR) if pick > 0 else 0.0
    return 0.5 + (wr - 0.5) * weight if wr is not None else None


def _load_hero_daily(path, today):
    """hero_id → 周中位数基准 + 近 7 / 30 天强度窗口。

    先按周聚合（避免单日作弊/绝活局把均值拉高），再对 8 周取中位数；
    最后按登场率向 50% 收缩：wr_adj = 0.5 + (wr - 0.5) * pick / (pick + PICK_PRIOR)。
    低登场率英雄的胜率更容易被少数绝活哥/异常局抬高，收缩是对这种选择偏差的折扣，
    不是样本量修正。

    另外给 `wr7 / pick7 / wrAdj7` 与 `wr30 / pick30 / wrAdj30`：一对一对位样本
    凑不够的时候，教练至少能看到「这个英雄在这个分段本身强不强」。
    """
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
    recent = recent.copy()
    recent['week'] = recent['date'].dt.to_period('W-MON')
    weekly = recent.groupby(['hero_id', 'week']).agg(
        wr=('win_rate', 'mean'), pick=('pick_rate', 'mean'),
        days=('date', 'count')).reset_index()
    name_by_id = recent.groupby('hero_id')['hero_name'].last().to_dict()
    stats = {}
    for hero_id, group in weekly.groupby('hero_id'):
        wr = float(group['wr'].median())
        pick = float(group['pick'].median())
        stats[int(hero_id)] = {
            'name': str(name_by_id.get(hero_id) or ''),
            'wr': wr,
            'wrAdj': _shrink(wr, pick),
            'pick': pick,
            'weeks': int(len(group)),
        }
    # 近 7 / 30 天：日线本身已经是当日全量的聚合值，窗口内取均值即可。
    for days, tag in STRENGTH_WINDOWS:
        window = recent[recent['date'] >= today - pd.Timedelta(days=days)]
        if window.empty:
            continue
        agg = window.groupby('hero_id').agg(
            wr=('win_rate', 'mean'), pick=('pick_rate', 'mean'),
            days=('date', 'nunique'))
        for hero_id, row in agg.iterrows():
            stat = stats.setdefault(int(hero_id), {'name': str(name_by_id.get(hero_id) or '')})
            wr, pick = float(row['wr']), float(row['pick'])
            stat[f'wr{tag}'] = wr
            stat[f'pick{tag}'] = pick
            stat[f'wrAdj{tag}'] = _shrink(wr, pick)
            stat[f'days{tag}'] = int(row['days'])
    latest = recent['date'].max()
    return stats, (latest.date().isoformat() if latest is not None else '')


def _role_pools(path):
    """分路英雄池：分路名 → 英雄名列表（T1–T4 档位要同路排，跨路比没意义）。

    源站把元流之子按形态拆成 `元流之子_射手`，与营地/回放里的
    `元流之子(射手)` 不是同一个写法，这里统一成营地写法。
    同一个英雄可以出现在多个分路池里（李信既在对抗路榜也在发育路榜），
    所以这里按池子原样保存，不折成一对一。
    """
    try:
        pools = json.loads(pathlib.Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    role_by_cid = {1: '对抗路', 2: '中路', 3: '发育路', 4: '打野', 5: '游走'}
    out = {}
    for cid, rows in (pools or {}).items():
        role = role_by_cid.get(int(cid)) if str(cid).isdigit() else None
        if not role:
            continue
        names = []
        for row in rows or []:
            name = str(row.get('hero_name') or '')
            if '_' in name:
                base, _, form = name.partition('_')
                name = f'{base}({form})'
            if name and name not in names:
                names.append(name)
        if names:
            out[role] = names
    return out


def _tier_index(rank, size):
    """名次 → 1–4（四等分，每档约四分之一；与 bp_facts._tier_of 同一口径）。"""
    if not size or not rank:
        return 4
    return max(1, min(4, -(-rank * 4 // size)))


def _assign_tiers(stats, pools):
    """同路按收缩后的 30 天强度排 T1–T4（每档约四分之一）。

    英雄在主分路（cid 顺序里第一个命中的池）上拿档位；跨路重复的英雄
    展示层会按本局实际那条路重排（见 `bp_facts._hero_strength`）。
    """
    name_by_id = {hero_id: stat.get('name') for hero_id, stat in stats.items()}
    ranked = {}
    for role, names in (pools or {}).items():
        rows = []
        for name in names:
            for hero_id, stat in stats.items():
                if stat.get('name') != name:
                    continue
                score = stat.get('wrAdj30d') or stat.get('wrAdj')
                if score is not None:
                    rows.append((score, hero_id))
                break
        if rows:
            ranked[role] = rows
    for role, rows in ranked.items():
        rows.sort(key=lambda item: -item[0])
        total = len(rows)
        for index, (_, hero_id) in enumerate(rows):
            stat = stats[hero_id]
            if stat.get('tier'):
                continue                      # 已有主分路档位就不覆盖
            stat['tier'] = f'T{_tier_index(index + 1, total)}'
            stat['role'] = role
            stat['roleRank'] = index + 1
            stat['roleSize'] = total
    _ = name_by_id
    return stats


def _expected(a_wr, b_wr):
    """Bradley-Terry：两个英雄各自的胜率推这一对的期望胜率。"""
    if not a_wr or not b_wr:
        return None
    num = a_wr * (1 - b_wr)
    den = num + (1 - a_wr) * b_wr
    return num / den if den > 0 else None


def _iter_matchup_rows(matchup_dir):
    """读外部项目布局的 matchups_*.jsonl，产出原始对位行。"""
    for path in sorted(matchup_dir.glob('matchups_*.jsonl')):
        with path.open(encoding='utf-8') as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                yield row


def build_lane_rows(matchup_rows, hero_stats):
    """原始对位行（可含双方向）→ 超额胜率表。

    输入是 `blue_id/red_id/n/blue_win_rate/status` 行的迭代器；调用方负责去重口径
    （一次性全量直接全给，带时间戳的分片则先按对位取最新，见 peak_crawl.py）。
    """
    pairs = defaultdict(lambda: [0, 0.0])      # (a,b) -> [n, weighted_win]
    for row in matchup_rows:
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
        # 兜底：英雄名解析失败（空串）时宁可跳过，也不要把所有对位折叠成一条空名记录
        if not str(ha.get('name') or '').strip() or not str(hb.get('name') or '').strip():
            continue
        if n < MIN_PAIR_N:
            continue
        if ha['pick'] < MIN_PICK_RATE or hb['pick'] < MIN_PICK_RATE:
            continue
        raw = weighted / n
        # 期望用登场率收缩后的胜率：低登场率英雄不把「绝活哥拉高的胜率」带进对位期望。
        exp = _expected(ha.get('wrAdj', ha['wr']), hb.get('wrAdj', hb['wr']))
        if exp is None:
            continue
        excess = max(-MAX_EXCESS, min(MAX_EXCESS, raw - exp))
        low_pick = min(ha['pick'], hb['pick']) < LOW_PICK_RATE
        rows.append({
            'a': ha['name'], 'b': hb['name'], 'n': n,
            'wr': round(raw * 100, 1),
            'expected': round(exp * 100, 1),
            'excess': round(excess * 100, 1),
            'aRank': round(ha['wr'] * 100, 1), 'bRank': round(hb['wr'] * 100, 1),
            'aPick': round(ha['pick'] * 100, 2), 'bPick': round(hb['pick'] * 100, 2),
            'lowPick': low_pick,
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


def build_lane_matchups(matchup_dir, hero_stats):
    """巅峰千强对位 → 超额胜率表。"""
    return build_lane_rows(_iter_matchup_rows(matchup_dir), hero_stats)


def build_ladder_doc(lane_rows, hero_stats, window_end, pools=None):
    """对位表 + 每个英雄的分段基准 → lane_matchups.json 的完整文档。"""
    pools = dict(pools or {})
    if pools:
        _assign_tiers(hero_stats, pools)
    heroes = {}
    for stat in hero_stats.values():
        name = stat.get('name')
        if not name:
            continue
        row = {
            'wr': round(stat['wr'] * 100, 1),
            'wrAdj': round(stat.get('wrAdj', stat['wr']) * 100, 1),
            'pick': round(stat['pick'] * 100, 2),
            'weeks': stat.get('weeks'),
        }
        # 近 7 / 30 天强度窗口：缺窗口就不要字段，前端按「无窗口」降级。
        for tag in ('7d', '30d'):
            if stat.get(f'wr{tag}') is None:
                continue
            row[f'wr{tag}'] = round(float(stat[f'wr{tag}']) * 100, 1)
            row[f'wrAdj{tag}'] = round(float(stat[f'wrAdj{tag}']) * 100, 1)
            row[f'pick{tag}'] = round(float(stat[f'pick{tag}']) * 100, 2)
            row[f'days{tag}'] = stat.get(f'days{tag}')
        for key in ('role', 'tier', 'roleRank', 'roleSize'):
            if stat.get(key) is not None:
                row[key] = stat[key]
        heroes[name] = row
    return {
        'schema': 'bp-lane-facts-v1',
        'source': 'ladder', 'bracket': BRACKET,
        'windowDays': WIN_WINDOW_DAYS, 'windowEnd': window_end,
        'period': 'week', 'pickPrior': PICK_PRIOR, 'lowPickRate': LOW_PICK_RATE,
        'minN': MIN_PAIR_N, 'minPickRate': MIN_PICK_RATE,
        'strengthWindows': [days for days, _ in STRENGTH_WINDOWS],
        'note': ('超额胜率 = 实际对位胜率 − 按两个英雄基准胜率算出的期望；'
                 '基准按最近 8 周的分周中位数，并按登场率向 50% 收缩'
                 '（低登场率英雄的胜率容易被绝活哥/异常局抬高）；'
                 '英雄强度另给近 7 天 / 近 30 天窗口，T1–T4 按同路收缩后胜率排名。'),
        'pairs': lane_rows,
        # 每个英雄在该分段的胜率与使用率：没有对位样本时，用它解释「为什么没有」
        'heroes': heroes,
        # 分路英雄池：本局某路英雄的档位按**本局那条路**的池子排（源站把李信也
        # 放在发育路榜里，按主分路排会把他和射手比，档位没有意义）
        'rolePools': pools,
    }


def build_kpl_combos(path, since_year, min_games):
    """旧外部数据包格式（`prematch_games_raw.jsonl` 的 picks1/picks2）→ 双人 / 三人组合。

    保留旧逻辑只为兼容 `--kpl <外部jsonl>`；本项目现在默认走 `kpl_bp.build_facts`。
    """
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


def detect_kpl_format(path):
    """识别 KPL jsonl 格式：`local`（本项目 kpl-bp-game-v1）/ `legacy`（外部数据包）。"""
    with path.open(encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict):
                continue
            if 'picks1' in row or 'picks2' in row:
                return 'legacy'
            if isinstance(row.get('picks'), dict):
                return 'local'
            return 'unknown'
    return 'unknown'


def build_kpl_facts(path, since_year, min_games):
    """读本项目自抓 jsonl（或旧外部 jsonl）→ `kpl_combos.json` 内容。"""
    if detect_kpl_format(path) == 'legacy':
        pairs, trios, games = build_kpl_combos(path, since_year, min_games)
        return {
            'schema': 'bp-kpl-combos-v1', 'source': 'kpl', 'sinceYear': since_year,
            'games': games, 'minGames': min_games,
            'note': '场次 = 该组合在 KPL 同队同场出现过的局数；胜率 = 这些局的胜率。不含版本换算。',
            'pairs': pairs, 'trios': trios,
        }
    games = kpl_bp.load_games(path)
    return kpl_bp.build_facts(games, since_year=since_year, min_games=min_games)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--bp-project', default='',
                    help='巅峰千强数据源项目路径；不传则跳过 lane_matchups 重建（保留现有文件）')
    ap.add_argument('--kpl', default=str(LOCAL_KPL),
                    help='KPL BP jsonl；默认本项目爬虫产物 data/kpl/bp_games.jsonl')
    ap.add_argument('--since-year', type=int, default=2024)
    ap.add_argument('--min-combo-games', type=int, default=3)
    ap.add_argument('--role-pools', default=str(ROLE_POOLS),
                    help='分路英雄池（T1–T4 档位同路排）；默认本项目爬虫产物')
    args = ap.parse_args()

    kpl = pathlib.Path(args.kpl)
    role_by_name = _role_pools(args.role_pools) if args.role_pools else {}
    OUT.mkdir(parents=True, exist_ok=True)
    result = {'ladder': None, 'kpl': None}

    # 1) 巅峰千强对位表：仍依赖外部 bp-project；没传就保留现有产物，绝不覆盖成空表
    if args.bp_project:
        bp = pathlib.Path(args.bp_project)
        hero_daily = bp / 'data/processed/91m/hero_daily.parquet'
        matchup_dir = bp / 'data/processed/91m/matchup_raw'
        if not hero_daily.exists() or not matchup_dir.is_dir():
            print(f'[WARN] 巅峰千强数据缺失（{hero_daily} / {matchup_dir}），'
                  '跳过 lane_matchups 重建，保留现有文件')
        else:
            hero_stats, window_end = _load_hero_daily(hero_daily, date.today())
            lane_rows = build_lane_matchups(matchup_dir, hero_stats)
            ladder = build_ladder_doc(lane_rows, hero_stats, window_end, role_by_name)
            (OUT / 'lane_matchups.json').write_text(
                json.dumps(ladder, ensure_ascii=False), encoding='utf-8')
            result['ladder'] = {'pairs': len(lane_rows), 'window': window_end,
                                'bracket': BRACKET,
                                'tiers': sum(1 for row in ladder['heroes'].values() if row.get('tier'))}
    else:
        print('[skip] 未提供 --bp-project：保留现有 lane_matchups.json')

    # 2) KPL 组合表：本项目自抓 jsonl → data/facts/kpl_combos.json
    if not kpl.exists():
        print(f'[FAIL] KPL BP 数据不存在：{kpl}；'
              '先跑 python scripts/crawl_kpl_bp.py --since-year 2024 --build', file=sys.stderr)
        return 2
    combos = build_kpl_facts(kpl, args.since_year, args.min_combo_games)
    (OUT / 'kpl_combos.json').write_text(json.dumps(combos, ensure_ascii=False), encoding='utf-8')
    result['kpl'] = {'games': combos['games'], 'pairs': len(combos['pairs']),
                     'trios': len(combos['trios']),
                     'quads': len(combos.get('quads') or []),
                     'lineups': len(combos.get('lineups') or []),
                     'since': args.since_year,
                     'window': f'{combos.get("windowStart")}~{combos.get("windowEnd")}'}

    # 3) KPL 跨阵营克制矩阵：同批数据 → data/facts/kpl_counters.json
    games = kpl_bp.load_games(kpl)
    counters = kpl_bp.build_counters(games, since_year=args.since_year)
    (OUT / 'kpl_counters.json').write_text(json.dumps(counters, ensure_ascii=False),
                                           encoding='utf-8')
    result['counters'] = {'games': counters['games'], 'pairs': len(counters['pairs']),
                          'minN': counters.get('minN'),
                          'window': f'{counters.get("windowStart")}~{counters.get("windowEnd")}'}

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
