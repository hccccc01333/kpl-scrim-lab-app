"""坐标定标：把回放的相对坐标映射到 0–1 地图空间。

营地回放给的是同一张地图上的相对坐标（本批 x/y 大致在 ±60 内）。
官方没有给地图边界，所以用**数据自身的稳健边界**定标：
  取全部位置点的 1% 与 99% 分位作为 x/y 的上下界，
  再把点线性映射到 [0,1]；距离一律换算成「地图对角线的比例」。

局限（页面上必须写明）：
- 边界来自本批数据，不是官方地图尺寸；换地图或换版本要重新定标。
- 分位裁剪会丢掉极少数贴边点，这些点会被夹到 0 或 1。
"""
from __future__ import annotations

import json
import math
from pathlib import Path

CALIBRATION_FILE = 'map_calibration.json'


def _percentile(values, ratio):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * ratio
    low = int(math.floor(position))
    high = min(len(ordered) - 1, low + 1)
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def scan_points(replays_dir, *, limit_games=None):
    """采样全部回放位置点；返回 (xs, ys, games)。"""
    xs, ys = [], []
    games = 0
    for folder in sorted(Path(replays_dir).glob('camp-*')):
        if limit_games is not None and games >= limit_games:
            break
        path = folder / 'positions.json'
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        touched = False
        for player in payload.get('players') or []:
            for point in player.get('posArr') or []:
                if not isinstance(point, (list, tuple)) or len(point) < 2:
                    continue
                x, y = point[0], point[1]
                if x == 0 and y == 0:
                    continue
                xs.append(float(x))
                ys.append(float(y))
                touched = True
        if touched:
            games += 1
    return xs, ys, games


def compute(replays_dir, *, low=0.01, high=0.99):
    xs, ys, games = scan_points(replays_dir)
    if not xs or not ys:
        return {'calibrated': False, 'reason': '没有可用的位置点'}
    bounds = {
        'xMin': round(_percentile(xs, low), 2),
        'xMax': round(_percentile(xs, high), 2),
        'yMin': round(_percentile(ys, low), 2),
        'yMax': round(_percentile(ys, high), 2),
    }
    width = bounds['xMax'] - bounds['xMin']
    height = bounds['yMax'] - bounds['yMin']
    return {
        'calibrated': width > 0 and height > 0,
        'bounds': bounds,
        'width': round(width, 2),
        'height': round(height, 2),
        'diagonal': round(math.hypot(width, height), 2),
        'points': len(xs),
        'games': games,
        'percentiles': [low, high],
        'source': 'derived:positions',
        'note': '边界取自本批回放位置点的 1%–99% 分位，不是官方地图尺寸。',
    }


def save(calibration, target_dir):
    path = Path(target_dir) / CALIBRATION_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(calibration, ensure_ascii=False, indent=2), encoding='utf-8')
    return path


def load(target_dir):
    path = Path(target_dir) / CALIBRATION_FILE
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def normalize(point, calibration):
    """把绝对坐标映射到 0–1；未定标或点为空返回 None。"""
    if not calibration or not calibration.get('calibrated') or point is None:
        return None
    bounds = calibration['bounds']
    width = bounds['xMax'] - bounds['xMin']
    height = bounds['yMax'] - bounds['yMin']
    if width <= 0 or height <= 0:
        return None
    u = (point[0] - bounds['xMin']) / width
    v = (point[1] - bounds['yMin']) / height
    return (min(1.0, max(0.0, u)), min(1.0, max(0.0, v)))


def unit_distance(a, b):
    """两个 0–1 坐标的欧氏距离，单位为「地图宽度」。"""
    if a is None or b is None:
        return None
    return math.hypot(a[0] - b[0], a[1] - b[1])
