"""A8 经济转折匹配 / A9 优势兑现路径。

只用回放里的团队经济序列与事件：
  normalized.economy.diff[]   约 30 秒一个点
  normalized.events.key[]     资源 / 团战事件
  normalized.match.durationSec / winCamp
  camp_details/<seq>.json     head.acntCamp（我方阵营）

口径（与规格一致）：
- 经济点是按索引线性铺到时间轴上的，标 approx=true，不假装精确。
- 转折只列候选事件，不宣称因果。
- 转化率用 Wilson 区间；样本 <10 局只给观察，不给结论。
"""
from __future__ import annotations

import json
import math
from pathlib import Path

WINDOWS = (30, 60, 120)
BUCKETS = (
    ('落后', -10 ** 9, -500),
    ('持平', -500, 500),
    ('小优', 500, 1500),
    ('大优', 1500, 10 ** 9),
)


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def load_games(replays_dir: Path, camp_dir: Path):
    """把回放与营地面板配对，补上我方阵营与胜负。"""
    games = []
    for folder in sorted(Path(replays_dir).glob('camp-*')):
        normalized = _read_json(folder / 'normalized.json')
        if not normalized:
            continue
        seq = folder.name.split('camp-')[-1]
        panel = _read_json(Path(camp_dir) / f'{seq}.json') or {}
        head = ((panel.get('data') or {}).get('head')) or {}
        own_code = str(head.get('acntCamp') or '')
        own_camp = {'1': 'blue', '2': 'red'}.get(own_code)
        match = normalized.get('match') or {}
        economy = normalized.get('economy') or {}
        diff = [value for value in (economy.get('diff') or []) if isinstance(value, (int, float))]
        if not diff or own_camp is None:
            continue
        duration = float(match.get('durationSec') or 0)
        if duration <= 0:
            continue
        win_camp = str(match.get('winCamp') or '')
        winner = {'1': 'blue', '2': 'red'}.get(win_camp)
        games.append({
            'seq': seq,
            'ownCamp': own_camp,
            'winner': winner,
            'win': None if winner is None else winner == own_camp,
            'duration': duration,
            'diff': diff,
            'events': (normalized.get('events') or {}).get('key') or [],
            'note': (economy.get('note') or ''),
        })
    return games


def _time_at(index, count, duration):
    return index * duration / max(1, count - 1)


def turning_points(replays_dir, camp_dir, *, min_delta=1000, limit=40):
    games = load_games(replays_dir, camp_dir)
    rows = []
    for game in games:
        diff = game['diff']
        count = len(diff)
        if count < 3:
            continue
        magnitudes = []
        for window in WINDOWS:
            step = max(1, round(window / max(1, game['duration'] / (count - 1))))
            for index in range(count - step):
                magnitudes.append(abs(diff[index + step] - diff[index]))
        if not magnitudes:
            continue
        magnitudes.sort()
        p90 = magnitudes[min(len(magnitudes) - 1, int(len(magnitudes) * 0.9))]
        threshold = max(min_delta, p90)

        for window in WINDOWS:
            seconds_per_point = game['duration'] / max(1, count - 1)
            step = max(1, round(window / max(1, seconds_per_point)))
            for index in range(count - step):
                delta = diff[index + step] - diff[index]
                if abs(delta) < threshold:
                    continue
                start = _time_at(index, count, game['duration'])
                end = _time_at(index + step, count, game['duration'])
                candidates = []
                for event in game['events']:
                    moment = event.get('timeSec')
                    if not isinstance(moment, (int, float)):
                        continue
                    if start - 60 <= moment <= end + 60:
                        candidates.append({
                            'type': event.get('eventType') or 'unknown',
                            't': round(float(moment), 1),
                            'camp': str(event.get('killerCamp') or event.get('dtCamp') or ''),
                            'magnitude': len(event.get('kills') or []),
                        })
                candidates.sort(key=lambda item: (abs(item['t'] - (start + end) / 2), -item['magnitude']))
                rows.append({
                    'game': game['seq'],
                    'window': window,
                    'start': round(start, 1),
                    'end': round(end, 1),
                    'delta': int(round(delta)),
                    'direction': 'blue' if delta > 0 else 'red',
                    'ownCamp': game['ownCamp'],
                    'ownAdvantage': (delta > 0) == (game['ownCamp'] == 'blue'),
                    'candidates': candidates[:4],
                    'approx': True,
                })
    rows.sort(key=lambda item: -abs(item['delta']))
    top = rows[:limit]

    # 给页面画图：把上榜对局的经济序列一并返回（最多 6 局）
    wanted = []
    for row in top:
        if row['game'] not in wanted:
            wanted.append(row['game'])
        if len(wanted) >= 6:
            break
    series = {}
    for game in games:
        if game['seq'] not in wanted:
            continue
        series[game['seq']] = {
            'duration': round(game['duration'], 1),
            'diff': game['diff'],
            'ownCamp': game['ownCamp'],
            'swings': [{'start': item['start'], 'end': item['end'], 'delta': item['delta']}
                       for item in top if item['game'] == game['seq']][:12],
        }

    return {
        'games': len(games),
        'threshold': min_delta,
        'rows': top,
        'total': len(rows),
        'series': series,
        'note': '经济点按索引均匀铺到时间轴（约 30 秒），窗口内只列候选事件，不宣称因果。',
    }


def _wilson(success, total, z=1.96):
    if total <= 0:
        return None, None
    phat = success / total
    denominator = 1 + z * z / total
    center = (phat + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(phat * (1 - phat) / total + z * z / (4 * total * total)) / denominator
    return max(0.0, center - margin) * 100, min(1.0, center + margin) * 100


def _value_at(seconds, diff, duration):
    count = len(diff)
    if count == 1:
        return diff[0]
    position = seconds / duration * (count - 1)
    # 短于取值时刻的对局（如 8 分钟投降局）position 会越过末点，必须夹住；
    # 否则 diff[low] 索引越界，优势兑现分析整页 500。夹住后取终局值，
    # 语义就是「该局在这个时刻已经结束」。
    low = max(0, min(count - 1, int(math.floor(position))))
    high = min(count - 1, low + 1)
    ratio = position - low
    return diff[low] * (1 - ratio) + diff[high] * ratio


def advantage(replays_dir, camp_dir, *, landmark=600):
    games = load_games(replays_dir, camp_dir)
    buckets = {name: {'n': 0, 'wins': 0, 'label': name, 'low': low, 'high': high}
               for name, low, high in BUCKETS}
    rows = []
    skipped_short = 0
    for game in games:
        if game['win'] is None:
            continue
        # 短于观测时刻（如 8 分钟投降）的局没有十分钟采样点，不能把终局经济差
        # 当成十分钟经济差计入分桶；与 v3/deep_analysis.advantage_from_games
        # 及 decision_loss 的 leadAt10 口径保持一致。
        if game['duration'] + 1e-9 < landmark:
            skipped_short += 1
            continue
        lead = _value_at(landmark, game['diff'], game['duration'])
        # 统一成「我方视角」：蓝方领先为正，红方要反过来
        own_lead = lead if game['ownCamp'] == 'blue' else -lead
        bucket_name = next((name for name, low, high in BUCKETS if low <= own_lead < high), '大优')
        bucket = buckets[bucket_name]
        bucket['n'] += 1
        bucket['wins'] += 1 if game['win'] else 0
        rows.append({
            'game': game['seq'],
            'ownCamp': game['ownCamp'],
            'leadAt10': int(round(own_lead)),
            'bucket': bucket_name,
            'won': game['win'],
        })

    summary = []
    for name, _, _ in BUCKETS:
        bucket = buckets[name]
        low, high = _wilson(bucket['wins'], bucket['n'])
        summary.append({
            'bucket': name,
            'n': bucket['n'],
            'wins': bucket['wins'],
            'winRate': round(bucket['wins'] / bucket['n'] * 100, 1) if bucket['n'] else None,
            'ciLow': None if low is None else round(low, 1),
            'ciHigh': None if high is None else round(high, 1),
            'enough': bucket['n'] >= 10,
        })

    overall_n = sum(item['n'] for item in summary)
    overall_w = sum(item['wins'] for item in summary)
    return {
        'games': len(games),
        'usableGames': len(rows),
        'excludedShortGames': skipped_short,
        'landmark': landmark,
        'rows': rows,
        'buckets': summary,
        'overall': {'n': overall_n, 'wins': overall_w,
                    'winRate': round(overall_w / overall_n * 100, 1) if overall_n else None},
        'note': '只算有胜负、且时长覆盖十分钟采样点的局（短局不参与，不补 0）；'
                '样本 <10 只给观察，不给转化率结论。',
    }



# ===========================================================================
# Merged from merged module (loss_chain + advantage_retention)
# ===========================================================================

"""赛训决策台 · 失利关键链（P0-1）与优势保持（P0-2）。

只读 ``match_facts.load_facts`` 的统一事实表，不扫目录、不读原始回放。
口径严格对齐 ``README.md`` 第 2.2 节：

- 经济点按采样索引均匀铺到时间轴（约 30 秒一个），窗口起止时间一律由
  ``Game.times`` / ``match_facts.value_at`` 推导并标 ``approx``，不假装精确。
- 失利窗口：30 / 60 / 120 秒滑窗，阈值 = max(1000, 该局 |Δ| 的 P90)，
  只取我方视角（``ownDiff`` 已按阵营翻转）的负向窗口；关联范围 = 窗口 ±60 秒。
- 主类按优先级取一个：wipe → multi_death → teamfight_loss →
  objective_lost → no_trade → unclassified；``candidates`` 保留关联范围内全部候选。
- 所有关键链的 ``confidence`` 恒为 ``candidate``，只是候选事件，不证明因果。
- 小样本（n<10）只展示事实与分布，不输出稳定结论；无数据返回
  ``available=false`` + ``reason``，不用 0 假填、不画空图。

优势保持（按局，我方视角）：
- ``maxLead`` / ``maxLeadAt``：最大经济领先及对应时间；
- ``drawdown`` / ``drawdownAt``：峰值之后（含峰值点）到终局的最低点与峰值之差；
- ``leadDurationSec``：ownDiff ≥ +500 的累计采样时长；
- ``conversionSec``：首次 ≥ +1000 后到下一次我方资源/建筑事件的时间差；
- ``postLead2mDelta``：首次跨越 +1000 后 120 秒的经济差变化；
- ``comeback``：maxLead ≥ +1000 且最终告负；
- ``leadAt10``：十分钟经济差（duration < 600 的局不参与该指标，不补 0）。
"""

import math

import match_facts as df

__all__ = ['loss_report', 'advantage_report']

# ---- 失利关键链（契约 2.2） -------------------------------------------------
WINDOWS = (30, 60, 120)          # 滑窗长度（秒）
EVIDENCE_WINDOW = 60             # 关联半径（秒），窗口 ±60 秒
MIN_DELTA = 1000                 # 显著变化下限（经济差）
TYPE_ORDER = ('wipe', 'multi_death', 'teamfight_loss', 'objective_lost',
              'no_trade', 'unclassified')
TYPE_LABELS = {
    # 教练可读口径：wipe 指窗口内我方阵亡 ≥4 人，不等于「一波团灭」，避免页面误解。
    'wipe': '4 人以上阵亡',
    'multi_death': '多人阵亡',
    'teamfight_loss': '团战失利',
    'objective_lost': '丢失资源/建筑',
    'no_trade': '未形成置换',
    'unclassified': '其他候选',
}

# ---- 优势保持（契约 2.2 / A9 口径） -----------------------------------------
LEAD_THRESHOLD = 500             # 领先时长累计阈值
SIGNIFICANT_LEAD = 1000          # 显著领先 / 翻盘阈值
CALLBACK_SEC = 120               # lead 后回看窗口
LANDMARK_SEC = 600               # 十分钟标记点
# 与 analysis_economy.BUCKETS 相同的十分钟分桶边界（本模块不 import 旧模块）
BUCKETS = (
    ('落后', -10 ** 9, -500),
    ('持平', -500, 500),
    ('小优', 500, 1500),
    ('大优', 1500, 10 ** 9),
)
MAX_BAND_MINUTE = 30

# ---- 小样本 / 输出上限 ------------------------------------------------------
MIN_SAMPLE = 10                  # 结论类指标的最小样本
MIN_PATH_SAMPLE = 3              # 路径展示的最小出现次数
MAX_PATTERN_EVIDENCE = 5         # summary.patterns[].evidence 上限
MAX_GAME_CANDIDATES = 3          # advantage games[].candidates 上限


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def _finite(value):
    """转 float；None / 非数 / NaN / inf 一律返回 None。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _round(value, digits=1):
    number = _finite(value)
    return None if number is None else round(number, digits)


def _signed(value):
    number = _finite(value)
    return '—' if number is None else f'{int(round(number)):+d}'


def _camp_text(camp):
    return {'own': '我方', 'enemy': '敌方'}.get(camp, '未标注阵营')


def _series(game):
    """取某局我方视角经济序列；不足两个点或缺少时长时返回 None。"""
    duration = _finite(game.get('duration'))
    if not duration or duration <= 0:
        return None
    own = [float(value) for value in (game.get('ownDiff') or []) if _finite(value) is not None]
    if len(own) < 2:
        return None
    times = [float(value) for value in (game.get('times') or []) if _finite(value) is not None]
    if len(times) != len(own):
        # 事实表会带 times；万一缺失按索引均匀铺开（与 load_facts 同口径）
        times = [round(df.time_at(index, len(own), duration), 1) for index in range(len(own))]
    raw = [float(value) for value in (game.get('diff') or []) if _finite(value) is not None]
    if len(raw) != len(own):
        raw = list(own)
    return {
        'ownDiff': own,
        'rawDiff': raw,
        'times': times,
        'duration': float(duration),
    }


def _context(game):
    """某局关联事件（死亡 / 团战 / 资源建筑），只算一次后复用。"""
    return {
        'deaths': df.death_events(game),
        'fights': df.fight_events(game),
        'objectives': df.objective_events(game),
    }


def _overlaps(fight, low, high):
    """团战 [startSec, endSec] 是否与 [low, high] 有交集。"""
    start = _finite(fight.get('startSec'))
    if start is None:
        return False
    end = _finite(fight.get('endSec'))
    if end is None or end < start:
        end = start
    return start <= high and end >= low


def _result_counts(games):
    counts = {'win': 0, 'loss': 0, 'unknown': 0}
    for item in games:
        key = item.get('result')
        if key in ('win', 'loss'):
            counts[key] += 1
        else:
            counts['unknown'] += 1
    return counts


def _date_range(games):
    dates = sorted({item.get('date') for item in games if item.get('date')})
    return [dates[0], dates[-1]] if dates else []


# ---------------------------------------------------------------------------
# 失利关键链：窗口、关联、分类
# ---------------------------------------------------------------------------
def _windows(series):
    """30/60/120 秒滑窗里筛出我方视角的负向显著窗口。

    返回 ``(windows, threshold)``；``threshold = max(1000, |Δ| P90)``。
    同一 (start, end) 范围只保留最先命中的窗口长度，避免 30/60 秒窗口在
    采样间隔较大时重复计同一次变化。
    """
    own = series['ownDiff']
    times = series['times']
    duration = series['duration']
    count = len(own)
    spacing = duration / float(count - 1)
    steps = {}
    magnitudes = []
    for window in WINDOWS:
        step = max(1, int(round(window / spacing))) if spacing > 0 else 1
        step = min(step, count - 1)
        steps[window] = step
        for index in range(count - step):
            magnitudes.append(abs(own[index + step] - own[index]))
    p90 = df.percentile(magnitudes, 90)
    threshold = max(float(MIN_DELTA), float(p90 or 0.0))

    found = []
    seen = set()
    for window in WINDOWS:
        step = steps[window]
        if step < 1:
            continue
        for index in range(count - step):
            delta = own[index + step] - own[index]
            if delta >= 0:                       # 只取负向（我方吃亏）
                continue
            if abs(delta) < threshold - 1e-9:    # 阈值 = max(1000, P90)
                continue
            start, end = times[index], times[index + step]
            key = (round(start, 2), round(end, 2))
            if key in seen:
                continue
            seen.add(key)
            found.append({
                'windowSec': window,
                'index': index,
                'step': step,
                'start': round(start, 1),
                'end': round(end, 1),
                'delta': round(delta, 1),
            })
    found.sort(key=lambda item: (item['start'], item['windowSec']))
    return found, round(threshold, 1)


def _classify(context, start, end):
    """窗口 ±60 秒内关联事件，并按优先级给一个主类。

    死亡类主类（wipe / multi_death）按**窗口内**（start–end）我方阵亡人数判定：
    若按 ±60 秒关联窗统计，真实局 240 秒跨度必然凑满 4 人，所有窗口都会误判成
    「4 人以上阵亡」。窗口外的死亡仍保留在 candidates 里，供教练复核。
    """
    low = start - EVIDENCE_WINDOW
    high = end + EVIDENCE_WINDOW
    deaths = [item for item in context['deaths'] if low <= item['t'] <= high]
    fights = [item for item in context['fights'] if _overlaps(item, low, high)]
    objectives = [item for item in context['objectives'] if low <= item['t'] <= high]
    window_deaths = [item for item in deaths if start <= item['t'] <= end]
    window_own_deaths = [item for item in window_deaths if item['side'] == 'own']
    own_deaths = [item for item in deaths if item['side'] == 'own']
    enemy_deaths = [item for item in deaths if item['side'] == 'enemy']
    own_objectives = [item for item in objectives if item['camp'] == 'own']
    enemy_objectives = [item for item in objectives if item['camp'] == 'enemy']
    losing_fights = [item for item in fights
                     if item['killDiff'] is not None and item['killDiff'] <= -2]
    won_fights = [item for item in fights
                  if item['killDiff'] is not None and item['killDiff'] > 0]

    if len(window_own_deaths) >= 4:
        primary = 'wipe'
    elif len(window_own_deaths) >= 2:
        primary = 'multi_death'
    elif losing_fights:
        primary = 'teamfight_loss'
    elif enemy_objectives and not own_objectives:
        primary = 'objective_lost'
    elif not own_objectives and not won_fights:
        primary = 'no_trade'
    else:
        primary = 'unclassified'
    return {
        'type': primary,
        'deaths': deaths,
        'windowDeaths': window_deaths,
        'windowOwnDeaths': window_own_deaths,
        'ownDeaths': own_deaths,
        'enemyDeaths': enemy_deaths,
        'fights': fights,
        'losingFights': losing_fights,
        'wonFights': won_fights,
        'objectives': objectives,
        'ownObjectives': own_objectives,
        'enemyObjectives': enemy_objectives,
    }


def _candidates(relation):
    """把关联范围内的死亡/团战/资源建筑整理成候选证据（全保留）。"""
    items = []
    for death in relation['deaths']:
        hero = death.get('hero') or '队员'
        text = f"{df.clock(death['t'])} {_camp_text(death['side'])}{hero}阵亡"
        if death['side'] == 'own':
            if death.get('isolated'):
                text += '（附近没有队友）'
            elif death.get('nearAllies') is not None:
                text += f"（附近 {death['nearAllies']} 名队友）"
        items.append({
            'kind': 'death',
            't': death['t'],
            'side': death['side'],
            'player': death.get('player') or '',
            'hero': hero,
            'nearAllies': death.get('nearAllies'),
            'isolated': death.get('isolated'),
            'text': text,
        })
    for fight in relation['fights']:
        end = fight.get('endSec')
        end_text = end if end is not None else fight['startSec']
        text = f"{df.clock(fight['startSec'])}–{df.clock(end_text)} 团战"
        if fight.get('killDiff') is not None:
            text += f"我方击杀 {fight.get('ownKills', 0)}:{fight.get('enemyKills', 0)}"
        if fight.get('advStart') is not None:
            text += f"，开局人数差 {fight['advStart']:+d}"
        items.append({
            'kind': 'fight',
            't': fight['startSec'],
            'end': end,
            'ownKills': fight.get('ownKills'),
            'enemyKills': fight.get('enemyKills'),
            'killDiff': fight.get('killDiff'),
            'advStart': fight.get('advStart'),
            'ownParticipants': fight.get('ownParticipants'),
            'enemyParticipants': fight.get('enemyParticipants'),
            'text': text,
        })
    for objective in relation['objectives']:
        camp = objective['camp']
        if camp == 'unknown':
            text = f"{df.clock(objective['t'])} 出现{objective['name']}事件（阵营未标注）"
        else:
            text = f"{df.clock(objective['t'])} {_camp_text(camp)}拿到{objective['name']}"
        items.append({
            'kind': 'objective',
            't': objective['t'],
            'name': objective['name'],
            'objectKind': objective['kind'],
            'camp': camp,
            'text': text,
        })
    items.sort(key=lambda item: (item['t'], item['kind']))
    return items


def _row_evidence(series, window, relation):
    """给教练看的一句话级证据（不宣称因果，只描述同期事实）。"""
    index = window['index']
    step = window['step']
    before = series['ownDiff'][index]
    after = series['ownDiff'][index + step]
    evidence = [
        f"{df.clock(window['start'])}–{df.clock(window['end'])} 我方经济差 "
        f"{_signed(before)} → {_signed(after)}（≈{_signed(window['delta'])}，近似采样）"
    ]
    own_deaths = relation['ownDeaths']
    window_own_deaths = relation['windowOwnDeaths']
    if window_own_deaths:
        suffix = '（4 人以上阵亡）' if len(window_own_deaths) >= 4 else ''
        evidence.append(f'窗口内我方 {len(window_own_deaths)} 人阵亡{suffix}')
    elif own_deaths:
        evidence.append(f'关联窗口内我方 {len(own_deaths)} 人阵亡（在窗口外）')
    if relation['enemyDeaths']:
        evidence.append(f"关联窗口内敌方 {len(relation['enemyDeaths'])} 人阵亡")
    for fight in relation['losingFights'][:2]:
        evidence.append(
            f"团战 {df.clock(fight['startSec'])} 起我方击杀差 {fight['killDiff']:+d}"
        )
    for objective in relation['enemyObjectives'][:2]:
        evidence.append(f"{df.clock(objective['t'])} 敌方拿到{objective['name']}")
    for objective in relation['ownObjectives'][:2]:
        evidence.append(f"{df.clock(objective['t'])} 我方拿到{objective['name']}")
    return evidence


def _build_row(game, series, window, context):
    relation = _classify(context, window['start'], window['end'])
    primary = relation['type']
    return {
        'game': game['id'],
        'label': game.get('label') or '',
        'opponent': game.get('opponentName') or '',
        'opponentId': game.get('opponentId'),
        'result': game.get('result'),
        'ownCamp': game.get('ownCamp'),
        'phase': df.phase_of(window['start']),
        'start': window['start'],
        'end': window['end'],
        'startClock': df.clock(window['start']),
        'endClock': df.clock(window['end']),
        'windowSec': window['windowSec'],
        'delta': int(round(window['delta'])),
        'type': primary,
        'typeLabel': TYPE_LABELS[primary],
        'candidates': _candidates(relation),
        'evidence': _row_evidence(series, window, relation),
        'confidence': 'candidate',
        'approx': True,
    }


# ---------------------------------------------------------------------------
# 失利关键链：汇总与对外入口
# ---------------------------------------------------------------------------
def _pattern_text(row):
    return (f"{row['label']} {row['startClock']}–{row['endClock']}，"
            f"经济差变化 {row['delta']:+d}，主类「{row['typeLabel']}」")


def _loss_summary(rows, economy, results):
    by_type = {key: 0 for key in TYPE_ORDER}
    for row in rows:
        by_type[row['type']] += 1

    patterns = []
    for key in TYPE_ORDER:
        subset = [row for row in rows if row['type'] == key]
        if not subset:
            continue
        costs = [row['delta'] for row in subset]
        patterns.append({
            'type': key,
            'typeLabel': TYPE_LABELS[key],
            'windows': len(subset),
            'games': len({row['game'] for row in subset}),
            'avgCost': _round(df.mean(costs), 1),
            'minCost': int(round(min(costs))),
            'enough': len(subset) >= MIN_SAMPLE,
            'reason': None if len(subset) >= MIN_SAMPLE else
                      f'该主类仅 {len(subset)} 条窗口（<10），只做观察',
            'evidence': [{
                'game': row['game'],
                'label': row['label'],
                'start': row['start'],
                'end': row['end'],
                'cost': row['delta'],
                'text': _pattern_text(row),
            } for row in subset[:MAX_PATTERN_EVIDENCE]],
        })
    patterns.sort(key=lambda item: (-item['windows'], item['avgCost'] or 0))

    phases = []
    for _, _, label in df.PHASES:
        subset = [row for row in rows if row['phase'] == label]
        phases.append({
            'phase': label,
            'windows': len(subset),
            'games': len({row['game'] for row in subset}),
            'avgCost': _round(df.mean([row['delta'] for row in subset]), 1),
            'enough': len(subset) >= MIN_SAMPLE,
        })

    enough = len(rows) >= MIN_SAMPLE
    return {
        'games': len(economy),
        'gamesWithWindows': len({row['game'] for row in rows}),
        'windows': len(rows),
        'enough': enough,
        'reason': None if enough else
                  f'失利窗口仅 {len(rows)} 条（<10），只做观察，不据此下结论',
        'results': results,
        'byType': by_type,
        'patterns': patterns,
        'phases': phases,
        'thresholds': {
            'windows': list(WINDOWS),
            'minDelta': MIN_DELTA,
            'evidenceWindowSec': EVIDENCE_WINDOW,
        },
    }


def _loss_coverage(selected, economy, skipped, rows):
    return {
        'games': len(selected),
        'economyGames': len(economy),
        'skippedGames': len(skipped),
        'skipped': skipped,
        'windows': len(rows),
        'gamesWithWindows': len({row['game'] for row in rows}),
        'dateRange': _date_range(selected),
        'results': _result_counts(selected),
        'approx': True,
    }


def _empty_loss(filters, coverage, *, reason, note):
    return {
        'available': False,
        'filters': filters,
        'summary': {
            'games': coverage['games'],
            'economyGames': coverage['economyGames'],
            'windows': 0,
            'enough': False,
            'reason': reason,
            'results': coverage['results'],
            'byType': {},
            'patterns': [],
            'phases': [],
        },
        'rows': [],
        'game': None,
        'coverage': coverage,
        'note': note,
        'reason': reason,
    }


def loss_report(facts, *, game=None, opponent=None, date_from=None, date_to=None,
                result=None, limit=80):
    """失利关键链报告（候选事件，不证明因果）。

    返回顶层 ``available/filters/summary/rows/game/coverage/note``（另有 ``reason``）；
    ``rows`` 按损失从大到小（``delta`` 升序）排序后取前 ``limit`` 条，
    ``summary`` 始终按过滤后的全量窗口统计，不受 ``limit`` 影响。
    """
    selected = df.filter_games(facts, game=game, opponent=opponent,
                               date_from=date_from, date_to=date_to, result=result)
    filters = {
        'game': game,
        'opponent': opponent,
        'dateFrom': date_from,
        'dateTo': date_to,
        'result': result,
        'limit': limit,
    }
    try:
        row_limit = max(1, int(limit)) if limit is not None else 80
    except (TypeError, ValueError):
        row_limit = 80

    economy = []
    skipped = []
    contexts = {}
    rows = []
    thresholds = {}
    for item in selected:
        series = _series(item)
        if series is None:
            skipped.append({
                'game': item['id'],
                'label': item.get('label') or '',
                'reason': '缺少经济序列或比赛时长',
            })
            continue
        economy.append((item, series))
        context = contexts.get(item['id'])
        if context is None:
            context = contexts[item['id']] = _context(item)
        windows, threshold = _windows(series)
        thresholds[item['id']] = threshold
        for window in windows:
            rows.append(_build_row(item, series, window, context))

    coverage = _loss_coverage(selected, economy, skipped, rows)
    note = ('经济点按索引均匀铺到时间轴（约 30 秒一个），窗口起止时间为近似值；'
            '关键链只列候选事件、不证明因果；样本 <10 只做观察。')
    note += f' 阈值=max({MIN_DELTA}, 该局 |Δ| P90)，关联范围=窗口 ±{EVIDENCE_WINDOW} 秒。'

    if not selected:
        return _empty_loss(
            filters, coverage,
            reason='当前筛选范围内没有可用对局（需要回放且能判定我方阵营）',
            note=note)
    if not economy:
        return _empty_loss(
            filters, coverage,
            reason=f'已选 {len(selected)} 局均缺少经济序列或比赛时长，无法计算失利窗口',
            note=note)

    rows.sort(key=lambda item: (item['delta'], item['start'], item['game']))
    summary = _loss_summary(rows, economy, _result_counts(selected))

    game_detail = None
    if game:
        wanted = str(game)
        match = next((item for item in selected if item['id'] == wanted), None)
        detail_series = next((series for item, series in economy if item['id'] == wanted), None)
        if match is not None and detail_series is not None:
            game_detail = {
                'id': match['id'],
                'label': match.get('label') or '',
                'date': match.get('date') or '',
                'start': match.get('start') or '',
                'opponentId': match.get('opponentId'),
                'opponentName': match.get('opponentName') or '',
                'ownCamp': match.get('ownCamp'),
                'enemyCamp': match.get('enemyCamp'),
                'result': match.get('result'),
                'duration': _round(detail_series['duration'], 1),
                'series': {
                    'times': list(detail_series['times']),
                    'ownDiff': list(detail_series['ownDiff']),
                    'rawDiff': list(detail_series['rawDiff']),
                    'duration': _round(detail_series['duration'], 1),
                    'approx': True,
                },
                'chains': [row for row in rows if row['game'] == match['id']],
                'threshold': thresholds.get(match['id']),
                'approx': True,
            }

    return {
        'available': True,
        'filters': filters,
        'summary': summary,
        'rows': rows[:row_limit],
        'game': game_detail,
        'coverage': coverage,
        'note': note,
        'reason': None,
    }


# ---------------------------------------------------------------------------
# 优势保持：逐局指标
# ---------------------------------------------------------------------------
def _bucket_of(lead):
    for name, low, high in BUCKETS:
        if low <= lead < high:
            return name
    return '大优'


def _value_safe(seconds, series, duration):
    value = df.value_at(seconds, series, duration)
    return _finite(value)


def _advantage_game(game, series):
    """单局优势保持指标（我方视角，全部标 approx）。"""
    own = series['ownDiff']
    times = series['times']
    duration = series['duration']
    count = len(own)
    step = duration / float(count - 1)

    peak_value = max(own)
    peak_index = own.index(peak_value)
    peak_at = times[peak_index]
    tail = own[peak_index:]
    low_value = min(tail)
    low_index = peak_index + tail.index(low_value)
    low_at = times[low_index]
    drawdown = max(0.0, peak_value - low_value)

    lead_duration = sum(step for index in range(count - 1)
                        if own[index] >= LEAD_THRESHOLD)

    first_lead_index = next((index for index, value in enumerate(own)
                             if value >= SIGNIFICANT_LEAD), None)
    own_objectives = [item for item in df.objective_events(game)
                      if item['camp'] == 'own']
    if first_lead_index is None:
        first_lead_at = None
        next_objective = None
        conversion = None
        post_lead = None
    else:
        first_lead_at = times[first_lead_index]
        next_objective = next((item for item in own_objectives
                               if item['t'] >= first_lead_at - 1e-9), None)
        conversion = (round(next_objective['t'] - first_lead_at, 1)
                      if next_objective is not None else None)
        if duration + 1e-9 >= first_lead_at + CALLBACK_SEC:
            later = _value_safe(first_lead_at + CALLBACK_SEC, own, duration)
            post_lead = (None if later is None
                         else int(round(later - own[first_lead_index])))
        else:
            post_lead = None

    lead_at10 = (_value_safe(LANDMARK_SEC, own, duration)
                 if duration + 1e-9 >= LANDMARK_SEC else None)
    bucket = _bucket_of(lead_at10) if lead_at10 is not None else None
    comeback = bool(peak_value >= SIGNIFICANT_LEAD and game.get('result') == 'loss')

    return {
        'game': game['id'],
        'label': game.get('label') or '',
        'date': game.get('date') or '',
        'opponentId': game.get('opponentId'),
        'opponentName': game.get('opponentName') or '',
        'result': game.get('result'),
        'ownCamp': game.get('ownCamp'),
        'duration': round(duration, 1),
        'samples': count,
        'stepSec': round(step, 1),
        'maxLead': int(round(peak_value)),
        'maxLeadAt': round(peak_at, 1),
        'maxLeadAtClock': df.clock(peak_at),
        'drawdown': int(round(drawdown)),
        'drawdownAt': round(low_at, 1),
        'drawdownAtClock': df.clock(low_at),
        'finalOwnDiff': int(round(own[-1])),
        'leadDurationSec': round(lead_duration, 1),
        'firstLeadAt': round(first_lead_at, 1) if first_lead_at is not None else None,
        'firstLeadAtClock': (df.clock(first_lead_at)
                             if first_lead_at is not None else None),
        'conversionSec': conversion,
        'postLead2mDelta': post_lead,
        'comeback': comeback,
        'leadAt10': int(round(lead_at10)) if lead_at10 is not None else None,
        'leadAt10Bucket': bucket,
        'candidates': _advantage_candidates(game, peak_at, low_at),
        'approx': True,
    }


def _advantage_candidates(game, peak_at, low_at):
    """回撤窗口附近的事件（最多 3 条），只用于提示复核方向。"""
    high = max(peak_at, low_at)
    low = min(peak_at, low_at)
    if high - low < 1e-9:
        high = peak_at + CALLBACK_SEC
    items = []
    for objective in df.objective_events(game):
        if low <= objective['t'] <= high:
            camp = objective['camp']
            text = (f"{df.clock(objective['t'])} 出现{objective['name']}事件（阵营未标注）"
                    if camp == 'unknown'
                    else f"{df.clock(objective['t'])} {_camp_text(camp)}拿到{objective['name']}")
            items.append({'kind': 'objective', 't': objective['t'],
                          'name': objective['name'], 'objectKind': objective['kind'],
                          'camp': camp, 'text': text})
    for fight in df.fight_events(game):
        if low <= fight['startSec'] <= high:
            text = f"{df.clock(fight['startSec'])} 团战"
            if fight.get('killDiff') is not None:
                text += f"我方击杀 {fight.get('ownKills', 0)}:{fight.get('enemyKills', 0)}"
            items.append({'kind': 'fight', 't': fight['startSec'],
                          'killDiff': fight.get('killDiff'), 'text': text})
    for death in df.death_events(game):
        if death['side'] == 'own' and low <= death['t'] <= high:
            items.append({'kind': 'death', 't': death['t'],
                          'hero': death.get('hero') or '',
                          'text': f"{df.clock(death['t'])} 我方{death.get('hero') or '队员'}阵亡"})
    items.sort(key=lambda item: item['t'])
    return items[:MAX_GAME_CANDIDATES]


# ---------------------------------------------------------------------------
# 优势保持：汇总 / 分桶 / 分位带 / 路径
# ---------------------------------------------------------------------------
def _advantage_summary(items):
    led = [item for item in items if item['maxLead'] >= SIGNIFICANT_LEAD]
    comebacks = [item for item in led if item['comeback']]
    led_total = len(led)
    rate = round(len(comebacks) / led_total * 100, 1) if led_total else None
    ci_low, ci_high = df.wilson(len(comebacks), led_total)
    conversion = [item['conversionSec'] for item in items
                  if item['conversionSec'] is not None]
    post = [item['postLead2mDelta'] for item in items
            if item['postLead2mDelta'] is not None]
    lead10 = [item['leadAt10'] for item in items if item['leadAt10'] is not None]
    enough = led_total >= MIN_SAMPLE
    largest = items[0] if items else None
    return {
        'games': len(items),
        'ledGames': led_total,
        'comebacks': len(comebacks),
        'comebackRate': rate,
        'comebackCiLow': _round(ci_low),
        'comebackCiHigh': _round(ci_high),
        'enough': enough,
        'reason': None if enough else
                  f'领先局仅 {led_total} 局（<10），翻盘率与均值只作观察',
        'avgMaxLead': _round(df.mean([item['maxLead'] for item in items])),
        'medianMaxLead': _round(df.median([item['maxLead'] for item in items])),
        'avgDrawdown': _round(df.mean([item['drawdown'] for item in items])),
        'avgLeadDurationSec': _round(df.mean([item['leadDurationSec'] for item in items])),
        'avgConversionSec': _round(df.mean(conversion)),
        'avgPostLead2mDelta': _round(df.mean(post)),
        'avgLeadAt10': _round(df.mean(lead10)),
        'conversionN': len(conversion),
        'conversionMissing': led_total - len(conversion),
        'maxDrawdown': (int(round(largest['drawdown'])) if largest else None),
        'maxDrawdownGame': ({
            'game': largest['game'],
            'label': largest['label'],
            'drawdown': int(round(largest['drawdown'])),
            'maxLead': largest['maxLead'],
            'maxLeadAt': largest['maxLeadAt'],
            'drawdownAt': largest['drawdownAt'],
        } if largest else None),
        'n': {
            'maxLead': len(items),
            'drawdown': len(items),
            'leadDurationSec': len(items),
            'conversionSec': len(conversion),
            'postLead2mDelta': len(post),
            'leadAt10': len(lead10),
        },
        'thresholds': {
            'leadThreshold': LEAD_THRESHOLD,
            'significantLead': SIGNIFICANT_LEAD,
            'landmarkSec': LANDMARK_SEC,
            'callbackSec': CALLBACK_SEC,
        },
    }


def _advantage_buckets(items):
    """十分钟经济差分桶（沿用 analysis_economy.BUCKETS 边界），带 Wilson 区间。"""
    out = []
    for name, low, high in BUCKETS:
        group = [item for item in items
                 if item['leadAt10'] is not None and low <= item['leadAt10'] < high]
        wins = sum(1 for item in group if item['result'] == 'win')
        ci_low, ci_high = df.wilson(wins, len(group))
        out.append({
            'bucket': name,
            'low': low,
            'high': high,
            'n': len(group),
            'wins': wins,
            'winRate': round(wins / len(group) * 100, 1) if group else None,
            'ciLow': _round(ci_low),
            'ciHigh': _round(ci_high),
            'enough': len(group) >= MIN_SAMPLE,
        })
    return out


def _advantage_bands(economy):
    """按分钟 0..min(30, ceil(maxDuration/60)) 的 win/loss/all P25/P50/P75。

    某局没打到该分钟时不计入该档（不把终局值夹到更长的时间点），
    某档 n=0 时三个分位都给 None——页面据此不画线。
    """
    if not economy:
        return [], 0
    durations = [series['duration'] for _, series in economy]
    max_minute = min(MAX_BAND_MINUTE, int(math.ceil(max(durations) / 60.0)))
    groups = {
        'win': [(item, series) for item, series in economy if item.get('result') == 'win'],
        'loss': [(item, series) for item, series in economy if item.get('result') == 'loss'],
        'all': list(economy),
    }
    bands = []
    for minute in range(max_minute + 1):
        seconds = float(minute * 60)
        entry = {'minute': minute, 'seconds': seconds}
        for name in ('win', 'loss', 'all'):
            values = []
            for _, series in groups[name]:
                if series['duration'] + 1e-9 < seconds:
                    continue
                value = _value_safe(seconds, series['ownDiff'], series['duration'])
                if value is not None:
                    values.append(value)
            entry[name] = {
                'n': len(values),
                'p25': _round(df.percentile(values, 25)),
                'p50': _round(df.percentile(values, 50)),
                'p75': _round(df.percentile(values, 75)),
            }
        bands.append(entry)
    return bands, max_minute


def _path_label(next_kind, next_name, tower, result):
    first = ('下一事件：无我方资源/建筑' if next_kind == 'none'
             else f"下一事件：{next_name or '资源/建筑'}")
    second = '推塔' if tower else '未推塔'
    third = {'win': '最终胜', 'loss': '最终负'}.get(result, '结果未知')
    return f'{first} → {second} → {third}'


def _advantage_paths(economy):
    """首次领先 ≥+1000 后的简化路径计数：下一事件 → 是否推塔 → 最终胜负。"""
    groups = {}
    for item, series in economy:
        own = series['ownDiff']
        times = series['times']
        first = next((index for index, value in enumerate(own)
                      if value >= SIGNIFICANT_LEAD), None)
        if first is None:
            continue
        lead_at = times[first]
        own_objectives = [obj for obj in df.objective_events(item)
                          if obj['camp'] == 'own'
                          and obj['t'] >= lead_at - 1e-9]
        next_objective = own_objectives[0] if own_objectives else None
        next_kind = next_objective['kind'] if next_objective is not None else 'none'
        tower = any(obj['kind'] == 'building' for obj in own_objectives)
        result = item.get('result') or 'unknown'
        key = f'{next_kind}|{1 if tower else 0}|{result}'
        group = groups.setdefault(key, {
            'key': key,
            'nextKind': next_kind,
            'nextName': next_objective['name'] if next_objective is not None else None,
            'tower': tower,
            'result': result,
            'n': 0,
            'games': [],
        })
        group['n'] += 1
        group['games'].append({
            'game': item['id'],
            'label': item.get('label') or '',
            'firstLeadAt': round(lead_at, 1),
            'firstLeadAtClock': df.clock(lead_at),
        })

    paths = []
    for group in groups.values():
        group['sequence'] = [
            ('下一事件：无我方资源/建筑' if group['nextKind'] == 'none'
             else f"下一事件：{group['nextName'] or '资源/建筑'}"),
            '推塔' if group['tower'] else '未推塔',
            {'win': '最终胜', 'loss': '最终负'}.get(group['result'], '结果未知'),
        ]
        group['label'] = _path_label(group['nextKind'], group['nextName'],
                                     group['tower'], group['result'])
        group['enough'] = group['n'] >= MIN_PATH_SAMPLE
        group['games'].sort(key=lambda item: item['firstLeadAt'])
        paths.append(group)
    paths.sort(key=lambda item: (-item['n'], item['key']))
    return paths


def _advantage_coverage(selected, economy, skipped, bands_minute=0):
    return {
        'games': len(selected),
        'economyGames': len(economy),
        'skippedGames': len(skipped),
        'skipped': skipped,
        'dateRange': _date_range(selected),
        'results': _result_counts(selected),
        'samples': sum(len(series['ownDiff']) for _, series in economy),
        'bandsMaxMinute': bands_minute,
        'approx': True,
    }


def _empty_advantage(filters, coverage, *, reason, note):
    return {
        'available': False,
        'filters': filters,
        'summary': {
            'games': coverage['games'],
            'economyGames': coverage['economyGames'],
            'ledGames': 0,
            'comebacks': 0,
            'comebackRate': None,
            'enough': False,
            'reason': reason,
            'n': {},
        },
        'buckets': [],
        'bands': [],
        'games': [],
        'paths': [],
        'coverage': coverage,
        'note': note,
        'reason': reason,
    }


def advantage_report(facts, *, opponent=None, date_from=None, date_to=None, result=None):
    """优势保持 / 回撤 / 兑现 / 翻盘报告（我方视角，全部标 approx）。"""
    selected = df.filter_games(facts, opponent=opponent,
                               date_from=date_from, date_to=date_to, result=result)
    filters = {
        'opponent': opponent,
        'dateFrom': date_from,
        'dateTo': date_to,
        'result': result,
    }
    economy = []
    skipped = []
    for item in selected:
        series = _series(item)
        if series is None:
            skipped.append({
                'game': item['id'],
                'label': item.get('label') or '',
                'reason': '缺少经济序列或比赛时长',
            })
            continue
        economy.append((item, series))

    note = ('经济点按索引均匀铺到时间轴（约 30 秒一个），时间与差值均为近似值；'
            '领先/回撤/兑现按我方视角 ownDiff 计算；翻盘率是样本内观察，不证明因果。')
    if not selected:
        coverage = _advantage_coverage(selected, economy, skipped)
        return _empty_advantage(
            filters, coverage,
            reason='当前筛选范围内没有可用对局（需要回放且能判定我方阵营）',
            note=note)
    if not economy:
        coverage = _advantage_coverage(selected, economy, skipped)
        return _empty_advantage(
            filters, coverage,
            reason=f'已选 {len(selected)} 局均缺少经济序列或比赛时长，无法计算优势指标',
            note=note)

    games = [_advantage_game(item, series) for item, series in economy]
    games.sort(key=lambda item: (-item['drawdown'], -item['maxLead'], item['game']))
    summary = _advantage_summary(games)
    buckets = _advantage_buckets(games)
    bands, max_minute = _advantage_bands(economy)
    paths = _advantage_paths(economy)
    coverage = _advantage_coverage(selected, economy, skipped, max_minute)
    if not summary['enough']:
        note += f" 领先局仅 {summary['ledGames']} 局（<10），只做观察。"

    return {
        'available': True,
        'filters': filters,
        'summary': summary,
        'buckets': buckets,
        'bands': bands,
        'games': games,
        'paths': paths,
        'coverage': coverage,
        'note': note,
        'reason': None,
    }
