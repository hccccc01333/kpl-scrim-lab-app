"""赛训组自定义组合池：内置默认、优先级覆盖、API 读写。"""
import json

import pytest

import bp_facts
import combo_pool


@pytest.fixture
def pool_dir(tmp_path, monkeypatch):
    facts = tmp_path / 'facts'
    facts.mkdir()
    monkeypatch.setattr(bp_facts, 'FACTS', facts)
    return facts


def test_builtin_defaults_are_normalized_and_complete(pool_dir):
    # 用隔离目录，避免赛训组已保存的组合池（41 对）干扰「内置默认 42 对」的断言。
    pairs = combo_pool.rows(2)
    trios = combo_pool.rows(3)
    assert len(pairs) == 42
    assert len(trios) == 1
    assert set(trios[0]['heroes']) == {'鲁班大师', '元流之子(坦克)', '司空震'}
    assert trios[0]['name'] == '流星锤组合'
    # Excel 简称已归一化到英雄库标准名
    names = {h for row in pairs + trios for h in row['heroes']}
    assert '大师' not in names and '鲁班大师' in names
    assert '元坦' not in names and '元流之子(坦克)' in names
    assert '猫咪' not in names and '沈梦溪' in names


def test_unsaved_pool_does_not_override_kpl(pool_dir):
    """没点保存之前，内置默认只用于展示，不影响命中口径。"""
    assert combo_pool.has_saved() is False
    pairs, trios = combo_pool.tables()
    assert pairs == {} and trios == {}


def test_saved_pool_overrides_kpl_index(pool_dir):
    doc = combo_pool.load()
    doc['pairs'] = [{'id': 'p1', 'heroes': ['钟馗', '小乔'], 'strength': 'weak'}]
    doc['trios'] = []
    combo_pool.save(doc, bump=False)

    assert combo_pool.has_saved() is True
    pairs, trios = combo_pool.tables()
    assert ('小乔', '钟馗') in pairs
    assert pairs[('小乔', '钟馗')]['strength'] == 'weak'

    own = ['钟馗', '小乔', '宫本武藏', '吕布', '张良']
    detail = {'ownCamp': 'blue', 'draft': {'picks': {
        'left': [{'name': h} for h in own], 'right': []}}, 'players': []}
    facts = bp_facts.for_match(detail)
    hit = facts['kpl']['pairs'][0]
    assert set(hit['heroes']) == {'钟馗', '小乔'}
    assert hit['source'] == 'custom'
    assert hit['strength'] == 'weak'


def test_new_trio_not_in_kpl_does_not_crash(pool_dir):
    """新建三人体系（KPL 事实表没收录）不能让整局 bpFacts 崩成 None。

    回归：trio_hits 曾直接下标 trow['wr']，overlay 行没这个键会 KeyError，
    被 serve.py 的宽泛 except 吞掉，整局组合/赛事分析静默消失。
    """
    trio = ['鲁班大师', '元流之子(坦克)', '司空震']
    doc = combo_pool.load()
    doc['pairs'] = []
    doc['trios'] = [{'id': 't1', 'heroes': trio, 'name': '流星锤组合'}]
    combo_pool.save(doc, bump=False)

    own = trio + ['吕布', '张良']
    detail = {'ownCamp': 'blue', 'draft': {'picks': {
        'left': [{'name': h} for h in own], 'right': []}}, 'players': []}
    facts = bp_facts.for_match(detail)          # 不应抛异常
    hit = facts['kpl']['trios'][0]
    assert set(hit['heroes']) == set(trio)
    assert hit['source'] == 'custom'
    assert hit['name'] == '流星锤组合'
    assert hit['wr'] is None                    # KPL 没背景，留空而不是崩
    assert hit['n'] == 0


def test_save_bumps_revision_and_rejects_bad_shape(pool_dir):
    doc = combo_pool.load()
    saved = combo_pool.save(doc)
    assert saved['revision'] == doc['revision'] + 1
    assert combo_pool.load()['revision'] == saved['revision']

    with pytest.raises(ValueError):
        combo_pool.save({'schema': combo_pool.SCHEMA, 'pairs': [{'heroes': ['钟馗']}], 'trios': []})


def test_save_roundtrip_with_revision(pool_dir):
    """设置页保存流程：GET 拿到内置默认，POST 保存后 revision 递增。"""
    first = combo_pool.load()
    assert len(first['pairs']) == 42

    incoming = {'schema': combo_pool.SCHEMA, 'revision': first['revision'],
                'updatedAt': first['updatedAt'],
                'pairs': first['pairs'] + [
                    {'id': 'px', 'heroes': ['张良', '虞姬'], 'strength': 'strong'}],
                'trios': first['trios']}
    saved = combo_pool.save(incoming)
    assert saved['revision'] == first['revision'] + 1
    assert len(combo_pool.load()['pairs']) == 43

    # 旧 revision 再来一次会被乐观锁挡住（API 层据此返回 409）
    assert combo_pool.load()['revision'] != first['revision']
