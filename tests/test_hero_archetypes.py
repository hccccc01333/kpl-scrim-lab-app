"""hero_archetypes 单元测试：工作簿导入版分类表结构与按分路取类型的语义。

词表与口径见 docs/team_dossier_p0.md §1；「待确认」副分路不入表、落「待分类」。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import hero_archetypes as ha


def test_lane_archetype_groups_cover_five_lanes():
    assert list(ha.LANE_ARCHETYPES) == list(ha.LANES)
    assert len(ha.LANES) == 5
    assert ha.LANE_ARCHETYPES['对抗路'] == ('战边', '坦边')
    assert ha.LANE_ARCHETYPES['打野'] == ('刺野', '战野', '坦野')
    assert ha.LANE_ARCHETYPES['中路'] == ('工具人', '法核')
    assert ha.LANE_ARCHETYPES['发育路'] == ('游射', '呆射')
    assert ha.LANE_ARCHETYPES['游走'] == ('开团辅', '保护辅', '功能辅')


def test_every_registered_archetype_is_in_its_lane_group():
    for hero, lanes in ha.HERO_ARCHETYPES.items():
        assert lanes, hero
        for lane, archetype in lanes.items():
            assert lane in ha.LANES, (hero, lane)
            assert archetype in ha.LANE_ARCHETYPES[lane], (hero, lane, archetype)
        # 第一个分路必须在该分路词表内（默认分路语义）
        first = next(iter(lanes))
        assert first in ha.LANES and lanes[first] in ha.LANE_ARCHETYPES[first]


def test_meta_covers_all_heroes():
    # 133 英雄档案全部入类型表（12 类精简版不再有默认待细分占位）
    assert len(ha.HERO_LABEL_META) == len(ha.HERO_ARCHETYPES) == 133
    assert ha.HERO_LABEL_META['元流之子(射手)']['confidence'] == '待复核'
    assert ha.archetype_of('元流之子(射手)', '发育路') == '游射'


def test_default_lane_is_first_registered_lane():
    assert ha.default_lane('关羽') == '对抗路'
    assert ha.default_lane('猪八戒') == '对抗路'   # 工作簿默认；打野为已确认副分路
    assert ha.default_lane('墨子') == '中路'
    assert ha.default_lane('曜') == '打野'
    assert ha.default_lane('不存在的英雄') is None


def test_archetype_uses_actual_lane_first():
    assert ha.archetype_of('猪八戒', '打野') == '坦野'      # 已确认副分路
    assert ha.archetype_of('猪八戒', '对抗路') == '坦边'
    assert ha.archetype_of('项羽', '游走') == '开团辅'      # 已确认副分路
    # 分路未知时退回默认分路
    assert ha.archetype_of('关羽') == '战边'
    assert ha.archetype_of('曜') == '战野'
    # 未收录英雄归「待分类」，不猜
    assert ha.archetype_of('不存在的英雄', '中路') == '待分类'


def test_unconfirmed_side_lane_returns_pending_instead_of_wrong_type():
    # 工作簿标「待按实际分路及版本确认」的副分路不入表：出现即「待分类」
    assert ha.archetype_of('关羽', '游走') == '待分类'
    assert ha.archetype_of('元歌', '发育路') == '待分类'
    assert ha.archetype_of('盾山', '对抗路') == '待分类'


def test_describe_shape_and_known_flag():
    row = ha.describe('公孙离', '发育路')
    assert row == {'hero': '公孙离', 'lane': '发育路', 'archetype': '游射', 'known': True}
    row = ha.describe('公孙离')
    assert row['lane'] == '发育路'
    row = ha.describe('元流之子(射手)', '发育路')
    assert row['known'] is True and row['archetype'] == '游射'
    row = ha.describe('不存在的英雄')
    assert row['known'] is False and row['archetype'] == '待分类'


def test_taxonomy_metadata():
    meta = ha.taxonomy()
    assert meta['lanes'] == list(ha.LANES)
    assert meta['groups']['对抗路'] == ['战边', '坦边']
    assert meta['other'] == '待分类'
    assert meta['note']
    # 五路 12 类精简版：本局词典与默认词表一致，不再保留角色型细类
    assert meta['gameTypes'] == meta['groups']
