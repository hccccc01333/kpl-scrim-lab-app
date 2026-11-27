"""规则中心英雄标签联动：hero_archetypes / grade_rules 实时读 hero_tags.json。

规则中心「英雄标签」保存后回写 resources/hero_tags.json。这里验证：
- 改标签后 archetype_of / subject_for 立刻按新类型判定（mtime 失效，不等重启）；
- 缓存不会因为文件被覆盖而返回旧值；
- 文件缺失 / 损坏时回退静态表，修好后下一次调用即可恢复；
- 五路 12 类的旧写法（法核 → 法刺）继续兼容。
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import grade_rules
import hero_archetypes as ha


def _reset_caches(monkeypatch):
    monkeypatch.setitem(ha._TAGS_CACHE, 'stamp', None)
    monkeypatch.setitem(ha._TAGS_CACHE, 'heroes', None)
    monkeypatch.setitem(grade_rules._HERO_LANE_TYPES_CACHE, 'stamp', None)
    monkeypatch.setitem(grade_rules._HERO_LANE_TYPES_CACHE, 'lanes', None)


def _write(path, heroes):
    path.write_text(json.dumps({'schema': 'scrim-hero-tags-v1', 'heroes': heroes},
                               ensure_ascii=False), encoding='utf-8')


def _bump(path):
    """即使内容长度不变也强制换 mtime，模拟规则中心一次覆盖保存。"""
    stat = path.stat()
    os.utime(path, ns=(stat.st_mtime_ns + 1_000_000, stat.st_mtime_ns + 1_000_000))


def test_archetype_follows_live_tag_change(tmp_path, monkeypatch):
    path = tmp_path / 'hero_tags.json'
    monkeypatch.setattr(ha, '_TAGS_PATH', path)
    _write(path, {'测试英雄': {'defaultLane': '对抗路', 'lanes': {'对抗路': '坦边'}}})
    _reset_caches(monkeypatch)

    assert ha.archetype_of('测试英雄', '对抗路') == '坦边'
    assert ha.default_lane('测试英雄') == '对抗路'
    assert ha.archetype_of('测试英雄') == '坦边'          # 没给分路 → 默认分路
    assert ha.archetype_of('测试英雄', '打野') == '待分类'  # 分路未登记，不猜

    _write(path, {'测试英雄': {'defaultLane': '打野', 'lanes': {'打野': '刺野'}}})
    _bump(path)
    assert ha.archetype_of('测试英雄', '打野') == '刺野'
    assert ha.default_lane('测试英雄') == '打野'
    assert ha.archetype_of('测试英雄') == '刺野'


def test_live_alias_and_new_hero(tmp_path, monkeypatch):
    path = tmp_path / 'hero_tags.json'
    monkeypatch.setattr(ha, '_TAGS_PATH', path)
    _write(path, {'新英雄': {'defaultLane': '中路', 'lanes': {'中路': '法核'}},
                  '清空英雄': {'lanes': {}}})
    _reset_caches(monkeypatch)

    assert ha.archetype_of('新英雄', '中路') == '法刺'      # 老写法归一
    assert ha.archetype_of('新英雄') == '法刺'
    assert ha.archetype_of('清空英雄', '中路') == '待分类'   # 登记了但没有分路类型


def test_static_fallback_when_tags_missing_or_broken(tmp_path, monkeypatch):
    path = tmp_path / 'hero_tags.json'
    monkeypatch.setattr(ha, '_TAGS_PATH', path)
    _reset_caches(monkeypatch)

    assert ha.archetype_of('关羽') == '战边'               # 离线静态表
    assert ha.archetype_of('猪八戒', '打野') == '坦野'
    assert ha.archetype_of('关羽', '游走') == '待分类'

    path.write_text('{ broken', encoding='utf-8')
    assert ha.archetype_of('关羽') == '战边'               # 损坏也回退

    _write(path, {'关羽': {'defaultLane': '对抗路', 'lanes': {'对抗路': '坦边'}}})
    assert ha.archetype_of('关羽') == '坦边'               # 修好后无需重启


def test_rules_center_save_reflected_in_both_readers(tmp_path, monkeypatch):
    """同一次「保存」要同时改到图7的 archetype 和评级主体的坦野/野核。"""
    path = tmp_path / 'hero_tags.json'
    monkeypatch.setattr(ha, '_TAGS_PATH', path)
    monkeypatch.setattr(grade_rules, '_HERO_TAGS_PATH', path)
    _reset_caches(monkeypatch)

    _write(path, {'联动英雄': {'defaultLane': '打野', 'lanes': {'打野': '坦野'}}})
    assert ha.archetype_of('联动英雄', '打野') == '坦野'
    assert grade_rules.subject_for('打野', '联动英雄') == '打野·坦野'

    _write(path, {'联动英雄': {'defaultLane': '打野', 'lanes': {'打野': '战野'}}})
    _bump(path)
    assert ha.archetype_of('联动英雄', '打野') == '战野'
    assert grade_rules.subject_for('打野', '联动英雄') == '打野·野核'


def test_subject_for_falls_back_and_blade_still_wins(tmp_path, monkeypatch):
    path = tmp_path / 'hero_tags.json'
    monkeypatch.setattr(grade_rules, '_HERO_TAGS_PATH', path)
    _reset_caches(monkeypatch)

    assert grade_rules.subject_for('打野', '未知英雄') == '打野·野核'
    _write(path, {'未知英雄': {'lanes': {'打野': '坦野'}}})
    assert grade_rules.subject_for('打野', '未知英雄') == '打野·坦野'

    # 本局打野刀优先于实时标签（原口径不变）
    assert grade_rules.subject_for('打野', '未知英雄', {'blade': {'kind': 'core'}}) == '打野·野核'
