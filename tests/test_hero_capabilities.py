"""hero_capabilities 单元测试：19 维能力矩阵、阵容功能标签与九维兼容映射。

口径见 docs/team_dossier_p0.md §1.2；「双核」不由能力标签派生，本模块不得输出。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import hero_capabilities as hc
import hero_roles


def test_capability_matrix_covers_all_heroes():
    import hero_archetypes
    assert len(hc.HERO_CAPABILITIES) == 133
    assert set(hc.HERO_CAPABILITIES) == set(hero_archetypes.HERO_LABEL_META)


def test_capability_vector_shape():
    vector = hc.capability_of('廉颇')
    assert set(vector) == set(hc.CAPABILITIES)
    assert all(v in (0, 1) for v in vector.values())
    assert vector['前排'] == 1 and vector['爆发'] == 0
    # 未收录英雄全 0，不猜
    assert all(v == 0 for v in hc.capability_of('不存在的英雄').values())


def test_lineup_capabilities_sum():
    total = hc.lineup_capabilities(['廉颇', '项羽'])
    assert total['前排'] == 2 and total['开团'] == 2
    assert hc.lineup_capabilities([]) == {c: 0 for c in hc.CAPABILITIES}
    assert hc.lineup_capabilities(None) == {c: 0 for c in hc.CAPABILITIES}


def test_functional_tags_rules():
    # 双前排 + 强开团 + 保护链
    tags = hc.functional_tags(['廉颇', '项羽', '王昭君', '公孙离', '张飞'])
    assert '双前排' in tags and '强开团' in tags and '保护链' in tags
    assert '双核' not in tags  # 双核是资源口径，绝不由能力标签派生
    # 无前排（负面标签）
    assert '无前排' in hc.functional_tags(['妲己', '安琪拉', '公孙离', '孙尚香', '小乔'])
    # 清线转线：沈梦溪/干将莫邪/女娲/王昭君 均带清线
    assert '清线转线' in hc.functional_tags(['沈梦溪', '干将莫邪', '女娲', '王昭君', '孙尚香'])
    assert hc.functional_tags([]) == []


def test_hero_roles_compat_mapping():
    compat = hc.hero_roles_compat('张飞')
    assert set(compat) == set(hero_roles.CAPABILITIES)
    assert compat['engage'] == 1 and compat['peel'] == 1
    assert compat['burst'] == 0 and compat['sustained'] == 0
    # 未收录英雄全 0
    assert all(v == 0 for v in hc.hero_roles_compat('不存在的英雄').values())
