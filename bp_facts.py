"""把外部事实表（巅峰千强对位 / KPL 组合）查成本局 BP 复盘要的结论。

数据由 `scripts/build_bp_facts.py` 离线生成，落在 `data/facts/`：

* `lane_matchups.json` —— 巅峰千强同分路对位，带**超额胜率**
  （实际对位胜率 − 按两个英雄各自基准算出的期望）。正数＝这对组合本身占优。
* `kpl_combos.json` —— KPL 赛事里同队双人 / 三人 / 整阵容组合的场次与胜率
  （由本项目 `scripts/crawl_kpl_bp.py` 从 KPL 官方接口自抓生成，带 `teams` 归属）。

口径纪律：
* 对位只用**大盘**（巅峰千强），绝不用 KPL——KPL 的英雄对位被「强队选强英雄」污染，
  冷门英雄样本又极少，拿它判克制会把「英雄本身弱」说成「被克制」。
* 组合与赛事命中用 KPL：教练要的是「这套阵容职业赛场见得到」，有就算命中。
* 三张表各带来源与样本，不合成一个分。
"""
from __future__ import annotations

import json
import math
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FACTS = ROOT / 'data' / 'facts'
LANES = ('对抗路', '打野', '中路', '发育路', '游走')

_cache: dict[str, tuple[float, dict]] = {}


def _load(name):
    path = FACTS / name
    try:
        stat = path.stat()
    except OSError:
        return None
    hit = _cache.get(name)
    if hit and hit[0] == stat.st_mtime:
        return hit[1]
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    _cache[name] = (stat.st_mtime, value)
    return value


def _lane_pairs():
    data = _load('lane_matchups.json') or {}
    table = {}
    for row in data.get('pairs') or []:
        table[(row['a'], row['b'])] = row
        table[(row['b'], row['a'])] = {**row, 'a': row['b'], 'b': row['a'],
                                       'wr': round(100 - row['wr'], 1),
                                       'expected': round(100 - row['expected'], 1),
                                       'excess': round(-row['excess'], 1)}
    return data, table


def _camp_counters():
    """营地英雄克制事实表：hero → {counters / counteredBy / duo / trio}。"""
    return _load('camp_counters.json') or {}


def _hero_strength():
    """巅峰千强英雄强度：hero → {wr7d, pick7d, wr30d, pick30d, tier…} + 分路池。

    对位样本对冷门英雄永远凑不够，教练要的「这个英雄在这个分段本身强不强」
    只能从英雄维度给：近 7 天看当下、近 30 天看稳定。
    """
    data = _load('lane_matchups.json') or {}
    return data.get('heroes') or {}, data.get('rolePools') or {}, data


def _tier_of(rank, size):
    """名次 → T1–T4（四等分，每档约四分之一；与 build_bp_facts 同一口径）。"""
    if not size or not rank:
        return None
    index = math.ceil(rank * 4 / size)
    return f'T{max(1, min(4, index))}'


def _lane_strength(heroes, pools, lane, hero):
    """本局这条路上的英雄强度：档位按**这条路**的英雄池排，不按源站主分路。

    源站把李信也放进发育路榜（可走射手的战士），按主分路排会拿他比射手，
    档位没有意义；这里用本局实际分路，跨路重复的英雄各自在路上有自己的名次。
    """
    row = heroes.get(hero) or {}
    if not row:
        return None
    pool = [name for name in (pools.get(lane) or []) if heroes.get(name)]
    tier = row.get('tier')
    rank = row.get('roleRank')
    size = row.get('roleSize')
    role = row.get('role')
    mine = row.get('wrAdj30d') if row.get('wrAdj30d') is not None else row.get('wrAdj')
    if pool and mine is not None:
        # 本局这条路排：池子里没有这个英雄（源站只把他列在别的路）就把他补进来，
        # 名次依旧可解释（「放到这条路大概第几」），不会出现 rank > size。
        names = pool if hero in pool else pool + [hero]
        scores = sorted((heroes[name].get('wrAdj30d') if heroes[name].get('wrAdj30d') is not None
                         else heroes[name].get('wrAdj')) or 0 for name in names)
        rank = 1 + sum(1 for score in scores if score > mine)
        size = len(scores)
        tier = _tier_of(rank, size)
        role = lane              # 本局这条路排的名次，标签也写这条路
    return {
        'wr7d': row.get('wr7d'), 'pick7d': row.get('pick7d'),
        'wr30d': row.get('wr30d'), 'pick30d': row.get('pick30d'),
        'wr': row.get('wr'), 'pick': row.get('pick'),
        'wrAdj30d': row.get('wrAdj30d'), 'wrAdj': row.get('wrAdj'),
        'tier': tier, 'rank': rank, 'size': size, 'role': role,
    }


def _kpl_counters():
    """KPL 跨阵营有向对位表：(a, b) → {n, wins, wr, lastDate, teams}。"""
    data = _load('kpl_counters.json') or {}
    table = {}
    for row in data.get('pairs') or []:
        try:
            table[(str(row['a']), str(row['b']))] = row
        except (KeyError, TypeError):
            continue
    return data, table


def _counter_block(lane_pairs, own_heroes, foe_heroes, heroes_doc=None, pools=None):
    """克制命中：五路对位逐对的两个证据源 + 非同路的重点交叉提示。

    口径纪律（与对位压制同源）：两个来源**永不合并成一个分**——
    * 营地 = 王者营地 App 英雄关系指数（官方编辑口径，无样本量概念）；
    * KPL = 自抓赛事数据的跨阵营有向对位（有样本量，按 n / 胜率判定命中）。

    营地表每个英雄只存「前 3 组」关系，所以一对英雄要从**两侧各查两向**：
    a克b 既可能记在 a 的 counters 里，也可能记在 b 的 counteredBy 里；
    只查我方一侧会漏掉一半命中（2026-11-17 修，本局孙权↔蔡文姬、李信↔鲁班七号
    就是只在对方那一侧才查得到）。
    """
    camp_doc = _camp_counters()
    camp = camp_doc.get('heroes') or {}
    kpl_data, kpl = _kpl_counters()
    heroes_doc = heroes_doc if heroes_doc is not None else {}
    pools = pools or {}

    def camp_index(hero, key, other):
        for item in (camp.get(hero) or {}).get(key) or []:
            if item.get('hero') == other:
                try:
                    return float(item.get('index'))
                except (TypeError, ValueError):
                    return None
        return None

    def camp_pair(a, b):
        """a 对 b：counter＝a 克 b 的指数；countered＝b 克 a 的指数；带来源侧。"""
        counter, counter_via = camp_index(a, 'counters', b), 'mine'
        if counter is None:
            counter, counter_via = camp_index(b, 'counteredBy', a), 'foe'
            if counter is None:
                counter_via = None
        countered, countered_via = camp_index(a, 'counteredBy', b), 'mine'
        if countered is None:
            countered, countered_via = camp_index(b, 'counters', a), 'foe'
            if countered is None:
                countered_via = None
        return counter, counter_via, countered, countered_via

    def kpl_of(a, b):
        row = kpl.get((a, b))
        if not row:
            return None
        return {'n': row.get('n'), 'wins': row.get('wins'), 'wr': row.get('wr'),
                'lastDate': row.get('lastDate'), 'teams': row.get('teams') or []}

    def kpl_view(fwd, rev):
        """KPL 统一成**我方视角**：一条「N 场 · 我方胜率 X%」。

        库里两个方向是分开存的（a→b / b→a），以前两个 chip 一起列，等于把
        「我方 40% / 对方 60%」同一件事说两遍，还容易看反。这里只出一条：
        有 a→b 就用它，否则用 b→a 的补数（100 − 对方胜率）。
        """
        if fwd and fwd.get('n'):
            n, wr, wins, date = fwd['n'], fwd['wr'], fwd.get('wins'), fwd.get('lastDate')
            source = 'fwd'
        elif rev and rev.get('n'):
            n, wr = rev['n'], (100 - rev['wr']) if rev.get('wr') is not None else None
            wins = (n - rev['wins']) if rev.get('wins') is not None else None
            date, source = rev.get('lastDate'), 'rev'
        else:
            return None
        if wr is None:
            return None
        lead = wr - 50
        return {'n': n, 'wins': wins, 'wr': wr, 'lastDate': date, 'source': source,
                'lead': lead,
                'hit': n >= KPL_HIT_N and wr >= KPL_HIT_WR,
                'watch': KPL_WATCH_N <= n < KPL_HIT_N and abs(lead) >= KPL_WATCH_GAP}

    def strength(lane, hero):
        return _lane_strength(heroes_doc, pools, lane, hero)

    lanes = []
    for lane, mine, foe in lane_pairs:
        if not mine or not foe:
            continue
        counter, counter_via, countered, countered_via = camp_pair(mine, foe)
        view = kpl_view(kpl_of(mine, foe), kpl_of(foe, mine))
        lanes.append({'lane': lane, 'mine': mine, 'foe': foe,
                      'kpl': view,
                      'campCounter': counter, 'campCounterVia': counter_via,
                      'campCountered': countered, 'campCounteredVia': countered_via,
                      'kplHit': bool(view and view['hit']),
                      'kplWatch': bool(view and view['watch']),
                      'campHit': _camp_hit(counter),
                      'campCounteredHit': _camp_hit(countered),
                      'campLean': _camp_lean(counter),
                      'campCounteredLean': _camp_lean(countered),
                      'strength': {'mine': strength(lane, mine), 'foe': strength(lane, foe)}})

    # 重点交叉：非同路对位里**有方向**的组合（营地有记录或 KPL 有 3 局），
    # 按证据强度排、限量 6 条。以前只收「命中」，本局五路全空时整块也空；
    # 现在把营地倾向（1.5–2.5）与 KPL 观察值（3–9 局）也收进来，标注写清楚。
    same_lane = {(mine, foe) for lane, mine, foe in lane_pairs}
    notable = []
    for mine in own_heroes:
        for foe in foe_heroes:
            if not mine or not foe or (mine, foe) in same_lane:
                continue
            view = kpl_view(kpl_of(mine, foe), kpl_of(foe, mine))
            counter, counter_via, countered, countered_via = camp_pair(mine, foe)
            # 方向打分：正＝我方占优。命中级证据记 2 分，倾向/观察记 1 分。
            score = 0.0
            if _camp_hit(counter):
                score += 2
            elif _camp_lean(counter):
                score += 1
            if _camp_hit(countered):
                score -= 2
            elif _camp_lean(countered):
                score -= 1
            if view:
                if view['hit']:
                    score += 2 if view['lead'] > 0 else -2
                elif view['watch']:
                    score += 1 if view['lead'] > 0 else -1
            if not score:
                continue
            good = score > 0
            notable.append({
                'mine': mine, 'foe': foe,
                'verdict': '我方克制' if good else '我方被克',
                'score': round(score, 1),
                'kpl': view,
                'kplHit': bool(view and view['hit'] and (view['lead'] > 0) == good),
                'kplWatch': bool(view and view['watch'] and (view['lead'] > 0) == good),
                'camp': counter if good else countered,
                'campVia': counter_via if good else countered_via,
                'campHit': (counter and _camp_hit(counter)) if good else (countered and _camp_hit(countered)),
                'campLean': (counter and _camp_lean(counter)) if good else (countered and _camp_lean(countered)),
                # 两源方向相反：营地和我方打出来的结果不一致，各看各的
                'conflict': _conflict(counter, countered, view),
            })
    notable.sort(key=lambda item: (-abs(item['score']), -(item['camp'] or 0), -((item['kpl'] or {}).get('n') or 0)))
    return {
        'schema': 'bp-counter-facts-v1',
        'camp': {'source': camp_doc.get('source') or '王者营地 App 英雄关系',
                 'capturedAt': camp_doc.get('capturedAt'), 'heroes': len(camp),
                 'perHero': CAMP_LIST_SIZE},
        'kpl': {'source': 'KPL 官方赛事（本项目自抓）', 'games': kpl_data.get('games'),
                'windowStart': kpl_data.get('windowStart'),
                'windowEnd': kpl_data.get('windowEnd'), 'minN': kpl_data.get('minN'),
                'pairs': len(kpl_data.get('pairs') or [])},
        'lanes': lanes, 'notable': notable[:6],
    }


def _camp_hit(index):
    return index is not None and CAMP_HIT_INDEX is not None \
        and isinstance(index, (int, float)) and index >= CAMP_HIT_INDEX


def _camp_lean(index):
    """弱倾向：营地有记录但没到命中门槛（1.5–2.5）。有数就显示，别写成「无记录」。"""
    return (index is not None and isinstance(index, (int, float))
            and CAMP_LEAN_INDEX <= index < CAMP_HIT_INDEX)


def _conflict(counter, countered, view):
    """两源方向相反：营地指数与 KPL 对位胜率一个说我方占优、一个说吃亏。

    只到「有方向」这一层就算（营地 ≥1.5 / KPL ≥3 局），不要求两边都过命中门槛——
    不然会出现「我方被克 + KPL 我方 60% ↑」这种没解释的组合。
    """
    camp_dir = 0
    if counter is not None and (_camp_hit(counter) or _camp_lean(counter)):
        camp_dir = 1
    elif countered is not None and (_camp_hit(countered) or _camp_lean(countered)):
        camp_dir = -1
    kpl_dir = 0
    if view and (view.get('hit') or view.get('watch')):
        kpl_dir = 1 if (view.get('lead') or 0) > 0 else -1
    return bool(camp_dir and kpl_dir and camp_dir != kpl_dir)


def _kpl_hit(row):
    if not row:
        return False
    n, wr = row.get('n'), row.get('wr')
    return bool(n and wr and n >= KPL_HIT_N and wr >= KPL_HIT_WR)


def _kpl_watch(row):
    """观察值：KPL 有 3 局以上、方向偏 5 个点以上，但样本不足以说「命中」。"""
    if not row:
        return False
    n, wr = row.get('n'), row.get('wr')
    return bool(n and wr and n >= KPL_WATCH_N and n < KPL_HIT_N
                and (wr >= 50 + KPL_WATCH_GAP or wr <= 50 - KPL_WATCH_GAP))


def _kpl_combos():
    data = _load('kpl_combos.json') or {}
    pairs, trios, quads, lineups = {}, {}, {}, {}
    for row in data.get('pairs') or []:
        pairs[tuple(row['heroes'])] = row
    for row in data.get('trios') or []:
        trios[tuple(row['heroes'])] = row
    for row in data.get('quads') or []:
        quads[tuple(row['heroes'])] = row
    # 整阵容：key 是 5 个英雄名排序后的元组（老文件没有 lineups 时就是空表）
    for row in data.get('lineups') or []:
        heroes = row.get('heroes') or []
        if len(heroes) == 5:
            lineups[tuple(sorted(heroes))] = row
    return data, pairs, trios, quads, lineups


def _latest_year(data, *groups):
    """最近一个赛季年份：组合行里的最大 year，退化为窗口结束年份。"""
    years = []
    for group in groups:
        for row in group:
            try:
                years.append(int(row.get('year') or 0))
            except (TypeError, ValueError):
                continue
    years = [year for year in years if year]
    if years:
        return max(years)
    window_end = str(data.get('windowEnd') or '')
    return int(window_end[:4]) if window_end[:4].isdigit() else None


def _lineup_of(heroes, kpl_lineups):
    """本队 5 人整阵容命中：排序后去 lineups 里查；不足 5 人视为没命中。"""
    if len(heroes) != 5:
        return None
    row = kpl_lineups.get(tuple(heroes))
    if not row:
        return None
    return {'heroes': row.get('heroes') or list(heroes),
            'n': row.get('n'), 'wins': row.get('wins'), 'wr': row.get('wr'),
            'year': row.get('year'), 'lastDate': row.get('lastDate'),
            'teams': row.get('teams') or []}


def kpl_index() -> dict:
    """公开读取 KPL 组合事实表，供战队页「阵容组合（KPL 命中）」做查表。

    `pairs` / `trios` / `quads` / `lineups` 的 key 都是英雄名排序后的元组，
    查表时不用关心原始行里的英雄顺序。文件读不到时返回空表（页面显示「无命中」），
    不猜组合。
    """
    data, pairs, trios, quads, lineups = _kpl_combos()

    def normalized(table):
        out = {}
        for heroes, row in (table or {}).items():
            try:
                out[tuple(sorted(heroes))] = row
            except TypeError:  # pragma: no cover - 数据表结构异常时跳过，不猜
                continue
        return out

    return {
        'source': 'KPL 官方赛事',
        'games': data.get('games'),
        'sinceYear': data.get('sinceYear'),
        'updatedAt': data.get('updatedAt'),
        'windowStart': data.get('windowStart'),
        'windowEnd': data.get('windowEnd'),
        'latestYear': _latest_year(data, pairs.values(), trios.values(),
                                   quads.values(), lineups.values()),
        'pairs': normalized(pairs),
        'trios': normalized(trios),
        'quads': normalized(quads),
        'lineups': lineups,
    }


def _own_side(detail):
    draft = detail.get('draft') or {}
    picks = draft.get('picks') or {}
    own = detail.get('ownCamp') or 'blue'
    own_key = 'right' if own in ('red', 'right') else 'left'
    foe_key = 'left' if own_key == 'right' else 'right'
    def names(key):
        return [str((row or {}).get('name') or '').strip() for row in (picks.get(key) or [])]
    return names(own_key), names(foe_key)


_SHRINK_K = 40.0
_Z95 = 1.959963984540054

# 克制命中的展示门槛（口径见 _counter_block；数据表存全量，判定在展示层）。
CAMP_HIT_INDEX = 2.5      # 营地克制指数 ≥ 2.5 算「营地克制命中」
CAMP_LEAN_INDEX = 1.5     # 1.5–2.5 算「有记录但不强」，照样显示数值，不写成「无记录」
CAMP_LIST_SIZE = 3        # 营地表每个英雄只抓了前 3 组关系（一对英雄两侧各查两向）
KPL_HIT_N = 10            # KPL 跨阵营对位样本 ≥ 10 局
KPL_HIT_WR = 55.0         # 且胜率 ≥ 55% 算「KPL 克制命中」
KPL_WATCH_N = 3           # 3–9 局、方向偏 5 个点：只作观察值
KPL_WATCH_GAP = 5.0


def _lane_reliability(n, ci_low, ci_high, low_pick=False):
    """证据分级：<50 不足；50–199 或低登场率 → 初步；≥200 可判；≥3000 且 CI 不跨 0 为高。"""
    if not n or n < 50:
        return 'insufficient'
    if low_pick or n < 200:
        return 'preliminary'
    # 单条对位最好有 3000 局样本（教练口径）；200~3000 算「中等」。
    if n >= 3000 and ci_low is not None and ci_high is not None \
            and not (ci_low <= 0 <= ci_high):
        return 'high'
    return 'medium'


def _lane_stats(row):
    n = row.get('n') or 0
    wr = row.get('wr')
    expected = row.get('expected')
    excess = row.get('excess')
    low_pick = bool(row.get('lowPick'))
    if not n or wr is None:
        return {'excessCI': None, 'reliability': 'insufficient',
                'shrunkExcess': excess, 'shrunkWr': wr, 'lowPick': low_pick}
    p = max(0.0, min(1.0, float(wr) / 100.0))
    se = math.sqrt(p * (1 - p) / n)
    lo = p - _Z95 * se
    hi = p + _Z95 * se
    exp = (float(expected) / 100.0) if expected is not None else 0.5
    ci_low = (lo - exp) * 100.0
    ci_high = (hi - exp) * 100.0
    wins = p * n
    alpha = _SHRINK_K * exp
    beta = _SHRINK_K * (1 - exp)
    shrunk_p = (wins + alpha) / (n + alpha + beta)
    shrunk_wr = shrunk_p * 100.0
    base = (expected if expected is not None else 50.0)
    shrunk_excess = shrunk_wr - base
    reliability = _lane_reliability(n, ci_low, ci_high, low_pick)
    return {
        'excessCI': [round(ci_low, 2), round(ci_high, 2)],
        'reliability': reliability,
        'shrunkExcess': round(shrunk_excess, 2),
        'shrunkWr': round(shrunk_wr, 2),
        'lowPick': low_pick,
    }


def _team_gold_at(detail, target_sec):
    """从 detail 的 ownDiff/times 序列取最接近 target_sec 的队伍经济差。"""
    own_diff = detail.get('ownDiff') or []
    times = detail.get('times') or []
    if not own_diff or not times:
        return None
    best = None
    for t, v in zip(times, own_diff):
        if t is None or v is None:
            continue
        if best is None or abs(t - target_sec) < abs(best[0] - target_sec):
            best = (t, v)
    return best[1] if best else None


def for_match(detail):
    """本局三块结论：对位压制（大盘） / 赛事命中 / 联动组合（KPL）。"""
    own_heroes, foe_heroes = _own_side(detail)
    if not own_heroes:
        return None
    lane_data, lane_table = _lane_pairs()
    heroes_doc, pools, _ = _hero_strength()
    combo_data, kpl_pairs, kpl_trios, kpl_quads, kpl_lineups = _kpl_combos()

    # 1) 对位压制：用营地面板里的位置对齐五路
    by_lane = {}
    for player in detail.get('players') or []:
        lane = player.get('position')
        if lane in LANES and player.get('hero'):
            by_lane.setdefault(lane, {})[(player.get('camp') or '')] = player
    own_camp = detail.get('ownCamp') or 'blue'
    foe_camp = 'red' if own_camp == 'blue' else 'blue'
    lanes = []
    lane_pairs = []          # (lane, 我方英雄, 对方英雄)——克制命中按同样五路取对
    for lane in LANES:
        pair = by_lane.get(lane) or {}
        mine, foe = pair.get(own_camp), pair.get(foe_camp)
        if not mine or not foe:
            continue
        lane_pairs.append((lane, mine.get('hero'), foe.get('hero')))
        row = lane_table.get((mine.get('hero'), foe.get('hero')))
        strength = {'mine': _lane_strength(heroes_doc, pools, lane, mine.get('hero')),
                    'foe': _lane_strength(heroes_doc, pools, lane, foe.get('hero'))}
        if not row:
            # 没对位样本时，把两个英雄在巅峰千强的使用率带出去，解释「为什么没有」；
            # 同时给出这两个英雄本身的强度梯度——冷门英雄凑不出对位样本时，这一行
            # 至少还能回答「这手选出来在巅峰千强是个什么强度的英雄」。
            lanes.append({'lane': lane, 'mine': mine.get('hero'), 'foe': foe.get('hero'),
                          'state': 'no-sample', 'n': 0,
                          'minePick': (heroes_doc.get(mine.get('hero')) or {}).get('pick'),
                          'foePick': (heroes_doc.get(foe.get('hero')) or {}).get('pick'),
                          'strength': strength,
                          'excessCI': None, 'reliability': 'low',
                          'shrunkExcess': None, 'shrunkWr': None,
                          'hypothesis': 'no-sample',
                          'realisedEarly': None, 'realisedFinal': None,
                          'attribution': '证据不足',
                          'earlyDiff': _team_gold_at(detail, 240),
                          'finalDiff': _team_gold_at(detail, detail.get('duration') or 0)})
            continue
        excess = row['excess']
        stats = _lane_stats(row)
        ci = stats['excessCI']
        if stats['reliability'] == 'preliminary':
            # 50–199 局：只给方向和区间，不判优势/劣势，也不算兑现。
            state = 'preliminary'
        elif stats['reliability'] == 'insufficient':
            state = 'no-sample'
        elif ci is not None and ci[0] > 0 and excess is not None and excess >= 2:
            state = 'ahead'
        elif ci is not None and ci[1] < 0 and excess is not None and excess <= -2:
            state = 'behind'
        else:
            state = 'even'
        # BP 预期与执行验证：假设（verdict）vs 证据（队伍/个人经济差）
        early_diff = _team_gold_at(detail, 240)
        realised_early = None
        if state in ('ahead', 'behind') and early_diff is not None:
            realised_early = (early_diff > 0) if state == 'ahead' else (early_diff < 0)
        now_diff = None
        # now_diff 由调用方（frontend）的 per-player gold 提供；此处用队伍终局经济差兜底
        final_diff = _team_gold_at(detail, detail.get('duration') or 0)
        realised_final = None
        if state in ('ahead', 'behind') and final_diff is not None:
            realised_final = (final_diff > 0) if state == 'ahead' else (final_diff < 0)
        if state not in ('ahead', 'behind'):
            attribution = '证据不足'
        elif realised_final is True:
            attribution = 'BP兑现'
        elif realised_final is False:
            attribution = 'BP未兑现'
        else:
            attribution = '证据不足'
        lanes.append({'lane': lane, 'mine': mine.get('hero'), 'foe': foe.get('hero'),
                      'state': state, 'n': row['n'], 'wr': row['wr'],
                      'expected': row['expected'], 'excess': excess,
                      'excessCI': stats['excessCI'],
                      'reliability': stats['reliability'],
                      'shrunkExcess': stats['shrunkExcess'],
                      'shrunkWr': stats['shrunkWr'],
                      'lowPick': bool(row.get('lowPick')),
                      'aPick': row.get('aPick'), 'bPick': row.get('bPick'),
                      'strength': strength,
                      'hypothesis': state,
                      'realisedEarly': realised_early,
                      'realisedFinal': realised_final,
                      'attribution': attribution,
                      'earlyDiff': early_diff,
                      'finalDiff': final_diff})

    # 2) 赛事命中：本队 5 人里的双人 / 三人组合，在 KPL 出现过几次
    heroes = sorted({h for h in own_heroes if h})
    pair_hits, trio_hits = [], []
    for i in range(len(heroes)):
        for j in range(i + 1, len(heroes)):
            row = kpl_pairs.get((heroes[i], heroes[j]))
            if row:
                pair_hits.append({'heroes': [heroes[i], heroes[j]], 'n': row['n'],
                                  'wins': row.get('wins'), 'wr': row['wr'],
                                  'year': row.get('year'),
                                  'lastDate': row.get('lastDate'),
                                  'teams': row.get('teams') or []})
            for k in range(j + 1, len(heroes)):
                trow = kpl_trios.get((heroes[i], heroes[j], heroes[k]))
                if trow:
                    trio_hits.append({'heroes': [heroes[i], heroes[j], heroes[k]],
                                      'n': trow['n'], 'wins': trow.get('wins'),
                                      'wr': trow['wr'],
                                      'year': trow.get('year'),
                                      'lastDate': trow.get('lastDate'),
                                      'teams': trow.get('teams') or []})
    pair_hits.sort(key=lambda item: -item['n'])
    trio_hits.sort(key=lambda item: -item['n'])

    # 双方阵容里所有双人组合的 KPL 战绩，供「联动组合」卡片直接查（自家 + 对手）
    combo_index = {}
    for group in (heroes, fh := sorted({h for h in foe_heroes if h})):
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                row = kpl_pairs.get((group[i], group[j]))
                if row:
                    combo_index[f'{group[i]}+{group[j]}'] = {
                        'n': row['n'], 'wins': row.get('wins'), 'wr': row['wr'],
                        'year': row.get('year'), 'lastDate': row.get('lastDate'),
                        'teams': row.get('teams') or []}
                    combo_index[f'{group[j]}+{group[i]}'] = combo_index[f'{group[i]}+{group[j]}']
                trow = None
                if len(group) >= 3:
                    for k in range(j + 1, len(group)):
                        trow = kpl_trios.get((group[i], group[j], group[k]))
                        if trow:
                            combo_index[f'{group[i]}+{group[j]}+{group[k]}'] = {
                                'n': trow['n'], 'wins': trow.get('wins'), 'wr': trow['wr'],
                                'year': trow.get('year'), 'lastDate': trow.get('lastDate'),
                                'teams': (trow.get('teams') or [])[:3]}

    # 「被拆掉的组合」用的 KPL 索引：只看**本局出现过的英雄**（双方选用 + 双方禁用）。
    # 想凑的组合里有一个被 ban / 被抢，那个英雄不在任何阵容里，所以不能只按阵容建表；
    # 20 个英雄的两两/三三组合最多 190 / 1140 对，查表很便宜。
    draft_heroes = sorted({h for h in list(own_heroes) + list(foe_heroes) if h})
    bans = detail.get('draft', {}).get('bans') or {}
    ban_names = set()
    for rows in bans.values():
        for row in rows or []:
            name = str((row or {}).get('name') or '').strip()
            if name:
                ban_names.add(name)
    draft_pool = sorted(set(draft_heroes) | ban_names)
    draft_combos = {'pairs': {}, 'trios': {}}
    for size, table, bucket in ((2, kpl_pairs, 'pairs'), (3, kpl_trios, 'trios')):
        for combo in combinations(draft_pool, size):
            row = table.get(combo)
            if not row:
                continue
            draft_combos[bucket]['+'.join(combo)] = {
                'heroes': list(combo), 'n': row['n'], 'wins': row.get('wins'),
                'wr': row['wr'], 'year': row.get('year'),
                'lastDate': row.get('lastDate'), 'teams': (row.get('teams') or [])[:3]}

    # 对手侧的组合，给 BP 复盘做对照
    foe_pairs = []
    for i in range(len(fh)):
        for j in range(i + 1, len(fh)):
            row = kpl_pairs.get((fh[i], fh[j]))
            if row:
                foe_pairs.append({'heroes': [fh[i], fh[j]], 'n': row['n'],
                                  'wins': row.get('wins'), 'wr': row['wr'],
                                  'year': row.get('year'),
                                  'lastDate': row.get('lastDate'),
                                  'teams': row.get('teams') or []})
    foe_pairs.sort(key=lambda item: -item['n'])

    # 3) 整阵容命中：本队 5 个 pick 排序后整套查（顺序不同算同一套）
    lineup = _lineup_of(heroes, kpl_lineups)
    latest_year = _latest_year(combo_data, kpl_pairs.values(), kpl_trios.values(),
                               kpl_lineups.values())
    total_trios = len(heroes) * (len(heroes) - 1) * (len(heroes) - 2) // 6 if len(heroes) >= 3 else 0

    # 4) 克制命中：KPL 跨阵营对位 + 营地英雄关系，两源分开不合并
    counters = _counter_block(lane_pairs, heroes, fh, heroes_doc, pools)

    # BP 预期与执行验证汇总
    attribution_counts = {}
    for ln in lanes:
        attribution_counts[ln.get('attribution', '证据不足')] = attribution_counts.get(ln.get('attribution', '证据不足'), 0) + 1
    hypothesis = {
        'lanes': [{'lane': ln['lane'], 'hypothesis': ln.get('hypothesis'),
                   'attribution': ln.get('attribution'),
                   'realisedEarly': ln.get('realisedEarly'),
                   'realisedFinal': ln.get('realisedFinal')} for ln in lanes],
        'attributionCounts': attribution_counts,
    }

    return {
        'schema': 'bp-match-facts-v1',
        'ladder': {'source': 'ladder', 'bracket': lane_data.get('bracket'),
                   'windowEnd': lane_data.get('windowEnd'),
                   'strengthWindows': lane_data.get('strengthWindows') or [7, 30],
                   'minN': lane_data.get('minN'), 'minPickRate': lane_data.get('minPickRate'),
                   'lanes': lanes},
        'hypothesis': hypothesis,
        'counters': counters,
        'kpl': {'source': 'kpl', 'sinceYear': combo_data.get('sinceYear'),
                'games': combo_data.get('games'), 'minGames': combo_data.get('minGames'),
                'updatedAt': combo_data.get('updatedAt'),
                'sourceLabel': 'KPL 官方赛事',
                'windowStart': combo_data.get('windowStart'),
                'windowEnd': combo_data.get('windowEnd'),
                'leagueCount': combo_data.get('leagueCount'),
                'latestYear': latest_year,
                'pairs': pair_hits[:6], 'trios': trio_hits[:6], 'foePairs': foe_pairs[:4],
                'hitPairs': len(pair_hits), 'hitTrios': len(trio_hits),
                'totalPairs': len(heroes) * (len(heroes) - 1) // 2,
                'totalTrios': total_trios,
                'comboIndex': combo_index,
                # 被拆组合用：只收「本局出现过的英雄」之间的 KPL 组合（含被 ban 的那个），
                # 这样前端能回答「这套在 KPL 也打过多少场」。
                'draftCombos': draft_combos,
                'lineup': lineup, 'lineupSeen': lineup is not None},
    }
