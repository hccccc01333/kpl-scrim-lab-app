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



# ===========================================================================
# Merged from merged module (resource_allocation)
# ===========================================================================

"""赛训决策台 · P0-4 资源分配与发育效率（A 级：终局面板）。

教练视角回答「经济给对位置了吗」：

- 逐局按阵营合计 5 人 gold/heroDamage/towerDamage/control/heal/jungleGold，
  再算每人占比（0–100，1 位小数）；
- 经济占比 × 英雄伤害占比 四象限，标出「吃钱多、打伤害少」的待复核配置；
- 分路均值与「经济→输出」转化，用来看分路职责差异，不跨分路排名；
- 游走/辅助不套用「高经济低输出」规则，页面提示改看控制/治疗。

数据口径（README.md 2.5）：

- gold = battleStats.money，heroDamage = battleStats.totalHeroHurtCnt，
  towerDamage = battleStats.buildingDamage，control = battleStats.ctrlTime，
  heal = battleStats.healCnt，jungleGold = battleStats.monsterCoin。
- ``damage``（totalHurtCnt 总伤害）与 ``heroDamage``（totalHeroHurtCnt 英雄伤害）
  属不同口径，分开保留，不混用；坦克/辅助的价值不只在输出。
- 缺失字段返回 None，不假填 0；团队合计为 0 或缺失时占比返回 None。
- 过滤后无面板行 / 面板缺少金币字段：available=false + reason，不画空图。

只读 ``match_facts.load_facts(...)['rows']``（逐人逐局 PanelRow，own + enemy），
不扫盘、不新增依赖。
"""

import math
from collections import defaultdict

from match_facts import mean, median

# ---------------------------------------------------------------------------
# 口径常量
# ---------------------------------------------------------------------------
GOLD_BASIS = 'battleStats.money'
DAMAGE_BASIS = 'battleStats.totalHeroHurtCnt'
TOWER_BASIS = 'battleStats.buildingDamage'
CONTROL_BASIS = 'battleStats.ctrlTime'
HEAL_BASIS = 'battleStats.healCnt'
JUNGLE_BASIS = 'battleStats.monsterCoin'

SIDES = ('own', 'enemy')
TOTAL_KEYS = ('gold', 'heroDamage', 'towerDamage', 'control', 'heal', 'jungleGold')
VALUE_TO_SHARE = {
    'gold': 'goldShare',
    'heroDamage': 'heroDamageShare',
    'towerDamage': 'towerShare',
    'control': 'controlShare',
    'heal': 'healShare',
    'jungleGold': 'jungleShare',
}
LANE_ORDER = ('对抗路', '中路', '发育路', '打野', '游走')
# facts 的 PanelRow.lane 用「中路/游走」；这里兼容教练口头的「中单/辅助」等叫法。
LANE_ALIASES = {'中单': '中路', '辅助': '游走', '射手': '发育路', '边路': '对抗路'}
FLAG_LANES = ('对抗路', '中路', '发育路', '打野')
SUPPORT_LANES = ('游走',)
FLAG_GAP_PP = 5.0          # goldShare − heroDamageShare ≥ 5pp
FLAG_MIN_GOLD_SHARE = 20.0  # 且 goldShare ≥ 20
FARM_LANE = '发育路'
FARM_LANE_DEATH_LIMIT = 3  # 发育路死亡 ≥ 3 单独复核
SMALL_SAMPLE = 10          # n<10 用 20/20 固定分界
FIXED_SPLIT = 20.0

QUADRANTS = {
    (True, True): '高经济·高输出',
    (True, False): '高经济·低输出',
    (False, True): '低经济·高输出',
    (False, False): '低经济·低输出',
}

LANE_ROLE_NOTES = {
    '对抗路': '对抗路：吃线抗压与单带，输出占比通常低于经济占比，还要看承伤与先手。',
    '中路': '中路：中线资源集中，输出占比通常高于经济占比，重点看支援与团战转化。',
    '发育路': '发育路：经济优先喂给射手，输出占比一般高于经济占比；死亡偏多单独复核。',
    '打野': '打野：经济含野区与抓人收益，输出与经济不同步，看节奏与资源转化。',
    '游走': '游走/辅助：让经济、买辅助装，价值主要看控制与治疗，不按输出评价。',
}

RESOURCE_METRICS = {
    'goldBasis': GOLD_BASIS,
    'damageBasis': DAMAGE_BASIS,
    'towerBasis': TOWER_BASIS,
    'controlBasis': CONTROL_BASIS,
    'healBasis': HEAL_BASIS,
    'jungleBasis': JUNGLE_BASIS,
    'damageNote': 'damage 与 totalHeroHurtCnt 属不同口径，不混用；坦克/辅助价值不只在输出。',
    'note': ('damage 与 totalHeroHurtCnt 属不同口径，不混用；坦克/辅助价值不只在输出。'
             '经济=营地 money，英雄伤害=totalHeroHurtCnt，推塔=buildingDamage，均为终局面板口径。'),
}

NOTE = ('占比按「同局同阵营五人合计」计算，分路/选手筛选不改变占比分母；'
        '四象限只用于发现值得复核的资源配置，不评价选手；游走/辅助请改看控制/治疗。'
        'lane/player 筛选同时作用于逐人点、分路均值与效率表。')
EFFICIENCY_NOTE = '同分路内看「输出占比 / 经济占比」，不跨分路排名：各分路职责不同。'
EMPTY_NOTE = '没有可分析的面板行，不输出空图。'


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def _num(value):
    """数字或 None；bool 不当作数字（避免 True/False 混入统计）。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _r1(value):
    return None if value is None else round(float(value), 1)


def _r2(value):
    return None if value is None else round(float(value), 2)


def _plain(value):
    """整数值输出成 int（JSON 更干净），非整数保持 float。"""
    number = _num(value)
    if number is None:
        return None
    return int(number) if float(number).is_integer() else number


def _pct(value, total):
    """占比（0–100，未取整）；分子/分母缺失或分母 ≤0 返回 None。"""
    number = _num(value)
    base = _num(total)
    if number is None or base is None or base <= 0:
        return None
    return number * 100.0 / base


def _canonical_lane(value):
    text = str(value or '').replace('\u2060', '').strip()
    return LANE_ALIASES.get(text, text)


def _lane_index(lane):
    try:
        return LANE_ORDER.index(lane)
    except ValueError:
        return len(LANE_ORDER)


def _iso_date(value):
    """日期参数/行日期 → YYYY-MM-DD；空值返回 None。"""
    if value is None:
        return None
    if hasattr(value, 'isoformat'):
        try:
            return str(value.isoformat())[:10]
        except (TypeError, ValueError):
            return None
    text = str(value).strip()
    return text[:10] if text else None


def _text(value):
    return str(value or '').replace('\u2060', '').strip()


def _result_index(facts):
    """seq → 我方视角胜负（win/loss）。面板优先，回放兜底。"""
    mapping = {}
    for seq, panel in (facts.get('panels') or {}).items():
        if not isinstance(panel, dict):
            continue
        win = panel.get('win')
        if isinstance(win, bool):
            mapping[str(seq)] = 'win' if win else 'loss'
    for seq, game in (facts.get('games') or {}).items():
        if not isinstance(game, dict):
            continue
        result = game.get('result')
        if result in ('win', 'loss'):
            mapping[str(seq)] = result
    return mapping


def _own_result(row, results):
    """单行的「我方视角」胜负；面板/回放都没有时按行内 won 反推。"""
    seq = str(row.get('seq') or '')
    if seq in results:
        return results[seq]
    won = row.get('won')
    if isinstance(won, bool):
        if row.get('side') == 'own':
            return 'win' if won else 'loss'
        return 'loss' if won else 'win'
    return None


def _match_row(row, *, opponent, date_from, date_to, result, results):
    if opponent:
        if opponent not in (_text(row.get('opponentId')), _text(row.get('opponentName'))):
            return False
    if result:
        if _own_result(row, results) != result:
            return False
    date = _iso_date(row.get('date'))
    if date_from:
        if not date or date < date_from:
            return False
    if date_to:
        if not date or date > date_to:
            return False
    return True


def _row_points(row):
    """一行 PanelRow → 展示/计算用的基础字段（占比另算）。"""
    lane = _canonical_lane(row.get('lane'))
    minutes = _num(row.get('minutes'))
    gold = _num(row.get('gold'))
    return {
        'seq': str(row.get('seq') or ''),
        'date': _iso_date(row.get('date')) or '',
        'start': _text(row.get('start')),
        'opponentId': _text(row.get('opponentId')),
        'opponentName': _text(row.get('opponentName')),
        'side': row.get('side') or '',
        'result': None,
        'won': None,
        'playerId': _text(row.get('playerId')),
        'name': _text(row.get('name')),
        'lane': lane,
        'hero': _text(row.get('hero')),
        'minutes': _r2(minutes),
        'gold': _plain(gold),
        'heroDamage': _plain(row.get('heroDamage')),
        'damage': _plain(row.get('damage')),
        'taken': _plain(row.get('taken')),
        'towerDamage': _plain(row.get('towerDamage')),
        'control': _plain(row.get('control')),
        'heal': _plain(row.get('heal')),
        'jungleGold': _plain(row.get('jungleGold')),
        'cs': _plain(row.get('cs')),
        'deaths': _plain(row.get('deaths')),
        'participation': _num(row.get('participation')),
        'grade': _num(row.get('grade')),
        'gpm': _r1(gold / minutes) if gold is not None and minutes else None,
    }


def _coverage(all_rows, base, eligible, points=None):
    """覆盖统计：rows/panelGames 描述最终展示范围，*Eligible* 描述筛完对局、未筛分路/选手的范围。"""
    shown = list(points) if points is not None else list(eligible)
    dates = sorted({_iso_date(row.get('date')) for row in shown if _iso_date(row.get('date'))})
    rows_with_gold = sum(1 for row in eligible if _num(row.get('gold')) is not None)
    return {
        'panelGames': len({_text(row.get('seq')) for row in shown}),
        'panelGamesEligible': len({_text(row.get('seq')) for row in eligible}),
        'panelGamesTotal': len({_text(row.get('seq')) for row in all_rows}),
        'rows': len(shown),
        'rowsEligible': len(eligible),
        'rowsTotal': len(all_rows),
        'ownRows': sum(1 for row in base if row.get('side') == 'own'),
        'enemyRows': sum(1 for row in base if row.get('side') == 'enemy'),
        'rowsWithGold': rows_with_gold,
        'gamesWithGold': len({_text(row.get('seq')) for row in eligible
                             if _num(row.get('gold')) is not None}),
        'missingFields': {key: sum(1 for row in eligible if _num(row.get(key)) is None)
                          for key in TOTAL_KEYS},
        'unknownLaneRows': sum(1 for row in eligible if not _canonical_lane(row.get('lane'))),
        'dateRange': [dates[0], dates[-1]] if dates else [],
    }


def _empty_report(reason, filters, coverage):
    return {
        'available': False,
        'reason': reason,
        'filters': filters,
        'summary': {
            'games': 0, 'rows': 0, 'players': 0,
            'quadrantFlagCount': 0, 'anomalyCount': 0,
            'quadrantBasis': 'fixed', 'smallSample': True,
            'flagLanes': list(FLAG_LANES), 'supportLanes': list(SUPPORT_LANES),
            'note': NOTE,
        },
        'quadrantBasis': 'fixed',
        'quadrant': {
            'x': 'goldShare', 'y': 'heroDamageShare',
            'xSplit': FIXED_SPLIT, 'ySplit': FIXED_SPLIT,
            'basis': 'fixed', 'n': 0,
            'note': f'有效样本 <{SMALL_SAMPLE} 时统一用 20/20 固定分界。',
        },
        'players': [],
        'byLane': [],
        'anomalies': [],
        'efficiency': [],
        'efficiencyNote': EFFICIENCY_NOTE,
        # 口径同时给扁平字段（按契约 2.5 字面消费）与 metrics（API 冒烟测试口径）
        'goldBasis': GOLD_BASIS,
        'damageBasis': DAMAGE_BASIS,
        'towerBasis': TOWER_BASIS,
        'metrics': dict(RESOURCE_METRICS),
        'coverage': coverage,
        'note': f'{NOTE}{EMPTY_NOTE}',
    }


def _team_totals(eligible):
    """seq → 5 人合计（只加非 None 字段；全部缺失则为 None，不用 0 假填）。"""
    sums = defaultdict(lambda: defaultdict(float))
    counts = defaultdict(lambda: defaultdict(int))
    for row in eligible:
        seq = _text(row.get('seq'))
        for key in TOTAL_KEYS:
            value = _num(row.get(key))
            if value is not None:
                sums[seq][key] += value
                counts[seq][key] += 1
    return {
        seq: {key: (sums[seq][key] if counts[seq][key] else None) for key in TOTAL_KEYS}
        for seq in sums
    }


def _quadrant_split(points):
    """返回 (basis, x_split, y_split, n)；n<10 或没有有效点时用 20/20 固定分界。

    用展示值（1 位小数占比）算中位数与分界，保证页面数字与象限标签一致。
    """
    pairs = [(point['goldShare'], point['heroDamageShare']) for point in points
             if point['goldShare'] is not None and point['heroDamageShare'] is not None]
    n = len(pairs)
    if n >= SMALL_SAMPLE:
        x_split = _r1(median([pair[0] for pair in pairs]))
        y_split = _r1(median([pair[1] for pair in pairs]))
        if x_split is not None and y_split is not None:
            return 'median', x_split, y_split, n
    return 'fixed', FIXED_SPLIT, FIXED_SPLIT, n


def _flag(row_point):
    """quadrantFlag：仅 中路/发育路/对抗路/打野，且吃钱多、打伤害少。"""
    if row_point['lane'] not in FLAG_LANES:
        return False
    x, y = row_point['goldShare'], row_point['heroDamageShare']
    if x is None or y is None:
        return False
    return (x - y) >= FLAG_GAP_PP and x >= FLAG_MIN_GOLD_SHARE


def _anomaly_text(point, gap, flag, death_risk):
    parts = []
    if flag:
        parts.append(
            f"经济占比 {point['goldShare']:.1f}%，英雄伤害占比 "
            f"{point['heroDamageShare']:.1f}%（差 {gap:.1f}pp）"
        )
    if death_risk:
        part = f"本局死亡 {int(point['deaths'])} 次"
        if point['goldShare'] is not None:
            part += f"，经济占比 {point['goldShare']:.1f}%"
        if point['heroDamageShare'] is not None:
            part += f"，英雄伤害占比 {point['heroDamageShare']:.1f}%"
        parts.append(part)
    return '；'.join(parts)


def _by_lane(points):
    groups = defaultdict(list)
    for point in points:
        lane = point['lane'] or ''
        if lane:
            groups[lane].append(point)

    def lane_mean(rows, key):
        return _r1(mean([row[key] for row in rows if row.get(key) is not None]))

    out = []
    for lane in sorted(groups, key=_lane_index):
        rows = groups[lane]
        out.append({
            'lane': lane,
            'n': len(rows),
            'games': len({row['seq'] for row in rows}),
            'goldShare': lane_mean(rows, 'goldShare'),
            'heroDamageShare': lane_mean(rows, 'heroDamageShare'),
            'towerShare': lane_mean(rows, 'towerShare'),
            'controlShare': lane_mean(rows, 'controlShare'),
            'healShare': lane_mean(rows, 'healShare'),
            'jungleShare': lane_mean(rows, 'jungleShare'),
            'deaths': lane_mean(rows, 'deaths'),
            'gpm': lane_mean(rows, 'gpm'),
        })
    return out


def _efficiency(points):
    groups = defaultdict(list)
    for point in points:
        lane = point['lane'] or ''
        if lane:
            groups[lane].append(point)

    out = []
    for lane in sorted(groups, key=_lane_index):
        rows = groups[lane]
        ratios = []
        for row in rows:
            x, y = row.get('goldShare'), row.get('heroDamageShare')
            if x is not None and y is not None and x > 0:
                ratios.append(y / x)
        out.append({
            'lane': lane,
            'n': len(ratios),
            'ratio': _r2(mean(ratios)),
            'goldShare': _r1(mean([row['goldShare'] for row in rows
                                   if row.get('goldShare') is not None])),
            'heroDamageShare': _r1(mean([row['heroDamageShare'] for row in rows
                                         if row.get('heroDamageShare') is not None])),
            'note': LANE_ROLE_NOTES.get(lane, ''),
        })
    return out


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def resource_report(facts, *, lane=None, player=None, opponent=None,
                    date_from=None, date_to=None, result=None, side='own'):
    """资源分配与发育效率报告（默认 side='own'，只取我方 5 人）。

    参数：
    - lane：分路（中路/发育路/对抗路/打野/游走；兼容「中单/辅助」叫法）。
    - player：选手 playerId 或营地昵称，精确匹配。
    - opponent：对手 id 或对手名，精确匹配。
    - date_from/date_to：YYYY-MM-DD（或 date），与行日期比较。
    - result：``win`` / ``loss``（我方视角；需要面板或回放能判定胜负）。
    - side：``own``（默认）/``enemy``，enemy 用于对照。

    过滤后无面板行、或面板缺少金币字段时返回 ``available=false`` + ``reason``。
    """
    side_key = str(side or 'own').strip().lower()
    if side_key not in SIDES:
        raise ValueError('side 只能取 own 或 enemy')

    facts = facts if isinstance(facts, dict) else {}
    all_rows = [row for row in (facts.get('rows') or []) if isinstance(row, dict)]

    lane_filter = _canonical_lane(lane) if _text(lane) else None
    player_filter = _text(player) or None
    opponent_filter = _text(opponent) or None
    result_filter = _text(result) or None
    date_from_key = _iso_date(date_from)
    date_to_key = _iso_date(date_to)
    filters = {
        'side': side_key,
        'lane': lane_filter,
        'player': player_filter,
        'opponent': opponent_filter,
        'dateFrom': date_from_key,
        'dateTo': date_to_key,
        'result': result_filter,
    }

    if not all_rows:
        return _empty_report(
            '终局面板为空（data/camp_details 没有可解析的逐人数据），无法做资源分配分析。',
            filters, _coverage([], [], []))

    results = _result_index(facts)
    base = [row for row in all_rows
            if _match_row(row, opponent=opponent_filter, date_from=date_from_key,
                          date_to=date_to_key, result=result_filter, results=results)]
    eligible = [row for row in base if row.get('side') == side_key]

    if not base:
        return _empty_report(
            '当前筛选范围内没有对局；请放宽日期、对手或胜负筛选。',
            filters, _coverage(all_rows, [], []))
    if not eligible:
        who = '我方' if side_key == 'own' else '对方'
        return _empty_report(
            f'当前筛选下没有{who}面板行；请检查数据覆盖或筛选条件。',
            filters, _coverage(all_rows, base, []))

    team_totals = _team_totals(eligible)

    points = []
    for row in eligible:
        lane_value = _canonical_lane(row.get('lane'))
        if lane_filter and lane_value != lane_filter:
            continue
        if player_filter and player_filter not in (_text(row.get('playerId')), _text(row.get('name'))):
            continue
        seq = _text(row.get('seq'))
        team = team_totals.get(seq) or {}
        point = _row_points(row)
        point['result'] = _own_result(row, results)
        point['won'] = None if point['result'] is None else point['result'] == 'win'
        for key, share_key in VALUE_TO_SHARE.items():
            point[share_key] = _r1(_pct(row.get(key), team.get(key)))
        points.append(point)

    if not points:
        detail = []
        if lane_filter:
            detail.append(f'分路={lane_filter}')
        if player_filter:
            detail.append(f'选手={player_filter}')
        suffix = f"（{'、'.join(detail)}）" if detail else ''
        return _empty_report(
            f'当前筛选筛不出任何选手面板行{suffix}；请放宽分路/选手筛选。',
            filters, _coverage(all_rows, base, eligible))

    coverage = _coverage(all_rows, base, eligible, points)
    if coverage['rowsWithGold'] == 0 or coverage['gamesWithGold'] == 0:
        return _empty_report(
            '面板行缺少 battleStats.money（金币）字段，无法计算经济占比与 GPM。',
            filters, coverage)

    # 四象限：默认中位数分界，n<10 用 20/20 固定分界
    basis, x_split, y_split, quad_n = _quadrant_split(points)
    for point in points:
        x, y = point['goldShare'], point['heroDamageShare']
        if x is None or y is None:
            point['quadrant'] = None
        else:
            point['quadrant'] = QUADRANTS[(x >= x_split, y >= y_split)]
        point['quadrantFlag'] = _flag(point)
        point['goldDamageGap'] = _r1(x - y) if x is not None and y is not None else None

    # anomalies：只列 quadrantFlag 或「发育路死亡 ≥3」，不排名、不评价选手
    anomalies = []
    for point in points:
        flag = point['quadrantFlag']
        deaths = point['deaths']
        death_risk = (point['lane'] == FARM_LANE and deaths is not None
                      and deaths >= FARM_LANE_DEATH_LIMIT)
        if not flag and not death_risk:
            continue
        gap = point['goldDamageGap'] if flag else None
        kind = ('high_gold_low_damage' if flag and not death_risk
                else 'farm_lane_deaths' if death_risk and not flag
                else 'high_gold_low_damage+farm_lane_deaths')
        anomalies.append({
            'kind': kind,
            'text': _anomaly_text(point, gap if gap is not None else 0.0, flag, death_risk),
            'gap': gap,
            'seq': point['seq'],
            'date': point['date'],
            'start': point['start'],
            'opponentName': point['opponentName'],
            'result': point['result'],
            'playerId': point['playerId'],
            'name': point['name'],
            'lane': point['lane'],
            'hero': point['hero'],
            'goldShare': point['goldShare'],
            'heroDamageShare': point['heroDamageShare'],
            'deaths': point['deaths'],
            'gold': point['gold'],
            'heroDamage': point['heroDamage'],
            'gpm': point['gpm'],
            'quadrant': point['quadrant'],
        })
    anomalies.sort(key=lambda item: (item['date'], item['start'],
                                     _lane_index(item['lane']), item['playerId']))

    by_lane = _by_lane(points)
    efficiency = _efficiency(points)
    flag_count = sum(1 for point in points if point['quadrantFlag'])
    death_count = sum(1 for item in anomalies if 'farm_lane_deaths' in item['kind'])

    summary = {
        'games': len({point['seq'] for point in points}),
        'rows': len(points),
        'players': len({point['playerId'] for point in points if point['playerId']}),
        'quadrantFlagCount': flag_count,
        'deathAnomalyCount': death_count,
        'anomalyCount': len(anomalies),
        'quadrantBasis': basis,
        'smallSample': quad_n < SMALL_SAMPLE,
        'flagLanes': list(FLAG_LANES),
        'supportLanes': list(SUPPORT_LANES),
        'note': NOTE,
    }

    return {
        'available': True,
        'reason': None,
        'filters': filters,
        'summary': summary,
        'quadrantBasis': basis,
        'quadrant': {
            'x': 'goldShare', 'y': 'heroDamageShare',
            'xSplit': x_split, 'ySplit': y_split,
            'basis': basis, 'n': quad_n,
            'note': (f'样本 {quad_n} 人：以 goldShare / heroDamageShare 各自中位数分界。'
                     if basis == 'median'
                     else f'有效样本 <{SMALL_SAMPLE}，统一用 20/20 固定分界。'),
        },
        'players': points,
        'byLane': by_lane,
        'anomalies': anomalies,
        'efficiency': efficiency,
        'efficiencyNote': EFFICIENCY_NOTE,
        # 口径同时给扁平字段（按契约 2.5 字面消费）与 metrics（API 冒烟测试口径）
        'goldBasis': GOLD_BASIS,
        'damageBasis': DAMAGE_BASIS,
        'towerBasis': TOWER_BASIS,
        'metrics': dict(RESOURCE_METRICS),
        'coverage': coverage,
        'note': NOTE,
    }
