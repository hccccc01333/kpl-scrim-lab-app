"""官方回放的团队经济序列 → 分析用的时间轴。

营地公开回放只给 ``economy.blue/red`` 两个数组，没有逐点时间戳，采样间隔约 30 秒
（``match.goldIntervalSecApprox``）。这里统一按第 1 个点=30 秒、第 2 个点=60 秒
还原成工作台时间轴，供已入库但缺少录制时间轴的 bundle 兜底。

只读，不写任何文件。
"""
from __future__ import annotations

import json
import math
from pathlib import Path

DEFAULT_INTERVAL = 30


def _number(value):
    if value is None or value == '' or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _interval(normalized):
    value = _number((normalized.get('match') or {}).get('goldIntervalSecApprox'))
    return value if value and value > 0 else DEFAULT_INTERVAL


def series(normalized):
    """返回 ``[{t, blue, red, diff}]``；双方数组按较短的一边对齐。"""
    if not isinstance(normalized, dict):
        return []
    economy = normalized.get('economy') or {}
    blue_values = economy.get('blue') or []
    red_values = economy.get('red') or []
    interval = _interval(normalized)
    points = []
    for index, (blue, red) in enumerate(zip(blue_values, red_values)):
        blue, red = _number(blue), _number(red)
        if blue is None or red is None:
            continue
        points.append({'t': int(round(interval * (index + 1))),
                       'blue': blue, 'red': red, 'diff': blue - red})
    points.sort(key=lambda point: point['t'])
    return points


def timeline(normalized):
    """返回 bundle ``team.timeline`` 使用的 30 秒点形状。"""
    return [{'gameTime': point['t'],
             'blueGold': point['blue'], 'redGold': point['red'],
             'blueKills': None, 'redKills': None,
             'goldDiff': point['diff'], 'source': 'official-30s'}
            for point in series(normalized)]


def diff_points(normalized):
    """返回全景/回放接口使用的 ``[{t, blue, red, diff}]``。"""
    return series(normalized)


def duration_from_bundle(official_dir, bundle):
    """按 bundle 的 ``match.officialReplay.id`` 读官方回放时长（秒）；失败返回 None。

    营地数据包可能缺顶层 ``match.duration``（旧版入库只写了部分字段），
    官方回放 normalized 里的 ``match.durationSec`` 是同一口径（秒）的兜底。
    """
    if not official_dir:
        return None
    replay_id = str(((bundle.get('match') or {}).get('officialReplay') or {}).get('id') or '')
    if not replay_id:
        return None
    path = Path(official_dir) / replay_id / 'normalized.json'
    try:
        normalized = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    seconds = _number((normalized.get('match') or {}).get('durationSec'))
    return int(round(seconds)) if seconds and seconds > 0 else None


def from_bundle(official_dir, bundle):
    """按 bundle 里的 ``match.officialReplay.id`` 读取官方经济；失败返回 []。"""
    if not official_dir:
        return []
    replay_id = str(((bundle.get('match') or {}).get('officialReplay') or {}).get('id') or '')
    if not replay_id:
        return []
    path = Path(official_dir) / replay_id / 'normalized.json'
    try:
        normalized = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    return timeline(normalized)
