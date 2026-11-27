"""打野评级主体映射：全项目必须是同一套口径。

本局打野刀优先，拿不到才退回英雄在打野位上的静态标签；同一个英雄换出装
要能换主体，英雄默认分路不能盖过打野位标签。
"""
import json
from pathlib import Path

import grade_rules
import kpl_bp

ROOT = Path(__file__).resolve().parents[1]
HERO_TAGS = json.loads((ROOT / 'resources' / 'hero_tags.json').read_text(encoding='utf-8'))
LANES = {name: item.get('lanes') or {} for name, item in HERO_TAGS['heroes'].items()}


def test_blade_overrides_hero_tag():
    # 梦奇静态打野标签是坦野，但本局红刀 → 野核。
    assert grade_rules.subject_for('打野', '梦奇', {'blade': {'kind': 'core'}}, LANES) == '打野·野核'
    # 大司命静态是战野，本局肉刀 → 坦野。
    assert grade_rules.subject_for('打野', '大司命', {'blade': {'kind': 'tank'}}, LANES) == '打野·坦野'


def test_hero_tag_fallback_without_blade():
    assert grade_rules.subject_for('打野', '梦奇', None, LANES) == '打野·坦野'
    assert grade_rules.subject_for('打野', '大司命', None, LANES) == '打野·野核'
    # 阿古朵的 compat 不是「坦野」，但打野位标签是，必须按标签走。
    assert grade_rules.subject_for('打野', '阿古朵', None, LANES) == '打野·坦野'


def test_lazy_hero_tags_same_result():
    assert grade_rules.subject_for('打野', '梦奇') == '打野·坦野'
    assert grade_rules.subject_for('打野', '大司命') == '打野·野核'


def test_accepts_both_hero_tag_shapes():
    # hero_tags.json 原形态（带 lanes 层）
    raw = {'梦奇': {'lanes': {'打野': '坦野'}}}
    # _icon_metadata()['heroTypes'] 形态（已剥 lanes 层）
    flat = {'梦奇': {'打野': '坦野'}}
    assert grade_rules.subject_for('打野', '梦奇', None, raw) == '打野·坦野'
    assert grade_rules.subject_for('打野', '梦奇', None, flat) == '打野·坦野'


def test_subject_key_passthrough_and_plain_lane():
    assert grade_rules.subject_for('打野·坦野') == '打野·坦野'
    assert grade_rules.subject_for('打野·野核') == '打野·野核'
    assert grade_rules.subject_for('中路', '不知火舞') == '中路'
    assert grade_rules.subject_for('游走') == '游走'
    assert grade_rules.subject_for('未知分路') == ''


def test_kpl_baseline_uses_same_fallback():
    lane = kpl_bp._baseline_lane({'position': '打野', 'hero': '梦奇'}, LANES)
    assert lane == '打野·坦野'
    assert lane == grade_rules.subject_for('打野', '梦奇', None, LANES)
