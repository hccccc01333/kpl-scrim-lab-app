"""大场挖掘层（V2.0 · 2026-11-15）：把一组 BO3/5/7 的几局放在一起做统计与挖掘。

与 `series_engine.analyze_series` 的分工：
- `analyze_series` 负责「关系与事实」：局序、账本、调整、败局恢复、覆盖；
- 本模块负责「证据与对照」：经济差→胜率参考模型、局面形态聚类、BP 价值、
  选手状态、团战/资源转化、历史相似局/相似大场，并汇总成带样本量的结论。

口径（与 docs/series_builder.md 一致）：
- 所有结论都给分母；n<2 的比例一律 None，不补 0。
- 模型、英雄价值、选手基线都排除本系列赛的对局，避免把要解释的结果
  又拿来训练（数据泄漏）；无法排除时在 caveats 里明说。
- 大场内部的小局不是独立实验：跨局结论按「描述性关联」写，不说因果。
- 历史语料可以包含尚未编组的对局；编组只影响大场关系，不影响单局胜负口径。
"""
from __future__ import annotations

import datetime
import math
import random
from collections import Counter, defaultdict
from itertools import combinations

import numpy as np

import hero_archetypes
import hero_capabilities
import series_engine

EB_PRIOR_STRENGTH = 8.0        # 英雄胜率向先验收缩的强度（约等于 8 局）
EB_MIN_APPS = 5                # 「舒适区」至少出现过的局数
KNN_K = 7                      # 历史相似局邻居数
KMEANS_K = 4                   # 局面形态聚类数
WP_MIN_SAMPLES = 60            # 经济差→胜率模型最少样本点
PLAYER_BASELINE_MIN = 4        # 个人基线最少局数
POSITION_BASELINE_MIN = 8      # 同位置基线最少局数
Z_METRIC_FLOOR = {'gpm': 30.0, 'dpm': 400.0, 'part': 5.0, 'kda': 0.8, 'deaths': 1.5}


# ---------------------------------------------------------------- 基础统计
def _num(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) \
        and math.isfinite(float(value)) else None


def _mean(values):
    nums = [v for v in (values or []) if isinstance(v, (int, float)) and math.isfinite(float(v))]
    return sum(nums) / len(nums) if nums else None


def _median(values):
    nums = sorted(v for v in (values or []) if isinstance(v, (int, float)) and math.isfinite(float(v)))
    if not nums:
        return None
    mid = len(nums) // 2
    return nums[mid] if len(nums) % 2 else (nums[mid - 1] + nums[mid]) / 2.0


def _std(values):
    nums = [v for v in (values or []) if isinstance(v, (int, float)) and math.isfinite(float(v))]
    if len(nums) < 2:
        return None
    mean = sum(nums) / len(nums)
    return math.sqrt(sum((v - mean) ** 2 for v in nums) / len(nums))


def _slope(points):
    """最小二乘斜率；points 为 [(x, y)]，x/y 都必须有值。"""
    pairs = [(float(x), float(y)) for x, y in (points or [])
             if isinstance(x, (int, float)) and isinstance(y, (int, float))]
    if len(pairs) < 2:
        return None
    mx = sum(x for x, _ in pairs) / len(pairs)
    my = sum(y for _, y in pairs) / len(pairs)
    denom = sum((x - mx) ** 2 for x, _ in pairs)
    if denom <= 0:
        return None
    return sum((x - mx) * (y - my) for x, y in pairs) / denom


def _rate(k, n):
    return round(k / n * 100, 1) if n else None


def _wilson(k, n, z=1.96):
    """Wilson 95% 区间，返回百分数 [low, high]；n=0 返回 None。"""
    if not n:
        return None
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [round(max(0.0, center - half) * 100, 1), round(min(1.0, center + half) * 100, 1)]


def _shrunk_rate(k, n, prior, strength=EB_PRIOR_STRENGTH):
    """Beta-Binomial 后验均值：向 prior 收缩，strength 约等于先验局数。"""
    return (k + prior * strength) / (n + strength)


def _r(value, digits=1):
    number = _num(value)
    return round(number, digits) if number is not None else None


def _gold(value):
    number = _num(value)
    return f'{number:+,.0f}' if number is not None else '—'


def _pct(value):
    number = _num(value)
    return f'{round(number, 1)}%' if number is not None else '—'


def _clip(value, low=-3.0, high=3.0):
    return max(low, min(high, value))


def _fingerprint(vector):
    """对局过程指纹：10 分钟差 / 终局差 / 时长 / 双方阵容。

    完全相同的指纹几乎不可能是两局独立对局，优先当作重复采集；
    全空指纹不参与去重，避免把缺数据的局误合并。"""
    vector = vector or {}

    def norm(value):
        number = _num(value)
        return round(number, 1) if number is not None else None

    own = tuple(str(hero) for hero in vector.get('heroes') or [] if hero)
    foe = tuple(str(hero) for hero in vector.get('heroesFoe') or [] if hero)
    at10 = norm(vector.get('at10'))
    final = norm(vector.get('finalDiff'))
    duration = norm(vector.get('duration'))
    if at10 is None and final is None and duration is None and not own and not foe:
        return None
    return (at10, final, duration, own, foe)


def _dedupe_corpus(corpus):
    """按过程指纹去重历史语料；重复局只保留一局，并报告重复组。"""
    groups = {}
    for vector in corpus or []:
        fingerprint = _fingerprint(vector)
        if fingerprint is None:
            groups[('unique', str(vector.get('key') or ''))] = [vector]
        else:
            # 去重键带上胜负：内容相同但结果相反的局是矛盾数据，不能悄悄
            # 丢掉一局；目标大场的质量检查仍用不含胜负的指纹，以便提示矛盾。
            groups.setdefault((fingerprint, vector.get('result')), []).append(vector)
    unique, duplicates = [], []
    for items in groups.values():
        unique.append(items[0])
        if len(items) > 1:
            duplicates.append({'keys': [str(item.get('key') or '') for item in items],
                               'count': len(items)})
    unique.sort(key=lambda vector: str(vector.get('key') or ''))
    duplicates.sort(key=lambda item: (-item['count'], item['keys'][0]))
    return {
        'vectors': unique,
        'raw': len(corpus or []),
        'unique': len(unique),
        'duplicateGroups': len(duplicates),
        'duplicateKeys': sum(item['count'] - 1 for item in duplicates),
        'groups': duplicates[:20],
    }


def _draft_valid(own, foe):
    own = [str(hero) for hero in own or [] if hero]
    foe = [str(hero) for hero in foe or [] if hero]
    return bool(own and foe and set(own) != set(foe))


def _target_quality(rows, corpus_stats):
    """目标大场的数据质量：重复局、双方同阵容、BP 名单缺失。"""
    groups = {}
    for row in rows or []:
        fingerprint = _fingerprint(row.get('vector') or {})
        if fingerprint is None:
            continue
        groups.setdefault(fingerprint, []).append(row)
    duplicates = []
    for items in groups.values():
        if len(items) > 1:
            duplicates.append({
                'gameIndexes': [item.get('gameIndex') for item in items],
                'matchKeys': [item.get('matchKey') for item in items],
                'count': len(items),
            })
    duplicates.sort(key=lambda item: (-item['count'], item['gameIndexes'][0] or 0))
    same_roster, invalid = [], []
    for row in rows or []:
        own = list(row.get('heroesOwn') or [])
        foe = list(row.get('heroesFoe') or [])
        if own and foe and set(own) == set(foe):
            same_roster.append({'gameIndex': row.get('gameIndex'),
                                'matchKey': row.get('matchKey'), 'heroes': own})
        if not _draft_valid(own, foe):
            invalid.append({'gameIndex': row.get('gameIndex'), 'matchKey': row.get('matchKey'),
                            'reason': '双方阵容缺失或相同'})
    return {
        'duplicates': duplicates[:20],
        'sameRoster': same_roster[:20],
        'draftInvalid': invalid[:20],
        'corpus': {key: corpus_stats.get(key) for key in
                   ('raw', 'unique', 'duplicateGroups', 'duplicateKeys')}
        if corpus_stats else None,
    }


# ---------------------------------------------------------------- 经济差 → 胜率
def _sigmoid(z):
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    exp = math.exp(z)
    return exp / (1.0 + exp)


def _fit_logistic(X, y, l2=1.0, iters=40, weights=None):
    """L2 逻辑回归（IRLS）。返回原始尺度系数，便于直接解释每 1000 经济差。

    weights 用于类别平衡：语料里我方胜率不是 50% 时，先给胜负样本重新加权，
    让「经济持平」对应的参考胜率回到 50%，避免把队伍整体胜率带进曲线。"""
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    if X.ndim != 2 or len(X) == 0:
        return None
    sample_weight = np.ones(len(X)) if weights is None else np.asarray(weights, dtype=float)
    mean = X.mean(axis=0)
    std = X.std(axis=0)
    std[std < 1e-9] = 1.0
    Z = np.column_stack([np.ones(len(X)), (X - mean) / std])
    beta = np.zeros(Z.shape[1])
    for _ in range(iters):
        eta = Z @ beta
        mu = 1.0 / (1.0 + np.exp(-np.clip(eta, -30, 30)))
        weight = np.clip(mu * (1 - mu), 1e-6, None)
        pseudo = eta + (y - mu) / weight
        combined = sample_weight * weight
        hessian = Z.T @ (combined[:, None] * Z)
        reg = np.eye(Z.shape[1]) * l2
        reg[0, 0] = 0.0
        try:
            step = np.linalg.solve(hessian + reg, Z.T @ (combined * pseudo))
        except np.linalg.LinAlgError:
            break
        if np.max(np.abs(step - beta)) < 1e-8:
            beta = step
            break
        beta = step
    raw = beta[1:] / std
    intercept = beta[0] - float(np.sum(beta[1:] * mean / std))
    return {'intercept': float(intercept), 'coef': [float(v) for v in raw]}


def _predict(model, diff, minute):
    if not model:
        return None
    diff = _num(diff)
    minute = _num(minute)
    if diff is None or minute is None:
        return None
    diff = max(-15000.0, min(15000.0, diff))
    minute = max(0.0, min(40.0, minute))
    x1 = diff / 1000.0
    x2 = x1 * (minute / 10.0)
    eta = model['intercept'] + model['coef'][0] * x1 + model['coef'][1] * x2
    return max(1.0, min(99.0, _sigmoid(eta) * 100))


def _auc(y, scores):
    pairs = sorted(zip(scores, y), key=lambda item: item[0])
    n = len(pairs)
    if not n:
        return None
    ranks = [0.0] * n
    index = 0
    while index < n:
        end = index
        while end < n and pairs[end][0] == pairs[index][0]:
            end += 1
        rank = (index + 1 + end) / 2.0
        for pos in range(index, end):
            ranks[pos] = rank
        index = end
    positives = sum(1 for _, label in pairs if label)
    negatives = n - positives
    if not positives or not negatives:
        return None
    rank_sum = sum(ranks[i] for i in range(n) if pairs[i][1])
    return (rank_sum - positives * (positives + 1) / 2.0) / (positives * negatives)


def _wp_samples(corpus, exclude_keys):
    samples = []
    for vector in corpus or []:
        if str(vector.get('key') or '') in exclude_keys:
            continue
        result = vector.get('result')
        if result not in ('win', 'loss'):
            continue
        for index, diff in enumerate(vector.get('g') or []):
            if index == 0 or _num(diff) is None:
                continue
            minute = index * 5.0
            samples.append(([diff / 1000.0, diff / 1000.0 * (minute / 10.0)],
                            1 if result == 'win' else 0,
                            str(vector.get('key') or ''), minute))
    return samples


def _class_weights(labels):
    """把胜负样本重新加权到各 50%，让经济持平的参考胜率回到 50%。"""
    base = _mean(labels)
    if base is None or base <= 0 or base >= 1:
        return None
    return [0.5 / base if label else 0.5 / (1 - base) for label in labels]


def _fit_wp_model(corpus, exclude_keys):
    samples = _wp_samples(corpus or [], exclude_keys)
    if len(samples) < WP_MIN_SAMPLES:
        return None
    X = [item[0] for item in samples]
    y = [item[1] for item in samples]
    model = _fit_logistic(X, y, l2=1.0, weights=_class_weights(y))
    if model is None:
        return None
    groups = sorted({item[2] for item in samples})
    auc = auc_at10 = n_at10 = None
    if len(groups) >= 8:
        shuffled = list(groups)
        random.Random(17).shuffle(shuffled)
        folds = {group: index % 5 for index, group in enumerate(shuffled)}
        held_out = []
        for fold in range(5):
            train = [item for item in samples if folds[item[2]] != fold]
            test = [item for item in samples if folds[item[2]] == fold]
            if not train or not test:
                continue
            train_labels = [item[1] for item in train]
            fitted = _fit_logistic([item[0] for item in train], train_labels, l2=1.0,
                                   weights=_class_weights(train_labels))
            if fitted is None:
                continue
            for item in test:
                held_out.append((item[1], _predict(fitted, item[0][0] * 1000, item[3]), item[3]))
        if held_out:
            auc = _auc([row[0] for row in held_out], [row[1] for row in held_out])
            at10 = [(label, score) for label, score, minute in held_out if abs(minute - 10.0) < 0.01]
            n_at10 = len(at10)
            if at10:
                auc_at10 = _auc([row[0] for row in at10], [row[1] for row in at10])
    coef = model['coef']
    # 参考曲线以「经济持平、0 分钟」为 50% 中性锚点：语料的整体胜率不应把
    # 每条曲线整体抬高/压低。AUC 对截距平移不变，只影响可读性。
    model['intercept'] = 0.0
    base = _mean(y)
    return {
        **model,
        'anchor': '经济持平、0 分钟 = 50%',
        'n': len(samples),
        'games': len(groups),
        'baseRate': round(float(base) * 100, 1) if base is not None else None,
        'auc': _r(auc, 3),
        'aucAt10': _r(auc_at10, 3),
        'nAt10': n_at10,
        'per1000At10': _r(coef[0] + coef[1], 3),
        'per1000At20': _r(coef[0] + 2 * coef[1], 3),
        'reliable': bool(auc is not None and auc >= 0.6 and len(samples) >= 100),
    }


def _wp_curve(vector, model):
    if not model:
        return None
    vector = vector or {}
    points = []
    base = _predict(model, 0, 0)
    if base is not None:
        points.append({'t': 0, 'diff': 0, 'p': round(base, 1)})
    for index, diff in enumerate(vector.get('g') or []):
        if index == 0 or _num(diff) is None:
            continue
        minute = index * 5.0
        probability = _predict(model, diff, minute)
        if probability is None:
            continue
        points.append({'t': index * 300, 'diff': round(diff, 1), 'p': round(probability, 1)})
    duration = _num(vector.get('duration'))
    final = _num(vector.get('finalDiff'))
    if duration and final is not None and (not points or points[-1]['t'] < duration - 60):
        probability = _predict(model, final, duration / 60.0)
        if probability is not None:
            points.append({'t': round(duration), 'diff': round(final, 1), 'p': round(probability, 1)})
    if len(points) < 2:
        return None
    values = [point['p'] for point in points]
    deltas = [(points[index]['p'] - points[index - 1]['p'], points[index - 1], points[index])
              for index in range(1, len(points))]
    rise = max(deltas, key=lambda row: row[0]) if deltas else None
    drop = min(deltas, key=lambda row: row[0]) if deltas else None
    biggest = max(deltas, key=lambda row: abs(row[0])) if deltas else None
    at10 = next((point for point in points if abs(point['t'] - 600) <= 30), None)
    return {
        'points': points,
        'at10': at10['p'] if at10 else None,
        'end': points[-1]['p'],
        'max': max(values),
        'min': min(values),
        'swing': round(abs(biggest[0]), 1) if biggest else None,
        'turning': ({'t': biggest[2]['t'], 'from': biggest[1]['p'], 'to': biggest[2]['p'],
                     'delta': round(biggest[0], 1)} if biggest else None),
        'maxRise': ({'t': rise[2]['t'], 'delta': round(rise[0], 1)} if rise else None),
        'maxDrop': ({'t': drop[2]['t'], 'delta': round(drop[0], 1)} if drop else None),
        'comeback': bool(min(values) < 35 and vector.get('result') == 'win'),
        'collapse': bool(max(values) > 65 and vector.get('result') == 'loss'),
    }


# ---------------------------------------------------------------- 局面形态聚类
def _sqdist(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b))


def _kmeans(points, k=KMEANS_K, iters=40, seed=11):
    if len(points) < k:
        return None
    rng = random.Random(seed)
    centers = [list(points[rng.randrange(len(points))])]
    while len(centers) < k:
        distances = [min(_sqdist(point, center) for center in centers) for point in points]
        total = sum(distances)
        if total <= 0:
            break
        target = rng.random() * total
        running = 0.0
        for point, distance in zip(points, distances):
            running += distance
            if running >= target:
                centers.append(list(point))
                break
        else:
            centers.append(list(points[rng.randrange(len(points))]))
    labels = [0] * len(points)
    for _ in range(iters):
        changed = False
        for index, point in enumerate(points):
            best = min(range(len(centers)), key=lambda slot: _sqdist(point, centers[slot]))
            if labels[index] != best:
                labels[index] = best
                changed = True
        for slot in range(len(centers)):
            group = [points[index] for index in range(len(points)) if labels[index] == slot]
            if group:
                centers[slot] = [sum(point[dim] for point in group) / len(group)
                                 for dim in range(len(group[0]))]
        if not changed:
            break
    counts = Counter(labels)
    return {'centers': centers, 'labels': labels, 'counts': dict(counts)}


def _shape_label(center):
    early = sum(center[:2]) / 2.0
    mid = sum(center[2:4]) / 2.0
    late = sum(center[4:]) / 2.0
    if early > 0.3 and late > 0.3:
        return '全程压制'
    if early < -0.3 and late > 0.3:
        return '逆风翻盘'
    if early > 0.3 and late < -0.3:
        return '优势被翻'
    if early < -0.3 and late < -0.3:
        return '全程逆风'
    if late - early > 4.0:
        return '强后程发力'
    if late - early > 0.5:
        return '后程发力'
    if early - late > 4.0:
        return '强后程失守'
    if early - late > 0.5:
        return '后程失守'
    return '拉锯'


def _shape_clusters(corpus):
    points = []
    for vector in corpus or []:
        shape = [v for v in (vector.get('s') or []) if _num(v) is not None]
        if len(shape) != 6:
            continue
        points.append([max(-15.0, min(15.0, value / 1000.0)) for value in shape])
    if len(points) < 8:
        return None
    k = min(KMEANS_K, max(2, len(points) // 8))
    fitted = _kmeans(points, k=k)
    if not fitted:
        return None
    # 合并语义与形状都几乎相同的簇：小语料里 k-means 常把同一种走势
    # 拆成两个只差几十金币的簇（如两个「后程失守」），合起来更可读。
    merged = []
    for slot, center in enumerate(fitted['centers']):
        label = _shape_label(center)
        count = int(fitted['counts'].get(slot, 0))
        for item in merged:
            if item['label'] != label:
                continue
            if math.sqrt(_sqdist(center, item['center'])) >= 1.5:
                continue
            total = item['n'] + count
            if total:
                item['center'] = [(item['center'][dim] * item['n'] + center[dim] * count) / total
                                  for dim in range(len(center))]
            item['n'] = total
            break
        else:
            merged.append({'label': label, 'center': list(center), 'n': count})
    merged.sort(key=lambda item: (sum(item['center'][:2]) + sum(item['center'][4:])))
    labels = []
    used = Counter()
    for item in merged:
        label = item['label']
        used[label] += 1
        if used[label] > 1:
            label = f'{label}·{used[label]}'
        center = item['center']
        labels.append({
            'id': f'C{len(labels) + 1}',
            'label': label,
            'center': [round(value, 2) for value in center],
            'n': int(item['n']),
            'early': round(sum(center[:2]) / 2.0, 2),
            'mid': round(sum(center[2:4]) / 2.0, 2),
            'late': round(sum(center[4:]) / 2.0, 2),
        })
    return {'k': len(labels), 'n': len(points), 'clusters': labels}


def _assign_cluster(vector, clusters):
    if not clusters:
        return None
    shape = [_num(v) for v in (vector.get('s') or [])]
    if len(shape) != 6 or any(value is None for value in shape):
        return None
    point = [max(-15.0, min(15.0, value / 1000.0)) for value in shape]
    best = min(clusters['clusters'], key=lambda item: _sqdist(point, item['center']))
    distance = math.sqrt(_sqdist(point, best['center']))
    return {'id': best['id'], 'label': best['label'], 'distance': round(distance, 2)}


# ---------------------------------------------------------------- 英雄价值
def _hero_stats(corpus, exclude_keys):
    stats = defaultdict(lambda: {
        'apps': 0, 'wins': 0, 'ownApps': 0, 'ownWins': 0,
        'foeApps': 0, 'foeWins': 0, 'bans': 0, 'ownBans': 0, 'foeBans': 0,
    })
    games = own_apps = own_wins = foe_apps = foe_wins = invalid_games = 0
    for vector in corpus or []:
        if str(vector.get('key') or '') in exclude_keys:
            continue
        result = vector.get('result')
        if result not in ('win', 'loss'):
            continue
        own_picks = [str(hero) for hero in vector.get('heroes') or [] if hero]
        foe_picks = [str(hero) for hero in vector.get('heroesFoe') or [] if hero]
        if not _draft_valid(own_picks, foe_picks):
            invalid_games += 1
            continue
        games += 1
        for hero in own_picks:
            row = stats[hero]
            row['apps'] += 1
            row['ownApps'] += 1
            own_apps += 1
            if result == 'win':
                row['wins'] += 1
                row['ownWins'] += 1
                own_wins += 1
        for hero in foe_picks:
            row = stats[hero]
            row['apps'] += 1
            row['foeApps'] += 1
            foe_apps += 1
            if result == 'loss':
                row['wins'] += 1
                row['foeWins'] += 1
                foe_wins += 1
        for hero in vector.get('bansOwn') or []:
            if hero:
                stats[str(hero)]['bans'] += 1
                stats[str(hero)]['ownBans'] += 1
        for hero in vector.get('bansFoe') or []:
            if hero:
                stats[str(hero)]['bans'] += 1
                stats[str(hero)]['foeBans'] += 1
    base_own = own_wins / own_apps if own_apps else 0.5
    base_foe = foe_wins / foe_apps if foe_apps else 0.5
    heroes = {}
    for hero, row in stats.items():
        value = _shrunk_rate(row['wins'], row['apps'], 0.5) - 0.5
        own_value = _shrunk_rate(row['ownWins'], row['ownApps'], base_own) - base_own
        foe_value = _shrunk_rate(row['foeWins'], row['foeApps'], base_foe) - base_foe
        presence = min(1.0, (row['apps'] + row['bans']) / max(2 * games, 1))
        heroes[hero] = {
            'name': hero,
            'apps': row['apps'], 'wins': row['wins'],
            'rate': _rate(row['wins'], row['apps']),
            'ci': _wilson(row['wins'], row['apps']),
            'value': round(value, 3),
            'ownApps': row['ownApps'], 'ownWins': row['ownWins'],
            'ownRate': _rate(row['ownWins'], row['ownApps']),
            'ownValue': round(own_value, 3),
            'foeApps': row['foeApps'], 'foeWins': row['foeWins'],
            'foeRate': _rate(row['foeWins'], row['foeApps']),
            'foeValue': round(foe_value, 3),
            'bans': row['bans'], 'ownBans': row['ownBans'], 'foeBans': row['foeBans'],
            'presence': round(presence, 3),
        }
    return {'heroes': heroes, 'games': games, 'baseOwn': round(base_own, 3),
            'baseFoe': round(base_foe, 3), 'ownApps': own_apps, 'foeApps': foe_apps,
            'invalidGames': invalid_games}


def _hero_row(name, stats):
    info = (stats.get('heroes') or {}).get(str(name))
    if info:
        return info
    return {
        'name': str(name), 'apps': 0, 'wins': 0, 'rate': None, 'ci': None, 'value': 0.0,
        'ownApps': 0, 'ownWins': 0, 'ownRate': None, 'ownValue': 0.0,
        'foeApps': 0, 'foeWins': 0, 'foeRate': None, 'foeValue': 0.0,
        'bans': 0, 'ownBans': 0, 'foeBans': 0, 'presence': 0.0,
    }


def _hero_tags(info, stats):
    tags = []
    own_value = _num(info.get('ownValue')) or 0.0
    value = _num(info.get('value')) or 0.0
    apps = int(info.get('apps') or 0)
    own_apps = int(info.get('ownApps') or 0)
    bans = int(info.get('bans') or 0)
    presence = _num(info.get('presence')) or 0.0
    if own_apps >= EB_MIN_APPS and own_value >= 0.05:
        tags.append('comfort')
    if own_apps and own_apps <= 2:
        tags.append('stretch')
    if apps == 0:
        tags.append('banOnly' if bans else 'novel')
    elif own_apps == 0:
        tags.append('unpicked')
    if apps >= 8 and value >= 0.05:
        tags.append('strong')
    elif apps >= 8 and value <= -0.05:
        tags.append('weak')
    if presence >= 0.6:
        tags.append('contested')
    return tags


# ---------------------------------------------------------------- 选手基线
def _player_metrics(player):
    kills = _num(player.get('k'))
    deaths = _num(player.get('d'))
    assists = _num(player.get('a'))
    kda = (kills + assists) / max(1.0, deaths) \
        if kills is not None and deaths is not None and assists is not None else None
    return {
        'kda': kda,
        'gpm': _num(player.get('gpm')),
        'dpm': _num(player.get('dpm')),
        'part': _num(player.get('part')),
        'deaths': deaths,
    }


PLAYER_WINDOWS = (('d1', '昨天', 1), ('d7', '近 7 天', 7), ('d30', '近 30 天', 30),
                  ('d90', '近 3 个月', 90), ('d180', '近 6 个月', 180),
                  ('d365', '近 1 年', 365), ('d730', '近 2 年', 730))

# 每个分路看的指标不一样：游走不看经济与输出，改看承伤/控制/治疗；
# 发育路额外看推塔；对抗路额外看承伤。这里就是前端分路卡片的指标来源。
LANE_METRICS = {
    '对抗路': ('kda', 'gpm', 'dpm', 'part', 'laneGold', 'tpm'),
    '打野': ('kda', 'gpm', 'dpm', 'part', 'laneGold', 'tpm'),
    '中路': ('kda', 'gpm', 'dpm', 'part', 'laneGold'),
    '发育路': ('kda', 'gpm', 'dpm', 'part', 'laneGold', 'twr'),
    '游走': ('kda', 'part', 'tpm', 'ctrlpm', 'heal'),
}
METRIC_META = {
    'kda': ('KDA', 2, ''), 'gpm': ('分均经济', 0, ''), 'dpm': ('分均输出', 0, ''),
    'part': ('参团率', 1, '%'), 'laneGold': ('对位经济', 0, '/分'),
    'tpm': ('分均承伤', 0, ''), 'ctrlpm': ('分均控制', 1, ''), 'heal': ('分均治疗', 0, ''),
    'twr': ('分均推塔', 0, ''),
}
Z_FLOOR_EXTRA = {'tpm': 400.0, 'ctrlpm': 0.5, 'heal': 300.0, 'twr': 100.0, 'laneGold': 40.0}
LANE_ORDER = ('对抗路', '打野', '中路', '发育路', '游走')


def _pl_metrics(player, vector, position, side):
    """单局单人的分路指标；承伤/控制/治疗/推塔都换算到每分钟。"""
    kills, deaths, assists = _num(player.get('k')), _num(player.get('d')), _num(player.get('a'))
    kda = (kills + assists) / max(1.0, deaths) \
        if None not in (kills, deaths, assists) else None
    lane = (vector.get('lanes') or {}).get(position) or {}
    lane_gold = _num(lane.get('gold'))
    if lane_gold is not None and side == 'foe':
        lane_gold = -lane_gold
    return {
        'kda': kda, 'gpm': _num(player.get('gpm')), 'dpm': _num(player.get('dpm')),
        'part': _num(player.get('part')), 'deaths': deaths,
        'tpm': _num(player.get('tpm')), 'ctrlpm': _num(player.get('ctrlpm')),
        'heal': _num(player.get('heal')), 'twr': _num(player.get('twr')),
        'laneGold': lane_gold,
    }


def _player_baselines(corpus, exclude_keys, since=None, until=None):
    positions = defaultdict(lambda: defaultdict(list))
    players = defaultdict(lambda: defaultdict(list))
    archetypes = defaultdict(Counter)
    games = defaultdict(int)
    for vector in corpus or []:
        if str(vector.get('key') or '') in exclude_keys:
            continue
        date = str(vector.get('date') or '')[:10]
        if since and date and date < since:
            continue
        if until and date and date > until:
            continue
        own_camp = vector.get('camp')
        games['n'] += 1
        for player in vector.get('pl') or []:
            position = str(player.get('pos') or '未知')
            side = 'own' if player.get('camp') == own_camp else 'foe'
            metrics = _pl_metrics(player, vector, position, side)
            for key, value in metrics.items():
                if value is None:
                    continue
                positions[position][key].append(value)
                if side == 'own' and player.get('name'):
                    players[(str(player['name']), position)][key].append(value)
            if side == 'own' and player.get('name') and player.get('arch'):
                archetypes[position][str(player['arch'])] += 1
    return {'positions': positions, 'players': players,
            'archetypes': archetypes, 'games': games['n']}


def _baseline_stats(values):
    values = [v for v in (values or []) if _num(v) is not None]
    if len(values) < 2:
        return None
    return {'mean': _mean(values), 'std': _std(values), 'n': len(values)}


def _z_score(value, baseline, floor):
    if value is None or not baseline:
        return None
    std = max(_num(baseline.get('std')) or 0.0, floor)
    mean = _num(baseline.get('mean'))
    if mean is None:
        return None
    return _clip((value - mean) / std)


# ---------------------------------------------------------------- 相似局 / 相似大场
def _game_feature(vector):
    vector = vector or {}
    seg = vector.get('seg') or {}
    fight = vector.get('fight') or {}
    decided = _num(fight.get('decidedN')) or 0.0
    won = _num(fight.get('decidedWin')) or 0.0
    obj10 = vector.get('objAt10') or {}
    dragon = (_num(obj10.get('dragonOwn')) - _num(obj10.get('dragonFoe'))) \
        if _num(obj10.get('dragonOwn')) is not None and _num(obj10.get('dragonFoe')) is not None else None
    tower = (_num(obj10.get('towerOwn')) - _num(obj10.get('towerFoe'))) \
        if _num(obj10.get('towerOwn')) is not None and _num(obj10.get('towerFoe')) is not None else None
    at10 = _num(vector.get('at10'))
    duration = _num(vector.get('duration'))
    return [
        at10 / 1000.0 if at10 is not None else None,
        _num(seg.get('early')) / 1000.0 if _num(seg.get('early')) is not None else None,
        _num(seg.get('mid')) / 1000.0 if _num(seg.get('mid')) is not None else None,
        _num(seg.get('late')) / 1000.0 if _num(seg.get('late')) is not None else None,
        won / decided if decided else None,
        dragon,
        tower,
        duration / 1200.0 if duration is not None else None,
    ]


def _feature_matrix(corpus, exclude_keys):
    rows = []
    for vector in corpus or []:
        key = str(vector.get('key') or '')
        if key in exclude_keys or vector.get('result') not in ('win', 'loss'):
            continue
        feature = _game_feature(vector)
        if sum(1 for value in feature if value is not None) < 2:
            continue
        rows.append({'key': key, 'vector': vector, 'feature': feature, 'result': vector.get('result')})
    if not rows:
        return None
    width = len(rows[0]['feature'])
    means, stds = [], []
    for column in range(width):
        values = [row['feature'][column] for row in rows if row['feature'][column] is not None]
        mean = _mean(values) or 0.0
        std = max(_std(values) or 0.0, 1e-6)
        means.append(mean)
        stds.append(std)
    for row in rows:
        row['z'] = [((value if value is not None else means[column]) - means[column]) / stds[column]
                    for column, value in enumerate(row['feature'])]
    return {'rows': rows, 'means': means, 'stds': stds}


def _knn_neighbors(feature, matrix, k=KNN_K):
    if not matrix or not matrix.get('rows'):
        return None
    means, stds = matrix['means'], matrix['stds']
    target = [((value if value is not None else means[index]) - means[index]) / stds[index]
              for index, value in enumerate(feature)]
    scored = []
    for row in matrix['rows']:
        distance = math.sqrt(sum((a - b) ** 2 for a, b in zip(target, row['z'])))
        scored.append((distance, row))
    scored.sort(key=lambda item: item[0])
    top = scored[:k]
    wins = sum(1 for _, row in top if row['result'] == 'win')
    smoothed = (wins + 2.0) / (len(top) + 4.0) * 100.0
    return {
        'n': len(top),
        'wins': wins,
        'expectedWinRate': round(smoothed, 1),
        'rawWinRate': _rate(wins, len(top)),
        'ci': _wilson(wins, len(top)),
        'smoothing': 'Beta(2,2) 先验平滑，避免 7 个邻居全胜/全负给出 100%/0%',
        'neighbors': [
            {
                'matchKey': row['key'],
                'date': row['vector'].get('date'),
                'opponent': row['vector'].get('opponent'),
                'result': row['result'],
                'at10': row['vector'].get('at10'),
                'duration': row['vector'].get('duration'),
                'distance': round(distance, 3),
            }
            for distance, row in top[:5]
        ],
    }


def _series_feature(rows):
    at10 = [r.get('at10') for r in rows if _num(r.get('at10')) is not None]
    early, mid, late, fight, dragon, tower, duration = [], [], [], [], [], [], []
    heroes = set()
    for row in rows:
        vector = row.get('vector') or {}
        seg = vector.get('seg') or {}
        for target, key in ((early, 'early'), (mid, 'mid'), (late, 'late')):
            value = _num(seg.get(key))
            if value is not None:
                target.append(value)
        rate = row.get('fightRate')
        if isinstance(rate, (int, float)):
            fight.append(rate)
        for target, key in ((dragon, 'dragon10Diff'), (tower, 'tower10Diff')):
            value = _num(row.get(key))
            if value is not None:
                target.append(value)
        value = _num(vector.get('duration'))
        if value is not None:
            duration.append(value)
        heroes.update(str(h) for h in (row.get('heroesOwn') or []) if h)
    return {
        'at10': _mean(at10),
        'early': _mean(early),
        'mid': _mean(mid),
        'late': _mean(late),
        'fight': _mean(fight),
        'dragon10': _mean(dragon),
        'tower10': _mean(tower),
        'duration': _mean(duration),
        'pool': len(heroes) / max(len(rows) * 5, 1),
        'games': len(rows),
    }


def _series_similarity(target, history):
    feature_keys = ('at10', 'early', 'mid', 'late', 'fight', 'dragon10', 'tower10', 'duration', 'pool')
    candidates = [{'id': target['series'].get('id'), 'series': target['series'],
                   'feature': target['feature'], 'rows': target.get('rows') or []}]
    for item in history:
        candidates.append({'id': item['series'].get('id'), 'series': item['series'],
                           'feature': item['feature'], 'rows': item.get('rows') or []})
    if len(candidates) < 3:
        return {'available': False, 'series': [], 'note': '历史大场不足 3 组，暂不做相似检索。'}
    means, stds = {}, {}
    for key in feature_keys:
        values = [item['feature'].get(key) for item in candidates
                  if _num(item['feature'].get(key)) is not None]
        means[key] = _mean(values) or 0.0
        stds[key] = max(_std(values) or 0.0, 1e-6)

    def vector(feature):
        return [((_num(feature.get(key)) if _num(feature.get(key)) is not None else means[key]) - means[key]) / stds[key]
                for key in feature_keys]

    source = vector(target['feature'])
    scored = []
    for item in candidates[1:]:
        other = vector(item['feature'])
        dot = sum(a * b for a, b in zip(source, other))
        norm = math.sqrt(sum(a * a for a in source)) * math.sqrt(sum(b * b for b in other))
        score = dot / norm if norm else 0.0
        scored.append((score, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    result = []
    for score, item in scored[:3]:
        rows = item.get('rows') or []
        wins = sum(1 for row in rows if row.get('result') == 'win')
        losses = sum(1 for row in rows if row.get('result') == 'loss')
        differences = []
        for key, label, unit in (
            ('at10', '10 分钟差', 'gold'), ('late', '10 分钟后', 'gold'),
            ('fight', '团战胜率', 'pct'), ('early', '0–4 分钟', 'gold'),
            ('mid', '4–10 分钟', 'gold'), ('duration', '平均时长', 'seconds'),
        ):
            ours, theirs = target['feature'].get(key), item['feature'].get(key)
            if _num(ours) is None or _num(theirs) is None:
                continue
            differences.append({'key': key, 'label': label, 'unit': unit,
                                'us': _r(ours, 1), 'them': _r(theirs, 1),
                                'delta': _r(ours - theirs, 1)})
        result.append({
            'seriesId': item['id'],
            'opponent': item['series'].get('opponent'),
            'date': item['series'].get('startAt'),
            'bestOf': item['series'].get('bestOf'),
            'score': {'us': wins, 'them': losses},
            'games': len(rows),
            'completion': item['series'].get('completion'),
            'similarity': round(score, 3),
            'differences': differences,
        })
    return {'available': True, 'series': result, 'note': '余弦相似度基于经济阶段、团战、资源与时长的 z-score；只做历史对照。'}


# ---------------------------------------------------------------- 目标大场
def _event_known(vector):
    first = vector.get('first') or {}
    if any(first.get(key) is not None for key in ('bloodT', 'dragonT', 'towerT')):
        return True
    fight = vector.get('fight') or {}
    return (_num(fight.get('n')) or 0) > 0


def _objectives(vector, at10=False):
    if not _event_known(vector):
        return {'dragonOwn': None, 'dragonFoe': None, 'towerOwn': None, 'towerFoe': None,
                'dragonDiff': None, 'towerDiff': None, 'net': None}
    source = (vector.get('objAt10') if at10 else vector.get('obj')) or {}
    own_dragon, foe_dragon = _num(source.get('dragonOwn')), _num(source.get('dragonFoe'))
    own_tower, foe_tower = _num(source.get('towerOwn')), _num(source.get('towerFoe'))
    dragon_diff = own_dragon - foe_dragon if own_dragon is not None and foe_dragon is not None else None
    tower_diff = own_tower - foe_tower if own_tower is not None and foe_tower is not None else None
    net = (dragon_diff or 0) + (tower_diff or 0) \
        if dragon_diff is not None or tower_diff is not None else None
    return {'dragonOwn': own_dragon, 'dragonFoe': foe_dragon,
            'towerOwn': own_tower, 'towerFoe': foe_tower,
            'dragonDiff': dragon_diff, 'towerDiff': tower_diff, 'net': net}


def _fight_rate(vector):
    fight = vector.get('fight') or {}
    decided = _num(fight.get('decidedN')) or 0.0
    won = _num(fight.get('decidedWin')) or 0.0
    return won / decided * 100.0 if decided else None


def _phase_values(row):
    vector = row.get('vector') or {}
    seg = vector.get('seg') or {}
    early = _num(seg.get('early'))
    mid = _num(seg.get('mid'))
    late = _num(seg.get('late'))
    at10 = _num(row.get('at10'))
    final = _num(row.get('finalDiff'))
    at4 = _num(vector.get('at4'))
    if early is None and at4 is not None:
        early = at4
    if mid is None and at10 is not None and at4 is not None:
        mid = at10 - at4
    if late is None and final is not None and at10 is not None:
        late = final - at10
    return {'early': _r(early, 1), 'mid': _r(mid, 1), 'late': _r(late, 1)}


def _build_rows(analysis, games):
    analysis_rows = {str(row.get('matchKey')): row for row in (analysis or {}).get('games') or []}
    rows = []
    for game in games or []:
        key = str(game.get('matchKey') or '')
        base = analysis_rows.get(key) or {}
        vector = game.get('vector') or {}
        # 没打/没采集的占位局不进分析：BO7 四比零就是四局，不能拿七个空槽
        # 冒充「第七把」。局次在后排连续重编号，原始序号留在 sourceGameIndex。
        if not vector and not (base.get('heroesOwn') or base.get('bansOwn') or base.get('result')):
            continue
        row = dict(base)
        row.update({'matchKey': key,
                    'gameIndex': int(game.get('gameIndex') or base.get('gameIndex') or 0),
                    'vector': vector,
                    'detail': game.get('detail')})
        result = row.get('result') or vector.get('result')
        row['result'] = result if result in ('win', 'loss') else None
        row['at10'] = _num(row.get('at10')) if row.get('at10') is not None else _num(vector.get('at10'))
        row['finalDiff'] = _num(row.get('finalDiff')) if row.get('finalDiff') is not None \
            else _num(vector.get('finalDiff'))
        row['duration'] = _num(row.get('duration')) if row.get('duration') is not None \
            else _num(vector.get('duration'))
        row['heroesOwn'] = list(row.get('heroesOwn') or vector.get('heroes') or [])
        row['heroesFoe'] = list(row.get('heroesFoe') or vector.get('heroesFoe') or [])
        row['bansOwn'] = list(row.get('bansOwn') or vector.get('bansOwn') or [])
        row['bansFoe'] = list(row.get('bansFoe') or vector.get('bansFoe') or [])
        row['compOwn'] = row.get('compOwn') or vector.get('compOwn')
        row['compFoe'] = row.get('compFoe') or vector.get('compFoe')
        row['orderKnown'] = bool(row.get('orderKnown') or False)
        row['bpSource'] = row.get('bpSource') or None
        row['phase'] = _phase_values(row)
        row['eventsKnown'] = _event_known(vector)
        row['objectives'] = _objectives(vector, at10=False)
        row['objectivesAt10'] = _objectives(vector, at10=True)
        row['dragon10Diff'] = (row['objectivesAt10'] or {}).get('dragonDiff')
        row['tower10Diff'] = (row['objectivesAt10'] or {}).get('towerDiff')
        row['obj10Net'] = (row['objectivesAt10'] or {}).get('net')
        row['fightRate'] = _fight_rate(vector)
        row['fight'] = vector.get('fight') or {}
        row['seg'] = vector.get('seg') or {}
        row['g'] = vector.get('g') or []
        row['hasReplay'] = bool(vector.get('hasReplay'))
        rows.append(row)
    rows.sort(key=lambda row: row.get('sourceGameIndex') or row.get('gameIndex') or 0)
    for seq, row in enumerate(rows, 1):
        row['sourceGameIndex'] = row.get('gameIndex')
        row['gameIndex'] = seq
    return rows


def _build_history(series, series_briefs, corpus_index):
    target_id = str((series or {}).get('id') or '')
    history = []
    for brief in series_briefs or []:
        if str(brief.get('id') or '') == target_id:
            continue
        games = []
        for game in brief.get('games') or []:
            key = str(game.get('matchKey') or '')
            vector = corpus_index.get(key)
            if vector:
                games.append({'matchKey': key, 'gameIndex': game.get('gameIndex'),
                              'vector': vector, 'detail': None})
        if not games:
            continue
        analysis = series_engine.analyze_series(brief, games)
        rows = analysis.get('games') or []
        for row in rows:
            row['vector'] = corpus_index.get(str(row.get('matchKey') or ''))
            row['fightRate'] = _fight_rate(row.get('vector') or {})
            row['dragon10Diff'] = (_objectives(row.get('vector') or {}, at10=True) or {}).get('dragonDiff')
            row['tower10Diff'] = (_objectives(row.get('vector') or {}, at10=True) or {}).get('towerDiff')
        if rows:
            history.append({'series': brief, 'rows': rows, 'feature': _series_feature(rows)})
    return history


def _series_rates(rows, predicate):
    n = wins = 0
    for row in rows or []:
        if row.get('result') not in ('win', 'loss'):
            continue
        if not predicate(row):
            continue
        n += 1
        wins += 1 if row.get('result') == 'win' else 0
    return {'n': n, 'wins': wins, 'rate': _rate(wins, n) if n >= 2 else None,
            'ci': _wilson(wins, n) if n >= 2 else None, 'enough': n >= 2}


def _corpus_rates(corpus, predicate):
    n = wins = 0
    for vector in corpus or []:
        if vector.get('result') not in ('win', 'loss'):
            continue
        if not predicate(vector):
            continue
        n += 1
        wins += 1 if vector.get('result') == 'win' else 0
    return {'n': n, 'wins': wins, 'rate': _rate(wins, n) if n >= 2 else None,
            'ci': _wilson(wins, n) if n >= 2 else None, 'enough': n >= 2}


def _flow_block(rows, model, corpus):
    games = []
    for row in rows:
        curve = _wp_curve(row.get('vector') or {}, model)
        games.append({
            'gameIndex': row.get('gameIndex'),
            'matchKey': row.get('matchKey'),
            'result': row.get('result'),
            'at10': _r(row.get('at10'), 1),
            'finalDiff': _r(row.get('finalDiff'), 1),
            'duration': _r(row.get('duration'), 1),
            'wp': curve,
        })
    swing = [game for game in games if game['wp'] and _num(game['wp'].get('swing')) is not None]
    swing_game = max(swing, key=lambda game: game['wp']['swing']) if swing else None
    late_swings = [game['wp']['end'] - game['wp']['at10'] for game in games
                   if game['wp'] and _num(game['wp'].get('at10')) is not None]
    ahead = _series_rates(rows, lambda row: _num(row.get('at10')) is not None and row['at10'] > 0)
    behind = _series_rates(rows, lambda row: _num(row.get('at10')) is not None and row['at10'] < 0)
    base_ahead = _corpus_rates(corpus, lambda vector: _num(vector.get('at10')) is not None
                               and vector['at10'] > 0)
    base_behind = _corpus_rates(corpus, lambda vector: _num(vector.get('at10')) is not None
                                and vector['at10'] < 0)
    return {
        'games': games,
        'scorePath': [row.get('result') for row in rows],
        'swingGame': ({'gameIndex': swing_game['gameIndex'], 'swing': swing_game['wp']['swing']}
                      if swing_game else None),
        'lateSwing': _r(_mean(late_swings), 1),
        'comebacks': sum(1 for game in games if game['wp'] and game['wp'].get('comeback')),
        'collapses': sum(1 for game in games if game['wp'] and game['wp'].get('collapse')),
        'leadConversion': {
            'ahead': {**ahead, 'baseline': base_ahead,
                      'delta': _r((ahead['rate'] - base_ahead['rate']), 1)
                      if ahead['rate'] is not None and base_ahead['rate'] is not None else None},
            'behind': {**behind, 'baseline': base_behind,
                       'delta': _r((behind['rate'] - base_behind['rate']), 1)
                       if behind['rate'] is not None and base_behind['rate'] is not None else None},
        },
        'model': ({key: model.get(key) for key in
                   ('n', 'games', 'baseRate', 'auc', 'aucAt10', 'nAt10', 'per1000At10',
                    'per1000At20', 'reliable', 'anchor')} if model else None),
    }


def _phase_block(rows, clusters):
    per_game = []
    for row in rows:
        phase = row.get('phase') or {}
        values = [(name, phase.get(name)) for name in ('early', 'mid', 'late')
                  if _num(phase.get(name)) is not None]
        decider = max(values, key=lambda item: abs(item[1])) if values else None
        cluster = _assign_cluster(row.get('vector') or {}, clusters)
        per_game.append({
            'gameIndex': row.get('gameIndex'),
            'matchKey': row.get('matchKey'),
            'result': row.get('result'),
            'early': phase.get('early'), 'mid': phase.get('mid'), 'late': phase.get('late'),
            'decider': decider[0] if decider else None,
            'deciderValue': decider[1] if decider else None,
            'cluster': cluster,
            'resources': _phase_resources(row.get('vector') or {}),
        })
    win_loss = []
    for key, label in (('early', '0–4 分钟'), ('mid', '4–10 分钟'), ('late', '10 分钟后')):
        wins = [row['phase'].get(key) for row in rows
                if row.get('result') == 'win' and _num(row['phase'].get(key)) is not None]
        losses = [row['phase'].get(key) for row in rows
                  if row.get('result') == 'loss' and _num(row['phase'].get(key)) is not None]
        win_loss.append({'key': key, 'label': label,
                         'winMean': _r(_mean(wins), 1), 'lossMean': _r(_mean(losses), 1),
                         'diff': _r((_mean(wins) or 0) - (_mean(losses) or 0), 1)
                         if wins and losses else None,
                         'winN': len(wins), 'lossN': len(losses)})
    deciders = Counter(item['decider'] for item in per_game
                       if item['decider'] and item.get('result') in ('win', 'loss'))
    return {
        'perGame': per_game,
        'winLoss': win_loss,
        'deciders': [{'phase': key, 'n': count} for key, count in deciders.most_common()],
        'clusters': clusters,
        'path': [item['cluster']['label'] if item.get('cluster') else None for item in per_game],
        'resources': _phase_resource_totals(per_game),
    }


PHASE_LABELS = (('early', '0–4 分钟'), ('mid', '4–10 分钟'), ('late', '10 分钟后'))


def _phase_resources(vector):
    """把回放里带时间戳的龙/塔/团战按 0–4′ / 4–10′ / 10′+ 分桶。

    缺回放的局整块为 None：教练看到的「没有数据」和「拿了 0 个」必须是两件事。
    """
    obj = vector.get('objPhase')
    fight = vector.get('fightPhase')
    if not obj and not fight:
        return None
    buff = vector.get('buffPhase')
    result = {}
    for key, _label in PHASE_LABELS:
        cell = dict((obj or {}).get(key) or {})
        fk = (fight or {}).get(key) or {}
        bk = dict((buff or {}).get(key) or {})
        result[key] = {
            'dragonOwn': _num(cell.get('dragonOwn')), 'dragonFoe': _num(cell.get('dragonFoe')),
            'towerOwn': _num(cell.get('towerOwn')), 'towerFoe': _num(cell.get('towerFoe')),
            'fightN': _num(fk.get('n')), 'fightWon': _num(fk.get('win')),
            'fightDecided': _num(fk.get('decidedN')),
            'fightDecidedWin': _num(fk.get('decidedWin')),
            'antiRed': _num(bk.get('antiRed')), 'antiBlue': _num(bk.get('antiBlue')),
            'stolenRed': _num(bk.get('stolenRed')), 'stolenBlue': _num(bk.get('stolenBlue')),
        }
    return result


def _phase_resource_totals(per_game):
    """按阶段汇总：有回放的局取和，无回放的局不进分母，单独报样本数。"""
    totals = []
    for key, label in PHASE_LABELS:
        with_data = [game for game in per_game
                     if game.get('resources') and game['resources'].get(key)]
        known = [game['resources'][key] for game in with_data]
        if not known:
            totals.append({'key': key, 'label': label, 'games': 0, 'enough': False})
            continue
        wins = [game['resources'][key] for game in with_data if game.get('result') == 'win']
        losses = [game['resources'][key] for game in with_data if game.get('result') == 'loss']

        def _sum(cells, field):
            values = [_num(cell.get(field)) for cell in cells if _num(cell.get(field)) is not None]
            return round(sum(values) / len(values), 2) if values else None
        totals.append({
            'key': key, 'label': label, 'games': len(known), 'enough': len(known) >= 2,
            'dragonGames': sum(1 for cell in known if _num(cell.get('dragonOwn')) is not None),
            'towerGames': sum(1 for cell in known if _num(cell.get('towerOwn')) is not None),
            'fightGames': sum(1 for cell in known if _num(cell.get('fightN')) is not None),
            'dragonOwn': _sum(known, 'dragonOwn'), 'dragonFoe': _sum(known, 'dragonFoe'),
            'towerOwn': _sum(known, 'towerOwn'), 'towerFoe': _sum(known, 'towerFoe'),
            'fightN': _sum(known, 'fightN'), 'fightWon': _sum(known, 'fightWon'),
            'antiRed': _sum(known, 'antiRed'), 'antiBlue': _sum(known, 'antiBlue'),
            'stolenRed': _sum(known, 'stolenRed'), 'stolenBlue': _sum(known, 'stolenBlue'),
            'winDragon': _sum(wins, 'dragonOwn'), 'winTower': _sum(wins, 'towerOwn'),
            'lossDragon': _sum(losses, 'dragonOwn'), 'lossTower': _sum(losses, 'towerOwn'),
            'winFightRate': _r(_mean([_rate(cell.get('fightDecidedWin'), cell.get('fightDecided'))
                                      for cell in wins
                                      if _num(cell.get('fightDecidedWin')) is not None
                                      and _num(cell.get('fightDecided'))]), 1),
            'lossFightRate': _r(_mean([_rate(cell.get('fightDecidedWin'), cell.get('fightDecided'))
                                       for cell in losses
                                       if _num(cell.get('fightDecidedWin')) is not None
                                       and _num(cell.get('fightDecided'))]), 1),
        })
    return totals


def _draft_block(rows, stats, analysis):
    games = []
    all_own, all_foe = [], []
    for row in rows:
        own_heroes = [str(hero) for hero in row.get('heroesOwn') or [] if hero]
        foe_heroes = [str(hero) for hero in row.get('heroesFoe') or [] if hero]
        own_info = [_hero_row(hero, stats) for hero in own_heroes]
        foe_info = [_hero_row(hero, stats) for hero in foe_heroes]
        draft_ok = _draft_valid(own_heroes, foe_heroes)
        has_corpus = bool(stats.get('games')) and draft_ok
        own_value = _mean([info['value'] for info in own_info]) if has_corpus else None
        foe_value = _mean([info['value'] for info in foe_info]) if has_corpus else None
        edge = round(own_value - foe_value, 3) \
            if own_value is not None and foe_value is not None else None
        own_comfort = _mean([1.0 if info['ownApps'] >= EB_MIN_APPS else 0.0 for info in own_info]) \
            if own_info and has_corpus else None
        own_stretch = _mean([1.0 if 0 < info['ownApps'] <= 2 else 0.0 for info in own_info]) \
            if own_info and has_corpus else None
        own_novel = _mean([1.0 if info['ownApps'] == 0 else 0.0 for info in own_info]) \
            if own_info and has_corpus else None
        own_bans = [str(hero) for hero in row.get('bansOwn') or [] if hero]
        foe_bans = [str(hero) for hero in row.get('bansFoe') or [] if hero]
        # 名单口径：每方 4/5 Ban + 5 Pick 时，按记录格式（draft-18/draft-20/rank-20）
        # 入位就是真实手序；数量不足才标「顺序未知」。
        complete_order = (len(own_bans) >= 4 and len(foe_bans) >= 4
                          and len(own_heroes) >= 5 and len(foe_heroes) >= 5)
        order_known = bool(row.get('orderKnown')) or complete_order
        rule_profile = str(row.get('ruleProfile') or '')
        if not rule_profile:
            rule_profile = 'draft-18' if len(own_bans) < 5 else 'rank-20'
        order_source = ('explicit' if row.get('orderKnown')
                        else (rule_profile or 'scrim-order') if complete_order else None)
        ban_own_value = _mean([_hero_row(hero, stats)['value'] for hero in own_bans]) \
            if has_corpus else None
        ban_foe_value = _mean([_hero_row(hero, stats)['value'] for hero in foe_bans]) \
            if has_corpus else None
        games.append({
            'gameIndex': row.get('gameIndex'),
            'matchKey': row.get('matchKey'),
            'result': row.get('result'),
            'heroesOwn': own_heroes, 'heroesFoe': foe_heroes,
            'bansOwn': own_bans, 'bansFoe': foe_bans,
            'valid': draft_ok,
            'invalidReason': None if draft_ok else '双方阵容缺失或相同，BP 价值不参与汇总',
            'ownValue': _r(own_value, 3), 'foeValue': _r(foe_value, 3),
            'edge': edge,
            'edgeLabel': 'BP 占优' if edge is not None and edge >= 0.03
                         else 'BP 下风' if edge is not None and edge <= -0.03
                         else '接近' if edge is not None else '数据不足',
            'ownComfort': _r(own_comfort, 3),
            'ownStretch': _r(own_stretch, 3),
            'ownNovel': _r(own_novel, 3),
            'banOwnValue': _r(ban_own_value, 3),
            'banFoeValue': _r(ban_foe_value, 3),
            'newOwn': list((row.get('adjustment') or {}).get('newOwn') or []),
            'compOwn': row.get('compOwn'), 'compFoe': row.get('compFoe'),
            'camp': row.get('camp') or 'blue',
            'orderKnown': order_known,
            'orderSource': order_source,
            'bpSource': row.get('bpSource'),
        })
        if draft_ok:
            all_own.extend(own_heroes)
            all_foe.extend(foe_heroes)
    unique_own, unique_foe = list(dict.fromkeys(all_own)), list(dict.fromkeys(all_foe))
    edges = [(game['result'], game['edge']) for game in games
             if game.get('valid') and game.get('result') in ('win', 'loss')
             and _num(game.get('edge')) is not None]
    win_edges = [value for result, value in edges if result == 'win']
    loss_edges = [value for result, value in edges if result == 'loss']
    comfort = [(game['result'], game['ownComfort']) for game in games
               if game.get('valid') and game.get('result') in ('win', 'loss')
               and _num(game.get('ownComfort')) is not None]
    win_comfort = [value for result, value in comfort if result == 'win']
    loss_comfort = [value for result, value in comfort if result == 'loss']
    involved = {}
    for game in games:
        if not game.get('valid'):
            continue
        for hero in game['heroesOwn']:
            involved.setdefault(hero, set()).add('own')
        for hero in game['heroesFoe']:
            involved.setdefault(hero, set()).add('foe')
        for hero in game['bansOwn']:
            involved.setdefault(hero, set()).add('ownBan')
        for hero in game['bansFoe']:
            involved.setdefault(hero, set()).add('foeBan')
    top_heroes = []
    for hero, sides in involved.items():
        info = _hero_row(hero, stats)
        top_heroes.append({
            **info,
            'sides': sorted(sides),
            'tags': _hero_tags(info, stats),
        })
    top_heroes.sort(key=lambda item: (-(item.get('presence') or 0), -(item.get('apps') or 0),
                                      str(item.get('name'))))
    response = []
    for item in (analysis or {}).get('opponentResponse') or []:
        row = dict(item)
        row['newFoeValues'] = [
            {'hero': hero, 'value': _hero_row(hero, stats)['value']}
            for hero in item.get('newFoe') or []
        ]
        row['banRepeatValues'] = [
            {'hero': hero, 'value': _hero_row(hero, stats)['value']}
            for hero in item.get('banRepeat') or []
        ]
        response.append(row)
    return {
        'games': games,
        'series': {
            'uniqueOwn': len(unique_own), 'uniqueFoe': len(unique_foe),
            'uniqueOwnHeroes': unique_own, 'uniqueFoeHeroes': unique_foe,
            'reuseOwn': len(all_own) - len(unique_own),
            'reuseFoe': len(all_foe) - len(unique_foe),
            'comfortShare': _r(_mean([game['ownComfort'] for game in games
                                      if _num(game.get('ownComfort')) is not None]), 3),
            'stretchShare': _r(_mean([game['ownStretch'] for game in games
                                      if _num(game.get('ownStretch')) is not None]), 3),
            'novelShare': _r(_mean([game['ownNovel'] for game in games
                                    if _num(game.get('ownNovel')) is not None]), 3),
            'edgeMean': _r(_mean([game['edge'] for game in games
                                  if _num(game.get('edge')) is not None]), 3),
            'edgeWins': len(win_edges), 'edgeLosses': len(loss_edges),
            'winEdge': _r(_mean(win_edges), 3), 'lossEdge': _r(_mean(loss_edges), 3),
            'edgeDiff': _r((_mean(win_edges) or 0) - (_mean(loss_edges) or 0), 3)
            if win_edges and loss_edges else None,
            'winComfort': _r(_mean(win_comfort), 3), 'lossComfort': _r(_mean(loss_comfort), 3),
            'comfortDiff': _r((_mean(win_comfort) or 0) - (_mean(loss_comfort) or 0), 3)
            if win_comfort and loss_comfort else None,
            'invalidGames': sum(1 for game in games if not game.get('valid')),
        },
        'heroes': top_heroes[:30],
        'response': response,
        'coverage': {
            'games': len(games),
            'orderKnownGames': sum(1 for game in games if game.get('orderKnown')),
            'bpSourceGames': sum(1 for game in games if game.get('bpSource')),
            'corpusGames': stats.get('games') or 0,
            'invalidGames': sum(1 for game in games if not game.get('valid')),
            'corpusInvalidGames': stats.get('invalidGames') or 0,
        },
        'orderKnown': any(game.get('orderKnown') for game in games),
    }


def _player_block(rows, corpus, exclude_keys, series_date=None):
    """十个人（双方）× 分路专属指标 × 时间窗基线。

    - 分路不同，指标不同：游走不看经济/输出，改看承伤、控制、治疗、参团；
      打野/对抗路额外看承伤与对位经济，发育路额外看推塔。
    - 时间窗：昨天 / 7 天 / 30 天 / 3 个月 / 6 个月 / 1 年 / 2 年，
      每个窗单独建基线；窗内样本不足就明确写「样本不足」，不拿 1 局当基线。
    - 基线优先个人（同分路 ≥4 局），其次同位置（≥8 局），都不够则无基线。
    """
    entries = {}
    for row in rows:
        vector = row.get('vector') or {}
        own_camp = vector.get('camp')
        for player in vector.get('pl') or []:
            if not player.get('camp'):
                continue
            side = 'own' if player.get('camp') == own_camp else 'foe'
            position = str(player.get('pos') or '未知')
            name = str(player.get('name') or '').strip() or position
            key = (side, name, position)
            entry = entries.setdefault(key, {
                'name': name, 'position': position, 'side': side, 'games': 0,
                'perGame': [], 'heroes': [], 'metrics': defaultdict(list),
            })
            metrics = _pl_metrics(player, vector, position, side)
            entry['games'] += 1
            for metric, value in metrics.items():
                if value is not None:
                    entry['metrics'][metric].append(value)
            hero = str(player.get('hero') or '')
            arch = str(player.get('arch') or '')
            entry['heroes'].append({'hero': hero, 'arch': arch,
                                    'gameIndex': row.get('gameIndex'),
                                    'result': row.get('result')})
            entry['perGame'].append({
                'gameIndex': row.get('gameIndex'), 'matchKey': row.get('matchKey'),
                'result': row.get('result'), 'hero': hero, 'arch': arch, **metrics,
            })

    windows = {}
    if corpus:
        for key, _label, days in PLAYER_WINDOWS:
            since = None
            if series_date and days:
                try:
                    since = (datetime.date.fromisoformat(series_date)
                             - datetime.timedelta(days=days)).isoformat()
                except ValueError:
                    since = None
            windows[key] = _player_baselines(corpus, exclude_keys, since=since,
                                             until=series_date or None)

    players = []
    for key, entry in entries.items():
        position = entry['position']
        lane_keys = LANE_METRICS.get(position, ('kda', 'gpm', 'dpm', 'part'))
        summary = {metric: _r(_mean(entry['metrics'].get(metric)), 2)
                   for metric in METRIC_META}
        window_stats = {}
        composites = {}
        for window_key, _label, _days in PLAYER_WINDOWS:
            base_set = windows.get(window_key)
            if not base_set:
                window_stats[window_key] = {'available': False, 'kind': None,
                                            'games': 0, 'metrics': {}, 'composite': None}
                continue
            player_base = base_set['players'].get((entry['name'], position))
            position_base = base_set['positions'].get(position)
            use_player = bool(player_base) and all(
                len(player_base.get(metric) or []) >= PLAYER_BASELINE_MIN for metric in lane_keys)
            use_position = bool(position_base) and all(
                len(position_base.get(metric) or []) >= POSITION_BASELINE_MIN for metric in lane_keys)
            base = player_base if use_player else position_base if use_position else None
            kind = 'player' if use_player else 'position' if use_position else None
            metric_cells = {}
            z_values = []
            for metric in lane_keys:
                value = summary.get(metric)
                stats = _baseline_stats((base or {}).get(metric))
                if value is None or not stats:
                    metric_cells[metric] = {'value': value, 'base': None, 'z': None, 'delta': None}
                    continue
                z = _z_score(value, stats, Z_METRIC_FLOOR.get(metric)
                             or Z_FLOOR_EXTRA.get(metric) or 1.0)
                metric_cells[metric] = {
                    'value': _r(value, 2), 'base': _r(stats['mean'], 2),
                    'std': _r(stats['std'], 2), 'n': stats['n'],
                    'z': _r(z, 2), 'delta': _r(value - (stats['mean'] or 0), 2),
                }
                if z is not None:
                    z_values.append(z)
            composite = _r(_mean(z_values), 2) if z_values else None
            composites[window_key] = composite
            sample = 0
            if base:
                first = lane_keys[0]
                sample = len(base.get(first) or [])
            window_stats[window_key] = {
                'available': bool(base), 'kind': kind,
                'games': sample,
                'metrics': metric_cells,
                'composite': composite,
                'tier': _tier(composite),
            }
            if window_key == 'd30':
                # 逐局状态分用同一套基线（近 30 天）算，卡片上的折线才和数字对得上。
                for game in entry['perGame']:
                    if game.get('composite') is not None:
                        continue
                    game_z = []
                    for metric in lane_keys:
                        stats = _baseline_stats((base or {}).get(metric))
                        game_z.append(_z_score(game.get(metric), stats,
                                               Z_METRIC_FLOOR.get(metric)
                                               or Z_FLOOR_EXTRA.get(metric) or 1.0))
                    values = [value for value in game_z if value is not None]
                    game['composite'] = _r(_mean(values), 2) if values else None
                    game['zScore'] = game['composite']

        # 兼容旧字段：主卡仍然读 composite / baseline / form，取「近 30 天」那套。
        default_window = 'd30' if windows else None
        default = window_stats.get(default_window) or {}
        summary_composite = default.get('composite')
        per_game = entry['perGame']
        game_composites = [game.get('composite') for game in per_game
                           if _num(game.get('composite')) is not None]
        trend = _slope([(game.get('gameIndex'), game.get('zScore'))
                        for game in per_game if _num(game.get('zScore')) is not None])
        arch_count = Counter(item['arch'] for item in entry['heroes'] if item['arch'])
        win_composites = [game.get('composite') for game in per_game
                          if game.get('result') == 'win' and _num(game.get('composite')) is not None]
        loss_composites = [game.get('composite') for game in per_game
                           if game.get('result') == 'loss' and _num(game.get('composite')) is not None]
        players.append({
            'name': entry['name'], 'position': position, 'side': entry['side'],
            'games': entry['games'],
            **{metric: summary.get(metric) for metric in
               ('kda', 'gpm', 'dpm', 'part', 'deaths', 'laneGold', 'tpm', 'ctrlpm', 'heal', 'twr')},
            'composite': summary_composite,
            'z': {metric: (default.get('metrics', {}).get(metric) or {}).get('z')
                  for metric in lane_keys},
            'baseline': default.get('kind'),
            'baselineGames': default.get('games') or 0,
            'tier': default.get('tier') or 'unknown',
            'windows': window_stats,
            'laneMetrics': list(lane_keys),
            'trend': _r(trend, 2),
            'consistency': _r(_std(game_composites), 2),
            'winComposite': _r(_mean(win_composites), 2) if win_composites else None,
            'lossComposite': _r(_mean(loss_composites), 2) if loss_composites else None,
            'form': 'hot' if summary_composite is not None and summary_composite >= 0.5
                    else 'cold' if summary_composite is not None and summary_composite <= -0.5
                    else 'stable' if summary_composite is not None else 'unknown',
            'heroes': entry['heroes'],
            'archCounts': [{'arch': arch, 'games': count}
                           for arch, count in arch_count.most_common()],
            'perGame': per_game,
        })

    def _lane_rank(player):
        lane = LANE_ORDER.index(player['position']) if player['position'] in LANE_ORDER else 9
        return (player['side'] != 'own', lane,
                -(player.get('composite') if _num(player.get('composite')) is not None else -99),
                player['name'])
    players.sort(key=_lane_rank)
    own = [player for player in players if player['side'] == 'own']
    foe = [player for player in players if player['side'] == 'foe']
    coverage = {window_key: sum(1 for player in own
                                if (player['windows'].get(window_key) or {}).get('available'))
                for window_key, _label, _days in PLAYER_WINDOWS} if windows else {}
    return {
        'players': players,
        'lanes': list(LANE_ORDER),
        'metricsByLane': {lane: [{'key': metric, **dict(zip(('label', 'digits', 'unit'),
                                                            METRIC_META[metric]))}
                                 for metric in keys]
                          for lane, keys in LANE_METRICS.items()},
        'windows': [{'key': key, 'label': label, 'days': days}
                    for key, label, days in PLAYER_WINDOWS],
        'lineup': {
            'unique': len({(player['side'], player['name']) for player in players}),
            'ownCount': len(own), 'foeCount': len(foe),
            'stable': len({player['name'] for player in own}) <= 5
                      and all(player['games'] == len(rows) for player in own),
            'substitutions': [{'name': player['name'], 'games': player['games']}
                              for player in own if player['games'] < len(rows)],
            'baselineCoverage': len([player for player in own
                                     if (player['windows'].get('d30') or {}).get('available')]),
            'coverage': coverage,
            'teamComposite': {
                'own': _r(_mean([player.get('composite') for player in own
                                 if _num(player.get('composite')) is not None]), 2),
                'foe': _r(_mean([player.get('composite') for player in foe
                                 if _num(player.get('composite')) is not None]), 2),
            },
        },
    }


def _tier(composite):
    if composite is None:
        return 'unknown'
    return 'up' if composite >= 0.35 else 'down' if composite <= -0.35 else 'flat'


def _fight_block(rows, corpus):
    per_game = []
    for row in rows:
        vector = row.get('vector') or {}
        obj10 = row.get('objectivesAt10') or {}
        obj = row.get('objectives') or {}
        fight = vector.get('fight') or {}
        first = vector.get('first') or {}
        fk = vector.get('fk') or {}
        adv = fk.get('adv') or {}
        even = fk.get('even') or {}
        dis = fk.get('dis') or {}
        per_game.append({
            'gameIndex': row.get('gameIndex'), 'matchKey': row.get('matchKey'),
            'result': row.get('result'),
            'eventsKnown': bool(row.get('eventsKnown')),
            'fightN': _num(fight.get('n')), 'decidedN': _num(fight.get('decidedN')),
            'fightWins': _num(fight.get('decidedWin')), 'fightRate': _r(row.get('fightRate'), 1),
            'advN': _num(adv.get('n')), 'advWins': _num(adv.get('win')),
            'advRate': _rate(_num(adv.get('win')) or 0, _num(adv.get('n')) or 0),
            'evenN': _num(even.get('n')), 'evenWins': _num(even.get('win')),
            'evenRate': _rate(_num(even.get('win')) or 0, _num(even.get('n')) or 0),
            'disN': _num(dis.get('n')), 'disWins': _num(dis.get('win')),
            'disRate': _rate(_num(dis.get('win')) or 0, _num(dis.get('n')) or 0),
            'firstFight': _num((fk.get('first') or {}).get('n')),
            'firstFightWins': _num((fk.get('first') or {}).get('win')),
            'dragon10Own': obj10.get('dragonOwn'), 'dragon10Foe': obj10.get('dragonFoe'),
            'tower10Own': obj10.get('towerOwn'), 'tower10Foe': obj10.get('towerFoe'),
            'dragon10Diff': obj10.get('dragonDiff'), 'tower10Diff': obj10.get('towerDiff'),
            'obj10Net': obj10.get('net'),
            'dragonOwn': obj.get('dragonOwn'), 'dragonFoe': obj.get('dragonFoe'),
            'towerOwn': obj.get('towerOwn'), 'towerFoe': obj.get('towerFoe'),
            'objNet': obj.get('net'),
            'deathsOwn': (vector.get('death') or {}).get('own'),
            'deathsFoe': (vector.get('death') or {}).get('foe'),
            'firstBlood': first.get('bloodSide'), 'firstDragon': first.get('dragonSide'),
            'firstTower': first.get('towerSide'),
            'jungleCrossShare': (vector.get('jungle') or {}).get('crossShare'),
            'cutN': (vector.get('cut') or {}).get('n'),
            'buffAnti': (vector.get('buff') or {}).get('anti'),
            'buffStolen': (vector.get('buff') or {}).get('stolen'),
        })
    win_loss = []
    game_by_index = {item['gameIndex']: item for item in per_game}
    for key, label, digits in (
        ('at10', '10 分钟经济差', 0), ('fightRate', '团战胜率', 1),
        ('dragon10Diff', '10 分钟龙差', 1), ('tower10Diff', '10 分钟塔差', 1),
        ('obj10Net', '10 分钟资源净差', 1), ('deathsOwn', '我方死亡', 1),
        ('deathsFoe', '对方死亡', 1), ('duration', '时长', 0),
    ):
        wins, losses = [], []
        for row in rows:
            if row.get('result') not in ('win', 'loss'):
                continue
            value = _num(row.get(key))
            if value is None:
                value = _num((game_by_index.get(row.get('gameIndex')) or {}).get(key))
            if value is None:
                continue
            (wins if row['result'] == 'win' else losses).append(value)
        win_loss.append({'key': key, 'label': label,
                         'winMean': _r(_mean(wins), digits), 'lossMean': _r(_mean(losses), digits),
                         'diff': _r((_mean(wins) or 0) - (_mean(losses) or 0), digits)
                         if wins and losses else None,
                         'winN': len(wins), 'lossN': len(losses)})
    baseline = {
        'ahead10': _corpus_rates(corpus, lambda vector: _num(vector.get('at10')) is not None
                                 and vector['at10'] > 0),
        'behind10': _corpus_rates(corpus, lambda vector: _num(vector.get('at10')) is not None
                                  and vector['at10'] < 0),
        'ahead10Obj': _corpus_rates(corpus, lambda vector: _num(vector.get('at10')) is not None
                                    and vector['at10'] > 0
                                    and (_objectives(vector, at10=True).get('net') or 0) > 0),
        'behind10Obj': _corpus_rates(corpus, lambda vector: _num(vector.get('at10')) is not None
                                     and vector['at10'] < 0
                                     and (_objectives(vector, at10=True).get('net') or 0) > 0),
        'fightHigh': _corpus_rates(corpus, lambda vector: _fight_rate(vector) is not None
                                   and _fight_rate(vector) >= 60),
        'fightLow': _corpus_rates(corpus, lambda vector: _fight_rate(vector) is not None
                                  and _fight_rate(vector) <= 40),
    }
    series = {
        'ahead10': _series_rates(rows, lambda row: _num(row.get('at10')) is not None and row['at10'] > 0),
        'behind10': _series_rates(rows, lambda row: _num(row.get('at10')) is not None and row['at10'] < 0),
        'ahead10Obj': _series_rates(rows, lambda row: _num(row.get('at10')) is not None
                                    and row['at10'] > 0
                                    and ((row.get('objectivesAt10') or {}).get('net') or 0) > 0),
        'behind10Obj': _series_rates(rows, lambda row: _num(row.get('at10')) is not None
                                     and row['at10'] < 0
                                     and ((row.get('objectivesAt10') or {}).get('net') or 0) > 0),
        'fightHigh': _series_rates(rows, lambda row: _num(row.get('fightRate')) is not None
                                   and row['fightRate'] >= 60),
        'fightLow': _series_rates(rows, lambda row: _num(row.get('fightRate')) is not None
                                  and row['fightRate'] <= 40),
    }
    return {
        'perGame': per_game,
        'winLoss': win_loss,
        'baseline': baseline,
        'series': series,
        'coverage': {
            'games': len(rows),
            'events': sum(1 for row in rows if row.get('eventsKnown')),
            'timeline': sum(1 for row in rows if row.get('at10') is not None),
            'fights': sum(1 for game in per_game if (game.get('decidedN') or 0) > 0),
        },
    }


def _similarity_block(rows, corpus, history, matrix=None):
    if matrix is None:
        matrix = _feature_matrix(corpus, {str(row.get('matchKey')) for row in rows})
    games = []
    for row in rows:
        feature = _game_feature(row.get('vector') or {})
        neighbors = _knn_neighbors(feature, matrix)
        games.append({
            'gameIndex': row.get('gameIndex'), 'matchKey': row.get('matchKey'),
            'result': row.get('result'),
            'expectedWinRate': neighbors.get('expectedWinRate') if neighbors else None,
            'ci': neighbors.get('ci') if neighbors else None,
            'n': neighbors.get('n') if neighbors else 0,
            'neighbors': neighbors.get('neighbors') if neighbors else [],
        })
    target = {'series': {'id': None, 'opponent': None, 'startAt': None, 'bestOf': None,
                         'completion': None},
              'feature': _series_feature(rows), 'rows': rows}
    return {
        'games': games,
        'series': _series_similarity(target, history),
        'coverage': {'corpusGames': len(matrix['rows']) if matrix else 0,
                     'historySeries': len(history)},
    }


# ---------------------------------------------------------------- 结论
def _links(*groups):
    links = []
    seen = set()
    for group in groups:
        for row in group or []:
            key = (row.get('matchKey'), row.get('gameIndex'))
            if key[0] and key not in seen:
                seen.add(key)
                links.append({'matchKey': key[0], 'gameIndex': key[1]})
    return links


# ---------------------------------------------------------------- BP：禁 / 选 / 组合
BP_SIMILAR_WINDOWS = (('d3', '近 3 天', 3), ('d7', '近 7 天', 7), ('d30', '近 30 天', 30),
                      ('d90', '近 3 个月', 90), ('all', '全部', None))


def _norm_team(name):
    return str(name or '').strip().lower()


def _pair_counts(heroes, won, pairs, pair_wins):
    picks = [str(hero) for hero in heroes or [] if hero]
    for index, first in enumerate(picks):
        for second in picks[index + 1:]:
            key = tuple(sorted((first, second)))
            pairs[key] += 1
            if won:
                pair_wins[key] += 1


def _team_pick_history(corpus, opponent):
    """对手在这份语料里的选人/禁用习惯；只按对手名精确匹配，不猜别名。"""
    target = _norm_team(opponent)
    if not target:
        return None
    games = [vector for vector in corpus or []
             if _norm_team(vector.get('opponent')) == target]
    if not games:
        return None
    picks, wins, bans = Counter(), Counter(), Counter()
    pairs, pair_wins = Counter(), Counter()
    for vector in games:
        won = vector.get('result') == 'loss'   # 对手赢 = 我方输
        for hero in vector.get('heroesFoe') or []:
            picks[hero] += 1
            if won:
                wins[hero] += 1
        _pair_counts(vector.get('heroesFoe'), won, pairs, pair_wins)
        for hero in vector.get('bansFoe') or []:
            bans[hero] += 1
    return {'games': len(games), 'picks': picks, 'wins': wins, 'bans': bans,
            'pairs': pairs, 'pairWins': pair_wins}


def _own_pick_history(corpus):
    picks, wins, bans = Counter(), Counter(), Counter()
    pairs, pair_wins = Counter(), Counter()
    for vector in corpus or []:
        won = vector.get('result') == 'win'
        for hero in vector.get('heroes') or []:
            picks[hero] += 1
            if won:
                wins[hero] += 1
        _pair_counts(vector.get('heroes'), won, pairs, pair_wins)
        for hero in vector.get('bansOwn') or []:
            bans[hero] += 1
    return {'games': len(corpus or []), 'picks': picks, 'wins': wins, 'bans': bans,
            'pairs': pairs, 'pairWins': pair_wins}


def _signature(vector, side):
    """阵容的功能分工签名：每个分路一个打法类型（战边/坦野/法核/游射/开团辅…）。"""
    camp = (vector or {}).get('camp')
    cells = []
    for player in (vector or {}).get('pl') or []:
        position = str(player.get('pos') or '')
        archetype = str(player.get('arch') or '')
        if position not in LANE_ORDER or not archetype or archetype == '待分类':
            continue
        player_side = 'own' if player.get('camp') == camp else 'foe'
        if player_side != side:
            continue
        cells.append({'position': position, 'archetype': archetype,
                      'hero': str(player.get('hero') or '')})
    cells.sort(key=lambda cell: LANE_ORDER.index(cell['position']))
    return cells


def _signature_overlap(target, other):
    target_set = {(cell['position'], cell['archetype']) for cell in target}
    other_set = {(cell['position'], cell['archetype']) for cell in other}
    if not target_set or not other_set:
        return 0
    return len(target_set & other_set)


def _similar_flag(side_win, lead, final_diff):
    """相似阵容里的「异常」：赢得很小、输得很小、领先被翻、逆风翻盘。

    教练看历史对照不是看胜率，而是找「这套分工明明能打，为什么这场输了」。
    """
    if lead is not None and lead >= 2000 and not side_win:
        return '领先被翻'
    if lead is not None and lead <= -2000 and side_win:
        return '逆风翻盘'
    if side_win and final_diff is not None:
        if final_diff >= 7000:
            return '大胜'
        if 0 <= final_diff < 1500:
            return '小胜'
    if not side_win and final_diff is not None and -1500 < final_diff <= 0:
        return '小负'
    return None


def _comp_matches(corpus, target_signature, side, exclude_keys, *, since=None,
                  until=None, min_overlap=3, limit=None):
    """按「同分路 + 同打法类型」找相似阵容；对手视角的胜负要翻过来看。"""
    rows = []
    target_heroes = {cell['hero'] for cell in target_signature if cell['hero']}
    for vector in corpus or []:
        key = str(vector.get('key') or '')
        if key in exclude_keys:
            continue
        date = str(vector.get('date') or '')[:10]
        if since and date and date < since:
            continue
        if until and date and date > until:
            continue
        signature = _signature(vector, side)
        overlap = _signature_overlap(target_signature, signature)
        if overlap < min_overlap:
            continue
        heroes = [cell['hero'] for cell in signature if cell['hero']]
        same_heroes = len(target_heroes & set(heroes))
        our_win = vector.get('result') == 'win'
        side_win = our_win if side == 'own' else vector.get('result') == 'loss'
        sign = 1 if side == 'own' else -1
        at10 = _num(vector.get('at10'))
        final_diff = _num(vector.get('finalDiff'))
        side_lead = at10 * sign if at10 is not None else None
        side_final = final_diff * sign if final_diff is not None else None
        obj10 = vector.get('objAt10') or {}
        dragon = (_num(obj10.get('dragonOwn')) - _num(obj10.get('dragonFoe'))) \
            if _num(obj10.get('dragonOwn')) is not None and _num(obj10.get('dragonFoe')) is not None else None
        tower = (_num(obj10.get('towerOwn')) - _num(obj10.get('towerFoe'))) \
            if _num(obj10.get('towerOwn')) is not None and _num(obj10.get('towerFoe')) is not None else None
        fight = _fight_rate(vector)
        rows.append({
            'matchKey': key, 'date': date, 'opponent': vector.get('opponent') or '',
            'gameIndex': vector.get('gameIndex'), 'result': vector.get('result'),
            'sideWin': side_win,
            'similarity': round(overlap / 5.0, 2), 'overlap': overlap,
            'sameHeroes': same_heroes, 'heroes': heroes,
            'slots': [cell['archetype'] for cell in signature],
            'at10': _r(side_lead, 1),
            'finalDiff': _r(side_final, 1),
            'dragon10': _r(dragon * sign, 1) if dragon is not None else None,
            'tower10': _r(tower * sign, 1) if tower is not None else None,
            'fightRate': _r(100 - fight, 1) if (fight is not None and side == 'foe') else _r(fight, 1),
            'duration': _r(vector.get('duration'), 0),
            'flag': _similar_flag(side_win, side_lead, side_final),
        })
    rows.sort(key=lambda row: (-row['overlap'], -row['sameHeroes'], row['date'] or ''))
    total = len(rows)
    strong = [row for row in rows if row['overlap'] >= 4]
    wins = sum(1 for row in rows if row['sideWin'])
    strong_wins = sum(1 for row in strong if row['sideWin'])
    # 结果方块条要用全部相似局，不能只取展示用的前 6 条。
    history = sorted(rows, key=lambda row: (str(row.get('date') or ''), str(row.get('matchKey') or '')))
    recent = [{'date': row.get('date'), 'win': bool(row.get('sideWin')),
               'overlap': row.get('overlap')} for row in history[-30:]]
    # 散点图用：相似度 × 终局经济差 × 胜负。只带极简字段，避免把整份明细塞进响应。
    points = [{'o': row.get('overlap'), 'd': row.get('finalDiff'),
               'w': 1 if row.get('sideWin') else 0,
               't': str(row.get('date') or '')[5:]} for row in history[-80:]]
    flag_counts = Counter(row.get('flag') for row in history if row.get('flag'))
    if limit is not None:
        rows = rows[:limit]
    return {
        'n': total, 'wins': wins, 'rate': _rate(wins, total),
        'enough': total >= 5,
        'strongN': len(strong), 'strongWins': strong_wins,
        'strongRate': _rate(strong_wins, len(strong)),
        'reuseN': sum(1 for row in rows if row['sameHeroes'] >= 3),
        'recent': recent,
        'points': points,
        'flags': [{'flag': flag, 'n': count} for flag, count in flag_counts.most_common()],
        'matches': rows,
    }


_KPL_CACHE = {}


def _kpl_index():
    if 'index' not in _KPL_CACHE:
        try:
            import bp_facts
            _KPL_CACHE['index'] = bp_facts.kpl_index()
        except Exception:  # noqa: BLE001 - KPL 事实表缺失时降级，不影响大场分析
            _KPL_CACHE['index'] = None
    return _KPL_CACHE['index']


def _kpl_comp(heroes):
    """这套五人组合在 KPL 的「双人组合契合度」：按样本加权，附带最强的一对。"""
    index = _kpl_index()
    heroes = [str(hero) for hero in (heroes or []) if hero]
    if not index or len(heroes) < 2:
        return None
    pairs = index.get('pairs') or {}
    total_n = 0.0
    weighted = 0.0
    hits = []
    for a, b in combinations(heroes, 2):
        row = pairs.get(tuple(sorted((a, b))))
        if not row or not _num(row.get('n')) or not _num(row.get('wr')):
            continue
        n = _num(row.get('n'))
        wr = _num(row.get('wr'))
        total_n += n
        weighted += n * wr
        hits.append({'heroes': [a, b], 'n': int(n), 'wr': _r(wr, 1)})
    lineup = (index.get('lineups') or {}).get(tuple(sorted(heroes)))
    trios = []
    for combo in combinations(heroes, 3):
        row = (index.get('trios') or {}).get(tuple(sorted(combo)))
        if row and _num(row.get('n')):
            trios.append({'heroes': list(combo), 'n': int(row['n']),
                          'wr': _r(row.get('wr'), 1), 'teams': row.get('teams') or []})
    if not total_n:
        return {'available': False, 'lineup': lineup, 'pairs': [], 'trios': trios}
    hits.sort(key=lambda item: (-item['n'], -item['wr']))
    trios.sort(key=lambda item: (-item['n'], -item['wr']))
    return {
        'available': True,
        'games': index.get('games'),
        'pairHits': len(hits),
        'pairN': int(total_n),
        'pairWr': _r(weighted / total_n, 1),
        'bestPair': hits[0] if hits else None,
        'pairs': hits,
        'trios': trios,
        'lineup': ({'n': lineup.get('n'), 'wins': lineup.get('wins'), 'wr': lineup.get('wr'),
                    'teams': lineup.get('teams') or [], 'year': lineup.get('year')}
                   if lineup else None),
    }


def _tag_matchup(corpus, own_tags, foe_tags, exclude_keys):
    """功能对位的历史结果：我方体系标签 × 对方体系标签，在语料里赢了多少。"""
    own_tags = {tag for tag in (own_tags or []) if tag}
    foe_tags = {tag for tag in (foe_tags or []) if tag}
    if not own_tags or not foe_tags:
        return None
    n = wins = 0
    for vector in corpus or []:
        if str(vector.get('key') or '') in exclude_keys:
            continue
        own = set(vector.get('compOwn') or [])
        foe = set(vector.get('compFoe') or [])
        if not own or not foe:
            continue
        if len(own & own_tags) + len(foe & foe_tags) < 2:
            continue
        if vector.get('result') not in ('win', 'loss'):
            continue
        n += 1
        wins += 1 if vector.get('result') == 'win' else 0
    if n < 5:
        return {'n': n, 'wins': wins, 'rate': _rate(wins, n), 'enough': False}
    return {'n': n, 'wins': wins, 'rate': _rate(wins, n), 'enough': True}


def _bp_plan_block(rows, stats, corpus, opponent):
    """BP 判断：讲人话的「拿到自己的东西 / 拆掉对方的东西 / 组合对位」。

    每个结论都有具体英雄和样本：
    - 选人：我们是否拿到自己的常用英雄与高胜率组合（含 KPL 双人组合契合度）；
    - 禁用：我们 ban 掉的英雄，是不是对手常用的高胜率英雄；
    - 组合：双方功能体系的历史对位结果，以及这套五人组合在 KPL 的样本。
    """
    own_history = _own_pick_history(corpus)
    foe_history = _team_pick_history(corpus, opponent)
    exclude_keys = set()

    def _cell(hero):
        return _hero_row(hero, stats)

    def _pick_share(history, hero):
        if not history or not history.get('games'):
            return 0.0
        return (history['picks'].get(hero) or 0) / history['games']

    def _pick_rate(history, hero):
        picks = (history or {}).get('picks', {}).get(hero) or 0
        return _rate((history or {}).get('wins', {}).get(hero) or 0, picks)

    def _wanted(history, limit=3):
        if not history:
            return []
        return [{'hero': hero, 'picks': count, 'rate': _pick_rate(history, hero),
                 'share': _r(_pick_share(history, hero) * 100, 0)}
                for hero, count in history['picks'].most_common(limit)]

    def _status(hero, own_side):
        """自己想要的英雄最后去哪了：拿到 / 被抢 / 被 ban / 没选中。"""
        if own_side:
            if hero in own_heroes:
                return 'got'
            if hero in bans_foe:
                return 'banned'
            if hero in foe_heroes:
                return 'stolen'
            return 'open'
        if hero in bans_own:
            return 'banned'
        if hero in own_heroes:
            return 'stolen'
        if hero in foe_heroes:
            return 'got'
        return 'open'

    games = []
    for row in rows:
        own_heroes = [str(hero) for hero in row.get('heroesOwn') or [] if hero]
        foe_heroes = [str(hero) for hero in row.get('heroesFoe') or [] if hero]
        bans_own = [str(hero) for hero in row.get('bansOwn') or [] if hero]
        bans_foe = [str(hero) for hero in row.get('bansFoe') or [] if hero]
        own_cells = [_cell(hero) for hero in own_heroes]
        foe_cells = [_cell(hero) for hero in foe_heroes]
        pick_own = _mean([cell.get('value') for cell in own_cells])
        pick_foe = _mean([cell.get('value') for cell in foe_cells])
        pick_edge = pick_own - pick_foe if pick_own is not None and pick_foe is not None else None

        deny_items, concede_items = [], []
        for hero in bans_own:
            info = _cell(hero)
            share = _pick_share(foe_history, hero)
            value = _num(info.get('value')) or 0.0
            deny_items.append({
                'hero': hero, 'value': _r(value, 3),
                'foePicks': (foe_history or {}).get('picks', {}).get(hero, 0),
                'foeShare': _r(share * 100, 0),
                'foeRate': _pick_rate(foe_history, hero),
                'score': round((max(0.0, value) + 0.02) * (0.5 + min(1.0, share * 4)), 4),
            })
        for hero in bans_foe:
            info = _cell(hero)
            share = _pick_share(own_history, hero)
            value = _num(info.get('value')) or 0.0
            concede_items.append({
                'hero': hero, 'value': _r(value, 3),
                'ownPicks': own_history['picks'].get(hero, 0),
                'ownShare': _r(share * 100, 0),
                'ownRate': _pick_rate(own_history, hero),
                'score': round((max(0.0, value) + 0.02) * (0.5 + min(1.0, share * 4)), 4),
            })
        deny_items.sort(key=lambda item: -item['score'])
        concede_items.sort(key=lambda item: -item['score'])
        deny_score = _mean([item['score'] for item in deny_items])
        concede_score = _mean([item['score'] for item in concede_items])
        ban_edge = (deny_score - concede_score) * 0.5 \
            if deny_score is not None and concede_score is not None else None

        own_signature = _signature(row.get('vector') or {}, 'own')
        foe_signature = _signature(row.get('vector') or {}, 'foe')
        own_comp = _comp_matches(corpus, own_signature, 'own', exclude_keys,
                                 min_overlap=4, limit=0)
        foe_comp = _comp_matches(corpus, foe_signature, 'foe', exclude_keys,
                                 min_overlap=4, limit=0)
        combo_own = own_comp['rate'] if own_comp['enough'] else None
        combo_foe = foe_comp['rate'] if foe_comp['enough'] else None
        combo_edge = None
        if combo_own is not None and combo_foe is not None:
            combo_edge = max(-0.12, min(0.12, (combo_own - combo_foe) / 100.0 * 0.6))

        parts = [(pick_edge, 0.45), (ban_edge, 0.30), (combo_edge, 0.25)]
        usable = [(value, weight) for value, weight in parts if _num(value) is not None]
        edge = sum(value * weight for value, weight in usable) / sum(weight for _, weight in usable) \
            if usable else None
        label = 'BP 占优' if edge is not None and edge >= 0.03 \
            else 'BP 下风' if edge is not None and edge <= -0.03 else 'BP 接近' \
            if edge is not None else 'BP 数据不足'

        foe_wanted = _wanted(foe_history)
        own_wanted = _wanted(own_history)
        for item in foe_wanted:
            item['status'] = _status(item['hero'], own_side=False)
        for item in own_wanted:
            item['status'] = _status(item['hero'], own_side=True)

        def _trim(items):
            involved = [item for item in items if item['status'] != 'open']
            return involved[:3] if involved else items[:2]
        foe_wanted = _trim(foe_wanted)
        own_wanted = _trim(own_wanted)

        kpl_own = _kpl_comp(own_heroes)
        kpl_foe = _kpl_comp(foe_heroes)
        matchup = _tag_matchup(corpus, (row.get('vector') or {}).get('compOwn'),
                               (row.get('vector') or {}).get('compFoe'), exclude_keys)

        def pair_status(pair, own_side):
            """一对组合在这局的下场：拿到 / 被拆 / 被抢 / 两边都没拿到。"""
            if own_side:
                got = [hero for hero in pair if hero in own_heroes]
                lost_ban = [hero for hero in pair if hero in bans_foe]
                lost_pick = [hero for hero in pair if hero in foe_heroes]
            else:
                got = [hero for hero in pair if hero in foe_heroes]
                lost_ban = [hero for hero in pair if hero in bans_own]
                lost_pick = [hero for hero in pair if hero in own_heroes]
            if len(got) == 2:
                return {'status': 'got', 'kept': list(pair), 'lost': None, 'by': None}
            if len(got) == 1 and lost_ban:
                return {'status': 'broken', 'kept': got[0], 'lost': lost_ban[0], 'by': 'ban'}
            if len(got) == 1 and lost_pick:
                return {'status': 'stolen', 'kept': got[0], 'lost': lost_pick[0], 'by': 'pick'}
            if lost_ban:
                return {'status': 'denied', 'kept': None, 'lost': lost_ban[0], 'by': 'ban'}
            if lost_pick:
                return {'status': 'denied', 'kept': None, 'lost': lost_pick[0], 'by': 'pick'}
            return {'status': 'open', 'kept': None, 'lost': None, 'by': None}

        def combo_rows(history, own_side):
            rows, seen = [], set()
            if history:
                # 空 Counter 是 falsy，直接 `or {}` 会退化成普通 dict，没有 most_common。
                pair_counts = history.get('pairs') or Counter()
                for pair, times in pair_counts.most_common(14):
                    if times < 3 or pair in seen:
                        continue
                    cell = pair_status(pair, own_side)
                    if cell['status'] == 'open':
                        continue
                    seen.add(pair)
                    rows.append({
                        'heroes': list(pair), 'n': times,
                        'wr': _rate((history.get('pairWins') or {}).get(pair, 0), times),
                        **cell,
                    })
            # 训练赛组合样本少，补 KPL 常用组合：他们拿到一张、我们 ban/抢掉另一张，
            # 就是「拆掉了一套成熟组合」。只收 KPL 样本 ≥20 局的配对。
            index = _kpl_index() or {}
            pairs_index = index.get('pairs') or {}
            kept_heroes = (own_heroes if own_side else foe_heroes)
            lost_bans = (bans_foe if own_side else bans_own)
            lost_picks = (foe_heroes if own_side else own_heroes)
            extra = []
            for kept in kept_heroes:
                for lost, by in [(hero, 'ban') for hero in lost_bans] + [(hero, 'pick') for hero in lost_picks]:
                    pair = tuple(sorted((kept, lost)))
                    if pair in seen:
                        continue
                    row = pairs_index.get(pair)
                    if not row or not _num(row.get('n')) or row['n'] < 20:
                        continue
                    extra.append({
                        'heroes': list(pair), 'n': int(row['n']), 'wr': _r(row.get('wr'), 1),
                        'status': 'broken' if by == 'ban' else 'stolen',
                        'kept': kept, 'lost': lost, 'by': by, 'source': 'KPL',
                    })
            extra.sort(key=lambda item: -item['n'])
            for item in extra[:2]:
                key = tuple(sorted(item['heroes']))
                if key in seen:
                    continue
                seen.add(key)
                rows.append(item)
            order = {'broken': 0, 'got': 1, 'stolen': 2, 'denied': 3, 'open': 4}
            rows.sort(key=lambda item: (order.get(item['status'], 9), -(item.get('n') or 0)))
            return rows[:2]

        combos = {
            'foe': combo_rows(foe_history, False),
            'own': combo_rows(own_history, True),
        }

        story = []
        for item in foe_wanted:
            if item['status'] == 'banned':
                story.append(f'ban 掉对手常用 {item["hero"]}（对手 {item["picks"]} 次用过、胜率 {item["rate"]}%），拆了对方首选。')
            elif item['status'] == 'stolen':
                story.append(f'先抢对手常用 {item["hero"]}，让对方少一个熟练点。')
        for item in own_wanted:
            if item['status'] == 'got':
                story.append(f'拿到自己常用 {item["hero"]}（我方 {item["picks"]} 次、胜率 {item["rate"]}%）。')
            elif item['status'] == 'banned':
                story.append(f'自己常用 {item["hero"]} 被对面 ban 掉。')
        if foe_wanted and all(item['status'] == 'open' for item in foe_wanted):
            story.append('对方最常用的几个英雄这局都没出现；可能是主动换体系，也可能是被 ban 位挤掉。')
        if kpl_own and kpl_own.get('available'):
            best = kpl_own.get('bestPair')
            story.append(f'五人组合在 KPL 的双人契合度 {kpl_own["pairWr"]}%（{kpl_own["pairHits"]} 对、样本 {kpl_own["pairN"]} 局）'
                         + (f'，最强一对 {best["heroes"][0]}+{best["heroes"][1]}（{best["wr"]}%，n={best["n"]}）。' if best else '。'))
        if matchup and matchup.get('enough'):
            story.append(f'双方功能对位在历史语料 {matchup["n"]} 局，我们赢 {matchup["wins"]} 局（{matchup["rate"]}%）。')
        if kpl_foe and kpl_foe.get('available') and kpl_foe.get('bestPair'):
            best = kpl_foe['bestPair']
            story.append(f'对方拿到 KPL 常用组合 {best["heroes"][0]}+{best["heroes"][1]}（{best["wr"]}%，n={best["n"]}）。')

        games.append({
            'gameIndex': row.get('gameIndex'), 'matchKey': row.get('matchKey'),
            'result': row.get('result'),
            'heroesOwn': own_heroes, 'heroesFoe': foe_heroes,
            'bansOwn': bans_own, 'bansFoe': bans_foe,
            'signature': {'own': own_signature, 'foe': foe_signature},
            'pick': {'own': _r(pick_own, 3), 'foe': _r(pick_foe, 3), 'edge': _r(pick_edge, 3)},
            'ban': {'deny': _r(deny_score, 3), 'conceded': _r(concede_score, 3),
                    'edge': _r(ban_edge, 3),
                    'denyItems': deny_items[:5], 'concedeItems': concede_items[:5]},
            'combo': {'ownRate': combo_own, 'ownN': own_comp['n'],
                      'foeRate': combo_foe, 'foeN': foe_comp['n'],
                      'edge': _r(combo_edge, 3)},
            'edge': _r(edge, 4), 'label': label,
            'plan': {
                'foeWanted': foe_wanted, 'ownWanted': own_wanted,
                'foeHits': sum(1 for item in foe_wanted if item['status'] in ('banned', 'stolen')),
                'ownHits': sum(1 for item in own_wanted if item['status'] == 'got'),
            },
            'kpl': {'own': kpl_own, 'foe': kpl_foe},
            'combos': combos,
            'matchup': matchup,
            'story': story[:5],
        })

    labelled = [game for game in games if _num(game.get('edge')) is not None]
    wins = [game['edge'] for game in labelled if game.get('result') == 'win']
    losses = [game['edge'] for game in labelled if game.get('result') == 'loss']
    # BP 质量拆成五项，每一份都带证据，不给一个难解释的总分。
    all_own = [hero for game in games for hero in game['heroesOwn']]
    all_foe = [hero for game in games for hero in game['heroesFoe']]
    hero_value = _mean([_num(_hero_row(hero, stats).get('value')) for hero in all_own])
    comfort = _mean([own_history['picks'].get(hero, 0) for hero in all_own])
    synergy_vals = [game['kpl']['own']['pairWr'] for game in games
                    if game.get('kpl') and game['kpl'].get('own')
                    and game['kpl']['own'].get('pairWr') is not None]
    synergy = _mean(synergy_vals)
    counter_n = sum(game['matchup']['n'] for game in games
                    if game.get('matchup') and game['matchup'].get('enough'))
    counter_w = sum(game['matchup']['wins'] for game in games
                    if game.get('matchup') and game['matchup'].get('enough'))
    counter = _rate(counter_w, counter_n)
    top_pool = {hero for hero, _count in own_history['picks'].most_common(24)}
    used = set(all_own)
    pool_cost = len(used & top_pool)
    quality = [
        {'key': 'hero', 'label': '单英雄价值', 'value': _r(hero_value, 3), 'unit': '',
         'evidence': f'我方 {len(all_own)} 个选人的历史价值均值；对方 {_r(_mean([_num(_hero_row(hero, stats).get("value")) for hero in all_foe]), 3)}。',
         'verdict': '偏高' if (hero_value or 0) > 0.02 else '偏低' if (hero_value or 0) < -0.02 else '接近平均'},
        {'key': 'comfort', 'label': '选手熟练度', 'value': _r(comfort, 1), 'unit': '次',
         'evidence': f'五人选人在我方历史里的平均出场次数；按每人每次选人计。',
         'verdict': '熟手' if (comfort or 0) >= 8 else '偏生' if (comfort or 0) < 3 else '一般'},
        {'key': 'synergy', 'label': '阵容协同', 'value': _r(synergy, 1), 'unit': '%',
         'evidence': '这套五人组合在 KPL 双人组合样本上的加权胜率；只作参照，不是本场预测。',
         'verdict': '有样本' if synergy is not None else '无样本'},
        {'key': 'counter', 'label': '对位克制', 'value': _r(counter, 1), 'unit': '%',
         'evidence': f'我方体系遇到对方体系的历史对位 {counter_n} 局，赢 {counter_w} 局。',
         'verdict': '占优' if (counter or 0) >= 55 else '下风' if (counter or 0) <= 45 else '接近'},
        {'key': 'pool', 'label': '英雄池成本', 'value': pool_cost, 'unit': '个',
         'evidence': f'我方常用前 24 个英雄里，这个 BO 已经用掉 {pool_cost} 个；剩 {max(0, 24 - pool_cost)} 个。',
         'verdict': '消耗大' if pool_cost >= 18 else '正常' if pool_cost <= 14 else '偏多'},
    ]
    top_foe_picks = sorted(((hero, count) for hero, count in (foe_history or {})
                            .get('picks', {}).items()), key=lambda item: -item[1])[:6] \
        if foe_history else []
    return {
        'games': games,
        'series': {
            'edgeMean': _r(_mean([game['edge'] for game in labelled]), 4),
            'pickMean': _r(_mean([game['pick']['edge'] for game in labelled
                                  if _num(game['pick']['edge']) is not None]), 4),
            'banMean': _r(_mean([game['ban']['edge'] for game in labelled
                                 if _num(game['ban']['edge']) is not None]), 4),
            'comboMean': _r(_mean([game['combo']['edge'] for game in labelled
                                   if _num(game['combo']['edge']) is not None]), 4),
            'winEdge': _r(_mean(wins), 4), 'lossEdge': _r(_mean(losses), 4),
            'edgeGames': len(labelled), 'advantageGames': sum(1 for game in labelled if game['edge'] >= 0.03),
            'count': len(games),
            'foePlanHits': sum(game['plan']['foeHits'] for game in games),
            'ownPlanHits': sum(game['plan']['ownHits'] for game in games),
            'quality': quality,
        },
        'opponent': {
            'name': opponent or '', 'games': (foe_history or {}).get('games', 0),
            'topPicks': [{'hero': hero, 'picks': count,
                          'rate': _pick_rate(foe_history, hero)} for hero, count in top_foe_picks],
            'bans': [{'hero': hero, 'n': count} for hero, count in
                     (foe_history or {}).get('bans', Counter()).most_common(6)],
        },
        'own': {
            'games': own_history['games'],
            'topPicks': [{'hero': hero, 'picks': count,
                          'rate': _pick_rate(own_history, hero)}
                         for hero, count in own_history['picks'].most_common(6)],
        },
    }


def _side_metrics(vector, side):
    """一局在某方视角下的效果指标：10 分钟差、终局差、团战、龙、塔、时长。"""
    vector = vector or {}
    sign = 1 if side == 'own' else -1
    at10 = _num(vector.get('at10'))
    final_diff = _num(vector.get('finalDiff'))
    obj10 = vector.get('objAt10') or {}
    dragon = (_num(obj10.get('dragonOwn')) - _num(obj10.get('dragonFoe'))) \
        if _num(obj10.get('dragonOwn')) is not None and _num(obj10.get('dragonFoe')) is not None else None
    tower = (_num(obj10.get('towerOwn')) - _num(obj10.get('towerFoe'))) \
        if _num(obj10.get('towerOwn')) is not None and _num(obj10.get('towerFoe')) is not None else None
    fight = _fight_rate(vector)
    return {
        'at10': _r(at10 * sign, 1) if at10 is not None else None,
        'finalDiff': _r(final_diff * sign, 1) if final_diff is not None else None,
        'dragon10': _r(dragon * sign, 1) if dragon is not None else None,
        'tower10': _r(tower * sign, 1) if tower is not None else None,
        'fightRate': _r(100 - fight, 1) if (fight is not None and side == 'foe') else _r(fight, 1),
        'duration': _r(vector.get('duration'), 0),
    }


def _bp_similar_block(rows, corpus, exclude_keys, series_date):
    """历史对照：按「分路 × 打法类型」找最像的阵容，给双方各一套。"""
    windows = []
    for key, label, days in BP_SIMILAR_WINDOWS:
        since = None
        if days and series_date:
            try:
                since = (datetime.date.fromisoformat(series_date)
                         - datetime.timedelta(days=days)).isoformat()
            except ValueError:
                since = None
        windows.append({'key': key, 'label': label, 'days': days, 'since': since})
    games = []
    for row in rows:
        vector = row.get('vector') or {}
        entry = {
            'gameIndex': row.get('gameIndex'), 'matchKey': row.get('matchKey'),
            'result': row.get('result'),
            'heroesOwn': list(row.get('heroesOwn') or []),
            'heroesFoe': list(row.get('heroesFoe') or []),
            'signature': {'own': _signature(vector, 'own'),
                          'foe': _signature(vector, 'foe')},
            'self': {'own': _side_metrics(vector, 'own'),
                     'foe': _side_metrics(vector, 'foe')},
            'sides': {},
        }
        for side in ('own', 'foe'):
            signature = entry['signature'][side]
            cells = {}
            for window in windows:
                cells[window['key']] = _comp_matches(
                    corpus, signature, side, exclude_keys,
                    since=window['since'], until=series_date, min_overlap=3, limit=6)
            entry['sides'][side] = cells
        games.append(entry)
    return {
        'games': games,
        'windows': [{'key': window['key'], 'label': window['label'],
                     'days': window['days']} for window in windows],
        'note': '相似＝同分路同打法类型（战边/坦野/法核/游射/开团辅…）；'
                '换英雄但分工相同也算像。对手视角的胜负按「对手赢」统计。',
    }


# ---------------------------------------------------------------- BO 赛制的 BP 习惯
BO_CLASS_LABEL = {'sacrifice': '赛马', 'allin': '梭哈', 'normal': '常规'}


def _bo_class(gap):
    if gap is None:
        return 'normal'
    if gap <= -0.03:
        return 'sacrifice'
    if gap >= 0.03:
        return 'allin'
    return 'normal'


def _bo_profile_block(rows, series, series_briefs, corpus_index, stats):
    """对手在同一赛制（BO3/5/7）下的 BP 习惯：第一把投入、轮换、ban 偏好与异常。

    没有 BP 手序的局只按「终局阵容」分析，不推断先手后手；有手序时前端另标。
    """
    best_of = int(series.get('bestOf') or 0)
    opponent = str(series.get('opponent') or '').strip()
    if not best_of:
        return {'available': False, 'bestOf': best_of}

    def value_of(heroes, side):
        key = 'ownValue' if side == 'own' else 'foeValue'
        cells = [_hero_row(hero, stats) for hero in heroes if hero]
        return _mean([cell.get(key) for cell in cells])

    def entry_from(brief):
        games = []
        for game in sorted(brief.get('games') or [], key=lambda item: item.get('gameIndex') or 0):
            vector = corpus_index.get(str(game.get('matchKey')))
            if not vector:
                continue
            own = list(vector.get('heroes') or [])
            foe = list(vector.get('heroesFoe') or [])
            result = vector.get('result')
            at10 = _num(vector.get('at10'))
            games.append({
                'index': game.get('gameIndex'),
                'result': 'win' if result == 'win' else 'loss' if result == 'loss' else None,
                'ownValue': _r(value_of(own, 'own'), 3),
                'foeValue': _r(value_of(foe, 'foe'), 3),
                'ownTags': list(vector.get('compOwn') or []),
                'foeTags': list(vector.get('compFoe') or []),
                'foeBans': list(vector.get('bansFoe') or []),
                'ownBans': list(vector.get('bansOwn') or []),
                'foePicks': list(vector.get('heroesFoe') or []),
                'ownPicks': list(vector.get('heroes') or []),
                'at10': _r(-at10, 1) if at10 is not None else None,
                'duration': _r(vector.get('duration'), 0),
            })
        if not games:
            return None
        # 与当前大场一致：只按真正有数据的局连续编号。历史 BO7 若只采到
        # 若干局，不能把缺口当成「第三把/第五把」。
        for seq, game in enumerate(games, 1):
            game['sourceIndex'] = game.get('index')
            game['index'] = seq
        first = games[0]
        later = [game['foeValue'] for game in games[1:] if game['foeValue'] is not None]
        gap = (first['foeValue'] - _mean(later)) \
            if first.get('foeValue') is not None and later else None
        own_later = [game['ownValue'] for game in games[1:] if game['ownValue'] is not None]
        own_gap = (first['ownValue'] - _mean(own_later)) \
            if first.get('ownValue') is not None and own_later else None
        switches = 0
        for prev, current in zip(games, games[1:]):
            if set(prev.get('foeTags') or []) != set(current.get('foeTags') or []):
                switches += 1
        return {
            'id': brief.get('id'), 'date': str(brief.get('startAt') or '')[:10],
            'bestOf': best_of, 'opponent': brief.get('opponent') or '',
            'sameOpponent': str(brief.get('opponent') or '').strip() == opponent,
            'games': games,
            'firstValue': first.get('foeValue'),
            'laterValue': _r(_mean(later), 3),
            'gap': _r(gap, 3),
            'class': _bo_class(gap),
            'ownFirst': first.get('ownValue'),
            'ownLater': _r(_mean(own_later), 3),
            'ownGap': _r(own_gap, 3),
            'ownClass': _bo_class(own_gap),
            'switches': switches,
            'wins': sum(1 for game in games if game.get('result') == 'win'),
            'losses': sum(1 for game in games if game.get('result') == 'loss'),
        }

    history = []
    for brief in series_briefs or []:
        if str(brief.get('id')) == str(series.get('id')):
            continue
        if int(brief.get('bestOf') or 0) != best_of:
            continue
        item = entry_from(brief)
        if item:
            history.append(item)
    history.sort(key=lambda item: item.get('date') or '', reverse=True)

    current_games = []
    for row in rows:
        vector = row.get('vector') or {}
        own = list(row.get('heroesOwn') or [])
        foe = list(row.get('heroesFoe') or [])
        at10 = _num(row.get('at10'))
        current_games.append({
            'index': row.get('gameIndex'),
            'result': row.get('result'),
            'ownValue': _r(value_of(own, 'own'), 3),
            'foeValue': _r(value_of(foe, 'foe'), 3),
            'ownTags': list(vector.get('compOwn') or []),
            'foeTags': list(vector.get('compFoe') or []),
            'foeBans': list(row.get('bansFoe') or []),
            'ownBans': list(row.get('bansOwn') or []),
            'foePicks': list(foe),
            'ownPicks': list(own),
            'at10': _r(-at10, 1) if at10 is not None else None,
            'duration': _r(row.get('duration'), 0),
        })
    current = None
    if current_games:
        first = current_games[0]
        later = [game['foeValue'] for game in current_games[1:] if game['foeValue'] is not None]
        gap = (first['foeValue'] - _mean(later)) \
            if first.get('foeValue') is not None and later else None
        own_later = [game['ownValue'] for game in current_games[1:] if game['ownValue'] is not None]
        own_gap = (first['ownValue'] - _mean(own_later)) \
            if first.get('ownValue') is not None and own_later else None
        switches = sum(1 for prev, cur in zip(current_games, current_games[1:])
                       if set(prev.get('foeTags') or []) != set(cur.get('foeTags') or []))
        current = {
            'id': series.get('id'), 'date': str(series.get('startAt') or '')[:10],
            'opponent': opponent, 'games': current_games,
            'firstValue': first.get('foeValue'), 'laterValue': _r(_mean(later), 3),
            'gap': _r(gap, 3), 'class': _bo_class(gap), 'switches': switches,
            'ownFirst': first.get('ownValue'), 'ownLater': _r(_mean(own_later), 3),
            'ownGap': _r(own_gap, 3), 'ownClass': _bo_class(own_gap),
        }

    same_opponent = [item for item in history if item.get('sameOpponent')]
    baseline_pool = same_opponent if len(same_opponent) >= 2 else history
    first_values = [item['firstValue'] for item in baseline_pool
                    if item.get('firstValue') is not None]
    gaps = [item['gap'] for item in baseline_pool if item.get('gap') is not None]
    own_gaps = [item['ownGap'] for item in baseline_pool if item.get('ownGap') is not None]
    switches_pool = [item.get('switches') for item in baseline_pool
                     if item.get('switches') is not None]
    classes = Counter(item['class'] for item in baseline_pool)
    baseline = {
        'series': len(baseline_pool),
        'sameOpponent': len(same_opponent),
        'firstMean': _r(_mean(first_values), 3),
        'firstStd': _r(_std(first_values), 3),
        'gapMean': _r(_mean(gaps), 3),
        'ownGapMean': _r(_mean(own_gaps), 3),
        'switchMean': _r(_mean(switches_pool), 1),
        'classes': [{'key': key, 'label': BO_CLASS_LABEL[key], 'n': count}
                    for key, count in classes.most_common()],
        'majority': (classes.most_common(1)[0][0] if classes else None),
    }

    def hero_counts(items, key):
        counter = Counter()
        for item in items:
            for game in item.get('games') or []:
                for hero in game.get(key) or []:
                    counter[hero] += 1
        return counter

    foe_bans = hero_counts(baseline_pool, 'foeBans')
    anomalies = []
    if current and baseline['series'] >= 2:
        mean_first = baseline.get('firstMean')
        if mean_first is not None and current.get('firstValue') is not None:
            delta = current['firstValue'] - mean_first
            if abs(delta) >= 0.03:
                anomalies.append({
                    'level': 'high' if abs(delta) >= 0.06 else 'medium',
                    'title': f'第一把的投入{"低于" if delta < 0 else "高于"}他们平时',
                    'detail': f'这场第一把对方阵容价值 {current["firstValue"]:+.3f}，'
                              f'他们在 BO{best_of} 第一把平均 {mean_first:+.3f}（{len(first_values)} 场）。'
                              + ('像是先让一局（赛马）。' if delta < 0 else '开场就上强度（梭哈）。'),
                })
        if baseline.get('majority') and current.get('class') != baseline['majority']:
            anomalies.append({
                'level': 'medium',
                'title': f'这场的开局类型变了：{BO_CLASS_LABEL[current["class"]]}',
                'detail': f'对手过去 BO{best_of} 多数是{BO_CLASS_LABEL[baseline["majority"]]}，'
                          f'这场第一把与后续的差值 {current.get("gap")}，归类为{BO_CLASS_LABEL[current["class"]]}。',
            })
        if baseline.get('switchMean') is not None and current.get('switches') is not None \
                and current['switches'] > (baseline.get('switchMean') or 0) + 1:
            anomalies.append({
                'level': 'medium',
                'title': '局间体系切换比平时更频繁',
                'detail': f'这场换了 {current["switches"]} 次体系，'
                          f'他们 BO{best_of} 平均 {baseline["switchMean"]} 次；核对是被迫改体系还是主动轮换。',
            })
        current_bans = set()
        for game in current.get('games') or []:
            current_bans.update(game.get('foeBans') or [])
        known_bans = set(foe_bans)
        new_bans = sorted(current_bans - known_bans)
        if new_bans and len(known_bans) >= 5:
            anomalies.append({
                'level': 'low',
                'title': '出现了以前没怎么 ban 的英雄',
                'detail': f'这场对手 ban 了 {("、".join(new_bans[:3]))}，'
                          f'在他们过去 {len(baseline_pool)} 场 BO{best_of} 的 ban 里没出现过；先确认是针对还是误判。',
            })

    return {
        'available': bool(history or current),
        'bestOf': best_of,
        'opponent': opponent,
        'orderKnown': any(bool(row.get('orderKnown')) for row in rows),
        'current': current,
        'history': history[:12],
        'baseline': baseline,
        'foeBans': [{'hero': hero, 'n': count} for hero, count in foe_bans.most_common(8)],
        'anomalies': anomalies[:4],
    }


# ---------------------------------------------------------------- 统一对比基准
def _first_side(vector, key):
    first = vector.get('first') or {}
    side = first.get(key)
    return 1 if side == 'own' else 0 if side == 'foe' else None


def _metric_game(vector, stats):
    vector = vector or {}
    own = vector.get('camp')
    at10 = _num(vector.get('at10'))
    final_diff = _num(vector.get('finalDiff'))
    obj10 = vector.get('objAt10') or {}
    dragon = (_num(obj10.get('dragonOwn')) - _num(obj10.get('dragonFoe'))) \
        if _num(obj10.get('dragonOwn')) is not None and _num(obj10.get('dragonFoe')) is not None else None
    tower = (_num(obj10.get('towerOwn')) - _num(obj10.get('towerFoe'))) \
        if _num(obj10.get('towerOwn')) is not None and _num(obj10.get('towerFoe')) is not None else None
    obj = vector.get('obj') or {}
    death = vector.get('death') or {}
    cut = vector.get('cut') or {}
    obj_types = vector.get('objTypes')
    dragon_types = {}
    for name, cell in (obj_types or {}).items():
        if not isinstance(cell, dict):
            continue
        dragon_types[str(name)] = {'own': _num(cell.get('own')), 'foe': _num(cell.get('foe'))}
    own_heroes = list(vector.get('heroes') or [])
    foe_heroes = list(vector.get('heroesFoe') or [])
    own_value = _mean([_hero_row(hero, stats).get('ownValue') for hero in own_heroes])
    foe_value = _mean([_hero_row(hero, stats).get('foeValue') for hero in foe_heroes])
    pl = [player for player in vector.get('pl') or [] if player.get('camp') == own]
    total_gpm = sum(_num(player.get('gpm')) or 0 for player in pl)
    shares = []
    if total_gpm:
        for player in pl:
            gpm = _num(player.get('gpm')) or 0
            shares.append({'pos': player.get('pos'), 'goldShare': _r(gpm / total_gpm * 100, 1),
                           'dpm': _r(player.get('dpm'), 0)})
        shares.sort(key=lambda item: -(item.get('goldShare') or 0))
    return {
        'result': vector.get('result'),
        'at10': _r(at10, 1), 'finalDiff': _r(final_diff, 1),
        'dragon10': _r(dragon, 1), 'tower10': _r(tower, 1),
        'fightRate': _r(_fight_rate(vector), 1),
        'duration': _r(vector.get('duration'), 0),
        'ownValue': _r(own_value, 3), 'foeValue': _r(foe_value, 3),
        'ownTags': list(vector.get('compOwn') or []),
        'foeTags': list(vector.get('compFoe') or []),
        'shares': shares,
        # 总览指标板用的逐局字段；没有回放的局保持 None。
        'firstBlood': _first_side(vector, 'bloodSide'),
        'firstTower': _first_side(vector, 'towerSide'),
        'firstDragon': _first_side(vector, 'dragonSide'),
        'towersOwn': _num(obj.get('towerOwn')), 'towersFoe': _num(obj.get('towerFoe')),
        'dragonsOwn': _num(obj.get('dragonOwn')), 'dragonsFoe': _num(obj.get('dragonFoe')),
        'dragonTypes': dragon_types or None,
        'cut': _num(cut.get('n')), 'cutJungle': _num(cut.get('jungle')),
        'cutTop': _num(cut.get('top')), 'cutSuffered': _num(cut.get('suffered')),
        'killsOwn': _num(vector.get('killsOwn')), 'killsFoe': _num(vector.get('killsFoe')),
        'deathsOwn': _num(death.get('own')), 'deathsFoe': _num(death.get('foe')),
    }


def _aggregate_series(games):
    results = [game.get('result') for game in games if game.get('result') in ('win', 'loss')]
    wins = sum(1 for result in results if result == 'win')
    at10 = [game.get('at10') for game in games if _num(game.get('at10')) is not None]
    leads = [game for game in games if _num(game.get('at10')) is not None and game['at10'] > 0]
    holds = sum(1 for game in leads if game.get('result') == 'win')
    fight = [game.get('fightRate') for game in games if _num(game.get('fightRate')) is not None]
    dragon = [game.get('dragon10') for game in games if _num(game.get('dragon10')) is not None]
    tower = [game.get('tower10') for game in games if _num(game.get('tower10')) is not None]
    durations = [game.get('duration') for game in games if _num(game.get('duration')) is not None]
    own_values = [game.get('ownValue') for game in games if _num(game.get('ownValue')) is not None]
    first_value = games[0].get('ownValue') if games else None
    later_values = [game.get('ownValue') for game in games[1:]
                    if _num(game.get('ownValue')) is not None]

    def flag(key):
        values = [game.get(key) for game in games if _num(game.get(key)) is not None]
        return {'own': sum(1 for value in values if value == 1), 'n': len(values),
                'rate': _rate(sum(1 for value in values if value == 1), len(values))}

    first_blood = flag('firstBlood')
    first_tower = flag('firstTower')
    first_dragon = flag('firstDragon')

    def pair(own_key, foe_key):
        own = [game.get(own_key) for game in games if _num(game.get(own_key)) is not None]
        foe = [game.get(foe_key) for game in games if _num(game.get(foe_key)) is not None]
        if not own and not foe:
            return {'ownMean': None, 'foeMean': None, 'diffMean': None,
                    'totalOwn': 0, 'totalFoe': 0, 'rate': None, 'n': 0}
        total_own, total_foe = sum(own), sum(foe)
        return {
            'ownMean': _r(_mean(own), 2), 'foeMean': _r(_mean(foe), 2),
            'diffMean': _r((_mean(own) or 0) - (_mean(foe) or 0), 2),
            'totalOwn': int(total_own), 'totalFoe': int(total_foe),
            'rate': _rate(total_own, total_own + total_foe) if total_own + total_foe else None,
            'n': max(len(own), len(foe)),
        }

    towers = pair('towersOwn', 'towersFoe')
    dragons = pair('dragonsOwn', 'dragonsFoe')

    dragon_totals = {}
    for game in games:
        for name, cell in (game.get('dragonTypes') or {}).items():
            if not isinstance(cell, dict):
                continue
            item = dragon_totals.setdefault(name, {'own': 0, 'foe': 0, 'n': 0})
            if _num(cell.get('own')) is not None and _num(cell.get('foe')) is not None:
                item['own'] += cell['own']
                item['foe'] += cell['foe']
                item['n'] += 1
    dragon_types = [{'name': name, **cell,
                     'rate': _rate(cell['own'], cell['own'] + cell['foe'])
                     if cell['own'] + cell['foe'] else None}
                    for name, cell in dragon_totals.items()]
    dragon_types.sort(key=lambda item: (-item['own'] - item['foe'], item['name']))

    def mean_of(key):
        values = [game.get(key) for game in games if _num(game.get(key)) is not None]
        return {'mean': _r(_mean(values), 2), 'n': len(values), 'total': int(sum(values))}

    cuts = mean_of('cut')
    cuts_jungle = mean_of('cutJungle')
    cuts_top = mean_of('cutTop')
    cuts_suffered = mean_of('cutSuffered')
    kills = pair('killsOwn', 'killsFoe')
    deaths = pair('deathsOwn', 'deathsFoe')

    return {
        'games': len(games), 'wins': wins, 'losses': len(results) - wins,
        'gameWinRate': _rate(wins, len(results)),
        'at10Mean': _r(_mean(at10), 1),
        'leadRate': _rate(len(leads), len(at10)),
        'holdRate': _rate(holds, len(leads)),
        'fightRate': _r(_mean(fight), 1),
        'dragon10': _r(_mean(dragon), 2), 'tower10': _r(_mean(tower), 2),
        'duration': _r(_mean(durations), 0),
        'ownValue': _r(_mean(own_values), 3),
        'firstValue': _r(first_value, 3),
        'laterValue': _r(_mean(later_values), 3),
        'gap': _r((first_value or 0) - (_mean(later_values) or 0), 3)
        if first_value is not None and later_values else None,
        'firstBlood': first_blood, 'firstTower': first_tower, 'firstDragon': first_dragon,
        'towers': towers, 'dragons': dragons, 'dragonTypes': dragon_types,
        'cut': cuts, 'cutJungle': cuts_jungle, 'cutTop': cuts_top,
        'cutSuffered': cuts_suffered, 'kills': kills, 'deaths': deaths,
    }


DRAGON_ORDER = ('暴君', '主宰', '暗影暴君', '暗影主宰', '风暴龙王')


def _overview_block(rows, baseline):
    """总览指标板：逐局值 + 整场值 + 各对比窗口的基准值。

    指标选择遵循「教练真的会看」：一血 / 一塔 / 10 分钟经济差 / 四类中立资源 /
    推塔 / 团战胜率 / 切 C。每个指标只保留一个最直观的口径，不在前端重算。
    """
    games = []
    for row in rows:
        metric = row.get('metrics') or {}
        games.append({
            'gameIndex': row.get('gameIndex'), 'matchKey': row.get('matchKey'),
            'result': row.get('result'), 'duration': metric.get('duration'),
            'at10': metric.get('at10'), 'finalDiff': metric.get('finalDiff'),
            'firstBlood': metric.get('firstBlood'), 'firstTower': metric.get('firstTower'),
            'dragonTypes': metric.get('dragonTypes'),
        })

    def base_rate(mode, key):
        block = ((baseline.get('modes') or {}).get(mode, {}).get('metrics') or {}).get(key) or {}
        return block.get('rate') if isinstance(block, dict) else None

    def base_number(mode, key, field='mean'):
        block = ((baseline.get('modes') or {}).get(mode, {}).get('metrics') or {}).get(key) or {}
        return block.get(field) if isinstance(block, dict) else None

    def base_scalar(mode, key):
        return ((baseline.get('modes') or {}).get(mode, {}).get('metrics') or {}).get(key)

    modes = [key for key in ('prev', 'd3', 'd7', 'd30', 'format')
             if key in ((baseline.get('modes') or {}))]

    def flag_metric(key, group, label, hint, series):
        return {
            'key': key, 'group': group, 'label': label, 'hint': hint, 'kind': 'flag',
            'perGame': [row.get('metrics', {}).get(key) for row in rows],
            'series': series,
            'base': {mode: base_rate(mode, key) for mode in modes},
        }

    first_blood = (baseline.get('current') or {}).get('firstBlood') or {}
    first_tower = (baseline.get('current') or {}).get('firstTower') or {}
    metrics = [
        flag_metric('firstBlood', '开局', '一血', '谁先拿到本局第一滴血', first_blood),
        flag_metric('firstTower', '开局', '一塔', '谁先推掉第一座防御塔', first_tower),
        {
            'key': 'at10', 'group': '开局', 'label': '10′ 经济差', 'hint': '10 分钟我方减对方',
            'kind': 'num', 'unit': 'gold',
            'perGame': [row.get('metrics', {}).get('at10') for row in rows],
            'series': {'value': (baseline.get('current') or {}).get('at10Mean'),
                       'n': sum(1 for row in rows if _num(row.get('metrics', {}).get('at10')) is not None)},
            'base': {mode: base_scalar(mode, 'at10Mean') for mode in modes},
        },
    ]

    current = baseline.get('current') or {}
    dragon_types = {(item.get('name')): item for item in (current.get('dragonTypes') or [])}
    for name in DRAGON_ORDER:
        present = name in dragon_types or any(
            name in (row.get('metrics', {}).get('dragonTypes') or {}) for row in rows)
        # 四类常用龙固定列出：没有就显示「—」，不让教练以为这个指标不存在；
        # 风暴龙王只在真的出现时列，避免每场都挂一条 0。
        if not present and name == '风暴龙王':
            continue
        series = dragon_types.get(name) or {'own': None, 'foe': None, 'rate': None, 'n': 0}
        per_game = []
        for row in rows:
            cell = (row.get('metrics', {}).get('dragonTypes') or {}).get(name)
            per_game.append({'own': cell.get('own'), 'foe': cell.get('foe')}
                            if cell else None)
        base = {}
        for mode in modes:
            items = ((baseline.get('modes') or {}).get(mode, {}).get('metrics') or {}).get('dragonTypes') or []
            hit = next((item for item in items if item.get('name') == name), None)
            base[mode] = hit.get('rate') if hit else None
        metrics.append({
            'key': f'dragon:{name}', 'group': '中立资源', 'label': name,
            'hint': '我方拿到 : 对方拿到', 'kind': 'pair',
            'perGame': per_game,
            'series': {'own': series.get('own'), 'foe': series.get('foe'),
                       'rate': series.get('rate'), 'n': series.get('n')},
            'base': base,
        })

    towers = current.get('towers') or {}
    metrics.append({
        'key': 'towers', 'group': '推进', 'label': '推塔', 'hint': '全场摧毁的防御塔',
        'kind': 'pair',
        'perGame': [{'own': row.get('metrics', {}).get('towersOwn'),
                     'foe': row.get('metrics', {}).get('towersFoe')} for row in rows],
        'series': {'own': towers.get('ownMean'), 'foe': towers.get('foeMean'),
                   'rate': towers.get('rate'), 'diff': towers.get('diffMean'),
                   'n': towers.get('n')},
        'base': {mode: base_rate(mode, 'towers') for mode in modes},
        'baseDiff': {mode: base_number(mode, 'towers', 'diffMean') for mode in modes},
    })

    metrics.append({
        'key': 'fightRate', 'group': '团战', 'label': '团战胜率', 'hint': '有击杀的团战里赢下的比例',
        'kind': 'pct',
        'perGame': [row.get('metrics', {}).get('fightRate') for row in rows],
        'series': {'value': current.get('fightRate'),
                   'n': sum(1 for row in rows if _num(row.get('metrics', {}).get('fightRate')) is not None)},
        'base': {mode: base_scalar(mode, 'fightRate') for mode in modes},
    })

    cuts = current.get('cut') or {}
    cuts_jungle = current.get('cutJungle') or {}
    cuts_suffered = current.get('cutSuffered') or {}
    metrics.append({
        'key': 'cut', 'group': '切入', 'label': '切 C', 'hint': '对抗路/打野击杀对方中路或发育路',
        'kind': 'num', 'unit': 'count',
        'perGame': [row.get('metrics', {}).get('cut') for row in rows],
        'series': {'value': cuts.get('mean'), 'total': cuts.get('total'), 'n': cuts.get('n')},
        'base': {mode: base_number(mode, 'cut') for mode in modes},
    })
    metrics.append({
        'key': 'cutJungle', 'group': '切入', 'label': '打野切 C', 'hint': '只算打野击杀对方中/射',
        'kind': 'num', 'unit': 'count',
        'perGame': [row.get('metrics', {}).get('cutJungle') for row in rows],
        'series': {'value': cuts_jungle.get('mean'), 'total': cuts_jungle.get('total'), 'n': cuts_jungle.get('n')},
        'base': {mode: base_number(mode, 'cutJungle') for mode in modes},
    })
    metrics.append({
        'key': 'cutSuffered', 'group': '切入', 'label': '被切 C', 'hint': '对方对抗路/打野击杀我方中/射',
        'kind': 'num', 'unit': 'count', 'reverse': True,
        'perGame': [row.get('metrics', {}).get('cutSuffered') for row in rows],
        'series': {'value': cuts_suffered.get('mean'), 'total': cuts_suffered.get('total'), 'n': cuts_suffered.get('n')},
        'base': {mode: base_number(mode, 'cutSuffered') for mode in modes},
    })

    coverage = {
        'firstBlood': sum(1 for row in rows if _num(row.get('metrics', {}).get('firstBlood')) is not None),
        'firstTower': sum(1 for row in rows if _num(row.get('metrics', {}).get('firstTower')) is not None),
        'objective': sum(1 for row in rows if row.get('metrics', {}).get('dragonTypes')),
        'towers': sum(1 for row in rows if _num(row.get('metrics', {}).get('towersOwn')) is not None),
        'cut': sum(1 for row in rows if _num(row.get('metrics', {}).get('cut')) is not None),
        'games': len(rows),
    }
    return {'games': games, 'metrics': metrics, 'coverage': coverage, 'modes': modes}


def _lane_cells(vector, side):
    """按分路取一方的英雄与打法类型；类型缺失时退回英雄默认分路类型。"""
    camp = (vector or {}).get('camp')
    cells = {}
    for player in (vector or {}).get('pl') or []:
        if not isinstance(player, dict):
            continue
        player_side = 'own' if player.get('camp') == camp else 'foe'
        if player_side != side:
            continue
        position = str(player.get('pos') or '')
        if position not in LANE_ORDER:
            continue
        archetype = str(player.get('arch') or player.get('archDefault') or '')
        if archetype == '待分类':
            archetype = ''
        cells[position] = {
            'hero': str(player.get('hero') or ''), 'type': archetype,
            'gpm': _num(player.get('gpm')), 'dpm': _num(player.get('dpm')),
            'part': _num(player.get('part')),
        }
    return cells


def _core_count(vector, side):
    camp = (vector or {}).get('camp')
    players = [player for player in (vector or {}).get('pl') or []
               if isinstance(player, dict) and _num(player.get('gpm')) is not None
               and (player.get('camp') == camp) == (side == 'own')]
    total = sum(player['gpm'] for player in players)
    if not total:
        return None
    shares = sorted((player['gpm'] / total * 100 for player in players), reverse=True)[:3]
    return sum(1 for share in shares if share >= 18)


def _comp_system_block(rows, corpus, opponent):
    own_history = _own_pick_history(corpus)
    foe_history = _team_pick_history(corpus, opponent)
    foil = _norm_team(opponent)
    hist_vectors = [vector for vector in corpus or []
                    if foil and _norm_team(vector.get('opponent')) == foil]

    hist_types = Counter()
    hist_games = 0
    for vector in hist_vectors:
        cells = _lane_cells(vector, 'foe')
        for lane, cell in cells.items():
            if cell.get('type'):
                hist_types[(lane, cell['type'])] += 1
        hist_games += 1

    games = []
    dist = {'own': {lane: Counter() for lane in LANE_ORDER},
            'foe': {lane: Counter() for lane in LANE_ORDER}}
    combos = {'own': Counter(), 'foe': Counter()}
    cores = {'own': Counter(), 'foe': Counter()}
    lane_stats = {'own': {lane: {'gpm': [], 'dpm': [], 'part': []} for lane in LANE_ORDER},
                  'foe': {lane: {'gpm': [], 'dpm': [], 'part': []} for lane in LANE_ORDER}}

    for row in rows:
        vector = row.get('vector') or {}
        entry = {'gameIndex': row.get('gameIndex'), 'result': row.get('result'),
                 'matchKey': row.get('matchKey')}
        for side in ('own', 'foe'):
            cells = _lane_cells(vector, side)
            types = {lane: cell.get('type') for lane, cell in cells.items() if cell.get('type')}
            for lane, cell in cells.items():
                if cell.get('type'):
                    dist[side][lane][cell['type']] += 1
                for key in ('gpm', 'dpm', 'part'):
                    if _num(cell.get(key)) is not None:
                        lane_stats[side][lane][key].append(cell[key])
            jungle = types.get('打野')
            top = types.get('对抗路')
            combo = f'{jungle} + {top}' if jungle and top else None
            if combo:
                combos[side][combo] += 1
            core_n = _core_count(vector, side)
            if core_n is not None:
                cores[side][core_n] += 1
            heroes = []
            for lane in LANE_ORDER:
                cell = cells.get(lane)
                if not cell or not cell.get('hero'):
                    continue
                own_apps = (own_history or {}).get('picks', {}).get(cell['hero'], 0)
                foe_apps = (foe_history or {}).get('picks', {}).get(cell['hero'], 0)
                status = 'both' if own_apps and foe_apps else 'own' if own_apps \
                    else 'foe' if foe_apps else 'none'
                heroes.append({'hero': cell['hero'], 'lane': lane, 'type': cell.get('type'),
                               'ownApps': own_apps, 'foeApps': foe_apps, 'status': status})
            entry[side] = {'types': types, 'combo': combo, 'cores': core_n, 'heroes': heroes,
                           'adc': types.get('发育路'), 'support': types.get('游走'),
                           'mid': types.get('中路')}
        games.append(entry)

    def dist_rows(side):
        out = {}
        for lane in LANE_ORDER:
            counter = dist[side][lane]
            total = sum(counter.values())
            out[lane] = [{'type': key, 'n': count,
                          'pct': _r(count / total * 100, 0) if total else None}
                         for key, count in counter.most_common()]
        return out

    def combo_rows(side):
        total = sum(combos[side].values())
        return [{'label': label, 'n': count,
                 'pct': _r(count / total * 100, 0) if total else None}
                for label, count in combos[side].most_common()]

    def core_rows(side):
        total = sum(cores[side].values())
        return [{'n': key, 'games': count,
                 'pct': _r(count / total * 100, 0) if total else None}
                for key, count in sorted(cores[side].items())]

    def stat_rows(side):
        out = {}
        for lane in LANE_ORDER:
            bucket = lane_stats[side][lane]
            out[lane] = {
                'gpm': _r(_mean(bucket['gpm']), 0) if bucket['gpm'] else None,
                'dpm': _r(_mean(bucket['dpm']), 0) if bucket['dpm'] else None,
                'part': _r(_mean(bucket['part']), 1) if bucket['part'] else None,
                'n': max(len(bucket['gpm']), len(bucket['dpm']), len(bucket['part'])),
            }
        return out

    anomalies = []
    for lane in LANE_ORDER:
        counter = dist['foe'][lane]
        total = sum(counter.values())
        if total < 2 or hist_games < 3 or not counter:
            continue
        main_type, count = counter.most_common(1)[0]
        current_share = count / total
        history_share = hist_types.get((lane, main_type), 0) / hist_games
        if current_share - history_share >= 0.35 and count >= 2:
            anomalies.append({
                'level': 'medium',
                'title': f'对手{lane}换了口味：{main_type} {count}/{total} 局',
                'detail': f'他们过去 {hist_games} 局里{lane}用{main_type}的比例约 '
                          f'{_r(history_share * 100, 0)}%，这场 {_r(current_share * 100, 0)}%；'
                          '先确认是主动换体系还是被 ban 位逼的。',
            })
    if not anomalies and hist_games >= 3:
        anomalies.append({
            'level': 'low',
            'title': f'对手这套体系与过去 {hist_games} 局基本一致',
            'detail': '五个分路的打法类型没有明显跳变；差异更多在具体英雄与对位，不在体系。',
        })

    return {
        'games': games,
        'distribution': {'own': dist_rows('own'), 'foe': dist_rows('foe')},
        'combos': {'own': combo_rows('own'), 'foe': combo_rows('foe')},
        'cores': {'own': core_rows('own'), 'foe': core_rows('foe')},
        'stats': {'own': stat_rows('own'), 'foe': stat_rows('foe')},
        'anomalies': anomalies,
        'historyGames': hist_games,
        'ownHistoryGames': (own_history or {}).get('games') or 0,
        'foeHistoryGames': (foe_history or {}).get('games') or 0,
    }


def _baseline_block(series, rows, series_briefs, corpus_index, stats):
    """大场对比控制台：上一场同赛制 / 近 3·7·30 天 / 同赛制历史。

    统计单位分开：大场胜率按 BO，局胜率按单局；同一 BO 的小局不当作独立系列赛。
    """
    current_games = [_metric_game(row.get('vector'), stats) for row in rows]
    current = _aggregate_series(current_games)
    current['series'] = 1
    current['seriesWins'] = 1 if (current.get('wins') or 0) > (current.get('losses') or 0) else 0
    current['seriesLosses'] = 1 if (current.get('losses') or 0) > (current.get('wins') or 0) else 0
    current_date = str(series.get('startAt') or '')[:10]
    best_of = int(series.get('bestOf') or 0)
    opponent = str(series.get('opponent') or '').strip()

    history = []
    for brief in series_briefs or []:
        if str(brief.get('id')) == str(series.get('id')):
            continue
        if int(brief.get('bestOf') or 0) != best_of:
            continue
        games = []
        for game in brief.get('games') or []:
            vector = corpus_index.get(str(game.get('matchKey')))
            if vector:
                games.append(_metric_game(vector, stats))
        if not games:
            continue
        item = {
            'id': brief.get('id'), 'date': str(brief.get('startAt') or '')[:10],
            'opponent': brief.get('opponent') or '',
            'sameOpponent': str(brief.get('opponent') or '').strip() == opponent,
            'games': games, 'metrics': _aggregate_series(games),
        }
        history.append(item)
    history.sort(key=lambda item: item.get('date') or '', reverse=True)

    def window(days):
        if not current_date:
            return []
        try:
            since = (datetime.date.fromisoformat(current_date)
                     - datetime.timedelta(days=days)).isoformat()
        except ValueError:
            return []
        return [item for item in history if (item.get('date') or '') >= since]

    modes = {
        'prev': {'label': '上一场同赛制', 'series': []},
        'd3': {'label': '近 3 天', 'series': window(3)},
        'd7': {'label': '近 7 天', 'series': window(7)},
        'd30': {'label': '近 30 天', 'series': window(30)},
        'format': {'label': '同赛制历史', 'series': history[:12]},
    }
    if history:
        previous = next((item for item in history
                         if item.get('sameOpponent') and (item.get('date') or '') <= current_date), None)
        if previous is None:
            previous = next((item for item in history if (item.get('date') or '') <= current_date), None)
        if previous is not None:
            modes['prev']['series'] = [previous]
    for key, mode in modes.items():
        pool = [game for item in mode['series'] for game in item.get('games') or []]
        metrics = _aggregate_series(pool)
        metrics['series'] = len(mode['series'])
        metrics['seriesWins'] = sum(1 for item in mode['series']
                                    if (item['metrics'].get('wins') or 0) > (item['metrics'].get('losses') or 0))
        metrics['seriesLosses'] = sum(1 for item in mode['series']
                                      if (item['metrics'].get('losses') or 0) > (item['metrics'].get('wins') or 0))
        mode['metrics'] = metrics
        mode['ids'] = [item.get('id') for item in mode['series']]
        del mode['series']
    by_game = {}
    for item in history:
        for index, game in enumerate(item.get('games') or [], start=1):
            if game.get('result') not in ('win', 'loss'):
                continue
            cell = by_game.setdefault(index, {'index': index, 'wins': 0, 'n': 0})
            cell['n'] += 1
            cell['wins'] += 1 if game['result'] == 'win' else 0
    by_game_rows = [{'index': index, 'wins': cell['wins'], 'n': cell['n'],
                     'rate': _rate(cell['wins'], cell['n'])}
                    for index, cell in sorted(by_game.items())]
    return {
        'mode': 'prev', 'bestOf': best_of, 'current': current,
        'modes': modes, 'byGame': by_game_rows,
        'history': [{key: item[key] for key in
                     ('id', 'date', 'opponent', 'sameOpponent')}
                    for item in history],
    }


# ---------------------------------------------------------------- 阵容能力与结构
CAP_COLLISION = (
    ('开团', '反开', '我们怎么开，对面怎么反'),
    ('控制', '续航', '控制链能不能压住对面的回复'),
    ('爆发', '保护', '爆发点能不能穿过保护'),
    ('推进', '清线', '推进节奏会不会被清线拖住'),
    ('切入', '保护', '突进能不能切到核心'),
    ('消耗', '续航', '消耗能不能磨穿回复'),
)


def _comp_block(rows, stats):
    games = []
    for row in rows:
        vector = row.get('vector') or {}
        own = [str(hero) for hero in row.get('heroesOwn') or [] if hero]
        foe = [str(hero) for hero in row.get('heroesFoe') or [] if hero]
        own_caps = hero_capabilities.lineup_capabilities(own)
        foe_caps = hero_capabilities.lineup_capabilities(foe)
        pl = [player for player in vector.get('pl') or [] if player.get('camp') == vector.get('camp')]
        total = sum(_num(player.get('gpm')) or 0 for player in pl)
        shares = []
        if total:
            for player in pl:
                gpm = _num(player.get('gpm')) or 0
                shares.append({'pos': player.get('pos'), 'hero': player.get('hero'),
                               'goldShare': _r(gpm / total * 100, 1),
                               'dmgShare': None})
            for cell in shares:
                same = next((player for player in pl if player.get('pos') == cell['pos']), None)
                if same and _num(same.get('dpm')) is not None:
                    total_dpm = sum(_num(player.get('dpm')) or 0 for player in pl)
                    cell['dmgShare'] = _r((_num(same.get('dpm')) or 0) / total_dpm * 100, 1) if total_dpm else None
            shares.sort(key=lambda item: -(item.get('goldShare') or 0))
        cores = [cell for cell in shares[:3] if (cell.get('goldShare') or 0) >= 18]
        games.append({
            'gameIndex': row.get('gameIndex'), 'matchKey': row.get('matchKey'),
            'result': row.get('result'),
            'own': own, 'foe': foe,
            'ownTags': list(vector.get('compOwn') or []),
            'foeTags': list(vector.get('compFoe') or []),
            'ownCaps': own_caps, 'foeCaps': foe_caps,
            'shares': shares, 'cores': cores,
        })
    capabilities = list(hero_capabilities.CAPABILITIES)
    own_mean = {cap: _r(_mean([game['ownCaps'].get(cap, 0) for game in games]), 2) for cap in capabilities}
    foe_mean = {cap: _r(_mean([game['foeCaps'].get(cap, 0) for game in games]), 2) for cap in capabilities}
    collisions = []
    for own_cap, foe_cap, hint in CAP_COLLISION:
        own_value = own_mean.get(own_cap) or 0
        foe_value = foe_mean.get(foe_cap) or 0
        if not own_value and not foe_value:
            continue
        collisions.append({
            'ownCap': own_cap, 'foeCap': foe_cap, 'hint': hint,
            'own': own_value, 'foe': foe_value,
            'verdict': '我们占优' if own_value > foe_value else '对方占优' if foe_value > own_value else '持平',
        })
    return {
        'games': games,
        'capabilities': capabilities,
        'series': {'own': own_mean, 'foe': foe_mean, 'collisions': collisions,
                   'coreCount': [len(game['cores']) for game in games]},
    }


# ---------------------------------------------------------------- 局间进化
def _evolution_block(rows, stats, own_history, corpus):
    signatures = [_signature(row.get('vector') or {}, 'own') for row in rows]
    transitions = []
    for index in range(1, len(rows)):
        prev, cur = rows[index - 1], rows[index]
        prev_own = set(prev.get('vector', {}).get('compOwn') or [])
        cur_own = set(cur.get('vector', {}).get('compOwn') or [])
        prev_foe = set(prev.get('vector', {}).get('compFoe') or [])
        cur_foe = set(cur.get('vector', {}).get('compFoe') or [])
        prev_sig = {(cell['position'], cell['archetype']) for cell in signatures[index - 1]}
        cur_sig = {(cell['position'], cell['archetype']) for cell in signatures[index]}
        tag_overlap = len(prev_own & cur_own) / max(1, len(prev_own | cur_own)) * 100
        role_changes = [position for position in LANE_ORDER
                        if dict(prev_sig).get(position) and dict(prev_sig).get(position) != dict(cur_sig).get(position)]
        prev_heroes = set(prev.get('heroesOwn') or [])
        cur_bans = set(cur.get('bansFoe') or [])
        direct = sorted(prev_heroes & cur_bans)
        prev_arch = {cell['archetype'] for cell in signatures[index - 1]}
        type_hits = []
        for hero in cur.get('bansFoe') or []:
            # 用英雄默认分路的类型做近似，仅作「同类针对」的提示，不当作确定意图
            archetype = hero_archetypes.archetype_of(hero)
            if archetype in prev_arch and hero not in direct:
                type_hits.append(hero)
        transitions.append({
            'from': prev.get('gameIndex'), 'to': cur.get('gameIndex'),
            'tagOverlap': _r(tag_overlap, 1),
            'roleChanges': role_changes,
            'foeTagOverlap': _r(len(prev_foe & cur_foe) / max(1, len(prev_foe | cur_foe)) * 100, 1),
            'responseDirect': direct[:4],
            'responseType': type_hits[:4],
            'forced': '全局 BP 下英雄必然更换，这里只看体系与角色结构是否延续。',
        })
    comfort = own_history['picks'].most_common(24)
    used = set()
    pool = []
    for row in rows:
        used.update(row.get('heroesOwn') or [])
        banned = set(row.get('bansFoe') or [])
        remaining = [(hero, count) for hero, count in comfort
                     if hero not in used and hero not in banned]
        values = [_hero_row(hero, stats).get('value') for hero, _count in remaining]
        pool.append({
            'gameIndex': row.get('gameIndex'),
            'remaining': len(remaining),
            'top': [hero for hero, _count in remaining[:5]],
            'valueMean': _r(_mean(values), 3),
        })
    lag = next((item['to'] for item in transitions
                if item.get('responseDirect') or item.get('responseType')), None)
    return {
        'transitions': transitions,
        'responseLag': lag,
        'pool': pool,
        'continuity': _r(_mean([item['tagOverlap'] for item in transitions]), 1),
        'responseHits': sum(len(item['responseDirect']) + len(item['responseType'])
                            for item in transitions),
        'identityChanges': sum(1 for item in transitions if item['roleChanges']),
    }


def _kpl_hit_block(bp_plan, series):
    """把每局我方五个选人拆成整阵容 / 双人 / 三人，去 KPL 历史里查「见没见过」。"""
    games = (bp_plan or {}).get('games') or []
    rows = []
    for game in games:
        kpl = (game.get('kpl') or {}).get('own') or {}
        lineup = kpl.get('lineup')
        rows.append({
            'gameIndex': game.get('gameIndex'),
            'lineup': bool(lineup and lineup.get('n')),
            'lineupN': (lineup or {}).get('n'),
            'lineupWr': (lineup or {}).get('wr'),
            'pairs': kpl.get('pairs') or [],
            'trios': kpl.get('trios') or [],
        })
    pairs = {}
    trios = {}
    for row in rows:
        for item in row['pairs']:
            key = tuple(item['heroes'])
            if key not in pairs or (item.get('n') or 0) > (pairs[key].get('n') or 0):
                pairs[key] = item
        for item in row['trios']:
            key = tuple(item['heroes'])
            if key not in trios or (item.get('n') or 0) > (trios[key].get('n') or 0):
                trios[key] = item
    pair_list = sorted(pairs.values(), key=lambda item: (-(item.get('n') or 0), -(item.get('wr') or 0)))
    trio_list = sorted(trios.values(), key=lambda item: (-(item.get('n') or 0), -(item.get('wr') or 0)))
    return {
        'available': bool(rows),
        'games': len(rows) or 0,
        'lineupGames': sum(1 for row in rows if row['lineup']),
        'pairGames': sum(1 for row in rows if row['pairs']),
        'trioGames': sum(1 for row in rows if row['trios']),
        'rows': rows,
        'pairs': pair_list[:6],
        'trios': trio_list[:4],
        'source': 'KPL 官方赛事',
    }


def _build_insights(rows, flow, phase, draft, players, fight, similar, analysis, quality=None):
    insights = []
    quality = quality or {}

    def add(kind, severity, title, detail, evidence, links, confidence, effect=0.0):
        insights.append({
            'kind': kind, 'severity': severity, 'title': title, 'detail': detail,
            'evidence': evidence, 'links': links, 'confidence': confidence,
            'effect': round(float(effect), 3),
        })

    if quality.get('duplicates'):
        groups = quality['duplicates']
        text = '；'.join('G' + '、G'.join(str(index) for index in group['gameIndexes'])
                        for group in groups[:4])
        add('quality', 'high', f'数据质量：{len(groups)} 组局的过程数据完全相同',
            f'{text} 的 10 分钟差、终局差、时长与双方阵容完全一致，几乎可以确定是重复采集或同一局被编了两次。'
            '跨局比例会把这些局重复计算，先核实编组/采集，再使用本页的系列结论。',
            [f'G{"/G".join(str(index) for index in group["gameIndexes"])} 指纹相同'
             for group in groups[:4]],
            _links([{'matchKey': key, 'gameIndex': index}
                    for group in groups
                    for key, index in zip(group.get('matchKeys') or [], group['gameIndexes'])]),
            'high', 100)
    if quality.get('draftInvalid') or quality.get('sameRoster'):
        items = quality.get('draftInvalid') or quality.get('sameRoster') or []
        text = '、'.join(f'G{item["gameIndex"]}' for item in items[:6])
        add('quality', 'high', f'数据质量：{len(items)} 局双方阵容缺失或完全相同',
            f'{text} 的 BP 名单不可用（双方阵容相同或缺一侧）。这些局已从 BP 价值汇总中剔除，'
            '保留原始记录供核实，不据此下选人结论。',
            [f'G{item["gameIndex"]}：{item.get("reason") or "双方阵容相同"}' for item in items[:6]],
            _links([{'matchKey': item.get('matchKey'), 'gameIndex': item.get('gameIndex')}
                    for item in items]), 'high', 90)

    wins = [row for row in rows if row.get('result') == 'win']
    losses = [row for row in rows if row.get('result') == 'loss']
    win_at10 = [_num(row.get('at10')) for row in wins if _num(row.get('at10')) is not None]
    loss_at10 = [_num(row.get('at10')) for row in losses if _num(row.get('at10')) is not None]
    if len(win_at10) >= 2 and len(loss_at10) >= 2:
        win_median, loss_median = _median(win_at10), _median(loss_at10)
        diff = win_median - loss_median
        if abs(diff) >= 600:
            severity = 'high' if abs(diff) >= 1500 else 'medium'
            if diff > 0:
                title = f'赢局 10 分钟中位比输局高 {_gold(diff)}'
                detail = (f'赢局 {len(win_at10)} 局 10 分钟中位 {_gold(win_median)}，'
                          f'输局 {len(loss_at10)} 局 {_gold(loss_median)}。'
                          '这条只说明过程与结果同向，不能单独当作因果。')
            else:
                title = f'赢局 10 分钟中位反而低 {_gold(abs(diff))}'
                detail = (f'赢局 10 分钟中位 {_gold(win_median)}，输局 {_gold(loss_median)}；'
                          '赢局靠中后期追回，输局反而更容易在前期拿到领先。')
            add('economy', severity, title, detail,
                [f'赢局 10′ 中位 {_gold(win_median)}（n={len(win_at10)}）',
                 f'输局 10′ 中位 {_gold(loss_median)}（n={len(loss_at10)}）'],
                _links(wins, losses), 'high' if len(rows) >= 5 else 'medium', abs(diff) / 1000)
    lost_lead = [row for row in losses if _num(row.get('at10')) is not None and row['at10'] > 500]
    if len(lost_lead) >= 2:
        items = [f"G{row['gameIndex']} {_gold(row['at10'])}→{_gold(row.get('finalDiff'))}"
                 for row in lost_lead]
        add('economy', 'high', f'前期领先没有兑现：{len(lost_lead)} 局 10 分钟领先仍失利',
            '这些局在 10 分钟有明确经济领先，但终局被追回；优先复盘中后期资源交换与团战决策。',
            items, _links(lost_lead), 'medium' if len(lost_lead) >= 3 else 'low',
            len(lost_lead))
    late_loss = [row for row in losses
                 if _num((row.get('phase') or {}).get('late')) is not None
                 and row['phase']['late'] < -1200]
    if len(late_loss) >= 2:
        items = [f"G{row['gameIndex']} 10′ 后 {_gold(row['phase']['late'])}" for row in late_loss]
        late_mean = _mean([row['phase']['late'] for row in late_loss])
        add('economy', 'medium', f'后期净失血：{len(late_loss)} 局 10 分钟后被拉开',
            f'这 {len(late_loss)} 局 10 分钟后的经济净变化均值 {_gold(late_mean)}；'
            '中后期运营/团战是主要失分点，优先复盘资源交换与开团时机。',
            items, _links(late_loss), 'medium', abs(late_mean or 0) / 1000)

    win_fight = [_num(row.get('fightRate')) for row in wins if _num(row.get('fightRate')) is not None]
    loss_fight = [_num(row.get('fightRate')) for row in losses if _num(row.get('fightRate')) is not None]
    if len(win_fight) >= 2 and len(loss_fight) >= 2:
        diff = (_mean(win_fight) or 0) - (_mean(loss_fight) or 0)
        if diff >= 15:
            add('fight', 'high' if diff >= 25 else 'medium', '团战转化与胜负同步',
                f'赢局的团战胜率 {_pct(_mean(win_fight))}，输局 {_pct(_mean(loss_fight))}，'
                f'相差 {_r(diff, 1)} 个百分点。团战赢没赢与结果同向，但仍是关联。',
                [f'赢局团战胜率 {_pct(_mean(win_fight))}（n={len(win_fight)}）',
                 f'输局团战胜率 {_pct(_mean(loss_fight))}（n={len(loss_fight)}）'],
                _links(wins, losses), 'medium', diff / 100)

    edge_wins = [_num(game.get('edge')) for game in draft.get('games') or []
                 if game.get('result') == 'win' and _num(game.get('edge')) is not None]
    edge_losses = [_num(game.get('edge')) for game in draft.get('games') or []
                   if game.get('result') == 'loss' and _num(game.get('edge')) is not None]
    if len(edge_wins) >= 2 and len(edge_losses) >= 2:
        win_mean, loss_mean = _mean(edge_wins), _mean(edge_losses)
        diff = (win_mean or 0) - (loss_mean or 0)
        if diff >= 0.03:
            both_ahead = (win_mean or 0) > 0.03 and (loss_mean or 0) > 0.03
            title = 'BP 端整体占优，但优势没有稳定转化' if both_ahead else 'BP 端价值与胜负同向'
            detail = (f'赢局平均 BP 价值 {_r(win_mean, 3)}，输局 {_r(loss_mean, 3)}。'
                      + ('输局在 BP 端也不落下风，说明问题更多在中后期执行与决策，而不是选人本身。'
                         if both_ahead else
                         '英雄价值来自历史收缩估计，不等于本场选人因果；但可作为复盘 BP 的入口。'))
            add('draft', 'medium', title, detail,
                [f'赢局 BP 价值 {_r(win_mean, 3)}（n={len(edge_wins)}）',
                 f'输局 BP 价值 {_r(loss_mean, 3)}（n={len(edge_losses)}）'],
                _links(wins, losses), 'medium', diff * 10)
    comfort_wins = [_num(game.get('ownComfort')) for game in draft.get('games') or []
                    if game.get('result') == 'win' and _num(game.get('ownComfort')) is not None]
    comfort_losses = [_num(game.get('ownComfort')) for game in draft.get('games') or []
                      if game.get('result') == 'loss' and _num(game.get('ownComfort')) is not None]
    if len(comfort_wins) >= 2 and len(comfort_losses) >= 2:
        diff = (_mean(comfort_wins) or 0) - (_mean(comfort_losses) or 0)
        if diff >= 0.2:
            add('draft', 'medium', '输局更多依赖生疏英雄',
                f'赢局舒适区英雄占比 {_pct((_mean(comfort_wins) or 0) * 100)}，'
                f'输局 {_pct((_mean(comfort_losses) or 0) * 100)}。'
                '全局 BP 下英雄池被压缩时，优先准备低出场英雄的替代方案。',
                [f'赢局舒适区占比 {_pct((_mean(comfort_wins) or 0) * 100)}',
                 f'输局舒适区占比 {_pct((_mean(comfort_losses) or 0) * 100)}'],
                _links(wins, losses), 'low', diff)

    repeat = Counter()
    for item in (analysis or {}).get('opponentResponse') or []:
        for hero in item.get('banRepeat') or []:
            repeat[str(hero)] += 1
    if repeat:
        hero, count = repeat.most_common(1)[0]
        if count >= 2:
            add('draft', 'medium', f'对手连续封锁 {hero}',
                f'对手在 {count} 次局间调整中重复 ban {hero}；结合该英雄的历史价值，'
                '判断是尊重绝活还是破坏体系。',
                [f'{hero} 重复 ban {count} 次'], _links(rows), 'medium', count)

    for player in players.get('players') or []:
        composite = _num(player.get('composite'))
        if composite is None or player.get('games', 0) < 2:
            continue
        if composite <= -0.8 and len(losses) >= 2:
            games = [game for game in player.get('perGame') or []
                     if game.get('result') == 'loss' and _num(game.get('composite')) is not None]
            add('player', 'medium', f'{player.get("name")} 的状态低于基线',
                f'{player.get("position")} 的状态分 {composite:+.2f}（相对'
                f'{"个人" if player.get("baseline") == "player" else "同位置"}基线）。'
                '这不是定责：状态分不含沟通/指挥/视野，先复盘对位与资源分配。',
                [f'状态分 {composite:+.2f}', f'样本 {player.get("games")} 局',
                 f'基线 {player.get("baseline") or "缺失"}'],
                _links(games or rows), 'low', abs(composite))
        elif composite >= 0.8 and len(wins) >= 2:
            games = [game for game in player.get('perGame') or []
                     if game.get('result') == 'win' and _num(game.get('composite')) is not None]
            add('player', 'low', f'{player.get("name")} 的状态高于基线',
                f'{player.get("position")} 的状态分 {composite:+.2f}，是本场相对稳定的点位。',
                [f'状态分 {composite:+.2f}', f'样本 {player.get("games")} 局'],
                _links(games or rows), 'low', composite)

    for key, label in (('dragon10Diff', '10 分钟龙'), ('tower10Diff', '10 分钟塔')):
        win_values = [_num(row.get(key)) for row in wins if _num(row.get(key)) is not None]
        loss_values = [_num(row.get(key)) for row in losses if _num(row.get(key)) is not None]
        if len(win_values) >= 2 and len(loss_values) >= 2:
            diff = (_mean(win_values) or 0) - (_mean(loss_values) or 0)
            if diff >= 1.5:
                add('objective', 'medium', f'{label}与胜负同向',
                    f'赢局平均 {_r(_mean(win_values), 1)}，输局 {_r(_mean(loss_values), 1)}。'
                    '资源控制与结果同向，优先核对前 10 分钟的节奏设计。',
                    [f'赢局 {label} {_r(_mean(win_values), 1)}（n={len(win_values)}）',
                     f'输局 {label} {_r(_mean(loss_values), 1)}（n={len(loss_values)}）'],
                    _links(wins, losses), 'low', diff / 2)

    disagreement = []
    for game in similar.get('games') or []:
        expected = _num(game.get('expectedWinRate'))
        if expected is None or game.get('result') not in ('win', 'loss'):
            continue
        if (game['result'] == 'loss' and expected >= 65) or (game['result'] == 'win' and expected <= 35):
            disagreement.append(game)
    if len(disagreement) >= 2:
        add('similar', 'medium', f'过程数据与结果背离：{len(disagreement)} 局',
            '历史相似局给出的参考胜率与结果方向相反；可能是执行/临场决策差异，'
            '也可能是相似局样本不足，先当作复盘线索而不是结论。',
            [f"G{game['gameIndex']} 历史参考 {_pct(game.get('expectedWinRate'))}，结果 {game.get('result')}"
             for game in disagreement],
            _links([{'matchKey': game.get('matchKey'), 'gameIndex': game.get('gameIndex')}
                    for game in disagreement]), 'low', len(disagreement))

    severity_weight = {'high': 3, 'medium': 2, 'low': 1}
    confidence_weight = {'high': 3, 'medium': 2, 'low': 1}
    insights.sort(key=lambda item: (-(severity_weight.get(item['severity'], 0) * 10
                                      + confidence_weight.get(item['confidence'], 0)),
                                    -item.get('effect', 0), item.get('title') or ''))
    return insights[:6]


def _headline(rows, insights):
    if not rows:
        return '本场没有可分析的局。'
    if not insights:
        return f'本场 {len(rows)} 局没有达到证据阈值的信号；先补齐过程数据再下钻。'
    first = insights[0]
    second = f'其次，{insights[1]["title"]}。' if len(insights) > 1 else ''
    return f'本场 {len(rows)} 局的优先信号：{first["title"]}。{second}'


def _methods(wp_model, clusters, stats, matrix, players, history_count):
    methods = []
    if wp_model:
        methods.append({
            'id': 'wp',
            'name': '经济差 → 胜率参考模型',
            'detail': 'L2 逻辑回归；特征为 1000 经济差及其与分钟数的交互；按对局分组 5 折交叉验证，'
                      '训练集排除本系列赛；经济持平/0 分钟锚定 50%。曲线只表示'
                      '「历史上类似经济差对应的胜率」，不是本场因果。',
            'metrics': {
                'samples': wp_model.get('n'), 'games': wp_model.get('games'),
                'auc': wp_model.get('auc'), 'aucAt10': wp_model.get('aucAt10'),
                'per1000At10': wp_model.get('per1000At10'),
                'per1000At20': wp_model.get('per1000At20'),
                'baseRate': wp_model.get('baseRate'),
            },
            'reliable': bool(wp_model.get('reliable')),
        })
    if clusters:
        methods.append({
            'id': 'shape',
            'name': '局面形态聚类',
            'detail': '把每局经济曲线按相对时长归一为 6 个点，标准化后做 k-means（固定种子）；'
                      '标签按早期/中期/后期均值启发式命名。',
            'metrics': {'n': clusters.get('n'), 'k': clusters.get('k')},
            'reliable': bool((clusters.get('n') or 0) >= 20),
        })
    methods.append({
        'id': 'hero',
        'name': '英雄价值收缩估计',
        'detail': f'按「选到该英雄的一方」统计胜率，向 50% 做 Beta-Binomial 收缩'
                  f'（先验强度 {EB_PRIOR_STRENGTH:g} 局）；附 Wilson 95% 区间。'
                  '已排除本系列赛对局，避免用结果反推 BP。',
        'metrics': {'games': stats.get('games'), 'ownApps': stats.get('ownApps'),
                    'foeApps': stats.get('foeApps')},
        'reliable': bool((stats.get('games') or 0) >= 20),
    })
    methods.append({
        'id': 'player',
        'name': '选手状态分',
        'detail': 'GPM / DPM / 参团 / KDA / 死亡相对个人基线（≥4 局）或同位置基线（≥8 局）'
                  '做 z-score，复合后向 0 收缩；不含沟通、指挥、视野等不可观测因素。',
        'metrics': {'players': len(players.get('players') or []),
                    'coverage': (players.get('lineup') or {}).get('baselineCoverage')},
        'reliable': bool((players.get('lineup') or {}).get('baselineCoverage')),
    })
    methods.append({
        'id': 'knn',
        'name': '历史相似局 / 相似大场',
        'detail': f'对每局取经济阶段、团战胜率、10 分钟资源、时长的 z-score 特征，找 {KNN_K} 个'
                  '欧氏距离最近的历史局；相似大场用余弦相似度。目标系列赛对局已排除。只做历史对照。',
        'metrics': {'corpusGames': len(matrix['rows']) if matrix else 0,
                    'historySeries': history_count, 'k': KNN_K},
        'reliable': bool(matrix and len(matrix['rows']) >= 50),
    })
    return methods


def _caveats(rows, analysis, wp_model, corpus, history_count, quality=None):
    quality = quality or {}
    caveats = list((analysis or {}).get('caveats') or [])
    if quality.get('duplicates'):
        caveats.append(f'本场检测到 {len(quality["duplicates"])} 组过程指纹完全相同的对局：'
                       '跨局汇总会重复计算这些局，先核实编组/采集。')
    if quality.get('draftInvalid') or quality.get('sameRoster'):
        bad = quality.get('draftInvalid') or quality.get('sameRoster') or []
        caveats.append(f'本场有 {len(bad)} 局 BP 名单缺失或双方阵容相同：这些局不进入 BP 价值汇总。')
    corpus_quality = quality.get('corpus') or {}
    if corpus_quality.get('duplicateKeys'):
        caveats.append(f'历史语料（排除本场后）原始 {corpus_quality.get("raw")} 局，按过程指纹去重后 '
                       f'{corpus_quality.get("unique")} 局（{corpus_quality.get("duplicateGroups")} 组重复，'
                       f'剔除 {corpus_quality.get("duplicateKeys")} 局）；模型与基线均使用去重后的语料。')
    if len(rows) < 3:
        caveats.append(f'本场只有 {len(rows)} 局：系列级比例只作记录，不做趋势结论。')
    caveats.append('大场内部的小局不是独立实验；所有「同向/相关」表述都是描述性关联，不是因果。')
    if corpus is not None and len(corpus) < 100:
        caveats.append(f'历史语料只有 {len(corpus)} 局：模型与基线只作参考，跨版本比较要谨慎。')
    if wp_model and not wp_model.get('reliable'):
        caveats.append('经济差→胜率模型区分度不足（AUC<0.6 或样本不足）：曲线仅作形状参考，不用于下结论。')
    if not history_count:
        caveats.append('没有可用的历史大场：相似大场检索不展示，相似局仍按单局语料对照。')
    caveats.append('BP 价值与英雄池来自历史统计，版本、对手与阵容都会改变选人价值；不能替代教练判断。')
    seen, unique = set(), []
    for item in caveats:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def build_insight(series, games, analysis, *, corpus=None, series_briefs=None):
    """构建单场大场的挖掘层。

    series: 已 enrich 的系列赛简介
    games: [{matchKey, gameIndex, vector, detail}]（detail 可为 None）
    analysis: series_engine.analyze_series 的输出
    corpus: 全量单局向量（最好含经济曲线/团战/十人面板）；缺失时降级
    series_briefs: 全量系列赛简介（用于相似大场；可缺）
    """
    series = series or {}
    raw_corpus = [vector for vector in (corpus or [])
                  if isinstance(vector, dict) and vector.get('key')]
    rows = _build_rows(analysis, games)
    target_keys = {str(row.get('matchKey')) for row in rows}
    series_date = str(series.get('startAt') or (rows[0].get('date') if rows else '') or '')[:10]
    corpus_index = {str(vector.get('key')): vector for vector in raw_corpus}
    # 目标系列赛先排除，再按过程指纹去重：避免同一局既进训练集又把重复局算两次。
    corpus_stats = _dedupe_corpus([vector for vector in raw_corpus
                                   if str(vector.get('key')) not in target_keys])
    # 目标局如果在语料里还有一份「同过程指纹」的重复采集（不同 matchKey），
    # 它会在相似局/相似阵容里排第一，等于拿这一局自己当历史对照。
    target_fingerprints = {_fingerprint(row.get('vector') or {}) for row in rows}
    target_fingerprints.discard(None)
    corpus = [vector for vector in corpus_stats['vectors']
              if _fingerprint(vector) not in target_fingerprints]
    quality = _target_quality(rows, corpus_stats)
    history = _build_history(series, series_briefs or [], corpus_index)
    hero_stats = _hero_stats(corpus, target_keys)
    wp_model = _fit_wp_model(corpus, target_keys)
    clusters = _shape_clusters(corpus)
    matrix = _feature_matrix(corpus, target_keys)
    flow = _flow_block(rows, wp_model, corpus)
    phase = _phase_block(rows, clusters)
    draft = _draft_block(rows, hero_stats, analysis)
    players = _player_block(rows, corpus, target_keys, series_date)
    fight = _fight_block(rows, corpus)
    similar = _similarity_block(rows, corpus, history, matrix)
    bp_plan = _bp_plan_block(rows, hero_stats, corpus, series.get('opponent'))
    bp_similar = _bp_similar_block(rows, corpus, target_keys, series_date)
    bo_bp = _bo_profile_block(rows, series, series_briefs or [], corpus_index, hero_stats)
    kpl_hit = _kpl_hit_block(bp_plan, series)
    baseline = _baseline_block(series, rows, series_briefs or [], corpus_index, hero_stats)
    for row in rows:
        row['metrics'] = _metric_game(row.get('vector') or {}, hero_stats)
    overview = _overview_block(rows, baseline)
    comp_system = _comp_system_block(rows, corpus, series.get('opponent'))
    comp_intel = _comp_block(rows, hero_stats)
    evolution = _evolution_block(rows, hero_stats, _own_pick_history(corpus), corpus)
    insights = _build_insights(rows, flow, phase, draft, {'players': []}, fight, similar, analysis, quality)
    sample = {
        'games': len(rows),
        'corpusGames': len(corpus),
        'corpusRawGames': len(raw_corpus),
        'corpusDuplicateGroups': corpus_stats.get('duplicateGroups'),
        'corpusDuplicateKeys': corpus_stats.get('duplicateKeys'),
        'corpusSeries': len(history),
        'targetGamesWithResult': sum(1 for row in rows if row.get('result') in ('win', 'loss')),
        'at10Games': sum(1 for row in rows if _num(row.get('at10')) is not None),
        'fightGames': sum(1 for row in rows if _num(row.get('fightRate')) is not None),
        'eventGames': sum(1 for row in rows if row.get('eventsKnown')),
        'playerGames': sum(1 for row in rows if row.get('vector', {}).get('pl')),
        'orderKnownGames': sum(1 for row in rows if row.get('orderKnown')),
    }
    return {
        'version': 'series-insight-v1',
        'available': bool(rows),
        'headline': _headline(rows, insights),
        'summary': {
            'score': {'us': sum(1 for row in rows if row.get('result') == 'win'),
                      'them': sum(1 for row in rows if row.get('result') == 'loss')},
            'winAt10Median': _r(_median([row.get('at10') for row in rows
                                         if row.get('result') == 'win' and _num(row.get('at10')) is not None]), 1),
            'lossAt10Median': _r(_median([row.get('at10') for row in rows
                                          if row.get('result') == 'loss' and _num(row.get('at10')) is not None]), 1),
            'winFightRate': _r(_mean([row.get('fightRate') for row in rows
                                      if row.get('result') == 'win' and _num(row.get('fightRate')) is not None]), 1),
            'lossFightRate': _r(_mean([row.get('fightRate') for row in rows
                                       if row.get('result') == 'loss' and _num(row.get('fightRate')) is not None]), 1),
            'winDraftEdge': (draft.get('series') or {}).get('winEdge'),
            'lossDraftEdge': (draft.get('series') or {}).get('lossEdge'),
        },
        'sample': sample,
        'insights': insights,
        'flow': flow,
        'phase': phase,
        'draft': draft,
        'bpPlan': bp_plan,
        'bpSimilar': bp_similar,
        'boBp': bo_bp,
        'kplHit': kpl_hit,
        'baseline': baseline,
        'overview': overview,
        'compSystem': comp_system,
        'comp': comp_intel,
        'evolution': evolution,
        'players': players,
        'fight': fight,
        'similar': similar,
        'quality': quality,
        'methods': _methods(wp_model, clusters, hero_stats, matrix, players, len(history)),
        'caveats': _caveats(rows, analysis, wp_model, corpus, len(history), quality),
    }
