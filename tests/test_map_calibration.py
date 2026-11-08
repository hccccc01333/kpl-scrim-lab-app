"""坐标定标：分位边界、归一化与距离。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import map_calibration as mc  # noqa: E402


def write_positions(tmp_path, points):
    folder = tmp_path / 'replays' / 'camp-1'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'positions.json').write_text(json.dumps({
        'players': [{'playerId': 'p1', 'posArr': points}]
    }), encoding='utf-8')
    return tmp_path / 'replays'


def test_bounds_from_percentiles(tmp_path):
    points = [[-10, -10]] * 50 + [[10, 10]] * 50
    calibration = mc.compute(write_positions(tmp_path, points))
    assert calibration['calibrated'] is True
    assert calibration['bounds']['xMin'] == -10.0
    assert calibration['bounds']['xMax'] == 10.0
    assert calibration['points'] == 100


def test_normalize_maps_to_unit_square(tmp_path):
    points = [[-10, -10], [0, 0], [10, 10]]
    calibration = mc.compute(write_positions(tmp_path, points))
    assert mc.normalize((-10, -10), calibration) == (0.0, 0.0)
    assert mc.normalize((10, 10), calibration) == (1.0, 1.0)
    middle = mc.normalize((0, 0), calibration)
    assert middle == (0.5, 0.5)


def test_normalize_clamps_outliers(tmp_path):
    points = [[-10, -10], [10, 10]]
    calibration = mc.compute(write_positions(tmp_path, points))
    x, y = mc.normalize((100, -100), calibration)
    assert x == 1.0 and y == 0.0


def test_unit_distance():
    assert mc.unit_distance((0, 0), (0.3, 0.4)) == 0.5
    assert mc.unit_distance(None, (0, 0)) is None


def test_no_points_is_not_calibrated(tmp_path):
    calibration = mc.compute(write_positions(tmp_path, []))
    assert calibration['calibrated'] is False
    assert mc.normalize((0, 0), calibration) is None


def test_roundtrip_save_load(tmp_path):
    calibration = mc.compute(write_positions(tmp_path, [[-5, -5], [5, 5]]))
    mc.save(calibration, tmp_path)
    assert mc.load(tmp_path)['bounds'] == calibration['bounds']
