"""首次安装补种：新机器开箱就有组合 / 克制 / 阵容标签 / 评级规则 / KPL 事实表。

回归背景：3.0.1 安装包只带代码与 resources/，data/ 是空骨架。演示机上英雄标签
在（resources/hero_tags.json 随包），其余规则全都空——因为内置种子只在代码里、
或依赖未随包发布的 data/facts 事实表。
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bp_facts  # noqa: E402
import builtin_seed  # noqa: E402
import combo_pool  # noqa: E402
import counter_library  # noqa: E402
import grade_rules  # noqa: E402
import lineup_tags  # noqa: E402


@pytest.fixture
def facts(tmp_path, monkeypatch):
    target = tmp_path / 'facts'
    monkeypatch.setattr(bp_facts, 'FACTS', target)
    return target


def test_ensure_all_seeds_every_config(facts):
    report = builtin_seed.ensure_all()
    for name in builtin_seed.FACT_FILES:
        assert (facts / name).is_file(), name
    for name in ('combo_pool.json', 'lineup_tags.json', 'grade_rules.json',
                 'counter_library.json', 'rules_counters.json',
                 'rules_combos.json', 'rules_lineup_tags.json'):
        assert (facts / name).is_file(), name
        assert name in report['seeded']
    # 落盘后这些配置就是「已保存」，命中判定 / 评级会真正消费它们。
    assert combo_pool.has_saved()
    assert len(combo_pool.tables()[0]) > 0
    assert counter_library.table()
    assert len(grade_rules.load()['subjects']['游走']) == len(grade_rules.FIELDS)
    assert len(lineup_tags.load()['tags']) == len(lineup_tags.DEFAULT_TAGS)
    counters = json.loads((facts / 'rules_counters.json').read_text(encoding='utf-8'))
    assert counters['heroPairs'] and counters['comboPairs']
    # 外部口径的原始语料也要随包补种：KPL 逐局 BP + 巅峰千强日线 / 对位分片。
    assert (facts.parent / 'kpl' / 'bp_games.jsonl').is_file()
    assert (facts.parent / 'peak' / 'hero_daily.parquet').is_file()
    assert (facts.parent / 'peak' / 'matchup_raw').is_dir()
    assert any((facts.parent / 'peak' / 'matchup_raw').iterdir())
    # 离线英雄名缓存：没它 hero_catalog 一进复盘就要连官网。
    assert (facts.parent / 'hero_list.json').is_file()
    assert (facts.parent / 'kpl' / 'manifest.json').is_file()


def test_ensure_all_is_idempotent_and_never_overwrites(facts):
    builtin_seed.ensure_all()
    sentinel = {'schema': combo_pool.SCHEMA, 'revision': 99,
                'pairs': [{'id': 'mine', 'heroes': ['钟馗', '小乔'], 'strength': 'strong'}],
                'trios': []}
    (facts / 'combo_pool.json').write_text(
        json.dumps(sentinel, ensure_ascii=False), encoding='utf-8')
    report = builtin_seed.ensure_all()
    assert 'combo_pool.json' in report['skipped']
    assert combo_pool.load()['revision'] == 99
    assert combo_pool.load()['pairs'] == sentinel['pairs']


def test_seed_files_are_shipped():
    sys.path.insert(0, str(ROOT / 'scripts'))
    from make_release import ship_files  # noqa: E402
    shipped = set(ship_files())
    for name in builtin_seed.FACT_FILES:
        assert f'resources/builtin/facts/{name}' in shipped
    for _, seed in builtin_seed.SEEDED_CONFIGS:
        assert f'resources/builtin/configs/{seed}' in shipped
    assert 'resources/builtin/kpl/bp_games.jsonl' in shipped
    assert 'resources/builtin/peak/hero_daily.parquet' in shipped
    assert 'resources/builtin/misc/hero_list.json' in shipped
    assert 'resources/builtin/misc/manifest.json' in shipped
    # peak_crawl 依赖 scripts/build_bp_facts.py：漏了它自动爬取整段静默失效。
    for name in ('scripts/build_bp_facts.py', 'scripts/crawl_kpl_bp.py',
                 'scripts/backfill_kpl_draft_events.py'):
        assert name in shipped
