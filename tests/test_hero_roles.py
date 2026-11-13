"""英雄能力标签：覆盖、短板与替代建议。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import hero_roles as hr  # noqa: E402


def test_lineup_profile_and_gaps():
    heroes = ['关羽', '妲己', '百里守约', '孙悟空', '钟馗']
    prof = hr.lineup_profile(heroes)
    assert prof['engage'] >= 1
    g = hr.gaps(heroes)
    # 应识别出缺少的维度（如 peel/frontline 可能不足）
    assert isinstance(g, list)
    st = hr.lineup_structure(heroes)
    assert st['heroCount'] == 5
    assert 0 <= st['coverageScore'] <= 1
    assert 'substitutes' in st


def test_unknown_hero_no_crash():
    prof = hr.lineup_profile(['不存在的英雄'])
    assert all(v == 0 for v in prof.values())
    assert hr.coverage_score(['不存在的英雄']) == 0.0


def test_substitutes_exclude():
    subs = hr.substitutes('peel', exclude={'张飞'}, limit=3)
    assert '张飞' not in subs
    assert len(subs) <= 3