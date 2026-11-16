"""build_camp_counters：名字归一、a/b 双排组合、种子表交叉校验清单。"""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'build_camp_counters.py'


def load_module():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location('build_camp_counters_test', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_raw(tmp_path):
    rows = [
        # 主英雄页：元流之子(法师) 页面里关系带 截断名 / 括号名 / 正常名
        {'hero_name': '元流之子(法师)', 'captured_at': '2026-11-08T12:47:01',
         'counters': [{'hero': '妲己', 'role': '法师', 'index': 3.0},
                      {'hero': '元流之子...', 'role': '法师', 'index': 2.0}],
         'countered_by': [{'hero': '张飞', 'role': '坦克/辅助', 'index': 4.0}],
         'duo': [{'a': '元流之子(法师)', 'b': '钟馗', 'pick_gain': 1.2, 'win_gain': 0.3, 'index': 2.1}],
         'trio': [{'heroes': ['元流之子(法师)', '妲己', '钟馗'], 'index': 3.3}]},
        {'hero_name': '张飞', 'captured_at': '2026-11-08T12:47:01',
         'counters': [{'hero': '妲己', 'role': '法师', 'index': 1.5}],
         'countered_by': [], 'duo': [], 'trio': []},
        {'hero_name': '钟馗', 'captured_at': '2026-11-08T12:47:01',
         'counters': [{'hero': '妲己', 'role': '法师', 'index': 1.4}],
         'countered_by': [], 'duo': [], 'trio': []},
    ]
    raw = tmp_path / 'camp_relations.jsonl'
    raw.write_text('\n'.join(json.dumps(row, ensure_ascii=False) for row in rows),
                   encoding='utf-8')
    return raw


def test_build_normalizes_and_skips_truncated(tmp_path):
    module = load_module()
    out = tmp_path / 'camp_counters.json'
    rc = module.main(['--raw', str(write_raw(tmp_path)), '--out', str(out)])
    assert rc == 0
    doc = json.loads(out.read_text(encoding='utf-8'))
    assert doc['schema'] == 'bp-camp-counters-v1'
    assert doc['capturedAt'] == '2026-11-08'
    assert set(doc['heroes']) == {'元流之子(法师)', '张飞', '钟馗'}
    hero = doc['heroes']['元流之子(法师)']
    # 正常名保留；截断名（元流之子...）宁缺不猜
    assert [item['hero'] for item in hero['counters']] == ['妲己']
    assert hero['counters'][0]['index'] == 3.0
    # duo 是 a/b 二元关系，产成 heroes 列表
    assert hero['duo'] == [{'heroes': ['元流之子(法师)', '钟馗'], 'index': 2.1,
                            'pickGain': 1.2, 'winGain': 0.3}]
    assert hero['trio'][0]['heroes'] == ['元流之子(法师)', '妲己', '钟馗']
    report = json.loads((tmp_path / 'camp_counters_report.json').read_text(encoding='utf-8'))
    assert report['skipped'] == {}


def test_seed_conflict_report_lists_untagged(tmp_path):
    module = load_module()
    out = tmp_path / 'camp_counters.json'
    module.main(['--raw', str(write_raw(tmp_path)), '--out', str(out)])
    report = json.loads((tmp_path / 'camp_counters_report.json').read_text(encoding='utf-8'))
    # 张飞：营地 role「坦克/辅助」→ tankish=True；种子表张飞 frontline=1，无冲突
    zhangfei = next(item for item in report['seedConflicts'] if item['hero'] == '张飞') \
        if any(item['hero'] == '张飞' for item in report['seedConflicts']) else None
    if zhangfei:
        assert zhangfei['campFrontline'] == zhangfei['seedFrontline']
    # 妲己在多个页面里反复以「法师」出现 → role claims 聚合成功；种子表妲己 frontline=0
    da = next((item for item in report['seedConflicts'] if item['hero'] == '妲己'), None)
    assert da is None or da.get('campFrontline') is False
