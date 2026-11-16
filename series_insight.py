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

import math
import random
from collections import Counter, defaultdict

import numpy as np

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


def _player_baselines(corpus, exclude_keys):
    positions = defaultdict(lambda: defaultdict(list))
    players = defaultdict(lambda: defaultdict(list))
    for vector in corpus or []:
        if str(vector.get('key') or '') in exclude_keys:
            continue
        own_camp = vector.get('camp')
        for player in vector.get('pl') or []:
            position = str(player.get('pos') or '未知')
            metrics = _player_metrics(player)
            for key, value in metrics.items():
                if value is None:
                    continue
                positions[position][key].append(value)
                if player.get('camp') == own_camp and player.get('name'):
                    players[(str(player['name']), position)][key].append(value)
    return {'positions': positions, 'players': players}


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
    rows.sort(key=lambda row: row.get('gameIndex') or 0)
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
    }


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
            'orderKnown': bool(row.get('orderKnown')),
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


def _player_block(rows, corpus, exclude_keys):
    baselines = _player_baselines(corpus, exclude_keys)
    entries = {}
    for row in rows:
        vector = row.get('vector') or {}
        own_camp = vector.get('camp')
        players = [player for player in vector.get('pl') or [] if player.get('camp') == own_camp]
        for player in players:
            name = str(player.get('name') or '').strip()
            position = str(player.get('pos') or '未知')
            key = (name or position, position)
            entry = entries.setdefault(key, {
                'name': name or position, 'position': position, 'games': 0, 'perGame': [],
                'kills': [], 'deaths': [], 'assists': [], 'kda': [], 'gpm': [], 'dpm': [],
                'part': [], 'laneGold': [], 'laneDamage': [], 'laneTaken': [],
            })
            metrics = _player_metrics(player)
            entry['games'] += 1
            for metric in ('kda', 'gpm', 'dpm', 'part', 'deaths'):
                if metrics.get(metric) is not None:
                    entry[metric].append(metrics[metric])
            for metric, key_name in (('kills', 'k'), ('assists', 'a')):
                value = _num(player.get(key_name))
                if value is not None:
                    entry[metric].append(value)
            lane = (vector.get('lanes') or {}).get(position) or {}
            for metric, key_name in (('laneGold', 'gold'), ('laneDamage', 'damage'),
                                     ('laneTaken', 'taken')):
                value = _num(lane.get(key_name))
                if value is not None:
                    entry[metric].append(value)
            entry['perGame'].append({
                'gameIndex': row.get('gameIndex'), 'matchKey': row.get('matchKey'),
                'result': row.get('result'), **metrics,
                'laneGold': _r(lane.get('gold'), 1),
                'laneDamage': _r(lane.get('damage'), 1),
                'laneTaken': _r(lane.get('taken'), 1),
            })
    players = []
    for key, entry in entries.items():
        position = entry['position']
        player_base = baselines['players'].get(key)
        position_base = baselines['positions'].get(position)
        use_player = player_base and all(len(player_base.get(metric) or []) >= PLAYER_BASELINE_MIN
                                         for metric in ('gpm', 'dpm', 'part', 'kda'))
        use_position = position_base and all(len(position_base.get(metric) or []) >= POSITION_BASELINE_MIN
                                             for metric in ('gpm', 'dpm', 'part', 'kda'))
        base = player_base if use_player else position_base if use_position else None
        baseline_kind = 'player' if use_player else 'position' if use_position else None
        summary = {metric: _mean(entry.get(metric)) for metric in
                   ('kda', 'gpm', 'dpm', 'part', 'deaths')}
        z_values = {}
        if base:
            for metric in ('kda', 'gpm', 'dpm', 'part', 'deaths'):
                z_values[metric] = _z_score(summary.get(metric),
                                            _baseline_stats(base.get(metric)),
                                            Z_METRIC_FLOOR[metric])
        for game in entry['perGame']:
            z_game = {}
            if base:
                for metric in ('kda', 'gpm', 'dpm', 'part', 'deaths'):
                    z_game[metric] = _z_score(game.get(metric),
                                              _baseline_stats(base.get(metric)),
                                              Z_METRIC_FLOOR[metric])
            available = [z_game[metric] for metric in ('kda', 'gpm', 'dpm', 'part')
                         if z_game.get(metric) is not None]
            if z_game.get('deaths') is not None:
                available.append(-z_game['deaths'])
            game['composite'] = _r(_mean(available), 2) if available else None
        composites = [game['composite'] for game in entry['perGame']
                      if _num(game.get('composite')) is not None]
        series_composite = _mean(composites)
        shrink = len(composites) / (len(composites) + 2) if composites else 0
        series_composite = round(series_composite * shrink, 2) if series_composite is not None else None
        win_composites = [game['composite'] for game in entry['perGame']
                          if game.get('result') == 'win' and _num(game.get('composite')) is not None]
        loss_composites = [game['composite'] for game in entry['perGame']
                           if game.get('result') == 'loss' and _num(game.get('composite')) is not None]
        trend = _slope([(game.get('gameIndex'), game.get('composite'))
                        for game in entry['perGame'] if _num(game.get('composite')) is not None])
        players.append({
            'name': entry['name'], 'position': position, 'games': entry['games'],
            'kda': _r(summary.get('kda'), 2), 'gpm': _r(summary.get('gpm'), 1),
            'dpm': _r(summary.get('dpm'), 1), 'part': _r(summary.get('part'), 1),
            'deaths': _r(summary.get('deaths'), 2),
            'laneGold': _r(_mean(entry.get('laneGold')), 1),
            'laneDamage': _r(_mean(entry.get('laneDamage')), 1),
            'laneTaken': _r(_mean(entry.get('laneTaken')), 1),
            'composite': series_composite,
            'z': {key: _r(value, 2) for key, value in z_values.items()},
            'baseline': baseline_kind,
            'baselineGames': (len(player_base.get('gpm') or []) if use_player
                              else len(position_base.get('gpm') or []) if use_position else 0),
            'trend': _r(trend, 2),
            'consistency': _r(_std(composites), 2),
            'winComposite': _r(_mean(win_composites), 2) if win_composites else None,
            'lossComposite': _r(_mean(loss_composites), 2) if loss_composites else None,
            'form': 'hot' if series_composite is not None and series_composite >= 0.8
                    else 'cold' if series_composite is not None and series_composite <= -0.8
                    else 'stable' if series_composite is not None else 'unknown',
            'perGame': entry['perGame'],
        })
    players.sort(key=lambda player: (-(player.get('composite') if player.get('composite') is not None
                                      else -99), player.get('position') or '', player.get('name') or ''))
    names = [player['name'] for player in players]
    covered = [player for player in players if player.get('baseline')]
    return {
        'players': players,
        'lineup': {
            'unique': len(names),
            'stable': len(names) <= 5 and all(player['games'] == len(rows) for player in players),
            'substitutions': [{'name': player['name'], 'games': player['games']}
                              for player in players if player['games'] < len(rows)],
            'baselineCoverage': len(covered),
            'teamComposite': _r(_mean([player['composite'] for player in players
                                       if _num(player.get('composite')) is not None]), 2),
        },
    }


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
    caveats.append('选手状态分只覆盖面板数据；不包含沟通、指挥、视野与训练量等不可观测因素。')
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
    corpus_index = {str(vector.get('key')): vector for vector in raw_corpus}
    # 目标系列赛先排除，再按过程指纹去重：避免同一局既进训练集又把重复局算两次。
    corpus_stats = _dedupe_corpus([vector for vector in raw_corpus
                                   if str(vector.get('key')) not in target_keys])
    corpus = corpus_stats['vectors']
    quality = _target_quality(rows, corpus_stats)
    history = _build_history(series, series_briefs or [], corpus_index)
    hero_stats = _hero_stats(corpus, target_keys)
    wp_model = _fit_wp_model(corpus, target_keys)
    clusters = _shape_clusters(corpus)
    matrix = _feature_matrix(corpus, target_keys)
    flow = _flow_block(rows, wp_model, corpus)
    phase = _phase_block(rows, clusters)
    draft = _draft_block(rows, hero_stats, analysis)
    players = _player_block(rows, corpus, target_keys)
    fight = _fight_block(rows, corpus)
    similar = _similarity_block(rows, corpus, history, matrix)
    insights = _build_insights(rows, flow, phase, draft, players, fight, similar, analysis, quality)
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
        'players': players,
        'fight': fight,
        'similar': similar,
        'quality': quality,
        'methods': _methods(wp_model, clusters, hero_stats, matrix, players, len(history)),
        'caveats': _caveats(rows, analysis, wp_model, corpus, len(history), quality),
    }
