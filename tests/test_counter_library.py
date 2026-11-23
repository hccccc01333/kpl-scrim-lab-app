"""自家克制库：KPL 初稿、教练删改、与营地数据分源、指向训练赛。"""
import json

import pytest

import bp_facts
import config_history
import counter_library


@pytest.fixture
def facts_dir(tmp_path, monkeypatch):
    facts = tmp_path / 'facts'
    facts.mkdir()
    monkeypatch.setattr(bp_facts, 'FACTS', facts)
    return facts


def _write_kpl(facts, pairs, **meta):
    doc = {'schema': 'bp-kpl-counters-v1', 'source': 'kpl-official',
           'games': 100, 'pairs': pairs}
    doc.update(meta)
    (facts / 'kpl_counters.json').write_text(json.dumps(doc, ensure_ascii=False), encoding='utf-8')


def test_empty_library_when_never_saved(facts_dir):
    doc = counter_library.load()
    assert doc['schema'] == counter_library.SCHEMA
    assert doc['saved'] is False
    assert doc['scope'] == 'training'
    assert doc['pairs'] == []
    assert counter_library.has_saved() is False
    assert counter_library.table() == {}
    assert counter_library.hit('赵云', '百里守约') is None


def test_build_draft_uses_kpl_hit_threshold(facts_dir):
    _write_kpl(facts_dir, [
        {'a': '赵云', 'b': '百里守约', 'n': 12, 'wins': 7, 'wr': 58.3},   # 命中
        {'a': '百里守约', 'b': '赵云', 'n': 12, 'wins': 5, 'wr': 41.7},   # 不命中
        {'a': '墨子', 'b': '达摩', 'n': 6, 'wins': 4, 'wr': 66.7},        # 样本不足
        {'a': '武则天', 'b': '芈月', 'n': 30, 'wins': 15, 'wr': 50.0},    # 胜率不足
    ])
    draft = counter_library.build_draft(version='2026秋')
    assert draft['source'] == 'kpl-draft'
    assert draft['version'] == '2026秋'
    assert [p['a'] for p in draft['pairs']] == ['赵云']
    pair = draft['pairs'][0]
    assert pair['b'] == '百里守约' and pair['wr'] == 58.3 and pair['n'] == 12
    assert pair['source'] == 'kpl-draft' and pair['trainingMatches'] == []
    assert draft['draftFrom']['file'] == 'kpl_counters.json'
    # 生成初稿不落盘：未保存前不参与命中判定
    assert counter_library.has_saved() is False


def test_build_draft_falls_back_to_editable_empty_library(facts_dir):
    draft = counter_library.build_draft()
    assert draft['source'] == 'empty'
    assert draft['pairs'] == []
    assert 'kpl_counters.json' in draft['sourceNote']


def test_save_validates_bumps_and_records_history(facts_dir):
    doc = counter_library.load()
    doc['pairs'] = [{'id': 'p1', 'a': '大师', 'b': '守约', 'source': 'manual',
                     'trainingMatches': ['m1']}]
    saved = counter_library.save(doc)
    assert saved['revision'] == 1
    assert saved['pairs'][0]['a'] == '鲁班大师'           # 简称归一化
    assert saved['pairs'][0]['b'] == '百里守约'
    assert saved['pairs'][0]['trainingMatches'] == ['m1']
    assert counter_library.load()['saved'] is True
    assert config_history.list_entries('counter_library')[0]['summary']

    # 重复对 / 相同英雄 / trainingMatches 非数组 → 拒绝
    bad = dict(saved)
    bad['pairs'] = [{'a': '铠', 'b': '铠'}]
    with pytest.raises(ValueError):
        counter_library.save(bad)


def test_hit_is_own_source_and_separate_from_camp(facts_dir):
    doc = counter_library.load()
    doc['pairs'] = [{'id': 'p1', 'a': '赵云', 'b': '百里守约', 'source': 'manual'}]
    counter_library.save(doc)

    own = counter_library.hit('赵云', '百里守约')
    assert own['source'] == 'own' and own['verdict'] == '我方克制'
    assert own['a'] == '赵云' and own['b'] == '百里守约'
    assert counter_library.hit('百里守约', '赵云') is None   # 有向，不会反向命中


def test_regenerate_overwrites_and_keeps_rollback_snapshot(facts_dir):
    _write_kpl(facts_dir, [{'a': '赵云', 'b': '百里守约', 'n': 12, 'wins': 7, 'wr': 58.3}])
    manual = counter_library.load()
    manual['pairs'] = [{'id': 'p1', 'a': '墨子', 'b': '达摩', 'source': 'manual'}]
    counter_library.save(manual)

    saved = counter_library.regenerate(version='2026冬')
    assert saved['version'] == '2026冬' and saved['source'] == 'kpl-draft'
    assert [(p['a'], p['b']) for p in saved['pairs']] == [('赵云', '百里守约')]
    assert saved['revision'] == 2
    # 旧库留在历史里可回滚
    snapshot = config_history.get_snapshot('counter_library',
                                           config_history.list_entries('counter_library')[0]['id'])
    assert snapshot['pairs'][0]['a'] == '墨子'


def test_link_match_points_pair_to_training_match(facts_dir):
    doc = counter_library.load()
    doc['pairs'] = [{'id': 'p1', 'a': '赵云', 'b': '百里守约', 'source': 'manual'}]
    counter_library.save(doc)
    updated = counter_library.link_match('赵云', '百里守约', 'train-2026-001')
    updated = counter_library.link_match('赵云', '百里守约', 'train-2026-001')  # 去重
    counter_library.save(updated, bump=False)
    assert counter_library.table()[('赵云', '百里守约')]['trainingMatches'] == ['train-2026-001']
