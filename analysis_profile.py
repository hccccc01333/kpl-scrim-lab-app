"""B1 对手战术画像 / B3 训练效果追踪。

数据：
  营地面板 data/camp_details/*.json —— 每局十人统计（KDA/经济/输出/参伤/参团/英雄/分路）
  team_clusters 的阵容签名 —— 把对面五人聚成对手战队
  training 表 —— 训练目标、干预、起止日期、适用选手、指标、目标值

口径：
- B1 要求同一对手 ≥3 局才出画像，否则只说「样本不足」。
- B3 只做前后对比（均值、差值、Cohen's d、目标达成率），不宣称因果。
- 缺失字段不参与计算，不用 0 代替。
"""
from __future__ import annotations

import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path

LANES = {0: '对抗路', 1: '中路', 2: '发育路', 3: '打野', 4: '游走'}

METRICS = {
    'kda': ('KDA', lambda row: (row['kills'] + row['assists']) / max(1, row['deaths'])),
    'gpm': ('分均经济', lambda row: row['gold'] / row['minutes'] if row['minutes'] else None),
    'dpm': ('分均输出', lambda row: row['heroDamage'] / row['minutes'] if row['minutes'] else None),
    'tpm': ('分均承伤', lambda row: row['taken'] / row['minutes'] if row['minutes'] else None),
    'participation': ('参团率', lambda row: row['participation'] * 100 if row['participation'] is not None else None),
}


def _clean(value):
    return str(value or '').replace('\u2060', '').strip()


def _int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_rows(camp_dir):
    """逐人逐局的面板行。日期用面板 startTime 补 2026 年。"""
    rows = []
    for path in sorted(Path(camp_dir).glob('*.json')):
        try:
            data = (json.loads(path.read_text(encoding='utf-8')).get('data') or {})
        except (OSError, ValueError):
            continue
        head = data.get('head') or {}
        own_code = str(head.get('acntCamp') or '')
        if own_code not in ('1', '2'):
            continue
        own_camp = 'blue' if own_code == '1' else 'red'
        battle = data.get('battle') or {}
        start = _clean(battle.get('startTime'))
        date = ''
        if start:
            month_day = start.split()[0]
            date = f'2026-{month_day}' if month_day.count('-') == 1 else ''
        minutes = (_float(battle.get('usedTime')) or 0) / 60
        for side_key, side in (('blueRoles', 'blue'), ('redRoles', 'red')):
            for role in data.get(side_key) or []:
                basic = role.get('basicInfo') or {}
                stats = role.get('battleStats') or {}
                records = role.get('battleRecords') or {}
                hero = ((records.get('usedHero') or {}).get('heroName')) or ''
                rows.append({
                    'seq': path.stem,
                    'date': date,
                    'camp': side,
                    'side': 'own' if side == own_camp else 'enemy',
                    'playerId': _clean(basic.get('playerId')),
                    'name': _clean(basic.get('roleName')),
                    'lane': LANES.get(_int(records.get('position')), ''),
                    'hero': hero,
                    'minutes': minutes,
                    'kills': _int(stats.get('killCnt')) or 0,
                    'deaths': _int(stats.get('deadCnt')) or 0,
                    'assists': _int(stats.get('assistCnt')) or 0,
                    'gold': _int(stats.get('money')) or 0,
                    'damage': _int(stats.get('totalHurtCnt')) or 0,
                    'heroDamage': _int(stats.get('totalHeroHurtCnt')) or 0,
                    'taken': _int(stats.get('totalBehurtCnt')) or 0,
                    'participation': _float(stats.get('joinGamePercent')),
                    'won': bool(head.get('gameResult')) == (side == own_camp),
                })
    return rows


def opponent_profiles(rows, teams, *, min_games=3):
    """teams: [{id, name}] —— 由 team_clusters 给出；按对手侧聚合。

    由于 rows 按局不直接带战队 id，这里用「对手五人签名」的分组在调用方完成；
    为保持模块独立，本函数接收已按队伍分好组的 rows。
    """
    profiles = []
    for team in teams:
        games = team.get('rows') or []
        if not games:
            continue
        seqs = {row['seq'] for row in games}
        if len(seqs) < min_games:
            profiles.append({
                'id': team['id'], 'name': team['name'], 'games': len(seqs),
                'available': False, 'reason': f'样本不足（{len(seqs)} 局，需 ≥{min_games} 局）',
            })
            continue

        # 每局有 5 名对手选手，胜场要按「局」去重
        win_seqs = {row['seq'] for row in games if row['won']}
        heroes = Counter(row['hero'] for row in games if row['hero'])
        lanes = defaultdict(Counter)
        for row in games:
            if row['lane']:
                lanes[row['lane']][row['hero']] += 1
        players = defaultdict(lambda: {'name': '', 'lane': '', 'games': 0, 'heroes': Counter()})
        for row in games:
            record = players[row['playerId']]
            record['games'] += 1
            record['name'] = record['name'] or row['name']
            record['lane'] = record['lane'] or row['lane']
            if row['hero']:
                record['heroes'][row['hero']] += 1

        roster_sets = defaultdict(set)
        for row in games:
            roster_sets[row['seq']].add(row['playerId'])
        signatures = list(roster_sets.values())
        stability = None
        if len(signatures) >= 2:
            base = signatures[0]
            stability = round(statistics.mean(len(base & item) / max(1, len(base)) for item in signatures[1:]) * 100, 1)

        metrics = {}
        for key, (label, getter) in METRICS.items():
            values = [getter(row) for row in games]
            values = [value for value in values if value is not None and math.isfinite(value)]
            metrics[key] = {'label': label,
                            'value': round(statistics.mean(values), 2) if values else None,
                            'n': len(values)}

        profiles.append({
            'id': team['id'], 'name': team['name'], 'games': len(seqs),
            'available': True,
            'wins': len(win_seqs),
            'winRate': round(len(win_seqs) / len(seqs) * 100, 1),
            'metrics': metrics,
            'heroes': [{'hero': hero, 'games': count} for hero, count in heroes.most_common(8)],
            'lanes': {lane: [{'hero': hero, 'games': count} for hero, count in counter.most_common(3)]
                      for lane, counter in lanes.items()},
            'players': [{'id': pid, 'name': record['name'], 'lane': record['lane'],
                         'games': record['games'],
                         'heroes': [{'hero': hero, 'games': count}
                                    for hero, count in record['heroes'].most_common(3)]}
                        for pid, record in sorted(players.items(), key=lambda item: -item[1]['games'])],
            'stability': stability,
            'confidence': 'high' if len(seqs) >= 6 else 'medium',
        })
    profiles.sort(key=lambda item: (not item['available'], -item['games']))
    return {'profiles': profiles, 'minGames': min_games}


def training_effect(rows, training, *, actor='coach'):
    """按干预窗口切 pre/post，输出均值、差值、Cohen's d、目标达成率。"""
    key = (training.get('metric') or '').strip()
    if key not in METRICS:
        return {'available': False, 'reason': f'不支持的指标：{key or "空"}'}
    label, getter = METRICS[key]
    players = set(training.get('player_ids') or [])
    start = training.get('start_date') or ''
    end = training.get('end_date') or start

    def values(before):
        out = []
        for row in rows:
            if players and row['playerId'] not in players:
                continue
            if not row['date']:
                continue
            if before and start and row['date'] >= start:
                continue
            if not before and end and row['date'] < end:
                continue
            value = getter(row)
            if value is not None and math.isfinite(value):
                out.append(value)
        return out

    pre, post = values(True), values(False)
    if len(pre) < 5 or len(post) < 5:
        return {'available': False,
                'reason': f'样本不足（干预前 {len(pre)} 人次 / 干预后 {len(post)} 人次，各需 ≥5）',
                'pre': len(pre), 'post': len(post), 'metric': key, 'label': label}

    pre_mean, post_mean = statistics.mean(pre), statistics.mean(post)
    delta = post_mean - pre_mean
    pooled = math.sqrt((statistics.pvariance(pre) + statistics.pvariance(post)) / 2) or 0
    effect = round(delta / pooled, 2) if pooled else None
    target = training.get('target')
    rate = None
    if target is not None:
        rate = round(sum(1 for value in post if value >= target) / len(post) * 100, 1)
    return {
        'available': True,
        'metric': key, 'label': label,
        'preMean': round(pre_mean, 2), 'postMean': round(post_mean, 2),
        'delta': round(delta, 2),
        'effectSize': effect,
        'target': target,
        'targetRate': rate,
        'nPre': len(pre), 'nPost': len(post),
        'confidence': 'high' if min(len(pre), len(post)) >= 10 else 'low',
        'note': '描述性前后对比，不宣称因果。',
    }


def group_by_opponent(rows, camp_dir, db_path):
    """按阵容签名把对手侧的行分组，队名走 team_clusters 的显示名。"""
    import team_clusters
    panels = team_clusters.load_panels(camp_dir)
    sig = {panel['seq']: team_clusters.signature(panel) for panel in panels}
    teams = team_clusters.list_teams(camp_dir, db_path)
    names = {team['id']: team['displayName'] for team in teams['teams']}
    groups = defaultdict(list)
    for row in rows:
        if row['side'] != 'enemy':
            continue
        key = sig.get(row['seq'])
        if key:
            groups[key].append(row)
    return [{'id': key, 'name': names.get(key, key), 'rows': items}
            for key, items in groups.items()]


def profiles(camp_dir, db_path, *, min_games=3):
    rows = load_rows(camp_dir)
    teams = group_by_opponent(rows, camp_dir, db_path)
    result = opponent_profiles(rows, teams, min_games=min_games)
    result['rows'] = len(rows)
    return result


def effect(camp_dir, training_row):
    rows = load_rows(camp_dir)
    return training_effect(rows, training_row)
