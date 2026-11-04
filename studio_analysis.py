"""Local statistical workbench. Source records are never mutated."""
import hashlib
import itertools
import json
import math
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

from analysis_data import AnalysisRepository


class StudioRepository(AnalysisRepository):
    """Keep observational POV and kill scores separate from team identity/results."""

    def _load_bundles(self, warnings):
        bundles = super()._load_bundles(warnings)
        raw = {}
        for path in sorted(self.matches_dir.glob('*.json')):
            try:
                body = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            if body.get('schema') == 'kpl-match-data-v1':
                match = body.get('match') or {}
                raw[match.get('key') or path.stem] = match
        for bundle in bundles:
            match = raw.get(bundle['key'], {})
            # Following a player in a video does not establish our team's camp.
            bundle['ownCamp'] = match.get('ownCamp') if match.get('ownCamp') in ('blue', 'red') else None
            bundle['ownSide'] = bundle['ownCamp']
            winner = match.get('winnerCamp') or match.get('winner')
            bundle['winner'] = winner if winner in ('blue', 'red') else None
            for field in ('opponent', 'session', 'version'):
                bundle[field] = match.get(field)
        return bundles

    def _load(self):
        data = super()._load()
        by_key = {m['key']: m for m in data['matches']}
        for row in data['rows']:
            match = by_key[row['matchKey']]
            winner = match.get('winnerCamp') or match.get('winner')
            row['result'] = ('win' if row.get('camp') == winner else 'loss') if winner else 'unknown'
        return data

    def _selected_rows(self, filters):
        rows, warnings = super()._selected_rows(filters)
        if filters.get('from') or filters.get('to'):
            rows = [r for r in rows if r.get('dateFull') and r.get('dateKey')]
        return rows, warnings

    def _db_match(self, body, roster):
        match = super()._db_match(body, roster)
        for player, original in zip(match['players'], body.get('players', [])):
            for key in METRICS:
                if key not in player:
                    field = original.get(key, (original.get('fields') or {}).get(key))
                    player[key] = finite(field.get('value') if isinstance(field, dict) else field)
        return match

    def _sheet_matches_for(self, import_id, sheet, rows, entry, warnings):
        matches = super()._sheet_matches_for(import_id, sheet, rows, entry, warnings)
        grouped = defaultdict(list)
        for row in rows:
            keys = row.get('keys') or {}
            key = keys.get('matchId') or keys.get('matchNo') or keys.get('date') or (row.get('dimensions') or {}).get('date')
            grouped[f'sheet-{import_id[:8]}-{sheet.get("name")}-{key}'].append(row)
        for match in matches:
            for player, original in zip(match['players'], grouped[match['key']]):
                for key in METRICS:
                    if key not in player:
                        field = (original.get('metrics') or {}).get(key)
                        player[key] = finite(field.get('value') if isinstance(field, dict) else field)
        return matches

    def _flat_rows(self, matches, warnings):
        rows = super()._flat_rows(matches, warnings)
        players = [player for match in matches for player in match['players']]
        for row, player in zip(rows, players):
            for key in METRICS:
                if key not in row:
                    row[key] = finite(player.get(key))
        return rows

    def matches(self, filters):
        result = super().matches(filters)
        matches = {m['key']: m for m in self.get()['matches'] + self.get()['sheetMatches']}
        for row in result['matches']:
            match = matches[row['key']]
            winner, own = match.get('winnerCamp') or match.get('winner'), match.get('ownCamp')
            if match.get('source') != 'sheet':
                row['result'] = ('win' if winner == own else 'loss') if winner and own else 'unknown'
            row['complete'] = bool(match['players']) and all(not p.get('partial') and all(p.get(k) is not None for k in ('kills', 'deaths', 'assists', 'gold', 'damage', 'taken')) for p in match['players'])
        return result

    def match_detail(self, key):
        result = super().match_detail(key)
        if result and result.get('source') != 'sheet':
            winner, own = result.get('winnerCamp') or result.get('winner'), result.get('ownCamp')
            result['result'] = ('win' if winner == own else 'loss') if winner and own else 'unknown'
        return result

METRICS = {
    'kills': ('击杀', '次'), 'deaths': ('死亡', '次'), 'assists': ('助攻', '次'),
    'kda': ('KDA', '比值'), 'gold': ('总经济', '金币'), 'damage': ('输出伤害', '伤害'),
    'taken': ('承受伤害', '伤害'), 'participation': ('参团率', '%'), 'rating': ('赛后评分', '分'),
    'gpm': ('分均经济', '金币/分钟'), 'dpm': ('分均输出', '伤害/分钟'),
    'tpm': ('分均承伤', '伤害/分钟'), 'goldShare': ('经济占比', '%'),
    'damageShare': ('输出占比', '%'), 'takenShare': ('承伤占比', '%'),
    'cs': ('补刀', '次'), 'jungleGold': ('野怪经济', '金币'), 'control': ('控制效果', '原始值'),
    'healing': ('治疗量', '治疗'), 'towerDamage': ('对塔伤害', '伤害'),
    'damageConversion': ('伤害转化比', '比值'), 'takenPerDeath': ('每死承伤', '伤害'),
}
DIMENSIONS = {'label': '选手', 'hero': '英雄', 'position': '分路', 'opponent': '对手',
              'version': '版本', 'camp': '阵营', 'result': '胜负', 'date': '日期', 'source': '来源'}
METHODS = [
    ('describe', '分布与分组统计', '看均值、中位数、波动和分位数，比较选手与英雄。', '统计'),
    ('correlation', '指标相关性', '区分随经济一起增长的指标与相对独立的表现。', '统计'),
    ('compare', '两组差异', '按比赛聚合后做置换检验，报告差值和效应量。', '统计'),
    ('trend', '表现趋势', '逐局追踪指标，检查滚动均值和近期变化。', '统计'),
    ('anomaly', '异常场次', '用中位数绝对偏差找需要回看的比赛。', '挖掘'),
    ('cluster', '表现风格聚类', '按多项指标将选手单局表现分组，查看各组特征。', '挖掘'),
    ('pca', '表现维度分析', '用主成分分析观察指标结构，保留载荷与解释方差。', '挖掘'),
    ('association', '阵容搭配规则', '查找同队英雄组合的支持度、置信度和提升度。', '挖掘'),
    ('regression', '指标解释模型', '用岭回归解释指标间关系，并在后续比赛上检验。', '建模'),
    ('prediction', '赛前阵容模型', '只用双方已选英雄建模，按时间留出比赛验证。', '建模'),
]


def finite(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def rounded(value):
    return round(float(value), 5) if value is not None and math.isfinite(float(value)) else None


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def extract_rows(repository, filters):
    """Enrich normalized records with optional fields retained in source bundles."""
    selected, warnings = repository._selected_rows(filters)
    rows = [dict(row) for row in selected]
    bundle_fields = {}
    for path in sorted(repository.matches_dir.glob('*.json')):
        try:
            body = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if body.get('schema') != 'kpl-match-data-v1':
            continue
        key = (body.get('match') or {}).get('key') or path.stem
        for player in body.get('players', []):
            final = player.get('final') or {}
            label = player.get('nickname') or player.get('hero') or player.get('key')
            bundle_fields[(key, player.get('camp'), label)] = final
    for row in rows:
        extra = bundle_fields.get((row['matchKey'], row.get('camp'), row.get('label')), {})
        for key in METRICS:
            if row.get(key) is None and key not in ('gpm', 'dpm', 'tpm'):
                field = extra.get(key)
                row[key] = finite(field.get('value') if isinstance(field, dict) else field)
        if row.get('damageConversion') is None and row.get('gold') and row.get('damage') is not None:
            row['damageConversion'] = row['damage'] / row['gold']
            row.setdefault('derivedFields', []).append('damageConversion')
        if row.get('takenPerDeath') is None and row.get('deaths') and row.get('taken') is not None:
            row['takenPerDeath'] = row['taken'] / row['deaths']
            row.setdefault('derivedFields', []).append('takenPerDeath')
    return rows, warnings


def screenshot_rows(db_path):
    """Explicit exploratory dataset, isolated from confirmed records and models."""
    import sqlite3
    from postgame_ocr import merge_pages
    pages = []
    with sqlite3.connect(Path(db_path).as_uri() + '?mode=ro', uri=True) as connection:
        for image_id, result in connection.execute('SELECT id,result FROM postgame_images'):
            page = json.loads(result)
            page['imageId'] = image_id
            pages.append(page)
    rows = []
    aliases = {'damageDealt': 'damage', 'damageTaken': 'taken', 'outputShare': 'damageShare'}
    for group in merge_pages(pages) if pages else []:
        images = sorted(str(page.get('imageId')) for page in group.get('pages', []))
        key = 'capture-' + fingerprint(images)[:16]
        match = group.get('match') or {}
        for player in group.get('players', []):
            label = player.get('nickname')
            if isinstance(label, dict):
                label = label.get('value')
            hero = player.get('hero')
            if isinstance(hero, dict):
                hero = hero.get('value')
            row = {k: None for k in METRICS}
            for name, field in {**(player.get('fields') or {}), **(player.get('shares') or {})}.items():
                name = aliases.get(name, name)
                if name in METRICS:
                    row[name] = finite(field.get('value') if isinstance(field, dict) else field)
            rating = player.get('rating')
            row['rating'] = finite(rating.get('value') if isinstance(rating, dict) else rating)
            if all(row[x] is not None for x in ('kills', 'deaths', 'assists')):
                row['kda'] = (row['kills'] + row['assists']) / max(1, row['deaths'])
            duration = finite(match.get('durationSec'))
            if duration and duration > 0:
                for key_metric, total in [('gpm', 'gold'), ('dpm', 'damage'), ('tpm', 'taken')]:
                    if row[total] is not None:
                        row[key_metric] = row[total] / (duration / 60)
            row.update(matchKey=key, label=label or '未识别昵称', playerKey=label or key,
                       hero=hero or '', camp=player.get('side'), date=match.get('date'),
                       source='capture', opponent='', position='', version='', result='unknown',
                       partial=True, full=False, bound=False, isOwn=False, evidence=images)
            rows.append(row)
    return rows


def deduplicate(rows):
    """Collapse matches whose full ten-player content is identical.

    The signature is a frozenset of primitive tuples. It is equivalent to
    canonical JSON for equality, but avoids serializing and sorting every row
    on large imports (10k matches ~= 100k rows).
    """
    matches = defaultdict(list)
    for row in rows:
        matches[row['matchKey']].append(row)
    seen, removed = {}, []
    for key, group in matches.items():
        signature = frozenset((r.get('camp'), r.get('hero'), r.get('label'), r.get('date'),
                               r.get('duration'), *(r.get(metric) for metric in METRICS))
                              for r in group)
        if signature in seen:
            removed.append({'excluded': key, 'retained': seen[signature]})
        else:
            seen[signature] = key
    excluded = {item['excluded'] for item in removed}
    return [row for row in rows if row['matchKey'] not in excluded], removed


def summarize(values):
    a = np.array(values, dtype=float)
    if not len(a):
        return {'n': 0}
    return {'n': len(a), 'mean': rounded(a.mean()), 'median': rounded(np.median(a)),
            'std': rounded(a.std(ddof=1)) if len(a) > 1 else None,
            'min': rounded(a.min()), 'q25': rounded(np.quantile(a, .25)),
            'q75': rounded(np.quantile(a, .75)), 'max': rounded(a.max())}


def blocked(reason, required, available):
    return {'status': 'insufficient', 'reason': reason, 'required': required, 'available': available,
            'columns': [], 'rows': []}


def rank(a):
    """Average ranks for ties (Spearman)."""
    order = np.argsort(a, kind='stable')
    result = np.empty(len(a), dtype=float)
    start = 0
    while start < len(a):
        end = start + 1
        while end < len(a) and a[order[end]] == a[order[start]]:
            end += 1
        result[order[start:end]] = (start + end - 1) / 2
        start = end
    return result


def run_analysis(all_rows, spec):
    method = spec.get('method', 'describe')
    if method not in {m[0] for m in METHODS}:
        raise ValueError('分析方法无效')
    metrics = list(dict.fromkeys(spec.get('metrics') or ['gold', 'damage', 'participation']))
    if not 1 <= len(metrics) <= 8 or any(m not in METRICS for m in metrics):
        raise ValueError('请选择 1–8 个已注册指标')
    dimension = spec.get('dimension', 'hero')
    if dimension not in DIMENSIONS:
        raise ValueError('分组字段无效')
    rows = list(all_rows)
    duplicates = []
    if spec.get('deduplicate', True):
        rows, duplicates = deduplicate(rows)
    if len(rows) > 30000:
        raise ValueError('本次最多分析 30,000 行，请缩小筛选范围')
    seed = np.random.default_rng(42)
    meta = {'engineVersion': 'studio-1', 'method': method, 'metrics': metrics, 'dimension': dimension, 'inputRows': len(all_rows),
            'rows': len(rows), 'matches': len({r['matchKey'] for r in rows}),
            'duplicates': duplicates, 'generatedAt': datetime.now(timezone.utc).isoformat(),
            'fingerprint': fingerprint(rows), 'warnings': [
                '同一局的十人记录并不相互独立；相关性和聚类用于描述，不作因果解释。',
                '内容折叠只用于本次分析；请在数据源中复核同一局关系。' if duplicates else '',
            ]}
    meta['warnings'] = [w for w in meta['warnings'] if w]
    result = _calculate(rows, spec, method, metrics, dimension, seed)
    return {'schema': 'kpl-studio-result-v1', 'meta': meta, **result}


def _calculate(rows, spec, method, metrics, dimension, rng):
    xkey = metrics[0]
    if method == 'describe':
        groups = defaultdict(list)
        for row in rows:
            groups[str(row.get(dimension) or '未填写')].append(row)
        out = []
        for group, members in groups.items():
            for metric in metrics:
                valid = [r for r in members if finite(r.get(metric)) is not None]
                if not valid:
                    continue
                out.append({'group': group, 'metric': METRICS[metric][0], 'unit': METRICS[metric][1],
                            'matches': len({r['matchKey'] for r in valid}),
                            'missing': len(members) - len(valid), **summarize([r[metric] for r in valid])})
        values = [r[xkey] for r in rows if finite(r.get(xkey)) is not None]
        distribution = []
        if values:
            counts, edges = np.histogram(values, bins=min(12, max(3, math.ceil(math.sqrt(len(values))))))
            distribution = [{'low': rounded(edges[i]), 'high': rounded(edges[i+1]), 'count': int(count)}
                            for i, count in enumerate(counts)]
        return {'status': 'ok', 'columns': ['group', 'metric', 'unit', 'n', 'matches', 'missing', 'mean', 'median', 'std', 'min', 'q25', 'q75', 'max'],
                'rows': out, 'distribution': distribution}
    if method == 'correlation':
        if len(metrics) < 2:
            raise ValueError('相关分析至少需要两个指标')
        out = []
        for a, b in itertools.combinations(metrics, 2):
            valid = [r for r in rows if finite(r.get(a)) is not None and finite(r.get(b)) is not None]
            x, y = np.array([r[a] for r in valid]), np.array([r[b] for r in valid])
            enough = len(x) >= 3 and np.std(x) > 0 and np.std(y) > 0
            out.append({'x': METRICS[a][0], 'y': METRICS[b][0], 'n': len(x),
                        'matches': len({r['matchKey'] for r in valid}),
                        'pearson': rounded(np.corrcoef(x, y)[0, 1]) if enough else None,
                        'spearman': rounded(np.corrcoef(rank(x), rank(y))[0, 1]) if enough else None,
                        'note': '描述性相关' if enough else '有效值不足或指标无变化'})
        return {'status': 'ok', 'columns': ['x', 'y', 'n', 'matches', 'pearson', 'spearman', 'note'], 'rows': out,
                'points': [{'x': r[metrics[0]], 'y': r[metrics[1]], 'label': r.get('label'), 'matchKey': r['matchKey']}
                           for r in rows if all(finite(r.get(k)) is not None for k in metrics[:2])][:1500]}
    if method == 'compare':
        a, b = str(spec.get('groupA', '')), str(spec.get('groupB', ''))
        if not a or not b or a == b:
            raise ValueError('请选择两个不同的分组')
        values = defaultdict(lambda: defaultdict(list))
        for r in rows:
            group = str(r.get(dimension) or '未填写')
            if group in (a, b) and finite(r.get(xkey)) is not None:
                values[group][r['matchKey']].append(r[xkey])
        # Use only unpaired games. Shared games must be handled as pairs.
        shared = set(values[a]) & set(values[b])
        if shared:
            differences = np.array([np.mean(values[a][k]) - np.mean(values[b][k]) for k in sorted(shared)])
            if len(differences) < 4:
                return blocked('配对检验至少需要 4 场同时含两组的比赛', 4, len(differences))
            observed = abs(differences.mean())
            permutations = (rng.choice([-1, 1], size=(2000, len(differences))) * differences).mean(axis=1)
            p = (1 + np.sum(np.abs(permutations) >= observed)) / 2001
            ci = np.quantile(rng.choice(differences, (2000, len(differences))).mean(axis=1), [.025, .975])
            out = {'comparison': f'{a} − {b}', 'design': '同局配对；每局各组取均值', 'nA': len(shared), 'nB': len(shared),
                   'difference': rounded(differences.mean()), 'ciLow': rounded(ci[0]), 'ciHigh': rounded(ci[1]),
                   'p': rounded(p), 'effect': rounded(differences.mean() / differences.std(ddof=1)) if differences.std(ddof=1) else None}
        else:
            x, y = [np.array([np.mean(v) for v in values[g].values()]) for g in (a, b)]
            if min(len(x), len(y)) < 4:
                return blocked('独立组比较每组至少需要 4 场比赛', 4, min(len(x), len(y)))
            observed, combined = abs(x.mean() - y.mean()), np.concatenate([x, y])
            exceed = 0
            for _ in range(2000):
                shuffled = rng.permutation(combined)
                exceed += abs(shuffled[:len(x)].mean() - shuffled[len(x):].mean()) >= observed
            ci = np.quantile(rng.choice(x, (2000, len(x))).mean(axis=1) - rng.choice(y, (2000, len(y))).mean(axis=1), [.025, .975])
            pooled = math.sqrt(((len(x)-1)*x.var(ddof=1)+(len(y)-1)*y.var(ddof=1))/(len(x)+len(y)-2))
            out = {'comparison': f'{a} − {b}', 'design': '不同比赛；每局各组取均值', 'nA': len(x), 'nB': len(y),
                   'difference': rounded(x.mean()-y.mean()), 'ciLow': rounded(ci[0]), 'ciHigh': rounded(ci[1]),
                   'p': rounded((exceed+1)/2001), 'effect': rounded((x.mean()-y.mean())/pooled) if pooled else None}
        return {'status': 'ok', 'columns': list(out), 'rows': [out], 'note': '95% 区间由比赛级 bootstrap 得到；2000 次置换。单次探索检验，未做多重比较校正。'}
    if method in ('trend', 'anomaly'):
        groups = defaultdict(list)
        for r in rows:
            if finite(r.get(xkey)) is not None:
                groups[(r.get('date') or '', r['matchKey'])].append(r)
        points = [{'date': k[0], 'matchKey': k[1], 'value': rounded(np.mean([r[xkey] for r in v])), 'n': len(v)}
                  for k, v in sorted(groups.items())]
        if not points:
            return blocked('当前筛选下没有该指标的有效值', 1, 0)
        v = np.array([p['value'] for p in points])
        median, mad = np.median(v), np.median(np.abs(v-np.median(v)))
        for i, p in enumerate(points):
            p['rolling'] = rounded(v[max(0, i-4):i+1].mean())
            p['deviation'] = rounded(.67449*(v[i]-median)/mad) if mad else None
            p['flag'] = '需回看' if mad and abs(p['deviation']) > 3.5 else ('尺度为零' if not mad else '范围内')
        return {'status': 'ok', 'columns': ['date', 'matchKey', 'value', 'rolling', 'n', 'deviation', 'flag'],
                'rows': points, 'note': '每局对当前选中选手取均值；滚动窗口为最近 5 局。日期缺失时仅按记录键排序，不解释时间趋势。MAD=0 时不判异常。'}
    if method in ('cluster', 'pca', 'regression'):
        valid = [r for r in rows if all(finite(r.get(k)) is not None for k in metrics)]
        minimum = max(6, len(metrics)+2)
        if len(metrics) < 2:
            raise ValueError('至少选择两个指标')
        if len(valid) < minimum:
            return blocked('完整指标向量不足，请减少指标或扩大样本范围', minimum, len(valid))
        data = np.array([[r[k] for k in metrics] for r in valid], dtype=float)
        mean, std = data.mean(axis=0), data.std(axis=0)
        if np.all(std == 0):
            return blocked('所有指标都没有变化，无法拟合', 1, 0)
        z = (data-mean)/np.where(std > 0, std, 1)
        if method == 'pca':
            _, s, vt = np.linalg.svd(z, full_matrices=False)
            total = (s*s).sum()
            loadings = [{'metric': METRICS[k][0], 'pc1': rounded(vt[0, i]), 'pc2': rounded(vt[1, i])} for i, k in enumerate(metrics)]
            coordinates = z @ vt[:2].T
            return {'status': 'ok', 'columns': ['metric', 'pc1', 'pc2'], 'rows': loadings,
                    'variance': [rounded(v*v/total*100) for v in s[:2]],
                    'points': [{'x': rounded(p[0]), 'y': rounded(p[1]), 'label': r.get('label'), 'matchKey': r['matchKey']} for p, r in zip(coordinates, valid)],
                    'note': '按选手单局标准化后做 PCA；载荷描述指标结构，不是能力权重。'}
        if method == 'cluster':
            k = int(spec.get('clusters', 3))
            if not 2 <= k <= 6:
                raise ValueError('聚类数应为 2–6')
            if len(np.unique(z, axis=0)) < k:
                return blocked('不同指标向量少于聚类数', k, len(np.unique(z, axis=0)))
            best = None
            for _ in range(8):
                centers = np.unique(z, axis=0)[rng.choice(len(np.unique(z, axis=0)), k, replace=False)]
                for _ in range(60):
                    labels = ((z[:, None, :]-centers[None, :, :])**2).sum(axis=2).argmin(axis=1)
                    next_centers = np.array([z[labels==i].mean(axis=0) if np.any(labels==i) else centers[i] for i in range(k)])
                    if np.allclose(next_centers, centers):
                        break
                    centers = next_centers
                inertia = ((z-centers[labels])**2).sum()
                if best is None or inertia < best[0]:
                    best = inertia, labels.copy(), centers.copy()
            _, labels, centers = best
            out = []
            for i in range(k):
                member = data[labels==i]
                if len(member):
                    out.append({'cluster': f'组 {i+1}', 'n': len(member), **{METRICS[m][0]: rounded(member[:, j].mean()) for j, m in enumerate(metrics)}})
            return {'status': 'ok', 'columns': list(out[0]), 'rows': out,
                    'members': [{'label': r.get('label'), 'hero': r.get('hero'), 'matchKey': r['matchKey'], 'cluster': int(c)+1} for r, c in zip(valid, labels)],
                    'note': '标准化 K-means，8 次初始化。组号没有强弱含义；分组对象是选手单局表现。'}
        # Retrospective regression: keep whole dates/matches outside training.
        return regression(valid, metrics)
    if method == 'association':
        transactions = defaultdict(set)
        for r in rows:
            if r.get('hero') and r.get('camp') not in (None, '', 'unknown'):
                transactions[(r['matchKey'], r['camp'])].add(r['hero'])
        transactions = [s for s in transactions.values() if len(s) == 5]
        if len(transactions) < 4:
            return blocked('至少需要 4 支完整的同队五英雄阵容', 4, len(transactions))
        singles, pairs = defaultdict(int), defaultdict(int)
        for t in transactions:
            for h in t:
                singles[h] += 1
            for a, b in itertools.combinations(sorted(t), 2):
                pairs[(a, b)] += 1
        out = []
        for (a, b), count in pairs.items():
            if count < 2:
                continue
            for x, y in ((a, b), (b, a)):
                out.append({'antecedent': x, 'consequent': y, 'count': count,
                            'support': rounded(count/len(transactions)), 'confidence': rounded(count/singles[x]),
                            'lift': rounded(count*len(transactions)/(singles[x]*singles[y]))})
        return {'status': 'ok', 'columns': ['antecedent', 'consequent', 'count', 'support', 'confidence', 'lift'],
                'rows': sorted(out, key=lambda x: (-x['lift'], -x['count']))[:100],
                'note': f'{len(transactions)} 支完整阵容。规则至少共现 2 次；描述搭配频率，不代表胜率提升。双方阵容来自同局，非独立样本。'}
    if method == 'prediction':
        return prediction(rows)
    raise ValueError('分析方法无效')


def temporal_split(valid):
    def valid_date(value):
        try:
            return len(str(value)) == 10 and bool(date.fromisoformat(value))
        except (TypeError, ValueError):
            return False
    dates = sorted({r.get('date') for r in valid if valid_date(r.get('date'))})
    if len(dates) < 4:
        return None
    cutoff = dates[max(1, int(len(dates)*.75))]
    train = [r for r in valid if valid_date(r.get('date')) and r['date'] < cutoff]
    test = [r for r in valid if valid_date(r.get('date')) and r['date'] >= cutoff]
    # Some imports reuse one match key across dates. Never permit overlap.
    overlap = {r['matchKey'] for r in train} & {r['matchKey'] for r in test}
    train = [r for r in train if r['matchKey'] not in overlap]
    return train, test, cutoff


def regression(valid, metrics):
    split = temporal_split(valid)
    if not split:
        return blocked('需要至少 4 个有完整日期的训练日以做时间留出验证', 4, len({r.get('date') for r in valid if r.get('date')}))
    train, test, cutoff = split
    if len({r['matchKey'] for r in train}) < 8 or len({r['matchKey'] for r in test}) < 3:
        return blocked('训练集至少 8 场、留出集至少 3 场；同一天和同一局不拆开', 11, len({r['matchKey'] for r in valid}))
    x = np.array([[r[k] for k in metrics[:-1]] for r in train])
    y = np.array([r[metrics[-1]] for r in train])
    mean, scale = x.mean(axis=0), x.std(axis=0)
    scale = np.where(scale > 0, scale, 1)
    design = np.column_stack([np.ones(len(x)), (x-mean)/scale])
    penalty = np.eye(design.shape[1]); penalty[0, 0] = 0
    weights = np.linalg.solve(design.T@design + penalty, design.T@y)
    tx = np.column_stack([np.ones(len(test)), (np.array([[r[k] for k in metrics[:-1]] for r in test])-mean)/scale])
    predicted, truth = tx@weights, np.array([r[metrics[-1]] for r in test])
    # Equal game weights in evaluation, regardless of players per game.
    errors, baseline_errors = defaultdict(list), defaultdict(list)
    for r, p, actual in zip(test, predicted, truth):
        errors[r['matchKey']].append(abs(p-actual))
        baseline_errors[r['matchKey']].append(abs(y.mean()-actual))
    result = {'target': METRICS[metrics[-1]][0], 'trainMatches': len({r['matchKey'] for r in train}),
              'testMatches': len(errors), 'cutoff': cutoff,
              'mae': rounded(np.mean([np.mean(v) for v in errors.values()])),
              'baselineMae': rounded(np.mean([np.mean(v) for v in baseline_errors.values()]))}
    return {'status': 'ok', 'columns': list(result), 'rows': [result],
            'coefficients': [{'metric': METRICS[k][0], 'weight': rounded(w)} for k, w in zip(metrics[:-1], weights[1:])],
            'note': '最后一个指标为目标；其余指标为解释变量。岭回归 α=1，标准化只拟合训练集；这是赛后解释模型，不能用于赛前预测。系数非因果贡献。'}


def prediction(rows):
    games = defaultdict(list)
    for r in rows:
        games[r['matchKey']].append(r)
    valid = []
    for key, members in games.items():
        own = [r for r in members if r.get('isOwn')]
        enemy = [r for r in members if not r.get('isOwn')]
        outcomes = {r.get('result') for r in own}
        if len(own) != 5 or len(enemy) != 5 or len(outcomes) != 1 or next(iter(outcomes), '') not in ('win', 'loss'):
            continue
        if not all(r.get('hero') for r in members):
            continue
        valid.append({'matchKey': key, 'date': own[0].get('date'), 'own': [r['hero'] for r in own],
                      'enemy': [r['hero'] for r in enemy], 'y': int(own[0]['result'] == 'win')})
    split = temporal_split(valid)
    if len(valid) < 40 or not split:
        return blocked('阵容模型需要至少 40 场完整十人、本队及胜负已确认的比赛，且覆盖至少 4 个训练日', 40, len(valid))
    train, test, cutoff = split
    if len(train) < 25 or len(test) < 10 or len({r['y'] for r in train}) < 2 or len({r['y'] for r in test}) < 2:
        return blocked('时间划分后需训练集 ≥25 场、留出集 ≥10 场，两边均含胜负', 35, len(train)+len(test))
    vocabulary = sorted({h for r in train for h in r['own']+r['enemy']})
    index = {h: i for i, h in enumerate(vocabulary)}
    def encode(records):
        a = np.zeros((len(records), len(vocabulary)+1)); a[:, 0] = 1
        for i, r in enumerate(records):
            for side, sign in [('own', 1), ('enemy', -1)]:
                for h in r[side]:
                    if h in index:
                        a[i, index[h]+1] += sign
        return a
    x, tx = encode(train), encode(test)
    y, truth = np.array([r['y'] for r in train]), np.array([r['y'] for r in test])
    weights = np.zeros(x.shape[1])
    for _ in range(700):
        p = 1/(1+np.exp(-np.clip(x@weights, -30, 30)))
        penalty = weights.copy(); penalty[0] = 0
        weights -= .15*(x.T@(p-y)/len(y)+.05*penalty)
    p = 1/(1+np.exp(-np.clip(tx@weights, -30, 30)))
    base = y.mean()
    out = {'trainMatches': len(train), 'testMatches': len(test), 'cutoff': cutoff,
           'accuracy': rounded(np.mean((p>=.5)==truth)),
           'baselineAccuracy': rounded(np.mean((base>=.5)==truth)),
           'brier': rounded(np.mean((p-truth)**2)), 'baselineBrier': rounded(np.mean((base-truth)**2))}
    return {'status': 'ok', 'columns': list(out), 'rows': [out],
            'note': 'L2 逻辑回归，只输入本队/对手英雄差分；不使用终局经济、评分或 KDA。词表仅拟合训练集。40 场只是运行门槛，不代表可靠性；留出结果供研究，不作 BP 自动推荐。'}
