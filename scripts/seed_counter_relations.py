"""从 KPL 原始对局挖掘「高准确率」集合克制关系，预置到赛训规则中心。

只做种子：从 `data/kpl/bp_games.jsonl` 的每局双方 5 人 picks 里枚举 size 1..3 的
子集，按「同场对立阵营」统计有向 (A, B) 的场次 / 胜局 / 胜率，再用全量 KPL 的
英雄基准强度算期望胜率、扣出超额胜率，并加 Wilson 95% 下界做小样本保护。
命中的行写成 rules-center-counters-v1 的行结构（heroPairs / comboPairs）。

口径（与 bp_facts 的超额胜率同源，门槛更严，专供「高准确率」初稿）：
* 英雄基准 p = (wins + 30*0.5) / (n + 30)，clip 到 [0.2, 0.8]，取 logit；
* 期望 = sigmoid( mean(logit(A)) - mean(logit(B)) )；
* excess(pp) = (实际胜率 - 期望) * 100；
* Wilson 95% 下界（z=1.96）保护小样本；
* 命中：n >= min_n（1v1=10 / 含 2 人=6 / 含 3 人=4）、excess >= 5.0pp、
  wilson_lower >= 0.55；排除 A/B 有交集或完全相同的方向；
* 排序：excess_pp + (wilson_lower - 0.55) * 50 + log(1 + n)，降序；
* 每类最多 80 条（--limit 可调）。

默认只打印 JSON 摘要，不落盘；--write 时原子写 rules_counters.json，保留已有
人工行（source != 'kpl-seed'），只替换/追加 kpl-seed 行，并保留原 revision 与
每行 1 条 config_history 风格快照（直接放 history 字段，不 import config_history）。

用法：
    python scripts/seed_counter_relations.py                 # 预览（只打印摘要）
    python scripts/seed_counter_relations.py --since-year 2024 --limit 80
    python scripts/seed_counter_relations.py --write          # 落盘
"""
from __future__ import annotations

import argparse
import json
import math
import os
import pathlib
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from itertools import combinations

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_GAMES = ROOT / 'data' / 'kpl' / 'bp_games.jsonl'
DEFAULT_SINCE_YEAR = 2024
DEFAULT_LIMIT = 80

SOURCE = 'kpl-seed'
SCHEMA = 'rules-center-counters-v1'
COUNTERS_FILE = 'rules_counters.json'
SOURCE_SNAPSHOT = 'kpl_bp_games.jsonl'

PRIOR_N = 30.0          # 基准胜率向 0.5 收缩的先验局数
CLIP_LO, CLIP_HI = 0.2, 0.8
Z95 = 1.96
MIN_EXCESS_PP = 5.0     # 超额胜率门槛（百分点）
MIN_WILSON = 0.55       # Wilson 95% 下界门槛
MAX_BATTLE_IDS = 8      # evidence 里最多留 8 个 battleId（不存全部）


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _facts_dir(facts_arg):
    if facts_arg:
        return pathlib.Path(facts_arg)
    try:
        import bp_facts
        return pathlib.Path(bp_facts.FACTS)
    except (ImportError, OSError):
        return ROOT / 'data' / 'facts'


def load_games(path):
    """复用 kpl_bp.load_games（跳过坏行），拿不到模块时退化成裸读。"""
    try:
        import kpl_bp
        return kpl_bp.load_games(path)
    except (ImportError, OSError):
        rows = []
        try:
            text = pathlib.Path(path).read_text(encoding='utf-8')
        except OSError:
            return rows
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get('battleId'):
                rows.append(row)
        return rows


def _heroes(picks, camp):
    """同侧 pick 先按英雄名去重（排序），与 kpl_bp._side_heroes 一致。"""
    return sorted({str(h).strip() for h in ((picks or {}).get(camp) or [])
                   if str(h or '').strip()})


def sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    ez = math.exp(z)
    return ez / (1.0 + ez)


def wilson_lower(p: float, n: int, z: float = Z95) -> float:
    """Wilson 95% 置信区间下界（比例，0..1）。"""
    if n <= 0:
        return 0.0
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / denom
    margin = (z / denom) * math.sqrt(p * (1.0 - p) / n + z2 / (4.0 * n * n))
    return max(0.0, center - margin)


def min_n_for(a, b) -> int:
    """样本门槛按集合大小：1v1=10；含 2 人=6；含 3 人=4。"""
    size = max(len(a), len(b))
    return 10 if size <= 1 else (6 if size == 2 else 4)


# ---------------------------------------------------------------------------
# 英雄基准强度（全量 KPL，n 向 0.5 收缩，clip 后取 logit）
# ---------------------------------------------------------------------------

def hero_logits(all_games):
    n = defaultdict(int)
    wins = defaultdict(int)
    for game in all_games:
        try:
            win_camp = int(game.get('winCamp') or 0)
        except (TypeError, ValueError):
            win_camp = 0
        picks = game.get('picks') or {}
        for camp in ('1', '2'):
            won = 1 if win_camp == int(camp) else 0
            for hero in _heroes(picks, camp):
                n[hero] += 1
                wins[hero] += won
    logits = {}
    for hero, count in n.items():
        p = (wins[hero] + PRIOR_N * 0.5) / (count + PRIOR_N)
        p = min(CLIP_HI, max(CLIP_LO, p))
        logits[hero] = math.log(p / (1.0 - p))
    return logits


# ---------------------------------------------------------------------------
# 有向集合对位统计
# ---------------------------------------------------------------------------

def _new_record():
    return {'n': 0, 'wins': 0, 'dmin': '', 'dmax': '', 'ids': []}


def mine_pairs(games, since_year):
    """每局：camp1 的 25 个子集 A、camp2 的 25 个子集 B，记 (A,B) 与 (B,A) 两向。"""
    store = defaultdict(_new_record)

    def bump(key, won, date, battle_id):
        rec = store[key]
        rec['n'] += 1
        rec['wins'] += won
        if date:
            if not rec['dmin'] or date < rec['dmin']:
                rec['dmin'] = date
            if not rec['dmax'] or date > rec['dmax']:
                rec['dmax'] = date
        if battle_id and len(rec['ids']) < MAX_BATTLE_IDS:
            rec['ids'].append(battle_id)

    included = 0
    dates = []
    for game in games:
        try:
            year = int(game.get('year') or 0)
        except (TypeError, ValueError):
            year = 0
        if year and year < since_year:
            continue
        s1, s2 = _heroes(game.get('picks'), '1'), _heroes(game.get('picks'), '2')
        if not s1 or not s2:
            continue
        try:
            win_camp = int(game.get('winCamp') or 0)
        except (TypeError, ValueError):
            win_camp = 0
        if win_camp not in (1, 2):
            continue
        won1 = 1 if win_camp == 1 else 0
        date = str(game.get('date') or '')[:10]
        battle_id = str(game.get('battleId') or '')
        if date:
            dates.append(date)
        subs1 = [c for size in (1, 2, 3) for c in combinations(s1, size)]
        subs2 = [c for size in (1, 2, 3) for c in combinations(s2, size)]
        for a in subs1:
            for b in subs2:
                bump((a, b), won1, date, battle_id)
                bump((b, a), 1 - won1, date, battle_id)
        included += 1
    window = (min(dates) if dates else '', max(dates) if dates else '')
    return store, included, window


# ---------------------------------------------------------------------------
# 命中判定 + 排序
# ---------------------------------------------------------------------------

def candidates(store, logits):
    out = []
    for (a, b), rec in store.items():
        n = rec['n']
        if n < min_n_for(a, b):
            continue
        if set(a) & set(b) or a == b:      # 有交集 / 完全相同方向，排除
            continue
        p = rec['wins'] / n
        mean_a = sum(logits.get(h, 0.0) for h in a) / len(a)
        mean_b = sum(logits.get(h, 0.0) for h in b) / len(b)
        expected = sigmoid(mean_a - mean_b)
        excess_pp = (p - expected) * 100.0
        if excess_pp < MIN_EXCESS_PP:
            continue
        wilson = wilson_lower(p, n)
        if wilson < MIN_WILSON:
            continue
        # 排序分：excess(fraction)*100 == excess_pp
        score = excess_pp + (wilson - MIN_WILSON) * 50.0 + math.log(1.0 + n)
        out.append({'score': score, 'a': a, 'b': b, 'rec': rec, 'p': p,
                    'expected': expected, 'excess_pp': excess_pp, 'wilson': wilson})
    out.sort(key=lambda item: -item['score'])
    return out


def make_row(prefix, idx, item, now, window):
    a, b, rec = item['a'], item['b'], item['rec']
    n, wins = rec['n'], rec['wins']
    wr = round(item['p'] * 100.0, 1)
    excess_pp = item['excess_pp']
    wilson = item['wilson']
    strength = '强' if excess_pp >= 10.0 and wilson >= 0.6 else '中'
    note = (f'KPL初稿 · n={n} · 胜率{wr:.1f}% · 超额+{excess_pp:.1f}pp · '
            f'Wilson下界{wilson * 100.0:.1f}%')
    return {
        'id': f'kplseed-{prefix}-{idx}',
        'a': '+'.join(a), 'b': '+'.join(b),
        'aHeroes': list(a), 'bHeroes': list(b),
        'strength': strength, 'lane': '全部', 'note': note,
        # 初稿按证据时间窗生效：复盘某赛事时只取当时窗口里筛出的关系，后续重跑不会串味。
        'effective': {'eventId': '', 'eventName': '',
                      'from': rec['dmin'] or window[0], 'to': rec['dmax'] or window[1]},
        'revision': 1,
        'history': [{'at': now, 'revision': 0, 'snapshot': {'source': SOURCE_SNAPSHOT}}],
        'source': SOURCE,
        'evidence': {
            'n': n, 'wins': wins, 'wr': wr,
            'expected': round(item['expected'] * 100.0, 1),
            'excess': round(excess_pp, 1),
            'wilsonLower': round(wilson, 4),
            'windowStart': rec['dmin'] or window[0],
            'windowEnd': rec['dmax'] or window[1],
            'battleIds': rec['ids'],
        },
    }


def split_rows(cands, limit, now, window):
    hero = [x for x in cands if len(x['a']) == 1 and len(x['b']) == 1]
    combo = [x for x in cands if not (len(x['a']) == 1 and len(x['b']) == 1)]
    take = lambda seq: seq if limit <= 0 else seq[:limit]
    rows_h = [make_row('h', i, x, now, window) for i, x in enumerate(take(hero), 1)]
    rows_c = [make_row('c', i, x, now, window) for i, x in enumerate(take(combo), 1)]
    return rows_h, rows_c, len(hero), len(combo)


# ---------------------------------------------------------------------------
# 落盘：保留人工行，只替换/追加 kpl-seed 行
# ---------------------------------------------------------------------------

def atomic_write(path, doc):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='rules-seed-counter-', suffix='.json',
                               dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(doc, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def write_rows(target, rows_h, rows_c, now):
    existing = {}
    try:
        loaded = json.loads(pathlib.Path(target).read_text(encoding='utf-8'))
        if isinstance(loaded, dict):
            existing = loaded
    except (OSError, ValueError):
        pass

    def keep(key):
        return [row for row in (existing.get(key) or [])
                if isinstance(row, dict) and row.get('source') != SOURCE]

    doc = {
        'schema': SCHEMA,
        'revision': int(existing.get('revision') or 0),   # 保留原 revision
        'updatedAt': now,
        'heroPairs': keep('heroPairs') + rows_h,
        'comboPairs': keep('comboPairs') + rows_c,
    }
    for key, value in existing.items():                   # 保留其它顶层字段
        if key not in doc:
            doc[key] = value
    atomic_write(target, doc)
    return len(rows_h) + len(rows_c)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def preview(*, games_path=DEFAULT_GAMES, since_year=DEFAULT_SINCE_YEAR,
            limit=DEFAULT_LIMIT):
    """给 API 用：返回 (hero_rows, combo_rows, meta)，不落盘。"""
    now = _now()
    all_games = load_games(games_path)
    logits = hero_logits(all_games)
    store, included, window = mine_pairs(all_games, since_year)
    cands = candidates(store, logits)
    rows_h, rows_c, n_hero, n_combo = split_rows(cands, limit, now, window)
    meta = {
        'games': {'total': len(all_games), 'included': included,
                  'windowStart': window[0], 'windowEnd': window[1]},
        'candidates': {'total': len(cands), 'hero': n_hero, 'combo': n_combo},
        'rows': {'hero': len(rows_h), 'combo': len(rows_c)},
        'thresholds': {
            'minN': {'1v1': 10, '含2人集合': 6, '含3人集合': 4},
            'minExcessPP': MIN_EXCESS_PP, 'minWilsonLower': MIN_WILSON,
            'z95': Z95, 'priorN': int(PRIOR_N), 'clip': [CLIP_LO, CLIP_HI],
            'limit': limit,
        },
    }
    return rows_h, rows_c, meta


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--games', type=pathlib.Path, default=DEFAULT_GAMES,
                    help='KPL 原始对局 jsonl（默认 data/kpl/bp_games.jsonl）')
    ap.add_argument('--since-year', type=int, default=DEFAULT_SINCE_YEAR,
                    help='只统计该年份及以后的对局（默认 2024）')
    ap.add_argument('--limit', type=int, default=DEFAULT_LIMIT,
                    help='每类最多写入条数（默认 80，0=不限）')
    ap.add_argument('--write', action='store_true', help='真正落盘；默认只打印摘要')
    ap.add_argument('--facts', type=pathlib.Path, default=None,
                    help='事实表目录（默认 bp_facts.FACTS）')
    args = ap.parse_args(argv)

    now = _now()
    all_games = load_games(args.games)
    logits = hero_logits(all_games)                       # 全量 KPL 基准
    store, included, window = mine_pairs(all_games, args.since_year)
    cands = candidates(store, logits)
    rows_h, rows_c, n_hero, n_combo = split_rows(cands, args.limit, now, window)

    written = 0
    target = _facts_dir(args.facts) / COUNTERS_FILE
    if args.write:
        written = write_rows(target, rows_h, rows_c, now)

    def brief(row):
        ev = row['evidence']
        return {'id': row['id'], 'a': row['a'], 'b': row['b'],
                'n': ev['n'], 'wr': ev['wr'], 'expected': ev['expected'],
                'excess': ev['excess'], 'wilsonLower': ev['wilsonLower'],
                'strength': row['strength']}

    summary = {
        'games': {'total': len(all_games), 'included': included,
                  'windowStart': window[0], 'windowEnd': window[1]},
        'candidates': {'total': len(cands), 'hero': n_hero, 'combo': n_combo},
        'rows': {'hero': len(rows_h), 'combo': len(rows_c)},
        'written': written if args.write else 0,
        'wouldWrite': 0 if args.write else len(rows_h) + len(rows_c),
        'target': str(target),
        'thresholds': {
            'minN': {'1v1': 10, '含2人集合': 6, '含3人集合': 4},
            'minExcessPP': MIN_EXCESS_PP, 'minWilsonLower': MIN_WILSON,
            'z95': Z95, 'priorN': int(PRIOR_N), 'clip': [CLIP_LO, CLIP_HI],
            'limit': args.limit,
        },
        'examples': [brief(row) for row in (rows_h + rows_c)[:5]],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
