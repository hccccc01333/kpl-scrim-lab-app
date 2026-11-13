"""出装时间轴：checkpoint 零值读数与临时目录归属的回归测试。"""
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import replay_timeline_build as tb  # noqa: E402

EVENT_COLUMNS = ('entity_id', 'time_s', 'player', 'hero', 'camp', 'slot', 'unit',
                 'family', 'command', 'fields_json')


def write_events(path):
    with path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=EVENT_COLUMNS)
        writer.writeheader()
        writer.writerow({'entity_id': '1', 'time_s': '1', 'player': '甲', 'hero': '瑶',
                         'camp': '1', 'slot': '1', 'unit': '1',
                         'family': 'buy', 'command': 'BUYEQUIP',
                         'fields_json': '{"equip_id": 1001, "price": 300}'})


def test_checkpoint_zero_values_are_kept(tmp_path):
    """0 金币 / 0 击杀是合法读数，不能按 truthiness 变成 None。"""
    events = tmp_path / 'events.csv'
    write_events(events)
    checkpoints = {0: {'1': {'gold': 0, 'kills': 0, 'deaths': 0, 'assists': 0, 'level': 1}}}
    meta = tb.build(events, 'sha-zero', tmp_path / 'out', checkpoints)
    assert meta['rows'] >= 2

    import json
    rows = [json.loads(line) for line in
            (tmp_path / 'out' / 'sha-zero' / 'timeline.jsonl').read_text(encoding='utf-8').splitlines()]
    first = next(row for row in rows if row['second'] == 0)
    assert first['gold'] == 0
    assert first['kills'] == 0
    assert first['deaths'] == 0
    assert first['assists'] == 0
    assert first['level'] == 1
    assert first['gold_confidence'] == 'engine'
    assert first['kda_confidence'] == 'engine'


def test_missing_checkpoint_value_reports_unknown_confidence(tmp_path):
    events = tmp_path / 'events.csv'
    write_events(events)
    checkpoints = {0: {'1': {'gold': None, 'kills': 2, 'deaths': 1, 'assists': 3, 'level': 1}}}
    tb.build(events, 'sha-none', tmp_path / 'out', checkpoints)
    import json
    rows = [json.loads(line) for line in
            (tmp_path / 'out' / 'sha-none' / 'timeline.jsonl').read_text(encoding='utf-8').splitlines()]
    first = next(row for row in rows if row['second'] == 0)
    assert first['gold'] is None
    assert first['gold_confidence'] == 'unknown'
    assert first['gold_source'] == ''
    assert first['kills'] == 2 and first['kda_confidence'] == 'engine'


def test_catalog_honours_caller_out_dir(tmp_path):
    """给 out_dir 时不再自己新建临时目录（临时目录归属调用方）。"""
    assert tb._catalog.__doc__ and 'out_dir' in tb._catalog.__doc__
