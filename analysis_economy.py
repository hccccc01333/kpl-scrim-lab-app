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
    for game in games:
        if game['win'] is None:
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
        'landmark': landmark,
        'rows': rows,
        'buckets': summary,
        'overall': {'n': overall_n, 'wins': overall_w,
                    'winRate': round(overall_w / overall_n * 100, 1) if overall_n else None},
        'note': '只算有胜负、且十分钟有采样点的局；样本 <10 只给观察，不给转化率结论。',
    }
