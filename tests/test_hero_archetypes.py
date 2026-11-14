"""hero_archetypes 单元测试：分类表结构与按分路取类型的语义。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import hero_archetypes as ha


def test_lane_archetype_groups_cover_five_lanes():
    assert list(ha.LANE_ARCHETYPES) == list(ha.LANES)
    assert len(ha.LANES) == 5
    assert ha.LANE_ARCHETYPES['对抗路'] == ('战边', '坦边', '带线边')
    assert ha.LANE_ARCHETYPES['打野'] == ('刺客野', '坦野', '蓝领野')
    assert ha.LANE_ARCHETYPES['中路'] == ('法核', '工具人', '法刺', '功能中单')
    assert ha.LANE_ARCHETYPES['发育路'] == ('呆射', '游射', '功能射')
    assert ha.LANE_ARCHETYPES['游走'] == ('开团辅', '保护辅', '功能辅')


def test_every_registered_archetype_is_in_its_lane_group():
    for hero, lanes in ha.HERO_ARCHETYPES.items():
        assert lanes, hero
        for lane, archetype in lanes.items():
            assert lane in ha.LANES, (hero, lane)
            assert archetype in ha.LANE_ARCHETYPES[lane], (hero, lane, archetype)


def test_default_lane_is_first_registered_lane():
    assert ha.default_lane('关羽') == '对抗路'
    assert ha.default_lane('猪八戒') == '打野'
    assert ha.default_lane('墨子') == '游走'
    assert ha.default_lane('不存在的英雄') is None


def test_archetype_uses_actual_lane_first():
    assert ha.archetype_of('猪八戒', '打野') == '坦野'
    assert ha.archetype_of('猪八戒', '对抗路') == '坦边'
    assert ha.archetype_of('关羽', '游走') == '开团辅'
    # 分路未知时退回默认分路
    assert ha.archetype_of('关羽') == '战边'
    # 未收录英雄归「其他」，不猜
    assert ha.archetype_of('不存在的英雄', '中路') == '其他'


def test_unregistered_lane_returns_other_instead_of_wrong_type():
    # 元歌只登记对抗路；出现在发育路时不能标成带线边
    assert ha.archetype_of('元歌', '发育路') == '其他'
    assert ha.archetype_of('海诺', '对抗路') == '其他'


def test_describe_shape_and_known_flag():
    row = ha.describe('公孙离', '发育路')
    assert row == {'hero': '公孙离', 'lane': '发育路', 'archetype': '游射', 'known': True}
    row = ha.describe('公孙离')
    assert row['lane'] == '发育路'
    row = ha.describe('不存在的英雄')
    assert row['known'] is False and row['archetype'] == '其他'


def test_taxonomy_metadata():
    meta = ha.taxonomy()
    assert meta['lanes'] == list(ha.LANES)
    assert meta['groups']['中路'] == ['法核', '工具人', '法刺', '功能中单']
    assert meta['other'] == '其他'
    assert meta['note']
