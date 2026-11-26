"""赛训组评级规则：内置默认、保存/读取、乐观锁、评级判定、字段取值、打野主体映射。"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bp_facts  # noqa: E402
import grade_rules  # noqa: E402


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(bp_facts, 'FACTS', tmp_path)
    return tmp_path


def test_default_doc_fields_real(isolated):
    doc = grade_rules.load()
    assert doc['revision'] == 0
    subjects = doc['subjects']
    assert '游走' in subjects and '打野·坦野' in subjects and '打野·野核' in subjects
    # 真实口径：控制时长按秒、治疗按经济转治疗比值、死亡按次；不再有"分均控制/分均治疗"
    assert subjects['游走']['control_time']['unit'] == '秒'
    assert subjects['游走']['gold_to_heal']['label'] == '经济转治疗'
    assert subjects['游走']['deaths']['unit'] == '次'
    assert 'healing' not in subjects['游走']
    assert 'control' not in subjects['游走']
    assert not grade_rules.has_saved()
    assert not (isolated / grade_rules.FILENAME).exists()


def test_all_rules_have_source_key_unit(isolated):
    doc = grade_rules.load()
    for subject, fields in doc['subjects'].items():
        for field, rule in fields.items():
            assert rule['source'] in ('player', 'tile'), (subject, field)
            assert rule['key'], (subject, field)
            assert rule['unit'], (subject, field)
            assert rule['direction'] in ('up', 'down')
            assert len(rule['thresholds']) == 3


def test_save_and_read_saved(isolated):
    doc = grade_rules.load()
    doc['subjects']['游走']['participation']['thresholds'] = [90, 80, 70]
    saved = grade_rules.save(doc)
    assert saved['revision'] == 1
    assert saved['updatedAt']
    assert grade_rules.has_saved()
    again = grade_rules.read_saved()
    assert again['subjects']['游走']['participation']['thresholds'] == [90, 80, 70]


def test_up_direction_grade(isolated):
    doc = grade_rules.load()
    assert grade_rules.grade('游走', 'participation', 85, doc)['level'] == 'elite'
    assert grade_rules.grade('游走', 'participation', 75, doc)['level'] == 'good'
    assert grade_rules.grade('游走', 'participation', 65, doc)['level'] == 'pass'
    assert grade_rules.grade('游走', 'participation', 40, doc)['level'] == 'low'
    assert grade_rules.grade('游走', 'participation', 80, doc)['label'] == '卓越'


def test_down_direction_grade(isolated):
    doc = grade_rules.load()
    assert grade_rules.grade('游走', 'deaths', 1, doc)['level'] == 'elite'
    assert grade_rules.grade('游走', 'deaths', 3, doc)['level'] == 'good'
    assert grade_rules.grade('游走', 'deaths', 4, doc)['level'] == 'pass'
    assert grade_rules.grade('游走', 'deaths', 6, doc)['level'] == 'low'


def test_grade_none_and_invalid(isolated):
    doc = grade_rules.load()
    assert grade_rules.grade('游走', 'participation', None, doc) is None
    assert grade_rules.grade('游走', 'participation', 'abc', doc) is None
    assert grade_rules.grade('游走', 'unknown_field', 100, doc) is None
    assert grade_rules.grade('不存在', 'participation', 100, doc) is None
    assert grade_rules.grade('游走', 'participation', 80) is None  # 未保存不过口径


def test_field_value_player_and_tile(isolated):
    doc = grade_rules.load()
    player = {
        'participation': 62.5, 'deaths': 4, 'gold': 8500, 'damage': 44000,
        'taken': 125000, 'minutes': 15.2,
        'campTiles': [
            {'key': 'control_time', 'value': 24.0, 'unit': 's'},
            {'key': 'vision', 'value': 70.0},
        ],
    }
    assert grade_rules.field_value(player, doc['subjects']['游走']['participation']) == 62.5
    assert grade_rules.field_value(player, doc['subjects']['游走']['control_time']) == 24.0
    assert grade_rules.field_value(player, doc['subjects']['游走']['vision']) == 70.0
    # 缺卡返回 None
    assert grade_rules.field_value(player, doc['subjects']['游走']['gold_to_heal']) is None
    # gpm 现算
    gpm = grade_rules.field_value(player, doc['subjects']['对抗路']['gpm'])
    assert gpm and abs(gpm - 8500 / 15.2) < 0.01


def test_subject_for_jungle_blade(isolated):
    assert grade_rules.subject_for('打野', player={'blade': {'kind': 'tank'}}) == '打野·坦野'
    assert grade_rules.subject_for('打野', player={'blade': {'kind': 'core'}}) == '打野·野核'
    assert grade_rules.subject_for('打野') == '打野·野核'
    assert grade_rules.subject_for('游走') == '游走'
    assert grade_rules.subject_for('中路') == '中路'
    assert grade_rules.subject_for('未知') == ''


def test_invalid_doc_rejected(isolated):
    bad = {'schema': grade_rules.SCHEMA, 'revision': 1,
           'subjects': {'游走': {'deaths': {'direction': 'sideways', 'thresholds': [1, 2, 3]}}}}
    with pytest.raises(ValueError):
        grade_rules.save(bad)


def test_every_subject_lists_all_fields_with_active(isolated):
    """设置页要列全字段；只有原本配过的默认勾选，其余列出但默认不生效。"""
    doc = grade_rules.load()
    for subject in grade_rules.SUBJECT_LABELS:
        fields = doc['subjects'][subject]
        assert set(fields) == set(grade_rules.FIELDS)
        assert all(isinstance(rule['active'], bool) for rule in fields.values())
        on = {key for key, rule in fields.items() if rule['active']}
        assert on == set(grade_rules._DEFAULT_SUBJECTS.get(subject) or {})


def test_inactive_field_does_not_grade(isolated):
    doc = grade_rules.load()
    doc['subjects']['游走']['kills']['active'] = False
    assert grade_rules.grade('游走', 'kills', 5, doc) is None
    doc['subjects']['游走']['kills']['active'] = True
    assert grade_rules.grade('游走', 'kills', 5, doc) is not None


def test_old_saved_doc_is_normalized_to_full_fields(isolated):
    """老存档只有几个字段：读取后自动补齐，老字段默认生效、新字段默认不生效。"""
    old = {
        'schema': grade_rules.SCHEMA, 'revision': 2, 'updatedAt': '',
        'subjects': {'游走': {'participation': {
            'label': '参团率', 'unit': '%', 'direction': 'up', 'source': 'player',
            'key': 'participation', 'thresholds': [88, 77, 66],
        }}},
    }
    (isolated / grade_rules.FILENAME).write_text(
        __import__('json').dumps(old, ensure_ascii=False), encoding='utf-8')
    doc = grade_rules.load()
    fields = doc['subjects']['游走']
    assert set(fields) == set(grade_rules.FIELDS)
    assert fields['participation']['thresholds'] == [88, 77, 66]
    assert fields['participation']['active'] is True
    assert fields['kills']['active'] is False
    assert grade_rules.grade('游走', 'participation', 80, doc)['level'] == 'good'


def test_save_roundtrip_keeps_active_flags(isolated):
    doc = grade_rules.load()
    doc['subjects']['对抗路']['vision']['active'] = True
    saved = grade_rules.save(doc)
    assert saved['subjects']['对抗路']['vision']['active'] is True
    assert grade_rules.read_saved()['subjects']['对抗路']['vision']['active'] is True

